"""Сессия по этапам (D60): диагностика → разбор → практика → работа над ошибками → проверка; ответы числом
проверяет код; проверку не съедает «доброе утро»; повторения тем по интервалам; видео ищет код; чат с файлами и голосом."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from arvix import review, study, videos
from arvix.core import ArvixError
from arvix.lesson import fallback_plan, windows_line
from arvix.state import State
from arvix.web import api as web_api

from tests.helpers import ArvixCase, moscow
from tests.test_study import StudyServerTest
from tests.test_telegram import BotCase, FakeSTT

DIAG = [
    {"q": "Катеты 6 и 8. Гипотенуза?", "short": "10", "why": "√(36+64)=10", "skill": "Пифагор", "level": 1,
     "twin": {"q": "Катеты 5 и 12. Гипотенуза?", "short": "13", "why": "√(25+144)=13"}},
    {"q": "Гипотенуза 10. Радиус описанной окружности?", "short": "5", "why": "R = c/2", "skill": "R описанной", "level": 2,
     "twin": {"q": "Гипотенуза 26. R?", "short": "13", "why": "R = c/2"}},
    {"q": "cos острого угла — это…", "options": ["противолежащий/гипотенуза", "прилежащий/гипотенуза"], "answer": 1,
     "why": "cos = прилежащий катет / гипотенуза", "skill": "cos", "level": 1,
     "twin": {"q": "sin острого угла — это…", "options": ["противолежащий/гипотенуза", "прилежащий/гипотенуза"], "answer": 0}},
    {"q": "Катет 3, гипотенуза 5. cos угла при этом катете?", "short": "0,6", "accept": ["3/5"], "why": "3/5", "skill": "cos", "level": 3},
]
PRACTICE = [
    {"q": "Катеты 9 и 12. Гипотенуза?", "short": "15", "why": "√(81+144)=15", "skill": "Пифагор", "level": 1,
     "twin": {"q": "Катеты 8 и 15. Гипотенуза?", "short": "17", "why": "17"}},
    {"q": "Гипотенуза 18. R?", "short": "9", "why": "R = c/2", "skill": "R описанной", "level": 2},
]
SESSION = {
    "topic": "Прямоугольный треугольник: Пифагор, cos, R описанной", "why": "ОГЭ №15", "roadmap_node": "",
    "plan": [{"stage": "diag", "from_min": 0, "to_min": 7, "step": "4 задачи в тетради", "tool": "тетрадь"},
             {"stage": "learn", "from_min": 7, "to_min": 18, "step": "Разбор и заметка", "tool": "Атанасян §66"},
             {"stage": "practice", "from_min": 18, "to_min": 34, "step": "Задачи №15", "tool": "Решу ОГЭ"},
             {"stage": "fix", "from_min": 34, "to_min": 40, "step": "Ошибки", "tool": "журнал ошибок"},
             {"stage": "check", "from_min": 40, "to_min": 45, "step": "Проверка", "tool": "Арвикс"}],
    "diagnostic": DIAG,
    "skills": [{"name": "Пифагор", "explain": "c² = a² + b². Пример: 6, 8 → 10.", "source": "Атанасян, §54"},
               {"name": "R описанной", "explain": "Центр — середина гипотенузы, R = c/2.", "source": "Атанасян, §74"},
               {"name": "cos", "explain": "cos = прилежащий / гипотенуза.", "source": "Атанасян, §66"}],
    "practice": PRACTICE, "video_query": "радиус описанной окружности прямоугольного треугольника ОГЭ",
    "sources": ["Атанасян, Геометрия 7–9, §66"],
    "check": [{"q": "Как найти R описанной?", "a": "c/2"}, {"q": "Что такое cos?", "a": "прилежащий/гипотенуза"},
              {"q": "Катеты 7 и 24. Гипотенуза?", "a": "25: 7²+24²=625"}],
    "note_title": "Прямоугольный треугольник",
}

RUTUBE = {"results": [
    {"id": "3e331ec6ce1cb57e91e05e705bc6047a", "title": "Радиус описанной окружности", "duration": 300, "author": {"name": "Математика ОГЭ"}},
    {"id": "0123456789abcdef0123456789abcdef", "title": "Шортс", "duration": 40, "author": {"name": "x"}},
    {"id": "ffffffffffffffffffffffffffffffff", "title": "18+", "duration": 600, "is_adult": True, "author": {"name": "x"}},
]}
YT_DATA = {"contents": {"a": [{"videoRenderer": {"videoId": "hiCCjOxhT64", "title": {"runs": [{"text": "Задание 15: треугольники"}]},
                                                 "ownerText": {"runs": [{"text": "Математика на 5+"}]}, "lengthText": {"simpleText": "10:12"}}},
                              {"videoRenderer": {"videoId": "liveLIVE123", "title": {"runs": [{"text": "Стрим"}]}}},
                              {"videoRenderer": {"videoId": "longLONG123", "title": {"runs": [{"text": "Марафон"}]},
                                                 "lengthText": {"simpleText": "3:01:00"}}}]}}
YT_HTML = ("<html><script>var ytInitialData = " + json.dumps(YT_DATA, ensure_ascii=False) + ";</script></html>").encode()


def fake_fetch(url: str, accept: str) -> bytes:
    if "rutube.ru" in url:
        return json.dumps(RUTUBE).encode()
    if "youtube.com" in url:
        return YT_HTML
    raise OSError(url)


class ShortAnswerTest(ArvixCase):
    """Ответ числом — как в бланке ОГЭ: «0,6», «3/5», «13 см», корни в любом порядке."""

    def test_numbers_fractions_units_and_lists(self) -> None:
        q = {"short": "0,6", "accept": ["3/5"]}
        for given in ("0,6", "0.6", " 0,60 ", "3/5", "x=0,6", "ответ: 0.6"):
            self.assertTrue(study.match_short(given, q), given)
        for given in ("0,66", "6", "", "?", None):
            self.assertFalse(study.match_short(given, q), given)
        self.assertTrue(study.match_short("13 см", {"short": "13"}))
        self.assertTrue(study.match_short("−2", {"short": "-2"}))  # минус из клавиатуры телефона
        self.assertTrue(study.match_short("3;-2", {"short": "-2; 3"}))
        self.assertFalse(study.match_short("3", {"short": "-2; 3"}))
        self.assertTrue(study.match_short("Ёлка", {"short": "елка"}))
        self.assertTrue(study.match_short("312", {"short": "312"}))
        self.assertFalse(study.match_short("321", {"short": "312"}))  # соответствие — по порядку

    def test_question_needs_checkable_answer_and_twin_is_code_checked(self) -> None:
        q = study._question({"q": "a?", "short": "5", "skill": "s", "level": 9, "twin": {"q": "b?", "a": "открытый"}})
        self.assertEqual(q, {"q": "a?", "why": "", "short": "5", "skill": "s"})  # level вне 1–3 и открытый twin — отброшены
        self.assertIsNone(study._question({"q": "без ответа"}))


class StageFlowTest(ArvixCase):
    """Диагностика → уровень и слабые подтемы → ошибки → похожая задача закрывает ошибку. Всё — свёртка журнала."""

    def setUp(self) -> None:
        super().setUp()
        self.task = self.core.add_task("Математика: 45 минут", sphere="learning", start="16:00", duration_min=45)
        self.diag = study.add_panel(self.core, {"type": "quiz", "stage": "diag", "title": "Диагностика", "questions": DIAG}, task_ref=self.task.id)
        self.prac = study.add_panel(self.core, {"type": "quiz", "stage": "practice", "title": "Практика", "questions": PRACTICE}, task_ref=self.task.id)

    def session(self) -> dict[str, Any]:
        return study.session_of(self.core, self.task.id)

    def test_route_errors_and_fix(self) -> None:
        self.assertEqual(study.current_stage(self.session()), "diag")
        self.assertIsNone(study.route(self.session()))
        result = study.answer_quiz(self.core, self.diag["id"], ["10", "?", 0, "3/5"], task_ref=self.task.id)
        self.assertEqual(result, {"results": [True, False, False, True], "score_pct": 50})
        r = study.route(self.session())
        self.assertEqual((r["level"], r["right"], r["total"], r["next"]), ("gaps", 2, 4, "learn"))
        self.assertEqual(r["weak"], ["R описанной", "cos"])
        self.assertEqual(r["strong"], ["Пифагор"])
        errs = study.errors(self.session())
        self.assertEqual([e["key"] for e in errs], [f"{self.diag['id']}:1", f"{self.diag['id']}:2"])
        self.assertTrue(errs[0]["unknown"])
        # похожая задача: неверно — ошибка открыта, второй раз — нельзя; верно — закрыта
        wrong = study.fix_error(self.core, errs[0]["key"], task_ref=self.task.id, kind="rule", twin="12")
        self.assertEqual((wrong["closed"], wrong["twin_ok"], wrong["kind"]), (False, False, "rule"))
        with self.assertRaises(ArvixError):
            study.fix_error(self.core, errs[0]["key"], task_ref=self.task.id, twin="13")
        done = study.fix_error(self.core, errs[0]["key"], task_ref=self.task.id, done=True)
        self.assertTrue(done["closed"] and done["self"])
        right = study.fix_error(self.core, errs[1]["key"], task_ref=self.task.id, twin=0)
        self.assertTrue(right["closed"] and right["twin_ok"] and not right["self"])
        with self.assertRaises(ArvixError):
            study.fix_error(self.core, errs[1]["key"], task_ref=self.task.id, kind="lazy")
        self.assertEqual(study.open_gaps(self.core, self.task.id), [])
        study.set_stage(self.core, "fix", task_ref=self.task.id)
        rebuilt = State.rebuild(self.core.store.read()).study[self.task.id]
        self.assertEqual(rebuilt["stage"], "fix")
        self.assertEqual(rebuilt["fixes"], self.session()["fixes"])
        block = study.context_block(self.core, self.task.id)
        self.assertIn("Этап сейчас: Работа над ошибками (4/5)", block)
        self.assertIn("Диагностика: 2 из 4 (50%) — «Есть пробелы»; слабые подтемы: R описанной, cos", block)
        self.assertIn("причина: не знал правило", block)

    def test_public_view_hides_answers_until_tried(self) -> None:
        hidden = json.dumps([study.public_panel(p, None) for p in self.session()["panels"]], ensure_ascii=False)
        for secret in ('"short"', "√(36+64)", "Катеты 5 и 12"):  # ни эталона, ни решения, ни похожей задачи
            self.assertNotIn(secret, hidden.replace('"short": true', "").replace('"short": false', ""))
        study.answer_quiz(self.core, self.diag["id"], ["11", "5", 1, "0,6"], task_ref=self.task.id)
        errs = study.public_errors(self.session())
        self.assertEqual(len(errs), 1)
        self.assertEqual((errs[0]["given"], errs[0]["right"]), ("11", "10"))
        self.assertEqual(errs[0]["twin"], {"q": "Катеты 5 и 12. Гипотенуза?", "options": None, "short": True, "done": False})
        study.fix_error(self.core, errs[0]["key"], task_ref=self.task.id, twin="13")
        twin = study.public_errors(self.session())[0]["twin"]
        self.assertEqual((twin["ok"], twin["right"]), (True, "13"))
        self.assertEqual(study.route(self.session())["level"], "gaps")  # 3 из 4 = 75 %
        study.answer_quiz(self.core, self.prac["id"], ["15", "9"], task_ref=self.task.id)
        self.assertEqual(len(study.errors(self.session())), 1)  # практика без ошибок

    def test_know_level_skips_theory(self) -> None:
        study.answer_quiz(self.core, self.diag["id"], ["10", "5", 1, "0.6"], task_ref=self.task.id)
        r = study.route(self.session())
        self.assertEqual((r["level"], r["next"], r["weak"]), ("know", "practice", []))
        task2 = self.core.add_task("Физика: ток", sphere="learning", start="18:00", duration_min=45)
        quiz = study.add_panel(self.core, {"type": "quiz", "stage": "diag", "questions": DIAG}, task_ref=task2.id)
        study.answer_quiz(self.core, quiz["id"], ["?", "?", "?", "?"], task_ref=task2.id)
        self.assertEqual(study.route(study.session_of(self.core, task2.id))["level"], "new")

    def test_chat_panel_lands_on_current_stage_and_legacy_sessions_map(self) -> None:
        study.set_stage(self.core, "practice", task_ref=self.task.id)
        board = study.add_panel(self.core, {"type": "board", "items": [{"kind": "fn", "expr": "x^2"}]}, task_ref=self.task.id)
        self.assertEqual(board["stage"], "practice")
        legacy = {"panels": [{"id": "a", "type": "quiz", "questions": [{"q": "x", "short": "1"}]},
                             {"id": "b", "type": "quiz", "questions": [{"q": "y", "short": "2"}]}, {"id": "c", "type": "text", "text": "t"}],
                  "answers": {}}
        self.assertEqual([study.panel_stage(p, legacy) for p in legacy["panels"]], ["diag", "practice", "learn"])
        self.assertEqual(study.current_stage(legacy), "diag")


class StagePlanTest(ArvixCase):
    def test_plan_with_stages_and_old_plan_by_order(self) -> None:
        plan = study.stage_plan(SESSION["plan"], 45)
        self.assertEqual(list(plan), list(study.STAGES))
        self.assertEqual((plan["learn"]["from"], plan["learn"]["to"]), (7, 18))
        old = [{"from_min": 0, "to_min": 8, "step": "Пустой лист"}, {"from_min": 8, "to_min": 18, "step": "Учебник"},
               {"from_min": 18, "to_min": 33, "step": "6 задач"}, {"from_min": 33, "to_min": 40, "step": "Интерливинг"},
               {"from_min": 40, "to_min": 45, "step": "Каждую ошибку — в журнал; 3 вопроса"}]
        self.assertEqual({k: (v["from"], v["to"]) for k, v in study.stage_plan(old, 45).items()},
                         {"diag": (0, 8), "learn": (8, 18), "practice": (18, 40), "check": (40, 45)})

    def test_fallback_plan_covers_block_by_stages(self) -> None:
        plan = fallback_plan(45)
        self.assertEqual([s["stage"] for s in plan], list(study.STAGES))
        self.assertEqual((plan[0]["from_min"], plan[-1]["to_min"]), (0, 45))
        self.assertTrue(all(a["to_min"] == b["from_min"] for a, b in zip(plan, plan[1:])))


class VideoSearchTest(ArvixCase):
    """Видео ищет код: RuTube (JSON) и YouTube (ytInitialData); шортсы, трансляции, 18+ и марафоны — мимо."""

    def test_parse_filter_and_interleave(self) -> None:
        videos.FETCH = fake_fetch
        found = videos.search("радиус описанной окружности")
        self.assertEqual([(v["site"], v["title"], v["minutes"]) for v in found],
                         [("youtube", "Задание 15: треугольники", 10), ("rutube", "Радиус описанной окружности", 5)])
        self.assertEqual(found[0]["embed"], "https://www.youtube-nocookie.com/embed/hiCCjOxhT64")
        videos.FETCH = lambda url, accept: (_ for _ in ()).throw(OSError("нет сети"))
        self.assertEqual(videos.search("другой запрос"), [])  # сеть упала — пусто, без исключения
        self.assertEqual(len(videos.search("радиус описанной окружности")), 2)  # из кэша

    def test_video_panel_from_chat_gets_real_results(self) -> None:
        videos.FETCH = fake_fetch
        task = self.core.add_task("Математика: 45 минут", sphere="learning", start="16:00", duration_min=45)
        panel = study.add_panel(self.core, {"type": "video", "query": "треугольник ОГЭ 15"}, task_ref=task.id)
        self.assertEqual(panel["url"], "https://www.youtube.com/watch?v=hiCCjOxhT64")
        self.assertEqual(len(panel["results"]), 2)
        self.core.cfg.raw.setdefault("learning", {})["video_search"] = False
        bare = study.add_panel(self.core, {"type": "video", "query": "что-то"}, task_ref=task.id)
        self.assertNotIn("results", bare)
        self.assertTrue(bare["search"].startswith("https://www.youtube.com/results"))


class LessonStagesBotTest(BotCase):
    """Голова наполняет этапы одним вызовом; приложение получает окна по этапам, Telegram — этапы по минутам."""

    start = moscow(2026, 11, 2, 15, 58)

    def setUp(self) -> None:
        super().setUp()
        self.core.cfg.raw["schedule"]["midday"] = ""
        self.task = self.core.add_task("Математика: 45 минут", sphere="learning", start="16:00", duration_min=45, deep_work=True)
        videos.FETCH = fake_fetch

    def test_prepare_fills_stages(self) -> None:
        self.brain.answers.append(json.loads(json.dumps(SESSION)))
        self.bot.prepare_lesson(self.task)
        call = self.brain.calls[-1]
        self.assertGreaterEqual(call["timeout"], 300)  # длинная работа — свой таймаут, не общий 180 с
        for field in ("diagnostic", "skills", "practice", "video_query"):
            self.assertIn(field, call["schema"]["required"] + list(call["schema"]["properties"]))
        panels = self.core.state.study[self.task.id]["panels"]
        self.assertEqual([(p["type"], p["stage"]) for p in panels],
                         [("quiz", "diag"), ("text", "learn"), ("text", "learn"), ("text", "learn"), ("video", "learn"), ("quiz", "practice")])
        self.assertEqual(panels[1]["skill"], "Пифагор")
        self.assertIn("Атанасян, §54", panels[1]["text"])
        self.assertEqual(panels[4]["results"][0]["site"], "youtube")
        self.assertIn("Этапы:", self.api.last)
        self.assertIn("0–7  Диагностика: 4 задачи в тетради · тетрадь", self.api.last)
        self.assertIn("🪟 В приложении, «Обучение»: диагностика (4 задачи) · разбор (3) · видео · практика (2 задачи)", self.api.last)
        view = web_api.study_view(self.core)["session"]
        self.assertEqual([s["id"] for s in view["stages"]], list(study.STAGES))
        self.assertEqual((view["stage"], view["stages"][1]["from"], view["stages"][1]["steps"][0]["tool"]), ("diag", 7, "Атанасян §66"))
        raw = json.dumps(view, ensure_ascii=False)
        for secret in ("√(36+64)", "Катеты 5 и 12", "7²+24²=625"):
            self.assertNotIn(secret, raw)  # решения, похожие задачи и эталоны проверки — не до ответа

    def test_answering_diag_starts_timer_and_stage_moves(self) -> None:
        self.brain.answers.append(json.loads(json.dumps(SESSION)))
        self.bot.prepare_lesson(self.task)
        diag = self.core.state.study[self.task.id]["panels"][0]
        out = web_api.study_op(self.task.id, "answer", {"panel": diag["id"], "answers": ["10", "?", 0, "0,6"]})(self.bot)
        self.assertEqual(out["score_pct"], 50)
        self.assertTrue(self.core.store.kv_get("lesson")["started"])  # ответил на задачи — блок пошёл сам
        self.assertEqual(self.core.store.kv_get("focus")["task_id"], self.task.id)
        self.assertEqual(out["session"]["route"]["level"], "gaps")
        out = web_api.study_op(self.task.id, "stage", {"stage": "learn"})(self.bot)
        self.assertEqual(out["session"]["stage"], "learn")
        key = out["session"]["errors"][0]["key"]
        out = web_api.study_op(self.task.id, "fix", {"key": key, "twin": "13"})(self.bot)
        self.assertTrue(out["fixed"]["closed"])
        self.assertEqual(out["session"]["stages"][3]["errors"], 1)  # одна ошибка ещё открыта
        with self.assertRaises(ArvixError):
            web_api.study_op(self.task.id, "stage", {"stage": "lunch"})(self.bot)


class ResumeTest(BotCase):
    """Стенд 21.11: урок 18:30 подготовлен, потом открыта другая тема — и при возврате голова готовила блок заново,
    с новой темой (окружность вместо треугольника) поверх старых окон. Теперь урок возвращается из журнала как был."""

    start = moscow(2026, 11, 2, 15, 58)

    def test_replaced_lesson_comes_back_without_head(self) -> None:
        first = self.core.add_task("Математика: 45 минут", sphere="learning", start="18:30", duration_min=45)
        self.brain.answers.append(json.loads(json.dumps(SESSION)))
        web_api.study_prepare(first.id)(self.bot)
        panels = [p["id"] for p in self.core.state.study[first.id]["panels"]]
        other = self.core.add_task("Физика: ток", sphere="learning", start="16:00", duration_min=30)
        self.bot.prepare_lesson(other)  # голова молчит — запасной план, урок сменился
        self.assertEqual(self.core.store.kv_get("lesson")["task_id"], other.id)
        calls = len(self.brain.calls)
        opened = web_api.study_open(first.id)(self.bot)
        self.assertTrue(opened["queued"])
        web_api.study_prepare(first.id)(self.bot)
        self.assertEqual(len(self.brain.calls), calls)  # голову не звали
        lesson = self.core.store.kv_get("lesson")
        self.assertEqual((lesson["task_id"], lesson["topic"]), (first.id, SESSION["topic"]))
        self.assertEqual(lesson["check"][2]["a"], "25: 7²+24²=625")  # эталоны проверки — из журнала
        self.assertEqual([p["id"] for p in self.core.state.study[first.id]["panels"]], panels)  # без дублей
        view = web_api.study_view(self.core, first.id)["session"]
        self.assertEqual((view["stages"][2]["from"], view["stages"][2]["to"]), (18, 34))
        self.assertIn("Сессия на месте", view["messages"][-1]["text"])

    def test_early_check_is_not_time_up(self) -> None:
        task = self.core.add_task("Математика: 45 минут", sphere="learning", start="16:00", duration_min=45)
        self.brain.answers.append(json.loads(json.dumps(SESSION)))
        self.bot.prepare_lesson(task)
        out = web_api.study_check(task.id)(self.bot)
        self.assertEqual(len(out["session"]["check"]), 3)
        text = out["session"]["messages"][-1]["text"]
        self.assertTrue(text.startswith("Проверка по теме"), text)  # не «Время вышло» — сам закончил раньше


class CheckGuardTest(BotCase):
    """21.11, живой журнал: проверка урока ждала ответа, владелец проснулся и написал в общий чат «Доброе утро,
    только щас проснулся» — бот принял это за ответ, поставил 0 % и закрыл блок. Теперь не-ответ — разговор."""

    start = moscow(2026, 11, 2, 15, 58)

    def setUp(self) -> None:
        super().setUp()
        self.core.cfg.raw["schedule"]["midday"] = ""
        self.task = self.core.add_task("Математика: 45 минут", sphere="learning", start="16:00", duration_min=45)
        self.brain.answers.append(json.loads(json.dumps(SESSION)))
        self.bot.prepare_lesson(self.task)
        self.bot.send_lesson_check()

    def test_greeting_is_not_an_answer(self) -> None:
        self.brain.answers.append({"is_answer": False, "score_pct": 0, "feedback": "", "gaps": []})
        self.brain.answers.append({"reply": "Доброе утро. Проверка по треугольникам ждёт — ответишь, когда сядешь.", "actions": []})
        self.text("Доброе утро, только щас проснулся")
        self.assertIn("is_answer = false", self.brain.calls[-2]["system"])
        self.assertEqual(self.core.state.tasks[self.task.id].status, "planned")  # блок не закрыт
        self.assertIsNotNone(self.core.store.kv_get("lesson"))
        self.assertEqual(self.core.store.kv_get("tg_await")["kind"], "lesson_check")
        self.assertFalse(self.core.state.lessons[-1]["checked"])
        self.assertIn("Проверка по треугольникам ждёт", self.api.last)
        # голова молчит — тоже не закрываем: не знаем, ответ ли это
        self.text("а что сегодня ещё?")
        self.assertEqual(self.core.state.tasks[self.task.id].status, "planned")
        # из окна сессии — ответ, без вопроса «ответ ли это»
        self.brain.answers.append({"is_answer": False, "score_pct": 67, "feedback": "Два из трёх.", "gaps": ["R = c/2"]})
        web_api.study_chat(self.task.id, "1) c/2 2) прилежащий/гипотенуза 3) не знаю")(self.bot)
        self.assertIn("Он ответил из окна проверки", self.brain.calls[-1]["system"])
        self.assertEqual(self.core.state.tasks[self.task.id].status, "done")
        self.assertEqual(self.core.state.lessons[-1]["score"], 67)
        session = web_api.study_view(self.core, self.task.id)["session"]
        self.assertIn("Два из трёх.", session["messages"][-1]["text"])  # итог — в нити сессии
        self.assertIn("🔁 Повторение темы — завтра", session["messages"][-1]["text"])

    def test_real_answer_in_telegram_is_graded(self) -> None:
        self.brain.answers.append({"is_answer": True, "score_pct": 100, "feedback": "Всё верно.", "gaps": []})
        self.text("1) c/2 2) прилежащий к гипотенузе 3) 25")
        self.assertEqual(self.core.state.tasks[self.task.id].status, "done")
        self.assertIsNone(self.core.store.kv_get("tg_await"))


class ReviewTest(BotCase):
    """Повторения тем: после проверки — завтра; ≥ 80 % — интервал растёт, < 50 — с начала; без головы — банк сессии."""

    start = moscow(2026, 11, 2, 15, 58)

    def setUp(self) -> None:
        super().setUp()
        self.core.cfg.raw["schedule"]["midday"] = ""
        self.task = self.core.add_task("Математика: 45 минут", sphere="learning", start="16:00", duration_min=45)
        self.brain.answers.append(json.loads(json.dumps(SESSION)))
        self.bot.prepare_lesson(self.task)
        diag = self.core.state.study[self.task.id]["panels"][0]
        study.answer_quiz(self.core, diag["id"], ["10", "?", 0, "0,6"], task_ref=self.task.id)  # две ошибки, не закрыты
        self.bot.send_lesson_check()
        self.brain.answers.append({"is_answer": True, "score_pct": 60, "feedback": "Частично.", "gaps": ["R = c/2"]})
        web_api.study_chat(self.task.id, "1) c/2 2) не помню 3) 25")(self.bot)
        self.rid = next(iter(self.core.state.reviews))

    def test_schedule_after_lesson_and_intervals(self) -> None:
        r = self.core.state.reviews[self.rid]
        self.assertEqual((r["step"], r["due"], r["status"]), (0, "2026-11-03", "active"))
        self.assertEqual(r["gaps"][:2], ["R описанной", "cos"])  # незакрытые ошибки сессии — пробелы темы
        self.assertEqual(review.due(self.core), [])
        self.assertIn("ПОВТОРЕНИЯ ТЕМ: дальше: Прямоугольный треугольник", __import__("arvix.context", fromlist=["x"]).build_context(self.core))
        self.at(moscow(2026, 11, 3, 9, 0))
        self.assertIn("🔁 Повторить: Прямоугольный треугольник", __import__("arvix.telegram.templates", fromlist=["x"]).brief(self.core))
        today = self.core.today()
        steps = []
        for pct in (100, 100, 60, 30, 100):
            r = review.schedule(r, pct, today)
            steps.append((r["step"], r["due"]))
        self.assertEqual(steps, [(1, "2026-11-06"), (2, "2026-11-10"), (2, "2026-11-10"), (0, "2026-11-04"), (1, "2026-11-06")])
        r = {**r, "step": 4}
        self.assertEqual(review.schedule(r, 90, today)["status"], "done")

    def test_head_quiz_then_grading_reschedules(self) -> None:
        self.at(moscow(2026, 11, 3, 9, 0))
        self.brain.answers.append({"items": [
            {"review": self.rid, "q": "Гипотенуза 30. R?", "short": "15", "why": "R = c/2"},
            {"review": self.rid, "q": "Катеты 20 и 21. Гипотенуза?", "short": "29", "why": "√841"},
            {"review": "чужой", "q": "x?", "short": "1"}, {"review": self.rid, "q": "открытый", "a": "нет"}]})
        out = web_api.review_start()(self.bot)
        quiz = out["review"]["quiz"]
        self.assertEqual([i["q"] for i in quiz["items"]], ["Гипотенуза 30. R?", "Катеты 20 и 21. Гипотенуза?"])
        self.assertNotIn("15", json.dumps(quiz, ensure_ascii=False))  # эталон — после ответа
        self.assertIn("R описанной", self.brain.calls[-1]["system"])  # пробелы темы — голове
        again = web_api.review_start()(self.bot)  # второе нажатие — тот же тест, голову не зовём
        self.assertEqual(again["review"]["quiz"]["items"], quiz["items"])
        self.assertEqual(len(self.brain.calls), 3)  # урок, проверка, повторение — второй раз голову не звали
        out = web_api.review_op("answer", {"answers": ["15", "29"]})(self.bot)
        self.assertEqual(out["review"]["quiz"]["by_review"][0]["pct"], 100)
        r = self.core.state.reviews[self.rid]
        self.assertEqual((r["step"], r["due"]), (1, "2026-11-06"))
        with self.assertRaises(ArvixError):
            web_api.review_op("answer", {"answers": ["15", "29"]})(self.bot)
        self.assertEqual(State.rebuild(self.core.store.read()).reviews, self.core.state.reviews)

    def test_bank_when_head_is_down_and_drop(self) -> None:
        self.at(moscow(2026, 11, 3, 9, 0))
        out = web_api.review_start()(self.bot)  # голова молчит — задачи из сессии: похожие, которых не видел
        items = out["review"]["quiz"]["items"]
        self.assertEqual(len(items), 2)
        self.assertIn(items[0]["q"], {"Катеты 5 и 12. Гипотенуза?", "Гипотенуза 26. R?", "sin острого угла — это…"})
        self.assertEqual(self.core.state.review_quiz["by"], "bank")
        web_api.review_op("answer", {"answers": ["?", "?"]})(self.bot)
        self.assertEqual(self.core.state.reviews[self.rid]["due"], "2026-11-04")  # 0 % — завтра снова
        web_api.review_op("drop", {"review": self.rid})(self.bot)
        self.assertEqual(review.due(self.core, self.core.today() + timedelta(days=5)), [])

    def test_same_topic_again_updates_one_review(self) -> None:
        task2 = self.core.add_task("Математика: 45 минут", sphere="learning", start="18:00", duration_min=45)
        review.after_lesson(self.core, task2, topic="Прямоугольный треугольник: Пифагор, cos и R описанной", subject="Математика",
                            score=90, gaps=["sin"])
        self.assertEqual(len(self.core.state.reviews), 1)
        self.assertEqual(self.core.state.reviews[self.rid]["tasks"], [self.task.id, task2.id])
        self.assertIn("sin", self.core.state.reviews[self.rid]["gaps"])

    def test_red_mode_hides_reviews(self) -> None:
        self.at(moscow(2026, 11, 3, 9, 0))
        self.core.safety_flag("high", "тест", source="l1")
        self.assertTrue(web_api.study_view(self.core)["gentle"])
        with self.assertRaises(ArvixError):
            web_api.review_start()(self.bot)
        from arvix.context import build_context

        self.assertNotIn("ПОВТОРЕНИЯ ТЕМ", build_context(self.core))


class StudyChatMediaTest(BotCase):
    """В чат урока — фото решения из тетради и голос; ответ — в нити сессии, с блоком <study>."""

    start = moscow(2026, 11, 2, 15, 58)

    def setUp(self) -> None:
        super().setUp()
        self.core.cfg.raw["schedule"]["midday"] = ""
        self.task = self.core.add_task("Математика: 45 минут", sphere="learning", start="16:00", duration_min=45)
        self.brain.answers.append(json.loads(json.dumps(SESSION)))
        self.bot.prepare_lesson(self.task)

    def test_photo_and_voice_go_to_session_thread(self) -> None:
        self.brain.answers.append({"reply": "Во второй строке потерял квадрат: 8² = 64.", "actions": []})
        png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000")  # заголовок PNG
        web_api.study_upload(self.task.id, png, "решение.png", "image/png", "проверь")(self.bot)
        self.assertIn("<study>", self.brain.calls[-1]["system"])
        self.bot.stt = FakeSTT("почему R равно половине гипотенузы")
        self.brain.answers.append({"reply": "Прямой угол опирается на диаметр.", "actions": []})
        web_api.study_voice(self.task.id, b"OGG", "voice.ogg")(self.bot)
        texts = [m["text"] for m in web_api.study_view(self.core, self.task.id)["session"]["messages"]]
        self.assertTrue(texts[0].startswith("📎 решение.png — проверь"))
        self.assertIn("Во второй строке потерял квадрат", texts[1])
        self.assertEqual(texts[2], "🎙 почему R равно половине гипотенузы")
        self.assertIn("Прямой угол опирается на диаметр", texts[3])
        general = [m["text"] for m in web_api.messages_view(self.core)]
        self.assertFalse(any("решение.png" in t or "половине гипотенузы" in t for t in general))


class StudyStagesServerTest(StudyServerTest):
    """HTTP: этап, работа над ошибкой, «к проверке», повторение."""

    def test_open_from_queue_answer_and_add_video(self) -> None:  # тот же сценарий в родителе — здесь не повторяем
        pass

    def test_stage_fix_check_review_over_http(self) -> None:
        videos.FETCH = fake_fetch
        task = self.core.add_task("Математика: 45 минут", sphere="learning", start="16:00", duration_min=45)
        self.brain.answers.append(json.loads(json.dumps(SESSION)))
        status, opened = self.call("/api/study/open", {"task": task.id})
        self.assertEqual(status, 200, opened)
        for _ in range(200):
            if self.core.state.study.get(task.id):
                break
            __import__("time").sleep(0.02)
        status, view = self.call(f"/api/study?task={task.id}")
        diag = next(p for p in view["session"]["panels"] if p["stage"] == "diag")
        status, r = self.call(f"/api/study/{task.id}/answer", {"panel": diag["id"], "answers": ["11", "5", 1, "0,6"]})
        self.assertEqual((status, r["score_pct"]), (200, 75))
        key = r["session"]["errors"][0]["key"]
        status, r = self.call(f"/api/study/{task.id}/fix", {"key": key, "kind": "calc"})
        self.assertEqual((status, r["fixed"]["kind"], r["fixed"]["twin"]["done"]), (200, "calc", False))
        self.assertNotIn("13", json.dumps(r["fixed"], ensure_ascii=False))  # ответ похожей — только после попытки
        status, r = self.call(f"/api/study/{task.id}/stage", {"stage": "check"})
        self.assertEqual(r["session"]["stage"], "check")
        status, r = self.call(f"/api/study/{task.id}/check", {})
        self.assertEqual((status, len(r["session"]["check"])), (200, 3), r)
        self.brain.answers.append({"is_answer": True, "score_pct": 100, "feedback": "Верно.", "gaps": []})
        status, _ = self.call(f"/api/study/{task.id}/message", {"text": "1) c/2 2) прилежащий 3) 25"})
        for _ in range(200):
            if self.core.state.reviews:
                break
            __import__("time").sleep(0.02)
        self.assertEqual(len(self.core.state.reviews), 1)
        status, r = self.call("/api/study/review", {})
        self.assertEqual(status, 400)  # сегодня повторять нечего — тема вернётся завтра
        self.assertIn("повторять нечего", r["error"])
