#!/usr/bin/env bash
# Залить Арвикса на сервер и установить/обновить его там.
#
#   deploy/sync-server.sh arvix@HOST            # обновление: код → install.sh → перезапуск бота
#   deploy/sync-server.sh arvix@HOST --init     # первый раз: плюс конфиг сервера из ноутбучного
#                                               #   (vault → ~/vault, home → ~/Arvix, тот же токен бота)
#
# Если на ноутбуке есть копия конфига прошлого сервера (её снимает arvix-backup.sh:
# ~/.local/share/arvix/backups/server-config.toml), --init берёт её за основу — ключи голоса,
# [obsidian] и прочие серверные настройки переезжают; поверх — ноутбучный конфиг. Другой файл: SERVER_CFG=путь.
# После --init на ноутбуке: arvix remote set arvix@HOST  (журнал и бот живут на сервере),
# и выключить локального бота: systemctl --user disable --now arvix-telegram.
set -euo pipefail
HOST="${1:?использование: sync-server.sh user@host [--init]}"
INIT="${2:-}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG="${XDG_CONFIG_HOME:-$HOME/.config}/arvix/config.toml"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST")

step() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }

step "Код → $HOST:src/arvix-claude/"
rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' --exclude 'tests/' "$SRC/" "$HOST:src/arvix-claude/"

if [[ "$INIT" == "--init" ]]; then
  step "Конфиг сервера из $CFG"
  [[ -f "$CFG" ]] || { echo "Сначала настрой ноутбук: arvix setup"; exit 1; }
  REMOTE_HOME="$("${SSH[@]}" 'echo $HOME')"
  TMP="$(mktemp)"
  SAVED="${SERVER_CFG:-${XDG_DATA_HOME:-$HOME/.local/share}/arvix/backups/server-config.toml}"
  [[ -f "$SAVED" ]] && echo "основа — сохранённый конфиг прошлого сервера: $SAVED"
  python3 - "$CFG" "$REMOTE_HOME" "$SRC" "$SAVED" "${HOST#*@}" > "$TMP" <<'EOF'
import os, sys, tomllib
cfg_path, remote_home, src, saved, host = sys.argv[1:6]
sys.path.insert(0, src)
from arvix.config import _merge, _toml_lines
laptop = tomllib.load(open(cfg_path, "rb"))
cfg = _merge(tomllib.load(open(saved, "rb")), laptop) if os.path.isfile(saved) else laptop
cfg.pop("remote", None)                      # сервер — это и есть «локально»
url = (cfg.get("web") or {}).get("public_url", "")
if url and host not in url and host.replace(".", "-") not in url:
    cfg["web"].pop("public_url")             # адрес прошлого сервера: новый пропишет deploy/web-setup.sh
cfg["vault"] = f"{remote_home}/vault"        # Syncthing: ноутбук ⇄ ~/vault
cfg["home"] = f"{remote_home}/Arvix"
cfg.setdefault("brain", {})["claude_bin"] = f"{remote_home}/.local/bin/claude"
print("# Конфиг Arvix на сервере. Создан deploy/sync-server.sh --init из конфига ноутбука.")
print("\n".join(_toml_lines(cfg)))
EOF
  "${SSH[@]}" 'mkdir -p ~/.config/arvix && umask 077 && cat > ~/.config/arvix/config.toml' < "$TMP"
  rm -f "$TMP"
  echo "записан ~/.config/arvix/config.toml на сервере (права 600)"
fi

step "Установка на сервере"
"${SSH[@]}" 'bash ~/src/arvix-claude/deploy/install.sh && ~/.local/bin/arvix init-home >/dev/null && ~/.local/bin/arvix doctor' || true

[[ "$INIT" == "--init" ]] || exit 0  # обновление: дальше — только шаги первой настройки

cat <<EOF

Дальше:
  arvix remote set $HOST                              # ноутбук ходит за журналом на сервер
  systemctl --user disable --now arvix-telegram       # бот теперь там, здесь — выключить
  systemctl --user enable --now arvix-backup.timer    # каждый час: журнал и конфиг сервера на ноутбук
На сервере (один раз): claude setup-token → ~/.config/arvix/claude.env, systemctl --user enable --now arvix-telegram
EOF
