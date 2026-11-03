"""MCP-сервер Arvix (stdio, JSON-RPC 2.0) — без зависимостей.

Через него Claude Code (плагин) и чат Claude Desktop работают с тем же журналом
событий, что и Telegram-бот. Каждый инструмент — тонкая обёртка над Core (L0):
модель вызывает, код считает. Включить ментора обратно инструментом нельзя —
только человек командой (02-MECHANICS §6).
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from arvix import __version__, rules
from arvix.context import QUOTA_RU, build_context, hm, task_line
from arvix.core import ArvixError, Core
from arvix.vault import Vault, VaultError

log = logging.getLogger("arvix.mcp")
SUPPORTED_PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "Arvix — личный ментор: журнал событий, задачи, XP/HP, Burnout Guard, интервью, Obsidian. "
    "Числа считает этот сервер; модель их только читает. Начинай с инструмента context."
)


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return schema


STR = {"type": "string"}
INT = {"type": "integer"}
BOOL = {"type": "boolean"}


def _enum(*values: str) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


TOOLS: dict[str, dict[str, Any]] = {
    "context": {
        "description": "Текущее состояние Арвикса: время, режим Burnout Guard, уровень/HP, задачи дня с id, долг, неделя, директивы, цели, память. Вызывай первым.",
        "inputSchema": _obj({"message": {**STR, "description": "текст сообщения человека — для подбора фактов памяти"}}),
    },
    "day": {
        "description": "Задачи на дату (по умолчанию сегодня) с id, статусами и метриками дня.",
        "inputSchema": _obj({"date": {**STR, "description": "ГГГГ-ММ-ДД, today, tomorrow, yesterday"}}),
    },
    "task": {
        "description": "Задачи: add (новая), complete (отчёт о выполнении, done_pct для частичного), fail (провал с причиной; importance ≥ 4 уходит в долг), defer (сдвиг на minutes), cancel (с причиной), start, write_off (списать долг с обоснованием). XP/HP считает код.",
        "inputSchema": _obj({
            "action": _enum("add", "complete", "fail", "defer", "cancel", "start", "write_off"),
            "task": {**STR, "description": "id задачи (8 символов) или часть названия"},
            "title": STR, "sphere": _enum(*rules.SPHERES), "importance": {**INT, "minimum": 1, "maximum": 5},
            "difficulty": {**INT, "minimum": 1, "maximum": 5}, "start": {**STR, "description": "ЧЧ:ММ"},
            "duration_min": INT, "deep_work": BOOL, "date": STR, "tags": {"type": "array", "items": STR},
            "done_pct": {**INT, "minimum": 1, "maximum": 100}, "report": {**STR, "description": "что именно сделано — словами человека"},
            "reason": STR, "minutes": INT,
        }, ["action"]),
    },
    "log": {
        "description": "Записи дня: sleep (duration вроде 7:30, bedtime ЧЧ:ММ), expense (amount, category, impulse), social (живой контакт для квоты), focus (minutes фокус-сессии), reason (причина плохого дня — для щита).",
        "inputSchema": _obj({
            "kind": _enum("sleep", "expense", "social", "focus", "reason"),
            "duration": STR, "bedtime": STR, "date": STR, "amount": {"type": "number"}, "category": STR,
            "impulse": BOOL, "note": STR, "who": STR, "minutes": INT, "task": STR, "reason": STR,
        }, ["kind"]),
    },
    "profile": {
        "description": "Профиль и долговременная память: get, set (key/value), goal (новая цель: title, why обязательно; этап: parent_id; обновить: goal_id + status active|done|dropped), goals (дерево целей), trait (kind: fear|weakness|bad_habit|good_habit|trigger), remember (topic, fact), forget (fact_id), template (шаблон дня: weekdays 0=пн…6=вс, day_type, blocks).",
        "inputSchema": _obj({
            "action": _enum("get", "set", "goal", "goals", "trait", "remember", "forget", "template"),
            "goal_id": STR, "parent_id": STR, "status": _enum("active", "done", "dropped"),
            "key": STR, "value": STR, "title": STR, "why": STR, "kind": STR, "deadline": STR, "metric": STR,
            "description": STR, "severity": INT, "counter_strategy": STR, "topic": STR, "fact": STR,
            "confidence": INT, "valid_days": INT, "fact_id": STR,
            "weekdays": {"type": "array", "items": INT}, "day_type": _enum("study", "work", "deep", "recovery", "silent"),
            "blocks": {"type": "array", "items": _obj({
                "start": STR, "duration": INT, "title": STR, "sphere": STR, "importance": INT, "difficulty": INT,
                "deep_work": BOOL, "tags": {"type": "array", "items": STR},
            }, ["start", "title"])},
        }, ["action"]),
    },
    "interview": {
        "description": "Интервью-знакомство (37 вопросов, 8 блоков, страхи последними): status, next (следующий вопрос, можно block), answer (qid + ответ словами человека), skip.",
        "inputSchema": _obj({"action": _enum("status", "next", "answer", "skip"), "qid": STR, "answer": STR, "block": STR}, ["action"]),
    },
    "check_request": {
        "description": "Факты для решения по просьбе изменить план («хочу погулять в 15:00»): выполнение, глубокая работа, долг, режим, конфликты в окне, квоты. Ничего не меняет — вердикт формулируешь ты на этих цифрах.",
        "inputSchema": _obj({"description": STR, "date": STR, "start": STR, "duration_min": INT}, ["description"]),
    },
    "debrief": {
        "description": "Вечерний разбор: facts (факты дня из журнала), complete (answers — ответы человека, conclusion — один вывод на завтра).",
        "inputSchema": _obj({"action": _enum("facts", "complete"), "date": STR, "answers": STR, "conclusion": STR}, ["action"]),
    },
    "analyst": {
        "description": "Совет (L2, только по явному запросу ретро): events (сырая лента с id за days), directive (kind, text, evidence — минимум один id события, иначе отказ), insight (text, evidence).",
        "inputSchema": _obj({
            "action": _enum("events", "directive", "insight"), "days": INT, "kinds": {"type": "array", "items": STR},
            "kind": _enum("focus", "warning", "schedule_change", "insight", "quota_push"), "text": STR,
            "voice_hint": STR, "priority": INT, "valid_days": INT, "evidence": {"type": "array", "items": INT},
        }, ["action"]),
    },
    "notes": {
        "description": "Obsidian: search (query), read (path), write (path внутри Arvix/, content, append), inbox (text — быстрая заметка), daily (ежедневная заметка человека за date: поля frontmatter).",
        "inputSchema": _obj({
            "action": _enum("search", "read", "write", "inbox", "daily"), "query": STR, "path": STR,
            "content": STR, "append": BOOL, "text": STR, "date": STR, "limit": INT,
        }, ["action"]),
    },
    "mode": {
        "description": "Режимы: status, sos_on / sos_off (ручной 🟥 на 24 ч), silent (тихий день сегодня), safety_flag (признаки настоящей беды — выключает ментора до ручного включения человеком).",
        "inputSchema": _obj({"action": _enum("status", "sos_on", "sos_off", "silent", "safety_flag"), "note": STR, "level": STR}, ["action"]),
    },
    "export": {
        "description": "Полный экспорт в Obsidian (Arvix/Profile.md, Daily/, Insights.md, _raw/events.md).",
        "inputSchema": _obj({"days": INT}),
    },
}


def _vault(core: Core) -> Vault:
    if not core.cfg.vault:
        raise ArvixError("Хранилище Obsidian не настроено: `arvix setup`")
    return Vault(core.cfg.vault, core.cfg.arvix_folder)


def t_context(core: Core, a: dict[str, Any]) -> str:
    return build_context(core, message=a.get("message", ""))


def t_day(core: Core, a: dict[str, Any]) -> str:
    facts = core.day_facts(core.parse_day(a.get("date")))
    lines = [f"{facts['date']:%d.%m.%Y}: {facts['done']}/{facts['total']} задач · глубокая {hm(facts['deep_min'])} · сон {hm(facts['sleep_min'])}"]
    lines += ["  " + task_line(t) for t in facts["tasks"]] or ["  задач нет"]
    if facts["debts"]:
        lines.append("ДОЛГ: " + " · ".join(f"[{t.id}] {t.title}" for t in facts["debts"]))
    return "\n".join(lines)


def t_task(core: Core, a: dict[str, Any]) -> str:
    action = a["action"]
    if action == "add":
        t = core.add_task(a.get("title", ""), sphere=a.get("sphere") or "project", importance=a.get("importance") or 3,
                          difficulty=a.get("difficulty") or 3, start=a.get("start"), duration_min=a.get("duration_min") or 60,
                          deep_work=bool(a.get("deep_work")), day=a.get("date"), tags=a.get("tags") or ())
        return f"Создана: {task_line(t)} · {t.local_date}"
    if action == "complete":
        r = core.complete_task(a["task"], done_pct=a.get("done_pct") or 100, report=a.get("report"))
        return f"Закрыта: {r['task'].title} · +{r['xp']} XP" + (" · долг закрыт" if r["debt_closed"] else "")
    if action == "fail":
        r = core.fail_task(a["task"], reason=a.get("reason", ""))
        return f"Провал: {r['task'].title} · {r['hp']} HP" + (" · ушла в долг" if r["debt"] else "")
    if action == "defer":
        t = core.defer_task(a["task"], int(a.get("minutes") or 15))
        return f"Отложена: {t.title} → {t.local_date} {t.start}"
    if action == "cancel":
        return f"Отменена: {core.cancel_task(a['task'], reason=a.get('reason', '')).title}"
    if action == "start":
        return f"В работе: {core.start_task(a['task']).title}"
    if action == "write_off":
        return f"Долг списан: {core.write_off_debt(a['task'], justification=a.get('reason', '')).title} (обоснование уйдёт в разбор)"
    raise ArvixError(f"Неизвестное действие {action}")


def t_log(core: Core, a: dict[str, Any]) -> str:
    kind = a["kind"]
    if kind == "sleep":
        r = core.log_sleep(a.get("duration") or a.get("minutes"), bedtime=a.get("bedtime"), day=a.get("date"))
        return f"Сон {hm(r['duration_min'])} за {r['date']}. Режим: {rules.MODE_LABELS[r['mode']]}"
    if kind == "expense":
        r = core.log_expense(a.get("amount"), a.get("category", "прочее"), impulse=bool(a.get("impulse")), note=a.get("note", ""))
        return f"Трата {r['amount']:.2f} {r['currency']}. За неделю: {r['week_total']:.2f}"
    if kind == "social":
        core.log_social(a.get("who", ""))
        return "Живой контакт записан (квота «социум»)."
    if kind == "focus":
        core.log_focus(int(a.get("minutes") or 0), task_ref=a.get("task"))
        return f"Фокус-сессия {a.get('minutes')} мин записана."
    if kind == "reason":
        r = core.declare_reason(a.get("reason") or a.get("note", ""))
        return f"Причина записана. Щитов в этом месяце осталось: {r['shields_left']} — сработает при закрытии дня."
    raise ArvixError(f"Неизвестный kind {kind}")


def t_profile(core: Core, a: dict[str, Any]) -> str:
    action = a["action"]
    st = core.state
    if action == "get":
        payload = {"profile": st.profile, "goals": list(st.goals.values()), "traits": list(st.traits.values()),
                   "facts": [{"id": k, **v} for k, v in st.facts.items()], "templates": st.templates}
        return json.dumps(payload, ensure_ascii=False, indent=1, default=str)
    if action == "set":
        core.profile_set(a["key"], a.get("value"))
        return f"Профиль: {a['key']} = {a.get('value')}"
    if action == "goal":
        gid = core.set_goal(a.get("title", ""), why=a.get("why", ""), kind=a.get("kind"), deadline=a.get("deadline"),
                            metric=a.get("metric"), goal_id=a.get("goal_id"), parent_id=a.get("parent_id"), status=a.get("status"))
        return f"Цель [{gid}] записана."
    if action == "goals":
        icons = {"active": "○", "done": "●", "dropped": "✖"}
        rows = [
            "  " * depth + f"{icons.get(g.get('status'), '○')} [{g['id']}] {g['title']}"
            + (f" · до {g['deadline']}" if g.get("deadline") else "") + (f" · метрика: {g['metric']}" if g.get("metric") else "")
            for depth, g in core.goal_tree()
        ]
        return "\n".join(rows) or "Целей пока нет."
    if action == "trait":
        tid = core.add_trait(a.get("kind", ""), a.get("title", ""), description=a.get("description", ""),
                             severity=a.get("severity") or 3, counter_strategy=a.get("counter_strategy", ""))
        return f"Черта [{tid}] записана."
    if action == "remember":
        fid = core.remember(a.get("topic", "general"), a.get("fact", ""), confidence=a.get("confidence") or 3, valid_days=a.get("valid_days"))
        return f"Факт [{fid}] в памяти."
    if action == "forget":
        core.forget(a.get("fact_id", ""), reason=a.get("description", ""))
        return "Факт снят (компенсирующим событием)."
    if action == "template":
        core.set_template(a.get("weekdays") or [], a.get("day_type", ""), a.get("blocks") or [])
        return f"Шаблон «{a.get('day_type')}» для дней {a.get('weekdays')} сохранён. Задачи появятся утром (или сразу — для будущих блоков сегодня)."
    raise ArvixError(f"Неизвестное действие {action}")


def t_interview(core: Core, a: dict[str, Any]) -> str:
    action = a["action"]
    if action == "status":
        s = core.interview_status()
        blocks = "\n".join(f"  {b['title']}: {b['done']}/{b['total']}" for b in s["blocks"])
        nxt = s["next"]
        return f"Отвечено {s['answered']}/{s['total']}\n{blocks}" + (f"\nСледующий: [{nxt['id']}] {nxt['text']}" if nxt else "\nИнтервью пройдено.")
    if action == "next":
        q = core.interview_next(a.get("block"))
        return f"[{q['id']}] ({q['block_title']}) {q['text']}" if q else "Вопросов не осталось."
    if action == "answer":
        r = core.interview_answer(a.get("qid", ""), a.get("answer", ""))
        out = f"Сохранено: {r['saved']}" + (f" · распознано: {r['extracted']}" if r["extracted"] else "")
        if r["block_done"]:
            out += "\nБлок закончен — разложи ответы блока на цели/черты/факты (profile) и спроси, продолжать ли."
        if r["next"]:
            out += f"\nСледующий: [{r['next']['id']}] ({r['next']['block_title']}) {r['next']['text']}"
        return out
    if action == "skip":
        q = core.interview_skip(a.get("qid", ""))
        return f"Пропущено. Следующий: [{q['id']}] {q['text']}" if q else "Пропущено. Вопросов не осталось."
    raise ArvixError(f"Неизвестное действие {action}")


def t_check_request(core: Core, a: dict[str, Any]) -> str:
    d = core.parse_day(a.get("date"))
    st = core.state
    facts = core.day_facts(d)
    lines = [f"ПРОСЬБА: {a.get('description', '')}"]
    pct = f"{facts['completion']:.0f}%" if facts["completion"] is not None else "—"
    lines.append(f"ВЫПОЛНЕНИЕ {d:%d.%m}: {facts['done']}/{facts['total']} ({pct}) · глубокая {hm(facts['deep_min'])} из {hm(int(core.cfg.mech('deep_target_min', 120)))} · сон {hm(facts['sleep_min'])}")
    lines.append(f"РЕЖИМ: {rules.MODE_LABELS[core.effective_mode()]} · HP {st.hp}")
    if facts["debts"]:
        lines.append(f"ДОЛГ: {len(facts['debts'])} — " + ", ".join(t.title for t in facts["debts"]) + (" · необязательные дела заблокированы" if len(facts["debts"]) >= 2 else ""))
    if a.get("start"):
        start = core.at(d, a["start"])
        end = start + timedelta(minutes=int(a.get("duration_min") or 60))
        clash = [t for t in facts["tasks"] if t.is_open and t.start and core.at(d, t.start) < end and core.at(d, t.start) + timedelta(minutes=t.duration_min) > start]
        lines.append("КОНФЛИКТЫ: " + ("; ".join(task_line(t) for t in clash) if clash else "нет"))
    quotas = core.cfg.mech("quotas") or {}
    week = facts["week"]
    lines.append("КВОТЫ НЕДЕЛИ: " + " · ".join(f"{QUOTA_RU.get(k, k)} {week['quotas'].get(k, 0)}/{v}" for k, v in quotas.items()))
    lines.append("Вердикт формулируешь ты — на этих цифрах (decision_rule). Согласился — меняй план инструментом task.")
    return "\n".join(lines)


def t_debrief(core: Core, a: dict[str, Any]) -> str:
    if a["action"] == "complete":
        core.complete_debrief(a.get("answers", ""), conclusion=a.get("conclusion", ""), day=a.get("date"))
        return "Разбор записан. Пропуска не будет (−8 HP снимается только за непройденный разбор)."
    d = core.parse_day(a.get("date"))
    facts = core.day_facts(d)
    lines = [t_day(core, {"date": d.isoformat()})]
    week = facts["week"]
    quotas = core.cfg.mech("quotas") or {}
    lines.append("Квоты: " + " · ".join(f"{QUOTA_RU.get(k, k)} {week['quotas'].get(k, 0)}/{v}" for k, v in quotas.items()))
    if facts["impulse"]:
        lines.append("Импульсивные траты: " + ", ".join(f"{e['amount']:.0f} {e['category']}" for e in facts["impulse"]))
    if core.cfg.vault:
        note = _vault(core).daily_note(d)
        if note:
            fields = ", ".join(f"{k}={v}" for k, v in note["fields"].items() if v)
            lines.append(f"Ежедневная заметка {note['path']}: {fields or 'поля пустые'}")
    return "\n".join(lines)


def t_analyst(core: Core, a: dict[str, Any]) -> str:
    action = a["action"]
    if action == "events":
        lines = core.events_feed(int(a.get("days") or 7), a.get("kinds"))
        return "\n".join(lines) or "Событий нет."
    if action == "directive":
        did = core.add_directive(a.get("kind", ""), a.get("text", ""), evidence=a.get("evidence") or [], voice_hint=a.get("voice_hint", ""),
                                 priority=a.get("priority") or 3, valid_days=a.get("valid_days") or 7, created_by="claude-code", source="claude")
        return f"Директива [{did}] создана — L1 увидит её в контексте."
    if action == "insight":
        core.add_insight(a.get("text", ""), evidence=a.get("evidence") or [], source="claude")
        return "Инсайт записан."
    raise ArvixError(f"Неизвестное действие {action}")


def t_notes(core: Core, a: dict[str, Any]) -> str:
    action = a["action"]
    if action == "inbox":
        path = core.capture_note(a.get("text", ""))
        return f"Записано в {path or 'журнал (хранилище не настроено)'}"
    vault = _vault(core)
    if action == "search":
        found = vault.search(a.get("query", ""), int(a.get("limit") or 8))
        if not found:
            return "Ничего не найдено."
        return "\n".join(f"📄 {r['path']}" + (f" — «{r['heading']}»" if r["heading"] else "") + f", {r['modified']}\n   {r['snippet']}" for r in found)
    if action == "read":
        return vault.read(a.get("path", ""))
    if action == "write":
        return f"Записано: {vault.write(a.get('path', ''), a.get('content', ''), append=bool(a.get('append')))}"
    if action == "daily":
        note = vault.daily_note(core.parse_day(a.get("date")))
        return json.dumps(note, ensure_ascii=False, indent=1) if note else "Ежедневной заметки за эту дату нет."
    raise ArvixError(f"Неизвестное действие {action}")


def t_mode(core: Core, a: dict[str, Any]) -> str:
    action = a["action"]
    if action == "sos_on":
        core.sos(True, note=a.get("note", ""))
    elif action == "sos_off":
        core.sos(False)
    elif action == "silent":
        core.silent_today()
    elif action == "safety_flag":
        core.safety_flag(a.get("level") or "high", a.get("note", ""), source="claude")
        return "Ментор выключен до ручного включения человеком. Дальше — только человеческий тон, без задач и цифр."
    s = core.status()
    return f"Режим: {rules.MODE_LABELS[s['effective_mode']]} ({s['mode_trigger'] or 'без триггера'}) · ментор {'вкл' if s['mentor_enabled'] else 'ВЫКЛ'} · HP {s['hp']}"


def t_export(core: Core, a: dict[str, Any]) -> str:
    from arvix.export import export_all

    written = export_all(core, int(a.get("days") or 60))
    return f"Экспортировано файлов: {len(written)} → {core.cfg.arvix_folder}/"


HANDLERS: dict[str, Callable[[Core, dict[str, Any]], str]] = {
    "context": t_context, "day": t_day, "task": t_task, "log": t_log, "profile": t_profile,
    "interview": t_interview, "check_request": t_check_request, "debrief": t_debrief,
    "analyst": t_analyst, "notes": t_notes, "mode": t_mode, "export": t_export,
}


class Server:
    def __init__(self, core_factory: Callable[[], Core] = Core):
        self._factory = core_factory
        self._core: Core | None = None

    @property
    def core(self) -> Core:
        if self._core is None:
            self._core = self._factory()
        return self._core

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        handler = HANDLERS.get(name)
        if handler is None:
            return {"content": [{"type": "text", "text": f"Нет инструмента {name}"}], "isError": True}
        try:
            self.core.refresh()
            text = handler(self.core, args or {})
            return {"content": [{"type": "text", "text": text}], "isError": False}
        except (ArvixError, VaultError) as exc:
            return {"content": [{"type": "text", "text": f"Отказ: {exc}"}], "isError": True}
        except Exception as exc:  # noqa: BLE001 — сервер не должен падать от одной ошибки
            log.error("tool %s: %s", name, traceback.format_exc())
            return {"content": [{"type": "text", "text": f"Ошибка: {exc}"}], "isError": True}

    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method")
        msg_id = msg.get("id")
        if msg_id is None:
            return None  # уведомления (notifications/initialized и др.) ответа не требуют
        params = msg.get("params") or {}
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[1]
            result: Any = {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "arvix", "version": __version__},
                "instructions": INSTRUCTIONS,
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [{"name": name, **spec} for name, spec in TOOLS.items()]}
        elif method == "tools/call":
            result = self.call_tool(params.get("name", ""), params.get("arguments") or {})
        elif method in ("resources/list", "prompts/list"):
            result = {method.split("/")[0]: []}
        else:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def serve() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="arvix-mcp %(levelname)s %(message)s")
    server = Server()
    out = sys.stdout.buffer
    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            response: Any = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            if isinstance(msg, list):
                response = [r for r in (server.handle(m) for m in msg) if r is not None] or None
            else:
                response = server.handle(msg)
        if response is not None:
            out.write((json.dumps(response, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
            out.flush()


if __name__ == "__main__":
    serve()
