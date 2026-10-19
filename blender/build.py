"""Build a room from its script and save the .blend.

    blender -b --factory-startup -P blender/build.py -- jobs_room
"""

import importlib
import json
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lib.geo import reset_scene  # noqa: E402
from lib.render import configure_cycles  # noqa: E402


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    room = args[0] if args else "jobs_room"
    module = importlib.import_module(f"rooms.{room}")

    scene = reset_scene()
    module.build()
    configure_cycles(scene)
    scene["space"] = module.SPEC["slug"]
    scene["space_title"] = module.SPEC["title"]
    scene["spec_json"] = json.dumps(module.SPEC)

    out = os.path.join(HERE, "build", f"{room}.blend")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"Saved {out}")


main()
