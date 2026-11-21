"""Файлы Arvix: хранилище, безопасная распаковка, документы, видео, Telegram и приложение."""

from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
import unittest
import zipfile
from pathlib import Path
from typing import Any
from unittest import mock

from arvix import files
from arvix.core import ArvixError

from tests import test_v04
from tests.test_telegram import OWNER, BotCase, FakeSTT

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def make_zip(entries: dict[str, bytes], symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (0o120777 << 16)
            zf.writestr(info, "/etc/passwd")
    return buf.getvalue()


def make_docx(paragraphs: list[str]) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = f'<?xml version="1.0"?><w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>'
    return make_zip({"word/document.xml": xml.encode()})


class StoreTest(BotCase):
    def test_classify(self) -> None:
        self.assertEqual(files.classify("доска.JPG"), "image")
        self.assertEqual(files.classify("пробник.pdf"), "pdf")
        self.assertEqual(files.classify("repo.tar.gz"), "archive")
        self.assertEqual(files.classify("main.py"), "text")
        self.assertEqual(files.classify("урок.mp4"), "video")
        self.assertEqual(files.classify("лекция.m4a"), "audio")
        self.assertEqual(files.classify("эссе.docx"), "docx")
        self.assertEqual(files.classify("photo.heic", "image/heic"), "other")

    def test_image_lands_in_vault_and_journal(self) -> None:
        info = self.core.receive_file(PNG, "../../доска.png", "image/png", caption="проверь решение")
        self.assertTrue(info["path"].startswith("00_Inbox/Файлы/2026-11-02/"), info["path"])
        self.assertTrue(info["path"].endswith("доска.png"))
        self.assertEqual((self.vault / info["path"]).read_bytes(), PNG)
        self.assertEqual(info["read"], [info["path"]])
        event = [e for e in self.core.store.read(0) if e.kind == "file_received"][-1]
        self.assertEqual((event.payload["kind"], event.payload["caption"]), ("image", "проверь решение"))

    def test_too_big_or_empty_is_refused_in_words(self) -> None:
        with self.assertRaises(ArvixError):
            self.core.receive_file(b"", "x.png")
        with mock.patch.object(files, "MAX_BYTES", 10), self.assertRaises(ArvixError) as ctx:
            self.core.receive_file(PNG, "x.png")
        self.assertIn("МБ", str(ctx.exception))

    def test_archive_unpacks_only_inside_its_folder(self) -> None:
        data = make_zip({"repo/main.py": b"print(1)\n", "repo/.git/config": b"x", "../evil.txt": b"x", "/abs.txt": b"x",
                         "repo/node_modules/a.js": b"x"}, symlink="repo/link")
        info = self.core.receive_file(data, "repo.zip")
        root = self.vault / info["unpacked"]
        written = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
        self.assertEqual(written, ["abs.txt", "repo/main.py"])
        self.assertFalse((self.vault / "00_Inbox" / "Файлы" / "evil.txt").exists())
        self.assertFalse(any(p.is_symlink() for p in root.rglob("*")))

    def test_tar_with_absolute_and_parent_paths(self) -> None:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for name in ("ok/a.txt", "../../escape.txt", "/etc/cron.d/x"):
                data = b"hi"
                ti = tarfile.TarInfo(name)
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
            link = tarfile.TarInfo("ok/link")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            tf.addfile(link)
        info = self.core.receive_file(buf.getvalue(), "repo.tar.gz")
        root = self.vault / info["unpacked"]
        self.assertEqual(sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()), ["etc/cron.d/x", "ok/a.txt"])
        self.assertFalse(Path(self.vault.parent / "escape.txt").exists())

    def test_archive_limits(self) -> None:
        with mock.patch.object(files, "MAX_ARCHIVE_FILES", 2), self.assertRaises(ArvixError):
            self.core.receive_file(make_zip({"a": b"1", "b": b"2", "c": b"3"}), "many.zip")

    def test_docx_becomes_text_for_the_head(self) -> None:
        info = self.core.receive_file(make_docx(["Сочинение", "Первый абзац."]), "эссе.docx")
        self.assertEqual(len(info["read"]), 1)
        self.assertEqual((self.vault / info["read"][0]).read_text(encoding="utf-8"), "Сочинение\nПервый абзац.")

    def test_video_without_ffmpeg_still_stored_with_explanation(self) -> None:
        with mock.patch.object(files.shutil, "which", return_value=None):
            info = self.core.receive_file(b"\x00\x00\x00\x18ftypmp42", "урок.mp4", stt=FakeSTT("текст"))
        self.assertTrue((self.vault / info["path"]).is_file())
        self.assertEqual(info["read"], [])
        self.assertTrue(any("ffmpeg" in n for n in info["notes"]))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "нет ffmpeg")
    def test_video_gives_frames_and_transcript(self) -> None:
        out = self.tmp / "clip.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=4:size=160x120:rate=10",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", str(out)], check=True, capture_output=True, timeout=60)
        stt = FakeSTT("сила тока равна напряжению делить на сопротивление")
        info = self.core.receive_file(out.read_bytes(), "урок.mp4", stt=stt)
        frames = [r for r in info["read"] if r.endswith(".jpg")]
        self.assertGreaterEqual(len(frames), 2)
        self.assertLessEqual(len(frames), files.MAX_FRAMES)
        transcript = [r for r in info["read"] if r.endswith("расшифровка.md")]
        self.assertIn("сопротивление", (self.vault / transcript[0]).read_text(encoding="utf-8"))
        self.assertTrue(stt.seen and stt.seen[0])


