#  Copyright (c) 2023. Charles Hymes
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.
#
# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#

"""
Registers the plug-in "StabDiffAuto1111" as a thin API client for Automatic1111's StableDiffusion API. A port of
ArtBit's Stable-GimpFusion.

 See ... gimp/devel-docs/GIMP3-plug-in-porting-guide/removed_functions.md etcetera.
"""

import base64
# gi is the python module for PyGObject. It is a Python package which provides bindings for GObject based libraries such
# as GTK, GStreamer, WebKitGTK, GLib, GIO and many more. See https://gnome.pages.gitlab.gnome.org/pygobject/
import gi
import json
import os
import random
import re
import site
import sys
import tempfile
import urllib

gi.require_version('Gimp', '3.0')  # noqa: E402
gi.require_version('GimpUi', '3.0')  # noqa: E402
gi.require_version("Gtk", "3.0")  # noqa: E402
gi.require_version('Gdk', '3.0')  # noqa: E402
from enum import Enum, auto
# noinspection PyUnresolvedReferences
from gi.repository import Gdk, Gio, Gimp, GimpUi, Gtk, GLib, GObject, Gegl
from urllib.request import urlopen
from urllib.parse import urlencode
from urllib import error
from sd_gui_utils import *

# layer_index from layer_combo_box.get_active() is 2 more than it should be!
# Does LayerComboBox have a bug? Are there 2 invisible elements before the ones shown?
LAYER_INDEX_CORRECTION: int = 2


class SubjectType(Enum):
    CHANNEL = auto()
    DRAWABLE = auto()
    IMAGE = auto()
    LAYER = auto()
    LAYER_MASK = auto()
    SELECTION = auto()
    TEXT_LAYER = auto()


