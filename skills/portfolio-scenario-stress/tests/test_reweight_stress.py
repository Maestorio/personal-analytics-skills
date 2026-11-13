#!/usr/bin/env python3
"""
test_reweight_stress.py — перевзвешивание стресс-артефакта и чувствительность (PSS-6).

Тесты с пометкой [РАЗЛИЧИТЕЛЬ] существуют не ради покрытия, а ради отличения верной
реализации от правдоподобной неверной, найденной аудитом плана. Снимать их нельзя:
без каждого из них соответствующая фальшивка проходит весь остальной список.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import reweight_stress as m  # noqa: E402

HAS_YAML = True
try:
    import yaml  # noqa: F401
except ImportError:
    HAS_YAML = False

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reweight_stress.py"
CM = Path("/Users/you/Library/CloudStorage/SynologyDrive-home/Claude-Memory")
LIVE = CM / "Portfolio/stress/stress-2026-08-04-geopol-ru-west-shell-d1.yaml"


def _stress(positions, scenarios=("A", "B", "C", "D"), horizons=("h6", "h12"),
            p=None, p_by_horizon=None, total_value=1_000_000.0, cash_pct=0.0,
            primary=None):
    """
    Синтетический артефакт. positions — {ticker: (weight_pct, {hk: {sid: delta}})}.
    """
    per_pos = {}
    for tkr, (w, deltas) in positions.items():
        per_pos[tkr] = {
            "weight_pct": w,
            "by_horizon": {
                hk: {"delta_pct_by_scenario": {
                    sid: {"value": deltas[hk][sid], "ci_pct": [0.0, 0.0]}
                    for sid in scenarios}}
                for hk in horizons},
        }
    scen = {}
    for sid in scenarios:
        node = {"p": (p or {}).get(sid, 1.0 / len(scenarios))}
        if p_by_horizon and sid in p_by_horizon:
            node["p_by_horizon"] = p_by_horizon[sid]
        scen[sid] = node
    doc = {
        "schema_version": 2, "date": "2026-08-04",
        "per_position": per_pos, "scenarios": scen,
        "cash_rub_pct": cash_pct,
        "portfolio_summary": {"total_value_rub": total_value},
    }
    if primary is not None:
        doc["primary_horizon"] = primary
    return doc


def _simple(scenarios=("A", "B", "C", "D"), horizons=("h6", "h12"), **kw):
    """Один тикер весом 100%, дельта = +10 у A, +20 у B, +30 у C, +40 у D."""
    base = {sid: 10.0 * (i + 1) for i, sid in enumerate(scenarios)}
    return _stress({"X": (100.0, {hk: dict(base) for hk in horizons})},
                   scenarios=scenarios, horizons=horizons, **kw)


class LoadAndContract(unittest.TestCase):
    def test_v1_artifact_refused(self):
        d = _simple(); d["schema_version"] = 1
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(d, f, allow_unicode=True); path = Path(f.name)
        with self.assertRaises(SystemExit) as cm:
            m.load_stress(path)
        self.assertIn("schema_version", str(cm.exception))
        path.unlink()

    def test_default_horizon_converts_int_primary(self):
        """primary_horizon в артефакте — ЧИСЛО 12, ключи by_horizon — строки 'h12'."""
        d = _simple(horizons=("h6", "h12"), primary=12)
        self.assertEqual(m.default_horizon(d), "h12")

    def test_default_horizon_survives_string_primary(self):
        """
        primary_horizon может прийти уже строкой 'h12'. Безусловное f"h{ph}" дало бы
        'hh12' — в репозитории уже был дефект ровно этого рода (осевые веса, 'hh6').
        В живых артефактах поле int, поэтому без этого теста ветка не проверена.
        """
        d = _simple(horizons=("h6", "h12"))
        d["primary_horizon"] = "h12"
        self.assertEqual(m.default_horizon(d), "h12")

    def test_default_horizon_rejects_absent_key(self):
        d = _simple(horizons=("h6", "h12"), primary=24)
        with self.assertRaises(SystemExit):
            m.default_horizon(d)


class PositionsBase(unittest.TestCase):
    """Полная база берётся из portfolio_summary.total_value_rub, а в файлах без этого блока
    (скилл его больше не пишет) — из верхнеуровневого base_value_rub."""

    def test_base_from_portfolio_summary(self):
        val, _ = m.positions_value_rub(_simple(total_value=1_000_000.0, cash_pct=2.0))
        self.assertAlmostEqual(val, 980_000.0)

    def test_base_from_base_value_rub_when_no_summary(self):
        d = _simple(total_value=1_000_000.0, cash_pct=2.0)
        del d["portfolio_summary"]
        d["base_value_rub"] = 1_000_000
        val, _ = m.positions_value_rub(d)
        self.assertAlmostEqual(val, 980_000.0)

    def test_no_base_at_all_asks_for_explicit_value(self):
        d = _simple(total_value=1_000_000.0, cash_pct=2.0)
        del d["portfolio_summary"]
        with self.assertRaises(SystemExit):
            m.positions_value_rub(d)


class PortfolioAggregation(unittest.TestCase):
    def test_diff_weights_divided_by_100_not_normalized(self):
        """
        [РАЗЛИЧИТЕЛЬ] Веса делятся на 100, а НЕ нормируются на Σ weight_pct.

        Сумма весов намеренно != 100 (50+30+19=99): при Σ=100 обе реализации
        совпадают тождественно и тест вырождается. Нормировка спрятала бы недостачу
        веса вместо того, чтобы её показать.
        """
        pos = {
            "A1": (50.0, {"h6": {"A": 10.0, "B": 0.0}}),
            "A2": (30.0, {"h6": {"A": 20.0, "B": 0.0}}),
            "A3": (19.0, {"h6": {"A": -10.0, "B": 0.0}}),
        }
        d = _stress(pos, scenarios=("A", "B"), horizons=("h6",))
        pbs = m.portfolio_by_scenario(d)
        # 0.50*10 + 0.30*20 + 0.19*(-10) = 5 + 6 - 1.9 = 9.1
        self.assertAlmostEqual(pbs["h6"]["A"], 9.1, places=9)
        # нормировка на 99 дала бы 9.1/0.99 = 9.191... — обязана не совпасть
        self.assertNotAlmostEqual(pbs["h6"]["A"], 9.1 / 0.99, places=4)

    def test_zeroed_cells_participate_as_zero(self):
        pos = {"B1": (100.0, {"h6": {"A": 0.0, "B": 5.0}})}
        d = _stress(pos, scenarios=("A", "B"), horizons=("h6",))
        self.assertEqual(m.portfolio_by_scenario(d)["h6"]["A"], 0.0)

    def test_rub_conversion(self):
        d = _simple(horizons=("h6",))
        pbs = m.portfolio_by_scenario(d)
        rub = m.portfolio_rub_by_scenario(pbs, 1_000_000.0)
        self.assertAlmostEqual(rub["h6"]["A"], 100_000.0, places=6)

    def test_missing_horizon_or_scenario_is_loud(self):
        d = _simple(horizons=("h6",))
        d["per_position"]["X"]["by_horizon"]["h6"]["delta_pct_by_scenario"].pop("C")
        with self.assertRaises(SystemExit):
            m.portfolio_by_scenario(d)


class WeightedExpectation(unittest.TestCase):
    def test_shift_moves_expectation_toward_scenario(self):
        d = _simple(horizons=("h6",))
        pbs = m.portfolio_by_scenario(d)
        even = m.weighted_expectation(pbs, {"A": .25, "B": .25, "C": .25, "D": .25})
        to_d = m.weighted_expectation(pbs, {"A": .1, "B": .1, "C": .1, "D": .7})
        self.assertGreater(to_d["h6"], even["h6"])

    def test_per_horizon_weights_give_different_answers(self):
        d = _simple(horizons=("h6", "h12"))
        pbs = m.portfolio_by_scenario(d)
        exp = m.weighted_expectation(pbs, {
            "h6": {"A": 1.0, "B": 0.0, "C": 0.0, "D": 0.0},
            "h12": {"A": 0.0, "B": 0.0, "C": 0.0, "D": 1.0}})
        self.assertAlmostEqual(exp["h6"], 10.0, places=9)
        self.assertAlmostEqual(exp["h12"], 40.0, places=9)

    def test_input_not_mutated(self):
        d = _simple(horizons=("h6",))
        before = json.dumps(d, sort_keys=True)
        m.weighted_expectation(m.portfolio_by_scenario(d), {"A": 1, "B": 0, "C": 0, "D": 0})
        self.assertEqual(json.dumps(d, sort_keys=True), before)


class Sensitivity(unittest.TestCase):
    BASE_UNEVEN = {"A": 0.4, "B": 0.3, "C": 0.2, "D": 0.1}

    def _pbs(self):
        return m.portfolio_by_scenario(_simple(horizons=("h6",)))

    def test_diff_M_is_baseline_weighted_not_plain_mean(self):
        """
        [РАЗЛИЧИТЕЛЬ] M — среднее по остальным, ВЗВЕШЕННОЕ по baseline, а не простое.

        Baseline намеренно неравный: при равных весах обе реализации тождественны, и
        различитель вырождается. Именно ради неравных весов PSS-6 и делается.
        """
        pbs = self._pbs()
        s = m.sensitivity(pbs, "D", "h6", self.BASE_UNEVEN, steps=2)
        # остальные A/B/C с весами 0.4/0.3/0.2 → доли 4/9, 3/9, 2/9
        expected_M = (4 * 10.0 + 3 * 20.0 + 2 * 30.0) / 9
        self.assertAlmostEqual(s["M"], expected_M, places=9)
        plain_mean = (10.0 + 20.0 + 30.0) / 3
        self.assertNotAlmostEqual(s["M"], plain_mean, places=4)

    def test_table_is_linear_and_slope_analytic(self):
        pbs = self._pbs()
        s = m.sensitivity(pbs, "D", "h6", self.BASE_UNEVEN, steps=7)
        vals = [r["value"] for r in s["table"]]
        deltas = [b - a for a, b in zip(vals, vals[1:])]
        for dd in deltas[1:]:
            self.assertAlmostEqual(dd, deltas[0], places=9)
        self.assertAlmostEqual(s["slope"], s["V_axis"] - s["M"], places=12)
        self.assertAlmostEqual(s["table"][0]["value"], s["M"], places=9)
        self.assertAlmostEqual(s["table"][-1]["value"], s["V_axis"], places=9)

    def test_grid_includes_both_ends(self):
        s = m.sensitivity(self._pbs(), "D", "h6", self.BASE_UNEVEN, steps=5)
        self.assertEqual(s["table"][0]["w"], 0.0)
        self.assertEqual(s["table"][-1]["w"], 1.0)
        self.assertEqual(len(s["table"]), 5)

    def test_steps_below_two_refused(self):
        with self.assertRaises(SystemExit):
            m.sensitivity(self._pbs(), "D", "h6", self.BASE_UNEVEN, steps=1)

    def test_zero_rest_baseline_refused(self):
        """Пропорции остальных неопределены — молча брать равные нельзя."""
        with self.assertRaises(SystemExit) as cm:
            m.sensitivity(self._pbs(), "D", "h6",
                          {"A": 0.0, "B": 0.0, "C": 0.0, "D": 1.0})
        self.assertIn("неопределены", str(cm.exception))

    def test_zero_axis_baseline_is_legal(self):
        """Вес самой оси в baseline не участвует: w едет 0→1 независимо от него."""
        s = m.sensitivity(self._pbs(), "D", "h6",
                          {"A": 0.5, "B": 0.3, "C": 0.2, "D": 0.0}, steps=3)
        self.assertAlmostEqual(s["baseline_w"], 0.0)
        self.assertAlmostEqual(s["V_axis"], 40.0, places=9)

    def test_unknown_scenario_or_horizon_refused(self):
        for kwargs in ({"axis_sid": "Z", "horizon": "h6"},
                       {"axis_sid": "D", "horizon": "h99"}):
            with self.assertRaises(SystemExit):
                m.sensitivity(self._pbs(), kwargs["axis_sid"], kwargs["horizon"],
                              self.BASE_UNEVEN)


class SolveFor(unittest.TestCase):
    BASE_UNEVEN = {"A": 0.4, "B": 0.3, "C": 0.2, "D": 0.1}

    def _pbs(self):
        return m.portfolio_by_scenario(_simple(horizons=("h6",)))

    def test_matches_closed_form_on_uneven_baseline(self):
        pbs = self._pbs()
        M = (4 * 10.0 + 3 * 20.0 + 2 * 30.0) / 9
        V = 40.0
        target = 25.0
        expected = (target - M) / (V - M)
        self.assertAlmostEqual(m.solve_for(pbs, "D", "h6", self.BASE_UNEVEN, target),
                               expected, places=9)

    def test_none_when_target_outside_range(self):
        self.assertIsNone(m.solve_for(self._pbs(), "D", "h6", self.BASE_UNEVEN, 999.0))

    def test_none_when_axis_equals_rest(self):
        pos = {"X": (100.0, {"h6": {"A": 7.0, "B": 7.0}})}
        pbs = m.portfolio_by_scenario(_stress(pos, scenarios=("A", "B"), horizons=("h6",)))
        self.assertIsNone(m.solve_for(pbs, "B", "h6", {"A": 0.5, "B": 0.5}, 7.0))


class BaselineSource(unittest.TestCase):
    def test_diff_reads_p_by_horizon_when_present(self):
        """
        [РАЗЛИЧИТЕЛЬ] Baseline берётся из p_by_horizon, если он есть.

        Реализация, всегда читающая скаляр p, проходит весь остальной список: живых
        артефактов с p_by_horizon нет ни одного, и без этого теста ветка не проверена.
        """
        pbh = {sid: {"h6": v, "h12": v} for sid, v in
               (("A", 0.7), ("B", 0.1), ("C", 0.1), ("D", 0.1))}
        d = _simple(horizons=("h6", "h12"), p_by_horizon=pbh)
        base, src = m.baseline_weights(d, "h6")
        self.assertAlmostEqual(base["A"], 0.7)
        self.assertIn("p_by_horizon", src)

    def test_scalar_p_when_no_block(self):
        d = _simple(horizons=("h6",), p={"A": .25, "B": .25, "C": .25, "D": .25})
        base, src = m.baseline_weights(d, "h6")
        self.assertAlmostEqual(base["A"], 0.25)
        self.assertIn("скаляр", src)

    def test_partial_block_refused(self):
        """Частично заданные убеждения смешивать со скаляром нельзя."""
        d = _simple(horizons=("h6",), p_by_horizon={"A": {"h6": 0.7}})
        with self.assertRaises(SystemExit) as cm:
            m.baseline_weights(d, "h6")
        self.assertIn("не у всех", str(cm.exception))


class WeightSumGuard(unittest.TestCase):
    def test_sum_and_tolerance_constant(self):
        pos = {"A1": (50.0, {"h6": {"A": 1.0}}), "A2": (49.0, {"h6": {"A": 1.0}})}
        d = _stress(pos, scenarios=("A",), horizons=("h6",))
        self.assertAlmostEqual(m.weight_sum(d), 99.0)
        # порог должен ловить недостачу 1 п.п.; чистое округление даёт ≤0.01
        self.assertLess(m.WEIGHT_SUM_TOLERANCE_PP, 1.0)
        self.assertGreater(m.WEIGHT_SUM_TOLERANCE_PP, 0.01)


# ───────────────────────────── CLI ─────────────────────────────

def _run_cli(*args):
    doc = args[0]
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(doc, f, allow_unicode=True); path = f.name
    try:
        r = subprocess.run([sys.executable, str(SCRIPT), "--stress", path, *args[1:]],
                           capture_output=True, text=True)
        return r
    finally:
        os.unlink(path)


@unittest.skipUnless(HAS_YAML, "требует PyYAML")
class CLI(unittest.TestCase):
    EVEN = '{"A":0.25,"B":0.25,"C":0.25,"D":0.25}'

    def test_diff_header_names_the_layer_and_bases(self):
        """
        [РАЗЛИЧИТЕЛЬ] Вывод обязан подписывать, ЧТО он посчитал.

        Реализация, считающая верно, но не печатающая слой и базу, не принимается:
        именно эта неясность приводит к подстановке ценового числа на место
        total-return — дефект уже случался в этом контуре.
        """
        r = _run_cli(_simple(horizons=("h6",)), "--weights", self.EVEN)
        self.assertEqual(r.returncode, 0, r.stderr)
        for needle in ("Слой 1", "позиционной базы", "Σ weight_pct",
                       "expected_pct_pweighted"):
            self.assertIn(needle, r.stdout)

    def test_weight_sum_warning_fires(self):
        pos = {"A1": (50.0, {"h6": {s: 1.0 for s in "ABCD"}}),
               "A2": (49.0, {"h6": {s: 1.0 for s in "ABCD"}})}
        r = _run_cli(_stress(pos, horizons=("h6",)), "--weights", self.EVEN)
        self.assertIn("Σ weight_pct отклоняется", r.stdout)

    def test_bad_sum_exits_2_and_names_the_sum(self):
        r = _run_cli(_simple(horizons=("h6",)), "--weights",
                     '{"A":0.3,"B":0.25,"C":0.25,"D":0.25}')
        self.assertEqual(r.returncode, 2)
        self.assertIn("1.050000", r.stdout + r.stderr)

    def test_bad_scenario_set_exits_2(self):
        r = _run_cli(_simple(horizons=("h6",)), "--weights", '{"A":0.5,"B":0.5}')
        self.assertEqual(r.returncode, 2)
        self.assertIn("Недостающие", r.stdout + r.stderr)

    def test_bad_horizon_set_exits_2(self):
        r = _run_cli(_simple(horizons=("h6", "h12")), "--weights",
                     '{"h6":{"A":0.25,"B":0.25,"C":0.25,"D":0.25}}')
        self.assertEqual(r.returncode, 2)
        self.assertIn("горизонтов", r.stdout + r.stderr)

    def test_target_without_sensitivity_refused(self):
        r = _run_cli(_simple(horizons=("h6",)), "--target", "5")
        self.assertEqual(r.returncode, 2)

    def test_no_mode_refused(self):
        self.assertEqual(_run_cli(_simple(horizons=("h6",))).returncode, 2)

    def test_sensitivity_prints_baseline_source(self):
        r = _run_cli(_simple(horizons=("h6",), primary=6), "--sensitivity", "D",
                     "--steps", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("источник:", r.stdout)


@unittest.skipUnless(HAS_YAML and LIVE.exists(), "нужен живой артефакт Claude-Memory")
class LiveArtifact(unittest.TestCase):
    """
    Якорь считается в РУБЛЯХ: `l1_price_only_pct` артефакта посчитан на ПОЛНОЙ базе
    (позиции + кэш), а weight_pct — на позиционной, отношение 1.03027. Сверять
    проценты напрямую нельзя.
    """
    STALE = {"RU000A1038V6": 0.8656}   # обе ноги; в артефакте опубликована одна

    def setUp(self):
        self.d = m.load_stress(LIVE)
        self.pbs = m.portfolio_by_scenario(self.d)

    def test_rub_anchor_after_correcting_known_stale_weight(self):
        """
        Расхождение с l1_price_only_delta_rub полностью объясняется одной бумагой:
        `RU000A1038V6` разложена по счетам, и в артефакте опубликован вес ОДНОЙ ноги
        (0.5358 вместо 0.8656). Движок это уже чинит (merge_holding_legs), но артефакт
        08-04 снят до фикса. После подстановки полного веса остаётся только
        округление weight_pct до 4 знаков — ≤10 ₽ на 13.4 млн.
        """
        pos_val = 13_420_790.60
        worst = 0.0
        for tkr, w in self.STALE.items():
            self.d["per_position"][tkr]["weight_pct"] = w
        pbs = m.portfolio_by_scenario(self.d)
        rub = m.portfolio_rub_by_scenario(pbs, pos_val)
        for sid, sc in self.d["scenarios"].items():
            for hk, node in sc["portfolio_level_by_horizon"].items():
                worst = max(worst, abs(rub[hk][sid] - node["l1_price_only_delta_rub"]))
        self.assertLess(worst, 10.0, f"максимум расхождения {worst:.2f} ₽")

    def test_published_artifact_trips_the_weight_guard(self):
        """Σ = 99.6701 — недостача 0.33 п.п., это ≈44 тыс ₽. Порог обязан сработать."""
        self.assertGreater(abs(m.weight_sum(self.d) - 100.0), m.WEIGHT_SUM_TOLERANCE_PP)

    def test_default_horizon_is_h12(self):
        self.assertEqual(m.default_horizon(self.d), "h12")


if __name__ == "__main__":
    unittest.main()
