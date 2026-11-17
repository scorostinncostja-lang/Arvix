"""Заметки как в Obsidian: переменные шаблона, галочки задач, правка из приложения без затирания."""

from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import quote

from arvix import daily_note
from arvix.vault import format_moment, parse_frontmatter, render_template, sha

from tests import test_v04
from tests.helpers import ArvixCase

# Шаблон владельца как есть (05_System/Templates/Daily Report.md): синтаксис ядра Obsidian с форматом.
OWNER_TEMPLATE = """---
date: {{date:YYYY-MM-DD}}
type: daily
energy:
focus_minutes:
---
# Отчёт {{date:DD.MM.YYYY}}

## План (максимум 3 задачи)
- [ ]\u0020

## Сделано + доказательство
-\u0020
"""


def use_template(case: ArvixCase, text: str) -> None:
    (case.vault / ".obsidian" / "daily-notes.json").write_text(
        json.dumps({"folder": "08_Daily Report", "format": "YYYY-MM-DD", "template": "05_System/Templates/Daily Report"}), encoding="utf-8")
    (case.vault / "05_System" / "Templates").mkdir(parents=True, exist_ok=True)
    (case.vault / "05_System" / "Templates" / "Daily Report.md").write_text(text, encoding="utf-8")


class TemplateTest(ArvixCase):
    def test_moment_formats_in_russian(self) -> None:
        dt = datetime(2026, 11, 17, 9, 5)
        self.assertEqual(format_moment("DD.MM.YYYY", dt), "17.11.2026")
        self.assertEqual(format_moment("D MMMM YYYY, dddd", dt), "17 ноября 2026, вторник")
        self.assertEqual(format_moment("MMMM YYYY", dt), "ноябрь 2026")
        self.assertEqual(format_moment("[Неделя] ww · HH:mm", dt), "Неделя 47 · 09:05")

    def test_core_and_templater_variables(self) -> None:
        dt = datetime(2026, 11, 17, 21, 30)
        text = render_template('{{date}} {{ time }} {{title}} <% tp.date.now("DD.MM") %> <% tp.date.now("D MMMM", 1) %> <% tp.file.title %>',
                               dt, "2026-11-17")
        self.assertEqual(text, "2026-11-17 21:30 2026-11-17 17.11 18 ноября 2026-11-17")

    def test_owner_template_is_rendered_not_left_raw(self) -> None:
        """Скриншот владельца 17.11: в отчёте дня осталось `date: {{date:YYYY-MM-DD}}` и «Отчёт {{date:DD.MM.YYYY}}»."""
        use_template(self, OWNER_TEMPLATE)
        self.core.add_task("Физика", start="18:00", duration_min=60)
        rel = daily_note.ensure(self.core, self.core.today())
        text = (self.vault / rel).read_text(encoding="utf-8")
        self.assertNotIn("{{", text)
        self.assertEqual(parse_frontmatter(text)["date"], "2026-11-02")
        self.assertIn("# Отчёт 02.11.2026", text)
        self.assertIn("- [ ] 18:00 Физика (60 мин)", text)

    def test_sync_repairs_note_created_raw_earlier(self) -> None:
        use_template(self, OWNER_TEMPLATE)
        rel = "08_Daily Report/2026-11-02.md"
        (self.vault / "08_Daily Report").mkdir()
        (self.vault / rel).write_text(OWNER_TEMPLATE.replace("-\u0020\n", "- сам написал\n"), encoding="utf-8")
        daily_note.sync(self.core, self.core.today())
        text = (self.vault / rel).read_text(encoding="utf-8")
        self.assertNotIn("{{", text)
        self.assertIn("# Отчёт 02.11.2026", text)
        self.assertIn("- сам написал", text)

    def test_done_task_gets_its_box_ticked_and_only_its_box(self) -> None:
        use_template(self, OWNER_TEMPLATE)
        a = self.core.add_task("Физика", start="18:00", duration_min=60)
        self.core.add_task("Алгебра", start="19:30", duration_min=45)
        rel = daily_note.ensure(self.core, self.core.today())
        path = self.vault / rel
        path.write_text(path.read_text(encoding="utf-8") + "- [ ] 18:00 Физика (60 мин) — моя копия строки? нет, своя задача\n- [ ] купить тетрадь\n",
                        encoding="utf-8")
        self.core.complete_task(a.id, report="6 задач")
        daily_note.repair(self.core, self.core.today(), rel)
        text = path.read_text(encoding="utf-8")
        self.assertIn("- [x] 18:00 Физика (60 мин)\n", text)
        self.assertIn("- [ ] 19:30 Алгебра (45 мин)", text)
        self.assertIn("- [ ] купить тетрадь", text)


