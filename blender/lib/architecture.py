"""Walls, openings, windows, doors and ceilings, driven by a room spec dict.

Conventions (every room): metres, Z up, +Y is north, room interior centred on the
origin, floor at z=0. Along-wall positions run west->east on N/S walls and
south->north on E/W walls.

Nothing here is a perfect box: walls are single meshes with rounded arrises at
window reveals and a faint low-frequency wobble; floor and ceiling boards are
individual pieces; timbers are lofted with twist, bow and chamfers.

Floorboard attributes (point domain, FLOAT, one value per board piece) for the
floor material:
    board_id    0, 1, 2, ... per piece (whole numbers)
    board_rand  0..1 random per piece
    board_along_x  1 where boards run east-west (along x), 0 north-south
"""

import math
import random
import zlib

import bmesh
import bpy
from mathutils import Vector, noise

from .geo import Builder, collection
from . import materials

INWARD = {"N": (0, -1, 0), "S": (0, 1, 0), "E": (-1, 0, 0), "W": (1, 0, 0)}
X, Y, Z = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))

# per wall finish: arris radius at window reveals, plaster wobble amplitude (m)
WALL_FEEL = {"plaster": (0.015, 0.003), "brick_x": (0.04, 0.002), "brick_y": (0.04, 0.002)}

# steel window sections (W20-like): face widths, flange/web thickness, depth
STEEL = {"frame": 0.034, "mullion": 0.034, "bar": 0.02, "casement": 0.026, "flange": 0.0045,
         "web": 0.004, "depth": 0.028, "proud": 0.007}

FLOOR_T = 0.021  # floorboard thickness
FLOOR_GAP = 0.0022
CEIL_T = 0.022  # ceiling board thickness


# --- materials (architecture-only extras) -------------------------------------


