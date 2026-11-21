"""Проекты (D43, D44, D47): карточка, этапы с DoD, время, застой, темп, блок в план, папка проекта в Obsidian,
чат проекта, «учиться», приложение и голова. Всё считается кодом — модель только читает."""

from __future__ import annotations

from datetime import timedelta

from arvix import brain, projects
from arvix.context import build_context
from arvix.core import ArvixError
from arvix.state import State
from arvix.web import api
from tests.helpers import ArvixCase, moscow


class ProjectCase(ArvixCase):
    def project(self, title: str = "Бот для расписания", **kw) -> str:
        kw.setdefault("why", "навык Python и первый кейс в портфолио")
        kw.setdefault("expectation", "бот работает у 10 одноклассников")
        kw.setdefault("deadline", "2026-12-31")
        kw.setdefault("kind", "portfolio")
        return projects.set_project(self.core, title, source="user", **kw)


class ProjectRulesTest(ProjectCase):
    def test_project_needs_why_and_closing_needs_result(self):
        with self.assertRaises(ArvixError):
            projects.set_project(self.core, "Без зачем", why="")
        pid = self.project()
        with self.assertRaisesRegex(ArvixError, "итог"):
            projects.set_project(self.core, project_id=pid, status="dropped")
        projects.set_project(self.core, project_id=pid, status="dropped", reason="понял, что бот никому не нужен — проверил опросом")
        self.assertEqual(self.core.state.projects[pid]["status"], "dropped")
        self.assertEqual(self.core.state.projects[pid]["closed"], "2026-11-02")

    def test_wip_limit_three_active_projects(self):
        for i in range(3):
            self.project(f"Проект {i}")
        with self.assertRaisesRegex(ArvixError, "лимит"):
            self.project("Четвёртый")
        idea = self.project("Четвёртый", status="idea")  # идеей — можно
        self.assertEqual(self.core.state.projects[idea]["status"], "idea")
        first = next(iter(self.core.state.projects))
        projects.set_project(self.core, project_id=first, status="paused")
        projects.set_project(self.core, project_id=idea, status="active")
        self.assertEqual(len(projects.active(self.core)), 3)

    def test_milestone_requires_definition_of_done(self):
        pid = self.project()
        with self.assertRaisesRegex(ArvixError, "критерий"):
            projects.set_milestone(self.core, pid, "Сделать бота")
        mid = projects.set_milestone(self.core, pid, "MVP", dod="бот отвечает на /today у меня в Telegram", due="2026-11-20")
        self.assertEqual(projects.next_step(self.core, self.core.state.projects[pid])["id"], mid)

    def test_time_counts_done_tasks_timer_and_said_minutes_separately(self):
        pid = self.project()
        task = self.core.add_task("Бот: парсер", start="11:00", duration_min=60, deep_work=True, project=pid, source="user")
        self.assertEqual(task.project, pid)
        self.core.log_focus(40, task_ref=task.id)
        self.core.complete_task(task.id, done_pct=50, report="парсер читает сайт школы")
        projects.log_entry(self.core, pid, "вечером дописал обработку ошибок", minutes=30)
        s = projects.stats(self.core, self.core.state.projects[pid])
        self.assertEqual(s["task_min"], 40)   # таймер 40 > 60×50 %
        self.assertEqual(s["said_min"], 30)
        self.assertEqual(s["minutes"], 70)
        self.assertEqual(s["week_min"], 70)

    def test_unknown_project_on_task_is_refused(self):
        with self.assertRaises(ArvixError):
            self.core.add_task("Сирота", project="nope", source="user")

    def test_stall_and_decision_are_raised_by_code(self):
        pid = self.project()
        projects.set_milestone(self.core, pid, "MVP", dod="работает у меня")
        p = self.core.state.projects[pid]
        self.assertFalse(any("без движения" in i for i in projects.issues(self.core, p)))
        self.at(self.start + timedelta(days=8))
        self.assertTrue(any("8 дн без движения" in i for i in projects.issues(self.core, p)))
        self.assertEqual([x[0]["id"] for x in projects.stalled(self.core)], [pid])
        self.at(self.start + timedelta(days=22))
        self.assertTrue(any("продолжаем, откладываем или завершаем" in i for i in projects.issues(self.core, p)))
        projects.log_entry(self.core, pid, "вернулся, сделал меню")
        self.assertEqual(projects.stats(self.core, p)["idle_days"], 0)

    def test_editing_the_card_is_not_movement(self):
        pid = self.project()
        self.at(self.start + timedelta(days=9))
        projects.set_project(self.core, project_id=pid, expectation="бот у 20 человек")
        self.assertEqual(projects.stats(self.core, self.core.state.projects[pid])["idle_days"], 9)

    def test_pace_and_forecast(self):
        pid = self.project(deadline="2026-11-30")  # 28 дней
        a = projects.set_milestone(self.core, pid, "A", dod="a")
        for name in ("B", "C", "D"):
            projects.set_milestone(self.core, pid, name, dod=name.lower())
        self.at(self.start + timedelta(days=14))
        projects.set_milestone(self.core, pid, milestone_id=a, status="done")
        s = projects.stats(self.core, self.core.state.projects[pid])
        self.assertTrue(s["pace"]["behind"])          # 25 % этапов при 50 % времени
        self.assertEqual(s["forecast"], "2026-12-28")  # 1 этап за 2 недели → ещё 3 за 6 недель
        self.assertTrue(any("отстаёт" in i for i in projects.issues(self.core, self.core.state.projects[pid])))

    def test_kind_is_free_text_and_purposes_are_many(self):
        pid = self.project("Подкаст", kind="подкаст с друзьями", why="", purposes=["people", "fun", "научиться говорить"])
        p = self.core.state.projects[pid]
        self.assertEqual(projects.kind_label(p["kind"]), "подкаст с друзьями")
        self.assertEqual([projects.purpose_label(x) for x in p["purposes"]], ["единомышленники", "удовольствие", "научиться говорить"])
        legacy = self.project("Старый", kind="income")  # тип из 0.7 — показывается по-человечески
        self.assertEqual(projects.kind_label(self.core.state.projects[legacy]["kind"]), "заработок")
        with self.assertRaisesRegex(ArvixError, "зачем"):
            projects.set_project(self.core, "Без всего", why="", purposes=[])

    def test_resources_fill_in_and_examples(self):
        pid = self.project()
        projects.set_resource(self.core, pid, "aiogram: пример бота", url="https://github.com/aiogram/aiogram", kind="example", by="arvix")
        rid = projects.set_resource(self.core, pid, "Документация aiogram", url="docs.aiogram.dev", kind="doc")
        self.assertEqual(self.core.state.resources[rid]["url"], "https://docs.aiogram.dev")
        projects.set_resource(self.core, pid, resource_id=rid, status="removed")
        self.assertEqual([r["kind"] for r in projects.resources(self.core, pid)], ["example"])
        with self.assertRaises(ArvixError):
            projects.set_resource(self.core, pid, "Плохая", url="не ссылка вовсе")

    def test_roadmap_orders_projects_by_goal(self):
        goal = self.core.set_goal("Поступить в лицей на IT", why="сильная школа", kind="main", deadline="2027-06-30")
        a = self.project("Сайт-визитка", goal_id=goal)
        b = self.project("Бот расписания", goal_id=goal)
        c = self.project("Олимпиада", goal_id=goal, status="idea")
        loose = self.project("Рисование", status="idea")
        rm = projects.roadmap(self.core)
        self.assertEqual([p["id"] for p in rm[0]["projects"]], [a, b, c])
        self.assertIsNone(rm[-1]["goal"])
        self.assertEqual([p["id"] for p in rm[-1]["projects"]], [loose])
        projects.move(self.core, c, -1)
        self.assertEqual([p["id"] for p in projects.roadmap_chain(self.core, goal)], [a, c, b])
        self.assertIn("2. [", projects.roadmap_text(self.core))

    def test_plan_block_finds_free_slot_and_names_next_step(self):
        pid = self.project()
        projects.set_milestone(self.core, pid, "MVP", dod="работает")
        self.core.add_task("Алгебра", start="10:15", duration_min=90, source="user")  # 10:15–11:45
        task = projects.plan_block(self.core, pid, minutes=60)
        self.assertEqual(task.start, "11:45")
        self.assertEqual(task.title, "Бот для расписания: MVP")
        self.assertEqual((task.project, task.sphere, task.deep_work), (pid, "project", True))

    def test_state_rebuild_equals_incremental(self):
        pid = self.project()
        mid = projects.set_milestone(self.core, pid, "MVP", dod="работает")
        projects.set_milestone(self.core, pid, milestone_id=mid, status="done")
        projects.set_resource(self.core, pid, "MDN", url="https://developer.mozilla.org")
        projects.set_learn(self.core, "SQL: JOIN", project_ref=pid, why="хранить расписание")
        self.core.emit("repo_activity", {"project_id": pid, "repo": "me/x", "meta": {"stars": 1},
                                         "commits": [{"sha": "abc", "message": "init", "at": "2026-11-02T08:00:00Z", "date": "2026-11-02"}]},
                       source="l0")
        projects.log_entry(self.core, pid, "релиз 0.1", kind="release")
        rebuilt = State.rebuild(self.core.store.read())
        for attr in ("projects", "milestones", "project_log", "resources", "learn_items"):
            self.assertEqual(getattr(rebuilt, attr), getattr(self.core.state, attr), attr)


