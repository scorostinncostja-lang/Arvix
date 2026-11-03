"""Банк вопросов знакомства (05-BOT-TWA §2, стадии 1–2).

Список вопросов — статичный, порядок задаёт код, а не модель. Модель нужна только
там, где ответ свободный: переспросить размытое и разложить ответ на цели, черты
и факты. Что разбирается регулярками (имя, род, сон, часовой пояс) — разбирается
здесь, без ИИ. Страхи идут последним блоком: сначала доверие (05 §2).
"""

from __future__ import annotations

import re
from typing import Any

BLOCKS: list[tuple[str, str]] = [
    ("core", "Ядро"),
    ("study", "Учёба"),
    ("direction", "Направление"),
    ("day", "Распорядок дня"),
    ("body", "Тело и энергия"),
    ("habits", "Привычки"),
    ("work_style", "Как ты работаешь"),
    ("money", "Деньги"),
    ("people", "Люди"),
    ("inner", "Слабости и страхи"),
]

QUESTIONS: list[dict[str, str]] = [
    # Ядро — без него система не запустится (стадия 1)
    {"id": "name", "block": "core", "text": "Как к тебе обращаться?"},
    {"id": "address", "block": "core", "text": "В каком роде к тебе обращаться: «ты сделал» или «ты сделала»?"},
    {"id": "city", "block": "core", "text": "Город и часовой пояс? Сейчас в настройках Europe/Moscow."},
    {"id": "sleep", "block": "core", "text": "Во сколько ложишься и встаёшь — реально, не в идеале? И во сколько хочешь? Формат: 01:30–09:00, цель 23:30–07:30."},
    {"id": "week", "block": "core", "text": "Расписание недели: какие дни и часы заняты учёбой, работой, сменами? По дням."},
    {"id": "main_goal", "block": "core", "text": "Одна главная цель на ближайший год. Измеримо: что именно и к какой дате."},
    {"id": "main_goal_why", "block": "core", "text": "Зачем тебе эта цель? Что изменится, когда она будет достигнута?"},
    # Учёба — от неё зависят роадмапы и бюджет часов
    {"id": "study_subjects", "block": "study", "text": "Какие предметы для тебя главные — нужны для экзаменов и поступления? Какие даются легко, а какие тяжело?"},
    {"id": "study_level", "block": "study", "text": "Где ты сейчас по главным предметам: оценки, баллы пробников, что конкретно не получается?"},
    {"id": "study_exams", "block": "study", "text": "Какие экзамены впереди (ОГЭ/ЕГЭ — какие предметы, олимпиады, сессия)? Даты и сколько баллов нужно."},
    {"id": "study_after", "block": "study", "text": "Что после текущей ступени: старшая школа, колледж, вуз? Куда хочешь поступить — заведение, направление, страна?"},
    {"id": "study_tools", "block": "study", "text": "Чем пользуешься для учёбы: Obsidian, Anki, YouTube, онлайн-школы, репетиторы, учебники, нейросети? Что реально помогает, а что для галочки?"},
    {"id": "study_method", "block": "study", "text": "Как проходит твоё учебное занятие от начала до конца? Как проверяешь, что понял, а не просто прочитал?"},
    {"id": "study_stuck", "block": "study", "text": "Где застреваешь чаще всего: не понимаю материал, не могу сесть, забываю через неделю, нет плана, не знаю, что учить?"},
    {"id": "study_hours", "block": "study", "text": "Сколько часов в неделю ты реально готов учиться сверх школы? А сколько сможешь, не выгорая?"},
    # Направление
    {"id": "dream", "block": "direction", "text": "Мечты — не цели, а крупно. Какой должна быть жизнь через 5–10 лет?"},
    {"id": "want", "block": "direction", "text": "Чем ты реально хочешь заниматься? Не «надо», а «хочу»."},
    {"id": "institution", "block": "direction", "text": "Где учишься или работаешь, какая нагрузка, что даётся тяжелее всего?"},
    {"id": "projects", "block": "direction", "text": "Какие проекты ведёшь сейчас? Какой из них самый важный и почему?"},
    {"id": "success_3m", "block": "direction", "text": "Как через 3 месяца понять, что Арвикс работает? Одна-две измеримые вещи."},
    {"id": "career", "block": "direction", "text": "Какие профессии и направления рассматриваешь? Что о них уже знаешь — чем там занимаются, какие требования, какой путь?"},
    # Распорядок дня — из него строятся шаблоны дней (без них нет задач и напоминаний)
    {"id": "day_weekday", "block": "day", "text": "Опиши обычный учебный день по часам: подъём, дорога, учёба, еда, свободное время, отбой."},
    {"id": "day_weekend", "block": "day", "text": "А выходной? Во сколько встаёшь, что обычно делаешь, что меняется?"},
    {"id": "day_fixed", "block": "day", "text": "Что в неделе нельзя двигать: тренировки, работа, кружки, репетиторы, семья? Дни и часы."},
    {"id": "day_free", "block": "day", "text": "Какие окна свободного времени реально есть по дням недели — куда можно ставить учёбу?"},
    {"id": "day_rest", "block": "day", "text": "Как ты отдыхаешь так, чтобы реально восстановиться? Сколько отдыха в день тебе нужно?"},
    {"id": "day_overload", "block": "day", "text": "По каким признакам понятно, что ты перегрузился или выгораешь? Что тогда помогает?"},
    # Тело и энергия
    {"id": "sport", "block": "body", "text": "Спорт: чем занимаешься, как часто, есть ли спортивная цель?"},
    {"id": "body", "block": "body", "text": "Рост и вес — если не против, для спортивных планов. Можно пропустить."},
    {"id": "energy", "block": "body", "text": "Когда в течение дня у тебя пик энергии, а когда провал?"},
    {"id": "food", "block": "body", "text": "Как с едой: регулярно ли ешь, что мешает?"},
    # Привычки
    {"id": "good_habits", "block": "habits", "text": "Какие хорошие привычки уже держатся? Что делаешь стабильно?"},
    {"id": "bad_habits", "block": "habits", "text": "Вредные привычки: что именно и сколько времени в день это съедает?"},
    {"id": "triggers", "block": "habits", "text": "Что запускает срыв? Время, место, состояние, человек — конкретно."},
    {"id": "screen", "block": "habits", "text": "Сколько часов в день телефон, игры и сериалы по учёту экрана? Честную цифру."},
    {"id": "tried", "block": "habits", "text": "Что уже пробовал для дисциплины? Что работало и почему бросил?"},
    # Как ты работаешь
    {"id": "focus", "block": "work_style", "text": "Сколько минут можешь работать без отвлечений? Где лучше всего работается?"},
    {"id": "procrastination", "block": "work_style", "text": "В какой момент конкретно ты открываешь телефон вместо задачи?"},
    {"id": "motivation", "block": "work_style", "text": "Что на тебя действует: жёсткость, цифры, соревнование, признание сделанного?"},
    {"id": "pressure_line", "block": "work_style", "text": "Где граница: какая жёсткость тебя мотивирует, а какая ломает?"},
    {"id": "learning_style", "block": "work_style", "text": "Как ты учишься лучше всего: видео, книги, практика, объяснение другим?"},
    # Деньги
    {"id": "income", "block": "money", "text": "Есть ли доход? Примерно сколько в месяц — одной цифрой, по желанию."},
    {"id": "spending", "block": "money", "text": "На что уходят деньги? Где бывают импульсивные траты?"},
    {"id": "money_goal", "block": "money", "text": "Есть ли цель накопления? Сумма и срок."},
    # Люди
    {"id": "people", "block": "people", "text": "Кто для тебя важен? С кем регулярный контакт?"},
    {"id": "social_energy", "block": "people", "text": "Общение тебя заряжает или выматывает? Сколько живых встреч в неделю — норма?"},
    {"id": "support", "block": "people", "text": "Кому можно написать, если станет по-настоящему плохо? Имя или роль — на случай safety-контура."},
    # Слабости и страхи — последним
    {"id": "weaknesses", "block": "inner", "text": "Где ты регулярно проигрываешь сам себе?"},
    {"id": "self_lies", "block": "inner", "text": "О чём ты чаще всего врёшь себе — в отчётах, планах, оценках?"},
    {"id": "fears", "block": "inner", "text": "Чего ты боишься — в учёбе, работе, жизни?"},
    {"id": "after_failure", "block": "inner", "text": "Что ты делаешь после провала: бросаешь, наказываешь себя, делаешь вид, что ничего не было?"},
    {"id": "mentor_role", "block": "inner", "text": "Каким должен быть идеальный ментор для тебя? И чего он не должен делать никогда?"},
]

