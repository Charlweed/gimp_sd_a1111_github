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

import gi
import logging


gi.require_version('Gimp', '3.0')  # noqa: E402
gi.require_version('GimpUi', '3.0')  # noqa: E402
gi.require_version("Gtk", "3.0")  # noqa: E402
gi.require_version('Gdk', '3.0')  # noqa: E402
# noinspection PyUnresolvedReferences
from gi.repository import Gdk, Gio, Gimp, GimpUi, Gtk, GLib, GObject
from typing import Any, Dict, Callable, List

from urllib import request, error


# Global functions
def as_strings_deeply(data: Any):
    """Recursively converts dictionary keys to strings."""
    if isinstance(data, str):
        return str(data)
    if not isinstance(data, dict):
        return data
    return dict((str(k), as_strings_deeply(v))
                for k, v in data.items())


def append_all_texts(combo_box: Gtk.ComboBoxText, items: List[str]) -> Gtk.ComboBoxText:
    for item in items:
        combo_box.append_text(item)
    return combo_box


def config_combobox_dict_int_str(combo_box: Gtk.ComboBox, dictionary: Dict[str, int], default_value: str):
    config_combobox_dict_str_int(combo_box, reciprocal_dict(dictionary), default_value)


def config_combobox_dict_str_int(combo_box: Gtk.ComboBox, dictionary: Dict[str, int], default_value: str):
    list_store: Gtk.ListStore = Gtk.ListStore.new(types=[int, str])  # noqa n_columns unfilled
    for key, value in dictionary.items():
        row = [value, key]  # Deliberately inverted
        if key:
            if value is not None:
                list_store.append(row)
            else:
                raise ValueError("Missing value in dictionary for " + key)
        else:
            raise ValueError("Missing key in dictionary")
    index: int = dictionary[default_value]
    if index < 0:
        raise ValueError("Could not find \"%s\" in dictionary" % default_value)
    config_combobox_liststore(combo_box, list_store, index)


def config_combobox_liststore(combo_box: Gtk.ComboBox, list_store:  Gtk.ListStore, index: int):
    combo_box.set_model(list_store)
    combo_box.set_active(index)
    cell_renderer_text = Gtk.CellRendererText()
    combo_box.pack_start(cell_renderer_text, True)
    combo_box.add_attribute(cell_renderer_text, "text", 1)


def filt_check_buttons(widgets: List[Gtk.Widget]) -> List[Gtk.ComboBox]:
    return filt_widg(Gtk.CheckButton, widgets)  # noqa


def filt_combo_box_texts(widgets: List[Gtk.Widget]) -> List[Gtk.ComboBoxText]:
    return filt_widg(Gtk.ComboBoxText, widgets)  # noqa


def filt_combo_boxes(widgets: List[Gtk.Widget]) -> List[Gtk.ComboBox]:
    return filt_widg(Gtk.ComboBox, widgets)  # noqa


def filt_entries(widgets: List[Gtk.Widget]) -> List[Gtk.Entry]:
    return filt_widg(Gtk.Entry, widgets)  # noqa


def filt_radio_buttons(widgets: List[Gtk.Widget]) -> List[Gtk.ComboBox]:
    return filt_widg(Gtk.RadioButton, widgets)  # noqa


def filt_scales(widgets: List[Gtk.Widget]) -> List[Gtk.Scale]:
    return filt_widg(Gtk.Scale, widgets)  # noqa


def filt_text_views(widgets: List[Gtk.Widget]) -> List[Gtk.TextView]:
    return filt_widg(Gtk.TextView, widgets)  # noqa


def filt_toggle_buttons(widgets: List[Gtk.Widget]) -> List[Gtk.ComboBox]:
    return filt_widg(Gtk.ToggleButton, widgets)  # noqa


def filt_widg(widget_type: type, widgets: List[Gtk.Widget]) -> List[Gtk.Widget]:
    if widget_type is None:
        raise ValueError("widget_type cannot be none")

    if widgets is None:
        raise ValueError("widgets list cannot be none")

    if not widgets:
        return []

    def widg_pred(subject) -> bool:
        # type_actual = type(subject)
        it_is = isinstance(subject, widget_type)
        # message = "%s is a %s %s" % (type_actual.__name__, widget_type.__name__, str(it_is))
        # print(message)
        return it_is

    return list(filter(widg_pred, widgets))


