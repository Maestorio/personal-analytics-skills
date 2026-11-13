#!/usr/bin/env python3
"""Снапшот без «Общего баланса» — позиции из сделок (assemble --holdings-from-trades, 2026-10-21).

Решение владельца: файл сделок обязателен, баланс — нет; из баланса берётся только то, что из сделок
не вывести. Контракты:
  • позиции основного счёта, qty, стоимость, средняя цена — из returns.snapshot_current
    (avg_cost_source "trades"); название — из прошлого снапшота;
  • облигация: корзина/подтип/рейтинг/номинал — из прошлого снапшота; выгрузка дала qty = основной +
    ИИС-3 (как ОФЗ 26238) → основной = qty − ИИС, ИИС переоценён по цене основного;
  • только-ИИС-3 облигация и фонд ИИС-3 (SBGB) — из прошлого снапшота, account iis_3;
  • внебиржевой (FINAMAR, в сделках цена покупки) — стоимость за бумагу из прошлого снапшота;
  • кэш = реконструкция по сделкам + прошлое расхождение «факт − реконструкция»; решение
    cash_drift_changed не возникает (сверять оценку с тем же расхождением бессмысленно);
  • доли и цели (IE), balance_summary — из прошлого снапшота с carried_from; итоги — по позициям;
  • флаг balance_absent_holdings_from_trades перечисляет перенесённое; без прошлого снапшота —
    ещё no_prev_snapshot_for_trades_mode;
  • этап 6 ухода от Numbers (сделки + plan.json = штатная сборка, план главный без --plan-primary):
    ie_model / ie_actual / ie_summary / goals_* / bonds_plan_vs_fact — из плана и holdings, не из прошлого
    снапшота; факт IE (доля реальная, дельта) считается из holdings; типизация облигаций по ISIN —
    из plan.bonds; стоимость FINAMAR — из plan.manual_positions; balance_carried_from и
    balance_summary.carried — только если что-то действительно взято из прошлого снапшота; нет плана —
    старое поведение + флаг no_plan_for_trades_mode; названия: прошлый снапшот → котировки → тикер.
Сеть не нужна. Запуск: python3 skills/portfolio-data-loader/tests/test_trades_mode.py
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import assemble_snapshot as asm  # noqa: E402

RETURNS = {"snapshot_current": {
    "cash_balance_rub": -100000.0, "cash_by_currency": {"RUB": -100000.0},
    "positions": [
        {"ticker": "SBER", "type": "stock", "qty": 80, "value_rub": 24000.0, "avg_cost_rub": 280.14,
         "currency": "RUB", "name": "Сбер", "price_source": "moex_last", "is_blocked": False},
        {"ticker": "SU26238RMFS4", "type": "bond", "qty": 210, "value_rub": 126000.0, "avg_cost_rub": 590.0,
         "currency": "RUB", "nominal_currency": "RUB", "name": "ОФЗ 26238", "price_source": "moex_last",
         "is_blocked": False},
        {"ticker": "FINAMAR", "type": "fund", "qty": 10, "value_rub": 9000.0, "avg_cost_rub": 900.0,
         "currency": "RUB", "name": "Финам", "price_source": "last_trade", "is_blocked": False},
        {"ticker": "SBGB", "type": "fund", "qty": 100, "value_rub": 1500.0, "avg_cost_rub": 14.0,
         "currency": "RUB", "name": "SBGB", "price_source": "moex_last", "is_blocked": False},
        {"ticker": "FXUS", "type": "fund", "qty": 5, "value_rub": 0.0, "avg_cost_rub": 1.0,
         "currency": "RUB", "name": "FXUS", "price_source": "blocked_zero", "is_blocked": True},
    ]}}

PREV = {
    "as_of_date": "2026-10-16",
    "holdings": [
        {"ticker": "SBER", "name": "Сбербанк ао", "asset_type": "stock", "account": "main", "qty": 80,
         "value_rub": 23000.0, "current_price_source": "moex_iss"},
        {"ticker": "SU26238RMFS4", "name": "ОФЗ 26238", "asset_type": "bond", "account": "main", "qty": 80,
         "value_rub": 47000.0, "plan_bucket": "ОФЗ", "plan_subtype": ">10", "nominal": 1000.0,
         "isin": "SU26238RMFS4", "current_price_source": "moex_iss"},
        {"ticker": "SU26238RMFS4", "name": "ОФЗ 26238", "asset_type": "bond", "account": "iis_3", "qty": 130,
         "value_rub": 76000.0, "plan_bucket": "ОФЗ", "plan_subtype": ">10", "isin": "SU26238RMFS4"},
        {"ticker": "SU26247RMFS5", "name": "ОФЗ 26247", "asset_type": "bond", "account": "iis_3", "qty": 50,
         "value_rub": 48000.0, "plan_bucket": "ОФЗ", "plan_subtype": "<10", "isin": "SU26247RMFS5"},
        {"ticker": "SBGB", "name": "SBGB", "asset_type": "fund", "account": "iis_3", "qty": 100, "value_rub": 1450.0},
        {"ticker": "FINAMAR", "name": "Финам Агрессивный", "asset_type": "fund", "account": "main", "qty": 10,
         "value_rub": 15000.0, "current_price_source": "cost_basis"},
    ],
    "cash": {"total_rub": 290000.0, "by_account": {"main": 270000.0, "iis_3": 20000.0}},
    "cash_reconciliation": {"current_drift_rub": 380000.0, "baseline_drift_rub": 200000.0},
    "ie_model": {"positions": [{"ticker": "SBER", "target_pct": 5}]},
    "ie_actual": {"x": 1}, "ie_summary": {"y": 2},
    "balance_summary": {"goals_matrix": {"m": 1}, "bonds_plan_vs_fact": [{"b": 1}]},
}


def build(prev=PREV):
    return asm.assemble(None, RETURNS, None, {}, prev_snapshot=prev, holdings_from_trades=True, as_of="2026-10-21")


class TradesMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = build()
        cls.h = {(h["ticker"], h["account"]): h for h in cls.s["holdings"]}
        cls.codes = [f["code"] for f in cls.s["data_quality_flags"]]

    def test_stock_from_trades(self):
        h = self.h[("SBER", "main")]
        self.assertEqual((h["qty"], h["value_rub"], h["avg_cost_rub"], h["avg_cost_source"], h["name"]),
                         (80, 24000.0, 280.14, "trades", "Сбербанк ао"))

    def test_bond_split_and_iis_repriced(self):
        m, i = self.h[("SU26238RMFS4", "main")], self.h[("SU26238RMFS4", "iis_3")]
        self.assertEqual((m["qty"], i["qty"]), (80, 130))
        self.assertAlmostEqual(m["value_rub"], 126000 / 210 * 80, places=1)
        self.assertAlmostEqual(i["value_rub"], 126000 / 210 * 130, places=1)
        self.assertEqual((m["plan_bucket"], m["plan_subtype"], m["nominal"]), ("ОФЗ", ">10", 1000.0))

    def test_iis_only_positions_carried(self):
        self.assertEqual(self.h[("SU26247RMFS5", "iis_3")]["value_rub"], 48000.0)
        self.assertIn(("SBGB", "iis_3"), self.h)
        self.assertNotIn(("SBGB", "main"), self.h)

    def test_otc_fund_priced_from_prev(self):
        self.assertEqual(self.h[("FINAMAR", "main")]["value_rub"], 15000.0)   # 1500 ₽/пай × 10, не цена покупки

    def test_blocked_kept(self):
        self.assertEqual(self.h[("FXUS", "main")]["status"], "blocked")

    def test_cash_estimate_and_no_drift_decision(self):
        self.assertEqual(self.s["cash"]["total_rub"], -100000.0 + 380000.0)
        self.assertEqual(self.s["cash"]["source"], "trades_plus_prev_drift")
        self.assertNotIn("cash_drift_changed", self.codes)

    def test_carried_from_prev(self):
        self.assertEqual(self.s["snapshot_type"], "trades_holdings")
        self.assertEqual(self.s["balance_carried_from"], "2026-10-16")
        self.assertEqual(self.s["ie_model"], PREV["ie_model"])
        bs = self.s["balance_summary"]
        self.assertEqual((bs["carried_from"], bs["goals_matrix"]), ("2026-10-16", {"m": 1}))
        securities = sum(h["value_rub"] for h in self.s["holdings"] if h.get("status") != "blocked")
        self.assertAlmostEqual(bs["total_current_rub_incl_iis"], securities + 280000.0, places=1)

    def test_flag_lists_carried(self):
        self.assertIn("balance_absent_holdings_from_trades", self.codes)
        msg = next(f["message"] for f in self.s["data_quality_flags"] if f["code"] == "balance_absent_holdings_from_trades")
        self.assertIn("2026-10-16", msg)
        self.assertIn("FINAMAR", msg)
        self.assertIn("SU26238RMFS4", msg)                      # сумма двух счетов распознана

    def test_iis_only_bond_in_main_trades_not_doubled(self):
        """Прогон 2026-10-22: ОФЗ 52004 только на ИИС-3, но её сделки есть в основной выгрузке —
        позиция встала и на основной счёт, и на ИИС-3 (+227 тыс. ₽; всего 4 бумаги, +462 тыс.)."""
        ret = {"snapshot_current": {"cash_balance_rub": 0.0, "positions": [
            {"ticker": "SU52004RMFS7", "type": "bond", "qty": 180, "value_rub": 227606.0, "avg_cost_rub": 1200.0,
             "currency": "RUB", "nominal_currency": "RUB", "price_source": "moex_last", "is_blocked": False}]}}
        prev = {"as_of_date": "2026-10-16", "cash_reconciliation": {"current_drift_rub": 0.0},
                "holdings": [{"ticker": "RU000A103MX5", "isin": "RU000A103MX5", "name": "ОФЗ 52004",
                              "asset_type": "bond", "account": "iis_3", "qty": 180, "value_rub": 227099.0}]}
        s = asm.assemble(None, ret, None, {"SU52004RMFS7": {"isin": "RU000A103MX5", "last": 120.0}},
                         prev_snapshot=prev, holdings_from_trades=True, as_of="2026-10-22")
        rows = [(h["account"], h["qty"], h["value_rub"]) for h in s["holdings"] if h["asset_type"] == "bond"]
        self.assertEqual(rows, [("iis_3", 180, 227606.0)])

    def test_secid_matched_to_isin(self):
        """Прогон 2026-10-22: в сделках облигация — код MOEX, в снапшоте — ISIN; без сопоставления
        10 облигаций «пропали из позиций», корзины и названия не перенеслись."""
        ret = {"snapshot_current": {"cash_balance_rub": 0.0, "positions": [
            {"ticker": "SU26243RMFS4", "type": "bond", "qty": 10, "value_rub": 9000.0, "avg_cost_rub": 880.0,
             "currency": "RUB", "nominal_currency": "RUB", "name": "ОФЗ 26243", "price_source": "moex_last",
             "is_blocked": False}]}}
        prev = {"as_of_date": "2026-10-16", "cash_reconciliation": {"current_drift_rub": 0.0},
                "holdings": [{"ticker": "RU000A106E90", "isin": "RU000A106E90", "name": "ОФЗ 26243 (баланс)",
                              "asset_type": "bond", "account": "main", "qty": 10, "value_rub": 8900.0,
                              "plan_bucket": "ОФЗ", "plan_subtype": ">10"}],
                "balance_summary": {"summary": {"Имеется (RUB)": 45590130.0}, "goals_matrix": {"m": 1}}}
        quotes = {"SU26243RMFS4": {"isin": "RU000A106E90", "last": 90.0}}
        s = asm.assemble(None, ret, None, quotes, prev_snapshot=prev, holdings_from_trades=True, as_of="2026-10-22")
        bonds = [h for h in s["holdings"] if h["asset_type"] == "bond"]
        self.assertEqual([(h["ticker"], h["name"], h["plan_bucket"], h["current_price"]) for h in bonds],
                         [("RU000A106E90", "ОФЗ 26243 (баланс)", "ОФЗ", 90.0)])
        self.assertIsNone(s["balance_summary"]["summary"])          # «Имеется» 16.10 не переносится
        self.assertEqual(s["balance_summary"]["goals_matrix"], {"m": 1})
        import checks
        res = checks.run_all(s, prev, as_of="2026-10-22")
        msgs = " ".join(c["message_ru"] for c in res)
        self.assertNotIn("Имеется", msgs)
        self.assertNotIn("Пропали из позиций", msgs)

    def test_without_prev_snapshot(self):
        s = build(prev=None)
        codes = [f["code"] for f in s["data_quality_flags"]]
        self.assertIn("no_prev_snapshot_for_trades_mode", codes)
        self.assertIsNone(s["cash"]["total_rub"])
        self.assertEqual({h["ticker"] for h in s["holdings"] if h.get("status") != "blocked"},
                         {"SBER", "SU26238RMFS4", "FINAMAR", "SBGB"})


# ── этап 6: сделки + plan.json ──────────────────────────────────────────────────

PLAN = {
    "schema_version": "plan@1.0", "updated_at": "2026-10-20", "updated_by": "hub-api",
    "source": {"kind": "site", "extraction_date": "2026-10-20"},
    "classes": [{"class": "Акции", "share": 0.4}, {"class": "Облигация", "share": 0.5},
                {"class": "Другое", "share": 0.05}, {"class": "Кеш", "share": 0.05}],
    "matrix": [{"currency": "RUB", "class": "Акция", "share": 0.4}, {"currency": "RUB", "class": "Облигация", "share": 0.5},
               {"currency": "RUB", "class": "Другое", "share": 0.05}, {"currency": "RUB", "class": "Кеш", "share": 0.05}],
    "bond_buckets": [{"key": "ОФЗ/>10", "type": "ОФЗ", "subtype": ">10", "share": 0.4},
                     {"key": "ОФЗ/<10", "type": "ОФЗ", "subtype": "<10", "share": 0.6}],
    "stocks": {"SBER": {"plan_pct": 6.0, "user_plan": "KEEP", "user_status": None, "note_ie": "заметка",
                        "note_ai": None, "ie_new_pct": 5.0, "ie_old_pct": 4.0}},
    "ie_model": {"extraction_date": "2026-10-20", "model_total_pct": 5.0, "positions": [
        {"ticker": "SBER", "target_share_pct": 5.0, "active_in_model": True},
        {"ticker": "ZZZZ", "target_share_pct": None, "active_in_model": False}]},
    # в плане облигация уже в другой корзине, чем в прошлом снапшоте (">10"): план главнее
    "bonds": {"SU26238RMFS4": {"name": "ОФЗ 26238", "type": "ОФЗ", "subtype": "<10", "rating": None,
                               "action": "BUY", "iis_qty": None}},
    "manual_positions": [{"type": "RUB - Другое", "name": "FINAMAR", "value_rub": 16000.0},
                         {"type": "USD - Другое", "name": "TGLD", "value_rub": 1.0}],
    "funds": {},
}


class TradesWithPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.plan_path = str(Path(cls.tmp.name) / "plan.json")
        Path(cls.plan_path).write_text(json.dumps(PLAN, ensure_ascii=False), encoding="utf-8")
        cls.s = asm.assemble(None, RETURNS, None, {}, prev_snapshot=PREV, holdings_from_trades=True,
                             as_of="2026-10-21", plan_path=cls.plan_path)
        cls.h = {(h["ticker"], h["account"]): h for h in cls.s["holdings"]}
        cls.codes = [f["code"] for f in cls.s["data_quality_flags"]]
        cls.bs = cls.s["balance_summary"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_ie_from_plan_not_prev(self):
        self.assertEqual(self.s["ie_model"]["extraction_date"], "2026-10-20")
        self.assertNotEqual(self.s["ie_model"], PREV["ie_model"])
        self.assertEqual(self.s["ie_actual"]["extraction_date"], "2026-10-20")
        self.assertEqual(self.s["ie_actual"]["source_sheet"], "plan.json")

    def test_ie_facts_from_holdings(self):
        row = self.s["ie_actual"]["per_ticker"]["SBER"]
        self.assertEqual((row["planned_share_pct"], row["ie_new_pct"], row["ie_old_pct"], row["user_plan"]),
                         (6.0, 5.0, 4.0, "KEEP"))
        self.assertEqual(row["ie_delta_pct"], 1.0)
        self.assertEqual(row["real_share_pct"], 100.0)               # единственная акция основного счёта
        self.assertEqual(row["user_note_ie"], "заметка")
        sm = self.s["ie_summary"]
        self.assertEqual((sm["tickers_in_ie_model"], sm["tickers_in_both"], sm["real_share_total_in_ie_pct"],
                          sm["ie_changes_count"]), (1, 1, 100.0, 1))      # позиция общего портфеля IE не считается

    def test_goals_from_plan(self):
        self.assertEqual([(r["Тип"], r["Доля"]) for r in self.bs["goals_overall"]],
                         [("Акции", 0.4), ("Облигация", 0.5), ("Другое", 0.05), ("Кеш", 0.05)])
        self.assertIsNone(self.bs["goals_matrix_iis"])               # ИИС-3 вне целей
        rub_stock = next(r for r in self.bs["goals_matrix"] if r["Бумага"] == "Акция")
        self.assertEqual(rub_stock["Сейчас"], 24000.0)               # факт матрицы считает загрузчик по holdings
        self.assertGreater(rub_stock["Планы"], 0)
        self.assertAlmostEqual(rub_stock["Изменение"], rub_stock["Планы"] - rub_stock["Сейчас"], places=2)

    def test_bond_typing_and_buckets_from_plan(self):
        m = self.h[("SU26238RMFS4", "main")]
        self.assertEqual((m["plan_bucket"], m["plan_subtype"]), ("ОФЗ", "<10"))
        rows = {r["bucket_key"]: r for r in self.bs["bonds_plan_vs_fact"]}
        self.assertAlmostEqual(rows["ОФЗ/<10"]["actual_rub"], 126000 / 210 * 80, places=1)   # основной счёт
        self.assertEqual(rows["ОФЗ/>10"]["actual_rub"], 0.0)
        self.assertEqual(rows["ОФЗ/<10"]["target_pct"], 60.0)
        cls_bond = next(r for r in self.bs["class_plan_vs_fact"] if r["class"] == "Облигация")
        self.assertAlmostEqual(rows["ОФЗ/<10"]["target_rub"], 0.6 * cls_bond["target_rub"], places=1)
        iis = {r["bucket_key"]: r["actual_rub"] for r in self.bs["bonds_plan_vs_fact_iis"]}
        self.assertIn("ОФЗ/<10", iis)                                # ИИС-3 той же бумаги — по типизации плана

    def _stale_codes(self, qty, plan_value):
        import copy
        ret = copy.deepcopy(RETURNS)
        for p in ret["snapshot_current"]["positions"]:
            if p["ticker"] == "FINAMAR":
                p["qty"] = qty
        plan = copy.deepcopy(PLAN)
        for m in plan["manual_positions"]:
            if m["name"] == "FINAMAR":
                m["value_rub"] = plan_value
        pp = Path(self.tmp.name) / "plan-stale.json"
        pp.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        s = asm.assemble(None, ret, None, {}, prev_snapshot=PREV, holdings_from_trades=True, as_of="2026-10-21", plan_path=str(pp))
        return [f for f in s["data_quality_flags"] if f["code"] == "manual_value_stale"]

    def test_manual_value_stale_qty_changed_value_same(self):
        fl = self._stale_codes(12, 15000.0)          # прошлый снапшот: 10 пай, 15 000 ₽
        self.assertEqual(len(fl), 1)
        self.assertEqual(fl[0]["severity"], "warning")
        self.assertIn("FINAMAR: количество по сделкам изменилось (10 → 12 шт.)", fl[0]["message"])
        self.assertIn("осталась 15 000 ₽", fl[0]["message"])

    def _asof_flags(self, as_of, last_trade, qty=10, plan_value=15000.0):
        import copy
        ret = copy.deepcopy(RETURNS)
        for p in ret["snapshot_current"]["positions"]:
            if p["ticker"] == "FINAMAR":
                p["qty"] = qty
        plan = copy.deepcopy(PLAN)
        for m in plan["manual_positions"]:
            if m["name"] == "FINAMAR":
                m["value_rub"] = plan_value
                if as_of:
                    m["value_as_of"] = as_of
        pp = Path(self.tmp.name) / "plan-asof.json"
        pp.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        ps = {"FINAMAR": {"last_trade_date": last_trade}} if last_trade else {}
        s = asm.assemble(None, ret, ps, {}, prev_snapshot=PREV, holdings_from_trades=True, as_of="2026-10-26", plan_path=str(pp))
        return [f for f in s["data_quality_flags"] if f["code"] == "manual_value_stale"]

    def test_manual_value_stale_second_branch_value_as_of_before_last_trade(self):
        fl = self._asof_flags("2026-10-20", "2026-10-25")
        self.assertEqual(len(fl), 1)
        self.assertEqual(fl[0]["severity"], "warning")
        self.assertIn("FINAMAR: оценка в базе сайта от 20.10.2026, последняя сделка 25.10.2026", fl[0]["message"])
        self.assertIn("«Оценку вручную»", fl[0]["message"])

    def test_manual_value_stale_second_branch_not_when_as_of_later_or_equal_or_absent(self):
        self.assertEqual(self._asof_flags("2026-10-25", "2026-10-25"), [])     # равна — без флага
        self.assertEqual(self._asof_flags("2026-10-26", "2026-10-25"), [])     # позже
        self.assertEqual(self._asof_flags(None, "2026-10-25"), [])             # нет value_as_of — только первая ветка
        self.assertEqual(self._asof_flags("2026-10-20", None), [])             # даты сделки нет

    def test_manual_value_stale_one_flag_per_security(self):
        fl = self._asof_flags("2026-10-20", "2026-10-25", qty=12)             # обе ветки применимы
        self.assertEqual(len(fl), 1)
        self.assertIn("количество по сделкам изменилось", fl[0]["message"])    # приоритет у первой

    def test_manual_value_stale_not_when_qty_same_or_value_changed(self):
        self.assertEqual(self._stale_codes(10, 15000.0), [])      # количество то же
        self.assertEqual(self._stale_codes(12, 18000.0), [])      # сумма в плане обновлена

    def test_iis_qty_not_overwritten_by_plan(self):
        self.assertEqual(self.h[("SU26238RMFS4", "iis_3")]["qty"], 130)

    def test_finamar_value_from_plan(self):
        self.assertEqual(self.h[("FINAMAR", "main")]["value_rub"], 16000.0)      # план, не 15000 прошлого
        self.assertNotIn("otc_price:FINAMAR", self.bs["carried"])

    def test_tgld_manual_value_not_applied(self):
        """В плане ручной остаток TGLD=1.0 (наследие Numbers) — для биржевых бумаг стоимость даёт MOEX (п. 5)."""
        ret = {"snapshot_current": {"cash_balance_rub": 0.0, "positions": [
            {"ticker": "TGLD", "type": "fund", "qty": 10, "value_rub": 5000.0, "avg_cost_rub": 400.0,
             "currency": "RUB", "name": "TGLD", "price_source": "moex_last", "is_blocked": False}]}}
        s = asm.assemble(None, ret, None, {}, prev_snapshot={"as_of_date": "2026-10-16"}, holdings_from_trades=True,
                         as_of="2026-10-21", plan_path=self.plan_path)
        self.assertEqual(next(h for h in s["holdings"] if h["ticker"] == "TGLD")["value_rub"], 5000.0)

    def test_carried_lists_what_is_taken_from_prev(self):
        self.assertEqual(self.s["balance_carried_from"], "2026-10-16")
        self.assertEqual(self.bs["carried_from"], "2026-10-16")
        for k in ("iis_positions", "cash_drift", "names"):
            self.assertIn(k, self.bs["carried"])
        self.assertNotIn("no_plan_for_trades_mode", self.codes)

    def test_flag_text_names_plan(self):
        msg = next(f["message"] for f in self.s["data_quality_flags"] if f["code"] == "balance_absent_holdings_from_trades")
        self.assertIn("plan.json от 2026-10-20", msg)
        self.assertIn("базы сайта", msg)
        self.assertIn("ИИС-3", msg)
        self.assertIn("кеш — оценка", msg)

    def test_plan_check_applied(self):
        pc = self.s["plan_check"]
        self.assertEqual((pc["source"], pc["applied"], pc["plan_updated_at"], pc["n_diff"]),
                         ("plan_only", True, "2026-10-20", 0))

    def test_nothing_carried_when_prev_has_nothing_to_give(self):
        """ИИС-3 без позиций, кэш внесён фактом (основной и ИИС-3), названия — из котировок."""
        ret = {"snapshot_current": {"cash_balance_rub": 0.0, "positions": [RETURNS["snapshot_current"]["positions"][0]]}}
        prev = {"as_of_date": "2026-10-16", "holdings": [], "cash_reconciliation": {"current_drift_rub": 0.0}}
        s = asm.assemble(None, ret, None, {"SBER": {"short_name": "Сбербанк ао"}}, prev_snapshot=prev,
                         holdings_from_trades=True, as_of="2026-10-21", plan_path=self.plan_path,
                         cash_fact=100000.0, cash_fact_iis=0.0)
        self.assertIsNone(s["balance_carried_from"])
        self.assertIsNone(s["balance_summary"]["carried_from"])
        self.assertEqual(s["balance_summary"]["carried"], [])
        self.assertEqual(s["holdings"][0]["name"], "Сбербанк ао")
        self.assertEqual(s["cash"]["source"], "owner_intelinvest")

    def test_without_plan_old_behaviour_and_flag(self):
        s = asm.assemble(None, RETURNS, None, {}, prev_snapshot=PREV, holdings_from_trades=True, as_of="2026-10-21")
        codes = [f["code"] for f in s["data_quality_flags"]]
        self.assertIn("no_plan_for_trades_mode", codes)
        self.assertEqual(s["ie_model"], PREV["ie_model"])
        self.assertEqual(s["balance_summary"]["goals_matrix"], {"m": 1})
        self.assertEqual(s["balance_carried_from"], "2026-10-16")
        self.assertIn("ie_model", s["balance_summary"]["carried"])

    def test_unreadable_plan_falls_back_with_flag(self):
        bad = Path(self.tmp.name) / "bad.json"
        bad.write_text("{не json", encoding="utf-8")
        s = asm.assemble(None, RETURNS, None, {}, prev_snapshot=PREV, holdings_from_trades=True, as_of="2026-10-21",
                         plan_path=str(bad))
        self.assertIn("no_plan_for_trades_mode", [f["code"] for f in s["data_quality_flags"]])
        self.assertEqual(s["ie_model"], PREV["ie_model"])
        self.assertEqual(s["plan_check"]["source"], "error")

    def test_names_prev_then_quotes_then_ticker(self):
        ret = {"snapshot_current": {"cash_balance_rub": 0.0, "positions": [
            {"ticker": "AAA", "type": "stock", "qty": 1, "value_rub": 10.0, "avg_cost_rub": 10.0, "currency": "RUB",
             "price_source": "moex_last", "is_blocked": False},
            {"ticker": "BBB", "type": "stock", "qty": 1, "value_rub": 10.0, "avg_cost_rub": 10.0, "currency": "RUB",
             "price_source": "moex_last", "is_blocked": False},
            {"ticker": "CCC", "type": "stock", "qty": 1, "value_rub": 10.0, "avg_cost_rub": 10.0, "currency": "RUB",
             "name": "Из сделок", "price_source": "moex_last", "is_blocked": False}]}}
        prev = {"as_of_date": "2026-10-16", "holdings": [
            {"ticker": "AAA", "name": "Из прошлого", "asset_type": "stock", "account": "main", "qty": 1}]}
        quotes = {"AAA": {"short_name": "Котировка AAA"}, "BBB": {"short_name": "Котировка BBB"}}
        s = asm.assemble(None, ret, None, quotes, prev_snapshot=prev, holdings_from_trades=True, as_of="2026-10-21")
        names = {h["ticker"]: h["name"] for h in s["holdings"]}
        self.assertEqual(names, {"AAA": "Из прошлого", "BBB": "Котировка BBB", "CCC": "Из сделок"})
        s2 = asm.assemble(None, {"snapshot_current": {"cash_balance_rub": 0.0, "positions": [
            dict(ret["snapshot_current"]["positions"][0], ticker="DDD")]}}, None, {}, prev_snapshot=None,
            holdings_from_trades=True, as_of="2026-10-21")
        self.assertEqual(s2["holdings"][0]["name"], "DDD")             # ни прошлого, ни котировки, ни сделок — тикер


class ByAccountNoBalance(unittest.TestCase):
    """balance_summary.by_account без баланса: из holdings и кэша, смысл полей как у сборки с балансом
    (блокер ухода от Numbers: стабы советника читали null и считали суммы облигаций вручную)."""

    @classmethod
    def setUpClass(cls):
        pos = list(RETURNS["snapshot_current"]["positions"]) + [
            {"ticker": "TMON", "type": "fund", "qty": 1, "value_rub": 100000.0, "avg_cost_rub": 1.0,
             "currency": "RUB", "name": "TMON", "price_source": "moex_last", "is_blocked": False},
            {"ticker": "TGLD", "type": "fund", "qty": 1, "value_rub": 5000.0, "avg_cost_rub": 1.0,
             "currency": "RUB", "name": "TGLD", "price_source": "moex_last", "is_blocked": False}]
        ret = {"snapshot_current": dict(RETURNS["snapshot_current"], positions=pos)}
        cls.s = asm.assemble(None, ret, None, {}, prev_snapshot=PREV, holdings_from_trades=True, as_of="2026-10-21")
        cls.ba = cls.s["balance_summary"]["by_account"]

    def test_main_classes(self):
        m = self.ba["main"]
        self.assertEqual(m["stocks_rub"], 24000.0)
        self.assertAlmostEqual(m["bonds_rub"], 126000 / 210 * 80, places=1)     # бумага на двух счетах: доля основного
        self.assertEqual(m["funds_rub"], 5000.0)             # TGLD; денежный TMON и внебиржевой FINAMAR — в кэш, как у баланса

    def test_iis_classes(self):
        i = self.ba["iis_3"]
        self.assertAlmostEqual(i["bonds_rub"], 126000 / 210 * 130 + 48000.0, places=1)
        self.assertEqual((i["stocks_rub"], i["funds_rub"]), (0.0, 1500.0))      # SBGB — реальный фонд счёта
        self.assertEqual(i["cash_rub"], 20000.0)             # кэш ИИС-3 из прошлого снапшота
        self.assertAlmostEqual(i["total_rub"], i["bonds_rub"] + i["funds_rub"] + 20000.0, places=1)

    def test_main_cash_is_dirty_residual_like_balance(self):
        m = self.ba["main"]
        self.assertAlmostEqual(m["cash_rub"], 260000.0 + 100000.0 + 15000.0, places=1)   # кэш + TMON + FINAMAR
        self.assertAlmostEqual(m["total_rub"], m["stocks_rub"] + m["bonds_rub"] + m["funds_rub"] + m["cash_rub"], places=1)
        self.assertEqual(m["total_rub"], self.s["balance_summary"]["total_current_rub_excl_iis"])

    def test_true_cash_untouched(self):
        self.assertEqual(self.s["cash"]["by_account"]["iis_3"], 20000.0)

    def test_cash_unknown_gives_none_not_invented(self):
        s = build(prev=None)
        m = s["balance_summary"]["by_account"]["main"]
        self.assertIsNone(m["total_rub"])
        self.assertIsNone(m["cash_rub"])
        self.assertEqual(m["stocks_rub"], 24000.0)           # то, что из позиций, считается и без кэша

    def test_with_balance_by_account_from_numbers(self):
        portfolio = {"metrics": {"total_current_rub_excl_iis": 1.0, "iis_balance_rub": 2.0,
                                 "by_account": {"main": {"total_rub": 1.0, "marker": "numbers"}}}}
        s = asm.assemble(portfolio, RETURNS, None, {}, prev_snapshot=None, as_of="2026-10-21")
        self.assertEqual(s["balance_summary"]["by_account"], portfolio["metrics"]["by_account"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
