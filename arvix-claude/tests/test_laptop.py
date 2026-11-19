"""Ноутбук (D42): команды `arvix` там нет, интерфейс — приложение с раскладкой под широкий экран."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT

STATIC = ROOT / "arvix" / "web" / "static"


class InstallCliTest(unittest.TestCase):
    """deploy/install.sh в песочнице: свой HOME, заглушки claude и systemctl — живая система не трогается."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="arvix-install-"))
        self.home = self.tmp / "home"
        stubs = self.tmp / "stubs"
        stubs.mkdir()
        for name in ("claude", "systemctl"):
            (stubs / name).write_text("#!/bin/sh\nexit 0\n")
            (stubs / name).chmod(0o755)
        self.env = {
            "HOME": str(self.home),
            "PATH": f"{stubs}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local/share"),
        }
        self.conf = self.home / ".config/arvix/config.toml"
        self.conf.parent.mkdir(parents=True)
        self.bin = self.home / ".local/bin/arvix"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def install(self) -> str:
        run = subprocess.run(["bash", str(ROOT / "deploy/install.sh")], env=self.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return run.stdout

    def test_remote_laptop_gets_no_cli_and_old_one_is_removed(self) -> None:
        self.conf.write_text(f'vault = "{self.tmp}/vault"\n\n[remote]\nhost = "arvix@example"\n')
        self.bin.parent.mkdir(parents=True)
        self.bin.write_text('#!/usr/bin/env bash\nexec python3 "/x/scripts/arvix_cli.py" "$@"\n')
        out = self.install()
        self.assertFalse(self.bin.exists())
        self.assertIn("удалён", out)

    def test_foreign_arvix_binary_is_left_alone(self) -> None:
        self.conf.write_text('[remote]\nhost = "arvix@example"\n')
        self.bin.parent.mkdir(parents=True)
        self.bin.write_text("#!/bin/sh\necho чужая программа\n")
        self.install()
        self.assertTrue(self.bin.exists())

    def test_server_still_gets_cli(self) -> None:
        self.conf.write_text(f'vault = "{self.tmp}/vault"\n')
        self.install()
        self.assertIn("arvix_cli.py", self.bin.read_text())


class LaptopLayoutTest(unittest.TestCase):
    def test_wide_threshold_is_the_same_in_css_and_js(self) -> None:
        css = (STATIC / "app.css").read_text()
        js = (STATIC / "app.js").read_text()
        js_px = re.search(r'matchMedia\("\(min-width: (\d+)px\)"\)', js)
        self.assertIsNotNone(js_px)
        self.assertIn(f"@media (min-width: {js_px.group(1)}px)", css)
        for selector in (".today-grid", ".notes-split", ".progress-grid", ".side-hint"):
            self.assertIn(selector, css)

    def test_shortcuts_use_physical_keys(self) -> None:
        """Владелец пишет по-русски: на ЙЦУКЕН «/» — это «.», «E» — «у»; клавиши ловятся по e.code."""
        js = (STATIC / "app.js").read_text()
        self.assertIn('e.code === "Slash"', js)
        self.assertIn('e.code === "KeyE"', js)
        self.assertIn('e.code === "KeyN"', js)

    def test_sidebar_markup(self) -> None:
        html = (STATIC / "index.html").read_text()
        self.assertIn('class="brand"', html)
        self.assertEqual(html.count("data-tab="), 5)  # Сегодня · Арвикс · Заметки · Проекты (D43) · Прогресс

    def test_sidebar_collapses(self) -> None:
        """Панель сворачивается в полосу значков кнопкой (касание, не наведение) и Ctrl+B; выбор помнится."""
        html = (STATIC / "index.html").read_text()
        css = (STATIC / "app.css").read_text()
        js = (STATIC / "app.js").read_text()
        self.assertIn('id="side-toggle"', html)
        self.assertIn("aria-expanded", html)
        self.assertIn(":root.side-mini { --side-w:", css)
        self.assertIn('"arvix_side_mini"', js)
        self.assertIn('e.code === "KeyB"', js)
        # Свёрнутая панель не прячет разделы: значки остаются, подписи уходят в title
        self.assertEqual(html.count('class="lbl"'), 5)


class TabletLayoutTest(unittest.TestCase):
    """Планшет (Lenovo Tab P11): «portrait» в манифесте заставлял Android рисовать WebAPK полосой с обоями по бокам."""

    def test_manifest_does_not_lock_orientation(self) -> None:
        manifest = json.loads((STATIC / "manifest.webmanifest").read_text())
        self.assertIn(manifest.get("orientation", "any"), ("any", "natural"))

    def test_portrait_tablet_fills_the_width(self) -> None:
        css = (STATIC / "app.css").read_text()
        block = css.split("@media (min-width: 600px) and (max-width: 899.98px)", 1)
        self.assertEqual(len(block), 2, "нет раскладки для планшета вертикально")
        self.assertIn("#app { max-width: none; }", block[1])

    def test_hover_styles_only_for_a_real_pointer(self) -> None:
        """На сенсорном экране :hover залипает после касания — правила наведения только под (hover: hover)."""
        css = (STATIC / "app.css").read_text()
        hover_block = css.split("@media (min-width: 900px) and (hover: hover)", 1)
        self.assertEqual(len(hover_block), 2)
        outside = hover_block[0] + hover_block[1].split("\n}\n", 1)[1]
        self.assertNotIn(":hover", outside)


if __name__ == "__main__":
    unittest.main()
