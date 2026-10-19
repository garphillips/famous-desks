"""Render settings and the camera render loop."""

import os

import bpy


def configure_cycles(scene, samples=128):
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    try:
        prefs.compute_device_type = "METAL"
        prefs.get_devices()
        for device in prefs.devices:
            device.use = True
        scene.cycles.device = "GPU"
    except (TypeError, AttributeError):
        scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.use_denoising = True
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Base Contrast"
    scene.render.image_settings.file_format = "PNG"
    scene.render.resolution_percentage = 100


def render_camera(scene, cam, out_dir, scale=100, filename=None, fmt="PNG"):
    hidden = []
    for col_name in cam.get("hide", []):
        col = bpy.data.collections.get(col_name)
        if col:
            for obj in col.all_objects:
                if not obj.hide_render:
                    obj.hide_render = True
                    hidden.append(obj)
    exposure = scene.view_settings.exposure
    if "exposure" in cam:
        scene.view_settings.exposure = cam["exposure"]
    settings = scene.render.image_settings
    settings.file_format = fmt
    if fmt in ("WEBP", "JPEG"):
        settings.quality = 85
    scene.camera = cam
    w, h = cam["res"]
    scene.render.resolution_x, scene.render.resolution_y = int(w), int(h)
    scene.render.resolution_percentage = scale
    ext = {"PNG": "png", "WEBP": "webp", "JPEG": "jpg"}[fmt]
    scene.render.filepath = os.path.join(out_dir, f"{filename or cam.name}.{ext}")
    scene.render.use_file_extension = False
    bpy.ops.render.render(write_still=True)
    for obj in hidden:
        obj.hide_render = False
    scene.view_settings.exposure = exposure
    return scene.render.filepath
