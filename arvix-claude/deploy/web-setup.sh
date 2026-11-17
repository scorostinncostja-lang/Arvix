#!/usr/bin/env bash
# Приложение Арвикса наружу по HTTPS (05-INTERFACES §7.1, D26): Mini App в Telegram и PWA на телефоне.
#
#   deploy/web-setup.sh root@HOST [arvix]       # root — ставит Caddy; arvix — пользователь бота
#
# Что делает на сервере:
#   1. ставит Caddy (apt) — он сам получает и продлевает сертификат Let's Encrypt;
#   2. адрес без покупки домена: <ip-через-дефисы>.sslip.io (DNS, который отвечает самим IP);
#   3. HTTPS на порту 8443, сертификат — через порт 80. Порт 443 НЕ трогается: на нём может жить VPN;
#   4. Caddy проксирует на 127.0.0.1:8787 — туда слушает служба бота (сам API наружу не открыт);
#   5. пишет [web] public_url у пользователя бота и перезапускает бота: в Telegram появится кнопка «Арвикс».
# Повторный запуск безопасен. Чужие сайты в Caddyfile не трогаются (свой блок — в /etc/caddy/arvix.caddy).
set -euo pipefail
ROOT_HOST="${1:?использование: web-setup.sh root@HOST [пользователь-бота]}"
BOT_USER="${2:-arvix}"
PORT="${ARVIX_WEB_PORT:-8443}"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15 "$ROOT_HOST")

step() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }

IP="$("${SSH[@]}" "curl -4 -s --max-time 10 https://api.ipify.org || hostname -I | awk '{print \$1}'")"
NAME="${ARVIX_WEB_HOST:-${IP//./-}.sslip.io}"
URL="https://$NAME:$PORT"
step "Адрес приложения: $URL"

step "Caddy на сервере"
"${SSH[@]}" bash -s -- "$NAME" "$PORT" <<'REMOTE'
set -euo pipefail
NAME="$1"; PORT="$2"
if ! command -v caddy >/dev/null; then
  DEBIAN_FRONTEND=noninteractive apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq caddy >/dev/null
fi
if ss -ltn | awk '{print $4}' | grep -qE ":80$" && ! ss -ltnp | grep -E ":80 " | grep -q caddy; then
  echo "Порт 80 занят не Caddy — сертификат не получить. Освободи 80 или задай ARVIX_WEB_HOST с DNS-проверкой." >&2
  exit 1
fi
cat > /etc/caddy/arvix.caddy <<CADDY
# Арвикс: приложение (Mini App / PWA). Файл пишет deploy/web-setup.sh.
$NAME:$PORT {
	encode gzip
	reverse_proxy 127.0.0.1:8787 {
		flush_interval -1
	}
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options nosniff
		Referrer-Policy no-referrer
	}
}
CADDY
CF=/etc/caddy/Caddyfile
if [ ! -f "$CF" ] || grep -q "/usr/share/caddy" "$CF"; then
  printf '# Caddyfile. Сайты — отдельными файлами рядом.\nimport /etc/caddy/arvix.caddy\n' > "$CF"   # стоковый «привет» Caddy заменяем
elif ! grep -q "import /etc/caddy/arvix.caddy" "$CF"; then
  printf '\nimport /etc/caddy/arvix.caddy\n' >> "$CF"
fi
caddy validate --config "$CF" --adapter caddyfile >/dev/null
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null; ufw allow "$PORT"/tcp >/dev/null
fi
systemctl enable --now caddy >/dev/null 2>&1
systemctl reload caddy
echo "Caddy: $(caddy version | cut -d' ' -f1), блок /etc/caddy/arvix.caddy"
REMOTE

step "Сертификат (до 90 с)"
for i in $(seq 1 30); do
  if curl -s --max-time 5 -o /dev/null -w '%{http_code}' "$URL/manifest.webmanifest" | grep -qE "^(200|502)$"; then
    echo "HTTPS отвечает: $URL"; break
  fi
  sleep 3
  [ "$i" = 30 ] && { echo "Сертификат не получен. Лог: ssh $ROOT_HOST journalctl -u caddy -n 50"; exit 1; }
done

step "Адрес в конфиг бота и перезапуск"
"${SSH[@]}" "sudo -iu $BOT_USER bash -lc '~/.local/bin/arvix app-url $URL && XDG_RUNTIME_DIR=/run/user/\$(id -u) systemctl --user restart arvix-telegram && sleep 3 && systemctl --user is-active arvix-telegram'"
curl -s --max-time 10 -o /dev/null -w "приложение: %{http_code}\n" "$URL/"

cat <<EOF

Готово.
  Telegram: кнопка «Арвикс» слева от поля ввода в чате с ботом (или «📱 Приложение» внизу).
  Телефон:  в приложении → «Прогресс» → «Установить на телефон» → в Chrome ⋮ → «Установить приложение».
  Ноутбук:  arvix  (терминал; идёт через ssh, HTTPS не нужен)
EOF
