#!/usr/bin/env python3
"""
sizing_to_target.py

«Довести долю бумаги до N %» по ЛЮБОЙ бумаге снапшота (акция, облигация, фонд): сколько рублей,
бумаг и лотов докупить (+) или продать (−). Это арифметика от цены снапшота, не совет.

Не заменяет `gate_aware_sizing.py`: докупка акций с гейтами (достижимая база докупки, блокировки,
лимиты концентрации) считается им; здесь для акций — только «простая» арифметика доли от выбранной базы.

Базы (`--base`) — только те, что приняты в скилле (references/analysis-process.md, «Шаг 5.7»):
  nav   (по умолчанию) — «NAV без ИИС-3»: `balance_summary.total_current_rub_excl_iis` (позиции основных
        счетов без блокировок + кэш основного счёта). Это L1-база скилла и база колонки «Сейчас» вьюера.
        Бумага берётся по основным счетам (позиция на ИИС-3 в эту базу не входит; в выводе — отдельной строкой).
  all   — «весь портфель с ИИС-3 и кэшем»: `balance_summary.total_current_rub_incl_iis`;
        бумага — по всем счетам (на двух счетах — суммарно).
  class — «внутри своего класса, без ИИС-3» (L2): сумма незаблокированных позиций основных счетов того же
        класса (для акций — активная книга, как `real_share_pct`). Покупка растёт на сумму сделки внутри
        класса, поэтому сумма считается как (p·B − текущая) / (1 − p); на nav/all база от сделки не меняется
        (деньги идут из кэша, который в базе).
Подкорзины облигаций (USD/EUR/CNY/ОФЗ…) и «база балансировки» как отдельные базы не поддерживаются.

Лоты — `gate_aware_sizing.compute_lots` (покупка вниз, продажа вверх); цена и размер лота — из снапшота
(`current_price`, `lot_size`; нет лота — 1 бумага) или `--quotes` (quotes@1: items.{T}.price/lot_size).

CLI:
    python3 sizing_to_target.py --snapshot <portfolio-ДАТА.json> --ticker TGLD=4[,TICK=3,…] \\
        [--base nav|all|class] [--quotes quotes.json] [--json | --text]
Одну бумагу можно указать несколько раз (`--ticker TGLD=4,TGLD=3`) — по строке на цель.

Exit codes: 0 — успех; 2 — ошибка входа (сообщение без traceback).
Stdlib only. Read-only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate_aware_sizing as gas  # noqa: E402

BASES = ("nav", "all", "class")
DEFAULT_BASE = "nav"
_BASE_LABEL = {
    "nav": "NAV без ИИС-3 (основные счета и кэш основного счёта)",
    "all": "весь портфель с ИИС-3 и кэшем",
    "class": "класс бумаги внутри основных счетов, без ИИС-3",
}
_ASSET_RU = {"stock": "акция", "bond": "облигация", "fund": "фонд"}


class SizingError(Exception):
    """Ошибка входа/данных — CLI завершается кодом 2 без traceback."""


def parse_targets(raw: list[str]) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for chunk in raw:
        for part in chunk.split(","):
            part = part.strip()
            if not part:
                continue
            if "=" not in part:
                raise SizingError(f"--ticker: ожидается TICKER=доля_в_процентах, получено {part!r}")
            t, v = part.split("=", 1)
            try:
                pct = float(v.replace(",", "."))
            except ValueError:
                raise SizingError(f"--ticker: доля {v!r} у {t!r} не число")
            if not (0 <= pct < 100):
                raise SizingError(f"--ticker: доля {pct} у {t!r} вне [0; 100)")
            out.append((t.strip(), pct))
    if not out:
        raise SizingError("не задан --ticker TICKER=доля")
    return out


def load_quotes(path: str | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f) or {}
    except (OSError, ValueError) as exc:
        raise SizingError(f"не удалось прочитать котировки {path!r}: {exc}")
    items = doc.get("items") if isinstance(doc, dict) else None
    if not isinstance(items, dict):
        raise SizingError(f"{path!r}: нет items (ожидается quotes@1)")
    out = {}
    for t, it in items.items():
        if isinstance(it, dict) and it.get("price"):
            out[t] = {"last": it["price"], "lot_size": it.get("lot_size")}
    return out


def _num(x: Any) -> float:
    return float(x) if isinstance(x, (int, float)) else 0.0


def compute_base(snapshot: dict[str, Any], base: str, asset_type: str | None) -> tuple[float, str]:
    """(сумма базы ₽, подпись). Для class подпись зависит от класса бумаги."""
    bs = snapshot.get("balance_summary")
    if base == "nav":
        v = (bs or {}).get("total_current_rub_excl_iis")
        if not isinstance(v, (int, float)):
            raise SizingError("в balance_summary нет числового total_current_rub_excl_iis")
        return float(v), _BASE_LABEL["nav"]
    if base == "all":
        v = (bs or {}).get("total_current_rub_incl_iis")
        if not isinstance(v, (int, float)):
            raise SizingError("в balance_summary нет числового total_current_rub_incl_iis")
        return float(v), _BASE_LABEL["all"]
    holdings = snapshot.get("holdings")
    if not isinstance(holdings, list):
        raise SizingError("в снапшоте нет списка holdings")
    if asset_type == "stock":
        total = sum(_num(h.get("value_rub")) for h in gas.active_stock_holdings(snapshot))
    else:
        total = sum(_num(h.get("value_rub")) for h in holdings
                    if isinstance(h, dict) and h.get("asset_type") == asset_type
                    and h.get("account") == "main" and not h.get("is_blocked")
                    and h.get("current_price_source") != "cost_basis")
    return total, f"{_ASSET_RU.get(asset_type or '', asset_type)}: класс внутри основных счетов, без ИИС-3"


def _position(snapshot: dict[str, Any], ticker: str, base: str) -> dict[str, Any]:
    rows = [h for h in snapshot.get("holdings") or []
            if isinstance(h, dict) and h.get("ticker") == ticker and not h.get("is_blocked")]
    if not rows:
        raise SizingError(f"бумаги {ticker!r} нет среди незаблокированных позиций снапшота")
    main = [h for h in rows if h.get("account") == "main"]
    scope = rows if base == "all" else main
    other = [h for h in rows if h not in scope]
    first = rows[0]
    return {
        "value": sum(_num(h.get("value_rub")) for h in scope),
        "qty": sum(_num(h.get("qty")) for h in scope),
        "other_value": sum(_num(h.get("value_rub")) for h in other),
        "accounts": sorted({h.get("account") for h in scope}),
        "asset_type": first.get("asset_type"),
        "price": first.get("current_price"),
        "lot_size": first.get("lot_size"),
    }


def _share_after(cur, base_rub, base, lots, lot_size, price, delta):
    if lots is None:
        return None
    trade = lots * lot_size * price * (1 if delta > 0 else -1)
    denom = base_rub + (trade if base == "class" else 0.0)
    return round((cur + trade) / denom * 100, 2) if denom > 0 else 0.0


def compute_one(snapshot: dict[str, Any], ticker: str, pct: float, base: str,
                quotes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pos = _position(snapshot, ticker, base)
    base_rub, base_label = compute_base(snapshot, base, pos["asset_type"])
    if base_rub <= 0:
        raise SizingError(f"база {base!r} не положительна ({base_rub})")
    cur = pos["value"]
    p = pct / 100.0
    target = p * base_rub
    if base == "class":
        delta = (target - cur) / (1 - p)
        target = cur + delta
    else:
        delta = target - cur
    q = dict(quotes.get(ticker) or {"last": pos["price"], "lot_size": pos["lot_size"]})
    lot_known = bool(q.get("lot_size"))
    q["lot_size"] = q.get("lot_size") or 1
    lots, remainder, price = gas.compute_lots(delta, q)
    lot_size = q["lot_size"]
    units = lots * lot_size if lots is not None else None
    units_exact = abs(delta) / price if price else None
    return {
        "ticker": ticker, "asset_type": pos["asset_type"], "accounts": pos["accounts"],
        "base": base, "base_label": base_label, "base_rub": round(base_rub, 2),
        "current_rub": round(cur, 2), "current_pct": round(cur / base_rub * 100, 2),
        "target_pct": pct, "target_rub": round(target, 2),
        "delta_rub": round(delta, 2),
        "direction": "buy" if delta > 0 else ("sell" if delta < 0 else "none"),
        "price": price, "lot_size": lot_size, "lot_known": lot_known,
        "lots": lots, "units": units,
        "units_exact": round(units_exact, 2) if units_exact is not None else None,
        "lots_rub": round(lots * lot_size * price, 2) if lots is not None else None,
        "remainder_rub": round(remainder, 2) if remainder is not None else None,
        "qty_after": (pos["qty"] + (units if delta > 0 else -units)) if units is not None else None,
        "other_accounts_rub": round(pos["other_value"], 2),
        "qty_now": pos["qty"],
        "share_after_pct": _share_after(cur, base_rub, base, lots, lot_size, price, delta),
    }


def _rub(x: float) -> str:
    return f"{round(x):,}".replace(",", " ") + " ₽"


def _n(x: float, nd: int = 0) -> str:
    s = f"{x:,.{nd}f}".replace(",", " ")
    if nd and "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace(".", ",")


def render_text(result: dict[str, Any]) -> str:
    items = result["items"]
    lines = [f"База: {items[0]['base_label']} — {_rub(items[0]['base_rub'])}." if items else ""]
    for r in items:
        pct_now = _n(r["current_pct"], 2)
        head = (f"{r['ticker']} ({_ASSET_RU.get(r['asset_type'], r['asset_type'])}, счета: "
                f"{', '.join(r['accounts'])}): сейчас {_rub(r['current_rub'])} = {pct_now} % базы; "
                f"цель {_n(r['target_pct'], 2)} % = {_rub(r['target_rub'])}.")
        lines.append(head)
        if r["direction"] == "none":
            lines.append("  Разница нулевая.")
        else:
            verb = "Докупить" if r["direction"] == "buy" else "Продать"
            lines.append(f"  {verb} на {_rub(abs(r['delta_rub']))}"
                         + (f" ≈ {_n(r['units_exact'])} шт по {_n(r['price'], 2)} ₽." if r["price"] else "."))
            if r["lots"] is not None:
                rnd = "вниз" if r["direction"] == "buy" else "вверх"
                lines.append(f"  По лотам ({rnd}): {_n(r['lots'])} лотов × {_n(r['lot_size'])} шт = "
                             f"{_n(r['units'])} шт на {_rub(r['lots_rub'])}; остаток {_rub(abs(r['remainder_rub']))}; "
                             f"доля после {_n(r['share_after_pct'], 2)} %. "
                             f"Бумаг после сделки: {_n(r['qty_after'])} шт."
                             + ("" if r["lot_known"] else " Размер лота в снапшоте не указан — принят 1 шт."))
            else:
                lines.append("  Лоты не посчитаны: нет цены в снапшоте.")
        if r["other_accounts_rub"]:
            lines.append(f"  Та же бумага на других счетах ({_rub(r['other_accounts_rub'])}) в эту базу не входит.")
        if r["asset_type"] == "stock":
            lines.append("  Докупка акций с гейтами и блокировками считается `gate_aware_sizing.py`; "
                         "здесь — арифметика доли от выбранной базы.")
    return "\n".join(l for l in lines if l)


def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Довести долю бумаги до N % от базы (сумма, бумаги, лоты).")
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--ticker", action="append", required=True, metavar="TICKER=N[,TICKER=N]")
    ap.add_argument("--base", choices=BASES, default=DEFAULT_BASE)
    ap.add_argument("--quotes", metavar="FILE")
    fmt = ap.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true")
    fmt.add_argument("--text", action="store_true")
    args = ap.parse_args(argv)
    try:
        snapshot = gas.load_snapshot(args.snapshot)
        targets = parse_targets(args.ticker)
        quotes = load_quotes(args.quotes)
        items = [compute_one(snapshot, t, pct, args.base, quotes) for t, pct in targets]
    except (SizingError, gas.GateAwareSizingError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2
    result = {"snapshot_date": snapshot.get("as_of_date"), "base": args.base, "items": items}
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(run())
