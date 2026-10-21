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
  plain; the website keeps views off it: tour.unseen_wall).
- Floor clutter along the bookshelf, south of the desk, and between the desk and
  the north-east window. Floor lamp south-east of the desk.
"""

import math
import os
import random

import bpy
from mathutils import Matrix, Vector

from lib import architecture, books, clutter, desk, environment, featured, furniture as f, hero, imported, materials, tour
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
# The corner windows (sizes from the sketch) run to within 30 cm of the north-east corner,
# leaving a narrow pillar of brick between them, as in Diana Walker's photo.
CORNER_PIER = 0.30
_ne_w, _e_w = span_x(1280, 1678)[1], span_y(112, 510)[1]
NE_WINDOW = (W / 2 - CORNER_PIER - _ne_w / 2, _ne_w)
E_WINDOW = (D / 2 - CORNER_PIER - _e_w / 2, _e_w)
# Steel windows: sill and head heights. The north-west window has a row of panes fewer than the
# corner ones (3 rows, not 4), so it's shorter, its head level with theirs.
SILL, HEAD = 0.55, 2.3
NW_SILL = 0.9125
DOOR = span_x(1110, 1508)  # the updated plan: towards the south-east corner
# mid-century chest of drawers against the east wall, south end (updated plan)
CHEST = span_y(752, 1150)
CHEST_DEPTH = 0.46
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
    "floor": {"run": "X", "board_width": 0.285},  # east-west boards, about 28 cm wide
    "ceiling": {"joist_axis": "X", "joist_spacing": 0.55, "joist_depth": 0.2, "cross_beams": [-2.3]},
    "walls": {
        "N": {"finish": "brick_x", "openings": [
            {"kind": "window", "style": "steel", "center": NW_WINDOW[0], "width": NW_WINDOW[1],
             "sill": NW_SILL, "head": HEAD, "cols": 4, "rows": 3, "tiled_sill": True},
            {"kind": "window", "style": "steel", "center": NE_WINDOW[0], "width": NE_WINDOW[1],
             "sill": SILL, "head": HEAD, "cols": 4, "rows": 4},
        ]},
        "E": {"finish": "brick_y", "openings": [
            {"kind": "window", "style": "steel", "center": E_WINDOW[0], "width": E_WINDOW[1],
             "sill": SILL, "head": HEAD, "cols": 4, "rows": 4},
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
    build_chest(c)
    build_tour(c)


# --- sections: each is owned by one area of work ------------------------------


def build_lighting(c):
    """Sky, sun, garden and exposure: a low morning sun through the east window."""
    environment.build_daylight(sun_azimuth=75, sun_elevation=25, mirror=True, backplate=1.6,
                               view="pretoria_gardens", view_strength=0.75)
    t = SPEC["wall_thickness"]
    environment.build_garden(c.m, (-W / 2 - t, -D / 2 - t, W / 2 + t, D / 2 + t), sides="NE",
                             sun_azimuth=75, sun_elevation=25)
    bpy.context.scene.view_settings.exposure = 5.1
    bpy.context.scene["white_balance"] = (0.72, 1.0, 1.32)  # neutralise the warm bounce off floor and beams
    bpy.context.scene["lamp_glow"] = 0.0  # lamp off in daylight, as in the photo (materials.finish_scene)


def build_bookshelf(c):
    """West wall bookshelf (front facing east), its books and what sits on top.
    Stocked to match the north-facing photo: bays run south to north (left to
    right in the photo), levels bottom to top."""
    m, furn, props = c.m, c.furn, c.props
    shelf_depth = 0.34
    bays = 3
    bay_w = (BOOKSHELF[1] - 0.025 * (bays + 1)) / bays
    layout = [
        ["dense", "mixed", "stacked"],
        ["dense", "leaning", "mixed"],
        ["mixed", "mixed", "objects+printer"],
        ["leaning", "leaning", "files+laptop"],
        ["files+jars", "dense", "files+camera"],
        ["dense", "stacked", "objects+clock"],
    ]
    books.bookshelf(m, c.books, furn, props, "bookshelf", (-W / 2 + shelf_depth / 2, BOOKSHELF[0], 0),
                    bays=[bay_w] * bays, shelves=[0.08, 0.46, 0.82, 1.16, 1.48, 1.80, 2.12], layout=layout,
                    depth=shelf_depth, rot_z=math.pi / 2, seed=3)
    top = 2.145
    books.basket(c.books, props, "basket", (-W / 2 + 0.19, -0.95, top), rot_z=math.pi / 2)
    books.basket_handle(m, props, "basket_handle", (-W / 2 + 0.19, -0.95, top + 0.29), rot_z=math.pi / 2)
    books.storage_box(m, props, "shelf_top_boxes", (-W / 2 + 0.19, 0.55, top), (0.42, 0.28, 0.11),
                      mat="plastic_black", rot_z=math.pi / 2 + 0.03)
    books.storage_box(m, props, "shelf_top_box_cream", (-W / 2 + 0.18, 0.95, top), (0.32, 0.26, 0.12),
                      mat="cardboard", rot_z=math.pi / 2 - 0.04)
    featured.place_books("jobs-room", "bookshelf", FEATURED_BOOKS, c.books, hotspot="bookshelf")


# Real books on the shelf: pulled out on the website (lib/featured.py). size is
# (thickness, height, width) in metres; near is a point on the shelf to stand close to
# (front of the shelf at x = -2.86, boards at z 0.82 / 1.16 / 1.48); spine is the artwork
# for web/scripts/book-art.mjs.
SHELF_FRONT = -2.95
FEATURED_BOOKS = [
    dict(slug="autobiography-of-a-yogi", title="Autobiography of a Yogi", author="Paramahansa Yogananda",
         spineAuthor="Yogananda", cover="cover_autobiography_of_a_yogi", kind="paperback",
         size=(0.034, 0.216, 0.14), near=(SHELF_FRONT, 0.3, 1.19),
         spine=dict(bg="#2f6fc0", fg="#ffffff", font="Futura", weight="bold", upper=True, scale=0.34),
         summary="Yogananda's 1946 memoir of his search for a guru in India and his decades teaching "
                 "meditation in America. Jobs first read it as a teenager and reread it every year; it "
                 "was reportedly the only book he downloaded to his iPad."),
    dict(slug="king-lear", title="King Lear", author="William Shakespeare", spineAuthor="Shakespeare",
         cover="cover_king_lear", kind="paperback", size=(0.022, 0.198, 0.129), near=(SHELF_FRONT, 0.4, 1.51),
         spine=dict(bg="#e8d9b0", fg="#1d1a14", font="Baskerville", scale=0.5, titleSpan=[0.1, 0.5]),
         summary="Shakespeare's tragedy of an ageing king who divides his kingdom between the daughters "
                 "who flatter him best, and loses everything. Jobs named it among the books that shaped "
                 "him at Reed College."),
    dict(slug="dylan-thomas-collected-poems", title="Collected Poems", author="Dylan Thomas",
         cover="cover_dylan_thomas_collected_poems", kind="hardback", size=(0.026, 0.222, 0.145),
         near=(SHELF_FRONT, 0.4, 0.85),
         spine=dict(bg="#efece4", fg="#222222", font="Gill Sans", upper=True, scale=0.36,
                    titleSpan=[0.42, 0.94], authorSpan=[0.06, 0.38]),
         summary="The poet's own selection of his work from 1934 to 1952, including \u201cFern Hill\u201d "
                 "and \u201cDo not go gentle into that good night\u201d. Jobs read and recited Dylan Thomas "
                 "in his late teens."),
    dict(slug="nineteen-eighty-four", title="Nineteen Eighty-Four", author="George Orwell", spineAuthor="Orwell",
         cover="cover_1984", kind="paperback", size=(0.02, 0.181, 0.111), near=(SHELF_FRONT, -0.04, 1.51),
         spine=dict(bg="#f1ece0", fg="#1a1a1a", font="Gill Sans", weight="bold", upper=True, scale=0.36,
                    bands=[[0, 0.22, "#e2522b"], [0.78, 1, "#e2522b"]], titleSpan=[0.24, 0.6],
                    authorSpan=[0.62, 0.76]),
         summary="Orwell's 1949 novel of Oceania, where Big Brother is always watching and the Party "
                 "rewrites the truth. Apple borrowed its imagery for the Ridley Scott ad that launched the "
                 "Macintosh in January 1984."),
    dict(slug="the-innovators-dilemma", title="The Innovator\u2019s Dilemma", author="Clayton M. Christensen",
         spineAuthor="Christensen", cover="cover_innovators_dilemma", kind="paperback",
         size=(0.022, 0.229, 0.152), near=(SHELF_FRONT, -0.3, 1.19),
         spine=dict(bg="#111111", fg="#c9d64a", accent="#ffffff", font="Futura", weight="bold", scale=0.4),
         summary="Christensen's 1997 study of why well-run companies lose to cheaper, simpler newcomers: "
                 "by listening too closely to their best customers. Jobs said it deeply influenced him."),
]


def build_desk(c):
    """The desk: short end against the north wall between the two windows.
    Display at the wall end facing into the room, angled towards the chair on
    the desk's west side (where the man sits in the south-facing photo). Also
    the prints on the walls."""
    m, furn, props = c.m, c.furn, c.props
    mt = desk.materials(m)
    rng = random.Random(7)
    top = 0.74
    desk.desk(mt, furn, "desk", (DESK_X, WALL - DESK_LEN / 2, 0), (DESK_W, DESK_LEN, top))
    # a 16:10 screen, like the Cinema Display in the photo from his desk
    hero.display(props, "display", DISPLAY_LOC, rot_z=-0.35, width=0.66, height=0.43)
    desk.speaker(mt, props, "speaker", (DESK_X + 0.31, WALL - 0.21, top), rot_z=-0.12)
    desk.desk_lamp(mt, props, "desk_lamp", (DESK_X + 0.31, WALL - 0.21, top + 0.303), rot_z=-0.12)
    desk.tower(mt, props, "mac_pro", (DESK_X - 0.2, WALL - 0.45, 0), rot_z=math.pi / 2)
    kb = desk.keyboard(mt, props, "keyboard", (DESK_X - 0.25, WALL - 0.55, top), rot_z=-1.34)
    ms = desk.mouse(mt, props, "mouse", (DESK_X - 0.26, WALL - 0.86, top), rot_z=-1.45)
    desk.desk_phone(mt, props, "desk_phone", (DESK_X - 0.31, WALL - 1.4, top), rot_z=-1.2)
    desk.photo_frame(mt, props, "photo_frame", (DESK_X + 0.2, WALL - 0.47, top), rot_z=0.15)
    _desk_cables(mt, props, kb, ms, top)

    # the pot, mug and bottles, then piles of paper, magazines and CDs
    small = hero.HeroBuilder()
    desk.pen_pot(small, mt, rng, (-0.33, 0.23, 0))
    desk.bottle(small, mt, (-0.36, 0.33, 0))
    desk.bottle(small, mt, (-0.28, 0.35, 0), height=0.14, radius=0.022, mat=mt["glass_clear"], cap=mt["cap_white"])
    desk.bottle(small, mt, (-0.25, 0.30, 0), height=0.11, radius=0.018, mat=mt["glass_clear"], cap=mt["cap_white"])
    desk.mug(small, mt, (-0.08, -0.07, 0), rot=2.4)
    small.build("desk_items", props, (DESK_X, WALL - 0.4, top))
    piles = [
        ((0.1, 1.42), 0.2, [("cds", 6), ("papers", 0.03), ("mags", 3), ("cds", 3)]),
        ((0.21, 1.0), -0.15, [("catalogues", 3), ("papers", 0.06), ("mags", 2), ("envelopes", 1), ("mags", 1)]),
        ((-0.1, 0.98), 0.35, [("papers", 0.035), ("envelopes", 2)]),
        ((0.05, 0.72), -0.3, [("mags", 4), ("cds", 2), ("notebook", 0)]),
        ((0.29, 0.55), 0.1, [("papers", 0.09), ("catalogues", 1), ("cds", 2)]),
        ((-0.25, 0.47), -0.5, [("notebook", 1), ("envelopes", 1)]),
    ]
    for i, ((x, y), rot, recipe) in enumerate(piles):
        desk.pile(mt, props, f"desk_pile_{i}", (DESK_X + x, y, top), recipe, rng, rot_z=rot)
    imported.load("vintage_stapler", "vintage_stapler_1k.gltf", props, "stapler", (DESK_X - 0.03, 1.24, top), rot_z=0.5)
    imported.load("stationery_supplies", "stationery_supplies_1k.gltf", props, "stationery",
                  (DESK_X - 0.01, 0.43, top), rot_z=0.08)

    imported.office_chair(m, furn, "chair", (DESK_X - DESK_W / 2 - 0.4, WALL - 0.7, 0), rot_z=0.5)
    # Ansel Adams, "Orchard, Portola Valley, California": the print over Jobs' desk. Unlicensed
    # (see the asset manifest), so it only hangs on the wall: no hotspot or close-up of it.
    north = desk.bw_print("hero_print_north", "print_orchard_portola", "ansel.webp", 2560,
                          left=0.0, top=0.006, height=0.988, aspect=0.56 / 0.43, out_h=1400, as_is=True)
    desk.framed_print(mt, props, "print_north", (DESK_X, WALL - 0.001, 1.85), (0.78, 0.62),
                      desk._image_material("hero_print_north", north, 0.45), window=(0.56, 0.43))
    west = desk.bw_print("hero_print_west", "print_misty_pines", "misty_pines.jpg", 4096,
                         left=0.43, top=0.1, height=0.55, aspect=0.39 / 0.57, gamma=1.25)
    # east wall, between the window and the chest of drawers (photo looking east from the desk)
    east = desk.bw_print("hero_print_east", "print_autumn_meadow", "DSC_0415.jpg", 4928,
                         left=0.62, top=0.3, height=0.6, aspect=0.3 / 0.4, gamma=1.4)
    desk.framed_print(mt, props, "print_east", (W / 2 - 0.001, -0.2, 1.6), (0.42, 0.54),
                      desk._image_material("hero_print_east", east, 0.45), window=(0.3, 0.4), rot_z=-math.pi / 2)
    desk.framed_print(mt, props, "print_west", (-W / 2 + 0.001, -1.75, 1.45), (0.6, 0.8),
                      desk._image_material("hero_print_west", west, 0.45), window=(0.4, 0.58),
                      rot_z=math.pi / 2)  # faces east


def _desk_cables(mt, props, kb, ms, top):
    """Mouse to keyboard, then keyboard, display, speaker and lamp cables off the
    desk's west edge by the wall and down to the tower."""
    def at(obj, p):
        return tuple(obj.matrix_world @ Vector(p))

    for o in (kb, ms):
        o.matrix_world = Matrix.Translation(o.location) @ Matrix.Rotation(o.rotation_euler.z, 4, "Z")
    x0 = DESK_X - DESK_W / 2
    b = hero.HeroBuilder()
    z = top + 0.0018
    mouse_end = at(ms, (0, 0.058, 0.004))
    kb_end = at(kb, (0.216, 0.03, 0.006))
    b.tube(hero.smooth_path([mouse_end, at(ms, (0.0, 0.1, 0.0)), (DESK_X - 0.12, WALL - 0.78, z),
                             (DESK_X - 0.08, WALL - 0.62, z), kb_end[:2] + (z,), kb_end], 6), 0.0017,
           mt["cable_white"])
    drop = [(x0 + 0.03, WALL - 0.08, z), (x0 - 0.006, WALL - 0.07, top - 0.01), (x0 - 0.01, WALL - 0.075, 0.45),
            (x0 + 0.02, WALL - 0.12, 0.004), (DESK_X - 0.44, WALL - 0.3, 0.004), (DESK_X - 0.44, WALL - 0.42, 0.2)]
    starts = [
        [at(kb, (0, 0.06, 0.004)), (DESK_X - 0.18, WALL - 0.2, z)],
        [(DISPLAY_LOC[0] + 0.02, WALL - 0.14, z), (DESK_X - 0.2, WALL - 0.1, z)],
        [(DESK_X + 0.33, WALL - 0.08, top + 0.08), (DESK_X + 0.3, WALL - 0.05, z), (DESK_X - 0.1, WALL - 0.04, z)],
    ]
    for i, s in enumerate(starts):
        off = Vector((0.006 * i, 0.007 * i, 0))
        path = s + [tuple(Vector(p) + off * (1 if p[2] > 0.01 else 3)) for p in drop]
        b.tube(hero.smooth_path(path, 6), 0.0022 if i else 0.0018, mt["cable_white"] if i < 2 else mt["cord"])
    b.build("desk_cables", props)


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
    imported.mesh_basket(m, props, "bin", (cx - 0.35, cy + 0.4, 0))
    f.flight_case(m, props, "camera_case", (cx - 0.1, cy - 0.45, 0), rot_z=-0.2)
    hero.camera(props, "camera", CAMERA_LOC, rot_z=0.3)

    nx, ny = NE_PILE
    _spare_display(cm, props, "spare_display", (nx + 0.2, ny + 0.15, 0), 0.4 + math.pi)
    imported.white_drum(m, props, "white_drum", (nx - 0.35, ny + 0.3, 0))
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
    """Floor cables: computer and power strip -> wall, lamp and chargers -> strip.
    (Cables on the desk itself come from _desk_cables.)"""
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
        ("cable_tower", "cable_black", 0.0035, [
            (tower_back + 0.005, WALL - 0.5, 0.1), (tower_back - 0.04, WALL - 0.52, 0.04),
            (tower_back - 0.1, WALL - 0.35, 0), (tower_back - 0.02, WALL - 0.12, 0),
            (sock[0] - 0.15, WALL - 0.05, 0), (sock[0] - 0.04, WALL - 0.03, 0.08),
            (sock[0] - 0.035, sock[1] - 0.03, sock[2] - 0.03)]),
        ("cable_strip", "cable_white", 0.0035, [
            (strip[0] + sr.x * 0.17, strip[1] + sr.y * 0.17, 0.02), (strip[0] + 0.25, strip[1] + 0.2, 0),
            (sock[0] + 0.15, WALL - 0.08, 0), (sock[0] + 0.06, WALL - 0.03, 0.1),
            (sock[0] + 0.035, sock[1] - 0.03, sock[2] - 0.03)]),
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


