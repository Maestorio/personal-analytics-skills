#!/usr/bin/env python3
"""
weekly_changes.py — недельные изменения цен, книги и индексов по закрытиям MOEX ISS (RPA-28).

Зачем. Аудит обзоров 01.10–16.10.2026: утренние цены снапшота подавались как «закрытие прошлого
дня», а индекс сравнивался по закрытиям. Итог — YDEX «−4,1% за неделю» вместо −7,2%, книга
«отстала от IMOEX на 0,3 пп» вместо ≈1,2 пп, в обзоре 08.10 знак сравнения перевёрнут, цены ОФЗ
с подписью «16.10 ~12:15» на деле закрытие 15.10 (inc-2026-10-16-1, inc-2026-10-20-1/-3).
Скрипт считает всё по закрытиям ISS обеих дат и сам ставит честную метку среза; модель берёт
числа и подписи только из его вывода.

Что считает:
- акции (TQBR) и облигации (любая доска с ценой; приоритет TQOB/TQCB/TQOD/TQIR) — закрытие на
  начало и конец окна, Δ%; у облигаций ещё доходность закрытия и Δ в б.п.;
- книгу акций при неизменных количествах из снапшота: Σ qty × close_end / Σ qty × close_start − 1;
- IMOEX и RGBI — Δ% и максимум/минимум закрытия внутри окна (для утверждений «впервые с …»
  нужна более длинная история — `--from` раньше);
- метка среза: фактические даты закрытий, которые попали в расчёт.

Окно: `--from` — дата базы (берётся закрытие этой даты или последнего торгового дня ДО неё),
`--to` — конец (закрытие этой даты или последнего торгового дня до неё). Для обзора, который
пишется утром 16.10 до закрытия, конец — 15.10, и метка так и скажет.

CLI:
  python3 weekly_changes.py --snapshot portfolio-2026-10-16.json --from 2026-10-07 --to 2026-10-15
  python3 weekly_changes.py --snapshot ... --from ... --to ... --kind stock   # только акции+IMOEX
Выход — JSON в stdout. Сеть нужна (ISS); без сети — честная ошибка по каждой бумаге.
Зависимости: только stdlib.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import urllib.request
from datetime import date, timedelta

ISS = "https://iss.moex.com/iss/history/engines/stock/markets"
BOND_BOARD_PRIORITY = ("TQOB", "TQCB", "TQOD", "TQIR", "TQOE", "TQOY")
INDICES = ("IMOEX", "RGBI")


def _http_json(url: str, timeout: int = 30, retries: int = 3) -> dict:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
            raw = urllib.request.urlopen(req, timeout=timeout).read()
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass
            return json.loads(raw)
        except Exception as exc:  # ISS иногда рвёт соединение — повтор с паузой
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise last


def resolve_secid(isin: str, fetch=_http_json) -> str | None:
    """ISIN → код ISS. ОФЗ в истории ISS живут под SU…RMFS…, а не под ISIN."""
    data = fetch(f"https://iss.moex.com/iss/securities.json?q={isin}&iss.meta=off"
                 f"&securities.columns=secid,isin")
    for secid, row_isin in data["securities"]["data"]:
        if row_isin == isin:
            return secid
    return None


def fetch_history(market: str, secid: str, d_from: date, d_to: date, fetch=_http_json) -> list[dict]:
    """Строки истории [{date, board, close, yield}] за [d_from, d_to]; доски — как есть."""
    cols = "TRADEDATE,BOARDID,CLOSE"
    if market == "bonds":
        cols += ",YIELDCLOSE"
    url = (f"{ISS}/{market}/securities/{secid}.json?from={d_from.isoformat()}"
           f"&till={d_to.isoformat()}&iss.meta=off&history.columns={cols}")
    rows, start = [], 0
    while True:
        data = fetch(url + f"&start={start}")
        chunk = data["history"]["data"]
        for r in chunk:
            rows.append({"date": r[0], "board": r[1], "close": r[2],
                         "yield": r[3] if len(r) > 3 else None})
        if len(chunk) < 100:
            break
        start += len(chunk)
    return rows


def _pick_board(rows: list[dict], market: str) -> list[dict]:
    rows = [r for r in rows if r["close"] not in (None, 0)]
    if market == "shares":
        return [r for r in rows if r["board"] == "TQBR"]
    if market == "index":
        return rows
    boards = {r["board"] for r in rows}
    for b in BOND_BOARD_PRIORITY:
        if b in boards:
            return [r for r in rows if r["board"] == b]
    return rows if len(boards) <= 1 else []


def _close_on_or_before(rows: list[dict], d: date):
    best = None
    for r in rows:
        if r["date"] <= d.isoformat() and (best is None or r["date"] > best["date"]):
            best = r
    return best


def security_change(market: str, secid: str, d_from: date, d_to: date, fetch=_http_json) -> dict:
    """Δ по закрытиям. Историю берём с запасом в 10 дней до d_from — на случай выходных и праздников."""
    lo = d_from - timedelta(days=10)
    try:
        rows = _pick_board(fetch_history(market, secid, lo, d_to, fetch), market)
        if not rows and market == "bonds":
            alt = resolve_secid(secid, fetch)
            if alt and alt != secid:
                rows = _pick_board(fetch_history(market, alt, lo, d_to, fetch), market)
    except Exception as exc:  # сеть / формат — честная ошибка по бумаге, не падение всего прогона
        return {"secid": secid, "error": f"fetch_failed: {exc}"}
    a, b = _close_on_or_before(rows, d_from), _close_on_or_before(rows, d_to)
    if not a or not b:
        return {"secid": secid, "error": "no_close_in_window"}
    out = {"secid": secid, "board": b["board"],
           "start": {"date": a["date"], "close": a["close"]},
           "end": {"date": b["date"], "close": b["close"]},
           "change_pct": round((b["close"] / a["close"] - 1) * 100, 2)}
    if market == "bonds" and a.get("yield") is not None and b.get("yield") is not None:
        out["start"]["yield_pct"], out["end"]["yield_pct"] = a["yield"], b["yield"]
        out["yield_change_bp"] = round((b["yield"] - a["yield"]) * 100)
    if market == "index":
        inside = [r for r in rows if a["date"] <= r["date"] <= b["date"]]
        out["window_max"] = max(inside, key=lambda r: r["close"]) if inside else None
        out["window_min"] = min(inside, key=lambda r: r["close"]) if inside else None
        for k in ("window_max", "window_min"):
            if out[k]:
                out[k] = {"date": out[k]["date"], "close": out[k]["close"]}
    return out


def _ddmm(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}"


def compute(snapshot: dict, d_from: date, d_to: date, kind: str = "all", fetch=_http_json) -> dict:
    active = [h for h in snapshot.get("holdings", []) if h.get("status") != "blocked"]
    stocks = [h for h in active if h.get("asset_type") == "stock"] if kind in ("all", "stock") else []
    bonds = [h for h in active if h.get("asset_type") == "bond"] if kind in ("all", "bond") else []

    per_stock, per_bond = {}, {}
    for h in stocks:
        per_stock[h["ticker"]] = security_change("shares", h["ticker"], d_from, d_to, fetch)
    seen = set()
    for h in bonds:
        isin = h.get("isin") or h.get("ticker")
        if isin in seen:  # одна бумага на двух счетах
            continue
        seen.add(isin)
        per_bond[isin] = security_change("bonds", isin, d_from, d_to, fetch)
        per_bond[isin]["name"] = h.get("name")

    indices = {}
    wanted = {"all": INDICES, "stock": ("IMOEX",), "bond": ("RGBI",)}[kind]
    for ix in wanted:
        indices[ix] = security_change("index", ix, d_from, d_to, fetch)

    # Книга акций при неизменных количествах: только бумаги с обеими ценами.
    book = None
    qty = {}
    for h in stocks:
        qty[h["ticker"]] = qty.get(h["ticker"], 0) + (h.get("qty") or 0)
    ok = {t: c for t, c in per_stock.items() if "error" not in c and qty.get(t)}
    if ok:
        v0 = sum(qty[t] * c["start"]["close"] for t, c in ok.items())
        v1 = sum(qty[t] * c["end"]["close"] for t, c in ok.items())
        book = {"change_pct": round((v1 / v0 - 1) * 100, 2), "tickers": len(ok),
                "tickers_missing": sorted(set(qty) - set(ok)),
                "basis": "закрытия ISS, количества из снапшота неизменны; без дивидендов"}
        imx = indices.get("IMOEX")
        if imx and "error" not in imx:
            book["vs_imoex_pp"] = round(book["change_pct"] - imx["change_pct"], 2)

    # Метка среза — из фактических дат закрытий, а не из дат аргументов.
    ends = sorted({c["end"]["date"] for grp in (per_stock, per_bond, indices)
                   for c in grp.values() if "error" not in c})
    starts = sorted({c["start"]["date"] for grp in (per_stock, per_bond, indices)
                     for c in grp.values() if "error" not in c})
    label = None
    if ends and starts:
        label = (f"закрытие {_ddmm(starts[0])}" + (f"–{_ddmm(starts[-1])}" if len(starts) > 1 else "")
                 + f" → закрытие {_ddmm(ends[0])}" + (f"–{_ddmm(ends[-1])}" if len(ends) > 1 else ""))
    errors = {k: c["error"] for grp in (per_stock, per_bond, indices) for k, c in grp.items() if "error" in c}
    return {"window": {"from_arg": d_from.isoformat(), "to_arg": d_to.isoformat(),
                       "start_dates": starts, "end_dates": ends, "label": label},
            "book_stocks": book, "indices": indices,
            "per_stock": per_stock, "per_bond": per_bond, "errors": errors}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--from", dest="d_from", required=True, help="ISO-дата базы (закрытие на/до неё)")
    ap.add_argument("--to", dest="d_to", required=True, help="ISO-дата конца (закрытие на/до неё)")
    ap.add_argument("--kind", choices=("all", "stock", "bond"), default="all")
    args = ap.parse_args(argv)
    d_from, d_to = date.fromisoformat(args.d_from), date.fromisoformat(args.d_to)
    if d_from >= d_to:
        print("ERROR: --from должен быть раньше --to", file=sys.stderr)
        return 2
    with open(args.snapshot, encoding="utf-8") as f:
        snap = json.load(f)
    if "holdings" not in snap:
        print("ERROR: ожидается снапшот v2 (поле holdings)", file=sys.stderr)
        return 2
    print(json.dumps(compute(snap, d_from, d_to, args.kind), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
