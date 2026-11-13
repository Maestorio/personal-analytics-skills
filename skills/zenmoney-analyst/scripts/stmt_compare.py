#!/usr/bin/env python3
"""Сопоставление операций выписки FF (ff_normalize.py) с операциями ZenMoney (MCP list_transactions).

Только чтение и арифметика — в ZenMoney ничего не пишет. Результат — списки расхождений,
из которых режим F предлагает исправления, а режим E (после «да») — добавление операций.

Вход:
  --ops    JSON из ff_normalize.py (операции банка)
  --zen    JSON с операциями ZenMoney: {"data": [...], "references": {...}} — страницы list_transactions
           по счетам FF, склеенные (data — конкатенация, references.accounts / categories — слияние)
  --accounts RUB=<id>,USD=<id>,KZT=<id>   счета FF в ZenMoney (EUR нет — валюта транзитная)
  [--from YYYY-MM-DD --to YYYY-MM-DD]     окно сравнения (обе стороны)
  [--adjust-category-id <id>]             категория «Корректировка» (list_categories.balanceAdjustmentCategoryId)
  [--bank-account <счёт|договор>]         только операции банка этого счёта (Т-Банк: несколько RUB-счетов — по одному за прогон)
  [--with-transfer-out]                   сравнивать и переводы банка на другие счета

Классы расхождений:
  matched              есть и в банке, и в ZenMoney (сумма совпала до копейки)
  differs              пара найдена, но сумма отличается (обычно курс) — показываем разницу
  missing_in_zen       есть в банке, нет в ZenMoney  → кандидат на добавление
  missing_in_bank      есть в ZenMoney (на счетах FF), нет в банке; adjustment=true для «Корректировок баланса»
  topup_currency       пополнение: ZenMoney зачислил на FF другую валюту, чем банк (подразумеваемый курс показан)
  date_shift           сумма совпала до копейки, дата разошлась больше чем на 3 дня (до 45; для сумм от 50 — до 120)
  merged               одна операция ZenMoney = сумма нескольких операций банка того же места
  partial_transfer     перевод: одна сторона совпала, другая нет
  to_other_account     покупка/перевод банка лежит в ZenMoney переводом на другой счёт (карта метро, свой депозит)
  expense_vs_transfer  наоборот: банк перевёл на другой свой счёт (`transfer_out`), а в ZenMoney — расход (превратить в перевод)

Правила: пара — тот же тип, та же валюта и сумма, дата ±3 дня (по дате транзакции или проводки);
сначала точные пары, потом с допуском max(0.05, 3%) — ZenMoney обычно выше банка на 1–3%: в приложении видна
блокировка по курсу на момент авторизации, а банк рассчитывает по итоговому. Пара одна на одну, жадно по близости даты.
Только stdlib.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal

TOL_DAYS = 3


def D(x) -> Decimal:
    return Decimal(str(x))


def dt(s: str) -> date:
    return date.fromisoformat(s)


def zen_ops(zen: dict, acct_by_ccy: dict, adjust_cat: str | None):
    """Операции ZenMoney → плоские записи, привязанные к счетам FF."""
    ff_ids = set(acct_by_ccy.values())
    refs = (zen.get("references") or {})
    accts = refs.get("accounts") or {}
    cats = refs.get("categories") or {}
    mers = refs.get("merchants") or {}
    out = []
    for r in zen.get("data", []):
        inc, exp = r.get("income"), r.get("expense")
        touches = [s for s in (inc, exp) if s and s.get("accountId") in ff_ids]
        if not touches:
            continue
        cat = cats.get(r.get("categoryId")) or {}
        cname = cat.get("name", "")
        parent = (cats.get(cat.get("parentId")) or {}).get("name") if cat.get("parentId") else None
        is_adj = bool(adjust_cat and r.get("categoryId") == adjust_cat) or "орректиров" in (r.get("comment") or "") or "орректиров" in cname
        kind = "transfer" if inc and exp else ("income" if inc else "expense")
        def side(s):
            if not s:
                return None
            a = accts.get(s["accountId"], {})
            return {"account": s["accountId"], "ccy": a.get("instrument"), "amount": D(s["amount"]), "ff": s["accountId"] in ff_ids}
        out.append({"id": r["id"], "date": r["date"], "kind": kind, "in": side(inc), "out": side(exp), "comment": r.get("comment"),
                    "category": cname or None, "category_path": (f"{parent}/{cname}" if parent and cname else (cname or None)), "category_id": r.get("categoryId"),
                    "tag_ids": r.get("tagIds") or [], "merchant_id": r.get("merchantId"), "merchant": (mers.get(r.get("merchantId")) or {}).get("name") if r.get("merchantId") else None,
                    "original_payee": r.get("originalPayee"),
                    "source": r.get("source"), "adjustment": is_adj, "used": False})
    return out


def _near(bank_dates, zdate):
    return min(abs((dt(zdate) - dt(d)).days) for d in bank_dates)


def _try(bank_amt: Decimal, zen_amt: Decimal, exact: bool) -> bool:
    diff = abs(bank_amt - zen_amt)
    if exact:
        return diff <= Decimal("0.005")
    return diff <= max(Decimal("0.05"), bank_amt * Decimal("0.03"))


def compare(ops: dict, zen: dict, acct_by_ccy: dict, date_from=None, date_to=None, adjust_cat=None, with_transfer_out=False, bank_account=None) -> dict:
    zs = zen_ops(zen, acct_by_ccy, adjust_cat)
    ff_ids = set(acct_by_ccy.values())
    inwin = lambda d: (not date_from or d >= date_from) and (not date_to or d <= date_to)
    types = ("expense", "refund", "transfer", "topup") + (("transfer_out",) if with_transfer_out else ())
    bank = [o for o in ops["operations"] if o["type"] in types and inwin(o["date"]) and (not bank_account or o.get("account") == bank_account)]
    zs = [z for z in zs if inwin(z["date"])]
    res = {"matched": [], "differs": [], "date_shift": [], "merged": [], "partial_transfer": [], "missing_in_zen": [], "missing_in_bank": [], "topup_currency": [], "to_other_account": [], "expense_vs_transfer": []}

    def dates(o):
        return [o["date"], o.get("booking_date") or o["date"]]

    def claim(o, pred, key_amt, exact):
        best = None
        for z in zs:
            if z["used"] or not pred(z):
                continue
            if not _try(key_amt(o), key_amt(z, True), exact):
                continue
            nd = _near(dates(o), z["date"])
            if nd > TOL_DAYS:
                continue
            if best is None or nd < best[0]:
                best = (nd, z)
        return best[1] if best else None

    def match_fn(o):
        t, c = o["type"], o.get("currency")
        if t == "expense":
            return (lambda z: z["kind"] == "expense" and z["out"]["ff"] and z["out"]["ccy"] == c), (lambda x, z=False: D(x["amount"]) if not z else x["out"]["amount"])
        if t == "refund":
            return (lambda z: z["kind"] == "income" and z["in"]["ff"] and z["in"]["ccy"] == c), (lambda x, z=False: D(x["amount"]) if not z else x["in"]["amount"])
        if t == "topup":
            return (lambda z: z["in"] and z["in"]["ff"] and z["in"]["ccy"] == c and (z["kind"] == "income" or not z["out"]["ff"])), (lambda x, z=False: D(x["amount"]) if not z else x["in"]["amount"])
        return None, None

    for exact in (True, False):
        for o in bank:
            if o.get("_done") or o["type"] == "transfer_out":
                continue
            if o["type"] == "transfer":
                f, t = o["from"], o["to"]
                z = None
                for cand in zs:
                    if cand["used"] or cand["kind"] != "transfer":
                        continue
                    if cand["out"]["ccy"] != f["currency"] or cand["in"]["ccy"] != t["currency"]:
                        continue
                    if not (_try(D(f["amount"]), cand["out"]["amount"], exact) and _try(D(t["amount"]), cand["in"]["amount"], exact)):
                        continue
                    if _near(dates(o), cand["date"]) <= TOL_DAYS:
                        z = cand
                        break
            else:
                pred, key = match_fn(o)
                z = claim(o, pred, key, exact)
            if z:
                z["used"] = True
                o["_done"] = True
                rec = {"bank": _brief(o), "zen": _zbrief(z)}
                (res["matched"] if exact else res["differs"]).append(rec)

    # пополнения: ZenMoney зачислил на FF другую валюту
    for o in bank:
        if o.get("_done") or o["type"] != "topup":
            continue
        for z in zs:
            if z["used"] or not (z["in"] and z["in"]["ff"]) or z["in"]["ccy"] == o["currency"]:
                continue
            flat = z["kind"] == "income" or (z["out"] and not z["out"]["ff"] and z["out"]["amount"] == z["in"]["amount"])  # одна и та же сумма с двух сторон — «халтурная» запись в чужой валюте
            if _near(dates(o), z["date"]) <= TOL_DAYS and flat:
                z["used"] = True
                o["_done"] = True
                implied = (z["in"]["amount"] / D(o["amount"])).quantize(Decimal("0.01")) if z["in"]["amount"] and D(o["amount"]) else None
                res["topup_currency"].append({"bank": _brief(o), "zen": _zbrief(z), "implied_rate": str(implied), "note":
                                              f'банк зачислил {o["amount"]} {o["currency"]}, ZenMoney — {z["in"]["amount"]} {z["in"]["ccy"]}'})
                break

    # дата разошлась: сумма до копейки, окно до 45 дней
    for z in zs:
        if z["used"] or z["kind"] not in ("expense", "income"):
            continue
        side = z["out"] if z["kind"] == "expense" else z["in"]
        want = "expense" if z["kind"] == "expense" else "refund"
        cands = [o for o in bank if not o.get("_done") and o["type"] == want and o["currency"] == side["ccy"]
                 and abs(D(o["amount"]) - side["amount"]) <= Decimal("0.005") and abs((dt(z["date"]) - dt(o["date"])).days) <= (120 if side["amount"] >= 50 else 45)]
        if cands:
            o = min(cands, key=lambda o: abs((dt(z["date"]) - dt(o["date"])).days))
            z["used"] = o["_done"] = True
            res["date_shift"].append({"bank": _brief(o), "zen": _zbrief(z), "days": (dt(z["date"]) - dt(o["date"])).days})

    # несколько покупок банка одного места = одна операция ZenMoney
    def place_key(o):
        return ((o.get("merchant") or {}).get("name") or "?").split()[0].upper().rstrip("*")
    for z in zs:
        if z["used"] or z["kind"] != "expense":
            continue
        pool = [o for o in bank if not o.get("_done") and o["type"] == "expense" and o["currency"] == z["out"]["ccy"]
                and abs((dt(z["date"]) - dt(o["date"])).days) <= 45]
        groups: dict = {}
        for o in pool:
            groups.setdefault(place_key(o), []).append(o)
        for key, g in groups.items():
            g = sorted(g, key=lambda o: abs((dt(z["date"]) - dt(o["date"])).days))[:16]
            hit = _subset(g, z["out"]["amount"], z["date"])
            if hit and len(hit) > 1:
                z["used"] = True
                for o in hit:
                    o["_done"] = True
                res["merged"].append({"zen": _zbrief(z), "bank": [_brief(o) for o in hit], "place": key,
                                      "diff": str(z["out"]["amount"] - sum((D(o["amount"]) for o in hit), Decimal(0)))})
                break

    # перевод: совпала одна сторона
    for o in bank:
        if o.get("_done") or o["type"] != "transfer":
            continue
        f, t = o["from"], o["to"]
        for z in zs:
            if z["used"] or z["kind"] != "transfer" or _near(dates(o), z["date"]) > TOL_DAYS + 4:
                continue
            ok_out = z["out"]["ccy"] == f["currency"] and _try(D(f["amount"]), z["out"]["amount"], False)
            ok_in = z["in"]["ccy"] == t["currency"] and _try(D(t["amount"]), z["in"]["amount"], False)
            if ok_out != ok_in:
                z["used"] = o["_done"] = True
                res["partial_transfer"].append({"bank": _brief(o), "zen": _zbrief(z), "matched_side": "списание" if ok_out else "зачисление"})
                break

    # покупка/перевод банка, который в ZenMoney лежит ПЕРЕВОДОМ на другой счёт (проездная карта, свой депозит): сумма и дата те же
    for o in bank:
        if o.get("_done") or o["type"] not in ("expense", "transfer_out"):
            continue
        for exact in (True, False):
            # ближайшая по дате, а не первая попавшаяся: одинаковые суммы в соседние дни иначе перекрещиваются (Т-Банк, 10 000 ₽ 07.10 и 11.10)
            z = min((z for z in zs if not z["used"] and z["kind"] == "transfer" and z["out"]["ff"] and not z["in"]["ff"] and z["out"]["ccy"] == o["currency"]
                     and _try(D(o["amount"]), z["out"]["amount"], exact) and _near(dates(o), z["date"]) <= TOL_DAYS), key=lambda z: _near(dates(o), z["date"]), default=None)
            if z:
                z["used"] = o["_done"] = True
                res["to_other_account"].append({"bank": _brief(o), "zen": _zbrief(z), "note": f'банк: {"покупка" if o["type"] == "expense" else "перевод"}; ZenMoney: перевод на другой счёт'})
                break

    # обратный случай: банк перевёл на другой свой счёт (СБП себе, между счетами), а в ZenMoney записан расход — превратить в перевод
    for o in bank:
        if o.get("_done") or o["type"] != "transfer_out":
            continue
        for exact in (True, False):
            z = min((z for z in zs if not z["used"] and z["kind"] == "expense" and z["out"]["ff"] and z["out"]["ccy"] == o["currency"]
                     and _try(D(o["amount"]), z["out"]["amount"], exact) and _near(dates(o), z["date"]) <= TOL_DAYS), key=lambda z: _near(dates(o), z["date"]), default=None)
            if z:
                z["used"] = o["_done"] = True
                res["expense_vs_transfer"].append({"bank": _brief(o), "zen": _zbrief(z), "note": "банк: перевод на другой счёт; ZenMoney: расход"})
                break

    for o in bank:
        if not o.get("_done"):
            res["missing_in_zen"].append(_brief(o))
    for z in zs:
        if not z["used"]:
            res["missing_in_bank"].append(dict(_zbrief(z), adjustment=z["adjustment"]))
    def _when(r):
        if "date" in r:
            return r["date"]
        b = r.get("bank")
        return (b[0] if isinstance(b, list) else b)["date"] if b else r["zen"]["date"]
    for lst in res.values():
        lst.sort(key=_when)
    res["summary"] = {k: len(v) for k, v in res.items()}
    res["summary"]["bank_ops"] = len(bank)
    res["summary"]["zen_ops"] = len(zs)
    return res


def _subset(items, target: Decimal, anchor: str, tol=Decimal("0.005")):
    """Подмножество операций банка (2…8 шт.) с суммой = target; из точных берём с меньшим разбросом дат
    вокруг даты ZenMoney. Точной нет — повторяем с допуском 0.02. None, если нет вовсе."""
    items = sorted(items, key=lambda o: -D(o["amount"]))
    found = []

    def go(i, acc, chosen):
        if len(found) >= 200:
            return
        if abs(acc - target) <= tol and len(chosen) >= 2:
            found.append(list(chosen))
            return
        if i >= len(items) or len(chosen) >= 8 or acc > target + tol:
            return
        chosen.append(items[i])
        go(i + 1, acc + D(items[i]["amount"]), chosen)
        chosen.pop()
        go(i + 1, acc, chosen)

    for t in (tol, Decimal("0.02")):
        found.clear()
        go(0, Decimal(0), [])
        if found:
            return min(found, key=lambda c: (max(abs((dt(anchor) - dt(o["date"])).days) for o in c), len(c)))
    return None


def merge_pages(pages: list[dict]) -> dict:
    """Страницы/выгрузки list_transactions по разным счетам и курсорам → один {data, references}; повторы по id убираются
    (перевод между двумя счетами FF приходит в обеих выгрузках)."""
    data, seen, refs = [], set(), {}
    for pg in pages:
        for r in pg.get("data", []):
            if r["id"] not in seen:
                seen.add(r["id"])
                data.append(r)
        for k, v in (pg.get("references") or {}).items():
            if isinstance(v, dict):
                refs.setdefault(k, {}).update(v)
    return {"data": data, "references": refs}


def _brief(o):
    b = {"id": o["id"], "type": o["type"], "date": o["date"], "currency": o.get("currency")}
    if o["type"] == "transfer":
        b["from"], b["to"] = o["from"], o["to"]
    else:
        b["amount"] = o["amount"]
    if o.get("original"):
        b["original"] = o["original"]
    if o.get("merchant"):
        b["place"] = o["merchant"]["name"]
        if o["merchant"].get("raw"):
            b["raw"] = o["merchant"]["raw"]
    for k in ("kind", "fee_for", "account", "recipient_bank", "counterparty_account"):
        if o.get(k):
            b[k] = o[k]
    return b


def _zbrief(z):
    return {"id": z["id"], "date": z["date"], "kind": z["kind"],
            "out": {"ccy": z["out"]["ccy"], "amount": str(z["out"]["amount"]), "account": z["out"]["account"]} if z["out"] else None,
            "in": {"ccy": z["in"]["ccy"], "amount": str(z["in"]["amount"]), "account": z["in"]["account"]} if z["in"] else None,
            "category": z["category"], "category_path": z.get("category_path"), "category_id": z["category_id"], "tag_ids": z["tag_ids"], "merchant_id": z["merchant_id"],
            "merchant": z.get("merchant"), "original_payee": z.get("original_payee"),
            "source": z["source"], "comment": z["comment"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ops", required=True)
    ap.add_argument("--zen", required=True, nargs="+", help="один или несколько JSON-файлов со страницами list_transactions")
    ap.add_argument("--accounts", required=True, help="RUB=id,USD=id,KZT=id")
    ap.add_argument("--from", dest="dfrom")
    ap.add_argument("--to", dest="dto")
    ap.add_argument("--adjust-category-id")
    ap.add_argument("--with-transfer-out", action="store_true", help="сравнивать и переводы банка на другие счета (transfer_out)")
    ap.add_argument("--bank-account", help="только операции банка этого счёта/договора (поле account): у Т-Банка несколько счетов одной валюты — сравнивать по одному")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    accts = dict(p.split("=", 1) for p in a.accounts.split(","))
    with open(a.ops, encoding="utf-8") as f:
        ops = json.load(f)
    pages = []
    for zf in a.zen:
        with open(zf, encoding="utf-8") as f:
            pages.append(json.load(f))
    zen = merge_pages(pages)
    res = compare(ops, zen, accts, a.dfrom, a.dto, a.adjust_category_id, a.with_transfer_out, a.bank_account)
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
