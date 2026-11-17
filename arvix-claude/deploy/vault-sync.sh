#!/usr/bin/env bash
# Двусторонняя синхронизация хранилища Obsidian с сервером через rsync (новее — побеждает,
# ничего не удаляется). Таймер arvix-vault-sync.timer — раз в 10 минут. Замена — deploy/syncthing-setup.sh:
# после неё ([sync] vault = "syncthing") скрипт ничего не делает.
#
#   deploy/vault-sync.sh                 # хост из [remote] host, хранилище из vault в config.toml
#   deploy/vault-sync.sh arvix@host      # хост явно
set -euo pipefail
CFG="${XDG_CONFIG_HOME:-$HOME/.config}/arvix/config.toml"
read -r MODE HOST VAULT < <(python3 - "$CFG" "${1:-}" <<'EOF'
import sys, tomllib
cfg = tomllib.load(open(sys.argv[1], "rb"))
host = sys.argv[2] or (cfg.get("remote") or {}).get("host", "")
print((cfg.get("sync") or {}).get("vault", "rsync"), host, cfg.get("vault", ""))
EOF
)
# После deploy/syncthing-setup.sh хранилище синхронизирует Syncthing: rsync поверх него затирал бы его версии.
if [[ "$MODE" == "syncthing" ]]; then
  echo "хранилище синхронизирует Syncthing ([sync] vault = \"syncthing\") — rsync не запускаю"
  exit 0
fi
[[ -n "$HOST" && -n "$VAULT" ]] || { echo "нужны [remote] host и vault в $CFG"; exit 2; }
OPTS=(-au --exclude '.trash' --exclude 'Cache' --exclude '.obsidian/workspace*' --timeout=60 -e 'ssh -o BatchMode=yes -o ConnectTimeout=15')
rsync "${OPTS[@]}" "$HOST:vault/" "$VAULT/"
rsync "${OPTS[@]}" "$VAULT/" "$HOST:vault/"
echo "vault ⇄ $HOST: $(date +%H:%M)"
