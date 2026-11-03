"""Формулы L0 — чистые функции без ИИ (00-VISION П3, 02-MECHANICS).

Модель про эти числа ничего не решает: она их только читает. Формулы можно
менять — журнал событий позволит пересчитать историю.
"""

from __future__ import annotations

# 02-MECHANICS §2
K_DIFF = {1: 0.6, 2: 0.8, 3: 1.0, 4: 1.4, 5: 2.0}
K_IMP = {1: 0.7, 2: 0.9, 3: 1.0, 4: 1.3, 5: 1.6}
K_PROOF = {"confirm": 1.0, "report": 1.1, "photo": 1.3, "timer": 1.4}
XP_BASE = 10
BONUS_FULL_DAY = 25
BONUS_SLEEP = 15
BONUS_QUOTA = 40
BONUS_SILENT_DAY = 50

# 02-MECHANICS §3
HP_MAX = 100
HP_FAIL = {1: -2, 2: -2, 3: -5, 4: -12, 5: -12}
HP_REGEN = 8
HP_IGNORE_DAY = -10
HP_NO_DEBRIEF = -8
HP_LATE_BEDTIME = -5
HP_LOW_3_DAYS = -20
HP_DEBT_OVERDUE = -15
HP_QUOTA_MISSED = -5
HP_RECOVERY_THRESHOLD = 30
HP_AFTER_ZERO = 50
DEBT_OVERDUE_DAYS = 7

SPHERES = ("learning", "work", "sport", "social", "health", "finance", "project", "chore")
# Необязательные дела, которые блокируются при долге >= 2 (02-MECHANICS §4).
OPTIONAL_SPHERES = ("social",)
MODES = ("normal", "pressure", "yellow", "red")
MODE_LABELS = {"normal": "🟩 НОРМА", "pressure": "🟦 ДАВЛЕНИЕ", "yellow": "🟨 ЖЁЛТЫЙ", "red": "🟥 КРАСНЫЙ"}
RANKS = ((88, "Элита"), (75, "Платина"), (60, "Золото"), (45, "Серебро"), (0, "Бронза"))
SEASON_WEEKS = 5


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def derive_proof(importance: int, sphere: str, deep_work: bool) -> str:
    """02-MECHANICS §1. Для глубокой работы отчёт показательнее фото."""
    if deep_work:
        return "report"
    if importance >= 4 or sphere == "sport":
        return "photo"
    if importance == 3:
        return "report"
    return "confirm"


def k_time(delay_min: float | None) -> float:
    """1.15 — начал раньше плана, 1.0 — в окне ±15 мин, 0.8 — опоздал >15 мин."""
    if delay_min is None:
        return 1.0
    if delay_min < -15:
        return 1.15
    if delay_min > 15:
        return 0.8
    return 1.0


def task_xp(difficulty: int, importance: int, proof: str, delay_min: float | None = None, done_pct: int = 100) -> int:
    xp = XP_BASE * K_DIFF.get(difficulty, 1.0) * K_IMP.get(importance, 1.0) * K_PROOF.get(proof, 1.0) * k_time(delay_min)
    return max(0, int(xp * clamp(done_pct, 0, 100) / 100))


def xp_for_next_level(level: int) -> int:
    """Уровень N → N+1 стоит 100 + 20×(N−1) XP. Уровень не теряется никогда."""
    return 100 + 20 * (level - 1)


def level_info(xp_total: int) -> tuple[int, int, int]:
    """(уровень, XP внутри уровня, XP до следующего)."""
    level, rest = 1, xp_total
    while rest >= xp_for_next_level(level):
        rest -= xp_for_next_level(level)
        level += 1
    return level, rest, xp_for_next_level(level)


def sleep_damage(sleep_min: int | None) -> int:
    if sleep_min is None:
        return 0
    if sleep_min < 300:
        return -12
    if sleep_min < 360:
        return -6
    return 0


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
    hp: int,
    sos: bool,
) -> tuple[str, str]:
    """Burnout Guard, 02-MECHANICS §6. Возвращает (режим, триггер).

    sleep — минуты сна по дням, completion — % выполнения закрытых дней (None —
    день без задач); в обоих списках новейший элемент последний. Нет данных о сне —
    нет и «давления»: нельзя утверждать «ты выспался», не зная этого.
    """
    if sos:
        return "red", "ручной SOS"
    if hp <= 20:
        return "red", f"HP {hp}"
    last3 = sleep[-3:]
    if len(last3) == 3 and all(s is not None and s < 300 for s in last3):
        return "red", "сон <5ч 3 дня подряд"
    week = [c for c in completion[-7:] if c is not None]
    if len(week) >= 5 and sum(week) / len(week) < 20:
        return "red", "выполнение <20% неделю"
    last2 = sleep[-2:]
    if len(last2) == 2 and all(s is not None and s < 360 for s in last2):
        return "yellow", "сон <6ч 2 дня подряд"
    recent = [c for c in completion[-3:] if c is not None]
    if recent:
        avg = sum(recent) / len(recent)
        if 20 <= avg <= 40:
            return "yellow", f"выполнение {avg:.0f}%"
        known = [s for s in last3 if s is not None]
        if avg < 50 and known and sum(known) / len(known) >= 420:
            return "pressure", f"выполнение {avg:.0f}% при нормальном сне"
    return "normal", ""


def penalty_multiplier(*, mode: str, mentor_enabled: bool, hp: int, silent: bool, ignore_days: int, protocol_zero: bool) -> float:
    """🟥, выключенный ментор, тихий день, Протокол Ноль и 3+ дня игнора замораживают
    штрафы; при HP ≤ 30 они действуют вполовину (02-MECHANICS §3, §6, §7)."""
    if silent or mode == "red" or not mentor_enabled or ignore_days >= 3 or protocol_zero:
        return 0.0
    if hp <= HP_RECOVERY_THRESHOLD:
        return 0.5
    return 1.0


def sp_for_day(completion: float | None, sleep_min: int | None, sleep_target: int, deep_min: int, deep_target: int) -> float:
    """Очко сезона: выполнение × 0.6 + сон × 0.2 + глубокая работа × 0.2 (0..100)."""
    done = completion or 0.0
    sleep_norm = 0.0 if not sleep_min else min(100.0, sleep_min / sleep_target * 100)
    deep_norm = min(100.0, deep_min / deep_target * 100) if deep_target else 0.0
    return round(done * 0.6 + sleep_norm * 0.2 + deep_norm * 0.2, 1)


def season_rank(sp_avg: float) -> str:
    for threshold, name in RANKS:
        if sp_avg >= threshold:
            return name
    return "Бронза"
