"""Obsidian как второй мозг (07-SECOND-BRAIN, 03-DATA-MODEL §4).

Читать можно всё хранилище, писать — только в папку Arvix/: заметки человека
Арвикс не редактирует никогда. Поиск — по словам с грубой поддержкой русских
окончаний (общая основа слова); векторный индекс для сотен заметок не нужен.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

SKIP_DIRS = {".obsidian", ".trash", ".git", "node_modules", "Cache"}
MAX_READ_BYTES = 200_000


class VaultError(ValueError):
    pass


def _stems(query: str) -> list[str]:
    words = re.findall(r"[\wё]+", query.lower())
    return [w[: max(4, len(w) - 2)] if len(w) > 5 else w for w in words if len(w) >= 3]


def parse_frontmatter(text: str) -> dict[str, str]:
    """Плоский YAML-frontmatter (ключ: значение) — без зависимостей."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip().strip('"')
    return out


class Vault:
    def __init__(self, root: Path, arvix_folder: str = "Arvix"):
        self.root = Path(root).expanduser().resolve()
        self.arvix = self.root / arvix_folder
        if not self.root.is_dir():
            raise VaultError(f"Хранилище не найдено: {self.root}")

    def _inside(self, rel: str, base: Path) -> Path:
        path = (self.root / rel).resolve()
        if not path.is_relative_to(base):
            raise VaultError(f"Путь вне {base.relative_to(self.root.parent)}: {rel}")
        return path

    def files(self) -> list[Path]:
        out = []
        for path in self.root.rglob("*.md"):
            if not any(part in SKIP_DIRS for part in path.relative_to(self.root).parts):
                out.append(path)
        return out

    def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        stems = _stems(query)
        if not stems:
            return []
        results = []
        for path in self.files():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            low = text.lower()
            name = path.stem.lower()
            hits = {s: low.count(s) for s in stems}
            matched = sum(1 for count in hits.values() if count)
            if not matched:
                continue
            score = matched * 10 + sum(min(count, 10) for count in hits.values()) + sum(15 for s in stems if s in name)
            first = min((low.find(s) for s in stems if s in low), default=0)
            snippet = re.sub(r"\s+", " ", text[max(0, first - 80) : first + 220]).strip()
            heading = ""
            for line in text[:first].splitlines()[::-1]:
                if line.startswith("#"):
                    heading = line.lstrip("# ").strip()
                    break
            results.append({
                "path": str(path.relative_to(self.root)), "heading": heading, "snippet": snippet,
                "score": score, "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%d.%m.%Y"),
            })
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    def read(self, rel: str) -> str:
        path = self._inside(rel, self.root)
        if path.suffix.lower() not in (".md", ".txt") or not path.is_file():
            raise VaultError(f"Нет такой заметки: {rel}")
        data = path.read_bytes()[:MAX_READ_BYTES]
        return data.decode("utf-8", errors="replace")

    def write(self, rel: str, content: str, *, append: bool = False) -> str:
        """Пишет только внутрь Arvix/. Путь можно давать как «Daily/x.md» или «Arvix/Daily/x.md»."""
        rel = rel.strip().lstrip("/")
        if not rel.startswith(self.arvix.name + "/"):
            rel = f"{self.arvix.name}/{rel}"
        if not rel.endswith(".md"):
            rel += ".md"
        path = self._inside(rel, self.arvix)
        path.parent.mkdir(parents=True, exist_ok=True)
        if append and path.exists():
            with path.open("a", encoding="utf-8") as fh:
                fh.write(("\n" if not content.startswith("\n") else "") + content)
        else:
            path.write_text(content, encoding="utf-8")
        return str(path.relative_to(self.root))

    def inbox(self, text: str, now: datetime) -> str:
        return self.write("Inbox.md", f"- {now:%Y-%m-%d %H:%M} {text.strip()}\n", append=True)

    def daily_note_settings(self) -> tuple[str, str]:
        """Папка и формат ежедневных заметок из настроек Obsidian (core-плагин Daily notes)."""
        cfg = self.root / ".obsidian" / "daily-notes.json"
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            return data.get("folder", ""), data.get("format", "YYYY-MM-DD")
        except (OSError, ValueError):
            return "", "YYYY-MM-DD"

    def daily_note(self, d: date) -> dict[str, Any] | None:
        """Ежедневная заметка человека за дату: frontmatter (wake, sleep, focus_min…)
        читается детерминированно, без ИИ."""
        folder, fmt = self.daily_note_settings()
        name = fmt.replace("YYYY", f"{d.year:04d}").replace("MM", f"{d.month:02d}").replace("DD", f"{d.day:02d}")
        path = self.root / folder / f"{name}.md"
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
        return {"path": str(path.relative_to(self.root)), "fields": parse_frontmatter(text), "text": text[:4000]}
