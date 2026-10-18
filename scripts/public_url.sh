#!/usr/bin/env bash
# Публичный адрес через pinggy (SSH на порт 443: в сети кампуса Cloudflare Tunnel
# блокируется — закрыт порт 7844, а localhost.run режет скорость до ~25 КБ/с).
#
#   ./scripts/public_url.sh            # API жюри: порт 8000, токен ~/.dalel_pinggy_token
#   ./scripts/public_url.sh front      # фронт:    порт 4173, токен ~/.dalel_pinggy_token_front
#
# С токеном Pro (файл в домашней папке, не в репозитории) — без лимита 60 минут и с постоянным
# адресом. Один токен — один туннель: для фронта нужен второй токен. Без токена — бесплатный
# туннель на 60 минут, скрипт переподключается сам, адрес при этом меняется.
# Текущий адрес: ~/.dalel_public_url (API) или ~/.dalel_public_url_front (фронт).
if [ "${1:-}" = front ]; then
  port=4173 dbg=4301 token=~/.dalel_pinggy_token_front out=~/.dalel_public_url_front
else
  port=8000 dbg=4300 token=~/.dalel_pinggy_token out=~/.dalel_public_url
fi
if [ -s "$token" ]; then
  dest="$(tr -d '[:space:]' < "$token")@pro.pinggy.io"
else
  dest=a.pinggy.io
fi
while true; do
  ( sleep 8; curl -s -m 5 "http://127.0.0.1:$dbg/urls" > "$out" ) &
  ssh -p 443 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
      -L"$dbg":localhost:4300 -R0:127.0.0.1:"$port" "$dest"
  sleep 2
done
