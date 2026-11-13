#!/usr/bin/env python3
"""
Термины словами: _shared-references/terms_ru.py ↔ кодлисты ↔ вьюер (tools/assets/viewer.js).

Контракт D плана переосмысления вьюера (2026-10-26): режимы, вердикты, план владельца, база «L2»
и уверенность словом — один канон для скриптов (render_weekly_md.py) и страницы. Слова кодов живут в
`_shared-references/codelists.json` (шаг 2 цикла машиночитаемости): terms_ru отдаёт их под прежними
именами, вьюер берёт из `CL` (assets/codelists.js). Тест держит, что обе стороны читают JSON.

Запуск:
    python3 tools/tests/test_terms_ru.py
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared-references"))
import codelists  # noqa: E402
import terms_ru as T  # noqa: E402

JS = (ROOT / "tools/assets/viewer.js").read_text(encoding="utf-8")


def js_reads(name: str, expr: str) -> bool:
    """`const NAME = <expr>` — словарь вьюера взят из кодлистов, а не записан литералом."""
    return re.search(r"const " + name + r" = " + re.escape(expr), JS) is not None


class TestTermsRu(unittest.TestCase):

    def test_modes_match_viewer(self):
        self.assertEqual(T.MODE_RU, codelists.words("mode_codes"))
        self.assertTrue(js_reads("MODE_RU", "CL.words('mode_codes')"))

    def test_verdicts_match_viewer(self):
        self.assertEqual(T.VERDICT_RU, codelists.words("verdict"))
        self.assertTrue(js_reads("VERDICT_WORD", "CL.words('verdict')"))

    def test_user_plan_matches_viewer(self):
        self.assertEqual(T.USER_PLAN_RU, codelists.words("user_plan"))
        self.assertEqual(T.USER_STATUS_RU, codelists.words("user_status"))   # 3.65.0: статус списком
        self.assertTrue(js_reads("USER_PLAN_WORD", "CL.words('user_plan')"))
        self.assertTrue(js_reads("USER_STATUS_WORD", "CL.words('user_status')"))

    def test_l2_phrase_in_viewer(self):
        self.assertIn(f"replace(/\\bL2\\b/g, '{T.L2_RU}')", JS)

    def test_confidence_thresholds_match_viewer(self):
        m = re.search(r"function confWord\(c\) \{(.*?)\n\}", JS, re.S)
        assert m, "confWord не найден во вьюере"
        body = m.group(1)
        self.assertIn(f"v < {T.CONF_LOW_BELOW} ? 'низкая'", body)
        self.assertIn(f"v < {T.CONF_HIGH_FROM} ? 'средняя' : 'высокая'", body)

    def test_helpers(self):
        self.assertEqual(T.conf_word(0.5), "низкая")
        self.assertEqual(T.conf_word(0.65), "средняя")
        self.assertEqual(T.conf_word(0.8), "высокая")
        self.assertEqual(T.conf_word(85), "высокая")     # проценты
        self.assertIsNone(T.conf_word(None))
        self.assertIsNone(T.conf_word(True))
        self.assertIsNone(T.conf_word("0.7"))
        self.assertEqual(T.verdict_word("HOLD"), "Держать")
        self.assertEqual(T.verdict_word("bogus"), "bogus")  # неизвестный код не прячется
        self.assertEqual(T.verdict_word(None), "—")
        self.assertEqual(T.mode_word(4), "разбор бумаги")
        self.assertIsNone(T.mode_word("12"))
        self.assertEqual(T.user_plan_word("BALANCE"), "привести к плану")
        self.assertEqual(T.gate_label("reviewed_keep"), "держать")   # реэкспорт gate_status_ru


if __name__ == "__main__":
    unittest.main(verbosity=1)
