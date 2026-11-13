#!/usr/bin/env python3
"""Тесты prior_digest.py (RPA-24): выжимка прошлого обзора вместо чтения MD целиком.

Условия — conditions@2 через модуль (а) (`load_conditions`), гейт акций — из последнего решения
`Portfolio/decisions/` (`load_gates`, decisions_read — временно до модуля (б)); файл гейтов не читается.

Запуск: python3 skills/ru-portfolio-advisor/tests/test_prior_digest.py
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from prior_digest import (digest, _first_sentence, load_reports, aging_gates, load_macro,  # noqa: E402
                          load_conditions, load_gates)


def _cond(cid, key, ttype, value, verdict_now="HOLD", verdict_on=None, kind="trade", action="notify_only",
          created_by="mode_1", created_at="2026-10-01T10:00:00+03:00", note=None):
    d = {"id": cid, "version": 1, "key": key, "kind": kind, "trigger": {"type": ttype, "value": value},
         "while_pending": {"verdict": verdict_now}, "on_trigger": {"action": action, "verdict": verdict_on, "text": "x"},
         "source": {"kind": "owner", "doc": None}, "created_at": created_at, "created_by": created_by,
         "withdrawn": None, "superseded_by": None}
    if note:
        d["note"] = note
    return d


def write_conditions(root, defs, events=()):
    port = Path(root) / "Portfolio"
    port.mkdir(parents=True, exist_ok=True)
    (port / "conditions.yaml").write_text(yaml.safe_dump({"schema_version": "conditions@2", "conditions": defs},
                                                         allow_unicode=True, sort_keys=False), encoding="utf-8")
    (port / "conditions-state.json").write_text(json.dumps({"schema_version": "conditions-state@1",
                                                            "events": list(events)}), encoding="utf-8")
    return str(port / "conditions.yaml")


def write_decision(root, key, verdict, recorded_at, review_by=None, doc=None):
    ddir = Path(root) / "Portfolio" / "decisions"
    ddir.mkdir(parents=True, exist_ok=True)
    did = f"{recorded_at[:10]}T{recorded_at[11:13]}{recorded_at[14:16]}-{key}"
    d = {"schema_version": "decision@1", "id": did, "key": key, "verdict": verdict, "target_pct": None,
         "review_by": review_by, "note": "x", "conditions_created": [], "conditions_resolved": [],
         "source": {"kind": "report" if doc else "owner", "doc": doc, "mode_codes": ["4a"] if doc else [],
                    "stress_id": None},
         "author": "model" if doc else "owner", "recorded_at": recorded_at}
    (ddir / f"{did}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return str(ddir)


PRIOR = {"review_date": "2026-10-08", "per_bond": {
    "RU000A108EG6": {"name": "ОФЗ 26245", "advisor_verdict": "SELL", "advisor_verdict_confidence": 0.62,
                     "advisor_verdict_basis": "Цена 80,96 → 80,78, YTM 16,72 → 16,78%. SELL — источник свопа в 26247/26248.",
                     "catalyst": [{"id": "swap", "trigger": "Своп до 23.10", "date_window": "2026-10-08 to 2026-10-23"}]},
    "RU000A107795": {"name": "ЛаймЗайм04", "advisor_verdict": "HOLD_TO_MAT", "advisor_verdict_confidence": 0.7,
                     "credit_rating": "ruBB+", "credit_rating_agency": "Эксперт РА",
                     "advisor_verdict_basis": "Погашение 30.10.",
                     "catalyst": [{"id": "old", "trigger": "Купон 02.10", "event_date": "2026-10-02"},
                                  {"id": "far", "trigger": "Далеко", "date_window": "2027-06"}]},
}, "key_risks": [{"risk": "Кредитный стресс у девелоперов. Подробности ниже."}]}
CONDS_DEFS = [
    _cond("ofz-long", "RU000A108EH4", "date", "2026-10-23", verdict_now="BUY", verdict_on="BUY"),
    _cond("fired-one", "RU000A107795", "date", "2026-10-01"),
]
CONDS_EVENTS = [{"condition_id": "fired-one", "event": "done", "at": "2026-10-02T10:00:00+03:00", "by": "owner",
                 "data": {}}]


def conds_rows(defs, events=(), today=date(2026, 10, 16)):
    with tempfile.TemporaryDirectory() as d:
        return load_conditions(write_conditions(d, defs, events), today)


class TestPriorDigest(unittest.TestCase):
    def setUp(self):
        self.out = digest(PRIOR, conds_rows(CONDS_DEFS, CONDS_EVENTS), date(2026, 10, 16), 14, 160)

    def test_counts_and_rows(self):
        self.assertIn("Вердикты: SELL 1, HOLD_TO_MAT 1", self.out)
        self.assertIn("| RU000A108EG6 ОФЗ 26245 | SELL | 0.62 | — | SELL — источник свопа в 26247/26248. |", self.out)
        self.assertIn("ruBB+ (Эксперт РА)", self.out)

    def test_price_lead_skipped(self):
        self.assertNotIn("Цена 80,96", self.out)
        self.assertEqual(_first_sentence("Цена 1 → 2. Причина.", 50, skip_price=True), "Причина.")
        self.assertEqual(_first_sentence("Цена 1 → 2.", 50, skip_price=True), "Цена 1 → 2.")  # больше нечего

    def test_catalyst_windows(self):
        self.assertIn("`swap` — Своп до 23.10 (до 2026-10-23)", self.out)
        self.assertIn("`old` — Купон 02.10 (ПРОШЛО — закрыть или обновить)", self.out)
        self.assertNotIn("`far`", self.out)

    def test_conditions_active_only(self):
        self.assertIn("`ofz-long`", self.out)
        self.assertIn("(бумаги нет в прошлом обзоре)", self.out)
        self.assertNotIn("fired-one", self.out)          # закрыто («сделал») — не действующее

    def test_owner_watch_condition_on_nonheld_stock_kept(self):
        """Условие владельца на акцию, которой нет в прошлом обзоре и в портфеле: выжимка его не теряет (с пометкой),
        verdict_now null — «—», не «None»."""
        defs = [dict(_cond("c-zzzz-w", "ZZZZ", "price_below", 250, verdict_now=None, kind="watch"),
                     while_pending={"verdict": None, "text": ""}, created_by="owner",
                     created_at="2026-11-11T10:00:00+03:00")]
        stock = {"review_date": "2026-10-08", "per_stock": {"AAAA": {"advisor_verdict": "HOLD", "advisor_verdict_confidence": 0.6,
                                                                    "advisor_verdict_basis": "Держим."}}}
        out = digest(stock, conds_rows(defs, today=date(2026, 11, 12)), date(2026, 11, 12), 14, 160)
        self.assertIn("- ZZZZ (бумаги нет в прошлом обзоре): `c-zzzz-w` — price_below 250; ждёт; сейчас —, при срабатывании —", out)
        self.assertIn("решение владельца 2026-11-11", out)
        self.assertNotIn("None", out)

    def test_fired_condition_marked(self):
        rows = conds_rows([_cond("px", "RU000A108EG6", "price_below", 80)],
                          [{"condition_id": "px", "event": "fired", "at": "2026-10-10T11:00:00+03:00", "by": "notifier",
                            "data": {}}])
        out = digest(PRIOR, rows, date(2026, 10, 16), 14, 160)
        self.assertIn("`px` — price_below 80; СРАБОТАЛО — ждёт владельца, нужна резолюция", out)

    def test_conditions_v1_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "conditions.yaml"
            path.write_text("schema_version: conditions@1.2\nconditions: []\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_conditions(str(path), date(2026, 10, 16))

    def test_truncation(self):
        self.assertTrue(_first_sentence("а" * 300, 20).endswith("…"))
        self.assertEqual(len(_first_sentence("а" * 300, 20)), 20)

    def test_key_risks(self):
        self.assertIn("- Кредитный стресс у девелоперов.", self.out)


STOCK_PRIOR = {"review_date": "2026-10-16", "per_stock": {
    "YDEX": {"advisor_verdict": "HOLD", "advisor_verdict_confidence": 0.55, "advisor_verdict_basis": "Держать."},
    "MDMG": {"advisor_verdict": "HOLD", "advisor_verdict_confidence": 0.6, "advisor_verdict_basis": "Держать."},
    "SBER": {"advisor_verdict": "HOLD", "advisor_verdict_confidence": 0.75, "advisor_verdict_basis": "Держать."},
}}
REPORT = """---
title: "Разбор бумаг"
kind: "single_analysis"
summary: "YDEX — держать без добора до раскрытия ущерба. MDMG — срезать."
tickers: ["YDEX", "MDMG", "SBER"]
---

