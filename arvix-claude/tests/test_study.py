"""Раздел «Обучение» (D55): окна учебной сессии, тесты кодом, Arvix видит сессию, очередь тем — общая с проектами."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from arvix import projects, study
from arvix.core import ArvixError
from arvix.web import api as web_api
from arvix.web.hub import Hub
from arvix.web.server import Server, WebApp, make_handler

from tests.helpers import ArvixCase, moscow
from tests.test_telegram import OWNER, BotCase

QUIZ = {"type": "quiz", "title": "Закон Ома: вспомнить", "questions": [
    {"q": "I = ?", "options": ["U·R", "U/R", "R/U"], "answer": 1, "why": "ток прямо пропорционален напряжению"},
    {"q": "R удвоили — ток?", "options": ["вдвое больше", "вдвое меньше"], "answer": 1},
    {"q": "Объясни своими словами, что такое сопротивление", "a": "свойство проводника препятствовать току"},
]}
BOARD = {"type": "board", "title": "Парабола", "view": [-5, 5, -2, 10],
         "items": [{"kind": "fn", "expr": "x^2-2*x+1", "label": "y=(x-1)²"}, {"kind": "point", "x": 1, "y": 0, "label": "вершина"}]}
PLAN = {
    "topic": "Закон Ома для участка цепи", "why": "ОГЭ физика №8", "roadmap_node": "Постоянный ток (3/12)",
    "plan": [{"from_min": 0, "to_min": 5, "step": "Вспомни с пустого листа", "tool": "лист"},
             {"from_min": 5, "to_min": 40, "step": "Перышкин §44, задачи", "tool": "учебник"},
             {"from_min": 40, "to_min": 45, "step": "Проверка", "tool": "Arvix"}],
    "sources": ["Перышкин, 8 класс, §44"],
    "check": [{"q": "I при U=12 В и R=4 Ом?", "a": "3 А"}, {"q": "Как связаны I, U, R?", "a": "I=U/R"}, {"q": "R↑ — I?", "a": "уменьшится"}],
    "note_title": "Закон Ома",
}


class PanelCleanTest(ArvixCase):
    """Окно от головы проверяет код: кривое — отказ, а не битое окно в приложении."""

    def test_quiz_keeps_only_checkable_questions(self) -> None:
        panel = study.clean_panel({"type": "quiz", "questions": [
            {"q": "a?", "options": ["1", "2"], "answer": 1}, {"q": "без эталона"}, {"q": "b?", "options": ["1", "2"], "answer": 5},
            {"q": "открытый", "a": "эталон"}]})
        self.assertEqual([q["q"] for q in panel["questions"]], ["a?", "открытый"])
        self.assertEqual(panel["title"], "Тест")
        with self.assertRaises(ArvixError):
            study.clean_panel({"type": "quiz", "questions": [{"q": "без ответа"}]})

    def test_board_formula_is_whitelisted_no_code(self) -> None:
        self.assertEqual(study.safe_expr("y = 2*x^2 - sin(x)"), "2*x^2 - sin(x)")
        for bad in ("__import__('os')", "x; alert(1)", "window.x", "constructor"):
            self.assertIsNone(study.safe_expr(bad), bad)
        with self.assertRaises(ArvixError):
            study.clean_panel({"type": "board", "items": [{"kind": "fn", "expr": "fetch(x)"}]})
        board = study.clean_panel({**BOARD, "view": [5, 1, 0, 0]})
        self.assertEqual(board["view"], [-10.0, 10.0, -10.0, 10.0])  # перевёрнутые границы — по умолчанию

    def test_video_embeds_only_known_players(self) -> None:
        cases = {
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42": "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?start=42",
            "https://youtu.be/dQw4w9WgXcQ": "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
            "https://m.youtube.com/shorts/abcDEF12345": "https://www.youtube-nocookie.com/embed/abcDEF12345",
            "https://rutube.ru/video/0123456789abcdef0123456789abcdef/": "https://rutube.ru/play/embed/0123456789abcdef0123456789abcdef",
            "https://vimeo.com/76979871": "https://player.vimeo.com/video/76979871",
        }
        for url, embed in cases.items():
            self.assertEqual(study.embed_url(url)[0], embed, url)
        self.assertIsNone(study.embed_url("https://evil.example/watch?v=dQw4w9WgXcQ"))
        self.assertIsNone(study.embed_url("javascript:alert(1)"))
        other = study.clean_panel({"type": "video", "url": "https://stepik.org/lesson/1"})
        self.assertNotIn("embed", other)  # не плеер — просто ссылка
        search = study.clean_panel({"type": "video", "query": "закон Ома ОГЭ"})
        self.assertTrue(search["search"].startswith("https://www.youtube.com/results?search_query="))
        with self.assertRaises(ArvixError):
            study.clean_panel({"type": "video", "url": "ftp://x"})

    def test_note_path_cannot_escape_vault(self) -> None:
        with self.assertRaises(ArvixError):
            study.clean_panel({"type": "note", "path": "../../etc/passwd"})
        self.assertEqual(study.clean_panel({"type": "note", "path": "Конспекты/Ом"})["path"], "Конспекты/Ом.md")


class SessionJournalTest(ArvixCase):
    """Окна и ответы — события журнала; тест с вариантами проверяет код, эталоны не уходят до ответа."""

    def setUp(self) -> None:
        super().setUp()
        self.task = self.core.add_task("Физика: постоянный ток", sphere="learning", start="16:00", duration_min=45)

    def test_panel_answer_and_rebuild(self) -> None:
        quiz = study.add_panel(self.core, QUIZ, task_ref=self.task.id)
        hidden = study.public_panel(self.core.state.study[self.task.id]["panels"][0], None)
        self.assertNotIn("answer", hidden["questions"][0])
        self.assertNotIn("a", hidden["questions"][2])
        result = study.answer_quiz(self.core, quiz["id"], [1, 0, "мешает току"], task_ref=self.task.id)
        self.assertEqual(result, {"results": [True, False, None], "score_pct": 50})
        with self.assertRaises(ArvixError):
            study.answer_quiz(self.core, quiz["id"], [1, 1, ""], task_ref=self.task.id)  # второй раз — новый тест у Arvix
        shown = study.public_panel(self.core.state.study[self.task.id]["panels"][0], self.core.state.study[self.task.id]["answers"][quiz["id"]])
        self.assertEqual(shown["questions"][1]["answer"], 1)
        self.assertFalse(shown["questions"][1]["ok"])
        study.hide_panel(self.core, quiz["id"], task_ref=self.task.id)
        from arvix.state import State

        session = State.rebuild(self.core.store.read()).study[self.task.id]  # свёртка журнала с нуля — то же самое
        self.assertTrue(session["panels"][0]["hidden"])
        self.assertEqual(session["answers"][quiz["id"]]["score_pct"], 50)

    def test_replacing_quiz_drops_old_answer(self) -> None:
        quiz = study.add_panel(self.core, QUIZ, task_ref=self.task.id)
        study.answer_quiz(self.core, quiz["id"], [0, 0, ""], task_ref=self.task.id)
        study.add_panel(self.core, {**QUIZ, "id": quiz["id"], "questions": QUIZ["questions"][:2]}, task_ref=self.task.id)
        self.assertNotIn(quiz["id"], self.core.state.study[self.task.id]["answers"])
        self.assertEqual(len(self.core.state.study[self.task.id]["panels"]), 1)

    def test_only_learning_blocks_get_panels(self) -> None:
        chore = self.core.add_task("Убраться", sphere="chore", start="12:00")
        with self.assertRaises(ArvixError):
            study.add_panel(self.core, QUIZ, task_ref=chore.id)
        with self.assertRaises(ArvixError):
            study.add_panel(self.core, QUIZ)  # урока нет — какой сессии окно?

    def test_window_limit(self) -> None:
        for i in range(study.MAX_PANELS):
            study.add_panel(self.core, {"type": "text", "text": f"шаг {i}"}, task_ref=self.task.id)
        with self.assertRaises(ArvixError):
            study.add_panel(self.core, {"type": "text", "text": "ещё"}, task_ref=self.task.id)


class LearnQueueTest(ArvixCase):
    """Очередь «учиться» — одна на проекты и «Обучение»: теория или практика, без проекта тоже."""

    def test_practice_from_project_and_no_double_block(self) -> None:
        pid = projects.start(self.core, "Бот для класса на Python", source="web")
        item = projects.set_learn(self.core, "asyncio", project_ref=pid, kind="practice", source="web")
        task = projects.learn_start(self.core, item, minutes=45)
        self.assertEqual(task.title, "Практика: asyncio")
        self.assertEqual(task.project, pid)
        again = projects.learn_start(self.core, item, minutes=45)  # второе нажатие, другое устройство
        self.assertEqual(again.id, task.id)
        self.assertEqual(len([t for t in self.core.state.tasks.values() if t.sphere == "learning"]), 1)
        theory = projects.set_learn(self.core, "Закон Ома", source="web")  # без проекта — для раздела «Обучение»
        self.assertEqual(self.core.state.learn_items[theory]["kind"], "theory")
        self.assertEqual({x["topic"] for x in projects.learn_items(self.core)}, {"asyncio", "Закон Ома"})
        with self.assertRaises(ArvixError):
            projects.set_learn(self.core, "x", kind="lecture")


class SubjectTest(ArvixCase):
    def test_queue_prefix_is_not_a_subject(self) -> None:
        """Блок из очереди назывался «Практика: aiogram…» — и предметом урока становилась «Практика»:
        история уроков по предмету и каркас заметки («Предмет: Практика») шли мимо."""
        from arvix.lesson import subject_of

        self.assertEqual(subject_of("Практика: aiogram: первый хендлер"), "aiogram")
        self.assertEqual(subject_of("Учить: Тригонометрия — формулы приведения"), "Тригонометрия")
        self.assertEqual(subject_of("Физика: постоянный ток"), "Физика")
        self.assertEqual(subject_of("Учить"), "Учить")


class StudyBotTest(BotCase):
    """Урок с окнами: голова ставит окна в плане и из чата, видит ответы и заметку, учитывает тесты в оценке."""

    start = moscow(2026, 11, 2, 15, 58)

    def setUp(self) -> None:
        super().setUp()
        self.core.cfg.raw["schedule"]["midday"] = ""
        (self.vault / "Конспекты").mkdir()
        self.phys = self.core.add_task("Физика: постоянный ток", sphere="learning", start="16:00", duration_min=45, deep_work=True)

    def test_plan_brings_panels_and_bad_ones_are_dropped(self) -> None:
        self.brain.answers.append({**PLAN, "panels": [QUIZ, {"type": "board", "items": [{"kind": "fn", "expr": "eval(1)"}]}, BOARD]})
        self.bot.prepare_lesson(self.phys)
        panels = self.core.state.study[self.phys.id]["panels"]
        self.assertEqual([p["type"] for p in panels], ["quiz", "board"])
        self.assertIn("🪟 В приложении, «Обучение»: Закон Ома: вспомнить · Парабола", self.api.last)
        system = self.brain.calls[-1]["system"]
        self.assertIn("panels", json.dumps(self.brain.calls[-1]["schema"], ensure_ascii=False))
        self.assertIn("Окна сессии", system)

    def test_topic_from_project_queue_is_kept(self) -> None:
        """Старый код искал тему в роадмапе предмета и терял тему проекта: «Учить сейчас: asyncio» становился уроком про что угодно."""
        pid = projects.start(self.core, "Бот на Python", source="web")
        item = projects.set_learn(self.core, "asyncio", project_ref=pid, kind="practice", why="бот отвечает без задержек", source="web")
        task = projects.learn_start(self.core, item)
        self.bot.prepare_lesson(task)  # голова молчит — запасной план
        system = self.brain.calls[-1]["system"]
        self.assertIn("Тема задана очередью «учиться»: «asyncio» — практика, для проекта «Бот на Python»", system)
        self.assertIn("Это практика", system)
        self.assertEqual(self.core.state.lessons[-1]["topic"], "asyncio")

    def test_arvix_sees_session_and_adds_panel_from_chat(self) -> None:
        self.brain.answers.append({**PLAN, "panels": [QUIZ]})
        self.press(f"l:{self.phys.id}:go")
        quiz = self.core.state.study[self.phys.id]["panels"][0]
        study.answer_quiz(self.core, quiz["id"], [0, 1, "не знаю"])
        note = self.core.store.kv_get("lesson")["note"]
        self.vault.joinpath(note).write_text("# Закон Ома\n\nТок — это заряд за секунду. Сопротивление мешает току.\n", encoding="utf-8")
        self.brain.answers.append({"reply": "Первый ответ — ошибка: I = U/R. Нарисую.", "learning": False, "actions": [
            {"type": "study_panel", "panel": BOARD}]})
        self.text("почему я ошибся в первом?")
        system = self.brain.calls[-1]["system"]
        self.assertIn("<study>", system)
        self.assertIn("ошибка: «I = ?» → U·R", system)
        self.assertIn("Сопротивление мешает току", system)  # заметку человека Arvix читает
        self.assertIn("окно урока: доска «Парабола»", self.api.last)
        self.assertEqual([p["type"] for p in self.core.state.study[self.phys.id]["panels"]], ["quiz", "board"])
        # Проверка в конце: тесты сессии — в оценке
        self.bot.send_lesson_check()
        self.brain.answers.append({"score_pct": 60, "feedback": "Частично.", "gaps": ["I = U/R"]})
        self.text("3 А; I=U/R; уменьшится")
        self.assertIn("Ответы на тесты в окнах сессии", self.brain.calls[-1]["system"])
        self.assertIn("I = ? → неверно", self.brain.calls[-1]["system"])
        self.assertTrue(self.core.state.lessons[-1]["checked"])

    def test_study_panel_without_session_is_refused_honestly(self) -> None:
        self.brain.answers.append({"reply": "Держи тест.", "actions": [{"type": "study_panel", "panel": QUIZ}]})
        self.text("дай тест по физике")
        self.assertIn("окно урока — Учебной сессии сейчас нет", self.api.last)

    def test_learn_add_without_project(self) -> None:
        """Старый код требовал проект: «добавь в учёбу тригонометрию» в общем чате падал отказом."""
        self.brain.answers.append({"reply": "Добавил.", "actions": [{"type": "learn_add", "topic": "Тригонометрия", "kind": "theory"}]})
        self.text("добавь в учёбу тригонометрию")
        self.assertEqual([x["topic"] for x in self.core.state.learn_items.values()], ["Тригонометрия"])
        self.assertIn("учиться: Тригонометрия · теория", self.api.last)


class StudyViewTest(BotCase):
    """Что видит приложение: эталоны не утекают, в 🟥 — без цифр."""

    def setUp(self) -> None:
        super().setUp()
        self.phys = self.core.add_task("Физика: постоянный ток", sphere="learning", start="16:00", duration_min=45)

    def test_session_hides_reference_answers(self) -> None:
        self.brain.answers.append({**PLAN, "panels": [QUIZ]})
        self.bot.prepare_lesson(self.phys)
        view = web_api.study_view(self.core)
        raw = json.dumps(view, ensure_ascii=False)
        self.assertNotIn("3 А", raw)  # эталон проверки
        self.assertNotIn("препятствовать току", raw)  # эталон открытого вопроса теста
        self.assertEqual(view["session"]["topic"], "Закон Ома для участка цепи")
        self.assertTrue(view["session"]["live"])
        self.assertEqual(view["blocks"][0]["id"], self.phys.id)
        self.bot.send_lesson_check()
        self.assertEqual(len(web_api.study_view(self.core)["session"]["check"]), 3)  # вопросы — да, эталоны — нет
        self.assertNotIn("3 А", json.dumps(web_api.study_view(self.core), ensure_ascii=False))

    def test_red_mode_shows_nothing(self) -> None:
        self.core.safety_flag("high", "тест", source="l1")
        view = web_api.study_view(self.core)
        self.assertTrue(view["gentle"])
        self.assertNotIn("queue", view)

    def test_other_running_lesson_is_not_overwritten(self) -> None:
        self.brain.answers.append(dict(PLAN))
        self.press(f"l:{self.phys.id}:go")  # урок идёт, таймер
        math_ = self.core.add_task("Математика: уравнения", sphere="learning", start="18:00", duration_min=45)
        with self.assertRaises(ArvixError):
            web_api.study_open(math_.id)(self.bot)
        self.assertEqual(self.core.store.kv_get("lesson")["task_id"], self.phys.id)


class StudyThreadTest(BotCase):
    """D56: у учебной сессии своя нить. Раньше чат сессии был общим чатом с начала урока: владелец не закрыл
    урок в 18:55 — и в окне сессии в полночь висели вечерний разбор и «ложись»."""

    start = moscow(2026, 11, 2, 15, 58)

    def setUp(self) -> None:
        super().setUp()
        self.core.cfg.raw["schedule"]["midday"] = ""
        self.phys = self.core.add_task("Физика: постоянный ток", sphere="learning", start="16:00", duration_min=45)
        self.brain.answers.append(dict(PLAN))
        self.press(f"l:{self.phys.id}:go")

    def test_session_chat_is_its_own_thread(self) -> None:
        self.brain.answers.append({"reply": "Сопротивление — как узкая труба для воды.", "actions": [{"type": "study_panel", "panel": BOARD}]})
        web_api.study_chat(self.phys.id, "объясни сопротивление")(self.bot)
        system = self.brain.calls[-1]["system"]
        self.assertIn("<study>", system)
        self.assertNotIn("приветствия первой строкой", system)  # посреди урока «Привет» не нужен
        self.brain.answers.append({"reply": "Отбой через час, закругляйся.", "actions": []})
        self.text("что у меня вечером?")  # общий чат, урок всё ещё идёт
        self.assertNotIn("объясни сопротивление", self.brain.calls[-1]["prompt"])
        session = web_api.study_view(self.core)["session"]
        texts = [m["text"] for m in session["messages"]]
        self.assertEqual(texts[0], "объясни сопротивление")
        self.assertTrue(texts[1].startswith("Сопротивление — как узкая труба"))
        self.assertIn("окно урока: доска «Парабола»", texts[1])
        self.assertEqual(len(texts), 2)  # ни плана из общего чата, ни «отбой через час»
        general = [m["text"] for m in web_api.messages_view(self.core)]
        self.assertIn("что у меня вечером?", general)
        self.assertNotIn("объясни сопротивление", general)

    def test_thread_history_goes_to_the_head(self) -> None:
        self.brain.answers.append({"reply": "Нет, I = U/R.", "actions": []})
        web_api.study_chat(self.phys.id, "I = U·R?")(self.bot)
        self.brain.answers.append({"reply": "Отбой в 23:00.", "actions": []})
        self.text("когда отбой?")
        self.brain.answers.append({"reply": "Потому что ток делится на сопротивление.", "actions": []})
        web_api.study_chat(self.phys.id, "а почему делится?")(self.bot)
        prompt = self.brain.calls[-1]["raw_prompt"]
        self.assertIn("I = U·R?", prompt)
        self.assertNotIn("когда отбой?", prompt)


class StudyServerTest(BotCase):
    """HTTP целиком: открыть тему из очереди → блок и план фоном → ответ на тест."""

    def make_core(self) -> Any:
        from arvix.config import load_config
        from arvix.core import Core
        from arvix.store import Store

        cfg = load_config()
        cfg.raw["vault"] = str(self.vault)
        cfg.raw["timezone"] = "Europe/Moscow"
        return Core(cfg, Store(self.tmp / "arvix.db", shared=True))

    def setUp(self) -> None:
        super().setUp()
        self.core.cfg.raw["telegram"] = {"token": "123:secret", "owner_id": OWNER}
        self.hub = Hub()
        self.app = WebApp(self.core.cfg, self.hub, core=self.core)
        self.server = Server(("127.0.0.1", 0), make_handler(self.app))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.running = True
        self.worker = threading.Thread(target=self.loop, daemon=True)
        self.worker.start()

    def loop(self) -> None:
        while self.running:
            with self.app.lock:
                self.hub.run_pending(self.bot, 0.05)
            time.sleep(0.002)

    def tearDown(self) -> None:
        self.running = False
        self.worker.join(2)
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def call(self, path: str, body: Any = None) -> tuple[int, Any]:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.app.token}"}
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers, method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"{}")

    def test_open_from_queue_answer_and_add_video(self) -> None:
        status, r = self.call("/api/study/learn", {"topic": "Закон Ома", "kind": "theory"})
        self.assertEqual(status, 200, r)
        item = r["item"]
        self.assertEqual(r["study"]["queue"][0]["kind_ru"], "теория")
        self.brain.answers.append({**PLAN, "panels": [QUIZ]})
        status, opened = self.call("/api/study/open", {"item": item})
        self.assertEqual(status, 200, opened)
        self.assertTrue(opened["queued"])
        task_id = opened["task_id"]
        for _ in range(200):
            if self.core.store.kv_get("lesson"):
                break
            time.sleep(0.02)
        status, view = self.call("/api/study")
        session = view["session"]
        self.assertEqual(session["task"]["id"], task_id)
        self.assertEqual(session["item"]["topic"], "Закон Ома")
        self.assertIsNone(session["started"])  # план — да, таймер — только по ▶
        quiz = session["panels"][0]
        status, r = self.call(f"/api/study/{task_id}/answer", {"panel": quiz["id"], "answers": [1, 1, "мешает"]})
        self.assertEqual(status, 200, r)
        self.assertEqual(r["score_pct"], 100)
        self.assertTrue(r["session"]["panels"][0]["done"])
        status, r = self.call(f"/api/study/{task_id}/panel", {"panel": {"type": "video", "url": "https://youtu.be/dQw4w9WgXcQ"}})
        self.assertEqual(r["panel"]["by"], "me")
        status, r = self.call(f"/api/study/{task_id}/panel", {"panel": QUIZ})
        self.assertEqual(status, 400)  # тест себе не пишут — его ставит Arvix
        status, again = self.call("/api/study/open", {"item": item})
        self.assertEqual(again["task_id"], task_id)
        self.assertFalse(again["queued"])  # план уже есть — голову второй раз не зовём
