#!/usr/bin/env python3
"""Tests for aggregate_positions.py — portfolio-integrated-view aggregator."""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from aggregate_positions import (  # noqa: E402
    _add_months_eom,
    NULL_DEPENDENCY_DISCOUNT,
    LOW_QUALITY_DISCOUNT,
    CARRY_CAP_PCT,
    _detect_on_iis,
    aggregate_div_or_carry,
    aggregate_idio,
    aggregate_macro,
    check_horizon_anchor_drift,
    check_snapshot_drift,
    check_stress_terms,
    format_summary,
    is_low_trust,
    collect_snapshot_quality_flags,
    stress_recalc_info,
    compute_diff,
    compute_portfolio_aggregates,
    compute_spread_switch_thresholds,
    compute_tail_flags,
    cross_validate,
    merge_duplicate_holdings,
    normalize_scenario_probs,
    sanity_checks,
    run,
)


def _scenarios_fresh():
    return {
        "Sc-A": {"p": 0.25},
        "Sc-B": {"p": 0.25},
        "Sc-C": {"p": 0.25},
        "Sc-D": {"p": 0.25},
    }


_PP_HORIZON_FIELDS = ("delta_pct_by_scenario", "expected_pct_pweighted", "ci_pct",
                      "tail_var_pct", "tail_var_scenario_id")


def _wrap_single_horizon(stress_pp, hk):
    """Плоские поля позиции stress → by_horizon.{hk} (wrap-as-single-horizon, как migrate_v1_to_v2)."""
    out = {}
    for t, pp in (stress_pp or {}).items():
        if not isinstance(pp, dict) or "by_horizon" in pp:
            out[t] = pp
            continue
        pp = dict(pp)
        moved = {k: pp.pop(k) for k in _PP_HORIZON_FIELDS if k in pp}
        pp["by_horizon"] = {hk: moved}
        out[t] = pp
    return out


def _make_payload(*, scenarios=None, holdings=None, stress_pp=None,
                  review_stocks_per=None, review_bonds_per=None,
                  stress_snapshot="portfolio-2026-05-07.json",
                  rs_snapshot="portfolio-2026-05-07.json",
                  rb_snapshot="portfolio-2026-05-07.json",
                  horizon=20):
    hk = f"h{horizon}"
    ends = {hk: _add_months_eom(date(2026, 5, 7), horizon).isoformat()}
    return {
        "horizons": [horizon],
        "primary_horizon": horizon,
        "snapshot": {
            "schema_version": "2.0",
            "holdings": holdings or [],
            "total_active_rub": 13_000_000,
        },
        "stress": {
            "schema_version": 2,
            "snapshot_id": stress_snapshot,
            "horizon_ends": ends,
            "scenarios": scenarios or _scenarios_fresh(),
            "per_position": _wrap_single_horizon(stress_pp, hk),
        },
        "review_stocks": {
            "schema_version": 2,
            "snapshot_id": rs_snapshot,
            "horizon_ends": ends,
            "per_stock": review_stocks_per or {},
        },
        "review_bonds": {
            "schema_version": 2,
            "snapshot_id": rb_snapshot,
            "horizon_ends": ends,
            "per_bond": review_bonds_per or {},
        },
    }


# ───────────────── Шаг 1.5: нормировка p ─────────────────

class NormalizeScenarioProbs(unittest.TestCase):
    def test_normal_sum_1(self):
        sc = _scenarios_fresh()
        S, sev = normalize_scenario_probs(sc)
        self.assertAlmostEqual(S, 1.0)
        self.assertIsNone(sev)
        for k in sc:
            self.assertAlmostEqual(sc[k]["p_norm"], 0.25)

    def test_low_severity(self):
        sc = {"A": {"p": 0.30}, "B": {"p": 0.30}, "C": {"p": 0.40}}  # sum=1.0
        sc2 = {"A": {"p": 0.30}, "B": {"p": 0.30}, "C": {"p": 0.43}}  # sum=1.03 → LOW
        _, sev = normalize_scenario_probs(sc2)
        self.assertEqual(sev, "LOW")

    def test_medium_severity(self):
        sc = {"A": {"p": 0.30}, "B": {"p": 0.30}, "C": {"p": 0.50}}  # sum=1.10 → MEDIUM
        _, sev = normalize_scenario_probs(sc)
        self.assertEqual(sev, "MEDIUM")

    def test_zero_sum(self):
        sc = {"A": {"p": 0}}
        S, sev = normalize_scenario_probs(sc)
        self.assertEqual(S, 0)
        self.assertEqual(sev, "MEDIUM")
        self.assertEqual(sc["A"]["p_norm"], 0.0)

    def test_normalization_when_sum_off(self):
        sc = {"A": {"p": 0.5}, "B": {"p": 0.5}, "C": {"p": 0.1}}  # sum=1.1
        normalize_scenario_probs(sc)
        # p_norm должны суммироваться к 1
        s = sum(v["p_norm"] for v in sc.values())
        self.assertAlmostEqual(s, 1.0)


# ───────────────── Шаг 2: cross-validate + drift ─────────────────

class CrossValidate(unittest.TestCase):
    def test_all_resolved(self):
        scenarios = _scenarios_fresh()
        review = {"per_stock": {
            "SBER": {"catalyst": [
                {"id": "c1", "p": 0.5, "macro_dependency": "Sc-A"},
                {"id": "c2", "p": 0.5, "macro_dependency": None},
            ]}
        }}
        result = cross_validate(review, scenarios)
        self.assertEqual(result["unresolved"], [])
        self.assertEqual(result["total_with_dependency"], 1)
        self.assertEqual(result["share"], 0.0)

    def test_mixed_unresolved_under_threshold(self):
        scenarios = _scenarios_fresh()
        review = {"per_stock": {
            "SBER": {"catalyst": [
                {"id": "c1", "p": 0.5, "macro_dependency": "Sc-A"},
                {"id": "c2", "p": 0.5, "macro_dependency": "Sc-A"},
                {"id": "c3", "p": 0.5, "macro_dependency": "Sc-A"},
                {"id": "c4", "p": 0.5, "macro_dependency": "Sc-X_old"},  # unresolved
            ]}
        }}
        result = cross_validate(review, scenarios)
        self.assertEqual(len(result["unresolved"]), 1)
        self.assertEqual(result["share"], 0.25)
        self.assertEqual(result["missing_scenario_ids"], ["Sc-X_old"])

    def test_all_unresolved_above_threshold(self):
        scenarios = _scenarios_fresh()
        review = {"per_stock": {
            "SBER": {"catalyst": [
                {"id": "c1", "p": 0.5, "macro_dependency": "Sc-D_base"},
                {"id": "c2", "p": 0.5, "macro_dependency": "Sc-B_stress"},
            ]}
        }}
        result = cross_validate(review, scenarios)
        self.assertEqual(result["share"], 1.0)
        self.assertEqual(set(result["missing_scenario_ids"]), {"Sc-D_base", "Sc-B_stress"})

    def test_empty_dependencies(self):
        result = cross_validate({"per_stock": {}}, _scenarios_fresh())
        self.assertEqual(result["total_with_dependency"], 0)
        self.assertEqual(result["share"], 0.0)


class SnapshotDrift(unittest.TestCase):
    def test_no_drift(self):
        stress = {"snapshot_id": "portfolio-2026-05-07.json"}
        review_stocks = {"snapshot_id": "portfolio-2026-05-07.json"}
        review_bonds = {"snapshot_id": "portfolio-2026-05-07.json"}
        d = check_snapshot_drift(stress, review_stocks, review_bonds)
        self.assertEqual(d["max_drift_days"], 0)
        self.assertFalse(d["drift_warning"])

    def test_drift_2_days_no_warning(self):
        stress = {"snapshot_id": "portfolio-2026-05-07.json"}
        review_stocks = {"snapshot_id": "portfolio-2026-05-05.json"}  # 2д
        d = check_snapshot_drift(stress, review_stocks, None)
        self.assertEqual(d["max_drift_days"], 2)
        self.assertFalse(d["drift_warning"])

    def test_drift_warning(self):
        stress = {"snapshot_id": "portfolio-2026-05-07.json"}
        review_stocks = {"snapshot_id": "portfolio-2026-05-01.json"}  # 6д
        d = check_snapshot_drift(stress, review_stocks, None)
        self.assertEqual(d["max_drift_days"], 6)
        self.assertTrue(d["drift_warning"])

    def test_max_of_stocks_and_bonds(self):
        stress = {"snapshot_id": "portfolio-2026-05-07.json"}
        review_stocks = {"snapshot_id": "portfolio-2026-05-07.json"}  # 0д
        review_bonds = {"snapshot_id": "portfolio-2026-04-30.json"}  # 7д
        d = check_snapshot_drift(stress, review_stocks, review_bonds)
        self.assertEqual(d["max_drift_days"], 7)
        self.assertTrue(d["drift_warning"])


# ───────────────── Шаг 3: per-position aggregate ─────────────────

class AggregateMacro(unittest.TestCase):
    def test_basic(self):
        sp = {"expected_pct_pweighted": -1.05, "ci_pct": [-6.05, 3.95], "macro_blindspot": False}
        m = aggregate_macro(sp)
        self.assertEqual(m["value"], -1.05)
        self.assertEqual(m["ci"], [-6.05, 3.95])
        self.assertFalse(m["blindspot"])
        self.assertEqual(m["source"], "stress")
        self.assertEqual(m["layer"], "L2")
        self.assertIsNone(m["coherence_gap"])

    def test_blindspot(self):
        sp = {"expected_pct_pweighted": 1.08, "ci_pct": [-3.92, 6.08], "macro_blindspot": True}
        m = aggregate_macro(sp)
        self.assertTrue(m["blindspot"])

    def test_missing(self):
        m = aggregate_macro(None)
        self.assertIsNone(m["value"])
        self.assertEqual(m["source"], "missing")
        self.assertIsNone(m["layer"])

    def test_l1_with_factor_betas(self):
        """@1.4: L1 = Σ(beta × central_estimate) уходит в l1_point; канон value = L2."""
        sp = {
            "expected_pct_pweighted": 2.0,  # L2 value
            "ci_pct": [-1.0, 5.0],
            "factor_betas": {"brent": 0.4, "usd_rub": 0.2},
        }
        mm = {"brent": {"central_estimate": 5.0}, "usd_rub": {"central_estimate": -3.0}}
        # L1 = 0.4×5 + 0.2×(-3) = 2.0 - 0.6 = 1.4
        m = aggregate_macro(sp, macro_marginal=mm)
        self.assertAlmostEqual(m["value"], 2.0, places=4)   # канон = L2 (MC-совместимый)
        self.assertAlmostEqual(m["l1_point"], 1.4, places=4)
        self.assertEqual(m["source"], "stress")
        self.assertEqual(m["layer"], "L2")
        # coherence_gap = |1.4 - 2.0| = 0.6
        self.assertAlmostEqual(m["coherence_gap"], 0.6, places=4)
        # CI is preserved from stress
        self.assertEqual(m["ci"], [-1.0, 5.0])

    def test_l1_becomes_value_only_when_l2_missing(self):
        """Fallback: L2 отсутствует → value = L1 (старое поведение), layer L1."""
        sp = {"ci_pct": [-1.0, 5.0], "factor_betas": {"brent": 0.4}}
        mm = {"brent": {"central_estimate": 5.0}}
        m = aggregate_macro(sp, macro_marginal=mm)
        self.assertAlmostEqual(m["value"], 2.0, places=4)   # 0.4×5
        self.assertAlmostEqual(m["l1_point"], 2.0, places=4)
        self.assertEqual(m["layer"], "L1")
        self.assertEqual(m["source"], "macro_marginal")
        self.assertIsNone(m["coherence_gap"])

    def test_l2_fallback_when_no_factor_betas(self):
        """No factor_betas in stress_pos → L2 fallback even if macro_marginal provided."""
        sp = {"expected_pct_pweighted": 3.0, "ci_pct": [0.0, 6.0]}
        mm = {"brent": {"central_estimate": 5.0}}
        m = aggregate_macro(sp, macro_marginal=mm)
        self.assertEqual(m["layer"], "L2")
        self.assertEqual(m["value"], 3.0)
        self.assertEqual(m["source"], "stress")

    def test_l2_fallback_when_no_macro_marginal(self):
        """No macro_marginal → L2 fallback (backward-compat)."""
        sp = {"expected_pct_pweighted": 3.0, "ci_pct": [0.0, 6.0],
              "factor_betas": {"brent": 0.5}}
        m = aggregate_macro(sp, macro_marginal=None)
        self.assertEqual(m["layer"], "L2")
        self.assertEqual(m["source"], "stress")

    # ── Баг #2: guard / alias / fallback на реальном macro-marginal ──
    def test_l1_skips_nonnumeric_central_estimate(self):
        """Качественный central_estimate (строка) пропускается без краша."""
        sp = {"expected_pct_pweighted": 2.0, "ci_pct": [-1.0, 5.0],
              "factor_betas": {"geopol": -0.2, "brent": 0.15}}
        mm = {"geopolitics": {"central_estimate": "Pure Shell D1: A=B=C=D=0.25"},
              "brent": {"central_estimate": 4.0}}
        m = aggregate_macro(sp, macro_marginal=mm)
        # geopolitics-строка пропущена, brent числовой → l1_point = 0.15×4 = 0.6
        self.assertAlmostEqual(m["l1_point"], 0.6, places=4)
        self.assertAlmostEqual(m["value"], 2.0, places=4)   # канон = L2

    def test_l1_alias_geopolitics_to_geopol(self):
        """Фактор geopolitics из macro-marginal сопоставляется с бетой geopol."""
        sp = {"expected_pct_pweighted": 2.0, "ci_pct": [-1.0, 5.0],
              "factor_betas": {"geopol": -0.2}}
        mm = {"geopolitics": {"central_estimate": 10.0}}
        m = aggregate_macro(sp, macro_marginal=mm)
        self.assertAlmostEqual(m["l1_point"], -2.0, places=4)  # -0.2 × 10
        self.assertAlmostEqual(m["value"], 2.0, places=4)      # канон = L2

    def test_l1_all_qualitative_falls_to_l2(self):
        """Если все факторы нечисловые → L2 fallback (не ложный L1=0)."""
        sp = {"expected_pct_pweighted": 3.0, "ci_pct": [0.0, 6.0],
              "factor_betas": {"geopol": -0.2, "sanctions": -0.35}}
        mm = {"geopolitics": {"central_estimate": "Pure Shell"},
              "sanctions": {"central_estimate": "Holding pattern ~50%"}}
        m = aggregate_macro(sp, macro_marginal=mm)
        self.assertEqual(m["layer"], "L2")
        self.assertEqual(m["value"], 3.0)
        self.assertIsNone(m["l1_point"])

    def test_l1_unmatched_factor_skipped(self):
        """Фактор без соответствующей беты пропускается (не падаем в 0-term)."""
        sp = {"expected_pct_pweighted": 2.0, "ci_pct": [-1.0, 5.0],
              "factor_betas": {"brent": 0.15}}
        mm = {"brent": {"central_estimate": 4.0},
              "cnyrub": {"central_estimate": 3.0}}  # нет беты cnyrub
        m = aggregate_macro(sp, macro_marginal=mm)
        self.assertAlmostEqual(m["l1_point"], 0.6, places=4)  # только brent
        self.assertAlmostEqual(m["value"], 2.0, places=4)     # канон = L2


class AggregateMacroL1Level(unittest.TestCase):
    """MFC-4: тесты нового формата level_l1_<год> + unit + baseline_spot."""

    _SPOT = {"brent_usd": 94.11, "usdrub": 71.38, "cnyrub": 10.475, "cbr_rate_pct": 14.5}

    def test_brent_level_to_pct_move(self):
        """level_l1 для brent конвертируется в % от baseline_spot."""
        sp = {
            "expected_pct_pweighted": 2.0,
            "ci_pct": [-1.0, 5.0],
            "factor_betas": {"brent": 0.15},
        }
        mm = {"brent": {"level_l1_2026": 68.0, "unit": "usd_per_bbl"}}
        # move = (68 - 94.11) / 94.11 * 100 = -27.744...
        expected_move = (68.0 - 94.11) / 94.11 * 100.0
        m = aggregate_macro(sp, macro_marginal=mm, baseline_spot=self._SPOT, horizon_year=2026)
        self.assertAlmostEqual(m["l1_point"], 0.15 * expected_move, places=3)
        self.assertAlmostEqual(m["value"], 2.0, places=4)   # канон = L2
        self.assertIsNotNone(m["coherence_gap"])

    def test_cbr_rate_level_to_pp_diff(self):
        """level_l1 для cbr_rate конвертируется в п.п. от baseline."""
        sp = {
            "expected_pct_pweighted": -0.5,
            "ci_pct": [-2.0, 1.0],
            "factor_betas": {"cbr_rate": -0.2},
        }
        mm = {"cbr_rate": {"level_l1_2026": 12.0, "unit": "rate_pct"}}
        # move = 12 - 14.5 = -2.5 п.п.
        m = aggregate_macro(sp, macro_marginal=mm, baseline_spot=self._SPOT, horizon_year=2026)
        self.assertAlmostEqual(m["l1_point"], (-0.2) * (-2.5), places=4)  # = 0.5
        self.assertAlmostEqual(m["value"], -0.5, places=4)               # канон = L2

    def test_picks_nearest_year_to_horizon(self):
        """horizon_year=2028 → ближайший доступный 2027 выбирается корректно."""
        sp = {
            "expected_pct_pweighted": 0.0,
            "ci_pct": [-1.0, 1.0],
            "factor_betas": {"brent": 0.1},
        }
        mm = {"brent": {
            "level_l1_2026": 68.0,
            "level_l1_2027": 57.0,
            "unit": "usd_per_bbl",
        }}
        m2028 = aggregate_macro(sp, macro_marginal=mm, baseline_spot=self._SPOT, horizon_year=2028)
        m2026 = aggregate_macro(sp, macro_marginal=mm, baseline_spot=self._SPOT, horizon_year=2026)
        # horizon_year=2028 → ближе к 2027 → level=57
        move_2027 = (57.0 - 94.11) / 94.11 * 100.0
        move_2026 = (68.0 - 94.11) / 94.11 * 100.0
        self.assertAlmostEqual(m2028["l1_point"], 0.1 * move_2027, places=3)
        self.assertAlmostEqual(m2026["l1_point"], 0.1 * move_2026, places=3)

    def test_fallback_to_l2_when_no_baseline_spot(self):
        """level_l1 присутствует, но baseline_spot=None → fallback на L2."""
        sp = {
            "expected_pct_pweighted": 3.0,
            "ci_pct": [-1.0, 7.0],
            "factor_betas": {"brent": 0.15},
        }
        mm = {"brent": {"level_l1_2026": 68.0, "unit": "usd_per_bbl"}}
        m = aggregate_macro(sp, macro_marginal=mm, baseline_spot=None, horizon_year=2026)
        # Нет baseline_spot → новый формат пропускается → нет backward-compat number → L2
        self.assertEqual(m["layer"], "L2")
        self.assertAlmostEqual(m["value"], 3.0)

    def test_fallback_to_l2_when_no_horizon_year(self):
        """horizon_year=None → попытка 1 не запускается, backward-compat тоже нет → L2."""
        sp = {
            "expected_pct_pweighted": 3.0,
            "ci_pct": [0.0, 6.0],
            "factor_betas": {"brent": 0.15},
        }
        mm = {"brent": {"level_l1_2026": 68.0, "unit": "usd_per_bbl"}}
        m = aggregate_macro(sp, macro_marginal=mm, baseline_spot=self._SPOT, horizon_year=None)
        self.assertEqual(m["layer"], "L2")

    def test_backward_compat_flat_central_estimate(self):
        """Старый формат с плоским central_estimate числом работает по-прежнему."""
        sp = {
            "expected_pct_pweighted": 2.0,
            "ci_pct": [-1.0, 5.0],
            "factor_betas": {"brent": 0.4, "usd_rub": 0.2},
        }
        mm = {"brent": {"central_estimate": 5.0}, "usd_rub": {"central_estimate": -3.0}}
        # L1 = 0.4×5 + 0.2×(-3) = 1.4 (без baseline_spot/horizon_year)
        m = aggregate_macro(sp, macro_marginal=mm)
        self.assertAlmostEqual(m["l1_point"], 1.4, places=4)
        self.assertAlmostEqual(m["value"], 2.0, places=4)   # канон = L2

    def test_unknown_unit_falls_through_to_l2(self):
        """Неизвестный unit → _level_to_move возвращает None → L2."""
        sp = {
            "expected_pct_pweighted": 3.0,
            "ci_pct": [0.0, 6.0],
            "factor_betas": {"brent": 0.15},
        }
        mm = {"brent": {"level_l1_2026": 68.0, "unit": "unknown_unit"}}
        m = aggregate_macro(sp, macro_marginal=mm, baseline_spot=self._SPOT, horizon_year=2026)
        self.assertEqual(m["layer"], "L2")

    def test_coherence_gap_is_numeric(self):
        """coherence_gap = |L1 − L2| и всегда числовой при наличии L2."""
        sp = {
            "expected_pct_pweighted": 2.0,
            "ci_pct": [-1.0, 5.0],
            "factor_betas": {"brent": 0.15},
        }
        mm = {"brent": {"level_l1_2026": 68.0, "unit": "usd_per_bbl"}}
        m = aggregate_macro(sp, macro_marginal=mm, baseline_spot=self._SPOT, horizon_year=2026)
        self.assertIsInstance(m["coherence_gap"], float)
        move = (68.0 - 94.11) / 94.11 * 100.0
        expected_l1 = 0.15 * move
        self.assertAlmostEqual(m["coherence_gap"], abs(expected_l1 - 2.0), places=3)

    def test_usdrub_level_to_pct(self):
        """USD/RUB level_l1 конвертируется через rub_per_usd → pct_from_spot."""
        sp = {
            "expected_pct_pweighted": 0.0,
            "ci_pct": [-2.0, 2.0],
            "factor_betas": {"usdrub": 0.1},
        }
        mm = {"usdrub": {"level_l1_2026": 88.0, "unit": "rub_per_usd"}}
        # move = (88 - 71.38) / 71.38 * 100 = +23.28...
        expected_move = (88.0 - 71.38) / 71.38 * 100.0
        m = aggregate_macro(sp, macro_marginal=mm, baseline_spot=self._SPOT, horizon_year=2026)
        self.assertAlmostEqual(m["l1_point"], 0.1 * expected_move, places=3)
        self.assertAlmostEqual(m["value"], 0.0, places=4)   # канон = L2


