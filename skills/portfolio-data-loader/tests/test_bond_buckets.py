#!/usr/bin/env python3
"""Корзина облигации выводится из данных Мосбиржи и рейтинга; средняя цена покупки облигации.

Контракты (SSOT — docs/investment/portfolio/bond-subtypes-plan.md §4.5):
  • A. security_types.parse_description несёт для облигации блок "bond" (тип выпуска, срок, валюта номинала,
    флоатер, эмитент): ОФЗ-ПД, ОФЗ-ПК (флоатер по «переменным купоном»), корпоративная RUB, замещайка USD,
    юаневая, иностранный суверен с TYPE ofz_bond (Казахстан-11 — НЕ ОФЗ); запись справочника без блока
    "bond" дозапрашивается один раз;
  • B. bond_bucket.derive_bucket / apply_bond_buckets: валюта → USD/EUR/CNY; ОФЗ → Флоат либо «>10»/«<10» по годам
    от даты снапшота (ровно 10 лет — «>10»; 26247 при приближении к погашению уходит в «<10»); КОРП → по
    лестнице: рейтинг обзора → рейтинг плана → нет (подтип пуст + bond_rating_missing); вне лестницы →
    bond_rating_below_ladder; manual перебивает; расхождение выведенной с плановой → корзина по плану +
    bond_bucket_changed (было → стало); плана нет → берётся выведенная; нет справочника → корзина плана;
  • C. load_review_ratings читает per_bond[ISIN].rating последнего обзора облигаций не позднее даты снапшота;
  • D. bond_avg_price: WACC, чистая цена в % номинала, докупка по другой цене сдвигает среднюю, продажа не меняет,
    сделки ИИС-3 вычитаются из выгрузки основного счёта, сопоставление ISIN ↔ SECID через справочник;
  • сборка: _apply_bond_derivations кладёт bucket_* и avg_* в holdings, bond_bucket_check — в снапшот.
Сеть не нужна. Запуск: python3 skills/portfolio-data-loader/tests/test_bond_buckets.py
"""
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import bond_avg_price as ba  # noqa: E402
import bond_bucket as bb  # noqa: E402
import portfolio_returns as pr  # noqa: E402
import security_types as st  # noqa: E402
from assemble_snapshot import _apply_bond_derivations, _build_bonds_plan_vs_fact  # noqa: E402

AS_OF = "2026-10-28"


def iss(rows):
    return {"description": {"columns": ["name", "title", "value"],
                            "data": [[k, k, v] for k, v in rows.items()]}}


OFZ_PD = {"SECID": "SU26247RMFS5", "ISSUENAME": "облигации федерального займа с постоянным купонным доходом",
          "NAME": "ОФЗ-ПД 26247 11/05/39", "ISIN": "RU000A108EF8", "MATDATE": "2039-05-11", "FACEUNIT": "SUR",
          "FACEVALUE": "1000", "TYPENAME": "Государственная облигация", "GROUP": "stock_bonds", "TYPE": "ofz_bond"}
OFZ_PK = {**OFZ_PD, "SECID": "SU29008RMFS8", "ISSUENAME": "облигации федерального займа с переменным купонным доходом",
          "NAME": "ОФЗ-ПК 29008 03/10/29", "ISIN": "RU000A0JV4P3", "MATDATE": "2029-10-03"}
CORP = {"SECID": "RU000A10CT33", "ISSUENAME": "биржевые облигации процентные неконвертируемые бездокументарные",
        "NAME": "Атомэнергопром АО 001Р-08", "ISIN": "RU000A10CT33", "MATDATE": "2030-09-17", "FACEUNIT": "SUR",
        "FACEVALUE": "1000", "TYPENAME": "Биржевая облигация", "GROUP": "stock_bonds", "TYPE": "exchange_bond"}
