"""Автонагрузка: Арвикс сам решает, сколько глубокой работы, учёбы, спорта и отдыха.

Человек не задаёт часы. Шаблоны дней — это структура (когда и что), а объём каждого
канала задаёт коэффициент, который код пересчитывает раз в неделю по фактам:
выполнение по каналу, сон, HP, дни 🟨/🟥. Правила (02-MECHANICS §5, П1):

- снижаем быстро, растим медленно: признаки выгорания — сразу −20% работы и +20% отдыха,
  рост +10% — только после двух подряд недель с выполнением канала ≥ 85%;
- мёртвая зона: 50–85% выполнения — ничего не трогаем, один плохой день план не дёргает;
- мало данных (< 4 дней с задачами) — держим;
- коэффициенты в [0.5; 1.5], старт — 0.7 для самостоятельной работы (люди переоценивают силы);
- обязательное (школа, дорога, еда) не масштабируется никогда.

Всё здесь — чистые функции без ИИ (правило №1).
"""

from __future__ import annotations

import re
from typing import Any

CHANNELS = ("deep", "learning", "sport", "rest", "other")
CHANNEL_LABELS = {"deep": "глубокая работа", "learning": "учёба", "sport": "спорт", "rest": "отдых", "other": "прочее"}
WORK_CHANNELS = ("deep", "learning", "other")
START_FACTORS = {"deep": 0.7, "learning": 0.7, "sport": 0.7, "rest": 1.0, "other": 1.0}
FACTOR_RANGE = (0.5, 1.5)
MIN_BLOCK = 15
REVIEW_DAYS = 7
MIN_DATA_DAYS = 4
GROW_AT, HOLD_AT = 0.85, 0.5
GROW_WEEKS = 2

FIXED_TITLE = re.compile(
    r"школ|урок|занят[иь]я в|колледж|универ|пар[аы]\b|дорог|завтрак|обед|ужин|еда|сон\b|подъ[её]м|отбой|работа\b|смена|репетитор|секци",
    re.IGNORECASE,
)


def is_fixed(block: dict[str, Any]) -> bool:
    """Обязательное время, которое нельзя сжать: явный флаг или очевидное название."""
    if "fixed" in block:
        return bool(block["fixed"])
    return bool(FIXED_TITLE.search(block.get("title", "")))


def channel_of(item: dict[str, Any]) -> str:
    """Канал блока шаблона или задачи (sphere / deep_work / tags)."""
    if item.get("deep_work"):
        return "deep"
    sphere = item.get("sphere")
    tags = item.get("tags") or ()
    if sphere == "learning":
        return "learning"
    if sphere == "sport":
        return "sport"
    if sphere in ("health", "social") or "offscreen" in tags or "rest" in tags:
        return "rest"
    return "other"


def factors_of(budget: dict[str, Any] | None) -> dict[str, float]:
    saved = (budget or {}).get("factors") or {}
    return {ch: float(saved.get(ch, START_FACTORS[ch])) for ch in CHANNELS}


def scaled_duration(block: dict[str, Any], factors: dict[str, float]) -> int:
    duration = int(block.get("duration", 60))
    if is_fixed(block):
        return duration
    value = duration * factors[channel_of(block)]
    return max(MIN_BLOCK, int(round(value / 5) * 5))


def week_load(templates: dict[int, dict[str, Any]], factors: dict[str, float]) -> dict[str, int]:
    """Минуты недели по каналам после масштабирования (+ total и fixed)."""
    out = {ch: 0 for ch in CHANNELS} | {"fixed": 0, "total": 0}
    for template in templates.values():
        for block in template.get("blocks", []):
            minutes = scaled_duration(block, factors)
            out["total"] += minutes
            if is_fixed(block):
                out["fixed"] += minutes
            else:
                out[channel_of(block)] += minutes
    return out


def _clamp(value: float) -> float:
    return round(min(FACTOR_RANGE[1], max(FACTOR_RANGE[0], value)) * 20) / 20


