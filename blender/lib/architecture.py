"""Walls, openings, windows, doors and ceilings, driven by a room spec dict.

Conventions (every room): metres, Z up, +Y is north, room interior centred on the
origin, floor at z=0. Along-wall positions run west->east on N/S walls and
south->north on E/W walls.
"""

import math

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


def build_outdoors(mats, size=60.0):
    """A simple garden so windows don't look out onto a void."""
    col = collection("Outdoors")
    b = Builder()
    b.box((size, size, 0.1), (0, 0, -0.17), mats["garden"])
    b.build("ground", col)
    hedges = Builder()
    for (x, y, sx, sy, h) in [
        (0, -11, 22, 1.5, 1.8), (0, 11, 22, 1.5, 2.2), (-11, 0, 1.5, 22, 2.0), (11, 0, 1.5, 22, 1.8),
    ]:
        hedges.box((sx, sy, h), (x, y, h / 2), mats["foliage"])
    for (x, y, r, h) in [(-5.5, -8, 1.8, 7), (4.5, -8.5, 2.2, 8), (8.5, 3, 2.0, 7), (-7, 6, 1.6, 6)]:
        hedges.cyl(0.18, h * 0.5, (x, y, h * 0.25), mats["beam_wood"], segments=12)
        hedges.cyl(r, h * 0.6, (x, y, h * 0.7), mats["foliage"], segments=12, radius2=r * 0.4)
    hedges.build("planting", col)


def build_sun(azimuth_deg, elevation_deg, strength=4.0):
    """Sun shining FROM the given azimuth (0 = north, 90 = east)."""
    col = collection("Lighting")
    light = bpy.data.lights.new("sun", "SUN")
    light.energy = strength
    light.angle = math.radians(1.0)
    obj = bpy.data.objects.new("sun", light)
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    towards_sun = Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)))
    obj.rotation_euler = (-towards_sun).to_track_quat("-Z", "Y").to_euler()
    col.objects.link(obj)
    return obj


def build_world(colour=(0.55, 0.68, 0.85), strength=1.0):
    world = bpy.data.worlds.new("sky")
    bpy.context.scene.world = world
    try:
        world.use_nodes = True
    except AttributeError:
        pass
    bg = world.node_tree.nodes.get("Background") or world.node_tree.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (*colour, 1)
    bg.inputs["Strength"].default_value = strength
    out = world.node_tree.nodes.get("World Output") or world.node_tree.nodes.new("ShaderNodeOutputWorld")
    world.node_tree.links.new(bg.outputs[0], out.inputs["Surface"])
    return world
