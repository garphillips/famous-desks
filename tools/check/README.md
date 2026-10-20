# check: headless-Chrome checks for the tour

Screenshots, interaction checks and smoke tests for the website, driven by
puppeteer-core and the system Chrome (headless, with WebGL through swiftshader).
They replace the one-off scripts every UI change used to need.

```sh
(cd tools/check && npm ci)                 # once
node tools/check/check.mjs help             # list commands and options
```

Needs Google Chrome at `/Applications/Google Chrome.app` (or set `CHROME=/path/to/chrome`)
and, for most commands, the dev server running (`cd web && npm run dev -- --port 5180`).

## When to use what

| Situation | Run |
| --- | --- |
| After any UI change | `smoke --size all` then `shot /jobs-room --size all` and look at the shots |
| Changed the minimap or the walk between viewpoints | `minimap --size desktop,phone` |
| Changed hotspots, close-ups, the detail panel or books | `closeup "The display"`, `closeup bookshelf` (`--size desktop,phone`) |
| Changed yaw limits or a viewpoint's camera | `edges` |
| Changed the music player or speaker ripples | `music --size desktop,phone` |
| Something looks juddery | `filmstrip <path> --turn -600` (or `--click <selector>`) and read the sheet |
| Re-rendered a room | `view <viewpoint> ...` for the angles you care about, then `sheet` them next to the reference photos |
| After a deploy | `smoke --base https://famousdesks.com --size all` (read-only) |

## Commands

All commands take `--base <url>` (default `http://localhost:5180`), `--size
desktop|tablet|phone|all` (or a comma list; default desktop), `--out <dir>`
(default `tools/check/out`, gitignored; each command writes into its own
`<dir>/<command>/` folder, and `--clean` empties it first) and `--space <slug>`
(default `jobs-room`). Sizes: desktop 1400×860, tablet 900×1000 (mouse), phone
390×844 (touch: taps, and drags through CDP touch events).

- **`shot <url-or-path>`**: screenshot a page once its panorama has loaded.
  `shot /jobs-room/desk --size all`
- **`view <viewpoint> [--turn <px>] [--hotspot <slug>] [--fov <deg>]`**: screenshot a
  viewpoint, aimed at a hotspot (`?h=`), zoomed (`?fov=`) and/or turned by a drag.
  Dragging right turns the view left, so `--turn -900` looks further right.
  `view desk --hotspot display --fov 45`, `view window --turn -900`
- **`closeup <title or slug> [--from <viewpoint>]`**: open a viewpoint facing the
  hotspot, click (tap) its pin, wait for the flight, screenshot the close-up, then
  open "Close-ups and 3D" (or, on the bookshelf, the first book) and screenshot that.
  Hidden hotspots (see `web/src/lib/site.ts`) have no pin and fail.
- **`minimap`**: grow the minimap (hover on desktop with a 4-frame filmstrip of the
  grow; first tap on phone, which must not move), visit every viewpoint through it,
  screenshot each arrival, and check it shrinks again.
- **`edges [--viewpoint <slug>]`**: at each viewpoint, keep dragging until the view
  stops at its left and right yaw limits, then look down; screenshot each.
- **`music [--viewpoint <slug>] [--frames N] [--every ms]`**: press play inside the
  Spotify embed, filmstrip the speaker ripples (counting drawn pixels per frame),
  press pause, and check the ripples canvas empties. Writes a contact sheet.
  Needs the network (the embed comes from open.spotify.com).
- **`filmstrip <url-or-path> [--frames N] [--every ms] [--turn px | --click <selector>]`**:
  record what Chrome actually draws (CDP screencast) during a drag, after a click, or
  idle; samples one frame per tick into a contact sheet and reports the frame rate and
  longest gap between frames. Swiftshader draws ~25-60 fps, so judge consistency of
  motion between frames, not absolute speed.
  `filmstrip /jobs-room/office --turn -600 --frames 12 --every 80`
- **`smoke [--paths /,/jobs-room/desk]`**: load each path, wait for the tiles, and
  report data-pano, viewpoint and pin counts, failed requests and page errors.
- **`sheet <img...> [--out file.png] [--labels a,b,...] [--cols N] [--width px] [--title text]`**:
  compose images into a labelled grid (rendered as HTML in the same headless Chrome,
  so no Python needed). Here `--out` is the sheet file (default `tools/check/out/sheet.png`).
  `sheet out/view/view-desk-desktop.png ~/refs/desk.jpg --labels render,photo --cols 2`

## Output

Each run prints what it did (`ok` / `FAIL` per check, notes), then failed requests,
page errors and console errors, a `PASS`/`FAIL` line, and finally **one line of JSON**:

```json
{"command":"smoke","args":[],"base":"https://famousdesks.com","ok":true,"checks":{"passed":8,"failed":[]},"failedRequests":[],"pageErrors":[],"consoleErrors":0,"files":["..."]}
```

Exit code: 0 if every check passed with no failed requests or page errors, 1 if
not, 2 for bad usage. Console errors are listed but don't fail a run (the Spotify
embed is noisy). Only requests to the `--base` origin count as failed requests;
cancelled tile requests (`net::ERR_ABORTED`) are expected and ignored.

## How it waits

Rather than fixed sleeps, a check waits for the view to stop moving (two strips
across the middle of the screen, 250 ms apart, come out identical; up to 8 s) and
then for the main canvas's `data-pano="<level>:<loaded>/<wanted>"` to show every
wanted tile loaded (or `equirect`). Both times are printed with each
"panorama loaded" check. The bookshelf close-up never looks still (the
highlighted books pulse), so checks that end up there (the minimap lands in it,
and `closeup bookshelf`) report `still after >8000 ms`; that is expected.

## Files

- `check.mjs`: the CLI and the commands.
- `lib.mjs`: launching Chrome, sizes, `waitForPano`, `settle`, `turn`, `press`/`hover`,
  screenshots, `filmstrip`, `screencast`, `inkPixels` and `contactSheet`; import it
  for a one-off script instead of starting from scratch.
