#!/usr/bin/env python3
"""Тесты для validate_stress_output.py (контракт баз расчёта, basis_contract).

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 \
        skills/portfolio-scenario-stress/tests/test_basis_contract.py

Синтетические фикстуры, stdlib only (валидатор работает с dict напрямую,
без сериализации в YAML). Полная спека — docs/investment/task-stress-basis-contract.md,
контракт полей — _shared-references/yaml-schemas.md §11.2a.

Синтетический корректный файл (2 сценария × 2 горизонта, самосогласованный по
всем инвариантам) проходит валидатор с exit 0. Каждая мутация из §4.3 задачи
обязана дать exit 1 с конкретным кодом среди сообщённых блокеров — тест не
требует, чтобы мутация давала РОВНО один код: числовая правка каскадно ломает
несколько производных сверок одновременно, это ожидаемо для
cross-consistency валидатора.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "skills/portfolio-scenario-stress/scripts"))

import validate_stress_output as v  # noqa: E402


def check(label: str, cond: bool, detail: str = "") -> bool:
    if cond:
        print(f"  ✓ {label}")
        return True
    print(f"  ✗ {label}{(' — ' + detail) if detail else ''}")
    return False


def valid_fixture() -> dict:
    """Самосогласованный синтетический артефакт: 2 сценария (A/B) × 2 горизонта
    (h6/h12), base_value_rub = 1 000 000, 2 позиции (TICK1 60%, TICK2 40%)."""
    return {
        "schema_version": 2,
        "type": "portfolio-stress-test",
        "basis_contract": 1,
        "layers_included": {"price": True, "bond_carry": True, "dividends": False},
        "per_position_basis": "price",
        "base_value_rub": 1_000_000,
        "base_value_note": "test fixture",
        "p_basis": "primary_horizon",
        "horizons": [6, 12],
        "unmapped_tickers": [],
        "scenarios": {
            "A": {
                "p": 0.5,
                "factors_by_horizon": {
                    "h6": {"brent": -10, "cbr_rate": 1.0},
                    "h12": {"brent": -20, "cbr_rate": 0.5},
                },
                "portfolio_level_by_horizon": {
                    "h6": {"price_delta_rub": -40000, "price_delta_pct": -4.0,
                           "carry_rub": 5000, "carry_pct": 0.5,
                           "total_return_rub": -35000, "total_return_pct": -3.5},
                    "h12": {"price_delta_rub": -80000, "price_delta_pct": -8.0,
                            "carry_rub": 10000, "carry_pct": 1.0,
                            "total_return_rub": -70000, "total_return_pct": -7.0},
                },
            },
            "B": {
                "p": 0.5,
                "factors_by_horizon": {
                    "h6": {"brent": 10, "cbr_rate": -1.0},
                    "h12": {"brent": 20, "cbr_rate": -0.5},
                },
                "portfolio_level_by_horizon": {
                    "h6": {"price_delta_rub": 40000, "price_delta_pct": 4.0,
                           "carry_rub": 3000, "carry_pct": 0.3,
                           "total_return_rub": 43000, "total_return_pct": 4.3},
                    "h12": {"price_delta_rub": 70000, "price_delta_pct": 7.0,
                            "carry_rub": 6000, "carry_pct": 0.6,
                            "total_return_rub": 76000, "total_return_pct": 7.6},
                },
            },
        },
        "portfolio_aggregates": {
            "price": {
                "basis": "price",
                "expected_pl_rub_by_horizon": {"h6": 0, "h12": -5000},
                "expected_pl_pct_by_horizon": {"h6": 0.0, "h12": -0.5},
                "pl_range_rub_by_horizon": {
                    "h6": {"min": -40000, "max": 40000, "min_scenario": "A", "max_scenario": "B"},
                    "h12": {"min": -80000, "max": 70000, "min_scenario": "A", "max_scenario": "B"},
                },
            },
            "total_return": {
                "basis": "total_return",
                "expected_pl_rub_by_horizon": {"h6": 4000, "h12": 3000},
                "expected_pl_pct_by_horizon": {"h6": 0.4, "h12": 0.3},
                "pl_range_rub_by_horizon": {
                    "h6": {"min": -35000, "max": 43000, "min_scenario": "A", "max_scenario": "B"},
                    "h12": {"min": -70000, "max": 76000, "min_scenario": "A", "max_scenario": "B"},
                },
            },
        },
        "robustness": {
            "price": {"basis": "price", "by_horizon": {
                "h6": {"positive_or_neutral_scenarios": 1,
                       "worst_case": {"id": "A", "pl_pct": -4.0},
                       "best_case": {"id": "B", "pl_pct": 4.0}, "spread_pct": 8.0},
                "h12": {"positive_or_neutral_scenarios": 1,
                        "worst_case": {"id": "A", "pl_pct": -8.0},
                        "best_case": {"id": "B", "pl_pct": 7.0}, "spread_pct": 15.0},
            }},
            "total_return": {"basis": "total_return", "by_horizon": {
                "h6": {"positive_or_neutral_scenarios": 1,
                       "worst_case": {"id": "A", "pl_pct": -3.5},
                       "best_case": {"id": "B", "pl_pct": 4.3}, "spread_pct": 7.8},
                "h12": {"positive_or_neutral_scenarios": 1,
                        "worst_case": {"id": "A", "pl_pct": -7.0},
                        "best_case": {"id": "B", "pl_pct": 7.6}, "spread_pct": 14.6},
            }},
            "modal_scenario": "none",
            "hedge_target": "A",
        },
        "per_position": {
            "TICK1": {"weight_pct": 60, "by_horizon": {
                "h6": {"delta_pct_by_scenario": {"A": -10.0, "B": 8.0}},
                "h12": {"delta_pct_by_scenario": {"A": -20.0, "B": 15.0}},
            }},
            "TICK2": {"weight_pct": 40, "by_horizon": {
                "h6": {"delta_pct_by_scenario": {"A": 5.0, "B": -2.0}},
                "h12": {"delta_pct_by_scenario": {"A": 10.0, "B": -5.0}},
            }},
        },
    }


def valid_fixture_with_cash() -> tuple[dict, dict]:
    """Как valid_fixture(), но с кэшем: positions_value_rub=900000 (TICK1/TICK2,
    веса 60/40 те же — weight_pct нормирован БЕЗ кэша), cash=100000,
    base_value_rub=1000000 (С кэшем — знаменатель процентов). Регрессия
    2026-09-18: бэктолл price_delta_rub обязан множить weight_pct на 900000,
    НЕ на 1000000 — иначе систематическое завышение на долю кэша.
    Возвращает (stress_doc, snapshot)."""
    snapshot = {
        "holdings": [
            {"ticker": "TICK1", "value_rub": 540000.0, "is_blocked": False},
            {"ticker": "TICK2", "value_rub": 360000.0, "is_blocked": False},
        ],
        "cash": {"total_rub": 100000.0},
    }
    doc = {
        "schema_version": 2,
        "type": "portfolio-stress-test",
        "basis_contract": 1,
        "layers_included": {"price": True, "bond_carry": True, "dividends": False},
        "per_position_basis": "price",
        "base_value_rub": 1_000_000,
        "base_value_note": "test fixture with cash",
        "p_basis": "primary_horizon",
        "cash_rub_pct": 10.0,
        "blocked_pct": 0.0,
        "horizons": [6, 12],
        "unmapped_tickers": [],
        "scenarios": {
            "A": {
                "p": 0.5,
                "factors_by_horizon": {"h6": {"brent": -10}, "h12": {"brent": -20}},
                "portfolio_level_by_horizon": {
                    "h6": {"price_delta_rub": -36000, "price_delta_pct": -3.6,
                           "carry_rub": 5000, "carry_pct": 0.5,
                           "total_return_rub": -31000, "total_return_pct": -3.1},
                    "h12": {"price_delta_rub": -72000, "price_delta_pct": -7.2,
                            "carry_rub": 10000, "carry_pct": 1.0,
                            "total_return_rub": -62000, "total_return_pct": -6.2},
                },
            },
            "B": {
                "p": 0.5,
                "factors_by_horizon": {"h6": {"brent": 10}, "h12": {"brent": 20}},
                "portfolio_level_by_horizon": {
                    "h6": {"price_delta_rub": 36000, "price_delta_pct": 3.6,
                           "carry_rub": 3000, "carry_pct": 0.3,
                           "total_return_rub": 39000, "total_return_pct": 3.9},
                    "h12": {"price_delta_rub": 63000, "price_delta_pct": 6.3,
                            "carry_rub": 6000, "carry_pct": 0.6,
                            "total_return_rub": 69000, "total_return_pct": 6.9},
                },
            },
        },
        "portfolio_aggregates": {
            "price": {"basis": "price",
                "expected_pl_rub_by_horizon": {"h6": 0, "h12": -4500},
                "expected_pl_pct_by_horizon": {"h6": 0.0, "h12": -0.45},
                "pl_range_rub_by_horizon": {
                    "h6": {"min": -36000, "max": 36000, "min_scenario": "A", "max_scenario": "B"},
                    "h12": {"min": -72000, "max": 63000, "min_scenario": "A", "max_scenario": "B"}}},
            "total_return": {"basis": "total_return",
                "expected_pl_rub_by_horizon": {"h6": 4000, "h12": 3500},
                "expected_pl_pct_by_horizon": {"h6": 0.4, "h12": 0.35},
                "pl_range_rub_by_horizon": {
                    "h6": {"min": -31000, "max": 39000, "min_scenario": "A", "max_scenario": "B"},
                    "h12": {"min": -62000, "max": 69000, "min_scenario": "A", "max_scenario": "B"}}},
        },
        "robustness": {
            "price": {"basis": "price", "by_horizon": {
                "h6": {"positive_or_neutral_scenarios": 1,
                       "worst_case": {"id": "A", "pl_pct": -3.6},
                       "best_case": {"id": "B", "pl_pct": 3.6}, "spread_pct": 7.2},
                "h12": {"positive_or_neutral_scenarios": 1,
                        "worst_case": {"id": "A", "pl_pct": -7.2},
                        "best_case": {"id": "B", "pl_pct": 6.3}, "spread_pct": 13.5}}},
            "total_return": {"basis": "total_return", "by_horizon": {
                "h6": {"positive_or_neutral_scenarios": 1,
                       "worst_case": {"id": "A", "pl_pct": -3.1},
                       "best_case": {"id": "B", "pl_pct": 3.9}, "spread_pct": 7.0},
                "h12": {"positive_or_neutral_scenarios": 1,
                        "worst_case": {"id": "A", "pl_pct": -6.2},
                        "best_case": {"id": "B", "pl_pct": 6.9}, "spread_pct": 13.1}}},
            "modal_scenario": "none",
            "hedge_target": "A",
        },
        "per_position": {
            "TICK1": {"weight_pct": 540000.0 / 900000.0 * 100, "by_horizon": {
                "h6": {"delta_pct_by_scenario": {"A": -10.0, "B": 8.0}},
                "h12": {"delta_pct_by_scenario": {"A": -20.0, "B": 15.0}},
            }},
            "TICK2": {"weight_pct": 360000.0 / 900000.0 * 100, "by_horizon": {
                "h6": {"delta_pct_by_scenario": {"A": 5.0, "B": -2.0}},
                "h12": {"delta_pct_by_scenario": {"A": 10.0, "B": -5.0}},
            }},
        },
    }
    return doc, snapshot


def test_bottom_up_with_cash_using_snapshot() -> bool:
    """Регрессия 2026-09-18: со снапшотом positions_value_rub считается точно
    (900000, без кэша) — 0 блокеров, включая 3.7."""
    print("\n[test_bottom_up_with_cash_using_snapshot]")
    doc, snapshot = valid_fixture_with_cash()
    issues = v.validate(doc, snapshot)
    return check("портфель с кэшем + снапшот → 0 блокеров",
                 issues == [], f"issues={issues}")


def test_bottom_up_with_cash_without_snapshot_approximation() -> bool:
    """Без снапшота — приближение через cash_rub_pct/blocked_pct top-level
    (уже существующие поля, не из этого контракта); при cash_rub_pct=10.0
    точно совпадает с истинным positions_value_rub=900000."""
    print("\n[test_bottom_up_with_cash_without_snapshot_approximation]")
    doc, _ = valid_fixture_with_cash()
    issues = v.validate(doc)
    return check("портфель с кэшем БЕЗ снапшота (приближение cash_rub_pct) → 0 блокеров",
                 issues == [], f"issues={issues}")


def codes(issues: list[dict]) -> set[str]:
    return {i["code"] for i in issues}


def test_valid_fixture_passes() -> bool:
    print("\n[test_valid_fixture_passes]")
    data = valid_fixture()
    issues = v.validate(data)
    return check("синтетический корректный файл → 0 блокеров",
                  issues == [], f"issues={issues}")


def test_mutation_layer_identity_broken() -> bool:
    print("\n[test_mutation_layer_identity_broken]")
    data = valid_fixture()
    cell = data["scenarios"]["A"]["portfolio_level_by_horizon"]["h6"]
    cell["total_return_rub"] = -30000
    cell["total_return_pct"] = -3.0  # внутренне согласовано с _rub, ломает только 3.6
    issues = v.validate(data)
    return check("тождество total=price+carry сломано → код 3.6",
                  "3.6" in codes(issues), f"codes={codes(issues)}")


def test_mutation_probability_sum_not_one() -> bool:
    print("\n[test_mutation_probability_sum_not_one]")
    data = valid_fixture()
    data["scenarios"]["B"]["p"] = 0.6
    issues = v.validate(data)
    return check("Σp ≠ 1 → код 3.8",
                  "3.8" in codes(issues), f"codes={codes(issues)}")


def test_mutation_robustness_wrong_basis_numbers() -> bool:
    print("\n[test_mutation_robustness_wrong_basis_numbers]")
    data = valid_fixture()
    # Подменяем robustness.price числами из total_return того же горизонта.
    data["robustness"]["price"]["by_horizon"]["h6"] = {
        "positive_or_neutral_scenarios": 1,
        "worst_case": {"id": "A", "pl_pct": -3.5},
        "best_case": {"id": "B", "pl_pct": 4.3},
        "spread_pct": 7.8,
    }
    issues = v.validate(data)
    return check("robustness.price посчитан на числах total_return → код 3.11",
                  "3.11" in codes(issues), f"codes={codes(issues)}")


def test_mutation_delta_rub_drift_rename() -> bool:
    print("\n[test_mutation_delta_rub_drift_rename]")
    data = valid_fixture()
    cell = data["scenarios"]["A"]["portfolio_level_by_horizon"]["h6"]
    cell["delta_rub"] = cell.pop("price_delta_rub")
    issues = v.validate(data)
    return check("price_delta_rub переименован обратно в delta_rub → код 3.2",
                  "3.2" in codes(issues), f"codes={codes(issues)}")


def test_mutation_per_position_carry_key() -> bool:
    print("\n[test_mutation_per_position_carry_key]")
    data = valid_fixture()
    data["per_position"]["TICK1"]["by_horizon"]["h6"]["carry_rub"] = 100
    issues = v.validate(data)
    return check("per_position с ключом carry_rub → код 3.5",
                  "3.5" in codes(issues), f"codes={codes(issues)}")


def test_mutation_horizon_collision() -> bool:
    print("\n[test_mutation_horizon_collision]")
    data = valid_fixture()
    data["scenarios"]["A"]["factors_by_horizon"]["h12"] = \
        copy.deepcopy(data["scenarios"]["A"]["factors_by_horizon"]["h6"])
    issues = v.validate(data)
    return check("два горизонта с одинаковыми факторами → код 3.9",
                  "3.9" in codes(issues), f"codes={codes(issues)}")


def test_mutation_expected_pl_not_weighted_sum() -> bool:
    print("\n[test_mutation_expected_pl_not_weighted_sum]")
    data = valid_fixture()
    data["portfolio_aggregates"]["price"]["expected_pl_rub_by_horizon"]["h6"] = 999
    issues = v.validate(data)
    return check("expected_pl_rub ≠ взвешенная сумма → код 3.8",
                  "3.8" in codes(issues), f"codes={codes(issues)}")


def test_mutation_bottom_up_mismatch() -> bool:
    print("\n[test_mutation_bottom_up_mismatch]")
    data = valid_fixture()
    # price_delta_rub перестаёт сходиться с суммой по позициям снизу вверх.
    data["scenarios"]["A"]["portfolio_level_by_horizon"]["h6"]["price_delta_rub"] = -200000
    issues = v.validate(data)
    return check("портфельный price_delta_rub не сходится с per_position → код 3.7",
                  "3.7" in codes(issues), f"codes={codes(issues)}")


def test_mutation_missing_dividends_false() -> bool:
    print("\n[test_mutation_missing_dividends_false]")
    data = valid_fixture()
    data["layers_included"]["dividends"] = True
    issues = v.validate(data)
    return check("layers_included.dividends != false → код 3.1",
                  "3.1" in codes(issues), f"codes={codes(issues)}")


TESTS = [
    test_valid_fixture_passes,
    test_bottom_up_with_cash_using_snapshot,
    test_bottom_up_with_cash_without_snapshot_approximation,
    test_mutation_layer_identity_broken,
    test_mutation_probability_sum_not_one,
    test_mutation_robustness_wrong_basis_numbers,
    test_mutation_delta_rub_drift_rename,
    test_mutation_per_position_carry_key,
    test_mutation_horizon_collision,
    test_mutation_expected_pl_not_weighted_sum,
    test_mutation_bottom_up_mismatch,
    test_mutation_missing_dividends_false,
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