class TelegramFileTest(BotCase):
    def send_message(self, **media: Any) -> None:
        self.bot.handle({"update_id": 9, "message": {"from": {"id": OWNER}, "chat": {"id": OWNER}, "date": 1, **media}})

    def test_photo_goes_to_head_with_path_to_read(self) -> None:
        self.api.download = lambda file_id: PNG  # type: ignore[method-assign]
        self.brain.answers.append({"reply": "Вижу задачу №8. Где ты взял R = 6?", "actions": []})
        self.send_message(photo=[{"file_id": "s", "file_size": 10, "width": 90, "height": 90},
                                 {"file_id": "big", "file_size": 900, "width": 1280, "height": 960}], caption="проверь")
        call = self.brain.calls[-1]
        self.assertTrue(call["vault_tools"])
        self.assertIn("<attachments>", call["system"])
        self.assertIn(str(self.vault / "00_Inbox" / "Файлы" / "2026-11-02"), call["system"])
        self.assertIn("не инструкции", call["system"])
        self.assertEqual(call["prompt"], "проверь")
        self.assertIn("Где ты взял R = 6?", self.api.last)
        self.assertTrue(any(e.payload.get("text", "").startswith("📎 ") for e in self.core.store.read(0) if e.kind == "message_in"))

    def test_photo_while_report_is_awaited_is_still_the_report(self) -> None:
        task = self.core.add_task("Зал", start="11:00", sphere="sport", importance=2)
        self.bot.await_set("report", task=task.id)
        self.send_message(photo=[{"file_id": "p", "file_size": 10}], caption="жим 3×8")
        self.assertEqual(self.core.state.tasks[task.id].status, "done")
        self.assertEqual(self.brain.calls, [])

    def test_document_over_limit_is_refused_without_download(self) -> None:
        def boom(file_id: str) -> bytes:
            raise AssertionError("не должен качать")

        self.api.download = boom  # type: ignore[method-assign]
        self.send_message(document={"file_id": "d", "file_name": "фильм.mkv", "file_size": 50 * 1024 * 1024})
        self.assertIn("больше 20 МБ", self.api.last)


