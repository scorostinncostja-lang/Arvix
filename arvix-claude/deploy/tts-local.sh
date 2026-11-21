#!/usr/bin/env bash
# Голос Arvix (D34): Piper — локальный синтез речи с русским голосом. Бесплатно, без ключа,
# текст никуда не уходит. Запускать на машине, где работает бот (сервер или ноутбук):
#
#   bash ~/.local/share/arvix/app/deploy/tts-local.sh [irina|dmitri|denis|ruslan]
#
# Бот, если он запущен на этой машине, скрипт перезапускает сам. Повторный запуск безопасен:
# скачанное не качается заново, секция [tts] переписывается той же.
#
# Скрипт кладёт Piper и голос в ~/.local/share/arvix/piper и пишет в конфиг:
#   [tts] engine = "command", command = "<piper> --model <голос>.onnx --output_file {out}"
# После этого ответ на голосовое приходит и голосовым, а режим разговора в приложении говорит
# голосом сервера там, где у телефона своего русского голоса нет (WebView Telegram).
# Нужны curl, tar, ffmpeg. Выключить: [tts] engine = "off" или voice_replies = false.
set -euo pipefail
VOICE="${1:-irina}"
DIR="${XDG_DATA_HOME:-$HOME/.local/share}/arvix/piper"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/arvix/config.toml"
PIPER_URL="https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_$(uname -m).tar.gz"
VOICES="https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU"

for bin in curl tar ffmpeg; do
  command -v "$bin" >/dev/null 2>&1 || { echo "нет $bin — поставь: sudo apt install -y curl tar ffmpeg"; exit 1; }
done
mkdir -p "$DIR"
if [[ ! -x "$DIR/piper/piper" ]]; then
  echo "Скачиваю Piper ($(uname -m))…"
  curl -fsSL "$PIPER_URL" | tar -xz -C "$DIR"
fi
MODEL="$DIR/ru_RU-$VOICE-medium.onnx"
if [[ ! -f "$MODEL" ]]; then
  echo "Скачиваю голос $VOICE…"
  curl -fsSL -o "$MODEL" "$VOICES/$VOICE/medium/ru_RU-$VOICE-medium.onnx"
  curl -fsSL -o "$MODEL.json" "$VOICES/$VOICE/medium/ru_RU-$VOICE-medium.onnx.json"
fi

echo "Проверка:"
echo "Привет. Я Arvix, и теперь я умею говорить." | "$DIR/piper/piper" --model "$MODEL" --output_file "$DIR/test.wav" >/dev/null 2>&1
[[ -s "$DIR/test.wav" ]] && echo "Piper работает: $DIR/test.wav" || { echo "Piper не создал звук"; exit 1; }

COMMAND="$DIR/piper/piper --model $MODEL --length_scale 0.85 --output_file {out}"  # 0.85 — на 15 % быстрее: по умолчанию Piper тянет слова
python3 - "$CONF" "$COMMAND" <<'PY'
import re, sys, pathlib
path, command = pathlib.Path(sys.argv[1]), sys.argv[2]
text = path.read_text(encoding="utf-8") if path.exists() else ""
block = f'[tts]\nengine = "command"\ncommand = "{command}"\nvoice_replies = true\n'
text = re.sub(r"(?ms)^\[tts\]\n.*?(?=^\[|\Z)", "", text).rstrip() + "\n\n" + block
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(text, encoding="utf-8")
path.chmod(0o600)
print(f"Записал [tts] в {path}")
PY
if systemctl --user is-active --quiet arvix-telegram 2>/dev/null; then
  systemctl --user restart arvix-telegram
  echo "Готово: голос включён, бот перезапущен. Проверь — отправь Arvix голосовое."
else
  echo "Готово: голос настроен. Бот на этой машине не запущен — включится при его старте."
fi
