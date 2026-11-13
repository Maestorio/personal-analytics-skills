#!/usr/bin/env python3
"""Этап 4b ухода от Numbers: build_class_breakdown — факт по классам и матрице валюта × класс.

Контракты (docs/investment/portfolio/numbers-exit-plan.md §3.2):
  • база — брокерский счёт без ИИС-3; акции без замороженных (cost_basis); облигации — по корзине плана
    (USD/EUR/CNY → своя валюта, ОФЗ/КОРП → RUB), иначе по nominal_currency; фонды — по карте plan.funds;
  • деньги = cash.by_account.main в «Кеш RUB»; фонд-облигации входят и в факт облигаций своей валюты;
  • строка «Таблицы 1» с бумагой, которая есть в holdings с ценой, пропускается (manual_position_duplicate);
  • фонд > 0 без карты и без строки «Таблицы 1» → class None + fund_unmapped; сумма фактов = сумма базы;
  • корзины облигаций: фонд-член берётся из карты (bucket) и из «Таблицы 1» без двойного счёта;
  • checks.py: fund_unmapped → предупреждение;
  • паритет с Numbers (goals.matrix[].«Сейчас») на реальных файлах — допуск 3 % на ячейку; нет файлов → skip.
Запуск: python3 skills/portfolio-data-loader/tests/test_class_breakdown.py
"""
import glob
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import checks as ch  # noqa: E402
from assemble_snapshot import (_build_bonds_plan_vs_fact, _class_fact_mismatch,  # noqa: E402
                               build_class_breakdown)

BALANCE = Path("/private/tmp/claude-501/-Users-alexey-Documents-----------claude-skills/"
               "589fde49-1d53-4681-9481-a7600fa59eb0/scratchpad/balance.json")
SNAP_DIR = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory/Portfolio/snapshots"

OWNER_MAP = {
    "TMON": ("Кеш", "RUB"), "TPAY": ("Кеш", "RUB"), "LQDT": ("Кеш", "RUB"),
    "TGLD": ("Золото", "USD"), "TLCB": ("Облигация", "USD"), "XXXXXX": ("Другое", "RUB"),
    "FINAMAR": ("Другое", "RUB"), "SBGB": ("Облигация", "RUB"),
}


def _funds(only=None):
    return {t: {"class": c, "currency": cur, "bucket": "USD" if t == "TLCB" else None}
            for t, (c, cur) in OWNER_MAP.items() if only is None or t in only}


def _h(ticker, at, value, *, account="main", cur="RUB", nom=None, src="moex_iss", bucket=None):
    return {"ticker": ticker, "asset_type": at, "account": account, "currency": cur, "nominal_currency": nom,
            "current_price_source": src, "value_rub": value, "plan_bucket": bucket}


PLAN = {
    "classes": [{"class": "Акции", "share": 0.4}, {"class": "Облигация", "share": 0.5},
                {"class": "Золото", "share": 0.03}, {"class": "Другое", "share": 0.03},
                {"class": "Кеш", "share": 0.04}],
    "matrix": [{"currency": "RUB", "class": "Кеш", "share": 0.04}, {"currency": "RUB", "class": "Акция", "share": 0.4},
               {"currency": "USD", "class": "Облигация", "share": 0.06}, {"currency": "USD", "class": "Золото", "share": 0.03}],
    "funds": _funds(),
    "manual_positions": [],
}


def _holdings():
    return [
        _h("SBER", "stock", 1000.0), _h("PLZL", "stock", 500.0),
        _h("KO", "stock", 0.0, src="cost_basis"),                      # замороженная — вне
        _h("AAPL", "stock", 777.0, src="cost_basis"),                  # замороженная с ценой > 0 — вне
        _h("B_RUB", "bond", 400.0, nom="RUB", bucket="ОФЗ"),
        _h("B_USD", "bond", 300.0, nom="USD", bucket="USD"),
        _h("B_CNY_CORP", "bond", 200.0, nom="CNY", bucket="КОРП"),     # номинал CNY, корзина КОРП → RUB
        _h("B_IIS", "bond", 999.0, account="iis_3", nom="RUB", bucket="ОФЗ"),
        _h("TMON", "fund", 100.0), _h("TGLD", "fund", 50.0), _h("TLCB", "fund", 30.0),
        _h("XXXXXX", "fund", 20.0), _h("FINAMAR", "fund", 10.0), _h("SBGB", "fund", 888.0, account="iis_3"),
    ]


CASH = {"total_rub": 400.0, "by_account": {"main": 60.0, "iis_3": 340.0}}


def _cell(rows, cur, cls):
    return next(r for r in rows if r["currency"] == cur and r["class"] == cls)["actual_rub"]


