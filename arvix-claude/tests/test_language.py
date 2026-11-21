"""Язык через видео (D61): субтитры текстом, диктант и «Повтори» сверяет код по словам, добыча предложений с
пропуском в Obsidian, урок иностранного языка ищет ролики на нём, свой ролик — субтитры распознаванием."""

from __future__ import annotations

import json
import time
from typing import Any

from arvix import media, study, videos
from arvix.core import ArvixError
from arvix.state import State
from arvix.web import api as web_api

from tests.helpers import ArvixCase, moscow
from tests.test_study import StudyServerTest
from tests.test_study_stages import YT_HTML
from tests.test_telegram import BotCase

YOUTUBE_COPY = """0:00
Hi everyone, welcome back to the channel
0:04
today we are going to talk about habits that really matter
0:09
I was reluctant to start running every morning
0:14
but after two weeks it became much easier for me
0:19
so let me tell you what actually changed in my life
0:24
the first thing is that I stopped checking my phone in bed
0:29
and the second thing is I went to sleep much earlier
0:33
thanks for watching"""

SRT = """1
00:00:01,000 --> 00:00:03,500
<i>I was reluctant</i> to go.

2
00:00:04,000 --> 00:00:06,000
[Music]
But I went anyway.
"""

VTT = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:02.500
Gonna be fine

