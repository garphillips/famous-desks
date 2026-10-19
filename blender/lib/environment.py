"""Outdoors, sun and sky: everything outside the room's walls.

Shared by every room. Sun and sky angles: azimuth 0 = north, clockwise (east = 90).

The view out is built in layers, so each window sees its own slice of garden and
the layers slide past each other as you move between viewpoints:

- near (1-3 m): planting beds along the walls, shrubs made of real leaf geometry
  (one quad-strip leaf per leaf, textured from a CC0 beech leaf atlas, no alpha);
- middle (4-14 m): a lawn and a few Poly Haven trees (instanced glTF);
- far (15-35 m): a clipped boundary hedge, a street and the houses across it;
- beyond: a second, camera-only HDRI (distant tree line and sky) behind it all,
  while the main HDRI still lights the scene and fills the reflections.
"""

import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector, noise

from . import assets
from .geo import Builder, collection

GROUND_Z = -0.12  # lawn level outside (the room floor is at 0)

# LeafSet024 (ambientCG, beech): leaf rectangles in the 2K atlas as (u0, v0, u1, v1), stalk at v0.
LEAF_ATLAS = ("acg_LeafSet024", "LeafSet024_2K-JPG")
LEAF_RECTS = np.array([
    (0.383, 0.008, 0.613, 0.324), (0.719, 0.008, 0.941, 0.320), (0.051, 0.012, 0.277, 0.324),
    (0.391, 0.340, 0.613, 0.648), (0.719, 0.340, 0.941, 0.660), (0.055, 0.344, 0.281, 0.656),
    (0.047, 0.672, 0.289, 0.992), (0.719, 0.676, 0.949, 0.992), (0.391, 0.680, 0.609, 0.996),
])
LEAF_ASPECT = 0.716  # rectangle width / height (pixels)

# Poly Haven trees (glTF, real leaf geometry): file, crown radius and crown centre as fractions of the height
TREES = {
    "small": ("ph_tree_small_02", "tree_small_02_1k.gltf", 0.34, 0.65),
    "island": ("ph_island_tree_01", "island_tree_01_1k.gltf", 0.5, 0.6),
    "jacaranda": ("ph_jacaranda_tree", "jacaranda_tree_1k.gltf", 0.62, 0.62),
}


# --------------------------------------------------------------------------- materials

def _nodes(name):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat, None
    mat = bpy.data.materials.new(name)
    try:
        mat.use_nodes = True
    except AttributeError:
        pass
    return mat, mat.node_tree


def _node(nt, kind, inputs=None, **props):
    n = nt.nodes.new(kind)
    for k, v in props.items():
        setattr(n, k, v)
    for k, v in (inputs or {}).items():
        n.inputs[k].default_value = v
    return n


def _image(nt, asset_id, filename, colour=True, vector=None):
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(assets.path(asset_id, filename), check_existing=True)
    if not colour:
        tex.image.colorspace_settings.name = "Non-Color"
    tex.interpolation = "Cubic"
    if vector is not None:
        nt.links.new(vector, tex.inputs["Vector"])
    return tex


def _bsdf(nt):
    return next(n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")


def _translucent_mix(nt, bsdf, colour, fac):
    """Thin leaves: mix some translucency in so they glow when the sun is behind them."""
    out = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeOutputMaterial")
    trans = nt.nodes.new("ShaderNodeBsdfTranslucent")
    if isinstance(colour, bpy.types.NodeSocket):
        tint = _node(nt, "ShaderNodeMix", {"Factor": 1.0}, data_type="RGBA", blend_type="MULTIPLY")
        tint.inputs[7].default_value = (0.9, 1.0, 0.55, 1.0)  # yellower in transmission
        nt.links.new(colour, tint.inputs[6])
        nt.links.new(tint.outputs[2], trans.inputs["Color"])
    else:
        trans.inputs["Color"].default_value = colour
    mix = _node(nt, "ShaderNodeMixShader", {"Fac": fac})
    nt.links.new(bsdf.outputs[0], mix.inputs[1])
    nt.links.new(trans.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])


