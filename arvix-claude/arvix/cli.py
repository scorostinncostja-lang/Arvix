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
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from arvix import __version__, rules
from arvix.config import config_file, data_dir, load_config, write_user_config
from arvix.context import build_context, hm, task_line
from arvix.core import ArvixError, Core
from arvix.state import State

CLI = "cli"
PLUGIN_STYLE = "arvix:Arvix"
PLUGIN_TOOLS = "mcp__plugin_arvix_arvix"
# Строка состояния Claude Code в доме Арвикса: режим · уровень · HP · день · следующий блок.
STATUS_LINE = {"type": "command", "command": "~/.local/bin/arvix statusline", "refreshInterval": 60}
YES = ("y", "д", "да", "yes")


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
        allow.append(f"Read(/{vault}/**)")  # «//…» в правилах Claude Code — абсолютный путь
    settings: dict[str, Any] = {"outputStyle": PLUGIN_STYLE, "statusLine": dict(STATUS_LINE), "permissions": {"allow": allow}}
    if vault:
        settings["permissions"]["additionalDirectories"] = [vault]
    return settings


def merge_home_settings(current: dict[str, Any], wanted: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Дополняет настройки дома тем, чего не хватает, не трогая то, что человек поменял сам."""
    merged = json.loads(json.dumps(current))
    changed = False
    for key in ("outputStyle", "statusLine"):
        if key not in merged:
            merged[key] = wanted[key]
            changed = True
    permissions = merged.setdefault("permissions", {})
    allow = permissions.setdefault("allow", [])
    for rule in wanted["permissions"]["allow"]:
        if rule not in allow:
            allow.append(rule)
            changed = True
    for folder in wanted["permissions"].get("additionalDirectories", []):
        dirs = permissions.setdefault("additionalDirectories", [])
        if folder not in dirs:
            dirs.append(folder)
            changed = True
    return merged, changed


def init_home(home: Path, vault: str) -> list[str]:
    """Дом Арвикса: папка, где `claude` запускается в стиле Arvix с доступом к хранилищу.
    Повторный вызов дополняет настройки (например, строкой состояния), не перезаписывая их."""
    created = []
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    marker = home / ".arvix-home"
    if not marker.exists():
        marker.write_text("Маркер дома Арвикса: хуки плагина работают только здесь.\n", encoding="utf-8")
        created.append(str(marker))
    settings = home / ".claude" / "settings.json"
    wanted = home_settings(vault)
    if settings.exists():
        try:
            current = json.loads(settings.read_text(encoding="utf-8"))
        except ValueError:
            current = {}
        merged, changed = merge_home_settings(current, wanted)
        if changed:
            settings.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            created.append(f"{settings} (дополнен)")
    else:
        settings.write_text(json.dumps(wanted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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


def _user_config() -> dict[str, Any]:
    """Только то, что записано в конфиге пользователя (без defaults.toml)."""
    try:
        return tomllib.loads(config_file().read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def cmd_setup(args: argparse.Namespace) -> None:
    """Без флагов — диалог. С флагами и --yes — без вопросов (скрипты, повторная настройка).
    Токен бота всегда вводится скрыто и только в терминале: в чаты и логи он не попадает."""
    cfg = load_config()
    ask = not args.yes

    def pick(prompt: str, default: str, given: str | None) -> str:
        if given is not None:
            return given
        return _ask(prompt, default) if ask else default

    print(f"Настройка Arvix {__version__}. Конфиг: {config_file()}\n")
    vault = pick("Путь к Obsidian-хранилищу", str(cfg.vault or _detect_vault()), args.vault)
    vault = str(Path(vault).expanduser()) if vault else ""
    if vault and not Path(vault).is_dir():
        sys.exit(f"Папки нет: {vault}")
    tz = pick("Часовой пояс", str(cfg.raw.get("timezone") or _detect_tz()), args.tz)
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        sys.exit(f"Неизвестный часовой пояс: {tz}")
    home = pick("Дом Арвикса для Claude Code", str(cfg.home), args.home)
    updates: dict[str, Any] = {"vault": vault, "timezone": tz, "home": home}
    claude_bin = cfg.section("brain").get("claude_bin") or "claude"
    from shutil import which

    updates["brain"] = {"claude_bin": which(claude_bin) or claude_bin}
    if vault:
        from arvix.vault import detect_paths

        user_paths = _user_config().get("vault_paths") or {}
        detected = {k: v for k, v in detect_paths(Path(vault)).items() if not user_paths.get(k)}
        if detected:
            updates["vault_paths"] = detected
            print("В хранилище нашёл: " + ", ".join(f"{k} → {v}" for k, v in detected.items()))
    want_telegram = args.telegram
    if want_telegram is None:
        want_telegram = ask and _ask("Настроить Telegram-бота сейчас? Y/n", "y").lower() in YES
    if want_telegram:
        if not sys.stdin.isatty():
            sys.exit("Токен бота вводится только в терминале (скрытый ввод): arvix setup --telegram --yes")
        print("Создай бота у @BotFather (/newbot) и вставь токен. Ввод скрыт.")
        token = getpass.getpass("Токен: ").strip()
        if token:
            updates["telegram"] = {"token": token, "owner_id": _pair_telegram(token)}
    path = write_user_config(updates)
    print(f"\nКонфиг записан: {path} (права 600)")
    for item in init_home(Path(home).expanduser(), vault):
        print(f"Создано: {item}")
    print(
        "\nДальше:\n"
        "  arvix setup --telegram --yes                   # привязать бота, если ещё нет\n"
        "  systemctl --user enable --now arvix-telegram   # бот\n"
        f"  cd {home} && claude                            # Арвикс в Claude Code\n"
        "  arvix doctor                                   # проверка"
    )


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


def _service_active(name: str = "arvix-telegram") -> bool | None:
    """True/False — служба активна или нет; None — systemd недоступен."""
    try:
        done = subprocess.run(["systemctl", "--user", "is-active", "--quiet", name], capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.returncode == 0


def cmd_doctor(args: argparse.Namespace) -> None:
    from arvix.brain import Brain
    from arvix.remote import run_remote, target

    cfg = load_config()
    ok = True

    def check(name: str, passed: bool, hint: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        print(("OK  " if passed else "FAIL") + f" {name}" + ("" if passed or not hint else f" — {hint}"))

    check(f"конфиг {config_file()}", config_file().exists(), "arvix setup")
    remote = target()
    if remote:
        alive = run_remote("arvix_cli.py", ["--version"], "", timeout=15)
        check(f"сервер {remote[0]} (журнал там)", alive is not None, "ssh не проходит или Арвикс на сервере не установлен: deploy/sync-server.sh")
    else:
        check(f"база {cfg.db_path}", Core().store is not None)
    check(f"хранилище {cfg.vault}", bool(cfg.vault and cfg.vault.is_dir()), "arvix setup")
    template = cfg.vault_paths.get("daily_template")
    if cfg.vault and template:
        check(f"шаблон отчёта {template}", (cfg.vault / template).is_file(), "поправь [vault_paths] daily_template в config.toml")
    check(f"дом {cfg.home}", (cfg.home / ".arvix-home").exists(), "arvix init-home")
    check("claude CLI для головы", Brain(cfg).available(), "укажи [brain] claude_bin в config.toml")
    try:
        listed = subprocess.run(["claude", "plugin", "list"], capture_output=True, text=True, timeout=40, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        listed = None
    if listed is None:
        print("??   плагин arvix — не удалось спросить claude")
    else:
        check("плагин arvix в Claude Code", "arvix" in listed, "bash deploy/install.sh")
    tg = cfg.section("telegram")
    check("Telegram токен и владелец", bool(tg.get("token") and tg.get("owner_id")), "arvix setup --telegram --yes")
    if tg.get("token"):
        from arvix.telegram.api import TelegramAPI, TelegramError

        try:
            me = TelegramAPI(tg["token"], http_timeout=15).call("getMe")
            check(f"Telegram API: бот @{me.get('username')}", True)
        except TelegramError as exc:
            check("Telegram API", False, f"{exc} — сеть или токен")
    active = _service_active()
    if remote:
        check("бот на этой машине выключен (он на сервере)", active is not True, "systemctl --user disable --now arvix-telegram")
    elif tg.get("token") and active is not None:
        check("служба arvix-telegram запущена", active, "systemctl --user enable --now arvix-telegram")
    print(f"Данные: {data_dir()}" + (f" · режим: удалённый ({remote[0]})" if remote else ""))
    if not ok:
        sys.exit(1)


def cmd_statusline(args: argparse.Namespace) -> None:
    """Строка состояния для Claude Code. На stdin — JSON сессии (может не быть).
    В удалённом режиме ответ сервера кэшируется на минуту: ssh на каждый ответ — слишком часто."""
    from arvix.remote import run_remote, target
    from arvix.statusline import CACHE_TTL, render

    raw = "" if sys.stdin.isatty() else sys.stdin.read()
    try:
        session = json.loads(raw or "{}")
    except ValueError:
        session = {}
    if target():
        cache = data_dir() / "statusline.txt"
        try:
            if time.time() - cache.stat().st_mtime < CACHE_TTL:
                print(cache.read_text(encoding="utf-8").strip())
                return
        except OSError:
            pass
        line = run_remote("arvix_cli.py", ["statusline"], raw or "{}", timeout=8)
        if line is None:
            stale = cache.read_text(encoding="utf-8").strip() if cache.exists() else ""
            print(f"{stale} · ⚠ сервер недоступен" if stale else "Arvix: сервер недоступен")
            return
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(line, encoding="utf-8")
        print(line.strip())
        return
    try:
        print(render(_core(), session))
    except Exception as exc:  # noqa: BLE001 — строка состояния не должна падать
        print(f"Arvix: {exc}")


def cmd_remote(args: argparse.Namespace) -> None:
    """Удалённый режим: журнал и бот живут на сервере, ноутбук ходит туда по SSH."""
    from arvix.remote import DEFAULT_APP, run_remote, target

    if args.action == "show":
        found = target()
        print(f"Удалённый режим: {found[0]} ({found[1]})" if found else "Локальный режим: журнал на этой машине.")
        return
    if args.action == "off":
        write_user_config({"remote": {"host": ""}})
        print("Локальный режим. Бот здесь: systemctl --user enable --now arvix-telegram")
        return
    host = (args.host or "").strip()
    if not host:
        sys.exit("Формат: arvix remote set user@host")
    write_user_config({"remote": {"host": host, "app": DEFAULT_APP}})
    os.environ.pop("ARVIX_LOCAL", None)
    version = run_remote("arvix_cli.py", ["--version"], "", timeout=15)
    if version is None:
        sys.exit(f"Записал [remote] host = {host}, но сервер не ответил. Проверь `ssh {host}` и установку там: deploy/sync-server.sh {host}")
    print(f"Удалённый режим: {host}, на сервере Arvix {version.strip()}. Команды, MCP-сервер и хук теперь ходят туда.")
    if _service_active():
        print("⚠ Бот на этой машине ещё работает — выключи: systemctl --user disable --now arvix-telegram (два бота с одним токеном мешают друг другу).")


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
    p = add("setup", cmd_setup, "первичная настройка (без флагов — диалог)")
    p.add_argument("--vault", help="путь к Obsidian-хранилищу")
    p.add_argument("--tz", help="часовой пояс, например Europe/Moscow")
    p.add_argument("--home", help="дом Арвикса для Claude Code")
    p.add_argument("--telegram", dest="telegram", action="store_true", default=None, help="привязать Telegram-бота (токен — скрытый ввод)")
    p.add_argument("--no-telegram", dest="telegram", action="store_false", help="пропустить Telegram")
    p.add_argument("-y", "--yes", action="store_true", help="без вопросов: текущие значения и флаги")
    add("init-home", cmd_init_home, "создать или дополнить дом Арвикса для Claude Code")
    add("doctor", cmd_doctor, "проверка установки")
    add("statusline", cmd_statusline, "строка состояния для Claude Code (stdin — JSON сессии)")
    p = add("remote", cmd_remote, "удалённый режим: журнал на сервере (show / set user@host / off)")
    p.add_argument("action", choices=("show", "set", "off"))
    p.add_argument("host", nargs="?")
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
