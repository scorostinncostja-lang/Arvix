"""Стратегия целей (D52): дубли, слияние, фокус, система цели, план стратега."""

import unittest

from arvix import strategy
from arvix.context import build_context

from tests.helpers import ArvixCase, moscow


class StrategyTest(ArvixCase):
    def goal(self, title, kind="yearly", **kw):
        return self.core.set_goal(title, why="потому что", kind=kind, **kw)

    def test_duplicates_found_and_merged_without_losing_projects(self):
        from arvix import projects

        a = self.goal("Сдать ОГЭ на высшие баллы: информатика, физика и обязательные предметы")
        b = self.goal("Сдать ОГЭ по русскому, математике, информатике и физике с максимальным баллом", deadline="2027-06-01")
        self.goal("Уровень B2 по английскому")
        pid = projects.set_project(self.core, "Пробники", why="тренировка", goal_id=a)
        dups = strategy.duplicates(self.core)
        self.assertEqual(len(dups), 1)
        keeper = dups[0]["keeper"]["id"]
        other = dups[0]["others"][0]["id"]
        strategy.merge(self.core, keeper, [other])
        self.assertEqual(self.core.state.goals[other]["status"], "dropped")
        self.assertEqual(self.core.state.goals[other]["merged_into"], keeper)
        self.assertEqual(self.core.state.projects[pid]["goal_id"], keeper)
        self.assertEqual(self.core.state.goals[keeper]["deadline"], "2027-06-01")
        self.assertEqual(strategy.duplicates(self.core), [])
        self.assertIn(b, (keeper, other))

    def test_focus_is_limited_and_survives_goal_edit(self):
        ids = [self.goal(t) for t in ("Английский B2", "Физика ОГЭ", "Подтянуться 15 раз", "Запустить блог")]
        now, later = strategy.focus(self.core)
        self.assertEqual(len(now), 3)
        self.assertEqual(len(later), 1)
        strategy.set_focus(self.core, ids[3], True)
        self.core.set_goal(goal_id=ids[3], metric="число")  # правка цели не стирает фокус
        self.assertTrue(self.core.state.goals[ids[3]]["focus"])
        self.assertIn(ids[3], [g["id"] for g in strategy.focus(self.core)[0]])

    def test_goal_without_system_then_habit_from_plan(self):
        gid = self.goal("Английский B2", deadline="2027-06-01", metric="тест B2")
        self.assertEqual(strategy.status(self.core, self.core.state.goals[gid]), "none")
        self.core.set_template(list(range(7)), "study", [{"start": "08:00", "duration": 360, "title": "Школа", "fixed": True}])
        plan_id = strategy.record_plan(self.core, gid, {"diagnosis": "нет системы", "summary": "", "items": [
            {"type": "habit", "title": "Английский: 15 слов", "why": "словарь", "weekdays": [0, 1, 2], "start": "09:00", "duration": 20},
            {"type": "bogus", "title": "мусор"}]})
        self.assertEqual(len(self.core.state.goal_plans[plan_id]["items"]), 1)
        done, failed = strategy.accept_all(self.core, plan_id)
        self.assertEqual(failed, [])
        block = next(b for b in self.core.state.templates[0]["blocks"] if b["title"] == "Английский: 15 слов")
        self.assertNotEqual(block["start"], "09:00")  # 09:00 занято школой — время подобрал код
        self.assertIn(strategy.goal_tag(gid), block["tags"])
        self.assertEqual(strategy.status(self.core, self.core.state.goals[gid]), "start")
        self.assertIsNone(strategy.pending_plan(self.core, gid))

    def test_context_has_strategy_but_not_in_red(self):
        self.goal("Английский B2")
        self.assertIn("СТРАТЕГИЯ", build_context(self.core))
        self.core.sos(True)
        self.assertNotIn("СТРАТЕГИЯ", build_context(self.core))

    def test_chat_task_with_goal_counts_minutes(self):
        from arvix.brain import apply_actions

        gid = self.goal("Физика ОГЭ")
        apply_actions(self.core, [{"type": "add_task", "title": "Физика: 5 задач", "start": "16:00", "duration_min": 40, "goal_id": gid}])
        task = next(t for t in self.core.state.tasks.values() if t.title == "Физика: 5 задач")
        self.core.complete_task(task.id, report="решил пять задач")
        self.assertEqual(strategy.engine(self.core, self.core.state.goals[gid])["week_min"], 40)


class FakeBot:
    def __init__(self, core):
        self.core = core

    def refresh_panel(self):
        return None


