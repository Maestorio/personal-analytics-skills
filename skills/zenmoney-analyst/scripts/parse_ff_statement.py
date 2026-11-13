#!/usr/bin/env python3
"""Разбор PDF-выписок Freedom Bank Kazakhstan (FF) в строки (решение 2026-10-10).

Выписки FF — PDF с текстовым слоем (mPDF), OCR не нужен. Таблица узкая: сумма с тысячами
переносится («1» / «000.00»), назначение платежа идёт в несколько строк, поэтому разбор
по тексту ненадёжен. Скрипт берёт координаты слов (`pdftotext -bbox`): строки таблицы —
по вертикальным разрывам, «Дебет»/«Кредит» — по колонкам из шапки таблицы.

Проверки (без них результат не отдаётся — это единственная гарантия точности):
  1. число строк = «Итого: N» внизу выписки;
  2. сумма дебетов и кредитов = итоговой строке выписки;
  3. входящий остаток + кредиты − дебеты = исходящий остаток.
Не сошлось хоть одно — код 2 (blocking), JSON всё равно печатается с `checks`, чтобы видеть где.

  parse_ff_statement.py FILE.pdf [FILE.pdf …] [--out FILE.json]
      Разобрать выписки. JSON: {"statements": [{meta, rows, checks}]}.
      Одна выписка = один счёт (текущий или депозитный) одной валюты.

В вывод идут IBAN счетов и тексты операций (личные данные): файл-результат держать
локально (scratchpad / вне git), в репозиторий не класть. ФИО клиента и ИИН в вывод не
попадают. Требует `pdftotext` (poppler). Остальное — stdlib.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from decimal import Decimal

AMOUNT_TOKEN = re.compile(r"\d{1,3}|\d+\.\d\d")  # «1» (тысячи) или «487.85»; 6-значные коды — не сумма
DATE = re.compile(r"\d\d\.\d\d\.\d{4}")
ROW_GAP = 12.0  # между строками таблицы ≥16 pt, внутри строки ≤8 pt


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
    return Decimal(re.sub(r"[\s ]", "", s))


def _balance(layout_text: str, which: str):
    """Остаток из шапки. У пустой выписки (нет ни одной операции) банк оставляет поле без числа — вернём None."""
    m = re.search(which + r" остаток:[ \t ]*([\d  ]+\.\d\d)?", layout_text)
    if not m:
        raise StatementError(f"в шапке выписки нет поля «{which.lower()} остаток»")
    return str(_money(m[1])) if m[1] else None


def parse_meta(layout_text: str) -> dict:
    """Шапка выписки: счёт, валюта, тип, период, остатки. ФИО и ИИН не читаем."""
    def find(pattern, what):
        m = re.search(pattern, layout_text)
        if not m:
            raise StatementError(f"в шапке выписки нет поля «{what}»")
        return m

    kind_m = find(r"Выписка по (текущему|депозитному) счету за период с (\d\d\.\d\d\.\d{4}) по (\d\d\.\d\d\.\d{4})", "тип/период")
    return {
        "account": find(r"Счет:\s*(KZ\w+)", "счёт")[1],
        "currency": find(r"Валюта:\s*([A-Z]{3})", "валюта")[1],
        "kind": "current" if kind_m[1] == "текущему" else "deposit",
        "period_from": kind_m[2],
        "period_to": kind_m[3],
        "opening": _balance(layout_text, "Входящий"),
        "closing": _balance(layout_text, "Исходящий"),
    }


def _join_amount(words) -> str:
    # тысячи и остаток лежат друг под другом (1 / 000.00): сверху вниз без пробела
    return "".join(w[4] for w in sorted(words, key=lambda w: (w[1], w[0])))


def parse_rows(pages) -> tuple[list[dict], dict]:
    """Строки таблицы и итоговая строка выписки {count, debit, credit}."""
    head = pages[0]
    try:
        deb_h = next(w for w in head if w[4] == "Дебет")
        cred_h = next(w for w in head if w[4] == "Кредит")
        doc_h = next(w for w in head if w[4] == "документа")
        end_h = max(w[1] for w in head if w[4].lower() == "платежа")
    except StopIteration:
        raise StatementError("не нашёл шапку таблицы (Дебет / Кредит / Назначение платежа)")
    deb_c = (deb_h[0] + deb_h[2]) / 2
    cred_c = (cred_h[0] + cred_h[2]) / 2
    split = (deb_c + cred_c) / 2
    amount_hi = cred_h[2] + 12  # правее зоны «Кредит» — текст назначения (в разных файлах колонки разной ширины)
    doc_c = (doc_h[0] + doc_h[2]) / 2
    rows: list[dict] = []
    total = None
    for pi, ws in enumerate(pages):
        body = sorted((w for w in ws if w[1] > (end_h + 8 if pi == 0 else 0)), key=lambda w: w[1])
        clusters, cur = [], []
        for w in body:
            if cur and w[1] - cur[-1][1] > ROW_GAP:
                clusters.append(cur)
                cur = []
            cur.append(w)
        if cur:
            clusters.append(cur)
        for c in clusters:
            dates = [w for w in c if DATE.fullmatch(w[4]) and w[0] < 80]
            deb = _join_amount([w for w in c if deb_h[0] - 25 <= (w[0] + w[2]) / 2 < split and AMOUNT_TOKEN.fullmatch(w[4])])
            cred = _join_amount([w for w in c if split <= (w[0] + w[2]) / 2 < amount_hi and AMOUNT_TOKEN.fullmatch(w[4])])
            it = next((w for w in c if w[4] == "Итого:"), None)
            if it:
                # N — слово сразу правее «Итого:» на той же строке (суммы выше/ниже — это тысячи колонок)
                near = sorted((w for w in c if w[0] > it[2] and abs(w[1] - it[1]) < 6 and w[4].isdigit()), key=lambda w: w[0])
                total = {"count": int(near[0][4]) if near else None, "debit": deb or "0", "credit": cred or "0"}
                continue
            if len(dates) != 1:
                continue  # шапка/подвал страницы
            # длинные тексты (место платежа) центрируются и заезжают влево, под колонки сумм — берём всё правее счёта контрагента, кроме самих сумм
            is_text = lambda w: w[0] >= deb_h[0] - 25 and not (deb_h[0] - 25 <= (w[0] + w[2]) / 2 < amount_hi and AMOUNT_TOKEN.fullmatch(w[4]))
            text_ws = sorted((w for w in c if is_text(w)), key=lambda w: (round(w[1] / 4), w[0]))
            rows.append({
                "date": dates[0][4],
                "doc": "".join(w[4] for w in c if abs((w[0] + w[2]) / 2 - doc_c) < 22 and re.fullmatch(r"\d+", w[4])),
                "debit": deb or None,
                "credit": cred or None,
                "counterparty_account": " ".join(w[4] for w in c if w[0] < deb_h[0] - 10 and w[4].startswith("KZ")) or None,
                "purpose": re.sub(r"\s+", " ", " ".join(w[4] for w in text_ws)).strip(),
            })
    if total is None:
        raise StatementError("нет итоговой строки «Итого:» — выписка обрезана?")
    return rows, total


def check_statement(meta: dict, rows: list[dict], total: dict) -> dict:
    sd = sum((_money(r["debit"]) for r in rows if r["debit"]), Decimal(0))
    sk = sum((_money(r["credit"]) for r in rows if r["credit"]), Decimal(0))
    balance = _money(meta["opening"]) + sk - sd
    checks = {
        "rows_vs_footer": len(rows) == total["count"],
        "debit_vs_footer": sd == _money(total["debit"]),
        "credit_vs_footer": sk == _money(total["credit"]),
        "balance": balance == _money(meta["closing"]),
        "rows": len(rows), "footer_rows": total["count"],
        "debit_sum": str(sd), "credit_sum": str(sk),
        "balance_calc": str(balance), "closing": meta["closing"],
    }
    checks["ok"] = all(checks[k] for k in ("rows_vs_footer", "debit_vs_footer", "credit_vs_footer", "balance"))
    return checks


def parse_statement(pdf: str) -> dict:
    meta = parse_meta(read_layout_text(pdf))
    rows, total = parse_rows(read_pages(pdf))
    for k in ("opening", "closing"):
        if meta[k] is None:
            if rows:
                raise StatementError(f"в выписке есть операции, но пустой {'входящий' if k == 'opening' else 'исходящий'} остаток")
            meta[k] = "0.00"  # пустая выписка: ни операций, ни остатков
    return {"meta": meta, "rows": rows, "checks": check_statement(meta, rows, total)}


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
