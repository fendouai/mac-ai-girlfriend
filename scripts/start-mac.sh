#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -x .venv/bin/python ]] || { echo '请先执行 uv venv --python 3.11 && uv pip install --python .venv/bin/python -r requirements-mac.lock.txt'; exit 1; }
curl -fsS --max-time 3 http://127.0.0.1:8200/v1/models >/dev/null || { echo '请先在 LM Studio 加载模型并启动端口 8200 的本地 API 服务'; exit 1; }
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PYTORCH_ENABLE_MPS_FALLBACK=1
export OMP_NUM_THREADS=4
mkdir -p logs
avatar_pid=''
server_pid=''
cleanup() {
  [[ -z "$server_pid" ]] || kill "$server_pid" 2>/dev/null || true
  [[ -z "$avatar_pid" ]] || kill "$avatar_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM
if ! curl -fsS --max-time 2 http://127.0.0.1:8010/index.html >/dev/null; then
  ./scripts/start-avatar-mac.sh > logs/avatar-mac.log 2>&1 &
  avatar_pid=$!
  ready=0
  for ((i=0;i<90;i++)); do
    kill -0 "$avatar_pid" 2>/dev/null || { tail -30 logs/avatar-mac.log; exit 1; }
    if curl -fsS --max-time 1 http://127.0.0.1:8010/index.html >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
  done
  [[ "$ready" = 1 ]] || { echo '数字人启动超时，查看 logs/avatar-mac.log'; exit 1; }
fi
printf '数字人已就绪。浏览器打开 http://localhost:7860\n'
.venv/bin/python src/server.py --config config.mac.yaml &
server_pid=$!
wait "$server_pid"
