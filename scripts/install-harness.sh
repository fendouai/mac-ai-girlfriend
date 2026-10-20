#!/usr/bin/env bash
# Install the pinned DeepSeek Harness CLI used by v2 (local, no global npm).
set -euo pipefail
cd "$(dirname "$0")/.."

command -v node >/dev/null || { echo '缺少 Node.js（建议 22+）'; exit 1; }
command -v npm >/dev/null || { echo '缺少 npm'; exit 1; }

VERSION="0.2.1-rc.2"
if command -v dsh >/dev/null 2>&1; then
  echo "已找到 dsh: $(command -v dsh)"
  dsh --version
  exit 0
fi

mkdir -p .harness-cli
export npm_config_cache="$PWD/.harness-cli/.npm-cache"

PKG_DIR=".harness-cli/node_modules/@deepseek-ai/dsh"
if [[ ! -f "$PKG_DIR/lib/bin.js" ]]; then
  # --ignore-scripts keeps the CLI install bounded; the headless runner does
  # not need the desktop native terminal modules.
  npm install --prefix .harness-cli --ignore-scripts --no-audit --no-fund \
    "@deepseek-ai/dsh@${VERSION}"
fi

DSH_BIN="$PWD/.harness-cli/node_modules/.bin/dsh"
if [[ ! -x "$DSH_BIN" ]]; then
  mkdir -p .harness-cli/node_modules/.bin
  ln -sf ../@deepseek-ai/dsh/lib/bin.js .harness-cli/node_modules/.bin/dsh
  chmod +x "$PKG_DIR/lib/bin.js"
fi
[[ -x "$DSH_BIN" ]] || { echo "安装后找不到 $DSH_BIN"; exit 1; }

echo
echo "DSH CLI: $DSH_BIN"
"$DSH_BIN" --version
echo
echo "下一步："
echo "  1. 把 DEEPSEEK_API_KEY 写入项目 .env（或导出到环境变量）"
echo "  2. 确保 .env / API key 可用后，重启 ./scripts/start-mac.sh"
echo "  3. Harness 默认以 ./scripts/start-mac.sh 的 cwd 为项目根；"
echo "     v2 配置里的 dsh_home 是 ./.dsh-home，workspace 是 ~/Documents/HexHarnessWorkspace"
echo
echo "如果希望手动运行，可执行："
echo "  export PATH=\"$PWD/.harness-cli/node_modules/.bin:\$PATH\""
