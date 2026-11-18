"""D38–D40: из 🟥 есть выход, Арвикс действует вместе с человеком, голова отвечает быстрее.

Каждый тест здесь падал на коде до 18.11: 🟥 кормил сам себя, «8:30 утра» не было подъёмом,
вернуться к плану было нечем, а весь промпт менялся от сообщения к сообщению."""

import unittest
from datetime import timedelta

from arvix import rules
from arvix.brain import Brain, apply_actions, effort_for
from arvix.core import ArvixError, parse_sleep_text
from arvix.prompt import read_block, voice_prompt
from arvix.telegram import templates as tpl

from tests.helpers import ArvixCase
from tests.test_telegram import BotCase


class GuardExitTest(unittest.TestCase):
    """rules.guard_mode: у 🟥 есть выход по данным и по решению человека."""

    def test_todays_good_sleep_lifts_sleep_red(self) -> None:
        self.assertEqual(rules.guard_mode(sleep=[280, 290, 250], completion=[], sos=False)[0], "red")
        self.assertNotEqual(rules.guard_mode(sleep=[280, 290, 480], completion=[], sos=False)[0], "red")

    def test_recovery_caps_data_red_at_yellow_but_not_sos(self) -> None:
        week = [5.0] * 7
        self.assertEqual(rules.guard_mode(sleep=[], completion=week, sos=False, recovery=True)[0], "yellow")
        self.assertEqual(rules.guard_mode(sleep=[480], completion=[], sos=True, recovery=True)[0], "red")

    def test_first_day_after_red_is_yellow_not_pressure(self) -> None:
        mode, trigger = rules.guard_mode(sleep=[480, 480, 480], completion=[45.0, 45.0, 45.0], sos=False, after_red=True)
        self.assertEqual((mode, trigger), ("yellow", "первый день после 🟥: без разгона"))
        self.assertEqual(rules.guard_mode(sleep=[480, 480, 480], completion=[45.0, 45.0, 45.0], sos=False)[0], "pressure")


class RedTrapTest(ArvixCase):
    def live_day(self, offset: int) -> None:
        """День с задачей, о которой никто не отчитался (бот молчал), и закрытие в 05:00."""
        day = self.start + timedelta(days=offset)
        self.at(day)
        self.core.refresh()
        self.core.add_task(f"Дело {offset}", importance=2, start="18:00")
        self.at(day + timedelta(hours=19))
        self.core.refresh()

    def test_red_does_not_feed_itself(self) -> None:
        """Пять дней по 0 % → 🟥. Дни в 🟥 без плана не считаются провалом: через три дня 🟥 кончается,
        первый день после — 🟨. Раньше они шли в выполнение как 0 % и держали 🟥 вечно."""
        for offset in range(5):
            self.live_day(offset)
        self.assertEqual(self.core.state.mode, "red")
        for offset in range(5, 8):
            self.live_day(offset)
        self.assertEqual(self.core.state.mode, "yellow")
        self.assertEqual(self.core.state.mode_trigger, "первый день после 🟥: без разгона")

    def sleep_red(self) -> None:
        """Три ночи меньше пяти часов: позавчера, вчера и сегодня."""
        for offset in (2, 1):
            self.core.log_sleep("4:30", day=(self.start - timedelta(days=offset)).date().isoformat())
        self.core.log_sleep("4:30")
        self.assertEqual(self.core.state.mode, "red")

    def test_good_sleep_lifts_red_the_same_morning(self) -> None:
        self.sleep_red()
        result = self.core.log_sleep(bedtime="00:30", wake="08:30")
        self.assertEqual(result["duration_min"], 480)
        self.assertEqual((result["mode_before"], result["mode"]), ("red", "normal"))
        self.assertEqual(tpl.sleep_logged(result), "Сон 8ч00м (00:30–08:30). Режим: 🟥 → 🟩 НОРМА")

    def test_old_hp_events_do_not_drive_the_mode(self) -> None:
        """D41: HP ≤ 20 больше не включает 🟥 — старые события журнала в режим не входят."""
        self.core.emit("hp_changed", {"amount": -95, "reason": "из старой версии"}, source="test")
        self.assertEqual(self.core.recompute_mode(), "normal")

    def test_resume_plan_is_the_persons_button(self) -> None:
        self.core.sos(True)
        self.assertEqual(self.core.state.mode, "red")
        self.assertEqual(self.core.resume_plan(source="telegram"), "yellow")
        self.assertFalse(self.core.sos_active())
        self.at(self.start + timedelta(days=1, hours=-5))  # 05:00 завтра: возвращение кончилось, день после 🟥 — 🟨
        self.core.refresh()
        self.assertFalse(self.core.recovery_active())

    def test_resume_never_turns_mentor_back_on(self) -> None:
        self.core.safety_flag("high", "тест")
        with self.assertRaises(ArvixError):
            self.core.resume_plan()
        self.assertFalse(self.core.state.mentor_enabled)

    def test_gentle_context_names_the_exit_without_numbers(self) -> None:
        from arvix.context import build_context

        for offset in range(5):  # неделя почти без выполнения → 🟥 по выполнению
            self.core.emit("day_closed", {"date": (self.start.date() - timedelta(days=offset + 1)).isoformat(), "completion": 5.0,
                                          "total": 4, "done": 0, "mode": "normal"}, source="test")
        self.assertEqual(self.core.recompute_mode(), "red")
        context = build_context(self.core)
        self.assertNotIn("<20%", context)  # раньше: «Режим: 🟥 КРАСНЫЙ (выполнение <20% неделю)» — цифры в мягком промпте
        self.assertIn("ВЫХОД ИЗ 🟥", context)
        self.assertIn("СОН СЕГОДНЯ: не записан", context)


