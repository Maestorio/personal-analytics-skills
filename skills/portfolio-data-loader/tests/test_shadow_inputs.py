#!/usr/bin/env python3
"""Тесты входов теневых баз AIR-1 shadow_inputs.py (потоки, дивиденды, классы, B3, сверка, план).

Полностью офлайн: Trade собираются вручную (rub_amount задан явно, конвертация не вызывается),
снапшоты — dict'ы, load_snapshots читает файлы из временного каталога.
Запуск: python3 skills/portfolio-data-loader/tests/test_shadow_inputs.py
"""
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import shadow_inputs as si  # noqa: E402
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


def T(ticker, op, date, amount=0.0, cur="RUB", note="", qty=None, rub=None):
    """Минимальная сделка: rub_amount по умолчанию = amount (RUB)."""
    return Trade(ticker=ticker, name=ticker, operation=op, date=date, qty=qty, price=None,
                 nominal=None, nkd=None, commission=0.0, amount=amount, amount_no_comm=amount,
                 currency=cur, note=note, rub_amount=amount if rub is None else rub)


RUB = "Деньги (RUB)"

# ------------------------------------------------------------------ 1
print("1. is_external_flow")
d = D(2026, 8, 1)
check("Внесение с пустой заметкой → True", si.is_external_flow(T(RUB, "Внесение", d, 1000, note="")) is True)
check("Внесение «Пополнение счета» → True",
      si.is_external_flow(T(RUB, "Внесение", d, 1000, note="Пополнение счета")) is True)
check("Внесение «Перечисление денежных средств» → True",
      si.is_external_flow(T(RUB, "Внесение", d, 1000, note="Перечисление денежных средств")) is True)
check("«Зачисление денег за сделку…» → False",
      si.is_external_flow(T(RUB, "Внесение", d, 1000, note="Зачисление денег за сделку №123")) is False)
check("«Зачисление дивидендов…» → False",
      si.is_external_flow(T(RUB, "Внесение", d, 1000, note="Зачисление дивидендов по SBER")) is False)
check("налог как «Расход» → False",
      si.is_external_flow(T(RUB, "Расход", d, -130, note="Налог на доход")) is False)
check("налог как «Списание … за расходную операцию» → False",
      si.is_external_flow(T(RUB, "Списание", d, -130, note="Налог на доход за расходную операцию")) is False)
check("конверсия: Деньги USD «Покупка» → False",
      si.is_external_flow(T("Деньги (USD)", "Покупка", d, 1000, cur="USD", rub=90000)) is False)
check("конверсия: Деньги RUB «Списание» «за покупку 1000 USD» → False",
      si.is_external_flow(T(RUB, "Списание", d, -90000, note="за покупку 1000 USD")) is False)
check("конверсия: Деньги RUB «Внесение» «за продажу 1000 USD» → False",
      si.is_external_flow(T(RUB, "Внесение", d, 90000, note="за продажу 1000 USD")) is False)
check("не-денежный тикер (SBER) Внесение → False", si.is_external_flow(T("SBER", "Внесение", d, 1000)) is False)
check("«Списание» «Вывод денежных средств» → True",
      si.is_external_flow(T(RUB, "Списание", d, -5000, note="Вывод денежных средств")) is True)
check("«Списание» с пустой заметкой → True", si.is_external_flow(T(RUB, "Списание", d, -5000, note="")) is True)
check("другая операция (Дивиденд) → False",
      si.is_external_flow(T(RUB, "Дивиденд", d, 100, note="")) is False)

