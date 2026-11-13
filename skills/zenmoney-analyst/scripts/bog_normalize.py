#!/usr/bin/env python3
"""Нормализация выписок BOG: строки → операции для ZenMoney (решение 2026-10-11).

BOG — мультивалютный счёт (GEL/USD/EUR/GBP в одном IBAN). В отличие от FF, цепочки
«конвертация → покупка» НЕ склеиваются: в ZenMoney счета BOG подключены банковской
синхронизацией, и там операция лежит так, как её показывает банк — по валюте списания.
Поэтому выход — построчный и однозначный: один счёт (IBAN) × валюта списания.

Вход: JSON из parse_bog_statement.py. Нужна хотя бы одна выписка; проверка парсера обязана
сойтись. Две выписки одного IBAN с пересекающимся периодом — стоп (задвоение).

Правила классификации (по тексту банка):
  * «Payment|Credit Funds … Merchant: …; MCC; Date; Card No» — покупка/возврат по карте. Дата
    операции — дата транзакции, дата проводки — `booking_date`. Если валюта покупки не равна
    валюте списания, исходная сумма — в `original`. Комиссии конвертации внутри суммы списания.
  * «Automatic conversion, rate: R» — ноги обмена. Пара — внутри даты и курса: большая сумма ≈
    меньшая × R (GEL за USD/EUR; кросс EUR↔USD — USD за EUR; допуск — округление курса). Пара → `transfer` с обеими суммами. Не нашлась — флаг.
  * Комиссия в GEL, оплаченная из другой валюты (Payment GEL / Income GEL / Payment USD, одна дата и текст) —
    как в синхронизации ZenMoney: `expense` kind=fee в GEL + `transfer` USD→GEL (how=fee-conversion).
  * Пара «Payment» + «Income» одной даты, валюты, суммы и одного текста — взаимно гасится (так
    банк возвращает комиссию за обслуживание и ведёт «размещение на депозит»): в `internal`,
    в операции не идёт. Остаток без пары — комиссия (`expense`, kind=fee).
  * «Outgoing Transfer» / «Incoming Transfer» / «Placing funds on deposit» без пары — перевод
    на другой счёт (`transfer_out`) или зачисление (`topup`); счёт контрагента — в `counterparty_account`.
  * «Money transfer received», «Cash deposit», «გაპროტესტებული თანხა» (chargeback) — `topup`
    с текстом. Платёж услуги («payment service, Magticom») — `expense`.
  * Не распознанное → флаг `unknown-row`, ничего не додумывается.

Выход: {operations, flags, internal, reconcile}. Сверка по IBAN × валюте: Δ остатка банка =
сумма операций + внутренние пары (должно быть 0.00). Только stdlib. Коды: 0 — ок, 2 — blocking.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")

RE_HEAD = re.compile(r"^(?P<word>Payment|Income|Credit Funds|Incoming Transfer|Outgoing Transfer)\s*-\s*Amount:?\s*(?P<ccy>[A-Z]{3})(?P<amt>[\d,]+(?:\.\d+)?)\s*;?\s*(?P<rest>.*)$")
RE_CARD = re.compile(r"^Merchant:\s*(?P<merchant>.+?);\s*MCC:\s*(?P<mcc>\d+);\s*Date:\s*(?P<date>\d\d/\d\d/\d{4})(?:\s+(?P<time>\d\d:\d\d))?;\s*Card No:\s*\*+(?P<card>\d{4})")
RE_CONV = re.compile(r"Automatic conversion, rate:\s*([\d.]+)")
RE_ACCOUNT = re.compile(r"Account:\s*(GE\w+?)(?:[A-Z]{3})?;")
RE_SYSTEM = re.compile(r"System:\s*([^;]+)")
RE_SERVICE = re.compile(r"payment service,\s*([^,]+)")


class Blocking(Exception):
    pass


def D(s) -> Decimal:
    return Decimal(str(s).replace(",", "").strip())


def q(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def iso(d: str, fmt: str = "%d.%m.%Y") -> str:
    return datetime.strptime(d, fmt).strftime("%Y-%m-%d")


def parse_row(r: dict) -> dict:
    """Строка выписки → {kind, ccy, amt (>0), side, ...}. Без догадок: чего нет в тексте — None."""
    amt = D(r["credit"] or r["debit"])
    side = "in" if r["credit"] else "out"
    base = {"n": r["n"], "date": r["date"], "ccy": r["currency"], "amt": amt, "side": side, "purpose": r["purpose"]}
    m = RE_HEAD.match(r["purpose"])
    if not m:
        return {**base, "kind": "unknown"}
    rest, word = m["rest"].strip(), m["word"]
    base["text_ccy"], base["text_amt"], base["rest"] = m["ccy"], D(m["amt"]), rest
    cm = RE_CARD.match(rest)
    if cm:
        mer = cm["merchant"].strip()
        name, _, country = mer.rpartition(", ")
        return {**base, "kind": "refund" if word == "Credit Funds" else "purchase", "merchant": {"name": (name or mer).strip(), "country": country.strip() if name else None, "mcc": cm["mcc"], "card": cm["card"]},
                "tx_date": iso(cm["date"], "%d/%m/%Y")}
    conv = RE_CONV.search(rest)
    if conv:
        return {**base, "kind": "convleg", "rate": D(conv[1])}
    if word in ("Outgoing Transfer", "Incoming Transfer"):
        acc = RE_ACCOUNT.search(rest)
        return {**base, "kind": "transfer_out" if word == "Outgoing Transfer" else "topup", "counterparty_account": acc[1] if acc else None, "text": "Перевод на другой счёт" if word == "Outgoing Transfer" else "Входящий перевод"}
    if "Placing funds on deposit" in rest:
        return {**base, "kind": "transfer_out" if side == "out" else "topup", "counterparty_account": None, "text": "Размещение средств на депозите"}
    if "Maintenance Fee" in rest or "Card Protection Service Fee" in rest:
        return {**base, "kind": "fee", "text": "Комиссия банка: " + ("обслуживание" if "Maintenance" in rest else "защита карты")}
    sv = RE_SERVICE.search(rest)
    if sv and side == "out":
        return {**base, "kind": "service", "merchant": {"name": sv[1].strip(), "country": "Georgia", "mcc": None, "card": None}}
    sysm = RE_SYSTEM.search(rest)
    if "Money transfer received" in rest and sysm and side == "in":
        return {**base, "kind": "topup", "counterparty_account": None, "text": "Денежный перевод: " + sysm[1].strip()}
    if "Cash deposit" in rest and side == "in":
        return {**base, "kind": "topup", "counterparty_account": None, "text": "Внесение наличных"}
    if "გაპროტესტებული" in rest and side == "in":
        return {**base, "kind": "topup", "counterparty_account": None, "text": "Возврат по оспоренной операции (chargeback)"}
    return {**base, "kind": "unknown"}


def fee_conversions(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Комиссия, списанная в GEL и оплаченная из другой валюты: у банка — три строки одной даты и одного текста
    (Payment GEL 5 / Income GEL 5 / Payment USD 1.87). Так их и показывает синхронизация ZenMoney: расход в GEL +
    обмен USD→GEL. Возвращает (строки без этих трёх, операции: fee-расход + transfer)."""
    groups: dict = {}
    for r in rows:
        if r["kind"] == "fee":
            groups.setdefault((r["date"], r["rest"]), []).append(r)
    gone, out = set(), []
    for (date, rest), g in groups.items():
        for pay in [r for r in g if r["side"] == "out" and r["n"] not in gone]:
            back = next((r for r in g if r["side"] == "in" and r["n"] not in gone and r["ccy"] == pay["ccy"] and r["amt"] == pay["amt"]), None)
            frn = next((r for r in g if r["side"] == "out" and r["n"] not in gone and r["ccy"] != pay["ccy"]), None)
            if back and frn:
                gone.update((pay["n"], back["n"], frn["n"]))
                out.append((pay, back, frn))
    return [r for r in rows if r["n"] not in gone], out


