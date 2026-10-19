"""Lived-in floor clutter: soft cardboard boxes, paper piles, bags, cases, and cables.

Everything is generated from code and seeded, so a build is repeatable. A pile
is one mesh object (its footprint feeds the floor plan); cables and loose sheets
go in their own collection so they stay off the minimap.

Parts are built from thick "surfaces": a (u, v) grid in [0, 1]^2 mapped through
a shape function, so sheets can curl, flaps bend and walls dent, with UVs for
labels and print. Conventions match lib.furniture: loc is the base of the
object, front faces -Y, rot_z turns it about Z.
"""

import math
import random

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector, noise

from . import assets
from .geo import Builder
from .materials import _new, _principled

# --------------------------------------------------------------------------- materials


def _cached(name, fn):
    return bpy.data.materials.get(name) or fn(name)


def _plain(name, color, rough, **extra):
    mat, g, bsdf = _new(name, color)
    n = g.noise(g.obj_coords(), 40.0, 3.0, 0.6)
    _principled(g, bsdf, color=color, rough=g.map(n, 0.3, 0.7, rough * 0.85, min(1.0, rough * 1.15)), **extra)
    return mat


def _uv(g):
    return g.node("ShaderNodeTexCoord").outputs["UV"]


def _label(name):
    """Blank shipping label: border, rows of abstract 'text' and a solid block. No codes."""
    mat, g, bsdf = _new(name, (0.9, 0.9, 0.88))
    u, v, _ = g.sep(_uv(g))
    rows = g.math("MULTIPLY", v, 11.0)
    row, rowf = g.math("FLOOR", rows), g.math("FRACT", rows)
    length, _ = g.white(g.vec(row, 3.1, 0.0))
    in_row = g.math("MULTIPLY", g.math("GREATER_THAN", rowf, 0.3), g.math("LESS_THAN", rowf, 0.72))
    in_len = g.math("MULTIPLY", g.math("GREATER_THAN", u, 0.08),
                    g.math("LESS_THAN", u, g.math("ADD", g.math("MULTIPLY", length, 0.55), 0.3)))
    rows_ok = g.math("MULTIPLY", g.math("GREATER_THAN", row, 0.5), g.math("LESS_THAN", row, 7.5))
    glyphs = g.math("GREATER_THAN", g.noise(g.vec(g.math("MULTIPLY", u, 90.0), row, 0.0), 1.0, 1.0), 0.42)
    text = g.math("MULTIPLY", g.math("MULTIPLY", in_row, in_len), g.math("MULTIPLY", rows_ok, glyphs))
    block = g.math("MULTIPLY", g.math("MULTIPLY", g.math("GREATER_THAN", u, 0.62), g.math("LESS_THAN", u, 0.9)),
                   g.math("MULTIPLY", g.math("GREATER_THAN", v, 0.74), g.math("LESS_THAN", v, 0.92)))
    edge = g.math("MINIMUM", g.math("MINIMUM", u, g.math("SUBTRACT", 1.0, u)),
                  g.math("MINIMUM", v, g.math("SUBTRACT", 1.0, v)))
    border = g.math("MULTIPLY", g.math("GREATER_THAN", edge, 0.03), g.math("LESS_THAN", edge, 0.045))
    rule = g.math("MULTIPLY", g.math("GREATER_THAN", v, 0.66), g.math("LESS_THAN", v, 0.675))
    ink = g.math("MAXIMUM", g.math("MAXIMUM", text, block), g.math("MAXIMUM", border, rule))
    col = g.mix(g.math("MULTIPLY", ink, 0.9), (0.86, 0.86, 0.83), (0.03, 0.03, 0.035))
    _principled(g, bsdf, color=col, rough=g.mixf(ink, 0.45, 0.6), coat=0.15)
    return mat


