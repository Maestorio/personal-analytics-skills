#!/usr/bin/env python3
"""Входы теневых баз AIR-1 (этап 2): факт B3, внешние потоки, дивиденды, история плана.

План: docs/investment/portfolio/air-1-decision-journal-plan.md §1–§2.
Только данные — без расчёта баз (это этап 3, shadow_baselines.py).

Источники:
  * снапшоты `Portfolio/snapshots/portfolio-*.json` — факт B3 (стоимость по MOEX
    + кэш), целевые доли классов, плановые доли акций, плановые корзины облигаций;
  * выгрузка IntelInvest `trades_portfolio_*.xlsx` — внешние потоки и дивиденды
    (парсер — portfolio_returns.parse_trades, single-ownership загрузки).

Решения, зафиксированные здесь (2026-10-07):
  * B3 = Σ незаблокированных позиций + cash.total_rub (не status_summary: тот до 08-15
    включал замороженные US-бумаги), только снапшоты с
    B3_START: раньше рыночной оценки нет (до 2026-07-02), а кэш до фикса
    семантики 2026-07-08 дважды считал ИИС и денежные фонды. «Имеется» из
    Numbers не годится: до 07-08 включало плановое «Пополнение».
  * Внешний поток = «Внесение»/«Списание» денег с пустой заметкой или явной
    заметкой пополнения/вывода. Налоги и комиссии — внутренние расходы: в
    выгрузке налог записан дважды («Расход» и «Списание»), и инвариантный метод
    portfolio_returns принимает его за вывод.
  * Дивиденд на акцию — ДО налога: автоимпорт брокера пишет нетто (−13%),
    ручные строки — брутто; берём максимум по выплате. Базы удерживают 13% сами.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from portfolio_returns import (  # noqa: E402
    Trade, apply_corrections, convert_trades_to_rub, is_forex_conversion, parse_trades,
)

B3_START = dt.date(2026, 7, 8)
DIVIDEND_TAX = 0.13
DIV_CLUSTER_DAYS = 5          # строки одной выплаты разнесены по счетам на ±дни
RECONCILE_MAX_ABS_RET = 0.05  # |доходность интервала| выше — флаг сверки (07-23→07-31 рынок дал +3,8%:
                              # 3% ловил настоящие ралли; сверка против рынка — этап 3)

EXTERNAL_NOTES_IN = ("Пополнение счета", "Перечисление денежных средств")
EXTERNAL_NOTES_OUT = ("Вывод денежных средств",)

CLASS_BY_GOAL = {"Акции": "stock", "Облигация": "bond", "Золото": "gold",
                 "Другое": "other", "Кеш": "cash"}
GOLD_FUND_TICKERS = frozenset({"TGLD", "GOLD", "AKGD", "SBGD", "VTBG"})

DEFAULT_SNAPSHOT_DIR = (Path.home() / "Library/CloudStorage/SynologyDrive-home/"
                        "Claude-Memory/Portfolio/snapshots")


# ---------------------------------------------------------------- потоки

def is_external_flow(t: Trade) -> bool:
    """Внешнее пополнение/вывод (см. докстринг модуля)."""
    if not t.ticker.startswith("Деньги") or is_forex_conversion(t):
        return False
    note = (t.note or "").strip()
    if t.operation == "Внесение":
        return note == "" or any(s in note for s in EXTERNAL_NOTES_IN)
    if t.operation == "Списание":
        return note == "" or any(s in note for s in EXTERNAL_NOTES_OUT)
    return False


def external_flows(trades: list[Trade], start: dt.date, end: dt.date) -> list[tuple[dt.date, float]]:
    """[(дата, руб)] — знак: + пополнение, − вывод; суммы за день схлопнуты."""
    by_day: dict[dt.date, float] = {}
    for t in trades:
        if start <= t.date <= end and is_external_flow(t):
            by_day[t.date] = by_day.get(t.date, 0.0) + t.rub_amount
    return sorted((d, round(v, 2)) for d, v in by_day.items() if abs(v) >= 1.0)


# ---------------------------------------------------------------- дивиденды

def dividends_per_share(trades: list[Trade], since: dt.date) -> tuple[dict[str, list[dict]], list[str]]:
    """{тикер: [{date, dps_gross, rows}]} по выплатам с `since`.

    Строки одной выплаты (разные счета, брутто и нетто) склеиваются, если идут
    в пределах DIV_CLUSTER_DAYS. dps_gross = максимум по брутто-строкам кластера;
    если в кластере только нетто-строки — брутто = нетто / 0,87 (флаг)."""
    flags: list[str] = []
    rows: dict[str, list[tuple[dt.date, float, bool]]] = {}
    for t in trades:
        if t.operation != "Дивиденд" or t.date < since or not t.qty or t.qty <= 0:
            continue
        if t.currency != "RUB":
            continue
        dps = abs(t.amount) / t.qty
        is_net = (t.note or "").startswith("Дивиденды по ")  # автоимпорт брокера
        rows.setdefault(t.ticker, []).append((t.date, dps, is_net))

    out: dict[str, list[dict]] = {}
    for ticker, lst in rows.items():
        lst.sort()
        clusters: list[list[tuple[dt.date, float, bool]]] = []
        for r in lst:
            if clusters and (r[0] - clusters[-1][0][0]).days <= DIV_CLUSTER_DAYS:
                clusters[-1].append(r)
            else:
                clusters.append([r])
        for c in clusters:
            gross_rows = [dps for _, dps, net in c if not net]
            net_rows = [dps for _, dps, net in c if net]
            if gross_rows:
                # нетто/0,87 сюда не подмешивать: брокер удерживает не ровно 13%
                # (PLZL 07-15: 25,28/0,87 = 29,06 против брутто 28,76)
                dps_gross = max(gross_rows)
            else:
                dps_gross = max(net_rows) / (1 - DIVIDEND_TAX)
                flags.append(f"дивиденд {ticker} {c[0][0]}: только нетто-строки, брутто восстановлен /0,87")
            out.setdefault(ticker, []).append({
                "date": c[0][0].isoformat(), "dps_gross": round(dps_gross, 6), "rows": len(c),
            })
    return out, flags


# ---------------------------------------------------------------- снапшоты

def load_snapshots(snapshot_dir: Path) -> list[tuple[dt.date, dict]]:
    out = []
    for f in sorted(glob.glob(str(snapshot_dir / "portfolio-????-??-??.json"))):
        d = dt.date.fromisoformat(Path(f).stem[len("portfolio-"):])
        with open(f, encoding="utf-8") as fh:
            out.append((d, json.load(fh)))
    return out


def fund_sectors(snaps: list[tuple[dt.date, dict]]) -> dict[str, str]:
    """Тикер фонда → последний известный сектор: в снапшотах до ~08-2026 у фондов
    sector = None (TMON/TPAY попадали бы в «другое» вместо кэша)."""
    out: dict[str, str] = {}
    for _, s in snaps:
        for h in s.get("holdings") or []:
            if h.get("asset_type") == "fund" and h.get("sector"):
                out[h["ticker"]] = h["sector"]
    return out


def holding_class(h: dict, sectors: dict[str, str] | None = None) -> str:
    """Класс плана (goals_overall) для позиции снапшота."""
    at = h.get("asset_type")
    if at == "stock":
        return "stock"
    if at == "bond":
        return "bond"
    sector = h.get("sector") or (sectors or {}).get(h.get("ticker"), "")
    if h.get("ticker") in GOLD_FUND_TICKERS:
        return "gold"
    if sector == "money_market":
        return "cash"
    if sector.startswith("bonds"):
        return "bond"
    return "other"


def b3_point(date: dt.date, snap: dict, sectors: dict[str, str] | None = None) -> dict | None:
    """Факт на дату снапшота: стоимость по MOEX незаблокированных + кэш, разбивка по классам."""
    ss = (snap.get("status_summary") or {}).get("total_value_rub")
    cash = (snap.get("cash") or {}).get("total_rub")
    if ss is None or cash is None:
        return None
    by_class = {k: 0.0 for k in CLASS_BY_GOAL.values()}
    for h in snap.get("holdings") or []:
        if h.get("status") == "blocked" or h.get("is_blocked"):
            continue
        by_class[holding_class(h, sectors)] += h.get("value_rub") or 0.0
    by_class["cash"] += cash
    # nav — сумма незаблокированных + кэш, НЕ status_summary.total_value_rub: тот до 2026-08-15
    # включал замороженные US-бумаги (239 тыс. ₽), с 08-19 их оценивают в ноль — ложный
    # «убыток» −1,6% на интервале 08-15→08-19.
    return {"date": date.isoformat(), "nav_rub": round(sum(by_class.values()), 2),
            "by_class_rub": {k: round(v, 2) for k, v in by_class.items()}}


def b3_series(snaps: list[tuple[dt.date, dict]], start: dt.date = B3_START) -> list[dict]:
    pts = []
    sectors = fund_sectors(snaps)
    for d, s in snaps:
        if d < start:
            continue
        p = b3_point(d, s, sectors)
        if p:
            pts.append(p)
    return pts


def reconcile(points: list[dict], flows: list[tuple[dt.date, float]]) -> list[dict]:
    """Доходность каждого интервала между снапшотами по Дитцу (поток в середине).
    |r| > RECONCILE_MAX_ABS_RET → флаг: вероятен сбой оценки снапшота или пропущенный поток."""
    out = []
    for a, b in zip(points, points[1:]):
        d0, d1 = dt.date.fromisoformat(a["date"]), dt.date.fromisoformat(b["date"])
        fl = sum(v for d, v in flows if d0 < d <= d1)
        base = a["nav_rub"] + fl / 2
        r = (b["nav_rub"] - a["nav_rub"] - fl) / base if base > 0 else None
        out.append({"from": a["date"], "to": b["date"], "flows_rub": round(fl, 2),
                    "ret": round(r, 5) if r is not None else None,
                    "flag": r is None or abs(r) > RECONCILE_MAX_ABS_RET})
    return out


def plan_point(date: dt.date, snap: dict) -> dict:
    """Плановые доли на дату: классы (доли 0..1), акции внутри класса (нормированы к 1),
    корзины облигаций (доли 0..1 или None, если разбивки ещё нет)."""
    bal = snap.get("balance_summary") or {}
    goals = bal.get("goals_overall")
    if isinstance(goals, dict):              # формат 2026-05-05: {"overall": [...]}
        goals = goals.get("overall")
    classes = None
    if goals:
        classes = {CLASS_BY_GOAL[g["Тип"]]: float(g["Доля"]) for g in goals if g.get("Тип") in CLASS_BY_GOAL}

    per_ticker = (snap.get("ie_actual") or {}).get("per_ticker") or {}
    raw = {t: v["planned_share_pct"] for t, v in per_ticker.items()
           if isinstance(v, dict) and v.get("planned_share_pct")}
    tot = sum(raw.values())
    stocks = {t: round(v / tot, 6) for t, v in sorted(raw.items())} if tot > 0 else None

    buckets = None
    br = bal.get("goals_bonds_breakdown")
    if br:
        buckets = {}
        for r in br:
            key = r.get("_bucket_key") or r.get("Тип")
            if not key or key == "Итог" or r.get("Доля План") is None:
                continue
            if key in buckets and not r.get("_bucket_key"):
                key = f"{key}#{len(buckets)}"     # до 08-19: два «КОРП» без подтипа
            buckets[key] = float(r["Доля План"])
    return {"date": date.isoformat(), "classes": classes, "stocks": stocks,
            "stocks_raw_sum_pct": round(tot, 4), "bond_buckets": buckets}


def plan_history(snaps: list[tuple[dt.date, dict]]) -> list[dict]:
    """Только точки, где план изменился (первая — всегда)."""
    out, prev = [], None
    for d, s in snaps:
        p = plan_point(d, s)
        key = (p["classes"], p["stocks"], p["bond_buckets"])
        if key != prev:
            out.append(p)
            prev = key
    return out


# ---------------------------------------------------------------- сборка

def newest_trades_export(downloads: Path = Path.home() / "Downloads") -> Path | None:
    files = glob.glob(str(downloads / "trades_portfolio_*.xlsx"))
    return Path(max(files, key=os.path.getmtime)) if files else None


def build_inputs(trades: list[Trade], snaps: list[tuple[dt.date, dict]],
                 since: dt.date, as_of: dt.date) -> dict[str, Any]:
    flags: list[str] = []
    b3 = b3_series(snaps, max(since, B3_START))
    flows = external_flows(trades, since, as_of)
    divs, dflags = dividends_per_share(trades, since)
    flags += dflags
    rec = reconcile(b3, flows)
    for r in rec:
        if r["flag"]:
            flags.append(f"сверка B3 {r['from']}→{r['to']}: доходность {r['ret']} при потоках {r['flows_rub']}")
    last_trade = max((t.date for t in trades), default=None)
    if b3 and last_trade and last_trade < dt.date.fromisoformat(b3[-1]["date"]) - dt.timedelta(days=3):
        flags.append(f"выгрузка сделок кончается {last_trade}, последний снапшот {b3[-1]['date']} — приложи свежую")
    return {
        "schema": "shadow-inputs@1",
        "window": {"since": since.isoformat(), "as_of": as_of.isoformat(), "b3_start": B3_START.isoformat()},
        "b3": b3,
        "reconcile": rec,
        "external_flows": [[d.isoformat(), v] for d, v in flows],
        "dividends": divs,
        "plan_history": plan_history(snaps),
        "trades_last_date": last_trade.isoformat() if last_trade else None,
        "flags": flags,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Входы теневых баз AIR-1: факт B3, потоки, дивиденды, план.")
    ap.add_argument("--trades", type=Path, help="trades_portfolio_*.xlsx (по умолчанию — самый свежий в ~/Downloads)")
    ap.add_argument("--snapshots", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    ap.add_argument("--since", type=dt.date.fromisoformat, default=dt.date(2026, 5, 1))
    ap.add_argument("--as-of", type=dt.date.fromisoformat, default=dt.date.today())
    ap.add_argument("--cbr-offline", action="store_true")
    ap.add_argument("--out", type=Path, help="записать JSON сюда (иначе — сводка в stdout)")
    a = ap.parse_args(argv)

    path = a.trades or newest_trades_export()
    if not path:
        print("нет выгрузки trades_portfolio_*.xlsx", file=sys.stderr)
        return 2
    trades = parse_trades(str(path))
    trades, _ = apply_corrections(trades)
    trades = convert_trades_to_rub(trades, cbr_offline=a.cbr_offline)
    res = build_inputs(trades, load_snapshots(a.snapshots), a.since, a.as_of)
    res["trades_file"] = path.name
    if a.out:
        a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {
        "trades_file": path.name, "trades_last_date": res["trades_last_date"],
        "b3_points": len(res["b3"]),
        "b3_first": res["b3"][0] if res["b3"] else None,
        "b3_last": res["b3"][-1] if res["b3"] else None,
        "external_flows": res["external_flows"],
        "dividend_tickers": len(res["dividends"]),
        "plan_changes": [p["date"] for p in res["plan_history"]],
        "flags": res["flags"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
