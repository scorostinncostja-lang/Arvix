"""Суточный цикл L0: закрытие дня, материализация шаблона, Протокол Ноль.

catch_up() идемпотентен: его безопасно звать из любого процесса и сколько угодно
раз — день закрывается ровно одним событием day_closed (02-MECHANICS §3, §7, §8).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from arvix import rules
from arvix.config import parse_hhmm

log = logging.getLogger("arvix.daily")
MAX_CATCH_UP_DAYS = 14


def catch_up(core: Any) -> None:
    now = core.now()
    rollover = parse_hhmm(core.cfg.schedule("rollover")) or datetime.min.time()
    last_closable = now.date() - timedelta(days=1 if now.time() >= rollover else 2)
    first = core.state.first_date
    if first is not None:
        d = max(first, last_closable - timedelta(days=MAX_CATCH_UP_DAYS - 1))
        while d <= last_closable:
            day = core.state.days.get(d)
            if not (day and day.closed):
                close_day(core, d)
            d += timedelta(days=1)
    finish_protocol_zero(core)
    review_budget(core)
    if now.time() >= rollover:
        materialize(core, now.date())
    core.recompute_mode()


def review_budget(core: Any) -> dict[str, Any] | None:
    """Раз в 4 недели: поднять, удержать или снизить бюджет недели (02-MECHANICS §5)."""
    budget = core.budget()
    today = core.today()
    if today < budget["next_review"] or not core.state.profile.get("season_start"):
        return None
    with core.tx():
        if core.budget()["next_review"] > today:
            return None
        start = today - timedelta(days=rules.BUDGET_REVIEW_DAYS)
        closed = [d.closed for x, d in core.state.days.items() if start <= x < today and d.closed]
        with_tasks = [c for c in closed if c.get("total")]
        sleeps = [c["sleep_min"] for c in closed if c.get("sleep_min")]
        week, deep, verdict, reason = rules.review_budget(
            week_min=budget["week_min"], deep_min=budget["deep_min"],
            completion_avg=sum(c["completion"] or 0 for c in with_tasks) / len(with_tasks) if with_tasks else None,
            sleep_avg=sum(sleeps) / len(sleeps) if sleeps else None,
            red_days=sum(1 for c in closed if c.get("mode") == "red"),
            yellow_days=sum(1 for c in closed if c.get("mode") == "yellow"),
            days_with_data=len(with_tasks),
        )
        payload = {"week_min": week, "deep_min": deep, "verdict": verdict, "reason": reason,
                   "from_week_min": budget["week_min"], "from_deep_min": budget["deep_min"]}
        core.emit("budget_set", payload, source="scheduler")
    return payload


def close_day(core: Any, d: date) -> dict[str, Any] | None:
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
        ignore_days = st.ignore_streak(d)
        # Протокол Ноль считается «идущим», пока не закрыт событием, — даже если
        # дни закрываются задним числом после сна ноутбука.
        in_zero = st.zero_until is not None
        mult = rules.penalty_multiplier(
            mode=st.mode, mentor_enabled=st.mentor_enabled, hp=st.hp, silent=day.silent,
            ignore_days=ignore_days, protocol_zero=in_zero,
        )
        damages: list[tuple[int, str, str | None]] = []  # (урон, причина, единоразовый ключ)

        # 1. Неотчитанные задачи. Если Арвикс ни разу не спросил (бот выключен,
        #    работа только в Claude Code) — без урона и без долга: наказывать за
        #    вопрос, которого не было, нечестно.
        for task in [t for t in tasks if t.is_open]:
            per_task = rules.HP_FAIL[task.importance] if asked and answered else 0
            core.emit(
                "task_failed",
                {"id": task.id, "reason": "no_report", "debt": asked and task.importance >= 4, "hp": per_task},
                source="scheduler",
                entity_id=task.id,
            )
            if per_task:
                damages.append((per_task, f"task_failed:{task.id}", None))
        # Игнор весь день — один штраф вместо стены за каждую задачу (02-MECHANICS §7).
        if ignored:
            damages.append((rules.HP_IGNORE_DAY, "ignore_day", None))

        # 2. Сон и отбой.
        if dmg := rules.sleep_damage(day.sleep_min):
            damages.append((dmg, "sleep", None))
        late = rules.minutes_after(st.profile.get("bedtime_target"), day.bedtime)
        if late is not None and late > 120:
            damages.append((rules.HP_LATE_BEDTIME, "late_bedtime", None))

        # 3. Вечерний разбор — единственное, что нельзя пропускать.
        if f"debrief:{d.isoformat()}" in day.out_keys and not day.debrief and not day.silent:
            damages.append((rules.HP_NO_DEBRIEF, "no_debrief", None))

        # 4. Три дня подряд < 40% — единоразово.
        completion = st.completion(d)
        recent = [c for c in st.series(d - timedelta(days=1), 2, "completion")] + [completion]
        if all(c is not None and c < 40 for c in recent):
            key = f"low3:{(d - timedelta(days=2)).isoformat()}"
            if not any(k.startswith("low3:") and date.fromisoformat(k[5:]) > d - timedelta(days=5) for k in st.penalized):
                damages.append((rules.HP_LOW_3_DAYS, "low_3_days", key))

        # 5. Долг старше 7 дней — единоразово на задачу.
        for task in st.debts():
            key = f"debt_overdue:{task.id}"
            if task.debt_since and (d - task.debt_since).days >= rules.DEBT_OVERDUE_DAYS and key not in st.penalized:
                damages.append((rules.HP_DEBT_OVERDUE, f"debt_overdue:{task.id}", key))

        # 6. Недельные квоты — по воскресеньям, и только если неделя вообще велась
        #    (иначе тот, кто квоты не трогал, получал бы −20 HP каждое воскресенье).
        xp_bonus: list[tuple[int, str]] = []
        week_days = [d - timedelta(days=i) for i in range(7)]
        if d.weekday() == 6 and st.profile.get("season_start") and any(st.tasks_on(x) for x in week_days):
            stats = st.week_stats(d)
            for sphere, target in (cfg.mech("quotas") or {}).items():
                actual = stats["quotas"].get(sphere, 0)
                met = actual >= int(target)
                core.emit("quota_result", {"sphere": sphere, "target": int(target), "actual": actual, "met": met, "week": stats["start"].isoformat()}, source="scheduler")
                if met:
                    xp_bonus.append((rules.BONUS_QUOTA, f"quota:{sphere}"))
                else:
                    damages.append((rules.HP_QUOTA_MISSED, f"quota:{sphere}", None))

        # 7. Щит: при заявленной причине снимает самый крупный урон дня, включая
        #    уже начисленный днём (компенсирующим событием).
        refund = 0
        if day.reason and core.state.shields_used(d) < int(cfg.mech("shields_per_month", 2)):
            pool = [(amount, reason) for amount, reason in day.damages] + [(round(a * mult), r) for a, r, _ in damages]
            pool = [x for x in pool if x[0] < 0]
            if pool:
                worst = min(pool, key=lambda x: x[0])
                core.emit("shield_used", {"date": d.isoformat(), "reason": day.reason, "damage_prevented": -worst[0], "target": worst[1]}, source="scheduler")
                if (worst[0], worst[1]) in day.damages:
                    refund = -worst[0]
                else:
                    for i, (_amount, r, _key) in enumerate(damages):
                        if r == worst[1]:
                            damages.pop(i)
                            break

        for amount, reason, once_key in damages:
            value = round(amount * mult)
            if value:
                core.emit("hp_changed", {"amount": value, "reason": reason, "date": d.isoformat(), "once_key": once_key}, source="scheduler")
            elif once_key:
                core.emit("hp_changed", {"amount": 0, "reason": f"{reason}:frozen", "date": d.isoformat(), "once_key": once_key}, source="scheduler")
        if refund:
            core.emit("hp_changed", {"amount": refund, "reason": "shield_refund", "date": d.isoformat()}, source="scheduler")

        # 8. Бонусы и регенерация (02-MECHANICS §2, §3).
        sleep_target = int(st.profile.get("sleep_target_min") or cfg.mech("sleep_target_min", 450))
        sleep_ok = day.sleep_min is not None and day.sleep_min >= sleep_target - 30
        if completion is not None and completion >= 100:
            xp_bonus.append((rules.BONUS_FULL_DAY, "full_day"))
        if sleep_ok:
            xp_bonus.append((rules.BONUS_SLEEP, "sleep_norm"))
        if day.silent and completion is not None and completion >= 70:
            xp_bonus.append((rules.BONUS_SILENT_DAY, "silent_day"))
        for amount, reason in xp_bonus:
            core.emit("xp_awarded", {"amount": amount, "reason": reason, "date": d.isoformat()}, source="scheduler")
        if completion is not None and completion >= 70 and sleep_ok and st.hp < rules.HP_MAX:
            core.emit("hp_changed", {"amount": rules.HP_REGEN, "reason": "regen", "date": d.isoformat()}, source="scheduler")

        # 9. HP = 0 → Протокол Ноль, а не потеря уровня.
        if core.state.hp == 0 and core.state.zero_until is None:
            until = core.now() + timedelta(hours=48)
            core.emit("protocol_zero", {"on": True, "until": until.isoformat()}, source="scheduler")

        deep_target = int(cfg.mech("deep_target_min", 120))
        payload = {
            "date": d.isoformat(),
            "completion": completion,
            "total": len(tasks),
            "done": sum(1 for t in core.state.tasks_on(d) if t.status == "done"),
            "deep_min": day.deep_min,
            "sleep_min": day.sleep_min,
            "sp": 0.0 if in_zero else rules.sp_for_day(completion, day.sleep_min, sleep_target, day.deep_min, deep_target),
            "ignored": ignored,
            "penalty_mult": mult,
            "hp_end": core.state.hp,
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


def finish_protocol_zero(core: Any) -> None:
    """По выходу из Протокола Ноль HP = 50 (02-MECHANICS §3)."""
    until = core.state.zero_until
    if until and datetime.fromisoformat(until) <= core.now():
        with core.tx():
            core.emit("protocol_zero", {"on": False}, source="scheduler")
            delta = rules.HP_AFTER_ZERO - core.state.hp
            if delta > 0:
                core.emit("hp_changed", {"amount": delta, "reason": "protocol_zero_exit"}, source="scheduler")


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
        for block in template["blocks"]:
            if d == now.date() and block["start"] and core.at(d, block["start"]) <= now:
                continue
            task = core.add_task(
                block["title"], sphere=block["sphere"], importance=block["importance"], difficulty=block["difficulty"],
                start=block["start"], duration_min=block["duration"], deep_work=block["deep_work"], day=d.isoformat(),
                tags=block.get("tags") or (), task_source="recurring", source="scheduler",
            )
            created.append(task.id)
    return created
