#!/usr/bin/env python3
"""stmt_propose.py — план исправлений и сборка вызовов записи (Режим C) по результату stmt_compare.

Зачем (решение 2026-10-10): пользователь вносит операции из выписки руками, часть — «халтурой»
(одна сумма вместо шести покупок, пополнение в рублях вместо долларов). Правки идут только
через `upsert_transactions` по ловушкам write-mode.md: Т1 (правка метаданных — без сторон),
Т3 (тег ≠ основной категории), Т6 (переводам без категорий), Т8 (сумма > 0), Т10 (plugin),
≤10 операций в пакете, новый requestId на пакет создания.
"""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import stmt_propose as fp  # noqa: E402

ok = fail = 0


def check(name, cond, extra=None):
    global ok, fail
    if cond:
        ok += 1
        print(f"  [OK] {name}")
    else:
        fail += 1
        print(f"  [FAIL] {name} {extra if extra is not None else ''}")


CATS = {"data": [
    {"id": "c-toys", "name": "Игрушки", "parentId": "c-leis"}, {"id": "c-leis", "name": "Досуг", "parentId": None},
    {"id": "c-ai", "name": "ИИ", "parentId": "c-bills"}, {"id": "c-bills", "name": "Счета", "parentId": None},
    {"id": "c-other-b", "name": "Другое", "parentId": "c-bills"}, {"id": "c-other-l", "name": "Другое", "parentId": "c-leis"},
    {"id": "c-old", "name": "Старая", "parentId": None, "isArchived": True}]}
ACC = {"USD": "a-usd", "RUB": "a-rub", "KZT": "a-kzt"}
TRIPS = [{"name": "#Камбоджа'26", "tag_id": "t-cam", "from": "2026-02-05", "to": "2026-02-23"}]
PLACES = {"Nintendo": {"category": "Игрушки", "merchant": "Nintendo"}, "ANTHROPIC": {"category": "ИИ"}}


def b(id_, type_, date, amount=None, ccy="USD", place=None, original=None, **kw):
    r = {"id": id_, "type": type_, "date": date, "currency": ccy}
    if amount is not None:
        r["amount"] = amount
    if place:
        r["place"] = place
    if original:
        r["original"] = original
    r.update(kw)
    return r


