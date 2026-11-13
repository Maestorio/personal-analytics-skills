#!/usr/bin/env python3
"""
weighted_consensus.py

Детерминированный расчёт filtered consensus по собранным прогнозам:
- применение trust-весов из INDEX.md (HIGH=1.0, MEDIUM=0.5, LOW/IGNORE/unaudited=0.0)
- weighted median и P10/P90 для числовых прогнозов
- split по позициям для качественных
- взвешенный горизонт (HIGH x 1.0, MEDIUM x 0.5)
- confidence = 0.4 + 0.4 * share_HIGH - 0.2 * asymmetry_warning
- next_due = forecast_date + interval_months

Используется в forecast-confidence-applier (Шаг 5 + Шаг 6 Events YAML).

CLI:
    cat input.json | python3 weighted_consensus.py
    python3 weighted_consensus.py --input input.json --output result.json

Input schema (JSON):
{
  "query_domain": "ru-macro",
  "asymmetry_warning": false,
  "forecast_date": "2026-05-05",          # YYYY-MM-DD
  "interval_months_override": null,        # int|null
  "sources": [
    {
      "id": "stratfor",
      "name": "Stratfor",
      "value": 88.5,                       # numeric forecast (optional)
      "position": "bullish",               # qualitative forecast (optional)
      "horizon_date": "2026-12-31",        # optional
      "applied_level": "HIGH",             # HIGH|MEDIUM|LOW|IGNORE (optional)
      "trust_profile": [                   # alternative: list of subdomain matches
        {"subdomain": "long-term-russia", "level": "HIGH"}
      ],
      "audited": true
    }
  ]
}
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from datetime import date, datetime, timedelta
from typing import Any

# Общий модуль весов сайта: сначала каталог скрипта (пакет .skill), затем _shared-references/ репозитория.
import os as _os
_HERE = _os.path.dirname(_os.path.abspath(__file__))
for _cand in (_HERE, _os.path.normpath(_os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import scenario_weights as _sw  # noqa: E402

LEVEL_TO_WEIGHT = {"HIGH": 1.0, "MEDIUM": 0.5, "LOW": 0.0, "IGNORE": 0.0}

DEFAULT_INTERVAL_MONTHS = {
    "ru-macro": 3,
    "geopolitics": 6,
    "global-banks": 3,
    "ru-sellside": 3,
    "tech-ceo": 6,
}


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def add_months(d: date, months: int) -> date:
    """forecast_date + N months, без зависимости от dateutil."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    last_day = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    day = min(d.day, last_day)
    return date(year, month, day)


def applied_weight(source: dict) -> tuple[float, str | None, bool]:
    """
    Возвращает (вес, matched_subdomain|None, is_fallback_medium).
    is_fallback_medium=True означает, что источник аудирован, но нет ни applied_level,
    ни trust_profile — выдан MEDIUM по умолчанию (trust-application.md §nearest-domain).
    Если source.audited == false → 0.0.
    Если есть applied_level — используется напрямую.
    Иначе берётся MAX по trust_profile.
    """
    if not source.get("audited", True):
        return 0.0, None, False

    if "applied_level" in source and source["applied_level"]:
        level = source["applied_level"]
        if level not in LEVEL_TO_WEIGHT:
            raise ValueError(f"unknown applied_level: {level} (source={source.get('id')})")
        return LEVEL_TO_WEIGHT[level], None, False

    profile = source.get("trust_profile") or []
    if not profile:
        # Аудирован, но нет subdomain match → MEDIUM по дефолту (trust-application.md §nearest-domain).
        return 0.5, None, True

    best_weight = 0.0
    best_subdomain = None
    for entry in profile:
        level = entry.get("level")
        if level not in LEVEL_TO_WEIGHT:
            continue
        w = LEVEL_TO_WEIGHT[level]
        if w > best_weight:
            best_weight = w
            best_subdomain = entry.get("subdomain")
    return best_weight, best_subdomain, False


