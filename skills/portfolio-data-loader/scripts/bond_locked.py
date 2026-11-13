#!/usr/bin/env python3
"""
bond_locked.py — «При покупке» (зафиксированная доходность к погашению) в holding'ах облигаций.

locked_pct = IRR(исторические потоки счёта по этой бумаге + будущие купоны/погашения по графику MOEX
(bondization) на текущее количество счёта). У линкеров ещё locked_real_pct (будущие потоки без индексации).
Расчёт один на оба счёта — iis_returns.locked_for:
  · ИИС-3 — строка returns.by_account.iis_3.per_bond (её считает iis_returns по выгрузке счёта) → в holding;
  · основной — потоки счёта = суммарные потоки бумаги (per_security.cashflows без терминала) минус потоки
    ИИС-3 (iis_account_flows), тем же вычитанием, что даёт per_instrument_xirr.by_account.
Нет графика / сети / потоков счёта → поле null, без шума в checks.
Только stdlib; сеть — только через переданный fetch (assemble передаёт iis_returns.fetch_schedule).
"""
from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any, Callable


def _cents(a: float) -> int:
    return int(round(float(a) * 100))


def account_counters(cfs: list | None, mv: float | None, iis_cashflows: list | None,
                     as_of: str | None) -> tuple[Counter, Counter] | None:
    """Потоки (дата, центы) основного счёта и ИИС-3 из суммарных потоков бумаги, без терминала.

    cfs — per_security.cashflows (в конце терминал: as_of, +market_value); iis_cashflows — потоки ИИС-3
    по той же бумаге. Любая нестыковка (терминала или потока ИИС-3 нет в суммарных) → None.
    """
    if not cfs or not as_of or mv is None:
        return None
    total = Counter((str(d)[:10], _cents(a)) for d, a in cfs)
    if mv > 0:
        term = (str(as_of)[:10], _cents(mv))
        if total.get(term, 0) <= 0:
            return None
        total[term] -= 1
    iis_c = Counter((str(d)[:10], _cents(a)) for d, a in (iis_cashflows or []))
    main_c = total - iis_c
    if sum(iis_c.values()) != sum((total & iis_c).values()) or not main_c:
        return None
    return main_c, iis_c


def counter_flows(counter: Counter) -> list[tuple[dt.date, float]]:
    return sorted((dt.date.fromisoformat(d), c / 100.0) for (d, c), n in counter.items() for _ in range(n))


def _ticker_of(h: dict, per_instrument: dict | None) -> str:
    """SECID бумаги: у ОФЗ холдинг стоит под ISIN, запись per_instrument_xirr несёт alias_of."""
    tk = str(h.get("ticker") or "")
    return str((per_instrument or {}).get(tk, {}).get("alias_of") or tk)


def apply_locked(
    holdings: list[dict] | None, *, as_of: str, per_security: dict | None, per_instrument: dict | None,
    iis_flows: dict | None, iis_per_bond: list[dict] | None,
    fetch: Callable[[str], dict] | None, infl: dict | None,
) -> int:
    """Пишет locked_pct (+ locked_real_pct у линкеров) в облигации-холдинги обоих счетов. → число заполненных.

    fetch=None — основной счёт не трогается (нет сети); ИИС-3 берётся из per_bond без сети.
    """
    import iis_returns as ir
    n = 0
    if not holdings:
        return n
    asof_d = dt.date.fromisoformat(str(as_of)[:10])
    infl = infl or {"source": "fallback", "path": [], "flat_pct": ir.DEFAULT_INFLATION_PCT}
    iis_rows = [r for r in iis_per_bond or [] if isinstance(r, dict)]
    schedules: dict[str, dict | None] = {}

    def _schedule(secid: str) -> dict | None:
        if secid not in schedules:
            try:
                sch = fetch(secid) if fetch else None
            except Exception:                                                      # noqa: BLE001 — сети нет = поля null
                sch = None
            schedules[secid] = sch if sch and (sch.get("coupons") or sch.get("amortizations")) else None
        return schedules[secid]

    def _iis_qty(ticker: str, isin: str | None) -> float:
        return sum(float(x.get("qty") or 0.0) for x in holdings
                   if x.get("account") == "iis_3" and x.get("asset_type") == "bond"
                   and (x.get("ticker") == ticker or (isin and x.get("isin") == isin)))

    for h in holdings:
        if h.get("asset_type") != "bond" or h.get("status") == "blocked" or not (float(h.get("qty") or 0) > 0):
            continue
        if h.get("account") == "iis_3":
            row = next((r for r in iis_rows if r.get("secid") in (h.get("ticker"),) or
                        (h.get("isin") and r.get("isin") == h.get("isin"))), None)
            h["locked_pct"] = row.get("locked_pct") if row else None
            if row and row.get("linker"):
                h["locked_real_pct"] = row.get("locked_real_pct")
            n += h["locked_pct"] is not None
            continue
        if fetch is None:
            continue
        secid = _ticker_of(h, per_instrument)
        h["locked_pct"] = None
        data = (per_security or {}).get(secid)
        sch = _schedule(secid)
        if not isinstance(data, dict) or not sch:
            continue
        iis_t = (iis_flows or {}).get(secid) or {}
        if not iis_t and _iis_qty(h.get("ticker"), h.get("isin")) > 0:
            continue                                      # бумага и на ИИС-3, а потоков ИИС-3 нет — вычесть нечего
        ctr = account_counters(data.get("cashflows"), _num(data.get("market_value_rub")),
                               iis_t.get("cashflows"), as_of)
        if ctr is None:
            continue
        lk = ir.locked_for(sch, str(h.get("name") or ""), float(h["qty"]), asof_d, infl, counter_flows(ctr[0]))
        h["locked_pct"] = lk["locked_pct"]
        if lk["linker"]:
            h["locked_real_pct"] = lk.get("locked_real_pct")
        n += h["locked_pct"] is not None
    return n


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) else None
