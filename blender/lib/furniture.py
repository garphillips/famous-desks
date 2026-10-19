"""Reusable furniture and props.

Every function builds one object at its local origin (floor or tabletop contact
point) with its front facing local -Y, then places it with location + rot_z.
"""

import math
import random

from mathutils import Vector

from .geo import Builder


def table(m, col, name, loc, size, rot_z=0.0, top="lino_green", frame="pine", leg=0.06):
    w, d, h = size
    b = Builder()
    b.box((w, d, 0.04), (0, 0, h - 0.026), m[frame])
    b.box((w - 0.01, d - 0.01, 0.006), (0, 0, h - 0.003), m[top])
    for sx in (-1, 1):
        for sy in (-1, 1):
            b.box((leg, leg, h - 0.046), (sx * (w / 2 - leg), sy * (d / 2 - leg), (h - 0.046) / 2), m[frame])
    b.box((w - 0.2, 0.025, 0.1), (0, -(d / 2 - leg), h - 0.1), m[frame])
    b.box((w - 0.2, 0.025, 0.1), (0, d / 2 - leg, h - 0.1), m[frame])
    return b.build(name, col, loc, rot_z)


def monitor(m, col, name, loc, rot_z=0.0, width=0.62, height=0.42, lift=0.12, body="aluminium"):
    """Cinema-display style screen on an aluminium foot. Screen faces -Y."""
    b = Builder()
    b.box((0.2, 0.2, 0.008), (0, 0.04, 0.004), m[body])
    b.box((0.18, 0.012, lift + height / 2), (0, 0.10, (lift + height / 2) / 2), m[body], rot=(-0.12, 0, 0))
    b.box((width, 0.035, height), (0, 0, lift + height / 2), m[body])
    b.box((width - 0.04, 0.002, height - 0.04), (0, -0.018, lift + height / 2), m["screen"])
    return b.build(name, col, loc, rot_z)


def tower(m, col, name, loc, rot_z=0.0, size=(0.21, 0.47, 0.51)):
    """Aluminium workstation tower."""
    w, d, h = size
    b = Builder()
    b.box((w, d, h), (0, 0, h / 2), m["aluminium"])
    b.box((w - 0.04, 0.004, h * 0.6), (0, -d / 2 - 0.002, h * 0.55), m["plastic_black"])
    return b.build(name, col, loc, rot_z)


def black_box(m, col, name, loc, size, rot_z=0.0, mat="plastic_black"):
    b = Builder()
    b.box(size, (0, 0, size[2] / 2), m[mat])
    return b.build(name, col, loc, rot_z)


def office_chair(m, col, name, loc, rot_z=0.0):
    b = Builder()
    for i in range(5):
        a = i * 2 * math.pi / 5
        b.box((0.32, 0.04, 0.03), (math.cos(a) * 0.16, math.sin(a) * 0.16, 0.06), m["plastic_black"], rot=(0, 0, a))
        b.cyl(0.025, 0.04, (math.cos(a) * 0.31, math.sin(a) * 0.31, 0.025), m["plastic_black"], segments=12)
    b.cyl(0.03, 0.36, (0, 0, 0.25), m["aluminium"], segments=16)
    b.box((0.48, 0.46, 0.08), (0, 0, 0.47), m["fabric_black"])
    b.box((0.44, 0.06, 0.52), (0, 0.24, 0.8), m["fabric_black"], rot=(-0.12, 0, 0))
    return b.build(name, col, loc, rot_z)


def floor_lamp(m, col, name, loc, height=1.75):
    b = Builder()
    b.box((0.3, 0.3, 0.02), (0, 0, 0.01), m["steel_black"])
    b.cyl(0.012, height - 0.3, (0, 0, (height - 0.3) / 2), m["steel_black"], segments=12)
    b.box((0.38, 0.38, 0.32), (0, 0, height - 0.16), m["lampshade"])
    return b.build(name, col, loc)


def tripod(m, col, name, loc, height=1.35):
    b = Builder()
    for i in range(3):
        a = i * 2 * math.pi / 3
        foot = Vector((math.cos(a) * 0.38, math.sin(a) * 0.38, 0))
        top = Vector((math.cos(a) * 0.04, math.sin(a) * 0.04, height - 0.04))
        leg = top - foot
        rot = leg.to_track_quat("Z", "Y").to_euler()
        b.cyl(0.014, leg.length, (foot + top) / 2, m["steel_black"], rot=tuple(rot), segments=10)
    b.box((0.09, 0.09, 0.08), (0, 0, height), m["plastic_black"])
    b.box((0.16, 0.1, 0.11), (0, 0, height + 0.1), m["plastic_black"])
    return b.build(name, col, loc)


def camera_body(m, col, name, loc, rot_z=0.0):
    b = Builder()
    b.box((0.15, 0.08, 0.11), (0, 0, 0.055), m["plastic_black"])
    b.cyl(0.04, 0.12, (0, -0.1, 0.05), m["plastic_black"], rot=(math.pi / 2, 0, 0))
    return b.build(name, col, loc, rot_z)


def flight_case(m, col, name, loc, size=(0.48, 0.3, 0.3), rot_z=0.0):
    w, d, h = size
    b = Builder()
    b.box(size, (0, 0, h / 2), m["aluminium"])
    for z in (0.02, h * 0.62, h - 0.02):
        b.box((w + 0.01, d + 0.01, 0.015), (0, 0, z), m["aluminium"])
    b.box((0.12, 0.02, 0.03), (0, -d / 2 - 0.015, h + 0.02), m["plastic_black"])
    return b.build(name, col, loc, rot_z)


def paper_stack(m, col, name, loc, size=(0.3, 0.22, 0.08), rot_z=0.0, rng=None):
    rng = rng or random.Random(0)
    b = Builder()
    z = 0
    while z < size[2]:
        t = rng.uniform(0.004, 0.02)
        b.box((size[0] + rng.uniform(-0.02, 0.02), size[1] + rng.uniform(-0.02, 0.02), t),
              (rng.uniform(-0.01, 0.01), rng.uniform(-0.01, 0.01), z + t / 2), m["paper"],
              rot=(0, 0, rng.uniform(-0.08, 0.08)))
        z += t
    return b.build(name, col, loc, rot_z)


def frame(m, col, name, loc, size, rot_z=0.0):
    """Framed picture; loc is the centre of the back face, art faces -Y."""
    w, h = size
    b = Builder()
    b.box((w, 0.04, h), (0, -0.02, 0), m["plastic_black"])
    b.box((w - 0.06, 0.002, h - 0.06), (0, -0.041, 0), m["paper"])
    b.box((w * 0.62, 0.002, h * 0.58), (0, -0.043, h * 0.03), m["art_dark"])
    return b.build(name, col, loc, rot_z)


def cardboard_box(m, col, name, loc, size, rot_z=0.0):
    w, d, h = size
    b = Builder()
    b.box(size, (0, 0, h / 2), m["cardboard"])
    b.box((w * 0.9, 0.01, 0.2), (0, -d / 2 - 0.05, h + 0.06), m["cardboard"], rot=(0.6, 0, 0))
    return b.build(name, col, loc, rot_z)


def bin_basket(m, col, name, loc):
    b = Builder()
    b.cyl(0.17, 0.4, (0, 0, 0.2), m["aluminium"], radius2=0.2, segments=28)
    return b.build(name, col, loc)
