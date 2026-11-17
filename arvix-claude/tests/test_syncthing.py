"""R9 · Syncthing вместо rsync: настройка папки, `arvix doctor`, выключенный rsync. Без сети:
REST API Syncthing подменён словарями в памяти."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.parse
from unittest import mock
from pathlib import Path

from tests.helpers import ROOT  # noqa: F401 — кладёт пакет в sys.path

from arvix import syncthing
from arvix.vault import Vault

ME = "AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA"
PEER = "BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB"
OLD = "CCCCCCC-CCCCCCC-CCCCCCC-CCCCCCC-CCCCCCC-CCCCCCC-CCCCCCC-CCCCCCC"


class FakeSyncthing(syncthing.Client):
    """Минимум REST API Syncthing, который трогают link() и doctor()."""

    def __init__(self) -> None:
        super().__init__("http://127.0.0.1:8384", "key")
        self.alive = True
        self.gui = {"address": "127.0.0.1:8384"}
        self.devices: dict[str, dict] = {ME: {"deviceID": ME, "name": "me", "addresses": ["dynamic"]}}
        self.folders: dict[str, dict] = {}
        self.ignores: dict[str, list[str]] = {}
        self.options = {"globalAnnounceEnabled": True, "relaysEnabled": True, "natEnabled": True}
        self.status: dict[str, dict] = {}
        self.connected: set[str] = set()
        self.writes: list[tuple[str, str]] = []

    def call(self, method, path, body=None):
        if not self.alive:
            raise syncthing.SyncthingError("не отвечает http://127.0.0.1:8384")
        route, _, query = path.partition("?")
        folder = urllib.parse.parse_qs(query).get("folder", [""])[0]
        if method != "GET":
            self.writes.append((method, route))
        if route == "/rest/system/ping":
            return {"ping": "pong"}
        if route == "/rest/system/status":
            return {"myID": ME}
        if route == "/rest/config/gui":
            if method == "PATCH":
                self.gui.update(body)
            return dict(self.gui)
        if route == "/rest/config/devices":
            if method == "POST":
                self.devices[body["deviceID"]] = dict(body)
            return list(self.devices.values())
        if route.startswith("/rest/config/devices/"):
            self.devices[route.rsplit("/", 1)[1]].update(body)
            return None
        if route == "/rest/config/folders":
            if method == "POST":
                self.folders[body["id"]] = dict(body)
            return [dict(f) for f in self.folders.values()]
        if route.startswith("/rest/config/folders/"):
            self.folders[route.rsplit("/", 1)[1]].update(body)
            return None
        if route == "/rest/db/ignores":
            if method == "POST":
                self.ignores[folder] = list(body["ignore"])
            return {"ignore": self.ignores.get(folder)}
        if route == "/rest/db/status":
            return self.status.get(folder, {"state": "idle", "errors": 0, "pullErrors": 0})
        if route == "/rest/config/options":
            if method == "PATCH":
                self.options.update(body)
            return dict(self.options)
        if route == "/rest/system/connections":
            return {"connections": {d: {"connected": d in self.connected} for d in self.devices}}
        raise AssertionError(f"неожиданный запрос {method} {path}")


class SyncthingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="arvix-st-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.vault = self.tmp / "vault"
        (self.vault / ".obsidian").mkdir(parents=True)
        (self.vault / "Заметка.md").write_text("# Заметка\n", encoding="utf-8")
        self.st = FakeSyncthing()

    def link(self, **kw):
        args = {"folder": "arvix-vault", "vault": self.vault, "peer": PEER, "name": "arvix-server",
                "address": "tcp://203.0.113.5:22000"}
        args.update(kw)
        return syncthing.link(self.st, **args)

    # --- настройка ----------------------------------------------------------------

    def test_link_creates_shared_folder_with_ignores_and_is_idempotent(self) -> None:
        changes = self.link()
        self.assertTrue(changes)
        folder = self.st.folders["arvix-vault"]
        self.assertTrue(syncthing.same_path(folder["path"], self.vault))
        self.assertEqual(folder["type"], "sendreceive")
        self.assertEqual({d["deviceID"] for d in folder["devices"]}, {ME, PEER})
        self.assertEqual(folder["versioning"]["type"], "trashcan")
        self.assertEqual(self.st.devices[PEER]["addresses"], ["tcp://203.0.113.5:22000", "dynamic"])
        ignores = self.st.ignores["arvix-vault"]
        self.assertIn("/.obsidian/workspace*", ignores)
        self.assertIn("/.trash", ignores)
        self.assertTrue((self.vault / ".stfolder").is_dir())

        writes = len(self.st.writes)
        self.assertEqual(self.link(), [])
        self.assertEqual(len(self.st.writes), writes, "второй запуск ничего не пишет")

    def test_link_reuses_existing_folder_and_keeps_other_devices_and_ignores(self) -> None:
        # Как на ноутбуке владельца: папка obsidian-vault уже есть и общая со старым сервером.
        self.st.devices[OLD] = {"deviceID": OLD, "name": "arvix-vps", "addresses": ["tcp://198.51.100.1:22000"]}
        self.st.folders["obsidian-vault"] = {"id": "obsidian-vault", "path": str(self.vault),
                                             "devices": [{"deviceID": ME}, {"deviceID": OLD}], "versioning": {"type": ""}}
        self.st.ignores["obsidian-vault"] = ["свой-игнор"]
        self.link(folder="obsidian-vault")
        folder = self.st.folders["obsidian-vault"]
        self.assertEqual([d["deviceID"] for d in folder["devices"]], [ME, OLD, PEER])
        self.assertEqual(folder["versioning"]["type"], "trashcan")
        self.assertEqual(self.st.ignores["obsidian-vault"][0], "свой-игнор")
        self.assertNotIn("arvix-vault", self.st.folders, "вторая папка на тот же путь не создаётся")

    def test_link_refuses_second_folder_on_same_path_and_wrong_path(self) -> None:
        self.st.folders["obsidian-vault"] = {"id": "obsidian-vault", "path": str(self.vault), "devices": []}
        with self.assertRaises(syncthing.SyncthingError):
            self.link(folder="arvix-vault")
        self.st.folders["arvix-vault"] = {"id": "arvix-vault", "path": str(self.tmp / "другое"), "devices": []}
        with self.assertRaises(syncthing.SyncthingError):
            self.link(folder="arvix-vault")

    def test_private_side_turns_off_announce_and_relays(self) -> None:
        self.link(private=True)
        self.assertEqual(set(self.st.options.values()), {False})

    def test_prepare_moves_gui_to_loopback_and_finds_folder(self) -> None:
        self.st.gui["address"] = "0.0.0.0:8384"
        self.st.folders["obsidian-vault"] = {"id": "obsidian-vault", "path": str(self.vault), "devices": []}
        found = syncthing.prepare(self.st, self.vault)
        self.assertEqual(self.st.gui["address"], "127.0.0.1:8384")
        self.assertEqual(found["folder"], "obsidian-vault")
        self.assertEqual(found["id"], ME)

    # --- doctor ------------------------------------------------------------------

    def statuses(self, lines):
        return [s for s, _, _ in lines]

    def test_doctor_ok_when_running_idle_and_peer_connected(self) -> None:
        self.link()
        self.st.connected.add(PEER)
        lines = syncthing.doctor(self.vault, "arvix-vault", client=self.st)
        self.assertEqual(self.statuses(lines), ["OK", "OK", "OK"])
        self.assertIn("arvix-server", lines[-1][1])

    def test_doctor_fails_when_syncthing_down_or_folder_in_error(self) -> None:
        self.link()
        self.st.status["arvix-vault"] = {"state": "error", "error": "folder marker missing", "errors": 0}
        lines = syncthing.doctor(self.vault, "arvix-vault", client=self.st)
        self.assertIn("FAIL", self.statuses(lines))
        self.assertTrue(any("folder marker missing" in hint for _, _, hint in lines))

        self.st.status["arvix-vault"] = {"state": "idle", "errors": 0, "pullErrors": 2}
        self.assertIn("FAIL", self.statuses(syncthing.doctor(self.vault, "arvix-vault", client=self.st)))

        self.st.alive = False
        lines = syncthing.doctor(self.vault, "arvix-vault", client=self.st)
        self.assertEqual(self.statuses(lines), ["FAIL"])
        self.assertIn("systemctl --user enable --now syncthing", lines[0][2])

    def test_doctor_fails_without_folder_and_warns_on_offline_peer(self) -> None:
        self.assertIn("FAIL", self.statuses(syncthing.doctor(self.vault, "arvix-vault", client=self.st)))
        self.link()
        lines = syncthing.doctor(self.vault, "arvix-vault", client=self.st)
        self.assertEqual(lines[-1][0], "WARN")
        self.assertIn("не на связи", lines[-1][1])

    def test_doctor_fails_when_gui_is_open_to_network(self) -> None:
        self.link()
        self.st.connected.add(PEER)
        gui = syncthing.Gui(address="0.0.0.0:8384", api_key="key", tls=False)
        self.assertIn("FAIL", self.statuses(syncthing.doctor(self.vault, "arvix-vault", client=self.st, gui=gui)))

    def test_doctor_without_config_xml_points_to_setup(self) -> None:
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp), "XDG_STATE_HOME": str(self.tmp / "s"),
                                                   "XDG_CONFIG_HOME": str(self.tmp / "c")}):
            os.environ.pop("STHOMEDIR", None)
            lines = syncthing.doctor(self.vault, "arvix-vault")
        self.assertEqual(self.statuses(lines), ["FAIL"])
        self.assertIn("syncthing-setup.sh", lines[0][2])

    def test_conflict_files_are_reported_and_versions_ignored(self) -> None:
        (self.vault / "Inbox.sync-conflict-20261117-221500-BBBBBBB.md").write_text("вторая версия", encoding="utf-8")
        (self.vault / ".stversions").mkdir()
        (self.vault / ".stversions" / "Старое.sync-conflict-20261101-101010-AAAAAAA.md").write_text("x", encoding="utf-8")
        self.assertEqual(syncthing.conflicts(self.vault), ["Inbox.sync-conflict-20261117-221500-BBBBBBB.md"])

        lines = syncthing.report(self.vault, {"vault": "syncthing"}, remote=True, probe=lambda v, f: [])
        self.assertEqual(lines[-1][0], "WARN")
        self.assertIn("конфликтов Syncthing: 1", lines[-1][1])

    def test_report_checks_syncthing_only_when_marked(self) -> None:
        seen = []
        probe = lambda vault, folder: seen.append(folder) or [("OK", "Syncthing", "")]  # noqa: E731
        self.assertEqual(syncthing.report(self.vault, {}, remote=False, probe=probe), [])
        rsync = syncthing.report(self.vault, {"vault": "rsync"}, remote=True, probe=probe)
        self.assertEqual([s for s, _, _ in rsync], ["INFO"])
        self.assertEqual(seen, [])
        syncthing.report(self.vault, {"vault": "syncthing", "folder": "obsidian-vault"}, remote=True, probe=probe)
        self.assertEqual(seen, ["obsidian-vault"])

    def test_config_xml_gui_and_key(self) -> None:
        state = self.tmp / "state" / "syncthing"
        state.mkdir(parents=True)
        (state / "config.xml").write_text(
            '<configuration version="52"><gui enabled="true" tls="true"><address>127.0.0.1:8385</address>'
            "<apikey>secret</apikey></gui></configuration>", encoding="utf-8")
        found = syncthing.find_config_xml({"HOME": str(self.tmp), "XDG_STATE_HOME": str(self.tmp / "state")})
        gui = syncthing.read_gui(found)
        self.assertEqual((gui.api_key, gui.port, gui.local), ("secret", 8385, True))
        self.assertEqual(gui.base_url, "https://127.0.0.1:8385")
        self.assertFalse(syncthing.Gui("0.0.0.0:8384", "k", False).local)

    def test_module_has_no_arvix_imports(self) -> None:
        # Скрипт настройки шлёт файл на сервер через `python3 -`: там нет пакета нужной версии.
        source = Path(syncthing.__file__).read_text(encoding="utf-8")
        self.assertNotIn("from arvix", source)
        self.assertNotIn("import arvix", source)

    def test_vault_search_skips_syncthing_versions(self) -> None:
        (self.vault / ".stversions").mkdir()
        (self.vault / ".stversions" / "Заметка~20261117-101010.md").write_text("# Заметка\n", encoding="utf-8")
        files = [p.name for p in Vault(self.vault).files()]
        self.assertEqual(files, ["Заметка.md"])


@unittest.skipUnless(shutil.which("bash"), "нужен bash")
class VaultSyncScriptTest(unittest.TestCase):
    def test_rsync_script_does_nothing_after_syncthing_setup(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="arvix-vs-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "arvix").mkdir()
        (tmp / "arvix" / "config.toml").write_text(
            f'vault = "{tmp}/vault"\n\n[remote]\nhost = "nobody@203.0.113.5"\n\n[sync]\nvault = "syncthing"\n',
            encoding="utf-8")
        env = dict(os.environ, XDG_CONFIG_HOME=str(tmp), PATH=os.environ.get("PATH", ""))
        done = subprocess.run(["bash", str(ROOT / "deploy" / "vault-sync.sh")], env=env, capture_output=True,
                              text=True, timeout=30, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Syncthing", done.stdout)


if __name__ == "__main__":
    unittest.main()