def leaf_material(name="out_beech_leaf"):
    """Beech leaves from the atlas; per-leaf 'leaf_rand' and per-shrub 'leaf_tone'
    (hue shift, saturation, value) vary the colour."""
    mat, nt = _nodes(name)
    if nt is None:
        return mat
    link = nt.links.new
    asset, stem = LEAF_ATLAS
    uv = _node(nt, "ShaderNodeUVMap")
    col = _image(nt, asset, f"{stem}_Color.jpg", vector=uv.outputs[0])
    rough = _image(nt, asset, f"{stem}_Roughness.jpg", False, uv.outputs[0])
    nor = _image(nt, asset, f"{stem}_NormalGL.jpg", False, uv.outputs[0])
    nmap = _node(nt, "ShaderNodeNormalMap", {"Strength": 0.6})
    link(nor.outputs["Color"], nmap.inputs["Color"])
    rnd = _node(nt, "ShaderNodeAttribute", attribute_name="leaf_rand")
    tone = _node(nt, "ShaderNodeAttribute", attribute_name="leaf_tone")
    sep = _node(nt, "ShaderNodeSeparateXYZ")
    link(tone.outputs["Vector"], sep.inputs[0])
    hue = _node(nt, "ShaderNodeMath", operation="MULTIPLY_ADD")  # 0.5 + hue shift + small per-leaf jitter
    jitter = _node(nt, "ShaderNodeMapRange", {"To Min": -0.015, "To Max": 0.015})
    link(rnd.outputs["Fac"], jitter.inputs["Value"])
    hue.inputs[1].default_value = 1.0
    link(sep.outputs[0], hue.inputs[0])
    link(jitter.outputs[0], hue.inputs[2])
    hue_off = _node(nt, "ShaderNodeMath", {1: 0.5}, operation="ADD")
    link(hue.outputs[0], hue_off.inputs[0])
    val = _node(nt, "ShaderNodeMapRange", {"To Min": 0.7, "To Max": 1.15})
    link(rnd.outputs["Fac"], val.inputs["Value"])
    val2 = _node(nt, "ShaderNodeMath", operation="MULTIPLY")
    link(val.outputs[0], val2.inputs[0])
    link(sep.outputs[2], val2.inputs[1])
    hsv = _node(nt, "ShaderNodeHueSaturation")
    link(hue_off.outputs[0], hsv.inputs["Hue"])
    link(sep.outputs[1], hsv.inputs["Saturation"])
    link(val2.outputs[0], hsv.inputs["Value"])
    link(col.outputs["Color"], hsv.inputs["Color"])
    bsdf = _bsdf(nt)
    link(hsv.outputs[0], bsdf.inputs["Base Color"])
    link(rough.outputs["Color"], bsdf.inputs["Roughness"])
    link(nmap.outputs[0], bsdf.inputs["Normal"])
    bsdf.inputs["Specular IOR Level"].default_value = 0.25
    _translucent_mix(nt, bsdf, hsv.outputs[0], 0.22)
    return mat


