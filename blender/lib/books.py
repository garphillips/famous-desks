"""Books and the bookshelf.

Every book is its own object, so it can stand, lean, lie in a stack or sit a
little forward or back. Books with the same kind and (rounded) size share one
mesh. A book's look comes from the object, not the mesh:
- obj.color: cover colour;
- custom properties read by the cover shader (Attribute node, Object type):
  "bk" (style, finish, seed), "dims" (thickness, height, depth), "ink" and "alt"
  (lettering and second colour).
Spine graphics are procedural, in the spine's UV space (u across, v up): bands,
colour blocks, labels and rows of illegible glyph-like marks. Nothing readable.

Conventions match lib.furniture: a book's origin is the centre of its bottom
face, its spine faces local -Y, and X is its thickness.
"""

import math
import random

import bmesh
import bpy
import numpy as np
from mathutils import Matrix

from . import materials as mt
from .geo import Builder, collection

T = Matrix.Translation


def R(angle, axis):
    return Matrix.Rotation(angle, 4, axis)


# ----------------------------------------------------------------------------
# Materials
# ----------------------------------------------------------------------------


def _obj_attr(g, name):
    n = g.node("ShaderNodeAttribute", attribute_type="OBJECT", attribute_name=name)
    return n.outputs["Vector"], n.outputs["Color"]


def _between(g, x, a, b):
    return g.math("MULTIPLY", g.math("GREATER_THAN", x, a), g.math("LESS_THAN", x, b))


def _glyphs(g, u, v, t, h, seed, v0, v1, scale=1.0):
    """Rows of blocky 5x3 'characters' with word gaps, centred across the spine."""
    hu = g.math("MINIMUM", g.math("DIVIDE", 0.003 * scale, t), 0.15 * scale)
    adv = g.math("DIVIDE", g.math("MULTIPLY", g.math("MULTIPLY", hu, t), 1.5), h)
    q = g.math("DIVIDE", g.math("SUBTRACT", v, v0), adv)
    ci, f = g.math("FLOOR", q), g.math("FRACT", q)
    uu = g.math("DIVIDE", g.math("SUBTRACT", u, g.math("SUBTRACT", 0.5, hu)), g.math("MULTIPLY", hu, 2.0))
    gu, gf = g.math("FLOOR", g.math("MULTIPLY", uu, 5.0)), g.math("FLOOR", g.math("MULTIPLY", f, 4.0))
    word, _ = g.white(g.vec(ci, seed, 3.7))
    pix, _ = g.white(g.vec(g.math("ADD", g.math("MULTIPLY", ci, 5.0), gf), gu, seed))
    m = g.math("MULTIPLY", _between(g, uu, 0.0, 1.0), _between(g, v, v0, v1))
    m = g.math("MULTIPLY", m, g.math("GREATER_THAN", word, 0.2))
    m = g.math("MULTIPLY", m, g.math("GREATER_THAN", pix, 0.5))
    return g.math("MULTIPLY", m, g.math("LESS_THAN", gf, 2.5))


def _cover(name="book_cover"):
    mat, g, bsdf = mt._new(name, (0.4, 0.4, 0.4))
    u, v, _ = g.sep(g.node("ShaderNodeUVMap", uv_map="UVMap").outputs["UV"])
    info = g.node("ShaderNodeObjectInfo")
    rnd = info.outputs["Random"]
    bk, _ = _obj_attr(g, "bk")
    style, finish, seed = g.sep(bk)
    dims, _ = _obj_attr(g, "dims")
    t, h, _ = g.sep(dims)
    _, ink = _obj_attr(g, "ink")
    _, alt = _obj_attr(g, "alt")
    st = [g.math("COMPARE", style, k, 0.5) for k in range(6)]
    r1 = g.math("FRACT", g.math("MULTIPLY", seed, 7.31))
    r2 = g.math("FRACT", g.math("MULTIPLY", seed, 3.17))
    r3 = g.math("FRACT", g.math("MULTIPLY", seed, 11.3))
    spine = g.math("LESS_THAN", u, 1.5)

    plain_text = g.math("LESS_THAN", style, 3.5)
    title = _glyphs(g, u, v, t, h, seed, g.map(r1, 0, 1, 0.36, 0.5), g.map(r2, 0, 1, 0.62, 0.9))
    author = _glyphs(g, u, v, t, h, g.math("ADD", seed, 0.37), g.map(r3, 0, 1, 0.13, 0.17), 0.27, 0.7)
    mark = g.math("MULTIPLY", _between(g, u, 0.3, 0.7),
                  _between(g, v, 0.035, g.math("ADD", 0.035, g.math("DIVIDE", g.math("MULTIPLY", t, 0.4), h))))
    text = g.math("MULTIPLY", g.math("ADD", title, author), plain_text)
    text = g.math("ADD", text, g.math("MULTIPLY", mark, st[0]))
    bands = g.math("MULTIPLY", st[1], g.math("ADD", _between(g, v, 0.885, 0.9), _between(g, v, 0.1, 0.115)))
    ink_mask = g.math("MULTIPLY", g.math("MINIMUM", g.math("ADD", text, bands), 1.0), spine)
    block = g.math("MULTIPLY", st[2], g.math("GREATER_THAN", v, g.map(r3, 0, 1, 0.58, 0.8)))
    s0 = g.map(r1, 0, 1, 0.68, 0.82)
    stripe = g.math("MULTIPLY", st[3], _between(g, v, s0, g.math("ADD", s0, 0.07)))
    filing = g.math("ADD", st[4], st[5])
    label = g.math("MULTIPLY", filing, g.math("MULTIPLY", _between(g, u, 0.17, 0.83), _between(g, v, 0.52, 0.86)))
    label_text = g.math("MULTIPLY", label, _glyphs(g, u, v, t, h, seed, 0.6, 0.8, 0.8))
    dv = g.math("DIVIDE", g.math("MULTIPLY", g.math("SUBTRACT", v, 0.22), h), t)
    hole = g.math("MULTIPLY", filing, g.math("LESS_THAN", g.vmath("LENGTH", g.vec(g.math("SUBTRACT", u, 0.5), dv, 0.0)), 0.17))

    # sun-faded, slightly varied base; then the graphics, spine only
    col = g.hsv(info.outputs["Color"], 0.5, g.map(rnd, 0, 1, 0.8, 1.05), g.map(r2, 0, 1, 0.9, 1.05))
    col = g.mix(g.math("MULTIPLY", g.math("ADD", block, stripe), spine), col, alt)
    col = g.mix(g.math("MULTIPLY", label, spine), col, (0.80, 0.79, 0.75))
    col = g.mix(ink_mask, col, ink)
    col = g.mix(g.math("MULTIPLY", label_text, spine), col, (0.03, 0.03, 0.03))
    col = g.mix(g.math("MULTIPLY", hole, spine), col, (0.008, 0.008, 0.008))

    # rubbed spine edges and corners
    p = g.obj_coords()
    edge = g.math("MINIMUM", g.math("MINIMUM", u, g.math("SUBTRACT", 1.0, u)),
                  g.math("MULTIPLY", g.math("MINIMUM", v, g.math("SUBTRACT", 1.0, v)), 3.0))
    wear = g.math("MULTIPLY", g.map(edge, 0.0, 0.05, 1.0, 0.0), g.map(g.noise(p, 180.0, 3.0, 0.6), 0.45, 0.7))
    col = g.mix(g.math("MULTIPLY", g.math("MULTIPLY", wear, spine), 0.35), col, (0.5, 0.48, 0.45))

    foil = g.math("MULTIPLY", g.math("MULTIPLY", ink_mask, st[1]), g.math("GREATER_THAN", finish, 0.7))
    rough = g.map(finish, 0.0, 1.0, 0.16, 0.85)
    rough = g.mixf(g.math("MULTIPLY", wear, 0.6), rough, 0.7)
    rough = g.mixf(foil, rough, 0.3)
    cloth = g.math("MULTIPLY", g.noise(p, 1500.0, 2.0, 0.6), g.math("GREATER_THAN", finish, 0.8))
    relief = g.math("ADD", g.math("MULTIPLY", cloth, 0.6), g.math("MULTIPLY", ink_mask, -0.3))
    relief = g.math("ADD", relief, g.math("MULTIPLY", g.noise(p, 300.0, 2.0, 0.5), 0.15))
    mt._principled(g, bsdf, color=col, rough=rough, metal=foil, coat=g.map(finish, 0.0, 0.3, 0.6, 0.0),
                   coat_rough=0.12, sheen=g.map(finish, 0.6, 1.0, 0.0, 0.5), normal=g.bump(relief, 0.15, 0.0005))
    return mat


