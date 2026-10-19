"""Shared material library: scanned PBR textures where they beat procedural, and
procedural node materials for the rest (and as a fallback when the texture
cache is missing: run python3 -I blender/assets/fetch.py).

Scanned textures (blender/assets/manifest/textures.json) are colour, roughness
and displacement maps; displacement only drives a Bump node. Builder meshes have
no UVs, so textures are projected triplanar in world space (walls), per floorboard
(floor), in object space (props), or along each part's grain frame (wood, brushed
metal), at real-world scale, with a random offset per part. A grime layer (dust and smudges, also
scanned) breaks up roughness and colour.

Patterns come from:
- world position, for things that must line up across objects (brick, floor wear);
- the floorboard attributes board_id / board_rand (see lib.architecture), so each
  real board piece gets its own tone and patch of the scan;
- the "grain" point attribute that finish_scene() writes on every mesh: per
  island (each Builder box/cylinder), a local frame whose X runs along the
  island's longest axis, plus a random offset, so wood grain follows each board
  and every piece is cut from a different part of the "log" (with a face-domain
  "grain_normal" saying which cross-grain axis runs across each face);
- the "island_rand" point attribute (0..1 per island), for per-object colour
  variation (books, paper, cardboard).

finish_scene() also adds small bevels to Builder furniture and the optional lamp
glow. It runs from render.configure_cycles(), so build.py applies it after the
room script has built everything.
"""

import math
import random

import bpy
import numpy as np

from . import assets

# ----------------------------------------------------------------------------
# Node graph helpers
# ----------------------------------------------------------------------------


class _G:
    """Tiny helper for building shader node graphs from code."""

    def __init__(self, nt):
        self.nt = nt

    def node(self, kind, **props):
        n = self.nt.nodes.new(kind)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def set(self, sock, val):
        if isinstance(val, bpy.types.NodeSocket):
            self.nt.links.new(val, sock)
            return
        if isinstance(val, (tuple, list)):
            if sock.type == "RGBA" and len(val) == 3:
                val = (*val, 1.0)
            elif sock.type in ("VALUE", "INT"):
                raise TypeError(f"vector given for scalar socket {sock.name}")
        sock.default_value = val

    def inp(self, node, key):
        for s in node.inputs:
            if s.identifier == key:
                return s
        return node.inputs[key]

    def out(self, node, key):
        for s in node.outputs:
            if s.identifier == key:
                return s
        return node.outputs[key]

    def math(self, op, a, b=0.0, c=0.0, clamp=False):
        n = self.node("ShaderNodeMath", operation=op, use_clamp=clamp)
        self.set(n.inputs[0], a)
        self.set(n.inputs[1], b)
        self.set(n.inputs[2], c)
        return n.outputs[0]

    def vmath(self, op, a, b=(0, 0, 0)):
        n = self.node("ShaderNodeVectorMath", operation=op)
        self.set(n.inputs[0], a)
        self.set(n.inputs[1], b)
        return n.outputs["Value"] if op in ("LENGTH", "DOT_PRODUCT", "DISTANCE") else n.outputs["Vector"]

    def vec(self, x, y, z):
        n = self.node("ShaderNodeCombineXYZ")
        for i, v in enumerate((x, y, z)):
            self.set(n.inputs[i], v)
        return n.outputs[0]

    def sep(self, v):
        n = self.node("ShaderNodeSeparateXYZ")
        self.set(n.inputs[0], v)
        return n.outputs[0], n.outputs[1], n.outputs[2]

    def mix(self, fac, a, b, blend="MIX", clamp=True):
        n = self.node("ShaderNodeMix", data_type="RGBA", blend_type=blend, clamp_result=clamp)
        self.set(self.inp(n, "Factor_Float"), fac)
        self.set(self.inp(n, "A_Color"), a)
        self.set(self.inp(n, "B_Color"), b)
        return self.out(n, "Result_Color")

    def mixf(self, fac, a, b):
        n = self.node("ShaderNodeMix", data_type="FLOAT")
        self.set(self.inp(n, "Factor_Float"), fac)
        self.set(self.inp(n, "A_Float"), a)
        self.set(self.inp(n, "B_Float"), b)
        return self.out(n, "Result_Float")

    def map(self, v, fmin, fmax, tmin=0.0, tmax=1.0, interp="LINEAR"):
        n = self.node("ShaderNodeMapRange", interpolation_type=interp, clamp=True)
        self.set(n.inputs["Value"], v)
        self.set(n.inputs["From Min"], fmin)
        self.set(n.inputs["From Max"], fmax)
        self.set(n.inputs["To Min"], tmin)
        self.set(n.inputs["To Max"], tmax)
        return n.outputs["Result"]

    def noise(self, vec, scale=1.0, detail=2.0, rough=0.5, distortion=0.0):
        n = self.node("ShaderNodeTexNoise")
        self.set(n.inputs["Vector"], vec)
        self.set(n.inputs["Scale"], scale)
        self.set(n.inputs["Detail"], detail)
        self.set(n.inputs["Roughness"], rough)
        self.set(n.inputs["Distortion"], distortion)
        return n.outputs["Factor"]

    def white(self, vec):
        n = self.node("ShaderNodeTexWhiteNoise", noise_dimensions="3D")
        self.set(n.inputs["Vector"], vec)
        return n.outputs["Value"], n.outputs["Color"]

    def position(self):
        return self.node("ShaderNodeNewGeometry").outputs["Position"]

    def normal(self):
        return self.node("ShaderNodeNewGeometry").outputs["Normal"]

    def obj_coords(self):
        return self.node("ShaderNodeTexCoord").outputs["Object"]

    def attr(self, name):
        n = self.node("ShaderNodeAttribute", attribute_type="GEOMETRY", attribute_name=name)
        return n.outputs["Vector"], n.outputs["Fac"]

    def scale(self, v, s):
        return self.vmath("MULTIPLY", v, s)

    def bump(self, height, strength=0.3, distance=0.01, normal=None, invert=False):
        n = self.node("ShaderNodeBump", invert=invert)
        self.set(n.inputs["Height"], height)
        self.set(n.inputs["Strength"], strength)
        self.set(n.inputs["Distance"], distance)
        if normal is not None:
            self.set(n.inputs["Normal"], normal)
        return n.outputs["Normal"]

    def hsv(self, color, hue=0.5, sat=1.0, val=1.0):
        n = self.node("ShaderNodeHueSaturation")
        self.set(n.inputs["Hue"], hue)
        self.set(n.inputs["Saturation"], sat)
        self.set(n.inputs["Value"], val)
        self.set(n.inputs["Color"], color)
        return n.outputs["Color"]

    def tex(self, img, vec, box=0.0):
        """Image texture; box > 0 is box (triplanar) projection with that blend."""
        n = self.node("ShaderNodeTexImage", image=img, projection="BOX" if box else "FLAT")
        if box:
            n.projection_blend = box
        self.set(n.inputs["Vector"], vec)
        return n.outputs["Color"]

    def bw(self, color):
        n = self.node("ShaderNodeRGBToBW")
        self.set(n.inputs[0], color)
        return n.outputs[0]

    def gray(self, v):
        return self.vec(v, v, v)


def _new(name, viewport_color):
    """Fresh node material with a Principled BSDF wired to the output."""
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
    mat.diffuse_color = (*viewport_color[:3], 1)
    return mat, _G(nt), bsdf


def _cached(name, fn):
    return bpy.data.materials.get(name) or fn(name)


def _principled(g, bsdf, **inputs):
    names = {
        "color": "Base Color", "rough": "Roughness", "metal": "Metallic", "normal": "Normal",
        "sheen": "Sheen Weight", "sheen_tint": "Sheen Tint", "sheen_rough": "Sheen Roughness",
        "coat": "Coat Weight", "coat_rough": "Coat Roughness", "spec": "Specular IOR Level",
        "emit_color": "Emission Color", "emit": "Emission Strength", "sss": "Subsurface Weight",
        "sss_radius": "Subsurface Radius", "aniso": "Anisotropic", "ior": "IOR",
        "transmission": "Transmission Weight", "alpha": "Alpha",
    }
    for k, v in inputs.items():
        g.set(bsdf.inputs[names[k]], v)


# ----------------------------------------------------------------------------
# Scanned texture helpers
# ----------------------------------------------------------------------------

BRICK = "ph_painted_brick"
PLASTER = "ph_white_plaster_02"
OAK = "ph_oak_veneer_01"
FLOOR_WOOD = "acg_Wood063"
TIMBER = "acg_Wood060"
PINE = "acg_Wood092"
CARDBOARD = "acg_Cardboard004"
PAPER = "acg_Paper001"
KNIT = "acg_Fabric030"
LEATHER = "acg_Leather027"
PLASTIC = "acg_Plastic012A"
BRUSHED = "acg_Metal009"
DUST = "acg_SurfaceImperfections015"
SMUDGE = "acg_SurfaceImperfections003"

_ROLES = {"ph": {"col": "diff", "rough": "rough", "disp": "disp"},
          "acg": {"col": "Color", "rough": "Roughness", "disp": "Displacement", "mask": "Opacity"}}


def _map_file(asset_id, role):
    src, base = asset_id.split("_", 1)
    if src == "ph":
        return f"{base}_{_ROLES[src][role]}_2k.jpg"
    return f"{base}_2K-JPG_{_ROLES[src][role]}.jpg"


