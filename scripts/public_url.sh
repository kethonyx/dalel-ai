#!/usr/bin/env bash
# Публичный адрес для жюри через pinggy (SSH на порт 443: в сети кампуса Cloudflare Tunnel
# блокируется — закрыт порт 7844, а localhost.run режет скорость до ~25 КБ/с).
# Бесплатный туннель живёт 60 минут: скрипт переподключается сам, адрес при этом меняется.
# Текущий адрес: curl -s http://127.0.0.1:4300/urls  (дублируется в ~/.dalel_public_url)
while true; do
  ( sleep 8; curl -s -m 5 http://127.0.0.1:4300/urls > ~/.dalel_public_url ) &
  ssh -p 443 -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
      -L4300:localhost:4300 -R0:127.0.0.1:8000 a.pinggy.io
  sleep 2
done
