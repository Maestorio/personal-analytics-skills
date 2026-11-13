#!/usr/bin/env python3
"""Что изменилось в ZenMoney между двумя CSV-выгрузками — перед пересчётом истории.

Зачем (2026-10-07): после правок мест в приложении у четырёх операций слетел тег
поездки, и итоги поездок уменьшились бы молча. Скрипт показывает, что именно
поменял пользователь, и отдельно — то, что пересчёт испортит:
  * операции, потерявшие тег поездки («Путешествия / #…»);
  * операции, исчезнувшие или появившиеся (удаление, смена суммы/счёта/даты);
  * сводку: сколько сменили место («Кому»), категорию, комментарий.

Ключ операции — (время создания, счета, суммы): дата может меняться правкой,
время создания — нет (часовой пояс у одной и той же операции бывает разным,
поэтому берётся только время суток).

  python3 tools/zenmoney_csv_diff.py --old <прошлая.csv> --new <новая.csv> [--top 30]

Ничего не пишет. Выгрузки — личные финансы: лежат в docs/zenmoney/ (в .gitignore).
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter

TRIP = "Путешествия"


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    out = {}
    for x in rows:
        k = (x["createdDate"][11:], x["outcomeAccountName"], x["outcome"], x["incomeAccountName"], x["income"])
        out.setdefault(k, x)
    return out


def tags(cat):
    return [p.strip() for p in (cat or "").split(",") if p.strip().startswith(TRIP)]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--old", required=True)
    p.add_argument("--new", required=True)
    p.add_argument("--top", type=int, default=30)
    a = p.parse_args(argv)
    o, n = load(a.old), load(a.new)
    common = set(o) & set(n)
    fields = Counter()
    payee, cats, lost, gained = Counter(), Counter(), [], []
    for k in common:
        x, y = o[k], n[k]
        for f in x:
            if f != "changedDate" and x[f] != y.get(f):
                fields[f] += 1
        if x["payee"] != y["payee"]:
            payee[(x["payee"], y["payee"])] += 1
        if x["categoryName"] != y["categoryName"]:
            cats[(x["categoryName"], y["categoryName"])] += 1
        tx, ty = tags(x["categoryName"]), tags(y["categoryName"])
        if set(tx) - set(ty):
            lost.append((y["date"], y["outcome"] or y["income"], y["outcomeAccountName"], y["payee"], ", ".join(tx), ", ".join(ty) or "—"))
        elif set(ty) - set(tx):
            gained.append((y["date"], y["outcome"] or y["income"], y["payee"], ", ".join(tx) or "—", ", ".join(ty)))
    print(f"операций: было {len(o)}, стало {len(n)}; только в старой {len(set(o) - set(n))}, только в новой {len(set(n) - set(o))}")
    print("изменено полей:", dict(fields.most_common()) or "ничего")
    print(f"\n!!! потеряли тег поездки: {len(lost)}" + (" — вернуть в приложении ДО пересчёта (итоги поездок уменьшатся)" if lost else ""))
    for r in sorted(lost):
        print(f"  {r[0]}  {r[1]} ₽  {r[2]}  «{r[3]}»: было {r[4]} → стало {r[5]}")
    if gained:
        print(f"\nполучили или сменили тег поездки: {len(gained)}")
        for r in sorted(gained):
            print(f"  {r[0]}  {r[1]}  «{r[2]}»: {r[3]} → {r[4]}")
    for title, src in (("только в старой (удалены или изменены сумма/счёт)", set(o) - set(n)), ("только в новой", set(n) - set(o))):
        if src:
            print(f"\n{title}: {len(src)}")
            for k in sorted(src, key=lambda k: (o.get(k) or n.get(k))["date"])[: a.top]:
                x = o.get(k) or n.get(k)
                print(f"  {x['date']}  {x['outcome'] or x['income']}  {x['outcomeAccountName'] or x['incomeAccountName']}  «{x['payee']}»  {x['categoryName']}")
    if payee:
        print(f"\nместо («Кому») сменилось: {sum(payee.values())} операций, {len(payee)} пар; крупнейшие:")
        for (a_, b_), c in payee.most_common(a.top):
            print(f"  {c:4}  {a_!r} → {b_!r}")
    if cats:
        print(f"\nкатегория сменилась: {sum(cats.values())} операций; крупнейшие:")
        for (a_, b_), c in cats.most_common(a.top):
            print(f"  {c:4}  {a_!r} → {b_!r}")
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