def _arch_mat(name, color, rough=0.5, metal=0.0):
    mat = bpy.data.materials.get(name)
    if mat:
        return mat
    mat = bpy.data.materials.new(name)
    try:
        mat.use_nodes = True
    except AttributeError:
        pass
    bsdf = next(n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    mat.diffuse_color = (*color, 1)
    return mat


def arch_materials():
    return {
        "arch_putty": _arch_mat("arch_putty", (0.025, 0.025, 0.024), 0.6),  # painted over, like the frames
        "arch_void": _arch_mat("arch_void", (0.02, 0.012, 0.008), 0.9),  # behind board gaps
        "arch_tile": _arch_mat("arch_tile", (0.86, 0.86, 0.84), 0.12),  # glazed white sill tiles
        "arch_grout": _arch_mat("arch_grout", (0.62, 0.61, 0.58), 0.8),
        # ceiling boards: the ceiling wood without its painted-on plank joints (boards are real here)
        "arch_ceiling_boards": materials.ceiling_boards(),
    }


# --- mesh helpers -------------------------------------------------------------


def _loft(b, rings, mat, cap=True):
    """Quads between consecutive closed rings of points (equal counts), optional end caps."""
    bm = b.bm
    vs = [[bm.verts.new(p) for p in ring] for ring in rings]
    n = len(vs[0])
    for r0, r1 in zip(vs, vs[1:]):
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((r0[i], r0[j], r1[j], r1[i]))
    if cap:
        bm.faces.new(vs[0][::-1])
        bm.faces.new(vs[-1])
    b._assign([v for r in vs for v in r], mat)
    return vs


def _sweep(b, profile, p0, p1, u, v, mat):
    """Extrude a 2D profile (pu, pv) -> p + u*pu + v*pv straight from p0 to p1."""
    p0, p1, u, v = Vector(p0), Vector(p1), Vector(u), Vector(v)
    return _loft(b, [[p + u * pu + v * pv for pu, pv in profile] for p in (p0, p1)], mat)


def _rrect(w, h, r, seg=3):
    """Rounded rectangle centred on 0 (seg=1 gives a chamfer)."""
    pts = []
    for cx, cy, a0 in ((w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90),
                       (-w / 2 + r, -h / 2 + r, 180), (w / 2 - r, -h / 2 + r, 270)):
        for k in range(seg + 1):
            a = math.radians(a0 + 90 * k / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _tee(face, flange, web, depth):
    """T section: flange on the room side (v=0), web running outward (+v)."""
    return [(-face / 2, 0), (face / 2, 0), (face / 2, flange), (web / 2, flange), (web / 2, depth),
            (-web / 2, depth), (-web / 2, flange), (-face / 2, flange)]


def _ell(face, flange, web, depth):
    """L section: flange from the outer edge (u=0) inward, web along the outer edge."""
    return [(0, 0), (face, 0), (face, flange), (web, flange), (web, depth), (0, depth)]


def _bullnose(depth, thick, seg=6):
    """Board end-on (u = depth into the room, v = up) with a fully rounded front edge."""
    r = thick / 2
    pts = [(0, 0), (depth - r, 0)]
    for k in range(1, seg):
        a = -math.pi / 2 + math.pi * k / seg
        pts.append((depth - r + r * math.cos(a), r + r * math.sin(a)))
    return pts + [(depth - r, thick), (0, thick)]


def _timber(b, p0, p1, w, h, rng, mat, round_r=0.008, seg=1, twist=0.01, bow=0.004, rough=0.0015,
            stations=9):
    """A sawn timber between two centreline points: chamfered/rounded section, slight
    twist about its axis, a bow, and a rough-sawn wander in its size."""
    p0, p1 = Vector(p0), Vector(p1)
    a = (p1 - p0).normalized()
    side = Z.cross(a).normalized()
    up = a.cross(side)
    tw, bw, sw = rng.uniform(-twist, twist), rng.uniform(-bow, bow), rng.uniform(-bow, bow)
    rings = []
    for k in range(stations):
        t = k / (stations - 1)
        ang = tw * (2 * t - 1)
        o = p0.lerp(p1, t) + up * (bw * math.sin(math.pi * t)) + side * (sw * math.sin(math.pi * t))
        u = side * math.cos(ang) + up * math.sin(ang)
        v = -side * math.sin(ang) + up * math.cos(ang)
        prof = _rrect(w + rng.uniform(-rough, rough), h + rng.uniform(-rough, rough), round_r, seg)
        rings.append([o + u * pu + v * pv for pu, pv in prof])
    return _loft(b, rings, mat)


def _finish(b, name, col, location=(0, 0, 0), rot_z=0.0, smooth=None, no_bevel=True):
    """Build with outward normals; optional smooth shading (sharp above `smooth` degrees)."""
    bmesh.ops.recalc_face_normals(b.bm, faces=b.bm.faces[:])
    if smooth:
        for f in b.bm.faces:
            f.smooth = True
    obj = b.build(name, col, location, rot_z)
    if smooth:
        try:
            obj.data.set_sharp_from_angle(angle=math.radians(smooth))
        except (AttributeError, TypeError):
            pass
    if no_bevel:
        obj["no_bevel"] = True
    return obj


def _breaks(fixed, lo, hi, step, keep=0.08):
    """Sorted grid lines: the fixed ones plus extras roughly every `step`, none closer than `keep`."""
    out = sorted({round(v, 6) for v in fixed if lo - 1e-6 <= v <= hi + 1e-6})
    n = max(1, int((hi - lo) / step))
    for k in range(1, n):
        v = lo + (hi - lo) * k / n
        if all(abs(v - f) > keep for f in out):
            out.append(v)
    return sorted(out)


def _board_edges(x0, x1, width=0.19):
    """Board edges across the floor: boards about `width` wide, gently varying.
    The floor material shades each board from its board_id/board_rand attributes."""
    def f(x):
        return x / width + 0.22 * math.sin(1.9 * x) + 0.13 * math.sin(4.3 * x + 1.0)

    edges = [x0]
    for k in range(math.ceil(f(x0)), math.floor(f(x1)) + 1):
        lo, hi = x0, x1
        for _ in range(40):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if f(mid) < k else (lo, mid)
        if (lo - edges[-1]) > 0.04 and (x1 - lo) > 0.04:
            edges.append(lo)
    return edges + [x1]


class Room:
    def __init__(self, spec, mats):
        self.spec = spec
        self.mats = dict(mats)
        self.mats.update(arch_materials())
        self.w = spec["width"]
        self.d = spec["depth"]
        self.h = spec["height"]
        self.t = spec["wall_thickness"]
        self.col = collection("Architecture")
        self.ceiling_col = collection("Ceiling")
        self.light_col = collection("Lighting")

    # --- wall geometry -------------------------------------------------------

    def _along_x(self, side):
        return side in ("N", "S")

    def _centre_line(self, side):
        return {
            "N": self.d / 2 + self.t / 2,
            "S": -self.d / 2 - self.t / 2,
            "E": self.w / 2 + self.t / 2,
            "W": -self.w / 2 - self.t / 2,
        }[side]

    def _extent(self, side):
        if self._along_x(side):
            return -self.w / 2 - self.t, self.w / 2 + self.t
        return -self.d / 2, self.d / 2

    def _interior(self, side):
        """Along-wall extent of the wall's visible interior face."""
        half = (self.w if self._along_x(side) else self.d) / 2
        return -half, half

    def _point(self, side, along, depth_offset, z):
        """World point on a wall: depth_offset is measured outward from the interior face."""
        inward = Vector(INWARD[side])
        c = self._centre_line(side)
        base = Vector((along, c, z)) if self._along_x(side) else Vector((c, along, z))
        return base + inward * (self.t / 2 - depth_offset)

    def _wall_mesh(self, side, wall, openings):
        """One closed mesh per wall: a grid over the faces with holes for the openings,
        reveal faces through the thickness, rounded arrises at window reveals and a
        faint wobble in the interior face."""
        finish = wall["finish"]
        arris, relief = WALL_FEEL.get(finish, (0.02, 0.002))
        arris, relief = wall.get("arris", arris), wall.get("relief", relief)
        holes = [(o["center"] - o["width"] / 2, o["center"] + o["width"] / 2, o["sill"], o["head"], o["kind"])
                 for o in openings]
        start, end = self._extent(side)
        xs = _breaks([start, end] + [v for h in holes for v in h[:2]], start, end, 0.3)
        zs = _breaks([0.0, self.h] + [v for h in holes for v in h[2:4]], 0.0, self.h, 0.3)

        def hole_at(i, j):
            cx, cz = (xs[i] + xs[i + 1]) / 2, (zs[j] + zs[j + 1]) / 2
            return next((h for h in holes if h[0] < cx < h[1] and h[2] < cz < h[3]), None)

        nx, nz = len(xs) - 1, len(zs) - 1
        solid = [[hole_at(i, j) is None for j in range(nz)] for i in range(nx)]
        b = Builder()
        bm = b.bm
        verts = {}

        def vert(i, j, layer):
            key = (i, j, layer)
            if key not in verts:
                verts[key] = bm.verts.new(self._point(side, xs[i], layer * self.t, zs[j]))
            return verts[key]

        def quad(a, c):  # a, c: (i, j) corners of a cell edge; makes the face through the wall
            return bm.faces.new((vert(*a, 0), vert(*c, 0), vert(*c, 1), vert(*a, 1)))

        round_edges = []
        for i in range(nx):
            for j in range(nz):
                if not solid[i][j]:
                    continue
                bm.faces.new([vert(i, j, 0), vert(i + 1, j, 0), vert(i + 1, j + 1, 0), vert(i, j + 1, 0)])
                bm.faces.new([vert(i, j, 1), vert(i, j + 1, 1), vert(i + 1, j + 1, 1), vert(i + 1, j, 1)])
                for (di, dj), a, c in (((-1, 0), (i, j), (i, j + 1)), ((1, 0), (i + 1, j), (i + 1, j + 1)),
                                       ((0, -1), (i, j), (i + 1, j)), ((0, 1), (i, j + 1), (i + 1, j + 1))):
                    ni, nj = i + di, j + dj
                    inside = 0 <= ni < nx and 0 <= nj < nz
                    if inside and solid[ni][nj]:
                        continue
                    quad(a, c)
                    if inside and hole_at(ni, nj)[4] == "window":
                        round_edges.append(bm.edges.get((vert(*a, 0), vert(*c, 0))))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        if arris > 0 and round_edges:
            bmesh.ops.bevel(bm, geom=round_edges, offset=arris, offset_type="OFFSET", segments=5,
                            profile=0.5, affect="EDGES", clamp_overlap=True)

        # low-frequency wobble, always into the room so corners never open up
        inward = Vector(INWARD[side])
        origin = self._point(side, 0.0, 0.0, 0.0)
        seed = Vector(({"N": 1.3, "S": 7.1, "E": 3.7, "W": 5.9}[side], 0.0, 2.2))
        for v in bm.verts:
            depth = (origin - v.co).dot(inward)
            if depth > arris + 1e-4:
                continue
            a = v.co.x if self._along_x(side) else v.co.y
            p = Vector((a, v.co.z, 0.0))
            n = noise.noise(p * 0.9 + seed) + 0.4 * noise.noise(p * 2.7 + seed * 2.0)
            v.co += inward * relief * (0.5 + 0.5 * max(-1.0, min(1.0, n)))
        b._assign(bm.verts[:], self.mats[finish])
        return _finish(b, f"wall_{side}", self.col, smooth=40)

    def build_walls(self):
        for side, wall in self.spec["walls"].items():
            openings = sorted(wall.get("openings", []), key=lambda o: o["center"])
            self._wall_mesh(side, wall, openings)
            for i, o in enumerate(openings):
                name = f"{o['kind']}_{side}{i + 1}"
                if o["kind"] == "window":
                    self._window(name, side, o)
                elif o["kind"] == "door":
                    self._door(name, side, o)
        self._skirting()

    def _skirting(self):
        """Painted skirting with a rounded top on plaster walls (the painted brick
        runs straight down to the floorboards, as in the photos)."""
        b = Builder()
        t_s, h_s, r = 0.018, 0.13, 0.009
        prof = [(0, 0), (t_s, 0), (t_s, h_s - r)]
        prof += [(t_s - r + r * math.cos(math.pi / 2 * k / 4), h_s - r + r * math.sin(math.pi / 2 * k / 4))
                 for k in range(1, 5)]
        prof += [(0, h_s)]
        for side, wall in self.spec["walls"].items():
            if not wall["finish"].startswith("plaster"):
                continue
            a0, a1 = self._interior(side)
            cuts = sorted((o["center"] - o["width"] / 2 - 0.075, o["center"] + o["width"] / 2 + 0.075)
                          for o in wall.get("openings", []) if o["sill"] < 0.15)
            spans, cur = [], a0
            for c0, c1 in cuts:
                spans.append((cur, c0))
                cur = c1
            spans.append((cur, a1))
            for s0, s1 in spans:
                if s1 - s0 > 0.02:
                    _sweep(b, prof, self._point(side, s0, 0, 0), self._point(side, s1, 0, 0), INWARD[side], Z,
                           self.mats["sash_white"])
        if b.bm.verts:
            _finish(b, "skirting", self.col, no_bevel=False)
        else:
            b.bm.free()

    # --- openings ------------------------------------------------------------

    def _rot(self, side):
        return 0.0 if self._along_x(side) else math.pi / 2

    def _rot_in(self, side):
        """Rotation that turns an opening's local -Y towards the room."""
        return self._rot(side) + (math.pi if side in ("S", "E") else 0.0)

    def _window(self, name, side, o):
        m = self.mats
        w, h = o["width"], o["head"] - o["sill"]
        inset = o.get("inset", self.t * 0.6)
        rng = random.Random(zlib.crc32(name.encode()))
        sill_t = 0.026
        zb, zt = o["sill"] + sill_t, o["head"]

        frame, glass = Builder(), Builder()
        if o.get("style", "steel") == "steel":
            self._steel_window(frame, glass, w, zb, zt, o, rng)
        else:
            self._sash_window(frame, glass, w, zb, zt, o, rng)
        rot = self._rot_in(side)
        centre = self._point(side, o["center"], inset, 0.0)
        _finish(frame, name, self.col, centre, rot, no_bevel=False)
        _finish(glass, f"{name}_glass", self.col, centre, rot)

        # sill board with a bullnose, from the frame out over the wall face (with horns),
        # or (tiled_sill) a deep ledge of glazed white tiles on a grout bed
        sb = Builder()
        proud = 0.032
        depth = inset + proud + 0.03
        y0 = 0.03  # under the frame's web
        if o.get("tiled_sill"):
            x0, x1 = -w / 2 - 0.04, w / 2 + 0.04
            sb.box((x1 - x0, depth, sill_t), ((x0 + x1) / 2, y0 - depth / 2, o["sill"] + sill_t / 2), m["arch_grout"])
            tile, grout = 0.15, 0.004
            nx, ny = max(1, round((x1 - x0) / tile)), max(1, round(depth / tile))
            tx, ty = (x1 - x0) / nx, depth / ny
            for i in range(nx):
                for j in range(ny):
                    sb.box((tx - grout, ty - grout, 0.008),
                           (x0 + tx * (i + 0.5), y0 - ty * (j + 0.5), o["sill"] + sill_t + 0.004), m["arch_tile"])
        else:
            _sweep(sb, _bullnose(depth, sill_t), (-w / 2 - 0.04, y0, o["sill"]), (w / 2 + 0.04, y0, o["sill"]),
                   (0, -1, 0), Z, m["sash_white"])
        _finish(sb, f"{name}_sill", self.col, centre, rot, smooth=35)

        # Cycles light portal just outside the glass
        light = bpy.data.lights.new(f"{name}_portal", "AREA")
        light.shape = "RECTANGLE"
        light.size, light.size_y = w, h
        try:
            light.cycles.is_portal = True
        except AttributeError:
            pass
        obj = bpy.data.objects.new(f"{name}_portal", light)
        obj.location = self._point(side, o["center"], inset + 0.06, o["sill"] + h / 2)
        obj.rotation_euler = Vector(INWARD[side]).to_track_quat("-Z", "Y").to_euler()
        self.light_col.objects.link(obj)

    def _pane(self, b, x0, x1, z0, z1, y, rng, n=4):
        """One pane of old glass: a whisker out of plane and very slightly wavy."""
        tx, tz = rng.uniform(-1, 1) * 0.0025, rng.uniform(-1, 1) * 0.0025
        seed = Vector((rng.uniform(0, 100), rng.uniform(0, 100), 0))
        cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
        grid = []
        for i in range(n + 1):
            row = []
            for j in range(n + 1):
                x, z = x0 + (x1 - x0) * i / n, z0 + (z1 - z0) * j / n
                wave = 0.0005 * noise.noise(Vector((x * 4.0, z * 4.0, 0)) + seed)
                row.append(b.bm.verts.new((x, y + (x - cx) * tx + (z - cz) * tz + wave, z)))
            grid.append(row)
        for i in range(n):
            for j in range(n):
                b.bm.faces.new((grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]))
        b._assign([v for r in grid for v in r], self.mats["glass"])

    def _glazed_cell(self, frame, glass, x0, x1, z0, z1, ov, y, rng):
        """Pane spanning a cell (edges `ov` under the surrounding flanges, per side:
        left, right, bottom, top) plus putty fillets on the outside face."""
        px0, px1, pz0, pz1 = x0 - ov[0], x1 + ov[1], z0 - ov[2], z1 + ov[3]
        self._pane(glass, px0, px1, pz0, pz1, y, rng)
        putty, fh = self.mats["arch_putty"], 0.007
        for (p0, p1, u), o_ in (
                (((px0, y, pz0), (px0, y, pz1), X), ov[0]), (((px1, y, pz0), (px1, y, pz1), -X), ov[1]),
                (((px0, y, pz0), (px1, y, pz0), Z), ov[2]), (((px0, y, pz1), (px1, y, pz1), -Z), ov[3])):
            fw = o_ + 0.003
            _sweep(frame, [(0, 0.0003), (fw, 0.0003), (0, fh)], p0, p1, u, Y, putty)

    def _steel_window(self, b, glass, w, zb, zt, o, rng):
        """Steel window in local space (x across, z = world height, -y = room).
        Outer columns are opening casements (proud of the fixed frame) with lever
        handles and stays; the rest are fixed lights."""
        s, steel = STEEL, self.mats["steel_black"]
        F, tf, tw, D = s["frame"], s["flange"], s["web"], s["depth"]
        cols, rows = o.get("cols", 3), o.get("rows", 4)
        casements = o.get("casements", [0, cols - 1] if cols >= 3 else list(range(cols)) if cols == 2 else [])
        lines = [-w / 2 + w * c / cols for c in range(cols + 1)]
        rows_z = [zb + (zt - zb) * r / rows for r in range(rows + 1)]

        # fixed outer frame: L sections; head/sill full width, jambs between them
        x0, x1 = -w / 2, w / 2
        _sweep(b, _ell(F, tf, tw, D), (x0, 0, zb), (x1, 0, zb), Z, Y, steel)
        _sweep(b, _ell(F, tf, tw, D), (x0, 0, zt), (x1, 0, zt), -Z, Y, steel)
        _sweep(b, _ell(F, tf, tw, D), (x0, 0, zb + F), (x0, 0, zt - F), X, Y, steel)
        _sweep(b, _ell(F, tf, tw, D), (x1, 0, zb + F), (x1, 0, zt - F), -X, Y, steel)
        cz0, cz1 = zb + F, zt - F

        # column boundaries: mullions where a casement meets anything, T bars between fixed lights
        def boundary(c):
            if c in (0, cols):
                return F, 0.008  # outer frame: visible face, pane overlap
            mull = (c - 1) in casements or c in casements
            face = s["mullion"] if mull else s["bar"]
            _sweep(b, _tee(face, tf, tw, D), (lines[c], 0.0005, cz0), (lines[c], 0.0005, cz1), X, Y, steel)
            return face / 2, face / 2 - tw / 2

        bounds = [boundary(c) for c in range(cols + 1)]
        bar_ov = s["bar"] / 2 - tw / 2
        fixed = [c for c in range(cols) if c not in casements]
        for c in fixed:  # horizontal T bars and panes in each fixed light
            l, r = lines[c] + bounds[c][0], lines[c + 1] - bounds[c + 1][0]
            for z in rows_z[1:-1]:
                _sweep(b, _tee(s["bar"], tf, tw, D), (l, 0.0005, z), (r, 0.0005, z), Z, Y, steel)
            for k in range(rows):
                zl = cz0 if k == 0 else rows_z[k] + s["bar"] / 2
                zh = cz1 if k == rows - 1 else rows_z[k + 1] - s["bar"] / 2
                self._glazed_cell(b, glass, l, r, zl, zh, (bounds[c][1], bounds[c + 1][1],
                                  0.008 if k == 0 else bar_ov, 0.008 if k == rows - 1 else bar_ov),
                                  tf + 0.0003, rng)
        for c in casements:
            l, r = lines[c] + bounds[c][0], lines[c + 1] - bounds[c + 1][0]
            hinge = -1 if c < cols / 2 else 1
            self._casement(b, glass, l, r, cz0, cz1, rows_z, hinge, rng)

    def _casement(self, b, glass, l, r, z0, z1, rows_z, hinge, rng):
        """Opening casement over the clear opening l..r x z0..z1, lapping the fixed frame."""
        s, steel = STEEL, self.mats["steel_black"]
        lap, Fc, tw, proud = 0.006, s["casement"], s["web"], s["proud"]
        prof = [(0, 0), (Fc, 0), (Fc, 0.022), (Fc - tw, 0.022), (Fc - tw, proud - 0.0005), (0, proud - 0.0005)]
        y = -proud
        ol, or_, ob, ot = l - lap, r + lap, z0 - lap, z1 + lap
        _sweep(b, prof, (ol, y, ob), (or_, y, ob), Z, Y, steel)
        _sweep(b, prof, (ol, y, ot), (or_, y, ot), -Z, Y, steel)
        _sweep(b, prof, (ol, y, ob + Fc), (ol, y, ot - Fc), X, Y, steel)
        _sweep(b, prof, (or_, y, ob + Fc), (or_, y, ot - Fc), -X, Y, steel)
        il, ir, ib, it = ol + Fc, or_ - Fc, ob + Fc, ot - Fc
        bar, tf = s["bar"], s["flange"]
        inner_z = [z for z in rows_z[1:-1] if ib + 0.03 < z < it - 0.03]
        for z in inner_z:
            _sweep(b, _tee(bar, tf, tw, 0.02), (il, y + 0.0015, z), (ir, y + 0.0015, z), Z, Y, steel)
        edges = [ib] + inner_z + [it]
        bar_ov = bar / 2 - tw / 2
        for k in range(len(edges) - 1):
            zl = edges[k] + (0 if k == 0 else bar / 2)
            zh = edges[k + 1] - (0 if k == len(edges) - 2 else bar / 2)
            self._glazed_cell(b, glass, il, ir, zl, zh, (0.008, 0.008, 0.008 if k == 0 else bar_ov,
                              0.008 if k == len(edges) - 2 else bar_ov), 0.0, rng)

        # ironmongery on the meeting stile: lever handle (pointing towards the hinge) and a stay
        meet = or_ - Fc / 2 if hinge < 0 else ol + Fc / 2
        hz = z0 + 0.45 * (z1 - z0)
        self._lever(b, meet, y, hz, hinge)
        self._stay(b, meet, y, ob + Fc / 2, hinge, min(0.26, 0.7 * (r - l)))

    def _lever(self, b, x, y, z, s):
        """Black lever ('monkey tail') casement fastener on a back plate; s = lever direction."""
        steel = self.mats["steel_black"]
        b.box((0.018, 0.005, 0.07), (x, y - 0.0025, z), steel)
        b.cyl(0.0065, 0.02, (x, y - 0.012, z), steel, rot=(math.pi / 2, 0, 0), segments=16)
        a, ln = 0.45, 0.095
        b.box((ln, 0.008, 0.011), (x + s * math.cos(a) * ln / 2, y - 0.02, z - math.sin(a) * ln / 2), steel,
              rot=(0, s * a, 0))
        tx, tz = x + s * math.cos(a) * ln, z - math.sin(a) * ln
        b.cyl(0.0085, 0.012, (tx, y - 0.02, tz), steel, rot=(math.pi / 2, 0, 0), segments=16)
        b.box((0.03, 0.007, 0.008), (tx + s * 0.012, y - 0.02, tz + 0.012), steel, rot=(0, -s * 1.0, 0))

    def _stay(self, b, x, y, z, s, length):
        """Casement stay lying along the bottom rail: pivot bracket at the meeting stile, pins along it."""
        steel = self.mats["steel_black"]
        b.box((0.022, 0.012, 0.024), (x, y - 0.006, z), steel)
        b.box((length, 0.005, 0.011), (x + s * length / 2, y - 0.0145, z), steel)
        b.cyl(0.0075, 0.006, (x, y - 0.018, z), steel, rot=(math.pi / 2, 0, 0), segments=16)
        for d in (length - 0.03, length - 0.1):
            b.cyl(0.0032, 0.024, (x + s * d, y - 0.012, z), steel, rot=(math.pi / 2, 0, 0), segments=10)

    def _sash_window(self, b, glass, w, zb, zt, o, rng):
        """Painted timber sliding sash: box frame, two sashes, glazing bars, meeting-rail catch."""
        m, paint = self.mats, self.mats["sash_white"]
        F, depth = 0.06, 0.1
        b.box((w, depth, F), (0, 0.02, zb + F / 2), paint)
        b.box((w, depth, F), (0, 0.02, zt - F / 2), paint)
        for sx in (-1, 1):
            b.box((F, depth, zt - zb - 2 * F), (sx * (w / 2 - F / 2), 0.02, (zb + zt) / 2), paint)
        l, r, z0, z1 = -w / 2 + F, w / 2 - F, zb + F, zt - F
        mid = (z0 + z1) / 2
        cols = o.get("cols", 2)
        for (sb, st, y, bottom, top) in ((z0, mid + 0.018, -0.022, 0.07, 0.035), (mid - 0.018, z1, 0.022, 0.035, 0.045)):
            stile = 0.045
            b.box((r - l, 0.04, bottom), (0, y, sb + bottom / 2), paint)
            b.box((r - l, 0.04, top), (0, y, st - top / 2), paint)
            for sx in (-1, 1):
                b.box((stile, 0.04, st - sb - bottom - top), (sx * ((r - l) / 2 - stile / 2), y,
                                                             (sb + bottom + st - top) / 2), paint)
            il, ir, ib, it = l + stile, r - stile, sb + bottom, st - top
            xs = [il + (ir - il) * c / cols for c in range(cols + 1)]
            for x in xs[1:-1]:
                b.box((0.022, 0.03, it - ib), (x, y, (ib + it) / 2), paint)
            for c in range(cols):
                self._pane(glass, xs[c] + (0 if c == 0 else 0.011) - 0.008, xs[c + 1] - (0 if c == cols - 1 else 0.011) + 0.008,
                           ib - 0.008, it + 0.008, y + 0.004, rng)
        b.box((0.06, 0.03, 0.012), (0, -0.04, mid + 0.024), m["aluminium"])

    def _door(self, name, side, o):
        """Panelled door(s) in a lined opening: architrave with mitred corners on the
        room side, butt hinges and lever handles."""
        m = self.mats
        paint = m[o.get("finish", "sash_white")]
        w, h = o["width"], o["head"]
        lin, leaf_y, leaf_t = 0.022, 0.08, 0.045
        b = Builder()
        # linings through the wall, and stops behind the leaves
        b.box((lin, self.t, h), (-w / 2 + lin / 2, self.t / 2, h / 2), paint)
        b.box((lin, self.t, h), (w / 2 - lin / 2, self.t / 2, h / 2), paint)
        b.box((w, self.t, lin), (0, self.t / 2, h - lin / 2), paint)
        stop_y = leaf_y + leaf_t / 2 + 0.006
        for sx in (-1, 1):
            b.box((0.012, 0.012, h - lin), (sx * (w / 2 - lin - 0.006), stop_y, (h - lin) / 2), paint)
        b.box((w - 2 * lin, 0.012, 0.012), (0, stop_y, h - lin - 0.006), paint)

        # architrave: stepped moulding, mitred at the head
        arch = [(0, 0), (0, -0.021), (0.008, -0.023), (0.022, -0.023), (0.028, -0.017), (0.07, -0.012),
                (0.075, -0.008), (0.075, 0)]
        for sx in (-1, 1):
            x = sx * w / 2
            ring0 = [(x + sx * pu, pv, 0.0) for pu, pv in arch]
            ring1 = [(x + sx * pu, pv, h + pu) for pu, pv in arch]
            _loft(b, [ring0, ring1] if sx > 0 else [ring1, ring0], paint)
        _loft(b, [[(-w / 2 - pu, pv, h + pu) for pu, pv in arch], [(w / 2 + pu, pv, h + pu) for pu, pv in arch]],
              paint)

        leaves = o.get("leaves", 1)
        clear = w - 2 * lin - 0.003 * (leaves + 1)
        lw = clear / leaves
        for i in range(leaves):
            lx = -w / 2 + lin + 0.003 + i * (lw + 0.003) + lw / 2
            hinge = -1 if (leaves == 1 or i == 0) else 1
            self._leaf(b, lx, leaf_y, lw, h - lin - 0.003, leaf_t, hinge, paint)
        if leaves == 2:  # astragal over the meeting stiles
            b.box((0.034, 0.009, h - lin - 0.003), (0, leaf_y - leaf_t / 2 - 0.0045, (h - lin - 0.003) / 2), paint)
        _finish(b, name, self.col, self._point(side, o["center"], 0.0, 0.0), self._rot_in(side), no_bevel=False)

    def _leaf(self, b, cx, y, lw, lh, t, hinge, paint):
        """One leaf: stiles and rails with two fielded panels, beads, hinges, lever handle."""
        m = self.mats
        st, top, mid, bot = 0.11, 0.11, 0.17, 0.21
        x0, x1 = cx - lw / 2, cx + lw / 2
        mz = 0.95
        b.box((st, t, lh), (x0 + st / 2, y, lh / 2), paint)
        b.box((st, t, lh), (x1 - st / 2, y, lh / 2), paint)
        for zc, hh in ((bot / 2, bot), (mz, mid), (lh - top / 2, top)):
            b.box((lw - 2 * st, t, hh), (cx, y, zc), paint)
        bead = _rrect(0.012, 0.012, 0.005, 2)
        for pz0, pz1 in ((bot, mz - mid / 2), (mz + mid / 2, lh - top)):
            pw, ph = lw - 2 * st, pz1 - pz0
            b.box((pw, 0.018, ph), (cx, y, (pz0 + pz1) / 2), paint)
            b.box((pw - 0.08, 0.026, ph - 0.08), (cx, y, (pz0 + pz1) / 2), paint)  # raised field
            for face in (-1, 1):
                yb = y + face * 0.012
                pts = [(cx - pw / 2 + 0.006, pz0 + 0.006), (cx + pw / 2 - 0.006, pz0 + 0.006),
                       (cx + pw / 2 - 0.006, pz1 - 0.006), (cx - pw / 2 + 0.006, pz1 - 0.006)]
                for k in range(4):
                    (ax, az), (bx, bz) = pts[k], pts[(k + 1) % 4]
                    _sweep(b, bead, (ax, yb, az), (bx, yb, bz), Z if az == bz else X, Y, paint)
        # hinges on the hinge edge (knuckles on the room face), handle on the meeting edge
        hx = x0 if hinge < 0 else x1
        for z in (0.24, 1.05, lh - 0.24):
            b.cyl(0.0075, 0.1, (hx, y - t / 2 - 0.002, z), m["aluminium"], segments=16)
            b.box((0.03, 0.002, 0.1), (hx - hinge * 0.015, y - t / 2 - 0.001, z), m["aluminium"])
        ex = x1 - 0.065 if hinge < 0 else x0 + 0.065
        ry = y - t / 2
        b.cyl(0.026, 0.008, (ex, ry - 0.004, 1.0), m["aluminium"], rot=(math.pi / 2, 0, 0))
        b.cyl(0.009, 0.05, (ex, ry - 0.03, 1.0), m["aluminium"], rot=(math.pi / 2, 0, 0), segments=16)
        b.cyl(0.0095, 0.13, (ex + hinge * 0.06, ry - 0.055, 1.0), m["aluminium"], rot=(0, math.pi / 2, 0),
              segments=16)
        b.cyl(0.016, 0.006, (ex, ry - 0.003, 0.88), m["aluminium"], rot=(math.pi / 2, 0, 0))

    # --- floor, ceiling, beams ----------------------------------------------

    def build_floor(self):
        """Floorboards: one piece per board length, chamfered top edges, gaps, staggered
        ends and tiny height/roll/yaw differences. The spec's "floor" sets the direction
        boards run ("Y" north-south, the default, or "X" east-west) and their width."""
        w, d, t = self.w, self.d, self.t
        spec = self.spec.get("floor", {})
        run_x = spec.get("run", "Y") == "X"
        rng = random.Random(5)
        b = Builder()
        bid = b.bm.verts.layers.float.new("board_id")
        brand = b.bm.verts.layers.float.new("board_rand")
        balong = b.bm.verts.layers.float.new("board_along_x")

        # Lay boards out in (across, along) and rotate into the room, so east-west
        # boards are a true rotation of north-south ones (a mirror would flip normals).
        def place(a, l, z):
            return Vector((l, -a, z)) if run_x else Vector((a, l, z))

        x_ext, y_ext = (-w / 2 - t, w / 2 + t), (-d / 2 - t, d / 2 + t)
        across, (y0, y1) = (y_ext, x_ext) if run_x else (x_ext, y_ext)
        edges = _board_edges(*across, width=spec.get("board_width", 0.19))
        c = 0.0015
        n = 0
        for xa, xb in zip(edges, edges[1:]):
            bw = xb - xa - FLOOR_GAP
            prof = [(-bw / 2, -FLOOR_T), (bw / 2, -FLOOR_T), (bw / 2, -c), (bw / 2 - c, 0),
                    (-bw / 2 + c, 0), (-bw / 2, -c)]
            ya = y0 - rng.uniform(0.0, 2.5)
            while ya < y1:
                yb = ya + rng.uniform(1.6, 3.8)
                pa, pb = max(ya, y0), min(yb, y1)
                if pb - pa > 0.05:
                    roll = rng.uniform(-1, 1) * 0.0016
                    cr, sr = math.cos(roll), math.sin(roll)
                    rings = []
                    for yy in (pa + FLOOR_GAP / 2, pb - FLOOR_GAP / 2):
                        oa, oz = (xa + xb) / 2 + rng.uniform(-1, 1) * 0.0004, rng.uniform(-0.0007, 0.0002)
                        rings.append([place(oa + cr * pu - sr * pv, yy, oz + sr * pu + cr * pv) for pu, pv in prof])
                    r = rng.random()
                    for ring in _loft(b, rings, self.mats["floor"]):
                        for vert in ring:
                            vert[bid], vert[brand], vert[balong] = float(n), r, float(run_x)
                    n += 1
                ya = yb
        b.box((w + 2 * t, d + 2 * t, 0.02), (0, 0, -FLOOR_T - 0.01), self.mats["arch_void"])
        _finish(b, "floor", self.col)

    def build_ceiling(self):
        m, w, d, h, t = self.mats, self.w, self.d, self.h, self.t
        spec = self.spec.get("ceiling", {})
        rng = random.Random(9)
        # joist_axis: the axis joists run along. Ceiling boards run across them; cross
        # beams run the other way too, positioned along the joist axis.
        along_x = spec.get("joist_axis", "Y") == "X"
        length, span = (w, d) if along_x else (d, w)

        def at(a, s, z):  # (along joists, across joists) -> world
            return Vector((a, s, z)) if along_x else Vector((s, a, z))

        cb = Builder()
        a = -length / 2
        while a < length / 2:
            bw = rng.uniform(0.11, 0.17)
            gap = rng.uniform(0.003, 0.007)
            z = h - CEIL_T / 2 + rng.uniform(-0.001, 0.001)
            _timber(cb, at(a + bw / 2, -span / 2 - 0.05, z), at(a + bw / 2, span / 2 + 0.05, z), bw - gap, CEIL_T,
                    rng, m["arch_ceiling_boards"], round_r=0.003, twist=0.004, bow=0.0015, rough=0.001, stations=4)
            a += bw
        cb.box((w + 2 * t, d + 2 * t, 0.1), (0, 0, h + 0.05), m["arch_void"])
        _finish(cb, "ceiling", self.ceiling_col, smooth=30)

        jb = Builder()
        depth = spec.get("joist_depth", 0.2)
        spacing = spec.get("joist_spacing", 0.55)
        top = h - CEIL_T + 0.004
        bottoms = []
        p = -span / 2 + spacing / 2
        while p < span / 2:
            q = p + rng.uniform(-0.025, 0.025)
            jw, jd = rng.uniform(0.09, 0.115), depth + rng.uniform(-0.008, 0.008)
            zc = top - jd / 2
            _timber(jb, at(-length / 2 - 0.08, q, zc), at(length / 2 + 0.08, q, zc), jw, jd, rng, m["beam_wood"],
                    round_r=rng.uniform(0.006, 0.012), twist=0.014, bow=0.005, rough=0.002)
            bottoms.append(top - jd)
            p += spacing
        bh, bwid = 0.32, 0.26
        btop = (max(bottoms) if bottoms else top) + 0.003
        for q in spec.get("cross_beams", []):
            zc = btop - bh / 2
            _timber(jb, at(q, -span / 2 - 0.1, zc), at(q, span / 2 + 0.1, zc), bwid, bh, rng, m["beam_wood"],
                    round_r=0.03, seg=3, twist=0.008, bow=0.006, rough=0.003, stations=11)
        _finish(jb, "joists", self.ceiling_col, smooth=30)

    def build_shell(self):
        self.build_floor()
        self.build_ceiling()

    def build(self):
        self.build_shell()
        self.build_walls()


# Kept here for rooms that still call architecture.build_world() etc.
from .environment import SKY_SUN_RATIO, build_outdoors, build_sun, build_world  # noqa: E402,F401
