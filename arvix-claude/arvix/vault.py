"""Obsidian как второй мозг (06-LEARNING §7, 03-DATA-MODEL §5).

Arvix работает прямо в структуре хранилища (цели, роадмапы, конспекты, ежедневные
отчёты — по местам из [vault_paths]), а не в отдельной папке. Правила записи — код:

- создать новую заметку можно в любой папке, кроме служебных;
- в чужую заметку — только дописать в конец или обновить свой помеченный блок
  %% arvix:имя %% … %% /arvix:имя %% (комментарий Obsidian — человеку не виден), текст вне блока не трогается;
- перезаписать целиком — только свою заметку, которую человек с тех пор не менял
  (сверка хэша), либо по явному согласию (force); перед перезаписью — бэкап;
- удалять Arvix не умеет вообще;
- человек правит свои заметки из приложения (save): запись только если файл не менялся
  с момента открытия (сверка хэша), иначе — конфликт с обеими версиями, без молчаливой потери.

Поиск — по словам с грубой поддержкой русских окончаний (общая основа слова).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

SKIP_DIRS = {".obsidian", ".trash", ".git", "node_modules", "Cache"}
TEMPLATE_DIR_NAMES = ("templates", "template", "шаблоны")
MAX_READ_BYTES = 200_000
ASSET_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
               ".svg": "image/svg+xml", ".pdf": "application/pdf", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".mp4": "video/mp4"}
DEFAULT_PATHS = {
    "profile": "05_System/Профиль Arvix.md",
    "goals": "05_System/Цели",
    "roadmaps": "03_Resources/Роадмапы",
    "notes": "03_Resources/Обучение",
    "weekly": "05_System/Недели",
    "inbox": "05_System/Inbox.md",
    "system": "05_System/Арвикс",
    "daily": "",
    "daily_template": "",
    "files": "00_Inbox/Файлы",
}


class VaultError(ValueError):
    pass


class VaultConflict(VaultError):
    """Файл изменился после того, как человек его открыл."""

    def __init__(self, path: str, current: str):
        super().__init__(f"«{path}» изменилась, пока ты её правил (ноутбук или синхронизация). Сравни и выбери версию.")
        self.path = path
        self.current = current


def detect_paths(root: Path) -> dict[str, str]:
    """Где в этом хранилище уже лежат роадмапы, Inbox, шаблон отчёта — чтобы `arvix setup`
    подставил реальные места, а не папки по умолчанию. Только то, что нашлось."""
    root = Path(root).expanduser().resolve()
    found: dict[str, str] = {}
    if not root.is_dir():
        return found
    dirs: list[Path] = []
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if len(rel.parts) > 3 or any(part in SKIP_DIRS for part in rel.parts):
            continue
        (dirs if path.is_dir() else files).append(path)
    for path in dirs:
        name = path.name.lower()
        if "roadmaps" not in found and ("роадмап" in name or "roadmap" in name):
            found["roadmaps"] = str(path.relative_to(root))
        if "weekly" not in found and ("недел" in name or "weekly" in name):
            found["weekly"] = str(path.relative_to(root))
        if "goals" not in found and (name.startswith("цели") or "goals" in name):
            found["goals"] = str(path.relative_to(root))
    for path in files:
        stem = path.stem.lower()
        if path.suffix == ".md" and "inbox" not in found and stem in ("inbox", "входящие", "00_inbox", "inbox — входящие"):
            found["inbox"] = str(path.relative_to(root))
    # Шаблон ежедневного отчёта: настройка Obsidian, а если она указывает в пустоту —
    # файл в папке шаблонов с подходящим именем.
    template = ""
    try:
        template = json.loads((root / ".obsidian" / "daily-notes.json").read_text(encoding="utf-8")).get("template") or ""
    except (OSError, ValueError):
        pass
    if template and not (root / (template if template.endswith(".md") else f"{template}.md")).is_file():
        template = ""
    if not template:
        folders = []
        try:
            folders.append(json.loads((root / ".obsidian" / "templates.json").read_text(encoding="utf-8")).get("folder") or "")
        except (OSError, ValueError):
            pass
        folders += [str(p.relative_to(root)) for p in dirs if p.name.lower() in TEMPLATE_DIR_NAMES]
        for folder in [f for f in folders if f]:
            for path in sorted((root / folder).glob("*.md")):
                if any(key in path.stem.lower() for key in ("daily", "отч", "report", "день")):
                    found["daily_template"] = str(path.relative_to(root))
                    break
            if "daily_template" in found:
                break
    return found


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _stems(query: str) -> list[str]:
    words = re.findall(r"[\wё]+", query.lower())
    return [w[: max(4, len(w) - 2)] if len(w) > 5 else w for w in words if len(w) >= 3]


def split_frontmatter(text: str) -> tuple[list[str], str]:
    """(строки frontmatter без ---, тело). Нет frontmatter — ([], весь текст)."""
    if not text.startswith("---\n"):
        return [], text
    end = text.find("\n---", 3)
    if end == -1:
        return [], text
    body = text[end + 4 :]
    return text[4:end].splitlines(), body.removeprefix("\n")


def parse_frontmatter(text: str) -> dict[str, str]:
    """Плоский YAML-frontmatter (ключ: значение) — без зависимостей."""
    lines, _ = split_frontmatter(text)
    out = {}
    for line in lines:
        if ":" in line and not line.startswith((" ", "\t", "-")):
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def set_frontmatter(text: str, values: dict[str, Any], *, only_empty: bool = True) -> str:
    """Заполняет поля frontmatter, сохраняя порядок и чужие поля. only_empty — не
    трогать то, что человек уже заполнил. Вложенные строки заменяемого поля
    (например, сломанное `date:` с подключом) убираются."""
    lines, body = split_frontmatter(text)
    if not lines and not text.startswith("---\n"):
        return text
    current = parse_frontmatter(text)
    out: list[str] = []
    skipping = False
    seen = set()
    for line in lines:
        if line.startswith((" ", "\t")) and skipping:
            continue
        skipping = False
        key = line.partition(":")[0].strip() if ":" in line and not line.startswith(("-", " ", "\t")) else None
        if key in values and (not only_empty or not current.get(key)):
            out.append(f"{key}: {values[key]}")
            seen.add(key)
            skipping = True
            continue
        if key:
            seen.add(key)
        out.append(line)
    return "---\n" + "\n".join(out) + "\n---\n" + body


def replace_block(text: str, name: str, content: str) -> str:
    """Свой блок внутри заметки. Метки — комментарии Obsidian %% … %%: в режиме чтения и
    в Live Preview их не видно. Старые HTML-метки <!-- arvix:… --> заменяются новыми."""
    start, end = f"%% arvix:{name} %%", f"%% /arvix:{name} %%"
    block = f"{start}\n{content.strip()}\n{end}"
    for old_start, old_end in ((start, end), (f"<!-- arvix:{name} -->", f"<!-- /arvix:{name} -->")):
        if old_start in text and old_end in text:
            head, _, rest = text.partition(old_start)
            _, _, tail = rest.partition(old_end)
            return head + block + tail
    return text.rstrip("\n") + "\n\n" + block + "\n"


MONTHS = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь")
MONTHS_GEN = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря")
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_MOMENT = re.compile(r"\[[^\]]*\]|YYYY|YY|MMMM|MMM|MM|M|DD|Do|D|dddd|ddd|dd|HH|H|mm|ss|ww|w|E")
# Шаблоны Obsidian: ядро ({{date}}, {{date:DD.MM.YYYY}}, {{time}}, {{title}}) и Templater
# (<% tp.date.now("YYYY-MM-DD") %>, <% tp.date.now("D MMMM", 1) %>, <% tp.file.title %>).
_CORE_TOKEN = re.compile(r"\{\{\s*(date|time|title)\s*(?::\s*([^}]*?))?\s*\}\}", re.IGNORECASE)
_TEMPLATER_DATE = re.compile(r"<%[-_*]?\s*tp\.date\.now\(\s*(?:[\"']([^\"']*)[\"'])?\s*(?:,\s*(-?\d+))?[^)]*\)\s*[-_]?%>")
_TEMPLATER_TITLE = re.compile(r"<%[-_*]?\s*tp\.file\.title\s*[-_]?%>")
PLACEHOLDER = re.compile(r"\{\{\s*(?:date|time|title)\b[^}]*\}\}|<%[-_*]?\s*tp\.(?:date\.now|file\.title)\b", re.IGNORECASE)


def format_moment(fmt: str, dt: datetime) -> str:
    """Формат даты в синтаксисе moment.js (его понимает Obsidian), русские названия."""
    genitive = "D" in fmt  # «17 ноября», но «ноябрь 2026»

    def one(m: re.Match[str]) -> str:
        tok = m.group(0)
        if tok.startswith("["):
            return tok[1:-1]
        week = dt.isocalendar()[1]
        return {
            "YYYY": f"{dt.year:04d}", "YY": f"{dt.year % 100:02d}",
            "MMMM": (MONTHS_GEN if genitive else MONTHS)[dt.month - 1], "MMM": MONTHS_GEN[dt.month - 1][:3],
            "MM": f"{dt.month:02d}", "M": str(dt.month), "DD": f"{dt.day:02d}", "Do": f"{dt.day}-е", "D": str(dt.day),
            "dddd": WEEKDAYS[dt.weekday()], "ddd": WEEKDAYS_SHORT[dt.weekday()], "dd": WEEKDAYS_SHORT[dt.weekday()],
            "HH": f"{dt.hour:02d}", "H": str(dt.hour), "mm": f"{dt.minute:02d}", "ss": f"{dt.second:02d}",
            "ww": f"{week:02d}", "w": str(week), "E": str(dt.isoweekday()),
        }[tok]

    return _MOMENT.sub(one, fmt)


def render_template(text: str, dt: datetime, title: str) -> str:
    """Подставляет переменные шаблона Obsidian так же, как это сделал бы сам Obsidian."""
    def core(m: re.Match[str]) -> str:
        kind, fmt = m.group(1).lower(), (m.group(2) or "").strip()
        if kind == "title":
            return title
        return format_moment(fmt or ("YYYY-MM-DD" if kind == "date" else "HH:mm"), dt)

    def templater(m: re.Match[str]) -> str:
        shift = int(m.group(2) or 0)
        return format_moment(m.group(1) or "YYYY-MM-DD", dt + timedelta(days=shift))

    text = _CORE_TOKEN.sub(core, text)
    text = _TEMPLATER_DATE.sub(templater, text)
    return _TEMPLATER_TITLE.sub(title, text)


class Vault:
    def __init__(self, root: Path, paths: dict[str, str] | None = None):
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise VaultError(f"Хранилище не найдено: {self.root}")
        self.paths = {**DEFAULT_PATHS, **{k: v for k, v in (paths or {}).items() if v is not None}}

    # --- пути -----------------------------------------------------------------

    def resolve(self, rel: str, *, must_exist: bool = False) -> Path:
        rel = str(rel).strip().lstrip("/")
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise VaultError(f"Путь вне хранилища: {rel}")
        if any(part in SKIP_DIRS for part in path.relative_to(self.root).parts):
            raise VaultError(f"Служебная папка Obsidian: {rel}")
        if must_exist and not path.is_file():
            raise VaultError(f"Нет такой заметки: {rel}")
        return path

    def rel(self, path: Path) -> str:
        return str(path.relative_to(self.root))

    def place(self, kind: str, name: str = "") -> str:
        """Место по умолчанию для вида заметки: goals + «JS» → 05_System/Цели/JS.md."""
        base = self.paths.get(kind) or ""
        if base.endswith(".md") or not name:
            return base
        safe = re.sub(r'[\\/:*?"<>|]', "-", name).strip()
        return f"{base}/{safe}.md" if base else f"{safe}.md"

    def asset(self, rel: str) -> Path:
        """Вложение заметки (картинка, PDF) для показа в приложении. Ищет как Obsidian:
        точный путь, затем по имени файла в любой папке."""
        rel = str(rel).strip().lstrip("/")
        if Path(rel).suffix.lower() not in ASSET_TYPES:
            raise VaultError(f"Не вложение: {rel}")
        path = self.resolve(rel)
        if path.is_file():
            return path
        name = Path(rel).name
        for found in self.root.rglob(name):
            if found.is_file() and not any(part in SKIP_DIRS for part in found.relative_to(self.root).parts):
                return found
        raise VaultError(f"Нет такого файла: {rel}")

    def files(self) -> list[Path]:
        out = []
        for path in self.root.rglob("*.md"):
            if not any(part in SKIP_DIRS for part in path.relative_to(self.root).parts):
                out.append(path)
        return sorted(out)

    # --- чтение -----------------------------------------------------------------

    def read(self, rel: str) -> str:
        path = self.resolve(rel, must_exist=True)
        if path.suffix.lower() not in (".md", ".txt"):
            raise VaultError(f"Это не заметка: {rel}")
        return path.read_bytes()[:MAX_READ_BYTES].decode("utf-8", errors="replace")

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
                "path": self.rel(path), "heading": heading, "snippet": snippet,
                "score": score, "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%d.%m.%Y"),
            })
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    def overview(self, limit: int = 400) -> dict[str, Any]:
        """Карта хранилища: папки и каждая заметка с заголовком и полями — чтобы Arvix
        знал, что уже написано, до того как задавать вопросы."""
        notes = []
        for path in self.files()[:limit]:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            _, body = split_frontmatter(text)
            title = next((line.lstrip("# ").strip() for line in body.splitlines() if line.startswith("#")), path.stem)
            words = len(re.findall(r"\w+", body))
            notes.append({"path": self.rel(path), "title": title, "words": words,
                          "fields": list(parse_frontmatter(text)), "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%d.%m.%Y")})
        folders: dict[str, int] = {}
        for note in notes:
            folder = str(Path(note["path"]).parent)
            folders[folder] = folders.get(folder, 0) + 1
        return {"notes": notes, "folders": folders, "paths": self.paths}

    # --- запись -----------------------------------------------------------------

    def write(self, rel: str, content: str, *, append: bool = False, owned_sha: str | None = None, force: bool = False) -> dict[str, Any]:
        """owned_sha — хэш, с которым Arvix записал файл в прошлый раз. Совпадает с
        текущим — человек не правил, перезапись безопасна."""
        if not str(rel).endswith(".md"):
            rel = f"{rel}.md"
        path = self.resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        backup = None
        before = sha(path.read_text(encoding="utf-8", errors="replace")) if existed else None
        was_owned = existed and owned_sha is not None and owned_sha == before
        if existed and append:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(("" if content.startswith("\n") else "\n") + content)
        elif existed:
            current = path.read_text(encoding="utf-8", errors="replace")
            if not force and owned_sha != sha(current):
                raise VaultError(
                    f"«{self.rel(path)}» — твоя заметка или ты её правил: перезаписывать не буду. "
                    "Допишу в конец (append) или перезапишу только по твоему явному согласию."
                )
            backup = self.backup(path, current)
            path.write_text(content, encoding="utf-8")
        else:
            path.write_text(content, encoding="utf-8")
        final = path.read_text(encoding="utf-8", errors="replace")
        owned = not existed or force or was_owned
        return {"path": self.rel(path), "created": not existed, "sha": sha(final), "backup": backup, "owned": owned}

    def write_block(self, rel: str, name: str, content: str, *, create_with: str = "") -> dict[str, Any]:
        """Обновляет только свой блок внутри любой заметки (или создаёт заметку)."""
        if not str(rel).endswith(".md"):
            rel = f"{rel}.md"
        path = self.resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        text = path.read_text(encoding="utf-8", errors="replace") if existed else create_with
        path.write_text(replace_block(text, name, content), encoding="utf-8")
        return {"path": self.rel(path), "created": not existed, "sha": sha(path.read_text(encoding="utf-8")), "owned": not existed}

    def update_text(self, rel: str, transform: Any, *, owned_sha: str | None = None) -> dict[str, Any]:
        """Точечная правка (заполнить пустые поля frontmatter), текст человека не трогается."""
        path = self.resolve(rel, must_exist=True)
        current = path.read_text(encoding="utf-8", errors="replace")
        new = transform(current)
        if new != current:
            path.write_text(new, encoding="utf-8")
        return {"path": self.rel(path), "changed": new != current, "sha": sha(new), "owned": owned_sha == sha(current)}

    def save(self, rel: str, content: str, *, base_sha: str | None) -> dict[str, Any]:
        """Правка самого человека из приложения. base_sha — хэш текста, который он открыл:
        если файл с тех пор изменился (ноутбук, синхронизация, Arvix), запись не идёт —
        VaultConflict с текущим текстом, чтобы ничья правка не пропала молча."""
        path = self.resolve(rel, must_exist=base_sha is not None)
        if path.suffix.lower() != ".md":
            raise VaultError(f"Это не заметка: {rel}")
        if path.exists():
            current = path.read_text(encoding="utf-8", errors="replace")
            if base_sha is None or sha(current) != base_sha:
                raise VaultConflict(self.rel(path), current)
            if current == content:
                return {"path": self.rel(path), "created": False, "sha": base_sha, "owned": False, "changed": False}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"path": self.rel(path), "created": base_sha is None, "sha": sha(content), "owned": False, "changed": True}

    def backup(self, path: Path, content: str) -> str:
        flat = self.rel(path).replace("/", "__")
        target = self.root / (self.paths.get("system") or "05_System/Арвикс") / "_backup" / f"{datetime.now():%Y%m%d-%H%M%S}__{flat}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return self.rel(target)

    def inbox(self, text: str, now: datetime) -> str:
        rel = self.paths.get("inbox") or "Inbox.md"
        path = self.resolve(rel)
        header = "" if path.exists() else "# Inbox\n\n"
        return self.write(rel, f"{header}- {now:%Y-%m-%d %H:%M} {text.strip()}\n", append=path.exists())["path"]

    # --- ежедневные заметки -------------------------------------------------------

    def daily_note_settings(self) -> tuple[str, str, str]:
        """Папка, формат и шаблон ежедневных заметок (настройки Obsidian, если не переопределены)."""
        folder, fmt, template = "", "YYYY-MM-DD", ""
        try:
            data = json.loads((self.root / ".obsidian" / "daily-notes.json").read_text(encoding="utf-8"))
            folder, fmt, template = data.get("folder", ""), data.get("format") or fmt, data.get("template", "")
        except (OSError, ValueError):
            pass
        return self.paths.get("daily") or folder, fmt, self.paths.get("daily_template") or template

    def daily_path(self, d: date) -> str:
        folder, fmt, _ = self.daily_note_settings()
        name = fmt.replace("YYYY", f"{d.year:04d}").replace("MM", f"{d.month:02d}").replace("DD", f"{d.day:02d}")
        return f"{folder}/{name}.md" if folder else f"{name}.md"

    def daily_note(self, d: date) -> dict[str, Any] | None:
        """Ежедневная заметка за дату: поля frontmatter читаются кодом, без ИИ."""
        rel = self.daily_path(d)
        path = self.root / rel
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
        return {"path": rel, "fields": parse_frontmatter(text), "text": text[:4000]}

    def template_dirs(self) -> list[str]:
        """Папки шаблонов: настройка Templates, папка Templater и любые «Templates»/«Шаблоны».
        Шаблон — заготовка, а не мысль: в граф и подсказки он не попадает."""
        found: list[str] = []
        for conf, key in ((".obsidian/templates.json", "folder"),
                          (".obsidian/plugins/templater-obsidian/data.json", "templates_folder")):
            try:
                found.append(str(json.loads((self.root / conf).read_text(encoding="utf-8")).get(key) or ""))
            except (OSError, ValueError, AttributeError):
                pass
        for path in self.root.rglob("*"):
            rel = path.relative_to(self.root)
            if len(rel.parts) <= 3 and path.is_dir() and path.name.lower() in TEMPLATE_DIR_NAMES \
                    and not any(part in SKIP_DIRS for part in rel.parts):
                found.append(rel.as_posix())
        return sorted({f.strip("/") for f in found if f.strip("/")})

    def daily_template(self) -> str:
        _, _, template = self.daily_note_settings()
        if template:
            path = self.root / (template if template.endswith(".md") else f"{template}.md")
            if path.is_file():
                return path.read_text(encoding="utf-8", errors="replace")
        return "---\ndate:\ntype: daily\nwake:\nsleep:\nfocus_min:\nworkout:\n---\n# День {{date}}\n\n## Задачи\n- [ ] \n\n## Отчёт\n- Что мешало (факт):\n- Один вывод на завтра:\n"
