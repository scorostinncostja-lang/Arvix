"""Проекты (D43): карточка, этапы с DoD, время, застой, темп, деньги, каналы, блок в план,
портфолио в Obsidian, приложение и голова. Всё считается кодом — модель только читает."""

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
        self.assertTrue(any("продолжаем, пауза или закрываем" in i for i in projects.issues(self.core, p)))
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

    def test_channels_count_people_not_money(self):
        pid = self.project("Канал про монтаж", kind="content")
        cid = projects.set_channel(self.core, pid, "Reels", type="free", hypothesis="5 роликов → 10 откликов")
        projects.set_channel(self.core, pid, channel_id=cid, reach=2000, leads=10, clients=2, status="works")
        ch = projects.stats(self.core, self.core.state.projects[pid])["channels"][0]
        self.assertEqual((ch["response"], ch["conversion"]), (0.5, 20.0))
        self.assertNotIn("cost", ch)
        with self.assertRaisesRegex(ArvixError, "гипотез"):
            projects.set_channel(self.core, pid, "Авито")

    def test_kind_is_free_text_and_purposes_are_many(self):
        pid = self.project("Подкаст", kind="подкаст с друзьями", why="", purposes=["people", "fun", "научиться говорить"])
        p = self.core.state.projects[pid]
        self.assertEqual(projects.kind_label(p["kind"]), "подкаст с друзьями")
        self.assertEqual([projects.purpose_label(x) for x in p["purposes"]], ["единомышленники", "удовольствие", "научиться говорить"])
        legacy = self.project("Старый", kind="income")  # тип из 0.7 — показывается по-человечески
        self.assertEqual(projects.kind_label(self.core.state.projects[legacy]["kind"]), "заработок")
        with self.assertRaisesRegex(ArvixError, "зачем"):
            projects.set_project(self.core, "Без всего", why="", purposes=[])

    def test_resources_and_repo_normalization(self):
        pid = self.project(repo="https://github.com/me/schedule-bot.git")
        self.assertEqual(self.core.state.projects[pid]["repo"], "me/schedule-bot")
        rid = projects.set_resource(self.core, pid, "Документация aiogram", url="docs.aiogram.dev", kind="doc")
        self.assertEqual(self.core.state.resources[rid]["url"], "https://docs.aiogram.dev")
        projects.set_resource(self.core, pid, resource_id=rid, status="removed")
        self.assertEqual(projects.resources(self.core, pid), [])
        with self.assertRaises(ArvixError):
            projects.set_resource(self.core, pid, "Плохая", url="не ссылка вовсе")
        with self.assertRaises(ArvixError):
            self.project("Плохой репо", repo="не репозиторий")

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
        projects.set_channel(self.core, pid, "Сарафан", hypothesis="друзья приведут 3")
        self.core.emit("repo_activity", {"project_id": pid, "repo": "me/x", "meta": {"stars": 1},
                                         "commits": [{"sha": "abc", "message": "init", "at": "2026-11-02T08:00:00Z", "date": "2026-11-02"}]},
                       source="l0")
        projects.log_entry(self.core, pid, "релиз 0.1", kind="release")
        rebuilt = State.rebuild(self.core.store.read())
        for attr in ("projects", "milestones", "project_log", "channels", "resources", "repos", "commits"):
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
        self.assertEqual(api.projects_view(self.core)["projects"], [])

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
            {"type": "project_channel", "project": pid, "title": "Threads", "hypothesis": "10 постов → 3 заказа"},
        ], source="telegram")
        self.assertFalse(failed, failed)
        self.assertEqual(len(done), 5)
        block = next(t for t in self.core.state.tasks.values() if t.project == pid)
        self.assertEqual(block.local_date, self.core.today() + timedelta(days=1))
        self.assertEqual(block.start, "09:00")
        self.assertEqual(self.core.state.projects[pid]["weekly_min"], 180)
        _, failed, _ = brain.apply_actions(self.core, [{"type": "set_milestone", "project": pid, "title": "Без критерия"}])
        self.assertTrue(failed and "критерий" in failed[0])

    def test_app_view_and_ops(self):
        pid = self.project()
        projects.set_milestone(self.core, pid, "MVP", dod="работает")
        view = api.projects_view(self.core)
        card = view["projects"][0]
        self.assertEqual(card["id"], pid)
        self.assertEqual(card["milestones_total"], 1)
        detail = api.project_view(self.core, pid)
        self.assertEqual(detail["milestones"][0]["title"], "MVP")
        self.assertIn("issues", detail)

        class FakeBot:
            core = self.core

            def refresh_panel(self):
                return None

        bot = FakeBot()
        api.project_op(pid, "milestone", {"milestone": detail["milestones"][0]["id"], "status": "done"})(bot)
        api.project_op(pid, "resource", {"title": "Figma", "url": "https://figma.com", "kind": "tool"})(bot)
        r = api.project_op(pid, "block", {"minutes": 30})(bot)
        self.assertEqual(r["task"]["project"], pid)
        r = api.project_save({"title": "Канал про ОГЭ", "purposes": ["people", "brand"], "kind": "контент", "status": "idea"})(bot)
        self.assertEqual(r["project"]["purposes_ru"], ["единомышленники", "личный бренд"])
        self.assertEqual(api.project_view(self.core, pid)["resources"][0]["title"], "Figma")
        self.assertNotIn("income", api.projects_view(self.core)["projects"][0])

    def test_portfolio_note_is_a_block_and_keeps_owner_text(self):
        pid = self.project(skills=["Python", "Telegram API"])
        projects.log_entry(self.core, pid, "вышла версия 0.1", kind="release")
        rel = projects.export_note(self.core, pid)
        self.assertEqual(rel, "01_Projects/Бот для расписания.md")
        path = self.vault / rel
        path.write_text(path.read_text(encoding="utf-8") + "\nМои мысли.\n", encoding="utf-8")
        projects.export_note(self.core, pid)
        text = path.read_text(encoding="utf-8")
        self.assertIn("Мои мысли.", text)
        self.assertIn("Навыки: Python, Telegram API", text)
        self.assertIn("вышла версия 0.1", text)
        self.assertEqual(text.count("arvix:проект"), 2)  # открывающий и закрывающий маркер — один блок

    def test_brief_line(self):
        pid = self.project()
        projects.set_milestone(self.core, pid, "MVP", dod="работает")
        self.assertEqual(projects.brief_line(self.core), "Проекты: «Бот для расписания» → MVP")
        self.at(moscow(2026, 11, 12, 10))
        self.assertIn("10 дн без движения", projects.brief_line(self.core))


