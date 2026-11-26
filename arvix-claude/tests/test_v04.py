"""Ревизия 0.4: разговор без команд, вёрстка, память без сжатия, погода, приложение и API."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from arvix import weather
from arvix.brain import Brain, apply_actions
from arvix.memory import Memory, export_transcripts, stems
from arvix.telegram import fmt
from arvix.telegram import templates as tpl
from arvix.web import api as web_api
from arvix.web.auth import app_token, authorize, check_init_data, sign_init_data
from arvix.web.hub import Hub
from arvix.web.server import Server, WebApp, make_handler

from tests.helpers import moscow
from tests.test_telegram import OWNER, BotCase


class FormatTest(BotCase):
    def test_every_sentence_starts_on_its_own_line(self) -> None:
        text = "В заметках так: четыре экзамена. Заявление до 1 марта 2027. Уточни у школы, т. е. у завуча! Пушкин А. С. писал."
        self.assertEqual(fmt.sentence_lines(text).splitlines(), [
            "В заметках так: четыре экзамена.", "Заявление до 1 марта 2027.", "Уточни у школы, т. е. у завуча!", "Пушкин А. С. писал.",
        ])

    def test_lists_become_dashes_and_paragraphs_survive(self) -> None:
        self.assertEqual(fmt.sentence_lines("План:\n- раз\n* два\n\nДальше."), "План:\n— раз\n— два\n\nДальше.")

    def test_html_escapes_and_keeps_bold(self) -> None:
        self.assertEqual(fmt.to_html("**Важно**: 2 < 3 & <b>"), "<b>Важно</b>: 2 &lt; 3 &amp; &lt;b&gt;")

    def test_head_reply_goes_out_as_html_line_by_line(self) -> None:
        self.brain.answers.append({"reply": "Сегодня **физика**. Потом зал.", "actions": []})
        self.text("что сегодня?")
        self.assertEqual(self.api.html[-1], "Сегодня <b>физика</b>.\nПотом зал.")
        self.assertEqual(self.api.last, "Сегодня физика.\nПотом зал.")  # запасной текст без звёздочек


class ActionsTest(BotCase):
    def test_remember_accepts_fact_in_text_field(self) -> None:
        """Скриншот владельца: «⚠️ Не выполнено: remember: 'fact'» — модель положила факт в text."""
        done, failed, _ = apply_actions(self.core, [{"type": "remember", "topic": "learning", "text": "пробник по информатике 21 ноября"}])
        self.assertEqual(failed, [])
        self.assertIn("пробник по информатике 21 ноября", [f["fact"] for f in self.core.state.facts.values()])

    def test_broken_action_is_explained_without_python_internals(self) -> None:
        _, failed, _ = apply_actions(self.core, [{"type": "complete_task"}])
        self.assertEqual(len(failed), 1)
        self.assertNotIn("'task'", failed[0])
        self.assertIn("отчёт", failed[0])

    def test_messages_and_facts_are_stored_whole(self) -> None:
        long = "объяснение " * 300
        self.core.message_out(long)
        self.core.remember("general", "факт " * 300)
        events = self.core.store.read(0)
        self.assertEqual(next(e for e in events if e.kind == "message_out").payload["text"], long)
        self.assertGreater(len(next(e for e in events if e.kind == "fact_remembered").payload["fact"]), 1000)


class NoCommandsTest(BotCase):
    def test_command_menu_is_empty_and_help_has_no_slashes(self) -> None:
        self.assertEqual(tpl.COMMANDS, [])
        self.assertNotIn("/", tpl.HELP)

    def test_week_in_words_becomes_schedule_proposal_without_interview(self) -> None:
        words = "Пн–пт школа до 14:00, после — физика и математика, в субботу зал"
        self.brain.answers.append({"reply": "Собираю распорядок.", "actions": [{"type": "plan_schedule", "wishes": words}]})
        self.brain.answers.append({"summary": "Учёба после школы, суббота — спорт.", "templates": [
            {"weekdays": [0, 1, 2, 3, 4], "day_type": "study", "blocks": [
                {"start": "08:00", "duration": 360, "title": "Школа", "sphere": "learning", "fixed": True},
                {"start": "16:00", "duration": 60, "title": "Физика", "sphere": "learning", "deep_work": True}]}]})
        self.text(words)
        self.assertIn(words, self.brain.calls[1]["prompt"])
        self.assertIn("📅 Распорядок недели", self.api.last)
        self.assertEqual(self.api.sent[-1][1], [[("✅ Сохранить", "s:save"), ("✏️ Поправить", "s:edit")]])

    def test_wish_to_study_becomes_block_steps_and_timer_in_one_answer(self) -> None:
        """D62: «давай позанимаемся» — не урок в приложении, а блок, шаги в его инструментах и таймер одним ответом."""
        self.brain.answers.append({"reply": "Начинаем.", "actions": [
            {"type": "add_task", "title": "Физика", "sphere": "learning", "start": "10:00", "duration_min": 45},
            {"type": "task_guide", "steps": [{"do": "§44 — правило и пример", "tool": "Учебник", "min": 15},
                                             {"do": "каталог → №8: 5 задач", "tool": "Решу ОГЭ", "min": 30}],
             "done": "4 из 5 верно"},
            {"type": "start_focus", "task": "Физика", "minutes": 45}]})
        self.text("давай позанимаемся физикой 45 минут")
        task = next(t for t in self.core.state.tasks.values() if t.title == "Физика")
        self.assertEqual((task.sphere, task.duration_min), ("learning", 45))
        self.assertEqual([s["tool"] for s in task.guide["steps"]], ["Учебник", "Решу ОГЭ"])  # шаги — к блоку этого ответа
        self.assertEqual(self.core.store.kv_get("focus")["task_id"], task.id)
        self.assertTrue(any("🧭 шаги к «Физика»: 2" in t for t in self.api.texts))  # квитанция, следом — строка таймера
        self.assertEqual(len(self.brain.calls), 1)  # один вызов головы — ни плана урока, ни проверки

    def test_timer_in_words_starts_focus(self) -> None:
        self.brain.answers.append({"reply": "Засёк.", "actions": [{"type": "start_focus", "minutes": 30}]})
        self.text("засеки 30 минут")
        self.assertEqual(self.core.store.kv_get("focus")["minutes"], 30)

    def test_ui_actions_are_not_reported_as_failures(self) -> None:
        self.brain.answers.append({"reply": "Вот день.", "actions": [{"type": "show_day"}]})
        self.text("что у меня сегодня")
        self.assertFalse(any("Не выполнено" in t for t in self.api.texts))
        self.assertIn("📋", self.api.last)


class DialogTest(BotCase):
    start = moscow(2026, 11, 2, 9, 0)

    def system(self) -> str:
        return self.brain.calls[-1]["system"]

    def test_first_message_of_the_day_gets_greeting_hint_once(self) -> None:
        self.brain.answers += [{"reply": "Привет.", "actions": []}, {"reply": "Ок.", "actions": []}]
        self.text("как дела")
        self.assertIn("Первое сообщение человека за сегодня", self.system())
        self.assertNotIn("отдельным сообщением", self.system())  # приветствие — первой строкой того же ответа (D46)
        self.text("понял")
        self.assertNotIn("Первое сообщение человека за сегодня", self.system())

    def test_late_evening_asks_to_say_goodnight(self) -> None:
        self.at(moscow(2026, 11, 2, 23, 10))
        self.brain.answers.append({"reply": "Спокойной ночи.", "actions": []})
        self.text("всё, иду спать")
        self.assertIn("пожелай спокойной ночи", self.system())


class WeatherTest(BotCase):
    def test_weather_question_without_city_asks_for_it(self) -> None:
        self.brain.answers.append({"reply": "В каком ты городе?", "actions": []})
        self.text("какая сегодня погода?")
        self.assertIn("Город человека неизвестен", self.brain.calls[-1]["system"])

    def test_weather_comes_from_code_and_is_cached(self) -> None:
        self.core.profile_set("city", "Санкт-Петербург")
        calls: list[str] = []

        def fake_get(url: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
            calls.append(url)
            if "geocoding" in url:
                return {"results": [{"name": "Санкт-Петербург", "latitude": 59.94, "longitude": 30.31}]}
            return {"current": {"temperature_2m": -3.4, "apparent_temperature": -8, "weather_code": 73, "wind_speed_10m": 5.2},
                    "daily": {"temperature_2m_min": [-5, -7], "temperature_2m_max": [-1, -2],
                              "precipitation_probability_max": [70, 20], "weather_code": [73, 3]}}

        original = weather._get
        weather._get = fake_get
        try:
            block = weather.weather_block(self.core)
            weather.weather_block(self.core)
        finally:
            weather._get = original
        self.assertIn("Санкт-Петербург сейчас −3°, ощущается −8°, снег, ветер 5 м/с", block)
        self.assertIn("Сегодня −5°…−1°, снег, осадки 70%", block)
        self.assertEqual(len(calls), 2)  # второй раз — из кэша

    def test_only_weather_words_trigger_lookup(self) -> None:
        self.assertTrue(weather.asks_weather("Что надеть, холодно?"))
        self.assertFalse(weather.asks_weather("Сделал физику"))


class MemoryTest(BotCase):
    def test_old_conversation_is_recalled_verbatim(self) -> None:
        self.core.message_in("Пробник по информатике будет 21 ноября в кабинете 305")
        for i in range(30):
            self.core.message_in(f"сообщение {i}")
            self.core.message_out(f"ответ {i}")
        self.brain.answers.append({"reply": "21 ноября, кабинет 305.", "actions": []})
        self.text("когда у меня пробник по информатике?")
        system = self.brain.calls[-1]["system"]
        self.assertIn("<recall>\nИз памяти", system)
        self.assertIn("кабинете 305", system)

    def test_recall_skips_what_is_already_in_history(self) -> None:
        self.core.message_in("Пробник по информатике завтра")
        self.brain.answers.append({"reply": "Да.", "actions": []})
        self.text("пробник по информатике когда?")
        self.assertNotIn("<recall>\nИз памяти", self.brain.calls[-1]["system"])

    def test_transcripts_folder_for_the_head(self) -> None:
        self.core.message_in("Привет")
        self.core.message_out("Привет.")
        self.core.remember("people", "друг Артём помогает с информатикой")
        folder = export_transcripts(self.core, self.tmp / "memory")
        self.assertIn("Привет", (folder / "2026-11-02.md").read_text(encoding="utf-8"))
        self.assertIn("друг Артём", (folder / "ФАКТЫ.md").read_text(encoding="utf-8"))

    def test_stems_drop_stop_words(self) -> None:
        self.assertEqual(stems("Что это за экзамены по информатике"), ["экзаме", "информ"])

    def test_index_is_incremental(self) -> None:
        memory = Memory(self.core)
        self.core.message_in("первое")
        self.assertEqual(memory.sync(), 1)
        self.assertEqual(memory.sync(), 0)


class BrainCommandTest(BotCase):
    def test_head_gets_memory_folder_and_web_tools(self) -> None:
        brain = Brain(self.core.cfg)
        (self.tmp / "data" / "memory").mkdir(parents=True, exist_ok=True)
        cmd = brain.command(system="s", prompt="p", schema={}, role="voice", vault_tools=True, web=True)
        tools = cmd[cmd.index("--tools") + 1]
        self.assertEqual(tools, "Read,Grep,Glob,WebSearch,WebFetch")
        self.assertIn(str(self.tmp / "data" / "memory"), cmd)

    def test_web_tools_can_be_switched_off(self) -> None:
        self.core.cfg.raw.setdefault("brain", {})["web_tools"] = False
        self.core.cfg.raw["brain"]["vault_tools"] = False
        cmd = Brain(self.core.cfg).command(system="s", prompt="p", schema={}, role="voice", vault_tools=True, web=True)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")


class CuriosityTest(BotCase):
    def test_writes_first_once_a_day_and_only_when_quiet(self) -> None:
        self.at(moscow(2026, 11, 2, 18, 35))
        self.brain.answers.append({"reply": "Как прошёл разговор с завучем про экзамены?", "actions": []})
        self.scheduler.curiosity(self.core.now())
        self.assertIn("завучем", self.api.last)
        sent = len(self.api.sent)
        self.scheduler.curiosity(self.core.now())
        self.assertEqual(len(self.api.sent), sent)

    def test_silent_while_focus_runs(self) -> None:
        self.at(moscow(2026, 11, 2, 18, 35))
        self.bot.start_focus(25)
        calls = len(self.brain.calls)
        self.scheduler.curiosity(self.core.now())
        self.assertEqual(len(self.brain.calls), calls)


class AuthTest(BotCase):
    TOKEN = "123:secret"

    def test_init_data_signed_by_telegram_for_owner(self) -> None:
        now = time.time()
        data = sign_init_data({"auth_date": int(now), "user": {"id": OWNER, "first_name": "D"}, "query_id": "q"}, self.TOKEN)
        self.assertTrue(check_init_data(data, self.TOKEN, OWNER, now))
        self.assertFalse(check_init_data(data, "123:other", OWNER, now))
        self.assertFalse(check_init_data(data, self.TOKEN, 999, now))
        self.assertFalse(check_init_data(data, self.TOKEN, OWNER, now + 8 * 24 * 3600))
        self.assertFalse(check_init_data(data.replace("first_name", "first_nam"), self.TOKEN, OWNER, now))

    def test_bearer_token(self) -> None:
        token = app_token(self.core)
        self.assertEqual(token, app_token(self.core))
        self.assertEqual(authorize({"Authorization": f"Bearer {token}"}, token=token, bot_token=self.TOKEN, owner_id=OWNER), "token")
        self.assertIsNone(authorize({"Authorization": "Bearer nope"}, token=token, bot_token=self.TOKEN, owner_id=OWNER))
        self.assertIsNone(authorize({}, token=token, bot_token=self.TOKEN, owner_id=OWNER))


class WebApiTest(BotCase):
    def run_main(self, fn: Any) -> Any:
        return fn(self.bot)

    def test_state_has_tasks_and_numbers(self) -> None:
        self.core.add_task("Физика", sphere="learning", start="16:00", duration_min=45)
        view = web_api.state_view(self.core)
        self.assertEqual(view["tasks"][0]["title"], "Физика")
        self.assertEqual(view["tasks"][0]["end"], "16:45")
        self.assertEqual(set(view["stats"]) & {"hp", "xp_into", "level", "streak", "season", "shields_left"}, set())
        self.assertIn("sleep_target", view["stats"])

    def test_red_mode_hides_numbers_and_list(self) -> None:
        self.core.add_task("Физика", start="16:00", duration_min=45)
        self.core.add_task("Зал", start="18:00", duration_min=60)
        self.core.sos(True)
        view = web_api.state_view(self.core)
        self.assertIsNone(view["stats"])
        self.assertEqual(len(view["tasks"]), 1)
        self.assertTrue(web_api.history_view(self.core)["gentle"])

    def test_task_ops_use_same_rules_as_buttons(self) -> None:
        task = self.core.add_task("Английский", start="12:00", duration_min=30, importance=2)
        done = self.run_main(web_api.task_op(task.id, "done", {}))
        self.assertNotIn("xp", done)
        self.assertEqual(self.core.state.tasks[task.id].status, "done")

    def test_add_task_from_app(self) -> None:
        result = self.run_main(web_api.add_task({"title": "Химия", "start": "19:00", "duration_min": 30, "sphere": "learning"}))
        self.assertEqual(result["task"]["start"], "19:00")

    def test_chat_from_app_answers_into_journal_not_telegram(self) -> None:
        self.brain.answers.append({"reply": "Привет. Я тут.", "actions": []})
        before = len(self.api.sent)
        self.run_main(web_api.chat("привет"))
        self.assertEqual(len(self.api.sent), before)
        messages = web_api.messages_view(self.core)
        self.assertEqual([m["channel"] for m in messages[-2:]], ["web", "web"])
        self.assertIn("Я тут.", messages[-1]["text"])

    def test_focus_from_app_stays_in_the_app(self) -> None:
        result = self.run_main(web_api.focus_start(25, None))
        self.assertEqual(result["focus"]["minutes"], 25)
        self.assertEqual(self.api.sent, [])  # таймер из приложения в Telegram не пишет (D50)
        self.run_main(web_api.focus_stop())
        self.assertIsNone(self.core.store.kv_get("focus"))

    def test_button_presses_are_hidden_from_feed(self) -> None:
        self.core.message_in("[кнопка p:refresh]")
        self.core.message_in("обычное")
        self.assertEqual([m["text"] for m in web_api.messages_view(self.core)], ["обычное"])


class ServerTest(BotCase):
    """Сервер целиком: HTTP, вход, очередь главного потока, статика."""

    def make_core(self) -> Any:
        # Бот и сервер в тесте живут в разных потоках — соединение общее, порядок держит замок.
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
            time.sleep(0.002)  # отпустить замок: иначе чтение /api/state голодает (замок нечестный) и ловит таймаут

    def tearDown(self) -> None:
        self.running = False
        self.worker.join(2)
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def call(self, path: str, body: Any = None, token: str | None = "auto") -> tuple[int, Any]:
        headers = {"Content-Type": "application/json"}
        if token == "auto":
            token = self.app.token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers, method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read()
                return response.status, json.loads(raw) if path.startswith("/api/") else raw.decode()
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read() or b"{}")

    def test_keep_alive_posts_do_not_share_a_body(self) -> None:
        """Браузер шлёт запросы по одному соединению: второй POST не должен получить тело первого,
        а следующий GET — споткнуться о непрочитанное тело (501)."""
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.app.token}"}
        titles = []
        for title in ("Первая задача", "Вторая задача"):
            conn.request("POST", "/api/tasks", json.dumps({"title": title, "start": "18:00"}), headers)
            response = conn.getresponse()
            titles.append(json.loads(response.read())["task"]["title"])
        conn.request("GET", "/api/state", headers=headers)
        response = conn.getresponse()
        body = json.loads(response.read())
        conn.close()
        self.assertEqual(titles, ["Первая задача", "Вторая задача"])
        self.assertEqual(response.status, 200)
        self.assertEqual(sorted(t["title"] for t in body["tasks"]), ["Вторая задача", "Первая задача"])

    def test_api_requires_login(self) -> None:
        status, body = self.call("/api/state", token=None)
        self.assertEqual(status, 401)
        self.assertIn("вход", body["error"].lower())

    def test_state_add_and_complete_over_http(self) -> None:
        status, added = self.call("/api/tasks", {"title": "Физика", "start": "16:00", "duration_min": 45})
        self.assertEqual(status, 200)
        task_id = added["task"]["id"]
        status, done = self.call(f"/api/tasks/{task_id}/done", {"report": "решил 6 задач"})
        self.assertEqual(status, 200)
        status, state = self.call("/api/state")
        self.assertEqual(state["tasks"][0]["status"], "done")

    def test_errors_come_back_as_words(self) -> None:
        status, body = self.call("/api/tasks/nope/done", {})
        self.assertEqual(status, 400)
        self.assertTrue(body["error"])

    def test_static_app_is_served(self) -> None:
        status, html = self.call("/", token=None)
        self.assertEqual(status, 200)
        self.assertIn("<title>Arvix</title>", html)
        status, html = self.call("/some/deep/link", token=None)
        self.assertIn("app.js", html)

    def test_pair_only_from_telegram(self) -> None:
        status, _ = self.call("/api/pair")
        self.assertEqual(status, 403)