class TestSynthetic(unittest.TestCase):
    def test_cells_by_hand(self):
        cls, mx, flags = build_class_breakdown(_holdings(), CASH, PLAN)
        self.assertEqual(_cell(mx, "RUB", "Акция"), 1500.0)
        self.assertEqual(_cell(mx, "RUB", "Облигация"), 600.0)          # 400 + корпоративная с номиналом CNY
        self.assertEqual(_cell(mx, "USD", "Облигация"), 330.0)          # облигация 300 + фонд TLCB 30
        self.assertEqual(_cell(mx, "USD", "Золото"), 50.0)
        self.assertEqual(_cell(mx, "RUB", "Кеш"), 160.0)                # 60 кэш + TMON 100
        self.assertEqual(_cell(mx, "RUB", "Другое"), 30.0)              # XXXXXX 20 + FINAMAR 10
        total = 1500 + 600 + 330 + 50 + 160 + 30
        self.assertAlmostEqual(sum(r["actual_rub"] for r in cls), total, 2)
        self.assertAlmostEqual(sum(r["actual_rub"] for r in mx), total, 2)
        by = {r["class"]: r for r in cls}
        self.assertEqual(by["Акции"]["actual_rub"], 1500.0)
        self.assertEqual(by["Облигация"]["actual_rub"], 930.0)
        self.assertAlmostEqual(by["Акции"]["target_pct"], 40.0)
        self.assertAlmostEqual(by["Акции"]["target_rub"], 0.4 * total, 2)
        self.assertAlmostEqual(by["Акции"]["delta_rub"], 0.4 * total - 1500, 2)
        self.assertAlmostEqual(by["Акции"]["actual_pct"], 1500 / total * 100, 3)
        self.assertEqual(flags, [])
        self.assertFalse(any(r["class"] is None for r in cls))

    def test_iis_and_frozen_excluded(self):
        _, mx, _ = build_class_breakdown(_holdings(), CASH, PLAN)
        self.assertNotIn(999.0, [r["actual_rub"] for r in mx])
        self.assertNotIn(777.0, [r["actual_rub"] for r in mx])

    def test_cash_fallback_total_minus_iis(self):
        _, mx, _ = build_class_breakdown([], {"total_rub": 400.0, "by_account": {"iis_3": 340.0}}, PLAN)
        self.assertEqual(_cell(mx, "RUB", "Кеш"), 60.0)

    def test_no_plan_gives_null_targets(self):
        cls, mx, _ = build_class_breakdown(_holdings(), CASH, None)
        self.assertTrue(all(r["target_pct"] is None and r["delta_rub"] is None for r in cls))
        self.assertEqual(_cell(mx, "RUB", "Акция"), 1500.0)

    def test_fund_unmapped(self):
        plan = {**PLAN, "funds": _funds(only={"TGLD", "TLCB", "XXXXXX", "FINAMAR"})}      # без TMON
        cls, mx, flags = build_class_breakdown(_holdings(), CASH, plan)
        un = [f for f in flags if f["code"] == "fund_unmapped"]
        self.assertEqual(len(un), 1)
        self.assertIn("TMON", un[0]["message"])
        self.assertEqual(un[0]["severity"], "warn")
        row = next(r for r in cls if r["class"] is None)
        self.assertEqual(row["actual_rub"], 100.0)
        self.assertIsNone(row["target_pct"])
        self.assertAlmostEqual(sum(r["actual_rub"] for r in cls), 1500 + 600 + 330 + 50 + 60 + 100 + 30, 2)
        # checks.py: предупреждение
        snap = {"data_quality_flags": flags, "schema_version": "2.0"}
        res = [r for r in ch.check_snapshot(ch.Ctx(snap=snap, prev=None, trades=None, as_of="2026-10-27",
                                                   returns=None)) if r["id"] == "fund_unmapped"]
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["level"], "warning")

    def test_manual_row_duplicate_skipped_and_fallback(self):
        manual = [
            {"name": "TGLD", "type": "USD - Другое", "value_rub": 382320.0},          # дубль holdings
            {"name": "Ренат ПРО", "type": "RUB - Другое", "value_rub": 270000.0},     # дубль XXXXXX по алиасу
            {"name": "SBGB", "type": "RUB - ИИС", "value_rub": 54334.0},              # ИИС — вне матрицы
            {"name": "ДОМ", "type": "RUB - Другое", "value_rub": 5.0},                # нет в holdings — считается
        ]
        plan = {**PLAN, "manual_positions": manual}
        _, mx, flags = build_class_breakdown(_holdings(), CASH, plan)
        dup = [f for f in flags if f["code"] == "manual_position_duplicate"]
        self.assertEqual(len(dup), 2)
        self.assertTrue(all(f["severity"] == "info" for f in dup))
        self.assertEqual(_cell(mx, "RUB", "Другое"), 35.0)
        self.assertEqual(_cell(mx, "USD", "Золото"), 50.0)

    def test_manual_value_overrides_non_exchange_price(self):
        manual = [{"name": "FINAMAR", "type": "RUB - Другое", "value_rub": 179493.0}]
        plan = {**PLAN, "manual_positions": manual}
        hs = [h for h in _holdings() if h["ticker"] != "FINAMAR"]
        for src, want, code in (("last_trade", 179493.0 + 20.0, "manual_position_override"),
                                ("cost_basis", 179493.0 + 20.0, "manual_position_override"),
                                ("moex_iss", 10.0 + 20.0, "manual_position_duplicate")):
            _, mx, flags = build_class_breakdown(hs + [_h("FINAMAR", "fund", 10.0, src=src)], CASH, plan)
            self.assertEqual(_cell(mx, "RUB", "Другое"), want, src)
            self.assertEqual([f["code"] for f in flags], [code], src)
            self.assertEqual(flags[0]["severity"], "info")

    def test_manual_row_is_fallback_class_for_unmapped_fund(self):
        plan = {**PLAN, "funds": {}, "manual_positions": [{"name": "TLCB", "type": "USD - Облигации", "value_rub": 1.0}]}
        _, mx, flags = build_class_breakdown(_holdings(), CASH, plan)
        self.assertEqual(_cell(mx, "USD", "Облигация"), 330.0)                          # стоимость — из holdings
        # без карты остаются TMON, TGLD, XXXXXX, FINAMAR; TLCB получил класс из строки «Таблицы 1»
        self.assertEqual(len([f for f in flags if f["code"] == "fund_unmapped"]), 4)

    def test_other_positions_numbers_form(self):
        other = [{"Тип": "USD - Другое", "Бумага": "TGLD", "Стоимость": 1.0},
                 {"Тип": "RUB - Другое", "Бумага": "ДОМ", "Стоимость": 7.0}]
        _, mx, flags = build_class_breakdown(_holdings(), CASH, PLAN, other_positions=other)
        self.assertEqual(_cell(mx, "RUB", "Другое"), 37.0)
        self.assertEqual(len([f for f in flags if f["code"] == "manual_position_duplicate"]), 1)

    def test_bucket_members_from_map_without_double_count(self):
        portfolio = {"goals": {"bonds_breakdown": [{"Тип": "USD", "_subtype": None, "_bucket_key": "USD",
                                                     "Доля План": 0.06, "План сумма": 1000.0}]},
                     "other_positions": [{"Тип": "USD - Облигации", "Бумага": "TLCB", "Стоимость": 31.0}]}
        usd = lambda r: next(x for x in r if x["bucket_key"] == "USD")["actual_rub"]   # noqa: E731
        hs2 = [dict(h, plan_bucket_key="USD" if h["ticker"] == "B_USD" else h.get("plan_bucket_key")) for h in _holdings()]
        with_map, _, _ = _build_bonds_plan_vs_fact(portfolio, hs2, _funds())
        fallback, _, _ = _build_bonds_plan_vs_fact(portfolio, hs2, None)
        self.assertEqual(usd(with_map), 330.0)          # 300 + TLCB 30 из holdings (карта); строка «Таблицы 1» (31) не добавляется
        self.assertEqual(usd(fallback), 331.0)          # запасной путь: TLCB только из «Таблицы 1»
        # карта без этого фонда → строка «Таблицы 1» остаётся единственным источником
        only_other, _, _ = _build_bonds_plan_vs_fact(portfolio, hs2, _funds(only={"TMON"}))
        self.assertEqual(usd(only_other), 331.0)

    def test_ofz_bucket_member_from_map(self):
        portfolio = {"goals": {"bonds_breakdown": [{"Тип": "ОФЗ", "_subtype": ">10", "_bucket_key": "ОФЗ/>10",
                                                     "Доля План": 0.3, "План сумма": 1000.0}]}}
        hs = [_h("SBGB", "fund", 70.0)]
        funds = {"SBGB": {"class": "Облигация", "currency": "RUB", "bucket": "ОФЗ/>10"}}
        res, _, _ = _build_bonds_plan_vs_fact(portfolio, hs, funds)
        self.assertEqual(next(x for x in res if x["bucket_key"] == "ОФЗ/>10")["actual_rub"], 70.0)
        res, _, _ = _build_bonds_plan_vs_fact(portfolio, hs, {"SBGB": dict(funds["SBGB"], bucket=None)})
        self.assertEqual(next(x for x in res if x["bucket_key"] == "ОФЗ/>10")["actual_rub"], 0.0)

    def test_fact_mismatch_flag(self):
        _, mx, _ = build_class_breakdown(_holdings(), CASH, PLAN)
        nm = [{"Валюта": "RUB", "Бумага": "Акция", "Сейчас": 1500.0 * 2}]
        self.assertEqual(len(_class_fact_mismatch(mx, nm)), 1)
        nm_ok = [{"Валюта": "RUB", "Бумага": "Акция", "Сейчас": 1500.0}]
        self.assertEqual(_class_fact_mismatch(mx, nm_ok), [])


