---
name: room-render
description: Render a Famous Desks room after a change, the right way: data-only export, draft preview against the reference photos, then one full render with the Mac kept awake, then tidy up. Use this whenever a change to blender/ needs new panoramas or tour data (moved furniture, windows, materials, a new print or screen image, new hotspots or viewpoints), when the user says "render", "re-render", "preview", "show me the preview", "keep the mac awake", or asks why the site still shows the old room.
---

# Rendering a room

`blender/pipeline.sh <room> [--draft|--no-render] [export.py args]` builds `blender/build/<room>.blend` and exports into `content/spaces/<slug>/`: panoramas (6 cube faces per viewpoint, tiled into `panos/<vp>/` levels), the plan, close-ups, book patches and `space.json`. Everything goes through `blender/blender.sh`, which holds a GPU lock, so only one Blender job runs at a time; more agents won't render faster.

## Pick the smallest thing that answers the question

| Change | Command | Time |
|---|---|---|
| Hotspots, viewpoints' data, focus/close-up settings, yaw limits, summaries | `blender/pipeline.sh <room> --no-render` | ~20 s |
| Anything visible, to check it | `scripts/preview.sh <room> <viewpoints>` (draft of those viewpoints + comparison sheet) | ~3–4 min for two |
| Before shipping visible changes | `blender/pipeline.sh <room>` (full) | ~1 h for five viewpoints |

`--no-render` is deterministic: on an unchanged scene it leaves git clean. If `model.glb` files show up modified, something really changed (or a new mesh builder reintroduced bevel-order noise; see the docstring of `HeroBuilder._compact` in `blender/lib/hero.py`).

## The loop

1. **Data-only first** when you can. Review `git diff content/spaces/<slug>/space.json` and confirm only what you meant changed.
2. **Preview** visible changes: `scripts/preview.sh <room> office,desk` (or `--views name,...`, `--list` to see the room's saved views in `blender/rooms/<room>.views.json`, `--no-render` for a "before" sheet). It draft-renders, starts a dev server for this checkout if needed, screenshots each view and opens a sheet with each render beside its reference photo. Look at the sheet yourself, then show the user and say what matches the photos and what doesn't. Draft lighting is darker and grainier; judge layout and shape, not exact tone.
3. Drafts overwrite `content/` with low-quality images. `scripts/deploy.sh` refuses to ship modified tracked content, which is deliberate. Either run the full render next or discard drafts with `scripts/preview.sh ... --restore` / `git checkout -- content/spaces/<slug> content/spaces/index.json`.
4. **Full render** once the user is happy (ask; it's an hour of GPU). Run it in the background, then tie a keep-awake to it:
   ```sh
   blender/pipeline.sh <room> > <scratchpad>/render.log 2>&1; echo "exit $?"   # run_in_background
   pid=$(pgrep -f "/bin/sh blender/pipeline.sh <room>$")
   caffeinate -ims -w "$pid"                                              # run_in_background
   ```
   Tell the user: the lid must stay open or the Mac plugged in (lid-closed on battery still sleeps). Don't poll; wait for the notification. A grep that counts `Traceback` exits 1 when there are none, which shows up as a "failed" task: read the log, don't trust the status.
5. **After**: `git status --short content/ | grep -v panos/` to see non-panorama changes; look at a couple of views (tour-check skill) against the photos; commit content and code together with a message describing what changed in the room; then ship-site.

## Gotchas
- Never run `git stash`/`checkout` on `content/` while a render is writing there.
- A worktree has no `web/node_modules`; featured books need it even for `--no-render` (`npm ci` in web/ or symlink).
- Export versions every image/model URL with `?v=<sha1[:10]>` of the file, and tile pyramids with a `version`, so a deployed re-render reaches every browser immediately. Never hand-edit those hashes; re-export instead.
- Changing a shared material (e.g. `oak`) changes everything that uses it (desk, photo frames).
- If the user is asked "ready to render?", offer any last tweak in the same question (the chest colour was changed that way, saving a second hour).
