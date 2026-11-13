#!/usr/bin/env python3
"""Тесты теневых баз AIR-1 shadow_baselines.py (рукава, рынок, книга, цели, полосы D-2, TWR, run).

Полностью офлайн: Market строится из синтетических рядов (dict ключ → [(iso, значение)]),
снапшоты и входы shadow_inputs — dict'ы; сеть, market_series и Synology не трогаются.
Числа в проверках считаются руками (комментарий рядом), допуски явные.
Запуск: python3 skills/portfolio-data-loader/tests/test_shadow_baselines.py
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import shadow_baselines as sb  # noqa: E402

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


def raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc:
        return True
    except Exception:
        return False
    return False


D = dt.date
T0 = D(2026, 7, 8)


def M(series=None, fx_yield=None, t0=T0):
    return sb.Market(series or {}, t0, fx_yield or {})


# Все цены 1.0 → units == ₽ (для тестов полос и ребаланса)
ONE = {"share:A": [("2026-07-01", 1.0)], "share:B": [("2026-07-01", 1.0)],
       "share:C": [("2026-07-01", 1.0)], "index:RGBITR": [("2026-07-01", 1.0)],
       "index:RUCBTRNS": [("2026-07-01", 1.0)], "index:MCFTR": [("2026-07-01", 1.0)],
       "currency:GLDRUB_TOM": [("2026-07-01", 1.0)]}


def book(values, series=None, name="T"):
    """Книга, где стоимость рукава = values[key] ₽ на T0 (цены 1.0, ставка RUSFAR отсутствует)."""
    b = sb.Book(name, M(series if series is not None else ONE))
    for k, v in values.items():
        b.units[k] = v
    return b


W = {"stock:A": 0.3, "stock:B": 0.3, "idx:RGBITR": 0.3, "rate:CASH": 0.1}   # классы: stock .6 / bond .3 / cash .1

# ------------------------------------------------------------------ 1
print("1. key_class / bucket_sleeve")
for key, cls in [("stock:SBER", "stock"), ("idx:MCFTR", "stock"), ("idx:RGBITR", "bond"),
                 ("idx:RUCBTRNS", "bond"), ("cny:RUCNYTR", "bond"), ("fxs:USD", "bond"),
                 ("fxs:EUR", "bond"), ("rate:FLOAT", "bond"), ("gold:GLDRUB_TOM", "gold"),
                 ("rate:OTHER", "other"), ("rate:CASH", "cash")]:
    check(f"key_class({key}) = {cls}", sb.key_class(key) == cls, str(sb.key_class(key)))
check("key_class: неизвестный → ValueError", raises(ValueError, sb.key_class, "foo:BAR"))
check("key_class: rate:XXX (неизвестная ставка) → ValueError", raises(ValueError, sb.key_class, "rate:XXX"))
for bucket, sl in [("USD", "fxs:USD"), ("EUR", "fxs:EUR"), ("CNY", "cny:RUCNYTR"),
                   ("ОФЗ", "idx:RGBITR"), ("ОФЗ/>10", "idx:RGBITR"), ("ОФЗ/Флоат", "rate:FLOAT"),
                   ("КОРП#5", "idx:RUCBTRNS"), ("КОРП/A", "idx:RUCBTRNS"), ("USD#2", "fxs:USD"),
                   ("ОФЗ/Флоат#3", "rate:FLOAT")]:
    check(f"bucket_sleeve({bucket}) = {sl}", sb.bucket_sleeve(bucket) == sl, str(sb.bucket_sleeve(bucket)))
check("bucket_sleeve: неизвестная корзина → ValueError", raises(ValueError, sb.bucket_sleeve, "ГОЛД"))

# ------------------------------------------------------------------ 2
print("2. Market")
m = M({"rate_index:RUSFAR": [("2026-07-01", 10.0)]})
check("rate:CASH на t0 = 1", near(m.price("rate:CASH", T0), 1.0, 1e-12))
check("rate:CASH до t0 = 1", near(m.price("rate:CASH", D(2026, 7, 1)), 1.0, 1e-12))
exp10 = (1 + 0.10 / 365) ** 10
check("RUSFAR 10% постоянно: через 10 дней (1+0,10/365)^10", near(m.price("rate:CASH", T0 + dt.timedelta(10)), exp10, 1e-12),
      str(m.price("rate:CASH", T0 + dt.timedelta(10))))
check("rate:FLOAT и rate:OTHER — тот же множитель", near(m.price("rate:FLOAT", T0 + dt.timedelta(10)), exp10, 1e-12)
      and near(m.price("rate:OTHER", T0 + dt.timedelta(10)), exp10, 1e-12))
# порядок запросов не влияет (кэш накопления): сначала дальняя дата, потом ближняя
m2 = M({"rate_index:RUSFAR": [("2026-07-01", 10.0)]})
m2.price("rate:CASH", T0 + dt.timedelta(30))
check("кэш: ближняя дата после дальней даёт тот же множитель",
      near(m2.price("rate:CASH", T0 + dt.timedelta(10)), exp10, 1e-12))
check("повторный запрос той же даты стабилен",
      near(m2.price("rate:CASH", T0 + dt.timedelta(30)), (1 + 0.10 / 365) ** 30, 1e-12))
# forward-fill ставки: 10% до 07-10 (ставка на начало суток), с 07-10 — 20%; точка 07-10 — пятница
m3 = M({"rate_index:RUSFAR": [("2026-07-08", 10.0), ("2026-07-10", 20.0)]})
exp_ff = (1 + 0.10 / 365) ** 2 * (1 + 0.20 / 365) ** 3      # сутки 07-08, 07-09 по 10%; 07-10, 07-11, 07-12 по 20%
check("forward-fill: смена ставки 07-10, выходные 11–12 на ставке пятницы",
      near(m3.price("rate:CASH", D(2026, 7, 13)), exp_ff, 1e-12), str(m3.price("rate:CASH", D(2026, 7, 13))))
check("нет ряда RUSFAR → ставка 0 → множитель 1", near(M().price("rate:CASH", T0 + dt.timedelta(100)), 1.0, 1e-12))

ms = M({"share:SBER": [("2026-07-08", 100.0), ("2026-07-10", 110.0)],
        "index:MCFTR": [("2026-07-08", 3000.0), ("2026-07-10", 3300.0)],
        "currency:GLDRUB_TOM": [("2026-07-08", 8000.0), ("2026-07-10", 8100.0)]})
check("stock: точка ≤ даты (пятница 07-10 → 110)", ms.price("stock:SBER", D(2026, 7, 10)) == 110.0)
check("stock: между точками → предыдущая (07-09 → 100)", ms.price("stock:SBER", D(2026, 7, 9)) == 100.0)
check("stock: выходной после последней точки → последняя", ms.price("stock:SBER", D(2026, 7, 12)) == 110.0)
check("stock: до первой точки → None", ms.price("stock:SBER", D(2026, 7, 7)) is None)
check("stock: нет ряда → None", ms.price("stock:ZZZ", D(2026, 7, 10)) is None)
check("idx:MCFTR — последняя точка ≤ даты", ms.price("idx:MCFTR", D(2026, 7, 11)) == 3300.0)
check("idx: до первой точки → None", ms.price("idx:MCFTR", D(2026, 7, 1)) is None)
check("gold:GLDRUB_TOM — последняя точка ≤ даты", ms.price("gold:GLDRUB_TOM", D(2026, 7, 9)) == 8000.0)
check("ряды неупорядочены → сортируются", M({"share:Q": [("2026-07-10", 2.0), ("2026-07-08", 1.0)]})
      .price("stock:Q", D(2026, 7, 9)) == 1.0)

mc = M({"index:RUCNYTR": [("2026-07-08", 2.0)], "fx_cbr:CNY": [("2026-07-08", 12.0)]})
check("cny:RUCNYTR = индекс × курс CNY = 2 × 12 = 24", near(mc.price("cny:RUCNYTR", D(2026, 7, 9)), 24.0, 1e-12))
check("cny:RUCNYTR без курса → None", M({"index:RUCNYTR": [("2026-07-08", 2.0)]}).price("cny:RUCNYTR", T0) is None)
check("cny:RUCNYTR без индекса → None", M({"fx_cbr:CNY": [("2026-07-08", 12.0)]}).price("cny:RUCNYTR", T0) is None)

mf = M({"fx_cbr:USD": [("2026-07-01", 90.0)], "fx_cbr:EUR": [("2026-07-01", 100.0)]}, fx_yield={"USD": 0.10})
check("fxs:USD на t0 = курс 90", near(mf.price("fxs:USD", T0), 90.0, 1e-12))
check("fxs:USD через 365 дней = 90 × 1,10 = 99", near(mf.price("fxs:USD", T0 + dt.timedelta(365)), 99.0, 1e-9),
      str(mf.price("fxs:USD", T0 + dt.timedelta(365))))
check("fxs:USD через 73 дня = 90 × 1,1^(73/365)",
      near(mf.price("fxs:USD", T0 + dt.timedelta(73)), 90 * 1.1 ** (73 / 365), 1e-9))
check("fxs:USD до t0: экспонента не отрицательна (= 90)", near(mf.price("fxs:USD", D(2026, 7, 1)), 90.0, 1e-12))
check("fxs:EUR без заданной доходности → просто курс 100", near(mf.price("fxs:EUR", T0 + dt.timedelta(365)), 100.0, 1e-12))
check("fxs:USD без курса → None", M().price("fxs:USD", T0) is None)
check("price: неизвестный ключ → ValueError", raises(ValueError, M().price, "zzz:X", T0))

# ------------------------------------------------------------------ 3
print("3. Book")
bk = sb.Book("B", M({"share:A": [("2026-07-01", 100.0)], "index:MCFTR": [("2026-07-01", 50.0)],
                     "currency:GLDRUB_TOM": [("2026-07-01", 10.0)]}))
bk.units = {"stock:A": 10.0, "rate:CASH": 1000.0, "idx:MCFTR": 4.0, "gold:GLDRUB_TOM": 5.0}
check("nav = 10×100 + 1000 + 4×50 + 5×10 = 2250", near(bk.nav(T0), 2250.0, 1e-9), str(bk.nav(T0)))
bc = bk.by_class(T0)
check("by_class: stock = 1000 + 200, cash = 1000, gold = 50, bond = other = 0",
      near(bc["stock"], 1200) and near(bc["cash"], 1000) and near(bc["gold"], 50)
      and bc["bond"] == 0 and bc["other"] == 0, str(bc))
check("by_class: все 5 классов присутствуют", set(bc) == set(sb.CLASSES))
check("value: нет рукава → 0", bk.value("stock:Q", T0) == 0.0)

b = sb.Book("B", M())
b.add_rub("stock:NOPE", 500.0, T0)
check("add_rub без цены → в rate:CASH", near(b.units.get("rate:CASH", 0), 500.0) and "stock:NOPE" not in b.units, str(b.units))
check("add_rub без цены → флаг с именем базы, ключом и датой",
      len(b.m.flags) == 1 and "B: нет цены stock:NOPE на 2026-07-08" in b.m.flags[0], str(b.m.flags))
b.add_rub("rate:CASH", 100.0, T0)
check("add_rub в rate:CASH накапливает (цена 1)", near(b.units["rate:CASH"], 600.0))
b0p = sb.Book("Z", M({"share:Z": [("2026-07-01", 0.0)]}))
b0p.add_rub("stock:Z", 100.0, T0)
check("add_rub при цене 0 → тоже в кэш (деления на 0 нет)", near(b0p.units.get("rate:CASH", 0), 100.0))
b.units = {"stock:NOPE": 5.0}
check("value без цены → 0 и флаг «рукав считается нулём»",
      b.value("stock:NOPE", T0) == 0.0 and any("рукав считается нулём" in f for f in b.m.flags))

# set_values
sv = sb.Book("S", M({"index:MCFTR": [("2026-07-01", 100.0)]}))
sv.units = {"rate:CASH": 100000.0}
sv.set_values({"idx:MCFTR": 50000.0, "rate:CASH": 50000.0}, T0, "тест")
# оборот = |50000−0| + |50000−100000| = 100000; комиссия 0,05% = 50 ₽
check("set_values: оборот 100000, комиссия 50", near(sv.turnover_rub, 100000.0) and near(sv.commission_rub, 50.0, 1e-9),
      f"{sv.turnover_rub} {sv.commission_rub}")
check("set_values: idx = 500 шт., кэш = 50000 − 50 = 49950",
      near(sv.units["idx:MCFTR"], 500.0, 1e-9) and near(sv.units["rate:CASH"], 49950.0, 1e-9), str(sv.units))
check("set_values: пишет запись в rebalances с датой и причиной", sv.rebalances == ["2026-07-08 тест"], str(sv.rebalances))
sv.set_values({"rate:CASH": 49950.0}, T0, "уход из индекса")
# оборот = |49950−49950| + |0−50000| = 50000; комиссия 25
check("set_values: рукав с целью 0 удаляется", "idx:MCFTR" not in sv.units, str(sv.units))
check("set_values: комиссия накапливается 50 + 25 = 75, кэш 49950 − 25 = 49925",
      near(sv.commission_rub, 75.0, 1e-9) and near(sv.units["rate:CASH"], 49925.0, 1e-9), str(sv.units))
sv2 = sb.Book("S2", M({"index:MCFTR": [("2026-07-01", 100.0)]}))
sv2.units = {"idx:MCFTR": 10.0, "rate:CASH": 500.0}
before = dict(sv2.units)
sv2.set_values({"idx:MCFTR": 1000.5, "rate:CASH": 500.0}, T0, "почти то же")   # оборот 0,5 ₽ < 1
check("set_values: оборот < 1 ₽ → ничего не меняет", sv2.units == before and sv2.commission_rub == 0
      and sv2.turnover_rub == 0 and sv2.rebalances == [], str(sv2.units))
sv2.set_values({"idx:MCFTR": 1000.0, "rate:CASH": 500.0}, T0, "то же")   # ровно текущие
check("set_values: цели = текущие → ничего", sv2.units == before and sv2.rebalances == [])

# pay_dividends
pd_ = sb.Book("P", M({"share:SBER": [("2026-07-01", 100.0)]}))
pd_.units = {"stock:SBER": 100.0, "rate:CASH": 0.0}
divs = {"SBER": [{"date": "2026-07-15", "dps_gross": 10.0}], "LKOH": [{"date": "2026-07-15", "dps_gross": 500.0}]}
pd_.pay_dividends(divs, D(2026, 7, 14))
check("pay_dividends: не в дату выплаты — ничего", near(pd_.units["rate:CASH"], 0.0))
pd_.pay_dividends(divs, D(2026, 7, 15))
check("pay_dividends: 100 × 10 × 0,87 = 870 ₽ в кэш (LKOH не держится — игнор)", near(pd_.units["rate:CASH"], 870.0, 1e-9),
      str(pd_.units))
pd_.pay_dividends(divs, D(2026, 7, 16))
check("pay_dividends: на следующий день повторно не платит", near(pd_.units["rate:CASH"], 870.0, 1e-9))
pd2 = sb.Book("P2", M({"index:MCFTR": [("2026-07-01", 1.0)]}))
pd2.units = {"idx:MCFTR": 100.0}
pd2.pay_dividends({"MCFTR": [{"date": "2026-07-15", "dps_gross": 10.0}]}, D(2026, 7, 15))
check("pay_dividends: индекс (idx:*) дивидендов не получает", "rate:CASH" not in pd2.units)

# ------------------------------------------------------------------ 4
print("4. targets_from_plan")
PLAN = {"date": "2026-07-01",
        "classes": {"stock": 0.4, "bond": 0.4, "gold": 0.05, "other": 0.05, "cash": 0.1},
        "stocks": {"SBER": 0.6, "LKOH": 0.4},
        "stocks_raw_sum_pct": 100.0,
        "bond_buckets": {"USD": 0.2, "CNY": 0.1, "ОФЗ": 0.3, "ОФЗ/Флоат": 0.1, "КОРП#5": 0.2, "КОРП/A": 0.1}}
w = sb.targets_from_plan(PLAN)
check("Σ весов = 1", near(sum(w.values()), 1.0, 1e-12), str(sum(w.values())))
check("акции внутри класса по долям: SBER 0,4×0,6 = 0,24; LKOH 0,16",
      near(w["stock:SBER"], 0.24, 1e-12) and near(w["stock:LKOH"], 0.16, 1e-12))
check("облигации: USD 0,08 · CNY 0,04 · ОФЗ 0,12 · Флоат 0,04 · КОРП (0,2+0,1) 0,12",
      near(w["fxs:USD"], 0.08, 1e-12) and near(w["cny:RUCNYTR"], 0.04, 1e-12)
      and near(w["idx:RGBITR"], 0.12, 1e-12) and near(w["rate:FLOAT"], 0.04, 1e-12)
      and near(w["idx:RUCBTRNS"], 0.12, 1e-12), str(w))
check("золото 0,05 · другое 0,05 · кэш 0,1",
      near(w["gold:GLDRUB_TOM"], 0.05) and near(w["rate:OTHER"], 0.05) and near(w["rate:CASH"], 0.1))

wr = sb.targets_from_plan(PLAN, rub_bond_only=True)
check("rub_bond_only: нет fxs/cny", not any(k.startswith(("fxs:", "cny:")) for k in wr), str(list(wr)))
# рублёвые корзины: ОФЗ .3, Флоат .1, КОРП .3 → Σ .7; ОФЗ = 0,4×0,3/0,7
check("rub_bond_only: ОФЗ = 0,4×0,3/0,7, Флоат = 0,4×0,1/0,7, КОРП = 0,4×0,3/0,7",
      near(wr["idx:RGBITR"], 0.4 * 0.3 / 0.7, 1e-12) and near(wr["rate:FLOAT"], 0.4 * 0.1 / 0.7, 1e-12)
      and near(wr["idx:RUCBTRNS"], 0.4 * 0.3 / 0.7, 1e-12), str(wr))
check("rub_bond_only: класс облигаций остаётся 0,4, Σ = 1",
      near(sum(v for k, v in wr.items() if sb.key_class(k) == "bond"), 0.4, 1e-12) and near(sum(wr.values()), 1.0, 1e-12))

wi = sb.targets_from_plan(PLAN, stock_index=True)
check("stock_index: один idx:MCFTR = 0,4, тикеров нет",
      near(wi["idx:MCFTR"], 0.4) and not any(k.startswith("stock:") for k in wi))
check("stock_index: Σ = 1", near(sum(wi.values()), 1.0, 1e-12))

pe = dict(PLAN, bond_buckets={})
we = sb.targets_from_plan(pe)
check("пустые корзины → весь класс облигаций в idx:RGBITR", near(we["idx:RGBITR"], 0.4) and
      not any(k in we for k in ("fxs:USD", "rate:FLOAT", "idx:RUCBTRNS")), str(we))
check("bond_buckets=None → тоже idx:RGBITR", near(sb.targets_from_plan(dict(PLAN, bond_buckets=None))["idx:RGBITR"], 0.4))
check("корзина с нулевой долей игнорируется", "fxs:USD" not in sb.targets_from_plan(dict(PLAN, bond_buckets={"USD": 0.0, "ОФЗ": 1.0})))
check("нет акций в плане → idx:MCFTR вместо тикеров",
      near(sb.targets_from_plan(dict(PLAN, stocks={}))["idx:MCFTR"], 0.4) and
      near(sb.targets_from_plan(dict(PLAN, stocks=None))["idx:MCFTR"], 0.4))

wf = sb.targets_from_plan(PLAN, frozen_stocks={"GAZP": 1.0}, frozen_buckets={"USD": 0.5, "ОФЗ": 0.5})
check("frozen_stocks подменяет акции плана: только GAZP = 0,4",
      near(wf["stock:GAZP"], 0.4) and "stock:SBER" not in wf and "stock:LKOH" not in wf, str(wf))
check("frozen_buckets подменяет корзины: USD 0,2 · ОФЗ 0,2, прочих нет",
      near(wf["fxs:USD"], 0.2) and near(wf["idx:RGBITR"], 0.2)
      and "cny:RUCNYTR" not in wf and "idx:RUCBTRNS" not in wf, str(wf))
check("frozen: Σ = 1", near(sum(wf.values()), 1.0, 1e-12))

# ------------------------------------------------------------------ 5
print("5. plan_at")
CL_A = {"stock": 0.5, "bond": 0.2, "gold": 0, "other": 0, "cash": 0.3}
CL_B = {"stock": 0.4, "bond": 0.3, "gold": 0, "other": 0, "cash": 0.3}
hist = [{"date": "2026-05-05", "classes": CL_A}, {"date": "2026-06-08", "classes": CL_B},
        {"date": "2026-07-01", "classes": None}, {"date": "2026-08-01"}]
check("plan_at: последняя точка ≤ даты", sb.plan_at(hist, D(2026, 6, 20))["classes"] is CL_B)
check("plan_at: точки без classes (None / нет ключа) пропускаются", sb.plan_at(hist, D(2026, 9, 1))["classes"] is CL_B)
check("plan_at: дата = дате точки → включительно", sb.plan_at(hist, D(2026, 5, 5))["classes"] is CL_A)
check("plan_at: до первой точки → None", sb.plan_at(hist, D(2026, 5, 4)) is None)
check("plan_at: пустая история → None", sb.plan_at([], D(2026, 7, 1)) is None)

# ------------------------------------------------------------------ 6
print("6. band_breach")
bb = book({"stock:A": 300, "stock:B": 300, "idx:RGBITR": 300, "rate:CASH": 100})
check("всё в полосе → (None, None)", sb.band_breach(bb, W, T0) == (None, None), str(sb.band_breach(bb, W, T0)))
bb = book({"stock:A": 360, "stock:B": 300, "idx:RGBITR": 240, "rate:CASH": 100})
sc, why = sb.band_breach(bb, W, T0)
check("акции 66% против 60% (6 п.п.) → 'full', причина про класс stock", sc == "full" and "stock" in why, f"{sc} {why}")
bb = book({"stock:A": 300, "stock:B": 300, "idx:RGBITR": 250, "rate:CASH": 150})
check("облигации 25% / кэш 15% (ровно −5 / +5 п.п.) → не full",
      sb.band_breach(bb, W, T0)[0] != "full", str(sb.band_breach(bb, W, T0)))
bb = book({"stock:A": 325, "stock:B": 325, "idx:RGBITR": 250, "rate:CASH": 100})
# регрессия: 0,65 − 0,6 = 0,05000000000000004 — без BAND_EPS ровно +5 п.п. давал full, а −5 п.п. нет
check("акции 65% против 60% (ровно +5 п.п.) → не full (BAND_EPS)",
      sb.band_breach(bb, W, T0)[0] != "full", str(sb.band_breach(bb, W, T0)))
bb = book({"stock:A": 330, "stock:B": 270, "idx:RGBITR": 300, "rate:CASH": 100})
check("рукав внутри класса отклонён на 10% относительно → в полосе", sb.band_breach(bb, W, T0) == (None, None))
bb = book({"stock:A": 400, "stock:B": 200, "idx:RGBITR": 300, "rate:CASH": 100})
sc, why = sb.band_breach(bb, W, T0)
check("A = 66,7% внутри акций против 50% (+33% отн.) → 'class:stock', причина называет stock:A",
      sc == "class:stock" and "stock:A" in why, f"{sc} {why}")
bb = book({"stock:A": 375, "stock:B": 225, "idx:RGBITR": 300, "rate:CASH": 100})
check("рукав ровно на +25% относительно (62,5% против 50%) → не нарушение", sb.band_breach(bb, W, T0) == (None, None),
      str(sb.band_breach(bb, W, T0)))
bb = book({"stock:A": 300, "stock:B": 290, "stock:C": 10, "idx:RGBITR": 300, "rate:CASH": 100})
sc, why = sb.band_breach(bb, W, T0)
check("держится тикер C без плана (1,7% класса) → 'class:stock', причина про stock:C",
      sc == "class:stock" and "stock:C" in why, f"{sc} {why}")
bb = book({"stock:A": 300, "stock:B": 299.5, "stock:C": 0.5, "idx:RGBITR": 300, "rate:CASH": 100})
check("тикер без плана ≤ 0,1% класса — не нарушение (0,5 из 600 = 0,083%)", sb.band_breach(bb, W, T0) == (None, None),
      str(sb.band_breach(bb, W, T0)))
w_b = {"stock:A": 0.6, "idx:RGBITR": 0.15, "idx:RUCBTRNS": 0.15, "rate:CASH": 0.1}
bb = book({"stock:A": 600, "idx:RGBITR": 240, "idx:RUCBTRNS": 60, "rate:CASH": 100})
sc, why = sb.band_breach(bb, w_b, T0)
check("рукава облигаций проверяются так же: ОФЗ 80% против 50% → 'class:bond'", sc == "class:bond" and "RGBITR" in why, f"{sc} {why}")
check("пустая книга (nav = 0) → (None, None)", sb.band_breach(book({}), W, T0) == (None, None))

# ------------------------------------------------------------------ 7
print("7. rebalance")
rb = book({"stock:A": 400, "stock:B": 200, "idx:RGBITR": 250, "rate:CASH": 150})
sb.rebalance(rb, W, T0, "class:stock", "причина")
# акции 600 → A 300, B 300; оборот 100 + 100 = 200 → комиссия 0,1 из кэша
check("class:stock: акции приведены к 300/300", near(rb.units["stock:A"], 300.0, 1e-9) and near(rb.units["stock:B"], 300.0, 1e-9),
      str(rb.units))
check("class:stock: облигации не тронуты (250)", near(rb.units["idx:RGBITR"], 250.0, 1e-12))
check("class:stock: кэш меняется только на комиссию 0,1 (150 → 149,9)", near(rb.units["rate:CASH"], 149.9, 1e-9) and near(rb.commission_rub, 0.1, 1e-9),
      str(rb.units))
check("class:stock: оборот 200, запись в rebalances", near(rb.turnover_rub, 200.0) and rb.rebalances == ["2026-07-08 причина"])
rb = book({"stock:A": 400, "stock:B": 200, "idx:RGBITR": 250, "rate:CASH": 150})
sb.rebalance(rb, W, T0, "full", "полный")
# цели 300/300/300/100; оборот 100+100+50+50 = 300 → комиссия 0,15; кэш 99,85
check("full: рукава приведены к целям (300/300/300), кэш 100 − 0,15 = 99,85",
      near(rb.units["stock:A"], 300.0, 1e-9) and near(rb.units["stock:B"], 300.0, 1e-9)
      and near(rb.units["idx:RGBITR"], 300.0, 1e-9) and near(rb.units["rate:CASH"], 99.85, 1e-9), str(rb.units))
check("full: комиссия 0,15, nav после = 999,85", near(rb.commission_rub, 0.15, 1e-9) and near(rb.nav(T0), 999.85, 1e-9))
rb = book({"stock:A": 600, "idx:RGBITR": 300, "rate:CASH": 100})
sb.rebalance(rb, W, T0, "class:stock", "в B нет бумаг")
check("class:stock: новый рукав B из плана создаётся (по 300)", near(rb.units.get("stock:B", 0), 300.0, 1e-9) and near(rb.units["stock:A"], 300.0, 1e-9),
      str(rb.units))
rb = book({"stock:A": 300, "stock:C": 300, "idx:RGBITR": 300, "rate:CASH": 100})
sb.rebalance(rb, W, T0, "class:stock", "C без плана")
check("class:stock: тикер без плана (C) продаётся целиком, A и B по 300",
      "stock:C" not in rb.units and near(rb.units["stock:A"], 300.0, 1e-9) and near(rb.units["stock:B"], 300.0, 1e-9), str(rb.units))

# ------------------------------------------------------------------ 8
print("8. deposit_to_deficits")
dd = book({"stock:A": 300, "stock:B": 250, "idx:RGBITR": 150, "rate:CASH": 100})
sb.deposit_to_deficits(dd, W, 100.0, T0)
# nav_after = 900; цели 270/270/270/90; недовесы: A 0, B 20, ОФЗ 120, кэш 0 → Σ 140
check("пополнение пропорционально недовесу: B +100·20/140, ОФЗ +100·120/140; A не растёт",
      near(dd.units["stock:A"], 300.0, 1e-9) and near(dd.units["stock:B"], 250 + 100 * 20 / 140, 1e-9)
      and near(dd.units["idx:RGBITR"], 150 + 100 * 120 / 140, 1e-9), str(dd.units))
check("пополнение: комиссия 0,05% от суммы (0,05) списана из кэша",
      near(dd.commission_rub, 0.05, 1e-12) and near(dd.units["rate:CASH"], 100 - 0.05, 1e-9), str(dd.units))
check("пополнение: nav вырос на сумму минус комиссия", near(dd.nav(T0), 800 + 100 - 0.05, 1e-9))

dd = book({"stock:A": 1000, "stock:B": 1000})
sb.deposit_to_deficits(dd, {"stock:A": 0.3, "stock:B": 0.3}, 100.0, T0)
# вырожденный план (Σw < 1): недовеса нет (цели 630 < 1000) → по целевым долям, +30 каждому.
# При Σw = 1 и положительном пополнении недовес есть всегда — эта ветка достижима только так.
check("недовеса нет → по целевым долям: A +30, B +30 (цены 1)",
      near(dd.units["stock:A"], 1030.0, 1e-9) and near(dd.units["stock:B"], 1030.0, 1e-9), str(dd.units))

dd = book({"stock:A": 300, "idx:RGBITR": 300, "rate:CASH": 400})
sb.deposit_to_deficits(dd, W, 0.0, T0)
check("нулевое пополнение — ничего не меняет", near(dd.units["rate:CASH"], 400.0) and dd.commission_rub == 0)
dd = book({"stock:A": 300, "idx:RGBITR": 300, "rate:CASH": 400})
sb.deposit_to_deficits(dd, W, -150.0, T0)
check("вывод (<0) — из кэша 400 → 250, остальное не тронуто, комиссии нет",
      near(dd.units["rate:CASH"], 250.0, 1e-9) and dd.units["stock:A"] == 300 and dd.units["idx:RGBITR"] == 300
      and dd.commission_rub == 0 and dd.turnover_rub == 0, str(dd.units))
dd = book({"rate:CASH": 100})
sb.deposit_to_deficits(dd, W, -150.0, T0)
check("вывод больше кэша → кэш уходит в минус (не исключение)", near(dd.units["rate:CASH"], -50.0, 1e-9))

# ------------------------------------------------------------------ 9
print("9. initial_from_snapshot")
PR = {"share:SBER": [("2026-07-01", 100.0)], "fx_cbr:USD": [("2026-07-01", 90.0)],
      "fx_cbr:EUR": [("2026-07-01", 100.0)], "index:RUCNYTR": [("2026-07-01", 2.0)],
      "fx_cbr:CNY": [("2026-07-01", 10.0)], "index:RGBITR": [("2026-07-01", 1000.0)],
      "index:RUCBTRNS": [("2026-07-01", 500.0)], "currency:GLDRUB_TOM": [("2026-07-01", 8000.0)]}


def H(ticker, at, value, cur=None, **kw):
    return dict(ticker=ticker, asset_type=at, value_rub=value, nominal_currency=cur, **kw)


snap = {"holdings": [
    H("SBER", "stock", 1000.0),
    H("XS1", "bond", 2000.0, "USD"), H("XS2", "bond", 500.0, "EUR"), H("CNB", "bond", 700.0, "CNY"),
    H("SU29014RMFS", "bond", 300.0, "RUB"), H("SU26238RMFS", "bond", 400.0, "RUB"),
    H("RU000A10XXXX", "bond", 600.0, "RUB"),
    H("SBMM", "fund", 100.0, sector="money_market"), H("TGLD", "fund", 200.0, sector="gold"),
    H("SBGB", "fund", 150.0, sector="bonds_ofz"), H("ZPIF", "fund", 80.0, sector="real_estate"),
    H("FS1", "fund", 50.0),                                   # сектор — из fund_sectors
    H("BLK", "stock", 999.0, status="blocked"), H("BLK2", "stock", 888.0, is_blocked=True),
    H("ZERO", "stock", 0.0), H("NEG", "stock", -5.0),
], "cash": {"total_rub": 5000.0}}
ib = sb.Book("I", M(PR, fx_yield={}))
sb.initial_from_snapshot(ib, snap, T0, {"FS1": "bonds_corp"})
val = lambda k: ib.value(k, T0)  # noqa: E731
check("акция → stock:SBER (1000)", near(val("stock:SBER"), 1000.0, 1e-9))
check("облигация USD → fxs:USD (2000), EUR → fxs:EUR (500)", near(val("fxs:USD"), 2000.0, 1e-9) and near(val("fxs:EUR"), 500.0, 1e-9))
check("облигация CNY → cny:RUCNYTR (700)", near(val("cny:RUCNYTR"), 700.0, 1e-9))
check("SU29014RMFS → rate:FLOAT (300)", near(val("rate:FLOAT"), 300.0, 1e-9))
check("SU26238RMFS + фонд bonds_ofz + фонд bonds_corp (по fund_sectors) → idx:RGBITR (400+150+50 = 600)",
      near(val("idx:RGBITR"), 600.0, 1e-9), str(val("idx:RGBITR")))
check("прочая рублёвая облигация → idx:RUCBTRNS (600)", near(val("idx:RUCBTRNS"), 600.0, 1e-9))
check("TGLD → золото (200)", near(val("gold:GLDRUB_TOM"), 200.0, 1e-9))
check("ЗПИФ (real_estate) → rate:OTHER (80)", near(val("rate:OTHER"), 80.0, 1e-9))
check("money_market (100) + cash.total_rub (5000) → rate:CASH 5100", near(val("rate:CASH"), 5100.0, 1e-9), str(val("rate:CASH")))
check("blocked / is_blocked / value ≤ 0 пропущены", not any(k in ib.units for k in ("stock:BLK", "stock:BLK2", "stock:ZERO", "stock:NEG")),
      str(list(ib.units)))
# Σ незаблокированных: 1000+2000+500+700+300+400+600+100+200+150+80+50 = 6080; + кэш 5000
check("nav книги на t0 = 6080 + 5000 = 11080", near(ib.nav(T0), 11080.0, 1e-9), str(ib.nav(T0)))
check("цен хватает → флагов нет", ib.m.flags == [], str(ib.m.flags))
# регрессия 2026-10-08: снапшот держит ОФЗ по ISIN — распознавать по названию, иначе ОФЗ уходят в корп. индекс
ob = sb.Book("O", M(PR, fx_yield={}))
sb.initial_from_snapshot(ob, {"holdings": [
    H("RU000A106E90", "bond", 400.0, "RUB", name="ОФЗ 26243"),
    H("RU000A10AA93", "bond", 300.0, "RUB", name="ОФЗ 29027"),
    H("RU000A103MX5", "bond", 200.0, "RUB", name="ОФЗ 52004"),
    H("RU000A10B2F7", "bond", 100.0, "RUB", name="Роделен2P3")], "cash": {"total_rub": 0.0}}, T0, {})
check("ОФЗ по ISIN + названию: 26xxx и 52xxx → idx:RGBITR (600)", near(ob.value("idx:RGBITR", T0), 600.0, 1e-9),
      str(ob.units))
check("ОФЗ 29xxx по названию → rate:FLOAT (300)", near(ob.value("rate:FLOAT", T0), 300.0, 1e-9), str(ob.units))
check("корпоративная по ISIN → idx:RUCBTRNS (100)", near(ob.value("idx:RUCBTRNS", T0), 100.0, 1e-9), str(ob.units))
eb = sb.Book("E", M())
sb.initial_from_snapshot(eb, {}, T0, {})
check("пустой снапшот без cash → пустая книга без ошибок", eb.nav(T0) == 0.0)
ib2 = sb.Book("I2", M())
sb.initial_from_snapshot(ib2, {"holdings": [H("SBER", "stock", 1000.0)], "cash": {"total_rub": 10.0}}, T0, {})
check("нет цены акции → стоимость уходит в rate:CASH + флаг", near(ib2.nav(T0), 1010.0, 1e-9) and len(ib2.m.flags) == 1,
      f"{ib2.nav(T0)} {ib2.m.flags}")

# ------------------------------------------------------------------ 10
print("10. fx_yields_from_snapshot")
fy = sb.fx_yields_from_snapshot({"holdings": [
    H("U1", "bond", 1000.0, "USD", ytm_pct=8.0), H("U2", "bond", 3000.0, "USD", ytm_pct=10.0),
    H("E1", "bond", 2000.0, "EUR", ytm_pct=5.0),
    H("C1", "bond", 500.0, "CNY", ytm_pct=12.0),                 # CNY не участвует
    H("U3", "bond", 9000.0, "USD", ytm_pct=None),                # без YTM — не участвует
    H("U4", "bond", 9000.0, "USD", ytm_pct=50.0, status="blocked"),
    H("U5", "bond", 0.0, "USD", ytm_pct=50.0),                   # нулевая стоимость
    H("S1", "stock", 5000.0, "USD", ytm_pct=40.0),
]})
# USD: (8×1000 + 10×3000) / 4000 = 9,5 % = 0,095
check("USD: взвешено по стоимости = 9,5% → 0,095 (доли, не %)", near(fy.get("USD"), 0.095, 1e-9), str(fy))
check("EUR: 5% → 0,05", near(fy.get("EUR"), 0.05, 1e-9), str(fy))
check("CNY / акции / blocked / без YTM не попали", set(fy) == {"USD", "EUR"}, str(fy))
check("нет валютных облигаций → {}", sb.fx_yields_from_snapshot({"holdings": []}) == {} and sb.fx_yields_from_snapshot({}) == {})

# ------------------------------------------------------------------ 11
print("11. twr")
d0, d1, d2 = D(2026, 7, 8), D(2026, 7, 18), D(2026, 7, 28)
r, ann = sb.twr([(d0, 100.0), (d1, 110.0), (d2, 121.0)], [])
check("без потоков: 1,1 × 1,1 − 1 = 0,21", near(r, 0.21, 1e-12), str(r))
check("годовая = 1,21^(365/20) − 1", near(ann, 1.21 ** (365 / 20) - 1, 1e-9), str(ann))
r, ann = sb.twr([(d0, 100.0), (d1, 100.0)], [])
check("без изменения: 0 и 0", near(r, 0, 1e-15) and near(ann, 0, 1e-12))
dY = d0 + dt.timedelta(365)
r, ann = sb.twr([(d0, 1000.0), (dY, 1250.0)], [(D(2026, 12, 1), 200.0)])
# Дитц: (1250 − 1000 − 200) / (1000 + 100) = 50/1100
check("поток 200 посередине: Дитц 50/1100", near(r, 50 / 1100, 1e-12), str(r))
check("365 дней → годовая = за период", near(ann, 50 / 1100, 1e-12), str(ann))
r, ann = sb.twr([(d0, 1000.0), (d0 + dt.timedelta(73), 1250.0)], [(d0 + dt.timedelta(30), 200.0)])
check("73 дня: годовая = (1+r)^5 − 1", near(ann, (1 + 50 / 1100) ** 5 - 1, 1e-9), str(ann))
r, _ = sb.twr([(d0, 1000.0), (d1, 1250.0)], [(d0, 200.0)])
check("поток в день d0 в интервал не входит (d0 < d)", near(r, 0.25, 1e-12), str(r))
r, _ = sb.twr([(d0, 1000.0), (d1, 1250.0)], [(d1, 200.0)])
check("поток в день d1 входит (d ≤ d1)", near(r, 50 / 1100, 1e-12), str(r))
r, _ = sb.twr([(d0, 1000.0), (d1, 1250.0)], [(D(2026, 7, 19), 200.0)])
check("поток после d1 не учитывается", near(r, 0.25, 1e-12), str(r))
r, _ = sb.twr([(d0, 1000.0), (d1, 900.0)], [(D(2026, 7, 10), -200.0)])
# вывод 200: (900 − 1000 + 200) / (1000 − 100) = 100/900
check("вывод −200: Дитц 100/900", near(r, 100 / 900, 1e-12), str(r))
r, _ = sb.twr([(d0, 100.0), (d1, 110.0), (d2, 132.0), (D(2026, 8, 7), 132.0)], [])
check("цепочка из трёх интервалов: 1,1 × 1,2 × 1 − 1 = 0,32", near(r, 0.32, 1e-12), str(r))
check("база = 0 → (None, None)", sb.twr([(d0, 0.0), (d1, 100.0)], []) == (None, None))
check("база < 0 → (None, None)", sb.twr([(d0, -50.0), (d1, 100.0)], []) == (None, None))
check("v0 + fl/2 = 0 (вывод = сумме NAV) → (None, None)", sb.twr([(d0, 100.0), (d1, 0.0)], [(D(2026, 7, 10), -200.0)]) == (None, None))
check("одна точка → (None, None)", sb.twr([(d0, 100.0)], []) == (None, None))
r, ann = sb.twr([(d0, 100.0), (d0, 105.0)], [])
check("две точки в один день: период есть, годовой нет", near(r, 0.05, 1e-12) and ann is None)

# ------------------------------------------------------------------ 12
print("12. run — интеграция")


def snapshot0():
    return {"holdings": [H("SBER", "stock", 4000.0), H("SU26238RMFS", "bond", 3000.0, "RUB")],
            "cash": {"total_rub": 3000.0}}


def plan_pt(date, cls, stocks=None, buckets=None):
    return {"date": date, "classes": cls, "stocks": stocks, "stocks_raw_sum_pct": 100.0 if stocks else None,
            "bond_buckets": buckets}


CL_FACT = {"stock": 0.4, "bond": 0.3, "gold": 0.0, "other": 0.0, "cash": 0.3}      # = факт t0
CL_SHIFT = {"stock": 0.5, "bond": 0.2, "gold": 0.0, "other": 0.0, "cash": 0.3}     # сдвиг на 10 п.п. в акции
PRICES = {"share:SBER": [("2026-07-01", 100.0)], "index:MCFTR": [("2026-07-01", 1000.0)],
          "index:RGBITR": [("2026-07-01", 500.0)], "currency:GLDRUB_TOM": [("2026-07-01", 8000.0)],
          "rate_index:RUSFAR": [("2026-07-01", 0.0)]}


def mk_inputs(dates, navs, flows=None, divs=None, hist=None):
    return {"b3": [{"date": d, "nav_rub": n} for d, n in zip(dates, navs)],
            "external_flows": flows or [], "dividends": divs or {}, "plan_history": hist}


def run_it(inputs, series=PRICES):
    t0 = dt.date.fromisoformat(inputs["b3"][0]["date"])
    return sb.run(inputs, {t0.isoformat(): snapshot0()}, M(series, t0=t0), {})


DATES = ["2026-07-08", "2026-07-15", "2026-07-22"]
HIST = [plan_pt("2026-05-05", CL_FACT, {"SBER": 1.0}),
        plan_pt("2026-07-01", CL_SHIFT, {"SBER": 1.0}, {"ОФЗ": 1.0})]

# --- A: цены постоянны, ставка 0, потоков и дивидендов нет
res = run_it(mk_inputs(DATES, [10000.0] * 3, hist=HIST))
bs = res["bases"]
check("схема, окно, четыре базы", res["schema"] == "shadow-baselines@1" and res["window"] == {"t0": "2026-07-08", "end": "2026-07-22", "days": 14}
      and list(bs) == ["B0", "B1", "B2-live", "B2-frozen"], str(res.get("window")) + str(list(bs)))
check("A: факт B3 twr = 0", near(res["b3"]["twr"], 0.0, 1e-12) and near(res["b3"]["twr_ann"], 0.0, 1e-12))
check("A: B0 — нет комиссии, twr 0, терминал 10000, b3 − B0 = 0",
      near(bs["B0"]["twr"], 0, 1e-12) and bs["B0"]["commission_rub"] == 0 and near(bs["B0"]["terminal_rub"], 10000.0, 1e-6)
      and near(bs["B0"]["b3_minus_base_rub"], 0.0, 1e-6), str(bs["B0"]))
check("A: B1 стартует без комиссии, в том же квартале не ребалансируется",
      bs["B1"]["commission_rub"] == 0 and bs["B1"]["rebalances"] == [] and near(bs["B1"]["terminal_rub"], 10000.0, 1e-6)
      and near(bs["B1"]["twr"], 0, 1e-12), str(bs["B1"]))
# B2: на t0 акции 40% против 50% (10 п.п.) → full: цели SBER 5000 / ОФЗ 2000 / кэш 3000, оборот 2000, комиссия 1,00
for n in ("B2-live", "B2-frozen"):
    b = bs[n]
    check(f"A: {n} — один полный ребаланс на t0, оборот 2000, комиссия 1,00",
          len(b["rebalances"]) == 1 and b["rebalances"][0].startswith("2026-07-08 full:")
          and near(b["commission_rub"], 1.0, 1e-9) and near(b["turnover_rub"], 2000.0, 1e-9), str(b))
    check(f"A: {n} — терминал 9999, twr = −1/10000, b3 − база = +комиссия",
          near(b["terminal_rub"], 9999.0, 1e-6) and near(b["twr"], -1e-4, 1e-6) and near(b["b3_minus_base_rub"], 1.0, 1e-6),
          f"{b['terminal_rub']} {b['twr']} {b['b3_minus_base_rub']}")
check("A: NAV-ряд B2 на t0 фиксируется ДО ребаланса (10000), затем 9999",
      bs["B2-live"]["nav"] == [["2026-07-08", 10000.0], ["2026-07-15", 9999.0], ["2026-07-22", 9999.0]], str(bs["B2-live"]["nav"]))
check("A: b3_minus_base_pp_ann: B0 = 0, B2 > 0 (факт лучше базы на комиссию)",
      near(bs["B0"]["b3_minus_base_pp_ann"], 0.0, 1e-6) and bs["B2-live"]["b3_minus_base_pp_ann"] > 0)
check("A: допущения: frozen-акции с 2026-05-05, корзины с 2026-07-01, налог на прирост не учитывается",
      res["assumptions"]["b2_frozen_stocks"] == "2026-05-05" and res["assumptions"]["b2_frozen_buckets"] == "2026-07-01"
      and "не учитывается" in res["assumptions"]["capital_gains_tax"] and res["assumptions"]["commission"] == 0.0005)
check("A: флагов нет", res["flags"] == [], str(res["flags"]))

res1 = run_it(mk_inputs(["2026-07-08"], [10000.0], hist=HIST))
check("меньше двух точек факта → error и пустые flags", "error" in res1 and res1["flags"] == [] and "bases" not in res1)

# --- B: пополнение 1000 в середине, факт получает его же
FL = [["2026-07-15", 1000.0]]
resB = run_it(mk_inputs(DATES, [10000.0, 11000.0, 11000.0], flows=FL, hist=HIST))
bsB = resB["bases"]
for n, b in bsB.items():
    check(f"B: {n} — терминал = старт + поток − комиссия ({b['terminal_rub']})",
          near(b["terminal_rub"], 10000.0 + 1000.0 - b["commission_rub"], 1e-6), f"{b['terminal_rub']} {b['commission_rub']}")
    check(f"B: {n} — b3 − база = комиссия", near(b["b3_minus_base_rub"], b["commission_rub"], 1e-6), str(b["b3_minus_base_rub"]))
check("B: B0 — поток целиком в кэш, комиссии нет, twr 0", bsB["B0"]["commission_rub"] == 0 and near(bsB["B0"]["twr"], 0, 1e-12))
# B2: t0-ребаланс комиссия 1,00 + пополнение 1000 × 0,05% = 0,50 → 1,50; терминал 10998,50
check("B: B2-live — комиссия 1,00 (ребаланс) + 0,50 (пополнение) = 1,50, терминал 10998,50",
      near(bsB["B2-live"]["commission_rub"], 1.5, 1e-9) and near(bsB["B2-live"]["terminal_rub"], 10998.5, 1e-6),
      f"{bsB['B2-live']['commission_rub']} {bsB['B2-live']['terminal_rub']}")
# Дитц B2, интервал 1: (10998,5 − 10000 − 1000) / (10000 + 500) = −1,5/10500; интервал 2: 0
check("B: B2 twr по Дитцу = −1,5/10500", near(bsB["B2-live"]["twr"], -1.5 / 10500, 1e-5), str(bsB["B2-live"]["twr"]))
check("B: поток попал в окно факта: twr B3 = 0 и сверки с B0 нет", near(resB["b3"]["twr"], 0, 1e-12) and resB["flags"] == [], str(resB["flags"]))
# регрессия: пополнение B1 по целевым долям — сделка, комиссия как у B2 (deposit_to_deficits)
check("B: B1 — пополнение 1000 в рукава по долям плана несёт комиссию (как в B2)",
      bsB["B1"]["commission_rub"] > 0, str(bsB["B1"]["commission_rub"]))
resB0 = run_it(mk_inputs(DATES, [10000.0, 10000.0, 10000.0], flows=[["2026-07-08", 500.0], ["2026-08-01", 500.0]], hist=HIST))
check("B: потоки вне окна (d ≤ t0 или d > end) игнорируются: B0 остаётся на 10000",
      all(v == 10000.0 for _, v in resB0["bases"]["B0"]["nav"]), str(resB0["bases"]["B0"]["nav"]))

# --- C: дивиденд (SBER 10 ₽ брутто на акцию) в B0 и B2, не в B1 (индекс)
resC = run_it(mk_inputs(DATES, [10000.0, 10348.0, 10348.0], divs={"SBER": [{"date": "2026-07-15", "dps_gross": 10.0}]}, hist=HIST))
check("C: дивиденд 40 × 10 × 0,87 = 348 ₽: B0 терминал 10348", near(resC["bases"]["B0"]["terminal_rub"], 10348.0, 1e-6),
      str(resC["bases"]["B0"]["terminal_rub"]))
check("C: B1 (индекс акций) дивиденда не получает", near(resC["bases"]["B1"]["terminal_rub"], 10000.0, 1e-6))
check("C: у B2 дивиденд идёт по 50 акциям после ребаланса (50 × 10 × 0,87 = 435) — терминал 9999 + 435",
      near(resC["bases"]["B2-live"]["terminal_rub"], 9999.0 + 435.0, 1e-6), str(resC["bases"]["B2-live"]["terminal_rub"]))

# --- D: факт растёт при постоянных ценах → сверка с B0
resD1 = run_it(mk_inputs(DATES, [10000.0, 10100.0, 10100.0], hist=HIST))
check("D: +1% против B0 (< порога RECONCILE_VS_B0_PP = 2 п.п.) — флага сверки нет",
      not any("сверка" in f for f in resD1["flags"]), str(resD1["flags"]))
resD = run_it(mk_inputs(DATES, [10000.0, 10300.0, 10300.0], hist=HIST))
sv_flags = [f for f in resD["flags"] if f.startswith("сверка")]
check("D: +3% против B0 0% → ровно один флаг «сверка 2026-07-08→2026-07-15: факт +3.00% против B0 +0.00%»",
      sv_flags == ["сверка 2026-07-08→2026-07-15: факт +3.00% против B0 +0.00%"], str(sv_flags))
check("D: b3 − B0 в рублях = +300", near(resD["bases"]["B0"]["b3_minus_base_rub"], 300.0, 1e-6))

# --- E: B1 ребалансируется в первом снапшоте нового квартала, ровно один раз
HIST_E = [plan_pt("2026-07-01", CL_FACT, {"SBER": 1.0}, {"ОФЗ": 1.0})]
PR_E = {**PRICES, "index:MCFTR": [("2026-09-01", 1000.0), ("2026-10-01", 1100.0)]}
resE = run_it(mk_inputs(["2026-09-24", "2026-10-01", "2026-10-08"], [10000.0] * 3, hist=HIST_E), series=PR_E)
b1 = resE["bases"]["B1"]
# 10-01: MCFTR 4000 → 4400, nav 10400; цели 40/30/30 → 4160/3120/3120; оборот 240+120+120 = 480; комиссия 0,24
check("E: B1 — ровно один ребаланс, в 2026-10-01", b1["rebalances"] == ["2026-10-01 квартальный ребаланс"], str(b1["rebalances"]))
check("E: B1 — оборот 480, комиссия 0,24, терминал 10400 − 0,24", near(b1["turnover_rub"], 480.0, 1e-6)
      and near(b1["commission_rub"], 0.24, 1e-9) and near(b1["terminal_rub"], 10399.76, 1e-6),
      f"{b1['turnover_rub']} {b1['commission_rub']} {b1['terminal_rub']}")
check("E: B1 — NAV 09-24 = 10000, 10-01 = 10400 (оценка до ребаланса)", b1["nav"][0] == ["2026-09-24", 10000.0] and b1["nav"][1] == ["2026-10-01", 10400.0],
      str(b1["nav"]))
check("E: B0/B2 (цены SBER/ОФЗ постоянны) без комиссии и ребалансов",
      all(b["commission_rub"] == 0 and b["rebalances"] == [] for n, b in resE["bases"].items() if n != "B1"),
      str({n: (b["commission_rub"], b["rebalances"]) for n, b in resE["bases"].items()}))
resE2 = run_it(mk_inputs(["2026-09-24", "2026-09-30", "2026-10-01"], [10000.0] * 3, hist=HIST_E), series=PR_E)
check("E: окно кончается 10-01 — ребаланс B1 в 10-01 есть (первый снапшот Q4)", len(resE2["bases"]["B1"]["rebalances"]) == 1)
resE3 = run_it(mk_inputs(["2026-07-08", "2026-08-12", "2026-09-30"], [10000.0] * 3, hist=HIST_E), series=PR_E)
check("E: все даты внутри Q3 — B1 не ребалансируется", resE3["bases"]["B1"]["rebalances"] == [])

print(f"\nИтого: {PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