class TestAssembleWiring(unittest.TestCase):
    def test_keys_with_and_without_plan(self):
        import tempfile
        import numbers_to_plan as n2p
        from assemble_snapshot import assemble
        from test_numbers_to_plan import portfolio
        p = portfolio()
        plan = n2p.build_plan(p, source_file=None)
        plan["funds"] = _funds()
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "plan.json"
            f.write_text(json.dumps(plan), encoding="utf-8")
            snap = assemble(p, None, None, None, plan_path=str(f), as_of="2026-10-27")
            bs = snap["balance_summary"]
            self.assertIsInstance(bs["class_plan_vs_fact"], list)
            self.assertIsInstance(bs["matrix_plan_vs_fact"], list)
            self.assertEqual([r["class"] for r in bs["class_plan_vs_fact"][:5]],
                             ["Кеш", "Акции", "Облигация", "Золото", "Другое"])
            snap2 = assemble(p, None, None, None, as_of="2026-10-27")
        self.assertIsNone(snap2["balance_summary"]["class_plan_vs_fact"])
        self.assertIsNone(snap2["balance_summary"]["matrix_plan_vs_fact"])


def _load_parity():
    if not BALANCE.exists() or not SNAP_DIR.exists():
        return None
    b = json.loads(BALANCE.read_text(encoding="utf-8"))
    snaps = sorted(glob.glob(str(SNAP_DIR / "portfolio-2026-10-2*.json")))
    if not snaps:
        return None
    want = (b.get("summary") or {}).get("Имеется (RUB)")
    loaded = [(p, json.loads(Path(p).read_text(encoding="utf-8"))) for p in snaps]
    same = [x for x in loaded if ((x[1].get("balance_summary") or {}).get("summary") or {}).get("Имеется (RUB)") == want]
    near = same or [x for x in loaded if x[1].get("holdings")]
    return b, (near[-1] if near else None)


