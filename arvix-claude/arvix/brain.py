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
from typing import Any

from arvix.config import Config, data_dir
from arvix.core import ArvixError, Core

log = logging.getLogger("arvix.brain")

ACTION_TYPES = (
    "add_task", "complete_task", "fail_task", "defer_task", "cancel_task", "start_task",
    "log_sleep", "log_expense", "log_social", "remember", "note", "profile_set",
    "set_goal", "add_trait", "declare_reason", "learning_question", "safety_flag", "set_template",
)

_ACTION_FIELDS = {
    "type": {"type": "string", "enum": list(ACTION_TYPES)},
    "task": {"type": "string", "description": "id задачи из контекста"},
    "title": {"type": "string"}, "sphere": {"type": "string"}, "importance": {"type": "integer"},
    "difficulty": {"type": "integer"}, "start": {"type": "string", "description": "время начала ЧЧ:ММ — для add_task обязательно"},
    "duration_min": {"type": "integer"}, "deep_work": {"type": "boolean"}, "date": {"type": "string"},
    "done_pct": {"type": "integer"}, "report": {"type": "string", "description": "для complete_task: что именно сделано, словами человека"},
    "reason": {"type": "string"},
    "minutes": {"type": "integer"}, "duration": {"type": "string", "description": "сон, например 7:30"},
    "bedtime": {"type": "string"}, "amount": {"type": "number"}, "category": {"type": "string"},
    "impulse": {"type": "boolean"}, "who": {"type": "string"}, "topic": {"type": "string"},
    "fact": {"type": "string"}, "key": {"type": "string"}, "value": {"type": "string"},
    "text": {"type": "string"}, "kind": {"type": "string"}, "why": {"type": "string"},
    "deadline": {"type": "string"}, "level": {"type": "string"}, "question": {"type": "string"},
    "direct": {"type": "boolean"},
    "weekdays": {"type": "array", "items": {"type": "integer"}, "description": "для set_template: 0=пн … 6=вс"},
    "day_type": {"type": "string", "enum": ["study", "work", "deep", "recovery", "silent"]},
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

# Валидаторы ответа (04-AI-LAYER §9) — дешёвые проверки кодом, без модели.
GENTLE_STOP = ("дисциплин", "продуктивн", "провал", "слил", "штраф", "лень", "саботаж", " xp", " hp", "выполнени", "долг")
LINK_RE = re.compile(r"https?://\S+")


def gentle_violation(text: str) -> bool:
    low = f" {text.lower()}"
    return any(word in low for word in GENTLE_STOP)


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
        self.last_error = ""

    def available(self) -> bool:
        return shutil.which(self.bin) is not None or os.path.isfile(self.bin)

    def command(self, *, system: str, prompt: str, schema: dict[str, Any], role: str, vault_tools: bool) -> list[str]:
        cmd = [
            self.bin, "-p", prompt,
            "--system-prompt", system,
            "--output-format", "json",
            "--json-schema", json.dumps(schema, ensure_ascii=False),
            "--setting-sources", "",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--permission-mode", "dontAsk",
            "--permission-prompts", "none",
        ]
        if model := self.cfg.model(role):
            cmd += ["--model", model]
        if vault_tools and self.vault_tools and self.cfg.vault:
            cmd += ["--tools", "Read,Grep,Glob", "--allowedTools", "Read,Grep,Glob", "--add-dir", str(self.cfg.vault)]
        else:
            cmd += ["--tools", ""]
        return cmd

    def ask(self, *, system: str, prompt: str, schema: dict[str, Any], role: str = "voice", vault_tools: bool = False) -> dict[str, Any] | None:
        """None — голова недоступна (лимит подписки, сеть, таймаут). Вызывающий
        отвечает шаблоном L0: напоминания и учёт от этого не ломаются."""
        cwd = data_dir() / "brain"
        cwd.mkdir(parents=True, exist_ok=True)
        cmd = self.command(system=system, prompt=prompt, schema=schema, role=role, vault_tools=vault_tools)
        env = {**os.environ, "ARVIX_BRAIN": "1"}
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
        return data["structured_output"]


def _start_from_deadline(action: dict[str, Any]) -> str | None:
    """Модель иногда пишет «до 20:30» в deadline вместо start: старт = дедлайн − длительность."""
    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(action.get("deadline") or ""))
    if action.get("start") or not match:
        return action.get("start")
    total = int(match.group(1)) * 60 + int(match.group(2)) - int(action.get("duration_min") or 60)
    return f"{max(total, 0) // 60:02d}:{max(total, 0) % 60:02d}"


def apply_actions(
    core: Core, actions: list[dict[str, Any]], *, source: str = "telegram", fallback_report: str | None = None,
) -> tuple[list[str], list[str]]:
    """Исполняет actions модели через операции L0. Возвращает (сделано, отказы).
    Отказ L0 (например, блокировка из-за долга) честно дописывается к ответу.
    fallback_report — сообщение человека: если модель забыла report, отчёт — его слова."""
    done: list[str] = []
    failed: list[str] = []
    for action in actions or []:
        kind = action.get("type")
        try:
            if kind == "add_task":
                task = core.add_task(
                    action.get("title", ""), sphere=action.get("sphere") or "project",
                    importance=action.get("importance") or 3, difficulty=action.get("difficulty") or 3,
                    start=_start_from_deadline(action), duration_min=action.get("duration_min") or 60,
                    deep_work=bool(action.get("deep_work")), day=action.get("date"), source=source,
                )
                done.append(f"+ задача [{task.id}] {task.title}")
            elif kind == "complete_task":
                report = action.get("report") or fallback_report
                result = core.complete_task(action["task"], done_pct=action.get("done_pct") or 100, report=report, source=source)
                done.append(f"✅ {result['task'].title} +{result['xp']} XP")
            elif kind == "fail_task":
                result = core.fail_task(action["task"], reason=action.get("reason", ""), source=source)
                done.append(f"❌ {result['task'].title} {result['hp']} HP" + (" · в долг" if result["debt"] else ""))
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
                result = core.log_sleep(action.get("duration") or action.get("minutes"), bedtime=action.get("bedtime"), day=action.get("date"), source=source)
                done.append(f"сон {result['duration_min'] // 60}ч{result['duration_min'] % 60:02d}м")
            elif kind == "log_expense":
                result = core.log_expense(action["amount"], action.get("category", "прочее"), impulse=bool(action.get("impulse")), note=action.get("text", ""), source=source)
                done.append(f"трата {result['amount']:.0f}")
            elif kind == "log_social":
                core.log_social(action.get("who", ""), source=source)
                done.append("социум +1")
            elif kind == "remember":
                core.remember(action.get("topic", "general"), action["fact"], source=source)
            elif kind == "note":
                core.capture_note(action["text"], source=source)
                done.append("заметка в Inbox")
            elif kind == "profile_set":
                core.profile_set(action["key"], action.get("value"), source=source)
            elif kind == "set_goal":
                core.set_goal(action["title"], why=action.get("why", ""), kind=action.get("kind") or "main", deadline=action.get("deadline"), source=source)
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
        except (ArvixError, KeyError, TypeError, ValueError) as exc:
            failed.append(f"{kind}: {exc}")
    return done, failed
