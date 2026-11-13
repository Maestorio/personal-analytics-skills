#!/usr/bin/env python3
"""Тесты render_weekly_md.py (RPA-33): детерминированная сборка MD недельного обзора из YAML.

Запуск: python3 skills/ru-portfolio-advisor/tests/test_render_weekly_md.py
"""

import copy
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import render_weekly_md as R  # noqa: E402

SCRIPT = os.path.join(HERE, "..", "scripts", "render_weekly_md.py")

STOCK = {
    "type": "weekly-stocks-review", "review_date": "2026-10-26", "snapshot_id": "portfolio-2026-10-23.json",
    "horizons": [6, 12, 24], "primary_horizon": 12, "producer": "claude-sonnet-5-5 (Mode 1)",
    "sources": {
        "snapshot": "Portfolio/snapshots/portfolio-2026-10-23.json",
        "prior_review": "Portfolio/weekly-reviews/weekly-review-stock-2026-10-16.yaml",
        "macro": [{"url": "https://iss.moex.com/a", "label": "MOEX ISS: IMOEX", "accessed_date": "2026-10-26"}],
    },
    "portfolio_summary": {"stocks_share_actual_pct": 33.7, "stocks_share_target_pct": 40.0,
                          "stocks_undershoot_pct": -6.3, "stocks_undershoot_rub": -911541.39,
                          "returns": {"stocks_xirr": -0.0106, "stocks_pnl_rub": -121761.92}},
    "per_stock": {
        "YDEX": {"sector_ru": "Технологии", "weight_real_pct": 8.97, "weight_user_planned_pct": 10.0,
                 "weight_ie_target_pct": 10.0, "weight_divergence_vs_planned_pp": -1.03, "price_rub": 3391.5,
                 "xirr": -0.0765, "pnl_rub": -56105.35, "div_yield_12m_pct": 6.49,
                 "advisor_verdict": "HOLD", "advisor_verdict_confidence": 0.5,
                 "advisor_verdict_basis": "Держать 8,97% L2 без добора. Гейт review_needed; разбор Mode 4 от 23.10.",
                 "gate_status_snapshot": {"status": "reviewed_under_review"},
                 "fundamental_score_sources": [{"url": "https://x.ru/1", "label": "IR Яндекса", "accessed_date": "2026-10-26"}],
                 "catalyst": [{"id": "y1", "trigger": "Закрепление e-commerce в прибыли. Ещё фраза.", "p": 0.6,
                               "upside_pct": 14.0, "upside_ci_pct": [2.0, 26.0], "date_window": "2026-Q4",
                               "source": "https://x.ru/cat1 — сегменты"}]},
        "MRKP": {"sector_ru": "Электросети", "weight_real_pct": 2.4, "weight_user_planned_pct": 2.0,
                 "xirr": 0.601, "advisor_verdict": "HOLD", "advisor_verdict_confidence": 0.65,
                 "advisor_verdict_basis": "Корпоративных новостей нет; по итогам Mode 4 от 17.09 держим. IE 7→8% не принято.",
                 "gate_status_snapshot": {"status": "reviewed_keep"}, "catalyst": []},
        "BTBR": {"sector_ru": "Финансы", "weight_real_pct": 1.5, "weight_user_planned_pct": 1.5,
                 "advisor_verdict": "HOLD", "advisor_verdict_confidence": 0.65,
                 "advisor_verdict_basis": "IPO-гейт: 2 квартала. Новости не проверены.",
                 "dividend_forward": {"year1_yield_pct": 15.11}, "catalyst": [
                     {"id": "b1", "trigger": "Риск X", "p": 0.4, "downside_pct": 5.0, "source": "https://x.ru/1"}]},
    },
    "conditions_evaluated": {
        "evaluated_at": "2026-10-26",
        "fired": [{"id": "mdmg-trim", "ticker": "MDMG", "trigger": "date 2026-10-19", "resolution": "применён"}],
        "pending_next_7_30d": [{"id": "ydex-q3", "ticker": "YDEX", "trigger": "date 2026-11-30"},
                               {"id": "ofz-bond", "ticker": "RU000A108EH4", "trigger": "date 2026-10-23"}],
    },
    "coverage": {"tickers_total": 3, "checked_this_run": ["YDEX", "MRKP"], "carried_over": ["BTBR"],
                 "not_checked": [], "note": "BTBR — carry-over."},
    "ie_discipline": {"real_share_total_in_ie_pct": 64.71, "threshold_pp": 1.5, "drifts_without_decision": 1,
                      "deviations_ge_threshold": [{"ticker": "MRKP", "real": 2.4, "planned": 2.0, "ie": 8.0,
                                                   "mark": "✓ решение: не принято"}],
                      "outside_ie": ["BTBR"]},
    "key_risks": [{"severity": "HIGH", "ticker": None, "risk": "Ставка 14%; гейт YDEX review_needed."}],
    "caveats": [{"severity": "HIGH", "message": "Оценки advisor, не калиброванная модель."}],
}

