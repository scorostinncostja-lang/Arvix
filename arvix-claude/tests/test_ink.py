"""Конспекты от руки (D66): почерк остаётся картинкой, расшифровка — свёрнутым блоком той же заметки."""

from base64 import b64encode
from datetime import timedelta

from arvix import ink
from arvix.core import ArvixError, NoteConflict
from arvix.state import State
from arvix.web import api

from tests.test_telegram import BotCase

PNG = b"\x89PNG\r\n\x1a\n" + b"page"


def stroke(*xy, color="#1b1f3b"):
    pts = []
    for x, y in zip(xy[::2], xy[1::2]):
        pts += [x, y, 500]
    return {"t": "pen", "c": color, "w": 2.2, "p": pts}


def png(tag=b""):
    return b64encode(PNG + tag).decode()


class InkTest(BotCase):
    def new(self, name="Квадратные уравнения"):
        return api.ink_create("03_Resources/Обучение", name)(self.bot)

    def save(self, note, pages, images, transcribe=False):
        body = {"path": note["path"], "rev": note["rev"], "pages": pages, "png": images, "transcribe": transcribe}
        return api.ink_save(body)(self.bot)

    def test_new_note_is_a_person_note_with_page_folder(self):
        note = self.new()
        self.assertEqual(note["path"], "03_Resources/Обучение/Квадратные уравнения.md")
        self.assertTrue(note["dir"].startswith("00_Inbox/Файлы/Рукописи/Квадратные уравнения "))
        self.assertEqual(note["pages"], [{"bg": "grid", "strokes": []}])
        text = (self.vault / note["path"]).read_text(encoding="utf-8")
        self.assertIn(f'ink: "{note["dir"]}"', text)
        self.assertIn("%% arvix:ink-pages %%", text)
        view = api.note_view(self.core, note["path"])
        self.assertEqual(view["ink"]["dir"], note["dir"])
        self.assertIsNone(api.note_view(self.core, self.plain_note())["ink"])
        with self.assertRaisesRegex(ArvixError, "уже есть"):
            self.new()

    def plain_note(self):
        (self.vault / "Просто.md").write_text("# Просто\n", encoding="utf-8")
        return "Просто.md"

    def test_saving_keeps_handwriting_as_images_and_strokes(self):
        note = self.new()
        saved = self.save(note, [{"bg": "lines", "strokes": [stroke(10, 10, 200, 40)]}], {"0": png()})
        folder = self.vault / note["dir"]
        self.assertEqual((folder / "стр-01.png").read_bytes(), PNG)
        self.assertEqual(saved["pages"][0]["bg"], "lines")
        self.assertEqual(saved["pages"][0]["strokes"][0]["p"], [10, 10, 500, 200, 40, 500])
        text = (self.vault / note["path"]).read_text(encoding="utf-8")
        self.assertIn(f"![[{note['dir']}/стр-01.png]]", text)
        self.assertEqual(saved["status"]["stale"], [0])
        self.assertEqual(self.brain.calls, [], "без просьбы расшифровать голову не зовём")
        # после перезапуска свёртка помнит страницы
        replay = State.rebuild(self.core.store.read(0))
        self.assertEqual(replay.ink[note["path"]]["pages"], 1)

    def test_other_device_wrote_first_is_a_conflict_not_a_loss(self):
        note = self.new()
        self.save(note, [{"bg": "grid", "strokes": [stroke(1, 1, 2, 2)]}], {"0": png()})
        with self.assertRaises(NoteConflict) as caught:
            self.save(note, [{"bg": "grid", "strokes": [stroke(5, 5, 6, 6)]}], {"0": png(b"2")})
        self.assertIn('"p":[1,1,500,2,2,500]', caught.exception.current)
        self.assertEqual((self.vault / note["dir"] / "стр-01.png").read_bytes(), PNG)

    def test_bad_input_is_refused(self):
        note = self.new()
        for pages, images, message in (
            ([{"bg": "grid", "strokes": [stroke(1, 1)]}], {}, "Нет картинки страницы 1"),
            ([{"bg": "grid", "strokes": []}], {"0": b64encode(b"GIF89a").decode()}, "не PNG"),
            ([{"bg": "neon", "strokes": []}], {"0": png()}, "повреждена"),
            ([{"bg": "grid", "strokes": [{"t": "pen", "c": "red", "w": 2, "p": [1, 2, 3]}]}], {"0": png()}, "Штрих"),
            ([{"bg": "grid", "strokes": []}], {"3": png()}, "несуществующей"),
        ):
            with self.assertRaisesRegex(ArvixError, message):
                self.save(note, pages, images)
        self.save(note, [{"bg": "grid", "strokes": []}, {"bg": "grid", "strokes": []}], {"0": png(), "1": png()})
        with self.assertRaisesRegex(ArvixError, "не удаляются"):
            self.save(ink.view(self.core, note["path"]), [{"bg": "grid", "strokes": []}], {})

    def test_transcription_goes_to_a_folded_block_and_only_for_changed_pages(self):
        note = self.new()
        pages = [{"bg": "grid", "strokes": [stroke(1, 1, 9, 9)]}, {"bg": "grid", "strokes": [stroke(3, 3, 4, 4)]},
                 {"bg": "grid", "strokes": []}]
        note = self.save(note, pages, {"0": png(b"a"), "1": png(b"b"), "2": png(b"c")})
        self.brain.answers.append({"pages": [{"page": 1, "text": "$ax^2+bx+c=0$"}, {"page": 2, "text": "D = b² − 4ac"}],
                                   "summary": "Квадратные уравнения и дискриминант"})
        result = ink.transcribe(self.core, self.brain, note["path"])
        call = self.brain.calls[-1]
        self.assertTrue(call["vault_tools"])
        self.assertFalse(call["web"])
        self.assertIn("стр-01.png", call["prompt"])
        self.assertNotIn("стр-03.png", call["prompt"], "пустую страницу не разбираем")
        self.assertEqual(result["stale"], [])
        text = (self.vault / note["path"]).read_text(encoding="utf-8")
        self.assertIn("> [!abstract]- Расшифровка Arvix", text)
        self.assertIn("> $ax^2+bx+c=0$", text)
        self.assertIn("![[", text.split("%% arvix:ink-text %%")[0], "почерк — до расшифровки, его видно первым")
        # человек дописал свой текст в заметку — Arvix его не трогает
        (self.vault / note["path"]).write_text(text + "\nМоя приписка\n", encoding="utf-8")
        # дописал только вторую страницу — голова видит только её
        note = ink.view(self.core, note["path"])
        pages[1]["strokes"].append(stroke(7, 7, 8, 8))
        self.save(note, pages, {"1": png(b"b2")})
        self.brain.answers.append({"pages": [{"page": 2, "text": "D = b² − 4ac, если D < 0 — корней нет"}], "summary": ""})
        ink.transcribe(self.core, self.brain, note["path"])
        self.assertNotIn("стр-01.png", self.brain.calls[-1]["prompt"])
        text = (self.vault / note["path"]).read_text(encoding="utf-8")
        self.assertIn("корней нет", text)
        self.assertIn("$ax^2+bx+c=0$", text)
        self.assertIn("Моя приписка", text)
        self.assertIn("*Квадратные уравнения и дискриминант*", text)
        self.assertEqual(len(self.brain.calls), 2)
        self.assertIsNone(ink.prepare(self.core, note["path"]), "всё расшифровано — второй раз не зовём")

    def test_head_down_is_an_honest_status_and_retry_works(self):
        note = self.new()
        note = self.save(note, [{"bg": "grid", "strokes": [stroke(1, 1, 9, 9)]}], {"0": png()})
        self.brain.last_error = "лимит подписки"
        status = ink.transcribe(self.core, self.brain, note["path"])
        self.assertEqual(status["error"], "лимит подписки")
        self.assertEqual(status["stale"], [0])
        self.assertFalse(status["pending"])
        self.brain.answers.append({"pages": [{"page": 1, "text": "x = 2"}], "summary": "корень"})
        status = ink.transcribe(self.core, self.brain, note["path"])
        self.assertEqual((status["error"], status["stale"]), ("", []))

    def test_interrupted_transcription_does_not_spin_forever(self):
        note = self.new()
        note = self.save(note, [{"bg": "grid", "strokes": [stroke(1, 1, 9, 9)]}], {"0": png()})
        ink.prepare(self.core, note["path"])  # служба упала посреди разбора: ответа не будет
        self.assertTrue(ink.status(self.core, note["path"])["pending"])
        self.at(self.core.now() + timedelta(minutes=11))
        self.assertFalse(ink.status(self.core, note["path"])["pending"])

    def test_page_rewritten_during_transcription_stays_stale(self):
        note = self.new()
        note = self.save(note, [{"bg": "grid", "strokes": [stroke(1, 1, 9, 9)]}], {"0": png(b"old")})
        job = ink.prepare(self.core, note["path"])
        self.save(note, [{"bg": "grid", "strokes": [stroke(1, 1, 9, 9), stroke(2, 2, 3, 3)]}], {"0": png(b"new")})
        ink.apply(self.core, job, {"pages": [{"page": 1, "text": "старое"}], "summary": ""})
        self.assertEqual(ink.status(self.core, note["path"])["stale"], [0])


class InkShellTest(BotCase):
    def test_app_has_the_canvas_and_new_cache(self):
        from pathlib import Path

        static = Path(api.__file__).resolve().parent / "static"
        js = (static / "app.js").read_text(encoding="utf-8")
        for needle in ("function openInk(", "pointerType === \"pen\"", "getCoalescedEvents", "ink/transcribe", "disableVerticalSwipes"):
            self.assertTrue(needle in js, needle)
        self.assertNotIn('"arvix-v19"', (static / "sw.js").read_text(encoding="utf-8"))