# ------------------------------------------------------------------ 2
print("2. external_flows")
tr = [
    T(RUB, "Внесение", D(2026, 8, 3), 1000, note=""),
    T(RUB, "Внесение", D(2026, 8, 3), 500, note="Пополнение счета"),
    T(RUB, "Списание", D(2026, 8, 5), -300, note="Вывод денежных средств"),
    T(RUB, "Внесение", D(2026, 8, 10), 0.5, note=""),                       # < 1 ₽
    T(RUB, "Внесение", D(2026, 7, 1), 7000, note=""),                       # до окна
    T(RUB, "Внесение", D(2026, 9, 1), 9000, note=""),                       # после окна
    T(RUB, "Внесение", D(2026, 8, 4), 777, note="Зачисление дивидендов"),   # не поток
]
fl = si.external_flows(tr, D(2026, 8, 1), D(2026, 8, 31))
check("два пополнения одного дня схлопнуты в одно", (D(2026, 8, 3), 1500.0) in fl, str(fl))
check("вывод — отрицательный", (D(2026, 8, 5), -300.0) in fl, str(fl))
check("|сумма| < 1 отброшена", all(x[0] != D(2026, 8, 10) for x in fl), str(fl))
check("окно дат: до и после — вне", len(fl) == 2, str(fl))
check("результат отсортирован по дате", [x[0] for x in fl] == sorted(x[0] for x in fl))
fl_edge = si.external_flows(tr, D(2026, 7, 1), D(2026, 7, 1))
check("границы окна включительно", fl_edge == [(D(2026, 7, 1), 7000.0)], str(fl_edge))
fl_zero = si.external_flows([T(RUB, "Внесение", d, 1000, note=""), T(RUB, "Списание", d, -1000, note="")], d, d)
check("пополнение и вывод одного дня взаимно гасятся (|0| < 1 → нет записи)", fl_zero == [], str(fl_zero))

# ------------------------------------------------------------------ 3
print("3. dividends_per_share")
since = D(2026, 5, 1)
GROSS = "Выплата дивидендов по акциям SBER"
NET = "Дивиденды по SBER"
tr = [
    T("SBER", "Дивиденд", D(2026, 7, 18), amount=37.64 * 740, qty=740, note=GROSS),
    T("SBER", "Дивиденд", D(2026, 7, 20), amount=32.7875 * 610, qty=610, note=NET),
]
res, flags = si.dividends_per_share(tr, since)
check("кластер брутто+нетто → одна выплата", len(res.get("SBER", [])) == 1, str(res))
check("dps_gross = ровно брутто 37,64 (нетто/0,87 не подмешивается)",
      near(res["SBER"][0]["dps_gross"], 37.64, 1e-6), str(res))
check("rows = 2", res["SBER"][0]["rows"] == 2)
check("дата выплаты — первая строка кластера", res["SBER"][0]["date"] == "2026-07-18")
check("флагов нет при наличии брутто", flags == [], str(flags))

# порядок строк не важен: нетто раньше брутто
res_r, _ = si.dividends_per_share(list(reversed(tr)), since)
check("порядок строк на вход не влияет", res_r == res, str(res_r))

# нетто, которое по делению превышает брутто, всё равно не побеждает
tr_hi = [
    T("PLZL", "Дивиденд", D(2026, 7, 15), amount=28.76 * 100, qty=100, note="Выплата дивидендов по акциям PLZL"),
    T("PLZL", "Дивиденд", D(2026, 7, 15), amount=25.28 * 100, qty=100, note="Дивиденды по PLZL"),
]
res_hi, _ = si.dividends_per_share(tr_hi, since)
check("нетто/0,87 (29,06) > брутто (28,76) — берётся брутто 28,76", near(res_hi["PLZL"][0]["dps_gross"], 28.76), str(res_hi))

# только нетто
tr_n = [T("LKOH", "Дивиденд", D(2026, 7, 10), amount=87.0 * 10, qty=10, note="Дивиденды по LKOH")]
res_n, fl_n = si.dividends_per_share(tr_n, since)
check("только нетто → брутто = нетто/0,87", near(res_n["LKOH"][0]["dps_gross"], 100.0, 1e-4), str(res_n))
check("только нетто → есть флаг", len(fl_n) == 1 and "LKOH" in fl_n[0] and "нетто" in fl_n[0], str(fl_n))

