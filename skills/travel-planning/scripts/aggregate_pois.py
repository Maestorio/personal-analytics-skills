#!/usr/bin/env python3
"""aggregate_pois.py — детерминированная агрегация POI Stage 3.

**Контракт формата** (6 POI-категорий `CATEGORY_RANK`, `VALID_AUTHOR_CATEGORIES` —
этот скрипт их вычисляет) — канон `references/stage3/stage3-output-spec.md`;
согласованность копий с ним проверяет `tests/test_format_contract.py`.

На входе — JSON-payload от LLM: список нормализованных POI с упоминаниями
(каждое упоминание — автор + его similarity-категория + тональность).
Скрипт считает упоминания, применяет 6 правил категоризации, формирует
агрегаты и anti-bloat warnings.

Граница LLM vs скрипт:
- LLM: извлекает POI из карточек, нормализует имена, проставляет
  тональность, пишет цитаты и характеристики места.
- Скрипт (этот файл): считает, категоризирует, агрегирует. Никакой
  семантики — только арифметика и детерминированные правила.

Шесть категорий (правила по приоритету сверху вниз):
  CONTESTED        — high_recommend >= 1 И high_neg >= 1
                     ИЛИ (scarce И high_recommend == 0 И non_high_negative >= 2)
  RED_FLAG         — high_neg >= 1 И high_recommend == 0 И low_recommend >= 1
                     ИЛИ (scarce И high_recommend == 0 И non_high_negative >= 3)
  STRONG_CONFIRMED — high_recommend >= 3 И high_neg == 0
  WEAK_CONFIRMED   — high_recommend == 2 (abundant) / 1–2 (scarce),
                     high_neg == 0 И non_high_total > 0
  HIDDEN_GEM       — high_recommend in {1,2} И high_neg == 0 И non_high_total == 0
  LOW_SIGNAL       — всё остальное
где high_neg = high_criticize + high_regret_visited; non_high_negative —
critic+regret_visited упоминания от OUTLIER/MEDIUM/LOW авторов.

В scarce-режиме RED_FLAG/CONTESTED имеют **вторую ветку** генерации,
которая срабатывает при отсутствии HIGH-recommend и достаточной
non-HIGH критике. Это закрывает математическую невозможность ветки 1
при узкой HIGH-когорте (Vietnam: 4 HIGH из 43).

Два режима категоризации (по доле HIGH = high_authors / total_authors):
- abundant (доля >= порога) — консервативно, WEAK требует high_recommend==2;
- scarce   (доля <  порога) — WEAK допускает high_recommend==1 (с
  non_high_total>0), чтобы место с одной HIGH-рекомендацией +
  подтверждением не падало в LOW_SIGNAL.
Отличаются ТОЛЬКО правилом WEAK_CONFIRMED. Режим — авто по доле, либо
форс через --mode.

Использование:
    echo '<payload>' | python3 aggregate_pois.py
    python3 aggregate_pois.py < payload.json
    python3 aggregate_pois.py --strong-min 3 --bloat-strong 0.5 < payload.json

Входной JSON:
    {
      "trip_slug": "аргентина_юг_2025-03",
      "pois": [
        {
          "name_ru": "Лагуна-де-лос-Трес",
          "name_local": "Laguna de los Tres",
          "region": "лос_гласьярес_чальтен",
          "mentions": [
            {"author_id": "...", "author_category": "HIGH", "tonality": "recommend"}
          ],
          "quotes": ["..."],
          "characteristics": "..."
        }
      ]
    }

Выходной JSON: trip_slug, region_order, aggregates, warnings, diagnostic,
pois[] (с counts + category, отсортирован region-first для §8). quotes и
characteristics пробрасываются без изменений.

Exit codes:
- 0 — обработан хотя бы 1 POI (LLM решает по diagnostic.status).
- 1 — пустой список pois.
- 2 — пустой stdin или невалидный JSON.
"""

from __future__ import annotations

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


def _canon_author_cat(v: Any) -> Any:
    """Категория автора (EN/RU) → канонический EN ('HIGH' …); None/мусор — как есть."""
    return taxonomy.canon("author_category", v) or v


def _canon_tonality(v: Any) -> Any:
    """Тональность (EN/RU) → канонический EN ('recommend' …); None/мусор — как есть."""
    return taxonomy.canon("tonality", v) or v


# Пороги категоризации.
DEFAULT_STRONG_MIN_RECOMMEND = 3   # high_recommend >= N → кандидат STRONG
WEAK_RECOMMEND = 2                 # high_recommend == N → кандидат WEAK / HIDDEN GEM

# Режим категоризации: доля HIGH = high_authors / total_authors.
DEFAULT_HIGH_SHARE_THRESHOLD = 0.30  # >= порога → abundant, иначе → scarce
ABS_FLOOR_HIGH_AUTHORS = 8           # fallback-порог, если total_authors неизвестен

# Per-region режим — порог HIGH-авторов на регион.
# Если у региона < N распознанных HIGH-авторов → scarce для этого региона.
# Решает кейс «глобально abundant, но один регион имеет мало HIGH-авторов»
# (часть регионов поездки — каноническое ядро страны с высоким HIGH-coverage,
# часть — второстепенные с 0-1 HIGH). Глобальный режим терял эту разницу:
# второстепенный регион не получал RED_FLAG по scarce-ветке.
DEFAULT_PER_REGION_HIGH_FLOOR = 3

