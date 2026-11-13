#!/usr/bin/env python3
"""Нормализация CSV-выписок Райффайзенбанка: строки → операции для ZenMoney (решение 2026-11-01).

Счета Райффайзена в ZenMoney синхронизируются; задача импорта — найти, что синхронизация пропустила
или что пользователь записал «корректировкой» вместо настоящей операции, и где нет контрагента. Поэтому
операции идут построчно, как их кладёт синхронизация: один счёт × строка выписки.

Вход: JSON из parse_raif_statement.py. Проверка парсера обязана сойтись; счёт файла должен быть узнан
(иначе — `account` из `--account FILE=NNNN`, со слов пользователя); два файла одного счёта с пересекающимися
датами — стоп (задвоение).

Правила классификации (по «Детали операции»):
  * «Рублевый перевод между счетами Клиента Со счета: *A На счет: *B» — перевод между своими счетами Райфа:
    списание → `transfer_out` kind=own (`counterparty_account` = B), зачисление → `topup` kind=own (= A).
  * «Телефон получателя N … Банк получателя X» (СБП по телефону): N — свой телефон → `transfer_out` kind=sbp
    с `recipient_bank` = X (в ZenMoney — перевод на счёт в банке X); чужой телефон → `expense` kind=p2p.
    Свой телефон — `--own-phone`, иначе тот, на который переводили в ≥2 разных банка (перевод самому себе).
  * «рублевый перевод,Заработная плата|Плановый аванс …» — `topup` kind=salary; «…ст. 79 НК РФ…» или
    отправитель — счёт казначейства 031… — `topup` kind=tax-refund; «…Перевод собственных средств…» —
    `topup` kind=own; прочий «рублевый перевод» — `topup` kind=incoming.
  * «Провайдер услуг <поставщик> …», «Оплата ЛС … ЖКУ …» — платёж услуги (`expense` kind=service).
  * «Комиссия …» — `expense` kind=fee, место = банк. «Возврат от <место>» — `refund`.
  * «<Имя> Со счета: *A» без счёта получателя — перевод человеку (`expense` kind=p2p, место не известно).
  * Остальное с номером карты — покупка по карте (`expense` kind=purchase, место = текст).
  * Пара «расход + возврат» одного номера документа и одной суммы — взаимно гасится (банк отменил операцию):
    в `internal`, в операции не идёт (так её не показывает и синхронизация).
  * Не распознанное → флаг `unknown-row`.

Выход: {operations, flags, internal, reconcile, bank_merchant}. `reconcile` по счёту — сумма операций за окно
выписки: сверяется с Δ остатка счёта ZenMoney за то же окно (остатков в выписке нет).
Только stdlib. Коды: 0 — ок, 2 — blocking.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal

BANK_MERCHANT = "Райффайзенбанк"

RE_OWN = re.compile(r"перевод между счетами Клиента Со счета:\s*\*(\d+)\s*На счет:\s*\*(\d+)", re.I)
RE_SBP = re.compile(r"^Телефон получателя\s+(\d{10,12}).*?Банк получателя\s+(.+?)\s*$")
RE_PROVIDER = re.compile(r"^Провайдер услуг\s+(.+?)(?:\s+Телефон\b.*)?$")
RE_RETURN = re.compile(r"^Возврат от\s+(.+)$")
RE_NAMED_OUT = re.compile(r"^(?P<name>[^,]+?)\s+Со счета:\s*\*\d+\s*$")


class Blocking(Exception):
    pass


def D(s) -> Decimal:
    return Decimal(str(s))


def iso(d: str) -> str:
    return datetime.strptime(d, "%d.%m.%Y").strftime("%Y-%m-%d")


def own_phones(rows: list[dict]) -> set:
    """Телефоны, на которые переводили по СБП в ≥2 разных банка — переводы самому себе."""
    banks = defaultdict(set)
    for r in rows:
        m = RE_SBP.match(r["purpose"])
        if m and r["amount"].startswith("-"):
            banks[m[1]].add(m[2])
    return {p for p, b in banks.items() if len(b) >= 2}


def classify(r: dict, phones: set) -> dict:
    p, out = r["purpose"], r["amount"].startswith("-")
    bank = {"name": BANK_MERCHANT, "raw": None, "country": None, "city": None}
    m = RE_OWN.search(p)
    if m:
        return ({"type": "transfer_out", "kind": "own", "counterparty_account": m[2], "text": "Перевод на свой счёт Райффайзенбанка"} if out
                else {"type": "topup", "kind": "own", "counterparty_account": m[1], "text": "Перевод со своего счёта Райффайзенбанка"})
    m = RE_SBP.match(p)
    if m and out:
        if m[1] in phones:
            return {"type": "transfer_out", "kind": "sbp", "recipient_bank": m[2], "counterparty_account": None, "text": f"СБП себе в {m[2]}"}
        return {"type": "expense", "kind": "p2p", "merchant": None, "recipient_bank": m[2], "text": "Перевод по СБП"}
    if p.lower().startswith("рублевый перевод") and not out:
        if re.search(r"Заработная плата|аванс", p, re.I):
            return {"type": "topup", "kind": "salary", "counterparty_account": None, "text": "Зарплата"}
        if re.search(r"ст\. ?79 НК РФ|отправителя-031\d+", p):
            return {"type": "topup", "kind": "tax-refund", "counterparty_account": None, "text": "Возврат налога"}
        if "Перевод собственных средств" in p:
            return {"type": "topup", "kind": "own", "counterparty_account": None, "text": "Перевод собственных средств из другого банка"}
        return {"type": "topup", "kind": "incoming", "counterparty_account": None, "text": "Входящий перевод"}
    m = RE_PROVIDER.match(p)
    if m and out:
        return {"type": "expense", "kind": "service", "merchant": {"name": m[1].strip(), "raw": p, "country": None, "city": None}}
    if p.startswith("Оплата ЛС") and out:
        return {"type": "expense", "kind": "service", "merchant": {"name": "ЖКУ" if "ЖКУ" in p else "Оплата лицевого счёта", "raw": p, "country": None, "city": None}}
    if p.startswith("Комиссия") and out:
        return {"type": "expense", "kind": "fee", "merchant": bank, "text": p}
    m = RE_RETURN.match(p)
    if m and not out:
        return {"type": "refund", "kind": "refund", "merchant": {"name": m[1].strip(), "raw": p, "country": None, "city": None}}
    m = RE_NAMED_OUT.match(p)
    if m and out and not r["card"]:
        return {"type": "expense", "kind": "p2p", "merchant": None, "text": "Перевод человеку"}
    if r["card"] and out:
        return {"type": "expense", "kind": "purchase", "merchant": {"name": p, "raw": p, "country": None, "city": None}}
    return {"type": None, "kind": "unknown"}


def neutralize(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Расход и зачисление одного номера документа на одну сумму — банк отменил операцию (internal)."""
    by: dict = defaultdict(lambda: {"in": [], "out": []})
    for r in rows:
        if r["doc"]:
            by[(r["doc"], D(r["amount"]).copy_abs())]["out" if r["amount"].startswith("-") else "in"].append(r)
    gone, internal = set(), []
    for (doc, amt), g in by.items():
        for o, i in zip(g["out"], g["in"]):
            gone.update((o["n"], i["n"]))
            internal.append({"date": iso(o["date"]), "amount": str(amt), "text": o["purpose"][:60], "rows": [o["n"], i["n"]]})
    return [r for r in rows if r["n"] not in gone], internal


