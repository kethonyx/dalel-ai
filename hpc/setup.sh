#!/bin/bash
# Один раз на login-узле Shabyt: сборка llama.cpp под V100 и скачивание модели.
#   bash hpc/setup.sh
# Компиляция на login-узле разрешена политикой HPC NU («compilation and short tests»).
set -euo pipefail

LLAMA_TAG=b11669                       # та же версия, что на Mac (brew llama.cpp 0.7.0)
ROOT=${DALEL_ROOT:-$HOME/dalel}
MODEL_REPO=Qwen/Qwen3-VL-30B-A3B-Instruct-GGUF
MODEL_FILE=Qwen3VL-30B-A3B-Instruct-Q4_K_M.gguf          # 18.6 ГБ
MMPROJ_FILE=mmproj-Qwen3VL-30B-A3B-Instruct-Q8_0.gguf    # 0.7 ГБ

# CUDA 12.x: в CUDA 13 убрана поддержка Volta (V100, sm_70)
module purge
module load GCC/13.3.0 CUDA/12.6.0 CMake/3.29.3-GCCcore-13.3.0

mkdir -p "$ROOT/models"
cd "$ROOT"

if [ ! -x llama.cpp/build/bin/llama-server ]; then
  [ -d llama.cpp ] || git clone --depth 1 --branch "$LLAMA_TAG" https://github.com/ggml-org/llama.cpp.git
  # GGML_NATIVE=OFF: собираем на login-узле, а запускаем на GPU-узле с другим CPU
  cmake -S llama.cpp -B llama.cpp/build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=70 \
        -DGGML_NATIVE=OFF -DLLAMA_CURL=OFF -DCMAKE_BUILD_TYPE=Release
  cmake --build llama.cpp/build --target llama-server -j 8
fi
# Не запускаем: на login-узле нет GPU и libcuda.so.1, проверка будет на GPU-узле в serve.sbatch
ls -l llama.cpp/build/bin/llama-server

for f in "$MODEL_FILE" "$MMPROJ_FILE"; do
  if [ ! -s "models/$f" ]; then
    curl -L --fail -C - -o "models/$f.part" "https://huggingface.co/$MODEL_REPO/resolve/main/$f"
    mv "models/$f.part" "models/$f"
  fi
done
ls -lh models

# Ключ, которым закрыт сервер модели (узел виден другим пользователям кластера)
if [ ! -s "$HOME/.dalel_key" ]; then
  (umask 077; openssl rand -hex 24 > "$HOME/.dalel_key")
fi
echo "Готово. Ключ сервера лежит в ~/.dalel_key (права 600)."