def _pages(name="book_pages"):
    """Page edges: fine lines across the block, cream to white, dusty on top."""
    mat, g, bsdf = mt._new(name, (0.78, 0.74, 0.64))
    rnd = g.node("ShaderNodeObjectInfo").outputs["Random"]
    p = g.obj_coords()
    x, _, _ = g.sep(p)
    wobble = g.math("MULTIPLY", g.noise(p, 60.0, 2.0, 0.5), 0.0006)
    lines = g.math("SINE", g.math("MULTIPLY", g.math("ADD", x, wobble), 9000.0))
    grain = g.noise(g.vec(g.math("MULTIPLY", x, 400.0), g.sep(p)[1], g.sep(p)[2]), 40.0, 3.0, 0.6)
    col = g.mix(g.math("POWER", rnd, 2.0), (0.80, 0.78, 0.71), (0.66, 0.58, 0.42))
    col = g.mix(g.math("GREATER_THAN", g.math("FRACT", g.math("MULTIPLY", rnd, 5.3)), 0.7), col, (0.83, 0.83, 0.80))
    col = g.mix(g.map(lines, -1.0, 1.0, 0.0, 0.18), col, (0.35, 0.32, 0.27), "MULTIPLY")
    col = g.mix(g.map(grain, 0.4, 0.7, 0.0, 0.15), col, (0.5, 0.46, 0.4))
    nz = g.sep(g.normal())[2]
    col = g.mix(g.math("MULTIPLY", g.math("GREATER_THAN", nz, 0.7), 0.22), col, (0.40, 0.38, 0.35))
    mt._principled(g, bsdf, color=col, rough=0.85, sheen=0.2, normal=g.bump(lines, 0.08, 0.0003))
    return mat


def _rattan(name="rattan"):
    """Woven cane: per-strand tone (island_rand) and fibres along each strand (grain)."""
    mat, g, bsdf = mt._new(name, (0.55, 0.40, 0.21))
    gv, _ = g.attr("grain")
    gx, gy, gz = g.sep(gv)
    _, rnd = g.attr("island_rand")
    fib = g.noise(g.vec(g.math("MULTIPLY", gx, 4.0), g.math("MULTIPLY", gy, 400.0), g.math("MULTIPLY", gz, 400.0)),
                  6.0, 4.0, 0.6)
    blot = g.noise(g.vec(gx, gy, gz), 25.0, 3.0, 0.6)
    col = g.mix(rnd, (0.46, 0.32, 0.16), (0.62, 0.47, 0.26))
    col = g.mix(g.map(fib, 0.35, 0.7, 0.0, 0.5), col, (0.30, 0.19, 0.08))
    col = g.mix(g.map(blot, 0.5, 0.75, 0.0, 0.3), col, (0.70, 0.56, 0.36))
    mt._principled(g, bsdf, color=col, rough=g.map(fib, 0.3, 0.7, 0.45, 0.7), sheen=0.25,
                   normal=g.bump(fib, 0.25, 0.0008))
    return mat


def _amber(name="amber_glass"):
    mat, g, bsdf = mt._new(name, (0.45, 0.18, 0.04))
    mt._principled(g, bsdf, color=(0.55, 0.22, 0.04), rough=0.06, transmission=1.0, ior=1.5)
    return mat


def _brass(name="brass"):
    mat, g, bsdf = mt._new(name, (0.75, 0.58, 0.3))
    n = g.noise(g.obj_coords(), 120.0, 3.0, 0.6)
    mt._principled(g, bsdf, color=(0.78, 0.6, 0.32), metal=1.0, rough=g.map(n, 0.3, 0.7, 0.22, 0.4))
    return mat


def materials():
    return {
        "cover": mt._cached("book_cover", _cover),
        "pages": mt._cached("book_pages", _pages),
        "rattan": mt._cached("rattan", _rattan),
        "amber": mt._cached("amber_glass", _amber),
        "brass": mt._cached("brass", _brass),
    }


# ----------------------------------------------------------------------------
# Book meshes
# ----------------------------------------------------------------------------

# board: cover thickness; over: board overhang past the pages; bulge: spine
# roundness (fraction of thickness, capped); p: superellipse power (2 round, 10 square)
KINDS = {
    "hardback": dict(board=0.0024, over=0.003, bulge=0.28, cap=0.009, p=2.4, n=12, pages=True),
    "paperback": dict(board=0.0008, over=0.0, bulge=0.25, cap=0.0015, p=8, n=10, pages=True),
    "magazine": dict(board=0.0004, over=0.0, bulge=0.3, cap=0.001, p=6, n=8, pages=True),
    "binder": dict(board=0.003, over=0.005, bulge=0.1, cap=0.004, p=10, n=10, pages=True),
    "box": dict(board=0.002, over=0.0, bulge=0.1, cap=0.002, p=12, n=10, pages=False),
}


def _arc(a, bulge, y0, p, n):
    """Spine profile from (+a, y0) round the front to (-a, y0)."""
    pts = []
    for i in range(n + 1):
        th = math.pi * i / n
        c, s = math.cos(th), math.sin(th)
        pts.append((a * math.copysign(abs(c) ** (2 / p), c), y0 - bulge * abs(s) ** (2 / p)))
    return pts


