"""Правила L0 из 02-MECHANICS — без базы и без ИИ."""

import unittest

from arvix import interview, rules

from tests.helpers import ROOT  # noqa: F401 — кладёт пакет в sys.path


class NoGameTest(unittest.TestCase):
    """D41: игры нет — ни очков, ни здоровья, ни уровней, ни сезонов в правилах L0."""

    def test_no_game_numbers_left(self) -> None:
        for name in ("task_xp", "level_info", "sleep_damage", "penalty_multiplier", "sp_for_day", "season_rank",
                     "HP_MAX", "HP_FAIL", "XP_BASE", "BONUS_FULL_DAY", "SEASON_WEEKS"):
            self.assertFalse(hasattr(rules, name), name)

    def test_proof_levels(self) -> None:
        self.assertEqual(rules.derive_proof(2, "work", False), "confirm")
        self.assertEqual(rules.derive_proof(3, "work", False), "report")
        self.assertEqual(rules.derive_proof(4, "work", False), "photo")
        self.assertEqual(rules.derive_proof(1, "sport", False), "photo")
        self.assertEqual(rules.derive_proof(5, "learning", True), "report")


class GuardTest(unittest.TestCase):
    def mode(self, **kw) -> str:
        base = {"sleep": [None, None, None], "completion": [None] * 7, "sos": False}
        base.update(kw)
        return rules.guard_mode(**base)[0]

    def test_no_data_is_normal(self) -> None:
        self.assertEqual(self.mode(), "normal")

    def test_red_triggers(self) -> None:
        self.assertEqual(self.mode(sos=True), "red")
        self.assertEqual(self.mode(sleep=[280, 290, 250]), "red")
        self.assertEqual(self.mode(completion=[10, 15, 5, 12, 18, 0, 10]), "red")

    def test_yellow_triggers(self) -> None:
        self.assertEqual(self.mode(sleep=[480, 340, 350]), "yellow")
        self.assertEqual(self.mode(completion=[None] * 4 + [30, 35, 25]), "yellow")

    def test_pressure_requires_known_good_sleep(self) -> None:
        low = [None] * 4 + [45, 40, 48]
        self.assertEqual(self.mode(completion=low, sleep=[460, 470, 450]), "pressure")
        self.assertEqual(self.mode(completion=low), "normal")  # сна не знаем — давить не на что

    def test_debt_freezes(self) -> None:
        common = {"mentor_enabled": True, "silent": False, "ignore_days": 0}
        self.assertFalse(rules.frozen(mode="normal", **common))
        self.assertTrue(rules.frozen(mode="red", **common))
        self.assertTrue(rules.frozen(mode="normal", **{**common, "ignore_days": 3}))
        self.assertTrue(rules.frozen(mode="normal", **{**common, "mentor_enabled": False}))
        self.assertTrue(rules.frozen(mode="normal", **common, reason=True))

    def test_bedtime(self) -> None:
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