PLAN = {"diagnosis": "0 минут за месяц", "summary": "коротко и каждый день", "items": [
    {"type": "habit", "title": "Слова: 15 карточек", "why": "словарь", "weekdays": [0, 1, 2, 3, 4], "start": "16:00", "duration": 20},
    {"type": "learn", "title": "Present Perfect", "why": "слабое место"}]}


class GoalsAppTest(ArvixCase):
    """Вкладка «Цели» (D52): фокус, дубли, план Арвикса, окна заметок."""

    def setUp(self):
        super().setUp()
        self.core.set_template(list(range(7)), "study", [{"start": "08:00", "duration": 360, "title": "Школа", "fixed": True}])

    def test_goals_view_groups_by_focus_and_offers_merge(self):
        from arvix.web import api

        a = self.core.set_goal("Сдать ОГЭ по информатике и физике", why="поступление", kind="main")
        b = self.core.set_goal("ОГЭ: информатика и физика на высший балл", why="поступление", kind="yearly")
        self.core.set_goal("Английский B2", why="поступление", kind="yearly")
        view = api.goals_view(self.core)
        self.assertFalse(view["gentle"])
        self.assertEqual(len(view["dups"]), 1)
        self.assertEqual({view["dups"][0]["keeper"]["id"], view["dups"][0]["others"][0]["id"]}, {a, b})
        self.assertEqual(len(view["focus"]), 2)  # проигравший дубль не занимает место в фокусе
        api.goal_op(view["dups"][0]["keeper"]["id"], "merge", {"others": [view["dups"][0]["others"][0]["id"]]})(FakeBot(self.core))
        self.assertEqual(api.goals_view(self.core)["dups"], [])

    def test_goals_tab_is_quiet_in_red(self):
        from arvix.web import api

        self.core.set_goal("Английский B2", why="поступление")
        self.core.sos(True)
        view = api.goals_view(self.core)
        self.assertTrue(view["gentle"])
        self.assertNotIn("focus", view)

    def test_plan_accept_and_reject_through_the_app(self):
        from arvix.web import api

        gid = self.core.set_goal("Английский B2", why="поступление", deadline="2027-08-01", metric="IELTS 6.5")
        plan = strategy.record_plan(self.core, gid, PLAN)
        card = api.goal_view(self.core, gid)
        self.assertEqual(card["plan"]["id"], plan)
        self.assertEqual(card["status"], "none")
        r = api.goal_op(gid, "accept", {"plan": plan, "idx": 0})(FakeBot(self.core))
        self.assertIn("привычка", r["done"][0])
        self.assertIn("16:00", r["done"][0])  # после школы окно свободно — встало, где просил стратег
        r = api.goal_op(gid, "reject", {"plan": plan, "idx": "all"})(FakeBot(self.core))
        self.assertEqual(r["rejected"], 1)
        self.assertIsNone(r["goal"]["plan"])
        self.assertEqual(r["goal"]["system"]["habits"], 1)
        # отказ виден стратегу в следующий раз
        from arvix import strategist

        self.assertIn("ОТКЛОНИЛ РАНЬШЕ: учиться: Present Perfect", strategist.prompt(self.core, self.core.state.goals[gid]))

    def test_focus_from_the_app_and_limit(self):
        from arvix.core import ArvixError
        from arvix.web import api

        ids = [self.core.set_goal(t, why="надо") for t in ("Английский B2", "Физика ОГЭ", "Подтянуться 15 раз", "Запустить блог")]
        for gid in ids[:3]:
            api.goal_op(gid, "focus", {"on": True})(FakeBot(self.core))
        with self.assertRaisesRegex(ArvixError, "сначала одну в «потом»"):
            api.goal_op(ids[3], "focus", {"on": True})(FakeBot(self.core))
        api.goal_op(ids[0], "focus", {"on": False})(FakeBot(self.core))
        later = [g["id"] for g in api.goals_view(self.core)["later"]]
        self.assertIn(ids[0], later)

    def test_note_attach_goes_next_to_the_note_and_stays_in_vault(self):
        from arvix.core import ArvixError
        from arvix.vault import VaultError
        from arvix.web import api

        out = api.note_attach("01_Projects/Бот", b"\x89PNG fake", "скрин 1.png")(FakeBot(self.core))
        self.assertEqual(out["path"], "01_Projects/Бот/Файлы/скрин 1.png")
        self.assertEqual(out["embed"], "![[скрин 1.png]]")
        self.assertTrue((self.vault / out["path"]).exists())
        again = api.note_attach("01_Projects/Бот", b"other", "скрин 1.png")(FakeBot(self.core))
        self.assertNotEqual(again["path"], out["path"])  # одноимённый файл не затирается
        with self.assertRaises((ArvixError, VaultError)):
            api.note_attach("../../etc", b"x", "evil.png")(FakeBot(self.core))
        with self.assertRaises((ArvixError, VaultError)):
            api.note_attach(".obsidian", b"x", "a.png")(FakeBot(self.core))
        out = api.note_attach("01_Projects/Бот", b"x", "../../../evil.png")(FakeBot(self.core))
        self.assertEqual(out["path"], "01_Projects/Бот/Файлы/evil.png")  # имя без пути: выйти из папки нельзя


