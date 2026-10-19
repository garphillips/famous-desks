"""Export a built room for the website: tour data, panoramas and floor plan.

    blender -b blender/build/jobs_room.blend -P blender/export.py -- [--no-render] [--samples 64] [--scale 100]

Writes content/spaces/<slug>/:
    space.json          viewpoints, hotspots (with yaw/pitch per viewpoint), plan mapping
    panos/<vp>.webp     equirectangular panoramas (centre = north, yaw clockwise)
    plan.webp           top-down floor plan for the minimap
and updates content/spaces/index.json (the list of all spaces).
"""

import argparse
import json
import math
import os
import sys

import bpy
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lib.render import configure_cycles, render_camera  # noqa: E402

CONTENT = os.path.join(os.path.dirname(HERE), "content", "spaces")
OCCLUSION_TOLERANCE = 0.4  # metres: hits this close to a hotspot count as the object itself


def yaw_pitch(origin, target):
    d = Vector(target) - Vector(origin)
    yaw = math.degrees(math.atan2(d.x, d.y))  # 0 = north, 90 = east
    pitch = math.degrees(math.atan2(d.z, math.hypot(d.x, d.y)))
    return round(yaw, 2), round(pitch, 2), round(d.length, 3)


def visible(scene, depsgraph, origin, target):
    d = Vector(target) - Vector(origin)
    hit, location, *_ = scene.ray_cast(depsgraph, Vector(origin), d.normalized(), distance=d.length)
    return not hit or (location - Vector(origin)).length >= d.length - OCCLUSION_TOLERANCE


def r3(v):
    return [round(c, 3) for c in v]


FOOTPRINT_COLLECTIONS = ("Furniture", "Props")


def floor_plan(scene, spec):
    """Line-drawing data for the minimap: room outline, openings, floor-standing footprints."""
    w, d = spec["width"], spec["depth"]
    openings = []
    for side, wall in spec["walls"].items():
        for o in wall.get("openings", []):
            openings.append({"wall": side, "kind": o["kind"], "center": round(o["center"], 3),
                             "width": round(o["width"], 3)})
    items = []
    for col_name in FOOTPRINT_COLLECTIONS:
        col = bpy.data.collections.get(col_name)
        for obj in col.objects if col else []:
            if obj.type != "MESH":
                continue
            corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
            if min(c.z for c in corners) > 0.05:
                continue  # not standing on the floor (e.g. on the desk)
            # bound_box corners 0,3,7,4 are the bottom face, in order
            poly = [corners[i] for i in (0, 3, 7, 4)]
            items.append({"name": obj.name, "points": [[round(p.x, 3), round(p.y, 3)] for p in poly]})
    return {"width": w, "depth": d, "wallThickness": spec["wall_thickness"],
            "openings": openings, "items": items}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--no-render", action="store_true", help="only write space.json")
    p.add_argument("--samples", type=int, default=64)
    p.add_argument("--scale", type=int, default=100)
    p.add_argument("--only", default="", help="comma list of viewpoint slugs to render (plan is skipped)")
    a = p.parse_args(argv)

    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    slug, title = scene["space"], scene["space_title"]
    out = os.path.join(CONTENT, slug)
    os.makedirs(os.path.join(out, "panos"), exist_ok=True)

    viewpoints = sorted(
        (o for o in scene.objects if o.get("kind") == "viewpoint"), key=lambda o: o["order"]
    )
    hotspots = [o for o in scene.objects if o.name.startswith("hs_")]
    plan = scene.objects["plan"]

    data = {
        "slug": slug,
        "title": title,
        "plan": {"image": "plan.webp", "center": [0, 0], "size": round(plan.data.ortho_scale, 3)},
        "floorPlan": floor_plan(scene, json.loads(scene["spec_json"])),
        "viewpoints": [],
        "hotspots": [],
    }

    for vp in viewpoints:
        entry = {
            "slug": vp["slug"],
            "title": vp["title"],
            "position": r3(vp.location),
            "pano": f"panos/{vp['slug']}.webp",
            "initialYaw": 0,
        }
        if "look_at" in vp:
            tx, ty = vp["look_at"]
            entry["initialYaw"] = yaw_pitch(vp.location, (tx, ty, vp.location.z))[0]
        data["viewpoints"].append(entry)

    for hs in hotspots:
        views = {}
        for vp in viewpoints:
            if not visible(scene, depsgraph, vp.location, hs.location):
                continue
            yaw, pitch, dist = yaw_pitch(vp.location, hs.location)
            if dist > 0.3:
                views[vp["slug"]] = {"yaw": yaw, "pitch": pitch, "distance": dist}
        entry = {
            "slug": hs["slug"],
            "title": hs["title"],
            "kind": hs["kind"],
            "icon": hs["icon"],
            "summary": hs.get("summary", ""),
            "position": r3(hs.location),
            "views": views,
        }
        if hs.get("target") is not None:
            entry["target"] = hs["target"]
        data["hotspots"].append(entry)

    with open(os.path.join(out, "space.json"), "w") as fh:
        json.dump(data, fh, indent=2)
    print(f"Wrote {os.path.join(out, 'space.json')}")

    index_path = os.path.join(CONTENT, "index.json")
    index = {"spaces": []}
    if os.path.exists(index_path):
        with open(index_path) as fh:
            index = json.load(fh)
    index["spaces"] = [s for s in index["spaces"] if s["slug"] != slug] + [{"slug": slug, "title": title}]
    with open(index_path, "w") as fh:
        json.dump(index, fh, indent=2)

    if a.no_render:
        return
    configure_cycles(scene, a.samples)
    only = [s for s in a.only.split(",") if s]
    if not only:
        render_camera(scene, plan, out, filename="plan", fmt="WEBP")
    for vp in viewpoints:
        if only and vp["slug"] not in only:
            continue
        print(f"Rendering panorama {vp['slug']}")
        render_camera(scene, vp, os.path.join(out, "panos"), a.scale, filename=vp["slug"], fmt="WEBP")


main()