class ProjectSurfacesTest(ProjectCase):
    def test_context_shows_projects_with_issues(self):
        pid = self.project()
        text = build_context(self.core)
        self.assertIn("ПРОЕКТЫ:", text)
        self.assertIn(f"[{pid}] Бот для расписания", text)
        self.assertIn("нет этапов", text)

    def test_projects_hidden_in_red_context_and_app(self):
        self.project()
        self.core.sos(True, note="тест")
        self.core.recompute_mode()
        self.assertNotIn("ПРОЕКТЫ", build_context(self.core))
        self.assertTrue(api.projects_view(self.core)["gentle"])
        self.assertEqual(api.projects_view(self.core)["groups"], [])

    def test_head_actions_create_project_milestone_and_block(self):
        done, failed, _ = brain.apply_actions(self.core, [
            {"type": "set_project", "title": "Сайт-портфолио", "why": "показать работы", "kind": "portfolio",
             "expectation": "сайт онлайн, 3 работы", "deadline": "2026-12-15", "weekly_min": 180},
        ], source="telegram")
        self.assertFalse(failed, failed)
        pid = next(iter(self.core.state.projects))
        done, failed, _ = brain.apply_actions(self.core, [
            {"type": "set_milestone", "project": pid, "title": "Главная", "metric": "страница открывается по ссылке"},
            {"type": "plan_project", "project": pid, "duration_min": 45, "date": "tomorrow"},
            {"type": "project_resource", "project": pid, "title": "Astro docs", "url": "https://docs.astro.build", "kind": "doc"},
            {"type": "project_log", "project": pid, "text": "выбрал Astro", "kind": "decision"},
            {"type": "project_note", "project": pid, "title": "Архитектура", "text": "## Стек\n- Astro"},
            {"type": "learn_add", "project": pid, "topic": "CSS Grid", "why": "вёрстка главной", "sources": ["MDN: CSS Grid"]},
        ], source="telegram")
        self.assertFalse(failed, failed)
        self.assertEqual(len(done), 6)
        self.assertTrue((self.vault / "01_Projects/Сайт-портфолио/Архитектура.md").exists())
        self.assertEqual(projects.learn_items(self.core, pid)[0]["topic"], "CSS Grid")
        block = next(t for t in self.core.state.tasks.values() if t.project == pid)
        self.assertEqual(block.local_date, self.core.today() + timedelta(days=1))
        self.assertEqual(block.start, "09:00")
        self.assertEqual(self.core.state.projects[pid]["weekly_min"], 180)
        _, failed, _ = brain.apply_actions(self.core, [{"type": "set_milestone", "project": pid, "title": "Без критерия"}])
        self.assertTrue(failed and "критерий" in failed[0])

    def test_app_view_and_ops(self):
        goal = self.core.set_goal("Стать разработчиком", why="работа мечты", kind="main")
        pid = self.project(goal_id=goal)
        projects.set_milestone(self.core, pid, "MVP", dod="работает")
        view = api.projects_view(self.core)
        self.assertEqual(view["groups"][0]["goal"]["id"], goal)
        card = view["groups"][0]["projects"][0]
        self.assertEqual((card["id"], card["milestones_total"], card["group"]), (pid, 1, "active"))
        detail = api.project_view(self.core, pid)
        self.assertEqual(detail["milestones"][0]["title"], "MVP")
        self.assertEqual(detail["files"][0]["path"], "01_Projects/Бот для расписания/Бот для расписания.md")

        class FakeBot:
            core = self.core

            def refresh_panel(self):
                return None

        bot = FakeBot()
        api.project_op(pid, "milestone", {"milestone": detail["milestones"][0]["id"], "status": "done"})(bot)
        api.project_op(pid, "learn", {"topic": "asyncio"})(bot)
        item = projects.learn_items(self.core, pid)[0]
        r = api.project_op(pid, "learn_start", {"item": item["id"], "minutes": 45})(bot)
        self.assertEqual((r["task"]["sphere"], r["task"]["project"]), ("learning", pid))
        self.core.complete_task(r["task"]["id"], report="разобрал event loop и gather")
        self.assertEqual(projects.learn_items(self.core, pid)[0]["status"], "done")  # урок закрыт — тема пройдена, без отметки
        r = api.project_op(pid, "save", {"title": "Бот расписания", "deadline": "2027-01-15"})(bot)
        self.assertEqual(r["project"]["title"], "Бот расписания")
        self.assertEqual(r["project"]["folder"], "01_Projects/Бот для расписания")  # папка не переезжает

    def test_one_phrase_creates_project_and_respects_limit(self):
        pid = projects.start(self.core, "хочу сделать бота, который напоминает про домашку. Чтобы научиться Python")
        p = self.core.state.projects[pid]
        self.assertEqual((p["title"], p["status"]), ("Хочу сделать бота, который напоминает про домашку", "active"))
        self.assertIn("научиться Python", p["why"])
        self.assertFalse((self.vault / "01_Projects").exists())  # черновик — папки ещё нет
        projects.set_project(self.core, "Бот-напоминалка", project_id=pid)  # Arvix дал имя
        p = self.core.state.projects[pid]
        self.assertEqual(p["folder"], "01_Projects/Бот-напоминалка")
        self.assertTrue((self.vault / "01_Projects/Бот-напоминалка/Бот-напоминалка.md").exists())
        for i in range(2):
            self.project(f"Ещё {i}")
        later = projects.start(self.core, "подкаст с другом")
        self.assertEqual(self.core.state.projects[later]["status"], "idea")  # лимит занят — отложен, а не отказ

    def test_obsidian_folder_keeps_owner_text_and_journal(self):
        pid = self.project(skills=["Python", "Telegram API"])
        p = self.core.state.projects[pid]
        path = self.vault / projects.main_note(self.core, p)
        path.write_text(path.read_text(encoding="utf-8") + "\nМои мысли.\n", encoding="utf-8")
        task = self.core.add_task("Бот: парсер", start="11:00", duration_min=60, project=pid, source="user")
        self.core.complete_task(task.id, report="парсер читает сайт школы")  # отчёт блока — сразу в журнал проекта
        text = path.read_text(encoding="utf-8")
        self.assertIn("Мои мысли.", text)
        self.assertIn("Навыки: Python, Telegram API", text)
        self.assertEqual(text.count("arvix:проект"), 2)
        journal = (self.vault / "01_Projects/Бот для расписания/Журнал.md").read_text(encoding="utf-8")
        self.assertIn("парсер читает сайт школы", journal)
        events = len(self.core.store.read())
        projects.sync_notes(self.core, pid)
        self.assertEqual(len(self.core.store.read()), events)  # ничего не изменилось — ни записи, ни события
        rel = projects.write_note(self.core, pid, "Идеи", "- уведомления")
        (self.vault / rel).write_text("моё\n", encoding="utf-8")
        projects.write_note(self.core, pid, "Идеи", "- тёмная тема")  # правленную человеком — только дописать
        lines = (self.vault / rel).read_text(encoding="utf-8").splitlines()
        self.assertEqual((lines[0], lines[-1]), ("моё", "- тёмная тема"))

    def test_brief_line(self):
        pid = self.project()
        projects.set_milestone(self.core, pid, "MVP", dod="работает")
        self.assertEqual(projects.brief_line(self.core), "Проекты: «Бот для расписания» → MVP")
        self.at(moscow(2026, 11, 12, 10))
        self.assertIn("10 дн без движения", projects.brief_line(self.core))


