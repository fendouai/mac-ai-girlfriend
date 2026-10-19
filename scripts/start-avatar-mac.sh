#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -z "${AVATAR_ID:-}" ]]; then
  AVATAR_ID="$("$ROOT/.venv/bin/python" - "$ROOT/config.mac.yaml" <<'CONFIG'
import sys, yaml
with open(sys.argv[1]) as f:
    print(yaml.safe_load(f).get('avatar', {}).get('id', 'hex_original'))
CONFIG
)"
fi
[[ "$AVATAR_ID" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo '无效的数字人 ID'; exit 1; }
cd "$ROOT/third_party/livetalking"
[[ -f models/wav2lip.pth && -f data/avatars/$AVATAR_ID/coords.pkl ]] || {
  echo '缺少 Wav2Lip 模型或数字人形象，请参阅 README_MAC.md'; exit 1;
}
export PYTORCH_ENABLE_MPS_FALLBACK=1
export OMP_NUM_THREADS=4
exec "$ROOT/.venv/bin/python" app.py --transport webrtc --model wav2lip \
  --avatar_id "$AVATAR_ID" --batch_size 4 --max_session 2 --stun '' --listenport 8010