# Пороги anti-bloat warnings.
DEFAULT_BLOAT_STRONG_RATIO = 0.50   # STRONG CONFIRMED > доля → warning
DEFAULT_BLOAT_REDFLAG_RATIO = 0.30  # RED FLAG > доля → warning

VALID_AUTHOR_CATEGORIES = {"HIGH", "OUTLIER", "MEDIUM", "LOW"}
VALID_TONALITIES = {
    "recommend", "neutral", "criticize", "regret_visited", "regret_missed",
}

# Порядок категорий для сортировки выходного списка.
CATEGORY_RANK = {
    "STRONG_CONFIRMED": 0,
    "WEAK_CONFIRMED": 1,
    "HIDDEN_GEM": 2,
    "CONTESTED": 3,
    "RED_FLAG": 4,
    "LOW_SIGNAL": 5,
}

NO_REGION_BUCKET = "без_региона"


def count_mentions(
    mentions: Any, poi_label: str, issues: list[dict[str, Any]],
) -> dict[str, int]:
    """Считает упоминания POI по категории автора и тональности.

    Невалидные упоминания (не dict, неизвестная категория/тональность)
    пропускаются и фиксируются как issue `invalid_mention`.
    """
    c = {
        "high_recommend": 0, "high_neutral": 0, "high_criticize": 0,
        "high_regret_visited": 0, "high_regret_missed": 0, "high_count": 0,
        "outlier_count": 0, "medium_count": 0,
        "low_count": 0, "low_recommend": 0,
        # non_high_negative — обоснованная критика (criticize или regret_visited)
        # от OUTLIER / MEDIUM / LOW авторов. Используется scarce-веткой
        # CONTESTED/RED_FLAG в categorize().
        "non_high_negative": 0,
        # outlier_negative — обоснованная критика от OUTLIER авторов
        # отдельно (подмножество non_high_negative). Используется F-55
        # веткой 3 CONTESTED (lone OUTLIER overrated сигнал).
        "outlier_negative": 0,
        "non_high_total": 0, "total_mentions": 0,
    }
    if not isinstance(mentions, list):
        issues.append({
            "severity": "error",
            "code": "invalid_mention",
            "message": f"POI «{poi_label}»: поле mentions не список.",
            "affected_pois": [poi_label],
        })
        return c

    low_non_recommend = 0
    for m in mentions:
        if not isinstance(m, dict):
            issues.append({
                "severity": "error",
                "code": "invalid_mention",
                "message": f"POI «{poi_label}»: упоминание не объект.",
                "affected_pois": [poi_label],
            })
            continue
        # Двуязычный приём: RU-синонимы категории/тональности → канонический EN.
        cat = _canon_author_cat(m.get("author_category"))
        ton = _canon_tonality(m.get("tonality"))
        if cat not in VALID_AUTHOR_CATEGORIES or ton not in VALID_TONALITIES:
            issues.append({
                "severity": "error",
                "code": "invalid_mention",
                "message": (
                    f"POI «{poi_label}»: упоминание с невалидной категорией "
                    f"({cat!r}) или тональностью ({ton!r})."
                ),
                "affected_pois": [poi_label],
            })
            continue
        c["total_mentions"] += 1
        if cat == "HIGH":
            c["high_count"] += 1
            c["high_" + ton] += 1
        elif cat == "OUTLIER":
            c["outlier_count"] += 1
            if ton in {"criticize", "regret_visited"}:
                c["non_high_negative"] += 1
                c["outlier_negative"] += 1
        elif cat == "MEDIUM":
            c["medium_count"] += 1
            if ton in {"criticize", "regret_visited"}:
                c["non_high_negative"] += 1
        else:  # LOW
            c["low_count"] += 1
            if ton == "recommend":
                c["low_recommend"] += 1
            elif ton in {"criticize", "regret_visited"}:
                c["non_high_negative"] += 1
                # Раньше эти упоминания попадали в low_non_recommend warning;
                # теперь они нужны scarce-ветке RED_FLAG/CONTESTED и не считаются
                # ошибкой.
            else:
                low_non_recommend += 1

    c["non_high_total"] = (
        c["outlier_count"] + c["medium_count"] + c["low_count"]
    )

    if low_non_recommend:
        issues.append({
            "severity": "info",
            "code": "low_non_recommend",
            "message": (
                f"POI «{poi_label}»: {low_non_recommend} упоминаний LOW-авторов "
                "не с тональностью recommend. По §6.4 от LOW передаются только "
                "recommend-упоминания; лишние искажают non_high_total."
            ),
            "affected_pois": [poi_label],
        })
    return c


VALID_ICONIC_STATUSES = frozenset({
    "world_iconic", "national_iconic", "regional_iconic",
})