def review(
    factors: dict[str, float], *, channels: dict[str, dict[str, int]], streaks: dict[str, int],
    days_with_data: int, red_days: int, yellow_days: int,
    sleep_avg: float | None, sleep_target: int, hp_drop: int,
) -> dict[str, Any]:
    """Новые коэффициенты по итогам недели.

    channels: {канал: {"planned": мин, "done": мин}} за неделю (без обязательного).
    streaks: сколько недель подряд канал выполнен ≥ 85% (для медленного роста).
    Возвращает factors, streaks, verdict (up|down|hold), reasons (строки для человека).
    """
    new = dict(factors)
    new_streaks = {ch: int(streaks.get(ch, 0)) for ch in CHANNELS}
    reasons: list[str] = []

    if days_with_data < MIN_DATA_DAYS:
        return {"factors": new, "streaks": new_streaks, "verdict": "hold",
                "reasons": [f"мало данных ({days_with_data} дн с задачами) — нагрузка держится"]}

    sleep_debt = sleep_target - sleep_avg if sleep_avg is not None else 0
    signs = []
    if red_days:
        signs.append(f"🟥 {red_days} дн")
    if yellow_days:
        signs.append(f"🟨 {yellow_days} дн")
    if sleep_debt > 30:
        signs.append(f"сон {sleep_avg / 60:.1f} ч при норме {sleep_target / 60:.1f}")
    if hp_drop >= 10:
        signs.append(f"HP −{hp_drop}")
    hard = red_days >= 2 or yellow_days >= 3 or sleep_debt > 60 or hp_drop >= 20
    soft = not hard and bool(signs)

    if hard or soft:
        cut, rest_up = (0.8, 1.2) if hard else (0.9, 1.1)
        for ch in WORK_CHANNELS:
            new[ch] = _clamp(new[ch] * cut)
        new["rest"] = _clamp(new["rest"] * rest_up)
        if hard and sleep_debt > 60:
            new["sport"] = _clamp(new["sport"] * 0.9)
        new_streaks = {ch: 0 for ch in CHANNELS}
        reasons.append(f"{'перегруз' if hard else 'первые признаки усталости'}: {', '.join(signs)} — "
                       f"работа −{round((1 - cut) * 100)}%, отдых +{round((rest_up - 1) * 100)}%")
    else:
        for ch in CHANNELS:
            stat = channels.get(ch) or {}
            planned, done = int(stat.get("planned", 0)), int(stat.get("done", 0))
            if planned < 60:
                continue
            rate = done / planned
            label = CHANNEL_LABELS[ch]
            if rate < HOLD_AT and ch != "rest":
                new[ch] = _clamp(new[ch] * 0.85)
                new_streaks[ch] = 0
                reasons.append(f"{label}: выполнено {rate:.0%} — план не по силам, −15%")
            elif rate >= GROW_AT:
                new_streaks[ch] += 1
                if new_streaks[ch] >= GROW_WEEKS and ch != "rest":
                    new[ch] = _clamp(new[ch] * 1.1)
                    new_streaks[ch] = 0
                    reasons.append(f"{label}: {GROW_WEEKS} недели подряд ≥ {GROW_AT:.0%} — +10%")
            else:
                new_streaks[ch] = 0

    changed = {ch for ch in CHANNELS if abs(new[ch] - factors[ch]) >= 0.01}
    if not changed:
        verdict = "hold"
        if not reasons:
            reasons.append("темп ровный — нагрузка держится")
    elif all(new[ch] <= factors[ch] for ch in changed if ch != "rest"):
        verdict = "down"
    else:
        verdict = "up"
    return {"factors": new, "streaks": new_streaks, "verdict": verdict, "reasons": reasons}


def describe_change(old: dict[str, float], new: dict[str, float], templates: dict[int, dict[str, Any]]) -> str:
    """«глубокая работа 6ч→5ч, отдых 3ч→3ч30м» — только изменившиеся каналы."""
    before, after = week_load(templates, old), week_load(templates, new)
    parts = []
    for ch in CHANNELS:
        if before[ch] != after[ch]:
            parts.append(f"{CHANNEL_LABELS[ch]} {_hm(before[ch])}→{_hm(after[ch])}")
    return ", ".join(parts)


def _hm(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h}ч{m:02d}м" if h and m else (f"{h}ч" if h else f"{m}м")
