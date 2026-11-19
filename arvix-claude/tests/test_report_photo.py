"""Отчёт по задаче с фото (D49): фото лежит в хранилище, путь — в событии, а отчёт и фото
видит голова — в контексте дня и в памяти по дням. Раньше фото из Telegram терялось
(записывалась только подпись), а текст отчёта в контекст не попадал вовсе."""

from __future__ import annotations

from arvix import memory
from arvix.context import build_context
from arvix.web import api
from tests.test_telegram import OWNER, BotCase

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 200 + b"\xff\xd9"


class ReportPhotoTest(BotCase):
    def test_report_text_reaches_the_head(self) -> None:
        task = self.core.add_task("Физика: задачи 1–5", start="18:00", duration_min=45)
        self.core.complete_task(task.id, report="решил 5 из 5, ошибка в единицах в №3", source="web")
        context = build_context(self.core)
        self.assertIn("решил 5 из 5, ошибка в единицах в №3", context)

    def test_photo_from_the_app_is_stored_and_visible(self) -> None:
        task = self.core.add_task("Математика", start="18:00", duration_min=45)
        uploaded = api.task_photo(task.id, JPEG, "IMG_1.jpg", "image/jpeg")(self.bot)
        rel = uploaded["path"]
        self.assertTrue((self.vault / rel).is_file())
        self.assertIn("Отчёты", rel)
        api.task_op(task.id, "done", {"report": "вариант 12", "photos": [rel]})(self.bot)
        done = self.core.state.tasks[task.id]
        self.assertEqual(done.status, "done")
        self.assertEqual(done.report_photos, [rel])
        context = build_context(self.core)
        self.assertIn("вариант 12", context)
        self.assertIn(str(self.vault / rel), context)  # абсолютный путь — голова открывает его Read
        self.assertEqual(self.brain.calls, [])  # отметка задачи — код, не модель

    def test_photo_only_report_is_enough(self) -> None:
        task = self.core.add_task("Конспект", start="18:00", duration_min=30, importance=4)
        rel = api.task_photo(task.id, JPEG, "c.jpg", "image/jpeg")(self.bot)["path"]
        api.task_op(task.id, "done", {"photos": [rel]})(self.bot)
        self.assertEqual(self.core.state.tasks[task.id].status, "done")

    def test_photo_outside_the_vault_is_refused(self) -> None:
        task = self.core.add_task("Химия", start="18:00", duration_min=30)
        with self.assertRaises(Exception):
            api.task_op(task.id, "done", {"report": "x", "photos": ["../../etc/passwd"]})(self.bot)

    def test_telegram_photo_report_keeps_the_photo(self) -> None:
        task = self.core.add_task("Конспект", start="18:00", duration_min=30, importance=4)
        self.press(f"t:{task.id}:yes")
        self.bot.handle({"update_id": 9, "message": {"from": {"id": OWNER}, "chat": {"id": OWNER}, "caption": "параграф 12",
                                                      "photo": [{"file_id": "small", "file_size": 10}, {"file_id": "big", "file_size": 900}]}})
        done = self.core.state.tasks[task.id]
        self.assertEqual(done.status, "done")
        self.assertEqual(len(done.report_photos), 1)
        self.assertEqual((self.vault / done.report_photos[0]).read_bytes(), b"OGG:big")  # FakeAPI.download — самое крупное фото
        self.assertIn("параграф 12", build_context(self.core))

    def test_report_goes_to_memory_by_day(self) -> None:
        task = self.core.add_task("Английский", start="18:00", duration_min=30)
        self.core.complete_task(task.id, report="20 слов, 3 ошибки", source="web")
        folder = memory.export_transcripts(self.core, self.tmp / "mem")
        text = (folder / f"{self.core.today().isoformat()}.md").read_text(encoding="utf-8")
        self.assertIn("Английский", text)
        self.assertIn("20 слов, 3 ошибки", text)
