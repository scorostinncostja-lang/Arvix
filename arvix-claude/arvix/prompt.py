"""Сборка промпта из слоёв (04-AI-LAYER §1): конституция → few-shot → тон → контекст.

Сначала статичное, потом динамичное — иначе не работает кэш провайдера.
Тон-блок выбирает Burnout Guard, а не модель. В 🟥 и при выключенном менторе
жёсткие тон-блоки, жёсткие примеры и правило «отказ с цифрой» физически не
попадают в текст (правило №5 CLAUDE.md, проверяется tests/test_prompt_safety.py).
"""

from __future__ import annotations

import json
from functools import cache
from typing import Any

from arvix.config import PACKAGE_DIR
from arvix.context import build_context

CONSTITUTION_DIR = PACKAGE_DIR / "constitution"
SECTIONS = ("identity", "mission", "voice", "autonomy_rule", "decision_rule", "honesty", "boundaries", "safety_override")
# Разделы, которые выпадают в мягком режиме: отказ «с цифрой» в 🟥 неуместен.
GENTLE_SKIP = frozenset({"decision_rule"})
TONE_FILES = {"normal": "tone_norm", "pressure": "tone_pressure", "yellow": "tone_yellow", "red": "tone_red"}
HARSH_TONES = ("tone_norm", "tone_pressure", "tone_yellow")
EMERGENCY = "112"


