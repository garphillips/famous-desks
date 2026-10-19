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
from mathutils import Matrix, Vector

from lib import architecture, clutter, environment, furniture as f, hero, materials, tour
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
    f.office_chair(m, furn, "chair", (DESK_X - DESK_W / 2 - 0.4, WALL - 0.7, 0), rot_z=0.5)
    f.frame(m, props, "print_north", (DESK_X, WALL - 0.001, 1.85), (0.78, 0.62))
    f.frame(m, props, "print_west", (-W / 2 + 0.001, -1.75, 1.45), (0.6, 0.8), rot_z=math.pi / 2)  # faces east


def build_clutter(c):
    """Floor clutter: along the bookshelf, south of the desk, and by the north-east window,
    plus the cables and loose paper between them (lib.clutter)."""
    m, props = c.m, c.props
    cm = clutter.library()
    rng = random.Random(11)

    sx, _ = to_m(275, 0)
    for i, py in enumerate([180, 380, 560, 760, 880]):
        _, y = to_m(0, py)
        size = (rng.uniform(0.3, 0.55), rng.uniform(0.3, 0.6), rng.uniform(0.12, 0.4))
        loc = (sx + rng.uniform(-0.08, 0.08), y, 0)
        rot = rng.uniform(-0.3, 0.3)
        rng.choice("abc")  # keeps the old random sequence, so the footprints don't move
        _shelf_pile(cm, props, f"shelf_pile_{i}", i, size, loc, rot)

    cx, cy = SOUTH_PILE
    hero.tripod(props, "tripod", TRIPOD_LOC)
    b = clutter.Pile(cm, random.Random(21))
    clutter.carton(b, (0.6, 0.45, 0.45), flaps=[(-1.2, 0.8), (0.35, -2.2), (1.65, -0.4), (1.2, -1.2)])
    b.build("box_1", props, (cx + 0.47, cy - 0.21, 0), 0.1)  # just clear of the tripod's east leg
    _case_stack(cm, props, "case_stack", (cx + 0.55, cy + 0.35, 0))
    _floor_pile(cm, props, "floor_pile", (cx - 0.3, cy - 0.25, 0))
    f.bin_basket(m, props, "bin", (cx - 0.35, cy + 0.4, 0))
    f.flight_case(m, props, "camera_case", (cx - 0.1, cy - 0.45, 0), rot_z=-0.2)
    hero.camera(props, "camera", CAMERA_LOC, rot_z=0.3)

    nx, ny = NE_PILE
    _spare_display(cm, props, "spare_display", (nx + 0.2, ny + 0.15, 0), 0.4 + math.pi)
    f.bin_basket(m, props, "white_drum", (nx - 0.35, ny + 0.3, 0))
    props.objects["white_drum"].scale = (1.0, 1.0, 1.4)
    _ne_pile(cm, props, "ne_pile", (nx - 0.1, ny - 0.3, 0), 0.15)

    loose = collection("Floor clutter")
    _cables(cm, loose)
    _loose_paper(cm, loose, random.Random(5))