def _image(asset_id, role):
    img = bpy.data.images.load(assets.path(asset_id, _map_file(asset_id, role)), check_existing=True)
    if role != "col":
        img.colorspace_settings.name = "Non-Color"
    return img


_missing = set()


def _have(*ids):
    """True when every texture is in the cache; otherwise warn once and use procedural."""
    ok = True
    for a in ids:
        try:
            assets.path(a, _map_file(a, "mask" if a in (DUST, SMUDGE) else "col"))
        except (KeyError, FileNotFoundError) as e:
            ok = False
            if a not in _missing:
                _missing.add(a)
                print(f"materials: {e} (procedural fallback)")
    return ok


def _scan(g, asset_id, vec, box=0.0, roles=("col", "rough", "disp")):
    return [g.tex(_image(asset_id, r), vec, box) for r in roles]


def _world_vec(g, size, offset=(0.0, 0.0, 0.0)):
    return g.vmath("ADD", g.scale(g.position(), (1 / size,) * 3), offset)


def _tri_weights(g, sharp=6.0):
    """Triplanar blend weights (wx, wy, wz) from the world normal: |n|^sharp, normalised,
    so flat faces take one projection and only rounded arrises blend."""
    nx, ny, nz = g.sep(g.normal())
    w = [g.math("POWER", g.math("ABSOLUTE", n), sharp) for n in (nx, ny, nz)]
    total = g.math("MAXIMUM", g.math("ADD", g.math("ADD", w[0], w[1]), w[2]), 1e-4)
    return [g.math("DIVIDE", wi, total) for wi in w]


def _tri_planes(g, size):
    """World-space planar coordinates per axis at real scale, each with its own offset:
    X faces (y, z), Y faces (x, z), Z faces (x, y). Vertical faces keep z as V, so
    brick courses stay level and line up from wall faces into reveals."""
    x, y, z = g.sep(g.position())
    k = 1.0 / size
    return [g.vec(g.math("MULTIPLY", a, k), g.math("MULTIPLY", b, k), 0.0)
            for a, b in ((g.math("ADD", y, 0.37), z), (x, z), (g.math("ADD", x, 0.21), g.math("ADD", y, 0.53)))]


def _tri_blend(g, weights, values, color=True):
    """Weighted sum of three per-axis samples (colours or scalars)."""
    if color:
        terms = [g.vmath("MULTIPLY", v, g.gray(w)) for v, w in zip(values, weights)]
        return g.vmath("ADD", g.vmath("ADD", terms[0], terms[1]), terms[2])
    terms = [g.math("MULTIPLY", v, w) for v, w in zip(values, weights)]
    return g.math("ADD", g.math("ADD", terms[0], terms[1]), terms[2])


def _tri_scan(g, asset_id, size, roles=("col", "rough", "disp"), sharp=6.0):
    """Scanned maps projected triplanar in world space (see _tri_planes), blended by
    the surface normal. Returns one blended output per role (colour for 'col',
    scalar for the others)."""
    weights = _tri_weights(g, sharp)
    planes = _tri_planes(g, size)
    out = []
    for role in roles:
        img = _image(asset_id, role)
        samples = [g.tex(img, p) for p in planes]
        if role == "col":
            out.append(_tri_blend(g, weights, samples))
        else:
            out.append(_tri_blend(g, weights, [g.bw(c) for c in samples], color=False))
    return out


def _obj_vec(g, size):
    """Object space, real-world scale, every part from a different patch of the texture."""
    _, rnd = g.attr("island_rand")
    off = g.scale(g.vec(rnd, rnd, rnd), (13.1, 7.7, 3.3))
    return g.vmath("ADD", g.scale(g.obj_coords(), (1 / size,) * 3), off)


def _grain_vec(g, size, swap=False, along=None, across=None):
    """Flat mapping along each part's grain frame: u along the long axis."""
    gv, _ = g.attr("grain")
    gx, gy, gz = g.sep(gv)
    u = g.math("DIVIDE", along if along is not None else gx, size)
    v = g.math("DIVIDE", across if across is not None else g.math("ADD", gy, gz), size)
    return g.vec(v, u, 0.0) if swap else g.vec(u, v, 0.0)


def _grain_across_y(g, sharp=4.0):
    """0..1 weight for mapping across the grain by gy (1) rather than gz (0): faces
    whose normal lies along the grain frame's Z run across gy, and the other way
    round; chamfers blend. Faces without the attribute get 1."""
    gn, _ = g.attr("grain_normal")
    _, ny, nz = g.sep(gn)
    py, pz = g.math("POWER", ny, sharp), g.math("POWER", nz, sharp)
    total = g.math("ADD", py, pz)
    w = g.math("DIVIDE", pz, g.math("MAXIMUM", total, 1e-6))
    return g.mixf(g.math("LESS_THAN", total, 1e-6), w, 1.0)


def _grime(g, vec):
    """(dust, smudge) masks, 0..1, from scanned imperfection maps."""
    dust = g.tex(_image(DUST, "mask"), vec, 0.3)
    smudge = g.tex(_image(SMUDGE, "mask"), g.vmath("ADD", g.scale(vec, (0.7, 0.7, 0.7)), (0.37, 0.61, 0.13)), 0.3)
    return g.map(dust, 0.2, 0.55), g.map(smudge, 0.08, 0.35)


def _edge_wear(g, radius=0.003, amount=1.0, vec=None):
    """0..1 mask of worn paint on convex edges: where a Bevel-node normal (rounded over
    `radius`) leans away from the true normal, broken up by noise so only some
    stretches of each edge are rubbed through. Bevel costs a few rays per shading
    point, so keep it to small dark metal parts."""
    bev = g.node("ShaderNodeBevel", samples=4)
    g.set(bev.inputs["Radius"], radius)
    edge = g.math("SUBTRACT", 1.0, g.vmath("DOT_PRODUCT", bev.outputs["Normal"], g.normal()))
    edge = g.map(edge, 0.01, 0.12)
    p = vec if vec is not None else g.position()
    breakup = g.map(g.noise(p, 40.0, 4.0, 0.7, 0.3), 0.45, 0.7)
    return g.math("MULTIPLY", g.math("MULTIPLY", edge, breakup), amount, clamp=True)


def _tone(g, color, tex, median, spread, lo=0.6, hi=1.4):
    """color modulated by a texture's luminance around its median (keeps the scan's
    detail, sets our own colour and value)."""
    k = g.map(g.bw(tex), median - spread, median + spread, lo, hi)
    return g.mix(1.0, color, g.gray(k), "MULTIPLY")


# ----------------------------------------------------------------------------
# Simple materials
# ----------------------------------------------------------------------------


def solid(name, color, roughness=0.5, metallic=0.0, emission=0.0):
    """Flat colour with a whisper of surface noise (kept for ad-hoc materials)."""
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat, g, bsdf = _new(name, color)
    n = g.noise(g.obj_coords(), 60.0, 3.0, 0.6)
    _principled(g, bsdf, color=color, metal=metallic,
                rough=g.map(n, 0.3, 0.7, roughness * 0.9, min(1.0, roughness * 1.1)))
    if emission:
        _principled(g, bsdf, emit_color=color, emit=emission)
    return mat


def _plastic(name, color, rough, bump=0.03):
    mat, g, bsdf = _new(name, color)
    p = g.obj_coords()
    peel = g.noise(p, 400.0, 2.0, 0.5)
    _principled(g, bsdf, color=color, rough=g.map(g.noise(p, 25.0, 2.0), 0.3, 0.7, rough * 0.85, rough * 1.15),
                normal=g.bump(peel, bump, 0.001))
    return mat


def plaster(name="plaster"):
    c = (0.80, 0.785, 0.75)
    mat, g, bsdf = _new(name, c)
    p = g.position()
    blotch = g.noise(p, 1.6, 4.0, 0.6)
    fine = g.noise(p, 90.0, 3.0, 0.6)
    trowel = g.noise(g.scale(p, (1.0, 1.0, 0.5)), 6.0, 3.0, 0.55, 0.4)
    col = g.mix(g.map(blotch, 0.35, 0.65, 0.0, 1.0), (0.75, 0.735, 0.70), c)
    col = g.mix(g.map(fine, 0.4, 0.6, 0.0, 0.25), col, (0.84, 0.83, 0.80))
    h = g.math("ADD", g.math("MULTIPLY", trowel, 0.6), g.math("MULTIPLY", fine, 0.4))
    _principled(g, bsdf, color=col, rough=g.map(trowel, 0.3, 0.7, 0.82, 0.95), normal=g.bump(h, 0.06, 0.004))
    return mat


def painted_brick(axis):
    """Whitewashed brick, projected in world space so courses line up across wall pieces.

    Triplanar: each face takes the projection its normal faces (X faces y-z, Y faces
    x-z, sills and soffits x-y), blended only across the rounded arrises, so reveals,
    sills and wall returns get properly scaled bricks too. The axis argument only
    keeps the historical material names (brick_x / brick_y)."""
    name = f"painted_brick_{axis.lower()}"
    return _pick(name, brick_scan, _brick_procedural, BRICK)


