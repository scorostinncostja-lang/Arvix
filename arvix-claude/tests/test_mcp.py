"""MCP-сервер: протокол JSON-RPC по stdio, как его видит Claude Code."""

import json
import os
import subprocess
import sys
import unittest

from arvix.mcp_server import HANDLERS, TOOLS, Server

from tests.helpers import ROOT, ArvixCase


class McpProtocolTest(ArvixCase):
    def rpc(self, proc: subprocess.Popen, msg_id: int | None, method: str, params: dict | None = None) -> dict | None:
        msg = {"jsonrpc": "2.0", "method": method, **({"id": msg_id} if msg_id is not None else {}), **({"params": params} if params else {})}
        proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode())
        proc.stdin.flush()
        if msg_id is None:
            return None
        return json.loads(proc.stdout.readline())

    def test_stdio_roundtrip(self) -> None:
        cfg = self.tmp / "cfg"
        cfg.mkdir(exist_ok=True)
        (cfg / "config.toml").write_text(f'vault = "{self.vault}"\n', encoding="utf-8")
        env = {**os.environ, "ARVIX_CONFIG_DIR": str(cfg), "ARVIX_DATA_DIR": str(self.tmp / "mcpdata")}
        proc = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "arvix_mcp.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        try:
            init = self.rpc(proc, 1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}})
            self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")
            self.assertEqual(init["result"]["serverInfo"]["name"], "arvix")
            self.rpc(proc, None, "notifications/initialized")
            tools = self.rpc(proc, 2, "tools/list")["result"]["tools"]
            self.assertEqual({t["name"] for t in tools}, set(TOOLS))
            for tool in tools:
                self.assertEqual(tool["inputSchema"]["type"], "object")
            added = self.rpc(proc, 3, "tools/call", {"name": "task", "arguments": {"action": "add", "title": "Физика", "start": "23:50", "importance": 2, "sphere": "work"}})
            self.assertFalse(added["result"]["isError"], added)
            done = self.rpc(proc, 4, "tools/call", {"name": "task", "arguments": {"action": "complete", "task": "Физика"}})
            self.assertIn("XP", done["result"]["content"][0]["text"])
            context = self.rpc(proc, 5, "tools/call", {"name": "context", "arguments": {}})
            self.assertIn("СОСТОЯНИЕ", context["result"]["content"][0]["text"])
            refused = self.rpc(proc, 6, "tools/call", {"name": "task", "arguments": {"action": "complete", "task": "Физика"}})
            self.assertTrue(refused["result"]["isError"])
            unknown = self.rpc(proc, 7, "nope/method")
            self.assertEqual(unknown["error"]["code"], -32601)
        finally:
            proc.stdin.close()
            proc.wait(timeout=10)
            proc.stdout.close()
            proc.stderr.close()

    def test_unknown_protocol_falls_back(self) -> None:
        reply = Server(lambda: self.core).handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}})
        self.assertIn(reply["result"]["protocolVersion"], ("2025-06-18",))


