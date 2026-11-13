#!/usr/bin/env python3
"""parse_ff_statement.py + ff_normalize.py — выписки FF (Freedom Bank KZ) → операции для ZenMoney.

Зачем (решение 2026-10-10): FF — мультивалютная карта (RUB, USD, KZT, EUR в тандеме); покупка
в валюте без денег идёт цепочкой «конвертация → покупка», а выписка — PDF с узкими колонками,
где суммы с тысячами переносятся («1» / «000.00»). Тест на синтетике (личные PDF в репозитории
не лежат); если рядом лежат реальные выписки 2026 (docs/zenmoney/текущ_*.pdf) — дополнительно
гонится интеграционная проверка (все три проверки парсера + сверка остатка).
"""
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ff_normalize as fn  # noqa: E402
import parse_ff_statement as pf  # noqa: E402

ok = fail = 0


def check(name, cond, extra=None):
    global ok, fail
    if cond:
        ok += 1
        print(f"  [OK] {name}")
    else:
        fail += 1
        print(f"  [FAIL] {name} {extra if extra is not None else ''}")


def W(x, y, t, w=None):
    return (x, y, x + (w if w is not None else 5 * len(t)), y + 6, t)


# ---------------------------------------------------------------- синтетическая страница
def fake_page():
    h = [W(430, 372, "Дебет", 15), W(458, 372, "Кредит", 20), W(493, 372, "Назначение"), W(527, 372, "платежа"), W(90, 375, "документа", 30)]
    rows = [
        # строка 1: дебет 1 000.00 (тысячи отдельным словом над «000.00»), покупка
        W(40, 400, "05.01.2026", 25), W(98, 400, "123", 12),
        W(435, 394, "1", 3), W(425, 402, "000.00", 25),
        W(500, 394, "Дата"), W(500, 400, "Операция:"), W(500, 406, "Покупка"),
        # строка 2 (через 40 pt): кредит 12.50
        W(40, 440, "06.01.2026", 25), W(98, 440, "456", 12),
        W(462, 440, "12.50", 25), W(500, 440, "Возврат"),
        # длинное место заезжает влево под колонки сумм и содержит код из цифр (не сумма)
        W(440, 446, "099170", 25),
        # итог
        W(45, 480, "Итого:", 15), W(76, 480, "2", 5), W(435, 476, "1", 3), W(425, 484, "000.00", 25), W(462, 484, "12.50", 25),
    ]
    return [h + rows]


print("\n== parse_ff_statement: разбор по координатам ==")
rows, total = pf.parse_rows(fake_page())
check("две строки таблицы по вертикальным разрывам", len(rows) == 2, rows)
check("тысячи «1» + «000.00» склеены в 1000.00", rows[0]["debit"] == "1000.00" and rows[0]["credit"] is None, rows[0])
check("кредит читается в своей колонке", rows[1]["credit"] == "12.50" and rows[1]["debit"] is None, rows[1])
check("номер документа из колонки", rows[0]["doc"] == "123", rows[0]["doc"])
check("шестизначный код не принят за сумму", rows[1]["credit"] == "12.50")
check("итоговая строка: N и суммы колонок", total == {"count": 2, "debit": "1000.00", "credit": "12.50"}, total)
meta = {"opening": "0.00", "closing": "-987.50"}
check("проверки сходятся: строки, дебет, кредит, остаток", pf.check_statement(meta, rows, total)["ok"] is True)
check("остаток не сошёлся → ok=False", pf.check_statement({"opening": "0.00", "closing": "5.00"}, rows, total)["ok"] is False)
check("число строк не равно «Итого» → ok=False", pf.check_statement(meta, rows[:1], total)["ok"] is False)

print("\n== parse_meta: шапка ==")
txt = ("Выписка по депозитному счету за период с 01.01.2026 по 31.12.2026\nСчет: KZ84551B429488011EUR\nКлиент: Иванов Иван\n"
       "ИИН/БИН: 123456789012\nВалюта: EUR\nВходящий остаток: 0.00\nИсходящий остаток: 32 698.92\n")
m = pf.parse_meta(txt)
check("тип, валюта, счёт, остатки (с пробелом тысяч)", (m["kind"], m["currency"], m["account"], m["closing"]) == ("deposit", "EUR", "KZ84551B429488011EUR", "32698.92"), m)
check("ФИО и ИИН в мету не попадают", "Иванов" not in str(m) and "123456789012" not in str(m))
m0 = pf.parse_meta("Выписка по текущему счету за период с 01.01.2025 по 31.12.2025\nСчет: KZ1KZT\nВалюта: KZT\nВходящий остаток:\nИсходящий остаток:\n")
check("пустая выписка (банк оставляет остатки без числа): None, а не ошибка шапки", m0["opening"] is None and m0["closing"] is None, m0)
try:
    pf.parse_meta("мусор")
    check("шапка без полей — ошибка", False)
