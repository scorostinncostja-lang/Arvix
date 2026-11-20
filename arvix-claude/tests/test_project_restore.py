"""Проекты переживают потерю журнала (D54): хранилище Obsidian → события, без потерь и без дублей.

20.11 сервер пропал, журнал поднят по снимку 19.11 — а проекты 19–20.11 остались только в заметках.
"""

from __future__ import annotations

from datetime import date

from arvix import project_roadmap
from arvix import projects as P
from arvix.core import Core
from arvix.project_restore import parse_card, restore
from arvix.store import Store
from tests.helpers import ArvixCase, moscow

GOAL = "Поступить в Stanford или MIT"


class ProjectRestoreTest(ArvixCase):
    start = moscow(2026, 11, 19, 21, 0)

    def setUp(self) -> None:
        super().setUp()
        self.core.cfg.raw.setdefault("vault_paths", {})["roadmaps"] = "02_Areas/Роадмапы"
        goal = self.core.set_goal(GOAL, why="EECS", source="test")
        self.goal_id = goal if isinstance(goal, str) else goal["id"]
        c = self.core
        self.active = P.set_project(c, "Монтаж: 12 видео для YouTube", why="Монтировать уверенно", kind="video",
                                    purposes=["skill", "brand"], expectation="12 видео", deadline="2027-02-28",
                                    weekly_min=90, skills=["монтаж", "звук"], link="https://example.com/channel", source="test")
        P.set_milestone(c, self.active, "Первый ролик", dod="Смонтирован ролик 30–60 с", due="2026-12-01", source="test")
        done = P.set_milestone(c, self.active, "Шаблон", dod="Свой шаблон проекта", source="test")
        P.set_milestone(c, self.active, "", milestone_id=done, status="done", source="test")
        P.set_resource(c, self.active, "DaVinci: обучение", url="https://www.blackmagicdesign.com/training", note="бесплатно", source="test")
        P.set_resource(c, self.active, "Мои заметки", url="03_Resources/Монтаж.md", source="test")
        P.set_resource(c, self.active, "Сайт школы (поиск по названию)", source="test")
        P.set_learn(c, "Цветокоррекция", project_ref=self.active, why="ролики серые", source="test")
        self.idea = P.set_project(c, "Олимпиадная база: 60 задач", why="Логика — слабое место", kind="admission",
                                  purposes=["admission"], expectation="60 задач", goal_id=self.goal_id, status="idea",
                                  weekly_min=240, weeks=8, source="test")
        P.set_milestone(c, self.idea, "Первые 15 задач", dod="15 задач решены", source="test")
        # Идея из роадмапа без папки: её знает только заметка роадмапа цели.
        self.roadmap_only = P.set_project(c, "Пакет для Газпром", why="Шаг к цели", goal_id=self.goal_id, status="idea",
                                          weeks=3, by="arvix", source="test", sync=False)
        P.set_milestone(c, self.roadmap_only, "Требования", dod="Одна страница требований", source="test", sync=False)
        c.write_block(f"02_Areas/Роадмапы/Проекты — {GOAL}.md", "проекты",
                      project_roadmap.note_md(c, c.state.goals[self.goal_id], "Сначала ритм, потом код."),
                      create_with=f"# Проекты — {GOAL}\n\n", source="test")
        self.notes = {p: p.read_text(encoding="utf-8") for p in (self.vault / "01_Projects").rglob("*.md")}
        self.before = {p["title"]: p for p in c.state.projects.values()}

    def lost_server(self) -> Core:
        """Журнал пропал: новая база, та же цель (она была в снимке), то же хранилище — и на день позже."""
        self.core.close()
        self.at(moscow(2026, 11, 20, 18, 0))
        core = Core(self.make_core().cfg, Store(self.tmp / "restored.db"))
        core.cfg.raw.setdefault("vault_paths", {})["roadmaps"] = "02_Areas/Роадмапы"
        self.core = core
        core.set_goal(GOAL, why="EECS", source="test")
        return core

    def test_round_trip_is_lossless_and_notes_untouched(self) -> None:
        core = self.lost_server()
        plan = restore(core)
        self.assertEqual(len([x for x in plan if x.startswith("будет")]), 3, plan)
        self.assertEqual(core.state.projects, {})                             # план ничего не пишет
        restore(core, apply=True)
        after = {p["title"]: p for p in core.state.projects.values()}
        self.assertEqual(set(after), set(self.before))
        goal_id = next(iter(core.state.goals))
        for title, old in self.before.items():
            new = after[title]
            for key in ("kind", "status", "why", "expectation", "deadline", "weekly_min", "skills", "link", "weeks", "folder"):
                if title == "Пакет для Газпром" and key in ("why", "folder"):
                    continue                                                  # у идеи без папки «зачем» в заметках нет
                self.assertEqual(new.get(key), old.get(key), f"{title}: {key}")
            self.assertEqual(sorted(new.get("purposes") or []), sorted(old.get("purposes") or []), title)
            self.assertEqual(new.get("goal_id") is None, old.get("goal_id") is None, title)
            if old.get("goal_id"):
                self.assertEqual(new["goal_id"], goal_id)
            if title != "Пакет для Газпром":                                  # у идеи без карточки даты нигде нет — не выдумываем
                self.assertEqual(new["started"], "2026-11-19", f"{title}: дата начала из карточки, не день восстановления")
        ms = {m["title"]: m for m in core.state.milestones.values()}
        self.assertEqual(ms["Первый ролик"]["due"], "2026-12-01")
        self.assertEqual(ms["Шаблон"]["status"], "done")
        res = {r["title"]: r for r in core.state.resources.values()}
        self.assertEqual(res["DaVinci: обучение"]["note"], "бесплатно")
        self.assertEqual(res["Мои заметки"]["url"], "03_Resources/Монтаж.md")
        self.assertEqual(res["Сайт школы (поиск по названию)"]["url"], "")
        self.assertEqual([x["topic"] for x in core.state.learn_items.values()], ["Цветокоррекция"])
        olymp = after["Олимпиадная база: 60 задач"]
        self.assertEqual(olymp["order"], 1)                                   # порядок — из роадмапа цели
        for path, text in self.notes.items():                                 # карточки пересобраны слово в слово
            self.assertEqual(path.read_text(encoding="utf-8"), text, path.name)
        sources = {e.source for e in core.store.read(0) if e.kind in ("project_set", "milestone_set", "resource_set", "learn_item_set")}
        self.assertEqual(sources, {"restore"})                                # честно видно, откуда события

    def test_second_run_adds_nothing(self) -> None:
        core = self.lost_server()
        restore(core, apply=True)
        count = len(core.store.read(0))
        report = restore(core, apply=True)
        self.assertEqual(len(core.store.read(0)), count)
        self.assertTrue(all(x.startswith("есть") for x in report), report)

    def test_failed_project_leaves_nothing_half_done(self) -> None:
        core = self.lost_server()
        for n in range(3):                                                    # лимит «в работе» уже занят
            P.set_project(core, f"Занят {n}", why="лимит", source="test")
        report = restore(core, apply=True)
        self.assertTrue(any(x.startswith("НЕ создан Монтаж") for x in report), report)
        self.assertNotIn("Монтаж: 12 видео для YouTube", {p["title"] for p in core.state.projects.values()})
        self.assertFalse(any(m["title"] == "Первый ролик" for m in core.state.milestones.values()))


