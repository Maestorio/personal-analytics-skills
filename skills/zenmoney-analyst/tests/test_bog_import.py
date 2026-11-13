#!/usr/bin/env python3
"""parse_bog_statement.py + bog_normalize.py — импорт Excel-выписок Bank of Georgia (решение 2026-10-11).

Синтетические xlsx строятся в тесте (личных данных нет). Интеграция на реальных выгрузках из
docs/zenmoney/source/ идёт, только если файлы лежат рядом (в git их нет).
"""
import copy
import json
import sys
import tempfile
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
warnings.simplefilter("ignore")
import openpyxl  # noqa: E402
import bog_normalize as bn  # noqa: E402
import parse_bog_statement as pb  # noqa: E402
import stmt_import as si  # noqa: E402

ok = fail = 0


def check(name, cond, extra=None):
    global ok, fail
    if cond:
        ok += 1
        print(f"  [OK] {name}")
    else:
        fail += 1
        print(f"  [FAIL] {name} {extra if extra is not None else ''}")


IBAN = "GE00BG0000000000000001"
CARD_USD = "Payment - Amount: USD10.00; Merchant: COFFEE, Georgia; MCC:5814; Date: 02/03/2026 09:00; Card No: ****1111; Payment transaction amount and currency: 10.00 USD"
CARD_JPY = "Payment - Amount: JPY1,000.00; Merchant: SHOP, A, Japan; MCC:5399; Date: 03/03/2026 00:00; Card No: ****1111; Payment transaction amount and currency: 18.31 GEL; Bank conversion commission fee: 0.13 USD"
REFUND = "Credit Funds - Amount: USD4.00; Merchant: COFFEE, Georgia; MCC:5814; Date: 04/03/2026 10:00; Card No: ****1111; Payment transaction amount and currency: 4.00 USD"


def make(path, rows, opening, closing, iban=IBAN, period=("01/03/2026", "31/03/2026"), marks=True):
    """rows: [(дата, текст, {валюта: сумма})]; «Balance» после каждой даты — как у банка."""
    wb = openpyxl.Workbook()
    d = wb.active
    d.title = "Details"
    d.append(["Account Statement"])
    d.append(["Account Owner:", None, "Test Owner"])
    d.append(["Account No:", None, iban])
    d.append(["Card:", None, "MC Standard Test (1111)"])
    d.append(["Filter Date From:", None, period[0]])
    d.append(["Filter Date To:", None, period[1]])
    for label, bal in (("Starting Balance:", opening), ("End Balance:", closing)):
        for i, (c, v) in enumerate(bal.items()):
            d.append([label if i == 0 else None, None, f"{v}{c}"])
    t = wb.create_sheet("Transactions")
    t.append(["Date", "Details", None, "GEL", "USD", "EUR", "GBP"])
    run = {c: float(opening.get(c, 0)) for c in ("GEL", "USD", "EUR", "GBP")}
    for i, (date, text, amt) in enumerate(rows):
        t.append([date, " " + text, None] + [amt.get(c) for c in ("GEL", "USD", "EUR", "GBP")])
        for c, v in amt.items():
            run[c] += v
        if marks and (i == len(rows) - 1 or rows[i + 1][0] != date):
            t.append(["Balance", " ", None] + [round(run[c], 2) for c in ("GEL", "USD", "EUR", "GBP")])
    wb.save(path)


