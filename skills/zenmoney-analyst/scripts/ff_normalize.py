#!/usr/bin/env python3
"""Нормализация выписок FF: строки четырёх валют → операции для ZenMoney (решение 2026-10-10).

FF — мультивалютная карта: четыре счёта (RUB, USD, KZT, EUR) работают в тандеме. Покупка
в валюте, где нет денег, идёт цепочкой «конвертация из другой валюты → покупка». Выписка
показывает каждую ногу отдельной строкой, а в ZenMoney нужна одна операция. Скрипт
собирает цепочки детерминированно; что собрать однозначно нельзя — помечает флагом и ничего
не додумывает.

Вход: JSON из parse_ff_statement.py. Обязательны ТЕКУЩИЕ выписки всех четырёх валют
(иначе цепочку не замкнуть — стоп); депозитные необязательны (нужны для сверки остатка).

Правила (почему именно так — docs/zenmoney/ff-import-plan.md):
  * «Прием вклада» / «Выплата вклада» — движение между текущим и депозитным счётом FF.
    Счёт FF в ZenMoney = текущий + депозит, на сумму не влияет → не операция.
  * Покупка/возврат — по строке «Операция: Покупка|Возврат»: дата транзакции, сумма и валюта
    покупки, место `терминал\\СТРАНА\\ГОРОД\\ТОЧКА` (у части покупок банк места не пишет).
  * Конвертация и «Transfer of own funds» — ноги обмена. Пары: сначала по «курсу» из текста
    (KZT: списано = зачислено / курс), затем перебором с условием «лоты одной пары валют
    идут по одному курсу (разброс ≤ 2%)». Не нашлось / несколько равноценных → флаг.
  * Транзитные валюты (по умолчанию EUR, KZT — денег там не держат): конвертация в такую
    валюту + покупка в ней = одна покупка в валюте источника (FIFO по лотам, остаток лота
    переходит дальше); возврат в транзитной валюте + обратная конвертация = один возврат.
  * «Перевод собственных средств на счёт в другом банке» с кредитом = пополнение из
    другого банка (сверяется с переводом в ZenMoney ±3 дня).
  * Проценты по вкладу — отдельный список (`interest`), в операции не идут.

Выход: {operations, flags, reconcile, interest}. Сверка остатка по каждой реальной валюте:
Δ(текущий + депозит) = сумма операций + остаток транзита ± копейки (по проценты).
Только stdlib. Коды: 0 — ок, 2 — blocking (нет выписки валюты, не сошлась проверка парсера).
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import sys
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

CURRENCIES = ("RUB", "USD", "KZT", "EUR")
DEFAULT_TRANSIT = ("EUR", "KZT")
CENT = Decimal("0.01")
RATE_SPREAD = Decimal("0.02")  # лоты одной пары валют, обмененные одновременно, по курсу в пределах 2%

RE_PURCHASE = re.compile(r"Операция:\s*(Покупка|Возврат)")
RE_TX_DATE = re.compile(r"Дата транзакции:\s*(\d\d\.\d\d\.\d{4})")
RE_TX_AMOUNT = re.compile(r"Сумма транзакции:\s*([\d ]+(?:\.\d+)?)\s*([A-Z]{3})")
RE_MERCHANT = re.compile(r"устройстве\s+(\S*?)\\([A-Z]{3})\\([^\\]*)\\(.+?)\s*$")
RE_RATE = re.compile(r"по курсу\s*([\d.]+?)\.?(?:\s|$)")


class Blocking(Exception):
    pass


def D(s) -> Decimal:
    return Decimal(str(s).replace(" ", ""))


def q(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def to_iso(d: str) -> str:
    return datetime.strptime(d, "%d.%m.%Y").strftime("%Y-%m-%d")


# ---------------------------------------------------------------- классификация строк

# Банк пишет в тексте «Сумма транзакции» для VND в сотых долях: 2440 в выписке = ₫244 000 в приложении (скриншот Apple Pay, 2026-10-11)
TEXT_SCALE = {"VND": 100}


def classify(purpose: str, debit, credit) -> str:
    if re.search(r"Выплата процентов", purpose):
        return "interest"
    if re.search(r"Прием вклада|Выплата вклада|вклада по Договору|вклада с депозитного|по договору\s+KZ\w+\s+в сумме\s+[\d.]+\s+[A-Z]{3}\.\s+Вкладчик", purpose):
        return "sweep"
    if RE_PURCHASE.search(purpose):
        return "refund" if "Возврат" in RE_PURCHASE.search(purpose).group(1) else "purchase"
    if "Конвертация" in purpose or "Transfer of own funds" in purpose:
        return "convleg"
    if "Перевод собственных средств на счет в другом банке" in purpose or "собственных средств на счет в другом" in purpose:
        return "topup" if credit else "transfer_out"
    return "unknown"


def merchant_of(purpose: str):
    m = RE_MERCHANT.search(purpose)
    if not m:
        return None
    return {"terminal": m[1], "country": m[2], "city": m[3].strip(), "name": m[4].strip(), "raw": m[0].replace("устройстве", "", 1).strip()}


# ---------------------------------------------------------------- пары конвертаций

def pair_conversions(legs: list[dict], flags: list[dict]) -> list[dict]:
    """legs одной даты: {i, ccy, side: out|in, amt, rate_hint}. → пары {out, in, rate}."""
    pairs, used = [], set()
    # 1) по курсу из текста: списано = зачислено / курс (с точностью до копейки)
    for lg in legs:
        if lg["side"] != "in" or lg.get("rate_hint") is None:
            continue
        expect = lg["amt"] / lg["rate_hint"]
        cands = [o for o in legs if o["side"] == "out" and o["i"] not in used and o["ccy"] != lg["ccy"] and abs(o["amt"] - expect) <= Decimal("0.011")]
        if len(cands) >= 1:
            o = min(cands, key=lambda o: abs(o["amt"] - expect))
            used.add(o["i"]); used.add(lg["i"])
            pairs.append({"out": o, "in": lg, "how": "rate-text"})
    rest = [lg for lg in legs if lg["i"] not in used]
    outs = [lg for lg in rest if lg["side"] == "out"]
    ins = [lg for lg in rest if lg["side"] == "in"]
    if not outs and not ins:
        return pairs
    if len(outs) != len(ins) or len(outs) > 7:
        flags.append({"kind": "conversion-unbalanced", "date": legs[0]["date"], "detail": f"ног списания {len(outs)}, зачисления {len(ins)}"})
        return pairs
    best, second = None, None
    for perm in itertools.permutations(range(len(ins))):
        cand = [(outs[k], ins[p]) for k, p in enumerate(perm)]
        if any(o["ccy"] == i["ccy"] for o, i in cand):
            continue
        groups: dict = {}
        for o, i in cand:
            groups.setdefault((o["ccy"], i["ccy"]), []).append(o["amt"] / i["amt"])
        spread = max((max(v) / min(v) - 1 for v in groups.values()), default=Decimal(0))
        if spread > RATE_SPREAD:
            continue
        score = sum((max(v) / min(v) - 1 for v in groups.values()), Decimal(0))
        if best is None or score < best[0]:
            best, second = (score, cand), best
        elif second is None or score < second[0]:
            second = (score, cand)
    if best is None:
        flags.append({"kind": "conversion-unmatched", "date": legs[0]["date"], "detail": "курсы пар не сходятся ни в одном сочетании: " + ", ".join(f'{l["side"]} {l["amt"]} {l["ccy"]}' for l in rest)})
        return pairs
    if second is not None and second[0] - best[0] <= Decimal("0.002") and {(o["i"], i["i"]) for o, i in second[1]} != {(o["i"], i["i"]) for o, i in best[1]}:
        # равноценные сочетания: безразлично, если курсы пар различаются меньше 0.5%
        def rates(c): return sorted(o["amt"] / i["amt"] for o, i in c)
        if any(abs(a - b) / a > Decimal("0.005") for a, b in zip(rates(best[1]), rates(second[1]))):
            flags.append({"kind": "conversion-ambiguous", "date": legs[0]["date"], "detail": "несколько равноценных сочетаний ног обмена"})
    for o, i in best[1]:
        pairs.append({"out": o, "in": i, "how": "rate-consistency"})
    return pairs


# ---------------------------------------------------------------- основная сборка

def normalize(parsed: dict, transit=DEFAULT_TRANSIT) -> dict:
    sts = parsed["statements"]
    cur = {s["meta"]["currency"]: s for s in sts if s["meta"]["kind"] == "current"}
    dep = {s["meta"]["currency"]: s for s in sts if s["meta"]["kind"] == "deposit"}
    missing = [c for c in CURRENCIES if c not in cur]
    if missing:
        raise Blocking("для FF нужны текущие выписки ВСЕХ четырёх валют (цепочка конвертаций не замкнётся); нет: " + ", ".join(missing))
    bad = [f'{s.get("file","?")}' for s in sts if not s["checks"]["ok"]]
    if bad:
        raise Blocking("проверка парсера не сошлась: " + ", ".join(bad))
    periods = {(s["meta"]["period_from"], s["meta"]["period_to"]) for s in cur.values()}
    if len(periods) > 1:
        raise Blocking("периоды выписок разные: " + str(sorted(periods)))

    flags: list[dict] = []
    ops: list[dict] = []
    interest: list[dict] = []
    events: list[dict] = []  # покупки/возвраты/конвертации для разбора лотов
    legs_by_date: dict[str, list] = {}

    for ccy, st in cur.items():
        for n, r in enumerate(st["rows"]):
            p = r["purpose"]
            kind = classify(p, r["debit"], r["credit"])
            amt = D(r["credit"] or r["debit"] or 0)
            row_ref = {"ccy": ccy, "n": n, "doc": r["doc"], "date": r["date"]}
            if kind == "sweep":
                continue
            if kind == "unknown":
                flags.append({"kind": "unknown-row", "date": r["date"], "detail": f"{ccy} {r['debit'] or r['credit']}: {p[:90]}"})
            elif kind in ("purchase", "refund"):
                tx = RE_TX_AMOUNT.search(p)
                td = RE_TX_DATE.search(p)
                events.append({"t": kind, "ccy": ccy, "amt": amt, "date": r["date"], "tx_date": td[1] if td else r["date"],
                               "orig": ({"amount": str(D(tx[1]) * TEXT_SCALE.get(tx[2], 1)), "currency": tx[2]} if tx else None), "merchant": merchant_of(p), "ref": row_ref})
                if not merchant_of(p):
                    flags.append({"kind": "no-merchant", "date": r["date"], "detail": f"{ccy} {amt}: банк не указал место"})
            elif kind == "convleg":
                hint = RE_RATE.search(p)
                legs_by_date.setdefault(r["date"], []).append({"i": (ccy, n), "ccy": ccy, "side": "out" if r["debit"] else "in", "amt": amt,
                                                                "rate_hint": D(hint[1]) if hint and r["credit"] else None, "date": r["date"], "ref": row_ref})
            elif kind == "topup":
                ops.append({"type": "topup", "date": to_iso(r["date"]), "currency": ccy, "amount": str(amt), "refs": [row_ref],
                            "text": "Пополнение из другого банка"})
            elif kind == "transfer_out":
                ops.append({"type": "transfer_out", "date": to_iso(r["date"]), "currency": ccy, "amount": str(amt), "refs": [row_ref]})

    for ccy, st in dep.items():
        for r in st["rows"]:
            if classify(r["purpose"], r["debit"], r["credit"]) == "interest":
                interest.append({"date": to_iso(r["date"]), "currency": ccy, "amount": r["credit"]})

    # пары конвертаций по датам
    conv_pairs: list[dict] = []
    for date, legs in sorted(legs_by_date.items(), key=lambda kv: to_iso(kv[0])):
        for pr in pair_conversions(legs, flags):
            pr["date"] = date
            conv_pairs.append(pr)

    # события по порядку: конвертация-вход, покупка, возврат, конвертация-выход (внутри даты)
    order = {"conv_in": 0, "purchase": 1, "refund": 2, "conv_out": 3}
    timeline = []
    for pr in conv_pairs:
        o, i = pr["out"], pr["in"]
        if i["ccy"] in transit and o["ccy"] not in transit:
            timeline.append({"t": "conv_in", "date": pr["date"], "ccy": i["ccy"], "amt": i["amt"], "src_ccy": o["ccy"], "src_amt": o["amt"], "refs": [o["ref"], i["ref"]]})
        elif o["ccy"] in transit and i["ccy"] not in transit:
            timeline.append({"t": "conv_out", "date": pr["date"], "ccy": o["ccy"], "amt": o["amt"], "dst_ccy": i["ccy"], "dst_amt": i["amt"], "refs": [o["ref"], i["ref"]]})
        elif o["ccy"] in transit and i["ccy"] in transit:
            flags.append({"kind": "transit-to-transit", "date": pr["date"], "detail": f'{o["ccy"]}→{i["ccy"]}: не поддержано'})
        else:
            ops.append({"type": "transfer", "date": to_iso(pr["date"]), "from": {"currency": o["ccy"], "amount": str(o["amt"])}, "to": {"currency": i["ccy"], "amount": str(i["amt"])},
                        "rate": str(q(o["amt"] / i["amt"])) if i["amt"] else None, "refs": [o["ref"], i["ref"]], "how": pr["how"]})
    for e in events:
        timeline.append(dict(e))

    def key(e):
        return (to_iso(e["date"]), order[e["t"]])

    drift: dict = {}  # накопленная ошибка округления цен по валютам-источникам
    refund_acc: dict = {}  # (id возврата, валюта) → части обратной конвертации складываются в один возврат
    lots: dict[str, list] = {c: [] for c in transit}  # {amt, cost: {ccy: Decimal}, kind: bought|refund}
    for e in sorted(timeline, key=key):
        c = e["ccy"]
        if e["t"] == "conv_in":
            lots[c].append({"amt": e["amt"], "cost": {e["src_ccy"]: e["src_amt"]}, "kind": "bought", "refs": list(e["refs"])})
        elif e["t"] == "purchase":
            if c in transit:
                cost, refs, rest = {}, [e["ref"]], e["amt"]
                while rest > 0 and lots[c]:
                    lot = lots[c][0]
                    take = min(rest, lot["amt"])
                    frac = take / lot["amt"]
                    for k, v in lot["cost"].items():
                        part = v if take == lot["amt"] else v * frac
                        cost[k] = cost.get(k, Decimal(0)) + part
                        lot["cost"][k] = v - part
                    lot["amt"] -= take
                    rest -= take
                    refs += lot["refs"]
                    if lot["amt"] == 0:
                        lots[c].pop(0)
                if rest > 0:
                    flags.append({"kind": "transit-unfunded", "date": e["date"], "detail": f"покупка {e['amt']} {c} без конвертации-источника (не хватает {rest})"})
                # хвост переносимого остатка лота (< 0.005) не отдельная операция — вливается в основную ногу
                tiny = [k for k, v in cost.items() if q(v) == 0]
                if tiny and len(cost) > len(tiny):
                    main = max(cost, key=lambda k: cost[k])
                    for k in tiny:
                        cost[main] += cost.pop(k)
                for k, v in cost.items():
                    # остаток округления переносим на следующую покупку: сумма цен не расходится с реально списанным
                    v += drift.get(k, Decimal(0))
                    drift[k] = v - q(v)
                    ops.append(_expense(e, k, q(v), refs, via=c))
            else:
                ops.append(_expense(e, c, e["amt"], [e["ref"]]))
        elif e["t"] == "refund":
            if c in transit:
                lots[c].append({"amt": e["amt"], "cost": {}, "kind": "refund", "refs": [e["ref"]], "ev": e})
            else:
                ops.append(_income(e, c, e["amt"], [e["ref"]]))
        elif e["t"] == "conv_out":
            rest = e["amt"]
            proceeds = e["dst_amt"]
            while rest > 0 and lots[c]:
                lot = lots[c][0]
                take = min(rest, lot["amt"])
                part = proceeds * take / e["amt"]
                if lot["kind"] == "refund":
                    acc = refund_acc.setdefault((id(lot["ev"]), e["dst_ccy"]), {"ev": lot["ev"], "sum": Decimal(0), "refs": list(lot["refs"])})
                    acc["sum"] += part
                    acc["refs"] += e["refs"]
                else:
                    ops.append({"type": "fx_unwind", "date": to_iso(e["date"]), "currency": e["dst_ccy"], "amount": str(q(part)), "refs": e["refs"],
                                "text": f"обратная конвертация непотраченного остатка {c}"})
                    flags.append({"kind": "unwind-leftover", "date": e["date"], "detail": f"{c}: проданный остаток без возврата покупки"})
                lot["amt"] -= take
                rest -= take
                if lot["amt"] == 0:
                    lots[c].pop(0)
            if rest > 0:
                flags.append({"kind": "transit-oversold", "date": e["date"], "detail": f"продано {rest} {c} больше, чем было"})

    for (_, dst), acc in refund_acc.items():
        ops.append(_income(acc["ev"], dst, q(acc["sum"]), acc["refs"], via=acc["ev"]["ccy"]))

    ops.sort(key=lambda o: (o["date"], o["type"]))
    for o in ops:
        sig = json.dumps([o["type"], o["date"], o.get("currency") or o.get("from"), o.get("amount") or o.get("to"), [(r["ccy"], r["doc"], r["n"]) for r in o["refs"]]], sort_keys=True, default=str)
        o["id"] = "ff-" + hashlib.sha1(sig.encode()).hexdigest()[:12]

    for c in transit:
        left = sum((l["amt"] for l in lots[c]), Decimal(0))
        if left > Decimal("0.5"):
            flags.append({"kind": "transit-leftover", "date": "", "detail": f"в транзитной валюте {c} остался непотраченный остаток {left} — проверьте, не должен ли он быть на счёте"})
    leftover = {c: {"amount": str(sum((l["amt"] for l in lots[c]), Decimal(0))), "cost": {k: str(q(sum((l["cost"].get(k, Decimal(0)) for l in lots[c]), Decimal(0)))) for k in CURRENCIES if any(k in l["cost"] for l in lots[c])}} for c in transit}
    return {"operations": ops, "flags": flags, "interest": interest, "transit_leftover": leftover,
            "reconcile": reconcile(cur, dep, ops, leftover, transit, interest)}


def _expense(e, ccy, amount, refs, via=None):
    o = {"type": "expense", "date": to_iso(e["tx_date"]), "booking_date": to_iso(e["date"]), "currency": ccy, "amount": str(amount),
         "original": e["orig"], "merchant": e["merchant"], "refs": refs}
    if via:
        o["via_transit"] = via
    return o


def _income(e, ccy, amount, refs, via=None):
    o = {"type": "refund", "date": to_iso(e["tx_date"]), "booking_date": to_iso(e["date"]), "currency": ccy, "amount": str(amount),
         "original": e["orig"], "merchant": e["merchant"], "refs": refs}
    if via:
        o["via_transit"] = via
    return o


def reconcile(cur, dep, ops, leftover, transit, interest):
    """Δ(текущий + депозит) по реальным валютам против суммы операций. Нужны депозитные выписки."""
    out = {}
    for ccy in CURRENCIES:
        if ccy in transit:
            continue
        if ccy not in dep:
            out[ccy] = {"checked": False, "why": "нет депозитной выписки этой валюты"}
            continue
        c, d = cur[ccy]["meta"], dep[ccy]["meta"]
        delta = D(c["closing"]) + D(d["closing"]) - D(c["opening"]) - D(d["opening"])
        eff = Decimal(0)
        for o in ops:
            t = o["type"]
            if t in ("topup", "fx_unwind", "refund") and o["currency"] == ccy:
                eff += D(o["amount"])
            elif t in ("expense", "transfer_out") and o["currency"] == ccy:
                eff -= D(o["amount"])
            elif t == "transfer":
                if o["from"]["currency"] == ccy:
                    eff -= D(o["from"]["amount"])
                if o["to"]["currency"] == ccy:
                    eff += D(o["to"]["amount"])
        for t, info in leftover.items():
            eff -= D(info["cost"].get(ccy, 0))
        intr = sum((D(i["amount"]) for i in interest if i["currency"] == ccy), Decimal(0))
        out[ccy] = {"checked": True, "delta_bank": str(delta), "sum_operations": str(eff), "interest": str(intr), "residual": str(delta - eff - intr)}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("parsed", help="JSON из parse_ff_statement.py")
    ap.add_argument("--transit", default=",".join(DEFAULT_TRANSIT), help="транзитные валюты (по умолчанию EUR,KZT)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        with open(a.parsed, encoding="utf-8") as f:
            res = normalize(json.load(f), tuple(x for x in a.transit.split(",") if x))
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
