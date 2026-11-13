#!/usr/bin/env python3
"""Тесты семантики кэша и «Имеется» (фикс 2026-07-08).

Зафиксированная владельцем семантика balance-файла:
  • «Имеется (RUB)» — весь портфель ВКЛЮЧАЯ ИИС-3, БЕЗ заблокированных.
    Инвариант файла: «Итого» = «Имеется» + «Пополнение».
  • Настоящий кэш = «Имеется» − стоимость всех незаблокированных holdings.
  • «Кэш + ликвидность» (liquid_rub) = настоящий кэш + TMON/TPAY/LQDT;
    FINAMAR — не кэш ни в каком смысле, остаётся fund-позицией.
  • SBGB лежит на ИИС-3 (вкладка «Другое», Тип «RUB - ИИС») → account=iis_3.

Запуск: python3 skills/portfolio-data-loader/tests/test_cash_semantics.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from parse_portfolio import compute_metrics            # noqa: E402
from portfolio_returns import classify_instrument_type, Trade  # noqa: E402
from assemble_snapshot import (                         # noqa: E402
    _apply_iis_accounts, _build_cash, assemble,
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


# ── 1. parse_portfolio.compute_metrics: трактовка «Имеется» ──────────────────

def mk_parse_data() -> dict:
    return {
        "summary": {"Имеется (RUB)": 39_468_003.0, "ИИС": 1_731_600.0,
                    "Пополнение (RUB)": 2_531_997.0, "Итого": 42_000_000.0},
        "stocks": [
            {"Тикер": "SBER", "Название": "Сбербанк", "Стоимость": 1_500_000.0},
        ],
        "bonds": [
            {"Тип": "ОФЗ", "Текущая стоимость": 900_000.0,
             "Итого без ИИСа": 300_000.0, "Итого на ИИС": 600_000.0},
        ],
        "other_positions": [
            {"Тип": "RUB - Другое", "Бумага": "TGLD", "Стоимость": 150_000.0},
            {"Тип": "RUB - ИИС", "Бумага": "SBGB", "Стоимость": 160_215.0},
        ],
        "iis_positions": [
            {"Тип": "RUB - ИИС", "Бумага": "SBGB", "Стоимость": 160_215.0},
        ],
        "invest_era": [],
    }


print("== 1. «Имеется» = весь портфель вкл. ИИС ==")
m = compute_metrics(mk_parse_data())
check("incl_iis = Имеется как есть", m["total_current_rub_incl_iis"] == 39_468_003.0,
      f'{m["total_current_rub_incl_iis"]}')
check("excl_iis = Имеется − ИИС", m["total_current_rub_excl_iis"] == 37_736_403.0,
      f'{m["total_current_rub_excl_iis"]}')
check("legacy total_current_rub = excl_iis",
      m["total_current_rub"] == m["total_current_rub_excl_iis"])
check("by_account.main.total = excl_iis",
      m["by_account"]["main"]["total_rub"] == 37_736_403.0)
check("iis cash residual вычитает SBGB",
      m["by_account"]["iis_3"]["cash_rub"] == 1_731_600.0 - 600_000.0 - 160_215.0,
      f'{m["by_account"]["iis_3"]["cash_rub"]}')
check("iis_other_tickers содержит SBGB", m["iis_other_tickers"] == ["SBGB"])

# ── 2. classify_instrument_type: TMON и Рентал ПРО — фонды ───────────────────

print("== 2. Классификация денежных/ЗПИФ фондов ==")


def mk_trade(ticker: str, operation: str = "Покупка") -> Trade:
    import datetime as dt
    return Trade(ticker=ticker, name=ticker, operation=operation,
                 date=dt.date(2026, 1, 1), qty=1.0, price=100.0,
                 nominal=None, nkd=None, commission=0.0,
                 amount=100.0, amount_no_comm=100.0, currency="RUB", note="")


check("TMON → fund (был stock: нет дивидендов)",
      classify_instrument_type([mk_trade("TMON")]) == "fund")
check("XXXXXX (Рентал ПРО) → fund (был stock: выплаты как дивиденды)",
      classify_instrument_type([mk_trade("XXXXXX", "Дивиденд")]) == "fund")
check("обычная акция по-прежнему stock",
      classify_instrument_type([mk_trade("SBER", "Дивиденд")]) == "stock")

# ── 3. _apply_iis_accounts: SBGB → iis_3 ─────────────────────────────────────

print("== 3. SBGB переназначается на ИИС-3 ==")
holdings = [
    {"ticker": "SBGB", "account": "main", "value_rub": 160_215.0},
    {"ticker": "TPAY", "account": "main", "value_rub": 1_517_700.0},
]
_apply_iis_accounts(holdings, {"metrics": {"iis_other_tickers": ["SBGB"]}})
check("SBGB → iis_3", holdings[0]["account"] == "iis_3")
check("TPAY остался main", holdings[1]["account"] == "main")
_apply_iis_accounts(holdings, {"metrics": {}})   # graceful без списка
check("graceful без iis_other_tickers", holdings[0]["account"] == "iis_3")

# ── 4. _build_cash: настоящий кэш из «Имеется» − holdings ───────────────────

print("== 4. Настоящий кэш ==")
HOLDINGS = [
    {"ticker": "SBER", "account": "main", "status": "normal", "value_rub": 30_000_000.0},
    {"ticker": "TPAY", "account": "main", "status": "normal", "value_rub": 1_517_700.0},
    {"ticker": "TMON", "account": "main", "status": "normal", "value_rub": 838_313.28},
    {"ticker": "FINAMAR", "account": "main", "status": "normal", "value_rub": 450_000.0},
    {"ticker": "SBGB", "account": "iis_3", "status": "normal", "value_rub": 160_215.0},
    {"ticker": "RU000A1038V6", "account": "iis_3", "status": "normal", "value_rub": 1_461_384.0},
    # blocked не входит в «Имеется» и не должен вычитаться
    {"ticker": "RTX", "account": "main", "status": "blocked", "value_rub": 117_000.0},
]
PORTFOLIO = {"metrics": {
    "total_current_rub_incl_iis": 36_000_000.0,
    "iis_balance_rub": 1_731_600.0,
}}
cash, cash_flags = _build_cash(
    {"snapshot_current": {"cash_by_currency": {"RUB": -100.0}}}, PORTFOLIO, HOLDINGS,
)
expected_total = 36_000_000.0 - (30_000_000.0 + 1_517_700.0 + 838_313.28
                                 + 450_000.0 + 160_215.0 + 1_461_384.0)
check("total = Имеется − незаблокированные holdings",
      abs(cash["total_rub"] - round(expected_total, 2)) < 0.01,
      f'{cash["total_rub"]} vs {expected_total}')
check("blocked НЕ вычитается", "RTX" not in str(cash))
expected_iis = 1_731_600.0 - 160_215.0 - 1_461_384.0
check("iis_3 = ИИС − облигации ИИС − SBGB",
      abs(cash["by_account"]["iis_3"] - expected_iis) < 0.01,
      f'{cash["by_account"]["iis_3"]}')
check("main = total − iis",
      abs(cash["by_account"]["main"] - (cash["total_rub"] - expected_iis)) < 0.01)
check("by_currency из трейдов сохранён", cash["by_currency"]["RUB"] == -100.0)
check("без warning-флагов при положительном кэше", cash_flags == [])

print("== 5. Отрицательный кэш → warning cash_negative ==")
cash_neg, neg_flags = _build_cash(
    None, {"metrics": {"total_current_rub_incl_iis": 27_000_000.0,
                       "iis_balance_rub": 0.0}}, HOLDINGS,
)
check("total отрицательный", cash_neg["total_rub"] < 0)
check("warning cash_negative",
      any(f["code"] == "cash_negative" and f["severity"] == "warning"
          for f in neg_flags))

print("== 6. Graceful: нет метрик/holdings ==")
c, fl = _build_cash({"snapshot_current": {}}, None, HOLDINGS)
check("нет portfolio → total None, без флагов", c["total_rub"] is None and fl == [])
c, fl = _build_cash(None, PORTFOLIO, None)
check("нет holdings → total None", c["total_rub"] is None and fl == [])
check("by_account None при total None", c["by_account"] is None)

# ── 7. e2e assemble: liquid_rub без двойного счёта, FINAMAR вне кэша ─────────

print("== 7. e2e: liquid_rub = настоящий кэш + TMON/TPAY ==")
returns = {"snapshot_current": {
    "cash_balance_rub": -433_950.0,
    "cash_by_currency": {"RUB": -433_950.0},
    "positions": [
        {"ticker": "SBER", "type": "stock", "qty": 100.0,
         "value_rub": 30_000_000.0, "currency": "RUB"},
        {"ticker": "TPAY", "type": "fund", "qty": 100.0,
         "value_rub": 1_517_700.0, "currency": "RUB"},
        {"ticker": "TMON", "type": "fund", "qty": 100.0,
         "value_rub": 838_313.28, "currency": "RUB"},
        {"ticker": "FINAMAR", "type": "fund", "qty": 1.0,
         "value_rub": 450_000.0, "currency": "RUB"},
        {"ticker": "SBGB", "type": "fund", "qty": 10.0,
         "value_rub": 160_215.0, "currency": "RUB"},
    ],
}}
portfolio = {
    "metrics": {
        "total_current_rub_incl_iis": 36_000_000.0,
        "iis_balance_rub": 1_731_600.0,
        "iis_other_tickers": ["SBGB"],
    },
    "stocks": [{"Тикер": "SBER", "Название": "Сбербанк", "Стоимость": 30_000_000.0}],
    "bonds": [], "other_positions": [], "iis_positions": [],
}
snap = assemble(portfolio, returns, None, None)
cash = snap["cash"]
securities = 30_000_000.0 + 1_517_700.0 + 838_313.28 + 450_000.0 + 160_215.0
real_cash = round(36_000_000.0 - securities, 2)
check("cash.total_rub = настоящий кэш", cash["total_rub"] == real_cash,
      f'{cash["total_rub"]} vs {real_cash}')
check("cash_equiv = TMON + TPAY", cash["cash_equiv_rub"] == 2_356_013.28,
      f'{cash["cash_equiv_rub"]}')
check("liquid = настоящий кэш + equiv (без двойного счёта)",
      cash["liquid_rub"] == round(real_cash + 2_356_013.28, 2),
      f'{cash["liquid_rub"]}')
check("FINAMAR не в cash_equiv_tickers",
      "FINAMAR" not in cash.get("cash_equiv_tickers", {}))
sbgb = next(h for h in snap["holdings"] if h["ticker"] == "SBGB")
check("SBGB в снапшоте на iis_3", sbgb["account"] == "iis_3")
check("actual в cash_reconciliation = cash.total_rub",
      snap["cash_reconciliation"]["actual_cash_rub"] == cash["total_rub"])

print(f"\nPassed: {PASSED}/{PASSED + FAILED}; Failed: {FAILED}")
sys.exit(1 if FAILED else 0)