class TestParityWithNumbers(unittest.TestCase):
    TOL_PCT = 3.0

    def test_parity(self):
        loaded = _load_parity()
        if loaded is None or loaded[1] is None:
            self.skipTest("skip: нет разбора Numbers или снапшотов")
        b, (path, snap) = loaded
        plan = {"funds": _funds()}
        _, mx, flags = build_class_breakdown(snap["holdings"], snap["cash"], plan, other_positions=b["other_positions"])
        ours: dict[tuple[str, str], float] = {}
        for r in mx:
            cls = "Другое" if r["class"] == "Золото" else r["class"]       # в Numbers золото лежит в «Другое USD»
            ours[(r["currency"], cls)] = ours.get((r["currency"], cls), 0.0) + r["actual_rub"]
        print(f"\nПаритет с Numbers: снапшот {Path(path).name}")
        print(f"{'ячейка':<20}{'Numbers':>14}{'расчёт':>14}{'разница %':>11}")
        bad = []
        nums = {}
        for n in b["goals"]["matrix"]:
            key = (n["Валюта"], n["Бумага"])
            num = n.get("Сейчас") or 0.0
            nums[key] = num
            got = ours.get(key, 0.0)
            d = (got - num) / num * 100 if num else 0.0
            print(f"{key[0] + ' ' + key[1]:<20}{num:>14,.0f}{got:>14,.0f}{d:>+10.1f}%")
            if num and abs(d) > self.TOL_PCT:
                bad.append((key, d))
        # «Другое RUB» (FINAMAR оценён в Numbers иначе) и «Кеш RUB» (остаток) расходятся на одну и ту же сумму
        offset = ours[("RUB", "Другое")] - nums[("RUB", "Другое")]
        offset2 = ours[("RUB", "Кеш")] - nums[("RUB", "Кеш")]
        print(f"Другое RUB: {offset:+,.0f} ₽; Кеш RUB: {offset2:+,.0f} ₽ — сумма {offset + offset2:+,.2f} ₽ "
              "(кеш в Numbers — остаток, поглощает оценку FINAMAR)")
        self.assertAlmostEqual(offset + offset2, 0.0, delta=500.0)
        self.assertEqual([k for k, _ in bad if k != ("RUB", "Другое")], [], f"ячейки вне допуска: {bad}")
        self.assertAlmostEqual(sum(ours.values()), snap["balance_summary"]["total_current_rub_excl_iis"], delta=1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