BOND = {
    "type": "weekly-bonds-review", "review_date": "2026-10-16", "snapshot_id": "portfolio-2026-10-16.json",
    "producer": "claude-sonnet-5-5 (Mode 2)", "carried_over_from": "weekly-review-bond-2026-10-08.yaml",
    "summary": {"bond_share_pct": 49.22, "target_share_pct": 50.0, "share_delta_pct": -0.78,
                "weighted_ytm_pct": {"value": 13.4747}, "verdict_counts": {"HOLD": 2, "SELL": 1}},
    "per_bond": {
        "RU000A108EG6": {"name": "ОФЗ 26245", "plan_bucket": "ОФЗ/>10", "weight_in_bonds_pct": 2.8, "value_rub": 215805.4,
                         "ytm_pct": 16.69, "duration_days": 1945, "current_price": 81.117, "maturity_date": "2035-09-26",
                         "advisor_verdict": "HOLD", "advisor_verdict_confidence": 0.6, "prior_verdict": "SELL",
                         "advisor_verdict_basis": "Цена 80,78 → 81,12. Своп больше не улучшает доходность.",
                         "carried_over": False,
                         "fundamental_sources": [{"url": "https://x.ru/1", "label": "MOEX", "accessed_date": "2026-10-16"}],
                         "catalyst": [{"id": "c", "trigger": "Навес ОФЗ", "p": 0.6, "downside_pct": -2.5}]},
        "RU000A107795": {"name": "ЛаймЗайм04", "plan_bucket": "КОРП/B+", "weight_in_bonds_pct": 0.3,
                         "advisor_verdict": "HOLD_TO_MAT", "advisor_verdict_confidence": 0.7,
                         "advisor_verdict_basis": "Погашение 30.10.", "carried_over": True},
    },
    "plan_vs_fact": [{"bucket_key": "USD", "target_pct": 12.0, "actual_pct": 27.71, "delta_pp": -15.71,
                      "delta_rub": -1000000.0}],
    "conditions_state": [{"id": "ofz-swap", "state": "pending (23.10)", "note": "Не исполнено."}],
    "key_risks": [{"id": "dev", "severity": "HIGH", "note": "Девелоперы."}],
    "caveats": [{"severity": "HIGH", "message": "Субагенты не запускались."}],
    "sources": {"web": ["https://x.ru/1", "https://y.ru/2"]},
}

STOCK_CH = """<!-- section: summary -->
Итог недели.
<!-- section: actions -->
1. Ничего не делать.
<!-- section: urgent -->
**1. GLRX — продать.**
<!-- item: YDEX | Яндекс -->
**Что произошло:**
- 23.10: IR подтвердил восстановление.

**Рекомендация:** держать.
"""
BOND_CH = """<!-- section: summary -->
Главное.
<!-- section: actions -->
1. Держать.
<!-- section: events -->
Рейтинги без изменений.
<!-- item: RU000A108EG6 -->
Вердикт пересмотрен: SELL → HOLD.
"""


def render(y, ch, kind):
    secs, items = R.parse_changes(ch, kind, set(y["per_stock" if kind == "stock" else "per_bond"]))
    return R.render(y, secs, items, kind)