def _shelf_pile(m, col, name, i, size, loc, rot):
    w, d, h = size
    b = clutter.Pile(m, random.Random(100 + i))
    if i == 0:
        top = clutter.paper_pile(b, (w * 0.8, d * 0.6, h * 0.7), (0, -d * 0.15, 0), 0.1)
        clutter.disc_stack(b, (w * 0.15, d * 0.3, 0), 6, 0.3)
        clutter.disc_stack(b, (0.0, -d * 0.1, top), 3, -0.4, dvd=False)
    elif i == 1:
        clutter.paper_bag(b, (0.32, 0.12, 0.38), (0, d * 0.15, 0), 0.2)
        clutter.paper_bag(b, (0.26, 0.1, 0.3), (-w * 0.1, -d * 0.25, 0), -0.25, m["bag_kraft"], tilt=-0.18)
        b.lump((0.22, 0.2, 0.12), (w * 0.25, -d * 0.1, 0), m["poly_bag"], 7.0, folds=0.6)
    elif i == 2:
        clutter.carton(b, (w * 0.95, d * 0.9, h), label=False)
    elif i == 3:
        z = 0.0
        for k in range(3):
            sw, sd, sh = w * (0.95 - 0.15 * k), d * (0.75 - 0.1 * k), 0.08 + 0.04 * (k % 2)
            clutter.case(b, (sw, sd, sh), (0.01 * k, -d * 0.1, z), b.rng.uniform(-0.15, 0.15), handle=k == 2)
            z += sh * 1.02 + 0.012
        bag = Matrix.Translation(loc) @ Matrix.Rotation(rot, 4, "Z") @ Vector((w * 0.05, d * 0.42, 0))
        clutter.model(col, "trash_bag", "trashbag", "trashbag_1k.gltf", bag, rot + 2.0, scale=0.75)
    else:
        clutter.paper_pile(b, (w * 0.7, d * 0.5, h * 0.35), (-w * 0.1, d * 0.2, 0), -0.2, mags=0.8)
        clutter.carton(b, (0.3, 0.24, 0.2), (w * 0.15, -d * 0.25, 0), 0.3, stuffing=False)
    b.build(name, col, loc, rot)


def _case_stack(m, col, name, loc):
    """Black cases and boxes stacked by the open box, discs on top."""
    b = clutter.Pile(m, random.Random(31))
    z = 0.0
    for k, (sw, sd, sh) in enumerate([(0.4, 0.3, 0.12), (0.36, 0.27, 0.1), (0.38, 0.26, 0.09), (0.3, 0.22, 0.08)]):
        clutter.case(b, (sw, sd, sh), (b.rng.uniform(-0.02, 0.02), 0, z), b.rng.uniform(-0.12, 0.12),
                     handle=k == 1, mat=m["case_shell"] if k % 2 == 0 else m["plastic_black"])
        z += sh * 1.02 + (0.012 if k == 1 else 0.0)
    clutter.disc_stack(b, (0.03, 0.0, z), 6, 0.15)
    b.build(name, col, loc, 0.05)


def _floor_pile(m, col, name, loc):
    """Foreground heap, wrapped around the camera case and the bin: printer, paper and
    magazines, a grey carrier bag and a black bag."""
    b = clutter.Pile(m, random.Random(41))
    clutter.printer(b, (-0.28, -0.19, 0), 0.35)
    top = clutter.paper_pile(b, (0.3, 0.3, 0.09), (0.07, 0.17, 0), -0.3, mags=0.6)
    clutter.disc_stack(b, (0.05, 0.15, top), 3, 0.5, dvd=False)
    clutter.paper_bag(b, (0.3, 0.1, 0.34), (-0.25, 0.17, 0), 0.15, m["bag_grey"], tilt=-0.2)
    clutter.jacket_heap(b, (-0.25, -0.5, 0), (0.38, 0.26, 0.12), 2.6, m["fabric_black"])
    b.build(name, col, loc)


def _ne_pile(m, col, name, loc, rot):
    """By the north-east window: a black case with the scanner and some paper on it."""
    b = clutter.Pile(m, random.Random(51))
    clutter.case(b, (0.55, 0.4, 0.22), (0, 0, 0), 0.0, handle=False)
    clutter.scanner(b, (-0.08, 0.0, 0.232), 0.08, lid=0.06)
    clutter.paper_pile(b, (0.22, 0.3, 0.04), (0.17, -0.02, 0.232), 0.3, mags=0.5)
    b.build(name, col, loc, rot)


def _spare_display(m, col, name, loc, rot):
    """A second display on the floor, switched off and turned to the window."""
    obj = hero.display(col, name, loc, rot_z=rot, width=0.6, height=0.42)
    mats = obj.data.materials
    for i, mat in enumerate(mats):
        if mat and mat.name == "hero_screen_image":
            mats[i] = m["screen"]


