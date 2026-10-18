#!/usr/bin/env bash
# Боевой запуск: PostgreSQL, сервис на :8000 с моделью (основная 30B через туннель, запасная 8B).
# Ключи не в репозитории, а в файлах домашней папки:
#   ~/.dalel_jury_key   — ключ X-API-Key для жюри (создаётся при первом запуске)
#   ~/.dalel_key        — ключ llama-server на GPU-компьютере (основная модель)
#   ~/.dalel_key_friend — ключ запасного llama-server (необязательно)
# Адреса моделей можно переопределить: PRIMARY_URL, BACKUP_URL.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -s ~/.dalel_jury_key ] || { python3 -c "import secrets;print(secrets.token_urlsafe(32))" > ~/.dalel_jury_key; chmod 600 ~/.dalel_jury_key; }

PRIMARY_URL=${PRIMARY_URL:-http://127.0.0.1:8080/v1}
BACKUP_URL=${BACKUP_URL:-http://10.70.54.255:8080/v1}
urls=$PRIMARY_URL keys=$(cat ~/.dalel_key)
if [ -s ~/.dalel_key_friend ] && [ -n "$BACKUP_URL" ]; then
  urls="$urls,$BACKUP_URL" keys="$keys,$(cat ~/.dalel_key_friend)"
fi

export POSTGRES_PORT=${POSTGRES_PORT:-5434}  # 5433 часто занят другими проектами
export DATABASE_URL=${DATABASE_URL:-postgresql://dalel:dalel_dev_password@127.0.0.1:$POSTGRES_PORT/dalel}
docker compose up -d --wait db

# фронт отдаётся самим сервисом на "/" (вход в API по cookie сессии интерфейса)
if [ ! -f front/dist/index.html ] && command -v npm >/dev/null; then
  (cd front && { [ -d node_modules ] || npm install --no-audit --no-fund; } && npm run build)
fi

export API_KEY=$(cat ~/.dalel_jury_key)
export VLM_BACKEND=openai_local VLM_BASE_URL=$urls VLM_API_KEY=$keys
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