class TestStock(unittest.TestCase):
    def setUp(self):
        self.md = render(STOCK, STOCK_CH, "stock")

    def test_header_and_save_requirements(self):
        # требования сохранения (workflow-fghijk F1): заголовок, snapshot_id:, таблица позиций
        self.assertRegex(self.md, r"(?m)^# Weekly Review 2026-10-26")
        self.assertRegex(self.md, r"(?m)^snapshot_id:\s+portfolio-2026-10-23\.json$")
        self.assertRegex(self.md, r"(?m)^\| Тикер \|")
        self.assertIn("prior_review: weekly-review-stock-2026-10-16.yaml", self.md)

    def test_all_sections_present(self):
        for h in ("## Executive summary", "## Срочные действия", "## Позиции — акции",
                  "## Позиции с существенными новостями (детали)", "## Позиции без существенных новостей",
                  "## Очередь условий", "## Покрытие проверкой", "## IE-дисциплина", "## Топ катализаторы",
                  "## Ключевые риски", "## Пункты действий", "## Caveats", "## Источники"):
            self.assertIn(h, self.md, h)

    def test_item_fragment_plus_yaml_facts(self):
        self.assertIn("#### YDEX (Яндекс) — ДЕРЖАТЬ", self.md)
        self.assertIn("**Рекомендация:** держать.", self.md)
        self.assertIn("вес 8,97% от акций при плане 10,0% (−1,03 пп); цена 3 391,50 ₽; XIRR −7,6%", self.md)
        self.assertIn("**Катализаторы:**", self.md)
        self.assertIn("ожидаемый эффект +14,0% [2,0; 26,0], p=0,60", self.md)

    def test_gate_in_words_not_codes(self):
        self.assertIn("Гейт: «наблюдать»", self.md)   # R27: подписи статусов = слова решений
        self.assertNotIn("reviewed_under_review", self.md)
        self.assertNotIn("reviewed_keep", self.md)
        self.assertNotIn("review_needed", self.md)                 # и в свободном тексте из YAML
        self.assertEqual(R.ru_modes("в реестре review_needed и `review_needed`"), "в реестре «нужен разбор» и `review_needed`")

    def test_quiet_position_is_compact_row_from_yaml(self):
        sect = self.md.split("## Позиции без существенных новостей")[1].split("\n## ")[0]
        self.assertIn("| MRKP | ДЕРЖАТЬ (средняя) | 2,40% / план 2,0% | Корпоративных новостей нет; по итогам разбор бумаги (Mode 4) от 17.09 держим. | проверено |", sect)
        self.assertIn("carry-over: новости не проверены", sect)  # BTBR
        self.assertNotIn("YDEX", sect)                            # есть фрагмент — в строки не попадает
        self.assertNotIn("IE 7→8% не принято", sect)              # только первая фраза

    def test_div_yield_fallback_and_missing_fields(self):
        row = [ln for ln in self.md.splitlines() if ln.startswith("| BTBR |")][0]
        self.assertIn("15,11%", row)
        self.assertIn("| — |", row)  # нет IE/xirr — прочерк, не выдумано

    def test_conditions_only_scope_tickers(self):
        sect = self.md.split("## Очередь условий")[1].split("\n## ")[0]
        self.assertIn("✅ `mdmg-trim` — MDMG: СРАБОТАЛО", sect)
        self.assertIn("`ydex-q3`", sect)
        self.assertNotIn("ofz-bond", sect)
        self.assertIn("вне этого обзора (облигации и др.): 1", sect)

    def test_mode_words(self):
        self.assertIn("по итогам разбор бумаги (Mode 4) от 17.09", self.md)   # из basis MRKP
        self.assertNotRegex(self.md, r"(?<![(\w])Mode 4\b(?!\))")           # голого «Mode 4» из YAML нет
        self.assertEqual(R.ru_modes("после Mode 4 от 17.09"), "после разбор бумаги (Mode 4) от 17.09")
        self.assertEqual(R.ru_modes("разбор бумаги (Mode 4) уже со словами"), "разбор бумаги (Mode 4) уже со словами")
        self.assertEqual(R.ru_modes("разбор бумаги 17.09, Mode 4"), "разбор бумаги 17.09, Mode 4")

    def test_sources_deduped_by_url(self):
        head, src = self.md.split("## Источники")
        # у YDEX свой раздел — его источник там, в сводном блоке не повторяется
        self.assertIn("https://x.ru/1", head)
        self.assertNotIn("https://x.ru/1", src)
        self.assertIn("MOEX ISS: IMOEX — https://iss.moex.com/a (26.10)", src)
        self.assertIn("Полный список источников с датами проверки — в YAML", src)

    def test_risks_from_yaml_and_override(self):
        self.assertIn("- **HIGH**: Ставка 14%; гейт YDEX «нужен разбор».", self.md)
        md = render(STOCK, STOCK_CH + "<!-- section: risks -->\nМои риски.\n", "stock")
        self.assertIn("Мои риски.", md)
        self.assertNotIn("Ставка 14%", md)

    def test_top_catalysts_split(self):
        sect = self.md.split("## Топ катализаторы")[1].split("\n## ")[0]
        self.assertIn("### Позитивные", sect)
        self.assertIn("1. **YDEX**: Закрепление e-commerce в прибыли.", sect)
        self.assertIn("### Риски", sect)
        self.assertIn("**BTBR**: Риск X — downside −5,0%", sect)

    def test_missing_optional_not_invented(self):
        y = {k: v for k, v in STOCK.items() if k not in ("coverage", "ie_discipline", "conditions_evaluated",
                                                          "caveats", "key_risks", "portfolio_summary")}
        md = render(y, "<!-- section: summary -->\nA\n<!-- section: actions -->\nB\n", "stock")
        for h in ("Покрытие проверкой", "IE-дисциплина", "Очередь условий", "Caveats", "Ключевые риски",
                  "Срочные действия", "Сводка портфеля", "Позиции с существенными новостями"):
            self.assertNotIn(h, md)
        self.assertIn("## Позиции без существенных новостей", md)

    def test_paragraphs_from_yaml_stay_short(self):
        for ln in self.md.splitlines():
            if ln.startswith("- ") or ln.startswith("|"):
                continue
            self.assertLess(len(ln), 400, ln[:60])