def normalize(parsed: dict, accounts: dict | None = None, phones: set | None = None) -> dict:
    sts = parsed["statements"]
    if not sts:
        raise Blocking("нет ни одной выписки Райффайзенбанка")
    bad = [s.get("file", "?") for s in sts if not s["checks"]["ok"]]
    if bad:
        raise Blocking("проверка парсера не сошлась: " + ", ".join(bad))
    for s in sts:
        acc = (accounts or {}).get(s.get("file")) or s["meta"]["account"]
        if not acc:
            raise Blocking(f'{s.get("file")}: счёт по текстам не узнан — укажите его (--account FILE=последние цифры счёта)')
        s["meta"]["account"] = acc
    seen: dict = {}
    for s in sts:
        m = s["meta"]
        for o in seen.get(m["account"], []):
            if not (iso(m["period_to"]) < iso(o["period_from"]) or iso(m["period_from"]) > iso(o["period_to"])):
                raise Blocking(f'два файла по счёту *{m["account"]} с пересекающимися датами — задвоение')
        seen.setdefault(m["account"], []).append(m)
    phones = phones if phones is not None else own_phones([r for s in sts for r in s["rows"]])

    flags, ops, internal, reconcile = [], [], [], {}
    for st in sts:
        acct, ccy = st["meta"]["account"], st["meta"]["currency"]
        rows, inner = neutralize(st["rows"])
        for x in inner:
            x["account"] = acct
        internal += inner
        total = Decimal(0)
        for r in rows:
            c = classify(r, phones)
            total += D(r["amount"])
            if c["kind"] == "unknown":
                flags.append({"kind": "unknown-row", "account": acct, "date": iso(r["date"]), "detail": f'{r["amount"]} {ccy}: {r["purpose"][:90]}'})
                continue
            o = {"account": acct, "date": iso(r["date"]), "time": r["time"], "booking_date": iso(r["booking_date"]), "currency": ccy,
                 "amount": str(D(r["amount"]).copy_abs()), "refs": [r["n"]], "doc": r["doc"], "card": r["card"], "type": c["type"], "kind": c["kind"]}
            if r["currency_op"] != ccy:
                o["original"] = {"amount": str(D(r["amount_op"]).copy_abs()), "currency": r["currency_op"]}
            for k in ("merchant", "counterparty_account", "recipient_bank", "text"):
                if k in c:
                    o[k] = c[k]
            ops.append(o)
        mine = [o for o in ops if o["account"] == acct]
        s = sum((D(o["amount"]) * (1 if o["type"] in ("topup", "refund") else -1) for o in mine), Decimal(0))
        reconcile[acct] = {"currency": ccy, "period": f'{iso(st["meta"]["period_from"])}…{iso(st["meta"]["period_to"])}', "sum_operations": str(s),
                           "sum_rows": str(total), "residual": str(total - s),
                           "check_with": "Δ остатка счёта ZenMoney за окно (get_account_balances на день до начала и на конец) = sum_operations"}

    counts: Counter = Counter()
    for o in sorted(ops, key=lambda o: (o["account"], o["date"], o["time"], o["type"], o["refs"])):
        sig = json.dumps([o["account"], o["type"], o["date"], o["time"], o["amount"], o.get("doc"), (o.get("merchant") or {}).get("raw"), o.get("text")], sort_keys=True)
        counts[sig] += 1
        o["id"] = "rf-" + hashlib.sha1((sig + f"#{counts[sig]}").encode()).hexdigest()[:12]
    ops.sort(key=lambda o: (o["date"], o["time"], o["account"], o["id"]))
    return {"operations": ops, "flags": flags, "internal": internal, "reconcile": reconcile, "bank_merchant": BANK_MERCHANT, "own_phones": sorted(phones)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("parsed", help="JSON из parse_raif_statement.py")
    ap.add_argument("--account", action="append", default=[], help="FILE=NNNN — счёт файла, если по текстам не узнан")
    ap.add_argument("--own-phone", action="append", help="свой телефон для СБП (иначе — по переводам в ≥2 банка)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        with open(a.parsed, encoding="utf-8") as f:
            res = normalize(json.load(f), dict(x.split("=", 1) for x in a.account), set(a.own_phone) if a.own_phone else None)
    except Blocking as e:
        print(f"[blocking] {e}", file=sys.stderr)
        return 2
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
