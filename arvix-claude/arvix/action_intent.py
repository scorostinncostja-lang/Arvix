"""Permissions for actions proposed by the conversational head."""
from __future__ import annotations

import re

# Direct commands are recognized from the current user turn. Previous replies,
# quotes and the model's own assessment do not authorize a change.
COMMANDS = {
    "add_task": r"(?:добавь|поставь|создай|запланируй)(?!\s+(?:таймер|фокус|заметку|цель|шаги|напоминание)\b)|внеси\s+в\s+план",
    "defer_task": r"перенеси|сдвинь|передвинь|отложи",
    "cancel_task": r"отмени|убери\s+из\s+плана",
    "start_task": r"(?:начни|запусти|старт)(?!\s+(?:фокус|таймер)\b)",
    "start_focus": r"засеки|запусти\s+(?:фокус|таймер)|включи\s+таймер|поставь\s+таймер|старт\s+фокус|фокус\s+\d",
    "stop_focus": r"останови|выключи\s+таймер|стоп\s+(?:таймер|фокус)|закрой\s+фокус",
    "complete_task": r"отметь|закрой\s+(?:задачу|блок|дело)|зачти",
    "fail_task": r"отметь\s+несделанн\w*|зафиксируй\s+(?:провал|срыв)|не\s+сделал[аи]?|провалил[аи]?",
    "task_guide": r"распиши|составь\s+шаги|добавь\s+шаги|как\s+(?:[а-я]+\s+){0,2}сделать",
    "write_note": r"запиши|сохрани|допиши|добавь\s+в\s+(?:заметку|obsidian)|создай\s+заметку",
    "note": r"запиши|сохрани|создай\s+заметку",
    "set_goal": r"поставь\s+цель|измени\s+цель|создай\s+цель|обнови\s+цель",
    "set_template": r"сохрани\s+(?:распорядок|шаблон)|запиши\s+(?:распорядок|шаблон)",
    "profile_set": r"запомни|обнови\s+профиль|измени\s+в\s+профиле|меня\s+зовут|называй\s+меня",
    "add_trait": r"запомни|запиши\s+как\s+(?:привычку|черту)",
    "rest_day": r"включи\s+(?:отдых|восстановление|режим восстановления)|хочу\s+отдых|дай\s+день\s+отдыха",
    "silent_day": r"включи\s+тихий\s+день|сегодня\s+веду\s+день\s+сам|сегодня\s+не\s+пиши",
}
READ_ONLY = frozenset({"safety_flag", "show_day", "show_week", "show_status", "show_schedule", "show_goals"})
QUOTES = re.compile(r'«[^»]*»|“[^”]*”|"[^"]*"|\x60[^\x60]*\x60')
NO_WRITE = re.compile(
    r"\b(?:ничего\s+не\s+(?:меняй|записывай|сохраняй|делай)|"
    r"не\s+(?:меняй|трогай)\s+(?:ничего|план|задачи)|"
    r"без\s+(?:изменений|записей)|без\s+действий)\b"
)
ADVISE = re.compile(
    r"\b(?:(?:только|просто)\s+(?:помоги|ответь|посоветуй|скажи|объясни|задай|выслушай|поговори|побудь|поддержи)|"
    r"(?:нужен|хочу)\s+только\s+совет)\b"
)
NO_FOCUS = re.compile(r"\b(?:не\s+(?:надо\s+)?(?:запускай|включай|засекай)|без\s+таймера)\b")
NO_DEFER = re.compile(r"\b(?:не\s+(?:(?:надо|хочу|буду)\s+)?(?:переносить|переноси|сдвигай)|"
                      r"(?:переносить|сдвигать)\b[^.!?\n]{0,24}\bне\s+(?:хочу|буду|надо)|без\s+переноса)\b")
NO_RECORD = re.compile(r"\bне\s+(?:записывай|сохраняй|запоминай)\b")
RECORD_ACTIONS = frozenset({"write_note", "note", "remember", "profile_set", "add_trait", "declare_reason",
                            "log_sleep", "log_expense", "log_social", "learning_question"})
POLITE = r"(?:(?:да|ок|хорошо|ну|пожалуйста|арвикс)\s*[,!]?\s*)*"
COMMAND = {kind: re.compile(rf"^{POLITE}(?:{words})\b") for kind, words in COMMANDS.items()}
STUDY_NOW = re.compile(rf"^{POLITE}давай\s+(?:позанимаемся|начн[её]м\s+заниматься)\b")
REPORT = re.compile(r"\b(?:сделал[аи]?|выполнил[аи]?|закончил[аи]?|решил[аи]?)\b")
NEG_REPORT = re.compile(r"\b(?:решил[аи]?\s*,?\s*что|не\s+(?:сделал[аи]?|выполнил[аи]?|закончил[аи]?|решил[аи]?)|"
                        r"когда|если|представь|допустим|вроде|кажется)\b")


def normalized(text: str) -> str:
    return QUOTES.sub(" … ", text.casefold())


def asks_for_conversation(text: str) -> bool:
    request = normalized(text)
    return bool(NO_WRITE.search(request) or ADVISE.search(request))


def allowed_actions(text: str, action_types: tuple[str, ...]) -> frozenset[str]:
    request = normalized(text)
    if NO_WRITE.search(request):
        return READ_ONLY
    parts = [part.strip() for part in re.split(r"[.!?;\n]+|,\s+а\s+", request)]
    permitted = set(action_types) - COMMAND.keys()
    if not ADVISE.search(request):
        permitted.update(kind for kind, prefix in COMMAND.items() if any(prefix.match(part) for part in parts))
        if any(STUDY_NOW.match(part) for part in parts):
            permitted.update(("add_task", "task_guide", "start_focus"))
        if any(REPORT.search(part) and not NEG_REPORT.search(part) for part in parts):
            permitted.add("complete_task")
    else:
        permitted.difference_update(("remember", "declare_reason", "plan_schedule", "debrief_now"))
    if NO_FOCUS.search(request):
        permitted.discard("start_focus")
    if NO_DEFER.search(request):
        permitted.discard("defer_task")
    if NO_RECORD.search(request):
        permitted.difference_update(RECORD_ACTIONS)
    return frozenset(permitted)
