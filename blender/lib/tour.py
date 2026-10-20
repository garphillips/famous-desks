"""Tour markup: viewpoint panorama cameras, hotspots, reference and plan cameras.

Everything the website needs is tagged with custom properties here, so the
export script can read it straight out of the .blend file.

Panorama convention: yaw 0 (the centre of every equirectangular image) faces
north (+Y). Yaw increases clockwise when seen from above (east = 90).
"""

import math

import bpy
from mathutils import Matrix, Vector

from .geo import collection, look_at

EYE_HEIGHT = 1.6


def _camera(name, col, loc):
    data = bpy.data.cameras.new(name)
    obj = bpy.data.objects.new(name, data)
    obj.location = loc
    col.objects.link(obj)
    return obj


def viewpoint(slug, title, xy, order, look_at=None, height=EYE_HEIGHT, res=(4096, 2048), face_size=None):
    """look_at: (x, y) the view initially faces on the website. face_size: cube face px
    for this viewpoint, instead of export.py's --face-size (e.g. sharper where people zoom in)."""
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
    if face_size:
        cam["face_size"] = face_size
    return cam


# Cube faces for sharp panoramas: six perspective cameras with a 90° field of view at the
# viewpoint. Per face: (forward, image right, image up) in Blender axes (x east, y north, z up).
# The four side faces stand upright; u is what you see tilting your head back from facing
# north (image top = south), d tilting it down from facing north (image top = north).
# Must match FACE_AXES in web/scripts/tile-pano.mjs and FACES in web/src/lib/viewer/cube.ts.
CUBE_FACES = {
    "n": ((0, 1, 0), (1, 0, 0), (0, 0, 1)),
    "e": ((1, 0, 0), (0, -1, 0), (0, 0, 1)),
    "s": ((0, -1, 0), (-1, 0, 0), (0, 0, 1)),
    "w": ((-1, 0, 0), (0, 1, 0), (0, 0, 1)),
    "u": ((0, 0, 1), (1, 0, 0), (0, -1, 0)),
    "d": ((0, 0, -1), (1, 0, 0), (0, 1, 0)),
}
CUBE_FACE_CAMERA = "vp_cube_face"


def cube_face_direction(face, a, b):
    """World direction through face coordinates a (right, -1..1) and b (up, -1..1).
    Pixel (col i, row j) of an N px face sits at a = 2(i+0.5)/N - 1, b = 1 - 2(j+0.5)/N."""
    f, r, u = (Vector(v) for v in CUBE_FACES[face])
    return (f + a * r + b * u).normalized()


def cube_face_camera(vp, face, size):
    """A square 90° perspective camera at viewpoint `vp` looking at cube face `face`.

    Reuses one temporary camera (CUBE_FACE_CAMERA); call remove_cube_face_camera() when done.
    Carries over the viewpoint's render tweaks (hide, exposure, brighten) and clipping.
    """
    cam = bpy.data.objects.get(CUBE_FACE_CAMERA)
    if cam is None:
        cam = bpy.data.objects.new(CUBE_FACE_CAMERA, bpy.data.cameras.new(CUBE_FACE_CAMERA))
        bpy.context.scene.collection.objects.link(cam)
    data = cam.data
    data.type = "PERSP"
    data.sensor_fit = "HORIZONTAL"
    data.sensor_width = 36
    data.angle = math.pi / 2  # exactly 90°: square faces meet edge to edge
    data.shift_x = data.shift_y = 0.0
    data.clip_start = vp.data.clip_start
    data.clip_end = vp.data.clip_end
    data.dof.use_dof = False
    f, r, u = (Vector(v) for v in CUBE_FACES[face])
    # Blender cameras look down local -Z with local +Y up and +X right.
    rot = Matrix((r, u, -f)).transposed()
    cam.matrix_world = Matrix.Translation(vp.matrix_world.translation) @ rot.to_4x4()
    for key in ("hide", "exposure", "brighten"):
        if key in cam:
            del cam[key]
        if key in vp:
            cam[key] = vp[key]
    cam["res"] = (size, size)
    cam["kind"] = "cube_face"
    return cam


def remove_cube_face_camera():
    cam = bpy.data.objects.get(CUBE_FACE_CAMERA)
    if cam is not None:
        data = cam.data
        bpy.data.objects.remove(cam)
        bpy.data.cameras.remove(data)


def hotspot(slug, title, loc, icon="eye", summary="", kind="hotspot", **extra):
    """icon: 'eye' (look closer), 'info' or 'music'. kind: 'hotspot' or 'door' (links to another space).

    extra: e.g. target='<space>' for doors, model='<object name>' to export
    that object as details/<slug>/model.glb for the 3D view, or
    focus=dict(viewpoint=<slug>, target=(x, y, z), fov=<degrees>): clicking the hotspot
    moves to that viewpoint and zooms in on the target, where the hotspot's items
    (objects tagged item_of=<slug>, e.g. lib/featured.py's books) can be picked, or
    playlist='<Spotify playlist id>' (with icon='music'): the hotspot opens its player.
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


def detail_camera(hotspot_slug, loc, target, lens=50, fstop=None, brighten=0.0, res=(1600, 1200)):
    """Close-up render for a hotspot's detail panel.

    Cameras are numbered per hotspot in the order they are added; export.py
    renders them to details/<hotspot>/closeup-<n>.webp. fstop enables a
    shallow depth of field focused on the target; brighten adds stops on top
    of the scene's exposure for this shot (e.g. objects in shadow on the floor).
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
    if brighten:
        cam["brighten"] = brighten
    cam["kind"] = "detail"
    cam["hotspot"] = hotspot_slug
    cam["index"] = index
    cam["res"] = res
    return cam
