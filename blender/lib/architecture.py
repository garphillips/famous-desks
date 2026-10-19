"""Walls, openings, windows, doors and ceilings, driven by a room spec dict.

Conventions (every room): metres, Z up, +Y is north, room interior centred on the
origin, floor at z=0. Along-wall positions run west->east on N/S walls and
south->north on E/W walls.
"""

import math

import bmesh
import bpy
from mathutils import Vector

from .geo import Builder, collection

INWARD = {"N": (0, -1, 0), "S": (0, 1, 0), "E": (-1, 0, 0), "W": (1, 0, 0)}


class Room:
    def __init__(self, spec, mats):
        self.spec = spec
        self.mats = mats
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

    def _point(self, side, along, depth_offset, z):
        """World point on a wall: depth_offset is measured outward from the interior face."""
        inward = Vector(INWARD[side])
        c = self._centre_line(side)
        base = Vector((along, c, z)) if self._along_x(side) else Vector((c, along, z))
        return base + inward * (self.t / 2 - depth_offset)

    def _segment(self, b, side, a0, a1, z0, z1, mat):
        if a1 - a0 < 1e-4 or z1 - z0 < 1e-4:
            return
        c = self._centre_line(side)
        mid_a, mid_z = (a0 + a1) / 2, (z0 + z1) / 2
        if self._along_x(side):
            b.box((a1 - a0, self.t, z1 - z0), (mid_a, c, mid_z), mat)
        else:
            b.box((self.t, a1 - a0, z1 - z0), (c, mid_a, mid_z), mat)

    def build_walls(self):
        for side, wall in self.spec["walls"].items():
            mat = self.mats[wall["finish"]]
            openings = sorted(wall.get("openings", []), key=lambda o: o["center"])
            b = Builder()
            start, end = self._extent(side)
            cursor = start
            for o in openings:
                o0, o1 = o["center"] - o["width"] / 2, o["center"] + o["width"] / 2
                self._segment(b, side, cursor, o0, 0, self.h, mat)
                self._segment(b, side, o0, o1, 0, o["sill"], mat)
                self._segment(b, side, o0, o1, o["head"], self.h, mat)
                cursor = o1
            self._segment(b, side, cursor, end, 0, self.h, mat)
            b.build(f"wall_{side}", self.col)

            for i, o in enumerate(openings):
                name = f"{o['kind']}_{side}{i + 1}"
                if o["kind"] == "window":
                    self._window(name, side, o)
                elif o["kind"] == "door":
                    self._door(name, side, o)

    # --- openings ------------------------------------------------------------

    def _rot(self, side):
        return 0.0 if self._along_x(side) else math.pi / 2

    def _window(self, name, side, o):
        m = self.mats
        w, h = o["width"], o["head"] - o["sill"]
        style = o.get("style", "steel")
        frame_mat = m["steel_black"] if style == "steel" else m["sash_white"]
        bar = 0.045 if style == "steel" else 0.065
        mullion = 0.018 if style == "steel" else 0.035
        inset = o.get("inset", self.t * 0.6)

        b = Builder()
        # outer frame
        b.box((w, 0.05, bar), (0, 0, h / 2 - bar / 2), frame_mat)
        b.box((w, 0.05, bar), (0, 0, -h / 2 + bar / 2), frame_mat)
        b.box((bar, 0.05, h), (-w / 2 + bar / 2, 0, 0), frame_mat)
        b.box((bar, 0.05, h), (w / 2 - bar / 2, 0, 0), frame_mat)
        # glazing bars
        cols, rows = o.get("cols", 3), o.get("rows", 4)
        for c in range(1, cols):
            b.box((mullion, 0.035, h), (-w / 2 + w * c / cols, 0, 0), frame_mat)
        for r in range(1, rows):
            b.box((w, 0.035, mullion), (0, 0, -h / 2 + h * r / rows), frame_mat)
        b.box((w - 0.01, 0.006, h - 0.01), (0, 0, 0), m["glass"])
        centre = self._point(side, o["center"], inset, o["sill"] + h / 2)
        b.build(name, self.col, centre, self._rot(side))

        # interior sill board across the reveal
        sb = Builder()
        sb.box((w + 0.04, inset + 0.03, 0.03), (0, 0, 0), m["sash_white"])
        sill_pos = self._point(side, o["center"], (inset - 0.03) / 2, o["sill"] + 0.015)
        sb.build(f"{name}_sill", self.col, sill_pos, self._rot(side))

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

    def _door(self, name, side, o):
        m = self.mats
        w, h = o["width"], o["head"]
        b = Builder()
        leaves = o.get("leaves", 1)
        leaf = w / leaves
        for i in range(leaves):
            x0 = -w / 2 + i * leaf
            b.box((leaf - 0.004, 0.045, h), (x0 + leaf / 2, 0, h / 2), m[o.get("finish", "sash_white")])
            handle_x = x0 + (0.09 if i else leaf - 0.09) if leaves > 1 else w / 2 - 0.09
            b.cyl(0.025, 0.07, (handle_x, -0.05, 1.0), m["aluminium"], rot=(math.pi / 2, 0, 0))
        # architrave on the room side
        trim = Builder()
        trim.box((0.07, 0.02, h + 0.07), (-w / 2 - 0.035, 0, (h + 0.07) / 2), m["sash_white"])
        trim.box((0.07, 0.02, h + 0.07), (w / 2 + 0.035, 0, (h + 0.07) / 2), m["sash_white"])
        trim.box((w + 0.14, 0.02, 0.07), (0, 0, h + 0.035), m["sash_white"])
        # local -Y (handle side) must face into the room
        rot = self._rot(side) + (math.pi if side in ("S", "E") else 0.0)
        b.build(name, self.col, self._point(side, o["center"], 0.08, 0), rot)
        trim.build(f"{name}_trim", self.col, self._point(side, o["center"], -0.01, 0), rot)

    # --- floor, ceiling, beams ----------------------------------------------

    def build_shell(self):
        m, w, d, h, t = self.mats, self.w, self.d, self.h, self.t
        fb = Builder()
        fb.box((w + 2 * t, d + 2 * t, 0.1), (0, 0, -0.05), m["floor"])  # runs under door openings
        fb.build("floor", self.col)

        cb = Builder()
        cb.box((w, d, 0.03), (0, 0, h - 0.015), m["ceiling_wood"])
        cb.box((w + 2 * t, d + 2 * t, 0.15), (0, 0, h + 0.075), m["plaster"])
        cb.build("ceiling", self.ceiling_col)

        # joist_axis: the axis joists run along. Cross beams run the other way,
        # positioned along the joist axis.
        spec = self.spec.get("ceiling", {})
        along_x = spec.get("joist_axis", "Y") == "X"
        length, span = (w, d) if along_x else (d, w)
        jb = Builder()
        depth = spec.get("joist_depth", 0.2)
        spacing = spec.get("joist_spacing", 0.55)
        z = h - 0.03 - depth / 2
        p = -span / 2 + spacing / 2
        while p < span / 2:
            if along_x:
                jb.box((length, 0.1, depth), (0, p, z), m["beam_wood"])
            else:
                jb.box((0.1, length, depth), (p, 0, z), m["beam_wood"])
            p += spacing
        bz = h - 0.03 - depth - 0.15
        for q in spec.get("cross_beams", []):
            if along_x:
                jb.box((0.24, d, 0.3), (q, 0, bz), m["beam_wood"])
            else:
                jb.box((w, 0.24, 0.3), (0, q, bz), m["beam_wood"])
        jb.build("joists", self.ceiling_col)

    def build(self):
        self.build_shell()
        self.build_walls()