BY_ID = {q["id"]: q for q in QUESTIONS}
BLOCK_TITLES = dict(BLOCKS)

# Город → часовой пояс. Неизвестный город просто сохраняется текстом.
CITY_TZ = {
    "москв": "Europe/Moscow", "петербург": "Europe/Moscow", "спб": "Europe/Moscow", "казан": "Europe/Moscow",
    "нижн": "Europe/Moscow", "краснодар": "Europe/Moscow", "ростов": "Europe/Moscow", "воронеж": "Europe/Moscow",
    "самар": "Europe/Samara", "екатеринбург": "Asia/Yekaterinburg", "челябинск": "Asia/Yekaterinburg",
    "уфа": "Asia/Yekaterinburg", "пермь": "Asia/Yekaterinburg", "тюмен": "Asia/Yekaterinburg",
    "омск": "Asia/Omsk", "новосибирск": "Asia/Novosibirsk", "томск": "Asia/Tomsk", "красноярск": "Asia/Krasnoyarsk",
    "иркутск": "Asia/Irkutsk", "владивосток": "Asia/Vladivostok", "хабаровск": "Asia/Vladivostok",
    "калининград": "Europe/Kaliningrad", "алмат": "Asia/Almaty", "астан": "Asia/Almaty", "шымкент": "Asia/Almaty",
    "караганд": "Asia/Almaty", "бишкек": "Asia/Bishkek", "ош": "Asia/Bishkek", "ташкент": "Asia/Tashkent",
    "душанбе": "Asia/Dushanbe", "минск": "Europe/Minsk", "киев": "Europe/Kyiv", "тбилиси": "Asia/Tbilisi",
    "ереван": "Asia/Yerevan", "баку": "Asia/Baku",
}