def build_chest(c):
    """The mid-century chest of drawers in the south-east corner, drawers facing west, with a
    pile of family photo frames on top (as in the photo looking east from the desk)."""
    mt = desk.materials(c.m)
    x = W / 2 - CHEST_DEPTH / 2 - 0.015
    desk.chest_of_drawers(mt, c.furn, "chest_of_drawers", (x, CHEST[0], 0), rot_z=-math.pi / 2,
                          size=(CHEST[1], CHEST_DEPTH, 0.78))
    top = 0.78
    # standing frames, facing west: (along the chest, from the wall, size, wood, photo, turn)
    frames = [
        (0.42, 0.16, (0.2, 0.25), "walnut", "snapshot_3", 0.1),
        (0.22, 0.12, (0.13, 0.18), "frame_black", "snapshot", -0.15),
        (0.05, 0.2, (0.18, 0.13), "oak", "snapshot_2", 0.05),
        (-0.12, 0.1, (0.24, 0.3), "frame_black", "snapshot_4", -0.06),
        (-0.3, 0.22, (0.1, 0.15), "oak", "snapshot_3", 0.25),
        (-0.45, 0.14, (0.16, 0.2), "walnut", "snapshot", -0.2),
    ]
    for i, (along, back, size, wood, photo, turn) in enumerate(frames):
        desk.photo_frame(mt, c.props, f"chest_frame_{i}", (x - CHEST_DEPTH / 2 + back, CHEST[0] + along, top),
                         rot_z=-math.pi / 2 + turn, size=size, wood=wood, photo=photo)
    desk.frame_stack(mt, c.props, "chest_frame_pile", (x - 0.06, CHEST[0] + 0.58, top), rot_z=0.3,
                     sizes=[(0.3, 0.24), (0.25, 0.2), (0.2, 0.25)])


