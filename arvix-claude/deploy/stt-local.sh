#!/usr/bin/env bash
# Локальное распознавание голосовых (whisper.cpp): голос никуда не уходит, ключ API не нужен.
# Запускать на машине, где работает бот (сервер или ноутбук):
#
#   bash ~/.local/share/arvix/app/deploy/stt-local.sh [base|small]
#   arvix setup --stt command        # команда по умолчанию подходит к этой установке
#   systemctl --user restart arvix-telegram
#
# Нужны git, cmake, g++, ffmpeg (Ubuntu: sudo apt install -y git cmake g++ ffmpeg).
# base — быстрее (на одном ядре ~10–20 с на 30 с речи), small — точнее по-русски и медленнее в 2–3 раза.
# Если важнее скорость и качество, чем приватность, — проще Groq: arvix setup --stt groq.
set -euo pipefail
MODEL="${1:-base}"
DIR="${XDG_DATA_HOME:-$HOME/.local/share}/arvix/whisper"

for bin in git cmake g++ ffmpeg; do
  command -v "$bin" >/dev/null 2>&1 || { echo "нет $bin — поставь: sudo apt install -y git cmake g++ ffmpeg"; exit 1; }
done
mkdir -p "$DIR"
[[ -d "$DIR/src/.git" ]] || git clone --depth 1 https://github.com/ggml-org/whisper.cpp "$DIR/src"
cmake -S "$DIR/src" -B "$DIR/build" -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build "$DIR/build" -j"$(nproc)" --config Release --target whisper-cli
cp "$DIR/build/bin/whisper-cli" "$DIR/whisper-cli"
[[ -f "$DIR/ggml-$MODEL.bin" ]] || bash "$DIR/src/models/download-ggml-model.sh" "$MODEL" "$DIR"
ln -sf "$DIR/ggml-$MODEL.bin" "$DIR/model.bin"

echo "Проверка на тишине:"
ffmpeg -loglevel error -y -f lavfi -i anullsrc=r=16000:cl=mono -t 1 "$DIR/test.wav"
"$DIR/whisper-cli" -m "$DIR/model.bin" -l ru -nt -np -f "$DIR/test.wav" >/dev/null && echo "whisper-cli работает."
rm -f "$DIR/test.wav"
echo "Дальше: arvix setup --stt command, затем systemctl --user restart arvix-telegram"
