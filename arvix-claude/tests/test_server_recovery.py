"""Сервер арендованный и может пропасть (D54): бэкап на ноутбук и переезд на новый сервер.

Скрипты deploy/ гоняются в песочнице: свой HOME ноутбука, заглушка `ssh`, которая выполняет удалённую
команду в отдельном «домашнем каталоге сервера», заглушки rsync/systemctl/notify-send. Сеть не нужна.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import time
import tomllib
import unittest
from pathlib import Path

from tests.helpers import ROOT

SSH_STUB = r"""#!/usr/bin/env bash
# Заглушка ssh: опции пропускаются, команда выполняется в $FAKE_SERVER_HOME.
echo "ssh $*" >> "$STUB_LOG"
[[ -n "${STUB_SSH_FAIL:-}" ]] && { echo "ssh: connect to host: Connection timed out" >&2; exit 255; }
while [[ "$1" == -* ]]; do [[ "$1" == -o ]] && shift; shift; done
shift  # хост
HOME="$FAKE_SERVER_HOME" exec bash -c "$*"
"""


def make_journal(path: Path, events: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, at TEXT NOT NULL, local_date TEXT, kind TEXT, "
               "entity_id TEXT, payload TEXT DEFAULT '{}', source TEXT)")
    db.executemany("INSERT INTO events (at, local_date, kind, source) VALUES (?, ?, 'note', 'test')",
                   [(f"2026-11-19T10:{i % 60:02d}:00+03:00", "2026-11-19") for i in range(events)])
    db.commit()
    db.close()


@unittest.skipUnless(shutil.which("sqlite3") and shutil.which("bash"), "нужны sqlite3 и bash")
def count(path: Path) -> int:
    db = sqlite3.connect(path)
    try:
        return db.execute("select count(*) from events").fetchone()[0]
    finally:
        db.close()


class Sandbox(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="arvix-recovery-"))
        self.home = self.tmp / "laptop"
        self.server = self.tmp / "server"
        self.server.mkdir()
        stubs = self.tmp / "stubs"
        stubs.mkdir()
        self.log = self.tmp / "calls.log"
        self.log.touch()
        (stubs / "ssh").write_text(SSH_STUB)
        for name in ("rsync", "systemctl"):
            (stubs / name).write_text(f'#!/bin/sh\necho "{name} $*" >> "$STUB_LOG"\nexit 0\n')
        (stubs / "notify-send").write_text('#!/bin/sh\necho "notify $*" >> "$STUB_LOG"\n')
        for f in stubs.iterdir():
            f.chmod(0o755)
        self.env = {
            "HOME": str(self.home),
            "PATH": f"{stubs}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local/share"),
            "FAKE_SERVER_HOME": str(self.server),
            "STUB_LOG": str(self.log),
        }
        self.backups = self.home / ".local/share/arvix/backups"
        self.laptop_cfg = self.home / ".config/arvix/config.toml"
        self.laptop_cfg.parent.mkdir(parents=True)
        self.laptop_cfg.write_text('vault = "/tmp/нет такого хранилища"\n\n[telegram]\ntoken = "123:new"\nowner_id = 7\n\n'
                                   '[remote]\nhost = "arvix@198.51.100.1"\n')

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_script(self, name: str, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", str(ROOT / "deploy" / name), *args], env={**self.env, **env},
                              capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)

    def calls(self) -> str:
        return self.log.read_text()


class BackupTest(Sandbox):
    """deploy/arvix-backup.sh: журнал и конфиг сервера на ноутбук, без обрывков, с тревогой."""

    def server_has(self, events: int, config: str | None = 'token = "x"\n[stt]\napi_key = "gsk-secret"\n') -> None:
        make_journal(self.server / ".local/share/arvix/arvix.db", events)
        if config is not None:
            (self.server / ".config/arvix").mkdir(parents=True, exist_ok=True)
            (self.server / ".config/arvix/config.toml").write_text(config)

    def test_saves_journal_and_server_config_with_private_mode(self) -> None:
        self.server_has(5)
        run = self.run_script("arvix-backup.sh")
        self.assertEqual(run.returncode, 0, run.stderr)
        today = self.backups / f"arvix-{time.strftime('%Y-%m-%d')}.db"
        self.assertEqual(count(today), 5)
        saved = self.backups / "server-config.toml"
        self.assertEqual(tomllib.loads(saved.read_text())["stt"]["api_key"], "gsk-secret")
        self.assertEqual(stat.S_IMODE(saved.stat().st_mode), 0o600)
        self.assertEqual(list(self.backups.glob("*.part")), [])

    def test_same_day_snapshot_is_refreshed_hourly(self) -> None:
        self.server_has(5)
        self.run_script("arvix-backup.sh")
        self.server_has(9)
        self.run_script("arvix-backup.sh")
        days = list(self.backups.glob("arvix-*.db"))
        self.assertEqual(len(days), 1)
        self.assertEqual(count(days[0]), 9)

    def test_dead_server_leaves_no_fragment_and_warns_once(self) -> None:
        """Было: 0-байтные arvix-*.db.part после каждой неудачи и ни одного сигнала, что бэкапа нет."""
        old = self.backups / "arvix-2026-11-19.db"
        make_journal(old, 3)
        (self.backups / "arvix-2026-11-14.db.part").touch()
        os.utime(old, (time.time() - 30 * 3600,) * 2)
        first = self.run_script("arvix-backup.sh", STUB_SSH_FAIL="1")
        second = self.run_script("arvix-backup.sh", STUB_SSH_FAIL="1")
        self.assertNotEqual(first.returncode, 0)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(list(self.backups.glob("*.part")), [])
        self.assertTrue(old.exists())
        self.assertEqual(self.calls().count("notify "), 1, self.calls())  # не чаще раза в 6 часов
        self.assertIn("restore-server.sh", self.calls())

    def test_fresh_backup_failure_does_not_warn(self) -> None:
        make_journal(self.backups / "arvix-2026-11-19.db", 3)  # снят только что
        self.run_script("arvix-backup.sh", STUB_SSH_FAIL="1")
        self.assertNotIn("notify ", self.calls())

    def test_missing_server_config_keeps_journal_and_old_copy(self) -> None:
        self.server_has(4, config=None)
        self.backups.mkdir(parents=True)
        (self.backups / "server-config.toml").write_text('[stt]\napi_key = "old"\n')
        run = self.run_script("arvix-backup.sh")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(len(list(self.backups.glob("arvix-*.db"))), 1)
        self.assertIn('"old"', (self.backups / "server-config.toml").read_text())

    def test_keeps_last_30_days(self) -> None:
        self.server_has(2)
        for day in range(1, 36):
            f = self.backups / f"arvix-2026-10-{day:02d}.db"
            make_journal(f, 1)
            os.utime(f, (time.time() - (40 - day) * 86400,) * 2)
        self.run_script("arvix-backup.sh")
        self.assertEqual(len(list(self.backups.glob("arvix-*.db"))), 30)


class InitConfigTest(Sandbox):
    """deploy/sync-server.sh --init берёт за основу сохранённый конфиг прошлого сервера."""

    def init(self, saved: str) -> dict:
        self.backups.mkdir(parents=True, exist_ok=True)
        (self.backups / "server-config.toml").write_text(saved)
        run = self.run_script("sync-server.sh", "arvix@203.0.113.7", "--init")
        written = self.server / ".config/arvix/config.toml"
        self.assertTrue(written.exists(), run.stdout + run.stderr)
        return tomllib.loads(written.read_text())

    def test_old_server_keys_move_laptop_wins_paths_fixed(self) -> None:
        cfg = self.init('vault = "/home/arvix/vault"\n[telegram]\ntoken = "123:old"\n[stt]\nengine = "groq"\napi_key = "gsk-1"\n'
                        '[obsidian]\nvault = "Obsidian Vault"\n[web]\npublic_url = "https://198-51-100-1.sslip.io:8443"\n')
        self.assertEqual(cfg["stt"], {"engine": "groq", "api_key": "gsk-1"})
        self.assertEqual(cfg["obsidian"]["vault"], "Obsidian Vault")
        self.assertEqual(cfg["telegram"]["token"], "123:new")             # перевыпущенный токен ноутбука главнее
        self.assertNotIn("remote", cfg)
        self.assertEqual(cfg["vault"], f"{self.server}/vault")
        self.assertNotIn("public_url", cfg.get("web", {}))                 # адрес умершего сервера не переносится

    def test_same_server_keeps_app_address(self) -> None:
        cfg = self.init('[web]\npublic_url = "https://203-0-113-7.sslip.io:8443"\n')
        self.assertEqual(cfg["web"]["public_url"], "https://203-0-113-7.sslip.io:8443")


class RestorePlanTest(Sandbox):
    """deploy/restore-server.sh --dry-run: выбирает целый снимок и ничего не трогает."""

    def setUp(self) -> None:
        super().setUp()
        (self.home / ".ssh").mkdir()
        (self.home / ".ssh/id_ed25519.pub").write_text("ssh-ed25519 AAAA test\n")

    def test_picks_newest_intact_snapshot_without_touching_anything(self) -> None:
        good = self.backups / "arvix-2026-11-18.db"
        make_journal(good, 7)
        broken = self.backups / "arvix-2026-11-19.db"
        broken.write_bytes(b"not a database")
        os.utime(good, (time.time() - 3600,) * 2)
        run = self.run_script("restore-server.sh", "root@203.0.113.7", "--dry-run")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("пропускаю повреждённый снимок", run.stdout)
        self.assertIn("arvix-2026-11-18.db — 7 событий", run.stdout)
        self.assertIn("203-0-113-7.sslip.io", run.stdout)
        self.assertEqual(self.calls(), "")                                  # ни ssh, ни systemctl

    def test_refuses_without_snapshot(self) -> None:
        run = self.run_script("restore-server.sh", "root@203.0.113.7", "--dry-run")
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("нет целого снимка", run.stderr)


if __name__ == "__main__":
    unittest.main()
