#!/usr/bin/env bash
# Разовая подготовка VPS под Арвикса. Запускается под root на сервере:
#
#   ssh root@HOST 'PUBKEY="'"$(cat ~/.ssh/id_ed25519.pub)"'" bash -s' < arvix-claude/deploy/server-setup.sh
#
# Что делает: пользователь arvix с linger (его службы живут без входа), зависимости
# (python3, rsync, sqlite3, syncthing), ключ ноутбука в authorized_keys, Claude CLI под arvix.
# Дальше с ноутбука: bash arvix-claude/deploy/sync-server.sh arvix@HOST --init
set -euo pipefail
USER_NAME="${ARVIX_USER:-arvix}"

if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3 rsync sqlite3 syncthing curl ca-certificates
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y -q python3 rsync sqlite syncthing curl
elif command -v pacman >/dev/null 2>&1; then
  pacman -Sy --noconfirm --needed python rsync sqlite syncthing curl
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "Нужен Python 3.11+ (есть $(python3 --version))"; exit 1; }

id "$USER_NAME" >/dev/null 2>&1 || useradd -m -s /bin/bash "$USER_NAME"
loginctl enable-linger "$USER_NAME"
HOME_DIR="$(getent passwd "$USER_NAME" | cut -d: -f6)"
install -d -m 700 -o "$USER_NAME" -g "$USER_NAME" "$HOME_DIR/.ssh"
if [[ -n "${PUBKEY:-}" ]]; then
  touch "$HOME_DIR/.ssh/authorized_keys"
  grep -qxF "$PUBKEY" "$HOME_DIR/.ssh/authorized_keys" || echo "$PUBKEY" >> "$HOME_DIR/.ssh/authorized_keys"
  chmod 600 "$HOME_DIR/.ssh/authorized_keys"
  chown "$USER_NAME:$USER_NAME" "$HOME_DIR/.ssh/authorized_keys"
else
  echo "PUBKEY не задан — добавь ключ ноутбука в $HOME_DIR/.ssh/authorized_keys сам."
fi
install -d -o "$USER_NAME" -g "$USER_NAME" "$HOME_DIR/src" "$HOME_DIR/vault" "$HOME_DIR/backups"

# Claude CLI под пользователем arvix (голова бота — claude -p по подписке).
if ! sudo -u "$USER_NAME" -H bash -lc 'command -v claude || test -x ~/.local/bin/claude' >/dev/null 2>&1; then
  sudo -u "$USER_NAME" -H bash -lc 'curl -fsSL https://claude.ai/install.sh | bash'
fi

cat <<EOF

Готово. Дальше с ноутбука:
  bash arvix-claude/deploy/sync-server.sh $USER_NAME@$(hostname -I 2>/dev/null | awk '{print $1}') --init
Потом один раз на сервере под $USER_NAME — токен подписки для головы:
  ssh $USER_NAME@HOST
  claude setup-token      # вставить вывод в ~/.config/arvix/claude.env как CLAUDE_CODE_OAUTH_TOKEN=…  (chmod 600)
  systemctl --user enable --now arvix-telegram syncthing
EOF