# --- outdoors, sun and sky -----------------------------------------------------


def _blob(b, centre, radius, mat, squash=1.0, seed=0, lumpiness=0.35):
    """A lumpy, roughly spherical leaf mass (icosphere displaced by smooth noise)."""
    from mathutils import Matrix, noise

    m = Matrix.Translation(centre) @ Matrix.Diagonal((radius, radius, radius * squash, 1.0))
    result = bmesh.ops.create_icosphere(b.bm, subdivisions=3, radius=1.0, matrix=m)
    off = Vector((seed * 3.7, seed * 1.3, seed * 5.1))
    c = Vector(centre)
    for v in result["verts"]:
        d = v.co - c
        n = noise.noise(d / radius * 1.4 + off) + 0.5 * noise.noise(d / radius * 3.5 + off)
        v.co = c + d * (1.0 + lumpiness * n)
    b._assign(result["verts"], mat)


def _tree(b, trunk, x, y, height, spread, crown_mat, mats, rng):
    trunk.cyl(0.12 + height * 0.012, height * 0.55, (x, y, height * 0.275), mats["bark"], segments=10,
              radius2=0.08 + height * 0.006)
    for i in range(rng.randint(5, 8)):
        a = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0.15, 0.55) * spread
        z = height * rng.uniform(0.55, 0.85)
        _blob(b, (x + math.cos(a) * r, y + math.sin(a) * r, z), spread * rng.uniform(0.45, 0.7), crown_mat,
              squash=rng.uniform(0.75, 1.0), seed=rng.randint(0, 999))


