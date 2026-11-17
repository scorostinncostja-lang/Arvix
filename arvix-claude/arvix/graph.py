"""Граф заметок — как в Obsidian, плюс то, чего там нет (05-INTERFACES §7.7, D32).

Код (L0, без модели) строит граф из [[вики-ссылок]], [текст](ссылок.md) и #тегов, как его
понимает Obsidian: ссылка ищется по имени файла в любой папке; несуществующая — «призрак».
Сверху — подсказки: пары заметок, которые говорят об одном (общие редкие основы слов и
теги), но не связаны. Связать — одно нажатие: в конец заметки дописывается строка со ссылкой.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from arvix.vault import split_frontmatter

WIKI = re.compile(r"!?\[\[([^\]|#^]+)(?:[#^][^\]|]*)?(?:\|[^\]]*)?\]\]")
MDLINK = re.compile(r"\[[^\]]*\]\(([^)\s]+?\.md)\)")
TAG = re.compile(r"(?:^|\s)#([\w/-]*[^\W\d][\w/-]*)", re.UNICODE)
WORD = re.compile(r"[a-zа-яё]{4,}", re.IGNORECASE)
CODE = re.compile(r"```.*?```", re.DOTALL)
STOP = set("""это этот эта эти того тому тоже также только когда если чтобы потому поэтому очень можно нужно надо
будет было были быть есть свой своя свои себя тебя меня него неё нему ними которые который которая какой какая
после перед между через более менее почти сейчас сегодня завтра вчера день дней задача задачи сделано сделать
отчёт отчет план плана минут минута часов время where with that this from have will your about there their""".split())
LINK_LINE = "Связи:"


def _stem(word: str) -> str:
    word = word.lower().replace("ё", "е")
    return word[: max(4, len(word) - 2)] if len(word) > 6 else word


def _kind(rel: str, vault: Any) -> str:
    paths = vault.paths
    if paths.get("daily") and rel.startswith(paths["daily"].rstrip("/") + "/") or re.search(r"\d{4}-\d{2}-\d{2}\.md$", rel):
        return "daily"
    for kind in ("goals", "roadmaps", "notes", "system", "files"):
        base = (paths.get(kind) or "").rstrip("/")
        if base and not base.endswith(".md") and rel.startswith(base + "/"):
            return kind
    return "note"


def build(vault: Any, *, suggestions: int = 12) -> dict[str, Any]:
    files = vault.files()
    by_name: dict[str, list[str]] = {}
    texts: dict[str, str] = {}
    for path in files:
        rel = vault.rel(path)
        by_name.setdefault(path.stem.lower(), []).append(rel)
        try:
            texts[rel] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            texts[rel] = ""

    def resolve(target: str, src: str) -> str | None:
        target = target.strip().removesuffix(".md")
        if "/" in target:
            direct = target + ".md"
            return direct if direct in texts else None
        hits = by_name.get(target.lower()) or []
        if len(hits) > 1:  # как Obsidian: ближайшая к источнику
            folder = str(Path(src).parent)
            hits = sorted(hits, key=lambda h: (str(Path(h).parent) != folder, len(h)))
        return hits[0] if hits else None

    nodes: dict[str, dict[str, Any]] = {}
    edges: set[tuple[str, str]] = set()
    ghosts: dict[str, int] = {}
    stems: dict[str, Counter[str]] = {}
    tags: dict[str, set[str]] = {}
    for rel, text in texts.items():
        _, body = split_frontmatter(text)
        title = next((line.lstrip("# ").strip() for line in body.splitlines() if line.startswith("# ")), Path(rel).stem)
        clean = CODE.sub(" ", body)
        note_tags = {t.lower() for t in TAG.findall(clean)}
        fm_tags = re.search(r"^tags:\s*\[?([^\]\n]*)", text[:2000], re.MULTILINE)
        if fm_tags:
            note_tags |= {t.strip(" '\"#").lower() for t in fm_tags.group(1).split(",") if t.strip(" '\"#")}
        tags[rel] = note_tags
        nodes[rel] = {"id": rel, "title": title[:80], "name": Path(rel).stem, "folder": str(Path(rel).parent) if "/" in rel else "",
                      "kind": _kind(rel, vault), "tags": sorted(note_tags)[:8], "words": len(WORD.findall(clean)), "degree": 0}
        for raw in WIKI.findall(clean) + MDLINK.findall(clean):
            target = resolve(raw.replace("%20", " "), rel)
            if target and target != rel:
                edges.add(tuple(sorted((rel, target))))  # type: ignore[arg-type]
            elif not target and not Path(raw).suffix.lower() in (".png", ".jpg", ".jpeg", ".pdf", ".gif", ".webp", ".svg"):
                ghosts[raw.strip()] = ghosts.get(raw.strip(), 0) + 1
        stems[rel] = Counter(_stem(w) for w in WORD.findall(clean) if w.lower() not in STOP)
    for a, b in edges:
        nodes[a]["degree"] += 1
        nodes[b]["degree"] += 1
    orphans = [n["id"] for n in nodes.values() if not n["degree"] and n["kind"] != "daily"]
    return {
        "nodes": list(nodes.values()),
        "edges": [{"s": a, "t": b} for a, b in sorted(edges)],
        "ghosts": [{"name": g, "refs": c} for g, c in sorted(ghosts.items(), key=lambda x: -x[1])[:60]],
        "orphans": orphans,
        "suggestions": suggest(nodes, edges, stems, tags, limit=suggestions),
    }


def suggest(nodes: dict[str, dict[str, Any]], edges: set[tuple[str, str]], stems: dict[str, Counter[str]],
            tags: dict[str, set[str]], *, limit: int = 12) -> list[dict[str, Any]]:
    """Похожие, но не связанные заметки: косинус по TF-IDF основ слов + общие теги.
    Дневные отчёты и служебные файлы не предлагаются — связывать стоит мысли, а не даты."""
    pool = [rel for rel, n in nodes.items() if n["kind"] not in ("daily", "system", "files") and n["words"] >= 15
            and n["name"].upper() not in ("CLAUDE", "AGENTS", "README")]
    df: Counter[str] = Counter()
    for rel in pool:
        df.update(set(stems[rel]))
    total = max(len(pool), 1)
    vectors: dict[str, dict[str, float]] = {}
    for rel in pool:
        vec = {s: c * math.log(1 + total / df[s]) for s, c in stems[rel].items() if 1 < df[s] <= max(2, total * 0.4)}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vectors[rel] = {s: v / norm for s, v in vec.items()}
    out = []
    for i, a in enumerate(pool):
        va = vectors[a]
        for b in pool[i + 1 :]:
            if (a, b) in edges or (b, a) in edges:
                continue
            vb = vectors[b]
            small, large = (va, vb) if len(va) < len(vb) else (vb, va)
            score = sum(v * large.get(s, 0.0) for s, v in small.items())
            common_tags = tags[a] & tags[b]
            score += 0.15 * len(common_tags)
            if score < 0.18:
                continue
            shared = sorted((s for s in small if s in large), key=lambda s: -(small[s] * large[s]))[:4]
            out.append({"a": a, "b": b, "score": round(score, 3), "why": shared, "tags": sorted(common_tags)[:4]})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


def link_line(text: str, target_name: str) -> str:
    """Дописать [[target]] в строку «Связи:» в конце заметки (или создать её)."""
    link = f"[[{target_name}]]"
    if link in text:
        return text
    lines = text.rstrip("\n").split("\n")
    if lines and lines[-1].startswith(LINK_LINE):
        lines[-1] = lines[-1].rstrip() + " " + link
    else:
        lines += ["", f"{LINK_LINE} {link}"]
    return "\n".join(lines) + "\n"


__all__ = ["build", "link_line", "suggest"]
