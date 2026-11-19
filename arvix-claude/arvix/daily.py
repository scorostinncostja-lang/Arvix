"""Суточный цикл L0: закрытие дня, материализация шаблона, пересмотр нагрузки.

catch_up() идемпотентен: его безопасно звать из любого процесса и сколько угодно
раз — день закрывается ровно одним событием day_closed (02-MECHANICS §4, §8, §9, §11).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from arvix import load, rules

log = logging.getLogger("arvix.daily")
MAX_CATCH_UP_DAYS = 14


def catch_up(core: Any) -> None:
    now = core.now()
    past_rollover = f"{now:%H:%M}" >= core.rollover()
    last_closable = now.date() - timedelta(days=1 if past_rollover else 2)
    first = core.state.first_date
    if first is not None:
        d = max(first, last_closable - timedelta(days=MAX_CATCH_UP_DAYS - 1))
        while d <= last_closable:
            day = core.state.days.get(d)
            if not (day and day.closed):
                close_day(core, d)
            d += timedelta(days=1)
    review_budget(core)
    if past_rollover:
        materialize(core, now.date())
    core.recompute_mode()


def review_budget(core: Any) -> dict[str, Any] | None:
    """Раз в неделю: автонагрузка по каналам (arvix/load.py). Без шаблонов дней
    масштабировать нечего — бюджет держится на часах из интервью."""
    st = core.state
    today = core.today()
    if not st.templates or today < core.budget()["next_review"]:
        return None
    with core.tx():
        st = core.state
        budget = core.budget()
        if budget["next_review"] > today:
            return None
        start = today - timedelta(days=load.REVIEW_DAYS)
        channels = {ch: {"planned": 0, "done": 0} for ch in load.CHANNELS}
        for task in st.tasks.values():
            if not start <= task.local_date < today or task.status == "cancelled":
                continue
            item = {"title": task.title, "sphere": task.sphere, "deep_work": task.deep_work, "tags": task.tags}
            if load.is_fixed(item):
                continue
            ch = load.channel_of(item)
            channels[ch]["planned"] += task.duration_min
            if task.status == "done":
                channels[ch]["done"] += task.duration_min * task.done_pct // 100
        closed = [(x, d.closed) for x, d in sorted(st.days.items()) if start <= x < today and d.closed]
        sleeps = [c["sleep_min"] for _, c in closed if c.get("sleep_min")]
        old = load.factors_of(st.budget)
        result = load.review(
            old, channels=channels, streaks=(st.budget or {}).get("streaks") or {},
            days_with_data=sum(1 for _, c in closed if c.get("total")),
            red_days=sum(1 for _, c in closed if c.get("mode") == "red"),
            yellow_days=sum(1 for _, c in closed if c.get("mode") == "yellow"),
            sleep_avg=sum(sleeps) / len(sleeps) if sleeps else None,
            sleep_target=core.sleep_target(),
        )
        week = load.week_load(st.templates, result["factors"])
        change = load.describe_change(old, result["factors"], st.templates)
        payload = {
            "week_min": week["total"] - week["fixed"], "deep_min": week["deep"], "factors": result["factors"], "streaks": result["streaks"],
            "verdict": result["verdict"], "reason": "; ".join(result["reasons"]), "change": change,
            "from_week_min": budget["week_min"], "from_deep_min": budget["deep_min"],
        }
        core.emit("budget_set", payload, source="scheduler")
    return payload


def close_day(core: Any, d: date) -> dict[str, Any] | None:
    """Закрытие дня (02-MECHANICS §11): неотмеченное — проваленным, важное — в долг, итог дня
    фактами. Очков, здоровья, бонусов и щитов нет (D41): день описывают сделанное, глубокие
    минуты и сон, а не число, которое может ошибаться."""
    with core.tx():
        st = core.state
        day = st.day(d)
        if day.closed:
            return None
        cfg = core.cfg
        tasks = st.tasks_on(d)
        asked = day.msgs_out > 0  # бот реально был на связи и писал
        answered = day.user_actions > 0
        ignored = asked and not answered
        hold = rules.frozen(mode=st.mode, mentor_enabled=st.mentor_enabled, silent=day.silent,
                            ignore_days=st.ignore_streak(d), reason=bool(day.reason))

        # Неотмеченные задачи. Если Арвикс ни разу не спросил (бот выключен, работа только
        # в Claude Code), — без долга: спрашивать за вопрос, которого не было, нечестно. В 🟥,
        # тихий день, при 3+ днях тишины и заявленной причине («заболел») долга тоже нет.
        for task in [t for t in tasks if t.is_open]:
            core.emit(
                "task_failed",
                {"id": task.id, "reason": "no_report", "debt": asked and task.importance >= 4 and not hold},
                source="scheduler",
                entity_id=task.id,
            )

        # Недельные квоты — по воскресеньям, и только если неделя вообще велась.
        week_days = [d - timedelta(days=i) for i in range(7)]
        if d.weekday() == 6 and any(st.tasks_on(x) for x in week_days):
            stats = st.week_stats(d)
            for sphere, target in (cfg.mech("quotas") or {}).items():
                actual = stats["quotas"].get(sphere, 0)
                core.emit("quota_result", {"sphere": sphere, "target": int(target), "actual": actual, "met": actual >= int(target),
                                           "week": stats["start"].isoformat()}, source="scheduler")

        payload = {
            "date": d.isoformat(),
            "completion": st.completion(d),
            "total": len(tasks),
            "done": sum(1 for t in core.state.tasks_on(d) if t.status == "done"),
            "deep_min": day.deep_min,
            "sleep_min": day.sleep_min,
            "ignored": ignored,
            "frozen": hold,
            "mode": core.effective_mode(),
        }
        core.emit("day_closed", payload, source="scheduler")
    if core.cfg.vault:
        try:
            from arvix import daily_note

            daily_note.sync(core, d, create=False)
        except Exception as exc:  # noqa: BLE001 — отчёт в Obsidian не должен ломать закрытие дня
            log.warning("ежедневный отчёт за %s не обновлён: %s", d, exc)
    return payload


def materialize(core: Any, d: date) -> list[str]:
    """Шаблон дня недели → задачи. Без шаблона (до онбординга) задач нет: лучше
    честная пустота, чем выдуманный план. Блоки, чьё время уже прошло, не создаются."""
    st = core.state
    template = st.templates.get(d.weekday())
    if not template or st.day(d).materialized:
        return []
    created = []
    with core.tx():
        if core.state.day(d).materialized:
            return []
        core.emit("day_materialized", {"date": d.isoformat(), "day_type": template["day_type"]}, source="scheduler")
        silent_weekday = int(core.cfg.schedule("silent_weekday") or -1)
        if template["day_type"] == "silent" or d.weekday() == silent_weekday:
            core.emit("silent_day", {"date": d.isoformat()}, source="scheduler")
        now = core.now()
        factors = load.factors_of(core.state.budget)
        for block in template["blocks"]:
            if load.is_fixed(block):
                continue  # школа, дорога, смена — занятое время, а не задача с отчётом и долгом
            if d == now.date() and block["start"] and core.at(d, block["start"]) <= now:
                continue
            task = core.add_task(
                block["title"], sphere=block["sphere"], importance=block["importance"], difficulty=block["difficulty"],
                start=block["start"], duration_min=load.scaled_duration(block, factors), deep_work=block["deep_work"], day=d.isoformat(),
                tags=block.get("tags") or (), task_source="recurring", source="scheduler",
            )
            created.append(task.id)
    return created
