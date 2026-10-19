"""Render settings and the camera render loop."""

import os

import bpy

from .materials import finish_scene


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
    c = scene.cycles
    c.samples = samples
    c.use_adaptive_sampling = True
    c.adaptive_threshold = 0.03
    c.adaptive_min_samples = 0  # automatic
    c.use_denoising = True
    for attr, value in (("denoiser", "OPENIMAGEDENOISE"), ("denoising_input_passes", "RGB_ALBEDO_NORMAL"),
                        ("denoising_prefilter", "ACCURATE"), ("denoising_quality", "HIGH"),
                        ("denoising_use_gpu", True)):
        try:
            setattr(c, attr, value)
        except (TypeError, AttributeError):
            pass
    # Light paths: enough bounces for a daylit white room, clamped to keep
    # fireflies out of the dim corners. Caustics off (glass is thin and transparent).
    c.max_bounces = 10
    c.diffuse_bounces = 4
    c.glossy_bounces = 3
    c.transmission_bounces = 4
    c.transparent_max_bounces = 16
    c.sample_clamp_direct = 0.0
    c.sample_clamp_indirect = 4.0
    c.blur_glossy = 1.0
    c.caustics_reflective = False
    c.caustics_refractive = False
    c.use_light_tree = True
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Base Contrast"
    scene.render.image_settings.file_format = "PNG"
    scene.render.resolution_percentage = 100
    # material/look finishing pass (grain attributes, bevels, lamp glow); once per scene
    finish_scene(scene)


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
    scene.view_settings.exposure += cam.get("brighten", 0.0)
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
