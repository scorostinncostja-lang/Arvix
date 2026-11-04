import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arvix import remote


class RemoteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        patcher = mock.patch.dict(os.environ, {"ARVIX_CONFIG_DIR": self.dir.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("ARVIX_LOCAL", None)

    def write(self, text: str) -> None:
        (Path(self.dir.name) / "config.toml").write_text(text, encoding="utf-8")

    def test_local_without_remote_section(self) -> None:
        self.assertIsNone(remote.target())
        self.write('vault = "/x"\n')
        self.assertIsNone(remote.target())

    def test_remote_target_and_command(self) -> None:
        self.write('[remote]\nhost = "arvix@vps"\n')
        host, app = remote.target()
        self.assertEqual(host, "arvix@vps")
        cmd = remote._command(host, app, "arvix_cli.py", ["note", "две мысли; rm -rf"])
        self.assertEqual(cmd[0], "ssh")
        self.assertIn("BatchMode=yes", cmd)
        self.assertTrue(cmd[-1].startswith("ARVIX_LOCAL=1 exec python3 $HOME/.local/share/arvix/app/scripts/arvix_cli.py"))
        self.assertIn("'две мысли; rm -rf'", cmd[-1])

    def test_server_side_never_forwards(self) -> None:
        self.write('[remote]\nhost = "arvix@vps"\n')
        with mock.patch.dict(os.environ, {"ARVIX_LOCAL": "1"}):
            self.assertIsNone(remote.target())