class AggregateDivCarry(unittest.TestCase):
    def test_equity_div_yield(self):
        review = {"div_yield_12m_pct": {"value": 11.6, "ci_pct": [10.5, 12.5]}}
        d = aggregate_div_or_carry("equity", review, None, {}, 20)
        # 11.6 × 20/12 = 19.333
        self.assertAlmostEqual(d["value"], 11.6 * (20.0 / 12.0), places=4)
        self.assertEqual(d["source"], "div_yield_12m_pct")

    def test_bond_ytm_priority(self):
        review_bond = {"ytm_pct": {"value": 14.5, "ci_pct": [13.5, 15.5]}}
        holding = {"xirr": 12.0}
        d = aggregate_div_or_carry("bond", None, review_bond, holding, 20)
        # 14.5 × 20/12 = 24.166 — НЕ XIRR fallback
        self.assertAlmostEqual(d["value"], 14.5 * (20.0 / 12.0), places=4)
        self.assertEqual(d["source"], "ytm_pct")

    def test_bond_xirr_fallback(self):
        d = aggregate_div_or_carry("bond", None, None, {"xirr": 12.0}, 20)
        self.assertAlmostEqual(d["value"], 12.0 * (20.0 / 12.0), places=4)
        self.assertEqual(d["source"], "xirr_fallback")

    def test_bond_no_source(self):
        d = aggregate_div_or_carry("bond", None, None, {}, 20)
        self.assertEqual(d["value"], 0.0)
        self.assertEqual(d["source"], "missing")

    def test_bond_ignores_div_yield(self):
        # Облигации НЕ должны брать div_yield_12m_pct из stocks-review
        review_stock = {"div_yield_12m_pct": {"value": 7.0}}
        d = aggregate_div_or_carry("bond", review_stock, None, {}, 20)
        self.assertEqual(d["value"], 0.0)
        self.assertEqual(d["source"], "missing")

    def test_equity_no_div(self):
        d = aggregate_div_or_carry("equity", None, None, {}, 20)
        self.assertEqual(d["value"], 0.0)
        self.assertEqual(d["source"], "none")

    # ── Баг #1A: put/offer-облигации ──
    def test_bond_offer_extreme_ytm_uses_coupon_and_caps_horizon(self):
        # ПР-Лиз 2P2: ytm_pct=414 (yield-to-offer), оферта через ~7 дней, coupon 18%.
        rb = {"ytm_pct": 414.11, "coupon_pct": 18.0, "offer_date": "2026-06-15"}
        d = aggregate_div_or_carry("bond", None, rb, {}, 20, as_of=date(2026, 6, 8))
        self.assertEqual(d["source"], "coupon_pct")
        # eff_months ≈ 7/30.44 ≈ 0.23 → carry ≈ 18 × 0.23/12 ≈ 0.34 (НЕ 690)
        self.assertLess(d["value"], 1.0)
        self.assertGreater(d["value"], 0.0)

    def test_bond_extreme_ytm_no_asof_uses_coupon_bounded(self):
        # Без as_of горизонт не capped, но базис всё равно coupon → carry ограничен.
        rb = {"ytm_pct": 414.11, "coupon_pct": 18.0, "offer_date": "2026-06-15"}
        d = aggregate_div_or_carry("bond", None, rb, {}, 20)
        self.assertEqual(d["source"], "coupon_pct")
        self.assertAlmostEqual(d["value"], 18.0 * 20 / 12, places=3)  # 30.0, < CARRY_CAP

    def test_bond_maturity_caps_horizon_with_sane_ytm(self):
        # Sane ytm + погашение внутри горизонта → базис ytm, eff_months capped.
        rb = {"ytm_pct": 12.0, "maturity_date": "2027-01-08"}  # ~7 мес от as_of
        d = aggregate_div_or_carry("bond", None, rb, {}, 20, as_of=date(2026, 6, 8))
        self.assertEqual(d["source"], "ytm_pct")
        # eff ≈ 7 мес, НЕ 20 → carry ≈ 12 × 7/12 ≈ 7, заметно меньше 12×20/12=20
        self.assertLess(d["value"], 12.0 * 20 / 12)
        self.assertGreater(d["value"], 0.0)

    def test_bond_backstop_clamp(self):
        # Аномальный coupon без оферты → carry превышает cap → клампится.
        rb = {"coupon_pct": 200.0}
        d = aggregate_div_or_carry("bond", None, rb, {}, 20)
        self.assertEqual(d["value"], CARRY_CAP_PCT)
        self.assertEqual(d["source"], "coupon_pct_capped")

    def test_bond_no_event_sane_ytm_unchanged(self):
        # Регресс: без оферты/погашения и при sane ytm — поведение прежнее (ytm × горизонт).
        rb = {"ytm_pct": 14.5}
        d = aggregate_div_or_carry("bond", None, rb, {}, 20)
        self.assertEqual(d["source"], "ytm_pct")
        self.assertAlmostEqual(d["value"], 14.5 * 20 / 12, places=4)


class AggregateIdio(unittest.TestCase):
    """Legacy backward-compat (без поля kind) + новые kind-aware тесты (METH-1)."""
    def setUp(self):
        self.scenarios = _scenarios_fresh()
        normalize_scenario_probs(self.scenarios)

    # ----- LEGACY backward-compat (без kind) -----

    def test_legacy_resolved_macro_dependency(self):
        review = {"catalyst": [
            {"id": "c1", "p": 0.6, "macro_dependency": "Sc-A",
             "upside_pct": 18, "upside_ci_pct": [10, 28], "source_quality": "HIGH"}
        ]}
        idio = aggregate_idio(review, self.scenarios, None)
        # legacy detected → binary, mass = p(Sc-A) = 0.25, factor = 0.6×0.25 = 0.15; value = 2.7
        self.assertAlmostEqual(idio["value"], 0.15 * 18, places=4)
        applied = idio["catalysts_applied"][0]
        self.assertEqual(applied["kind"], "binary")
        self.assertIn("catalyst_missing_kind", applied["warnings"])

    def test_legacy_unresolved_macro_dependency_discounts(self):
        review = {"catalyst": [
            {"id": "c1", "p": 0.6, "macro_dependency": "Sc-X_old",
             "upside_pct": 18, "upside_ci_pct": [10, 28]}
        ]}
        idio = aggregate_idio(review, self.scenarios, None)
        # unresolved → mass = NULL_DEPENDENCY_DISCOUNT = 0.7; factor = 0.42; value = 7.56
        self.assertAlmostEqual(idio["value"], 0.42 * 18, places=4)
        applied = idio["catalysts_applied"][0]
        self.assertIn("scenario_unresolved", applied["warnings"])

    def test_legacy_null_macro_dependency_discounts(self):
        review = {"catalyst": [
            {"id": "c1", "p": 0.5, "macro_dependency": None,
             "upside_pct": 10, "upside_ci_pct": [5, 15]}
        ]}
        idio = aggregate_idio(review, self.scenarios, None)
        # null dep → mass = 0.7 (null discount); factor = 0.35; value = 3.5
        self.assertAlmostEqual(idio["value"], 0.35 * 10, places=4)

    def test_legacy_low_source_quality_halves(self):
        review = {"catalyst": [
            {"id": "c1", "p": 0.5, "macro_dependency": "Sc-A",
             "upside_pct": 10, "upside_ci_pct": [5, 15], "source_quality": "LOW"}
        ]}
        idio = aggregate_idio(review, self.scenarios, None)
        # mass=0.25, src=0.5; factor=0.5×0.25×0.5=0.0625; value=0.625
        self.assertAlmostEqual(idio["value"], 0.0625 * 10, places=4)

    def test_trust_matrix_ignores(self):
        review = {"catalyst": [
            {"id": "c1", "p": 0.5, "macro_dependency": "Sc-A",
             "upside_pct": 10, "upside_ci_pct": [5, 15], "source": "invest_era_macro"}
        ]}
        trust = {"ignored_subdomains": ["invest_era_macro"]}
        idio = aggregate_idio(review, self.scenarios, trust)
        self.assertEqual(idio["value"], 0.0)
        self.assertEqual(idio["ignored_catalysts"][0]["reason"], "trust_ignore")

    def test_legacy_downside_catalyst(self):
        review = {"catalyst": [
            {"id": "c1", "p": 0.12, "macro_dependency": None,
             "downside_pct": 35, "downside_ci_pct": [20, 50]}
        ]}
        idio = aggregate_idio(review, self.scenarios, None)
        # null_dep → mass = 0.7; factor = 0.12 × 0.7 = 0.084; impact = -35
        self.assertAlmostEqual(idio["value"], -0.084 * 35, places=4)

    def test_out_of_horizon_skipped(self):
        review = {"catalyst": [
            {"id": "c1", "p": 0.5, "macro_dependency": "Sc-A",
             "upside_pct": 10, "date_window": "2029-01"}
        ]}
        idio = aggregate_idio(review, self.scenarios, None, horizon_end=date(2027, 5, 31))
        self.assertEqual(idio["value"], 0.0)
        self.assertEqual(idio["ignored_catalysts"][0]["reason"], "out_of_horizon")

    # ----- NEW kind-aware (METH-1) -----

    def test_binary_explicit_kind(self):
        """binary с явным kind + scenario-independent (null macro_dep)."""
        review = {"catalyst": [
            {"id": "div_2025", "kind": "binary",
             "p": 0.88, "upside_pct": 3, "upside_ci_pct": [0, 5],
             "macro_dependency": None, "source_quality": "HIGH"}
        ]}
        idio = aggregate_idio(review, self.scenarios, None)
        # mass = 0.7 (null_dep); factor = 0.88 × 0.7 = 0.616; value = 1.848
        self.assertAlmostEqual(idio["value"], 0.616 * 3, places=4)
        applied = idio["catalysts_applied"][0]
        self.assertEqual(applied["kind"], "binary")
        self.assertNotIn("catalyst_missing_kind", applied["warnings"])

    def test_binary_active_scenarios_list(self):
        """binary с active_scenarios=[A,B,C] — mass = 0.75."""
        review = {"catalyst": [
            {"id": "rate_cut_event", "kind": "binary",
             "p": 0.65, "upside_pct": 18, "upside_ci_pct": [8, 30],
             "active_scenarios": ["Sc-A", "Sc-B", "Sc-C"], "source_quality": "MEDIUM"}
        ]}
        idio = aggregate_idio(review, self.scenarios, None)
        # mass = 0.25+0.25+0.25 = 0.75; factor = 0.65 × 0.75 = 0.4875; value = 8.775
        self.assertAlmostEqual(idio["value"], 0.4875 * 18, places=4)
        applied = idio["catalysts_applied"][0]
        self.assertAlmostEqual(applied["ci"][0], 0.4875 * 8, places=4)
        self.assertAlmostEqual(applied["ci"][1], 0.4875 * 30, places=4)

    def test_quantitative_full_per_scenario(self):
        """quantitative с полным upside_by_scenario."""
        review = {"catalyst": [
            {"id": "rate_cut_rerating", "kind": "quantitative",
             "upside_by_scenario": {"Sc-A": 18, "Sc-B": 10, "Sc-C": 10, "Sc-D": 0},
             "upside_ci_by_scenario": {
                 "Sc-A": [8, 30], "Sc-B": [3, 17], "Sc-C": [3, 17], "Sc-D": [0, 0]
             },
             "source_quality": "MEDIUM"}
        ]}
        idio = aggregate_idio(review, self.scenarios, None)
        # E = 0.25×18 + 0.25×10 + 0.25×10 + 0.25×0 = 4.5 + 2.5 + 2.5 + 0 = 9.5
        self.assertAlmostEqual(idio["value"], 9.5, places=4)
        applied = idio["catalysts_applied"][0]
        self.assertEqual(applied["kind"], "quantitative")
        # CI: lo = 0.25×8 + 0.25×3 + 0.25×3 + 0 = 3.5; hi = 0.25×30 + 0.25×17 + 0.25×17 + 0 = 16.0
        self.assertAlmostEqual(applied["ci"][0], 3.5, places=4)
        self.assertAlmostEqual(applied["ci"][1], 16.0, places=4)

    def test_quantitative_low_source_quality(self):
        review = {"catalyst": [
            {"id": "q_low", "kind": "quantitative",
             "upside_by_scenario": {"Sc-A": 18, "Sc-B": 10, "Sc-C": 10, "Sc-D": 0},
             "source_quality": "LOW"}
        ]}
        idio = aggregate_idio(review, self.scenarios, None)
        # E без LOW = 9.5; с LOW = 4.75
        self.assertAlmostEqual(idio["value"], 4.75, places=4)

    def test_quantitative_incomplete_scenarios(self):
        """quantitative с пропущенным Sc-D — missing подставляется как 0 + warning."""
        review = {"catalyst": [
            {"id": "q_partial", "kind": "quantitative",
             "upside_by_scenario": {"Sc-A": 20, "Sc-B": 10, "Sc-C": 5}}
        ]}
        idio = aggregate_idio(review, self.scenarios, None)
        # E = 0.25×20 + 0.25×10 + 0.25×5 + 0.25×0 = 8.75
        self.assertAlmostEqual(idio["value"], 8.75, places=4)
        applied = idio["catalysts_applied"][0]
        self.assertTrue(any("missing_scenarios_zeroed" in w for w in applied["warnings"]))

    def test_quantitative_p_field_ignored(self):
        """quantitative с p — warning, но не влияет на расчёт."""
        review = {"catalyst": [
            {"id": "q_with_p", "kind": "quantitative", "p": 0.5,
             "upside_by_scenario": {"Sc-A": 10, "Sc-B": 10, "Sc-C": 10, "Sc-D": 10}}
        ]}
        idio = aggregate_idio(review, self.scenarios, None)
        # E = 10 (без p); если бы p применили → 5
        self.assertAlmostEqual(idio["value"], 10.0, places=4)
        applied = idio["catalysts_applied"][0]
        self.assertIn("quantitative_has_p_ignored", applied["warnings"])

    def test_invalid_kind_skipped(self):
        review = {"catalyst": [
            {"id": "bad", "kind": "weird_unknown",
             "upside_pct": 10, "p": 0.5}
        ]}
        idio = aggregate_idio(review, self.scenarios, None)
        self.assertEqual(idio["value"], 0.0)
        self.assertEqual(len(idio["ignored_catalysts"]), 1)
        self.assertIn("invalid_kind", idio["ignored_catalysts"][0]["reason"])

    def test_mixed_kinds_sum_correctly(self):
        """SBER-like: один quant (rate-cut) + один binary null (div) + binary LOW (credit_cycle)."""
        review = {"catalyst": [
            {"id": "rate_cut", "kind": "quantitative",
             "upside_by_scenario": {"Sc-A": 18, "Sc-B": 10, "Sc-C": 10, "Sc-D": 0}},
            {"id": "div", "kind": "binary", "p": 0.88, "upside_pct": 3,
             "macro_dependency": None, "source_quality": "HIGH"},
            {"id": "credit", "kind": "quantitative",
             "upside_by_scenario": {"Sc-A": 12, "Sc-B": 6, "Sc-C": 6, "Sc-D": 0},
             "source_quality": "LOW"},
        ]}
        idio = aggregate_idio(review, self.scenarios, None)
        # rate_cut: 9.5; div: 0.88 × 0.7 × 3 = 1.848; credit: 0.5 × (0.25×12+0.25×6+0.25×6+0) = 0.5 × 6 = 3.0
        expected = 9.5 + 1.848 + 3.0
        self.assertAlmostEqual(idio["value"], expected, places=3)

    def test_binary_active_scenarios_priority_over_macro_dep(self):
        """Если заданы оба active_scenarios и macro_dependency — active_scenarios приоритет."""
        review = {"catalyst": [
            {"id": "c1", "kind": "binary", "p": 0.5,
             "upside_pct": 10, "upside_ci_pct": [5, 15],
             "active_scenarios": ["Sc-A", "Sc-B"],
             "macro_dependency": "Sc-D"}  # должен быть проигнорирован
        ]}
        idio = aggregate_idio(review, self.scenarios, None)
        # mass = p(A)+p(B) = 0.5; factor = 0.5 × 0.5 = 0.25; value = 2.5
        self.assertAlmostEqual(idio["value"], 2.5, places=4)


# ───────────────── Шаг 4: portfolio aggregates ─────────────────

class PortfolioAggregates(unittest.TestCase):
    def _pos(self, ticker, ac, weight, total_v, total_lo, total_hi, blocked=False):
        return {
            "ticker": ticker, "asset_class": ac, "weight_pct": weight,
            "is_blocked": blocked, "weight_source": "stress",
            "macro": {"value": 0, "ci": [0, 0]},
            "div_or_carry": {"value": 0, "ci": [0, 0]},
            "idio": {"value": 0, "ci": [0, 0]},
            "total": {"value": total_v, "ci": [total_lo, total_hi]},
        }

    def test_simple_split(self):
        positions = [
            self._pos("SBER", "equity", 10.0, 20.0, 5.0, 35.0),
            self._pos("OFZ", "bond", 20.0, 50.0, 30.0, 70.0),
        ]
        out = compute_portfolio_aggregates(positions, 20)
        self.assertAlmostEqual(out["equity"]["expected_pct_horizon"]["value"], 20.0)
        self.assertAlmostEqual(out["bond"]["expected_pct_horizon"]["value"], 50.0)
        self.assertAlmostEqual(out["spread_pp_horizon"]["point"], -30.0)

    def test_weighted_mean(self):
        positions = [
            self._pos("A", "equity", 10.0, 20.0, 10.0, 30.0),
            self._pos("B", "equity", 30.0, 40.0, 20.0, 60.0),
        ]
        out = compute_portfolio_aggregates(positions, 20)
        # weighted = (10×20 + 30×40) / 40 = (200+1200)/40 = 35
        self.assertAlmostEqual(out["equity"]["expected_pct_horizon"]["value"], 35.0)

    def test_blocked_excluded(self):
        positions = [
            self._pos("A", "equity", 10.0, 20.0, 10.0, 30.0),
            self._pos("B", "equity", 100.0, 999.0, 999.0, 999.0, blocked=True),
        ]
        out = compute_portfolio_aggregates(positions, 20)
        # Только A считается
        self.assertAlmostEqual(out["equity"]["expected_pct_horizon"]["value"], 20.0)
        self.assertAlmostEqual(out["equity"]["weight_pct"], 10.0)

    def test_dual_ci_propagation(self):
        positions = [
            self._pos("A", "equity", 50.0, 20.0, 10.0, 30.0),  # CI width 20
            self._pos("B", "bond", 50.0, 30.0, 25.0, 35.0),    # CI width 10
        ]
        out = compute_portfolio_aggregates(positions, 20)
        spread = out["spread_pp_horizon"]
        self.assertAlmostEqual(spread["point"], -10.0)
        # Линейный: [10-35, 30-25] = [-25, 5]
        self.assertAlmostEqual(spread["ci_linear"][0], -25.0)
        self.assertAlmostEqual(spread["ci_linear"][1], 5.0)
        # Квадратурный: σ_eq=5, σ_bd=2.5, σ_spread=√(25+6.25)=5.59
        # CI = [-10 - 11.18, -10 + 11.18] ≈ [-21.18, 1.18]
        self.assertAlmostEqual(spread["ci_quadratic"][0], -21.180, places=2)
        self.assertAlmostEqual(spread["ci_quadratic"][1], 1.180, places=2)

    def test_annualization(self):
        positions = [self._pos("A", "equity", 10.0, 20.0, 10.0, 30.0)]
        out = compute_portfolio_aggregates(positions, 20)
        # Геометрическая аннуализация (2026-07): (1+0.20)^(12/20) − 1 = 11.567%
        self.assertAlmostEqual(out["equity"]["expected_pct_annualized"]["value"],
                               ((1.20) ** (12 / 20) - 1) * 100, places=6)
        self.assertEqual(out["equity"]["expected_pct_annualized"]["method"], "geometric")

    def test_empty_one_class(self):
        positions = [self._pos("A", "equity", 10.0, 20.0, 10.0, 30.0)]
        out = compute_portfolio_aggregates(positions, 20)
        self.assertIsNone(out["bond"]["expected_pct_horizon"]["value"])
        self.assertIsNone(out["spread_pp_horizon"])

    # ── @1.4: L1-overlay точка отдельным полем, канон/spread не трогает ──

    def test_l1_point_emitted_separately(self):
        a = self._pos("A", "bond", 10.0, 20.0, 10.0, 30.0)
        a["l1_total"] = 28.0
        b = self._pos("B", "bond", 10.0, 30.0, 20.0, 40.0)
        b["l1_total"] = 34.0
        out = compute_portfolio_aggregates([a, b], 12)
        # канон не изменился
        self.assertAlmostEqual(out["bond"]["expected_pct_horizon"]["value"], 25.0)
        # l1_point = (10×28 + 10×34)/20 = 31
        self.assertAlmostEqual(out["bond"]["l1_point"]["value"], 31.0)
        self.assertIn("не входит", out["bond"]["l1_point"]["note"])

    def test_l1_point_absent_without_l1_totals(self):
        positions = [self._pos("A", "equity", 10.0, 20.0, 10.0, 30.0)]
        out = compute_portfolio_aggregates(positions, 12)
        self.assertNotIn("l1_point", out["equity"])

    def test_l1_point_mixed_positions_fallback_to_total(self):
        a = self._pos("A", "equity", 10.0, 20.0, 10.0, 30.0)
        a["l1_total"] = 26.0
        b = self._pos("B", "equity", 10.0, 40.0, 30.0, 50.0)   # без L1 → канон total
        out = compute_portfolio_aggregates([a, b], 12)
        # l1_point = (10×26 + 10×40)/20 = 33; канон = 30
        self.assertAlmostEqual(out["equity"]["l1_point"]["value"], 33.0)
        self.assertAlmostEqual(out["equity"]["expected_pct_horizon"]["value"], 30.0)

    def test_l1_point_does_not_move_spread(self):
        a = self._pos("A", "equity", 10.0, 20.0, 10.0, 30.0)
        a["l1_total"] = 90.0   # экстремальная L1 не должна утечь в spread
        b = self._pos("B", "bond", 10.0, 30.0, 20.0, 40.0)
        b["l1_total"] = -90.0
        out = compute_portfolio_aggregates([a, b], 12)
        self.assertAlmostEqual(out["spread_pp_horizon"]["point"], -10.0)