class TestBond(unittest.TestCase):
    def setUp(self):
        self.md = render(BOND, BOND_CH, "bond")

    def test_structure(self):
        self.assertRegex(self.md, r"(?m)^# Weekly Review 2026-10-16 — Обзор облигаций за неделю \(Mode 2\)$")
        self.assertRegex(self.md, r"(?m)^snapshot_id:\s+portfolio-2026-10-16\.json$")
        for h in ("## Основной вывод", "## Рейтинговые действия и корпоративные события",
                  "## Цены, YTM и вердикты по корзинам", "## Позиции, требующие внимания",
                  "## Остальные позиции — обоснования", "## План ↔ факт по корзинам", "## Очередь условий",
                  "## Что делать с облигационной частью сейчас", "## Caveats", "## Источники"):
            self.assertIn(h, self.md, h)

    def test_item_and_quiet_row(self):
        self.assertIn("### ОФЗ 26245 (`RU000A108EG6`) — **HOLD** · 215 805 ₽ · 2,80% облигаций", self.md)
        self.assertIn("SELL → HOLD", self.md)
        quiet = self.md.split("## Остальные позиции — обоснования")[1].split("\n## ")[0]
        self.assertIn("| ЛаймЗайм04 | HOLD_TO_MAT (средняя) | 0,30% | Погашение 30.10. | carry-over: новости не проверены |", quiet)
        self.assertNotIn("ОФЗ 26245", quiet)

    def test_table_by_bucket_and_plan_fact(self):
        self.assertIn("### ОФЗ/>10", self.md)
        self.assertIn("| ОФЗ 26245 | `RU000A108EG6` | 81,12 | 16,69 | 1 945 | 2035-09-26 | 2,80% | HOLD |", self.md)
        self.assertIn("| USD | 12,0 | 27,71 | −15,71 | −1 000 000 |", self.md)

    def test_conditions_and_sources(self):
        self.assertIn("⏳ `ofz-swap` — pending (23.10): Не исполнено.", self.md)
        src = self.md.split("## Источники")[1]
        self.assertEqual(src.count("https://x.ru/1"), 1)
        self.assertIn("https://y.ru/2", src)

    def test_summary_block(self):
        self.assertIn("Класс «Облигации»: 49,22% NAV при цели 50,0%; Δ −0,78 пп", self.md)
        self.assertIn("Вердикты: HOLD — 2, SELL — 1", self.md)

    def test_ie_section_name_for_bond(self):
        md = render(BOND, BOND_CH + "<!-- section: ie -->\nСтрим IE.\n", "bond")
        self.assertIn("## Invest Era", md)


class TestRatingChecked(unittest.TestCase):
    def _md(self, **kw):
        y = copy.deepcopy(BOND)
        y["per_bond"]["RU000A108EG6"].update({"bond_type": "corp_rub", "credit_rating": "AA(RU)", **kw})
        y["per_bond"]["RU000A107795"].update({"bond_type": "ofz"})
        return render(y, BOND_CH, "bond")

    def test_checked_date_and_no_summary_when_fresh(self):
        md = self._md(credit_rating_checked_at="2026-10-14")
        self.assertIn("рейтинг AA(RU) (проверен 14.10.2026)", md)
        self.assertNotIn("Рейтинг пора перепроверить", md)

    def test_not_recorded_and_summary_line(self):
        md = self._md()
        self.assertIn("рейтинг AA(RU) (дата проверки не записана)", md)
        self.assertIn("Рейтинг пора перепроверить: ОФЗ 26245 (RU000A108EG6).", md)
        self.assertNotIn("ЛаймЗайм04 (RU000A107795)", md)   # ОФЗ в списке не бывает

    def test_stale_in_summary(self):
        md = self._md(credit_rating_checked_at="2026-09-01")
        self.assertIn("(проверен 01.09.2026)", md)
        self.assertIn("Рейтинг пора перепроверить: ОФЗ 26245", md)