# две выплаты с разрывом > 5 дней
tr_2 = [
    T("MTSS", "Дивиденд", D(2026, 7, 1), amount=100, qty=10, note=GROSS),
    T("MTSS", "Дивиденд", D(2026, 7, 7), amount=200, qty=10, note=GROSS),       # +6 дней → новая выплата
]
res_2, _ = si.dividends_per_share(tr_2, since)
check("разрыв 6 дней → две записи", len(res_2["MTSS"]) == 2, str(res_2))
check("значения не смешаны", [r["dps_gross"] for r in res_2["MTSS"]] == [10.0, 20.0], str(res_2))
tr_5 = [
    T("MTSS", "Дивиденд", D(2026, 7, 1), amount=100, qty=10, note=GROSS),
    T("MTSS", "Дивиденд", D(2026, 7, 6), amount=100, qty=10, note=GROSS),       # ровно 5 дней → склейка
]
res_5, _ = si.dividends_per_share(tr_5, since)
check("разрыв ровно 5 дней → одна запись", len(res_5["MTSS"]) == 1 and res_5["MTSS"][0]["rows"] == 2, str(res_5))

# пропуски
tr_skip = [
    T("A1", "Дивиденд", D(2026, 7, 1), amount=100, qty=0, note=GROSS),
    T("A2", "Дивиденд", D(2026, 7, 1), amount=100, qty=None, note=GROSS),
    T("A3", "Дивиденд", D(2026, 7, 1), amount=100, qty=10, cur="USD", note=GROSS),
    T("A4", "Дивиденд", D(2026, 4, 30), amount=100, qty=10, note=GROSS),         # раньше since
    T("A5", "Дивиденд", D(2026, 5, 1), amount=100, qty=10, note=GROSS),          # ровно since → берётся
    T("A6", "Внесение", D(2026, 7, 1), amount=100, qty=10, note=GROSS),          # не дивиденд
    T("A7", "Дивиденд", D(2026, 7, 1), amount=100, qty=-5, note=GROSS),
]
res_s, _ = si.dividends_per_share(tr_skip, since)
check("qty=0/None/<0 пропущены", not ({"A1", "A2", "A7"} & set(res_s)), str(res_s))
check("валюта ≠ RUB пропущена", "A3" not in res_s)
check("дата раньше since пропущена", "A4" not in res_s)
check("дата == since берётся", "A5" in res_s)
check("не-дивидендная операция пропущена", "A6" not in res_s)

# ------------------------------------------------------------------ 4
print("4. holding_class + fund_sectors")
check("акция → stock", si.holding_class({"asset_type": "stock", "ticker": "SBER"}) == "stock")
check("облигация → bond", si.holding_class({"asset_type": "bond", "ticker": "SU26238"}) == "bond")
check("фонд money_market → cash",
      si.holding_class({"asset_type": "fund", "ticker": "TMON", "sector": "money_market"}) == "cash")
check("TGLD → gold даже без сектора", si.holding_class({"asset_type": "fund", "ticker": "TGLD", "sector": None}) == "gold")
check("TGLD с сектором money_market всё равно gold",
      si.holding_class({"asset_type": "fund", "ticker": "TGLD", "sector": "money_market"}) == "gold")
check("фонд bonds_rub → bond",
      si.holding_class({"asset_type": "fund", "ticker": "TBRU", "sector": "bonds_rub"}) == "bond")
check("прочий фонд → other",
      si.holding_class({"asset_type": "fund", "ticker": "TMOS", "sector": "equity_ru"}) == "other")
check("фонд без сектора и без справочника → other",
      si.holding_class({"asset_type": "fund", "ticker": "XXXX", "sector": None}) == "other")

