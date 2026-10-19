"""Shared material library. Blockout-level for now; refined in the detail pass."""

import bpy


def _base(name):
    mat = bpy.data.materials.new(name)
    try:
        mat.use_nodes = True
    except AttributeError:
        pass  # Blender 5+: materials always use nodes
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat, nt, bsdf


def solid(name, color, roughness=0.5, metallic=0.0, emission=0.0):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat, _, bsdf = _base(name)
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*color, 1)
        bsdf.inputs["Emission Strength"].default_value = emission
    mat.diffuse_color = (*color, 1)
    return mat


def _projected(nt, horizontal, vertical):
    """World-space coordinates projected onto a plane, so patterns line up across separate objects."""
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    comb = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(geo.outputs["Position"], sep.inputs[0])
    nt.links.new(sep.outputs[horizontal], comb.inputs["X"])
    nt.links.new(sep.outputs[vertical], comb.inputs["Y"])
    return comb.outputs[0]


def _brick_pattern(name, horizontal, vertical, width, row, mortar, c1, c2, cm, roughness, bump):
    mat, nt, bsdf = _base(name)
    tex = nt.nodes.new("ShaderNodeTexBrick")
    nt.links.new(_projected(nt, horizontal, vertical), tex.inputs["Vector"])
    tex.inputs["Scale"].default_value = 1.0
    tex.inputs["Brick Width"].default_value = width
    tex.inputs["Row Height"].default_value = row
    tex.inputs["Mortar Size"].default_value = mortar
    tex.inputs["Color1"].default_value = (*c1, 1)
    tex.inputs["Color2"].default_value = (*c2, 1)
    tex.inputs["Mortar"].default_value = (*cm, 1)
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = roughness
    bmp = nt.nodes.new("ShaderNodeBump")
    bmp.invert = True
    bmp.inputs["Strength"].default_value = bump
    nt.links.new(tex.outputs["Fac"], bmp.inputs["Height"])
    nt.links.new(bmp.outputs["Normal"], bsdf.inputs["Normal"])
    mat.diffuse_color = (*c1, 1)
    return mat


def painted_brick(axis):
    """Whitewashed brick. axis = the world axis the wall runs along ('X' or 'Y')."""
    name = f"painted_brick_{axis.lower()}"
    return bpy.data.materials.get(name) or _brick_pattern(
        name, axis, "Z", 0.30, 0.085, 0.012,
        (0.86, 0.85, 0.82), (0.80, 0.79, 0.76), (0.70, 0.69, 0.66), 0.85, 0.35,
    )


def floorboards():
    return bpy.data.materials.get("floorboards") or _brick_pattern(
        "floorboards", "Y", "X", 1.9, 0.16, 0.003,
        (0.36, 0.17, 0.06), (0.30, 0.13, 0.04), (0.08, 0.04, 0.02), 0.35, 0.1,
    )


def glass():
    mat = bpy.data.materials.get("glass")
    if mat:
        return mat
    mat, nt, bsdf = _base("glass")
    out = nt.nodes["Material Output"]
    transparent = nt.nodes.new("ShaderNodeBsdfTransparent")
    glossy = nt.nodes.new("ShaderNodeBsdfGlossy")
    glossy.inputs["Roughness"].default_value = 0.02
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = 0.08
    nt.links.new(transparent.outputs[0], mix.inputs[1])
    nt.links.new(glossy.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    nt.nodes.remove(bsdf)
    mat.diffuse_color = (0.7, 0.8, 0.9, 0.3)
    return mat


def library():
    """Named materials every room can draw from."""
    return {
        "plaster": solid("plaster", (0.82, 0.81, 0.78), 0.9),
        "brick_x": painted_brick("X"),
        "brick_y": painted_brick("Y"),
        "floor": floorboards(),
        "ceiling_wood": solid("ceiling_wood", (0.42, 0.26, 0.13), 0.7),
        "beam_wood": solid("beam_wood", (0.48, 0.30, 0.15), 0.75),
        "oak": solid("oak", (0.45, 0.25, 0.10), 0.5),
        "pine": solid("pine", (0.55, 0.33, 0.14), 0.55),
        "lino_green": solid("lino_green", (0.07, 0.12, 0.09), 0.45),
        "steel_black": solid("steel_black", (0.02, 0.02, 0.02), 0.4, 0.6),
        "sash_white": solid("sash_white", (0.85, 0.85, 0.83), 0.4),
        "glass": glass(),
        "aluminium": solid("aluminium", (0.75, 0.76, 0.78), 0.25, 1.0),
        "plastic_black": solid("plastic_black", (0.02, 0.02, 0.02), 0.35),
        "plastic_white": solid("plastic_white", (0.85, 0.85, 0.84), 0.3),
        "screen": solid("screen", (0.01, 0.01, 0.012), 0.08),
        "paper": solid("paper", (0.85, 0.84, 0.80), 0.8),
        "cardboard": solid("cardboard", (0.45, 0.32, 0.18), 0.85),
        "fabric_black": solid("fabric_black", (0.03, 0.03, 0.03), 0.9),
        "wicker": solid("wicker", (0.50, 0.38, 0.22), 0.9),
        "lampshade": solid("lampshade", (0.85, 0.72, 0.52), 0.8),
        "art_dark": solid("art_dark", (0.06, 0.07, 0.06), 0.7),
        "garden": solid("garden", (0.12, 0.22, 0.07), 0.9),
        "foliage": solid("foliage", (0.08, 0.18, 0.05), 0.9),
    }


BOOK_COLOURS = [
    (0.80, 0.78, 0.72), (0.05, 0.05, 0.05), (0.08, 0.15, 0.35), (0.55, 0.10, 0.08),
    (0.85, 0.65, 0.10), (0.15, 0.30, 0.25), (0.92, 0.92, 0.90), (0.30, 0.45, 0.60),
    (0.65, 0.55, 0.40), (0.40, 0.05, 0.20), (0.20, 0.20, 0.22), (0.75, 0.35, 0.20),
]


def book_materials():
    return [solid(f"book_{i:02d}", c, 0.6) for i, c in enumerate(BOOK_COLOURS)]