TIME_RE = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b")
TZ_RE = re.compile(r"\b([A-Z][a-z]+/[A-Z][A-Za-z_]+)\b")


def next_question(answered: set[str], skipped: set[str], block: str | None = None) -> dict[str, str] | None:
    pool = [q for q in QUESTIONS if q["id"] not in answered and q["id"] not in skipped]
    if block:
        pool = [q for q in pool if q["block"] == block]
    return pool[0] if pool else None


def progress(answered: set[str], skipped: set[str]) -> dict[str, Any]:
    blocks = []
    for key, title in BLOCKS:
        ids = [q["id"] for q in QUESTIONS if q["block"] == key]
        done = sum(1 for i in ids if i in answered or i in skipped)
        blocks.append({"block": key, "title": title, "done": done, "total": len(ids)})
    return {"answered": len(answered), "total": len(QUESTIONS), "blocks": blocks}


def extract(qid: str, answer: str) -> dict[str, Any]:
    """Детерминированный разбор ответа в поля профиля. Всё, что не распознано, —
    остаётся сырым ответом, его разложит модель (или ты сам в Claude Code)."""
    text = answer.strip()
    low = text.lower()
    out: dict[str, Any] = {}
    if qid == "name":
        out["name"] = text.split("\n")[0].strip(" .!,")[:60]
    elif qid == "address":
        if re.search(r"сделала|женск|\bж\b|\bона\b", low):
            out["address"] = "f"
        elif re.search(r"сделал|мужск|\bм\b|\bон\b", low):
            out["address"] = "m"
    elif qid == "city":
        out["city"] = text.split(",")[0].strip()[:80]
        if match := TZ_RE.search(text):
            out["timezone"] = match.group(1)
        else:
            for stem, tz in CITY_TZ.items():
                if re.search(rf"\b{stem}", low):
                    out["timezone"] = tz
                    break
    elif qid == "sleep":
        times = [f"{int(h):02d}:{m}" for h, m in TIME_RE.findall(text)]
        if len(times) >= 4:
            out.update(bedtime_actual=times[0], wake_actual=times[1], bedtime_target=times[2], wake_target=times[3])
        elif len(times) >= 2:
            out.update(bedtime_target=times[0], wake_target=times[1])
    elif qid == "main_goal":
        out["main_goal"] = text[:300]
    elif qid == "main_goal_why":
        out["main_goal_why"] = text[:500]
    elif qid == "support":
        out["support_person"] = text[:120]
    elif qid == "study_hours":
        hours = [float(h.replace(",", ".")) for h in re.findall(r"\d+(?:[.,]\d)?", text)]
        if hours:
            # Стартовый бюджет — нижняя из названных цифр: начинать с того, что точно потянешь.
            out["week_budget_min"] = int(min(hours) * 60)
    return out