class StrategistBotTest(ArvixCase):
    """Стратег в Telegram: план кнопками, автозапуск раз в день для цели без системы, в 🟥 — молчит."""

    def setUp(self):
        super().setUp()
        from arvix.telegram.bot import Bot
        from arvix.telegram.scheduler import Scheduler
        from tests.test_telegram import OWNER, FakeAPI, FakeBrain

        self.api, self.brain = FakeAPI(), FakeBrain()
        self.bot = Bot(self.core, self.api, self.brain, OWNER, sleep=lambda _s: None)
        self.scheduler = Scheduler(self.bot)
        self.owner = OWNER
        self.core.set_template(list(range(7)), "study", [{"start": "08:00", "duration": 360, "title": "Школа", "fixed": True}])
        self.gid = self.core.set_goal("Английский B2", why="поступление", deadline="2027-08-01", metric="IELTS 6.5", kind="main")

    def press(self, data):
        self.bot.handle({"update_id": 2, "callback_query": {"id": "c", "from": {"id": self.owner}, "data": data,
                                                            "message": {"chat": {"id": self.owner}, "message_id": 5}}})

    def test_plan_message_buttons_accept_everything(self):
        self.brain.answers.append(PLAN)
        self.assertTrue(self.bot.run_goal_plan(self.gid))
        text, buttons = self.api.sent[-1]
        self.assertIn("Английский B2", text)
        self.assertIn("привычка: Слова: 15 карточек", text)
        plan_id = next(iter(self.core.state.goal_plans))
        self.assertEqual(buttons[0][0][1], f"g:{plan_id}:all")
        self.press(f"g:{plan_id}:all")
        self.assertIn("✅ привычка «Слова: 15 карточек»", self.api.sent[-1][0])
        self.assertEqual(strategy.status(self.core, self.core.state.goals[self.gid]), "start")

    def test_plan_goal_action_runs_after_the_reply_not_inside_it(self):
        from tests.test_telegram import OWNER

        self.brain.answers += [{"reply": "Собираю систему к цели.", "actions": [{"type": "plan_goal", "goal_id": self.gid}]}, PLAN]
        self.bot.handle({"update_id": 1, "message": {"from": {"id": OWNER}, "chat": {"id": OWNER}, "text": "собери план к английскому"}})
        texts = [t for t, _ in self.api.sent]
        reply = next(i for i, t in enumerate(texts) if "Собираю систему" in t)
        plan = next(i for i, t in enumerate(texts) if "Предлагаю" in t)
        self.assertLess(reply, plan)  # правило №2: совет — после ответа, а не в его цепочке
        self.assertEqual(self.brain.calls[1]["role"], "analyst")

    def test_scheduler_comes_once_a_day_and_not_in_red(self):
        self.core.message_out("привет")
        self.at(moscow(2026, 11, 2, 15, 5))
        self.core.message_in("я тут")
        self.core.log_social("тест")
        self.brain.answers.append(PLAN)
        self.scheduler.tick()
        self.assertEqual(sum(1 for c in self.brain.calls if c.get("schema", {}).get("properties", {}).get("diagnosis")), 1)
        self.scheduler.tick()
        self.assertEqual(sum(1 for c in self.brain.calls if c.get("schema", {}).get("properties", {}).get("diagnosis")), 1)
        self.assertIsNone(strategy.auto_candidate(self.core))  # план ждёт ответа — второй не нужен
        self.core.sos(True)
        self.assertFalse(self.bot.run_goal_plan(self.gid, auto=True))


class GoalsTabMarkupTest(unittest.TestCase):
    def test_no_wall_of_suggest_buttons_and_windows_are_managed(self):
        from tests.helpers import ROOT

        static = ROOT / "arvix" / "web" / "static"
        js = (static / "app.js").read_text()
        html = (static / "index.html").read_text()
        self.assertNotIn("✨ предложить", js)       # у каждой цели больше нет своей кнопки «предложить»
        self.assertNotIn("data-proadmap", js)
        self.assertIn('<span class="lbl">Цели</span>', html)
        for marker in ('"arvix_ws"', "data-wclose", "data-wmax", 'data-gact="add"', "wsPaste", "wsDrop", "note/attach"):
            self.assertIn(marker, js)