class StabDiffAuto1111(Gimp.PlugIn):
    """
    This is a Gimp python plugin that allows you to augment your painting using Automatic1111's
    StableDiffusion Web-UI API from your local StableDiffusion server.  This is re-write port of ArtBit's
    Stable-GimpFusion plug-in.

    CONSTANTS:
    --------
    PYTHON_PLUGIN_NAME,
    PYTHON_PLUGIN_UUID_STRING,
    PYTHON_PLUGIN_NAME_LONG,
    VERSION,
    PLUGIN_VERSION_URL,
    PLUGIN_MENU_LABEL,
    HOME,
    LIMB_IMAGE_MENU_NAME,
    LIMB_LAYERS_MENU_NAME,
    MAX_BATCH_SIZE
    """
    DEBUG: bool = False

    # With GIMP 2.99, site-packages is <GIMP_INSTALL_DIR>/lib/python<PYTHON_VERSION>/site-packages
    # For example, L:/bin/GIMP 2.99/lib/python3.11/site-packages
    PYTHON_PLUGIN_NAME: str = "StabDiffAuto1111"
    PYTHON_PLUGIN_UUID_STRING: str = "6470ee6c-ad2d-4ec1-92a9-9465048d859f"
    PYTHON_PLUGIN_NAME_LONG: str = PYTHON_PLUGIN_NAME + "_" + PYTHON_PLUGIN_UUID_STRING
    VERSION: float = 0.8
    # This odd looking string is actually the most robust form of file URI on Windows.
    PLUGIN_VERSION_URL: str = "https://gist.github.com/Charlweed/1e13ec25d0a22ac2837f127539874743/raw"
    PLUGIN_MENU_LABEL: str = "_StabDiffAuto1111"  # Mnemonics work here.
    HOME: str = os.path.expanduser('~')
    LIMB_IMAGE_MENU_NAME: str = "<Image>/StableDiffusionAuto1111"
    LIMB_LAYERS_MENU_NAME: str = "<Layers>/StableDiffusionAuto1111"
    MAX_BATCH_SIZE: int = 20
    FORMAT = "[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s"
    LOGGER = logging.getLogger(__name__)
    logging.basicConfig(format=FORMAT, level="DEBUG")
    LOGGER.setLevel(logging.DEBUG)
    MESSAGE_REGISTRATION = "Registering " + __file__ + ":" + PYTHON_PLUGIN_NAME
    MESSAGE_REGISTRATION_COMPETED = __file__ + ":" + PYTHON_PLUGIN_NAME + " returned."

    # Procedure names.
    PYTHON_PROCEDURE_CONFIG_GLOBAL = PYTHON_PLUGIN_NAME + "-global"
    PYTHON_PROCEDURE_CONFIG_MODEL = PYTHON_PLUGIN_NAME + "-change-model"
    PYTHON_PROCEDURE_CONTROLNET_LAYER = PYTHON_PLUGIN_NAME + "-controlnet-layer"
    PYTHON_PROCEDURE_CONTROLNET_LAYER_CONTEXT = PYTHON_PLUGIN_NAME + "-controlnet-layer-context"
    PYTHON_PROCEDURE_IMG2IMG = PYTHON_PLUGIN_NAME + "-img2img"
    PYTHON_PROCEDURE_IMG2IMG_CONTEXT = PYTHON_PLUGIN_NAME + "-img2img-context"
    PYTHON_PROCEDURE_INPAINTING = PYTHON_PLUGIN_NAME + "-inpainting"
    PYTHON_PROCEDURE_INPAINTING_CONTEXT = PYTHON_PLUGIN_NAME + "-inpainting-context"
    PYTHON_PROCEDURE_LAYER_INFO = PYTHON_PLUGIN_NAME + "-layer-info"
    PYTHON_PROCEDURE_LAYER_INFO_CONTEXT = PYTHON_PLUGIN_NAME + "-layer-info-context"
    PYTHON_PROCEDURE_TEXT2IMG = PYTHON_PLUGIN_NAME + "-text2img"
    PYTHON_PROCEDURE_TEXT2IMG_CONTEXT = PYTHON_PLUGIN_NAME + "-text2img-context"

    PYTHON_PROCEDURE_NAMES = [
        PYTHON_PROCEDURE_CONFIG_GLOBAL,
        PYTHON_PROCEDURE_CONFIG_MODEL,
        PYTHON_PROCEDURE_CONTROLNET_LAYER,
        PYTHON_PROCEDURE_CONTROLNET_LAYER_CONTEXT,
        PYTHON_PROCEDURE_IMG2IMG,
        PYTHON_PROCEDURE_IMG2IMG_CONTEXT,
        PYTHON_PROCEDURE_INPAINTING,
        PYTHON_PROCEDURE_INPAINTING_CONTEXT,
        PYTHON_PROCEDURE_LAYER_INFO,
        PYTHON_PROCEDURE_LAYER_INFO_CONTEXT,
        PYTHON_PROCEDURE_TEXT2IMG,
        PYTHON_PROCEDURE_TEXT2IMG_CONTEXT
    ]

    # There is overlap with settings, except that POPULATOR_RESPONSES are optional, volatile, and specific to the
    # latest values from each populator. The first string is the name of the populator, the second string is the key
    # in a key/value pair. For example "add_components_controlnet_options" : {"cn1_layer": "control_net_layer_tr3b"}
    POPULATOR_RESPONSES: Dict[str, Dict[str, Any]] = {}

    STABLE_DIFF_AUTO1111_DEFAULT_SETTINGS = {
        "api_base": "http://127.0.0.1:7860",
        "batch_size": 1,
        "cfg_scale": 7.5,
        "cn_models": [],
        "denoising_strength": 0.8,
        "height": 512,
        "is_server_running": False,
        "mask_blur": 4,
        "model": "",
        "models": [],
        "negative_prompt": "",
        "prompt": "",
        "sampler_name": "Euler a",
        "sd_model_checkpoint": None,
        "seed": -1,
        "steps": 50,
        "width": 512
    }

    RESIZE_MODES = {
        "Just Resize": 0,
        "Crop And Resize": 1,
        "Resize And Fill": 2,
        "Just Resize (Latent Upscale)": 3
    }

    CONTROL_MODES = {
        "Balanced": 0,
        "My prompt is more important": 1,
        "ControlNet is more important": 2,
    }

    SAMPLERS = [
        "Euler a",
        "Euler",
        "LMS",
        "Heun",
        "DPM2",
        "DPM2 a",
        "DPM++ 2S a",
        "DPM++ 2M",
        "DPM++ SDE",
        "DPM fast",
        "DPM adaptive",
        "LMS Karras",
        "DPM2 Karras",
        "DPM2 a Karras",
        "DPM++ 2S a Karras",
        "DPM++ 2M Karras",
        "DPM++ SDE Karras",
        "DDIM"
    ]

    CONTROLNET_RESIZE_MODES = [
        "Just Resize",
        "Scale to Fit (Inner Fit)",
        "Envelope (Outer Fit)",
    ]

    CONTROLNET_MODULES = [
        "none",
        "canny",
        "depth",
        "depth_leres",
        "hed",
        "mlsd",
        "normal_map",
        "openpose",
        "openpose_hand",
        "clip_vision",
        "color",
        "pidinet",
        "scribble",
        "fake_scribble",
        "segmentation",
        "binary"
    ]

    CONTROLNET_DEFAULT_SETTINGS = {
        "input_image": "",
        "mask": "",
        "module": "none",
        "model": "none",
        "weight": 1.0,
        "resize_mode": "Scale to Fit (Inner Fit)",
        "lowvram": False,
        "processor_res": 64,
        "threshold_a": 64,
        "threshold_b": 64,
        "guidance": 1.0,
        "guidance_start": 0.0,
        "guidance_end": 1.0,
        "control_mode": 0,
    }

    GENERATION_MESSAGES = [
        "Making happy little pixels...",
        "Fetching pixels from a digital art museum...",
        "Waiting for bot-painters to finish...",
        "Waiting for the prompt to bake...",
        "Fetching random pixels from the internet",
        "Taking a random screenshot from an AI dream",
        "Throwing pixels at screen and seeing what sticks",
        "Converting random internet comment to RGB values",
        "Computer make pretty picture, you happy.",
        "Computer is hand-painting pixels...",
        "Turning the Gimp knob up to 11...",
        "Pixelated dreams come true, thanks to AI.",
        "AI is doing its magic...",
        "Pocket Picasso is speed-painting...",
        "Instant Rembrandt! Well, relatively instant...",
        "Doodle buddy is doing its thing...",
        "Waiting for the digital paint to dry..."
    ]

    @staticmethod
    def _(message_text):
        return GLib.dgettext(None, message_text)  # This is a terrible idiom.

    @staticmethod
    def check_update():
        try:
            # TODO: Gimp.PDB.get_data is deprecated. Find replacement.
            """
/**
 * gimp_is_canonical_identifier:
 * @identifier: The identifier string to check.
 *
 * Checks if @identifier is canonical and non-%NULL.
 *
 * Canonical identifiers are e.g. expected by the PDB for procedure
 * and parameter names. Every character of the input string must be
 * either '-', 'a-z', 'A-Z' or '0-9'.
 *
 * Returns: %TRUE if @identifier is canonical, %FALSE otherwise.
 *
 * Since: 3.0
 **/            
            """
            Gimp.PDB.get_data("update-checked")
            update_checked = True
        except Exception as ex:  # noqa
            update_checked = False

        if update_checked is False:
            try:
                response = urlopen(StabDiffAuto1111.PLUGIN_VERSION_URL)
                data = response.read()
                data = json.loads(data)
                Gimp.PDB.set_data("update-checked", "0.8")

                if StabDiffAuto1111.VERSION < int(data["version"]):
                    Gimp.message(data["message"])
            except Exception as ex:
                ignored = ex  # noqa

    @classmethod
    def assert_imagery_args(cls, image_in: Gimp.Image, n_drawables: int, drawables, verbose: bool = False):
        if image_in:
            if verbose:
                message = "image argument = \"%s\"" % image_in.get_name()
                cls.LOGGER.debug(message)
        else:
            complaint = "missing image_in argument"
            cls.LOGGER.error(complaint)
            raise ValueError(complaint)
        if n_drawables:
            if verbose:
                message = "n_drawables argument = \"%d\"" % n_drawables
                cls.LOGGER.debug(message)
        else:
            complaint = "missing n_drawables argument"
            cls.LOGGER.error(complaint)  # No raise
        if drawables:
            n: int = 0
            for subject_drawable in drawables:
                if verbose:
                    message = "drawables[%d] argument = \"%s\"" % (n, subject_drawable.get_name())
                    cls.LOGGER.debug(message)
                n += 1
        else:
            complaint = "missing drawables argument"
            cls.LOGGER.error(complaint)
            raise ValueError(complaint)

    @classmethod
    def get_layer_info(cls, subject_layer: Gimp.Layer) -> str:
        """ Show any layer info associated with the active layer """
        data = cls.LayerData(subject_layer).data
        layer_name = subject_layer.get_name()
        json_str = json.dumps(data, sort_keys=True, indent=2)
        message: str = "Layer %s has the following associated data:\n%s" % (layer_name, json_str)
        return message

    @classmethod
    def write_layer_info(cls, subject_layer: Gimp.Layer):
        layer_json_text: str = cls.get_layer_info(subject_layer=subject_layer)
        Gimp.message(layer_json_text)

    def get_layer_as_base64(self, layer):
        # store active_layer
        subject_image: Gimp.Image = layer.get_image()
        active_layer = subject_image.list_layers()[0]
        copy = StabDiffAuto1111.LayerLocal(self, layer).copy().insert()
        result = copy.to_base64()
        copy.remove()
        # restore active_layer
        # Gimp.Image.set_active_layer(active_layer.image, active_layer)
        subject_image.active_layer = active_layer
        return result

    def get_layer_mask_as_base64(self, layer):
        selection: Gimp.Selection = layer.get_image().get_selection()
        # This makes little sense. Why get the selection from an image, then supply the image to the selection as
        # an argument?
        # Currently, some_bool is undocumented.
        some_bool, non_empty, x1, y1, x2, y2 = selection.bounds(layer.get_image())
        # Currently, some_bool and non_empty, are both booleans
        # StabDiffAuto1111.LOGGER.debug("some_bool from selection.bounds is %r" % some_bool)
        # StabDiffAuto1111.LOGGER.debug("non_empty from selection.bounds is %r" % non_empty)
        mask_perhaps = layer.get_mask()  # Docs say this returns -1. It currently returns None instead
        if non_empty:

            # selection to base64

            # store active_layer
            active_layer = layer.get_image().list_layers()[0]  # I am sceptical that this gets the "active_layer"

            # selection to file
            # disable=pdb.gimp_image_undo_disable(layer.get_image())
            tmp_layer = StabDiffAuto1111.LayerLocal.create(self, layer.get_image(),
                                                           "mask",
                                                           layer.get_image().get_width(),
                                                           layer.get_image().get_height(),
                                                           Gimp.ImageType.RGBA_IMAGE,
                                                           100, Gimp.LayerMode.NORMAL)
            tmp_layer.add_selection_as_mask().insert()

            result = tmp_layer.mask_to_base64()
            tmp_layer.remove()
            # enable = pdb.gimp_image_undo_enable(layer.get_image())

            # restore active_layer
            subject_image: Gimp.Image = active_layer.get_image()
            subject_image.set_selected_layers([active_layer])  # NOTE: docs say 2 arguments
            return result
        elif mask_perhaps and (not mask_perhaps == -1):
            StabDiffAuto1111.LOGGER.debug("Empty selection, but layer.get_mask() returned something.")
            mp_type = type(mask_perhaps)
            mp_type_name = mp_type.name
            StabDiffAuto1111.LOGGER.debug("mp_type_name = %s" % mp_type_name)
            StabDiffAuto1111.LOGGER.debug("mask_perhaps ≈ %s" % str(mask_perhaps))
            # mask to file
            tmp_layer = StabDiffAuto1111.LayerLocal(layer)
            return tmp_layer.mask_to_base64()
        else:
            # StabDiffAuto1111.LOGGER.debug("Empty selection, and layer.get_mask() returned None or -1.")
            return ""

    def get_control_net_params(self, cn_layer: Gimp.Layer):
        if cn_layer:
            if not isinstance(cn_layer, Gimp.Layer):
                raise ValueError("cn_layer argument must be a Gimp.Layer, not a %s" % type(cn_layer).__name__)
            layer = StabDiffAuto1111.LayerLocal(self, cn_layer)
            data = layer.load_data(StabDiffAuto1111.CONTROLNET_DEFAULT_SETTINGS)
            # ControlNet image size need to be in multiples of 64
            layer64 = layer.copy().insert().resize_to_multiple_of(64)
            data.update({"input_image": layer64.to_base64()})
            if cn_layer.get_mask():
                data.update({"mask": layer64.mask_to_base64()})
            layer64.remove()
            return data
        return None

    class MyShelf:
        """ GimpShelf is not available at init time, so we keep our persistent data in a json file """
        def assert_settings_available(self):
            if self.data is None:
                raise ValueError("Data is unset")
            if self.data is None:
                raise ValueError("No data available")
            if "api_base" not in self.data:
                raise ValueError("api_base value unavailable.")

        def __init__(self, default_shelf={}):  # noqa
            self.data: Dict = None  # noqa
            self.file_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'stable_diffusion_auto1111.json')
            self.load(default_shelf)

        def load(self, default_shelf={}):  # noqa
            self.data = default_shelf
            try:
                if os.path.isfile(self.file_path):
                    StabDiffAuto1111.LOGGER.debug("Loading shelf from %s" % self.file_path)
                    with open(self.file_path, "r") as f:
                        self.data = json.load(f)
                    StabDiffAuto1111.LOGGER.info("Successfully loaded shelf from %s" % self.file_path)
                else:
                    StabDiffAuto1111.LOGGER.warning("Did not find %s" % self.file_path)
            except Exception as e:  # noqa
                StabDiffAuto1111.LOGGER.exception("Error reading %s" % self.file_path)

        def save(self, data={}):  # noqa
            try:
                self.data.update(data)
                StabDiffAuto1111.LOGGER.info("Saving shelf to %s" % self.file_path)
                with open(self.file_path, "w") as f:
                    json.dump(self.data, f, indent=2, sort_keys=True)
                StabDiffAuto1111.LOGGER.info("Successfully saved shelf to %s" % self.file_path)

            except Exception as e:
                StabDiffAuto1111.LOGGER.exception(e)

        def get(self, name, default_value=None):
            if name in self.data:
                return self.data[name]
            return default_value

        def set(self, name, default_value=None):
            self.data[name] = default_value
            self.save()

        def __str__(self):
            if self.data:
                string_rep = json.dumps(self.data, indent=2, sort_keys=True)
            else:
                string_rep = "{}"
            return string_rep

    class TempFiles:
        def __init__(self):
            self.files = []

        def get(self, filename):
            self.files.append(filename)
            return r"{}".format(os.path.join(tempfile.gettempdir(), filename))

        def remove_all(self):
            try:
                unique_list = (list(set(self.files)))
                for tmp_file in unique_list:
                    if os.path.exists(tmp_file):
                        os.remove(tmp_file)
            except Exception as ex:
                ignored = ex  # noqa

    class ApiClient:
        """ Simple API client used to interface with StableDiffusion JSON endpoints """
        @staticmethod
        def save_timestamped_json(json_bytes: bytes, sample: bool):
            if sample:
                infix = "_sample_"
            else:
                infix = "_"
            try:
                import time
                timestamp = str(int(time.time()))
                post_file_name = tempfile.gettempdir() + "/stabdiffauto1111_post" + infix + timestamp + ".json"
                logging.warning("json file will be \"%s\"" % post_file_name)
                with open(post_file_name, "wb") as json_text_file:
                    json_text_file.write(json_bytes)
                    logging.warning("Wrote json \"%s\"" % post_file_name)
            except Exception as ex:  # noqa
                StabDiffAuto1111.LOGGER.exception("Exception forming and writing JSON")

        @staticmethod
        def save_dict_as_json(some_dict, sample: bool):
            if some_dict is None:
                raise ValueError("save_dict_as_json(some_dict): Required argument some_dict is None")
            if some_dict is None:
                logging.warning("save_dict_as_json(some_dict): Required argument some_dict is empty.")
            json_str: str = json.dumps(some_dict, sort_keys=True, indent=2)
            json_bytes: bytes = json_str.encode('utf-8')
            StabDiffAuto1111.ApiClient.save_timestamped_json(json_bytes, sample)

        def __init__(self, base_url):
            self.base_url = None
            self.set_base_url(base_url)

        def set_base_url(self, base_url):
            self.base_url = base_url

        def post(self, endpoint, dict_in={}, params={}, headers=None):  # noqa
            try:
                url = self.base_url + endpoint + "?" + urllib.parse.urlencode(params)
                StabDiffAuto1111.LOGGER.warning("POST %s" % url)

                if StabDiffAuto1111.DEBUG:
                    StabDiffAuto1111.ApiClient.save_dict_as_json(dict_in, True)
                # NOTE: In the original code, the string returned by json.dumps is sent directly to urllib2.Request.
                # That changes in urllib.request.Request, where the data parameter specifies "bytes"
                json_str: str = json.dumps(dict_in, sort_keys=True, indent=2)
                json_bytes: bytes = json_str.encode('utf-8')

                if StabDiffAuto1111.DEBUG:
                    StabDiffAuto1111.ApiClient.save_timestamped_json(json_bytes, False)
                    StabDiffAuto1111.LOGGER.debug('post data %s', json_bytes)

                headers = headers or {"Content-Type": "application/json", "Accept": "application/json"}
                request_out = urllib.request.Request(url=url, data=json_bytes, headers=headers)
                response = urlopen(request_out)
                response_json_str = response.read()
                response_dict = json.loads(response_json_str)

                # StabDiffAuto1111.LOGGER.debug('response: %s', data)
                return response_dict
            except urllib.error.HTTPError as ex:
                StabDiffAuto1111.LOGGER.exception("ERROR: ApiClient.post()")
                message = "url=%s, code=%d, reason=%s" % (ex.url, ex.code, ex.reason)
                StabDiffAuto1111.LOGGER.error(message)
                StabDiffAuto1111.LOGGER.error(str(ex.headers))

        def get(self, endpoint, params={}, headers=None):  # noqa
            if StabDiffAuto1111.skip_a1111:
                return
            try:
                url = self.base_url + endpoint + "?" + urllib.parse.urlencode(params)
                StabDiffAuto1111.LOGGER.debug("POST %s" % url)
                headers = headers or {"Content-Type": "application/json", "Accept": "application/json"}
                request_out = urllib.request.Request(url=url, headers=headers)
                response = urlopen(request_out)
                data = response.read()
                data = json.loads(data)
                return data
            except urllib.error.HTTPError as ex:
                StabDiffAuto1111.LOGGER.exception("ERROR: ApiClient.get")
                message = "url=%s, code=%d, reason=%s" % (ex.url, ex.code, ex.reason)
                StabDiffAuto1111.LOGGER.error(message)
                StabDiffAuto1111.LOGGER.error(str(ex.headers))

    class LayerData:
        def __init__(self, layer, defaults=None):
            self.data = None
            if defaults is None:
                defaults = {}
            self.name = 'stabdiffauto1111'
            self.layer = layer
            self.image = layer.get_image()
            self.defaults = defaults
            self.had_parasite = False
            self.load()

        def load(self):
            parasite = self.layer.get_parasite(self.name)
            if parasite is None:
                self.data = self.defaults.copy()
            else:
                self.had_parasite = True
                data_bytes = bytes(parasite.get_data())
                data_string = data_bytes.decode('utf-8')
                self.data = json.loads(data_string)
            self.data = as_strings_deeply(self.data)
            return self.data

        def save(self, data):
            dumped: str = json.dumps(data, sort_keys=True, indent=2)
            p_data: str = as_strings_deeply(dumped)
            p_data_bytes = p_data.encode('utf-8')
            wrapped_bytes = list(p_data_bytes)
            parasite = Gimp.Parasite.new(name=self.name, flags=Gimp.PARASITE_PERSISTENT, data=wrapped_bytes)
            self.layer.attach_parasite(parasite)

    class LayerLocal:
        def __init__(self, plugin, layer_in: Gimp.Layer = None):
            if not isinstance(plugin, StabDiffAuto1111):
                raise ValueError("First argument to LayerLocal must be a StabDiffAuto1111 plugin.")
            self._chassis: StabDiffAuto1111 = plugin
            self._id = self._chassis.layer_count
            self._chassis.layer_count += 1
            if layer_in is not None:
                if not isinstance(layer_in, Gimp.Layer):
                    raise ValueError("layer_in argument must be a Gimp.Layer, not a %s" % type(layer_in).__name__)
                self._layer = layer_in
                self._image = layer_in.get_image()

        @property
        def id(self):
            return self._id

        @property
        def layer(self):
            return self._layer

        @property
        def image(self):
            return self._image

        @property
        def plugin(self):
            return self._chassis

        @staticmethod
        def create(plugin, image, name, width, height, image_type, opacity, mode):
            layer = Gimp.Layer.new(image, name, width, height, image_type, opacity, mode)
            return StabDiffAuto1111.LayerLocal(plugin, layer)

        @staticmethod
        def from_base64(plugin, image, base64_data):
            filepath = plugin.files_handle.get("generated.png")
            a_gfile: Gio.File = Gio.File.new_for_path(filepath)
            image_file = open(filepath, "wb+")
            image_file.write(base64.b64decode(base64_data))
            image_file.close()
            layer = Gimp.file_load_layer(Gimp.RunMode.INTERACTIVE, image, a_gfile)
            return StabDiffAuto1111.LayerLocal(plugin, layer)

        def rename(self, name):
            self._layer.set_name(name)
            return self

        def save_data(self, data):
            StabDiffAuto1111.LayerData(self.layer).save(data)
            return self

        def load_data(self, default_data):
            return StabDiffAuto1111.LayerData(self.layer, default_data).data.copy()

        def copy(self):
            copy = self._layer.copy()
            return StabDiffAuto1111.LayerLocal(self.plugin, copy)

        def scale(self, new_scale=1.0):
            if new_scale != 1.0:
                self.layer.scale(self.layer, int(new_scale * self.layer.get_width()), int(new_scale * self.layer.get_height()), False)
            return self

        def resize(self, width, height):
            StabDiffAuto1111.LOGGER.info("Resizing to %dx%d", width, height)
            self.layer.scale(width, height, False)

        def resize_to_multiple_of(self, multiple):
            self._layer.scale(round_to_multiple(self.layer.get_width(), multiple),
                              round_to_multiple(self.layer.get_height(), multiple),
                              False)
            return self

        def translate(self, offset=None):
            if offset is not None:
                self.layer.set_offsets(offset[0], offset[1])
            return self

        def insert(self):
            self.image.insert_layer(self.layer, None, -1)
            return self

        def insert_to(self, image=None):
            image = image or self.image
            image.insert_layer(self.layer, None, -1)
            return self

        def add_selection_as_mask(self):
            mask = self._layer.create_mask(Gimp.AddMaskType.SELECTION)
            self.layer.add_mask(mask)
            return self

        def save_mask_as(self, filepath):
            a_g_file: Gio.File = Gio.File.new_for_path(filepath)
            save_success = Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, self.image, [self.layer.get_mask()], a_g_file)
            if save_success is None:
                StabDiffAuto1111.LOGGER.warning("save_mask_as(): Gimp.file_save returned None")
            if save_success is False:
                StabDiffAuto1111.LOGGER.error("save_mask_as(): Gimp.file_save returned false")
            return self

        def save_as(self, filepath):
            a_g_file: Gio.File = Gio.File.new_for_path(filepath)
            save_success = Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, self.image, [self.layer], a_g_file)
            if save_success is None:
                StabDiffAuto1111.LOGGER.warning("save_as(): Gimp.file_save returned None")
            if save_success is False:
                StabDiffAuto1111.LOGGER.error("save_as(): Gimp.file_save returned false")
            else:
                if StabDiffAuto1111.DEBUG:
                    boolean_type = type(save_success)
                    StabDiffAuto1111.LOGGER.debug("save_as(): Gimp.file_save returned a %s with value %s" % (boolean_type.__name__, str(save_success)))

            return self

        def mask_to_base64(self) -> str:
            filepath = StabDiffAuto1111.TempFiles().get("mask" + str(self.id) + ".png")
            self.save_mask_as(filepath)
            file = open(filepath, "rb")
            return base64.b64encode(file.read()).decode('utf-8')

        def to_base64(self):
            filepath = StabDiffAuto1111.TempFiles().get("layer" + str(self.id) + ".png")
            self.save_as(filepath)
            file = open(filepath, "rb")
            return base64.b64encode(file.read()).decode('utf-8')

        def remove(self):
            self.image.remove_layer(self.layer)
            return self

    class ResponseLayers:
        def __init__(self, plugin,  img, response, options=None):
            if not isinstance(plugin, StabDiffAuto1111):
                raise ValueError("First argument to LayerLocal must be a StabDiffAuto1111 plugin.")
            self._chassis = plugin
            if self._chassis.files_handle is None:
                raise ValueError("StabDiffAuto1111 plugin instance has no files_handle")
            if options is None:
                options = {}
            self._image = img
            color = Gimp.context_get_foreground()
            blackness: Gegl.Color = Gegl.Color.new("BLACK")
            Gimp.context_set_foreground(blackness)

            layers = []
            try:
                info = json.loads(response["info"])
                infotexts = info["infotexts"]
                seeds = info["all_seeds"]
                index = 0
                StabDiffAuto1111.LOGGER.debug(infotexts)
                StabDiffAuto1111.LOGGER.debug(seeds)
                total_images = len(seeds)
                for image in response["images"]:
                    if index < total_images:
                        layer_data = {"info": infotexts[index], "seed": seeds[index]}
                        layer_local = StabDiffAuto1111.LayerLocal.from_base64(self._chassis, img, image).rename(
                            "Generated Layer " + str(seeds[index])).save_data(
                            layer_data).insert_to(img)
                    else:
                        layer_local = None
                        # annotator layers
                        if "skip_annotator_layers" in options and not options["skip_annotator_layers"]:
                            layer_local = StabDiffAuto1111.LayerLocal.from_base64(self._chassis, img, image).rename(
                                "Annotator Layer").insert_to(img)
                    layers.append(layer_local.layer)
                    index += 1
            except Exception as e:  # noqa
                StabDiffAuto1111.LOGGER.exception("ResponseLayers")

            Gimp.context_set_foreground(color)
            self.layers = layers

        @property
        def image(self):
            return self._image

        @property
        def plugin(self):
            return self._chassis

        def scale(self, new_scale=1.0):
            if new_scale != 1.0:
                for layer in self.layers:
                    StabDiffAuto1111.LayerLocal(layer).scale(new_scale)
            return self

        def resize(self, width, height):
            for layer in self.layers:
                StabDiffAuto1111.LayerLocal(self.plugin, layer).resize(width, height)
            return self

        def translate(self, offset=None):
            if offset is not None:
                for layer in self.layers:
                    StabDiffAuto1111.LayerLocal(self.plugin, layer).translate(offset)
            return self

        def insert_to(self, image=None):
            image = image or self.image
            for layer in self.layers:
                StabDiffAuto1111.LayerLocal(self.plugin, layer).insert_to(image)
            return self

        def add_selection_as_mask(self):
            undocumented, non_empty, x1, y1, x2, y2 = Gimp.Selection.bounds(self.image)
            if not non_empty:
                return
            if (x1 == 0) and (y1 == 0) and (x2 - x1 == self.image.get_width()) and (y2 - y1 == self.image.get_height()):
                return
            for layer in self.layers:
                StabDiffAuto1111.LayerLocal(self.plugin, layer).add_selection_as_mask()
            return self

    # noinspection GrazieInspection
    @classmethod
    def dialog_values(cls, populators: List[Callable]) -> List[Any]:  # Perhaps should be Gimp.ValueArray ?
        values: List[Any] = []
        for populator in populators:
            dialog_responses: Dict[str, Any] = cls.POPULATOR_RESPONSES[populator.__name__]
            if dialog_responses is not None:
                values += list(dialog_responses.values())
        return values

    @classmethod
    def dialog_responses(cls, populators: List[Callable]) -> Dict[str, Any]:
        all_responses: Dict[str, Any] = {}
        for populator in populators:
            dialog_responses: Dict[str, Any] = cls.POPULATOR_RESPONSES[populator.__name__]
            if dialog_responses is not None:
                all_responses.update(dialog_responses)
        return all_responses

    @classmethod
    def display_layer_info(cls, subject_layer: Gimp.Layer):
        layer_json_text: str = cls.get_layer_info(subject_layer=subject_layer)
        cls.write_layer_info(subject_layer)
        dialog = new_dialog_info("Layer Data", layer_json_text)
        dialog.run()
        dialog.destroy()

    # Class initialization
    __initialized = False  # We will use 1st call to instance constructor to initialize class members

    @classmethod
    def __init_plugin(cls):
        if StabDiffAuto1111.__initialized:
            raise SystemError("Class has already been initialized.")
        cls.__initialized = True

    def __new__(cls, *args, **kwargs):
        cls.__initialized = False  # We will use 1st call to instance constructor to initialize class members
        instance_fresh = super(StabDiffAuto1111, cls).__new__(cls)
        cls.LOGGER.debug("GIMP Python3 site-packages paths are:")
        cls.LOGGER.debug("\n".join(site.getsitepackages()))
        cls.LOGGER.debug("GIMP Python3 sys.path is:")
        cls.LOGGER.debug("\n".join(sys.path))
        # Initialize debugging
        if os.environ.get('DEBUG'):
            cls.DEBUG = True
            logging.basicConfig(level=logging.DEBUG)
        else:
            cls.DEBUG = False
            logging.basicConfig(level=logging.INFO)

        cls.LOGGER.info("StabDiffAuto1111 version %d" % cls.VERSION)

        if os.environ.get('skip_a1111'):
            cls.skip_a1111 = True
            cls.LOGGER.warning("Disabling connection attempts to SD_A1111")
        return instance_fresh

    def __init__(self):
        self._name = StabDiffAuto1111.PYTHON_PLUGIN_NAME_LONG
        self._settings: StabDiffAuto1111.MyShelf = StabDiffAuto1111.MyShelf(StabDiffAuto1111.STABLE_DIFF_AUTO1111_DEFAULT_SETTINGS)
        self._settings.assert_settings_available()
        self._image: Gimp.Image = None
        self._files: StabDiffAuto1111.TempFiles = StabDiffAuto1111.TempFiles()
        self._layer_count = 1
        self._api: StabDiffAuto1111.ApiClient = StabDiffAuto1111.ApiClient(self._settings.get("api_base"))
        self._models = self._settings.get("models", [])
        self._sd_model_checkpoint = None
        self._skip_a1111 = False
        self.is_server_running = False
        """
        We use this instance constructor to initialize the plugin. If something better comes along, 
        we will use that instead.
        """
        if not StabDiffAuto1111.__initialized:
            StabDiffAuto1111.__init_plugin()

        self.poll_server()
        if not self.is_server_running:
            Gimp.message("It seems that StableDiffusion is not running on " + self.settings.get("api_base"))

    @property
    def image(self) -> Gimp.Image:
        return self._image

    @image.setter
    def image(self, image_in: Gimp.Image):
        self._image = image_in

    def check_imagery_and_set(self, image_in: Gimp.Image, n_drawables: int, drawables, verbose: bool = False):
        StabDiffAuto1111.assert_imagery_args(image_in=image_in, n_drawables=n_drawables, drawables=drawables, verbose=verbose)
        self.image = image_in

    @property
    def name(self) -> str:
        return self._name

    @property
    def files_handle(self) -> TempFiles:
        return self._files

    @property
    def api(self) -> ApiClient:
        return self._api

    @property
    def models(self):
        return self._models

    @property
    def checkpoint(self):
        return self.sd_model_checkpoint

    @property
    def is_server_running(self) -> bool:
        return self._is_server_running

    @is_server_running.setter
    def is_server_running(self, connectable: bool):
        self._is_server_running = connectable

    @property
    def settings(self) -> MyShelf:
        return self._settings

    @settings.setter
    def settings(self, settings_in):
        self._settings = settings_in

    @property
    def layer_count(self):
        return self._layer_count

    @layer_count.setter
    def layer_count(self, layer_count):
        self._layer_count = layer_count

    def val_str(self, key: str, default_value="") -> str:
        return self.settings.get(key, default_value)

    def val_float(self, key: str, default_value: float = 0.0) -> float:
        return self.settings.get(key, default_value)

    def val_int(self, key: str, default_value: int = 0) -> int:
        return self.settings.get(key, default_value)

    def fetch_stablediffusion_options(self):
        """ Get the StableDiffusion data needed for dynamic gimpfu.PF_OPTION lists """
        try:
            options: Dict = as_strings_deeply(self.api.get("/sdapi/v1/options") or {})
            sd_model_checkpoint_local = options.get("sd_model_checkpoint", None)
            models_local = list(map(lambda data: data["title"], self.api.get("/sdapi/v1/sd-models") or []))
            cn_models = (self.api.get("/controlnet/model_list") or {}).get("model_list", [])
            cn_models = ["None"] + cn_models

            self.settings.save({
                "models": models_local,  # noqa
                "cn_models": cn_models,  # noqa
                "sd_model_checkpoint": sd_model_checkpoint_local,  # noqa
                "is_server_running": True  # noqa
            })
        except Exception as ex:  # noqa
            StabDiffAuto1111.LOGGER.exception("ERROR: fetch_stablediffusion_options")
            self.settings.save({
                "is_server_running": False  # noqa
            })

    def config(self, prompt, negative_prompt, url):
        self.settings.save({
            "prompt": prompt,  # noqa
            "negative_prompt": negative_prompt,  # noqa
            "api_base": url,  # noqa
        })

    def poll_server(self):
        server_url: str = self.settings.get("api_base")
        if server_url is None:
            raise ValueError("api_base setting is missing.")
        if server_url.strip() == "":
            raise ValueError("api_base setting is blank.")
        if not server_url.lower().startswith("http://"):
            raise ValueError("api_base setting \"%s\" is not a valid http URL." % server_url)
        self.is_server_running = server_online(server_url)
        return self.is_server_running

    # noinspection PyMethodMayBeStatic
    def do_query_procedures(self) -> list[str]:
        # This is the list of procedure names.
        return StabDiffAuto1111.PYTHON_PROCEDURE_NAMES

    def do_create_procedure(self, name) -> Gimp.ImageProcedure:
        """
        This method must be overridden by all plug-ins and return a newly allocated GimpProcedure with the identifier
         specified by the parameter "name". Generally, procedures are the behaviour invoked by menu selections.
        Parameters
        ----------
        :param name:
            The name of the procedure.
        :return:
            A Gimp.ImageProcedure.
        """
        match name:
            case StabDiffAuto1111.PYTHON_PROCEDURE_CONFIG_GLOBAL:
                procedure = self.create_procedure(name_raw=name,
                                                  docs="This is where you configure params that are shared between all API requests",
                                                  usage_hint="Gimp Client for the StableDiffusion Automatic1111 API",
                                                  run_func_in=self.run_with_image,
                                                  is_config_proc=True,
                                                  subject_type=SubjectType.IMAGE)

            case StabDiffAuto1111.PYTHON_PROCEDURE_CONFIG_MODEL:
                procedure = self.create_procedure(name_raw=name,
                                                  docs="Configure checkpoint model of Automatic1111 api",
                                                  usage_hint="Change checkpoint model of Automatic1111 api",
                                                  run_func_in=self.run_with_image,
                                                  is_config_proc=True,
                                                  subject_type=SubjectType.IMAGE)

            case StabDiffAuto1111.PYTHON_PROCEDURE_CONTROLNET_LAYER:
                procedure = self.create_procedure(name_raw=name,
                                                  docs="Convert current layer to ControlNet layer \n   or edit ControlNet Layer's options",
                                                  usage_hint="Active layer as ControlNet",
                                                  run_func_in=self.run_layer_to_controlnet,
                                                  subject_type=SubjectType.IMAGE)

            case StabDiffAuto1111.PYTHON_PROCEDURE_CONTROLNET_LAYER_CONTEXT:
                procedure = self.create_procedure(name_raw=name,
                                                  docs="Convert current layer to ControlNet layer \n   or edit ControlNet Layer's options",
                                                  usage_hint="Use as ControlNet",
                                                  run_func_in=self.run_layer_to_controlnet,
                                                  subject_type=SubjectType.LAYER)

            case StabDiffAuto1111.PYTHON_PROCEDURE_IMG2IMG:
                procedure = self.create_procedure(name_raw=name,
                                                  docs="Image to image",
                                                  usage_hint="Image to image",
                                                  run_func_in=self.run_image_2_image,
                                                  subject_type=SubjectType.IMAGE)

            case StabDiffAuto1111.PYTHON_PROCEDURE_IMG2IMG_CONTEXT:
                procedure = self.create_procedure(name_raw=name,
                                                  docs="Image to image",
                                                  usage_hint="Image to image",
                                                  run_func_in=self.run_image_2_image,
                                                  subject_type=SubjectType.LAYER)

            case StabDiffAuto1111.PYTHON_PROCEDURE_INPAINTING:
                procedure = self.create_procedure(name_raw=name,
                                                  docs="Inpainting",
                                                  usage_hint="Inpainting",
                                                  run_func_in=self.run_inpainting,
                                                  subject_type=SubjectType.IMAGE)

            case StabDiffAuto1111.PYTHON_PROCEDURE_INPAINTING_CONTEXT:
                procedure = self.create_procedure(name_raw=name,
                                                  docs="Inpainting",
                                                  usage_hint="Inpainting",
                                                  run_func_in=self.run_inpainting,
                                                  subject_type=SubjectType.LAYER)

            case StabDiffAuto1111.PYTHON_PROCEDURE_LAYER_INFO:  # Passes run_with_image, and uses a layer-selection dialog.
                procedure = self.create_procedure(name_raw=name,
                                                  docs="Show stable StabDiffAuto1111 info associated with this layer.",
                                                  usage_hint="Layer Info",
                                                  run_func_in=self.run_with_image,
                                                  is_config_proc=True,
                                                  subject_type=SubjectType.IMAGE)

            case StabDiffAuto1111.PYTHON_PROCEDURE_LAYER_INFO_CONTEXT:
                procedure = self.create_procedure(name_raw=name,
                                                  docs="Show stable StabDiffAuto1111 info associated with this layer.",
                                                  usage_hint="Layer Info",
                                                  run_func_in=self.run_layer_info_context,
                                                  subject_type=SubjectType.LAYER)

            case StabDiffAuto1111.PYTHON_PROCEDURE_TEXT2IMG:
                procedure = self.create_procedure(name_raw=name,
                                                  docs="Text2Image",
                                                  usage_hint="It's Magic!",
                                                  run_func_in=self.run_text_2_image,
                                                  subject_type=SubjectType.IMAGE)

            case StabDiffAuto1111.PYTHON_PROCEDURE_TEXT2IMG_CONTEXT:
                procedure = self.create_procedure(name_raw=name,
                                                  docs="Text2Image",
                                                  usage_hint="It's Magic!",
                                                  run_func_in=self.run_text_2_image,
                                                  subject_type=SubjectType.LAYER)
            case _:
                raise TypeError("Unknown procedure name \"" + name + "\"")
        if StabDiffAuto1111.DEBUG:
            message = "Added procedure %s to menu path %s" % (procedure.get_name(), ", ".join(procedure.get_menu_paths()))
            StabDiffAuto1111.LOGGER.debug(message)
        return procedure

    def create_procedure(self, name_raw: str,
                         docs: str,
                         usage_hint: str,
                         run_func_in: Callable,
                         subject_type: SubjectType,
                         is_config_proc: bool = False,
                         is_image_optional: bool = False
                         ) -> Gimp.ImageProcedure:
        run_func: Callable
        match subject_type:
            case SubjectType.IMAGE:
                run_func = self.run_with_image if run_func_in is None else run_func_in
                menu_path = StabDiffAuto1111.LIMB_IMAGE_MENU_NAME
            case SubjectType.LAYER:
                run_func = self.run_with_layer if run_func_in is None else run_func_in
                menu_path = StabDiffAuto1111.LIMB_LAYERS_MENU_NAME
            case _:
                raise TypeError("Unsupported SubjectType %s" % str(subject_type))

        name = re.sub(StabDiffAuto1111.PYTHON_PLUGIN_NAME + "-", "", name_raw)
        procedure = Gimp.ImageProcedure.new(self,
                                            name_raw,
                                            Gimp.PDBProcType.PLUGIN,
                                            run_func,
                                            None)
        if StabDiffAuto1111.DEBUG:
            n_raw = name
            n_pretty = pretty_name(ugly_name=n_raw)
            n_cooked = StabDiffAuto1111._(n_pretty)
            message = "name=%s, prettified=%s, cooked=%s" % (n_raw, n_pretty, n_cooked)
            StabDiffAuto1111.LOGGER.warning(message)
        procedure.set_menu_label(StabDiffAuto1111._(pretty_name(name)))
        procedure.set_documentation(docs, usage_hint, name)
        if is_image_optional:
            procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.ALWAYS)  # "ALWAYS" required if image optional
            procedure.set_image_types("")  # NOTE: Isn't "*"
        else:
            procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE)
            procedure.set_image_types("*")  # NOTE: Isn't ""
        procedure.set_icon_name(GimpUi.ICON_GEGL)
        procedure.set_attribution("Hymerfania", "Hymerfania", "2024")

        if is_config_proc:
            menu_path = StabDiffAuto1111.LIMB_IMAGE_MENU_NAME + "/Config"
        procedure.add_menu_path(menu_path)
        return procedure

    """
    Part of reason for the exotic style here is that GIMP calls these run_*() methods autonomously. The parameters must conform 
    to the set below. So we can either have every procedure include even more boilerplate, or we can normalize common
    dialog wrangling code, and introduce more functions to handle each dialog's custom logic.
    Yes, it would be good to use GimpUi.ProcedureDialog. But at the time of this writing, up-to-date documentation is
    sparse, and there seems to be blocking bugs for things we need to do.
    """

    # noinspection PyUnusedLocal
    def run_layer_to_controlnet(self, procedure: Gimp.ImageProcedure, run_mode: Gimp.RunMode, image_in: Gimp.Image, n_drawables, drawables, args, run_data) -> Gimp.ValueArray:
        retval = procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        self.check_imagery_and_set(image_in=image_in, n_drawables=n_drawables, drawables=drawables)

        def assemble_and_post(chassis: StabDiffAuto1111, target_layer: Gimp.Layer):
            save_controlnet_args: Dict[Any, Any] = DialogPopulator.merged_responses(StabDiffAuto1111.PYTHON_PROCEDURE_CONTROLNET_LAYER)
            if StabDiffAuto1111.DEBUG:
                StabDiffAuto1111.LOGGER.debug(json.dumps(save_controlnet_args, indent=2, sort_keys=True))
            chassis.save_control_layer(
                    active_layer=target_layer,
                    module_index=save_controlnet_args["modules_index"],  # int
                    model_index=save_controlnet_args["cn_models_index"],  # int
                    weight=float(save_controlnet_args["weight"]),  #
                    resize_mode_index=save_controlnet_args["resize_mode_index"],  # int
                    low_vram=bool(save_controlnet_args["low_vram"]),  #
                    control_mode=save_controlnet_args["control_mode"],  # str , ie "Balanced"
                    guidance_start=save_controlnet_args["guidance_start"],  #
                    guidance_end=save_controlnet_args["guidance_end"],  #
                    guidance=save_controlnet_args["guidance"],  #
                    processor_res=save_controlnet_args["processor_res"],  #
                    threshold_a=save_controlnet_args["threshold_a"],  #
                    threshold_b=save_controlnet_args["threshold_b"]  #
            )

        try:
            self.poll_server()
            # There may be cases where a Layer is not usable by SD, text, splines, etc.
            active_layer: Gimp.Drawable = image_in.get_selected_drawables()[0]
            if active_layer is None:
                StabDiffAuto1111.LOGGER.error("No active Layer.")
                return retval
            if not isinstance(active_layer, Gimp.Layer):
                StabDiffAuto1111.LOGGER.error("Drawable is not a Gimp.Layer")
                return retval
            if StabDiffAuto1111.DEBUG:
                StabDiffAuto1111.LOGGER.debug("Active(Selected) Layer is %s" % active_layer.get_name())
            procedure_name_short = re.sub(StabDiffAuto1111.PYTHON_PLUGIN_NAME + "-", "", procedure.get_name())
            title = "%s with Layer %s " % (procedure_name_short.title(), active_layer.get_name())
            blurb = "Convert layer \"%s\" to ControlNet layer \n   or edit ControlNet Layer's options" % active_layer.get_name()
            dialog: GimpUi.Dialog = self.new_procedure_dialog(title_in=title, role_in=procedure_name_short.title(), procedure=procedure, blurb_in=blurb)
            while True:
                response = dialog.run()
                if response == Gtk.ResponseType.OK:
                    assemble_and_post(self, target_layer=active_layer)
                    dialog.destroy()
                    break
                elif response == Gtk.ResponseType.APPLY:
                    assemble_and_post(self, target_layer=active_layer)
                else:
                    dialog.destroy()
                    retval: Gimp.ValueArray = procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
                    break
        except Exception:  # noqa
            StabDiffAuto1111.LOGGER.exception("Error in run_layer_to_controlnet")
        Gimp.displays_flush()
        return retval

    # noinspection PyUnusedLocal
    def run_image_2_image(self, procedure: Gimp.ImageProcedure, run_mode: Gimp.RunMode, image_in: Gimp.Image, n_drawables, drawables, args, run_data) -> Gimp.ValueArray:
        StabDiffAuto1111.LOGGER.setLevel(logging.DEBUG)
        retval = procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        self.check_imagery_and_set(image_in=image_in, n_drawables=n_drawables, drawables=drawables)

        def assemble_and_post(chassis: StabDiffAuto1111):
            img2img_args: Dict[Any, Any] = DialogPopulator.merged_responses(StabDiffAuto1111.PYTHON_PROCEDURE_IMG2IMG)
            if StabDiffAuto1111.DEBUG:
                StabDiffAuto1111.LOGGER.info(json.dumps(img2img_args, indent=2, sort_keys=True))
            chassis_layers: List[Gimp.Layer] = chassis.image.list_layers()
            cn1_layer: Gimp.Layer = None
            cn2_layer: Gimp.Layer = None
            # AGAIN! layer_index is 2 more than it should be!
            # Does LayerComboBox have a bug? Are there 2 invisible elements before the ones shown?
            c1i = int(img2img_args["cn1_layer"]) - LAYER_INDEX_CORRECTION  # Strange and Bad!
            c2i = int(img2img_args["cn2_layer"]) - LAYER_INDEX_CORRECTION  # Strange and Bad!
            cn1_enabled: bool = bool(img2img_args["cn1_enabled"])
            cn2_enabled: bool = bool(img2img_args["cn2_enabled"])
            if cn1_enabled:
                try:
                    cn1_layer = chassis_layers[c1i]
                except IndexError:
                    StabDiffAuto1111.LOGGER.exception("Layer index %d for cn1_layer is out of range " % c1i)
            if cn2_enabled:
                try:
                    cn2_layer = chassis_layers[c2i]
                except IndexError:
                    StabDiffAuto1111.LOGGER.exception("Layer index %d for cn1_layer is out of range " % c1i)

            chassis.image_to_image(
                resize_mode=img2img_args["resize_mode"],
                p_prompt_prefix=img2img_args["prompt_prefix"],
                n_prompt_prefix=img2img_args["negative_prompt_prefix"],
                seed=img2img_args["seed"],
                batch_size=img2img_args["batch_size"],
                steps=img2img_args["steps"],
                # mask_blur=img2img_args["mask_blur"],
                width=img2img_args["width"],
                height=img2img_args["height"],
                cfg_scale=img2img_args["cfg"],
                denoising_strength=img2img_args["denoising_strength"],
                sampler_index=img2img_args["samplers_index"],
                cn1_enabled=cn1_enabled,
                cn1_layer=cn1_layer,
                cn2_enabled=cn2_enabled,
                cn2_layer=cn2_layer,
                cn_skip_annotator_layers=img2img_args["skip_annotator"]
            )

        try:
            self.poll_server()
            GimpUi.init(StabDiffAuto1111.PYTHON_PLUGIN_NAME)
            procedure_name_short = re.sub(StabDiffAuto1111.PYTHON_PLUGIN_NAME + "-", "", procedure.get_name())
            dialog: GimpUi.Dialog = self.new_procedure_dialog(title_in=procedure_name_short.title(), role_in=procedure_name_short.title(), procedure=procedure, blurb_in=procedure.get_blurb())
            while True:
                response = dialog.run()
                if response == Gtk.ResponseType.OK:
                    assemble_and_post(self)
                    dialog.destroy()
                    break
                elif response == Gtk.ResponseType.APPLY:
                    assemble_and_post(self)
                else:
                    dialog.destroy()
                    retval: Gimp.ValueArray = procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
                    break
        except Exception:  # noqa
            StabDiffAuto1111.LOGGER.exception("Error in run_image_2_image")
        Gimp.displays_flush()
        return retval

    # noinspection PyUnusedLocal
    def run_inpainting(self, procedure: Gimp.ImageProcedure, run_mode: Gimp.RunMode, image_in: Gimp.Image, n_drawables, drawables, args, run_data) -> Gimp.ValueArray:
        StabDiffAuto1111.LOGGER.setLevel(logging.DEBUG)
        retval = procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        self.check_imagery_and_set(image_in=image_in, n_drawables=n_drawables, drawables=drawables)

        def assemble_and_post(chassis: StabDiffAuto1111):
            inpainting_args: Dict[Any, Any] = DialogPopulator.merged_responses(StabDiffAuto1111.PYTHON_PROCEDURE_INPAINTING)
            if StabDiffAuto1111.DEBUG:
                StabDiffAuto1111.LOGGER.info(json.dumps(inpainting_args, indent=2, sort_keys=True))
            if not self.image:
                raise ValueError("Image has been reset to None")
            chassis_layers: List[Gimp.Layer] = chassis.image.list_layers()
            cn1_layer: Gimp.Layer = None
            cn2_layer: Gimp.Layer = None
            # AGAIN! layer_index is 2 more than it should be!
            # Does LayerComboBox have a bug? Are there 2 invisible elements before the ones shown?
            c1i = int(inpainting_args["cn1_layer"]) - LAYER_INDEX_CORRECTION  # Strange and Bad!
            c2i = int(inpainting_args["cn2_layer"]) - LAYER_INDEX_CORRECTION  # Strange and Bad!
            cn1_enabled: bool = bool(inpainting_args["cn1_enabled"])
            cn2_enabled: bool = bool(inpainting_args["cn2_enabled"])
            if cn1_enabled:
                try:
                    cn1_layer = chassis_layers[c1i]
                except IndexError:
                    layer_max: int = len(chassis_layers) - 1
                    StabDiffAuto1111.LOGGER.exception("Layer index %d for cn1_layer is out of range 0-%d" % (c1i, layer_max))
                    cn1_enabled = False
            if cn2_enabled:
                try:
                    cn2_layer = chassis_layers[c2i]
                except IndexError:
                    layer_max: int = len(chassis_layers) - 1
                    StabDiffAuto1111.LOGGER.exception("Layer index %d for cn1_layer is out of range 0-%d" % (c1i, layer_max))
                    cn2_enabled = False

            chassis.inpainting(
                batch_size=min(StabDiffAuto1111.MAX_BATCH_SIZE, max(1, inpainting_args["batch_size"])),
                cfg_scale=float(inpainting_args["cfg"]),
                cn1_enabled=cn1_enabled,
                cn1_layer=cn1_layer,
                cn2_enabled=cn2_enabled,
                cn2_layer=cn2_layer,
                cn_skip_annotator_layers=inpainting_args["skip_annotator"],
                denoising_strength=float(inpainting_args["denoising_strength"]),
                height=round_to_multiple(inpainting_args["height"], 8),
                inpaint_full_res=inpainting_args["inpaint_full_res"],
                invert_mask=inpainting_args["invert_mask"],
                mask_blur=int(inpainting_args["mask_blur"]),
                n_prompt_prefix=inpainting_args["negative_prompt_prefix"],
                p_prompt_prefix=inpainting_args["prompt_prefix"],
                resize_mode=inpainting_args["resize_mode"],
                sampler_index=inpainting_args["samplers_index"],
                seed=inpainting_args["seed"],
                steps=inpainting_args["steps"],
                width=inpainting_args["width"]
            )

        try:
            if not self.image:
                raise ValueError("Image has been reset to None")
            image_selection: Gimp.Selection = self.image.get_selection()
            if self.get_active_mask_as_base64() == "":
                err_message: str = "Insufficient data:\nNo selection in layer. "
                StabDiffAuto1111.LOGGER.error(err_message)
                Gimp.message(err_message)  # I expect Gimp.message to be a dialog, but nope. Perhaps because console.
                # TODO: Only show dialog if GIMP doesn't
                err_dialog: GimpUi.Dialog = new_dialog_error_user(title_in="Insufficient data", blurb_in=err_message)
                err_dialog.run()
                err_dialog.destroy()
                return retval

            self.poll_server()
            procedure_name_short = re.sub(StabDiffAuto1111.PYTHON_PLUGIN_NAME + "-", "", procedure.get_name())

            dialog: GimpUi.Dialog = self.new_procedure_dialog(title_in=procedure_name_short.title(), role_in=procedure_name_short.title(), procedure=procedure, blurb_in=procedure.get_blurb())
            while True:
                response = dialog.run()
                if not self.image:
                    raise ValueError("Image has been reset to None")
                if response == Gtk.ResponseType.OK:
                    assemble_and_post(self)
                    dialog.destroy()
                    break
                elif response == Gtk.ResponseType.APPLY:
                    assemble_and_post(self)
                else:
                    dialog.destroy()
                    retval: Gimp.ValueArray = procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
                    break
        except Exception:  # noqa
            StabDiffAuto1111.LOGGER.exception("Error in run_inpainting")
        Gimp.displays_flush()
        return retval

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def run_layer_info_context(self, procedure: Gimp.ImageProcedure, run_mode: Gimp.RunMode, image_in: Gimp.Layer, n_drawables, drawables, args, run_data) -> Gimp.ValueArray:
        """
        Entry point of each procedure.
        Parameters
        ----------
        :param procedure:
        :param run_mode:
        :param image_in:
        :param n_drawables:
        :param drawables:
        :param args:
        :param run_data:
        :return:
        """
        retval = procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        self.check_imagery_and_set(image_in=image_in, n_drawables=n_drawables, drawables=drawables, verbose=True)
        try:
            self.poll_server()
            GimpUi.init(StabDiffAuto1111.PYTHON_PLUGIN_NAME)
            selected_layers = image_in.get_selected_drawables()
            StabDiffAuto1111.display_layer_info(subject_layer=selected_layers[0])  # This is an ASSUMPTION that selected_layers[0] is the "active layer"
            retval: Gimp.ValueArray = procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
            return retval
        except Exception:  # noqa
            StabDiffAuto1111.LOGGER.exception("Error in run_with_layer_context")
            return retval

    # noinspection PyUnusedLocal
    def run_text_2_image(self, procedure: Gimp.ImageProcedure, run_mode: Gimp.RunMode, image_in: Gimp.Image, n_drawables, drawables, args, run_data) -> Gimp.ValueArray:
        retval = procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        self.check_imagery_and_set(image_in=image_in, n_drawables=n_drawables, drawables=drawables)

        def assemble_and_post(chassis: StabDiffAuto1111):
            txt2img_args: Dict[Any, Any] = DialogPopulator.merged_responses(StabDiffAuto1111.PYTHON_PROCEDURE_TEXT2IMG)
            if StabDiffAuto1111.DEBUG:
                StabDiffAuto1111.LOGGER.info(json.dumps(txt2img_args, indent=2, sort_keys=True))
            if not self.image:
                raise ValueError("Image has been reset to None")

            chassis.text_to_image(
                p_prompt_prefix=txt2img_args["prompt_prefix"],
                n_prompt_prefix=txt2img_args["negative_prompt_prefix"],
                seed=txt2img_args["seed"],
                batch_size=txt2img_args["batch_size"],
                steps=txt2img_args["steps"],
                mask_blur=txt2img_args["mask_blur"],
                width=txt2img_args["width"],
                height=txt2img_args["height"],
                cfg_scale=txt2img_args["cfg"],
                denoising_strength=txt2img_args["denoising_strength"],
                sampler_index=txt2img_args["samplers_index"],
                cn1_enabled=txt2img_args["cn1_enabled"],
                cn1_layer=txt2img_args["cn1_layer"],
                cn2_enabled=txt2img_args["cn2_enabled"],
                cn2_layer=txt2img_args["cn2_layer"],
                cn_skip_annotator_layers=txt2img_args["skip_annotator"]
            )

        try:
            GimpUi.init(StabDiffAuto1111.PYTHON_PLUGIN_NAME)
            procedure_name_short = re.sub(StabDiffAuto1111.PYTHON_PLUGIN_NAME + "-", "", procedure.get_name())
            if not self.image:
                raise ValueError("Image has been reset to None")
            dialog: GimpUi.Dialog = self.new_procedure_dialog(title_in=procedure_name_short.title(), role_in=procedure_name_short.title(), procedure=procedure, blurb_in=procedure.get_blurb())
            while True:
                response = dialog.run()
                if not self.image:
                    raise ValueError("Image has been reset to None")
                if response == Gtk.ResponseType.OK:
                    assemble_and_post(self)
                    dialog.destroy()
                    break
                elif response == Gtk.ResponseType.APPLY:
                    assemble_and_post(self)
                else:
                    dialog.destroy()
                    retval: Gimp.ValueArray = procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())
                    break
        except Exception:  # noqa
            StabDiffAuto1111.LOGGER.exception("Error in run_text_2_image")
        Gimp.displays_flush()
        return retval

    # noinspection PyUnusedLocal
    def run_with_image(self, procedure: Gimp.ImageProcedure, run_mode: Gimp.RunMode, image_in: Gimp.Image, n_drawables, drawables, args, run_data) -> Gimp.ValueArray:
        """
        For Procedures that don't need a current image.
        Parameters
        ----------
        :param run_data:
        :type run_data:
        :param args:
        :type args:
        :param drawables:
        :type drawables:
        :param n_drawables:
        :type n_drawables:
        :param image_in:
        :type image_in:
        :param procedure:
        :param run_mode:
        :return:
        """
        retval = procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
        try:
            self.poll_server()
            self.check_imagery_and_set(image_in=image_in, n_drawables=n_drawables, drawables=drawables)

            GimpUi.init(StabDiffAuto1111.PYTHON_PLUGIN_NAME)
            procedure_name_short = re.sub(StabDiffAuto1111.PYTHON_PLUGIN_NAME + "-", "", procedure.get_name())
            if StabDiffAuto1111.DEBUG:
                StabDiffAuto1111.LOGGER.debug("Building dialog for procedure %s" % procedure_name_short)
            dialog: GimpUi.Dialog = self.new_procedure_dialog(title_in=procedure_name_short.title(), role_in=procedure_name_short.title(), procedure=procedure, blurb_in=procedure.get_blurb())
            while True:
                response = dialog.run()
                if response == Gtk.ResponseType.OK:
                    dialog.destroy()
                    break
                elif response == Gtk.ResponseType.APPLY:
                    pass
                else:
                    dialog.destroy()
                    retval: Gimp.ValueArray = procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
                    break
        except Exception:  # noqa
            StabDiffAuto1111.LOGGER.exception("Error in run_with_image")
        Gimp.displays_flush()
        return retval

    # noinspection PyUnusedLocal
    def run_with_layer(self, procedure: Gimp.ImageProcedure, run_mode: Gimp.RunMode, image_in: Gimp.Layer, n_drawables, drawables, args, run_data) -> Gimp.ValueArray:
        """
        Entry point of each procedure.
        Parameters
        ----------
        :param procedure:
        :param run_mode:
        :param image_in:
        :type image_in:
        :param n_drawables:
        :param drawables:
        :param args:
        :param run_data:
        :return:
        """
        try:
            Gimp.message("Method \"run_with_layer\" unimplemented in %s " % self.name)
            retval = procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
            StabDiffAuto1111.assert_imagery_args(image_in=image_in, n_drawables=n_drawables, drawables=drawables)
            return retval
        except Exception:  # noqa
            StabDiffAuto1111.LOGGER.exception("Error in run_with_layer")

    # noinspection PyUnusedLocal
    def run_with_layer_context(self, procedure: Gimp.ImageProcedure, run_mode: Gimp.RunMode, image_in: Gimp.Layer, n_drawables, drawables, args, run_data) -> Gimp.ValueArray:
        """
        Entry point of each procedure.
        Parameters
        ----------
        :param procedure:
        :param run_mode:
        :param image_in:
        :type image_in:
        :param n_drawables:
        :param drawables:
        :param args:
        :param run_data:
        :return:
        """
        try:
            Gimp.message("Method \"run_with_layer_context\" unimplemented in %s " % self.name)
            GimpUi.init(StabDiffAuto1111.PYTHON_PLUGIN_NAME)
            retval = procedure.new_return_values(Gimp.PDBStatusType.CANCEL, GLib.Error())
            StabDiffAuto1111.assert_imagery_args(image_in=image_in, n_drawables=n_drawables, drawables=drawables)
            return retval
        except Exception:  # noqa
            StabDiffAuto1111.LOGGER.exception("Error in run_with_layer_context")

    def new_procedure_dialog(self, title_in: str, role_in: str,
                             procedure: Gimp.Procedure,
                             blurb_in: str,
                             gimp_icon_name: str = GimpUi.ICON_DIALOG_INFORMATION,
                             ) -> GimpUi.Dialog:
        dialog = GimpUi.Dialog(use_header_bar=True, title=title_in, role=role_in)
        dialog_box = dialog.get_content_area()
        if blurb_in:
            label_and_icon_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            icon_image = Gtk.Image.new_from_icon_name(gimp_icon_name, Gtk.IconSize.DIALOG)  # noqa
            blurb_label: Gtk.Label = Gtk.Label(label=blurb_in)
            label_and_icon_box.pack_start(child=icon_image, expand=False, fill=False, padding=0)  # noqa
            label_and_icon_box.pack_start(child=blurb_label, expand=False, fill=False, padding=0)  # noqa
            label_and_icon_box.show_all()  # noqa
            dialog_box.add(label_and_icon_box)

        # GIMP does something to the layout in dialogs. I'm not sure if I should force it to look more conventional.
        dialog.add_button(StabDiffAuto1111._("_Cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(StabDiffAuto1111._("_Apply"), Gtk.ResponseType.APPLY)
        dialog.add_button(StabDiffAuto1111._("_OK"), Gtk.ResponseType.OK)

        populators = DialogPopulator.from_procedure(procedure)
        if populators is None:
            raise ValueError("No DialogPopulators list from procedure %s " % procedure.get_name())
        populator: DialogPopulator
        for populator in populators:
            if StabDiffAuto1111.DEBUG:
                StabDiffAuto1111.LOGGER.debug("populating components defined by populator %s, factory %s" % (populator.populator_name, populator.widget_factory_name))
            try:
                populator.add_components(plugin=self, dialog_in=dialog)
                dialog.get_widget_for_response(Gtk.ResponseType.CANCEL).connect("clicked", populator.delete_results)
                dialog.get_widget_for_response(Gtk.ResponseType.APPLY).connect("clicked", populator.assign_results)
                dialog.get_widget_for_response(Gtk.ResponseType.OK).connect("clicked", populator.assign_results)
            except Exception:  # noqa
                StabDiffAuto1111.LOGGER.exception("ERROR: Exception in Dialog populator")

        # Note that we add the progress bar after the populators have added stuff
        # GIMP bug prevents GimpUi.ProgressBar from being visible. This does not seem to hurt anything, so when the GIMP
        # bug is fixed, perhaps this will appear correctly.
        progress_bar: GimpUi.ProgressBar = GimpUi.ProgressBar.new()
        progress_bar.set_hexpand(True)
        progress_bar.set_show_text(True)
        dialog_box.add(progress_bar)
        progress_bar.show()

        geometry = Gdk.Geometry()  # noqa
        geometry.min_aspect = 0.5
        geometry.max_aspect = 1.0
        dialog.set_geometry_hints(None, geometry, Gdk.WindowHints.ASPECT)  # noqa
        dialog.show_all()
        return dialog

    def get_active_mask_as_base64(self):
        return self.get_layer_mask_as_base64(self.image.list_layers()[0])  # FIXME we really need the active layer, not just the 1st one

    def get_active_layer_as_base64(self):
        return self.get_layer_as_base64(self.image.list_layers()[0])  # FIXME we really need the active layer, not just the 1st one

    def get_selection_bounds(self):
        bounds_result = Gimp.Selection.bounds(self.image)
        if StabDiffAuto1111.DEBUG:
            StabDiffAuto1111.LOGGER.debug("bounds_result=%s" % str(bounds_result))
            StabDiffAuto1111.LOGGER.debug("bounds_result type count =%s" % type(bounds_result).__name__)
            StabDiffAuto1111.LOGGER.debug("bounds_result item count =%d" % len(bounds_result))
        # some_bool is an undocumented returned value. I don't know if this is a docs problem or a GIMP bug.
        some_bool, non_empty, x1, y1, x2, y2 = bounds_result
        if non_empty:
            return x1, y1, x2 - x1, y2 - y1
        return 0, 0, self.image.get_width(), self.image.get_height()

    def cleanup(self):
        if self.files_handle:
            self.files_handle.remove_all()
        self.check_update()

    def image_to_image(self,
                       resize_mode,
                       p_prompt_prefix,
                       n_prompt_prefix,
                       seed, batch_size,
                       steps,
                       # mask_blur,
                       width,
                       height,
                       cfg_scale,
                       denoising_strength,
                       sampler_index,
                       cn1_enabled,
                       cn1_layer,
                       cn2_enabled,
                       cn2_layer,
                       cn_skip_annotator_layers
                       ):
        if StabDiffAuto1111.DEBUG:
            StabDiffAuto1111.LOGGER.debug("image_to_image")
        image_local = self.image
        if image_local is None:
            raise ValueError("Image has been reset to None")

        if cn1_enabled and not isinstance(cn1_layer, Gimp.Layer):
            raise TypeError("cn1_argument must be a Gimp.Layer, not a %s" % type(cn1_layer).__name__)

        if cn2_enabled and not isinstance(cn2_layer, Gimp.Layer):
            raise TypeError("cn2_argument must be a Gimp.Layer, not a %s" % type(cn2_layer).__name__)

        x, y, orig_width, orig_height = self.get_selection_bounds()
        # if mask_blur and StabDiffAuto1111.DEBUG:
        #     StabDiffAuto1111.LOGGER.debug("skipping mask_blur %d" % int(mask_blur))
        data = {
            "resize_mode": resize_mode,
            "init_images": [self.get_active_layer_as_base64()],
            "prompt": (p_prompt_prefix + " " + self.settings.get("prompt")).strip(),
            "negative_prompt": (n_prompt_prefix + " " + self.settings.get("negative_prompt")).strip(),
            "denoising_strength": float(denoising_strength),
            "steps": int(steps),
            "cfg_scale": float(cfg_scale),
            "width": round_to_multiple(width, 8),
            "height": round_to_multiple(height, 8),
            "sampler_index": StabDiffAuto1111.SAMPLERS[sampler_index],
            "batch_size": min(StabDiffAuto1111.MAX_BATCH_SIZE, max(1, batch_size)),
            "seed": seed or -1
        }

        try:
            Gimp.progress_init("Standby...")
            Gimp.progress_set_text(random.choice(StabDiffAuto1111.GENERATION_MESSAGES))

            controlnet_units = []
            if cn1_enabled:
                controlnet_units.append(self.get_control_net_params(cn1_layer))
            if cn2_enabled:
                controlnet_units.append(self.get_control_net_params(cn2_layer))
            if len(controlnet_units) > 0:
                alwayson_scripts = {
                    "controlnet": {
                        "args": controlnet_units
                    }
                }
                data.update({"alwayson_scripts": alwayson_scripts})

            response = self.api.post("/sdapi/v1/img2img", data)

            StabDiffAuto1111.ResponseLayers(self, image_local, response, {
                "skip_annotator_layers": cn_skip_annotator_layers  # noqa
            }).resize(orig_width, orig_height)

        except Exception as ex:
            StabDiffAuto1111.LOGGER.exception("ERROR: StabDiffAuto1111.imageToImage")
            Gimp.message(repr(ex))
        finally:
            Gimp.progress_end()
            self.cleanup()

    def inpainting(self,
                   batch_size,
                   cfg_scale,
                   cn1_enabled,
                   cn1_layer,
                   cn2_enabled,
                   cn2_layer,
                   cn_skip_annotator_layers,
                   denoising_strength,
                   height,
                   inpaint_full_res,
                   invert_mask,
                   mask_blur,
                   n_prompt_prefix,
                   p_prompt_prefix,
                   resize_mode,
                   sampler_index,
                   seed,
                   steps,
                   width
                   ):
        image = self.image

        self.get_selection_bounds()  # Perhaps there are important side effects?

        init_images = [self.get_active_layer_as_base64()]
        mask = self.get_active_mask_as_base64()
        if mask == "":
            StabDiffAuto1111.LOGGER.exception("ERROR: StabDiffAuto1111.inpainting")
            raise Exception("Inpainting must use either a selection or layer mask")

        data = {
            "mask": mask,
            "mask_blur": mask_blur,
            "inpaint_full_res": inpaint_full_res,
            "inpaint_full_res_padding": 10,
            "inpainting_mask_invert": 1 if invert_mask else 0,
            "resize_mode": resize_mode,
            "init_images": init_images,
            "prompt": (p_prompt_prefix + " " + self.settings.get("prompt")).strip(),
            "negative_prompt": (n_prompt_prefix + " " + self.settings.get("negative_prompt")).strip(),
            "denoising_strength": float(denoising_strength),
            "steps": int(steps),
            "cfg_scale": float(cfg_scale),
            "width": round_to_multiple(width, 8),
            "height": round_to_multiple(height, 8),
            "sampler_index": StabDiffAuto1111.SAMPLERS[sampler_index],
            "batch_size": min(StabDiffAuto1111.MAX_BATCH_SIZE, max(1, batch_size)),
            "seed": seed or -1
        }

        try:
            Gimp.progress_init("Standby...")
            Gimp.progress_set_text(random.choice(StabDiffAuto1111.GENERATION_MESSAGES))

            controlnet_units = []
            if cn1_enabled:
                controlnet_units.append(self.get_control_net_params(cn1_layer))
            if cn2_enabled:
                controlnet_units.append(self.get_control_net_params(cn2_layer))

            if len(controlnet_units) > 0:
                alwayson_scripts = {
                    "controlnet": {
                        "args": controlnet_units
                    }
                }
                data.update({"alwayson_scripts": alwayson_scripts})

            response = self.api.post("/sdapi/v1/img2img", data)

            StabDiffAuto1111.ResponseLayers(self, image, response, {
                "skip_annotator_layers": cn_skip_annotator_layers  # noqa
            }).resize(
                self.image.get_width(), self.image.get_height())

        except Exception as ex:
            StabDiffAuto1111.LOGGER.exception("ERROR: StabDiffAuto1111.inpainting")
            Gimp.message(repr(ex))
        finally:
            Gimp.progress_end()
            self.cleanup()

    def text_to_image(self, p_prompt_prefix, n_prompt_prefix, seed, batch_size, steps, mask_blur, width, height, cfg_scale, denoising_strength, sampler_index, cn1_enabled, cn1_layer, cn2_enabled, cn2_layer, cn_skip_annotator_layers):
        if StabDiffAuto1111.DEBUG:
            StabDiffAuto1111.LOGGER.debug("text_to_image")
        image = self.image
        if image is None:
            raise ValueError("Image has been reset to None")

        x, y, orig_width, orig_height = self.get_selection_bounds()

        data = {
            "prompt": (p_prompt_prefix + " " + self.settings.get("prompt")).strip(),
            "negative_prompt": (n_prompt_prefix + " " + self.settings.get("negative_prompt")).strip(),
            "cfg_scale": float(cfg_scale),
            "denoising_strength": float(denoising_strength),
            "steps": int(steps),
            "width": round_to_multiple(width, 8),
            "height": round_to_multiple(height, 8),
            "mask_blur": int(mask_blur),   # Not in original code
            "sampler_index": StabDiffAuto1111.SAMPLERS[sampler_index],
            "batch_size": min(StabDiffAuto1111.MAX_BATCH_SIZE, max(1, batch_size)),
            "seed": seed or -1
        }

        try:
            Gimp.progress_init("Standby...")
            Gimp.progress_set_text(random.choice(StabDiffAuto1111.GENERATION_MESSAGES))

            controlnet_units = []
            if cn1_enabled:
                controlnet_units.append(self.get_control_net_params(cn1_layer))
            if cn2_enabled:
                controlnet_units.append(self.get_control_net_params(cn2_layer))

            if len(controlnet_units) > 0:
                alwayson_scripts = {
                    "controlnet": {
                        "args": controlnet_units
                    }
                }
                data.update({"alwayson_scripts": alwayson_scripts})

            response = self.api.post("/sdapi/v1/txt2img", data)

            StabDiffAuto1111.ResponseLayers(self, image, response, {
                "skip_annotator_layers": cn_skip_annotator_layers  # noqa
            }).resize(orig_width, orig_height).translate((x, y)).add_selection_as_mask()

        except Exception as ex:
            StabDiffAuto1111.LOGGER.exception("ERROR: StabDiffAuto1111.textToImage")
            Gimp.message(repr(ex))
        finally:
            Gimp.progress_end()
            self.cleanup()

    def show_layer_info(self, layer_index: int = 0):
        """ Show any layer info associated with the active layer """
        if StabDiffAuto1111.DEBUG:  # There's a bug where layer_index is oob, but I can't reproduce.
            StabDiffAuto1111.LOGGER.debug("layer_index = %d" % layer_index)
        layers_list: List[Gimp.Layer] = self.image.list_layers()
        if layers_list is None:
            raise ValueError("No layers list from image")
        l_count = len(layers_list)
        if (layer_index + 1) > l_count:
            e_message = "layer_index %d > %d: Out-Of-Bounds error." % (layer_index,  l_count)
            StabDiffAuto1111.LOGGER.error(e_message)
        # For now, let python raise the error.
        active_layer: Gimp.Layer = layers_list[layer_index]
        StabDiffAuto1111.write_layer_info(active_layer)

    def save_control_layer(self, active_layer: Gimp.Layer, module_index: int, model_index: int, weight: float, resize_mode_index: int, low_vram: bool,
                           control_mode: str, guidance_start: float,
                           guidance_end: float, guidance: float, processor_res: float,
                           threshold_a: float, threshold_b: float):
        """ Take the form params and save them to the layer as gimp.Parasite """
        cn_models = self.settings.get("cn_models", [])
        cn_settings = {
            "module": StabDiffAuto1111.CONTROLNET_MODULES[module_index],
            "model": cn_models[model_index],
            "weight": weight,
            "resize_mode": StabDiffAuto1111.CONTROLNET_RESIZE_MODES[resize_mode_index],
            "lowvram": low_vram,
            "control_mode": control_mode,
            "guidance_start": guidance_start,
            "guidance_end": guidance_end,
            "guidance": guidance,
            "processor_res": processor_res,
            "threshold_a": threshold_a,
            "threshold_b": threshold_b,
        }
        if active_layer:
            cn_layer = StabDiffAuto1111.LayerLocal(self, active_layer)
            cn_layer.save_data(cn_settings)
            cn_layer.rename("ControlNet" + str(cn_layer.id))
        else:
            self.LOGGER.error("Unable to obtain active Layer")

    def change_model(self, model_index: int):
        # FIXME: This seems to cause 500 error in server
        if self.settings.get("model") != model_index:
            Gimp.progress_init("Standby...")
            Gimp.progress_set_text("Changing model...")
            try:
                self.api.post("/sdapi/v1/options", {
                    "sd_model_checkpoint": self.models[model_index]  # noqa
                })
                self.settings.set("sd_model_checkpoint", model_index)
            except Exception:  # noqa
                StabDiffAuto1111.LOGGER.exception("Exception in change_model")
            Gimp.progress_end()

    def equip_widgets_checkpoint(self, dialog_in: GimpUi.Dialog) -> List[Gtk.Widget]:
        sd_model_checkpoint = self.settings.get("sd_model_checkpoint")
        if sd_model_checkpoint is None:
            err_message: str = "No setting for \"sd_model_checkpoint"
            StabDiffAuto1111.LOGGER.error(err_message + "\n" + self.settings.__str__())
            raise ValueError(err_message)

        if True:
            StabDiffAuto1111.LOGGER.debug("sd_model_checkpoint=%s" % sd_model_checkpoint)
        checkpoints_label: Gtk.Label = Gtk.Label(label="Checkpoint")
        checkpoints_combo: Gtk.ComboBoxText = Gtk.ComboBoxText.new()
        checkpoints_combo.set_name("sd_model_checkpoint")
        models: List[str] = self.settings.get("models", [])
        append_all_texts(checkpoints_combo, models)
        index: int
        try:
            index = models.index(sd_model_checkpoint)
        except ValueError:
            index = 0
            if StabDiffAuto1111.DEBUG:
                StabDiffAuto1111.LOGGER.exception("value \"%s\" is not in %s" % (sd_model_checkpoint, checkpoints_combo.get_name()))
        checkpoints_combo.set_active(index)

        h_box: Gtk.Box = Gtk.Box(spacing=6)
        h_box.pack_start(child=checkpoints_label, expand=False, fill=False, padding=2)  # noqa ide error
        h_box.pack_start(child=checkpoints_combo, expand=True, fill=True, padding=0)  # noqa ide error
        dialog_in.get_content_area().add(h_box)
        def response_handler(widget: GimpUi.Dialog, response_id: int):  # noqa ignore arguments
            match response_id:
                case Gtk.ResponseType.OK | Gtk.ResponseType.APPLY:
                    self.change_model(checkpoints_combo.get_active())  # Get the index
                case _:
                    if StabDiffAuto1111.DEBUG:
                        StabDiffAuto1111.LOGGER.debug("response from equip_widgets_checkpoint = " + str(response_id))

        dialog_in.connect("response", response_handler)

        return [checkpoints_combo]

    def equip_widgets_common(self, dialog_in: GimpUi.Dialog) -> List[Gtk.Widget]:
        p_prompt_label = Gtk.Label(label="Prompt prefix")
        positive_prompt_text_view: Gtk.TextView = Gtk.TextView()
        # set_hexpand(True) Must be called on a component within the grid for any of the grid's contained components to expand.
        positive_prompt_text_view.set_hexpand(True)
        positive_prompt_text_view.set_vexpand(True)
        n_prompt_label = Gtk.Label(label="Negative Prompt prefix")
        negative_prompt_entry = Gtk.Entry()
        positive_prompt_text_view.get_buffer().set_text(self.val_str("prompt_prefix"))
        negative_prompt_entry.set_text(self.val_str("negative_prompt_prefix"))

        seed_label = Gtk.Label(label="Seed (int)")
        seed_entry = Gtk.Entry()
        seed_entry.set_text(str(self.val_int("seed", -1)))
        restrict_to_ints(seed_entry)

        batch_size_scale: Gtk.Scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=Gtk.Adjustment(value=self.val_int("batch_size"), lower=1, upper=100.0, step_increment=1.1, page_increment=10.0, page_size=0.0))
        steps_scale: Gtk.Scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=Gtk.Adjustment(value=self.val_int("steps"), lower=10.0, upper=100.0, step_increment=1.1, page_increment=10.0, page_size=0.0))
        mask_blur_scale: Gtk.Scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=Gtk.Adjustment(value=self.val_float("mask_blur"), lower=1.0, upper=100.0, step_increment=1.0, page_increment=10.0, page_size=0.0))
        width_scale: Gtk.Scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=Gtk.Adjustment(value=self.val_int("width"), lower=64.0, upper=2048.0, step_increment=1, page_increment=16.0, page_size=0.0))
        height_scale: Gtk.Scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=Gtk.Adjustment(value=self.val_int("height"), lower=64.0, upper=2048.0, step_increment=1, page_increment=16.0, page_size=0.0))
        cfg_scale_scale: Gtk.Scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=Gtk.Adjustment(value=self.val_float("cfg_scale"), lower=0.0, upper=20.0, step_increment=0.5, page_increment=10.0, page_size=0.0))
        denoising_strength_scale: Gtk.Scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=Gtk.Adjustment(value=self.val_float("denoising_strength"), lower=0.0, upper=1.0, step_increment=0.01, page_increment=0.1, page_size=0.0))

        scale_cs: list[Gtk.Scale] = [
            batch_size_scale,
            steps_scale,
            mask_blur_scale,
            width_scale,
            height_scale,
            cfg_scale_scale,
            denoising_strength_scale,
        ]

        for scale_c in scale_cs:
            scale_c.set_value_pos(Gtk.PositionType.LEFT)
            scale_c.set_vexpand(False)
            scale_c.set_hexpand(True)

        batch_size_label: Gtk.Label = Gtk.Label(label="Batch Size")
        steps_label: Gtk.Label = Gtk.Label(label="Steps")
        mask_blur_label: Gtk.Label = Gtk.Label(label="Mask Blur")
        width_label: Gtk.Label = Gtk.Label(label="Width")
        height_label: Gtk.Label = Gtk.Label(label="Height")
        cfg_scale_label: Gtk.Label = Gtk.Label(label="C.F.G. Scale")
        denoising_strength_label: Gtk.Label = Gtk.Label(label="Denoising Strength")

        samplers_combo: Gtk.ComboBoxText = Gtk.ComboBoxText.new()
        for sis in StabDiffAuto1111.SAMPLERS:
            samplers_combo.append_text(sis)

        samplers_combo.set_active(StabDiffAuto1111.SAMPLERS.index("DPM++ 2M"))
        samplers_label: Gtk.Label = Gtk.Label(label="Sampler")

        grid_0: Gtk.Grid = Gtk.Grid()

        # Text entry fields
        grid_0.attach(child=p_prompt_label, left=0, top=0, width=1, height=2)  # noqa ide error
        grid_0.attach(child=positive_prompt_text_view, left=1, top=0, width=3, height=2)  # noqa ide error
        grid_0.attach(n_prompt_label, left=0, top=2, width=1, height=1)  # noqa ide error
        grid_0.attach(child=negative_prompt_entry, left=1, top=2, width=3, height=1)  # noqa ide error
        grid_0.attach(seed_label, left=0, top=3, width=1, height=1)  # noqa ide error
        grid_0.attach(child=seed_entry, left=1, top=3, width=3, height=1)  # noqa ide error

        # Sliders
        grid_0.attach(child=batch_size_label, left=0, top=4, width=1, height=1)  # noqa ide error
        grid_0.attach(child=batch_size_scale, left=1, top=4, width=3, height=1)  # noqa ide error
        grid_0.attach(child=steps_label, left=0, top=5, width=1, height=1)  # noqa ide error
        grid_0.attach(child=steps_scale, left=1, top=5, width=3, height=1)  # noqa ide error
        grid_0.attach(child=mask_blur_label, left=0, top=6, width=1, height=1)  # noqa ide error
        grid_0.attach(child=mask_blur_scale, left=1, top=6, width=3, height=1)  # noqa ide error
        grid_0.attach(child=width_label, left=0, top=7, width=1, height=1)  # noqa ide error
        grid_0.attach(child=width_scale, left=1, top=7, width=3, height=1)  # noqa ide error
        grid_0.attach(child=height_label, left=0, top=8, width=1, height=1)  # noqa ide error
        grid_0.attach(child=height_scale, left=1, top=8, width=3, height=1)  # noqa ide error
        grid_0.attach(child=cfg_scale_label, left=0, top=9, width=1, height=1)  # noqa ide error
        grid_0.attach(child=cfg_scale_scale, left=1, top=9, width=3, height=1)  # noqa ide error
        grid_0.attach(child=denoising_strength_label, left=0, top=10, width=1, height=1)  # noqa ide error
        grid_0.attach(child=denoising_strength_scale, left=1, top=10, width=3, height=1)  # noqa ide error

        # ComboBox
        grid_0.attach(child=samplers_label, left=0, top=11, width=1, height=1)  # noqa ide error
        grid_0.attach(child=samplers_combo, left=1, top=11, width=3, height=1)  # noqa ide error

        dialog_in.get_content_area().add(grid_0)

        positive_prompt_text_view.set_name("prompt_prefix")
        negative_prompt_entry.set_name("negative_prompt_prefix")
        seed_entry.set_name("seed")
        batch_size_scale.set_name("batch_size")
        steps_scale.set_name("steps")
        mask_blur_scale.set_name("mask_blur")
        width_scale.set_name("width")
        height_scale.set_name("height")
        cfg_scale_scale.set_name("cfg")
        denoising_strength_scale.set_name("denoising_strength")
        samplers_combo.set_name("samplers")
        
        return [
            p_prompt_label,
            positive_prompt_text_view,
            n_prompt_label,
            negative_prompt_entry,
            seed_label,
            seed_entry,
            batch_size_scale,
            steps_scale,
            mask_blur_scale,
            width_scale,
            height_scale,
            cfg_scale_scale,
            denoising_strength_scale,
            samplers_label,
            samplers_combo
        ]

    def equip_widgets_config(self, dialog_in: GimpUi.Dialog) -> List[Gtk.Widget]:
        p_prompt_label: Gtk.Label = Gtk.Label(label="Prompt")
        positive_prompt_text_view: Gtk.TextView = Gtk.TextView()
        # set_hexpand(True) Must be called on a component within the grid for any of the grid's contained components to expand.
        positive_prompt_text_view.set_hexpand(True)
        positive_prompt_text_view.set_vexpand(True)
        n_prompt_label: Gtk.Label = Gtk.Label(label="Negative Prompt")
        negative_prompt_entry: Gtk.Entry = Gtk.Entry()
        api_base_label: Gtk.Label = Gtk.Label(label="Auto1111 API base URL")
        api_base_entry: Gtk.Entry = Gtk.Entry()

        grid_0: Gtk.Grid = Gtk.Grid()
        grid_0.attach(child=p_prompt_label, left=0, top=0, width=1, height=2)  # noqa ide error
        grid_0.attach_next_to(positive_prompt_text_view, p_prompt_label, Gtk.PositionType.RIGHT, width=3, height=1)
        grid_0.attach_next_to(n_prompt_label, p_prompt_label, Gtk.PositionType.BOTTOM, width=1, height=1)
        grid_0.attach_next_to(negative_prompt_entry, n_prompt_label, Gtk.PositionType.RIGHT, width=3, height=1)
        grid_0.attach_next_to(api_base_label, n_prompt_label, Gtk.PositionType.BOTTOM, width=1, height=1)
        grid_0.attach_next_to(api_base_entry, api_base_label, Gtk.PositionType.RIGHT, width=3, height=1)
        dialog_in.get_content_area().add(grid_0)

        # Set widget values from MyShelf
        positive_prompt_text_view.get_buffer().set_text(self.val_str("prompt"))
        negative_prompt_entry.set_text(self.val_str("negative_prompt"))
        api_base_entry.set_text(self.val_str("api_base"))

        positive_prompt_text_view.set_name("prompt")
        negative_prompt_entry.set_name("negative_prompt")
        api_base_entry.set_name("api_base")

        def response_handler(widget: GimpUi.Dialog, response_id: int):  # noqa
            match response_id:
                case Gtk.ResponseType.OK | Gtk.ResponseType.APPLY:
                    self.config(val_text_view(positive_prompt_text_view), negative_prompt_entry.get_text(), api_base_entry.get_text())
                case _:
                    if StabDiffAuto1111.DEBUG:
                        StabDiffAuto1111.LOGGER.debug("response from equip_widgets_config = " + str(response_id))
        dialog_in.connect("response", response_handler)
        return [
                p_prompt_label,
                positive_prompt_text_view,
                n_prompt_label,
                negative_prompt_entry,
                api_base_label,
                api_base_entry
        ]

    def equip_widgets_controlnet(self, dialog_in: GimpUi.Dialog) -> List[Gtk.Widget]:
        # Labels
        modules_label: Gtk.Label = Gtk.Label(label="Modules")
        cn_models_label: Gtk.Label = Gtk.Label(label="ControlNet Models")
        weight_label: Gtk.Label = Gtk.Label(label="Weight")
        resize_mode_label: Gtk.Label = Gtk.Label(label="Resize Mode")
        control_mode_label: Gtk.Label = Gtk.Label(label="Control Mode")
        guidance_start_label: Gtk.Label = Gtk.Label(label="Guidance Start (T)")
        guidance_end_label: Gtk.Label = Gtk.Label(label="Guidance End (T)")
        guidance_label: Gtk.Label = Gtk.Label(label="Guidance")
        processor_resolution_label: Gtk.Label = Gtk.Label(label="Processor Resolution")
        threshold_a_label: Gtk.Label = Gtk.Label(label="Threshold A")
        threshold_b_label: Gtk.Label = Gtk.Label(label="Threshold B")

        # ComboBoxes
        modules_combo_box: Gtk.ComboBoxText = Gtk.ComboBoxText.new()
        cn_models_combo_box: Gtk.ComboBoxText = Gtk.ComboBoxText.new()
        resize_mode_combo_box: Gtk.ComboBoxText = Gtk.ComboBoxText.new()
        control_mode_combo_box: Gtk.ComboBox = Gtk.ComboBox.new()  # More general than ComboBoxText
        # set_hexpand(True) Must be called on a component within the grid for any of the grid's contained components to expand.
        modules_combo_box.set_hexpand(True)

        for entry in StabDiffAuto1111.CONTROLNET_MODULES:
            modules_combo_box.append_text(entry)
        cn_models: List[str] = self.settings.get("cn_models")
        if cn_models is None:
            raise ValueError("Could not obtain cn_models list")
        if len(cn_models) == 0:
            raise ValueError("cn_models list is empty.")
        append_all_texts(cn_models_combo_box, cn_models)

        for entry in StabDiffAuto1111.CONTROLNET_RESIZE_MODES:
            resize_mode_combo_box.append_text(entry)

        modules_combo_box.set_active(StabDiffAuto1111.CONTROLNET_MODULES.index("depth"))
        cn_models_combo_box.set_active(0)
        resize_mode_combo_box.set_active(StabDiffAuto1111.CONTROLNET_RESIZE_MODES.index("Scale to Fit (Inner Fit)"))

        config_combobox_dict_str_int(combo_box=control_mode_combo_box, dictionary=StabDiffAuto1111.CONTROL_MODES, default_value="My prompt is more important")

        # Scales
        cds = StabDiffAuto1111.CONTROLNET_DEFAULT_SETTINGS
        weight_scale: Gtk.Scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=Gtk.Adjustment(value=cds["weight"], lower=0.0, upper=2.0, step_increment=0.05, page_increment=0.5, page_size=0.0))
        guidance_start_scale: Gtk.Scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=Gtk.Adjustment(value=cds["guidance_start"], lower=0.0, upper=1.0, step_increment=0.01, page_increment=0.1, page_size=0.0))
        guidance_end_scale: Gtk.Scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=Gtk.Adjustment(value=cds["guidance_end"], lower=0.0, upper=1.0, step_increment=0.01, page_increment=0.1, page_size=0.0))
        guidance_scale: Gtk.Scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=Gtk.Adjustment(value=cds["guidance"], lower=0.0, upper=1.0, step_increment=0.01, page_increment=0.1, page_size=0.0))
        processor_res_scale: Gtk.Scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=Gtk.Adjustment(value=cds["processor_res"], lower=64.0, upper=2048.0, step_increment=1.0, page_increment=10.0, page_size=0.0))
        threshold_a_scale: Gtk.Scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=Gtk.Adjustment(value=cds["threshold_a"], lower=32.0, upper=2048.0, step_increment=16, page_increment=16.0, page_size=0.0))
        threshold_b_scale: Gtk.Scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=Gtk.Adjustment(value=cds["threshold_b"], lower=32.0, upper=2048.0, step_increment=16, page_increment=16.0, page_size=0.0))

        # CheckButtons
        low_vram_check_button: Gtk.CheckButton = Gtk.CheckButton(label="Low VRAM")

        grid_0: Gtk.Grid = Gtk.Grid()

        # noinspection PyUnresolvedReferences
        grid_0.add(modules_label)
        grid_0.attach_next_to(modules_combo_box, modules_label, Gtk.PositionType.RIGHT, 2, 1)
        grid_0.attach_next_to(cn_models_label, modules_label, Gtk.PositionType.BOTTOM, 1, 1)
        grid_0.attach_next_to(cn_models_combo_box, cn_models_label, Gtk.PositionType.RIGHT, 2, 1)
        grid_0.attach_next_to(weight_label, cn_models_label, Gtk.PositionType.BOTTOM, 1, 1)
        grid_0.attach_next_to(weight_scale, weight_label, Gtk.PositionType.RIGHT, 2, 1)
        grid_0.attach_next_to(resize_mode_label, weight_label, Gtk.PositionType.BOTTOM, 1, 1)
        grid_0.attach_next_to(resize_mode_combo_box, resize_mode_label, Gtk.PositionType.RIGHT, 2, 1)
        grid_0.attach_next_to(low_vram_check_button, resize_mode_label, Gtk.PositionType.BOTTOM, 3, 1)
        grid_0.attach_next_to(control_mode_label, low_vram_check_button, Gtk.PositionType.BOTTOM, 1, 1)
        grid_0.attach_next_to(control_mode_combo_box, control_mode_label, Gtk.PositionType.RIGHT, 2, 1)

        grid_0.attach_next_to(guidance_start_label, control_mode_label, Gtk.PositionType.BOTTOM, 1, 1)
        grid_0.attach_next_to(guidance_start_scale, guidance_start_label, Gtk.PositionType.RIGHT, 2, 1)
        grid_0.attach_next_to(guidance_end_label, guidance_start_label, Gtk.PositionType.BOTTOM, 1, 1)
        grid_0.attach_next_to(guidance_end_scale, guidance_end_label, Gtk.PositionType.RIGHT, 2, 1)
        grid_0.attach_next_to(guidance_label, guidance_end_label, Gtk.PositionType.BOTTOM, 1, 1)
        grid_0.attach_next_to(guidance_scale, guidance_label, Gtk.PositionType.RIGHT, 2, 1)
        grid_0.attach_next_to(processor_resolution_label, guidance_label, Gtk.PositionType.BOTTOM, 1, 1)
        grid_0.attach_next_to(processor_res_scale, processor_resolution_label, Gtk.PositionType.RIGHT, 2, 1)

        grid_0.attach_next_to(threshold_a_label, processor_resolution_label, Gtk.PositionType.BOTTOM, 1, 1)
        grid_0.attach_next_to(threshold_a_scale, threshold_a_label, Gtk.PositionType.RIGHT, 2, 1)
        grid_0.attach_next_to(threshold_b_label, threshold_a_label, Gtk.PositionType.BOTTOM, 1, 1)
        grid_0.attach_next_to(threshold_b_scale, threshold_b_label, Gtk.PositionType.RIGHT, 2, 1)

        dialog_in.get_content_area().add(grid_0)

        modules_combo_box.set_name("modules")
        cn_models_combo_box.set_name("cn_models")
        resize_mode_combo_box.set_name("resize_mode")
        control_mode_combo_box.set_name("control_mode")
        weight_scale.set_name("weight")
        guidance_start_scale.set_name("guidance_start")
        guidance_end_scale.set_name("guidance_end")
        guidance_scale.set_name("guidance")
        processor_res_scale.set_name("processor_res")
        threshold_a_scale.set_name("threshold_a")
        threshold_b_scale.set_name("threshold_b")
        low_vram_check_button.set_name("low_vram")

        return [
            # Labels
            modules_label,
            cn_models_label,
            weight_label,
            resize_mode_label,
            control_mode_label,
            guidance_start_label,
            guidance_end_label,
            guidance_label,
            processor_resolution_label,
            threshold_a_label,
            threshold_b_label,
            # ComboBoxes
            modules_combo_box,
            cn_models_combo_box,
            resize_mode_combo_box,
            control_mode_combo_box,
            # Scales
            weight_scale,
            guidance_start_scale,
            guidance_end_scale,
            guidance_scale,
            processor_res_scale,
            threshold_a_scale,
            threshold_b_scale,
            # CheckButtons
            low_vram_check_button
        ]

    # noinspection PyMethodMayBeStatic
    def equip_widgets_controlnet_options(self, dialog_in: GimpUi.Dialog) -> List[Gtk.Widget]:
        cn1_layers_combo: GimpUi.LayerComboBox = GimpUi.LayerComboBox().new(constraint=None, data=None)
        cn2_layers_combo: GimpUi.LayerComboBox = GimpUi.LayerComboBox().new(constraint=None, data=None)
        cn1_layers_combo.set_sensitive(False)
        cn2_layers_combo.set_sensitive(False)

        cn1_enabler_check_button: Gtk.CheckButton = Gtk.CheckButton(label="Enable ControlNet 1 Layer:")
        cn2_enabler_check_button: Gtk.CheckButton = Gtk.CheckButton(label="Enable ControlNet 2 Layer:")
        skip_annotator_layers_check_button: Gtk.CheckButton = Gtk.CheckButton(label="Skip annotator layers")

        def on_button_toggled(button: Gtk.CheckButton, name):
            match name:
                case "cn1_enabler_check_button":
                    cn1_layers_combo.set_sensitive(button.get_active())
                case "cn2_enabler_check_button":
                    cn2_layers_combo.set_sensitive(button.get_active())
                case "skip_annotator_layers_check_button":
                    pass
                case _:
                    pass

        cn1_enabler_check_button.connect("toggled", on_button_toggled, "cn1_enabler_check_button")
        cn2_enabler_check_button.connect("toggled", on_button_toggled, "cn2_enabler_check_button")
        skip_annotator_layers_check_button.connect("toggled", on_button_toggled, "skip_annotator_layers_check_button")

        # set_hexpand(True) Must be called on a component within the grid for any of the grid's contained components to expand.
        cn1_layers_combo.set_hexpand(True)

        grid_0: Gtk.Grid = Gtk.Grid()
        # noinspection PyUnresolvedReferences
        grid_0.add(cn1_enabler_check_button)
        grid_0.attach_next_to(child=cn1_layers_combo, sibling=cn1_enabler_check_button, side=Gtk.PositionType.RIGHT, width=2, height=1)
        grid_0.attach_next_to(child=cn2_enabler_check_button, sibling=cn1_enabler_check_button, side=Gtk.PositionType.BOTTOM, width=1, height=1)
        grid_0.attach_next_to(child=cn2_layers_combo, sibling=cn2_enabler_check_button, side=Gtk.PositionType.RIGHT, width=2, height=1)
        grid_0.attach_next_to(child=skip_annotator_layers_check_button, sibling=cn2_enabler_check_button, side=Gtk.PositionType.BOTTOM, width=3, height=1)

        dialog_in.get_content_area().add(grid_0)
        cn1_enabler_check_button.set_name("cn1_enabled")
        cn1_layers_combo.set_name("cn1_layer")
        cn2_enabler_check_button.set_name("cn2_enabled")
        cn2_layers_combo.set_name("cn2_layer")
        skip_annotator_layers_check_button.set_name("skip_annotator")
        return [
            cn1_enabler_check_button,
            cn1_layers_combo,
            cn2_enabler_check_button,
            cn2_layers_combo,
            skip_annotator_layers_check_button
        ]

    # noinspection PyMethodMayBeStatic
    def equip_widgets_image(self, dialog_in: GimpUi.Dialog) -> List[Gtk.Widget]:
        images_list_store: Gtk.ListStore = new_list_store_images()
        if images_list_store is None:
            raise ValueError("No Images store for combobox")
        image_count = len(images_list_store)  # noqa
        if image_count == 0:
            if StabDiffAuto1111.DEBUG:
                StabDiffAuto1111.LOGGER.debug("images_list_store is empty")
            return []

        images_label: Gtk.Label = Gtk.Label(label="Images")
        images_combo: Gtk.ComboBox = Gtk.ComboBox.new_with_model(images_list_store)
        # TODO: replace with config_combobox_liststore
        # A lot of code for more general control_mode_combo_box
        images_combo.set_active(0)
        cell_renderer_text = Gtk.CellRendererText()
        images_combo.pack_start(cell_renderer_text, True)
        images_combo.add_attribute(cell_renderer_text, "text", 2)
        # set_hexpand(True) Must be called on a component within the grid for any of the grid's contained components to expand.
        images_combo.set_hexpand(True)

        grid_0: Gtk.Grid = Gtk.Grid()
        grid_0.add(images_label)  # noqa
        grid_0.attach_next_to(images_combo, images_label, Gtk.PositionType.RIGHT, width=2, height=1)

        dialog_in.get_content_area().add(grid_0)
        images_combo.set_name("images")
        return [images_label, images_combo]

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def equip_widgets_img2img(self, dialog_in: GimpUi.Dialog) -> List[Gtk.Widget]:
        return []

    # noinspection PyMethodMayBeStatic
    def equip_widgets_inpainting(self, dialog_in: GimpUi.Dialog) -> List[Gtk.Widget]:
        invert_mask_check_button: Gtk.CheckButton = Gtk.CheckButton(label="Invert Mask")
        inpaint_whole_pic_check_button: Gtk.CheckButton = Gtk.CheckButton(label="Inpaint Whole Picture")
        invert_mask_check_button.set_name("invert_mask")
        inpaint_whole_pic_check_button.set_name("inpaint_full_res")

        inpainting_toggles_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        inpainting_toggles_box.pack_start(child=invert_mask_check_button, expand=True, fill=True, padding=0)  # noqa
        inpainting_toggles_box.pack_start(child=inpaint_whole_pic_check_button, expand=True, fill=True, padding=0)  # noqa
        dialog_in.get_content_area().add(inpainting_toggles_box)

        return [invert_mask_check_button, inpaint_whole_pic_check_button]

    def equip_widgets_layers(self, dialog_in: GimpUi.Dialog) -> List[Gtk.Widget]: pass

    # noinspection PyMethodMayBeStatic
    def equip_widgets_resize_mode(self, dialog_in: GimpUi.Dialog) -> List[Gtk.Widget]:
        resize_mode_combo_box: Gtk.ComboBox = Gtk.ComboBox.new()
        resize_mode_combo_box.set_hexpand(True)
        resize_mode_combo_box.set_name("resize_mode")
        config_combobox_dict_str_int(combo_box=resize_mode_combo_box, dictionary=StabDiffAuto1111.RESIZE_MODES, default_value="Just Resize")
        dialog_in.get_content_area().add(resize_mode_combo_box)
        return [resize_mode_combo_box]

    def equip_widgets_show_layer_info(self, dialog_in: GimpUi.Dialog) -> List[Gtk.Widget]:
        layer_combo_box: GimpUi.LayerComboBox = GimpUi.LayerComboBox().new(constraint=None, data=None)
        layer_combo_box.set_hexpand(True)
        dialog_in.get_content_area().add(layer_combo_box)
        def response_handler(widget: GimpUi.Dialog, response_id: int):  # noqa Ignore arguments
            match response_id:
                case Gtk.ResponseType.OK | Gtk.ResponseType.APPLY:
                    some_bool, layer_index = layer_combo_box.get_active()
                    # layer_index is 2 more than it should be!
                    # Does LayerComboBox have a bug? Are there 2 invisible elements before the ones shown?
                    StabDiffAuto1111.LOGGER.warning("layer_index=\"%s\" some_bool=%s" % (layer_index, str(some_bool)))
                    # FIXME: Sometimes this causes an OOB error, even when "corrected". I can't consistently reproduce.
                    self.show_layer_info(layer_index - LAYER_INDEX_CORRECTION)  # This is very strange, and pretty bad.
                case _:
                    if StabDiffAuto1111.DEBUG:
                        StabDiffAuto1111.LOGGER.debug("response from equip_widgets_show_layer_info = " + str(response_id))

        dialog_in.connect("response", response_handler)
        return [layer_combo_box]

    def equip_widgets_txt2img(self, dialog_in: GimpUi.Dialog) -> List[Gtk.Widget]:  # noqa Ignore arguments
        return []