tmp = Path(tempfile.mkdtemp(prefix="bogtest-"))
rows = [
    ("02/03/2026", CARD_USD, {"USD": -10.0}),
    ("04/03/2026", REFUND, {"USD": 4.0}),
    ("05/03/2026", CARD_JPY, {"GEL": -18.31}),
    ("06/03/2026", "Income - Amount GEL37.07; Automatic conversion, rate: 3.066", {"GEL": 37.07}),
    ("06/03/2026", "Payment - Amount EUR12.09; Automatic conversion, rate: 3.066", {"EUR": -12.09}),
    ("07/03/2026", "Income - Amount EUR36.16; Automatic conversion, rate: 1.235717", {"EUR": 36.16}),
    ("07/03/2026", "Payment - Amount USD44.68; Automatic conversion, rate: 1.235717", {"USD": -44.68}),
    ("28/03/2026", "Payment - Amount GEL5.00; Set S Maintenance Fee.Acct #", {"GEL": -5.0}),
    ("28/03/2026", "Income - Amount GEL5.00; Set S Maintenance Fee.Acct #", {"GEL": 5.0}),
    ("28/03/2026", "Payment - Amount USD1.87; Set S Maintenance Fee.Acct #", {"USD": -1.87}),
    ("28/03/2026", "Payment - Amount USD10.00; Placing funds on deposit", {"USD": -10.0}),
    ("28/03/2026", "Income - Amount USD10.00; Placing funds on deposit", {"USD": 10.0}),
    ("29/03/2026", "Outgoing Transfer - Amount: USD20.00; Beneficiary: Test; Account: GE11BG0000000000000002USD; Bank: Bank Of Georgia BAGAGE22; Details: Transfer to Deposit", {"USD": -20.0}),
    ("30/03/2026", "Income - Amount GEL300.00; Money transfer received - Sender: SOMEONE; System: ZolotayaKorona", {"GEL": 300.0}),
    ("31/03/2026", "Payment - Amount GEL1.00; Payment, 31/03/2026 , payment service, Magticom, Phone number 599000000, payment code - 1", {"GEL": -1.0}),
]
closing = {"GEL": 300.0 - 18.31 + 37.07 - 1.0, "USD": 100.0 - 10 + 4 - 44.68 - 1.87 - 20 + 36.16 * 0 + 0, "EUR": 36.16 - 12.09, "GBP": 0}
# USD: 100 − 10 + 4 − 44.68 (кросс-обмен, EUR получен) − 1.87 − 20; GEL: +37.07 − 18.31 + 300 − 1 (+5−5 комиссия)
closing["GEL"] = round(closing["GEL"], 2)
closing["USD"] = round(closing["USD"], 2)
closing["EUR"] = round(closing["EUR"], 2)
f1 = tmp / "a.xlsx"
make(f1, rows, {"GEL": 0, "USD": 100.0, "EUR": 0, "GBP": 0}, closing)

print("\n== парсер: шапка и проверки ==")
st = pb.parse_statement(str(f1))
check("счёт, карты, период (дд.мм.гггг), без ФИО", st["meta"]["account"] == IBAN and st["meta"]["cards"] == ["1111"] and st["meta"]["period_from"] == "01.03.2026" and "Test Owner" not in str(st["meta"]))
check("остатки по валютам разобраны", st["meta"]["opening"]["USD"] == "100.0" and st["meta"]["closing"]["EUR"] == "24.07", st["meta"])
check("строк = строкам таблицы, «Balance» не строка", len(st["rows"]) == len(rows))
check("все проверки сошлись", st["checks"]["ok"] and st["checks"]["balance_marks"] == 9, st["checks"])
r0 = st["rows"][0]
check("расход: debit без знака, credit пуст, валюта колонки", r0["debit"] == "10.00" and r0["credit"] is None and r0["currency"] == "USD")

bad_close = copy.deepcopy(closing)
bad_close["USD"] += 0.01
make(tmp / "b.xlsx", rows, {"GEL": 0, "USD": 100.0, "EUR": 0, "GBP": 0}, bad_close)
check("исходящий остаток на копейку не тот — ok=False", not pb.parse_statement(str(tmp / "b.xlsx"))["checks"]["ok"])

wrong_mark = list(rows)
make(tmp / "c.xlsx", wrong_mark, {"GEL": 0, "USD": 100.0, "EUR": 0, "GBP": 0}, closing)
wb = openpyxl.load_workbook(tmp / "c.xlsx")
ws = wb["Transactions"]
ws.cell(row=3, column=5).value = 95.0  # «Balance» после 1-го дня: банк 95, расчёт 90
wb.save(tmp / "c.xlsx")
check("ненулевое расхождение в «Balance» — ошибка", not pb.parse_statement(str(tmp / "c.xlsx"))["checks"]["ok"])

ws.cell(row=3, column=5).value = 0.0  # нулевое показание при ненулевом расчёте — причуда банка
wb.save(tmp / "c.xlsx")
q = pb.parse_statement(str(tmp / "c.xlsx"))["checks"]
check("нулевое показание в «Balance» — причуда (zero_quirk), не ошибка", q["ok"] and len(q["zero_quirk"]) == 1, q)

