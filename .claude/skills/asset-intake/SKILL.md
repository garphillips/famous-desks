---
name: asset-intake
description: Bring any third-party or user-supplied file into Famous Desks with its licence checked and recorded: textures, 3D models, HDRIs, photos and prints for frames, book covers, screen images, icons, fonts, audio, music. Use this whenever the user shares an image or link to put in the room ("update the print to this", "use this for the screen", "here's the wallpaper"), you're about to download an asset, add a font or icon set, or anything touches blender/assets/manifest/, even if they don't mention licensing.
---

# Asset intake

The user cares about licensing (a personal site that may earn money later). Every asset has a paper trail in `blender/assets/manifest/*.json`; the files themselves live in a cache outside the repo (`~/Library/Caches/office-tour/assets/<asset id>/`, or `$OFFICE_TOUR_ASSETS`). `python3 -I blender/assets/fetch.py` downloads anything missing; `--check` lists what's missing. Room code reads files through `lib/assets.path(asset_id, name)` / `hero.photo_pixels(...)`, which fall back to a generated stand-in when a file is absent.

## Allowed licences
- `CC0` and `CC-BY-4.0`: the default for textures, models, HDRIs, photos (Poly Haven is the usual source; record author and page).
- `cover-art` (kind `cover`): publishers' covers from Open Library, shown only to identify a book.
- `all-rights-reserved` (kind `artwork`): **only** with the user's explicit decision after you've flagged it. Current examples: the Ansel Adams print over the desk (NGA 66721, not open access), shown on the wall only, with no hotspot, close-up or caption; and the Mac OS X desktop on the display (Apple logo and icons), supplied by the user.
- Fonts: OFL or Apache-2.0 (Archivo; Special Elite for the typewritten letter), via Fontsource packages pinned exactly. Icons: Phosphor (MIT), inlined.
- Music: never hosted. Only Spotify's official embed.
- Never NC licences for anything.

## When the user supplies or names an image
1. Find out what it is and who holds the rights. For artworks, look the work up (e.g. the National Gallery of Art's open data on GitHub has an `openaccess` flag per image; their website blocks scripts). For screenshots/renders, look for logos, UI and trademarks.
2. If it's not CC0/CC-BY, **say so plainly before using it**, with the consequences (it becomes public in panoramas and the public repo; a full re-render costs ~1 h), and ask with options: keep a placeholder with a credit, find a CC0 look-alike, or use it anyway logged as unlicensed. If the user changes their mind ("no no I answered wrong"), ask again rather than guess.
3. Copy user-supplied files into the cache by hand (`mkdir -p <cache>/<asset id> && cp ...`), never into the repo. Private references (`starter/`, `~/Downloads/`) are never committed or copied into the repo.
4. Add the manifest entry: `kind, title, source, page, author, license, files[{name, url}]`. A file without a URL gets `"supplied": "<how>"` instead (fetch.py tells you to copy it by hand if missing). Unlicensed ones also get `credit` and a `note` saying to license or replace before the site earns money.
5. Run `fetch.py --check` (expect 0 missing) and record exceptions in the asset-licensing memory file.

## Fitting images in
- Prints: `desk.bw_print(...)` crops and tones a CC0 photo into a black-and-white print; `as_is=True` keeps a real photographer's tones (only crop + paper colour). Match the crop's aspect to the mount window so nothing stretches.
- Screens: `hero._desktop` loads `screen_desktop` and fits it to the 16:10 screen (squeezing slightly rather than cropping logos or icons off).
- Small framed snapshots: crops of CC0 photos defined in `desk.SNAPSHOTS` (no people's faces needed).
- Check the result in a draft preview (room-render skill) before the full render.