def _brick_pattern(g, uv, pos):
    """(per-brick random 0..1, mortar 0..1) for one projection plane (uv in metres)."""
    u, v, _ = g.sep(uv)
    # mortar lines wobble a few mm, like hand-laid courses under thick paint
    wob = g.noise(pos, 4.0, 2.0, 0.5)
    wob2 = g.noise(g.vmath("ADD", pos, (5.3, 1.1, 7.7)), 4.0, 2.0, 0.5)
    u = g.math("ADD", u, g.math("MULTIPLY", g.math("SUBTRACT", wob, 0.5), 0.02))
    v = g.math("ADD", v, g.math("MULTIPLY", g.math("SUBTRACT", wob2, 0.5), 0.012))
    brick = g.node("ShaderNodeTexBrick", offset=0.5, offset_frequency=2, squash=1.0, squash_frequency=2)
    g.set(brick.inputs["Vector"], g.vec(u, v, 0.0))
    g.set(brick.inputs["Scale"], 1.0)
    g.set(brick.inputs["Brick Width"], 0.23)
    g.set(brick.inputs["Row Height"], 0.077)
    g.set(brick.inputs["Mortar Size"], 0.013)
    g.set(brick.inputs["Mortar Smooth"], 0.6)
    g.set(brick.inputs["Bias"], 0.0)
    g.set(brick.inputs["Color1"], (1.0, 1.0, 1.0))
    g.set(brick.inputs["Color2"], (0.0, 0.0, 0.0))
    g.set(brick.inputs["Mortar"], (0.5, 0.5, 0.5))
    per_brick, _, _ = g.sep(brick.outputs["Color"])  # random 0..1 per brick (0.5 in mortar)
    return per_brick, brick.outputs["Factor"]


def _brick_procedural(name):
    paint = (0.80, 0.79, 0.76)
    mat, g, bsdf = _new(name, paint)
    pos = g.position()
    weights = _tri_weights(g)
    pats = [_brick_pattern(g, uv, pos) for uv in _tri_planes(g, 1.0)]
    per_brick = _tri_blend(g, weights, [p[0] for p in pats], color=False)
    mortar = _tri_blend(g, weights, [p[1] for p in pats], color=False)

    # paint colour: per-brick tint, broad blotches where the wash is thinner, fine mottling
    col = g.mix(per_brick, (0.80, 0.79, 0.76), (0.86, 0.855, 0.83))
    thin = g.map(g.noise(pos, 1.2, 5.0, 0.65), 0.55, 0.75, 0.0, 0.35)
    col = g.mix(thin, col, (0.66, 0.64, 0.60))
    speck = g.noise(pos, 70.0, 3.0, 0.7)
    col = g.mix(g.map(speck, 0.45, 0.7, 0.0, 0.4), col, (0.70, 0.69, 0.66))
    col = g.mix(g.math("MULTIPLY", mortar, 0.6), col, (0.72, 0.71, 0.68))

    # relief: recessed mortar, slightly pillowy brick faces, pitted surface
    face = g.noise(pos, 9.0, 5.0, 0.65)
    pits = g.noise(pos, 140.0, 2.0, 0.6)
    h = g.math("SUBTRACT", 1.0, mortar)
    h = g.math("ADD", h, g.math("MULTIPLY", face, 0.25))
    h = g.math("ADD", h, g.math("MULTIPLY", pits, 0.12))
    h = g.math("ADD", h, g.math("MULTIPLY", per_brick, 0.15))
    _principled(g, bsdf, color=col, rough=g.map(face, 0.3, 0.7, 0.8, 0.95), spec=0.4,
                normal=g.bump(h, 0.5, 0.01))
    return mat


def floorboards(name="floorboards"):
    """Wide oak boards (procedural fallback). The boards themselves are real geometry
    (architecture.build_floor), so this only shades them: every board piece its own
    tone and figure from its board_rand / board_id attributes."""
    mat, g, bsdf = _new(name, (0.36, 0.17, 0.06))
    b = _board_attrs(g)
    x, y, r_piece = b["x"], b["y"], b["rand"]
    r1, r2, r3 = b["r"]

    # plain-sawn grain: rings around a log axis set back from the board face
    gy = g.math("ADD", x, g.math("MULTIPLY", r1, 0.5))
    gz = g.math("ADD", 0.06, g.math("MULTIPLY", r2, 0.25))
    gx = g.math("ADD", g.math("MULTIPLY", y, b["flip"]), g.math("MULTIPLY", r3, 40.0))
    band, pores = _grain(g, gx, gy, gz, rings_per_m=110.0, pore_scale=1.0)

    tone = g.mix(r_piece, (0.30, 0.135, 0.045), (0.46, 0.235, 0.09))
    tone = g.mix(g.map(r2, 0.75, 1.0, 0.0, 0.6), tone, (0.52, 0.30, 0.13))  # a few pale boards
    tone = g.mix(g.map(r1, 0.0, 0.18, 0.5, 0.0), tone, (0.20, 0.085, 0.03))  # a few dark ones
    wood = g.mix(g.math("MULTIPLY", band, 0.45), tone, g.mix(0.5, tone, (0.12, 0.05, 0.015), "MULTIPLY"))
    wood = g.mix(g.math("MULTIPLY", pores, 0.25), wood, (0.14, 0.06, 0.02))
    # wear: lighter, duller patches in traffic areas
    wear = g.map(g.noise(g.vec(x, y, 0.0), 0.7, 3.0, 0.5), 0.45, 0.7, 0.0, 1.0)
    wood = g.mix(g.math("MULTIPLY", wear, 0.25), wood, (0.55, 0.33, 0.16))
    col = g.mix(b["side"], wood, (0.05, 0.025, 0.01))
    scuff = g.noise(g.vec(g.math("MULTIPLY", x, 3.0), y, 0.0), 12.0, 4.0, 0.6)
    rough = g.math("ADD", g.map(r_piece, 0.0, 1.0, 0.24, 0.36), g.math("MULTIPLY", wear, 0.12))
    rough = g.math("ADD", rough, g.map(scuff, 0.4, 0.7, 0.0, 0.12))
    h = g.math("SUBTRACT", g.math("MULTIPLY", band, 0.08), g.math("MULTIPLY", pores, 0.12))
    _principled(g, bsdf, color=col, rough=rough, spec=0.5, normal=g.bump(h, 0.35, 0.003))
    return mat


def _board_attrs(g):
    """Per-board values from the floorboard geometry (see lib.architecture): world x/y,
    board_rand, three more randoms hashed from board_id, a +-1 flip (each board's
    figure runs one way or the other, i.e. turned 180 degrees) and 'side', 1 on the
    board sides and ends down in the real gaps (and a little on the chamfers)."""
    x, y, _ = g.sep(g.position())
    _, bid = g.attr("board_id")
    _, brand = g.attr("board_rand")
    _, rc = g.white(g.vec(bid, 7.0, 0.0))
    r1, r2, r3 = g.sep(rc)
    flip = g.math("SUBTRACT", 1.0, g.math("MULTIPLY", g.math("GREATER_THAN", r3, 0.5), 2.0))
    _, _, nz = g.sep(g.normal())
    side = g.map(nz, 0.55, 0.97, 0.85, 0.0)
    return {"x": x, "y": y, "id": bid, "rand": brand, "r": (r1, r2, r3), "flip": flip, "side": side}


def _grain(g, gx, gy, gz, rings_per_m=90.0, pore_scale=1.0):
    """Shared wood figure. gx runs along the grain (m); gy/gz across, offset from the pith.
    Returns (late-wood band 0..1, pore streaks 0..1)."""
    wobble = g.noise(g.vec(g.math("MULTIPLY", gx, 0.8), g.math("MULTIPLY", gy, 6.0), g.math("MULTIPLY", gz, 6.0)),
                     1.0, 3.0, 0.55)
    r = g.vmath("LENGTH", g.vec(gy, gz, 0.0))
    rings = g.math("ADD", g.math("MULTIPLY", r, rings_per_m), g.math("MULTIPLY", wobble, 4.0))
    band = g.math("POWER", g.math("ADD", 0.5, g.math("MULTIPLY", g.math("SINE", g.math("MULTIPLY", rings, 6.2832)), 0.5)), 3.0)
    pores = g.noise(g.vec(g.math("MULTIPLY", gx, 3.0 * pore_scale), g.math("MULTIPLY", gy, 220.0 * pore_scale),
                          g.math("MULTIPLY", gz, 220.0 * pore_scale)), 1.0, 2.0, 0.6)
    pores = g.map(pores, 0.55, 0.8, 0.0, 1.0)
    return band, pores


