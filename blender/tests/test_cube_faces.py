"""Checks the cube-face camera convention (no rendering, so no GPU queue needed):

    /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python-exit-code 1 \
        -P blender/tests/test_cube_faces.py

Each face camera must be a square 90° perspective camera at the viewpoint whose image right/up
and view direction match CUBE_FACES, the side faces' centres must sit at the yaw the website
uses (0 = north, clockwise: n 0, e 90, s 180, w -90), and neighbouring faces must share edges.
"""

import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.tour import CUBE_FACES, cube_face_camera, cube_face_direction, remove_cube_face_camera  # noqa: E402

vp = bpy.data.objects.new("vp_test", bpy.data.cameras.new("vp_test"))
vp.location = (0.35, -1.65, 1.6)
vp["hide"] = ["Ceiling"]
bpy.context.scene.collection.objects.link(vp)
bpy.context.view_layer.update()


def angle_diff(a, b):
    return abs(((a - b + 180) % 360) - 180)


EXPECTED_YAW = {"n": 0, "e": 90, "s": 180, "w": -90}
errors = []
for face in CUBE_FACES:
    cam = cube_face_camera(vp, face, 64)
    bpy.context.view_layer.update()
    m = cam.matrix_world
    assert (m.translation - vp.location).length < 1e-6, face
    assert abs(cam.data.angle - math.pi / 2) < 1e-6, face
    assert tuple(cam["res"]) == (64, 64) and list(cam["hide"]) == ["Ceiling"], face
    rot = m.to_3x3()
    # camera local: +X right, +Y up, -Z forward; image point (a, b) is local (a, b, -1)
    for a, b in ((0, 0), (1, 1), (-1, 1), (1, -1), (-0.3, 0.7)):
        got = (rot @ Vector((a, b, -1))).normalized()
        want = cube_face_direction(face, a, b)
        if (got - want).length > 1e-5:
            errors.append(f"{face} ({a}, {b}): camera {tuple(got)} != table {tuple(want)}")
    if face in EXPECTED_YAW:
        d = rot @ Vector((0, 0, -1))
        yaw = math.degrees(math.atan2(d.x, d.y))
        if angle_diff(yaw, EXPECTED_YAW[face]) > 1e-4:
            errors.append(f"{face}: centre yaw {yaw}, expected {EXPECTED_YAW[face]}")
        right = rot @ Vector((1, 0, 0))
        if angle_diff(math.degrees(math.atan2(right.x, right.y)), EXPECTED_YAW[face] + 90) > 1e-4:
            errors.append(f"{face}: image right is not clockwise (+90° yaw)")
remove_cube_face_camera()
assert "vp_cube_face" not in bpy.data.objects

# Faces meet edge to edge: the right edge of n is the left edge of e, and so on.
for f1, f2 in (("n", "e"), ("e", "s"), ("s", "w"), ("w", "n")):
    for b in (-1, 0, 0.5, 1):
        if (cube_face_direction(f1, 1, b) - cube_face_direction(f2, -1, b)).length > 1e-5:
            errors.append(f"{f1}/{f2} edge mismatch at b={b}")
# u's bottom edge is n's top edge; d's top edge is n's bottom edge
for a in (-1, 0, 1):
    if (cube_face_direction("u", a, -1) - cube_face_direction("n", a, 1)).length > 1e-5:
        errors.append(f"u/n edge mismatch at a={a}")
    if (cube_face_direction("d", a, 1) - cube_face_direction("n", a, -1)).length > 1e-5:
        errors.append(f"d/n edge mismatch at a={a}")

if errors:
    print("\n".join(errors))
    sys.exit(1)
print("cube faces OK")
