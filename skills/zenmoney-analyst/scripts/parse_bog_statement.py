#!/usr/bin/env python3
"""Разбор Excel-выписок Bank of Georgia (BOG) в строки (решение 2026-10-11).

Выписка BOG — .xlsx из интернет-банка (листы «Details» и «Transactions»). Один файл = один IBAN,
счёт мультивалютный: колонки GEL / USD / EUR / GBP в одной таблице. Банк сам пишет после каждого
дня строку «Balance» с остатками по всем валютам — это и есть проверка арифметики.

Проверки (без них результат не отдаётся):
  1. после каждой строки «Balance»: входящий остаток + сумма строк = остаток банка — по КАЖДОЙ валюте.
     Исключение — известная причуда банка: в «Balance» валюта без движения за день иногда показана
     как ровно 0, хотя деньги на счёте есть (на реальной выписке 4 из 97 строк). Нулевое показание
     при ненулевом расчёте не ошибка, а запись в `zero_quirk` (видно, где); любое ненулевое
     расхождение — ошибка. Страховка — проверка 2 (исходящий остаток строгий);
  2. исходящий остаток из листа «Details» = входящий + сумма всех строк, по каждой валюте;
  3. каждая строка — ровно одна сумма, валюта колонки совпадает с валютой «Amount» в тексте;
     знак совпадает со словом (Payment/Outgoing — минус, Income/Incoming/Credit — плюс).
Не сошлось — `checks.ok = False`, код 2 (blocking), JSON всё равно печатается, чтобы видеть где.

  parse_bog_statement.py FILE.xlsx [FILE.xlsx …] [--out FILE.json]
      JSON: {"statements": [{meta, rows, checks}]}.

В вывод идут IBAN и тексты операций (личные данные): результат держать локально, в git не
класть. ФИО владельца в `meta` не попадает. Нужен `openpyxl`; остальное — stdlib.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal

CURRENCY_HEADERS = ("GEL", "USD", "EUR", "GBP")
RE_AMOUNT_TEXT = re.compile(r"^\s*(?P<word>[A-Za-z ]+?)\s*-\s*Amount:?\s*(?P<ccy>[A-Z]{3})(?P<amt>[\d,]+(?:\.\d+)?)")
RE_BALANCE = re.compile(r"^(-?[\d,]*\.?\d+)\s*([A-Z]{3})$")
RE_FILTER_DATE = re.compile(r"^(\d\d)/(\d\d)/(\d{4})$")
RE_CARD = re.compile(r"\((\d{4})\)\s*$")
SIGN = {"payment": -1, "outgoing transfer": -1, "income": 1, "incoming transfer": 1, "credit funds": 1}


class StatementError(Exception):
    pass


def _dec(x) -> Decimal:
    return Decimal(str(x).replace(",", "").strip())


def _date(s: str) -> str:
    """dd/mm/yyyy → dd.mm.yyyy (как у остальных банков в скилле)."""
    m = RE_FILTER_DATE.match(str(s).strip())
    if not m:
        raise StatementError(f"дата не в формате дд/мм/гггг: {s!r}")
    return f"{m[1]}.{m[2]}.{m[3]}"


def _pad(r, n=7) -> tuple:
    """openpyxl отдаёт строки разной длины — добиваем до ширины таблицы."""
    return tuple(r) + (None,) * (n - len(r))


def _balances(values) -> dict:
    out = {}
    for v in values:
        m = RE_BALANCE.match(str(v).strip())
        if not m:
            raise StatementError(f"остаток не разобран: {v!r}")
        out[m[2]] = str(_dec(m[1]))
    return out


def parse_details(ws) -> dict:
    """Лист «Details»: счёт, карты, период, остатки по валютам. Владельца не читаем."""
    account, cards, period, opening, closing = None, [], {}, [], []
    section = None
    for r in ws.iter_rows(values_only=True):
        r = _pad(r)
        label, value = (r[0] or "").strip() if isinstance(r[0], str) else None, r[2]
        if label == "Account No:":
            account = str(value).strip()
        elif label in ("Card:", "Filter Date From:", "Filter Date To:", "Starting Balance:", "End Balance:"):
            section = label
        elif label not in (None, ""):
            section = None  # другое поле (например, «Account Owner:»)
        if value in (None, ""):
            continue
        if section == "Card:":
            m = RE_CARD.search(str(value))
            if m:
                cards.append(m[1])
        elif section in ("Filter Date From:", "Filter Date To:") and label == section:
            period["from" if "From" in section else "to"] = _date(value)
        elif section == "Starting Balance:":
            opening.append(value)
        elif section == "End Balance:":
            closing.append(value)
    if not account or "from" not in period or "to" not in period or not opening or not closing:
        raise StatementError("в листе «Details» нет счёта, периода или остатков — это выписка BOG?")
    return {"account": account, "cards": cards, "period_from": period["from"], "period_to": period["to"],
            "opening": _balances(opening), "closing": _balances(closing)}


def parse_transactions(ws) -> tuple[list[dict], list[dict]]:
    """Строки операций и контрольные остатки («Balance» после каждого дня)."""
    it = ws.iter_rows(values_only=True)
    head = next(it, None)
    head = _pad(head) if head else head
    if not head or tuple(head[:2]) != ("Date", "Details") or tuple(head[3:7]) != CURRENCY_HEADERS:
        raise StatementError("шапка листа «Transactions» не «Date | Details | | GEL | USD | EUR | GBP»")
    rows, marks = [], []
    for r in map(_pad, it):
        if all(v is None for v in r):
            continue
        if r[0] == "Balance":
            marks.append({"after_row": len(rows), "balance": {c: str(_dec(v if v is not None else 0)) for c, v in zip(CURRENCY_HEADERS, r[3:7])}})
            continue
        amounts = [(c, v) for c, v in zip(CURRENCY_HEADERS, r[3:7]) if v not in (None, "")]
        rows.append({"n": len(rows), "date": _date(r[0]), "purpose": re.sub(r"\s+", " ", str(r[1] or "")).strip(),
                     "amounts": amounts})
    return rows, marks


def build_rows(raw: list[dict]) -> tuple[list[dict], list[str]]:
    """В общий вид: currency, debit/credit (как у FF), purpose. Нарушения построчных правил — в problems."""
    rows, problems = [], []
    for r in raw:
        if len(r["amounts"]) != 1:
            problems.append(f'строка {r["n"]} ({r["date"]}): сумм {len(r["amounts"])}, нужна ровно одна')
            continue
        ccy, v = r["amounts"][0]
        v = _dec(v)
        m = RE_AMOUNT_TEXT.match(r["purpose"])
        if m:
            sign = SIGN.get(m["word"].strip().lower())
            if m["ccy"] != ccy and "Merchant:" not in r["purpose"]:
                problems.append(f'строка {r["n"]} ({r["date"]}): колонка {ccy}, в тексте {m["ccy"]}')
            if m["ccy"] == ccy and abs(v) != _dec(m["amt"]):
                problems.append(f'строка {r["n"]} ({r["date"]}): сумма {v} ≠ суммы в тексте {m["amt"]}')
            if sign is not None and (v < 0) != (sign < 0):
                problems.append(f'строка {r["n"]} ({r["date"]}): знак суммы {v} не сходится со словом «{m["word"].strip()}»')
        rows.append({"n": r["n"], "date": r["date"], "currency": ccy, "purpose": r["purpose"],
                     "debit": f"{-v:.2f}" if v < 0 else None, "credit": f"{v:.2f}" if v > 0 else None})
    return rows, problems


def check_statement(meta: dict, raw: list[dict], marks: list[dict], problems: list[str]) -> dict:
    ccys = sorted(set(meta["opening"]) | set(meta["closing"]) | set(CURRENCY_HEADERS))
    run = {c: _dec(meta["opening"].get(c, 0)) for c in ccys}
    bad, quirk, mi = [], [], 0
    for i in range(len(raw) + 1):
        if i > 0:
            for c, v in raw[i - 1]["amounts"]:
                run[c] += _dec(v)
        while mi < len(marks) and marks[mi]["after_row"] == i:
            for c, v in marks[mi]["balance"].items():
                if run[c] != _dec(v):
                    (quirk if _dec(v) == 0 else bad).append(f'после строки {i}: {c} посчитано {run[c]}, банк {v}')
            mi += 1
    closing_bad = [f'{c}: посчитано {run[c]}, банк {meta["closing"].get(c, "0")}' for c in ccys if run[c] != _dec(meta["closing"].get(c, 0))]
    checks = {"running_balance": not bad, "closing_balance": not closing_bad, "row_rules": not problems,
              "rows": len(raw), "balance_marks": len(marks), "zero_quirk": quirk, "mismatches": (bad + closing_bad + problems)[:20]}
    checks["ok"] = checks["running_balance"] and checks["closing_balance"] and checks["row_rules"]
    return checks


def parse_statement(path: str) -> dict:
    try:
        import openpyxl
    except ImportError:
        raise StatementError("нужен openpyxl: pip install openpyxl --break-system-packages")
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # выгрузка BOG без стилей — openpyxl ворчит, на данные не влияет
        try:
            wb = openpyxl.load_workbook(path, data_only=True)  # не read_only: у выгрузки BOG нет размеров листа, потоковое чтение режет строки
        except Exception as e:
            raise StatementError(f"не открылся как xlsx: {e}")
    if "Details" not in wb.sheetnames or "Transactions" not in wb.sheetnames:
        raise StatementError("нет листов «Details» и «Transactions» — это выписка BOG?")
    d = parse_details(wb["Details"])
    raw, marks = parse_transactions(wb["Transactions"])
    rows, problems = build_rows(raw)
    meta = {**d, "kind": "current", "currencies": [c for c in CURRENCY_HEADERS if c in d["opening"] or c in d["closing"]], "currency": "multi"}
    return {"meta": meta, "rows": rows, "checks": check_statement(meta, raw, marks, problems)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("xlsx", nargs="+")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    res, code = {"statements": []}, 0
    for p in a.xlsx:
        try:
            st = parse_statement(p)
        except StatementError as e:
            print(f"[blocking] {p}: {e}", file=sys.stderr)
            return 2
        st["file"] = p.rsplit("/", 1)[-1]
        res["statements"].append(st)
        if not st["checks"]["ok"]:
            code = 2
            print(f"[blocking] {st['file']}: проверка не сошлась: {st['checks']['mismatches']}", file=sys.stderr)
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