class NotesServerTest(test_v04.ServerTest):
    def setUp(self) -> None:
        super().setUp()
        (self.vault / "Учёба").mkdir()
        self.note = self.vault / "Учёба" / "Физика.md"
        self.note.write_text("# Физика\n\n- [ ] §12 конспект\n- [x] §11\n", encoding="utf-8")

    def open_note(self, path: str = "Учёба/Физика.md") -> dict:
        status, note = self.call("/api/note?path=" + quote(path))
        self.assertEqual(status, 200, note)
        return note

    def test_edit_saves_and_is_journaled(self) -> None:
        note = self.open_note()
        status, saved = self.call("/api/note", {"path": note["path"], "text": note["text"] + "Новая строка\n", "sha": note["sha"]})
        self.assertEqual(status, 200, saved)
        self.assertIn("Новая строка", self.note.read_text(encoding="utf-8"))
        self.assertEqual(saved["sha"], sha(self.note.read_text(encoding="utf-8")))
        event = [e for e in self.core.store.read(0) if e.kind == "note_written"][-1]
        self.assertEqual((event.payload["mode"], event.payload["owned"], event.source), ("edit", False, "web"))

    def test_edit_over_changed_file_is_a_conflict_not_a_loss(self) -> None:
        note = self.open_note()
        self.note.write_text("# Физика\n\nправка с ноутбука\n", encoding="utf-8")  # синхронизация пришла, пока правил телефон
        status, body = self.call("/api/note", {"path": note["path"], "text": "моя версия", "sha": note["sha"]})
        self.assertEqual(status, 409)
        self.assertTrue(body["conflict"])
        self.assertIn("правка с ноутбука", body["text"])
        self.assertIn("правка с ноутбука", self.note.read_text(encoding="utf-8"))
        status, _ = self.call("/api/note", {"path": note["path"], "text": "моя версия", "sha": body["sha"]})  # «оставить мою»
        self.assertEqual(status, 200)
        self.assertEqual(self.note.read_text(encoding="utf-8"), "моя версия")

    def test_new_note_in_folder(self) -> None:
        status, note = self.call("/api/note/new", {"dir": "Учёба", "name": "Закон Ома"})
        self.assertEqual(status, 200, note)
        self.assertEqual(note["path"], "Учёба/Закон Ома.md")
        self.assertEqual((self.vault / "Учёба" / "Закон Ома.md").read_text(encoding="utf-8"), "# Закон Ома\n\n")
        status, body = self.call("/api/note/new", {"dir": "Учёба", "name": "Закон Ома"})
        self.assertEqual(status, 400)
        self.assertIn("уже есть", body["error"])

    def test_checkbox_toggles_in_file(self) -> None:
        note = self.open_note()
        status, after = self.call("/api/note/toggle", {"path": note["path"], "line": 2, "sha": note["sha"]})
        self.assertEqual(status, 200, after)
        self.assertIn("- [x] §12 конспект", self.note.read_text(encoding="utf-8"))
        status, after = self.call("/api/note/toggle", {"path": note["path"], "line": 3, "sha": after["sha"]})
        self.assertIn("- [ ] §11", self.note.read_text(encoding="utf-8"))
        status, body = self.call("/api/note/toggle", {"path": note["path"], "line": 0, "sha": after["sha"]})
        self.assertEqual(status, 400)

    def test_task_line_in_daily_note_closes_the_task_not_the_text(self) -> None:
        use_template(self, OWNER_TEMPLATE)
        task = self.core.add_task("Физика", start="18:00", duration_min=60)
        rel = daily_note.ensure(self.core, self.core.today())
        note = self.open_note(rel)
        line = next(int(i) for i, t in note["tasks"].items() if t["id"] == task.id)
        status, body = self.call("/api/note/toggle", {"path": rel, "line": line, "sha": note["sha"]})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["task"]["id"], task.id)
        self.assertIn("- [ ] 18:00 Физика", (self.vault / rel).read_text(encoding="utf-8"))  # текст ждёт закрытия задачи
        self.call(f"/api/tasks/{task.id}/done", {"report": "6 задач"})
        self.assertIn("- [x] 18:00 Физика (60 мин)", (self.vault / rel).read_text(encoding="utf-8"))
        note = self.open_note(rel)
        status, body = self.call("/api/note/toggle", {"path": rel, "line": line, "sha": note["sha"]})
        self.assertEqual(status, 400)
        self.assertIn("уже закрыта", body["error"])

    def test_attachments_are_served_sandboxed_and_inside_vault_only(self) -> None:
        import urllib.request

        (self.vault / "08_Daily Report" / "attachments").mkdir(parents=True)
        (self.vault / "08_Daily Report" / "attachments" / "доска.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/file?path=" + urllib.request.quote("доска.png"),
                                         headers={"Authorization": f"Bearer {self.app.token}"})
        with urllib.request.urlopen(request, timeout=10) as response:
            self.assertEqual(response.headers["Content-Type"], "image/png")
            self.assertEqual(response.headers["Content-Security-Policy"], "sandbox")
            self.assertTrue(response.read().startswith(b"\x89PNG"))
        status, body = self.call("/api/file?path=../../etc/passwd")
        self.assertEqual(status, 400)
        status, body = self.call("/api/note?path=../secret.md")
        self.assertEqual(status, 400)


