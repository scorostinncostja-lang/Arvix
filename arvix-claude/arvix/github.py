"""GitHub для проектов (D44): список репозиториев человека и коммиты как движение проекта.

Коммит — лучшее доказательство работы над кодом: его нельзя «отметить кнопкой», он либо есть, либо нет.
Поэтому новые коммиты привязанного репозитория попадают в журнал событием repo_activity и дальше
считаются как движение, время недели и строка портфолио — тем же кодом, что всё остальное.

Сеть — только здесь и только чтение публичного API (как погода в weather.py). Имя пользователя —
в профиле (`github_user`, его можно задать из приложения); токен для приватных репозиториев — только
в конфиге сервера (`[github] token`), в чат и приложение он не попадает.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime
from typing import Any

from arvix.core import ArvixError

log = logging.getLogger("arvix.github")
API = "https://api.github.com"
USER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
REPOS_TTL = 600        # список репозиториев — кэш 10 минут
SYNC_EVERY = 3600      # коммиты — раз в час из планировщика, по кнопке — сразу
Fetch = Callable[[str, str], Any]


def _fetch(path: str, token: str) -> Any:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "arvix", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(API + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ArvixError("GitHub: не найдено — проверь имя или доступ (приватному нужен токен на сервере)") from exc
        if exc.code in (401, 403):
            raise ArvixError("GitHub отказал: лимит запросов без токена или неверный токен") from exc
        raise ArvixError(f"GitHub ответил {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ArvixError("GitHub недоступен — нет сети") from exc


def user(core: Any) -> str:
    return str(core.state.profile.get("github_user") or core.cfg.section("github").get("user") or "").strip()


def token(core: Any) -> str:
    return str(core.cfg.section("github").get("token") or "").strip()


def set_user(core: Any, name: str, *, source: str = "web") -> str:
    name = str(name or "").strip().lstrip("@")
    m = re.search(r"github\.com/([^/\s?#]+)", name)
    name = m.group(1) if m else name
    if name and not USER_RE.match(name):
        raise ArvixError(f"«{name}» не похоже на имя пользователя GitHub")
    core.profile_set("github_user", name, source=source)
    core.store.kv_set("github_repos", None)
    return name


def cached_repos(core: Any, fresh: bool = False) -> list[dict[str, Any]] | None:
    """Список из кэша, если он свежий; None — надо сходить в GitHub."""
    cached = core.store.kv_get("github_repos") or {}
    if not fresh and cached.get("user") == user(core) and core.now().timestamp() - float(cached.get("at") or 0) < REPOS_TTL:
        return list(cached.get("items") or [])
    return None


def store_repos(core: Any, who: str, items: list[dict[str, Any]]) -> None:
    core.store.kv_set("github_repos", {"user": who, "at": core.now().timestamp(), "items": items})


def repos(core: Any, *, fetch: Fetch = _fetch, fresh: bool = False) -> list[dict[str, Any]]:
    """Репозитории человека, свежие сверху. С токеном — и приватные."""
    who, key = user(core), token(core)
    if not who and not key:
        return []
    cached = cached_repos(core, fresh)
    if cached is not None:
        return cached
    items = fetch_repos(who, key, fetch)
    store_repos(core, who, items)
    return items


def fetch_repos(who: str, key: str, fetch: Fetch = _fetch) -> list[dict[str, Any]]:
    """Только сеть, без ядра — можно звать вне замка."""
    path = "/user/repos?sort=pushed&per_page=100&affiliation=owner" if key else \
        f"/users/{urllib.parse.quote(who)}/repos?sort=pushed&per_page=100"
    return [{
        "repo": r["full_name"], "name": r["name"], "description": r.get("description") or "", "language": r.get("language") or "",
        "stars": int(r.get("stargazers_count") or 0), "issues": int(r.get("open_issues_count") or 0),
        "pushed_at": r.get("pushed_at") or "", "url": r.get("html_url") or f"https://github.com/{r['full_name']}",
        "private": bool(r.get("private")), "fork": bool(r.get("fork")), "archived": bool(r.get("archived")),
    } for r in fetch(path, key) or []]


def _local_date(core: Any, iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(core.tz).date().isoformat()
    except ValueError:
        return core.today().isoformat()


def sync(core: Any, *, fetch: Fetch = _fetch, force: bool = False, source: str = "l0") -> dict[str, int]:
    """Новые коммиты привязанных репозиториев → repo_activity. Ничего нового — ничего не пишется.
    Возвращает {проект: число новых коммитов}. Ошибка одного репозитория не мешает другим."""
    now = core.now().timestamp()
    if not force and now - float(core.store.kv_get("github_synced_at") or 0) < SYNC_EVERY:
        return {}
    core.store.kv_set("github_synced_at", now)
    key = token(core)
    out: dict[str, int] = {}
    for project in list(core.state.projects.values()):
        repo = project.get("repo")
        if not repo or project["status"] not in ("active", "paused", "idea"):
            continue
        try:
            meta = fetch(f"/repos/{repo}", key) or {}
            known = [c for c in core.state.commits.values() if c["project_id"] == project["id"]]
            since = max((c["at"] for c in known), default="")
            query = "?per_page=50" + (f"&since={urllib.parse.quote(since)}" if since else "")
            raw = fetch(f"/repos/{repo}/commits{query}", key) or []
        except ArvixError as exc:
            log.info("github %s: %s", repo, exc)
            continue
        fresh = []
        for c in raw:
            sha = str(c.get("sha") or "")[:12]
            info = c.get("commit") or {}
            when = (info.get("author") or {}).get("date") or (info.get("committer") or {}).get("date") or ""
            if not sha or sha in core.state.commits:
                continue
            fresh.append({"sha": sha, "message": str(info.get("message") or "").split("\n")[0][:160], "at": when,
                          "date": _local_date(core, when), "url": c.get("html_url") or ""})
        info = {"pushed_at": meta.get("pushed_at") or "", "stars": int(meta.get("stargazers_count") or 0),
                "issues": int(meta.get("open_issues_count") or 0), "language": meta.get("language") or "",
                "description": meta.get("description") or "", "url": meta.get("html_url") or f"https://github.com/{repo}"}
        old = core.state.repos.get(project["id"]) or {}
        if fresh or any(old.get(k) != v for k, v in info.items()):
            with core.tx():
                core.emit("repo_activity", {"project_id": project["id"], "repo": repo, "commits": fresh[:50], "meta": info},
                          source=source, entity_id=project["id"])
        out[project["id"]] = len(fresh)
    return out
