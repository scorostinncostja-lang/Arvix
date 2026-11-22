"""D62: Arvix — навигатор по инструментам человека, а не их замена.

Нет вкладок «Проекты» и «Обучение»; есть список инструментов в Obsidian и «Как сделать» у задачи:
шаги «действие → инструмент → минуты», «готово, когда», куда записать — в чате, в приложении, в заметке дня.
"""

from arvix import brain, context, guide, tools
from arvix.prompt import system_prompt
from arvix.state import State
from arvix.telegram import templates as tpl
from arvix.web import api

from tests.helpers import moscow
from tests.test_telegram import BotCase

STEPS = {"steps": [{"do": "по памяти: Пифагор, sin, cos", "tool": "Бумага", "min": 5},
                   {"do": "каталог → №15: 6 задач", "tool": "Решу ОГЭ", "min": 30},
                   {"do": "ошибки — строкой", "tool": "Obsidian", "min": 10}],
         "done": "5 из 6 верно", "save": "03_Resources/ОГЭ/Журнал ошибок ОГЭ.md"}


class ToolsTest(BotCase):
    def test_note_is_created_once_and_person_edits_win(self) -> None:
        rel = tools.ensure(self.core)
        self.assertEqual(rel, "05_System/Инструменты.md")
        self.assertIn("| Решу ОГЭ |", (self.vault / rel).read_text())
        (self.vault / rel).write_text("| Инструмент | Для чего | Как |\n|---|---|---|\n| **Stepik** | курсы Python | по уроку в день |\n"
                                      "- Тетрадь — черновик\n- [ ] не инструмент — задача\n")
        tools.ensure(self.core)  # правленая заметка не перезаписывается
        names = [r["name"] for r in tools.load(self.core)]
        self.assertEqual(names, ["Stepik", "Тетрадь"])
        self.assertIn("Stepik — курсы Python", context.build_context(self.core))

    def test_bot_puts_the_list_into_vault_on_its_own(self) -> None:
        """«🧰 Мои инструменты» в приложении открывает заметку — она должна существовать без просьбы."""
        self.bot.refresh_panel()
        self.assertTrue((self.vault / "05_System/Инструменты.md").is_file())

    def test_without_note_starter_list_goes_to_context(self) -> None:
        line = context.build_context(self.core)
        self.assertIn("ИНСТРУМЕНТЫ", line)
        self.assertIn("Anki", line)
        self.assertNotIn("УРОКИ", line)

    def test_projects_live_in_vault_folder(self) -> None:
        self.assertNotIn("ПРОЕКТЫ:", context.build_context(self.core))
        (self.vault / "01_Projects").mkdir()
        self.assertIn("ПРОЕКТЫ: папки и заметки в 01_Projects", context.build_context(self.core))

    def test_red_mode_gets_no_tools_and_no_navigator(self) -> None:
        self.core.sos(True, source="telegram")
        self.assertNotIn("ИНСТРУМЕНТЫ", context.build_context(self.core))  # в 🟥 — одна маленькая вещь, не шаги (правило №5)
        self.assertNotIn("<navigator>", system_prompt(self.core, message="как учить?"))
        self.core.sos(False, source="telegram")
        self.assertIn("<navigator>", system_prompt(self.core, message="как учить?"))