def _cables(m, col):
    """Display -> computer, computer and power strip -> wall, speaker and lamp -> strip."""
    x0, x1 = DESK_X - DESK_W / 2, DESK_X + DESK_W / 2
    dx, dy, dz = DISPLAY_LOC
    top = dz + 0.006
    strip = (DESK_X + 0.2, WALL - 0.5)
    sock = (DESK_X + 0.05, WALL - 0.012, 0.28)
    tower_back = DESK_X - 0.2 - 0.24
    lx, ly = LAMP
    clutter.power_strip(col, m, "power_strip", (*strip, 0), 0.35)
    clutter.wall_socket(col, m, "wall_socket", sock, math.pi)
    sr = Vector((math.cos(0.35), math.sin(0.35)))  # along the strip

    def plug(i):
        return (strip[0] + sr.x * (-0.11 + 0.06 * i), strip[1] + sr.y * (-0.11 + 0.06 * i), 0.06)

    cables = [
        ("cable_display", "cable_white", 0.004, [
            (dx + 0.04, dy + 0.11, dz + 0.2), (dx + 0.06, dy + 0.18, dz + 0.06), (dx + 0.02, dy + 0.24, top),
            (dx - 0.2, dy + 0.22, top), (x0 + 0.02, dy + 0.12, top), (x0 - 0.02, dy + 0.1, dz - 0.05),
            (x0 - 0.04, dy + 0.06, 0.35), (x0 - 0.06, dy, 0.08), (x0 - 0.1, dy - 0.12, 0),
            (tower_back - 0.08, WALL - 0.42, 0), (tower_back - 0.02, WALL - 0.4, 0.12),
            (tower_back + 0.005, WALL - 0.4, 0.2)]),
        ("cable_tower", "cable_black", 0.0035, [
            (tower_back + 0.005, WALL - 0.5, 0.1), (tower_back - 0.04, WALL - 0.52, 0.04),
            (tower_back - 0.1, WALL - 0.35, 0), (tower_back - 0.02, WALL - 0.12, 0),
            (sock[0] - 0.15, WALL - 0.05, 0), (sock[0] - 0.04, WALL - 0.03, 0.08),
            (sock[0] - 0.035, sock[1] - 0.03, sock[2] - 0.03)]),
        ("cable_strip", "cable_white", 0.0035, [
            (strip[0] + sr.x * 0.17, strip[1] + sr.y * 0.17, 0.02), (strip[0] + 0.25, strip[1] + 0.2, 0),
            (sock[0] + 0.15, WALL - 0.08, 0), (sock[0] + 0.06, WALL - 0.03, 0.1),
            (sock[0] + 0.035, sock[1] - 0.03, sock[2] - 0.03)]),
        ("cable_speaker", "cable_black", 0.0025, [
            (DESK_X + 0.28, WALL - 0.19, 0.8), (DESK_X + 0.3, WALL - 0.15, top), (x1 - 0.02, WALL - 0.2, top),
            (x1 + 0.015, WALL - 0.24, dz - 0.04), (x1 + 0.03, WALL - 0.3, 0.3), (x1, WALL - 0.42, 0.04),
            (x1 - 0.1, WALL - 0.55, 0), plug(3)]),
        ("cable_tower_speaker", "cable_grey", 0.002, [
            (tower_back + 0.005, WALL - 0.44, 0.15), (tower_back - 0.05, WALL - 0.6, 0),
            (DESK_X - 0.05, WALL - 0.75, 0), (x1 - 0.05, WALL - 0.6, 0), (x1 - 0.01, WALL - 0.45, 0.06),
            (x1 + 0.02, WALL - 0.32, 0.32), (x1 + 0.012, WALL - 0.26, dz - 0.03)]),
        ("cable_lamp", "cable_black", 0.003, [
            (lx - 0.15, ly + 0.02, 0.012), (lx - 0.28, ly + 0.15, 0), (lx - 0.2, ly + 0.45, 0),
            (lx - 0.38, ly + 0.62, 0), (lx - 0.5, ly + 0.5, 0), (lx - 0.62, ly + 0.75, 0),
            (x1 + 0.35, WALL - 1.15, 0), (x1 + 0.12, WALL - 0.85, 0), (strip[0] + 0.15, strip[1] - 0.2, 0),
            plug(0)]),
        ("cable_charger", "cable_black", 0.0025, [
            plug(1), (strip[0] - 0.05, strip[1] - 0.35, 0), (DESK_X + 0.1, WALL - 1.0, 0),
            (DESK_X + 0.35, WALL - 1.45, 0), (DESK_X + 0.25, WALL - 1.75, 0), (DESK_X + 0.42, WALL - 2.05, 0),
            (DESK_X + 0.5, WALL - 2.15, 0)]),
        ("cable_desk_usb", "cable_grey", 0.0022, [
            (x1 - 0.12, WALL - 1.1, top), (x1 + 0.005, WALL - 1.05, top), (x1 + 0.02, WALL - 1.0, dz - 0.15),
            (x1 + 0.06, WALL - 0.95, 0.06), (x1 + 0.2, WALL - 0.9, 0)]
            + clutter.coil((x1 + 0.28, WALL - 0.98), 0.09, 2, random.Random(2))),
        ("cable_spare_display", "cable_white", 0.0035,
            [(NE_PILE[0] + 0.25, NE_PILE[1] + 0.25, 0.08), (NE_PILE[0] + 0.15, NE_PILE[1] - 0.05, 0)]
            + clutter.coil((NE_PILE[0] - 0.05, NE_PILE[1] - 0.78), 0.12, 1.5, random.Random(3))
            + [(NE_PILE[0] - 0.5, NE_PILE[1] - 0.55, 0), (x1 + 0.6, WALL - 0.95, 0), (x1 + 0.3, WALL - 0.6, 0),
               plug(2)]),
    ]
    for i, (name, mat, r, pts) in enumerate(cables):
        clutter.cable(col, name, pts, m[mat], r, seed=i * 5.0, lift=0.0005 * (i % 3))
    # charger brick at the end of its cable
    b = clutter.Pile(m)
    b.box((0.07, 0.11, 0.03), (0, 0, 0.015), m["plastic_black"])
    b.build("charger", col, (DESK_X + 0.55, WALL - 2.22, 0), 0.6, bevel=0.004)


