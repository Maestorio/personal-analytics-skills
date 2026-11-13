#!/usr/bin/env python3
"""similarity_score.py — детерминированная арифметика Stage 2.

**Контракт формата** (категории `HIGH/MEDIUM/LOW/OUTLIER/UNSCORED`, 6 компонентов
`COMPONENT_NAMES`, пороги — этот скрипт их вычисляет) — канон
`references/stage2/stage2-output-spec.md`; согласованность копий с ним проверяет
`tests/test_format_contract.py`.

Принимает JSON со списком авторов (LLM проставила 6 компонентов 0–10,
outlier_signal и user_added), возвращает JSON с total_score, категорией,
confidence, components_known, warnings и reading_list.

Граница LLM vs скрипт:
- LLM: парсит карточки 20-field, проставляет components, определяет
  outlier_signal (есть ли уникальный сильный сигнал, релевантный профилю).
- Скрипт: нормализует веса при null-компонентах, агрегирует, категоризирует,
  считает распределения, генерирует warnings.

Использование:
    python3 similarity_score.py < input.json > output.json
    python3 similarity_score.py --archetype семья_с_детьми < input.json
    python3 similarity_score.py --weights 25,25,15,10,15,10 < input.json
    python3 similarity_score.py --thresholds 7.0,5.0 < input.json

Приоритет источников весов (выше — перебивает ниже):
    1. CLI --weights (raw 6 чисел)
    2. CLI --archetype (лукап ARCHETYPE_WEIGHTS)
    3. payload.similarity_weights_override (русские ключи стиль/фокус/...)
    4. payload.weights (raw 6 чисел)
    5. payload.группа_архетип (лукап ARCHETYPE_WEIGHTS)
    6. DEFAULT_WEIGHTS (backward-compat = "самостоятельные")

Архетип резолвится через ARCHETYPE_ALIASES: legacy-имя
`независимые_соло_пара` → каноническое `самостоятельные`.

Входной JSON:
    {
      "authors": [
        {
          "id": "vietnam-helvhrav-001",
          "url": "https://forum.awd.ru/...",
          "name": "helvhrav",
          "components": {
            "style": 8.0,
            "focus": 7.5,
            "pace": null,
            "independence": 10.0,
            "depth": 9.0,
            "demo": 6.0
          },
          "outlier_signal": {"present": false, "description": ""},
          "user_added": false
        },
        ...
      ],
      "группа_архетип": "самостоятельные",          // опц., из YAML профиля
                                                    // (legacy-алиас независимые_соло_пара тоже принимается)
      "similarity_weights_override": {              // опц., перекрывает архетип
        "стиль": 30, "фокус": 25, "темп": 15,
        "независимость": 5, "non_touristy": 15, "возраст_состав": 10
      },
      "weights": [25, 25, 15, 10, 15, 10],   // опц., raw веса (legacy)
      "thresholds": [7.0, 5.0]                // опц., [high, medium]
    }

Выходной JSON:
    {
      "scored_authors": [
        {
          "id": "...", "url": "...", "name": "...",
          "components": {...},                     // as input
          "components_known": int,
          "effective_weights": {component: pct},  // нормализованные веса в %
          "weighted_contributions": {              // вклад каждого компонента
            "style": float,                        // value × eff_weight / 100
            "focus": float,
            ...
          },
          "total_score": float,                    // = сумма weighted_contributions
          "category": "HIGH|MEDIUM|LOW|OUTLIER|UNSCORED",
          "confidence": "full|partial|low|unscored",
          "low_confidence_flag": bool,
          "outlier_signal": {...},
          "user_added": bool,
          "in_reading_list": bool,                 // = HIGH + OUTLIER
          "in_extended_reading_list": bool         // MEDIUM >= 6.5
        }
      ],
      "distribution": {"high": N, "medium": N, "low": N, "outlier": N,
                       "unscored": N, "total": N},
      "confidence_breakdown": {"full": N, "partial": N, "low": N, "unscored": N},
      "warnings": [{"severity": "...", "message": "..."}],
      "reading_list": ["id1", "id2", ...],
      "reading_list_extended": ["id3", ...],       // MEDIUM с total >= 6.5
      "unscored_with_signal": ["id4", ...],
      "weights_used": [25, 25, 15, 10, 15, 10],
      "weights_source": "default | archetype | override | cli_weights | cli_archetype | payload_weights",
      "archetype_used": "самостоятельные" | null,   // всегда каноническое имя (алиас уже резолвлен)
      "thresholds_used": {"high": 7.0, "medium": 5.0,
                          "medium_high_borderline": 6.5}
    }
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# taxonomy — словарь таксонов (рядом, scripts/taxonomy.py).
try:
    import taxonomy
except ModuleNotFoundError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import taxonomy

# 6 компонентов similarity в порядке, заданном методологией.
COMPONENT_NAMES = ["style", "focus", "pace", "independence", "depth", "demo"]


def _canon_components(components: dict) -> dict:
    """Нормализовать ключи компонентов входа (EN/RU) к каноническим EN.

    Защита от русских/алиасных имён компонентов от LLM — контракт выхода
    остаётся в EN (COMPONENT_NAMES). Неизвестные ключи сохраняются как есть."""
    if not isinstance(components, dict):
        return components
    out: dict = {}
    for k, v in components.items():
        out[taxonomy.canon("similarity_component", k) or k] = v
    return out

# Дефолтные веса 25/25/15/10/15/10 (sum=100) — равны архетипу
# "самостоятельные". Сохраняются для backward-compat без архетипа.
DEFAULT_WEIGHTS = [25.0, 25.0, 15.0, 10.0, 15.0, 10.0]

# Веса по архетипам группы (см. references/profile-management.md §7.5).
# Порядок весов соответствует COMPONENT_NAMES.
# Сумма каждого списка должна быть 100.
ARCHETYPE_WEIGHTS: dict[str, list[float]] = {
    "самостоятельные":  [25.0, 25.0, 15.0, 10.0, 15.0, 10.0],
    "семья_с_детьми":   [20.0, 20.0, 25.0,  5.0,  5.0, 25.0],
    "взрослые_50_плюс": [15.0, 15.0, 25.0,  5.0,  5.0, 35.0],
    "люкс":             [30.0, 20.0, 15.0,  5.0, 10.0, 20.0],
}

# Legacy-алиасы архетипов: старое имя → каноническое. Профили v0.22 и ранее
# могли сохранить `родители_60_плюс`; резолвим их в текущее `взрослые_50_плюс`.
# Профили и артефакты поездок до переименования хранят `независимые_соло_пара`;
# резолвим в `самостоятельные`, чтобы они не падали с «неизвестный архетип».
ARCHETYPE_ALIASES: dict[str, str] = {
    "родители_60_плюс": "взрослые_50_плюс",
    "независимые_соло_пара": "самостоятельные",
}

# Допустимые ключи в similarity_weights_override (русские имена компонентов).
OVERRIDE_KEY_TO_INDEX: dict[str, int] = {
    "стиль": 0,
    "фокус": 1,
    "темп": 2,
    "независимость": 3,
    "non_touristy": 4,
    "возраст_состав": 5,
}

# Пороги категоризации.
DEFAULT_HIGH_THRESHOLD = 7.0
DEFAULT_MEDIUM_THRESHOLD = 5.0
DEFAULT_MEDIUM_HIGH_BORDERLINE = 6.5  # MEDIUM >= 6.5 → reading_list_extended

# Пороги для warning-логики (см. methodology + storage-and-naming §6.3).
HIGH_COUNT_CRITICAL = 5    # < 5 в HIGH → critical
HIGH_COUNT_BORDERLINE = 8  # 5 <= N < 8 → borderline

# Пороги для UNSCORED и low_confidence (см. обсуждение в чате).
UNSCORED_KNOWN_THRESHOLD = 3      # components_known < 3 → UNSCORED
LOW_CONFIDENCE_KNOWN_THRESHOLD = 4  # components_known < 4 → low_confidence-флаг

# Anti-bloat: если OUTLIER занимает >30% выборки, категория размывается
# и теряет смысл «уникальный сильный сигнал». 30% — практический потолок.
OUTLIER_BLOAT_THRESHOLD = 0.30


def canonical_archetype(archetype: str | None) -> str | None:
    """Имя архетипа в каноническом виде: legacy-алиас → текущее имя.

    Неизвестные имена возвращаются как есть (валидация — в
    resolve_weights_from_archetype).
    """
    if archetype is None:
        return None
    return ARCHETYPE_ALIASES.get(archetype, archetype)


def resolve_weights_from_archetype(archetype: str | None) -> list[float] | None:
    """Возвращает дефолтные веса для архетипа, либо None если архетип не задан.

    Если архетип задан, но неизвестен — ValueError.
    """
    if archetype is None:
        return None
    archetype = canonical_archetype(archetype)
    if archetype not in ARCHETYPE_WEIGHTS:
        valid = ", ".join(sorted(ARCHETYPE_WEIGHTS))
        raise ValueError(
            f"Неизвестный архетип '{archetype}'. Допустимо: {valid}."
        )
    return list(ARCHETYPE_WEIGHTS[archetype])


def resolve_override_weights(override: dict[str, float] | None) -> list[float] | None:
    """Парсит similarity_weights_override → 6 весов в порядке COMPONENT_NAMES.

    Возвращает None если override не задан. ValueError при невалидных
    ключах или сумме != 100.
    """
    if override is None:
        return None
    if not isinstance(override, dict):
        raise ValueError("similarity_weights_override должен быть объектом.")

    weights: list[float | None] = [None] * 6
    unknown_keys = [k for k in override if k not in OVERRIDE_KEY_TO_INDEX]
    if unknown_keys:
        raise ValueError(
            f"similarity_weights_override содержит неизвестные ключи: "
            f"{unknown_keys}. Допустимо: {sorted(OVERRIDE_KEY_TO_INDEX)}."
        )
    for key, idx in OVERRIDE_KEY_TO_INDEX.items():
        if key not in override:
            raise ValueError(
                f"similarity_weights_override: не хватает ключа '{key}'. "
                "Override должен содержать все 6 компонентов."
            )
        try:
            weights[idx] = float(override[key])
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"similarity_weights_override['{key}']: ожидается число, "
                f"получено {override[key]!r} ({e})."
            )

    weights_concrete = [w for w in weights if w is not None]
    total = sum(weights_concrete)
    if abs(total - 100.0) > 0.01:
        raise ValueError(
            f"similarity_weights_override: сумма весов {total} ≠ 100. "
            "Скорректируй веса."
        )
    return weights_concrete


def normalize_weights(raw_weights: list[float], known_mask: list[bool]) -> list[float]:
    """Перераспределяет веса на известные компоненты.

    Если все 6 компонентов известны — возвращает raw_weights as is.
    Если N из 6 известны — веса известных пропорционально нормируются до
    суммы исходных raw_weights (обычно 100).

    Пример: raw=[25,25,15,10,15,10], known=[T,T,F,T,T,T]
    → известные веса = [25,25,_,10,15,10], сумма=85
    → нормировка коэффициент = 100/85
    → эффективные = [29.41, 29.41, 0, 11.76, 17.65, 11.76]

    Args:
        raw_weights: список из 6 базовых весов.
        known_mask: список из 6 bool — известен ли каждый компонент.

    Returns:
        Список из 6 эффективных весов (0 для неизвестных).
    """
    if len(raw_weights) != 6 or len(known_mask) != 6:
        raise ValueError("weights и mask должны быть длины 6")

    target_sum = sum(raw_weights)
    known_sum = sum(w for w, k in zip(raw_weights, known_mask) if k)

    if known_sum == 0:
        return [0.0] * 6

    scale = target_sum / known_sum
    return [
        w * scale if k else 0.0
        for w, k in zip(raw_weights, known_mask)
    ]


def score_author(
    author: dict[str, Any],
    raw_weights: list[float],
    high_threshold: float,
    medium_threshold: float,
    medium_high_borderline: float = DEFAULT_MEDIUM_HIGH_BORDERLINE,
) -> dict[str, Any]:
    """Считает total_score, категорию, confidence для одного автора.

    Args:
        author: входная карточка автора (см. docstring модуля).
        raw_weights: 6 базовых весов.
        high_threshold: порог для HIGH.
        medium_threshold: порог для MEDIUM.

    Returns:
        Расширенная карточка с total_score, category, confidence,
        components_known, effective_weights, in_reading_list.
    """
    components = _canon_components(author.get("components", {}))
    component_values = [components.get(name) for name in COMPONENT_NAMES]
    known_mask = [v is not None for v in component_values]
    components_known = sum(known_mask)

    # Confidence — производна от количества известных компонентов.
    if components_known == 6:
        confidence = "full"
    elif components_known >= LOW_CONFIDENCE_KNOWN_THRESHOLD:
        confidence = "partial"
    elif components_known >= UNSCORED_KNOWN_THRESHOLD:
        confidence = "low"
    else:
        confidence = "unscored"

    effective_weights = normalize_weights(raw_weights, known_mask)

    # Total = sum(value * effective_weight) / sum(effective_weights). При full
    # это эквивалентно sum(value*w) / 100. При normalized — то же, потому что
    # sum(effective_weights) == sum(raw_weights) для случая когда хоть один
    # известен.
    weights_sum = sum(effective_weights)
    if weights_sum == 0:
        total_score = 0.0
        weighted_contributions_list = [0.0] * 6
    else:
        # contribution[i] = value[i] × eff_weight[i] / weights_sum × 10
        # Тождественно: value[i] × (eff_weight[i] / weights_sum) × 10, где
        # eff_weight[i] / weights_sum — нормированная доля. Сумма contributions
        # == total_score, по построению.
        weighted_contributions_list = [
            (v if v is not None else 0.0) * w / weights_sum
            for v, w in zip(component_values, effective_weights)
        ]
        total_score = sum(weighted_contributions_list)

    outlier_signal = author.get("outlier_signal") or {"present": False, "description": ""}
    signal_present = bool(outlier_signal.get("present", False))

    # Категоризация. UNSCORED перебивает всё (мало данных для категоризации).
    if confidence == "unscored":
        category = "UNSCORED"
    elif total_score >= high_threshold:
        category = "HIGH"
    elif total_score >= medium_threshold:
        category = "OUTLIER" if signal_present else "MEDIUM"
    else:
        category = "OUTLIER" if signal_present else "LOW"

    low_confidence_flag = (
        category in {"HIGH", "OUTLIER"}
        and components_known < LOW_CONFIDENCE_KNOWN_THRESHOLD
    )

    # Reading list: HIGH и OUTLIER. UNSCORED — нет, даже с signal
    # (учитывается отдельно в unscored_with_signal).
    in_reading_list = category in {"HIGH", "OUTLIER"}

    # Extended reading list — MEDIUM с borderline-high score.
    # Те, кто близок к HIGH, но не дотянул. Порог: total >= 6.5.
    in_extended_reading_list = (
        category == "MEDIUM" and total_score >= medium_high_borderline
    )

    result = {
        "id": author.get("id"),
        "url": author.get("url"),
        "name": author.get("name"),
        "components": components,
        "components_known": components_known,
        "effective_weights": {
            name: round(w, 4)
            for name, w in zip(COMPONENT_NAMES, effective_weights)
        },
        "weighted_contributions": {
            name: round(c, 4)
            for name, c in zip(COMPONENT_NAMES, weighted_contributions_list)
        },
        "total_score": round(total_score, 2),
        "category": category,
        # Аддитивное display-поле (Фаза 1): русский ярлык категории.
        # Контракт EN-поля `category` не меняется.
        "category_label": taxonomy.label("author_category", category),
        "confidence": confidence,
        "low_confidence_flag": low_confidence_flag,
        "outlier_signal": outlier_signal,
        "user_added": bool(author.get("user_added", False)),
        "in_reading_list": in_reading_list,
        "in_extended_reading_list": in_extended_reading_list,
    }
    return result


def build_warnings(
    distribution: dict[str, int],
    scored_authors: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Собирает warnings по итогам категоризации."""
    warnings: list[dict[str, str]] = []
    high = distribution["high"]
    unscored = distribution["unscored"]

    # Размер HIGH-выборки.
    if high < HIGH_COUNT_CRITICAL:
        warnings.append({
            "severity": "critical",
            "message": (
                f"HIGH = {high} (< {HIGH_COUNT_CRITICAL}): выборка крайне узкая. "
                "Серьёзно расширь источники (Stage 1 Mode B) перед Stage 3, "
                "иначе POI-агрегация будет на 2–4 авторах."
            ),
        })
    elif high < HIGH_COUNT_BORDERLINE:
        warnings.append({
            "severity": "borderline",
            "message": (
                f"HIGH = {high} (< {HIGH_COUNT_BORDERLINE}): выборка пограничная. "
                "Рассмотри расширение источников — Stage 3 будет работоспособен, "
                "но статистика на грани."
            ),
        })

    # Низкая уверенность в HIGH/OUTLIER.
    low_conf_in_reading = sum(
        1 for a in scored_authors
        if a["in_reading_list"] and a["low_confidence_flag"]
    )
    if low_conf_in_reading:
        warnings.append({
            "severity": "info",
            "message": (
                f"{low_conf_in_reading} автор(ов) в reading list с малыми данными "
                f"(components_known < {LOW_CONFIDENCE_KNOWN_THRESHOLD}). Категория "
                "поставлена на 3 компонентах из 6 — учитывай при чтении."
            ),
        })

    # UNSCORED — есть ли вообще, есть ли среди них с signal.
    if unscored:
        unscored_with_signal = sum(
            1 for a in scored_authors
            if a["category"] == "UNSCORED" and a["outlier_signal"].get("present")
        )
        if unscored_with_signal:
            warnings.append({
                "severity": "info",
                "message": (
                    f"{unscored} автор(ов) UNSCORED (components_known < "
                    f"{UNSCORED_KNOWN_THRESHOLD}), из них {unscored_with_signal} "
                    "с outlier-сигналом — перечислены в unscored_with_signal, "
                    "не вошли в reading list автоматически."
                ),
            })
        else:
            warnings.append({
                "severity": "info",
                "message": (
                    f"{unscored} автор(ов) UNSCORED (components_known < "
                    f"{UNSCORED_KNOWN_THRESHOLD}) — отбракованы из-за нехватки данных."
                ),
            })

    # Anti-bloat OUTLIER. Если доля OUTLIER в выборке выше порога —
    # категория размывается и теряет смысл «уникального сильного сигнала».
    outlier = distribution["outlier"]
    total = distribution["total"]
    if total > 0:
        outlier_share = outlier / total
        if outlier_share > OUTLIER_BLOAT_THRESHOLD:
            warnings.append({
                "severity": "critical",
                "message": (
                    f"OUTLIER = {outlier}/{total} ({outlier_share:.0%}): "
                    f"доля выше порога {OUTLIER_BLOAT_THRESHOLD:.0%} — "
                    "категория размывается. Методика OUTLIER требует "
                    "«уникального сильного сигнала», но он не может быть "
                    "у половины выборки. Пересмотри outlier_signal по "
                    "каждому автору и убери present=true там, где сигнал "
                    "не уникален (есть у >2 других авторов) или не "
                    "релевантен профилю напрямую."
                ),
            })

    # user_added в LOW — полезная калибровочная информация для пользователя.
    user_added_below_high = sum(
        1 for a in scored_authors
        if a["user_added"] and a["category"] in {"LOW", "MEDIUM"}
    )
    if user_added_below_high:
        warnings.append({
            "severity": "info",
            "message": (
                f"{user_added_below_high} вручную добавленных автора(ов) "
                "получили score ниже HIGH. Это нормально (визуальная привлекательность "
                "≠ similarity с профилем), но если повторяется системно — стоит "
                "пересмотреть либо профиль, либо критерии добавления."
            ),
        })

    # Аддитивное display-поле (Фаза 1): русский ярлык severity рядом с
    # машинным `severity`. Контракт EN-поля не меняется.
    for w in warnings:
        w["severity_label"] = taxonomy.label("warning_severity", w["severity"])
    return warnings


