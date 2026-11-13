#!/usr/bin/env python3
"""Tests for assemble_artifact.py — 330 checks (incl. §14 outcome_log/fca_stats)."""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.assemble_artifact import (
    validate_stress,
    validate_forecast_frontmatter,
    validate_audit_frontmatter,
    validate_weekly_review,
    validate_weekly_review_stock_detailed,
    validate_weekly_review_bond_detailed,
    validate_portfolio_snapshot,
    validate_integrated_view,
    validate_scenario_events,
    validate_forecast_events,
    freeze_outcome_log,
    complete_outcome_log,
    compute_cone,
    check_one_sided_cone,
    _validate_cone,
    _validate_falsifier_sides,
    _validate_confidence_layering,
    _validate_deferred_audit,
    determine_subfolder,
    compute_inclusion,
    find_yaml_top_level_duplicates,
    find_yaml_nested_duplicates,
    check_yaml_duplicates,
    validate_calibration_report,
    validate_monitor_report,
    CALIBRATION_KIND_PREFIX,
    WEIGHT_DIVERGENCE_TOLERANCE_PP,
)


def _b(result):
    return [i for i in result["issues"] if i["severity"] == "blocking"]


def _w(result):
    return [i for i in result["issues"] if i["severity"] == "warning"]


def _b_fields(result):
    return [i["field"] for i in _b(result)]


def _w_fields(result):
    return [i["field"] for i in _w(result)]


# ---------------------------------------------------------------------------
# TestValidateStress — 20 tests
# ---------------------------------------------------------------------------

class TestValidateStress(unittest.TestCase):
    # V2-CUTOVER 2026-08-03: v1-приём снят, канонический фикстур — _v2_stress()
    # (schema 2 + горизонт-блок + factors_by_horizon/by_horizon).
    def _ok(self):
        return _v2_stress()

    def test_valid_passes(self):
        r = validate_stress(self._ok())
        self.assertTrue(r["valid"])
        self.assertEqual(r["blocking_count"], 0)

    def test_missing_schema_version(self):
        d = self._ok(); del d["schema_version"]
        r = validate_stress(d)
        self.assertFalse(r["valid"])
        self.assertIn("schema_version", _b_fields(r))

    def test_wrong_schema_version(self):
        # V2-CUTOVER: schema 1 больше не принимается
        d = self._ok(); d["schema_version"] = 1
        self.assertFalse(validate_stress(d)["valid"])

    def test_missing_type(self):
        d = self._ok(); del d["type"]
        self.assertIn("type", _b_fields(validate_stress(d)))

    def test_wrong_type(self):
        d = self._ok(); d["type"] = "other"
        self.assertFalse(validate_stress(d)["valid"])

    def test_missing_date(self):
        d = self._ok(); del d["date"]
        self.assertIn("date", _b_fields(validate_stress(d)))

    def test_missing_snapshot_id(self):
        d = self._ok(); del d["portfolio_snapshot_id"]
        self.assertIn("portfolio_snapshot_id", _b_fields(validate_stress(d)))

    def test_wrong_weight_type(self):
        d = self._ok(); d["weight_type"] = "normalized"
        self.assertFalse(validate_stress(d)["valid"])

    def test_missing_scenarios(self):
        d = self._ok(); del d["scenarios"]
        self.assertFalse(validate_stress(d)["valid"])

    # --- Anti-drift checks (2026-05-12 Opus gen incident) -----------------
    def test_drift_label_without_name_blocks(self):
        """scenarios.X.label вместо name — drift."""
        d = self._ok()
        d["scenarios"]["Sc-A_bull"] = {"p": 0.25, "label": "Bull"}
        result = validate_stress(d)
        self.assertFalse(result["valid"])
        self.assertTrue(any("label" in i["field"] for i in result["issues"]))

    def test_drift_probability_without_p_blocks(self):
        """scenarios.X.probability вместо p — drift."""
        d = self._ok()
        d["scenarios"]["Sc-A_bull"] = {"name": "Bull", "probability": 0.25}
        result = validate_stress(d)
        self.assertFalse(result["valid"])
        self.assertTrue(any("probability" in i["field"] for i in result["issues"]))

    def test_drift_flat_pnl_rub_without_portfolio_level_blocks(self):
        """scenarios.X.pnl_rub плоско, без portfolio_level — drift."""
        d = self._ok()
        d["scenarios"]["Sc-A_bull"]["pnl_rub"] = 3175455
        result = validate_stress(d)
        self.assertFalse(result["valid"])
        self.assertTrue(any("pnl_rub" in i["field"] for i in result["issues"]))

    def test_flat_pnl_with_portfolio_level_passes(self):
        """Если portfolio_level.delta_rub есть, pnl_rub в scenario OK как дубликат."""
        d = self._ok()
        d["scenarios"]["Sc-A_bull"]["pnl_rub"] = 3175455
        d["scenarios"]["Sc-A_bull"]["portfolio_level"] = {"delta_rub": 3175455}
        result = validate_stress(d)
        # Should not have a pnl_rub blocking
        self.assertFalse(any(i["field"] == "scenarios.Sc-A_bull.pnl_rub"
                             for i in result["issues"] if i["severity"] == "blocking"))

    def test_prob_sum_warning(self):
        d = self._ok()
        d["scenarios"]["Sc-A_bull"]["p"] = 0.10  # sum = 0.85 < 0.99
        r = validate_stress(d)
        self.assertTrue(r["valid"])  # not blocking
        self.assertGreater(r["warning_count"], 0)

    def test_low_coverage_blocking(self):
        d = self._ok()
        d["per_position"]["SBER"]["weight_pct"] = 5.0   # sum=60 + cash5 + blocked10 = 75
        d["cash_pct"] = 2.0
        d["blocked_pct"] = 0.0
        r = validate_stress(d)
        self.assertFalse(r["valid"])
        self.assertTrue(any("coverage" in f for f in _b_fields(r)))

    def test_high_coverage_blocking(self):
        d = self._ok()
        d["per_position"]["SBER"]["weight_pct"] = 90.0  # 90+55+5+10=160
        r = validate_stress(d)
        self.assertFalse(r["valid"])

    def test_orphan_scenario_id(self):
        d = self._ok()
        d["per_position"]["SBER"]["by_horizon"]["h20"]["delta_pct_by_scenario"]["Sc-ORPHAN"] = 1.0
        r = validate_stress(d)
        self.assertFalse(r["valid"])
        self.assertTrue(any("SBER" in f for f in _b_fields(r)))

    def test_missing_caveats(self):
        d = self._ok(); del d["caveats"]
        self.assertIn("caveats", _b_fields(validate_stress(d)))

    def test_empty_caveats(self):
        d = self._ok(); d["caveats"] = []
        self.assertFalse(validate_stress(d)["valid"])

    def test_no_high_severity_caveat(self):
        d = self._ok()
        d["caveats"] = [{"text": "low risk", "severity": "LOW"}]
        self.assertFalse(validate_stress(d)["valid"])

    def test_missing_per_position(self):
        d = self._ok(); del d["per_position"]
        self.assertFalse(validate_stress(d)["valid"])

    def test_macro_blindspots_warning_unknown_ticker(self):
        d = self._ok(); d["macro_blindspots"] = ["GAZP"]
        r = validate_stress(d)
        self.assertTrue(r["valid"])
        self.assertGreater(r["warning_count"], 0)

    def test_macro_blindspots_ok_known_ticker(self):
        d = self._ok(); d["macro_blindspots"] = ["SBER"]
        r = validate_stress(d)
        # v2-фикстур без baseline_spot даёт документированный warning про мёртвый
        # L1-overlay — здесь важно только отсутствие blindspot-warning'ов
        blindspot_warns = [i for i in r["issues"]
                           if i["severity"] == "warning" and "blindspot" in i["field"]]
        self.assertEqual(blindspot_warns, [])

    def test_multiple_blocking_reported(self):
        d = {}
        r = validate_stress(d)
        self.assertGreater(r["blocking_count"], 3)

    def test_missing_unmapped_tickers_blocks(self):
        d = self._ok(); del d["unmapped_tickers"]
        r = validate_stress(d)
        self.assertFalse(r["valid"])
        self.assertIn("unmapped_tickers", _b_fields(r))

    def test_unmapped_tickers_wrong_type_blocks(self):
        d = self._ok(); d["unmapped_tickers"] = "not a list"
        self.assertFalse(validate_stress(d)["valid"])

    def test_generated_at_without_date_blocks(self):
        d = self._ok(); del d["date"]; d["generated_at"] = "2026-05-06T10:00:00"
        r = validate_stress(d)
        self.assertFalse(r["valid"])
        # Должна быть ошибка про date
        self.assertIn("date", _b_fields(r))

    def test_unmapped_tickers_with_entries_old_stress_warns(self):
        """Стресс старше правила «чувствительность всем бумагам» остаётся валидным — только warning."""
        d = self._ok()
        d["date"] = "2026-07-15"
        d["unmapped_tickers"] = [
            {"ticker": "WUSH", "weight_pct": 0.5, "reason": "no priors"},
        ]
        r = validate_stress(d)
        self.assertNotIn("unmapped_tickers", _b_fields(r))
        self.assertIn("unmapped_tickers", [i["field"] for i in r["issues"] if i["severity"] == "warning"])

    def test_unmapped_tickers_with_entries_blocks_new_stress(self):
        """С 2026-11-06 бумага без чувствительности блокирует сохранение стресса: её вес выпал бы из расчёта."""
        for unmapped in ([{"ticker": "WUSH", "weight_pct": 0.5, "reason": "no priors"}], ["WUSH"]):
            d = self._ok()
            d["date"] = "2026-11-06"
            d["unmapped_tickers"] = unmapped
            r = validate_stress(d)
            self.assertIn("unmapped_tickers", _b_fields(r))
            issue = next(i for i in r["issues"] if i["field"] == "unmapped_tickers")
            self.assertIn("WUSH", issue["actual"])

    def test_empty_unmapped_tickers_new_stress_no_issue(self):
        d = self._ok()
        d["date"] = "2026-11-06"
        d["unmapped_tickers"] = []
        self.assertNotIn("unmapped_tickers", [i["field"] for i in validate_stress(d)["issues"]])

    # -- контракт баз расчёта (2026-09-18, §11.2a) — warning, не blocking --

    def test_basis_contract_missing_warns_not_blocks(self):
        """_v2_stress() старше контракта — предсказуемо warns, но valid остаётся True."""
        r = validate_stress(self._ok())
        self.assertTrue(r["valid"])
        self.assertIn("basis_contract", _w_fields(r))
        self.assertIn("per_position_basis", _w_fields(r))
        self.assertIn("base_value_rub", _w_fields(r))
        self.assertIn("p_basis", _w_fields(r))

    def test_basis_contract_present_no_warning(self):
        d = self._ok()
        d.update({"basis_contract": 1, "per_position_basis": "price",
                  "base_value_rub": 1000000, "p_basis": "primary_horizon"})
        r = validate_stress(d)
        self.assertNotIn("basis_contract", _w_fields(r))
        self.assertNotIn("per_position_basis", _w_fields(r))
        self.assertNotIn("base_value_rub", _w_fields(r))
        self.assertNotIn("p_basis", _w_fields(r))

    def test_deprecated_top_level_scalar_warns(self):
        d = self._ok()
        d["expected_pl_rub"] = -50000
        d["portfolio_pl_range_rub"] = {"min": -100000, "max": 50000}
        r = validate_stress(d)
        self.assertIn("expected_pl_rub", _w_fields(r))
        self.assertIn("portfolio_pl_range_rub", _w_fields(r))

    def test_deprecated_portfolio_level_cell_key_warns(self):
        d = self._ok()
        sid = next(iter(d["scenarios"]))
        d["scenarios"][sid]["portfolio_level_by_horizon"] = {
            "h12": {"delta_rub": 1000, "l1_price_only_delta_rub": 900},
        }
        r = validate_stress(d)
        w = _w_fields(r)
        self.assertTrue(any(f.endswith(".delta_rub") for f in w), w)
        self.assertTrue(any(f.endswith(".l1_price_only_delta_rub") for f in w), w)


# ---------------------------------------------------------------------------
# TestDetermineSubfolder — 11 tests
# ---------------------------------------------------------------------------

class TestDetermineSubfolder(unittest.TestCase):
    def test_geopolitics(self):
        r = determine_subfolder({"long-term-russia": "HIGH", "eu-future": "MEDIUM", "iran": "LOW"})
        self.assertEqual(r["recommended"], "geopolitics")
        self.assertFalse(r["ambiguous"])

    def test_ru_macro(self):
        r = determine_subfolder({"ru-rates-forecast": "HIGH", "ru-inflation": "HIGH"})
        self.assertEqual(r["recommended"], "ru-macro")

    def test_global_banks(self):
        r = determine_subfolder({"us-equities": "HIGH", "oil-forecast": "MEDIUM", "ny-rates": "HIGH"})
        self.assertEqual(r["recommended"], "global-banks")

    def test_tech_ceo(self):
        r = determine_subfolder({"agi-timeline": "HIGH", "model-capability": "HIGH"})
        self.assertEqual(r["recommended"], "tech-ceo")

    def test_ru_sellside(self):
        r = determine_subfolder({"iis-targets": "HIGH", "dividend-stocks": "HIGH", "etfs-ru": "MEDIUM"})
        self.assertEqual(r["recommended"], "ru-sellside")

    def test_tie_ambiguous(self):
        r = determine_subfolder({"long-term-russia": "HIGH", "us-equities": "HIGH"})
        self.assertTrue(r["ambiguous"])
        self.assertIsNone(r["recommended"])
        self.assertIn("candidates", r)

    def test_ignore_excluded(self):
        r = determine_subfolder({"long-term-russia": "IGNORE", "eu-future": "IGNORE"})
        self.assertTrue(r["ambiguous"])

    def test_empty_trust_ambiguous(self):
        r = determine_subfolder({})
        self.assertTrue(r["ambiguous"])

    def test_unknown_subdomain_no_match(self):
        r = determine_subfolder({"unknown-xyz": "HIGH"})
        self.assertTrue(r["ambiguous"])
        self.assertIn("unmatched", r)

    def test_mixed_known_unknown_known_wins(self):
        r = determine_subfolder({"long-term-russia": "HIGH", "eu-future": "MEDIUM", "unknown-xyz": "HIGH"})
        self.assertEqual(r["recommended"], "geopolitics")

    def test_crypto_counted_for_both(self):
        # crypto appears in both global-banks and tech-ceo
        r = determine_subfolder({"crypto": "HIGH"})
        self.assertTrue(r["ambiguous"])  # tie between global-banks and tech-ceo

    def test_commodity_agencies_iea(self):
        r = determine_subfolder({"iea-omr": "HIGH", "oil-market": "HIGH", "oil-demand": "MEDIUM"})
        self.assertEqual(r["recommended"], "commodity-agencies")
        self.assertFalse(r["ambiguous"])

    def test_commodity_agencies_opec(self):
        r = determine_subfolder({"opec-omr": "HIGH", "gas-market": "MEDIUM"})
        self.assertEqual(r["recommended"], "commodity-agencies")

    def test_commodity_vs_global_banks_tie(self):
        # oil-forecast is global-banks; oil-market is commodity-agencies
        r = determine_subfolder({"oil-forecast": "HIGH", "oil-market": "HIGH"})
        self.assertTrue(r["ambiguous"])
        self.assertIn("candidates", r)


# ---------------------------------------------------------------------------
# TestComputeInclusion — 7 tests
# ---------------------------------------------------------------------------

class TestComputeInclusion(unittest.TestCase):
    def test_pin_true(self):
        r = compute_inclusion(True, {})
        self.assertTrue(r["include_in_memory"])
        self.assertIn("pin", r["reason"])

    def test_high_trust(self):
        r = compute_inclusion(False, {"long-term-russia": "HIGH", "eu-future": "MEDIUM"})
        self.assertTrue(r["include_in_memory"])
        self.assertIn("long-term-russia", r["reason"])

    def test_medium_only_no_inclusion(self):
        r = compute_inclusion(False, {"eu-future": "MEDIUM", "iran": "LOW"})
        self.assertFalse(r["include_in_memory"])

    def test_ignore_no_inclusion(self):
        r = compute_inclusion(False, {"long-term-russia": "IGNORE"})
        self.assertFalse(r["include_in_memory"])

    def test_empty_trust_no_pin(self):
        r = compute_inclusion(False, {})
        self.assertFalse(r["include_in_memory"])

    def test_pin_overrides_low_trust(self):
        r = compute_inclusion(True, {"long-term-russia": "LOW"})
        self.assertTrue(r["include_in_memory"])

    def test_multiple_high_subdomains_all_listed(self):
        r = compute_inclusion(False, {"agi-timeline": "HIGH", "model-capability": "HIGH"})
        self.assertTrue(r["include_in_memory"])
        self.assertIn("agi-timeline", r["reason"])
        self.assertIn("model-capability", r["reason"])


# ---------------------------------------------------------------------------
# TestValidateForecastFrontmatter — 11 tests
# ---------------------------------------------------------------------------

class TestValidateForecastFrontmatter(unittest.TestCase):
    def _ok_fca(self):
        return {
            "schema_version": 1,
            "forecast_date": "2026-05-01",
            "horizon_date": "2026-12-31",
            "review_interval_months": 3,
            "topic": "ru-rates-2026",
            "domain": "ru-macro",
            "method": "fca",
            "confidence": 0.65,
        }

    def test_valid_fca(self):
        self.assertTrue(validate_forecast_frontmatter(self._ok_fca())["valid"])

    def test_valid_manual_no_confidence(self):
        d = self._ok_fca(); d["method"] = "manual"; d["confidence"] = None
        self.assertTrue(validate_forecast_frontmatter(d)["valid"])

    def test_valid_external_quoted_no_confidence(self):
        d = self._ok_fca(); d["method"] = "external_quoted"; d["confidence"] = None
        self.assertTrue(validate_forecast_frontmatter(d)["valid"])

    def test_fca_without_confidence_blocking(self):
        d = self._ok_fca(); d["confidence"] = None
        r = validate_forecast_frontmatter(d)
        self.assertFalse(r["valid"])
        self.assertIn("confidence", _b_fields(r))

    def test_fca_confidence_out_of_range(self):
        d = self._ok_fca(); d["confidence"] = 1.5
        self.assertFalse(validate_forecast_frontmatter(d)["valid"])

    def test_horizon_todo_blocking(self):
        d = self._ok_fca(); d["horizon_date"] = "TODO"
        self.assertIn("horizon_date", _b_fields(validate_forecast_frontmatter(d)))

    def test_invalid_domain(self):
        d = self._ok_fca(); d["domain"] = "crypto-macro"
        self.assertIn("domain", _b_fields(validate_forecast_frontmatter(d)))

    def test_invalid_method(self):
        d = self._ok_fca(); d["method"] = "ai-generated"
        self.assertFalse(validate_forecast_frontmatter(d)["valid"])

    def test_empty_returns_multiple_blocking(self):
        r = validate_forecast_frontmatter({})
        self.assertGreater(r["blocking_count"], 4)

    def test_schema_version_missing_is_info(self):
        d = self._ok_fca(); del d["schema_version"]
        r = validate_forecast_frontmatter(d)
        self.assertTrue(r["valid"])  # blocking_count=0
        info = [i for i in r["issues"] if i["severity"] == "info"]
        self.assertTrue(len(info) > 0)

    def test_fca_confidence_zero_valid(self):
        d = self._ok_fca(); d["confidence"] = 0.0
        self.assertTrue(validate_forecast_frontmatter(d)["valid"])


# ---------------------------------------------------------------------------
# TestValidateAuditFrontmatter — 6 tests
# ---------------------------------------------------------------------------

class TestValidateAuditFrontmatter(unittest.TestCase):
    def test_valid(self):
        d = {"source": "Stratfor", "audit_date": "2026-05-01",
             "trust": {"long-term-russia": "HIGH", "eu-future": "MEDIUM"}}
        self.assertTrue(validate_audit_frontmatter(d)["valid"])

    def test_missing_source(self):
        d = {"audit_date": "2026-05-01", "trust": {"long-term-russia": "HIGH"}}
        self.assertIn("source", _b_fields(validate_audit_frontmatter(d)))

    def test_missing_trust(self):
        d = {"source": "Stratfor", "audit_date": "2026-05-01"}
        self.assertFalse(validate_audit_frontmatter(d)["valid"])

    def test_missing_audit_date(self):
        d = {"source": "Stratfor", "trust": {"long-term-russia": "HIGH"}}
        self.assertIn("audit_date", _b_fields(validate_audit_frontmatter(d)))

    def test_invalid_trust_level_warning_not_blocking(self):
        d = {"source": "Stratfor", "audit_date": "2026-05-01",
             "trust": {"long-term-russia": "VERY_HIGH"}}
        r = validate_audit_frontmatter(d)
        self.assertTrue(r["valid"])  # not blocking
        self.assertGreater(len(_w(r)), 0)

    def test_trust_not_dict_blocking(self):
        d = {"source": "Stratfor", "audit_date": "2026-05-01", "trust": "HIGH"}
        self.assertFalse(validate_audit_frontmatter(d)["valid"])

    # --- trust 3D backward-compat (D4) ---

    def test_trust_3d_valid(self):
        d = {
            "source": "Stratfor",
            "audit_date": "2026-05-01",
            "trust": {
                "marginal": {"long-term-russia": "HIGH", "eu-future": "MEDIUM"},
                "world_picking": {"primary-D-secondary-B": "MEDIUM"},
                "conditional": {},
            },
        }
        r = validate_audit_frontmatter(d)
        self.assertTrue(r["valid"])

    def test_trust_3d_invalid_level_in_marginal_warning(self):
        d = {
            "source": "Stratfor",
            "audit_date": "2026-05-01",
            "trust": {"marginal": {"x": "VERY_HIGH"}, "world_picking": {}, "conditional": {}},
        }
        r = validate_audit_frontmatter(d)
        self.assertTrue(r["valid"])
        warning_fields = [i["field"] for i in _w(r)]
        self.assertIn("trust.marginal.x", warning_fields)

    def test_determine_subfolder_accepts_3d(self):
        # Via dispatcher: assert flatten_trust normalizes 3D → marginal.
        from scripts.assemble_artifact import flatten_trust
        flat = flatten_trust({
            "marginal": {"ru-rates-forecast": "HIGH", "geopolitics": "MEDIUM"},
            "world_picking": {"primary-D": "HIGH"},
            "conditional": {},
        })
        self.assertEqual(flat, {"ru-rates-forecast": "HIGH", "geopolitics": "MEDIUM"})

    def test_flatten_trust_passthrough_flat(self):
        from scripts.assemble_artifact import flatten_trust
        flat = flatten_trust({"long-term-russia": "HIGH"})
        self.assertEqual(flat, {"long-term-russia": "HIGH"})


# ---------------------------------------------------------------------------
# TestValidateWeeklyReview — 4 tests (Workflow F)
# ---------------------------------------------------------------------------

def _ok_catalyst():
    """Full catalyst structure for tests."""
    return {
        "id": "rate_cut_q3",
        "trigger": "CBR ставка cut −50bp on 2026-06-19",
        "date_window": "2026-Q3",
        "in_horizon": True,
        "p": 0.6,
        "upside_pct": 12.0,
        "upside_ci_pct": [5.0, 20.0],
        "source": "advisor estimate based on CBR forward guidance",
        "source_quality": "MEDIUM",
        "macro_dependency": "A",
    }


def _ok_per_bond_entry():
    """Минимальный канонический per_bond entry, проходящий detailed validator."""
    return {
        "name": "ГазКЗ-29Д",
        "weight_real_pct": 4.59,
        "on_iis": False,
        "bond_type": "fx_replacement",
        "maturity_date": "2029-01-27",
        "ytm_pct": 7.81,
        "credit_quality": "HIGH",
        "advisor_verdict": "HOLD",
        "advisor_verdict_basis": "Ядро USD-корзины, YTM 7.81% USD",
        "verification_priority": "LOW",
        "catalyst": [{
            "id": "redemption",
            "trigger": "Погашение 27.01.2029 (вне горизонта 20 мес)",
            "date_window": "2029-01-27",
            "in_horizon": False,
            "p": 0.97,
            "upside_pct": 0,
            "upside_ci_pct": [-1, 1],
            "source": "moex_iss",
            "source_quality": "HIGH",
            "macro_dependency": None,
        }],
    }


def _ok_bond_review():
    """Канонический weekly-review-bond YAML payload."""
    return {
        "schema_version": 1,
        "type": "weekly-bonds-review",
        "review_date": "2026-05-12",
        "snapshot_id": "portfolio-2026-05-12.json",
        "per_bond": {"RU000A105KU0": _ok_per_bond_entry()},
        "summary": {
            "total_value_rub": 19161681,
            "weighted_ytm_pct": {"value": 15.67, "ci_pct": [14.5, 16.5]},
            "weighted_duration_days": 1420,
            "by_type_pct": {"ofz": 17.3, "fx_replacement": 59.2, "corp_rub": 12.0},
            "by_credit_quality_pct": {"HIGH": 64.4, "MEDIUM": 18.1, "LOW": 10.1},
            "maturity_ladder_pct": {"2026": 24.7, "2027": 27.5},
        },
    }


def _ok_per_stock_entry():
    """Минимальный канонический per_stock entry, проходящий detailed validator.

    RPA-19: real=12.0, planned=10.0, ie_target=6.0 → divergence_vs_planned=2.0
    (PRIMARY), divergence_vs_ie=6.0 (secondary) == deprecated алиас weight_divergence_pp.
    """
    return {
        "sector": "Финансовый",
        "weight_real_pct": 12.0,
        "weight_user_planned_pct": 10.0,
        "weight_ie_target_pct": 6.0,
        "weight_divergence_vs_planned_pp": 2.0,
        "weight_divergence_vs_ie_pp": 6.0,
        "weight_divergence_pp": 6.0,
        "on_iis": False,
        "fundamental_score": "HIGH",
        "fundamental_score_basis": "Крупнейший банк РФ, ROE 24%, CET1>13%",
        "div_yield_12m_pct": {"value": 11.5, "ci_pct": [10.0, 13.0]},
        "div_confidence": "HIGH",
        "div_basis": "37.64 руб/акцию за 2025",
        "catalyst": [_ok_catalyst()],
        "advisor_verdict": "HOLD",
        "advisor_verdict_confidence": 0.85,
        "advisor_verdict_basis": "Удерживать в ожидании ставочного цикла",
        "verification_priority": "LOW",
    }


class TestValidateWeeklyReview(unittest.TestCase):
    # V2-CUTOVER 2026-08-03: router-тесты на v2-фикстурах (v1-приём снят).
    def _ok_stocks(self):
        return _v2_stock_review()

    def _ok_bonds(self):
        return _v2_bond_review()

    def test_valid_stocks(self):
        self.assertTrue(validate_weekly_review(self._ok_stocks())["valid"])

    def test_valid_bonds(self):
        self.assertTrue(validate_weekly_review(self._ok_bonds())["valid"])

    def test_missing_review_date(self):
        d = self._ok_stocks(); del d["review_date"]
        self.assertIn("review_date", _b_fields(validate_weekly_review(d)))

    def test_missing_snapshot_id(self):
        d = self._ok_stocks(); del d["snapshot_id"]
        self.assertIn("snapshot_id", _b_fields(validate_weekly_review(d)))

    def test_empty_per_stock_blocking(self):
        d = self._ok_stocks(); d["per_stock"] = {}
        self.assertFalse(validate_weekly_review(d)["valid"])

    def test_empty_per_bond_blocking(self):
        d = self._ok_bonds(); d["per_bond"] = {}
        self.assertFalse(validate_weekly_review(d)["valid"])

    def test_bond_missing_summary_field(self):
        d = self._ok_bonds(); del d["summary"]["weighted_ytm_pct"]
        self.assertIn("summary.weighted_ytm_pct", _b_fields(validate_weekly_review(d)))


# ---------------------------------------------------------------------------
# Phase 4 (schema v2): multiple horizons — роутинг + drift-чеки
# ---------------------------------------------------------------------------

def _v2_horizons():
    """Top-level horizon-блок v2 для review_date/date 2026-05-12 (или 2026-05-06)."""
    return {
        "horizons": [12, 20, 36],
        "horizon_ends": {"h12": "2027-05-31", "h20": "2028-01-31", "h36": "2029-05-31"},
        "primary_horizon": 20,
    }


def _v2_catalyst():
    c = _ok_catalyst()
    c.pop("in_horizon", None)          # v2: in_horizon удалён
    return c


def _v2_stock_review():
    entry = _ok_per_stock_entry()
    entry["catalyst"] = [_v2_catalyst()]
    return {
        "schema_version": 2,
        "type": "weekly-stocks-review",
        "review_date": "2026-05-12",
        "snapshot_id": "portfolio-2026-05-12.json",
        **_v2_horizons(),
        "per_stock": {"SBER": entry},
    }


def _v2_bond_review():
    d = _ok_bond_review()
    d["schema_version"] = 2
    d.update(_v2_horizons())
    for entry in d["per_bond"].values():
        for c in entry.get("catalyst", []):
            c.pop("in_horizon", None)
    return d