USD_REPL = {**CORP, "SECID": "RU000A105A95", "ISIN": "RU000A105A95", "FACEUNIT": "USD",
            "NAME": "Газпром капитал ООО ЗО34-1-Д", "TYPENAME": "Корпоративная облигация", "TYPE": "corporate_bond"}
CNY_BOND = {**CORP, "SECID": "RU000A1054W1", "ISIN": "RU000A1054W1", "FACEUNIT": "CNY"}
KAZ = {**OFZ_PD, "SECID": "RU000A101RZ3", "ISIN": "RU000A101RZ3", "NAME": "Республика Казахстан 11",
       "ISSUENAME": "бездокументарные процентные неконвертируемые государственные облигации Республики Казахстан"}


def attrs_of(rows):
    return st.parse_description(iss(rows))["bond"]


# ───────────────────────────── A ─────────────────────────────

class ParseBondAttrs(unittest.TestCase):
    def test_ofz_pd(self):
        b = attrs_of(OFZ_PD)
        self.assertEqual((b["issuer_type"], b["is_floater"], b["faceunit"], b["matdate"], b["facevalue"]),
                         ("ofz", False, "RUB", "2039-05-11", 1000.0))
        self.assertEqual((b["sectype"], b["typename"]), ("ofz_bond", "Государственная облигация"))

    def test_ofz_pk_is_floater(self):
        self.assertTrue(attrs_of(OFZ_PK)["is_floater"])
        self.assertEqual(attrs_of(OFZ_PK)["issuer_type"], "ofz")

    def test_floater_by_name_only(self):
        rows = {**OFZ_PD, "ISSUENAME": "облигации федерального займа", "NAME": "ОФЗ-ПК 29027 01/01/30"}
        self.assertTrue(attrs_of(rows)["is_floater"])

    def test_corp_rub(self):
        b = attrs_of(CORP)
        self.assertEqual((b["issuer_type"], b["is_floater"], b["faceunit"]), ("corp", False, "RUB"))

    def test_fx_units(self):
        self.assertEqual(attrs_of(USD_REPL)["faceunit"], "USD")
        self.assertEqual(attrs_of(CNY_BOND)["faceunit"], "CNY")

    def test_foreign_sovereign_is_not_ofz(self):
        b = attrs_of(KAZ)
        self.assertEqual((b["sectype"], b["issuer_type"]), ("ofz_bond", "gov_other"))

    def test_not_bond_has_no_block(self):
        r = st.parse_description(iss({"GROUP": "stock_shares", "TYPE": "common_share", "ISIN": "RU0009029540"}))
        self.assertNotIn("bond", r)

    def test_entry_without_bond_block_is_refetched(self):
        today = dt.date(2026, 10, 28)
        old = {"type": "bond", "isin": "X", "fetched_at": "2026-10-01", "source": "moex_iss"}
        self.assertTrue(st.needs_fetch(old, today))
        self.assertFalse(st.needs_fetch({**old, "bond": {"issuer_type": "corp"}}, today))
        self.assertFalse(st.needs_fetch({"type": "fund", "isin": "X", "fetched_at": "2026-10-01"}, today))


# ───────────────────────────── B ─────────────────────────────

def derive(rows, as_of=AS_OF, nominal_currency=None, plan_rating=None, review=None, maturity=None):
    return bb.derive_bucket(attrs_of(rows), nominal_currency=nominal_currency, maturity_date=maturity,
                            as_of=as_of, plan_rating=plan_rating, review_rating=review)


