#!/usr/bin/env python3
"""Статистика поездки ZenMoney: сколько на что ушло — билеты, жильё, еда… (рецепт R4).

Поездка = операции с тегом поездки ИЛИ с ней основной категорией, за ВСЁ время:
билеты и жильё покупают за месяцы до поездки, поэтому окно выгрузки — широкое
(рекомендация: от года до начала поездки до двух месяцев после конца).

  needs-rates: python3 trip_stats.py needs-rates --trip <ID> --tx <файлы>
  отчёт:       python3 trip_stats.py report --trip <ID> --tx <файлы> --rates <файлы>
                   [--wallet-tx <файлы>] [--categories <файл>] [--config <файл>]

  --tx         list_transactions с tagIds=[ID] и с categoryIds=[ID] (оба запроса)
  --wallet-tx  операции валютного кошелька поездки за её даты (accountIds) — для поиска
               трат без тега (в ответ, не в историю); --wallet ID… — оставить только эти счета
  --config     как у audit_month.py, плюс:
                 trip_dates {ID: ["YYYY-MM-DD", "YYYY-MM-DD"]} — даты из карты (с дорогой);
                 trip_types {ID категории: "тип"} — переопределить тип статьи;
                 excluded_categories — как у month_stats.py (для партнёра и кешбэка)

Даты поездки: из карты; нет — по данным (самая плотная серия дней с тратами на месте,
разрывы ≤ 2 дней) с пометкой «по данным». Только stdlib, ничего не пишет, JSON в stdout.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_month import Ctx, d, kind, load_categories, load_config, load_rates, merge_pages, norm_name  # noqa: E402
from month_stats import Stats, r2  # noqa: E402

TYPES = ["Билеты", "Жильё", "Транспорт на месте", "Еда", "Экскурсии и развлечения", "Покупки и подарки",
         "Связь и сервисы", "Здоровье и страховка", "Незаписанные траты", "Без статьи", "Другое"]
PREPAID_TYPES = {"Билеты", "Жильё"}           # не определяют даты «на месте»
TICKET_MERCHANT = re.compile(r"ржд|rzd|купибилет|kupibilet|aviasales|авиасейлс|туту|tutu|аэрофлот|aeroflot|"
                             r"t-?bank ?air|avia|авиа|s7|победа|pobeda|уральск|airline|airways|air ?asia|vietjet|airport|аэропорт|"
                             r"ufs|onetwotrip|ozon ?travel|яндекс ?путешеств", re.I)
HOUSING_MERCHANT = re.compile(r"booking|airbnb|ostrovok|островок|agoda|hotel|отель|гостиниц|hostel|хостел|суточно", re.I)
NAME_RULES = [  # (по названию самой категории) → тип
    (re.compile(r"перел|авиа|билет|поезд|\bжд\b|переплыв|паром"), "Билеты"),
    (re.compile(r"гостиниц|отел|хостел|жиль|аренда жилья"), "Жильё"),
    (re.compile(r"такси|арендован|бензин|проезд|каршер|транспорт|топливо"), "Транспорт на месте"),
    (re.compile(r"страх|аптек|медиц|здоров"), "Здоровье и страховка"),
    (re.compile(r"подар|покупк|сувенир|одежд|игрушк"), "Покупки и подарки"),   # игрушка — покупка, не развлечение (Вьетнам'26)
    (re.compile(r"экскурс|развлеч|отдых|музе|досуг"), "Экскурсии и развлечения"),
    (re.compile(r"связь|сотов|интернет|esim|сим"), "Связь и сервисы"),
]
ROOT_RULES = {"питание": "Еда", "досуг": "Экскурсии и развлечения", "одежда,обувь,аксессуары": "Покупки и подарки",
              "одеждаобувьаксессуары": "Покупки и подарки", "счета": "Связь и сервисы",
              "здоровье": "Здоровье и страховка", "жилище": "Жильё", "транспорт": "Транспорт на месте"}
LEAD_BUCKETS = [(30, "до месяца"), (91, "1–3 месяца"), (182, "3–6 месяцев"), (10 ** 6, "больше 6 месяцев")]


class Trip:
    def __init__(self, ctx: Ctx, trip_id: str):
        self.ctx, self.id = ctx, trip_id
        self.st = Stats(ctx)
        self.types_cfg = ctx.cfg.get("trip_types") or {}

    def ops(self):
        return [o for o in self.ctx.ops if kind(o) != "transfer"
                and (o.get("categoryId") == self.id or self.id in (o.get("tagIds") or []))]

    def type_of(self, op):
        ctx, cid = self.ctx, op.get("categoryId")
        if cid in ctx.correction_ids:
            return "Незаписанные траты"
        if cid == self.id or cid in ctx.project_ids:
            return "Без статьи"
        root = self.st.root(cid) if cid else None
        for key in (cid, root):
            if key in self.types_cfg:
                return self.types_cfg[key]
        m = (ctx.refs["merchants"].get(op.get("merchantId")) or {}).get("name", "") if op.get("merchantId") else ""
        text = f"{m} {op.get('originalPayee', '')}"
        if TICKET_MERCHANT.search(text):
            return "Билеты"
        if HOUSING_MERCHANT.search(text):
            return "Жильё"
        own = (ctx.cats.get(cid) or {}).get("name", "").lower()
        for rx, t in NAME_RULES:
            if rx.search(own):
                return t
        return ROOT_RULES.get(norm_name(ctx.cat_name(root)) if root else "", "Другое")


def infer_period(trip, ops):
    """Самая плотная серия дней с тратами «на месте» (не билеты/жильё), разрывы ≤ 2 дней."""
    days = sorted({d(o["date"]) for o in ops if kind(o) == "expense" and trip.type_of(o) not in PREPAID_TYPES})
    if not days:
        return None
    count = Counter(d(o["date"]) for o in ops)
    runs, cur = [], [days[0]]
    for x in days[1:]:
        if (x - cur[-1]).days <= 3:
            cur.append(x)
        else:
            runs.append(cur)
            cur = [x]
    runs.append(cur)
    best = max(runs, key=lambda r: (sum(count[x] for x in r), len(r)))
    return best[0], best[-1]


def lead_bucket(days):
    return next(label for lim, label in LEAD_BUCKETS if days <= lim)


def report(ctx: Ctx, trip_id: str, wallet_ops=None):
    tr = Trip(ctx, trip_id)
    ops = tr.ops()
    dates = (ctx.cfg.get("trip_dates") or {}).get(trip_id)
    if dates:
        start, end, basis = d(dates[0]), d(dates[1]), "карта"
    else:
        p = infer_period(tr, ops)
        start, end, basis = (p[0], p[1], "по данным") if p else (None, None, "нет данных")
    by_type = defaultdict(lambda: {"rub": 0.0, "count": 0})
    phase = defaultdict(float)
    type_phase = defaultdict(lambda: defaultdict(float))
    lead = defaultdict(lambda: {"rub": 0.0, "count": 0})
    cur_amt = defaultdict(lambda: {"amount": 0.0, "rub": 0.0})
    tot = defaultdict(float)
    for o in ops:
        v = ctx.rub(o)
        if v is None:
            continue
        k, cid = kind(o), o.get("categoryId")
        if k == "income" and not tr.st.is_refund(o):
            g = tr.st.group(cid)
            tot["partner_rub" if g == "partner" else "compensations_rub"] += v
            continue
        sign = 1 if k == "expense" else -1
        if k == "income":
            tot["refunds_rub"] += v
        else:
            tot["gross_rub"] += v
        t = tr.type_of(o)
        by_type[t]["rub"] += sign * v
        by_type[t]["count"] += 1
        dt = d(o["date"])
        ph = "before" if start and dt < start else ("after" if end and dt > end else "during")
        if not start:
            ph = "during"
        phase[ph] += sign * v
        type_phase[t][ph] += sign * v
        if ph == "before":
            b = lead_bucket((start - dt).days)
            lead[b]["rub"] += sign * v
            lead[b]["count"] += 1
        s = o.get("expense") or o.get("income")
        inst = ctx.acc(s["accountId"]).get("instrument", ctx.main)
        cur_amt[inst]["amount"] += sign * float(s["amount"])
        cur_amt[inst]["rub"] += sign * v
    spent = tot["gross_rub"] - tot["refunds_rub"]
    net = spent - tot["compensations_rub"]
    days = (end - start).days + 1 if start else None
    untagged = []
    if wallet_ops is not None and start:
        seen = {o["id"] for o in ops}
        for o in wallet_ops:
            if (o["id"] not in seen and kind(o) == "expense" and start <= d(o["date"]) <= end
                    and o.get("categoryId") not in ctx.correction_ids):
                untagged.append({"id": o["id"], "date": o["date"], "rub": r2(ctx.rub(o) or 0.0),
                                 "category": ctx.cat_name(o.get("categoryId")) if o.get("categoryId") else None,
                                 "tags": [ctx.cat_name(t) for t in o.get("tagIds") or []]})
    order = {t: i for i, t in enumerate(TYPES)}
    return {
        "schema": "zenmoney-trip-stats-run@1",
        "trip": {"id": trip_id, "name": ctx.cat_name(trip_id)},
        "period": {"start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
                   "basis": basis, "days": days},
        "first_purchase": min((o["date"] for o in ops), default=None),
        "totals": {"spent_rub": r2(spent), "gross_rub": r2(tot["gross_rub"]), "refunds_rub": r2(tot["refunds_rub"]),
                   "compensations_rub": r2(tot["compensations_rub"]), "net_rub": r2(net),
                   "partner_rub": r2(tot["partner_rub"]),
                   "unrecorded_rub": r2(by_type["Незаписанные траты"]["rub"]) if "Незаписанные траты" in by_type else 0.0,
                   "per_day_during_rub": r2(phase["during"] / days) if days else None,
                   "operations": len(ops)},
        "by_type": [{"type": t, "rub": r2(x["rub"]), "count": x["count"],
                     "share": round(x["rub"] / spent, 4) if spent else None}
                    for t, x in sorted(by_type.items(), key=lambda kv: order.get(kv[0], 99))],
        "by_phase": {p: r2(phase[p]) for p in ("before", "during", "after")},
        "type_by_phase": [{"type": t, **{p: r2(v[p]) for p in ("before", "during", "after")}}
                          for t, v in sorted(type_phase.items(), key=lambda kv: order.get(kv[0], 99))],
        "prepaid_by_lead": [{"bucket": label, "rub": r2(lead[label]["rub"]), "count": lead[label]["count"]}
                            for _lim, label in LEAD_BUCKETS if label in lead],
        "currencies": [{"instrument": i, "amount": round(x["amount"], 2), "rub": r2(x["rub"])}
                       for i, x in sorted(cur_amt.items(), key=lambda kv: -kv[1]["rub"])],
        "untagged_in_wallet": untagged,
        "coverage": {"unconverted": dict(Counter(i for _o, _a, i in ctx.missing))},
    }


def needs_rates(ctx: Ctx, trip_id: str, extra_ops=()):
    tr = Trip(ctx, trip_id)
    need = defaultdict(set)
    for o in list(tr.ops()) + list(extra_ops):
        s = o.get("expense") or o.get("income")
        inst = ctx.acc(s["accountId"]).get("instrument", ctx.main)
        if inst != ctx.main:
            need[inst].add(o["date"])
    # get_instrument_rates принимает до 31 даты — режем на пачки
    return {inst: [sorted(ds)[i:i + 31] for i in range(0, len(ds), 31)] for inst, ds in sorted(need.items())}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["needs-rates", "report"])
    p.add_argument("--trip", required=True, help="ID категории-поездки (тега)")
    p.add_argument("--tx", nargs="+", required=True)
    p.add_argument("--wallet-tx", nargs="*")
    p.add_argument("--wallet", nargs="*", help="ID валютных кошельков поездки: из --wallet-tx берутся только их траты")
    p.add_argument("--rates", nargs="*")
    p.add_argument("--categories")
    p.add_argument("--config")
    a = p.parse_args(argv)
    ops, refs = merge_pages(a.tx + (a.wallet_tx or []))
    wallet_ops = merge_pages(a.wallet_tx)[0] if a.wallet_tx else None
    if wallet_ops is not None and a.wallet:
        wallet_ops = [o for o in wallet_ops if (o.get("expense") or o.get("income") or {}).get("accountId") in set(a.wallet)]
    ctx = Ctx(ops, refs, load_categories(a.categories), load_rates(a.rates), load_config(a.config), set())
    if a.trip not in ctx.cats:
        print(json.dumps({"blocking": f"категория {a.trip} не найдена в списке категорий"}, ensure_ascii=False))
        return 2
    out = needs_rates(ctx, a.trip, wallet_ops or []) if a.mode == "needs-rates" else report(ctx, a.trip, wallet_ops)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
