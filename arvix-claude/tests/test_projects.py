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

    def test_money_and_channels(self):
        pid = self.project("Монтаж на заказ", kind="income")
        projects.log_money(self.core, pid, 1500, direction="out", category="реклама")
        cid = projects.set_channel(self.core, pid, "Reels", type="free", hypothesis="5 роликов → 10 заявок")
        projects.set_channel(self.core, pid, channel_id=cid, cost=1500, leads=10, clients=2, revenue=6000, status="works")
        projects.log_money(self.core, pid, "6 000", direction="in", channel_id=cid)
        s = projects.stats(self.core, self.core.state.projects[pid])
        self.assertEqual((s["income"], s["expense"], s["net"]), (6000, 1500, 4500))
        ch = s["channels"][0]
        self.assertEqual((ch["cpl"], ch["cpc"], ch["conversion"], ch["roi"]), (150, 750, 20.0, 300.0))
        # Траты проекта — не личные траты недели
        self.assertEqual(self.core.state.week_stats(self.core.today())["expenses"], {})
        with self.assertRaisesRegex(ArvixError, "гипотез"):
            projects.set_channel(self.core, pid, "Авито")

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
        projects.log_money(self.core, pid, 100, direction="in")
        projects.set_channel(self.core, pid, "Сарафан", hypothesis="друзья приведут 3")
        projects.log_entry(self.core, pid, "релиз 0.1", kind="release")
        rebuilt = State.rebuild(self.core.store.read())
        for attr in ("projects", "milestones", "project_log", "project_money", "channels"):
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
            {"type": "project_money", "project": pid, "amount": 300, "direction": "out", "category": "домен"},
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
        api.project_op(pid, "money", {"amount": "250", "direction": "in", "note": "первый заказ"})(bot)
        r = api.project_op(pid, "block", {"minutes": 30})(bot)
        self.assertEqual(r["task"]["project"], pid)
        r = api.project_save({"title": "Канал про ОГЭ", "why": "люди и навык", "kind": "community"})(bot)
        self.assertEqual(r["project"]["kind"], "community")
        self.assertEqual(projects.stats(self.core, self.core.state.projects[pid])["income"], 250)

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
        r = server.call_tool("project", {"action": "milestone", "project": "Сайт", "title": "Без критерия"})
        self.assertTrue(r["isError"])
