#!/usr/bin/env python3
"""Точка входа режимов E/F: выписки любых банков → операции (решение 2026-10-11).

Пользователь не объясняет, «что есть что»: банк, тип счёта (текущий/депозитный), валюта и период
берутся из содержимого файла. Скрипт:
  1. определяет банк каждого файла по сигнатурам реестра `BANKS`;
  2. разбирает файл парсером банка (у каждого парсера свои проверки арифметики — не сошлись → blocking);
  3. группирует по банку и вызывает нормализатор банка (он же проверяет комплектность: у FF нужны
     текущие выписки всех четырёх валют);
  4. отдаёт: `files` (что за файл), `missing` (чего не хватает), `unrecognized` (банк не узнан —
     нужен образец для нового парсера), `banks` (операции, флаги, сверка остатка).

  stmt_import.py FILE [FILE …] [--out FILE.json]

Новый банк = запись в `BANKS` (сигнатуры + парсер + нормализатор) + строка в реестре тестов. Результат
содержит IBAN и тексты операций — только локально, в git и в Claude-Memory не класть.
Код: 0 — всё разобрано; 2 — blocking (проверка парсера, нет обязательной выписки) либо банк не узнан.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _read_head(path: str, limit: int = 4000) -> str:
    """Начало файла как текст: PDF — через pdftotext (1-я страница), остальное — как есть."""
    if path.lower().endswith(".pdf"):
        try:
            return subprocess.run(["pdftotext", "-f", "1", "-l", "1", "-layout", path, "-"], capture_output=True, text=True, check=True).stdout[:limit]
        except (FileNotFoundError, subprocess.CalledProcessError):
            return ""
    if path.lower().endswith(".xlsx"):
        return _xlsx_head(path, limit)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def _xlsx_head(path: str, limit: int) -> str:
    """Первый лист xlsx как текст (ячейки через пробел); нет openpyxl или файл битый — пусто (банк не узнан)."""
    try:
        import warnings
        import openpyxl
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb[wb.sheetnames[0]]
        return "\n".join(" ".join(str(c) for c in r if c is not None) for r in ws.iter_rows(values_only=True))[:limit]
    except Exception:
        return ""


def _ff():
    import ff_normalize
    import parse_ff_statement
    return parse_ff_statement.parse_statement, ff_normalize.normalize, ff_normalize.Blocking


def _tbank():
    import parse_tbank_statement
    import tbank_normalize
    return parse_tbank_statement.parse_statement, tbank_normalize.normalize, tbank_normalize.Blocking


def _raif():
    import parse_raif_statement
    import raif_normalize
    return parse_raif_statement.parse_statement, raif_normalize.normalize, raif_normalize.Blocking


def _bog():
    import bog_normalize
    import parse_bog_statement
    return parse_bog_statement.parse_statement, bog_normalize.normalize, bog_normalize.Blocking


# Реестр банков: сигнатуры (подстроки без регистра) и/или регулярки → парсер и нормализатор. Импорт ленивый.
BANKS = {
    "ff": {"name": "Freedom Bank Kazakhstan (FF)", "signatures": ["фридом банк казахстан", "freedom bank kazakhstan", "ksnvkzka"],
           "account_patterns": [r"\bFF\b", "freedom", "фридом"], "loader": _ff},
    # у выписки BOG в шапке нет названия банка — узнаём по IBAN Грузии с кодом банка BG (GExxBG + 16 цифр)
    "bog": {"name": "Bank of Georgia (BOG)", "signatures": ["bank of georgia"], "patterns": [r"\bGE\d\dBG\d{16}\b"],
            "account_patterns": [r"\bBOG\b", "bank of georgia", "банк грузии"], "loader": _bog},
    # справка о движении средств Т-Банка (PDF): один файл = один договор; счёт ZenMoney — по последним 4 цифрам договора в externalIds
    "tbank": {"name": "Т-Банк (Тинькофф)", "signatures": ["акционерное общество «тбанк»", "ао «тбанк»", "tbank.ru"],
              "account_patterns": ["т-банк", "т‑банк", "тинькофф", "tinkoff", "tbank"], "loader": _tbank},
    # CSV из интернет-банка Райффайзена: названия банка нет — узнаём по шапке колонок; счёт — по текстам операций
    "raif": {"name": "Райффайзенбанк", "signatures": ["выполнено банком;номер документа;сумма в валюте операции (поступления)"],
             "account_patterns": ["райффайзен", "raiffeisen", r"\braif", "райф"], "loader": _raif},
}


def detect_bank(text: str, banks=None) -> str | None:
    t = (text or "").lower()
    for key, b in (banks or BANKS).items():
        if any(sig in t for sig in b["signatures"]) or any(re.search(p, text or "", re.I) for p in b.get("patterns", [])):
            return key
    return None


def run(paths: list[str], banks=None, reader=_read_head) -> dict:
    banks = banks or BANKS
    out = {"files": [], "unrecognized": [], "missing": [], "banks": {}}
    by_bank: dict[str, list] = {}
    for p in paths:
        key = detect_bank(reader(p), banks)
        if key is None:
            out["unrecognized"].append(os.path.basename(p))
            continue
        by_bank.setdefault(key, []).append(p)
    for key, files in by_bank.items():
        parse, normalize, blocking = banks[key]["loader"]()
        statements = []
        for p in files:
            st = parse(p)
            st["file"] = os.path.basename(p)
            statements.append(st)
            m = st["meta"]
            out["files"].append({"file": st["file"], "bank": key, "kind": m.get("kind"), "currency": m.get("currency"),
                                 "period": f'{m.get("period_from")}–{m.get("period_to")}', "checks_ok": st["checks"]["ok"]})
        try:
            out["banks"][key] = normalize({"statements": statements})
        except blocking as e:
            out["missing"].append({"bank": key, "why": str(e)})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        res = run(a.files)
    except Exception as e:  # парсер банка отказал (проверки арифметики и т. п.)
        print(f"[blocking] {e}", file=sys.stderr)
        return 2
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    for f in res["files"]:
        print(f'  {f["file"]}: {f["bank"]}, {"текущий" if f["kind"] == "current" else "депозитный"} {f["currency"]}, {f["period"]}', file=sys.stderr)
    for m in res["missing"]:
        print(f'[blocking] {m["bank"]}: {m["why"]}', file=sys.stderr)
    if res["unrecognized"]:
        print("[blocking] банк не узнан (нужен образец для нового парсера): " + ", ".join(res["unrecognized"]), file=sys.stderr)
    return 2 if (res["missing"] or res["unrecognized"]) else 0


if __name__ == "__main__":
    sys.exit(main())
