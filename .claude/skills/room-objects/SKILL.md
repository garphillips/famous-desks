---
name: room-objects
description: Add, change, hide or remove the things visitors can interact with in a Famous Desks room: hotspots (pins), close-up zooms like the bookshelf and display, detail panels with close-up renders and 3D models, featured books, the music/Spotify player and speaker ripples, doors to other spaces. Use this whenever the user says "add a hotspot", "make X clickable", "zoom into X like the bookshelf", "remove/hide the hotspot", "change the icon", "add a book", "the playlist", or wants an object to do something when clicked.
---

# Room objects

Hotspots are declared in the room script's `build_tour()` with `tour.hotspot(slug, title, (x, y, z), icon=..., summary=..., kind="hotspot", **extra)` and exported into `space.json` (with per-viewpoint yaw/pitch/distance for every viewpoint that can see them). The site renders them in `web/src/lib/components/Tour.svelte` and `HotspotMarker.svelte`. Most changes need only `blender/pipeline.sh <room> --no-render` (room-render skill), no re-render.

## Choose the kind

| Want | Declare | Behaviour |
|---|---|---|
| Info card, then a panel of close-up renders and/or a 3D model | `model="<object name>"` and/or `tour.detail_camera(slug, loc, target, lens=...)` | Hover shows a card; click pins it; second click opens the panel. Close-ups and models need a render. |
| One-click zoom ("like the bookshelf") | `focus=dict(viewpoint=<slug>, target=(x, y, z), fov=<deg>, width=<deg>)` | No hover card; one click flies to that viewpoint and zooms. Bar has back; "Close-ups and 3D" if the hotspot also has detail. Zooming out / Esc leaves. |
| Pickable items in the close-up (books) | focus + items via `lib/featured.py` (`FEATURED_BOOKS` in the room) | Highlighted spines; a book flies out with its cover and summary. |
| Music | `icon="music"`, `playlist="<Spotify playlist id>"`, `summary=` (the "why these songs" text) | Not a pin: the Spotify player sits in the corner; ripples spread from the hotspot's position while it plays. |
| Door to another space | `kind="door", icon="door", target="<space>", arrive="<viewpoint>"` | Navigates. |

Icons are Phosphor glyphs inlined in `web/src/lib/components/Icon.svelte` (filled where the shape reads well, bold for thin glyphs like plus/minus/close). To add one: take the SVG from `@phosphor-icons/core` (MIT), add a branch and the name to `IconName`, and add the name to the `icon` union in `web/src/lib/types.ts` and to `tour.hotspot`'s docstring.

## Close-ups: picking the viewpoint and zoom

The viewpoint to zoom from matters more than anything else. For each viewpoint, compute the angle between the object's facing direction and the direction to the viewpoint, plus the distance (the yaw from viewpoint to target is `atan2(dx, dy)` in degrees; `space.json` hotspot `views` give yaw and distance). Prefer near head-on (under ~30°), then close. A viewpoint that's 2 m away head-on beats one 1.7 m away at 58°. The minimap still treats the viewpoint as normal; only a focus with items takes over its arrival.

- `fov` is the vertical field of view to land at. The viewer's usual limit is 30°. A close-up may go tighter (the display uses 20°) only if the viewpoint has `face_size=4096`; the viewer lowers `minFov` for the close-up and restores it on leaving.
- `width` (degrees across) keeps the whole subject in view on portrait phones; without it the code assumes 0.8 × fov, which suits a wide shelf, not a monitor.
- Target the visual centre (e.g. screen centre = desk top + stand lift + half the screen height), not the hotspot pin's position.
- Check desktop and phone with `node tools/check/check.mjs closeup "<title>" --size desktop,phone`.

## Hiding and removing

- **"Hide for now"**: add the slug to `site.hiddenHotspots` in `web/src/lib/site.ts`. Data and renders stay; the tour and Objects page skip it. No export needed.
- **Remove**: delete the `tour.hotspot` (and its `detail_camera`s) in the room script, `--no-render` export, and `git rm` the orphaned `content/spaces/<slug>/details/<hotspot>/` folder.
- Things the user finds sensitive (an unlicensed artwork) may stay in the room but get no hotspot, close-up or caption at all.

## Featured books
Each entry in the room's `FEATURED_BOOKS` has `slug, title, author, spineAuthor, cover (asset id), kind, size (thickness, height, width in m), near (where on the shelf), spine` style, and a `summary` of one or two factual sentences on why it mattered to the person (no invention: only well-documented facts). Covers come from Open Library via the asset manifest (`covers.json`, `kind: "cover"`, licence `cover-art`); see the asset-intake skill. `web/scripts/book-art.mjs` makes the spine and web images during the build.

## Music
Spotify's official embed only (no Apple Music: its embed has no playback events, so the ripples couldn't follow playback, and it has no slim player). Never overlay or alter the embed. The playlist should belong to a Famous Desks Spotify account, not the user's personal one (the embed shows the owner's name).