def weighted_median_tie(pairs: list[tuple[float, float]]) -> tuple[float, float] | None:
    """
    Ничья: накопленный вес ровно на половине между двумя соседними значениями
    (чётное число равновесных источников). Возвращает (нижнее, верхнее) или None.
    """
    sorted_pairs = sorted(pairs, key=lambda p: p[0])
    total = sum(w for _, w in sorted_pairs)
    half = total / 2.0
    cum = 0.0
    for i, (value, weight) in enumerate(sorted_pairs[:-1]):
        cum += weight
        if abs(cum - half) <= 1e-9 * max(total, 1.0):
            upper = sorted_pairs[i + 1][0]
            return (value, upper) if upper != value else None
        if cum > half:
            return None
    return None


def weighted_median(pairs: list[tuple[float, float]]) -> float:
    """
    pairs: [(value, weight), ...] — все weight > 0.
    Вычисляет взвешенную медиану: значение, делящее total_weight пополам.
    При ничьей — середина двух соседних значений: нижнее значение смещало бы
    итог вниз при каждом чётном числе равновесных источников.
    """
    if not pairs:
        raise ValueError("weighted_median: empty input")
    tie = weighted_median_tie(pairs)
    if tie is not None:
        return (tie[0] + tie[1]) / 2.0
    sorted_pairs = sorted(pairs, key=lambda p: p[0])
    total = sum(w for _, w in sorted_pairs)
    half = total / 2.0
    cum = 0.0
    for value, weight in sorted_pairs:
        cum += weight
        if cum >= half:
            return value
    return sorted_pairs[-1][0]


def weighted_quantile(pairs: list[tuple[float, float]], q: float) -> float:
    """
    Взвешенный квантиль: значение, ниже которого находится доля q взвешенной массы.
    """
    if not pairs:
        raise ValueError("weighted_quantile: empty input")
    sorted_pairs = sorted(pairs, key=lambda p: p[0])
    total = sum(w for _, w in sorted_pairs)
    target = total * q
    cum = 0.0
    for value, weight in sorted_pairs:
        cum += weight
        if cum >= target:
            return value
    return sorted_pairs[-1][0]


def weighted_horizon(pairs: list[tuple[date, float]], forecast_date: date | None) -> dict | None:
    """
    pairs: [(horizon_date, weight), ...] — только источники с известным горизонтом и весом > 0.
    Считает взвешенное среднее по дням от forecast_date.
    """
    valid = [(d, w) for d, w in pairs if d is not None and w > 0]
    if not valid or forecast_date is None:
        return None

    days = [(d - forecast_date).days for d, _ in valid]
    weights = [w for _, w in valid]
    total_weight = sum(weights)
    if total_weight == 0:
        return None

    weighted_avg_days = sum(d * w for d, w in zip(days, weights)) / total_weight
    weighted_date = forecast_date + timedelta(days=round(weighted_avg_days))

    all_dates = [d for d, _ in valid]
    return {
        "weighted_date": weighted_date.isoformat(),
        "min_date": min(all_dates).isoformat(),
        "max_date": max(all_dates).isoformat(),
    }


def compute_confidence(n_high: int, n_in_consensus: int, asymmetry_warning: bool) -> float:
    """
    confidence = 0.4 + 0.4 * (доля HIGH среди собранных) - 0.2 * asymmetry_warning
    Округление до 2 знаков, диапазон [0.0, 1.0].

    "Среди собранных" = HIGH + MEDIUM (всё, что попало в filtered consensus с весом > 0).
    Если в consensus нет источников — считаем долю HIGH = 0.
    """
    share_high = (n_high / n_in_consensus) if n_in_consensus > 0 else 0.0
    raw = 0.4 + 0.4 * share_high - (0.2 if asymmetry_warning else 0.0)
    return round(max(0.0, min(1.0, raw)), 2)


