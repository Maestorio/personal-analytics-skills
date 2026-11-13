#!/usr/bin/env python3
"""Подвязка счетов банка к счетам ZenMoney по названию и валюте — без номера счёта (решение 2026-10-11).

Пользователю не нужно знать и вводить IBAN: счёт ZenMoney выбирается по трём признакам —
  1. в названии счёта или в названии банка-учреждения (`institution.name`) есть метка банка (`account_patterns` банка в `stmt_import.BANKS`: BOG → «BOG», FF → «FF»);
  2. валюта счёта (`instrument`) = валюта из выписки;
  3. счёт не депозитный (`isSavings`) и не архивный.
Результат по каждой валюте: один счёт — берём; несколько — `ambiguous` (спросить пользователя, не угадывать);
ни одного — `missing` (для транзитной валюты FF это нормально). Депозитные счета банка отдаются отдельно
(`savings`) — нужны для сверки переводов «на депозит».

  stmt_accounts.py --list FILE --bank bog --currencies GEL,USD,EUR [--out FILE]
      FILE — ответ MCP list_accounts. Печатает JSON и строку для `stmt_compare.py --accounts`.
      `--iban` — IBAN из выписки: по `externalIds` счёта видно, тот ли это счёт (депозит `0830` ≠ выписка `…0831`).
      `--contract` — то же для номера договора (Т-Банк): из нескольких счетов одной валюты, включая накопительные,
      выбирается тот, у кого в `externalIds` последние 4 цифры договора.

Страховка от неверной подвязки — сверка остатка: `check_balances` сравнивает остаток банка на конец выписки
с остатком счёта ZenMoney (get_account_balances, граница end) по каждой валюте; не сошлось — подвязка неверна
или в ZenMoney расхождение. Только stdlib.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def iban_check(account: dict, iban: str | None) -> str:
    """Конец IBAN против `externalIds` счёта ZenMoney: «2USD» = последняя цифра IBAN + валюта, «0830» = последние 4 цифры.
    match / mismatch / unknown (нет IBAN или externalIds в незнакомом виде) — mismatch значит «это другой счёт банка»."""
    if not iban:
        return "unknown"
    ccy = account.get("instrument") or ""
    verdict = "unknown"
    for t in account.get("externalIds") or []:
        if re.fullmatch(r"\d{4}", t):
            if iban[-4:] == t:
                return "match"
            verdict = "mismatch"
        elif re.fullmatch(r"\d[A-Z]{3}", t) and t[1:] == ccy:
            if iban[-1] == t[0]:
                return "match"
            verdict = "mismatch"
    return verdict


def resolve(list_accounts: dict, patterns: list[str], currencies: list[str], iban: str | None = None) -> dict:
    rx = re.compile("|".join(f"(?:{p})" for p in patterns), re.I)
    mine = [a for a in list_accounts.get("data", []) if rx.search(f'{a.get("name") or ""} | {(a.get("institution") or {}).get("name") or ""}') and not a.get("isArchived")]
    out = {"accounts": {}, "ambiguous": {}, "missing": [], "savings": {}, "iban_check": {}}
    for c in currencies:
        cur = [a for a in mine if a.get("instrument") == c]
        plain = [a for a in cur if not a.get("isSavings") and a.get("type") != "deposit"]
        sav = [a for a in cur if a not in plain]
        if sav:
            out["savings"][c] = [{"id": a["id"], "name": a["name"], "iban_check": iban_check(a, iban)} for a in sav]
        # несколько счетов одного банка в одной валюте (у Т-Банка карта, совместный и накопительный — все RUB):
        # счёт выписки — тот, у кого в externalIds последние 4 цифры номера (IBAN или договора), включая накопительные
        by_no = [a for a in plain + sav if iban_check(a, iban) == "match"] if iban else []
        if len(by_no) == 1 and (len(plain) != 1 or by_no[0] is not plain[0]):
            out["accounts"][c] = by_no[0]["id"]
            out["iban_check"][c] = "match"
        elif len(plain) == 1:
            out["accounts"][c] = plain[0]["id"]
            out["iban_check"][c] = iban_check(plain[0], iban)
        elif plain:
            out["ambiguous"][c] = [{"id": a["id"], "name": a["name"]} for a in plain]
        else:
            out["missing"].append(c)
    return out


def check_balances(statement_closing: dict, zen_balances: dict) -> list[str]:
    """Остаток банка на конец выписки против остатка счёта ZenMoney. {ccy: "11.51"} против {ccy: 11.51}. Пусто — всё сошлось."""
    bad = []
    for c, zb in zen_balances.items():
        bank = Decimal(str(statement_closing.get(c, "0")))
        if bank != Decimal(str(zb)):
            bad.append(f"{c}: банк {bank}, ZenMoney {zb}")
    return bad


def main(argv=None) -> int:
    import stmt_import
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--list", required=True, help="JSON ответа list_accounts")
    ap.add_argument("--bank", required=True, choices=sorted(stmt_import.BANKS))
    ap.add_argument("--currencies", required=True)
    ap.add_argument("--iban", "--contract", dest="iban", help="IBAN или номер договора из выписки: сверит с externalIds счетов (другой счёт банка → mismatch); при нескольких счетах одной валюты выберет совпавший")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    with open(a.list, encoding="utf-8") as f:
        res = resolve(json.load(f), stmt_import.BANKS[a.bank]["account_patterns"], [c for c in a.currencies.split(",") if c], a.iban)
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    print("--accounts " + ",".join(f"{c}={i}" for c, i in res["accounts"].items()), file=sys.stderr)
    for c, v in res["ambiguous"].items():
        print(f"[ask] {c}: несколько счетов — " + "; ".join(x["name"] for x in v), file=sys.stderr)
    for c, v in res["iban_check"].items():
        if v == "mismatch":
            print(f"[ask] {c}: externalIds счёта не совпадают с IBAN выписки — это другой счёт банка", file=sys.stderr)
    return 2 if res["ambiguous"] or "mismatch" in res["iban_check"].values() else 0


if __name__ == "__main__":
    sys.exit(main())
