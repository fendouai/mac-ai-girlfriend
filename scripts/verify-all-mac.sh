#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python - <<'PY'
import time,json,urllib.request
for _ in range(60):
    try:
        with urllib.request.urlopen('http://127.0.0.1:7860/api/health',timeout=2) as response:
            state=json.load(response)
        if state.get('startup_error'):
            raise SystemExit(state['startup_error'])
        if state.get('engines_ready'):
            break
    except OSError:
        pass
    time.sleep(1)
else:
    raise SystemExit('Local engine startup timed out')
PY
uv pip check --python .venv/bin/python
.venv/bin/python scripts/verify-voice.py
.venv/bin/python scripts/verify-playback.py
.venv/bin/python scripts/verify-interrupt.py
if .venv/bin/python - <<'PYCONFIG'
import sys,yaml
with open('config.mac.yaml') as f:
    sys.exit(0 if yaml.safe_load(f).get('avatar',{}).get('id') == 'hex_original_motion' else 1)
PYCONFIG
then
  .venv/bin/python scripts/verify-motion.py
fi

.venv/bin/python scripts/verify-face-assets.py
.venv/bin/python scripts/verify-mouth-compositor.py
node scripts/verify-browser-playback.mjs
HEX_VERIFY_TRANSPORT=browser .venv/bin/python scripts/verify-voice.py
