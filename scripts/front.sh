#!/usr/bin/env bash
# Собранный фронт на 127.0.0.1:4173 (vite preview). /ui и /api/v1 проксируются на сервис :8000,
# заголовок X-API-Key подставляет прокси — ключ в браузер не попадает.
set -euo pipefail
cd "$(dirname "$0")/../front"
[ -d node_modules ] || npm install --no-audit --no-fund
npm run build
API_KEY=$(cat ~/.dalel_jury_key) exec npx vite preview --host 127.0.0.1 --port 4173 --strictPort