except pf.StatementError:
    check("шапка без полей — ошибка", True)

# ---------------------------------------------------------------- нормализатор
def row(date, doc, debit=None, credit=None, purpose="", acct=None):
    return {"date": date, "doc": doc, "debit": debit, "credit": credit, "counterparty_account": acct, "purpose": purpose}


def purchase(date, doc, debit, amt, ccy, merchant="123\\THA\\BANGKOK\\MCD-001 WANGBURA"):
    return row(date, doc, debit=debit, purpose=f"Дата транзакции: {date} Код авторизации: 1 Номер карты: 5269********1 Сумма транзакции: {amt} {ccy} Операция: Покупка с нашей карты в чужом устройстве {merchant}".strip())


def stmt(ccy, rows, opening="0.00", kind="current"):
    d = sum((Decimal(r["debit"]) for r in rows if r["debit"]), Decimal(0))
    k = sum((Decimal(r["credit"]) for r in rows if r["credit"]), Decimal(0))
    return {"file": f"{kind}_{ccy}.pdf", "meta": {"currency": ccy, "kind": kind, "period_from": "01.01.2026", "period_to": "31.12.2026",
                                                    "opening": opening, "closing": str(Decimal(opening) + k - d), "account": "KZ" + ccy},
            "rows": rows, "checks": {"ok": True}}


def build(usd=(), eur=(), kzt=(), rub=(), deps=()):
    return {"statements": [stmt("USD", list(usd)), stmt("EUR", list(eur)), stmt("KZT", list(kzt)), stmt("RUB", list(rub)), *deps]}


print("\n== классификация строк ==")
check("вклад — движение внутри FF", fn.classify("Прием вклада по договору KZ1 в сумме .04 USD", "0.04", None) == "sweep")
check("прием вклада с потерянным началом строки (2025: «по договору KZ… в сумме .16 USD. Вкладчик…») — тоже внутреннее", fn.classify("по договору KZ09551B429486702USD в сумме .16 USD. Вкладчик:Иванов Алексей Юрьевич.", "0.16", None) == "sweep")
check("выплата вклада с депозита — тоже", fn.classify("Выплата вклада с депозитного договора KZ1", None, "6.20") == "sweep")
check("покупка / возврат", fn.classify("Операция: Покупка с нашей карты", "1", None) == "purchase" and fn.classify("Операция: Возврат покупки по своей карте", None, "1") == "refund")
check("пополнение из другого банка — кредит", fn.classify("Перевод собственных средств на счет в другом банке.", None, "320.10") == "topup")
check("Transfer of own funds и Конвертация — ноги обмена", fn.classify("Transfer of own funds", "1", None) == "convleg" and fn.classify("Конвертация", None, "1") == "convleg")
check("проценты — отдельно", fn.classify("Выплата процентов по вкладу № 1", None, "0.01") == "interest")
check("незнакомое — unknown, не молча", fn.classify("что-то новое", "1", None) == "unknown")

print("\n== место платежа ==")
mm = fn.merchant_of("... в чужом устройстве TN9YXKW\\THA\\BANGKOK\\GIFTOWN VACATION HOME")
check("терминал\\СТРАНА\\ГОРОД\\ТОЧКА", mm and (mm["country"], mm["city"], mm["name"]) == ("THA", "BANGKOK", "GIFTOWN VACATION HOME"), mm)
check("места нет — None (банк иногда не пишет)", fn.merchant_of("Операция: Покупка с нашей карты в чужом устройстве") is None)

print("\n== сумма в VND: банк пишет в сотых ==")
rv = fn.normalize(build(usd=[purchase("10.09.2026", "1", "9.62", "2440", "VND", "1\\VNM\\LAO CAI\\STARBUCKS")]))
vo = [o for o in rv["operations"] if o["type"] == "expense"]
check("2440 VND в выписке = ₫244 000 (скриншот Apple Pay); USD-сумма не меняется", len(vo) == 1 and vo[0]["original"] == {"amount": "244000", "currency": "VND"} and vo[0]["amount"] == "9.62", vo)