# --- F3 confidence_by_horizon — ПРОВИЗОРНЫЕ пороги (provisional until outcome_log calibration) ---
# Взяты из self-audit §8 F3; НЕ подтверждены данными (outcome_log ещё пуст). Подкрутить после
# накопления resolved-исходов, а не хардкодить магию по месту.
CONF_DECAY_FREE_MONTHS = 6            # provisional until outcome_log calibration
CONF_DECAY_PER_6MO = 0.05            # provisional until outcome_log calibration
CONF_THIN_COVERAGE_MIN_SOURCES = 2   # provisional until outcome_log calibration
CONF_THIN_COVERAGE_CAP = 0.30       # provisional until outcome_log calibration
ANCHOR_SHARE_CAP_THRESHOLD = 0.5    # provisional until outcome_log calibration (кусок F2)
ANCHOR_SHARE_CAP = 0.40             # provisional until outcome_log calibration (кусок F2)


def _resolve_target_horizons(payload: dict, in_consensus: list) -> list:
    """Целевые горизонты для confidence_by_horizon: payload.horizons (от FCA — forecast.horizons)
    → иначе distinct horizon_date источников в консенсусе. Пусто → [] (аддитивно, поле пустое)."""
    raw = payload.get("horizons")
    if raw:
        parsed = [parse_date(h) for h in raw]
        return [h for h in parsed if h is not None]
    return sorted({s["horizon_date"] for s in in_consensus if s["horizon_date"] is not None})


def compute_confidence_by_horizon(source_coverage, anchor_share, in_consensus,
                                  forecast_date, horizons) -> dict:
    """Per-horizon confidence (F3, self-audit №3): база source_coverage − декэй по дальности,
    cap при тонком покрытии, cap при anchor_share>0.5. Скаляр `confidence` этим НЕ подменяется —
    это отдельный носитель сигнала (пороги — provisional-константы выше)."""
    out: dict[str, float] = {}
    for h in horizons:
        if h is None:
            continue
        val = source_coverage
        if forecast_date is not None:
            months = (h.year - forecast_date.year) * 12 + (h.month - forecast_date.month)
            beyond = max(0, months - CONF_DECAY_FREE_MONTHS)
            val -= CONF_DECAY_PER_6MO * (beyond / 6.0)
        # Тонкое покрытие горизонта: сколько источников «дотягиваются» до h (horizon_date ≥ h).
        n_cover = sum(1 for s in in_consensus
                      if s["horizon_date"] is not None and s["horizon_date"] >= h)
        if n_cover < CONF_THIN_COVERAGE_MIN_SOURCES:
            val = min(val, CONF_THIN_COVERAGE_CAP)
        if anchor_share is not None and anchor_share > ANCHOR_SHARE_CAP_THRESHOLD:
            val = min(val, ANCHOR_SHARE_CAP)
        out[h.isoformat()] = round(max(0.0, min(1.0, val)), 2)
    return out


def parse_central(central_estimate: str | float) -> float | None:
    """Извлекает число из central_estimate.

    Поддерживает формат `references/events-yaml-spec.md` §2.3
    «{переменная}: {значение или диапазон} к {дата}», а также короткие
    значения типа '12.7%', '$88', '85-90'. Возвращает центр диапазона.

    Поддержка: %, $, €, em-/en-dash, RU-десятичная запятая (13,5),
    qualifiers <, >, ~, thousands-separator (5,400 → 5400). Качественные
    строки без числа («Korean-style armistice») возвращают None.
    """
    if isinstance(central_estimate, (int, float)):
        return float(central_estimate)
    if not isinstance(central_estimate, str):
        return None
    s = central_estimate.strip()
    # Drop "к YYYY..." date suffix (spec format «переменная: значение к дата»).
    s = re.split(r'\s+к\s+\d', s, maxsplit=1)[0].strip()
    # If still has colon (variable name prefix), take last segment.
    if ':' in s:
        s = s.rsplit(':', 1)[1].strip()
    # Drop parenthesised commentary "(weighted median 12.7%)".
    s = re.sub(r'\s*\([^)]*\)\s*', ' ', s).strip()
    # Strip thousands-separator commas: "5,400" → "5400" (only when followed by 3 digits).
    s = re.sub(r'(?<=\d),(?=\d{3}(?:\D|$))', '', s)
    # RU decimal comma: "13,5" → "13.5" (only between digits, not 3-digit groups).
    s = re.sub(r'(?<=\d),(?=\d)', '.', s)
    # Strip leading qualifiers "<15%", ">5", "~10".
    s = re.sub(r'^[<>~]\s*', '', s)
    # Strip leading currency symbol.
    s = re.sub(r'^[$€]\s*', '', s)
    # Normalize em-/en-dash to hyphen.
    s = s.replace('—', '-').replace('–', '-')
    # Range "70-80" → midpoint (units between/after numbers допустимы).
    m = re.search(r'(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)', s)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2
    # Single number anywhere в строке.
    m = re.search(r'(-?\d+(?:\.\d+)?)', s)
    if m:
        return float(m.group(1))
    return None


