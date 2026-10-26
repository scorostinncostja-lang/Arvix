#!/bin/bash
# Git commit и push для интеграции AI-слоя

cd "/home/dastan/Рабочий стол/Projects/Arvix" || exit 1

echo "📊 Git status..."
git status --short

echo ""
echo "➕ Adding all changes..."
git add .

echo ""
echo "💾 Committing..."
git commit -m "feat(ai): integrate AI layer L1 (steps 0.8-0.9)

- Added core/ai/ with router, context builder, privacy filter
- Integrated debrief and freeform handlers (freeform LAST)
- Scheduler jobs for morning brief (07:30) and debrief (22:30)
- Deleted temp files (check_syntax.py, AI_LAYER_*.md)
- Added test scripts and documentation

Invariants enforced:
- RED mode + mentor_disabled exclude harsh tone blocks
- OpenAI-compatible universal client (AsyncOpenAI)
- Event sourcing through emit()
- L0/L1/L2 separation maintained"

echo ""
echo "🚀 Pushing to remote..."
git push

echo ""
echo "✅ Done!"
