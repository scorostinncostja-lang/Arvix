#!/usr/bin/env bash
# Токен подписки Claude для головы бота на сервере. Запускается под пользователем arvix
# в интерактивном терминале (нужен браузер на ноутбуке для входа в аккаунт):
#
#   ssh -t arvix@HOST 'bash ~/.local/share/arvix/app/deploy/server-claude-token.sh'   # в кавычках: ~ — каталог сервера
#
# `claude setup-token` покажет ссылку — открой её, войди, вставь код обратно в терминал.
# Полученный токен (sk-ant-oat…) скрипт кладёт в ~/.config/arvix/claude.env (права 600),
# откуда его читает служба arvix-telegram. Токен claude показывает на экране один раз — не делись этим экраном.
set -euo pipefail
ENV_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/arvix/claude.env"
CLAUDE="$(command -v claude || echo "$HOME/.local/bin/claude")"
[[ -x "$CLAUDE" ]] || { echo "claude не найден: curl -fsSL https://claude.ai/install.sh | bash"; exit 1; }

OUT="$(mktemp)"
trap 'rm -f "$OUT"' EXIT
# Диалог входа должен идти прямо в терминал: через трубу (`| tee`) интерфейс claude не может
# стирать строки и рисует окно заново на каждое нажатие. `script` даёт ему настоящий терминал
# и пишет сеанс в файл — оттуда берём токен. Сам токен виден на экране один раз, как у claude.
if command -v script >/dev/null 2>&1; then
  script -q -e -c "$(printf '%q' "$CLAUDE") setup-token" "$OUT"
else
  "$CLAUDE" setup-token 2>&1 | tee "$OUT"
fi
TOKEN="$(sed 's/\x1b\[[0-9;?]*[A-Za-z]//g' "$OUT" | tr -d '\r' | grep -oE 'sk-ant-oat[0-9]*-[A-Za-z0-9_-]+' | tail -1 || true)"
[[ -n "$TOKEN" ]] || { echo "Токен в выводе не найден — повтори: claude setup-token"; exit 1; }

mkdir -p "$(dirname "$ENV_FILE")"
umask 077
printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$TOKEN" > "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "Токен записан в $ENV_FILE (права 600)."
if systemctl --user is-enabled --quiet arvix-telegram 2>/dev/null; then
  systemctl --user restart arvix-telegram && echo "Бот перезапущен с новым токеном."
else
  echo "Дальше: systemctl --user enable --now arvix-telegram"
fi
