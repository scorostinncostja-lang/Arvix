# Arvix — Claude Code

Правила общие для Claude Code и Codex и живут в одном файле — [AGENTS.md](AGENTS.md), он подключён ниже.
Карта кода — [ARCHITECTURE.md](ARCHITECTURE.md), планы больших задач — [PLANS.md](PLANS.md).
Здесь — только то, что касается одного Claude Code. Общее правило сюда не копируй: правь `AGENTS.md`.

@AGENTS.md

## Только для Claude Code

- Работаешь в рабочей копии `.claude/worktrees/<имя>/` на ветке `claude/<тема>`. Чужие рабочие копии не трогай.
- Перед работой проверь открытые ветки и PR `codex/*` — не пересекаешься ли по файлам и номеру `D<N>`.
- Плагин: после правки `.claude-plugin/`, `skills/`, `hooks/`, `.mcp.json` — `claude plugin validate .` из `arvix-claude/`.
- Деплой (`deploy/install.sh`, `deploy/sync-server.sh`) можешь запустить сам, но только после мержа и с явного
  «да» владельца в этом разговоре (`AGENTS.md` §8).
