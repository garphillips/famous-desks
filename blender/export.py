"""Export a built room for the website: tour data, panoramas and floor plan.

    blender -b blender/build/jobs_room.blend -P blender/export.py -- [--no-render] [--only-details]
        [--samples 64] [--scale 100] [--only office,desk] [--face-size 2560] [--tile-size 512]
        [--equirect-width 4096] [--detail-width 2400]

Writes content/spaces/<slug>/:
    space.json          viewpoints, hotspots (with yaw/pitch per viewpoint), plan mapping
    panos/<vp>/         cube-face tile pyramid + preview strip (see PanoTiles in web/src/lib/types.ts)
    panos/<vp>.webp     equirectangular panorama (centre = north, yaw clockwise), the fallback
    plan.webp           top-down floor plan for the minimap
    details/<hotspot>/closeup-<n>.webp   close-up renders from the hotspot's detail cameras
    details/<hotspot>/model.glb          the hotspot's `model` object, for the 3D view
    details/<hotspot>/items/<item>/      a featured item (lib/featured.py): cover.webp, spine.webp,
                                         and patch-<face>.webp: the focus viewpoint's panorama with
                                         the item taken out, for where it leaves its slot
and updates content/spaces/index.json (the list of all spaces).

Panoramas are rendered as six 90° perspective cube faces (--face-size px square, default
2560 ~ the sharpness of an 8192x4096 equirect: 8192/pi) into blender/build/cube/<slug>/<vp>/,
(or the viewpoint's own face_size), then web/scripts/tile-pano.mjs (Node + sharp; needs `npm ci` in web/) cuts them into 512 px
WebP tiles at q85 per level (512, 1024, 2048, 2560), a 6x256 preview strip, and reprojects
the 4096 equirect fallback. Tiling runs in the background while the next viewpoint renders.
"""

import argparse
import copy
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from lib.render import configure_cycles, render_camera  # noqa: E402
from lib.tour import CUBE_FACES, cube_face_camera, remove_cube_face_camera  # noqa: E402

ROOT = os.path.dirname(HERE)
CONTENT = os.path.join(ROOT, "content", "spaces")
CUBE_BUILD = os.path.join(HERE, "build", "cube")
TILER = os.path.join(ROOT, "web", "scripts", "tile-pano.mjs")
OCCLUSION_TOLERANCE = 0.4  # metres: hits this close to a hotspot count as the object itself


def yaw_pitch(origin, target):
    d = Vector(target) - Vector(origin)
    yaw = math.degrees(math.atan2(d.x, d.y))  # 0 = north, 90 = east
    pitch = math.degrees(math.atan2(d.z, math.hypot(d.x, d.y)))
    return round(yaw, 2), round(pitch, 2), round(d.length, 3)


def yaw_range(origin, a, b):
    """The directions (degrees, clockwise from `from` to `to`) that look past the wall a-b."""
    ya = yaw_pitch(origin, (a[0], a[1], origin.z))[0]
    yb = yaw_pitch(origin, (b[0], b[1], origin.z))[0]
    d = (yb - ya + 180) % 360 - 180  # the wall's arc, the short way from a to b
    start, end = (ya + d, ya + 360) if d > 0 else (ya, ya + 360 + d)
    if start > 180:
        start, end = start - 360, end - 360
    return [round(start, 2), round(end, 2)]


VERSIONED = (".webp", ".png", ".jpg", ".glb")


def file_hash(*paths):
    h = hashlib.sha1()
    for path in paths:
        with open(path, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:10]


def versioned(value, out):
    """A copy of the space data with ?v=<hash> on every image and model path, and a `version`
    on each tile pyramid, so browsers and Cloudflare can cache them for good: a re-render
    changes the file, so the address changes too."""
    if isinstance(value, dict):
        value = {k: versioned(v, out) for k, v in value.items()}
        if "levels" in value and "path" in value and "tileSize" in value:
            folder = os.path.join(out, value["path"])
            files = sorted(os.path.join(dp, f) for dp, _, fs in os.walk(folder) for f in fs)
            value["version"] = file_hash(*files)
        return value
    if isinstance(value, list):
        return [versioned(v, out) for v in value]
    if isinstance(value, str) and "?" not in value and value.endswith(VERSIONED):
        path = os.path.join(out, value)
        if os.path.isfile(path):
            return f"{value}?v={file_hash(path)}"
    return value


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


def space_title(slug):
    """Title of another space: from content/spaces/index.json, else its room script's SPEC."""
    try:
        with open(os.path.join(CONTENT, "index.json")) as fh:
            for s in json.load(fh)["spaces"]:
                if s["slug"] == slug:
                    return s["title"]
    except (OSError, ValueError, KeyError):
        pass
    try:
        import importlib
        return importlib.import_module(f"rooms.{slug.replace('-', '_')}").SPEC["title"]
    except Exception:  # noqa: BLE001 - unknown room: the website falls back to the slug
        return ""


