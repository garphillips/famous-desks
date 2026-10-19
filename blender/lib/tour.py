"""Tour markup: viewpoint panorama cameras, hotspots, reference and plan cameras.

Everything the website needs is tagged with custom properties here, so the
export script can read it straight out of the .blend file.

Panorama convention: yaw 0 (the centre of every equirectangular image) faces
north (+Y). Yaw increases clockwise when seen from above (east = 90).
"""

import math

import bpy
from mathutils import Vector

from .geo import collection, look_at

EYE_HEIGHT = 1.6


def _camera(name, col, loc):
    data = bpy.data.cameras.new(name)
    obj = bpy.data.objects.new(name, data)
    obj.location = loc
    col.objects.link(obj)
    return obj


def viewpoint(slug, title, xy, order, look_at=None, height=EYE_HEIGHT, res=(4096, 2048)):
    """look_at: (x, y) the view initially faces on the website."""
    cam = _camera(f"vp_{slug}", collection("Viewpoints"), (xy[0], xy[1], height))
    cam.data.type = "PANO"
    cam.data.panorama_type = "EQUIRECTANGULAR"
    cam.rotation_euler = (math.pi / 2, 0, 0)  # look north
    cam["kind"] = "viewpoint"
    cam["slug"] = slug
    cam["title"] = title
    cam["order"] = order
    cam["res"] = res
    if look_at:
        cam["look_at"] = look_at
    return cam


def hotspot(slug, title, loc, icon="eye", summary="", kind="hotspot", **extra):
    """icon: 'eye' (look closer) or 'info'. kind: 'hotspot' or 'door' (links to another space).

    extra: e.g. target='<space>' for doors, or model='<object name>' to export
    that object as details/<slug>/model.glb for the 3D view.
    """
    empty = bpy.data.objects.new(f"hs_{slug}", None)
    empty.empty_display_type = "SPHERE"
    empty.empty_display_size = 0.06
    empty.location = loc
    empty["kind"] = kind
    empty["slug"] = slug
    empty["title"] = title
    empty["icon"] = icon
    empty["summary"] = summary
    for k, v in extra.items():
        empty[k] = v
    collection("Hotspots").objects.link(empty)
    return empty


def reference_camera(name, loc, target, lens=22, res=(1600, 1092)):
    """Matches a reference photo, for comparing the model against it."""
    cam = _camera(name, collection("Reference cameras"), loc)
    cam.data.lens = lens
    cam.data.sensor_width = 36
    look_at(cam, target)
    cam["kind"] = "reference"
    cam["res"] = res
    return cam


def plan_camera(width, depth, margin=0.6, px=1600):
    """Top-down orthographic camera for the minimap floor plan."""
    cam = _camera("plan", collection("Reference cameras"), (0, 0, 10))
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = max(width, depth) + 2 * margin
    cam["kind"] = "plan"
    cam["res"] = (px, px)
    cam["hide"] = ["Ceiling"]
    cam["exposure"] = 0.0
    return cam


def detail_camera(hotspot_slug, loc, target, lens=50, fstop=None, exposure=None, res=(1600, 1200)):
    """Close-up render for a hotspot's detail panel.

    Cameras are numbered per hotspot in the order they are added; export.py
    renders them to details/<hotspot>/closeup-<n>.webp. fstop enables a
    shallow depth of field focused on the target; exposure overrides the
    scene's for this shot (e.g. objects sitting in shadow on the floor).
    """
    index = 1 + sum(1 for o in bpy.data.objects
                    if o.get("kind") == "detail" and o.get("hotspot") == hotspot_slug)
    cam = _camera(f"dc_{hotspot_slug}_{index}", collection("Detail cameras"), loc)
    cam.data.lens = lens
    cam.data.sensor_width = 36
    cam.data.clip_start = 0.02
    look_at(cam, target)
    if fstop:
        cam.data.dof.use_dof = True
        cam.data.dof.focus_distance = (cam.location - Vector(target)).length
        cam.data.dof.aperture_fstop = fstop
    if exposure is not None:
        cam["exposure"] = exposure
    cam["kind"] = "detail"
    cam["hotspot"] = hotspot_slug
    cam["index"] = index
    cam["res"] = res
    return cam