class ProjectStallTelegramTest(ProjectCase):
    """Застой: Arvix пишет сам, раз в неделю на проект, кнопки ставят блок или паузу."""

    def setUp(self) -> None:
        super().setUp()
        from arvix.telegram.bot import Bot
        from arvix.telegram.scheduler import Scheduler
        from tests.test_telegram import OWNER, FakeAPI, FakeBrain

        self.api = FakeAPI()
        self.bot = Bot(self.core, self.api, FakeBrain(), OWNER, sleep=lambda _s: None)
        self.scheduler = Scheduler(self.bot)
        self.owner = OWNER

    def test_stalled_project_nudge_once_a_week_and_buttons(self):
        pid = self.project()
        projects.set_milestone(self.core, pid, "MVP", dod="работает у меня")
        self.core.message_out("привет")  # бот писал и человек отвечал — обычный день
        self.at(moscow(2026, 11, 10, 15, 5))
        self.core.message_in("я тут")
        self.core.log_social("тест")  # действие человека сегодня
        self.scheduler.tick()
        nudges = [(t, b) for t, b in self.api.sent if "без движения" in t]
        self.assertEqual(len(nudges), 1)
        self.assertIn("Бот для расписания", nudges[0][0])
        self.assertIn(f"j:{pid}:b30", str(nudges[0][1]))
        self.scheduler.tick()
        self.assertEqual(len([t for t in self.api.texts if "без движения" in t]), 1)  # ключ недели — без дубля
        self.bot.on_callback({"id": "1", "from": {"id": self.owner}, "data": f"j:{pid}:b30", "message": {}})
        block = next(t for t in self.core.state.tasks.values() if t.project == pid)
        self.assertEqual((block.duration_min, block.local_date), (30, self.core.today()))
        self.bot.on_callback({"id": "2", "from": {"id": self.owner}, "data": f"j:{pid}:pause", "message": {}})
        self.assertEqual(self.core.state.projects[pid]["status"], "paused")
        self.assertEqual(projects.stalled(self.core), [])


