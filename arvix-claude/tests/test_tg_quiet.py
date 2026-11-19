"""Telegram — разговор и напоминания, без пультов (D50): таймер фокуса, панель дня и меню
под полем ввода живут в приложении. Владелец 19.11: «этим я не пользуюсь, в приложении удобнее»."""

from __future__ import annotations

from datetime import timedelta

from arvix.telegram import templates as tpl
from arvix.telegram.api import reply_markup
from tests.helpers import moscow
from tests.test_telegram import BotCase


def has_button(sent: list, prefix: str) -> bool:
    return any(b and any(data.startswith(prefix) for row in b for _, data in row) for _, b in sent)


class QuietTelegramTest(BotCase):
    def test_focus_timer_has_no_control_message(self) -> None:
        self.bot.start_focus(30, topic="Проект Arvix")
        self.assertFalse(has_button(self.api.sent, "f:"))
        self.assertIsNone(self.core.store.kv_get("focus").get("message_id"))

    def test_focus_from_the_app_says_nothing_in_telegram(self) -> None:
        from arvix.web import api

        api.focus_start(25, None, "физика")(self.bot)
        self.assertEqual(self.api.sent, [])

    def test_focus_end_is_logged_silently(self) -> None:
        self.bot.start_focus(30, topic="физика")
        sent = len(self.api.sent)
        self.at(self.core.now() + timedelta(minutes=31))
        self.scheduler.tick()
        self.assertIsNone(self.core.store.kv_get("focus"))
        self.assertEqual(self.core.state.days[self.core.today()].deep_min, 30)
        self.assertFalse(any("Без прерываний" in t or "Что успел" in t for t, _ in self.api.sent[sent:]))

    def test_long_pause_closes_focus_silently(self) -> None:
        self.bot.start_focus(30, topic="физика")
        self.at(self.core.now() + timedelta(minutes=10))
        self.bot.pause_focus()
        sent = len(self.api.sent)
        self.at(self.core.now() + timedelta(minutes=tpl.FOCUS_MAX_PAUSE_MIN + 1))
        self.scheduler.tick()
        self.assertIsNone(self.core.store.kv_get("focus"))
        self.assertFalse(any("окус" in t or "Пауза" in t or "Что успел" in t for t, _ in self.api.sent[sent:]))
        self.assertEqual(self.core.state.days[self.core.today()].user_times, [])  # закрыл код — не действие человека

    def test_brief_sends_no_day_panel(self) -> None:
        self.core.add_task("Алгоритмы", start="18:00", duration_min=60)
        self.bot.send_brief()
        self.assertFalse(has_button(self.api.sent, "t:") or has_button(self.api.sent, "p:"))
        self.assertEqual(self.api.pinned, [])

    def test_old_pinned_panel_is_unpinned(self) -> None:
        self.core.store.kv_set("tg_panel", {"message_id": 77, "date": self.core.today().isoformat(), "hash": "x"})
        self.bot.refresh_panel()
        self.assertEqual(self.api.unpinned, [77])
        self.assertIsNone(self.core.store.kv_get("tg_panel"))

    def test_menu_keyboard_is_gone(self) -> None:
        self.assertEqual(tpl.keyboard(""), [])
        self.assertEqual(tpl.keyboard("https://arvix.example"), [[tpl.MENU_APP]])
        self.assertEqual(reply_markup([]), {"remove_keyboard": True})

    def test_red_mode_still_offers_the_way_back(self) -> None:
        self.core.sos(True)
        self.bot.send_brief()
        self.assertTrue(has_button(self.api.sent, "r:back"))
        self.assertEqual(self.api.pinned, [])


class QuietSchedulerTest(BotCase):
    start = moscow(2026, 11, 2, 7, 0)

    def test_task_reminders_stay(self) -> None:
        self.core.add_task("Алгоритмы", importance=4, start="09:00", duration_min=60)
        self.at(moscow(2026, 11, 2, 8, 56))
        self.scheduler.tick()
        self.assertTrue(any("Через" in t for t, _ in self.api.sent))
