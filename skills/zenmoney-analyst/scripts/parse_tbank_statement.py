#!/usr/bin/env python3
"""Разбор PDF «Справка о движении средств» Т-Банка в строки (решение 2026-11-01).

Справка — PDF с текстовым слоем (JasperReports), OCR не нужен. Один файл = один договор (карта,
совместный, накопительный счёт); суммы в валюте договора. Таблица: «Дата и время операции» · «Дата
списания» · «Сумма в валюте операции» · «Сумма операции в валюте договора|карты» · «Описание операции» ·
«Номер карты». Разбор по координатам слов (`pdftotext -bbox`): строка начинается с даты в первой колонке,
описание и время переносятся на следующие строки внутри той же ячейки.

Входящего остатка в справке нет — только «Сумма доступного остатка на <дата>» и итоги «Пополнения» /
«Расходы». Поэтому проверки (без них результат не отдаётся):
  1. сумма плюсовых строк в валюте договора = «Пополнения», сумма минусовых = «Расходы» (до копейки);
  2. у каждой строки знак двух сумм один; если валюта операции = валюте договора — суммы равны;
  3. в каждой строке есть дата операции, время, дата списания и обе суммы; валюта узнана.
Остаток сверяется уже с ZenMoney (`get_account_balances` на дату остатка) — у справки его не с чем сравнить.
Не сошлось — `checks.ok = False`, код 2 (blocking), JSON всё равно печатается, чтобы видеть где.

  parse_tbank_statement.py FILE.pdf [FILE.pdf …] [--out FILE.json]
      JSON: {"statements": [{meta, rows, checks}]}.

В вывод идут номер договора, счёта и тексты операций (личные данные): результат держать локально,
в git не класть. ФИО и адрес в `meta` не попадают. Нужен pdftotext (poppler); остальное — stdlib.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from decimal import Decimal

DATE = re.compile(r"\d\d\.\d\d\.\d{4}")
TIME = re.compile(r"\d\d:\d\d")
# символ валюты в колонках сумм → код; незнакомый символ — ошибка проверки 3 (не угадываем)
CURRENCY_SIGNS = {"₽": "RUB", "₸": "KZT", "$": "USD", "€": "EUR", "₾": "GEL", "£": "GBP", "¥": "CNY", "₺": "TRY", "₫": "VND", "฿": "THB",
                  "֏": "AMD", "₼": "AZN", "₹": "INR", "₩": "KRW", "₴": "UAH", "Br": "BYN", "сум": "UZS", "сом": "KGS"}


class StatementError(Exception):
    pass


def read_pages(pdf: str) -> list[list[tuple[float, float, float, float, str]]]:
    """[(xMin, yMin, xMax, yMax, слово)] по страницам."""
    try:
        out = subprocess.run(["pdftotext", "-bbox", pdf, "-"], capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        raise StatementError("нужен pdftotext (poppler): brew install poppler")
    except subprocess.CalledProcessError as e:
        raise StatementError(f"pdftotext не прочитал {pdf}: {e.stderr.strip()[:200]}")
    pages: list[list] = []
    for m in re.finditer(r'<page [^>]*>|<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', out):
        if m.group(0).startswith("<page"):
            pages.append([])
        else:
            pages[-1].append((float(m[1]), float(m[2]), float(m[3]), float(m[4]), html.unescape(m[5])))
    return pages


def read_layout_text(pdf: str) -> str:
    return subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True, check=True).stdout


def _money(s: str) -> Decimal:
    """«-1 234.56», «272 429,83», «+70 000.00» → Decimal."""
    return Decimal(re.sub(r"[\s\u00a0\u202f]", "", s).replace(",", ".").lstrip("+"))


def parse_meta(text: str) -> dict:
    """Шапка справки: банк, договор, счёт, период, доступный остаток, итоги. ФИО и адрес не читаем."""
    def find(pattern, what):
        m = re.search(pattern, text)
        if not m:
            raise StatementError(f"в справке нет поля «{what}»")
        return m

    if not re.search(r"ТБАНК|ТБанк|TBANK", text):
        raise StatementError("это не справка Т-Банка (нет названия банка в шапке)")
    per = find(r"Движение средств за период с (\d\d\.\d\d\.\d{4}) по (\d\d\.\d\d\.\d{4})", "период")
    bal = find(r"Сумма доступного остатка на (\d\d\.\d\d\.\d{4}):\s*(-?[\d \u00a0]+[.,]\d\d)\s*(\S+)", "доступный остаток")
    inc = re.search(r"Пополнения:\s*([\d \u00a0]+[.,]\d\d)", text)
    exp = re.search(r"Расходы:\s*([\d \u00a0]+[.,]\d\d)", text)
    if not (inc and exp):
        raise StatementError("нет итогов «Пополнения» / «Расходы» — справка обрезана?")
    ccy = CURRENCY_SIGNS.get(bal[3])
    if not ccy:
        raise StatementError(f"незнакомая валюта остатка: {bal[3]!r}")
    contract_date = re.search(r"Дата заключения договора:\s*(\d\d\.\d\d\.\d{4})", text)
    head = re.search(r"Сумма операции\s+(?:в\s+)?валюте\s+(договора|карты)|Сумма операции в\s*\n.*?валюте (договора|карты)", text)
    return {
        "bank": "tbank",
        "contract": find(r"Номер договора:\s*(\d+)", "номер договора")[1],
        "account": find(r"Номер лицевого счета:\s*(\d{20})", "номер лицевого счёта")[1],
        "contract_date": contract_date[1] if contract_date else None,
        "currency": ccy,
        "kind": "current",
        "period_from": per[1],
        "period_to": per[2],
        "closing": str(_money(bal[2])),
        "closing_date": bal[1],
        "closing_kind": "available",
        "total_in": str(_money(inc[1])),
        "total_out": str(_money(exp[1])),
        "product": "card" if re.search(r"валюте\s+карты", text) else ("contract" if re.search(r"валюте\s+договора", text) else None),
    }


def _columns(pages) -> dict:
    """Границы колонок по шапке таблицы первой страницы (слова «Дата», «Сумма», «Описание», «Номер»)."""
    for ws in pages:
        try:
            desc = next(w for w in ws if w[4] == "Описание")
        except StopIteration:
            continue
        y = desc[1]
        line = sorted((w for w in ws if abs(w[1] - y) < 3), key=lambda w: w[0])
        xs = {}
        sums = [w[0] for w in line if w[4] == "Сумма"]
        dates = [w[0] for w in line if w[4] == "Дата"]
        num = [w[0] for w in line if w[4] == "Номер"]
        if len(sums) < 2 or len(dates) < 2 or not num:
            raise StatementError("шапка таблицы не узнана (нужны две «Дата», две «Сумма», «Описание», «Номер»)")
        xs.update(op=dates[0], book=dates[1], amt_op=sums[0], amt_acc=sums[1], desc=desc[0], card=num[-1], head_y=y)
        return xs
    raise StatementError("не нашёл шапку таблицы (Описание операции)")


def _col(x: float, c: dict) -> str | None:
    edges = [("op", c["op"]), ("book", c["book"]), ("amt_op", c["amt_op"]), ("amt_acc", c["amt_acc"]), ("desc", c["desc"]), ("card", c["card"])]
    name = None
    for n, left in edges:
        if x >= left - 4:
            name = n
    return name


def _amount(words) -> tuple[str | None, str | None]:
    """Слова ячейки суммы («-6», «357.50», «₽») → («-6357.50», «RUB»). Символ валюты — последнее нечисловое слово."""
    nums = [w[4] for w in words if re.fullmatch(r"[+-]?[\d.,]+", w[4])]
    signs = [w[4] for w in words if not re.fullmatch(r"[+-]?[\d.,]+", w[4])]
    if not nums:
        return None, None
    return "".join(nums), (CURRENCY_SIGNS.get(" ".join(signs)) or CURRENCY_SIGNS.get(signs[-1] if signs else "") or ("?" + " ".join(signs)))


def parse_rows(pages) -> list[dict]:
    c = _columns(pages)
    rows: list[dict] = []
    for ws in pages:
        # конец таблицы на странице: первое слово левее колонки сумм, которое не дата и не время (итоги, подвал)
        heads = [w for w in ws if w[4] == "Описание"]
        top = heads[0][1] + 20 if heads else 0
        body = [w for w in ws if w[1] > top]
        stops = [w[1] for w in body if w[0] < c["amt_op"] - 4 and not (DATE.fullmatch(w[4]) or TIME.fullmatch(w[4]))]
        bottom = min(stops) if stops else float("inf")
        body = [w for w in body if w[1] < bottom - 1]
        starts = sorted({round(w[1], 1) for w in body if _col(w[0], c) == "op" and DATE.fullmatch(w[4])})
        for i, y0 in enumerate(starts):
            y1 = starts[i + 1] if i + 1 < len(starts) else bottom
            cell: dict = {}
            for w in body:
                if y0 - 2 <= w[1] < y1 - 2:
                    col = _col(w[0], c)
                    if col == "card" and not re.fullmatch(r"\d{4}|[—-]", w[4]):
                        col = "desc"  # длинное описание заезжает в колонку карты — там только 4 цифры или «—»
                    cell.setdefault(col, []).append(w)
            for k in cell:
                cell[k].sort(key=lambda w: (round(w[1]), w[0]))
            op = [w[4] for w in cell.get("op", [])]
            book = [w[4] for w in cell.get("book", [])]
            a_op, c_op = _amount(cell.get("amt_op", []))
            a_acc, c_acc = _amount(cell.get("amt_acc", []))
            card = " ".join(w[4] for w in cell.get("card", [])) or None
            rows.append({
                "date": op[0] if op else None, "time": op[1] if len(op) > 1 and TIME.fullmatch(op[1]) else None,
                "booking_date": book[0] if book else None, "booking_time": book[1] if len(book) > 1 and TIME.fullmatch(book[1]) else None,
                "amount_op": a_op, "currency_op": c_op, "amount": a_acc, "currency": c_acc,
                "purpose": re.sub(r"\s+", " ", " ".join(w[4] for w in cell.get("desc", []))).strip(),
                "card": None if card in (None, "—", "-") else card,
            })
    for n, r in enumerate(rows, 1):
        r["n"] = n
    return rows


def check_statement(meta: dict, rows: list[dict]) -> dict:
    bad: list[str] = []
    s_in = s_out = Decimal(0)
    for r in rows:
        where = f'строка {r["n"]} ({r["date"]} {r["purpose"][:30]})'
        if not (r["date"] and r["time"] and r["booking_date"] and r["amount"] and r["amount_op"]):
            bad.append(f"{where}: нет даты/времени/суммы")
            continue
        if r["currency"] != meta["currency"] or (r["currency_op"] or "?").startswith("?"):
            bad.append(f'{where}: валюта не узнана ({r["currency_op"]} / {r["currency"]})')
            continue
        a, ao = _money(r["amount"]), _money(r["amount_op"])
        if (a > 0) != (ao > 0) or a == 0:
            bad.append(f"{where}: знак сумм расходится или сумма 0")
        if r["currency_op"] == r["currency"] and a != ao:
            bad.append(f"{where}: валюта одна, суммы разные ({ao} / {a})")
        if a > 0:
            s_in += a
        else:
            s_out -= a
    checks = {
        "rows": len(rows),
        "credit_sum": str(s_in), "debit_sum": str(s_out),
        "credit_vs_footer": s_in == Decimal(meta["total_in"]),
        "debit_vs_footer": s_out == Decimal(meta["total_out"]),
        "row_errors": bad,
    }
    checks["ok"] = checks["credit_vs_footer"] and checks["debit_vs_footer"] and not bad and len(rows) > 0
    return checks


def parse_statement(pdf: str) -> dict:
    meta = parse_meta(read_layout_text(pdf))
    rows = parse_rows(read_pages(pdf))
    return {"meta": meta, "rows": rows, "checks": check_statement(meta, rows)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pdf", nargs="+")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    res = {"statements": []}
    code = 0
    for p in a.pdf:
        try:
            st = parse_statement(p)
        except StatementError as e:
            print(f"[blocking] {p}: {e}", file=sys.stderr)
            return 2
        st["file"] = p.rsplit("/", 1)[-1]
        res["statements"].append(st)
        if not st["checks"]["ok"]:
            code = 2
            print(f"[blocking] {st['file']}: проверка не сошлась: {st['checks']}", file=sys.stderr)
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
