#!/usr/bin/env python3
"""
Регрессионные тесты статистики месяца ZenMoney: month_stats.py (очищенные итоги по
операциям, категории верхнего уровня, поездки, места, сравнение со средним) и запись
spending.json через audit_history.py spending.

Синтетические данные. Запуск из корня репозитория:
    python3 skills/zenmoney-analyst/tests/test_month_stats.py
Без внешних зависимостей.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "skills" / "zenmoney-analyst" / "scripts"))
import audit_history as ah  # noqa: E402
import month_stats as ms  # noqa: E402

PASSED = FAILED = 0


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {detail}")


ACC = {
    "card": {"name": "Карта", "instrument": "RUB", "type": "card", "isInBalance": True},
    "wallet": {"name": "Кошелёк поездки", "instrument": "USD", "type": "cash", "isInBalance": False},
}
CATS = {
    "food": {"name": "Питание", "parentId": None, "isIncome": False, "isExpense": True},
    "cafe": {"name": "Кафе", "parentId": "food", "isIncome": False, "isExpense": True},
    "shop": {"name": "Магазины", "parentId": "food", "isIncome": False, "isExpense": True},
    "taxi": {"name": "Такси", "parentId": "transport", "isIncome": False, "isExpense": True},
    "transport": {"name": "Транспорт", "parentId": None, "isIncome": False, "isExpense": True},
    "corr": {"name": "Корректировка", "parentId": None, "isIncome": True, "isExpense": True},
    "inv": {"name": "Инвестиции", "parentId": None, "isIncome": True, "isExpense": True},
    "inv-fee": {"name": "Комиссия", "parentId": "inv", "isIncome": False, "isExpense": True},
    "cb": {"name": "Кэшбэк", "parentId": None, "isIncome": True, "isExpense": False},
    "partner": {"name": "Общак", "parentId": None, "isIncome": True, "isExpense": False},
    "salary": {"name": "Зарплата", "parentId": None, "isIncome": True, "isExpense": False},
    "trip": {"name": "#Страна'26", "parentId": None, "isIncome": False, "isExpense": True},
}
MERCH = {"m-shop": {"name": "Магазин у дома"}, "m-cafe": {"name": "Кофейня"}}


def op(i, dt, side, acc, amt, cat=None, **kw):
    o = {"id": i, "date": dt, side: {"accountId": acc, "amount": amt}}
    if cat:
        o["categoryId"] = cat
    o.update(kw)
    return o


OPS = [
    op("1", "2026-09-02", "expense", "card", 1000, "shop", merchantId="m-shop"),
    op("2", "2026-09-03", "expense", "card", 500, "shop", merchantId="m-shop"),
    op("3", "2026-09-04", "expense", "card", 300, "cafe", merchantId="m-cafe"),
    op("4", "2026-09-05", "income", "card", 200, "shop", merchantId="m-shop"),       # возврат покупки
    op("5", "2026-09-06", "expense", "card", 400, "taxi", tagIds=["trip"]),            # поездка тегом
    op("6", "2026-09-07", "expense", "wallet", 10, "cafe", tagIds=["trip"]),           # вне баланса, USD
    op("7", "2026-09-08", "expense", "card", 700, "trip"),                             # поездка основной категорией
    op("8", "2026-09-09", "expense", "card", 5000, "corr"),                            # исключение
    op("9", "2026-09-10", "expense", "card", 50, "inv-fee"),                           # исключение (ребёнок)
    op("10", "2026-09-11", "income", "card", 300, "cb"),
    op("11", "2026-09-12", "income", "card", 4000, "partner"),
    op("12", "2026-09-25", "income", "card", 100000, "salary"),
    op("13", "2026-09-13", "expense", "card", 250),                                    # без категории
    {"id": "14", "date": "2026-09-14", "expense": {"accountId": "card", "amount": 9000},
     "income": {"accountId": "wallet", "amount": 100}},                                # перевод — не в базе
    op("15", "2026-08-20", "expense", "card", 999, "shop"),                            # не тот месяц
    op("16", "2026-09-15", "expense", "wallet", 5, "cafe"),                            # нет курса на дату
]
RATES = {"data": [{"instrument": "USD", "date": "2026-09-07", "rate": 90.0}]}


def jdump(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return str(path)


def cli(mod, argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod.main(argv)
    return rc, json.loads(buf.getvalue())


def main():
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        page = {"data": OPS, "nextCursor": None,
                "references": {"user": {"currency": "RUB", "monthStartDay": 1}, "accounts": ACC,
                               "categories": CATS, "merchants": MERCH}}
        base = ["--month", "2026-09", "--as-of", "2026-10-03", "--tx", jdump(t / "p.json", page),
                "--rates", jdump(t / "r.json", RATES)]
        rc, r = cli(ms, base)
        T = r["totals"]

        print("Итоги")
        # расход: 1000+500+300−200+400+900+700+250 = 3850 (USD 5 без курса — не входит)
        check("очищенный расход", T["expense_rub"] == 3850.0, T)
        check("возвраты покупок вычтены и показаны", T["refunds_rub"] == 200.0)
        check("доход без кешбэка и партнёра", T["income_rub"] == 100000.0, T)
        check("вне баланса — кошелёк поездки", T["expense_off_balance_rub"] == 900.0 and T["expense_in_balance_rub"] == 2950.0, T)
        check("переводы и другой месяц не в базе", T["operations"] == 14, T)
        check("закрытый месяц", r["closed"] is True)
        check("валюта без курса — в охвате", r["coverage"]["unconverted"] == {"USD": 1}, r["coverage"])

        print("Регулярные, поездки, разовые")
        check("три корзины: поездки 2000, разовые 0, регулярные 1850",
              (T["expense_trips_rub"], T["expense_one_off_rub"], T["expense_regular_rub"]) == (2000.0, 0.0, 1850.0), T)
        check("корзины в сумме = расход", abs(T["expense_trips_rub"] + T["expense_one_off_rub"] + T["expense_regular_rub"] - T["expense_rub"]) < 0.01)
        reg = {c["name"]: c["rub"] for c in r["categories_regular"]}
        check("регулярные категории без поездки", reg == {"Питание": 1600.0, "Без категории": 250.0}, reg)
        oc = r["outlier_candidates"]
        check("порог кандидатов: не меньше 10 000 ₽", oc["threshold_rub"] == 10000.0 and oc["items"] == [], oc)
        cfg1 = jdump(t / "cfg1.json", {"one_off_ids": ["1"], "outlier_min_rub": 400})
        rc, r1 = cli(ms, base + ["--config", cfg1])
        T1 = r1["totals"]
        check("разовая по карте уходит из регулярных", T1["expense_one_off_rub"] == 1000.0 and T1["expense_regular_rub"] == 850.0, T1)
        check("кандидат в разовые: регулярная трата выше порога", [x["id"] for x in r1["outlier_candidates"]["items"]] == ["2"], r1["outlier_candidates"])
        cfg2 = jdump(t / "cfg2.json", {"outlier_min_rub": 400, "regular_big_ids": ["food"]})
        rc, r2_ = cli(ms, base + ["--config", cfg2])
        check("крупная регулярная (группа по карте) — не кандидат", r2_["outlier_candidates"]["items"] == [], r2_["outlier_candidates"])
        rules = jdump(t / "rules.json", {"schema": "zenmoney-spending-rules@1", "updated": "2026-10-05",
                                         "one_off": [{"id": "1", "month": "2026-09", "note": "техника", "date": "2026-10-05"}],
                                         "regular_big": [{"category_id": "food", "note": "еда", "date": "2026-10-05"}]})
        rc, r3_ = cli(ms, base + ["--rules", rules, "--config", jdump(t / "cfg3.json", {"outlier_min_rub": 400})])
        check("правила (spending-rules.json): разовая уходит из регулярных",
              r3_["totals"]["expense_one_off_rub"] == 1000.0, r3_["totals"])
        check("правила: крупная обычная группа — не кандидат", r3_["outlier_candidates"]["items"] == [], r3_["outlier_candidates"])
        rc, r4_ = cli(ms, base + ["--rules", rules, "--config", jdump(t / "cfg4.json", {"one_off_ids": ["2"]})])
        check("правила и карта объединяются", r4_["totals"]["expense_one_off_rub"] == 1500.0, r4_["totals"])
        # правило сайта (id site-…) заведено без ID операции MCP: находится по тройке op (дата, название счёта, сумма ±0,01)
        site = {"id": "site-0123456789ab", "month": "2026-09", "note": "с сайта", "date": "2026-11-10",
                "op": {"date": "2026-09-03", "account": "Карта", "amount": 500}}
        rules_s = jdump(t / "rules_s.json", {"schema": "zenmoney-spending-rules@1", "updated": "2026-11-10",
                                             "one_off": [site], "one_off_merchants": [], "regular_big": []})
        rc, rs_ = cli(ms, base + ["--rules", rules_s])
        check("правило сайта разрешается по тройке op: разовая 500 ₽",
              rs_["totals"]["expense_one_off_rub"] == 500.0 and rs_["one_off"][0]["note"] == "с сайта", rs_["totals"])
        refs_ = {"accounts": ACC}
        got = ms.resolve_rule_ops([site], OPS, refs_)
        check("resolve_rule_ops: id заменён на ID операции", [x["id"] for x in got] == ["2"], got)
        near = dict(site, op=dict(site["op"], amount=500.004))
        check("сумма ±0,01 — найдена", ms.resolve_rule_ops([near], OPS, refs_)[0]["id"] == "2")
        far = dict(site, op=dict(site["op"], amount=500.5))
        check("сумма дальше 0,01 — не найдена, id прежний", ms.resolve_rule_ops([far], OPS, refs_)[0]["id"] == site["id"])
        other = dict(site, op=dict(site["op"], account="Другой счёт"))
        check("другое название счёта — не найдена", ms.resolve_rule_ops([other], OPS, refs_)[0]["id"] == site["id"])
        twin = OPS + [op("2b", "2026-09-03", "expense", "card", 500, "shop")]
        check("две одинаковые операции — не угадываем, id прежний",
              ms.resolve_rule_ops([site], twin, refs_)[0]["id"] == site["id"])
        known = dict(site, id="2", op=dict(site["op"], amount=1))
        check("правило с найденным ID не трогается (op не перебивает id)", ms.resolve_rule_ops([known], OPS, refs_)[0]["id"] == "2")
        check("правило без op остаётся как есть",
              ms.resolve_rule_ops([{"id": "zz", "month": "2026-09", "note": "н", "date": "2026-10-01"}], OPS, refs_)[0]["id"] == "zz")
        # 2026-10-06: холодильник (разовая) стоял в «Где платил» обычной «Электротехники» —
        # место разовой траты помечается отдельно от того же места в обычных тратах
        mk = {(x["name"], x["kind"]) for x in r3_["merchants"]}
        check("место разовой траты — отдельной строкой с kind=one_off",
              ("Магазин у дома", "one_off") in mk and ("Магазин у дома", "regular") in mk, r3_["merchants"])
        reg_shop = next(x for x in r3_["merchants"] if x["name"] == "Магазин у дома" and x["kind"] == "regular")
        check("в обычном месте разовая не учтена", reg_shop["rub"] == 300.0 and reg_shop["count"] == 2, reg_shop)
        check("поездки в местах не лежат", all(x["kind"] in ("regular", "one_off") for x in r3_["merchants"]))
        check("разовые поштучно с заметкой и без id",
              r3_["one_off"] == [{"name": "Магазин у дома", "rub": 1000.0, "category": "Питание", "note": "техника"}], r3_["one_off"])
        check("без разовых — пустой список", r["one_off"] == [])
        rules_m = jdump(t / "rules_m.json", {"schema": "zenmoney-spending-rules@1", "updated": "2026-10-06", "one_off": [],
                                             "one_off_merchants": [{"merchant_id": "m-cafe", "note": "раз в год", "date": "2026-10-06"}],
                                             "regular_big": []})
        rc, r5_ = cli(ms, base + ["--rules", rules_m])
        check("разовое место: все его траты разовые", r5_["totals"]["expense_one_off_rub"] == 300.0
              and r5_["one_off"] == [{"name": "Кофейня", "rub": 300.0, "category": "Питание", "note": "раз в год"}], r5_["one_off"])
        check("разовое место: поездка в нём остаётся поездкой", r5_["totals"]["expense_trips_rub"] == T["expense_trips_rub"])
        check("поездочная трата не бывает кандидатом", all(x["id"] not in ("5", "6", "7") for x in r1["outlier_candidates"]["items"]))

        print("Исключения")
        ex = r["excluded"]
        check("корректировка отдельно", ex["corrections"] == {"expense_rub": 5000.0, "income_rub": 0.0, "count": 1}, ex)
        check("ребёнок инвестиций наследует исключение", ex["investments"]["expense_rub"] == 50.0)
        check("кешбэк и партнёр — не доход", ex["cashback"]["income_rub"] == 300.0 and ex["partner"]["income_rub"] == 4000.0)

        print("Категории")
        cats = {c["name"]: c for c in r["categories"]}
        check("сворачивание к верхнему уровню", cats["Питание"]["rub"] == 1600.0 + 900.0, cats.get("Питание"))
        check("возврат вычтен из своей группы", cats["Питание"]["count"] == 5)
        check("без категории — своей строкой", cats["Без категории"]["rub"] == 250.0)
        check("поездка основной категорией — своя строка", cats["#Страна'26"]["rub"] == 700.0)
        check("доли в сумме ≈ 1", abs(sum(c["share"] for c in r["categories"]) - 1) < 1e-3)
        check("по убыванию", [c["rub"] for c in r["categories"]] == sorted([c["rub"] for c in r["categories"]], reverse=True))
        check("доходы по категориям", r["income_categories"] == [{"name": "Зарплата", "rub": 100000.0}])

        print("Подкатегории обычных трат")
        subs = [(x["parent"], x["name"], x["rub"], x["count"]) for x in r["subcategories_regular"]]
        check("подкатегории: возврат вычтен, траты без категории — «без подкатегории»",
              subs == [("Питание", "Магазины", 1300.0, 3), ("Питание", "Кафе", 300.0, 1),
                       ("Без категории", "без подкатегории", 250.0, 1)], subs)
        per = {}
        for x in r["subcategories_regular"]:
            per[x["parent"]] = per.get(x["parent"], 0) + x["rub"]
        check("подкатегории родителя в сумме = его обычные траты",
              all(abs(per.get(c["name"], 0) - c["rub"]) < 0.01 for c in r["categories_regular"]), (per, r["categories_regular"]))
        check("поездки и разовые в подкатегории не попадают",
              all(x["name"] != "Такси" for x in r["subcategories_regular"])
              and next(x for x in r3_["subcategories_regular"] if x["name"] == "Магазины")["rub"] == 300.0, r3_["subcategories_regular"])
        page_d = dict(page, data=[op("d1", "2026-09-02", "expense", "card", 70, "food")])
        rc, rd = cli(ms, ["--month", "2026-09", "--as-of", "2026-10-03", "--tx", jdump(t / "pd.json", page_d)])
        check("трата прямо в родителе — «без подкатегории»",
              rd["subcategories_regular"] == [{"parent": "Питание", "name": "без подкатегории", "rub": 70.0, "count": 1}], rd["subcategories_regular"])

        print("Поездки и места")
        check("поездка: тег + основная категория", r["trips"] == [{"name": "#Страна'26", "rub": 2000.0, "count": 3}], r["trips"])
        m = {x["name"]: x for x in r["merchants"]}
        check("место: сумма за вычетом возврата, с подкатегорией",
              m["Магазин у дома"] == {"name": "Магазин у дома", "rub": 1300.0, "count": 3, "category": "Питание", "sub": "Магазины", "kind": "regular"}, m)
        # все места (2026-10-07): траты без места — «без места» в своей подкатегории
        check("без места — строкой в подкатегории", any(x["name"] == "без места" and x.get("rest") and x["category"] == "Без категории"
                                                         and x["sub"] == "без подкатегории" and x["rub"] == 250.0 for x in r["merchants"]), r["merchants"])
        sub_m = {}
        for x in r["merchants"]:
            if x["kind"] == "regular":
                sub_m[(x["category"], x["sub"])] = sub_m.get((x["category"], x["sub"]), 0) + x["rub"]
        check("места подкатегории в сумме = подкатегория",
              all(abs(sub_m.get((s["parent"], s["name"]), 0) - s["rub"]) < 0.01 for s in r["subcategories_regular"]), (sub_m, r["subcategories_regular"]))
        check("доля расхода с местом", r["merchant_share_of_expense"] == round(1600 / 3850, 4))
        rc, r1 = cli(ms, base + ["--top", "1"])
        # --top — мест на категорию; остальное и траты без места — «прочие» (2026-10-06)
        food = [x for x in r1["merchants"] if x["category"] == "Питание"]
        check("--top: на категорию, остальное — «прочие»",
              [x["name"] for x in food] == ["Магазин у дома", "прочие"] and food[1].get("rest") is True
              and food[1]["rub"] == 300.0, food)
        for rr in (r, r1):
            per = {}
            for x in rr["merchants"]:
                if x["kind"] == "regular":
                    per[x["category"]] = per.get(x["category"], 0) + x["rub"]
            check("места категории в сумме = её итог (с «прочими» / «без места»)",
                  all(abs(per.get(c["name"], 0) - c["rub"]) < 0.01 for c in rr["categories_regular"]), (per, rr["categories_regular"]))

        print("Без карты и с картой")
        cfg = jdump(t / "cfg.json", {"excluded_categories": {"corr": "corrections"}})
        rc, rc_ = cli(ms, base + ["--config", cfg])
        check("excluded_categories из карты заменяет умолчания", set(rc_["excluded"]) == {"corrections"}, rc_["excluded"])

        print("Запись и сравнение")
        sp = t / "audit" / "spending.json"
        rc, s = cli(ah, ["spending", "--run", jdump(t / "s9.json", r), "--spending", str(sp)])
        check("dry-run не пишет", rc == 0 and not sp.exists() and s["written"] is False, s)
        prev = []
        for mon, k in (("2026-06", 1.0), ("2026-07", 2.0), ("2026-08", 3.0)):
            cats_prev = [{"name": "Питание", "rub": 1000.0 * k, "count": 1, "share": 1.0},
                         {"name": "Старое", "rub": 1.0, "count": 1, "share": 0.0}]
            rr = dict(r, month=mon, as_of=f"{mon}-28", closed=True,
                      totals=dict(T, expense_rub=1000.0 * k, income_rub=50000.0, expense_regular_rub=1000.0 * k),
                      categories=cats_prev, categories_regular=cats_prev)
            rc, s = cli(ah, ["spending", "--run", jdump(t / f"s{mon}.json", rr), "--spending", str(sp), "--write"])
            prev.append(s)
        check("три месяца записаны", prev[-1]["months_total"] == 3 and sp.exists(), prev[-1])
        rc, r2 = cli(ms, base + ["--spending", str(sp)])
        c = r2["compare"]
        check("среднее за 3 предыдущих", c["months_used"] == ["2026-06", "2026-07", "2026-08"] and c["expense_avg_rub"] == 2000.0, c)
        check("отклонение расхода", c["expense_delta_share"] == round(3850 / 2000 - 1, 4))
        pc = {x["name"]: x for x in c["categories"]}
        check("категория к среднему", pc["Питание"]["avg_rub"] == 2000.0)
        check("сравнение категорий — по регулярным тратам", c["categories_basis"] == "regular" and "Транспорт" not in pc, c["categories_basis"])
        check("регулярный расход к среднему", c["expense_regular_avg_rub"] == 2000.0 and c["expense_regular_delta_share"] == round(1850 / 2000 - 1, 4), c)
        check("новой категории среднее 0 → без доли", pc["Без категории"]["avg_rub"] == 0.0 and pc["Без категории"]["delta_share"] is None)
        check("пропавшая категория названа", c["categories_absent_this_month"] == ["Старое"])
        rc, r0 = cli(ms, base)
        check("без истории — compare null", r0["compare"] is None and r0["coverage"]["history"] == "нет истории")
        rc, s = cli(ah, ["spending", "--run", jdump(t / "s9b.json", r2), "--spending", str(sp), "--write"])
        rc, s = cli(ah, ["spending", "--run", str(t / "s9b.json"), "--spending", str(sp), "--write"])
        check("повтор месяца — замена", s["record"] == "заменена" and s["months_total"] == 4, s)
        S = json.loads(sp.read_text(encoding="utf-8"))
        check("в записи нет сравнения, охвата и кандидатов-операций",
              not {"compare", "coverage", "outlier_candidates"} & set(S["months"][-1]))
        check("регулярные категории сохраняются", S["months"][-1]["categories_regular"] == r2["categories_regular"])
        rc, s1 = cli(ah, ["spending", "--run", jdump(t / "s9c.json", dict(r3_, month="2026-09", closed=True)), "--spending", str(sp), "--write"])
        S = json.loads(sp.read_text(encoding="utf-8"))
        check("разовые и kind мест проходят в историю", rc == 0 and S["months"][-1]["one_off"] == r3_["one_off"]
              and all("kind" in x for x in S["months"][-1]["merchants"]), s1)
        check("бэкап", sp.with_suffix(".json.bak").exists())

        check("подкатегории проходят в историю", S["months"][-1]["subcategories_regular"] == r3_["subcategories_regular"])

        print("Пересчитан ли месяц (recomputed_at)")
        check("замена другими итогами ставит дату пересчёта", s1["recomputed"] is True
              and S["months"][-1]["recomputed_at"] == r3_["as_of"], s1)
        before = S["months"][-1].get("recomputed_at")
        same = dict(r3_, month="2026-09", closed=True, as_of="2026-10-09")
        rc, s2 = cli(ah, ["spending", "--run", jdump(t / "same.json", same), "--spending", str(sp), "--write"])
        S = json.loads(sp.read_text(encoding="utf-8"))
        check("те же итоги — не «пересчитан», дата прежняя",
              s2["recomputed"] is False and S["months"][-1].get("recomputed_at") == before, s2)
        legacy = json.loads(sp.read_text(encoding="utf-8"))
        legacy["months"][-1].pop("subcategories_regular")
        sp.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        rc, s3 = cli(ah, ["spending", "--run", str(t / "same.json"), "--spending", str(sp), "--write"])
        check("появление подкатегорий в старой записи — не «пересчитан»", s3["recomputed"] is False, s3)
        moved = json.loads(json.dumps(same))
        moved["as_of"] = "2026-10-10"
        moved["categories_regular"] = [dict(c, rub=c["rub"] - 100) if c["name"] == "Питание" else c for c in moved["categories_regular"]]
        moved["categories_regular"].append({"name": "Транспорт", "rub": 100.0, "count": 1, "share": 0.1})
        rc, s4 = cli(ah, ["spending", "--run", jdump(t / "moved.json", moved), "--spending", str(sp), "--write"])
        S = json.loads(sp.read_text(encoding="utf-8"))
        check("перенос между категориями при тех же суммах — «пересчитан» с датой",
              s4["recomputed"] is True and S["months"][-1]["recomputed_at"] == "2026-10-10", s4)
        rc, s5 = cli(ah, ["spending", "--run", jdump(t / "moved2.json", dict(moved, as_of="2026-10-12")), "--spending", str(sp), "--write"])
        S = json.loads(sp.read_text(encoding="utf-8"))
        check("повтор без изменений сохраняет прежнюю дату пересчёта",
              s5["recomputed"] is False and S["months"][-1]["recomputed_at"] == "2026-10-10", S["months"][-1].get("recomputed_at"))
        small = json.loads(json.dumps(moved))
        small["totals"]["expense_rub"] += 0.4
        small["totals"]["operations"] += 3
        rc, s6 = cli(ah, ["spending", "--run", jdump(t / "small.json", small), "--spending", str(sp)])
        check("копейки округления и число операций — не пересчёт", s6["recomputed"] is False, s6)
        badr = json.loads(sp.read_text(encoding="utf-8"))
        badr["months"][-1]["recomputed_at"] = "вчера"
        check("плохая дата пересчёта не пройдёт", any("recomputed_at" in e for e in ah.validate_spending(badr)))

        print("Гейты")
        rc, s = cli(ah, ["spending", "--run", jdump(t / "open.json", dict(r, closed=False)), "--spending", str(sp)])
        check("незакрытый месяц — blocking", rc == 2 and "не закрыт" in s["blocking"], s)
        rc, s = cli(ah, ["spending", "--run", jdump(t / "bad.json", {"schema": "x"}), "--spending", str(sp)])
        check("чужой вход — blocking", rc == 2)
        bad = json.loads(sp.read_text(encoding="utf-8"))
        bad["months"][0]["merchants"].append({"name": "x", "rub": 1, "count": 1, "category": "y", "accountId": "card"})
        check("счёт у места не пройдёт", any("недопустимые поля" in e for e in ah.validate_spending(bad)))
        bad2 = json.loads(sp.read_text(encoding="utf-8"))
        bad2["months"][0]["operations"] = []
        check("операции в записи не пройдут", any("недопустимые поля" in e for e in ah.validate_spending(bad2)))
        rc, s = cli(ah, ["validate", "--spending", str(sp)])
        check("validate", rc == 0 and s["ok"], s)

    print(f"\nИтого: {PASSED} OK, {FAILED} FAIL")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
