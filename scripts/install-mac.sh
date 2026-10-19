#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "$(uname -s)" = Darwin && "$(uname -m)" = arm64 ]] || { echo '此脚本用于 Apple Silicon Mac'; exit 1; }
command -v uv >/dev/null || { echo '缺少 uv，请先从 https://docs.astral.sh/uv/getting-started/installation/ 安装'; exit 1; }
[[ -x .venv/bin/python ]] || uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements-mac.lock.txt
if [[ ! -f models/CosyVoice2-0.5B/llm.pt || ! -f models/SenseVoiceSmall/model.pt || ! -f models/wav2lip256.pth ]]; then
  .venv/bin/python scripts/download-voice-models.py
fi
mkdir -p third_party/livetalking/models
cp models/wav2lip256.pth third_party/livetalking/models/wav2lip.pth
SFD="third_party/livetalking/avatars/wav2lip/face_detection/detection/sfd/s3fd.pth"
SFD_HASH='619a31681264d3f7f7fc7a16a42cbbe8b23f31a256f75a366e5a1bcd59b33543'
if ! printf '%s  %s\n' "$SFD_HASH" "$SFD" | shasum -a 256 -c - >/dev/null 2>&1; then
  curl -fL --retry 3 'https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth' -o "$SFD.partial"
  printf '%s  %s\n' "$SFD_HASH" "$SFD.partial" | shasum -a 256 -c -
  mv "$SFD.partial" "$SFD"
fi
.venv/bin/python scripts/prepare-original-avatar.py
[[ -d models/wav2lip256-b4.mlpackage ]] || .venv/bin/python scripts/convert-avatar-coreml.py
[[ -d models/cosyvoice2-flow.mlpackage ]] || .venv/bin/python scripts/convert-cosyvoice-flow-coreml.py
# Prepare the two clean facial characters; runtime does not need LivePortrait.
if [[ ! -f third_party/livetalking/data/avatars/hex_clean_original/source.json || ! -f third_party/livetalking/data/avatars/hex_clean_sweet/source.json ]]; then
  LP_REVISION=9b294b3d0536135442ea73cb01e6cb3ca7029dd3
  if [[ ! -d third_party/LivePortrait/.git ]]; then
    git clone --no-checkout https://github.com/KlingTeam/LivePortrait.git third_party/LivePortrait
    git -C third_party/LivePortrait fetch --depth 1 origin "$LP_REVISION"
    git -C third_party/LivePortrait checkout --detach "$LP_REVISION"
  fi
  .venv/bin/python scripts/download-liveportrait-models.py
  PYTORCH_ENABLE_MPS_FALLBACK=1 .venv/bin/python scripts/prepare-face-avatars.py
fi
echo 'Mac 环境已安装。LM Studio 加载本地模型并开启 8200 端口后运行 ./scripts/start-mac.sh'