class Derive(unittest.TestCase):
    def test_ofz_over_10_then_under_10_when_closer_to_maturity(self):
        far = derive(OFZ_PD, as_of="2026-10-28")                      # 12,5 г.
        self.assertEqual(far["key"], "ОФЗ/>10")
        self.assertIn("до погашения 12,5 г.", far["reason"])
        near = derive(OFZ_PD, as_of="2030-01-01")                     # 9,4 г.
        self.assertEqual(near["key"], "ОФЗ/<10")
        self.assertEqual(near["source"], "iss")

    def test_ofz_ten_years_boundary_inclusive(self):
        m = dt.date.fromisoformat(AS_OF) + dt.timedelta(days=3653)    # 10,001 г.
        on = {**OFZ_PD, "MATDATE": m.isoformat()}
        self.assertEqual(derive(on)["key"], "ОФЗ/>10")
        under = {**OFZ_PD, "MATDATE": (m - dt.timedelta(days=2)).isoformat()}
        self.assertEqual(derive(under)["key"], "ОФЗ/<10")

    def test_ofz_pk_float(self):
        d = derive(OFZ_PK)
        self.assertEqual((d["key"], d["subtype"]), ("ОФЗ/Флоат", "Флоат"))

    def test_fx_replacement(self):
        self.assertEqual(derive(USD_REPL)["key"], "USD")
        self.assertEqual(derive(CNY_BOND)["key"], "CNY")
        self.assertEqual(derive(USD_REPL)["reason"], "валюта номинала USD")

    def test_corp_rating_from_review_by_ladder(self):
        rv = {"value": "AA-", "agency": "АКРА", "date": "2026-09-12"}
        d = derive(CORP, review=rv)
        self.assertEqual((d["key"], d["source"]), ("КОРП/AA+", "rating"))
        self.assertEqual(d["reason"], "КОРП, рейтинг AA- (АКРА, 12.09.2026, обзор)")
        for r, want in (("AAA", "AA+"), ("A+", "A"), ("A-", "A"), ("BBB+", "B+"), ("B-", "B+")):
            self.assertEqual(derive(CORP, review={"value": r})["subtype"], want, r)

    def test_review_rating_beats_plan(self):
        d = derive(CORP, plan_rating="A", review={"value": "A+", "agency": "АКРА", "date": "2026-09-12"})
        self.assertEqual(d["key"], "КОРП/A")                  # A+ по лестнице → A; обзор, не план
        self.assertEqual(d["reason"], "КОРП, рейтинг A+ (АКРА, 12.09.2026, обзор)")
        d = derive(CORP, plan_rating="AAA", review={"value": "A"})
        self.assertEqual(d["key"], "КОРП/A")                  # план AAA не перебивает обзор
        d = derive(CORP, plan_rating="A")
        self.assertEqual(d["key"], "КОРП/A")
        self.assertEqual(d["reason"], "КОРП, рейтинг A (план)")  # обзора нет — запасной план

    def test_corp_without_rating(self):
        d = derive(CORP)
        self.assertIsNone(d["key"])
        self.assertEqual(d["codes"], ["bond_rating_missing"])
        self.assertEqual(derive(CORP, review={"value": "нет рейтинга"})["codes"], ["bond_rating_missing"])

    def test_corp_below_ladder(self):
        d = derive(CORP, review={"value": "CCC"})
        self.assertIsNone(d["key"])
        self.assertEqual(d["codes"], ["bond_rating_below_ladder"])

    def test_foreign_sovereign_not_derivable(self):
        d = derive(KAZ)
        self.assertIsNone(d["key"])
        self.assertEqual(d["codes"], ["bond_issuer_not_derivable"])

    def test_no_attrs(self):
        d = bb.derive_bucket(None, nominal_currency="RUB", maturity_date=None, as_of=AS_OF)
        self.assertIsNone(d["key"])


def hold(isin, plan_t, plan_s, **kw):
    h = {"ticker": isin, "isin": isin, "name": isin, "asset_type": "bond", "account": "main",
         "plan_bucket": plan_t, "plan_subtype": plan_s,
         "plan_bucket_key": (f"{plan_t}/{plan_s}" if plan_s else plan_t) if plan_t else None,
         "nominal_currency": "RUB", "maturity_date": None, "value_rub": 1000.0}
    h.update(kw)
    return h


def attrs_map(**rows):
    return {isin: attrs_of(r) for isin, r in rows.items()}


