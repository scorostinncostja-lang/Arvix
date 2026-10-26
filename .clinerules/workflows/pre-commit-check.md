# Workflow: Проверка перед коммитом (/pre-commit-check)

1. Выполни `git status` и `git diff --stat`.
2. Убедись, что в индекс не попали `.env`, секреты или временные файлы.
3. Запусти `ruff check .` и `pytest`.
4. Предложи осмысленное сообщение коммита в формате Conventional Commits (`feat(scope): ...` или `fix(scope): ...`).
