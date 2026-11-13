#!/usr/bin/env python3
"""
compute_marginal_move.py — парсер строк-уровней FCA → числовые поля macro-marginal (MFC-4).

Назначение: LLM записывает в macro-marginal человекочитаемые строки-уровни:
  central_estimate_l1_2026: "$68/bbl (JPMorgan-dominant weighted median)"

Этот скрипт детерминированно парсит их и добавляет рядом машинные поля:
  level_l1_2026: 68.0
  unit: usd_per_bbl

Без внешних зависимостей (только stdlib).

CLI:
  cat macro_marginal_fragment.json | python3 compute_marginal_move.py
  echo '{"brent": {"central_estimate_l1_2026": "$68/bbl"}}' | python3 compute_marginal_move.py

Вход (stdin, JSON):
  {
    "<factor>": {
      "central_estimate_l1_<year>": "<строка>",
      ...
    },
    ...
  }

Выход (stdout, JSON):
  {
    "<factor>": {
      "level_l1_<year>": <float>,
      "unit": "<unit>",
      ...  (все исходные поля сохраняются)
    },
    ...
  }

Единицы (контракт Шага 0.1, _shared-references/events-yaml-spec.md §5.6):
  usd_per_bbl      — Brent/Urals, % движения от baseline_spot в consumer
  rub_per_usd      — USD/RUB, % движения от baseline_spot
  rub_per_cny      — CNY/RUB, % движения от baseline_spot
  usd_per_troy_oz  — Золото, % движения от baseline_spot
  rate_pct         — CBR rate, Δ п.п. в consumer
"""
from __future__ import annotations

import json
import re
import sys

# Подсказки единиц по имени фактора (если паттерн в строке неоднозначен)
FACTOR_UNIT_HINTS: dict[str, str] = {
    "brent":           "usd_per_bbl",
    "urals":           "usd_per_bbl",
    "urals_discount":  "usd_per_bbl",
    "usdrub":          "rub_per_usd",
    "cnyrub":          "rub_per_cny",
    "xauusd":          "usd_per_troy_oz",
    "cbr_rate":        "rate_pct",
}

_L1_PREFIX = "central_estimate_l1_"
_OUT_PREFIX = "level_l1_"


def parse_level_string(text: str, factor: str) -> tuple[float | None, str | None]:
    """
    Парсит строку FCA-уровня в (числовой_уровень, unit).

    Поддерживаемые паттерны:
      "$68/bbl ..."         → 68.0, usd_per_bbl
      "88 руб./$ ..."       → 88.0, rub_per_usd
      "12.5 руб./¥ ..."     → 12.5, rub_per_cny
      "14.5% к 2026-12-31"  → 14.5, rate_pct (только при cbr_rate hint)
      "1800 $/тр.oz ..."    → 1800.0, usd_per_troy_oz
    """
    if not isinstance(text, str):
        return None, None
    t = text.strip()

    # $N/bbl (Brent, Urals)
    m = re.search(r'\$\s*([\d]+(?:[.,][\d]+)?)\s*/bbl', t, re.IGNORECASE)
    if m:
        return _to_float(m.group(1)), "usd_per_bbl"

    # N$/bbl альтернатива
    m = re.search(r'([\d]+(?:[.,][\d]+)?)\s*\$\s*/bbl', t, re.IGNORECASE)
    if m:
        return _to_float(m.group(1)), "usd_per_bbl"

    # N руб./$ (USD/RUB)
    m = re.search(r'([\d]+(?:[.,][\d]+)?)\s*руб\.?\s*/\s*\$', t)
    if m:
        return _to_float(m.group(1)), "rub_per_usd"

    # N руб./¥ или N руб./юань (CNY/RUB)
    m = re.search(r'([\d]+(?:[.,][\d]+)?)\s*руб\.?\s*/\s*[¥юань]', t, re.IGNORECASE)
    if m:
        return _to_float(m.group(1)), "rub_per_cny"

    # N% — только если hint подсказывает rate (cbr_rate)
    m = re.search(r'^([\d]+(?:[.,][\d]+)?)\s*%', t)
    if m and FACTOR_UNIT_HINTS.get(factor) == "rate_pct":
        return _to_float(m.group(1)), "rate_pct"

    # $N для золота (3+ цифр, избегаем путаницы с bbl)
    m = re.search(r'\$\s*([\d]{3,}(?:[.,][\d]+)?)', t)
    if m and FACTOR_UNIT_HINTS.get(factor) == "usd_per_troy_oz":
        return _to_float(m.group(1)), "usd_per_troy_oz"

    # Fallback: первое число + unit_hint от имени фактора
    m = re.search(r'([\d]+(?:[.,][\d]+)?)', t)
    if m:
        unit = FACTOR_UNIT_HINTS.get(factor)
        if unit:
            return _to_float(m.group(1)), unit

    return None, None


def _to_float(s: str) -> float | None:
    try:
        return float(s.replace(',', '.'))
    except (ValueError, AttributeError):
        return None


def enrich_factor(factor: str, fcast: dict) -> dict:
    """
    Принимает dict одного фактора из macro-marginal, добавляет level_l1_<год> + unit.
    Сохраняет все исходные поля без изменений.
    """
    if not isinstance(fcast, dict):
        return fcast
    result = dict(fcast)

    detected_unit: str | None = None
    for key, val in fcast.items():
        if not key.startswith(_L1_PREFIX):
            continue
        year_part = key[len(_L1_PREFIX):]
        try:
            year = int(year_part)
        except ValueError:
            continue

        level, unit = parse_level_string(val, factor)
        if level is None:
            continue

        result[f"{_OUT_PREFIX}{year}"] = level
        if detected_unit is None and unit:
            detected_unit = unit

    if detected_unit is not None and "unit" not in result:
        result["unit"] = detected_unit

    return result


def process(payload: dict) -> dict:
    """Обрабатывает весь блок factors из macro-marginal."""
    return {factor: enrich_factor(factor, fcast) for factor, fcast in payload.items()}


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"ERROR: невалидный JSON на stdin: {e}\n")
        return 1
    if not isinstance(payload, dict):
        sys.stderr.write("ERROR: ожидался JSON-объект {factor: {...}, ...}\n")
        return 1

    result = process(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