def _print(name):
    """Magazine and box-art print: a colour per island, a picture area and a masthead band."""
    mat, g, bsdf = _new(name, (0.5, 0.4, 0.3))
    _, rnd = g.attr("island_rand")
    u, v, _ = g.sep(_uv(g))
    ramp = g.node("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT"
    palette = [(0.75, 0.73, 0.68), (0.06, 0.06, 0.07), (0.55, 0.08, 0.06), (0.08, 0.16, 0.32),
               (0.80, 0.62, 0.12), (0.88, 0.87, 0.84), (0.15, 0.28, 0.22), (0.45, 0.42, 0.40)]
    els = ramp.color_ramp.elements
    els[0].color = (*palette[0], 1)
    els[1].position, els[1].color = 1 / len(palette), (*palette[1], 1)
    for i, c in enumerate(palette[2:], 2):
        e = els.new(i / len(palette))
        e.color = (*c, 1)
    g.set(ramp.inputs["Fac"], rnd)
    base = ramp.outputs["Color"]
    seed = g.math("MULTIPLY", rnd, 97.0)
    pic = g.node("ShaderNodeTexNoise")
    g.set(pic.inputs["Vector"], g.vec(g.math("ADD", u, seed), v, seed))
    g.set(pic.inputs["Scale"], 3.0)
    g.set(pic.inputs["Detail"], 4.0)
    picture = g.mix(0.55, g.hsv(pic.outputs["Color"], 0.5, 0.3, 0.5), base, "MULTIPLY")
    split = g.math("ADD", 0.55, g.math("MULTIPLY", g.math("FRACT", g.math("MULTIPLY", rnd, 13.7)), 0.25))
    in_pic = g.math("MULTIPLY", g.math("LESS_THAN", v, split),
                    g.math("MULTIPLY", g.math("GREATER_THAN", u, 0.06), g.math("LESS_THAN", u, 0.94)))
    in_pic = g.math("MULTIPLY", in_pic, g.math("GREATER_THAN", v, 0.05))
    bars = g.math("GREATER_THAN", g.noise(g.vec(g.math("MULTIPLY", u, 6.0), g.math("MULTIPLY", v, 30.0), seed), 1.0, 1.0), 0.6)
    mast = g.math("MULTIPLY", g.math("GREATER_THAN", v, g.math("ADD", split, 0.08)), bars)
    col = g.mix(g.math("MULTIPLY", in_pic, 0.85), base, picture)
    col = g.mix(g.math("MULTIPLY", mast, 0.8), col, (0.9, 0.9, 0.88))
    _principled(g, bsdf, color=col, rough=0.3, coat=0.25, coat_rough=0.15)
    return mat


def _bag_paper(name, color):
    mat, g, bsdf = _new(name, color)
    p = g.obj_coords()
    fib = g.noise(p, 200.0, 3.0, 0.6)
    blot = g.noise(p, 6.0, 3.0, 0.6)
    col = g.mix(g.map(blot, 0.35, 0.7, 0.0, 0.25), color, tuple(c * 0.8 for c in color))
    _principled(g, bsdf, color=col, rough=0.62, sheen=0.2, normal=g.bump(fib, 0.06, 0.0005))
    return mat


def _poly_bag(name):
    mat, g, bsdf = _new(name, (0.85, 0.85, 0.83))
    p = g.obj_coords()
    crinkle = g.noise(p, 70.0, 4.0, 0.7, 0.5)
    _principled(g, bsdf, color=(0.82, 0.82, 0.8), rough=g.map(crinkle, 0.3, 0.7, 0.18, 0.4),
                sss=0.3, sss_radius=(0.03, 0.03, 0.03), normal=g.bump(crinkle, 0.25, 0.002))
    return mat


def _tape(name):
    mat, g, bsdf = _new(name, (0.62, 0.47, 0.28))
    p = g.obj_coords()
    wrinkle = g.noise(g.scale(p, (1.0, 1.0, 1.0)), 90.0, 3.0, 0.6)
    _principled(g, bsdf, color=(0.6, 0.46, 0.27), rough=g.map(wrinkle, 0.3, 0.7, 0.12, 0.3), coat=0.4,
                coat_rough=0.08, normal=g.bump(wrinkle, 0.08, 0.0008))
    return mat


def library():
    """Clutter materials, plus the shared ones they sit next to."""
    from .materials import library as shared
    m = shared()
    m.update({
        "label": _cached("clutter_label", _label),
        "print": _cached("clutter_print", _print),
        "tape": _cached("clutter_tape", _tape),
        "bag_white": _cached("clutter_bag_white", lambda n: _bag_paper(n, (0.8, 0.79, 0.76))),
        "bag_grey": _cached("clutter_bag_grey", lambda n: _bag_paper(n, (0.16, 0.16, 0.16))),
        "bag_kraft": _cached("clutter_bag_kraft", lambda n: _bag_paper(n, (0.42, 0.28, 0.15))),
        "poly_bag": _cached("clutter_poly_bag", _poly_bag),
        "cable_black": _cached("clutter_cable_black", lambda n: _plain(n, (0.012, 0.012, 0.013), 0.42)),
        "cable_white": _cached("clutter_cable_white", lambda n: _plain(n, (0.72, 0.72, 0.7), 0.35)),
        "cable_grey": _cached("clutter_cable_grey", lambda n: _plain(n, (0.22, 0.22, 0.23), 0.4)),
        "rubber": _cached("clutter_rubber", lambda n: _plain(n, (0.02, 0.02, 0.02), 0.75)),
        "case_shell": _cached("clutter_case_shell", lambda n: _plain(n, (0.025, 0.025, 0.027), 0.55)),
        "dvd": _cached("clutter_dvd", lambda n: _plain(n, (0.012, 0.012, 0.014), 0.2, coat=0.3)),
    })
    return m


# --------------------------------------------------------------------------- mesh building


def frame(loc=(0, 0, 0), rot=(0, 0, 0)):
    return Matrix.Translation(loc) @ Euler(rot).to_matrix().to_4x4()


def breaks(n, *extra):
    return sorted({round(i / n, 6) for i in range(n + 1)} | {round(e, 6) for e in extra if 0 < e < 1})


def flat(w, l):
    return lambda u, v: ((u - 0.5) * w, (v - 0.5) * l, 0.0)


class Pile(Builder):
    """Builder with soft parts: thick surfaces, lumps and tubes."""

    def __init__(self, m, rng=None):
        super().__init__()
        self.m = m
        self.rng = rng or random.Random(0)
        self.uv = self.bm.loops.layers.uv.verify()

    def index(self, mat):
        if mat not in self.mats:
            self.mats.append(mat)
        return self.mats.index(mat)

    def _face(self, verts, mat, uvs=None):
        f = self.bm.faces.new(verts)
        f.material_index = self.index(mat)
        if uvs:
            for loop, uv in zip(f.loops, uvs):
                loop[self.uv].uv = uv
        return f

    def surface(self, m, shape, us, vs, t, mat, paint=None, rim=None):
        """Thick sheet over shape(u, v) -> local point, placed by matrix m.
        paint(u, v) -> material, or (material, (u0, v0, u1, v1)) to give that cell
        UVs local to the rectangle (labels). rim is the edge material."""
        eps = 1e-3

        def pt(u, v):
            return Vector(shape(u, v))

        grid = {}
        for i, u in enumerate(us):
            for j, v in enumerate(vs):
                p = pt(u, v)
                du = pt(min(u + eps, 1), v) - pt(max(u - eps, 0), v)
                dv = pt(u, min(v + eps, 1)) - pt(u, max(v - eps, 0))
                n = du.cross(dv).normalized() * (t / 2)
                grid[i, j] = (self.bm.verts.new(m @ (p + n)), self.bm.verts.new(m @ (p - n)))
        for i in range(len(us) - 1):
            for j in range(len(vs) - 1):
                q = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
                uvs = [(us[a], vs[b]) for a, b in q]
                cell = (paint((us[i] + us[i + 1]) / 2, (vs[j] + vs[j + 1]) / 2) if paint else None) or mat
                if isinstance(cell, tuple):
                    cell, (u0, v0, u1, v1) = cell
                    uvs = [((uu - u0) / (u1 - u0), (vv - v0) / (v1 - v0)) for uu, vv in uvs]
                self._face([grid[k][0] for k in q], cell, uvs)
                self._face([grid[k][1] for k in reversed(q)], cell, list(reversed(uvs)))
        nu, nv = len(us) - 1, len(vs) - 1
        ring = ([(i, 0) for i in range(nu)] + [(nu, j) for j in range(nv)]
                + [(i, nv) for i in range(nu, 0, -1)] + [(0, j) for j in range(nv, 0, -1)])
        for a, b in zip(ring, ring[1:] + ring[:1]):
            self._face([grid[a][0], grid[a][1], grid[b][1], grid[b][0]], rim or mat)

    def lump(self, size, center, mat, seed, folds=0.25, crumple=0.0, rings=16, segs=32, squash=0.0):
        """Soft heap (bags, jackets, crumpled paper): a flat-bottomed blob with
        folds (soft ridges) and crumple (sharp creases)."""
        res = bmesh.ops.create_uvsphere(self.bm, u_segments=segs, v_segments=rings, radius=0.5)
        verts = res["verts"]
        off = Vector((seed * 7.1, seed * 3.3, seed * 1.7))
        axis = Vector((math.cos(seed), math.sin(seed), 0.3)).normalized()
        sx, sy, sz = size
        for v in verts:
            n = v.co.normalized()
            d = noise.noise(n * 1.3 + off) * 0.35 + noise.noise(n * 3.5 + off) * 0.12
            d += folds * abs(math.sin(n.dot(axis) * 9.0 + noise.noise(n * 2 + off) * 3)) * 0.25
            d -= crumple * abs(noise.noise(n * 6.0 + off)) * 0.5
            p = n * 0.5 * (1 + d)
            z = p.z * sz + sz * 0.42
            z = max(z, 0.0)
            v.co = Vector((p.x * sx * (1 + squash * (0.42 - p.z)), p.y * sy * (1 + squash * (0.42 - p.z)), z))
            v.co += Vector(center)
        self._assign(verts, mat)
        return verts

    def tube(self, pts, r, mat, sides=8, flatten=1.0):
        pts = [Vector(p) for p in pts]
        rings = []
        for i, p in enumerate(pts):
            t = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
            side = t.cross(Vector((0, 0, 1)))
            if side.length < 1e-3:
                side = t.cross(Vector((1, 0, 0)))
            side.normalize()
            up = side.cross(t)
            ring = []
            for k in range(sides):
                a = 2 * math.pi * k / sides
                ring.append(self.bm.verts.new(p + side * math.cos(a) * r + up * math.sin(a) * r * flatten))
            rings.append(ring)
        for r0, r1 in zip(rings, rings[1:]):
            for k in range(sides):
                self._face([r0[k], r0[(k + 1) % sides], r1[(k + 1) % sides], r1[k]], mat)
        self._face(list(reversed(rings[0])), mat)
        self._face(rings[-1], mat)

    def build(self, name, col, location=(0, 0, 0), rot_z=0.0, bevel=0.0015):
        obj = super().build(name, col, location, rot_z)
        obj.data.shade_smooth()
        obj.data.set_sharp_from_angle(angle=math.radians(35))
        if bevel:
            mod = obj.modifiers.new("bevel", "BEVEL")
            mod.width = bevel
            mod.segments = 2
            mod.limit_method = "ANGLE"
            mod.angle_limit = math.radians(40)
            mod.use_clamp_overlap = True
        return obj


# --------------------------------------------------------------------------- parts


def _bend(a0, curl, s):
    """Point at arc length s along a strip leaving at angle a0 and curving by curl (rad/m)."""
    if abs(curl) < 1e-4:
        return s * math.cos(a0), s * math.sin(a0)
    a = a0 + curl * s
    return (math.sin(a) - math.sin(a0)) / curl, (math.cos(a0) - math.cos(a)) / curl


def _dents(rng, amp):
    """A dent field over a wall: outward bulge, a couple of knocks, fine crumple."""
    off = Vector((rng.uniform(0, 99), rng.uniform(0, 99), 0))
    knocks = [(rng.uniform(0.15, 0.85), rng.uniform(0.1, 0.7), rng.uniform(0.08, 0.2), rng.uniform(0.3, 1.0))
              for _ in range(rng.randint(0, 2))]

    def f(u, v):
        s = math.sin(math.pi * u) * math.sin(math.pi * min(v, 1))
        d = -0.4 * s + 0.35 * noise.noise(Vector((u * 3, v * 3, 0)) + off) * s
        for ku, kv, kr, kd in knocks:
            d += kd * math.exp(-((u - ku) ** 2 + (v - kv) ** 2) / (kr * kr))
        return d * amp
    return f


def carton(b, size, center=(0, 0, 0), rot_z=0.0, flaps=None, tape=True, label=True, dent=0.013,
           mat=None, stuffing=True):
    """Open corrugated box: dented walls, bent flaps, tape and a blank label.
    flaps: (angle from horizontal-outward, curl) per wall front/right/back/left;
    None picks a random messy set."""
    rng = b.rng
    m = b.m
    mat = mat or m["cardboard"]
    w, d, h = size
    t = 0.0045
    base = frame(center, (0, 0, rot_z))
    b.surface(base @ frame((0, 0, t / 2)), flat(w - t, d - t), breaks(2), breaks(2), t, mat)
    flaps = flaps or [(rng.choice([-1.25, -0.6, 0.3, 0.9, 1.3]) + rng.uniform(-0.2, 0.2), rng.uniform(-2.5, 1.0))
                      for _ in range(4)]
    tw = 0.05
    for k, (length, off) in enumerate([(w, d / 2), (d, w / 2), (w, d / 2), (d, w / 2)]):
        wall = base @ frame((0, 0, 0), (0, 0, k * math.pi / 2)) @ frame((0, -off, 0))
        dents = _dents(rng, dent)
        tu0, tu1 = 0.5 - tw / 2 / length, 0.5 + tw / 2 / length
        tv0 = 1 - 0.09 / h
        lab = (0.55, 0.22, 0.88, 0.22 + 0.2 * length / h * 0.33 / 0.6) if label and k == 0 else None

        def paint(u, v, k=k, tu0=tu0, tu1=tu1, tv0=tv0, lab=lab):
            if tape and k in (0, 2) and tu0 < u < tu1 and v > tv0:
                return m["tape"]
            if lab and lab[0] < u < lab[2] and lab[1] < v < lab[3]:
                return m["label"], lab
            return None

        us = breaks(8, tu0, tu1, *(lab[0::2] if lab else ()))
        vs = breaks(6, tv0, *(lab[1::2] if lab else ()))
        b.surface(wall, lambda u, v, L=length, f=dents: ((u - 0.5) * L, f(u, v), v * h), us, vs, t, mat, paint)
        # flap hinged on the wall's top edge, outward = -Y
        a0, curl = flaps[k]
        flen = min(w, d) / 2 - 0.004
        fw = length - 0.01
        crease = rng.uniform(0.3, 0.7)
        kink = rng.uniform(-0.25, 0.25)

        def flap(u, s, a0=a0, curl=curl, fw=fw, flen=flen, crease=crease, kink=kink, f=dents):
            ang = a0 + kink * min(1, (s - crease) * 8) if s > crease else a0
            y, z = _bend(ang, curl, s * flen)
            return ((u - 0.5) * fw * (1 - 0.04 * s), -y + f(u, 1.0) * 0.5, h + z)

        tape_flap = (lambda u, v: m["tape"] if tu0 < u < tu1 and v < 0.35 else None) if tape and k in (0, 2) else None
        b.surface(wall, flap, breaks(8, tu0, tu1), breaks(6, 0.35), t * 0.9, mat, tape_flap)
    if stuffing:
        # whatever is packed inside, then crumpled packing paper on top of it
        fill = h * rng.uniform(0.45, 0.65)
        placed_box(b, (w - 3 * t, d - 3 * t, fill), base @ Vector((0, 0, fill / 2)), m["cardboard"], (0, 0, rot_z))
        for i in range(rng.randint(2, 4)):
            sz = (w * rng.uniform(0.3, 0.45), d * rng.uniform(0.3, 0.5), rng.uniform(0.07, 0.12))
            c = base @ Vector((rng.uniform(-0.22, 0.22) * w, rng.uniform(-0.2, 0.2) * d, fill))
            b.lump(sz, c, m["paper"] if i % 3 else m["poly_bag"], rng.uniform(0, 50), folds=0.3, crumple=0.7)


def paper_bag(b, size, center, rot_z=0.0, mat=None, tilt=0.0, handles=True):
    """Carrier bag: crumpled walls with the gussets folded in, rope handles."""
    rng = b.rng
    m = b.m
    mat = mat or m["bag_white"]
    w, d, h = size
    t = 0.0012
    base = frame(center, (tilt, 0, rot_z))
    b.surface(base @ frame((0, 0, t)), flat(w, d), breaks(2), breaks(2), t, mat)
    off = Vector((rng.uniform(0, 99), rng.uniform(0, 99), 0))
    slump = rng.uniform(0.0, 0.25)
    for k, (length, half) in enumerate([(w, d / 2), (d, w / 2), (w, d / 2), (d, w / 2)]):
        wall = base @ frame((0, 0, 0), (0, 0, k * math.pi / 2)) @ frame((0, -half, 0))
        gusset = k % 2

        def shape(u, v, L=length, k=k, g=gusset):
            crumple = noise.noise(Vector((u * 4 + k * 9, v * 4, 0)) + off) * 0.012 * v
            crumple += noise.noise(Vector((u * 11 + k * 9, v * 11, 3)) + off) * 0.004
            fold = (1 - abs(2 * u - 1)) * L * 0.35 * v ** 0.7 if g else 0.0
            sag = slump * v * v * h * 0.5
            return ((u - 0.5) * L, crumple + fold + sag * 0.3, v * h * (1 - slump * 0.3 * v))

        b.surface(wall, shape, breaks(6), breaks(8), t, mat)
    if handles:
        for side in (-1, 1):
            y = side * (d / 2 + 0.004)
            lean = rng.uniform(-0.6, 0.6)
            pts = []
            for i in range(9):
                a = math.pi * i / 8
                hz = h * (1 - slump * 0.3) + math.sin(a) * 0.09
                pts.append(base @ Vector((-math.cos(a) * w * 0.18, y + side * math.sin(a) * 0.09 * lean, hz)))
            b.tube(pts, 0.003, m["bag_grey"] if mat is m["bag_white"] else m["bag_white"], sides=6)


def sheet_shape(w, l, curl=0.03, corner=0.01, seed=0.0):
    """A paper sheet lying flat: ends curl up, one corner lifts, a gentle ripple (never below z=0)."""
    off = Vector((seed, seed * 0.7, 0))

    def f(u, v):
        x, y = (u - 0.5) * w, (v - 0.5) * l
        z = curl * (2 * v - 1) ** 4 + corner * max(0, (u + v - 1.4)) ** 2 / 0.36
        z += 0.0015 * (1 + noise.noise(Vector((u * 2, v * 2, 0)) + off))
        return x, y, z
    return f


def paper_pile(b, size, center, rot_z=0.0, mags=0.4, mess=1.0):
    """A pile of paper and magazines: thin slabs, each a bit off square, curled top sheets."""
    rng = b.rng
    m = b.m
    w, d, h = size
    z = 0.0
    while z < h:
        mag = rng.random() < mags
        t = rng.uniform(0.004, 0.009) if mag else rng.uniform(0.0015, 0.012)
        sw, sd = (0.21, 0.28) if mag else (0.21, 0.297)
        if rng.random() < 0.3:
            sw, sd = sw * 1.1, sd * 1.2
        sw, sd = min(sw, w), min(sd, d)
        cx = rng.uniform(-1, 1) * max(0.0, w - sw) / 2 + rng.uniform(-0.02, 0.02) * mess
        cy = rng.uniform(-1, 1) * max(0.0, d - sd) / 2 + rng.uniform(-0.02, 0.02) * mess
        base = frame((center[0], center[1], center[2] + z + t / 2), (0, 0, rot_z))
        mm = base @ frame((cx, cy, 0), (rng.uniform(-0.03, 0.03), rng.uniform(-0.03, 0.03), rng.uniform(-0.25, 0.25) * mess))
        shape = sheet_shape(sw, sd, rng.uniform(0, 0.006), rng.uniform(0, 0.006), rng.uniform(0, 50))
        if mag:
            b.surface(mm, shape, breaks(3), breaks(4), t, m["print"], rim=m["paper"])
        else:
            b.surface(mm, shape, breaks(3), breaks(4), t, m["paper"])
        z += t * 0.92
    for i in range(rng.randint(1, 3)):
        mm = frame((center[0], center[1], center[2] + z + 0.001), (0, 0, rot_z + rng.uniform(-0.6, 0.6)))
        mm = mm @ frame((rng.uniform(-0.04, 0.04), rng.uniform(-0.04, 0.04), 0))
        b.surface(mm, sheet_shape(0.21, 0.297, rng.uniform(0.01, 0.03), rng.uniform(0.0, 0.04), rng.uniform(0, 50)),
                breaks(5), breaks(8), 0.0004, m["paper"])
        z += 0.002
    return z


def case(b, size, center, rot_z=0.0, mat=None, handle=True, tilt=(0.0, 0.0)):
    """Black hard case: shell, lid seam, latches and a handle."""
    m = b.m
    mat = mat or m["case_shell"]
    w, d, h = size
    mm = frame(center, (tilt[0], tilt[1], rot_z))
    for part, c, mt in [((w, d, h), (0, 0, h / 2), mat),
                        ((w + 0.006, d + 0.006, 0.012), (0, 0, h * 0.62), mat)]:
        verts_before = len(b.bm.verts)
        b.box(part, c, mt)
        b.bm.verts.ensure_lookup_table()
        bmesh.ops.transform(b.bm, matrix=mm, verts=b.bm.verts[verts_before:])
    if handle:
        pts = [mm @ Vector((x, 0, h + 0.004 + 0.022 * math.sin(math.pi * (x + 0.06) / 0.12)))
               for x in [i * 0.015 - 0.06 for i in range(9)]]
        b.tube(pts, 0.007, m["rubber"], sides=8, flatten=0.8)
        for sx in (-1, 1):
            n0 = len(b.bm.verts)
            b.box((0.035, 0.012, 0.03), (sx * w * 0.3, -d / 2 - 0.006, h * 0.62), m["plastic_black_satin"])
            b.bm.verts.ensure_lookup_table()
            bmesh.ops.transform(b.bm, matrix=mm, verts=b.bm.verts[n0:])


def placed_box(b, size, center, mat, rot=(0, 0, 0)):
    n0 = len(b.bm.verts)
    b.box(size, (0, 0, 0), mat)
    b.bm.verts.ensure_lookup_table()
    bmesh.ops.transform(b.bm, matrix=frame(center, rot), verts=b.bm.verts[n0:])


def disc_stack(b, center, n, rot_z=0.0, dvd=True):
    """CD/DVD cases, stacked a bit untidily."""
    rng = b.rng
    m = b.m
    z = center[2]
    for i in range(n):
        size = (0.135, 0.19, 0.014) if dvd or rng.random() < 0.5 else (0.142, 0.125, 0.0104)
        mat = m["dvd"] if rng.random() < 0.75 else m["plastic_black_satin"]
        placed_box(b, size, (center[0] + rng.uniform(-0.012, 0.012), center[1] + rng.uniform(-0.012, 0.012),
                             z + size[2] / 2), mat, (0, 0, rot_z + rng.uniform(-0.12, 0.12)))
        z += size[2]
    return z


def printer(b, center, rot_z=0.0, size=(0.42, 0.3, 0.16)):
    """White desktop printer: body, lid seam, paper slot and an output tray."""
    m = b.m
    w, d, h = size
    mm = frame(center, (0, 0, rot_z))
    parts = [((w, d, h * 0.82), (0, 0, h * 0.41), m["plastic_white"]),
             ((w - 0.02, d - 0.03, h * 0.16), (0, 0.01, h * 0.9), m["plastic_white"]),
             ((w * 0.7, 0.004, 0.012), (0, -d / 2 - 0.001, h * 0.55), m["plastic_black"]),
             ((0.06, 0.004, 0.02), (w * 0.36, -d / 2 - 0.001, h * 0.7), m["plastic_black_satin"]),
             ((w * 0.62, 0.14, 0.004), (0, -d / 2 - 0.06, h * 0.32), m["plastic_white"]),
             ((w * 0.6, 0.1, 0.006), (0, d / 2 + 0.03, h * 0.98), m["plastic_white"])]
    for size_, c, mt in parts:
        placed_box(b, size_, mm @ Vector(c), mt, (0.0, 0, rot_z))
    # a sheet waiting in the rear tray
    b.surface(mm @ frame((0, d / 2 + 0.05, h * 1.05), (-1.1, 0, 0)),
            sheet_shape(0.21, 0.2, 0.0, 0.0, 3.0), breaks(2), breaks(3), 0.0004, m["paper"])


def scanner(b, center, rot_z=0.0, size=(0.3, 0.44, 0.07), lid=0.05):
    m = b.m
    w, d, h = size
    mm = frame(center, (0, 0, rot_z))
    placed_box(b, (w, d, h * 0.75), mm @ Vector((0, 0, h * 0.375)), m["plastic_white"], (0, 0, rot_z))
    hinge = mm @ frame((0, d / 2 - 0.01, h * 0.78), (lid, 0, 0))
    n0 = len(b.bm.verts)
    b.box((w - 0.004, d - 0.02, h * 0.2), (0, -(d - 0.02) / 2, h * 0.1), m["plastic_white"])
    b.bm.verts.ensure_lookup_table()
    bmesh.ops.transform(b.bm, matrix=hinge, verts=b.bm.verts[n0:])
    placed_box(b, (w * 0.9, 0.004, 0.006), mm @ Vector((0, -d / 2 - 0.001, h * 0.6)), m["plastic_black"],
               (0, 0, rot_z))


def jacket_heap(b, center, size=(0.5, 0.4, 0.16), rot_z=0.0, mat=None):
    """Black jacket or bag in a heap: two lumps and a sleeve trailing out."""
    rng = b.rng
    m = b.m
    mat = mat or m["fabric_black"]
    w, d, h = size
    mm = frame(center, (0, 0, rot_z))
    b.lump((w, d, h), mm @ Vector((0, 0, 0)), mat, rng.uniform(0, 50), folds=0.5, squash=0.3)
    b.lump((w * 0.6, d * 0.6, h * 0.8), mm @ Vector((w * 0.25, -d * 0.1, h * 0.3)), mat, rng.uniform(0, 50),
           folds=0.6)
    pts, a = [], rng.uniform(-0.5, 0.5)
    for i in range(10):
        s = i / 9
        a += rng.uniform(-0.3, 0.3)
        p = Vector((-w * 0.35 - s * 0.35 * math.cos(a), s * 0.35 * math.sin(a), 0.04 + h * 0.5 * (1 - s) ** 2))
        pts.append(mm @ p)
    b.tube(pts, 0.045, mat, sides=10, flatten=0.55)


# --------------------------------------------------------------------------- cables


def _catmull(pts, per=8):
    pts = [Vector(p) for p in pts]
    pts = [pts[0] * 2 - pts[1]] + pts + [pts[-1] * 2 - pts[-2]]
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        n = max(2, int(per * (p2 - p1).length / 0.1) + 1)
        for k in range(n):
            t = k / n
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(pts[-2])
    return out


def cable(col, name, pts, mat, radius=0.0035, wiggle=0.025, seed=0.0, lift=0.0):
    """A cable through control points; where it lies on the floor it meanders a
    little and rests on the boards (z = radius + lift)."""
    path = _catmull(pts)
    off = Vector((seed * 3.7, seed * 1.3, 0))
    out, s = [], 0.0
    for i, p in enumerate(path):
        if i:
            s += (p - path[i - 1]).length
        if p.z < 0.05:
            t = (path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]).normalized()
            side = Vector((-t.y, t.x, 0))
            if side.length > 1e-3:
                side.normalize()
            k = min(1.0, (0.05 - p.z) / 0.03)
            p = p + side * noise.noise(Vector((s * 3.0, 0, 0)) + off) * wiggle * k
        p = Vector((p.x, p.y, max(p.z, radius + lift)))
        out.append(p)
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_mode = "ROUND"
    cu.bevel_depth = radius
    cu.bevel_resolution = 2
    cu.use_fill_caps = True
    cu.twist_mode = "MINIMUM"
    sp = cu.splines.new("POLY")
    sp.points.add(len(out) - 1)
    for p, q in zip(sp.points, out):
        p.co = (q.x, q.y, q.z, 1.0)
    sp.use_smooth = True
    cu.materials.append(mat)
    obj = bpy.data.objects.new(name, cu)
    col.objects.link(obj)
    return obj


