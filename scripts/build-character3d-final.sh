#!/usr/bin/env bash
# Reassemble/validate the already generated body and facial assets; no ML weights loaded.
set -euo pipefail
cd "$(dirname "$0")/.."
blender_app=${BLENDER_BIN:-/Applications/Blender.app/Contents/MacOS/Blender}
[[ -x "$blender_app" ]] || { echo 'Blender 4.5 LTS is required; set BLENDER_BIN.'; exit 1; }
.venv-3d/bin/python scripts/verify-character3d-geometry.py
mkdir -p logs
"$blender_app" --background --python scripts/assemble-character3d-blender.py > logs/character3d-assemble.log 2>&1
rg -q CUSTOM_AVATAR_ASSEMBLED logs/character3d-assemble.log
"$blender_app" --background --python scripts/polish-character3d-blender.py > logs/character3d-polish.log 2>&1
rg -q CUSTOM_AVATAR_POLISHED logs/character3d-polish.log
.venv-3d/bin/python scripts/export-character3d-vrm.py --source models/character3d-work/sweet-polished.glb
.venv-3d/bin/python scripts/verify-character3d-asset.py
node scripts/verify-body-motion.mjs web/assets/models/sweet-realistic.vrm