def _house(b, x, y, w, d, eaves, ridge, wall_mat, mats, rot_y=False):
    """Simple gabled house; the ridge runs along X (or Y when rot_y)."""
    sx, sy = (d, w) if rot_y else (w, d)
    b.box((sx, sy, eaves), (x, y, eaves / 2), wall_mat)
    bm = b.bm
    over = 0.3
    if rot_y:
        base = [(x - sx / 2 - over, y - sy / 2 - over), (x + sx / 2 + over, y - sy / 2 - over),
                (x + sx / 2 + over, y + sy / 2 + over), (x - sx / 2 - over, y + sy / 2 + over)]
        ridge_pts = [(x, y - sy / 2 - over), (x, y + sy / 2 + over)]
    else:
        base = [(x - sx / 2 - over, y - sy / 2 - over), (x + sx / 2 + over, y - sy / 2 - over),
                (x + sx / 2 + over, y + sy / 2 + over), (x - sx / 2 - over, y + sy / 2 + over)]
        ridge_pts = [(x - sx / 2 - over, y), (x + sx / 2 + over, y)]
    vb = [bm.verts.new((px, py, eaves - 0.2)) for px, py in base]
    vr = [bm.verts.new((px, py, ridge)) for px, py in ridge_pts]
    if rot_y:
        faces = [(vb[0], vb[1], vr[0]), (vb[1], vb[2], vr[1], vr[0]), (vb[2], vb[3], vr[1]),
                 (vb[3], vb[0], vr[0], vr[1]), (vb[3], vb[2], vb[1], vb[0])]
    else:
        faces = [(vb[0], vb[1], vr[1], vr[0]), (vb[1], vb[2], vr[1]), (vb[2], vb[3], vr[0], vr[1]),
                 (vb[3], vb[0], vr[0]), (vb[3], vb[2], vb[1], vb[0])]
    for f in faces:
        bm.faces.new(f)
    b._assign(vb + vr, mats["roof_slate"])
    # dark windows on every face, two storeys
    for level in (eaves * 0.28, eaves * 0.72):
        for t in (-0.3, 0.0, 0.3):
            if rot_y:
                for side in (-1, 1):
                    b.box((0.08, 1.0, 1.2), (x + side * sx / 2, y + t * sy, level), mats["steel_black"])
            else:
                for side in (-1, 1):
                    b.box((1.0, 0.08, 1.2), (x + t * sx, y + side * sy / 2, level), mats["steel_black"])