class Apply(unittest.TestCase):
    def run_apply(self, holdings, plan_bonds, attrs, reviews=None):
        return bb.apply_bond_buckets(holdings, plan_bonds, attrs, reviews or {}, AS_OF)

    def test_agree_with_plan_gets_source_and_reason(self):
        h = hold("RU000A108EF8", "ОФЗ", ">10")
        blk, flags = self.run_apply([h], {}, {"RU000A108EF8": attrs_of(OFZ_PD)})
        self.assertEqual((h["bucket_source"], h["bucket_derived"], h["plan_bucket_key"]), ("iss", "ОФЗ/>10", "ОФЗ/>10"))
        self.assertEqual(flags, [])
        self.assertEqual(blk["changes"], [])

    def test_disagreement_keeps_plan_and_flags_change(self):
        h = hold("RU000A108EF8", "ОФЗ", "<10", name="ОФЗ 26247")
        blk, flags = self.run_apply([h], {}, {"RU000A108EF8": attrs_of(OFZ_PD)})
        self.assertEqual(h["plan_bucket_key"], "ОФЗ/<10")                 # корзина — по-старому
        self.assertEqual((h["bucket_source"], h["bucket_derived"]), ("plan", "ОФЗ/>10"))
        self.assertEqual([(c["was"], c["now"]) for c in blk["changes"]], [("ОФЗ/<10", "ОФЗ/>10")])
        self.assertEqual([f["code"] for f in flags], ["bond_bucket_changed"])
        self.assertIn("ОФЗ/<10", flags[0]["message"])
        self.assertIn("ОФЗ/>10", flags[0]["message"])

    def test_two_accounts_one_change(self):
        a = hold("RU000A108EF8", "ОФЗ", "<10")
        b = hold("RU000A108EF8", "ОФЗ", "<10", account="iis_3")
        blk, flags = self.run_apply([a, b], {}, {"RU000A108EF8": attrs_of(OFZ_PD)})
        self.assertEqual(len(blk["changes"]), 1)
        self.assertEqual(len(flags), 1)
        self.assertEqual(b["bucket_derived"], "ОФЗ/>10")

    def test_manual_beats_derived(self):
        h = hold("RU000A108EF8", "ОФЗ", "<10")
        plan = {"RU000A108EF8": {"manual": True, "reason": "держу как короткую до погашения"}}
        blk, flags = self.run_apply([h], plan, {"RU000A108EF8": attrs_of(OFZ_PD)})
        self.assertEqual((h["bucket_source"], h["plan_bucket_key"]), ("manual", "ОФЗ/<10"))
        self.assertEqual(h["bucket_reason"], "вручную: держу как короткую до погашения")
        self.assertEqual(h["bucket_derived"], "ОФЗ/>10")
        self.assertEqual((blk["changes"], flags), ([], []))

    def test_no_plan_bucket_adopts_derived(self):
        h = hold("RU000A1054W1", None, None)
        self.run_apply([h], {}, {"RU000A1054W1": attrs_of(CNY_BOND)})
        self.assertEqual((h["plan_bucket"], h["plan_bucket_key"], h["bucket_source"]), ("CNY", "CNY", "iss"))

    def test_corp_rating_from_review_used_when_plan_has_none(self):
        h = hold("RU000A10CT33", "КОРП", "AA+")
        rv = {"RU000A10CT33": {"value": "AAA", "agency": "АКРА", "date": "2026-09-12"}}
        self.run_apply([h], {"RU000A10CT33": {"rating": None}}, {"RU000A10CT33": attrs_of(CORP)}, rv)
        self.assertEqual((h["bucket_source"], h["bucket_derived"]), ("rating", "КОРП/AA+"))
        self.assertEqual(h["bucket_reason"], "КОРП, рейтинг AAA (АКРА, 12.09.2026, обзор)")

    def test_corp_without_rating_flag_and_plan_kept(self):
        h = hold("RU000A10CT33", "КОРП", "A", name="Атомэнпр08")
        blk, flags = self.run_apply([h], {}, {"RU000A10CT33": attrs_of(CORP)})
        self.assertEqual((h["bucket_source"], h["plan_bucket_key"], h["bucket_derived"]), ("plan", "КОРП/A", None))
        self.assertEqual([f["code"] for f in flags], ["bond_rating_missing"])
        self.assertEqual(blk["missing"][0]["code"], "bond_rating_missing")

    def test_no_attrs_keeps_plan_old_behavior(self):
        h = hold("RU000A108EF8", "ОФЗ", "<10")
        blk, flags = self.run_apply([h], {}, {})
        self.assertEqual((h["plan_bucket_key"], h["bucket_source"], h["bucket_derived"]), ("ОФЗ/<10", "plan", None))
        self.assertEqual((blk["changes"], flags), ([], []))

    def test_other_asset_types_untouched(self):
        f = {"ticker": "TMON", "asset_type": "fund"}
        self.run_apply([f], {}, {})
        self.assertNotIn("bucket_source", f)

    PLAN_ROWS = [
        {"Тип": "КОРП", "_subtype": "AA+", "_bucket_key": "КОРП/AA+", "Доля План": 0.5, "План сумма": 100.0},
        {"Тип": "CNY", "_subtype": None, "_bucket_key": "CNY", "Доля План": 0.5, "План сумма": 100.0},
    ]

    def test_guard_bond_bucket_not_in_plan(self):
        # Акрон 29–30.10: ключ «CNY/AA+» — такой корзины в плане нет; бумага выпала из корзин, сумма корзин меньше облигаций
        ok = hold("A1", "CNY", None, value_rub=100.0)
        bad = hold("AKRON", "CNY", "AA+", value_rub=141700.0, name="Акрон Б2P3")
        rows, _iis, fl = _build_bonds_plan_vs_fact({"goals": {"bonds_breakdown": self.PLAN_ROWS}}, [ok, bad], {})
        miss = [f for f in fl if f["code"] == "bond_bucket_not_in_plan"]
        self.assertEqual(len(miss), 1)
        self.assertEqual(miss[0]["severity"], "warn")
        self.assertIn("Акрон Б2P3", miss[0]["message"])
        self.assertIn("141,700", miss[0]["message"])
        self.assertIn("CNY/AA+", miss[0]["message"])
        self.assertEqual(sum(r["actual_rub"] for r in rows), 100.0)         # проверка падением: сумма корзин < облигаций

    def test_guard_silent_when_all_in_plan_and_iis_ignored(self):
        a = hold("A1", "CNY", None, value_rub=100.0)
        iis = hold("I1", "ОФЗ", "<10", value_rub=500.0, account="iis_3")    # ИИС-3 в план не входит — не флаг
        rows, _iis, fl = _build_bonds_plan_vs_fact({"goals": {"bonds_breakdown": self.PLAN_ROWS}}, [a, iis], {})
        self.assertEqual([f for f in fl if f["code"] == "bond_bucket_not_in_plan"], [])

    def test_guard_fund_bucket_not_in_plan_main_only(self):
        # фонд основного счёта с корзиной вне плана — флаг; тот же фонд только на ИИС-3 (SBGB) — нет
        fund_main = {"ticker": "TLCB", "name": "TLCB", "asset_type": "fund", "account": "main", "value_rub": 162000.0}
        fund_iis = {"ticker": "SBGB", "name": "SBGB", "asset_type": "fund", "account": "iis_3", "value_rub": 9000.0}
        funds = {"TLCB": {"bucket": "EUR"}, "SBGB": {"bucket": "ОФЗ/<10"}}
        _r, _i, fl = _build_bonds_plan_vs_fact({"goals": {"bonds_breakdown": self.PLAN_ROWS}}, [fund_main, fund_iis], funds)
        miss = [f for f in fl if f["code"] == "bond_bucket_not_in_plan"]
        self.assertEqual(len(miss), 1)
        self.assertIn("TLCB", miss[0]["message"])

    def test_parity_bonds_plan_vs_fact_uses_final_key(self):
        a = hold("RU000A108EF8", "ОФЗ", "<10", value_rub=100.0)       # выведено >10, но корзина по плану
        c = hold("RU000A1054W1", None, None, value_rub=50.0)          # плана нет → выведенная CNY
        self.run_apply([a, c], {}, {"RU000A108EF8": attrs_of(OFZ_PD), "RU000A1054W1": attrs_of(CNY_BOND)})
        portfolio = {"goals": {"bonds_breakdown": [
            {"Тип": "ОФЗ", "_subtype": "<10", "_bucket_key": "ОФЗ/<10", "Доля План": 0.5, "План сумма": 100.0},
            {"Тип": "CNY", "_subtype": None, "_bucket_key": "CNY", "Доля План": 0.5, "План сумма": 100.0},
        ]}}
        rows, _iis, _fl = _build_bonds_plan_vs_fact(portfolio, [a, c], {})
        by = {r["bucket_key"]: r["actual_rub"] for r in rows}
        self.assertEqual(by, {"ОФЗ/<10": 100.0, "CNY": 50.0})