def find_all_widgets(widget: Gtk.Widget) -> List[Gtk.Widget]:
    contained: List[Gtk.Widget] = []
    if hasattr(widget, 'get_child') and callable(getattr(widget, 'get_child')):  # rare, but happens
        child: Gtk.Widget = widget.get_child()
        contained.append(child)  # append one singleton item
        contained += find_all_widgets(child)  # append all of new list
    if hasattr(widget, 'get_children') and callable(getattr(widget, 'get_children')):  # true for all containers
        children: List[Gtk.Widget] = widget.get_children()
        for child_widget in children:
            contained.append(child_widget)  # append one singleton item
            contained += find_all_widgets(child_widget)  # append all of new list
    return contained


def new_box_of_radios(options: List[str], handler: Callable[[Any], None]) -> Gtk.Box:
    box_0: Gtk.Box = Gtk.Box()
    i: int = 1
    group: Gtk.RadioButton = None  # noqa
    for label in options:
        check_button: Gtk.RadioButton = Gtk.RadioButton.new_with_label_from_widget(group, label)  # noqa
        check_button.connect("toggled", handler, str(i))
        box_0.pack_start(check_button, False, False, 0)  # noqa
        group = check_button
        i += 1
    return box_0


def new_dialog_error_user(title_in: str, blurb_in: str, gimp_icon_name: str = GimpUi.ICON_DIALOG_ERROR) -> GimpUi.Dialog:
    dialog = GimpUi.Dialog(use_header_bar=True, title=title_in, role="User_Error")
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
    dialog.add_button(GLib.dgettext(None, "_OK"), Gtk.ResponseType.OK)
    geometry = Gdk.Geometry()  # noqa
    geometry.min_aspect = 0.5
    geometry.max_aspect = 1.0
    dialog.set_geometry_hints(None, geometry, Gdk.WindowHints.ASPECT)  # noqa
    dialog.show_all()
    return dialog


def new_dialog_info(title_in: str, blurb_in: str) -> GimpUi.Dialog:
    gimp_icon_name: str = GimpUi.ICON_DIALOG_INFORMATION
    dialog = GimpUi.Dialog(use_header_bar=True, title=title_in, role="Information")
    dialog_box = dialog.get_content_area()
    if blurb_in:
        label_and_icon_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        icon_image = Gtk.Image.new_from_icon_name(gimp_icon_name, Gtk.IconSize.DIALOG)  # noqa
        blurb_label: Gtk.Label = Gtk.Label(label=blurb_in)
        label_and_icon_box.pack_start(child=icon_image, expand=False, fill=False, padding=0)  # noqa
        label_and_icon_box.pack_start(child=blurb_label, expand=False, fill=False, padding=0)  # noqa
        label_and_icon_box.set_margin_start(40)
        label_and_icon_box.set_margin_end(40)
        label_and_icon_box.show_all()  # noqa
        dialog_box.add(label_and_icon_box)
    else:
        raise ValueError("new_dialog_info is missing blurb text.")

    # GIMP does something to the layout in dialogs. I'm not sure if I should force it to look more conventional.
    dialog.add_button(GLib.dgettext(None, "OK"), Gtk.ResponseType.OK)
    geometry = Gdk.Geometry()  # noqa
    # TODO: Far too much empty whitespace, but resizing toes not seem to work.
    geometry.min_aspect = 1.0
    geometry.max_aspect = 1.0
    dialog.set_geometry_hints(None, geometry, Gdk.WindowHints.ASPECT)  # noqa
    dialog.show_all()
    return dialog


def new_list_store_images() -> Gtk.ListStore:
    images_list_store: Gtk.ListStore = Gtk.ListStore.new(types=[int, int, str])  # noqa
    image: Gimp.Image
    i: int = 0
    for image in Gimp.list_images():
        row = [image.get_id(), i, image.get_name()]
        # message = "image_id=%d, index=%d, image_name=%s" % (row[0], row[1], row[2])
        # StabDiffAuto1111.LOGGER.debug(message)
        images_list_store.append(row)
        i += 1
    return images_list_store


def new_list_store_layers(image_in: Gimp.Image) -> Gtk.ListStore:
    if not image_in:
        raise ValueError("image_in argument cannot be None.")
    # Model row will be layer_id, index, name
    layers_list_store: Gtk.ListStore = Gtk.ListStore.new(types=[int, int, str])  # noqa
    layer: Gimp.Layer
    i: int = 0
    for layer in image_in.list_layers():
        row = [layer.get_id(), i, layer.get_name()]
        # message = "layer_id=%d, index=%d, layer_name=%s" % (row[0], row[1], row[2])
        layers_list_store.append(row)
        i += 1
    return layers_list_store