make(tmp / "d.xlsx", [("02/03/2026", "Income - Amount USD10.00; X", {"USD": -10.0})], {"USD": 10.0}, {"USD": 0.0})
check("знак суммы против слова «Income» — ошибка", not pb.parse_statement(str(tmp / "d.xlsx"))["checks"]["ok"])

make(tmp / "e.xlsx", [], {"GEL": 5, "USD": 0}, {"GEL": 5, "USD": 0}, marks=False)
check("пустая выписка (операций нет, остатки равны) — ok", pb.parse_statement(str(tmp / "e.xlsx"))["checks"]["ok"])

try:
    wb2 = openpyxl.Workbook()
    wb2.save(tmp / "x.xlsx")
    pb.parse_statement(str(tmp / "x.xlsx"))
    check("чужой xlsx — StatementError", False)
except pb.StatementError:
    check("чужой xlsx — StatementError, не угадывается", True)

print("\n== нормализатор ==")
res = bn.normalize({"statements": [{**st, "file": "a.xlsx"}]})
ops = res["operations"]
by = lambda t: [o for o in ops if o["type"] == t]
exp = [o for o in by("expense") if o.get("merchant") and o["merchant"]["name"] == "COFFEE"]
check("покупка по карте: дата транзакции, дата проводки, место, карта", exp and exp[0]["date"] == "2026-03-02" and exp[0]["booking_date"] == "2026-03-02" and exp[0]["merchant"]["country"] == "Georgia" and exp[0]["merchant"]["card"] == "1111", exp)
jpy = [o for o in by("expense") if o.get("merchant") and o["merchant"]["name"] == "SHOP, A"]
check("покупка в чужой валюте: списано GEL, исходная сумма JPY в original; запятая в названии места", jpy and jpy[0]["currency"] == "GEL" and jpy[0]["amount"] == "18.31" and jpy[0]["original"] == {"amount": "1000.00", "currency": "JPY"}, jpy)
check("покупка в валюте списания — original пуст", exp[0]["original"] is None)
check("возврат (Credit Funds) — refund с местом", by("refund") and by("refund")[0]["amount"] == "4.00" and by("refund")[0]["merchant"]["name"] == "COFFEE")
tr = by("transfer")
gel_eur = [t for t in tr if {t["from"]["currency"], t["to"]["currency"]} == {"GEL", "EUR"}]
check("обмен GEL→EUR: пара по курсу, обе суммы", gel_eur and gel_eur[0]["from"] == {"currency": "EUR", "amount": "12.09"} and gel_eur[0]["to"] == {"currency": "GEL", "amount": "37.07"}, tr)
cross = [t for t in tr if {t["from"]["currency"], t["to"]["currency"]} == {"USD", "EUR"}]
check("кросс-обмен USD→EUR: пара по курсу (USD за EUR)", cross and cross[0]["from"]["currency"] == "USD" and cross[0]["to"]["amount"] == "36.16", tr)
check("гасящаяся пара без обмена («Placing funds on deposit» USD 10 / 10) — в internal, не операция", len(res["internal"]) == 1 and res["internal"][0]["amount"] == "10.00", res["internal"])
fees = [o for o in by("expense") if o.get("kind") == "fee"]
check("комиссия в GEL, оплаченная из USD (три строки) — как в ZenMoney: расход GEL 5 + обмен USD 1.87→GEL 5", fees and fees[0]["currency"] == "GEL" and fees[0]["amount"] == "5.00" and any(t["how"] == "fee-conversion" and t["from"] == {"currency": "USD", "amount": "1.87"} and t["to"] == {"currency": "GEL", "amount": "5.00"} for t in by("transfer")), (fees, by("transfer")))
to = by("transfer_out")
check("перевод на свой депозит — transfer_out со счётом контрагента (без суффикса валюты)", to and to[0]["counterparty_account"] == "GE11BG0000000000000002" and to[0]["amount"] == "20.00", to)
tu = by("topup")
check("денежный перевод — topup с системой", tu and "ZolotayaKorona" in tu[0]["text"] and tu[0]["amount"] == "300.00")
svc = [o for o in by("expense") if o.get("merchant") and o["merchant"]["name"] == "Magticom"]
check("платёж услуги — expense с получателем", svc and svc[0]["amount"] == "1.00")
check("флагов нет, незнакомых строк нет", res["flags"] == [], res["flags"])
check("сверка остатка: невязка 0 по каждой валюте", all(v["residual"] in ("0", "0.00") for v in res["reconcile"][IBAN].values()), res["reconcile"])
check("id стабильны и уникальны", len({o["id"] for o in ops}) == len(ops) and res == bn.normalize({"statements": [{**st, "file": "a.xlsx"}]}))

