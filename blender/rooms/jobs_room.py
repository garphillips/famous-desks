"""The Jobs Room: blockout, built from the user's sketch (starter/sketch-floor-plan.png).

The sketch is the source of truth for layout (top of sketch = north). It is
roughly to scale: 1796 x 1200 px mapped to 6.4 m x 4.3 m, so 1 px ~ 3.56 mm.
Positions below are converted from sketch pixels with to_m(); sizes are
real-world furniture sizes where the sketch is only indicative.

- North wall: painted brick. Two windows (west and east of the desk). The desk's
  short end touches this wall between them, under a framed print.
- East wall: painted brick, one window in the northern half.
- West wall: plaster, bookshelf along most of its length.
- South wall: plaster, double door ("presumed": unknown in the photos, so kept
  plain; the website may restrict views towards it).
- Floor clutter along the bookshelf, south of the desk, and between the desk and
  the north-east window. Floor lamp south-east of the desk.
"""

import math
import random

import bpy

from lib import architecture, environment, furniture as f, hero, imported, materials, tour
from lib.geo import collection

W, D = 6.4, 4.3
SKETCH_PX = (1796, 1200)


def to_m(px, py):
    """Sketch pixel -> room metres (origin at room centre, +Y north)."""
    return px * W / SKETCH_PX[0] - W / 2, D / 2 - py * D / SKETCH_PX[1]


def span_x(px0, px1):
    (x0, _), (x1, _) = to_m(px0, 0), to_m(px1, 0)
    return (x0 + x1) / 2, x1 - x0


def span_y(py0, py1):
    (_, y0), (_, y1) = to_m(0, py0), to_m(0, py1)
    return (y0 + y1) / 2, y0 - y1


NW_WINDOW = span_x(232, 630)
NE_WINDOW = span_x(1280, 1678)
E_WINDOW = span_y(112, 510)
DOOR = span_x(368, 766)
BOOKSHELF = span_y(0, 975)
DESK_X = span_x(710, 1072)[0]

SPEC = {
    "slug": "jobs-room",
    "title": "The Jobs Room",
    "order": 1,
    "width": W,
    "depth": D,
    "height": 2.75,
    "wall_thickness": 0.42,
    "ceiling": {"joist_axis": "X", "joist_spacing": 0.55, "joist_depth": 0.2, "cross_beams": [-2.3]},
    "walls": {
        "N": {"finish": "brick_x", "openings": [
            {"kind": "window", "style": "steel", "center": NW_WINDOW[0], "width": NW_WINDOW[1],
             "sill": 0.85, "head": 2.3, "cols": 4, "rows": 4},
            {"kind": "window", "style": "steel", "center": NE_WINDOW[0], "width": NE_WINDOW[1],
             "sill": 0.85, "head": 2.3, "cols": 4, "rows": 4},
        ]},
        "E": {"finish": "brick_y", "openings": [
            {"kind": "window", "style": "steel", "center": E_WINDOW[0], "width": E_WINDOW[1],
             "sill": 0.85, "head": 2.3, "cols": 4, "rows": 4},
        ]},
        "S": {"finish": "plaster", "openings": [
            {"kind": "door", "center": DOOR[0], "width": DOOR[1], "sill": 0.0, "head": 2.1,
             "leaves": 2, "finish": "sash_white"},
        ]},
        "W": {"finish": "plaster"},
    },
}


# Shared positions (sections and the tour markup both use these)
WALL = D / 2  # north wall interior face
DESK_W, DESK_LEN = 0.9, 1.8
DISPLAY_LOC = (DESK_X - 0.05, WALL - 0.3, 0.74)
SOUTH_PILE = to_m(876, 753)  # floor clutter south of the desk (south photo foreground)
NE_PILE = to_m(1480, 273)  # between the desk and the north-east window
LAMP = to_m(1310, 705)
CAMERA_LOC = (SOUTH_PILE[0] - 0.1, SOUTH_PILE[1] - 0.45, 0.3)  # on the camera case
TRIPOD_LOC = (SOUTH_PILE[0] + 0.15, SOUTH_PILE[1] + 0.1, 0)


class Ctx:
    """What every section needs: materials and the target collections."""

    def __init__(self):
        self.m = materials.library()
        self.books = materials.book_materials()
        self.furn = collection("Furniture")
        self.props = collection("Props")


def build():
    c = Ctx()
    architecture.Room(SPEC, c.m).build()
    build_lighting(c)
    build_bookshelf(c)
    build_desk(c)
    build_clutter(c)
    build_lamp(c)
    build_tour(c)


# --- sections: each is owned by one area of work ------------------------------


