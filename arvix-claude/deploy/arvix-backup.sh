#!/usr/bin/env bash
# Бэкап сервера на ноутбук (таймер arvix-backup.timer — каждый час). Сервер арендованный:
# его могут отключить или заблокировать, поэтому всё, без чего Arvix не поднять заново, лежит и здесь.
#
#   1. Журнал: на сервере sqlite3 .backup (целостный снимок при работающем боте) → integrity_check →
#      ~/.local/share/arvix/backups/arvix-ГГГГ-ММ-ДД.db. За день файл обновляется каждый час,
#      хранится 30 дней — потеря при смерти сервера не больше часа.
#   2. Конфиг сервера (ключи голоса, токен бота, адрес приложения) → backups/server-config.toml, права 600.
#      Его берёт deploy/sync-server.sh --init при переезде (deploy/restore-server.sh).
#   Хранилище Obsidian бэкапить не нужно: arvix-vault-sync.timer держит его копию на ноутбуке.
#
# Неудача не оставляет обрывков; если свежего снимка нет больше ARVIX_BACKUP_WARN_H часов (12),
# на рабочий стол приходит уведомление — не чаще раза в 6 часов.
#
#   deploy/arvix-backup.sh                 # хост из [remote] host в ~/.config/arvix/config.toml
#   deploy/arvix-backup.sh arvix@host      # хост явно
set -euo pipefail
CFG="${XDG_CONFIG_HOME:-$HOME/.config}/arvix/config.toml"
HOST="${1:-}"
if [[ -z "$HOST" && -f "$CFG" ]]; then
  HOST="$(python3 -c 'import sys,tomllib; print((tomllib.load(open(sys.argv[1],"rb")).get("remote") or {}).get("host",""))' "$CFG")"
fi
[[ -n "$HOST" ]] || { echo "использование: arvix-backup.sh arvix@host (или [remote] host в $CFG)"; exit 2; }
DIR="${XDG_DATA_HOME:-$HOME/.local/share}/arvix/backups"
KEEP="${ARVIX_BACKUP_KEEP:-30}"
WARN_H="${ARVIX_BACKUP_WARN_H:-12}"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST")
mkdir -p "$DIR"
OUT="$DIR/arvix-$(date +%F).db"
rm -f "$DIR"/*.part                          # обрывки прошлых неудач

warn_stale() {
  local newest age
  newest="$(ls -1t "$DIR"/arvix-*.db 2>/dev/null | head -1 || true)"
  age=$(( ( $(date +%s) - $( [[ -n "$newest" ]] && stat -c %Y "$newest" || echo 0 ) ) / 3600 ))
  (( age >= WARN_H )) || return 0
  local stamp="$DIR/.warned"
  [[ -f "$stamp" ]] && (( $(date +%s) - $(stat -c %Y "$stamp") < 6 * 3600 )) && return 0
  touch "$stamp"
  local msg="Сервер $HOST не отвечает. Последний бэкап журнала — $age ч назад. Переезд: deploy/restore-server.sh"
  echo "⚠ $msg" >&2
  command -v notify-send >/dev/null && notify-send -u critical -a Arvix "Arvix: нет свежего бэкапа" "$msg" 2>/dev/null || true
}

fail() { rm -f "$OUT.part" "$DIR/server-config.toml.part"; warn_stale; exit 1; }
trap fail ERR

"${SSH[@]}" 'f=$(mktemp); sqlite3 ~/.local/share/arvix/arvix.db ".backup $f" && cat "$f"; rm -f "$f"' > "$OUT.part"
sqlite3 "$OUT.part" "pragma integrity_check;" | grep -qx ok
EVENTS="$(sqlite3 "$OUT.part" 'select count(*) from events')"
mv "$OUT.part" "$OUT"
trap - ERR

# Конфиг — вторым: журнал уже сохранён, неудача здесь его не отменяет. Битый или пустой файл
# не затирает прошлую хорошую копию.
CONF_PART="$DIR/server-config.toml.part"
if ( umask 077; "${SSH[@]}" 'cat ~/.config/arvix/config.toml' > "$CONF_PART" ) && [[ -s "$CONF_PART" ]] \
   && python3 -c 'import sys,tomllib; tomllib.load(open(sys.argv[1],"rb"))' "$CONF_PART" 2>/dev/null; then
  chmod 600 "$CONF_PART" && mv "$CONF_PART" "$DIR/server-config.toml"
else
  rm -f "$CONF_PART"; echo "⚠ конфиг сервера не снят, прошлая копия оставлена" >&2
fi
rm -f "$DIR/.warned"

ls -1t "$DIR"/arvix-*.db | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "бэкап: $OUT ($EVENTS событий), конфиг сервера: $DIR/server-config.toml"
