"""Граф заметок: ссылки как в Obsidian, призраки, одинокие, подсказки «связать»."""

from __future__ import annotations

from arvix import graph
from arvix.vault import Vault

from tests import test_v04
from tests.helpers import ArvixCase

OHM = "# Закон Ома\nСила тока в проводнике пропорциональна напряжению. Сопротивление проводника измеряется в омах. " * 3
CURRENT = "# Электрический ток\nТок — направленное движение зарядов в проводнике. Напряжение и сопротивление проводника задают ток. " * 3


class GraphTest(ArvixCase):
    def write(self, rel: str, text: str) -> None:
        path = self.vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def setUp(self) -> None:
        super().setUp()
        self.write("Физика/Закон Ома.md", OHM + "\nСм. [[Мощность|мощность тока]] и [[Нет такой]] #физика\n")
        self.write("Физика/Мощность.md", "# Мощность\nP = UI. Ссылка назад: [Ом](Закон%20Ома.md)\n```\n[[В коде не ссылка]]\n```\n")
        self.write("Конспекты/Электрический ток.md", CURRENT + "\n#физика\n")
        self.write("08_Daily Report/2026-11-02.md", "# День\nток напряжение сопротивление проводник " * 5)
        self.write("Одинокая.md", "# Одинокая\nпро кошек и собак, совсем не физика " * 5)
        self.g = graph.build(Vault(self.vault))

    def test_links_ghosts_and_orphans(self) -> None:
        edges = {(e["s"], e["t"]) for e in self.g["edges"]}
        self.assertIn(("Физика/Закон Ома.md", "Физика/Мощность.md"), edges)
        self.assertEqual(len(edges), 1)  # вики-ссылка и обратная md-ссылка — одна связь; ссылка в коде не считается
        self.assertEqual([g["name"] for g in self.g["ghosts"]], ["Нет такой"])
        self.assertIn("Одинокая.md", self.g["orphans"])
        self.assertNotIn("08_Daily Report/2026-11-02.md", self.g["orphans"])
        ohm = next(n for n in self.g["nodes"] if n["name"] == "Закон Ома")
        self.assertEqual((ohm["title"], ohm["degree"], ohm["tags"]), ("Закон Ома", 1, ["физика"]))

    def test_suggestion_links_similar_unlinked_notes_but_not_daily(self) -> None:
        pairs = {(s["a"], s["b"]) for s in self.g["suggestions"]}
        self.assertIn(("Конспекты/Электрический ток.md", "Физика/Закон Ома.md"), pairs)
        self.assertFalse(any("Daily" in a or "Daily" in b for a, b in pairs))
        self.assertFalse(any({a, b} == {"Физика/Закон Ома.md", "Физика/Мощность.md"} for a, b in pairs))
        best = next(s for s in self.g["suggestions"] if s["b"] == "Физика/Закон Ома.md")
        self.assertIn("физика", best["tags"])

    def test_link_line_appends_once(self) -> None:
        text = graph.link_line("# A\nтекст\n", "Б")
        self.assertTrue(text.endswith("\nСвязи: [[Б]]\n"))
        text = graph.link_line(text, "В")
        self.assertTrue(text.endswith("\nСвязи: [[Б]] [[В]]\n"))
        self.assertEqual(graph.link_line(text, "В"), text)


class GraphServerTest(test_v04.ServerTest):
    def test_graph_and_link_over_http(self) -> None:
        (self.vault / "А.md").write_text(OHM, encoding="utf-8")
        (self.vault / "Б.md").write_text(CURRENT, encoding="utf-8")
        status, g = self.call("/api/graph")
        self.assertEqual(status, 200)
        self.assertEqual(len(g["suggestions"]), 1)
        status, body = self.call("/api/note/link", {"a": "А.md", "b": "Б.md"})
        self.assertEqual(status, 200, body)
        self.assertTrue((self.vault / "А.md").read_text(encoding="utf-8").endswith("Связи: [[Б]]\n"))
        status, g = self.call("/api/graph")
        self.assertEqual((len(g["edges"]), g["suggestions"]), (1, []))
