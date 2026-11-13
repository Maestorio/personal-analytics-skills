#!/usr/bin/env python3
"""Тесты бенчмарк-гейта (PME): реплей тех же потоков в MCFTR / вклад КС−1.

Офлайн: серии ставки и индекса инжектируются, сеть не нужна.
Запуск: python3 skills/portfolio-data-loader/tests/test_benchmarks.py
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from portfolio_returns import (  # noqa: E402
    replay_deposit_pme, replay_index_pme, _rate_lookup, _index_lookup,
    compute_benchmarks, xirr, Trade,
)

PASSED = FAILED = 0


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ✓ {name}")
    else:
        FAILED += 1
        print(f"  ✗ {name}  {detail}")


def daily_series(start, end, value):
    out = []
    d = start
    while d <= end:
        out.append((d.isoformat(), value))
        d += dt.timedelta(days=1)
    return out


START = dt.date(2024, 1, 1)
END = dt.date(2025, 1, 1)          # ровно 366 дней (2024 високосный)

print("== 1. Вклад: плоская ставка, без потоков — ежедневная капитализация ==")
rlook = _rate_lookup(daily_series(START, END, 11.0))   # КС 11 → вклад 10
term, neg = replay_deposit_pme(100_000.0, START, [], END, rlook, spread_pp=1.0)
expected = 100_000.0 * (1 + 0.10 / 365) ** 366
check("терминал = 100k×(1+10%/365)^366", abs(term - expected) < 1.0, f"{term:.2f} vs {expected:.2f}")
check("баланс не уходил в минус", not neg)
x = xirr([(START, -100_000.0), (END, term)])
check("XIRR ≈ эффективные ~10.5%", abs(x - (expected / 100_000.0 - 1) / (366 / 365.25)) < 0.005, f"{x:.4f}")

print("== 2. Вклад: вход и выход по знаковой конвенции subportfolio_cashflows ==")
# cf < 0 = вход в стратегию (покупка), cf > 0 = выход (продажа/купон)
term2, _ = replay_deposit_pme(0.0, START, [(START, -50_000.0)], END, rlook)
check("вход 50k в день старта растёт как вклад", abs(term2 - expected / 2) < 1.0, f"{term2:.2f}")
term3, _ = replay_deposit_pme(100_000.0, START, [(dt.date(2024, 12, 31), 50_000.0)], END, rlook)
check("выход уменьшает терминал на ~50k", abs((term - term3) - 50_000.0 * (1 + 0.10 / 365)) < 5.0,
      f"Δ={term - term3:.2f}")

print("== 3. Вклад: выходы больше накопленного — флаг минуса ==")
_, neg3 = replay_deposit_pme(10_000.0, START, [(dt.date(2024, 6, 1), 50_000.0)], END, rlook)
check("went_negative = True", neg3)

print("== 4. Индекс: плоский — терминал = initial + нетто-входы ==")
ilook = _index_lookup(daily_series(START, END, 500.0))
res = replay_index_pme(100_000.0, START, [(dt.date(2024, 3, 1), -20_000.0), (dt.date(2024, 9, 1), 30_000.0)], END, ilook)
check("плоский индекс: 100k + 20k − 30k = 90k", res is not None and abs(res[0] - 90_000.0) < 0.01,
      f"{res and res[0]}")

print("== 5. Индекс: рост ×1.2 без потоков ==")
half = dt.date(2024, 7, 1)
ser = daily_series(START, half - dt.timedelta(days=1), 500.0) + daily_series(half, END, 600.0)
ilook2 = _index_lookup(ser)
res2 = replay_index_pme(100_000.0, START, [], END, ilook2)
check("терминал = 120k", res2 is not None and abs(res2[0] - 120_000.0) < 0.01, f"{res2 and res2[0]}")

print("== 6. Индекс: вход до роста учитывает цену покупки ==")
res3 = replay_index_pme(0.0, START, [(dt.date(2024, 2, 1), -60_000.0)], END, ilook2)
check("60k по 500 → 72k по 600", res3 is not None and abs(res3[0] - 72_000.0) < 0.01, f"{res3 and res3[0]}")

print("== 7. Индекс: выход больше юнитов — флаг ==")
res4 = replay_index_pme(10_000.0, START, [(dt.date(2024, 8, 1), 50_000.0)], END, ilook2)
check("went_negative = True", res4 is not None and res4[1])

print("== 8. compute_benchmarks: структура, gap, флаги недоступности ==")
per_type = {
    "stock": {"initial_value_rub": 100_000.0, "end_value_rub": 110_000.0, "xirr": 0.0997},
    "bond":  {"initial_value_rub": 200_000.0, "end_value_rub": 210_000.0, "xirr": 0.0499},
}
blk = compute_benchmarks([], {}, START, END, per_type, set(),
                         daily_series(START, END, 11.0), daily_series(START, END, 500.0))
sv = blk["stock_vs_mcftr"]
check("stock: bench терминал = initial (плоский индекс)", abs(sv["bench_terminal_rub"] - 100_000.0) < 0.01)
check("stock: bench XIRR ≈ 0", abs(sv["bench_xirr"]) < 0.001, f'{sv["bench_xirr"]}')
check("stock: gap ≈ +10 пп (факт лучше плоского индекса)", abs(sv["gap_pp"] - 9.97) < 0.2, f'{sv["gap_pp"]}')
bv = blk["bond_vs_deposit"]
check("bond: bench XIRR ≈ 10.5% (вклад КС−1)", abs(bv["bench_xirr"] - 0.105) < 0.005, f'{bv["bench_xirr"]}')
check("bond: gap отрицательный (факт 5% хуже вклада)", bv["gap_pp"] < -4.5, f'{bv["gap_pp"]}')
check("окно записано", blk["window"] == {"start": START.isoformat(), "end": END.isoformat()})

blk2 = compute_benchmarks([], {}, START, END, per_type, set(), None, None)
check("без серий: оба None + 2 флага", blk2["stock_vs_mcftr"] is None and blk2["bond_vs_deposit"] is None
      and len(blk2["flags"]) == 2, str(blk2["flags"]))

print("== 9. Реальные потоки: XIRR факта == by_type при bench==факт ==")
# синтетика: bond-трейд внутри окна должен попасть в реплей как вход
trades = [Trade(ticker="RU000A100000", name="Тест-бонд", operation="Покупка",
                date=dt.date(2024, 3, 1), qty=10, price=100, nominal=1000, nkd=0,
                commission=0, amount=-10_000, amount_no_comm=-10_000, currency="RUB",
                note="", rub_amount=-10_000)]
tbt = {"RU000A100000": [trades[0]]}
blk3 = compute_benchmarks(trades, tbt, START, END, per_type, set(),
                          daily_series(START, END, 11.0), daily_series(START, END, 500.0))
bv3 = blk3["bond_vs_deposit"]
# вход 10k на 10 мес под ~10% добавляет к бенчмарк-терминалу ~10.85k
check("покупка из трейдов попала в реплей вклада",
      abs(bv3["bench_terminal_rub"] - (200_000.0 * (1 + 0.10/365) ** 366 + 10_000 * (1 + 0.10/365) ** 306)) < 10,
      f'{bv3["bench_terminal_rub"]:.0f}')

print(f"\nPassed: {PASSED}/{PASSED + FAILED}; Failed: {FAILED}")
sys.exit(1 if FAILED else 0)