class TestInputErrors(unittest.TestCase):
    def parse(self, text, kind="stock"):
        return R.parse_changes(text, kind, {"YDEX", "RU000A108EG6"})

    def test_unknown_marker_lists_allowed(self):
        with self.assertRaises(R.InputError) as cm:
            self.parse("<!-- section: foo -->\nx")
        self.assertIn("допустимые: summary, actions, urgent", str(cm.exception))

    def test_bond_only_section_in_stock(self):
        with self.assertRaises(R.InputError):
            self.parse("<!-- section: events -->\nx", "stock")

    def test_missing_required(self):
        with self.assertRaises(R.InputError) as cm:
            self.parse("<!-- section: summary -->\nx")
        self.assertIn("actions", str(cm.exception))

    def test_unknown_ticker_and_duplicates(self):
        base = "<!-- section: summary -->\na\n<!-- section: actions -->\nb\n"
        with self.assertRaises(R.InputError):
            self.parse(base + "<!-- item: ZZZZ -->\nx")
        with self.assertRaises(R.InputError):
            self.parse(base + "<!-- item: YDEX -->\nx\n<!-- item: YDEX -->\ny")
        with self.assertRaises(R.InputError):
            self.parse(base + "<!-- section: summary -->\nz")

    def test_text_before_first_marker(self):
        with self.assertRaises(R.InputError):
            self.parse("вступление\n<!-- section: summary -->\na")


class TestTextCheck(unittest.TestCase):
    """Проверка текста модели: голый «Mode N» и коды гейтов вне обратных кавычек — предупреждения."""

    def warns(self, body, kind="stock"):
        ch = f"<!-- section: summary -->\n{body}\n<!-- section: actions -->\nок\n"
        secs, items = R.parse_changes(ch, kind, set())
        return R.check_text(secs, items)

    def test_bare_mode_and_gate_found_with_place_and_quote(self):
        w = self.warns("После Mode 4 от 17.09 гейт review_needed снят.")
        self.assertEqual(len(w), 2, w)
        self.assertTrue(all(x.startswith("раздел «summary»") for x in w))
        self.assertIn("голый «Mode 4»", w[0])
        self.assertIn("После Mode 4 от 17.09", w[0])
        self.assertIn("review_needed", w[1])

    def test_words_and_code_spans_are_legal(self):
        self.assertEqual(self.warns("разбор бумаги (Mode 4) и `Mode 4`, статус `review_needed`; «Нужен разбор»"), [])
        self.assertEqual(self.warns("```\nMode 4 review_needed\n```"), [])
        self.assertEqual(self.warns("разбор бумаги 17.09, Mode 4"), [])   # слова рядом — как в ru_modes

    def test_item_fragment_names_ticker(self):
        secs, items = R.parse_changes(STOCK_CH + "<!-- item: MRKP -->\nПо Mode 8 всё ок: reviewed_keep.\n",
                                      "stock", set(STOCK["per_stock"]))
        w = R.check_text(secs, items)
        self.assertEqual(len(w), 2)
        self.assertTrue(all(x.startswith("бумага MRKP") for x in w))

    def test_clean_changes_no_warnings(self):
        secs, items = R.parse_changes(STOCK_CH, "stock", set(STOCK["per_stock"]))
        self.assertEqual(R.check_text(secs, items), [])


