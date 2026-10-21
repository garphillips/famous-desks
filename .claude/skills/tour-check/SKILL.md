---
name: tour-check
description: Verify the Famous Desks website in a real (headless) browser before saying a change works: screenshots at desktop/tablet/phone, close-up flights, minimap, view limits, music and ripples, smoothness filmstrips, live-site smoke tests, and comparison sheets against reference photos. Use this after any change under web/, after any export or render, after deploying, when the user reports something looks wrong, juddery or broken, or asks "show me" / "does it work on mobile", even if they don't ask for tests.
---

# Checking the tour

`tools/check/` is a puppeteer-core CLI that drives the system Chrome headlessly (WebGL via swiftshader). Setup once: `(cd tools/check && npm ci)`. Most commands need the dev server (`cd web && npx vite dev --port 5180 --strictPort`, usually already running); `--base https://famousdesks.com` checks production read-only. Full docs: `tools/check/README.md`.

```sh
node tools/check/check.mjs <command> [args] [--size desktop|tablet|phone|all] [--base url] [--clean]
```
Output goes to `tools/check/out/<command>/` (gitignored); each run prints ok/FAIL lines and a JSON summary; exit 0/1/2.

## What to run when

| Change | Run |
|---|---|
| Any UI change | `smoke --size all`, then `shot /jobs-room --size all` and look at the shots |
| Minimap, walking between viewpoints | `minimap --size desktop,phone` |
| Hotspots, close-ups, panels, books | `closeup "<title>" --size desktop,phone`, `closeup bookshelf` |
| Yaw limits, viewpoints | `edges` |
| Music player, ripples | `music --size desktop,phone` |
| Anything animated ("juddery", "staggered") | `filmstrip <path> --turn -600` or `--click <selector>`, then read the sheet and report fps and the longest gap |
| A re-render | `view <viewpoint> --yaw <deg> [--pitch] [--fov]`, or `scripts/preview.sh` for photo comparisons |
| After deploying | `smoke --base https://famousdesks.com --size all` |

## Look, don't just count
Passing checks prove things loaded; they don't prove it looks right. Always open a few screenshots with the Read tool, and for anything visual show the user (open them on the Mac with `open <file>`; combine views with `sheet <img...> --out <file> --labels ...`). Things automated checks missed today but screenshots caught: the minimap covering a book panel on phones, rings too faint on white brick, a display cut off on portrait screens.

## Know the app's behaviours (so a check isn't wrongly "failing")
- On touch screens the minimap's first tap only opens it; on desktop it opens on hover.
- Hidden hotspots (`site.hiddenHotspots`) have no pin, so `closeup <hidden>` fails by design.
- The bookshelf close-up never goes still (spines pulse); waits time out with a note but pass.
- Panorama loads report via the canvas's `data-pano="<level>:<loaded>/<wanted>"`.
- `/jobs-room/bookshelf` loaded directly doesn't open the book close-up; the minimap or the pin does.
- If a check shows SvelteKit's 500 page once and the rerun passes, note it (the dev server may have reloaded mid-run) and look at the printed stack if it recurs.

## Smoothness
The user notices staggered motion (several separate moves where they expect one). When you change an animation, record a filmstrip and look at the frames: one continuous move, no jumps, no pauses between phases.
