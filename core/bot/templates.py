"""Шаблоны сообщений L0 — чистые строки, без модели (01-ARCHITECTURE.md §1)."""

ONBOARDING_INVITE = (
    "Я Арвикс.\n\n"
    "Прежде чем начать — мне нужно знать минимум о тебе: имя, город, "
    "когда ложишься и встаёшь, какие дни заняты, и одна главная цель на год. "
    "Две минуты, дальше я работаю сам."
)

ONBOARDING_BUTTON_TEXT = "Начать"


def onboarding_confirmation(goal_title: str) -> str:
    return (
        f"Профиль сохранён. Главная цель: «{goal_title}».\n\n"
        "Дальше строю расписание и шаблоны дней — это следующий шаг. "
        "Пока полноценного плана нет, честно: рано выдумывать задачи без него."
    )


def welcome_back() -> str:
    return "С возвращением. Расписания и команд пока нет — это следующие шаги."


# --- Напоминания о задачах (05-BOT-TWA.md §3.2) ---


def reminder_t_minus_5(task_title: str, duration_min: int, importance: int) -> str:
    """Напоминание за 5 минут до начала задачи."""
    importance_marker = "ДОЛГ" if importance >= 4 else ""
    return (
        f"⏱ Через 5 минут: {task_title} · {duration_min} мин"
        + (f" · {importance_marker}" if importance_marker else "")
    )


def reminder_started(task_title: str, duration_min: int) -> str:
    """Уведомление о начале блока."""
    return f"▶️ Блок пошёл. {duration_min} минут. Телефон убрал."


def reminder_completion_check(task_title: str) -> str:
    """Запрос подтверждения выполнения."""
    return f"Выполнил: {task_title}?"


def task_started_message(task_title: str) -> str:
    """Подтверждение старта задачи."""
    return f"▶️ Задача запущена: {task_title}"


def task_deferred_message(task_title: str, new_time: str) -> str:
    """Подтверждение переноса задачи."""
    return f"⏳ Задача отложена на {new_time}: {task_title}"


def task_completed_message(task_title: str, xp: int) -> str:
    """Подтверждение завершения задачи."""
    return f"✅ Задача выполнена: {task_title}\n+{xp} XP"


def task_failed_message(task_title: str, hp_damage: int, is_debt: bool) -> str:
    """Уведомление о провале задачи."""
    debt_note = "\n⚠️ Задача ушла в долг." if is_debt else ""
    return f"❌ Задача провалена: {task_title}\n{hp_damage} HP{debt_note}"


def ask_for_report() -> str:
    """Запрос текстового отчета."""
    return "В одном предложении: что конкретно сделал?"


"""Добавить шаблон утреннего брифинга."""


def brief_morning(mode: str, hp: int, streak: int) -> str:
    """Утренний брифинг (L0-шаблон)."""
    mode_emoji = {"normal": "🟢", "yellow": "🟡", "red": "🟥"}.get(mode, "⚪")
    return f"{mode_emoji} Режим: {mode.upper()}\nHP: {hp}/100\nСтрик: {streak} дней"