def _book_mesh(name, kind, t, d, h, bow=0.0):
    k = KINDS[kind]
    c = min(k["board"], t * 0.2)
    b = min(k["bulge"] * t, k["cap"])
    o = k["over"]
    e = min(0.0007, c * 0.45)  # chamfer on the cover edges
    y0 = -d / 2 + b
    outer = [(t / 2, d / 2)] + _arc(t / 2, b, y0, k["p"], k["n"]) + [(-t / 2, d / 2)]
    inner = [(t / 2 - c, d / 2)] + _arc(t / 2 - c, max(b - c, 0.0003), y0, k["p"], k["n"]) + [(-t / 2 + c, d / 2)]
    seg_kind = ["board"] + ["spine"] * k["n"] + ["board"]
    mid = list(np.linspace(0, h, 7)[1:-1]) if bow else []
    oz = [0.0, e] + mid + [h - e, h]
    iz = [0.0] + mid + [h]

    bm = bmesh.new()
    uv = bm.loops.layers.uv.new("UVMap")

    def ring(pts, z, pull=0.0):
        vs = []
        for (x, y), (xi, yi) in zip(pts, inner if pts is outer else pts):
            dx, dy = xi - x, yi - y
            ln = math.hypot(dx, dy) or 1.0
            vs.append(bm.verts.new((x + dx / ln * pull, y + dy / ln * pull, z)))
        return vs

    O = [ring(outer, z, e if z in (0.0, h) else 0.0) for z in oz]
    I = [ring(inner, z) for z in iz]

    def face(vs, label, mat=0):
        f = bm.faces.new(vs)
        f.material_index = mat
        for loop in f.loops:
            x, y, z = loop.vert.co
            if label == "spine":
                loop[uv].uv = ((x + t / 2) / t, z / h)
            elif label == "board":
                loop[uv].uv = (2.0 + (y + d / 2) / d, z / h)
            else:
                loop[uv].uv = (5.0, 0.0)
        return f

    n = len(outer)
    for i in range(n - 1):
        for lv in range(len(oz) - 1):
            face([O[lv][i], O[lv][i + 1], O[lv + 1][i + 1], O[lv + 1][i]], seg_kind[i])
        for lv in range(len(iz) - 1):
            face([I[lv][i + 1], I[lv][i], I[lv + 1][i], I[lv + 1][i + 1]], "inner")
        face([O[0][i + 1], O[0][i], I[0][i], I[0][i + 1]], "cap")
        face([O[-1][i], O[-1][i + 1], I[-1][i + 1], I[-1][i]], "cap")
    for i in (0, n - 1):
        face([O[lv][i] for lv in range(len(oz))] + [I[lv][i] for lv in reversed(range(len(iz)))], "cap")

    # the text block: inside the boards, behind the spine
    gap = 0.0004 if k["pages"] else 0.0
    _slab(bm, face, (-t / 2 + c + gap, t / 2 - c - gap), (y0 - max(b - c, 0.0) * 0.7, d / 2 - o),
          (o, h - o), [0.0] + mid + [h], 1 if k["pages"] else 0)

    if bow:
        for v in bm.verts:
            v.co.x += bow * math.sin(math.pi * v.co.z / h)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.shade_smooth()
    mesh.set_sharp_from_angle(angle=math.radians(38))
    return mesh


def _slab(bm, face, xs, ys, zs, levels, mat):
    """Box split at the given z levels (clamped into zs), so it can bend with a bowed cover."""
    z0, z1 = zs
    lv = sorted({min(max(z, z0), z1) for z in levels})
    rings = [[bm.verts.new((x, y, z)) for x, y in ((xs[0], ys[0]), (xs[1], ys[0]), (xs[1], ys[1]), (xs[0], ys[1]))]
             for z in lv]
    for a, b in zip(rings[:-1], rings[1:]):
        for i in range(4):
            j = (i + 1) % 4
            face([a[i], a[j], b[j], b[i]], "cap", mat)
    face(list(reversed(rings[0])), "cap", mat)
    face(rings[-1], "cap", mat)


# ----------------------------------------------------------------------------
# What's on the shelves: book families and colours
# ----------------------------------------------------------------------------

# cover colours (linear) and how common they are on these shelves: mostly
# white and black photography / design books, with runs of colour
PALETTE = [
    ((0.78, 0.77, 0.73), 22), ((0.70, 0.65, 0.53), 6), ((0.025, 0.025, 0.03), 18), ((0.08, 0.08, 0.085), 6),
    ((0.30, 0.30, 0.30), 4), ((0.55, 0.55, 0.53), 4), ((0.025, 0.05, 0.16), 6), ((0.07, 0.2, 0.48), 5),
    ((0.33, 0.52, 0.68), 3), ((0.04, 0.25, 0.26), 4), ((0.48, 0.05, 0.04), 5), ((0.72, 0.26, 0.05), 3),
    ((0.78, 0.58, 0.07), 4), ((0.66, 0.33, 0.38), 2), ((0.10, 0.22, 0.09), 3), ((0.22, 0.11, 0.05), 3),
]
GOLD = (0.8, 0.58, 0.26)

# kind, height / depth / thickness ranges (m), finishes (0 gloss .. 1 cloth), style weights
# styles: 0 plain title, 1 bands, 2 colour block, 3 stripe, 4 binder label, 5 box-file label
FAMILIES = {
    "paperback": dict(kind="paperback", h=(0.178, 0.198), d=(0.108, 0.13), t=(0.01, 0.032),
                      finish=(0.1, 0.45), styles={0: 5, 2: 2, 3: 2}),
    "novel": dict(kind="hardback", h=(0.215, 0.245), d=(0.14, 0.165), t=(0.02, 0.045),
                  finish=(0.45, 0.9), styles={0: 3, 1: 3, 2: 1}),
    "art": dict(kind="hardback", h=(0.25, 0.29), d=(0.21, 0.27), t=(0.012, 0.04),
                finish=(0.1, 0.4, 0.9), styles={0: 6, 2: 1, 3: 1}),
    "big": dict(kind="hardback", h=(0.3, 0.34), d=(0.24, 0.3), t=(0.015, 0.05),
                finish=(0.1, 0.4), styles={0: 5, 2: 1}),
    "catalog": dict(kind="paperback", h=(0.24, 0.3), d=(0.2, 0.24), t=(0.005, 0.014),
                    finish=(0.1, 0.45), styles={0: 4, 3: 1}),
    "magazine": dict(kind="magazine", h=(0.275, 0.297), d=(0.21, 0.225), t=(0.003, 0.008),
                     finish=(0.05,), styles={0: 3, 2: 2}),
    "binder": dict(kind="binder", h=(0.3, 0.315), d=(0.28, 0.285), t=(0.05, 0.075),
                   finish=(0.3,), styles={4: 1},
                   colours=[(0.02, 0.02, 0.022), (0.02, 0.02, 0.022), (0.75, 0.75, 0.72), (0.05, 0.12, 0.35)]),
    "boxfile": dict(kind="box", h=(0.33, 0.345), d=(0.24, 0.255), t=(0.075, 0.08),
                    finish=(0.35,), styles={5: 1}, colours=[(0.78, 0.78, 0.75)]),
    "slipcase": dict(kind="box", h=(0.26, 0.3), d=(0.22, 0.26), t=(0.035, 0.07),
                     finish=(0.15, 0.9), styles={0: 2, 2: 1}),
}
UPRIGHT = {"paperback": 1.5, "novel": 1.5, "art": 4, "big": 2.5, "catalog": 2.5, "magazine": 0.6, "slipcase": 0.4}
LYING = {"art": 4, "big": 3, "catalog": 2, "magazine": 2, "novel": 1, "paperback": 1}


def _weighted(rng, table):
    keys = list(table)
    return rng.choices(keys, [table[k] for k in keys])[0]