def hedge_core_material(name="out_hedge_core"):
    """The shaded inside of a hedge: twiggy dark green-brown, seen between the leaves."""
    mat, nt = _nodes(name)
    if nt is None:
        return mat
    tc = _node(nt, "ShaderNodeTexCoord")
    n = _node(nt, "ShaderNodeTexNoise", {"Scale": 9.0, "Detail": 6.0, "Roughness": 0.65})
    nt.links.new(tc.outputs["Object"], n.inputs["Vector"])
    ramp = _node(nt, "ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.012, 0.016, 0.006, 1)
    ramp.color_ramp.elements[1].color = (0.05, 0.075, 0.022, 1)
    nt.links.new(n.outputs["Fac"], ramp.inputs["Fac"])
    bsdf = _bsdf(nt)
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.9
    return mat


def lawn_material(name="out_lawn"):
    """Grass004 at two scales (so it doesn't tile), with mown patches and dry spots."""
    mat, nt = _nodes(name)
    if nt is None:
        return mat
    link = nt.links.new
    tc = _node(nt, "ShaderNodeTexCoord")
    maps = []
    for scale, rot in ((1 / 1.4, 0.0), (1 / 2.3, 0.9)):
        m = _node(nt, "ShaderNodeMapping")
        m.inputs["Scale"].default_value = (scale, scale, scale)
        m.inputs["Rotation"].default_value = (0, 0, rot)
        link(tc.outputs["Object"], m.inputs["Vector"])
        maps.append(m.outputs[0])
    a = "acg_Grass004"
    cols = [_image(nt, a, "Grass004_2K-JPG_Color.jpg", vector=v) for v in maps]
    nors = [_image(nt, a, "Grass004_2K-JPG_NormalGL.jpg", False, v) for v in maps]
    blend = _node(nt, "ShaderNodeTexNoise", {"Scale": 0.35, "Detail": 2.0})
    link(tc.outputs["Object"], blend.inputs["Vector"])
    fac = _node(nt, "ShaderNodeMapRange", {"From Min": 0.4, "From Max": 0.6})
    link(blend.outputs["Fac"], fac.inputs["Value"])
    mixc = _node(nt, "ShaderNodeMix", data_type="RGBA")
    link(fac.outputs[0], mixc.inputs["Factor"])
    link(cols[0].outputs["Color"], mixc.inputs[6])
    link(cols[1].outputs["Color"], mixc.inputs[7])
    mixn = _node(nt, "ShaderNodeMix", data_type="RGBA")
    link(fac.outputs[0], mixn.inputs["Factor"])
    link(nors[0].outputs["Color"], mixn.inputs[6])
    link(nors[1].outputs["Color"], mixn.inputs[7])
    # broad patches: lush/dark and sun-dried
    patch = _node(nt, "ShaderNodeTexNoise", {"Scale": 0.12, "Detail": 3.0, "Roughness": 0.6})
    link(tc.outputs["Object"], patch.inputs["Vector"])
    tint = _node(nt, "ShaderNodeValToRGB")
    els = tint.color_ramp.elements
    els[0].position, els[0].color = 0.3, (0.42, 0.5, 0.3, 1)
    els[1].position, els[1].color = 0.7, (0.66, 0.62, 0.4, 1)
    link(patch.outputs["Fac"], tint.inputs["Fac"])
    shade = _node(nt, "ShaderNodeMix", {"Factor": 1.0}, data_type="RGBA", blend_type="MULTIPLY")
    link(mixc.outputs[2], shade.inputs[6])
    link(tint.outputs["Color"], shade.inputs[7])
    nmap = _node(nt, "ShaderNodeNormalMap", {"Strength": 0.8})
    link(mixn.outputs[2], nmap.inputs["Color"])
    bsdf = _bsdf(nt)
    link(shade.outputs[2], bsdf.inputs["Base Color"])
    link(nmap.outputs[0], bsdf.inputs["Normal"])
    bsdf.inputs["Roughness"].default_value = 0.85
    bsdf.inputs["Specular IOR Level"].default_value = 0.3
    _translucent_mix(nt, bsdf, shade.outputs[2], 0.12)
    return mat


def _plain_material(name, dark, light, scale, rough):
    """Noise-mottled flat material (bed soil, asphalt)."""
    mat, nt = _nodes(name)
    if nt is None:
        return mat
    tc = _node(nt, "ShaderNodeTexCoord")
    n = _node(nt, "ShaderNodeTexNoise", {"Scale": scale, "Detail": 8.0, "Roughness": 0.7})
    nt.links.new(tc.outputs["Object"], n.inputs["Vector"])
    ramp = _node(nt, "ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*dark, 1)
    ramp.color_ramp.elements[1].color = (*light, 1)
    nt.links.new(n.outputs["Fac"], ramp.inputs["Fac"])
    bump = _node(nt, "ShaderNodeBump", {"Strength": 0.4, "Distance": 0.01})
    nt.links.new(n.outputs["Fac"], bump.inputs["Height"])
    bsdf = _bsdf(nt)
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bump.outputs[0], bsdf.inputs["Normal"])
    bsdf.inputs["Roughness"].default_value = rough
    return mat


def _leafy(mat):
    """Poly Haven tree leaves: opaque (the jpg alpha is always 1, so skip the
    transparency test on every shadow ray) and a little translucent."""
    if mat.get("out_leafy"):
        return
    mat["out_leafy"] = True
    nt = mat.node_tree
    bsdf = _bsdf(nt)
    for l in list(bsdf.inputs["Alpha"].links):
        nt.links.remove(l)
    bsdf.inputs["Alpha"].default_value = 1.0
    try:
        mat.surface_render_method = "DITHERED"
    except AttributeError:
        pass
    src = bsdf.inputs["Base Color"].links
    _translucent_mix(nt, bsdf, src[0].from_socket if src else (0.2, 0.3, 0.05, 1), 0.25)


# --------------------------------------------------------------------------- leaf geometry

def _leaf_template():
    """One leaf, stalk at the origin pointing along +Y, length 1: six vertices
    (stalk, two pairs of edge points, tip), bowed and curling down at the tip."""
    xy = np.array([(0.0, 0.0), (-0.345, 0.32), (0.345, 0.32), (-0.27, 0.7), (0.27, 0.7), (0.0, 1.0)])
    z = 0.12 * np.abs(xy[:, 0]) - 0.16 * (xy[:, 1] - 0.3) ** 2
    faces = [(0, 2, 1), (1, 2, 4, 3), (3, 4, 5)]
    uv = np.stack([xy[:, 0] / LEAF_ASPECT + 0.5, xy[:, 1]], axis=1)
    return xy[:, 0], xy[:, 1], z, faces, uv


def _write_leaves(name, col, mat, P, N, D, S, rand, tone, variant):
    """One mesh holding every leaf: positions P, normals N, along-the-leaf
    directions D (all (n, 3)), lengths S, per-leaf rand (0..1), tone (n, 3) and
    atlas variant (n,)."""
    tx, ty, tz, faces, tuv = _leaf_template()
    n, nv, nf = len(P), len(tx), len(faces)
    X = np.cross(D, N)
    co = (P[:, None, :] + S[:, None, None] * (tx[None, :, None] * X[:, None, :] + ty[None, :, None] * D[:, None, :]
                                              + tz[None, :, None] * N[:, None, :]))
    idx = np.array([v for f in faces for v in f])
    sizes = np.array([len(f) for f in faces])
    starts = np.concatenate([[0], np.cumsum(sizes)[:-1]])
    nl = len(idx)
    mesh = bpy.data.meshes.new(name)
    mesh.vertices.add(n * nv)
    mesh.vertices.foreach_set("co", co.reshape(-1).astype(np.float32))
    mesh.loops.add(n * nl)
    mesh.loops.foreach_set("vertex_index", (idx[None, :] + nv * np.arange(n)[:, None]).reshape(-1).astype(np.int32))
    mesh.polygons.add(n * nf)
    mesh.polygons.foreach_set("loop_start", (starts[None, :] + nl * np.arange(n)[:, None]).reshape(-1).astype(np.int32))
    mesh.update(calc_edges=True)
    rect = LEAF_RECTS[variant]  # (n, 4)
    luv = tuv[idx]  # (nl, 2)
    u = rect[:, None, 0] + luv[None, :, 0] * (rect[:, None, 2] - rect[:, None, 0])
    v = rect[:, None, 1] + luv[None, :, 1] * (rect[:, None, 3] - rect[:, None, 1])
    mesh.uv_layers.new(name="UVMap").data.foreach_set("uv", np.stack([u, v], axis=2).reshape(-1).astype(np.float32))
    a = mesh.attributes.new("leaf_rand", "FLOAT", "FACE")
    a.data.foreach_set("value", np.repeat(rand, nf).astype(np.float32))
    a = mesh.attributes.new("leaf_tone", "FLOAT_VECTOR", "FACE")
    a.data.foreach_set("vector", np.repeat(tone, nf, axis=0).reshape(-1).astype(np.float32))
    mesh.shade_smooth()
    mesh.materials.append(mat)
    return _outdoor_object(name, mesh, col)


def _outdoor_object(name, mesh, col):
    # finish_scene() writes per-island 'grain' attributes on every mesh, which takes
    # minutes on a million leaves; nothing outside uses them, so mark them done.
    if "grain" not in mesh.attributes:
        mesh.attributes.new("grain", "FLOAT_VECTOR", "POINT")
    obj = bpy.data.objects.new(name, mesh)
    obj["no_bevel"] = True
    col.objects.link(obj)
    return obj


class Planting:
    """Leafy masses: lumpy cores (the dark inside of a shrub or hedge) covered in
    leaves scattered over their surface."""

    def __init__(self, seed):
        self.rng = np.random.default_rng(seed)
        self.bm = bmesh.new()
        self.leaves = []  # per mass: (P, N, D, S, rand, tone, variant)

    def mass(self, centre, radii, density, leaf=(0.06, 0.09), tone=(0.0, 1.0, 1.0), box=0.0, lump=0.18, depth=0.05):
        """A shrub (box=0) or a clipped block (box ~0.6). density: leaves per m^2 of core."""
        rng = self.rng
        res = bmesh.ops.create_icosphere(self.bm, subdivisions=3, radius=1.0)
        verts = res["verts"]
        off = Vector(rng.uniform(0, 100, 3))
        c = Vector(centre)
        for v in verts:
            d = v.co.copy()
            if box:
                d = Vector(tuple(math.copysign(abs(k) ** (1.0 - box), k) for k in d))
            nz = noise.noise(d * 1.7 + off) + 0.5 * noise.noise(d * 4.5 + off)
            v.co = c + Vector((d.x * radii[0], d.y * radii[1], d.z * radii[2])) * (1.0 + lump * nz)
        faces = list({f for v in verts for f in v.link_faces})
        tri = np.array([[list(l.vert.co) for l in f.loops] for f in faces])  # icosphere: triangles
        e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
        cr = np.cross(e1, e2)
        area = np.linalg.norm(cr, axis=1) / 2
        nrm = cr / np.maximum(np.linalg.norm(cr, axis=1, keepdims=True), 1e-9)
        nrm *= np.sign(np.einsum("ij,ij->i", nrm, tri.mean(axis=1) - np.array(centre)))[:, None]
        count = int(area.sum() * density)
        pick = rng.choice(len(tri), count, p=area / area.sum())
        r1, r2 = np.sqrt(rng.random(count)), rng.random(count)
        P = tri[pick, 0] * (1 - r1)[:, None] + tri[pick, 1] * (r1 * (1 - r2))[:, None] + tri[pick, 2] * (r1 * r2)[:, None]
        nr = nrm[pick]
        keep = P[:, 2] > GROUND_Z + 0.03
        P, nr = P[keep], nr[keep]
        count = len(P)
        P = P + nr * rng.uniform(-depth, depth * 1.2, count)[:, None]
        rv = rng.normal(size=(count, 3))
        rv /= np.linalg.norm(rv, axis=1, keepdims=True)
        N = nr + 0.75 * rv + np.array([0, 0, 0.35])
        N /= np.linalg.norm(N, axis=1, keepdims=True)
        rd = rng.normal(size=(count, 3)) + nr * 0.8 + np.array([0, 0, -0.25])
        D = rd - np.einsum("ij,ij->i", rd, N)[:, None] * N
        D /= np.maximum(np.linalg.norm(D, axis=1, keepdims=True), 1e-9)
        S = rng.uniform(*leaf, count)
        tone = np.tile(np.array(tone, dtype=float), (count, 1))
        self.leaves.append((P, N, D, S, rng.random(count), tone, rng.integers(0, len(LEAF_RECTS), count)))

    def build(self, name, col):
        mesh = bpy.data.meshes.new(f"{name}_cores")
        self.bm.to_mesh(mesh)
        self.bm.free()
        mesh.materials.append(hedge_core_material())
        mesh.shade_smooth()
        cores = _outdoor_object(f"{name}_cores", mesh, col)
        if not self.leaves:
            return cores, None
        parts = [np.concatenate(k) for k in zip(*self.leaves)]
        leaves = _write_leaves(f"{name}_leaves", col, leaf_material(), *parts)
        return cores, leaves


# --------------------------------------------------------------------------- the garden

SIDES = {  # outward normal, along-axis for each wall
    "N": ((0, 1), (1, 0)), "S": ((0, -1), (-1, 0)), "E": ((1, 0), (0, -1)), "W": ((-1, 0), (0, 1)),
}


def _side_frame(fp, side):
    """(origin at the wall's middle, outward normal, along, half length) for a footprint side."""
    x0, y0, x1, y1 = fp
    (nx, ny), (ax, ay) = SIDES[side]
    cx = x1 if nx > 0 else x0 if nx < 0 else (x0 + x1) / 2
    cy = y1 if ny > 0 else y0 if ny < 0 else (y0 + y1) / 2
    half = (x1 - x0) / 2 if ax else (y1 - y0) / 2
    return np.array((cx, cy)), np.array((nx, ny), float), np.array((ax, ay), float), half


def _sun_dir(azimuth, elevation):
    az, el = math.radians(azimuth), math.radians(elevation)
    return np.array((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)))


