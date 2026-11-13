#!/usr/bin/env python3
"""
lint_numbers.py

Линт черновика ответа: каждая сумма, количество и целевая доля СДЕЛКИ в строке с действием должны
найтись в выводе скриптов прогона (`sizing_to_target.py`, `gate_aware_sizing.py`, `stress_digest.py` и др.).
Числа сделок приходят из скриптов, а не из арифметики модели. Узкие проверки `gate_aware_sizing.py --lint-draft`
(запрещённая нотация, сумма докупки акции без «База докупки») остаются отдельно; этот линт их дополняет.

CLI:
    python3 lint_numbers.py --draft <черновик.md> --sources <вывод 1> [<вывод 2> …] [--json]
Источники — текстовые и JSON-выводы скриптов (сохранённые в файлы). Из них собирается множество чисел.

Что проверяется. Строка-действие содержит оборот сделки в будущем/повелительном виде: докупить/докупка,
купить, добрать, нарастить, продать, сократить, срезать, довести, «до плана N %», либо «если (всё же) N %», либо тикер рядом с «до N %» в строке про долю/вес.
Прошедшее время (докупил, продал) и множественное «докупки» — история, а не предложение: не проверяются.
В такой строке проверяются: (1) суммы в ₽ (`206 376 ₽`, `≈89 900 ₽`, `167 тыс ₽`, `1,2 млн ₽`), кроме цены за единицу и порогов (после «по», «при», «под», «выше», «ниже», «цене», ≥, ≤, <, >); (2) количества (`паёв`, `акций`, `лотов`, `шт`, `бумаг`, `облигаций`);
(3) доля `N %`, названная целью или результатом («до 4 %», «станет 4 %», «→ 4 %», «цель 4 %», «до плана 3 %»).
Строки без действия (факты о фонде, цены, новости, даты) не проверяются.

Правило округления: число черновика совпало, если в источниках есть значение v с |v − x| ≤ g/2, где g —
точность записи в черновике: для дробных — 10^(−знаков после запятой); для целых ≥ 1000 или с «≈»/«~» —
10^(число хвостовых нулей); для остальных целых — 1; при единице «тыс/млн/млрд» — множитель × 10^(−знаков).
Для доли допуск фиксирован ±0,05 пп. Примеры: «≈89 900 ₽» совпадает с 89 912 (g=100); «206 376 ₽» — только
с 206 376 (g=1); «≈16 100 паёв» — с 16 098; «24 акции» — только с 24.

Коды: 0 — чисто; 1 — есть нарушения; 2 — ошибка входа (без traceback). Stdlib only. Read-only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

_SP = "   "
NUM = rf"\d{{1,3}}(?:[{_SP}]\d{{3}})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_UNIT = {"тыс": 1e3, "млн": 1e6, "млрд": 1e9}

SUM_RE = re.compile(rf"(?P<num>{NUM})\s*(?P<unit>тыс|млн|млрд)?\.?\s*(?:₽|руб)", re.IGNORECASE)
QTY_RE = re.compile(
    rf"(?P<num>{NUM})\s*(?:паёв|паев|пая|пай|акци(?:й|и|я|ю)|лот(?:ов|а)?|шт\b|бумаг|облигаци(?:й|и|я|ю))",
    re.IGNORECASE)
SHARE_RE = re.compile(rf"(?P<num>{NUM})\s*%")
_SHARE_CTX = re.compile(r"(?:\bдо\s+|\bстанет|\bстанут|\bбудет|→|->|\bцел\w*|\bесли\s+|\bвсё\s+же)[^\d%]{0,20}$",
                       re.IGNORECASE)
ACTION_RE = re.compile(
    r"\b(?:докупить|докупать|докупай|докупите|докупка(?!м)|купить|добрать|добор|нарастить|нарастим|"
    r"продать|продай|сократить|срезать|довести)|до\s+плана\s+\d[\d.,]*\s*%",
    re.IGNORECASE)
_TICKER_BEFORE_TO_PCT = re.compile(rf"\b[A-Z][A-Z0-9]{{2,6}}\b[^\n]{{0,15}}?\bдо\s+(?:{NUM})\s*%")
_PRICE_CTX = re.compile(r"(?:\bпо|\bпри|\bпод|\bнад|\bвыше|\bниже|\bцен[аеуы]|\bкурс\w*|[≥≤<>])\s*[~≈]?\s*$",
                        re.IGNORECASE)
_NOT_TICKERS = {"NAV", "USD", "EUR", "CNY", "RUB", "ETF", "TER", "ISS", "IMOEX", "RGBI", "MOEX", "KPI"}
_SHARE_WORD = re.compile(r"\bдол[яиюе]\b|\bвес\w*|\bдоли\b", re.IGNORECASE)
_IF_TARGET = re.compile(rf"\bесли\s+(?:всё\s+же\s+|довести\s+(?:до\s+)?)?(?:{NUM})\s*%", re.IGNORECASE)


def _val(tok: str) -> float:
    for c in _SP:
        tok = tok.replace(c, "")
    return float(tok.replace(",", "."))


def _decimals(tok: str) -> int:
    m = re.search(r"[.,](\d+)$", tok)
    return len(m.group(1)) if m else 0


def _granularity(tok: str, unit: str | None, approx: bool) -> float:
    """g — точность записи числа в черновике (см. докстринг)."""
    d = _decimals(tok)
    x = _val(tok)
    mult = _UNIT.get((unit or "").lower(), 1.0)
    if d:
        return mult * 10 ** (-d)
    if unit:
        return mult
    if x >= 1000 or approx:
        n = int(x)
        k = 0
        while n and n % 10 == 0:
            n //= 10
            k += 1
        return 10.0 ** k
    return 1.0


def _numbers_in_text(text: str, out: set[float]) -> None:
    for m in re.finditer(NUM, text):
        out.add(_val(m.group(0)))
    for m in SUM_RE.finditer(text):
        if m.group("unit"):
            out.add(_val(m.group("num")) * _UNIT[m.group("unit").lower()])


def _walk_json(o: Any, out: set[float]) -> None:
    if isinstance(o, bool) or o is None:
        return
    if isinstance(o, (int, float)):
        v = abs(float(o))
        out.add(v)
        if 0 < v < 1:
            out.add(v * 100)
    elif isinstance(o, str):
        _numbers_in_text(o, out)
    elif isinstance(o, dict):
        for v in o.values():
            _walk_json(v, out)
    elif isinstance(o, list):
        for v in o:
            _walk_json(v, out)


def collect_source_numbers(texts: list[str]) -> set[float]:
    out: set[float] = set()
    for t in texts:
        s = t.lstrip()
        if s[:1] in "{[":
            try:
                _walk_json(json.loads(t), out)
                continue
            except ValueError:
                pass
        _numbers_in_text(t, out)
    return out


def _found(x: float, g: float, pool: set[float], tol: float | None = None) -> bool:
    t = (g / 2 if tol is None else tol) + 1e-6
    return any(abs(v - x) <= t for v in pool)


def is_action_line(line: str) -> bool:
    if ACTION_RE.search(line) or _IF_TARGET.search(line):
        return True
    if _SHARE_WORD.search(line):
        return any(m.group(0).split()[0] not in _NOT_TICKERS for m in _TICKER_BEFORE_TO_PCT.finditer(line))
    return False


def lint(draft: str, pool: set[float]) -> list[tuple[int, str]]:
    violations: list[tuple[int, str]] = []
    for i, line in enumerate(draft.splitlines(), start=1):
        if not is_action_line(line):
            continue
        for m in SUM_RE.finditer(line):
            before = line[:m.start()]
            if _PRICE_CTX.search(before):   # цена за единицу и пороги цен/метрик — факты, не сумма сделки
                continue
            approx = bool(re.search(r"[≈~]\s*[+\-−]?\s*$", before))
            unit = m.group("unit")
            x = _val(m.group("num")) * _UNIT.get((unit or "").lower(), 1.0)
            g = _granularity(m.group("num"), unit, approx)
            if not _found(x, g, pool):
                violations.append((i, f"сумма {m.group(0).strip()} не найдена в выводе скриптов"))
        for m in QTY_RE.finditer(line):
            approx = bool(re.search(r"[≈~]\s*$", line[:m.start()]))
            x = _val(m.group("num"))
            if not _found(x, _granularity(m.group("num"), None, approx), pool):
                violations.append((i, f"количество {m.group(0).strip()} не найдено в выводе скриптов"))
        for m in SHARE_RE.finditer(line):
            if not _SHARE_CTX.search(line[:m.start()]):
                continue
            if not _found(_val(m.group("num")), 0, pool, tol=0.05):
                violations.append((i, f"доля {m.group(0).strip()} не найдена в выводе скриптов"))
    return violations


def _read(path: str, what: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError as exc:
        raise SystemExit(_fail(f"не удалось прочитать {what} {path!r}: {exc}"))


def _fail(msg: str) -> int:
    print(f"Ошибка: {msg}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Числа сделок черновика должны быть в выводе скриптов.")
    ap.add_argument("--draft", required=True)
    ap.add_argument("--sources", nargs="+", required=True, metavar="FILE")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        draft = _read(args.draft, "черновик")
        pool = collect_source_numbers([_read(p, "источник") for p in args.sources])
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 2
    violations = lint(draft, pool)
    if args.json:
        print(json.dumps({"violations": [{"line": n, "message": m} for n, m in violations]}, ensure_ascii=False))
    elif not violations:
        print("Линт чист.")
    else:
        for n, m in violations:
            print(f"строка {n}: {m}")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