def build_lighting(c):
    """Sky, sun, garden and exposure."""
    environment.build_outdoors(c.m)
    sky = 0.1  # physical sky strength; sun lamp and exposure follow it
    environment.build_world(strength=sky, sun_azimuth=200, sun_elevation=35)
    environment.build_sun(azimuth_deg=200, elevation_deg=35, strength=environment.SKY_SUN_RATIO * sky)
    bpy.context.scene.view_settings.exposure = 3.4
    bpy.context.scene["lamp_glow"] = 1.0  # warm floor-lamp glow (materials.finish_scene)


def build_bookshelf(c):
    """West wall bookshelf (front facing east), its books and what sits on top."""
    m, furn, props = c.m, c.furn, c.props
    shelf_depth = 0.34
    bays = 3
    bay_w = (BOOKSHELF[1] - 0.025 * (bays + 1)) / bays
    f.bookshelf(m, furn, c.books, "bookshelf", (-W / 2 + shelf_depth / 2, BOOKSHELF[0], 0),
                bays=[bay_w] * bays, shelves=[0.08, 0.46, 0.82, 1.16, 1.48, 1.80, 2.12],
                depth=shelf_depth, rot_z=math.pi / 2, seed=3)
    f.black_box(m, props, "basket", (-W / 2 + 0.2, 1.4, 2.145), (0.3, 0.6, 0.32), mat="wicker")
    f.black_box(m, props, "shelf_top_boxes", (-W / 2 + 0.2, 0.2, 2.145), (0.25, 0.45, 0.12))


def build_desk(c):
    """The desk: short end against the north wall between the two windows.
    Display at the wall end facing into the room, angled towards the chair on
    the desk's west side (where the man sits in the south-facing photo). Also
    the prints on the walls."""
    m, furn, props = c.m, c.furn, c.props
    rng = random.Random(7)
    desk_y = WALL - DESK_LEN / 2
    f.table(m, furn, "desk", (DESK_X, desk_y, 0), (DESK_W, DESK_LEN, 0.74), top="oak", frame="oak")
    hero.display(props, "display", DISPLAY_LOC, rot_z=-0.35, width=0.66, height=0.46)
    f.black_box(m, props, "speaker", (DESK_X + 0.28, WALL - 0.3, 0.74), (0.18, 0.2, 0.26))
    f.black_box(m, props, "keyboard", (DESK_X - 0.25, WALL - 0.5, 0.74), (0.42, 0.15, 0.03), rot_z=math.pi / 2 + 0.3)
    f.tower(m, props, "mac_pro", (DESK_X - 0.2, WALL - 0.45, 0), rot_z=math.pi / 2)
    for i, dy in enumerate([0.85, 1.15, 1.5]):
        f.paper_stack(m, props, f"papers_{i}", (DESK_X + rng.uniform(-0.15, 0.15), WALL - dy, 0.74),
                      rot_z=rng.uniform(-0.4, 0.4), size=(0.32, 0.24, rng.uniform(0.03, 0.12)), rng=rng)
    imported.office_chair(m, furn, "chair", (DESK_X - DESK_W / 2 - 0.4, WALL - 0.7, 0), rot_z=0.5)
    f.frame(m, props, "print_north", (DESK_X, WALL - 0.001, 1.85), (0.78, 0.62))
    f.frame(m, props, "print_west", (-W / 2 + 0.001, -1.75, 1.45), (0.6, 0.8), rot_z=math.pi / 2)  # faces east


def build_clutter(c):
    """Floor clutter: along the bookshelf, south of the desk, and by the north-east window."""
    m, props = c.m, c.props
    rng = random.Random(11)

    sx, _ = to_m(275, 0)
    for i, py in enumerate([180, 380, 560, 760, 880]):
        _, y = to_m(0, py)
        size = (rng.uniform(0.3, 0.55), rng.uniform(0.3, 0.6), rng.uniform(0.12, 0.4))
        f.black_box(m, props, f"shelf_pile_{i}", (sx + rng.uniform(-0.08, 0.08), y, 0), size,
                    rot_z=rng.uniform(-0.3, 0.3), mat=rng.choice(["plastic_black", "cardboard", "paper"]))

    cx, cy = SOUTH_PILE
    hero.tripod(props, "tripod", TRIPOD_LOC)
    f.cardboard_box(m, props, "box_1", (cx + 0.45, cy - 0.1, 0), (0.6, 0.45, 0.45), rot_z=0.1)
    f.black_box(m, props, "case_stack", (cx + 0.55, cy + 0.35, 0), (0.4, 0.3, 0.55))
    f.black_box(m, props, "floor_pile", (cx - 0.3, cy - 0.25, 0), (0.7, 0.45, 0.22), rot_z=0.2)
    imported.mesh_basket(m, props, "bin", (cx - 0.35, cy + 0.4, 0))
    f.flight_case(m, props, "camera_case", (cx - 0.1, cy - 0.45, 0), rot_z=-0.2)
    hero.camera(props, "camera", CAMERA_LOC, rot_z=0.3)

    nx, ny = NE_PILE
    f.monitor(m, props, "spare_display", (nx + 0.2, ny + 0.15, 0), rot_z=0.4)
    imported.white_drum(m, props, "white_drum", (nx - 0.35, ny + 0.3, 0))
    f.black_box(m, props, "ne_pile", (nx - 0.1, ny - 0.3, 0), (0.55, 0.4, 0.3), rot_z=0.15)