class DailyTickTest(test_v04.BotCase):
    def test_scheduler_tick_repairs_raw_note_without_closed_tasks(self) -> None:
        """Отчёт 17.11 остался сырым до вечера: чинить надо при первом тике дня, а не после разбора."""
        use_template(self, OWNER_TEMPLATE)
        rel = "08_Daily Report/2026-11-02.md"
        (self.vault / "08_Daily Report").mkdir()
        (self.vault / rel).write_text(OWNER_TEMPLATE, encoding="utf-8")
        self.bot.refresh_panel()
        text = (self.vault / rel).read_text(encoding="utf-8")
        self.assertNotIn("{{", text)
        self.assertIn("date: 2026-11-02", text)
        mtime = (self.vault / rel).stat().st_mtime_ns
        self.bot.refresh_panel()  # второй тик ничего не читает и не пишет
        self.assertEqual((self.vault / rel).stat().st_mtime_ns, mtime)


class DaySummaryTest(ArvixCase):
    def test_owner_day_17_11_reads_like_a_summary_not_a_transcript(self) -> None:
        """17.11: задач 0, сон 10ч, разбор. В заметке была копия ответа и «Сделано 0/0 · глубокая 0м»."""
        use_template(self, OWNER_TEMPLATE)
        self.core.log_sleep("10:00", bedtime="23:00")
        rel = daily_note.ensure(self.core, self.core.today())
        self.core.complete_debrief("Всё отлично. Хорошо отдохнул, понял, что тяжело с самим собой",
                                   conclusion="Отдых засчитан. Завтра — распорядок и первая задача до обеда.")
        daily_note.sync(self.core, self.core.today())
        text = (self.vault / rel).read_text(encoding="utf-8")
        self.assertIn("Плана не было: распорядок ещё не сохранён", text)
        self.assertIn("**Вывод.** Отдых засчитан.", text)
        self.assertNotIn("Хорошо отдохнул", text)
        self.assertNotIn("Сделано 0/0", text)
        self.assertNotIn("<!--", text)
        self.assertEqual(parse_frontmatter(text)["focus_minutes"], "0")  # после разбора — и ноль

    def test_old_html_block_is_replaced_by_obsidian_comment_block(self) -> None:
        use_template(self, OWNER_TEMPLATE)
        rel = daily_note.ensure(self.core, self.core.today())
        path = self.vault / rel
        path.write_text(path.read_text(encoding="utf-8") + "\n<!-- arvix:день -->\n## Арвикс\nстарое\n<!-- /arvix:день -->\nмоя строка\n",
                        encoding="utf-8")
        daily_note.sync(self.core, self.core.today())
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("<!-- arvix", text)
        self.assertNotIn("старое", text)
        self.assertEqual(text.count("%% arvix:день %%"), 1)
        self.assertIn("моя строка", text)