class TestAdditiveFields(unittest.TestCase):
    """Name в YAML, checked_dates, --prior: новые поля аддитивны — без них вывод прежний."""

    def test_name_from_yaml_and_marker_priority(self):
        y = yaml.safe_load(yaml.safe_dump(STOCK))
        y["per_stock"]["YDEX"]["name"] = "Yandex"
        md = render(y, STOCK_CH, "stock")
        self.assertIn("#### YDEX (Яндекс) — ДЕРЖАТЬ", md)           # маркер приоритетнее
        ch = STOCK_CH.replace("<!-- item: YDEX | Яндекс -->", "<!-- item: YDEX -->")
        self.assertIn("#### YDEX (Yandex) — ДЕРЖАТЬ", render(y, ch, "stock"))   # нет маркера — из YAML
        self.assertIn("#### YDEX — ДЕРЖАТЬ", render(STOCK, ch, "stock"))        # нет нигде — как раньше

    def test_checked_dates_in_coverage_and_quiet_table(self):
        y = yaml.safe_load(yaml.safe_dump(STOCK))
        y["coverage"]["checked_dates"] = {"YDEX": "2026-10-26", "MRKP": "2026-10-26"}
        md = render(y, STOCK_CH, "stock")
        cov = md.split("## Покрытие проверкой")[1].split("\n## ")[0]
        self.assertIn("; дата проверки 26.10", cov)
        self.assertRegex(md, r"\| проверено 26\.10 \|")                      # MRKP в таблице «без новостей»
        y["coverage"]["checked_dates"]["MRKP"] = "2026-10-23"
        cov = render(y, STOCK_CH, "stock").split("## Покрытие проверкой")[1].split("\n## ")[0]
        self.assertIn("Даты проверки: YDEX (26.10), MRKP (23.10)", cov)
        base = render(STOCK, STOCK_CH, "stock")
        self.assertNotIn("дата проверки", base)
        self.assertIn("| проверено |", base)

    def test_no_prior_output_unchanged(self):
        self.assertEqual(R.render(STOCK, *R.parse_changes(STOCK_CH, "stock", set(STOCK["per_stock"])), "stock"),
                         R.render(STOCK, *R.parse_changes(STOCK_CH, "stock", set(STOCK["per_stock"])), "stock", None))
        self.assertNotIn("→", render(STOCK, STOCK_CH, "stock").split("## Позиции — акции")[1].split("\n## ")[0])
        bond = render(BOND, BOND_CH, "bond").split("## Цены, YTM")[1].split("\n## ")[0]
        self.assertIn("| 81,12 | 16,69 |", bond)
        self.assertNotIn("→", bond)

    def test_prior_stock_price_arrow(self):
        prior = {"type": "weekly-stocks-review", "per_stock": {"YDEX": {"price_rub": 3300.0}}}
        secs, items = R.parse_changes(STOCK_CH, "stock", set(STOCK["per_stock"]))
        md = R.render(STOCK, secs, items, "stock", prior)
        tbl = md.split("## Позиции — акции")[1].split("\n## ")[0]
        self.assertIn("Цена, ₽ (было → стало)", tbl)
        ydex = [ln for ln in tbl.splitlines() if ln.startswith("| YDEX |")][0]
        self.assertIn("3 300,00 → 3 391,50", ydex)
        mrkp = [ln for ln in tbl.splitlines() if ln.startswith("| MRKP |")][0]
        self.assertNotIn("→", mrkp.split("|")[2])                  # нет в прошлом (и цены нет) — только текущее/прочерк

    def test_prior_bond_price_ytm_by_isin(self):
        prior = {"type": "weekly-bonds-review", "per_bond": {
            "RU000A108EG6": {"current_price": 80.78, "ytm_pct": 16.9}}}
        secs, items = R.parse_changes(BOND_CH, "bond", set(BOND["per_bond"]))
        md = R.render(BOND, secs, items, "bond", prior)
        row = [ln for ln in md.splitlines() if "`RU000A108EG6`" in ln and ln.startswith("| ОФЗ")][0]
        self.assertIn("80,78 → 81,12", row)
        self.assertIn("16,90 → 16,69", row)
        new = [ln for ln in md.splitlines() if "`RU000A107795`" in ln and ln.startswith("| Лайм")][0]
        self.assertNotIn("→", new)                                 # бумаги нет в прошлом
        self.assertIn("Цена (было → стало)", md)