print("\n== нормализатор: не угадывает ==")
rows_u = rows + [("31/03/2026", "Weird - something new", {"USD": -1.0})]
make(tmp / "u.xlsx", rows_u, {"GEL": 0, "USD": 100.0, "EUR": 0, "GBP": 0}, {**closing, "USD": round(closing["USD"] - 1.0, 2)})
ru = bn.normalize({"statements": [pb.parse_statement(str(tmp / "u.xlsx"))]})
check("незнакомая строка — флаг unknown-row, сверка всё равно сходится", [f["kind"] for f in ru["flags"]] == ["unknown-row"] and all(v["residual"] in ("0", "0.00") for v in ru["reconcile"][IBAN].values()), ru["flags"])
rows_c = [r for r in rows if "44.68" not in r[1]]
cl = {**closing, "USD": round(closing["USD"] + 44.68, 2)}
make(tmp / "v.xlsx", rows_c, {"GEL": 0, "USD": 100.0, "EUR": 0, "GBP": 0}, cl)
rv = bn.normalize({"statements": [pb.parse_statement(str(tmp / "v.xlsx"))]})
check("нога обмена без пары — флаг conversion-unmatched, не выдумывается", [f["kind"] for f in rv["flags"]] == ["conversion-unmatched"] and not [t for t in rv["operations"] if t["type"] == "transfer" and t["how"] != "fee-conversion" and "USD" in (t["from"]["currency"], t["to"]["currency"])], rv["flags"])
check("сверка остатка с непарной ногой — невязка 0 (деньги учтены, операции нет)", all(v["residual"] in ("0", "0.00") for v in rv["reconcile"][IBAN].values()), rv["reconcile"])

bad = copy.deepcopy(st)
bad["checks"]["ok"] = False
try:
    bn.normalize({"statements": [bad]})
    check("проверка парсера не сошлась — Blocking", False)
except bn.Blocking:
    check("проверка парсера не сошлась — Blocking", True)
st2 = copy.deepcopy(st)
st2["meta"]["period_from"], st2["meta"]["period_to"] = "15.03.2026", "15.04.2026"
try:
    bn.normalize({"statements": [st, st2]})
    check("пересекающиеся периоды одного IBAN — Blocking", False)
except bn.Blocking:
    check("пересекающиеся периоды одного IBAN — Blocking (задвоение)", True)
st3 = copy.deepcopy(st)
st3["meta"]["account"] = "GE00BG0000000000000009"
check("тот же период у другого IBAN — можно", len(bn.normalize({"statements": [st, st3]})["reconcile"]) == 2)

