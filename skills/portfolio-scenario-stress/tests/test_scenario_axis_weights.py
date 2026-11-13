#!/usr/bin/env python3
"""
Тесты канона `_shared-references/scenario_axis_weights.py` — перевод убеждений
по осям Shell-матрицы в веса сценариев, в том числе по горизонтам.

Главное, что здесь проверяется, — ПОЛЯРНОСТЬ. Перепутанный маппинг квадрантов на
id сценариев не падает и не выглядит подозрительно: он зеркалит веса, и вес войны
уезжает на разрядку. Ровно это и жило в `joint_from_axes` до 2026-08-04.

Плюс drift-контракт: канон и реализация в FCA обязаны давать одинаковые числа.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 \\
        skills/portfolio-scenario-stress/tests/test_scenario_axis_weights.py
stdlib only; живая матрица с Synology читается опционально (нет — тест пропускается).
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "_shared-references"))
sys.path.insert(0, str(REPO / "skills/forecast-confidence-applier/scripts"))

from scenario_axis_weights import (  # noqa: E402
    CANON_QUADRANT_MAPPING,
    EQUAL_WEIGHTS,
    AxisWeightsError,
    axis_beliefs_from_matrix,
    mapping_from_matrix,
    quadrant_probabilities,
    weights_by_horizon,
    weights_from_axes,
)

LIVE_MATRIX = (
    Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory"
    / "scenarios/scenario-geopolitics-ru-west-2026-07-01.yaml"
)


class TestPolarity(unittest.TestCase):
    """Канон §17 F4: A — стресс-полюс (обе оси HIGH), D — детант (обе LOW)."""

    def test_canon_mapping(self):
        self.assertEqual(CANON_QUADRANT_MAPPING["A"], ("high", "high"))
        self.assertEqual(CANON_QUADRANT_MAPPING["B"], ("high", "low"))
        self.assertEqual(CANON_QUADRANT_MAPPING["C"], ("low", "high"))
        self.assertEqual(CANON_QUADRANT_MAPPING["D"], ("low", "low"))

    @unittest.skipUnless(LIVE_MATRIX.exists(), "живая матрица недоступна")
    def test_canon_matches_live_matrix_labels(self):
        """
        Полярность выводится ИЗ ЯРЛЫКОВ матрицы, а не пересказывает константу.
        Инверсия ориентации осей в новой версии матрицы (Type-C update) должна
        ронять этот тест, а не проезжать незамеченной.
        """
        import yaml
        doc = yaml.safe_load(LIVE_MATRIX.read_text())
        meta = doc["downstream_sensitivity_hints"]["axes_meta"]
        self.assertIn("война", meta["axis_x"]["domain"]["high_label"])
        self.assertIn("перемирие", meta["axis_x"]["domain"]["low_label"])
        self.assertIn("ужесточ", meta["axis_y"]["domain"]["high_label"])
        self.assertIn("снятие", meta["axis_y"]["domain"]["low_label"])
        triggers = doc.get("scenario_triggers") or doc["matrix"]["scenario_triggers"]
        labels = {t["scenario_id"]: t["label"] for t in triggers}
        # A — обе оси HIGH: война + ужесточение; D — обе LOW
        self.assertIn("осада", labels["A"].lower())
        self.assertIn("разрядка", labels["D"].lower())

    def test_war_certain_puts_no_weight_on_detente(self):
        """Война достоверна и санкции держатся → весь вес на A, ноль на D."""
        w = weights_from_axes(1.0, 1.0)
        self.assertAlmostEqual(w["A"], 1.0, places=9)
        self.assertAlmostEqual(w["D"], 0.0, places=9)

    def test_truce_certain_puts_no_weight_on_siege(self):
        w = weights_from_axes(0.0, 0.0)
        self.assertAlmostEqual(w["D"], 1.0, places=9)
        self.assertAlmostEqual(w["A"], 0.0, places=9)

    def test_live_matrix_anchors_give_sane_ordering(self):
        """
        На якорях живой матрицы (ev_x=0.6 «война продолжается», ev_y=0.55
        «санкции единые») осада должна быть вероятнее большой сделки. При
        зеркальном маппинге вышло бы наоборот — и выглядело бы правдоподобно.
        """
        w = weights_from_axes(0.6, 0.55)
        self.assertAlmostEqual(w["A"], 0.33, places=6)
        self.assertAlmostEqual(w["B"], 0.27, places=6)
        self.assertAlmostEqual(w["C"], 0.22, places=6)
        self.assertAlmostEqual(w["D"], 0.18, places=6)
        self.assertGreater(w["A"], w["D"])


class TestQuadrantMath(unittest.TestCase):
    def test_independent_sums_to_one(self):
        q = quadrant_probabilities(0.73, 0.65, rho=0.0)
        self.assertAlmostEqual(sum(q.values()), 1.0, places=9)
        self.assertAlmostEqual(q[("high", "high")], 0.73 * 0.65, places=9)

    def test_positive_rho_moves_mass_to_same_pole_quadrants(self):
        q0 = quadrant_probabilities(0.6, 0.55, rho=0.0)
        q1 = quadrant_probabilities(0.6, 0.55, rho=0.2)
        self.assertGreater(q1[("high", "high")], q0[("high", "high")])
        self.assertGreater(q1[("low", "low")], q0[("low", "low")])
        self.assertLess(q1[("high", "low")], q0[("high", "low")])
        self.assertAlmostEqual(sum(q1.values()), 1.0, places=9)

    def test_negative_rho_moves_mass_to_mixed_quadrants(self):
        """
        `correlation-rubric.md` штатно предлагает ρ < 0. Потеря знака перебросила
        бы массу на однополюсные квадранты — переоценка крайних миров.
        """
        q0 = quadrant_probabilities(0.6, 0.55, rho=0.0)
        qm = quadrant_probabilities(0.6, 0.55, rho=-0.2)
        self.assertLess(qm[("high", "high")], q0[("high", "high")])
        self.assertLess(qm[("low", "low")], q0[("low", "low")])
        self.assertGreater(qm[("high", "low")], q0[("high", "low")])
        self.assertAlmostEqual(sum(qm.values()), 1.0, places=9)

    def test_impossible_joint_raises(self):
        with self.assertRaises(AxisWeightsError):
            quadrant_probabilities(0.9, 0.2, rho=1.0)

    def test_bad_inputs_raise(self):
        for bad in (1.5, -0.1, "0.5", None, True):
            with self.subTest(ev=bad):
                with self.assertRaises(AxisWeightsError):
                    quadrant_probabilities(bad, 0.5)
        with self.assertRaises(AxisWeightsError):
            quadrant_probabilities(0.5, 0.5, rho=2.0)

    def test_mapping_must_cover_all_quadrants(self):
        with self.assertRaises(AxisWeightsError):
            weights_from_axes(0.5, 0.5, mapping={
                "A": ("high", "high"), "B": ("high", "high"),
                "C": ("low", "high"), "D": ("low", "low")})

    def test_custom_mapping_relabels(self):
        """Матрица с другой раскладкой квадрантов задаётся явно, а не угадывается."""
        inverted = {"A": ("low", "low"), "B": ("low", "high"),
                    "C": ("high", "low"), "D": ("high", "high")}
        w = weights_from_axes(1.0, 1.0, mapping=inverted)
        self.assertAlmostEqual(w["D"], 1.0, places=9)


class TestBeliefsFromMatrix(unittest.TestCase):
    FIXTURE = {"downstream_sensitivity_hints": {"axes_meta": {
        "axis_x": {"name": "conflict_intensity",
                   "quantitative_anchor": {"low_value": 0.0, "high_value": 1.0,
                                           "modal_expected_value": 0.6}},
        "axis_y": {"name": "sanctions_intensity",
                   "quantitative_anchor": {"modal_expected_value": 0.55,
                                           "modal_expected_value_by_horizon":
                                               {"h6": 0.8, "h24": 0.45}}},
    }}}

    def test_reads_scalar_and_by_horizon(self):
        b = axis_beliefs_from_matrix(self.FIXTURE)
        self.assertEqual(b["x"]["scalar"], 0.6)
        self.assertEqual(b["x"]["by_horizon"], {})
        self.assertEqual(b["y"]["scalar"], 0.55)
        self.assertEqual(b["y"]["by_horizon"], {6: 0.8, 24: 0.45})

    def test_missing_block_is_not_a_crash(self):
        for doc in ({}, None, {"downstream_sensitivity_hints": None},
                    {"downstream_sensitivity_hints": {"axes_meta": "текст"}}):
            with self.subTest(doc=doc):
                b = axis_beliefs_from_matrix(doc)
                self.assertIsNone(b["x"]["scalar"])

    @unittest.skipUnless(LIVE_MATRIX.exists(), "живая матрица недоступна")
    def test_live_matrix_has_anchors(self):
        import yaml
        b = axis_beliefs_from_matrix(yaml.safe_load(LIVE_MATRIX.read_text()))
        self.assertIsNotNone(b["x"]["scalar"], "в матрице пропал axis_x anchor")
        self.assertIsNotNone(b["y"]["scalar"], "в матрице пропал axis_y anchor")
        w = weights_from_axes(b["x"]["scalar"], b["y"]["scalar"])
        self.assertGreater(w["A"], w["D"], "порядок сценариев перевёрнут")


class TestPolarityDeclaration(unittest.TestCase):
    """
    Канон верен для geopolitics-ru-west, но 3 из 5 живых матриц зеркальные.
    Матрица обязана объявлять полярность, иначе умолчание отдаст вес стрессового
    мира благополучному — молча.
    """

    def test_declared_polarity_read(self):
        mp = mapping_from_matrix({"matrix": {
            "polarity": {"stress_pole": "A", "detente_pole": "D"},
            "scenario_triggers": [{"scenario_id": s} for s in "ABCD"]}})
        self.assertEqual(mp["B"], ("high", "low"))
        self.assertEqual(mp["A"], ("high", "high"))
        self.assertEqual(mp["D"], ("low", "low"))

    def test_mirrored_matrix_declares_and_gets_mirrored_mapping(self):
        mp = mapping_from_matrix({"matrix": {
            "polarity": {"stress_pole": "D", "detente_pole": "A"},
            "scenario_triggers": [{"scenario_id": s} for s in "ABCD"]}})
        self.assertEqual(mp["D"], ("high", "high"))
        self.assertEqual(mp["A"], ("low", "low"))

    def test_triggers_at_top_level_also_read(self):
        """В живых файлах scenario_triggers лежит НЕ внутри matrix."""
        mp = mapping_from_matrix({
            "matrix": {"polarity": {"stress_pole": "A", "detente_pole": "D"}},
            "scenario_triggers": [{"scenario_id": s} for s in "ABCD"]})
        self.assertEqual(mp["A"], ("high", "high"))

    def test_no_polarity_with_known_triggers_is_still_none(self):
        """
        Состав сценариев известен, полярность НЕ объявлена → канон не подставляется.
        Три из пяти живых матриц зеркальные: молчаливое умолчание отдало бы вес
        стрессового мира благополучному.
        """
        self.assertIsNone(mapping_from_matrix({
            "matrix": {"axis_x": "…", "axis_y": "…"},
            "scenario_triggers": [{"scenario_id": s} for s in "ABCD"]}))

    def test_unknown_scenario_set_is_none(self):
        """Состав сценариев неизвестен — маппинг не выводим, а не угадываем."""
        self.assertIsNone(mapping_from_matrix(
            {"matrix": {"polarity": {"stress_pole": "A", "detente_pole": "D"}}}))

    def test_absent_polarity_is_none_not_canon(self):
        for doc in ({"matrix": {}}, {}, None,
                    {"matrix": {"polarity": {"stress_pole": "A", "detente_pole": "A"}}}):
            with self.subTest(doc=doc):
                self.assertIsNone(mapping_from_matrix(doc))

    def test_beliefs_report_whether_polarity_declared(self):
        b = axis_beliefs_from_matrix({"matrix": {}})
        self.assertFalse(b["polarity_declared"])
        self.assertIsNone(b["mapping"])


class TestWeightsByHorizon(unittest.TestCase):
    BELIEFS = {"x": {"scalar": 0.6, "by_horizon": {6: 0.9}},
               "y": {"scalar": 0.55, "by_horizon": {}}}

    def test_horizon_anchor_wins_over_scalar(self):
        w, notes = weights_by_horizon(self.BELIEFS, [6, 24])
        self.assertAlmostEqual(w["h6"]["A"], 0.9 * 0.55, places=6)
        self.assertAlmostEqual(w["h24"]["A"], 0.6 * 0.55, places=6)
        self.assertTrue(any("по горизонту" in n for n in notes))

    def test_y_axis_horizon_anchor_used(self):
        """Раньше все фикстуры держали by_horizon только на оси X."""
        w, _ = weights_by_horizon(
            {"x": {"scalar": 0.5, "by_horizon": {}},
             "y": {"scalar": 0.5, "by_horizon": {6: 1.0}}}, [6, 24])
        self.assertAlmostEqual(w["h6"]["A"], 0.5, places=6)     # 0.5 × 1.0
        self.assertAlmostEqual(w["h24"]["A"], 0.25, places=6)   # 0.5 × 0.5

    def test_horizon_accepts_key_form(self):
        """Горизонты ходят и как int, и как «hNN»; «hh6» — молчаливая потеря якоря."""
        w, _ = weights_by_horizon(
            {"x": {"scalar": 0.5, "by_horizon": {6: 1.0}},
             "y": {"scalar": 0.5, "by_horizon": {}}}, ["h6", 24])
        self.assertEqual(sorted(w), ["h24", "h6"])
        self.assertAlmostEqual(w["h6"]["A"], 0.5, places=6)

    def test_bad_horizon_rejected(self):
        for bad in ("шесть", "6m", None, True):
            with self.subTest(h=bad):
                with self.assertRaises(AxisWeightsError):
                    weights_by_horizon({"x": {"scalar": 0.5, "by_horizon": {}},
                                        "y": {"scalar": 0.5, "by_horizon": {}}}, [bad])

    def test_equal_fallback_respects_custom_mapping(self):
        """Иначе один блок p_by_horizon получал бы два разных набора id."""
        custom = {"S1": ("high", "high"), "S2": ("high", "low"),
                  "S3": ("low", "high"), "S4": ("low", "low")}
        w, _ = weights_by_horizon(
            {"x": {"scalar": None, "by_horizon": {}},
             "y": {"scalar": 0.5, "by_horizon": {}}}, [6], mapping=custom)
        self.assertEqual(sorted(w["h6"]), ["S1", "S2", "S3", "S4"])

    def test_missing_belief_falls_back_to_equal_and_says_so(self):
        w, notes = weights_by_horizon({"x": {"scalar": None, "by_horizon": {}},
                                       "y": {"scalar": 0.5, "by_horizon": {}}}, [12])
        self.assertEqual(w["h12"], EQUAL_WEIGHTS)
        self.assertTrue(any("равные веса" in n for n in notes))

    def test_no_interpolation_between_horizons(self):
        """
        Промежуточный горизонт не выдумывается: берётся скаляр оси. Скаляр взят
        не равным 0.5, иначе результат совпал бы с равными весами и тест не
        отличал бы «взяли скаляр» от «упали на fallback».
        """
        w, _ = weights_by_horizon(
            {"x": {"scalar": 0.8, "by_horizon": {6: 0.9, 24: 0.1}},
             "y": {"scalar": 0.5, "by_horizon": {}}}, [12])
        self.assertAlmostEqual(w["h12"]["A"], 0.4, places=6)    # 0.8×0.5
        self.assertNotAlmostEqual(w["h12"]["A"], 0.25, places=6)  # не fallback
        # интерполяция дала бы 0.5×0.5 = 0.25 при линейном (0.9+0.1)/2
        self.assertNotAlmostEqual(w["h12"]["A"], 0.5 * 0.5, places=6)

    def test_every_horizon_sums_to_one(self):
        w, _ = weights_by_horizon(self.BELIEFS, [6, 12, 24])
        for hk, weights in w.items():
            self.assertAlmostEqual(sum(weights.values()), 1.0, places=6, msg=hk)


class TestDriftAgainstFCA(unittest.TestCase):
    """
    Канон и реализация в FCA обязаны давать одинаковые веса. Две копии формулы
    в репозитории — источник расхождения конвенций; контракт его фиксирует.
    """

    def test_same_weights_on_grid(self):
        from weighted_consensus import joint_from_axes
        for ev_x in (0.0, 0.2, 0.5, 0.73, 1.0):
            for ev_y in (0.0, 0.35, 0.55, 0.9, 1.0):
                for rho in (0.0, 0.1):
                    with self.subTest(ev_x=ev_x, ev_y=ev_y, rho=rho):
                        try:
                            a = joint_from_axes(ev_x, ev_y, rho)
                        except ValueError:
                            with self.assertRaises(AxisWeightsError):
                                weights_from_axes(ev_x, ev_y, rho)
                            continue
                        b = weights_from_axes(ev_x, ev_y, rho)
                        for sid in "ABCD":
                            self.assertAlmostEqual(a[sid], b[sid], places=6, msg=sid)


if __name__ == "__main__":
    unittest.main()