def wood(name, light, dark, rough=0.5, rings_per_m=80.0, planks=0.0, coat=0.0, age=0.0):
    """Solid wood following each piece's own grain axis (the 'grain' attribute)."""
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat, g, bsdf = _new(name, light)
    gv, _ = g.attr("grain")
    gx, gy, gz = g.sep(gv)
    _, rnd = g.attr("island_rand")
    joint = r_pl = None
    if planks:
        # separate boards across the second grain axis (ceiling boards): each
        # board gets its own figure, offset along the grain and from the pith
        f = g.math("DIVIDE", g.math("ADD", gy, 50.0), planks)
        frac = g.math("FRACT", f)
        e = g.math("MULTIPLY", g.math("MINIMUM", frac, g.math("SUBTRACT", 1.0, frac)), planks)
        joint = g.map(e, 0.0, 0.004, 1.0, 0.0)
        r_pl, r_plc = g.white(g.vec(g.math("FLOOR", f), 3.0, 0.0))
        p1, p2, _ = g.sep(r_plc)
        gx = g.math("ADD", gx, g.math("MULTIPLY", p1, 37.0))
        gy = g.math("ADD", g.math("MULTIPLY", frac, planks), g.math("ADD", 0.04, g.math("MULTIPLY", p2, 0.3)))
    band, pores = _grain(g, gx, gy, gz, rings_per_m)
    tint = g.map(rnd, 0.0, 1.0, 0.0, 1.0)
    base = g.mix(tint, light, g.mix(0.35, light, dark))
    col = g.mix(g.math("MULTIPLY", band, 0.55), base, dark)
    col = g.mix(g.math("MULTIPLY", pores, 0.3), col, g.mix(0.6, dark, (0.0, 0.0, 0.0)))
    h = g.math("ADD", g.math("MULTIPLY", band, 0.3), g.math("MULTIPLY", pores, -0.4))
    if planks:
        col = g.mix(g.math("MULTIPLY", r_pl, 0.5), col, g.mix(0.5, col, dark))
        col = g.mix(joint, col, (0.02, 0.01, 0.005))
        h = g.math("SUBTRACT", h, joint)
    if age:
        # old timber: darker weathered patches and checks
        p = g.position()
        patches = g.map(g.noise(p, 2.5, 4.0, 0.6), 0.4, 0.7, 0.0, age)
        col = g.mix(patches, col, g.mix(0.5, dark, (0.05, 0.03, 0.02)))
        checks = g.map(g.noise(g.vec(g.math("MULTIPLY", gx, 1.0), g.math("MULTIPLY", gy, 60.0),
                                     g.math("MULTIPLY", gz, 60.0)), 1.0, 2.0, 0.5), 0.72, 0.78, 0.0, 1.0)
        col = g.mix(g.math("MULTIPLY", checks, 0.6 * age), col, (0.03, 0.015, 0.01))
        h = g.math("SUBTRACT", h, g.math("MULTIPLY", checks, 1.5 * age))
    _principled(g, bsdf, color=col, rough=g.map(pores, 0.0, 1.0, rough, min(1.0, rough + 0.15)),
                coat=coat, coat_rough=0.25, normal=g.bump(h, 0.25, 0.002))
    return mat


def lino(name="lino_green"):
    c = (0.045, 0.085, 0.06)
    mat, g, bsdf = _new(name, c)
    p = g.position()
    m1 = g.noise(p, 9.0, 6.0, 0.7)
    m2 = g.noise(p, 2.0, 3.0, 0.5)
    col = g.mix(g.map(m1, 0.35, 0.65), (0.035, 0.07, 0.05), (0.06, 0.105, 0.075))
    col = g.mix(g.map(m2, 0.4, 0.7, 0.0, 0.3), col, (0.08, 0.10, 0.08))
    _principled(g, bsdf, color=col, rough=g.map(m2, 0.3, 0.7, 0.38, 0.55), normal=g.bump(m1, 0.05, 0.002))
    return mat


def steel_black(name="steel_black"):
    """Painted black steel (window sections): soft sheen, slight orange-peel and wear."""
    mat, g, bsdf = _new(name, (0.015, 0.015, 0.015))
    p = g.position()
    peel = g.noise(p, 300.0, 2.0, 0.5)
    var = g.noise(p, 8.0, 3.0, 0.6)
    col = g.mix(g.map(var, 0.4, 0.7, 0.0, 1.0), (0.012, 0.012, 0.013), (0.03, 0.03, 0.03))
    wear = _edge_wear(g, amount=0.8)
    col = g.mix(wear, col, (0.16, 0.155, 0.15))
    _principled(g, bsdf, color=col, metal=g.mixf(wear, 0.15, 0.8), rough=g.map(var, 0.3, 0.7, 0.28, 0.45),
                coat=g.mixf(wear, 0.2, 0.0), coat_rough=0.3, normal=g.bump(peel, 0.05, 0.001))
    return mat


def satin_paint(name, color, rough=0.32):
    mat, g, bsdf = _new(name, color)
    p = g.position()
    peel = g.noise(p, 250.0, 2.0, 0.5)
    brush = g.noise(g.scale(p, (1.0, 1.0, 12.0)), 30.0, 2.0, 0.5)
    _principled(g, bsdf, color=color, rough=g.map(brush, 0.3, 0.7, rough * 0.85, rough * 1.2),
                normal=g.bump(g.math("ADD", peel, g.math("MULTIPLY", brush, 0.5)), 0.04, 0.001))
    return mat


