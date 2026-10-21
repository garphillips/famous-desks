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

## Previewing a room change

```sh
(cd web && npm ci) && (cd tools/check && npm ci)   # once
scripts/preview.sh jobs_room office,desk            # draft-render office + desk, sheet their views
scripts/preview.sh jobs_room                        # every listed view (renders all their viewpoints)
scripts/preview.sh jobs_room --no-render            # sheet what content/ holds now (a "before")
scripts/preview.sh jobs_room --list                 # the room's comparison views
```

One command instead of five: it draft-renders the viewpoints (`pipeline.sh --draft --only ...`,
about 1.5 min a viewpoint, keeping the Mac awake), starts a dev server for this checkout if none
is running (and stops it after), screenshots each comparison view with `tools/check view`, and
writes one sheet of each view beside its reference photo to `tools/check/out/preview/`
(gitignored), which it opens. `--views a,b` picks views by name, `--restore` discards the draft
renders afterwards, `--no-open` doesn't open the sheet, `--help` lists the rest.

The views live beside the room in `blender/rooms/<room>.views.json`: a name, a viewpoint, an
aim (`yaw`/`pitch` in compass degrees, or a `hotspot` slug, or a `turn` in drag px), an optional
`fov`, and an optional `ref` photo (absolute, `~/...`, or relative to the main checkout's private
`starter/`; photos never go in the repo). It's JSON rather than Python because the room scripts
import `bpy`, so only Blender can read them.

A draft leaves low-quality renders in `content/`: run the full render before deploying, or
`git checkout -- content/spaces/<space> content/spaces/index.json` to discard them
(`scripts/deploy.sh` refuses to deploy until then; the preview reminds you).

## Deploying

The site is famousdesks.com, served as Cloudflare Workers static assets (`web/wrangler.jsonc`).
Deploy with `scripts/deploy.sh` (or `cd web && npm run deploy -- <flags>`):

```sh
scripts/deploy.sh --dry-run   # build and validate with wrangler, upload nothing
scripts/deploy.sh             # deploy HEAD of main, then check the live site
scripts/deploy.sh --push      # ...and push main to GitHub if the checks pass
scripts/deploy.sh --check     # only check the live site against HEAD (no build, no deploy)
```

It refuses to run unless HEAD is on main with no uncommitted changes under `web/` or
`content/spaces/` (`--force` overrides; `--ref <commit>` deploys another commit). It builds
from a temporary git worktree of the commit, because the site's static assets are `../content`
and a build in the working folder would ship half-written renders or untracked spaces. Wrangler
4 needs Node 22, which the script runs through `npx -p node@22` without changing the system Node
(`web/.nvmrc` says 22 for nvm users). After deploying it checks the home page and its share tags,
`/spaces/index.json`, `favicon.svg`, and that a panorama's live bytes match the committed file,
and exits non-zero if any check fails. You need to be logged in to Cloudflare (`npx wrangler login`)
for a real deploy; a dry run needs no login.

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
