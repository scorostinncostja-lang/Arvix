#!/usr/bin/env bash
# Переезд Arvix на новый сервер, когда старый пропал (отключили, заблокировали IP, кончилась аренда).
# Запускается на НОУТБУКЕ — всё нужное для восстановления лежит здесь:
#   журнал        ~/.local/share/arvix/backups/arvix-ГГГГ-ММ-ДД.db   (arvix-backup.timer, каждый час)
#   конфиг        ~/.local/share/arvix/backups/server-config.toml    (там же; если нет — из ноутбучного)
#   хранилище     vault из ~/.config/arvix/config.toml                (arvix-vault-sync.timer)
#
#   bash deploy/restore-server.sh root@НОВЫЙ_IP                    # всё по шагам
#   bash deploy/restore-server.sh root@НОВЫЙ_IP --dry-run          # только показать, что и откуда поднимется
#   bash deploy/restore-server.sh root@НОВЫЙ_IP --journal FILE.db  # другой снимок журнала
#
# Перед запуском — вход на сервер по ключу ноутбука (один раз, спросит пароль root от хостера):
#   ssh-copy-id root@НОВЫЙ_IP
#
# Повторный запуск безопасен: каждый шаг либо уже сделан, либо делается заново. Журнал на сервере
# заменяется снимком, только если там событий меньше, чем в снимке (свежий сервер); иначе — --force-journal.
set -euo pipefail

ROOT_HOST="${1:-}"
[[ "$ROOT_HOST" == *@* ]] || { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
shift
IP="${ROOT_HOST#*@}"
USER_NAME="${ARVIX_USER:-arvix}"
HOST="$USER_NAME@$IP"
JOURNAL=""; DRY=0; FORCE=0
while (( $# )); do
  case "$1" in
    --journal) JOURNAL="${2:?--journal FILE}"; shift ;;
    --dry-run) DRY=1 ;;
    --force-journal) FORCE=1 ;;
    *) echo "неизвестный ключ: $1"; exit 2 ;;
  esac
  shift
