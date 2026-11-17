"""Syncthing: хранилище Obsidian ноутбук ⇄ сервер (R9, D29).

Один файл, только стандартная библиотека и ни одного импорта из `arvix`: `deploy/syncthing-setup.sh`
передаёт его на сервер по ssh (`ssh HOST python3 - link … < arvix/syncthing.py`), поэтому серверу
не нужна свежая версия Арвикса. Этот же модуль читает `arvix doctor`.

Говорим с Syncthing только через его REST API на 127.0.0.1 с ключом из `config.xml`.
Конфликт Syncthing решает сам: обе версии остаются, вторая — файлом `*.sync-conflict-*`.
Арвикс их не сливает, а показывает в `doctor`: что оставить, решает человек.

Скрипт:
  python3 syncthing.py alive                      код 0 — Syncthing отвечает
  python3 syncthing.py prepare                    JSON: id устройства, хранилище, id папки на этот путь
  python3 syncthing.py link --folder F --peer ID --name N [--address tcp://ip:22000] [--private]
  python3 syncthing.py wait-peer --folder F [--timeout 60]
  python3 syncthing.py status [--folder F]        то же, что строки Syncthing в `arvix doctor`
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

FOLDER_ID = "arvix-vault"
FOLDER_LABEL = "Obsidian (Арвикс)"
# Не синхронизируются: раскладка окон Obsidian (своя на каждой машине), корзина Obsidian, кэш плагинов.
IGNORES = ("/.obsidian/workspace*", "/.trash", "Cache")
# Удалённое или заменённое с другой стороны лежит 30 дней в .stversions: удаления теперь переносятся.
VERSIONING = {"type": "trashcan", "params": {"cleanoutDays": "30"}}
CONFLICT_MARK = ".sync-conflict-"
SERVICE_DIRS = {".stversions", ".stfolder", ".trash", ".git", "node_modules"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

OK, FAIL, WARN, INFO = "OK", "FAIL", "WARN", "INFO"
SETUP_HINT = "bash deploy/syncthing-setup.sh arvix@HOST"


class SyncthingError(RuntimeError):
    pass


# --- где Syncthing и как с ним говорить ------------------------------------------


def config_xml_candidates(env: dict[str, str] | None = None) -> list[Path]:
    """Syncthing ≥ 1.27 и 2.x держат конфиг в ~/.local/state/syncthing, старые — в ~/.config/syncthing."""
    env = dict(os.environ) if env is None else env
    home = Path(env.get("HOME") or Path.home())
    out = []
    if env.get("STHOMEDIR"):
        out.append(Path(env["STHOMEDIR"]) / "config.xml")
    out.append(Path(env.get("XDG_STATE_HOME") or home / ".local/state") / "syncthing/config.xml")
    out.append(Path(env.get("XDG_CONFIG_HOME") or home / ".config") / "syncthing/config.xml")
    return out


def find_config_xml(env: dict[str, str] | None = None) -> Path | None:
    found = [p for p in config_xml_candidates(env) if p.is_file()]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


@dataclass
class Gui:
    address: str
    api_key: str
    tls: bool

    @property
    def host(self) -> str:
        host, _, _ = self.address.rpartition(":")
        return host.strip("[]")

    @property
    def port(self) -> int:
        return int(self.address.rpartition(":")[2] or 8384)

    @property
    def local(self) -> bool:
        return self.host in LOCAL_HOSTS

    @property
    def base_url(self) -> str:
        # Даже если GUI слушает 0.0.0.0, ходим на петлю: ключ API наружу не уходит.
        return f"{'https' if self.tls else 'http'}://127.0.0.1:{self.port}"


def read_gui(path: Path) -> Gui:
    try:
        gui = ET.parse(path).getroot().find("gui")
    except (OSError, ET.ParseError) as exc:
        raise SyncthingError(f"не читается {path}: {exc}") from exc
    if gui is None:
        raise SyncthingError(f"в {path} нет секции <gui>")
    address = (gui.findtext("address") or "127.0.0.1:8384").strip()
    if address.startswith("/") or address.startswith("unix"):
        raise SyncthingError(f"GUI Syncthing слушает сокет {address} — нужен 127.0.0.1:8384")
    key = (gui.findtext("apikey") or "").strip()
    if not key:
        raise SyncthingError(f"в {path} нет ключа API")
    return Gui(address=address, api_key=key, tls=gui.get("tls") == "true")


class Client:
    """REST API Syncthing через urllib. `call` — единственная точка выхода в сеть (тесты её подменяют)."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 10):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    @classmethod
    def from_gui(cls, gui: Gui) -> "Client":
        return cls(gui.base_url, gui.api_key)

    def call(self, method: str, path: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base_url + path, data=data, method=method,
                                     headers={"X-API-Key": self.api_key, "Content-Type": "application/json"})
        context = None
        if self.base_url.startswith("https"):
            context = ssl.create_default_context()      # свой самоподписанный сертификат на 127.0.0.1
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=context) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace").strip()[:200]
            raise SyncthingError(f"{method} {path}: HTTP {exc.code} {detail}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise SyncthingError(f"не отвечает {self.base_url}: {exc}") from exc
        return json.loads(raw) if raw.strip() else None


def connect(env: dict[str, str] | None = None) -> tuple[Client, Gui]:
    path = find_config_xml(env)
    if path is None:
        raise SyncthingError("config.xml Syncthing не найден — Syncthing ни разу не запускался")
    gui = read_gui(path)
    return Client.from_gui(gui), gui


# --- настройка (deploy/syncthing-setup.sh) ----------------------------------------


def same_path(a: str | Path, b: str | Path) -> bool:
    def norm(p: str | Path) -> Path:
        return Path(os.path.expanduser(str(p))).resolve()
    return norm(a) == norm(b)


def my_id(client: Client) -> str:
    return client.call("GET", "/rest/system/status")["myID"]


def prepare(client: Client, vault: Path) -> dict[str, Any]:
    """GUI — только на петле; какая папка Syncthing уже смотрит на это хранилище."""
    changes = []
    gui = client.call("GET", "/rest/config/gui") or {}
    address = str(gui.get("address") or "127.0.0.1:8384")
    host = address.rpartition(":")[0].strip("[]")
    if host not in LOCAL_HOSTS:
        port = address.rpartition(":")[2] or "8384"
        client.call("PATCH", "/rest/config/gui", {"address": f"127.0.0.1:{port}"})
        changes.append(f"GUI: {address} → 127.0.0.1:{port}")
    folder = next((f["id"] for f in client.call("GET", "/rest/config/folders") or []
                   if same_path(f.get("path", ""), vault)), None)
    return {"id": my_id(client), "vault": str(vault), "folder": folder, "changes": changes}


def link(client: Client, *, folder: str, vault: Path, peer: str, name: str,
         address: str = "", private: bool = False) -> list[str]:
    """Идемпотентно: устройство-напарник, общая папка на хранилище, игнор, корзина версий.
    Возвращает, что изменилось; второй запуск возвращает пустой список."""
    vault = Path(vault).expanduser()
    if not vault.is_dir():
        raise SyncthingError(f"нет хранилища {vault}")
    changes: list[str] = []
    me = my_id(client)
    if peer == me:
        raise SyncthingError("id напарника совпадает со своим — это одна и та же машина")

    devices = {d["deviceID"]: d for d in client.call("GET", "/rest/config/devices") or []}
    wanted = [address, "dynamic"] if address else ["dynamic"]
    if peer not in devices:
        client.call("POST", "/rest/config/devices", {"deviceID": peer, "name": name, "addresses": wanted})
        changes.append(f"устройство {name} добавлено")
    elif address and address not in (devices[peer].get("addresses") or []):
        merged = [address] + [a for a in devices[peer].get("addresses") or [] if a != address]
        client.call("PATCH", f"/rest/config/devices/{peer}", {"addresses": merged})
        changes.append(f"устройство {name}: адрес {address}")

    # Без маркера Syncthing считает папку пропавшей (отмонтированный диск) и встаёт в ошибку.
    marker = vault / ".stfolder"
    if not marker.exists():
        marker.mkdir()
        changes.append("маркер .stfolder создан")

    folders = {f["id"]: f for f in client.call("GET", "/rest/config/folders") or []}
    current = folders.get(folder)
    if current is None:
        other = next((f["id"] for f in folders.values() if same_path(f.get("path", ""), vault)), None)
        if other:
            raise SyncthingError(f"на {vault} уже смотрит папка {other} — запусти с --folder {other}")
        client.call("POST", "/rest/config/folders", {
            "id": folder, "label": FOLDER_LABEL, "path": str(vault), "type": "sendreceive",
            "fsWatcherEnabled": True, "rescanIntervalS": 3600,
            "devices": [{"deviceID": me}, {"deviceID": peer}], "versioning": VERSIONING,
        })
        changes.append(f"папка {folder} → {vault}")
    else:
        if not same_path(current.get("path", ""), vault):
            raise SyncthingError(f"папка {folder} смотрит на {current.get('path')}, а хранилище — {vault}")
        shared = [d.get("deviceID") for d in current.get("devices") or []]
        if peer not in shared:
            devs = [d for d in current.get("devices") or []] + [{"deviceID": peer}]
            client.call("PATCH", f"/rest/config/folders/{folder}", {"devices": devs})
            changes.append(f"папка {folder}: общая с {name}")
        if not (current.get("versioning") or {}).get("type"):
            client.call("PATCH", f"/rest/config/folders/{folder}", {"versioning": VERSIONING})
            changes.append(f"папка {folder}: корзина версий 30 дней")
        if current.get("paused"):
            client.call("PATCH", f"/rest/config/folders/{folder}", {"paused": False})
            changes.append(f"папка {folder}: снята с паузы")

    query = urllib.parse.urlencode({"folder": folder})
    have = (client.call("GET", f"/rest/db/ignores?{query}") or {}).get("ignore") or []
    missing = [p for p in IGNORES if p not in have]
    if missing:
        client.call("POST", f"/rest/db/ignores?{query}", {"ignore": list(have) + missing})
        changes.append("игнор: " + ", ".join(missing))

    if private:
        # Сервер с белым IP: ноутбук сам приходит на tcp://IP:22000. Ни глобального анонса, ни ретрансляторов —
        # id и адрес сервера не уходят на серверы Syncthing.
        options = client.call("GET", "/rest/config/options") or {}
        off = {k: False for k in ("globalAnnounceEnabled", "relaysEnabled", "natEnabled") if options.get(k)}
        if off:
            client.call("PATCH", "/rest/config/options", off)
            changes.append("анонс и ретрансляторы выключены")
    return changes


# --- проверка (arvix doctor) ------------------------------------------------------


def conflicts(vault: Path, limit: int = 200) -> list[str]:
    """Файлы `*.sync-conflict-*` в хранилище — вторые версии, которые Syncthing сохранил при конфликте."""
    vault = Path(vault).expanduser()
    out: list[str] = []
    if not vault.is_dir():
        return out
    for path in vault.rglob(f"*{CONFLICT_MARK}*"):
        rel = path.relative_to(vault)
        if any(part in SERVICE_DIRS for part in rel.parts[:-1]) or not path.is_file():
            continue
        out.append(str(rel))
        if len(out) >= limit:
            break
    return sorted(out)


STATE_RU = {"idle": "синхронизирована", "scanning": "сканирует", "syncing": "синхронизирует",
            "sync-preparing": "готовит синхронизацию", "scan-waiting": "ждёт сканирования",
            "sync-waiting": "ждёт синхронизации", "cleaning": "чистит версии", "error": "ошибка"}


def doctor(vault: Path, folder: str, client: Client | None = None, gui: Gui | None = None) -> list[tuple[str, str, str]]:
    """Строки для `arvix doctor`: (OK|FAIL|WARN|INFO, что, подсказка)."""
    lines: list[tuple[str, str, str]] = []
    if client is None:
        try:
            client, gui = connect()
        except SyncthingError as exc:
            return [(FAIL, "Syncthing", f"{exc}. {SETUP_HINT}")]
    where = f"127.0.0.1:{gui.port}" if gui else client.base_url
    try:
        client.call("GET", "/rest/system/ping")
    except SyncthingError:
        return [(FAIL, f"Syncthing запущен ({where})", "systemctl --user enable --now syncthing")]
    lines.append((OK, f"Syncthing запущен ({where})", ""))
    if gui is not None and not gui.local:
        lines.append((FAIL, f"GUI Syncthing только на 127.0.0.1 (сейчас {gui.address})", SETUP_HINT))
    try:
        me = my_id(client)
        found = next((f for f in client.call("GET", "/rest/config/folders") or [] if f.get("id") == folder), None)
        if found is None:
            return lines + [(FAIL, f"папка Syncthing {folder}", f"нет такой папки — {SETUP_HINT}")]
        if not same_path(found.get("path", ""), vault):
            return lines + [(FAIL, f"папка {folder} = хранилище", f"Syncthing: {found.get('path')}, конфиг: {vault}")]
        if found.get("paused"):
            return lines + [(FAIL, f"папка {folder}", "на паузе — сними в GUI или перезапусти setup")]
        query = urllib.parse.urlencode({"folder": folder})
        status = client.call("GET", f"/rest/db/status?{query}") or {}
        state = str(status.get("state") or "?")
        errors = int(status.get("errors") or 0) + int(status.get("pullErrors") or 0)
        if state == "error" or errors:
            reason = status.get("error") or (f"{errors} файлов не синхронизируются" if errors else state)
            lines.append((FAIL, f"папка {folder}: {STATE_RU.get(state, state)}", f"{reason} — подробности в GUI {where}"))
        else:
            lines.append((OK, f"папка {folder}: {STATE_RU.get(state, state)}", ""))
        peers = [d.get("deviceID") for d in found.get("devices") or [] if d.get("deviceID") != me]
        if not peers:
            lines.append((WARN, f"папка {folder} ни с кем не общая", SETUP_HINT))
            return lines
        names = {d["deviceID"]: d.get("name") or d["deviceID"][:7] for d in client.call("GET", "/rest/config/devices") or []}
        links = (client.call("GET", "/rest/system/connections") or {}).get("connections") or {}
        for peer in peers:
            name = names.get(peer, peer[:7])
            if (links.get(peer) or {}).get("connected"):
                lines.append((OK, f"на связи: {name}", ""))
            else:
                lines.append((WARN, f"не на связи: {name}",
                              "выключен? на сервере открыт 22000/tcp? старое устройство — убери его из папки в GUI"))
    except SyncthingError as exc:
        lines.append((FAIL, "Syncthing API", str(exc)))
    return lines


def report(vault: Path | None, sync: dict[str, Any], remote: bool,
           probe: Callable[[Path, str], list[tuple[str, str, str]]] = doctor) -> list[tuple[str, str, str]]:
    """Всё про синхронизацию хранилища для `arvix doctor`. `sync` — секция `[sync]` конфига."""
    if not vault:
        return []
    mode = str(sync.get("vault") or "rsync")
    lines: list[tuple[str, str, str]] = []
    if mode == "syncthing":
        lines += probe(vault, str(sync.get("folder") or FOLDER_ID))
    elif remote:
        lines.append((INFO, "хранилище: rsync раз в 10 минут, правки с двух сторон могут теряться", SETUP_HINT))
    found = conflicts(vault)
    if found:
        shown = ", ".join(found[:3]) + (f" и ещё {len(found) - 3}" if len(found) > 3 else "")
        lines.append((WARN, f"конфликтов Syncthing: {len(found)} — {shown}",
                      "сравни с оригиналом, перенеси нужное, файл *.sync-conflict-* удали"))
    return lines


# --- скрипт ----------------------------------------------------------------------


def arvix_vault(env: dict[str, str] | None = None) -> Path:
    env = dict(os.environ) if env is None else env
    base = env.get("ARVIX_CONFIG_DIR") or str(Path(env.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "arvix")
    path = Path(base).expanduser() / "config.toml"
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8")).get("vault")
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SyncthingError(f"не читается {path}: {exc}") from exc
    if not value:
        raise SyncthingError(f"в {path} нет vault — arvix setup")
    return Path(value).expanduser()


def wait_client(timeout: float = 60) -> Client:
    """Только что запущенный Syncthing пишет config.xml и поднимает API не сразу."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            client, _ = connect()
            client.call("GET", "/rest/system/ping")
            return client
        except SyncthingError:
            if time.monotonic() > deadline:
                raise
            time.sleep(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="syncthing.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("alive")
    sub.add_parser("prepare")
    p = sub.add_parser("link")
    p.add_argument("--folder", required=True)
    p.add_argument("--peer", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--address", default="")
    p.add_argument("--private", action="store_true")
    p = sub.add_parser("wait-peer")
    p.add_argument("--folder", required=True)
    p.add_argument("--timeout", type=float, default=60)
    p = sub.add_parser("status")
    p.add_argument("--folder", default=FOLDER_ID)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "alive":
            client, _ = connect()
            client.call("GET", "/rest/system/ping")
            return 0
        if args.cmd == "prepare":
            print(json.dumps(prepare(wait_client(), arvix_vault()), ensure_ascii=False))
            return 0
        if args.cmd == "link":
            changes = link(wait_client(), folder=args.folder, vault=arvix_vault(), peer=args.peer,
                           name=args.name, address=args.address, private=args.private)
            print("\n".join(changes) if changes else "без изменений")
            return 0
        if args.cmd == "wait-peer":
            deadline = time.monotonic() + args.timeout
            while True:
                lines = doctor(arvix_vault(), args.folder)
                if any(s == OK and t.startswith("на связи") for s, t, _ in lines) or time.monotonic() > deadline:
                    break
                time.sleep(3)
        else:
            lines = doctor(arvix_vault(), args.folder)
        for status, text, hint in lines:
            print(f"{status:<4} {text}" + (f" — {hint}" if hint and status != OK else ""))
        return 1 if any(s == FAIL for s, _, _ in lines) else 0
    except SyncthingError as exc:
        print(f"Syncthing: {exc}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, KeyError, ValueError) as exc:
        print(f"Syncthing: неожиданный ответ: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
