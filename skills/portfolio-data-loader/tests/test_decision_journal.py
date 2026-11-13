#!/usr/bin/env python3
"""Тесты журнала решений AIR-1 decision_journal.py (направление, обзоры, сделки, B2, исходы, эпизоды, вопросы, сборка).

Полностью офлайн: обзоры — dict'ы (load_reviews — YAML во временном каталоге), сделки — Trade с rub_amount,
ряды — dict ключ → [(iso, значение)]. Сеть, Synology и git-репозиторий не трогаются
(REPO_ROOT подменяется на каталог без .git). Числа считаются руками (комментарий рядом).
Запуск: python3 skills/portfolio-data-loader/tests/test_decision_journal.py
"""
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import decision_journal as dj  # noqa: E402
from portfolio_returns import Trade  # noqa: E402

PASSED = FAILED = 0


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ✓ {name}")
    else:
        FAILED += 1
        print(f"  ✗ {name}  {detail}")


def near(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol


D = dt.date


def trade(ticker, op, date, rub, name="x"):
    return Trade(ticker, name, op, date, 1, 1, None, None, 0.0, rub, rub, "RUB", "", rub_amount=rub)


def rev(kind, date, doc=None):
    return {"kind": kind, "date": date, "path": Path(f"weekly-review-{kind}-{date}.yaml"), "doc": doc or {}}


# ---------------------------------------------------------------- 1. direction
print("direction")
for v in ("BUY", "ADD"):
    check(f"{v} → +", dj.direction(v) == "+")
for v in ("TRIM", "SELL"):
    check(f"{v} → −", dj.direction(v) == "-")
for v in ("HOLD", "HOLD_TO_MAT", "HOLD_ADD", "RED_FLAG", None, ""):
    check(f"{v!r} → None", dj.direction(v) is None)
check("регистр не важен", dj.direction("trim") == "-" and dj.direction("Add") == "+")

# ---------------------------------------------------------------- 2. review_kind / load_reviews
print("review_kind, load_reviews")
check("kind stock по имени", dj.review_kind(Path("weekly-review-stock-2026-08-01.yaml"), {}) == "stock")
check("kind bond по имени", dj.review_kind(Path("weekly-review-bond-2026-08-01.yaml"), {}) == "bond")
check("легаси → stock", dj.review_kind(Path("weekly-review-2026-05-06.yaml"), {}) == "stock")
check("неизвестное имя → None", dj.review_kind(Path("weekly-review-foo.yaml"), {}) is None)
with tempfile.TemporaryDirectory() as td:
    p = Path(td)
    (p / "weekly-review-stock-2026-08-08.yaml").write_text("review_date: 2026-08-09\nper_stock: {}\n", encoding="utf-8")
    (p / "weekly-review-stock-2026-07-01.yaml").write_text("per_stock: {}\n", encoding="utf-8")
    (p / "weekly-review-bond-2026-08-02.yaml").write_text("per_bond: []\n", encoding="utf-8")
    (p / "weekly-review-2026-05-06.yaml").write_text("{}\n", encoding="utf-8")
    (p / "weekly-review-stock-2026-08-15.yaml.bak").write_text("x: 1\n", encoding="utf-8")
    (p / "weekly-review-stock-2026-08-22.md").write_text("# md\n", encoding="utf-8")
    rs = dj.load_reviews(p)
    check("4 обзора (.bak и .md игнорируются)", len(rs) == 4, str(len(rs)))
    check("сортировка (kind, date): bond первым", [(r["kind"], r["date"]) for r in rs] == [
        ("bond", "2026-08-02"), ("stock", "2026-05-06"), ("stock", "2026-07-01"), ("stock", "2026-08-09")],
        str([(r["kind"], r["date"]) for r in rs]))
    check("review_date из поля, а не из имени", any(r["date"] == "2026-08-09" for r in rs))
    check("дата из имени, если поля нет", any(r["date"] == "2026-07-01" for r in rs))

# ---------------------------------------------------------------- 3. macro_as_of
print("macro_as_of")
check("macro_context.as_of", dj.macro_as_of({"macro_context": {"as_of": "2026-08-01"}}) == "2026-08-01")
check("as_of — объект date", dj.macro_as_of({"macro_context": {"as_of": D(2026, 8, 2)}}) == "2026-08-02")
check("macro_input: дата из строки", dj.macro_as_of({"macro_input": "macro-input-2026-07-30.yaml"}) == "2026-07-30")
check("macro_source: дата из строки", dj.macro_as_of({"macro_source": "chain 2026-07-29"}) == "2026-07-29")
check("macro_context приоритетнее строк", dj.macro_as_of(
    {"macro_context": {"as_of": "2026-08-01"}, "macro_input": "2026-07-01"}) == "2026-08-01")
check("нет — None", dj.macro_as_of({}) is None)

# ---------------------------------------------------------------- 4. positions
print("positions")
ps = dj.positions({"per_stock": {"A": {"x": 1}, "B": "мусор"}}, "stock")
check("per_stock dict: только dict-значения", ps == [("A", {"x": 1})], str(ps))
pb = dj.positions({"per_bond": [{"isin": "RU1", "n": 1}, {"ticker": "T2"}, {"n": 3}, "s"]}, "bond")
check("per_bond список: isin, затем ticker, без ключа пропуск", [k for k, _ in pb] == ["RU1", "T2"], str(pb))
check("нет позиций → []", dj.positions({}, "stock") == [])

# ---------------------------------------------------------------- 5. сделки
print("trades_index, owner_action")
tr = [trade("A", "Покупка", D(2026, 8, 1), 100.0), trade("A", "Продажа", D(2026, 8, 5), -30.0),
      trade("A", "Пополнение", D(2026, 8, 2), 999.0), trade("Деньги RUB", "Покупка", D(2026, 8, 2), 5.0),
      trade("A", "Покупка", D(2026, 8, 10), 50.0)]
ti = dj.trades_index(tr)
check("только Покупка/Продажа, «Деньги» исключены", set(ti) == {"A", "name:x"} and len(ti["A"]) == 3, str(ti))
# регрессия 2026-10-08: обзор держит ОФЗ по ISIN, выгрузка — по SU-коду; совпадает только название
ti2 = dj.trades_index([trade("SU26243RMFS4", "Продажа", D(2026, 9, 20), -500.0, name="ОФЗ 26243")])
a2 = dj.owner_action(ti2, "RU000A106E90", D(2026, 9, 16), D(2026, 9, 26), "ОФЗ 26243")
check("ОФЗ: ISIN из обзора находит сделку по названию → sold", a2["action"] == "sold" and a2["trades"] == 1, str(a2))
check("без названия ISIN сделку не находит → none",
      dj.owner_action(ti2, "RU000A106E90", D(2026, 9, 16), D(2026, 9, 26))["action"] == "none")
check("сумма abs", ti["A"][1] == (D(2026, 8, 5), "sell", 30.0))
oa = dj.owner_action(ti, "A", D(2026, 8, 1), D(2026, 8, 10))
check("окно [d0,d1): сделка в d1 не входит", oa["trades"] == 2 and oa["buy_rub"] == 100.0 and oa["sell_rub"] == 30.0, str(oa))
check("действие bought по большей сумме", oa["action"] == "bought")
check("сделка в день d0 входит", dj.owner_action(ti, "A", D(2026, 8, 1), D(2026, 8, 2))["trades"] == 1)
check("d1=None — до конца", dj.owner_action(ti, "A", D(2026, 8, 1), None)["trades"] == 3)
check("sold, если продано больше", dj.owner_action(ti, "A", D(2026, 8, 5), D(2026, 8, 6))["action"] == "sold")
check("none без сделок", dj.owner_action(ti, "Z", D(2026, 8, 1), None) == {
    "action": "none", "buy_rub": 0, "sell_rub": 0, "trades": 0})

# ---------------------------------------------------------------- 6. concordance
print("concordance")
check("+ и bought → followed", dj.concordance("+", "bought") == "followed")
check("− и sold → followed", dj.concordance("-", "sold") == "followed")
check("+ и sold → contrary", dj.concordance("+", "sold") == "contrary")
check("− и bought → contrary", dj.concordance("-", "bought") == "contrary")
check("направленный без сделок → ignored", dj.concordance("+", "none") == "ignored")
check("HOLD без сделок → n/a", dj.concordance(None, "none") == "n/a")
check("HOLD со сделкой → acted_on_hold", dj.concordance(None, "bought") == "acted_on_hold")

# ---------------------------------------------------------------- 7. b2_action
print("b2_action")
check("план 4, факт 2,9 → add", dj.b2_action(2.9, 4.0) == "add")
check("план 4, факт 5,1 → trim", dj.b2_action(5.1, 4.0) == "trim")
check("план 4, факт 4,9 → none", dj.b2_action(4.9, 4.0) == "none")
check("план 0, факт > 0,1 → trim", dj.b2_action(0.5, 0) == "trim")
check("план 0, факт ≤ 0,1 → none", dj.b2_action(0.1, 0) == "none")
check("None-вход → None", dj.b2_action(None, 4.0) is None and dj.b2_action(4.0, None) is None)

# ---------------------------------------------------------------- 8. stock_outcome
print("stock_outcome")
# d0=2026-07-01, d0+91 = 2026-09-30; цена 100→110, MCFTR 1000→1050, дивиденд 2 (2026-08-01)
# rel_3m = ((110+2)/100 − 1 − 0,05)·100 = 7,0
SER = {"share:A": [("2026-07-01", 100.0), ("2026-09-30", 110.0)],
       "index:MCFTR": [("2026-07-01", 1000.0), ("2026-09-30", 1050.0)]}
DIV = {"A": [{"date": "2026-08-01", "dps_gross": 2.0}]}
o = dj.stock_outcome(SER, DIV, "A", "2026-07-01", D(2026, 10, 1))
check("rel_3m = 7,0", near(o["rel_3m"], 7.0, 1e-3), str(o))
check("12m не созрел → None", o["rel_12m"] is None)
o2 = dj.stock_outcome(SER, DIV, "A", "2026-07-01", D(2026, 9, 29))
check("as_of раньше d0+91 → rel_3m None", o2["rel_3m"] is None, str(o2))
o3 = dj.stock_outcome(SER, DIV, "A", "2026-06-01", D(2026, 10, 1))
check("нет цены на d0 → None", o3["rel_3m"] is None and o3["rel_1m"] is None, str(o3))
o4 = dj.stock_outcome(SER, {"A": [{"date": "2026-07-01", "dps_gross": 2.0}]}, "A", "2026-07-01", D(2026, 10, 1))
check("дивиденд в день d0 не входит: rel = 5,0", near(o4["rel_3m"], 5.0, 1e-3), str(o4))
o5 = dj.stock_outcome(SER, {"A": [{"date": "2026-09-30", "dps_gross": 2.0}]}, "A", "2026-07-01", D(2026, 10, 1))
check("дивиденд в день d1 входит: rel = 7,0", near(o5["rel_3m"], 7.0, 1e-3), str(o5))

# ---------------------------------------------------------------- 9. hit
print("hit")
check("+ и rel>0", dj.hit("+", 1.0) is True)
check("+ и rel<0 → False", dj.hit("+", -1.0) is False)
check("− и rel<0 → True", dj.hit("-", -1.0) is True)
check("− и rel>0 → False", dj.hit("-", 1.0) is False)
check("rel None → None", dj.hit("+", None) is None)
check("без направления → None", dj.hit(None, 1.0) is None)

# ---------------------------------------------------------------- 10. build_records
print("build_records")
AS_OF = D(2026, 12, 31)
empty_tidx = {}
r1 = rev("stock", "2026-08-01", {"per_stock": {"A": {"advisor_verdict": "HOLD", "unconstrained_verdict": "TRIM",
                                                      "name": "Аэро"}}, "revision": {"note": "правка"}})
recs, fl = dj.build_records([r1], empty_tidx, [], {}, {}, AS_OF)
x = recs[0]
check("unconstrained приоритетнее advisor", x["system"]["verdict"] == "TRIM" and x["system"]["direction"] == "-", str(x["system"]))
check("verdict_published сохраняет опубликованный", x["system"]["verdict_published"] == "HOLD")
check("revision → revised_post_hoc", x["revised_post_hoc"] is True)
check("decision_id и имя", x["decision_id"] == "weekly-review-stock-2026-08-01/A" and x["position_name"] == "Аэро")
r2 = rev("stock", "2026-08-01", {"per_stock": {"A": {"advisor_verdict": "BUY"}}})
check("без revision → False", dj.build_records([r2], {}, [], {}, {}, AS_OF)[0][0]["revised_post_hoc"] is False)
rh = rev("stock", "2026-08-01", {"per_stock": {"A": {"advisor_verdict": "BUY"}},
                                 "caveats": [{"severity": "HIGH", "message": "расхождение баз данных"}]})
check("HIGH-caveat «расхождение баз» → data", dj.build_records([rh], {}, [], {}, {}, AS_OF)[0][0]["error_category"] == "data")
rl = rev("stock", "2026-08-01", {"per_stock": {"A": {"advisor_verdict": "BUY"}},
                                 "caveats": [{"severity": "LOW", "message": "расхождение баз"}]})
check("LOW-caveat не даёт data", dj.build_records([rl], {}, [], {}, {}, AS_OF)[0][0]["error_category"] is None)
rs_ = rev("stock", "2026-08-20", {"per_stock": {"A": {"advisor_verdict": "BUY"}}, "macro_context": {"as_of": "2026-08-01"}})
xs = dj.build_records([rs_], {}, [], {}, {}, AS_OF)[0][0]
check("staleness 19 дней > 14 → data", xs["inputs"]["staleness_days"] == 19 and xs["error_category"] == "data", str(xs["inputs"]))
rs2 = rev("stock", "2026-08-15", {"per_stock": {"A": {"advisor_verdict": "BUY"}}, "macro_context": {"as_of": "2026-08-01"}})
check("staleness ровно 14 → не data", dj.build_records([rs2], {}, [], {}, {}, AS_OF)[0][0]["error_category"] is None)
# + и цена 100→90 при плоском индексе: rel_3m = −10 → hit False → forecast
SF = {"share:A": [("2026-01-01", 100.0), ("2026-04-02", 90.0)],
      "index:MCFTR": [("2026-01-01", 1000.0), ("2026-04-02", 1000.0)]}
rf = rev("stock", "2026-01-01", {"per_stock": {"A": {"advisor_verdict": "BUY"}}})
xf = dj.build_records([rf], {}, [], SF, {}, AS_OF)[0][0]
check("hit_3m False → error forecast", xf["outcome"]["hit_3m"] is False and xf["error_category"] == "forecast", str(xf["outcome"]))
check("rel_3m = −10", near(xf["outcome"]["rel_3m"], -10.0, 1e-3))
# план
rp = rev("stock", "2026-08-01", {"per_stock": {"A": {"advisor_verdict": "BUY", "weight_real_pct": 2.0,
                                                      "weight_user_planned_pct": 3.0}}})
xp = dj.build_records([rp], {}, [{"date": "2026-01-01", "stocks": {"A": 0.04}}], {}, {}, AS_OF)[0][0]
check("plan_pct из weight_user_planned_pct", xp["b2"]["plan_pct"] == 3.0 and xp["b2"]["action"] == "add", str(xp["b2"]))
rp2 = rev("stock", "2026-08-01", {"per_stock": {"A": {"advisor_verdict": "BUY", "weight_real_pct": 5.5}}})
xp2 = dj.build_records([rp2], {}, [{"date": "2026-01-01", "stocks": {"A": 0.04}}], {}, {}, AS_OF)[0][0]
check("plan_pct из plan_history (доля ×100)", xp2["b2"]["plan_pct"] == 4.0 and xp2["b2"]["action"] == "trim", str(xp2["b2"]))
# облигации
b1 = rev("bond", "2026-08-01", {"per_bond": [{"isin": "RU1", "advisor_verdict": "BUY"}]})
b2 = rev("bond", "2026-08-08", {"per_bond": [{"isin": "RU1", "advisor_verdict": "BUY"}, {"isin": "RU2", "advisor_verdict": "HOLD"}]})
rb, fb = dj.build_records([b1, b2], {}, [], {}, {}, AS_OF)
check("облигации без рядов: исходы None", all(v is None for r in rb for k, v in r["outcome"].items() if k.startswith("rel_")))
check("рублёвые облигации без рядов — флага USD/EUR нет", not any("USD/EUR" in f for f in fb), str(fb))

# AIR-1b: исходы облигаций против индекса корзины
check("bond_benchmark: USD → None, CNY → RUCNYTR", dj.bond_benchmark({"nominal_currency": "USD"}) is None
      and dj.bond_benchmark({"nominal_currency": "CNY"}) == "index:RUCNYTR")
check("bond_benchmark: ОФЗ 26xxx → RGBITR, ОФЗ 29xxx → RUSFAR, корп. → RUCBTRNS, флоатер → RUSFAR",
      dj.bond_benchmark({"name": "ОФЗ 26243"}) == "index:RGBITR"
      and dj.bond_benchmark({"name": "ОФЗ 29027"}) == "rate_index:RUSFAR"
      and dj.bond_benchmark({"name": "Роделен2P3"}) == "index:RUCBTRNS"
      and dj.bond_benchmark({"name": "X", "is_floater": True}) == "rate_index:RUSFAR")
# грязная цена 1000 → 990, купон 30 в окне → r_b = (990+30)/1000 − 1 = 2%; RUCBTRNS 200 → 202 = 1% → rel = 1,0 п.п.
S = {"bond:RU1": [("2026-05-01", 1000.0), ("2026-07-31", 990.0)],
     "bond_cf:RU1": [("2026-05-01", 99.0), ("2026-06-15", 30.0), ("2026-09-01", 30.0)],
     "index:RUCBTRNS": [("2026-05-01", 200.0), ("2026-07-31", 202.0)]}
o = dj.bond_outcome(S, "RU1", {"name": "Корп"}, "2026-05-01", D(2026, 10, 7))
check("bond_outcome: (990+30)/1000 − 1 − 1% = +1,0 п.п.; купон в день d0 не входит", o["rel_3m"] == 1.0, str(o))
check("bond_outcome: 12 мес. не созрело → None", o["rel_12m"] is None)
o2 = dj.bond_outcome({"bond:RU1": [("2026-05-01", 1000.0)], "bond_cf:RU1": [("2026-06-30", 1030.0)],
                      "index:RUCBTRNS": [("2026-05-01", 200.0), ("2026-07-31", 202.0)]},
                     "RU1", {"name": "Корп", "maturity_date": "2026-06-30"}, "2026-05-01", D(2026, 10, 7))
check("bond_outcome: погашена в окне → цена 0, номинал+купон в выплатах: 3% − 1% = +2,0", o2["rel_3m"] == 2.0, str(o2))
g = (1 + 10 / 100 / 365) ** 91
o3 = dj.bond_outcome({"bond:RU2": [("2026-05-01", 1000.0), ("2026-07-31", 1000.0)], "bond_cf:RU2": [],
                      "rate_index:RUSFAR": [("2026-04-30", 10.0)]},
                     "RU2", {"name": "ОФЗ 29027"}, "2026-05-01", D(2026, 10, 7))
check("bond_outcome: флоатер против RUSFAR-накопления", abs(o3["rel_3m"] - round((0 - (g - 1)) * 100, 3)) < 1e-9, str(o3))
bu = rev("bond", "2026-08-01", {"per_bond": [{"isin": "RU9", "advisor_verdict": "ADD", "nominal_currency": "USD", "name": "ГазКЗ-29Д"}]})
_, fu = dj.build_records([bu], {}, [], {}, {}, AS_OF)
check("USD-облигация → флаг «нет индекса» с числом бумаг", any("USD/EUR" in f and "(бумаг: 1)" in f for f in fu), str(fu))
check("облигации: b2 без доли", rb[0]["b2"]["action"] is None)
check("пустой обзор → флаг «нет позиций»", any("нет позиций" in f for f in dj.build_records([rev("stock", "2026-08-01")], {}, [], {}, {}, AS_OF)[1]))
rt = rev("stock", "2026-08-01", {"per_stock": {"A": {"advisor_verdict": "BUY"}}})
rt2 = rev("stock", "2026-08-08", {"per_stock": {"A": {"advisor_verdict": "HOLD"}}})
rr, _ = dj.build_records([rt, rt2], dj.trades_index([trade("A", "Покупка", D(2026, 8, 3), 10.0)]), [], {}, {}, AS_OF)
check("окно исполнения: покупка 08-03 → followed у первого, n/a у второго",
      rr[0]["owner"]["concordance"] == "followed" and rr[1]["owner"]["concordance"] == "n/a", str([r["owner"] for r in rr]))


# ---------------------------------------------------------------- 11. build_episodes
print("build_episodes")
def rec(cls, pos, date, dir_, verdict=None, conc="ignored", revised=False):
    return {"class": cls, "position": pos, "position_name": pos, "date": date,
            "system": {"direction": dir_, "verdict": verdict or {"-": "TRIM", "+": "BUY", None: "HOLD"}[dir_]},
            "owner": {"concordance": conc}, "outcome": {"hit_3m": None, "rel_3m": date},
            "revised_post_hoc": revised, "decision_id": f"{cls}/{pos}/{date}"}

DATES = ["2026-08-01", "2026-08-08", "2026-08-15"]
revs3 = [rev("stock", d) for d in DATES]
e = dj.build_episodes([rec("stock", "X", d, "-") for d in DATES], revs3, {})
check("три подряд TRIM → один эпизод reviews=3", len(e) == 1 and e[0]["reviews"] == 3, str(e))
check("outcome от первого обзора", e[0]["outcome"]["rel_3m"] == "2026-08-01")
check("episode_id", e[0]["episode_id"] == "stock:X:2026-08-01:-")
e = dj.build_episodes([rec("stock", "X", DATES[0], "-"), rec("stock", "X", DATES[1], None), rec("stock", "X", DATES[2], "-")], revs3, {})
check("TRIM, HOLD, TRIM → два эпизода", len(e) == 2 and [x["first_date"] for x in e] == [DATES[0], DATES[2]], str(e))
e = dj.build_episodes([rec("stock", "X", DATES[0], "-"), rec("stock", "X", DATES[2], "-")], revs3, {})
check("TRIM в 1 и 3, в обзоре 2 нет X → два эпизода", len(e) == 2, str(e))
e = dj.build_episodes([rec("stock", "X", DATES[0], "-"), rec("stock", "X", DATES[1], "+")], revs3, {})
check("смена направления → новый эпизод", len(e) == 2 and {x["direction"] for x in e} == {"+", "-"})
e = dj.build_episodes([rec("stock", "X", DATES[0], "-"), rec("stock", "X", DATES[1], "-", conc="followed"),
                       rec("stock", "X", DATES[2], "-")], revs3, {})
check("followed, если хоть одна запись followed", e[0]["concordance"] == "followed")
e = dj.build_episodes([rec("stock", "X", DATES[0], "-", conc="contrary"), rec("stock", "X", DATES[1], "-")], revs3, {})
check("contrary без followed → contrary", e[0]["concordance"] == "contrary")
e = dj.build_episodes([rec("stock", "X", DATES[0], "-"), rec("stock", "X", DATES[1], "-", revised=True)], revs3, {})
check("revised_post_hoc эпизода = any", e[0]["revised_post_hoc"] is True)
e = dj.build_episodes([rec("stock", "X", DATES[0], "-")], revs3, {"stock:X:2026-08-01:-": "налог"})
check("owner_reason из refusals", e[0]["owner_reason"] == "налог")
e = dj.build_episodes([rec("stock", "X", DATES[0], "-"), rec("stock", "Y", DATES[0], "-")], revs3, {})
check("разные тикеры — разные эпизоды", len(e) == 2)

# ---------------------------------------------------------------- 12. pending_questions
print("pending_questions")
RD = ["2026-08-01", "2026-08-08", "2026-08-15", "2026-08-22", "2026-08-29"]


def ep(date, conc="ignored", reason=None, name="Аэрофлот"):
    return {"episode_id": f"stock:X:{date}:-", "class": "stock", "position": "X", "position_name": name,
            "verdict": "TRIM", "first_date": date, "concordance": conc, "owner_reason": reason}


q = dj.pending_questions([ep(RD[4])], {"stock": RD})
check("эпизод из самого свежего обзора — не спрашивается", q == [])
q = dj.pending_questions([ep(RD[3]), ep(RD[2])], {"stock": RD})
check("два предыдущих обзора — спрашиваются", len(q) == 2, str(q))
check("текст содержит position_name", "Аэрофлот" in q[0]["question"], q[0]["question"])
e_old = ep(RD[1])
q = dj.pending_questions([e_old], {"stock": RD})
check("старше окна — не спрашивается", q == [])
check("и получает owner_reason «не спрашивалось (вне окна вопроса)»", e_old["owner_reason"] == "не спрашивалось (вне окна вопроса)", str(e_old["owner_reason"]))
check("есть ответ — не спрашивается", dj.pending_questions([ep(RD[3], reason="налог")], {"stock": RD}) == [])
check("followed — не спрашивается", dj.pending_questions([ep(RD[3], conc="followed")], {"stock": RD}) == [])
check("contrary — не спрашивается", dj.pending_questions([ep(RD[3], conc="contrary")], {"stock": RD}) == [])

# ---------------------------------------------------------------- 13. plan_change_records
print("plan_change_records")
check("gate_records удалён (файла гейтов нет, шаг 13)", not hasattr(dj, "gate_records"))
H = [{"date": "2026-07-01", "stocks": {"A": 0.5, "B": 0.5}, "bond_buckets": {"x": 1}, "classes": {"s": 0.5}},
     {"date": "2026-08-01", "stocks": {"A": 0.6, "B": 0.4}, "bond_buckets": {"x": 1}, "classes": {"s": 0.5}},
     {"date": "2026-09-01", "stocks": {"A": 0.6, "B": 0.4}, "bond_buckets": {"x": 1}, "classes": {"s": 0.5}},
     {"date": "2026-10-01", "stocks": {"A": 0.6, "B": 0.4}, "bond_buckets": {"y": 1}, "classes": {"s": 0.5}}]
pc = dj.plan_change_records(H)
check("изменение долей → [было, стало] в %", pc[0]["stocks_pct_within_class"] == {"A": [50.0, 60.0], "B": [50.0, 40.0]}, str(pc[0]))
check("без изменений — нет записи (3 пары → 2 записи)", len(pc) == 2 and [p["date"] for p in pc] == ["2026-08-01", "2026-10-01"], str(pc))
check("смена корзин облигаций фиксируется", pc[1]["bond_buckets"] == {"from": {"x": 1}, "to": {"y": 1}} and pc[1]["stocks_pct_within_class"] is None, str(pc[1]))
check("история из одного элемента → []", dj.plan_change_records(H[:1]) == [])

# ---------------------------------------------------------------- 14. summarize
print("summarize")
def sep(cls, hit_, revised=False, conc="followed"):
    return {"class": cls, "outcome": {"hit_3m": hit_}, "revised_post_hoc": revised, "concordance": conc}

eps = [sep("stock", True), sep("stock", False), sep("stock", True, revised=True), sep("stock", None), sep("bond", None, conc="ignored")]
rcs = [{"class": "stock", "system": {"direction": d}} for d in ("+", None, None, "-")] + [{"class": "bond", "system": {"direction": "+"}}]
sm = dj.summarize(eps, rcs)
s = sm["stock"]
check("episodes=4, matured_3m=3, hits_3m=2", (s["episodes"], s["matured_3m"], s["hits_3m"]) == (4, 3, 2), str(s))
check("*_clean исключают revised_post_hoc", (s["matured_3m_clean"], s["hits_3m_clean"]) == (2, 1), str(s))
check("hold_share = 2/4", s["hold_share"] == 0.5, str(s["hold_share"]))
check("verdicts и concordance", s["verdicts"] == 4 and s["concordance"] == {"followed": 4}, str(s))
check("bond: hold_share 0, ignored", sm["bond"]["hold_share"] == 0.0 and sm["bond"]["concordance"] == {"ignored": 1})
check("нет записей → hold_share None", dj.summarize([], [])["stock"]["hold_share"] is None)
check("эпизоды решений в summary не входят",
      dj.summarize([sep("stock", True) | {"kind": "decision"}], [])["stock"]["episodes"] == 0)

# ---------------------------------------------------------------- 15. build
print("build, incidents_monthly")
with tempfile.TemporaryDirectory() as td:
    old_root = dj.REPO_ROOT
    dj.REPO_ROOT = Path(td)
    try:
        (Path(td) / "docs/investment").mkdir(parents=True)
        (Path(td) / "docs/investment/2026-08-19-retro_x.md").write_text("# ретро\n", encoding="utf-8")
        revs = [rev("stock", "2026-08-10", {"per_stock": {"A": {"advisor_verdict": "BUY"}}}),
                rev("stock", "2026-08-17", {"per_stock": {"A": {"advisor_verdict": "BUY"}},
                                            "caveats": [{"severity": "HIGH", "message": "расхождение баз"}]})]
        inputs = {"plan_history": [], "dividends": {}}
        try:
            res = dj.build(revs, [trade("A", "Покупка", D(2026, 8, 1), 10.0)], inputs, {}, {}, {}, D(2026, 8, 30))
            ok = True
        except Exception as ex:  # noqa: BLE001
            ok = False
            print("   исключение:", repr(ex))
        check("build не падает без git", ok)
        if ok:
            check("схема decision-journal@1", res["schema"] == "decision-journal@1" and res["as_of"] == "2026-08-30")
            check("флаг «выгрузка сделок кончается …»", any(f.startswith("выгрузка сделок кончается 2026-08-01") for f in res["flags"]), str(res["flags"]))
            im = res["incidents_monthly"]
            check("retro_docs за 2026-08 = 1", im.get("2026-08", {}).get("retro_docs") == 1, str(im))
            check("коммитов 0 без .git", im.get("2026-08", {}).get("fix_commits") == 0, str(im))
            check("data_flags: один обзор с проблемой данных", im["2026-08"]["data_flags"] == 1, str(im))
            check("records и episodes собраны", len(res["records"]) == 2 and len(res["episodes"]) == 1)
        res2 = dj.build(revs, [trade("A", "Покупка", D(2026, 8, 20), 10.0)], inputs, {}, {}, {}, D(2026, 8, 30))
        check("свежая выгрузка — флага нет", not any("выгрузка сделок" in f for f in res2["flags"]), str(res2["flags"]))
    finally:
        dj.REPO_ROOT = old_root


# ---------------------------------------------------------------- 16. шаг 13: решения, условия, журнал плана
print("шаг 13: deferred_by_condition / owner_decided / ignored")
T0 = "2026-07-30T10:00:00+03:00"


def decision(key, verdict, rec_at=T0, review_by="2026-08-20", created=(), src_kind="report"):
    did = f"{rec_at[:10]}T{rec_at[11:13]}{rec_at[14:16]}-{key}"
    return {"schema_version": "decision@1", "id": did, "key": key, "verdict": verdict, "target_pct": None,
            "review_by": review_by, "note": "почему", "conditions_created": list(created), "conditions_resolved": [],
            "source": {"kind": src_kind, "doc": "Portfolio/reports/r.md", "mode_codes": ["8"], "stress_id": None},
            "author": "model", "recorded_at": rec_at}


def cond(cid, key, created_at=T0, trig_date="2026-12-01", valid_until="2027-01-01", decision_id=None, withdrawn=None):
    return {"id": cid, "version": 1, "key": key, "kind": "review", "trigger": {"type": "date", "value": trig_date},
            "while_pending": {"verdict": "HOLD"}, "on_trigger": {"action": "run_analysis", "text": "разбор"},
            "not_before": None, "valid_until": valid_until, "source": {"kind": "report", "doc": "r.md",
                                                                       "decision_id": decision_id},
            "created_at": created_at, "created_by": "mode_8", "withdrawn": withdrawn, "superseded_by": None}


R13 = [rev("stock", "2026-08-01", {"per_stock": {"X": {"advisor_verdict": "TRIM", "name": "Икс"}}}),
       rev("stock", "2026-08-08", {"per_stock": {"X": {"advisor_verdict": "HOLD", "name": "Икс"}}})]
INP = {"plan_history": [], "dividends": {}}
AS13 = D(2026, 8, 30)
TYPES = {"X": "stock", "Y": "stock"}


def run13(owner, trades=(), reviews=R13, refusals=None):
    with tempfile.TemporaryDirectory() as td:
        old = dj.REPO_ROOT
        dj.REPO_ROOT = Path(td)
        try:
            return dj.build(reviews, list(trades), INP, {}, owner, refusals or {}, AS13)
        finally:
            dj.REPO_ROOT = old


def ep_of(res, kind="review", key="X"):
    return [e for e in res["episodes"] if e.get("kind") == kind and e["position"] == key]


DEC = decision("X", "TRIM", created=["c-1"])
r = run13({"decisions": [DEC], "defs": [cond("c-1", "X")], "events": [], "journal": [], "types": TYPES})
check("условие, созданное решением (conditions_created) и действующее → deferred_by_condition (эпизод обзора)",
      ep_of(r)[0]["concordance"] == "deferred_by_condition", str(ep_of(r)))
check("… и эпизод решения тоже", ep_of(r, "decision")[0]["concordance"] == "deferred_by_condition",
      str(ep_of(r, "decision")))
check("запись обзора тоже различает", r["records"][0]["owner"]["concordance"] == "deferred_by_condition",
      str(r["records"][0]["owner"]))
check("отложенное условием — без вопроса об отказе", r["pending_questions"] == [], str(r["pending_questions"]))
check("summary.concordance несёт новый код",
      r["summary"]["stock"]["concordance"] == {"deferred_by_condition": 1}, str(r["summary"]["stock"]))

r = run13({"decisions": [decision("X", "TRIM")], "defs": [cond("c-1", "X", decision_id=DEC["id"])], "events": [],
           "journal": [], "types": TYPES})
check("связь через source.decision_id определения → deferred_by_condition",
      ep_of(r)[0]["concordance"] == "deferred_by_condition", str(ep_of(r)))

r = run13({"decisions": [decision("X", "TRIM")], "defs": [cond("c-1", "X", decision_id="другое")], "events": [],
           "journal": [], "types": TYPES})
check("условие не от решения, ждёт срабатывания (не владельца) → ignored", ep_of(r)[0]["concordance"] == "ignored",
      str(ep_of(r)))
check("ignored → вопрос об отказе один (эпизод решения покрыт эпизодом обзора)",
      [q["episode_id"] for q in r["pending_questions"]] == ["stock:X:2026-08-01:-"], str(r["pending_questions"]))

r = run13({"decisions": [], "defs": [cond("c-2", "X", trig_date="2026-08-05", decision_id=None)], "events": [],
           "journal": [], "types": TYPES})
check("условие без решения, но сработало и ждёт владельца → deferred_by_condition",
      ep_of(r)[0]["concordance"] == "deferred_by_condition", str(ep_of(r)))
r = run13({"decisions": [], "defs": [cond("c-2", "X", trig_date="2026-08-05")],
           "events": [{"condition_id": "c-2", "event": "owner_mark", "at": "2026-08-06T09:00:00+03:00", "by": "owner",
                       "data": {"mark": "deferred", "until": "2026-09-01"}}], "journal": [], "types": TYPES})
check("ждало владельца, но владелец отложил отметкой в окне → owner_decided",
      ep_of(r)[0]["concordance"] == "owner_decided", str(ep_of(r)))

r = run13({"decisions": [DEC], "defs": [cond("c-1", "X", created_at="2026-08-10T10:00:00+03:00")], "events": [],
           "journal": [], "types": TYPES})
check("условие создано после конца окна эпизода → не откладывает его (ignored)",
      ep_of(r)[0]["concordance"] == "ignored", str(ep_of(r)))
r = run13({"decisions": [DEC], "defs": [cond("c-1", "X", withdrawn={"at": "2026-08-03T10:00:00+03:00", "by": "owner",
                                                                    "reason": "x"})],
           "events": [], "journal": [], "types": TYPES})
check("условие снято внутри окна → не действует на конец окна (ignored)", ep_of(r)[0]["concordance"] == "ignored")
r = run13({"decisions": [DEC], "defs": [cond("c-1", "X", withdrawn={"at": "2026-08-20T10:00:00+03:00", "by": "owner",
                                                                    "reason": "x"})],
           "events": [], "journal": [], "types": TYPES})
check("условие снято после окна → на конец окна действовало (deferred_by_condition)",
      ep_of(r)[0]["concordance"] == "deferred_by_condition", str(ep_of(r)))
r = run13({"decisions": [DEC], "defs": [cond("c-1", "X")],
           "events": [{"condition_id": "c-1", "event": "owner_mark", "at": "2026-08-02T09:00:00+03:00", "by": "owner",
                       "data": {"mark": "dismissed"}}], "journal": [], "types": TYPES})
check("условие закрыто владельцем (dismissed) в окне → owner_decided", ep_of(r)[0]["concordance"] == "owner_decided",
      str(ep_of(r)))
r = run13({"decisions": [DEC], "defs": [cond("c-1", "X")],
           "events": [{"condition_id": "c-1", "event": "done", "at": "2026-08-02T09:00:00+03:00", "by": "owner",
                       "data": {"note": "сделал"}}], "journal": [], "types": TYPES})
check("done by: owner в окне → owner_decided", ep_of(r)[0]["concordance"] == "owner_decided")

J_IN = {"ts": "2026-08-03T12:00:00+03:00", "who": "site", "path": "stocks.X.user_plan", "was": "KEEP", "now": "SELL"}
r = run13({"decisions": [], "defs": [], "events": [], "journal": [J_IN], "types": TYPES})
check("правка плана по бумаге в окне закрывает «проигнорировано» → owner_decided",
      ep_of(r)[0]["concordance"] == "owner_decided" and r["pending_questions"] == [], str(ep_of(r)))
r = run13({"decisions": [], "defs": [], "events": [],
           "journal": [{"ts": "2026-08-03T09:00:00", "path": "stocks.X.user_status", "now": "жду"}], "types": TYPES})
check("старая строка журнала плана без пояса (UTC) тоже читается", ep_of(r)[0]["concordance"] == "owner_decided")
r = run13({"decisions": [], "defs": [], "events": [],
           "journal": [J_IN | {"ts": "2026-07-31T12:00:00+03:00"}, J_IN | {"path": "stocks.X.plan_pct"},
                       J_IN | {"path": "stocks.XX.user_plan"}, J_IN | {"ts": "2026-08-09T12:00:00+03:00"}],
           "types": TYPES})
check("правка до окна, после окна, plan_pct и чужая бумага → ignored", ep_of(r)[0]["concordance"] == "ignored",
      str(ep_of(r)))
r = run13({"decisions": [DEC], "defs": [cond("c-1", "X")], "events": [], "journal": [J_IN], "types": TYPES},
          trades=[trade("X", "Продажа", D(2026, 8, 3), 10.0)])
check("сделка важнее условия и плана → followed", ep_of(r)[0]["concordance"] == "followed", str(ep_of(r)))
r = run13({})
check("пустой owner — как до шага 13: ignored, эпизодов решений нет",
      ep_of(r)[0]["concordance"] == "ignored" and r["decisions"] == [] and not ep_of(r, "decision"), str(r["episodes"]))

print("шаг 13: эпизоды решений")
DY = decision("Y", "BUY", rec_at="2026-08-05T11:30:00+03:00", review_by="2026-08-20")
DY2 = decision("Y", "HOLD", rec_at="2026-08-18T11:30:00+03:00", review_by="2026-09-20")
r = run13({"decisions": [DY, DY2], "defs": [], "events": [], "journal": [], "types": TYPES})
ey = ep_of(r, "decision", "Y")
check("направленное решение → эпизод, HOLD — нет", len(ey) == 1 and ey[0]["verdict"] == "BUY", str(ey))
check("окно до следующего решения", (ey[0]["first_date"], ey[0]["last_date"]) == ("2026-08-05", "2026-08-18"), str(ey))
check("поля эпизода решения: decision_id, review_by, источник",
      ey[0]["decision_id"] == DY["id"] and ey[0]["review_by"] == "2026-08-20" and ey[0]["source"]["kind"] == "report"
      and ey[0]["episode_id"] == f"decision:{DY['id']}", str(ey[0]))
check("ignored без эпизода обзора → вопрос по решению",
      any(q["episode_id"] == f"decision:{DY['id']}" for q in r["pending_questions"]), str(r["pending_questions"]))
check("decisions — все решения строкой (вместо gate_changes)",
      [d["decision_id"] for d in r["decisions"]] == [DY["id"], DY2["id"]] and "gate_changes" not in r, str(r.keys()))
check("decisions_summary", r["decisions_summary"] == {"decisions": 2, "directed": 1, "episodes": 1, "closed": 1,
                                                      "concordance": {"ignored": 1}}, str(r["decisions_summary"]))
check("эпизод решения не меняет summary обзоров", r["summary"]["stock"]["episodes"] == 1)
r = run13({"decisions": [DY, DY2], "defs": [], "events": [], "journal": [], "types": TYPES},
          refusals={f"decision:{DY['id']}": "ждал отчёта"})
check("ответ в refusals по episode_id решения → вопроса нет",
      not any(q["episode_id"].startswith("decision:") for q in r["pending_questions"]))
r = run13({"decisions": [DY], "defs": [], "events": [], "journal": [], "types": TYPES})
check("окно ограничено review_by и закрыто", ep_of(r, "decision", "Y")[0]["last_date"] == "2026-08-20"
      and ep_of(r, "decision", "Y")[0]["window_closed"] is True)
with tempfile.TemporaryDirectory() as td:
    old = dj.REPO_ROOT
    dj.REPO_ROOT = Path(td)
    try:
        r = dj.build(R13, [], INP, {}, {"decisions": [DY], "types": TYPES}, {}, D(2026, 10, 1))
    finally:
        dj.REPO_ROOT = old
check("окно закрыто давно → «не спрашивалось (вне окна вопроса)»",
      ep_of(r, "decision", "Y")[0]["owner_reason"] == "не спрашивалось (вне окна вопроса)"
      and not any(q["episode_id"].startswith("decision:") for q in r["pending_questions"]))
specs = dj.series_specs(R13, dj.owner_context(decisions=[DY, decision("RU000A0JX0J2", "SELL")], types={"Y": "stock"}))
check("series_specs: акции и облигации решений в рядах",
      ("share", "Y") in specs and ("bond", "RU000A0JX0J2") in specs and ("share", "X") in specs, str(specs))

print("шаг 13: incidents_monthly, ручные входы, load_owner")
im = dj.incidents_monthly([], [], "2026-08-01", {"incidents": [
    {"id": "i1", "date": "2026-08-03", "what": "a"}, {"id": "i2", "date": "2026-08-04", "what": "b", "corrects": "i1"},
    {"id": "i0", "date": "2026-07-01", "what": "старше since"}]})
check("инциденты владельца по месяцам, уточнения (corrects) не считаются", im.get("2026-08", {}).get("manual") == 1
      and "2026-07" not in im, str(im))
import ds_schemas  # noqa: E402  (рядом с decision_journal через _shared-references)
check("валидатор refusals: без episode_id — ошибка",
      any("episode_id" in e for e in ds_schemas.validate_refusals({"refusals": [{"reason": "x", "answered": "2026-10-09"}]})))
check("валидатор refusals: reason null («пропустить») допустим",
      ds_schemas.validate_refusals({"refusals": [{"episode_id": "e", "reason": None, "answered": D(2026, 10, 9)}]}) == [])
check("валидатор refusals: без даты — ошибка",
      any("нет даты" in e for e in ds_schemas.validate_refusals({"refusals": [{"episode_id": "e", "reason": "x"}]})))
check("валидатор theses: запись-закрытие (closed + note) валидна",
      ds_schemas.validate_theses({"theses": [{"id": "t", "status": "closed", "closed": "2027-10-01", "note": "сбылось"}]}) == [])
check("валидатор theses: без текста — ошибка",
      any("нет текста" in e for e in ds_schemas.validate_theses({"theses": [{"id": "t", "opened": "2026-10-01"}]})))
check("валидатор incidents: без what — ошибка",
      any("what" in e for e in ds_schemas.validate_incidents({"incidents": [{"id": "i", "date": "2026-10-01"}]})))
check("валидатор: чужая schema — ошибка",
      any("schema" in e for e in ds_schemas.validate_refusals({"schema": "x@1", "refusals": []})))
check("валидатор: пустой файл валиден", ds_schemas.validate_refusals(None) == [] and ds_schemas.validate_theses({}) == [])

with tempfile.TemporaryDirectory() as td:
    jd = Path(td) / "decision-journal"
    jd.mkdir()
    (jd / "refusals.yaml").write_text("schema: decision-journal-refusals@1\nrefusals:\n  - reason: забыл\n"
                                      "    answered: 2026-10-09\n", encoding="utf-8")
    ref, th, inc, errs = dj.load_manual(jd)
    check("load_manual: refusals без episode_id → ошибка валидатора, не KeyError", errs and "refusals.yaml" in errs[0]
          and ref == {}, str(errs))
    (jd / "refusals.yaml").write_text("schema: decision-journal-refusals@1\nrefusals:\n  - episode_id: \"e1\"\n"
                                      "    reason: null\n    answered: 2026-10-09\n", encoding="utf-8")
    ref, th, inc, errs = dj.load_manual(jd)
    check("load_manual: «пропустить» → «пропущено»", errs == [] and ref == {"e1": "пропущено"}, str((ref, errs)))

with tempfile.TemporaryDirectory() as td:
    port = Path(td) / "Portfolio"
    (port / "decisions").mkdir(parents=True)
    (port / "decisions" / f"{DEC['id']}.json").write_text(json.dumps(DEC), encoding="utf-8")
    (port / "decisions" / "bad.json").write_text(json.dumps({"id": "bad"}), encoding="utf-8")
    (port / "conditions.yaml").write_text("schema_version: '1.2'\nconditions: []\n", encoding="utf-8")
    (port / "plan-journal.jsonl").write_text(json.dumps(J_IN) + "\nне json\n", encoding="utf-8")
    (port / "security-types.json").write_text(json.dumps({"by_ticker": {"X": {"type": "stock"}}}), encoding="utf-8")
    ow, fl = dj.load_owner(Path(td))
    check("load_owner: валидное решение прочитано, невалидное — флагом",
          [d["id"] for d in ow["decisions"]] == [DEC["id"]] and any("bad.json" in f for f in fl), str(fl))
    check("load_owner: conditions.yaml не формата 2 → флаг, условий нет",
          ow["defs"] == [] and any("conditions@2" in f for f in fl), str(fl))
    check("load_owner: журнал плана (битая строка пропущена) и реестр типов",
          len(ow["journal"]) == 1 and ow["types"] == {"X": "stock"}, str(ow["journal"]))
    (port / "conditions.yaml").write_text("schema_version: conditions@2\nconditions:\n  - id: c-1\n    version: 1\n"
                                          "    key: X\n    trigger: {type: date, value: '2026-12-01'}\n"
                                          "    created_at: '2026-07-30T10:00:00+03:00'\n    withdrawn: null\n",
                                          encoding="utf-8")
    (port / "conditions-state.json").write_text(json.dumps({"schema_version": "conditions-state@1", "events": [
        {"condition_id": "c-1", "event": "fired", "at": "2026-08-02T10:00:00+03:00", "by": "notifier"}]}),
        encoding="utf-8")
    ow, fl = dj.load_owner(Path(td))
    check("load_owner: conditions@2 + состояние", len(ow["defs"]) == 1 and len(ow["events"]) == 1
          and not any("conditions@2" in f for f in fl), str(fl))
    check("load_owner без decisions/ → флаг", any("decisions" in f for f in dj.load_owner(Path(td) / "нет")[1]))
    # годовой архив определений (R23/шаг 12 вьюера: condDefsAll) — условие прошлого года откладывает эпизод старого окна
    DEC_A = decision("X", "TRIM", created=["c-arch"])
    (port / "decisions" / f"{DEC_A['id']}.json").write_text(json.dumps(DEC_A), encoding="utf-8")
    (port / "decisions" / "bad.json").unlink()
    (port / "conditions-state.json").write_text(json.dumps({"schema_version": "conditions-state@1", "events": []}),
                                                encoding="utf-8")
    (port / "conditions.yaml").write_text("schema_version: conditions@2\nconditions: []\n", encoding="utf-8")
    (port / "plan-journal.jsonl").write_text("", encoding="utf-8")       # без правки плана в окне
    ow, fl = dj.load_owner(Path(td))
    r = run13(ow)
    check("без архива условие c-arch не видно → эпизод старого окна ignored", ep_of(r)[0]["concordance"] == "ignored",
          str(ep_of(r)))
    import yaml as _y  # noqa: E402
    (port / "conditions-archive-2026.yaml").write_text(_y.safe_dump(
        {"schema_version": "conditions@2", "conditions": [cond("c-arch", "X", valid_until="2026-08-31")]},
        allow_unicode=True), encoding="utf-8")
    (port / "conditions-archive-2025.yaml").write_text("schema_version: '1.2'\nconditions: []\n", encoding="utf-8")
    (port / "conditions-archive-x.yaml").write_text("schema_version: conditions@2\nconditions: [{id: z, key: X}]\n",
                                                    encoding="utf-8")
    ow, fl = dj.load_owner(Path(td))
    check("load_owner: архивы conditions-archive-ГГГГ.yaml читаются вместе с текущими; чужое имя — нет; архив не формата 2 — флаг",
          [d["id"] for d in ow["defs"]] == ["c-arch"] and any("conditions-archive-2025.yaml" in f for f in fl), str((ow["defs"], fl)))
    r = run13(ow)
    check("условие из архива (создано решением окна) → deferred_by_condition в старом окне",
          ep_of(r)[0]["concordance"] == "deferred_by_condition", str(ep_of(r)))

# ---------------------------------------------------------------- ставки владельца (decision_journal_update)
print("ставки владельца")
import decision_journal_update as dju  # noqa: E402
TH = {"theses": [
    {"id": "a", "event": "USD/RUB ≥ 90", "p": 0.8, "check_date": "2027-10-08", "status": "open"},
    {"id": "b", "event": "X", "p": 0.5, "check_date": "2027-01-01", "status": "open"},
    {"id": "b", "status": "closed", "closed": "2027-01-02", "outcome": True}]}
ot = dju.open_theses(TH)
check("open_theses: закрытая позже запись убирает ставку (append-only)", [t["id"] for t in ot] == ["a"], str(ot))
check("open_theses: пустой/None документ → []", dju.open_theses(None) == [] and dju.open_theses({}) == [])
# регрессия 2026-10-08: даты из YAML приходят объектами date — journal.json падал на json.dumps
otd = dju.open_theses({"theses": [{"id": "d", "status": "open", "check_date": D(2027, 10, 8), "opened": D(2026, 10, 8)}]})
check("open_theses: даты из YAML → ISO-строки, json.dumps не падает",
      otd[0]["check_date"] == "2027-10-08" and isinstance(json.dumps(otd), str), str(otd))
BASE = {"window": {"days": 85}, "bases": {"B2-live": {"b3_minus_base_pp_ann": -0.1, "b3_minus_base_rub": -1.0}}, "flags": []}
JR = {"summary": {"stock": {"matured_3m": 1, "hits_3m": 1}}, "pending_questions": [], "flags": [], "theses": ot}
far = dju.console_summary(BASE, JR, D(2027, 9, 1))
near_ = dju.console_summary(BASE, JR, D(2027, 10, 4))
past = dju.console_summary(BASE, JR, D(2027, 10, 20))
check("ставка: за месяц до проверки — молчит", not any("Ставка" in x for x in far), str(far))
check("ставка: за 4 дня — строка с фразой закрытия", any("через 4 дн.;" in x and "закрой ставку a" in x for x in near_), str(near_))
check("ставка: дата прошла, не закрыта — напоминает", any("сегодня или раньше" in x for x in past), str(past))

# регрессия 2026-10-22: неполная копия Claude-Memory без weekly-reviews — понятный отказ, а не ValueError
import contextlib, io, tempfile  # noqa: E402,E401
with tempfile.TemporaryDirectory() as _m:
    (Path(_m) / "Portfolio" / "weekly-reviews").mkdir(parents=True)
    _err = io.StringIO()
    with contextlib.redirect_stderr(_err):
        _rc = dju.main(["--memory", _m, "--trades", str(Path(_m) / "t.xlsx"), "--offline", "--dry-run"])
    check("нет недельных обзоров — код 2 и объяснение, журнал не тронут",
          _rc == 2 and "Нет недельных обзоров" in _err.getvalue(), _err.getvalue())
# шаг 13: refusals без episode_id — понятная ошибка валидатора ДО сборки (раньше KeyError посреди прогона)
with tempfile.TemporaryDirectory() as _m:
    (Path(_m) / "Portfolio" / "weekly-reviews").mkdir(parents=True)
    (Path(_m) / "Portfolio" / "decision-journal").mkdir(parents=True)
    (Path(_m) / "Portfolio" / "decision-journal" / "refusals.yaml").write_text(
        "schema: decision-journal-refusals@1\nrefusals:\n  - reason: забыл\n    answered: 2026-10-09\n", encoding="utf-8")
    _err = io.StringIO()
    with contextlib.redirect_stderr(_err):
        _rc = dju.main(["--memory", _m, "--trades", str(Path(_m) / "t.xlsx"), "--offline", "--dry-run"])
    check("refusals без episode_id — код 2, текст валидатора, до чтения сделок",
          _rc == 2 and "не прошли валидатор" in _err.getvalue() and "episode_id" in _err.getvalue(), _err.getvalue())
    _err = io.StringIO()
    with contextlib.redirect_stderr(_err):
        _rc = dj.main(["--memory", _m, "--inputs", str(Path(_m) / "нет.json"), "--offline"])
    check("decision_journal.main: то же", _rc == 2 and "episode_id" in _err.getvalue(), _err.getvalue())

print(f"\nИтого: {PASSED} ✓, {FAILED} ✗")
sys.exit(1 if FAILED else 0)