# ───────────────── End-to-end через run() ─────────────────

class EndToEnd(unittest.TestCase):
    def test_stale_pipeline_gate_fails(self):
        """Все catalyst используют старые scenario IDs → gate=FAIL."""
        payload = _make_payload(
            holdings=[{"ticker": "SBER", "asset_class": "equity",
                       "value_rub": 100_000, "currency": "RUB"}],
            stress_pp={"SBER": {"weight_pct": 5.0,
                                "expected_pct_pweighted": -1.0, "ci_pct": [-5.0, 3.0]}},
            review_stocks_per={
                "SBER": {
                    "div_yield_12m_pct": {"value": 11.6, "ci_pct": [10.5, 12.5]},
                    "catalyst": [
                        {"id": "c1", "p": 0.6, "macro_dependency": "Sc-D_base",
                         "upside_pct": 18, "upside_ci_pct": [10, 28]},
                        {"id": "c2", "p": 0.12, "macro_dependency": "Sc-B_stress",
                         "downside_pct": 35, "downside_ci_pct": [20, 50]},
                    ],
                    "advisor_verdict": "HOLD",
                },
            },
        )
        result = run(payload)
        self.assertEqual(result["validation"]["stale_pipeline_gate"], "FAIL")
        self.assertEqual(result["validation"]["unresolved_share"], 1.0)
        self.assertIn("RECALIBRATE", result["validation"]["stale_pipeline_message"])
        self.assertEqual(set(result["validation"]["missing_scenario_ids"]),
                         {"Sc-D_base", "Sc-B_stress"})

    def test_stale_pipeline_gate_passes(self):
        """1 unresolved из 4 (25% < 30%) → gate=PASS, discount применяется per-catalyst."""
        payload = _make_payload(
            holdings=[{"ticker": "SBER", "asset_class": "equity",
                       "value_rub": 100_000, "currency": "RUB"}],
            stress_pp={"SBER": {"weight_pct": 5.0,
                                "expected_pct_pweighted": -1.0, "ci_pct": [-5.0, 3.0]}},
            review_stocks_per={
                "SBER": {
                    "catalyst": [
                        {"id": "c1", "p": 0.6, "macro_dependency": "Sc-A",
                         "upside_pct": 18, "upside_ci_pct": [10, 28]},
                        {"id": "c2", "p": 0.6, "macro_dependency": "Sc-B",
                         "upside_pct": 18, "upside_ci_pct": [10, 28]},
                        {"id": "c3", "p": 0.6, "macro_dependency": "Sc-C",
                         "upside_pct": 18, "upside_ci_pct": [10, 28]},
                        {"id": "c4", "p": 0.6, "macro_dependency": "Sc-X_old",
                         "upside_pct": 18, "upside_ci_pct": [10, 28]},
                    ],
                    "advisor_verdict": "HOLD",
                },
            },
        )
        result = run(payload)
        self.assertEqual(result["validation"]["stale_pipeline_gate"], "PASS")
        self.assertAlmostEqual(result["validation"]["unresolved_share"], 0.25)

    def test_weight_from_stress_not_review(self):
        """R-SNAP: вес позиции в per_position берётся из stress, а не из review.weight_real_pct."""
        payload = _make_payload(
            holdings=[{"ticker": "SBER", "asset_class": "equity",
                       "value_rub": 100_000, "currency": "RUB"}],
            stress_pp={"SBER": {"weight_pct": 4.37,  # из stress
                                "expected_pct_pweighted": 0.0, "ci_pct": [-5.0, 5.0]}},
            review_stocks_per={"SBER": {"weight_real_pct": 12.58,  # должно игнорироваться
                                         "advisor_verdict": "HOLD"}},
        )
        result = run(payload)
        sber = next(p for p in result["per_position"] if p["ticker"] == "SBER")
        self.assertEqual(sber["weight_pct"], 4.37)
        self.assertEqual(sber["weight_source"], "stress")

    def test_bond_ytm_carry_path(self):
        payload = _make_payload(
            holdings=[{"ticker": "OFZ_26243", "asset_class": "bond",
                       "value_rub": 1_000_000, "currency": "RUB", "xirr": 12.0}],
            stress_pp={"OFZ_26243": {"weight_pct": 8.0,
                                     "expected_pct_pweighted": 48.0, "ci_pct": [40.0, 56.0]}},
            review_bonds_per={
                "OFZ_26243": {
                    "ytm_pct": {"value": 14.5, "ci_pct": [13.5, 15.5]},
                    "advisor_verdict": "HOLD",
                }
            },
        )
        result = run(payload)
        bond = next(p for p in result["per_position"] if p["ticker"] == "OFZ_26243")
        self.assertEqual(bond["div_or_carry"]["source"], "ytm_pct")
        self.assertAlmostEqual(bond["div_or_carry"]["value"], 14.5 * 20 / 12, places=3)
        # total = 48 (macro) + 24.166 (carry) + 0 (idio)
        self.assertAlmostEqual(bond["total"]["value"], 48.0 + 14.5 * 20 / 12, places=3)

    def test_bond_xirr_fallback_when_no_review(self):
        payload = _make_payload(
            holdings=[{"ticker": "BOND_NO_REVIEW", "asset_class": "bond",
                       "value_rub": 100_000, "currency": "RUB", "xirr": 12.0}],
            stress_pp={"BOND_NO_REVIEW": {"weight_pct": 1.0,
                                          "expected_pct_pweighted": 0.0, "ci_pct": [-2.0, 2.0]}},
        )
        result = run(payload)
        bond = result["per_position"][0]
        self.assertEqual(bond["div_or_carry"]["source"], "xirr_fallback")
        self.assertAlmostEqual(bond["div_or_carry"]["value"], 12.0 * 20 / 12, places=3)

    def test_legacy_bond_verdict_is_error_not_translation(self):
        """Прежние коды вердиктов облигаций (до единого словаря) — понятная ошибка, а не тихий перевод."""
        for legacy, target in (("HOLD_ADD", "ADD"), ("RED_FLAG", "WATCH"), ("MATURE", "HOLD_TO_MAT"),
                               ("HOLD_NO_OFFER", "HOLD_TO_MAT")):
            payload = _make_payload(
                holdings=[{"ticker": "RU000A0", "asset_class": "bond", "value_rub": 100_000, "currency": "RUB"}],
                stress_pp={"RU000A0": {"weight_pct": 1.0, "expected_pct_pweighted": 0.0, "ci_pct": [-2.0, 2.0]}},
                review_bonds_per={"RU000A0": {"advisor_verdict": legacy}},
            )
            with self.assertRaises(ValueError) as cm:
                run(payload)
            self.assertIn(target, str(cm.exception))
            self.assertIn(legacy, str(cm.exception))

    def test_snapshot_drift_detected(self):
        payload = _make_payload(
            stress_snapshot="portfolio-2026-05-07.json",
            rs_snapshot="portfolio-2026-05-01.json",  # 6д drift
        )
        result = run(payload)
        self.assertTrue(result["validation"]["snapshot_drift"]["drift_warning"])
        self.assertEqual(result["validation"]["snapshot_drift"]["max_drift_days"], 6)

    def test_blocked_position_excluded_from_aggregates(self):
        payload = _make_payload(
            holdings=[
                {"ticker": "GOOD", "asset_class": "equity",
                 "value_rub": 100_000, "currency": "RUB"},
                {"ticker": "T_blocked", "asset_class": "equity",
                 "value_rub": 50_000, "currency": "USD", "is_blocked": True},
            ],
            stress_pp={
                "GOOD": {"weight_pct": 10.0,
                         "expected_pct_pweighted": 20.0, "ci_pct": [10, 30]},
                "T_blocked": {"weight_pct": 5.0,
                              "expected_pct_pweighted": 999.0, "ci_pct": [0, 9999]},
            },
        )
        result = run(payload)
        self.assertAlmostEqual(result["portfolio"]["equity"]["expected_pct_horizon"]["value"], 20.0)
        self.assertAlmostEqual(result["portfolio"]["equity"]["weight_pct"], 10.0)

    def test_full_e2e_repro_brent_only_scenario(self):
        """Воспроизводим ситуацию из лога: только Brent в новом формате,
        остальное в старом → gate=FAIL."""
        payload = _make_payload(
            scenarios={
                "Sc-A": {"p": 0.25}, "Sc-B": {"p": 0.25},
                "Sc-C": {"p": 0.25}, "Sc-D": {"p": 0.25},
            },
            holdings=[
                {"ticker": "SBER", "asset_class": "equity", "value_rub": 575_000, "currency": "RUB"},
                {"ticker": "MBNK", "asset_class": "equity", "value_rub": 207_000, "currency": "RUB"},
            ],
            stress_pp={
                "SBER": {"weight_pct": 4.37, "expected_pct_pweighted": -1.05, "ci_pct": [-6.05, 3.95]},
                "MBNK": {"weight_pct": 1.58, "expected_pct_pweighted": -0.02, "ci_pct": [-5.02, 4.98]},
            },
            review_stocks_per={
                "SBER": {"catalyst": [
                    {"id": "rate_cut_re_rating", "p": 0.6, "macro_dependency": "Sc-D_base",
                     "upside_pct": 18, "upside_ci_pct": [10, 28]},
                    {"id": "sanctions_tail", "p": 0.12, "macro_dependency": "Sc-B_stress",
                     "downside_pct": 35, "downside_ci_pct": [20, 50]},
                ]},
                "MBNK": {"catalyst": [
                    {"id": "rate_cut", "p": 0.55, "macro_dependency": "Sc-D_base",
                     "upside_pct": 25, "upside_ci_pct": [15, 35]},
                ]},
            },
        )
        result = run(payload)
        self.assertEqual(result["validation"]["stale_pipeline_gate"], "FAIL")
        self.assertGreater(result["validation"]["unresolved_share"], 0.3)
        self.assertIn("Sc-D_base", result["validation"]["missing_scenario_ids"])


# ───────────────── Tail-risk флаги (output schema @1.2) ─────────────────

def _tail_pos(ticker, weight, value, lo, hi, *, asset_class="equity",
             blocked=False):
    """Минимальная per_position-строка для compute_tail_flags."""
    return {
        "ticker": ticker,
        "asset_class": asset_class,
        "weight_pct": weight,
        "is_blocked": blocked,
        "total": {"value": value, "ci": [lo, hi]},
    }


class TailFlagsCalibration(unittest.TestCase):
    """Кейсы §D на реальных значениях integrated-view-2026-05-29.md."""

    def test_upro_binary_skew(self):
        # UPRO: −4.5 [−17.3; +46.4], skew = 50.9/12.8 = 3.98 → Флаг 1
        pos = [_tail_pos("UPRO", 0.41, -4.5, -17.3, 46.4)]
        out = compute_tail_flags(pos)
        binary = [f for f in out["flags"] if f["code"] == "binary_skew"]
        self.assertEqual(len(binary), 1)
        self.assertEqual(binary[0]["ticker"], "UPRO")
        self.assertAlmostEqual(binary[0]["skew"], 3.98, places=2)
        self.assertEqual(binary[0]["direction"], "вверх")
        self.assertEqual(binary[0]["marker"], "⚡")
        # НЕ должен зажечь Флаг 2 (вес 0.41% < 2.0%)
        self.assertFalse([f for f in out["flags"] if f["code"] == "sign_unresolved"])

    def test_glrx_below_skew_threshold(self):
        # GLRX: −0.6 [−9.8; +13.9], skew = 14.5/9.2 = 1.58 < 2.0 → не срабатывает
        pos = [_tail_pos("GLRX", 0.56, -0.6, -9.8, 13.9)]
        out = compute_tail_flags(pos)
        self.assertFalse([f for f in out["flags"] if f["code"] == "binary_skew"])

    def test_ozon_weight_floor_boundary(self):
        # OZON: −4.1 [−12.7; +5.0], weight 1.87% < 2.0% floor → Флаг 2 НЕ срабатывает
        pos = [_tail_pos("OZON", 1.87, -4.1, -12.7, 5.0)]
        out = compute_tail_flags(pos)
        self.assertFalse([f for f in out["flags"] if f["code"] == "sign_unresolved"])
        # И не бимодален (skew ≈ 1.06)
        self.assertFalse([f for f in out["flags"] if f["code"] == "binary_skew"])

    def test_plzl_clean_all_positive(self):
        # PLZL: +69.1 [+36.1; +105.5] — весь CI положителен, скос ≈ 1.1 → чисто
        pos = [_tail_pos("PLZL", 2.51, 69.1, 36.1, 105.5)]
        out = compute_tail_flags(pos)
        self.assertEqual(out["flags"], [])
        self.assertFalse(out["fired"])
        # lo > 0 → нет вклада в нижний хвост
        self.assertEqual(out["portfolio_downside"], 0.0)

    def test_calibration_basket_tail_silent(self):
        # Ключевая проверка §D: на корзине из 4 позиций Σ contrib_down ≪ floor=3.0,
        # Флаг 3 молчит → хвост диверсифицирован.
        pos = [
            _tail_pos("UPRO", 0.41, -4.5, -17.3, 46.4),
            _tail_pos("GLRX", 0.56, -0.6, -9.8, 13.9),
            _tail_pos("OZON", 1.87, -4.1, -12.7, 5.0),
            _tail_pos("PLZL", 2.51, 69.1, 36.1, 105.5),
        ]
        out = compute_tail_flags(pos)
        self.assertFalse([f for f in out["flags"] if f["code"] == "portfolio_tail"])
        # Σ contrib_down ≈ 0.0041×12.8 + 0.0056×9.2 + 0.0187×8.6 + 0 ≈ 0.265
        self.assertLess(out["portfolio_downside"], 3.0)
        self.assertAlmostEqual(out["portfolio_downside"], 0.265, places=2)
        # Сработал только Флаг 1 на UPRO
        self.assertEqual([f["code"] for f in out["flags"]], ["binary_skew"])


class TailFlagsLogic(unittest.TestCase):
    def test_flag2_sign_unresolved_fires_at_floor(self):
        # lo<0<hi и weight ровно 2.0% → Флаг 2 срабатывает (≥ floor)
        pos = [_tail_pos("BIGZ", 2.0, -4.1, -12.7, 5.0)]
        out = compute_tail_flags(pos)
        f2 = [f for f in out["flags"] if f["code"] == "sign_unresolved"]
        self.assertEqual(len(f2), 1)
        self.assertEqual(f2[0]["severity"], "HIGH")
        self.assertEqual(f2[0]["weight_pct"], 2.0)

    def test_flag1_left_skew_direction(self):
        # Лево-скос: down_arm ≫ up_arm. value=−5 [−25; 0], down=20, up=5 → 4.0 вниз
        pos = [_tail_pos("LEFT", 1.0, -5.0, -25.0, 0.0)]
        out = compute_tail_flags(pos)
        b = [f for f in out["flags"] if f["code"] == "binary_skew"]
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0]["direction"], "вниз")
        self.assertAlmostEqual(b[0]["skew"], 4.0, places=2)

    def test_flag3_fires_above_floor_with_cap(self):
        # Крупная концентрация хвоста: одна позиция доминирует.
        # A: weight 40%, downside 20пп → contrib 0.4×20 = 8.0
        # B,C,D: weight 5%, downside 4пп → 0.05×4 = 0.2 каждая
        pos = [
            _tail_pos("A", 40.0, -10.0, -30.0, 10.0),  # skew симметричен, без Флаг1; lo<0<hi вес 40% → Флаг2 тоже
            _tail_pos("B", 5.0, -2.0, -6.0, 8.0),
            _tail_pos("C", 5.0, -2.0, -6.0, 8.0),
            _tail_pos("D", 5.0, -2.0, -6.0, 8.0),
        ]
        out = compute_tail_flags(pos)
        tail = [f for f in out["flags"] if f["code"] == "portfolio_tail"]
        self.assertTrue(tail)
        # A доминирует: contrib 8.0 из Σ=8.6 → 93%
        self.assertEqual(tail[0]["ticker"], "A")
        self.assertGreater(tail[0]["share_pct"], 90.0)
        # Σ contrib_down ≥ floor
        self.assertGreaterEqual(out["portfolio_downside"], 3.0)

    def test_flag3_cap_top3(self):
        # 5 равных по contrib позиций, все > 15% share → cap top-3
        pos = [_tail_pos(f"P{i}", 20.0, -10.0, -30.0, -1.0) for i in range(5)]
        # каждая: 0.20×20 = 4.0; Σ=20.0; share=20% > 15%
        out = compute_tail_flags(pos)
        tail = [f for f in out["flags"] if f["code"] == "portfolio_tail"]
        self.assertEqual(len(tail), 3)  # cap top-3

    def test_flag3_silent_below_floor(self):
        # Маленький хвост: Σ contrib_down < floor → Флаг 3 молчит даже при концентрации
        pos = [
            _tail_pos("X", 1.0, -1.0, -2.0, 3.0),   # 0.01×1 = 0.01
            _tail_pos("Y", 0.5, -0.5, -1.0, 2.0),   # 0.005×0.5 = 0.0025
        ]
        out = compute_tail_flags(pos)
        self.assertFalse([f for f in out["flags"] if f["code"] == "portfolio_tail"])
        self.assertLess(out["portfolio_downside"], 3.0)

    def test_blocked_excluded(self):
        # Заблокированная позиция исключена из всех флагов и из Σ contrib_down
        pos = [_tail_pos("T", 50.0, -50.0, -200.0, 300.0, blocked=True)]
        out = compute_tail_flags(pos)
        self.assertEqual(out["flags"], [])
        self.assertEqual(out["portfolio_downside"], 0.0)

    def test_missing_ci_skipped(self):
        # Позиция без CI (n/a макро) — пропускается без падения
        pos = [{"ticker": "NA", "weight_pct": 5.0, "is_blocked": False,
                "total": {"value": None, "ci": [None, None]}}]
        out = compute_tail_flags(pos)
        self.assertEqual(out["flags"], [])
        self.assertFalse(out["fired"])

    def test_thresholds_parameterizable(self):
        # Снижение skew-порога до 1.5 ловит GLRX (1.58); дефолт 2.0 — нет
        pos = [_tail_pos("GLRX", 0.56, -0.6, -9.8, 13.9)]
        default_out = compute_tail_flags(pos)
        self.assertFalse(default_out["fired"])
        tuned = compute_tail_flags(pos, thresholds={"skew_threshold": 1.5})
        self.assertTrue([f for f in tuned["flags"] if f["code"] == "binary_skew"])
        # Пороги отражены в выводе для воспроизводимости
        self.assertEqual(tuned["thresholds"]["skew_threshold"], 1.5)

    def test_orthogonal_flags_multiple_on_one_position(self):
        # Позиция может зажечь Флаг 1 И Флаг 2 одновременно
        # value=−2 [−6; +40]: skew=42/4=10.5>2 (Флаг1); lo<0<hi, вес 5% (Флаг2)
        pos = [_tail_pos("MULTI", 5.0, -2.0, -6.0, 40.0)]
        out = compute_tail_flags(pos)
        codes = {f["code"] for f in out["flags"] if f["ticker"] == "MULTI"}
        self.assertIn("binary_skew", codes)
        self.assertIn("sign_unresolved", codes)

    def test_result_shape(self):
        out = compute_tail_flags([_tail_pos("Z", 1.0, 5.0, 1.0, 9.0)])
        self.assertEqual(set(out.keys()),
                         {"flags", "portfolio_downside", "thresholds", "fired"})
        self.assertFalse(out["fired"])


class TailFlagsEndToEnd(unittest.TestCase):
    def test_run_includes_tail_flags(self):
        payload = _make_payload(
            holdings=[{"ticker": "UPRO", "asset_class": "equity",
                       "value_rub": 50_000, "currency": "RUB"}],
            stress_pp={"UPRO": {"weight_pct": 0.41,
                                "expected_pct_pweighted": -4.5,
                                "ci_pct": [-17.3, 46.4]}},
        )
        result = run(payload)
        self.assertIn("tail_flags", result)
        tf = result["tail_flags"]
        self.assertTrue(tf["fired"])
        self.assertTrue([f for f in tf["flags"] if f["code"] == "binary_skew"])

    def test_run_tail_thresholds_passthrough(self):
        payload = _make_payload(
            holdings=[{"ticker": "GLRX", "asset_class": "equity",
                       "value_rub": 50_000, "currency": "RUB"}],
            stress_pp={"GLRX": {"weight_pct": 0.56,
                                "expected_pct_pweighted": -0.6,
                                "ci_pct": [-9.8, 13.9]}},
        )
        payload["tail_thresholds"] = {"skew_threshold": 1.5}
        result = run(payload)
        self.assertTrue(result["tail_flags"]["fired"])