snaps = [
    (D(2026, 7, 10), {"holdings": [{"asset_type": "fund", "ticker": "TMON", "sector": None},
                                    {"asset_type": "fund", "ticker": "TPAY", "sector": None}]}),
    (D(2026, 9, 10), {"holdings": [{"asset_type": "fund", "ticker": "TMON", "sector": "money_market"},
                                    {"asset_type": "fund", "ticker": "TPAY", "sector": "bonds_rub"},
                                    {"asset_type": "stock", "ticker": "SBER", "sector": "banks"}]}),
]
sec = si.fund_sectors(snaps)
check("fund_sectors берёт сектор из позднего снапшота", sec == {"TMON": "money_market", "TPAY": "bonds_rub"}, str(sec))
check("акции в fund_sectors не попадают", "SBER" not in sec)
h_old = {"asset_type": "fund", "ticker": "TMON", "sector": None}
check("июльский фонд без сектора + справочник → cash", si.holding_class(h_old, sec) == "cash")
check("июльский фонд без сектора без справочника → other", si.holding_class(h_old) == "other")
check("fund_sectors: более поздний сектор перекрывает ранний",
      si.fund_sectors([(D(2026, 8, 1), {"holdings": [{"asset_type": "fund", "ticker": "F", "sector": "a"}]}),
                       (D(2026, 9, 1), {"holdings": [{"asset_type": "fund", "ticker": "F", "sector": "b"}]})]) == {"F": "b"})
check("fund_sectors без holdings не падает", si.fund_sectors([(D(2026, 8, 1), {})]) == {})

# ------------------------------------------------------------------ 5
print("5. b3_point / b3_series")
snap = {
    # итог снапшота включает заблокированные (как в живых снапшотах до 2026-08-15: +239 тыс. ₽)
    "status_summary": {"total_value_rub": 1000.0 + 9999.0},
    "cash": {"total_rub": 200.0},
    "holdings": [
        {"asset_type": "stock", "ticker": "SBER", "value_rub": 600.0},
        {"asset_type": "bond", "ticker": "SU1", "value_rub": 300.0},
        {"asset_type": "stock", "ticker": "ZZZ", "value_rub": 9999.0, "status": "blocked"},
        {"asset_type": "stock", "ticker": "YYY", "value_rub": 8888.0, "is_blocked": True},
        {"asset_type": "fund", "ticker": "TGLD", "value_rub": 100.0},
        {"asset_type": "stock", "ticker": "NONE", "value_rub": None},
    ],
}
p = si.b3_point(D(2026, 8, 1), snap)
check("nav = Σ незаблокированных + кэш, НЕ status_summary (регрессия 08-15→08-19)", near(p["nav_rub"], 1200.0), str(p))
check("nav = Σ by_class", near(p["nav_rub"], sum(p["by_class_rub"].values())), str(p))
check("дата ISO", p["date"] == "2026-08-01")
bc = p["by_class_rub"]
check("blocked (status) не входит в by_class", near(bc["stock"], 600.0), str(bc))
check("blocked (is_blocked) не входит в by_class", bc["stock"] < 1000, str(bc))
check("облигации и золото по классам", near(bc["bond"], 300.0) and near(bc["gold"], 100.0), str(bc))
check("кэш добавлен в by_class['cash']", near(bc["cash"], 200.0), str(bc))
check("все классы присутствуют", set(bc) == {"stock", "bond", "gold", "other", "cash"}, str(bc))
check("value_rub=None не ломает", True)
check("снапшот без status_summary → None", si.b3_point(D(2026, 8, 1), {"cash": {"total_rub": 1}}) is None)
check("снапшот без cash → None", si.b3_point(D(2026, 8, 1), {"status_summary": {"total_value_rub": 1}}) is None)
check("status_summary есть, но total_value_rub отсутствует → None",
      si.b3_point(D(2026, 8, 1), {"status_summary": {}, "cash": {"total_rub": 1}}) is None)