@cache
def read_block(name: str) -> str:
    return (CONSTITUTION_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


@cache
def _examples() -> list[dict[str, Any]]:
    return json.loads((CONSTITUTION_DIR / "fewshot.json").read_text(encoding="utf-8"))


def is_gentle(mode: str, mentor_enabled: bool) -> bool:
    return mode == "red" or not mentor_enabled


def address_block(profile: dict[str, Any]) -> str:
    name = profile.get("name") or "пока неизвестно"
    form = {"m": "мужской род («ты сделал»)", "f": "женский род («ты сделала»)"}.get(profile.get("address", ""))
    form_line = f"Грамматический род: {form}." if form else "Род неизвестен: избегай глаголов прошедшего времени с родом, пока не узнаешь."
    return f"<address>\nОбращайся на «ты». Имя: {name}.\n{form_line}\n</address>"


def constitution(profile: dict[str, Any], *, gentle: bool, sections: tuple[str, ...] = SECTIONS) -> str:
    support = profile.get("support_person")
    parts = []
    for section in sections:
        if gentle and section in GENTLE_SKIP:
            continue
        text = read_block(section)
        text = text.replace("{support}", f" (например: {support})" if support else "").replace("{emergency}", EMERGENCY)
        parts.append(text)
    return "\n\n".join(parts)


def tone_block(mode: str, mentor_enabled: bool) -> str:
    return read_block(TONE_FILES["red" if is_gentle(mode, mentor_enabled) else mode])


def fewshot(*, gentle: bool, only: str = "all") -> str:
    """only: all | soft | harsh. В мягком режиме жёсткие примеры не выдаются никогда."""
    picked = []
    for example in _examples():
        if example["harsh"] and (gentle or only == "soft"):
            continue
        if not example["harsh"] and only == "harsh":
            continue
        picked.append(example)
    if not picked:
        return ""
    body = "\n\n".join(
        f"# {e['situation']}\nКОНТЕКСТ: {e['context']}\nЧЕЛОВЕК: {e['user']}\nАРВИКС: {e['arvix']}" for e in picked
    )
    return f"<examples>\nТак звучит Арвикс. Подражай голосу, а не словам.\n\n{body}\n</examples>"


def system_prompt(core: Any, *, channel: str = "telegram", message: str = "", history: list[str] | None = None, extra: str = "") -> str:
    """Промпт L1 для Telegram-головы (один вызов claude -p на сообщение)."""
    st = core.state
    gentle = is_gentle(st.mode, st.mentor_enabled)
    parts = [
        constitution(st.profile, gentle=gentle),
        fewshot(gentle=gentle),
        read_block(f"channel_{channel}"),
        address_block(st.profile),
        tone_block(st.mode, st.mentor_enabled),
        "<context>\n" + build_context(core, message=message, gentle=gentle) + "\n</context>",
    ]
    if history:
        parts.append("<history>\n" + "\n".join(history) + "\n</history>")
    if extra:
        parts.append(extra)
    return "\n\n".join(p for p in parts if p)


def hook_context(core: Any) -> str:
    """Динамическая часть для Claude Code (SessionStart-хук): тон по режиму,
    правило решений и жёсткие примеры — только вне мягкого режима."""
    st = core.state
    gentle = is_gentle(st.mode, st.mentor_enabled)
    parts = [
        "Состояние Арвикса на начало сессии. Тон-блок выбран Burnout Guard — следуй ему.",
        address_block(st.profile),
        tone_block(st.mode, st.mentor_enabled),
    ]
    if not gentle:
        parts += [constitution(st.profile, gentle=False, sections=("decision_rule",)), fewshot(gentle=False, only="harsh")]
    parts.append("<context>\n" + build_context(core, gentle=gentle) + "\n</context>")
    return "\n\n".join(p for p in parts if p)


STYLE_TOOLS = """<tools_rule>
Ты работаешь через MCP-инструменты сервера arvix. Числа (XP, HP, долг, режим) считает код —
ты их только читаешь из инструментов и никогда не вычисляешь и не выдумываешь сам.
В начале разговора и после любых изменений смотри состояние инструментом context.
Отчёт о задаче → task (complete/fail), сон → log, факт о человеке → profile (remember),
просьба изменить план → сначала check_request, потом решение на цифрах.
Obsidian: работаешь в структуре хранилища (notes action=overview — карта, action=paths — места для целей,
роадмапов, конспектов). Свои новые заметки создаёшь, чужие только дополняешь (append или свой блок);
перезапись чужой заметки — только по явному «да, перезапиши» (force). Удалять нельзя.
Признаки настоящей беды → mode с action safety_flag и человеческий ответ без задач.
Включить ментора обратно может только сам человек командой — ты этого не делаешь.
</tools_rule>"""


def render_output_style() -> str:
    """output-styles/arvix.md собирается из тех же файлов конституции, что и
    промпт Telegram, — один источник правды. Тон-блоков и жёстких примеров здесь
    нет: их подставляет хук по текущему режиму."""
    sections = tuple(s for s in SECTIONS if s not in GENTLE_SKIP)
    body = "\n\n".join([constitution({}, gentle=True, sections=sections), STYLE_TOOLS, fewshot(gentle=True)])
    header = (
        "---\n"
        "name: Arvix\n"
        "description: Арвикс — личный ментор. План, отчёты, разбор, сократовский режим. Голос, а не ассистент.\n"
        "keep-coding-instructions: false\n"
        "---\n\n"
        "<!-- Файл генерируется: python3 scripts/build_assets.py. Правь arvix/constitution/*. -->\n\n"
    )
    return header + body + "\n"


def render_claude_ai_instructions() -> str:
    """Инструкции для проекта на claude.ai — без доступа к базе и хранилищу."""
    sections = tuple(s for s in SECTIONS if s not in GENTLE_SKIP)
    note = (
        "<stateless>\nЗдесь у тебя нет доступа к журналу событий, XP/HP и Obsidian: они живут на ноутбуке.\n"
        "Не выдумывай цифры состояния. Если человек хочет отметить задачу, сон или трату — "
        "скажи сделать это в Telegram-боте или в Claude Code.\nМетодика, голос и сократовский режим — те же.\n</stateless>"
    )
    return "\n\n".join([constitution({}, gentle=True, sections=sections), read_block("tone_norm"), note, fewshot(gentle=False)]) + "\n"
