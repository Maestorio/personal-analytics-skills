#!/usr/bin/env python3
"""Разбор CSV-выписок Райффайзенбанка в строки (решение 2026-11-01).

Выписка — CSV из интернет-банка (UTF-8 с BOM, разделитель «;»): «Дата операции» (с временем) · «Выполнено
банком» · «Номер документа» · суммы в валюте операции и в валюте счёта (поступления / расходы отдельными
колонками) · валюты · «Детали операции (назначение платежа)» · «Номер карты». Один файл = один счёт.

В файле НЕТ ни номера счёта, ни периода, ни остатков, ни итогов. Поэтому:
  * счёт узнаётся по текстам операций (`account_hint`): «Со счета: *NNNNNNN» у списаний, «На счет: *NNNNNNN»
    у зачислений между своими счетами, «р/с 408…» у зарплаты; разные счета в одном файле или ни одного —
    `account_hint = None`, спросить пользователя, какой это счёт;
  * проверки только построчные (без них результат не отдаётся): ровно одна сумма в каждой паре колонок
    (поступление или расход), знак и сумма совпадают между валютой операции и валютой счёта при одной
    валюте, валюта счёта одна на весь файл, даты разбираются; шапка — ровно ожидаемые колонки;
  * сверка остатка — только против ZenMoney: Δ остатка счёта за окно выписки = сумма операций
    (`get_account_balances` на день до начала и на конец).

  parse_raif_statement.py FILE.csv [FILE.csv …] [--out FILE.json]
      JSON: {"statements": [{meta, rows, checks}]}.

В вывод идут тексты операций и номера счетов (личные данные): результат держать локально, в git не класть.
Только stdlib.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation

HEADER = ["Дата операции", "Выполнено банком", "Номер документа", "Сумма в валюте операции (поступления)", "Сумма в валюте операции (расходы)",
          "Валюта операции", "Сумма в валюте счета (поступления)", "Сумма в валюте счета (расходы)", "Валюта счета",
          "Детали операции (назначение платежа)", "Номер карты"]
RE_FROM = re.compile(r"Со счета:\s*\*(\d{4,})")
RE_TO = re.compile(r"На счет:\s*\*(\d{4,})")
RE_RS = re.compile(r"р/с\s*\d{13}(\d{7})\b")


class StatementError(Exception):
    pass


def _read_text(path: str) -> str:
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise StatementError("кодировка файла не узнана (ни UTF-8, ни cp1251)")


def _money(s: str) -> Decimal | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return Decimal(re.sub(r"[\s  ]", "", s).replace(",", "."))
    except InvalidOperation:
        raise StatementError(f"сумма не разбирается: {s!r}")


def parse_text(text: str) -> tuple[list[dict], dict]:
    rd = list(csv.reader(io.StringIO(text), delimiter=";"))
    if not rd or [h.strip() for h in rd[0]] != HEADER:
        raise StatementError("шапка CSV не та (ожидается выписка Райффайзенбанка из интернет-банка)")
    rows, bad = [], []
    for n, r in enumerate(rd[1:], 1):
        if not any(c.strip() for c in r):
            continue
        if len(r) != len(HEADER):
            bad.append(f"строка {n}: {len(r)} колонок вместо {len(HEADER)}")
            continue
        dt, booked, doc, op_in, op_out, op_ccy, acc_in, acc_out, acc_ccy, details, card = [c.strip() for c in r]
        where = f"строка {n} ({dt} {details[:30]})"
        try:
            d = datetime.strptime(dt, "%d.%m.%Y %H:%M")
            b = datetime.strptime(booked, "%d.%m.%Y")
        except ValueError:
            bad.append(f"{where}: дата не разбирается")
            continue
        oi, oo, ai, ao = _money(op_in), _money(op_out), _money(acc_in), _money(acc_out)
        if (oi is None) == (oo is None) or (ai is None) == (ao is None):
            bad.append(f"{where}: нужна ровно одна сумма (поступление или расход)")
            continue
        if (oi is None) != (ai is None):
            bad.append(f"{where}: поступление/расход расходятся между валютой операции и счёта")
            continue
        amt = ai if ai is not None else -ao
        amt_op = oi if oi is not None else -oo
        if amt == 0:
            bad.append(f"{where}: сумма 0")
        if op_ccy == acc_ccy and amt != amt_op:
            bad.append(f"{where}: валюта одна, суммы разные ({amt_op} / {amt})")
        rows.append({"n": n, "date": d.strftime("%d.%m.%Y"), "time": d.strftime("%H:%M"), "booking_date": b.strftime("%d.%m.%Y"), "doc": doc or None,
                     "amount": str(amt), "currency": acc_ccy, "amount_op": str(amt_op), "currency_op": op_ccy,
                     "purpose": re.sub(r"\s+", " ", details).strip(), "card": card.lstrip("*") or None})
    return rows, {"row_errors": bad}


def account_hint(rows: list[dict]) -> tuple[str | None, dict]:
    """Номер счёта файла (последние цифры, как в тексте «*NNNNNNN») по текстам операций. Голоса: «Со счета» у
    списаний, «На счет» у зачислений, «р/с» в зарплате. Один кандидат — он; несколько или ни одного — None."""
    votes: Counter = Counter()
    for r in rows:
        p, out = r["purpose"], r["amount"].startswith("-")
        m = RE_FROM.search(p) if out else RE_TO.search(p)
        if m:
            votes[m[1]] += 1
        m = RE_RS.search(p)
        if m and not out:
            votes[m[1]] += 1
    # один и тот же счёт пишется с разным числом цифр («*6546130», «р/с …0006546130»): кандидаты, где короткий — конец
    # всех остальных, — это один счёт; берём самую короткую запись (её же видно в текстах переводов)
    cands = sorted(votes, key=len)
    if cands and all(c.endswith(cands[0]) for c in cands):
        return cands[0], dict(votes)
    return None, dict(votes)


def parse_statement(path: str) -> dict:
    rows, chk = parse_text(_read_text(path))
    hint, votes = account_hint(rows)
    ccys = {r["currency"] for r in rows}
    if len(ccys) > 1:
        chk["row_errors"].append(f"в файле несколько валют счёта: {sorted(ccys)}")
    dates = sorted(datetime.strptime(r["date"], "%d.%m.%Y") for r in rows)
    meta = {"bank": "raif", "account": hint, "account_votes": votes, "currency": next(iter(ccys)) if len(ccys) == 1 else None, "kind": "current",
            "period_from": dates[0].strftime("%d.%m.%Y") if dates else None, "period_to": dates[-1].strftime("%d.%m.%Y") if dates else None,
            "cards": sorted({r["card"] for r in rows if r["card"]})}
    chk.update(rows=len(rows), ok=not chk["row_errors"] and bool(rows))
    return {"meta": meta, "rows": rows, "checks": chk}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    res = {"statements": []}
    code = 0
    for p in a.csv:
        try:
            st = parse_statement(p)
        except StatementError as e:
            print(f"[blocking] {p}: {e}", file=sys.stderr)
            return 2
        st["file"] = p.rsplit("/", 1)[-1]
        res["statements"].append(st)
        if not st["checks"]["ok"]:
            code = 2
            print(f"[blocking] {st['file']}: проверка не сошлась: {st['checks']['row_errors'][:5]}", file=sys.stderr)
        if not st["meta"]["account"]:
            print(f"[ask] {st['file']}: счёт по текстам не узнан ({st['meta']['account_votes']}) — спросить пользователя", file=sys.stderr)
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