class CardFormatTest(ArvixCase):
    def test_old_card_format_without_bullets(self) -> None:
        """Карточки 0.8 писались без «- » и с «Ожидание:» / «Этапы:» — их тоже понимаем."""
        card = parse_card("%% arvix:проект %%\n**Ниша и 3 пробных поста** · контент и блог · идея\n"
                          "Зачем: навык, портфолио, заработок; Быстрый результат за 2 недели\n"
                          "Цель: Выйти на доход\nОжидание: 3 поста\nначат 2026-11-19 · 1ч30м в неделю · вложено 0м\n"
                          "Навыки: ниша, текст\n\nЭтапы:\n- [ ] Выбрать нишу — Записаны 10 тем\n\n"
                          "Источники и инструменты:\n- [Canva](https://www.canva.com)\n%% /arvix:проект %%")
        self.assertEqual(card["kind"], "content")
        self.assertEqual(card["status"], "idea")
        self.assertEqual(card["purposes"], ["skill", "portfolio", "earn"])
        self.assertEqual(card["why"], "Быстрый результат за 2 недели")
        self.assertEqual(card["expectation"], "3 поста")
        self.assertEqual(card["weekly_min"], 90)
        self.assertEqual(card["started"], date(2026, 11, 19).isoformat())
        self.assertEqual(card["milestones"], [{"title": "Выбрать нишу", "dod": "Записаны 10 тем", "due": None, "status": "open"}])
        self.assertEqual(card["resources"], [{"title": "Canva", "url": "https://www.canva.com", "note": ""}])

    def test_no_card_no_project(self) -> None:
        self.assertIsNone(parse_card("# GYM Bro\n\nПросто заметка человека."))