class SleepWordsTest(unittest.TestCase):
    def test_morning_time_is_wake_not_duration(self) -> None:
        self.assertEqual(parse_sleep_text("8:30 утра"), {"duration": None, "bedtime": None, "wake": "08:30"})

    def test_bed_and_wake_give_duration_over_midnight(self) -> None:
        self.assertEqual(parse_sleep_text("лёг в час, встал в 8:30")["duration"], 450)
        self.assertEqual(parse_sleep_text("с 23:30 до 7:00")["duration"], 450)
        self.assertEqual(parse_sleep_text("лёг в 11, проснулся в 7")["bedtime"], "23:00")

    def test_old_formats_still_work(self) -> None:
        self.assertEqual(parse_sleep_text("7:20 00:30"), {"duration": 440, "bedtime": "00:30", "wake": None})
        self.assertEqual(parse_sleep_text("спал 6 часов, лёг в час")["duration"], 360)

    def test_not_about_sleep_is_refused(self) -> None:
        with self.assertRaises(ArvixError):
            parse_sleep_text("5 задач сегодня?")

    def test_expected_half_is_a_bare_clock(self) -> None:
        self.assertEqual(parse_sleep_text("в час", expect="bedtime")["bedtime"], "01:00")


class BotRecoveryTest(BotCase):
    def test_wake_time_answer_asks_bedtime_then_logs(self) -> None:
        """Брифинг ждёт сон, человек пишет «8:30 утра» — это подъём. Раньше записывалось 8ч30м сна."""
        self.bot.await_set("sleep")
        self.text("8:30 утра")
        self.assertIn("Во сколько уснул?", self.api.last)
        self.assertIsNone(self.core.state.days.get(self.core.today()) and self.core.state.days[self.core.today()].sleep_min)
        self.text("в час")
        self.assertEqual(self.core.state.days[self.core.today()].sleep_min, 450)
        self.assertTrue(any("Сон 7ч30м (01:00–08:30)" in t for t in self.api.texts))
        self.assertEqual(self.brain.calls, [])  # без модели

    def test_red_brief_asks_sleep_and_offers_the_way_back(self) -> None:
        self.core.sos(True)
        self.bot.send_brief()
        self.assertTrue(any("во сколько лёг и встал" in t for t in self.api.texts))
        self.assertTrue(any(b and ("▶️ Вернуться к плану", "r:back") in b[0] for _, b in self.api.sent))

    def test_return_button_brings_the_plan_back_softly(self) -> None:
        self.core.add_task("Растяжка", start="18:00", duration_min=10, importance=2)
        self.core.sos(True)
        self.press("r:back")
        self.assertEqual(self.core.state.mode, "yellow")
        self.assertTrue(any("Возвращаемся" in t for t in self.api.texts))
        self.assertIn("Растяжка", self.api.texts[-1])  # панель уже с задачами, а не «без плана»

    def test_head_offers_return_but_does_not_switch_mode(self) -> None:
        self.core.sos(True)
        self.brain.answers.append({"reply": "Вижу, ты выспался.", "actions": [{"type": "offer_return"}]})
        self.text("Режим восстановился, пора двигаться дальше")
        self.assertEqual(self.core.state.mode, "red")  # модель режим не меняет
        self.assertEqual(self.api.sent[-1][1], tpl.red_buttons(refresh=False))

    def test_advice_becomes_a_task_in_the_plan(self) -> None:
        """«Что советуешь» → задача в плане, а не «скажи, что берёшь»."""
        self.brain.answers.append({
            "reply": "Начинаем сейчас: 25 минут математики.",
            "actions": [{"type": "add_task", "title": "Математика: задание 21", "start": "10:05", "duration_min": 25, "sphere": "learning"}],
        })
        self.text("Ну так напиши, что нужно и что ты реально советуешь")
        titles = [t.title for t in self.core.state.tasks_on(self.core.today())]
        self.assertIn("Математика: задание 21", titles)
        self.assertEqual(self.brain.calls[-1]["effort"], "medium")

    def test_system_prompt_is_static_and_the_rest_goes_to_the_request(self) -> None:
        """Кэш провайдера: системный промпт тот же байт в байт, живое — в запросе (D40)."""
        self.brain.answers += [{"reply": "Да.", "actions": []}, {"reply": "Ок.", "actions": []}]
        self.text("привет")
        self.core.add_task("Физика", start="18:00")
        self.text("ок")
        first, second = self.brain.calls
        self.assertEqual(first["raw_system"], second["raw_system"])
        self.assertNotIn("<context>", second["raw_system"])
        self.assertIn("Физика", second["raw_prompt"])
        self.assertTrue(second["raw_prompt"].endswith("<message>\nок\n</message>"))
        self.assertEqual(second["effort"], "low")


