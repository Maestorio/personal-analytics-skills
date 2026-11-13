#!/usr/bin/env python3
"""
test_lint_numbers.py — тесты scripts/lint_numbers.py (числа сделок черновика против вывода скриптов).

Покрывает: строка-действие против строки-факта, правило округления на границах, «тыс/млн ₽», количества,
доли, подмену числа, несколько источников, JSON-источник, пустые источники, коды выхода.

Запуск:
    ~/.pyenv/versions/3.12.9/bin/python3 skills/ru-portfolio-advisor/tests/test_lint_numbers.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
SCRIPT = os.path.join(SCRIPTS, "lint_numbers.py")
sys.path.insert(0, SCRIPTS)
import lint_numbers as ln  # noqa: E402

SRC = ("База: NAV без ИИС-3 — 10 000 000 ₽.\n"
       "TGLD: сейчас 259 000 ₽ = 2,59 % базы; цель 4 % = 400 000 ₽.\n"
       "  Докупить на 141 000 ₽ ≈ 10 998 шт по 12,82 ₽. Продать на 61 482 ₽ ≈ 24 шт. Бумаг после сделки: 483 шт.\n")


def lint(draft, *srcs):
    return ln.lint(draft, ln.collect_source_numbers(list(srcs) or [SRC]))


class TestActionLines(unittest.TestCase):
    def test_fact_line_not_checked(self):
        self.assertEqual(lint("Цена фонда 99 999 ₽, оборот 12 345 шт, комиссия до 0,66 %."), [])

    def test_action_line_checked(self):
        v = lint("Докупить на 111 111 ₽.")
        self.assertEqual(len(v), 1)
        self.assertIn("сумма 111 111 ₽", v[0][1])

    def test_past_and_plural_are_history(self):
        self.assertEqual(lint("Три августовские докупки (+11 700 паёв, ≈167 тыс ₽ по снапшотам)."), [])
        self.assertEqual(lint("Докупил 555 паёв на 777 777 ₽."), [])

    def test_nedobor_is_not_dobor(self):
        self.assertEqual(lint("недобор по ОФЗ ≈ 948 тыс ₽"), [])

    def test_to_plan_needs_percent(self):
        self.assertEqual(lint("запас до плана 16 тыс ₽"), [])
        self.assertEqual(len(lint("до плана 7 % — 55 555 ₽")), 2)  # доля 7 % и сумма

    def test_if_target_is_action(self):
        self.assertEqual(len(lint("Если всё же 9 % (111 111 ₽)")), 2)

    def test_ticker_to_pct_needs_share_word(self):
        self.assertEqual(lint("GOLD до 0,66 % в год"), [])
        self.assertEqual(len(lint("доля TGLD до 7 %")), 1)
        self.assertEqual(lint("доля NAV до 7 %"), [])  # NAV — не тикер

    def test_price_and_threshold_skipped(self):
        self.assertEqual(lint("Докупить по 9 999 ₽, при цене ≤ 350 ₽, выше 1 180 ₽, под 1 100 ₽"), [])

    def test_table_row(self):
        v = lint("| TGLD | докупить | 141 000 ₽ | 10 998 шт |\n| PLZL | продать | 222 222 ₽ | 24 шт |")
        self.assertEqual([n for n, _ in v], [2])


class TestRounding(unittest.TestCase):
    def test_trailing_zeros_granularity(self):
        self.assertEqual(lint("продать ≈61 500 ₽"), [])        # 61 500: g=100, |Δ|=12 ≤ 50
        self.assertEqual(lint("продать ≈61 500 ₽", "61 549 ₽"), [])   # граница 50 включена
        self.assertEqual(len(lint("продать ≈61 500 ₽", "61 551 ₽")), 1)  # 51 > 50
        self.assertEqual(len(lint("продать ≈61 500 ₽", "61 449 ₽")), 1)

    def test_exact_amount_only_exact(self):
        self.assertEqual(lint("докупить на 141 000 ₽"), [])
        self.assertEqual(len(lint("докупить на 206 377 ₽")), 1)
        self.assertEqual(len(lint("докупить на 206 375 ₽")), 1)

    def test_quantity_rounding(self):
        self.assertEqual(lint("докупить ≈11 000 паёв"), [])
        self.assertEqual(len(lint("докупить ≈16 200 паёв")), 1)
        self.assertEqual(lint("продать ≈24 акции"), [])
        self.assertEqual(len(lint("продать 25 акций")), 1)
        self.assertEqual(lint("докупить 483 пая"), [])

    def test_small_round_integer_is_exact(self):
        self.assertEqual(len(lint("продать 20 акций", "в выводе 24 шт")), 1)  # без ≈ ноль не округляет
        self.assertEqual(lint("продать ≈20 акций", "в выводе 24 шт"), [])    # «≈»: g=10, |Δ|=4 ≤ 5
        self.assertEqual(len(lint("продать ≈20 акций", "в выводе 26 шт")), 1)

    def test_decimal_granularity(self):
        self.assertEqual(lint("докупить на 1,5 млн ₽", "1 480 000 ₽"), [])   # g=100 000, Δ=20 000
        self.assertEqual(len(lint("докупить на 1,5 млн ₽", "1 400 000 ₽")), 1)

    def test_thousands_unit(self):
        self.assertEqual(lint("продать на 61 тыс ₽", "61 482 ₽"), [])         # g=1000
        self.assertEqual(len(lint("продать на 61 тыс ₽", "88 912 ₽")), 1)
        self.assertEqual(lint("продать на 61,5 тыс ₽", "61 482 ₽"), [])        # g=100
        self.assertEqual(len(lint("продать на 61,5 тыс ₽", "61 700 ₽")), 1)

    def test_source_in_thousands(self):
        self.assertEqual(lint("докупить на 167 тыс ₽", "около 167 тыс ₽"), [])

    def test_share_tolerance(self):
        self.assertEqual(lint("довести до 4 %"), [])
        self.assertEqual(lint("довести TGLD до 2,6 %"), [])          # 2,59 ± 0,05
        self.assertEqual(lint("довести до 4,05 %"), [])
        self.assertEqual(len(lint("довести до 4,2 %")), 1)
        self.assertEqual(len(lint("довести до 4,1 %")), 1)

    def test_share_not_target_ignored(self):
        self.assertEqual(lint("докупить; фонд даёт 13,7 % годовых"), [])


class TestSubstitution(unittest.TestCase):
    def test_swapped_number_caught(self):
        good = "Если всё же 4 % — докупить на 141 000 ₽ ≈ 11 000 паёв"
        self.assertEqual(lint(good), [])
        bad = lint(good.replace("141 000", "216 376"))
        self.assertEqual([m for _, m in bad], ["сумма 216 376 ₽ не найдена в выводе скриптов"])


class TestSources(unittest.TestCase):
    def test_multiple_sources(self):
        d = "докупить на 31 000 ₽, продать ≈24 акции"
        self.assertEqual(len(lint(d, SRC)), 1)
        self.assertEqual(lint(d, SRC, "второй вывод: 31 000 ₽"), [])

    def test_json_source(self):
        js = json.dumps({"items": [{"delta_rub": -60234.0, "share": 0.0259, "txt": "≈4 698 шт"}]})
        self.assertEqual(lint("продать на 60 234 ₽ (4 698 шт)", js), [])
        self.assertEqual(lint("продать на 60 234 ₽", json.dumps({"x": True, "y": None})), lint("продать на 60 234 ₽", ""))

    def test_json_fraction_as_percent(self):
        self.assertEqual(lint("довести до 2,59 %", json.dumps({"share": 0.0259})), [])

    def test_empty_sources_everything_in_action_is_violation(self):
        v = lint("докупить на 141 000 ₽ ≈ 11 000 шт, до 4 %", "")
        self.assertEqual(len(v), 3)

    def test_broken_json_falls_back_to_text(self):
        self.assertEqual(lint("докупить на 141 000 ₽", "{ не json: 141 000 ₽"), [])


class TestCli(unittest.TestCase):
    def _run(self, draft, sources, extra=()):
        with tempfile.TemporaryDirectory() as d:
            dp = os.path.join(d, "d.md")
            with open(dp, "w", encoding="utf-8") as f:
                f.write(draft)
            sp = []
            for i, s in enumerate(sources):
                p = os.path.join(d, f"s{i}.txt")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(s)
                sp.append(p)
            return subprocess.run([sys.executable, SCRIPT, "--draft", dp, "--sources", *sp, *extra],
                                  capture_output=True, text=True)

    def test_clean_exit_0(self):
        p = self._run("докупить на 141 000 ₽", [SRC])
        self.assertEqual((p.returncode, p.stdout.strip()), (0, "Линт чист."))

    def test_violation_exit_1_with_line(self):
        p = self._run("x\nдокупить на 216 376 ₽", [SRC])
        self.assertEqual(p.returncode, 1)
        self.assertIn("строка 2: сумма 216 376 ₽ не найдена в выводе скриптов", p.stdout)

    def test_json_output(self):
        p = self._run("докупить на 216 376 ₽", [SRC], ["--json"])
        self.assertEqual(json.loads(p.stdout)["violations"][0]["line"], 1)

    def test_missing_files_exit_2(self):
        p = subprocess.run([sys.executable, SCRIPT, "--draft", "/no/d.md", "--sources", "/no/s.txt"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)
        self.assertNotIn("Traceback", p.stderr)
        with tempfile.TemporaryDirectory() as d:
            dp = os.path.join(d, "d.md")
            with open(dp, "w") as f:
                f.write("x")
            p = subprocess.run([sys.executable, SCRIPT, "--draft", dp, "--sources", "/no/s.txt"],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 2)
            self.assertNotIn("Traceback", p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