class ProjectStallTelegramTest(ProjectCase):
    """Застой: Арвикс пишет сам, раз в неделю на проект, кнопки ставят блок или паузу."""

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
        r = server.call_tool("project", {"action": "milestone", "project": "Сайт", "title": "Без критерия"})
        self.assertTrue(r["isError"])


class GithubTest(ProjectCase):
    """Коммиты — движение без слов. Сеть подменена: тест без интернета."""

    def fake(self, commits):
        calls = []

        def fetch(path, token):
            calls.append(path)
            if path.startswith("/users/"):
                return [{"full_name": "me/bot", "name": "bot", "stargazers_count": 2, "pushed_at": "2026-11-09T10:00:00Z",
                         "html_url": "https://github.com/me/bot"}]
            if path.endswith("/commits") or "/commits?" in path:
                return commits
            return {"pushed_at": "2026-11-09T10:00:00Z", "stargazers_count": 2, "open_issues_count": 1, "language": "Python"}
        return fetch, calls

    def test_sync_commits_become_movement_once(self):
        from arvix import github

        pid = self.project(repo="me/bot")
        self.at(self.start + timedelta(days=9))
        commit = {"sha": "a1b2c3d4e5f6a7", "html_url": "u", "commit": {"message": "парсер\n\nподробности",
                                                                      "author": {"date": "2026-11-09T21:30:00Z"}}}
        fetch, _ = self.fake([commit])
        self.assertEqual(github.sync(self.core, fetch=fetch, force=True), {pid: 1})
        c = projects.commits(self.core, pid)[0]
        self.assertEqual((c["message"], c["date"]), ("парсер", "2026-11-10"))  # 21:30 UTC — уже 10.11 по Москве
        s = projects.stats(self.core, self.core.state.projects[pid])
        self.assertEqual((s["idle_days"], s["commits_total"], s["commits_week"]), (1, 1, 1))
        events = len(self.core.store.read())
        self.assertEqual(github.sync(self.core, fetch=fetch, force=True), {pid: 0})
        self.assertEqual(len(self.core.store.read()), events)  # ничего нового — журнал не растёт
        self.assertEqual(github.sync(self.core, fetch=fetch), {})  # без force — не чаще раза в час

    def test_repos_list_marks_linked_and_caches(self):
        from arvix import github

        self.project(repo="me/bot")
        github.set_user(self.core, "https://github.com/me")
        fetch, calls = self.fake([])
        view = api.github_repos(lambda fn: fn(self.core), fetch=fetch)
        self.assertEqual(view["user"], "me")
        self.assertEqual(view["repos"][0]["project"], "Бот для расписания")
        api.github_repos(lambda fn: fn(self.core), fetch=fetch)
        self.assertEqual(len(calls), 1)  # второй раз — из кэша
        with self.assertRaises(ArvixError):
            github.set_user(self.core, "не имя!")