def export_model(obj, path):
    """Write one object as a self-contained .glb: real-world metres, Y-up,
    modifiers and transform applied, centred horizontally and resting on y=0,
    facing +Z (its Blender front, -Y). Room position and rotation are dropped."""
    copy = obj.copy()
    copy.data = obj.data.copy()
    bpy.context.scene.collection.objects.link(copy)
    copy.matrix_world = Matrix.Diagonal((*obj.matrix_world.to_scale(), 1.0))
    bpy.context.view_layer.update()
    corners = [copy.matrix_world @ Vector(c) for c in copy.bound_box]
    lo = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    hi = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    copy.location = (-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z)
    bpy.context.view_layer.update()
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    copy.select_set(True)
    bpy.context.view_layer.objects.active = copy
    bpy.ops.export_scene.gltf(
        filepath=path, export_format="GLB", use_selection=True, export_apply=True,
        export_yup=True, export_cameras=False, export_lights=False, export_extras=False,
        export_animations=False, export_materials="EXPORT")
    mesh = copy.data
    bpy.data.objects.remove(copy)
    bpy.data.meshes.remove(mesh)
    print(f"Wrote {path} ({os.path.getsize(path) / 1e6:.2f} MB)")


PATCH_PAD = 24  # px around an item's footprint on a face, for the website to feather


def item_patches(vp, obj, size):
    """Where `obj` appears on the cube faces of viewpoint `vp` at `size` px:
    {face: [x, y, w, h]} pixel rectangles (top-left origin), padded and clipped."""
    origin = vp.matrix_world.translation
    corners = [obj.matrix_world @ Vector(c) - origin for c in obj.bound_box]
    out = {}
    for face, (f, r, u) in CUBE_FACES.items():
        f, r, u = Vector(f), Vector(r), Vector(u)
        if any(c.dot(f) <= 0.01 for c in corners):
            continue
        xs = [(c.dot(r) / c.dot(f) + 1) / 2 * size for c in corners]
        ys = [(1 - c.dot(u) / c.dot(f)) / 2 * size for c in corners]
        x0, x1 = max(0, math.floor(min(xs)) - PATCH_PAD), min(size, math.ceil(max(xs)) + PATCH_PAD)
        y0, y1 = max(0, math.floor(min(ys)) - PATCH_PAD), min(size, math.ceil(max(ys)) + PATCH_PAD)
        if x1 - x0 > PATCH_PAD and y1 - y0 > PATCH_PAD:
            out[face] = [x0, y0, x1 - x0, y1 - y0]
    return out


def render_patches(scene, vp, items, out, size, quality=92):
    """For each item: the viewpoint's cube faces where it shows, re-rendered without it,
    cropped to its rectangle (details/<hotspot>/items/<item>/patch-<face>.webp)."""
    render = scene.render
    try:
        for obj in items:
            folder = os.path.join(out, "details", obj["item_of"], "items", obj["item"])
            os.makedirs(folder, exist_ok=True)
            obj.hide_render = True
            for face, (x, y, w, h) in item_patches(vp, obj, size).items():
                cam = cube_face_camera(vp, face, size)
                render.use_border = True
                render.use_crop_to_border = True
                render.border_min_x, render.border_max_x = x / size, (x + w) / size
                render.border_min_y, render.border_max_y = 1 - (y + h) / size, 1 - y / size
                t0 = time.time()
                render_camera(scene, cam, folder, filename=f"patch-{face}", fmt="WEBP", quality=quality)
                print(f"Patch {obj['item']}/{face} {w}x{h}: {time.time() - t0:.1f} s")
            obj.hide_render = False
    finally:
        render.use_border = False
        render.use_crop_to_border = False
        remove_cube_face_camera()
        scene.camera = vp


def item_entry(obj, hs_slug, out):
    """space.json entry for a featured item (see HotspotItem in web/src/lib/types.ts)."""
    slug = obj["item"]
    rel = f"details/{hs_slug}/items/{slug}"
    folder = os.path.join(out, "details", hs_slug, "items", slug)
    os.makedirs(folder, exist_ok=True)
    for name in ("cover.webp", "spine.webp"):
        shutil.copyfile(os.path.join(obj["item_art"], name), os.path.join(folder, name))
    data = json.loads(obj["item_json"])
    loc, rot, _ = obj.matrix_world.decompose()
    t, h, d = obj["dims"]
    return {
        "slug": slug,
        **data,
        "cover": f"{rel}/cover.webp",
        "spine": f"{rel}/spine.webp",
        "size": [round(t, 4), round(h, 4), round(d, 4)],
        "position": [round(c, 4) for c in loc],
        "rotation": [round(c, 6) for c in rot],
        "patches": [],
    }


