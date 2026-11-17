#!/usr/bin/env bash
# Хранилище Obsidian ноутбук ⇄ сервер через Syncthing вместо rsync-таймера (07-OPERATIONS §4, D29).
#
#   deploy/syncthing-setup.sh arvix@HOST        # запускать на ноутбуке; повторный запуск безопасен
#
# Что делает:
#   1. на обеих сторонах включает syncthing как службу пользователя (если он ещё не запущен);
#   2. GUI Syncthing — только 127.0.0.1; на сервере выключает глобальный анонс и ретрансляторы:
#      ноутбук сам приходит на tcp://<сервер>:22000;
#   3. обменивает id устройств и делает общую папку = vault из ~/.config/arvix/config.toml на каждой стороне
#      (если на ноутбуке папка Syncthing на это хранилище уже есть — берёт её id), игнор
#      /.obsidian/workspace*, /.trash, Cache; удалённое с другой стороны 30 дней лежит в .stversions;
#   4. пишет [sync] vault = "syncthing" в конфиг Арвикса на обеих сторонах и выключает
#      arvix-vault-sync.timer (disable --now; юнит остаётся — откат: 07-OPERATIONS §4).
# Конфликты Syncthing не сливает: вторая версия остаётся файлом *.sync-conflict-*, их показывает `arvix doctor`.
# Порт 443 и чужие службы не трогаются. На сервере нужен открытый 22000/tcp.
set -euo pipefail
HOST="${1:?использование: syncthing-setup.sh user@host}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER="$SRC/arvix/syncthing.py"
REMOTE_APP='$HOME/.local/share/arvix/app'
TIMER=arvix-vault-sync.timer
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST")

step() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }
die() { echo "✗ $*" >&2; exit 1; }
remote_py() { "${SSH[@]}" python3 - "$@" < "$HELPER"; }   # тот же модуль, без установки на сервер
json_get() { python3 -c 'import json,sys; v=json.loads(sys.argv[1]).get(sys.argv[2]); print("" if v is None else v)' "$1" "$2"; }

step "Проверка"
command -v syncthing >/dev/null || die "на ноутбуке нет syncthing: sudo pacman -S syncthing"
"${SSH[@]}" true || die "ssh $HOST не проходит"
"${SSH[@]}" 'command -v syncthing >/dev/null' || die "на сервере нет syncthing — deploy/server-setup.sh (под root)"
"${SSH[@]}" "test -f $REMOTE_APP/arvix/config.py && test -f ~/.config/arvix/config.toml" \
  || die "на сервере нет Арвикса или конфига — deploy/sync-server.sh $HOST --init"
echo "ноутбук: $(syncthing --version | cut -d' ' -f1-2) · сервер: $("${SSH[@]}" 'syncthing --version' | cut -d' ' -f1-2)"

# rsync не должен ходить, пока Syncthing делает первый обмен; если настройка сорвётся — включаем обратно.
TIMER_WAS_ACTIVE=0
if systemctl --user is-active --quiet "$TIMER" 2>/dev/null; then
  TIMER_WAS_ACTIVE=1
  systemctl --user stop "$TIMER"
fi
DONE=0
restore() { if [[ $DONE == 0 && $TIMER_WAS_ACTIVE == 1 ]]; then systemctl --user start "$TIMER" || true; echo "rsync-таймер включён обратно"; fi; }
trap restore EXIT

step "Syncthing как служба пользователя"
if python3 "$HELPER" alive 2>/dev/null; then
  echo "ноутбук: уже запущен"
else
  systemctl --user enable --now syncthing.service
  echo "ноутбук: syncthing.service включён"
fi
if remote_py alive 2>/dev/null; then
  echo "сервер: уже запущен"
else
  "${SSH[@]}" 'systemctl --user enable --now syncthing.service'
  echo "сервер: syncthing.service включён"
fi

step "Устройства и папка"
LOCAL="$(python3 "$HELPER" prepare)" || die "Syncthing на ноутбуке не отвечает: journalctl --user -u syncthing -n 30"
REMOTE="$(remote_py prepare)" || die "Syncthing на сервере не отвечает: ssh $HOST journalctl --user -u syncthing -n 30"
LOCAL_ID="$(json_get "$LOCAL" id)";   REMOTE_ID="$(json_get "$REMOTE" id)"
LOCAL_FOLDER="$(json_get "$LOCAL" folder)"; REMOTE_FOLDER="$(json_get "$REMOTE" folder)"
for side in "$LOCAL" "$REMOTE"; do
  python3 -c 'import json,sys; [print("  " + c) for c in json.loads(sys.argv[1])["changes"]]' "$side"
done
if [[ -n "$LOCAL_FOLDER" && -n "$REMOTE_FOLDER" && "$LOCAL_FOLDER" != "$REMOTE_FOLDER" ]]; then
  die "на хранилище смотрят разные папки: ноутбук $LOCAL_FOLDER, сервер $REMOTE_FOLDER — убери лишнюю в GUI одной из сторон"
fi
FOLDER="${LOCAL_FOLDER:-${REMOTE_FOLDER:-arvix-vault}}"
echo "ноутбук $(json_get "$LOCAL" vault) · сервер $(json_get "$REMOTE" vault) · папка $FOLDER"

ADDR="$(ssh -G "$HOST" | awk '/^hostname /{print $2; exit}')"
[[ "$ADDR" == *:* ]] && ADDR="[$ADDR]"
echo "ноутбук:"; python3 "$HELPER" link --folder "$FOLDER" --peer "$REMOTE_ID" --name arvix-server --address "tcp://$ADDR:22000" | sed 's/^/  /'
echo "сервер:";  remote_py link --folder "$FOLDER" --peer "$LOCAL_ID" --name "$(uname -n)" --private | sed 's/^/  /'

step "Арвикс: [sync] vault = \"syncthing\", rsync-таймер выключен"
MARK='import sys; sys.path.insert(0, sys.argv[1]); from arvix.config import write_user_config; write_user_config({"sync": {"vault": "syncthing", "folder": sys.argv[2]}})'
python3 -c "$MARK" "$SRC" "$FOLDER"
"${SSH[@]}" "python3 -c '$MARK' $REMOTE_APP '$FOLDER'"
systemctl --user disable --now "$TIMER" 2>/dev/null || true
"${SSH[@]}" "systemctl --user disable --now $TIMER 2>/dev/null || true"
DONE=1
echo "готово на обеих сторонах"

step "Связь (до 60 с)"
if ! python3 "$HELPER" wait-peer --folder "$FOLDER" --timeout 60; then
  cat <<EOF
Сервер пока не на связи. Проверь, что на нём открыт 22000/tcp (под root: ufw allow 22000/tcp,
или в панели провайдера), и посмотри: arvix doctor.
EOF
fi

cat <<EOF

Дальше:
  arvix doctor                        Syncthing, папка, связь, файлы *.sync-conflict-*
  ssh -L 8385:127.0.0.1:8384 $HOST    GUI сервера на http://127.0.0.1:8385 (наружу он закрыт)
Откат на rsync: 07-OPERATIONS §4.
EOF
