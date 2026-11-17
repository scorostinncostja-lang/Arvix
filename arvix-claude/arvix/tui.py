"""`arvix` в терминале — то же приложение, что в Telegram и на телефоне (05-INTERFACES §7.5).

Слева — день: задачи, таймер, цифры. Справа — разговор с Арвиксом. Внизу — строка ввода:
пишешь как в Telegram, Enter — отправить. Всё обновляется само (поток /api/stream).

Подключение: бот на этой машине — 127.0.0.1:<port>; удалённый режим ([remote] host) —
SSH-туннель к серверу, ключ приложения забирается оттуда же по ssh. Никаких паролей в чате.

Клавиши: ↑/↓ — выбрать задачу · Ctrl+D — сделано · Ctrl+S — начать · Ctrl+P — перенести на 30 мин
Ctrl+F — фокус 25 мин · Ctrl+X — стоп фокус · Ctrl+N — новая задача (в строке: «Физика 18:00 60м»)
PgUp/PgDn — листать разговор · Ctrl+R — обновить · Ctrl+C или Ctrl+Q — выход.
"""

from __future__ import annotations

import curses
import json
import locale
import os
import shutil
import socket
import subprocess
import sys
import textwrap
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

STATUS_ICON = {"planned": "○", "active": "▶", "done": "✓", "failed": "✗", "debt": "!", "cancelled": "–", "written_off": "–"}