def categorize(
    c: dict[str, int], strong_min: int, mode: str = "abundant",
    has_trap_archetype: bool = False,
    iconic_status: str | None = None,
) -> str:
    """Применяет правила категоризации по приоритету сверху вниз.

    `mode` влияет на:
    - WEAK_CONFIRMED: abundant требует high_recommend == 2; scarce
      допускает high_recommend in {1,2} (место с одной HIGH-рекомендацией
      и non_high_total > 0 не падает в LOW_SIGNAL).
    - RED_FLAG/CONTESTED scarce-ветка: при high_recommend == 0
      срабатывает по обоснованной non-HIGH критике (≥3 → RED_FLAG,
      ≥2 → CONTESTED).

    `has_trap_archetype` (F-55): если POI помечен LLM как туристическая
    ловушка через `trap_archetype` поле в payload, применяется override
    с наивысшим приоритетом:
    - hr == 0 → RED_FLAG (любой режим)
    - hr == 1 И non_high_negative ≥ 1 → CONTESTED
    - hr ≥ 2 → override не применяется, fall through к §6.5 правилам

    `iconic_status` (F-56 v2): если POI имеет статус известного iconic
    POI (`world_iconic` / `national_iconic` / `regional_iconic`),
    применяется tiebreaker — auto-elevate стандартной категории
    WEAK_CONFIRMED или HIDDEN_GEM до STRONG_CONFIRMED при условиях:
    - hr ≥ 1 (есть хотя бы одно HIGH-подтверждение)
    - hneg == 0 (нет HIGH-критики)
    - стандартная категория < STRONG_CONFIRMED
    Tiebreaker применяется ПОСЛЕ стандартной категоризации, перед
    return. Не работает без HIGH-recommend — не auto-include UNESCO.

    STRONG_CONFIRMED от режима не зависит.
    """
    hr = c["high_recommend"]
    hneg = c["high_criticize"] + c["high_regret_visited"]
    lr = c["low_recommend"]
    nht = c["non_high_total"]
    nhn = c["non_high_negative"]
    out_neg = c.get("outlier_negative", 0)

    # F-55 trap_archetype override (наивысший приоритет).
    # Применяется только при hr ∈ {0, 1}; при hr ≥ 2 — fall through к §6.5.
    if has_trap_archetype:
        if hr == 0:
            return "RED_FLAG"
        if hr == 1 and nhn >= 1:
            return "CONTESTED"
        # hr >= 2 — fall through к стандартным правилам

    # Ветка 1 (abundant + scarce): HIGH-recommend + HIGH-critique → CONTESTED.
    if hr >= 1 and hneg >= 1:
        return "CONTESTED"

    # Ветка 1: HIGH-критика + LOW-recommend → RED_FLAG.
    if hneg >= 1 and hr == 0 and lr >= 1:
        return "RED_FLAG"

    # Ветка 3 (F-55, lone OUTLIER): HIGH-recommend ≥ 1, hneg == 0,
    # одиночная OUTLIER-критика overrated → CONTESTED. Лечит структурное
    # подавление одиночного профильно-релевантного негативного голоса
    # HIGH-gate'ом. Проверка стоит ДО STRONG/WEAK/HIDDEN, чтобы override
    # их к CONTESTED, но ПОСЛЕ ветки 1 (которая уже даёт CONTESTED при
    # HIGH-критике).
    if hr >= 1 and hneg == 0 and out_neg >= 1:
        return "CONTESTED"

    # Ветка 2 (только scarce): нет HIGH-recommend, обоснованная non-HIGH критика.
    # Срабатывает при узкой HIGH-когорте, где ветка 1 математически невозможна.
    # Порядок важен: RED_FLAG строже, проверяется первым.
    if mode == "scarce" and hr == 0:
        if nhn >= 3:
            return "RED_FLAG"
        if nhn >= 2:
            return "CONTESTED"

    # Стандартная категоризация — STRONG / WEAK / HIDDEN / LOW.
    if hr >= strong_min and hneg == 0:
        category = "STRONG_CONFIRMED"
    else:
        weak_min = 1 if mode == "scarce" else WEAK_RECOMMEND
        if weak_min <= hr <= WEAK_RECOMMEND and hneg == 0 and nht > 0:
            category = "WEAK_CONFIRMED"
        elif hr in (1, 2) and hneg == 0 and nht == 0:
            category = "HIDDEN_GEM"
        else:
            category = "LOW_SIGNAL"

    # F-56 v2 UNESCO/iconic tiebreaker.
    # Условия: hr ≥ 1, hneg == 0, iconic_status задан, и стандартная
    # категория WEAK_CONFIRMED или HIDDEN_GEM — auto-elevate до STRONG.
    # При LOW_SIGNAL (hr == 0) и CONTESTED (hneg >= 1 или out_neg >= 1)
    # tiebreaker не работает.
    if (iconic_status in VALID_ICONIC_STATUSES
            and hr >= 1 and hneg == 0
            and category in ("WEAK_CONFIRMED", "HIDDEN_GEM")):
        return "STRONG_CONFIRMED"

    return category


