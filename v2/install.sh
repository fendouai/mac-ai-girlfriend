#!/usr/bin/env bash
# v2 shares the root Python env/models with v1; this is a thin wrapper.
set -euo pipefail
V2="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$V2/.." && pwd)"
cd "$ROOT"
./install.sh
echo
echo "根环境已安装。v2 的 Harness CLI 请执行: cd v2 && ./scripts/install-harness.sh"
