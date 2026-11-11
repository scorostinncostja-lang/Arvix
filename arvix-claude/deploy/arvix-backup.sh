#!/usr/bin/env bash
# Бэкап журнала Арвикса с сервера на ноутбук (раз в сутки, таймер arvix-backup.timer).
# Снимок делается на сервере через sqlite3 .backup — целостный даже при работающем боте.
# Хранится 14 последних копий в ~/.local/share/arvix/backups/.
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
mkdir -p "$DIR"
OUT="$DIR/arvix-$(date +%F).db"
ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" \
  'f=$(mktemp); sqlite3 ~/.local/share/arvix/arvix.db ".backup $f" && cat "$f"; rm -f "$f"' > "$OUT.part"
sqlite3 "$OUT.part" "pragma integrity_check;" | grep -qx ok
mv "$OUT.part" "$OUT"
ls -1t "$DIR"/arvix-*.db | tail -n +15 | xargs -r rm -f
echo "бэкап: $OUT ($(sqlite3 "$OUT" 'select count(*) from events') событий)"
