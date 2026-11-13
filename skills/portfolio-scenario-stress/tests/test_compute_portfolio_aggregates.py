#!/usr/bin/env python3
"""Тесты для compute_portfolio_aggregates.py (контракт баз расчёта, 2026-09-18).

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 \
        skills/portfolio-scenario-stress/tests/test_compute_portfolio_aggregates.py

Фикстура (2 позиции × 2 сценария × 2 горизонта) идентична valid_fixture() из
test_basis_contract.py — числа сверены вручную один раз, здесь переиспользуются,
чтобы проверить: (а) агрегатор считает их так же, как валидатор их проверяет;
(б) полный собранный документ (top-level контракт + scenarios из агрегатора +
per_position + portfolio_aggregates/robustness из агрегатора) проходит
validate_stress_output.validate() с 0 блокеров — доказательство, что при
единой формуле пересчёт руками не нужен.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "skills/portfolio-scenario-stress/scripts"))

import compute_portfolio_aggregates as cpa  # noqa: E402
import validate_stress_output as v  # noqa: E402


def check(label: str, cond: bool, detail: str = "") -> bool:
    if cond:
        print(f"  ✓ {label}")
        return True
    print(f"  ✗ {label}{(' — ' + detail) if detail else ''}")
    return False


def snapshot() -> dict:
    return {
        "holdings": [
            {"ticker": "TICK1", "value_rub": 600000.0, "is_blocked": False},
            {"ticker": "TICK2", "value_rub": 400000.0, "is_blocked": False},
        ],
        "cash": {"total_rub": 0.0},
    }


def scenarios() -> dict:
    return {"A": {"p": 0.5}, "B": {"p": 0.5}}


def per_position() -> dict:
    return {
        "TICK1": {"weight_pct": 60, "by_horizon": {
            "h6": {"delta_pct_by_scenario": {"A": -10.0, "B": 8.0}},
            "h12": {"delta_pct_by_scenario": {"A": -20.0, "B": 15.0}},
        }},
        "TICK2": {"weight_pct": 40, "by_horizon": {
            "h6": {"delta_pct_by_scenario": {"A": 5.0, "B": -2.0}},
            "h12": {"delta_pct_by_scenario": {"A": 10.0, "B": -5.0}},
        }},
    }


def bond_carry() -> dict:
    return {"portfolio_level_by_horizon": {
        "h6": {"A": {"carry_rub": 5000}, "B": {"carry_rub": 3000}},
        "h12": {"A": {"carry_rub": 10000}, "B": {"carry_rub": 6000}},
    }}


def test_bottom_up_matches_manual_arithmetic() -> bool:
    print("\n[test_bottom_up_matches_manual_arithmetic]")
    result = cpa.compute(snapshot(), scenarios(), per_position(), bond_carry(),
                         weight_type="probability", include_ev=True)
    plbh = result["scenarios"]
    ok = True
    expected = {
        ("A", "h6"): {"price_delta_rub": -40000, "carry_rub": 5000, "total_return_rub": -35000},
        ("A", "h12"): {"price_delta_rub": -80000, "carry_rub": 10000, "total_return_rub": -70000},
        ("B", "h6"): {"price_delta_rub": 40000, "carry_rub": 3000, "total_return_rub": 43000},
        ("B", "h12"): {"price_delta_rub": 70000, "carry_rub": 6000, "total_return_rub": 76000},
    }
    for (sid, hk), exp in expected.items():
        cell = plbh[sid]["portfolio_level_by_horizon"][hk]
        for field, want in exp.items():
            ok &= check(f"{sid}/{hk}.{field} == {want}", cell[field] == want,
                        f"got={cell[field]}")
    return ok


def test_expected_value_weighted_and_range() -> bool:
    print("\n[test_expected_value_weighted_and_range]")
    result = cpa.compute(snapshot(), scenarios(), per_position(), bond_carry(),
                         weight_type="probability", include_ev=True)
    agg = result["portfolio_aggregates"]
    ok = True
    ok &= check("price.expected_pl_rub_by_horizon.h6 == 0 (0.5×-40000+0.5×40000)",
                agg["price"]["expected_pl_rub_by_horizon"]["h6"] == 0)
    ok &= check("price.expected_pl_rub_by_horizon.h12 == -5000",
                agg["price"]["expected_pl_rub_by_horizon"]["h12"] == -5000)
    ok &= check("total_return.expected_pl_rub_by_horizon.h6 == 4000",
                agg["total_return"]["expected_pl_rub_by_horizon"]["h6"] == 4000)
    r = agg["price"]["pl_range_rub_by_horizon"]["h6"]
    ok &= check("price range h6: min=-40000(A) max=40000(B)",
                r == {"min": -40000, "max": 40000, "min_scenario": "A", "max_scenario": "B"},
                str(r))
    return ok


def test_ev_null_without_include_ev() -> bool:
    print("\n[test_ev_null_without_include_ev]")
    result = cpa.compute(snapshot(), scenarios(), per_position(), bond_carry(),
                         weight_type="equal", include_ev=False)
    agg = result["portfolio_aggregates"]
    ok = True
    for basis in ("price", "total_return"):
        for hk in ("h6", "h12"):
            ok &= check(f"{basis}.expected_pl_rub_by_horizon.{hk} is None (equal-weighted, D2)",
                        agg[basis]["expected_pl_rub_by_horizon"][hk] is None)
    ok &= check("robustness.modal_scenario == none (equal-weighted, правило 5a)",
                result["robustness"]["modal_scenario"] == "none")
    # Диапазон и robustness НЕ зависят от include_ev — считаются всегда.
    ok &= check("pl_range всё равно посчитан",
                result["portfolio_aggregates"]["price"]["pl_range_rub_by_horizon"]["h6"]["max"] == 40000)
    return ok


def test_no_bond_carry_zeroes_layer2() -> bool:
    print("\n[test_no_bond_carry_zeroes_layer2]")
    result = cpa.compute(snapshot(), scenarios(), per_position(), None,
                         weight_type="equal", include_ev=False)
    cell = result["scenarios"]["A"]["portfolio_level_by_horizon"]["h6"]
    return check("без bond_carry: carry_rub=0, total_return_rub==price_delta_rub",
                 cell["carry_rub"] == 0 and cell["total_return_rub"] == cell["price_delta_rub"],
                 str(cell))


def test_weight_pct_base_excludes_cash() -> bool:
    """Регрессия (2026-09-18): weight_pct нормирован БЕЗ кэша
    (compute_per_position.compute_total_value), а base_value_rub — С кэшем
    (§1.1 контракта). Смешать их — систематически завысить price_delta_rub на
    долю кэша. Портфель: TICK1=600000, TICK2=300000 (Σ=900000, БЕЗ кэша),
    cash=100000 → base_value_rub=1000000."""
    print("\n[test_weight_pct_base_excludes_cash]")
    snap = {
        "holdings": [
            {"ticker": "TICK1", "value_rub": 600000.0, "is_blocked": False},
            {"ticker": "TICK2", "value_rub": 300000.0, "is_blocked": False},
        ],
        "cash": {"total_rub": 100000.0},
    }
    pos = {
        "TICK1": {"weight_pct": 600000.0 / 900000.0 * 100, "by_horizon": {
            "h6": {"delta_pct_by_scenario": {"A": -10.0, "B": 8.0}}}},
        "TICK2": {"weight_pct": 300000.0 / 900000.0 * 100, "by_horizon": {
            "h6": {"delta_pct_by_scenario": {"A": 5.0, "B": -2.0}}}},
    }
    result = cpa.compute(snap, {"A": {"p": 0.5}, "B": {"p": 0.5}}, pos, None,
                         weight_type="equal", include_ev=False)
    cell = result["scenarios"]["A"]["portfolio_level_by_horizon"]["h6"]
    # Правильно: Σ weight_pct/100 × positions_value_rub(=900000) × delta/100
    #   = 0.666667×900000×-0.10 + 0.333333×900000×0.05 = -60000+15000 = -45000
    # Ошибочно (домножить на base_value_rub=1000000): -50000
    ok = True
    ok &= check("price_delta_rub = -45000 (множитель — БЕЗ кэша, 900000)",
                abs(cell["price_delta_rub"] - (-45000)) <= 1, str(cell["price_delta_rub"]))
    ok &= check("price_delta_rub != -50000 (не завышено множителем С кэшем)",
                abs(cell["price_delta_rub"] - (-50000)) > 100, str(cell["price_delta_rub"]))
    ok &= check("price_delta_pct = -4.5 (от base_value_rub=1000000, С кэшем — знаменатель процентов)",
                abs(cell["price_delta_pct"] - (-4.5)) < 1e-6, str(cell["price_delta_pct"]))
    return ok


def test_full_document_passes_validator() -> bool:
    """Интеграционный тест: собранный документ (контракт + agregator + per_position)
    проходит validate_stress_output.validate() с 0 блокеров."""
    print("\n[test_full_document_passes_validator]")
    result = cpa.compute(snapshot(), scenarios(), per_position(), bond_carry(),
                         weight_type="probability", include_ev=True)
    doc = {
        "schema_version": 2,
        "type": "portfolio-stress-test",
        "basis_contract": 1,
        "layers_included": {"price": True, "bond_carry": True, "dividends": False},
        "per_position_basis": "price",
        "base_value_rub": 1_000_000,
        "base_value_note": "test",
        "p_basis": "primary_horizon",
        "horizons": [6, 12],
        "unmapped_tickers": [],
        "scenarios": {
            sid: {"p": scenarios()[sid]["p"],
                 "factors_by_horizon": {"h6": {"brent": 1.0 if sid == "A" else -1.0},
                                        "h12": {"brent": 2.0 if sid == "A" else -2.0}},
                 **result["scenarios"][sid]}
            for sid in scenarios()
        },
        "portfolio_aggregates": result["portfolio_aggregates"],
        "robustness": {**result["robustness"], "hedge_target": "A"},
        "per_position": per_position(),
    }
    issues = v.validate(doc)
    return check("0 блокеров на документе, собранном из фрагментов",
                 issues == [], f"issues={issues}")


TESTS = [
    test_bottom_up_matches_manual_arithmetic,
    test_expected_value_weighted_and_range,
    test_ev_null_without_include_ev,
    test_no_bond_carry_zeroes_layer2,
    test_weight_pct_base_excludes_cash,
    test_full_document_passes_validator,
]


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