def _colour(rng, f):
    base = rng.choice(f["colours"]) if "colours" in f else rng.choices(*zip(*PALETTE))[0]
    k = rng.uniform(0.9, 1.08)
    return tuple(min(1.0, c * k) for c in base)


def _lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def book_spec(rng, fam, hmax, like=None):
    """A book of a family, or None if no book of that family fits under hmax.
    like: a previous spec to copy size and colour from (a series)."""
    f = FAMILIES[fam]
    if f["h"][0] > hmax - 0.008:
        return None
    if like:
        spec = dict(like, t=max(0.004, round(like["t"] * rng.uniform(0.8, 1.2) / 0.002) * 0.002),
                    seed=rng.random())
        return spec
    h = min(rng.uniform(*f["h"]), hmax - 0.008)
    t = rng.uniform(*f["t"])
    t = round(t / 0.001) * 0.001 if t < 0.012 else round(t / 0.002) * 0.002
    colour = _colour(rng, f)
    style = _weighted(rng, f["styles"])
    finish = rng.choice(f["finish"])
    dark = _lum(colour) < 0.2
    if style == 1 and finish > 0.7:
        ink = GOLD
    elif dark:
        ink = rng.choice([(0.8, 0.8, 0.77), (0.8, 0.8, 0.77), GOLD, (0.75, 0.3, 0.1)])
    else:
        ink = rng.choice([(0.02, 0.02, 0.02), (0.02, 0.02, 0.02), (0.4, 0.04, 0.03), (0.03, 0.08, 0.25)])
    alt = rng.choices(*zip(*PALETTE))[0]
    return dict(fam=fam, kind=f["kind"], t=t, d=round(rng.uniform(*f["d"]) / 0.005) * 0.005,
                h=round(h / 0.003) * 0.003, colour=colour, style=style, finish=finish,
                seed=rng.random(), ink=ink, alt=alt)


# ----------------------------------------------------------------------------
# Small shelf objects (Builder-based, so finish_scene bevels them)
# ----------------------------------------------------------------------------


def _clock(b, m, bm, rng):
    r, z = 0.045, 0.06
    b.cyl(r, 0.035, (0, 0, z), bm["brass"], rot=(math.pi / 2, 0, 0), segments=32)
    b.cyl(r - 0.005, 0.002, (0, -0.018, z), m["paper"], rot=(math.pi / 2, 0, 0), segments=32)
    for a, ln in ((rng.uniform(0, 6.3), 0.022), (rng.uniform(0, 6.3), 0.032)):
        b.box((0.003, 0.001, ln), (math.sin(a) * ln / 2, -0.0195, z + math.cos(a) * ln / 2), m["plastic_black"],
              rot=(0, a, 0))
    for sx in (-1, 1):
        b.cyl(0.016, 0.01, (sx * 0.026, 0, z + r + 0.004), bm["brass"], rot=(0, sx * 0.6, 0), segments=16)
        b.box((0.006, 0.006, 0.022), (sx * 0.03, 0, 0.011), bm["brass"], rot=(0, sx * 0.3, 0))
    return 0.11, 0.04


def _small_box(b, m, bm, rng):
    w, d, h = rng.uniform(0.06, 0.16), rng.uniform(0.06, 0.12), rng.uniform(0.03, 0.09)
    mat = m[rng.choice(["cardboard", "plastic_black", "plastic_black", "plastic_white", "paper"])]
    b.box((w, d, h - 0.012), (0, 0, (h - 0.012) / 2), mat)
    b.box((w + 0.003, d + 0.003, 0.014), (0, 0, h - 0.007), mat)
    return w, d


def _slr(b, m, bm, rng):
    b.box((0.135, 0.05, 0.075), (0, 0, 0.0375), m["plastic_black"])
    b.box((0.135, 0.05, 0.012), (0, 0, 0.081), m["aluminium"])
    b.box((0.055, 0.045, 0.035), (0, 0.003, 0.098), m["plastic_black"])
    b.cyl(0.031, 0.055, (0, -0.052, 0.042), m["plastic_black"], rot=(math.pi / 2, 0, 0), segments=28)
    b.cyl(0.024, 0.004, (0, -0.0805, 0.042), m["glass"], rot=(math.pi / 2, 0, 0), segments=28)
    return 0.14, 0.11


def _rangefinder(b, m, bm, rng):
    b.box((0.13, 0.035, 0.045), (0, 0, 0.0225), m["fabric_black"])
    b.box((0.13, 0.035, 0.032), (0, 0, 0.061), m["aluminium"])
    b.cyl(0.021, 0.035, (0, -0.035, 0.04), m["plastic_black"], rot=(math.pi / 2, 0, 0), segments=24)
    b.box((0.02, 0.002, 0.012), (-0.045, -0.018, 0.064), m["glass"])
    return 0.13, 0.07


def _jar(b, m, bm, rng):
    r, h = rng.uniform(0.018, 0.032), rng.uniform(0.06, 0.12)
    if rng.random() < 0.35:
        b.cyl(r * 0.8, h * 1.3, (0, 0, h * 0.65), m["plastic_white"], segments=20)
        b.cyl(r * 0.85, 0.015, (0, 0, h * 1.3 + 0.007), m["plastic_white"], segments=20)
        return 2 * r, 2 * r
    b.cyl(r, h, (0, 0, h / 2), bm["amber"], segments=24)
    b.cyl(r * 0.45, 0.012, (0, 0, h + 0.006), bm["amber"], segments=16)
    b.cyl(r * 0.5, 0.016, (0, 0, h + 0.02), m[rng.choice(["plastic_black", "plastic_white"])], segments=16)
    return 2 * r, 2 * r


def _radio(b, m, bm, rng):
    b.box((0.24, 0.08, 0.13), (0, 0, 0.065), m["oak"])
    b.box((0.12, 0.002, 0.09), (-0.05, -0.041, 0.065), m["aluminium"])
    b.box((0.07, 0.002, 0.03), (0.07, -0.041, 0.09), m["paper"])
    for x in (0.05, 0.09):
        b.cyl(0.011, 0.012, (x, -0.046, 0.04), m["plastic_black"], rot=(math.pi / 2, 0, 0), segments=16)
    b.box((0.2, 0.01, 0.008), (0, 0, 0.17), m["plastic_black"])
    for x in (-0.1, 0.1):
        b.box((0.008, 0.008, 0.04), (x, 0, 0.15), m["plastic_black"])
    return 0.24, 0.08


def _speaker(b, m, bm, rng):
    b.box((0.13, 0.16, 0.22), (0, 0, 0.11), m["plastic_black_satin"])
    b.cyl(0.045, 0.006, (0, -0.081, 0.08), m["fabric_black"], rot=(math.pi / 2, 0, 0), segments=28)
    b.cyl(0.015, 0.006, (0, -0.081, 0.17), m["plastic_black"], rot=(math.pi / 2, 0, 0), segments=20)
    return 0.13, 0.16


def _printer(b, m, bm, rng):
    b.box((0.44, 0.3, 0.15), (0, 0, 0.075), m["plastic_white"])
    b.box((0.42, 0.28, 0.025), (0, 0.005, 0.163), m["aluminium"])
    b.box((0.3, 0.004, 0.02), (0, -0.151, 0.05), m["plastic_black"])
    b.box((0.26, 0.12, 0.004), (0, -0.2, 0.04), m["plastic_white"])
    return 0.44, 0.3


