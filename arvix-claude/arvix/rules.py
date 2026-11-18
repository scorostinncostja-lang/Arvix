"""Правила L0 — чистые функции без ИИ (00-VISION П3, 02-MECHANICS).

Модель про эти решения ничего не решает: она их только читает. Игры здесь нет (D41):
ни очков, ни здоровья, ни уровней, ни сезонов — только факты дня и защита от выгорания.
"""

from __future__ import annotations

SPHERES = ("learning", "work", "sport", "social", "health", "finance", "project", "chore")
# Необязательные дела, которые блокируются при долге >= 2 (02-MECHANICS §4).
OPTIONAL_SPHERES = ("social",)
MODES = ("normal", "pressure", "yellow", "red")
MODE_LABELS = {"normal": "🟩 НОРМА", "pressure": "🟦 ДАВЛЕНИЕ", "yellow": "🟨 ЖЁЛТЫЙ", "red": "🟥 КРАСНЫЙ"}
# Уровни safety-флага, которые выключают ментора (02-MECHANICS §6). Остальные
# («info», «low») — не беда, а сведения: они пишутся фактом о человеке.
SAFETY_ALARM_LEVELS = ("high", "critical")


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def derive_proof(importance: int, sphere: str, deep_work: bool) -> str:
    """Каким отчётом закрывается задача (02-MECHANICS §1): ритуал, а не множитель очков.
    Для глубокой работы отчёт словами показательнее фото."""
    if deep_work:
        return "report"
    if importance >= 4 or sphere == "sport":
        return "photo"
    if importance == 3:
        return "report"
    return "confirm"


def minutes_after(target: str | None, actual: str | None) -> int | None:
    """На сколько минут actual позже target (оба HH:MM). Время до полудня считается
    следующими сутками: отбой в 01:30 при цели 23:30 — это +120, а не −1320."""
    if not target or not actual:
        return None

    def to_min(value: str) -> int:
        hours, _, minutes = value.partition(":")
        total = int(hours) * 60 + int(minutes or 0)
        return total + 1440 if total < 720 else total

    return to_min(actual) - to_min(target)


def guard_mode(
    *,
    sleep: list[int | None],
    completion: list[float | None],
    sos: bool,
    recovery: bool = False,
    after_red: bool = False,
) -> tuple[str, str]:
    """Burnout Guard, 02-MECHANICS §6. Возвращает (режим, триггер).

    sleep — минуты сна по дням, completion — % выполнения закрытых дней (None —
    день без задач и день, закрытый в 🟥: плана тогда не было); в обоих списках новейший
    элемент последний. Нет данных о сне — нет и «давления»: нельзя утверждать «ты выспался»,
    не зная этого. Входы — только факты (сон, выполнение, просьба человека), без очков (D41).

    Из 🟥 есть выход (D38): сон снимается сам, как только записан нормальный сегодняшний;
    recovery — человек сам нажал «Вернуться к плану» (не модель); after_red — первый день
    после 🟥 тоже 🟨, без разгона. Ручной SOS — выбор человека: снимает его только он или 24 ч.
    """
    if sos:
        return "red", "ручной SOS"
    red = ""
    last3 = sleep[-3:]
    if len(last3) == 3 and all(s is not None and s < 300 for s in last3):
        red = "сон <5ч 3 дня подряд"
    week = [c for c in completion[-7:] if c is not None]
    if not red and len(week) >= 5 and sum(week) / len(week) < 20:
        red = "выполнение <20% неделю"
    if red:
        return ("yellow", f"возвращение после 🟥 ({red})") if recovery else ("red", red)
    last2 = sleep[-2:]
    if len(last2) == 2 and all(s is not None and s < 360 for s in last2):
        return "yellow", "сон <6ч 2 дня подряд"
    recent = [c for c in completion[-3:] if c is not None]
    if recent:
        avg = sum(recent) / len(recent)
        if 20 <= avg <= 40:
            return "yellow", f"выполнение {avg:.0f}%"
        known = [s for s in last3 if s is not None]
        if avg < 50 and known and sum(known) / len(known) >= 420 and not (after_red or recovery):
            return "pressure", f"выполнение {avg:.0f}% при нормальном сне"
    if after_red or recovery:
        return "yellow", "первый день после 🟥: без разгона"
    return "normal", ""


def frozen(*, mode: str, mentor_enabled: bool, silent: bool, ignore_days: int, reason: bool = False) -> bool:
    """Дни, когда неотмеченное важное не уходит в долг (02-MECHANICS §4): 🟥, выключенный
    ментор, тихий день, 3+ дня тишины, заявленная причина дня. Бот в эти дни о задачах не
    напоминал или человек честно сказал, почему не смог, — записывать это долгом нечестно."""
    return silent or mode == "red" or not mentor_enabled or ignore_days >= 3 or reason