def aggregate(
    authors: list[dict[str, Any]],
    raw_weights: list[float],
    high_threshold: float,
    medium_threshold: float,
    medium_high_borderline: float = DEFAULT_MEDIUM_HIGH_BORDERLINE,
    archetype_used: str | None = None,
    weights_source: str = "default",
) -> dict[str, Any]:
    """Главная функция: сквозной проход по списку авторов."""
    scored = [
        score_author(
            a, raw_weights, high_threshold, medium_threshold,
            medium_high_borderline,
        )
        for a in authors
    ]

    distribution = {
        "high": sum(1 for a in scored if a["category"] == "HIGH"),
        "medium": sum(1 for a in scored if a["category"] == "MEDIUM"),
        "low": sum(1 for a in scored if a["category"] == "LOW"),
        "outlier": sum(1 for a in scored if a["category"] == "OUTLIER"),
        "unscored": sum(1 for a in scored if a["category"] == "UNSCORED"),
        "total": len(scored),
    }

    confidence_breakdown = {
        "full": sum(1 for a in scored if a["confidence"] == "full"),
        "partial": sum(1 for a in scored if a["confidence"] == "partial"),
        "low": sum(1 for a in scored if a["confidence"] == "low"),
        "unscored": sum(1 for a in scored if a["confidence"] == "unscored"),
    }

    warnings = build_warnings(distribution, scored)

    reading_list = [a["id"] for a in scored if a["in_reading_list"]]
    reading_list_extended = [
        a["id"] for a in scored if a["in_extended_reading_list"]
    ]
    unscored_with_signal = [
        a["id"] for a in scored
        if a["category"] == "UNSCORED" and a["outlier_signal"].get("present")
    ]

    return {
        "scored_authors": scored,
        "distribution": distribution,
        "confidence_breakdown": confidence_breakdown,
        "warnings": warnings,
        "reading_list": reading_list,
        "reading_list_extended": reading_list_extended,
        "unscored_with_signal": unscored_with_signal,
        "weights_used": raw_weights,
        "weights_source": weights_source,
        "archetype_used": archetype_used,
        "thresholds_used": {
            "high": high_threshold,
            "medium": medium_threshold,
            "medium_high_borderline": medium_high_borderline,
        },
    }


