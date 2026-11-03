"""Шаблоны сообщений L0 — чистые строки, без модели (01-ARCHITECTURE §4.2, 05-BOT-TWA §3).

Формулировки без глаголов прошедшего времени с родом («сделано?», а не
«выполнил?»): род человека бот узнаёт только в интервью.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from arvix import rules
from arvix.context import DAY_TYPES_RU, QUOTA_RU, hm

WEEKDAYS_FULL = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")

HELP = """Пиши мне обычным текстом — команды не обязательны. Например:
• «Физику сделал, решил 12 задач» — закрою задачу
• «Спал 6:10, лёг в час» — запишу сон, пересчитаю режим
• «Добавь на завтра алгоритмы в 16:00 на 90 минут»
• «Можно я в 18:00 в зал вместо английского?» — решу по цифрам
• «Потратил 900 на доставку, импульсивно»
• «Что у меня осталось на сегодня?» · «Как я иду к цели?»
• «Запиши мысль: …» — в Obsidian Inbox
• учебный вопрос — дам направление и источники, не готовый ответ

Планы на неделю, цели, роадмапы, каркасы заметок — в Claude Code: cd ~/Arvix && claude

Команды:
/day /week /status — день, неделя, уровень и HP
/done <id> [что сделано] · /add Физика 18:00 60м !4 [deep] [завтра]
/sleep 7:30 [00:10] · /spend 1200 еда [!] · /note текст · /find запрос
/focus 45 — фокус-сессия · /reason заболел — причина дня (щит)
/debrief — разбор сейчас · /answer — готовый ответ на следующий учебный вопрос
/onboard · /skip · /pause — знакомство
/silent — тихий день · /sos — режим 🟥 · /mentor on — вернуть ментора · /export"""

ONBOARD_INTRO = (
    "Чтобы держать твой день, мне нужно тебя знать. 37 вопросов, 8 блоков, страхи — последними.\n"
    "Отвечай как есть, коротко можно. /skip — пропустить вопрос, /pause — остановиться, /onboard — продолжить.\n"
    "Начнём с ядра: без него система не запустится."
)
ONBOARD_DONE = "Знакомство пройдено. Профиль собран — открой Arvix/Profile.md в Obsidian после /export."
ASK_REPORT = "Одним предложением: что именно сделано?"
ASK_PHOTO = "Фото-отчёт: пришли фото с подписью. Или одним предложением — что сделано."
ASK_PARTIAL = "Сколько процентов сделано и что помешало? Например: «60, не хватило времени»."
ASK_FAIL_REASON = "Что помешало? Одной фразой — это пойдёт в разбор."
FALLBACK = "Голова сейчас недоступна — лимит подписки или сеть. Сообщение в журнале, отвечу, когда связь вернётся. Учёт и напоминания работают."
GENTLE_FALLBACK = "Я рядом. Сегодня без планов и цифр: поесть, немного движения, лечь пораньше. Одна маленькая вещь — любая."
DEBRIEF_FALLBACK_QUESTIONS = ["Что сегодня сработало — конкретно?", "Что помешало и что меняем завтра?"]
RETURN_HINT = (
    "<return_protocol>Человек вернулся после {days} дн молчания. Никакого разбора прошлого и никаких цифр за пропуск. "
    "Один вопрос «что случилось» и один маленький шаг на сегодня. Разбор пропущенного — не раньше чем через 3 дня стабильной работы.</return_protocol>"
)
IGNORE_DAY2 = "Второй день тишины. Одно слово — и я пойму, что происходит."
IGNORE = {
    2: "Три дня. Я не знаю, что происходит, и это хуже, чем провал. Напиши одно слово.",
}
IGNORE_LATER = "Я здесь."
SILENT_TODAY = "Ты сегодня молчишь. Что происходит?"


def task_buttons_before(task_id: str) -> list[list[tuple[str, str]]]:
    return [[("Начать сейчас", f"t:{task_id}:start"), ("Отложить 15", f"t:{task_id}:d15")], [("Не смогу", f"t:{task_id}:no")]]


def task_buttons_check(task_id: str) -> list[list[tuple[str, str]]]:
    return [[("✅ Да", f"t:{task_id}:yes"), ("⚠️ Частично", f"t:{task_id}:part"), ("❌ Нет", f"t:{task_id}:no")]]


def reminder_before(task: Any, minutes: int) -> str:
    debt = " · ДОЛГ" if task.status == "debt" or task.debt_since else ""
    return f"⏱ Через {minutes} мин: {task.title} · {task.duration_min} мин{debt}"


def reminder_start(task: Any) -> str:
    return f"▶️ Блок пошёл: {task.title}. {task.duration_min} минут. Телефон — убрать."


def reminder_check(task: Any) -> str:
    return f"Сделано: {task.title}?"


def completed(title: str, xp: int, debt_closed: bool = False) -> str:
    return f"✅ {title} · +{xp} XP" + (" · долг закрыт" if debt_closed else "")


def failed(title: str, hp: int, debt: bool) -> str:
    return f"❌ {title} · {hp} HP" + (" · ушла в долг" if debt else "")


def safety(support: str | None) -> str:
    person = f", например {support}" if support else ""
    return (
        "Похоже, тебе сейчас по-настоящему тяжело. Режим ментора выключен: никаких задач, цифр и штрафов.\n"
        f"Это не то, с чем должен справляться бот. Напиши или позвони живому человеку{person} — прямо сейчас. "
        "Если есть угроза жизни — 112.\n"
        "Я здесь, если захочется просто написать. Вернуть режим ментора — /mentor on, когда решишь."
    )


def _task_short(task: Any) -> str:
    debt = ", ДОЛГ" if task.debt_since else ""
    return f"{task.start or '--:--'} {task.title} ({task.duration_min} мин{debt})"


def brief(core: Any) -> str:
    st = core.state
    now = core.now()
    today = now.date()
    day = st.days.get(today)
    head = f"☀️ {now:%H:%M} · {WEEKDAYS_FULL[today.weekday()]}"
    if day and day.day_type:
        head += f" · {DAY_TYPES_RU.get(day.day_type, day.day_type)} день"
    if core.effective_mode() == "red":
        return head + "\n\nСегодня без плана и без цифр. Сон, еда, движение и одна маленькая вещь — любая. Я рядом."
    lines = [head, ""]
    mode = rules.MODE_LABELS[st.mode] + (f" — {st.mode_trigger}" if st.mode_trigger else "")
    lines.append(f"Режим {mode}.")
    yesterday = st.days.get(today - timedelta(days=1))
    if yesterday and yesterday.closed and yesterday.closed.get("total"):
        lines.append(f"Вчера: {yesterday.closed['done']} из {yesterday.closed['total']}, глубокая {hm(yesterday.deep_min)}.")
    tasks = [t for t in st.tasks_on(today) if t.is_open]
    if tasks:
        lines += ["", f"Сегодня {len(tasks)}:"] + [f"{i}. {_task_short(t)}" for i, t in enumerate(tasks[:6], 1)]
    else:
        lines.append("Плана на сегодня нет. Напиши, что делаешь, — соберу.")
    debts = st.debts()
    if debts:
        lines.append("Долг: " + ", ".join(t.title for t in debts[:3]))
    week = st.week_stats(today)
    quotas = core.cfg.mech("quotas") or {}
    if today.weekday() >= 2:
        missing = [f"{QUOTA_RU.get(k, k)} {week['quotas'].get(k, 0)}/{v}" for k, v in quotas.items() if week["quotas"].get(k, 0) < v]
        if missing:
            lines.append("Квоты недели: " + " · ".join(missing))
    if not (day and day.sleep_min):
        lines.append("\nСон не записан: ответь числом, например 7:20, или /sleep 7:20 00:30.")
    if st.profile.get("bedtime_target"):
        lines.append(f"Отбой сегодня в {st.profile['bedtime_target']}. Не обсуждается.")
    return "\n".join(lines)


def midday(core: Any) -> str | None:
    st = core.state
    today = core.today()
    tasks = st.tasks_on(today)
    completion = st.completion(today)
    if not tasks or completion is None or completion >= 40:
        return None
    done = sum(1 for t in tasks if t.status == "done")
    nxt = next((t for t in tasks if t.is_open and t.start and t.start >= core.now().strftime("%H:%M")), None)
    text = f"Середина дня: {done} из {len(tasks)}."
    if nxt:
        text += f" Следующий блок {nxt.start} — «{nxt.title}». Он решает, каким будет день."
    return text


def debrief_facts(core: Any) -> str:
    facts = core.day_facts()
    lines = ["🌙 Разбор", "", f"Сделано: {facts['done']} из {facts['total']}. Глубокая {hm(facts['deep_min'])} из {hm(int(core.cfg.mech('deep_target_min', 120)))}."]
    if facts["sleep_min"]:
        lines.append(f"Сон {hm(facts['sleep_min'])}.")
    quotas = core.cfg.mech("quotas") or {}
    lines.append("Квоты: " + " · ".join(f"{QUOTA_RU.get(k, k)} {facts['week']['quotas'].get(k, 0)}/{v}" for k, v in quotas.items()))
    if facts["debts"]:
        lines.append("Долг: " + ", ".join(t.title for t in facts["debts"]))
    if facts["impulse"]:
        lines.append("Импульсивные траты: " + ", ".join(f"{e['amount']:.0f} {e['category']}" for e in facts["impulse"]))
    return "\n".join(lines)


def status(core: Any) -> str:
    s = core.status()
    season = s["season"]
    lines = [
        f"Режим: {rules.MODE_LABELS[s['effective_mode']]}" + (f" ({s['mode_trigger']})" if s["mode_trigger"] else ""),
        f"Уровень {s['level']} · {s['xp_into']}/{s['xp_need']} XP · HP {s['hp']} · стрик {s['streak']} дн",
        f"Сезон S{season['number']}, неделя {season['week']}: {season['rank']} (SP {season['sp_avg']}) · щитов {s['shields_left']}",
    ]
    if not s["mentor_enabled"]:
        lines.append("Ментор выключен safety-контуром. Вернуть: /mentor on")
    if s["protocol_zero"]:
        lines.append("Протокол Ноль: сон, еда, движение, одна задача в день.")
    return "\n".join(lines)


def week(core: Any) -> str:
    stats = core.state.week_stats(core.today())
    quotas = core.cfg.mech("quotas") or {}
    lines = [
        f"Неделя с {stats['start']:%d.%m}",
        f"Продуктивно {hm(stats['productive_min'])} из {hm(int(core.cfg.mech('week_budget_min', 1560)))} · глубокая {hm(stats['deep_min'])} из {hm(int(core.cfg.mech('week_deep_budget_min', 480)))}",
        "Квоты: " + " · ".join(f"{QUOTA_RU.get(k, k)} {stats['quotas'].get(k, 0)}/{v}" for k, v in quotas.items()),
    ]
    if stats["expenses"]:
        top = sorted(stats["expenses"].items(), key=lambda x: -x[1])[:3]
        lines.append("Траты: " + ", ".join(f"{k} {v:.0f}" for k, v in top) + (f" · импульсивные {stats['impulse']:.0f}" if stats["impulse"] else ""))
    return "\n".join(lines)


def question(q: dict[str, Any], number: int, total: int) -> str:
    return f"[{q['block_title']} · {number}/{total}]\n{q['text']}"