def load_weights_from_scenario(scenario_yaml_path: str) -> dict[str, float]:
    """Читает SSOT scenario YAML, возвращает {A,B,C,D: weight}. Stdlib-only.

    Формат — `references/scenario-yaml-spec.md` §1.1:
        matrix:
          scenario_triggers:
            - scenario_id: A
              probability: 0.25
            ...

    Также поддерживает legacy формат-словарь (для совместимости с
    синтетическими fixtures):
        scenarios:
          A:
            probability: 0.25
    """
    with open(scenario_yaml_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    weights: dict[str, float] = {}
    current: str | None = None
    for line in lines:
        # "- scenario_id: X" — старт нового триггера в scenario_triggers.
        m = re.match(r'^\s*-\s*scenario_id:\s*([A-D])\b', line)
        if m:
            current = m.group(1)
            continue
        # "scenario_id: X" indented (без дефиса — продолжение списка).
        m = re.match(r'^\s+scenario_id:\s*([A-D])\b', line)
        if m:
            current = m.group(1)
            continue
        # Legacy "X:" indented (dict format).
        m = re.match(r'^\s+([A-D]):\s*$', line)
        if m:
            current = m.group(1)
            continue
        if current is not None:
            m = re.match(r'^\s+probability:\s*([\d.]+)', line)
            if m:
                weights[current] = float(m.group(1))
    return weights


def joint_from_axes(ev_x: float, ev_y: float, rho: float = 0.0) -> dict[str, float]:
    """
    Получить веса 4 сценариев Shell-матрицы из FCA на осях.
    Используется ТОЛЬКО при opt-in (CLI флаг --apply-joint-from-axes);
    по default scenario-builder выдаёт 0.25 каждому (D1).

    Args:
        ev_x: P(axis_x = HIGH), 0..1
        ev_y: P(axis_y = HIGH), 0..1
        rho: корреляция между осями, -1..1 (D6: default 0 = независимость)

    Returns:
        {"A": p_A, "B": p_B, "C": p_C, "D": p_D}, сумма == 1.0

    Mapping — канон полярности §17 F4 (`stress_pole: A`, `detente_pole: D`),
    сверено с живой матрицей scenario-geopolitics-ru-west-2026-07-01
    (axis_x high = «война продолжается», axis_y high = «единый/ужесточённый»):
        A: x_HIGH + y_HIGH     «Затяжная осада» — война + ужесточение
        B: x_HIGH + y_LOW      «Война на расколотом фронте» — война + фрагментация
        C: x_LOW  + y_HIGH     «Замороженный конфликт» — перемирие + holding
        D: x_LOW  + y_LOW      «Большая сделка и разрядка» — перемирие + снятие

    ⚠️ До 2026-08-04 маппинг здесь был ЗЕРКАЛЬНЫМ (A = x_LOW+y_LOW), то есть вес
    войны уезжал на разрядку. Ошибка не падала и выглядела правдоподобно. Канон
    для кросс-скиллового использования — `_shared-references/scenario_axis_weights.py`;
    совпадение результатов закреплено drift-контрактом в тестах.
    """
    p_x_low = 1 - ev_x
    p_y_low = 1 - ev_y

    cov_correction = rho * (ev_x * p_x_low * ev_y * p_y_low) ** 0.5

    # cov прибавляется к «однополюсным» квадрантам (оба HIGH / оба LOW) и
    # вычитается из смешанных — при любой привязке к id сценариев.
    p_A = ev_x * ev_y + cov_correction              # оба HIGH  — стресс-полюс
    p_D = p_x_low * p_y_low + cov_correction        # оба LOW   — детант-полюс
    p_B = ev_x * p_y_low - cov_correction
    p_C = p_x_low * ev_y - cov_correction

    weights = {"A": p_A, "B": p_B, "C": p_C, "D": p_D}

    # Numerical tolerance: floating-point ошибки округления возле 0/1.
    TOL = 1e-9
    for k, w in list(weights.items()):
        if -TOL < w < 0:
            weights[k] = 0.0
        elif 1 < w < 1 + TOL:
            weights[k] = 1.0

    # После tolerance: если остались отрицательные веса — joint distribution
    # математически невозможен при заданных (ev_x, ev_y, ρ). Bivariate Bernoulli
    # joint существует только когда |ρ| ≤ min(√(ev_x·(1-ev_y)/((1-ev_x)·ev_y)),
    # √((1-ev_x)·ev_y/(ev_x·(1-ev_y)))). Используем ValueError, не AssertionError —
    # чтобы не исчезало при `python3 -O`.
    invalid = {k: round(w, 6) for k, w in weights.items() if w < 0 or w > 1}
    if invalid:
        raise ValueError(
            f"joint distribution не существует при ev_x={ev_x}, ev_y={ev_y}, ρ={rho}: "
            f"невалидные веса {invalid}. Уменьшите |ρ| или сдвиньте ev_x/ev_y от 0/1."
        )

    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        weights = {k: v / total for k, v in weights.items()}

    return weights


def aggregate_marginal(
    by_scenario: dict,
    weights: dict[str, float],
    horizon: str,
    method: str = "linear",
) -> dict:
    """
    Детерминированный пересчёт Layer 2 marginal-значения из by_scenario блока.

    Args:
        by_scenario: {"A": {"values": {horizon: {"central": x, ...}}}, …}
        weights: {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}, сумма == 1.0
        horizon: "2026-12-31" и т.д.
        method: linear | nonlinear | modal | axis_dependent

    Returns:
        {"central": <number>, "range": [lo, hi]}

    Raises:
        ValueError: если sum(weights) отклоняется от 1.0 более чем на 0.001.
            Защита от битых RECALIBRATE-обновлений (D7).
    """
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-3:
        raise ValueError(
            f"sum(weights) = {total:.6f}, ожидалось 1.0 ± 0.001 "
            f"(weights={weights})"
        )

    if method == "linear":
        central = sum(
            weights[sid] * by_scenario[sid]["values"][horizon]["central"]
            for sid in ["A", "B", "C", "D"]
        )
        lows = [by_scenario[sid]["values"][horizon].get("range", [None, None])[0]
                for sid in ["A", "B", "C", "D"]]
        highs = [by_scenario[sid]["values"][horizon].get("range", [None, None])[1]
                 for sid in ["A", "B", "C", "D"]]
        lows = [x for x in lows if x is not None]
        highs = [x for x in highs if x is not None]
        return {
            "central": central,
            "range": [min(lows), max(highs)] if lows and highs else None,
        }
    elif method == "modal":
        modal = max(weights, key=weights.get)
        return by_scenario[modal]["values"][horizon]
    elif method == "nonlinear":
        modal = max(weights, key=weights.get)
        return {
            **by_scenario[modal]["values"][horizon],
            "note": f"nonlinear: modal {modal} (p={weights[modal]:.2f})",
        }
    elif method == "axis_dependent":
        raise NotImplementedError("axis_dependent requires axis_value mapping context")
    else:
        raise ValueError(f"Unknown method: {method}")


def coherence_check(forecast_yaml: dict) -> dict:
    """
    Сравнивает Layer 1 marginal (forecast.central_estimate) с Layer 2 marginal
    (computed from by_scenario). Возвращает divergence diagnostic.

    Используется в conditional_on_scenarios.coherence_diagnostic блок.
    """
    layer1 = parse_central(forecast_yaml["forecast"]["central_estimate"])

    cond = forecast_yaml.get("conditional_on_scenarios")
    if not cond:
        return {
            "layer1_marginal": layer1,
            "layer2_marginal": None,
            "severity": "LOW",
            "warning": "no conditional_on_scenarios block",
        }

    scenario_path = cond["source_matrix"]
    weights = load_weights_from_scenario(scenario_path)

    horizon = list(cond["by_scenario"]["A"]["values"].keys())[0]
    # Действующие веса — файл сайта рядом с матрицей (единый источник): на дату сравнения, интерполяцией
    # между сроками сайта. Файла нет — веса матрицы. Негодный файл — отказ (SiteWeightsError), не откат.
    site = _sw.load_site(_sw.site_file_for(scenario_path))
    if site is not None:
        hz = horizon.isoformat() if hasattr(horizon, "isoformat") else str(horizon)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", hz):     # горизонт-метка (не дата) — остаются веса матрицы
            weights = _sw.weights_on_dates(site, [hz])[0][hz]
    layer2 = aggregate_marginal(
        cond["by_scenario"], weights, horizon, method=cond["marginal"]["method"]
    )["central"]

    if layer1 is None or layer2 is None:
        return {"severity": "UNKNOWN"}

    # Edge case: layer1 == 0. Процентная divergence неопределена — используем
    # абсолютную метрику и UNKNOWN severity, если layer2 не равно 0.
    if layer1 == 0:
        if layer2 == 0:
            return {
                "layer1_marginal": 0.0,
                "layer2_marginal": 0.0,
                "divergence_pct": 0.0,
                "severity": "LOW",
                "warning": None,
            }
        return {
            "layer1_marginal": 0.0,
            "layer2_marginal": layer2,
            "divergence_abs": abs(layer2),
            "severity": "UNKNOWN",
            "warning": (
                f"Layer 1 marginal = 0; процентная divergence неопределена. "
                f"Абсолютное расхождение |layer2| = {abs(layer2):.4f}. "
                f"Проверьте central_estimate (возможно, парсинг вернул 0 на качественной строке)."
            ),
        }

    divergence_pct = abs(layer1 - layer2) / abs(layer1) * 100
    severity = (
        "LOW" if divergence_pct < 5
        else "MEDIUM" if divergence_pct < 15
        else "HIGH"
    )

    warning = None
    if severity != "LOW":
        warning = (
            f"Layer 1 marginal ({layer1:.2f}) расходится с Layer 2 marginal ({layer2:.2f}) "
            f"на {divergence_pct:.1f}%. Возможные причины: asymmetric coverage, "
            f"dominant HIGH-trust source, unequal weights с непропорциональными conditional values."
        )

    return {
        "layer1_marginal": layer1,
        "layer2_marginal": layer2,
        "divergence_pct": divergence_pct,
        "severity": severity,
        "warning": warning,
    }


# FCA-1: порог доли доминирующего лагеря, с которой распределение взглядов
# считается асимметричным. Provisional (как CONF_*-константы) — подкрутить
# после накопления resolved-исходов в outcome_log, не хардкодить по месту.
ASYMMETRY_CAMP_THRESHOLD = 0.7


def resolve_asymmetry(payload: dict) -> tuple[bool, list]:
    """FCA-1: asymmetry_warning вычисляется из camp_distribution, а не берётся на веру.

    Приоритет:
      1. `camp_distribution: {<лагерь>: int, …}` (счётчики источников по лагерям
         карты Шага 1.5; имена лагерей произвольные — bull/bear/neutral или
         Iran-side/Atlantic-side/…; в знаменателе ВСЕ ключи) → детерминированно:
         max_camp/total ≥ 0.7.
      2. Fallback (backward-compat): ручной bool `asymmetry_warning` из payload +
         warning {"type": "manual_asymmetry"} — сигнал, что LLM выставил флаг сам
         и число не проверено.
      3. Ни того ни другого → False без warning.

    Возвращает (asymmetry_warning, warnings_to_append).
    """
    camps = payload.get("camp_distribution")
    if camps is not None and not isinstance(camps, dict):
        # Битый ТИП поля — не глотать молча (аудит 2026-08-03): fallback с warning,
        # симметрично битым значениям внутри dict.
        return bool(payload.get("asymmetry_warning", False)), [{
            "type": "manual_asymmetry",
            "detail": f"camp_distribution не dict ({type(camps).__name__}) — fallback на ручной bool",
        }]
    if isinstance(camps, dict):
        # Счёт по ВСЕМ ключам-лагерям: SKILL Шаг 1.5 допускает произвольные имена
        # (Iran-side/Atlantic-side/…), жёсткая тройка bull/bear/neutral молча
        # выкидывала нестандартные лагеря из знаменателя (аудит 2026-08-03).
        counts = []
        for camp, v in camps.items():
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                return bool(payload.get("asymmetry_warning", False)), [{
                    "type": "manual_asymmetry",
                    "detail": f"camp_distribution.{camp} не неотрицательное целое ({v!r}) — fallback на ручной bool",
                }]
            counts.append(v)
        total = sum(counts)
        if total > 0:
            return (max(counts) / total) >= ASYMMETRY_CAMP_THRESHOLD, []
        return bool(payload.get("asymmetry_warning", False)), [{
            "type": "manual_asymmetry",
            "detail": "camp_distribution пуст (все счётчики 0) — fallback на ручной bool",
        }]
    if "asymmetry_warning" in payload:
        return bool(payload.get("asymmetry_warning")), [{"type": "manual_asymmetry"}]
    return False, []


def compute(payload: dict) -> dict:
    forecast_date = parse_date(payload.get("forecast_date"))
    asymmetry_warning, asymmetry_warnings = resolve_asymmetry(payload)
    sources = payload.get("sources") or []

    enriched = []
    fallback_medium_warnings: list[dict[str, str | None]] = []
    for src in sources:
        weight, matched_sub, is_fallback = applied_weight(src)
        horizon = parse_date(src.get("horizon_date"))
        enriched.append({
            "id": src.get("id"),
            "name": src.get("name"),
            "value": src.get("value"),
            "position": src.get("position"),
            "horizon_date": horizon,
            "weight": weight,
            "audited": src.get("audited", True),
            "matched_subdomain": matched_sub,
        })
        if is_fallback:
            fallback_medium_warnings.append({
                "type": "fallback_medium",
                "source": src.get("name") or src.get("id"),
                "subdomain": src.get("requested_subdomain"),
            })

    in_consensus = [s for s in enriched if s["weight"] > 0]
    outliers = [s for s in enriched if s["weight"] == 0 and s["audited"]]
    unaudited = [s for s in enriched if not s["audited"]]

    n_high = sum(1 for s in in_consensus if s["weight"] == 1.0)
    n_medium = sum(1 for s in in_consensus if s["weight"] == 0.5)

    has_numeric = any(s["value"] is not None for s in enriched)
    has_qualitative = any(s["position"] for s in enriched)
    if has_numeric and has_qualitative:
        kind = "mixed"
    elif has_numeric:
        kind = "numeric"
    elif has_qualitative:
        kind = "qualitative"
    else:
        kind = "empty"

    result: dict[str, Any] = {
        "kind": kind,
        "n_sources": {
            "high": n_high,
            "medium": n_medium,
            "low_or_ignore": len(outliers),
            "unaudited": len(unaudited),
            "in_consensus": len(in_consensus),
            "outliers": len(outliers),
            "total": len(enriched),
        },
        "applied_weights": [
            {
                "id": s["id"],
                "applied_weight": s["weight"],
                "matched_subdomain": s["matched_subdomain"],
                "audited": s["audited"],
            }
            for s in enriched
        ],
        "confidence": compute_confidence(n_high, len(in_consensus), asymmetry_warning),
        "asymmetry_warning": asymmetry_warning,
        "warnings": list(fallback_medium_warnings) + asymmetry_warnings,
    }

    if kind in ("numeric", "mixed"):
        weighted_pairs = [(s["value"], s["weight"]) for s in in_consensus if s["value"] is not None]
        all_values = [s["value"] for s in enriched if s["value"] is not None]
        if weighted_pairs:
            wm = weighted_median(weighted_pairs)
            result["weighted_median"] = round(wm, 4)
            tie = weighted_median_tie(weighted_pairs)
            if tie is not None:
                result["weighted_median_tie"] = [round(tie[0], 4), round(tie[1], 4)]
            result["p10"] = round(weighted_quantile(weighted_pairs, 0.10), 4)
            result["p90"] = round(weighted_quantile(weighted_pairs, 0.90), 4)
        else:
            result["weighted_median"] = None
            result["p10"] = None
            result["p90"] = None
            result["warnings"].append("no_weighted_numeric_sources")

        if all_values:
            um = statistics.median(all_values)
            result["unweighted_median"] = round(um, 4)
            if result["weighted_median"] is not None:
                result["filter_strength"] = round(abs(result["weighted_median"] - um), 4)
        else:
            result["unweighted_median"] = None

    if kind in ("qualitative", "mixed"):
        split: dict[str, dict[str, float]] = {}
        for s in in_consensus:
            pos = s.get("position")
            if not pos:
                continue
            entry = split.setdefault(pos, {"count": 0, "weight_sum": 0.0, "high": 0, "medium": 0})
            entry["count"] += 1
            entry["weight_sum"] += s["weight"]
            if s["weight"] == 1.0:
                entry["high"] += 1
            elif s["weight"] == 0.5:
                entry["medium"] += 1
        for v in split.values():
            v["weight_sum"] = round(v["weight_sum"], 4)
        result["split_by_position"] = split
        if split:
            result["modal_position"] = max(split.items(), key=lambda kv: kv[1]["weight_sum"])[0]
        else:
            result["modal_position"] = None
            result["warnings"].append("no_qualitative_sources_in_consensus")

    horizon_pairs = [(s["horizon_date"], s["weight"]) for s in in_consensus]
    horizon = weighted_horizon(horizon_pairs, forecast_date)
    result["horizon"] = horizon
    if horizon is None and in_consensus:
        result["warnings"].append("horizon_not_computable")

    interval_months = payload.get("interval_months_override")
    if interval_months is None:
        interval_months = DEFAULT_INTERVAL_MONTHS.get(payload.get("query_domain") or "", 6)
    if forecast_date is not None:
        result["reviews"] = {
            "interval_months": interval_months,
            "next_due": add_months(forecast_date, interval_months).isoformat(),
        }

    # --- F3 (аддитивно): честное имя coverage + anchor_share + per-horizon confidence ---
    # Скаляр `confidence` НЕ пересчитывается (legacy, нулевой дрейф). source_coverage_score —
    # то же число под честным именем; весь новый сигнал живёт в confidence_by_horizon.
    result["source_coverage_score"] = result["confidence"]
    cons_weights = [s["weight"] for s in in_consensus]
    total_w = sum(cons_weights)
    result["anchor_share"] = round(max(cons_weights) / total_w, 4) if total_w > 0 else None
    result["confidence_by_horizon"] = compute_confidence_by_horizon(
        result["source_coverage_score"], result["anchor_share"],
        in_consensus, forecast_date, _resolve_target_horizons(payload, in_consensus))

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Weighted consensus calculator for forecast-confidence-applier.")
    parser.add_argument("--input", "-i", help="Path to JSON input (default: stdin)")
    parser.add_argument("--output", "-o", help="Path to JSON output (default: stdout)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            payload = json.load(f)
    else:
        payload = json.load(sys.stdin)

    result = compute(payload)

    indent = 2 if args.pretty else None
    serialized = json.dumps(result, ensure_ascii=False, indent=indent)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(serialized)
            f.write("\n")
    else:
        print(serialized)

    return 0


if __name__ == "__main__":
    sys.exit(main())