def _wall_points(fp):
    """Points along the outside walls at window height (for the sun-path test)."""
    x0, y0, x1, y1 = fp
    pts = []
    for z in (0.9, 1.6, 2.3):
        for x in np.arange(x0, x1 + 0.01, 0.5):
            pts += [(x, y0, z), (x, y1, z)]
        for y in np.arange(y0, y1 + 0.01, 0.5):
            pts += [(x0, y, z), (x1, y, z)]
    return np.array(pts)


def _shades_walls(centre, radius, walls, sun):
    w = np.asarray(centre) - walls
    t = w @ sun
    d2 = np.einsum("ij,ij->i", w, w) - t ** 2
    return bool(np.any((t > 0) & (d2 < radius ** 2)))


def build_garden(mats, footprint, sides="NE", sun_azimuth=75.0, sun_elevation=25.0, seed=3,
                 hedge_out=15.0, street_out=(17.5, 24.0)):
    """The layered garden round a building whose outside walls span footprint
    (x0, y0, x1, y1). ``sides`` are the walls with windows: those get the
    planting beds and trees, the others only lawn, the boundary hedge and houses.
    Trees are kept out of the sun's path to the walls, so the sun patches stay."""
    col = collection("Outdoors")
    rng = np.random.default_rng(seed)
    x0, y0, x1, y1 = footprint
    sun = _sun_dir(sun_azimuth, sun_elevation)
    walls = _wall_points(footprint)

    # ground: lawn everywhere, soil beds along the dressed walls, the street beyond the hedge
    g = Builder()
    g.box((400.0, 400.0, 0.1), (0, 0, GROUND_Z - 0.05), lawn_material())
    soil = _plain_material("out_soil", (0.035, 0.025, 0.017), (0.09, 0.065, 0.045), 14.0, 0.95)
    road = _plain_material("out_asphalt", (0.05, 0.05, 0.05), (0.13, 0.125, 0.12), 40.0, 0.8)
    for s in sides:
        o, n, a, half = _side_frame(footprint, s)
        c = o + n * 0.9
        size = (abs(a[0]) * (2 * half + 3.6) + abs(n[0]) * 1.8, abs(a[1]) * (2 * half + 3.6) + abs(n[1]) * 1.8, 0.04)
        g.box(size, (c[0], c[1], GROUND_Z + 0.01), soil)
    for s in "NESW":
        o, n, a, half = _side_frame(footprint, s)
        mid = o + n * sum(street_out) / 2
        w = street_out[1] - street_out[0]
        size = (abs(a[0]) * 300 + abs(n[0]) * w, abs(a[1]) * 300 + abs(n[1]) * w, 0.04)
        g.box(size, (mid[0], mid[1], GROUND_Z + 0.005), road)
    _outdoor_object("ground", _bm_mesh(g, "ground"), col)

    # near: shrubs in the beds (beech, laurel-dark and a few yellow-green), with gaps
    near = Planting(seed)
    tones = [(0.0, 1.15, 0.62), (0.025, 1.0, 0.45), (-0.025, 1.25, 0.75), (0.012, 1.1, 0.55)]
    for s in sides:
        o, n, a, half = _side_frame(footprint, s)
        t = -half - 1.4
        while t < half + 1.4:
            if rng.random() < 0.85:
                h = rng.uniform(0.55, 1.1)
                r = rng.uniform(0.45, 0.75)
                p = o + a * t + n * rng.uniform(0.55, 1.2)
                near.mass((p[0], p[1], GROUND_Z + h * 0.45), (r, r * 0.9, h * 0.55), density=900,
                          tone=tones[rng.integers(len(tones))], lump=0.25)
            t += rng.uniform(0.7, 1.3)
        # a couple of bigger, looser shrubs a few metres out, each a cluster of lobes
        for _ in range(3):
            p = o + a * rng.uniform(-half - 3, half + 3) + n * rng.uniform(3.2, 5.5)
            h = rng.uniform(1.2, 1.9)
            if _shades_walls((p[0], p[1], GROUND_Z + h * 0.5), h * 0.8, walls, sun):
                continue
            tone = tones[rng.integers(len(tones))]
            for _ in range(rng.integers(3, 6)):
                q = p + rng.normal(0, h * 0.3, 2)
                lh = h * rng.uniform(0.55, 1.0)
                lr = lh * rng.uniform(0.3, 0.45)
                near.mass((q[0], q[1], GROUND_Z + lh - lr * 0.9), (lr, lr * rng.uniform(0.8, 1.1), lr * 1.05),
                          density=750, tone=tone, leaf=(0.06, 0.09), lump=0.35)
    near.build("shrubs", col)

    # far: the clipped boundary hedge all round (sparser, bigger leaves: it's 15 m away)
    far = Planting(seed + 1)
    hx0, hy0, hx1, hy1 = x0 - hedge_out, y0 - hedge_out, x1 + hedge_out, y1 + hedge_out
    for side, (ax0, ay0, ax1, ay1) in zip("NESW", ((hx0, hy1, hx1, hy1), (hx1, hy0, hx1, hy1), (hx0, hy0, hx1, hy0),
                                                (hx0, hy0, hx0, hy1))):
        length = math.hypot(ax1 - ax0, ay1 - ay0)
        k = int(length / 1.6)
        along_x = abs(ax1 - ax0) > 0
        for i in range(k + 1):
            f = i / k
            h = 1.9 * rng.uniform(0.96, 1.04)
            cx, cy = ax0 + (ax1 - ax0) * f, ay0 + (ay1 - ay0) * f
            rx, ry = (1.05, 0.55) if along_x else (0.55, 1.05)
            # leaves only where a window looks out; elsewhere the dark core is enough
            far.mass((cx, cy, GROUND_Z + h * 0.5), (rx, ry, h * 0.55), density=200 if side in sides else 0,
                     leaf=(0.1, 0.14),
                     tone=(0.015, 1.05, 0.5), box=0.6, lump=0.08, depth=0.04)
    far.build("hedge", col)

    # middle: trees on the lawn, out of the sun's path to the walls
    spots = []
    for s in sides:
        o, n, a, half = _side_frame(footprint, s)
        for t in np.arange(-half - 9, half + 9, 4.5):
            for _ in range(4):
                kind = ("small", "island")[rng.choice(2, p=(0.45, 0.55))]
                h = {"small": rng.uniform(4.0, 5.5), "island": rng.uniform(5.5, 7.5),
                     "jacaranda": rng.uniform(8.5, 11.0)}[kind]
                out = rng.uniform(4.5, 8.0) if kind == "small" else rng.uniform(9.0, hedge_out - 2.0)
                p = o + a * (t + rng.uniform(-1.5, 1.5)) + n * out
                r = TREES[kind][2] * h
                if not (hx0 + 1 < p[0] < hx1 - 1 and hy0 + 1 < p[1] < hy1 - 1):
                    continue
                if _shades_walls((p[0], p[1], GROUND_Z + TREES[kind][3] * h), r, walls, sun):
                    continue
                if any(np.hypot(*(p - q)) < 0.75 * (r + rq) for q, rq, _, _ in spots):
                    continue
                spots.append((p, r, kind, h))
                break
    _plant_trees(col, spots, rng)

    # far: houses across the street, facing the garden
    _houses(mats, col, footprint, sides, rng, street_out[1] + 3.0)
    return col


