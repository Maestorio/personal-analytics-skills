#!/usr/bin/env python3
"""
Парсер портфельного файла (Apple Numbers или Excel) в структурированный JSON.

Usage:
    python parse_portfolio.py <path-to-file> [--output json|text]

Поддерживает:
- .numbers (требует numbers-parser; pip install numbers-parser)
- .xlsx (требует openpyxl; pip install openpyxl)

Извлекает ключевые таблицы:
- Общий баланс (тотал, пополнение)
- Общие планы (доли по типам)
- Планы (матрица валюта × тип)
- План по Облигациям (подкорзины)
- Акции / Актуальные акции (включая IE-колонки → ie_actual)
- Облигации / Облигации (с ИИС-3 split)
- Invest Era / Модельный портфель Invest Era → ie_model
- Tаблица 1 (блок "Другое")
- Проверка (статус ошибок)

v2 additions (schema_version 2.0):
- ie_model: блок модельного портфеля IE
- ie_actual: per-ticker IE state из вкладки Акции
- ie_summary: derived cross-reference stats
- data_quality_flags: флаги качества данных этого шага парсинга
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any


# ---------------- Numbers reader ----------------

def read_numbers(path: str) -> dict[str, dict[str, list[list[Any]]]]:
    try:
        from numbers_parser import Document  # type: ignore
    except ImportError:
        sys.stderr.write(
            "numbers-parser not installed. Run: pip install numbers-parser\n"
        )
        sys.exit(2)

    doc = Document(path)
    out: dict[str, dict[str, list[list[Any]]]] = {}
    for sheet in doc.sheets:
        out[sheet.name] = {}
        for table in sheet.tables:
            rows = [list(r) for r in table.rows(values_only=True)]
            out[sheet.name][table.name] = rows
    return out


# ---------------- Excel reader ----------------

def read_xlsx(path: str) -> dict[str, dict[str, list[list[Any]]]]:
    try:
        from openpyxl import load_workbook  # type: ignore
    except ImportError:
        sys.stderr.write(
            "openpyxl not installed. Run: pip install openpyxl\n"
        )
        sys.exit(2)

    wb = load_workbook(path, data_only=True)
    out: dict[str, dict[str, list[list[Any]]]] = {}
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        if ws.tables:
            sheet_tables: dict[str, list[list[Any]]] = {}
            for tbl_name, tbl_ref in ws.tables.items():
                rows = [[c.value for c in row] for row in ws[tbl_ref]]
                sheet_tables[tbl_name] = rows
            out[sheet_name] = sheet_tables
        else:
            rows = [[c.value for c in row] for row in ws.iter_rows()]
            out[sheet_name] = {sheet_name: rows}
    return out


# ---------------- Helpers ----------------

def _rows_to_dicts(rows: list[list[Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    header = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
    return [
        {k: v for k, v in zip(header, r) if k}
        for r in rows[1:]
        if any(v is not None for v in r)
    ]


def _parse_decimal(val: Any) -> float | None:
    """Парсинг значений '5,59', 25.0, '-', None в float или None."""
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        if s in ('-', '--', ''):
            return None
        try:
            return float(s.replace(',', '.'))
        except ValueError:
            return None
    return None


def _text_or_none(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


# ---------------- Контракт подтипов облигаций (bond-subtypes-plan.md §4) ----------------
#
# SSOT — docs/investment/portfolio/bond-subtypes-plan.md §4 (не дублировать
# в других файлах, только ссылаться). Не «чинить» лестницу по интуиции:
# имена корзин — ЯРЛЫКИ владельца, не верхние границы диапазона: корзина
# "AA+" содержит "AAA", корзина "B+" содержит "BBB+". См. §4.2.

# Национальная рейтинговая лестница (Эксперт РА / АКРА / НКР / НРА),
# от старшего к младшему (§4.2).
RATING_LADDER: list[str] = [
    "AAA", "AA+", "AA", "AA-", "A+", "A", "A-",
    "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-",
]

# Корзина подтипа КОРП → множество детальных рейтингов, которые в неё
# попадают (§4.2, диапазоны по RATING_LADDER, границы включительно). Ниже
# "B-" лестницы нет — bond_rating_below_ladder. B+ = "B-…BBB+" по плану:
# это 9 позиций лестницы (BBB+ down to B-), а не только B+ сам по себе —
# тест §5.2 п.6 явно требует B-→B+.
CORP_SUBTYPE_BUCKETS: dict[str, frozenset[str]] = {
    "AA+": frozenset({"AAA", "AA+", "AA", "AA-"}),
    "A": frozenset({"A+", "A", "A-"}),
    "B+": frozenset({"BBB+", "BBB", "BBB-", "BB+", "BB", "BB-", "B+", "B", "B-"}),
}

# Допустимые пары (Тип, Подтип) таблиц «Облигации» / «План по Облигациям»
# (§4.3). КОРП/Флоат разрешена структурно (решение владельца Q4), но
# строки в плане для неё нет — это ловит отдельный гейт
# bond_bucket_not_in_plan, а не bond_subtype_unknown.
VALID_TYPE_SUBTYPE: dict[str, frozenset[str | None]] = {
    "USD": frozenset({None}),
    "EUR": frozenset({None}),
    "CNY": frozenset({None}),
    "ОФЗ": frozenset({">10", "<10", "Флоат"}),
    "КОРП": frozenset({"AA+", "A", "B+", "Флоат"}),
}


def rating_to_corp_bucket(rating: str | None) -> str | None:
    """Отобразить детальный `Рейтинг` в плановую корзину КОРП по лестнице
    §4.2. None — рейтинг пуст ИЛИ ниже "B-" / не распознан лестницей
    (тест §5.2 п.6: `CCC` → вне лестницы)."""
    if not rating:
        return None
    r = str(rating).strip().upper()
    for bucket, members in CORP_SUBTYPE_BUCKETS.items():
        if r in members:
            return bucket
    return None


def _bond_bucket_key(typ: Any, subtype: Any) -> str | None:
    """Производный ключ плановой корзины: `"ОФЗ/>10"` для ОФЗ/КОРП,
    просто `"USD"` для валютных строк без подтипа (§4.1). Пустой/«Итог»
    Тип → None (не отражает ни одну корзину)."""
    t = _text_or_none(typ)
    if not t or t == "Итог":
        return None
    s = _text_or_none(subtype)
    return f"{t}/{s}" if s else t


def _bonds_breakdown_subtype_column(rows: list[list[Any]]) -> str:
    """Какая колонка таблицы «План по Облигациям» несёт подтип: новая
    `Подтип` или legacy `Рейтинг` (§1.2 — в ЭТОЙ таблице это переименование
    одной колонки, не появление новой; §4.4 — обратная совместимость со
    снапшотами до 2026-08-18). Приоритет — `Подтип`."""
    if rows:
        header = [str(h) if h is not None else "" for h in rows[0]]
        if "Подтип" in header:
            return "Подтип"
        if "Рейтинг" in header:
            return "Рейтинг"
    return "Подтип"


def _enrich_bonds_breakdown(
    rows: list[dict[str, Any]], subtype_col: str
) -> list[dict[str, Any]]:
    """Добавить в каждую строку «План по Облигациям» производные `_subtype`
    (нормализованная строка из `subtype_col`) и `_bucket_key` (§4.1).
    Исходные русские ключи (включая legacy `Рейтинг`) НЕ трогаются —
    сохраняются как есть (§4.4)."""
    out: list[dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        typ = _text_or_none(row.get("Тип"))
        subtype = _text_or_none(row.get(subtype_col))
        row["_subtype"] = subtype
        row["_bucket_key"] = _bond_bucket_key(typ, subtype)
        out.append(row)
    return out


def _check_bond_subtype_gates(bond_rows: list[dict[str, Any]]) -> list[dict]:
    """PDL-7: гейты качества подтипа на уровне бумаги (§5.1), на строках
    таблицы «Облигации» (Тикер/Тип/Подтип/Название). Пара (Тип, Подтип)
    сверяется по VALID_TYPE_SUBTYPE (§4.3); отсутствие Подтип у ОФЗ/КОРП —
    отдельный, более специфичный гейт, не дублирующий warn дважды на одной
    строке. Пустой Подтип у валютных строк (USD/EUR/CNY) — норма, флагов
    не порождает (VALID_TYPE_SUBTYPE[...] == {None})."""
    flags: list[dict] = []
    for b in bond_rows:
        typ = _text_or_none(b.get("Тип"))
        subtype = _text_or_none(b.get("Подтип"))
        if typ in ("ОФЗ", "КОРП") and subtype is None:
            flags.append({
                "step": "bond_subtype_check",
                "severity": "warn",
                "code": "bond_subtype_missing",
                "message": (
                    f"{b.get('Тикер', '?')} ({b.get('Название', '?')}): "
                    f"Тип={typ}, но Подтип пуст."
                ),
            })
            continue
        allowed = VALID_TYPE_SUBTYPE.get(typ)
        if allowed is not None and subtype not in allowed:
            flags.append({
                "step": "bond_subtype_check",
                "severity": "warn",
                "code": "bond_subtype_unknown",
                "message": (
                    f"{b.get('Тикер', '?')} ({b.get('Название', '?')}): "
                    f"пара (Тип={typ}, Подтип={subtype}) вне §4.3."
                ),
            })
    return flags


# ---------------- v2: IE Model parser ----------------

def parse_ie_model(raw: dict[str, Any], flags: list[dict]) -> dict[str, Any]:
    """
    Парсинг вкладки 'Invest Era' → блок ie_model.

    Graceful degradation: если вкладки нет → positions=[], warning flag.
    Колонки: Тикер(0), Название(1), Сектор(2), Доля(3), Текущая цена(4),
             Точка входа(5), Уровень риска(6), Потенциал роста, %(7),
             Долгосрочный потенциал роста, %(8), Дивиденды за 2024, %(9),
             active_in_model bool(10)
    """
    today = _today()
    sheet_tables = raw.get("Invest Era", {})

    # Найти таблицу (точное совпадение или по подстроке)
    rows: list[list[Any]] | None = None
    for name, tbl in sheet_tables.items():
        if "модельный" in name.lower() or "invest era" in name.lower():
            rows = tbl
            break

    if not rows:
        flags.append({
            "step": "ie_model_parse",
            "severity": "warn",
            "code": "ie_model_sheet_missing",
            "message": "Вкладка 'Invest Era' не найдена. ie_model.positions = []",
        })
        return {
            "source_sheet": "Invest Era",
            "extraction_date": today,
            "model_total_pct": 0.0,
            "positions": [],
        }

    positions: list[dict[str, Any]] = []
    for row in rows[1:]:  # пропускаем заголовок
        if not row or row[0] is None:
            continue  # пустые строки (первая строка таблицы бывает пустой)
        ticker = _text_or_none(row[0])
        if not ticker:
            continue

        positions.append({
            "ticker": ticker,
            "name": _text_or_none(row[1]) if len(row) > 1 else None,
            "sector": _text_or_none(row[2]) if len(row) > 2 else None,
            "target_share_pct": _parse_decimal(row[3]) if len(row) > 3 else None,
            "current_price_rub": _parse_decimal(row[4]) if len(row) > 4 else None,
            "entry_price_rub": _parse_decimal(row[5]) if len(row) > 5 else None,
            "risk_level": _text_or_none(row[6]) if len(row) > 6 else None,
            "growth_potential_12m_pct": _parse_decimal(row[7]) if len(row) > 7 else None,
            "growth_potential_lt_pct": _parse_decimal(row[8]) if len(row) > 8 else None,
            "div_yield_2024_pct": _parse_decimal(row[9]) if len(row) > 9 else None,
            # Последняя колонка — булева отметка активности в модели
            "active_in_model": bool(row[10]) if len(row) > 10 and row[10] is not None else True,
        })

    model_total = sum(
        p["target_share_pct"] for p in positions if p["target_share_pct"] is not None
    )

    if positions and abs(model_total - 100.0) > 1.0:
        flags.append({
            "step": "ie_model_parse",
            "severity": "warn",
            "code": "ie_model_total_mismatch",
            "message": (
                f"Сумма target_share_pct в IE-модели = {model_total:.1f}%, "
                f"ожидается 100.0%. Возможна ошибка в файле."
            ),
        })

    return {
        "source_sheet": "Invest Era",
        "extraction_date": today,
        "model_total_pct": round(model_total, 4),
        "positions": positions,
    }


# ---------------- v2: IE Actual parser ----------------

def parse_ie_actual(raw: dict[str, Any], flags: list[dict]) -> dict[str, Any]:
    """
    Парсинг IE-колонок из вкладки 'Акции' → блок ie_actual.

    Колонки: Тикер(0), Название(1), Стоимость(2), Ср,Цена(3), Цена(4),
             Точка Входа(5), IE New(6), IE Old(7), Доля актуальная(8),
             Доля Планируемая(9), Доля Реальная(10), План(11),
             Статус(12), IE(13), AI(14)

    План(11)   — что пользователь собирается сделать (→ user_plan)
    Статус(12) — что пользователь уже сделал (→ user_status)
    IE(13)     — комментарий от Invest Era (→ user_note_ie)
    AI(14)     — вывод ru-portfolio-advisor (→ user_note_ai)

    Значения долей — дроби (0.06), конвертируем в % (6.0) через × 100.

    Фильтрация: пропускаем строки, где Стоимость=0 И IE New пустой И IE Old пустой
    (удалённые/неактуальные тикеры).
    """
    today = _today()
    sheet_tables = raw.get("Акции", {})

    rows: list[list[Any]] | None = None
    for name, tbl in sheet_tables.items():
        if "актуальные" in name.lower():
            rows = tbl
            break

    if not rows:
        return {"source_sheet": "Акции", "extraction_date": today, "per_ticker": {}}

    per_ticker: dict[str, dict[str, Any]] = {}
    changes: list[str] = []

    for row in rows[1:]:  # пропускаем заголовок
        if not row:
            continue
        ticker = _text_or_none(row[0])
        if not ticker or ticker == "Итог":
            continue

        stoimost = row[2] if len(row) > 2 else None
        ie_new_raw = row[6] if len(row) > 6 else None
        ie_old_raw = row[7] if len(row) > 7 else None

        # Пропускаем: Стоимость=0 И IE New пустой И IE Old пустой
        ie_new_empty = ie_new_raw is None or ie_new_raw == "" or ie_new_raw == "--"
        ie_old_empty = ie_old_raw is None or ie_old_raw == "" or ie_old_raw == "--"
        stoimost_zero = not isinstance(stoimost, (int, float)) or stoimost == 0
        if stoimost_zero and ie_new_empty and ie_old_empty:
            continue

        # Доли — дроби → проценты (× 100)
        ie_new_frac = None if ie_new_empty else _parse_decimal(ie_new_raw)
        ie_old_frac = None if ie_old_empty else _parse_decimal(ie_old_raw)
        ie_new_pct = round(ie_new_frac * 100, 4) if ie_new_frac is not None else None
        ie_old_pct = round(ie_old_frac * 100, 4) if ie_old_frac is not None else None

        if ie_new_pct is not None and ie_old_pct is not None:
            ie_delta = round(ie_new_pct - ie_old_pct, 4)
        else:
            ie_delta = None

        if ie_delta is not None and abs(ie_delta) > 0.001:
            changes.append(f"{ticker} ({ie_old_pct:.0f}→{ie_new_pct:.0f})")

        # Доля Реальная — дробь → %
        real_raw = row[10] if len(row) > 10 else None
        real_frac = _parse_decimal(real_raw)
        real_share_pct = round(real_frac * 100, 4) if real_frac is not None else None

        # Доля Планируемая — дробь → % (может быть '--')
        planned_raw = row[9] if len(row) > 9 else None
        planned_str = str(planned_raw or "").strip()
        if planned_str in ("--", ""):
            planned_share_pct = None
        else:
            pf = _parse_decimal(planned_raw)
            planned_share_pct = round(pf * 100, 4) if pf is not None else None

        per_ticker[ticker] = {
            "ie_new_pct": ie_new_pct,
            "ie_old_pct": ie_old_pct,
            "ie_delta_pct": ie_delta,
            "real_share_pct": real_share_pct,
            "planned_share_pct": planned_share_pct,
            "user_plan": _text_or_none(row[11] if len(row) > 11 else None),
            "user_status": _text_or_none(row[12] if len(row) > 12 else None),
            "user_note_ie": _text_or_none(row[13] if len(row) > 13 else None),
            "user_note_ai": _text_or_none(row[14] if len(row) > 14 else None),
        }

    if changes:
        flags.append({
            "step": "ie_actual_parse",
            "severity": "info",
            "code": "ie_changes_detected",
            "message": (
                f"За период обнаружены изменения IE по {len(changes)} тикерам: "
                + ", ".join(changes)
            ),
        })

    return {"source_sheet": "Акции", "extraction_date": today, "per_ticker": per_ticker}


# ---------------- v2: IE Summary ----------------

def compute_ie_summary(
    ie_model: dict[str, Any],
    ie_actual: dict[str, Any],
    active_tickers: list[str],
) -> dict[str, Any]:
    """Derived cross-reference stats между портфелем и IE-моделью."""
    ie_tickers = {p["ticker"] for p in ie_model.get("positions", [])}
    portfolio_tickers = set(active_tickers)

    both = ie_tickers & portfolio_tickers
    in_portfolio_not_ie = portfolio_tickers - ie_tickers
    in_ie_not_portfolio = ie_tickers - portfolio_tickers

    per_ticker = ie_actual.get("per_ticker", {})
    real_share_in_ie = sum(
        (per_ticker[t].get("real_share_pct") or 0.0)
        for t in both
        if t in per_ticker
    )

    ie_changes = sum(
        1
        for entry in per_ticker.values()
        if entry.get("ie_delta_pct") is not None and abs(entry["ie_delta_pct"]) > 0.001
    )

    return {
        "tickers_in_ie_model": len(ie_tickers),
        "tickers_in_portfolio_active": len(portfolio_tickers),
        "tickers_in_both": len(both),
        "tickers_in_portfolio_not_in_ie": len(in_portfolio_not_ie),
        "tickers_in_ie_not_in_portfolio": len(in_ie_not_portfolio),
        "ie_model_total_pct": ie_model.get("model_total_pct", 0.0),
        "real_share_total_in_ie_pct": round(real_share_in_ie, 4),
        "ie_changes_count": ie_changes,
        "list_in_portfolio_not_in_ie": sorted(in_portfolio_not_ie),
        "list_in_ie_not_in_portfolio": sorted(in_ie_not_portfolio),
    }


# ---------------- Transformers ----------------

def extract_portfolio(raw: dict[str, dict[str, list[list[Any]]]]) -> dict[str, Any]:
    """
    Нормализовать в плоскую JSON-структуру, удобную для LLM.
    v2: добавляет ie_model, ie_actual, ie_summary, data_quality_flags.

    ВАЖНО: выходной JSON использует русские имена колонок из Numbers-файла:
      - stocks: [{"Тикер": "SBER", "Название": "Сбербанк", "Стоимость": 49275.00, ...}]
      - bonds: [{"Тикер": "RU000A1038V6", "Название": "ОФЗ 26238",
                 "Итого без ИИСа": 49116.80, "Итого на ИИС": 79814.80, ...}]
      - other_positions: [{"Тикер": "...", "Тип": "БПИФ", "Стоимость": ...}]

    Потребители (assembly-скрипты) при сборке holdings должны:
    1. Акции: qty берут из returns.json (balance.json не содержит qty для акций)
    2. Облигации: qty = Всего − ИИС (для main), qty = ИИС (для iis_3)
    3. Цены обновляют из quotes.json (MOEX ISS, поле 'last', а не 'price')
    """

    def table(sheet: str, name: str) -> list[list[Any]] | None:
        tables = raw.get(sheet, {})
        if name in tables:
            return tables[name]
        for k, v in tables.items():
            if k.lower().replace("t", "т") == name.lower().replace("t", "т"):
                return v
        return None

    # Накопитель флагов качества данных этого шага парсинга
    flags: list[dict] = []

    result: dict[str, Any] = {
        "summary": {},
        "goals": {
            "overall": [],
            "matrix": [],
            "matrix_iis": [],
            "bonds_breakdown": [],
        },
        "other_positions": [],
        "iis_positions": [],
        "errors_check": [],
        "stocks": [],
        "bonds": [],
        "bonds_iis": [],
        "bonds_main": [],
        "invest_era": [],           # backward compat (raw rows)
        "raw_sheets": list(raw.keys()),
    }

    # --- Общий баланс ---
    t = table("Общий баланс", "Общий баланс")
    if t:
        for row in t:
            if not row or row[0] is None:
                continue
            result["summary"][str(row[0])] = row[1] if len(row) > 1 else None

    # --- Общие планы ---
    t = table("Общий баланс", "Общие планы")
    if t:
        result["goals"]["overall"] = _rows_to_dicts(t)

    # --- Планы (матрица) ---
    t = table("Общий баланс", "Планы")
    if t:
        filtered = [r for r in t if r and (r[0] or r[1])]
        all_rows = _rows_to_dicts(filtered)
        main_rows = []
        iis_rows = []
        for r in all_rows:
            if str(r.get("Бумага") or "").strip().upper() == "ИИС" or \
               str(r.get("Доля план") or "").strip().upper() == "NA":
                iis_rows.append(r)
            else:
                main_rows.append(r)
        result["goals"]["matrix"] = main_rows
        result["goals"]["matrix_iis"] = iis_rows

    # --- План по Облигациям ---
    # PDL-1: колонка «Рейтинг» переименована в «Подтип» (§1.2 — только в
    # ЭТОЙ таблице; в «Облигации» ниже «Подтип» — НОВАЯ колонка рядом с
    # сохранившимся «Рейтинг», нормализатор здесь не переиспользуется).
    t = table("Общий баланс", "План по Облигациям")
    if t:
        subtype_col = _bonds_breakdown_subtype_column(t)
        result["goals"]["bonds_breakdown"] = _enrich_bonds_breakdown(
            _rows_to_dicts(t), subtype_col
        )

    # --- Tаблица 1 (Другое) ---
    t = table("Общий баланс", "Tаблица 1") or table("Общий баланс", "Таблица 1")
    if t:
        all_rows = _rows_to_dicts(t)
        result["other_positions"] = all_rows
        result["iis_positions"] = [
            r for r in all_rows
            if "ИИС" in str(r.get("Тип") or "").upper()
        ]

    # --- Проверка ---
    t = table("Общий баланс", "Проверка")
    if t:
        result["errors_check"] = _rows_to_dicts(t)

    # --- Акции ---
    t = table("Акции", "Актуальные акции")
    if t:
        rows = _rows_to_dicts(t)
        rows = [r for r in rows if r.get("Тикер") and r.get("Тикер") != "Итог"]
        result["stocks"] = rows

    # --- Облигации ---
    t = table("Облигации", "Облигации")
    if t:
        rows = _rows_to_dicts(t)
        rows = [r for r in rows if r.get("Тикер") and r.get("Тикер") != "Итог"]
        result["bonds"] = rows
        result["bonds_iis"] = [
            b for b in rows
            if isinstance(b.get("ИИС"), (int, float)) and b["ИИС"] > 0
        ]
        result["bonds_main"] = [
            b for b in rows
            if isinstance(b.get("Итого без ИИСа"), (int, float)) and b["Итого без ИИСа"] > 0
        ]

        # Флаги для позиций, разделённых между main и iis_3
        for b in rows:
            val_main = b.get("Итого без ИИСа")
            val_iis = b.get("Итого на ИИС")
            qty_all = b.get("Всего")
            qty_iis = b.get("ИИС")
            if (
                isinstance(val_main, (int, float)) and val_main > 0
                and isinstance(val_iis, (int, float)) and val_iis > 0
            ):
                qty_main_str = (
                    f"{int(qty_all - qty_iis)}"
                    if isinstance(qty_all, (int, float)) and isinstance(qty_iis, (int, float))
                    else "?"
                )
                qty_iis_str = str(int(qty_iis)) if isinstance(qty_iis, (int, float)) else "?"
                flags.append({
                    "step": "iis_account_assignment",
                    "severity": "warn",
                    "code": "iis_split_position",
                    "message": (
                        f"Тикер {b.get('Тикер', '?')} ({b.get('Название', '?')}) "
                        f"разделён между main и iis_3: "
                        f"{qty_main_str} + {qty_iis_str} шт. соответственно"
                    ),
                })

        # PDL-7: гейты качества подтипа на уровне бумаги (§5.1).
        flags.extend(_check_bond_subtype_gates(rows))

    # --- Invest Era (backward compat raw) ---
    t = table("Invest Era", "Модельный портфель Invest Era")
    if t:
        result["invest_era"] = _rows_to_dicts(t)

    # --- v2: IE Model, IE Actual, IE Summary ---
    result["ie_model"] = parse_ie_model(raw, flags)
    result["ie_actual"] = parse_ie_actual(raw, flags)

    # active_tickers для ie_summary будут вычислены в compute_metrics,
    # поэтому ie_summary заполняем после
    result["_flags"] = flags  # временный ключ, переносится в data_quality_flags ниже

    return result


# ---------------- Derived metrics ----------------

def compute_metrics(data: dict[str, Any]) -> dict[str, Any]:
    """
    Рассчитать производные метрики: реальные доли, отклонения, активные тикеры.

    С версии 2026-04-20 разделяет ИИС-3 (долгосрочные облигации, отдельный счёт)
    от основной части портфеля.

    Семантика строки «Имеется (RUB)» (уточнена владельцем 2026-07-08):
    это стоимость ВСЕГО портфеля — ВКЛЮЧАЯ ИИС-3, БЕЗ заблокированных активов.
    Проверочный инвариант файла: «Итого» = «Имеется» + «Пополнение» (ИИС не
    прибавляется отдельно — он уже внутри «Имеется»).
      - total_current_rub_incl_iis: сумма "Имеется (RUB)" как есть
      - iis_balance_rub: сумма "ИИС" (ИИС-3, не учитывается в ребалансе)
      - total_current_rub_excl_iis: Имеется − ИИС
        (основные счета, по ним считается ребалансировка)

    Побочный эффект (PDL-7): дописывает гейты план↔факт облигаций в
    `data["_flags"]` — тот же мутируемый список, что extract_portfolio уже
    положил в result["_flags"] (перенос в data_quality_flags — в parse()).
    """
    total_current_incl_iis: float | None = None
    iis_balance: float | None = None

    for k, v in data["summary"].items():
        key_norm = str(k).strip().lower()
        if "имеется" in key_norm and isinstance(v, (int, float)):
            total_current_incl_iis = float(v)
        elif key_norm == "иис" and isinstance(v, (int, float)):
            iis_balance = float(v)

    total_current_excl_iis = None
    if total_current_incl_iis is not None:
        total_current_excl_iis = total_current_incl_iis - (iis_balance or 0.0)

    total_current = total_current_excl_iis

    # Активные акции (стоимость > 0)
    active_stocks = [
        s for s in data["stocks"]
        if isinstance(s.get("Стоимость"), (int, float)) and s["Стоимость"] > 0
    ]

    planned_stocks = [
        s for s in data["stocks"]
        if (not isinstance(s.get("Стоимость"), (int, float)) or s["Стоимость"] == 0)
        and s.get("Доля Планируемая") not in (None, "", "--", 0)
    ]

    active_bonds = [
        b for b in data["bonds"]
        if isinstance(b.get("Текущая стоимость"), (int, float)) and b["Текущая стоимость"] > 0
    ]

    bonds_by_type_all: dict[str, float] = {}
    bonds_by_type_excl_iis: dict[str, float] = {}
    bonds_by_type_iis_only: dict[str, float] = {}
    # PDL-2: те же три среза, но по плановой корзине (Тип/Подтип →
    # "ОФЗ/>10" и т.п., §4.1) вместо голого Тип — закрывает дефект A
    # (план стал 9-корзинным, факт был 5-корзинным).
    bonds_by_subtype_all: dict[str, float] = {}
    bonds_by_subtype_excl_iis: dict[str, float] = {}
    bonds_by_subtype_iis_only: dict[str, float] = {}

    for b in active_bonds:
        t = str(b.get("Тип") or "?")
        val_all = float(b.get("Текущая стоимость") or 0)
        val_main = float(b.get("Итого без ИИСа") or 0) if isinstance(b.get("Итого без ИИСа"), (int, float)) else val_all
        val_iis = float(b.get("Итого на ИИС") or 0) if isinstance(b.get("Итого на ИИС"), (int, float)) else 0.0

        bonds_by_type_all[t] = bonds_by_type_all.get(t, 0.0) + val_all
        if val_main > 0:
            bonds_by_type_excl_iis[t] = bonds_by_type_excl_iis.get(t, 0.0) + val_main
        if val_iis > 0:
            bonds_by_type_iis_only[t] = bonds_by_type_iis_only.get(t, 0.0) + val_iis

        bucket_key = _bond_bucket_key(b.get("Тип"), b.get("Подтип"))
        if bucket_key:
            bonds_by_subtype_all[bucket_key] = bonds_by_subtype_all.get(bucket_key, 0.0) + val_all
            if val_main > 0:
                bonds_by_subtype_excl_iis[bucket_key] = bonds_by_subtype_excl_iis.get(bucket_key, 0.0) + val_main
            if val_iis > 0:
                bonds_by_subtype_iis_only[bucket_key] = bonds_by_subtype_iis_only.get(bucket_key, 0.0) + val_iis

    total_bonds_iis_rub = sum(bonds_by_type_iis_only.values())
    total_bonds_main_rub = sum(bonds_by_type_excl_iis.values())

    active_tickers = sorted({s["Тикер"] for s in active_stocks})

    ie_gap = [
        ie for ie in data["invest_era"]
        if ie.get("Название") and ie["Название"] not in set(active_tickers)
    ]

    action_flags = [
        s for s in data["stocks"]
        if s.get("План") or s.get("Статус") or s.get("AI") or s.get("IE")
    ]

    # --- by_account breakdown (v2) ---
    stocks_main_rub = sum(
        float(s["Стоимость"]) for s in active_stocks
        if isinstance(s.get("Стоимость"), (int, float))
    )
    # other_positions (funds, TLCB, etc.) — из Tаблицы 1
    other_main_rub = sum(
        float(r["Стоимость"]) for r in data.get("other_positions", [])
        if isinstance(r.get("Стоимость"), (int, float))
        and "ИИС" not in str(r.get("Тип") or "").upper()
    )
    bonds_main_total = total_bonds_main_rub

    # Остаток — «грязный» балансовый: кроме кэша содержит позиции, которых нет
    # во вкладках баланса (денежные фонды TPAY/TMON, FINAMAR из трейдов).
    # Канонический настоящий кэш считает assemble_snapshot._build_cash по
    # полному списку holdings.
    accounted_main = stocks_main_rub + bonds_main_total + other_main_rub
    cash_main_rub = (
        (total_current_excl_iis - accounted_main)
        if total_current_excl_iis is not None
        else None
    )

    # PDL-7: гейты план↔факт, которым достаточно portfolio.json (без
    # свежих котировок MOEX/holdings — те гейты живут в assemble_snapshot.py,
    # bond-subtypes-plan.md §5.1). Пишем напрямую в data["_flags"] — тот же
    # мутируемый список, что extract_portfolio положил в result["_flags"]
    # и parse() позже переносит в data_quality_flags.
    _gates: list[dict] = data.setdefault("_flags", [])
    bonds_breakdown = data.get("goals", {}).get("bonds_breakdown", [])
    plan_rows = [
        r for r in bonds_breakdown
        if _text_or_none(r.get("Тип")) not in (None, "Итог")
    ]
    itog_row = next(
        (r for r in bonds_breakdown if _text_or_none(r.get("Тип")) == "Итог"),
        None,
    )
    _GATE_TOL_RUB = 1.0

    # bond_bucket_not_in_plan: позиция в корзине, которой нет в плане.
    plan_bucket_keys = {r.get("_bucket_key") for r in plan_rows if r.get("_bucket_key")}
    _reported_missing_buckets: set[str] = set()
    for b in active_bonds:
        bk = _bond_bucket_key(b.get("Тип"), b.get("Подтип"))
        if bk and bk not in plan_bucket_keys and bk not in _reported_missing_buckets:
            _reported_missing_buckets.add(bk)
            _gates.append({
                "step": "bond_plan_check", "severity": "warn",
                "code": "bond_bucket_not_in_plan",
                "message": (
                    f"Корзина {bk} встречается в holdings, но отсутствует "
                    f"в «План по Облигациям»."
                ),
            })

    # bond_plan_shares_not_100: Σ «Доля План» ≠ 1.0 ± 0.005.
    if plan_rows:
        total_share = sum(_parse_decimal(r.get("Доля План")) or 0.0 for r in plan_rows)
        if abs(total_share - 1.0) > 0.005:
            _gates.append({
                "step": "bond_plan_check", "severity": "warn",
                "code": "bond_plan_shares_not_100",
                "message": (
                    f"Σ «Доля План» в «План по Облигациям» = {total_share:.4f}, "
                    f"ожидается 1.0 ± 0.005."
                ),
            })

    # bond_plan_base_mismatch: строка «Итог».Нынешняя Сумма файла должна
    # совпадать с Σ «Итого без ИИСа» (база excl_iis, §3.1/Q1), а не с
    # Σ «Текущая стоимость» (incl_iis) — иначе файл смешивает базы.
    if itog_row is not None:
        itog_val = _parse_decimal(itog_row.get("Нынешняя Сумма"))
        if itog_val is not None:
            sum_incl = sum(_parse_decimal(b.get("Текущая стоимость")) or 0.0 for b in active_bonds)
            sum_excl = total_bonds_main_rub
            matches_incl = abs(itog_val - sum_incl) < _GATE_TOL_RUB
            matches_excl = abs(itog_val - sum_excl) < _GATE_TOL_RUB
            if matches_incl and not matches_excl:
                _gates.append({
                    "step": "bond_plan_check", "severity": "warn",
                    "code": "bond_plan_base_mismatch",
                    "message": (
                        f"«План по Облигациям».Итог/Нынешняя Сумма "
                        f"({itog_val:,.2f}) совпал с Σ «Текущая стоимость» "
                        f"(вкл. ИИС-3), а не с Σ «Итого без ИИСа» — файл "
                        f"смешивает базы (§3.1)."
                    ),
                })

    # matrix_bond_iis_leak: «Планы».RUB/Облигация.Сейчас должно совпадать
    # с Σ(ОФЗ+КОРП) из «План по Облигациям» — иначе ИИС-3 протекла в матрицу.
    matrix_main = data.get("goals", {}).get("matrix", [])
    rub_bond_row = next(
        (
            r for r in matrix_main
            if str(r.get("Валюта") or "").strip().upper() == "RUB"
            and str(r.get("Бумага") or "").strip() == "Облигация"
        ),
        None,
    )
    if rub_bond_row is not None:
        sejchas = _parse_decimal(rub_bond_row.get("Сейчас"))
        if sejchas is not None:
            ofz_corp_sum = sum(
                _parse_decimal(r.get("Нынешняя Сумма")) or 0.0
                for r in plan_rows
                if _text_or_none(r.get("Тип")) in ("ОФЗ", "КОРП")
            )
            if abs(sejchas - ofz_corp_sum) > _GATE_TOL_RUB:
                _gates.append({
                    "step": "bond_plan_check", "severity": "warn",
                    "code": "matrix_bond_iis_leak",
                    "message": (
                        f"«Планы».RUB/Облигация.Сейчас ({sejchas:,.2f}) ≠ "
                        f"Σ(ОФЗ+КОРП) из «План по Облигациям» "
                        f"({ofz_corp_sum:,.2f}) — похоже, ИИС-3 протекла "
                        f"в матрицу «Планы» (§3.1)."
                    ),
                })

    # balance_identity_broken: Σ «Сейчас» по строкам матрицы + строка ИИС
    # должна совпадать с «Имеется (RUB)».
    if total_current_incl_iis is not None:
        matrix_iis = data.get("goals", {}).get("matrix_iis", [])
        main_sum = sum(_parse_decimal(r.get("Сейчас")) or 0.0 for r in matrix_main)
        iis_sum = sum(_parse_decimal(r.get("Сейчас")) or 0.0 for r in matrix_iis)
        if abs(main_sum + iis_sum - total_current_incl_iis) > _GATE_TOL_RUB:
            _gates.append({
                "step": "bond_plan_check", "severity": "warn",
                "code": "balance_identity_broken",
                "message": (
                    f"Σ «Сейчас» по строкам матрицы «Планы» + строка ИИС "
                    f"({main_sum + iis_sum:,.2f}) ≠ «Имеется (RUB)» "
                    f"({total_current_incl_iis:,.2f})."
                ),
            })

    by_account = {
        "main": {
            "total_rub": total_current_excl_iis,
            "stocks_rub": round(stocks_main_rub, 2),
            "bonds_rub": round(bonds_main_total, 2),
            "funds_rub": round(other_main_rub, 2),
            "cash_rub": round(cash_main_rub, 2) if cash_main_rub is not None else None,
        },
        "iis_3": {
            "total_rub": iis_balance,
            "stocks_rub": 0.0,
            "bonds_rub": round(total_bonds_iis_rub, 2),
            "funds_rub": 0.0,
            "cash_rub": (
                # Минус облигации ИИС и минус прочие ИИС-позиции из вкладки
                # «Другое» (Тип содержит ИИС — например, SBGB).
                round(
                    (iis_balance or 0.0) - total_bonds_iis_rub - sum(
                        float(r["Стоимость"]) for r in data.get("iis_positions", [])
                        if isinstance(r.get("Стоимость"), (int, float))
                    ),
                    2,
                )
                if iis_balance is not None
                else None
            ),
        },
    }

    return {
        # Совместимость: старое поле (основные счета без ИИС = Имеется − ИИС)
        "total_current_rub": total_current,
        # Явные поля (с 2026-04-20)
        "total_current_rub_excl_iis": total_current_excl_iis,
        "total_current_rub_incl_iis": total_current_incl_iis,
        "iis_balance_rub": iis_balance,
        # Счётчики
        "n_active_stocks": len(active_stocks),
        "n_planned_stocks": len(planned_stocks),
        "n_active_bonds": len(active_bonds),
        "n_active_bonds_iis": len(data.get("bonds_iis", [])),
        "n_active_bonds_main": len(data.get("bonds_main", [])),
        # Списки
        "active_stock_tickers": active_tickers,
        "planned_stock_tickers": sorted(s["Тикер"] for s in planned_stocks),
        "ie_not_in_active": sorted(ie["Название"] for ie in ie_gap),
        # Облигации по типам
        "bonds_value_by_type": bonds_by_type_all,
        "bonds_value_by_type_excl_iis": bonds_by_type_excl_iis,
        "bonds_value_by_type_iis_only": bonds_by_type_iis_only,
        # PDL-2: облигации по плановой корзине (Тип/Подтип, §4.1)
        "bonds_value_by_subtype": bonds_by_subtype_all,
        "bonds_value_by_subtype_excl_iis": bonds_by_subtype_excl_iis,
        "bonds_value_by_subtype_iis_only": bonds_by_subtype_iis_only,
        "total_bonds_main_rub": total_bonds_main_rub,
        "total_bonds_iis_rub": total_bonds_iis_rub,
        "iis_other_tickers": sorted(
            r.get("Бумага") for r in data.get("iis_positions", []) if r.get("Бумага")
        ),
        "stocks_with_action_notes": [
            {
                "ticker": s.get("Тикер"),
                "name": s.get("Название"),
                "plan": s.get("План"),
                "status": s.get("Статус"),
                "ie_note": s.get("IE"),
                "ai_note": s.get("AI"),
            }
            for s in action_flags
            if s.get("Тикер") != "Итог"
        ],
        # v2: by_account breakdown
        "by_account": by_account,
    }


# ---------------- Main ----------------

def parse(path: str) -> dict[str, Any]:
    ext = Path(path).suffix.lower()
    if ext == ".numbers":
        raw = read_numbers(path)
    elif ext in (".xlsx", ".xlsm"):
        raw = read_xlsx(path)
    else:
        raise SystemExit(f"Unsupported file extension: {ext}")

    data = extract_portfolio(raw)
    data["metrics"] = compute_metrics(data)

    # Финализировать ie_summary (нужны active_tickers из metrics)
    data["ie_summary"] = compute_ie_summary(
        data["ie_model"],
        data["ie_actual"],
        data["metrics"]["active_stock_tickers"],
    )

    # Перенести флаги из временного ключа в data_quality_flags
    data["data_quality_flags"] = data.pop("_flags", [])

    return data


def _today() -> str:
    """Дата выгрузки (`extraction_date`): PDL_AS_OF ставит build_snapshot.py — повтор пакета
    прогона в другой день не должен менять снапшот; без переменной — системные часы."""
    return os.environ.get("PDL_AS_OF") or datetime.date.today().isoformat()


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: parse_portfolio.py <path> [--output json|text]")
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"File not found: {path}")
        sys.exit(1)

    mode = "json"
    if "--output" in sys.argv:
        i = sys.argv.index("--output")
        if i + 1 < len(sys.argv):
            mode = sys.argv[i + 1]

    data = parse(path)

    if mode == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        m = data["metrics"]
        print(f"Total (current RUB): {m['total_current_rub']}")
        print(f"Active stocks: {m['n_active_stocks']}")
        print(f"Planned stocks: {m['n_planned_stocks']}")
        print(f"Active bonds: {m['n_active_bonds']}")
        print(f"Bonds by type: {m['bonds_value_by_type']}")
        print(f"IE tickers not in active: {m['ie_not_in_active']}")
        print(f"\nIE Model positions: {len(data['ie_model']['positions'])}")
        print(f"IE Summary: {data['ie_summary']}")
        print(f"Data quality flags: {len(data['data_quality_flags'])}")


if __name__ == "__main__":
    main()