class ProjectMcpTest(ProjectCase):
    def test_mcp_project_tool(self):
        from arvix.mcp_server import Server

        server = Server(lambda: self.core)
        r = server.call_tool("project", {"action": "set", "title": "Сайт", "why": "портфолио", "expectation": "онлайн",
                                         "deadline": "2026-12-01", "weekly_min": 120})
        self.assertFalse(r["isError"], r)
        self.assertIn("нет этапов", r["content"][0]["text"])  # несостыковка — модели сразу
        r = server.call_tool("project", {"action": "milestone", "project": "Сайт", "title": "Главная", "dod": "открывается"})
        self.assertFalse(r["isError"], r)
        r = server.call_tool("project", {"action": "block", "project": "Сайт", "duration_min": 30})
        self.assertIn("Сайт: Главная", r["content"][0]["text"])
        r = server.call_tool("project", {"action": "list"})
        self.assertIn("ПРОЕКТЫ:", r["content"][0]["text"])
        r = server.call_tool("project", {"action": "roadmap"})
        self.assertIn("Вне целей", r["content"][0]["text"])
        r = server.call_tool("project", {"action": "note", "project": "Сайт", "title": "План", "text": "1. Главная"})
        self.assertIn("01_Projects/Сайт/План.md", r["content"][0]["text"])
        r = server.call_tool("project", {"action": "show", "project": "Сайт"})
        self.assertIn("ПАПКА В OBSIDIAN: 01_Projects/Сайт", r["content"][0]["text"])
        r = server.call_tool("project", {"action": "milestone", "project": "Сайт", "title": "Без критерия"})
        self.assertTrue(r["isError"])