# ───────────────────────────── C ─────────────────────────────

def write_review(d: Path, date, per_bond):
    import yaml
    (d / f"weekly-review-bond-{date}.yaml").write_text(
        yaml.safe_dump({"review_date": date, "per_bond": per_bond}, allow_unicode=True), encoding="utf-8")


class ReviewRatings(unittest.TestCase):
    def test_latest_review_not_after_asof(self):
        d = Path(tempfile.mkdtemp())
        write_review(d, "2026-10-16", {"A": {"rating": {"value": "A", "agency": "АКРА", "date": "2026-09-01"}}})
        write_review(d, "2026-10-28", {"A": {"rating": {"value": "AA", "agency": "АКРА", "date": "2026-10-20"}},
                                       "B": {"credit_rating": None}})
        write_review(d, "2026-11-05", {"A": {"rating": {"value": "AAA"}}})
        got = bb.load_review_ratings(d, "2026-10-28")
        self.assertEqual(got["A"]["value"], "AA")
        self.assertNotIn("B", got)
        self.assertEqual(bb.load_review_ratings(d, "2026-10-20")["A"]["value"], "A")

    def test_missing_dir(self):
        self.assertEqual(bb.load_review_ratings(None), {})
        self.assertEqual(bb.load_review_ratings("/nonexistent-dir-xyz"), {})


