"""Хуки Claude Code.

SessionStart подкладывает состояние Арвикса и тон-блок текущего режима,
UserPromptSubmit — строку «сейчас / режим / день», а при смене режима посреди
сессии — новый тон-блок. Хуки срабатывают только в доме Арвикса (маркер
.arvix-home): в обычных кодинг-сессиях они выходят до импорта ядра и не тратят
ни токенов, ни заметного времени.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

MARKER = ".arvix-home"
EVENTS = {"session-start": "SessionStart", "prompt": "UserPromptSubmit"}


def in_arvix_home(cwd: str) -> bool:
    if os.environ.get("ARVIX_BRAIN"):
        return False  # голова Telegram собирает промпт сама
    path = Path(cwd).expanduser().resolve()
    return any((candidate / MARKER).exists() for candidate in [path, *path.parents][:6])


def prompt_line(core) -> str:
    from arvix import rules
    from arvix.context import WEEKDAYS

    st = core.state
    now = core.now()
    mode = core.effective_mode()
    line = f"Арвикс · сейчас {WEEKDAYS[now.weekday()]} {now:%d.%m %H:%M} · режим {rules.MODE_LABELS[mode]}"
    if mode == "red":
        return line + " · без метрик и задач, человеческий тон"
    tasks = st.tasks_on(now.date())
    done = sum(1 for t in tasks if t.status == "done")
    return line + f" · HP {st.hp} · сегодня {done}/{len(tasks)}"


def _remote_configured() -> bool:
    from arvix.remote import target

    return target() is not None


def run(event: str) -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        data = {}
    trusted = "--trusted" in sys.argv  # вызов с ноутбука через SSH: дом уже проверен там
    if not trusted and not in_arvix_home(data.get("cwd") or os.getcwd()):
        return 0
    from arvix.remote import run_remote

    forwarded = run_remote("arvix_hook.py", [event, "--trusted"], json.dumps(data), timeout=8)
    if forwarded is not None:
        print(forwarded, end="")
        return 0
    if _remote_configured():
        print(json.dumps({"hookSpecificOutput": {"hookEventName": EVENTS[event], "additionalContext":
                          "Arvix: сервер недоступен — состояние не загружено. Проверь интернет и `arvix doctor`."}}, ensure_ascii=False))
        return 0
    session = str(data.get("session_id") or "")
    try:
        from arvix.core import Core
        from arvix.prompt import hook_context, tone_block

        core = Core()
        core.refresh()
        mode = core.effective_mode()
        if event == "session-start":
            text = hook_context(core)
        else:
            text = prompt_line(core)
            if session and core.store.kv_get(f"hook_mode:{session}") not in (None, mode):
                text += "\nРежим сменился. Новый тон-блок:\n" + tone_block(core.state.mode, core.state.mentor_enabled)
        if session:
            core.store.kv_set(f"hook_mode:{session}", mode)
    except Exception as exc:  # noqa: BLE001 — хук не должен ломать сессию
        text = f"Arvix: состояние недоступно ({exc}). Проверь `arvix doctor`."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": EVENTS[event], "additionalContext": text}}, ensure_ascii=False))
    return 0