def _bm_mesh(b, name):
    mesh = bpy.data.meshes.new(name)
    b.bm.to_mesh(mesh)
    b.bm.free()
    for m in b.mats:
        mesh.materials.append(m)
    return mesh


def _plant_trees(col, spots, rng):
    loaded = {}
    from .imported import load  # imported.py pulls in this module's neighbours; keep the import local
    for i, (p, r, kind, h) in enumerate(spots):
        asset, filename, _, _ = TREES[kind]
        if kind not in loaded:
            src = load(asset, filename, col, f"tree_{kind}", height=1.0)
            for slot in src.material_slots:
                if slot.material and "leaves" in slot.material.name:
                    _leafy(slot.material)
            _outdoor_object_mark(src)
            src.hide_render = True  # the template; every tree is an instance of it
            loaded[kind] = src
        obj = loaded[kind].copy()  # shares the mesh: Cycles instances it
        obj.name = f"tree_{i:02d}_{kind}"
        obj.hide_render = False
        obj.location = (p[0], p[1], GROUND_Z - 0.05)
        obj.rotation_euler = (0, 0, rng.uniform(0, 2 * math.pi))
        obj.scale = (h * rng.uniform(0.9, 1.1), h * rng.uniform(0.9, 1.1), h)
        col.objects.link(obj)


