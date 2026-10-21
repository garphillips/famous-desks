#!/bin/sh
# Preview a room change in one command: draft-render the viewpoints, screenshot the
# comparison views in blender/rooms/<room>.views.json, sheet them beside the photos.
#
#   scripts/preview.sh jobs_room                  every listed view
#   scripts/preview.sh jobs_room office,desk      only views on these viewpoints
#   scripts/preview.sh jobs_room --views desk-display --restore
#
# --help for all options. The work is in preview.mjs.
exec node "$(dirname "$0")/preview.mjs" "$@"
