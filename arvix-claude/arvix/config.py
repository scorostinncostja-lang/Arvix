"""Конфиг и пути.

Данные живут вне плагина (~/.local/share/arvix): ${CLAUDE_PLUGIN_DATA} удаляется
вместе с плагином, а журнал событий вечен (00-VISION П6).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULTS_FILE = PACKAGE_DIR / "defaults.toml"


def config_dir() -> Path:
    if os.environ.get("ARVIX_CONFIG_DIR"):
        return Path(os.environ["ARVIX_CONFIG_DIR"]).expanduser()
    return Path(os.environ.get("XDG_CONFIG_HOME") or "~/.config").expanduser() / "arvix"


def data_dir() -> Path:
    if os.environ.get("ARVIX_DATA_DIR"):
        return Path(os.environ["ARVIX_DATA_DIR"]).expanduser()
    return Path(os.environ.get("XDG_DATA_HOME") or "~/.local/share").expanduser() / "arvix"


def config_file() -> Path:
    return config_dir() / "config.toml"


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def parse_hhmm(value: str | None) -> time | None:
    if not value or value == "auto":
        return None
    hours, _, minutes = str(value).strip().partition(":")
    return time(int(hours) % 24, int(minutes or 0))


@dataclass
class Config:
    raw: dict[str, Any]

    def section(self, name: str) -> dict[str, Any]:
        return self.raw.get(name) or {}

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.raw.get("timezone") or "Europe/Moscow")
        except ZoneInfoNotFoundError:
            return ZoneInfo("Europe/Moscow")

    @property
    def vault(self) -> Path | None:
        value = self.raw.get("vault")
        return Path(value).expanduser() if value else None

    @property
    def home(self) -> Path:
        return Path(self.raw.get("home") or "~/Arvix").expanduser()

    @property
    def arvix_folder(self) -> str:
        return self.raw.get("arvix_folder") or "Arvix"

    @property
    def db_path(self) -> Path:
        return data_dir() / "arvix.db"

    def schedule(self, key: str) -> str:
        return str(self.section("schedule").get(key, ""))

    def model(self, role: str) -> str | None:
        return (self.section("roles").get(role) or {}).get("model") or None

    def mech(self, key: str, default: Any = None) -> Any:
        return self.section("mechanics").get(key, default)


def load_config() -> Config:
    raw = tomllib.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))
    user = config_file()
    if user.exists():
        raw = _merge(raw, tomllib.loads(user.read_text(encoding="utf-8")))
    return Config(raw)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _toml_lines(data: dict[str, Any], prefix: str = "") -> list[str]:
    scalars = [(k, v) for k, v in data.items() if not isinstance(v, dict)]
    tables = [(k, v) for k, v in data.items() if isinstance(v, dict)]
    lines = [f"{k} = {_toml_value(v)}" for k, v in scalars]
    for key, table in tables:
        name = f"{prefix}{key}"
        if any(not isinstance(v, dict) for v in table.values()):
            lines += ["", f"[{name}]"]
        lines += _toml_lines(table, prefix=f"{name}.")
    return lines


def write_user_config(updates: dict[str, Any]) -> Path:
    """tomllib умеет только читать, поэтому пишем TOML сами. Файл содержит токен
    бота — права 0600."""
    path = config_file()
    current = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    merged = _merge(current, updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "# Конфиг Arvix. Пишется командой `arvix setup`, можно править руками.\n"
    body += "\n".join(_toml_lines(merged)).strip() + "\n"
    path.write_text(body, encoding="utf-8")
    path.chmod(0o600)
    return path
