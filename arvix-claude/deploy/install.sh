#!/usr/bin/env bash
# Установка Arvix: копия плагина в стабильный путь, CLI `arvix`, плагин Claude Code,
# systemd-юнит бота. Повторный запуск = обновление. Данные (~/.local/share/arvix/arvix.db)
# и конфиг (~/.config/arvix/config.toml) не трогаются.
#
#   bash deploy/install.sh            # всё, кроме Claude Desktop
#   bash deploy/install.sh --desktop  # плюс MCP-сервер в чат Claude Desktop
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/arvix"
APP="$DATA/app"
BIN="$HOME/.local/bin"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/arvix/config.toml"
PYTHON="$(command -v python3)"
CONFIGURED=0; [[ -f "$CONF" ]] && CONFIGURED=1  # повторная установка = обновление: инструкции первого раза не нужны

step() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }

"$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "Нужен Python 3.11+"; exit 1; }

# Путь без пробелов и кириллицы: плагин, systemd и Claude Desktop ссылаются на него,
# и он не исчезнет вместе с git-worktree.
step "Копирую плагин в $APP"
mkdir -p "$APP"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete --exclude '__pycache__' --exclude '*.pyc' --exclude 'tests/' "$SRC/" "$APP/"
else
  rm -rf "$APP" && mkdir -p "$APP" && cp -r "$SRC/." "$APP/" && rm -rf "$APP/tests"
fi

# Ноутбук в удалённом режиме ([remote] host) команду `arvix` не получает: там работают приложение
# (Chromium) и Claude Code, а терминальный интерфейс владелец убрал (D42). Сервер и машина без
# [remote] — получают: на них `arvix setup/doctor` и деплой.
REMOTE_HOST=""
[[ -f "$CONF" ]] && REMOTE_HOST="$(sed -n '/^\[remote\]/,/^\[/{s/^host *= *"\(.*\)"/\1/p}' "$CONF")"
if [[ -n "$REMOTE_HOST" ]]; then
  step "CLI: не ставлю — эта машина ходит на сервер $REMOTE_HOST, интерфейс здесь — приложение"
  [[ -f "$BIN/arvix" ]] && grep -q "arvix_cli.py" "$BIN/arvix" && rm -f "$BIN/arvix" && echo "удалён $BIN/arvix"
  echo "Если понадобится: $PYTHON $APP/scripts/arvix_cli.py <команда>"
else
  step "CLI: $BIN/arvix"
  mkdir -p "$BIN"
  cat > "$BIN/arvix" <<EOF
#!/usr/bin/env bash
exec "$PYTHON" "$APP/scripts/arvix_cli.py" "\$@"
EOF
  chmod +x "$BIN/arvix"
  case ":$PATH:" in *":$BIN:"*) ;; *) echo "⚠ $BIN не в PATH — добавь в ~/.bashrc / config.fish: export PATH=\"$BIN:\$PATH\"";; esac
fi

step "Плагин Claude Code (маркетплейс arvix, scope user)"
if command -v claude >/dev/null 2>&1; then
  claude plugin validate "$APP" || echo "⚠ validate нашёл замечания (см. выше)"
  if claude plugin marketplace list 2>/dev/null | grep -q "arvix"; then
    claude plugin marketplace update arvix >/dev/null 2>&1 || true
  else
    claude plugin marketplace add "$APP" --scope user
  fi
  if claude plugin list 2>/dev/null | grep -q "arvix@arvix"; then
    claude plugin update arvix@arvix >/dev/null 2>&1 || true
    echo "обновлён"
  else
    claude plugin install arvix@arvix --scope user
  fi
elif (( CONFIGURED )); then
  echo "Claude Code не в PATH — плагин пропущен (боту и голове он не нужен)"
else
  echo "claude не найден. Потом: claude plugin marketplace add $APP && claude plugin install arvix@arvix"
fi

if (( CONFIGURED )); then step "systemd: юниты обновлены"; else step "systemd: arvix-telegram.service и arvix-backup.timer (не запускаю до arvix setup)"; fi
mkdir -p "$UNIT_DIR"
CLAUDE_DIR="$(dirname "$(command -v claude 2>/dev/null || echo /usr/bin/claude)")"
sed -e "s|@APP@|$APP|g" -e "s|@PYTHON@|$PYTHON|g" -e "s|@PATH@|$BIN:$CLAUDE_DIR:/usr/local/bin:/usr/bin:/bin|g" \
  "$SRC/deploy/arvix-telegram.service" > "$UNIT_DIR/arvix-telegram.service"
sed -e "s|@APP@|$APP|g" "$SRC/deploy/arvix-backup.service" > "$UNIT_DIR/arvix-backup.service"
cp "$SRC/deploy/arvix-backup.timer" "$UNIT_DIR/arvix-backup.timer"
sed -e "s|@APP@|$APP|g" "$SRC/deploy/arvix-vault-sync.service" > "$UNIT_DIR/arvix-vault-sync.service"
cp "$SRC/deploy/arvix-vault-sync.timer" "$UNIT_DIR/arvix-vault-sync.timer"
systemctl --user daemon-reload 2>/dev/null || true
for timer in arvix-backup.timer arvix-vault-sync.timer; do  # новое расписание вступает в силу только после перезапуска таймера
  systemctl --user is-active --quiet "$timer" 2>/dev/null && systemctl --user restart "$timer" 2>/dev/null || true
done
BOT=stopped
if systemctl --user is-active --quiet arvix-telegram 2>/dev/null; then
  systemctl --user restart arvix-telegram && BOT=restarted
fi

if [[ "${1:-}" == "--desktop" ]]; then
  step "Claude Desktop: MCP-сервер arvix"
  "$PYTHON" "$APP/scripts/arvix_cli.py" desktop-mcp
fi

if (( CONFIGURED )); then
  "$PYTHON" "$APP/scripts/arvix_cli.py" init-home >/dev/null 2>&1 || true
  VERSION="$("$PYTHON" -c "import sys; sys.path.insert(0, '$APP'); import arvix; print(arvix.__version__)")"
  REMOTE="$(sed -n '/^\[remote\]/,/^\[/{s/^host *= *"\(.*\)"/\1/p}' "$CONF")"
  if [[ "$BOT" == restarted ]]; then
    step "Готово: Арвикс $VERSION, бот перезапущен на новой версии"
  elif [[ -n "$REMOTE" ]]; then
    step "Готово: Арвикс $VERSION на этой машине. Бот и журнал — на сервере; обнови его: deploy/sync-server.sh $REMOTE"
  else
    step "Готово: Арвикс $VERSION. Бот здесь не запущен — systemctl --user enable --now arvix-telegram"
  fi
  exit 0
fi

step "Готово — первая установка"
cat <<'EOF'
Дальше:
  1. arvix setup                                   хранилище, часовой пояс, Telegram-бот
     (без вопросов: arvix setup --vault "…" --tz Europe/Moscow --no-telegram --yes)
  2. systemctl --user enable --now arvix-telegram  запустить бота
  3. cd ~/Arvix && claude                          Арвикс в Claude Code: сам начнёт знакомство
Проверка: arvix doctor · логи бота: journalctl --user -u arvix-telegram -f
Сервер: deploy/server-setup.sh (на VPS под root), затем deploy/sync-server.sh user@host --init
EOF