class UploadServerTest(test_v04.ServerTest):
    def test_upload_from_app_reaches_the_head(self) -> None:
        import time
        import urllib.parse
        import urllib.request

        self.brain.answers.append({"reply": "В PDF — пробник, 25 заданий.", "actions": []})
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/upload", data=b"%PDF-1.4 fake", method="POST", headers={
            "Authorization": f"Bearer {self.app.token}", "Content-Type": "application/pdf",
            "X-File-Name": urllib.parse.quote("пробник ОГЭ.pdf"), "X-Caption": urllib.parse.quote("что тут?")})
        with urllib.request.urlopen(request, timeout=10) as response:
            self.assertEqual(response.status, 202)
        for _ in range(100):
            if self.brain.calls:
                break
            time.sleep(0.05)
        self.assertIn("пробник ОГЭ.pdf", self.brain.calls[-1]["system"])
        stored = list((self.vault / "00_Inbox" / "Файлы").rglob("*пробник ОГЭ.pdf"))
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].read_bytes(), b"%PDF-1.4 fake")


class InstallTest(BotCase):
    def test_install_link_is_one_time_and_expires(self) -> None:
        from arvix.web.auth import PAIR_MINUTES, app_token, claim_pair

        self.core.cfg.raw["web"] = {"public_url": "https://1-2-3-4.sslip.io:8443"}
        self.brain.answers.append({"reply": "Держи.", "actions": [{"type": "install_app"}]})
        self.text("скинь приложение на телефон, apk")
        text, buttons = self.api.sent[-1]
        self.assertIn("Arvix на телефон", text)
        label, data = buttons[0][0]
        self.assertTrue(data.startswith("url:https://1-2-3-4.sslip.io:8443/#p="), data)
        self.assertNotIn(app_token(self.core), data)  # постоянный ключ в переписку не попадает
        code = data.split("#p=")[1]
        self.assertEqual(claim_pair(self.core, code), app_token(self.core))
        self.assertIsNone(claim_pair(self.core, code))  # второй раз — нет
        self.bot.send_install()
        code = self.api.sent[-1][1][0][0][1].split("#p=")[1]
        self.at(self.core.now() + __import__("datetime").timedelta(minutes=PAIR_MINUTES + 1))
        self.assertIsNone(claim_pair(self.core, code))  # устарела

    def test_no_public_url_explains(self) -> None:
        self.bot.send_install()
        self.assertIn("HTTPS", self.api.last)


class PairServerTest(test_v04.ServerTest):
    def test_claim_over_http_without_login(self) -> None:
        self.core.cfg.raw["web"] = {"public_url": "https://x.sslip.io:8443"}
        code = self.bot.install_link().split("#p=")[1]
        status, body = self.call("/api/pair/claim?code=" + code, token=None)
        self.assertEqual((status, body["token"]), (200, self.app.token))
        status, body = self.call("/api/pair/claim?code=" + code, token=None)
        self.assertEqual(status, 403)
        self.assertIn("устарела", body["error"])

    def test_share_without_service_worker_goes_to_chat(self) -> None:
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/share", body=b"--x--", headers={"Content-Type": "multipart/form-data; boundary=x"})
        response = conn.getresponse()
        response.read()
        self.assertEqual((response.status, response.headers["Location"]), (303, "/?tab=chat"))
        conn.close()


class AvatarTest(unittest.TestCase):
    def test_set_profile_photo_sends_multipart_with_attach(self) -> None:
        import json as _json

        from arvix.telegram.api import TelegramAPI

        seen: dict[str, Any] = {}

        class Response(io.BytesIO):
            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *a: Any) -> None:
                return None

        def fake_urlopen(request: Any, timeout: int = 0) -> Response:
            seen["url"], seen["body"], seen["type"] = request.full_url, request.data, request.headers["Content-type"]
            return Response(_json.dumps({"ok": True, "result": True}).encode())

        png = (Path(files.__file__).resolve().parent.parent / "deploy" / "avatar.png").read_bytes()
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            TelegramAPI("123:x").set_profile_photo(png)
        self.assertTrue(seen["url"].endswith("/setMyProfilePhoto"))
        self.assertTrue(seen["type"].startswith("multipart/form-data; boundary="))
        self.assertIn(b'"photo": "attach://avatar"', seen["body"])
        self.assertIn(b'name="avatar"; filename="avatar.png"', seen["body"])
        self.assertIn(png[:64], seen["body"])