print("\n== цепочка EUR: конвертация + покупка = одна покупка в USD ==")
res = fn.normalize(build(
    usd=[row("12.01.2026", "1", debit="39.87", purpose="Конвертация"), row("12.01.2026", "2", debit="37.46", purpose="Конвертация")],
    eur=[row("12.01.2026", "3", credit="31.82", purpose="Конвертация"), row("12.01.2026", "4", credit="33.84", purpose="Конвертация"),
         purchase("12.01.2026", "5", "33.84", "33.84", "EUR"), purchase("12.01.2026", "6", "31.82", "31.82", "EUR")]))
ex = sorted((o for o in res["operations"] if o["type"] == "expense"), key=lambda o: o["amount"])
check("две покупки в USD с исходной суммой в EUR", [(o["currency"], o["amount"], o["original"]["amount"]) for o in ex] == [("USD", "37.46", "31.82"), ("USD", "39.87", "33.84")], ex)
check("пары по курсу, не крест-накрест (39.87↔33.84)", not any(f["kind"].startswith("conversion") for f in res["flags"]), res["flags"])
check("конвертации не остались переводами", not [o for o in res["operations"] if o["type"] == "transfer"])
check("транзит пуст", res["transit_leftover"]["EUR"]["amount"] == "0", res["transit_leftover"])

print("\n== возврат в EUR + обратная конвертация частями = один возврат в USD ==")
res = fn.normalize(build(
    usd=[row("12.01.2026", "1", debit="37.46", purpose="Конвертация"), row("21.02.2026", "2", credit="8.60", purpose="Конвертация"), row("21.02.2026", "3", credit="28.20", purpose="Конвертация")],
    eur=[row("12.01.2026", "4", credit="31.82", purpose="Конвертация"), purchase("12.01.2026", "5", "31.82", "31.82", "EUR"),
         row("18.02.2026", "6", credit="31.82", purpose="Дата транзакции: 16.02.2026 Сумма транзакции: 31.82 EUR Операция: Возврат покупки по своей карте в чужом ТСП"),
         row("21.02.2026", "7", debit="7.37", purpose="Конвертация"), row("21.02.2026", "8", debit="24.45", purpose="Конвертация")]))
rf = [o for o in res["operations"] if o["type"] == "refund"]
check("один возврат, а не по числу конвертаций", len(rf) == 1, rf)
check("сумма возврата = сумма зачисленных USD", rf and rf[0]["amount"] == "36.80" and rf[0]["currency"] == "USD", rf)
check("дата возврата — по транзакции, не по обратной конвертации", rf and rf[0]["date"] == "2026-02-16", rf)

print("\n== KZT: пары по «курсу» из текста, копейки округления — в цену ==")
kz = lambda d, doc, a, rate: row(d, doc, credit=a, purpose=f"Зачисление проданой валюты KZT, заявка №{doc} на сумму {a} по курсу {rate}. Дата валютирования Конвертация")
res = fn.normalize(build(
    usd=[row("27.04.2026", "1", debit="3.28", purpose="Конвертация"), row("27.04.2026", "2", debit="3.27", purpose="Конвертация")],
    kzt=[kz("27.04.2026", "10", "1487.85", "455"), kz("27.04.2026", "11", "1492.40", "455"),
         purchase("28.04.2026", "12", "1490.00", "1490", "KZT", "9\\IRL\\CORK\\APPLE.COM/BILL"), purchase("28.04.2026", "13", "1490.00", "1490", "KZT", "9\\IRL\\CORK\\APPLE.COM/BILL")]))
ex = [o for o in res["operations"] if o["type"] == "expense"]
check("две покупки по 1490 KZT в USD", len(ex) == 2 and all(o["original"]["currency"] == "KZT" for o in ex), ex)
check("сумма цен = списанным USD (6.55), копейки округления в цене", sum(Decimal(o["amount"]) for o in ex) == Decimal("6.55"), [o["amount"] for o in ex])
check("остаток транзита — копейки KZT, не операция", res["transit_leftover"]["KZT"]["amount"] == "0.25", res["transit_leftover"])

print("\n== RUB→USD: обмен между реальными валютами = перевод ==")
res = fn.normalize(build(
    rub=[row("15.08.2026", "1", debit="28044.00", purpose="Transfer of own funds")],
    usd=[row("15.08.2026", "2", credit="319.52", purpose="Transfer of own funds")]))
tr = [o for o in res["operations"] if o["type"] == "transfer"]
check("один перевод RUB→USD с обеими суммами", len(tr) == 1 and tr[0]["from"] == {"currency": "RUB", "amount": "28044.00"} and tr[0]["to"] == {"currency": "USD", "amount": "319.52"}, tr)

print("\n== пополнение и вклад ==")
res = fn.normalize(build(usd=[row("30.01.2026", "1", credit="320.10", purpose="Перевод собственных средств на счет в другом банке."),
                              row("30.01.2026", "2", debit="320.10", purpose="Прием вклада по договору KZ1 в сумме 320.1 USD.")]))