def _loose_paper(m, col, rng):
    """Sheets that slid off the piles."""
    shelf_x = to_m(275, 0)[0]
    spots = [(SOUTH_PILE[0] + 0.25, SOUTH_PILE[1] + 0.35), (SOUTH_PILE[0] - 0.65, SOUTH_PILE[1] - 0.1),
             (SOUTH_PILE[0] + 0.1, SOUTH_PILE[1] + 0.5), (shelf_x + 0.45, to_m(0, 470)[1]),
             (shelf_x + 0.5, to_m(0, 300)[1]), (shelf_x + 0.35, to_m(0, 820)[1]),
             (NE_PILE[0] - 0.4, NE_PILE[1] - 0.6), (DESK_X - 0.1, WALL - 2.0)]
    b = clutter.Pile(m, rng)
    for x, y in spots:
        for k in range(rng.randint(1, 2)):
            mm = clutter.frame((x + rng.uniform(-0.08, 0.08), y + rng.uniform(-0.08, 0.08), 0.0008 + 0.002 * k),
                               (0, 0, rng.uniform(0, math.tau)))
            shape = clutter.sheet_shape(0.21, 0.297, rng.uniform(0.005, 0.03), rng.uniform(0.0, 0.05),
                                        rng.uniform(0, 50))
            mat = m["print"] if rng.random() < 0.2 else m["paper"]
            b.surface(mm, shape, clutter.breaks(5), clutter.breaks(8), 0.0004, mat, rim=m["paper"])
    b.build("loose_paper", col, bevel=0.0)


def build_lamp(c):
    f.floor_lamp(c.m, c.furn, "floor_lamp", (*LAMP, 0))


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
