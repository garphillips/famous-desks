# Office tour (working title)

A website for exploring 3D-rendered office spaces. Each space is modelled in
Blender from scripts, rendered as 360° panoramas per viewpoint, and shown in
the browser with clickable hotspots.

## Layout

```
blender/
  lib/          shared building blocks (walls & openings, materials, furniture, tour markup, render)
  rooms/        one script per space (jobs_room.py = The Jobs Room)
  build.py      builds a room and saves blender/build/<room>.blend
  render.py     renders cameras from a built room
  export.py     writes tour data, panoramas and plan to content/
  pipeline.sh   build + export in one go
content/        exported tour data + images per space (generated)
web/            the website (SvelteKit)
starter/        private reference images — git-ignored, never published
```

## Quick start

```sh
(cd web && npm ci)                    # once: the panorama tiler needs sharp
blender/pipeline.sh jobs_room          # build + export panoramas, plan and space.json to content/
cd web && npm run dev                  # tour at http://localhost:5173
```

`pipeline.sh` also takes `--draft` (fast low-res renders) or `--no-render` (data only).
The website reads `content/` directly (served at `/spaces/...`). Web stack:
SvelteKit 2 + Vite 6 (Node 20 compatible) + Three.js, built as a static site.

## Build and render by hand

```sh
BLENDER=/Applications/Blender.app/Contents/MacOS/Blender

# build the room (saves blender/build/jobs_room.blend, which you can open and edit)
$BLENDER -b --factory-startup -P blender/build.py -- jobs_room

# render: --cams takes names, or all / viewpoints / reference
$BLENDER -b blender/build/jobs_room.blend -P blender/render.py -- --cams reference --samples 64
```

## Conventions

- Metres, Z up, +Y is north, room interior centred on the origin, floor at z=0.
- Panoramas are equirectangular; the image centre faces north and yaw runs
  clockwise (east = 90°). For sharpness they are rendered as six 90° cube faces
  (2560 px, about an 8K equirect; faces n e s w u d, see `CUBE_FACES` in
  `blender/lib/tour.py`) and cut by `web/scripts/tile-pano.mjs` (Node + sharp) into
  512 px WebP tile levels under `panos/<vp>/`, which the viewer streams by level of
  detail. A 4096 equirect `panos/<vp>.webp` is kept as the fallback.
  `?fov=40` on a tour URL opens zoomed in; `?tiles=0` forces the equirect.
- Cameras named `vp_*` are tour viewpoints; empties named `hs_*` are hotspots.
  Their custom properties (title, icon, summary, kind) feed the website.