good = {"status_summary": {"total_value_rub": 10.0}, "cash": {"total_rub": 5.0}, "holdings": []}
ser = si.b3_series([(D(2026, 7, 7), good), (D(2026, 7, 8), good), (D(2026, 7, 9), {"cash": {"total_rub": 1}}),
                    (D(2026, 7, 10), good)])
check("точки раньше B3_START отброшены, без status_summary пропущены",
      [x["date"] for x in ser] == ["2026-07-08", "2026-07-10"], str([x["date"] for x in ser]))
ser2 = si.b3_series([(D(2026, 7, 8), good), (D(2026, 7, 10), good)], start=D(2026, 7, 9))
check("явный start отсекает ранние", [x["date"] for x in ser2] == ["2026-07-10"])
snaps_f = [
    (D(2026, 7, 8), {"holdings": [{"asset_type": "fund", "ticker": "TMON", "sector": None, "value_rub": 50.0}],
                     "status_summary": {"total_value_rub": 50.0}, "cash": {"total_rub": 0.0}}),
    (D(2026, 9, 1), {"holdings": [{"asset_type": "fund", "ticker": "TMON", "sector": "money_market"}]}),
]
ser3 = si.b3_series(snaps_f)
check("b3_series подставляет сектор из позднего снапшота (TMON → cash)",
      near(ser3[0]["by_class_rub"]["cash"], 50.0) and near(ser3[0]["by_class_rub"]["other"], 0.0), str(ser3))

# ------------------------------------------------------------------ 6
print("6. reconcile")
pa = {"date": "2026-07-10", "nav_rub": 1000.0}
pb = {"date": "2026-07-16", "nav_rub": 1210.0}
pc = {"date": "2026-07-20", "nav_rub": 1100.0}
# интервал 1: поток +200 в середине: (1210−1000−200)/(1000+100) = 10/1100
rec = si.reconcile([pa, pb], [(D(2026, 7, 13), 200.0)])
check("Дитц: (1210−1000−200)/1100 = 0,00909", near(rec[0]["ret"], 0.00909, 1e-9), str(rec))
check("flows_rub = 200", near(rec[0]["flows_rub"], 200.0))
check("|r| < 0,05 → флага нет", rec[0]["flag"] is False)
check("from/to", rec[0]["from"] == "2026-07-10" and rec[0]["to"] == "2026-07-16")
# два интервала; −100 в интервале 2: (1100−1210+100)/(1210−50) = −10/1160
rec2 = si.reconcile([pa, pb, pc], [(D(2026, 7, 13), 200.0), (D(2026, 7, 18), -100.0)])
check("интервал 2: −10/1160 = −0,00862", near(rec2[1]["ret"], -0.00862, 1e-9), str(rec2))
check("интервал 1 не захватил поток интервала 2", near(rec2[0]["flows_rub"], 200.0), str(rec2))
check("число интервалов = точек − 1", len(rec2) == 2)
# граничные потоки: d0 < d <= d1
rec_b = si.reconcile([pa, pb, pc], [(D(2026, 7, 10), 500.0), (D(2026, 7, 16), 300.0)])
check("поток в день начала интервала 1 не входит; в день конца входит",
      near(rec_b[0]["flows_rub"], 300.0), str(rec_b))
check("поток в день 07-16 принадлежит интервалу 1, а не 2 (там он — день начала)",
      near(rec_b[1]["flows_rub"], 0.0), str(rec_b))