class ProjectChatTest(ProjectCase):
    """Чат проекта: своя нить, блок <project> в запросе головы, файлы — в папку проекта."""

    def setUp(self) -> None:
        super().setUp()
        from arvix.telegram.bot import Bot
        from tests.test_telegram import OWNER, FakeAPI, FakeBrain

        self.brain = FakeBrain()
        self.bot = Bot(self.core, FakeAPI(), self.brain, OWNER, sleep=lambda _s: None)

    def test_project_chat_thread_and_context(self):
        pid = self.project()
        self.core.message_in("общий разговор про сон")
        self.brain.answers.append({"reply": "Ставлю этап MVP.", "actions": [
            {"type": "set_milestone", "project": pid, "title": "MVP", "dod": "/today отвечает"}]})
        api.project_chat(pid, "с чего начать?")(self.bot)
        call = self.brain.calls[-1]
        self.assertIn(f'<project id="{pid}">', call["system"])
        self.assertNotIn("общий разговор про сон", call["system"])  # история — нить проекта
        thread = api.project_messages(self.core, pid)
        self.assertEqual([m["who"] for m in thread], ["me", "arvix"])
        self.assertNotIn("с чего начать?", [m["text"] for m in api.messages_view(self.core)])  # общий чат чистый
        self.assertEqual(projects.next_step(self.core, self.core.state.projects[pid])["title"], "MVP")

    def test_file_in_project_chat_goes_to_project_folder(self):
        pid = self.project()
        self.brain.answers.append({"reply": "Вижу парсер.", "actions": []})
        api.project_upload(pid, b"print('hi')\n", "parser.py", "text/x-python", "посмотри код")(self.bot)
        files = [f["path"] for f in projects.note_files(self.core, self.core.state.projects[pid])]
        self.assertTrue(any(f.startswith("01_Projects/Бот для расписания/Файлы/") and f.endswith("parser.py") for f in files), files)