def new_list_store_selected_drawables(image_in: Gimp.Image) -> Gtk.ListStore:
    if not image_in:
        raise ValueError("image_in argument cannot be None.")
    # Model row will be layer_id, index, name
    selected_drawables_list_store: Gtk.ListStore = Gtk.ListStore.new(types=[int, int, str])  # noqa
    drawable: Gimp.Item
    i: int = 0
    for drawable in image_in.list_selected_drawables():
        row = [drawable.get_id(), i, drawable.get_name()]
        # message = "drawable_id=%d, index=%d, drawable_name=%s" % (row[0], row[1], row[2])
        selected_drawables_list_store.append(row)
        i += 1
    return selected_drawables_list_store


def pretty_name(ugly_name: str) -> str:
    fresh_name = ugly_name.replace("StabDiffAuto1111-", "")
    fresh_name = fresh_name.replace("-image-context", "")
    fresh_name = fresh_name.replace("-layer", "")
    fresh_name = fresh_name.replace("-layers-context", "")
    fresh_name = fresh_name.replace("-info", " info")
    fresh_name = fresh_name.replace("-model", " model")
    fresh_name = fresh_name.replace("2", " to ")
    fresh_name = fresh_name.replace("img", "image")
    fresh_name = fresh_name.replace("txt", "text")
    fresh_name = fresh_name.replace("-context", "")  # Keep as penultimate
    fresh_name = fresh_name.title()
    return fresh_name


def reciprocal_dict(dictionary: Dict[Any, Any]) -> Dict[Any, Any]:
    reciprocal: Dict[Any, Any] = {}
    for key, value in dictionary.items():
        reciprocal[value] = key  # Deliberately inverted
    return reciprocal


def restrict_to_ints(widget: Gtk.Entry):
    # noinspection PyUnusedLocal
    def filter_numbers(entry: Gtk.Entry, *args):
        text = entry.get_text().strip()
        entry.set_text(''.join([i for i in text if i in '0123456789-']))

    widget.connect('changed', filter_numbers)


def restrict_to_numbers(widget: Gtk.Entry):
    # noinspection PyUnusedLocal
    def filter_numbers(entry: Gtk.Entry, *args):
        text = entry.get_text().strip()
        entry.set_text(''.join([i for i in text if i in '0123456789.-']))

        widget.connect('changed', filter_numbers)


def round_to_multiple(value, multiple):
    return multiple * round(float(value) / multiple)


def server_online(url_in: str):
    try:
        request.urlopen(url=url_in, timeout=3)
        return True
    except error.URLError:
        logging.getLogger("URLError").exception("Could not connect to %s" % url_in)
        return False


def val_combo_index(cbox: Gtk.ComboBox) -> int:
    return cbox.get_active()


def val_combo(cbox: Gtk.ComboBox):
    return cbox.get_model()[cbox.get_active_iter()][0]  # noqa


def val_entry(an_entry: Gtk.Entry):
    return an_entry.get_text()


def val_scale(a_scale: Gtk.Scale):
    return a_scale.get_value()


def val_text_view(a_text_view: Gtk.TextView):
    buffer: Gtk.TextBuffer = a_text_view.get_buffer()
    start: Gtk.TextIter = buffer.get_start_iter()
    end: Gtk.TextIter = buffer.get_end_iter()
    return buffer.get_text(start, end, False)


def val_widget(a_widget: Gtk.Widget):
    if isinstance(a_widget, GimpUi.LayerComboBox):
        result = val_combo(a_widget)  # noqa
        if type(result) is tuple:
            return result[1]  # First or second value of this weird tuple?
        else:
            return result
    if isinstance(a_widget, Gtk.ComboBox): return val_combo(a_widget)  # noqa
    if isinstance(a_widget, Gtk.Entry): return a_widget.get_text() # noqa
    if isinstance(a_widget, Gtk.Scale): return a_widget.get_value()  # noqa
    if isinstance(a_widget, Gtk.TextView): return val_text_view(a_widget)  # noqa
    if isinstance(a_widget, Gtk.ToggleButton): return a_widget.get_active()  # noqa