# флаг
rec_f = si.reconcile([pa, {"date": "2026-07-16", "nav_rub": 1100.0}], [])
check("|r|=0,1 > 0,05 → флаг", rec_f[0]["flag"] is True and near(rec_f[0]["ret"], 0.1), str(rec_f))
rec_f2 = si.reconcile([pa, {"date": "2026-07-16", "nav_rub": 900.0}], [])
check("отрицательная |r|=0,1 тоже флаг", rec_f2[0]["flag"] is True and near(rec_f2[0]["ret"], -0.1), str(rec_f2))
rec_f3 = si.reconcile([pa, {"date": "2026-07-16", "nav_rub": 1050.0}], [])
check("r = 0,05 ровно — не флаг (строгое >)", rec_f3[0]["flag"] is False, str(rec_f3))
rec_z = si.reconcile([{"date": "2026-07-10", "nav_rub": 0.0}, pb], [])
check("база ≤ 0 → ret None и флаг", rec_z[0]["ret"] is None and rec_z[0]["flag"] is True, str(rec_z))
check("одна точка → пустой список", si.reconcile([pa], []) == [])

# ------------------------------------------------------------------ 7
print("7. plan_point")
goals = [{"Тип": "Акции", "Доля": 0.5}, {"Тип": "Облигация", "Доля": 0.3}, {"Тип": "Золото", "Доля": 0.1},
         {"Тип": "Другое", "Доля": 0.05}, {"Тип": "Кеш", "Доля": 0.05}, {"Тип": "Итого", "Доля": 1.0}]
pl = si.plan_point(D(2026, 8, 1), {"balance_summary": {"goals_overall": goals}})
exp = {"stock": 0.5, "bond": 0.3, "gold": 0.1, "other": 0.05, "cash": 0.05}
check("goals_overall — список", pl["classes"] == exp, str(pl["classes"]))
pl2 = si.plan_point(D(2026, 5, 5), {"balance_summary": {"goals_overall": {"overall": goals}}})
check("goals_overall — {'overall': [...]}", pl2["classes"] == exp, str(pl2["classes"]))
check("неизвестный Тип («Итого») игнорируется", "Итого" not in pl["classes"])
check("goals_overall отсутствует → classes None", si.plan_point(D(2026, 8, 1), {})["classes"] is None)
check("пустая balance_summary → bond_buckets None", si.plan_point(D(2026, 8, 1), {})["bond_buckets"] is None)

snap_st = {"ie_actual": {"per_ticker": {
    "SBER": {"planned_share_pct": 29.1},
    "LKOH": {"planned_share_pct": 67.9},
    "ZERO": {"planned_share_pct": 0},
    "NONE": {"planned_share_pct": None},
    "NOKEY": {"actual": 5},
    "BAD": "не dict",
}}}
ps = si.plan_point(D(2026, 8, 1), snap_st)
check("нормировка при сумме 97: SBER = 29,1/97 = 0,3", near(ps["stocks"]["SBER"], 0.3, 1e-6), str(ps["stocks"]))
check("нормировка при сумме 97: LKOH = 67,9/97 = 0,7", near(ps["stocks"]["LKOH"], 0.7, 1e-6), str(ps["stocks"]))
check("сумма долей = 1", near(sum(ps["stocks"].values()), 1.0, 1e-5))
check("планы None/0/без ключа/не-dict игнорируются", set(ps["stocks"]) == {"SBER", "LKOH"}, str(ps["stocks"]))
check("stocks_raw_sum_pct = 97", near(ps["stocks_raw_sum_pct"], 97.0, 1e-3), str(ps["stocks_raw_sum_pct"]))
pe = si.plan_point(D(2026, 8, 1), {"ie_actual": {"per_ticker": {"A": {"planned_share_pct": 0}}}})
check("все планы нулевые → stocks None", pe["stocks"] is None and pe["stocks_raw_sum_pct"] == 0)
check("нет ie_actual → stocks None", si.plan_point(D(2026, 8, 1), {})["stocks"] is None)

br_old = [{"Тип": "ОФЗ", "Доля План": 0.4}, {"Тип": "КОРП", "Доля План": 0.2},
          {"Тип": "КОРП", "Доля План": 0.1}, {"Тип": "Итог", "Доля План": 1.0},
          {"Тип": "ВАЛ", "Доля План": None}]
