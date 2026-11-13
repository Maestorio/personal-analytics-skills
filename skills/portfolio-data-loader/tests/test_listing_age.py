#!/usr/bin/env python3
"""Тесты listing_date / listing_age_quarters (IPO-гейт, правило 23 advisor).

Возраст листинга в полных кварталах из listing_from (первый торговый день
на MOEX, moex_quotes weekly). Порог гейта (8 кварталов) живёт в advisor —
здесь только детерминированная арифметика и прокладка в holdings.

Запуск: python3 skills/portfolio-data-loader/tests/test_listing_age.py
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from assemble_snapshot import _listing_fields, _build_stocks  # noqa: E402

PASSED = FAILED = 0


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ✓ {name}")
    else:
        FAILED += 1
        print(f"  ✗ {name}  {detail}")


TODAY = dt.date(2026, 7, 3)

print("== 1. Арифметика кварталов ==")
r = _listing_fields({"listing_from": "2024-10-01"}, TODAY)   # 640 дней
check("DATA (IPO 2024-10): 7 кварталов — под гейтом", r["listing_age_quarters"] == 7, str(r))
r = _listing_fields({"listing_from": "2024-06-04"}, TODAY)   # 759 дней
check("IVAT (IPO 2024-06): 8 кварталов — ровно на границе", r["listing_age_quarters"] == 8, str(r))
r = _listing_fields({"listing_from": "2011-11-21"}, TODAY)
check("SBER: 58 кварталов", r["listing_age_quarters"] == 58, str(r))
check("listing_date проброшена", r["listing_date"] == "2011-11-21")

print("== 2. Graceful: нет/битая дата ==")
r = _listing_fields({})
check("нет listing_from → оба null", r == {"listing_date": None, "listing_age_quarters": None})
r = _listing_fields({"listing_from": "не-дата"})
check("битая дата → оба null", r == {"listing_date": None, "listing_age_quarters": None})
r = _listing_fields({"listing_from": "2030-01-01"}, TODAY)
check("дата в будущем → 0 кварталов (не отрицательное)", r["listing_age_quarters"] == 0, str(r))

print("== 3. Прокладка в holdings через _build_stocks ==")
returns = {"snapshot_current": {"positions": [
    {"ticker": "DATA", "type": "stock", "qty": 100, "value_rub": 7692.0,
     "is_blocked": False, "currency": "RUB"},
]}}
quotes = {"DATA": {"last": 76.92, "isin": "RU000A107K42", "listing_from": "2024-10-01",
                   "kind": "share", "timestamp": "2026-07-03T12:00:00"}}
holdings, _fl = _build_stocks({}, returns, quotes)
h = next(x for x in holdings if x["ticker"] == "DATA")
check("holding.listing_date из котировки", h["listing_date"] == "2024-10-01")
check("holding.listing_age_quarters посчитан", isinstance(h["listing_age_quarters"], int)
      and h["listing_age_quarters"] >= 7, str(h["listing_age_quarters"]))
quotes_no = {"DATA": {"last": 76.92, "kind": "share"}}
holdings2, _ = _build_stocks({}, returns, quotes_no)
h2 = next(x for x in holdings2 if x["ticker"] == "DATA")
check("без listing_from → null-поля присутствуют", h2["listing_date"] is None
      and h2["listing_age_quarters"] is None)

print("== 4. Лот MOEX в holdings (2026-10-13: вьюер считает лоты как gate_aware_sizing) ==")
quotes_lot = {"DATA": {"last": 76.92, "kind": "share", "lot_size": 10}}
h3 = next(x for x in _build_stocks({}, returns, quotes_lot)[0] if x["ticker"] == "DATA")
check("lot_size из котировки", h3["lot_size"] == 10, str(h3.get("lot_size")))
check("нет lot_size → null", h2.get("lot_size", "missing") is None, str(h2.get("lot_size", "missing")))
h4 = next(x for x in _build_stocks({}, returns, {"DATA": {"last": 1, "lot_size": "0"}})[0] if x["ticker"] == "DATA")
check("лот 0/битый → null", h4["lot_size"] is None)

print(f"\nPassed: {PASSED}/{PASSED + FAILED}; Failed: {FAILED}")
sys.exit(1 if FAILED else 0)
