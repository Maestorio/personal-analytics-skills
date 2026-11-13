#!/usr/bin/env python3
"""
bond_avg_price.py — средняя цена покупки облигации по сделкам (отдельно основной счёт и ИИС-3).

Правило учёта то же, что у фондов и акций в загрузчике (portfolio_returns.reconstruct_positions):
средневзвешенная (WACC) — продажа списывает бумаги по средней цене и сама среднюю не меняет, поэтому
«частичная продажа» оставляет avg_price_pct прежним; докупка по другой цене сдвигает его на вес докупки.
  avg_price_pct — % номинала, чистая цена (без НКД и комиссии): Σ(кол-во × цена) / Σ кол-во;
  avg_cost_rub  — ₽ за бумагу без НКД: цена × номинал сделки (в ₽ по курсу ЦБ на дату сделки, если сделка
                  в валюте); нет цены/номинала в сделке — «Сумма без комиссии» / кол-во и avg_includes_accint=true
                  (НКД в такой цене сидит, avg_price_pct тогда null).
Выгрузка основного счёта несёт и сделки ИИС-3 (сумма двух счетов), поэтому сделки ИИС-3 из неё вычитаются
(subtract_trades: ключ тикер · операция · дата · кол-во · цена).
Корректировки (операция «Корректировка») не учитываются — у них нет цены.
Только stdlib; Trade — из portfolio_returns.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

QTY_EPS = 1e-9


def _trade_key(t: Any) -> tuple:
    return (t.ticker, t.operation, str(t.date), round(float(t.qty or 0.0), 6),
            round(float(t.price), 6) if t.price is not None else None)


def subtract_trades(main: Iterable[Any], other: Iterable[Any]) -> list[Any]:
    """Сделки основной выгрузки без тех, что есть в выгрузке другого счёта (мультимножество по ключу)."""
    left = Counter(_trade_key(t) for t in other if t.operation in ("Покупка", "Продажа"))
    out = []
    for t in main:
        if t.operation in ("Покупка", "Продажа"):
            k = _trade_key(t)
            if left.get(k, 0) > 0:
                left[k] -= 1
                continue
        out.append(t)
    return out


def bond_avg_prices(trades: Iterable[Any]) -> dict[str, dict]:
    """Тикер сделок → {qty, avg_price_pct, avg_cost_rub, avg_cost_currency, avg_includes_accint, name}
    для открытых позиций (qty > 0). Ожидает Trade в хронологическом порядке (parse_trades сортирует)."""
    acc: dict[str, dict] = {}
    for t in trades:
        if t.operation not in ("Покупка", "Продажа"):
            continue
        q = float(t.qty or 0.0)
        if q <= 0:
            continue
        a = acc.setdefault(t.ticker, {"qty": 0.0, "pct": 0.0, "rub": 0.0, "native": 0.0, "cur": t.currency,
                                      "rub_ok": True, "pct_ok": True, "accint": False, "name": t.name})
        if t.operation == "Продажа":
            if a["qty"] <= QTY_EPS:
                continue
            k = max(a["qty"] - q, 0.0) / a["qty"]
            for f in ("qty", "pct", "rub", "native"):
                a[f] *= k
            continue
        rate = float(getattr(t, "rub_rate", 0.0) or 0.0)
        if t.currency == "RUB":
            rate = 1.0
        a["qty"] += q
        if t.price is not None and t.nominal:
            a["pct"] += q * float(t.price)
            native = q * float(t.price) / 100.0 * float(t.nominal)
        else:
            a["pct_ok"] = False
            a["accint"] = True
            native = float(t.amount_no_comm or 0.0)
        a["native"] += native
        if rate > 0:
            a["rub"] += native * rate
        else:
            a["rub_ok"] = False
        a["cur"] = t.currency
    out: dict[str, dict] = {}
    for tk, a in acc.items():
        if a["qty"] <= QTY_EPS:
            continue
        out[tk] = {
            "qty": round(a["qty"], 6),
            "avg_price_pct": round(a["pct"] / a["qty"], 4) if a["pct_ok"] else None,
            "avg_cost_rub": round(a["rub"] / a["qty"], 4) if a["rub_ok"] else None,
            "avg_cost_currency": a["cur"],
            "avg_includes_accint": bool(a["accint"]),
            "name": a["name"],
        }
    return out


def match_holding(avgs: dict[str, dict], holding: dict, secid_by_isin: dict[str, list[str]]) -> dict | None:
    """Запись средней для холдинга: тикер или ISIN холдинга, SECID из справочника по ISIN, затем имя."""
    isin, ticker = holding.get("isin"), holding.get("ticker")
    for k in [ticker, isin, *(secid_by_isin.get(isin or "", []))]:
        if k and k in avgs:
            return avgs[k]
    nm = holding.get("name")
    if nm:
        hits = [v for v in avgs.values() if v.get("name") == nm]
        if len(hits) == 1:
            return hits[0]
    return None


def secid_index(types_data: dict | None) -> dict[str, list[str]]:
    """ISIN → SECID-ы справочника (ОФЗ торгуются под SU…, в холдингах — ISIN)."""
    out: dict[str, list[str]] = {}
    for tk, e in ((types_data or {}).get("by_ticker") or {}).items():
        if isinstance(e, dict) and e.get("isin"):
            out.setdefault(e["isin"], []).append(tk)
    return out


def apply_bond_avg(holdings: list[dict], main_avgs: dict[str, dict] | None, iis_avgs: dict[str, dict] | None,
                   types_data: dict | None) -> int:
    """Пишет avg_price_pct / avg_cost_rub / avg_cost_source / avg_includes_accint в облигации-холдинги.
    → число облигаций, получивших среднюю."""
    idx = secid_index(types_data)
    n = 0
    for h in holdings:
        if h.get("asset_type") != "bond":
            continue
        src = iis_avgs if h.get("account") == "iis_3" else main_avgs
        if src is None:
            continue
        rec = match_holding(src, h, idx)
        if rec is None:
            continue
        h["avg_price_pct"] = rec["avg_price_pct"]
        h["avg_cost_rub"] = rec["avg_cost_rub"]
        h["avg_cost_source"] = "trades"
        h["avg_includes_accint"] = rec["avg_includes_accint"]
        n += 1
    return n


def compact_trades(trades: Iterable[Any]) -> list[list]:
    """Покупки/продажи в компактном виде для передачи между шагами сборки (iis_returns → assemble):
    [тикер, операция, дата, кол-во, цена, номинал, валюта, курс, сумма без комиссии, название]."""
    out = []
    for t in trades:
        if t.operation in ("Покупка", "Продажа") and not getattr(t, "is_synthetic", False):
            out.append([t.ticker, t.operation, str(t.date), t.qty, t.price, t.nominal, t.currency,
                        getattr(t, "rub_rate", 1.0), t.amount_no_comm, t.name])
    return out


def expand_trades(rows: Iterable[list]) -> list[Any]:
    """Обратное compact_trades → Trade (поля, нужные учёту средней)."""
    import datetime as dt
    from portfolio_returns import Trade
    out = []
    for r in rows or []:
        tk, op, d, q, p, nom, cur, rate, anc, nm = r
        t = Trade(ticker=tk, name=nm or "", operation=op, date=dt.date.fromisoformat(d), qty=q, price=p,
                  nominal=nom, nkd=None, commission=0.0, amount=anc or 0.0, amount_no_comm=anc or 0.0,
                  currency=cur or "RUB", note="")
        t.rub_rate = float(rate or 0.0)
        out.append(t)
    return out
