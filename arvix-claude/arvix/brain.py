"""Голова Arvix для Telegram: один вызов `claude -p` на сообщение (L1) и фоновые
вызовы аналитика (L2). Работает по подписке Claude, без API-ключа.

Вызов урезан до минимума: свой системный промпт, без MCP-серверов, скиллов и
пользовательских настроек — ~1.5k токенов служебного текста вместо ~43k.
Модель возвращает JSON {reply, actions}; actions исполняет код (apply_actions),
модель в журнал напрямую не пишет (04-AI-LAYER §5).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from arvix.config import Config, data_dir
from arvix.core import ArvixError, Core

HEAD_SKILLS = Path(__file__).resolve().parent.parent / "head-skills"  # библиотека навыков головы (D33)

log = logging.getLogger("arvix.brain")

ACTION_TYPES = (
    "add_task", "complete_task", "fail_task", "defer_task", "cancel_task", "start_task",
    "log_sleep", "log_expense", "log_social", "remember", "note", "profile_set",
    "set_goal", "add_trait", "declare_reason", "learning_question", "safety_flag", "set_template",
    # Проекты (D43): карточка, этап с критерием, блок в план, журнал, деньги, канал привлечения.
    "set_project", "set_milestone", "plan_project", "project_log", "project_money", "project_channel",
) + (
    # Действия интерфейса: их исполняет бот после ответа, а не ядро (05-INTERFACES §2.1).
    # Так человек говорит словами, а не командами: «давай позанимаемся физикой» → урок.
    "plan_schedule", "show_schedule", "start_lesson", "start_focus", "stop_focus", "show_day", "show_status",
    "show_week", "show_goals", "debrief_now", "rest_day", "silent_day", "open_app", "install_app", "offer_return",
)
UI_ACTIONS = frozenset(ACTION_TYPES[ACTION_TYPES.index("plan_schedule"):])
ACTION_RU = {
    "add_task": "задача", "complete_task": "отчёт", "fail_task": "провал", "defer_task": "перенос", "cancel_task": "отмена",
    "start_task": "старт", "log_sleep": "сон", "log_expense": "трата", "log_social": "социум", "remember": "память",
    "note": "заметка", "profile_set": "профиль", "set_goal": "цель", "add_trait": "черта", "declare_reason": "причина дня",
    "learning_question": "учебный вопрос", "safety_flag": "safety", "set_template": "распорядок",
    "set_project": "проект", "set_milestone": "этап проекта", "plan_project": "блок проекта", "project_log": "журнал проекта",
    "project_money": "деньги проекта", "project_channel": "канал привлечения",
}

_ACTION_FIELDS = {
    "type": {"type": "string", "enum": list(ACTION_TYPES)},
    "task": {"type": "string", "description": "id задачи из контекста"},
    "title": {"type": "string"}, "sphere": {"type": "string"}, "importance": {"type": "integer"},
    "difficulty": {"type": "integer"}, "start": {"type": "string", "description": "время начала ЧЧ:ММ — для add_task обязательно"},
    "duration_min": {"type": "integer"}, "deep_work": {"type": "boolean"}, "date": {"type": "string"},
    "done_pct": {"type": "integer"}, "report": {"type": "string", "description": "для complete_task: что именно сделано, словами человека"},
    "reason": {"type": "string"},
    "minutes": {"type": "integer"}, "duration": {"type": "string", "description": "сон, например 7:30"},
    "bedtime": {"type": "string", "description": "отбой ЧЧ:ММ"},
    "wake": {"type": "string", "description": "для log_sleep: подъём ЧЧ:ММ — с bedtime длительность посчитает код"}, "amount": {"type": "number"}, "category": {"type": "string"},
    "impulse": {"type": "boolean"}, "who": {"type": "string"}, "topic": {"type": "string"},
    "fact": {"type": "string"}, "key": {"type": "string"}, "value": {"type": "string"},
    "text": {"type": "string"}, "kind": {"type": "string"}, "why": {"type": "string"},
    "deadline": {"type": "string"}, "level": {"type": "string"}, "question": {"type": "string"},
    "direct": {"type": "boolean"},
    "wishes": {"type": "string", "description": "для plan_schedule: распорядок и пожелания словами человека, полностью"},
    "goal_id": {"type": "string", "description": "для set_goal: id существующей цели — исправить её (kind, deadline, metric, status=dropped)"},
    "parent_id": {"type": "string", "description": "для set_goal: id цели, этапом которой становится эта"},
    "metric": {"type": "string", "description": "для set_goal: как проверить достижение — число, оценка, результат"},
    "status": {"type": "string", "enum": ["active", "done", "dropped", "idea", "paused", "open", "test", "works"],
               "description": "цель: active/done/dropped; проект: idea/active/paused/done/dropped (done и dropped — с итогом в reason); "
                              "этап: open/done/dropped; канал: test/works/dropped"},
    "weekdays": {"type": "array", "items": {"type": "integer"}, "description": "для set_template: 0=пн … 6=вс"},
    "day_type": {"type": "string", "enum": ["study", "work", "deep", "recovery", "silent"]},
    "project": {"type": "string", "description": "id проекта из блока ПРОЕКТЫ: для add_task — блок работает на проект; для set_project — правка"},
    "milestone": {"type": "string", "description": "для set_milestone: id этапа — отметить (status=done/dropped) или исправить"},
    "dod": {"type": "string", "description": "для set_milestone: критерий готовности этапа — как проверить, что он сделан"},
    "expectation": {"type": "string", "description": "для set_project: что должно быть в конце, проверяемо"},
    "weekly_min": {"type": "integer", "description": "для set_project: минут в неделю на проект"},
    "skills": {"type": "array", "items": {"type": "string"}, "description": "для set_project: навыки, которые даёт проект"},
    "direction": {"type": "string", "enum": ["in", "out"], "description": "для project_money: in — доход, out — расход"},
    "hypothesis": {"type": "string", "description": "для project_channel: что ждём от канала, с числом и сроком"},
    "cost": {"type": "number"}, "leads": {"type": "integer"}, "clients": {"type": "integer"}, "revenue": {"type": "number"},
    "channel": {"type": "string", "description": "для project_channel: id канала — обновить итоги"},
    "link": {"type": "string"},
    "blocks": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "start": {"type": "string"}, "duration": {"type": "integer"}, "title": {"type": "string"},
                "sphere": {"type": "string"}, "importance": {"type": "integer"}, "difficulty": {"type": "integer"},
                "deep_work": {"type": "boolean"}, "tags": {"type": "array", "items": {"type": "string"}},
                "fixed": {"type": "boolean"},
            },
            "required": ["start", "title"],
        },
    },
}

VOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "actions": {"type": "array", "items": {"type": "object", "properties": _ACTION_FIELDS, "required": ["type"]}},
        "learning": {"type": "boolean"},
    },
    "required": ["reply", "actions"],
}

DEBRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "assessment": {"type": "string", "description": "одна честная оценка дня, 1–2 предложения"},
        "questions": {"type": "array", "items": {"type": "string"}, "description": "ровно два вопроса под этот день"},
    },
    "required": ["assessment", "questions"],
}

RETRO_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string", "description": "ретро для человека голосом Арвикса, до 900 символов"},
        "directives": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["focus", "warning", "schedule_change", "insight", "quota_push"]},
                    "text": {"type": "string"}, "voice_hint": {"type": "string"},
                    "priority": {"type": "integer"}, "valid_days": {"type": "integer"},
                    "evidence": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["kind", "text", "evidence"],
            },
        },
        "insights": {
            "type": "array",
            "items": {"type": "object", "properties": {"text": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "integer"}}}, "required": ["text", "evidence"]},
        },
    },
    "required": ["message", "directives"],
}

TEMPLATES_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "логика распорядка в 2–4 строках"},
        "templates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "weekdays": {"type": "array", "items": {"type": "integer"}, "description": "0=пн … 6=вс"},
                    "day_type": {"type": "string", "enum": ["study", "work", "deep", "recovery", "silent"]},
                    "blocks": _ACTION_FIELDS["blocks"],
                },
                "required": ["weekdays", "day_type", "blocks"],
            },
        },
    },
    "required": ["summary", "templates"],
}

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "что записано, одной-двумя строками"},
        "actions": VOICE_SCHEMA["properties"]["actions"],
    },
    "required": ["summary", "actions"],
}

EFFORTS = ("low", "medium", "high", "xhigh", "max")
# Сообщения, где нужно подумать: план, выбор, «почему», учёба, разбор — им усилие выше. Остальное
# (отчёт, сон, «ок», «давай», болтовня) — низкое: ответ быстрее в разы, а думать там не о чем (D40).
DEEP_ASK = re.compile(
    r"план|распоряд|расписан|недел|почему|зачем|объясни|как лучше|что делать|посоветуй|советуешь|совет|цел[ьиея]|роадмап|"
    r"разбер|проверь|стратег|выбрать|сравни|правильно ли|не понимаю|научи|как мне|помоги",
    re.IGNORECASE,
)


def effort_for(text: str) -> str:
    """Усилие головы по сообщению — код, а не модель: длинное или «думательное» — medium, остальное — low."""
    return "medium" if len(text) > 280 or DEEP_ASK.search(text or "") else "low"


def mode_shift(result: dict[str, Any]) -> str:
    """«· режим 🟥 → 🟨» к записи сна, если сон сменил режим: человек видит, что сон сработал."""
    from arvix.rules import MODE_LABELS

    before, after = result.get("mode_before"), result.get("mode")
    if not before or before == after:
        return ""
    return f" · режим {MODE_LABELS[before].split()[0]} → {MODE_LABELS[after]}"


# Валидаторы ответа (04-AI-LAYER) — дешёвые проверки кодом, без модели.
GENTLE_STOP = ("дисциплин", "продуктивн", "провал", "слил", "штраф", "лень", "саботаж", " xp", " hp", "выполнени", "долг")
LINK_RE = re.compile(r"https?://\S+")
# Обучающий ответ обязан назвать первоисточник. Требовать именно URL нельзя: валидатор,
# который принимает только ссылку, учит модель выдумывать адреса. Учебник с параграфом,
# документация или спецификация по названию — тоже источник.
SOURCE_RE = re.compile(
    r"https?://\S+|первоисточник|источник|учебник|параграф|§\s*\d|глава\s*\d|документац|спецификац|справочник",
    re.IGNORECASE,
)


GENTLE_RE = re.compile(r"(?<![а-яёa-z])(?:" + "|".join(re.escape(w.strip()) for w in GENTLE_STOP) + ")", re.IGNORECASE)


def gentle_violation(text: str) -> bool:
    """Слова давления — с начала слова: «лень» да, «маленькая вещь» (совет самого 🟥) — нет."""
    return bool(GENTLE_RE.search(text or ""))


def has_source(text: str) -> bool:
    return bool(SOURCE_RE.search(text or ""))


def clip(text: str, limit: int = 700) -> str:
    """Сжатие длинного проактивного сообщения по границе предложения."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("\n"), cut.rfind("! "), cut.rfind("? "))
    return (cut[: end + 1] if end > limit // 2 else cut.rstrip() + "…").strip()


class Brain:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        section = cfg.section("brain")
        self.bin = section.get("claude_bin") or "claude"
        self.timeout = int(section.get("timeout_sec") or 180)
        self.vault_tools = bool(section.get("vault_tools", True))
        self.web_tools = bool(section.get("web_tools", True))
        # Навыки головы (D33): своя проверенная библиотека + папки плагинов, которые владелец указал сам.
        self.skills_enabled = bool(section.get("skills", True))
        self.skill_dirs = [str(Path(p).expanduser()) for p in (section.get("skill_dirs") or []) if p]
        # Усилие (D40): "auto" — по сообщению (effort_for), уровень — для всех, "" — как решит CLI.
        self.effort = str(section.get("effort", "auto") or "").strip().lower()
        self.last_error = ""
        self.last_stats: dict[str, Any] = {}
        self._flags: str | None = None

    def supports(self, flag: str) -> bool:
        """Старый claude не знает нового флага и падает на нём — а голова молчала бы на каждом
        сообщении. Справку читаем один раз за жизнь процесса."""
        if self._flags is None:
            try:
                out = subprocess.run([self.bin, "--help"], capture_output=True, text=True, timeout=20, check=False)
                self._flags = out.stdout + out.stderr
            except (OSError, subprocess.TimeoutExpired):
                self._flags = ""
        return flag in self._flags

    def effort_level(self, effort: str | None) -> str | None:
        """effort — уровень, который код подобрал под сообщение (effort_for). Конфиг сильнее:
        «auto» — берём подобранный, конкретный уровень — всегда он, пусто — флаг не передаём."""
        level = self.effort if self.effort != "auto" else (effort or "").strip().lower()
        if level not in EFFORTS or not self.supports("--effort"):
            return None
        return level

    def available(self) -> bool:
        return shutil.which(self.bin) is not None or os.path.isfile(self.bin)

    def skill_plugins(self, skills: str) -> list[str]:
        """Папки-плагины с навыками: «gentle» — только безопасные в 🟥 (разговор, тревога);
        «full» — вся библиотека и папки владельца из [brain] skill_dirs; «off» — без навыков."""
        if skills == "off" or not self.skills_enabled:
            return []
        dirs = [str(HEAD_SKILLS / "gentle")]
        if skills == "full":
            dirs += [str(HEAD_SKILLS / "full")] + [d for d in self.skill_dirs if Path(d).is_dir()]
        return dirs

    def command(self, *, system: str, prompt: str, schema: dict[str, Any], role: str, vault_tools: bool, web: bool = False,
                skills: str = "off", effort: str | None = None) -> list[str]:
        plugins = self.skill_plugins(skills)
        cmd = [
            self.bin, "-p", prompt,
            "--system-prompt", system,
            "--output-format", "json",
            "--json-schema", json.dumps(schema, ensure_ascii=False),
            "--setting-sources", "",
            "--strict-mcp-config",
            "--no-session-persistence",
            "--permission-mode", "dontAsk",
            "--permission-prompts", "none",
        ]
        if not plugins:
            cmd.append("--disable-slash-commands")  # навыки — тоже слеш-команды: без библиотеки выключено всё
        if model := self.cfg.model(role):
            cmd += ["--model", model]
        if level := self.effort_level(effort):
            cmd += ["--effort", level]
        tools: list[str] = []
        dirs: list[str] = []
        if vault_tools and self.vault_tools:
            # Хранилище и дословная память разговоров (arvix/memory.py) — голова ищет в них сама,
            # когда нужного нет в контексте, а не отвечает «не знаю».
            if self.cfg.vault:
                dirs.append(str(self.cfg.vault))
            memory = data_dir() / "memory"
            if memory.is_dir():
                dirs.append(str(memory))
            if dirs:
                tools += ["Read", "Grep", "Glob"]
        if web and self.web_tools:
            tools += ["WebSearch", "WebFetch"]
        if plugins:
            tools.append("Skill")
            for folder in plugins:
                cmd += ["--plugin-dir", folder]
        if tools:
            cmd += ["--tools", ",".join(tools), "--allowedTools", ",".join(tools)]
            for folder in dirs:
                cmd += ["--add-dir", folder]
        else:
            cmd += ["--tools", ""]
        return cmd

    def ask(self, *, system: str, prompt: str, schema: dict[str, Any], role: str = "voice", vault_tools: bool = False,
            web: bool = False, skills: str = "off", effort: str | None = None) -> dict[str, Any] | None:
        """None — голова недоступна (лимит подписки, сеть, таймаут). Вызывающий
        отвечает шаблоном L0: напоминания и учёт от этого не ломаются."""
        result = self._ask(system=system, prompt=prompt, schema=schema, role=role, vault_tools=vault_tools, web=web,
                           skills=skills, effort=effort)
        if result is None and self.effort_level(effort) and "effort" in self.last_error.lower():
            # Модель роли не знает усилия (например, старая) — без флага, и больше его не передаём.
            log.warning("усилие отключено: %s", self.last_error[:200])
            self.effort = ""
            result = self._ask(system=system, prompt=prompt, schema=schema, role=role, vault_tools=vault_tools, web=web,
                               skills=skills, effort=None)
        return result

    def _ask(self, *, system: str, prompt: str, schema: dict[str, Any], role: str, vault_tools: bool, web: bool,
             skills: str, effort: str | None) -> dict[str, Any] | None:
        cwd = data_dir() / "brain"
        cwd.mkdir(parents=True, exist_ok=True)
        cmd = self.command(system=system, prompt=prompt, schema=schema, role=role, vault_tools=vault_tools, web=web, skills=skills,
                           effort=effort)
        # Без телеметрии, автообновления и отчётов об ошибках: вызов на сообщение не ждёт чужой сети.
        env = {**os.environ, "ARVIX_BRAIN": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
        started = time.monotonic()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout, cwd=cwd, env=env, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.last_error = str(exc)
            log.warning("claude -p не ответил: %s", exc)
            return None
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            self.last_error = (proc.stderr or proc.stdout)[-500:]
            log.warning("claude -p вернул не JSON (код %s): %s", proc.returncode, self.last_error)
            return None
        if data.get("is_error") or not isinstance(data.get("structured_output"), dict):
            self.last_error = str(data.get("result") or data)[:500]
            log.warning("claude -p ошибка: %s", self.last_error)
            return None
        self.last_error = ""
        # Скорость видна в журнале службы: сколько ждали, сколько ходов с инструментами.
        self.last_stats = {"sec": round(time.monotonic() - started, 1), "turns": data.get("num_turns"), "role": role,
                           "api_ms": data.get("duration_api_ms"), "effort": self.effort_level(effort) or "-"}
        log.info("голова: %(sec)s с, ходов %(turns)s, роль %(role)s, усилие %(effort)s", self.last_stats)
        return data["structured_output"]


def _start_from_deadline(action: dict[str, Any]) -> str | None:
    """Модель иногда пишет «до 20:30» в deadline вместо start: старт = дедлайн − длительность."""
    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(action.get("deadline") or ""))
    if action.get("start") or not match:
        return action.get("start")
    total = int(match.group(1)) * 60 + int(match.group(2)) - int(action.get("duration_min") or 60)
    return f"{max(total, 0) // 60:02d}:{max(total, 0) % 60:02d}"


PROJECT_ACTIONS = frozenset({"set_project", "set_milestone", "plan_project", "project_log", "project_money", "project_channel"})


def _project_action(core: Core, kind: str, a: dict[str, Any], source: str) -> tuple[str, list[str]]:
    """Действия проекта — те же операции L0, что у кнопок приложения (arvix/projects.py)."""
    from arvix import projects

    if kind == "set_project":
        pid = projects.set_project(
            core, a.get("title", ""), project_id=a.get("project") or None, why=a.get("why", ""), kind=a.get("kind"),
            expectation=a.get("expectation") or a.get("metric") or "", deadline=a.get("deadline"), weekly_min=a.get("weekly_min"),
            goal_id=a.get("goal_id") or None, status=a.get("status"), skills=a.get("skills"), link=a.get("link", ""),
            reason=a.get("reason") or a.get("report") or "", source=source,
        )
        p = core.state.projects[pid]
        return f"проект «{p['title']}» · {projects.STATUSES[p['status']]}", [f"проект «{p['title']}»: {i}" for i in projects.issues(core, p)[:3]]
    project = projects.resolve(core, a.get("project") or a.get("goal_id") or "")
    if kind == "set_milestone":
        status = a.get("status") if a.get("status") in projects.MILESTONE_STATUSES else None
        projects.set_milestone(core, project["id"], a.get("title", ""), milestone_id=a.get("milestone") or None,
                               due=a.get("deadline") or a.get("date"), dod=a.get("dod") or a.get("metric") or "",
                               status=status, source=source)
        return f"этап «{a.get('title') or core.state.milestones[a['milestone']]['title']}» · {project['title']}" + (
            " · пройден" if status == "done" else ""), []
    if kind == "plan_project":
        task = projects.plan_block(core, project["id"], minutes=a.get("duration_min") or a.get("minutes") or 60,
                                   day=a.get("date"), start=a.get("start"), title=a.get("title", ""), source=source)
        return f"+ {task.title} · {task.start}, {task.duration_min} мин" + (" · завтра" if task.local_date > core.today() else ""), \
            core.task_warnings(task)
    if kind == "project_log":
        entry = projects.log_entry(core, project["id"], a.get("text") or a.get("report") or "", kind=a.get("kind") or "update",
                                   minutes=a.get("minutes") or 0, source=source)
        return f"журнал «{project['title']}»: {projects.LOG_KINDS[entry['kind']]}", []
    if kind == "project_money":
        m = projects.log_money(core, project["id"], a.get("amount"), direction=a.get("direction") or "out",
                               category=a.get("category", ""), note=a.get("text", ""), channel_id=a.get("channel") or None, source=source)
        return f"{'доход' if m['direction'] == 'in' else 'расход'} {m['amount']:.0f} · {project['title']}", []
    projects.set_channel(core, project["id"], a.get("title", ""), channel_id=a.get("channel") or None, type=a.get("kind"),
                         hypothesis=a.get("hypothesis", ""), cost=a.get("cost"), leads=a.get("leads"), clients=a.get("clients"),
                         revenue=a.get("revenue"), status=a.get("status") if a.get("status") in projects.CHANNEL_STATUSES else None,
                         note=a.get("text", ""), source=source)
    return f"канал «{a.get('title') or a.get('channel')}» · {project['title']}", []


def apply_actions(
    core: Core, actions: list[dict[str, Any]], *, source: str = "telegram", fallback_report: str | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Исполняет actions модели через операции L0. Возвращает (сделано, отказы, сомнения).
    Отказ L0 (например, блокировка из-за долга) честно дописывается к ответу; сомнения —
    несостыковки, найденные checks.py (цель без срока, задача поверх школы, отчёт раньше времени).
    fallback_report — сообщение человека: если модель забыла report, отчёт — его слова."""
    done: list[str] = []
    failed: list[str] = []
    warnings: list[str] = []
    added: list[str] = []
    for action in actions or []:
        kind = action.get("type")
        if kind in UI_ACTIONS:
            continue  # их исполняет бот (Bot.run_ui_actions)
        try:
            if kind == "add_task":
                task = core.add_task(
                    action.get("title", ""), sphere=action.get("sphere") or "project",
                    importance=action.get("importance") or 3, difficulty=action.get("difficulty") or 3,
                    start=_start_from_deadline(action), duration_min=action.get("duration_min") or 60,
                    deep_work=bool(action.get("deep_work")), day=action.get("date"), project=action.get("project") or None,
                    source=source,
                )
                when = (f"{task.start}, " if task.start else "") + f"{task.duration_min} мин"
                done.append(f"+ {task.title} · {when}" + (" · завтра" if task.local_date > core.today() else ""))
                added.append(task.id)
            elif kind == "complete_task":
                report = action.get("report") or fallback_report
                result = core.complete_task(action["task"], done_pct=action.get("done_pct") or 100, report=report, source=source)
                done.append(f"✅ {result['task'].title}" + (" · долг закрыт" if result["debt_closed"] else ""))
                warnings += result["warnings"]
            elif kind == "fail_task":
                result = core.fail_task(action["task"], reason=action.get("reason", ""), source=source)
                done.append(f"❌ {result['task'].title}" + (" · в долг" if result["debt"] else ""))
            elif kind == "defer_task":
                task = core.defer_task(action["task"], int(action.get("minutes") or 15), source=source)
                done.append(f"⏳ {task.title} → {task.start}")
            elif kind == "cancel_task":
                task = core.cancel_task(action["task"], reason=action.get("reason", ""), source=source)
                done.append(f"✖️ {task.title} отменена")
            elif kind == "start_task":
                task = core.start_task(action["task"], source=source)
                done.append(f"▶️ {task.title}")
            elif kind == "log_sleep":
                result = core.log_sleep(action.get("duration") or action.get("minutes"), bedtime=action.get("bedtime"),
                                        wake=action.get("wake"), day=action.get("date"), source=source)
                done.append(f"сон {result['duration_min'] // 60}ч{result['duration_min'] % 60:02d}м" + mode_shift(result))
                warnings += result["warnings"]
            elif kind == "log_expense":
                result = core.log_expense(action["amount"], action.get("category", "прочее"), impulse=bool(action.get("impulse")), note=action.get("text", ""), source=source)
                done.append(f"трата {result['amount']:.0f}")
            elif kind == "log_social":
                core.log_social(action.get("who", ""), source=source)
                done.append("социум +1")
            elif kind == "remember":
                # Модель иногда кладёт факт в text или value — факт важнее имени поля.
                fact = action.get("fact") or action.get("text") or action.get("value") or action.get("title") or ""
                core.remember(action.get("topic") or "general", str(fact), source=source)
            elif kind == "note":
                core.capture_note(action["text"], source=source)
                done.append("заметка в Inbox")
            elif kind == "profile_set":
                core.profile_set(action["key"], action.get("value"), source=source)
            elif kind == "set_goal":
                gid = core.set_goal(
                    action.get("title", ""), why=action.get("why", ""), kind=action.get("kind"), deadline=action.get("deadline"),
                    metric=action.get("metric"), goal_id=action.get("goal_id"), parent_id=action.get("parent_id"),
                    status=action.get("status"), source=source,
                )
                goal = core.state.goals[gid]
                done.append(f"цель «{goal['title']}» · {goal['kind']}" + (f" · {goal['status']}" if goal.get("status") != "active" else ""))
                warnings += [f"цель «{goal['title']}»: {w}" for w in core.goal_warnings(gid)]
            elif kind == "add_trait":
                core.add_trait(action.get("kind", "weakness"), action["title"], description=action.get("text", ""), source=source)
            elif kind == "declare_reason":
                core.declare_reason(action["reason"], source=source)
            elif kind == "learning_question":
                core.learning_question(action.get("question", ""), direct=bool(action.get("direct")), source=source)
            elif kind == "safety_flag":
                core.safety_flag(action.get("level") or "high", action.get("reason") or action.get("text") or "", source="l1")
            elif kind == "set_template":
                core.set_template(action.get("weekdays") or [], action.get("day_type", ""), action.get("blocks") or [], source=source)
                done.append(f"шаблон «{action.get('day_type')}» для дней {action.get('weekdays')}")
            elif kind in PROJECT_ACTIONS:
                line, extra = _project_action(core, kind, action, source)
                done.append(line)
                warnings += extra
        except ArvixError as exc:
            failed.append(f"{ACTION_RU.get(kind, kind)} — {exc}")
        except (KeyError, TypeError, ValueError) as exc:
            # Неполная команда модели — не повод показывать человеку «remember: 'fact'».
            log.warning("action %s отброшен: %r (%s)", kind, exc, action)
            failed.append(f"{ACTION_RU.get(kind, kind)} — не понял, что именно записать; скажи ещё раз словами")
    # Сомнения по новым задачам — после всех actions: модель часто добавляет блок и тем же
    # ответом сдвигает соседний; проверка внахлёст до сдвига была бы ложной.
    for task_id in added:
        task = core.state.tasks.get(task_id)
        if task is not None:
            warnings += [f"«{task.title}»: {w}" for w in core.task_warnings(task)]
    return done, failed, warnings