# ───────────────────────────── D ─────────────────────────────

def T(tk, op, d, qty, price, nominal=1000.0, nkd=10.0, cur="RUB", name=None):
    t = pr.Trade(tk, name or tk, op, dt.date.fromisoformat(d), qty, price, nominal, nkd, 0.0,
                 (qty or 0) * ((price or 0) / 100 * (nominal or 0) + (nkd or 0)),
                 (qty or 0) * ((price or 0) / 100 * (nominal or 0)), cur, "")
    t.rub_rate = 1.0 if cur == "RUB" else 11.0
    return t


class AvgPrice(unittest.TestCase):
    def test_two_buys_weighted(self):
        a = ba.bond_avg_prices([T("X", "Покупка", "2026-01-10", 10, 80.0), T("X", "Покупка", "2026-02-10", 30, 90.0)])["X"]
        self.assertEqual(a["qty"], 40)
        self.assertAlmostEqual(a["avg_price_pct"], 87.5, 4)
        self.assertAlmostEqual(a["avg_cost_rub"], 875.0, 4)               # без НКД
        self.assertFalse(a["avg_includes_accint"])

    def test_partial_sale_keeps_average_and_rebuy_shifts_it(self):
        tr = [T("X", "Покупка", "2026-01-10", 10, 80.0), T("X", "Покупка", "2026-02-10", 30, 90.0),
              T("X", "Продажа", "2026-03-10", 20, 95.0)]
        a = ba.bond_avg_prices(tr)["X"]
        self.assertEqual(a["qty"], 20)
        self.assertAlmostEqual(a["avg_price_pct"], 87.5, 4)               # WACC: продажа среднюю не меняет
        a2 = ba.bond_avg_prices(tr + [T("X", "Покупка", "2026-04-10", 20, 100.0)])["X"]
        self.assertAlmostEqual(a2["avg_price_pct"], (20 * 87.5 + 20 * 100.0) / 40, 4)

    def test_closed_position_absent(self):
        self.assertEqual(ba.bond_avg_prices([T("X", "Покупка", "2026-01-10", 5, 80.0),
                                             T("X", "Продажа", "2026-02-10", 5, 85.0)]), {})

    def test_fx_trade_converted_to_rub(self):
        a = ba.bond_avg_prices([T("C", "Покупка", "2026-01-10", 5, 99.0, cur="CNY")])["C"]
        self.assertAlmostEqual(a["avg_price_pct"], 99.0, 4)
        self.assertAlmostEqual(a["avg_cost_rub"], 990.0 * 11.0, 4)
        self.assertEqual(a["avg_cost_currency"], "CNY")

    def test_no_price_falls_back_with_accint_mark(self):
        t = T("X", "Покупка", "2026-01-10", 10, None, nominal=None)
        t.amount_no_comm = 9000.0
        a = ba.bond_avg_prices([t])["X"]
        self.assertIsNone(a["avg_price_pct"])
        self.assertAlmostEqual(a["avg_cost_rub"], 900.0, 4)
        self.assertTrue(a["avg_includes_accint"])

    def test_subtract_iis_trades_from_main_export(self):
        main = [T("X", "Покупка", "2026-01-10", 10, 80.0), T("X", "Покупка", "2026-04-20", 130, 60.0),
                T("X", "Купон", "2026-05-01", 140, None)]
        iis = [T("X", "Покупка", "2026-04-20", 130, 60.0)]
        rest = ba.subtract_trades(main, iis)
        self.assertEqual([(t.operation, t.qty) for t in rest], [("Покупка", 10), ("Купон", 140)])
        self.assertAlmostEqual(ba.bond_avg_prices(rest)["X"]["avg_price_pct"], 80.0, 4)
        self.assertAlmostEqual(ba.bond_avg_prices(iis)["X"]["avg_price_pct"], 60.0, 4)

    def test_compact_roundtrip(self):
        tr = [T("X", "Покупка", "2026-01-10", 10, 80.0), T("X", "Продажа", "2026-02-10", 4, 85.0),
              T("X", "Купон", "2026-03-10", 6, None)]
        back = ba.expand_trades(json.loads(json.dumps(ba.compact_trades(tr))))
        self.assertEqual(ba.bond_avg_prices(back), ba.bond_avg_prices(tr))

    def test_match_holding_isin_secid_and_name(self):
        avgs = {"SU26238RMFS4": {"avg_price_pct": 60.0, "name": "ОФЗ 26238"}}
        idx = ba.secid_index({"by_ticker": {"SU26238RMFS4": {"isin": "RU000A1038V6", "type": "bond"}}})
        self.assertIs(ba.match_holding(avgs, {"ticker": "RU000A1038V6", "isin": "RU000A1038V6"}, idx),
                      avgs["SU26238RMFS4"])
        self.assertIs(ba.match_holding(avgs, {"ticker": "Z", "isin": "Z", "name": "ОФЗ 26238"}, {}),
                      avgs["SU26238RMFS4"])
        self.assertIsNone(ba.match_holding(avgs, {"ticker": "Q", "isin": "Q", "name": "другая"}, idx))

    def test_apply_per_account(self):
        main = {"A": {"avg_price_pct": 80.0, "avg_cost_rub": 800.0, "avg_includes_accint": False}}
        iis = {"A": {"avg_price_pct": 60.0, "avg_cost_rub": 600.0, "avg_includes_accint": False}}
        hs = [hold("A", "ОФЗ", ">10"), hold("A", "ОФЗ", ">10", account="iis_3")]
        self.assertEqual(ba.apply_bond_avg(hs, main, iis, {}), 2)
        self.assertEqual([h["avg_price_pct"] for h in hs], [80.0, 60.0])
        self.assertEqual(hs[0]["avg_cost_source"], "trades")


