#!/bin/bash
# Сервер модели на узле с V100: sbatch hpc/serve.sbatch
#SBATCH --job-name=dalel-vlm
#SBATCH --partition=NVIDIA
#SBATCH --account=stud
#SBATCH --qos=qos_stud
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=2-00:00:00
#SBATCH --output=%x-%j.log
set -euo pipefail

ROOT=${DALEL_ROOT:-$HOME/dalel}
PORT=${DALEL_PORT:-8080}
module purge
module load GCC/13.3.0 CUDA/12.6.0

echo "NODE=$(hostname -s) PORT=$PORT JOB=$SLURM_JOB_ID"
echo "Туннель с Mac: ssh -N -L 8080:$(hostname -s):$PORT $USER@shabyt.nu.edu.kz"
nvidia-smi -L
"$ROOT/llama.cpp/build/bin/llama-server" --version

# --host 0.0.0.0 нужен, чтобы туннель через login-узел достал до узла;
# поэтому сервер закрыт ключом (~/.dalel_key), без него он отвечает 401.
exec "$ROOT/llama.cpp/build/bin/llama-server" \
  -m "$ROOT/models/Qwen3VL-30B-A3B-Instruct-Q4_K_M.gguf" \
  --mmproj "$ROOT/models/mmproj-Qwen3VL-30B-A3B-Instruct-Q8_0.gguf" \
  --host 0.0.0.0 --port "$PORT" --api-key-file "$HOME/.dalel_key" \
  -ngl 99 -c 8192 -np 1