class RoadmapGenerationTest(ProjectCase):
    def test_roadmap_from_head_becomes_ideas_with_milestones(self):
        from arvix import project_roadmap

        goal = self.core.set_goal("Стать бэкенд-разработчиком", why="работа мечты", kind="main")
        self.project("Бот расписания", goal_id=goal)

        class Brain:
            def __init__(self):
                self.calls = []

            def ask(self, **kw):
                self.calls.append(kw)
                return {"summary": "От простого к сложному.", "projects": [
                    {"title": "Бот расписания", "why": "дубль", "expectation": "x", "milestones": []},
                    {"title": "REST API заметок", "why": "HTTP и базы", "kind": "code", "purposes": ["skill", "portfolio", "чушь"],
                     "expectation": "API в интернете с документацией", "weeks": 4, "weekly_min": 180, "skills": ["FastAPI"],
                     "milestones": [{"title": "CRUD", "dod": "5 эндпоинтов с тестами"}, {"title": "Без критерия", "dod": ""}],
                     "resources": [{"title": "FastAPI docs", "url": "https://fastapi.tiangolo.com", "kind": "doc"},
                                   {"title": "Выдуманная", "url": "не ссылка", "kind": "doc"}]},
                ]}

        brain = Brain()
        result = project_roadmap.generate(self.core, brain, goal, system="SYS")
        self.assertEqual(result["created"], ["REST API заметок"])
        self.assertIn("Бот расписания", brain.calls[0]["prompt"])  # существующее модель видит
        chain = projects.roadmap_chain(self.core, goal)
        new = chain[-1]
        self.assertEqual((new["status"], new["by"], new["order"], new["weeks"]), ("idea", "arvix", 2, 4))
        self.assertEqual(new["purposes"], ["skill", "portfolio"])
        self.assertEqual([m["title"] for m in projects.milestones(self.core, new["id"])], ["CRUD"])
        self.assertEqual([r["title"] for r in projects.resources(self.core, new["id"])], ["FastAPI docs"])
        self.assertTrue((self.vault / result["path"]).exists())

        class Down:
            def ask(self, **kw):
                return None

        with self.assertRaisesRegex(ArvixError, "недоступна"):
            project_roadmap.generate(self.core, Down(), goal, system="SYS")
