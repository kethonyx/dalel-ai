# Модель на кластере Shabyt (HPC NU)

Сервис (FastAPI, ffmpeg, правила) остаётся на Mac. На кластере работает только
`llama-server` с Qwen3-VL-30B-A3B на одной V100 32 ГБ. Mac ходит к нему через SSH-туннель,
поэтому для сервиса модель по-прежнему висит на `127.0.0.1:8080`.

```
Mac: FastAPI ── 127.0.0.1:8080 ══ SSH (VPN NU) ══► lgn01 ══► узел NVIDIA: llama-server
```

Перед использованием на проверке жюри: согласовать с организаторами (ТЗ, раздел 7) и с
руководителем / hpcadmin@nu.edu.kz (политика HPC: «university research or teaching»).

## 1. Скопировать файлы на кластер (с Mac)

```bash
scp -r hpc <логин>@shabyt.nu.edu.kz:~/dalel-hpc
```

## 2. Сборка и модель (на lgn01, один раз, ~30–60 мин)

```bash
bash ~/dalel-hpc/setup.sh
```

Собирает llama.cpp `b11669` с CUDA 12.6 под V100 (sm_70), качает модель (~19 ГБ) в
`~/dalel/models`, создаёт ключ сервера `~/.dalel_key`.

## 3. Запуск сервера модели

```bash
sbatch ~/dalel-hpc/serve.sbatch
squeue -u $USER                  # ST=R — работает, NODELIST — имя узла
cat dalel-vlm-<JOBID>.log        # там готовая команда туннеля
```

Задача живёт до 2 суток (лимит раздела NVIDIA). Остановить: `scancel <JOBID>`.

## 4. Туннель и сервис (на Mac)

```bash
ssh -N -L 8080:<узел>:8080 <логин>@shabyt.nu.edu.kz
```

В другой вкладке (ключ скопировать из `~/.dalel_key` на кластере, в репозиторий не класть):

```bash
export VLM_BACKEND=openai_local VLM_BASE_URL=http://127.0.0.1:8080/v1 VLM_API_KEY=<ключ>
curl -s -H "Authorization: Bearer $VLM_API_KEY" http://127.0.0.1:8080/v1/models
```

Дальше сервис или `scripts/eval.py` запускаются как обычно. Кэш ответов разделён по имени
модели, ответы 4B (Mac) и 30B (кластер) не смешиваются.
