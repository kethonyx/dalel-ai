#!/bin/bash
# Один раз на GPU-компьютере: сборка llama.cpp с CUDA и скачивание модели.
#   bash gpu/setup.sh
# Нужны git, cmake, компилятор C++ и CUDA 12.x (для старых карт, например Volta, CUDA 13 не подходит).
set -euo pipefail

LLAMA_TAG=b11669                       # та же версия, что на Mac (brew llama.cpp 0.7.0)
ROOT=${DALEL_ROOT:-$HOME/dalel}
CUDA_ARCH=${CUDA_ARCH:-native}         # архитектура видеокарты; native — та, на которой собираем
MODEL_REPO=Qwen/Qwen3-VL-30B-A3B-Instruct-GGUF
MODEL_FILE=Qwen3VL-30B-A3B-Instruct-Q4_K_M.gguf          # 18.6 ГБ
MMPROJ_FILE=mmproj-Qwen3VL-30B-A3B-Instruct-Q8_0.gguf    # 0.7 ГБ

mkdir -p "$ROOT/models"
cd "$ROOT"

if [ ! -x llama.cpp/build/bin/llama-server ]; then
  [ -d llama.cpp ] || git clone --depth 1 --branch "$LLAMA_TAG" https://github.com/ggml-org/llama.cpp.git
  cmake -S llama.cpp -B llama.cpp/build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES="$CUDA_ARCH" \
        -DLLAMA_CURL=OFF -DCMAKE_BUILD_TYPE=Release
  cmake --build llama.cpp/build --target llama-server -j 8
fi
ls -l llama.cpp/build/bin/llama-server

for f in "$MODEL_FILE" "$MMPROJ_FILE"; do
  if [ ! -s "models/$f" ]; then
    curl -L --fail -C - -o "models/$f.part" "https://huggingface.co/$MODEL_REPO/resolve/main/$f"
    mv "models/$f.part" "models/$f"
  fi
done
ls -lh models

# Ключ, которым закрыт сервер модели
if [ ! -s "$HOME/.dalel_key" ]; then
  (umask 077; openssl rand -hex 24 > "$HOME/.dalel_key")
fi
echo "Готово. Ключ сервера лежит в ~/.dalel_key (права 600)."
