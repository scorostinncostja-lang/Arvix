#!/usr/bin/env bash
# Установка Arvix Lite: копия плагина в стабильный путь, CLI `arvix`, плагин Claude Code,
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
PYTHON="$(command -v python3)"

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

step "CLI: $BIN/arvix"
mkdir -p "$BIN"
cat > "$BIN/arvix" <<EOF
#!/usr/bin/env bash
exec "$PYTHON" "$APP/scripts/arvix_cli.py" "\$@"
EOF
chmod +x "$BIN/arvix"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "⚠ $BIN не в PATH — добавь в ~/.bashrc / config.fish: export PATH=\"$BIN:\$PATH\"";; esac

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
else
  echo "claude не найден. Потом: claude plugin marketplace add $APP && claude plugin install arvix@arvix"
fi

step "systemd: arvix-telegram.service и arvix-backup.timer (не запускаю до arvix setup)"
mkdir -p "$UNIT_DIR"
CLAUDE_DIR="$(dirname "$(command -v claude 2>/dev/null || echo /usr/bin/claude)")"
sed -e "s|@APP@|$APP|g" -e "s|@PYTHON@|$PYTHON|g" -e "s|@PATH@|$BIN:$CLAUDE_DIR:/usr/local/bin:/usr/bin:/bin|g" \
  "$SRC/deploy/arvix-telegram.service" > "$UNIT_DIR/arvix-telegram.service"
sed -e "s|@APP@|$APP|g" "$SRC/deploy/arvix-backup.service" > "$UNIT_DIR/arvix-backup.service"
cp "$SRC/deploy/arvix-backup.timer" "$UNIT_DIR/arvix-backup.timer"
systemctl --user daemon-reload 2>/dev/null || true
if systemctl --user is-active --quiet arvix-telegram 2>/dev/null; then
  systemctl --user restart arvix-telegram && echo "бот перезапущен на новой версии"
fi

if [[ "${1:-}" == "--desktop" ]]; then
  step "Claude Desktop: MCP-сервер arvix"
  "$PYTHON" "$APP/scripts/arvix_cli.py" desktop-mcp
fi

if [[ -f "${XDG_CONFIG_HOME:-$HOME/.config}/arvix/config.toml" ]]; then
  step "Дом Арвикса"
  "$PYTHON" "$APP/scripts/arvix_cli.py" init-home || true
fi

step "Готово"
cat <<'EOF'
Дальше:
  1. arvix setup                                   хранилище, часовой пояс, Telegram-бот
     (без вопросов: arvix setup --vault "…" --tz Europe/Moscow --no-telegram --yes)
  2. systemctl --user enable --now arvix-telegram  запустить бота
  3. cd ~/Arvix && claude                          Арвикс в Claude Code: сам начнёт знакомство
Проверка: arvix doctor · логи бота: journalctl --user -u arvix-telegram -f
Сервер: deploy/server-setup.sh (на VPS под root), затем deploy/sync-server.sh user@host --init
EOF
