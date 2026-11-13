#!/usr/bin/env python3
"""Тесты маппинга последних 4 колонок вкладки «Акции» (с 2026-06).

Колонки сдвинулись: было Действие(11)/IE(12)/T(13)/AI(14) →
стало План(11)/Статус(12)/IE(13)/AI(14). Соответственно в ie_actual.per_ticker:
  user_action/user_note_t  →  user_plan/user_status (user_note_ie сдвинут на col13).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.parse_portfolio import parse_ie_actual, extract_portfolio, compute_metrics


HEADER = [
    "Тикер", "Название", "Стоимость", "Ср, Цена", "Цена", "Точка Входа",
    "IE New", "IE Old", "Доля актуальная", "Доля Планируемая", "Доля Реальная",
    "План", "Статус", "IE", "AI",
]


def _raw(rows):
    """Собрать raw-структуру с листом «Акции» → «Актуальные акции»."""
    return {"Акции": {"Актуальные акции": [HEADER] + rows}}


class TestIeActualColumns(unittest.TestCase):
    def test_new_columns_mapped(self):
        rows = [
            ["SBER", "Сбербанк", 49275.0, 250.0, 300.0, "--",
             0.06, 0.05, 0.11, 0.10, 0.12,
             "Сокращение", "Продал часть", "Держать", "OK"],
        ]
        flags = []
        out = parse_ie_actual(_raw(rows), flags)
        rec = out["per_ticker"]["SBER"]
        # последние 4 колонки → новые поля
        self.assertEqual(rec["user_plan"], "Сокращение")     # col11 План
        self.assertEqual(rec["user_status"], "Продал часть")  # col12 Статус
        self.assertEqual(rec["user_note_ie"], "Держать")      # col13 IE
        self.assertEqual(rec["user_note_ai"], "OK")           # col14 AI
        # доли — дроби → проценты
        self.assertEqual(rec["ie_new_pct"], 6.0)
        self.assertEqual(rec["ie_old_pct"], 5.0)
        self.assertEqual(rec["real_share_pct"], 12.0)

    def test_old_keys_removed(self):
        rows = [["SBER", "Сбербанк", 49275.0, 250.0, 300.0, "--",
                 0.06, 0.05, 0.11, 0.10, 0.12, "X", "Y", "Z", "W"]]
        rec = parse_ie_actual(_raw(rows), [])["per_ticker"]["SBER"]
        self.assertNotIn("user_action", rec)
        self.assertNotIn("user_note_t", rec)

    def test_empty_trailing_columns_are_none(self):
        # None и пустая строка в текстовых колонках → None
        rows = [["GMKN", "ГМК", 1000.0, 1.0, 1.0, "--",
                 0.03, 0.03, 0.03, "--", 0.03, None, "", None, ""]]
        rec = parse_ie_actual(_raw(rows), [])["per_ticker"]["GMKN"]
        self.assertIsNone(rec["user_plan"])
        self.assertIsNone(rec["user_status"])
        self.assertIsNone(rec["user_note_ie"])
        self.assertIsNone(rec["user_note_ai"])

    def test_filtered_row_skipped(self):
        # Стоимость=0 И IE New пусто И IE Old пусто → строка пропускается
        rows = [["AFKS", "Система", 0.0, 0.0, 11.0, "--",
                 "", "", "--", "--", 0.0, None, None, None, None]]
        out = parse_ie_actual(_raw(rows), [])
        self.assertNotIn("AFKS", out["per_ticker"])


class TestStocksActionNotes(unittest.TestCase):
    def _metrics(self, rows):
        data = extract_portfolio(_raw(rows))
        return compute_metrics(data)

    def test_action_notes_keys(self):
        rows = [["DIAS", "Диасофт", 5000.0, 1.0, 1.0, "--",
                 0.02, 0.02, 0.02, 0.02, 0.02,
                 "Продать", "Держать до 4100", "Продать", "Падает прибыль"]]
        m = self._metrics(rows)
        notes = m["stocks_with_action_notes"]
        self.assertEqual(len(notes), 1)
        rec = notes[0]
        self.assertEqual(rec["ticker"], "DIAS")
        self.assertEqual(rec["plan"], "Продать")
        self.assertEqual(rec["status"], "Держать до 4100")
        self.assertEqual(rec["ie_note"], "Продать")
        self.assertEqual(rec["ai_note"], "Падает прибыль")
        # старые ключи отсутствуют
        self.assertNotIn("action", rec)
        self.assertNotIn("t_note", rec)

    def test_action_flag_triggers_on_status_only(self):
        # пометка только в «Статус» — позиция всё равно попадает в notes
        rows = [["LENT", "Лента", 7000.0, 1.0, 1.0, "--",
                 0.01, 0.01, 0.01, 0.01, 0.01, None, "Купил вчера", None, None]]
        m = self._metrics(rows)
        tickers = [n["ticker"] for n in m["stocks_with_action_notes"]]
        self.assertIn("LENT", tickers)

    def test_no_notes_no_entry(self):
        rows = [["MGNT", "Магнит", 3000.0, 1.0, 1.0, "--",
                 0.01, 0.01, 0.01, 0.01, 0.01, None, None, None, None]]
        m = self._metrics(rows)
        self.assertEqual(m["stocks_with_action_notes"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
