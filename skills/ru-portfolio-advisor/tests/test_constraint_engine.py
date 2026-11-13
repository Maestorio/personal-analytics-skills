#!/usr/bin/env python3
"""
test_constraint_engine.py — юнит-тесты общего движка: форма среза ограничений обзора (schema.md §4.2),
verification_priority (C5), неподвижная точка сайзинга.

Запуск:
    python3 skills/ru-portfolio-advisor/tests/test_constraint_engine.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "_shared-references"))
from constraint_engine import (  # noqa: E402
    is_derived,
    slice_era,
    slice_form_errors,
    compute_verification_priority,
    compute_fixed_point_target,
)



class TestSliceForm(unittest.TestCase):
    """Срез user_constraints[] обзора (schema.md §4.2): производный, с as_of, источник — условие или план."""

    OK = {"derived": True, "as_of": "2026-11-02", "condition_id": "c1", "reason": "condition_hold",
          "status": "pending", "until": None, "summary": "условие c1: ждём"}

    def test_valid_condition_and_plan_records(self):
        plan = {"derived": True, "as_of": "2026-11-02", "plan_field": "user_plan", "plan_value": "WAIT",
                "reason": "user_plan", "summary": "план владельца"}
        self.assertEqual(slice_form_errors([self.OK, plan]), [])
        self.assertEqual(slice_form_errors([]), [])

    def test_source_exactly_one(self):
        both = dict(self.OK, plan_field="user_plan")
        none = {k: v for k, v in self.OK.items() if k != "condition_id"}
        self.assertTrue(any("ровно одно" in e for e in slice_form_errors([both])))
        self.assertTrue(any("ровно одно" in e for e in slice_form_errors([none])))
        self.assertTrue(slice_form_errors([dict(none, plan_field="note_ai")]))

    def test_field_checks(self):
        for bad, frag in ((dict(self.OK, derived=False), "derived"), (dict(self.OK, as_of="31.10.2026"), "as_of"),
                          (dict(self.OK, summary=" "), "summary"), (dict(self.OK, reason="lockup"), "block_reason"),
                          (dict(self.OK, status="done"), "status"), (dict(self.OK, until="скоро"), "until"),
                          (dict(self.OK, active=True), "не из формы")):
            errs = slice_form_errors([bad])
            self.assertTrue(any(frag in e for e in errs), (bad, errs))

    def test_legacy_records_not_checked_and_not_list(self):
        self.assertFalse(is_derived({"type": "no_buy", "active": True}))
        self.assertEqual(slice_form_errors([{"type": "no_buy", "active": True}]), [])
        self.assertTrue(slice_form_errors({"a": 1}))

    def test_slice_era(self):
        self.assertTrue(slice_era({"recorded_at": "2026-10-31T12:00:00+03:00", "review_date": "2026-10-30"}))
        self.assertFalse(slice_era({"recorded_at": "2026-10-28T00:00:00+03:00"}))
        self.assertTrue(slice_era({"review_date": "2026-11-06"}))
        self.assertFalse(slice_era({"review_date": "2026-10-16"}))
        self.assertFalse(slice_era({}))

    def test_old_engine_removed(self):
        import constraint_engine as ce
        for name in ("evaluate_constraint", "apply_constraints_to_verdict", "reconcile_entry"):
            self.assertFalse(hasattr(ce, name), name)


class TestComputeVerificationPriority(unittest.TestCase):
    def test_actionable_now_high(self):
        for v in ("BUY", "TRIM", "SELL", "ADD"):
            self.assertEqual(compute_verification_priority({"advisor_verdict": v, "advisor_verdict_confidence": 0.8}), "HIGH")

    def test_hold_unconstrained_actionable_soon_medium(self):
        # MOEX: effective HOLD, намерение TRIM под constraint'ом (отложено) → MEDIUM, не HIGH
        e = {"advisor_verdict": "HOLD", "unconstrained_verdict": "TRIM", "advisor_verdict_confidence": 0.65}
        self.assertEqual(compute_verification_priority(e), "MEDIUM")

    def test_hold_active_condition_actionable_soon_medium(self):
        # Условие с отложенным TRIM/BUY → MEDIUM (ждём дату/цену), не HIGH
        e = {"advisor_verdict": "HOLD", "advisor_verdict_confidence": 0.7}
        self.assertEqual(compute_verification_priority(e, active_condition_verdicts=["TRIM"]), "MEDIUM")

    def test_hold_gate_review_needed_high(self):
        e = {"advisor_verdict": "HOLD", "advisor_verdict_confidence": 0.7}
        self.assertEqual(compute_verification_priority(e, gate_status="review_needed"), "HIGH")
        self.assertEqual(compute_verification_priority(e, gate_status="new_position"), "HIGH")
        # R28 (03.11): «срок решения вышел» — нужен разбор → HIGH; «наблюдать» — ждёт условия, не pending
        self.assertEqual(compute_verification_priority(e, gate_status="review_aging"), "HIGH")
        self.assertEqual(compute_verification_priority(e, gate_status="reviewed_under_review"), "LOW")
        w = {"advisor_verdict": "HOLD", "advisor_verdict_confidence": 0.55}   # YDEX 28.10: HOLD / 0,55 / «наблюдать»
        self.assertEqual(compute_verification_priority(w, gate_status="reviewed_under_review"), "MEDIUM")
        self.assertEqual(compute_verification_priority(dict(e), active_condition_verdicts=["BUY"],
                                                       gate_status="reviewed_under_review"), "MEDIUM")

    def test_hold_low_conf_medium(self):
        e = {"advisor_verdict": "HOLD", "unconstrained_verdict": "HOLD", "advisor_verdict_confidence": 0.55}
        self.assertEqual(compute_verification_priority(e), "MEDIUM")

    def test_hold_hidden_critical_event_medium(self):
        e = {"advisor_verdict": "HOLD", "advisor_verdict_confidence": 0.8}
        self.assertEqual(compute_verification_priority(e, has_hidden_critical_event=True), "MEDIUM")

    def test_hold_settled_low(self):
        e = {"advisor_verdict": "HOLD", "unconstrained_verdict": "HOLD", "advisor_verdict_confidence": 0.75}
        self.assertEqual(compute_verification_priority(e, gate_status="reviewed_keep"), "LOW")

    def test_lifecycle_buy_high_then_hold_drops(self):
        # Был BUY + review_needed → HIGH
        before = {"advisor_verdict": "BUY", "advisor_verdict_confidence": 0.7}
        self.assertEqual(compute_verification_priority(before, gate_status="review_needed"), "HIGH")
        # После глубокого анализа (Mode 4) → HOLD, gate reviewed_keep → приоритет спадает
        after = {"advisor_verdict": "HOLD", "unconstrained_verdict": "HOLD", "advisor_verdict_confidence": 0.7}
        self.assertEqual(compute_verification_priority(after, gate_status="reviewed_keep"), "LOW")

    def test_rental_pro_case(self):
        # XXXXXX после разбора: HOLD, conf 0.55, gate reviewed_keep → MEDIUM (conf<0.6), НЕ HIGH
        e = {"advisor_verdict": "HOLD", "unconstrained_verdict": None, "advisor_verdict_confidence": 0.55}
        self.assertEqual(compute_verification_priority(e, gate_status="reviewed_keep"), "MEDIUM")


class TestComputeFixedPointTarget(unittest.TestCase):
    """gate-aware-sizing-spec.md §3/§6/§7 — неподвижная точка сайзинга."""

    def test_spec_case_gates_present(self):
        # §7: F=2 782 500 (весь во blocked), Open RENI 11% / MBNK 4% / X5 5.5% (S=0.205).
        r = compute_fixed_point_target(
            blocked_sum=3_785_957, dormant_sum=0,
            open_weights={"RENI": 0.11, "MBNK": 0.04, "X5": 0.055},
        )
        self.assertFalse(r["degenerate"])
        self.assertFalse(r["near_degenerate"])
        self.assertAlmostEqual(r["S"], 0.205)
        self.assertAlmostEqual(r["T_star"], 3_785_957 / 0.795, places=3)
        self.assertAlmostEqual(r["targets"]["RENI"], 523_843, delta=1)
        self.assertAlmostEqual(r["targets"]["MBNK"], 190_488, delta=1)
        self.assertAlmostEqual(r["targets"]["X5"], 261_922, delta=1)
        current = {"RENI": 508_004, "MBNK": 147_234, "X5": 247_250}
        total_buy = sum(r["targets"][t] - current[t] for t in current)
        self.assertAlmostEqual(total_buy, 73_765, delta=1)

    def test_variant_c_beats_variant_b_never_exceeds_cap(self):
        # Доказательство §3: T* всегда между L2_cur и T_full (не больше T_full),
        # поэтому вариант C никогда не даёт цели выше T_full × w_i (вариант B).
        r = compute_fixed_point_target(
            blocked_sum=3_785_957, dormant_sum=0,
            open_weights={"RENI": 0.11, "MBNK": 0.04, "X5": 0.055},
        )
        T_full = 5_771_609
        self.assertLess(r["T_star"], T_full)
        for ticker, w in {"RENI": 0.11, "MBNK": 0.04, "X5": 0.055}.items():
            self.assertLess(r["targets"][ticker], w * T_full)

    def test_dormant_included_in_f_without_distorting_gap(self):
        # §3.2: Dormant на таргете не создаёт разрыва T_full − T* сверх Blocked-компоненты.
        blocked_only = compute_fixed_point_target(
            blocked_sum=1_000_000, dormant_sum=0, open_weights={"A": 0.2},
        )
        blocked_plus_dormant_at_target = compute_fixed_point_target(
            blocked_sum=1_000_000, dormant_sum=500_000, open_weights={"A": 0.2},
        )
        # Добавление dormant_sum увеличивает F и, следовательно, T* пропорционально —
        # разрыв не "прячется", просто база больше.
        self.assertGreater(blocked_plus_dormant_at_target["T_star"], blocked_only["T_star"])

    def test_selling_ticker_excluded_manually_not_a_function_concern(self):
        # §3.3: функция ничего не знает о Selling-тикерах — вызывающий код обязан
        # исключить их сумму из blocked_sum/dormant_sum/open_weights до вызова.
        # Здесь просто фиксируем: F/S не включают такую сумму, если её не передали.
        r = compute_fixed_point_target(
            blocked_sum=1_000_000, dormant_sum=200_000, open_weights={"A": 0.1},
        )
        self.assertAlmostEqual(r["T_star"], 1_200_000 / 0.9)

    def test_degenerate_no_blocked_tickers(self):
        # §3.1 / §7 второй кейс: blocked_sum=0 → degenerate=True, без деления.
        r = compute_fixed_point_target(
            blocked_sum=0, dormant_sum=900_000, open_weights={"A": 0.1, "B": 0.05},
        )
        self.assertTrue(r["degenerate"])
        self.assertFalse(r["near_degenerate"])
        self.assertIsNotNone(r["T_star"])
        expected_t_full = 900_000 / (1 - 0.15)
        self.assertAlmostEqual(r["T_star"], expected_t_full)
        self.assertAlmostEqual(r["targets"]["A"], 0.1 * expected_t_full)
        self.assertAlmostEqual(r["targets"]["B"], 0.05 * expected_t_full)

    def test_degenerate_no_blocked_no_dormant_no_open(self):
        r = compute_fixed_point_target(blocked_sum=0, dormant_sum=0, open_weights={})
        self.assertTrue(r["degenerate"])
        self.assertEqual(r["S"], 0.0)
        self.assertEqual(r["T_star"], 0.0)
        self.assertEqual(r["targets"], {})

    def test_near_degenerate_s_close_to_one_no_number_invented(self):
        # (1 - S) < 0.01 → near_degenerate: true, T_star/targets НЕ считаются.
        r = compute_fixed_point_target(
            blocked_sum=500_000, dormant_sum=0,
            open_weights={"A": 0.5, "B": 0.495},  # S = 0.995
        )
        self.assertTrue(r["near_degenerate"])
        self.assertIsNone(r["T_star"])
        self.assertEqual(r["targets"], {})

    def test_s_equal_or_above_one_raises(self):
        with self.assertRaises(ValueError):
            compute_fixed_point_target(
                blocked_sum=100, dormant_sum=0, open_weights={"A": 0.6, "B": 0.4},
            )
        with self.assertRaises(ValueError):
            compute_fixed_point_target(
                blocked_sum=100, dormant_sum=0, open_weights={"A": 0.6, "B": 0.5},
            )

    def test_extra_cash_from_sales_does_not_move_t_star(self):
        without = compute_fixed_point_target(
            blocked_sum=1_000_000, dormant_sum=0, open_weights={"A": 0.2},
        )
        with_cash = compute_fixed_point_target(
            blocked_sum=1_000_000, dormant_sum=0, open_weights={"A": 0.2},
            extra_cash_from_sales=250_000,
        )
        self.assertAlmostEqual(without["T_star"], with_cash["T_star"])
        self.assertEqual(with_cash["targets"], with_cash["targets"])
        self.assertEqual(with_cash["cash_available_for_open"], 250_000)
        self.assertEqual(without["cash_available_for_open"], 0.0)

    def test_t_full_caps_t_star(self):
        # F выше своей доли: T* = 1.2M/0.88 > T_full = 1M → база = T_full, capped
        r = compute_fixed_point_target(
            blocked_sum=1_200_000, dormant_sum=0, open_weights={"A": 0.12}, t_full=1_000_000,
        )
        self.assertTrue(r["capped"])
        self.assertAlmostEqual(r["T_star"], 1_000_000)
        self.assertAlmostEqual(r["targets"]["A"], 120_000)
        # обычный случай: предел не срабатывает
        r2 = compute_fixed_point_target(
            blocked_sum=400_000, dormant_sum=0, open_weights={"A": 0.2}, t_full=1_000_000,
        )
        self.assertFalse(r2["capped"])
        self.assertAlmostEqual(r2["T_star"], 500_000)
        # без t_full — как раньше
        r3 = compute_fixed_point_target(blocked_sum=1_200_000, dormant_sum=0, open_weights={"A": 0.12})
        self.assertFalse(r3["capped"])
        self.assertAlmostEqual(r3["T_star"], 1_200_000 / 0.88)

    def test_frozen_over_plan_stays_in_f(self):
        # §10.7 (11.11): перевод перевешенной заморозки «на план» отменён — её рубли в F, как у любой неторгуемой;
        # параметров frozen_plans/book_rub больше нет (база = книга после исполнения)
        import inspect
        params = inspect.signature(compute_fixed_point_target).parameters
        self.assertNotIn("frozen_plans", params)
        self.assertNotIn("book_rub", params)
        r = compute_fixed_point_target(blocked_sum=50_000, dormant_sum=200_000, open_weights={"K": 0.24},
                                       t_full=1_000_000, full_plan_without_gates=False)
        self.assertAlmostEqual(r["T_star"], 250_000 / 0.76)
        self.assertNotIn("frozen_at_plan", r)
        # книга после идеального исполнения = база: F + K·T* = T*
        self.assertAlmostEqual(250_000 + 0.24 * r["T_star"], r["T_star"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