def build_lamp(c):
    imported.floor_lamp(c.m, c.furn, "floor_lamp", (*LAMP, 0))


def build_tour(c):
    """Viewpoints, hotspots, close-up cameras and reference cameras."""
    # No photos show the south wall (the door's is presumed), so the tour never faces it.
    tour.unseen_wall((-W / 2, -D / 2), (W / 2, -D / 2))
    # minimap moves land facing the north-west window (the one by the bookshelf), centred
    tour.arrive_facing((NW_WINDOW[0], D / 2, (NW_SILL + HEAD) / 2))
    tour.viewpoint("office", "Office", (0.35, -1.65), 0, look_at=(DESK_X, WALL))
    # sharper (4096 px faces) so the featured books' spines read when zoomed in
    tour.viewpoint("bookshelf", "Bookshelf", (-1.25, 0.3), 1, look_at=(-W / 2, 0.3), face_size=4096)
    tour.viewpoint("desk", "Desk", (0.95, 0.55), 2, look_at=(DESK_X, WALL))
    tour.viewpoint("window", "Window", (2.15, -1.05), 3, look_at=(W / 2, E_WINDOW[0]))
    tour.viewpoint("entrance", "Entrance", (DOOR[0], -D / 2 + 0.6), 4, look_at=(DESK_X, WALL))

    tour.hotspot("bookshelf", "Bookshelf", (-W / 2 + 0.2, BOOKSHELF[0], 1.65), icon="books",
                 summary="Explore the collection of books, cameras and creative tools.",
                 focus=dict(viewpoint="bookshelf", target=(SHELF_FRONT, 0.2, 1.25), fov=42))
    # the screen, close up from the bookshelf viewpoint: nearly head-on, and its 4096 px faces
    # are sharp enough to zoom to 20 degrees (desk top 0.74 + lift 0.12 + half the 0.43 m screen)
    tour.hotspot("display", "The display", (DISPLAY_LOC[0], DISPLAY_LOC[1], 1.3), model="display",
                 focus=dict(viewpoint="bookshelf", target=(DISPLAY_LOC[0], DISPLAY_LOC[1], 1.075), fov=20,
                            width=26))  # degrees across that must fit on a portrait screen
    # in front of the desk speaker's baffle (desk top 0.74 m, speaker 0.30 m tall)
    tour.hotspot("speaker", "On the speaker", (DESK_X + 0.31, WALL - 0.34, 0.91), icon="music",
                 summary="Jobs was a lifelong Bob Dylan fan: he opened Apple's 1984 shareholders' meeting "
                         "by reciting a verse of \"The Times They Are a-Changin'\". A few songs for the room, "
                         "starting with \"One Too Many Mornings\".",
                 playlist="09XZ2JIqeA6kxT3NhsM9iG")
    # Gareth's letter to Steve, in the kraft envelope on the red notebook (desk pile 5): the site
    # opens it on screen, so its words live in jobs_room.letter.txt and change without a render
    with open(os.path.join(os.path.dirname(__file__), "jobs_room.letter.txt")) as fh:
        letter = fh.read().strip()
    tour.hotspot("letter", "A letter to Steve", (-0.25, 0.43, 0.8), icon="envelope", letter=letter)
    tour.hotspot("tripod", "Tripod", (TRIPOD_LOC[0], TRIPOD_LOC[1], 1.6), model="tripod")
    tour.hotspot("east_window", "Garden window", (W / 2 - 0.1, E_WINDOW[0], 1.85))
    tour.hotspot("entrance", "Entrance", (DOOR[0], -D / 2 + 0.05, 1.4), kind="door", icon="door",
                 target="hallway", arrive="door")

    # Close-ups for the detail panels (details/<hotspot>/closeup-<n>.webp)
    disp = DISPLAY_LOC
    tour.detail_camera("display", (disp[0] - 0.62, disp[1] - 0.95, 1.22), (disp[0], disp[1], 1.04),
                       lens=35, fstop=5.6)
    tour.detail_camera("display", (disp[0] - 0.8, disp[1] + 0.2, 1.08), (disp[0] - 0.02, disp[1] + 0.07, 0.94),
                       lens=32, fstop=5.6)
    pod = TRIPOD_LOC
    tour.detail_camera("tripod", (pod[0] + 0.45, pod[1] - 0.55, 1.55), (pod[0], pod[1], 1.3),
                       lens=50, fstop=2.8, brighten=0.6)
    tour.detail_camera("tripod", (pod[0] + 1.0, pod[1] - 1.5, 0.85), (pod[0], pod[1], 0.68),
                       lens=35, brighten=0.4)
    tour.detail_camera("bookshelf", (-1.5, 0.75, 1.45), (-W / 2, 0.35, 1.25), lens=30)

    # Matches "Upscaled facing south.png" (looks north at the desk) and
    # "upscaled facing north.png" (looks west at the bookshelf)
    tour.reference_camera("ref_desk_photo", (0.4, -1.95, 1.75), (-0.2, D / 2, 0.2), lens=18)
    tour.reference_camera("ref_bookshelf_photo", (2.6, 0.2, 1.5), (-W / 2, 0.5, 1.0))
    tour.plan_camera(W, D)
