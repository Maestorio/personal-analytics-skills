#!/usr/bin/env python3
"""Тесты cash_reconciliation: baseline-дрейф кэша (факт vs реконструкция из трейдов).

Механика: историческое расхождение (пополнения прошлых лет вне экспорта)
фиксируется как baseline при первом снапшоте и едет дальше через prev_snapshot;
warning только когда новое расхождение отличается от baseline больше порога
(10 тыс. ₽). Осознанное изменение принимается через rebaseline_cash=True.

С 2026-07-08 actual — настоящий кэш из cash.total_rub («Имеется» вкл. ИИС −
все незаблокированные holdings), а не «грязный» балансовый остаток by_account.

Запуск: python3 skills/portfolio-data-loader/tests/test_cash_reconciliation.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from assemble_snapshot import (  # noqa: E402
    _build_cash_reconciliation, CASH_DRIFT_THRESHOLD_RUB, assemble,
)

PASSED = FAILED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ✓ {name}")
    else:
        FAILED += 1
        print(f"  ✗ {name}  {detail}")


def mk_returns(recon_cash: float, positions: list | None = None) -> dict:
    return {"snapshot_current": {
        "cash_balance_rub": recon_cash,
        "positions": positions or [],
    }}


def mk_portfolio(incl_iis: float, iis_balance: float = 0.0) -> dict:
    """Минимальный portfolio.json: метрики + пустые вкладки."""
    return {
        "metrics": {
            "total_current_rub_incl_iis": incl_iis,
            "iis_balance_rub": iis_balance,
        },
        "stocks": [], "bonds": [], "other_positions": [], "iis_positions": [],
    }


STOCK_POS = {"ticker": "SBER", "type": "stock", "qty": 100.0,
             "value_rub": 64_659.0, "currency": "RUB"}

print("== 1. Первый снапшот: baseline фиксируется, info-флаг ==")
# actual = настоящий кэш (передаётся готовым числом)
block, flag = _build_cash_reconciliation(
    mk_returns(-741_564.0), 5_335_341.0,
    prev_snapshot=None, today="2026-07-03",
)
check("блок построен", block is not None)
check("drift = actual − recon", abs(block["current_drift_rub"] - 6_076_905.0) < 1.0,
      f'{block["current_drift_rub"]}')
check("baseline = текущий drift", block["baseline_drift_rub"] == block["current_drift_rub"])
check("baseline_date = today", block["baseline_date"] == "2026-07-03")
check("delta = 0", block["delta_vs_baseline_rub"] == 0.0)
check("info-флаг cash_baseline_set", flag is not None and flag["code"] == "cash_baseline_set"
      and flag["severity"] == "info")

print("== 2. Следующий снапшот: дрейф в пределах порога — тихо ==")
prev = {"cash_reconciliation": block}
block2, flag2 = _build_cash_reconciliation(
    mk_returns(-729_000.0), 5_338_341.0,
    prev_snapshot=prev, today="2026-07-10",
)
check("baseline унаследован", block2["baseline_drift_rub"] == block["baseline_drift_rub"])
check("baseline_date унаследована", block2["baseline_date"] == "2026-07-03")
check("|delta| < порога", abs(block2["delta_vs_baseline_rub"]) < CASH_DRIFT_THRESHOLD_RUB,
      f'{block2["delta_vs_baseline_rub"]}')
check("флага нет", flag2 is None)

print("== 3. Новая дыра больше порога — warning ==")
block3, flag3 = _build_cash_reconciliation(
    mk_returns(-741_564.0), 5_335_341.0 + 450_000.0,
    prev_snapshot=prev, today="2026-07-17",
)
check("delta ≈ +150 тыс.", abs(block3["delta_vs_baseline_rub"] - 450_000.0) < 1.0)
check("warning cash_drift_changed", flag3 is not None and flag3["code"] == "cash_drift_changed"
      and flag3["severity"] == "warning")
check("baseline НЕ самозакрепился", block3["baseline_drift_rub"] == block["baseline_drift_rub"])
check("в тексте — числа и --rebaseline-cash",
      flag3 is not None and "--rebaseline-cash" in flag3["message"])

print("== 4. Ре-бейзлайн: осознанное принятие нового расхождения ==")
block4, flag4 = _build_cash_reconciliation(
    mk_returns(-741_564.0), 5_335_341.0 + 450_000.0,
    prev_snapshot=prev, today="2026-07-17", rebaseline=True,
)
check("baseline = новый drift", block4["baseline_drift_rub"] == block4["current_drift_rub"])
check("info-флаг о новом baseline", flag4 is not None and flag4["code"] == "cash_baseline_set")

print("== 5. Graceful: нет данных — блок None, без флага ==")
b, f = _build_cash_reconciliation(None, 1.0, None, "2026-07-03")
check("нет returns → None", b is None and f is None)
b, f = _build_cash_reconciliation(mk_returns(0.0), None, None, "2026-07-03")
check("нет actual-кэша → None", b is None and f is None)
b, f = _build_cash_reconciliation({"snapshot_current": {}}, 1.0, None, "2026-07-03")
check("нет cash_balance_rub → None", b is None and f is None)

print("== 6. Интеграция в assemble(): блок и флаг в снапшоте ==")
# actual считается внутри assemble: incl_iis − holdings (одна акция 64 659 ₽)
snap = assemble(
    mk_portfolio(5_400_000.0, 268_341.0),
    mk_returns(-741_564.0, positions=[STOCK_POS]),
    None, None,
)
check("actual = incl_iis − holdings",
      snap["cash_reconciliation"]["actual_cash_rub"] == 5_335_341.0,
      f'{snap["cash_reconciliation"]["actual_cash_rub"]}')
check("cash_reconciliation в снапшоте", snap.get("cash_reconciliation") is not None)
check("info-флаг в data_quality_flags",
      any(fl.get("code") == "cash_baseline_set" for fl in snap["data_quality_flags"]))
snap2 = assemble(
    mk_portfolio(5_850_000.0, 268_341.0),
    mk_returns(-741_564.0, positions=[STOCK_POS]),
    None, None,
    prev_snapshot=snap,
)
check("warning при новой дыре через assemble",
      any(fl.get("code") == "cash_drift_changed" for fl in snap2["data_quality_flags"]))
snap3 = assemble(
    mk_portfolio(5_850_000.0, 268_341.0),
    mk_returns(-741_564.0, positions=[STOCK_POS]),
    None, None,
    prev_snapshot=snap, rebaseline_cash=True,
)
check("rebaseline_cash через assemble",
      (snap3["cash_reconciliation"]["baseline_drift_rub"]
       == snap3["cash_reconciliation"]["current_drift_rub"])
      and any(fl.get("code") == "cash_baseline_set" for fl in snap3["data_quality_flags"]))

print(f"\nPassed: {PASSED}/{PASSED + FAILED}; Failed: {FAILED}")
sys.exit(1 if FAILED else 0)