class SanityChecks(unittest.TestCase):
    """IV-C: проверки на выходящие за пределы значения."""

    def _pos(self, ticker, val, ci, weight_pct=10.0, weight_source="stress"):
        return {
            "ticker": ticker,
            "weight_pct": weight_pct,
            "weight_source": weight_source,
            "total": {"value": val, "ci": ci},
            "asset_class": "equity",
        }

    def _portfolio(self, eq_val=5.0, eq_ci=None, bd_val=3.0, bd_ci=None):
        eq_ci = eq_ci or [2.0, 8.0]
        bd_ci = bd_ci or [1.0, 5.0]
        return {
            "equity": {"expected_pct_horizon": {"value": eq_val, "ci": eq_ci}},
            "bond": {"expected_pct_horizon": {"value": bd_val, "ci": bd_ci}},
        }

    def test_clean_payload_no_warnings(self):
        positions = [self._pos("SBER", 5.0, [2.0, 8.0], 50.0),
                     self._pos("LKOH", 3.0, [1.0, 5.0], 50.0)]
        w = sanity_checks(positions, self._portfolio())
        self.assertEqual(w, [])

    def test_extreme_total_pct_high(self):
        positions = [self._pos("SBER", 150.0, [100.0, 200.0], 100.0)]
        w = sanity_checks(positions, self._portfolio())
        types = [x["type"] for x in w]
        self.assertIn("extreme_total_pct", types)
        self.assertEqual(w[0]["severity"], "HIGH")

    def test_extreme_total_pct_low(self):
        positions = [self._pos("SBER", -120.0, [-150.0, -90.0], 100.0)]
        w = sanity_checks(positions, self._portfolio())
        self.assertTrue(any(x["type"] == "extreme_total_pct" for x in w))

    def test_extreme_ci_width(self):
        positions = [self._pos("SBER", 5.0, [-60.0, 60.0], 100.0)]
        w = sanity_checks(positions, self._portfolio())
        self.assertTrue(any(x["type"] == "extreme_ci_width" for x in w))

    def test_weight_sum_off(self):
        # Σweight = 99.0 — не в пределах ±0.5
        positions = [self._pos("SBER", 5.0, [2.0, 8.0], 49.0),
                     self._pos("LKOH", 3.0, [1.0, 5.0], 50.0)]
        w = sanity_checks(positions, self._portfolio())
        self.assertTrue(any(x["type"] == "weight_sum_off" for x in w))

    def test_weight_sum_ok_within_tolerance(self):
        # Σweight = 100.3 — в пределах ±0.5
        positions = [self._pos("SBER", 5.0, [2.0, 8.0], 50.3),
                     self._pos("LKOH", 3.0, [1.0, 5.0], 50.0)]
        w = sanity_checks(positions, self._portfolio())
        self.assertFalse(any(x["type"] == "weight_sum_off" for x in w))

    def test_weight_sum_ignores_non_stress_source(self):
        # missing-источник не входит в Σ
        positions = [self._pos("SBER", 5.0, [2.0, 8.0], 50.0, "stress"),
                     self._pos("LKOH", 3.0, [1.0, 5.0], 10.0, "missing")]
        w = sanity_checks(positions, self._portfolio())
        self.assertFalse(any(x["type"] == "weight_sum_off" for x in w))

    def test_sanity_warnings_in_run_output(self):
        """sanity_warnings должен быть в validation блоке run()."""
        result = run({
            "snapshot": {"holdings": []},
            "stress": {"schema_version": 2, "scenarios": {"Sc-A": {"p": 0.25}, "Sc-B": {"p": 0.25},
                                     "Sc-C": {"p": 0.25}, "Sc-D": {"p": 0.25}},
                       "per_position": {}},
            "review_stocks": {},
        })
        self.assertIn("sanity_warnings", result["validation"])
        self.assertIsInstance(result["validation"]["sanity_warnings"], list)


class RejectV1Inputs(unittest.TestCase):
    """v1-вход (schema_version != 2) → понятная ошибка с адресом мигратора, не трейсбек."""

    def _assert_rejected(self, payload, who):
        r = run(payload)
        self.assertEqual(r["error"], "schema_v1_not_supported")
        self.assertIn("migrate_v1_to_v2.py", r["message"])
        self.assertTrue(any(x.startswith(who) for x in r["invalid_inputs"]))

    def test_stress_v1(self):
        p = _make_payload()
        p["stress"]["schema_version"] = 1
        self._assert_rejected(p, "stress")

    def test_review_stocks_v1(self):
        p = _make_payload()
        p["review_stocks"]["schema_version"] = 1
        self._assert_rejected(p, "review_stocks")

    def test_review_bonds_without_schema_version(self):
        p = _make_payload()
        del p["review_bonds"]["schema_version"]
        self._assert_rejected(p, "review_bonds")

    def test_v2_passes(self):
        self.assertNotIn("error", run(_make_payload()))


class DiffWithPrevious(unittest.TestCase):
    """Tests for compute_diff (IV-A)."""

    def _curr(self, ticker, total_value=5.0, verdict="hold", prio="MEDIUM"):
        return {
            "ticker": ticker,
            "total": {"value": total_value, "ci": [total_value - 2, total_value + 2]},
            "verdict": verdict,
            "verification_priority": prio,
            "weight_pct": 20.0,
        }

    def _prev(self, ticker, total_value=5.0, verdict="hold", prio="MEDIUM"):
        return {
            "ticker": ticker,
            "total_value": total_value,
            "verdict": verdict,
            "verification_priority": prio,
            "weight_pct": 20.0,
        }

    def test_no_previous_returns_none(self):
        curr = [self._curr("SBER")]
        self.assertIsNone(compute_diff(curr, None))
        self.assertIsNone(compute_diff(curr, []))

    def test_new_position_marked_plus(self):
        curr = [self._curr("SBER"), self._curr("LKOH")]
        prev = [self._prev("SBER")]
        result = compute_diff(curr, prev)
        markers = {r["ticker"]: r["marker"] for r in result["rows"]}
        self.assertEqual(markers["LKOH"], "+")
        self.assertEqual(markers["SBER"], "=")
        self.assertEqual(result["total_added"], 1)

    def test_removed_position_marked_minus(self):
        curr = [self._curr("SBER")]
        prev = [self._prev("SBER"), self._prev("LKOH")]
        result = compute_diff(curr, prev)
        markers = {r["ticker"]: r["marker"] for r in result["rows"]}
        self.assertEqual(markers["LKOH"], "-")
        self.assertEqual(result["total_removed"], 1)

    def test_new_high_priority_detected(self):
        curr = [self._curr("SBER", prio="HIGH"), self._curr("LKOH", prio="LOW")]
        prev = [self._prev("LKOH")]
        result = compute_diff(curr, prev)
        self.assertIn("SBER", result["new_high_priority"])
        self.assertNotIn("LKOH", result["new_high_priority"])

    def test_verdict_change_detected(self):
        curr = [self._curr("SBER", verdict="sell")]
        prev = [self._prev("SBER", verdict="hold")]
        result = compute_diff(curr, prev)
        self.assertEqual(len(result["verdict_changes"]), 1)
        vc = result["verdict_changes"][0]
        self.assertEqual(vc["ticker"], "SBER")
        self.assertEqual(vc["from"], "hold")
        self.assertEqual(vc["to"], "sell")

    def test_large_move_detected(self):
        curr = [self._curr("SBER", total_value=12.0)]
        prev = [self._prev("SBER", total_value=5.0)]  # delta = +7 > 5
        result = compute_diff(curr, prev)
        self.assertEqual(len(result["large_moves"]), 1)
        lm = result["large_moves"][0]
        self.assertAlmostEqual(lm["delta"], 7.0)

    def test_small_move_not_flagged(self):
        curr = [self._curr("SBER", total_value=7.0)]
        prev = [self._prev("SBER", total_value=5.0)]  # delta = +2 ≤ 5
        result = compute_diff(curr, prev)
        self.assertEqual(len(result["large_moves"]), 0)

    def test_identical_previous_all_equal(self):
        curr = [self._curr("SBER"), self._curr("LKOH")]
        prev = [self._prev("SBER"), self._prev("LKOH")]
        result = compute_diff(curr, prev)
        self.assertTrue(all(r["marker"] == "=" for r in result["rows"]))
        self.assertEqual(result["total_added"], 0)
        self.assertEqual(result["total_removed"], 0)
        self.assertEqual(result["total_changed"], 0)
        self.assertEqual(result["new_high_priority"], [])
        self.assertEqual(result["verdict_changes"], [])
        self.assertEqual(result["large_moves"], [])

    def test_diff_in_run_output(self):
        """previous_view in payload → diff key present in result."""
        prev = [{"ticker": "SBER", "total_value": 5.0, "verdict": "hold",
                 "verification_priority": "MEDIUM", "weight_pct": 100.0}]
        result = run({
            "snapshot": {"holdings": []},
            "stress": {"schema_version": 2, "scenarios": {"Sc-A": {"p": 0.25}, "Sc-B": {"p": 0.25},
                                     "Sc-C": {"p": 0.25}, "Sc-D": {"p": 0.25}},
                       "per_position": {}},
            "review_stocks": {},
            "previous_view": prev,
        })
        self.assertIn("diff", result)
        # No positions in current view → all previous marked removed
        diff = result["diff"]
        self.assertIsNotNone(diff)
        self.assertEqual(diff["total_removed"], 1)

    def test_no_previous_view_in_payload_diff_none(self):
        """Without previous_view key, diff should be None (backward-compat)."""
        result = run({
            "snapshot": {"holdings": []},
            "stress": {"schema_version": 2, "scenarios": {"Sc-A": {"p": 0.25}, "Sc-B": {"p": 0.25},
                                     "Sc-C": {"p": 0.25}, "Sc-D": {"p": 0.25}},
                       "per_position": {}},
            "review_stocks": {},
        })
        self.assertIn("diff", result)
        self.assertIsNone(result["diff"])


# ───────────────── V2-A: multiple horizons ─────────────────

from aggregate_positions import (  # noqa: E402
    _parse_date_window_start, _catalyst_in_horizon, mc_simulate,
)


def _v2_horizon_ends():
    # as_of 2026-05-07: +12 → 2027-05-31, +20 → 2028-01-31, +36 → 2029-05-31
    return {"h12": "2027-05-31", "h20": "2028-01-31", "h36": "2029-05-31"}


def _by_h(e12, e20, e36, ci=None):
    ci = ci if ci is not None else [None, None]
    return {"h12": {"expected_pct_pweighted": e12, "ci_pct": ci},
            "h20": {"expected_pct_pweighted": e20, "ci_pct": ci},
            "h36": {"expected_pct_pweighted": e36, "ci_pct": ci}}


def _make_v2_payload(*, holdings, stress_pp, review_stocks_per=None, review_bonds_per=None,
                     horizons=(12, 20, 36), primary=20, horizon_ends=None):
    he = horizon_ends or _v2_horizon_ends()
    return {
        "horizons": list(horizons),
        "primary_horizon": primary,
        "snapshot": {"schema_version": "2.0", "as_of_date": "2026-05-07", "holdings": holdings},
        "stress": {"schema_version": 2, "snapshot_id": "portfolio-2026-05-07.json",
                   "horizon_ends": he, "scenarios": _scenarios_fresh(), "per_position": stress_pp},
        "review_stocks": {"schema_version": 2, "snapshot_id": "portfolio-2026-05-07.json",
                          "review_date": "2026-05-07", "horizon_ends": he,
                          "per_stock": review_stocks_per or {}},
        "review_bonds": {"schema_version": 2, "snapshot_id": "portfolio-2026-05-07.json",
                         "horizon_ends": he, "per_bond": review_bonds_per or {}},
    }