def render_cube_faces(scene, vp, folder, size):
    """Renders the six cube faces of viewpoint `vp` as <folder>/<face>.png."""
    os.makedirs(folder, exist_ok=True)
    try:
        for face in CUBE_FACES:
            cam = cube_face_camera(vp, face, size)
            render_camera(scene, cam, folder, filename=face, fmt="PNG")
    finally:
        remove_cube_face_camera()
        scene.camera = vp


def start_tiling(faces, out_dir, equirect, a):
    """Runs the tiler in the background; returns the process."""
    node = shutil.which("node")
    if not node:
        raise SystemExit("export.py: `node` not found on PATH; it is needed to tile the panoramas")
    if not os.path.isdir(os.path.join(ROOT, "web", "node_modules", "sharp")):
        raise SystemExit("export.py: sharp is missing; run `npm ci` in web/ first")
    cmd = [node, TILER, "--faces", faces, "--out", out_dir, "--equirect", equirect,
           "--equirect-width", str(a.equirect_width), "--tile", str(a.tile_size), "--quality", "85"]
    return subprocess.Popen(cmd)


def tiles_entry(out, vp_slug):
    """The viewpoint's `tiles` field, from the tiler's panos/<vp>/tiles.json (if tiled)."""
    try:
        with open(os.path.join(out, "panos", vp_slug, "tiles.json")) as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        return None
    path = f"panos/{vp_slug}"
    return {"path": path, "faceSize": meta["faceSize"], "tileSize": meta["tileSize"],
            "levels": meta["levels"], "bleed": meta["bleed"], "format": meta["format"],
            "preview": f"{path}/preview.webp", "previewSize": meta["previewSize"]}


