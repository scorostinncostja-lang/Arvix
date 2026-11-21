"""Разметка ответов (D57): одна и та же в Telegram (telegram/fmt.py) и в приложении (app.js, richText).

Модель пишет **жирный**, *курсив*, `код` и списки строками «- » — Telegram получает <b>/<i>/<code>,
приложение рисует то же самое из журнала, где текст лежит с разметкой."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest

from arvix.prompt import read_block, system_prompt
from arvix.telegram import fmt
from tests.test_laptop import STATIC
from tests.test_telegram import BotCase


class TelegramMarkupTest(unittest.TestCase):
    def test_bold_italic_code(self) -> None:
        self.assertEqual(fmt.to_html("**В 18:00** физика, *если успеешь*, формула `U = I*R`"),
                         "<b>В 18:00</b> физика, <i>если успеешь</i>, формула <code>U = I*R</code>")

    def test_multiplication_and_words_with_stars_stay_text(self) -> None:
        self.assertEqual(fmt.to_html("5 * 3 * 2 и a*b*c"), "5 * 3 * 2 и a*b*c")

    def test_escaping_still_first(self) -> None:
        self.assertEqual(fmt.to_html("*<b>* и `<i>`"), "<i>&lt;b&gt;</i> и <code>&lt;i&gt;</code>")

    def test_plain_fallback_has_no_markers(self) -> None:
        self.assertEqual(fmt.strip_markup("**Важно**: *курсив* и `код`, 2 * 3"), "Важно: курсив и код, 2 * 3")


class StoredMarkupTest(BotCase):
    def test_code_message_keeps_bold_for_the_app(self) -> None:
        # раньше send_rich писал в журнал текст без звёздочек — в приложении жирный пропадал
        self.bot.send_rich("📚 **Физика: §12**\n⏱ 30 мин")
        out = [e for e in self.core.store.read() if e.kind == "message_out"][-1]
        self.assertEqual(out.payload["text"], "📚 **Физика: §12**\n⏱ 30 мин")
        self.assertNotIn("**", self.api.last)


class PromptAsksForEmphasisTest(BotCase):
    def test_channel_rule_names_what_to_bold(self) -> None:
        block = read_block("channel_telegram")
        self.assertIn("**жирным**", block)
        self.assertIn("*Курсив*", block)
        self.assertIn(block, system_prompt(self.core, message="привет"))

    def test_examples_show_emphasis(self) -> None:
        examples = json.loads((STATIC.parent.parent / "constitution" / "fewshot.json").read_text(encoding="utf-8"))
        bold = [e for e in examples if "**" in e["arvix"]]
        self.assertGreaterEqual(len(bold), 5)
        for e in bold:  # жирный — точечно, а не целым ответом
            self.assertLessEqual(e["arvix"].count("**") // 2, 3, e["situation"])


@unittest.skipUnless(shutil.which("node"), "нужен node")
class AppRichTextTest(unittest.TestCase):
    """richText из app.js — в node, без браузера: вырезается по меткам rich:start / rich:end."""

    def render(self, text: str, fn: str = "richText") -> str:
        js = (STATIC / "app.js").read_text(encoding="utf-8")
        esc = next(line for line in js.splitlines() if line.startswith("const esc ="))
        body = js[js.index("/* rich:start"):js.index("/* rich:end */")]
        script = f"{esc}\n{body}\nprocess.stdout.write({fn}({json.dumps(text, ensure_ascii=False)}));"
        return subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True, timeout=20).stdout

    def test_inline_marks(self) -> None:
        self.assertEqual(self.render("**В 18:00** физика, *если успеешь*, `U = I*R`, 5 * 3 * 2"),
                         "<p><b>В 18:00</b> физика, <i>если успеешь</i>, <code>U = I*R</code>, 5 * 3 * 2</p>")

    def test_lines_paragraphs_and_lists(self) -> None:
        html = self.render("Первое.\nВторое.\n\nПлан:\n— математика\n— физика\n1. раз\n2. два")
        self.assertEqual(html, "<p>Первое.<br>Второе.</p><p>План:</p>"
                               "<ul class=\"m-list\"><li>математика</li><li>физика</li></ul>"
                               "<ol class=\"m-list\"><li>раз</li><li>два</li></ol>")

    def test_quote_code_block_and_links(self) -> None:
        html = self.render("> мысль\n```\na**b**\n```\nhttps://example.org/x.")
        self.assertEqual(html, "<blockquote>мысль</blockquote><pre class=\"m-code\"><code>a**b**</code></pre>"
                               "<p><a href=\"https://example.org/x\" target=\"_blank\" rel=\"noopener\">https://example.org/x</a>.</p>")

    def test_no_tag_from_model_reaches_page(self) -> None:
        html = self.render("<img src=x onerror=alert(1)> **<script>**")
        self.assertNotIn("<img", html)
        self.assertNotIn("<script", html)
        self.assertIn("<b>&lt;script&gt;</b>", html)

    def test_plain_text_for_quotes_and_copy(self) -> None:
        self.assertEqual(self.render("**Важно**: *курсив* и `код`, 2 * 3", "plainText"), "Важно: курсив и код, 2 * 3")


if __name__ == "__main__":
    unittest.main()