def _laptop(b, m, bm, rng):
    z = 0
    for _ in range(rng.randint(1, 3)):
        b.box((0.32, 0.22, 0.018), (rng.uniform(-0.01, 0.01), 0, z + 0.009), m["aluminium"],
              rot=(0, 0, rng.uniform(-0.05, 0.05)))
        z += 0.018
    return 0.33, 0.23


def _frame(b, m, bm, rng):
    b.box((0.13, 0.012, 0.18), (0, 0.02, 0.088), m["plastic_black"], rot=(-0.18, 0, 0))
    b.box((0.1, 0.002, 0.14), (0, 0.013, 0.09), m["art_dark"], rot=(-0.18, 0, 0))
    return 0.13, 0.08


PROPS = {"clock": _clock, "box": _small_box, "slr": _slr, "rangefinder": _rangefinder, "jar": _jar,
         "radio": _radio, "speaker": _speaker, "printer": _printer, "laptop": _laptop, "frame": _frame}
LIMITS = {"clock": 1, "radio": 1, "speaker": 2, "frame": 1, "slr": 2, "rangefinder": 1}
SHELF_PROPS = {"box": 4, "slr": 1.5, "rangefinder": 1, "jar": 1.5, "radio": 0.6, "speaker": 0.6, "frame": 0.6,
               "clock": 0.3}


# ----------------------------------------------------------------------------
# Stocking the shelves
# ----------------------------------------------------------------------------

# segment weights per compartment recipe, plus chances of a stack on top of a
# run and of books leaning at the end of a run
RECIPES = {
    "dense": dict(run=8, stack=2.5, gap=0.1, objects=0.15, files=0.3, top=0.9, lean=0.3),
    "stacked": dict(run=4, stack=6, gap=0.05, objects=0.15, files=0, top=0.9, lean=0.2),
    "mixed": dict(run=6, stack=2, gap=0.25, objects=0.6, files=0.5, top=0.75, lean=0.5),
    "leaning": dict(run=6, stack=1.5, gap=0.2, objects=0.3, files=0.2, top=0.7, lean=0.9),
    "files": dict(run=3, stack=1, gap=0.15, objects=0.4, files=4, top=0.5, lean=0.3),
    "objects": dict(run=2.5, stack=1.5, gap=0.3, objects=3, files=0.3, top=0.5, lean=0.4),
}


class Stocker:
    """Places books and small objects in shelf-local space (x along the shelf,
    front at -y, z up); M maps that space into the world."""

    def __init__(self, m, mats, books_col, props_col, M, rng, prefix):
        self.m, self.mats, self.M, self.rng = m, mats, M, rng
        self.books_col, self.props_col, self.prefix = books_col, props_col, prefix
        self.meshes = {}
        self.count = 0
        self.used = {}  # how many of each small object are on the shelf

    def mesh(self, spec, bow=0.0):
        key = (spec["kind"], round(spec["t"], 3), round(spec["d"], 3), round(spec["h"], 3), round(bow, 3))
        if key not in self.meshes:
            mesh = _book_mesh(f"book_{spec['kind']}_{len(self.meshes):03d}", spec["kind"], *key[1:])
            mesh.materials.append(self.mats["cover"])
            mesh.materials.append(self.mats["pages"] if KINDS[spec["kind"]]["pages"] else self.mats["cover"])
            if spec["kind"] == "binder":
                mesh.materials[1] = self.m["paper"]
            self.meshes[key] = mesh
        return self.meshes[key]

    def book(self, spec, local, bow=0.0):
        self.count += 1
        obj = bpy.data.objects.new(f"{self.prefix}_book_{self.count:03d}", self.mesh(spec, bow))
        obj.color = (*spec["colour"], 1.0)
        obj["bk"] = (float(spec["style"]), spec["finish"], spec["seed"])
        obj["dims"] = (spec["t"], spec["h"], spec["d"])
        obj["ink"] = spec["ink"]
        obj["alt"] = spec["alt"]
        self.books_col.objects.link(obj)
        obj.matrix_world = self.M @ local
        return obj

    def prop(self, kind, local=None, place=None):
        """Build a small object; place(w, d) -> local matrix, once its size is known."""
        self.count += 1
        b = Builder()
        w, d = PROPS[kind](b, self.m, self.mats, self.rng)
        local = local if place is None else place(w, d)
        if local is None:
            b.bm.free()
            return None
        obj = b.build(f"{self.prefix}_{kind}_{self.count:03d}", self.props_col)
        obj.matrix_world = self.M @ local
        return w, d


