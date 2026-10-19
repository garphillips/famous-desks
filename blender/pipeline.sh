#!/bin/sh
# Build a room, then export its tour data, panoramas and floor plan to content/.
#
#   blender/pipeline.sh jobs_room            full quality
#   blender/pipeline.sh jobs_room --draft    quick low-res renders for checking layout
#   blender/pipeline.sh jobs_room --no-render  data only (hotspot/viewpoint changes)
set -e

BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ROOM="${1:?usage: pipeline.sh <room> [--draft|--no-render]}"
shift

case "$1" in
  --draft) EXPORT_ARGS="--samples 16 --scale 50" ;;
  --no-render) EXPORT_ARGS="--no-render" ;;
  *) EXPORT_ARGS="--samples 64" ;;
esac

"$BLENDER" -b --factory-startup -P "$ROOT/blender/build.py" -- "$ROOM"
"$BLENDER" -b "$ROOT/blender/build/$ROOM.blend" -P "$ROOT/blender/export.py" -- $EXPORT_ARGS