class GuideTest(BotCase):
    start = moscow(2026, 11, 2, 17, 0)

    def task(self, **kw):
        return self.core.add_task("Математика ОГЭ: №15", start="18:00", duration_min=45, sphere="learning",
                                  importance=4, deep_work=True, source="telegram", **kw)

    def test_clean_cuts_empty_steps_and_fits_minutes_into_block(self) -> None:
        g = guide.clean({"steps": [{"do": " ", "tool": "x", "min": 5}, {"do": "a", "tool": "A", "min": 60},
                                   {"do": "b", "tool": "B", "min": 30}], "done": "ок"}, 45)
        self.assertEqual([s["do"] for s in g["steps"]], ["a", "b"])
        self.assertLessEqual(sum(s["min"] for s in g["steps"]), 45)
        with self.assertRaises(ValueError):
            guide.clean({"steps": [], "done": "x"}, 45)

    def test_guide_is_an_event_in_context_check_and_daily_note(self) -> None:
        t = self.task()
        self.core.set_guide(t.id, STEPS, source="l1")
        task = self.core.state.tasks[t.id]
        self.assertEqual(task.guide["steps"][1]["tool"], "Решу ОГЭ")
        rebuilt = State.rebuild(self.core.store.read(0))
        self.assertEqual(rebuilt.tasks[t.id].guide, task.guide)
        self.assertIn("ШАГИ К ЗАДАЧАМ", context.build_context(self.core))
        self.assertIn("Готово, когда: 5 из 6 верно", tpl.reminder_check(task))  # «Сделано?» сверяет с результатом
        note = (self.vault / self.core.vault.daily_path(self.core.today())).read_text()
        self.assertIn("## Как · Arvix", note)
        self.assertIn("каталог → №15: 6 задач", note)
        self.assertIn("%% arvix:как %%", note)

    def test_block_start_brings_steps_from_head_with_his_tools(self) -> None:
        t = self.task()
        self.brain.answers.append(STEPS)
        self.at(moscow(2026, 11, 2, 18, 0))
        self.scheduler.reminders(self.core.now())
        call = self.brain.calls[-1]
        self.assertEqual(call["schema"], guide.SCHEMA)
        self.assertIn("<guide>", call["system"])
        self.assertIn("Решу ОГЭ", call["system"])  # инструменты человека — в промпте шагов
        sent = next(x for x in self.api.texts if "Блок пошёл" in x)
        self.assertIn("каталог → №15: 6 задач", sent)
        self.assertIn("Готово, когда:", sent)
        self.assertIsNotNone(self.core.state.tasks[t.id].guide)

    def test_head_down_means_plain_block_start(self) -> None:
        self.task()
        self.at(moscow(2026, 11, 2, 18, 0))
        self.scheduler.reminders(self.core.now())
        self.assertTrue(any(x.startswith("▶️ Блок пошёл") for x in self.api.texts))

    def test_app_asks_steps_for_a_task(self) -> None:
        t = self.task()
        self.brain.answers.append({**STEPS, "note": "Треугольники — выбор теоремы"})
        out = api.task_guide(t.id)(self.bot)
        self.assertEqual(out["task"]["guide"]["done"], "5 из 6 верно")
        self.assertTrue(out["task"]["guide"]["note_path"].endswith("Треугольники — выбор теоремы.md"))
        self.assertTrue((self.vault / out["task"]["guide"]["note_path"]).is_file())  # каркас заметки своими словами

    def test_chat_attaches_steps_and_writes_notes_by_vault_rules(self) -> None:
        t = self.task()
        (self.vault / "01_Projects").mkdir()
        (self.vault / "01_Projects/GYM Bro.md").write_text("# GYM Bro\nмой текст\n")
        done, failed, _ = brain.apply_actions(self.core, [
            {"type": "task_guide", "task": t.id, **STEPS},
            {"type": "write_note", "path": "01_Projects/GYM Bro.md", "text": "## Следующий шаг"},  # без append — отказ
            {"type": "write_note", "path": "01_Projects/GYM Bro.md", "text": "## Следующий шаг", "append": True},
            {"type": "write_note", "path": "03_Resources/План №15.md", "text": "# План"},
        ], source="telegram")
        self.assertTrue(any("шаги к" in d for d in done))
        self.assertEqual(len(failed), 1)
        self.assertIn("мой текст", (self.vault / "01_Projects/GYM Bro.md").read_text())
        self.assertIn("## Следующий шаг", (self.vault / "01_Projects/GYM Bro.md").read_text())
        self.assertTrue((self.vault / "03_Resources/План №15.md").is_file())


class SectionsGoneTest(BotCase):
    def test_no_project_or_study_actions_and_routes(self) -> None:
        for kind in ("set_project", "plan_project", "learn_add", "study_panel", "start_lesson"):
            self.assertNotIn(kind, brain.ACTION_TYPES)
        self.assertIn("task_guide", brain.ACTION_TYPES)
        self.assertNotIn("lesson", api.state_view(self.core))

    def test_old_project_and_study_events_do_not_break_the_fold(self) -> None:
        with self.core.tx():
            self.core.emit("project_set", {"id": "p1", "title": "GYM Bro", "status": "active"}, source="telegram")
            self.core.emit("study_panel", {"task_id": "x", "panel": {"id": "w", "type": "quiz"}}, source="telegram")
            self.core.emit("lesson_started", {"task_id": "x", "topic": "Ток"}, source="telegram")
            self.core.emit("message_out", {"text": "в нити проекта", "project": "p1"}, source="bot")
        state = State.rebuild(self.core.store.read(0))
        self.assertFalse(hasattr(state, "projects"))
        self.assertNotIn("в нити проекта", [m["text"] for m in api.messages_view(self.core)])