# Разбор
"""
REPORT_DOC = "Portfolio/reports/2026-10-23-single-analysis-ydex-mdmg-sber.md"


class TestReportsAndGates(unittest.TestCase):
    """Разборы после прошлого обзора и гейты из последнего решения (файл гейтов упразднён)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        rdir = root / "Portfolio" / "reports"
        rdir.mkdir(parents=True)
        (rdir / "2026-10-23-single-analysis-ydex-mdmg-sber.md").write_text(REPORT, encoding="utf-8")
        (rdir / "2026-10-10-single-analysis-old.md").write_text(REPORT, encoding="utf-8")  # до прошлого обзора
        (rdir / "2026-10-20-general-notes.md").write_text("---\nkind: general\n---\nтекст", encoding="utf-8")
        write_decision(root, "YDEX", "WATCH", "2026-10-23T18:00:00+03:00", "2026-12-01", REPORT_DOC)
        write_decision(root, "MDMG", "TRIM", "2026-10-23T18:00:00+03:00", "2026-12-01", REPORT_DOC)
        ddir = write_decision(root, "SBER", "HOLD", "2026-10-25T09:00:00+03:00", "2026-12-20")
        self.gates, decisions = load_gates(ddir, date(2026, 10, 26))
        self.reports = load_reports(str(rdir), date(2026, 10, 16), decisions)
        self.out = digest(STOCK_PRIOR, None, date(2026, 10, 26), 14, 160, self.gates, self.reports)

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_reviews_after_prior(self):
        self.assertEqual([r["file"] for r in self.reports], ["2026-10-23-single-analysis-ydex-mdmg-sber.md"])
        self.assertIn("## Разборы бумаг после прошлого обзора (2026-10-16)", self.out)
        self.assertIn("YDEX — держать без добора до раскрытия ущерба.", self.out)

    def test_decisions_from_report_listed(self):
        self.assertIn("Решения записаны: MDMG — Сократить; YDEX — Наблюдать.", self.out)

    def test_gate_column_from_decisions_in_words(self):
        self.assertIn("| YDEX | HOLD | 0.55 | наблюдать | Держать. |", self.out)
        self.assertIn("| MDMG | HOLD | 0.6 | сократить | Держать. |", self.out)
        self.assertIn("| SBER | HOLD | 0.75 | держать | Держать. |", self.out)
        self.assertNotIn("reviewed_", self.out)
        self.assertNotIn("реестр", self.out)

    def test_no_decision_column(self):
        out = digest({"review_date": "2026-10-16", "per_stock": {"NEWT": {"advisor_verdict": "HOLD"}}}, None,
                     date(2026, 10, 26), 14, 160, self.gates, [])
        self.assertIn("| NEWT | HOLD | — | нет решения |", out)

    def test_aging_gate_points_to_latest_report(self):
        """CNRU 26.10: срок решения истёк 19.10, решение «держать до 30.11» было в отчёте 16.10."""
        gates = {"CNRU": {"status": "review_aging", "expires_on": "2026-10-19", "expired": True},
                 "SBER": {"status": "reviewed_keep", "expires_on": "2026-11-18", "expired": False}}
        reps = [{"file": "a.md", "date": date(2026, 10, 2), "kind": "single_analysis", "tickers": ["CNRU"]},
                {"file": "b.md", "date": date(2026, 10, 16), "kind": "tactical_rebalance", "tickers": ["CNRU"]}]
        out = aging_gates(gates, reps, date(2026, 10, 26), {"CNRU", "SBER"})
        self.assertEqual([(a["ticker"], (a["report"] or {}).get("file")) for a in out], [("CNRU", "b.md")])
        text = digest({"review_date": "2026-10-16", "per_stock": {"CNRU": {}, "SBER": {}}}, None,
                      date(2026, 10, 26), 14, 160, gates, reps)
        self.assertIn("## Срок решения вышел — нужен разбор", text)
        self.assertIn("**CNRU**: «срок решения вышел», срок истёк 19.10; последний отчёт с бумагой — 16.10", text)
        self.assertNotIn("decision_write.py owner", text)   # правило 9а: переподтверждение без разбора не предлагается
        self.assertIn("Разбери X", text)
        self.assertNotIn("**SBER**", text)
        self.assertNotIn("`a.md`", text.split("## Срок решения вышел")[0])

    def test_expired_decision_gives_aging(self):
        ddir = write_decision(self.tmp.name, "PLZL", "HOLD", "2026-08-01T10:00:00+03:00")   # 60 дней → 30.09
        gates, _ = load_gates(ddir, date(2026, 10, 26))
        self.assertEqual((gates["PLZL"]["status"], gates["PLZL"]["expires_on"]), ("review_aging", "2026-09-30"))

    def test_owner_decision_note_and_class_filter(self):
        """26.10: обзор переспросил срез OZON, хотя 16.10 владелец решил «держим» (ozon-below-1610)."""
        conds = conds_rows([
            _cond("ozon-below-1610", "OZON", "price_below", 3250, created_by="owner",
                  created_at="2026-10-16T12:00:00+03:00",
                  note="Решение владельца 16.10: держим, срез не делаем. Подробности."),
            _cond("bond-one", "RU000A107795", "date", "2026-10-30")], today=date(2026, 10, 26))
        out = digest({"review_date": "2026-10-16", "per_stock": {"OZON": {}}}, conds, date(2026, 10, 26), 14, 160)
        self.assertIn("при срабатывании — · решение владельца 2026-10-16 — Решение владельца 16.10: держим, срез не делаем.", out)
        self.assertNotIn("bond-one", out)  # облигационное условие — не в выжимке акций
        bout = digest(PRIOR, conds, date(2026, 10, 16), 14, 160)
        self.assertIn("bond-one", bout)
        self.assertNotIn("ozon-below-1610", bout)

    def test_macro_snapshot_block(self):
        """26.10: «валюта, нефть не собирались» при макроснимке от 21.10."""
        with tempfile.TemporaryDirectory() as d:
            for name, val in (("ru-2026-10-16.md", "7.22%"), ("ru-2026-10-21.md", "7.15% (на 19.10)")):
                Path(d, name).write_text("# Макропанель\n\n| Индикатор | Текущее | Прошлый |\n|---|---|---|\n"
                                         f"| Инфляция (г/г) | {val} | x |\n| USD/RUB | 81.9 | 84 |\n\n## Аномалии\n", encoding="utf-8")
            m = load_macro(d)
            self.assertEqual(m["file"], "ru-2026-10-21.md")
            out = digest(STOCK_PRIOR, None, date(2026, 10, 26), 14, 160, macro=m)
            self.assertIn("## Макроснимок 21.10 (`ru-2026-10-21.md`, 5 дн.)", out)
            self.assertIn("- Инфляция (г/г): 7.15% (на 19.10)", out)
            self.assertNotIn("Старше", out)
            self.assertIn("Старше 7 дней", digest(STOCK_PRIOR, None, date(2026, 11, 2), 14, 160, macro=m))
            with tempfile.TemporaryDirectory() as empty:
                self.assertIn("Снимков нет", digest(STOCK_PRIOR, None, date(2026, 11, 2), 14, 160, macro=load_macro(empty)))

    def test_class_filter_and_planned_review(self):
        """В выжимку облигаций не попадают отчёты по акциям; «Гейт устарел» не зовёт переподтверждать, если разбор
        уже назначен условием (kind: review или action run_analysis)."""
        bond_out = digest(PRIOR, None, date(2026, 10, 26), 14, 160, None, [
            {"file": "2026-10-23-single-analysis-ydex.md", "date": date(2026, 10, 23), "kind": "single_analysis",
             "tickers": ["YDEX"], "summary": "x"}])
        self.assertNotIn("single-analysis-ydex", bond_out)
        conds = conds_rows([_cond("x5-ifrs3q-review", "X5", "date", "2026-10-29", kind="review",
                                  action="run_analysis")], today=date(2026, 10, 26))
        out = digest({"review_date": "2026-10-16", "per_stock": {"X5": {}}}, conds, date(2026, 10, 26), 14, 160,
                     {"X5": {"status": "review_aging", "expires_on": "2026-10-20", "expired": True}}, [])
        self.assertIn("**X5**: «срок решения вышел», срок истёк 20.10; разбор уже назначен — условие `x5-ifrs3q-review` "
                      "(срок 2026-10-29)", out)

    def test_without_new_args_unchanged(self):
        out = digest(STOCK_PRIOR, None, date(2026, 10, 26), 14, 160)
        self.assertNotIn("Гейт", out)
        self.assertNotIn("Разборы бумаг", out)