class Compartment:
    """One shelf space between two boards, filled left to right."""

    def __init__(self, s, x0, x1, z0, z1, depth, sag, recipe):
        self.s, self.rng = s, s.rng
        self.x0, self.x1, self.z0, self.z1, self.depth, self.sag = x0, x1, z0, z1, depth, sag
        names = recipe.split("+")
        self.recipe = RECIPES[names[0]]
        self.extras = names[1:]
        self.back = 0.07 if "jars" in self.extras else 0.0  # books pushed back behind a row of jars

    def zb(self, x):
        """Top of the (sagging) board at x."""
        c, half = (self.x0 + self.x1) / 2, (self.x1 - self.x0) / 2
        return self.z0 - self.sag * (1 - ((x - c) / half) ** 2)

    @property
    def hmax(self):
        return self.z1 - self.z0

    def y_front(self, d, inset):
        y = -self.depth / 2 + self.back + inset
        return min(y, self.depth / 2 - d - 0.003)

    def fill(self):
        rng = self.rng
        x, x1 = self.x0 + 0.002, self.x1 - 0.002
        if "printer" in self.extras:
            x1 -= 0.46
            self.s.prop("printer", T((x1 + 0.23, -self.depth / 2 + 0.17, self.zb(x1 + 0.23))))
        if "laptop" in self.extras:
            self.s.prop("laptop", T((x + 0.17, -self.depth / 2 + 0.14, self.zb(x + 0.17))))
            x += 0.36
        if "clock" in self.extras:
            x = self.objects(x, x1, first="clock")
        if "camera" in self.extras:
            x = self.objects(x, x1, first="slr")
        r = self.recipe
        kinds = {"run": r["run"], "stack": r["stack"], "gap": r["gap"], "objects": r["objects"], "files": r["files"]}
        last = None
        while x < x1 - 0.03:
            kind = _weighted(rng, kinds)
            if kind == last and kind in ("gap", "objects"):
                continue
            x = getattr(self, kind)(x, x1)
            last = kind
        if "jars" in self.extras:
            self.jars()

    # --- segments: each takes the free span [x, x1] and returns the new x

    def gap(self, x, x1):
        return x + self.rng.uniform(0.03, 0.1)

    def run(self, x, x1):
        rng = self.rng
        fam = _weighted(rng, {k: v for k, v in UPRIGHT.items() if FAMILIES[k]["h"][0] < self.hmax - 0.01})
        series = rng.random() < 0.25
        inset = rng.choice((rng.uniform(0.002, 0.02), rng.uniform(0.02, 0.07)))
        placed, prev = [], None
        for i in range(rng.randint(8, 40)):
            if series and i > rng.randint(3, 9):
                series = False
            if rng.random() < 0.2 and not series:
                fam = _weighted(rng, {k: v for k, v in UPRIGHT.items() if FAMILIES[k]["h"][0] < self.hmax - 0.01})
            spec = book_spec(rng, fam, self.hmax, like=prev if series else None)
            if spec is None:
                continue
            if x + spec["t"] > x1:
                break
            jitter = rng.random()
            dy = (rng.gauss(0, 0.004) if jitter < 0.7 else rng.uniform(0.01, 0.05) if jitter < 0.88
                  else -rng.uniform(0.005, 0.02))
            y = max(self.y_front(spec["d"], inset + dy), -self.depth / 2 - 0.012)
            bow = rng.uniform(0.002, 0.006) * rng.choice((-1, 1)) if spec["t"] < 0.02 and rng.random() < 0.06 else 0.0
            xc = x + spec["t"] / 2
            self.s.book(spec, T((xc, y + spec["d"] / 2, self.zb(xc))) @ R(rng.gauss(0, 0.006), "Z"), bow)
            placed.append((x, spec))
            prev = spec
            x += spec["t"] + rng.uniform(0.0, 0.0015)
        if not placed:
            return x + 0.02
        if rng.random() < self.recipe["top"]:
            self.top_stack(placed)
        if rng.random() < self.recipe["lean"] and x1 - x > 0.06:
            x = self.lean(x, x1, placed[-1][1])
        return x

    def lean(self, x, x1, against):
        """1-3 books leaning left onto the end of a run."""
        rng = self.rng
        a = math.radians(rng.uniform(8, 28))
        xn, hn = x, against["h"]
        for i in range(rng.randint(1, 3)):
            fam = _weighted(rng, {k: v for k, v in UPRIGHT.items() if FAMILIES[k]["h"][0] < self.hmax - 0.01})
            spec = book_spec(rng, fam, self.hmax)
            if spec is None:
                break
            t, h = spec["t"], spec["h"]
            if i == 0:
                xq = xn + (hn * math.tan(a) if hn / math.cos(a) <= h else h * math.sin(a))
            else:
                xq = xn + 0.0005
            right = xq + t * math.cos(a)
            if right > x1 or h * math.cos(a) + t * math.sin(a) > self.hmax - 0.005:
                break
            bow = rng.uniform(0.002, 0.008) if t < 0.015 and rng.random() < 0.4 else 0.0
            y = self.y_front(spec["d"], rng.uniform(0.005, 0.03))
            loc = (xq + t / 2 * math.cos(a), y + spec["d"] / 2, self.zb(xq) + t / 2 * math.sin(a))
            self.s.book(spec, T(loc) @ R(-a, "Y"), bow)
            xn = xq + t / math.cos(a)
            x = right
        return x + rng.uniform(0.01, 0.05)

    def lying(self, spec, cx, z, yc, spin):
        """A book lying flat, spine to the front, centred at cx."""
        flip = math.pi / 2 if self.rng.random() < 0.5 else -math.pi / 2
        local = T((cx, yc, z + spec["t"] / 2)) @ R(spin, "Z") @ R(flip, "Y") @ T((0, 0, -spec["h"] / 2))
        self.s.book(spec, local)

    def stack_specs(self, width, height):
        rng = self.rng
        specs, total = [], 0.0
        series = rng.random() < 0.12
        fam = _weighted(rng, LYING)
        for _ in range(rng.randint(2, 14)):
            spec = book_spec(rng, fam if series else _weighted(rng, LYING), 1.0,
                             like=specs[-1] if series and specs else None)
            if spec["h"] > width or total + spec["t"] > height:
                continue
            specs.append(spec)
            total += spec["t"]
        return sorted(specs, key=lambda s: -s["h"] * s["d"])

    def stack(self, x, x1):
        rng = self.rng
        width = min(x1 - x - 0.01, 0.36)
        if width < 0.15:
            return x1
        specs = self.stack_specs(width, (self.hmax - 0.01) * rng.uniform(0.55, 0.97))
        if not specs:
            return x + 0.02
        w = max(s["h"] for s in specs)
        cx = x + w / 2 + 0.005
        z = self.zb(cx)
        for spec in specs:
            yc = self.y_front(spec["d"], rng.uniform(0.0, 0.03)) + spec["d"] / 2
            self.lying(spec, cx + rng.uniform(-0.01, 0.01), z, yc, rng.gauss(0, 0.04))
            z += spec["t"]
        if rng.random() < 0.15 and self.z1 - z > 0.08:
            self.s.prop("box", T((cx, -self.depth / 2 + 0.1, z)) @ R(rng.uniform(-0.3, 0.3), "Z"))
        return x + w + 0.012

    def top_stack(self, placed):
        """A few books lying across the tops of a run."""
        rng = self.rng
        x0 = placed[0][0]
        x_end = placed[-1][0] + placed[-1][1]["t"]
        top = max(self.zb(x0 + s["t"] / 2) + s["h"] for x0, s in placed)
        specs = self.stack_specs(x_end - x0 + 0.02, self.z1 - top - 0.006)
        if not specs:
            return
        cx = rng.uniform(x0 + max(s["h"] for s in specs) / 2, max(x0, x_end - max(s["h"] for s in specs) / 2))
        z = top
        for spec in specs[: rng.randint(1, 7)]:
            yc = self.y_front(spec["d"], rng.uniform(0.0, 0.03)) + spec["d"] / 2
            self.lying(spec, cx + rng.uniform(-0.015, 0.015), z, yc, rng.gauss(0, 0.05))
            z += spec["t"]

    def files(self, x, x1):
        """Binders, magazine files and the odd white box file."""
        rng = self.rng
        if self.hmax < 0.33:
            return self.run(x, x1)
        choice = rng.random()
        if choice < 0.45:
            spec = book_spec(rng, "binder", self.hmax)
            for _ in range(rng.randint(2, 6)):
                if x + spec["t"] > x1:
                    break
                y = self.y_front(spec["d"], rng.uniform(0.002, 0.012))
                self.s.book(dict(spec, seed=rng.random()), T((x + spec["t"] / 2, y + spec["d"] / 2, self.zb(x))))
                x += spec["t"] + 0.001
        elif choice < 0.8:
            mat = rng.choice(["plastic_black", "plastic_black", "plastic_white", "cardboard"])
            for _ in range(rng.randint(1, 4)):
                if x + 0.085 > x1:
                    break
                self.magazine_file(x + 0.04, mat)
                x += 0.083
        else:
            spec = book_spec(rng, "boxfile", self.hmax)
            if spec and x + spec["t"] <= x1:
                y = self.y_front(spec["d"], 0.004)
                self.s.book(spec, T((x + spec["t"] / 2, y + spec["d"] / 2, self.zb(x))))
                x += spec["t"] + 0.002
        return x + rng.uniform(0.0, 0.01)

    def magazine_file(self, cx, mat_name, t=0.08, d=0.24, h=0.31):
        """Open-backed magazine holder: tall at the front, sloping down to the back."""
        rng, m = self.rng, self.s.m
        b = Builder()
        mat = m[mat_name]
        wall = 0.002
        for sx in (-1, 1):
            _prism(b, mat, (sx * (t / 2 - wall / 2), wall), d, h, h * 0.45)
        b.box((t, wall, h), (0, -d / 2 + wall / 2, h / 2), mat)
        b.box((t, d, wall), (0, 0, wall / 2), mat)
        b.box((t, wall, h * 0.45), (0, d / 2 - wall / 2, h * 0.225), mat)
        b.box((t * 0.6, 0.001, 0.05), (0, -d / 2 - 0.0005, h - 0.06), m["paper"])
        y = self.y_front(d, rng.uniform(0.002, 0.012)) + d / 2
        z = self.zb(cx)
        self.s.count += 1
        obj = b.build(f"{self.s.prefix}_magfile_{self.s.count:03d}", self.s.props_col)
        obj.matrix_world = self.s.M @ T((cx, y, z))
        # magazines inside, leaning together
        lean = rng.uniform(0.05, 0.25) * rng.choice((-1, 1))
        xm = cx - t / 2 + 0.006
        for _ in range(rng.randint(3, 9)):
            spec = book_spec(rng, "magazine", h - 0.004)
            if spec is None or xm + spec["t"] > cx + t / 2 - 0.006:
                break
            spec["d"] = min(spec["d"], d - 0.01)
            self.s.book(spec, T((xm + spec["t"] / 2, y + 0.002, z + 0.004)) @ R(lean * 0.2, "Y"))
            xm += spec["t"]

    def objects(self, x, x1, first=None):
        rng = self.rng
        for i in range(rng.randint(1, 2)):
            kind = first if i == 0 and first else _weighted(rng, SHELF_PROPS)
            if self.s.used.get(kind, 0) >= LIMITS.get(kind, 99):
                kind = "box"
            self.s.used[kind] = self.s.used.get(kind, 0) + 1

            def place(w, d):
                if x + w + 0.01 > x1:
                    return None
                cx = x + w / 2 + 0.005
                y = -self.depth / 2 + max(d / 2 + 0.01, rng.uniform(0.04, 0.17))
                return T((cx, y, self.zb(cx))) @ R(rng.uniform(-0.25, 0.25), "Z")

            size = self.s.prop(kind, place=place)
            if size is None:
                break
            x += size[0] + rng.uniform(0.01, 0.04)
        return x

    def jars(self):
        rng = self.rng
        x = self.x0 + rng.uniform(0.01, 0.05)
        while x < self.x1 - 0.06:
            if rng.random() < 0.15:
                x += rng.uniform(0.04, 0.12)
                continue
            y = -self.depth / 2 + rng.uniform(0.025, 0.05)
            w, _ = self.s.prop("jar", place=lambda w, d: T((x + w / 2, y, self.zb(x + w / 2))))
            x += max(w, 0.03) + rng.uniform(0.0, 0.015)


