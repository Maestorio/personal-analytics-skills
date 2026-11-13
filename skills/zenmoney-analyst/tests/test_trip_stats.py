#!/usr/bin/env python3
"""
Регрессионные тесты статистики поездки ZenMoney: trip_stats.py (типы трат, даты
поездки из карты или по данным, фазы «до / во время / после», предоплаты по сроку,
возвраты и компенсации, траты без тега в кошельке) и запись trips.json.

Синтетические данные. Запуск из корня репозитория:
    python3 skills/zenmoney-analyst/tests/test_trip_stats.py
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
import trip_stats as ts  # noqa: E402

PASSED = FAILED = 0


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {detail}")


TRIP = "trip"
ACC = {
    "card": {"name": "Карта", "instrument": "RUB", "type": "card", "isInBalance": True},
    "wallet": {"name": "Кошелёк", "instrument": "USD", "type": "cash", "isInBalance": False},
}
CATS = {
    "transport": {"name": "Транспорт", "parentId": None, "isExpense": True, "isIncome": False},
    "flights": {"name": "Перелёты/переплывы", "parentId": "transport", "isExpense": True, "isIncome": False},
    "taxi": {"name": "Такси", "parentId": "transport", "isExpense": True, "isIncome": False},
    "housing": {"name": "Жилище", "parentId": None, "isExpense": True, "isIncome": False},
    "hotel": {"name": "Гостиница", "parentId": "housing", "isExpense": True, "isIncome": False},
    "food": {"name": "Питание", "parentId": None, "isExpense": True, "isIncome": False},
    "cafe": {"name": "Кафе и рестораны", "parentId": "food", "isExpense": True, "isIncome": False},
    "leisure": {"name": "Досуг", "parentId": None, "isExpense": True, "isIncome": False},
    "tours": {"name": "Экскурсии", "parentId": "leisure", "isExpense": True, "isIncome": False},
    "gifts": {"name": "Подарки и другие покупки", "parentId": "leisure", "isExpense": True, "isIncome": False},
    "other": {"name": "Другое", "parentId": None, "isExpense": True, "isIncome": True},
    "corr": {"name": "Корректировка", "parentId": None, "isExpense": True, "isIncome": True},
    "refund": {"name": "Возврат", "parentId": None, "isExpense": False, "isIncome": True},
    "partner": {"name": "Общак", "parentId": None, "isExpense": False, "isIncome": True},
    "travel": {"name": "Путешествия", "parentId": None, "isExpense": True, "isIncome": False},
    TRIP: {"name": "#Страна'26", "parentId": "travel", "isExpense": True, "isIncome": False},
}
MERCH = {"m-air": {"name": "Аэрофлот"}, "m-bank": {"name": "Т-Банк"}}


def op(i, dt, side, acc, amt, cat=None, tag=True, **kw):
    o = {"id": i, "date": dt, side: {"accountId": acc, "amount": amt}}
    if cat:
        o["categoryId"] = cat
    if tag:
        o["tagIds"] = [TRIP]
    o.update(kw)
    return o


OPS = [
    op("t1", "2026-02-20", "expense", "card", 60000, "flights", merchantId="m-air"),      # за ~200 дней
    op("t2", "2026-07-30", "expense", "card", 20000, "hotel"),                           # за ~37 дней
    op("t3", "2026-08-25", "expense", "card", 5000, "other", merchantId="m-bank", originalPayee="T-BankAir"),  # билет по payee
    op("d1", "2026-09-05", "expense", "card", 1000, "cafe"),
    op("d2", "2026-09-06", "expense", "wallet", 10, "taxi"),                             # USD
    op("d3", "2026-09-07", "expense", "card", 3000, "tours"),
    op("d4", "2026-09-09", "expense", "card", 2000, "gifts"),
    op("d5", "2026-09-10", "expense", "card", 4000, "corr"),                             # незаписанные
    op("d6", "2026-09-11", "expense", "card", 500, TRIP, tag=False),                     # поездка основной категорией
    op("d7", "2026-09-12", "income", "card", 300, "taxi"),                               # возврат за такси
    op("d8", "2026-09-12", "income", "card", 1500, "refund"),                            # компенсация
    op("d9", "2026-09-12", "income", "card", 7000, "partner"),                           # доля партнёра
    op("a1", "2026-09-20", "expense", "card", 400, "cafe"),                              # после поездки
    op("x1", "2026-09-08", "expense", "wallet", 5, "cafe", tag=False),                   # в кошельке без тега
    op("x2", "2026-09-08", "expense", "card", 999, "cafe", tag=False),                   # не кошелёк, не поездка
]
RATES = {"data": [{"instrument": "USD", "date": "2026-09-06", "rate": 90.0},
                  {"instrument": "USD", "date": "2026-09-08", "rate": 90.0}]}


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
        page = jdump(t / "p.json", {"data": OPS, "nextCursor": None, "references": {
            "user": {"currency": "RUB", "monthStartDay": 1}, "accounts": ACC, "categories": CATS, "merchants": MERCH}})
        rates = jdump(t / "r.json", RATES)
        base = ["report", "--trip", TRIP, "--tx", page, "--rates", rates]

        print("Даты и фазы")
        rc, r = cli(ts, base)
        # серия — по дням РАСХОДОВ на месте: 12.09 только доходы, поездка по данным кончается 11.09
        check("даты по данным: серия трат на месте", r["period"] == {"start": "2026-09-05", "end": "2026-09-11",
                                                                     "basis": "по данным", "days": 7}, r["period"])
        check("первая покупка", r["first_purchase"] == "2026-02-20")
        ph = r["by_phase"]
        check("до поездки: билеты и жильё", ph["before"] == 85000.0, ph)
        check("после поездки: кафе 20.09 − возврат 12.09", ph["after"] == 100.0, ph)
        # во время: 1000 + 900 + 3000 + 2000 + 4000 + 500 = 11400
        check("во время поездки", ph["during"] == 11400.0, ph)
        lead = {x["bucket"]: x for x in r["prepaid_by_lead"]}
        check("предоплата > 6 мес", lead["больше 6 месяцев"]["rub"] == 60000.0, lead)
        check("предоплата 1–3 мес и до месяца", lead["1–3 месяца"]["rub"] == 20000.0 and lead["до месяца"]["rub"] == 5000.0, lead)
        cfg = jdump(t / "c.json", {"trip_dates": {TRIP: ["2026-09-04", "2026-09-21"]}})
        rc, rc_ = cli(ts, base + ["--config", cfg])
        check("даты из карты важнее данных", rc_["period"]["basis"] == "карта" and rc_["by_phase"]["after"] == 0.0, rc_["period"])
        check("в день на месте", rc_["totals"]["per_day_during_rub"] == round(11500 / 18, 2), rc_["totals"])

        print("Типы")
        ty = {x["type"]: x for x in r["by_type"]}
        check("билеты: категория + payee T-BankAir", ty["Билеты"]["rub"] == 65000.0 and ty["Билеты"]["count"] == 2, ty.get("Билеты"))
        check("жильё", ty["Жильё"]["rub"] == 20000.0)
        check("еда (в т. ч. после поездки)", ty["Еда"]["rub"] == 1400.0)
        check("транспорт на месте: USD по курсу − возврат", ty["Транспорт на месте"]["rub"] == 600.0, ty["Транспорт на месте"])
        check("экскурсии", ty["Экскурсии и развлечения"]["rub"] == 3000.0)
        check("подарки", ty["Покупки и подарки"]["rub"] == 2000.0)
        check("незаписанные — своим типом", ty["Незаписанные траты"]["rub"] == 4000.0 and r["totals"]["unrecorded_rub"] == 4000.0)
        check("поездка основной категорией — «Без статьи»", ty["Без статьи"]["rub"] == 500.0)
        check("порядок типов по шаблону", [x["type"] for x in r["by_type"]][:2] == ["Билеты", "Жильё"])
        cfg2 = jdump(t / "c2.json", {"trip_types": {"gifts": "Экскурсии и развлечения"}})
        rc, r2 = cli(ts, base + ["--config", cfg2])
        check("тип из карты переопределяет", "Покупки и подарки" not in {x["type"] for x in r2["by_type"]})

        print("Итоги")
        T = r["totals"]
        check("потрачено = траты − возвраты", T["spent_rub"] == 96500.0 and T["refunds_rub"] == 300.0, T)
        check("компенсации уменьшают «чистую» стоимость", T["compensations_rub"] == 1500.0 and T["net_rub"] == 95000.0, T)
        check("доля партнёра отдельно, не вычитается", T["partner_rub"] == 7000.0)
        check("доли типов ≈ 1", abs(sum(x["share"] for x in r["by_type"]) - 1) < 1e-3)
        check("валюты", {c["instrument"]: c["amount"] for c in r["currencies"]} == {"RUB": 95600.0, "USD": 10.0}, r["currencies"])
        check("фазы по типам: билеты до поездки", r["type_by_phase"][0] == {"type": "Билеты", "before": 65000.0, "during": 0.0, "after": 0.0})

        print("Траты без тега в кошельке")
        rc, rw = cli(ts, base + ["--wallet-tx", page, "--wallet", "wallet"])
        check("найдена трата кошелька без тега", [x["id"] for x in rw["untagged_in_wallet"]] == ["x1"], rw["untagged_in_wallet"])
        rc, rn = cli(ts, base + ["--wallet-tx", page])
        check("без --wallet берутся все операции файла", {x["id"] for x in rn["untagged_in_wallet"]} == {"x1", "x2"})
        check("без --wallet-tx список пуст", r["untagged_in_wallet"] == [])

        print("needs-rates")
        many = [op(f"u{i}", f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", "expense", "wallet", 1, "cafe") for i in range(40)]
        pm = jdump(t / "pm.json", {"data": many, "nextCursor": None, "references": {
            "user": {"currency": "RUB"}, "accounts": ACC, "categories": CATS}})
        rc, nr = cli(ts, ["needs-rates", "--trip", TRIP, "--tx", pm])
        check("даты режутся пачками по 31", [len(x) for x in nr["USD"]] == [31, 9], [len(x) for x in nr["USD"]])
        print("Вьетнам'26 (2026-10-05): игрушка и неполный список категорий")
        cats_toy = dict(CATS, toy={"name": "Игрушки", "parentId": "leisure", "isExpense": True, "isIncome": False})
        ptoy = jdump(t / "ptoy.json", {"data": OPS + [op("d10", "2026-09-07", "expense", "card", 1600, "toy")],
                                       "nextCursor": None, "references": {"user": {"currency": "RUB", "monthStartDay": 1},
                                                                          "accounts": ACC, "categories": cats_toy, "merchants": MERCH}})
        rc, rt = cli(ts, ["report", "--trip", TRIP, "--tx", ptoy, "--rates", rates])
        bt = {x["type"]: x["rub"] for x in rt["by_type"]}
        check("игрушка — «Покупки и подарки», не развлечения", bt["Покупки и подарки"] == 3600.0, bt)
        part = jdump(t / "cats-part.json", {"data": [dict(CATS[TRIP], id=TRIP), dict(CATS["travel"], id="travel")],
                                            "nextCursor": None})
        rc, rp = cli(ts, base + ["--categories", part])
        check("неполный список категорий не превращает возврат за такси в компенсацию",
              rp["totals"]["refunds_rub"] == r["totals"]["refunds_rub"]
              and rp["totals"]["compensations_rub"] == r["totals"]["compensations_rub"], rp["totals"])
        rc, bad = cli(ts, ["report", "--trip", "nope", "--tx", page])
        check("неизвестная поездка — blocking", rc == 2 and "не найдена" in bad["blocking"])

        print("Запись trips.json")
        tp = t / "audit" / "trips.json"
        rc, s = cli(ah, ["trip", "--run", jdump(t / "run.json", rw), "--trips", str(tp), "--date", "2026-10-05"])
        check("dry-run", rc == 0 and not tp.exists())
        rc, s = cli(ah, ["trip", "--run", str(t / "run.json"), "--trips", str(tp), "--date", "2026-10-05", "--write"])
        check("записано", s["record"] == "добавлена" and tp.exists(), s)
        rc, s = cli(ah, ["trip", "--run", str(t / "run.json"), "--trips", str(tp), "--date", "2026-10-06", "--write"])
        check("повтор поездки — замена", s["record"] == "заменена" and s["trips_total"] == 1, s)
        TR = json.loads(tp.read_text(encoding="utf-8"))["trips"][0]
        check("без операций и списка без тега", "untagged_in_wallet" not in TR and "coverage" not in TR and TR["as_of"] == "2026-10-06")
        bad = json.loads(tp.read_text(encoding="utf-8"))
        bad["trips"][0]["operations"] = []
        check("операции в записи не пройдут", any("недопустимые поля" in e for e in ah.validate_trips(bad)))
        print("Поездка с сайта и поездка скилла — одна запись (id site:… ↔ настоящий ID)")
        site_run = json.loads(json.dumps(rw))
        site_run["trip"] = {"id": "site:" + rw["trip"]["name"], "name": rw["trip"]["name"]}
        real_id = rw["trip"]["id"]
        tr0 = {"schema": ah.TRIPS_SCHEMA, "updated": "2026-10-01", "trips": []}
        tr1, i1 = ah.apply_trip(site_run, tr0, "2026-11-01")
        check("поездка сайта записана с id site:…", [x["trip"]["id"] for x in tr1["trips"]] == ["site:" + rw["trip"]["name"]], i1)
        tr2, i2 = ah.apply_trip(rw, tr1, "2026-11-05")
        check("пришла запись скилла: сайтовая заменена, дубля нет",
              [x["trip"]["id"] for x in tr2["trips"]] == [real_id] and i2["trips_total"] == 1 and i2["record"] == "заменена", (tr2, i2))
        changed = json.loads(json.dumps(site_run))
        changed["totals"] = dict(changed["totals"], spent_rub=changed["totals"]["spent_rub"] + 1)
        tr3, i3 = ah.apply_trip(changed, tr2, "2026-11-09")
        check("пришла запись сайта при настоящем ID: числа обновлены, id настоящий",
              [x["trip"]["id"] for x in tr3["trips"]] == [real_id] and len(tr3["trips"]) == 1
              and tr3["trips"][0]["totals"]["spent_rub"] == changed["totals"]["spent_rub"], (tr3, i3))
        check("запись сайта не меняет дат as_of у чужих записей и проходит validate", ah.validate_trips(tr3) == [])
        other = json.loads(json.dumps(rw))
        other["trip"] = {"id": "site:#Другая", "name": "#Другая"}
        tr4, _ = ah.apply_trip(other, tr3, "2026-11-09")
        check("поездка с другим именем — отдельная запись", len(tr4["trips"]) == 2)
        rc, s = cli(ah, ["trip", "--run", jdump(t / "x.json", {"schema": "x"}), "--trips", str(tp), "--date", "2026-10-05"])
        check("чужой вход — blocking", rc == 2)
        rc, s = cli(ah, ["validate", "--trips", str(tp)])
        check("validate", rc == 0 and s["ok"], s)

    print(f"\nИтого: {PASSED} OK, {FAILED} FAIL")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
