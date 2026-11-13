#!/usr/bin/env python3
"""
Регрессионные тесты справки по истории ZenMoney: history_query.py (годы, периоды,
категория, масштаб суммы, факты «на что взглянуть») и запись facts.json через
audit_history.py (команда facts и пересчёт после записи месяца).

Синтетическая история 2022-01…2025-12, собранная так, чтобы каждый факт срабатывал
по своей причине. Запуск из корня репозитория:
    python3 skills/zenmoney-analyst/tests/test_history_query.py
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
import history_query as hq  # noqa: E402

PASSED = FAILED = 0


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {detail}")


def month_rec(m, i):
    """Месяц истории. Питание ровное (лёгкий шум), Кафе удваивается с 2025-09 за счёт новой
    подкатегории «Кофейни», Жилище удваивается с 2025-05, Досуг — всплеск только в 2025-12,
    поездки в 2025-03 и 2025-08 дают месяцы с минусом."""
    food = 50000 + (i % 3) * 100
    cafe_r, cafe_k = 10000, (10000 if m >= "2025-09" else 0)
    home = 16000 if m >= "2025-05" else 8000
    fun = 30000 if m == "2025-12" else 3000
    trips = 60000 if m in ("2025-03", "2025-08") else 0
    cats = [("Питание", food, 40), ("Кафе", cafe_r + cafe_k, 10 if not cafe_k else 20),
            ("Жилище", home, 2), ("Досуг", fun, 1)]
    reg = sum(c[1] for c in cats)
    subs = [{"parent": "Питание", "name": "Магазины", "rub": food, "count": 40},
            {"parent": "Кафе", "name": "Рестораны", "rub": cafe_r, "count": 10}]
    if cafe_k:
        subs.append({"parent": "Кафе", "name": "Кофейни", "rub": cafe_k, "count": 10})
    subs += [{"parent": "Жилище", "name": "Квартплата", "rub": home, "count": 2},
             {"parent": "Досуг", "name": hq.DIRECT_SUB, "rub": fun, "count": 1}]
    return {"month": m, "as_of": "2026-01-05",
            "totals": {"expense_rub": reg + trips, "income_rub": 100000.0, "refunds_rub": 0.0,
                       "expense_in_balance_rub": reg + trips, "income_in_balance_rub": 100000.0,
                       "expense_off_balance_rub": 0.0, "expense_trips_rub": float(trips), "expense_one_off_rub": 0.0,
                       "expense_regular_rub": float(reg), "operations": 60},
            "excluded": {}, "categories": [{"name": n, "rub": float(v), "count": c, "share": None} for n, v, c in cats],
            "categories_regular": [{"name": n, "rub": float(v), "count": c, "share": round(v / reg, 4)} for n, v, c in cats],
            "subcategories_regular": subs, "income_categories": [{"name": "Зарплата", "rub": 100000.0}],
            "trips": [], "merchants": [], "one_off": [], "merchant_share_of_expense": None, "unconverted": {}}


MONTHS = hq.span("2022-01", "2025-12")
SP = {"schema": "zenmoney-spending@1", "updated": "2026-01-05", "months": [month_rec(m, i) for i, m in enumerate(MONTHS)]}
SP["months"][-2]["recomputed_at"] = "2026-01-04"
HIST = {"schema": "zenmoney-audit@1", "records": [
    {"month": m, "expense_rub": 100000.0, "correction_rub": c, "correction_transfer_out_rub": t}
    for m, c, t in (("2025-10", 1000.0, 0.0), ("2025-11", 2500.0, 500.0), ("2025-12", 3000.0, 0.0))]}
TAIL = {"schema": "zenmoney-month-stats-run@1", "month": "2026-01", "as_of": "2026-01-06", "closed": False,
        "totals": dict(month_rec("2026-01", 0)["totals"], expense_rub=20000.0, expense_regular_rub=20000.0, income_rub=0.0),
        "categories_regular": [{"name": "Кафе", "rub": 4000.0, "count": 4, "share": 0.2}]}


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
        spf, tailf = jdump(t / "spending.json", SP), jdump(t / "tail.json", TAIL)

        print("Годы")
        rc, y = cli(hq, ["years", "--spending", spf])
        ys = {x["year"]: x for x in y["years"]}
        check("четыре года, все месяцы закрыты", list(ys) == ["2022", "2023", "2024", "2025"]
              and all(x["months_closed"] == 12 for x in ys.values()), list(ys))
        reg24 = sum(month_rec(m, i)["totals"]["expense_regular_rub"] for i, m in enumerate(MONTHS) if m[:4] == "2024") / 12
        check("обычные в месяц за год", ys["2024"]["per_month"]["regular"] == round(reg24, 2), ys["2024"]["per_month"])
        check("изменение к прошлому году", ys["2025"]["regular_change"] == round(ys["2025"]["per_month"]["regular"] / reg24 - 1, 4))
        check("остаток = доход − все расходы", ys["2025"]["per_month"]["flow"] == round(
            (ys["2025"]["sum"]["income"] - ys["2025"]["sum"]["expense"]) / 12, 2))
        check("пересчитанный месяц виден в источнике", y["source"]["recomputed"] == [{"month": "2025-11", "recomputed_at": "2026-01-04"}])
        rc, yt = cli(hq, ["years", "--spending", spf, "--tail", tailf])
        y26 = yt["years"][-1]
        check("текущий месяц: в сумме, не в среднем", y26["year"] == "2026" and y26["months_closed"] == 0
              and y26["per_month"]["regular"] is None and y26["tail"]["sum"]["regular"] == 20000.0, y26)
        check("год только с текущим месяцем — без изменения к прошлому", y26["regular_change"] is None)

        print("Периоды")
        rc, p = cli(hq, ["periods", "--spending", spf, "--a", "2024-01:2024-12", "--b", "2025-01:2025-12",
                         "--category", "Кафе", "--sub"])
        cafe = p["categories"][0]
        check("категория к категории в месяц", cafe["a"]["per_month"] == 10000.0 and cafe["b"]["per_month"] == round(160000 / 12, 2)
              and cafe["change"] == round(160000 / 12 / 10000 - 1, 4), cafe)
        check("подкатегории в периоде", [s["name"] for s in cafe["b"]["sub"]] == ["Рестораны", "Кофейни"], cafe["b"]["sub"])
        check("чаще, а не дороже: средний чек тот же", cafe["a"]["avg_check"] == cafe["b"]["avg_check"] == 1000.0, cafe)
        rc, p2 = cli(hq, ["periods", "--spending", spf, "--a", "2021-12:2022-02", "--b", "2025-12:2026-01", "--tail", tailf])
        check("месяцы вне истории названы", p2["a"]["missing"] == ["2021-12"] and p2["a"]["months_closed"] == 2, p2["a"])
        check("смешанный период: хвост в сумме отдельно", p2["b"]["months_closed"] == 1 and p2["b"]["missing"] == []
              and p2["b"]["sum_with_tail"]["regular"] == p2["b"]["sum"]["regular"] + 20000.0, p2["b"])
        rc, bad = cli(hq, ["periods", "--spending", spf, "--a", "2024-12:2024-01", "--b", "2025-01:2025-02"])
        check("плохой период — blocking", rc == 2 and "период" in bad["blocking"], bad)

        print("Категория")
        rc, c = cli(hq, ["category", "--spending", spf, "--name", "Кафе"])
        check("по годам, доля в обычных", [r["year"] for r in c["rows"]] == ["2022", "2023", "2024", "2025"]
              and c["rows"][0]["share_of_regular"] is not None, c["rows"][0])
        check("месяц появления подкатегории", c["sub_first_seen"] == {"Рестораны": "2022-01", "Кофейни": "2025-09"}, c["sub_first_seen"])
        rc, cm = cli(hq, ["category", "--spending", spf, "--name", "Кафе", "--by", "month"])
        check("по месяцам", len(cm["rows"]) == 48 and cm["rows"][-1]["rub"] == 20000.0)
        rc, cn = cli(hq, ["category", "--spending", spf, "--name", "Нет такой"])
        check("неизвестная категория — blocking", rc == 2)

        print("Масштаб суммы")
        rc, s = cli(hq, ["scale", "--spending", spf, "--amount", "600000"])
        last12 = [month_rec(m, i) for i, m in enumerate(MONTHS)][-12:]
        avg_reg = sum(r["totals"]["expense_regular_rub"] for r in last12) / 12
        check("в месяцах обычных трат", s["months_of_regular"] == round(600000 / avg_reg, 1), s)
        check("в месяцах медианного остатка", s["months_of_median_flow"] == round(600000 / s["flow_median"], 1))
        check("месяцы с минусом посчитаны", s["months_with_minus"] == 3, s)
        rc, bt = cli(hq, ["years", "--spending", spf, "--tail", jdump(t / "t2.json", dict(TAIL, month="2025-12"))])
        check("хвост за закрытый месяц — blocking", rc == 2 and "уже закрыт" in bt["blocking"], bt)

        print("Факты")
        f = hq.compute_facts(SP, HIST)
        kinds = [(x["kind"], x.get("category")) for x in f["facts"]]
        check("на последний закрытый месяц", f["month"] == "2025-12" and f["not_enough_data"] == [], f["not_enough_data"])
        check("незаписанное растёт — первым", kinds[0] == ("unrecorded_rising", None)
              and [x["share"] for x in f["facts"][0]["series"]] == [0.01, 0.02, 0.03], f["facts"][0])
        mm = next(x for x in f["facts"] if x["kind"] == "minus_months")
        check("месяцев с минусом больше, чем год назад", mm["count"] == 3 and mm["count_prev"] == 0
              and [x["month"] for x in mm["months"]] == ["2025-03", "2025-08", "2025-12"], mm)
        check("у минусового месяца названа поездка", mm["months"][0]["with"] == ["trips"], mm["months"][0])
        check("ускорение обычных трат", ("acceleration", None) in kinds)
        check("скачок Кафе", ("jump", "Кафе") in kinds, kinds)
        check("рост Жилища против остальных трат", ("growth", "Жилище") in kinds, kinds)
        check("всплеск одного месяца не держится два закрытия — не факт",
              not any(x.get("category") == "Досуг" for x in f["facts"]), kinds)
        check("Питание растёт как все — не факт", not any(x.get("category") == "Питание" for x in f["facts"]))
        check("метки категорий", f["flagged_categories"] == {"Кафе": ["growth", "jump"], "Жилище": ["growth"]}
              or f["flagged_categories"] == {"Кафе": ["jump", "growth"], "Жилище": ["growth"]}, f["flagged_categories"])
        j = next(x for x in f["facts"] if x["kind"] == "jump")
        check("скачок: медиана, среднее, кратность", j["median_rub"] == 10000.0 and j["recent_avg_rub"] == 20000.0 and j["ratio"] == 2.0, j)
        e = j["explain"]
        # база скачка (12 мес. до окна, 2024-10…2025-09) захватывает первый месяц «Кофеен» — 10,8 покупки в месяц
        check("пояснение: чаще, средний чек тот же", e["count_per_month"] == [10.8, 20.0] and e["avg_check_change"] == 0.0, e)
        ks = {s["name"]: s for s in e["sub"]}
        check("пояснение: новая статья с месяца появления и без процента", ks["Кофейни"]["new_since"] == "2025-09"
              and ks["Кофейни"]["change"] is None and ks["Рестораны"]["new_since"] is None and ks["Рестораны"]["change"] == 0.0, e["sub"])
        g = next(x for x in f["facts"] if x["kind"] == "growth" and x["category"] == "Жилище")
        check("рост: окно к тем же месяцам год назад", g["window"] == ["2025-07", "2025-12"] and g["base"] == ["2024-07", "2024-12"]
              and g["growth"] == 1.0 and g["others_growth"] < g["growth"], g)
        check("в фактах нет служебных полей", not ah.validate_facts(f), ah.validate_facts(f))
        short = dict(SP, months=SP["months"][-10:])
        fs = hq.compute_facts(short, None)
        check("мало истории — факты не выдумываются", fs["facts"] == []
              and set(fs["not_enough_data"]) == {"jump", "growth", "acceleration", "minus_months", "unrecorded_rising"}, fs)
        check("пустая история", hq.compute_facts({"schema": "zenmoney-spending@1", "months": []})["month"] is None)
        old = dict(hq.PARAMS["growth"])
        hq.PARAMS["growth"]["min_gap"] = 5.0
        check("порог из PARAMS действует", not any(x["kind"] == "growth" for x in hq.compute_facts(SP, HIST)["facts"]))
        hq.PARAMS["growth"].update(old)

        print("Запись facts.json")
        a = t / "audit"
        a.mkdir()
        spp, hip = Path(jdump(a / "spending.json", SP)), jdump(a / "history.json", HIST)
        rc, d = cli(ah, ["facts", "--spending", str(spp), "--history", hip])
        check("facts: dry-run не пишет", rc == 0 and not (a / "facts.json").exists() and d["written"] is False, d)
        rc, d = cli(ah, ["facts", "--spending", str(spp), "--history", hip, "--write"])
        F = json.loads((a / "facts.json").read_text(encoding="utf-8"))
        check("facts --write пишет рядом со spending.json", rc == 0 and F["schema"] == hq.FACTS_SCHEMA and F["month"] == "2025-12", d)
        rc, v = cli(ah, ["validate", "--facts", str(a / "facts.json")])
        check("validate facts", rc == 0 and v["ok"], v)
        run = dict(month_rec("2026-01", 0), schema="zenmoney-month-stats-run@1", as_of="2026-02-03", closed=True, coverage={})
        rc, w = cli(ah, ["spending", "--run", jdump(t / "run.json", run), "--spending", str(spp), "--write"])
        F = json.loads((a / "facts.json").read_text(encoding="utf-8"))
        check("запись месяца пересчитывает факты", rc == 0 and w["facts"]["written"] is True and F["month"] == "2026-01", w)
        rc, w2 = cli(ah, ["spending", "--run", jdump(t / "run2.json", dict(run, month="2026-02")), "--spending", str(spp)])
        check("dry-run месяца факты не трогает", "facts" not in w2 and json.loads((a / "facts.json").read_text(encoding="utf-8"))["month"] == "2026-01", w2)
        bad = dict(F, facts=[{"kind": "jump", "_cur": [], "accountId": "x"}])
        check("служебные и запрещённые поля не пройдут", any("запрещённые" in e for e in ah.validate_facts(bad)))
        check("чужой вид факта не пройдёт", any("неизвестный" in e for e in ah.validate_facts(dict(F, facts=[{"kind": "x"}]))))

    print(f"\nИтого: {PASSED} OK, {FAILED} FAIL")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