def _outdoor_object_mark(obj):
    if "grain" not in obj.data.attributes:
        obj.data.attributes.new("grain", "FLOAT_VECTOR", "POINT")
    obj["no_bevel"] = True


def _houses(mats, col, footprint, sides, rng, out):
    """Two-storey houses with hipped/gabled roofs, in a row across the street from each dressed side."""
    hb = Builder()
    for s in sides:
        o, n, a, half = _side_frame(footprint, s)
        t = -half - 26 + rng.uniform(0, 4)
        while t < half + 26:
            w, d = rng.uniform(8.0, 11.5), rng.uniform(7.0, 9.0)
            eaves, ridge = rng.uniform(5.4, 6.4), 0.0
            ridge = eaves + rng.uniform(2.6, 3.6)
            p = o + a * (t + w / 2) + n * (out + d / 2 + rng.uniform(0, 3))
            wall = mats["house_render"] if rng.random() < 0.6 else mats["house_brick"]
            _house(hb, p[0], p[1], w, d, eaves, ridge, wall, mats, rot_y=bool(a[1]), z0=GROUND_Z)
            t += w + rng.uniform(3.0, 7.0)
    obj = hb.build("houses", col)
    _outdoor_object_mark(obj)


def _house(b, x, y, w, d, eaves, ridge, wall_mat, mats, rot_y=False, z0=0.0):
    """Simple gabled house; the ridge runs along X (or Y when rot_y). White-framed
    windows on two storeys, a chimney."""
    sx, sy = (d, w) if rot_y else (w, d)
    b.box((sx, sy, eaves), (x, y, z0 + eaves / 2), wall_mat)
    bm = b.bm
    over = 0.35
    base = [(x - sx / 2 - over, y - sy / 2 - over), (x + sx / 2 + over, y - sy / 2 - over),
            (x + sx / 2 + over, y + sy / 2 + over), (x - sx / 2 - over, y + sy / 2 + over)]
    if rot_y:
        ridge_pts = [(x, y - sy / 2 - over), (x, y + sy / 2 + over)]
    else:
        ridge_pts = [(x - sx / 2 - over, y), (x + sx / 2 + over, y)]
    vb = [bm.verts.new((px, py, z0 + eaves - 0.15)) for px, py in base]
    vr = [bm.verts.new((px, py, z0 + ridge)) for px, py in ridge_pts]
    if rot_y:
        faces = [(vb[0], vb[1], vr[0]), (vb[1], vb[2], vr[1], vr[0]), (vb[2], vb[3], vr[1]),
                 (vb[3], vb[0], vr[0], vr[1]), (vb[3], vb[2], vb[1], vb[0])]
    else:
        faces = [(vb[0], vb[1], vr[1], vr[0]), (vb[1], vb[2], vr[1]), (vb[2], vb[3], vr[0], vr[1]),
                 (vb[3], vb[0], vr[0]), (vb[3], vb[2], vb[1], vb[0])]
    for f in faces:
        bm.faces.new(f)
    b._assign(vb + vr, mats["roof_slate"])
    cx, cy = (x, y + sy * 0.25) if rot_y else (x + sx * 0.25, y)
    b.box((0.6, 0.6, ridge - eaves + 1.0), (cx, cy, z0 + (eaves + ridge) / 2 + 0.6), wall_mat)  # chimney
    for level in (eaves * 0.3, eaves * 0.74):
        for t in (-0.32, -0.1, 0.12, 0.33):
            for side in (-1, 1):
                if rot_y:
                    p, size, fr = (x + side * sx / 2, y + t * sy, z0 + level), (0.06, 1.0, 1.3), (0.04, 1.14, 1.44)
                else:
                    p, size, fr = (x + t * sx, y + side * sy / 2, z0 + level), (1.0, 0.06, 1.3), (1.14, 0.04, 1.44)
                b.box(fr, p, mats["sash_white"])
                b.box(size, p, mats["steel_black"])