def _prism(b, mat, xw, d, h, h_back):
    """Side wall of a magazine file: x = (centre, thickness); full height at the
    front (-y), sloping down to h_back at the back."""
    xc, w = xw
    poly = [(-d / 2, 0), (d / 2, 0), (d / 2, h_back), (-d / 2 + d * 0.3, h), (-d / 2, h)]
    bm = b.bm
    vs = [[bm.verts.new((xc + sx * w / 2, y, z)) for y, z in poly] for sx in (-1, 1)]
    n = len(poly)
    faces = [bm.faces.new(vs[0]), bm.faces.new(list(reversed(vs[1])))]
    for i in range(n):
        j = (i + 1) % n
        faces.append(bm.faces.new([vs[0][j], vs[0][i], vs[1][i], vs[1][j]]))
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    b._assign(vs[0] + vs[1], mat)


# ----------------------------------------------------------------------------
# The bookshelf
# ----------------------------------------------------------------------------


def _board(b, mat, size, center, sag, n=12):
    """Box subdivided along x whose middle sags by `sag`."""
    w, d, h = size
    cx, cy, cz = center
    bm = b.bm
    rings = []
    for i in range(n + 1):
        x = cx - w / 2 + w * i / n
        dz = -sag * (1 - (2 * (x - cx) / w) ** 2)
        rings.append([bm.verts.new((x, cy + sy * d / 2, cz + dz + sz * h / 2))
                      for sy, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
    faces = [bm.faces.new(rings[0]), bm.faces.new(list(reversed(rings[-1])))]
    for a, c in zip(rings[:-1], rings[1:]):
        for k in range(4):
            j = (k + 1) % 4
            faces.append(bm.faces.new([a[k], a[j], c[j], c[k]]))
    bmesh.ops.recalc_face_normals(bm, faces=faces)
    b._assign([v for r in rings for v in r], mat)


def bookshelf(m, mats, furn, props, name, loc, bays, shelves, layout, depth=0.34, rot_z=0.0, seed=1,
              board=0.025):
    """Open pine bookshelf (the wall shows behind), stocked per `layout`:
    layout[level][bay] is a recipe name (see RECIPES), with optional extras
    after '+': jars, printer, laptop, clock, camera.
    bays: bay widths (m). shelves: z of each board, bottom to top."""
    rng = random.Random(seed)
    books_col = collection("Books")
    total = sum(bays) + board * (len(bays) + 1)
    top = shelves[-1]
    M = T(loc) @ R(rot_z, "Z")
    s = Stocker(m, mats, books_col, props, M, rng, name)
    carcass = Builder()
    x = -total / 2
    carcass.box((board, depth, top + board), (x + board / 2, 0, (top + board) / 2), m["pine"])
    for bay_i, bay in enumerate(bays):
        x0, x1 = x + board, x + board + bay
        for lv, z in enumerate(shelves):
            loaded = 0 < lv < len(shelves) - 1
            sag = rng.uniform(0.003, 0.006) * bay if loaded else 0.0
            _board(carcass, m["pine"], (bay, depth, board), ((x0 + x1) / 2, 0, z + board / 2), sag)
            if lv < len(shelves) - 1:
                next_sag = rng.uniform(0.003, 0.006) * bay
                Compartment(s, x0, x1, z + board, shelves[lv + 1] - next_sag, depth, sag,
                            layout[lv][bay_i]).fill()
        carcass.box((board, depth, top + board), (x1 + board / 2, 0, (top + board) / 2), m["pine"])
        x = x1
    carcass.box((total - 2 * board, board, shelves[0]), (0, -depth / 2 + board / 2 + 0.01, shelves[0] / 2), m["pine"])
    return carcass.build(name, furn, loc, rot_z)


# ----------------------------------------------------------------------------
# On top of the shelf: a woven basket and storage boxes
# ----------------------------------------------------------------------------


def _rounded_rect(a, b, r, s):
    """Point and outward normal at arc length s round a rounded rectangle (half sizes a, b)."""
    ex, ey = 2 * (a - r), 2 * (b - r)
    quarter = math.pi * r / 2
    per = 2 * ex + 2 * ey + 4 * quarter
    s %= per
    corners = [(a - r, -(b - r)), (a - r, b - r), (-(a - r), b - r), (-(a - r), -(b - r))]
    # right side up, top side left, left side down, bottom side right; corner arcs between
    legs = [(ey, (a, -(b - r)), (0, 1), (1, 0)), (ex, (a - r, b), (-1, 0), (0, 1)),
            (ey, (-a, b - r), (0, -1), (-1, 0)), (ex, (-(a - r), -b), (1, 0), (0, -1))]
    for i, (length, start, direction, normal) in enumerate(legs):
        if s < length:
            return (start[0] + direction[0] * s, start[1] + direction[1] * s), normal
        s -= length
        if s < quarter:
            ang = i * math.pi / 2 + s / r
            cx, cy = corners[(i + 1) % 4]
            return (cx + r * math.cos(ang), cy + r * math.sin(ang)), (math.cos(ang), math.sin(ang))
        s -= quarter
    return (a, -(b - r)), (1, 0)


def _sweep(path, normals, ups, section, closed):
    """Tube along a path; section: (n, up) offsets of the cross-section corners."""
    path, normals, ups = (np.asarray(v, dtype=float) for v in (path, normals, ups))
    sec = np.asarray(section, dtype=float)
    k, n = len(sec), len(path)
    verts = (path[:, None, :] + normals[:, None, :] * sec[None, :, 0:1] + ups[:, None, :] * sec[None, :, 1:2])
    verts = verts.reshape(-1, 3)
    faces = []
    for i in range(n if closed else n - 1):
        i2 = (i + 1) % n
        for j in range(k):
            j2 = (j + 1) % k
            faces.append((i * k + j, i2 * k + j, i2 * k + j2, i * k + j2))
    if not closed:
        faces.append(tuple(range(k - 1, -1, -1)))
        faces.append(tuple((n - 1) * k + j for j in range(k)))
    return verts, faces


class _Mesh:
    def __init__(self):
        self.verts, self.faces, self.n = [], [], 0

    def add(self, verts, faces):
        self.verts.append(verts)
        self.faces.extend(tuple(i + self.n for i in f) for f in faces)
        self.n += len(verts)

    def build(self, name, mat):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(np.concatenate(self.verts).tolist(), [], self.faces)
        mesh.materials.append(mat)
        mesh.validate()
        mesh.shade_smooth()
        return mesh


def _ribbon(w, th):
    return [(-th / 2, -w / 2), (th / 2, -w / 2), (th / 2, w / 2), (-th / 2, w / 2)]


def _round(r, k=8):
    return [(r * math.cos(2 * math.pi * i / k), r * math.sin(2 * math.pi * i / k)) for i in range(k)]


def basket(mats, col, name, loc, size=(0.55, 0.32, 0.27), rot_z=0.0, seed=5):
    """Lidded picnic basket woven from cane: stakes, over-and-under weavers,
    a rolled rim, a woven lid and a wooden handle. Front faces local -Y."""
    rng = random.Random(seed)
    L, D, H = size
    a0, b0, r0 = L / 2 - 0.01, D / 2 - 0.01, 0.045
    flare = 0.02  # wider at the top
    pitch, spacing, amp = 0.0085, 0.022, 0.0016
    per = 2 * (2 * (a0 - r0) + 2 * (b0 - r0)) + 2 * math.pi * r0
    stakes = 2 * round(per / spacing / 2)
    rows = int((H - 0.03) / pitch)
    mm = _Mesh()

    def at(s, z):
        f = 1 + flare * z / H / min(a0, b0)
        (x, y), (nx, ny) = _rounded_rect(a0 * f, b0 * f, r0 * f, s * f)
        return (x, y, z), (nx, ny, 0.0)

    samples = stakes * 4
    for k in range(rows):
        z = 0.015 + (k + 0.5) * pitch
        pts, nrm = [], []
        for i in range(samples):
            s = per * i / samples
            p, n = at(s, z)
            off = amp * math.cos(math.pi * stakes * s / per + math.pi * k)
            pts.append((p[0] + n[0] * off, p[1] + n[1] * off, z + rng.gauss(0, 0.0002)))
            nrm.append(n)
        mm.add(*_sweep(pts, nrm, [(0, 0, 1)] * samples, _ribbon(pitch * 0.92, 0.0017), True))
    for j in range(stakes):
        s = per * j / stakes
        pts, nrm, ups = [], [], []
        for z in np.linspace(0.01, H - 0.008, 6):
            p, n = at(s, z)
            pts.append(p)
            nrm.append(n)
            ups.append((-n[1], n[0], 0.0))
        mm.add(*_sweep(pts, nrm, ups, _ribbon(0.004, 0.0024), False))
    for z, r in ((0.012, 0.007), (H - 0.004, 0.008)):
        pts, nrm = [], []
        for i in range(stakes * 2):
            p, n = at(per * i / (stakes * 2), z)
            pts.append(p)
            nrm.append(n)
        mm.add(*_sweep(pts, nrm, [(0, 0, 1)] * len(pts), _round(r), True))

    # lid: weavers along x over cross stakes, gently domed, with its own rim
    f = 1 + flare / min(a0, b0)
    la, lb, lr = a0 * f + 0.004, b0 * f + 0.004, r0 * f
    zl = H + 0.006
    lid_rows = int(2 * lb / pitch)
    for k in range(lid_rows):
        y = -lb + (k + 0.5) * 2 * lb / lid_rows
        dy = max(0.0, abs(y) - (lb - lr))
        xe = la - lr + math.sqrt(max(lr * lr - dy * dy, 0.0)) - 0.004
        xs = np.linspace(-xe, xe, max(4, int(2 * xe / spacing) * 4))
        pts = [(x, y, zl + 0.012 * (1 - (x / la) ** 2) * (1 - (y / lb) ** 2)
                + amp * math.cos(math.pi * (x + la) / spacing + math.pi * k)) for x in xs]
        mm.add(*_sweep(pts, [(0, 0, 1)] * len(pts), [(0, 1, 0)] * len(pts),
                       _ribbon(2 * lb / lid_rows * 0.92, 0.0017), False))
    pts, nrm = [], []
    lid_per = 2 * (2 * (la - lr) + 2 * (lb - lr)) + 2 * math.pi * lr
    for i in range(stakes * 2):
        (x, y), (nx, ny) = _rounded_rect(la, lb, lr, lid_per * i / (stakes * 2))
        pts.append((x, y, zl))
        nrm.append((nx, ny, 0.0))
    mm.add(*_sweep(pts, nrm, [(0, 0, 1)] * len(pts), _round(0.006), True))

    mesh = mm.build(name, mats["rattan"])
    obj = bpy.data.objects.new(name, mesh)
    col.objects.link(obj)
    obj.location = loc
    obj.rotation_euler = (0, 0, rot_z)
    return obj


def basket_handle(m, col, name, loc, length=0.42, height=0.035, rot_z=0.0):
    """Wooden bar handle on two posts, for the top of the basket."""
    b = Builder()
    b.cyl(0.01, length, (0, 0, height), m["oak"], rot=(0, math.pi / 2, 0), segments=16)
    for sx in (-1, 1):
        b.box((0.012, 0.02, height), (sx * (length / 2 - 0.04), 0, height / 2), m["oak"])
    return b.build(name, col, loc, rot_z)


def storage_box(m, col, name, loc, size, mat="cardboard", rot_z=0.0):
    """Lidded storage box."""
    w, d, h = size
    b = Builder()
    b.box((w, d, h - 0.02), (0, 0, (h - 0.02) / 2), m[mat])
    b.box((w + 0.006, d + 0.006, 0.035), (0, 0, h - 0.0175), m[mat])
    return b.build(name, col, loc, rot_z)
