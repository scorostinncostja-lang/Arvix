"""Формулы L0 из 02-MECHANICS — без базы и без ИИ."""

import unittest

from arvix import interview, rules

from tests.helpers import ROOT  # noqa: F401 — кладёт пакет в sys.path


class XpTest(unittest.TestCase):
    def test_formula_matches_spec(self) -> None:
        # 10 × K_diff(3)=1.0 × K_imp(4)=1.3 × K_proof(report)=1.1 × K_time=1.0 = 14.3
        self.assertEqual(rules.task_xp(3, 4, "report"), 14)
        self.assertEqual(rules.task_xp(5, 5, "photo", delay_min=-20), int(10 * 2.0 * 1.6 * 1.3 * 1.15))
        self.assertEqual(rules.task_xp(3, 3, "confirm", delay_min=40), 8)

    def test_partial_scales_xp(self) -> None:
        self.assertEqual(rules.task_xp(3, 3, "confirm", done_pct=50), 5)

    def test_proof_levels(self) -> None:
        self.assertEqual(rules.derive_proof(2, "work", False), "confirm")
        self.assertEqual(rules.derive_proof(3, "work", False), "report")
        self.assertEqual(rules.derive_proof(4, "work", False), "photo")
        self.assertEqual(rules.derive_proof(1, "sport", False), "photo")
        self.assertEqual(rules.derive_proof(5, "learning", True), "report")

    def test_levels_never_lost(self) -> None:
        self.assertEqual(rules.level_info(0), (1, 0, 100))
        self.assertEqual(rules.level_info(100), (2, 0, 120))
        self.assertEqual(rules.level_info(250), (3, 30, 140))


class GuardTest(unittest.TestCase):
    def mode(self, **kw) -> str:
        base = {"sleep": [None, None, None], "completion": [None] * 7, "hp": 100, "sos": False}
        base.update(kw)
        return rules.guard_mode(**base)[0]

    def test_no_data_is_normal(self) -> None:
        self.assertEqual(self.mode(), "normal")

    def test_red_triggers(self) -> None:
        self.assertEqual(self.mode(sos=True), "red")
        self.assertEqual(self.mode(hp=20), "red")
        self.assertEqual(self.mode(sleep=[280, 290, 250]), "red")
        self.assertEqual(self.mode(completion=[10, 15, 5, 12, 18, 0, 10]), "red")

    def test_yellow_triggers(self) -> None:
        self.assertEqual(self.mode(sleep=[480, 340, 350]), "yellow")
        self.assertEqual(self.mode(completion=[None] * 4 + [30, 35, 25]), "yellow")

    def test_pressure_requires_known_good_sleep(self) -> None:
        low = [None] * 4 + [45, 40, 48]
        self.assertEqual(self.mode(completion=low, sleep=[460, 470, 450]), "pressure")
        self.assertEqual(self.mode(completion=low), "normal")  # сна не знаем — давить не на что

    def test_penalties_freeze(self) -> None:
        common = {"mentor_enabled": True, "hp": 80, "silent": False, "ignore_days": 0, "protocol_zero": False}
        self.assertEqual(rules.penalty_multiplier(mode="normal", **common), 1.0)
        self.assertEqual(rules.penalty_multiplier(mode="red", **common), 0.0)
        self.assertEqual(rules.penalty_multiplier(mode="normal", **{**common, "ignore_days": 3}), 0.0)
        self.assertEqual(rules.penalty_multiplier(mode="normal", **{**common, "hp": 30}), 0.5)
        self.assertEqual(rules.penalty_multiplier(mode="normal", **{**common, "mentor_enabled": False}), 0.0)

    def test_sleep_and_bedtime(self) -> None:
        self.assertEqual(rules.sleep_damage(290), -12)
        self.assertEqual(rules.sleep_damage(350), -6)
        self.assertEqual(rules.sleep_damage(420), 0)
        self.assertEqual(rules.minutes_after("23:30", "01:30"), 120)
        self.assertEqual(rules.minutes_after("23:30", "23:00"), -30)


class InterviewExtractTest(unittest.TestCase):
    def test_deterministic_fields(self) -> None:
        self.assertEqual(interview.extract("name", "Дастан")["name"], "Дастан")
        self.assertEqual(interview.extract("address", "ты сделала")["address"], "f")
        self.assertEqual(interview.extract("address", "сделал")["address"], "m")
        self.assertEqual(interview.extract("city", "Алматы")["timezone"], "Asia/Almaty")
        self.assertEqual(interview.extract("city", "Бишкек, Asia/Bishkek")["timezone"], "Asia/Bishkek")
        sleep = interview.extract("sleep", "сейчас 01:30–09:00, хочу 23:30-07:30")
        self.assertEqual((sleep["bedtime_target"], sleep["wake_target"]), ("23:30", "07:30"))

    def test_bank_order_puts_fears_last(self) -> None:
        self.assertEqual(interview.QUESTIONS[0]["block"], "core")
        self.assertEqual(interview.QUESTIONS[-1]["block"], "inner")
        self.assertEqual(len({q["id"] for q in interview.QUESTIONS}), len(interview.QUESTIONS))


if __name__ == "__main__":
    unittest.main()