pb_old = si.plan_point(D(2026, 8, 1), {"balance_summary": {"goals_bonds_breakdown": br_old}})["bond_buckets"]
check("строка «Итог» отброшена", "Итог" not in pb_old, str(pb_old))
check("две строки «КОРП» без _bucket_key не затирают друг друга",
      near(pb_old.get("КОРП"), 0.2) and any(k.startswith("КОРП#") and near(v, 0.1) for k, v in pb_old.items()),
      str(pb_old))
check("Доля План=None пропущена", "ВАЛ" not in pb_old)
check("сумма корзин сохранена (0,4+0,2+0,1)", near(sum(pb_old.values()), 0.7), str(pb_old))
br_new = [{"Тип": "КОРП", "_bucket_key": "КОРП_ИГ", "Доля План": 0.2},
          {"Тип": "КОРП", "_bucket_key": "КОРП_ВДО", "Доля План": 0.1},
          {"Тип": "ОФЗ", "_bucket_key": "ОФЗ", "Доля План": 0.4},
          {"Тип": "Итог", "Доля План": 1.0}]
pb_new = si.plan_point(D(2026, 9, 1), {"balance_summary": {"goals_bonds_breakdown": br_new}})["bond_buckets"]
check("новый формат с _bucket_key", pb_new == {"КОРП_ИГ": 0.2, "КОРП_ВДО": 0.1, "ОФЗ": 0.4}, str(pb_new))
check("дата точки плана ISO", si.plan_point(D(2026, 9, 1), {})["date"] == "2026-09-01")

# ------------------------------------------------------------------ 8
print("8. plan_history")


def snap_with_plan(stock_share):
    return {"balance_summary": {"goals_overall": [{"Тип": "Акции", "Доля": stock_share}, {"Тип": "Облигация", "Доля": 1 - stock_share}]},
            "ie_actual": {"per_ticker": {"SBER": {"planned_share_pct": 100.0}}}}


hist = si.plan_history([(D(2026, 8, 1), snap_with_plan(0.5)), (D(2026, 8, 8), snap_with_plan(0.6)),
                        (D(2026, 8, 15), snap_with_plan(0.6))])
check("3 снапшота, план меняется во 2-м → 2 точки", len(hist) == 2, str([h["date"] for h in hist]))
check("точки: первая и момент изменения", [h["date"] for h in hist] == ["2026-08-01", "2026-08-08"])
check("значение плана во второй точке", near(hist[1]["classes"]["stock"], 0.6))
hist_back = si.plan_history([(D(2026, 8, 1), snap_with_plan(0.5)), (D(2026, 8, 8), snap_with_plan(0.6)),
                             (D(2026, 8, 15), snap_with_plan(0.5))])
check("возврат к прежнему плану — это новая точка", len(hist_back) == 3)
check("пустой вход → пустая история", si.plan_history([]) == [])
check("один снапшот → одна точка", len(si.plan_history([(D(2026, 8, 1), snap_with_plan(0.5))])) == 1)

# ------------------------------------------------------------------ 9
print("9. build_inputs + load_snapshots")


def full_snap(total, cash):
    s = snap_with_plan(0.5)
    s.update({"status_summary": {"total_value_rub": total}, "cash": {"total_rub": cash}, "holdings": []})
    return s


snaps_b = [(D(2026, 8, 1), full_snap(1000, 0)), (D(2026, 8, 20), full_snap(1010, 0))]
tr_old = [T(RUB, "Внесение", D(2026, 8, 10), 100, note="")]                      # на 10 дней старше снапшота
res = si.build_inputs(tr_old, snaps_b, D(2026, 5, 1), D(2026, 8, 25))
check("схема shadow-inputs@1", res["schema"] == "shadow-inputs@1")
check("флаг «выгрузка сделок кончается …»",
      any("выгрузка сделок кончается 2026-08-10" in f for f in res["flags"]), str(res["flags"]))