def glass(name="glass"):
    """Thin window glass: transparent (so the sun and portals pass straight through)
    with Fresnel reflections, slightly green at grazing angles."""
    mat, g, bsdf = _new(name, (0.7, 0.8, 0.9))
    nt = g.nt
    out = nt.nodes["Material Output"]
    nt.nodes.remove(bsdf)
    transparent = g.node("ShaderNodeBsdfTransparent")
    g.set(transparent.inputs["Color"], (0.97, 0.985, 0.98))
    glossy = g.node("ShaderNodeBsdfGlossy")
    g.set(glossy.inputs["Roughness"], 0.0)
    lw = g.node("ShaderNodeLayerWeight")
    g.set(lw.inputs["Blend"], 0.08)
    mix = g.node("ShaderNodeMixShader")
    g.set(mix.inputs["Fac"], lw.outputs["Fresnel"])
    nt.links.new(transparent.outputs[0], mix.inputs[1])
    nt.links.new(glossy.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    mat.diffuse_color = (0.7, 0.8, 0.9, 0.3)
    return mat


def aluminium(name="aluminium"):
    """Brushed/bead-blasted aluminium: streaks along each part's long axis."""
    mat, g, bsdf = _new(name, (0.8, 0.8, 0.82))
    gv, _ = g.attr("grain")
    gx, gy, gz = g.sep(gv)
    streak = g.noise(g.vec(g.math("MULTIPLY", gx, 4.0), g.math("MULTIPLY", gy, 900.0), g.math("MULTIPLY", gz, 900.0)),
                     1.0, 3.0, 0.6)
    blotch = g.noise(g.position(), 6.0, 3.0, 0.5)
    col = g.mix(g.map(streak, 0.3, 0.7), (0.80, 0.81, 0.83), (0.90, 0.905, 0.91))
    _principled(g, bsdf, color=col, metal=1.0,
                rough=g.math("ADD", g.map(streak, 0.2, 0.8, 0.3, 0.42), g.map(blotch, 0.4, 0.7, 0.0, 0.08)),
                normal=g.bump(streak, 0.04, 0.0005))
    return mat


def screen(name="screen"):
    mat, g, bsdf = _new(name, (0.01, 0.01, 0.012))
    _principled(g, bsdf, color=(0.004, 0.005, 0.007), rough=0.06, coat=0.6, coat_rough=0.03)
    return mat


def paper(name="paper"):
    mat, g, bsdf = _new(name, (0.85, 0.84, 0.80))
    _, rnd = g.attr("island_rand")
    p = g.obj_coords()
    fib = g.noise(p, 300.0, 3.0, 0.6)
    col = g.mix(g.map(rnd, 0.0, 1.0), (0.86, 0.86, 0.84), (0.82, 0.79, 0.70))
    col = g.mix(g.map(g.math("FRACT", g.math("MULTIPLY", rnd, 7.3)), 0.85, 1.0, 0.0, 0.8), col, (0.80, 0.82, 0.86))
    col = g.mix(g.map(fib, 0.4, 0.7, 0.0, 0.08), col, (0.6, 0.58, 0.55))
    _principled(g, bsdf, color=col, rough=0.72, sheen=0.25, sss=0.05, sss_radius=(0.02, 0.02, 0.02),
                normal=g.bump(fib, 0.05, 0.0005))
    return mat


def cardboard(name="cardboard"):
    mat, g, bsdf = _new(name, (0.43, 0.27, 0.13))
    _, rnd = g.attr("island_rand")
    gv, _ = g.attr("grain")
    gx, gy, gz = g.sep(gv)
    p = g.obj_coords()
    fib = g.noise(p, 120.0, 4.0, 0.65)
    blot = g.noise(p, 5.0, 3.0, 0.6)
    # corrugation ripples running across the long axis, faint through the liner
    ripple = g.math("SINE", g.math("MULTIPLY", gx, 800.0))
    col = g.mix(g.map(rnd, 0.0, 1.0), (0.42, 0.27, 0.13), (0.50, 0.34, 0.18))
    col = g.mix(g.map(blot, 0.4, 0.7, 0.0, 0.3), col, (0.34, 0.20, 0.09))
    col = g.mix(g.map(fib, 0.5, 0.7, 0.0, 0.25), col, (0.56, 0.42, 0.26))
    h = g.math("ADD", g.math("MULTIPLY", ripple, 0.05), g.math("MULTIPLY", fib, 0.3))
    _principled(g, bsdf, color=col, rough=0.85, sheen=0.2, normal=g.bump(h, 0.1, 0.001))
    return mat


def fabric(name, color, sheen_tint=(0.5, 0.5, 0.5)):
    mat, g, bsdf = _new(name, color)
    p = g.obj_coords()
    w1 = g.math("SINE", g.math("MULTIPLY", g.sep(p)[0], 1400.0))
    w2 = g.math("SINE", g.math("MULTIPLY", g.sep(p)[2], 1400.0))
    weave = g.math("MULTIPLY", w1, w2)
    blot = g.noise(p, 12.0, 3.0, 0.6)
    col = g.mix(g.map(blot, 0.35, 0.7), color, tuple(min(1.0, c * 1.6 + 0.01) for c in color))
    _principled(g, bsdf, color=col, rough=0.95, sheen=0.7, sheen_tint=sheen_tint, sheen_rough=0.4,
                normal=g.bump(weave, 0.12, 0.0005))
    return mat


def lampshade(name="lampshade"):
    """Linen shade. Lets light through (translucent), and glows warm when
    finish_scene() switches the lamp on (emission is set there)."""
    c = (0.84, 0.72, 0.52)
    mat, g, bsdf = _new(name, c)
    nt = g.nt
    out = nt.nodes["Material Output"]
    p = g.obj_coords()
    x, y, z = g.sep(p)
    weave = g.math("MULTIPLY", g.math("SINE", g.math("MULTIPLY", g.math("ADD", x, y), 900.0)),
                   g.math("SINE", g.math("MULTIPLY", z, 900.0)))
    slub = g.noise(g.vec(x, y, g.math("MULTIPLY", z, 25.0)), 30.0, 2.0, 0.5)
    col = g.mix(g.map(slub, 0.5, 0.8, 0.0, 0.5), c, (0.74, 0.62, 0.42))
    _principled(g, bsdf, color=col, rough=0.9, sheen=0.4, normal=g.bump(weave, 0.06, 0.0005),
                emit_color=(1.0, 0.62, 0.30), emit=0.0)
    trans = g.node("ShaderNodeBsdfTranslucent")
    g.set(trans.inputs["Color"], col)
    mix = g.node("ShaderNodeMixShader")
    g.set(mix.inputs["Fac"], 0.3)
    nt.links.new(bsdf.outputs[0], mix.inputs[1])
    nt.links.new(trans.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return mat


def wicker(name="wicker"):
    c = (0.48, 0.34, 0.18)
    mat, g, bsdf = _new(name, c)
    gv, _ = g.attr("grain")
    gx, gy, gz = g.sep(gv)
    pitch = 120.0  # strands per metre (ish)
    a = g.math("SINE", g.math("MULTIPLY", g.math("ADD", gx, g.math("ADD", gy, gz)), pitch * 3.1416))
    b = g.math("SINE", g.math("MULTIPLY", g.math("SUBTRACT", gx, g.math("ADD", gy, gz)), pitch * 3.1416))
    weave = g.math("MAXIMUM", g.math("ABSOLUTE", a), g.math("ABSOLUTE", b))
    gaps = g.map(weave, 0.0, 0.35, 1.0, 0.0)
    tone = g.noise(g.vec(gx, gy, gz), 20.0, 3.0, 0.6)
    col = g.mix(g.map(tone, 0.35, 0.65), (0.40, 0.27, 0.13), (0.58, 0.43, 0.24))
    col = g.mix(gaps, col, (0.08, 0.05, 0.02))
    _principled(g, bsdf, color=col, rough=0.75, normal=g.bump(weave, 0.6, 0.004))
    return mat


def art_print(name="art_dark"):
    """Black-and-white landscape print: rows of dark trees under a pale sky."""
    mat, g, bsdf = _new(name, (0.06, 0.07, 0.06))
    p = g.obj_coords()
    x, y, z = g.sep(p)  # print faces -Y: x across, z up
    land = g.noise(g.vec(g.math("MULTIPLY", x, 1.0), 0.0, g.math("MULTIPLY", z, 0.3)), 6.0, 6.0, 0.6)
    trees = g.noise(g.vec(g.math("MULTIPLY", x, 3.0), 0.0, g.math("MULTIPLY", z, 1.2)), 18.0, 8.0, 0.65)
    horizon = g.map(z, 0.04, 0.12, 0.0, 1.0, "SMOOTHSTEP")
    v = g.map(g.math("ADD", trees, g.math("MULTIPLY", land, 0.4)), 0.4, 0.9, 0.012, 0.22)
    v = g.mixf(horizon, v, g.map(z, 0.1, 0.25, 0.25, 0.45))
    col = g.mix(1.0, (0.0, 0.0, 0.0), g.vec(v, v, v), "ADD")
    _principled(g, bsdf, color=col, rough=0.6)
    return mat


def book(name, color):
    """Cloth/paper book covers: each book a slightly different shade, gloss and wear."""
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat, g, bsdf = _new(name, color)
    _, rnd = g.attr("island_rand")
    r2 = g.math("FRACT", g.math("MULTIPLY", rnd, 7.31))
    r3 = g.math("FRACT", g.math("MULTIPLY", rnd, 13.7))
    col = g.hsv(color, g.map(rnd, 0.0, 1.0, 0.47, 0.53), g.map(r2, 0.0, 1.0, 0.75, 1.15), g.map(r3, 0.0, 1.0, 0.7, 1.2))
    p = g.obj_coords()
    cloth = g.noise(p, 500.0, 2.0, 0.5)
    edge = g.noise(p, 30.0, 3.0, 0.6)
    col = g.mix(g.map(edge, 0.6, 0.8, 0.0, 0.25), col, (0.5, 0.48, 0.45))
    _principled(g, bsdf, color=col, rough=g.map(r2, 0.0, 1.0, 0.3, 0.85), sheen=0.15,
                normal=g.bump(cloth, 0.05, 0.0005))
    return mat


# --- outdoors -------------------------------------------------------------------


def grass(name="garden"):
    mat, g, bsdf = _new(name, (0.10, 0.20, 0.05))
    p = g.position()
    big = g.noise(p, 0.12, 3.0, 0.5)
    mid = g.noise(p, 0.8, 4.0, 0.6)
    fine = g.noise(p, 40.0, 3.0, 0.7)
    col = g.mix(g.map(big, 0.35, 0.65), (0.05, 0.11, 0.02), (0.11, 0.19, 0.035))
    col = g.mix(g.map(mid, 0.55, 0.75, 0.0, 0.5), col, (0.17, 0.20, 0.06))
    col = g.mix(g.map(fine, 0.3, 0.7), g.mix(0.5, col, (0.0, 0.0, 0.0)), col)
    _principled(g, bsdf, color=col, rough=0.95, spec=0.2, normal=g.bump(fine, 0.5, 0.02))
    return mat


def foliage(name="foliage", light=(0.10, 0.20, 0.035), dark=(0.025, 0.06, 0.012)):
    """Leaf clumps: Voronoi cells for clusters of leaves, each a slightly different green."""
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat, g, bsdf = _new(name, light)
    p = g.position()
    vor = g.node("ShaderNodeTexVoronoi", feature="F1")
    g.set(vor.inputs["Vector"], p)
    g.set(vor.inputs["Scale"], 14.0)
    g.set(vor.inputs["Randomness"], 1.0)
    cell_r, cell_g, _ = g.sep(vor.outputs["Color"])
    dist = vor.outputs["Distance"]
    leaf = g.noise(p, 35.0, 3.0, 0.6)
    _, rnd = g.attr("island_rand")
    col = g.mix(cell_r, dark, light)
    col = g.mix(g.math("MULTIPLY", cell_g, 0.25), col, (0.13, 0.17, 0.04))  # yellow-green flecks
    col = g.mix(g.math("MULTIPLY", rnd, 0.6), col, g.hsv(col, 0.53, 1.0, 1.0))  # per-tree hue
    col = g.mix(g.map(dist, 0.2, 0.6, 0.0, 0.5), col, (0.01, 0.02, 0.005))  # depth between clumps
    h = g.math("SUBTRACT", g.math("MULTIPLY", leaf, 0.5), dist)
    nt = g.nt
    out = nt.nodes["Material Output"]
    _principled(g, bsdf, color=col, rough=0.8, spec=0.25, normal=g.bump(h, 0.45, 0.04))
    trans = g.node("ShaderNodeBsdfTranslucent")
    g.set(trans.inputs["Color"], g.mix(0.5, col, (0.35, 0.5, 0.05), "SCREEN"))
    mix = g.node("ShaderNodeMixShader")
    g.set(mix.inputs["Fac"], 0.2)
    nt.links.new(bsdf.outputs[0], mix.inputs[1])
    nt.links.new(trans.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return mat


def bark(name="bark"):
    mat, g, bsdf = _new(name, (0.12, 0.10, 0.08))
    p = g.position()
    x, y, z = g.sep(p)
    ridges = g.noise(g.vec(g.math("MULTIPLY", x, 8.0), g.math("MULTIPLY", y, 8.0), g.math("MULTIPLY", z, 1.0)),
                     3.0, 4.0, 0.6)
    col = g.mix(g.map(ridges, 0.3, 0.7), (0.05, 0.045, 0.04), (0.20, 0.18, 0.15))
    _principled(g, bsdf, color=col, rough=0.9, normal=g.bump(ridges, 0.8, 0.02))
    return mat


def render_wall(name, color):
    """Distant house walls: painted render or brick, weathered."""
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat, g, bsdf = _new(name, color)
    p = g.position()
    n = g.noise(p, 1.5, 4.0, 0.6)
    col = g.mix(g.map(n, 0.3, 0.7, 0.0, 0.4), color, g.mix(0.5, color, (0.3, 0.3, 0.3), "MULTIPLY"))
    _principled(g, bsdf, color=col, rough=0.9)
    return mat


def roof(name="roof_slate"):
    mat, g, bsdf = _new(name, (0.05, 0.05, 0.06))
    p = g.position()
    x, y, z = g.sep(p)
    courses = g.math("FRACT", g.math("MULTIPLY", z, 9.0))
    col = g.mix(g.map(g.noise(p, 3.0, 3.0, 0.5), 0.3, 0.7), (0.035, 0.035, 0.045), (0.09, 0.085, 0.09))
    _principled(g, bsdf, color=col, rough=0.6, normal=g.bump(courses, 0.3, 0.01))
    return mat


# ----------------------------------------------------------------------------
# Scanned (PBR) materials
# ----------------------------------------------------------------------------


def brick_scan(name):
    """Thick white paint over hand-laid brick (scan: 22 courses per 1.69 m tile,
    so ~7.7 cm courses and ~21 cm bricks). World-space triplanar (_tri_scan), so
    courses run on across wall pieces and reveals, sills and returns get true-scale
    bricks."""
    paint = (0.77, 0.79, 0.81)  # a touch cool: the room's bounce light is warm timber
    mat, g, bsdf = _new(name, paint)
    pos = g.position()
    col_t, r_t, h_t = _tri_scan(g, BRICK, 1.69)
    lum = g.bw(col_t)
    # the scan's paint is blue: keep its light and shade, repaint it white
    shade = g.map(lum, 0.03, 0.36, 0.5, 1.04)
    wash = g.noise(pos, 0.8, 4.0, 0.6)  # paint thickness varies across the wall
    shade = g.math("MULTIPLY", shade, g.map(wash, 0.3, 0.7, 0.92, 1.03))
    col = g.mix(1.0, paint, g.gray(shade), "MULTIPLY")
    chip = g.map(lum, 0.04, 0.12, 1.0, 0.0)  # bare brick where paint has flaked
    col = g.mix(g.math("MULTIPLY", chip, 0.6), col, (0.30, 0.19, 0.13))
    dust, smudge = _grime(g, _world_vec(g, 1.3))
    col = g.mix(g.math("MULTIPLY", smudge, 0.12), col, (0.50, 0.48, 0.45))
    rough = g.math("ADD", g.map(r_t, 0.88, 1.0, 0.8, 0.94), g.math("MULTIPLY", dust, 0.04))
    _principled(g, bsdf, color=col, rough=rough, spec=0.4, normal=g.bump(h_t, 0.8, 0.012))
    return mat


def plaster_scan(name="plaster"):
    c = (0.80, 0.785, 0.75)
    mat, g, bsdf = _new(name, c)
    col_t, r_t, h_t = _scan(g, PLASTER, _world_vec(g, 1.2, (0.3, 0.7, 0.1)), 0.2)
    col = _tone(g, c, col_t, 0.245, 0.06, 0.94, 1.04)
    dust, smudge = _grime(g, _world_vec(g, 1.6))
    col = g.mix(g.math("MULTIPLY", smudge, 0.1), col, (0.55, 0.53, 0.50))
    rough = g.map(r_t, 0.85, 0.95, 0.82, 0.95)
    _principled(g, bsdf, color=col, rough=rough, normal=g.bump(h_t, 0.15, 0.003))
    return mat


# Warm-wood grade: the room's camera white balance (scene["white_balance"], cool to
# neutralise the bounce off all this timber) greys wood down, so wood scans are
# pushed back towards the photo's rich orange-brown here (linear RGB gains).
WOOD_WARMTH = (1.06, 1.0, 0.9)


def floor_scan(name="floorboards"):
    """Oiled oak boards cut from a scanned wood. The boards are real geometry
    (architecture.build_floor: real gaps, ends and chamfers), so the shading takes
    each piece's board_rand / board_id: its own strip of the scan, turned either way,
    its own tone, plus world-space wear and dust that run on across boards."""
    mat, g, bsdf = _new(name, (0.36, 0.17, 0.06))
    b = _board_attrs(g)
    r1, r2, r3 = b["r"]
    # u along the board (world y), v across (world x); random strip, either way round
    u = g.math("DIVIDE", g.math("ADD", g.math("MULTIPLY", b["y"], b["flip"]), g.math("MULTIPLY", r3, 40.0)), 2.0)
    v = g.math("DIVIDE", g.math("ADD", g.math("MULTIPLY", b["x"], b["flip"]), g.math("MULTIPLY", r1, 7.3)), 2.0)
    col_t, r_t, h_t = _scan(g, FLOOR_WOOD, g.vec(u, v, 0.0))
    tone = g.map(b["rand"], 0.0, 1.0, 0.78, 1.22)
    tone = g.math("MULTIPLY", tone, g.map(r2, 0.85, 1.0, 1.0, 1.2))  # a few pale boards
    tone = g.math("MULTIPLY", tone, 1.35)
    col = g.hsv(col_t, g.map(r2, 0.0, 1.0, 0.49, 0.51), g.map(r1, 0.0, 1.0, 0.85, 1.0), tone)
    col = g.mix(1.0, col, WOOD_WARMTH, "MULTIPLY")
    xy = g.vec(b["x"], b["y"], 0.0)
    wear = g.map(g.noise(xy, 0.7, 3.0, 0.5), 0.45, 0.7, 0.0, 1.0)  # traffic: lighter, duller
    col = g.mix(g.math("MULTIPLY", wear, 0.18), col, (0.58, 0.32, 0.13))
    dust, smudge = _grime(g, g.scale(xy, (0.6, 0.6, 0.6)))
    col = g.mix(g.math("MULTIPLY", dust, 0.1), col, (0.42, 0.32, 0.22))
    col = g.mix(b["side"], col, (0.04, 0.02, 0.008))  # board sides and ends, down in the gaps
    rough = g.math("ADD", g.map(r_t, 0.42, 0.58, 0.22, 0.34), g.math("MULTIPLY", wear, 0.14))
    rough = g.math("ADD", rough, g.math("MULTIPLY", dust, 0.2))
    coat_rough = g.math("ADD", 0.1, g.math("ADD", g.math("MULTIPLY", smudge, 0.25), g.math("MULTIPLY", wear, 0.2)))
    _principled(g, bsdf, color=col, rough=rough, spec=0.5, coat=g.map(wear, 0.0, 1.0, 0.35, 0.1),
                coat_rough=coat_rough, normal=g.bump(h_t, 0.14, 0.003))
    return mat


def wood_scan(name, asset, size, swap=False, hsv=(0.5, 1.0, 1.0), rough=(0.4, 0.6), planks=0.0, coat=0.0,
              age=0.0, rough_map=(0.0, 1.0), warm=False):
    """Solid wood from a scan, mapped along each part's grain frame ('grain' attribute,
    which already offsets every part to a different patch). swap: the scan's grain runs
    along the image's V axis. planks: board width (m) across the second grain axis.
    warm: apply WOOD_WARMTH (architectural timber under the room's cool white balance)."""
    mat, g, bsdf = _new(name, (0.3, 0.17, 0.07))
    gv, _ = g.attr("grain")
    gx, gy, gz = g.sep(gv)
    _, rnd = g.attr("island_rand")
    along, off = gx, 0.0
    joint = r_pl = None
    if planks:
        f = g.math("DIVIDE", g.math("ADD", gy, 50.0), planks)
        frac = g.math("FRACT", f)
        e = g.math("MULTIPLY", g.math("MINIMUM", frac, g.math("SUBTRACT", 1.0, frac)), planks)
        joint = g.map(e, 0.0, 0.004, 1.0, 0.0)
        r_pl, r_plc = g.white(g.vec(g.math("FLOOR", f), 3.0, 0.0))
        p1, p2, _ = g.sep(r_plc)
        along = g.math("ADD", along, g.math("MULTIPLY", p1, 37.0))
        off = g.math("MULTIPLY", p2, 5.0)
    # Across the grain, a face may run along either of the part's other two axes. Map
    # each face by the one that actually runs across it (a single gy + gz mix goes
    # flat on 45-degree chamfers and smears the scan into stripes there): two
    # samples, blended by the face normal in the grain frame ('grain_normal').
    wy = _grain_across_y(g)
    samples = [_scan(g, asset, _grain_vec(g, size, swap, along, g.math("ADD", a, off))) for a in (gy, gz)]
    col_t = g.mix(wy, samples[1][0], samples[0][0])
    r_t = g.mixf(wy, g.bw(samples[1][1]), g.bw(samples[0][1]))
    h_t = g.mixf(wy, g.bw(samples[1][2]), g.bw(samples[0][2]))
    hue, sat, val = hsv
    col = g.hsv(col_t, g.map(rnd, 0.0, 1.0, hue - 0.01, hue + 0.01), sat, g.map(rnd, 0.0, 1.0, val * 0.85, val * 1.12))
    if warm:
        col = g.mix(1.0, col, WOOD_WARMTH, "MULTIPLY")
    h = h_t
    if planks:
        col = g.mix(g.math("MULTIPLY", r_pl, 0.35), col, g.mix(0.5, col, (0.0, 0.0, 0.0)))
        col = g.mix(joint, col, (0.02, 0.01, 0.005))
        h = g.math("SUBTRACT", h, joint)
    dust, smudge = _grime(g, _world_vec(g, 1.0))
    if age:
        # old timber: darker weathered patches
        patches = g.map(g.noise(g.position(), 2.5, 4.0, 0.6), 0.4, 0.7, 0.0, 0.5 * age)
        col = g.mix(patches, col, g.mix(0.6, col, (0.0, 0.0, 0.0)))
    r = g.map(r_t, rough_map[0], rough_map[1], rough[0], rough[1])
    r = g.math("ADD", r, g.math("MULTIPLY", dust, 0.1))
    _principled(g, bsdf, color=col, rough=r, coat=coat,
                coat_rough=g.math("ADD", 0.18, g.math("MULTIPLY", smudge, 0.3)),
                normal=g.bump(h, 0.3, 0.002))
    return mat


def plastic_scan(name, color, rough, bump=0.03):
    """Matte/satin plastic (and black storage boxes): scan detail, our colour, dust and smudges."""
    mat, g, bsdf = _new(name, color)
    col_t, r_t, h_t = _scan(g, PLASTIC, _obj_vec(g, 0.6), 0.25)
    col = _tone(g, color, col_t, 0.024, 0.02, 0.75, 1.25)
    dust, smudge = _grime(g, _obj_vec(g, 0.9))
    col = g.mix(g.math("MULTIPLY", dust, 0.12 if max(color) < 0.2 else 0.05), col, (0.30, 0.29, 0.27))
    r = g.math("MULTIPLY", rough, g.map(r_t, 0.37, 0.42, 0.85, 1.15))
    r = g.math("ADD", r, g.math("ADD", g.math("MULTIPLY", smudge, 0.15), g.math("MULTIPLY", dust, 0.2)))
    _principled(g, bsdf, color=col, rough=r, normal=g.bump(h_t, bump * 3, 0.001))
    return mat


def fabric_scan(name, color, sheen_tint=(0.5, 0.5, 0.5)):
    mat, g, bsdf = _new(name, color)
    col_t, r_t, h_t = _scan(g, KNIT, _obj_vec(g, 0.25), 0.3)
    col = _tone(g, color, col_t, 0.104, 0.03, 0.6, 1.5)
    _principled(g, bsdf, color=col, rough=g.map(r_t, 0.65, 0.85, 0.85, 1.0), sheen=0.7, sheen_tint=sheen_tint,
                sheen_rough=0.4, normal=g.bump(h_t, 0.4, 0.001))
    return mat


def leatherette_scan(name, color=(0.02, 0.02, 0.021)):
    mat, g, bsdf = _new(name, color)
    col_t, r_t, h_t = _scan(g, LEATHER, _obj_vec(g, 0.4), 0.3)
    col = _tone(g, color, col_t, 0.005, 0.003, 0.7, 1.3)
    _, smudge = _grime(g, _obj_vec(g, 0.7))
    r = g.math("ADD", g.map(r_t, 0.4, 0.5, 0.38, 0.52), g.math("MULTIPLY", smudge, 0.12))
    _principled(g, bsdf, color=col, rough=r, coat=0.15, coat_rough=0.35, normal=g.bump(h_t, 0.3, 0.001))
    return mat


def paper_scan(name="paper"):
    mat, g, bsdf = _new(name, (0.85, 0.84, 0.80))
    _, rnd = g.attr("island_rand")
    col_t, r_t, h_t = _scan(g, PAPER, _obj_vec(g, 0.35), 0.3)
    col = g.mix(g.map(rnd, 0.0, 1.0), (0.86, 0.86, 0.84), (0.82, 0.79, 0.70))
    col = g.mix(g.map(g.math("FRACT", g.math("MULTIPLY", rnd, 7.3)), 0.85, 1.0, 0.0, 0.8), col, (0.80, 0.82, 0.86))
    col = _tone(g, col, col_t, 0.9, 0.04, 0.95, 1.03)
    _, smudge = _grime(g, _obj_vec(g, 0.5))
    col = g.mix(g.math("MULTIPLY", smudge, 0.15), col, (0.55, 0.53, 0.50))
    _principled(g, bsdf, color=col, rough=g.map(r_t, 0.55, 0.7, 0.62, 0.8), sheen=0.25, sss=0.05,
                sss_radius=(0.02, 0.02, 0.02), normal=g.bump(h_t, 0.08, 0.0005))
    return mat


def cardboard_scan(name="cardboard"):
    mat, g, bsdf = _new(name, (0.43, 0.27, 0.13))
    _, rnd = g.attr("island_rand")
    col_t, r_t, h_t = _scan(g, CARDBOARD, _obj_vec(g, 0.7), 0.25)
    col = g.hsv(col_t, g.map(rnd, 0.0, 1.0, 0.49, 0.505), 0.8, g.map(rnd, 0.0, 1.0, 0.85, 1.05))
    dust, smudge = _grime(g, _obj_vec(g, 0.9))
    col = g.mix(g.math("MULTIPLY", smudge, 0.2), col, (0.22, 0.14, 0.07))
    _principled(g, bsdf, color=col, rough=g.map(r_t, 0.6, 0.66, 0.78, 0.9), sheen=0.2,
                normal=g.bump(h_t, 0.15, 0.001))
    return mat


def aluminium_scan(name="aluminium"):
    """Brushed/bead-blasted aluminium: brushing along each part's long axis."""
    mat, g, bsdf = _new(name, (0.8, 0.8, 0.82))
    col_t, r_t, h_t = _scan(g, BRUSHED, _grain_vec(g, 0.45))
    col = _tone(g, (0.86, 0.865, 0.88), col_t, 0.299, 0.03, 0.93, 1.05)
    _, smudge = _grime(g, _obj_vec(g, 0.6))
    r = g.math("ADD", g.map(r_t, 0.42, 0.53, 0.24, 0.36), g.math("MULTIPLY", smudge, 0.12))
    _principled(g, bsdf, color=col, metal=1.0, rough=r, normal=g.bump(h_t, 0.03, 0.0005))
    return mat


def steel_black_scan(name="steel_black"):
    """Painted black steel (window sections): soft sheen, orange-peel, grime in the roughness."""
    mat, g, bsdf = _new(name, (0.015, 0.015, 0.015))
    p = g.position()
    peel = g.noise(p, 300.0, 2.0, 0.5)
    var = g.noise(p, 8.0, 3.0, 0.6)
    col = g.mix(g.map(var, 0.4, 0.7, 0.0, 1.0), (0.014, 0.014, 0.015), (0.03, 0.03, 0.03))
    dust, smudge = _grime(g, _world_vec(g, 0.8))
    col = g.mix(g.math("MULTIPLY", dust, 0.15), col, (0.25, 0.24, 0.22))
    r = g.math("ADD", g.map(var, 0.3, 0.7, 0.3, 0.42), g.math("ADD", g.math("MULTIPLY", smudge, 0.2),
                                                              g.math("MULTIPLY", dust, 0.25)))
    # edge wear: paint rubbed thin on arrises (dark grey steel showing through, a
    # little more metallic and polished by hands), never bright
    wear = _edge_wear(g, amount=0.8)
    col = g.mix(wear, col, (0.16, 0.155, 0.15))
    r = g.mixf(wear, r, 0.3)
    _principled(g, bsdf, color=col, metal=g.mixf(wear, 0.15, 0.8), rough=r, coat=g.mixf(wear, 0.2, 0.0),
                coat_rough=0.3, normal=g.bump(peel, 0.05, 0.001))
    return mat


# ----------------------------------------------------------------------------
# Library
# ----------------------------------------------------------------------------


def _pick(name, scanned, procedural, *ids):
    """Scanned material when its textures are cached, else the procedural one."""
    if name not in bpy.data.materials:
        (scanned if _have(*ids, DUST, SMUDGE) else procedural)(name)
    return bpy.data.materials[name]


def floor_material():
    return _pick("floorboards", floor_scan, floorboards, FLOOR_WOOD)


# Old ceiling timber (boards, joists, beams): one scan, one grade, so boards and
# beams read as the same warm wood, beams a touch darker with age.
TIMBER_HSV = (0.51, 0.75, 2.9)
BEAM_HSV = (0.51, 0.75, 4.2)  # beams: same wood, lifted (they sit in the ceiling's shade)


def ceiling_boards(name="arch_ceiling_boards"):
    """Ceiling boards (real pieces from architecture.build_ceiling, so no painted
    joints): the scanned ceiling timber, each board its own patch of the scan."""
    return _pick(name,
                 lambda n: wood_scan(n, TIMBER, 1.0, hsv=TIMBER_HSV, rough=(0.6, 0.8), age=0.5,
                                     rough_map=(0.6, 0.72), warm=True),
                 lambda n: wood(n, (0.34, 0.20, 0.10), (0.16, 0.08, 0.035), 0.7, 60.0, age=0.5),
                 TIMBER)


def library():
    """Named materials every room can draw from. Names are stable; add, don't rename."""
    return {
        "plaster": _pick("plaster", plaster_scan, plaster, PLASTER),
        "brick_x": painted_brick("X"),
        "brick_y": painted_brick("Y"),
        "floor": floor_material(),
        "ceiling_wood": _pick("ceiling_wood",
                              lambda n: wood_scan(n, TIMBER, 1.0, hsv=TIMBER_HSV, rough=(0.6, 0.8), planks=0.14,
                                                  age=0.5, rough_map=(0.6, 0.72), warm=True),
                              lambda n: wood(n, (0.34, 0.20, 0.10), (0.16, 0.08, 0.035), 0.7, 60.0, planks=0.14, age=0.5),
                              TIMBER),
        "beam_wood": _pick("beam_wood",
                           lambda n: wood_scan(n, TIMBER, 1.3, hsv=BEAM_HSV, rough=(0.58, 0.8), age=1.0,
                                               rough_map=(0.6, 0.72), warm=True),
                           lambda n: wood(n, (0.40, 0.25, 0.12), (0.17, 0.09, 0.04), 0.65, 45.0, age=1.0),
                           TIMBER),
        "oak": _pick("oak",
                     lambda n: wood_scan(n, OAK, 1.83, swap=True, hsv=(0.485, 1.35, 0.75), rough=(0.3, 0.5),
                                         coat=0.3, rough_map=(0.35, 0.7)),
                     lambda n: wood(n, (0.30, 0.15, 0.055), (0.13, 0.055, 0.018), 0.38, 110.0, coat=0.3),
                     OAK),
        "pine": _pick("pine",
                      lambda n: wood_scan(n, PINE, 1.0, swap=True, hsv=(0.5, 0.8, 1.0), rough=(0.35, 0.55), coat=0.15,
                                          rough_map=(0.45, 0.52)),
                      lambda n: wood(n, (0.58, 0.36, 0.15), (0.36, 0.17, 0.05), 0.5, 55.0, coat=0.15),
                      PINE),
        "lino_green": _cached("lino_green", lino),
        "steel_black": _pick("steel_black", steel_black_scan, steel_black),
        "sash_white": _cached("sash_white", lambda n: satin_paint(n, (0.82, 0.82, 0.80))),
        "glass": _cached("glass", glass),
        "aluminium": _pick("aluminium", aluminium_scan, aluminium, BRUSHED),
        "plastic_black": _plastic_lib("plastic_black", (0.022, 0.022, 0.024), 0.5),
        "plastic_black_satin": _plastic_lib("plastic_black_satin", (0.018, 0.018, 0.02), 0.22),
        "plastic_white": _plastic_lib("plastic_white", (0.82, 0.82, 0.80), 0.28),
        "screen": _cached("screen", screen),
        "paper": _pick("paper", paper_scan, paper, PAPER),
        "cardboard": _pick("cardboard", cardboard_scan, cardboard, CARDBOARD),
        "fabric_black": _pick("fabric_black", lambda n: fabric_scan(n, (0.025, 0.025, 0.028)),
                              lambda n: fabric(n, (0.025, 0.025, 0.028)), KNIT),
        "leatherette_black": _pick("leatherette_black", leatherette_scan,
                                   lambda n: _plastic(n, (0.02, 0.02, 0.021), 0.45, 0.08), LEATHER),
        "wicker": _cached("wicker", wicker),
        "lampshade": _cached("lampshade", lampshade),
        "art_dark": _cached("art_dark", art_print),
        "garden": _cached("garden", grass),
        "foliage": foliage("foliage"),
        "foliage_dark": foliage("foliage_dark", (0.06, 0.14, 0.03), (0.015, 0.04, 0.01)),
        "foliage_light": foliage("foliage_light", (0.16, 0.26, 0.05), (0.04, 0.09, 0.015)),
        "bark": _cached("bark", bark),
        "house_render": render_wall("house_render", (0.62, 0.58, 0.50)),
        "house_brick": render_wall("house_brick", (0.30, 0.12, 0.07)),
        "roof_slate": _cached("roof_slate", roof),
    }


def _plastic_lib(name, color, rough):
    return _pick(name, lambda n: plastic_scan(n, color, rough), lambda n: _plastic(n, color, rough), PLASTIC)


BOOK_COLOURS = [
    (0.80, 0.78, 0.72), (0.05, 0.05, 0.05), (0.08, 0.15, 0.35), (0.55, 0.10, 0.08),
    (0.85, 0.65, 0.10), (0.15, 0.30, 0.25), (0.92, 0.92, 0.90), (0.30, 0.45, 0.60),
    (0.65, 0.55, 0.40), (0.40, 0.05, 0.20), (0.20, 0.20, 0.22), (0.75, 0.35, 0.20),
]


def book_materials():
    """Cover, page and shelf-prop materials for lib.books (defined there)."""
    from .books import materials as book_set
    return book_set()


# ----------------------------------------------------------------------------
# Scene finishing pass (runs once, after the room is built)
# ----------------------------------------------------------------------------

BEVEL_COLLECTIONS = ("Furniture", "Props", "Ceiling", "Architecture")
BEVEL_SKIP_PREFIXES = ("wall_", "floor", "ceiling", "ground")


def _islands(mesh):
    """Vertex island index per vertex (union-find over edges)."""
    n = len(mesh.vertices)
    parent = np.arange(n)
    edges = np.empty(len(mesh.edges) * 2, dtype=np.int64)
    mesh.edges.foreach_get("vertices", edges)
    edges = edges.reshape(-1, 2)

    def find(a):
        root = a
        while parent[root] != root:
            root = parent[root]
        while parent[a] != root:
            parent[a], a = root, parent[a]
        return root

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    return np.array([find(i) for i in range(n)])


def _write_grain(obj, rng):
    """'grain' (vector, local frame per island: X along the longest axis) and
    'island_rand' (0..1 per island) point attributes, plus 'grain_normal' (face
    domain): |face normal| in that island's frame, so materials know which of the
    two cross-grain axes runs across each face."""
    mesh = obj.data
    if "grain" in mesh.attributes or len(mesh.vertices) == 0:
        return np.zeros(0)
    co = np.empty(len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    isl = _islands(mesh)
    grain = np.zeros_like(co)
    rand = np.zeros(len(co))
    frames = np.zeros((len(co), 3, 3))
    sizes = []
    for root in np.unique(isl):
        idx = np.nonzero(isl == root)[0]
        sizes.append(len(idx))
        pts = co[idx]
        c = pts.mean(axis=0)
        d = pts - c
        if len(idx) >= 3:
            _, vecs = np.linalg.eigh(d.T @ d)
            axes = vecs[:, ::-1]  # longest first
        else:
            axes = np.eye(3)
        local = d @ axes
        frames[idx] = axes
        off = np.array([rng.uniform(0, 50), rng.choice((-1, 1)) * rng.uniform(0.05, 0.35),
                        rng.choice((-1, 1)) * rng.uniform(0.05, 0.35)])
        grain[idx] = local + off
        rand[idx] = rng.random()
    a = mesh.attributes.new("grain", "FLOAT_VECTOR", "POINT")
    a.data.foreach_set("vector", grain.ravel())
    r = mesh.attributes.new("island_rand", "FLOAT", "POINT")
    r.data.foreach_set("value", rand)
    if len(mesh.polygons):
        normals = np.empty(len(mesh.polygons) * 3)
        mesh.polygons.foreach_get("normal", normals)
        starts = np.empty(len(mesh.polygons), dtype=np.int64)
        mesh.polygons.foreach_get("loop_start", starts)
        corner_verts = np.empty(len(mesh.loops), dtype=np.int64)
        mesh.loops.foreach_get("vertex_index", corner_verts)
        first = corner_verts[starts]
        local_n = np.abs(np.einsum("fi,fij->fj", normals.reshape(-1, 3), frames[first]))
        gn = mesh.attributes.new("grain_normal", "FLOAT_VECTOR", "FACE")
        gn.data.foreach_set("vector", local_n.ravel())
    return np.array(sizes)


def _bevel(obj, width):
    mod = obj.modifiers.new("bevel", "BEVEL")
    mod.width = width
    mod.segments = 2
    mod.limit_method = "ANGLE"
    mod.angle_limit = math.radians(35)
    mod.use_clamp_overlap = True
    mod.harden_normals = False


def _lamp_glow(scene, strength):
    shade = bpy.data.materials.get("lampshade")
    if shade:
        bsdf = next(n for n in shade.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
        bsdf.inputs["Emission Strength"].default_value = 0.04 * strength
    col = bpy.data.collections.get("Lighting") or scene.collection
    for obj in [o for o in scene.objects if o.type == "MESH" and o.name.startswith("floor_lamp")]:
        top = max((obj.matrix_world @ v.co).z for v in obj.data.vertices)
        x, y = obj.matrix_world.translation.xy
        # one bulb inside the shade; no shadows from the shade itself, so it
        # behaves like an open-topped, open-bottomed drum
        light = bpy.data.lights.new(f"{obj.name}_bulb", "POINT")
        light.energy = 4.0 * strength
        light.shadow_soft_size = 0.05
        light.color = (1.0, 0.72, 0.45)
        try:
            light.cycles.cast_shadow = False
        except AttributeError:
            light.use_shadow = False
        lo = bpy.data.objects.new(f"{obj.name}_bulb", light)
        lo.location = (x, y, top - 0.16)
        col.objects.link(lo)


def finish_scene(scene):
    """Look pass over the built scene. Idempotent (guarded by a scene flag)."""
    if scene.get("look_finished"):
        return
    rng = random.Random(1234)
    for obj in scene.objects:
        if obj.type != "MESH":
            continue
        sizes = _write_grain(obj, rng)
        cols = {c.name for c in obj.users_collection}
        small_parts = len(sizes) and sizes.max() <= 66  # Builder boxes/cylinders only
        if (small_parts and cols & set(BEVEL_COLLECTIONS) and not obj.modifiers
                and not obj.name.startswith(BEVEL_SKIP_PREFIXES) and not obj.get("no_bevel")):
            heavy = obj.name.startswith(("joists",))
            fine = obj.name.endswith("_books") or obj.name.startswith(("papers", "window_", "door_"))
            _bevel(obj, 0.012 if heavy else 0.0015 if fine else 0.003)
        if small_parts:
            # smooth cylinders, crisp boxes (normals only; geometry untouched)
            try:
                obj.data.shade_smooth()
                obj.data.set_sharp_from_angle(angle=math.radians(30))
            except (AttributeError, TypeError):
                pass
    glow = scene.get("lamp_glow", 0.0)
    if glow:
        _lamp_glow(scene, glow)
    scene["look_finished"] = True
