---
name: room-from-photos
description: Turn reference photos and a rough floor-plan sketch into (or correct) a Famous Desks room script in blender/rooms/. Use this whenever the user shares photos of a famous person's office or desk, a floor plan or "updated plan", says something is in the wrong place (a door, window, desk, bookshelf), wants windows bigger/taller/closer, wants furniture added from a photo, or starts a new room/space, even if they don't say "room script". Covers reading the photos, the read-back-and-ask step, the room SPEC, viewpoints, the unseen-wall rule and checking the result against the photos.
---

# Room from photos

A room is a Python script (`blender/rooms/<room>.py`) that builds walls, openings, furniture and tour markup from a SPEC plus helper calls. It's built and exported by `blender/pipeline.sh <room>`. The user supplies reference photos (private: `starter/`, `~/Downloads/`; never commit them) and rough plans drawn as labelled boxes on a canvas.

The hard part is not the code; it's reading the photos correctly. In the Jobs Room the desk took four corrections and the windows three, because things were built from a first glance. So: **read, say what you see, ask about what's ambiguous, then build, then compare.**

## 1. Read every input before touching code

For each photo, write down (for yourself, then for the user):
- **Where it was taken from and which way it faces** (e.g. "from beside the north-west window, looking east along the desk"). Use the room's compass: +Y north, yaw clockwise from north, east = 90°.
- **What it confirms** about the current room, and **what it contradicts** (sizes, positions, counts of window panes, which wall something is on, colours).
- **What's new** (furniture, prints, a ledge, a lamp).
- **What it can't tell you** (a wall nobody photographed, the far side of an object).

For a plan sketch: it's roughly to scale. Measure pixels, convert with the room's `to_m()` / `span_x()` / `span_y()` (the sketch's canvas size maps to W × D metres; top of sketch = north). Compare it box by box with the previous plan and list every difference, including small nudges (the corner windows moved ~10 cm in the "updated plan"; easy to miss).

## 2. Read back and ask

Before building, tell the user the layout you've understood in a few bullets, then ask about anything ambiguous with `AskUserQuestion` (recommended option first, with the reasoning in the description). Typical questions that came up:
- Which edge moves when a window gets shorter or taller (sill or head)? The user's answer was not the obvious one twice.
- Does "bigger" mean wider, taller, or closer to the corner?
- Is a darker-looking surface really darker, or is it the lighting? ("more of a lighting thing")
- Is a ledge a window sill or a separate seat?

Ask one round of questions, not a drip. When the user later contradicts an earlier answer ("no, all of the increase goes downwards"), just apply it; don't re-argue.

## 3. Build

Where things live in the room script:
- **SPEC**: `width`, `depth`, `height`, `wall_thickness`, floor/ceiling, and `walls` N/E/S/W with `finish` and `openings`: windows `{kind: "window", style: "steel", center, width, sill, head, cols, rows, tiled_sill?}`, doors `{kind: "door", center, width, sill: 0, head, leaves, finish}`. Keep pane counts when resizing (the user thinks in panes: "one row of glass panes less").
- Name the numbers: `SILL, HEAD`, `NW_WINDOW`, `CORNER_PIER`... and derive dependants from them (the minimap's `arrive_facing` point uses the window's centre height), so one change doesn't leave others stale.
- **Furniture/props**: builders in `blender/lib/desk.py`, `hero.py` (HeroBuilder: bevelled boxes, rods, lathes), `furniture.py`, `clutter.py`, `imported.py` (CC0 models). New pieces go in their own `build_<thing>(c)` called from `build()`.
- **Tour markup** (`build_tour`): `tour.viewpoint(slug, title, (x, y), order, look_at=..., face_size=...)`, `tour.unseen_wall(a, b)`, `tour.arrive_facing(point)`, hotspots (see the room-objects skill), and `tour.reference_camera(name, loc, target)` cameras that reproduce a reference photo's angle (render them with `blender/render.py --cams reference`).

### Rules learned the hard way
- **Walls nobody photographed stay plain and unseen.** Mark them `tour.unseen_wall((x0, y0), (x1, y1))`; export gives each viewpoint a `yawRange` and the viewer never lets the frame show that wall. Don't invent detail for them.
- **Viewpoints**: eye height 1.6 m; keep them clear of furniture; a viewpoint someone will zoom from closely (books, a screen) gets `face_size=4096`.
- **Every viewpoint's first view** (`look_at`) and the minimap's arrival landmark (`arrive_facing`) should face something the photos confirm.
- **Moving a door/window moves things tied to it** (the Entrance viewpoint sits 0.6 m inside the door; hotspots reference window centres). Grep for the constant you changed.
- Colours from black-and-white or badly lit photos are guesses; change them a little and ask.

## 4. Check against the photos

Use the room-render skill: a draft preview of the affected viewpoints with `scripts/preview.sh <room> <viewpoints>` (about 3–4 minutes), which lays each render beside its reference photo. Add or adjust entries in `blender/rooms/<room>.views.json` so each photo has a matching view (`yaw`/`pitch` in compass degrees, `fov`, `ref`). Open the sheet for the user and point out what matches and what doesn't before suggesting the full render.

## New room checklist
1. Copy the shape of `jobs_room.py`: constants from the sketch, SPEC, `build()` sections, `build_tour()`.
2. Register it in content via the export (index.json order), and decide whether it's hidden for now (`site.hiddenSpaces` in `web/src/lib/site.ts`).
3. Per-room site text (tagline, share image, description) is currently global in `site.ts` / `web/src/app.html`; a second live room needs those made per-room first.
4. Start a `<room>.views.json` with one view per reference photo.
