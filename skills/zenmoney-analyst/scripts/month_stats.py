#!/usr/bin/env python3
"""Статистика месяца ZenMoney по операциям: траты и доходы (Режим D, «закрой месяц»).

Считается из тех же файлов `list_transactions`, что и аудит (`audit_month.py`), — без
лишних вызовов MCP. В отличие от месячного отчёта ZenMoney, учитывает и счета вне
баланса (кошельки поездок); итог «как в приложении» (только счета в балансе) — рядом.

  python3 month_stats.py --month 2026-09 --as-of 2026-10-05 --tx <файлы> --rates <файлы>
      [--categories <файл>] [--config <файл>] [--rules spending-rules.json]
      [--spending spending.json] [--top N]

Места обычных трат (2026-10-07) — ВСЕ места месяца, у каждого — категория и подкатегория
(`sub`); траты без места — строкой «без места» (`rest: true`) в своей подкатегории. Так
сумма мест за любой период точная (раньше хранились 6 крупнейших на категорию, а в «прочие»
уходила пятая часть трат года), и на странице можно смотреть места подкатегории.
`--top N` (N > 0) — старое поведение: N мест на категорию, остальное — «прочие».

Подкатегории обычных трат (2026-10-06) — `subcategories_regular`: родитель, подкатегория,
сумма, число операций; траты прямо в родителе — строкой «без подкатегории». Сумма строк
родителя = его итог в `categories_regular`. Нужны как пояснение «за счёт чего вырос»
к фактам по категориям верхнего уровня; сами факты по подкатегориям не строятся.

Очищенные итоги (принцип 5 SKILL.md): без «Корректировки», инвестиций, кешбэка,
расчётов с партнёром, «Возврата», займов; возвраты покупок (доход в расходной
категории) вычитаются из своей категории. Исключённое — отдельными строками.

Разовые траты (по операции или по месту платежа — «всё в этом месте разовое») и
«крупные обычные» группы — из `--rules` (spending-rules.json, ведёт
`audit_history.py rules` по ответам пользователя) и из конфига карты (`one_off_ids`,
`regular_big_ids`) — объединением.

С `--spending` (история, пишет `audit_history.py spending`) — сравнение со средним
за до 3 предыдущих месяцев. Только stdlib, ничего не пишет, JSON в stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_month import (Ctx, d, kind, load_categories, load_config, load_mcp,  # noqa: E402
                         load_rates, merge_pages, month_bounds, norm_name)

# Группы исключений по умолчанию (без карты) — по названию корневой категории
DEFAULT_EXCLUDED = {
    "корректировка": "corrections",
    "инвестиции": "investments",
    "кэшбэк": "cashback", "кешбэк": "cashback",
    "общак": "partner",
    "возврат": "refund_category",
    "взялучленасемьи": "loans",
}
NO_CATEGORY = "Без категории"
DIRECT_SUB = "без подкатегории"     # трата прямо в родительской категории
OUTLIER_MIN_RUB = 10000      # кандидат в разовые: не меньше этой суммы
OUTLIER_SHARE = 0.10         # … и не меньше этой доли регулярного расхода месяца


class Stats:
    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        cfg_ex = ctx.cfg.get("excluded_categories")
        if cfg_ex:
            self.excluded = dict(cfg_ex)
        else:
            self.excluded = {cid: DEFAULT_EXCLUDED[norm_name(c.get("name", ""))]
                             for cid, c in ctx.cats.items() if norm_name(c.get("name", "")) in DEFAULT_EXCLUDED}

    def root(self, cid):
        c = self.ctx.cats.get(cid) or {}
        return c.get("parentId") or cid

    def group(self, cid):
        """Группа исключения категории (наследуется от родителя) или None."""
        if not cid:
            return None
        return self.excluded.get(cid) or self.excluded.get(self.root(cid))

    def is_refund(self, op):
        """Доход в расходной категории = возврат покупки."""
        c = self.ctx.cats.get(op.get("categoryId")) or {}
        return kind(op) == "income" and c.get("isExpense") is True and c.get("isIncome") is not True

    def in_balance(self, op):
        return self.ctx.acc((op.get("expense") or op.get("income"))["accountId"]).get("isInBalance") is not False


def r2(x):
    return round(x, 2)


def compute(ctx: Ctx, month: str, start, end, top: int):
    st = Stats(ctx)
    ops = [o for o in ctx.ops if start <= d(o["date"]) <= end and kind(o) != "transfer"]
    tot = defaultdict(float)
    excluded = defaultdict(lambda: {"expense_rub": 0.0, "income_rub": 0.0, "count": 0})
    cat_exp = defaultdict(lambda: {"rub": 0.0, "count": 0})
    cat_reg = defaultdict(lambda: {"rub": 0.0, "count": 0})
    sub_reg = defaultdict(lambda: {"rub": 0.0, "count": 0})   # (родитель, подкатегория)
    one_off_ids = set(ctx.cfg.get("one_off_ids") or [])
    one_off_merch = set(ctx.cfg.get("one_off_merchant_ids") or [])
    regular_big = set(ctx.cfg.get("regular_big_ids") or [])
    regular_ops = []
    cat_inc = defaultdict(float)
    trips = defaultdict(lambda: {"rub": 0.0, "count": 0})
    # место платежа — отдельно по корзинам: холодильник под «Электротехникой» не должен
    # выглядеть обычной тратой категории
    merch = defaultdict(lambda: {"rub": 0.0, "count": 0, "cats": defaultdict(float)})
    reg_cat = defaultdict(lambda: defaultdict(lambda: {"rub": 0.0, "count": 0}))
    one_off = []
    with_merchant = 0.0
    for o in ops:
        v = ctx.rub(o)
        if v is None:
            continue
        cid, k = o.get("categoryId"), kind(o)
        g = st.group(cid)
        if g:
            e = excluded[g]
            e["expense_rub" if k == "expense" else "income_rub"] += v
            e["count"] += 1
            continue
        root_name = ctx.cat_name(st.root(cid)) if cid else NO_CATEGORY
        bal = st.in_balance(o)
        if k == "expense" or st.is_refund(o):
            sign = 1 if k == "expense" else -1
            if k == "income":
                tot["refunds_rub"] += v
            tot["expense_rub"] += sign * v
            if bal:
                tot["expense_in_balance_rub"] += sign * v
            cat_exp[root_name]["rub"] += sign * v
            cat_exp[root_name]["count"] += 1
            projects = [t for t in (o.get("tagIds") or []) if t in ctx.project_ids]
            if cid in ctx.project_ids:
                projects.append(cid)
            for p in dict.fromkeys(projects):
                trips[ctx.cat_name(p)]["rub"] += sign * v
                trips[ctx.cat_name(p)]["count"] += 1
            # три корзины без пересечений: поездка → разовая (по карте) → регулярная
            bucket = "trips" if projects else ("one_off" if o["id"] in one_off_ids or o.get("merchantId") in one_off_merch
                                                    else "regular")
            tot[f"expense_{bucket}_rub"] += sign * v
            if bucket == "regular":
                cat_reg[root_name]["rub"] += sign * v
                cat_reg[root_name]["count"] += 1
                sub = ctx.cat_name(cid) if cid and st.root(cid) != cid else DIRECT_SUB
                sub_reg[(root_name, sub)]["rub"] += sign * v
                sub_reg[(root_name, sub)]["count"] += 1
                if k == "expense" and cid not in regular_big and st.root(cid) not in regular_big:
                    regular_ops.append((o, v, root_name))
            mid = o.get("merchantId")
            if bucket == "one_off":
                one_off.append((o, sign * v, root_name))
            if bucket == "regular":
                # обычные — по категории и подкатегории: место в своей подкатегории, без места — «без места»
                c = reg_cat[root_name][(sub, mid or None)]
                c["rub"] += sign * v
                c["count"] += 1
            elif mid and bucket == "one_off":
                m = merch[(mid, bucket)]
                m["rub"] += sign * v
                m["count"] += 1
                m["cats"][root_name] += sign * v
            if mid:
                with_merchant += sign * v
        else:
            tot["income_rub"] += v
            if bal:
                tot["income_in_balance_rub"] += v
            cat_inc[root_name] += v
    expense = tot["expense_rub"]
    totals = {k: r2(tot[k]) for k in ("expense_rub", "income_rub", "refunds_rub",
                                      "expense_in_balance_rub", "income_in_balance_rub")}
    totals["expense_off_balance_rub"] = r2(tot["expense_rub"] - tot["expense_in_balance_rub"])
    for b in ("trips", "one_off", "regular"):
        totals[f"expense_{b}_rub"] = r2(tot[f"expense_{b}_rub"])
    totals["operations"] = len(ops)

    def breakdown(src, base):
        return [{"name": n, "rub": r2(x["rub"]), "count": x["count"],
                 "share": round(x["rub"] / base, 4) if base else None}
                for n, x in sorted(src.items(), key=lambda kv: -kv[1]["rub"])]
    categories = breakdown(cat_exp, expense)
    regular = tot["expense_regular_rub"]
    threshold = max(ctx.cfg.get("outlier_min_rub", OUTLIER_MIN_RUB), OUTLIER_SHARE * regular)
    outliers = [{"id": o["id"], "date": o["date"], "rub": r2(v), "category": rn,
                 "merchant": (ctx.refs["merchants"].get(o.get("merchantId")) or {}).get("name") if o.get("merchantId") else None,
                 "comment": o.get("comment")}
                for o, v, rn in sorted(regular_ops, key=lambda x: -x[1]) if v >= threshold]
    # обычные траты: все места по категории и подкатегории, траты без места — строкой
    # «без места» (rest) в своей подкатегории; сумма мест категории = её итог в
    # categories_regular (2026-10-07: раньше 6 мест на категорию и «прочие» — за год в
    # «прочие» уходила пятая часть, места подкатегорий не было видно). С --top N > 0 —
    # старое: N мест на категорию, остальное одной строкой «прочие».
    # Плюс все места разовых; места поездок — в trips.json
    merchants = []
    mname = lambda mid: (ctx.refs["merchants"].get(mid) or {}).get("name") or mid
    for cat, places in sorted(reg_cat.items(), key=lambda kv: -sum(x["rub"] for x in kv[1].values())):
        named = sorted(((k, x) for k, x in places.items() if k[1]), key=lambda kv: -kv[1]["rub"])
        if top:
            for (sub, mid), x in named[:top]:
                merchants.append({"name": mname(mid), "rub": r2(x["rub"]), "count": x["count"], "category": cat, "kind": "regular"})
            rest = [x for _k, x in named[top:]] + [x for k, x in places.items() if not k[1]]
            if rest:
                merchants.append({"name": "прочие", "rub": r2(sum(x["rub"] for x in rest)),
                                  "count": sum(x["count"] for x in rest), "category": cat, "kind": "regular", "rest": True})
            continue
        for (sub, mid), x in named:
            merchants.append({"name": mname(mid), "rub": r2(x["rub"]), "count": x["count"],
                              "category": cat, "sub": sub, "kind": "regular"})
        for (sub, _mid), x in sorted(((k, x) for k, x in places.items() if not k[1]), key=lambda kv: -kv[1]["rub"]):
            merchants.append({"name": "без места", "rub": r2(x["rub"]), "count": x["count"],
                              "category": cat, "sub": sub, "kind": "regular", "rest": True})
    one_m = sorted(((k, m) for k, m in merch.items() if k[1] == "one_off"), key=lambda kv: -kv[1]["rub"])
    for (mid, bucket), m in one_m:
        name = (ctx.refs["merchants"].get(mid) or {}).get("name") or mid
        merchants.append({"name": name, "rub": r2(m["rub"]), "count": m["count"],
                          "category": max(m["cats"].items(), key=lambda kv: kv[1])[0], "kind": bucket})
    notes = ctx.cfg.get("one_off_notes") or {}
    one_off_items = [{"name": (ctx.refs["merchants"].get(o.get("merchantId")) or {}).get("name")
                      or o.get("payee") or rn,
                      "rub": r2(v), "category": rn,
                      "note": notes.get(o["id"]) or notes.get(o.get("merchantId")) or ""}
                     for o, v, rn in sorted(one_off, key=lambda x: -x[1])]
    return {
        "totals": totals,
        "excluded": {g: {"expense_rub": r2(x["expense_rub"]), "income_rub": r2(x["income_rub"]), "count": x["count"]}
                     for g, x in sorted(excluded.items())},
        "categories": categories,
        "categories_regular": breakdown(cat_reg, regular),
        # порядок: родители как в categories_regular, внутри — по убыванию суммы
        "subcategories_regular": [{"parent": p, "name": n, "rub": r2(x["rub"]), "count": x["count"]}
                                  for (p, n), x in sorted(sub_reg.items(),
                                                          key=lambda kv: (-cat_reg[kv[0][0]]["rub"], kv[0][0], -kv[1]["rub"]))],
        # кандидаты в разовые — только в ответ, в историю не пишутся (это отдельные операции)
        "outlier_candidates": {"threshold_rub": r2(threshold), "items": outliers},
        "income_categories": [{"name": n, "rub": r2(v)} for n, v in sorted(cat_inc.items(), key=lambda kv: -kv[1])],
        "trips": [{"name": n, "rub": r2(x["rub"]), "count": x["count"]}
                  for n, x in sorted(trips.items(), key=lambda kv: -kv[1]["rub"])],
        "merchants": merchants,
        # разовые траты месяца поштучно: что, сколько, заметка из ответа пользователя (без id операций)
        "one_off": one_off_items,
        "merchant_share_of_expense": round(with_merchant / expense, 4) if expense else None,
    }


def compare(cur, hist, month, n=3):
    """Сравнение со средним за до n предыдущих месяцев из spending.json."""
    prev = [m for m in (hist or {}).get("months", []) if m["month"] < month][-n:]
    if not prev:
        return None
    avg = lambda xs: sum(xs) / len(xs)
    exp_avg = avg([m["totals"]["expense_rub"] for m in prev])
    inc_avg = avg([m["totals"]["income_rub"] for m in prev])
    # категории сравниваем по регулярным тратам: поездки и разовые ломают «обычный месяц»
    key = "categories_regular" if all("categories_regular" in m for m in prev) else "categories"
    reg_prev = [m["totals"].get("expense_regular_rub") for m in prev]
    reg_avg = avg(reg_prev) if all(x is not None for x in reg_prev) else None
    cats = []
    for c in cur[key]:
        vals = [next((x["rub"] for x in m[key] if x["name"] == c["name"]), 0.0) for m in prev]
        a = avg(vals)
        cats.append({"name": c["name"], "rub": c["rub"], "avg_rub": r2(a),
                     "delta_share": round(c["rub"] / a - 1, 4) if a else None})
    gone = sorted({x["name"] for m in prev for x in m[key]} - {c["name"] for c in cur[key]})
    return {
        "months_used": [m["month"] for m in prev],
        "expense_avg_rub": r2(exp_avg),
        "expense_delta_share": round(cur["totals"]["expense_rub"] / exp_avg - 1, 4) if exp_avg else None,
        "income_avg_rub": r2(inc_avg),
        "income_delta_share": round(cur["totals"]["income_rub"] / inc_avg - 1, 4) if inc_avg else None,
        "expense_regular_avg_rub": r2(reg_avg) if reg_avg is not None else None,
        "expense_regular_delta_share": (round(cur["totals"]["expense_regular_rub"] / reg_avg - 1, 4)
                                        if reg_avg else None),
        "categories_basis": "regular" if key == "categories_regular" else "all",
        "categories": cats,
        "categories_absent_this_month": gone,
    }


def resolve_rule_ops(one_off, ops, refs):
    """Правила «разовая» с тройкой `op` {date, account, amount}, чей `id` не встретился среди операций, получают
    ID найденной операции: дата, название счёта (refs.accounts), сумма ±0,01 — и ровно одна такая операция.
    Правила сайта (id `site-…`) заведены без ID операции MCP; этой же функцией их находит CSV-путь. → список правил."""
    have = {o["id"] for o in ops}
    pending = [x for x in one_off if x["id"] not in have and isinstance(x.get("op"), dict)]
    if not pending:
        return list(one_off)
    accounts = (refs or {}).get("accounts") or {}
    out = []
    for x in one_off:
        if x not in pending:
            out.append(x)
            continue
        t = x["op"]
        hits = []
        for o in ops:
            if o.get("date") != t.get("date"):
                continue
            s = o.get("expense") or o.get("income")
            if s and (accounts.get(s.get("accountId")) or {}).get("name") == t.get("account") \
                    and abs(float(s["amount"]) - float(t.get("amount", 0))) <= 0.01:
                hits.append(o["id"])
        out.append(dict(x, id=hits[0]) if len(hits) == 1 else x)
    return out


def load_rules(path, cfg, ops=None, refs=None):
    """Слить правила spending-rules.json в конфиг: разовые операции и крупные обычные группы.
    С `ops`/`refs` правила без найденного ID разрешаются по тройке `op` (resolve_rule_ops)."""
    if not path or not Path(path).exists():
        return cfg
    r = json.loads(Path(path).read_text(encoding="utf-8"))
    cfg = dict(cfg)
    if ops is not None:
        r["one_off"] = resolve_rule_ops(r.get("one_off", []), ops, refs)
    cfg["one_off_ids"] = sorted(set(cfg.get("one_off_ids") or []) | {x["id"] for x in r.get("one_off", [])})
    cfg["one_off_notes"] = {**(cfg.get("one_off_notes") or {}),
                            **{x["id"]: x.get("note") or "" for x in r.get("one_off", [])},
                            **{x["merchant_id"]: x.get("note") or "" for x in r.get("one_off_merchants", [])}}
    cfg["one_off_merchant_ids"] = sorted(set(cfg.get("one_off_merchant_ids") or [])
                                         | {x["merchant_id"] for x in r.get("one_off_merchants", [])})
    cfg["regular_big_ids"] = sorted(set(cfg.get("regular_big_ids") or [])
                                    | {x["category_id"] for x in r.get("regular_big", [])})
    return cfg


def run(args):
    ops, refs = merge_pages(args.tx)
    cfg = load_rules(args.rules, load_config(args.config), ops, refs)
    ctx = Ctx(ops, refs, load_categories(args.categories), load_rates(args.rates), cfg, set())
    start_day = int((refs.get("user") or {}).get("monthStartDay") or 1)
    start, end = month_bounds(args.month, start_day)
    as_of = args.as_of or max((o["date"] for o in ops), default=end.isoformat())
    cur = compute(ctx, args.month, start, end, args.top)
    hist = load_mcp(args.spending) if args.spending and Path(args.spending).exists() else None
    return {
        "schema": "zenmoney-month-stats-run@1",
        "month": args.month,
        "period": [start.isoformat(), end.isoformat()],
        "as_of": as_of,
        "closed": d(as_of) > end,
        "main_currency": ctx.main,
        **cur,
        "compare": compare(cur, hist, args.month),
        "coverage": {"unconverted": dict(Counter(i for _o, _a, i in ctx.missing)),
                     "history": "есть" if hist else "нет истории"},
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--month", required=True)
    p.add_argument("--as-of")
    p.add_argument("--tx", nargs="+", required=True)
    p.add_argument("--rates", nargs="*")
    p.add_argument("--categories")
    p.add_argument("--config")
    p.add_argument("--rules", help="spending-rules.json — разовые траты и крупные обычные группы (только чтение)")
    p.add_argument("--spending", help="spending.json — история для сравнения (только чтение)")
    p.add_argument("--top", type=int, default=0, help="0 (по умолчанию) — все места; N — N мест на категорию, остальное «прочие»")
    args = p.parse_args(argv)
    json.dump(run(args), sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
