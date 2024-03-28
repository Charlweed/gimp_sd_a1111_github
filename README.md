# Welcome to StableDiffusionAuto1111

**StableDiffusionAuto1111** is a plugin to connect the realtime - WSYWIG image editing of GIMP with the AI image generatiopn of Stable Diffusion via the API of AUTOMATIC1111's web api. This plugin is targeted for GIMP 3.0, which is not yet finished. The development and testing platform is GIMP 2.99+

This project was based upon ["stable-gimpfusion"]https://github.com/ArtBIT/stable-gimpfusion which uses the (soon obsolete) GIMP 2.10 api, and python 2.7. Enormous thanks to ArtBit for their work.

IMPORTANT: This project is an experiment and a demonstration, and is NOT supported. I wrote it to gain experience with the GIMP 3.0 api, and Stable Diffusion web apis. Issues are unlikely to be resolved, as I am writing GIMP 3.0 plugins for ComfyUI.


# Example usage (From stable-gimpfusion)

Using Mona Lisa as the ControlNet

<img src="https://raw.githubusercontent.com/ArtBIT/stable-gimpfusion/master/assets/monalisa.png" width="400" />

Converting it to Lady Gaga

<img src="https://raw.githubusercontent.com/ArtBIT/stable-gimpfusion/master/assets/monalisa-controlnet-to-ladygaga.png" width="400" />

And inpainting some nerdy glasses

<img src="https://raw.githubusercontent.com/ArtBIT/stable-gimpfusion/master/assets/ladygaga-inpainting.png" width="400" />
<img src="https://raw.githubusercontent.com/ArtBIT/stable-gimpfusion/master/assets/ladygaga-inpainting-result.png" width="400" />

See the demo video on YouTube

<a href="https://www.youtube.com/watch?v=4IuIKe1sEFY" title="Stable Gimpfusion Demo"><img src="https://raw.githubusercontent.com/ArtBIT/stable-gimpfusion/master/assets/youtube-icon.jpg" width="100" /></a>


# Prerequisites and Dependencies
You need to install stable-diffusion-webui, with [sd-webui-controlnet]https://github.com/Mikubill/sd-webui-controlnet, and have it running, and accepting connections without errors. See [stable-diffusion-webui]https://github.com/AUTOMATIC1111/stable-diffusion-uginwebui for AUTOMATIC1111 details.

# Installation
Currently, StableDiffusionAuto1111 can be installed into GIMP by creating a subdirectory named exactly "stable-gimpfusion" in one of GIMP's plug-in directories, and copying only the *.py, and *.json files from this repository into that sub-folder. For example, under "\~/AppData/Roaming/GIMP/2.99/plug-ins/stable-gimpfusion" or "\~/.config/GIMP/2.99/plug-ins/stable-gimpfusion".

It is not a good idea to clone or copy this entire repository into the plug-ins folder, because GIMP will read every file, and try to evaluate each as plug-in content. This raises security and performance issues. There are also issues with which GIMP plug-in directory you select (user v.s. system-wide), depending upon your system platform. These issues are expected to be resolved by the GIMP 3.0 release, but may cause confusion.

Personally, I have loosely followed the example of the apache web server. Outside of GIMP's default directories, I've created a directory "plugins-available". Running GIMP, I edited GIMP's "Plug-Ins Folders" preferences, and added the path of the "plugins-available" directory. Now, I can clone, copy, or symbolicly link this repository into plugins-available, excluding everything except the *.py, and *.json files. This is sufficient for this experimental project.


- On MacOS and Linux, ensure the execute bit is set on each .py file by running `chmod +x ./*.py`
- Restart Gimp, and you will see a new AI menu item
- Configure global properties via `StableDiffusionAuto1111 -> Config` and set the backend API URL base (should be `http://127.0.0.1:7860/` by default)

# Troubleshooting

- Make sure you're running the Automatic1111's Web UI in API mode (`--api`) [Automatic1111's StableDiffusion Web-UI API](https://github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/API) try accessing [http://127.0.0.1:7860/docs](http://127.0.0.1:7860/docs) and verify the `/sdapi/` routes are present to make sure it's running.
- Verify that whatever plugin folder you are using (~/.config/GIMP/2.99/plug-ins) is listed in the GIMP's plug-ins folders. (`Edit>Preferences>Folders>Plug-Ins`)

# Known bugs
Setting the global model causes an internal error in stable-diffusion-webui. It used to work, but it seems some update of stable-diffusion-webui broke this feature. I might fix this bug, but this project is unsupported.

# Version
The latest version of StableDiffusionAuto1111 [is visible through]https://gist.github.com/Charlweed/1e13ec25d0a22ac2837f127539874743

# License

[MIT](LICENSE)
