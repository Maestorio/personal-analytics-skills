#!/usr/bin/env python3
"""parse_tbank_statement.py + tbank_normalize.py + точки (stmt_propose.place_review) — справки Т-Банка (решение 2026-11-01).

Синтетические слова PDF строятся в тесте (личных данных нет). Интеграция на реальных справках из
docs/zenmoney/source/tbank/ и снимке ZenMoney tbank-regression/ идёт, только если файлы лежат рядом (в git их нет).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import parse_tbank_statement as pt  # noqa: E402
import stmt_accounts as sa  # noqa: E402
import stmt_compare as sc  # noqa: E402
import stmt_import as si  # noqa: E402
import stmt_propose as sp  # noqa: E402
import tbank_normalize as tn  # noqa: E402

ok = fail = 0


def check(name, cond, extra=None):
    global ok, fail
    if cond:
        ok += 1
        print(f"  [OK] {name}")
    else:
        fail += 1
        print(f"  [FAIL] {name} {extra if extra is not None else ''}")


# ---------------------------------------------------------------- синтетическая справка
X = {"op": 56, "book": 126, "amt_op": 199, "amt_acc": 294, "desc": 389, "card": 499}


def W(x, y, t):
    return (float(x), float(y), float(x) + 6 * len(t), float(y) + 11, t)


def header(y=315):
    return [W(56, y, "Дата"), W(126, y, "Дата"), W(199, y, "Сумма"), W(294, y, "Сумма"), W(389, y, "Описание"), W(499, y, "Номер")]


def row(y, date, time, amt, desc, card="0873", amt_op=None, sign_op="₽", bdate=None, btime=None):
    """Строка таблицы: дата/время в две строки, суммы со знаком «₽», описание с переносами."""
    ws = [W(56, y, date), W(56, y + 11, time), W(126, y, bdate or date), W(126, y + 11, btime or time)]
    for x, (a, s) in ((199, (amt_op or amt, sign_op)), (294, (amt, "₽"))):
        parts = a.split(" ")
        cx = x
        for p in parts:
            ws.append(W(cx, y, p))
            cx += 6 * len(p) + 2
        ws.append(W(cx, y + 1, s))
    for i, line in enumerate(desc):
        cx = 389
        for t in line.split():
            ws.append(W(cx, y + 11 * i, t))
            cx += 6 * len(t) + 2
    if card:
        ws.append(W(499, y, card))
    return ws


def footer(y):
    return [W(56, y, "Пополнения:"), W(120, y, "100,00"), W(56, y + 12, "Расходы:"), W(106, y + 40, "АО"), W(117, y + 40, "«ТБанк»")]


META_TEXT = """АКЦИОНЕРНОЕ ОБЩЕСТВО «ТБАНК»
Справка о движении средств
Номер договора: 5000000001
Номер лицевого счета: 40817810000000000001
Сумма доступного остатка на 01.11.2026: 1 234.50 ₽
Движение средств за период с 01.10.2026 по 01.11.2026
Дата и время        Дата                Сумма в валюте            Сумма операции           Описание
операции            списания            операции                  в валюте карты           операции
Пополнения:    10 100,00 ₽
Расходы:       1 873,85 ₽
"""

print("== шапка справки ==")
meta = pt.parse_meta(META_TEXT)
check("договор, счёт, валюта, период, доступный остаток, итоги", (meta["contract"], meta["account"], meta["currency"], meta["period_from"], meta["closing"], meta["closing_date"], meta["total_in"], meta["total_out"])
      == ("5000000001", "40817810000000000001", "RUB", "01.10.2026", "1234.50", "01.11.2026", "10100.00", "1873.85"), meta)
check("карта или договор — по подписи колонки", meta["product"] == "card")
check("ФИО и адрес в meta не попадают", not any("Иванов" in str(v) for v in meta.values()))
try:
    pt.parse_meta(META_TEXT.replace("АКЦИОНЕРНОЕ ОБЩЕСТВО «ТБАНК»", "Другой банк"))
    check("чужая справка — ошибка", False)
except pt.StatementError:
    check("чужая справка — ошибка", True)

print("\n== строки таблицы ==")
page1 = header() + row(342, "31.10.2026", "21:40", "-1 700.00", ["Оплата в OOO MARTSIPAN", "MOSCOW RUS"], card="2386") \
    + row(367, "30.10.2026", "16:49", "+100.00", ["Возврат средств по", "операции оплаты", "GRANDTRAIN g. Moskva", "RUS"]) \
    + row(417, "22.10.2026", "02:57", "-161.95", ["Оплата в YANDEX.GO", "MOSKVA RU"], amt_op="-1 990.00", sign_op="₸", btime="04:58") \
    + row(442, "22.10.2026", "04:58", "-11.90", ["Комиссия за операции", "покупок/снятия наличных в", "иностранной валюте"])
page2 = header(40) + row(67, "15.10.2026", "22:29", "+5.00", ["Кэшбэк за покупки у", "партнеров"], card="—") \
    + row(92, "15.10.2026", "22:31", "+3.00", ["Кэшбэк за обычные", "покупки"], card="—") \
    + row(117, "08.10.2026", "19:38", "+9 992.00", ["Перевод себе"]) + footer(160)
rows = pt.parse_rows([page1, page2])
check("7 строк с двух страниц, подвал не попал", len(rows) == 7, len(rows))
check("описание собрано из переносов", rows[1]["purpose"] == "Возврат средств по операции оплаты GRANDTRAIN g. Moskva RUS", rows[1]["purpose"])
check("сумма с пробелом тысяч склеена, знак сохранён", rows[0]["amount"] == "-1700.00" and rows[6]["amount"] == "+9992.00", (rows[0]["amount"], rows[6]["amount"]))
check("валюта операции ₸ → KZT, исходная сумма", rows[2]["currency_op"] == "KZT" and rows[2]["amount_op"] == "-1990.00", rows[2])
check("время операции и списания", rows[2]["time"] == "02:57" and rows[2]["booking_time"] == "04:58")
check("кэшбэк без карты: «—» → None", rows[4]["card"] is None)
meta2 = dict(meta, total_in="10100.00", total_out="1873.85")
chk = pt.check_statement(meta2, rows)
check("итоги «Пополнения/Расходы» сходятся", chk["ok"], chk)
bad = pt.check_statement(dict(meta2, total_out="1873.86"), rows)
check("копейка в итогах — ok=False (blocking)", not bad["ok"] and not bad["debit_vs_footer"])
r_bad = [dict(rows[0], amount_op="-1600.00")] + rows[1:]
check("одна валюта, разные суммы — ошибка строки", pt.check_statement(meta2, r_bad)["row_errors"])

print("\n== нормализация ==")
st = {"meta": dict(meta2, contract="5000000001"), "rows": rows, "checks": chk, "file": "a.pdf"}
own_rows = [{"n": 1, "date": "08.10.2026", "time": "19:37", "booking_date": "08.10.2026", "booking_time": "19:38", "amount_op": "-9992.00", "currency_op": "RUB",
             "amount": "-9992.00", "currency": "RUB", "purpose": "Внутренний перевод на договор 5000000001", "card": "0668"},
            {"n": 2, "date": "07.10.2026", "time": "17:01", "booking_date": "07.10.2026", "booking_time": "17:02", "amount_op": "-900.00", "currency_op": "RUB",
             "amount": "-900.00", "currency": "RUB", "purpose": "Внутренний перевод на договор 5999999999", "card": "0668"},
            {"n": 3, "date": "06.10.2026", "time": "10:00", "booking_date": "06.10.2026", "booking_time": "10:00", "amount_op": "-5.00", "currency_op": "RUB",
             "amount": "-5.00", "currency": "RUB", "purpose": "Непонятная операция", "card": "0668"},
            {"n": 4, "date": "05.10.2026", "time": "10:00", "booking_date": "05.10.2026", "booking_time": "10:00", "amount_op": "-5000.00", "currency_op": "RUB",
             "amount": "-5000.00", "currency": "RUB", "purpose": "Снятие наличных. Т-Банк, 6542 Москва Россия", "card": "0668"}]
st2 = {"meta": dict(meta2, contract="8000000002", total_in="0", total_out="9997.00"), "rows": own_rows, "checks": {"ok": True}, "file": "b.pdf"}
res = tn.normalize({"statements": [st, st2]})
ops = res["operations"]
by = lambda pred: [o for o in ops if pred(o)]
pur = by(lambda o: o["kind"] == "purchase" and o["merchant"]["name"] == "OOO MARTSIPAN")
check("покупка: место без города и страны", pur and pur[0]["merchant"]["city"] == "MOSCOW" and pur[0]["merchant"]["country"] == "RUS" and pur[0]["type"] == "expense")
ref = by(lambda o: o["type"] == "refund")
check("возврат: «g. Moskva» отрезан от места", ref and ref[0]["merchant"]["name"] == "GRANDTRAIN", ref and ref[0]["merchant"])
fx = by(lambda o: o["kind"] == "purchase" and o.get("original"))
fee = by(lambda o: o["kind"] == "fee-fx")
check("покупка в ₸: original 1990 KZT", fx and fx[0]["original"] == {"amount": "1990.00", "currency": "KZT"})
check("комиссия за валюту → её покупка по времени списания (fee_for)", fee and fee[0].get("fee_for") == fx[0]["id"] and fee[0]["merchant"]["name"] == tn.BANK_MERCHANT)
cb = by(lambda o: o["kind"] == "cashback")
check("кэшбэк одного дня — одной суммой (как синхронизация)", len(cb) == 1 and cb[0]["amount"] == "8.00" and len(cb[0]["refs"]) == 2, cb)
self_in = by(lambda o: o["kind"] == "own" and o["type"] == "topup")
check("«Перевод себе» связан с договором-источником при расхождении в минуту", self_in and self_in[0]["counterparty_contract"] == "8000000002", self_in)
check("перевод на свой договор — transfer_out own", by(lambda o: o["type"] == "transfer_out" and o["kind"] == "own" and o["counterparty_contract"] == "5000000001"))
check("перевод на чужой договор — расход p2p без места", by(lambda o: o["type"] == "expense" and o["kind"] == "p2p" and o["merchant"] is None))
check("снятие наличных — transfer_out cash", by(lambda o: o["type"] == "transfer_out" and o["kind"] == "cash"))
check("незнакомая строка — флаг, не операция", any(f["kind"] == "unknown-row" for f in res["flags"]) and not by(lambda o: "Непонятная" in str(o)))
check("сверка: сумма операций = Пополнения − Расходы (невязка 0)", res["reconcile"]["5000000001"]["residual"] == "0.00", res["reconcile"]["5000000001"])
check("id стабильны (tb- + хеш)", all(o["id"].startswith("tb-") for o in ops) and len({o["id"] for o in ops}) == len(ops))
check("повторный прогон — те же id", [o["id"] for o in tn.normalize({"statements": [st, st2]})["operations"]] == [o["id"] for o in ops])
try:
    tn.normalize({"statements": [st, dict(st, file="dup.pdf")]})
    check("две справки одного договора с пересечением — blocking", False)
except tn.Blocking:
    check("две справки одного договора с пересечением — blocking", True)
try:
    tn.normalize({"statements": [dict(st, checks={"ok": False})]})
    check("непрошедшая проверка парсера — blocking", False)
except tn.Blocking:
    check("непрошедшая проверка парсера — blocking", True)

print("\n== узнавание банка и счёта ==")
check("Т-Банк узнаётся по шапке", si.detect_bank(META_TEXT) == "tbank")
check("FF/BOG не путаются с Т-Банком", si.detect_bank("Фридом Банк Казахстан") == "ff")
LA = {"data": [
    {"id": "a-black", "name": "Tinkoff Black", "type": "card", "instrument": "RUB", "institution": {"name": "Т-Банк"}, "externalIds": ["0873", "1923"]},
    {"id": "a-joint", "name": "Совместный счет", "type": "card", "instrument": "RUB", "institution": {"name": "Т-Банк"}, "externalIds": ["2386", "4603"]},
    {"id": "a-sav", "name": "Накопительный счет", "type": "checking", "isSavings": True, "instrument": "RUB", "institution": {"name": "Т-Банк"}, "externalIds": ["6191"]},
    {"id": "a-other", "name": "Сбер", "type": "card", "instrument": "RUB", "institution": {"name": "Сбербанк"}, "externalIds": ["1923"]}]}
pat = si.BANKS["tbank"]["account_patterns"]
check("без договора три RUB-счёта Т-Банка — ambiguous", "RUB" in sa.resolve(LA, pat, ["RUB"])["ambiguous"])
check("по договору: последние 4 цифры в externalIds → карта", sa.resolve(LA, pat, ["RUB"], "5647911923")["accounts"] == {"RUB": "a-black"})
check("по договору: накопительный (isSavings) тоже выбирается", sa.resolve(LA, pat, ["RUB"], "8033126191")["accounts"] == {"RUB": "a-sav"})
check("чужой банк с теми же цифрами не берётся", sa.resolve(LA, pat, ["RUB"], "5647911923")["accounts"]["RUB"] != "a-other")

print("\n== сравнение и точки ==")
BM = "m-bank"
zen = {"data": [
    {"id": "z1", "date": "2026-10-31", "expense": {"accountId": "a1", "amount": 1700}, "categoryId": "c-food", "merchantId": "m-tokio", "originalPayee": "OOO MARTSIPAN", "source": "plugin"},
    {"id": "z2", "date": "2026-10-22", "expense": {"accountId": "a1", "amount": 161.95}, "categoryId": "c-taxi", "merchantId": BM, "originalPayee": "YANDEX.GO"},
    {"id": "z3", "date": "2026-10-22", "expense": {"accountId": "a1", "amount": 11.9}, "categoryId": "c-taxi", "merchantId": "m-yandex", "originalPayee": ""},
    {"id": "z4", "date": "2026-10-30", "income": {"accountId": "a1", "amount": 100}, "categoryId": "c-trav", "merchantId": "m-grand", "originalPayee": "GRANDTRAIN"},
    {"id": "z5", "date": "2026-10-15", "income": {"accountId": "a1", "amount": 8}, "categoryId": "c-cb"},
    {"id": "z6", "date": "2026-10-08", "expense": {"accountId": "a-sav", "amount": 9992}, "income": {"accountId": "a1", "amount": 9992}},
    {"id": "z7", "date": "2026-10-20", "expense": {"accountId": "a1", "amount": 50}, "categoryId": "c-taxi", "merchantId": "m-yandex", "originalPayee": "YANDEX.GO"}],
    "references": {"accounts": {"a1": {"instrument": "RUB"}, "a-sav": {"instrument": "RUB"}},
                   "categories": {"c-food": {"name": "Кафе"}, "c-taxi": {"name": "Такси", "parentId": "c-tr"}, "c-tr": {"name": "Транспорт"}, "c-trav": {"name": "Поездки"}, "c-cb": {"name": "Кэшбэк"}},
                   "merchants": {"m-tokio": {"name": "Токио Рамен"}, BM: {"name": "Т-Банк"}, "m-yandex": {"name": "Яндекс Go"}, "m-grand": {"name": "GRANDTRAIN"}}}}
extra = {"id": "tb-x", "type": "expense", "kind": "purchase", "account": "5000000001", "date": "2026-10-20", "currency": "RUB", "amount": "50.00", "merchant": {"name": "YANDEX.GO", "raw": "YANDEX.GO MOSKVA RU"}, "refs": [99]}
ops_cmp = dict(res, operations=res["operations"] + [extra])
c = sc.compare(ops_cmp, zen, {"RUB": "a1"}, "2026-10-01", "2026-11-01", with_transfer_out=True, bank_account="5000000001")
check("--bank-account: в сравнении только операции своего договора", c["summary"]["bank_ops"] == 7 and not any(r.get("account") == "8000000002" for r in c["missing_in_zen"]), c["summary"])
check("всё нашло пару", c["summary"]["missing_in_zen"] == 0 and c["summary"]["missing_in_bank"] == 0, c["summary"])
check("в паре видны точка, исходный текст и категория с родителем", any(r["zen"]["merchant"] == "Токио Рамен" and r["zen"]["original_payee"] == "OOO MARTSIPAN" for r in c["matched"])
      and any(r["zen"]["category_path"] == "Транспорт/Такси" for r in c["matched"]))
pl = sp.plan(c, ops_cmp, {"data": []}, {"RUB": "a1"}, places={"MARTSIPAN": {"category": "Кафе", "merchant": "Токио Рамен", "merchantId": "m-tokio"}})
fp = {i["zen_id"]: i for i in pl["items"] if i["kind"] == "fix_place"}
check("покупка с точкой банка — перепутана, точка места из соседних операций", fp.get("z2", {}).get("reason") == "swapped" and fp["z2"]["merchant_id"] == "m-yandex", fp.get("z2"))
check("комиссия с точкой места — перепутана, точка банка", fp.get("z3", {}).get("reason") == "swapped" and fp["z3"]["merchant_id"] == BM, fp.get("z3"))
check("сырая точка (латиница = текст банка) — пункт без предложения", fp.get("z4", {}).get("reason") == "raw" and fp["z4"]["needs"] == ["merchant"], fp.get("z4"))
check("точка подтверждена словарём — не трогаем", "z1" not in fp)
check("кэшбэк/переводы — не пункты точки", "z5" not in fp and "z6" not in fp)
sg = {x["key"]: x for x in pl["places_suggest"]}
check("в словарь: место с одной точкой и категорией", sg.get("YANDEX.GO", {}).get("merchantId") == "m-yandex" and sg["YANDEX.GO"]["category"] == "Транспорт/Такси", pl["places_suggest"])
check("в словарь не предлагаются уже покрытые и сырые", "OOO MARTSIPAN" not in sg and "GRANDTRAIN" not in sg)
z_ok = dict(zen, data=[dict(zen["data"][0], merchantId="m-mts", originalPayee="МТС")])
z_ok["references"] = dict(zen["references"], merchants={"m-mts": {"name": "МТС"}})
c2 = {"matched": [{"bank": {"id": "b", "type": "expense", "kind": "service", "date": "2026-10-31", "place": "MTS"}, "zen": sc._zbrief(sc.zen_ops(z_ok, {"RUB": "a1"}, None)[0])}]}
check("читаемое имя от синхронизации (кириллица) сырым не считается", sp.place_review(c2)[0] == [])
acc = sp.accepted_merchants({"items": [{"id": "m-grand|m1_x", "check": "C10"}, {"id": "m-grand", "check": "C9"}]})
z4 = next(r for r in c["matched"] if r["zen"]["id"] == "z4")
check("решение «оставить как есть» (accepted.json, C10) — сырой точку не считаем", sp.place_review({"matched": [dict(z4, zen=dict(z4["zen"], merchant_id="m1_x"))]}, accepted=acc)[0] == [])
c3 = {"matched": [{"bank": {"id": "b", "type": "expense", "kind": "purchase", "date": "2026-10-31", "place": "KAFE X"},
                   "zen": {"id": "11111111-1111-1111-1111-111111111111", "date": "2026-10-31", "kind": "expense", "out": {"ccy": "RUB", "amount": "1", "account": "a1"}, "in": None, "merchant_id": None, "merchant": None}}]}
it, _ = sp.place_review(c3, {"KAFE X": {"category": "Кафе", "merchantId": "m-kx", "merchant": "Кафе Икс"}})
check("нет точки → точка из словаря", it and it[0]["reason"] == "no_place" and it[0]["merchant_id"] == "m-kx", it)

print("\n== пакеты записи точек ==")
items = [{"n": 1, "kind": "fix_place", "zen_id": "11111111-1111-1111-1111-111111111111", "merchant_id": "m-kx", "needs": []},
         {"n": 2, "kind": "fix_place", "zen_id": "22222222-2222-2222-2222-222222222222", "merchant_id": None, "needs": ["merchant"]},
         {"n": 3, "kind": "fix_place", "zen_id": "33333333-3333-3333-3333-333333333333", "merchant_id": None, "needs": ["merchant"]},
         {"n": 4, "kind": "fix_place", "zen_id": "44444444-4444-4444-4444-444444444444", "merchant_id": None, "needs": ["merchant"]}]
out = sp.payload({"items": items}, {1, 2, 3, 4}, {"33333333-3333-3333-3333-333333333333": {"keep": True}, "44444444-4444-4444-4444-444444444444": {"merchantId": "m-new"}}, {"data": []}, {})
upd = [t for b in out["batches"] for t in b["transactions"]]
check("правка точки — только id + merchantId", {"id": "11111111-1111-1111-1111-111111111111", "merchantId": "m-kx"} in upd and all(set(t) == {"id", "merchantId"} for t in upd), upd)
check("решение пользователя merchantId — в пакет", {"id": "44444444-4444-4444-4444-444444444444", "merchantId": "m-new"} in upd)
check("keep — не пишется; без точки — problem, не null", len(upd) == 2 and any("№2" in p for p in out["problems"]) and not any(t.get("merchantId") is None for t in upd), out)

print("\n== интеграция на реальных справках (если лежат рядом) ==")
src = ROOT.parent.parent / "docs" / "zenmoney" / "source" / "tbank"
real = sorted(src.glob("*.pdf")) if src.exists() else []
if real:
    r = si.run([str(p) for p in real])
    s = r["banks"].get("tbank")
    check("все реальные справки разобраны, итоги сошлись", s is not None and all(f["checks_ok"] for f in r["files"]) and not r["unrecognized"], r["files"])
    check("реальные: незнакомых строк и непривязанных комиссий нет", s and s["flags"] == [], s and s["flags"])
    check("реальные: невязка 0 по всем договорам", s and all(v["residual"] == "0.00" for v in s["reconcile"].values()), s and s["reconcile"])
    snap = src.parent / "tbank-regression"
    if (snap / "accounts.json").exists() and s is not None:
        meta = json.loads((snap / "accounts.json").read_text(encoding="utf-8"))
        zen_real = sc.merge_pages([json.loads((snap / n).read_text(encoding="utf-8")) for n in sorted(p.name for p in snap.glob("zen-page*.json"))])
        swapped = 0
        for contract, acc in meta["contracts"].items():
            cr = sc.compare(s, zen_real, {"RUB": acc}, *meta["window"], with_transfer_out=True, bank_account=contract)
            got = {k: cr["summary"][k] for k in meta["expected"][contract]}
            check(f"реальные …{contract[-4:]}: сравнение со снимком ZenMoney (регрессия)", got == meta["expected"][contract], (got, meta["expected"][contract]))
            swapped += sum(1 for i in sp.place_review(cr, None, s["bank_merchant"])[0] if i["reason"] == "swapped")
        check("реальные: перепутанные точки комиссия ↔ покупка найдены", swapped == meta["expected_place_items"]["swapped"], swapped)
    else:
        print("  (нет снимка ZenMoney tbank-regression — пропуск)")
else:
    print("  (нет файлов — пропуск)")

print(f"\nИтого: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