# DialogPopulator cannot be defined in a separate file. It depends on StabDiffAuto1111, which is circular. The normal
# work-around of putting include statements causes a fatal error because gimp_env_init() ends up being invoked multiple
# times.
class DialogPopulator(Enum):
    CHECKPOINT = ("checkpoint", "equip_widgets_checkpoint")
    COMMON = ("common", "equip_widgets_common")
    CONFIG = ("config", "equip_widgets_config")
    CONTROLNET = ("controlnet", "equip_widgets_controlnet")
    CONTROLNET_OPTIONS = ("controlnet_options", "equip_widgets_controlnet_options")
    IMAGE = ("image", "equip_widgets_image")
    IMG2IMG = ("img2img", "equip_widgets_img2img")
    INPAINTING = ("inpainting", "equip_widgets_inpainting")
    LAYERS = ("layers", "equip_widgets_layers")
    RESIZE_MODE = ("resize_mode", "equip_widgets_resize_mode")
    SHOW_LAYER_INFO = ("show_layer_info", "equip_widgets_show_layer_info")
    TXT2IMG = ("txt2img", "equip_widgets_txt2img")

    def __init__(self, populator_name: str, dialog_widget_factory_name: str):
        self.populator_name: str = populator_name
        self._dialog_widget_factory_name: str = dialog_widget_factory_name
        # This is annoying that every value instance needs its own copy, and so much horizontal boilerplate.
        self._procedure_mappings_instance: Dict[str, List[StabDiffAuto1111.DialogPopulator]] = None  # noqa
        self.__widgets__: List[Gtk.Widget] = []
        self.__responses__: Dict[str, Any] = None  # noqa

    @property
    def widget_factory_name(self):
        return self._dialog_widget_factory_name

    @classmethod
    def _late_initialize(cls):
        """
        StabDiffAuto1111 is not fully defined until after the inner classes. So we must initialise DialogPopulator here.
        """
        cls.COMMON._procedure_mappings_instance = {
            # These will need to be rethought if procedure is invoked without an open image.
            StabDiffAuto1111.PYTHON_PROCEDURE_CONFIG_GLOBAL: [DialogPopulator.IMAGE, DialogPopulator.CONFIG],
            StabDiffAuto1111.PYTHON_PROCEDURE_CONFIG_MODEL: [DialogPopulator.CHECKPOINT],
            StabDiffAuto1111.PYTHON_PROCEDURE_CONTROLNET_LAYER: [DialogPopulator.LAYERS, DialogPopulator.CONTROLNET],
            StabDiffAuto1111.PYTHON_PROCEDURE_CONTROLNET_LAYER_CONTEXT: [DialogPopulator.LAYERS, DialogPopulator.CONTROLNET],
            StabDiffAuto1111.PYTHON_PROCEDURE_IMG2IMG:         [DialogPopulator.IMAGE,  DialogPopulator.RESIZE_MODE, DialogPopulator.COMMON, DialogPopulator.CONTROLNET_OPTIONS, DialogPopulator.TXT2IMG, DialogPopulator.IMG2IMG],
            StabDiffAuto1111.PYTHON_PROCEDURE_IMG2IMG_CONTEXT: [DialogPopulator.LAYERS, DialogPopulator.RESIZE_MODE, DialogPopulator.COMMON, DialogPopulator.CONTROLNET_OPTIONS, DialogPopulator.TXT2IMG, DialogPopulator.IMG2IMG],
            StabDiffAuto1111.PYTHON_PROCEDURE_INPAINTING: [DialogPopulator.IMAGE,  DialogPopulator.RESIZE_MODE, DialogPopulator.IMG2IMG, DialogPopulator.COMMON, DialogPopulator.CONTROLNET_OPTIONS, DialogPopulator.INPAINTING],
            StabDiffAuto1111.PYTHON_PROCEDURE_INPAINTING_CONTEXT: [DialogPopulator.IMAGE,  DialogPopulator.RESIZE_MODE, DialogPopulator.IMG2IMG, DialogPopulator.COMMON, DialogPopulator.CONTROLNET_OPTIONS, DialogPopulator.INPAINTING],
            StabDiffAuto1111.PYTHON_PROCEDURE_LAYER_INFO: [DialogPopulator.IMAGE, DialogPopulator.SHOW_LAYER_INFO],
            StabDiffAuto1111.PYTHON_PROCEDURE_LAYER_INFO_CONTEXT: [DialogPopulator.LAYERS, DialogPopulator.SHOW_LAYER_INFO],
            StabDiffAuto1111.PYTHON_PROCEDURE_TEXT2IMG: [DialogPopulator.COMMON, DialogPopulator.CONTROLNET_OPTIONS, DialogPopulator.TXT2IMG],
            StabDiffAuto1111.PYTHON_PROCEDURE_TEXT2IMG_CONTEXT: [DialogPopulator.LAYERS, DialogPopulator.COMMON, DialogPopulator.CONTROLNET_OPTIONS, DialogPopulator.TXT2IMG],
        }

    @classmethod
    def from_procedure_name(cls, procedure_name: str):
        if cls.COMMON._procedure_mappings_instance is None:
            if StabDiffAuto1111.DEBUG:
                StabDiffAuto1111.LOGGER.debug("_procedure_mappings_instance NOT initialized. Creating now...")
            cls._late_initialize()
        populators: List[StabDiffAuto1111.DialogPopulator] = cls.COMMON._procedure_mappings_instance[procedure_name]
        if populators is None:
            raise ValueError("No List[DialogPopulator]  for procedure " % procedure_name)
        if len(populators) == 0:
            raise ValueError("Empty List[DialogPopulator] for procedure " % procedure_name)
        populator: StabDiffAuto1111.DialogPopulator
        if StabDiffAuto1111.DEBUG:
            for populator in populators:
                StabDiffAuto1111.LOGGER.debug("Found populator %s for procedure %s" % (str(populator), procedure_name))
        return populators

    @classmethod
    def from_procedure(cls, procedure):
        return cls.from_procedure_name(procedure.get_name())

    @classmethod
    def merged_responses(cls, procedure_name: str) -> Dict[Any, Any]:
        merged_dict: Dict[Any, Any] = {}
        populator: DialogPopulator
        for populator in cls.from_procedure_name(procedure_name):
            if StabDiffAuto1111.DEBUG:
                StabDiffAuto1111.LOGGER.debug("%s" % str(populator))
            responses = populator.get_responses()
            if responses is not None:
                if responses:
                    StabDiffAuto1111.LOGGER.info("Found response for %s" % str(populator))
                    merged_dict.update(responses)
                else:
                    StabDiffAuto1111.LOGGER.info("Empty responses for %s" % str(populator))
            else:
                StabDiffAuto1111.LOGGER.info("No responses for %s" % str(populator))
        return merged_dict

    def add_components(self, plugin: StabDiffAuto1111, dialog_in: GimpUi.Dialog):
        if dialog_in is None:
            raise ValueError("dialog_in argument is unset")
        if plugin is None:
            raise ValueError("plugin is None.")
        dialog_widget_factory = getattr(plugin, self.widget_factory_name)
        if StabDiffAuto1111.DEBUG:
            StabDiffAuto1111.LOGGER.warning("Name of _dialog_widget_factory is %s " % self.widget_factory_name)
        self.__widgets__ = dialog_widget_factory(dialog_in)

    def _validate_widgeted(self, widget_producer: Callable[[List[Gtk.Widget]], List[Gtk.Widget]]) -> List[Gtk.Widget]:
        if self.__widgets__ is None:
            if StabDiffAuto1111.DEBUG:
                complaint: str = "%s: has no widgets" % str(self)
                StabDiffAuto1111.LOGGER.warning(complaint)
            return []
        else:
            return widget_producer(self.__widgets__)

    def get_check_buttons(self) -> List[Gtk.CheckButton]:
        return self._validate_widgeted(filt_check_buttons)  # noqa

    def get_toggle_buttons(self) -> List[Gtk.ToggleButton]:
        return self._validate_widgeted(filt_toggle_buttons)  # noqa

    def get_radio_buttons(self) -> List[Gtk.RadioButton]: # noqa ide cannot find Gtk.RadioButton
        return self._validate_widgeted(filt_radio_buttons)  # noqa

    def get_combo_boxes(self) -> List[Gtk.ComboBox]:
        return self._validate_widgeted(filt_combo_boxes)  # noqa

    def get_combo_box_texts(self) -> List[Gtk.ComboBoxText]:
        return self._validate_widgeted(filt_combo_box_texts)  # noqa

    def get_entries(self) -> List[Gtk.Entry]:
        return self._validate_widgeted(filt_entries)  # noqa

    def get_scales(self) -> List[Gtk.Scale]:
        return self._validate_widgeted(filt_scales)  # noqa

    def get_text_views(self) -> List[Gtk.TextView]:
        return self._validate_widgeted(filt_text_views)  # noqa

    def get_responses(self) -> Dict[str, Any]:
        return self.__responses__

    def assign_from_widgets(self, widgets: List[Gtk.Widget], widget_category) -> Dict[str, Any]:
        response_results: Dict[str, Any] = {}  # noqa
        if widgets is not None:
            if len(widgets) > 0:
                widget_kind = type(widgets[0]).__name__
                if StabDiffAuto1111.DEBUG:
                    StabDiffAuto1111.LOGGER.debug("There are %d %ss as locals of %s" % (len(widgets), widget_kind, self.populator_name))
                widget: Gtk.ComboBox
                for widget in widgets:
                    widget_name = widget.get_name()
                    widget_value = val_widget(widget)
                    message = "Found %s, value is \"%s\"" % (widget_name, str(widget_value))
                    response_results[widget_name] = widget_value
                    if isinstance(widget, Gtk.ComboBox):
                        index_name = widget_name + "_index"
                        index_value = val_combo_index(widget)
                        if isinstance(index_value, int):
                            message += ", index is %d" % index_value
                            response_results[index_name] = index_value
                        elif isinstance(index_value, tuple):
                            if StabDiffAuto1111.DEBUG:
                                complaint = "index_value is a %s wih value %s, extracting 2nd item" % (type(index_value).__name__, str(index_value))
                                StabDiffAuto1111.LOGGER.warning(complaint)
                            index_value = index_value[1]
                            response_results[index_name] = index_value
                        else:
                            complaint = "index_value is not an int, it is a %s wih value %s" % (type(index_value).__name__, str(index_value))
                            StabDiffAuto1111.LOGGER.error(complaint)
                    if StabDiffAuto1111.DEBUG:
                        StabDiffAuto1111.LOGGER.debug(message)
            else:
                if StabDiffAuto1111.DEBUG:
                    StabDiffAuto1111.LOGGER.warning("No %s widgets in populator \"%s\"" % (widget_category, self.populator_name))
        else:
            StabDiffAuto1111.LOGGER.error("None Widget List of %s in %s" % (widget_category, self.populator_name))
        return response_results

    # noinspection PyUnusedLocal
    def assign_results(self, widget=None, data=None):
        if StabDiffAuto1111.DEBUG:
            StabDiffAuto1111.LOGGER.debug("assign_results")
        response_results: Dict[str, Any] = {}  # noqa
        entries: List[Gtk.Entry] = self.get_entries()
        text_views: List[Gtk.TextView] = self.get_text_views()
        combo_boxes: List[Gtk.ComboBox] = self.get_combo_boxes()
        scales: List[Gtk.Scale] = self.get_scales()
        toggles: List[Gtk.ToggleButton] = self.get_toggle_buttons()
        response_results.update(self.assign_from_widgets(entries, Gtk.Entry.__name__))
        response_results.update(self.assign_from_widgets(text_views, Gtk.TextView.__name__))
        response_results.update(self.assign_from_widgets(combo_boxes, Gtk.ComboBox.__name__))
        response_results.update(self.assign_from_widgets(scales, Gtk.Scale.__name__))
        response_results.update(self.assign_from_widgets(toggles, Gtk.ToggleButton.__name__))
        if response_results is None:
            if StabDiffAuto1111.DEBUG:
                StabDiffAuto1111.LOGGER.info("No response_results found for populator \"%s\"" % self.populator_name)
            self.__responses__ = None
            return
        self.__responses__ = response_results

    # noinspection PyUnusedLocal
    def delete_results(self, widget=None, data=None):
        if StabDiffAuto1111.DEBUG:
            StabDiffAuto1111.LOGGER.debug("delete_results")
        self.__responses__ = None  # noqa


# Gimp 2.99.16 is using Python 3.10.12 (main, Jun 14 2023, 19:14:29)  [GCC 13.1.0 64 bit (AMD64)]
# StabDiffAuto1111.LOGGER.warning(sys.version)
# For Gimp.main invocation see source gimp_world\gimp\libgimp\gimp.c and
# https://developer.gimp.org/api/3.0/libgimp/func.main.html
Gimp.main(StabDiffAuto1111.__gtype__, sys.argv)
StabDiffAuto1111_LOADED_GLOBAL = True