# ───────────────────────────── сборка ─────────────────────────────

class AssembleStep(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        (self.d / "weekly-reviews").mkdir()
        (self.d / "plan.json").write_text("{}", encoding="utf-8")
        self.types = {"schema_version": "security-types@1.0", "by_ticker": {
            "SU26247RMFS5": {"type": "bond", "isin": "RU000A108EF8", "bond": attrs_of(OFZ_PD)},
            "RU000A10CT33": {"type": "bond", "isin": "RU000A10CT33", "bond": attrs_of(CORP)},
            "RU000A105A95": {"type": "bond", "isin": "RU000A105A95", "bond": attrs_of(USD_REPL)}}}
        (self.d / "security-types.json").write_text(json.dumps(self.types), encoding="utf-8")
        write_review(self.d / "weekly-reviews", "2026-10-28",
                     {"RU000A10CT33": {"rating": {"value": "AAA", "agency": "Эксперт РА", "date": "2026-08-01"}}})

    def holdings(self):
        return [hold("RU000A108EF8", "ОФЗ", ">10"), hold("RU000A10CT33", "КОРП", "AA+"),
                hold("RU000A105A95", "USD", None), hold("RU000A108EF8", "ОФЗ", ">10", account="iis_3")]

    def test_defaults_next_to_plan(self):
        hs = self.holdings()
        plan = {"bonds": {"RU000A10CT33": {"rating": None}}}
        chk, flags = _apply_bond_derivations(hs, plan, AS_OF, None, None, None, str(self.d / "plan.json"), None, None)
        self.assertEqual([h["bucket_source"] for h in hs], ["iss", "rating", "iss", "iss"])
        self.assertEqual(hs[1]["bucket_reason"], "КОРП, рейтинг AAA (Эксперт РА, 01.08.2026, обзор)")
        self.assertEqual((chk["changes"], chk["derived"], flags), ([], 4, []))

    def test_without_plan_path_old_behavior(self):
        hs = self.holdings()
        chk, flags = _apply_bond_derivations(hs, None, AS_OF, None, None, None, None, None, None)
        self.assertTrue(all(h["bucket_source"] == "plan" for h in hs))
        self.assertEqual([f["code"] for f in flags], ["bond_attrs_unavailable"])

    def test_explicit_paths_and_carry_for_iis(self):
        hs = self.holdings()
        prev = {"holdings": [{"asset_type": "bond", "account": "iis_3", "isin": "RU000A108EF8", "qty": 5,
                              "avg_price_pct": 70.0, "avg_cost_rub": 700.0, "avg_cost_source": "trades"}]}
        hs[3]["qty"] = 5
        _apply_bond_derivations(hs, None, AS_OF, None, None, [prev], None,
                                str(self.d / "security-types.json"), str(self.d / "weekly-reviews"))
        self.assertEqual((hs[3]["avg_price_pct"], hs[3]["avg_cost_source"]), (70.0, "carried"))
        self.assertNotIn("avg_price_pct", hs[0])
        hs[3]["qty"] = 6                                                 # количество изменилось — не переносим
        hs[3].pop("avg_price_pct")
        _apply_bond_derivations(hs, None, AS_OF, None, None, [prev], None,
                                str(self.d / "security-types.json"), str(self.d / "weekly-reviews"))
        self.assertNotIn("avg_price_pct", hs[3])


if __name__ == "__main__":
    unittest.main(verbosity=1)