class PartnerPromptTest(ArvixCase):
    def test_partner_rules_in_every_mode(self) -> None:
        self.assertIn("<partner>", voice_prompt(self.core)[0])
        self.core.sos(True)
        system, request = voice_prompt(self.core, message="всё плохо")
        self.assertIn("<partner>", system)
        self.assertIn(read_block("tone_red"), system)
        self.assertNotIn("<decision_rule>", system + request)


class SpeedTest(ArvixCase):
    def test_effort_follows_the_message(self) -> None:
        self.assertEqual(effort_for("ок"), "low")
        self.assertEqual(effort_for("почему так, а не иначе?"), "medium")

    def test_effort_flag_only_when_cli_knows_it(self) -> None:
        brain = Brain(self.core.cfg)
        brain._flags = "--effort <level>"
        cmd = brain.command(system="s", prompt="p", schema={}, role="voice", vault_tools=False, effort="low")
        self.assertEqual(cmd[cmd.index("--effort") + 1], "low")
        brain._flags = ""
        self.assertNotIn("--effort", brain.command(system="s", prompt="p", schema={}, role="voice", vault_tools=False, effort="low"))

    def test_log_sleep_action_takes_bed_and_wake(self) -> None:
        self.core.sos(True)
        self.core.resume_plan()  # 🟨 до смены дня
        done, failed, _ = apply_actions(self.core, [{"type": "log_sleep", "bedtime": "01:00", "wake": "08:30"}])
        self.assertEqual(failed, [])
        self.assertEqual(done, ["сон 7ч30м"])  # режим не сменился — и квитанция об этом молчит


if __name__ == "__main__":
    unittest.main()
