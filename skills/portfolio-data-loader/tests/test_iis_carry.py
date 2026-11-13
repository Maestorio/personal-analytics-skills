#!/usr/bin/env python3
"""Перенос returns.by_account.iis_3 без новой выгрузки (2026-10-13).
Запуск: python3 skills/portfolio-data-loader/tests/test_iis_carry.py"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import assemble_snapshot as A  # noqa: E402


def _blk(status="ok", **kw):
    b = {"broker": "БКС", "source_file": "trades_portfolio_838526.xlsx",
         "file_last_operation": "2026-09-23", "status": status, "reconciliation": [],
         "fact": {"xirr": 0.0077}, "forward": {"account_pct": 14.3}}
    b.update(kw)
    return b


def _snap(date, blk=None, qty=180.0):
    return {"as_of_date": date,
            "returns": {"by_account": {"iis_3": blk}} if blk else {"by_account": {}},
            "holdings": [{"ticker": "SU52004RMFS7", "isin": "RU000A103MX5",
                          "account": "iis_3", "qty": qty}]}


HOLD = _snap("x")["holdings"]


class TestCarry(unittest.TestCase):
    def test_carries_from_first_with_block(self):
        srcs = [_snap("2026-10-13", _blk()), _snap("2026-10-12", _blk(fact={"xirr": 9}))]
        b, flags = A._carry_iis_block(srcs, HOLD)
        self.assertEqual(b["carried_from"], "2026-10-13")
        self.assertEqual(b["carried_reason"], "нет новой выгрузки ИИС-3")
        self.assertEqual(b["fact"]["xirr"], 0.0077)
        self.assertEqual([f["code"] for f in flags], ["iis_returns_carried"])
        self.assertEqual(flags[0]["severity"], "info")

    def test_skips_missing_and_mismatch(self):
        srcs = [_snap("2026-10-13"), _snap("2026-10-12", {"status": "mismatch"}),
                _snap("2026-10-11", _blk())]
        b, _ = A._carry_iis_block(srcs, HOLD)
        self.assertEqual(b["carried_from"], "2026-10-11")

    def test_chain_keeps_original_date(self):
        srcs = [_snap("2026-10-14", _blk(carried_from="2026-10-13"))]
        b, _ = A._carry_iis_block(srcs, HOLD)
        self.assertEqual(b["carried_from"], "2026-10-13")

    def test_composition_changed_warns_but_carries(self):
        cur = [{"ticker": "SU52004RMFS7", "isin": "RU000A103MX5", "account": "iis_3", "qty": 200.0}]
        b, flags = A._carry_iis_block([_snap("2026-10-13", _blk(), qty=180.0)], cur)
        self.assertIsNotNone(b)
        codes = {f["code"]: f["severity"] for f in flags}
        self.assertEqual(codes["iis_composition_changed"], "warn")

    def test_same_composition_no_warn(self):
        _, flags = A._carry_iis_block([_snap("2026-10-13", _blk())], HOLD)
        self.assertNotIn("iis_composition_changed", [f["code"] for f in flags])

    def test_no_source(self):
        self.assertEqual(A._carry_iis_block([_snap("2026-10-13")], HOLD), (None, []))
        self.assertEqual(A._carry_iis_block(None, HOLD), (None, []))

    def test_assemble_wiring(self):
        ret = {"snapshot_current": {"positions": []}, "fx_rates_asof": {}}
        snap = A.assemble({"stocks": [], "bonds": [], "other_positions": []}, ret, None, {},
                          iis_carry_sources=[_snap("2026-10-13", _blk())])
        self.assertEqual(snap["returns"]["by_account"]["iis_3"]["carried_from"], "2026-10-13")
        self.assertIn("iis_returns_carried", [f["code"] for f in snap["data_quality_flags"]])


if __name__ == "__main__":
    unittest.main(verbosity=1)
