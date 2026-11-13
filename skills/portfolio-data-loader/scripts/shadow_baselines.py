#!/usr/bin/env python3
"""Теневые базы AIR-1 (этап 3): B0 / B1 / B2-live / B2-frozen против факта B3.

План: docs/investment/portfolio/air-1-decision-journal-plan.md §2 (определения
зафиксированы до первого расчёта, решения D-2, D-4). Входы — shadow_inputs.py,
ряды — market_series.py. Только данные: никаких выводов и рекомендаций.

Модель. Каждая база — набор «рукавов» key → units, стоимость = units × price(key, d):
  stock:{T}        акция TQBR, дивиденд (брутто × 0,87) зачисляется в кэш в день выплаты
  idx:MCFTR        индекс акций полной доходности (B1)
  idx:RGBITR       ОФЗ (полная доходность)
  idx:RUCBTRNS     корпоративные облигации (полная доходность)
  cny:RUCNYTR      юаневые облигации: индекс в CNY × курс CNY ЦБ
  fxs:USD|EUR      синтетика валютных облигаций: курс ЦБ × (1+YTM на t0)^(дни/365) — D-4, условность
  gold:GLDRUB_TOM  золото, руб/г
  rate:CASH|FLOAT|OTHER  рубли, растущие по RUSFAR: кэш; флоатеры ОФЗ; «другое» (ЗПИФ, недвижимость) — прокси
Сделки — по закрытию ≤ дате, комиссия COMMISSION от оборота. Налог на прирост
не учитывается ни в одной базе (флаг: B2 продаёт растущие бумаги чаще факта).

Базы (все получают одни и те же внешние потоки в те же дни):
  B0  позиции факта на t0 заморожены; облигации — индекс рукава по валюте/типу (приближение);
      пополнения и дивиденды — в кэш.
  B1  классы в долях плана; облигации ТОЛЬКО рублёвые (D-4): ОФЗ/корп. в пропорции рублёвых
      корзин плана на t0; ребаланс в первый снапшот квартала; пополнения — по целевым долям.
  B2  старт из позиций факта на t0, правило полос D-2 на каждой дате снапшота:
      класс вне ±5 п.п. → полный ребаланс; иначе рукав внутри класса вне ±25% своей доли
      (или держится без плана) → ребаланс внутри класса. Пополнения — в недовес.
      live — план на каждую дату; frozen — акции по плану 2026-05-05, корзины облигаций —
      по первой известной разбивке (2026-06-08, до неё разбивки не было).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

COMMISSION = 0.0005
DIVIDEND_TAX = 0.13
CLASS_BAND_PP = 0.05
SLEEVE_BAND_REL = 0.25
B2_FROZEN_STOCKS_DATE = "2026-05-05"
RECONCILE_VS_B0_PP = 0.02   # |r_B3 − r_B0| на интервале выше — флаг сверки
BAND_EPS = 1e-9             # граница полосы включительно: 0,65 − 0,6 = 0,05000000000000004

CLASSES = ("stock", "bond", "gold", "other", "cash")


def key_class(key: str) -> str:
    if key.startswith("stock:") or key == "idx:MCFTR":
        return "stock"
    if key.startswith(("idx:", "cny:", "fxs:")) or key == "rate:FLOAT":
        return "bond"
    if key.startswith("gold:"):
        return "gold"
    if key == "rate:OTHER":
        return "other"
    if key == "rate:CASH":
        return "cash"
    raise ValueError(f"неизвестный рукав {key!r}")


def bucket_sleeve(bucket: str) -> str:
    """Корзина плана облигаций → рукав."""
    b = bucket.split("#")[0]
    if b == "USD":
        return "fxs:USD"
    if b == "EUR":
        return "fxs:EUR"
    if b == "CNY":
        return "cny:RUCNYTR"
    if b == "ОФЗ/Флоат":
        return "rate:FLOAT"
    if b.startswith("ОФЗ"):
        return "idx:RGBITR"
    if b.startswith("КОРП"):
        return "idx:RUCBTRNS"
    raise ValueError(f"неизвестная корзина {bucket!r}")


# ---------------------------------------------------------------- рынок

def _prev(points: list[tuple[str, float]], iso: str) -> float | None:
    lo, hi = 0, len(points)
    while lo < hi:
        mid = (lo + hi) // 2
        if points[mid][0] <= iso:
            lo = mid + 1
        else:
            hi = mid
    return points[lo - 1][1] if lo else None


class Market:
    """Цены рукавов на дату. series: {"index:MCFTR": [(iso, v)], "share:SBER": …,
    "rate_index:RUSFAR": …, "currency:GLDRUB_TOM": …, "fx_cbr:USD": …}.
    fx_yield: {"USD": 0.097, "EUR": …} — YTM синтетики на t0."""

    def __init__(self, series: dict[str, list[tuple[str, float]]], t0: dt.date,
                 fx_yield: dict[str, float]):
        self.s = {k: sorted(v) for k, v in series.items()}
        self.t0 = t0
        self.fx_yield = fx_yield
        self.flags: list[str] = []
        self._acc_cache: dict[dt.date, float] = {t0: 1.0}
        self._acc_last = t0

    def _acc(self, d: dt.date) -> float:
        """Накопленный множитель RUSFAR с t0 (ставка forward-fill, actual/365)."""
        if d <= self.t0:
            return 1.0
        if d in self._acc_cache:
            return self._acc_cache[d]
        cur, v = self._acc_last, self._acc_cache[self._acc_last]
        if d < cur:
            cur, v = self.t0, 1.0
        rus = self.s.get("rate_index:RUSFAR") or []
        while cur < d:
            r = _prev(rus, cur.isoformat())
            if r is None:
                r = 0.0
            v *= 1 + r / 100 / 365
            cur += dt.timedelta(days=1)
            self._acc_cache[cur] = v
        self._acc_last = max(self._acc_last, d)
        return v

    def price(self, key: str, d: dt.date) -> float | None:
        iso = d.isoformat()
        if key.startswith("rate:"):
            return self._acc(d)
        if key.startswith("stock:"):
            return _prev(self.s.get("share:" + key[6:]) or [], iso)
        if key.startswith("idx:"):
            return _prev(self.s.get("index:" + key[4:]) or [], iso)
        if key.startswith("gold:"):
            return _prev(self.s.get("currency:" + key[5:]) or [], iso)
        if key == "cny:RUCNYTR":
            i = _prev(self.s.get("index:RUCNYTR") or [], iso)
            fx = _prev(self.s.get("fx_cbr:CNY") or [], iso)
            return i * fx if i is not None and fx is not None else None
        if key.startswith("fxs:"):
            cur = key[4:]
            fx = _prev(self.s.get("fx_cbr:" + cur) or [], iso)
            if fx is None:
                return None
            y = self.fx_yield.get(cur, 0.0)
            return fx * (1 + y) ** (max((d - self.t0).days, 0) / 365)
        raise ValueError(key)


# ---------------------------------------------------------------- портфель

class Book:
    def __init__(self, name: str, market: Market):
        self.name = name
        self.m = market
        self.units: dict[str, float] = {}
        self.commission_rub = 0.0
        self.turnover_rub = 0.0
        self.rebalances: list[str] = []

    def value(self, key: str, d: dt.date) -> float:
        u = self.units.get(key, 0.0)
        if not u:
            return 0.0
        p = self.m.price(key, d)
        if p is None:
            self.m.flags.append(f"{self.name}: нет цены {key} на {d} — рукав считается нулём")
            return 0.0
        return u * p

    def nav(self, d: dt.date) -> float:
        return sum(self.value(k, d) for k in list(self.units))

    def by_class(self, d: dt.date) -> dict[str, float]:
        out = {c: 0.0 for c in CLASSES}
        for k in self.units:
            out[key_class(k)] += self.value(k, d)
        return out

    def add_rub(self, key: str, rub: float, d: dt.date) -> None:
        p = self.m.price(key, d)
        if p is None or p <= 0:
            self.m.flags.append(f"{self.name}: нет цены {key} на {d} — {rub:.0f} ₽ ушли в кэш")
            key, p = "rate:CASH", self.m.price("rate:CASH", d)
        self.units[key] = self.units.get(key, 0.0) + rub / p

    def set_values(self, target_rub: dict[str, float], d: dt.date, why: str) -> None:
        """Привести рукава к целевым суммам (₽). Комиссия — из кэша."""
        keys = set(target_rub) | set(self.units)
        turnover = sum(abs(target_rub.get(k, 0.0) - self.value(k, d)) for k in keys)
        if turnover < 1.0:
            return
        fee = turnover * COMMISSION
        for k in keys:
            tv = target_rub.get(k, 0.0)
            p = self.m.price(k, d)
            if tv <= 0:
                self.units.pop(k, None)
            elif p:
                self.units[k] = tv / p
        self.add_rub("rate:CASH", -fee, d)
        self.commission_rub += fee
        self.turnover_rub += turnover
        self.rebalances.append(f"{d} {why}")

    def pay_dividends(self, divs: dict[str, list[dict]], d: dt.date) -> None:
        iso = d.isoformat()
        for k in [k for k in self.units if k.startswith("stock:")]:
            for x in divs.get(k[6:], []):
                if x["date"] == iso:
                    self.add_rub("rate:CASH", self.units[k] * x["dps_gross"] * (1 - DIVIDEND_TAX), d)


# ---------------------------------------------------------------- цели

def targets_from_plan(plan: dict, rub_bond_only: bool = False,
                      stock_index: bool = False, frozen_stocks: dict | None = None,
                      frozen_buckets: dict | None = None) -> dict[str, float]:
    """Целевые веса рукавов (Σ = 1) из точки плана shadow_inputs.plan_point."""
    cls = plan["classes"]
    w: dict[str, float] = {}
    stocks = frozen_stocks if frozen_stocks is not None else (plan["stocks"] or {})
    if stock_index or not stocks:
        w["idx:MCFTR"] = cls["stock"]
    else:
        for t, s in stocks.items():
            w["stock:" + t] = w.get("stock:" + t, 0.0) + cls["stock"] * s
    buckets = frozen_buckets if frozen_buckets is not None else (plan["bond_buckets"] or {})
    sleeves: dict[str, float] = {}
    for b, s in buckets.items():
        if s <= 0:
            continue
        k = bucket_sleeve(b)
        if rub_bond_only and k.startswith(("fxs:", "cny:")):
            continue
        sleeves[k] = sleeves.get(k, 0.0) + s
    tot = sum(sleeves.values())
    if tot <= 0:
        sleeves, tot = {"idx:RGBITR": 1.0}, 1.0
    for k, s in sleeves.items():
        w[k] = w.get(k, 0.0) + cls["bond"] * s / tot
    w["gold:GLDRUB_TOM"] = cls["gold"]
    w["rate:OTHER"] = cls["other"]
    w["rate:CASH"] = cls["cash"]
    return w


def plan_at(history: list[dict], d: dt.date) -> dict | None:
    """Последняя точка плана ≤ d с заданными классами."""
    best = None
    for p in history:
        if p["date"] <= d.isoformat() and p.get("classes"):
            best = p
    return best


def band_breach(book: Book, w: dict[str, float], d: dt.date) -> tuple[str | None, str | None]:
    """D-2: ('full'|'class:<c>'|None, причина)."""
    nav = book.nav(d)
    if nav <= 0:
        return None, None
    cur = book.by_class(d)
    tgt = {c: 0.0 for c in CLASSES}
    for k, x in w.items():
        tgt[key_class(k)] += x
    for c in CLASSES:
        if abs(cur[c] / nav - tgt[c]) > CLASS_BAND_PP + BAND_EPS:
            return "full", f"класс {c}: {cur[c] / nav:.1%} против {tgt[c]:.1%}"
    for c in ("stock", "bond"):
        if cur[c] <= 0 or tgt[c] <= 0:
            continue
        keys = {k for k in set(w) | set(book.units) if key_class(k) == c}
        for k in sorted(keys):
            share_t = w.get(k, 0.0) / tgt[c]
            share = book.value(k, d) / cur[c]
            if (share_t == 0 and share > 0.001) or (share_t > 0 and abs(share - share_t) > SLEEVE_BAND_REL * share_t + BAND_EPS):
                return f"class:{c}", f"{k}: {share:.1%} внутри {c} против {share_t:.1%}"
    return None, None


def rebalance(book: Book, w: dict[str, float], d: dt.date, scope: str, why: str) -> None:
    nav = book.nav(d)
    if scope == "full":
        book.set_values({k: nav * x for k, x in w.items()}, d, why)
        return
    c = scope.split(":", 1)[1]
    cls_val = book.by_class(d)[c]
    tgt_c = sum(x for k, x in w.items() if key_class(k) == c)
    target = {k: book.value(k, d) for k in book.units if key_class(k) != c}
    for k, x in w.items():
        if key_class(k) == c:
            target[k] = cls_val * x / tgt_c
    book.set_values(target, d, why)


def deposit_to_deficits(book: Book, w: dict[str, float], rub: float, d: dt.date) -> None:
    """«Новые деньги — в недовес»: пропорционально недовесу рукавов после пополнения."""
    if rub <= 0:
        book.add_rub("rate:CASH", rub, d)       # вывод — из кэша
        return
    nav_after = book.nav(d) + rub
    deficits = {k: max(nav_after * x - book.value(k, d), 0.0) for k, x in w.items()}
    tot = sum(deficits.values())
    alloc = ({k: rub * v / tot for k, v in deficits.items() if v > 0} if tot > 0
             else {k: rub * x for k, x in w.items()})
    for k, v in alloc.items():
        book.add_rub(k, v, d)
    book.commission_rub += rub * COMMISSION
    book.add_rub("rate:CASH", -rub * COMMISSION, d)


# ---------------------------------------------------------------- старт из факта

def _is_ofz(h: dict) -> bool:
    """ОФЗ: снапшот держит их по ISIN (RU000A106E90), биржевой код SU… — только в выгрузке сделок."""
    return (h.get("ticker") or "").startswith("SU") or (h.get("name") or "").startswith("ОФЗ")


def _ofz_series(h: dict) -> str:
    """Первые две цифры номера выпуска: 26 — постоянный купон, 29 — флоатер (ОФЗ-ПК), 52 — линкер."""
    t, n = h.get("ticker") or "", (h.get("name") or "").replace("ОФЗ", "").strip()
    if t.startswith("SU"):
        return t[2:4]
    return n[:2]


def initial_from_snapshot(book: Book, snap: dict, d: dt.date, fund_sectors: dict[str, str]) -> None:
    """Позиции факта на t0 → рукава. Облигации — по валюте/типу (приближение B0)."""
    from shadow_inputs import holding_class
    for h in snap.get("holdings") or []:
        if h.get("status") == "blocked" or h.get("is_blocked"):
            continue
        v = h.get("value_rub") or 0.0
        if v <= 0:
            continue
        cls = holding_class(h, fund_sectors)
        t = h.get("ticker") or ""
        if h.get("asset_type") == "stock":
            key = "stock:" + t
        elif h.get("asset_type") == "bond":
            cur = h.get("nominal_currency") or "RUB"
            if cur in ("USD", "EUR"):
                key = "fxs:" + cur
            elif cur == "CNY":
                key = "cny:RUCNYTR"
            elif _is_ofz(h) and _ofz_series(h) == "29":
                key = "rate:FLOAT"                # ОФЗ-ПК 29xxx
            elif _is_ofz(h):
                key = "idx:RGBITR"
            else:
                key = "idx:RUCBTRNS"
        elif cls == "cash":
            key = "rate:CASH"
        elif cls == "gold":
            key = "gold:GLDRUB_TOM"
        elif cls == "bond":
            key = "idx:RGBITR"
        else:
            key = "rate:OTHER"
        book.add_rub(key, v, d)
    book.add_rub("rate:CASH", (snap.get("cash") or {}).get("total_rub") or 0.0, d)


def fx_yields_from_snapshot(snap: dict) -> dict[str, float]:
    """Взвешенная по стоимости YTM валютных облигаций факта на t0 (доли, не %)."""
    acc: dict[str, list[float]] = {}
    for h in snap.get("holdings") or []:
        if h.get("asset_type") != "bond" or h.get("status") == "blocked":
            continue
        cur = h.get("nominal_currency")
        if cur in ("USD", "EUR") and h.get("ytm_pct") is not None and h.get("value_rub"):
            a = acc.setdefault(cur, [0.0, 0.0])
            a[0] += h["ytm_pct"] * h["value_rub"]
            a[1] += h["value_rub"]
    return {c: round(a[0] / a[1] / 100, 6) for c, a in acc.items() if a[1] > 0}


# ---------------------------------------------------------------- прогон

def twr(navs: list[tuple[dt.date, float]], flows: list[tuple[dt.date, float]]) -> tuple[float | None, float | None]:
    """Цепочка Дитца по интервалам между датами оценки → (за период, годовая)."""
    if len(navs) < 2:
        return None, None
    g = 1.0
    for (d0, v0), (d1, v1) in zip(navs, navs[1:]):
        fl = sum(v for d, v in flows if d0 < d <= d1)
        base = v0 + fl / 2
        if base <= 0:
            return None, None
        g *= 1 + (v1 - v0 - fl) / base
    days = (navs[-1][0] - navs[0][0]).days
    ann = g ** (365 / days) - 1 if days > 0 else None
    return g - 1, ann


def run(inputs: dict, snaps: dict[str, dict], market: Market,
        fund_sectors: dict[str, str]) -> dict:
    b3 = inputs["b3"]
    if len(b3) < 2:
        return {"schema": "shadow-baselines@1", "error": "меньше двух точек факта B3", "flags": []}
    eval_dates = [dt.date.fromisoformat(p["date"]) for p in b3]
    t0, end = eval_dates[0], eval_dates[-1]
    flows = [(dt.date.fromisoformat(d), v) for d, v in inputs["external_flows"]
             if t0 < dt.date.fromisoformat(d) <= end]
    divs = inputs["dividends"]
    hist = inputs["plan_history"]
    snap0 = snaps[t0.isoformat()]

    frozen_p = next((p for p in hist if p["date"] == B2_FROZEN_STOCKS_DATE), None)
    frozen_stocks = frozen_p["stocks"] if frozen_p else None
    first_buckets = next((p["bond_buckets"] for p in hist if p.get("bond_buckets")), None)

    def plan_w(kind: str, d: dt.date) -> dict[str, float]:
        p = plan_at(hist, d)
        if kind == "B1":
            p0 = plan_at(hist, t0)
            return targets_from_plan(p0, rub_bond_only=True, stock_index=True)
        if kind == "B2-frozen":
            return targets_from_plan(p, frozen_stocks=frozen_stocks, frozen_buckets=first_buckets)
        return targets_from_plan(p)

    books = {n: Book(n, market) for n in ("B0", "B1", "B2-live", "B2-frozen")}
    for n in ("B0", "B2-live", "B2-frozen"):
        initial_from_snapshot(books[n], snap0, t0, fund_sectors)
    nav0 = books["B0"].nav(t0)
    for k, x in plan_w("B1", t0).items():                          # старт индексной базы — не сделка
        books["B1"].add_rub(k, nav0 * x, t0)

    div_dates = {dt.date.fromisoformat(x["date"]) for lst in divs.values() for x in lst}
    quarter_starts = {dt.date(y, m, 1) for y in range(t0.year, end.year + 1) for m in (1, 4, 7, 10)}
    b1_rebalanced_q: set[tuple[int, int]] = {(t0.year, (t0.month - 1) // 3)}
    events = sorted({t0, end} | set(eval_dates) | {d for d, _ in flows}
                    | {d for d in div_dates if t0 < d <= end} | {d for d in quarter_starts if t0 < d <= end})

    series: dict[str, list[tuple[dt.date, float]]] = {n: [] for n in books}
    log: dict[str, list[str]] = {n: [] for n in books}
    for d in events:
        flow = sum(v for fd, v in flows if fd == d)
        for n, bk in books.items():
            if d > t0:
                bk.pay_dividends(divs, d)
            if flow:
                if n == "B0":
                    bk.add_rub("rate:CASH", flow, d)
                elif n == "B1":
                    w = plan_w("B1", d)
                    if flow > 0:                     # покупка рукавов — сделка: комиссия как у B2
                        fee = flow * COMMISSION
                        for k, x in w.items():
                            bk.add_rub(k, (flow - fee) * x, d)
                        bk.commission_rub += fee
                    else:
                        bk.add_rub("rate:CASH", flow, d)
                else:
                    deposit_to_deficits(bk, plan_w(n, d), flow, d)
            if d in eval_dates:
                series[n].append((d, bk.nav(d)))
                if n.startswith("B2"):
                    w = plan_w(n, d)
                    scope, why = band_breach(bk, w, d)
                    if scope:
                        rebalance(bk, w, d, scope, why)
                        log[n].append(f"{d} {scope}: {why}")
                if n == "B1":
                    q = (d.year, (d.month - 1) // 3)
                    if q not in b1_rebalanced_q:
                        b1_rebalanced_q.add(q)
                        w = plan_w("B1", d)
                        bk.set_values({k: bk.nav(d) * x for k, x in w.items()}, d, "квартальный ребаланс")
                        log[n].append(f"{d} квартальный ребаланс")

    b3_navs = [(dt.date.fromisoformat(p["date"]), p["nav_rub"]) for p in b3]
    out_bases: dict[str, dict] = {}
    b3_twr, b3_ann = twr(b3_navs, flows)
    for n, s in series.items():
        tw, ann = twr(s, flows)
        out_bases[n] = {
            "nav": [[d.isoformat(), round(v, 2)] for d, v in s],
            "terminal_rub": round(s[-1][1], 2),
            "twr": round(tw, 5) if tw is not None else None,
            "twr_ann": round(ann, 5) if ann is not None else None,
            "b3_minus_base_pp_ann": (round((b3_ann - ann) * 100, 2)
                                     if b3_ann is not None and ann is not None else None),
            "b3_minus_base_rub": round(b3_navs[-1][1] - s[-1][1], 2),
            "commission_rub": round(books[n].commission_rub, 2),
            "turnover_rub": round(books[n].turnover_rub, 2),
            "rebalances": log[n],
        }

    # сверка факта против B0 (те же позиции t0 по ценам рынка) — ловит сбои оценки снапшотов
    flags = sorted(set(market.flags))
    b0 = series["B0"]
    for i in range(1, len(b3_navs)):
        r3 = twr(b3_navs[i - 1:i + 1], flows)[0]
        r0 = twr(b0[i - 1:i + 1], flows)[0]
        if r3 is not None and r0 is not None and abs(r3 - r0) > RECONCILE_VS_B0_PP:
            flags.append(f"сверка {b3_navs[i-1][0]}→{b3_navs[i][0]}: факт {r3:+.2%} против B0 {r0:+.2%}")

    return {
        "schema": "shadow-baselines@1",
        "window": {"t0": t0.isoformat(), "end": end.isoformat(), "days": (end - t0).days},
        "b3": {"nav": [[d.isoformat(), v] for d, v in b3_navs],
               "twr": round(b3_twr, 5) if b3_twr is not None else None,
               "twr_ann": round(b3_ann, 5) if b3_ann is not None else None},
        "bases": out_bases,
        "assumptions": {
            "commission": COMMISSION, "dividend_tax": DIVIDEND_TAX,
            "class_band_pp": CLASS_BAND_PP, "sleeve_band_rel": SLEEVE_BAND_REL,
            "fx_yield_t0": market.fx_yield,
            "b2_frozen_stocks": B2_FROZEN_STOCKS_DATE if frozen_stocks else None,
            "b2_frozen_buckets": next((p["date"] for p in hist if p.get("bond_buckets")), None),
            "capital_gains_tax": "не учитывается ни в одной базе",
            "other_class": "«другое» (ЗПИФ, недвижимость) — прокси RUSFAR",
        },
        "flags": flags,
    }


# ---------------------------------------------------------------- CLI

def required_series(inputs: dict, snap0: dict) -> list[tuple[str, str]]:
    tickers = {h["ticker"] for h in snap0.get("holdings") or []
               if h.get("asset_type") == "stock" and h.get("status") != "blocked"}
    for p in inputs["plan_history"]:
        tickers |= set((p.get("stocks") or {}).keys())
    specs = [("index", "MCFTR"), ("index", "RGBITR"), ("index", "RUCBTRNS"), ("index", "RUCNYTR"),
             ("rate_index", "RUSFAR"), ("currency", "GLDRUB_TOM"),
             ("fx_cbr", "USD"), ("fx_cbr", "EUR"), ("fx_cbr", "CNY")]
    return specs + [("share", t) for t in sorted(tickers)]


def main(argv: list[str] | None = None) -> int:
    import market_series as ms
    from shadow_inputs import DEFAULT_SNAPSHOT_DIR, fund_sectors, load_snapshots

    ap = argparse.ArgumentParser(description="Теневые базы AIR-1 против факта.")
    ap.add_argument("--inputs", type=Path, required=True, help="JSON из shadow_inputs.py --out")
    ap.add_argument("--snapshots", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)

    inputs = json.loads(a.inputs.read_text(encoding="utf-8"))
    snaps_l = load_snapshots(a.snapshots)
    snaps = {d.isoformat(): s for d, s in snaps_l}
    t0 = dt.date.fromisoformat(inputs["b3"][0]["date"])
    end = dt.date.fromisoformat(inputs["b3"][-1]["date"])
    snap0 = snaps[t0.isoformat()]
    got = ms.get_many(required_series(inputs, snap0), t0 - dt.timedelta(days=14), end, offline=a.offline)
    series = {k: s.points for k, s in got.items()}
    empty = [k for k, s in got.items() if not s.points]
    market = Market(series, t0, fx_yields_from_snapshot(snap0))
    res = run(inputs, snaps, market, fund_sectors(snaps_l))
    res["flags"] = [f"ряд пуст: {k}" for k in empty] + res.get("flags", [])
    if a.out:
        a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    brief = {"window": res.get("window"), "b3": {k: res["b3"][k] for k in ("twr", "twr_ann")},
             "bases": {n: {k: b[k] for k in ("terminal_rub", "twr", "twr_ann", "b3_minus_base_pp_ann",
                                             "b3_minus_base_rub", "commission_rub")} | {"rebalances": len(b["rebalances"])}
                       for n, b in res["bases"].items()},
             "flags": res["flags"]}
    print(json.dumps(brief, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
