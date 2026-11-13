#!/usr/bin/env python3
"""parse_raif_statement.py + raif_normalize.py + «расход ↔ перевод» и «группа даёт 0» — выписки Райффайзенбанка (решение 2026-11-01).

Синтетический CSV строится в тесте (личных данных нет). Интеграция на реальных выписках из
docs/zenmoney/source/raif/ и снимке ZenMoney raif-regression/ идёт, только если файлы лежат рядом (в git их нет).
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import parse_raif_statement as pr  # noqa: E402
import raif_normalize as rn  # noqa: E402
import stmt_accounts as sa  # noqa: E402
import stmt_compare as sc  # noqa: E402
import stmt_import as si  # noqa: E402
import stmt_propose as sp  # noqa: E402

ok = fail = 0


def check(name, cond, extra=None):
    global ok, fail
    if cond:
        ok += 1
        print(f"  [OK] {name}")
    else:
        fail += 1
        print(f"  [FAIL] {name} {extra if extra is not None else ''}")


HEAD = ";".join(pr.HEADER)
PH = "79000000001"


def line(dt, booked, doc, amt, text, card=""):
    inc, out = (amt, "") if not amt.startswith("-") else ("", amt[1:])
    return ";".join(f'"{x}"' for x in (dt, booked, doc, inc, out, "RUB", inc, out, "RUB", " " + text, card))


ROWS = [
    line("29.10.2026 11:10", "29.10.2026", "RC1", "240 739,55", "рублевый перевод,Заработная плата за Октябрь 2026 р/с 40817810800000001234 Тест,номер счета отправителя-40702810700000000001 На счет: 40817810******1234"),
    line("26.10.2026 18:55", "26.10.2026", "ZP1", "-62 467,80", f"Телефон получателя {PH} Сообщение  Идентификатор операции СБП A1 Банк получателя Т-Банк"),
    line("26.10.2026 18:56", "26.10.2026", "ZP2", "-1 000,00", f"Телефон получателя {PH} Сообщение  Идентификатор операции СБП A2 Банк получателя Цифра банк"),
    line("20.10.2026 10:00", "20.10.2026", "ZP3", "-500,00", "Телефон получателя 79000000099 Сообщение  Идентификатор операции СБП A3 Банк получателя Сбербанк"),
    line("03.07.2026 09:02", "03.07.2026", "ZR9", "-1 000,00", "Золотая корона", "*3512"),
    line("03.07.2026 09:03", "03.07.2026", "ZR9", "1 000,00", "Возврат от Золотая корона", "*3512"),
    line("03.07.2026 09:11", "06.07.2026", "ZP4", "-8,26", "Комиссия за перевод на KORONA/UNISTREAM/ECT с дебетовой карты", "*3512"),
    line("03.07.2026 09:11", "06.07.2026", "ZP5", "-1 651,17", "Золотая корона", "*3512"),
    line("30.07.2026 13:11", "30.07.2026", "ZP6", "-328 116,12", "Рублевый перевод между счетами Клиента Со счета: *1234 На счет: *5678"),
    line("19.03.2026 10:20", "19.03.2026", "", "-13 736,50", "Алексей Т Со счета: *1234"),
    line("23.04.2026 15:05", "23.04.2026", "ZP7", "14 306,00", "рублевый перевод,18201061201010000610;ст. 79 НК РФ заявление N1 от 18.04.2026,номер счета отправителя-03100643000000018500 На счет: 40817810******"),
    line("24.01.2026 00:03", "24.01.2026", "ZP8", "-5 000,00", "Провайдер услуг МТС и МГТС Телефон +7 900 000-00-01"),
    line("07.03.2026 15:21", "09.03.2026", "RC2", "-932,43", "Оплата ЛС //№1//ИПД //№2// ЖКУ <ИПД2> Со счета: *1234 На счет: *0027199"),
    line("01.03.2026 10:00", "01.03.2026", "ZP9", "-10,00", "Что-то новое"),
]
TEXT = "﻿" + HEAD + "\r\n" + "\r\n".join(ROWS) + "\r\n"

print("== разбор CSV ==")
rows, chk = pr.parse_text(TEXT.lstrip("﻿"))
check("14 строк, построчные проверки чистые", len(rows) == 14 and chk["row_errors"] == [], chk)
check("сумма с пробелом и запятой → Decimal, знак расхода", rows[1]["amount"] == "-62467.80" and rows[0]["amount"] == "240739.55")
check("дата и время операции, дата банка, карта без «*»", (rows[6]["date"], rows[6]["time"], rows[6]["booking_date"], rows[6]["card"]) == ("03.07.2026", "09:11", "06.07.2026", "3512"))
hint, votes = pr.account_hint(rows)
check("счёт файла по текстам: «Со счета» у списаний, «На счет» у зачислений, «р/с» у зарплаты", hint == "1234", votes)
bad_two = line("01.01.2026 10:00", "01.01.2026", "X", "-1,00", "x").replace('"";"1,00"', '"1,00";"1,00"', 1)
_, c2 = pr.parse_text(HEAD + "\n" + bad_two)
check("две суммы в одной строке — ошибка строки", c2["row_errors"])
try:
    pr.parse_text("Дата;Сумма\n1;2")
    check("чужая шапка — ошибка", False)
except pr.StatementError:
    check("чужая шапка — ошибка", True)
tmp = Path(tempfile.mkdtemp())
f1 = tmp / "Выписка.csv"
f1.write_bytes(TEXT.encode("utf-8"))
f_cp = tmp / "cp.csv"
f_cp.write_bytes((HEAD + "\r\n" + ROWS[1] + "\r\n").encode("cp1251"))
st = pr.parse_statement(str(f1))
check("parse_statement: счёт, валюта, период по датам, ok", (st["meta"]["account"], st["meta"]["currency"], st["meta"]["period_from"], st["meta"]["period_to"], st["checks"]["ok"])
      == ("1234", "RUB", "24.01.2026", "29.10.2026", True), st["meta"])
check("cp1251 тоже читается", pr.parse_statement(str(f_cp))["checks"]["ok"])

print("\n== нормализация ==")
st["file"] = "Выписка.csv"
res = rn.normalize({"statements": [st]})
ops = res["operations"]
k = lambda t, kind: [o for o in ops if o["type"] == t and o["kind"] == kind]
check("свой телефон — тот, на который переводили в ≥2 банка", res["own_phones"] == [PH], res["own_phones"])
check("СБП себе → transfer_out sbp с банком получателя", len(k("transfer_out", "sbp")) == 2 and {o["recipient_bank"] for o in k("transfer_out", "sbp")} == {"Т-Банк", "Цифра банк"})
check("СБП на чужой телефон → расход p2p без места", len(k("expense", "p2p")) == 2 and all(o["merchant"] is None for o in k("expense", "p2p")))
check("перевод между своими счетами → transfer_out own, счёт-получатель", k("transfer_out", "own") and k("transfer_out", "own")[0]["counterparty_account"] == "5678")
check("зарплата и возврат налога — пополнения", k("topup", "salary") and k("topup", "tax-refund"))
check("провайдер услуг и ЖКУ — платежи услуг с местом", {o["merchant"]["name"] for o in k("expense", "service")} == {"МТС и МГТС", "ЖКУ"})
check("комиссия — расход с местом банка", k("expense", "fee") and k("expense", "fee")[0]["merchant"]["name"] == rn.BANK_MERCHANT)
check("расход + возврат одного документа и суммы — в internal, не операции", len(res["internal"]) == 1 and res["internal"][0]["amount"] == "1000.00"
      and len(k("expense", "purchase")) == 1 and k("expense", "purchase")[0]["amount"] == "1651.17", res["internal"])
check("незнакомая строка — флаг", any(f["kind"] == "unknown-row" for f in res["flags"]))
rec = res["reconcile"]["1234"]
check("сверка: sum_rows − sum_operations = незнакомая строка (−10)", rec["residual"] == "-10.00", rec)
check("id стабильны (rf- + хеш)", all(o["id"].startswith("rf-") for o in ops) and len({o["id"] for o in ops}) == len(ops)
      and [o["id"] for o in rn.normalize({"statements": [pr.parse_statement(str(f1)) | {"file": "Выписка.csv"}]})["operations"]] == [o["id"] for o in ops])
st_noacc = {"meta": dict(st["meta"], account=None), "rows": st["rows"], "checks": st["checks"], "file": "x.csv"}
try:
    rn.normalize({"statements": [st_noacc]})
    check("счёт не узнан — blocking", False)
except rn.Blocking:
    check("счёт не узнан — blocking", True)
check("счёт со слов пользователя (--account FILE=NNNN)", rn.normalize({"statements": [st_noacc]}, {"x.csv": "9999"})["operations"][0]["account"] == "9999")
try:
    rn.normalize({"statements": [st, dict(st, file="dup.csv")]})
    check("два файла одного счёта с пересечением — blocking", False)
except rn.Blocking:
    check("два файла одного счёта с пересечением — blocking", True)

print("\n== узнавание банка и счёта ==")
check("Райффайзен узнаётся по шапке CSV", si.detect_bank(si._read_head(str(f1))) == "raif")
check("Т-Банк/FF/BOG не узнаются как Райф", si.detect_bank("АО «ТБанк»") == "tbank")
LA = {"data": [{"id": "a-cb", "name": "Cashback Card", "type": "card", "instrument": "RUB", "institution": {"name": "Райффайзенбанк"}, "externalIds": ["9612", "1234", "3512"]},
               {"id": "a-mir", "name": "RUR MIR Standard", "type": "card", "instrument": "RUB", "institution": {"name": "Райффайзенбанк"}, "externalIds": ["5160"]},
               {"id": "a-sav", "name": "Накопительный счёт", "type": "checking", "isSavings": True, "instrument": "RUB", "institution": {"name": "Райффайзенбанк"}, "externalIds": ["5678"]}]}
pat = si.BANKS["raif"]["account_patterns"]
check("счёт ZenMoney по последним 4 цифрам счёта из выписки", sa.resolve(LA, pat, ["RUB"], "1234")["accounts"] == {"RUB": "a-cb"} and sa.resolve(LA, pat, ["RUB"], "5678")["accounts"] == {"RUB": "a-sav"})

print("\n== сравнение: расход ↔ перевод, группа даёт 0 ==")
bank = {"operations": [
    {"id": "rf-1", "type": "transfer_out", "kind": "sbp", "account": "1234", "date": "2026-03-21", "currency": "RUB", "amount": "5877.00", "recipient_bank": "Озон Банк (Ozon)", "refs": [1]},
    {"id": "rf-2", "type": "transfer_out", "kind": "sbp", "account": "1234", "date": "2026-04-01", "currency": "RUB", "amount": "700.00", "recipient_bank": "Т-Банк", "refs": [2]},
    {"id": "rf-3", "type": "topup", "kind": "salary", "account": "1234", "date": "2026-04-02", "currency": "RUB", "amount": "100.00", "refs": [3]}]}
Z = "d16838fe-03a3-45d2-a87d-b5b31e25885f"
zen = {"data": [
    {"id": "11111111-1111-1111-1111-111111111111", "date": "2026-03-21", "expense": {"accountId": "a-cb", "amount": 5877}, "categoryId": "c-oth", "source": "plugin"},
    {"id": "22222222-2222-2222-2222-222222222222", "date": "2026-04-02", "income": {"accountId": "a-cb", "amount": 100}, "categoryId": "c-sal"},
    {"id": "33333333-3333-3333-3333-333333333333", "date": "2026-06-22", "income": {"accountId": "a-cb", "amount": 12496}, "categoryId": "c-adj"},
    {"id": "44444444-4444-4444-4444-444444444444", "date": "2026-07-14", "expense": {"accountId": "a-cb", "amount": 3124}, "categoryId": "c-oth"},
    {"id": "55555555-5555-5555-5555-555555555555", "date": "2026-10-06", "expense": {"accountId": "a-cb", "amount": 9372}, "categoryId": "c-adj"},
    {"id": "66666666-6666-6666-6666-666666666666", "date": "2026-10-07", "expense": {"accountId": "a-cb", "amount": 1}, "categoryId": "c-oth"}],
    "references": {"accounts": {"a-cb": {"instrument": "RUB"}}, "categories": {"c-oth": {"name": "Другое"}, "c-sal": {"name": "Зарплата"}, "c-adj": {"name": "Корректировка"}}}}
c = sc.compare(bank, zen, {"RUB": "a-cb"}, "2026-01-01", "2026-11-01", "c-adj", with_transfer_out=True, bank_account="1234")
check("банк: перевод себе, ZenMoney: расход → expense_vs_transfer", len(c["expense_vs_transfer"]) == 1 and c["expense_vs_transfer"][0]["bank"]["recipient_bank"] == "Озон Банк (Ozon)", c["summary"])
check("перевода нет в ZenMoney — missing_in_zen", [b["id"] for b in c["missing_in_zen"]] == ["rf-2"])
pl = sp.plan(c, bank, {"data": []}, {"RUB": "a-cb"})
kinds = {i["kind"] for i in pl["items"]}
check("план: «в перевод» (нужен счёт-получатель) и «создать перевод»", {"fix_to_transfer", "create_transfer_out"} <= kinds, kinds)
nz = [i for i in pl["items"] if i.get("net_zero")]
check("записи без пары, взаимно гасящиеся (+12496 −3124 −9372), отмечены «группа даёт 0»; лишняя −1 — нет",
      sorted(i["zen_id"][0] for i in nz) == ["3", "4", "5"], [(i["zen_id"][0], i.get("net_zero")) for i in pl["items"] if i["kind"] == "review"])
tbl = sp.table(pl)
check("в таблице видно банк получателя и пометку plugin", "Озон Банк" in tbl and "plugin" in tbl and "дают 0" in tbl)
n_fix = next(i["n"] for i in pl["items"] if i["kind"] == "fix_to_transfer")
n_new = next(i["n"] for i in pl["items"] if i["kind"] == "create_transfer_out")
out = sp.payload(pl, {n_fix, n_new}, {"11111111-1111-1111-1111-111111111111": {"to_account": "a-ozon"}, "rf-2": {"to_account": "a-tb"}}, {"data": []}, {"RUB": "a-cb"})
check("plugin без отдельного согласия — не пишется (Т10/Т14)", any("plugin_ok" in p for p in out["problems"]) and out["updated"] == 0, out["problems"])
check("создание перевода: обе стороны", out["created"] == 1 and out["batches"][0]["transactions"][0] == {"date": "2026-04-01", "expense": {"accountId": "a-cb", "amount": 700.0}, "income": {"accountId": "a-tb", "amount": 700.0}})
out2 = sp.payload(pl, {n_fix}, {"11111111-1111-1111-1111-111111111111": {"to_account": "a-ozon", "plugin_ok": True}}, {"data": []}, {"RUB": "a-cb"})
upd = out2["batches"][0]["transactions"][0]
check("с согласием: та же запись → перевод (обе стороны, без даты и категории — Т14)", upd == {"id": "11111111-1111-1111-1111-111111111111", "expense": {"accountId": "a-cb", "amount": 5877.0}, "income": {"accountId": "a-ozon", "amount": 5877.0}}, upd)

print("\n== интеграция на реальных выписках (если лежат рядом) ==")
src = ROOT.parent.parent / "docs" / "zenmoney" / "source" / "raif"
real = sorted(src.glob("*.csv")) if src.exists() else []
if real:
    r = si.run([str(p) for p in real])
    s = r["banks"].get("raif")
    check("все реальные выписки разобраны, счета узнаны", s is not None and all(f["checks_ok"] for f in r["files"]) and not r["unrecognized"] and not r["missing"], (r["files"], r["missing"]))
    check("реальные: незнакомых строк нет, невязка 0", s and s["flags"] == [] and all(v["residual"] == "0.00" for v in s["reconcile"].values()), s and (s["flags"], s["reconcile"]))
    snap = src.parent / "raif-regression"
    if (snap / "accounts.json").exists() and s is not None:
        meta = json.loads((snap / "accounts.json").read_text(encoding="utf-8"))
        zen_real = sc.merge_pages([json.loads((snap / n).read_text(encoding="utf-8")) for n in sorted(p.name for p in snap.glob("zen-page*.json"))])
        for acc, (zid, f, t) in meta["accounts"].items():
            cr = sc.compare(s, zen_real, {"RUB": zid}, f, t, meta["adjust_category_id"], with_transfer_out=True, bank_account=acc)
            got = {k: cr["summary"][k] for k in meta["expected"][acc]}
            check(f"реальные *{acc[-4:]}: сравнение со снимком ZenMoney (регрессия)", got == meta["expected"][acc], (got, meta["expected"][acc]))
            if acc in meta.get("expected_net_zero", {}):
                nz = sum(1 for i in sp.plan(cr, s, {"data": []}, {"RUB": zid})["items"] if i.get("net_zero"))
                check(f"реальные *{acc[-4:]}: взаимно гасящиеся записи без пары найдены", nz == meta["expected_net_zero"][acc], nz)
    else:
        print("  (нет снимка ZenMoney raif-regression — пропуск)")
else:
    print("  (нет файлов — пропуск)")

print(f"\nИтого: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
