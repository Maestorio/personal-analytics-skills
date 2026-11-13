#!/usr/bin/env python3
"""Тесты для compute_bond_carry.py (Слой 2 total-return).

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 \
        skills/portfolio-scenario-stress/tests/test_compute_bond_carry.py

Синтетические фикстуры, stdlib only. Приёмка §8 плана total-return:
короткая бумага (реинвест), длинная (купоны без реинвеста), FX (SUR-маппинг,
FX на купоны и тело), distressed override, флоатер, санкционный haircut,
MM/кэш по КС-траектории, аддитивность компонент, p-weighted expected.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "skills/portfolio-scenario-stress/scripts"))

import compute_bond_carry as cbc  # noqa: E402


def check(label: str, cond: bool, detail: str = "") -> bool:
    if cond:
        print(f"  ✓ {label}")
        return True
    print(f"  ✗ {label}{(' — ' + detail) if detail else ''}")
    return False


AS_OF = "2026-07-02"
BASELINE = {"cbr_rate_pct": 16.0}
HORIZON_ENDS = {"h6": "2026-12-31", "h12": "2027-06-30", "h24": "2028-06-30"}

# Сценарий A: снижение КС, ослабление рубля, санкции; B: всё стоит на месте.
SCENARIOS = {
    "A": {"p": 0.5, "factors_by_horizon": {
        "h6": {"cbr_rate": -1.0, "usdrub": 5.0, "cnyrub": 4.0, "sanctions": 1.0},
        "h12": {"cbr_rate": -2.0, "usdrub": 10.0, "cnyrub": 8.0, "sanctions": 1.0},
        "h24": {"cbr_rate": -4.0, "usdrub": 20.0, "cnyrub": 16.0, "sanctions": 1.0},
    }},
    "B": {"p": 0.5, "factors_by_horizon": {
        "h6": {"cbr_rate": 0.0, "usdrub": 0.0, "cnyrub": 0.0, "sanctions": 0.0},
        "h12": {"cbr_rate": 0.0, "usdrub": 0.0, "cnyrub": 0.0, "sanctions": 0.0},
        "h24": {"cbr_rate": 0.0, "usdrub": 0.0, "cnyrub": 0.0, "sanctions": 0.0},
    }},
}


def bond(**kw) -> dict:
    base = {
        "ticker": "TESTBOND", "asset_type": "bond", "is_blocked": False,
        "value_rub": 100000.0, "current_price": 95.0, "nominal": 1000.0,
        "nominal_currency": "SUR", "coupon_pct": 12.0, "coupon_freq_per_year": 2,
        "next_coupon_date": "2026-10-01", "maturity_date": "2031-04-01",
        "offer_date": None, "ytm_pct": 13.0, "ytm_to_offer_pct": None,
        "account": "main",
    }
    base.update(kw)
    return base


def run_for(holdings, cash_rub=0.0, overrides=None, params=None):
    snap = {"as_of_date": AS_OF, "holdings": holdings,
            "cash": {"total_rub": cash_rub}}
    return cbc.run({
        "snapshot": snap, "scenarios": SCENARIOS, "baseline": BASELINE,
        "horizon_ends": HORIZON_ENDS, "overrides": overrides, "params": params,
    })["bond_carry"]


def cells(entry, hk):
    return entry["by_horizon"][hk]["by_scenario"]


def additive(cell) -> bool:
    return abs(sum(cell["components"].values()) - cell["carry_pct"]) < 1e-6


def all_additive(bc) -> bool:
    for entry in bc["per_position"].values():
        for hk in entry["by_horizon"]:
            for cell in cells(entry, hk).values():
                if not additive(cell):
                    return False
    return True


# ───────────────────────────── тесты ─────────────────────────────

def test_short_bond_reinvest():
    """Короткая бумага (гасится 2027-04-01, внутри h12/h24): купоны до t_live,
    pull-to-par, реинвест по сценарной КС; в h6 — только купоны."""
    print("\n[test_short_bond_reinvest]")
    b = bond(ticker="SHORT", maturity_date="2027-04-01")
    bc = run_for([b])
    e = bc["per_position"]["SHORT"]
    ok = True

    h6 = cells(e, "h6")["B"]
    exp_coupon = (12.0 / 2) * 100 / 95.0  # один купон 2026-10-01
    ok &= check("h6: один купон, ≈6.316% от цены",
                abs(h6["components"]["coupons"] - exp_coupon) < 1e-3,
                str(h6["components"]))
    ok &= check("h6: pull-to-par нет (не гасится)", h6["components"]["pull_to_par"] == 0)
    ok &= check("h6: реинвеста нет", h6["components"]["reinvest"] == 0)
    ok &= check("h6: matures_within=False", not e["by_horizon"]["h6"]["matures_within"])

    h12 = cells(e, "h12")["B"]
    ok &= check("h12: два купона (2026-10-01 + 2027-04-01 при погашении)",
                abs(h12["components"]["coupons"] - 2 * exp_coupon) < 1e-3,
                str(h12["components"]))
    exp_pull = (100 - 95) / 95 * 100
    ok &= check("h12: pull-to-par = 5/95", abs(h12["components"]["pull_to_par"] - exp_pull) < 1e-3)
    ok &= check("h12: реинвест > 0", h12["components"]["reinvest"] > 0)
    ok &= check("h12: matures_within=True", e["by_horizon"]["h12"]["matures_within"])
    ok &= check("h12: флаг reinvested", "reinvested" in e["by_horizon"]["h12"]["flags"])
    ok &= check("h12: t_live < H",
                e["by_horizon"]["h12"]["t_live_months"] < 11.9,
                str(e["by_horizon"]["h12"]["t_live_months"]))

    # Сценарная зависимость реинвеста: в A ставка ниже → реинвест меньше, чем в B
    rA = cells(e, "h24")["A"]["components"]["reinvest"]
    rB = cells(e, "h24")["B"]["components"]["reinvest"]
    ok &= check("h24: реинвест в A (КС падает) < B (КС стоит)", rA < rB, f"A={rA} B={rB}")
    ok &= check("реинвест B ≈ base×16%×(H−t_live)/12 (санити >10% на ~15 мес)",
                rB > 10.0, str(rB))
    return ok


def test_long_bond_coupons_only():
    """Длинная бумага (2031): купоны на всех горизонтах, без pull-to-par/реинвеста;
    RUB фикс-купон — carry одинаков в A и B (haircut не задет: спред < порога)."""
    print("\n[test_long_bond_coupons_only]")
    b = bond(ticker="LONG", maturity_date="2031-04-01", ytm_pct=13.0)
    bc = run_for([b])
    e = bc["per_position"]["LONG"]
    ok = True
    for hk in ("h6", "h12", "h24"):
        c = cells(e, hk)["B"]
        ok &= check(f"{hk}: pull-to-par = 0", c["components"]["pull_to_par"] == 0)
        ok &= check(f"{hk}: реинвест = 0", c["components"]["reinvest"] == 0)
        ok &= check(f"{hk}: не гасится", not e["by_horizon"][hk]["matures_within"])
    cA, cB = cells(e, "h24")["A"], cells(e, "h24")["B"]
    ok &= check("h24: фикс RUB-купон сценарно-независим (A == B)",
                abs(cA["carry_pct"] - cB["carry_pct"]) < 1e-9,
                f"A={cA['carry_pct']} B={cB['carry_pct']}")
    n24 = cells(e, "h24")["B"]["components"]["coupons"] / ((12.0 / 2) * 100 / 95.0)
    ok &= check("h24: 4 купона за ~24 мес (окт26, апр27, окт27, апр28)",
                abs(n24 - 4) < 1e-3, str(n24))
    return ok


def test_fx_bond_and_sur_mapping():
    """FX: SUR → рублёвая (fx_income = 0); USD-бумага получает FX на купоны,
    при погашении внутри H — и на тело; carry зависит от usdrub-сценария."""
    print("\n[test_fx_bond_and_sur_mapping]")
    sur = bond(ticker="SURB", nominal_currency="SUR")
    usd = bond(ticker="USDB", nominal_currency="USD", coupon_pct=3.0,
               current_price=97.0, maturity_date="2027-06-29",
               next_coupon_date="2026-12-29", ytm_pct=6.0)
    bc = run_for([sur, usd])
    ok = True
    e_sur = bc["per_position"]["SURB"]
    ok &= check("SUR: fx_income = 0 (рублёвая по MOEX-конвенции)",
                all(cells(e_sur, hk)[s]["components"]["fx_income"] == 0
                    for hk in ("h6", "h12", "h24") for s in ("A", "B")))
    e_usd = bc["per_position"]["USDB"]
    cA = cells(e_usd, "h12")["A"]
    cB = cells(e_usd, "h12")["B"]
    ok &= check("USD h12 A: fx_income > 0 (купон + тело при погашении)",
                cA["components"]["fx_income"] > 0, str(cA["components"]))
    ok &= check("USD h12 B: fx_income = 0 (usdrub 0%)",
                abs(cB["components"]["fx_income"]) < 1e-9)
    ok &= check("USD h12: купонная база A == B (без FX)",
                abs(cA["components"]["coupons"] - cB["components"]["coupons"]) < 1e-9)
    ok &= check("USD h12: carry A > carry B (рубль слабеет)",
                cA["carry_pct"] > cB["carry_pct"])
    # тело: fx(t_live≈11.9 мес) ≈ 10% × (100/97) ≈ 10.2 в fx_income сверх купонного FX
    ok &= check("USD h12 A: FX тела доминирует (fx_income > 8)",
                cA["components"]["fx_income"] > 8.0, str(cA["components"]["fx_income"]))
    # EUR-прокси
    eur = bond(ticker="EURB", nominal_currency="EUR")
    bc2 = run_for([eur])
    ok &= check("EUR: флаг eur_fx_proxy_usdrub",
                "eur_fx_proxy_usdrub" in bc2["per_position"]["EURB"]["flags"])
    return ok


def test_distressed_override():
    """Distressed (профиль БорецКЗО26: ytm 45.5 > 2×КС, оферта через 19 дн, yto<0):
    наивный carry НЕ применён — все ячейки 0, флаг + HIGH-caveat."""
    print("\n[test_distressed_override]")
    b = bond(ticker="DISTR", ytm_pct=45.5, ytm_to_offer_pct=-3.9,
             offer_date="2026-07-21", maturity_date="2026-12-15", coupon_pct=6.0)
    bc = run_for([b])
    e = bc["per_position"]["DISTR"]
    ok = True
    ok &= check("флаг credit_review_required", "credit_review_required" in e["flags"])
    ok &= check("carry = 0 во всех ячейках",
                all(cells(e, hk)[s]["carry_pct"] == 0
                    for hk in ("h6", "h12", "h24") for s in ("A", "B")))
    ok &= check("expected_carry = 0",
                all(e["by_horizon"][hk]["expected_carry_pct"] == 0
                    for hk in ("h6", "h12", "h24")))
    ok &= check("HIGH-caveat про DISTR",
                any(c["severity"] == "HIGH" and "DISTR" in c["message"]
                    for c in bc["caveats"]))
    ok &= check("reason содержит и причину ytm-порога",
                "2×" in e["credit_review_reason"] or "ytm" in e["credit_review_reason"],
                e["credit_review_reason"])
    # только второй критерий (оферта близко + yto<0), ytm нормальный
    b2 = bond(ticker="DISTR2", ytm_pct=20.0, ytm_to_offer_pct=-1.0,
              offer_date="2026-07-21")
    bc2 = run_for([b2])
    ok &= check("оферта <30 дн + yto<0 → тоже distressed",
                "credit_review_required" in bc2["per_position"]["DISTR2"]["flags"])
    # контроль: ПР-Лиз-профиль (ytm 21.45 < 2×16, оферта далеко) — НЕ distressed
    b3 = bond(ticker="PRLIZ", ytm_pct=21.45, ytm_to_offer_pct=21.2,
              offer_date="2028-02-04", coupon_pct=18.0)
    bc3 = run_for([b3])
    ok &= check("ytm 21.45 при КС 16 — НЕ distressed",
                "credit_review_required" not in bc3["per_position"]["PRLIZ"]["flags"])
    return ok


def test_floater_adjustment():
    """Флоатер (override bond_type=floater): купон корректируется на Δcbr(t):
    в A (КС падает) купонов меньше, чем в B; флаг floater_coupon_adjusted; пол 0."""
    print("\n[test_floater_adjustment]")
    b = bond(ticker="FLOAT", coupon_pct=20.0, ytm_pct=17.0)
    bc = run_for([b], overrides={"FLOAT": {"bond_type": "floater"}})
    e = bc["per_position"]["FLOAT"]
    ok = True
    cA = cells(e, "h24")["A"]["components"]["coupons"]
    cB = cells(e, "h24")["B"]["components"]["coupons"]
    ok &= check("h24: купоны флоатера в A < B (КС падает)", cA < cB, f"A={cA} B={cB}")
    ok &= check("флаг floater_coupon_adjusted",
                "floater_coupon_adjusted" in e["by_horizon"]["h24"]["flags"])
    # пол 0: экстремальное падение ставки не даёт отрицательный купон
    deep = {"A": {"p": 1.0, "factors_by_horizon": {
        "h12": {"cbr_rate": -30.0, "usdrub": 0.0, "sanctions": 0.0}}}}
    snap = {"as_of_date": AS_OF, "holdings": [bond(ticker="FLOAT2", coupon_pct=5.0)],
            "cash": {"total_rub": 0}}
    bc2 = cbc.run({"snapshot": snap, "scenarios": deep, "baseline": BASELINE,
                   "overrides": {"FLOAT2": {"bond_type": "floater"}}})["bond_carry"]
    c = bc2["per_position"]["FLOAT2"]["by_horizon"]["h12"]["by_scenario"]["A"]
    ok &= check("пол 0: купон не уходит в минус", c["components"]["coupons"] >= 0,
                str(c["components"]))
    return ok


def test_floater_plan_subtype_detection():
    """PSS-12/13 (unit): _is_floater — порядок override → snapshot plan_subtype
    == "Флоат" → эвристика имени. Кейс из плана: реальное имя серии ОФЗ-ПК
    «ОФЗ 29014» НЕ содержит «флоатер»/«floater» — до фикса такая бумага
    распознавалась НЕ флоатером, и к ней ошибочно применялись pull-to-par и
    реинвест по сценарной КС вместо коррекции плавающего купона."""
    print("\n[test_floater_plan_subtype_detection]")
    ok = True
    ok &= check(
        "ОФЗ 29014 + plan_subtype=Флоат, без override → floater",
        cbc._is_floater({"name": "ОФЗ 29014", "plan_subtype": "Флоат"}, None) is True)
    ok &= check(
        "та же бумага БЕЗ plan_subtype → старое поведение (НЕ floater, регресс-защита)",
        cbc._is_floater({"name": "ОФЗ 29014"}, None) is False)
    ok &= check(
        "plan_subtype, отличный от «Флоат» (например '>10') → НЕ floater",
        cbc._is_floater({"name": "ОФЗ 26238", "plan_subtype": ">10"}, None) is False)
    ok &= check(
        "явный override.bond_type=floater работает независимо от имени/plan_subtype",
        cbc._is_floater({"name": "ОбычнБО1"}, {"bond_type": "floater"}) is True)
    ok &= check(
        "override с другим bond_type НЕ подавляет plan_subtype=Флоат (не вето, а приоритет)",
        cbc._is_floater({"name": "ОФЗ 29014", "plan_subtype": "Флоат"},
                        {"bond_type": "fixed"}) is True)
    ok &= check(
        "эвристика по имени по-прежнему работает как fallback без plan_subtype/override",
        cbc._is_floater({"name": "Бумага-флоатер"}, None) is True)
    return ok


def test_floater_plan_subtype_carry_effect():
    """PSS-12/13 (интеграция через run_for): ОФЗ 29014 с snapshot plan_subtype
    == "Флоат" и БЕЗ override — carry реально считается флоатером (купон
    корректируется на Δcbr), а не фикс-купоном с pull-to-par/реинвестом."""
    print("\n[test_floater_plan_subtype_carry_effect]")
    b = bond(ticker="OFZ29014", name="ОФЗ 29014", coupon_pct=20.0, ytm_pct=17.0,
             plan_subtype="Флоат")
    bc = run_for([b])
    e = bc["per_position"]["OFZ29014"]
    ok = True
    cA = cells(e, "h24")["A"]["components"]["coupons"]
    cB = cells(e, "h24")["B"]["components"]["coupons"]
    ok &= check("h24: купоны ОФЗ 29014 в A < B (КС падает — плавающий купон)",
                cA < cB, f"A={cA} B={cB}")
    ok &= check("флаг floater_coupon_adjusted",
                "floater_coupon_adjusted" in e["by_horizon"]["h24"]["flags"])
    # Регресс: та же серия, но без plan_subtype в снапшоте — старое поведение.
    b2 = bond(ticker="OFZ29014B", name="ОФЗ 29014", coupon_pct=20.0, ytm_pct=17.0)
    bc2 = run_for([b2])
    e2 = bc2["per_position"]["OFZ29014B"]
    ok &= check("без plan_subtype: флаг floater_coupon_adjusted отсутствует (регресс)",
                "floater_coupon_adjusted" not in e2["by_horizon"]["h24"]["flags"])
    return ok


def test_sanctions_haircut():
    """High-yield (спред > 5 пп) в сценарии sanctions ≥ 1 → компонент
    sanctions_haircut = −25% суммы; в B (sanctions 0) — нет."""
    print("\n[test_sanctions_haircut]")
    b = bond(ticker="HY", ytm_pct=23.0, coupon_pct=18.0)  # спред 7 > 5
    bc = run_for([b])
    e = bc["per_position"]["HY"]
    ok = True
    cA = cells(e, "h12")["A"]
    cB = cells(e, "h12")["B"]
    ok &= check("A: sanctions_haircut присутствует и отрицателен",
                cA["components"].get("sanctions_haircut", 0) < 0, str(cA["components"]))
    ok &= check("A: haircut = −25% от остальных компонент",
                abs(cA["components"]["sanctions_haircut"]
                    + 0.25 * (cA["carry_pct"] - cA["components"]["sanctions_haircut"])) < 1e-4)
    ok &= check("B: haircut отсутствует", "sanctions_haircut" not in cB["components"])
    ok &= check("A: флаг sanctions_haircut_applied",
                "sanctions_haircut_applied" in e["by_horizon"]["h12"]["flags"])
    # не-HY бумага (спред < 5) в A — без haircut
    b2 = bond(ticker="IG", ytm_pct=17.0, coupon_pct=12.0)
    bc2 = run_for([b2])
    ok &= check("IG (спред 1 пп): haircut не применён",
                "sanctions_haircut" not in
                cells(bc2["per_position"]["IG"], "h12")["A"]["components"])
    # выключение параметром
    bc3 = run_for([b], params={"sanctions_haircut": 0.0})
    ok &= check("--sanctions-haircut 0 выключает",
                "sanctions_haircut" not in
                cells(bc3["per_position"]["HY"], "h12")["A"]["components"])
    return ok


def test_mm_and_cash():
    """MM-фонды и голый кэш: carry = (КС-траектория − mm_spread) × H/12;
    в A (КС падает) carry ниже; флаги mm_proxy / cash_carry_assumed_mm."""
    print("\n[test_mm_and_cash]")
    tmon = {"ticker": "TMON", "asset_type": "stock", "is_blocked": False,
            "value_rub": 278810.0}
    bc = run_for([tmon], cash_rub=5346811.83)
    ok = True
    ok &= check("TMON присутствует как money_market",
                bc["per_position"].get("TMON", {}).get("kind") == "money_market")
    ok &= check("CASH_RUB присутствует как cash",
                bc["per_position"].get(cbc.CASH_KEY, {}).get("kind") == "cash")
    e = bc["per_position"]["TMON"]
    cB = cells(e, "h12")["B"]["carry_pct"]
    # B: КС стоит на 16 → (16 − 1) × H/12; H ≈ 11.93 мес → ≈ 14.9%
    ok &= check("TMON h12 B ≈ (16−1)×H/12 (14.5..15.2)", 14.5 < cB < 15.2, str(cB))
    cA = cells(e, "h12")["A"]["carry_pct"]
    ok &= check("TMON h12: A < B (КС падает)", cA < cB, f"A={cA} B={cB}")
    ok &= check("флаг mm_proxy", "mm_proxy" in e["by_horizon"]["h12"]["flags"])
    ok &= check("флаг cash_carry_assumed_mm на кэше",
                "cash_carry_assumed_mm" in bc["per_position"][cbc.CASH_KEY]["flags"])
    ok &= check("MEDIUM-caveat про допущение размещения кэша",
                any("cash_carry_assumed_mm" in c["message"] for c in bc["caveats"]))
    # без кэша — нет CASH_RUB
    bc2 = run_for([tmon], cash_rub=0.0)
    ok &= check("cash_rub = 0 → нет CASH_RUB", cbc.CASH_KEY not in bc2["per_position"])
    return ok


def test_schedule_and_perpetual():
    """Расписание купонов: нет next_coupon_date → estimated-флаг; перпечуал
    (без maturity/offer) — купоны до конца горизонта, без реинвеста."""
    print("\n[test_schedule_and_perpetual]")
    b = bond(ticker="NOSCHED", next_coupon_date=None)
    bc = run_for([b])
    e = bc["per_position"]["NOSCHED"]
    ok = True
    ok &= check("флаг coupon_schedule_estimated",
                "coupon_schedule_estimated" in e["by_horizon"]["h12"]["flags"])
    ok &= check("купоны всё равно посчитаны",
                cells(e, "h12")["B"]["components"]["coupons"] > 0)
    perp = bond(ticker="PERP", maturity_date=None, offer_date=None,
                coupon_freq_per_year=4, next_coupon_date="2026-09-15")
    bc2 = run_for([perp])
    e2 = bc2["per_position"]["PERP"]
    ok &= check("перпечуал: event_date = null", e2["event_date"] is None)
    ok &= check("перпечуал h24: 8 квартальных купонов",
                abs(cells(e2, "h24")["B"]["components"]["coupons"]
                    - 8 * (12.0 / 4) * 100 / 95.0) < 1e-3,
                str(cells(e2, "h24")["B"]["components"]))
    ok &= check("перпечуал: без реинвеста",
                cells(e2, "h24")["B"]["components"]["reinvest"] == 0)
    return ok


def test_expected_and_dedup():
    """expected_carry = p-weighted (нормировка p); дубль main+iis_3 одного
    тикера → одна запись; аддитивность компонент во всех ячейках."""
    print("\n[test_expected_and_dedup]")
    b_main = bond(ticker="DUP", account="main", value_rub=50000.0)
    b_iis = bond(ticker="DUP", account="iis_3", value_rub=30000.0)
    bc = run_for([b_main, b_iis], cash_rub=100000.0)
    ok = True
    ok &= check("main+iis_3 → одна запись DUP",
                sum(1 for k in bc["per_position"] if k == "DUP") == 1)
    e = bc["per_position"]["DUP"]
    exp = e["by_horizon"]["h24"]["expected_carry_pct"]
    manual = 0.5 * cells(e, "h24")["A"]["carry_pct"] + 0.5 * cells(e, "h24")["B"]["carry_pct"]
    ok &= check("expected_carry == Σ p_norm × carry", abs(exp - round(manual, 4)) < 1e-6,
                f"exp={exp} manual={manual}")
    ok &= check("аддитивность компонент во всех ячейках", all_additive(bc))
    ok &= check("HIGH-caveat про немоделируемое (реинвест купонов и т.д.)",
                any(c["severity"] == "HIGH" and "реинвест промежуточных купонов"
                    in c["message"] for c in bc["caveats"]))
    # ненормированные p
    scen = {sid: dict(sc, p=sc["p"] * 2) for sid, sc in SCENARIOS.items()}  # Σp = 2
    snap = {"as_of_date": AS_OF, "holdings": [bond(ticker="PNORM")], "cash": {}}
    bc2 = cbc.run({"snapshot": snap, "scenarios": scen, "baseline": BASELINE,
                   "horizon_ends": HORIZON_ENDS})["bond_carry"]
    e2 = bc2["per_position"]["PNORM"]
    manual2 = 0.5 * (cells(e2, "h12")["A"]["carry_pct"]
                     + cells(e2, "h12")["B"]["carry_pct"])
    ok &= check("Σp=2 нормируется до 1",
                abs(e2["by_horizon"]["h12"]["expected_carry_pct"] - round(manual2, 4)) < 1e-6)
    return ok


def test_errors_and_edge():
    """Fail-fast: нет baseline.cbr_rate_pct / as_of / scenarios; цена отсутствует →
    par + флаг; blocked/zero-value пропускаются."""
    print("\n[test_errors_and_edge]")
    ok = True
    snap = {"as_of_date": AS_OF, "holdings": [bond()], "cash": {}}
    for bad, label in [
        ({"snapshot": snap, "scenarios": SCENARIOS}, "нет baseline → SystemExit"),
        ({"snapshot": {"holdings": [bond()]}, "scenarios": SCENARIOS,
          "baseline": BASELINE}, "нет as_of → SystemExit"),
        ({"snapshot": snap, "baseline": BASELINE}, "нет scenarios → SystemExit"),
    ]:
        try:
            cbc.run(bad)
            ok &= check(label, False, "не упал")
        except SystemExit:
            ok &= check(label, True)
    noprice = bond(ticker="NOPRICE", current_price=None)
    bc = run_for([noprice])
    ok &= check("нет цены → флаг price_missing_assumed_par",
                "price_missing_assumed_par" in bc["per_position"]["NOPRICE"]["flags"])
    blocked = bond(ticker="BLK", is_blocked=True)
    zero = bond(ticker="ZERO", value_rub=0.0)
    bc2 = run_for([blocked, zero, bond(ticker="OKB")])
    ok &= check("blocked/zero-value исключены",
                "BLK" not in bc2["per_position"] and "ZERO" not in bc2["per_position"]
                and "OKB" in bc2["per_position"])
    return ok


def test_no_double_count_with_price_layer():
    """§8.2: для бумаги, гасящейся внутри H, тело НЕ сидит одновременно в двух
    слоях: Слой 1 (compute_per_position, maturity guard) даёт price_delta = 0
    ровно на тех горизонтах, где Слой 2 несёт pull-to-par/реинвест."""
    print("\n[test_no_double_count_with_price_layer]")
    import compute_per_position as cpp
    b = bond(ticker="SHORT", maturity_date="2027-04-01")
    snap = {"as_of_date": AS_OF, "holdings": [b], "cash": {"total_rub": 0}}
    priors = {"SHORT": {"factor_betas": {"cbr_rate": -3.0},
                        "factor_betas_method": "corp-RUB rating-tier A, duration 3yr"}}
    pp, _, _ = cpp.compute_per_position(snap, SCENARIOS, priors, "priors",
                                        horizon_ends=HORIZON_ENDS)
    bc = run_for([b])
    carry_e = bc["per_position"]["SHORT"]
    ok = True
    for hk in ("h6", "h12", "h24"):
        price_slot = pp["SHORT"]["by_horizon"][hk]
        carry_slot = carry_e["by_horizon"][hk]
        if carry_slot["matures_within"]:
            # тело в carry (pull-to-par) → цена обязана быть обнулена
            ok &= check(f"{hk}: price_delta_zeroed при matures_within",
                        price_slot.get("price_delta_zeroed") == "maturity_within_horizon")
            ok &= check(f"{hk}: все price-дельты = 0",
                        all(d["value"] == 0.0
                            for d in price_slot["delta_pct_by_scenario"].values()))
            ok &= check(f"{hk}: pull-to-par в carry > 0",
                        cells(carry_e, hk)["B"]["components"]["pull_to_par"] > 0)
        else:
            # тело в цене (беты живые) → в carry НЕТ pull-to-par/реинвеста
            ok &= check(f"{hk}: price-слой живой (не обнулён)",
                        "price_delta_zeroed" not in price_slot)
            ok &= check(f"{hk}: carry без pull-to-par",
                        cells(carry_e, hk)["B"]["components"]["pull_to_par"] == 0)
        # согласованность t_live между слоями
        if carry_slot["matures_within"]:
            ok &= check(f"{hk}: t_live согласован между слоями (±0.05)",
                        abs(price_slot["t_live_months"] - carry_slot["t_live_months"]) < 0.05,
                        f"price={price_slot.get('t_live_months')} carry={carry_slot['t_live_months']}")
    return ok


def test_factor_path():
    """FactorPath: интерполяция, flat-хвост, средняя (трапеция)."""
    print("\n[test_factor_path]")
    hm = {"h6": 6.0, "h12": 12.0, "h24": 24.0}
    p = cbc.FactorPath(SCENARIOS["A"], "cbr_rate", hm)
    ok = True
    ok &= check("t=0 → 0", p.at(0) == 0.0)
    ok &= check("t=6 → −1", abs(p.at(6) - (-1.0)) < 1e-9)
    ok &= check("t=9 → −1.5 (интерполяция 6..12)", abs(p.at(9) - (-1.5)) < 1e-9)
    ok &= check("t=30 → −4 (flat за 24)", abs(p.at(30) - (-4.0)) < 1e-9)
    # средняя на [12, 24]: линейно от −2 до −4 → −3
    ok &= check("average(12,24) = −3", abs(p.average(12, 24) - (-3.0)) < 1e-9)
    ok &= check("average(a,a) = at(a)", abs(p.average(6, 6) - p.at(6)) < 1e-9)
    return ok


def test_cli_smoke():
    """CLI: JSON-входы → JSON-выход, exit 0 (yaml не требуется для JSON-пути)."""
    print("\n[test_cli_smoke]")
    import json as _json
    import subprocess
    import tempfile
    ok = True
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        (tdp / "snap.json").write_text(_json.dumps(
            {"as_of_date": AS_OF, "holdings": [bond()], "cash": {"total_rub": 0}}),
            encoding="utf-8")
        (tdp / "scen.json").write_text(_json.dumps(
            {"scenarios": SCENARIOS, "horizon_ends": HORIZON_ENDS,
             "baseline_spot": {"cbr_rate_pct": 16.0}}), encoding="utf-8")
        out = tdp / "carry.json"
        proc = subprocess.run(
            [sys.executable,
             str(REPO / "skills/portfolio-scenario-stress/scripts/compute_bond_carry.py"),
             "--snapshot", str(tdp / "snap.json"),
             "--scenarios", str(tdp / "scen.json"),
             "--output", str(out), "--pretty"],
            capture_output=True, text=True)
        ok &= check("exit 0", proc.returncode == 0, proc.stderr[-300:])
        if proc.returncode == 0:
            data = _json.loads(out.read_text(encoding="utf-8"))
            ok &= check("bond_carry.schema = bond-carry@1",
                        data["bond_carry"]["schema"] == "bond-carry@1")
            ok &= check("baseline_cbr взят из scenarios.baseline_spot",
                        data["bond_carry"]["baseline_cbr_rate_pct"] == 16.0)
            ok &= check("TESTBOND в per_position",
                        "TESTBOND" in data["bond_carry"]["per_position"])
    return ok


def test_value_rub_dedup_sums_both_legs():
    """Бумага на main+iis_3: entry['value_rub'] — СУММА обеих ног, не первая
    встреченная (контракт баз расчёта, 2026-09-18)."""
    print("\n[test_value_rub_dedup_sums_both_legs]")
    main_leg = bond(ticker="SPLIT", account="main", value_rub=100000.0)
    iis_leg = bond(ticker="SPLIT", account="iis_3", value_rub=50000.0)
    bc = run_for([main_leg, iis_leg])
    e = bc["per_position"]["SPLIT"]
    return check("value_rub = 100000+50000 = 150000",
                 abs(e["value_rub"] - 150000.0) < 1e-6, str(e["value_rub"]))


def test_portfolio_level_by_horizon_matches_base_value():
    """Единственная позиция, кэша нет → base_value_rub == value_rub позиции →
    портфельный carry_pct должен буквально совпасть с позиционным."""
    print("\n[test_portfolio_level_by_horizon_matches_base_value]")
    b = bond(ticker="SOLO", value_rub=200000.0, maturity_date="2027-04-01")
    bc = run_for([b])
    ok = True
    ok &= check("base_value_rub == value_rub позиции (кэша нет)",
                abs(bc["base_value_rub"] - 200000.0) < 1e-6, str(bc["base_value_rub"]))
    for hk in ("h6", "h12", "h24"):
        for sid in ("A", "B"):
            pos_pct = cells(bc["per_position"]["SOLO"], hk)[sid]["carry_pct"]
            port = bc["portfolio_level_by_horizon"][hk][sid]
            expected_rub = round(200000.0 * pos_pct / 100.0)
            ok &= check(f"{hk}/{sid}: carry_rub = value_rub × carry_pct/100",
                        abs(port["carry_rub"] - expected_rub) <= 1,
                        f"got={port['carry_rub']} ждали={expected_rub}")
            ok &= check(f"{hk}/{sid}: carry_pct портфеля == carry_pct позиции (база совпадает)",
                        abs(port["carry_pct"] - pos_pct) < 1e-3,
                        f"got={port['carry_pct']} ждали={pos_pct}")
    return ok


def test_portfolio_level_by_horizon_sums_across_positions_and_cash():
    """Две позиции + кэш: carry_rub портфеля — сумма вкладов, carry_pct — от
    base_value_rub (Σ позиций + кэш), а не от суммы одних позиций."""
    print("\n[test_portfolio_level_by_horizon_sums_across_positions_and_cash]")
    b1 = bond(ticker="ONE", value_rub=100000.0, maturity_date="2027-04-01")
    b2 = bond(ticker="TWO", value_rub=300000.0, maturity_date="2030-04-01")
    cash = 50000.0
    bc = run_for([b1, b2], cash_rub=cash)
    ok = True
    base = 100000.0 + 300000.0 + cash
    ok &= check("base_value_rub = Σ позиций + кэш", abs(bc["base_value_rub"] - base) < 1e-6)
    for hk in ("h6", "h12", "h24"):
        for sid in ("A", "B"):
            expected_rub = 0.0
            for ticker, val in (("ONE", 100000.0), ("TWO", 300000.0), (cbc.CASH_KEY, cash)):
                pct = cells(bc["per_position"][ticker], hk)[sid]["carry_pct"]
                expected_rub += val * pct / 100.0
            port = bc["portfolio_level_by_horizon"][hk][sid]
            ok &= check(f"{hk}/{sid}: carry_rub = Σ по позициям (+кэш)",
                        abs(port["carry_rub"] - round(expected_rub)) <= 1,
                        f"got={port['carry_rub']} ждали={round(expected_rub)}")
            expected_pct = expected_rub / base * 100.0
            ok &= check(f"{hk}/{sid}: carry_pct = carry_rub/base_value_rub×100",
                        abs(port["carry_pct"] - expected_pct) < 1e-2,
                        f"got={port['carry_pct']} ждали={expected_pct}")
    return ok


def test_distressed_ytm_near_event_skip():
    """Порог ytm пропускается, если событие (погашение/оферта) ближе 30 дн; граница 29/30."""
    print("\n[test_distressed_ytm_near_event_skip]")
    ok = True

    def one(**kw):
        return run_for([bond(ticker="NE", ytm_pct=42.1, coupon_pct=12.0, **kw)])
    bc = one(maturity_date="2026-07-15")  # 13 дн
    e = bc["per_position"]["NE"]
    ok &= check("13 дн: не distressed", "credit_review_required" not in e["flags"])
    ok &= check("13 дн: метка пропуска", "ytm_threshold_skipped_near_event" in e["flags"])
    ok &= check("13 дн: carry ненулевой",
                any(cells(e, hk)[s]["carry_pct"] != 0 for hk in ("h6", "h12") for s in ("A", "B")))
    ok &= check("13 дн: нет HIGH-caveat",
                not any(c["severity"] == "HIGH" and "NE" in c["message"] for c in bc["caveats"]))
    e29 = one(maturity_date="2026-07-31")["per_position"]["NE"]  # 29 дн
    ok &= check("29 дн: пропуск", "ytm_threshold_skipped_near_event" in e29["flags"]
                and "credit_review_required" not in e29["flags"])
    for d, lbl in (("2026-08-01", "30 дн"), ("2027-01-18", "200 дн")):
        ex = one(maturity_date=d)["per_position"]["NE"]
        ok &= check(f"{lbl}: distressed как раньше", "credit_review_required" in ex["flags"]
                    and "ytm_threshold_skipped_near_event" not in ex["flags"])
    eo = one(maturity_date="2031-04-01", offer_date="2026-07-12")["per_position"]["NE"]
    ok &= check("оферта 10 дн: порог пропущен", "ytm_threshold_skipped_near_event" in eo["flags"]
                and "credit_review_required" not in eo["flags"])
    # санкционный haircut: высокодоходной по раздутой доходности бумага у погашения не считается
    ok &= check("13 дн: санкционного haircut нет (сценарий A, sanctions ≥ 1)",
                all("sanctions_haircut" not in cells(e, hk)["A"]["components"] for hk in ("h6", "h12")),
                str(cells(e, "h12")["A"]["components"]))
    far = run_for([bond(ticker="NE", ytm_pct=23.0, coupon_pct=18.0, maturity_date="2031-04-01")])["per_position"]["NE"]
    ok &= check("дальнее погашение, спред 9 пп: haircut есть как раньше",
                cells(far, "h12")["A"]["components"].get("sanctions_haircut", 0) < 0)
    el = run_for([bond(ticker="NE", ytm_pct=14.0, maturity_date="2026-07-15")])["per_position"]["NE"]
    ok &= check("ytm ниже порога: метки нет", "ytm_threshold_skipped_near_event" not in el["flags"])
    # старый файл: params без ключа → 30, ключ попадает в результат
    old = {k: v for k, v in cbc.DEFAULT_PARAMS.items() if k != "distressed_ytm_min_days"}
    bco = run_for([bond(ticker="NE", ytm_pct=42.1, maturity_date="2026-07-15")], params=old)
    ok &= check("params без ключа: значение по умолчанию 30",
                bco["params"]["distressed_ytm_min_days"] == 30
                and "ytm_threshold_skipped_near_event" in bco["per_position"]["NE"]["flags"])
    ok &= check("check_distressed напрямую с params без ключа не падает",
                cbc.check_distressed(bond(ytm_pct=42.1, maturity_date="2026-07-15"), None, 16.0,
                                     cbc._parse_date(AS_OF), old) is None)
    return ok


TESTS = [
    test_short_bond_reinvest,
    test_long_bond_coupons_only,
    test_fx_bond_and_sur_mapping,
    test_distressed_override,
    test_distressed_ytm_near_event_skip,
    test_value_rub_dedup_sums_both_legs,
    test_portfolio_level_by_horizon_matches_base_value,
    test_portfolio_level_by_horizon_sums_across_positions_and_cash,
    test_floater_adjustment,
    test_floater_plan_subtype_detection,
    test_floater_plan_subtype_carry_effect,
    test_sanctions_haircut,
    test_mm_and_cash,
    test_schedule_and_perpetual,
    test_expected_and_dedup,
    test_errors_and_edge,
    test_no_double_count_with_price_layer,
    test_factor_path,
    test_cli_smoke,
]


# ───────────────── PSS-9: горизонтные веса ─────────────────

def _scen_hz():
    """Скаляр и h24-веса различаются СИЛЬНО, чтобы подмена была видна в числах."""
    return {
        "A": {"p": 0.5, "p_by_horizon": {"h6": 0.5, "h24": 0.0},
              "factors_by_horizon": {"h6": {"cbr_rate": 0.0}, "h24": {"cbr_rate": 0.0}}},
        "B": {"p": 0.5, "p_by_horizon": {"h6": 0.5, "h24": 1.0},
              "factors_by_horizon": {"h6": {"cbr_rate": 0.0}, "h24": {"cbr_rate": 0.0}}},
    }


def test_p_norm_without_horizon_unchanged():
    """Прежнее поведение бит-в-бит, когда горизонт не задан."""
    sc = _scen_hz()
    assert cbc._p_norm(sc) == {"A": 0.5, "B": 0.5}
    return True


def test_p_norm_reads_horizon_block():
    sc = _scen_hz()
    assert cbc._p_norm(sc, "h24") == {"A": 0.0, "B": 1.0}
    assert cbc._p_norm(sc, "h6") == {"A": 0.5, "B": 0.5}
    return True


def test_p_norm_partial_block_refused():
    """Смешивать горизонтные веса со скаляром нельзя — расчёт останавливается."""
    sc = _scen_hz(); del sc["A"]["p_by_horizon"]
    try:
        cbc._p_norm(sc, "h24")
    except SystemExit as e:
        return "не у всех" in str(e)
    return False


def test_p_norm_missing_key_refused():
    """Блок есть, но запрошенного горизонта в нём нет у части сценариев."""
    sc = _scen_hz(); del sc["A"]["p_by_horizon"]["h24"]
    try:
        cbc._p_norm(sc, "h24")
    except SystemExit:
        return True
    return False


def test_p_norm_normalises_horizon_block():
    """
    Горизонтные веса НОРМИРУЮТСЯ, а не берутся как есть.

    Дыра покрытия, найденная аудитом 2026-08-05: во всех прежних фикстурах сумма
    `p_by_horizon` по сценариям была ровно 1.0, поэтому деление на неё было
    неотличимо от его отсутствия — мутация «снять `v / total`» выживала. Для
    скаляра такой случай был (Σp = 2 → нормируется), для горизонтов — нет.
    """
    sc = {
        "A": {"p": 0.5, "p_by_horizon": {"h6": 1.5, "h24": 0.0}},
        "B": {"p": 0.5, "p_by_horizon": {"h6": 0.5, "h24": 2.0}},
    }
    got6, got24 = cbc._p_norm(sc, "h6"), cbc._p_norm(sc, "h24")
    ok = True
    ok &= check("Σ=2.0 на h6 нормируется к 0.75/0.25",
                got6 == {"A": 0.75, "B": 0.25}, str(got6))
    ok &= check("Σ=2.0 на h24 нормируется к 0.0/1.0",
                got24 == {"A": 0.0, "B": 1.0}, str(got24))
    ok &= check("сумма нормированных = 1", abs(sum(got6.values()) - 1.0) < 1e-12)
    # Отрицательная сумма — нормировать нечего, расчёт останавливается.
    bad = {"A": {"p": 0.5, "p_by_horizon": {"h6": -1.0}},
           "B": {"p": 0.5, "p_by_horizon": {"h6": 0.0}}}
    try:
        cbc._p_norm(bad, "h6")
        ok &= check("сумма ≤ 0 → отказ", False, "принял неположительную сумму")
    except SystemExit as e:
        ok &= check("сумма ≤ 0 → отказ", "нормировать нечего" in str(e), str(e)[:60])
    return ok


def test_p_norm_unknown_horizon_falls_back_to_scalar():
    """Горизонта нет ни у кого → скаляр, как раньше (не ошибка)."""
    return cbc._p_norm(_scen_hz(), "h99") == {"A": 0.5, "B": 0.5}


def _scen_hz_run():
    """
    Сценарии для прогона через run(): траектории КС РАЗЛИЧАЮТСЯ (иначе carry по
    сценариям совпадёт, и любой набор весов даст одно число — различитель выродится).
    Веса: h6 отдаёт всё A, h24 — всё B, скаляр 0.5/0.5.
    """
    def fbh(cbr6, cbr12, cbr24):
        return {"h6": {"cbr_rate": cbr6}, "h12": {"cbr_rate": cbr12},
                "h24": {"cbr_rate": cbr24}}
    return {
        "A": {"p": 0.5, "p_by_horizon": {"h6": 1.0, "h12": 0.5, "h24": 0.0},
              "factors_by_horizon": fbh(-1.0, -2.0, -4.0)},
        "B": {"p": 0.5, "p_by_horizon": {"h6": 0.0, "h12": 0.5, "h24": 1.0},
              "factors_by_horizon": fbh(0.0, 0.0, 0.0)},
    }


def test_horizon_weights_reach_all_three_consumers_through_run():
    """
    [РАЗЛИЧИТЕЛЬ] Обёртка `p_norm_by_h = {hk: _p_norm(scenarios, hk)}` (run(), ~446)
    реально раздаёт КАЖДОМУ горизонту свои веса — во всех трёх точках потребления:
    облигации (524), money-market (569), голый кэш (589).

    Юнит-тесты бьют по самой функции `_p_norm` и мутацию
    `_p_norm(scenarios, hk)` → `_p_norm(scenarios)` в этой строке переживают:
    функция остаётся корректной, ошибочен вызов. Отсюда прогон через run() и
    сверка с ДВУМЯ моделями — горизонтной (обязана совпасть) и скалярной
    (обязана разойтись).
    """
    print("\n[test_horizon_weights_reach_all_three_consumers_through_run]")
    sc = _scen_hz_run()
    tmon = {"ticker": "TMON", "asset_type": "stock", "is_blocked": False,
            "value_rub": 278810.0}
    # Бумага гасится 2026-10-01 — ВНУТРИ h6: тело реинвестируется по сценарной
    # траектории КС, и carry различается по сценариям на всех трёх горизонтах.
    # Длинная бумага (дефолт 2031) здесь бесполезна: одни купоны, carry в A и B
    # совпадает — любые веса дают одно число, различитель вырождается.
    shortb = bond(ticker="SHORTB", maturity_date="2026-10-01")
    bc = cbc.run({
        "snapshot": {"as_of_date": AS_OF, "holdings": [shortb, tmon],
                     "cash": {"total_rub": 1_500_000.0}},
        "scenarios": sc, "baseline": BASELINE, "horizon_ends": HORIZON_ENDS,
    })["bond_carry"]

    ok = True
    for key in ("SHORTB", "TMON", cbc.CASH_KEY):
        entry = bc["per_position"][key]
        for hk, w in (("h6", {"A": 1.0, "B": 0.0}), ("h24", {"A": 0.0, "B": 1.0})):
            cs = cells(entry, hk)
            by_horizon_w = sum(w[s] * cs[s]["carry_pct"] for s in cs)
            by_scalar_w = sum(0.5 * cs[s]["carry_pct"] for s in cs)
            got = entry["by_horizon"][hk]["expected_carry_pct"]
            ok &= check(f"{key} {hk}: expected по горизонтным весам",
                        abs(got - by_horizon_w) < 1e-3,
                        f"got={got} ждали={by_horizon_w}")
            # Различитель имеет смысл, только если модели реально расходятся.
            ok &= check(f"{key} {hk}: скалярная модель отличима",
                        abs(by_horizon_w - by_scalar_w) > 0.05,
                        f"гориз={by_horizon_w} скаляр={by_scalar_w}")
            ok &= check(f"{key} {hk}: expected НЕ по скаляру",
                        abs(got - by_scalar_w) > 0.05,
                        f"got={got} скаляр={by_scalar_w}")
    return ok


def test_without_horizon_block_run_unchanged():
    """Обратная совместимость: без p_by_horizon expected — прежний скалярный."""
    print("\n[test_without_horizon_block_run_unchanged]")
    sc = _scen_hz_run()
    for node in sc.values():
        del node["p_by_horizon"]
    bc = cbc.run({
        "snapshot": {"as_of_date": AS_OF,
                     "holdings": [bond(ticker="SHORTB", maturity_date="2026-10-01")],
                     "cash": {"total_rub": 0.0}},
        "scenarios": sc, "baseline": BASELINE, "horizon_ends": HORIZON_ENDS,
    })["bond_carry"]
    ok = True
    for hk in ("h6", "h12", "h24"):
        cs = cells(bc["per_position"]["SHORTB"], hk)
        want = sum(0.5 * cs[s]["carry_pct"] for s in cs)
        got = bc["per_position"]["SHORTB"]["by_horizon"][hk]["expected_carry_pct"]
        ok &= check(f"h={hk}: скалярное взвешивание", abs(got - want) < 1e-3,
                    f"got={got} ждали={want}")
    return ok


TESTS += [test_p_norm_without_horizon_unchanged, test_p_norm_reads_horizon_block,
          test_p_norm_partial_block_refused, test_p_norm_missing_key_refused,
          test_p_norm_unknown_horizon_falls_back_to_scalar,
          test_p_norm_normalises_horizon_block,
          test_horizon_weights_reach_all_three_consumers_through_run,
          test_without_horizon_block_run_unchanged]


def main() -> int:
    passed = failed = 0
    for t in TESTS:
        try:
            ok = t()
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  ✗ {t.__name__}: {type(e).__name__}: {e}")
            ok = False
        passed += ok
        failed += not ok
    print(f"\n{'=' * 50}\nPassed: {passed}/{len(TESTS)}; Failed: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
