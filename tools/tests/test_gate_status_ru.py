#!/usr/bin/env python3
"""
Статусы гейтов словами: _shared-references/gate_status_ru.py ↔ кодлисты ↔ gate-status-labels.md ↔ вьюер.

Скиллы говорят о гейтах теми же словами, что и страница: подписи и смысл живут в кодлисте `gate_status`
(`_shared-references/codelists.json`), gate_status_ru и вьюер (GATE_STATUS_META из CL) их читают. 26.10.2026 владелец не распознал вопрос «применить гейты? YDEX
reviewed_under_review» — коды в тексте для человека не читаются (RPA-35). Дрейф подписи в любом
из трёх мест должен ронять этот тест.

Запуск:
    python3 tools/tests/test_gate_status_ru.py
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_shared-references"))
import codelists  # noqa: E402
from gate_status_ru import GATE_STATUS_RU, label, phrase  # noqa: E402

JS = (ROOT / "tools/assets/viewer.js").read_text(encoding="utf-8")


def viewer_labels() -> dict:
    """Подписи вьюера: GATE_STATUS_META строится из CL.codes('gate_status') / CL.ru('gate_status', k)."""
    assert "const GATE_STATUS_META = Object.fromEntries(CL.codes('gate_status').map(k => [k, { label: CL.ru('gate_status', k)" in JS, \
        "GATE_STATUS_META вьюера не из кодлистов"
    return {c: e["ru"] for c, e in codelists.entries("gate_status").items()}


def md_rows() -> dict:
    md = (ROOT / "_shared-references/gate-status-labels.md").read_text(encoding="utf-8")
    return {code: (lab.strip(), eff.strip())
            for code, lab, eff in re.findall(r"^\| `(\w+)` \| ([^|]+) \| ([^|]+) \|$", md, re.M)}


def valid_statuses() -> set:
    # Файл гейтов упразднён (schema.md §4.4): ни apply_gate_review.py, ни слоя гейтов в validate_library нет —
    # допустимые коды берутся прямо из кодлиста, как у модуля (б)
    return set(codelists.codes("gate_status"))


class TestGateStatusRu(unittest.TestCase):

    def test_same_codes_everywhere(self):
        self.assertEqual(set(GATE_STATUS_RU), valid_statuses())
        self.assertEqual(set(GATE_STATUS_RU), set(viewer_labels()))
        self.assertEqual(set(GATE_STATUS_RU), set(md_rows()))

    def test_labels_match_viewer(self):
        v = viewer_labels()
        for code, (lab, _) in GATE_STATUS_RU.items():
            self.assertEqual(lab, v[code], code)

    def test_module_reads_codelists(self):
        self.assertEqual(GATE_STATUS_RU, {c: (e["ru"], e["effect"]) for c, e in codelists.entries("gate_status").items()})
        self.assertIn("const GATE_STATUS_HINT = CL.words('gate_status', 'hint')", JS)

    def test_md_table_matches_module(self):
        rows = md_rows()
        for code, pair in GATE_STATUS_RU.items():
            self.assertEqual(rows[code], pair, code)

    def test_helpers(self):
        self.assertEqual(label("reviewed_keep"), "держать")   # R27: подписи статусов = слова решений
        self.assertEqual(label(None), "—")
        self.assertEqual(label("bogus"), "bogus")  # неизвестный код не прячется
        self.assertTrue(phrase("reviewed_under_review").startswith("«наблюдать» (решение — наблюдать: разбор нашёл"))
        self.assertIn("докупка закрыта", phrase("reviewed_under_review"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