def neutralize(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Взаимно гасящиеся пары Payment/Income (дата, валюта, сумма, текст) → internal. Остальное — как есть."""
    by_key: dict = {}
    for r in rows:
        if r["kind"] in ("fee", "transfer_out", "topup", "unknown") and "rest" in r:
            by_key.setdefault((r["date"], r["ccy"], r["amt"], r["rest"]), {"in": [], "out": []})[r["side"]].append(r)
    gone, internal = set(), []
    for (date, ccy, amt, rest), g in by_key.items():
        for o, i in zip(g["out"], g["in"]):
            gone.update((o["n"], i["n"]))
            internal.append({"date": iso(date), "currency": ccy, "amount": str(amt), "text": rest[:60], "rows": [o["n"], i["n"]]})
    return [r for r in rows if r["n"] not in gone], sorted(internal, key=lambda x: (x["date"], x["currency"]))


def pair_conversions(legs: list[dict], flags: list[dict]) -> list[tuple]:
    """Ноги одной даты с одним курсом, разные валюты, разные стороны: большая сумма ≈ меньшая × курс
    (GEL за USD/EUR; для кросса EUR↔USD — USD за EUR). Допуск — округление курса банком."""
    pairs, used = [], set()
    for g in legs:
        if g["n"] in used:
            continue
        def err(o):
            hi, lo = max(g["amt"], o["amt"]), min(g["amt"], o["amt"])
            return abs(hi - lo * g["rate"])
        cands = [o for o in legs if o["n"] not in used and o["n"] != g["n"] and o["ccy"] != g["ccy"] and o["side"] != g["side"] and o["rate"] == g["rate"]
                 and err(o) <= min(g["amt"], o["amt"]) * Decimal("0.0006") + Decimal("0.011")]
        if cands:
            o = min(cands, key=err)
            used.update((o["n"], g["n"]))
            pairs.append((g, o))
    for lg in legs:
        if lg["n"] not in used:
            flags.append({"kind": "conversion-unmatched", "date": lg["date"], "detail": f'{lg["side"]} {lg["amt"]} {lg["ccy"]} по курсу {lg["rate"]}: пары нет'})
    return pairs


def normalize(parsed: dict) -> dict:
    sts = parsed["statements"]
    if not sts:
        raise Blocking("нет ни одной выписки BOG")
    bad = [s.get("file", "?") for s in sts if not s["checks"]["ok"]]
    if bad:
        raise Blocking("проверка парсера не сошлась: " + ", ".join(bad))
    seen: dict = {}
    for s in sts:
        m = s["meta"]
        for other in seen.get(m["account"], []):
            if not (iso(m["period_to"]) < iso(other["period_from"]) or iso(m["period_from"]) > iso(other["period_to"])):
                raise Blocking(f'два файла по одному счёту с пересекающимся периодом ({m["period_from"]}–{m["period_to"]}) — задвоение')
        seen.setdefault(m["account"], []).append(m)

    flags, ops, internal, reconcile = [], [], [], {}
    for st in sts:
        acct = st["meta"]["account"]
        rows = [parse_row(r) for r in st["rows"]]
        rows, fee_triples = fee_conversions(rows)
        rows, inner = neutralize(rows)
        for x in inner:
            x["account"] = acct
        internal += inner
        for pay, back, frn in fee_triples:
            ops.append({"date": iso(pay["date"]), "account": acct, "currency": pay["ccy"], "amount": str(pay["amt"]), "refs": [pay["n"]], "type": "expense", "kind": "fee", "original": None,
                        "merchant": {"name": "Bank of Georgia", "country": "Georgia", "mcc": None, "card": None}, "text": pay["text"]})
            ops.append({"type": "transfer", "date": iso(pay["date"]), "account": acct, "from": {"currency": frn["ccy"], "amount": str(frn["amt"])}, "to": {"currency": back["ccy"], "amount": str(back["amt"])},
                        "rate": None, "refs": [frn["n"], back["n"]], "how": "fee-conversion"})
        conv_by_date: dict = {}
        for r in rows:
            if r["kind"] == "unknown":
                flags.append({"kind": "unknown-row", "date": r["date"], "detail": f'{r["ccy"]} {r["amt"]}: {r["purpose"][:90]}'})
            elif r["kind"] == "convleg":
                conv_by_date.setdefault(r["date"], []).append(r)
        paired = set()
        for date, legs in conv_by_date.items():
            for g, o in pair_conversions(legs, flags):
                out, inn = (g, o) if g["side"] == "out" else (o, g)
                paired.update((g["n"], o["n"]))
                ops.append({"type": "transfer", "date": iso(date), "account": acct, "from": {"currency": out["ccy"], "amount": str(out["amt"])}, "to": {"currency": inn["ccy"], "amount": str(inn["amt"])},
                            "rate": str(g["rate"]), "refs": [out["n"], inn["n"]], "how": "rate-text"})
        for r in rows:
            k, base = r["kind"], {"date": iso(r["date"]), "account": acct, "currency": r["ccy"], "amount": str(r["amt"]), "refs": [r["n"]]}
            if k in ("purchase", "refund"):
                orig = {"amount": str(r["text_amt"]), "currency": r["text_ccy"]} if r["text_ccy"] != r["ccy"] else None
                ops.append({**base, "type": "expense" if k == "purchase" else "refund", "date": r["tx_date"], "booking_date": iso(r["date"]), "original": orig,
                            "merchant": r["merchant"]})
            elif k == "service":
                ops.append({**base, "type": "expense", "original": None, "merchant": r["merchant"]})
            elif k == "fee":
                ops.append({**base, "type": "expense", "kind": "fee", "original": None, "merchant": {"name": "Bank of Georgia", "country": "Georgia", "mcc": None, "card": None}, "text": r["text"]})
            elif k in ("topup", "transfer_out"):
                ops.append({**base, "type": k, "counterparty_account": r["counterparty_account"], "text": r["text"]})
            elif k == "convleg" and r["n"] not in paired:
                pass  # флаг уже выставлен pair_conversions
        # сверка: Δ банка по валюте = сумма операций + внутренние пары (≈0) ; считаем по строкам, поэтому ловит потерянные/задвоенные
        delta = {c: D(st["meta"]["closing"].get(c, 0)) - D(st["meta"]["opening"].get(c, 0)) for c in st["meta"]["currencies"]}
        mine = [o for o in ops if o["account"] == acct]
        eff = {c: Decimal(0) for c in delta}
        for o in mine:
            t = o["type"]
            if t in ("topup", "refund"):
                eff[o["currency"]] += D(o["amount"])
            elif t in ("expense", "transfer_out"):
                eff[o["currency"]] -= D(o["amount"])
            elif t == "transfer":
                eff[o["from"]["currency"]] -= D(o["from"]["amount"])
                eff[o["to"]["currency"]] += D(o["to"]["amount"])
        for r in rows:  # непарные ноги обмена — тоже движение денег, но операции из них нет (флаг)
            if r["kind"] == "convleg" and r["n"] not in paired:
                eff[r["ccy"]] += r["amt"] if r["side"] == "in" else -r["amt"]
            elif r["kind"] == "unknown":
                eff[r["ccy"]] += r["amt"] if r["side"] == "in" else -r["amt"]
        reconcile[acct] = {c: {"delta_bank": str(delta[c]), "sum_operations": str(eff[c]), "residual": str(delta[c] - eff[c])} for c in delta}

    counts: Counter = Counter()
    for o in sorted(ops, key=lambda o: (o["date"], o["type"], o["account"], o["refs"])):
        sig = json.dumps([o["account"], o["type"], o["date"], o.get("currency") or o.get("from"), o.get("amount") or o.get("to"), (o.get("merchant") or {}).get("name"), o.get("text")], sort_keys=True, default=str)
        counts[sig] += 1  # одинаковые операции одного дня различаются порядковым номером — id не зависит от смещения строк в выгрузке
        o["id"] = "bog-" + hashlib.sha1((sig + f"#{counts[sig]}").encode()).hexdigest()[:12]
    ops.sort(key=lambda o: (o["date"], o["type"], o["id"]))
    return {"operations": ops, "flags": flags, "internal": internal, "reconcile": reconcile}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("parsed", help="JSON из parse_bog_statement.py")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        with open(a.parsed, encoding="utf-8") as f:
            res = normalize(json.load(f))
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
