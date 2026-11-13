#!/usr/bin/env python3
"""
test_stress_digest.py — тесты для scripts/stress_digest.py.

Закрывает RPA-20: чтение stress-файла в режимах 3 и 8. Покрывает разные лестницы
свежести (Mode 8 отказывается при >60 дней, Mode 3 деградирует до defer L1-redirect),
арифметику якорных горизонтов (ключ hNN ≠ число месяцев — источник неверного множителя
дивидендов в прежнем шаблоне), взвешивание EV по акциям с ренормировкой на покрытые
бумаги, bond-сторону из готового блока `bond_carry`, таблицу пропорций L1-redirect,
контракт блока для отчёта, сверку поколения со снапшотом, read-only гарантию и
(TestDocsGuard) согласованность референсов после переименования mode-8-stress.md.

Запуск:
    ~/.pyenv/versions/3.12.9/bin/python3 skills/ru-portfolio-advisor/tests/test_stress_digest.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SKILL_DIR = os.path.join(REPO, "skills", "ru-portfolio-advisor")
SCRIPT_PATH = os.path.join(SKILL_DIR, "scripts", "stress_digest.py")
REFS = os.path.join(SKILL_DIR, "references")

sys.path.insert(0, os.path.join(SKILL_DIR, "scripts"))
import stress_digest as sd  # noqa: E402

PY = sys.executable

MEMORY = os.path.expanduser("~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/Portfolio")
LIVE_STRESS = os.path.join(MEMORY, "stress", "stress-2026-08-15-geopol-ru-west-shell-d1.yaml")
LIVE_SNAPSHOT = os.path.join(MEMORY, "snapshots", "portfolio-2026-08-19.json")

try:
    import yaml  # noqa: F401
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# ─────────────────────────── синтетические фикстуры ───────────────────────────

def mk_slice(ev, tail, scenario="A"):
    return {
        "expected_pct_pweighted": {"value": ev, "ci_pct": [ev - 5, ev + 5]},
        "tail_var_pct": tail,
        "tail_var_scenario_id": scenario,
    }


def mk_stress(date_="2026-08-15", **over):
    data = {
        "schema_version": 2,
        "type": "portfolio-stress-test",
        "date": date_,
        "horizon_mode": "anchored",
        "primary_horizon": 12,
        "horizon_ends": {"h6": "2026-12-31", "h12": "2027-06-30", "h24": "2028-06-30"},
        "portfolio_snapshot_id": "portfolio-2026-08-15.json",
        "run_id": "PSS-TEST",
        "scenario_matrix_ref": "scenarios/test.yaml",
        "per_position": {
            "AAA": {"weight_pct": 50.0, "by_horizon": {"h12": mk_slice(10.0, -20.0),
                                                       "h24": mk_slice(20.0, -30.0)}},
            "BBB": {"weight_pct": 30.0, "by_horizon": {"h12": mk_slice(-4.0, -35.0, "B"),
                                                       "h24": mk_slice(-8.0, -40.0, "B")}},
        },
        "bond_carry": {
            "as_of": date_,
            "baseline_cbr_rate_pct": 14.0,
            "per_position": {
                "RU000AAA0001": {"kind": "bond", "flags": [], "by_horizon": {
                    "h12": {"expected_carry_pct": 12.0, "t_live_months": 10.45, "matures_within": False},
                    "h24": {"expected_carry_pct": 24.0, "t_live_months": 22.5, "matures_within": False}}},
                "RU000AAA0002": {"kind": "bond", "flags": [], "by_horizon": {
                    "h12": {"expected_carry_pct": 8.0, "t_live_months": 10.45, "matures_within": False},
                    "h24": {"expected_carry_pct": 16.0, "t_live_months": 22.5, "matures_within": False}}},
            },
        },
    }
    data.update(over)
    return data


def mk_snapshot(as_of="2026-08-15"):
    return {
        "schema_version": "2.0",
        "as_of_date": as_of,
        "holdings": [
            {"ticker": "AAA", "asset_type": "stock", "value_rub": 600_000,
             "is_blocked": False, "current_price_source": "moex_iss"},
            {"ticker": "BBB", "asset_type": "stock", "value_rub": 300_000,
             "is_blocked": False, "current_price_source": "moex_iss"},
            {"ticker": "CCC", "asset_type": "stock", "value_rub": 100_000,
             "is_blocked": False, "current_price_source": "moex_iss"},
            {"ticker": "LQDT", "asset_type": "stock", "value_rub": 500_000,
             "is_blocked": False, "current_price_source": "moex_iss"},
            {"ticker": "AAPL", "asset_type": "stock", "value_rub": 900_000,
             "is_blocked": False, "current_price_source": "cost_basis"},
            {"ticker": "FROZ", "asset_type": "stock", "value_rub": 700_000,
             "is_blocked": True, "current_price_source": "moex_iss"},
            {"ticker": "RU000AAA0001", "isin": "RU000AAA0001", "name": "Тест-1",
             "asset_type": "bond", "value_rub": 750_000, "is_blocked": False},
            {"ticker": "RU000AAA0002", "isin": "RU000AAA0002", "name": "Тест-2",
             "asset_type": "bond", "value_rub": 250_000, "is_blocked": False},
            {"ticker": "RU000AAA0009", "isin": "RU000AAA0009", "name": "Тест-непокрытая",
             "asset_type": "bond", "value_rub": 100_000, "is_blocked": False},
        ],
        "ie_actual": {"per_ticker": {
            "AAA": {"real_share_pct": 60.0},
            "BBB": {"real_share_pct": 30.0},
            "CCC": {"real_share_pct": 10.0},
        }},
    }


def write_tmp_text(text):
    fd, path = tempfile.mkstemp(suffix=".md")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def write_tmp(obj, suffix):
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        if suffix.endswith(".json"):
            json.dump(obj, f, ensure_ascii=False)
        else:
            import yaml as _y
            _y.safe_dump(obj, f, allow_unicode=True)
    return path


# ─────────────────────────── свежесть ───────────────────────────

class TestFreshnessLadders(unittest.TestCase):
    """Лестницы у режимов разные — Mode 8 отказывается, Mode 3 деградирует."""

    def test_mode8_fresh_warn_refuse(self):
        self.assertEqual(sd.freshness_verdict(5, 8)["code"], "fresh")
        self.assertEqual(sd.freshness_verdict(30, 8)["code"], "fresh")
        self.assertEqual(sd.freshness_verdict(31, 8)["code"], "confirm_required")
        self.assertEqual(sd.freshness_verdict(60, 8)["code"], "confirm_required")
        self.assertEqual(sd.freshness_verdict(61, 8)["code"], "refuse")

    def test_mode8_refuse_is_blocking_others_are_not(self):
        self.assertTrue(sd.freshness_verdict(61, 8)["blocking"])
        self.assertFalse(sd.freshness_verdict(60, 8)["blocking"])
        self.assertFalse(sd.freshness_verdict(365, 3)["blocking"])

    def test_mode3_degrades_instead_of_refusing(self):
        self.assertEqual(sd.freshness_verdict(5, 3)["code"], "fresh")
        self.assertEqual(sd.freshness_verdict(31, 3)["code"], "warn")
        self.assertEqual(sd.freshness_verdict(61, 3)["code"], "defer_redirect")

    def test_mode3_defer_text_says_rest_of_mode_continues(self):
        text = sd.freshness_verdict(90, 3)["text"]
        self.assertIn("L1-redirect", text)
        self.assertIn("выполняется полностью", text)

    def test_absent_verdicts_differ_by_mode(self):
        self.assertEqual(sd.absent_verdict(3)["code"], "absent_defer_redirect")
        self.assertEqual(sd.absent_verdict(8)["code"], "absent_continue_noted")
        self.assertFalse(sd.absent_verdict(8)["blocking"])


# ─────────────────────────── горизонты ───────────────────────────

class TestHorizons(unittest.TestCase):
    """Ключ hNN — конвенция цепочки, длина берётся из horizon_ends."""

    def test_anchored_months_are_not_literal(self):
        rows = sd.build_horizons(mk_stress(), date(2026, 8, 20), ["h12", "h24"])
        h12, h24 = rows[0], rows[1]
        self.assertAlmostEqual(h12["months_from_stress"], 10.48, delta=0.05)
        self.assertAlmostEqual(h24["months_from_stress"], 22.51, delta=0.05)
        self.assertNotEqual(h12["scale_factor"], h12["literal_factor"])

    def test_scale_factor_matches_real_window(self):
        rows = sd.build_horizons(mk_stress(), date(2026, 8, 20), ["h12"])
        self.assertAlmostEqual(rows[0]["scale_factor"], 0.873, delta=0.005)
        self.assertEqual(rows[0]["literal_factor"], 1.0)

    def test_months_from_as_of_tracks_report_date(self):
        rows = sd.build_horizons(mk_stress(), date(2026, 10, 15), ["h12"])
        self.assertLess(rows[0]["months_from_as_of"], rows[0]["months_from_stress"])

    def test_unknown_horizon_key_is_error_not_neighbour(self):
        with self.assertRaises(sd.StressDigestError) as ctx:
            sd.build_horizons(mk_stress(), date(2026, 8, 20), ["h18"])
        self.assertIn("h18", str(ctx.exception))

    def test_missing_horizon_ends_is_error(self):
        st = mk_stress()
        del st["horizon_ends"]
        with self.assertRaises(sd.StressDigestError):
            sd.build_horizons(st, date(2026, 8, 20), ["h12"])


# ─────────────────────────── акции ───────────────────────────

class TestStocksSide(unittest.TestCase):

    def setUp(self):
        self.stress = mk_stress()
        self.snapshot = mk_snapshot()
        self.res = sd.stocks_side(self.stress, self.snapshot, ["h12", "h24"], top_n=10)

    def test_weights_come_from_ie_actual_when_complete(self):
        self.assertEqual(self.res["weight_source"], "ie_actual.real_share_pct")

    def test_money_market_blocked_and_frozen_are_out_of_the_book(self):
        seen = {r["ticker"] for r in self.res["positions"]} | {u["ticker"] for u in self.res["uncovered"]}
        self.assertNotIn("LQDT", seen)
        self.assertNotIn("AAPL", seen)
        self.assertNotIn("FROZ", seen)

    def test_uncovered_ticker_is_reported_with_weight(self):
        self.assertEqual([u["ticker"] for u in self.res["uncovered"]], ["CCC"])
        self.assertAlmostEqual(self.res["uncovered_weight_pct"], 10.0, delta=0.01)

    def test_weighted_ev_renormalises_on_covered_only(self):
        # 60×10 + 30×(−4) = 480; /90 = 5.33 — а не /100 = 4.8, как было бы, если бы
        # непокрытая CCC молча вошла с нулевым EV.
        self.assertAlmostEqual(self.res["weighted_ev_pct"]["h12"], 5.33, delta=0.01)

    def test_weighted_ev_h24_uses_its_own_slice(self):
        self.assertAlmostEqual(self.res["weighted_ev_pct"]["h24"], 10.67, delta=0.01)

    def test_top_n_limits_and_renormalises(self):
        res = sd.stocks_side(self.stress, self.snapshot, ["h12"], top_n=1)
        self.assertEqual(res["top_tickers"], ["AAA"])
        self.assertAlmostEqual(res["weighted_ev_top_pct"]["h12"], 10.0, delta=0.01)

    def test_positions_sorted_by_weight_desc(self):
        weights = [r["weight_pct"] for r in self.res["positions"]]
        self.assertEqual(weights, sorted(weights, reverse=True))

    def test_worst_tail_is_the_minimum_not_the_largest_position(self):
        worst = self.res["worst_tail"]["h12"]
        self.assertEqual(worst["ticker"], "BBB")
        self.assertEqual(worst["scenario_id"], "B")

    def test_fallback_to_value_rub_when_ie_actual_incomplete(self):
        snap = mk_snapshot()
        del snap["ie_actual"]["per_ticker"]["BBB"]
        res = sd.stocks_side(self.stress, snap, ["h12"], top_n=10)
        self.assertEqual(res["weight_source"], "value_rub")
        self.assertAlmostEqual(res["positions"][0]["weight_pct"], 60.0, delta=0.01)


# ─────────────────────────── облигации ───────────────────────────

class TestBondsSide(unittest.TestCase):

    def setUp(self):
        self.res = sd.bonds_side(mk_stress(), mk_snapshot(), ["h12", "h24"])

    def test_carry_is_weighted_by_value(self):
        # 750/1000 × 12 + 250/1000 × 8 = 11.0, ренормировка на покрытые (без 100к непокрытой)
        self.assertAlmostEqual(self.res["weighted_carry_pct"]["h12"], 11.0, delta=0.01)

    def test_h24_slice_read_separately(self):
        self.assertAlmostEqual(self.res["weighted_carry_pct"]["h24"], 22.0, delta=0.01)

    def test_uncovered_isin_named(self):
        self.assertEqual([u["isin"] for u in self.res["uncovered"]], ["RU000AAA0009"])
        self.assertTrue(self.res["available"])

    def test_t_live_months_is_carried_through(self):
        top = self.res["positions"][0]
        self.assertAlmostEqual(top["by_horizon"]["h12"]["t_live_months"], 10.45, delta=0.01)

    def test_no_bonds_in_snapshot_degrades_cleanly(self):
        snap = mk_snapshot()
        snap["holdings"] = [h for h in snap["holdings"] if h["asset_type"] != "bond"]
        res = sd.bonds_side(mk_stress(), snap, ["h12"])
        self.assertFalse(res["available"])
        self.assertEqual(res["positions"], [])


# ─────────────────────────── redirect ───────────────────────────

class TestRedirectTable(unittest.TestCase):
    """Границы включаются в нижнюю корзину (§6.2)."""

    def test_narrow_spread_keeps_buffer_inside_stocks(self):
        self.assertIn("внутри акций", sd.redirect_proportion(12.0, 15.0)["proportion"])

    def test_boundary_ten_is_still_inside_stocks(self):
        self.assertIn("внутри акций", sd.redirect_proportion(10.0, 20.0)["proportion"])

    def test_mid_spread_is_fifty_fifty(self):
        self.assertIn("50/50", sd.redirect_proportion(10.0, 25.0)["proportion"])

    def test_boundary_twenty_is_fifty_fifty(self):
        self.assertIn("50/50", sd.redirect_proportion(0.0, 20.0)["proportion"])

    def test_structural_bond_bias(self):
        self.assertIn("70/30", sd.redirect_proportion(0.0, 25.0)["proportion"])
        self.assertIn("70/30", sd.redirect_proportion(0.0, 35.0)["proportion"])

    def test_strong_bias_above_thirty_five(self):
        self.assertIn("90/10", sd.redirect_proportion(0.0, 40.0)["proportion"])

    def test_negative_spread_keeps_money_in_stocks(self):
        res = sd.redirect_proportion(20.0, 5.0)
        self.assertAlmostEqual(res["spread_pp"], -15.0, delta=0.01)
        self.assertIn("внутри акций", res["proportion"])


# ─────────────────────────── контракт блока отчёта ───────────────────────────

class TestReportBlock(unittest.TestCase):

    def setUp(self):
        self.payload = sd.run_digest(
            write_tmp(mk_stress(), ".yaml"), write_tmp(mk_snapshot(), ".json"),
            3, date(2026, 8, 20), ["h12", "h24"], "h12", 10, None, None,
        )
        self.block = self.payload["report_block"]

    def test_provenance_present(self):
        self.assertIn("15.08.2026", self.block)
        self.assertIn("возраст 5 дн", self.block)

    def test_horizon_factor_is_spelled_out_with_two_decimals(self):
        self.assertIn("0,87", self.block)
        self.assertIn("не 1,00", self.block)

    def test_stress_macro_ev_named_for_report(self):
        self.assertIn("Stress macro EV", self.block)
        self.assertIn("Bond carry", self.block)

    def test_candidates_outside_portfolio_are_flagged_as_separate_work(self):
        self.assertIn("moex_quotes.py", self.block)

    def test_generation_match_produces_no_noise(self):
        self.assertNotIn("Поколение расходится", self.block)

    def test_generation_mismatch_is_surfaced(self):
        payload = sd.run_digest(
            write_tmp(mk_stress(), ".yaml"), write_tmp(mk_snapshot("2026-08-19"), ".json"),
            3, date(2026, 8, 20), ["h12"], "h12", 10, None, None,
        )
        self.assertIn("Поколение расходится", payload["report_block"])
        self.assertTrue(any(w.startswith("generation_mismatch") for w in payload["warnings"]))

    def test_redirect_line_appears_only_with_both_sides(self):
        payload = sd.run_digest(
            write_tmp(mk_stress(), ".yaml"), write_tmp(mk_snapshot(), ".json"),
            3, date(2026, 8, 20), ["h12"], "h12", 10, 12.0, 15.0,
        )
        self.assertIn("Спред TR", payload["report_block"])
        self.assertNotIn("Спред TR", self.block)

    def test_stale_warn_marks_proportion_for_recheck(self):
        payload = sd.run_digest(
            write_tmp(mk_stress(), ".yaml"), write_tmp(mk_snapshot(), ".json"),
            3, date(2026, 10, 1), ["h12"], "h12", 10, 12.0, 30.0,
        )
        self.assertEqual(payload["freshness"]["code"], "warn")
        self.assertIn("после refresh", payload["report_block"])

    def test_absent_stress_block_states_degradation(self):
        payload = sd.run_digest(None, None, 3, date(2026, 8, 20), ["h12"], "h12", 10, None, None)
        self.assertIn("Стресс-тест недоступен", payload["report_block"])
        self.assertIn("L1-redirect", payload["report_block"])

    def test_uncovered_stocks_named_in_block(self):
        self.assertIn("CCC", self.block)


# ─────────────────────────── входные гарантии ───────────────────────────

class TestInputGuards(unittest.TestCase):

    def test_schema_v1_is_refused_with_cutover_hint(self):
        path = write_tmp(mk_stress(schema_version=1), ".yaml")
        with self.assertRaises(sd.StressDigestError) as ctx:
            sd.load_stress(path)
        self.assertIn("V2-CUTOVER", str(ctx.exception))

    def test_missing_file_is_clear_error(self):
        with self.assertRaises(sd.StressDigestError):
            sd.load_stress("/nonexistent/stress.yaml")

    def test_snapshot_without_holdings_is_clear_error(self):
        with self.assertRaises(sd.StressDigestError):
            sd.stocks_side(mk_stress(), {"as_of_date": "2026-08-15"}, ["h12"], 10)

    def test_stress_dated_in_future_does_not_go_negative(self):
        payload = sd.run_digest(
            write_tmp(mk_stress("2026-09-01"), ".yaml"), None,
            3, date(2026, 8, 20), ["h12"], "h12", 10, None, None,
        )
        self.assertEqual(payload["source"]["age_days"], 0)
        self.assertTrue(any(w.startswith("stress_in_future") for w in payload["warnings"]))

    def test_primary_horizon_is_added_when_missing_from_list(self):
        payload = sd.run_digest(
            write_tmp(mk_stress(), ".yaml"), None,
            3, date(2026, 8, 20), ["h24"], "h12", 10, None, None,
        )
        self.assertIn("h12", [h["key"] for h in payload["horizons"]])


# ─────────────────────────── CLI ───────────────────────────

class TestCli(unittest.TestCase):

    def test_json_run_exits_zero(self):
        stress, snap = write_tmp(mk_stress(), ".yaml"), write_tmp(mk_snapshot(), ".json")
        proc = subprocess.run([PY, SCRIPT_PATH, "--stress", stress, "--snapshot", snap,
                               "--as-of", "2026-08-20", "--json"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["mode"], 3)
        self.assertIn("report_block", payload)

    def test_mode8_stale_exits_one(self):
        stress = write_tmp(mk_stress("2026-05-01"), ".yaml")
        proc = subprocess.run([PY, SCRIPT_PATH, "--stress", stress, "--mode", "8",
                               "--as-of", "2026-08-20"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("refuse", proc.stdout)

    def test_mode3_same_stale_file_exits_zero(self):
        stress = write_tmp(mk_stress("2026-05-01"), ".yaml")
        proc = subprocess.run([PY, SCRIPT_PATH, "--stress", stress, "--mode", "3",
                               "--as-of", "2026-08-20"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("defer_redirect", proc.stdout)

    def test_bad_input_exits_two_without_traceback(self):
        proc = subprocess.run([PY, SCRIPT_PATH, "--stress", "/nonexistent.yaml"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)


# ─────────────────────────── lint-draft ───────────────────────────

class TestLintDraft(unittest.TestCase):
    """Ровно две проверки: провенанс стресса и литеральный множитель горизонта."""

    PROV = "**Макро-срез — `stress-2026-08-15-geopol-ru-west-shell-d1.yaml` от 15.08.2026 (возраст 5 дн).**"

    def test_stress_numbers_without_provenance_are_flagged(self):
        v = sd.lint_draft("Stress macro EV по корзине +6,6%.")
        self.assertEqual(len(v), 1)
        self.assertIn("файл и дата стресса", v[0][1])

    def test_provenance_by_artifact_name_clears_it(self):
        self.assertEqual(sd.lint_draft(f"{self.PROV}\nStress macro EV +6,6%."), [])

    def test_provenance_by_prose_date_clears_it(self):
        text = "Опираюсь на стресс-тест от 15.08.2026.\nBond carry по держимым бумагам +11,9%."
        self.assertEqual(sd.lint_draft(text), [])

    def test_literal_horizon_factor_is_flagged_even_with_provenance(self):
        v = sd.lint_draft(f"{self.PROV}\nДивиденды масштабируем × 24/12.")
        self.assertEqual(len(v), 1)
        self.assertIn("якорные", v[0][1])

    def test_real_factor_is_not_flagged(self):
        self.assertEqual(sd.lint_draft(f"{self.PROV}\nДивиденды масштабированы множителем 0,87."), [])

    def test_text_without_stress_signals_is_clean(self):
        self.assertEqual(sd.lint_draft("Разбор изменений IE и тайминг продаж, стресс не упоминается."), [])

    def test_each_trigger_line_reported_once(self):
        v = sd.lint_draft("Stress macro EV и bond carry в одной строке.")
        self.assertEqual(len(v), 1)

    def test_violations_sorted_by_line(self):
        text = "Stress macro EV +6%.\nСпред TR = +20 пп.\nBond carry +11%."
        self.assertEqual([n for n, _ in sd.lint_draft(text)], [1, 2, 3])

    def test_cli_exit_one_on_violation(self):
        path = write_tmp_text("Спред TR = +20,6 пп → пропорция 70/30.")
        proc = subprocess.run([PY, SCRIPT_PATH, "--lint-draft", path], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Нарушений: 1", proc.stdout)

    def test_cli_exit_zero_on_clean_draft(self):
        path = write_tmp_text(f"{self.PROV}\nStress macro EV +6,6%.")
        proc = subprocess.run([PY, SCRIPT_PATH, "--lint-draft", path], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Линт чист", proc.stdout)

    def test_cli_missing_draft_exits_two(self):
        proc = subprocess.run([PY, SCRIPT_PATH, "--lint-draft", "/nonexistent/draft.md"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)


# ─────────────────────────── константы-близнецы ───────────────────────────

class TestConstantTwins(unittest.TestCase):
    """MONEY_MARKET_TICKERS живёт в трёх скриптах — расхождение не должно проходить молча."""

    def test_money_market_sets_agree(self):
        import gate_aware_sizing as gas
        import build_weekly_stock_stub as bwss
        self.assertEqual(sd.MONEY_MARKET_TICKERS, gas.MONEY_MARKET_TICKERS)
        self.assertEqual(sd.MONEY_MARKET_TICKERS, bwss.MONEY_MARKET_TICKERS)


# ─────────────────────────── документация ───────────────────────────

class TestDocsGuard(unittest.TestCase):
    """Переименование mode-8-stress.md → stress-reading.md доведено до всех ссылок."""

    def read(self, name):
        with open(os.path.join(REFS, name), encoding="utf-8") as f:
            return f.read()

    def test_old_file_is_gone(self):
        self.assertFalse(os.path.exists(os.path.join(REFS, "mode-8-stress.md")))

    def test_no_reference_points_at_old_name(self):
        for root, _dirs, files in os.walk(SKILL_DIR):
            for name in files:
                if not name.endswith(".md"):
                    continue
                path = os.path.join(root, name)
                if os.path.basename(path) == "stress-reading.md":
                    continue  # шапка честно называет файл, который заменила
                with open(path, encoding="utf-8") as f:
                    self.assertNotIn("mode-8-stress", f.read(), f"устаревшая ссылка в {name}")

    def test_stress_reading_covers_both_modes(self):
        text = self.read("stress-reading.md")
        self.assertIn("Mode 3", text)
        self.assertIn("Mode 8", text)
        self.assertIn("stress_digest.py", text)

    def test_stress_reading_mentions_draft_lint(self):
        self.assertIn("--lint-draft", self.read("stress-reading.md"))

    def test_stress_reading_states_anchored_horizons(self):
        text = self.read("stress-reading.md")
        self.assertIn("horizon_ends", text)
        self.assertIn("anchored", text)

    def test_skill_md_points_at_new_file_and_script(self):
        with open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("references/stress-reading.md", text)
        self.assertIn("scripts/stress_digest.py", text)

    def test_skill_md_primary_horizon_is_h12(self):
        with open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as f:
            text = f.read()
        section = text.split("### Режимы 3 и 8 — чтение stress-файла", 1)[1].split("###", 1)[0]
        self.assertIn("h12", section)
        self.assertIn("вторая колонка", section)

    def test_rebalance_framework_uses_bond_carry(self):
        text = self.read("rebalance-framework.md")
        self.assertIn("bond_carry", text)
        self.assertIn("stress_digest.py", text)

    def test_rebalance_framework_defers_instead_of_refusing(self):
        text = self.read("rebalance-framework.md")
        self.assertIn("L1-redirect **defer**", text)

    def test_template_requires_provenance_and_real_horizon(self):
        text = self.read("output-templates.md")
        self.assertIn("stress_digest.py --mode 3", text)
        self.assertNotIn("(множители `× 24/12`)", text)

    def test_analysis_process_step8_covers_mode3(self):
        text = self.read("analysis-process.md")
        step = text.split("**Шаг 8.", 1)[1].split("**Шаг 7.5", 1)[0]
        self.assertIn("режимов 3 и 8", step)
        self.assertIn("stress_digest.py", step)

    def test_stocks_methodology_ladder_scoped_to_mode4(self):
        text = self.read("stocks-methodology.md")
        self.assertIn("только для Mode 4", text)

    def test_registered_in_repo_docs(self):
        # с 2026-10-05 единственный список тестов — реестр (его запускает tools/run_tests.py);
        # CLAUDE.md тесты не перечисляет
        with open(os.path.join(REPO, "docs", "test-registry.md"), encoding="utf-8") as f:
            registry = f.read()
        self.assertIn("python3 skills/ru-portfolio-advisor/tests/test_stress_digest.py", registry)


# ─────────────────────────── живая регрессия ───────────────────────────

@unittest.skipUnless(HAS_YAML and os.path.exists(LIVE_STRESS) and os.path.exists(LIVE_SNAPSHOT),
                     "нужен Synology mount с боевыми стрессом 15.08 и снапшотом 19.08 + PyYAML")
class TestLiveRegression(unittest.TestCase):
    """Числа снятого прогона 20.08.2026 — стресс 15.08 против снапшота 19.08."""

    @classmethod
    def setUpClass(cls):
        proc = subprocess.run([PY, SCRIPT_PATH, "--stress", LIVE_STRESS, "--snapshot", LIVE_SNAPSHOT,
                               "--as-of", "2026-08-20", "--json"], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        cls.payload = json.loads(proc.stdout)

    def test_age_and_verdict(self):
        self.assertEqual(self.payload["source"]["age_days"], 5)
        self.assertEqual(self.payload["freshness"]["code"], "fresh")

    def test_anchored_horizon_factors(self):
        h12 = next(h for h in self.payload["horizons"] if h["key"] == "h12")
        h24 = next(h for h in self.payload["horizons"] if h["key"] == "h24")
        self.assertAlmostEqual(h12["scale_factor"], 0.873, delta=0.01)
        self.assertAlmostEqual(h24["scale_factor"], 1.875, delta=0.01)

    def test_weighted_stock_ev(self):
        self.assertAlmostEqual(self.payload["stocks"]["weighted_ev_pct"]["h12"], 6.00, delta=0.05)
        self.assertAlmostEqual(self.payload["stocks"]["weighted_ev_top_pct"]["h12"], 6.60, delta=0.05)

    def test_all_active_stocks_covered_by_stress(self):
        self.assertEqual(self.payload["stocks"]["uncovered"], [])

    def test_bond_carry_weighted_and_gaps(self):
        self.assertAlmostEqual(self.payload["bonds"]["weighted_carry_pct"]["h12"], 11.87, delta=0.05)
        self.assertEqual(len(self.payload["bonds"]["uncovered"]), 4)

    def test_generation_mismatch_detected(self):
        self.assertFalse(self.payload["generation"]["match"])


# ─────────────────────────── пересчёт сайта ───────────────────────────

class TestSiteRecalc(unittest.TestCase):
    """Числа — из recalc-<стресс> (auto/), возраст и вердикт — по стрессу скилла."""

    NAME = "stress-2026-08-01-test.yaml"

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, self.NAME)
        self._dump(self.path, mk_stress("2026-08-01"))
        self._touch(self.path, "2026-08-10T00:00:00+03:00")   # стресс записан до пересчёта (at = 20.08)

    @staticmethod
    def _touch(path, iso):
        from datetime import datetime as _dt
        ts = _dt.fromisoformat(iso).timestamp()
        os.utime(path, (ts, ts))

    @staticmethod
    def _dump(path, obj):
        import yaml as _y
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            _y.safe_dump(obj, f, allow_unicode=True)

    def _recalc(self, source=None, ev=77.0, **rc_over):
        st = mk_stress("2026-08-20", run_id="RECALC-x", portfolio_snapshot_id="portfolio-2026-08-19.json")
        st["per_position"]["AAA"]["by_horizon"]["h12"] = mk_slice(ev, -20.0)
        st["recalc"] = {"source_stress": source or self.NAME, "source_kind": "stress",
                        "source_snapshot_id": "portfolio-2026-08-15.json",
                        "snapshot_id": "portfolio-2026-08-19.json", "reason": "snapshot",
                        "at": "2026-08-20T10:00:00+03:00", "narrative_stale": True, **rc_over}
        self._dump(os.path.join(self.dir, "auto", "recalc-" + self.NAME), st)

    def _run(self, stress, auto=True):
        return sd.run_digest(stress, None, 3, date(2026, 8, 25), ["h12"], "h12", 10, None, None,
                             auto_recalc=auto)

    def _ev(self, payload):
        return payload["horizons"] and payload["horizons"][0]["key"]

    def test_recalc_used_numbers_from_it_age_from_judgments(self):
        self._recalc()
        p = self._run(self.path)
        self.assertEqual(p["source"]["file"], self.NAME)
        self.assertEqual(p["source"]["numbers_file"], "recalc-" + self.NAME)
        self.assertEqual(p["source"]["date"], "2026-08-01")
        self.assertEqual(p["source"]["age_days"], 24)  # от 01.08, а не от 20.08
        self.assertEqual(p["source"]["portfolio_snapshot_id"], "portfolio-2026-08-19.json")
        rc = p["stress_recalc"]
        self.assertEqual(rc["judgments_date"], "2026-08-01")
        self.assertTrue(rc["narrative_stale"])
        self.assertIn("пересчёт сайта", rc["message"])
        self.assertIn("пересчёт сайта", p["report_block"])
        self.assertIn("написаны для чисел дня прогона", p["report_block"])
        self.assertIn("числа:", sd.build_text_output(p))

    def test_recalc_numbers_reach_stocks_side(self):
        self._recalc(ev=77.0)
        snap = write_tmp(mk_snapshot("2026-08-19"), ".json")
        p = sd.run_digest(self.path, snap, 3, date(2026, 8, 25), ["h12"], "h12", 10, None, None,
                          auto_recalc=True)
        base = sd.run_digest(self.path, snap, 3, date(2026, 8, 25), ["h12"], "h12", 10, None, None)
        self.assertNotEqual(json.dumps(p["stocks"], sort_keys=True), json.dumps(base["stocks"], sort_keys=True))
        self.assertTrue(p["generation"]["match"])
        self.assertIsNone(base["stress_recalc"])

    def test_recalc_of_other_stress_not_taken(self):
        self._recalc(source="stress-2026-07-01-old.yaml")
        p = self._run(self.path)
        self.assertIsNone(p["stress_recalc"])
        self.assertEqual(p["source"]["numbers_file"], self.NAME)
        self.assertTrue(any(w.startswith("stress_recalc_skipped") for w in p["warnings"]))

    def test_broken_recalc_does_not_crash(self):
        os.makedirs(os.path.join(self.dir, "auto"))
        with open(os.path.join(self.dir, "auto", "recalc-" + self.NAME), "w") as f:
            f.write("{: not yaml [")
        p = self._run(self.path)
        self.assertIsNone(p["stress_recalc"])
        self.assertTrue(any(w.startswith("stress_recalc_skipped") for w in p["warnings"]))

    def test_explicit_stress_does_not_substitute(self):
        self._recalc()
        p = self._run(self.path, auto=False)
        self.assertIsNone(p["stress_recalc"])
        self.assertEqual(p["source"]["numbers_file"], self.NAME)

    def test_explicit_recalc_file_ages_by_judgments(self):
        self._recalc()
        p = self._run(os.path.join(self.dir, "auto", "recalc-" + self.NAME), auto=False)
        self.assertEqual(p["source"]["age_days"], 24)
        self.assertEqual(p["source"]["file"], self.NAME)
        self.assertEqual(p["stress_recalc"]["judgments_date"], "2026-08-01")

    def test_no_auto_dir_behaves_as_before(self):
        p = self._run(self.path)
        self.assertIsNone(p["stress_recalc"])
        self.assertFalse([w for w in p["warnings"] if w.startswith("stress_recalc")])
        self.assertEqual(p["source"]["age_days"], 24)

    def test_cli_auto_picks_recalc_and_ignores_auto_dir_in_selection(self):
        self._recalc()
        r = subprocess.run([PY, SCRIPT_PATH, "--stress-dir", self.dir, "--as-of", "2026-08-25", "--json"],
                           capture_output=True, text=True)
        out = json.loads(r.stdout)
        self.assertEqual(out["source"]["file"], self.NAME)
        self.assertIsNotNone(out["stress_recalc"])

    def test_recalc_older_than_stress_file_is_skipped(self):
        self._recalc()
        self._touch(self.path, "2026-08-21T00:00:00+03:00")   # стресс заменён после пересчёта (at = 20.08)
        p = self._run(self.path)
        self.assertIsNone(p["stress_recalc"])
        self.assertEqual(p["source"]["numbers_file"], self.NAME)
        w = [x for x in p["warnings"] if x.startswith("stress_recalc_skipped")]
        self.assertTrue(w and "до последней записи" in w[0], p["warnings"])

    def test_recalc_not_older_than_stress_file_is_taken(self):
        self._recalc()
        self._touch(self.path, "2026-08-20T10:00:00+03:00")   # та же секунда, что recalc.at — берётся
        p = self._run(self.path)
        self.assertEqual(p["source"]["numbers_file"], "recalc-" + self.NAME)
        self.assertFalse([x for x in p["warnings"] if x.startswith("stress_recalc")])

    def test_recalc_at_without_zone_is_moscow(self):
        self._recalc(at="2026-08-20T10:00:00")
        self._touch(self.path, "2026-08-20T10:00:01+03:00")
        self.assertIsNone(self._run(self.path)["stress_recalc"])   # 10:00 МСК < 10:00:01 МСК
        self._touch(self.path, "2026-08-20T09:59:59+03:00")
        self.assertIsNotNone(self._run(self.path)["stress_recalc"])


class TestFindLatestStress(unittest.TestCase):
    """Один день — два файла: решает время записи, а не имя; старая дата новую не обгоняет."""

    def _mk(self, d, name, date_s, when):
        p = os.path.join(d, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"date: '{date_s}'\n")
        os.utime(p, (when, when))
        return p

    def test_same_date_later_written_wins(self):
        d = tempfile.mkdtemp()
        a = self._mk(d, "stress-2026-08-01-b.yaml", "2026-08-01", 1_000_000)
        b = self._mk(d, "stress-2026-08-01-a.yaml", "2026-08-01", 2_000_000)
        self.assertEqual(sd.find_latest_stress(d), b)
        os.utime(a, (3_000_000, 3_000_000))
        self.assertEqual(sd.find_latest_stress(d), a)

    def test_old_date_with_later_mtime_does_not_win(self):
        d = tempfile.mkdtemp()
        self._mk(d, "stress-2026-07-01-x.yaml", "2026-07-01", 9_000_000)
        new = self._mk(d, "stress-2026-08-01-x.yaml", "2026-08-01", 1_000_000)
        self.assertEqual(sd.find_latest_stress(d), new)


# ─────────────────────────── сроки сайта ───────────────────────────

class TestSiteTerms(unittest.TestCase):
    """Файл сроков сайта сверяется со сроками стресса: расхождение — предупреждение, не отказ."""

    ENDS = {"h6": "2026-12-31", "h12": "2027-06-30", "h24": "2028-06-30"}   # сроки mk_stress

    def _file(self, ends=None, **over):
        doc = {"schema": "horizons@1", "horizon_ends": ends or dict(self.ENDS), "primary_horizon": 12,
               "set_at": "2026-11-06T21:30:00+03:00", "reason": "тест", "history": []}
        doc.update(over)
        return write_tmp(doc, ".json")

    def _run(self, hf, **stress_over):
        stress, snap = write_tmp(mk_stress(**stress_over), ".yaml"), write_tmp(mk_snapshot(), ".json")
        return sd.run_digest(stress, snap, 3, date(2026, 8, 20), ["h12"], "h12", 10, None, None, horizons_file=hf)

    def test_same_terms_no_warning(self):
        p = self._run(self._file())
        self.assertIs(p["terms"]["match"], True)
        self.assertFalse([w for w in p["warnings"] if "terms" in w])
        self.assertEqual(p["terms"]["stress"], self.ENDS)
        self.assertEqual(p["terms"]["site"]["primary_horizon"], 12)

    def test_primary_horizon_is_not_compared(self):
        p = self._run(self._file(primary_horizon=6))
        self.assertIs(p["terms"]["match"], True)

    def test_different_dates_warn_with_both_sets_and_site_date(self):
        p = self._run(self._file(ends={"h6": "2027-05-06", "h12": "2027-11-06", "h24": "2028-11-06"}))
        self.assertIs(p["terms"]["match"], False)
        w = [x for x in p["warnings"] if x.startswith("stress_terms_mismatch: ")]
        self.assertEqual(len(w), 1)
        self.assertIn("стресс посчитан на сроки h6 2026-12-31, h12 2027-06-30, h24 2028-06-30", w[0])
        self.assertIn("действующие сроки h6 2027-05-06, h12 2027-11-06, h24 2028-11-06", w[0])
        self.assertIn("(заданы на сайте 06.11.2026)", w[0])
        self.assertIn("числа стресса относятся к прежним срокам", w[0])

    def test_different_labels_warn(self):
        p = self._run(self._file(ends={"h6": "2026-12-31", "h12": "2027-06-30"}))
        self.assertIs(p["terms"]["match"], False)

    def test_no_file_gives_null_and_no_warning(self):
        p = self._run(os.path.join(tempfile.mkdtemp(), "нет.json"))
        self.assertIsNone(p["terms"]["site"])
        self.assertIsNone(p["terms"]["match"])
        self.assertFalse([w for w in p["warnings"] if "terms" in w or "horizons_file" in w])
        self.assertIsNone(self._run(None)["terms"]["match"])

    def test_invalid_file_is_treated_as_absent_with_reason(self):
        p = self._run(self._file(ends={"h6": "2027-06-30", "h12": "2026-12-31"}))
        self.assertIsNone(p["terms"]["match"])
        self.assertTrue(any(w.startswith("horizons_file_invalid:") for w in p["warnings"]))
        self.assertFalse(any(w.startswith("stress_terms_mismatch") for w in p["warnings"]))
        bad = write_tmp_text("{не json")
        self.assertTrue(any(w.startswith("horizons_file_invalid:") for w in self._run(bad)["warnings"]))

    def test_validity_rules_match_site(self):
        good = {"schema": "horizons@1", "horizon_ends": dict(self.ENDS), "primary_horizon": 12}
        self.assertEqual(sd.horizons_file_errors(good), [])
        for label, chg in (("schema", {"schema": "x"}), ("пусто", {"horizon_ends": {}}),
                           ("ключ", {"horizon_ends": {"six": "2027-01-01"}}), ("h0", {"horizon_ends": {"h0": "2027-01-01"}}),
                           ("дата", {"horizon_ends": {"h6": "2027-02-30"}, "primary_horizon": 6}),
                           ("порядок", {"horizon_ends": {"h6": "2028-01-01", "h12": "2027-01-01"}}),
                           ("основной", {"primary_horizon": 7}), ("основной bool", {"primary_horizon": True}),
                           ("семь", {"horizon_ends": {f"h{i}": f"202{i}-01-01" for i in range(1, 8)}, "primary_horizon": 1})):
            self.assertTrue(sd.horizons_file_errors({**good, **chg}), label)

    def test_cli_default_path_is_next_to_stress_dir(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "Portfolio", "stress"))
        os.makedirs(os.path.join(root, "scenarios"))
        with open(os.path.join(root, "scenarios", "horizons.json"), "w", encoding="utf-8") as f:
            json.dump({"schema": "horizons@1", "horizon_ends": {"h6": "2027-05-06"}, "primary_horizon": 6,
                       "set_at": "2026-11-06T10:00:00+03:00"}, f)
        stress = write_tmp(mk_stress(), ".yaml")
        proc = subprocess.run([PY, SCRIPT_PATH, "--stress", stress, "--stress-dir", os.path.join(root, "Portfolio", "stress"),
                               "--as-of", "2026-08-20", "--json"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIs(json.loads(proc.stdout)["terms"]["match"], False)
        explicit = os.path.join(root, "scenarios", "horizons.json")
        proc = subprocess.run([PY, SCRIPT_PATH, "--stress", stress, "--horizons-file", explicit,
                               "--as-of", "2026-08-20", "--json"], capture_output=True, text=True)
        self.assertIs(json.loads(proc.stdout)["terms"]["match"], False)


# ─────────────────────────── read-only ───────────────────────────

class TestReadOnly(unittest.TestCase):

    def test_no_write_mode_file_opens_in_source(self):
        with open(SCRIPT_PATH, encoding="utf-8") as f:
            src = f.read()
        forbidden = re.findall(r"""open\([^)]*["']([wxa]b?\+?)["']""", src)
        self.assertEqual(forbidden, [], f"stress_digest.py открывает файл(ы) на запись: {forbidden}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