def ID(name):
    h = hashlib.md5(name.encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def z(id_, date, out=None, inn=None, cat_id=None, tags=None, source=None):
    return {"id": ID(id_) if len(id_) < 12 else id_, "date": date, "kind": "transfer" if out and inn else ("expense" if out else "income"),
            "out": out, "in": inn, "category": None, "category_id": cat_id, "tag_ids": tags or [], "merchant_id": None, "source": source, "comment": None}


def cmp_(**kw):
    base = {k: [] for k in ("matched", "differs", "date_shift", "merged", "partial_transfer", "missing_in_zen", "missing_in_bank", "topup_currency")}
    base.update(kw)
    return base


def mkplan(c, ops=None):
    return fp.plan(c, {"operations": ops or []}, CATS, ACC, TRIPS, PLACES)


print("\n== план: создания ==")
pl = mkplan(cmp_(missing_in_zen=[
    b("b1", "expense", "2026-02-10", "5.00", place="Grab", original=None),
    b("b2", "expense", "2026-08-24", "21.31", place="Nintendo CB1"),
    b("b3", "expense", "2026-02-11", "131.56", place="QUEEN HOUSE", original={"amount": "2753190", "currency": "LAK"}),
    b("b4", "topup", "2026-04-16", "251.44")]))
it = {i["bank_id"]: i for i in pl["items"]}
check("место из словаря → категория подставлена, needs без category", it["b2"]["category_id"] == "c-toys" and "category" not in it["b2"]["needs"], it["b2"])
check("места нет в словаре → needs: category", "category" in it["b1"]["needs"])
check("тег поездки — по датам поездки, вне их — нет", it["b1"]["tag"]["id"] == "t-cam" and it["b2"]["tag"] is None)
check("покупка в другой валюте несёт исходную сумму; в валюте счёта — нет", it["b3"]["original"]["currency"] == "LAK" and it["b2"]["original"] is None)
check("пополнение требует счёт-источник и даёт окно поиска ±3 дня", it["b4"]["needs"] == ["from_account"] and it["b4"]["lookup"]["from"] == "2026-04-13" and it["b4"]["lookup"]["to"] == "2026-04-19", it["b4"])
N = {k: v["n"] for k, v in it.items()}
check("номера стабильны и идут по датам", [i["n"] for i in pl["items"]] == [1, 2, 3, 4] and [i["date"] for i in pl["items"]] == sorted(i["date"] for i in pl["items"]))
check("таблица плана строится", "| № |" in fp.table(pl) and "возврат" not in fp.table(pl))

print("\n== пакеты: создания ==")
DEC = {}
res = fp.payload(pl, {N["b2"]}, DEC, CATS, ACC)
tx = res["batches"][0]["transactions"][0]
check("покупка: счёт, сумма, категория, дата; без валютной пары, если валюта счёта", tx["expense"] == {"accountId": "a-usd", "amount": 21.31} and tx["categoryId"] == "c-toys" and tx["date"] == "2026-08-24", tx)
check("создание: requestId есть", res["batches"][0]["mode"] == "create" and len(res["batches"][0]["requestId"]) >= 32)
res = fp.payload(pl, {N["b3"]}, {str(N["b3"]): {"category": "Досуг/Другое"}}, CATS, ACC)
tx = res["batches"][0]["transactions"][0]
check("исходная сумма и валюта — парой (Т5); тег поездки добавлен", tx["expense"]["originalAmount"] == 2753190.0 and tx["expense"]["originalInstrument"] == "LAK" and tx["tagIds"] == ["t-cam"], tx)
check("категория «Досуг/Другое» однозначна, «Другое» без родителя — нет", res["problems"] == [] and fp.payload(pl, {N["b3"]}, {str(N["b3"]): {"category": "Другое"}}, CATS, ACC)["problems"])
check("без категории — в пакет не идёт, причина названа", fp.payload(pl, {N["b1"]}, DEC, CATS, ACC)["problems"] and not fp.payload(pl, {N["b1"]}, DEC, CATS, ACC)["batches"])
check("тег = основной категории (Т3) → стоп", fp.payload(pl, {N["b2"]}, {str(N["b2"]): {"tags": ["c-toys"]}}, CATS, ACC)["problems"])
check("пополнение без источника не пишется; с источником — перевод между счетами", fp.payload(pl, {N["b4"]}, DEC, CATS, ACC)["problems"]
      and fp.payload(pl, {N["b4"]}, {str(N["b4"]): {"from_account": "a-tin"}}, CATS, ACC)["batches"][0]["transactions"][0]["expense"]["accountId"] == "a-tin")
check("архивная категория не находится", fp.resolve_category("Старая", *fp.cat_index(CATS))[0] is None)

res = fp.payload(pl, {N["b1"]}, {str(N["b1"]): {"category": "Игрушки", "payee": "Khmer Grill"}}, CATS, ACC)
check("место из приложения банка → originalPayee (когда в выписке его нет)", res["batches"][0]["transactions"][0]["originalPayee"] == "Khmer Grill", res)

pl_m = fp.plan(cmp_(missing_in_zen=[b("bm", "expense", "2026-04-27", "3.27", place="APPLE.COM/BILL", original={"amount": "1490", "currency": "KZT"})]), {"operations": [{"id": "bm", "merchant": {"raw": "9\\IRL\\CORK\\APPLE.COM/BILL"}}]}, CATS, ACC, TRIPS, {"APPLE.COM": {"category": "Счета/Другое", "merchantId": "m1_apple"}})
txm = fp.payload(pl_m, {1}, {}, CATS, ACC)["batches"][0]["transactions"][0]
check("контрагент из словаря → merchantId + исходный текст банка в originalPayee", txm["merchantId"] == "m1_apple" and txm["originalPayee"].endswith("APPLE.COM/BILL"), txm)
txn = fp.payload(pl_m, {1}, {"1": {"no_payee": True}}, CATS, ACC)["batches"][0]["transactions"][0]
check("«без места» — originalPayee не передаём", "originalPayee" not in txn, txn)

# Т12: без merchantId сырая строка банка с кодом терминала в originalPayee не уходит (иначе ZenMoney заводит сырую точку)
pl_n = fp.plan(cmp_(missing_in_zen=[b("bh", "expense", "2026-10-20", "12.00", place="HOPERS BAR")]), {"operations": [{"id": "bh", "merchant": {"raw": "12345\\KAZ\\ASTANA\\HOPERS BAR"}}]}, CATS, ACC, TRIPS, {"HOPERS": {"category": "Игрушки", "merchant": "Hoper's Bar"}})
rn = fp.payload(pl_n, {1}, {}, CATS, ACC)
txh = rn["batches"][0]["transactions"][0]
check("без merchantId → читаемое место, не сырая строка банка", txh.get("originalPayee") == "HOPERS BAR" and "merchantId" not in txh, txh)
check("без merchantId → в without_merchant, подсказка имени из словаря", [(w["n"], w["suggest"], w["bank_text"]) for w in rn["without_merchant"]] == [(1, "Hoper's Bar", "12345\\KAZ\\ASTANA\\HOPERS BAR")], rn["without_merchant"])
txd = fp.payload(pl_n, {1}, {"1": {"merchantId": "m1_hop"}}, CATS, ACC)
check("merchantId из решения → исходный текст банка + точка, список без точки пуст", txd["batches"][0]["transactions"][0]["originalPayee"].startswith("12345") and txd["batches"][0]["transactions"][0]["merchantId"] == "m1_hop" and txd["without_merchant"] == [], txd)
check("с merchantId из словаря — список без точки пуст", fp.payload(pl_m, {1}, {}, CATS, ACC)["without_merchant"] == [])
check("в плане видно, что точку надо найти", "точка: найти «Hoper's Bar»" in fp.table(pl_n) and "точка: из словаря" in fp.table(pl_m))

txc = fp.payload(pl_m, {1}, {"1": {"comment": "Возврат"}}, CATS, ACC)["batches"][0]["transactions"][0]
check("комментарий из решения попадает в запись", txc["comment"] == "Возврат", txc)

print("\n== пакеты: изменения ==")
zo = lambda amt, acc="a-usd": {"ccy": "USD", "amount": str(amt), "account": acc}
pl2 = mkplan(cmp_(
    date_shift=[{"bank": b("b9", "expense", "2026-07-16", "100.00"), "zen": z("z1", "2026-09-25", out=zo(100)), "days": 71}],
    differs=[{"bank": b("b8", "expense", "2026-09-10", "9.62"), "zen": z("z2", "2026-09-10", out=zo(9.72))},
             {"bank": b("b7", "expense", "2026-09-10", "3.00"), "zen": z("z3", "2026-09-10", out=zo(3.05), source="plugin")}],
    topup_currency=[{"bank": b("b6", "topup", "2026-02-17", "125.47"), "zen": z("z4", "2026-02-17", out={"ccy": "RUB", "amount": "10000", "account": "a-tin"}, inn={"ccy": "RUB", "amount": "10000", "account": "a-rub"}), "implied_rate": "79.70"}],
    partial_transfer=[{"bank": {"id": "b5", "type": "transfer", "date": "2026-10-03", "from": {"currency": "RUB", "amount": "1748.00"}, "to": {"currency": "USD", "amount": "20.00"}},
                       "zen": z("z5", "2026-10-07", out={"ccy": "RUB", "amount": "2301.1", "account": "a-rub"}, inn={"ccy": "USD", "amount": "20", "account": "a-usd"}), "matched_side": "зачисление"}],
    merged=[{"zen": z("z6", "2026-08-28", out=zo(60.71), cat_id="c-toys", tags=["t-x"]), "bank": [b("m1", "expense", "2026-08-27", "25.58"), b("m2", "expense", "2026-08-28", "10.65"), b("m3", "expense", "2026-08-28", "2.12")], "diff": "0.00"}]))
res = fp.payload(pl2, {i["n"] for i in pl2["items"]}, {}, CATS, ACC)
upd = {u["id"]: u for bt in res["batches"] if bt["mode"] == "update" for u in bt["transactions"]}
check("правка даты — без сторон (Т1)", upd[ID("z1")] == {"id": ID("z1"), "date": "2026-07-16"}, upd.get(ID("z1")))
check("правка суммы — сторона с тем же счётом", upd[ID("z2")] == {"id": ID("z2"), "expense": {"accountId": "a-usd", "amount": 9.62}}, upd.get(ID("z2")))
check("операция банковского плагина — сумму не трогаем (Т10), причина названа", ID("z3") not in upd and any("плагин" in p for p in res["problems"]), res["problems"])
check("пополнение в чужой валюте: счёт зачисления → FF USD, обе стороны (Т1)", upd[ID("z4")]["income"] == {"accountId": "a-usd", "amount": 125.47} and upd[ID("z4")]["expense"] == {"accountId": "a-tin", "amount": 10000.0}, upd.get(ID("z4")))
check("перевод: обе суммы и дата банка", upd[ID("z5")]["expense"]["amount"] == 1748.0 and upd[ID("z5")]["income"]["amount"] == 20.0 and upd[ID("z5")]["date"] == "2026-10-03", upd.get(ID("z5")))
check("разделение: исходная получает первую часть", upd[ID("z6")]["expense"]["amount"] == 25.58)
cr = [t for bt in res["batches"] if bt["mode"] == "create" for t in bt["transactions"]]
check("разделение: остальные части создаются с категорией и тегами исходной", len(cr) == 2 and all(t["categoryId"] == "c-toys" and t["tagIds"] == ["t-x"] for t in cr), cr)
check("создания и изменения — разными вызовами", {bt["mode"] for bt in res["batches"]} == {"create", "update"})

print("\n== переделка вместо «создать + удалить» ==")
AI = {"id": "c-ai"}
zi = z("31feee18-762b-47cb-8368-7ea2d2002947", "2026-07-16", out=zo(20), cat_id="c-ai")
pl_r = fp.plan(cmp_(missing_in_zen=[b("a1", "expense", "2026-06-16", "100.00", place="ANTHROPIC* CLAUD"), b("a2", "expense", "2026-04-16", "100.00", place="CLAUDE.AI"), b("n1", "expense", "2026-10-04", "26.65", place="Nintendo")],
                      missing_in_bank=[dict({"id": zi["id"], "date": zi["date"], "kind": "expense", "out": zi["out"], "in": None, "category": "ИИ", "category_id": "c-ai", "tag_ids": [], "merchant_id": None, "source": None, "comment": None}, adjustment=False)]),
               {"operations": []}, CATS, ACC, TRIPS, {"ANTHROPIC": {"category": "ИИ"}, "CLAUDE": {"category": "ИИ"}, "Nintendo": {"category": "Игрушки"}})
kinds = [i["kind"] for i in pl_r["items"]]
check("запись без пары + непарная покупка банка той же категории → правка, а не создание", kinds.count("fix_rework") == 1 and kinds.count("create_expense") == 2, kinds)
rw = next(i for i in pl_r["items"] if i["kind"] == "fix_rework")
check("берём ближайшую по дате (06-16, а не 04-16)", rw["rework"]["to_date"] == "2026-06-16", rw["rework"])
rs_r = fp.payload(pl_r, {rw["n"]}, {}, CATS, ACC)
check("правка: дата и расход целиком (Т1), категория и тег не передаются", rs_r["batches"][0]["transactions"] == [{"id": "31feee18-762b-47cb-8368-7ea2d2002947", "date": "2026-06-16", "expense": {"accountId": "a-usd", "amount": 100.0}}], rs_r)
pl_d = mkplan(cmp_(missing_in_bank=[z("1992fb72-1c09-4cb1-9c29-bb8586604e94", "2026-09-13", out=zo(1.49), cat_id="c-taxi")]))
check("без пары в банке и без подходящей покупки — остаётся в списке на удаление", fp.delete_list(pl_d).count("1992fb72") == 1 and pl_d["items"][0]["kind"] == "review")

print("\n== решения по bank_id и превращение корректировки в перевод ==")
pl_c = mkplan(cmp_(missing_in_zen=[b("bk1", "topup", "2026-01-30", "320.10"), b("bk2", "expense", "2026-02-10", "5.00", place="Nintendo")]))
cv = {"bk1": {"convert": {"zen_id": ID("corr"), "from_account": "a-nak", "from_amount": "25000"}}, "bk2": {"category": "Игрушки"}}
rc = fp.payload(pl_c, {1, 2}, cv, CATS, ACC)
up = [t for bt in rc["batches"] if bt["mode"] == "update" for t in bt["transactions"]]
check("корректировка → перевод: обе стороны, доллары на FF USD, ничего не создаётся", up == [{"id": ID("corr"), "expense": {"accountId": "a-nak", "amount": 25000.0}, "income": {"accountId": "a-usd", "amount": 320.1}}], up)
check("решение найдено по bank_id, а не по номеру", any(bt["mode"] == "create" for bt in rc["batches"]) and rc["created"] == 1)

print("\n== полный ID ==")
sh = mkplan(cmp_(date_shift=[{"bank": b("b1", "expense", "2026-07-16", "100.00"), "zen": z("93d931bf-short", "2026-09-25", out=zo(100)), "days": 71}]))
rs = fp.payload(sh, {1}, {}, CATS, ACC)
check("укороченный ID не пишем — только полный из MCP", rs["problems"] and not rs["batches"], rs)
full = mkplan(cmp_(date_shift=[{"bank": b("b1", "expense", "2026-07-16", "100.00"), "zen": z("93d931bf-6c01-4e88-8295-540939759eb8", "2026-09-25", out=zo(100)), "days": 71}]))
check("полный UUID проходит", fp.payload(full, {1}, {}, CATS, ACC)["batches"][0]["transactions"] == [{"id": "93d931bf-6c01-4e88-8295-540939759eb8", "date": "2026-07-16"}])

print("\n== пакеты по 10 ==")
many = mkplan(cmp_(missing_in_zen=[b(f"n{i}", "expense", "2026-08-24", "1.00", place="Nintendo") for i in range(23)]))
rs = fp.payload(many, set(range(1, 24)), {}, CATS, ACC)
check("23 создания → 10+10+3, у каждого пакета свой requestId", [len(x["transactions"]) for x in rs["batches"]] == [10, 10, 3] and len({x["requestId"] for x in rs["batches"]}) == 3)

print("\n== «только показать» и разбор подтверждения ==")
rv = mkplan(cmp_(missing_in_bank=[z("zz", "2026-07-16", out=zo(20))]))
check("review ничего не пишет", fp.payload(rv, {1}, {}, CATS, ACC)["batches"] == [])
check("«1,3-5,8» разбирается", fp.parse_confirm("1,3-5,8") == {1, 3, 4, 5, 8})

print("\n== словарь мест ==")
with tempfile.TemporaryDirectory() as d:
    f = os.path.join(d, "places.json")
    fp.places_add(f, "GRAB", "Такси", "Grab")
    fp.places_add(f, "Apple", "Счета/Другое")
    data = json.load(open(f, encoding="utf-8"))
    check("запись и повторная запись не теряют прежнее", set(data) == {"GRAB", "Apple"} and data["GRAB"]["merchant"] == "Grab", data)
    check("временных файлов не остаётся", [n for n in os.listdir(d) if n.endswith(".tmp")] == [])
    pl = {"PRO": {"category": "ИИ"}, "MCD-": {"category": "Бистро"}}
    check("короткий ключ «PRO» — только слово целиком (не PROMENADE)", fp.place_rule("USA\\SAN FRANCISCO\\PRO", pl) == {"category": "ИИ"} and fp.place_rule("THA\\PROMENADE CAFE", pl) is None)
    check("ключ с дефисом по-прежнему подстрокой", fp.place_rule("1\\THA\\MCD-001 WANGBURA", pl) == {"category": "Бистро"})

print(f"\nИтого: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
