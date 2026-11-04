#!/usr/bin/env bash
# Бэкап журнала Арвикса с сервера на ноутбук (раз в сутки, таймер arvix-backup.timer).
# Снимок делается на сервере через sqlite3 .backup — целостный даже при работающем боте.
# Хранится 14 последних копий в ~/.local/share/arvix/backups/.
set -euo pipefail
HOST="${1:?использование: arvix-backup.sh arvix@host}"
DIR="${XDG_DATA_HOME:-$HOME/.local/share}/arvix/backups"
mkdir -p "$DIR"
OUT="$DIR/arvix-$(date +%F).db"
ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" \
  'f=$(mktemp); sqlite3 ~/.local/share/arvix/arvix.db ".backup $f" && cat "$f"; rm -f "$f"' > "$OUT.part"
sqlite3 "$OUT.part" "pragma integrity_check;" | grep -qx ok
mv "$OUT.part" "$OUT"
ls -1t "$DIR"/arvix-*.db | tail -n +15 | xargs -r rm -f
echo "бэкап: $OUT ($(sqlite3 "$OUT" 'select count(*) from events') событий)"
