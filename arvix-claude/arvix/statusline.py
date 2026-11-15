"""Строка состояния Claude Code (statusLine): режим, уровень, HP, день, следующий блок.

Claude Code зовёт команду после каждого ответа (дебаунс 300 мс) и раз в минуту —
поэтому здесь только код, без ИИ, и ответ за доли секунды. В 🟥 и при выключенном
менторе цифр нет (правило №5): строка не должна давить, когда давить нельзя.
"""

from __future__ import annotations

from typing import Any

from arvix import rules

CACHE_TTL = 60  # с: в удалённом режиме строка берётся с сервера не чаще раза в минуту
TITLE_LEN = 26


def render(core: Any, session: dict[str, Any] | None = None) -> str:
    """Одна строка. session — JSON, который Claude Code подаёт на stdin (может быть пустым)."""
    st = core.state
    status = core.status()
    mode = status["effective_mode"]
    label = rules.MODE_LABELS[mode]
    if mode == "red":
        return f"{label} · без цифр и задач"
    today = core.today()
    tasks = st.tasks_on(today)
    done = sum(1 for t in tasks if t.status == "done")
    parts = [label, f"ур.{status['level']}", f"HP {status['hp']}", f"сегодня {done}/{len(tasks)}"]
    now = core.now().strftime("%H:%M")
    active = next((t for t in tasks if t.status == "active"), None)
    upcoming = next((t for t in tasks if t.status == "planned" and t.start and t.start >= now), None)
    if active:
        parts.append(f"▶ {active.title[:TITLE_LEN]}")
    elif upcoming:
        parts.append(f"→ {upcoming.start} {upcoming.title[:TITLE_LEN]}")
    if status["debts"]:
        parts.append(f"долг {status['debts']}")
    day = st.days.get(today)
    if day and day.silent:
        parts.append("тихий день")
    percent = ((session or {}).get("context_window") or {}).get("used_percentage")
    if percent is not None:
        try:
            parts.append(f"ctx {float(percent):.0f}%")
        except (TypeError, ValueError):
            pass
    return " · ".join(parts)