class McpToolsTest(ArvixCase):
    def call(self, tool: str, **args) -> dict:
        return Server(lambda: self.core).call_tool(tool, args)

    def text(self, tool: str, **args) -> str:
        result = self.call(tool, **args)
        return result["content"][0]["text"]

    def test_no_tool_can_reenable_mentor(self) -> None:
        """Включить ментора обратно может только человек командой — не модель."""
        self.text("mode", action="safety_flag", note="тест")
        self.assertFalse(self.core.state.mentor_enabled)
        result = self.call("profile", action="set", key="mentor_enabled", value="true")
        self.assertTrue(result["isError"])
        for name in HANDLERS:
            self.assertNotIn("mentor_on", json.dumps(TOOLS[name], ensure_ascii=False))
        self.assertFalse(self.core.state.mentor_enabled)

    def test_check_request_reports_conflicts_and_debt(self) -> None:
        task = self.core.add_task("Алгоритмы", start="15:00", duration_min=90, importance=3)
        text = self.text("check_request", description="погулять", start="15:30", duration_min=60)
        self.assertIn(task.id, text)
        self.assertIn("КОНФЛИКТЫ", text)

    def test_interview_and_template(self) -> None:
        self.assertIn("[name]", self.text("interview", action="next"))
        self.assertIn("Сохранено", self.text("interview", action="answer", qid="name", answer="Дастан"))
        out = self.text("profile", action="template", weekdays=[0, 1], day_type="study",
                        blocks=[{"start": "18:00", "duration": 60, "title": "Практика", "sphere": "learning", "importance": 3}])
        self.assertIn("сохранён", out)
        self.assertEqual(self.core.state.templates[0]["blocks"][0]["title"], "Практика")

    def test_goal_hierarchy_and_progress(self) -> None:
        self.assertTrue(self.call("profile", action="goal", title="Фронтенд-джун")["isError"])  # без «зачем» нельзя
        gid = self.text("profile", action="goal", title="Фронтенд-джун", why="уйти со смен", deadline="2027-06-01").split("[")[1][:8]
        stage = self.text("profile", action="goal", title="3 компонента на React", parent_id=gid, deadline="2026-12-15").split("[")[1][:8]
        self.assertTrue(self.call("profile", action="goal", title="x", parent_id="nope0000")["isError"])
        tree = self.text("profile", action="goals")
        self.assertLess(tree.index("Фронтенд-джун"), tree.index("  ○ [" + stage))
        self.assertIn("ЭТАПЫ: 0/1", self.text("context"))
        self.text("profile", action="goal", goal_id=stage, status="done")
        self.assertEqual(self.core.state.goals[stage]["title"], "3 компонента на React")  # остальные поля сохранились
        self.assertIn("● [" + stage, self.text("profile", action="goals"))

    def test_notes_write_into_vault_structure_safely(self) -> None:
        created = self.text("notes", action="write", kind="roadmaps", name="JS", content="# JS\n- [ ] узел 1")
        self.assertIn("03_Resources/Роадмапы/JS.md", created)
        self.assertIn("Перезаписано", self.text("notes", action="write", kind="roadmaps", name="JS", content="# JS v2"))
        path = self.vault / "03_Resources/Роадмапы/JS.md"
        path.write_text("# JS v2\n- [x] узел 1 — моя отметка", encoding="utf-8")  # человек поправил
        self.assertTrue(self.call("notes", action="write", kind="roadmaps", name="JS", content="# JS v3")["isError"])
        self.assertIn("Дописано", self.text("notes", action="write", kind="roadmaps", name="JS", content="- [ ] узел 2", append=True))
        self.assertIn("моя отметка", path.read_text(encoding="utf-8"))
        (self.vault / "Моё.md").write_text("# Мои мысли", encoding="utf-8")
        self.assertTrue(self.call("notes", action="write", path="Моё.md", content="чужое")["isError"])
        self.assertIn("бэкап", self.text("notes", action="write", path="Моё.md", content="# Новое", force=True))
        self.assertTrue(self.call("notes", action="write", path="../outside.md", content="x")["isError"])
        self.assertTrue(self.call("notes", action="write", path=".obsidian/app.md", content="x")["isError"])
        (self.vault / "Bluetooth.md").write_text("# Беспроводные протоколы\nBluetooth LE и GATT", encoding="utf-8")
        self.assertIn("Bluetooth.md", self.text("notes", action="search", query="bluetooth протоколы"))
        self.assertIn("«Беспроводные протоколы»", self.text("notes", action="overview"))
        self.assertTrue(self.call("notes", action="read", path="../../etc/passwd")["isError"])

    def test_block_keeps_human_text(self) -> None:
        (self.vault / "План.md").write_text("# План\nмой текст", encoding="utf-8")
        self.text("notes", action="block", path="План.md", block="сводка", content="v1")
        self.text("notes", action="block", path="План.md", block="сводка", content="v2")
        text = (self.vault / "План.md").read_text(encoding="utf-8")
        self.assertIn("мой текст", text)
        self.assertIn("v2", text)
        self.assertNotIn("v1", text)

    def test_directive_needs_evidence(self) -> None:
        self.core.add_task("x", start="11:00")
        self.assertTrue(self.call("analyst", action="directive", kind="warning", text="без доказательств", evidence=[])["isError"])
        self.assertIn("создана", self.text("analyst", action="directive", kind="warning", text="с доказательством", evidence=[1]))


if __name__ == "__main__":
    unittest.main()
