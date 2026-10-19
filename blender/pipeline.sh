#!/bin/sh
# Build a room, then export its tour data, panoramas and floor plan to content/.
#
#   blender/pipeline.sh jobs_room              full quality: 2560 px cube faces (~8K equirect), 4 tile levels
#   blender/pipeline.sh jobs_room --draft      quick check: 1024 px faces, 2 tile levels, 2048 equirect
#   blender/pipeline.sh jobs_room --no-render  data only (hotspot/viewpoint changes)
#
# Extra arguments go to export.py, e.g. `--only office` or `--face-size 3072`.
# Panorama tiling needs Node and web/node_modules (run `npm ci` in web/ once).
set -e

BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROOM="${1:?usage: pipeline.sh <room> [--draft|--no-render] [export.py args...]}"
shift

case "$1" in
  --draft) EXPORT_ARGS="--samples 16 --scale 50 --face-size 2048 --equirect-width 2048"; shift ;;
  --no-render) EXPORT_ARGS="--no-render"; shift ;;
  *) EXPORT_ARGS="--samples 64" ;;
esac

if [ "$EXPORT_ARGS" != "--no-render" ] && [ ! -d "$ROOT/web/node_modules/sharp" ]; then
  echo "pipeline.sh: panorama tiling needs sharp: run \`npm ci\` in web/ first" >&2
  exit 1
fi

"$BLENDER" -b --factory-startup -P "$ROOT/blender/build.py" -- "$ROOM"
"$ROOT/blender/blender.sh" -b "$ROOT/blender/build/$ROOM.blend" -P "$ROOT/blender/export.py" -- $EXPORT_ARGS "$@"