def parse_weights_arg(arg: str) -> list[float]:
    """Парсит CLI --weights 25,25,15,10,15,10 → [25.0, ...]."""
    parts = arg.split(",")
    if len(parts) != 6:
        raise argparse.ArgumentTypeError("weights должно быть ровно 6 чисел через запятую")
    try:
        return [float(p.strip()) for p in parts]
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"weights — все значения должны быть числами: {e}")


def parse_thresholds_arg(arg: str) -> tuple[float, float]:
    """Парсит CLI --thresholds 7.0,5.0 → (7.0, 5.0)."""
    parts = arg.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("thresholds должно быть ровно 2 числа через запятую (high,medium)")
    try:
        high = float(parts[0].strip())
        medium = float(parts[1].strip())
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"thresholds — оба значения должны быть числами: {e}")
    if not (0 <= medium < high <= 10):
        raise argparse.ArgumentTypeError("требуется 0 <= medium < high <= 10")
    return high, medium


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Similarity-score агрегатор для Stage 2 travel-planning",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--weights",
        type=parse_weights_arg,
        default=None,
        help="6 весов через запятую (style,focus,pace,independence,depth,demo). "
             "Перебивает входной JSON и --archetype. Дефолт: 25,25,15,10,15,10",
    )
    parser.add_argument(
        "--archetype",
        type=str,
        default=None,
        choices=sorted(ARCHETYPE_WEIGHTS) + sorted(ARCHETYPE_ALIASES),
        help="Архетип группы — лукап предзаданных весов. Перебивает входной "
             "JSON, но перебивается --weights. См. references/profile-management.md §7.5.",
    )
    parser.add_argument(
        "--thresholds",
        type=parse_thresholds_arg,
        default=None,
        help="Пороги high,medium через запятую. Перебивает входной JSON. "
             "Дефолт: 7.0,5.0",
    )
    parser.add_argument(
        "--medium-high-borderline",
        type=float,
        default=None,
        help="Порог для reading_list_extended (MEDIUM с total >= порог). "
             "Перебивает входной JSON. Дефолт: 6.5",
    )
    args = parser.parse_args()

    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Ошибка парсинга stdin JSON: {e}", file=sys.stderr)
        return 2

    if not isinstance(payload, dict) or "authors" not in payload:
        print("Ожидается JSON-объект с полем 'authors' (список).", file=sys.stderr)
        return 2

    authors = payload["authors"]
    if not isinstance(authors, list):
        print("'authors' должен быть списком.", file=sys.stderr)
        return 2

    # Приоритет резолва весов (выше — перебивает ниже):
    # 1. CLI --weights
    # 2. CLI --archetype
    # 3. payload.similarity_weights_override
    # 4. payload.weights
    # 5. payload.группа_архетип
    # 6. DEFAULT_WEIGHTS
    raw_weights: list[float] | None = None
    weights_source = "default"
    archetype_used: str | None = None

    if args.weights:
        raw_weights = list(args.weights)
        weights_source = "cli_weights"
    elif args.archetype:
        try:
            raw_weights = resolve_weights_from_archetype(args.archetype)
        except ValueError as e:
            print(f"Ошибка --archetype: {e}", file=sys.stderr)
            return 2
        archetype_used = canonical_archetype(args.archetype)
        weights_source = "cli_archetype"
    else:
        try:
            override_weights = resolve_override_weights(
                payload.get("similarity_weights_override")
            )
        except ValueError as e:
            print(f"Ошибка similarity_weights_override: {e}", file=sys.stderr)
            return 2

        if override_weights is not None:
            raw_weights = override_weights
            weights_source = "override"
            # Архетип всё равно фиксируем для traceability, если был.
            archetype_used = canonical_archetype(payload.get("группа_архетип"))
        elif payload.get("weights"):
            raw_weights = list(payload["weights"])
            weights_source = "payload_weights"
            archetype_used = canonical_archetype(payload.get("группа_архетип"))
        else:
            payload_archetype = payload.get("группа_архетип")
            if payload_archetype:
                try:
                    raw_weights = resolve_weights_from_archetype(payload_archetype)
                except ValueError as e:
                    print(f"Ошибка payload.группа_архетип: {e}", file=sys.stderr)
                    return 2
                archetype_used = canonical_archetype(payload_archetype)
                weights_source = "archetype"
            else:
                raw_weights = list(DEFAULT_WEIGHTS)
                weights_source = "default"

    if raw_weights is None or len(raw_weights) != 6:
        print("weights должен содержать ровно 6 значений.", file=sys.stderr)
        return 2

    if args.thresholds:
        high_thr, medium_thr = args.thresholds
    else:
        payload_thresholds = payload.get("thresholds")
        if payload_thresholds and len(payload_thresholds) == 2:
            high_thr, medium_thr = payload_thresholds
        else:
            high_thr, medium_thr = DEFAULT_HIGH_THRESHOLD, DEFAULT_MEDIUM_THRESHOLD

    # medium_high_borderline: CLI > payload > computed default.
    # Дефолт = в верхних 75% MEDIUM-диапазона. При стандартных порогах
    # (high=7, medium=5) это 6.5. При кастомных high=6, medium=4 — 5.5.
    if args.medium_high_borderline is not None:
        mh_borderline = args.medium_high_borderline
    elif "medium_high_borderline" in payload:
        mh_borderline = payload["medium_high_borderline"]
    else:
        # Default 6.5 при стандартных порогах; иначе — пропорционально.
        if high_thr == DEFAULT_HIGH_THRESHOLD and medium_thr == DEFAULT_MEDIUM_THRESHOLD:
            mh_borderline = DEFAULT_MEDIUM_HIGH_BORDERLINE
        else:
            mh_borderline = medium_thr + (high_thr - medium_thr) * 0.75
    if not (medium_thr <= mh_borderline <= high_thr):
        print(
            f"medium_high_borderline ({mh_borderline}) должен быть "
            f"между medium ({medium_thr}) и high ({high_thr}).",
            file=sys.stderr,
        )
        return 2

    result = aggregate(
        authors, list(raw_weights), high_thr, medium_thr, mh_borderline,
        archetype_used=archetype_used,
        weights_source=weights_source,
    )
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
