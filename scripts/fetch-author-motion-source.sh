#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$ROOT/models/avatar_sources/author-intro-4k.mp4"
[[ ! -f "$TARGET" ]] || { echo "已缓存：$TARGET"; exit 0; }
command -v ffmpeg >/dev/null || { echo '请先安装 ffmpeg（brew install ffmpeg）'; exit 1; }
command -v node >/dev/null || { echo '请先安装 Node.js，供 yt-dlp 解析视频'; exit 1; }
mkdir -p "$(dirname "$TARGET")"
PARTIAL="$TARGET.partial.mp4"
trap 'rm -f "$PARTIAL"' EXIT
# Network/proxy settings are inherited from the user's environment.
uvx --from 'yt-dlp[default]==2026.8.19' yt-dlp --js-runtimes node \
  -f 'bv[height=2160][ext=mp4]' --download-sections '*0-14' \
  -o "$PARTIAL" 'https://www.youtube.com/watch?v=xsh3UJ32p_w'

mv "$PARTIAL" "$TARGET"
