#!/usr/bin/env python3
"""Справка по истории ZenMoney: ответы за годы из `ZenMoney/audit/` без вызовов MCP.

Только чтение. Числа из сохранённых итогов месяцев (`spending.json`, пишет
`audit_history.py spending`); модель их объясняет. Справка, а не вердикт:
скрипт не оценивает и не советует — даёт ряды, сравнения, арифметику по числу
пользователя и факты, на которые стоит взглянуть (решение пользователя 2026-10-06).

  python3 history_query.py years    --spending S [--from 2020] [--to 2026] [--tail RUN]
  python3 history_query.py periods  --spending S --a 2023-01:2023-12 --b 2025-01:2025-12
                                    [--category ИМЯ ...] [--sub] [--tail RUN]
  python3 history_query.py category --spending S --name ИМЯ [--by year|month] [--tail RUN]
  python3 history_query.py scale    --spending S --amount 600000 [--window 12] [--trips T]
  python3 history_query.py facts    --spending S [--history H]

`--tail RUN` — результат `month_stats.py` по текущему незакрытому месяцу (операции
из MCP на сегодня): входит в суммы периода с пометкой «на N-е число», в средние в
месяц — нет (неполный месяц не экстраполируется). Средние «в месяц» — по закрытым
месяцам периода; месяцев нет в истории — их список в `missing`.

Факты (`facts`) — пороги в `PARAMS`, подобраны на истории 2022-12…2026-09
(46 закрытий; README 2.11.0). Запись `facts.json` — только `audit_history.py facts`
(единственный писатель `audit/`), он же пересчитывает факты при каждой записи месяца.
Только stdlib, JSON в stdout.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

FACTS_SCHEMA = "zenmoney-facts@1"
STATS_RUN_SCHEMA = "zenmoney-month-stats-run@1"
DIRECT_SUB = "без подкатегории"

# Пороги фактов. Меняешь число — поправь тест (tests/test_history_query.py) и пересчитай
# facts.json: `audit_history.py facts --spending … --write`.
PARAMS = {
    # скачок категории: среднее последних 3 мес. против медианы 12 предыдущих
    "jump": {"window": 3, "base": 12, "min_share_of_regular": 0.015, "iqr_k": 1.5, "min_ratio": 1.3},
    # рост категории: 6 мес. к тем же месяцам год назад, против остальных обычных трат
    # (без самой категории: если одна категория — больше половины трат, сравнение со всеми = с самим собой)
    "growth": {"window": 6, "min_share": 0.05, "min_gap": 0.30},
    # ускорение обычных трат: рост за 12 мес. минус рост за 12 мес. до них
    "acceleration": {"window": 12, "min_gap": 0.05},
    # месяцы с минусом (доход − все расходы < 0): за 12 мес. больше, чем за 12 до них
    "minus": {"window": 12, "min_months": 2},
    # незаписанные траты (корректировки без переводов себе) растут столько месяцев подряд
    "unrecorded": {"months": 3},
    # факты 2–4 — только если держатся столько закрытий подряд
    "persist": 2,
}


class Blocking(Exception):
    pass


# ─── месяцы ──────────────────────────────────────────────────────────────────

def shift(m: str, k: int) -> str:
    y, mo = int(m[:4]), int(m[5:7]) - 1 + k
    return f"{y + mo // 12:04d}-{mo % 12 + 1:02d}"


def span(a: str, b: str) -> list[str]:
    out, m = [], a
    while m <= b:
        out.append(m)
        m = shift(m, 1)
    return out


def window(end: str, n: int) -> list[str]:
    return [shift(end, -i) for i in range(n - 1, -1, -1)]


def r2(x):
    return round(x, 2) if x is not None else None


def share(a, b):
    return round(a / b, 4) if b else None


def growth(cur, base):
    return round(cur / base - 1, 4) if base else None


# ─── история ─────────────────────────────────────────────────────────────────

class Hist:
    def __init__(self, spending: dict, history: dict | None = None, tail: dict | None = None):
        if spending.get("schema") != "zenmoney-spending@1":
            raise Blocking("на входе не spending.json (zenmoney-spending@1)")
        self.sp = spending
        self.m = {x["month"]: x for x in spending.get("months", [])}
        self.last = max(self.m) if self.m else None
        self.audit = {r["month"]: r for r in (history or {}).get("records", [])}
        self.tail = None
        if tail:
            if tail.get("schema") != STATS_RUN_SCHEMA:
                raise Blocking("--tail: на входе не результат month_stats.py")
            if tail["month"] in self.m:
                raise Blocking(f"--tail: {tail['month']} уже закрыт и есть в истории")
            self.tail = tail

    def has(self, months):
        return all(x in self.m for x in months)

    def reg(self, m):
        return self.m[m]["totals"]["expense_regular_rub"]

    def tot(self, m, key):
        return self.m[m]["totals"][key]

    def flow(self, m):
        return self.tot(m, "income_rub") - self.tot(m, "expense_rub")

    def cat(self, m, name, field="rub"):
        return next((c[field] for c in self.m[m].get("categories_regular") or [] if c["name"] == name), 0)

    def cats(self, months):
        return sorted({c["name"] for x in months for c in self.m[x].get("categories_regular") or []})

    def subs(self, m, parent):
        return {s["name"]: s for s in self.m[m].get("subcategories_regular") or [] if s["parent"] == parent}

    def recomputed(self, months):
        return [{"month": x, "recomputed_at": self.m[x]["recomputed_at"]}
                for x in months if x in self.m and self.m[x].get("recomputed_at")]

    def source(self, months=()):
        return {"spending_updated": self.sp.get("updated"), "last_closed_month": self.last,
                "recomputed": self.recomputed(months),
                "tail": ({"month": self.tail["month"], "as_of": self.tail["as_of"]} if self.tail else None)}


# ─── справка ─────────────────────────────────────────────────────────────────

SUMS = (("regular", "expense_regular_rub"), ("trips", "expense_trips_rub"), ("one_off", "expense_one_off_rub"),
        ("expense", "expense_rub"), ("income", "income_rub"))


def period_sums(h: Hist, months):
    closed = [x for x in months if x in h.m]
    sums = {k: sum(h.tot(x, f) for x in closed) for k, f in SUMS}
    n = len(closed)
    out = {"months_closed": n, "missing": [x for x in months if x not in h.m and not (h.tail and x == h.tail["month"])],
           "per_month": {k: r2(v / n) if n else None for k, v in sums.items()},
           "sum": {k: r2(v) for k, v in sums.items()}}
    out["per_month"]["flow"] = r2((sums["income"] - sums["expense"]) / n) if n else None
    out["flow_share_of_income"] = share(sums["income"] - sums["expense"], sums["income"])
    if h.tail and h.tail["month"] in months:
        t = h.tail["totals"]
        out["tail"] = {"month": h.tail["month"], "as_of": h.tail["as_of"],
                       "sum": {k: r2(t[f]) for k, f in SUMS}}
        out["sum_with_tail"] = {k: r2(sums[k] + t[f]) for k, f in SUMS}
    return out


def q_years(h: Hist, frm=None, to=None):
    if not h.m:
        return {"years": [], "source": h.source()}
    first = min(h.m)[:4]
    last = (h.tail["month"] if h.tail else h.last)[:4]
    years, prev = [], None
    for y in range(int(frm or first), int(to or last) + 1):
        months = span(f"{y}-01", f"{y}-12")
        s = period_sums(h, months)
        if not s["months_closed"] and "tail" not in s:
            continue
        s["year"] = str(y)
        s["regular_change"] = growth(s["per_month"]["regular"], prev["per_month"]["regular"]) if prev and s["months_closed"] else None
        s["income_change"] = growth(s["per_month"]["income"], prev["per_month"]["income"]) if prev and s["months_closed"] else None
        years.append(s)
        prev = s if s["months_closed"] else prev
    return {"years": years, "source": h.source(span(f"{frm or first}-01", f"{to or last}-12"))}


def cat_block(h: Hist, months, name, with_sub):
    closed = [x for x in months if x in h.m]
    n = len(closed) or None
    rub = sum(h.cat(x, name) for x in closed)
    cnt = sum(h.cat(x, name, "count") for x in closed)
    b = {"name": name, "per_month": r2(rub / n) if n else None, "sum": r2(rub),
         "count_per_month": round(cnt / n, 1) if n else None, "avg_check": r2(rub / cnt) if cnt else None}
    if with_sub:
        acc = {}
        for x in closed:
            for s, v in h.subs(x, name).items():
                a = acc.setdefault(s, [0.0, 0])
                a[0] += v["rub"]
                a[1] += v["count"]
        b["sub"] = [{"name": s, "per_month": r2(v[0] / n), "sum": r2(v[0]), "count_per_month": round(v[1] / n, 1)}
                    for s, v in sorted(acc.items(), key=lambda kv: -kv[1][0])]
    return b


def parse_period(s):
    a, _, b = s.partition(":")
    if not (len(a) == 7 and len(b) == 7 and a <= b):
        raise Blocking(f"период {s!r}: нужен YYYY-MM:YYYY-MM")
    return span(a, b)


def q_periods(h: Hist, pa, pb, categories=None, sub=False):
    A, B = parse_period(pa), parse_period(pb)
    out = {"a": {"period": pa, **period_sums(h, A)}, "b": {"period": pb, **period_sums(h, B)}}
    names = categories or sorted(set(h.cats([x for x in A if x in h.m])) | set(h.cats([x for x in B if x in h.m])))
    rows = []
    for n in names:
        ca, cb = cat_block(h, A, n, sub), cat_block(h, B, n, sub)
        rows.append({"name": n, "a": ca, "b": cb, "change": growth(cb["per_month"], ca["per_month"])})
    rows.sort(key=lambda r: -((r["b"]["per_month"] or 0) + (r["a"]["per_month"] or 0)))
    out["categories"] = rows
    out["regular_change"] = growth(out["b"]["per_month"]["regular"], out["a"]["per_month"]["regular"])
    out["source"] = h.source(A + B)
    return out


def first_seen(h: Hist, parent):
    seen = {}
    for x in sorted(h.m):
        for s, v in h.subs(x, parent).items():
            if v["rub"] and s not in seen:
                seen[s] = x
    return seen


def q_category(h: Hist, name, by="year"):
    if not any(name == c["name"] for x in h.m.values() for c in x.get("categories_regular") or []):
        raise Blocking(f"категории {name!r} нет в обычных тратах истории")
    months = sorted(h.m)
    if by == "month":
        rows = [{"month": x, "rub": r2(h.cat(x, name)), "count": h.cat(x, name, "count"),
                 "share_of_regular": share(h.cat(x, name), h.reg(x)),
                 "sub": [{"name": s, "rub": v["rub"], "count": v["count"]} for s, v in h.subs(x, name).items()]}
                for x in months]
    else:
        rows = []
        for y in sorted({x[:4] for x in months}):
            ym = [x for x in months if x[:4] == y]
            b = cat_block(h, ym, name, True)
            b.update(year=y, months_closed=len(ym), share_of_regular=share(sum(h.cat(x, name) for x in ym),
                                                                           sum(h.reg(x) for x in ym)))
            rows.append(b)
    out = {"category": name, "by": by, "rows": rows,
           "sub_first_seen": first_seen(h, name), "source": h.source(months)}
    if h.tail:
        t = next((c for c in h.tail.get("categories_regular") or [] if c["name"] == name), None)
        out["tail"] = {"month": h.tail["month"], "as_of": h.tail["as_of"], "rub": t["rub"] if t else 0}
    return out


def q_scale(h: Hist, amount, n=12, trips=None):
    if not h.last:
        raise Blocking("история пуста")
    months = [x for x in window(h.last, n) if x in h.m]
    flows = sorted(h.flow(x) for x in months)
    q = statistics.quantiles(flows, n=4) if len(flows) >= 4 else None
    reg = sum(h.reg(x) for x in months) / len(months)
    med = statistics.median(flows)
    out = {"amount": amount, "months": [months[0], months[-1]], "months_closed": len(months),
           "flow_median": r2(med), "flow_q1": r2(q[0]) if q else None,
           "months_of_median_flow": round(amount / med, 1) if med > 0 else None,
           "months_of_regular": round(amount / reg, 1), "regular_per_month": r2(reg),
           "months_with_minus": sum(1 for f in flows if f < 0), "source": h.source(months)}
    if trips:
        start = months[0]
        tt = [t for t in trips.get("trips", []) if (t.get("period") or {}).get("end", "")[:7] >= start]
        if tt:
            avg = sum(t["totals"]["spent_rub"] for t in tt) / len(tt)
            out["trips"] = {"count": len(tt), "avg_spent_rub": r2(avg), "amount_in_trips": round(amount / avg, 1)}
    return out


# ─── факты ───────────────────────────────────────────────────────────────────

def explain(h: Hist, name, cur, base):
    """Пояснение к факту по категории: чаще или дороже, за счёт каких подкатегорий."""
    a, b = cat_block(h, base, name, True), cat_block(h, cur, name, True)
    seen = first_seen(h, name)
    bs = {s["name"]: s for s in a.get("sub", [])}
    subs = []
    for s in b.get("sub", []):
        o = bs.get(s["name"])
        new = seen.get(s["name"])
        new = new if new and new >= base[0] else None
        # у новой статьи процента нет: «+1100%» у перестановки учёта выглядит ростом трат
        subs.append({"name": s["name"], "per_month_base": o["per_month"] if o else 0.0, "per_month": s["per_month"],
                     "change": growth(s["per_month"], o["per_month"]) if o and o["per_month"] and not new else None,
                     "new_since": new})
    return {"count_per_month": [a["count_per_month"], b["count_per_month"]],
            "avg_check": [a["avg_check"], b["avg_check"]],
            "count_change": growth(b["count_per_month"], a["count_per_month"]),
            "avg_check_change": growth(b["avg_check"], a["avg_check"]), "sub": subs}


def f_jump(h: Hist, M):
    p = PARAMS["jump"]
    cur, base = window(M, p["window"]), window(shift(M, -p["window"]), p["base"])
    if not h.has(cur + base):
        return None
    tl = sum(h.reg(x) for x in cur) / len(cur)
    out = []
    for c in h.cats(cur):
        vals = [h.cat(x, c) for x in base]
        med = statistics.median(vals)
        q = statistics.quantiles(vals, n=4)
        rec = sum(h.cat(x, c) for x in cur) / len(cur)
        d = rec - med
        if med > 0 and d >= p["min_share_of_regular"] * tl and d > p["iqr_k"] * (q[2] - q[0]) and rec / med >= p["min_ratio"]:
            out.append({"kind": "jump", "category": c, "window": [cur[0], cur[-1]], "base": [base[0], base[-1]],
                        "median_rub": r2(med), "recent_avg_rub": r2(rec), "ratio": round(rec / med, 2),
                        "excess_rub": r2(d), "_cur": cur, "_base": base})
    return out


def f_growth(h: Hist, M):
    p = PARAMS["growth"]
    cur = window(M, p["window"])
    base = [shift(x, -12) for x in cur]
    if not h.has(cur + base):
        return None
    tc, tb = sum(h.reg(x) for x in cur), sum(h.reg(x) for x in base)
    out = []
    for c in h.cats(cur):
        cc, cb = sum(h.cat(x, c) for x in cur), sum(h.cat(x, c) for x in base)
        if cb <= 0 or not tc or cc / tc < p["min_share"] or tb - cb <= 0:
            continue
        g, go = cc / cb - 1, (tc - cc) / (tb - cb) - 1
        if g - go >= p["min_gap"]:
            n = len(cur)
            out.append({"kind": "growth", "category": c, "window": [cur[0], cur[-1]], "base": [base[0], base[-1]],
                        "per_month_base": r2(cb / n), "per_month": r2(cc / n), "growth": round(g, 4),
                        "others_growth": round(go, 4), "share_base": share(cb, tb), "share": share(cc, tc),
                        "excess_rub": r2((cc - cb * (1 + go)) / n), "_cur": cur, "_base": base})
    return out


def f_accel(h: Hist, M):
    w = PARAMS["acceleration"]["window"]
    w1, w0, wp = window(M, w), window(shift(M, -w), w), window(shift(M, -2 * w), w)
    if not h.has(w1 + w0 + wp):
        return None
    s1, s0, sp = (sum(h.reg(x) for x in ws) for ws in (w1, w0, wp))
    g1, g0 = s1 / s0 - 1, s0 / sp - 1
    if g1 - g0 >= PARAMS["acceleration"]["min_gap"]:
        return [{"kind": "acceleration", "window": [w1[0], w1[-1]], "growth": round(g1, 4), "growth_prev": round(g0, 4),
                 "per_month": r2(s1 / w), "per_month_prev": r2(s0 / w)}]
    return []


def f_minus(h: Hist, M):
    p = PARAMS["minus"]
    w1, w0 = window(M, p["window"]), window(shift(M, -p["window"]), p["window"])
    if not h.has(w1 + w0):
        return None
    neg = [x for x in w1 if h.flow(x) < 0]
    prev = sum(1 for x in w0 if h.flow(x) < 0)
    if len(neg) > prev and len(neg) >= p["min_months"]:
        def why(x):
            r = h.m[x]["totals"]
            return [k for k, f in (("trips", "expense_trips_rub"), ("one_off", "expense_one_off_rub")) if r[f] > 0]
        return [{"kind": "minus_months", "window": [w1[0], w1[-1]], "count": len(neg), "count_prev": prev,
                 "months": [{"month": x, "flow": r2(h.flow(x)), "with": why(x)} for x in neg]}]
    return []


def f_unrecorded(h: Hist, M):
    n = PARAMS["unrecorded"]["months"]
    ms = window(M, n)
    if not all(x in h.audit for x in ms):
        return None
    def val(x):
        r = h.audit[x]
        un = (r.get("correction_rub") or 0) - (r.get("correction_transfer_out_rub") or 0)
        return un, (un / r["expense_rub"] if r.get("expense_rub") else 0.0)
    ser = [val(x) for x in ms]
    if ser[-1][1] > 0 and all(ser[i][1] < ser[i + 1][1] for i in range(n - 1)):
        return [{"kind": "unrecorded_rising",
                 "series": [{"month": x, "rub": r2(v[0]), "share": round(v[1], 4)} for x, v in zip(ms, ser)]}]
    return []


def raw_facts(h: Hist, M):
    return {k: f(h, M) for k, f in (("jump", f_jump), ("growth", f_growth), ("acceleration", f_accel),
                                     ("minus_months", f_minus))}


def compute_facts(spending: dict, history: dict | None = None) -> dict:
    """Факты на последний закрытый месяц истории. Чистая функция — пишет audit_history.py."""
    h = Hist(spending, history)
    out = {"schema": FACTS_SCHEMA, "updated": spending.get("updated"), "month": h.last,
           "params": PARAMS, "facts": [], "flagged_categories": {}, "not_enough_data": []}
    if not h.last:
        return out
    now, prev = raw_facts(h, h.last), raw_facts(h, shift(h.last, -1))
    key = lambda f: (f["kind"], f.get("category"))
    facts = []
    for k, items in now.items():
        if items is None:
            out["not_enough_data"].append(k)
            continue
        held = {key(f) for f in prev[k] or []} if PARAMS["persist"] > 1 else None
        facts += [f for f in items if held is None or key(f) in held]
    un = f_unrecorded(h, h.last)
    if un is None:
        out["not_enough_data"].append("unrecorded_rising")
    facts = (un or []) + facts
    for f in facts:
        if f.get("category"):
            f["explain"] = explain(h, f["category"], f.pop("_cur"), f.pop("_base"))
            out["flagged_categories"].setdefault(f["category"], []).append(f["kind"])
    order = {"unrecorded_rising": 0, "minus_months": 1, "acceleration": 2, "growth": 3, "jump": 3}
    facts.sort(key=lambda f: (order[f["kind"]], -(f.get("excess_rub") or 0)))
    out["facts"] = facts
    return out


# ─── CLI ─────────────────────────────────────────────────────────────────────

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else None


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    for name in ("years", "periods", "category", "scale", "facts"):
        s = sp.add_parser(name)
        s.add_argument("--spending", required=True)
        if name != "facts":
            s.add_argument("--tail", help="month_stats.py по текущему месяцу (на сегодня)")
        if name == "years":
            s.add_argument("--from", dest="frm")
            s.add_argument("--to")
        if name == "periods":
            s.add_argument("--a", required=True)
            s.add_argument("--b", required=True)
            s.add_argument("--category", action="append")
            s.add_argument("--sub", action="store_true", help="с подкатегориями")
        if name == "category":
            s.add_argument("--name", required=True)
            s.add_argument("--by", choices=("year", "month"), default="year")
        if name == "scale":
            s.add_argument("--amount", type=float, required=True)
            s.add_argument("--window", type=int, default=12)
            s.add_argument("--trips")
        if name == "facts":
            s.add_argument("--history")
    a = p.parse_args(argv)
    try:
        sp_ = load(a.spending)
        if a.cmd == "facts":
            res = compute_facts(sp_, load(a.history))
        else:
            h = Hist(sp_, tail=load(a.tail))
            if a.cmd == "years":
                res = q_years(h, a.frm, a.to)
            elif a.cmd == "periods":
                res = q_periods(h, a.a, a.b, a.category, a.sub)
            elif a.cmd == "category":
                res = q_category(h, a.name, a.by)
            else:
                res = q_scale(h, a.amount, a.window, load(a.trips))
    except Blocking as e:
        print(json.dumps({"blocking": str(e)}, ensure_ascii=False))
        return 2
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
