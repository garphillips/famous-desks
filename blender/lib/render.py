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
    c.adaptive_threshold = 0.02
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
    c.sample_clamp_indirect = 2.0  # scene-linear; the view exposure lifts it ~16x
    c.blur_glossy = 1.0
    c.caustics_reflective = False
    c.caustics_refractive = False
    c.use_light_tree = True
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    scene.render.image_settings.file_format = "PNG"
    scene.render.resolution_percentage = 100
    build_camera_finish(scene)
    # material/look finishing pass (grain attributes, bevels, lamp glow); once per scene
    finish_scene(scene)


# Camera finish, per camera kind: bloom on windows and sun patches, a light
# vignette, lateral chromatic aberration and film grain. Panoramas get no
# vignette or aberration (they'd wrap and smear); the plan gets nothing.
FINISH = {
    "bloom": 0.06,        # glare strength
    "bloom_from": 3.0,    # display-referred brightness where bloom starts
    "vignette": 0.22,     # darkening in the corners
    "aberration": 0.008,  # lens dispersion
    "grain": 0.035,       # +- relative noise per pixel
    "white_balance": (1.0, 1.0, 1.0),  # linear RGB gains; a room can set scene["white_balance"]
}


def _node(nt, kind, **settings):
    """New node; each setting is a node property or else an input's default value."""
    node = nt.nodes.new(kind)
    for name, value in settings.items():
        if hasattr(node, name):
            setattr(node, name, value)
        else:
            node.inputs[name].default_value = value
    return node


def build_camera_finish(scene):
    nt = bpy.data.node_groups.get("camera_finish")
    if nt:
        scene.compositing_node_group = nt
        return nt
    nt = bpy.data.node_groups.new("camera_finish", "CompositorNodeTree")
    nt.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    link = nt.links.new
    layers = nt.nodes.new("CompositorNodeRLayers")
    glare = _node(nt, "CompositorNodeGlare", Type="Bloom", Quality="High", Smoothness=0.3, Size=0.7)
    glare.name = "bloom"
    link(layers.outputs["Image"], glare.inputs["Image"])
    lens = _node(nt, "CompositorNodeLensdist", Type="Radial", Distortion=0.0, Jitter=True, Fit=True)
    lens.name = "aberration"
    link(glare.outputs["Image"], lens.inputs["Image"])

    # vignette: 1 - k * r^2 (r = distance from the centre, 1 at the corners)
    coords = nt.nodes.new("CompositorNodeImageCoordinates")
    link(layers.outputs["Image"], coords.inputs["Image"])
    centred = _node(nt, "ShaderNodeVectorMath", operation="MULTIPLY_ADD")
    centred.inputs[1].default_value = (2.0, 2.0, 0.0)
    centred.inputs[2].default_value = (-1.0, -1.0, 0.0)
    link(coords.outputs["Normalized"], centred.inputs[0])
    r2 = _node(nt, "ShaderNodeVectorMath", operation="DOT_PRODUCT")
    link(centred.outputs[0], r2.inputs[0])
    link(centred.outputs[0], r2.inputs[1])
    vig = _node(nt, "ShaderNodeMath", operation="MULTIPLY_ADD")
    vig.name = "vignette"
    vig.inputs[2].default_value = 1.0
    link(r2.outputs["Value"], vig.inputs[0])

    # grain: per-pixel white noise, multiplicative so it sits evenly across the tones
    noise = nt.nodes.new("ShaderNodeTexWhiteNoise")
    noise.noise_dimensions = "2D"
    link(coords.outputs["Pixel"], noise.inputs["Vector"])
    grain = _node(nt, "ShaderNodeMath", operation="MULTIPLY_ADD")
    grain.name = "grain"
    link(noise.outputs["Value"], grain.inputs[0])
    shade = _node(nt, "ShaderNodeMath", operation="MULTIPLY")
    link(vig.outputs[0], shade.inputs[0])
    link(grain.outputs[0], shade.inputs[1])
    out_mix = _node(nt, "ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
    out_mix.inputs["Factor"].default_value = 1.0
    link(lens.outputs["Image"], out_mix.inputs[6])
    link(shade.outputs[0], out_mix.inputs[7])
    out = nt.nodes.new("NodeGroupOutput")
    # (Mix sockets by index: 6/7 are the colour A/B, output 2 the colour result)
    balance = _node(nt, "ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY", Factor=1.0)
    balance.name = "white_balance"
    link(out_mix.outputs[2], balance.inputs[6])
    link(balance.outputs[2], out.inputs[0])
    scene.compositing_node_group = nt
    scene.render.use_compositing = True
    return nt


def set_camera_finish(scene, cam):
    """Tune the finish for this camera (call after its exposure is set)."""
    nt = scene.compositing_node_group
    kind = cam.get("kind")
    scene.render.use_compositing = bool(nt) and kind != "plan"
    if not nt or kind == "plan":
        return
    # Cube faces are stitched edge to edge in the viewer, so nothing that depends on
    # position in the frame (vignette, aberration) or spreads across it (bloom) can
    # run per face without leaving seams.
    face = kind == "cube_face"
    pano = face or cam.data.type == "PANO"
    f = FINISH
    bloom = nt.nodes["bloom"]
    # the compositor sees scene-linear light before the view exposure
    bloom.inputs["Threshold"].default_value = f["bloom_from"] / 2 ** scene.view_settings.exposure
    bloom.inputs["Strength"].default_value = 0.0 if face else f["bloom"]
    nt.nodes["aberration"].inputs["Dispersion"].default_value = 0.0 if pano else f["aberration"]
    nt.nodes["vignette"].inputs[1].default_value = 0.0 if pano else -f["vignette"] / 2
    nt.nodes["grain"].inputs[1].default_value = 2 * f["grain"]
    nt.nodes["grain"].inputs[2].default_value = 1.0 - f["grain"]
    nt.nodes["white_balance"].inputs[7].default_value = (*scene.get("white_balance", f["white_balance"]), 1.0)



# --- Output and format (panoramas, cube faces, close-ups) -----------------------------
# Kept apart from the quality/light-path settings above.


def render_camera(scene, cam, out_dir, scale=100, filename=None, fmt="PNG", quality=85):
    """Renders `cam` at its "res" x scale% to <out_dir>/<filename>.<ext>.
    quality applies to WEBP/JPEG; PNG is written as 8-bit RGB (cube faces for tiling)."""
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
    set_camera_finish(scene, cam)
    settings = scene.render.image_settings
    settings.file_format = fmt
    if fmt in ("WEBP", "JPEG"):
        settings.quality = quality
    else:
        settings.color_mode = "RGB"
        settings.color_depth = "8"
        settings.compression = 15
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
