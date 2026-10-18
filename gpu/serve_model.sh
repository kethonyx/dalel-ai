#!/bin/bash
# Сервер модели на GPU-компьютере: bash gpu/serve_model.sh
set -euo pipefail

ROOT=${DALEL_ROOT:-$HOME/dalel}
PORT=${DALEL_PORT:-8080}
HOST=${DALEL_HOST:-127.0.0.1}   # 127.0.0.1 — доступ только через SSH-туннель; 0.0.0.0 — из локальной сети

nvidia-smi -L || true
echo "Туннель с компьютера сервиса: ssh -N -L 8080:127.0.0.1:$PORT <логин>@<этот компьютер>"

# Сервер закрыт ключом (~/.dalel_key): без него отвечает 401.
exec "$ROOT/llama.cpp/build/bin/llama-server" \
  -m "$ROOT/models/Qwen3VL-30B-A3B-Instruct-Q4_K_M.gguf" \
  --mmproj "$ROOT/models/mmproj-Qwen3VL-30B-A3B-Instruct-Q8_0.gguf" \
  --host "$HOST" --port "$PORT" --api-key-file "$HOME/.dalel_key" \
  -ngl 99 -c 8192 -np 1
