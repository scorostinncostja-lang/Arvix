"""Ответы на сообщения, как в Telegram (D52).

Человек отвечает цитатой — голова получает, на что именно; Arvix отвечает цитатой, когда без неё
непонятно, на что ответ: человек уже написал следующее или голова вернулась к раннему сообщению.
Раньше `reply_to_message` из Telegram выбрасывался: «а это зачем?» в ответ на вчерашний план
голова читала как вопрос о последнем сообщении."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from arvix.telegram.api import TelegramAPI
from arvix.web import api as web_api
from arvix.web.hub import Hub
from arvix.web.server import reply_id
from tests.test_telegram import OWNER, BotCase


class ReplyCase(BotCase):
    def say(self, text: str, tg_id: int, *, reply_to: dict[str, Any] | None = None, quote: str = "") -> None:
        msg: dict[str, Any] = {"message_id": tg_id, "from": {"id": OWNER}, "chat": {"id": OWNER}, "text": text}
        if reply_to:
            msg["reply_to_message"] = reply_to
        if quote:
            msg["quote"] = {"text": quote}
        self.bot.handle({"update_id": tg_id, "message": msg})

    def events(self, kind: str) -> list[Any]:
        return [e for e in self.core.store.read(0) if e.kind == kind]


class HumanQuotesTest(ReplyCase):
    def test_reply_to_arvix_message_reaches_the_head(self) -> None:
        self.bot.send("План на вечер: физика 19:00, английский 20:00")
        plan_tg = len(self.api.sent)  # FakeAPI: message_id = номер отправленного
        plan = self.events("message_out")[-1]
        self.assertEqual(plan.payload["tg_id"], plan_tg)
        self.brain.answers.append({"reply": "Физику можно сдвинуть.", "actions": []})
        self.say("а это зачем так поздно?", 1001, reply_to={"message_id": plan_tg, "from": {"is_bot": True}, "text": "План…"},
                 quote="физика 19:00")
        seen = self.brain.calls[-1]["system"]
        self.assertIn("<reply_to>\nЧеловек ответил цитатой", seen)
        self.assertIn("сообщение Arvix", seen)
        self.assertIn("физика 19:00, английский 20:00", seen)  # текст из журнала, а не обрезок Telegram
        self.assertIn("Выделенный фрагмент: «физика 19:00»", seen)
        incoming = self.events("message_in")[-1]
        self.assertEqual(incoming.payload["reply_to"], plan.id)
        self.assertEqual(incoming.payload["tg_id"], 1001)

    def test_reply_to_message_missing_from_journal_uses_telegram_text(self) -> None:
        self.brain.answers.append({"reply": "Помню.", "actions": []})
        self.say("и что с этим?", 1002, reply_to={"message_id": 7, "from": {"is_bot": True}, "text": "Старое сообщение до обновления",
                                                  "date": int((self.core.now() - timedelta(days=2)).timestamp())})
        seen = self.brain.calls[-1]["system"]
        self.assertIn("«Старое сообщение до обновления»", seen)
        self.assertNotIn("reply_to", self.events("message_in")[-1].payload)

    def test_plain_message_has_no_reply_block(self) -> None:
        self.brain.answers.append({"reply": "Привет.", "actions": []})
        self.say("привет", 1003)
        self.assertNotIn("Человек ответил цитатой", self.brain.calls[-1]["system"])

    def test_quote_of_older_message_is_not_an_answer_to_the_pending_question(self) -> None:
        self.bot.send("Вчерашний разбор: сон 6 ч")
        old_tg = len(self.api.sent)
        self.at(self.core.now() + timedelta(minutes=30))
        task = self.core.add_task("Физика", start="11:00", duration_min=30, importance=3, source="l0")
        self.bot.await_set("report", task=task.id)  # ждём отчёт по задаче
        self.brain.answers.append({"reply": "Про сон — да.", "actions": []})
        self.say("почему так мало?", 1004, reply_to={"message_id": old_tg, "from": {"is_bot": True}, "text": "Вчерашний разбор"})
        self.assertEqual(self.core.state.tasks[task.id].status, "planned")  # отчётом это не засчитано
        self.assertEqual(len(self.brain.calls), 1)

    def test_quote_of_the_question_itself_still_answers_it(self) -> None:
        task = self.core.add_task("Физика", start="11:00", duration_min=30, importance=3, source="l0")
        self.bot.send("Как прошла физика?")
        self.bot.await_set("report", task=task.id)
        self.say("решил 10 задач", 1005, reply_to={"message_id": len(self.api.sent), "from": {"is_bot": True}, "text": "Как прошла физика?"})
        self.assertEqual(self.core.state.tasks[task.id].status, "done")


class ArvixQuotesTest(ReplyCase):
    def test_no_quote_when_answer_follows_the_message(self) -> None:
        self.brain.answers.append({"reply": "Ок.", "actions": []})
        self.say("сделал зарядку", 1010)
        self.assertIsNone(self.api.replies[-1])
        self.assertNotIn("reply_to", self.events("message_out")[-1].payload)

    def test_quote_when_human_already_wrote_the_next_message(self) -> None:
        self.bot.more_incoming = lambda: True  # следующее сообщение ждёт в очереди
        self.brain.answers.append({"reply": "Про зарядку — молодец.", "actions": []})
        self.say("сделал зарядку", 1011)
        self.assertEqual(self.api.replies[-1], 1011)
        out = self.events("message_out")[-1]
        self.assertEqual(out.payload["reply_to"], self.events("message_in")[-1].id)

    def test_only_the_first_answer_quotes(self) -> None:
        self.bot.more_incoming = lambda: True
        self.brain.answers.append({"reply": "Собираю распорядок.", "actions": [{"type": "show_status"}]})
        self.say("покажи итоги", 1012)
        self.assertEqual(self.api.replies[-2], 1012)
        self.assertIsNone(self.api.replies[-1])

    def test_head_quotes_an_earlier_message_from_history(self) -> None:
        self.brain.answers.append({"reply": "Ок.", "actions": []})
        self.say("завтра контрольная по алгебре", 1020)
        first = self.events("message_in")[-1]
        self.brain.answers.append({"reply": "Про контрольную: повтори формулы.", "actions": [], "reply_to": first.id})
        self.say("а что мне сегодня делать?", 1021)
        seen = self.brain.calls[-1]["system"]
        self.assertIn(f"[#{first.id}] ЧЕЛОВЕК", seen)
        self.assertEqual(self.api.replies[-1], 1020)
        self.assertEqual(self.events("message_out")[-1].payload["reply_to"], first.id)

    def test_head_cannot_quote_what_it_was_not_shown(self) -> None:
        self.brain.answers.append({"reply": "Ок.", "actions": [], "reply_to": 99999})
        self.say("привет", 1030)
        self.assertIsNone(self.api.replies[-1])

    def test_history_marks_replies(self) -> None:
        self.bot.send("Отбой в 23:00")
        plan = self.events("message_out")[-1]
        self.brain.answers.append({"reply": "Ок.", "actions": []})
        self.say("давай в 23:30", 1040, reply_to={"message_id": plan.payload["tg_id"], "from": {"is_bot": True}, "text": "Отбой"})
        self.brain.answers.append({"reply": "Ок.", "actions": []})
        self.say("и ещё вопрос", 1041)
        self.assertIn(f"в ответ на #{plan.id}: давай в 23:30", self.brain.calls[-1]["system"])

    def test_proactive_messages_never_quote(self) -> None:
        self.bot.more_incoming = lambda: True
        self.bot.send("☀️ брифинг")
        self.assertIsNone(self.api.replies[-1])


class AppRepliesTest(ReplyCase):
    def test_app_reply_and_quote_in_the_feed(self) -> None:
        self.bot.send("Сегодня три задачи")
        target = self.events("message_out")[-1]
        self.brain.answers.append({"reply": "Да, три.", "actions": []})
        web_api.chat("а какие?", reply_to=target.id)(self.bot)
        self.assertIn("Сегодня три задачи", self.brain.calls[-1]["system"])
        feed = web_api.messages_view(self.core)
        mine = [m for m in feed if m["who"] == "me"][-1]
        self.assertEqual(mine["reply_to"], {"id": target.id, "who": "arvix", "text": "Сегодня три задачи"})
        self.assertNotIn("tg_id", self.events("message_in")[-1].payload)  # в приложении номеров Telegram нет

    def test_arvix_reply_in_the_app_carries_the_quote(self) -> None:
        self.bot.more_incoming = lambda: True
        self.brain.answers.append({"reply": "Отвечаю.", "actions": []})
        web_api.chat("первая мысль")(self.bot)
        feed = web_api.messages_view(self.core)
        self.assertEqual(feed[-1]["reply_to"]["text"], "первая мысль")

    def test_reply_id_parsing(self) -> None:
        self.assertEqual(reply_id(12), 12)
        self.assertEqual(reply_id("12"), 12)
        for junk in (None, "", "abc", "-3", 0, "1; drop"):
            self.assertIsNone(reply_id(junk))


class PlumbingTest(ReplyCase):
    def test_telegram_send_uses_reply_parameters(self) -> None:
        calls: list[dict[str, Any]] = []
        tg = TelegramAPI("t")
        tg.call = lambda method, **params: calls.append(params) or {"message_id": 5}  # type: ignore[method-assign]
        tg.send(OWNER, "ответ", html="ответ", reply_to=42)
        self.assertEqual(calls[-1]["reply_parameters"], {"message_id": 42, "allow_sending_without_reply": True})
        tg.send(OWNER, "без цитаты")
        self.assertNotIn("reply_parameters", calls[-1])

    def test_hub_sees_waiting_messages_only(self) -> None:
        hub = Hub()
        hub.post(lambda b: None, label="state")
        self.assertFalse(hub.chat_waiting())
        hub.post(lambda b: None, label="update 1", chat=True)
        self.assertTrue(hub.chat_waiting())


class ReactionsTest(ReplyCase):
    """Реакции (D52): сигнал, а не реплика — Arvix видит и учитывает; «непонятно» — объясняет проще."""

    def tg_react(self, tg_id: int, emoji: str, user: int = OWNER) -> None:
        new = [{"type": "emoji", "emoji": emoji}] if emoji else []
        self.bot.handle({"update_id": 77, "message_reaction": {"chat": {"id": OWNER}, "message_id": tg_id, "user": {"id": user},
                                                               "date": 0, "old_reaction": [], "new_reaction": new}})

    def test_telegram_reaction_is_logged_and_silent(self) -> None:
        self.bot.send("Сегодня: физика 16:00")
        out = self.events("message_out")[-1]
        sent = len(self.api.sent)
        self.tg_react(out.payload["tg_id"], "👍")
        self.assertEqual(self.core.state.reactions[out.id]["emoji"], "👍")
        self.assertEqual(len(self.api.sent), sent)  # на реакцию не отвечают
        self.assertEqual(self.brain.calls, [])
        self.assertEqual(self.core.state.days[self.core.today()].user_actions, 1)  # реакция — действие человека
        self.tg_react(out.payload["tg_id"], "")
        self.assertNotIn(out.id, self.core.state.reactions)

    def test_strangers_and_unknown_messages_are_ignored(self) -> None:
        self.bot.send("Привет")
        out = self.events("message_out")[-1]
        self.tg_react(out.payload["tg_id"], "👍", user=999)
        self.tg_react(4242, "👍")
        self.assertEqual(self.core.state.reactions, {})

    def test_confused_reaction_gets_a_simpler_explanation_quoting_the_message(self) -> None:
        self.bot.send("Дискриминант — это b² − 4ac; знак говорит, сколько корней.")
        out = self.events("message_out")[-1]
        self.brain.answers.append({"reply": "Проще: считаешь одно число — по нему видно, есть ли ответы.", "actions": []})
        self.tg_react(out.payload["tg_id"], "🤔")  # в Telegram знака вопроса среди реакций нет
        seen = self.brain.calls[-1]["system"]
        self.assertIn("<reaction>", seen)
        self.assertIn("b² − 4ac", seen)
        self.assertEqual(self.api.replies[-1], out.payload["tg_id"])  # объяснение — цитатой того, что непонятно
        self.assertEqual(self.events("message_out")[-1].payload["reply_to"], out.id)

    def test_reactions_reach_the_head(self) -> None:
        self.bot.send("Совет: учи формулы карточками")
        advice = self.events("message_out")[-1]
        self.tg_react(advice.payload["tg_id"], "👎")
        self.brain.answers.append({"reply": "Ок.", "actions": []})
        self.say("что дальше?", 2001)
        seen = self.brain.calls[-1]["system"]
        self.assertIn(f"[#{advice.id}] АРВИКС", seen)
        self.assertIn("[его реакция 👎]", seen)
        self.assertNotIn("Реакция 👎 на твоё", seen)  # уже видна в истории — второй раз не повторяется

    def test_app_reaction_set_is_checked(self) -> None:
        from arvix.core import ArvixError

        self.bot.send("Ответ")
        out = self.events("message_out")[-1]
        with self.assertRaises(ArvixError):
            web_api.react(out.id, "🍌")
        web_api.react(out.id, "❤️")(self.bot)
        self.assertEqual(web_api.messages_view(self.core)[-1]["reaction"], "❤️")
        with self.assertRaises(ArvixError):  # на своё сообщение реакция Arvix ничего не говорит
            self.core.react(self.core.message_in("моё", channel="web"), "👍")

    def test_question_mark_in_the_app_explains(self) -> None:
        self.bot.send("Тезис: интервальные повторения")
        out = self.events("message_out")[-1]
        self.brain.answers.append({"reply": "Повторяешь тогда, когда почти забыл.", "actions": []})
        web_api.react(out.id, "❓")(self.bot)
        self.assertEqual(len(self.brain.calls), 1)
        self.assertEqual(web_api.messages_view(self.core)[-1]["reply_to"]["id"], out.id)


class SeenTest(ReplyCase):
    def test_presence_is_runtime_not_journal(self) -> None:
        before = self.core.state.last_event_id
        web_api.seen(None)(self.bot)
        self.assertEqual(self.core.state.last_event_id, before)
        self.assertTrue(self.core.presence()["online"])
        self.at(self.core.now() + timedelta(minutes=5))
        self.assertFalse(self.core.presence()["online"])

    def test_read_is_logged_once_and_is_not_an_action(self) -> None:
        self.bot.send("Брифинг")
        out = self.events("message_out")[-1]
        web_api.seen(out.id)(self.bot)
        web_api.seen(out.id)(self.bot)  # повтор — без события
        reads = self.events("messages_read")
        self.assertEqual(len(reads), 1)
        self.assertEqual(reads[0].source, "seen")
        self.assertEqual(self.core.state.read_upto, out.id)
        self.assertEqual(self.core.state.days[self.core.today()].user_actions, 0)  # прочитать — не сделать

    def test_head_sees_online_and_unread(self) -> None:
        self.bot.send("Первое")
        first = self.events("message_out")[-1]
        web_api.seen(first.id)(self.bot)
        self.bot.send("Второе, его он ещё не видел")
        self.brain.answers.append({"reply": "Ок.", "actions": []})
        self.bot.send_curiosity()
        seen = self.brain.calls[-1]["system"]
        self.assertIn("Сейчас в приложении: да", seen)
        self.assertIn(f"Прочитал ленту в приложении до #{first.id}", seen)
        self.assertIn("Не видел в приложении твоих сообщений: 1", seen)

    def test_nothing_known_means_no_block(self) -> None:
        self.brain.answers.append({"reply": "Ок.", "actions": []})
        self.say("привет", 2100)
        self.assertNotIn("<messenger>", self.brain.calls[-1]["system"])

    def test_app_endpoints(self) -> None:
        from tests.test_laptop import STATIC

        js = (STATIC / "app.js").read_text()
        for emoji in ("👍", "👎", "❤️", "💔", "❓"):
            self.assertIn(emoji, js)
        from arvix.core import Core

        # набор приложения и сервера один: иначе кнопка в меню получала бы 400
        self.assertIn("const REACTIONS = [" + ", ".join(f'"{e}"' for e in Core.REACTIONS) + "]", js)
