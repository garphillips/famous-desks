#!/bin/sh
# Run Blender holding the shared GPU lock, so parallel jobs render one at a time
# instead of all crawling together. Use it for anything that renders:
#
#   blender/blender.sh -b blender/build/jobs_room.blend -P blender/render.py -- --cams ref_desk_photo
#
# The lock is a directory holding the owner's PID; a lock left by a dead process is taken over.
BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
LOCK="${OFFICE_TOUR_GPU_LOCK:-$HOME/Library/Caches/office-tour/gpu.lock}"
mkdir -p "$(dirname "$LOCK")"

waited=0
until mkdir "$LOCK" 2>/dev/null; do
  owner=$(cat "$LOCK/pid" 2>/dev/null)
  if [ -n "$owner" ] && ! kill -0 "$owner" 2>/dev/null; then
    rm -rf "$LOCK"
    continue
  fi
  [ "$waited" -eq 0 ] && echo "blender.sh: waiting for the GPU (held by PID ${owner:-?})" >&2
  waited=$((waited + 1))
  sleep 2
done
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT INT TERM

"$BLENDER" "$@"
