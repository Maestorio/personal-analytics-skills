#!/usr/bin/env python3
"""
trades_digest.py — отпечаток выгрузки сделок IntelInvest для поиска правок задним числом.

Зачем (PDL-RECON, 2026-10-21). Кэш-дрейф 13→16.10 (+169 тыс ₽) разбирали вручную по двум
выгрузкам: фантомное погашение Борца, автокорректировка IntelInvest −183 510 ₽, продажа
ЭталонФин5 датой 28.09, внесённая после снапшота 13.10, дубли выплат TPAY и ПГК. Каждая из
этих правок меняет строки, датированные РАНЬШЕ прошлого снапшота. Снапшот хранит итоги по
бумагам (`per_instrument_xirr`), но сравнивать их между снапшотами нельзя: их смысл менялся
между версиями загрузчика (13→16.10 «расходятся» 65 итогов на сотни тысяч). Отпечаток —
сырые строки выгрузки, сгруппированные без расчётов, поэтому не зависит от версии расчёта.

Формат (snapshot.trades_digest, ≈30 КБ):
    {"schema": "trades-digest@1", "upto": "YYYY-MM-DD", "rows": N,
     "by_ticker": {ticker: {operation: [строк, сумма, количество]}}}
Сумма — в валюте операции, как в выгрузке (без пересчёта в рубли), округление 2 знака;
количество — 6 знаков.

Сравнение (`diff`): отпечаток прошлого снапшота против отпечатка ТЕКУЩЕЙ выгрузки на ту же
дату `upto` — разница и есть строки, вставленные или удалённые задним числом.
Только stdlib.
"""
from __future__ import annotations

SCHEMA = "trades-digest@1"
PAYOUT_OPS = frozenset({"Купон", "Дивиденд", "Амортизация"})


def from_rows(rows, upto: str) -> dict:
    """rows — кортежи (дата ISO, тикер, операция, количество, сумма) — как TradesInfo.rows."""
    by: dict[str, dict[str, list]] = {}
    n = 0
    for date, ticker, op, qty, amount in rows:
        if date > upto:
            continue
        n += 1
        cell = by.setdefault(str(ticker), {}).setdefault(str(op), [0, 0.0, 0.0])
        cell[0] += 1
        cell[1] += amount or 0.0
        cell[2] += qty or 0.0
    for ops in by.values():
        for cell in ops.values():
            cell[1] = round(cell[1], 2)
            cell[2] = round(cell[2], 6)
    return {"schema": SCHEMA, "upto": upto, "rows": n, "by_ticker": by}


def rows_from_trades(trades) -> list[tuple]:
    """Trade (portfolio_returns.parse_trades) → кортежи для from_rows. Сырые строки выгрузки,
    до apply_corrections: отпечаток описывает файл, а не результат расчёта."""
    return [(t.date.isoformat(), t.ticker, t.operation, t.qty,
             round(t.amount, 2) if t.amount is not None else None) for t in trades]


def from_trades_file(path: str, upto: str) -> dict:
    from portfolio_returns import parse_trades  # noqa: WPS433
    return from_rows(rows_from_trades(parse_trades(str(path))), upto)


def diff(old: dict, new: dict, money_eps: float = 0.01) -> list[dict]:
    """Ячейки (тикер, операция), где отпечатки разошлись: Δ строк, суммы, количества."""
    out = []
    a, b = old.get("by_ticker") or {}, new.get("by_ticker") or {}
    for tk in sorted(set(a) | set(b)):
        for op in sorted(set(a.get(tk, {})) | set(b.get(tk, {}))):
            x = a.get(tk, {}).get(op, [0, 0.0, 0.0])
            y = b.get(tk, {}).get(op, [0, 0.0, 0.0])
            d_rows, d_sum, d_qty = y[0] - x[0], round(y[1] - x[1], 2), round(y[2] - x[2], 6)
            if d_rows or abs(d_sum) > money_eps or abs(d_qty) > 1e-6:
                out.append({"ticker": tk, "operation": op, "rows": d_rows, "sum": d_sum, "qty": d_qty})
    return out