class Client:
    def __init__(self, base: str, token: str):
        self.base = base.rstrip("/")
        self.token = token

    def call(self, path: str, body: Any = None, timeout: float = 40) -> Any:
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        request = urllib.request.Request(self.base + "/api/" + path, data=data, method="POST" if data is not None else "GET",
                                         headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                message = json.loads(exc.read() or b"{}").get("error")
            except ValueError:
                message = None
            raise RuntimeError(message or f"HTTP {exc.code}") from exc

    def stream(self, on_change: Any, stop: threading.Event) -> None:
        while not stop.is_set():
            request = urllib.request.Request(self.base + "/api/stream", headers={"Authorization": f"Bearer {self.token}"})
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    for raw in response:
                        if stop.is_set():
                            return
                        line = raw.decode("utf-8", "replace").strip()
                        if line.startswith("data: "):
                            on_change(json.loads(line[6:]))
            except (OSError, ValueError, urllib.error.URLError):
                stop.wait(3)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def connect() -> tuple[Client, subprocess.Popen[bytes] | None]:
    """Локально — прямо к службе; в удалённом режиме — туннель ssh к серверу."""
    from arvix.config import load_config
    from arvix.remote import SSH_OPTS, run_remote, target

    cfg = load_config()
    port = int(cfg.section("web").get("port") or 8787)
    remote = target()
    if not remote:
        from arvix.core import Core
        from arvix.web.auth import app_token

        core = Core(cfg)
        token = app_token(core)
        core.close()
        return Client(f"http://127.0.0.1:{port}", token), None
    host = remote[0]
    token = (run_remote("arvix_cli.py", ["app-token"], "", timeout=20) or "").strip()
    if not token:
        sys.exit(f"Сервер {host} не отдал ключ приложения. Обновлён ли он (deploy/sync-server.sh)? Работает ли ssh {host}?")
    local = free_port()
    ssh_opts = [o for o in SSH_OPTS if o != "-T"]
    tunnel = subprocess.Popen(["ssh", *ssh_opts, "-N", "-L", f"{local}:127.0.0.1:{port}", host],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client = Client(f"http://127.0.0.1:{local}", token)
    for _ in range(50):  # ждём туннель до 10 с
        try:
            client.call("state", timeout=3)
            return client, tunnel
        except (RuntimeError, OSError):
            if tunnel.poll() is not None:
                break
            time.sleep(0.2)
    tunnel.terminate()
    sys.exit(f"Не достучался до приложения на {host}: служба бота запущена? (systemctl --user status arvix-telegram)")


class TUI:
    def __init__(self, client: Client):
        self.client = client
        self.state: dict[str, Any] = {}
        self.messages: list[dict[str, Any]] = []
        self.thinking = ""
        self.selected = 0
        self.scroll = 0
        self.input = ""
        self.mode = "chat"  # chat | add | report
        self.report_for: dict[str, Any] | None = None
        self.notice = ""
        self.notice_at = 0.0
        self.dirty = threading.Event()
        self.wanted = threading.Event()  # один поток обновления: ответы не обгоняют друг друга
        self.stop = threading.Event()
        self.lock = threading.Lock()

    # --- данные ----------------------------------------------------------------------------

    def refresh(self) -> None:
        try:
            state = self.client.call("state")
            messages = self.client.call("messages")
        except (RuntimeError, OSError) as exc:
            self.say(f"нет связи: {exc}")
            return
        with self.lock:
            self.state = state
            self.messages = messages.get("messages") or []
            self.thinking = messages.get("thinking") or state.get("thinking") or ""
        self.dirty.set()

    def on_change(self, event: dict[str, Any]) -> None:
        self.thinking = event.get("thinking") or ""
        self.wanted.set()

    def refresher(self) -> None:
        while not self.stop.is_set():
            if self.wanted.wait(1):
                self.wanted.clear()
                self.refresh()

    def say(self, text: str) -> None:
        self.notice, self.notice_at = text, time.monotonic()
        self.dirty.set()

    def tasks(self) -> list[dict[str, Any]]:
        return list(self.state.get("tasks") or []) + list(self.state.get("debts") or [])

    def act(self, path: str, body: dict[str, Any], ok: str) -> None:
        def run() -> None:
            try:
                result = self.client.call(path, body)
                extra = f" +{result['xp']} XP" if result.get("xp") else ""
                warn = " ⚠ " + "; ".join(result["warnings"]) if result.get("warnings") else ""
                self.say(ok + extra + warn)
            except (RuntimeError, OSError) as exc:
                self.say(f"✗ {exc}")
            self.wanted.set()
        threading.Thread(target=run, daemon=True).start()

    def selected_task(self) -> dict[str, Any] | None:
        tasks = self.tasks()
        return tasks[self.selected] if 0 <= self.selected < len(tasks) else None

    def submit(self) -> None:
        text = self.input.strip()
        self.input = ""
        if not text:
            return
        if self.mode == "add":
            self.mode = "chat"
            self.add_task(text)
            return
        if self.mode == "report" and self.report_for:
            task, self.mode, self.report_for = self.report_for, "chat", None
            self.act(f"tasks/{task['id']}/done", {"report": text}, f"✓ {task['title']}")
            return
        self.messages.append({"who": "me", "text": text, "at": datetime.now().astimezone().isoformat(), "channel": "terminal"})
        self.thinking = "думаю"
        self.scroll = 0

        def run() -> None:
            try:
                self.client.call("message", {"text": text})
            except (RuntimeError, OSError) as exc:
                self.say(f"✗ {exc}")
        threading.Thread(target=run, daemon=True).start()

    def add_task(self, text: str) -> None:
        from arvix.telegram.bot import parse_quick_task

        fields = parse_quick_task(text)
        if not fields.get("title"):
            self.say("Нужно название: «Физика 18:00 60м»")
            return
        body = {"title": fields["title"], "start": fields.get("start"), "duration_min": fields.get("duration_min") or 60,
                "importance": fields.get("importance") or 3, "deep_work": bool(fields.get("deep_work")),
                "date": fields.get("day"), "sphere": "project"}
        self.act("tasks", body, f"+ {fields['title']}")

    # --- экран -------------------------------------------------------------------------------

    def draw(self, scr: Any, full: bool = False) -> None:
        # Новые данные — полная перерисовка: иначе оптимизация curses (сдвиг строк) оставляет
        # обрывки старых сообщений в части терминалов. Тик таймера — лёгкая.
        scr.clear() if full else scr.erase()
        height, width = scr.getmaxyx()
        if height < 12 or width < 50:
            scr.addstr(0, 0, "Окно маловато: нужно хотя бы 50×12")
            scr.refresh()
            return
        with self.lock:
            state, messages, thinking = self.state, list(self.messages), self.thinking
        left_w = max(34, min(52, width * 2 // 5))
        self.draw_top(scr, state, width)
        self.draw_day(scr, state, 2, 0, height - 4, left_w)
        for y in range(1, height - 2):
            put(scr, y, left_w, "│", curses.A_DIM)
        self.draw_chat(scr, messages, thinking, 2, left_w + 2, height - 4, width - left_w - 3)
        self.draw_input(scr, height, width)
        scr.refresh()

    def draw_top(self, scr: Any, state: dict[str, Any], width: int) -> None:
        if not state:
            put(scr, 0, 1, "Арвикс · подключаюсь…", curses.A_BOLD)
            return
        now = datetime.fromisoformat(state["now"])
        head = f" Арвикс · {state.get('weekday', '')} {now:%d.%m} · {plain(state.get('mode_label', ''))}"
        stats = state.get("stats")
        if stats:
            head += f" · {stats['done']}/{stats['total']} · HP {stats['hp']} · ур.{stats['level']} {stats['xp_into']}/{stats['xp_need']} XP · серия {stats['streak']}"
        focus = state.get("focus")
        if focus:
            left = max(0, int((datetime.fromisoformat(focus["until"]) - datetime.now().astimezone()).total_seconds()))
            head += f" · ◎ {left // 60:02d}:{left % 60:02d}"
        put(scr, 0, 0, pad(cut(head, width - 1), width - 1), curses.A_REVERSE | curses.A_BOLD)

    def draw_day(self, scr: Any, state: dict[str, Any], top: int, left: int, height: int, width: int) -> None:
        y = top
        if state.get("gentle"):
            for line in textwrap.wrap(state.get("note") or "", width - 2):
                put(scr, y, left + 1, line)
                y += 1
            y += 1
        focus = state.get("focus")
        if focus:
            put(scr, y, left + 1, f"◎ Фокус {focus['minutes']} мин до {focus['until'][11:16]}", curses.A_BOLD)
            y += 1
            if focus.get("title"):
                put(scr, y, left + 3, cut(focus["title"], width - 4), curses.A_DIM)
                y += 1
            y += 1
        put(scr, y, left + 1, "СЕГОДНЯ", curses.A_DIM | curses.A_BOLD)
        y += 1
        tasks = self.tasks()
        if not tasks:
            put(scr, y, left + 1, "задач нет · Ctrl+N — добавить", curses.A_DIM)
        self.selected = min(self.selected, max(0, len(tasks) - 1))
        for i, task in enumerate(tasks):
            if y >= top + height - 1:
                break
            icon = STATUS_ICON.get(task["status"], "?")
            line = plain(f"{icon} {task.get('start') or '--:--'} {task['title']}")
            meta = f" {task['duration_min']}м" + (" ★" if task["importance"] >= 4 else "")
            attr = curses.A_REVERSE if i == self.selected else (curses.A_DIM if not task["open"] and task["status"] != "debt" else 0)
            if task["status"] == "active" and i != self.selected:
                attr |= curses.A_BOLD
            put(scr, y, left, pad(cut(" " + line, width - len(meta) - 1), width - len(meta) - 1) + meta, attr)
            y += 1
        tomorrow = state.get("tomorrow") or []
        if tomorrow and y < top + height - 3:
            y += 1
            put(scr, y, left + 1, "ЗАВТРА", curses.A_DIM | curses.A_BOLD)
            y += 1
            for task in tomorrow:
                if y >= top + height - 1:
                    break
                put(scr, y, left + 1, cut(plain(f"{task.get('start') or '--:--'} {task['title']}"), width - 2), curses.A_DIM)
                y += 1

    def draw_chat(self, scr: Any, messages: list[dict[str, Any]], thinking: str, top: int, left: int, height: int, width: int) -> None:
        lines: list[tuple[str, int]] = []
        last_day = ""
        for message in messages:
            at = datetime.fromisoformat(message["at"])
            day = f"{at:%d.%m}"
            if day != last_day:
                lines.append((f"── {day} ──".center(width), curses.A_DIM))
                last_day = day
            mine = message["who"] == "me"
            who = "ты" if mine else "Арвикс"
            lines.append((f"{who} · {at:%H:%M}", curses.A_DIM | (0 if mine else curses.A_BOLD)))
            text = plain(message["text"].replace("**", ""))
            for para in text.split("\n"):
                for line in textwrap.wrap(para, width - 4) or [""]:
                    lines.append(("  " + line, curses.color_pair(2) if mine and curses.has_colors() else 0))
            buttons = [plain(b[0]) for row in message.get("buttons") or [] for b in row]
            if buttons:
                lines.append(("  [" + "] [".join(buttons) + "]", curses.A_DIM))
            lines.append(("", 0))
        if thinking:
            lines.append((f"Арвикс {thinking}…", curses.A_DIM))
        self.scroll = max(0, min(self.scroll, len(lines) - height))
        visible = lines[max(0, len(lines) - height - self.scroll): len(lines) - self.scroll]
        for i, (line, attr) in enumerate(visible):
            put(scr, top + i, left, cut(line, width), attr)

    def draw_input(self, scr: Any, height: int, width: int) -> None:
        hint = "Enter — отправить · ↑↓ задача · ^D сделано · ^S начать · ^P +30м · ^F фокус · ^X стоп · ^N задача · ^Q выход"
        if self.notice and time.monotonic() - self.notice_at < 6:
            hint = self.notice
        put(scr, height - 2, 0, pad(cut(" " + hint, width - 1), width - 1), curses.A_DIM)
        prompt = {"add": "новая задача › ", "report": "отчёт › "}.get(self.mode, "› ")
        visible = (prompt + self.input)[-(width - 2):]
        put(scr, height - 1, 0, visible.ljust(width - 1), curses.A_BOLD)
        try:
            scr.move(height - 1, min(len(visible), width - 2))
        except curses.error:
            pass

    # --- цикл --------------------------------------------------------------------------------

    def handle(self, key: Any) -> bool:
        task = self.selected_task()
        if key in ("\x03", "\x11"):  # Ctrl+C, Ctrl+Q
            return False
        if key == "\x1b":
            self.mode, self.input, self.report_for = "chat", "", None
        elif key in ("\n", "\r", curses.KEY_ENTER):
            self.submit()
        elif key in ("\x7f", "\b", curses.KEY_BACKSPACE):
            self.input = self.input[:-1]
        elif key == curses.KEY_UP:
            self.selected = max(0, self.selected - 1)
        elif key == curses.KEY_DOWN:
            self.selected = min(len(self.tasks()) - 1, self.selected + 1)
        elif key == curses.KEY_PPAGE:
            self.scroll += 10
        elif key == curses.KEY_NPAGE:
            self.scroll = max(0, self.scroll - 10)
        elif key == "\x04" and task:  # Ctrl+D
            if task.get("proof") and task["proof"] != "confirm":
                self.mode, self.input, self.report_for = "report", "", task
                self.say(f"Отчёт по «{task['title']}»: что именно сделано? Enter — записать, Esc — отмена")
            else:
                self.act(f"tasks/{task['id']}/done", {}, f"✓ {task['title']}")
        elif key == "\x13" and task:  # Ctrl+S
            self.act(f"tasks/{task['id']}/start", {}, f"▶ {task['title']}")
        elif key == "\x10" and task:  # Ctrl+P
            self.act(f"tasks/{task['id']}/defer", {"minutes": 30}, f"⏳ {task['title']} +30 мин")
        elif key == "\x06":  # Ctrl+F
            self.act("focus", {"minutes": 25, "task": task["id"] if task and task["open"] else None}, "🎯 фокус 25 мин")
        elif key == "\x18":  # Ctrl+X
            self.act("focus/stop", {}, "⏹ фокус остановлен")
        elif key == "\x0e":  # Ctrl+N
            self.mode, self.input = "add", ""
            self.say("Новая задача: «Физика 18:00 60м !4 deep» · Esc — отмена")
        elif key == "\x12":  # Ctrl+R
            self.wanted.set()
        elif isinstance(key, str) and key.isprintable():
            self.input += key
        return True

    def run(self, scr: Any) -> None:
        curses.raw()
        curses.use_default_colors()
        if curses.has_colors():
            curses.init_pair(2, curses.COLOR_CYAN, -1)
        scr.timeout(250)
        scr.keypad(True)
        self.wanted.set()
        threading.Thread(target=self.refresher, daemon=True).start()
        threading.Thread(target=self.client.stream, args=(self.on_change, self.stop), daemon=True).start()
        tick = 0.0
        while True:
            if self.dirty.is_set() or time.monotonic() - tick > 1:
                full = self.dirty.is_set()
                self.dirty.clear()
                tick = time.monotonic()
                self.draw(scr, full=full)
            try:
                key = scr.get_wch()
            except curses.error:
                continue
            if key == curses.KEY_RESIZE:
                self.dirty.set()
                continue
            if not self.handle(key):
                break
            self.draw(scr)
        self.stop.set()


def put(scr: Any, y: int, x: int, text: str, attr: int = 0) -> None:
    height, width = scr.getmaxyx()
    if 0 <= y < height and 0 <= x < width:
        try:
            scr.addnstr(y, x, text, max(0, width - x - 1), attr)
        except curses.error:
            pass


def cols(text: str) -> int:
    """Ширина в колонках терминала: эмодзи и иероглифы — две."""
    return sum(0 if unicodedata.combining(ch) or ch in "\ufe0f\u200d" else 2 if unicodedata.east_asian_width(ch) in "WF" else 1
               for ch in text)


def cut(text: str, width: int) -> str:
    if cols(text) <= width:
        return text
    out, used = "", 0
    for ch in text:
        w = cols(ch)
        if used + w > width - 1:
            break
        out, used = out + ch, used + w
    return out + "…"


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - cols(text))


def plain(text: str) -> str:
    """Без эмодзи: их ширину терминал и curses считают по-разному, и строки съезжают.
    Простые символы (✓ ○ ▶ —) остаются."""
    out = "".join(ch for ch in text if ord(ch) < 0x1F000 and ch not in "\ufe0f\u200d")
    return " ".join(out.split(" ")).replace("  ", " ").strip() if out != text else text


def main() -> None:
    if not sys.stdout.isatty():
        sys.exit("arvix без аргументов — приложение для терминала. Команды: arvix --help")
    locale.setlocale(locale.LC_ALL, "")
    os.environ.setdefault("ESCDELAY", "25")
    if shutil.get_terminal_size().columns < 50:
        sys.exit("Терминал уже 50 колонок — расширь окно.")
    client, tunnel = connect()
    try:
        curses.wrapper(TUI(client).run)
    finally:
        if tunnel is not None:
            tunnel.terminate()