build_outdoors = build_garden  # older name (lib.architecture re-exports it)


# --------------------------------------------------------------------------- sun and sky

def build_sun(azimuth_deg, elevation_deg, strength=4.0, colour=(1.0, 0.82, 0.68), angle_deg=0.6):
    """Sun shining FROM the given azimuth (0 = north, 90 = east)."""
    col = collection("Lighting")
    light = bpy.data.lights.new("sun", "SUN")
    light.energy = strength
    light.color = colour
    light.angle = math.radians(angle_deg)
    obj = bpy.data.objects.new("sun", light)
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    towards_sun = Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)))
    obj.rotation_euler = (-towards_sun).to_track_quat("-Z", "Y").to_euler()
    col.objects.link(obj)
    return obj


# Irradiance of the Multiple Scattering sky's sun disc at 35 deg elevation relative
# to world strength 1 (measured in Blender 5.2). build_sun(strength=SKY_SUN_RATIO * k)
# matches a sky of strength k.
SKY_SUN_RATIO = 155.0


def build_world(strength=0.1, sun_azimuth=200.0, sun_elevation=35.0, air=1.0, aerosol=1.6, colour=None):
    """Physical sky (Blender 5.x Multiple Scattering) lit for the given sun position.

    The sky's own sun disc is off; build_sun() adds a sun lamp at the same angle
    (cleaner shadows, less noise). Azimuth as build_sun: 0 = north, clockwise.
    `colour` keeps the old flat-colour sky as a fallback.
    """
    world = bpy.data.worlds.new("sky")
    bpy.context.scene.world = world
    try:
        world.use_nodes = True
    except AttributeError:
        pass
    nt = world.node_tree
    bg = nt.nodes.get("Background") or nt.nodes.new("ShaderNodeBackground")
    out = nt.nodes.get("World Output") or nt.nodes.new("ShaderNodeOutputWorld")
    bg.inputs["Strength"].default_value = strength
    if colour is not None:
        bg.inputs["Color"].default_value = (*colour, 1)
    else:
        sky = nt.nodes.new("ShaderNodeTexSky")
        sky.sky_type = "MULTIPLE_SCATTERING"
        sky.sun_disc = False
        sky.sun_elevation = math.radians(sun_elevation)
        sky.sun_rotation = math.radians(sun_azimuth)  # same clockwise-from-north convention
        sky.air_density = air
        sky.aerosol_density = aerosol
        nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    return world