class TestRatingCheckDue(unittest.TestCase):
    """Правило «рейтинг пора перепроверить» (rating_check) и блок выжимки."""
    ASOF = date(2026, 11, 3)

    def _due(self, **e):
        import rating_check as rc
        return rc.rating_check_due({"bond_type": "corp_rub", "credit_rating": "AA", **e}, self.ASOF)

    def test_rule(self):
        self.assertFalse(self._due(credit_rating_checked_at="2026-10-30"))   # свежая
        self.assertFalse(self._due(credit_rating_checked_at="2026-10-06"))   # ровно 28 дней
        self.assertTrue(self._due(credit_rating_checked_at="2026-10-05"))    # 29 дней
        self.assertTrue(self._due(credit_rating_checked_at=None))
        self.assertTrue(self._due())                                         # поля нет вовсе
        self.assertTrue(self._due(credit_rating_checked_at="не дата"))
        self.assertFalse(self._due(bond_type="ofz", credit_rating_checked_at=None))   # ОФЗ при любой дате
        self.assertFalse(self._due(bond_type="ofz", credit_rating_checked_at="2020-01-01"))
        self.assertTrue(self._due(credit_rating=None, credit_rating_checked_at=None))  # корп без рейтинга
        self.assertTrue(self._due(credit_rating=None, credit_rating_checked_at="2026-01-01"))
        self.assertFalse(self._due(credit_rating=None, credit_rating_checked_at="2026-10-30"))

    def test_rf_sovereign_by_issuer_excluded_foreign_sovereign_kept(self):
        # замещающий выпуск Минфина РФ — не ОФЗ по типу, но долг РФ: исключён (живой RU000A10A869)
        minfin = "Министерство финансов Российской Федерации (суверенный замещающий выпуск)"
        self.assertFalse(self._due(bond_type="fx_replacement", issuer=minfin, credit_rating_checked_at=None))
        # иностранный суверен остаётся: его рейтинг меняется (живой RU000A101RZ3)
        self.assertTrue(self._due(bond_type="corp_rub", issuer="Республика Казахстан (суверенный эмитент)",
                                  credit_rating_checked_at=None))
        self.assertTrue(self._due(bond_type="fx_replacement", issuer="ПАО «Газпром»", credit_rating_checked_at=None))

    def test_block_present(self):
        prior = {"review_date": "2026-11-03", "per_bond": {
            "RU1": {"name": "Бонд-1", "issuer": "ООО Альфа", "bond_type": "corp_rub", "credit_rating": "AA(RU)",
                    "credit_rating_agency": "АКРА", "credit_rating_checked_at": "2026-09-01"},
            "RU2": {"name": "Бонд-2", "issuer": "ООО Альфа", "bond_type": "corp_rub", "credit_rating": "AA(RU)"},
            "RU3": {"name": "ОФЗ", "bond_type": "ofz"}}}
        out = digest(prior, None, date(2026, 11, 5), 14, 160)
        self.assertIn("## Рейтинг пора перепроверить", out)
        self.assertIn("ООО Альфа: RU1, RU2 — AA(RU) (АКРА); последняя проверка: 2026-09-01", out)
        self.assertNotIn("RU3,", out.split("## Рейтинг пора перепроверить")[1].split("\n## ")[0])

    def test_block_empty_not_printed(self):
        prior = {"review_date": "2026-11-03", "per_bond": {
            "RU1": {"name": "Бонд-1", "bond_type": "corp_rub", "credit_rating": "AA", "credit_rating_checked_at": "2026-11-01"},
            "RU3": {"name": "ОФЗ", "bond_type": "ofz"}}}
        self.assertNotIn("Рейтинг пора перепроверить", digest(prior, None, date(2026, 11, 5), 14, 160))
        stock = {"review_date": "2026-11-03", "per_stock": {"X5": {}}}
        self.assertNotIn("Рейтинг пора перепроверить", digest(stock, None, date(2026, 11, 5), 14, 160))


if __name__ == "__main__":
    unittest.main(verbosity=1)