class TestWeekNote(unittest.TestCase):
    """Контракт A (план переосмысления вьюера, 2026-10-26): фрагмент бумаги → week_note в YAML."""

    def test_parse_labels(self):
        frag = ("**Что произошло:**\n- 23.10: IR подтвердил восстановление.\n- Запущен новый сайт;\n"
                "  T-Инвестиции сняли рекомендацию.\n\n**Рекомендация:** держать 9% без добора.\n\n"
                "### Макро\nПрямой фактор — удары по ЦОД; ставка вторична.\n")
        n = R.parse_week_note(frag)
        self.assertEqual(n["what_happened"], ["23.10: IR подтвердил восстановление.",
                                              "Запущен новый сайт; T-Инвестиции сняли рекомендацию."])
        self.assertEqual(n["recommendation"], ["держать 9% без добора."])
        self.assertEqual(n["macro_link"], "Прямой фактор — удары по ЦОД; ставка вторична.")

    def test_unlabelled_text_goes_to_what_happened(self):
        n = R.parse_week_note("Вердикт пересмотрен: SELL → HOLD.\n\n- Цена 15→23.10: −0,79%.")
        self.assertEqual(n["what_happened"], ["Вердикт пересмотрен: SELL → HOLD.", "Цена 15→23.10: −0,79%."])
        self.assertEqual(n["recommendation"], [])
        self.assertIsNone(n["macro_link"])
        self.assertIsNone(R.parse_week_note("  \n"))

    def test_embed_sets_and_removes(self):
        y = copy.deepcopy(STOCK)
        y["per_stock"]["MRKP"]["week_note"] = {"what_happened": ["прошлая неделя"]}   # не должен остаться
        secs, items = R.parse_changes(STOCK_CH, "stock", set(y["per_stock"]))
        self.assertEqual(R.embed_week_notes(y, items, "stock"), 1)
        self.assertEqual(y["per_stock"]["YDEX"]["week_note"]["what_happened"], ["23.10: IR подтвердил восстановление."])
        self.assertEqual(y["per_stock"]["YDEX"]["week_note"]["recommendation"], ["держать."])
        self.assertNotIn("week_note", y["per_stock"]["MRKP"])

    def test_cli_embed_notes_rewrites_yaml(self):
        with tempfile.TemporaryDirectory() as d:
            yp, cp, op = Path(d, "r.yaml"), Path(d, "changes.md"), Path(d, "r.md")
            yp.write_text(yaml.safe_dump(STOCK, allow_unicode=True, sort_keys=False), encoding="utf-8")
            cp.write_text(STOCK_CH, encoding="utf-8")
            r = subprocess.run([sys.executable, SCRIPT, "--yaml", str(yp), "--changes", str(cp), "--output", str(op),
                                "--embed-notes"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("week_note записан в YAML у 1 бумаг", r.stdout)
            y2 = yaml.safe_load(yp.read_text(encoding="utf-8"))
            self.assertEqual(y2["per_stock"]["YDEX"]["week_note"]["recommendation"], ["держать."])
            self.assertEqual(list(y2), list(STOCK))                     # порядок ключей сохранён
            self.assertNotIn("&id0", yp.read_text(encoding="utf-8"))   # без якорей
            # без флага YAML не трогается
            yp.write_text(yaml.safe_dump(STOCK, allow_unicode=True, sort_keys=False), encoding="utf-8")
            subprocess.run([sys.executable, SCRIPT, "--yaml", str(yp), "--changes", str(cp), "--output", str(op)],
                           capture_output=True, text=True)
            self.assertNotIn("week_note", yp.read_text(encoding="utf-8"))


class TestCli(unittest.TestCase):
    def run_cli(self, y, ch, *extra):
        d = tempfile.mkdtemp()
        Path(d, "r.yaml").write_text(yaml.safe_dump(y, allow_unicode=True), encoding="utf-8")
        Path(d, "c.md").write_text(ch, encoding="utf-8")
        p = subprocess.run([sys.executable, SCRIPT, "--yaml", f"{d}/r.yaml", "--changes", f"{d}/c.md",
                            "--output", f"{d}/o.md", *extra], capture_output=True, text=True)
        out = Path(d, "o.md")
        return p, (out.read_text(encoding="utf-8") if out.exists() else None)

    def test_ok_kind_by_type(self):
        p, md = self.run_cli(STOCK, STOCK_CH)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("пишет модель", p.stdout)
        self.assertTrue(md.startswith("# Weekly Review 2026-10-26"))
        p, md = self.run_cli(BOND, BOND_CH)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("Обзор облигаций", md)

    def test_bad_marker_exit_2_no_output(self):
        p, md = self.run_cli(STOCK, "<!-- section: nope -->\nx")
        self.assertEqual(p.returncode, 2)
        self.assertIn("допустимые", p.stderr)
        self.assertIsNone(md)

    def test_missing_file_exit_2(self):
        p = subprocess.run([sys.executable, SCRIPT, "--yaml", "/nonexistent.yaml", "--changes", "/x.md",
                            "--output", "/tmp/never.md"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)

    def test_unknown_type_needs_kind(self):
        y = dict(STOCK, type="something")
        p, _ = self.run_cli(y, STOCK_CH)
        self.assertEqual(p.returncode, 2)
        p, md = self.run_cli(y, STOCK_CH, "--kind", "stock")
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_text_warnings_exit_0_and_strict_3(self):
        ch = STOCK_CH.replace("Итог недели.", "Итог недели по Mode 4: review_needed.")
        p, md = self.run_cli(STOCK, ch)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("предупреждение: раздел «summary»", p.stderr)
        self.assertIn("предупреждений по тексту модели: 2", p.stderr)
        p, md = self.run_cli(STOCK, ch, "--strict-text")
        self.assertEqual(p.returncode, 3)
        self.assertIsNotNone(md)                                   # файл записан, код 3 — только сигнал
        p, _ = self.run_cli(STOCK, STOCK_CH, "--strict-text")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stderr, "")

    def test_prior_cli_and_kind_mismatch(self):
        d = tempfile.mkdtemp()
        Path(d, "p.yaml").write_text(yaml.safe_dump(
            {"type": "weekly-stocks-review", "per_stock": {"YDEX": {"price_rub": 3300.0}}}, allow_unicode=True),
            encoding="utf-8")
        p, md = self.run_cli(STOCK, STOCK_CH, "--prior", f"{d}/p.yaml")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("3 300,00 → 3 391,50", md)
        p, md = self.run_cli(BOND, BOND_CH, "--prior", f"{d}/p.yaml")
        self.assertEqual(p.returncode, 2)
        self.assertIn("--prior", p.stderr)
        p, _ = self.run_cli(STOCK, STOCK_CH, "--prior", f"{d}/нет.yaml")
        self.assertEqual(p.returncode, 2)



class TestStaleConditions(unittest.TestCase):
    """Сухой прогон 26.10: перенос предупреждал, а отчёт молча показал очередь условий от 16.10."""

    def test_stale_block_flagged_in_md_and_function(self):
        y = copy.deepcopy(STOCK)
        y["conditions_evaluated"] = dict(y.get("conditions_evaluated") or {}, evaluated_at="2026-10-16")
        self.assertTrue(R.stale_conditions(y))
        self.assertIn("не этой недели", render(y, STOCK_CH, "stock"))
        y["conditions_evaluated"]["evaluated_at"] = y["review_date"]
        self.assertFalse(R.stale_conditions(y))


class TestConditionsFromDigest(unittest.TestCase):
    """Очередь условий — из выдачи apply_condition.py digest (модуль (а)); обзор условий не вычисляет."""

    DIG = {"ok": True, "command": "digest", "today": "2026-10-26", "items": [
        {"id": "mrkp-trim", "key": "MRKP", "active": True, "status": "fired", "trigger": {"type": "date", "value": "2026-10-19"},
         "text": "срезать до плана"},
        {"id": "c-2026-10-20-ydex-1", "key": "YDEX", "active": True, "status": "pending",
         "trigger": {"type": "report_published", "value": "МСФО 3К", "window_end": "2026-11-03"}, "text": "разбор после МСФО"},
        {"id": "ofz-bond", "key": "RU000A108EH4", "active": True, "status": "pending", "trigger": {"type": "date", "value": "2026-11-23"}},
        {"id": "old", "key": "YDEX", "active": False, "status": "done", "trigger": {"type": "date", "value": "2026-10-01"}},
    ]}

    def md(self, y, conds):
        secs, items = R.parse_changes(STOCK_CH, "stock", set(y["per_stock"]))
        return R.render(y, secs, items, "stock", None, conds)

    def test_rows_from_digest(self):
        y = copy.deepcopy(STOCK)
        y["conditions_evaluated"]["fired"] = [{"id": "mrkp-trim", "resolution": "применён"}]
        sect = self.md(y, self.DIG).split("## Очередь условий")[1].split("\n## ")[0]
        self.assertIn("(на 2026-10-26)", sect)
        self.assertIn("✅ `mrkp-trim` — MRKP: СРАБОТАЛО (date 2026-10-19) → **резолюция: применён**", sect)
        self.assertIn("⏳ `c-2026-10-20-ydex-1` — YDEX: ждёт (report_published МСФО 3К, окно до 2026-11-03)", sect)
        self.assertIn("Условий по бумагам вне этого обзора: 1.", sect)
        self.assertNotIn("`old`", sect)
        self.assertNotIn("evaluate", sect)

    def test_fired_without_resolution_and_stale(self):
        y = copy.deepcopy(STOCK)
        y.pop("conditions_evaluated")
        dig = dict(self.DIG, today="2026-10-16")
        out = self.md(y, dig)
        self.assertIn("СРАБОТАЛО (date 2026-10-19) — ждёт резолюции", out)
        self.assertIn("не этой недели", out)
        self.assertTrue(R.stale_conditions(y, dig))
        self.assertFalse(R.stale_conditions(y, self.DIG))

    def test_resolution_from_changes_fragment(self):
        # 03.11: обзор не несёт conditions_evaluated — резолюция сработавшего из <!-- cond: id --> changes.md
        y = copy.deepcopy(STOCK)
        y.pop("conditions_evaluated")
        secs, items = R.parse_changes(STOCK_CH + "<!-- cond: mrkp-trim -->\nуже исполнено — срез 28.10\n",
                                      "stock", set(y["per_stock"]))
        sect = R.render(y, secs, items, "stock", None, self.DIG).split("## Очередь условий")[1].split("\n## ")[0]
        self.assertIn("✅ `mrkp-trim` — MRKP: СРАБОТАЛО (date 2026-10-19) → **резолюция: уже исполнено — срез 28.10**", sect)
        with self.assertRaises(R.InputError):
            R.parse_changes(STOCK_CH + "<!-- cond: a -->\nх\n<!-- cond: a -->\nу\n", "stock", set(y["per_stock"]))


if __name__ == "__main__":
    unittest.main(verbosity=1)
