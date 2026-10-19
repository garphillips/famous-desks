"""Hallway: a deliberately plain PLACEHOLDER space outside the Jobs Room.

Nobody has decided what is actually outside the Jobs Room. This corridor only
exists to prove multi-space navigation (two-way doors, the Spaces menu), so it
is kept obviously generic: painted plaster, one window, a console table and a
framed print.

Layout: a 2 m x 5 m corridor running north-south. The double door at the north
end leads back into the Jobs Room (whose door is on its south wall); the window
is at the south end.
"""

import math

import bpy

from lib import architecture, environment, furniture as f, materials, tour
from lib.geo import collection

W, D = 2.0, 5.0
DOOR_W = 1.42  # matches the Jobs Room's double door

SPEC = {
    "slug": "hallway",
    "title": "Hallway",
    "order": 2,
    "width": W,
    "depth": D,
    "height": 2.75,
    "wall_thickness": 0.3,
    "ceiling": {"joist_axis": "X", "joist_spacing": 0.6, "joist_depth": 0.16},
    "walls": {
        "N": {"finish": "plaster", "openings": [
            {"kind": "door", "center": 0.0, "width": DOOR_W, "sill": 0.0, "head": 2.1,
             "leaves": 2, "finish": "sash_white"},
        ]},
        "S": {"finish": "plaster", "openings": [
            {"kind": "window", "style": "sash", "center": 0.0, "width": 1.0,
             "sill": 0.85, "head": 2.3, "cols": 2, "rows": 3},
        ]},
        "E": {"finish": "plaster"},
        "W": {"finish": "plaster"},
    },
}

CONSOLE_Y = 0.4


def build():
    m = materials.library()
    architecture.Room(SPEC, m).build()
    environment.build_daylight(sun_azimuth=75, sun_elevation=25, mirror=True)  # same morning as the Jobs Room
    bpy.context.scene.view_settings.exposure = 4.6

    furn = collection("Furniture")
    props = collection("Props")

    # Console table against the east wall, with a framed print above it
    ex = W / 2
    f.table(m, furn, "console", (ex - 0.19, CONSOLE_Y, 0), (1.1, 0.34, 0.8), rot_z=math.pi / 2,
            top="oak", frame="oak", leg=0.04)
    f.paper_stack(m, props, "console_papers", (ex - 0.2, CONSOLE_Y - 0.25, 0.8), size=(0.28, 0.22, 0.05))
    f.black_box(m, props, "console_box", (ex - 0.2, CONSOLE_Y + 0.3, 0.8), (0.16, 0.16, 0.12), mat="cardboard")
    f.frame(m, props, "print_east", (ex - 0.001, CONSOLE_Y, 1.55), (0.7, 0.5), rot_z=-math.pi / 2)

    # Tour markup
    tour.viewpoint("door", "By the door", (0.0, D / 2 - 0.8), 0, look_at=(0.0, -D / 2))
    tour.viewpoint("middle", "Hallway", (-0.25, -0.2), 1, look_at=(ex, CONSOLE_Y))
    tour.viewpoint("window", "Window", (0.0, -D / 2 + 0.9), 2, look_at=(0.0, D / 2))

    tour.hotspot("jobs_room_door", "The Jobs Room", (0.0, D / 2 - 0.05, 1.4), kind="door", icon="door",
                 target="jobs-room", arrive="entrance")
    tour.hotspot("console", "Console table", (ex - 0.19, CONSOLE_Y, 1.0), icon="info",
                 summary="A placeholder hallway: what's really outside the Jobs Room hasn't been decided yet.")
    tour.hotspot("print", "The print", (ex - 0.05, CONSOLE_Y, 1.85))

    tour.plan_camera(W, D)