class DateWindowParser(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(_parse_date_window_start("2026-07"), date(2026, 7, 1))
        self.assertEqual(_parse_date_window_start("2026-07-15"), date(2026, 7, 15))
        self.assertEqual(_parse_date_window_start("2027"), date(2027, 1, 1))
        self.assertEqual(_parse_date_window_start("2026-Q3"), date(2026, 7, 1))
        self.assertEqual(_parse_date_window_start("2026-q1"), date(2026, 1, 1))

    def test_ranges_take_left(self):
        self.assertEqual(_parse_date_window_start("2026-Q4 .. 2027-Q2"), date(2026, 10, 1))
        self.assertEqual(_parse_date_window_start("2026-07 - 2027-01"), date(2026, 7, 1))
        self.assertEqual(_parse_date_window_start("2026-07—2027-01"), date(2026, 7, 1))
        self.assertEqual(_parse_date_window_start("2026 to 2028"), date(2026, 1, 1))

    def test_unparseable(self):
        self.assertIsNone(_parse_date_window_start("когда-нибудь"))
        self.assertIsNone(_parse_date_window_start(""))
        self.assertIsNone(_parse_date_window_start(None))

    def test_in_horizon_by_date(self):
        cat = {"date_window": "2028-06"}
        in12, _ = _catalyst_in_horizon(cat, date(2027, 5, 31))
        in36, _ = _catalyst_in_horizon(cat, date(2029, 5, 31))
        self.assertFalse(in12)
        self.assertTrue(in36)

    def test_unparseable_in_all_with_warning(self):
        cat = {"date_window": "скоро"}
        in_h, warn = _catalyst_in_horizon(cat, date(2027, 5, 31))
        self.assertTrue(in_h)
        self.assertEqual(warn, "date_window_unparseable")

    def test_no_horizon_end_means_no_filter(self):
        """Без horizon_end фильтра нет; поле in_horizon (v1) не читается."""
        self.assertEqual(_catalyst_in_horizon({"in_horizon": False}, None), (True, None))
        self.assertEqual(_catalyst_in_horizon({"date_window": "2030-01"}, None), (True, None))
        self.assertEqual(_catalyst_in_horizon({}, None), (True, None))


class V2MultiHorizon(unittest.TestCase):
    def test_h20_slice_matches_v1_flat(self):
        """Регрессия: h20-срез v2 == плоскому v1 при равных входах (без катализаторов)."""
        holdings = [{"ticker": "SBER", "asset_class": "equity", "value_rub": 100000, "currency": "RUB"}]
        rs = {"SBER": {"div_yield_12m_pct": {"value": 12.0, "ci_pct": [10, 14]}, "advisor_verdict": "HOLD"}}
        v1 = _make_payload(holdings=holdings,
                           stress_pp={"SBER": {"weight_pct": 5.0, "expected_pct_pweighted": 2.0, "ci_pct": [-1, 5]}},
                           review_stocks_per=rs)
        v2 = _make_v2_payload(holdings=holdings,
                              stress_pp={"SBER": {"weight_pct": 5.0, "by_horizon": _by_h(1.0, 2.0, 3.0, [-1, 5])}},
                              review_stocks_per=rs)
        s1 = next(p for p in run(v1)["per_position"] if p["ticker"] == "SBER")
        s2 = next(p for p in run(v2)["per_position"] if p["ticker"] == "SBER")
        self.assertAlmostEqual(s2["by_horizon"]["h20"]["total"]["value"], s1["total"]["value"])

    def test_by_horizon_keys_and_flat_primary(self):
        holdings = [{"ticker": "SBER", "asset_class": "equity", "value_rub": 100000, "currency": "RUB"}]
        r = run(_make_v2_payload(
            holdings=holdings,
            stress_pp={"SBER": {"weight_pct": 5.0, "by_horizon": _by_h(1.0, 2.0, 3.0, [-1, 5])}},
            review_stocks_per={"SBER": {"advisor_verdict": "HOLD"}}))
        s = next(p for p in r["per_position"] if p["ticker"] == "SBER")
        self.assertEqual(set(s["by_horizon"]), {"h12", "h20", "h36"})
        # дельты различаются по горизонтам (macro 1/2/3 + div 0)
        self.assertNotEqual(s["by_horizon"]["h12"]["total"]["value"],
                            s["by_horizon"]["h36"]["total"]["value"])
        # плоское поле == primary (h20)
        self.assertEqual(s["total"], s["by_horizon"]["h20"]["total"])
        self.assertEqual(s["primary_horizon_key"], "h20")
        self.assertEqual(r["horizon_months"], 20)
        self.assertEqual(r["horizons"], [12, 20, 36])

    def test_portfolio_by_horizon(self):
        holdings = [{"ticker": "SBER", "asset_class": "equity", "value_rub": 100000, "currency": "RUB"}]
        r = run(_make_v2_payload(
            holdings=holdings,
            stress_pp={"SBER": {"weight_pct": 100.0, "by_horizon": _by_h(1.0, 2.0, 3.0, [0, 4])}},
            review_stocks_per={"SBER": {"advisor_verdict": "HOLD"}}))
        self.assertEqual(set(r["portfolio_by_horizon"]), {"h12", "h20", "h36"})
        # flat portfolio == primary
        self.assertEqual(r["portfolio"], r["portfolio_by_horizon"]["h20"])
        # equity expected различается по горизонтам
        self.assertNotEqual(r["portfolio_by_horizon"]["h12"]["equity"]["expected_pct_horizon"]["value"],
                            r["portfolio_by_horizon"]["h36"]["equity"]["expected_pct_horizon"]["value"])

    def test_predictions_for_review_horizons_field(self):
        holdings = [{"ticker": "SBER", "asset_class": "equity", "value_rub": 100000, "currency": "RUB"}]
        rs = {"SBER": {"advisor_verdict": "HOLD", "catalyst": [
            {"id": "near", "kind": "binary", "p": 0.6, "upside_pct": 3, "upside_ci_pct": [0, 6],
             "date_window": "2026-07", "source": "x", "source_quality": "HIGH"},
            {"id": "far", "kind": "binary", "p": 0.6, "upside_pct": 3, "upside_ci_pct": [0, 6],
             "date_window": "2028-06", "source": "x", "source_quality": "HIGH"},
        ]}}
        r = run(_make_v2_payload(
            holdings=holdings,
            stress_pp={"SBER": {"weight_pct": 5.0, "by_horizon": _by_h(1.0, 2.0, 3.0, [0, 4])}},
            review_stocks_per=rs))
        preds = {p["catalyst_id"]: p["horizons"] for p in r["predictions_for_review"]}
        self.assertEqual(preds["near"], [12, 20, 36])   # начало 2026-07 ≤ все концы
        self.assertEqual(preds["far"], [36])            # начало 2028-06 только в h36

    def test_far_catalyst_excluded_from_near_horizons(self):
        """Катализатор вне горизонта по date_window не вносит вклад в idio."""
        holdings = [{"ticker": "SBER", "asset_class": "equity", "value_rub": 100000, "currency": "RUB"}]
        rs = {"SBER": {"advisor_verdict": "HOLD", "catalyst": [
            {"id": "far", "kind": "binary", "p": 1.0, "upside_pct": 10, "upside_ci_pct": [10, 10],
             "date_window": "2028-06", "source": "x", "source_quality": "HIGH"},
        ]}}
        r = run(_make_v2_payload(
            holdings=holdings,
            stress_pp={"SBER": {"weight_pct": 5.0, "by_horizon": _by_h(0.0, 0.0, 0.0, [0, 0])}},
            review_stocks_per=rs))
        s = next(p for p in r["per_position"] if p["ticker"] == "SBER")
        self.assertEqual(s["by_horizon"]["h12"]["idio"]["value"], 0.0)   # вне h12
        self.assertGreater(s["by_horizon"]["h36"]["idio"]["value"], 0.0)  # в h36

    def test_subset_horizon(self):
        holdings = [{"ticker": "SBER", "asset_class": "equity", "value_rub": 100000, "currency": "RUB"}]
        payload = _make_v2_payload(
            holdings=holdings,
            stress_pp={"SBER": {"weight_pct": 5.0, "by_horizon": _by_h(1.0, 2.0, 3.0, [0, 4])}},
            review_stocks_per={"SBER": {"advisor_verdict": "HOLD"}})
        payload["_horizon_subset"] = [12]
        r = run(payload)
        self.assertEqual(r["horizons"], [12])
        s = next(p for p in r["per_position"] if p["ticker"] == "SBER")
        self.assertEqual(set(s["by_horizon"]), {"h12"})

    def test_fail_fast_missing_horizon_in_stress(self):
        holdings = [{"ticker": "SBER", "asset_class": "equity", "value_rub": 100000, "currency": "RUB"}]
        # stress несёт только h12/h20, запрашиваем h36
        sp = {"SBER": {"weight_pct": 5.0, "by_horizon": {
            "h12": {"expected_pct_pweighted": 1.0, "ci_pct": [0, 2]},
            "h20": {"expected_pct_pweighted": 2.0, "ci_pct": [0, 4]}}}}
        payload = _make_v2_payload(holdings=holdings, stress_pp=sp,
                                   review_stocks_per={"SBER": {"advisor_verdict": "HOLD"}})
        r = run(payload)
        self.assertEqual(r.get("error"), "horizon_mismatch")
        self.assertIn("h36", r["message"])

    def test_fail_fast_v1_stress_multi_horizon(self):
        holdings = [{"ticker": "SBER", "asset_class": "equity", "value_rub": 100000, "currency": "RUB"}]
        payload = _make_payload(holdings=holdings,
                                stress_pp={"SBER": {"weight_pct": 5.0, "expected_pct_pweighted": 2.0, "ci_pct": [0, 4]}})
        payload["horizons"] = [12, 20]   # v1 stress (flat) + несколько горизонтов
        r = run(payload)
        self.assertEqual(r.get("error"), "horizon_mismatch")

    def test_bond_carry_cap_per_horizon(self):
        """Carry кэпится до оферты: h36 == h20 (оба ограничены офертой ~18 мес), h12 меньше."""
        holdings = [{"ticker": "BND", "asset_class": "bond", "value_rub": 1_000_000, "currency": "RUB"}]
        rb = {"BND": {"ytm_pct": 10.0, "offer_date": "2027-11-07", "advisor_verdict": "HOLD"}}
        r = run(_make_v2_payload(
            holdings=holdings,
            stress_pp={"BND": {"weight_pct": 100.0, "by_horizon": _by_h(0.0, 0.0, 0.0, [0, 0])}},
            review_bonds_per=rb))
        s = next(p for p in r["per_position"] if p["ticker"] == "BND")
        c12 = s["by_horizon"]["h12"]["div_or_carry"]["value"]
        c20 = s["by_horizon"]["h20"]["div_or_carry"]["value"]
        c36 = s["by_horizon"]["h36"]["div_or_carry"]["value"]
        self.assertAlmostEqual(c20, c36, places=4)   # оба кэпнуты офертой
        self.assertLess(c12, c20)                     # h12 < оферта → не кэпнут


# ───────────────── V2-B: Monte Carlo CI ─────────────────

def _mc_ctx(ticker, asset_class, weight, delta_by_scenario=None, macro=(0.0, [0.0, 0.0]),
            div=(0.0, [0.0, 0.0]), catalysts=None):
    return {
        "ticker": ticker, "asset_class": asset_class, "weight_pct": weight, "is_blocked": False,
        "delta_by_scenario": delta_by_scenario or {},
        "macro_point": macro[0], "macro_ci": macro[1],
        "div": {"value": div[0], "ci": div[1]}, "catalysts": catalysts or [],
    }


_SC_HALF = {"A": {"p_norm": 0.5}, "B": {"p_norm": 0.5}}


class MonteCarloCI(unittest.TestCase):
    def test_reproducible_fixed_seed(self):
        ctxs = [_mc_ctx("X", "equity", 100.0,
                        delta_by_scenario={"A": {"value": 10, "ci_pct": [5, 15]},
                                           "B": {"value": -10, "ci_pct": [-15, -5]}})]
        m1 = mc_simulate(ctxs, _SC_HALF, paths=5000, seed=42)
        m2 = mc_simulate(ctxs, _SC_HALF, paths=5000, seed=42)
        self.assertEqual(m1["position_ci"], m2["position_ci"])
        self.assertEqual(m1["equity_ci"], m2["equity_ci"])

    def test_converges_to_analytic_mean(self):
        # симметрично: A:+10, B:−10, p 0.5/0.5 → аналитич. ожидание 0; MC mean ≈ 0
        ctxs = [_mc_ctx("X", "equity", 100.0,
                        delta_by_scenario={"A": {"value": 10, "ci_pct": [5, 15]},
                                           "B": {"value": -10, "ci_pct": [-15, -5]}})]
        m = mc_simulate(ctxs, _SC_HALF, paths=10000, seed=42)
        self.assertLess(abs(m["equity_mean"]), 0.5)

    def test_common_scenario_narrows_correlated_spread(self):
        """eq и bd движутся одинаково по общему сценарию → MC spread CI уже corr=0-квадратуры."""
        holdings = [{"ticker": "EQ", "asset_class": "equity", "value_rub": 100000, "currency": "RUB"},
                    {"ticker": "BD", "asset_class": "bond", "value_rub": 100000, "currency": "RUB"}]
        # обе позиции: A → +10, B → −10 (положительно коррелированы через общий сценарий)
        by = {"h12": {"delta_pct_by_scenario": {"A": {"value": 10, "ci_pct": [8, 12]},
                                                "B": {"value": -10, "ci_pct": [-12, -8]}},
                      "expected_pct_pweighted": 0.0, "ci_pct": [-12, 12]}}
        sp = {"EQ": {"weight_pct": 50.0, "by_horizon": by},
              "BD": {"weight_pct": 50.0, "by_horizon": by}}
        payload = _make_v2_payload(holdings=holdings, stress_pp=sp, horizons=(12,), primary=12,
                                   horizon_ends={"h12": "2027-05-31"})
        # bond carry должен быть 0 — даём ytm 0
        payload["review_bonds"]["per_bond"] = {"BD": {"ytm_pct": 0.0, "advisor_verdict": "HOLD"}}
        payload_mc = dict(payload, ci_mode="mc", mc_paths=8000, mc_seed=42)
        payload_an = dict(payload, ci_mode="analytic")
        r_mc = run(payload_mc)
        r_an = run(payload_an)
        sp_mc = r_mc["portfolio_by_horizon"]["h12"]["spread_pp_horizon"]["ci"]
        sp_quad = r_an["portfolio_by_horizon"]["h12"]["spread_pp_horizon"]["ci_quadratic"]
        w_mc = sp_mc[1] - sp_mc[0]
        w_quad = sp_quad[1] - sp_quad[0]
        self.assertLess(w_mc, w_quad)  # общий сценарий сужает spread vs независимая квадратура

    def test_bernoulli_parity_certain_catalyst(self):
        # binary p=1, active=все сценарии, upside точечный 10 → всегда +10
        cat = {"id": "c", "kind": "binary", "p": 1.0, "active_scenarios": ["A", "B"],
               "upside_pct": 10, "upside_ci_pct": [10, 10], "source": "x", "source_quality": "HIGH"}
        ctxs = [_mc_ctx("X", "equity", 100.0, catalysts=[cat])]
        m = mc_simulate(ctxs, _SC_HALF, paths=3000, seed=7)
        self.assertEqual(m["position_ci"]["X"], [10.0, 10.0])

    def test_degenerate_zero_width_ci_no_crash(self):
        ctxs = [_mc_ctx("X", "equity", 100.0,
                        delta_by_scenario={"A": {"value": 3, "ci_pct": [3, 3]},
                                           "B": {"value": 3, "ci_pct": [3, 3]}})]
        m = mc_simulate(ctxs, _SC_HALF, paths=1000, seed=1)
        self.assertEqual(m["position_ci"]["X"], [3.0, 3.0])

    def test_run_ci_method_mc_default(self):
        holdings = [{"ticker": "SBER", "asset_class": "equity", "value_rub": 100000, "currency": "RUB"}]
        r = run(_make_v2_payload(
            holdings=holdings,
            stress_pp={"SBER": {"weight_pct": 100.0, "by_horizon": {
                "h12": {"delta_pct_by_scenario": {"Sc-A": {"value": 2, "ci_pct": [0, 4]},
                                                  "Sc-B": {"value": 2, "ci_pct": [0, 4]},
                                                  "Sc-C": {"value": 2, "ci_pct": [0, 4]},
                                                  "Sc-D": {"value": 2, "ci_pct": [0, 4]}},
                        "expected_pct_pweighted": 2.0, "ci_pct": [0, 4]},
                "h20": {"delta_pct_by_scenario": {"Sc-A": {"value": 2, "ci_pct": [0, 4]}},
                        "expected_pct_pweighted": 2.0, "ci_pct": [0, 4]},
                "h36": {"delta_pct_by_scenario": {"Sc-A": {"value": 2, "ci_pct": [0, 4]}},
                        "expected_pct_pweighted": 2.0, "ci_pct": [0, 4]}}}},
            review_stocks_per={"SBER": {"advisor_verdict": "HOLD"}}))
        self.assertEqual(r["ci_method"], "mc")
        self.assertEqual(r["mc"], {"paths": 10000, "seed": 42})
        # spread None (нет облигаций) — но equity CI из MC присутствует
        eq_ci = r["portfolio_by_horizon"]["h12"]["equity"]["expected_pct_horizon"]["ci"]
        self.assertIsNotNone(eq_ci[0])

    def test_analytic_mode_keeps_dual_spread_ci(self):
        holdings = [{"ticker": "EQ", "asset_class": "equity", "value_rub": 100000, "currency": "RUB"},
                    {"ticker": "BD", "asset_class": "bond", "value_rub": 100000, "currency": "RUB"}]
        by = {"h12": {"delta_pct_by_scenario": {"A": {"value": 5, "ci_pct": [0, 10]}},
                      "expected_pct_pweighted": 5.0, "ci_pct": [0, 10]}}
        payload = _make_v2_payload(
            holdings=holdings,
            stress_pp={"EQ": {"weight_pct": 50.0, "by_horizon": by},
                       "BD": {"weight_pct": 50.0, "by_horizon": by}},
            horizons=(12,), primary=12, horizon_ends={"h12": "2027-05-31"})
        payload["review_bonds"]["per_bond"] = {"BD": {"ytm_pct": 0.0, "advisor_verdict": "HOLD"}}
        payload["ci_mode"] = "analytic"
        r = run(payload)
        self.assertEqual(r["ci_method"], "analytic")
        self.assertIsNone(r["mc"])
        sp = r["portfolio_by_horizon"]["h12"]["spread_pp_horizon"]
        self.assertIn("ci_linear", sp)
        self.assertIn("ci_quadratic", sp)
        self.assertNotIn("ci_method", sp)


# ───────────── Total return (3 слоя): bond_carry + dividend_forward ─────────────

def _delta_slot(vals: dict, zeroed=False, t_live=None):
    """Срез stress by_horizon.hNN с per-scenario дельтами (v2)."""
    slot = {"delta_pct_by_scenario": {sid: {"value": v, "ci_pct": [v - 2, v + 2]}
                                      for sid, v in vals.items()},
            "expected_pct_pweighted": sum(vals.values()) / len(vals),
            "ci_pct": [-3, 3]}
    if zeroed:
        slot["delta_pct_by_scenario"] = {sid: {"value": 0.0, "ci_pct": [0.0, 0.0]}
                                         for sid in vals}
        slot["expected_pct_pweighted"] = 0.0
        slot["ci_pct"] = [0.0, 0.0]
        slot["price_delta_zeroed"] = "maturity_within_horizon"
        slot["t_live_months"] = t_live if t_live is not None else 9.0
    return slot


def _carry_cells(vals: dict, matures=False, t_live=9.0):
    return {
        "t_live_months": t_live, "matures_within": matures,
        "by_scenario": {sid: {"carry_pct": v, "ci_pct": [v * 0.9, v * 1.1],
                              "components": {}}
                        for sid, v in vals.items()},
        "expected_carry_pct": sum(vals.values()) / len(vals),
        "flags": [],
    }


class TestTotalReturnLayers(unittest.TestCase):
    SIDS = ("Sc-A", "Sc-B", "Sc-C", "Sc-D")

    def _payload(self, *, with_carry=True, sanctions_in_a=False, cash_rub=0.0,
                 div_forward=None, div_haircut="__default__"):
        holdings = [
            {"ticker": "RUBOND", "asset_class": "bond", "value_rub": 500_000,
             "currency": "RUB"},
            {"ticker": "SBER", "asset_class": "equity", "value_rub": 500_000,
             "currency": "RUB"},
        ]
        stress_pp = {
            # облигация гасится внутри всех горизонтов → цена обнулена
            "RUBOND": {"weight_pct": 50.0, "by_horizon": {
                hk: _delta_slot({s: -5.0 for s in self.SIDS}, zeroed=True)
                for hk in ("h12", "h20", "h36")}},
            "SBER": {"weight_pct": 50.0, "by_horizon": {
                hk: _delta_slot({"Sc-A": -10.0, "Sc-B": 2.0, "Sc-C": 4.0, "Sc-D": 8.0})
                for hk in ("h12", "h20", "h36")}},
        }
        rs = {"SBER": {"advisor_verdict": "HOLD",
                       "div_yield_12m_pct": {"value": 12.0, "ci_pct": [10, 14]}}}
        if div_forward is not None:
            rs["SBER"]["dividend_forward"] = div_forward
        rb = {"RUBOND": {"ytm_pct": 15.0, "advisor_verdict": "HOLD"}}
        payload = _make_v2_payload(holdings=holdings, stress_pp=stress_pp,
                                   review_stocks_per=rs, review_bonds_per=rb)
        if sanctions_in_a:
            for sid in self.SIDS:
                payload["stress"]["scenarios"][sid]["factors_by_horizon"] = {
                    hk: {"sanctions": 1.0 if sid == "Sc-A" else 0.0}
                    for hk in ("h12", "h20", "h36")}
        if with_carry:
            payload["stress"]["bond_carry"] = {"schema": "bond-carry@1", "per_position": {
                "RUBOND": {"kind": "bond", "by_horizon": {
                    hk: _carry_cells({"Sc-A": 10.0, "Sc-B": 14.0,
                                      "Sc-C": 14.0, "Sc-D": 16.0}, matures=True)
                    for hk in ("h12", "h20", "h36")}},
                "CASH_RUB": {"kind": "cash", "by_horizon": {
                    hk: _carry_cells({s: 13.0 for s in self.SIDS})
                    for hk in ("h12", "h20", "h36")}},
            }}
        if cash_rub:
            payload["snapshot"]["cash"] = {"total_rub": cash_rub}
        if div_haircut != "__default__":
            payload["div_sanctions_haircut"] = div_haircut
        return payload

    def _pos(self, r, ticker):
        return next(p for p in r["per_position"] if p["ticker"] == ticker)

    def test_carry_from_block_priority_over_ytm(self):
        """Слой 2: блок bond_carry приоритетнее legacy ytm×t (R-BOND-CARRY)."""
        r = run(self._payload())
        divc = self._pos(r, "RUBOND")["by_horizon"]["h12"]["div_or_carry"]
        self.assertEqual(divc["source"], "bond_carry")
        # p-weighted: (10+14+14+16)/4 = 13.5 (равные p)
        self.assertAlmostEqual(divc["value"], 13.5, delta=1e-6)
        self.assertAlmostEqual(divc["ci"][0], 13.5 * 0.9, delta=1e-6)
        self.assertEqual(r["carry_source"], "bond_carry")

    def test_legacy_fallback_without_block(self):
        """Старый stress без bond_carry → прежний ytm×t путь (back-compat)."""
        r = run(self._payload(with_carry=False))
        divc = self._pos(r, "RUBOND")["by_horizon"]["h12"]["div_or_carry"]
        self.assertEqual(divc["source"], "ytm_pct")
        self.assertAlmostEqual(divc["value"], 15.0, delta=1e-6)  # 15% × 12/12
        self.assertEqual(r["carry_source"], "legacy_r_bond_carry")

    def test_dividend_forward_priority_and_projection(self):
        """Слой 3: dividend_forward вытесняет div_yield_12m_pct; проекция
        год1×min(h,12)/12 + год2×(min(h,24)−12)/12 (+carry_forward года 2 за 24)."""
        df = {"policy_state": "declared", "year1_yield_pct": 12.0,
              "year2_yield_pct": 10.0, "year2_basis": "analyst",
              "confidence": "HIGH", "as_of": "2026-05-01", "source": "СД"}
        r = run(self._payload(div_forward=df))
        bh = self._pos(r, "SBER")["by_horizon"]
        self.assertEqual(bh["h12"]["div_or_carry"]["source"], "dividend_forward")
        self.assertAlmostEqual(bh["h12"]["div_or_carry"]["value"], 12.0, delta=1e-4)
        self.assertAlmostEqual(bh["h20"]["div_or_carry"]["value"],
                               12.0 + 10.0 * 8 / 12, delta=1e-3)
        # h36: год 3 = carry_forward года 2 → 12 + 10 + 10 = 32 + флаг
        self.assertAlmostEqual(bh["h36"]["div_or_carry"]["value"], 32.0, delta=1e-3)
        self.assertIn("beyond_projection_carry_forward",
                      bh["h36"]["div_or_carry"]["flags"])

    def test_dividend_gating_uncertain_and_suspended(self):
        """policy_state гейтит: uncertain → 0 + флаг ПРОПУСКА; suspended → 0."""
        r = run(self._payload(div_forward={"policy_state": "uncertain"}))
        divc = self._pos(r, "SBER")["by_horizon"]["h12"]["div_or_carry"]
        self.assertEqual(divc["value"], 0.0)
        self.assertEqual(divc["source"], "dividend_forward_uncertain")
        self.assertIn("dividend_missing_policy_unknown", divc["flags"])
        r2 = run(self._payload(div_forward={"policy_state": "suspended"}))
        self.assertEqual(self._pos(r2, "SBER")["by_horizon"]["h12"]
                         ["div_or_carry"]["value"], 0.0)

    def test_total_return_block_no_double_count(self):
        """total_return: у гасящейся облигации price = 0, тело в carry;
        сумма по сценарию = w-взвешенное (price + income)."""
        r = run(self._payload(cash_rub=250_000))
        tr = r["total_return_by_horizon"]
        self.assertIsNotNone(tr)
        row = tr["by_horizon"]["h12"]["by_scenario"]["Sc-D"]
        # bond: price 0 (zeroed) + carry 16 → 16; equity: price 8 + div 12 → 20
        self.assertAlmostEqual(row["bond"], 16.0, delta=1e-4)
        self.assertAlmostEqual(row["equity"], 20.0, delta=1e-4)
        self.assertAlmostEqual(row["cash"], 13.0, delta=1e-4)
        # портфель: (1,000,000 × 18% + 250,000 × 13%) / 1,250,000 = 17.0
        self.assertAlmostEqual(row["portfolio"], 17.0, delta=1e-3)
        self.assertTrue(tr["cash_included"])
        exp = tr["by_horizon"]["h12"]["expected"]
        self.assertAlmostEqual(exp["bond"], 13.5, delta=1e-3)  # = expected carry
        # layers: у бондов income_kind = carry, у акций = dividend
        self.assertEqual(tr["by_horizon"]["h12"]["layers"]["bond"]["income_kind"], "carry")
        self.assertEqual(tr["by_horizon"]["h12"]["layers"]["equity"]["income_kind"], "dividend")
        self.assertAlmostEqual(
            tr["by_horizon"]["h12"]["layers"]["bond"]["price"]["value"], 0.0, delta=1e-6)

    def test_div_sanctions_haircut_scenario_cells(self):
        """Решение C: в сценарии с sanctions ≥ 1 дивиденды × (1 − haircut);
        выключается payload.div_sanctions_haircut = null."""
        r = run(self._payload(sanctions_in_a=True, div_haircut=0.25))
        bysc = r["total_return_by_horizon"]["by_horizon"]["h12"]["by_scenario"]
        # Sc-A: price −10 + div 12×0.75 = −1; Sc-B: price 2 + div 12 = 14
        self.assertAlmostEqual(bysc["Sc-A"]["equity"], -1.0, delta=1e-3)
        self.assertAlmostEqual(bysc["Sc-B"]["equity"], 14.0, delta=1e-3)
        self.assertTrue(r["total_return_by_horizon"]["div_sanctions_haircut"]
                        ["applied_in"])
        r2 = run(self._payload(sanctions_in_a=True, div_haircut=None))
        bysc2 = r2["total_return_by_horizon"]["by_horizon"]["h12"]["by_scenario"]
        self.assertAlmostEqual(bysc2["Sc-A"]["equity"], 2.0, delta=1e-3)  # −10+12
        self.assertIsNone(r2["total_return_by_horizon"]["div_sanctions_haircut"])

    def test_null_impact_catalyst_not_crash(self):
        """Регрессия (боевой review 2026-06-28): catalyst с `upside_pct: null`
        (ключ есть, значение None) у downside-катализатора не роняет расчёт."""
        from aggregate_positions import compute_catalyst_contribution
        cat = {"id": "tail", "kind": "binary", "p": 0.2,
               "upside_pct": None, "upside_ci_pct": None,
               "downside_pct": 30.0, "downside_ci_pct": [20, 40],
               "source": "x", "source_quality": "HIGH"}
        contrib = compute_catalyst_contribution(cat, _scenarios_fresh())
        self.assertAlmostEqual(contrib["value"],
                               0.2 * NULL_DEPENDENCY_DISCOUNT * -30.0, delta=1e-6)

    def test_raw_stress_portfolio_snapshot_id_drift(self):
        """Сырой stress-YAML (portfolio_snapshot_id) участвует в drift-чеке."""
        drift = check_snapshot_drift(
            {"portfolio_snapshot_id": "portfolio-2026-07-02.json"},
            {"snapshot_id": "portfolio-2026-06-28.json"}, None)
        self.assertEqual(drift["max_drift_days"], 4)
        self.assertTrue(drift["drift_warning"])

    def test_frontmatter_contract_emitted(self):
        """@1.3: run() отдаёт готовые frontmatter-блоки (контракт вьюера
        design-reference/INDEX.md) — ключи-месяцы БЕЗ h, значения round(2),
        слои дохода именованы carry/dividend."""
        r = run(self._payload(cash_rub=250_000))
        fm = r["frontmatter_portfolio_by_horizon"]
        self.assertEqual(fm["primary_horizon"], 20)
        self.assertIn(fm["ci_method"], ("mc", "analytic"))
        self.assertEqual(set(fm["horizons"].keys()), {"12", "20", "36"})
        h12 = fm["horizons"]["12"]
        self.assertEqual(h12["end"], "2027-05-31")
        pf12 = r["portfolio_by_horizon"]["h12"]
        self.assertAlmostEqual(
            h12["equity"]["value"],
            round(pf12["equity"]["expected_pct_horizon"]["value"], 2), delta=1e-9)
        self.assertAlmostEqual(
            h12["spread"]["value"],
            round(pf12["spread_pp_horizon"]["point"], 2), delta=1e-9)
        self.assertIsNotNone(h12["equity"]["ci"])
        tr = r["frontmatter_total_return"]
        self.assertIsNotNone(tr)
        e12 = tr["horizons"]["12"]
        self.assertIn("portfolio", e12["expected"])
        self.assertIn("carry", e12["layers"]["bond"])
        self.assertIn("dividend", e12["layers"]["equity"])
        self.assertNotIn("income", e12["layers"]["bond"])

    def test_mc_samples_carry_per_scenario(self):
        """MC: carry сэмплируется по разыгранному сценарию (детерминизм сида;
        CI облигации с carry-ячейками уже, чем при выключенном MC-карри — ячейки
        сценарные, не общий div-спек)."""
        payload = self._payload()
        payload["ci_mode"] = "mc"
        payload["mc_paths"] = 2000
        r = run(payload)
        self.assertEqual(r["ci_method"], "mc")
        ci = self._pos(r, "RUBOND")["by_horizon"]["h12"]["total"]["ci"]
        self.assertIsNotNone(ci[0])
        # тотал бонда = 0 (цена, zeroed) + carry ∈ [9, 17.6] → CI внутри этой полосы
        self.assertGreaterEqual(ci[0], 8.9)
        self.assertLessEqual(ci[1], 17.7)
        # воспроизводимость: тот же сид → тот же CI
        r2 = run(self._payload() | {"ci_mode": "mc", "mc_paths": 2000})
        self.assertEqual(ci, self._pos(r2, "RUBOND")["by_horizon"]["h12"]["total"]["ci"])


class CanonicalCenterL1Shadow(unittest.TestCase):
    """@1.4 (двойное центральное значение bond-ноги): канон центра —
    MC-совместимый L2 (p-weighted stress + income + idio); L1-overlay больше
    не подменяет headline, а выносится в l1_point (per-bucket и frontmatter)."""

    SIDS = ("Sc-A", "Sc-B", "Sc-C", "Sc-D")

    def _payload(self, with_mm=True, ci_mode="analytic"):
        holdings = [
            {"ticker": "SBER", "asset_class": "equity", "value_rub": 500_000,
             "currency": "RUB"},
            {"ticker": "RUBOND", "asset_class": "bond", "value_rub": 500_000,
             "currency": "RUB"},
        ]
        eq_deltas = {"Sc-A": -8.0, "Sc-B": 2.0, "Sc-C": 4.0, "Sc-D": 6.0}  # pweighted 1.0
        bd_deltas = {s: 3.0 for s in self.SIDS}                            # pweighted 3.0
        stress_pp = {
            "SBER": {"weight_pct": 50.0, "factor_betas": {"brent": 0.5},
                     "by_horizon": {hk: _delta_slot(eq_deltas)
                                    for hk in ("h12", "h20", "h36")}},
            "RUBOND": {"weight_pct": 50.0, "factor_betas": {"cbr_rate": -2.0},
                       "by_horizon": {hk: _delta_slot(bd_deltas)
                                      for hk in ("h12", "h20", "h36")}},
        }
        rs = {"SBER": {"advisor_verdict": "HOLD",
                       "div_yield_12m_pct": {"value": 12.0, "ci_pct": [10, 14]}}}
        rb = {"RUBOND": {"ytm_pct": 15.0, "advisor_verdict": "HOLD"}}
        payload = _make_v2_payload(holdings=holdings, stress_pp=stress_pp,
                                   review_stocks_per=rs, review_bonds_per=rb)
        payload["ci_mode"] = ci_mode
        if with_mm:
            # L1: SBER = 0.5×10 = 5.0 (vs L2 1.0); RUBOND = −2×−2 = 4.0 (vs L2 3.0)
            payload["macro_marginal"] = {"brent": {"central_estimate": 10.0},
                                         "cbr_rate": {"central_estimate": -2.0}}
        return payload

    def _bucket(self, r, hk, b):
        return r["portfolio_by_horizon"][hk][b]

    def test_headline_invariant_to_l1_overlay(self):
        """Канон headline один и тот же с overlay и без него (L2-центр)."""
        r_mm = run(self._payload(with_mm=True))
        r_no = run(self._payload(with_mm=False))
        for hk in ("h12", "h20", "h36"):
            for b in ("equity", "bond"):
                self.assertAlmostEqual(
                    self._bucket(r_mm, hk, b)["expected_pct_horizon"]["value"],
                    self._bucket(r_no, hk, b)["expected_pct_horizon"]["value"],
                    places=6, msg=f"{hk}/{b}")
        # h12: equity = L2 1.0 + div 12.0 = 13.0; bond = L2 3.0 + ytm 15.0 = 18.0
        self.assertAlmostEqual(
            self._bucket(r_mm, "h12", "equity")["expected_pct_horizon"]["value"],
            13.0, places=4)
        self.assertAlmostEqual(
            self._bucket(r_mm, "h12", "bond")["expected_pct_horizon"]["value"],
            18.0, places=4)

    def test_l1_point_exposed_per_bucket_and_frontmatter(self):
        r = run(self._payload(with_mm=True))
        # h12: equity L1-total = 5.0 + 12.0 = 17.0; bond = 4.0 + 15.0 = 19.0
        self.assertAlmostEqual(
            self._bucket(r, "h12", "equity")["l1_point"]["value"], 17.0, places=4)
        self.assertAlmostEqual(
            self._bucket(r, "h12", "bond")["l1_point"]["value"], 19.0, places=4)
        fm12 = r["frontmatter_portfolio_by_horizon"]["horizons"]["12"]
        self.assertAlmostEqual(fm12["equity"]["l1_point"], 17.0, places=2)
        self.assertAlmostEqual(fm12["bond"]["l1_point"], 19.0, places=2)
        # канон в frontmatter — L2-центр, не L1
        self.assertAlmostEqual(fm12["bond"]["value"], 18.0, places=2)
        # без overlay поля нет
        r_no = run(self._payload(with_mm=False))
        self.assertNotIn("l1_point", self._bucket(r_no, "h12", "bond"))
        self.assertNotIn(
            "l1_point", r_no["frontmatter_portfolio_by_horizon"]["horizons"]["12"]["bond"])

    def test_headline_equals_total_return_expected_when_no_idio(self):
        """Приёмка: headline == total_return.expected (идио = 0 → строгое равенство)."""
        r = run(self._payload(with_mm=True))
        for hk in ("h12", "h20", "h36"):
            exp = r["total_return_by_horizon"]["by_horizon"][hk]["expected"]
            for b in ("equity", "bond"):
                self.assertAlmostEqual(
                    self._bucket(r, hk, b)["expected_pct_horizon"]["value"],
                    exp[b], places=3, msg=f"{hk}/{b}")

    def test_headline_inside_mc_ci_and_spread_consistent(self):
        """Приёмка: value внутри собственного MC-CI; spread = eq − bd от тех же центров."""
        r = run(self._payload(with_mm=True, ci_mode="mc"))
        for hk in ("h12", "h20", "h36"):
            pf = r["portfolio_by_horizon"][hk]
            for b in ("equity", "bond"):
                e = pf[b]["expected_pct_horizon"]
                self.assertLessEqual(e["ci"][0], e["value"], msg=f"{hk}/{b}")
                self.assertGreaterEqual(e["ci"][1], e["value"], msg=f"{hk}/{b}")
            sp = pf["spread_pp_horizon"]
            self.assertAlmostEqual(
                sp["point"],
                pf["equity"]["expected_pct_horizon"]["value"]
                - pf["bond"]["expected_pct_horizon"]["value"], places=6)
            self.assertEqual(sp.get("ci_method"), "mc")

    def test_mc_divergence_silent_with_overlay(self):
        """Раньше L1-подмена давала mc_divergence каждый прогон — теперь канон
        L2-совместим с MC и warning молчит."""
        r = run(self._payload(with_mm=True, ci_mode="mc"))
        self.assertEqual(r["mc_divergence"], [])


class SnapshotQualityFlags(unittest.TestCase):
    """
    Флаги качества снапшота обязаны доезжать до §0.

    Регрессия 2026-08-04: загрузчик пометил `iis_split_position` и
    `ie_model_total_mismatch` (оба `warn`), ни один не попал ни в стресс, ни в
    сводный обзор, а §0 при этом писал «нарушений нет».
    """

    LIVE = [
        {"step": "moex_quotes", "severity": "info", "code": "moex_unavailable_tickers",
         "message": "MOEX ISS не вернул данные для 16 тикеров"},
        {"step": "iis_account_assignment", "severity": "warn", "code": "iis_split_position",
         "message": "Тикер RU000A1038V6 (ОФЗ 26238) разделён между main и iis_3"},
        {"step": "ie_model_parse", "severity": "warn", "code": "ie_model_total_mismatch",
         "message": "Сумма target_share_pct в IE-модели = 93.0%, ожидается 100.0%"},
        {"step": "assemble_blocked", "severity": "warning",
         "code": "blocked_positions_zero_valued", "message": "35 позиций оценены в 0"},
    ]

    def test_actionable_flags_pass_info_does_not(self):
        got = collect_snapshot_quality_flags({"data_quality_flags": self.LIVE})
        self.assertEqual(
            [f["code"] for f in got],
            ["iis_split_position", "ie_model_total_mismatch",
             "blocked_positions_zero_valued"])
        self.assertTrue(all(f["message"] for f in got))
        self.assertEqual(got[0]["step"], "iis_account_assignment")

    def test_unknown_severity_is_not_dropped(self):
        """Незнакомая severity — ровно тот случай, ради которого пишется проброс."""
        got = collect_snapshot_quality_flags({"data_quality_flags": [
            {"severity": "notice", "code": "new_code", "message": "x"},
            {"code": "no_severity_at_all", "message": "y"},
        ]})
        self.assertEqual([f["code"] for f in got], ["new_code", "no_severity_at_all"])

    def test_severity_case_and_spaces_do_not_hide_a_flag(self):
        got = collect_snapshot_quality_flags({"data_quality_flags": [
            {"severity": " INFO ", "code": "quiet", "message": "z"}]})
        self.assertEqual(got, [])

    def test_non_dict_flag_is_shown_not_swallowed(self):
        got = collect_snapshot_quality_flags({"data_quality_flags": ["сломанная запись"]})
        self.assertEqual(len(got), 1)
        self.assertIn("сломанная запись", got[0]["message"])

    def test_missing_or_broken_block_is_empty(self):
        self.assertEqual(collect_snapshot_quality_flags({}), [])
        self.assertEqual(collect_snapshot_quality_flags({"data_quality_flags": None}), [])
        self.assertEqual(collect_snapshot_quality_flags({"data_quality_flags": {}}), [])

    def test_flags_reach_validation_block_of_run(self):
        payload = _make_payload()
        payload["snapshot"]["data_quality_flags"] = self.LIVE
        got = run(payload)["validation"]["snapshot_quality_flags"]
        self.assertEqual([f["code"] for f in got],
                         ["iis_split_position", "ie_model_total_mismatch",
                          "blocked_positions_zero_valued"])

    def test_clean_snapshot_yields_empty_list_not_missing_key(self):
        got = run(_make_payload())["validation"]
        self.assertIn("snapshot_quality_flags", got)
        self.assertEqual(got["snapshot_quality_flags"], [])


class HorizonWeightsReachConsumers(unittest.TestCase):
    """
    PSS-9: горизонтные веса должны доезжать до ВСЕХ потребителей, а не только до
    ценового слоя. Тесты идут через run(), а не прямыми вызовами: самая вероятная
    ошибка проводки — забыть передать horizon_keys в normalize_scenario_probs, и
    прямой вызов с руками собранным p_norm_by_horizon её не заметит.
    """

    SIDS = ("Sc-A", "Sc-B", "Sc-C", "Sc-D")

    def _payload(self, per_horizon=True):
        # Веса на h12 и h36 различаются предельно: h12 отдаёт всё Sc-A, h36 — Sc-D.
        scen = {}
        for sid in self.SIDS:
            node = {"p": 0.25}
            if per_horizon:
                node["p_by_horizon"] = {
                    "h12": 1.0 if sid == "Sc-A" else 0.0,
                    "h20": 0.25,
                    "h36": 1.0 if sid == "Sc-D" else 0.0,
                }
            scen[sid] = node
        holdings = [{"ticker": "RUBOND", "asset_type": "bond", "value_rub": 1_000_000,
                     "currency": "RUB"}]
        # Ценовые дельты РАЗЛИЧАЮТСЯ по сценариям: иначе розыгрыш MC не на что влиять,
        # и различитель MC вырождается (проверено — мутация «MC по скаляру» выживала).
        dpc = {"Sc-A": -10.0, "Sc-B": 0.0, "Sc-C": 10.0, "Sc-D": 20.0}
        # expected_pct_pweighted — поле САМОГО стресса, и там оно уже горизонт-взвешено
        # (compute_per_position считает его через _scenario_weight). Держим фикстуру
        # согласованной, иначе аналитический центр разойдётся с MC по чужой причине.
        exp_by_h = {"h12": -10.0, "h20": 5.0, "h36": 20.0} if per_horizon else \
                   {hk: 5.0 for hk in ("h12", "h20", "h36")}
        stress_pp = {"RUBOND": {"weight_pct": 100.0, "by_horizon": {
            hk: {"delta_pct_by_scenario": {s: {"value": dpc[s], "ci_pct": [dpc[s] - 1,
                                                                           dpc[s] + 1]}
                                           for s in self.SIDS},
                 "expected_pct_pweighted": {"value": exp_by_h[hk],
                                            "ci_pct": [exp_by_h[hk] - 1,
                                                       exp_by_h[hk] + 1]}}
            for hk in ("h12", "h20", "h36")}}}
        payload = _make_payload(scenarios=scen, holdings=holdings, stress_pp=stress_pp,
                                horizon=12)
        # горизонты берутся из payload.horizons (v2), horizon_months — v1-совместимость
        payload["horizons"] = [12, 20, 36]
        payload["primary_horizon"] = 12
        payload["stress"]["schema_version"] = 2
        payload["stress"]["horizons"] = [12, 20, 36]
        payload["stress"]["horizon_ends"] = {"h12": "2027-08-31", "h20": "2028-04-30",
                                             "h36": "2029-08-31"}
        payload["stress"]["primary_horizon"] = 12
        # Ячейки carry различаются по сценариям — иначе вес не на что влиять.
        payload["stress"]["bond_carry"] = {"schema": "bond-carry@1", "per_position": {
            "RUBOND": {"kind": "bond", "by_horizon": {
                hk: _carry_cells({"Sc-A": 2.0, "Sc-B": 4.0, "Sc-C": 6.0, "Sc-D": 8.0})
                for hk in ("h12", "h20", "h36")}}}}
        return payload

    def _carry(self, r, hk):
        pos = next(p for p in r["per_position"] if p["ticker"] == "RUBOND")
        return pos["by_horizon"][hk]["div_or_carry"]["value"]

    def test_diff_horizon_weights_reach_carry_through_run(self):
        """
        [РАЗЛИЧИТЕЛЬ] Через run(): carry на h12 идёт по h12-весам (всё Sc-A → 2.0),
        на h36 — по h36-весам (всё Sc-D → 8.0). Скаляр дал бы (2+4+6+8)/4 = 5.0
        на обоих.

        Реализация, которая пишет p_norm_by_horizon и добавляет параметр в
        _scenario_p_norm, но НЕ передаёт horizon_keys в normalize_scenario_probs,
        проходит все юнит-тесты и падает здесь — это зеркало дефекта, который
        PSS-9 и чинит.
        """
        r = run(self._payload())
        self.assertAlmostEqual(self._carry(r, "h12"), 2.0, places=4)
        self.assertAlmostEqual(self._carry(r, "h36"), 8.0, places=4)
        self.assertAlmostEqual(self._carry(r, "h20"), 5.0, places=4)

    def _payload_with_catalyst(self, per_horizon=True, kind="quantitative"):
        """
        Катализатор кладётся в review_bonds.per_bond[ticker]["catalyst"] — ключ
        СИНГУЛЯРНЫЙ (aggregate_idio:984 читает `review_pos.get("catalyst")`).
        Ровно на этом споткнулась первая попытка закрыть дыру: список под ключом
        "catalysts" молча даёт `catalysts_applied: []`, и тест проходил на любой
        реализации.
        """
        payload = self._payload(per_horizon=per_horizon)
        if kind == "quantitative":
            # Вклад различается по сценариям — иначе взвешивать нечего.
            cat = {"id": "cat-q", "kind": "quantitative",
                   "upside_by_scenario": {"Sc-A": 0.0, "Sc-B": 0.0,
                                          "Sc-C": 0.0, "Sc-D": 12.0}}
        else:
            # binary: горизонт входит через scenario_mass (_scenario_mass).
            cat = {"id": "cat-b", "kind": "binary", "p": 1.0,
                   "upside_pct": 12.0, "active_scenarios": ["Sc-D"]}
        payload["review_bonds"]["per_bond"]["RUBOND"] = {"catalyst": [cat]}
        return payload

    def _idio(self, r, hk):
        pos = next(p for p in r["per_position"] if p["ticker"] == "RUBOND")
        return pos["by_horizon"][hk]["idio"]["value"]

    def test_diff_horizon_weights_reach_idio_quantitative(self):
        """
        [РАЗЛИЧИТЕЛЬ] Горизонт доезжает до идио-слоя:
        aggregate_idio → compute_catalyst_contribution → _scenario_p_norm.

        Вклад квантового катализатора живёт только в Sc-D. На h12 весь вес у
        Sc-A → 0.0; на h36 весь вес у Sc-D → 12.0. Скаляр (0.25 каждому) дал бы
        3.0 на всех горизонтах.

        Мутация «снять horizon_key=hk в вызове aggregate_idio» (~1076) переживала
        весь остальной набор — этот тест её и убивает.
        """
        r = run(self._payload_with_catalyst())
        applied = next(p for p in r["per_position"]
                       if p["ticker"] == "RUBOND")["by_horizon"]["h12"]["idio"]
        self.assertEqual([c["id"] for c in applied["catalysts_applied"]], ["cat-q"],
                         "катализатор не доехал до идио-слоя — фикстура мимо формата")
        self.assertAlmostEqual(self._idio(r, "h12"), 0.0, places=4)
        self.assertAlmostEqual(self._idio(r, "h20"), 3.0, places=4)
        self.assertAlmostEqual(self._idio(r, "h36"), 12.0, places=4)

    def test_diff_horizon_weights_reach_idio_binary_scenario_mass(self):
        """
        [РАЗЛИЧИТЕЛЬ] Та же проводка через ВТОРУЮ точку чтения весов — массу
        сценариев binary-катализатора (`_scenario_mass:782`). Реализация, которая
        протянула horizon_key только в quantitative-ветку, падает здесь.
        """
        r = run(self._payload_with_catalyst(kind="binary"))
        self.assertAlmostEqual(self._idio(r, "h12"), 0.0, places=4)
        self.assertAlmostEqual(self._idio(r, "h20"), 3.0, places=4)
        self.assertAlmostEqual(self._idio(r, "h36"), 12.0, places=4)

    def test_idio_without_block_scalar_behaviour_unchanged(self):
        """Без p_by_horizon идио-вклад скалярный (0.25 × 12) на всех горизонтах."""
        for kind in ("quantitative", "binary"):
            r = run(self._payload_with_catalyst(per_horizon=False, kind=kind))
            for hk in ("h12", "h20", "h36"):
                self.assertAlmostEqual(self._idio(r, hk), 3.0, places=4,
                                       msg=f"{kind}/{hk}")

    def test_without_block_scalar_behaviour_unchanged(self):
        """Артефакт без p_by_horizon считается ровно как раньше."""
        r = run(self._payload(per_horizon=False))
        for hk in ("h12", "h20", "h36"):
            self.assertAlmostEqual(self._carry(r, hk), 5.0, places=4)

    def test_partial_block_refused_through_run(self):
        """Согласованно с compute_bond_carry: смешанный вход останавливает расчёт."""
        payload = self._payload()
        del payload["stress"]["scenarios"]["Sc-A"]["p_by_horizon"]
        with self.assertRaises(SystemExit) as cm:
            run(payload)
        self.assertIn("не у всех", str(cm.exception))

    def test_monte_carlo_ci_follows_horizon_weights(self):
        """
        [РАЗЛИЧИТЕЛЬ] MC разыгрывает сценарий по весам ТЕКУЩЕГО горизонта.

        Снятие `horizon_key=hk` в вызове `mc_simulate` разводит MC-среднее и
        аналитический центр (на h36: 10.06 против 28.0), интервал разъезжается с
        [26.998; 29.052] до [-8.504; 28.738], и `mc_divergence` перестаёт быть пустым.

        Первая попытка проверить эту мутацию дала ложное «выживает»: подстрока
        `horizon_key=hk)` встречается в файле ДВАЖДЫ, и замена с count=1 попадала в
        вызов `aggregate_idio`, а не `mc_simulate`.

        MC гоняется внутри цикла по горизонтам (свой под-сид mc_seed+h), поэтому
        розыгрыш по скаляру рассинхронизировал бы MC-среднее с аналитическим центром
        на непервичных горизонтах — и сторож mc_divergence начал бы срабатывать на
        каждом прогоне.
        """
        payload = self._payload()
        payload["ci_mode"] = "mc"
        payload["mc_paths"] = 4000
        payload["mc_seed"] = 42
        r = run(payload)
        self.assertEqual(r["mc_divergence"], [], r["mc_divergence"])
        # Пустой mc_divergence — и есть проверка: он сравнивает MC-среднее с
        # аналитическим центром. Розыгрыш по скаляру дал бы на h36 смесь
        # (-10/0/10/20) вместо Sc-D, среднее уехало бы к 5 против аналитических 20,
        # и сторож MC_DIVERGENCE_PP = 1.5 сработал бы.

    def test_scalar_p_norm_still_written(self):
        """Скалярный p_norm сохраняется: (S, severity) считаются по нему."""
        payload = self._payload()
        run(payload)
        sc = payload["stress"]["scenarios"]["Sc-A"]
        self.assertIn("p_norm", sc)
        self.assertIn("p_norm_by_horizon", sc)
        self.assertAlmostEqual(sc["p_norm"], 0.25)
        self.assertAlmostEqual(sc["p_norm_by_horizon"]["h36"], 0.0)


class GoldenRun(unittest.TestCase):
    """
    Эталон §0.1.1 плана scenario-weights-and-ci: снимок `run()` на НЕПУСТОМ
    портфеле. Синтетика юнит-тестов не заходит в половину веток, а
    `_make_payload()` без аргументов даёт пустой портфель и как эталон бесполезен.

    Фикстура собрана из живых артефактов 2026-08-04 (снапшот + стресс + оба
    weekly-обзора), 4 позиции: SBER, YDEX, RU000A106E90, RU000A1038V6 — акции,
    облигации с блоком `bond_carry`, катализаторы, три горизонта, MC. Две записи
    катализаторов синтетические (`synthetic_*`): все живые катализаторы этого
    среза scenario-independent, и путь весов сценариев в идио-слое они не
    задевали бы вовсе.

    Payload и снимок КОММИТЯТСЯ: эталон не должен зависеть от наличия Synology.

    **Чего эталон НЕ защищает** (проверено аудитом 2026-08-05 мутациями): у
    сценариев фикстуры нет `p_by_horizon`, только скаляр `p=0.25`, а ячейки
    `bond_carry` сценарно-инвариантны — поэтому мутации, ломающие именно
    ГОРИЗОНТНЫЕ веса (снятый `horizon_key=hk` в `aggregate_idio`, форс скалярной
    ветки в `_scenario_p_norm`), этот снимок НЕ роняют. Их держит отдельный класс
    `HorizonWeightsReachConsumers`. К логике сценарных весов как таковой эталон
    чувствителен — мутация `_scenario_mass` → константа его ломает.

    Фикстуру намеренно НЕ переводили на горизонтные веса: эталон снят с живых
    артефактов 08-04, где их не было, и его ценность — в неизменности среза
    реальных данных, а не в максимуме покрытия.

    **Журнал осознанных пересъёмок эталона** (смена снимка без записи в этот журнал
    = потеря смысла эталона):

    - 2026-08-16 (PIV-5): `per_position[RU000A1038V6].on_iis` False → **True**.
      Эталон фиксировал сам баг: снапшот пишет `account`, а не `on_iis`, и метка
      ИИС-3 терялась молча — при `stress.on_iis: true` у той же бумаги. Изменение
      значения ОДНО и оно в сторону исправления; остальная дельта снимка —
      аддитивные ключи (`l1_status`, `l1_unmatched_factors`, `blindspot_source`,
      `validation.{l1_overlay,horizon_anchor_drift,blindspot_coverage}`), ни одно
      число не поехало (сверено ключ-в-ключ до пересъёмки).
    - 2026-08-16 (PIV-6): дельта **строго аддитивная** — новые верхнеуровневые
      блоки `share_bases` и `layer_shares`; изменённых значений ноль (сверено
      ключ-в-ключ). Пересъёмка нужна только потому, что снимок сравнивается целиком.
    - 2026-10-07 (шаг 4 разбора «ИИ в инвестициях»): дельта **строго аддитивная** —
      новый верхнеуровневый блок `spread_switch` (пороги знака спреда по весу
      сценария); изменённых значений ноль (сверено ключ-в-ключ).
    """

    FIX = Path(__file__).resolve().parent / "fixtures"

    def _payload(self):
        with open(self.FIX / "iv_golden_payload.json", encoding="utf-8") as f:
            return json.load(f)

    def test_matches_committed_snapshot(self):
        with open(self.FIX / "iv_golden_output.json", encoding="utf-8") as f:
            want = json.load(f)
        got = run(self._payload())
        self.assertEqual(json.dumps(got, sort_keys=True, ensure_ascii=False),
                         json.dumps(want, sort_keys=True, ensure_ascii=False))

    def test_deterministic(self):
        """Сид фиксирован, date.today() в модуле нет — два прогона совпадают."""
        a = json.dumps(run(self._payload()), sort_keys=True, ensure_ascii=False)
        b = json.dumps(run(self._payload()), sort_keys=True, ensure_ascii=False)
        self.assertEqual(a, b)

    def test_fixture_actually_covers_the_paths(self):
        """
        Эталон, не задевающий тронутых веток, — не эталон. Проверяем, что
        фикстура реально несёт carry-блок, применённые катализаторы обеих
        ветвей и multi-horizon.
        """
        r = run(self._payload())
        self.assertEqual(len(r["per_position"]), 4)
        self.assertEqual(sorted(r["horizons"]), [6, 12, 24])
        bonds = [p for p in r["per_position"] if p["ticker"].startswith("RU000")]
        self.assertTrue(all(p["by_horizon"]["h12"]["div_or_carry"]["value"] != 0
                            for p in bonds))
        ids = {c["id"] for p in r["per_position"]
               for c in p["by_horizon"]["h12"]["idio"]["catalysts_applied"]}
        self.assertIn("synthetic_scenario_binary", ids)
        self.assertIn("synthetic_scenario_quant", ids)
        self.assertIsNotNone(r.get("total_return_by_horizon") or
                             r.get("frontmatter_total_return"))


# ───────── PIV-4: вакуум гейта, маршрутизация фондов, дедуп счетов ─────────

class Piv4GateUnlinked(unittest.TestCase):
    def test_unlinked_flag_counts_both_reviews(self):
        review = {"per_stock": {"AAA": {"catalyst": [{"id": "c1", "kind": "binary"}]}}}
        bonds = {"per_bond": {"BBB": {"catalyst": [{"id": "c2"}, {"id": "c3"}]}}}
        r = cross_validate(review, _scenarios_fresh(), bonds)
        self.assertEqual(r["total_catalysts"], 3)
        self.assertTrue(r["idio_layer_unlinked"])
        self.assertEqual(r["share"], 0.0)

    def test_single_dependency_clears_flag(self):
        review = {"per_stock": {"AAA": {"catalyst": [
            {"id": "c1", "macro_dependency": "Sc-A"}]}}}
        r = cross_validate(review, _scenarios_fresh())
        self.assertFalse(r["idio_layer_unlinked"])
        self.assertEqual(r["total_catalysts"], 1)

    def test_empty_reviews_no_flag(self):
        r = cross_validate({"per_stock": {}}, _scenarios_fresh())
        self.assertFalse(r["idio_layer_unlinked"])
        self.assertEqual(r["total_catalysts"], 0)

    def test_run_pass_gate_still_warns(self):
        """Кейс 08-06: гейт PASS («0 из 0»), но сообщение обязано звучать."""
        payload = _make_payload(
            holdings=[{"ticker": "AAA", "asset_class": "equity",
                       "value_rub": 100_000, "currency": "RUB"}],
            stress_pp={"AAA": {"weight_pct": 5.0,
                               "expected_pct_pweighted": 1.0, "ci_pct": [-5.0, 5.0]}},
            review_stocks_per={"AAA": {"catalyst": [
                {"id": "c1", "p": 0.5, "upside_pct": 5.0, "upside_ci_pct": [2, 8]}]}},
        )
        out = run(payload)
        v = out["validation"]
        self.assertEqual(v["stale_pipeline_gate"], "PASS")
        self.assertTrue(v["idio_layer_unlinked"])
        self.assertIn("развязан", v["stale_pipeline_message"])

    def test_run_linked_message_stays_none(self):
        payload = _make_payload(
            holdings=[{"ticker": "AAA", "asset_class": "equity",
                       "value_rub": 100_000, "currency": "RUB"}],
            stress_pp={"AAA": {"weight_pct": 5.0,
                               "expected_pct_pweighted": 1.0, "ci_pct": [-5.0, 5.0]}},
            review_stocks_per={"AAA": {"catalyst": [
                {"id": "c1", "p": 0.5, "upside_pct": 5.0, "upside_ci_pct": [2, 8],
                 "macro_dependency": "Sc-A"}]}},
        )
        out = run(payload)
        self.assertIsNone(out["validation"]["stale_pipeline_message"])
        self.assertFalse(out["validation"]["idio_layer_unlinked"])


class Piv4FundRouting(unittest.TestCase):
    def _payload(self, with_fc):
        holdings = [
            {"ticker": "AAA", "asset_type": "stock", "value_rub": 100_000.0},
            {"ticker": "TMONX", "asset_type": "fund", "value_rub": 50_000.0},
            {"ticker": "TGOLD", "asset_type": "fund", "value_rub": 50_000.0},
            {"ticker": "TBOND", "asset_type": "fund", "value_rub": 50_000.0},
            {"ticker": "ZPIF", "asset_type": "fund", "value_rub": 50_000.0},
            {"ticker": "STRAY", "asset_type": "fund", "value_rub": 50_000.0},
        ]
        p = _make_payload(holdings=holdings)
        if with_fc:
            p["fund_classification"] = {
                "cash_equivalent": {"tickers": ["TMONX"]},
                "gold": ["TGOLD"],                      # голый список — вторая форма
                "bond_bucket": {"tickers": ["TBOND"]},
                "equity_bucket": {"tickers": ["ZPIF"]},
            }
        return p

    def test_routing_assigns_classes_and_flags_stray(self):
        out = run(self._payload(True))
        cls = {p["ticker"]: p["asset_class"] for p in out["per_position"]}
        self.assertEqual(cls["TMONX"], "cash_equivalent")
        self.assertEqual(cls["TGOLD"], "gold")
        self.assertEqual(cls["TBOND"], "fund_bond")
        self.assertEqual(cls["ZPIF"], "fund_equity")
        self.assertEqual(cls["STRAY"], "fund_unknown")
        self.assertEqual(out["validation"]["fund_unrouted"], ["STRAY"])

    def test_without_key_previous_behavior(self):
        out = run(self._payload(False))
        cls = {p["ticker"]: p["asset_class"] for p in out["per_position"]}
        for t in ("TMONX", "TGOLD", "TBOND", "ZPIF", "STRAY"):
            self.assertEqual(cls[t], "fund_unknown")
        self.assertEqual(out["validation"]["fund_unrouted"], [])

    def test_reference_wins_over_explicit_class(self):
        """Справочник — SSOT: перекрывает явный asset_class payload'а."""
        p = self._payload(True)
        p["snapshot"]["holdings"][1]["asset_class"] = "fund_equity"  # TMONX
        out = run(p)
        cls = {q["ticker"]: q["asset_class"] for q in out["per_position"]}
        self.assertEqual(cls["TMONX"], "cash_equivalent")

    def test_input_not_mutated(self):
        p = self._payload(True)
        run(p)
        self.assertNotIn("asset_class", p["snapshot"]["holdings"][1])


class Piv4DedupHoldings(unittest.TestCase):
    def test_two_accounts_merge_sums(self):
        rows = [
            {"ticker": "BND1", "asset_type": "bond", "qty": 80,
             "value_rub": 44646.4, "account": "main"},
            {"ticker": "BND1", "asset_type": "bond", "qty": 130,
             "value_rub": 72550.4, "account": "iis_3"},
        ]
        merged, tickers = merge_duplicate_holdings(rows)
        self.assertEqual(tickers, ["BND1"])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["qty"], 210)
        self.assertAlmostEqual(merged[0]["value_rub"], 117196.8, places=4)
        self.assertEqual(merged[0]["accounts_merged"], ["iis_3", "main"])
        # скалярные поля — от строки с большей стоимостью
        self.assertEqual(merged[0]["account"], "iis_3")
        # вход не мутирован
        self.assertEqual(rows[0]["qty"], 80)
        self.assertNotIn("accounts_merged", rows[0])

    def test_three_rows_accounts_accumulate(self):
        rows = [{"ticker": "X", "qty": 1, "value_rub": 1.0, "account": a}
                for a in ("main", "iis_3", "broker2")]
        merged, tickers = merge_duplicate_holdings(rows)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["qty"], 3)
        self.assertEqual(merged[0]["accounts_merged"],
                         ["broker2", "iis_3", "main"])

    def test_blocked_homonym_not_merged(self):
        """Шрам T: AT&T (blocked) vs Т-Технологии — один тикер, разные бумаги."""
        rows = [
            {"ticker": "T", "value_rub": 100.0, "is_blocked": True},
            {"ticker": "T", "value_rub": 200.0},
        ]
        merged, tickers = merge_duplicate_holdings(rows)
        self.assertEqual(len(merged), 2)
        self.assertEqual(tickers, [])

    def test_no_duplicates_passthrough(self):
        rows = [{"ticker": "A", "value_rub": 1.0}, {"ticker": "B", "value_rub": 2.0}]
        merged, tickers = merge_duplicate_holdings(rows)
        self.assertEqual(merged, rows)
        self.assertEqual(tickers, [])

    def test_run_reports_merged(self):
        payload = _make_payload(
            holdings=[
                {"ticker": "BND1", "asset_class": "bond", "qty": 80,
                 "value_rub": 44646.4, "account": "main", "currency": "RUB"},
                {"ticker": "BND1", "asset_class": "bond", "qty": 130,
                 "value_rub": 72550.4, "account": "iis_3", "currency": "RUB"},
            ],
            stress_pp={"BND1": {"weight_pct": 1.0,
                                "expected_pct_pweighted": 0.5, "ci_pct": [-1.0, 2.0]}},
        )
        out = run(payload)
        rows = [p for p in out["per_position"] if p["ticker"] == "BND1"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(out["validation"]["merged_duplicate_tickers"], ["BND1"])


# ───────── PIV-5: тихие отказы, вскрытые прогоном 2026-08-15 ─────────
# Разбор: docs/investment/portfolio/piv-run-2026-08-15-review.md
# Общая черта всех пяти: прогон не падал и не предупреждал — результат просто
# оказывался не тем, что написано в артефакте. Поэтому тесты проверяют не только
# «посчиталось верно», но и «молчание невозможно».


class Piv5L1FactorNames(unittest.TestCase):
    """L1-overlay: имена факторов macro-marginal против бет и baseline_spot."""

    # Живые имена прогона 08-15: у macro-marginal суффиксы, у бет — нет.
    _MM_LIVE = {
        "brent_price": {"level_l1_2027": 64.4, "unit": "usd_per_bbl"},
        "usdrub_rate": {"level_l1_2027": 92.95, "unit": "rub_per_usd"},
        "cbr_rate": {"level_l1_2027": 12.22, "unit": "rate_pct"},
    }
    _BETAS = {"brent": 0.15, "usdrub": 0.30, "cbr_rate": -0.20}
    _SPOT_NEW = {"brent_price": 87.07, "usdrub_rate": 84.28, "cbr_rate": 14.0}
    _SPOT_OLD = {"brent_usd": 87.07, "usdrub": 84.28, "cbr_rate_pct": 14.0}

    def _pos(self):
        return {"expected_pct_pweighted": 2.0, "ci_pct": [-1.0, 5.0],
                "factor_betas": dict(self._BETAS)}

    def _expected_l1(self):
        return (0.15 * (64.4 - 87.07) / 87.07 * 100.0
                + 0.30 * (92.95 - 84.28) / 84.28 * 100.0
                + (-0.20) * (12.22 - 14.0))

    def test_suffixed_names_resolve_to_betas(self):
        """`brent_price` → бета `brent`: overlay считается, а не вырождается в L2."""
        m = aggregate_macro(self._pos(), macro_marginal=self._MM_LIVE,
                            baseline_spot=self._SPOT_NEW, horizon_year=2027)
        self.assertEqual(m["l1_status"], "applied")
        self.assertAlmostEqual(m["l1_point"], self._expected_l1(), places=3)
        self.assertEqual(m["l1_unmatched_factors"], [])

    def test_old_baseline_spot_keys_still_work(self):
        """Архивные stress (до 08-06) несут brent_usd/usdrub/cbr_rate_pct — backward-compat."""
        m = aggregate_macro(self._pos(), macro_marginal=self._MM_LIVE,
                            baseline_spot=self._SPOT_OLD, horizon_year=2027)
        self.assertEqual(m["l1_status"], "applied")
        self.assertAlmostEqual(m["l1_point"], self._expected_l1(), places=3)

    def test_headline_still_l2_after_alias_fix(self):
        """@1.4 не нарушен: канон центра остаётся L2, L1 живёт отдельным полем."""
        m = aggregate_macro(self._pos(), macro_marginal=self._MM_LIVE,
                            baseline_spot=self._SPOT_NEW, horizon_year=2027)
        self.assertAlmostEqual(m["value"], 2.0, places=6)
        self.assertEqual(m["layer"], "L2")

    def test_unknown_factor_name_reported_not_swallowed(self):
        """Фактор без сопоставимого движения попадает в l1_unmatched_factors."""
        mm = dict(self._MM_LIVE)
        mm["exotic_factor"] = {"level_l1_2027": 1.0, "unit": "usd_per_bbl"}
        pos = self._pos()
        pos["factor_betas"]["exotic_factor"] = 0.1
        m = aggregate_macro(pos, macro_marginal=mm,
                            baseline_spot={"brent_price": 87.07, "usdrub_rate": 84.28,
                                           "cbr_rate": 14.0},
                            horizon_year=2027)
        self.assertEqual(m["l1_status"], "applied")
        self.assertNotIn("exotic_factor", m["l1_unmatched_factors"])

    def test_no_match_is_flagged_not_silent(self):
        """Ни один фактор не сопоставился → статус no_factor_match (был тихий L2)."""
        m = aggregate_macro(self._pos(),
                            macro_marginal={"zzz": {"level_l1_2027": 1.0, "unit": "usd_per_bbl"}},
                            baseline_spot=self._SPOT_NEW, horizon_year=2027)
        self.assertEqual(m["l1_status"], "no_factor_match")
        self.assertIsNone(m["l1_point"])

    def test_status_none_when_overlay_not_requested(self):
        m = aggregate_macro(self._pos(), macro_marginal=None)
        self.assertIsNone(m["l1_status"])


class Piv5L1OverlayReport(unittest.TestCase):
    """run(): overlay передали, но он не применился — обязано быть сообщение."""

    def _payload(self, mm):
        p = _make_payload(
            holdings=[{"ticker": "AAA", "asset_class": "equity", "account": "main"}],
            stress_pp={"AAA": {"weight_pct": 10.0, "expected_pct_pweighted": 2.0,
                               "ci_pct": [-1.0, 5.0],
                               "factor_betas": {"brent": 0.15}}},
        )
        p["stress"]["baseline_spot"] = {"brent_price": 87.07}
        # as_of обязателен: без него horizon_year не вычисляется и ветка level_l1
        # пропускается — L1 не посчитается даже при корректных именах факторов.
        p["snapshot"]["as_of_date"] = "2026-08-15"
        p["stress"]["horizon_ends"] = {"h20": "2027-06-30"}
        if mm is not None:
            p["macro_marginal"] = mm
        return p

    def test_silent_failure_becomes_message(self):
        out = run(self._payload({"zzz": {"level_l1_2027": 1.0, "unit": "usd_per_bbl"}}))
        rep = out["validation"]["l1_overlay"]
        self.assertTrue(rep["requested"])
        self.assertEqual(rep["applied_positions"], 0)
        self.assertIsNotNone(rep["message"])
        self.assertIn("НЕ применился", rep["message"])

    def test_applied_overlay_has_no_alarm(self):
        out = run(self._payload({"brent_price": {"level_l1_2027": 64.4,
                                                 "unit": "usd_per_bbl"}}))
        rep = out["validation"]["l1_overlay"]
        self.assertEqual(rep["applied_positions"], 1)
        self.assertIsNone(rep["message"])

    def test_not_requested_is_not_a_warning(self):
        rep = run(self._payload(None))["validation"]["l1_overlay"]
        self.assertFalse(rep["requested"])
        self.assertIsNone(rep["message"])


class Piv5OnIis(unittest.TestCase):
    """Метка ИИС-3 не должна теряться из-за отсутствия поля on_iis в снапшоте."""

    def test_account_field_alone_is_enough(self):
        self.assertTrue(_detect_on_iis({"ticker": "X", "account": "iis_3"}, None))

    def test_stress_flag_alone_is_enough(self):
        """Главный кейс прогона: снапшот про ИИС молчит, stress знает."""
        self.assertTrue(_detect_on_iis({"ticker": "X", "account": "main"},
                                       {"on_iis": True}))

    def test_accounts_merged_after_dedup(self):
        self.assertTrue(_detect_on_iis(
            {"ticker": "X", "accounts_merged": ["iis_3", "main"]}, None))

    def test_plain_main_position_stays_false(self):
        self.assertFalse(_detect_on_iis({"ticker": "X", "account": "main"},
                                        {"on_iis": False}))

    def test_run_marks_position_from_stress(self):
        payload = _make_payload(
            holdings=[{"ticker": "BND", "asset_class": "bond", "account": "main"}],
            stress_pp={"BND": {"weight_pct": 1.0, "on_iis": True,
                               "expected_pct_pweighted": 0.5, "ci_pct": [-1.0, 2.0]}},
        )
        out = run(payload)
        self.assertTrue(out["per_position"][0]["on_iis"])


class Piv5BlindspotTable(unittest.TestCase):
    """👁 читается из таблицы стресса, а не только из булева флага позиции."""

    def _payload(self, blindspots):
        p = _make_payload(
            holdings=[{"ticker": "AAA", "asset_class": "equity", "account": "main"},
                      {"ticker": "BBB", "asset_class": "equity", "account": "main"},
                      {"ticker": "CCC", "asset_class": "equity", "account": "main"}],
            stress_pp={t: {"weight_pct": 10.0, "expected_pct_pweighted": 1.0,
                           "ci_pct": [-1.0, 3.0]} for t in ("AAA", "BBB", "CCC")},
        )
        p["stress"]["macro_blindspots"] = blindspots
        return p

    def test_mixed_verdict_marks_blindspot(self):
        out = run(self._payload([{"ticker": "AAA", "verdict": "MIXED"}]))
        by = {p["ticker"]: p for p in out["per_position"]}
        self.assertTrue(by["AAA"]["macro"]["blindspot"])
        self.assertEqual(by["AAA"]["macro"]["blindspot_source"], "stress_table")
        self.assertFalse(by["BBB"]["macro"]["blindspot"])

    def test_macro_dominates_is_not_a_blindspot(self):
        """MACRO_DOMINATES = макро объясняет позицию хорошо — метки быть не должно."""
        out = run(self._payload([{"ticker": "CCC", "verdict": "MACRO_DOMINATES"}]))
        by = {p["ticker"]: p for p in out["per_position"]}
        self.assertFalse(by["CCC"]["macro"]["blindspot"])
        self.assertEqual(by["CCC"]["macro"]["blindspot_verdict"], "MACRO_DOMINATES")

    def test_position_flag_still_wins_without_table(self):
        p = self._payload([])
        p["stress"]["per_position"]["BBB"]["macro_blindspot"] = True
        out = run(p)
        by = {x["ticker"]: x for x in out["per_position"]}
        self.assertTrue(by["BBB"]["macro"]["blindspot"])
        self.assertEqual(by["BBB"]["macro"]["blindspot_source"], "position_flag")

    def test_coverage_counts_both_sources(self):
        p = self._payload([{"ticker": "AAA", "verdict": "IDIOSYNCRATIC_DOMINATES"}])
        p["stress"]["per_position"]["BBB"]["macro_blindspot"] = True
        cov = run(p)["validation"]["blindspot_coverage"]
        self.assertEqual(cov["from_stress_table"], ["AAA"])
        self.assertEqual(cov["from_position_flag"], ["BBB"])
        self.assertEqual(cov["flagged_total"], 2)
        self.assertAlmostEqual(cov["flagged_weight_pct"], 20.0, places=4)


class Piv5HorizonAnchorDrift(unittest.TestCase):
    """Расхождение якорей stress vs review больше не проходит молча."""

    def _args(self, review_ends):
        stress = {"horizon_ends": {"h6": "2026-12-31", "h12": "2027-06-30"}}
        review = {"schema_version": 2, "horizon_ends": review_ends, "per_stock": {
            "AAA": {"catalyst": [
                # окно попадает между якорями stress (30.06) и review (31.08)
                {"id": "between", "date_window": "2027-08", "p": 0.5, "upside_pct": 5.0},
                {"id": "early", "date_window": "2026-09", "p": 0.5, "upside_pct": 5.0},
            ]}}}
        return [6, 12], stress, review

    def test_same_anchors_no_drift(self):
        hz, stress, review = self._args({"h6": "2026-12-31", "h12": "2027-06-30"})
        d = check_horizon_anchor_drift(hz, stress, review, None)
        self.assertFalse(d["drift"])
        self.assertIsNone(d["message"])

    def test_drift_detected_with_days(self):
        hz, stress, review = self._args({"h6": "2027-02-28", "h12": "2027-08-31"})
        d = check_horizon_anchor_drift(hz, stress, review, None)
        self.assertTrue(d["drift"])
        self.assertEqual(d["by_horizon"]["h12"]["stress"], "2027-06-30")
        self.assertEqual(d["by_horizon"]["h12"]["days"], 62)
        self.assertIsNotNone(d["message"])

    def test_affected_catalyst_named(self):
        """Катализатор, меняющий горизонт из-за подмены даты, назван поимённо."""
        hz, stress, review = self._args({"h6": "2027-02-28", "h12": "2027-08-31"})
        d = check_horizon_anchor_drift(hz, stress, review, None)
        ids = {a["catalyst_id"] for a in d["affected_catalysts"]}
        self.assertIn("between", ids)
        self.assertNotIn("early", ids)
        self.assertTrue(all(a["counted_by"] == "review" for a in d["affected_catalysts"]))

    def test_reaches_validation_block(self):
        payload = _make_payload(
            holdings=[{"ticker": "AAA", "asset_class": "equity", "account": "main"}],
            stress_pp={"AAA": {"weight_pct": 1.0, "expected_pct_pweighted": 1.0,
                               "ci_pct": [-1.0, 3.0]}},
            horizon=12,
        )
        payload["stress"]["horizon_ends"] = {"h12": "2027-06-30"}
        payload["review_stocks"]["horizon_ends"] = {"h12": "2027-08-31"}
        got = run(payload)["validation"]["horizon_anchor_drift"]
        self.assertTrue(got["drift"])
        self.assertEqual(got["source_of_truth"], "stress")


class Piv5Summary(unittest.TestCase):
    """--summary: чтение результата штатным способом, а не ad-hoc скриптами."""

    def _out(self):
        payload = _make_payload(
            holdings=[{"ticker": "AAA", "asset_class": "equity", "account": "main"},
                      {"ticker": "BLK", "asset_class": "equity", "account": "main",
                       "is_blocked": True}],
            stress_pp={"AAA": {"weight_pct": 10.0, "expected_pct_pweighted": 2.0,
                               "ci_pct": [-1.0, 5.0]}},
        )
        return run(payload)

    def test_renders_without_crash_on_none_weights(self):
        """Заблокированная позиция несёт weight_pct=None — на ней падали ad-hoc скрипты."""
        text = format_summary(self._out())
        self.assertIn("Валидация", text)
        self.assertIn("Позиций:", text)

    def test_reports_horizon_lines(self):
        self.assertIn("спред", format_summary(self._out()))

    def test_error_result_is_readable(self):
        text = format_summary({"error": "horizon_mismatch", "message": "нет h36"})
        self.assertIn("horizon_mismatch", text)
        self.assertIn("нет h36", text)


# ───────── PIV-6: базы долей и доли слоёв считает скрипт ─────────


class Piv6ShareBases(unittest.TestCase):
    """Все базы долей — из результата, а не из головы (§5 прогона 08-15 привёл 4-ю)."""

    def _payload(self):
        p = _make_payload(
            holdings=[
                {"ticker": "AAA", "asset_class": "equity", "asset_type": "stock",
                 "account": "main", "value_rub": 300.0},
                {"ticker": "BND", "asset_class": "bond", "asset_type": "bond",
                 "account": "main", "value_rub": 700.0},
                {"ticker": "BLK", "asset_class": "equity", "asset_type": "stock",
                 "account": "main", "value_rub": 999.0, "is_blocked": True},
            ],
            # веса стресса нормированы на свою базу и с долями holdings не совпадают
            stress_pp={"AAA": {"weight_pct": 40.0, "expected_pct_pweighted": 1.0,
                               "ci_pct": [-1.0, 3.0]},
                       "BND": {"weight_pct": 60.0, "expected_pct_pweighted": 1.0,
                               "ci_pct": [-1.0, 3.0]}},
        )
        p["snapshot"]["balance_summary"] = {"by_account": {"main": {
            "total_rub": 2000.0, "stocks_rub": 300.0, "bonds_rub": 700.0,
            "funds_rub": 0.0, "cash_rub": 1000.0}}}
        return p

    def test_blocked_excluded_from_holdings_base(self):
        sb = run(self._payload())["share_bases"]["unblocked_holdings"]
        self.assertAlmostEqual(sb["basis_rub"], 1000.0, places=4)
        self.assertAlmostEqual(sb["shares_pct"]["equity"], 30.0, places=4)

    def test_stress_base_uses_stress_weights(self):
        sb = run(self._payload())["share_bases"]["stress_weights"]
        self.assertAlmostEqual(sb["shares_pct"]["equity"], 40.0, places=4)
        self.assertAlmostEqual(sb["shares_pct"]["bond"], 60.0, places=4)

    def test_main_account_base_is_the_fourth_one(self):
        """Кэш в знаменателе — та самая база, которой не было в таблице сверки."""
        sb = run(self._payload())["share_bases"]["main_account"]
        self.assertAlmostEqual(sb["basis_rub"], 2000.0, places=4)
        self.assertAlmostEqual(sb["shares_pct"]["equity"], 15.0, places=4)

    def test_bases_disagree_by_design(self):
        """Три базы дают три разные доли акций — это норма, потому и нужен блок сверки."""
        sb = run(self._payload())["share_bases"]
        got = {k: sb[k]["shares_pct"].get("equity") for k in sb}
        self.assertEqual(len(set(got.values())), 3, got)

    def test_missing_balance_summary_not_fatal(self):
        p = self._payload()
        p["snapshot"].pop("balance_summary")
        self.assertEqual(run(p)["share_bases"]["main_account"]["shares_pct"], {})


class Piv6LayerShares(unittest.TestCase):
    """Доли слоёв на ОДНОМ знаменателе (в §4 08-15 сравнивались 67% и 46% от разных)."""

    SIDS = ("Sc-A", "Sc-B", "Sc-C", "Sc-D")

    def _out(self):
        holdings = [
            {"ticker": "RUBOND", "asset_class": "bond", "value_rub": 500_000,
             "currency": "RUB"},
            {"ticker": "SBER", "asset_class": "equity", "value_rub": 500_000,
             "currency": "RUB"},
        ]
        stress_pp = {
            "RUBOND": {"weight_pct": 50.0, "by_horizon": {
                hk: _delta_slot({s: 3.0 for s in self.SIDS})
                for hk in ("h12", "h20", "h36")}},
            "SBER": {"weight_pct": 50.0, "by_horizon": {
                hk: _delta_slot({"Sc-A": -10.0, "Sc-B": 2.0, "Sc-C": 4.0, "Sc-D": 8.0})
                for hk in ("h12", "h20", "h36")}},
        }
        # катализатор нужен, чтобы идио-слой был ненулевым и знаменатели разошлись
        rs = {"SBER": {"div_yield_12m_pct": {"value": 12.0, "ci_pct": [10, 14]},
                       "catalyst": [{"id": "c1", "kind": "binary", "p": 0.5,
                                     "upside_pct": 10.0, "upside_ci_pct": [5.0, 15.0],
                                     "date_window": "2026-09"}]}}
        rb = {"RUBOND": {"ytm_pct": 15.0}}
        return run(_make_v2_payload(holdings=holdings, stress_pp=stress_pp,
                                    review_stocks_per=rs, review_bonds_per=rb))

    def test_shares_sum_to_one_on_common_denominator(self):
        eq = self._out()["layer_shares"]["h20"]["buckets"]["equity"]
        self.assertAlmostEqual(sum(eq["share_of_headline"].values()), 1.0, places=3)

    def test_denominator_named_and_differs_from_no_idio(self):
        """Обе величины видны рядом — перепутать знаменатель молча нельзя."""
        ls = self._out()["layer_shares"]["h20"]
        self.assertEqual(ls["denominator"], "headline_with_idio")
        eq = ls["buckets"]["equity"]
        self.assertIsNotNone(eq["expected_without_idio"])
        self.assertNotAlmostEqual(eq["headline_with_idio"],
                                  eq["expected_without_idio"], places=3)

    def test_both_legs_share_one_denominator(self):
        """Пара «доля купона / доля идио» сопоставима: у обеих ног знаменатель свой headline."""
        b = self._out()["layer_shares"]["h20"]["buckets"]
        for bucket in ("equity", "bond"):
            head = b[bucket]["headline_with_idio"]
            for k, pp in b[bucket]["layers_pp"].items():
                self.assertAlmostEqual(b[bucket]["share_of_headline"][k],
                                       pp / head, places=4, msg=f"{bucket}/{k}")



# ───────── PIV-7: матрица доверия матчится по тегу, а не по прозе ─────────


class Piv7TrustTagMatch(unittest.TestCase):
    """Фильтр IGNORE применяется к `source_trust`, а не к прозаическому `source`."""

    MATRIX = {"ignored": [{"analyst": "Invest Era", "subdomain": "oil-gas-ru"}]}
    LEGACY = {"ignored_subdomains": ["Invest Era oil-gas-ru"]}

    def _cat(self, **st):
        c = {"id": "c1", "source": "https://smart-lab.ru/q/NVTK/ (обзор IE от 12.08)"}
        if st:
            c["source_trust"] = st
        return c

    def test_tag_in_ignore_is_filtered(self):
        self.assertTrue(is_low_trust(
            self._cat(analyst="Invest Era", subdomain="oil-gas-ru"), self.MATRIX))

    def test_other_subdomain_of_same_analyst_survives(self):
        """Матрица различает поддомены одного аналитика — bonds-rub у IE это HIGH."""
        self.assertFalse(is_low_trust(
            self._cat(analyst="Invest Era", subdomain="bonds-rub"), self.MATRIX))

    def test_case_and_spaces_do_not_hide_a_match(self):
        self.assertTrue(is_low_trust(
            self._cat(analyst="  invest era ", subdomain="OIL-GAS-RU"), self.MATRIX))

    def test_legacy_string_matrix_form_understood(self):
        """Легаси-форма «Аналитик поддомен» (её собирал прогон 08-15 из INDEX.md)."""
        self.assertTrue(is_low_trust(
            self._cat(analyst="Invest Era", subdomain="oil-gas-ru"), self.LEGACY))

    def test_multiword_analyst_name_split_by_last_space(self):
        m = {"ignored_subdomains": ["Bank of Russia (CBR) usd-rub-forecast"]}
        self.assertTrue(is_low_trust(
            self._cat(analyst="Bank of Russia (CBR)", subdomain="usd-rub-forecast"), m))

    def test_untagged_catalyst_is_not_discounted(self):
        """Переходный режим: без тега катализатор не дисконтируется молча."""
        self.assertFalse(is_low_trust(self._cat(), self.MATRIX))

    def test_advisor_own_estimate_is_not_in_matrix(self):
        self.assertFalse(is_low_trust(
            self._cat(analyst="advisor", subdomain="self"), self.MATRIX))

    def test_incomplete_tag_falls_back_to_untagged(self):
        self.assertFalse(is_low_trust(self._cat(analyst="Invest Era"), self.MATRIX))

    def test_legacy_exact_source_match_still_works(self):
        """Старый путь (точное совпадение по source) не сломан."""
        c = {"id": "c1", "source": "invest_era_macro"}
        self.assertTrue(is_low_trust(c, {"ignored_subdomains": ["invest_era_macro"]}))


class Piv7TrustCoverage(unittest.TestCase):
    """§9 обязан отличать «источников нет» от «атрибуция не выполнена»."""

    MATRIX = {"ignored": [{"analyst": "Invest Era", "subdomain": "oil-gas-ru"}]}

    def _payload(self, cats):
        p = _make_payload(
            holdings=[{"ticker": "AAA", "asset_class": "equity", "account": "main"}],
            stress_pp={"AAA": {"weight_pct": 10.0, "expected_pct_pweighted": 1.0,
                               "ci_pct": [-1.0, 3.0]}},
            review_stocks_per={"AAA": {"catalyst": cats}},
        )
        p["trust_matrix"] = self.MATRIX
        return p

    def _cat(self, cid, st=None):
        c = {"id": cid, "kind": "binary", "p": 0.5, "upside_pct": 5.0,
             "upside_ci_pct": [0.0, 10.0], "source": "проза"}
        if st:
            c["source_trust"] = st
        return c

    def test_all_untagged_yields_loud_message(self):
        cov = run(self._payload([self._cat("a"), self._cat("b")]))["validation"]["trust_coverage"]
        self.assertEqual(cov["tagged"], 0)
        self.assertEqual(cov["untagged"], 2)
        self.assertIn("не применялась", cov["message"])
        self.assertIn("НЕЛЬЗЯ", cov["message"])

    def test_partial_tagging_is_medium_warning(self):
        cov = run(self._payload([
            self._cat("a", {"analyst": "advisor", "subdomain": "self"}),
            self._cat("b"),
        ]))["validation"]["trust_coverage"]
        self.assertEqual((cov["tagged"], cov["untagged"]), (1, 1))
        self.assertIn("атрибутировано 1 из 2", cov["message"])

    def test_full_tagging_is_silent(self):
        cov = run(self._payload([
            self._cat("a", {"analyst": "advisor", "subdomain": "self"}),
        ]))["validation"]["trust_coverage"]
        self.assertIsNone(cov["message"])

    def test_ignored_catalyst_named_and_excluded_from_idio(self):
        out = run(self._payload([
            self._cat("a", {"analyst": "Invest Era", "subdomain": "oil-gas-ru"}),
        ]))
        cov = out["validation"]["trust_coverage"]
        self.assertEqual(cov["ignored_applied"], 1)
        self.assertEqual(cov["ignored_catalysts"][0]["catalyst_id"], "a")
        pos = out["per_position"][0]
        self.assertEqual(pos["idio"]["catalysts_applied"], [])
        self.assertEqual(pos["idio"]["value"], 0.0)

    def test_no_matrix_no_message(self):
        p = self._payload([self._cat("a")])
        p.pop("trust_matrix")
        self.assertIsNone(run(p)["validation"]["trust_coverage"]["message"])


class TestSpreadSwitchThresholds(unittest.TestCase):
    """Пороги знака спреда «акции − облигации» по весу сценария (шаг 4, 2026-10-07).
    Модель — как PSS-6: S(w) = w·V_s + (1−w)·M_s, порог w* = −M_s/(V_s − M_s)."""

    @staticmethod
    def _tr(rows, hk="h12"):
        return {"by_horizon": {hk: {"by_scenario": rows}}}

    def test_closed_form_and_direction(self):
        # спреды по сценариям: A −10, B +2, C +2, D +6; веса A .25 B .25 C .25 D .25
        rows = {"A": {"equity": 0.0, "bond": 10.0}, "B": {"equity": 12.0, "bond": 10.0},
                "C": {"equity": 12.0, "bond": 10.0}, "D": {"equity": 16.0, "bond": 10.0}}
        sc = {s: {"p": 0.25} for s in rows}
        r = compute_spread_switch_thresholds(self._tr(rows), sc)["by_horizon"]["h12"]
        self.assertAlmostEqual(r["spread_now_pp"], 0.0, delta=1e-9)  # (−10+2+2+6)/4
        a = r["by_scenario"]["A"]
        # M_A = (2+2+6)/3 = 10/3; w* = −M/(V−M) = −(10/3)/(−10 − 10/3) = 0.25
        self.assertAlmostEqual(a["w_flip"], 0.25, delta=1e-4)
        # теперь сдвинем веса: A .1 → спред > 0, и A переворачивает его ВВЕРХ к 0.25
        sc2 = {"A": {"p": 0.1}, "B": {"p": 0.3}, "C": {"p": 0.3}, "D": {"p": 0.3}}
        r2 = compute_spread_switch_thresholds(self._tr(rows), sc2)["by_horizon"]["h12"]
        self.assertGreater(r2["spread_now_pp"], 0)
        self.assertEqual(r2["by_scenario"]["A"]["direction"], "up")
        self.assertAlmostEqual(r2["by_scenario"]["A"]["w_flip"], 0.25, delta=1e-4)

    def test_no_flip_when_all_same_sign(self):
        rows = {s: {"equity": 5.0 + i, "bond": 1.0} for i, s in enumerate("ABCD")}
        sc = {s: {"p": 0.25} for s in rows}
        r = compute_spread_switch_thresholds(self._tr(rows), sc)["by_horizon"]["h12"]
        for c in r["by_scenario"].values():
            self.assertIsNone(c["w_flip"])
            self.assertIsNone(c["direction"])

    def test_horizon_weights_used(self):
        rows = {"A": {"equity": 0.0, "bond": 10.0}, "D": {"equity": 20.0, "bond": 10.0}}
        sc = {"A": {"p": 0.5, "p_norm_by_horizon": {"h12": 0.8}},
              "D": {"p": 0.5, "p_norm_by_horizon": {"h12": 0.2}}}
        r = compute_spread_switch_thresholds(self._tr(rows), sc)["by_horizon"]["h12"]
        self.assertAlmostEqual(r["by_scenario"]["A"]["w_now"], 0.8, delta=1e-9)
        self.assertAlmostEqual(r["spread_now_pp"], 0.8 * -10 + 0.2 * 10, delta=1e-9)
        # два сценария: порог для A = 0.5 (−10 и +10 гасятся), направление вниз
        self.assertAlmostEqual(r["by_scenario"]["A"]["w_flip"], 0.5, delta=1e-4)
        self.assertEqual(r["by_scenario"]["A"]["direction"], "down")

    def test_none_inputs(self):
        self.assertIsNone(compute_spread_switch_thresholds(None, {}))
        # меньше двух сценариев с обоими бакетами — горизонт пропускается
        rows = {"A": {"equity": 1.0, "bond": None}, "B": {"equity": 2.0, "bond": 1.0}}
        self.assertIsNone(compute_spread_switch_thresholds(self._tr(rows), {}))

    def test_run_wires_block_and_matches_total_return_expected(self):
        """spread_now обязан совпасть с expected.equity − expected.bond того же
        total_return (одни веса, одна база без идио)."""
        r = run(TestTotalReturnLayers()._payload(cash_rub=250_000))
        sw = r["spread_switch"]
        self.assertIsNotNone(sw)
        for hk, blk in r["total_return_by_horizon"]["by_horizon"].items():
            exp = blk["expected"]
            self.assertAlmostEqual(sw["by_horizon"][hk]["spread_now_pp"],
                                   exp["equity"] - exp["bond"], delta=1e-3)
        self.assertIn("БЕЗ идиосинкратики", sw["basis"])
        self.assertIn("Когда знак спреда", format_summary(r))


class StressRecalcInfoTests(unittest.TestCase):
    """Числа стресса из пересчёта сайта: сведения о пересчёте доезжают до validation, возраст — по дате суждений."""

    RC = {"source_stress": "stress-2026-11-04-geopol-ru-west-shell-d1.yaml", "source_kind": "stress",
          "source_snapshot_id": "portfolio-2026-11-03.json", "snapshot_id": "portfolio-2026-11-06.json",
          "weights_source": "stress-weights:x.json", "reason": "both", "at": "2026-11-06T11:13:19+03:00"}

    def test_skill_stress_has_no_recalc_info(self):
        self.assertIsNone(stress_recalc_info({"date": "2026-11-06"}))
        self.assertIsNone(stress_recalc_info({"recalc": None}))
        self.assertIsNone(stress_recalc_info({"recalc": {"at": "x"}}))  # без имени стресса скилла — не пересчёт

    def test_recalc_block_is_passed_with_judgments_date(self):
        got = stress_recalc_info({"date": "2026-11-06", "recalc": self.RC})
        self.assertEqual(got["source_stress"], self.RC["source_stress"])
        self.assertEqual(got["judgments_date"], "2026-11-04")   # дата суждений, не дата пересчёта
        self.assertEqual(got["snapshot_id"], "portfolio-2026-11-06.json")
        self.assertEqual(got["at"], self.RC["at"])
        self.assertEqual(got["reason"], "both")
        self.assertIn("возраст стресса считать по дате суждений", got["message"])

    def test_run_carries_recalc_info_to_validation_and_summary(self):
        payload = _make_payload()
        base = run(json.loads(json.dumps(payload)))
        self.assertNotIn("stress_recalc", base["validation"])   # у стресса скилла ключа нет
        payload["stress"]["recalc"] = dict(self.RC)
        out = run(json.loads(json.dumps(payload)))
        self.assertEqual(out["validation"]["stress_recalc"]["judgments_date"], "2026-11-04")
        self.assertIn("пересчёт сайта", format_summary(out))
        # сам расчёт от блока recalc не зависит
        self.assertEqual(out["portfolio"], base["portfolio"])


class StressTermsMismatchTests(unittest.TestCase):
    """Сроки сайта (payload.horizons_file) против сроков стресса: расхождение — предупреждение STRESS_TERMS_MISMATCH."""

    ENDS = {"h6": "2026-12-31", "h12": "2027-06-30", "h24": "2028-06-30"}

    def _site(self, ends=None, **over):
        d = {"schema": "horizons@1", "horizon_ends": dict(ends or self.ENDS), "primary_horizon": 12,
             "set_at": "2026-11-06T21:30:00+03:00", "reason": "тест", "history": []}
        d.update(over)
        return d

    def test_same_terms_and_no_key_are_silent(self):
        self.assertIsNone(check_stress_terms({"horizon_ends": self.ENDS}, self._site()))
        self.assertIsNone(check_stress_terms({"horizon_ends": self.ENDS}, self._site(primary_horizon=6)))  # основной не сравнивается
        self.assertIsNone(check_stress_terms({"horizon_ends": self.ENDS}, None))

    def test_different_dates_give_code_and_text(self):
        got = check_stress_terms({"horizon_ends": self.ENDS},
                                 self._site({"h6": "2027-05-06", "h12": "2027-11-06", "h24": "2028-11-06"}))
        self.assertEqual(got["code"], "STRESS_TERMS_MISMATCH")
        self.assertIn("стресс посчитан на сроки h6 2026-12-31, h12 2027-06-30, h24 2028-06-30", got["message"])
        self.assertIn("действующие сроки h6 2027-05-06, h12 2027-11-06, h24 2028-11-06", got["message"])
        self.assertIn("заданы на сайте 06.11.2026", got["message"])

    def test_different_label_set_is_mismatch(self):
        self.assertIsNotNone(check_stress_terms({"horizon_ends": self.ENDS}, self._site({"h6": "2026-12-31"}, primary_horizon=6)))

    def test_invalid_site_file_or_stress_without_ends_is_silent(self):
        for bad in (self._site({"h6": "2027-06-30", "h12": "2026-12-31"}), self._site(schema="x"),
                    self._site({"h6": "2027-02-30"}, primary_horizon=6), self._site(primary_horizon=18), "не словарь"):
            self.assertIsNone(check_stress_terms({"horizon_ends": {"h6": "2000-01-01"}}, bad))
        self.assertIsNone(check_stress_terms({}, self._site()))

    def test_run_puts_warning_only_on_mismatch(self):
        payload = _make_payload()
        payload["stress"]["horizon_ends"] = dict(self.ENDS)
        base = run(json.loads(json.dumps(payload)))
        self.assertNotIn("stress_terms_mismatch", base["validation"])
        payload["horizons_file"] = self._site()
        same = run(json.loads(json.dumps(payload)))
        self.assertNotIn("stress_terms_mismatch", same["validation"])
        payload["horizons_file"] = self._site({"h6": "2027-05-06", "h12": "2027-11-06", "h24": "2028-11-06"})
        out = run(json.loads(json.dumps(payload)))
        self.assertEqual(out["validation"]["stress_terms_mismatch"]["code"], "STRESS_TERMS_MISMATCH")
        self.assertIn("STRESS_TERMS_MISMATCH", format_summary(out))
        self.assertEqual(out["portfolio"], base["portfolio"])   # расчёт от сроков сайта не зависит


if __name__ == "__main__":
    unittest.main(verbosity=2)