check("trades_last_date", res["trades_last_date"] == "2026-08-10")
check("окно в результате", res["window"] == {"since": "2026-05-01", "as_of": "2026-08-25", "b3_start": "2026-07-08"}, str(res["window"]))
check("b3 содержит 2 точки", len(res["b3"]) == 2)
check("external_flows сериализованы в [iso, руб]", res["external_flows"] == [["2026-08-10", 100.0]], str(res["external_flows"]))
check("ключи результата",
      {"b3", "reconcile", "external_flows", "dividends", "plan_history", "flags", "trades_last_date"} <= set(res))
check("результат сериализуется в JSON", bool(json.dumps(res, ensure_ascii=False)))

tr_3 = [T(RUB, "Внесение", D(2026, 8, 17), 100, note="")]                         # ровно −3 дня
res3 = si.build_inputs(tr_3, snaps_b, D(2026, 5, 1), D(2026, 8, 25))
check("сделка за 3 дня до снапшота — флага нет", not any("выгрузка" in f for f in res3["flags"]), str(res3["flags"]))
tr_4 = [T(RUB, "Внесение", D(2026, 8, 16), 100, note="")]                         # −4 дня
res4 = si.build_inputs(tr_4, snaps_b, D(2026, 5, 1), D(2026, 8, 25))
check("сделка за 4 дня до снапшота — флаг есть", any("выгрузка" in f for f in res4["flags"]), str(res4["flags"]))
res_ne = si.build_inputs([], snaps_b, D(2026, 5, 1), D(2026, 8, 25))
check("нет сделок → trades_last_date None, флага выгрузки нет",
      res_ne["trades_last_date"] is None and all("выгрузка" not in f for f in res_ne["flags"]), str(res_ne["flags"]))
res_since = si.build_inputs(tr_3, snaps_b, D(2026, 8, 10), D(2026, 8, 25))
check("since позже B3_START отсекает ранние снапшоты", [p["date"] for p in res_since["b3"]] == ["2026-08-20"])
# флаг сверки попадает в flags
snaps_j = [(D(2026, 8, 1), full_snap(1000, 0)), (D(2026, 8, 5), full_snap(1500, 0))]
res_j = si.build_inputs([T(RUB, "Внесение", D(2026, 8, 4), 1, note="")], snaps_j, D(2026, 5, 1), D(2026, 8, 25))
check("скачок NAV без потока → флаг «сверка B3»", any("сверка B3" in f for f in res_j["flags"]), str(res_j["flags"]))
check("дивиденды в результате",
      "SBER" in si.build_inputs([T("SBER", "Дивиденд", D(2026, 8, 3), amount=10, qty=1, note="Выплата дивидендов")],
                                snaps_b, D(2026, 5, 1), D(2026, 8, 25))["dividends"])

with tempfile.TemporaryDirectory(prefix="shadow_test_") as td:
    p = Path(td)
    (p / "portfolio-2026-07-10.json").write_text(json.dumps({"n": 2}), encoding="utf-8")
    (p / "portfolio-2026-07-08.json").write_text(json.dumps({"n": 1}), encoding="utf-8")
    (p / "portfolio-latest.json").write_text("{}", encoding="utf-8")
    (p / "portfolio-2026-07-09.bak.json").write_text("{}", encoding="utf-8")
    (p / "portfolio-2026-07-12.md").write_text("x", encoding="utf-8")
    loaded = si.load_snapshots(p)
    check("load_snapshots: только portfolio-YYYY-MM-DD.json, по возрастанию даты",
          [d.isoformat() for d, _ in loaded] == ["2026-07-08", "2026-07-10"], str([d for d, _ in loaded]))
    check("load_snapshots: содержимое прочитано", [s["n"] for _, s in loaded] == [1, 2])
with tempfile.TemporaryDirectory(prefix="shadow_test_") as td:
    check("load_snapshots: пустой каталог → []", si.load_snapshots(Path(td)) == [])

print(f"\nИтого: {PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
