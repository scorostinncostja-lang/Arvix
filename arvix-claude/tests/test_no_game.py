"""D41: игры нет. Ни XP, ни HP, ни уровней, ни сезонов, ни серии — ни в одном лице Арвикса.

Владелец 18.11: «убрать геймификацию полностью (HP, EXP, статус и т. п.), которые могут ошибаться».
Старые игровые события остаются в журнале (он только дополняется), но никуда не выводятся."""

import io
import re
from contextlib import redirect_stdout

from arvix import hooks, statusline
from arvix.context import build_context
from arvix.prompt import voice_prompt
from arvix.telegram import templates as tpl
from arvix.web import api as web_api

from tests.test_telegram import BotCase

GAME = re.compile(r"\bXP\b|\bHP\b|[Уу]ровень|ур\.\s?\d|[Сс]езон|[Сс]ери[яи]\s+\d|стрик|щит|Протокол Ноль|\bSP\b")


class NoGameTest(BotCase):
    def setUp(self) -> None:
        super().setUp()
        # Журнал прошлой версии: очки, урон, щит, Протокол Ноль — всё это там есть и останется.
        for kind, payload in (("xp_awarded", {"amount": 40, "reason": "full_day"}), ("hp_changed", {"amount": -90, "reason": "old"}),
                              ("shield_used", {"date": "2026-11-01"}), ("protocol_zero", {"on": True, "until": "2026-11-09T00:00:00+03:00"})):
            self.core.emit(kind, payload, source="test")
        self.task = self.core.add_task("Физика", importance=3, start="16:00", duration_min=45)

    def assert_clean(self, text: str, where: str) -> None:
        self.assertIsNone(GAME.search(text), f"{where}: {text}")

    def test_every_face_shows_facts_only(self) -> None:
        self.assert_clean(tpl.status(self.core), "📊 Итоги")
        self.assert_clean(tpl.day_panel(self.core), "панель дня")
        self.assert_clean(tpl.brief(self.core), "брифинг")
        self.assert_clean(statusline.render(self.core), "строка состояния Claude Code")
        self.assert_clean(hooks.prompt_line(self.core), "хук Claude Code")
        self.assert_clean(build_context(self.core), "контекст модели")
        self.assert_clean(repr(web_api.state_view(self.core)), "приложение")
        self.assertIn("Сегодня: 0 из 1", tpl.status(self.core))

    def test_old_game_events_do_not_change_anything(self) -> None:
        """HP −90 из старого журнала не включает 🟥 и не появляется нигде."""
        self.assertEqual(self.core.recompute_mode(), "normal")
        self.assertFalse(hasattr(self.core.state, "hp"))
        self.assertFalse(hasattr(self.core.state, "xp_total"))

    def test_buttons_report_facts(self) -> None:
        self.press(f"t:{self.task.id}:yes")
        self.text("решил 6 задач")
        self.assert_clean(self.api.last, "отчёт кнопкой")
        other = self.core.add_task("Экзамен", importance=5, start="18:00")
        self.press(f"t:{other.id}:no")
        self.assert_clean("\n".join(self.api.texts[-2:]), "провал кнопкой")
        self.assertIn("ушла в долг", "\n".join(self.api.texts[-2:]))

    def test_old_status_button_still_answers_with_facts(self) -> None:
        self.text(tpl.MENU_STATUS_OLD)  # клавиатура до 0.6 на телефоне
        self.assertTrue(self.api.last.startswith("Режим: 🟩 НОРМА"), self.api.last)
        self.assert_clean(self.api.last, "старая кнопка статуса")
        self.text(tpl.MENU_STATUS)
        self.assertIn("Неделя:", self.api.last)

    def test_model_is_told_there_is_no_game(self) -> None:
        system, _ = voice_prompt(self.core, message="сколько у меня XP?")
        self.assertIn("Очков, здоровья, уровней и серий у Арвикса нет", " ".join(system.split()))

    def test_cli_status_is_facts(self) -> None:
        from arvix import cli

        out = io.StringIO()
        cli._core = lambda: self.core  # type: ignore[assignment]
        with redirect_stdout(out):
            cli.cmd_status(None)  # type: ignore[arg-type]
        self.assert_clean(out.getvalue(), "arvix status")
        self.assertIn("Сегодня", out.getvalue())