00:00:02.500 --> 00:00:05.000
<00:00:02.900><c>don't</c> worry about it
"""

DICT = [{"word": "reluctant", "phonetic": "/ɹɪˈlʌktənt/", "phonetics": [{"audio": ""}, {"audio": "https://api.dictionaryapi.dev/media/reluctant-us.mp3"}],
         "meanings": [{"partOfSpeech": "adjective", "definitions": [{"definition": "Not willing to do something.", "example": "He was reluctant to go."}]}]}]


class TranscriptTest(ArvixCase):
    def test_youtube_copy_srt_vtt_and_plain(self) -> None:
        yt = media.parse_transcript(YOUTUBE_COPY)
        self.assertEqual(len(yt), 8)
        self.assertEqual((yt[0]["t"], yt[0]["d"], yt[0]["text"]), (0, 4, "Hi everyone, welcome back to the channel"))
        self.assertEqual(yt[-1]["d"], 4.0)  # последняя строка — длительность по умолчанию
        inline = media.parse_transcript("0:01 Hello there\n0:03 General Kenobi")
        self.assertEqual([(x["t"], x["text"]) for x in inline], [(1, "Hello there"), (3, "General Kenobi")])
        srt = media.parse_transcript(SRT)
        self.assertEqual([(x["t"], x["d"], x["text"]) for x in srt], [(1.0, 2.5, "I was reluctant to go."), (4.0, 2.0, "But I went anyway.")])
        vtt = media.parse_transcript(VTT)
        self.assertEqual([x["text"] for x in vtt], ["Gonna be fine", "don't worry about it"])
        plain = media.parse_transcript("First line\nSecond line")
        self.assertEqual([x["t"] for x in plain], [None, None])
        self.assertEqual(media.from_segments([{"start": 1.2, "end": 3.0, "text": " Hello "}, {"start": "x"}]), [{"t": 1.2, "d": 1.8, "text": "Hello"}])

    def test_word_accuracy_for_dictation_and_shadowing(self) -> None:
        self.assertEqual(media.accuracy("i was reluctant to go", "I was reluctant to go.")["pct"], 100)
        self.assertEqual(media.accuracy("I don’t know", "I don't know")["pct"], 100)  # апостроф с телефона
        # сокращения — те же услышанные слова (стенд 22.11: «that's» против «that is» было ошибкой)
        self.assertEqual(media.accuracy("that's all for this program, I'm gonna go", "that is all for this programme, I am going to go")["pct"], 100)
        self.assertEqual(media.accuracy("I can't", "I cannot")["pct"], 100)
        wrong = media.accuracy("I want go", "I want to go")
        self.assertEqual(wrong["pct"], 75)
        self.assertEqual([d["s"] for d in wrong["diff"]], ["ok", "ok", "miss", "ok"])
        self.assertEqual(media.accuracy("I was reluctant to go there", "I was reluctant to go")["pct"], 83)  # лишнее — тоже ошибка
        self.assertTrue(media.dictation_ok("the first thing is that i stopped checking my phone in the bed", "the first thing is that I stopped checking my phone in bed"))
        self.assertFalse(media.dictation_ok("the first thing is i stop checking phone", "the first thing is that I stopped checking my phone in bed"))
        picks = media.pick_dictation(media.parse_transcript(YOUTUBE_COPY), 5)
        self.assertEqual(len(picks), 5)
        self.assertNotIn(7, picks)  # «thanks for watching» — короче 5 слов

    def test_language_detection_cloze_and_dictionary(self) -> None:
        self.assertEqual(media.language_of("Английский язык: 45 минут"), "en")
        self.assertEqual(media.language_of("Учить: IELTS listening"), "en")
        self.assertEqual(media.language_of("Немецкий: артикли"), "de")
        self.assertIsNone(media.language_of("Русский язык ОГЭ: сочинение"))  # родной язык — урок по задачам, без роликов
        self.assertEqual(media.cloze("I was Reluctant to go.", "reluctant"), "I was {{c1::Reluctant}} to go.")
        media.FETCH = lambda url: json.dumps(DICT).encode()
        entry = media.define("Reluctant!")
        self.assertEqual((entry["word"], entry["audio"]), ("reluctant", "https://api.dictionaryapi.dev/media/reluctant-us.mp3"))
        self.assertEqual(entry["meanings"][0]["def"], "Not willing to do something.")
        media.FETCH = lambda url: (_ for _ in ()).throw(OSError("нет сети"))
        self.assertIsNotNone(media.define("reluctant"))  # из кэша
        self.assertIsNone(media.define("zzqx"))  # сеть упала — None, без исключения


class LanguageSessionTest(ArvixCase):
    """Субтитры → диктант кодом → ошибки диктанта и переписать заново → «Повтори» → предложения в Obsidian."""

    def setUp(self) -> None:
        super().setUp()
        (self.vault / "07_Blind dictation English").mkdir()
        self.task = self.core.add_task("Английский язык: 45 минут", sphere="learning", start="16:00", duration_min=45)
        self.video = study.add_panel(self.core, {"type": "video", "stage": "learn", "url": "https://youtu.be/dQw4w9WgXcQ", "title": "Habits"},
                                     task_ref=self.task.id)

    def session(self) -> dict[str, Any]:
        return study.session_of(self.core, self.task.id)

    def test_transcript_dictation_fix_and_rebuild(self) -> None:
        self.assertEqual(self.video["lang"], "en")  # урок английского — субтитры в плеере на английском
        with self.assertRaises(ArvixError):
            study.add_transcript(self.core, self.video["id"], text="просто слово", task_ref=self.task.id)
        video = study.add_transcript(self.core, self.video["id"], text=YOUTUBE_COPY, task_ref=self.task.id)
        self.assertEqual(len(video["transcript"]), 8)
        dictation = next(p for p in study.visible(self.session()) if p["type"] == "quiz")
        self.assertEqual((dictation["stage"], len(dictation["questions"])), ("practice", 5))
        self.assertEqual(dictation["questions"][0]["listen"]["panel"], self.video["id"])
        hidden = json.dumps(study.public_panel(dictation, None), ensure_ascii=False)
        self.assertNotIn("reluctant", hidden)  # текст фразы — только после ответа
        study.add_transcript(self.core, self.video["id"], text=YOUTUBE_COPY, task_ref=self.task.id)
        self.assertEqual(sum(1 for p in study.visible(self.session()) if p["type"] == "quiz"), 1)  # второй диктант не ставится
        truth = [q["short"] for q in dictation["questions"]]
        self.assertEqual(truth[1], "I was reluctant to start running every morning")
        # одна опечатка на 8 слов (87 %) — засчитано; две (75 %) — ошибка: диктант — про «услышал», а не про буквы
        self.assertTrue(media.dictation_ok("I was relucant to start running every morning", truth[1]))
        answers = [truth[0], "I was relucant to start runing every morning", "?", truth[3], "so let me tell"]
        out = study.answer_quiz(self.core, dictation["id"], answers, task_ref=self.task.id)
        self.assertEqual(out["results"], [True, False, False, True, False])
        self.assertEqual(out["scores"][:3], [100, 75, None])
        shown = study.public_panel(dictation, self.session()["answers"][dictation["id"]])
        self.assertEqual([d["s"] for d in shown["questions"][1]["diff"]].count("wrong"), 2)
        errs = study.errors(self.session())
        self.assertEqual(len(errs), 3)
        key = errs[0]["key"]
        fixed = study.fix_error(self.core, key, task_ref=self.task.id, kind="hear", twin=truth[1])
        self.assertTrue(fixed["closed"] and fixed["twin_ok"])  # переслушал и записал верно — ошибка закрыта
        self.assertEqual(study.public_errors(self.session())[0]["twin"]["mode"], "dictation")
        self.assertIn("диктант: «", study.open_gaps(self.core, self.task.id)[0])
        rebuilt = State.rebuild(self.core.store.read()).study[self.task.id]
        self.assertEqual(rebuilt["answers"][dictation["id"]]["scores"], self.session()["answers"][dictation["id"]]["scores"])
        self.assertIn("субтитры текстом: 8 строк (английский)", study.context_block(self.core, self.task.id))

    def test_video_choice_is_journaled_and_locked_by_subtitles(self) -> None:
        """Стенд 22.11: выбор ролика из найденных жил только в браузере — после перезагрузки диктант играл бы первый ролик."""
        found = [{"url": "https://www.youtube.com/watch?v=AAAAAAAAAAA", "title": "First"}, {"url": "https://www.youtube.com/watch?v=BBBBBBBBBBB", "title": "6 Minute Grammar"}]
        panel = study.add_panel(self.core, {"type": "video", "stage": "learn", "query": "q", "results": found}, task_ref=self.task.id)
        self.assertEqual(panel["url"], found[0]["url"])
        picked = study.pick_video(self.core, panel["id"], 1, task_ref=self.task.id)
        self.assertEqual((picked["url"], picked["embed"]), (found[1]["url"], "https://www.youtube-nocookie.com/embed/BBBBBBBBBBB"))
        self.assertEqual(State.rebuild(self.core.store.read()).study[self.task.id]["panels"][-1]["url"], found[1]["url"])
        study.add_transcript(self.core, panel["id"], text=YOUTUBE_COPY, task_ref=self.task.id)
        with self.assertRaises(ArvixError):
            study.pick_video(self.core, panel["id"], 0, task_ref=self.task.id)
        self.assertEqual(study.mine(self.core, panel["id"], 2, "reluctant", task_ref=self.task.id)["title"], "6 Minute Grammar")

    def test_shadow_and_mining_into_vault(self) -> None:
        study.add_transcript(self.core, self.video["id"], text=YOUTUBE_COPY, task_ref=self.task.id)
        r = study.shadow(self.core, self.video["id"], 2, "I was reluctant to start running every morning", task_ref=self.task.id)
        self.assertEqual(r["pct"], 100)
        study.shadow(self.core, self.video["id"], 2, "I was to start running", task_ref=self.task.id)
        sh = self.session()["shadow"][f"{self.video['id']}:2"]
        self.assertEqual((sh["n"], sh["best"], sh["pct"]), (2, 100, 62))
        with self.assertRaises(ArvixError):
            study.shadow(self.core, self.video["id"], 99, "x", task_ref=self.task.id)
        m = study.mine(self.core, self.video["id"], 2, "reluctant", task_ref=self.task.id)
        self.assertEqual(m["cloze"], "I was {{c1::reluctant}} to start running every morning")
        self.assertEqual(m["note"], "07_Blind dictation English/Предложения из видео.md")  # папка английского — его
        study.mine(self.core, self.video["id"], 2, "reluctant", task_ref=self.task.id)  # второе нажатие — без дубля
        study.mine(self.core, self.video["id"], 3, "easier", task_ref=self.task.id)
        self.assertEqual(len(self.session()["mined"]), 2)
        note = (self.vault / m["note"]).read_text(encoding="utf-8")
        self.assertIn("I was {{c1::reluctant}} to start running every morning — *Habits 0:09* (https://youtu.be/dQw4w9WgXcQ?t=9)", note)
        self.assertIn("{{c1::easier}}", note)
        with self.assertRaises(ArvixError):
            study.mine(self.core, self.video["id"], 2, "banana", task_ref=self.task.id)
        self.assertIn("слово «reluctant»", " ".join(study.open_gaps(self.core, self.task.id)))
        self.assertIn("Добыл предложения: «reluctant»", study.context_block(self.core, self.task.id))


class FakeSegmentSTT:
    enabled = True
    max_seconds = 300

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def transcribe_segments(self, audio: bytes, filename: str = "", *, language: str = "") -> list[dict[str, Any]]:
        self.calls.append({"filename": filename, "language": language, "size": len(audio)})
        return [{"start": 0.0, "end": 3.2, "text": " I was reluctant to start running every morning "},
                {"start": 3.2, "end": 6.0, "text": "but after two weeks it became much easier for me"},
                {"start": 6.0, "end": 9.0, "text": "so let me tell you what actually changed"}]

    def transcribe(self, audio: bytes, filename: str = "", *, browser: bool = False, language: str = "") -> str:
        return "hello"


class LanguageLessonBotTest(BotCase):
    """Урок английского: голова получает метод языка, ролик ищется на английском, свой ролик — субтитры распознаванием."""

    start = moscow(2026, 11, 2, 15, 58)

    def setUp(self) -> None:
        super().setUp()
        self.core.cfg.raw["schedule"]["midday"] = ""
        self.urls: list[str] = []

        def fetch(url: str, accept: str) -> bytes:
            self.urls.append(url)
            if "youtube.com" in url:
                return YT_HTML
            raise OSError(url)
        videos.FETCH = fetch

    def test_language_rules_and_english_video(self) -> None:
        task = self.core.add_task("Английский язык: 45 минут", sphere="learning", start="16:00", duration_min=45)
        self.brain.answers.append({"topic": "Present Perfect in real speech", "why": "B1", "plan": [{"stage": "learn", "from_min": 0, "to_min": 45, "step": "ролик"}],
                                   "diagnostic": [{"q": "I ___ never been to London.", "options": ["have", "has"], "answer": 0}], "skills": [],
                                   "practice": [], "video_query": "present perfect English conversation intermediate", "sources": ["Murphy, Unit 7"],
                                   "check": [{"q": "Retell", "a": "суть"}]})
        self.bot.prepare_lesson(task)
        system = self.brain.calls[-1]["system"]
        self.assertIn("Это иностранный язык (английский)", system)
        self.assertIn("никакого «переведи на русский»", system)
        self.assertTrue(any("hl=en&gl=US" in u for u in self.urls))
        self.assertFalse(any("rutube" in u for u in self.urls))  # RuTube для английского не ищем
        video = next(p for p in self.core.state.study[task.id]["panels"] if p["type"] == "video")
        self.assertEqual((video["lang"], video["title"]), ("en", "Ролик на языке урока"))
        session = web_api.study_view(self.core, task.id)["session"]
        self.assertEqual(session["lang"], "en")
        self.assertIn("hear", session["lang_kinds"])

    def test_english_titles_first_for_english_lesson(self) -> None:
        """Живой сервер 22.11: первым роликом урока английского пришёл «РАЗГОВОР (использование Present Perfect)»."""
        import json as _json

        data = {"contents": [{"videoRenderer": {"videoId": f"vid{i}AAAAAAA", "title": {"runs": [{"text": t}]}, "lengthText": {"simpleText": "5:00"}}}
                             for i, t in enumerate(["РАЗГОВОР (Present Perfect)", "Present Perfect speaking practice"])]}
        html = ("<script>var ytInitialData = " + _json.dumps(data, ensure_ascii=False) + ";</script>").encode()
        videos.FETCH = lambda url, accept: html
        found = videos.search("present perfect", 2, lang="en")
        self.assertEqual([v["title"] for v in found], ["Present Perfect speaking practice", "РАЗГОВОР (Present Perfect)"])

    def test_russian_language_lesson_is_not_a_video_lesson(self) -> None:
        task = self.core.add_task("Русский язык: сочинение 13.3", sphere="learning", start="16:00", duration_min=45)
        self.bot.prepare_lesson(task)  # голова молчит — запасной план
        self.assertNotIn("Это иностранный язык", self.brain.calls[-1]["system"])
        self.assertIsNone(web_api.study_view(self.core, task.id)["session"]["lang"])

    def test_own_clip_gets_subtitles_and_dictation(self) -> None:
        task = self.core.add_task("Английский язык: 45 минут", sphere="learning", start="16:00", duration_min=45)
        self.bot.prepare_lesson(task)
        self.bot.stt = FakeSegmentSTT()
        web_api.study_upload(task.id, b"ID3fake-mp3-bytes", "friends s01e01 clip.mp3", "audio/mpeg", "")(self.bot)
        self.assertEqual(self.bot.stt.calls[0]["language"], "en")
        panels = self.core.state.study[task.id]["panels"]
        clip = next(p for p in panels if p["type"] == "video" and p.get("media"))
        self.assertTrue(clip["media"].endswith("friends s01e01 clip.mp3"))
        self.assertEqual(len(clip["transcript"]), 3)
        self.assertTrue((self.vault / clip["media"]).is_file())
        messages = web_api.study_view(self.core, task.id)["session"]["messages"]
        self.assertIn("субтитры — 3 строк", messages[-1]["text"])
        self.assertEqual(len(self.brain.calls), 1)  # свой ролик — без головы


class OpenGuardTest(BotCase):
    """Стенд 22.11: проверка урока 18:30 ждала ответа, «Учить сейчас» у темы английского ставил блок на завтра —
    и только потом отказывал «сейчас идёт урок». Отказ — до блока; прошлую сессию посмотреть можно всегда."""

    start = moscow(2026, 11, 2, 15, 58)

    def test_refuse_before_creating_a_block(self) -> None:
        from arvix import projects

        self.core.cfg.raw["schedule"]["midday"] = ""
        math_ = self.core.add_task("Математика: 45 минут", sphere="learning", start="16:00", duration_min=45)
        self.brain.answers.append({"topic": "x", "why": "y", "plan": [{"stage": "check", "from_min": 0, "to_min": 45, "step": "s"}],
                                   "diagnostic": [], "skills": [], "practice": [], "sources": [], "check": [{"q": "q", "a": "a"}]})
        self.bot.prepare_lesson(math_)
        self.bot.send_lesson_check()
        item = projects.set_learn(self.core, "Английский: Present Perfect", kind="practice", source="web")
        before = len(self.core.state.tasks)
        with self.assertRaises(ArvixError):
            web_api.study_open(item_id=item)(self.bot)
        self.assertEqual(len(self.core.state.tasks), before)  # блока в плане нет
        done = self.core.add_task("Физика: ток", sphere="learning", start="10:00", duration_min=30)
        self.core.complete_task(done.id, report="решил 5 задач", source="web")
        self.assertEqual(web_api.study_open(done.id)(self.bot), {"task_id": done.id, "queued": False})


class LanguageServerTest(StudyServerTest):
    """HTTP: субтитры, слово, «Повтори», видео в сессию, словарь."""

    def test_open_from_queue_answer_and_add_video(self) -> None:  # родительский сценарий здесь не повторяем
        pass

    def test_media_routes(self) -> None:
        import arvix.stt

        (self.vault / "English").mkdir()
        videos.FETCH = lambda url, accept: YT_HTML if "youtube.com" in url else (_ for _ in ()).throw(OSError(url))
        media.FETCH = lambda url: json.dumps(DICT).encode()
        task = self.core.add_task("Английский язык: 45 минут", sphere="learning", start="16:00", duration_min=45)
        self.brain.answers.append(None)
        status, opened = self.call("/api/study/open", {"task": task.id})
        for _ in range(200):
            if self.core.store.kv_get("lesson"):
                break
            time.sleep(0.02)
        status, r = self.call(f"/api/study/{task.id}/video", {"query": "habits English", "lang": "en", "stage": "learn"})
        self.assertEqual(status, 200, r)
        video = r["panel"]
        self.assertEqual((video["lang"], video["results"][0]["site"]), ("en", "youtube"))
        status, r = self.call(f"/api/study/{task.id}/transcript", {"panel": video["id"], "text": YOUTUBE_COPY})
        self.assertEqual((status, len(r["panel"]["transcript"])), (200, 8), r)
        self.assertTrue(any(p["title"].startswith("Диктант") for p in r["session"]["panels"]))
        status, r = self.call(f"/api/study/{task.id}/mine", {"panel": video["id"], "i": 2, "word": "reluctant"})
        self.assertEqual((status, r["mined"]["note"]), (200, "English/Предложения из видео.md"), r)
        status, r = self.call("/api/define?word=reluctant")
        self.assertEqual(r["entry"]["phonetic"], "/ɹɪˈlʌktənt/")
        saved = arvix.stt.STT

        class Heard:
            enabled = True

            def __init__(self, cfg: Any) -> None:
                pass

            def transcribe(self, audio: bytes, filename: str = "", *, browser: bool = False, language: str = "") -> str:
                assert language == "en"
                return "I was reluctant to start running every morning"
        arvix.stt.STT = Heard
        try:
            request = __import__("urllib.request", fromlist=["x"]).Request(
                f"http://127.0.0.1:{self.port}/api/study/{task.id}/shadow", data=b"OggS-audio", method="POST",
                headers={"Authorization": f"Bearer {self.app.token}", "Content-Type": "audio/ogg", "X-Panel": video["id"], "X-Line": "2", "X-Lang": "en"})
            with __import__("urllib.request", fromlist=["x"]).urlopen(request, timeout=10) as resp:
                shadow = json.loads(resp.read())["shadow"]
        finally:
            arvix.stt.STT = saved
        self.assertEqual(shadow["pct"], 100)
        status, r = self.call(f"/api/study/{task.id}/transcript", {"panel": video["id"], "text": "нет времени"})
        self.assertEqual(status, 400)