def export_details(scene, hotspots, out, render, scale, width=2400, quality=88):
    """Close-up renders and glTF models per hotspot. Returns {slug: detail entry}.
    Close-ups are rendered `width` px wide (keeping the camera's aspect) x scale%."""
    cams = sorted((o for o in scene.objects if o.get("kind") == "detail"),
                  key=lambda o: (o["hotspot"], o["index"]))
    details = {}
    for hs in hotspots:
        slug = hs["slug"]
        rel = f"details/{slug}"
        folder = os.path.join(out, "details", slug)
        images = []
        for cam in (c for c in cams if c["hotspot"] == slug):
            name = f"closeup-{cam['index']}"
            path = os.path.join(folder, f"{name}.webp")
            if render:
                os.makedirs(folder, exist_ok=True)
                print(f"Rendering close-up {slug}/{name}")
                pct = max(1, round(scale * width / cam["res"][0]))
                t0 = time.time()
                render_camera(scene, cam, folder, pct, filename=name, fmt="WEBP", quality=quality)
                print(f"Close-up {slug}/{name}: {time.time() - t0:.1f} s")
            if os.path.exists(path):
                images.append(f"{rel}/{name}.webp")
        detail = {"images": images}
        model_name = hs.get("model")
        if model_name:
            obj = bpy.data.objects.get(model_name)
            if obj is None:
                print(f"WARNING: hotspot {slug}: no object called {model_name!r}")
            else:
                os.makedirs(folder, exist_ok=True)
                export_model(obj, os.path.join(folder, "model.glb"))
                detail["model"] = f"{rel}/model.glb"
        if images or "model" in detail:
            details[slug] = detail
    return details


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--no-render", action="store_true", help="only write space.json")
    p.add_argument("--samples", type=int, default=64)
    p.add_argument("--scale", type=int, default=100)
    p.add_argument("--only", default="", help="comma list of viewpoint slugs to render (plan is skipped)")
    p.add_argument("--only-details", action="store_true",
                   help="re-export close-ups and models (and space.json) without rendering panoramas")
    p.add_argument("--face-size", type=int, default=2560, help="cube face px (2560 ~ an 8192 equirect)")
    p.add_argument("--tile-size", type=int, default=512)
    p.add_argument("--equirect-width", type=int, default=4096, help="width of the fallback equirect")
    p.add_argument("--detail-width", type=int, default=2400, help="close-up width before --scale")
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
        if "arrive_facing" in scene:
            yaw, pitch, _ = yaw_pitch(vp.location, tuple(scene["arrive_facing"]))
            entry["arrive"] = {"yaw": yaw, "pitch": pitch}
        if "unseen_wall" in scene:
            ax, ay, bx, by = scene["unseen_wall"]
            entry["yawRange"] = yaw_range(vp.location, (ax, ay), (bx, by))
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
        focus = hs.get("focus")
        if focus:
            fvp = next(v for v in viewpoints if v["slug"] == focus["viewpoint"])
            yaw, pitch, _ = yaw_pitch(fvp.location, focus["target"])
            entry["focus"] = {"viewpoint": focus["viewpoint"], "yaw": yaw, "pitch": pitch, "fov": focus["fov"]}
            items = sorted((o for o in scene.objects if o.get("item_of") == hs["slug"]),
                           key=lambda o: o["item_order"])
            entry["items"] = [item_entry(o, hs["slug"], out) for o in items]
        if hs.get("playlist"):
            entry["playlist"] = hs["playlist"]
        if hs.get("target") is not None:
            entry["target"] = hs["target"]
            if hs["target"]:
                entry["targetTitle"] = space_title(hs["target"])
            if hs.get("arrive"):
                entry["arrive"] = hs["arrive"]  # viewpoint slug to land at in the target space
        data["hotspots"].append(entry)

    if not a.no_render:
        configure_cycles(scene, a.samples)
    # --only re-renders a few panoramas: keep the existing close-ups
    render_details = not a.no_render and (a.only_details or not a.only)
    details = export_details(scene, hotspots, out, render=render_details, scale=a.scale,
                             width=a.detail_width)
    for entry in data["hotspots"]:
        if entry["slug"] in details:
            entry["detail"] = details[entry["slug"]]

    def face_size(vp):
        # --scale shrinks the faces too, but never below one tile
        return max(a.tile_size, round(vp.get("face_size", a.face_size) * a.scale / 100))

    def write_space():
        # patches: only those rendered for the focus viewpoint's current face size
        for entry in data["hotspots"]:
            if "focus" not in entry:
                continue
            fvp = next(v for v in viewpoints if v["slug"] == entry["focus"]["viewpoint"])
            size = face_size(fvp)
            for item in entry["items"]:
                obj = next(o for o in scene.objects if o.get("item") == item["slug"])
                item["patches"] = []
                for face, rect in item_patches(fvp, obj, size).items():
                    rel = f"details/{entry['slug']}/items/{item['slug']}/patch-{face}.webp"
                    if os.path.exists(os.path.join(out, rel)):
                        item["patches"].append({"viewpoint": fvp["slug"], "face": face, "faceSize": size,
                                                "rect": rect, "image": rel})
        for entry in data["viewpoints"]:
            tiles = tiles_entry(out, entry["slug"])
            if tiles:
                entry["tiles"] = tiles
            else:
                entry.pop("tiles", None)
        with open(os.path.join(out, "space.json"), "w") as fh:
            json.dump(versioned(copy.deepcopy(data), out), fh, indent=2)
        print(f"Wrote {os.path.join(out, 'space.json')}")

    write_space()

    index_path = os.path.join(CONTENT, "index.json")
    index = {"spaces": []}
    if os.path.exists(index_path):
        with open(index_path) as fh:
            index = json.load(fh)
    order = json.loads(scene["spec_json"]).get("order")
    me = {"slug": slug, "title": title, **({"order": order} if order is not None else {})}
    index["spaces"] = [s for s in index["spaces"] if s["slug"] != slug] + [me]
    # stable however the spaces were exported: by SPEC "order", then unordered ones by slug
    index["spaces"].sort(key=lambda s: (s.get("order") is None, s.get("order") or 0, s["slug"]))
    with open(index_path, "w") as fh:
        json.dump(index, fh, indent=2)

    if a.no_render or a.only_details:
        return
    only = [s for s in a.only.split(",") if s]
    if not only:
        render_camera(scene, plan, out, filename="plan", fmt="WEBP")
    tilers = []
    for vp in viewpoints:
        if only and vp["slug"] not in only:
            continue
        size = face_size(vp)
        faces = os.path.join(CUBE_BUILD, slug, vp["slug"])
        print(f"Rendering panorama {vp['slug']}: 6 cube faces of {size} px")
        t0 = time.time()
        render_cube_faces(scene, vp, faces, size)
        print(f"Panorama {vp['slug']}: rendered in {time.time() - t0:.1f} s")
        tilers.append(start_tiling(faces, os.path.join(out, "panos", vp["slug"]),
                                   os.path.join(out, "panos", f"{vp['slug']}.webp"), a))
        items = [o for o in scene.objects if o.get("item_of")
                 and (bpy.data.objects[f"hs_{o['item_of']}"].get("focus") or {}).get("viewpoint") == vp["slug"]]
        if items:
            render_patches(scene, vp, items, out, size)
    failed = [t for t in tilers if t.wait() != 0]
    write_space()
    if failed:
        raise SystemExit(f"export.py: tiling failed for {len(failed)} panorama(s)")


main()