done

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG="${XDG_CONFIG_HOME:-$HOME/.config}/arvix/config.toml"
BACKUPS="${XDG_DATA_HOME:-$HOME/.local/share}/arvix/backups"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new)
step() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }
die() { printf '\n\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# --- 0. Что есть на ноутбуке -------------------------------------------------------------
step "Что есть на ноутбуке"
[[ -f "$CFG" ]] || die "нет $CFG — без конфига ноутбука (токен бота, хранилище) поднимать нечего"
journal_ok() { [[ -s "$1" ]] && [[ "$(sqlite3 "$1" 'pragma integrity_check;' 2>/dev/null)" == ok ]] \
  && sqlite3 "$1" 'select count(*) from events' >/dev/null 2>&1; }
if [[ -z "$JOURNAL" ]]; then
  for f in $(ls -1t "$BACKUPS"/arvix-*.db 2>/dev/null); do
    journal_ok "$f" && { JOURNAL="$f"; break; }
    echo "пропускаю повреждённый снимок: $f"
  done
fi
[[ -n "$JOURNAL" ]] || die "в $BACKUPS нет целого снимка журнала. Укажи файл: --journal ПУТЬ"
journal_ok "$JOURNAL" || die "снимок повреждён: $JOURNAL"
EVENTS="$(sqlite3 "$JOURNAL" 'select count(*) from events')"
LAST="$(sqlite3 "$JOURNAL" 'select max(at) from events')"
echo "журнал:    $JOURNAL — $EVENTS событий, последнее $LAST"
echo "           всё, что было на старом сервере позже, восстановить неоткуда"
if [[ -f "$BACKUPS/server-config.toml" ]]; then
  echo "конфиг:    $BACKUPS/server-config.toml (с ключами голоса и настройками прошлого сервера)"
else
  echo "конфиг:    из ноутбучного $CFG — ключи голоса (Groq/Gemini) придётся ввести заново"
fi
read -r OLD_REMOTE VAULT < <(python3 - "$CFG" <<'EOF'
import sys, tomllib
c = tomllib.load(open(sys.argv[1], "rb"))
print((c.get("remote") or {}).get("host", "") or "-", c.get("vault", "") or "-")  # путь последним: в нём бывают пробелы
EOF
)
[[ "$VAULT" != - && -d "$VAULT" ]] && echo "хранилище: $VAULT ($(find "$VAULT" -name '*.md' | wc -l) заметок)" \
  || echo "хранилище: не задано или не найдено — сервер поднимется без него"
echo "сервер:    $HOST (было: $OLD_REMOTE)"
PUBKEY_FILE="$(ls ~/.ssh/id_ed25519.pub ~/.ssh/id_rsa.pub 2>/dev/null | head -1 || true)"
[[ -n "$PUBKEY_FILE" ]] || die "нет SSH-ключа ноутбука: ssh-keygen -t ed25519"

if (( DRY )); then
  cat <<EOF

План (--dry-run, ничего не сделано):
  1. root@$IP: пользователь $USER_NAME, python3, sqlite3, ffmpeg, Claude CLI      deploy/server-setup.sh
  2. код и конфиг на сервер, установка                                    deploy/sync-server.sh $HOST --init
  3. журнал $EVENTS событий → ~/.local/share/arvix/arvix.db, проверка arvix rebuild
  4. хранилище ноутбука → ~/vault                                          deploy/vault-sync.sh
     и проекты, которых нет в снимке журнала, — из карточек и роадмапов     arvix restore-projects --apply
  5. вход в Claude для головы бота (ссылка → браузер → код)                 deploy/server-claude-token.sh
  6. бот: systemctl --user enable --now arvix-telegram
  7. приложение по HTTPS: Caddy, адрес https://${IP//./-}.sslip.io:8443     deploy/web-setup.sh
  8. ноутбук: [remote] host = $HOST, таймеры синхронизации и бэкапа
  9. одноразовая ссылка привязки приложения на новом адресе                 arvix app-link
EOF
  exit 0
fi

ssh "${SSH_OPTS[@]}" "$ROOT_HOST" true 2>/dev/null || die "нет входа root@$IP по ключу. Сделай один раз (спросит пароль root):
    ssh-copy-id root@$IP
  Если ssh пишет REMOTE HOST IDENTIFICATION HAS CHANGED: ssh-keygen -R $IP"

# Пока переезжаем, таймеры ноутбука не трогают ни старый, ни новый сервер.
systemctl --user stop arvix-vault-sync.timer arvix-backup.timer 2>/dev/null || true
trap 'systemctl --user start arvix-vault-sync.timer arvix-backup.timer 2>/dev/null || true' EXIT

# --- 1. Сервер с нуля ------------------------------------------------------------------
step "1/8 Подготовка сервера под root"
ssh "${SSH_OPTS[@]}" "$ROOT_HOST" "PUBKEY='$(cat "$PUBKEY_FILE")' ARVIX_USER='$USER_NAME' bash -s" < "$SRC/deploy/server-setup.sh" \
  || die "server-setup.sh упал — вывод выше"
ssh "${SSH_OPTS[@]}" "$HOST" true || die "нет входа $HOST по ключу после server-setup.sh"

# --- 2. Код и конфиг -------------------------------------------------------------------
step "2/8 Код и конфиг"
bash "$SRC/deploy/sync-server.sh" "$HOST" --init || die "sync-server.sh упал — вывод выше"

# --- 3. Журнал -------------------------------------------------------------------------
step "3/8 Журнал"
RUN=(ssh "${SSH_OPTS[@]}" "$HOST")
ON_SERVER="$("${RUN[@]}" 'f=~/.local/share/arvix/arvix.db; [ -f "$f" ] && sqlite3 "$f" "select count(*) from events" 2>/dev/null || echo 0')"
[[ "$ON_SERVER" =~ ^[0-9]+$ ]] || ON_SERVER=0
if (( ON_SERVER >= EVENTS && ! FORCE )); then
  echo "на сервере уже $ON_SERVER событий (в снимке $EVENTS) — журнал не трогаю. Заменить: --force-journal"
else
  "${RUN[@]}" 'systemctl --user stop arvix-telegram 2>/dev/null; d=~/.local/share/arvix; mkdir -p "$d";
    [ -f "$d/arvix.db" ] && mv "$d/arvix.db" "$d/arvix.db.before-restore-$(date +%s)"; rm -f "$d"/arvix.db-wal "$d"/arvix.db-shm; true'
  "${RUN[@]}" 'cat > ~/.local/share/arvix/arvix.db.part && mv ~/.local/share/arvix/arvix.db.part ~/.local/share/arvix/arvix.db' < "$JOURNAL"
  GOT="$("${RUN[@]}" 'sqlite3 ~/.local/share/arvix/arvix.db "select count(*) from events"')"
  [[ "$GOT" == "$EVENTS" ]] || die "на сервере $GOT событий вместо $EVENTS — журнал доехал не целиком"
  echo "журнал на сервере: $GOT событий"
fi
"${RUN[@]}" '~/.local/bin/arvix rebuild' || die "arvix rebuild нашёл расхождения — бота не запускаю"

# --- 4. Хранилище ----------------------------------------------------------------------
step "4/8 Хранилище Obsidian"
if [[ "$VAULT" != - && -d "$VAULT" ]]; then
  bash "$SRC/deploy/vault-sync.sh" "$HOST"
  # Проекты, созданные после снимка журнала, живы в заметках: карточки папок и роадмапы целей (D54).
  # Создаются только те, которых в журнале нет, — повторный запуск ничего не дублирует.
  "${RUN[@]}" '~/.local/bin/arvix restore-projects --apply' || echo "⚠ проекты из хранилища не восстановлены: ssh $HOST '~/.local/bin/arvix restore-projects'"
else
  echo "пропущено: на ноутбуке нет хранилища"
fi

# --- 5. Claude для головы бота ---------------------------------------------------------
step "5/8 Вход в Claude на сервере"
if "${RUN[@]}" 'test -s ~/.config/arvix/claude.env'; then
  echo "токен уже есть (~/.config/arvix/claude.env). Перевойти: ssh -t $HOST 'bash ~/.local/share/arvix/app/deploy/server-claude-token.sh'"
elif [[ -t 0 && -t 1 ]]; then
  echo "Сейчас будет ссылка: открой её в браузере, войди в свой аккаунт Claude, вставь код сюда."
  ssh -t -o ConnectTimeout=15 "$HOST" 'bash ~/.local/share/arvix/app/deploy/server-claude-token.sh' \
    || echo "⚠ вход не завершён — повтори: ssh -t $HOST 'bash ~/.local/share/arvix/app/deploy/server-claude-token.sh'"
else
  echo "нет терминала — войди сам: ssh -t $HOST 'bash ~/.local/share/arvix/app/deploy/server-claude-token.sh'"
fi

# --- 6. Бот ----------------------------------------------------------------------------
step "6/8 Бот"
"${RUN[@]}" 'systemctl --user enable --now arvix-telegram >/dev/null 2>&1; sleep 3; systemctl --user is-active arvix-telegram' \
  || echo "⚠ бот не запустился: ssh $HOST journalctl --user -u arvix-telegram -n 50"

# --- 7. Приложение ---------------------------------------------------------------------
step "7/8 Приложение по HTTPS"
bash "$SRC/deploy/web-setup.sh" "$ROOT_HOST" "$USER_NAME" \
  || echo "⚠ приложение не поднялось — повтори: bash deploy/web-setup.sh $ROOT_HOST"
APP_URL="$("${RUN[@]}" "python3 -c 'import tomllib,os; print((tomllib.load(open(os.path.expanduser(\"~/.config/arvix/config.toml\"),\"rb\")).get(\"web\") or {}).get(\"public_url\",\"\"))'" || true)"

# --- 8. Ноутбук ------------------------------------------------------------------------
step "8/8 Ноутбук → новый сервер"
python3 "$SRC/scripts/arvix_cli.py" remote set "$HOST"
bash "$SRC/deploy/install.sh"
systemctl --user enable --now arvix-vault-sync.timer arvix-backup.timer >/dev/null 2>&1 || true
systemctl --user start arvix-backup.service 2>/dev/null && echo "первый бэкап с нового сервера снят: $BACKUPS" \
  || echo "⚠ бэкап с нового сервера не снялся: journalctl --user -u arvix-backup -n 20"

# Ключ приложения браузер хранит для адреса, а адрес сменился: голый новый адрес откроет пустое
# приложение. Ссылка привязки — последней, чтобы её 15 минут не ушли на остальные шаги.
APP_LINK=""
[[ -n "$APP_URL" ]] && APP_LINK="$("${RUN[@]}" '~/.local/bin/arvix app-link' 2>/dev/null || true)"

cat <<EOF

Готово. Arvix живёт на $HOST.
  Telegram:   тот же бот, та же переписка — напиши ему, он ответит с нового сервера.
              Кнопка «Arvix» у поля ввода уже ведёт на новый адрес, входить не нужно.
  Журнал:     поднят по $LAST. Что было на старом сервере позже — потеряно.
  Приложение: ${APP_URL:-адрес не получен — bash deploy/web-setup.sh $ROOT_HOST}
              Старое приложение смотрит на умерший адрес и будет пустым — удали его (⋮ → «Удалить»).
EOF
if [[ -n "$APP_LINK" ]]; then
  cat <<EOF
              На ноутбуке открой в браузере ЭТУ ссылку (15 минут, один раз), потом ⋮ → «Установить приложение»:
                $APP_LINK
              Голый адрес без ссылки откроет приложение без данных. Новая ссылка: ssh $HOST '~/.local/bin/arvix app-link'
              Телефон: кнопка «Arvix» в Telegram → «Прогресс» → «Установить на телефон».
EOF
fi
if ! grep -q 'api_key' "$BACKUPS/server-config.toml" 2>/dev/null; then
  cat <<EOF
  Голос:      ключи не сохранились — если пользовался, введи заново (ввод скрытый):
                ssh -t $HOST '~/.local/bin/arvix setup --stt groq --yes'
                ssh -t $HOST '~/.local/bin/arvix setup --tts gemini --yes'
EOF
fi
[[ "$OLD_REMOTE" != - && "$OLD_REMOTE" != "$HOST" ]] && cat <<EOF
  Старый сервер $OLD_REMOTE: если он вдруг оживёт — выключи там бота, два бота с одним токеном мешают друг другу:
                ssh $OLD_REMOTE systemctl --user disable --now arvix-telegram
EOF
exit 0