def build_lamp(c):
    imported.floor_lamp(c.m, c.furn, "floor_lamp", (*LAMP, 0))


def build_tour(c):
    """Viewpoints, hotspots, close-up cameras and reference cameras."""
    lx, ly = LAMP
    tour.viewpoint("office", "Office", (0.35, -1.65), 0, look_at=(DESK_X, WALL))
    tour.viewpoint("bookshelf", "Bookshelf", (-1.25, 0.3), 1, look_at=(-W / 2, 0.3))
    tour.viewpoint("desk", "Desk", (0.95, 0.55), 2, look_at=(DESK_X, WALL))
    tour.viewpoint("window", "Window", (2.15, -1.05), 3, look_at=(W / 2, E_WINDOW[0]))
    tour.viewpoint("entrance", "Entrance", (DOOR[0], -D / 2 + 0.6), 4, look_at=(DESK_X, WALL))

    tour.hotspot("bookshelf", "Bookshelf", (-W / 2 + 0.2, BOOKSHELF[0], 1.65), icon="info",
                 summary="Explore the collection of books, cameras and creative tools.")
    tour.hotspot("display", "The display", (DISPLAY_LOC[0], DISPLAY_LOC[1], 1.3), model="display")
    tour.hotspot("print", "The print", (DESK_X, WALL - 0.05, 2.25), icon="info")
    tour.hotspot("camera", "Camera", (CAMERA_LOC[0], CAMERA_LOC[1], 0.55), model="camera")
    tour.hotspot("tripod", "Tripod", (TRIPOD_LOC[0], TRIPOD_LOC[1], 1.6), model="tripod")
    tour.hotspot("east_window", "Garden window", (W / 2 - 0.1, E_WINDOW[0], 1.85))
    tour.hotspot("floor_lamp", "Floor lamp", (lx, ly, 1.75))
    tour.hotspot("entrance", "Entrance", (DOOR[0], -D / 2 + 0.05, 1.4), kind="door", icon="door",
                 target="hallway", arrive="door")

    # Close-ups for the detail panels (details/<hotspot>/closeup-<n>.webp)
    disp = DISPLAY_LOC
    tour.detail_camera("display", (disp[0] - 0.62, disp[1] - 0.95, 1.22), (disp[0], disp[1], 1.04),
                       lens=35, fstop=5.6)
    tour.detail_camera("display", (disp[0] - 0.8, disp[1] + 0.2, 1.08), (disp[0] - 0.02, disp[1] + 0.07, 0.94),
                       lens=32, fstop=5.6)
    cam_loc = CAMERA_LOC
    tour.detail_camera("camera", (cam_loc[0] + 0.38, cam_loc[1] - 0.24, 0.52),
                       (cam_loc[0] + 0.01, cam_loc[1] - 0.03, 0.355), lens=50, fstop=2.8, brighten=1.0)
    tour.detail_camera("camera", (cam_loc[0] - 0.38, cam_loc[1] + 0.24, 0.56),
                       (cam_loc[0], cam_loc[1], 0.35), lens=50, fstop=2.8, brighten=1.0)
    pod = TRIPOD_LOC
    tour.detail_camera("tripod", (pod[0] + 0.45, pod[1] - 0.55, 1.55), (pod[0], pod[1], 1.3),
                       lens=50, fstop=2.8, brighten=0.6)
    tour.detail_camera("tripod", (pod[0] + 1.0, pod[1] - 1.5, 0.85), (pod[0], pod[1], 0.68),
                       lens=35, brighten=0.4)
    tour.detail_camera("bookshelf", (-1.5, 0.75, 1.45), (-W / 2, 0.35, 1.25), lens=30)
    tour.detail_camera("print", (DESK_X + 0.05, 0.85, 1.85), (DESK_X, WALL, 1.85), lens=50)

    # Matches "Upscaled facing south.png" (looks north at the desk) and
    # "upscaled facing north.png" (looks west at the bookshelf)
    tour.reference_camera("ref_desk_photo", (0.4, -1.95, 1.75), (-0.2, D / 2, 0.75))
    tour.reference_camera("ref_bookshelf_photo", (2.6, 0.2, 1.5), (-W / 2, 0.5, 1.0))
    tour.plan_camera(W, D)
