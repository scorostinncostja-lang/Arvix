#!/bin/bash
# Скрипт для проверки и тестирования после интеграции AI-слоя
# Запускать из корня проекта: bash scripts/test_and_lint.sh

set -e

echo "🔧 Проверка и установка зависимостей..."
pip install -q openai pyyaml || true

echo ""
echo "✅ Запуск тестов AI слоя..."
python -m pytest tests/test_ai_layer.py -v

echo ""
echo "✅ Запуск всех тестов..."
python -m pytest tests/ -v

echo ""
echo "🔍 Проверка линтером..."
python -m ruff check . --fix

echo ""
echo "✅ ВСЕ ПРОВЕРКИ ЗАВЕРШЕНЫ!"
