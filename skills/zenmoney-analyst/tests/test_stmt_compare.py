#!/usr/bin/env python3
"""stmt_compare.py — сопоставление операций выписки FF с ZenMoney (только чтение).

Зачем (решение 2026-10-10): пользователь вносил операции после поездки руками «до копейки», но
по приложению — на ручной ввод влияют блокировки (ZenMoney на 1–3% выше банка), слияние нескольких
покупок в одну сумму, сдвиг даты на недели, переводы с несовпавшей стороной и пополнения, где
отправитель-банк зачислил в другой валюте. Тест на синтетике по реальным случаям (сентябрь 2026).
"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import stmt_compare as fc  # noqa: E402

ok = fail = 0


def check(name, cond, extra=None):
    global ok, fail
    if cond:
        ok += 1
        print(f"  [OK] {name}")
    else:
        fail += 1
        print(f"  [FAIL] {name} {extra if extra is not None else ''}")


USD, RUB, OTHER = "acc-usd", "acc-rub", "acc-tinkoff"
ACC = {"USD": USD, "RUB": RUB, "KZT": "acc-kzt"}
REFS = {"accounts": {USD: {"instrument": "USD"}, RUB: {"instrument": "RUB"}, "acc-kzt": {"instrument": "KZT"}, OTHER: {"instrument": "RUB"}},
        "categories": {"cat-adj": {"name": "Корректировка"}, "cat-taxi": {"name": "Такси"}}}
_n = [0]


def bexp(date, amt, ccy="USD", place="GRAB", orig=None):
    _n[0] += 1
    return {"id": f"b{_n[0]}", "type": "expense", "date": date, "booking_date": date, "currency": ccy, "amount": str(amt), "merchant": {"name": place}, "original": orig}


def btopup(date, amt, ccy):
    _n[0] += 1
    return {"id": f"b{_n[0]}", "type": "topup", "date": date, "currency": ccy, "amount": str(amt)}


def btransfer(date, rub, usd):
    _n[0] += 1
    return {"id": f"b{_n[0]}", "type": "transfer", "date": date, "from": {"currency": "RUB", "amount": str(rub)}, "to": {"currency": "USD", "amount": str(usd)}}


def zexp(date, amt, acc=USD, comment=None, cat="cat-taxi"):
    _n[0] += 1
    return {"id": f"z{_n[0]}", "date": date, "expense": {"accountId": acc, "amount": amt}, "categoryId": cat, "comment": comment}


def ztr(date, out_acc, out_amt, in_acc, in_amt):
    _n[0] += 1
    return {"id": f"z{_n[0]}", "date": date, "expense": {"accountId": out_acc, "amount": out_amt}, "income": {"accountId": in_acc, "amount": in_amt}}


def run(bank, zen, **kw):
    return fc.compare({"operations": bank}, {"data": zen, "references": REFS}, ACC, **kw)


print("\n== точное и допуск ==")
r = run([bexp("2026-09-10", "9.62")], [zexp("2026-09-10", 9.62)])
check("сумма и дата совпали — matched", r["summary"]["matched"] == 1 and not r["missing_in_zen"] and not r["missing_in_bank"], r["summary"])
r = run([bexp("2026-09-10", "9.62")], [zexp("2026-09-13", 9.62)])
check("дата ±3 дня — всё ещё matched", r["summary"]["matched"] == 1)
r = run([bexp("2026-09-10", "158.55")], [zexp("2026-09-10", 160.19)])
check("ZenMoney выше банка на 1% (блокировка) — differs, не пропуск", r["summary"]["differs"] == 1 and not r["missing_in_zen"], r["summary"])
r = run([bexp("2026-09-10", "100.00")], [zexp("2026-09-10", 110.0)])
check("разница 10% — не пара: и в банке без пары, и в ZenMoney", r["summary"]["missing_in_zen"] == 1 and r["summary"]["missing_in_bank"] == 1, r["summary"])
r = run([bexp("2026-09-10", "1.49")], [zexp("2026-09-10", 1.49), zexp("2026-09-10", 1.49)])
check("один к одному: дубль в ZenMoney виден как «нет в банке»", r["summary"]["matched"] == 1 and r["summary"]["missing_in_bank"] == 1, r["summary"])

print("\n== сдвиг даты ==")
r = run([bexp("2026-08-24", "21.31", place="Nintendo")], [zexp("2026-09-16", 21.31)])
check("сумма до копейки, дата на 23 дня позже — date_shift", r["summary"]["date_shift"] == 1 and r["date_shift"][0]["days"] == 23, r["summary"])
r = run([bexp("2026-07-16", "100.00", place="ANTHROPIC")], [zexp("2026-09-25", 100)])
check("крупная сумма (≥50) внесена через 71 день — date_shift", r["summary"]["date_shift"] == 1, r["summary"])
r = run([bexp("2026-07-16", "10.00")], [zexp("2026-09-25", 10)])
check("мелкая сумма через 71 день — не связываем (слишком легко ошибиться)", r["summary"]["date_shift"] == 0 and r["summary"]["missing_in_zen"] == 1, r["summary"])

print("\n== несколько покупок в одной сумме ==")
nint = [bexp("2026-08-27", "25.58", place="Nintendo CB1"), bexp("2026-08-28", "10.65", place="Nintendo CB2"), bexp("2026-08-28", "8.52", place="Nintendo CB3"),
        bexp("2026-08-28", "10.65", place="Nintendo CB4"), bexp("2026-08-28", "2.12", place="Nintendo CB5"), bexp("2026-08-28", "3.19", place="Nintendo CB6"),
        bexp("2026-10-04", "26.65", place="Nintendo CB7"), bexp("2026-08-24", "21.31", place="Nintendo CB8")]
r = run(nint, [zexp("2026-08-28", 60.71)])
check("60.71 = шесть покупок Nintendo (точная сумма и близкие даты предпочтительнее случайного подмножества)",
      r["summary"]["merged"] == 1 and sorted(b["amount"] for b in r["merged"][0]["bank"]) == sorted(["25.58", "10.65", "10.65", "8.52", "2.12", "3.19"]), r["merged"] and [b["amount"] for b in r["merged"][0]["bank"]])
r = run([bexp("2026-08-28", "10.00", place="Nintendo"), bexp("2026-08-28", "5.00", place="Nintendo")], [zexp("2026-08-28", 99.0)])
check("сумма не собирается — слияния нет, остаётся честное расхождение", r["summary"]["merged"] == 0 and r["summary"]["missing_in_bank"] == 1)
r = run([bexp("2026-08-28", "10.00", place="Nintendo"), bexp("2026-08-28", "5.00", place="Grab")], [zexp("2026-08-28", 15.0)])
check("слияние — только покупки одного места (Nintendo + Grab не склеиваем)", r["summary"]["merged"] == 0)

print("\n== переводы и пополнения ==")
r = run([btransfer("2026-10-03", "1748.00", "20.00")], [ztr("2026-10-03", RUB, 2301.1, USD, 20)])
check("перевод: USD-сторона совпала, RUB нет — partial_transfer", r["summary"]["partial_transfer"] == 1 and r["partial_transfer"][0]["matched_side"] == "зачисление", r["summary"])
r = run([btransfer("2026-08-15", "28044.00", "319.52")], [ztr("2026-08-15", RUB, 28044, USD, 319.52)])
check("перевод RUB→USD, обе стороны — matched", r["summary"]["matched"] == 1)
r = run([btopup("2026-02-17", "125.47", "USD")], [ztr("2026-02-17", OTHER, 10000, RUB, 10000)])
check("банк зачислил USD, ZenMoney — RUB: topup_currency с подразумеваемым курсом", r["summary"]["topup_currency"] == 1 and r["topup_currency"][0]["implied_rate"] == "79.70", r["topup_currency"])
r = run([btopup("2026-08-18", "39500.00", "RUB")], [ztr("2026-08-18", OTHER, 39500, RUB, 39500)])
check("пополнение в той же валюте и сумме — matched", r["summary"]["matched"] == 1)
r = run([btopup("2026-04-16", "251.44", "USD")], [])
check("пополнения нет в ZenMoney — в missing_in_zen", r["summary"]["missing_in_zen"] == 1)

print("\n== корректировки и чужие счета ==")
r = run([], [zexp("2025-04-18", 100, comment="Корректировка баланса")])
check("«Корректировка баланса» в комментарии → adjustment=True", r["missing_in_bank"][0]["adjustment"] is True)
r = run([], [zexp("2025-04-18", 100, cat="cat-adj")])
check("категория «Корректировка» (по имени) → adjustment=True", r["missing_in_bank"][0]["adjustment"] is True)
r = run([], [zexp("2025-04-18", 100, cat="cat-taxi")], adjust_cat="cat-taxi")
check("--adjust-category-id считает корректировкой по id", r["missing_in_bank"][0]["adjustment"] is True)
r = run([], [zexp("2026-09-10", 5, acc=OTHER)])
check("операции чужих счетов (Tinkoff) игнорируются — их не грузим и не сравниваем", r["summary"]["zen_ops"] == 0)

print("\n== окно ==")
r = run([bexp("2026-01-10", "5.00"), bexp("2026-09-10", "5.00")], [], date_from="2026-09-01", date_to="2026-09-30")
check("окно режет обе стороны", r["summary"]["bank_ops"] == 1 and r["missing_in_zen"][0]["date"] == "2026-09-10")

print("\n== склейка страниц MCP ==")
m = fc.merge_pages([{"data": [{"id": "a", "date": "2026-01-01"}, {"id": "t", "date": "2026-01-02"}], "references": {"accounts": {"x": 1}}},
                    {"data": [{"id": "t", "date": "2026-01-02"}, {"id": "b", "date": "2026-01-03"}], "references": {"accounts": {"y": 2}, "user": {"id": 1}}}])
check("перевод между двумя счетами FF приходит в обеих выгрузках — один раз", [r["id"] for r in m["data"]] == ["a", "t", "b"])
check("справочники сливаются", set(m["references"]["accounts"]) == {"x", "y"})

print(f"\nИтого: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