print("\n== сравнение с ZenMoney (stmt_compare) ==")
import stmt_compare as sc  # noqa: E402
A = {"GEL": "acc-gel", "USD": "acc-usd", "EUR": "acc-eur"}
Z = lambda i, d, out=None, inc=None, **kw: {"id": i, "date": d, "hold": False, "source": "plugin", **({"expense": {"accountId": out[0], "amount": out[1]}} if out else {}), **({"income": {"accountId": inc[0], "amount": inc[1]}} if inc else {}), **kw}
zen = {"data": [
    Z("z1", "2026-03-02", out=("acc-usd", 10)), Z("z2", "2026-03-04", inc=("acc-usd", 4)), Z("z3", "2026-03-05", out=("acc-gel", 18.31)),
    Z("z4", "2026-03-06", out=("acc-eur", 12.09), inc=("acc-gel", 37.07)), Z("z5", "2026-03-07", out=("acc-usd", 44.68), inc=("acc-eur", 36.16)),
    Z("z6", "2026-03-28", out=("acc-gel", 5)), Z("z7", "2026-03-28", out=("acc-usd", 1.87), inc=("acc-gel", 5)),
    Z("z8", "2026-03-29", out=("acc-usd", 20), inc=("acc-dep", 20)),
    Z("z9", "2026-03-30", inc=("acc-gel", 300)), Z("z10", "2026-03-31", out=("acc-gel", 1)),
], "references": {"accounts": {"acc-gel": {"instrument": "GEL"}, "acc-usd": {"instrument": "USD"}, "acc-eur": {"instrument": "EUR"}, "acc-dep": {"instrument": "USD"}}}}
cmp_ = sc.compare(copy.deepcopy(res), zen, A, with_transfer_out=True)  # compare помечает операции банка — каждому прогону своя копия
check("синхронизированные операции сходятся 1:1 (в т.ч. комиссия-тройка и кросс-обмен), расхождений нет", cmp_["summary"]["matched"] == 9 and not cmp_["missing_in_zen"] and not cmp_["missing_in_bank"], cmp_["summary"])
check("перевод на депозит: к другому счёту ZenMoney — отдельный класс, не «потеряно»", len(cmp_["to_other_account"]) == 1 and cmp_["summary"]["to_other_account"] == 1, cmp_["summary"])
zen2 = {**zen, "data": [z for z in zen["data"] if z["id"] != "z1"] + [Z("z11", "2026-03-10", out=("acc-gel", 33.03))]}
c2 = sc.compare(copy.deepcopy(res), zen2, A, with_transfer_out=True)
check("лишний расход в ZenMoney — missing_in_bank, нехватающий — missing_in_zen", [z["id"] for z in c2["missing_in_bank"]] == ["z11"] and [b["place"] for b in c2["missing_in_zen"]] == ["COFFEE"], c2["summary"])
check("без --with-transfer-out переводы на свои счета не сравниваются (поведение FF не меняется)", "transfer_out" not in str(sc.compare(copy.deepcopy(res), zen, A)["missing_in_zen"]))

print("\n== stmt_import: банк узнаётся по содержимому xlsx ==")
check("BOG по IBAN с кодом BG в шапке", si.detect_bank(si._read_head(str(f1))) == "bog")
check("IBAN другого банка Грузии — не BOG", si.detect_bank("Account No: GE11TB0000000000000001") is None)
check("битый/чужой xlsx — не узнан", si.detect_bank(si._read_head(str(tmp / "x.xlsx"))) is None)
out = si.run([str(f1), str(tmp / "x.xlsx")])
check("run: BOG разобран, чужой xlsx в unrecognized", "bog" in out["banks"] and out["unrecognized"] == ["x.xlsx"] and out["files"][0]["bank"] == "bog" and out["missing"] == [], out["unrecognized"])

print("\n== интеграция на реальных выгрузках (если лежат рядом) ==")
src = ROOT.parent.parent / "docs" / "zenmoney" / "source"
real = sorted(src.glob("Report-*.xlsx")) if src.exists() else []
if real:
    r = si.run([str(p) for p in real])
    s = r["banks"].get("bog")
    check("все реальные выписки BOG разобраны и проверки сошлись", s is not None and all(f["checks_ok"] for f in r["files"]) and not r["unrecognized"], r["files"])
    check("реальные: незнакомых строк и непарных обменов нет", s and s["flags"] == [], s and s["flags"])
    check("реальные: сверка остатка — невязка 0 по всем счетам и валютам", s and all(v["residual"].rstrip("0").rstrip(".") in ("0", "") for a in s["reconcile"].values() for v in a.values()), s and s["reconcile"])
    snap = src / "bog-regression"  # личный снимок ZenMoney (страницы list_transactions + id счетов + ожидаемые числа), в git не идёт
    if (snap / "accounts.json").exists() and s is not None:
        meta = json.loads((snap / "accounts.json").read_text(encoding="utf-8"))
        zen_real = sc.merge_pages([json.loads((snap / n).read_text(encoding="utf-8")) for n in sorted(p.name for p in snap.glob("zen-page*.json"))])
        ops_real = {"operations": [o for o in s["operations"] if o["account"] == meta["iban"]]}
        c = sc.compare(ops_real, zen_real, meta["accounts"], *meta["window"], with_transfer_out=True)
        got = {k: c["summary"][k] for k in meta["expected"]}
        check("реальные: сравнение выписки со снимком ZenMoney даёт зафиксированные числа (регрессия)", got == meta["expected"], (got, meta["expected"]))
    else:
        print("  (нет снимка ZenMoney bog-regression — пропуск)")
else:
    print("  (нет файлов — пропуск)")

print(f"\nИтого: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