check("пополнение — операция topup", [o["type"] for o in res["operations"]] == ["topup"], res["operations"])
check("прием вклада в операции не попал", len(res["operations"]) == 1)

print("\n== не угадываем ==")
res = fn.normalize(build(usd=[row("12.01.2026", "1", debit="40.00", purpose="Конвертация")], eur=[row("12.01.2026", "2", credit="30.00", purpose="Конвертация"), row("12.01.2026", "3", credit="31.00", purpose="Конвертация")]))
check("ног списания меньше, чем зачисления → флаг", any(f["kind"] == "conversion-unbalanced" for f in res["flags"]), res["flags"])
res = fn.normalize(build(eur=[purchase("12.01.2026", "1", "10.00", "10", "EUR")]))
check("покупка в транзитной валюте без конвертации → флаг, не выдумка", any(f["kind"] == "transit-unfunded" for f in res["flags"]), res["flags"])
res = fn.normalize(build(usd=[row("01.02.2026", "1", debit="5.00", purpose="Непонятная операция")]))
check("незнакомая строка → флаг unknown-row", any(f["kind"] == "unknown-row" for f in res["flags"]))
res = fn.normalize(build(usd=[purchase("02.01.2026", "1", "6.16", "22.08", "PLN", "")]))
check("покупка без места → флаг no-merchant, операция есть", any(f["kind"] == "no-merchant" for f in res["flags"]) and res["operations"][0]["merchant"] is None)

print("\n== обязательные выписки ==")
try:
    fn.normalize({"statements": [stmt("USD", []), stmt("RUB", []), stmt("KZT", [])]})
    check("нет текущей выписки EUR → blocking", False)
except fn.Blocking as e:
    check("нет текущей выписки EUR → blocking", "EUR" in str(e), str(e))
bad = build()
bad["statements"][0]["checks"] = {"ok": False}
try:
    fn.normalize(bad)
    check("выписка не прошла проверки парсера → blocking", False)
except fn.Blocking:
    check("выписка не прошла проверки парсера → blocking", True)

print("\n== сверка остатка: текущий + депозит ==")
dep = stmt("USD", [row("04.01.2026", "9", credit="0.01", purpose="Выплата процентов по вкладу № 1 за период")], opening="0.00", kind="deposit")
res = fn.normalize(build(usd=[row("02.01.2026", "1", credit="10.00", purpose="Перевод собственных средств на счет в другом банке.")], deps=[dep]))
rc = res["reconcile"]["USD"]
check("пополнение 10.00 + проценты 0.01: остаток сошёлся", rc["checked"] and rc["residual"] == "0.00" and rc["interest"] == "0.01", rc)
check("без депозитной выписки — не проверено, причина названа", fn.normalize(build())["reconcile"]["RUB"]["checked"] is False)

print("\n== идентификаторы стабильны ==")
a = fn.normalize(build(usd=[purchase("02.01.2026", "1", "6.16", "22.08", "PLN")]))["operations"][0]["id"]
b = fn.normalize(build(usd=[purchase("02.01.2026", "1", "6.16", "22.08", "PLN")]))["operations"][0]["id"]
check("один вход — один id (для requestId записи)", a == b and a.startswith("ff-"))

# ---------------------------------------------------------------- интеграция (если личные выписки лежат рядом)
DOCS = ROOT.parent.parent / "docs" / "zenmoney"
files = sorted(DOCS.glob("текущ_*.pdf")) + sorted(DOCS.glob("депозит_*.pdf"))
if len(files) == 8:
    print("\n== интеграция на реальных выписках 2026 ==")
    sts = []
    for f in files:
        s = pf.parse_statement(str(f))
        s["file"] = f.name
        sts.append(s)
    check("все 8 выписок: строки, итоги, остаток сошлись", all(s["checks"]["ok"] for s in sts), [s["file"] for s in sts if not s["checks"]["ok"]])
    res = fn.normalize({"statements": sts})
    check("нет флагов кроме «банк не указал место»", {f["kind"] for f in res["flags"]} <= {"no-merchant"}, [f for f in res["flags"] if f["kind"] != "no-merchant"][:3])
    check("сверка остатка RUB/USD в пределах копеек", all(r["checked"] and abs(Decimal(r["residual"])) <= Decimal("0.05") for r in res["reconcile"].values()), res["reconcile"])
else:
    print("\n  (реальные выписки не лежат рядом — интеграция пропущена)")

print(f"\nИтого: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
