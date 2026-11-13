#!/usr/bin/env python3
"""known_splits.py — реестр сплитов бумаг как ДАННЫЕ (stdlib only).

Реестр = встроенный набор (BUILTIN) ∪ файл `Portfolio/known-splits.json` (формат known-splits@1).
Запись файла перебивает встроенную при совпадении (тикер, дата). Нет файла — только встроенный.
Невалидный файл — исключение KnownSplitsError: молча откатываться на встроенный набор нельзя,
пропущенный сплит меняет количество бумаги в 10–100 раз.

`date` — день возобновления торгов (первый день постсплитовых цен). ratio > 1 — прямой сплит
(1 акция → ratio), 0 < ratio < 1 — обратный.

CLI:  python3 known_splits.py list|add|dismiss --file PATH [--ticker T --date D --ratio R --note … --by …]
Коды: 0 ок, 1 отказ (дубль, невалидная запись), 2 ошибка вызова.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

# Время МСК (`time_msk.py`) — канон в _shared-references/; в упакованном .skill — рядом (pack.sh).
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import time_msk  # noqa: E402

SCHEMA = "known-splits@1"
ADDED_BY = ("site", "claude", "owner")
DETECT_TOL = 0.07          # допуск отношения цен к целому N

# Встроенный набор. {ticker: [{"date": date, "ratio": float, "note": str}]}
BUILTIN: dict[str, list[dict]] = {
    "T": [
        {
            "date": dt.date(2026, 4, 17),
            "ratio": 10.0,
            "note": "Т-Технологии сплит 1:10. Последний pre-split торговый день "
                    "10.04.2026, возобновление торгов post-split 17.04.2026. "
                    "В IntelInvest операция сплита не фиксируется отдельной строкой.",
        },
    ],
    "PLZL": [
        {
            "date": dt.date(2025, 3, 27),
            "ratio": 10.0,
            "note": "Полюс сплит 1:10. Последний pre-split торговый день "
                    "21.03.2025, конвертация 25.03.2025, возобновление торгов "
                    "27.03.2025.",
        },
    ],
    "GMKN": [
        {
            "date": dt.date(2024, 4, 4),
            "ratio": 100.0,
            "note": "Норникель сплит 1:100. Завершён 04.04.2024.",
        },
    ],
    "TRNFP": [
        {
            "date": dt.date(2024, 2, 21),
            "ratio": 100.0,
            "note": "Транснефть префы сплит 1:100. Последний pre-split 05.02.2024, "
                    "конвертация 19.02.2024, возобновление торгов 21.02.2024.",
        },
    ],
    # TMF reverse-split 1:10 08.07.2024 уже обрабатывается через apply_corrections
    # (TMF_FORCED_CLOSE), здесь не дублируем.
}


class KnownSplitsError(ValueError):
    """Файл реестра сплитов нечитаем или невалиден."""


class DuplicateSplitError(KnownSplitsError):
    """Запись уже есть в реестре (сайт отвечает 409, а не 400)."""


def builtin_copy() -> dict[str, list[dict]]:
    return copy.deepcopy(BUILTIN)


# ───────────────────────────── проверка записей ─────────────────────────────

def _check_entry(e, where: str, *, need_ratio: bool = True) -> tuple[str, dt.date, float]:
    if not isinstance(e, dict):
        raise KnownSplitsError(f"{where}: запись должна быть объектом")
    tk = e.get("ticker")
    if not isinstance(tk, str) or not tk.strip():
        raise KnownSplitsError(f"{where}: пустой или нечисловой тикер")
    ds = e.get("date")
    try:
        if not isinstance(ds, str):
            raise ValueError
        d = dt.date.fromisoformat(ds)
    except ValueError:
        raise KnownSplitsError(f"{where} ({tk}): дата «{ds}» не в формате ГГГГ-ММ-ДД") from None
    r = e.get("ratio")
    if isinstance(r, bool) or not isinstance(r, (int, float)) or r != r or r <= 0 or r == 1 or r == float("inf"):
        raise KnownSplitsError(f"{where} ({tk} {ds}): ratio должен быть числом > 0 и ≠ 1, получено {r!r}")
    return tk.strip(), d, float(r)


def validate_doc(doc) -> None:
    if not isinstance(doc, dict):
        raise KnownSplitsError("корень файла должен быть объектом")
    if doc.get("schema") != SCHEMA:
        raise KnownSplitsError(f"schema должна быть «{SCHEMA}», получено {doc.get('schema')!r}")
    for key in ("splits", "dismissed"):
        if not isinstance(doc.get(key, []), list):
            raise KnownSplitsError(f"«{key}» должен быть списком")
    seen = set()
    for i, e in enumerate(doc.get("splits") or []):
        tk, d, _ = _check_entry(e, f"splits[{i}]")
        if (tk, d) in seen:
            raise KnownSplitsError(f"splits[{i}]: дубль ({tk}, {d.isoformat()})")
        seen.add((tk, d))
        if e.get("added_by") is not None and e["added_by"] not in ADDED_BY:
            raise KnownSplitsError(f"splits[{i}] ({tk}): added_by должен быть из {list(ADDED_BY)}")
    seen = set()
    for i, e in enumerate(doc.get("dismissed") or []):
        tk, d, r = _check_entry(e, f"dismissed[{i}]")
        if (tk, d, r) in seen:
            raise KnownSplitsError(f"dismissed[{i}]: дубль ({tk}, {d.isoformat()}, {r:g})")
        seen.add((tk, d, r))


def _read_doc(path) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as ex:
        raise KnownSplitsError(f"файл реестра сплитов {path} не читается: {ex}") from ex
    try:
        validate_doc(doc)
    except KnownSplitsError as ex:
        raise KnownSplitsError(f"файл реестра сплитов {path} невалиден: {ex}") from ex
    return doc


def load(path) -> tuple[dict[str, list[dict]], list[dict]]:
    """(реестр {ticker: [{date, ratio, note}]}, отклонённые подозрения). Нет файла — встроенный набор."""
    reg = builtin_copy()
    if not path or not Path(path).is_file():
        return reg, []
    doc = _read_doc(path)
    by_key = {(tk, e["date"]): e for tk, lst in reg.items() for e in lst}
    for e in doc.get("splits") or []:
        tk, d, r = _check_entry(e, "splits")
        by_key[(tk, d)] = {"date": d, "ratio": r, "note": str(e.get("note") or "")}
    out: dict[str, list[dict]] = {}
    for (tk, _d), e in by_key.items():
        out.setdefault(tk, []).append(e)
    for lst in out.values():
        lst.sort(key=lambda e: e["date"])
    return out, [dict(x) for x in doc.get("dismissed") or []]


# ───────────────────────────── запись ─────────────────────────────

def _now(now) -> str:
    return now if isinstance(now, str) else time_msk.now_iso()


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _write_atomic(path: Path, doc: dict, now_iso: str, expected_digest=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if expected_digest is not None and _digest(path) != expected_digest:
        raise KnownSplitsError(f"файл реестра сплитов {path} изменился после чтения (сайт, синк или другая "
                               f"сессия) — ничего не записано, повтори команду")
    if path.is_file():
        bdir = path.parent / ".backups"
        bdir.mkdir(exist_ok=True)
        stamp = now_iso[:10] + "-" + now_iso[11:13] + now_iso[14:16]
        (bdir / f"known-splits-{stamp}.json").write_bytes(path.read_bytes())
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".known-splits-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _load_or_new(path: Path) -> tuple[dict, str | None]:
    """(документ, sha256 файла на момент чтения | None, если файла нет)."""
    if path.is_file():
        return _read_doc(path), _digest(path)
    return {"schema": SCHEMA, "splits": [], "dismissed": []}, None


def _add_to_doc(doc: dict, entry: dict, now) -> tuple[dict, dict]:
    added_by = entry.get("added_by", "owner")
    if added_by not in ADDED_BY:
        raise KnownSplitsError(f"added_by должен быть из {list(ADDED_BY)}")
    note = entry.get("note") or ""
    tk, d, r = _check_entry({"ticker": entry.get("ticker"), "date": entry.get("date"),
                             "ratio": entry.get("ratio"), "note": note}, "новая запись")
    doc = copy.deepcopy(doc)
    if any(e["ticker"].strip() == tk and e["date"] == d.isoformat() for e in doc["splits"]) \
            or any(e["date"] == d for e in BUILTIN.get(tk, [])):
        raise DuplicateSplitError(f"сплит {tk} {d.isoformat()} уже есть в реестре")
    ts = _now(now)
    new = {"ticker": tk, "date": d.isoformat(), "ratio": r, "note": note,
           "added_at": ts, "added_by": added_by}
    doc["splits"].append(new)
    doc["splits"].sort(key=lambda e: (e["ticker"], e["date"]))
    return doc, new


def apply_add(doc: dict, entry: dict, now=None) -> dict:
    """Чистая функция: документ реестра + запись {ticker, date, ratio, note?, added_by?} → НОВЫЙ документ.
    Исходный не меняется. Дубль (тикер, дата) в документе или во встроенном наборе — DuplicateSplitError."""
    return _add_to_doc(doc, entry, now)[0]


def _dismiss_in_doc(doc: dict, entry: dict, now) -> tuple[dict, dict]:
    tk, d, r = _check_entry({"ticker": entry.get("ticker"), "date": entry.get("date"),
                             "ratio": entry.get("ratio")}, "отклонение")
    doc = copy.deepcopy(doc)
    if any(e["ticker"].strip() == tk and e["date"] == d.isoformat() and float(e["ratio"]) == r
           for e in doc["dismissed"]):
        raise DuplicateSplitError(f"отклонение {tk} {d.isoformat()} ×{r:g} уже записано")
    ts = _now(now)
    new = {"ticker": tk, "date": d.isoformat(), "ratio": r, "dismissed_at": ts, "note": entry.get("note") or ""}
    doc["dismissed"].append(new)
    return doc, new


def apply_dismiss(doc: dict, entry: dict, now=None) -> dict:
    """Чистая функция: отклонение подозрения на сплит → НОВЫЙ документ (исходный не меняется)."""
    return _dismiss_in_doc(doc, entry, now)[0]


def add(path, ticker, date, ratio, note="", added_by="owner", now=None) -> dict:
    """Добавить сплит в файл. Дубль (тикер, дата) в файле или во встроенном наборе — KnownSplitsError."""
    path = Path(path)
    loaded, digest = _load_or_new(path)
    doc, entry = _add_to_doc(loaded, {"ticker": ticker, "date": date, "ratio": ratio,
                                      "note": note, "added_by": added_by}, now)
    _write_atomic(path, doc, entry["added_at"], digest)
    return entry


def dismiss(path, ticker, date, ratio, note="", now=None) -> dict:
    """Отклонить подозрение на сплит (проверка split_suspected больше не повторяет его)."""
    path = Path(path)
    loaded, digest = _load_or_new(path)
    doc, entry = _dismiss_in_doc(loaded, {"ticker": ticker, "date": date, "ratio": ratio,
                                          "note": note}, now)
    _write_atomic(path, doc, entry["dismissed_at"], digest)
    return entry


# ───────────────────────────── поиск сплита ─────────────────────────────

# Кратности выше 10 — только «круглые»: при относительном допуске любое число больше ~8 лежит
# в пределах ±7 % от какого-нибудь целого, и случайный скачок цены выглядел бы сплитом 1:343.
ROUND_RATIOS = (20, 25, 30, 40, 50, 100, 200, 250, 400, 500, 1000, 2000, 5000, 10000)


def near_integer(x: float, tol: float = DETECT_TOL) -> int | None:
    """Кратность сплита N, если x в пределах ±tol (относительно N) от N: целое 2..10
    или одно из ROUND_RATIOS. Иначе None."""
    n = round(x)
    if 2 <= n <= 10:
        return n if abs(x / n - 1) <= tol else None
    return next((c for c in ROUND_RATIOS if abs(x / c - 1) <= tol), None)


def suspect_ratio(prev_price: float, cur_price: float, tol: float = DETECT_TOL) -> float | None:
    """ratio сплита по падению/росту цены: N (прямой) или 1/N (обратный); None — не похоже."""
    if not prev_price or not cur_price or prev_price <= 0 or cur_price <= 0:
        return None
    r = prev_price / cur_price
    n = near_integer(r, tol)
    if n:
        return float(n)
    n = near_integer(1 / r, tol)
    return 1.0 / n if n else None


def _default_fetch(ticker: str, from_date: dt.date, to_date: dt.date):
    import market_series
    rows, _meta = market_series.fetch_iss_history("share", ticker, from_date, to_date)
    return rows


def _weekdays_between(a: dt.date, b: dt.date) -> int:
    n, d = 0, a + dt.timedelta(days=1)
    while d < b:
        if d.weekday() < 5:
            n += 1
        d += dt.timedelta(days=1)
    return n


def find_split_date(ticker: str, from_date, to_date, ratio: float | None = None, fetch=None,
                    tol: float = DETECT_TOL) -> dict | None:
    """Первая пара соседних торговых дней, где закрытие изменилось как при сплите.

    fetch(ticker, from_date, to_date) -> [(ГГГГ-ММ-ДД, close|None)]; по умолчанию ISS history (акции).
    ratio задан — ищем именно его (N или 1/N), иначе любой целый N ≥ 2 в обе стороны.
    Возвращает {date, ratio, prev_close, new_close, halt_days} или None. Сбой сети — исключение fetch."""
    f = fetch or _default_fetch
    fd = dt.date.fromisoformat(str(from_date)[:10])
    td = dt.date.fromisoformat(str(to_date)[:10])
    rows = sorted((str(d)[:10], float(c)) for d, c in f(ticker, fd, td) if c is not None and float(c) > 0)
    for (d0, c0), (d1, c1) in zip(rows, rows[1:]):
        got = suspect_ratio(c0, c1, tol)
        if got is None:
            continue
        if ratio is not None and abs(got / ratio - 1) > tol:
            continue
        return {"date": d1, "ratio": got, "prev_close": c0, "new_close": c1,
                "halt_days": _weekdays_between(dt.date.fromisoformat(d0), dt.date.fromisoformat(d1))}
    return None


# ───────────────────────────── CLI ─────────────────────────────

def _jprint(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Реестр сплитов бумаг (known-splits@1).")
    ap.add_argument("cmd", choices=["list", "add", "dismiss"])
    ap.add_argument("--file", required=True, help="Portfolio/known-splits.json")
    ap.add_argument("--ticker")
    ap.add_argument("--date", help="день возобновления торгов ГГГГ-ММ-ДД")
    ap.add_argument("--ratio", type=float)
    ap.add_argument("--note", default="")
    ap.add_argument("--by", default="owner", choices=ADDED_BY)
    try:
        a = ap.parse_args(argv)
    except SystemExit as ex:
        return 2 if ex.code else 0
    try:
        if a.cmd == "list":
            reg, dis = load(a.file)
            _jprint({"splits": {t: [{**e, "date": e["date"].isoformat()} for e in lst]
                                for t, lst in sorted(reg.items())}, "dismissed": dis})
            return 0
        if not (a.ticker and a.date and a.ratio is not None):
            print("нужны --ticker, --date, --ratio", file=sys.stderr)
            return 2
        if a.cmd == "add":
            _jprint({"added": add(a.file, a.ticker, a.date, a.ratio, a.note, a.by)})
        else:
            _jprint({"dismissed": dismiss(a.file, a.ticker, a.date, a.ratio, a.note)})
        return 0
    except KnownSplitsError as ex:
        _jprint({"error": str(ex)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