# Daylight HDRIs (blender/assets/manifest/*.json). sun_azimuth: where the
# photo's sun lands with no rotation; sun_irradiance: the energy clamped out of its
# sun disc, relative to the sky (so a sun lamp of that strength puts it back).
HDRIS = {
    "studio_garden": {"asset": "hdri_studio_garden", "file": "studio_garden_8k.exr",
                      "sun_azimuth": 126.2, "sun_irradiance": 8.0},
    # open parkland: a distant tree line under a clear sky, used only as the view
    "pretoria_gardens": {"asset": "hdri_pretoria_gardens", "file": "pretoria_gardens_8k.exr",
                         "sun_azimuth": 126.6, "sun_irradiance": 8.0},
}


def _hdri_colour(nt, name, sun_azimuth, mirror, clamp):
    info = HDRIS[name]
    nodes, link = nt.nodes, nt.links.new
    coord = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    turn = (-sun_azimuth if mirror else sun_azimuth) - info["sun_azimuth"]
    mapping.inputs["Rotation"].default_value = (0, 0, math.radians(turn))
    mapping.inputs["Scale"].default_value = (-1 if mirror else 1, 1, 1)
    env = nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(assets.path(info["asset"], info["file"]), check_existing=True)
    env.interpolation = "Cubic"
    link(coord.outputs["Generated"], mapping.inputs["Vector"])
    link(mapping.outputs["Vector"], env.inputs["Vector"])
    colour = env.outputs["Color"]
    if clamp:
        lo = nodes.new("ShaderNodeVectorMath")
        lo.operation = "MINIMUM"
        lo.inputs[1].default_value = (clamp, clamp, clamp)
        link(colour, lo.inputs[0])
        colour = lo.outputs["Vector"]
    return colour


def build_hdri_world(name, sun_azimuth, strength=1.0, clamp=20.0, mirror=False, backplate=1.0,
                     view=None, view_strength=1.0):
    """Photographic sky: light and reflections, and (without ``view``) the view
    out of the windows.

    Rotated so the photo's sun sits at sun_azimuth (0 = north, clockwise); its
    disc is clamped away and build_sun() stands in for it. mirror flips the
    photo east-west (the sun stays put). backplate scales only what the camera
    sees directly, to balance the bright view against the interior. ``view``
    names a second HDRI that only camera rays see (the far distance behind the
    modelled garden), scaled by view_strength; light still comes from ``name``.
    """
    world = bpy.data.worlds.new("sky")
    bpy.context.scene.world = world
    nt = world.node_tree
    nodes, link = nt.nodes, nt.links.new
    bg = nodes.get("Background") or nodes.new("ShaderNodeBackground")
    out = nodes.get("World Output") or nodes.new("ShaderNodeOutputWorld")
    colour = _hdri_colour(nt, name, sun_azimuth, mirror, clamp)
    path = nodes.new("ShaderNodeLightPath")
    if view:
        far = _hdri_colour(nt, view, sun_azimuth, mirror, clamp)
        scaled = nodes.new("ShaderNodeVectorMath")
        scaled.operation = "SCALE"
        scaled.inputs["Scale"].default_value = view_strength
        link(far, scaled.inputs[0])
        pick = nodes.new("ShaderNodeMix")
        pick.data_type = "RGBA"
        link(path.outputs["Is Camera Ray"], pick.inputs["Factor"])
        link(colour, pick.inputs[6])
        link(scaled.outputs["Vector"], pick.inputs[7])
        colour = pick.outputs[2]
    link(colour, bg.inputs["Color"])
    if backplate == 1.0:
        bg.inputs["Strength"].default_value = strength
    else:
        mix = nodes.new("ShaderNodeMix")
        mix.inputs["A"].default_value = strength
        mix.inputs["B"].default_value = strength * backplate
        link(path.outputs["Is Camera Ray"], mix.inputs["Factor"])
        link(mix.outputs["Result"], bg.inputs["Strength"])
    link(bg.outputs[0], out.inputs["Surface"])
    return world


def build_daylight(sun_azimuth, sun_elevation, hdri="studio_garden", strength=1.0, mirror=False, backplate=1.0,
                   sun_colour=(1.0, 0.94, 0.88), view=None, view_strength=1.0):
    """HDRI sky plus a sun lamp standing in for its (clamped) sun, at the same azimuth and energy."""
    world = build_hdri_world(hdri, sun_azimuth, strength, mirror=mirror, backplate=backplate, view=view,
                             view_strength=view_strength)
    sun = build_sun(sun_azimuth, sun_elevation, strength=HDRIS[hdri]["sun_irradiance"] * strength, colour=sun_colour)
    return world, sun
