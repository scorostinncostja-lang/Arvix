"""CLI `arvix` — для человека, хуков, systemd и отладки.

Примеры:
  arvix status                 уровень, HP, режим, сезон
  arvix day                    задачи на сегодня
  arvix add "Физика" --start 18:00 --dur 60 --imp 4 --sphere learning --deep
  arvix done a1b2 --report "решил 12 задач"
  arvix sleep 7:20 --bed 00:10
  arvix setup                  хранилище, часовой пояс, Telegram
  arvix telegram               запустить бота (обычно это делает systemd)
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from arvix import __version__, rules
from arvix.config import config_file, data_dir, load_config, write_user_config
from arvix.context import build_context, hm, task_line
from arvix.core import ArvixError, Core
from arvix.state import State

CLI = "cli"
PLUGIN_STYLE = "arvix:Arvix"
PLUGIN_TOOLS = "mcp__plugin_arvix_arvix"


def _core() -> Core:
    core = Core()
    core.refresh()
    return core


def cmd_status(args: argparse.Namespace) -> None:
    core = _core()
    s = core.status()
    season = s["season"]
    print(f"Режим: {rules.MODE_LABELS[s['effective_mode']]} {('(' + s['mode_trigger'] + ')') if s['mode_trigger'] else ''}")
    print(f"Уровень {s['level']} ({s['xp_into']}/{s['xp_need']} XP, всего {s['xp_total']}) · HP {s['hp']} · стрик {s['streak']} дн")
    print(f"Сезон S{season['number']} нед.{season['week']} · {season['rank']} (SP {season['sp_avg']}) · щитов {s['shields_left']}")
    print(f"Ментор: {'включён' if s['mentor_enabled'] else 'ВЫКЛЮЧЕН (safety-контур) — `arvix mentor on`'} · долг: {s['debts']}")


def cmd_context(args: argparse.Namespace) -> None:
    print(build_context(_core()))


def cmd_day(args: argparse.Namespace) -> None:
    core = _core()
    facts = core.day_facts(core.parse_day(args.date))
    print(f"{facts['date']:%d.%m.%Y}: {facts['done']}/{facts['total']} · глубокая {hm(facts['deep_min'])} · сон {hm(facts['sleep_min'])}")
    for task in facts["tasks"]:
        print("  " + task_line(task))


def cmd_add(args: argparse.Namespace) -> None:
    task = _core().add_task(args.title, sphere=args.sphere, importance=args.imp, difficulty=args.diff, start=args.start,
                            duration_min=args.dur, deep_work=args.deep, day=args.date, source=CLI)
    print(f"+ {task_line(task)}")


def cmd_done(args: argparse.Namespace) -> None:
    result = _core().complete_task(args.task, done_pct=args.pct, report=args.report, source=CLI)
    print(f"✅ {result['task'].title} · +{result['xp']} XP")


def cmd_fail(args: argparse.Namespace) -> None:
    result = _core().fail_task(args.task, reason=args.reason, source=CLI)
    print(f"❌ {result['task'].title} · {result['hp']} HP" + (" · в долг" if result["debt"] else ""))


def cmd_defer(args: argparse.Namespace) -> None:
    task = _core().defer_task(args.task, args.minutes, source=CLI)
    print(f"⏳ {task.title} → {task.start}")


def cmd_sleep(args: argparse.Namespace) -> None:
    result = _core().log_sleep(args.duration, bedtime=args.bed, day=args.date, source=CLI)
    print(f"Сон {hm(result['duration_min'])}. Режим: {rules.MODE_LABELS[result['mode']]}")


def cmd_spend(args: argparse.Namespace) -> None:
    result = _core().log_expense(args.amount, args.category, impulse=args.impulse, source=CLI)
    print(f"Трата {result['amount']:.2f} {result['currency']} · за неделю {result['week_total']:.2f}")


def cmd_note(args: argparse.Namespace) -> None:
    print(f"Записано: {_core().capture_note(' '.join(args.text), source=CLI) or 'в журнал'}")


def cmd_find(args: argparse.Namespace) -> None:
    from arvix.vault import Vault

    cfg = load_config()
    if not cfg.vault:
        sys.exit("Хранилище не настроено: arvix setup")
    for r in Vault(cfg.vault, cfg.vault_paths).search(" ".join(args.query)):
        print(f"📄 {r['path']} {('— ' + r['heading']) if r['heading'] else ''}\n   {r['snippet']}")


def cmd_mentor(args: argparse.Namespace) -> None:
    _core().set_mentor(args.state == "on", by="cli")
    print("Режим ментора " + ("включён." if args.state == "on" else "выключен."))


def cmd_sos(args: argparse.Namespace) -> None:
    mode = _core().sos(args.state == "on", source=CLI)
    print(f"Режим: {rules.MODE_LABELS[mode]}")


def cmd_silent(args: argparse.Namespace) -> None:
    _core().silent_today(source=CLI)
    print("Тихий день: проактивных сообщений не будет, разбор без штрафов.")


def cmd_export(args: argparse.Namespace) -> None:
    from arvix.export import export_all

    written = export_all(_core(), args.days)
    print(f"Экспортировано файлов: {len(written)}")


def cmd_events(args: argparse.Namespace) -> None:
    print("\n".join(_core().events_feed(args.days)))


def cmd_rebuild(args: argparse.Namespace) -> None:
    """Проверка инвариантов 03-DATA-MODEL §3 на живой базе."""
    core = Core()
    events = core.store.read(0)
    fresh = State.rebuild(events)
    xp_sum = sum(int(e.payload["amount"]) for e in events if e.kind == "xp_awarded")
    checks = {
        "rebuild == инкремент (XP, HP, задачи)": (fresh.xp_total, fresh.hp, len(fresh.tasks)) == (core.state.xp_total, core.state.hp, len(core.state.tasks)),
        "HP в [0, 100]": 0 <= fresh.hp <= 100,
        "сумма xp_awarded == xp_total": xp_sum == fresh.xp_total,
        "XP не убывает": all(int(e.payload["amount"]) >= 0 for e in events if e.kind == "xp_awarded"),
    }
    for name, ok in checks.items():
        print(("OK  " if ok else "FAIL") + " " + name)
    print(f"Событий: {len(events)}")
    if not all(checks.values()):
        sys.exit(1)


def cmd_interview(args: argparse.Namespace) -> None:
    """Интервью в терминале, без ИИ. Ctrl+C — пауза, продолжишь потом."""
    core = _core()
    print("Знакомство. Enter без текста — пропустить вопрос, Ctrl+C — пауза.\n")
    try:
        while question := core.interview_next(args.block):
            answer = input(f"[{question['block_title']}] {question['text']}\n> ").strip()
            if answer:
                result = core.interview_answer(question["id"], answer, source=CLI)
                if result["extracted"]:
                    print(f"  записал: {result['extracted']}")
            else:
                core.interview_skip(question["id"], source=CLI)
        print("Интервью пройдено. Разложить ответы на цели и черты: /arvix:onboarding в Claude Code.")
    except (KeyboardInterrupt, EOFError):
        print("\nПауза. Продолжишь: arvix interview")


def _detect_vault() -> str:
    registry = Path("~/.config/obsidian/obsidian.json").expanduser()
    try:
        vaults = json.loads(registry.read_text(encoding="utf-8")).get("vaults", {}).values()
        ordered = sorted(vaults, key=lambda v: (not v.get("open"), -int(v.get("ts", 0))))
        return ordered[0]["path"] if ordered else ""
    except (OSError, ValueError, KeyError, IndexError):
        return ""


def _detect_tz() -> str:
    try:
        link = os.readlink("/etc/localtime")
        return link.split("zoneinfo/", 1)[1]
    except (OSError, IndexError):
        return "Europe/Moscow"


def _ask(prompt: str, default: str = "") -> str:
    answer = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return answer or default


def home_settings(vault: str) -> dict[str, Any]:
    allow = [PLUGIN_TOOLS, "Grep", "Glob"]
    if vault:
        allow.append(f"Read(/{vault}/**)")
    settings: dict[str, Any] = {"outputStyle": PLUGIN_STYLE, "permissions": {"allow": allow}}
    if vault:
        settings["permissions"]["additionalDirectories"] = [vault]
    return settings


def init_home(home: Path, vault: str) -> list[str]:
    """Дом Арвикса: папка, где `claude` запускается в стиле Arvix с доступом к хранилищу."""
    created = []
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    marker = home / ".arvix-home"
    if not marker.exists():
        marker.write_text("Маркер дома Арвикса: хуки плагина работают только здесь.\n", encoding="utf-8")
        created.append(str(marker))
    settings = home / ".claude" / "settings.json"
    if not settings.exists():
        settings.write_text(json.dumps(home_settings(vault), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        created.append(str(settings))
    readme = home / "CLAUDE.md"
    if not readme.exists():
        readme.write_text(
            "# Дом Арвикса\n\n"
            "Здесь Claude работает как Арвикс — личный ментор (стиль Arvix включён в .claude/settings.json).\n\n"
            "- Состояние, задачи, XP/HP, интервью — MCP-инструменты `arvix` (начинай с `context`).\n"
            f"- Obsidian: `{vault or 'не настроено'}` — Арвикс работает в его структуре: свои заметки создаёт, чужие только дополняет.\n"
            "- Скиллы: /arvix:onboarding, /arvix:plan, /arvix:goal, /arvix:brief, /arvix:debrief, /arvix:retro, /arvix:learn, /arvix:notes.\n",
            encoding="utf-8",
        )
        created.append(str(readme))
    return created


def _pair_telegram(token: str) -> int:
    from arvix.telegram.api import TelegramAPI, TelegramError

    api = TelegramAPI(token)
    try:
        me = api.call("getMe")
    except TelegramError as exc:
        sys.exit(f"Токен не подошёл: {exc}")
    print(f"Бот @{me['username']} найден. Открой его в Telegram и отправь /start — жду 3 минуты.")
    offset = 0
    deadline = time.time() + 180
    while time.time() < deadline:
        for update in api.get_updates(offset, timeout=20):
            offset = update["update_id"] + 1
            sender = (update.get("message") or {}).get("from")
            if not sender:
                continue
            name = " ".join(x for x in (sender.get("first_name"), sender.get("last_name")) if x)
            if _ask(f"Сообщение от {name} (@{sender.get('username', '—')}, id {sender['id']}). Это ты? y/N", "n").lower() in ("y", "д", "да", "yes"):
                api.get_updates(offset, timeout=0)  # подтвердить прочитанное
                api.send(sender["id"], "Связь есть. Я Арвикс. Дальше — /start.")
                return int(sender["id"])
    sys.exit("Не дождался сообщения. Запусти `arvix setup` ещё раз.")


def cmd_setup(args: argparse.Namespace) -> None:
    cfg = load_config()
    print(f"Настройка Arvix {__version__}. Конфиг: {config_file()}\n")
    vault = _ask("Путь к Obsidian-хранилищу", str(cfg.vault or _detect_vault()))
    if vault and not Path(vault).expanduser().is_dir():
        sys.exit(f"Папки нет: {vault}")
    tz = _ask("Часовой пояс", str(cfg.raw.get("timezone") or _detect_tz()))
    home = _ask("Дом Арвикса для Claude Code", str(cfg.home))
    updates: dict[str, Any] = {"vault": vault, "timezone": tz, "home": home}
    claude_bin = cfg.section("brain").get("claude_bin") or "claude"
    from shutil import which

    updates["brain"] = {"claude_bin": which(claude_bin) or claude_bin}
    if _ask("Настроить Telegram-бота сейчас? Y/n", "y").lower() in ("y", "д", "да", "yes"):
        print("Создай бота у @BotFather (/newbot) и вставь токен. Ввод скрыт.")
        token = getpass.getpass("Токен: ").strip()
        if token:
            updates["telegram"] = {"token": token, "owner_id": _pair_telegram(token)}
    path = write_user_config(updates)
    print(f"\nКонфиг записан: {path} (права 600)")
    for item in init_home(Path(home).expanduser(), vault):
        print(f"Создано: {item}")
    print("\nДальше:\n  systemctl --user enable --now arvix-telegram   # бот\n  cd ~/Arvix && claude                            # Арвикс в Claude Code")


def cmd_init_home(args: argparse.Namespace) -> None:
    cfg = load_config()
    for item in init_home(cfg.home, str(cfg.vault or "")):
        print(f"Создано: {item}")


def cmd_desktop_mcp(args: argparse.Namespace) -> None:
    """Регистрирует MCP-сервер в чате Claude Desktop (с резервной копией конфига)."""
    path = Path("~/.config/Claude/claude_desktop_config.json").expanduser()
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    script = Path(__file__).resolve().parent.parent / "scripts" / "arvix_mcp.py"
    entry = {"command": sys.executable, "args": [str(script)]}
    if data.get("mcpServers", {}).get("arvix") == entry:
        print("Уже зарегистрирован.")
        return
    if path.exists():
        backup = path.with_suffix(f".json.bak-{int(time.time())}")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Резервная копия: {backup}")
    data.setdefault("mcpServers", {})["arvix"] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"MCP-сервер arvix добавлен в {path}. Перезапусти Claude Desktop.")


def cmd_doctor(args: argparse.Namespace) -> None:
    from arvix.brain import Brain

    cfg = load_config()
    ok = True

    def check(name: str, passed: bool, hint: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        print(("OK  " if passed else "FAIL") + f" {name}" + ("" if passed or not hint else f" — {hint}"))

    check(f"конфиг {config_file()}", config_file().exists(), "arvix setup")
    check(f"база {cfg.db_path}", Core().store is not None)
    check(f"хранилище {cfg.vault}", bool(cfg.vault and cfg.vault.is_dir()), "arvix setup")
    check(f"дом {cfg.home}", (cfg.home / ".arvix-home").exists(), "arvix init-home")
    check("claude CLI для головы", Brain(cfg).available(), "укажи [brain] claude_bin в config.toml")
    tg = cfg.section("telegram")
    check("Telegram токен и владелец", bool(tg.get("token") and tg.get("owner_id")), "arvix setup")
    print(f"Данные: {data_dir()}")
    if not ok:
        sys.exit(1)


def cmd_brain_test(args: argparse.Namespace) -> None:
    from arvix.brain import VOICE_SCHEMA, Brain
    from arvix.prompt import system_prompt

    core = _core()
    started = time.time()
    result = Brain(core.cfg).ask(system=system_prompt(core), prompt=args.text, schema=VOICE_SCHEMA)
    print(json.dumps(result, ensure_ascii=False, indent=1) if result else "Голова не ответила — смотри журнал.")
    print(f"{time.time() - started:.1f} с")


def cmd_telegram(args: argparse.Namespace) -> None:
    from arvix.telegram.daemon import main

    main()


def cmd_mcp(args: argparse.Namespace) -> None:
    from arvix.mcp_server import serve

    serve()


def cmd_hook(args: argparse.Namespace) -> None:
    from arvix.hooks import run

    sys.exit(run(args.event))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arvix", description="Арвикс — личный ментор (L0-команды без ИИ).")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, func: Any, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=func)
        return p

    add("status", cmd_status, "уровень, HP, режим, сезон")
    add("context", cmd_context, "контекст-пакет, который видит модель")
    add("day", cmd_day, "задачи на дату").add_argument("date", nargs="?")
    p = add("add", cmd_add, "новая задача")
    p.add_argument("title")
    p.add_argument("--start")
    p.add_argument("--dur", type=int, default=60)
    p.add_argument("--imp", type=int, default=3)
    p.add_argument("--diff", type=int, default=3)
    p.add_argument("--sphere", default="project", choices=rules.SPHERES)
    p.add_argument("--deep", action="store_true")
    p.add_argument("--date")
    p = add("done", cmd_done, "закрыть задачу")
    p.add_argument("task")
    p.add_argument("--report")
    p.add_argument("--pct", type=int, default=100)
    p = add("fail", cmd_fail, "провал задачи")
    p.add_argument("task")
    p.add_argument("--reason", required=True)
    p = add("defer", cmd_defer, "отложить задачу")
    p.add_argument("task")
    p.add_argument("minutes", type=int, nargs="?", default=15)
    p = add("sleep", cmd_sleep, "записать сон: 7:30")
    p.add_argument("duration")
    p.add_argument("--bed")
    p.add_argument("--date")
    p = add("spend", cmd_spend, "трата: 1200 еда")
    p.add_argument("amount")
    p.add_argument("category")
    p.add_argument("--impulse", action="store_true")
    add("note", cmd_note, "заметка в Inbox хранилища").add_argument("text", nargs="+")
    add("find", cmd_find, "поиск по Obsidian").add_argument("query", nargs="+")
    add("mentor", cmd_mentor, "включить/выключить ментора").add_argument("state", choices=("on", "off"))
    add("sos", cmd_sos, "ручной режим 🟥").add_argument("state", choices=("on", "off"))
    add("silent", cmd_silent, "тихий день сегодня")
    add("export", cmd_export, "экспорт в Obsidian").add_argument("--days", type=int, default=60)
    add("events", cmd_events, "лента событий").add_argument("--days", type=int, default=3)
    add("rebuild", cmd_rebuild, "проверить инварианты журнала")
    add("interview", cmd_interview, "интервью-знакомство в терминале").add_argument("--block")
    add("setup", cmd_setup, "первичная настройка")
    add("init-home", cmd_init_home, "создать дом Арвикса для Claude Code")
    add("doctor", cmd_doctor, "проверка установки")
    add("desktop-mcp", cmd_desktop_mcp, "подключить к чату Claude Desktop")
    add("brain-test", cmd_brain_test, "пробный вызов головы").add_argument("text", nargs="?", default="Как у меня дела сегодня?")
    add("telegram", cmd_telegram, "запустить Telegram-бота")
    add("mcp", cmd_mcp, "MCP-сервер (stdio)")
    add("hook", cmd_hook, "хуки Claude Code").add_argument("event", choices=("session-start", "prompt"))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except ArvixError as exc:
        sys.exit(f"Отказ: {exc}")


if __name__ == "__main__":
    main()