def process_pois(
    pois_in: list[Any],
    strong_min: int,
    mode: str = "abundant",
    mode_per_region: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Обрабатывает входной список POI → (processed, issues).

    `mode_per_region` (если передан) определяет режим для каждого POI
    по его региону. Если регион не в карте — fallback на глобальный `mode`.
    POI без региона использует глобальный `mode`.

    `mode` (abundant | scarce) — глобальный fallback, пробрасывается в
    categorize() для POI без региона или вне карты.
    """
    processed: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    seen_names: dict[str, int] = {}

    for idx, poi in enumerate(pois_in, start=1):
        if not isinstance(poi, dict):
            issues.append({
                "severity": "error",
                "code": "poi_not_object",
                "message": f"POI #{idx}: не объект (тип {type(poi).__name__}).",
                "affected_pois": [f"#{idx}"],
            })
            continue

        name_ru = str(poi.get("name_ru") or "").strip()
        name_local = poi.get("name_local")
        if name_local is not None:
            name_local = str(name_local).strip() or None
        region_raw = poi.get("region")
        region = str(region_raw).strip() if region_raw else ""
        label = name_ru or f"#{idx}"

        if not name_ru:
            issues.append({
                "severity": "error",
                "code": "poi_without_name",
                "message": f"POI #{idx}: пустое поле name_ru.",
                "affected_pois": [label],
            })
        else:
            key = name_ru.casefold()
            seen_names[key] = seen_names.get(key, 0) + 1

        if not region:
            issues.append({
                "severity": "warning",
                "code": "poi_without_region",
                "message": f"POI «{label}»: регион не определён.",
                "affected_pois": [label],
            })

        mentions = poi.get("mentions")
        c = count_mentions(mentions, label, issues)
        if c["total_mentions"] == 0:
            issues.append({
                "severity": "warning",
                "code": "poi_no_mentions",
                "message": f"POI «{label}»: ни одного валидного упоминания.",
                "affected_pois": [label],
            })

        # Per-region mode выбор
        if mode_per_region and region and region in mode_per_region:
            poi_mode = mode_per_region[region]
        else:
            poi_mode = mode

        # F-55 trap_archetype passthrough + override-сигнал для categorize.
        # LLM при экстракции (§6.10 spec) может пометить POI флагом
        # `trap_archetype: {archetype, reasoning}` — обозначение известной
        # туристической ловушки (Chong Khneas, Pub Street, sunset-hill
        # overcrowded etc.). Скрипт не валидирует значение архетипа против
        # справочника — это работа LLM; здесь только структура.
        trap_raw = poi.get("trap_archetype")
        trap_archetype: dict[str, str] | None
        has_trap = False
        if isinstance(trap_raw, dict):
            arch_name = str(trap_raw.get("archetype") or "").strip()
            arch_reason = str(trap_raw.get("reasoning") or "").strip()
            if arch_name:
                has_trap = True
                if not arch_reason:
                    issues.append({
                        "severity": "info",
                        "code": "trap_no_reasoning",
                        "message": (
                            f"POI «{label}»: trap_archetype задан "
                            f"({arch_name}), но reasoning пустой. Reason "
                            "обязателен для прозрачности — иначе пользователь "
                            "не поймёт, на основании чего флаг поставлен."
                        ),
                        "affected_pois": [label],
                    })
                trap_archetype = {
                    "archetype": arch_name,
                    "reasoning": arch_reason,
                }
            else:
                trap_archetype = None
        else:
            trap_archetype = None

        # F-56 v2 iconic_status passthrough + override-сигнал для categorize.
        # LLM при экстракции (§6.5 spec) может пометить POI флагом
        # `iconic_status: world_iconic | national_iconic | regional_iconic`
        # — для известных UNESCO/iconic POI. Скрипт валидирует значение
        # против VALID_ICONIC_STATUSES; невалидное → null с warning.
        iconic_status_raw = poi.get("iconic_status")
        iconic_status: str | None = None
        if iconic_status_raw is not None:
            iconic_status_str = str(iconic_status_raw).strip()
            if iconic_status_str in VALID_ICONIC_STATUSES:
                iconic_status = iconic_status_str
            elif iconic_status_str:
                issues.append({
                    "severity": "warning",
                    "code": "invalid_iconic_status",
                    "message": (
                        f"POI «{label}»: iconic_status={iconic_status_str!r} "
                        "не из VALID_ICONIC_STATUSES "
                        f"({sorted(VALID_ICONIC_STATUSES)}); игнорировано."
                    ),
                    "affected_pois": [label],
                })

        category = categorize(
            c, strong_min, poi_mode, has_trap_archetype=has_trap,
            iconic_status=iconic_status,
        )

        quotes = poi.get("quotes")
        if not isinstance(quotes, list):
            quotes = []
        characteristics = poi.get("characteristics")
        if not isinstance(characteristics, str):
            characteristics = ""

        iconic_raw = poi.get("iconic_exception")
        if isinstance(iconic_raw, dict):
            iconic_present = bool(iconic_raw.get("present"))
            iconic_reason = str(iconic_raw.get("reason") or "").strip()
        else:
            iconic_present, iconic_reason = False, ""
        if iconic_present and not iconic_reason:
            issues.append({
                "severity": "info",
                "code": "iconic_no_reason",
                "message": (
                    f"POI «{label}»: iconic_exception.present=true, но "
                    "reason пустой. Reason обязателен для прозрачности —"
                    " иначе пользователь не поймёт, на основании чего "
                    "флаг поставлен."
                ),
                "affected_pois": [label],
            })

        # Passthrough commonly_combined_with — список объектов
        # {poi_name, why} или null. Скрипт не валидирует семантику
        # пар; только нормализует структуру.
        synergy_raw = poi.get("commonly_combined_with")
        synergy_list: list[dict[str, str]] = []
        if isinstance(synergy_raw, list):
            for item in synergy_raw:
                if not isinstance(item, dict):
                    continue
                poi_name = str(item.get("poi_name") or "").strip()
                why = str(item.get("why") or "").strip()
                if poi_name:
                    synergy_list.append({"poi_name": poi_name, "why": why})

        # Cluster_id и cluster_name_ru — passthrough. LLM маркирует POI как
        # членов одной логической единицы (храмовый комплекс, группа водопадов,
        # археологический круг). Скрипт группирует и считает cluster-level
        # aggregates в build_clusters().
        cluster_id = poi.get("cluster_id")
        cluster_id = str(cluster_id).strip() if cluster_id else None
        cluster_name_ru = poi.get("cluster_name_ru")
        cluster_name_ru = (
            str(cluster_name_ru).strip() if cluster_name_ru else None
        )

        processed.append({
            "name_ru": name_ru,
            "name_local": name_local,
            "region": region or None,
            "high_recommend": c["high_recommend"],
            "high_neutral": c["high_neutral"],
            "high_criticize": c["high_criticize"],
            "high_regret_visited": c["high_regret_visited"],
            "high_regret_missed": c["high_regret_missed"],
            "high_count": c["high_count"],
            "outlier_count": c["outlier_count"],
            "medium_count": c["medium_count"],
            "low_count": c["low_count"],
            "low_recommend": c["low_recommend"],
            "non_high_negative": c["non_high_negative"],
            "outlier_negative": c["outlier_negative"],
            "non_high_total": c["non_high_total"],
            "total_mentions": c["total_mentions"],
            "category": category,
            # Аддитивное display-поле (Фаза 1): русский ярлык категории POI.
            # Контракт EN-поля `category` (underscore-форма) не меняется.
            "category_label": taxonomy.label("poi_category", category),
            "mode_used": poi_mode,                # per-region режим для диагностики
            "cluster_id": cluster_id,             # passthrough
            "cluster_name_ru": cluster_name_ru,   # passthrough
            "quotes": quotes,
            "characteristics": characteristics,
            "iconic_exception": {
                "present": iconic_present,
                "reason": iconic_reason,
            },
            "commonly_combined_with": synergy_list,
            "trap_archetype": trap_archetype,     # F-55 passthrough
            "iconic_status": iconic_status,       # F-56 v2 passthrough
        })

    # Дубли имён (нормализация POI не свела одно место).
    for name_key, n in seen_names.items():
        if n > 1:
            issues.append({
                "severity": "warning",
                "code": "duplicate_poi",
                "message": (
                    f"Имя POI встречается {n} раз — нормализация (§6.2) не "
                    "свела одно место. Пересобери payload."
                ),
                "affected_pois": [name_key],
            })

    return processed, issues


def build_clusters(
    pois: list[dict[str, Any]],
    strong_min: int,
    mode_per_region: dict[str, str] | None,
    mode: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Группирует POI по cluster_id и считает cluster-level aggregates.

    Каждый cluster — один selectable unit для Stage 4. Cluster категория
    определяется на основе **суммированных counts** всех members и
    применяется через categorize() с тем же mode что у region cluster'а.

    POI без cluster_id → пропускаются (остаются individual). POI в clusters
    сохраняют свою individual category в выходе — cluster_category
    используется параллельно (для Stage 4 selection).

    Возвращает (clusters[], issues[]).

    Cluster структура:
        {
          "cluster_id": "<идентификатор>",
          "cluster_name_ru": "<display name>",
          "region": "<регион>",
          "member_poi_names": ["<POI 1>", "<POI 2>", ...],
          "member_count": 5,
          "high_recommend": 12,         # sum по members
          "high_count": ...,
          "non_high_negative": ...,
          ...
          "cluster_category": "STRONG_CONFIRMED",   # на aggregated counts
          "mode_used": "abundant"
        }
    """
    issues: list[dict[str, Any]] = []
    by_id: dict[str, list[dict[str, Any]]] = {}
    for p in pois:
        cid = p.get("cluster_id")
        if cid:
            by_id.setdefault(cid, []).append(p)

    clusters: list[dict[str, Any]] = []
    SUM_FIELDS = (
        "high_recommend", "high_neutral", "high_criticize",
        "high_regret_visited", "high_regret_missed", "high_count",
        "outlier_count", "medium_count", "low_count", "low_recommend",
        "non_high_negative", "outlier_negative",
        "non_high_total", "total_mentions",
    )

    for cid, members in by_id.items():
        # Регион cluster'а — общий у всех members; warning если расходится.
        regions = {m["region"] for m in members if m["region"]}
        if len(regions) > 1:
            issues.append({
                "severity": "warning",
                "code": "cluster_cross_region",
                "message": (
                    f"Cluster «{cid}»: members в разных регионах ({regions}). "
                    "LLM должен кластеризовать POI только внутри одного региона."
                ),
                "affected_pois": [m["name_ru"] for m in members],
            })
        cluster_region = next(iter(regions), None) if regions else None

        # Cluster name — из первого члена, у которого он задан.
        cluster_name = None
        for m in members:
            if m.get("cluster_name_ru"):
                cluster_name = m["cluster_name_ru"]
                break

        # Aggregated counts — sum по members.
        agg = {f: sum(m[f] for m in members) for f in SUM_FIELDS}

        # Mode для категоризации — region mode, иначе global fallback.
        if mode_per_region and cluster_region and cluster_region in mode_per_region:
            cmode = mode_per_region[cluster_region]
        else:
            cmode = mode

        cluster_category = categorize(agg, strong_min, cmode)

        clusters.append({
            "cluster_id": cid,
            "cluster_name_ru": cluster_name,
            "region": cluster_region,
            "member_poi_names": [m["name_ru"] for m in members],
            "member_count": len(members),
            **agg,
            "cluster_category": cluster_category,
            "cluster_category_label": taxonomy.label("poi_category", cluster_category),
            "mode_used": cmode,
        })

    # Сортировка кластеров: по приоритету категории, потом по member_count.
    clusters.sort(key=lambda c: (
        CATEGORY_RANK.get(c["cluster_category"], 99),
        -c["member_count"],
        c["cluster_id"],
    ))

    return clusters, issues


def build_aggregates(pois: list[dict[str, Any]]) -> dict[str, Any]:
    """Считает агрегаты: счётчики категорий и распределение по регионам."""
    counts = {
        "strong_confirmed": 0, "weak_confirmed": 0, "hidden_gems": 0,
        "contested": 0, "red_flags": 0, "low_signal": 0,
    }
    cat_to_key = {
        "STRONG_CONFIRMED": "strong_confirmed",
        "WEAK_CONFIRMED": "weak_confirmed",
        "HIDDEN_GEM": "hidden_gems",
        "CONTESTED": "contested",
        "RED_FLAG": "red_flags",
        "LOW_SIGNAL": "low_signal",
    }
    by_region: dict[str, int] = {}
    iconic_count = 0
    synergy_pairs_count = 0
    trap_archetypes_count = 0
    for p in pois:
        counts[cat_to_key[p["category"]]] += 1
        region = p["region"] or NO_REGION_BUCKET
        by_region[region] = by_region.get(region, 0) + 1
        if p.get("iconic_exception", {}).get("present"):
            iconic_count += 1
        if p.get("commonly_combined_with"):
            synergy_pairs_count += 1
        if p.get("trap_archetype"):
            trap_archetypes_count += 1

    return {
        "total_pois": len(pois),
        **counts,
        "iconic_exceptions": iconic_count,
        "synergy_pairs": synergy_pairs_count,
        "trap_archetypes": trap_archetypes_count,
        "by_region": dict(sorted(by_region.items())),
    }


def order_pois(
    pois: list[dict[str, Any]], by_region: dict[str, int],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Сортирует POI для region-grouped вывода §8.

    Регионы — по убыванию числа POI (ties — по имени региона). POI без
    региона (`без_региона`) — последним. Внутри региона — по приоритету
    категории, затем по убыванию high_recommend / high_count /
    total_mentions. Возвращает (отсортированный список, порядок регионов).
    """
    real = {r: c for r, c in by_region.items() if r != NO_REGION_BUCKET}
    region_order = [
        r for r, _ in sorted(real.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    if NO_REGION_BUCKET in by_region:
        region_order.append(NO_REGION_BUCKET)
    region_rank = {r: i for i, r in enumerate(region_order)}

    def sort_key(p: dict[str, Any]) -> tuple:
        region = p["region"] or NO_REGION_BUCKET
        return (
            region_rank.get(region, len(region_rank)),
            CATEGORY_RANK.get(p["category"], 99),
            -p["high_recommend"],
            -p["high_count"],
            -p["total_mentions"],
            p["name_ru"],
        )

    return sorted(pois, key=sort_key), region_order


def count_distinct_high_authors(pois_in: list[Any]) -> int:
    """Размер HIGH-когорты — число различных HIGH-авторов во всём payload.

    Stage 1 даёт 20–30 отчётов (худший случай ~20); после фильтра Stage 2
    HIGH-авторов мало. Счётчик нужен, чтобы предупредить: STRONG CONFIRMED
    (>= strong_min рекомендаций от разных HIGH) при узкой когорте строг
    или недостижим — это ожидаемо, не дефект.
    """
    ids: set[str] = set()
    for poi in pois_in:
        if not isinstance(poi, dict):
            continue
        mentions = poi.get("mentions")
        if not isinstance(mentions, list):
            continue
        for mention in mentions:
            if (isinstance(mention, dict)
                    and _canon_author_cat(mention.get("author_category")) == "HIGH"):
                aid = mention.get("author_id")
                if aid:
                    ids.add(str(aid))
    return len(ids)


def count_high_authors_per_region(pois_in: list[Any]) -> dict[str, int]:
    """Distinct HIGH author_ids по регионам (per-region режим).

    Для каждого региона: множество HIGH-авторов, упомянувших хотя бы один
    POI этого региона. Возвращает {region: count}. POI без региона не
    учитываются.
    """
    per_region: dict[str, set[str]] = {}
    for poi in pois_in:
        if not isinstance(poi, dict):
            continue
        region = str(poi.get("region") or "").strip()
        if not region:
            continue
        mentions = poi.get("mentions")
        if not isinstance(mentions, list):
            continue
        bucket = per_region.setdefault(region, set())
        for mention in mentions:
            if (isinstance(mention, dict)
                    and _canon_author_cat(mention.get("author_category")) == "HIGH"):
                aid = mention.get("author_id")
                if aid:
                    bucket.add(str(aid))
    return {region: len(authors) for region, authors in per_region.items()}


def resolve_mode_per_region(
    high_per_region: dict[str, int],
    floor: int,
    forced: str,
) -> dict[str, str]:
    """Per-region режим категоризации.

    Если для региона `high_per_region[region] >= floor` → abundant, иначе
    scarce. `forced` ∈ {auto, abundant, scarce}: при ручном форсе все
    регионы получают одинаковый режим (для backward compat и тестов).
    """
    if forced in ("abundant", "scarce"):
        return {r: forced for r in high_per_region}
    return {
        r: ("abundant" if cnt >= floor else "scarce")
        for r, cnt in high_per_region.items()
    }


def resolve_mode(
    high_authors: int, total_authors: int | None,
    threshold: float, forced: str,
) -> tuple[str, float | None]:
    """Определяет режим категоризации и долю HIGH.

    Режим — по доле HIGH = high_authors / total_authors:
    abundant (доля >= threshold) или scarce. `forced` ∈
    {auto, abundant, scarce} — ручной override. Если total_authors
    неизвестен и режим auto — fallback на абсолют
    (high_authors >= ABS_FLOOR_HIGH_AUTHORS → abundant).
    Возвращает (mode, high_share | None).
    """
    share = (
        high_authors / total_authors
        if total_authors and total_authors > 0 else None
    )
    if forced in ("abundant", "scarce"):
        return forced, share
    if share is not None:
        return ("abundant" if share >= threshold else "scarce"), share
    return (
        "abundant" if high_authors >= ABS_FLOOR_HIGH_AUTHORS else "scarce"
    ), None


def build_warnings(
    aggregates: dict[str, Any],
    bloat_strong: float,
    bloat_redflag: float,
    strong_min: int,
) -> list[str]:
    """Аналитические warnings: размер HIGH-когорты + anti-bloat."""
    warnings: list[str] = []
    total = aggregates["total_pois"]
    if total == 0:
        return warnings

    # Размер HIGH-когорты — worst-case awareness. Дефолт Stage 1 — 20–30
    # отчётов (худший случай ~20), после фильтра Stage 2 HIGH-авторов мало.
    high_total = aggregates.get("high_authors_total", 0)
    if high_total < strong_min:
        warnings.append(
            f"⚠️ critical: HIGH-авторов всего {high_total} — категория "
            f"STRONG CONFIRMED недостижима (нужно ≥ {strong_min} рекомендаций "
            "от разных HIGH-авторов). Ожидаемо при минимальной DR-выборке "
            "(Stage 1 = 20–30 отчётов). POI распределятся по WEAK CONFIRMED / "
            "HIDDEN GEM / LOW SIGNAL — это не дефект Stage 3."
        )
    elif high_total < 2 * strong_min:
        warnings.append(
            f"ℹ️ info: HIGH-когорта узкая ({high_total} авторов). "
            f"STRONG CONFIRMED (≥ {strong_min} рекомендаций) будет редким — "
            "мало «подтверждённых» POI ожидаемо при небольшой DR-выборке, "
            "не считать это провалом выборки."
        )

    if aggregates.get("mode") == "scarce":
        share = aggregates.get("high_share")
        share_txt = (
            f" (HIGH-доля {share:.0%})"
            if isinstance(share, (int, float)) else ""
        )
        warnings.append(
            f"ℹ️ info: режим категоризации — scarce{share_txt}. "
            "WEAK CONFIRMED включает места с 1 HIGH-рекомендацией "
            "(+ подтверждение OUTLIER/MEDIUM/LOW); в режиме abundant такие "
            "места были бы LOW SIGNAL. См. stage3-poi.md §6.5."
        )

    strong_ratio = aggregates["strong_confirmed"] / total
    redflag_ratio = aggregates["red_flags"] / total

    if strong_ratio > bloat_strong:
        warnings.append(
            f"⚠️ critical: STRONG CONFIRMED — {aggregates['strong_confirmed']}/"
            f"{total} ({strong_ratio:.0%} > {bloat_strong:.0%}). Слишком много "
            "«подтверждённых» мест размывает приоритизацию на Stage 4. "
            "Проверь, не слила ли нормализация разные места и не однороден ли "
            "reading list."
        )
    if redflag_ratio > bloat_redflag:
        warnings.append(
            f"⚠️ critical: RED FLAG — {aggregates['red_flags']}/{total} "
            f"({redflag_ratio:.0%} > {bloat_redflag:.0%}). Высокая доля "
            "туристических ловушек — структурный конфликт профиля с регионом "
            "или с DR-выборкой. Рассмотри пересмотр scope."
        )
    return warnings


def build_diagnostic(issues: list[dict[str, Any]]) -> dict[str, Any]:
    """Сворачивает issues в diagnostic block со статусом."""
    severities = {i["severity"] for i in issues}
    if "error" in severities:
        status = "error"
    elif "warning" in severities:
        status = "warning"
    else:
        status = "ok"
    return {"status": status, "issues": issues}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Агрегатор POI Stage 3 travel-planning",
    )
    parser.add_argument(
        "--strong-min", type=int, default=DEFAULT_STRONG_MIN_RECOMMEND,
        help="Минимум high_recommend для STRONG CONFIRMED. Дефолт: 3.",
    )
    parser.add_argument(
        "--bloat-strong", type=float, default=DEFAULT_BLOAT_STRONG_RATIO,
        help="Порог доли STRONG CONFIRMED для anti-bloat warning. Дефолт: 0.5.",
    )
    parser.add_argument(
        "--bloat-redflag", type=float, default=DEFAULT_BLOAT_REDFLAG_RATIO,
        help="Порог доли RED FLAG для anti-bloat warning. Дефолт: 0.3.",
    )
    parser.add_argument(
        "--high-share-threshold", type=float,
        default=DEFAULT_HIGH_SHARE_THRESHOLD,
        help="Порог доли HIGH (high_authors/total_authors) для режима "
             "abundant. Ниже порога — режим scarce. Дефолт: 0.3.",
    )
    parser.add_argument(
        "--mode", choices=["auto", "abundant", "scarce"], default="auto",
        help="Режим категоризации. auto — по доле HIGH (дефолт); "
             "abundant / scarce — ручной форс (применяется глобально И "
             "ко всем регионам в per-region режиме).",
    )
    parser.add_argument(
        "--per-region-floor", type=int,
        default=DEFAULT_PER_REGION_HIGH_FLOOR,
        help=f"Порог HIGH-авторов на регион для per-region abundant mode. "
             f"Дефолт: {DEFAULT_PER_REGION_HIGH_FLOOR}. Регионы с меньшим "
             "числом HIGH получают scarce-режим.",
    )
    args = parser.parse_args()

    if args.strong_min < 1:
        print("Ошибка: --strong-min должен быть >= 1.", file=sys.stderr)
        return 2
    if not (0.0 < args.bloat_strong <= 1.0) or not (0.0 < args.bloat_redflag <= 1.0):
        print("Ошибка: пороги bloat должны быть в (0, 1].", file=sys.stderr)
        return 2
    if not (0.0 < args.high_share_threshold <= 1.0):
        print("Ошибка: --high-share-threshold должен быть в (0, 1].",
              file=sys.stderr)
        return 2

    raw = sys.stdin.read()
    if not raw.strip():
        print("Ошибка: stdin пустой.", file=sys.stderr)
        return 2
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Ошибка: невалидный JSON — {exc}.", file=sys.stderr)
        return 2
    if not isinstance(data, dict):
        print("Ошибка: ожидался JSON-объект на верхнем уровне.", file=sys.stderr)
        return 2

    pois_in = data.get("pois")
    if not isinstance(pois_in, list):
        print("Ошибка: поле pois отсутствует или не список.", file=sys.stderr)
        return 2
    if not pois_in:
        print(
            "Ошибка: список pois пуст — агрегировать нечего.", file=sys.stderr,
        )
        return 1

    trip_slug = str(data.get("trip_slug") or "trip")

    # Режим категоризации — глобальный по доле HIGH (см. resolve_mode).
    total_authors = data.get("total_authors")
    if (not isinstance(total_authors, int) or isinstance(total_authors, bool)
            or total_authors <= 0):
        total_authors = None
    high_authors_total = count_distinct_high_authors(pois_in)
    mode, high_share = resolve_mode(
        high_authors_total, total_authors,
        args.high_share_threshold, args.mode,
    )

    # Per-region mode.
    high_authors_per_region = count_high_authors_per_region(pois_in)
    mode_per_region = resolve_mode_per_region(
        high_authors_per_region, args.per_region_floor, args.mode,
    )

    pois, issues = process_pois(
        pois_in, args.strong_min, mode, mode_per_region=mode_per_region,
    )

    # Кластеры (после process_pois, до order_pois).
    clusters, cluster_issues = build_clusters(
        pois, args.strong_min, mode_per_region, mode,
    )
    issues.extend(cluster_issues)

    aggregates = build_aggregates(pois)
    aggregates["high_authors_total"] = high_authors_total
    aggregates["total_authors"] = total_authors
    aggregates["high_share"] = (
        round(high_share, 4) if high_share is not None else None
    )
    aggregates["mode"] = mode
    # Per-region режим + high counts.
    aggregates["high_authors_per_region"] = dict(
        sorted(high_authors_per_region.items())
    )
    aggregates["mode_per_region"] = dict(sorted(mode_per_region.items()))
    # Clusters summary.
    aggregates["total_clusters"] = len(clusters)
    aggregates["pois_in_clusters"] = sum(c["member_count"] for c in clusters)
    aggregates["pois_standalone"] = (
        len(pois) - aggregates["pois_in_clusters"]
    )

    pois, region_order = order_pois(pois, aggregates["by_region"])
    warnings = build_warnings(
        aggregates, args.bloat_strong, args.bloat_redflag, args.strong_min,
    )
    diagnostic = build_diagnostic(issues)

    result = {
        "trip_slug": trip_slug,
        "region_order": region_order,
        "aggregates": aggregates,
        "warnings": warnings,
        "diagnostic": diagnostic,
        "pois": pois,
        "clusters": clusters,           # cluster units для Stage 4
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