def build_outdoors(mats, size=200.0, seed=11):
    """A simple procedural garden: lawn, clipped hedges, a few trees and shrubs,
    and the roofs of neighbouring houses beyond the hedge. Everything the
    north and east windows can see is dressed; the rest is kept plain."""
    import random

    rng = random.Random(seed)
    col = collection("Outdoors")
    b = Builder()
    b.box((size, size, 0.1), (0, 0, -0.17), mats["garden"])
    b.build("ground", col)

    # hedges: chains of overlapping leaf masses around the garden
    hedges = Builder()
    for (x0, y0, x1, y1, h) in [(-14, 11, 14, 11, 2.3), (11, -12, 11, 11, 2.0),
                                (-11, -12, -11, 11, 2.0), (-14, -11, 14, -11, 1.8)]:
        n = int(math.hypot(x1 - x0, y1 - y0) / 0.9)
        for i in range(n + 1):
            t = i / n
            hh = h * rng.uniform(0.9, 1.08)
            _blob(hedges, (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, hh * 0.5), 0.85, mats["foliage_dark"],
                  squash=hh / 1.7, seed=rng.randint(0, 999), lumpiness=0.2)
    hedges.build("hedges", col)

    # trees and shrubs (north and east gardens are what the windows see)
    trunks = Builder()
    crowns = Builder()
    tree_specs = [
        (-2.5, 7.5, 7.0, 2.4, "foliage"), (5.0, 7.0, 8.5, 2.8, "foliage_light"), (-8.0, 8.5, 9.0, 3.0, "foliage"),
        (1.5, 13.5, 11.0, 3.4, "foliage_dark"), (8.5, 2.0, 7.5, 2.6, "foliage"), (7.0, -4.5, 9.5, 3.2, "foliage_light"),
        (13.5, 6.5, 10.0, 3.5, "foliage_dark"), (-5.5, -8, 7.0, 2.2, "foliage"), (4.5, -8.5, 8.0, 2.6, "foliage"),
        (-12.5, 14.0, 12.0, 3.8, "foliage_dark"), (15.5, -3.0, 11.0, 3.6, "foliage"),
    ]
    for x, y, h, spread, mat in tree_specs:
        _tree(crowns, trunks, x, y, h, spread, mats[mat], mats, rng)
    for x, y, r in [(-1.0, 4.2, 0.7), (1.8, 4.6, 0.9), (-4.5, 4.0, 0.8), (5.3, 3.8, 0.75), (5.2, 0.4, 0.8),
                    (6.2, -2.0, 0.7), (3.0, 5.6, 0.6)]:
        for k in range(3):
            _blob(crowns, (x + rng.uniform(-0.4, 0.4), y + rng.uniform(-0.4, 0.4), r * 0.6), r * rng.uniform(0.7, 1.0),
                  mats[rng.choice(["foliage", "foliage_light"])], squash=0.8, seed=rng.randint(0, 999))
    trunks.build("tree_trunks", col)
    crowns.build("planting", col)

    # neighbouring houses beyond the hedges
    houses = Builder()
    for x, y, w, d, eaves, ridge, mat, rot in [
        (-9.0, 24.0, 9.0, 7.0, 5.8, 9.0, "house_render", False),
        (3.5, 27.0, 10.0, 8.0, 6.2, 9.8, "house_brick", False),
        (15.0, 23.0, 8.0, 7.0, 5.6, 8.6, "house_render", False),
        (25.0, 2.0, 9.0, 7.5, 5.8, 9.2, "house_brick", True),
        (27.0, 14.0, 8.0, 7.0, 6.0, 9.0, "house_render", True),
    ]:
        _house(houses, x, y, w, d, eaves, ridge, mats[mat], mats, rot)
    houses.build("houses", col)


def build_sun(azimuth_deg, elevation_deg, strength=4.0, colour=(1.0, 0.82, 0.68), angle_deg=1.2):
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
