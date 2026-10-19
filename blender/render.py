"""Render cameras from a built room.

    blender -b blender/build/jobs_room.blend -P blender/render.py -- \
        --cams ref_north,ref_south,plan --samples 64 --scale 100 --out blender/build/renders
"""

import argparse
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lib.render import configure_cycles, render_camera  # noqa: E402


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--cams", default="all", help="comma list of camera names, or 'all' / 'viewpoints' / 'reference'")
    p.add_argument("--samples", type=int, default=128)
    p.add_argument("--scale", type=int, default=100, help="resolution percentage")
    p.add_argument("--out", default=os.path.join(HERE, "build", "renders"))
    a = p.parse_args(argv)

    scene = bpy.context.scene
    configure_cycles(scene, a.samples)
    cams = [o for o in scene.objects if o.type == "CAMERA"]
    if a.cams == "viewpoints":
        cams = [c for c in cams if c.get("kind") == "viewpoint"]
    elif a.cams == "reference":
        cams = [c for c in cams if c.get("kind") in ("reference", "plan")]
    elif a.cams != "all":
        names = a.cams.split(",")
        cams = [c for c in cams if c.name in names]

    os.makedirs(a.out, exist_ok=True)
    for cam in cams:
        print(f"Rendering {cam.name}")
        print(f"  -> {render_camera(scene, cam, a.out, a.scale)}")


main()
