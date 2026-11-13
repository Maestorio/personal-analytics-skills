#!/usr/bin/env python3
"""План исправлений ZenMoney по результату stmt_compare.py и сборка вызовов записи (Режим C, решение 2026-10-10).

Сам в ZenMoney не пишет: делает (1) пронумерованный план по формату `references/write-mode.md` §2 и
(2) после согласия пользователя — готовые пакеты для `upsert_transactions`, соблюдая ловушки Т1–Т12.

  plan     --cmp FILE --ops FILE --categories FILE --accounts RUB=…,USD=… [--trips FILE] [--places FILE] [--out FILE]
           Номера пунктов стабильны (порядок: даты, затем вид). Что нельзя решить кодом (категория, место,
           откуда пополнение) — поле `needs`; пункт без закрытых `needs` в пакет не попадёт.
  payload  --plan FILE --confirm 1,2,5-9 [--decide FILE]
           Пакеты: создания ≤10 в вызове (новый requestId на пакет), изменения — отдельно. `decide` —
           {"№": {"category": "Имя|id", "tags": [...], "merchantId": "...", "payee": "Имя", "no_payee": true, "from_account": "id",
                  "to_account": "id", "to_amount": 1.0, "plugin_ok": true, "keep": true}}.
           `originalPayee`: с merchantId — исходный текст банка; без — читаемое имя (`payee` или место), сырую
           строку банка не шлёт (Т12). `without_merchant` в ответе — созданные без точки, для «Итога записи».
  places-add --file F --key K --category "Имя" [--merchant "Имя"] [--merchant-id m1_…]
           Словарь постоянных мест (подстрока названия, без регистра). С `--merchant-id` точка проставляется
           сама при следующих импортах; одно имя без ID — только подсказка для поиска.

Виды пунктов: create_expense / create_refund / create_transfer / create_transfer_out / create_topup, fix_to_transfer, fix_date, fix_amount,
fix_topup_currency, fix_transfer, split_merged, fix_place, review (только показать: нет в банке — решает пользователь).
`fix_place` — точка у операции, которая уже есть в ZenMoney (`place_review`): нет точки · перепутана у комиссии и
покупки · расходится со словарём · сырая (имя = текст банка). Запись — только `merchantId` (решение `keep` — оставить).
`places_suggest` в плане — места, у всех операций которых одна точка и одна категория, а словарь их не знает:
предложения для `places-add` (сам план словарь не пишет).
Правки операций плагина (`source: plugin`) с суммой/датой — blocking-предупреждение (Т10).
Только stdlib.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import uuid
from decimal import Decimal

# Общие модули — канон в _shared-references/; в упакованном .skill — в своей scripts/ (pack.sh кладёт по импорту).
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import hub_settings  # noqa: E402

BATCH = 10


def D(x):
    return Decimal(str(x))


# ---------------------------------------------------------------- вспомогательное
def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cat_index(cats: dict):
    by_id = {c["id"]: c for c in cats["data"]}
    by_name: dict = {}
    for c in cats["data"]:
        if c.get("isArchived"):
            continue
        parent = by_id.get(c.get("parentId"))
        by_name.setdefault(c["name"].lower(), []).append(c)
        if parent:
            by_name.setdefault(f'{parent["name"]}/{c["name"]}'.lower(), []).append(c)
    return by_id, by_name


def resolve_category(spec, by_id, by_name):
    if not spec:
        return None, None
    if spec in by_id:
        return spec, None
    hit = by_name.get(str(spec).lower(), [])
    if len(hit) == 1:
        return hit[0]["id"], None
    if not hit:
        return None, f"категория «{spec}» не найдена"
    return None, f"категория «{spec}» неоднозначна ({len(hit)}): уточните «Родитель/Имя»"


def trip_for(date, trips):
    for t in trips or []:
        if t["from"] <= date <= t["to"]:
            return t
    return None


def place_rule(name, places):
    n = (name or "").lower()
    for key, v in (places or {}).items():
        k = key.lower()
        if k.isalnum() and len(k) <= 4:  # короткое слово («PRO») — только целиком, иначе зацепит PROMENADE
            if re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", n):
                return v
        elif k in n:
            return v
    return None


# ---------------------------------------------------------------- точки у операций, которые уже есть в ZenMoney
PLACE_KINDS = ("purchase", "refund", "service", "bank-transfer", "p2p", "fee", "fee-fx", "compensation", None)


def _norm(t) -> str:
    return re.sub(r"[^0-9a-zа-яё]", "", (t or "").lower())


def place_key(name: str) -> str:
    """Ключ словаря мест из названия банка: «PYATEROCHKA 231» → «PYATEROCHKA» (номер магазина — хвост из одних цифр)."""
    toks = (name or "").split()
    while len(toks) > 1 and toks[-1].isdigit():
        toks.pop()
    return " ".join(toks)


def accepted_merchants(accepted) -> set:
    """merchantId, которые пользователь уже признал верными («оставить как есть», «бренд») — audit/accepted.json, проверка C10."""
    items = (accepted or {}).get("items", accepted) if isinstance(accepted, dict) else (accepted or [])
    out = set()
    for x in items or []:
        if isinstance(x, dict) and x.get("check") == "C10":
            out.update(i for i in str(x.get("id", "")).split("|") if i.startswith("m1_"))
    return out


def place_review(cmp: dict, places=None, bank_merchant=None, accepted=None) -> tuple[list[dict], list[dict]]:
    """Пары «банк ↔ ZenMoney» (расходы и возвраты) → (пункты fix_place, предложения в словарь мест).

    Причины пункта (по убыванию уверенности):
      swapped    комиссия банка с точкой места или покупка с точкой банка (синхронизация путает их у покупок в валюте);
      dictionary в словаре мест для этого места другой merchantId;
      no_place   у операции нет точки;
      raw        имя точки = текст банка и похоже на строку банка (без кириллицы либо с номерами, «//», «№»), а словарь эту
                 точку не подтверждал;
                 читаемое имя от синхронизации («МТС», «Юрий Х.») сырым не считается. Верная точка → решение `keep`
                 и запись места в словарь (places-add --merchant-id), чтобы не спрашивать снова.
    Предложение точки: словарь → та же точка у других операций этого места в паре (если одна) → нет (needs merchant).
    Предложения в словарь: место, у всех операций которого одна точка и одна категория, и словарь его не покрывает."""
    pairs = []
    for cls in ("matched", "differs", "date_shift"):
        for r in cmp.get(cls, []):
            b, z = r["bank"], r["zen"]
            if b["type"] in ("expense", "refund") and z["kind"] in ("expense", "income") and b.get("kind") in PLACE_KINDS:
                pairs.append((b, z))
    is_fee = lambda b: b.get("kind") in ("fee", "fee-fx")
    bank_mid = None
    if bank_merchant:
        ids = {z["merchant_id"] for b, z in pairs if z.get("merchant") == bank_merchant and z.get("merchant_id")}
        bank_mid = ids.pop() if len(ids) == 1 else None
    # точки мест по остальным парам: ключ места → {merchantId: имя}
    seen: dict = {}
    for b, z in pairs:
        if b.get("place") and z.get("merchant_id") and not is_fee(b) and z.get("merchant") != bank_merchant:
            seen.setdefault(place_key(b["place"]).upper(), {})[z["merchant_id"]] = z.get("merchant")
    items, flagged = [], set()
    for b, z in pairs:
        name = z.get("merchant")
        rule = place_rule(b.get("place") or "", places) if b.get("place") and not is_fee(b) else None
        reason = sugg = sugg_name = None
        if is_fee(b) and bank_merchant:
            if name != bank_merchant:
                reason, sugg, sugg_name = ("swapped" if z.get("merchant_id") else "no_place"), bank_mid, bank_merchant
        elif bank_merchant and name == bank_merchant and b.get("kind") in ("purchase", "refund"):
            reason = "swapped"
        elif not z.get("merchant_id"):
            reason = "no_place"
        elif rule and rule.get("merchantId") and z.get("merchant_id") != rule["merchantId"]:
            reason, sugg, sugg_name = "dictionary", rule["merchantId"], rule.get("merchant")
        elif (b.get("kind") != "p2p" and z.get("merchant_id") not in (accepted or set()) and (not re.search(r"[а-яё]", name or "", re.I) or re.search(r"\d{5,}|//|№|<", name or ""))
              and _norm(name) in (_norm(z.get("original_payee")), _norm(b.get("place")), _norm(b.get("raw")))
              and not (rule and rule.get("merchantId") == z["merchant_id"])):
            reason = "raw"
        if not reason:
            continue
        flagged.add(z["id"])
        if not sugg and reason in ("swapped", "no_place"):
            if rule and rule.get("merchantId"):
                sugg, sugg_name = rule["merchantId"], rule.get("merchant")
            else:
                cand = seen.get(place_key(b.get("place") or "").upper(), {}) if b.get("place") else {}
                if len(cand) == 1:
                    sugg, sugg_name = next(iter(cand.items()))
        items.append({"kind": "fix_place", "date": z["date"], "zen_id": z["id"], "zen": z, "bank": b, "reason": reason,
                      "merchant_id": sugg, "merchant_name": sugg_name, "merchant_query": None if sugg else (rule or {}).get("merchant") or b.get("place"),
                      "needs": [] if sugg else ["merchant"]})
    # предложения в словарь мест
    groups: dict = {}
    for b, z in pairs:
        if is_fee(b) or not b.get("place") or b.get("kind") == "p2p" or z["id"] in flagged:
            continue
        groups.setdefault(place_key(b["place"]), []).append(z)
    suggest = []
    for key, zs in sorted(groups.items()):
        combos = {(z.get("merchant_id"), z.get("category_id")) for z in zs}
        if len(combos) != 1:
            continue
        mid, cid = combos.pop()
        if not mid or not cid:
            continue
        rule = place_rule(key, places)
        if rule and rule.get("merchantId") == mid:
            continue
        z = zs[0]
        suggest.append({"key": key, "category": z.get("category_path") or z.get("category"), "merchant": z.get("merchant"), "merchantId": mid, "count": len(zs),
                        "replaces": rule or None, "warn": "короткий ключ — сработает только целым словом" if key.isalnum() and len(key) <= 4 else None})
    return items, suggest


# ---------------------------------------------------------------- план
def plan(cmp: dict, ops: dict, cats: dict, accounts: dict, trips=None, places=None, accepted=None) -> dict:
    by_id, by_name = cat_index(cats)
    items = []

    def add(kind, date, **kw):
        items.append(dict(kind=kind, date=date, **kw))

    ops_by_id = {o["id"]: o for o in ops["operations"]}
    for b in cmp["missing_in_zen"]:
        o = ops_by_id.get(b["id"], b)
        d = b["date"]
        if b["type"] in ("expense", "refund"):
            acc = accounts.get(b["currency"])
            rule = place_rule((b.get("place") or ""), places)
            cid, why = resolve_category(rule["category"], by_id, by_name) if rule else (None, None)
            t = trip_for(d, trips)
            needs = []
            if not cid:
                needs.append("category")
            if not b.get("place"):
                needs.append("place")
            add("create_expense" if b["type"] == "expense" else "create_refund", d, bank_id=b["id"], merchant_id=(rule or {}).get("merchantId"), account=acc, currency=b["currency"], amount=b["amount"],
                original=b.get("original") if (b.get("original") or {}).get("currency") != b["currency"] else None,
                place=b.get("place"), raw_merchant=(o.get("merchant") or {}).get("raw"), merchant_query=(rule or {}).get("merchant"),
                category_id=cid, category_hint=(rule or {}).get("category"), tag=({"id": t["tag_id"], "name": t["name"]} if t else None),
                needs=needs, warn=why)
        elif b["type"] == "transfer":
            add("create_transfer", d, bank_id=b["id"], from_=b["from"], to=b["to"], from_account=accounts.get(b["from"]["currency"]), to_account=accounts.get(b["to"]["currency"]), needs=[])
        elif b["type"] == "transfer_out":
            # перевод на другой свой счёт, которого нет в ZenMoney: счёт-получатель называет пользователь (подсказка — банк получателя)
            add("create_transfer_out", d, bank_id=b["id"], account=accounts.get(b["currency"]), currency=b["currency"], amount=b["amount"], needs=["to_account"],
                hint=b.get("recipient_bank") or b.get("counterparty_account") or b.get("kind"))
        elif b["type"] == "topup":
            from datetime import date as _d, timedelta as _td
            dd = _d.fromisoformat(d)
            add("create_topup", d, bank_id=b["id"], account=accounts.get(b["currency"]), currency=b["currency"], amount=b["amount"], needs=["from_account"],
                lookup={"from": str(dd - _td(days=3)), "to": str(dd + _td(days=3)), "comments": ["Алексей"], "hint": "перевод со своего счёта или «Корректировка» на счёте-источнике в эти даты"})

    for r in cmp.get("expense_vs_transfer", []):
        z, b = r["zen"], r["bank"]
        add("fix_to_transfer", z["date"], zen_id=z["id"], zen=z, bank=b, needs=["to_account"], hint=b.get("recipient_bank") or b.get("counterparty_account") or b.get("kind"),
            plugin=(z.get("source") == "plugin"))
    for r in cmp["date_shift"]:
        z = r["zen"]
        add("fix_date", z["date"], zen_id=z["id"], to_date=r["bank"]["date"], zen=z, bank=r["bank"], days=r["days"], needs=[])
    for r in cmp["differs"]:
        z, b = r["zen"], r["bank"]
        add("fix_amount", z["date"], zen_id=z["id"], zen=z, bank=b, needs=[], plugin=(z.get("source") == "plugin"))
    for r in cmp["topup_currency"]:
        z, b = r["zen"], r["bank"]
        add("fix_topup_currency", z["date"], zen_id=z["id"], zen=z, bank=b, implied_rate=r["implied_rate"], to_account=accounts.get(b["currency"]), needs=[])
    for r in cmp["partial_transfer"]:
        z, b = r["zen"], r["bank"]
        add("fix_transfer", z["date"], zen_id=z["id"], zen=z, bank=b, matched_side=r["matched_side"], needs=[])
    for r in cmp["merged"]:
        z = r["zen"]
        add("split_merged", z["date"], zen_id=z["id"], zen=z, parts=r["bank"], diff=r["diff"], needs=[])
    for z in cmp["missing_in_bank"]:
        add("review", z["date"], zen_id=z["id"], zen=z, adjustment=z.get("adjustment"), needs=[])

    # переделка: у записи ZenMoney нет пары, у банка есть непарная покупка той же категории и валюты — правим запись, а не создаём новую
    from datetime import date as _dt
    def _gap(a, b):
        return abs((_dt.fromisoformat(a) - _dt.fromisoformat(b)).days)
    for rv in [i for i in items if i["kind"] == "review" and not i.get("adjustment") and i["zen"]["kind"] == "expense" and i["zen"].get("category_id")]:
        z = rv["zen"]
        cands = [c for c in items if c["kind"] == "create_expense" and c.get("category_id") == z["category_id"] and c["currency"] == z["out"]["ccy"]
                 and _gap(c["date"], z["date"]) <= 90 and not c.get("_taken")]
        if not cands:
            continue
        c = min(cands, key=lambda c: (_gap(c["date"], z["date"]), abs(D(c["amount"]) - D(z["out"]["amount"]))))
        c["_taken"] = True
        rv["kind"], rv["rework"] = "fix_rework", {"to_date": c["date"], "to_amount": c["amount"], "original": c.get("original"), "bank_id": c["bank_id"], "place": c.get("place")}
    items = [i for i in items if not i.get("_taken")]

    place_items, suggest = place_review(cmp, places, ops.get("bank_merchant"), accepted_merchants(accepted))
    items += place_items

    # записи без пары в банке, которые вместе дают 0 (корректировка туда и обратно): скорее лишние, чем пропущенные
    acc_ids = set(accounts.values())
    def _signed(z):
        v = Decimal(0)
        if z.get("in") and z["in"]["account"] in acc_ids:
            v += D(z["in"]["amount"])
        if z.get("out") and z["out"]["account"] in acc_ids:
            v -= D(z["out"]["amount"])
        return v
    revs = [i for i in items if i["kind"] == "review"]
    if len(revs) >= 2:
        best = None
        for mask in range(1, 1 << min(len(revs), 12)):
            grp = [revs[k] for k in range(min(len(revs), 12)) if mask >> k & 1]
            if len(grp) >= 2 and sum((_signed(i["zen"]) for i in grp), Decimal(0)) == 0 and (best is None or len(grp) > len(best)):
                best = grp
        for i in best or []:
            i["net_zero"] = True

    order = {k: i for i, k in enumerate(("create_expense", "create_refund", "create_transfer", "create_transfer_out", "create_topup", "fix_to_transfer", "fix_date", "fix_amount", "fix_topup_currency", "fix_transfer", "fix_rework", "split_merged", "fix_place", "review"))}
    items.sort(key=lambda i: (i["date"], order[i["kind"]]))
    for n, it in enumerate(items, 1):
        it["n"] = n
    return {"items": items, "counts": {k: sum(1 for i in items if i["kind"] == k) for k in order if any(i["kind"] == k for i in items)}, "places_suggest": suggest}


PLACE_REASON = {"swapped": "перепутана (комиссия ↔ покупка)", "dictionary": "по словарю мест другая", "no_place": "нет точки", "raw": "сырая (= текст банка)?"}


def places_table(pl: dict) -> str:
    """Предложения в словарь мест (stmt-places.json): пишутся только командой places-add после «да»."""
    sg = pl.get("places_suggest") or []
    if not sg:
        return ""
    rows = ["| Ключ (текст банка) | Категория | Точка | Операций | Заметка |", "|---|---|---|---|---|"]
    for x in sg:
        note = "; ".join(t for t in (("было: " + (x["replaces"].get("merchant") or x["replaces"].get("category") or "")) if x.get("replaces") else None, x.get("warn")) if t)
        rows.append(f'| {x["key"]} | {x["category"]} | {x["merchant"]} | {x["count"]} | {note} |')
    return "\n".join(rows)


def table(pl: dict) -> str:
    rows = ["| № | Действие | Запись | Поле | Было | Станет |", "|---|---|---|---|---|---|"]
    for it in pl["items"]:
        k, n = it["kind"], it["n"]
        if k in ("create_expense", "create_refund"):
            orig = f' ({it["original"]["amount"]} {it["original"]["currency"]})' if it.get("original") else ""
            need = f' — нужно: {", ".join(it["needs"])}' if it["needs"] else ""
            tag = f' + {it["tag"]["name"]}' if it.get("tag") else ""
            pt = " / точка: из словаря" if it.get("merchant_id") else (f' / точка: найти «{it.get("merchant_query") or it["place"]}»' if it.get("place") else "")
            rows.append(f'| {n} | {"создать (возврат)" if k == "create_refund" else "создать"} | новая, {it["date"]}, {it.get("place") or "место не указано"} | счёт / сумма / категория / точка | — | {it["currency"]} {it["amount"]}{orig} / {it.get("category_hint") or "?"}{tag}{pt}{need} |')
        elif k == "create_transfer":
            rows.append(f'| {n} | создать | перевод {it["date"]} | суммы | — | {it["from_"]["amount"]} {it["from_"]["currency"]} → {it["to"]["amount"]} {it["to"]["currency"]} |')
        elif k == "create_transfer_out":
            rows.append(f'| {n} | создать | перевод {it["date"]} | счёт-получатель / сумма | — | {it["currency"]} {it["amount"]} → ? — нужно: счёт-получатель (банк: {it.get("hint") or "?"}) |')
        elif k == "fix_to_transfer":
            z = it["zen"]
            warn = " ⚠ банковская (plugin): отдельное согласие (Т10, Т14)" if it.get("plugin") else ""
            rows.append(f'| {n} | в перевод | `{it["zen_id"]}` {z["date"]} {z["out"]["amount"]} {z["out"]["ccy"]}, {z.get("category") or "—"} | вид записи | расход | перевод на свой счёт (банк: {it.get("hint") or "?"}) — нужно: счёт-получатель{warn} |')
        elif k == "create_topup":
            rows.append(f'| {n} | создать | пополнение {it["date"]} | счёт-источник / сумма | — | ? → {it["currency"]} {it["amount"]} — нужно: счёт-источник (искать {it["lookup"]["from"]}…{it["lookup"]["to"]}) |')
        elif k == "fix_date":
            rows.append(f'| {n} | изменить | `{it["zen_id"]}` {it["zen"]["out"]["amount"] if it["zen"]["out"] else it["zen"]["in"]["amount"]} {(it["zen"]["out"] or it["zen"]["in"])["ccy"]}, {it["zen"]["category"]} | дата | {it["zen"]["date"]} | {it["to_date"]} ({it["days"]:+d} дн.) |')
        elif k == "fix_amount":
            side = it["zen"]["out"] or it["zen"]["in"]
            warn = " ⚠ банковская (plugin)" if it.get("plugin") else ""
            rows.append(f'| {n} | изменить | `{it["zen_id"]}` {it["zen"]["date"]}, {it["zen"]["category"]} | сумма | {side["amount"]} {side["ccy"]} | {it["bank"]["amount"]} {it["bank"]["currency"]}{warn} |')
        elif k == "fix_topup_currency":
            rows.append(f'| {n} | изменить | `{it["zen_id"]}` {it["zen"]["date"]} | зачисление | {it["zen"]["in"]["amount"]} {it["zen"]["in"]["ccy"]} | {it["bank"]["amount"]} {it["bank"]["currency"]} (курс {it["implied_rate"]}) |')
        elif k == "fix_transfer":
            rows.append(f'| {n} | изменить | `{it["zen_id"]}` {it["zen"]["date"]} | суммы перевода | {it["zen"]["out"]["amount"]} {it["zen"]["out"]["ccy"]} → {it["zen"]["in"]["amount"]} {it["zen"]["in"]["ccy"]} | {it["bank"]["from"]["amount"]} → {it["bank"]["to"]["amount"]}{" , дата " + it["bank"]["date"] if it["bank"]["date"] != it["zen"]["date"] else ""} |')
        elif k == "fix_rework":
            z, rw = it["zen"], it["rework"]
            rows.append(f'| {n} | изменить | `{it["zen_id"]}` {z["category"]}, ваша запись без пары | сумма и дата | {z["out"]["amount"]} {z["out"]["ccy"]}, {z["date"]} | {rw["to_amount"]} {z["out"]["ccy"]}, {rw["to_date"]} (операция банка {rw.get("place") or ""}) |')
        elif k == "split_merged":
            parts = ", ".join(p["amount"] for p in it["parts"])
            rows.append(f'| {n} | разделить | `{it["zen_id"]}` {it["zen"]["date"]} {it["zen"]["out"]["amount"]} {it["zen"]["out"]["ccy"]} | сумма + {len(it["parts"]) - 1} новых | {it["zen"]["out"]["amount"]} | {parts} |')
        elif k == "fix_place":
            z, b = it["zen"], it["bank"]
            side = z["out"] or z["in"]
            new = (it.get("merchant_name") if it.get("merchant_id") else (f'найти «{it.get("merchant_name") or it["merchant_query"]}»' if (it.get("merchant_name") or it.get("merchant_query")) else "спросить"))
            rows.append(f'| {n} | точка: {PLACE_REASON[it["reason"]]} | `{it["zen_id"]}` {z["date"]} {side["amount"]} {side["ccy"]}, {z.get("category") or "—"}; банк: {b.get("place") or b.get("kind")} | точка | {z.get("merchant") or "—"} | {new}{" — нужно: точка" if it["needs"] else ""} |')
        else:
            tag = (" (корректировка баланса)" if it.get("adjustment") else "") + (" — вместе с другими такими дают 0" if it.get("net_zero") else "")
            z = it["zen"]
            rows.append(f'| {n} | на удаление/решение | `{it["zen_id"]}` {z["date"]} {(z["out"] or z["in"])["amount"]} {(z["out"] or z["in"])["ccy"]}, {z["category"] or ("перевод" if z["kind"] == "transfer" else "—")}{tag} | — | нет в банке | вы, в приложении |')
    return "\n".join(rows)


def delete_list(pl: dict) -> str:
    """Что остаётся после всех правок и без пары в банке: пользователь решает/удаляет в приложении (delete_transactions запрещён)."""
    rows = ["| № | Дата | Сумма | Категория | ID | Заметка |", "|---|---|---|---|---|---|"]
    for it in pl["items"]:
        if it["kind"] != "review":
            continue
        z = it["zen"]
        side = z["out"] or z["in"]
        note = "корректировка баланса" if it.get("adjustment") else "в банке такой операции нет"
        rows.append(f'| {it["n"]} | {z["date"]} | {side["amount"]} {side["ccy"]} | {z["category"] or "—"} | `{it["zen_id"]}` | {note}{"; группа даёт 0" if it.get("net_zero") else ""} |')
    return "\n".join(rows)


# ---------------------------------------------------------------- пакеты записи
class Blocking(Exception):
    pass


FULL_ID = re.compile(r"^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|a1_[A-Za-z0-9_-]{23,})$")


def payload(pl: dict, confirm: set, decide: dict, cats: dict, accounts: dict, requests=None) -> dict:
    by_id, by_name = cat_index(cats)
    creates, updates, problems, no_merchant = [], [], [], []
    for it in pl["items"]:
        if it["n"] not in confirm:
            continue
        k = it["kind"]
        dec = decide.get(it.get("bank_id") or "") or decide.get(it.get("zen_id") or "") or decide.get(str(it["n"]), {})  # решения привязаны к операции, а не к номеру (номера сдвигаются)
        if it.get("zen_id") and k != "review" and not FULL_ID.match(it["zen_id"]):
            problems.append(f'№{it["n"]}: ID «{it["zen_id"]}» неполный — писать можно только по полному ID из MCP')
            continue
        if k == "review":
            problems.append(f'№{it["n"]}: «на удаление/решение» — через MCP не пишется')
            continue
        if k in ("create_expense", "create_refund"):
            cid = it.get("category_id")
            if dec.get("category"):
                cid, why = resolve_category(dec["category"], by_id, by_name)
                if why:
                    problems.append(f'№{it["n"]}: {why}')
                    continue
            if not cid:
                problems.append(f'№{it["n"]}: не задана категория')
                continue
            tags = list(dec.get("tags") or ([it["tag"]["id"]] if it.get("tag") else []))
            if cid in tags:
                problems.append(f'№{it["n"]}: тег совпадает с основной категорией (Т3)')
                continue
            if D(it["amount"]) <= 0:
                problems.append(f'№{it["n"]}: сумма ≤ 0 (Т8)')
                continue
            side = {"accountId": it["account"], "amount": float(D(it["amount"]))}
            if it.get("original"):
                side["originalAmount"] = float(D(it["original"]["amount"]))
                side["originalInstrument"] = it["original"]["currency"]
            tx = {"date": it["date"], ("expense" if k == "create_expense" else "income"): side, "categoryId": cid}
            if tags:
                tx["tagIds"] = tags
            mid = dec.get("merchantId") or it.get("merchant_id")
            if mid:
                tx["merchantId"] = mid
            if dec.get("comment"):
                tx["comment"] = dec["comment"]
            # Т12: исходный текст банка — только вместе с merchantId; без точки — читаемое имя, сырую строку не слать
            payee = None if dec.get("no_payee") else (
                (it.get("raw_merchant") or dec.get("payee") or it.get("place")) if mid else (dec.get("payee") or it.get("place")))
            if payee:
                tx["originalPayee"] = payee
            if not mid and not dec.get("no_payee"):
                no_merchant.append({"n": it["n"], "date": it["date"], "amount": it["amount"], "currency": it["currency"],
                                    "bank_text": it.get("raw_merchant") or it.get("place"), "category": dec.get("category") or it.get("category_hint"),
                                    "suggest": dec.get("payee") or it.get("merchant_query") or it.get("place")})
            creates.append(tx)
        elif k == "create_transfer":
            creates.append({"date": it["date"], "expense": {"accountId": it["from_account"], "amount": float(D(it["from_"]["amount"]))},
                            "income": {"accountId": it["to_account"], "amount": float(D(it["to"]["amount"]))}})
        elif k == "create_transfer_out":
            to = dec.get("to_account")
            if not to:
                problems.append(f'№{it["n"]}: не указан счёт-получатель перевода')
                continue
            creates.append({"date": it["date"], "expense": {"accountId": it["account"], "amount": float(D(it["amount"]))},
                            "income": {"accountId": to, "amount": float(D(dec.get("to_amount") or it["amount"]))}})
        elif k == "fix_to_transfer":
            to, z = dec.get("to_account"), it["zen"]
            if not to:
                problems.append(f'№{it["n"]}: не указан счёт-получатель перевода')
                continue
            if it.get("plugin") and not dec.get("plugin_ok"):
                problems.append(f'№{it["n"]}: операция банковского плагина — превращать в перевод только с отдельным согласием (Т10, Т14: plugin_ok)')
                continue
            # Т14: передаём обе стороны; дата не меняется; категория у перевода игнорируется
            updates.append({"id": it["zen_id"], "expense": {"accountId": z["out"]["account"], "amount": float(D(z["out"]["amount"]))},
                            "income": {"accountId": to, "amount": float(D(dec.get("to_amount") or z["out"]["amount"]))}})
        elif k == "create_topup" and dec.get("convert"):
            # пополнение уже записано как «Корректировка» на счёте-источнике: превращаем её в перевод, а не создаём второй расход
            cv = dec["convert"]
            updates.append({"id": cv["zen_id"], "expense": {"accountId": cv["from_account"], "amount": float(D(cv["from_amount"]))},
                            "income": {"accountId": it["account"], "amount": float(D(it["amount"]))}})
        elif k == "create_topup":
            src = dec.get("from_account")
            if not src:
                problems.append(f'№{it["n"]}: не указан счёт-источник пополнения')
                continue
            creates.append({"date": it["date"], "expense": {"accountId": src, "amount": float(D(dec.get("from_amount") or it["amount"]))},
                            "income": {"accountId": it["account"], "amount": float(D(it["amount"]))}})
        elif k == "fix_date":
            updates.append({"id": it["zen_id"], "date": it["to_date"]})  # Т1: стороны не передаём
        elif k == "fix_amount":
            z = it["zen"]
            if it.get("plugin"):
                problems.append(f'№{it["n"]}: операция банковского плагина — сумму не менять (Т10) без отдельного согласия')
                continue
            if z["out"]:
                updates.append({"id": it["zen_id"], "expense": {"accountId": z["out"]["account"], "amount": float(D(it["bank"]["amount"]))}})
            else:
                updates.append({"id": it["zen_id"], "income": {"accountId": z["in"]["account"], "amount": float(D(it["bank"]["amount"]))}})
        elif k == "fix_topup_currency":
            z = it["zen"]
            # Т1: меняем счёт зачисления — передаём пару сторон целиком
            upd = {"id": it["zen_id"], "income": {"accountId": it["to_account"], "amount": float(D(it["bank"]["amount"]))}}
            if z["out"]:
                upd["expense"] = {"accountId": z["out"]["account"], "amount": float(D(z["out"]["amount"]))}
            updates.append(upd)
        elif k == "fix_transfer":
            z, b = it["zen"], it["bank"]
            upd = {"id": it["zen_id"], "expense": {"accountId": z["out"]["account"], "amount": float(D(b["from"]["amount"]))},
                   "income": {"accountId": z["in"]["account"], "amount": float(D(b["to"]["amount"]))}}
            if b["date"] != z["date"]:
                upd["date"] = b["date"]
            updates.append(upd)
        elif k == "fix_rework":
            z, rw = it["zen"], it["rework"]
            side = {"accountId": z["out"]["account"], "amount": float(D(rw["to_amount"]))}
            if rw.get("original") and rw["original"]["currency"] != z["out"]["ccy"]:
                side["originalAmount"], side["originalInstrument"] = float(D(rw["original"]["amount"])), rw["original"]["currency"]
            updates.append({"id": it["zen_id"], "date": rw["to_date"], "expense": side})
        elif k == "fix_place":
            if dec.get("keep"):
                continue  # точка верная — пользователь оставил; её место стоит записать в словарь (places-add), чтобы не спрашивать снова
            mid = dec.get("merchantId") or it.get("merchant_id")
            if not mid:
                problems.append(f'№{it["n"]}: не задана точка (merchantId) — найти search_merchants или создать по согласию')
                continue
            updates.append({"id": it["zen_id"], "merchantId": mid})  # Т4: null не шлём никогда; Т10: точка — метаданные, у операций плагина можно
        elif k == "split_merged":
            z = it["zen"]
            first, rest = it["parts"][0], it["parts"][1:]
            updates.append({"id": it["zen_id"], "expense": {"accountId": z["out"]["account"], "amount": float(D(first["amount"]))}})
            for p in rest:
                tx = {"date": p["date"], "expense": {"accountId": z["out"]["account"], "amount": float(D(p["amount"]))}}
                if z.get("category_id"):
                    tx["categoryId"] = z["category_id"]
                if z.get("tag_ids"):
                    tx["tagIds"] = z["tag_ids"]
                if z.get("merchant_id"):
                    tx["merchantId"] = z["merchant_id"]
                creates.append(tx)
    batches = []
    for i in range(0, len(creates), BATCH):
        batches.append({"tool": "upsert_transactions", "mode": "create", "requestId": (requests or {}).get(len(batches)) or str(uuid.uuid4()), "transactions": creates[i:i + BATCH]})
    for i in range(0, len(updates), BATCH):
        batches.append({"tool": "upsert_transactions", "mode": "update", "transactions": updates[i:i + BATCH]})
    # «Итог записи», п. 2 (write-mode.md §1, шаг 9): созданные операции без merchantId — найти или завести точку
    return {"batches": batches, "problems": problems, "created": len(creates), "updated": len(updates), "without_merchant": no_merchant}


# ---------------------------------------------------------------- словарь мест
def places_add(path, key, category, merchant=None, merchant_id=None):
    data = {}
    if os.path.exists(path):
        data = load_json(path)
    data[key] = {"category": category, **({"merchant": merchant} if merchant else {}), **({"merchantId": merchant_id} if merchant_id else {})}
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".places-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)
    return data


def parse_confirm(s: str) -> set:
    out = set()
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            out |= set(range(int(a), int(b) + 1))
        elif part:
            out.add(int(part))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("plan")
    p1.add_argument("--cmp", required=True)
    p1.add_argument("--ops", required=True)
    p1.add_argument("--categories", required=True)
    p1.add_argument("--accounts", required=True)
    p1.add_argument("--trips")
    p1.add_argument("--places")
    p1.add_argument("--accepted", help="audit/accepted.json: точки, признанные верными (C10), сырыми не считаются")
    p1.add_argument("--out")
    p1.add_argument("--delete-list", help="записать список «на удаление/решение» (markdown)")
    p2 = sub.add_parser("payload")
    p2.add_argument("--plan", required=True)
    p2.add_argument("--confirm", required=True)
    p2.add_argument("--decide")
    p2.add_argument("--categories", required=True)
    p2.add_argument("--accounts", required=True)
    p3 = sub.add_parser("places-add")
    p3.add_argument("--file", required=True)
    p3.add_argument("--key", required=True)
    p3.add_argument("--category", required=True)
    p3.add_argument("--merchant")
    p3.add_argument("--merchant-id")
    a = ap.parse_args(argv)
    if a.cmd == "places-add":
        hub_settings.require_ai(a.file, "stmt_propose.py places-add", "словарь мест выписки", zones=("ZenMoney",))   # вход — вывод модели
        places_add(a.file, a.key, a.category, a.merchant, a.merchant_id)
        print(f"ok: {a.key} → {a.category}")
        return 0
    accts = dict(p.split("=", 1) for p in a.accounts.split(","))
    cats = load_json(a.categories)
    if a.cmd == "plan":
        pl = plan(load_json(a.cmp), load_json(a.ops), cats, accts, load_json(a.trips) if a.trips else None, load_json(a.places) if a.places else None,
                  load_json(a.accepted) if a.accepted else None)
        if a.out:
            with open(a.out, "w", encoding="utf-8") as f:
                json.dump(pl, f, ensure_ascii=False, indent=1)
        print(table(pl))
        print("\n" + json.dumps(pl["counts"], ensure_ascii=False))
        if pl.get("places_suggest"):
            print("\nВ словарь мест (после «да» — places-add):\n" + places_table(pl))
        if a.delete_list:
            with open(a.delete_list, "w", encoding="utf-8") as f:
                f.write(delete_list(pl))
        return 0
    res = payload(load_json(a.plan), parse_confirm(a.confirm), load_json(a.decide) if a.decide else {}, cats, accts)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 2 if res["problems"] and not res["batches"] else 0


if __name__ == "__main__":
    sys.exit(main())
