#!/usr/bin/env python3
"""Нормализация справок Т-Банка: строки → операции для ZenMoney (решение 2026-11-01).

Т-Банк в ZenMoney подключён синхронизацией, поэтому операции не склеиваются, а идут построчно, как их
кладёт синхронизация: один договор (= один счёт ZenMoney) × строка справки. Исключение — кэшбэк: строки
кэшбэка одного дня синхронизация кладёт одной суммой («Зачисление кэшбэка»), нормализатор делает так же.

Вход: JSON из parse_tbank_statement.py (одна или несколько справок). Проверка парсера обязана сойтись;
две справки одного договора с пересекающимся периодом — стоп (задвоение).

Правила классификации (по тексту «Описание операции»):
  * «Оплата в <место> [<город>] [<страна>]» — покупка (`expense`); дата — дата операции, `booking_date` —
    дата списания. Валюта операции ≠ валюте договора → исходная сумма в `original`.
  * «Возврат средств по операции оплаты <место>» — возврат (`refund`).
  * «Оплата услуг mBank.<поставщик>» — платёж услуги (`expense`, место = поставщик).
  * «Комиссия за операции покупок/снятия наличных в иностранной валюте» — отдельный расход (`expense`,
    kind=fee-fx, место = банк). Его покупка — строка в чужой валюте того же договора с тем же временем
    списания: `fee_for` = id покупки. Так синхронизация и кладёт (две операции), а связь нужна, чтобы
    увидеть перепутанные точки (у комиссии — точка места, у покупки — банк).
  * «Внутренний перевод на договор N»: N — договор из приложенных справок → `transfer_out` (свой счёт);
    чужой договор → `expense` kind=p2p (перевод человеку; в ZenMoney это расход или перевод на счёт).
  * «AIA*<место> …» (оплата через агрегатор) — покупка, место после «AIA*». «Возврат покупки через СБП. <место>»,
    «Возврат по заказу …» — возврат.
  * «Пополнение брокерского счета» — `transfer_out` kind=broker; «Операция в других кредитных организациях <банк>» —
    `transfer_out` kind=other-bank; «Пополнение. <отправитель>» — `topup` kind=incoming; «Внутрибанковский перевод
    с договора N» — как «Перевод с договора N».
  * «Внешний перевод по номеру телефона|карты», «Перевод на карту другого банка» — `expense` kind=p2p, место
    не известно (контрагента не придумывать — правило 12).
  * «Внешний банковский перевод счёт …, <получатель>» — `expense`, место = получатель.
  * «Снятие наличных» — `transfer_out` kind=cash (в ZenMoney — перевод на наличные).
  * «Перевод себе» — `topup` со своего договора (договор-источник — по встречной строке другой справки,
    если она приложена); «Перевод с договора N» — `topup` с договора N; «Пополнение. Система быстрых
    платежей» — `topup` (СБП).
  * «Проценты на остаток» — `topup` kind=interest; «Кэшбэк за …» — `topup` kind=cashback (суммой за
    день); «Компенсация поездки» — `refund` kind=compensation (место = банк).
  * Не распознанное → флаг `unknown-row`, ничего не додумывается.

Выход: {operations, flags, reconcile, bank_merchant}. Входящего остатка в справке нет, поэтому
`reconcile` по договору — сумма операций (должна совпасть с «Пополнения − Расходы») и доступный остаток
на дату: его сверяют с `get_account_balances` ZenMoney на ту же дату (`stmt_accounts.check_balances`).
Только stdlib. Коды: 0 — ок, 2 — blocking.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal

BANK_MERCHANT = "Т-Банк"  # так точку банка называет ZenMoney (комиссии, проценты, кэшбэк)

RE_PAY = re.compile(r"^(?:Оплата в\s+(?P<rest>.+)|(?P<aia>AIA\*.+))$")
RE_REFUND = re.compile(r"^(?:Возврат средств по (?:операции )?оплат[аеы]\s+|Возврат покупки через СБП\.\s*)(?P<rest>.+)$")
RE_SERVICE = re.compile(r"^Оплата услуг\s+(?:mBank\.)?(?P<name>.+)$")
RE_FEE_FX = re.compile(r"^Комиссия за операции покупок/снятия наличных в иностранной валюте")
RE_FEE = re.compile(r"^Комиссия\b")
RE_INTERNAL_OUT = re.compile(r"^Внутренний перевод на договор\s+(?P<c>\d+)")
RE_FROM_CONTRACT = re.compile(r"^(?:Внутрибанковский перевод|Перевод) с договора\s+(?P<c>\d+)")
RE_EXT_BANK = re.compile(r"^Внешний банковский перевод счёт\s+\d+,\s*(?P<name>.+)$")
RE_COUNTRY = re.compile(r"^[A-Z]{2,3}$")


PAIR_MINUTES = 5  # встречные строки своего перевода расходятся на минуту-другую (08.10 19:37 → 19:38)


def _minutes(a: dict, b: dict) -> float:
    ta = datetime.strptime(f'{a["date"]} {a["time"] or "00:00"}', "%Y-%m-%d %H:%M")
    tb = datetime.strptime(f'{b["date"]} {b["time"] or "00:00"}', "%Y-%m-%d %H:%M")
    return abs((ta - tb).total_seconds()) / 60


class Blocking(Exception):
    pass


def D(s) -> Decimal:
    return Decimal(str(s).replace(" ", "").lstrip("+"))


def iso(d: str) -> str:
    return datetime.strptime(d, "%d.%m.%Y").strftime("%Y-%m-%d")


def split_place(rest: str) -> dict:
    """«OOO MOSPLOV MOSCOW RUS» → name «OOO MOSPLOV», city «MOSCOW», country «RUS». Без кода страны в конце —
    всё название (город не отделяем: не угадываем). «GRANDTRAIN g. Moskva RUS» → «GRANDTRAIN»."""
    toks = rest.split()
    country = city = None
    if len(toks) >= 2 and RE_COUNTRY.fullmatch(toks[-1]):
        country = toks.pop()
        if len(toks) >= 2:
            city = toks.pop()
            if len(toks) >= 2 and toks[-1].lower() == "g.":
                toks.pop()
    name = " ".join(toks)
    return {"name": name, "raw": rest, "country": country, "city": city}


def classify(r: dict, own: set) -> dict:
    p, a = r["purpose"], D(r["amount"])
    side = "in" if a > 0 else "out"
    m = RE_PAY.match(p)
    if m and side == "out":
        place = split_place(m["rest"] or m["aia"])
        if m["aia"]:  # «AIA*vkusvill MOSCOW RU» — оплата через агрегатор (Apple Pay / сервис): место — после «AIA*»
            place["name"] = place["name"][4:] or place["name"]
        return {"type": "expense", "kind": "purchase", "merchant": place}
    m = RE_REFUND.match(p)
    if m and side == "in":
        return {"type": "refund", "kind": "refund", "merchant": split_place(m["rest"])}
    m = RE_SERVICE.match(p)
    if m and side == "out":
        name = m["name"].strip()
        return {"type": "expense", "kind": "service", "merchant": {"name": name, "raw": p, "country": None, "city": None}}
    if RE_FEE_FX.match(p) and side == "out":
        return {"type": "expense", "kind": "fee-fx", "merchant": {"name": BANK_MERCHANT, "raw": None, "country": None, "city": None}, "text": "Комиссия за операцию в иностранной валюте"}
    if RE_FEE.match(p) and side == "out":
        return {"type": "expense", "kind": "fee", "merchant": {"name": BANK_MERCHANT, "raw": None, "country": None, "city": None}, "text": p}
    m = RE_INTERNAL_OUT.match(p)
    if m and side == "out":
        if m["c"] in own:
            return {"type": "transfer_out", "kind": "own", "counterparty_contract": m["c"], "text": "Перевод на свой договор"}
        return {"type": "expense", "kind": "p2p", "counterparty_contract": m["c"], "merchant": None, "text": "Перевод на договор Т-Банка"}
    if (p.startswith("Внешний перевод по номеру") or p.startswith("Перевод на карту другого банка")) and side == "out":
        return {"type": "expense", "kind": "p2p", "merchant": None, "text": p}
    m = RE_EXT_BANK.match(p)
    if m and side == "out":
        return {"type": "expense", "kind": "bank-transfer", "merchant": {"name": m["name"].strip(), "raw": p, "country": None, "city": None}}
    if p.startswith("Пополнение брокерского счета") and side == "out":
        return {"type": "transfer_out", "kind": "broker", "counterparty_contract": None, "text": "Пополнение брокерского счёта"}
    m = re.match(r"^Операция в других кредитных организациях\s+(?P<rest>.+)$", p)
    if m and side == "out":
        return {"type": "transfer_out", "kind": "other-bank", "counterparty_contract": None, "recipient_bank": m["rest"], "text": "Операция в другом банке"}
    if p.startswith("Снятие наличных") and side == "out":
        return {"type": "transfer_out", "kind": "cash", "counterparty_contract": None, "text": "Снятие наличных"}
    if p == "Перевод себе" and side == "in":
        return {"type": "topup", "kind": "own", "counterparty_contract": None, "text": "Перевод себе"}
    m = RE_FROM_CONTRACT.match(p)
    if m and side == "in":
        return {"type": "topup", "kind": "own" if m["c"] in own else "p2p", "counterparty_contract": m["c"], "text": "Перевод с договора Т-Банка"}
    if p.startswith("Пополнение. Система быстрых платежей") and side == "in":
        return {"type": "topup", "kind": "sbp", "counterparty_contract": None, "text": "Пополнение через СБП"}
    if p.startswith("Проценты на остаток") and side == "in":
        return {"type": "topup", "kind": "interest", "counterparty_contract": None, "text": "Проценты на остаток", "merchant": {"name": BANK_MERCHANT, "raw": None, "country": None, "city": None}}
    if (p.startswith("Кэшбэк") or p.startswith("Зачисление кэшбэка") or p.startswith("Выплата кэшбэка") or p.startswith("За участие в акции")) and side == "in":
        return {"type": "topup", "kind": "cashback", "counterparty_contract": None, "text": "Кэшбэк", "merchant": {"name": BANK_MERCHANT, "raw": None, "country": None, "city": None}}
    if p.startswith("Возврат по заказу") and side == "in":
        return {"type": "refund", "kind": "refund", "merchant": {"name": p.split(" в ", 1)[-1].strip() if " в " in p else BANK_MERCHANT, "raw": p, "country": None, "city": None}, "text": p}
    if p.startswith("Пополнение.") and side == "in":
        return {"type": "topup", "kind": "incoming", "counterparty_contract": None, "text": p}
    if p.startswith("Компенсация") and side == "in":
        return {"type": "refund", "kind": "compensation", "merchant": {"name": BANK_MERCHANT, "raw": p, "country": None, "city": None}, "text": p}
    return {"type": None, "kind": "unknown"}


def normalize(parsed: dict) -> dict:
    sts = parsed["statements"]
    if not sts:
        raise Blocking("нет ни одной справки Т-Банка")
    bad = [s.get("file", "?") for s in sts if not s["checks"]["ok"]]
    if bad:
        raise Blocking("проверка парсера не сошлась: " + ", ".join(bad))
    seen: dict = {}
    for s in sts:
        m = s["meta"]
        for other in seen.get(m["contract"], []):
            if not (iso(m["period_to"]) < iso(other["period_from"]) or iso(m["period_from"]) > iso(other["period_to"])):
                raise Blocking(f'две справки по договору …{m["contract"][-4:]} с пересекающимся периодом — задвоение')
        seen.setdefault(m["contract"], []).append(m)
    own = set(seen)

    flags, ops, reconcile = [], [], {}
    for st in sts:
        meta = st["meta"]
        acct, ccy = meta["contract"], meta["currency"]
        rows = st["rows"]
        cash: dict = {}
        for r in rows:
            c = classify(r, own)
            if c["kind"] == "unknown":
                flags.append({"kind": "unknown-row", "account": acct, "date": iso(r["date"]), "detail": f'{r["amount"]} {ccy}: {r["purpose"][:90]}'})
                continue
            amt = abs(D(r["amount"]))
            base = {"account": acct, "date": iso(r["date"]), "time": r["time"], "booking_date": iso(r["booking_date"]), "booking_time": r["booking_time"],
                    "currency": ccy, "amount": str(amt), "refs": [r["n"]], "type": c["type"], "kind": c["kind"], "card": r["card"]}
            if c["kind"] == "cashback":
                key = r["date"]  # синхронизация кладёт весь кэшбэк дня одной суммой (строки 15-го числа — с разным временем)
                if key in cash:
                    o = cash[key]
                    o["amount"] = str(D(o["amount"]) + amt)
                    o["refs"].append(r["n"])
                    continue
            o = dict(base)
            if r["currency_op"] != ccy:
                o["original"] = {"amount": str(abs(D(r["amount_op"]))), "currency": r["currency_op"]}
            for k in ("merchant", "counterparty_contract", "text"):
                if k in c:
                    o[k] = c[k]
            if c["kind"] == "cashback":
                cash[r["date"]] = o
            ops.append(o)
        # комиссия за валюту → её покупка: тот же договор, то же время списания, покупка в чужой валюте
        mine = [o for o in ops if o["account"] == acct]
        for f in [o for o in mine if o["kind"] == "fee-fx"]:
            cands = [o for o in mine if o["kind"] == "purchase" and o.get("original") and (o["booking_date"], o["booking_time"]) == (f["booking_date"], f["booking_time"])]
            if len(cands) == 1:
                f["_fee_for"] = cands[0]
            else:
                flags.append({"kind": "fee-unlinked", "account": acct, "date": f["date"], "detail": f'комиссия {f["amount"]} {ccy}: покупок в валюте с тем же временем списания — {len(cands)}'})
        s = sum((D(o["amount"]) * (1 if o["type"] in ("topup", "refund") else -1) for o in mine), Decimal(0))
        unk = sum((D(r["amount"]) for r in rows if classify(r, own)["kind"] == "unknown"), Decimal(0))
        expected = D(meta["total_in"]) - D(meta["total_out"])
        reconcile[acct] = {"currency": ccy, "period": f'{iso(meta["period_from"])}…{iso(meta["period_to"])}', "sum_operations": str(s), "unknown_rows": str(unk),
                           "footer_net": str(expected), "residual": str(expected - s - unk),
                           "closing_available": meta["closing"], "closing_date": iso(meta["closing_date"])}

    # «Перевод себе» без номера договора: договор-источник — встречная строка «Внутренний перевод на договор <этот>» той же суммы в пределах PAIR_MINUTES
    outs = [o for o in ops if o["type"] == "transfer_out" and o["kind"] == "own"]
    for o in ops:
        if o["type"] == "topup" and o["kind"] == "own" and not o.get("counterparty_contract"):
            hit = [x for x in outs if x["counterparty_contract"] == o["account"] and x["amount"] == o["amount"] and not x.get("_used") and _minutes(x, o) <= PAIR_MINUTES]
            if hit:
                hit = sorted(hit, key=lambda x: _minutes(x, o))
                hit[0]["_used"] = True
                o["counterparty_contract"] = hit[0]["account"]

    counts: Counter = Counter()
    for o in sorted(ops, key=lambda o: (o["account"], o["date"], o["time"] or "", o["type"], o["refs"])):
        sig = json.dumps([o["account"], o["type"], o["date"], o["time"], o["amount"], (o.get("merchant") or {}).get("raw") or (o.get("merchant") or {}).get("name"), o.get("text")], sort_keys=True)
        counts[sig] += 1
        o["id"] = "tb-" + hashlib.sha1((sig + f"#{counts[sig]}").encode()).hexdigest()[:12]
    for o in ops:
        o.pop("_used", None)
        if "_fee_for" in o:
            o["fee_for"] = o.pop("_fee_for")["id"]
    ops.sort(key=lambda o: (o["date"], o["time"] or "", o["account"], o["id"]))
    return {"operations": ops, "flags": flags, "reconcile": reconcile, "bank_merchant": BANK_MERCHANT}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("parsed", help="JSON из parse_tbank_statement.py")
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