class FixedBrain:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def ask(self, **kw):
        self.calls.append(kw)
        return self.answers.pop(0) if self.answers else None


class RoadmapGenerationTest(ProjectCase):
    """D56: Arvix предлагает ОДИН следующий проект — или говорит, что проект не нужен. Раньше цепочка
    из 3–6 проектов на цель за два нажатия дала девять «отложенных», половина из них — не проекты."""

    def goal(self, title="Стать бэкенд-разработчиком"):
        return self.core.set_goal(title, why="работа мечты", kind="main")

    def test_one_next_project_becomes_idea_with_milestones(self):
        from arvix import project_roadmap

        goal = self.goal()
        done = self.project("Бот расписания", goal_id=goal)
        projects.set_project(self.core, project_id=done, status="done", reason="бот работает у класса, 12 человек")
        brain = FixedBrain({"summary": "Дальше — HTTP и базы.", "projects": [
            {"title": "REST API заметок", "why": "HTTP и базы", "kind": "code", "purposes": ["skill", "portfolio", "чушь"],
             "expectation": "API в интернете с документацией", "weeks": 4, "weekly_min": 180, "skills": ["FastAPI"],
             "milestones": [{"title": "CRUD", "dod": "5 эндпоинтов с тестами"}, {"title": "Без критерия", "dod": ""}],
             "resources": [{"title": "FastAPI docs", "url": "https://fastapi.tiangolo.com", "kind": "doc"},
                           {"title": "Выдуманная", "url": "не ссылка", "kind": "doc"}]},
            {"title": "Второй проект сверх одного", "why": "x", "expectation": "x", "milestones": []},
        ]})
        result = project_roadmap.generate(self.core, brain, goal, system="SYS")
        self.assertEqual(result["created"], ["REST API заметок"])  # второй из ответа код не берёт
        self.assertIn("Бот расписания", brain.calls[0]["prompt"])  # существующее модель видит
        self.assertIn("ОДИН или ни одного", brain.calls[0]["system"])
        new = projects.roadmap_chain(self.core, goal)[-1]
        self.assertEqual((new["status"], new["by"], new["order"], new["weeks"]), ("idea", "arvix", 2, 4))
        self.assertEqual(new["purposes"], ["skill", "portfolio"])
        self.assertEqual([m["title"] for m in projects.milestones(self.core, new["id"])], ["CRUD"])
        self.assertEqual([r["title"] for r in projects.resources(self.core, new["id"])], ["FastAPI docs"])
        self.assertTrue((self.vault / result["path"]).exists())
        with self.assertRaisesRegex(ArvixError, "недоступна"):
            project_roadmap.generate(self.core, FixedBrain(), self.goal("Сдать ОГЭ"), system="SYS")

    def test_open_step_blocks_without_asking_the_head(self):
        """Старый код спрашивал голову при любом нажатии и копил идеи; теперь сначала решает человек."""
        from arvix import project_roadmap

        goal = self.goal()
        pid = self.project("Бот расписания", goal_id=goal)
        brain = FixedBrain({"summary": "", "projects": [{"title": "Ещё", "why": "x", "expectation": "x", "milestones": []}]})
        with self.assertRaisesRegex(ArvixError, "доведи"):
            project_roadmap.generate(self.core, brain, goal, system="SYS")
        projects.set_project(self.core, project_id=pid, status="paused")
        with self.assertRaisesRegex(ArvixError, "Не нужен"):
            project_roadmap.generate(self.core, brain, goal, system="SYS")
        self.assertEqual(brain.calls, [])

    def test_too_many_untouched_ideas_block_new_ones(self):
        from arvix import project_roadmap

        for n, title in enumerate(("Монтаж роликов", "Сайт-визитка", "Олимпиадные задачи")):
            self.project(title, goal_id=self.goal(f"Цель {n}"), status="idea")
        with self.assertRaisesRegex(ArvixError, "Неначатых проектов уже 3"):
            project_roadmap.generate(self.core, FixedBrain(), self.goal("Новая цель"), system="SYS")

    def test_refused_project_is_not_suggested_again_even_reworded(self):
        from arvix import project_roadmap

        goal = self.goal("Поступить на EECS")
        pid = self.project("Портфолио EECS: сайт, 2 проекта и английский", goal_id=goal, status="idea")
        projects.set_project(self.core, project_id=pid, status="dropped", reason="Не нужен — убран из списка кнопкой ✕")
        brain = FixedBrain({"summary": "Портфолио нужно.", "projects": [
            {"title": "Сайт-портфолио для EECS и английский", "why": "x", "expectation": "сайт", "milestones": []}]})
        result = project_roadmap.generate(self.core, brain, goal, system="SYS")
        self.assertEqual(result["created"], [])
        self.assertIsNone(result["path"])
        self.assertIn("ОТКАЗАЛСЯ ИЛИ ЗАКРЫЛ", brain.calls[0]["prompt"])
        self.assertIn("Портфолио EECS", brain.calls[0]["prompt"])
        self.assertTrue(project_roadmap.similar("Пакет для поступления в Школу Газпром Бишкек", "Пакет поступления: школа Газпром"))
        self.assertFalse(project_roadmap.similar("Бот расписания", "REST API заметок"))

    def test_head_may_answer_that_no_project_is_needed(self):
        from arvix import project_roadmap

        goal = self.goal("Режим сна и 2 часа глубокой работы")
        brain = FixedBrain({"summary": "", "not_project": "Это привычка: блок 45 минут каждый день — в распорядок, не проект.", "projects": []})
        result = project_roadmap.generate(self.core, brain, goal, system="SYS")
        self.assertEqual((result["created"], result["path"]), ([], None))
        self.assertIn("привычка", result["not_project"])
        self.assertEqual(self.core.state.projects, {})

    def test_list_shows_goals_without_projects_apart(self):
        """Пятнадцать целей пустыми группами с «предложить» прятали сами проекты (скриншот владельца 21.11)."""
        exam, blog = self.goal("Сдать ОГЭ"), self.goal("Запустить блог")
        idea = self.project("Регулярность: 2 поста в неделю", goal_id=blog, status="idea")
        work = self.project("Ниша и 3 пробных поста", goal_id=blog)
        view = api.projects_view(self.core)
        self.assertEqual([g["goal"]["id"] for g in view["groups"]], [blog])
        self.assertEqual([p["id"] for p in view["groups"][0]["projects"]], [work, idea])  # в работе — сверху
        self.assertEqual([g["id"] for g in view["idle_goals"]], [exam])
        self.assertEqual(view["ideas"], 1)
        projects.set_project(self.core, project_id=idea, status="dropped", reason="Не нужен — убран из списка кнопкой ✕")
        view = api.projects_view(self.core)
        self.assertEqual([p["id"] for p in view["groups"][0]["projects"]], [work])
        self.assertEqual([c["id"] for c in view["closed"]], [idea])  # вернуть можно из «Завершённых»