def coil(center, r=0.12, turns=2, rng=None, z=0.0):
    """Control points for a loose coil lying on the floor."""
    rng = rng or random.Random(0)
    pts = []
    a0 = rng.uniform(0, math.tau)
    for i in range(int(turns * 8)):
        a = a0 + i / 8 * math.tau
        rr = r * rng.uniform(0.8, 1.15)
        pts.append((center[0] + math.cos(a) * rr, center[1] + math.sin(a) * rr * rng.uniform(0.7, 1.0), z))
    return pts


def power_strip(col, m, name, loc, rot_z=0.0, n=4):
    b = Pile(m)
    b.box((0.32, 0.055, 0.04), (0, 0, 0.02), m["plastic_white"])
    for i in range(n):
        x = -0.11 + i * 0.06
        b.box((0.034, 0.034, 0.002), (x, 0, 0.041), m["plastic_black_satin"])
    for x in (-0.11, 0.01):
        b.box((0.04, 0.03, 0.035), (x, 0.0, 0.058), m["plastic_black"])
    b.box((0.025, 0.015, 0.012), (0.15, 0.0, 0.043), m["plastic_black"])
    return b.build(name, col, loc, rot_z, bevel=0.003)


def wall_socket(col, m, name, loc, rot_z=0.0):
    b = Pile(m)
    b.box((0.146, 0.009, 0.086), (0, 0, 0), m["plastic_white"])
    for x in (-0.035, 0.035):
        b.box((0.02, 0.003, 0.03), (x, -0.005, 0.0), m["plastic_white"])
        b.box((0.03, 0.025, 0.04), (x, -0.017, -0.01), m["plastic_black"])
    return b.build(name, col, loc, rot_z, bevel=0.002)


# --------------------------------------------------------------------------- scanned models


def model(col, name, asset_id, filename, loc, rot_z=0.0, scale=1.0):
    """A glTF model from the asset cache, joined into one object standing on loc."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=assets.path(asset_id, filename))
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    for o in meshes:
        o.matrix_world = o.matrix_world.copy()
        o.parent = None
    for o in new:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        if o.type == "MESH":
            col.objects.link(o)
        else:
            bpy.data.objects.remove(o)
    obj = meshes[0]
    if len(meshes) > 1:
        with bpy.context.temp_override(active_object=obj, selected_editable_objects=meshes):
            bpy.ops.object.join()
    obj.data.transform(obj.matrix_world)
    obj.matrix_world = Matrix()
    low = min(v.co.z for v in obj.data.vertices)
    obj.data.transform(Matrix.Translation((0, 0, -low)))
    obj.name = obj.data.name = name
    obj.location = loc
    obj.rotation_euler = (0, 0, rot_z)
    obj.scale = (scale, scale, scale)
    return obj

