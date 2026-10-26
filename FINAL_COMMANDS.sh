#!/bin/bash
# ФИНАЛЬНЫЕ КОМАНДЫ ДЛЯ ЗАВЕРШЕНИЯ ИНТЕГРАЦИИ AI-СЛОЯ
# Скопируйте и выполните эти команды в терминале вручную

# 1. Перейти в проект
cd "/home/dastan/Рабочий стол/Projects/Arvix"

# 2. Проверить статус
git status

# 3. Добавить все изменения
git add .

# 4. Сделать коммит
git commit -m "feat(ai): integrate AI layer L1 (steps 0.8-0.9)

- Added core/ai/ with router, context builder, privacy filter
- Integrated debrief and freeform handlers (freeform LAST)
- Scheduler jobs for morning brief (07:30) and debrief (22:30)
- Deleted temp files (check_syntax.py, AI_LAYER_*.md)
- Added test and git scripts

Invariants enforced:
- RED mode + mentor_disabled exclude harsh tone blocks
- OpenAI-compatible universal client (AsyncOpenAI)
- Event sourcing through emit()
- L0/L1/L2 separation maintained"

# 5. Отправить в репозиторий
git push

# 6. ОПЦИОНАЛЬНО: Запустить тесты
python -m pytest tests/test_ai_layer.py -v
python -m pytest tests/ -v
python -m ruff check . --fix

echo "✅ Готово!"