def _v2_stress():
    fbh = {"h12": {"brent": 5.0}, "h20": {"brent": 3.0}, "h36": {"brent": 1.0}}
    def _pos(w, a, b, c):
        deltas = {"Sc-A_bull": a, "Sc-B_base": b, "Sc-C_bear": c}
        return {"weight_pct": w, "by_horizon": {
            hk: {"delta_pct_by_scenario": dict(deltas)} for hk in ("h12", "h20", "h36")}}
    return {
        "schema_version": 2,
        "type": "portfolio-stress-test",
        "date": "2026-05-06",
        "portfolio_snapshot_id": "portfolio-2026-05-06.json",
        "weight_type": "probability",
        "cash_pct": 5.0,
        "blocked_pct": 10.0,
        **_v2_horizons(),
        "scenarios": {
            "Sc-A_bull": {"p": 0.25, "name": "Bull", "factors_by_horizon": fbh},
            "Sc-B_base": {"p": 0.40, "name": "Base", "factors_by_horizon": fbh},
            "Sc-C_bear": {"p": 0.35, "name": "Bear", "factors_by_horizon": fbh},
        },
        "per_position": {"SBER": _pos(30.0, 5, 1, -8), "LKOH": _pos(55.0, 3, -1, -12)},
        "caveats": [{"text": "x", "severity": "HIGH"}],
        "unmapped_tickers": [],
    }


class TestSchemaV2Validators(unittest.TestCase):
    # --- stock v2 ---
    def test_v2_stock_valid(self):
        r = validate_weekly_review_stock_detailed(_v2_stock_review())
        self.assertTrue(r["valid"], _b_fields(r))

    def test_v2_stock_in_horizon_blocks(self):
        d = _v2_stock_review()
        d["per_stock"]["SBER"]["catalyst"][0]["in_horizon"] = True
        self.assertFalse(validate_weekly_review_stock_detailed(d)["valid"])
        self.assertTrue(any("in_horizon" in f for f in _b_fields(validate_weekly_review_stock_detailed(d))))

    def test_v2_stock_horizon_months_blocks(self):
        d = _v2_stock_review(); d["horizon_months"] = 20
        self.assertIn("horizon_months", _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_v2_stock_horizon_end_blocks(self):
        d = _v2_stock_review(); d["horizon_end"] = "2028-01-31"
        self.assertIn("horizon_end", _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_v2_stock_missing_horizons_blocks(self):
        d = _v2_stock_review(); del d["horizons"]
        self.assertIn("horizons", _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_v2_stock_primary_not_in_horizons_blocks(self):
        d = _v2_stock_review(); d["primary_horizon"] = 99
        self.assertIn("primary_horizon", _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_v2_stock_horizon_ends_wrong_keys_blocks(self):
        d = _v2_stock_review(); d["horizon_ends"] = {"h12": "2027-05-31"}  # не все ключи
        self.assertIn("horizon_ends", _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_v2_stock_unparseable_date_window_warns_not_blocks(self):
        d = _v2_stock_review()
        d["per_stock"]["SBER"]["catalyst"][0]["date_window"] = "когда-нибудь"
        r = validate_weekly_review_stock_detailed(d)
        self.assertTrue(r["valid"])  # warning, не blocking
        self.assertTrue(any("date_window" in i["field"] and i["severity"] == "warning"
                            for i in r["issues"]))

    def test_v2_stock_range_date_window_ok(self):
        d = _v2_stock_review()
        d["per_stock"]["SBER"]["catalyst"][0]["date_window"] = "2026-Q4 .. 2027-Q2"
        self.assertTrue(validate_weekly_review_stock_detailed(d)["valid"])

    # --- bond v2 ---
    def test_v2_bond_valid(self):
        r = validate_weekly_review_bond_detailed(_v2_bond_review())
        self.assertTrue(r["valid"], _b_fields(r))

    def test_v2_bond_in_horizon_blocks(self):
        d = _v2_bond_review()
        d["per_bond"]["RU000A105KU0"]["catalyst"][0]["in_horizon"] = False
        self.assertFalse(validate_weekly_review_bond_detailed(d)["valid"])

    # --- stress v2 ---
    def test_v2_stress_valid(self):
        r = validate_stress(_v2_stress())
        self.assertTrue(r["valid"], _b_fields(r))

    def test_v2_stress_flat_factors_blocks(self):
        d = _v2_stress(); d["scenarios"]["Sc-A_bull"]["factors"] = {"brent": 5}
        self.assertTrue(any("factors" in f for f in _b_fields(validate_stress(d))))

    def test_v2_stress_flat_portfolio_level_blocks(self):
        d = _v2_stress(); d["scenarios"]["Sc-A_bull"]["portfolio_level"] = {"delta_rub": 1}
        self.assertIn("scenarios.Sc-A_bull.portfolio_level", _b_fields(validate_stress(d)))

    def test_v2_stress_orphan_scenario_in_by_horizon_blocks(self):
        d = _v2_stress()
        d["per_position"]["SBER"]["by_horizon"]["h20"]["delta_pct_by_scenario"]["Sc-Z"] = 1.0
        self.assertTrue(any("by_horizon.h20" in f for f in _b_fields(validate_stress(d))))

    def test_v2_stress_horizon_months_blocks(self):
        d = _v2_stress(); d["horizon_months"] = 20
        self.assertIn("horizon_months", _b_fields(validate_stress(d)))

    # --- ссылка на макросценарии (шаг 14, R22) ---
    def test_v2_stress_macro_input_link(self):
        def mi_issues(d):
            return [i for i in validate_stress(d)["issues"] if i["field"] in ("macro_input", "macro_scenarios_file")]
        d = _v2_stress(); d["scenario_source"] = "macro-forecast-chain"; d["macro_input"] = "macro-scenarios-2026-10-04.yaml"
        self.assertEqual(mi_issues(d), [])
        d = _v2_stress(); d["scenario_source"] = "macro-forecast-chain"; d.pop("macro_input", None)
        r = validate_stress(d)
        self.assertTrue(r["valid"])                                       # старые стрессы без ссылки — не блок
        self.assertEqual([i["severity"] for i in mi_issues(d)], ["warning"])
        d = _v2_stress(); d["scenario_source"] = "scenario-builder"; d.pop("macro_input", None)
        self.assertEqual(mi_issues(d), [])
        d = _v2_stress(); d["macro_input"] = {"file": "x"}
        self.assertIn("macro_input", _b_fields(validate_stress(d)))
        d = _v2_stress(); d["macro_scenarios_file"] = "macro-scenarios-2026-10-04.yaml"
        self.assertIn("macro_scenarios_file", _b_fields(validate_stress(d)))   # второго имени нет (R22)

    # --- horizon_mode + anchor fix (A4) ---
    def test_v2_stress_rolling_date_anchor_no_horizon_warnings(self):
        """Регрессия A4-bug: stress использует `date`, а не `review_date` как якорь.
        review_date = date + 6мес (другой месяц) → раньше давал 3 ложных warning'а."""
        d = _v2_stress()
        d["date"] = "2026-06-08"
        d["review_date"] = "2026-12-05"  # date + ~6мес — НЕ якорь для horizon_ends
        # horizon_ends корректны относительно date=2026-06-08
        d["horizons"] = [6, 12, 24]
        d["horizon_ends"] = {"h6": "2026-12-31", "h12": "2027-06-30", "h24": "2028-06-30"}
        d["primary_horizon"] = 12
        r = validate_stress(d)
        horizon_warns = [i for i in r["issues"]
                         if "horizon_ends" in i["field"] and i["severity"] == "warning"]
        self.assertEqual(horizon_warns, [], f"Ложные warnings: {horizon_warns}")

    def test_v2_anchored_valid_no_warnings(self):
        """anchored mode: даты > base, строго возрастают, ≈N мес → 0 warnings."""
        d = _v2_stock_review()
        # review_date=2026-05-12, h8 ≈ 2027-01-12, h14 ≈ 2027-07-12
        d["horizons"] = [8, 14]
        d["horizon_ends"] = {"h8": "2027-01-15", "h14": "2027-07-20"}
        d["primary_horizon"] = 8
        d["horizon_mode"] = "anchored"
        r = validate_weekly_review_stock_detailed(d)
        horizon_issues = [i for i in r["issues"] if "horizon_ends" in i["field"]]
        self.assertEqual(horizon_issues, [], f"Неожиданные issues: {horizon_issues}")

    def test_v2_anchored_far_offset_warns(self):
        """anchored mode: дата намного дальше N мес → warning."""
        d = _v2_stock_review()
        d["horizons"] = [6]
        # review_date=2026-05-12 + 6мес ≈ 2026-11-12, но ставим 2029-01-01 (+31 мес) — warning
        d["horizon_ends"] = {"h6": "2029-01-01"}
        d["primary_horizon"] = 6
        d["horizon_mode"] = "anchored"
        r = validate_weekly_review_stock_detailed(d)
        self.assertTrue(any("horizon_ends.h6" in i["field"] and i["severity"] == "warning"
                            for i in r["issues"]), "Ожидался warning для сильно смещённой даты")

    def test_v2_anchored_label_drift_within_shift_rule(self):
        """anchored: сроки держатся до сдвига (меньше 3 мес до ближайшего), поэтому метка расходится
        с фактом до 3 мес — без warning; 4 мес — warning."""
        d = _v2_stock_review()   # review_date=2026-05-12
        d["horizons"] = [6, 12]
        d["primary_horizon"] = 6
        d["horizon_mode"] = "anchored"
        d["horizon_ends"] = {"h6": "2026-08-31", "h12": "2027-02-28"}   # 3 и 9 мес: расхождение ровно 3
        r = validate_weekly_review_stock_detailed(d)
        self.assertEqual([i for i in r["issues"] if "horizon_ends" in i["field"]], [])
        d["horizon_ends"] = {"h6": "2026-07-31", "h12": "2027-01-31"}   # 2 и 8 мес: расхождение 4
        r = validate_weekly_review_stock_detailed(d)
        self.assertEqual(sorted(i["field"] for i in r["issues"]
                                if "horizon_ends" in i["field"] and i["severity"] == "warning"),
                         ["horizon_ends.h12", "horizon_ends.h6"])

    def test_v2_anchored_non_increasing_blocks(self):
        """anchored mode: даты не возрастают строго → blocking."""
        d = _v2_stock_review()
        d["horizons"] = [6, 12]
        d["horizon_ends"] = {"h6": "2027-06-30", "h12": "2026-12-31"}  # h6 > h12 — ошибка
        d["primary_horizon"] = 6
        d["horizon_mode"] = "anchored"
        r = validate_weekly_review_stock_detailed(d)
        self.assertTrue(any("horizon_ends" in i["field"] and i["severity"] == "blocking"
                            for i in r["issues"]), "Ожидался blocking для неупорядоченных дат")

    def test_v2_unknown_horizon_mode_warns(self):
        """Неизвестный horizon_mode → warning (не blocking), валидация rolling-чеком."""
        d = _v2_stock_review()
        d["horizon_mode"] = "biennial"
        r = validate_weekly_review_stock_detailed(d)
        self.assertTrue(any("horizon_mode" in i["field"] and i["severity"] == "warning"
                            for i in r["issues"]))

    def test_v2_no_horizon_mode_defaults_rolling_valid(self):
        """Артефакты без horizon_mode валидны (default=rolling, backward-compat)."""
        d = _v2_stock_review()
        self.assertNotIn("horizon_mode", d)
        r = validate_weekly_review_stock_detailed(d)
        self.assertTrue(r["valid"], _b_fields(r))


# ---------------------------------------------------------------------------
# TestValidateWeeklyReviewStockDetailed — full canonical schema enforcement
# ---------------------------------------------------------------------------

class TestValidateWeeklyReviewStockDetailed(unittest.TestCase):
    """Детальная валидация stock weekly-review YAML.

    Защищает контракт после 2026-05-12 incident:
    - TODO_LLM плейсхолдеры → blocking
    - Drift-имена (share_actual_pct/ie_share_pct/delta_pct/catalysts) → blocking
    - Отсутствие/null required-поля (fundamental_score/div/catalyst/verdict/priority) → blocking
    - Неверный тип (schema_version "1" string) / enum → blocking
    """

    # V2-CUTOVER 2026-08-03: v1-приём снят — фикстур v2, per_stock из двух тикеров.
    def _ok(self):
        d = _v2_stock_review()
        entry = _ok_per_stock_entry()
        entry["catalyst"] = [_v2_catalyst()]
        d["per_stock"]["T"] = entry
        return d

    # === Positive case ===
    def test_valid_payload_passes(self):
        result = validate_weekly_review_stock_detailed(self._ok())
        self.assertTrue(result["valid"], _b_fields(result))

    # === Top-level type checks ===
    def test_schema_version_string_blocks(self):
        d = self._ok(); d["schema_version"] = "1"
        self.assertIn("schema_version", _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_schema_version_unknown_blocks(self):
        # только 2 валидна (V2-CUTOVER); неизвестная версия (3) блокируется
        d = self._ok(); d["schema_version"] = 3
        self.assertIn("schema_version", _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_wrong_type_blocks(self):
        d = self._ok(); d["type"] = "weekly-stocks"
        self.assertIn("type", _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_missing_review_date_blocks(self):
        d = self._ok(); del d["review_date"]
        self.assertIn("review_date", _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_horizon_months_drift_blocks(self):
        # V2-CUTOVER: v1-поле horizon_months в v2-доке — drift → blocking
        d = self._ok(); d["horizon_months"] = 12
        self.assertIn("horizon_months", _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_empty_per_stock_blocks(self):
        d = self._ok(); d["per_stock"] = {}
        self.assertIn("per_stock", _b_fields(validate_weekly_review_stock_detailed(d)))

    # === TODO_LLM detection ===
    def test_todo_llm_in_fundamental_score_blocks(self):
        d = self._ok()
        d["per_stock"]["SBER"]["fundamental_score"] = "TODO_LLM_HIGH_MEDIUM_LOW_RED_FLAG"
        fields = _b_fields(validate_weekly_review_stock_detailed(d))
        self.assertIn("per_stock.SBER.fundamental_score", fields)

    def test_todo_llm_in_advisor_verdict_basis_blocks(self):
        d = self._ok()
        d["per_stock"]["SBER"]["advisor_verdict_basis"] = "TODO_LLM_2_to_5_lines"
        fields = _b_fields(validate_weekly_review_stock_detailed(d))
        self.assertIn("per_stock.SBER.advisor_verdict_basis", fields)

    def test_todo_llm_in_div_yield_value_blocks(self):
        d = self._ok()
        d["per_stock"]["SBER"]["div_yield_12m_pct"]["value"] = "TODO_LLM_float_pct"
        fields = _b_fields(validate_weekly_review_stock_detailed(d))
        self.assertIn("per_stock.SBER.div_yield_12m_pct.value", fields)

    def test_todo_llm_in_catalyst_trigger_blocks(self):
        d = self._ok()
        d["per_stock"]["SBER"]["catalyst"][0]["trigger"] = "TODO_LLM_event"
        fields = _b_fields(validate_weekly_review_stock_detailed(d))
        self.assertIn("per_stock.SBER.catalyst[0].trigger", fields)

    # === Anti-drift rename checks ===
    def test_drift_share_actual_pct_blocks(self):
        """Использование `share_actual_pct` вместо `weight_real_pct` блокирует запись."""
        d = self._ok()
        # Оставим оба для теста — drift должен detect
        d["per_stock"]["SBER"]["share_actual_pct"] = 4.47
        fields = _b_fields(validate_weekly_review_stock_detailed(d))
        self.assertIn("per_stock.SBER.share_actual_pct", fields)

    def test_drift_ie_share_pct_blocks(self):
        d = self._ok()
        d["per_stock"]["SBER"]["ie_share_pct"] = 6.0
        fields = _b_fields(validate_weekly_review_stock_detailed(d))
        self.assertIn("per_stock.SBER.ie_share_pct", fields)

    def test_drift_delta_pct_blocks(self):
        d = self._ok()
        d["per_stock"]["SBER"]["delta_pct"] = -1.53
        fields = _b_fields(validate_weekly_review_stock_detailed(d))
        self.assertIn("per_stock.SBER.delta_pct", fields)

    def test_drift_catalysts_key_blocks(self):
        """Ключ `catalysts:` (с «s») вместо канонического `catalyst:`."""
        d = self._ok()
        # Заменим catalyst на catalysts (drift)
        d["per_stock"]["SBER"]["catalysts"] = d["per_stock"]["SBER"].pop("catalyst")
        fields = _b_fields(validate_weekly_review_stock_detailed(d))
        self.assertIn("per_stock.SBER.catalysts", fields)
        # И в т.ч. catalyst теперь отсутствует
        self.assertIn("per_stock.SBER.catalyst", fields)

    # === Missing required fields ===
    def test_missing_fundamental_score_blocks(self):
        d = self._ok(); del d["per_stock"]["SBER"]["fundamental_score"]
        self.assertIn("per_stock.SBER.fundamental_score",
                      _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_missing_div_yield_12m_pct_blocks(self):
        d = self._ok(); del d["per_stock"]["SBER"]["div_yield_12m_pct"]
        self.assertIn("per_stock.SBER.div_yield_12m_pct",
                      _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_missing_verification_priority_blocks(self):
        d = self._ok(); del d["per_stock"]["SBER"]["verification_priority"]
        self.assertIn("per_stock.SBER.verification_priority",
                      _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_missing_advisor_verdict_basis_blocks(self):
        d = self._ok(); del d["per_stock"]["SBER"]["advisor_verdict_basis"]
        self.assertIn("per_stock.SBER.advisor_verdict_basis",
                      _b_fields(validate_weekly_review_stock_detailed(d)))

    # === RPA-19 (2026-08-20): плановая доля владельца — PRIMARY target ===
    def test_rpa19_missing_weight_user_planned_pct_blocks(self):
        """Отсутствие weight_user_planned_pct (ключ вообще не задан) блокирует запись."""
        d = self._ok(); del d["per_stock"]["SBER"]["weight_user_planned_pct"]
        self.assertIn("per_stock.SBER.weight_user_planned_pct",
                      _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_rpa19_missing_divergence_vs_planned_blocks(self):
        """Отсутствие weight_divergence_vs_planned_pp (ключ вообще не задан) блокирует запись."""
        d = self._ok(); del d["per_stock"]["SBER"]["weight_divergence_vs_planned_pp"]
        self.assertIn("per_stock.SBER.weight_divergence_vs_planned_pp",
                      _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_rpa19_null_planned_and_divergence_ok_no_plan(self):
        """Бумага без плана владельца: weight_user_planned_pct и divergence_vs_planned
        оба null — штатный случай (план по бумаге не задан), не блокирует."""
        d = self._ok()
        d["per_stock"]["SBER"]["weight_user_planned_pct"] = None
        d["per_stock"]["SBER"]["weight_divergence_vs_planned_pp"] = None
        result = validate_weekly_review_stock_detailed(d)
        self.assertTrue(result["valid"], _b_fields(result))

    def test_rpa19_drift_planned_share_pct_blocks(self):
        """Дрейф-имя `planned_share_pct` (как в снапшоте ie_actual) вместо канонического
        weight_user_planned_pct — типовая ошибка копирования, должна ловиться."""
        d = self._ok()
        d["per_stock"]["SBER"]["planned_share_pct"] = 10.0
        fields = _b_fields(validate_weekly_review_stock_detailed(d))
        self.assertIn("per_stock.SBER.planned_share_pct", fields)

    def test_rpa19_divergence_vs_planned_mismatch_blocks(self):
        """real=10, planned=8 → divergence обязан быть real−planned=2, не отдельное
        число 5 (расхождение с указанием ожидаемого значения в сообщении)."""
        d = self._ok()
        e = d["per_stock"]["SBER"]
        e["weight_real_pct"] = 10.0
        e["weight_user_planned_pct"] = 8.0
        e["weight_divergence_vs_planned_pp"] = 5.0  # неверно: должно быть 2.0
        # IE-слагаемые оставляем внутренне согласованными, чтобы не поймать
        # вторую (не тестируемую здесь) сверку real vs ie_target.
        e["weight_ie_target_pct"] = 6.0
        e["weight_divergence_vs_ie_pp"] = 4.0
        e["weight_divergence_pp"] = 4.0
        result = validate_weekly_review_stock_detailed(d)
        issues = [i for i in result["issues"]
                  if i["field"] == "per_stock.SBER.weight_divergence_vs_planned_pp"]
        self.assertTrue(issues, _b_fields(result))
        self.assertIn("2", issues[0]["expected"])  # ожидание: real − planned = 2.0

    def test_rpa19_divergence_vs_planned_within_tolerance_passes(self):
        """Расхождение в пределах допуска WEIGHT_DIVERGENCE_TOLERANCE_PP (0.05 пп) —
        округление, не ручная правка мимо слагаемых — проходит."""
        d = self._ok()
        e = d["per_stock"]["SBER"]
        # real=12.0, planned=10.0 → точная разность 2.0; берём значение внутри допуска.
        e["weight_divergence_vs_planned_pp"] = round(2.0 + WEIGHT_DIVERGENCE_TOLERANCE_PP / 2, 4)
        result = validate_weekly_review_stock_detailed(d)
        self.assertNotIn("per_stock.SBER.weight_divergence_vs_planned_pp", _b_fields(result))

    def test_rpa19_deprecated_alias_mismatch_blocks(self):
        """deprecated weight_divergence_pp, не равный weight_divergence_vs_ie_pp, блокирует."""
        d = self._ok()
        d["per_stock"]["SBER"]["weight_divergence_pp"] = 99.0  # vs_ie_pp остался 6.0
        fields = _b_fields(validate_weekly_review_stock_detailed(d))
        self.assertIn("per_stock.SBER.weight_divergence_pp", fields)

    def test_rpa19_ticker_outside_ie_model_with_plan_passes(self):
        """Бумага вне модели IE (ie_target/vs_ie/deprecated null), план владельца
        задан — проходит, weight_divergence_vs_planned_pp остаётся числом."""
        d = self._ok()
        e = d["per_stock"]["SBER"]
        e["weight_ie_target_pct"] = None
        e["weight_divergence_vs_ie_pp"] = None
        e["weight_divergence_pp"] = None
        # weight_real_pct=12.0, weight_user_planned_pct=10.0 (из _ok_per_stock_entry) остаются
        result = validate_weekly_review_stock_detailed(d)
        self.assertTrue(result["valid"], _b_fields(result))
        self.assertEqual(e["weight_divergence_vs_planned_pp"], 2.0)

    # === Enum membership ===
    def test_invalid_fundamental_score_blocks(self):
        d = self._ok(); d["per_stock"]["SBER"]["fundamental_score"] = "EXCELLENT"
        self.assertIn("per_stock.SBER.fundamental_score",
                      _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_invalid_advisor_verdict_blocks(self):
        d = self._ok(); d["per_stock"]["SBER"]["advisor_verdict"] = "STRONG_BUY"
        self.assertIn("per_stock.SBER.advisor_verdict",
                      _b_fields(validate_weekly_review_stock_detailed(d)))

    # === Type / range checks ===
    def test_advisor_confidence_out_of_range_blocks(self):
        d = self._ok(); d["per_stock"]["SBER"]["advisor_verdict_confidence"] = 1.5
        self.assertIn("per_stock.SBER.advisor_verdict_confidence",
                      _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_div_yield_ci_not_list_blocks(self):
        d = self._ok(); d["per_stock"]["SBER"]["div_yield_12m_pct"]["ci_pct"] = 12.0
        self.assertIn("per_stock.SBER.div_yield_12m_pct.ci_pct",
                      _b_fields(validate_weekly_review_stock_detailed(d)))

    # === Catalyst structure ===
    def test_empty_catalyst_list_blocks(self):
        d = self._ok(); d["per_stock"]["SBER"]["catalyst"] = []
        self.assertIn("per_stock.SBER.catalyst",
                      _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_catalyst_missing_source_blocks(self):
        d = self._ok(); del d["per_stock"]["SBER"]["catalyst"][0]["source"]
        self.assertIn("per_stock.SBER.catalyst[0].source",
                      _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_catalyst_no_upside_or_downside_blocks(self):
        d = self._ok()
        del d["per_stock"]["SBER"]["catalyst"][0]["upside_pct"]
        del d["per_stock"]["SBER"]["catalyst"][0]["upside_ci_pct"]
        fields = _b_fields(validate_weekly_review_stock_detailed(d))
        self.assertTrue(any("upside_pct/downside_pct" in f for f in fields),
                        f"expected upside_pct/downside_pct issue, got: {fields}")

    def test_catalyst_p_out_of_range_blocks(self):
        d = self._ok(); d["per_stock"]["SBER"]["catalyst"][0]["p"] = 1.2
        self.assertIn("per_stock.SBER.catalyst[0].p",
                      _b_fields(validate_weekly_review_stock_detailed(d)))


# ---------------------------------------------------------------------------
# TestValidateCatalystKindV2 — METH-1 (2026-05-13) binary/quantitative
# ---------------------------------------------------------------------------

class TestValidateCatalystKindV2(unittest.TestCase):
    """METH-1: catalyst.kind = binary | quantitative + scenario-aware валидация."""

    def _ok_stock(self):
        # V2-CUTOVER: v2-фикстур (schema 2 + горизонт-блок); catalyst без in_horizon
        d = _v2_stock_review()
        d["review_date"] = "2026-05-13"
        d["snapshot_id"] = "portfolio-2026-05-13.json"
        return d

    # === Legacy (без kind) — warning, не блок ===
    def test_legacy_no_kind_passes_with_warning(self):
        """Catalyst без kind → warning, save разрешён (backward-compat)."""
        d = self._ok_stock()
        # _ok_per_stock_entry без kind — legacy
        cats = d["per_stock"]["SBER"]["catalyst"]
        self.assertNotIn("kind", cats[0])  # sanity
        result = validate_weekly_review_stock_detailed(d)
        self.assertTrue(result["valid"], _b_fields(result))
        # Должна быть warning категория про kind
        warnings_fields = [i["field"] for i in result["issues"] if i["severity"] == "warning"]
        self.assertTrue(any(".kind" in f for f in warnings_fields),
                        f"expected catalyst kind warning, got warnings: {warnings_fields}")

    # === Explicit kind = binary ===
    def test_explicit_binary_passes(self):
        d = self._ok_stock()
        d["per_stock"]["SBER"]["catalyst"][0]["kind"] = "binary"
        result = validate_weekly_review_stock_detailed(d)
        self.assertTrue(result["valid"], _b_fields(result))

    def test_invalid_kind_blocks(self):
        d = self._ok_stock()
        d["per_stock"]["SBER"]["catalyst"][0]["kind"] = "weird_unknown"
        fields = _b_fields(validate_weekly_review_stock_detailed(d))
        self.assertIn("per_stock.SBER.catalyst[0].kind", fields)

    # === Quantitative ===
    def test_quantitative_valid_passes(self):
        d = self._ok_stock()
        # Меняем первый catalyst на quantitative
        cat = d["per_stock"]["SBER"]["catalyst"][0]
        cat.pop("p", None)
        cat.pop("upside_pct", None)
        cat.pop("upside_ci_pct", None)
        cat.pop("macro_dependency", None)
        cat["kind"] = "quantitative"
        cat["upside_by_scenario"] = {"A": 18, "B": 10, "C": 10, "D": 0}
        cat["upside_ci_by_scenario"] = {"A": [8, 30], "B": [3, 17], "C": [3, 17], "D": [0, 0]}
        result = validate_weekly_review_stock_detailed(d)
        self.assertTrue(result["valid"], _b_fields(result))

    def test_quantitative_missing_upside_by_scenario_blocks(self):
        d = self._ok_stock()
        cat = d["per_stock"]["SBER"]["catalyst"][0]
        cat.pop("p", None)
        cat.pop("upside_pct", None)
        cat.pop("upside_ci_pct", None)
        cat["kind"] = "quantitative"
        fields = _b_fields(validate_weekly_review_stock_detailed(d))
        self.assertIn("per_stock.SBER.catalyst[0].upside_by_scenario", fields)

    def test_quantitative_unknown_scenario_id_blocks(self):
        d = self._ok_stock()
        cat = d["per_stock"]["SBER"]["catalyst"][0]
        cat.pop("p", None); cat.pop("upside_pct", None); cat.pop("upside_ci_pct", None)
        cat["kind"] = "quantitative"
        cat["upside_by_scenario"] = {"A": 18, "Z_unknown": 10}
        fields = _b_fields(validate_weekly_review_stock_detailed(d))
        self.assertTrue(any("upside_by_scenario.Z_unknown" in f for f in fields))

    def test_quantitative_p_field_warning(self):
        d = self._ok_stock()
        cat = d["per_stock"]["SBER"]["catalyst"][0]
        cat["kind"] = "quantitative"
        cat["upside_by_scenario"] = {"A": 18, "B": 10, "C": 10, "D": 0}
        cat["upside_ci_by_scenario"] = {"A": [8, 30], "B": [3, 17], "C": [3, 17], "D": [0, 0]}
        # p remains (legacy field) — should be warning, not blocking
        result = validate_weekly_review_stock_detailed(d)
        self.assertTrue(result["valid"], _b_fields(result))
        warn_fields = [i["field"] for i in result["issues"] if i["severity"] == "warning"]
        self.assertTrue(any(".p" in f for f in warn_fields))

    def test_quantitative_todo_llm_blocks(self):
        d = self._ok_stock()
        cat = d["per_stock"]["SBER"]["catalyst"][0]
        cat.pop("p", None); cat.pop("upside_pct", None); cat.pop("upside_ci_pct", None)
        cat["kind"] = "quantitative"
        cat["upside_by_scenario"] = {"A": 18, "B": "TODO_LLM_B_value", "C": 10, "D": 0}
        fields = _b_fields(validate_weekly_review_stock_detailed(d))
        self.assertTrue(any("upside_by_scenario.B" in f for f in fields))

    # === Binary с active_scenarios ===
    def test_binary_with_active_scenarios_passes(self):
        d = self._ok_stock()
        cat = d["per_stock"]["SBER"]["catalyst"][0]
        cat["kind"] = "binary"
        cat["active_scenarios"] = ["A", "B"]
        result = validate_weekly_review_stock_detailed(d)
        self.assertTrue(result["valid"], _b_fields(result))

    def test_binary_p_warning_above_095(self):
        """p ∈ (0.95, 1] → warning (METH-1 рекомендация), не блок."""
        d = self._ok_stock()
        d["per_stock"]["SBER"]["catalyst"][0]["p"] = 0.97
        result = validate_weekly_review_stock_detailed(d)
        self.assertTrue(result["valid"], _b_fields(result))
        warn_fields = [i["field"] for i in result["issues"] if i["severity"] == "warning"]
        self.assertTrue(any("catalyst[0].p" in f for f in warn_fields))


# ---------------------------------------------------------------------------
# TestValidateUserConstraints — METH-1/v1.4
# ---------------------------------------------------------------------------

class TestValidateUserConstraints(unittest.TestCase):
    """Срез ограничений user_constraints[] (schema.md §4.2, F2.6): форма, эпоха по recorded_at, TRIPLET RULE."""

    def _stock(self, recorded_at="2026-11-06T18:00:00+03:00"):
        d = _v2_stock_review()
        d["review_date"] = "2026-11-06"
        d["snapshot_id"] = "portfolio-2026-11-05.json"
        if recorded_at:
            d["recorded_at"] = recorded_at
        entry = _ok_per_stock_entry()
        entry["catalyst"] = [_v2_catalyst()]
        d["per_stock"] = {"DOMRF": entry}
        return d

    @staticmethod
    def _rec(**over):
        r = {"derived": True, "as_of": "2026-11-06", "condition_id": "domrf-px-2200",
             "reason": "pending_buy_condition", "status": "pending", "until": "2026-12-31",
             "summary": "условие domrf-px-2200: покупать ниже 2200"}
        r.update(over)
        return r

    @staticmethod
    def _legacy():
        return {"set_date": "2026-05-13", "type": "no_buy_until_date", "active": True,
                "expires": {"type": "date", "value": "2026-05-20"}, "summary": "Lock-up до 2026-05-20"}

    def test_no_constraints_passes(self):
        self.assertTrue(validate_weekly_review_stock_detailed(self._stock())["valid"])

    def test_valid_slice_passes(self):
        d = self._stock()
        e = d["per_stock"]["DOMRF"]
        e.update(user_constraints=[self._rec(), self._rec(condition_id=None, plan_field="user_plan",
                                                          plan_value="WAIT", reason="user_plan")],
                 unconstrained_verdict="BUY", unconstrained_verdict_confidence=0.72, advisor_verdict="HOLD",
                 p_outperform_3m=0.6)
        del e["user_constraints"][1]["condition_id"]
        result = validate_weekly_review_stock_detailed(d)
        self.assertTrue(result["valid"], _b_fields(result))
        self.assertFalse([i for i in _w(result) if "user_constraints" in i["field"]])

    def test_bad_slice_blocks_in_new_review(self):
        for bad in (self._rec(as_of=None), self._rec(condition_id=None), self._rec(plan_field="user_plan"),
                    self._rec(summary=""), self._rec(derived=False), self._rec(reason="lockup")):
            d = self._stock()
            d["per_stock"]["DOMRF"]["user_constraints"] = [bad]
            fields = _b_fields(validate_weekly_review_stock_detailed(d))
            self.assertTrue(any(f.startswith("per_stock.DOMRF.user_constraints[0]") for f in fields), (bad, fields))

    def test_legacy_record_in_new_review_warns_only(self):
        d = self._stock()
        d["per_stock"]["DOMRF"]["user_constraints"] = [self._legacy()]
        result = validate_weekly_review_stock_detailed(d)
        self.assertTrue(result["valid"], _b_fields(result))
        w = [i for i in _w(result) if i["field"] == "per_stock.DOMRF.user_constraints[0]"]
        self.assertTrue(w and "устаревшая форма" in w[0]["actual"])

    def test_old_review_no_noise(self):
        d = self._stock(recorded_at="2026-10-28T00:00:00+03:00")
        d["per_stock"]["DOMRF"]["user_constraints"] = [self._legacy(), self._rec(as_of=None)]
        result = validate_weekly_review_stock_detailed(d)
        self.assertTrue(result["valid"], _b_fields(result))
        self.assertFalse([i for i in result["issues"] if "user_constraints" in i["field"]])

    def test_era_by_review_date_without_recorded_at(self):
        d = self._stock(recorded_at=None)
        d["per_stock"]["DOMRF"]["user_constraints"] = [self._rec(as_of=None)]
        self.assertIn("per_stock.DOMRF.user_constraints[0].as_of", _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_triplet_rule_needs_derived_slice(self):
        d = self._stock()
        e = d["per_stock"]["DOMRF"]
        e.update(unconstrained_verdict="BUY", advisor_verdict="HOLD", p_outperform_3m=0.6)
        self.assertIn("per_stock.DOMRF.user_constraints", _b_fields(validate_weekly_review_stock_detailed(d)))
        e["user_constraints"] = [self._legacy()]  # устаревшая форма срезом не считается
        self.assertIn("per_stock.DOMRF.user_constraints", _b_fields(validate_weekly_review_stock_detailed(d)))
        e["user_constraints"] = [self._rec()]
        self.assertTrue(validate_weekly_review_stock_detailed(d)["valid"])

    def test_triplet_rule_old_review_any_block(self):
        d = self._stock(recorded_at="2026-10-28T00:00:00+03:00")
        e = d["per_stock"]["DOMRF"]
        e.update(unconstrained_verdict="BUY", advisor_verdict="HOLD", p_outperform_3m=0.6)
        self.assertIn("per_stock.DOMRF.user_constraints", _b_fields(validate_weekly_review_stock_detailed(d)))
        e["user_constraints"] = [self._legacy()]
        self.assertTrue(validate_weekly_review_stock_detailed(d)["valid"])

    def test_not_list_blocks_in_new_review(self):
        d = self._stock()
        d["per_stock"]["DOMRF"]["user_constraints"] = "not_a_list"
        self.assertIn("per_stock.DOMRF.user_constraints", _b_fields(validate_weekly_review_stock_detailed(d)))

    def test_no_verdict_resync_and_no_carry_over_command(self):
        from scripts.assemble_artifact import COMMANDS
        import scripts.assemble_artifact as aa
        self.assertNotIn("check-constraint-carry-over", COMMANDS)
        self.assertFalse(hasattr(aa, "_reconcile_check"))
        self.assertFalse(hasattr(aa, "check_constraint_carry_over_presence"))


# ---------------------------------------------------------------------------
# TestValidateWeeklyReviewBondDetailed — full canonical schema enforcement (bond)
# ---------------------------------------------------------------------------

class TestBondRatingCheckedAt(unittest.TestCase):
    """credit_rating_checked_at: формат — warning, устаревание — одно сводное warning rating_check_due."""

    def _doc(self, **entry_kw):
        d = _v2_bond_review()
        d["snapshot_date"] = "2026-05-12"
        e = next(iter(d["per_bond"].values()))
        e["bond_type"] = "corp_rub"
        e.update(entry_kw)
        return d

    def _due(self, r):
        return [i for i in r["issues"] if i["field"] == "rating_check_due"]

    def test_old_format_without_field_valid_with_one_summary_warning(self):
        d = self._doc()
        d["per_bond"]["RU2"] = copy.deepcopy(d["per_bond"]["RU000A105KU0"])   # вторая корп-бумага
        r = validate_weekly_review_bond_detailed(d)
        self.assertTrue(r["valid"], _b_fields(r))
        due = self._due(r)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["severity"], "warning")
        self.assertIn("RU000A105KU0", due[0]["actual"])
        self.assertIn("RU2", due[0]["actual"])

    def test_fresh_and_28_days_no_warning(self):
        for dt in ("2026-05-12", "2026-04-14"):    # сегодня и ровно 28 дней
            r = validate_weekly_review_bond_detailed(self._doc(credit_rating_checked_at=dt))
            self.assertTrue(r["valid"]); self.assertEqual(self._due(r), [], dt)

    def test_29_days_warns_not_blocks(self):
        r = validate_weekly_review_bond_detailed(self._doc(credit_rating_checked_at="2026-04-13"))
        self.assertTrue(r["valid"]); self.assertEqual(len(self._due(r)), 1)

    def test_ofz_never_listed(self):
        r = validate_weekly_review_bond_detailed(self._doc(bond_type="ofz", credit_rating_checked_at=None))
        self.assertEqual(self._due(r), [])

    def test_bad_format_and_future_date_are_warnings(self):
        for bad in ("12.05.2026", "2026-13-45", 20260512, "2026-05-13"):
            r = validate_weekly_review_bond_detailed(self._doc(credit_rating_checked_at=bad))
            self.assertTrue(r["valid"], bad)
            self.assertIn("per_bond.RU000A105KU0.credit_rating_checked_at", _w_fields(r), bad)


class TestValidateWeeklyReviewBondDetailed(unittest.TestCase):
    """Детальная валидация bond weekly-review YAML (V2-CUTOVER: фикстур v2)."""

    def _ok(self):
        return _v2_bond_review()

    # Positive
    def test_valid_payload_passes(self):
        result = validate_weekly_review_bond_detailed(self._ok())
        self.assertTrue(result["valid"], _b_fields(result))

    # Единый словарь вердиктов (schema.md §3.4, шаг 8): целевые коды; прежние коды — блок
    def test_bond_verdicts_single_dictionary(self):
        for v in ("BUY", "ADD", "HOLD", "HOLD_TO_MAT", "WATCH", "TRIM", "SELL"):
            d = self._ok()
            for e in d["per_bond"].values():
                e["advisor_verdict"] = v
                e.setdefault("p_outperform_3m", 0.5)
            fields = _b_fields(validate_weekly_review_bond_detailed(d))
            self.assertFalse(any(f.endswith(".advisor_verdict") for f in fields), (v, fields))
        for v in ("HOLD_ADD", "RED_FLAG", "MATURE", "HOLD_NO_OFFER"):    # прежние коды снятых допусков — блок
            d = self._ok()
            next(iter(d["per_bond"].values()))["advisor_verdict"] = v
            self.assertTrue(any(f.endswith(".advisor_verdict") for f in _b_fields(validate_weekly_review_bond_detailed(d))), v)
        d = self._ok()
        next(iter(d["per_bond"].values()))["advisor_verdict"] = "reviewed_keep"
        self.assertTrue(any(f.endswith(".advisor_verdict") for f in _b_fields(validate_weekly_review_bond_detailed(d))))

    # Top-level
    def test_schema_version_string_blocks(self):
        d = self._ok(); d["schema_version"] = "1"
        self.assertIn("schema_version", _b_fields(validate_weekly_review_bond_detailed(d)))

    def test_wrong_type_blocks(self):
        d = self._ok(); d["type"] = "weekly-bonds"
        self.assertIn("type", _b_fields(validate_weekly_review_bond_detailed(d)))

    def test_missing_review_date_blocks(self):
        d = self._ok(); del d["review_date"]
        self.assertIn("review_date", _b_fields(validate_weekly_review_bond_detailed(d)))

    # summary block
    def test_missing_summary_blocks(self):
        d = self._ok(); del d["summary"]
        self.assertIn("summary", _b_fields(validate_weekly_review_bond_detailed(d)))

    def test_missing_total_value_rub_blocks(self):
        d = self._ok(); del d["summary"]["total_value_rub"]
        self.assertIn("summary.total_value_rub",
                      _b_fields(validate_weekly_review_bond_detailed(d)))

    def test_drift_bonds_total_rub_without_total_value_rub_blocks(self):
        """bonds_total_rub без total_value_rub — drift."""
        d = self._ok()
        d["summary"]["bonds_total_rub"] = d["summary"].pop("total_value_rub")
        self.assertIn("summary.bonds_total_rub",
                      _b_fields(validate_weekly_review_bond_detailed(d)))

    def test_weighted_ytm_pct_number_form_passes(self):
        """weighted_ytm_pct может быть числом (legacy) или {value, ci_pct}."""
        d = self._ok(); d["summary"]["weighted_ytm_pct"] = 15.67
        self.assertTrue(validate_weekly_review_bond_detailed(d)["valid"])

    def test_weighted_ytm_pct_object_missing_ci_blocks(self):
        d = self._ok()
        d["summary"]["weighted_ytm_pct"] = {"value": 15.67}
        self.assertIn("summary.weighted_ytm_pct.ci_pct",
                      _b_fields(validate_weekly_review_bond_detailed(d)))

    def test_weighted_duration_days_as_object_blocks(self):
        d = self._ok()
        d["summary"]["weighted_duration_days"] = {"main_only": 1420, "main_plus_iis": 1500}
        self.assertIn("summary.weighted_duration_days",
                      _b_fields(validate_weekly_review_bond_detailed(d)))

    def test_invalid_credit_quality_keys_blocks(self):
        d = self._ok()
        d["summary"]["by_credit_quality_pct"] = {"GOOD": 70, "BAD": 30}
        self.assertIn("summary.by_credit_quality_pct",
                      _b_fields(validate_weekly_review_bond_detailed(d)))

    def test_empty_per_bond_blocks(self):
        d = self._ok(); d["per_bond"] = {}
        self.assertIn("per_bond", _b_fields(validate_weekly_review_bond_detailed(d)))

    # per_bond entry checks
    def test_missing_bond_type_blocks(self):
        d = self._ok(); del d["per_bond"]["RU000A105KU0"]["bond_type"]
        self.assertIn("per_bond.RU000A105KU0.bond_type",
                      _b_fields(validate_weekly_review_bond_detailed(d)))

    def test_invalid_bond_type_enum_blocks(self):
        d = self._ok(); d["per_bond"]["RU000A105KU0"]["bond_type"] = "weird_bond"
        self.assertIn("per_bond.RU000A105KU0.bond_type",
                      _b_fields(validate_weekly_review_bond_detailed(d)))

    def test_invalid_credit_quality_blocks(self):
        d = self._ok(); d["per_bond"]["RU000A105KU0"]["credit_quality"] = "AAA"
        self.assertIn("per_bond.RU000A105KU0.credit_quality",
                      _b_fields(validate_weekly_review_bond_detailed(d)))

    def test_todo_llm_in_advisor_verdict_blocks(self):
        d = self._ok()
        d["per_bond"]["RU000A105KU0"]["advisor_verdict"] = "TODO_LLM_HOLD_TRIM_SELL"
        self.assertIn("per_bond.RU000A105KU0.advisor_verdict",
                      _b_fields(validate_weekly_review_bond_detailed(d)))

    def test_empty_catalyst_blocks(self):
        d = self._ok(); d["per_bond"]["RU000A105KU0"]["catalyst"] = []
        self.assertIn("per_bond.RU000A105KU0.catalyst",
                      _b_fields(validate_weekly_review_bond_detailed(d)))


# ---------------------------------------------------------------------------
# TestBondPlanTaxonomyFields — STL-9: plan_bucket/plan_subtype/credit_rating_file/
# is_floater (bond-subtypes-plan.md §4, STL-7/8). Опциональные поля per_bond entry —
# отсутствие не blocking (§4.4, старые артефакты), невалидная пара/тип — warning, не
# blocking (симметрично PDL-7 bond_subtype_* гейтам, severity warn).
# ---------------------------------------------------------------------------

class TestBondPlanTaxonomyFields(unittest.TestCase):
    def _ok(self):
        return _v2_bond_review()

    def _entry(self, d):
        return d["per_bond"]["RU000A105KU0"]

    def _plan_w(self, result):
        """Warnings, относящиеся ТОЛЬКО к новым полям (базовая фикстура несёт свои
        предсуществующие catalyst-warnings — kind/p/macro_dependency/source_trust,
        не имеющие отношения к STL-7/8)."""
        fields = ("plan_bucket", "plan_subtype", "credit_rating_file", "is_floater")
        return [i for i in _w(result) if any(f in i["field"] for f in fields)]

    # --- back-compat: полное отсутствие полей ---
    def test_fields_absent_no_issues(self):
        """§4.4: артефакты до 2026-08-18 не несут новых полей — ни одного issue."""
        d = self._ok()
        entry = self._entry(d)
        for f in ("plan_bucket", "plan_subtype", "credit_rating_file", "is_floater"):
            entry.pop(f, None)
        result = validate_weekly_review_bond_detailed(d)
        self.assertTrue(result["valid"])
        related = [i for i in result["issues"]
                   if any(f in i["field"] for f in
                          ("plan_bucket", "plan_subtype", "credit_rating_file", "is_floater"))]
        self.assertEqual(related, [], related)

    # --- допустимые пары §4.3 — проходят без warning ---
    def test_valid_pair_usd_null_passes(self):
        d = self._ok(); e = self._entry(d)
        e["plan_bucket"] = "USD"; e["plan_subtype"] = None
        self.assertFalse(self._plan_w(validate_weekly_review_bond_detailed(d)))

    def test_valid_pair_eur_null_passes(self):
        d = self._ok(); e = self._entry(d)
        e["plan_bucket"] = "EUR"; e["plan_subtype"] = None
        self.assertFalse(self._plan_w(validate_weekly_review_bond_detailed(d)))

    def test_valid_pair_cny_null_passes(self):
        d = self._ok(); e = self._entry(d)
        e["plan_bucket"] = "CNY"; e["plan_subtype"] = None
        self.assertFalse(self._plan_w(validate_weekly_review_bond_detailed(d)))

    def test_valid_pair_ofz_gt10_passes(self):
        d = self._ok(); e = self._entry(d)
        e["plan_bucket"] = "ОФЗ"; e["plan_subtype"] = ">10"
        self.assertFalse(self._plan_w(validate_weekly_review_bond_detailed(d)))

    def test_valid_pair_ofz_lt10_passes(self):
        d = self._ok(); e = self._entry(d)
        e["plan_bucket"] = "ОФЗ"; e["plan_subtype"] = "<10"
        self.assertFalse(self._plan_w(validate_weekly_review_bond_detailed(d)))

    def test_valid_pair_ofz_floater_passes(self):
        """ОФЗ-ПК: plan_subtype=Флоат + is_floater=true, bond_type остаётся ofz
        (не трогается валидатором — решение RPA-14, ортогональность полей)."""
        d = self._ok(); e = self._entry(d)
        e["plan_bucket"] = "ОФЗ"; e["plan_subtype"] = "Флоат"
        e["is_floater"] = True
        e["bond_type"] = "ofz"
        result = validate_weekly_review_bond_detailed(d)
        self.assertTrue(result["valid"])
        self.assertFalse(self._plan_w(result))
        self.assertEqual(e["bond_type"], "ofz")

    def test_valid_pair_corp_aa_plus_passes(self):
        d = self._ok(); e = self._entry(d)
        e["plan_bucket"] = "КОРП"; e["plan_subtype"] = "AA+"
        self.assertFalse(self._plan_w(validate_weekly_review_bond_detailed(d)))

    def test_valid_pair_corp_a_passes(self):
        d = self._ok(); e = self._entry(d)
        e["plan_bucket"] = "КОРП"; e["plan_subtype"] = "A"
        self.assertFalse(self._plan_w(validate_weekly_review_bond_detailed(d)))

    def test_valid_pair_corp_b_plus_passes(self):
        d = self._ok(); e = self._entry(d)
        e["plan_bucket"] = "КОРП"; e["plan_subtype"] = "B+"
        self.assertFalse(self._plan_w(validate_weekly_review_bond_detailed(d)))

    def test_valid_pair_corp_floater_passes(self):
        """Q4: КОРП/Флоат структурно разрешена (флаг «корзина вне плана» — забота
        data-loader/PDL-7, не save-to-library)."""
        d = self._ok(); e = self._entry(d)
        e["plan_bucket"] = "КОРП"; e["plan_subtype"] = "Флоат"
        self.assertFalse(self._plan_w(validate_weekly_review_bond_detailed(d)))

    # --- невалидные пары — ловятся (warning, не blocking) ---
    def test_invalid_bucket_unknown_warns(self):
        d = self._ok(); e = self._entry(d)
        e["plan_bucket"] = "GBP"; e["plan_subtype"] = None
        result = validate_weekly_review_bond_detailed(d)
        self.assertTrue(result["valid"])  # warning, не blocking
        self.assertTrue(any("plan_bucket" in i["field"] for i in self._plan_w(result)))

    def test_invalid_subtype_for_currency_bucket_warns(self):
        d = self._ok(); e = self._entry(d)
        e["plan_bucket"] = "USD"; e["plan_subtype"] = "A"
        result = validate_weekly_review_bond_detailed(d)
        self.assertTrue(result["valid"])
        self.assertTrue(any("plan_subtype" in i["field"] for i in self._plan_w(result)))

    def test_invalid_subtype_for_ofz_bucket_warns(self):
        d = self._ok(); e = self._entry(d)
        e["plan_bucket"] = "ОФЗ"; e["plan_subtype"] = "AA+"
        result = validate_weekly_review_bond_detailed(d)
        self.assertTrue(any("plan_subtype" in i["field"] for i in self._plan_w(result)))

    def test_invalid_subtype_for_corp_bucket_warns(self):
        d = self._ok(); e = self._entry(d)
        e["plan_bucket"] = "КОРП"; e["plan_subtype"] = ">10"
        result = validate_weekly_review_bond_detailed(d)
        self.assertTrue(any("plan_subtype" in i["field"] for i in self._plan_w(result)))

    def test_rating_label_not_accepted_as_corp_subtype(self):
        """Имена корзин ≠ рейтинги (§4.2): 'AAA' — рейтинг, не имя корзины ('AA+') —
        подстановка рейтинга вместо имени корзины ловится как неизвестный подтип."""
        d = self._ok(); e = self._entry(d)
        e["plan_bucket"] = "КОРП"; e["plan_subtype"] = "AAA"
        result = validate_weekly_review_bond_detailed(d)
        self.assertTrue(any("plan_subtype" in i["field"] for i in self._plan_w(result)))

    def test_subtype_without_bucket_warns(self):
        """plan_subtype присутствует, plan_bucket — нет: пара невалидна."""
        d = self._ok(); e = self._entry(d)
        e["plan_subtype"] = ">10"
        result = validate_weekly_review_bond_detailed(d)
        self.assertTrue(any("plan_bucket" in i["field"] for i in self._plan_w(result)))

    # --- is_floater: тип bool ---
    def test_is_floater_true_passes(self):
        d = self._ok(); e = self._entry(d)
        e["is_floater"] = True
        self.assertFalse(self._plan_w(validate_weekly_review_bond_detailed(d)))

    def test_is_floater_false_passes(self):
        d = self._ok(); e = self._entry(d)
        e["is_floater"] = False
        self.assertFalse(self._plan_w(validate_weekly_review_bond_detailed(d)))

    def test_is_floater_string_warns(self):
        d = self._ok(); e = self._entry(d)
        e["is_floater"] = "true"
        result = validate_weekly_review_bond_detailed(d)
        self.assertTrue(result["valid"])
        self.assertTrue(any("is_floater" in i["field"] for i in self._plan_w(result)))

    def test_is_floater_int_warns(self):
        d = self._ok(); e = self._entry(d)
        e["is_floater"] = 1
        result = validate_weekly_review_bond_detailed(d)
        self.assertTrue(any("is_floater" in i["field"] for i in self._plan_w(result)))

    # --- credit_rating_file: справочное поле (Q5), enum не проверяется ---
    def test_credit_rating_file_any_string_no_issue(self):
        d = self._ok(); e = self._entry(d)
        e["credit_rating_file"] = "A"
        result = validate_weekly_review_bond_detailed(d)
        self.assertTrue(result["valid"])
        self.assertFalse(any("credit_rating_file" in i["field"] for i in result["issues"]))

    def test_credit_rating_file_does_not_replace_credit_rating(self):
        """Q5: credit_rating_file — справка для сверки, credit_rating остаётся
        обязательным LLM-полем (VALID_ADVISOR_VERDICT_BOND независим от него)."""
        d = self._ok(); e = self._entry(d)
        e["credit_rating_file"] = "BBB"
        e.pop("credit_rating", None)  # credit_rating и не был обязательным сам по себе
        result = validate_weekly_review_bond_detailed(d)
        self.assertTrue(result["valid"])


# ---------------------------------------------------------------------------
# TestValidatePortfolioSnapshot — 4 tests (Workflow H)
# ---------------------------------------------------------------------------

class TestValidatePortfolioSnapshot(unittest.TestCase):
    def _ok(self):
        return {
            "schema_version": "2.0",
            "positions": [{"ticker": "SBER", "weight_pct": 30.0}],
            "total_value": 1_000_000.0,
        }

    def test_valid(self):
        self.assertTrue(validate_portfolio_snapshot(self._ok())["valid"])

    def test_wrong_schema_version(self):
        d = self._ok(); d["schema_version"] = "1.0"
        self.assertIn("schema_version", _b_fields(validate_portfolio_snapshot(d)))

    def test_empty_positions(self):
        d = self._ok(); d["positions"] = []
        self.assertFalse(validate_portfolio_snapshot(d)["valid"])

    def test_zero_total_value(self):
        d = self._ok(); d["total_value"] = 0
        self.assertFalse(validate_portfolio_snapshot(d)["valid"])


# ---------------------------------------------------------------------------
# TestValidateScenarioEvents — 5 tests (Workflow C)
# ---------------------------------------------------------------------------

class TestValidateScenarioEvents(unittest.TestCase):
    def _ok(self):
        return {
            "type": "scenario-events",
            "schema_version": 1,
            # polarity задекларирован по канону (§17 F4) — иначе soft-warning про рассинхрон.
            "matrix": {"topic": "ai-capex-scenarios",
                       "polarity": {"stress_pole": "A", "detente_pole": "D"}},
            "scenario_triggers": [
                {"scenario_id": "A", "probability": 0.25},
                {"scenario_id": "B", "probability": 0.25},
                {"scenario_id": "C", "probability": 0.25},
                {"scenario_id": "D", "probability": 0.25},
            ],
            "reviews": {"interval_months": 6, "next_due": "2026-11-01"},
        }

    def test_valid(self):
        result = validate_scenario_events(self._ok())
        self.assertTrue(result["valid"])
        self.assertEqual(result["issues"], [])

    def test_missing_scenario_triggers(self):
        d = self._ok()
        del d["scenario_triggers"]
        self.assertIn("scenario_triggers", _b_fields(validate_scenario_events(d)))

    def test_probability_sum_out_of_range(self):
        d = self._ok()
        d["scenario_triggers"][0]["probability"] = 0.05  # sum = 0.80
        result = validate_scenario_events(d)
        self.assertTrue(result["valid"])  # warning only, not blocking
        fields = [i["field"] for i in _w(result)]
        self.assertIn("scenario_triggers[*].probability", fields)

    def test_empty_scenario_triggers(self):
        d = self._ok()
        d["scenario_triggers"] = []
        self.assertIn("scenario_triggers", _b_fields(validate_scenario_events(d)))

    def test_missing_reviews(self):
        d = self._ok()
        del d["reviews"]
        self.assertIn("reviews", _b_fields(validate_scenario_events(d)))


class TestValidateForecastEvents(unittest.TestCase):
    """events-yaml-spec.md §5: Type 1 isolated vs Type 2 conditional_on_scenarios."""

    def _ok_conditional(self):
        return {
            "forecast": {
                "central_estimate": "Test: 11.5% к 2026-12-31 (weighted FCA across all sources)",
            },
            "conditional_on_scenarios": {
                "source_matrix": "scenarios/scenario-test-2026-05-04.yaml",
                "scenario_id_format": "short",
                "unit": "%",
                "by_scenario": {
                    "A": {
                        "values": {"2026-12-31": {"central": 10.0, "range": [9.0, 11.0]}},
                        "provenance": "derived_from_marginal",
                        "sources_used": [],
                        "coverage_quality": "DERIVED",
                    },
                    "B": {
                        "values": {"2026-12-31": {"central": 12.0, "range": [11.0, 13.0]}},
                        "provenance": "native_fca",
                        "sources_used": ["src1", "src2"],
                        "coverage_quality": "MEDIUM",
                    },
                    "C": {
                        "values": {"2026-12-31": {"central": 11.0, "range": [10.0, 12.0]}},
                        "provenance": "single_native",
                        "sources_used": ["src3"],
                        "coverage_quality": "LOW",
                    },
                    "D": {
                        "values": {"2026-12-31": {"central": 13.0, "range": [12.0, 14.0]}},
                        "provenance": "native_fca",
                        "sources_used": ["src1", "src2", "src3", "src4", "src5"],
                        "coverage_quality": "HIGH",
                    },
                },
                "marginal": {
                    "method": "linear",
                    "modal_scenario_id": "none",
                    "values": {"2026-12-31": {"central": 11.5, "range": [9.0, 14.0]}},
                    "aggregation_formula": "weighted_mean",
                },
            },
            "coherence_diagnostic": {
                "layer1_marginal": 11.7,
                "layer2_marginal": 11.5,
                "divergence_pct": 1.7,
                "severity": "LOW",
                "warning": None,
            },
        }

    def _ok_isolated(self):
        return {
            "isolated": True,
            "isolated_reason": "Single binary event без сценарной декомпозиции",
        }

    # --- Type 1 (isolated) ---

    def test_valid_isolated(self):
        self.assertTrue(validate_forecast_events(self._ok_isolated())["valid"])

    def test_isolated_missing_reason(self):
        d = self._ok_isolated()
        del d["isolated_reason"]
        self.assertIn("isolated_reason", _b_fields(validate_forecast_events(d)))

    def test_isolated_reason_too_long(self):
        d = self._ok_isolated()
        d["isolated_reason"] = "x" * 250
        self.assertIn("isolated_reason", _b_fields(validate_forecast_events(d)))

    # --- Type 2 (conditional) ---

    def test_valid_conditional(self):
        self.assertTrue(validate_forecast_events(self._ok_conditional())["valid"])

    def test_neither_isolated_nor_conditional(self):
        result = validate_forecast_events({})
        self.assertFalse(result["valid"])
        self.assertIn(
            "isolated|conditional_on_scenarios",
            _b_fields(result),
        )

    def test_both_isolated_and_conditional(self):
        d = self._ok_conditional()
        d["isolated"] = True
        d["isolated_reason"] = "should not have both"
        self.assertIn("isolated", _b_fields(validate_forecast_events(d)))

    def test_missing_source_matrix(self):
        d = self._ok_conditional()
        del d["conditional_on_scenarios"]["source_matrix"]
        self.assertIn(
            "conditional_on_scenarios.source_matrix",
            _b_fields(validate_forecast_events(d)),
        )

    def test_source_matrix_wrong_prefix(self):
        d = self._ok_conditional()
        d["conditional_on_scenarios"]["source_matrix"] = "Claude-Memory/scenarios/x.yaml"
        self.assertIn(
            "conditional_on_scenarios.source_matrix",
            _b_fields(validate_forecast_events(d)),
        )

    def test_only_three_scenarios(self):
        d = self._ok_conditional()
        del d["conditional_on_scenarios"]["by_scenario"]["C"]
        fields = _b_fields(validate_forecast_events(d))
        self.assertTrue(any("by_scenario" in f for f in fields))

    def test_extra_scenario_id(self):
        d = self._ok_conditional()
        d["conditional_on_scenarios"]["by_scenario"]["E"] = (
            d["conditional_on_scenarios"]["by_scenario"]["A"]
        )
        fields = _b_fields(validate_forecast_events(d))
        self.assertTrue(any("by_scenario" in f for f in fields))

    def test_invalid_provenance(self):
        d = self._ok_conditional()
        d["conditional_on_scenarios"]["by_scenario"]["A"]["provenance"] = "other"
        self.assertIn(
            "conditional_on_scenarios.by_scenario.A.provenance",
            _b_fields(validate_forecast_events(d)),
        )

    def test_invalid_coverage_quality(self):
        d = self._ok_conditional()
        d["conditional_on_scenarios"]["by_scenario"]["B"]["coverage_quality"] = "EXCELLENT"
        self.assertIn(
            "conditional_on_scenarios.by_scenario.B.coverage_quality",
            _b_fields(validate_forecast_events(d)),
        )

    def test_unit_mismatch_per_scenario(self):
        d = self._ok_conditional()
        d["conditional_on_scenarios"]["by_scenario"]["A"]["unit"] = "USD"
        self.assertIn(
            "conditional_on_scenarios.by_scenario.A.unit",
            _b_fields(validate_forecast_events(d)),
        )

    def test_unit_mismatch_marginal(self):
        d = self._ok_conditional()
        d["conditional_on_scenarios"]["marginal"]["unit"] = "RUB"
        self.assertIn(
            "conditional_on_scenarios.marginal.unit",
            _b_fields(validate_forecast_events(d)),
        )

    def test_invalid_marginal_method(self):
        d = self._ok_conditional()
        d["conditional_on_scenarios"]["marginal"]["method"] = "exotic"
        self.assertIn(
            "conditional_on_scenarios.marginal.method",
            _b_fields(validate_forecast_events(d)),
        )

    def test_invalid_modal_scenario_id(self):
        d = self._ok_conditional()
        d["conditional_on_scenarios"]["marginal"]["modal_scenario_id"] = "Z"
        self.assertIn(
            "conditional_on_scenarios.marginal.modal_scenario_id",
            _b_fields(validate_forecast_events(d)),
        )

    # --- coherence_diagnostic threshold checks ---

    def test_severity_low_at_high_divergence(self):
        d = self._ok_conditional()
        d["coherence_diagnostic"]["divergence_pct"] = 10.0
        d["coherence_diagnostic"]["severity"] = "LOW"
        self.assertIn("coherence_diagnostic.severity", _b_fields(validate_forecast_events(d)))

    def test_severity_high_at_low_divergence(self):
        d = self._ok_conditional()
        d["coherence_diagnostic"]["divergence_pct"] = 3.0
        d["coherence_diagnostic"]["severity"] = "HIGH"
        self.assertIn("coherence_diagnostic.severity", _b_fields(validate_forecast_events(d)))

    def test_negative_divergence(self):
        d = self._ok_conditional()
        d["coherence_diagnostic"]["divergence_pct"] = -1.0
        self.assertIn(
            "coherence_diagnostic.divergence_pct",
            _b_fields(validate_forecast_events(d)),
        )

    def test_invalid_severity_value(self):
        d = self._ok_conditional()
        d["coherence_diagnostic"]["severity"] = "CRITICAL"
        self.assertIn("coherence_diagnostic.severity", _b_fields(validate_forecast_events(d)))

    def test_type2_missing_layer1_marginal_blocks(self):
        """Type 2 conditional обязан иметь forecast.central_estimate (Layer 1) — иначе ru-portfolio-advisor лишается точечной оценки."""
        d = self._ok_conditional()
        del d["forecast"]
        self.assertIn("forecast.central_estimate", _b_fields(validate_forecast_events(d)))

    def test_type2_empty_layer1_marginal_blocks(self):
        d = self._ok_conditional()
        d["forecast"]["central_estimate"] = ""
        self.assertIn("forecast.central_estimate", _b_fields(validate_forecast_events(d)))

    # ── FCA-3 (§5.2.1): канон provenance + upstream_used + кросс-правила ──

    def test_new_canonical_provenance_accepted(self):
        d = self._ok_conditional()
        d["conditional_on_scenarios"]["by_scenario"]["C"].update({
            "provenance": "derived_from_upstream",
            "sources_used": [],
            "upstream_used": [{"factor": "brent", "value": 62, "unit": "USD/bbl"}],
        })
        self.assertTrue(validate_forecast_events(d)["valid"])

    def test_legacy_provenance_blocking_with_migration_hint(self):
        d = self._ok_conditional()
        d["conditional_on_scenarios"]["by_scenario"]["C"]["provenance"] = "structural_derivation"
        r = validate_forecast_events(d)
        prov = [i for i in r["issues"]
                if i["field"].endswith("C.provenance") and i["severity"] == "blocking"]
        self.assertEqual(len(prov), 1)
        self.assertIn("derived_from_upstream", prov[0]["actual"])

    def test_cross_rule_warning_by_default_blocking_in_strict(self):
        """derived_from_upstream без upstream_used: warning мягко, blocking в strict."""
        d = self._ok_conditional()
        d["conditional_on_scenarios"]["by_scenario"]["C"].update({
            "provenance": "derived_from_upstream", "sources_used": [],
        })
        soft = validate_forecast_events(d)
        cross = [i for i in soft["issues"] if i["field"].endswith("C.upstream_used")]
        self.assertEqual([i["severity"] for i in cross], ["warning"])
        self.assertTrue(soft["valid"])  # warning не блокирует

        d["_strict"] = True
        hard = validate_forecast_events(d)
        cross = [i for i in hard["issues"] if i["field"].endswith("C.upstream_used")]
        self.assertEqual([i["severity"] for i in cross], ["blocking"])
        self.assertFalse(hard["valid"])

    def test_upstream_used_shape_always_blocking(self):
        d = self._ok_conditional()
        d["conditional_on_scenarios"]["by_scenario"]["B"]["upstream_used"] = [
            {"factor": "", "value": "62"},
        ]
        r = validate_forecast_events(d)
        fields = _b_fields(r)
        self.assertTrue(any(f.endswith("[0].factor") for f in fields), fields)
        self.assertTrue(any(f.endswith("[0].value") for f in fields), fields)

    def test_strict_flags_nonspec_fca_shapes(self):
        """FCA-2: horizon_YYYY / central_estimate в values / sources_used int / coherence внутри cond."""
        d = self._ok_conditional()
        cond = d["conditional_on_scenarios"]
        cond["by_scenario"]["A"]["horizon_2026"] = {"central_estimate": 10.0}
        cond["by_scenario"]["B"]["sources_used"] = 3
        cond["by_scenario"]["D"]["values"]["2027-12-31"] = {
            "central_estimate": 13.5, "p10": 12.0, "p90": 15.0,
        }
        cond["coherence_diagnostic"] = d.pop("coherence_diagnostic")

        soft = validate_forecast_events(dict(d))
        soft_fields = _b_fields(soft)
        self.assertFalse(any("horizon_2026" in str(i.get("actual")) for i in soft["issues"]
                             if i["severity"] == "blocking"))

        d["_strict"] = True
        hard = validate_forecast_events(d)
        hard_fields = _b_fields(hard)
        self.assertIn("conditional_on_scenarios.by_scenario.A", hard_fields)
        self.assertIn("conditional_on_scenarios.by_scenario.B.sources_used", hard_fields)
        self.assertIn("conditional_on_scenarios.by_scenario.D.values.2027-12-31", hard_fields)
        self.assertIn("conditional_on_scenarios.coherence_diagnostic", hard_fields)
        self.assertNotIn("conditional_on_scenarios.coherence_diagnostic", soft_fields)


class TestYamlDuplicateDetection(unittest.TestCase):
    """Top-level duplicate-key guard для assemble_artifact."""

    def test_clean_yaml_no_duplicates(self):
        text = "monitoring:\n  - id: a\nfalsifiers:\n  - id: b\n"
        self.assertEqual(find_yaml_top_level_duplicates(text), [])

    def test_two_monitoring_keys_detected(self):
        text = (
            "monitoring:\n"
            "  - id: a\n"
            "falsifiers:\n"
            "  - id: b\n"
            "\n"
            "# HST Tier 2 patch\n"
            "monitoring:\n"
            "  - id: c\n"
        )
        dups = find_yaml_top_level_duplicates(text)
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["key"], "monitoring")
        self.assertEqual(dups[0]["first_line"], 1)
        self.assertEqual(dups[0]["duplicate_line"], 7)

    def test_nested_same_key_is_ok(self):
        text = (
            "forecast:\n"
            "  central_estimate:\n"
            "    value: 81\n"
            "conditional_on_scenarios:\n"
            "  by_scenario:\n"
            "    A:\n"
            "      central_estimate:\n"
            "        value: 90\n"
        )
        self.assertEqual(find_yaml_top_level_duplicates(text), [])

    def test_list_items_with_id_ignored(self):
        text = (
            "monitoring:\n"
            "  - id: first\n"
            "  - id: second\n"
        )
        self.assertEqual(find_yaml_top_level_duplicates(text), [])

    def test_block_scalar_body_ignored(self):
        text = (
            "description: |\n"
            "  monitoring: this is just text\n"
            "  status: not a key\n"
            "monitoring:\n"
            "  - id: real\n"
        )
        # description, monitoring — два разных top-level ключа, никаких дубликатов.
        self.assertEqual(find_yaml_top_level_duplicates(text), [])

    def test_check_yaml_duplicates_valid(self):
        result = check_yaml_duplicates({"yaml_text": "foo: 1\nbar: 2\n"})
        self.assertTrue(result["valid"])
        self.assertEqual(result["blocking_count"], 0)
        self.assertEqual(result["duplicates"], [])

    def test_check_yaml_duplicates_invalid(self):
        result = check_yaml_duplicates({
            "yaml_text": "foo: 1\nfoo: 2\n",
            "file": "x.yaml",
        })
        self.assertFalse(result["valid"])
        self.assertEqual(result["blocking_count"], 1)
        self.assertEqual(result["issues"][0]["severity"], "blocking")
        self.assertEqual(result["issues"][0]["key"], "foo")

    def test_three_duplicates_in_one_file(self):
        text = (
            "a: 1\n"
            "b: 2\n"
            "a: 3\n"  # dup #1
            "c: 4\n"
            "b: 5\n"  # dup #2
            "a: 6\n"  # dup #3 (a again)
        )
        dups = find_yaml_top_level_duplicates(text)
        self.assertEqual(len(dups), 3)

    def test_empty_string_no_duplicates(self):
        self.assertEqual(find_yaml_top_level_duplicates(""), [])

    def test_non_string_input_safe(self):
        # Защита от случайного None/dict в payload.
        self.assertEqual(find_yaml_top_level_duplicates(None), [])
        self.assertEqual(find_yaml_top_level_duplicates(123), [])

    def test_comments_and_blanks_ignored(self):
        text = (
            "# leading comment\n"
            "\n"
            "alpha: 1\n"
            "# alpha: 2  (in comment — должен игнорироваться)\n"
            "beta: 3\n"
        )
        self.assertEqual(find_yaml_top_level_duplicates(text), [])


class TestYamlNestedDuplicateDetection(unittest.TestCase):
    """STL-6: вложенный duplicate-guard (find_yaml_nested_duplicates).

    Позитив — DOMRF-паттерн инцидента 2026-06-28 (вложенный дубль после
    user_constraints). Негативы — классы, где блокирующий валидатор обязан
    молчать. Зеркало yaml.compose — в test_mirror_agreement (пропускается
    без PyYAML: сканер обязан оставаться stdlib-only).
    """

    DOMRF_TEXT = (
        "per_stock:\n"
        "  DOMRF:\n"
        "    unconstrained_verdict: HOLD\n"
        "    user_constraints:\n"
        "      - kind: max_share\n"
        '        set_date: "2026-06-01"\n'
        "    unconstrained_verdict: HOLD\n"
    )

    def test_domrf_nested_duplicate_detected(self):
        dups = find_yaml_nested_duplicates(self.DOMRF_TEXT)
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["key"], "unconstrained_verdict")
        self.assertEqual(dups[0]["path"], "per_stock.DOMRF")
        self.assertEqual(dups[0]["first_line"], 3)
        self.assertEqual(dups[0]["duplicate_line"], 7)

    def test_repeat_keys_in_sibling_list_items_ok(self):
        text = (
            "conditions:\n"
            "  - id: a\n"
            '    set_date: "2026-01-01"\n'
            "  - id: b\n"
            '    set_date: "2026-02-02"\n'
        )
        self.assertEqual(find_yaml_nested_duplicates(text), [])

    def test_duplicate_inside_one_list_item_detected(self):
        text = (
            "catalysts:\n"
            "  - id: x\n"
            "    p: 0.5\n"
            "    p: 0.6\n"
        )
        dups = find_yaml_nested_duplicates(text)
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["key"], "p")
        self.assertEqual(dups[0]["path"], "catalysts.[]")

    def test_same_key_under_different_parents_ok(self):
        text = "a:\n  x: 1\nb:\n  x: 2\n"
        self.assertEqual(find_yaml_nested_duplicates(text), [])

    def test_block_scalar_body_with_keylike_lines_ok(self):
        text = (
            "basis: |\n"
            "  key: 1\n"
            "  key: 2\n"
            "next: ok\n"
        )
        self.assertEqual(find_yaml_nested_duplicates(text), [])

    def test_quoted_date_key_siblings_with_same_child_ok(self):
        """Реальный формат values-блоков FCA: соседние даты-ключи с одинаковым child."""
        text = (
            "values:\n"
            '  "2026-12-31":\n'
            "    central: 65\n"
            '  "2027-12-31":\n'
            "    central: 60\n"
        )
        self.assertEqual(find_yaml_nested_duplicates(text), [])

    def test_quoted_key_real_duplicate_detected(self):
        text = (
            "values:\n"
            '  "2026-12-31":\n'
            "    central: 65\n"
            '  "2026-12-31":\n'
            "    central: 66\n"
        )
        dups = find_yaml_nested_duplicates(text)
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["key"], "2026-12-31")

    def test_multiline_flow_skipped(self):
        text = (
            "horizons: [12,\n"
            "  20, 36]\n"
            "meta: {a: 1,\n"
            "  b: 2}\n"
            "after: ok\n"
        )
        self.assertEqual(find_yaml_nested_duplicates(text), [])

    def test_document_separator_resets_scopes(self):
        text = "a:\n  x: 1\n---\na:\n  x: 2\n"
        self.assertEqual(find_yaml_nested_duplicates(text), [])

    def test_non_string_input_safe(self):
        self.assertEqual(find_yaml_nested_duplicates(None), [])
        self.assertEqual(find_yaml_nested_duplicates(123), [])

    def test_check_yaml_duplicates_reports_nested_blocking(self):
        result = check_yaml_duplicates({
            "yaml_text": self.DOMRF_TEXT,
            "file": "weekly-review-stock.yaml",
        })
        self.assertFalse(result["valid"])
        self.assertEqual(result["blocking_count"], 1)
        self.assertEqual(result["duplicates"], [])  # top-level слой молчит
        self.assertEqual(len(result["nested_duplicates"]), 1)
        self.assertIn("per_stock.DOMRF", result["issues"][0]["actual"])

    def test_check_yaml_duplicates_no_double_report_top_level(self):
        """Top-level дубль репортится один раз (историческим guard'ом)."""
        result = check_yaml_duplicates({"yaml_text": "foo: 1\nfoo: 2\n"})
        self.assertEqual(result["blocking_count"], 1)
        self.assertEqual(len(result["duplicates"]), 1)
        self.assertEqual(result["nested_duplicates"], [])

    # ── Классы независимого аудита 2026-08-03 (FP-1..4 / FN-1..3) ──

    def test_audit_fp1_multiline_quoted_scalar_ok(self):
        """Многострочный quoted-скаляр с key-подобными продолжениями — не дубль."""
        for q in ('"', "'"):
            text = f'summary: {q}first line\n  second: part\n  second: part{q}\nafter: ok\n'
            self.assertEqual(find_yaml_nested_duplicates(text), [], q)

    def test_audit_fp2_block_scalar_as_list_item_ok(self):
        """`- |` / `- >-`: тело скаляра-элемента списка не сканируется как ключи."""
        for ind in ("|", ">-", "|2-"):
            text = f"notes:\n  - {ind}\n    key: 1\n    key: 2\nafter: ok\n"
            self.assertEqual(find_yaml_nested_duplicates(text), [], ind)

    def test_audit_fp3_top_guard_multidoc_reset(self):
        """`---` начинает новый документ — top-guard не считает это дублем."""
        self.assertEqual(find_yaml_top_level_duplicates("a: 1\n---\na: 2\n"), [])

    def test_audit_fn1_quoted_top_level_dup_blocking(self):
        """Quoted/не-strict top-level дубль виден nested-слоем (top-guard его чарсет не берёт)."""
        r = check_yaml_duplicates({"yaml_text": '"2026": 1\n"2026": 2\n'})
        self.assertEqual(r["blocking_count"], 1)
        # strict-ключ по-прежнему без двойного репорта
        r2 = check_yaml_duplicates({"yaml_text": "foo: 1\nfoo: 2\n"})
        self.assertEqual(r2["blocking_count"], 1)
        self.assertEqual(r2["nested_duplicates"], [])

    def test_audit_fn2_fake_flow_does_not_disarm(self):
        """Незакрытая '[' в прозе plain-скаляра — литерал: сканер НЕ слепнет до конца файла."""
        text = "note: score [1 of 3\nz:\n  k: 1\n  k: 2\n"
        self.assertEqual(len(find_yaml_nested_duplicates(text)), 1)
        text2 = "tags: [Ivan's, beta]\nz:\n  k: 1\n  k: 2\n"
        self.assertEqual(len(find_yaml_nested_duplicates(text2)), 1)

    def test_audit_fn3_inline_flow_mapping_dups(self):
        """Дубли внутри однострочных flow-коллекций (js-yaml падает и на них)."""
        self.assertEqual(len(find_yaml_nested_duplicates("meta: {a: 1, a: 2}\n")), 1)
        self.assertEqual(len(find_yaml_nested_duplicates("rows:\n  - {issue: x, issue: y}\n")), 1)
        # чистые формы и URL-значения не фонят
        self.assertEqual(find_yaml_nested_duplicates(
            "meta: {a: 1, b: 2}\nexpires: {type: date, value: x}\n"), [])
        self.assertEqual(find_yaml_nested_duplicates("meta: {url: http://x, a: 1}\n"), [])

    def test_mirror_agreement(self):
        """Зеркало yaml.compose: позитив подтверждается, негативы чистые."""
        try:
            import yaml as _yaml
        except ImportError:
            self.skipTest("PyYAML недоступен — зеркало пропущено (сканер stdlib-only)")

        def compose_has_dups(text):
            found = []
            for doc in _yaml.compose_all(text):
                def walk(node):
                    if isinstance(node, _yaml.MappingNode):
                        seen = set()
                        for k, v in node.value:
                            kk = getattr(k, "value", None)
                            if isinstance(kk, str):
                                if kk in seen:
                                    found.append(kk)
                                seen.add(kk)
                            walk(v)
                    elif isinstance(node, _yaml.SequenceNode):
                        for it in node.value:
                            walk(it)
                if doc is not None:
                    walk(doc)
            return found

        # позитив: DOMRF — оба слоя видят дубль
        self.assertEqual(compose_has_dups(self.DOMRF_TEXT), ["unconstrained_verdict"])
        self.assertEqual(len(find_yaml_nested_duplicates(self.DOMRF_TEXT)), 1)
        # негативы: оба слоя молчат
        negatives = [
            "conditions:\n  - id: a\n  - id: b\n",
            "a:\n  x: 1\nb:\n  x: 2\n",
            "basis: |\n  key: 1\n  key: 2\nnext: ok\n",
            'values:\n  "2026-12-31":\n    central: 65\n  "2027-12-31":\n    central: 60\n',
        ]
        for text in negatives:
            self.assertEqual(compose_has_dups(text), [], text)
            self.assertEqual(find_yaml_nested_duplicates(text), [], text)


# ---------------------------------------------------------------------------
# Шаг 8 цикла машиночитаемости — validate-decision, validate-report; команды гейтов удалены
# ---------------------------------------------------------------------------

_REPORT_FM = {
    "schema_version": "report@1", "title": "Разбор AAAA", "date": "2026-10-29", "kind": "single_analysis",
    "mode_codes": ["4a", "3"], "tickers": ["AAAA", "RU000A000AA0"], "recorded_at": "2026-10-29T17:40:00+03:00",
    "summary": "держать", "mode": "4 (single)", "recorded_at_estimated": True,   # открытые поля шапки допустимы
}
_DECISION = {
    "schema_version": "decision@1", "id": "2026-10-29T1740-AAAA", "key": "AAAA", "verdict": "HOLD",
    "target_pct": 4.5, "review_by": "2026-12-15", "note": "тезис жив", "conditions_created": [],
    "conditions_resolved": [], "source": {"kind": "report", "doc": "Portfolio/reports/r.md", "mode_codes": ["4a"],
                                          "stress_id": None},
    "author": "model", "recorded_at": "2026-10-29T17:40:00+03:00",
}


class TestValidateReport(unittest.TestCase):
    """validate-report: шапка report@1 (schema.md §4.3) и блок decisions: (поля модели §3.1) — блокирующий."""

    def _run(self, fm):
        from scripts.assemble_artifact import COMMANDS
        return COMMANDS["validate-report"](fm)

    def _fields(self, fm):
        return {i["field"] for i in self._run(fm)["issues"]}

    def test_valid_header(self):
        r = self._run(dict(_REPORT_FM))
        self.assertTrue(r["valid"], r)
        self.assertEqual(r["blocking_count"], 0)

    def test_required_fields(self):
        for f in ("schema_version", "title", "date", "kind", "mode_codes", "tickers", "recorded_at"):
            fm = dict(_REPORT_FM)
            fm.pop(f)
            r = self._run(fm)
            self.assertFalse(r["valid"], f)
            self.assertIn(f, {i["field"] for i in r["issues"]}, f)
            self.assertTrue(all(i["severity"] == "blocking" for i in r["issues"]))

    def test_codes(self):
        self.assertIn("kind", self._fields(dict(_REPORT_FM, kind="weekly")))
        self.assertIn("kind", self._fields(dict(_REPORT_FM, kind="stock_quality")))     # legacy kind
        self.assertIn("mode_codes[0]", self._fields(dict(_REPORT_FM, mode_codes=["4"])))  # legacy 4
        self.assertIn("mode_codes", self._fields(dict(_REPORT_FM, mode_codes=[])))
        self.assertIn("mode_codes", self._fields(dict(_REPORT_FM, mode_codes=["3", "3"])))
        self.assertIn("schema_version", self._fields(dict(_REPORT_FM, schema_version="report@2")))

    def test_tickers_and_times(self):
        self.assertTrue(self._run(dict(_REPORT_FM, tickers=[]))["valid"])                # макро-отчёт без бумаг
        self.assertIn("tickers[1]", self._fields(dict(_REPORT_FM, tickers=["AAAA", " "])))
        self.assertIn("tickers", self._fields(dict(_REPORT_FM, tickers="AAAA")))
        self.assertIn("recorded_at", self._fields(dict(_REPORT_FM, recorded_at="2026-10-29T17:40")))
        self.assertIn("recorded_at", self._fields(dict(_REPORT_FM, recorded_at="2026-10-29T14:40:00Z")))
        self.assertIn("date", self._fields(dict(_REPORT_FM, date="29.10.2026")))
        self.assertIn("title", self._fields(dict(_REPORT_FM, title="")))

    def test_yaml_date_objects_from_file(self):
        """--file отчёт.md читает шапку yaml.safe_load: неквотированные дата и время — объекты, не ошибка."""
        from datetime import date, datetime, timedelta, timezone
        fm = dict(_REPORT_FM, date=date(2026, 10, 29),
                  recorded_at=datetime(2026, 10, 29, 17, 40, tzinfo=timezone(timedelta(hours=3))))
        self.assertTrue(self._run(fm)["valid"])
        self.assertFalse(self._run(dict(fm, recorded_at=datetime(2026, 10, 29, 17, 40)))["valid"])  # без пояса

    def test_decisions_block(self):
        ok = [{"key": "AAAA", "verdict": "HOLD", "target_pct": 4.5, "review_by": "2026-12-15", "note": "тезис жив",
               "confidence": 0.7, "keep_open": ["c-1"]},
              {"key": "RU000A000AA0", "verdict": "HOLD_TO_MAT", "target_pct": None, "review_by": None, "note": "к погашению"}]
        self.assertTrue(self._run(dict(_REPORT_FM, decisions=ok))["valid"])
        bad = [
            ([dict(ok[0], verdict="RED_FLAG")], "decisions[0].verdict"),          # legacy-вердикт
            ([dict(ok[0], verdict="reviewed_keep")], "decisions[0].verdict"),     # статус гейта — не вердикт
            ([dict(ok[0], key="ZZZZ")], "decisions[0].key"),                      # нет в tickers[]
            ([ok[0], dict(ok[0])], "decisions[1].key"),                           # повтор ключа
            ([dict(ok[0], review_by="15.12.2026")], "decisions[0].review_by"),
            ([dict(ok[0], target_pct=150)], "decisions[0].target_pct"),
            ([dict(ok[0], note="x" * 201)], "decisions[0].note"),
            ([dict(ok[0], confidence=1.2)], "decisions[0].confidence"),
            ([dict(ok[0], keep_open="c-1")], "decisions[0].keep_open"),
            ([dict(ok[0], ticker_class="ipo")], "decisions[0].ticker_class"),      # поле не из блока
            ([{k: v for k, v in ok[0].items() if k != "target_pct"}], "decisions[0].target_pct"),
            ([], "decisions"),
        ]
        for block, field in bad:
            self.assertIn(field, self._fields(dict(_REPORT_FM, decisions=block)), (block, field))

    def test_file_input(self):
        """CLI: validate-report --file отчёт.md (шапка из frontmatter)."""
        import json, subprocess, sys, tempfile
        from pathlib import Path
        script = Path(__file__).parent.parent / "scripts" / "assemble_artifact.py"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.md"
            p.write_text("---\nschema_version: report@1\ntitle: T\ndate: 2026-10-29\nkind: general\n"
                         "mode_codes: [\"free\"]\ntickers: []\nrecorded_at: 2026-10-29T17:40:00+03:00\n---\n# T\n",
                         encoding="utf-8")
            r = subprocess.run([sys.executable, str(script), "validate-report", "--file", str(p)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(json.loads(r.stdout)["valid"], r.stdout)


class TestValidateDecision(unittest.TestCase):
    """validate-decision — обёртка над ds_schemas.validate_decision (schema.md §3.1)."""

    def _run(self, d):
        from scripts.assemble_artifact import COMMANDS
        return COMMANDS["validate-decision"](d)

    def test_valid(self):
        r = self._run(dict(_DECISION))
        self.assertTrue(r["valid"], r)

    def test_same_errors_as_ds_schemas(self):
        import ds_schemas
        bad = dict(_DECISION, verdict="HOLD_ADD", review_by="2026-11-01", gate={"status": "reviewed_keep"})
        r = self._run(bad)
        self.assertFalse(r["valid"])
        self.assertEqual(r["blocking_count"], len(ds_schemas.validate_decision(bad)))
        fields = {i["field"] for i in r["issues"]}
        self.assertTrue({"verdict", "review_by", "gate"} <= fields, fields)


class TestGateCommandsRemoved(unittest.TestCase):
    """Файл гейтов упразднён (schema.md §4.4): команд гейтов в диспетчере нет, скриптов в скилле нет."""

    def test_commands_absent(self):
        from scripts.assemble_artifact import COMMANDS
        for c in ("validate-gate-directive", "apply-gate-directive", "auto-maintain-gate-reviews"):
            self.assertNotIn(c, COMMANDS)
        self.assertIn("validate-decision", COMMANDS)
        self.assertIn("validate-report", COMMANDS)

    def test_scripts_absent(self):
        from pathlib import Path
        sd = Path(__file__).parent.parent / "scripts"
        for name in ("apply_gate_review.py", "auto_maintain_gate_reviews.py"):
            self.assertFalse((sd / name).exists(), name)
        src = (sd / "assemble_artifact.py").read_text(encoding="utf-8")
        self.assertNotIn("apply_gate_review", src)
        self.assertNotIn("auto_maintain_gate_reviews", src)


# ---------------------------------------------------------------------------
# TestValidateRetroAuditPaths — Workflow D pre-emit guard
# ---------------------------------------------------------------------------

class TestValidateRetroAuditPaths(unittest.TestCase):
    """Workflow D — pre-emit guard для атомарного retro-audit save."""

    def _ok_pair(self):
        return {
            "report_path": "reports/2026-05-15-zhirinovsky-1991-2022.md",
            "profile_path": "domains/geopolitics/zhirinovsky-1991-2022.md",
            "source_slug": "zhirinovsky",
            "period": "1991-2022",
            "audit_date": "2026-05-15",
        }

    def _validate(self, payload):
        from scripts.assemble_artifact import validate_retro_audit_paths
        return validate_retro_audit_paths(payload)

    # --- Happy paths -------------------------------------------------------

    def test_valid_pair_passes(self):
        r = self._validate(self._ok_pair())
        self.assertTrue(r["valid"])
        self.assertEqual(r["blocking_count"], 0)

    def test_valid_docx_report(self):
        p = self._ok_pair()
        p["report_path"] = "reports/2026-05-15-zhirinovsky-1991-2022.docx"
        r = self._validate(p)
        self.assertTrue(r["valid"])

    def test_only_report_no_profile_ok(self):
        p = self._ok_pair()
        del p["profile_path"]
        p["only"] = "report"
        r = self._validate(p)
        self.assertTrue(r["valid"])

    def test_only_profile_no_report_ok(self):
        p = self._ok_pair()
        del p["report_path"]
        p["only"] = "profile"
        r = self._validate(p)
        self.assertTrue(r["valid"])

    def test_single_year_period_ok(self):
        p = self._ok_pair()
        p["period"] = "2024"
        p["report_path"] = "reports/2026-05-15-zhirinovsky-2024.md"
        p["profile_path"] = "domains/geopolitics/zhirinovsky-2024.md"
        r = self._validate(p)
        self.assertTrue(r["valid"])

    # --- Forbidden destinations -------------------------------------------

    def test_blocks_deprecated_audits_dir(self):
        p = self._ok_pair()
        p["report_path"] = "audits/2026-05-15-zhirinovsky-1991-2022.md"
        r = self._validate(p)
        self.assertFalse(r["valid"])
        self.assertTrue(any("audits/" in i["expected"] for i in _b(r)))

    def test_blocks_deprecated_underscore_audits_dir(self):
        p = self._ok_pair()
        p["profile_path"] = "_audits/zhirinovsky-1991-2022.md"
        r = self._validate(p)
        self.assertFalse(r["valid"])

    # --- MCP dup markers --------------------------------------------------

    def test_blocks_mcp_dup_marker_in_report(self):
        p = self._ok_pair()
        p["report_path"] = "reports/2026-05-15-zhirinovsky-1991-2022 (1).md"
        r = self._validate(p)
        self.assertFalse(r["valid"])

    def test_blocks_space_in_filename(self):
        p = self._ok_pair()
        p["profile_path"] = "domains/geopolitics/zhirinovsky 1991-2022.md"
        r = self._validate(p)
        self.assertFalse(r["valid"])

    # --- -audit suffix in profile -----------------------------------------

    def test_blocks_audit_suffix_in_profile(self):
        p = self._ok_pair()
        p["profile_path"] = "domains/geopolitics/zhirinovsky-1991-2022-audit.md"
        r = self._validate(p)
        self.assertFalse(r["valid"])
        self.assertTrue(any("-audit" in i["expected"] for i in _b(r)))

    # --- Path shape -------------------------------------------------------

    def test_blocks_report_not_in_reports_dir(self):
        p = self._ok_pair()
        p["report_path"] = "weekly-reviews/2026-05-15-zhirinovsky-1991-2022.md"
        r = self._validate(p)
        self.assertFalse(r["valid"])

    def test_blocks_profile_not_in_domains(self):
        p = self._ok_pair()
        p["profile_path"] = "geopolitics/zhirinovsky-1991-2022.md"
        r = self._validate(p)
        self.assertFalse(r["valid"])

    def test_blocks_wrong_extension(self):
        p = self._ok_pair()
        p["report_path"] = "reports/2026-05-15-zhirinovsky-1991-2022.txt"
        r = self._validate(p)
        self.assertFalse(r["valid"])

    def test_blocks_mismatched_stem_report(self):
        p = self._ok_pair()
        p["report_path"] = "reports/2026-05-15-wrong-slug-1991-2022.md"
        r = self._validate(p)
        self.assertFalse(r["valid"])

    def test_blocks_mismatched_stem_profile(self):
        p = self._ok_pair()
        p["profile_path"] = "domains/geopolitics/wrong-slug-1991-2022.md"
        r = self._validate(p)
        self.assertFalse(r["valid"])

    # --- Missing fields ---------------------------------------------------

    def test_blocks_missing_report_when_not_only(self):
        p = self._ok_pair()
        del p["report_path"]
        r = self._validate(p)
        self.assertFalse(r["valid"])
        self.assertIn("report_path", _b_fields(r))

    def test_blocks_missing_profile_when_not_only(self):
        p = self._ok_pair()
        del p["profile_path"]
        r = self._validate(p)
        self.assertFalse(r["valid"])
        self.assertIn("profile_path", _b_fields(r))

    def test_blocks_missing_source_slug(self):
        p = self._ok_pair()
        del p["source_slug"]
        r = self._validate(p)
        self.assertFalse(r["valid"])
        self.assertIn("source_slug", _b_fields(r))

    def test_blocks_bad_period_format(self):
        p = self._ok_pair()
        p["period"] = "1991/2022"
        r = self._validate(p)
        self.assertFalse(r["valid"])

    def test_blocks_bad_audit_date(self):
        p = self._ok_pair()
        p["audit_date"] = "May 15 2026"
        r = self._validate(p)
        self.assertFalse(r["valid"])

    def test_blocks_uppercase_slug(self):
        p = self._ok_pair()
        p["source_slug"] = "Zhirinovsky"
        p["report_path"] = "reports/2026-05-15-Zhirinovsky-1991-2022.md"
        p["profile_path"] = "domains/geopolitics/Zhirinovsky-1991-2022.md"
        r = self._validate(p)
        self.assertFalse(r["valid"])

    def test_blocks_invalid_only_value(self):
        p = self._ok_pair()
        p["only"] = "both"
        r = self._validate(p)
        self.assertFalse(r["valid"])

    # --- Dispatch ---------------------------------------------------------

    def test_dispatch_registered(self):
        from scripts.assemble_artifact import COMMANDS
        self.assertIn("validate-retro-audit-paths", COMMANDS)


def _w_fields(result):
    return [i["field"] for i in _w(result)]


# ---------------------------------------------------------------------------
# Part C — verification_priority derived (stale → warning)
# ---------------------------------------------------------------------------

class TestPriorityCheckPartC(unittest.TestCase):
    def _review(self, prio, ctx, ticker="MBNK", **over):
        d = _v2_stock_review()
        e = _ok_per_stock_entry()
        e["catalyst"] = [_v2_catalyst()]
        e["advisor_verdict"] = "HOLD"
        e["verification_priority"] = prio
        e.update(over)
        d["per_stock"] = {ticker: e}
        if ctx is not None:
            d["_priority_context"] = {ticker: ctx}
        return d

    def test_stale_high_blocks(self):
        # R28: HOLD, conf 0.7, gate reviewed_keep, нет условий → движок LOW; записан HIGH → BLOCKING (с контекстом)
        d = self._review("HIGH", {"gate_status": "reviewed_keep"},
                         advisor_verdict_confidence=0.7, unconstrained_verdict="HOLD")
        r = validate_weekly_review_stock_detailed(d)
        self.assertFalse(r["valid"])
        self.assertIn("per_stock.MBNK.verification_priority", _b_fields(r))

    def test_null_with_context_blocks_without_context_warns(self):
        # R28: пустой приоритет — штамп не запускали: с --root блок, без — предупреждение «контекст не передан»
        d = self._review(None, {"gate_status": "reviewed_keep"}, advisor_verdict_confidence=0.7)
        self.assertIn("per_stock.MBNK.verification_priority", _b_fields(validate_weekly_review_stock_detailed(d)))
        r = validate_weekly_review_stock_detailed(self._review(None, None, advisor_verdict_confidence=0.7))
        self.assertTrue(r["valid"], _b(r))
        w = [i for i in _w(r) if i["field"] == "per_stock.*.verification_priority"]
        self.assertTrue(w and "контекст не передан" in w[0]["actual"], _w(r))

    def test_review_aging_high_under_review_not(self):
        # R28: «срок решения вышел» — нужен разбор → HIGH; «наблюдать» без условия и при уверенности 0,7 → LOW
        ok = self._review("HIGH", {"gate_status": "review_aging"}, advisor_verdict_confidence=0.7)
        self.assertNotIn("per_stock.MBNK.verification_priority", _b_fields(validate_weekly_review_stock_detailed(ok)))
        bad = self._review("HIGH", {"gate_status": "reviewed_under_review"}, advisor_verdict_confidence=0.7)
        self.assertIn("per_stock.MBNK.verification_priority", _b_fields(validate_weekly_review_stock_detailed(bad)))

    def test_gate_copy_warns_old_review_valid(self):
        # R28: копия gate_status_snapshot — предупреждение «устаревшая копия», обзор валиден
        d = self._review("LOW", None, advisor_verdict_confidence=0.7,
                         gate_status_snapshot={"status": "new_position", "as_of": "2026-08-06"})
        r = validate_weekly_review_stock_detailed(d)
        self.assertTrue(r["valid"], _b(r))
        self.assertIn("per_stock.*.gate_status_snapshot", _w_fields(r))

    def test_bond_priority_checked(self):
        # R28: облигации — та же сверка (гейта у облигаций нет: только вердикт, уверенность, условия)
        d = _v2_bond_review()
        isin = next(iter(d["per_bond"]))
        d["per_bond"][isin].update(advisor_verdict="HOLD_TO_MAT", advisor_verdict_confidence=0.8,
                                   verification_priority="HIGH")
        d["_priority_context"] = {isin: {"gate_status": None, "active_condition_verdicts": []}}
        self.assertIn(f"per_bond.{isin}.verification_priority", _b_fields(validate_weekly_review_bond_detailed(d)))
        d["per_bond"][isin]["verification_priority"] = "LOW"
        self.assertNotIn(f"per_bond.{isin}.verification_priority", _b_fields(validate_weekly_review_bond_detailed(d)))

    def test_high_justified_by_gate_no_warning(self):
        d = self._review("HIGH", {"gate_status": "review_needed"}, advisor_verdict_confidence=0.7)
        r = validate_weekly_review_stock_detailed(d)
        self.assertNotIn("per_stock.MBNK.verification_priority", _w_fields(r))

    def test_condition_medium_no_warning(self):
        # Отложенное действие (условие TRIM) → MEDIUM; stored MEDIUM → нет warning
        d = self._review("MEDIUM", {"gate_status": "reviewed_keep", "active_condition_verdicts": ["TRIM"]},
                         advisor_verdict_confidence=0.7)
        r = validate_weekly_review_stock_detailed(d)
        self.assertNotIn("per_stock.MBNK.verification_priority", _w_fields(r))

    def test_condition_high_blocks(self):
        # Отложенное действие → MEDIUM; stored HIGH → blocking (HIGH «залит»; приоритет ставит штамп)
        d = self._review("HIGH", {"gate_status": "reviewed_keep", "active_condition_verdicts": ["TRIM"]},
                         advisor_verdict_confidence=0.7)
        r = validate_weekly_review_stock_detailed(d)
        self.assertIn("per_stock.MBNK.verification_priority", _b_fields(r))

    def test_no_context_no_check(self):
        # Без _priority_context — проверка не запускается (нет данных о gate/условиях)
        d = self._review("HIGH", None, advisor_verdict_confidence=0.7, unconstrained_verdict="HOLD")
        r = validate_weekly_review_stock_detailed(d)
        self.assertNotIn("per_stock.MBNK.verification_priority", _w_fields(r))

    def test_correct_medium_no_warning(self):
        d = self._review("MEDIUM", {"gate_status": "reviewed_keep"},
                         advisor_verdict_confidence=0.55, unconstrained_verdict="HOLD")
        r = validate_weekly_review_stock_detailed(d)
        self.assertNotIn("per_stock.MBNK.verification_priority", _w_fields(r))


class TestStampWeekly(unittest.TestCase):
    """R28 (03.11): stamp-report обзора недели — recorded_at и verification_priority функцией движка, построчно."""
    NOW = "2026-11-03T12:00:00+03:00"
    DOC = "Portfolio/weekly-reviews/weekly-review-stock-2026-11-03.yaml"

    def setUp(self):
        import json
        import shutil
        import tempfile
        import yaml
        self.root = tempfile.mkdtemp(prefix="stamp-weekly-")
        self.addCleanup(shutil.rmtree, self.root, True)
        for d in ("weekly-reviews", "decisions"):
            os.makedirs(os.path.join(self.root, "Portfolio", d))
        # решение HOLD со сроком в прошлом → гейт «срок решения вышел» → HIGH
        dec = {"schema_version": "decision@1", "id": "2026-08-01T1000-AGED", "key": "AGED", "verdict": "HOLD",
               "target_pct": 2.0, "review_by": "2026-10-01", "note": "держим", "confidence": 0.7,
               "conditions_created": [], "conditions_resolved": [],
               "source": {"kind": "report", "doc": "Portfolio/reports/x.md", "mode_codes": ["4a"], "stress_id": None},
               "author": "model", "recorded_at": "2026-08-01T10:00:00+03:00"}
        with open(os.path.join(self.root, "Portfolio", "decisions", "2026-08-01T1000-AGED.json"), "w") as f:
            json.dump(dec, f)
        d = _v2_stock_review()
        d["review_date"] = "2026-11-03"
        base = copy.deepcopy(d["per_stock"]["SBER"])
        base.update(advisor_verdict="HOLD", advisor_verdict_confidence=0.7, unconstrained_verdict="HOLD")
        d["per_stock"] = {"SBER": dict(base, verification_priority="HIGH"),          # залитый HIGH → LOW
                          "GAZP": dict(base, advisor_verdict="TRIM", verification_priority=None),   # → HIGH
                          "AGED": dict(base, verification_priority=None),
                          "LAST": {k: v for k, v in base.items() if k != "verification_priority"}}   # поля нет
        self.text = "# стаб\n" + yaml.safe_dump(d, allow_unicode=True, sort_keys=False)
        self.path = os.path.join(self.root, *self.DOC.split("/"))
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(self.text)
        import scripts.assemble_artifact as AA
        self.AA = AA

    def stamp(self, doc=None):
        return self.AA.stamp_report(["--root", self.root, "--doc", doc or self.DOC, "--now", self.NOW])

    def test_stamps_priority_and_recorded_at(self):
        import yaml
        code, out = self.stamp()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["recorded_at"], self.NOW)
        self.assertEqual(out["priority"], {"SBER": "LOW", "GAZP": "HIGH", "AGED": "HIGH", "LAST": "LOW"})
        self.assertIn("SBER: HIGH → LOW", out["priority_changed"])
        self.assertIn("GAZP: — → HIGH", out["priority_changed"])
        with open(self.path, encoding="utf-8") as f:
            new = f.read()
        doc = yaml.safe_load(new)
        self.assertEqual({k: v["verification_priority"] for k, v in doc["per_stock"].items()}, out["priority"])
        self.assertEqual(doc["recorded_at"], self.NOW)
        self.assertTrue(new.startswith("# стаб\n"))                    # остальной текст не тронут
        # после штампа сверка с --root проходит; повторный штамп ничего не меняет
        doc_v = self.AA._load_doc(self.path)
        self.AA._priority_context_from_root(doc_v, self.root)
        r = validate_weekly_review_stock_detailed(doc_v)
        self.assertFalse([i for i in _b(r) if "verification_priority" in i["field"]], _b(r))
        code, out2 = self.stamp()
        self.assertEqual((code, out2["stamped"], out2["priority_changed"]), (0, [], []))

    def test_model_value_overwritten_mutant(self):
        # мутант «приоритет из обзора вместо штампа»: значение модели при сверке с --root — блок
        import yaml
        self.stamp()
        doc = yaml.safe_load(open(self.path, encoding="utf-8").read())
        doc["per_stock"]["SBER"]["verification_priority"] = "HIGH"
        self.AA._priority_context_from_root(doc, self.root)
        self.assertIn("per_stock.SBER.verification_priority", _b_fields(validate_weekly_review_stock_detailed(doc)))

    def test_bad_doc_rejected(self):
        code, out = self.stamp("Portfolio/weekly-reviews/other.yaml")
        self.assertEqual(code, 1)
        self.assertIn("weekly-review-", out["error"])


class TestObsoleteBlocksAndChecklist(unittest.TestCase):
    """03.11: упразднённые блоки старого формата (warning; written_back: true — blocking) и пункты проверки при
    «срочно» (HIGH без пунктов — blocking, MEDIUM — warning; HIGH от гейта «нужен разбор» — warning). Старые обзоры
    (review_date < 2026-10-31) — без замечаний."""

    def _stock(self, prio="LOW", checklist=None, verdict="HOLD", date="2026-11-03", **top):
        d = _v2_stock_review()
        d["review_date"] = date
        e = d["per_stock"]["SBER"]
        e.update(advisor_verdict=verdict, verification_priority=prio, verification_checklist=checklist or [])
        d.update(top)
        return d

    def _issue(self, r, field):
        return [i for i in r["issues"] if i["field"] == field]

    def test_obsolete_blocks(self):
        for k in ("conditions_evaluated", "gate_review_directives", "proposed_gate_review_directives",
                  "conditions_state", "conditions_mutations_applied"):
            r = validate_weekly_review_stock_detailed(self._stock(**{k: {}}))
            self.assertEqual([i["severity"] for i in self._issue(r, k)], ["warning"], k)
        r = validate_weekly_review_bond_detailed(dict(_v2_bond_review(), review_date="2026-11-03",
                                                      conditions_state=[]))
        self.assertEqual([i["severity"] for i in self._issue(r, "conditions_state")], ["warning"])
        r = validate_weekly_review_stock_detailed(self._stock(conditions_evaluated={"written_back": True}))
        self.assertIn("conditions_evaluated.written_back", _b_fields(r))
        self.assertIn("обзор не пишет состояние условий", self._issue(r, "conditions_evaluated.written_back")[0]["expected"])
        old = validate_weekly_review_stock_detailed(self._stock(date="2026-10-28", conditions_evaluated={"written_back": True}))
        self.assertFalse(self._issue(old, "conditions_evaluated") + self._issue(old, "conditions_evaluated.written_back"))

    def test_checklist_by_priority(self):
        f = "per_stock.SBER.verification_checklist"
        r = validate_weekly_review_stock_detailed(self._stock("HIGH", verdict="TRIM"))
        self.assertIn(f, _b_fields(r))
        r = validate_weekly_review_stock_detailed(self._stock("HIGH", ["МСФО 3К до 15.11: ЧП не ниже 50 млрд ₽"], verdict="TRIM"))
        self.assertFalse(self._issue(r, f))
        r = validate_weekly_review_stock_detailed(self._stock("MEDIUM"))
        self.assertEqual([i["severity"] for i in self._issue(r, f)], ["warning"])
        self.assertFalse(self._issue(validate_weekly_review_stock_detailed(self._stock("LOW")), f))
        self.assertFalse(self._issue(validate_weekly_review_stock_detailed(self._stock("HIGH", verdict="TRIM",
                                                                                         date="2026-10-28")), f))
        # облигации — так же
        b = dict(_v2_bond_review(), review_date="2026-11-03")
        e = next(iter(b["per_bond"].values()))
        e.update(advisor_verdict="SELL", verification_priority="HIGH", verification_checklist=[])
        self.assertTrue(any(x.endswith(".verification_checklist") for x in _b_fields(validate_weekly_review_bond_detailed(b))))

    def test_high_from_gate_is_review_warning(self):
        f = "per_stock.SBER.verification_checklist"
        d = self._stock("HIGH")
        d["_priority_context"] = {"SBER": {"gate_status": "review_aging", "active_condition_verdicts": []}}
        r = validate_weekly_review_stock_detailed(d)
        iss = self._issue(r, f)
        self.assertEqual([i["severity"] for i in iss], ["warning"])
        self.assertIn("«Разбери SBER»", iss[0]["expected"])
        # приоритет — после штампа (по движку): «докупать» при гейте — всё равно действие → blocking
        d = self._stock("HIGH", verdict="BUY")
        d["_priority_context"] = {"SBER": {"gate_status": "review_needed", "active_condition_verdicts": []}}
        self.assertIn(f, _b_fields(validate_weekly_review_stock_detailed(d)))


# ---------------------------------------------------------------------------
# TestStressBondCarry — Слой 2 total-return: блок bond_carry + baseline_spot
# ---------------------------------------------------------------------------

def _carry_block(matures_hk=None, ticker="SHORTB", kind="bond"):
    """Минимальный валидный bond_carry-блок под сценарии _v2_stress()."""
    cells = {sid: {"carry_pct": 2.0, "ci_pct": [1.8, 2.2],
                   "components": {"coupons": 2.0, "pull_to_par": 0.0,
                                  "fx_income": 0.0, "reinvest": 0.0}}
             for sid in ("Sc-A_bull", "Sc-B_base", "Sc-C_bear")}
    by_h = {}
    for hk in ("h12", "h20", "h36"):
        by_h[hk] = {
            "t_live_months": 9.0, "matures_within": (hk == matures_hk),
            "by_scenario": {k: dict(v) for k, v in cells.items()},
            "expected_carry_pct": 2.0, "flags": [],
        }
    return {
        "schema": "bond-carry@1",
        "as_of": "2026-05-06",
        "baseline_cbr_rate_pct": 14.25,
        "per_position": {ticker: {"kind": kind, "event_date": None,
                                  "by_horizon": by_h, "flags": []}},
        "caveats": [], "warnings": [],
    }


class TestStressBondCarry(unittest.TestCase):
    def _stress_with_bond(self, zeroed_h20=False):
        d = _v2_stress()
        deltas = {"Sc-A_bull": {"value": 1.0, "ci_pct": [0, 2]},
                  "Sc-B_base": {"value": 0.5, "ci_pct": [0, 1]},
                  "Sc-C_bear": {"value": -2.0, "ci_pct": [-3, -1]}}
        zero = {"value": 0.0, "ci_pct": [0.0, 0.0]}
        d["per_position"]["SHORTB"] = {"weight_pct": 15.0, "by_horizon": {
            "h12": {"delta_pct_by_scenario": {k: dict(v) for k, v in deltas.items()}},
            "h20": (
                {"delta_pct_by_scenario": {k: dict(zero) for k in deltas},
                 "price_delta_zeroed": "maturity_within_horizon", "t_live_months": 9.0}
                if zeroed_h20 else
                {"delta_pct_by_scenario": {k: dict(v) for k, v in deltas.items()}}
            ),
            "h36": {"delta_pct_by_scenario": {k: dict(zero) for k in deltas},
                    "price_delta_zeroed": "maturity_within_horizon",
                    "t_live_months": 9.0},
        }}
        d["per_position"]["SBER"]["weight_pct"] = 15.0  # покрытие в [98,102]
        return d

    def test_v2_without_baseline_spot_warns(self):
        r = validate_stress(_v2_stress())
        self.assertTrue(r["valid"])
        self.assertTrue(any(i["field"] == "baseline_spot" and i["severity"] == "warning"
                            for i in r["issues"]))

    def test_v2_with_baseline_spot_no_warning(self):
        d = _v2_stress()
        d["baseline_spot"] = {"brent_usd": 73.0, "usdrub": 78.27,
                              "cbr_rate_pct": 14.25}
        r = validate_stress(d)
        self.assertFalse(any(i["field"] == "baseline_spot" for i in r["issues"]))

    def test_valid_carry_with_maturity_guard_passes(self):
        d = self._stress_with_bond(zeroed_h20=True)
        d["bond_carry"] = _carry_block(matures_hk="h20")
        r = validate_stress(d)
        self.assertTrue(r["valid"], _b_fields(r))

    def test_matures_without_zeroed_price_blocks(self):
        """Тело в carry (matures_within) + живой price_delta = двойной счёт."""
        d = self._stress_with_bond(zeroed_h20=False)
        d["bond_carry"] = _carry_block(matures_hk="h20")
        r = validate_stress(d)
        self.assertFalse(r["valid"])
        self.assertTrue(any("per_position.SHORTB.by_horizon.h20" in f
                            for f in _b_fields(r)))

    def test_all_zero_deltas_without_flag_passes(self):
        """Дельты нулевые (без флага) — тела в цене нет, double-count не ложный."""
        d = self._stress_with_bond(zeroed_h20=False)
        for cell in d["per_position"]["SHORTB"]["by_horizon"]["h20"][
                "delta_pct_by_scenario"].values():
            cell["value"] = 0.0
        d["bond_carry"] = _carry_block(matures_hk="h20")
        self.assertTrue(validate_stress(d)["valid"])

    def test_carry_orphan_scenario_blocks(self):
        d = self._stress_with_bond(zeroed_h20=True)
        carry = _carry_block(matures_hk="h20")
        carry["per_position"]["SHORTB"]["by_horizon"]["h12"]["by_scenario"]["Sc-Z"] = {
            "carry_pct": 1.0}
        d["bond_carry"] = carry
        self.assertTrue(any("bond_carry.per_position.SHORTB.by_horizon.h12" in f
                            for f in _b_fields(validate_stress(d))))

    def test_carry_wrong_schema_blocks(self):
        d = self._stress_with_bond(zeroed_h20=True)
        carry = _carry_block(matures_hk="h20")
        carry["schema"] = "bond-carry@99"
        d["bond_carry"] = carry
        self.assertIn("bond_carry.schema", _b_fields(validate_stress(d)))

    def test_carry_empty_per_position_blocks(self):
        d = _v2_stress()
        d["bond_carry"] = {"schema": "bond-carry@1", "per_position": {}}
        self.assertIn("bond_carry.per_position", _b_fields(validate_stress(d)))

    def test_zeroed_price_without_carry_warns(self):
        """Maturity guard сработал, а carry-блока нет → доход бумаги потерян."""
        d = self._stress_with_bond(zeroed_h20=True)
        r = validate_stress(d)
        self.assertTrue(r["valid"])  # warning, не blocking (старый флоу)
        self.assertTrue(any(i["field"] == "bond_carry" and i["severity"] == "warning"
                            and "SHORTB" in str(i["actual"]) for i in r["issues"]))

    def test_cash_and_mm_kinds_skip_double_count(self):
        """CASH_RUB/money_market в carry не требуют price-слоя."""
        d = self._stress_with_bond(zeroed_h20=True)
        carry = _carry_block(matures_hk="h20")
        cash = _carry_block(ticker="CASH_RUB", kind="cash")["per_position"]["CASH_RUB"]
        cash["by_horizon"]["h20"]["matures_within"] = True  # даже с мусорным флагом
        carry["per_position"]["CASH_RUB"] = cash
        d["bond_carry"] = carry
        r = validate_stress(d)
        self.assertTrue(r["valid"], _b_fields(r))

    def test_stress_without_carry_untouched(self):
        """Артефакт без bond_carry — блок опционален: 0 blocking carry-issues.
        (V2-CUTOVER: фикстур v2; warning про отсутствующий baseline_spot —
        отдельное документированное поведение, не carry-блокировка.)"""
        r = validate_stress(TestValidateStress._ok(TestValidateStress()))
        self.assertTrue(r["valid"])
        self.assertFalse(any((i["field"].startswith("bond_carry")
                              or i["field"] == "baseline_spot")
                             and i["severity"] == "blocking" for i in r["issues"]))


# ---------------------------------------------------------------------------
# TestDividendForward — Слой 3 total-return: опциональный блок per_stock
# ---------------------------------------------------------------------------

class TestDividendForward(unittest.TestCase):
    def _df(self, **kw):
        base = {
            "policy_state": "declared",
            "year1_yield_pct": 11.0,
            "year2_yield_pct": 10.0,
            "year2_basis": "analyst",
            "source": "решение СД 2026-06-20",
            "as_of": "2026-07-01",
            "confidence": "HIGH",
            "note": "2026 declared 11% (СД), 2027 expected ~10% (аналитик)",
        }
        base.update(kw)
        return base

    def _review(self, df):
        d = _v2_stock_review()
        if df is not None:
            d["per_stock"]["SBER"]["dividend_forward"] = df
        return d

    def _issues_for(self, df):
        r = validate_weekly_review_stock_detailed(self._review(df))
        return r, [i for i in r["issues"] if "dividend_forward" in i["field"]]

    def test_absent_block_valid(self):
        """Back-compat: блока нет → валидно, ни одного div-issue."""
        r, div = self._issues_for(None)
        self.assertTrue(r["valid"])
        self.assertEqual(div, [])

    def test_valid_declared_passes(self):
        r, div = self._issues_for(self._df())
        self.assertTrue(r["valid"], _b_fields(r))
        self.assertEqual([i for i in div if i["severity"] == "blocking"], [])

    def test_bad_policy_state_blocks(self):
        r, _ = self._issues_for(self._df(policy_state="maybe"))
        self.assertIn("per_stock.SBER.dividend_forward.policy_state", _b_fields(r))

    def test_declared_without_year1_blocks(self):
        df = self._df()
        del df["year1_yield_pct"]
        r, _ = self._issues_for(df)
        self.assertIn("per_stock.SBER.dividend_forward.year1_yield_pct", _b_fields(r))

    def test_year2_basis_enum_blocks(self):
        r, _ = self._issues_for(self._df(year2_basis="guess"))
        self.assertIn("per_stock.SBER.dividend_forward.year2_basis", _b_fields(r))

    def test_carry_forward_needs_year2_value(self):
        df = self._df(year2_basis="carry_forward", confidence="LOW")
        del df["year2_yield_pct"]
        r, _ = self._issues_for(df)
        self.assertIn("per_stock.SBER.dividend_forward.year2_yield_pct", _b_fields(r))

    def test_carry_forward_high_confidence_warns(self):
        df = self._df(year2_basis="carry_forward", confidence="HIGH")
        r, div = self._issues_for(df)
        self.assertTrue(r["valid"])
        self.assertTrue(any(i["severity"] == "warning" and "confidence" in i["field"]
                            for i in div))

    def test_suspended_with_yield_blocks(self):
        """Гейт: suspended/none/uncertain «не оживают» — ненулевой yield запрещён."""
        for ps in ("suspended", "none", "uncertain"):
            df = {"policy_state": ps, "year1_yield_pct": 8.0}
            r, _ = self._issues_for(df)
            self.assertIn("per_stock.SBER.dividend_forward.year1_yield_pct",
                          _b_fields(r), ps)

    def test_suspended_zero_or_absent_ok(self):
        for df in ({"policy_state": "suspended"},
                   {"policy_state": "none", "year1_yield_pct": 0}):
            r, div = self._issues_for(df)
            self.assertEqual([i for i in div if i["severity"] == "blocking"], [], df)

    def test_uncertain_without_note_warns(self):
        """uncertain без note — пропуск не читается как пропуск → warning."""
        r, div = self._issues_for({"policy_state": "uncertain"})
        self.assertTrue(r["valid"])
        self.assertTrue(any(i["field"].endswith(".note") and i["severity"] == "warning"
                            for i in div))

    def test_bad_as_of_format_blocks(self):
        r, _ = self._issues_for(self._df(as_of="июль 2026"))
        self.assertIn("per_stock.SBER.dividend_forward.as_of", _b_fields(r))

    def test_stale_as_of_warns(self):
        """as_of старше 8 недель от review_date → warning stale."""
        r, div = self._issues_for(self._df(as_of="2026-01-10"))
        self.assertTrue(r["valid"])
        self.assertTrue(any(i["field"].endswith(".as_of") and i["severity"] == "warning"
                            and "stale" in str(i["actual"]) for i in div))

    def test_leftover_todo_blocks_even_when_suspended(self):
        """Незаменённый TODO_LLM в любом поле блока → blocking (не проскочит
        через non-contributing ветку)."""
        df = {"policy_state": "suspended",
              "year1_yield_pct": "TODO_LLM_float_or_remove_if_not_declared_expected"}
        r, _ = self._issues_for(df)
        self.assertIn("per_stock.SBER.dividend_forward.year1_yield_pct", _b_fields(r))

    def test_todo_block_blocks(self):
        r, _ = self._issues_for("TODO_LLM_block")
        self.assertIn("per_stock.SBER.dividend_forward", _b_fields(r))


# ---------------------------------------------------------------------------
# TestValidateIntegratedView — Workflow G, контракт стабильности графиков @1.3
# ---------------------------------------------------------------------------

def _iv_metric(v, lo, hi):
    return {"value": v, "ci": [lo, hi]}


def _iv_fm():
    """Валидный frontmatter integrated-view@1.3 (минимум для контракта)."""
    hz = {}
    for k, end in (("6", "2026-12-31"), ("12", "2027-06-30"), ("24", "2028-06-30")):
        hz[k] = {"end": end,
                 "equity": _iv_metric(13.6, 9.6, 18.6),
                 "bond": _iv_metric(31.2, 24.4, 38.9),
                 "spread": _iv_metric(-17.6, -24.7, -9.5)}
    return {
        "schema_version": "integrated-view@1.3",
        "view_date": "2026-07-02",
        "horizons": [6, 12, 24],
        "horizon_ends": {"h6": "2026-12-31", "h12": "2027-06-30", "h24": "2028-06-30"},
        "primary_horizon": 12,
        "horizon_mode": "rolling",
        "ci_method": "mc",
        "inputs": {"snapshot_age_days": 0, "stress_age_days": 0, "review_age_days": 0},
        "tail_flags": {"fired": False, "flags": []},
        "portfolio_by_horizon": {"primary_horizon": 12, "ci_method": "mc",
                                 "horizons": hz},
        "total_return": {"horizons": {
            k: {"expected": {"portfolio": 35.2, "equity": 18.6, "bond": 55.2,
                             "cash": 20.5},
                "layers": {"equity": {"price": 5.7, "dividend": 13.6, "idio": 2.6},
                           "bond": {"price": 25.5, "carry": 29.7, "idio": 3.9}}}
            for k in ("6", "12", "24")}},
    }


class TestValidateIntegratedView(unittest.TestCase):
    def test_valid_passes_clean(self):
        r = validate_integrated_view(_iv_fm())
        self.assertTrue(r["valid"], _b_fields(r))
        self.assertEqual(r["blocking_count"], 0)
        self.assertEqual(r["warning_count"], 0)

    def test_legacy_12_warns_not_blocks(self):
        r = validate_integrated_view({"schema_version": "integrated-view@1.2"})
        self.assertTrue(r["valid"])
        self.assertTrue(any(i["severity"] == "warning" for i in r["issues"]))

    def test_bad_schema_version_blocks(self):
        self.assertFalse(validate_integrated_view({"schema_version": "1.3"})["valid"])
        self.assertFalse(validate_integrated_view({})["valid"])

    def test_missing_pbh_blocks(self):
        d = _iv_fm(); del d["portfolio_by_horizon"]
        self.assertIn("portfolio_by_horizon", _b_fields(validate_integrated_view(d)))

    def test_llm_formatted_string_blocks(self):
        """Ключевой кейс: LLM вывел «+13.6%» строкой вместо числа → блок."""
        d = _iv_fm()
        d["portfolio_by_horizon"]["horizons"]["12"]["equity"]["value"] = "+13.6%"
        r = validate_integrated_view(d)
        self.assertIn("portfolio_by_horizon.horizons.12.equity.value", _b_fields(r))

    def test_date_object_end_blocks(self):
        """Незакавыченная дата → PyYAML/js-yaml дают Date-объект → блок."""
        from datetime import date as _d
        d = _iv_fm()
        d["portfolio_by_horizon"]["horizons"]["12"]["end"] = _d(2027, 6, 30)
        self.assertIn("portfolio_by_horizon.horizons.12.end",
                      _b_fields(validate_integrated_view(d)))

    def test_horizon_keys_mismatch_blocks(self):
        d = _iv_fm()
        del d["portfolio_by_horizon"]["horizons"]["24"]
        self.assertIn("portfolio_by_horizon.horizons",
                      _b_fields(validate_integrated_view(d)))

    def test_primary_not_in_horizons_blocks(self):
        d = _iv_fm()
        d["portfolio_by_horizon"]["primary_horizon"] = 99
        self.assertIn("portfolio_by_horizon.primary_horizon",
                      _b_fields(validate_integrated_view(d)))

    def test_bad_ci_blocks(self):
        d = _iv_fm()
        d["portfolio_by_horizon"]["horizons"]["6"]["bond"]["ci"] = ["9.6", 18.6]
        self.assertIn("portfolio_by_horizon.horizons.6.bond.ci",
                      _b_fields(validate_integrated_view(d)))

    def test_total_return_string_layer_blocks(self):
        d = _iv_fm()
        d["total_return"]["horizons"]["24"]["layers"]["bond"]["carry"] = "≈29.7%"
        self.assertIn("total_return.horizons.24.layers.bond.carry",
                      _b_fields(validate_integrated_view(d)))

    def test_total_return_optional(self):
        d = _iv_fm(); del d["total_return"]
        self.assertTrue(validate_integrated_view(d)["valid"])

    def test_v1_horizon_fields_block(self):
        d = _iv_fm(); d["horizon_months"] = 20
        self.assertIn("horizon_months", _b_fields(validate_integrated_view(d)))

    def test_missing_tail_flags_and_ages_warn(self):
        d = _iv_fm(); del d["tail_flags"]; d["inputs"] = {}
        r = validate_integrated_view(d)
        self.assertTrue(r["valid"])
        wf = [i["field"] for i in r["issues"] if i["severity"] == "warning"]
        self.assertIn("tail_flags", wf)
        self.assertIn("inputs", wf)

    def test_real_emitter_output_passes(self):
        """Интеграционный: блоки из aggregate_positions.build_frontmatter_contract
        проходят валидатор без правок (contract round-trip)."""
        import sys as _sys
        _sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                         "portfolio-integrated-view", "scripts"))
        from aggregate_positions import build_frontmatter_contract
        pbh = {"h12": {"equity": {"expected_pct_horizon": {"value": 13.61, "ci": [9.62, 18.64]}},
                       "bond": {"expected_pct_horizon": {"value": 31.24, "ci": [24.4, 38.9]}},
                       "spread_pp_horizon": {"point": -17.63, "ci": [-24.7, -9.5]}}}
        fm_pbh, fm_tr = build_frontmatter_contract(
            pbh, {"h12": "2027-06-30"}, 12, "mc",
            {"by_horizon": {"h12": {
                "expected": {"portfolio": 35.24, "equity": 18.59, "bond": 55.24,
                             "cash": 20.54},
                "layers": {"bond": {"price": {"value": 25.5}, "income": {"value": 29.7},
                           "income_kind": "carry"}}}}, "note": "x"})
        d = _iv_fm()
        d["horizons"] = [12]
        d["horizon_ends"] = {"h12": "2027-06-30"}
        d["portfolio_by_horizon"] = fm_pbh
        d["total_return"] = fm_tr
        r = validate_integrated_view(d)
        self.assertTrue(r["valid"], _b_fields(r))


# ---------------------------------------------------------------------------
# TestOutcomeLogCalibration — §14 outcome_log / fca_stats (аддитивные блоки)
# ---------------------------------------------------------------------------

class TestOutcomeLogCalibration(unittest.TestCase):
    # --- freeze-outcome-log: заморозка stub из fca_stats ---

    def _fca_level(self):
        return {"kind": "level", "unit": "percent_annual", "l1_weighted": 13.0,
                "l1_unweighted": 13.25, "l2_ev": 13.03, "p10": 12.25, "p90": 13.25}

    def test_freeze_level_copies_fields(self):
        r = freeze_outcome_log({"fca_stats_entry": self._fca_level(),
                                "resolve_date": "2026-12-31", "logged_at": "2026-07-05",
                                "record_type": "horizon_resolve", "confidence_at_forecast": 0.40})
        e = r["entry"]
        self.assertEqual(r["blocking_count"], 0)
        self.assertEqual(e["forecast_l1_weighted"], 13.0)
        self.assertEqual(e["forecast_l1_unweighted"], 13.25)
        self.assertEqual(e["forecast_l2_ev"], 13.03)
        self.assertEqual(e["p10_p90"], [12.25, 13.25])
        self.assertIsNone(e["actual"])          # заполнит резолв
        self.assertIsNone(e["error_pct"])
        self.assertEqual(e["shock_flag"], "none")

    def test_freeze_level_missing_unweighted_is_warning_not_blocking(self):
        fca = self._fca_level()
        fca["l1_unweighted"] = None             # не персистилось до схемы
        r = freeze_outcome_log({"fca_stats_entry": fca, "resolve_date": "2026-12-31",
                                "logged_at": "2026-07-05", "record_type": "horizon_resolve",
                                "confidence_at_forecast": 0.40})
        self.assertEqual(r["blocking_count"], 0)
        self.assertIsNone(r["entry"]["forecast_l1_unweighted"])
        self.assertTrue(any("unweighted" in i["field"] and i["severity"] == "warning"
                            for i in r["issues"]))

    def test_freeze_level_missing_p10p90_becomes_null(self):
        fca = self._fca_level()
        fca["p10"], fca["p90"] = None, None
        r = freeze_outcome_log({"fca_stats_entry": fca, "resolve_date": "2026-12-31",
                                "logged_at": "2026-07-05", "record_type": "horizon_resolve",
                                "confidence_at_forecast": 0.40})
        self.assertIsNone(r["entry"]["p10_p90"])
        self.assertEqual(r["blocking_count"], 0)

    def test_freeze_event_stub_predicted_p_null_warns(self):
        r = freeze_outcome_log({"fca_stats_entry": {"kind": "event", "predicted_p": None},
                                "resolve_date": "2026-07-24", "logged_at": "2026-07-05",
                                "record_type": "horizon_resolve", "confidence_at_forecast": 0.40})
        self.assertEqual(r["entry"]["kind"], "event")
        self.assertIsNone(r["entry"]["resolved"])
        self.assertEqual(r["blocking_count"], 0)          # stub — не блок
        self.assertTrue(any("predicted_p" in i["field"] and i["severity"] == "warning"
                            for i in r["issues"]))

    def test_freeze_event_with_predicted_p(self):
        r = freeze_outcome_log({"fca_stats_entry": {"kind": "event", "predicted_p": 0.6},
                                "resolve_date": "2026-07-24", "logged_at": "2026-07-05",
                                "record_type": "horizon_resolve", "confidence_at_forecast": 0.40})
        self.assertEqual(r["entry"]["predicted_p"], 0.6)
        self.assertEqual(r["blocking_count"], 0)

    def test_freeze_unknown_kind_blocks(self):
        r = freeze_outcome_log({"fca_stats_entry": {"kind": "banana"},
                                "resolve_date": "2026-07-24", "logged_at": "2026-07-05",
                                "record_type": "horizon_resolve"})
        self.assertGreater(r["blocking_count"], 0)

    # --- complete-outcome-log: детерминированная арифметика ---

    def _resolved_level(self, actual):
        return {"entry": {"resolve_date": "2026-12-31", "logged_at": "2026-12-31",
                          "record_type": "horizon_resolve", "kind": "level",
                          "forecast_l1_weighted": 13.0, "forecast_l1_unweighted": 13.25,
                          "forecast_l2_ev": 13.03, "p10_p90": [12.25, 13.25],
                          "confidence_at_forecast": 0.40, "actual": actual,
                          "actual_source": "https://cbr.ru", "shock_flag": "none"}}

    def test_complete_level_error_pct(self):
        r = complete_outcome_log(self._resolved_level(13.5))
        # (13.5 − 13.0)/13.0 × 100 = 3.8462
        self.assertAlmostEqual(r["entry"]["error_pct"], 3.8462, places=3)
        self.assertEqual(r["blocking_count"], 0)

    def test_complete_level_in_p10p90_false(self):
        r = complete_outcome_log(self._resolved_level(13.5))     # 13.5 > 13.25
        self.assertFalse(r["entry"]["in_p10_p90"])

    def test_complete_level_in_p10p90_true(self):
        r = complete_outcome_log(self._resolved_level(12.9))     # 12.25 ≤ 12.9 ≤ 13.25
        self.assertTrue(r["entry"]["in_p10_p90"])
        self.assertAlmostEqual(r["entry"]["error_pct"], -0.7692, places=3)

    def test_complete_level_no_actual_warns(self):
        d = self._resolved_level(None)
        r = complete_outcome_log(d)
        self.assertTrue(any(i["field"] == "entry.actual" and i["severity"] == "warning"
                            for i in r["issues"]))

    def test_complete_event_resolve_without_p_blocks(self):
        r = complete_outcome_log({"entry": {"resolve_date": "2026-07-24", "logged_at": "2026-07-24",
                                            "record_type": "horizon_resolve", "kind": "event",
                                            "predicted_p": None, "resolved": 1,
                                            "confidence_at_forecast": 0.40,
                                            "actual_source": "https://cbr.ru", "shock_flag": "none"}})
        self.assertGreater(r["blocking_count"], 0)
        # ровно один blocking на predicted_p (без дублей)
        self.assertEqual(sum(1 for i in r["issues"]
                             if i["field"] == "entry.predicted_p" and i["severity"] == "blocking"), 1)

    def test_complete_level_actual_without_frozen_forecast_refuses(self):
        # interim_supersession с forecast_l1_weighted=null (кейс замены cnyrub-rate-2026-09-17): помощник
        # отказывает blocking'ом и обнуляет факт — не отдаёт запись, которую валидатор потом заблокирует
        d = self._resolved_level(86.4)
        d["entry"].update(record_type="interim_supersession", forecast_l1_weighted=None,
                          error_pct=1.5, in_p10_p90=True)
        r = complete_outcome_log(d)
        self.assertGreater(r["blocking_count"], 0)
        b = [i for i in r["issues"] if i["severity"] == "blocking"]
        self.assertEqual([i["field"] for i in b], ["entry.forecast_l1_weighted"])
        self.assertIn("actual оставлен null", str(b[0]["expected"]))
        self.assertIsNone(r["entry"]["actual"])
        self.assertIsNone(r["entry"]["error_pct"])
        self.assertIsNone(r["entry"]["in_p10_p90"])
        # обнулённая запись — валидный stub: validate-forecast-events её не блокирует
        v = validate_forecast_events({"isolated": True, "isolated_reason": "Type 1", "outcome_log": [r["entry"]]})
        self.assertTrue(v["valid"], _b_fields(v))

    def test_complete_level_actual_with_non_numeric_forecast_refuses(self):
        d = self._resolved_level(86.4)
        d["entry"]["forecast_l1_weighted"] = "TODO"
        r = complete_outcome_log(d)
        self.assertTrue(any(i["field"] == "entry.forecast_l1_weighted" and i["severity"] == "blocking"
                            for i in r["issues"]))
        self.assertIsNone(r["entry"]["actual"])

    def test_complete_event_resolve_without_p_nulls_resolved(self):
        r = complete_outcome_log({"entry": {"resolve_date": "2026-07-24", "logged_at": "2026-07-24",
                                            "record_type": "interim_supersession", "kind": "event",
                                            "predicted_p": None, "resolved": 1,
                                            "confidence_at_forecast": 0.40,
                                            "actual_source": "https://cbr.ru", "shock_flag": "none"}})
        self.assertGreater(r["blocking_count"], 0)
        self.assertIsNone(r["entry"]["resolved"])

    def test_complete_event_resolve_with_p_ok(self):
        r = complete_outcome_log({"entry": {"resolve_date": "2026-07-24", "logged_at": "2026-07-24",
                                            "record_type": "horizon_resolve", "kind": "event",
                                            "predicted_p": 0.6, "resolved": 1,
                                            "confidence_at_forecast": 0.40,
                                            "actual_source": "https://cbr.ru", "shock_flag": "none"}})
        self.assertEqual(r["blocking_count"], 0)

    # --- validate-forecast-events: интеграция + backward-compat ---

    def test_validate_events_backward_compat_no_blocks(self):
        # Type 1 без outcome_log/fca_stats — валиден как раньше.
        r = validate_forecast_events({"isolated": True, "isolated_reason": "binary event"})
        self.assertTrue(r["valid"])
        self.assertEqual(r["blocking_count"], 0)

    def test_validate_events_with_outcome_log_and_fca_stats(self):
        d = {"isolated": True, "isolated_reason": "binary",
             "fca_stats": {"2026-07-24": {"kind": "event", "predicted_p": 0.6}},
             "outcome_log": [{"resolve_date": "2026-07-24", "logged_at": "2026-07-05",
                              "record_type": "horizon_resolve", "kind": "event",
                              "predicted_p": 0.6, "resolved": None,
                              "confidence_at_forecast": 0.40, "actual_source": None,
                              "shock_flag": "none"}]}
        r = validate_forecast_events(d)
        self.assertTrue(r["valid"], _b_fields(r))

    def _closed_forecast(self, **over):
        # прогноз, закрытый фразой «Закрой прогноз …»: freeze → complete → resolved + final_audit
        frozen = freeze_outcome_log({
            "fca_stats_entry": {"kind": "level", "l1_weighted": 87.5, "l1_unweighted": 89.0,
                                "l2_ev": None, "p10": 85.0, "p90": 90.0},
            "resolve_date": "2026-09-01", "logged_at": "2026-10-29",
            "record_type": "horizon_resolve", "confidence_at_forecast": 0.40})["entry"]
        frozen["actual"] = 86.3793
        frozen["actual_source"] = "https://www.cbr.ru/currency_base/daily/"
        entry = complete_outcome_log({"entry": frozen})["entry"]
        d = {"status": "resolved", "isolated": True, "isolated_reason": "Type 1",
             "outcome_log": [entry],
             "final_audit": {"due": "2026-09-01", "status": "done", "completed": "2026-10-29",
                             "closed_by": "owner_close", "audit_file": None, "result": "hit"}}
        d.update(over)
        return d

    def test_close_forecast_new_format_valid(self):
        d = self._closed_forecast()
        self.assertEqual(d["outcome_log"][0]["in_p10_p90"], True)
        r = validate_forecast_events(d)
        self.assertTrue(r["valid"], _b_fields(r))
        self.assertEqual(_w_fields(r), [])

    def test_close_forecast_owner_close_without_outcome_blocks(self):
        # закрытие без ретро-аудита обязано нести исход; пустой actual — тоже без исхода
        self.assertEqual(_b_fields(validate_forecast_events(self._closed_forecast(outcome_log=None))),
                         ["outcome_log"])
        d = self._closed_forecast()
        d["outcome_log"][0]["actual"] = None
        self.assertIn("outcome_log", _b_fields(validate_forecast_events(d)))

    def test_close_forecast_resolved_other_paths_warn_only(self):
        # легаси ретро-аудита: resolved без исхода — warning; неизвестный closed_by — warning
        d = self._closed_forecast(outcome_log=None,
                                  final_audit={"due": "2026-09-01", "status": "done", "audit_file": "reports/x.md"})
        r = validate_forecast_events(d)
        self.assertTrue(r["valid"])
        self.assertEqual(_w_fields(r), ["outcome_log"])
        r2 = validate_forecast_events(self._closed_forecast(
            final_audit={"status": "done", "closed_by": "whim"}))
        self.assertIn("final_audit.closed_by", _w_fields(r2))

    def test_close_forecast_active_not_checked(self):
        r = validate_forecast_events({"status": "active", "isolated": True, "isolated_reason": "x"})
        self.assertEqual(_w_fields(r), [])

    def test_validate_events_outcome_log_bad_record_type_blocks(self):
        d = {"isolated": True, "isolated_reason": "x",
             "outcome_log": [{"resolve_date": "2026-12-31", "logged_at": "2026-07-05",
                              "record_type": "wrong", "kind": "level",
                              "forecast_l1_weighted": 13.0, "confidence_at_forecast": 0.4,
                              "shock_flag": "none"}]}
        r = validate_forecast_events(d)
        self.assertFalse(r["valid"])
        self.assertTrue(any("record_type" in f for f in _b_fields(r)))

    def test_validate_events_outcome_log_unknown_shock_flag_blocks(self):
        d = {"isolated": True, "isolated_reason": "x",
             "outcome_log": [{"resolve_date": "2026-12-31", "logged_at": "2026-07-05",
                              "record_type": "horizon_resolve", "kind": "level",
                              "forecast_l1_weighted": 13.0, "confidence_at_forecast": 0.4,
                              "shock_flag": "boom"}]}
        r = validate_forecast_events(d)
        self.assertTrue(any("shock_flag" in f for f in _b_fields(r)))

    def test_validate_events_level_resolved_without_l1_weighted_blocks(self):
        d = {"isolated": True, "isolated_reason": "x",
             "outcome_log": [{"resolve_date": "2026-12-31", "logged_at": "2026-12-31",
                              "record_type": "horizon_resolve", "kind": "level",
                              "forecast_l1_weighted": None, "actual": 13.5,
                              "confidence_at_forecast": 0.4, "shock_flag": "none"}]}
        r = validate_forecast_events(d)
        self.assertTrue(any("forecast_l1_weighted" in f for f in _b_fields(r)))

    def test_validate_events_outcome_log_not_list_blocks(self):
        d = {"isolated": True, "isolated_reason": "x", "outcome_log": {"bad": 1}}
        r = validate_forecast_events(d)
        self.assertTrue(any(f == "outcome_log" for f in _b_fields(r)))

    def test_validate_events_fca_stats_bad_p10p90_blocks(self):
        d = {"isolated": True, "isolated_reason": "x",
             "fca_stats": {"2026-12-31": {"kind": "level", "l1_weighted": 13.0,
                                          "p10": 14.0, "p90": 12.0}}}
        r = validate_forecast_events(d)
        self.assertTrue(any("p10/p90" in f for f in _b_fields(r)))

    def test_validate_events_fca_stats_predicted_p_out_of_range_blocks(self):
        d = {"isolated": True, "isolated_reason": "x",
             "fca_stats": {"2026-07-24": {"kind": "event", "predicted_p": 1.5}}}
        r = validate_forecast_events(d)
        self.assertTrue(any("predicted_p" in f for f in _b_fields(r)))

    def test_validate_events_level_with_event_only_field_warns(self):
        d = {"isolated": True, "isolated_reason": "x",
             "outcome_log": [{"resolve_date": "2026-12-31", "logged_at": "2026-07-05",
                              "record_type": "horizon_resolve", "kind": "level",
                              "forecast_l1_weighted": 13.0, "forecast_l1_unweighted": 13.25,
                              "forecast_l2_ev": 13.03, "p10_p90": [12.25, 13.25],
                              "confidence_at_forecast": 0.4, "predicted_p": 0.6,
                              "shock_flag": "none"}]}
        r = validate_forecast_events(d)
        self.assertTrue(r["valid"])                       # warning, не блок
        self.assertTrue(any(i["field"].endswith("predicted_p") and i["severity"] == "warning"
                            for i in r["issues"]))


# ---------------------------------------------------------------------------
# TestOneSidedCone — §15 F1 (fact_anchor / one_sided_cone / гейт / стороны)
# ---------------------------------------------------------------------------

class TestOneSidedCone(unittest.TestCase):
    def _bs(self, a, b, c, d, h="2026-12-31"):
        return {s: {"values": {h: {"central": v}}}
                for s, v in (("A", a), ("B", b), ("C", c), ("D", d))}

    # --- compute_cone: чистая арифметика ---

    def test_cbr_all_below_anchor_one_sided_down(self):
        bs = {"A": {"values": {"2026-12-31": {"central": 13.5}, "2027-06-30": {"central": 11.4}}},
              "B": {"values": {"2026-12-31": {"central": 13.0}, "2027-06-30": {"central": 11.0}}},
              "C": {"values": {"2026-12-31": {"central": 13.1}, "2027-06-30": {"central": 11.1}}},
              "D": {"values": {"2026-12-31": {"central": 12.5}, "2027-06-30": {"central": 10.6}}}}
        r = compute_cone(bs, 14.25)
        self.assertTrue(r["one_sided_cone"])
        self.assertEqual(r["cone_side"]["2026-12-31"], "down")
        self.assertEqual(r["cone_side"]["2027-06-30"], "down")
        self.assertEqual(sorted(r["horizons_flagged"]), ["2026-12-31", "2027-06-30"])

    def test_urals_two_sided_no_flag(self):
        r = compute_cone(self._bs(24, 14, 11, 7), 15)
        self.assertFalse(r["one_sided_cone"])
        self.assertEqual(r["cone_side"]["2026-12-31"], "two_sided")

    def test_urals_two_sided_robust_low_anchor(self):
        self.assertFalse(compute_cone(self._bs(24, 14, 11, 7), 12)["one_sided_cone"])

    def test_all_neutral_not_flagged(self):
        r = compute_cone(self._bs(15, 15, 15, 15), 15)
        self.assertFalse(r["one_sided_cone"])
        self.assertEqual(r["cone_side"]["2026-12-31"], "neutral")

    def test_eps_neutral_band_excludes_near_anchor(self):
        # A внутри eps (anchor 100, eps=0.5) → нейтрален; B/C/D ниже → one_sided down
        r = compute_cone(self._bs(100.3, 95, 94, 93), 100)
        self.assertTrue(r["one_sided_cone"])
        self.assertEqual(r["cone_side"]["2026-12-31"], "down")
        self.assertIn("A", r["neutral_worlds"]["2026-12-31"])

    def test_delta_format_anchor_zero(self):
        # macro-scenarios формат: значения уже дельты; anchor=0
        r = compute_cone(self._bs(-5, -3, -8, -2), 0)
        self.assertTrue(r["one_sided_cone"])
        self.assertEqual(r["cone_side"]["2026-12-31"], "down")

    def test_any_horizon_flags(self):
        bs = {"A": {"values": {"h1": {"central": 12}, "h2": {"central": 20}}},
              "B": {"values": {"h1": {"central": 11}, "h2": {"central": 8}}},
              "C": {"values": {"h1": {"central": 10}, "h2": {"central": 9}}},
              "D": {"values": {"h1": {"central": 9}, "h2": {"central": 7}}}}
        r = compute_cone(bs, 15)      # h1 all below → down; h2 straddles → two_sided
        self.assertTrue(r["one_sided_cone"])
        self.assertEqual(r["horizons_flagged"], ["h1"])
        self.assertEqual(r["cone_side"]["h2"], "two_sided")

    def test_per_horizon_anchor_map(self):
        bs = {"A": {"values": {"h1": {"central": 12}}}, "B": {"values": {"h1": {"central": 11}}},
              "C": {"values": {"h1": {"central": 10}}}, "D": {"values": {"h1": {"central": 9}}}}
        self.assertTrue(compute_cone(bs, {"h1": 15})["one_sided_cone"])
        self.assertFalse(compute_cone(bs, {"h1": 10})["one_sided_cone"])  # straddles

    def test_cli_bad_anchor_errors(self):
        self.assertIn("error", check_one_sided_cone({"anchor": "x", "by_scenario": {}}))

    # --- _validate_cone: гейт ---

    def _cond(self, bs, **extra):
        c = {"conditional_on_scenarios": {"by_scenario": bs, "unit": "%"}}
        c["conditional_on_scenarios"].update(extra)
        return c

    def test_gate_one_sided_no_reason_blocks(self):
        issues = []
        d = self._cond(self._bs(13.5, 13.0, 13.1, 12.5),
                       fact_anchor={"value": 14.25, "as_of": "2026-06-19", "source": "CBR"})
        _validate_cone(d, issues)
        blk = [i for i in issues if i["severity"] == "blocking"]
        self.assertTrue(any("counter_world_reason" in i["field"] for i in blk))
        # адрес горизонта в сообщении
        self.assertTrue(any("2026-12-31" in i["expected"] for i in blk))

    def test_gate_one_sided_with_reason_passes(self):
        issues = []
        d = self._cond(self._bs(13.5, 13.0, 13.1, 12.5),
                       fact_anchor={"value": 14.25, "as_of": "2026-06-19", "source": "CBR"},
                       counter_world_reason="Встречный мир девальвации в by_scenario не добавлен: обоснование ...")
        _validate_cone(d, issues)
        self.assertFalse([i for i in issues if i["severity"] == "blocking"])

    def test_gate_two_sided_no_block(self):
        issues = []
        d = self._cond(self._bs(24, 14, 11, 7),
                       fact_anchor={"value": 15, "as_of": "2026-06-30", "source": "MOEX"})
        _validate_cone(d, issues)
        self.assertFalse([i for i in issues if i["severity"] == "blocking"])

    def test_missing_fact_anchor_warns_not_blocks(self):
        issues = []
        _validate_cone(self._cond(self._bs(13.5, 13.0, 13.1, 12.5)), issues)
        self.assertFalse([i for i in issues if i["severity"] == "blocking"])
        self.assertTrue(any("fact_anchor" in i["field"] and i["severity"] == "warning"
                            for i in issues))

    def test_fact_anchor_non_numeric_blocks(self):
        issues = []
        d = self._cond(self._bs(13.5, 13.0, 13.1, 12.5), fact_anchor={"value": "high"})
        _validate_cone(d, issues)
        self.assertTrue(any("fact_anchor.value" in i["field"] and i["severity"] == "blocking"
                            for i in issues))

    def test_fact_anchor_missing_meta_warns(self):
        issues = []
        d = self._cond(self._bs(24, 14, 11, 7), fact_anchor={"value": 15})
        _validate_cone(d, issues)
        fields = [i["field"] for i in issues if i["severity"] == "warning"]
        self.assertTrue(any("as_of" in f for f in fields))
        self.assertTrue(any("source" in f for f in fields))

    def test_drift_persisted_true_computed_false_warns(self):
        issues = []
        d = self._cond(self._bs(24, 14, 11, 7),
                       fact_anchor={"value": 15, "as_of": "2026-06-30", "source": "x"},
                       one_sided_cone=True)
        _validate_cone(d, issues)
        self.assertTrue(any("one_sided_cone" in i["field"] and i["severity"] == "warning"
                            for i in issues))

    def test_bad_cone_side_value_blocks(self):
        issues = []
        d = self._cond(self._bs(24, 14, 11, 7),
                       fact_anchor={"value": 15, "as_of": "2026-06-30", "source": "x"},
                       cone_side={"2026-12-31": "sideways"})
        _validate_cone(d, issues)
        self.assertTrue(any("cone_side" in i["field"] and i["severity"] == "blocking"
                            for i in issues))

    def test_counter_world_reason_wrong_type_blocks(self):
        issues = []
        d = self._cond(self._bs(24, 14, 11, 7),
                       fact_anchor={"value": 15, "as_of": "2026-06-30", "source": "x"},
                       counter_world_reason=123)
        _validate_cone(d, issues)
        self.assertTrue(any("counter_world_reason" in i["field"] and i["severity"] == "blocking"
                            for i in issues))

    # --- _validate_falsifier_sides ---

    def test_side_coverage_missing_down_warns(self):
        issues = []
        d = {"conditional_on_scenarios": {"x": 1},
             "monitoring": [{"id": "m1", "side": "up"}]}
        _validate_falsifier_sides(d, issues)
        self.assertTrue(any("missing_side_falsifier" in i["expected"] for i in issues))

    def test_side_coverage_both_ok(self):
        issues = []
        d = {"conditional_on_scenarios": {"x": 1},
             "falsifiers": [{"id": "f1", "side": "up"}, {"id": "f2", "side": "down"}]}
        _validate_falsifier_sides(d, issues)
        self.assertFalse(any("missing_side_falsifier" in i.get("expected", "") for i in issues))

    def test_side_coverage_both_keyword(self):
        issues = []
        d = {"conditional_on_scenarios": {"x": 1}, "monitoring": [{"id": "m", "side": "both"}]}
        _validate_falsifier_sides(d, issues)
        self.assertFalse(any("missing_side_falsifier" in i.get("expected", "") for i in issues))

    def test_side_undeclared_warns(self):
        issues = []
        d = {"conditional_on_scenarios": {"x": 1}, "monitoring": [{"id": "m"}]}
        _validate_falsifier_sides(d, issues)
        self.assertTrue(any("не размечена" in i.get("expected", "") for i in issues))

    def test_side_invalid_value_blocks(self):
        issues = []
        d = {"conditional_on_scenarios": {"x": 1}, "monitoring": [{"id": "m", "side": "sideways"}]}
        _validate_falsifier_sides(d, issues)
        self.assertTrue(any(i["severity"] == "blocking" for i in issues))

    def test_side_no_conditional_skips(self):
        issues = []
        _validate_falsifier_sides({"monitoring": [{"id": "m", "side": "up"}]}, issues)
        self.assertEqual(issues, [])

    # --- integration через validate_forecast_events ---

    def _type2(self, a=13.5, b=13.0, c=13.1, d=12.5):
        return {
            "forecast": {"central_estimate": "Ставка: 13% к 2026-12-31"},
            "conditional_on_scenarios": {
                "source_matrix": "scenarios/foo.yaml", "unit": "%",
                "by_scenario": {s: {"values": {"2026-12-31": {"central": v, "range": [v - 1, v + 1]}},
                                    "provenance": "derived_from_marginal", "coverage_quality": "DERIVED"}
                                for s, v in (("A", a), ("B", b), ("C", c), ("D", d))},
                "marginal": {"method": "linear", "modal_scenario_id": "none",
                             "values": {"2026-12-31": {"central": 13.0, "range": [12, 14]}}},
            },
        }

    def test_integration_base_valid(self):
        self.assertTrue(validate_forecast_events(self._type2())["valid"], _b_fields(validate_forecast_events(self._type2())))

    def test_integration_one_sided_blocks_save(self):
        d = self._type2()
        d["conditional_on_scenarios"]["fact_anchor"] = {"value": 14.25, "as_of": "2026-06-19", "source": "CBR"}
        r = validate_forecast_events(d)
        self.assertFalse(r["valid"])
        self.assertTrue(any("counter_world_reason" in f for f in _b_fields(r)))

    def test_integration_one_sided_with_reason_valid(self):
        d = self._type2()
        d["conditional_on_scenarios"]["fact_anchor"] = {"value": 14.25, "as_of": "2026-06-19", "source": "CBR"}
        d["conditional_on_scenarios"]["counter_world_reason"] = "мир девальвации: эскалация→pass-through→ЦБ держит"
        self.assertTrue(validate_forecast_events(d)["valid"], _b_fields(validate_forecast_events(d)))

    def test_integration_no_anchor_backward_compat_valid(self):
        # Type 2 без fact_anchor — валиден как раньше (только warning про пропущенный чек)
        r = validate_forecast_events(self._type2())
        self.assertTrue(r["valid"])
        self.assertTrue(any("fact_anchor" in i["field"] and i["severity"] == "warning"
                            for i in r["issues"]))


# ---------------------------------------------------------------------------
# TestConfidenceLayering — §16 F3 (source_coverage_score / confidence_by_horizon)
# ---------------------------------------------------------------------------

class TestConfidenceLayering(unittest.TestCase):
    def _fc(self, **extra):
        d = {"forecast": {"confidence": 0.40, "central_estimate": "x"}}
        d["forecast"].update(extra)
        return d

    def test_valid_fields_no_issues(self):
        issues = []
        _validate_confidence_layering(
            self._fc(source_coverage_score=0.40,
                     confidence_by_horizon={"2026-12-31": 0.50, "2028-06-30": 0.30}), issues)
        self.assertEqual(issues, [])

    def test_absent_fields_no_issues(self):
        issues = []
        _validate_confidence_layering(self._fc(), issues)
        self.assertEqual(issues, [])

    def test_source_coverage_out_of_range_warns(self):
        issues = []
        _validate_confidence_layering(self._fc(source_coverage_score=1.5), issues)
        self.assertTrue(any("source_coverage_score" in i["field"] and i["severity"] == "warning"
                            for i in issues))
        self.assertFalse([i for i in issues if i["severity"] == "blocking"])

    def test_cbh_not_dict_warns(self):
        issues = []
        _validate_confidence_layering(self._fc(confidence_by_horizon=[0.5]), issues)
        self.assertTrue(any("confidence_by_horizon" in i["field"] and i["severity"] == "warning"
                            for i in issues))

    def test_cbh_bad_value_warns_not_blocks(self):
        issues = []
        _validate_confidence_layering(self._fc(confidence_by_horizon={"2026-12-31": 2.0}), issues)
        self.assertTrue(any(i["severity"] == "warning" for i in issues))
        self.assertFalse([i for i in issues if i["severity"] == "blocking"])

    def test_scalar_confidence_untouched(self):
        # Валидатор F3 не мутирует и не проверяет forecast.confidence (legacy).
        fc = self._fc(source_coverage_score=0.40)
        _validate_confidence_layering(fc, [])
        self.assertEqual(fc["forecast"]["confidence"], 0.40)

    def test_integration_type1_with_f3_fields_valid(self):
        d = {"isolated": True, "isolated_reason": "x",
             "forecast": {"confidence": 0.40, "source_coverage_score": 0.40,
                          "confidence_by_horizon": {"2026-12-31": 0.5}}}
        r = validate_forecast_events(d)
        self.assertTrue(r["valid"])
        self.assertEqual(r["blocking_count"], 0)


# ---------------------------------------------------------------------------
# TestPolarityLock — §17 F4 (канон Sc-A=стресс / Sc-D=разрядка)
# ---------------------------------------------------------------------------

class TestPolarityLock(unittest.TestCase):
    def _scen(self, **matrix):
        return {"type": "scenario-events", "schema_version": 1, "matrix": {**matrix},
                "scenario_triggers": [{"probability": 0.25} for _ in range(4)], "reviews": {}}

    def _pol_warn(self, r):
        return [i for i in r["issues"]
                if i["field"] in ("matrix.polarity", "matrix.axis_polarity_migration")]

    def test_canon_no_warning(self):
        r = validate_scenario_events(self._scen(polarity={"stress_pole": "A", "detente_pole": "D"}))
        self.assertEqual(self._pol_warn(r), [])
        self.assertEqual(r["blocking_count"], 0)

    def test_inverted_without_flag_warns(self):
        r = validate_scenario_events(self._scen(polarity={"stress_pole": "D", "detente_pole": "A"}))
        self.assertTrue(any(i["field"] == "matrix.polarity" and i["severity"] == "warning"
                            for i in r["issues"]))
        self.assertEqual(r["blocking_count"], 0)

    def test_inverted_with_change_and_migration_ok(self):
        r = validate_scenario_events(self._scen(
            polarity={"stress_pole": "D", "detente_pole": "A"},
            axis_polarity_change=True, axis_polarity_migration={"A": "D", "D": "A"}))
        self.assertEqual(self._pol_warn(r), [])

    def test_change_without_migration_warns(self):
        r = validate_scenario_events(self._scen(
            polarity={"stress_pole": "D", "detente_pole": "A"}, axis_polarity_change=True))
        self.assertTrue(any("migration" in i["field"] for i in r["issues"]))

    def test_polarity_absent_warns(self):
        r = validate_scenario_events(self._scen())
        self.assertTrue(any(i["field"] == "matrix.polarity" for i in r["issues"]))

    def test_invalid_pole_warns(self):
        r = validate_scenario_events(self._scen(polarity={"stress_pole": "X", "detente_pole": "D"}))
        self.assertTrue(any(i["field"] == "matrix.polarity" and i["severity"] == "warning"
                            for i in r["issues"]))

    def test_polarity_never_blocks(self):
        r = validate_scenario_events(self._scen(polarity="bogus"))
        self.assertEqual(r["blocking_count"], 0)


# ---------------------------------------------------------------------------
# TestL2Informative — §18 F5 (весь by_scenario DERIVED → не LOW 0.0%)
# ---------------------------------------------------------------------------

class TestL2Informative(unittest.TestCase):
    def _t2(self, provenances, l2_informative=None, coherence=None):
        by = {}
        for sid, prov in zip(("A", "B", "C", "D"), provenances):
            by[sid] = {"values": {"2026-12-31": {"central": 10, "range": [9, 11]}},
                       "provenance": prov,
                       "coverage_quality": "DERIVED" if prov == "derived_from_marginal" else "MEDIUM"}
        cond = {"source_matrix": "scenarios/x.yaml", "unit": "%", "by_scenario": by,
                "marginal": {"method": "linear", "modal_scenario_id": "none",
                             "values": {"2026-12-31": {"central": 10, "range": [9, 11]}}}}
        if l2_informative is not None:
            cond["l2_informative"] = l2_informative
        d = {"forecast": {"central_estimate": "x"}, "conditional_on_scenarios": cond}
        if coherence is not None:
            d["coherence_diagnostic"] = coherence
        return d

    def test_all_derived_flags_l2_and_low(self):
        d = self._t2(["derived_from_marginal"] * 4, coherence={"severity": "LOW", "divergence_pct": 0.0})
        r = validate_forecast_events(d)
        w = [i["field"] for i in r["issues"] if i["severity"] == "warning"]
        self.assertTrue(any("l2_informative" in f for f in w))
        self.assertTrue(any("coherence_diagnostic.severity" in f for f in w))
        self.assertEqual(r["blocking_count"], 0)

    def test_all_derived_with_l2_false_and_na_ok(self):
        d = self._t2(["derived_from_marginal"] * 4, l2_informative=False,
                     coherence={"severity": "N/A", "divergence_pct": 0.0})
        r = validate_forecast_events(d)
        self.assertTrue(r["valid"])
        self.assertFalse(any("l2_informative" in i["field"] for i in r["issues"]))
        self.assertEqual(r["blocking_count"], 0)

    def test_native_present_no_l2_flag(self):
        d = self._t2(["native_fca", "derived_from_marginal", "derived_from_marginal", "derived_from_marginal"])
        r = validate_forecast_events(d)
        self.assertFalse(any("l2_informative" in i["field"] for i in r["issues"]))

    def test_l2_false_with_native_contradiction_warns(self):
        d = self._t2(["native_fca", "derived_from_marginal", "derived_from_marginal", "derived_from_marginal"],
                     l2_informative=False)
        r = validate_forecast_events(d)
        self.assertTrue(any("l2_informative" in i["field"] and i["severity"] == "warning"
                            for i in r["issues"]))

    def test_na_severity_accepted(self):
        d = self._t2(["native_fca"] * 4, coherence={"severity": "N/A"})
        r = validate_forecast_events(d)
        self.assertEqual(r["blocking_count"], 0)

    def test_inferred_from_content_provenance_valid(self):
        # D8-канон (events-yaml-spec.md §5.2/§6.1) — FCA эмитит его; валидатор должен принимать.
        d = self._t2(["inferred_from_content"] * 4)
        r = validate_forecast_events(d)
        self.assertEqual(r["blocking_count"], 0, _b_fields(r))
        self.assertFalse(any("provenance" in f for f in _b_fields(r)))


class TestDeferredAudit(unittest.TestCase):
    def test_deferred_requires_scheduled_for(self):
        issues = []
        _validate_deferred_audit({"final_audit": {"status": "deferred"}}, issues)
        self.assertTrue(any("scheduled_for" in i["field"] and i["severity"] == "warning"
                            for i in issues))

    def test_deferred_with_scheduled_for_ok(self):
        issues = []
        _validate_deferred_audit(
            {"final_audit": {"status": "deferred", "scheduled_for": "2026-11-15"}}, issues)
        self.assertEqual(issues, [])

    def test_deferred_bad_date_warns(self):
        issues = []
        _validate_deferred_audit(
            {"final_audit": {"status": "deferred", "scheduled_for": "ноябрь"}}, issues)
        self.assertTrue(any("scheduled_for" in i["field"] for i in issues))

    def test_non_deferred_ignored(self):
        issues = []
        _validate_deferred_audit({"final_audit": {"status": "pending"}}, issues)
        self.assertEqual(issues, [])

    def test_deferred_never_blocks(self):
        # Через полный валидатор — deferred без даты не роняет сохранение (warning-only).
        d = {"isolated": True, "isolated_reason": "x",
             "final_audit": {"status": "deferred"}}
        r = validate_forecast_events(d)
        self.assertTrue(r["valid"])
        self.assertEqual(r["blocking_count"], 0)


# ---------------------------------------------------------------------------
# TestValidateCalibrationReport — Workflow O (маркеры сторожа M1–M4)
# ---------------------------------------------------------------------------

def _cal_fm(**over):
    fm = {"type": "calibration-report", "kind": "adhoc",
          "date": "2026-09-14", "summary": "Первый ad-hoc прогон", "n_clean": 17}
    fm.update(over)
    return fm


class TestValidateCalibrationReport(unittest.TestCase):
    def test_valid_adhoc(self):
        r = validate_calibration_report(
            {"filename": "adhoc-2026-09-14.md", "frontmatter": _cal_fm()})
        self.assertTrue(r["valid"])
        self.assertEqual(r["blocking_count"], 0)

    def test_all_kinds_prefixes(self):
        # Каждый kind валиден со своим префиксом — паритет с CAL-константами монитора
        for kind, prefix in CALIBRATION_KIND_PREFIX.items():
            r = validate_calibration_report(
                {"filename": f"{prefix}2026-09-14.md",
                 "frontmatter": _cal_fm(kind=kind)})
            self.assertTrue(r["valid"], f"{kind}: {r['issues']}")

    def test_v2_suffix_allowed(self):
        r = validate_calibration_report(
            {"filename": "adhoc-2026-09-14-v2.md", "frontmatter": _cal_fm()})
        self.assertTrue(r["valid"])

    def test_wrong_prefix_for_kind(self):
        r = validate_calibration_report(
            {"filename": "calibration-2026-09-14.md", "frontmatter": _cal_fm(kind="adhoc")})
        self.assertIn("filename", _b_fields(r))

    def test_filename_date_mismatch(self):
        r = validate_calibration_report(
            {"filename": "adhoc-2026-09-15.md", "frontmatter": _cal_fm()})
        self.assertIn("filename", _b_fields(r))

    def test_kind_out_of_enum(self):
        r = validate_calibration_report(
            {"filename": "adhoc-2026-09-14.md", "frontmatter": _cal_fm(kind="weekly")})
        self.assertIn("frontmatter.kind", _b_fields(r))

    def test_missing_type_and_summary(self):
        r = validate_calibration_report(
            {"filename": "adhoc-2026-09-14.md",
             "frontmatter": _cal_fm(type=None, summary="  ")})
        self.assertIn("frontmatter.type", _b_fields(r))
        self.assertIn("frontmatter.summary", _b_fields(r))

    def test_bad_date(self):
        r = validate_calibration_report(
            {"filename": "adhoc-2026-09-14.md", "frontmatter": _cal_fm(date="сентябрь")})
        self.assertIn("frontmatter.date", _b_fields(r))

    def test_n_clean_missing_warning_only(self):
        fm = _cal_fm()
        del fm["n_clean"]
        r = validate_calibration_report({"filename": "adhoc-2026-09-14.md", "frontmatter": fm})
        self.assertTrue(r["valid"])
        self.assertIn("frontmatter.n_clean", [i["field"] for i in _w(r)])

    def test_n_clean_wrong_type_blocks(self):
        r = validate_calibration_report(
            {"filename": "adhoc-2026-09-14.md", "frontmatter": _cal_fm(n_clean="17")})
        self.assertIn("frontmatter.n_clean", _b_fields(r))

    def test_todo_llm_blocks(self):
        r = validate_calibration_report(
            {"filename": "adhoc-2026-09-14.md",
             "frontmatter": _cal_fm(summary="TODO_LLM: написать")})
        self.assertFalse(r["valid"])

    def test_path_in_filename_blocks(self):
        r = validate_calibration_report(
            {"filename": "calibration/adhoc-2026-09-14.md", "frontmatter": _cal_fm()})
        self.assertIn("filename", _b_fields(r))

    def test_marker_visible_to_monitor_watchdog(self):
        # Round-trip контракт: валидное имя Workflow O видимо сторожу forecast-monitor
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                        "forecast-monitor", "scripts"))
        from monitor_alerts import _cal_count_markers, _cal_latest_marker
        for kind, prefix in CALIBRATION_KIND_PREFIX.items():
            name = f"{prefix}2026-09-14.md"
            r = validate_calibration_report({"filename": name, "frontmatter": _cal_fm(kind=kind)})
            self.assertTrue(r["valid"])
            self.assertEqual(_cal_count_markers([name], prefix), 1)
            self.assertIsNotNone(_cal_latest_marker([name], prefix))


class TestResearchFreshnessRCov(unittest.TestCase):
    """R-COV (2026-07-23): warning при молчаливом carry-over per-stock блока.

    Ретро-кейс: обзор 23.07 у всех 21 тикеров нёс источники с accessed_date 11.07
    и basis, идентичный обзору 15.07, при заявлении «проверено всё» — валидатор
    видел полную структуру и молчал. Правило: ≥1 источник в окне 7 дн до
    review_date ИЛИ явный carried_over: true; иначе warning (не блок)."""

    def _review(self, entry, review_date="2026-05-12"):
        d = _v2_stock_review()
        d["review_date"] = review_date
        d["per_stock"] = {"SBER": entry}
        return d

    def _entry(self, accessed=None, carried_over=None):
        e = _ok_per_stock_entry()
        e["catalyst"] = [_v2_catalyst()]
        if accessed is not None:
            e["fundamental_score_sources"] = [
                {"url": "https://example.com", "label": "src", "accessed_date": accessed}]
        if carried_over is not None:
            e["carried_over"] = carried_over
        return e

    def _rcov_warnings(self, r):
        return [i for i in r["issues"] if i.get("severity") == "warning"
                and "fundamental_score_sources" in i.get("field", "")]

    def test_stale_sources_warning_not_blocking(self):
        r = validate_weekly_review_stock_detailed(self._review(self._entry(accessed="2026-04-20")))
        self.assertTrue(r["valid"])  # warning, не блок
        warn = self._rcov_warnings(r)
        self.assertEqual(len(warn), 1)
        self.assertIn("carry-over", warn[0]["actual"])
        self.assertIn("2026-04-20", warn[0]["actual"])

    def test_fresh_source_no_warning(self):
        r = validate_weekly_review_stock_detailed(self._review(self._entry(accessed="2026-05-10")))
        self.assertEqual(self._rcov_warnings(r), [])

    def test_boundary_exactly_window_edge_fresh(self):
        # review_date 2026-05-12, окно 7 дн → floor 2026-05-05 включительно
        r = validate_weekly_review_stock_detailed(self._review(self._entry(accessed="2026-05-05")))
        self.assertEqual(self._rcov_warnings(r), [])

    def test_carried_over_flag_suppresses_warning(self):
        r = validate_weekly_review_stock_detailed(
            self._review(self._entry(accessed="2026-04-20", carried_over=True)))
        self.assertEqual(self._rcov_warnings(r), [])

    def test_no_sources_at_all_warning(self):
        r = validate_weekly_review_stock_detailed(self._review(self._entry()))
        warn = self._rcov_warnings(r)
        self.assertEqual(len(warn), 1)
        self.assertIn("нет дат", warn[0]["actual"])

    def test_fresh_div_source_counts(self):
        e = self._entry(accessed="2026-04-20")
        e["div_sources"] = [{"url": "https://example.com", "label": "div",
                             "accessed_date": "2026-05-11"}]
        r = validate_weekly_review_stock_detailed(self._review(e))
        self.assertEqual(self._rcov_warnings(r), [])

    def test_v1_schema_not_affected(self):
        d = {
            "schema_version": 1, "type": "weekly-stocks-review",
            "review_date": "2026-05-09", "snapshot_id": "portfolio-2026-05-07.json",
            "horizon_months": 20, "per_stock": {"SBER": _ok_per_stock_entry()},
        }
        r = validate_weekly_review_stock_detailed(d)
        self.assertEqual(self._rcov_warnings(r), [])


class TestScenarioAttributionGate(unittest.TestCase):
    """Hard rule 4: сплошной macro_dependency: null во всех катализаторах обзора.

    Ретро-кейс 2026-08-06 и 2026-08-15: 66 катализаторов stock-обзора и 40
    bond-обзора без единой сценарной привязки при живой матрице
    scenarios/scenario-geopolitics-ru-west-2026-07-01.yaml. Валидатор проверял
    только тип отдельного поля и оба раза пропустил; portfolio-integrated-view
    считает joint expectation через macro_dependency и деградировал молча.
    Правило: ≥1 привязанный катализатор на обзор. Сплошной null при ≥10
    катализаторах — blocking, при меньшем числе — warning (мелкий артефакт
    не должен блокироваться на пороге статистики).
    """

    def _issues(self, r):
        return [i for i in r["issues"] if "macro_dependency" in i.get("field", "")
                and "catalyst[*]" in i.get("field", "")]

    def _stock_review(self, n_tickers, macro_dependency="__absent__"):
        d = _v2_stock_review()
        d["per_stock"] = {}
        for i in range(n_tickers):
            e = _ok_per_stock_entry()
            c = _v2_catalyst()
            if macro_dependency != "__absent__":
                c["macro_dependency"] = macro_dependency
            else:
                c.pop("macro_dependency", None)
            e["catalyst"] = [c]
            d["per_stock"][f"TIC{i}"] = e
        return d

    def test_all_null_blocking_above_threshold(self):
        r = validate_weekly_review_stock_detailed(self._stock_review(12, macro_dependency=None))
        iss = self._issues(r)
        self.assertEqual(len(iss), 1)
        self.assertEqual(iss[0]["severity"], "blocking")
        self.assertFalse(r["valid"])
        self.assertIn("12", iss[0]["actual"])

    def test_absent_field_counts_as_unattributed(self):
        r = validate_weekly_review_stock_detailed(self._stock_review(12))
        self.assertEqual([i["severity"] for i in self._issues(r)], ["blocking"])

    def test_all_null_below_threshold_is_warning(self):
        r = validate_weekly_review_stock_detailed(self._stock_review(3, macro_dependency=None))
        iss = self._issues(r)
        self.assertEqual(len(iss), 1)
        self.assertEqual(iss[0]["severity"], "warning")
        self.assertTrue(r["valid"])

    def test_single_attribution_clears_gate(self):
        d = self._stock_review(12, macro_dependency=None)
        list(d["per_stock"].values())[0]["catalyst"][0]["macro_dependency"] = "Sc-B"
        self.assertEqual(self._issues(validate_weekly_review_stock_detailed(d)), [])

    def test_partial_null_is_legal(self):
        """Идиосинкратические триггеры (отсечка, оферта) от сценария не зависят."""
        d = self._stock_review(12, macro_dependency=None)
        for e in list(d["per_stock"].values())[:4]:
            e["catalyst"][0]["macro_dependency"] = "Sc-C"
        self.assertEqual(self._issues(validate_weekly_review_stock_detailed(d)), [])

    def test_quantitative_scenarios_count_as_attributed(self):
        """upside_by_scenario несёт сценарии структурно — macro_dependency не нужен."""
        d = self._stock_review(12, macro_dependency=None)
        list(d["per_stock"].values())[0]["catalyst"][0]["upside_by_scenario"] = {
            "Sc-A": 5.0, "Sc-B": 3.0, "Sc-C": -2.0, "Sc-D": -6.0}
        self.assertEqual(self._issues(validate_weekly_review_stock_detailed(d)), [])

    def test_active_scenarios_count_as_attributed(self):
        d = self._stock_review(12, macro_dependency=None)
        list(d["per_stock"].values())[0]["catalyst"][0]["active_scenarios"] = ["Sc-A"]
        self.assertEqual(self._issues(validate_weekly_review_stock_detailed(d)), [])

    def test_empty_list_is_not_attribution(self):
        d = self._stock_review(12, macro_dependency=[])
        self.assertEqual([i["severity"] for i in self._issues(d and
                          validate_weekly_review_stock_detailed(d))], ["blocking"])

    def test_bond_review_gated_too(self):
        d = _v2_bond_review()
        base = list(d["per_bond"].values())[0]
        d["per_bond"] = {}
        for i in range(12):
            e = copy.deepcopy(base)
            for c in e.get("catalyst", []):
                c["macro_dependency"] = None
            d["per_bond"][f"RU000A10{i:04d}"] = e
        r = validate_weekly_review_bond_detailed(d)
        iss = self._issues(r)
        self.assertEqual(len(iss), 1)
        self.assertEqual(iss[0]["severity"], "blocking")
        self.assertIn("per_bond", iss[0]["field"])

    def test_no_catalysts_no_issue(self):
        d = self._stock_review(12, macro_dependency=None)
        for e in d["per_stock"].values():
            e["catalyst"] = []
        self.assertEqual(self._issues(validate_weekly_review_stock_detailed(d)), [])

    def test_v1_schema_not_gated(self):
        """V2-CUTOVER: гейт живёт только в v2-ветке."""
        d = {
            "schema_version": 1, "type": "weekly-stocks-review",
            "review_date": "2026-05-09", "snapshot_id": "portfolio-2026-05-07.json",
            "horizon_months": 20, "per_stock": {"SBER": _ok_per_stock_entry()},
        }
        self.assertEqual(self._issues(validate_weekly_review_stock_detailed(d)), [])


class TrustAttributionGate(unittest.TestCase):
    """R11 (2026-08-16): атрибуция источника катализатора — `source_trust`.

    Ретро-кейс 2026-08-15: матрица доверия из INDEX.md сопоставлялась потребителем
    с прозаическим `source` (URL/фраза) — 28 IGNORE-записей против 105 катализаторов,
    отфильтровано 0, при этом правило 11 выглядело работающим. Атрибуцию теперь
    ставит производитель. Гейт покрытия — **warning**, а не blocking: обзоры до этой
    даты поля не несут по построению. Форма самого тега проверяется жёстко: пустой
    или битый `source_trust` хуже отсутствующего, потому что выглядит атрибуцией.
    """

    def _cov_issues(self, r):
        return [i for i in r["issues"] if i.get("field", "").endswith("catalyst[*].source_trust")]

    def _shape_issues(self, r):
        return [i for i in r["issues"]
                if ".source_trust" in i.get("field", "")
                and not i.get("field", "").endswith("catalyst[*].source_trust")]

    def _review(self, n=3, trust="__absent__"):
        d = _v2_stock_review()
        d["per_stock"] = {}
        for i in range(n):
            e = _ok_per_stock_entry()
            c = _v2_catalyst()
            c["macro_dependency"] = "Sc-B"      # сценарный гейт не должен фонить
            if trust != "__absent__":
                c["source_trust"] = trust
            e["catalyst"] = [c]
            d["per_stock"][f"TIC{i}"] = e
        return d

    def test_no_tags_is_warning_not_blocking(self):
        r = validate_weekly_review_stock_detailed(self._review())
        iss = self._cov_issues(r)
        self.assertEqual([i["severity"] for i in iss], ["warning"])
        self.assertTrue(r["valid"], "переходный режим не должен блокировать сохранение")

    def test_single_tag_clears_coverage_gate(self):
        d = self._review()
        list(d["per_stock"].values())[0]["catalyst"][0]["source_trust"] = {
            "analyst": "advisor", "subdomain": "self"}
        self.assertEqual(self._cov_issues(validate_weekly_review_stock_detailed(d)), [])

    def test_broken_tag_is_blocking(self):
        """Тег без поддомена выглядит атрибуцией, не будучи ею."""
        r = validate_weekly_review_stock_detailed(self._review(trust={"analyst": "БКС"}))
        iss = self._shape_issues(r)
        self.assertTrue(iss)
        self.assertEqual(iss[0]["severity"], "blocking")
        self.assertIn("subdomain", iss[0]["actual"])

    def test_non_dict_tag_is_blocking(self):
        """Ругается на КАЖДЫЙ битый тег (3 тикера → 3 блокировки), не на первый."""
        r = validate_weekly_review_stock_detailed(self._review(trust="Invest Era"))
        sev = [i["severity"] for i in self._shape_issues(r)]
        self.assertEqual((len(sev), set(sev)), (3, {"blocking"}))

    def test_todo_llm_tag_is_blocking(self):
        r = validate_weekly_review_stock_detailed(
            self._review(trust={"analyst": "TODO_LLM", "subdomain": "self"}))
        sev = [i["severity"] for i in self._shape_issues(r)]
        self.assertEqual((len(sev), set(sev)), (3, {"blocking"}))

    def test_valid_tag_passes_clean(self):
        d = self._review(trust={"analyst": "Invest Era", "subdomain": "bonds-rub"})
        r = validate_weekly_review_stock_detailed(d)
        self.assertEqual(self._cov_issues(r), [])
        self.assertEqual(self._shape_issues(r), [])

    def test_bond_review_gated_too(self):
        d = _v2_bond_review()
        for e in d["per_bond"].values():
            for c in e.get("catalyst", []):
                c.pop("source_trust", None)
                c["macro_dependency"] = "Sc-B"
        self.assertEqual(
            [i["severity"] for i in self._cov_issues(validate_weekly_review_bond_detailed(d))],
            ["warning"])

    def test_no_catalysts_no_issue(self):
        d = self._review()
        for e in d["per_stock"].values():
            e["catalyst"] = []
        self.assertEqual(self._cov_issues(validate_weekly_review_stock_detailed(d)), [])


class TestPOutperform(unittest.TestCase):
    """AIR-1 D-3: p_outperform_3m у направленных вердиктов."""

    def _run(self, entry, review_date="2026-10-10"):
        from scripts.assemble_artifact import _p_outperform_check
        issues = []
        _p_outperform_check(entry, "per_stock.X", review_date, issues)
        return [(i["severity"], i["field"]) for i in issues]

    def test_directional_missing_after_cutover_blocks(self):
        self.assertEqual(self._run({"advisor_verdict": "TRIM"}), [("blocking", "per_stock.X.p_outperform_3m")])

    def test_directional_missing_before_cutover_warns(self):
        self.assertEqual(self._run({"advisor_verdict": "BUY"}, "2026-09-26"),
                         [("warning", "per_stock.X.p_outperform_3m")])

    def test_hold_needs_nothing(self):
        self.assertEqual(self._run({"advisor_verdict": "HOLD"}), [])
        self.assertEqual(self._run({"advisor_verdict": "HOLD_TO_MAT"}), [])

    def test_unconstrained_verdict_decides(self):
        # гейт урезал BUY до HOLD — вероятность всё равно нужна: система хотела направления
        self.assertEqual(self._run({"advisor_verdict": "HOLD", "unconstrained_verdict": "BUY"}),
                         [("blocking", "per_stock.X.p_outperform_3m")])

    def test_valid_and_invalid_values(self):
        self.assertEqual(self._run({"advisor_verdict": "SELL", "p_outperform_3m": 0.62}), [])
        self.assertEqual(self._run({"advisor_verdict": "SELL", "p_outperform_3m": 0}), [])
        for bad in (1.2, -0.1, "0.6", True):
            self.assertEqual(self._run({"advisor_verdict": "SELL", "p_outperform_3m": bad}),
                             [("blocking", "per_stock.X.p_outperform_3m")], bad)


class TestRpa30StaleTextAndSourceUrl(unittest.TestCase):
    """RPA-30 (аудит 20.10.2026): текст со старой ценой и внешний катализатор без ссылки — warning."""

    def setUp(self):
        from scripts.assemble_artifact import _stale_text_check, _catalyst_source_url_check
        self.stale, self.url = _stale_text_check, _catalyst_source_url_check

    def _run(self, fn, *args):
        issues = []
        fn(*args, issues)
        return issues

    def test_stock_div_basis_old_price_flagged(self):
        e = {"price_rub": 283.63, "div_basis": "Консенсус ≈42 ₽ → 15,2% к 276,48 ₽. Решение весной."}
        r = self._run(self.stale, e, "per_stock.SBER", "stock")
        self.assertEqual([i["severity"] for i in r], ["warning"])
        self.assertIn("276.48", r[0]["actual"])

    def test_stock_current_price_and_non_price_numbers_quiet(self):
        e = {"price_rub": 3427.0, "div_basis": "6,4% к 3 427 ₽; дивиденд 220 ₽ к 1 000 ₽ номинала."}
        self.assertEqual(self._run(self.stale, e, "p", "stock"), [])

    def test_bond_price_lead_mismatch(self):
        e = {"current_price": 79.435, "advisor_verdict_basis": "Цена 78,80 → 79,10, YTM 16,78 → 16,70%. HOLD."}
        self.assertEqual(len(self._run(self.stale, e, "p", "bond")), 1)
        e["advisor_verdict_basis"] = "Цена 78,80 → 79,43. HOLD."
        self.assertEqual(self._run(self.stale, e, "p", "bond"), [])

    def test_external_catalyst_without_url(self):
        e = {"catalyst": [
            {"id": "a", "source": "Эксперт/Ведомости 16.10", "source_trust": {"analyst": "issuer"}},
            {"id": "b", "source": "https://e-disclosure.ru/x", "source_trust": {"analyst": "issuer"}},
            {"id": "c", "source": "advisor estimate", "source_trust": {"analyst": "advisor"}},
            {"id": "d", "source": "moex_iss", "source_trust": {"analyst": "moex_iss"}},
        ]}
        r = self._run(self.url, e, "per_stock.CNRU")
        self.assertEqual([i["field"] for i in r], ["per_stock.CNRU.catalyst[0].source"])


class TestValidateMonitorReport(unittest.TestCase):
    """Workflow L3 (2026-10-26): у HIGH/MEDIUM — готовая команда «/скилл …»; условия — не в alerts."""

    def _mr(self, **alert):
        a = {"severity": "HIGH", "category": "stale", "target": "x", "message": "m",
             "detected_at": "2026-10-26", "suggested_action": "/forecast-confidence-applier Обнови прогноз x.yaml"}
        a.update(alert)
        return {"schema_version": 1, "type": "monitor-report", "generated_at": "2026-10-26T08:00:00",
                "producer": "forecast-monitor", "alerts": [a], "freshness_audit": {}}

    def _fields(self, d):
        return [i["field"] for i in validate_monitor_report(d)["issues"] if i["severity"] == "blocking"]

    def test_valid(self):
        self.assertTrue(validate_monitor_report(self._mr())["valid"])

    def test_command_in_backticks_ok(self):
        self.assertEqual(self._fields(self._mr(suggested_action="`/scenario-builder Обнови сценарии s.yaml`")), [])

    def test_phrase_without_skill_blocks(self):
        # отчёт 2026-10-26: «Проверить подписание Graham Act вручную; …»
        self.assertEqual(self._fields(self._mr(suggested_action="Проверить вручную и обновить x")),
                         ["alerts[0].suggested_action"])

    def test_missing_command_blocks_for_medium_not_low(self):
        self.assertEqual(self._fields(self._mr(severity="MEDIUM", suggested_action=None)), ["alerts[0].suggested_action"])
        self.assertEqual(self._fields(self._mr(severity="LOW", suggested_action=None)), [])

    def test_condition_target_blocks(self):
        d = self._mr(category="event_window", target="condition ru000a107795-date-2110",
                     suggested_action="/ru-portfolio-advisor Условие ru000a107795-date-2110 — разбираем")
        self.assertEqual(self._fields(d), ["alerts[0].target"])

    def test_required_and_enums(self):
        d = self._mr(category="weird")
        del d["freshness_audit"]
        self.assertEqual(sorted(self._fields(d)), ["alerts[0].category", "freshness_audit"])

    def _warn(self, d):
        return [i["field"] for i in validate_monitor_report(d)["issues"] if i["severity"] == "warning"]

    def test_partial_without_checked_warns(self):
        # частичный прогон без перечня файлов: вьюер не знает, какие предупреждения заменить
        self.assertEqual(self._warn({**self._mr(), "scope": "partial"}), ["checked"])
        self.assertEqual(self._warn({**self._mr(), "scope": "partial", "checked": []}), ["checked"])
        self.assertTrue(validate_monitor_report({**self._mr(), "scope": "partial"})["valid"])

    def test_horizon_passed_category_and_closing_phrase(self):
        # горизонт прошёл: категория допустима; действие — «Закрой прогноз», не «Обнови»
        ok = self._mr(category="horizon_passed",
                      suggested_action="/save-to-library Закрой прогноз usd-rub-sept-2026: на 01.09.2026 86,38, прогноз 85–90 — сбылся")
        self.assertEqual(self._fields(ok), [])
        self.assertEqual(self._warn(ok), [])
        bad = self._mr(category="horizon_passed", suggested_action="/forecast-confidence-applier Обнови прогноз x.yaml")
        self.assertEqual(self._fields(bad), [])
        self.assertEqual(self._warn(bad), ["alerts[0].suggested_action"])
        self.assertEqual(self._warn(self._mr(category="horizon_passed", severity="LOW", suggested_action=None)), [])

    def test_unknown_category_blocks(self):
        self.assertEqual(self._fields(self._mr(category="horizon_gone")), ["alerts[0].category"])

    def test_partial_with_checked_and_full_clean(self):
        self.assertEqual(self._warn({**self._mr(), "scope": "partial", "checked": ["forecasts/x-2026-04-30.yaml"]}), [])

        self.assertEqual(self._warn({**self._mr(), "scope": "full"}), [])
        self.assertEqual(self._warn(self._mr()), [])          # без scope — полный, как раньше

    def test_unknown_scope_warns(self):
        self.assertEqual(self._warn({**self._mr(), "scope": "some"}), ["scope"])

    def test_condition_events_retired(self):
        # шаг 7 цикла машиночитаемости: прежнее поле — blocking, находки — condition_findings[]
        d = self._mr()
        d["condition_events"] = [{"condition_id": "c2", "event": "x", "status": "not_found"}]
        self.assertEqual(self._fields(d), ["condition_events"])

    def test_condition_findings(self):
        d = self._mr()
        d["condition_findings"] = [
            {"condition_id": "c1", "version": 2, "doc": "https://e-disclosure.ru/x", "found_at": "2026-10-29", "note": "вышел"},
            {"condition_id": "c2", "version": 1, "doc": None, "found_at": None, "note": None},
        ]
        self.assertEqual(self._fields(d), [])
        d["condition_findings"] = [
            {"condition_id": "c1", "version": 2, "doc": None, "found_at": "2026-10-29"},
            {"condition_id": "", "version": 0, "doc": "https://x", "found_at": None},
            {"condition_id": "c3", "version": "1", "doc": "https://x", "found_at": "29.10.2026", "ticker": "X"},
        ]
        self.assertEqual(sorted(self._fields(d)), sorted([
            "condition_findings[0].doc",
            "condition_findings[1].condition_id", "condition_findings[1].version", "condition_findings[1].found_at",
            "condition_findings[2].ticker", "condition_findings[2].version", "condition_findings[2].found_at"]))
        self.assertEqual(self._fields({**self._mr(), "condition_findings": {"c1": 1}}), ["condition_findings"])



class TestMonitorReportCoverage(unittest.TestCase):
    """FM-20: пункт monitoring[] с прошедшей датой не может исчезнуть из отчёта монитора — алерт с monitoring_id
    или строка monitoring_checked; корень даёт --root (контекст `_monitoring_context`)."""

    @classmethod
    def setUpClass(cls):
        import tempfile, yaml
        from pathlib import Path
        cls.root = Path(tempfile.mkdtemp(prefix="mr-cover-"))
        (cls.root / "forecasts").mkdir()
        (cls.root / "scenarios").mkdir()
        (cls.root / "forecasts" / "f-2026-10-01.yaml").write_text(yaml.safe_dump({
            "schema_version": 1, "type": "forecast-events", "status": "active",
            "forecast": {"topic": "f", "date": "2026-10-01"},
            "monitoring": [{"id": "past", "check_date": "2026-11-04", "auto_checkable": True},
                           {"id": "future", "check_date": "2026-12-01", "auto_checkable": True}]},
            allow_unicode=True), encoding="utf-8")
        (cls.root / "scenarios" / "s-old-2026-05-01.yaml").write_text(yaml.safe_dump({
            "schema_version": 1, "type": "scenario-events", "status": "superseded",
            "matrix": {"topic": "s-old"},
            "monitoring": [{"id": "old-past", "check_date": "2026-06-01"}]}), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.root, ignore_errors=True)

    def _mr(self, gen="2026-11-06T09:00:00+03:00", alerts=None, mchecked=None, **top):
        d = {"schema_version": 1, "type": "monitor-report", "generated_at": gen, "producer": "forecast-monitor",
             "alerts": alerts or [], "freshness_audit": {}}
        if mchecked is not None:
            d["monitoring_checked"] = mchecked
        d.update(top)
        return d

    def _run(self, d, root=True):
        from scripts.assemble_artifact import _monitoring_context_from_root
        if root:
            _monitoring_context_from_root(d, str(self.root))
        return validate_monitor_report(d)

    def _sev(self, r, sev):
        return [(i["field"], str(i["actual"])) for i in r["issues"] if i["severity"] == sev]

    _ROW = {"target": "f", "target_file": "forecasts/f-2026-10-01.yaml", "monitoring_id": "past",
            "check_date": "2026-11-04", "result": "not_met"}

    def test_uncovered_past_item_blocks(self):
        r = self._run(self._mr())
        self.assertFalse(r["valid"])
        b = self._sev(r, "blocking")
        self.assertEqual(len(b), 1, b)          # будущий пункт и неактивный сценарий не требуются
        self.assertIn("не отражён: forecasts/f-2026-10-01.yaml past 2026-11-04", b[0][1])

    def test_alert_with_monitoring_id_covers(self):
        a = {"severity": "LOW", "category": "factor_breach", "target": "f", "monitoring_id": "past",
             "message": "m", "detected_at": "2026-11-06"}
        r = self._run(self._mr(alerts=[a]))
        self.assertTrue(r["valid"], r["issues"])
        self.assertEqual(self._sev(r, "warning"), [])

    def test_horizon_passed_alert_covers_its_items(self):
        """Прогноз с прошедшим горизонтом закрывают с исходом: его пункты покрыты алертом horizon_passed."""
        hp = {"severity": "HIGH", "category": "horizon_passed", "target_kind": "forecast",
              "message": "горизонт прошёл, ставку сохранили", "detected_at": "2026-11-06",
              "suggested_action": "/save-to-library Закрой прогноз f: на дату горизонта ставка сохранена — не сбылся"}
        for key in ({"target": "f-alias", "target_file": "forecasts/f-2026-10-01.yaml"}, {"target": "f"}):
            r = self._run(self._mr(alerts=[dict(hp, **key)]))
            self.assertEqual(self._sev(r, "blocking"), [], key)
            self.assertTrue(r["valid"], r["issues"])
        r = self._run(self._mr(alerts=[dict(hp, target="other", target_file="forecasts/other.yaml")]))
        self.assertFalse(r["valid"])                                  # чужой прогноз пункт не покрывает

    def test_checked_row_covers(self):
        r = self._run(self._mr(mchecked=[dict(self._ROW)]))
        self.assertTrue(r["valid"], r["issues"])
        self.assertEqual(self._sev(r, "warning"), [])

    def test_checked_row_result_codelist_and_unverified_note(self):
        r = self._run(self._mr(mchecked=[dict(self._ROW, result="done")]))
        self.assertEqual([f for f, _ in self._sev(r, "blocking")], ["monitoring_checked[0].result"])
        r = self._run(self._mr(mchecked=[dict(self._ROW, result="unverified")]))
        self.assertTrue(r["valid"])
        self.assertEqual([f for f, _ in self._sev(r, "warning")], ["monitoring_checked[0].note"])
        r = self._run(self._mr(mchecked=[dict(self._ROW, result="unverified", note="ручной пункт, владелец")]))
        self.assertEqual(self._sev(r, "warning"), [])

    def test_unknown_monitoring_id_warns(self):
        r = self._run(self._mr(mchecked=[dict(self._ROW), dict(self._ROW, monitoring_id="ghost")]))
        self.assertTrue(r["valid"])
        self.assertEqual([f for f, _ in self._sev(r, "warning")], ["monitoring_checked[1].monitoring_id"])

    def test_old_report_not_checked(self):
        r = self._run(self._mr(gen="2026-11-04T10:00:00+03:00"))
        self.assertTrue(r["valid"])
        self.assertEqual(r["issues"], [])

    def test_without_root_warns(self):
        r = self._run(self._mr(), root=False)
        self.assertTrue(r["valid"])
        self.assertEqual([f for f, _ in self._sev(r, "warning")], ["monitoring_checked"])

    def test_partial_scope_only_checked_files(self):
        r = self._run(self._mr(scope="partial", checked=["forecasts/other.yaml"]))
        self.assertTrue(r["valid"], r["issues"])

    def test_cli_file_and_root(self):
        import json, subprocess, sys, tempfile, yaml
        from pathlib import Path
        script = Path(__file__).parent.parent / "scripts" / "assemble_artifact.py"
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "monitor-report-2026-11-06.yaml"
            p.write_text(yaml.safe_dump(self._mr(), allow_unicode=True), encoding="utf-8")
            r = subprocess.run([sys.executable, str(script), "validate-monitor-report", "--file", str(p),
                                "--root", str(self.root)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["blocking_count"], 1, r.stdout)



class TestSweepMethodRequired(unittest.TestCase):
    """RPA-34: новости по ≥5 бумагам — субагентами через sweep_collect.py (coverage.method).

    26.10.2026 обзор акций на Sonnet открыл ~45 страниц в основном контексте и прошёл 3 компакции.
    """

    def _stock(self, n=6, date="2026-10-27", coverage=None):
        d = _v2_stock_review()
        d["review_date"] = date
        d["per_stock"] = {f"T{i}": copy.deepcopy(d["per_stock"]["SBER"]) for i in range(n)}
        if coverage is not None:
            d["coverage"] = coverage
        return d

    def _bond(self, corp=6, date="2026-10-27", coverage=None):
        d = _v2_bond_review()
        d["review_date"] = date
        base = d["per_bond"]["RU000A105KU0"]
        d["per_bond"] = {}
        for i in range(corp):
            e = copy.deepcopy(base); e["issuer"] = f"Эмитент {i}"; d["per_bond"][f"RU{i}"] = e
        for i in range(4):
            e = copy.deepcopy(base); e["bond_type"] = "ofz"; e["issuer"] = "Минфин"; d["per_bond"][f"OFZ{i}"] = e
        if coverage is not None:
            d["coverage"] = coverage
        return d

    def _cov(self, result):
        return [i for i in result["issues"] if i["field"].startswith("coverage.method")]

    def test_stock_without_method_blocks(self):
        iss = self._cov(validate_weekly_review_stock_detailed(self._stock()))
        self.assertEqual([(i["field"], i["severity"]) for i in iss], [("coverage.method", "blocking")])

    def test_stock_with_sweep_ok(self):
        self.assertEqual(self._cov(validate_weekly_review_stock_detailed(
            self._stock(coverage={"method": "sweep_collect"}))), [])

    def test_inline_needs_note_then_warns(self):
        r = validate_weekly_review_stock_detailed(self._stock(coverage={"method": "inline_owner_approved"}))
        self.assertIn(("coverage.method_note", "blocking"), [(i["field"], i["severity"]) for i in self._cov(r)])
        r = validate_weekly_review_stock_detailed(self._stock(coverage={
            "method": "inline_owner_approved", "method_note": "в среде нет субагентов; владелец согласился 27.10"}))
        self.assertEqual([(i["field"], i["severity"]) for i in self._cov(r)], [("coverage.method", "warning")])

    def test_old_reviews_and_small_books_untouched(self):
        self.assertEqual(self._cov(validate_weekly_review_stock_detailed(self._stock(date="2026-10-26"))), [])
        self.assertEqual(self._cov(validate_weekly_review_stock_detailed(self._stock(n=4))), [])

    def test_bond_counts_corporate_issuers_only(self):
        self.assertEqual(len(self._cov(validate_weekly_review_bond_detailed(self._bond(corp=6)))), 1)
        self.assertEqual(self._cov(validate_weekly_review_bond_detailed(self._bond(corp=4))), [])  # + 4 ОФЗ
        self.assertEqual(self._cov(validate_weekly_review_bond_detailed(
            self._bond(corp=6, coverage={"method": "sweep_collect"}))), [])



class TestCliFileInput(unittest.TestCase):
    """RPA-38: вход по пути к файлу вместо echo '<YAML>' в команде (обзор 200–260 КБ)."""

    def _run(self, *args, stdin=None):
        import subprocess
        script = os.path.join(os.path.dirname(__file__), "..", "scripts", "assemble_artifact.py")
        return subprocess.run([sys.executable, script, *args], input=stdin, capture_output=True, text=True)

    def test_file_input_and_anchor_removed(self):
        import json, tempfile, yaml
        with tempfile.TemporaryDirectory() as d:
            cur = os.path.join(d, "cur.yaml")
            with open(cur, "w", encoding="utf-8") as f:
                yaml.safe_dump(_v2_stock_review(), f, allow_unicode=True)
            r = self._run("validate-weekly-review-stock", "--file", cur)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("valid", json.loads(r.stdout))
            # перенос ограничений из прошлого обзора упразднён (срез производный) — --anchor/--current нет
            r = self._run("validate-weekly-review-stock", "--anchor", cur, "--current", cur)
            self.assertEqual(r.returncode, 1)

    def test_stdin_still_works_and_bad_arg_fails(self):
        import json
        r = self._run("validate-weekly-review-stock", stdin=json.dumps(_v2_stock_review()))
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self._run("validate-weekly-review-stock", "--oops", "x")
        self.assertEqual(r.returncode, 1)



class TestWeekNoteAndConfidenceBasis(unittest.TestCase):
    """Аддитивные поля бумаги (план переосмысления вьюера, 2026-10-26): week_note (контракт A)
    и confidence_basis (что снижает уверенность)."""

    def _issues(self, d):
        return validate_weekly_review_stock_detailed(d)["issues"]

    def _blocking(self, d, field_part):
        return [i for i in self._issues(d) if i["severity"] == "blocking" and field_part in i["field"]]

    def test_fields_absent_is_fine_but_low_confidence_warns(self):
        d = _v2_stock_review()
        d["per_stock"]["SBER"]["advisor_verdict_confidence"] = 0.5
        r = validate_weekly_review_stock_detailed(d)
        self.assertTrue(r["valid"])
        warns = [i for i in r["issues"] if i["severity"] == "warning" and i["field"].endswith("confidence_basis")]
        self.assertEqual(len(warns), 1)
        d["per_stock"]["SBER"]["confidence_basis"] = "один источник, отчёт не вышел"
        r = validate_weekly_review_stock_detailed(d)
        self.assertFalse([i for i in r["issues"] if i["field"].endswith("confidence_basis")])

    def test_high_confidence_needs_no_basis(self):
        d = _v2_stock_review()   # 0.85
        d["per_stock"]["SBER"]["confidence_basis"] = None
        self.assertFalse([i for i in self._issues(d) if i["field"].endswith("confidence_basis")])

    def test_confidence_basis_todo_or_blank_blocks(self):
        d = _v2_stock_review()
        d["per_stock"]["SBER"]["confidence_basis"] = "TODO_LLM_what_lowers_confidence_one_phrase_or_null"
        self.assertTrue(self._blocking(d, "confidence_basis"))
        d["per_stock"]["SBER"]["confidence_basis"] = "   "
        self.assertTrue(self._blocking(d, "confidence_basis"))

    def test_week_note_ok(self):
        d = _v2_stock_review()
        d["per_stock"]["SBER"]["week_note"] = {"what_happened": ["23.10: IR подтвердил восстановление."],
                                               "recommendation": ["держать"], "macro_link": None}
        self.assertTrue(validate_weekly_review_stock_detailed(d)["valid"])
        self.assertFalse(self._blocking(d, "week_note"))

    def test_week_note_shape_errors(self):
        d = _v2_stock_review()
        e = d["per_stock"]["SBER"]
        e["week_note"] = "текст"
        self.assertTrue(self._blocking(d, "week_note"))
        e["week_note"] = {"what_happened": "строка вместо списка"}
        self.assertTrue(self._blocking(d, "week_note.what_happened"))
        e["week_note"] = {"what_happened": [], "recommendation": []}
        self.assertTrue(self._blocking(d, "week_note"))
        e["week_note"] = {"what_happened": ["x"], "summary": "лишний"}
        self.assertTrue(self._blocking(d, "week_note"))
        e["week_note"] = {"what_happened": ["TODO_LLM_fill"]}
        self.assertTrue(self._blocking(d, "week_note.what_happened"))
        e["week_note"] = {"what_happened": ["x"], "macro_link": ""}
        self.assertTrue(self._blocking(d, "week_note.macro_link"))

    def test_bond_entry_gets_same_checks(self):
        d = _v2_bond_review()
        isin = next(iter(d["per_bond"]))
        d["per_bond"][isin]["week_note"] = {"what_happened": "не список"}
        r = validate_weekly_review_bond_detailed(d)
        self.assertTrue([i for i in r["issues"] if i["severity"] == "blocking" and "week_note" in i["field"]])


# ---------------------------------------------------------------------------
# TestBondRatingBlock — per_bond[ISIN].rating {value, agency, date, source} (bond-subtypes-plan.md §4.5):
# необязательный блок; форма — warning, не blocking (загрузчик берёт из него рейтинг для вывода корзины).
# ---------------------------------------------------------------------------

class TestBondRatingBlock(unittest.TestCase):
    def _entry(self, d):
        return d["per_bond"]["RU000A105KU0"]

    def _rating_w(self, result):
        return [i for i in _w(result) if ".rating" in i["field"]]

    def _run(self, rating):
        d = _v2_bond_review()
        self._entry(d)["rating"] = rating
        return validate_weekly_review_bond_detailed(d)

    def test_absent_and_null_are_valid(self):
        d = _v2_bond_review()
        self._entry(d).pop("rating", None)
        self.assertEqual(self._rating_w(validate_weekly_review_bond_detailed(d)), [])
        self.assertEqual(self._rating_w(self._run(None)), [])

    def test_good_block_passes(self):
        r = self._run({"value": "AA-", "agency": "АКРА", "date": "2026-09-12", "source": "https://www.acra-ratings.ru/"})
        self.assertTrue(r["valid"])
        self.assertEqual(self._rating_w(r), [])

    def test_no_rating_needs_no_agency(self):
        r = self._run({"value": "нет рейтинга", "agency": None, "date": "2026-10-28", "source": "реестр агентств"})
        self.assertEqual(self._rating_w(r), [])

    def test_bad_value_agency_date_source_are_warnings_not_blocking(self):
        r = self._run({"value": "AAA+", "agency": "Moody's", "date": "12.09.2026", "source": ""})
        fields = {i["field"].split("rating.")[1] for i in self._rating_w(r)}
        self.assertEqual(fields, {"value", "agency", "date", "source"})
        self.assertTrue(r["valid"])

    def test_not_a_dict(self):
        self.assertEqual(len(self._rating_w(self._run("AA-"))), 1)

    def test_below_ladder_value_rejected(self):
        self.assertTrue(any(i["field"].endswith("rating.value")
                            for i in self._rating_w(self._run(
                                {"value": "CCC", "agency": "АКРА", "date": "2026-09-12", "source": "x"}))))

if __name__ == "__main__":
    unittest.main(verbosity=2)
