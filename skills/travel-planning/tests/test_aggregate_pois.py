#!/usr/bin/env python3
"""Регрессионные тесты для aggregate_pois.py.

Запуск из корня репозитория:
    python3 skills/travel-planning/tests/test_aggregate_pois.py

Stdlib only. Без внешних файлов.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "travel-planning" / "scripts" / "aggregate_pois.py"

sys.path.insert(0, str(SCRIPT.parent))
from aggregate_pois import (  # noqa: E402
    build_aggregates,
    build_clusters,
    build_diagnostic,
    build_warnings,
    categorize,
    count_distinct_high_authors,
    count_high_authors_per_region,
    count_mentions,
    order_pois,
    process_pois,
    resolve_mode,
    resolve_mode_per_region,
)


checks_run = 0
checks_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    if condition:
        print(f"  ✓ {name}")
    else:
        checks_failed += 1
        suffix = f" — {detail}" if detail else ""
        print(f"  ✗ {name}{suffix}")


def m(cat: str, ton: str, aid: str = "x") -> dict:
    """Упоминание."""
    return {"author_id": aid, "author_category": cat, "tonality": ton}


def cnt(high_recommend=0, high_criticize=0, high_regret_visited=0,
        low_recommend=0, non_high_total=0, non_high_negative=0,
        outlier_negative=0) -> dict:
    """Минимальный counts-dict для categorize()."""
    return {
        "high_recommend": high_recommend,
        "high_criticize": high_criticize,
        "high_regret_visited": high_regret_visited,
        "low_recommend": low_recommend,
        "non_high_total": non_high_total,
        "non_high_negative": non_high_negative,
        "outlier_negative": outlier_negative,
    }


def poi(name_ru="Место", name_local=None, region="регион",
        mentions=None, quotes=None, characteristics="") -> dict:
    """Сырой входной POI."""
    return {
        "name_ru": name_ru,
        "name_local": name_local,
        "region": region,
        "mentions": mentions if mentions is not None else [],
        "quotes": quotes if quotes is not None else [],
        "characteristics": characteristics,
    }


# ─── 1. count_mentions ───────────────────────────────────────────────────

import taxonomy  # noqa: E402


def test_taxonomy_display_and_bilingual():
    """Фаза 1 русификации: category_label на выходе + приём русских
    категорий/тональностей упоминаний (контракт EN-полей не меняется)."""
    print("\n[i18n] display-поле + двуязычный вход")

    # category_label рядом с EN underscore-категорией.
    processed, _ = process_pois([poi("Альфа", mentions=[m("HIGH", "recommend")] * 3)], 3)
    p = processed[0]
    check("process_pois: category_label == taxonomy(poi_category, category)",
          p["category_label"] == taxonomy.label("poi_category", p["category"]))
    check("process_pois: EN-поле category (underscore) не тронуто",
          p["category"] == "STRONG_CONFIRMED")

    # Русские категории/тональности на входе → тот же результат, что EN.
    en_in = [m("HIGH", "recommend")] * 3 + [m("OUTLIER", "criticize")]
    ru_in = ([m("ВЫСОКАЯ", "рекомендует")] * 3
             + [m("ОСОБЫЙ СИГНАЛ", "критикует")])
    issues: list = []
    c_en = count_mentions(en_in, "Т", issues)
    c_ru = count_mentions(ru_in, "Т", issues)
    check("RU-упоминания: нет invalid_mention issue",
          not any(i["code"] == "invalid_mention" for i in issues), str(issues))
    check("RU-упоминания → те же counts, что EN", c_en == c_ru,
          f"{c_en} vs {c_ru}")

    # Distinct HIGH-авторы считаются и по русской категории.
    pr_ru, _ = process_pois(
        [poi("Бета", region="р", mentions=[m("ВЫСОКАЯ", "рекомендует", "a1")])], 1)
    check("RU «ВЫСОКАЯ» учтена как HIGH (per-region режим резолвится)",
          pr_ru[0]["category"] in {"HIDDEN_GEM", "WEAK_CONFIRMED", "STRONG_CONFIRMED"})


def test_count_mentions():
    print("\n[1] count_mentions")

    issues = []
    mentions = (
        [m("HIGH", "recommend")] * 3
        + [m("HIGH", "criticize")]
        + [m("OUTLIER", "neutral")]
        + [m("MEDIUM", "recommend")]
        + [m("LOW", "recommend")] * 2
    )
    c = count_mentions(mentions, "Тест", issues)
    check("high_recommend = 3", c["high_recommend"] == 3, f"got {c['high_recommend']}")
    check("high_criticize = 1", c["high_criticize"] == 1)
    check("high_count = 4", c["high_count"] == 4, f"got {c['high_count']}")
    check("outlier_count = 1", c["outlier_count"] == 1)
    check("medium_count = 1", c["medium_count"] == 1)
    check("low_count = 2", c["low_count"] == 2)
    check("low_recommend = 2", c["low_recommend"] == 2)
    check("non_high_total = 4", c["non_high_total"] == 4, f"got {c['non_high_total']}")
    check("total_mentions = 8", c["total_mentions"] == 8)
    check("чистый счёт — без issues", issues == [])

    # Невалидная категория → issue, не считается.
    issues = []
    c = count_mentions([m("BOGUS", "recommend"), m("HIGH", "recommend")], "Т", issues)
    check("невалидная категория → high_recommend=1 (BOGUS пропущен)",
          c["high_recommend"] == 1)
    check("невалидная категория → issue invalid_mention",
          any(i["code"] == "invalid_mention" for i in issues))

    # Невалидная тональность → issue.
    issues = []
    count_mentions([m("HIGH", "happy")], "Т", issues)
    check("невалидная тональность → issue invalid_mention",
          any(i["code"] == "invalid_mention" for i in issues))

    # mentions не список → issue, нулевые counts.
    issues = []
    c = count_mentions("not-a-list", "Т", issues)
    check("mentions не список → total_mentions=0", c["total_mentions"] == 0)
    check("mentions не список → issue invalid_mention",
          any(i["code"] == "invalid_mention" for i in issues))

    # LOW criticize → non_high_negative++ (используется scarce-веткой),
    # больше НЕ создаёт low_non_recommend warning.
    issues = []
    c = count_mentions([m("LOW", "criticize")], "Т", issues)
    check("LOW criticize: low_count=1, low_recommend=0",
          c["low_count"] == 1 and c["low_recommend"] == 0)
    check("LOW criticize: non_high_negative=1",
          c["non_high_negative"] == 1)
    check("LOW criticize больше НЕ создаёт low_non_recommend issue",
          not any(i["code"] == "low_non_recommend" for i in issues))

    # LOW neutral — всё ещё low_non_recommend (neutral не считается негативом).
    issues = []
    c = count_mentions([m("LOW", "neutral")], "Т", issues)
    check("LOW neutral: low_non_recommend issue остался",
          any(i["code"] == "low_non_recommend" and i["severity"] == "info"
              for i in issues))
    check("LOW neutral: non_high_negative=0 (neutral ≠ негатив)",
          c["non_high_negative"] == 0)

    # OUTLIER criticize → non_high_negative++.
    issues = []
    c = count_mentions([m("OUTLIER", "criticize")], "Т", issues)
    check("OUTLIER criticize: non_high_negative=1",
          c["non_high_negative"] == 1)

    # MEDIUM regret_visited → non_high_negative++.
    issues = []
    c = count_mentions([m("MEDIUM", "regret_visited")], "Т", issues)
    check("MEDIUM regret_visited: non_high_negative=1",
          c["non_high_negative"] == 1)


# ─── 2. categorize ───────────────────────────────────────────────────────

def test_categorize():
    print("\n[2] categorize")

    check("CONTESTED: hr>=1 и hneg>=1",
          categorize(cnt(high_recommend=2, high_criticize=1), 3) == "CONTESTED")
    check("CONTESTED приоритетнее STRONG (hr=3 + критика)",
          categorize(cnt(high_recommend=3, high_criticize=1), 3) == "CONTESTED")
    check("CONTESTED: regret_visited считается негативом",
          categorize(cnt(high_recommend=3, high_regret_visited=1), 3) == "CONTESTED")

    check("RED_FLAG: hcrit>=1, hr=0, low_recommend>=1",
          categorize(cnt(high_criticize=1, low_recommend=2), 3) == "RED_FLAG")
    check("RED_FLAG требует low_recommend: без него → LOW_SIGNAL",
          categorize(cnt(high_criticize=2), 3) == "LOW_SIGNAL")
    check("RED_FLAG не срабатывает если есть hr (это CONTESTED)",
          categorize(cnt(high_recommend=1, high_criticize=1, low_recommend=5), 3)
          == "CONTESTED")

    check("STRONG_CONFIRMED: hr>=3, hneg=0",
          categorize(cnt(high_recommend=4), 3) == "STRONG_CONFIRMED")
    check("STRONG: ровно 3 рекоменд.",
          categorize(cnt(high_recommend=3), 3) == "STRONG_CONFIRMED")

    check("WEAK_CONFIRMED: hr=2, hneg=0, nht>0",
          categorize(cnt(high_recommend=2, non_high_total=1), 3) == "WEAK_CONFIRMED")
    check("hr=2, nht=0 → HIDDEN_GEM (не WEAK)",
          categorize(cnt(high_recommend=2, non_high_total=0), 3) == "HIDDEN_GEM")

    check("HIDDEN_GEM: hr=1, hneg=0, nht=0",
          categorize(cnt(high_recommend=1, non_high_total=0), 3) == "HIDDEN_GEM")
    check("hr=1, nht>0 → LOW_SIGNAL (не HIDDEN_GEM)",
          categorize(cnt(high_recommend=1, non_high_total=2), 3) == "LOW_SIGNAL")

    check("LOW_SIGNAL: пусто",
          categorize(cnt(), 3) == "LOW_SIGNAL")
    check("LOW_SIGNAL: только нейтральные/прочие сигналы",
          categorize(cnt(non_high_total=3), 3) == "LOW_SIGNAL")

    # strong_min override.
    check("strong_min=2: hr=2 → STRONG_CONFIRMED",
          categorize(cnt(high_recommend=2), 2) == "STRONG_CONFIRMED")
    check("strong_min=5: hr=4 → не STRONG (nht=0 → HIDDEN_GEM не подходит, hr!=2)",
          categorize(cnt(high_recommend=4), 5) == "LOW_SIGNAL")

    # Режим scarce — отличается только правилом WEAK CONFIRMED.
    check("scarce: hr=1, hneg=0, nht>0 → WEAK_CONFIRMED",
          categorize(cnt(high_recommend=1, non_high_total=1), 3, "scarce")
          == "WEAK_CONFIRMED")
    check("abundant: hr=1, hneg=0, nht>0 → LOW_SIGNAL (не WEAK)",
          categorize(cnt(high_recommend=1, non_high_total=1), 3, "abundant")
          == "LOW_SIGNAL")
    check("scarce: hr=1, nht=0 → HIDDEN_GEM (не WEAK)",
          categorize(cnt(high_recommend=1, non_high_total=0), 3, "scarce")
          == "HIDDEN_GEM")
    check("scarce: hr=2, nht>0 → WEAK_CONFIRMED",
          categorize(cnt(high_recommend=2, non_high_total=1), 3, "scarce")
          == "WEAK_CONFIRMED")
    check("scarce НЕ трогает STRONG: hr=2, strong_min=3 → не STRONG",
          categorize(cnt(high_recommend=2, non_high_total=1), 3, "scarce")
          != "STRONG_CONFIRMED")
    check("scarce: hr=0 → LOW_SIGNAL (WEAK требует hr>=1)",
          categorize(cnt(non_high_total=2), 3, "scarce") == "LOW_SIGNAL")

    # ── Scarce-ветка RED_FLAG / CONTESTED по non_high_negative ─────────
    # Срабатывает при hr=0 (нет HIGH-recommend) и ≥2/≥3 негативных
    # упоминаний от OUTLIER/MEDIUM/LOW. Закрывает кейс Vietnam-Далат:
    # ни одного HIGH-автора, но 3 OUTLIER/MEDIUM критикуют → RED_FLAG.
    check("scarce-ветка RED_FLAG: hr=0, nhn=3 → RED_FLAG",
          categorize(cnt(non_high_negative=3, non_high_total=3), 3, "scarce")
          == "RED_FLAG")
    check("scarce-ветка RED_FLAG: hr=0, nhn=4 → RED_FLAG",
          categorize(cnt(non_high_negative=4, non_high_total=4), 3, "scarce")
          == "RED_FLAG")
    check("scarce-ветка CONTESTED: hr=0, nhn=2 → CONTESTED",
          categorize(cnt(non_high_negative=2, non_high_total=2), 3, "scarce")
          == "CONTESTED")
    check("scarce: hr=0, nhn=1 → LOW_SIGNAL (порог не достигнут)",
          categorize(cnt(non_high_negative=1, non_high_total=1), 3, "scarce")
          == "LOW_SIGNAL")
    check("scarce-ветка не срабатывает при hr>=1: falls through к WEAK",
          # hr=1 → не попадает в scarce branch2 (hr==0 требуется),
          # дальше: nht>0 + hr in {1,2} + hneg=0 → WEAK_CONFIRMED (scarce).
          categorize(cnt(high_recommend=1, non_high_negative=3,
                         non_high_total=4), 3, "scarce") == "WEAK_CONFIRMED")
    check("abundant-режим: scarce-ветка НЕ срабатывает (nhn>=3 игнорируется)",
          categorize(cnt(non_high_negative=3, non_high_total=3), 3, "abundant")
          == "LOW_SIGNAL")
    check("RED_FLAG Branch 1 приоритетнее scarce-ветки",
          # hr=0, hcrit=1, lr=1 → Branch 1 RED_FLAG (а не scarce).
          # nhn высокий не должен мешать.
          categorize(cnt(high_criticize=1, low_recommend=1,
                         non_high_negative=3), 3, "scarce") == "RED_FLAG")
    check("scarce-ветка приоритетнее STRONG_CONFIRMED при hr=0 (нет STRONG)",
          # hr=0 и так не даст STRONG, но проверяем порядок rules:
          # scarce RED_FLAG срабатывает до STRONG check.
          categorize(cnt(non_high_negative=3, non_high_total=3), 3, "scarce")
          == "RED_FLAG")

    # ── F-55 trap_archetype override (наивысший приоритет) ─────────────
    # POI помечен LLM как известная туристическая ловушка → сдвиг
    # категоризации без зависимости от scarce/abundant.
    check("F-55 trap: hr=0 → RED_FLAG (любой режим, любые non-HIGH)",
          categorize(cnt(), 3, "abundant", has_trap_archetype=True)
          == "RED_FLAG")
    check("F-55 trap: hr=0 в scarce → RED_FLAG",
          categorize(cnt(non_high_total=2), 3, "scarce",
                     has_trap_archetype=True) == "RED_FLAG")
    check("F-55 trap: hr=0, scarce nhn=3 → trap RED_FLAG override (тот же исход)",
          categorize(cnt(non_high_negative=3, non_high_total=3), 3, "scarce",
                     has_trap_archetype=True) == "RED_FLAG")
    check("F-55 trap: hr=1, nhn>=1 → CONTESTED (трап усиливает non-HIGH критику)",
          categorize(cnt(high_recommend=1, non_high_negative=1, non_high_total=1),
                     3, "abundant", has_trap_archetype=True) == "CONTESTED")
    check("F-55 trap: hr=1, nhn=0 → fall through (HIDDEN_GEM)",
          # trap override не срабатывает при hr==1 без non-HIGH критики;
          # стандартное правило: hr=1, hneg=0, nht=0 → HIDDEN_GEM.
          categorize(cnt(high_recommend=1), 3, "abundant",
                     has_trap_archetype=True) == "HIDDEN_GEM")
    check("F-55 trap: hr=2 → fall through (override НЕ применяется при сильной HIGH)",
          # 2+ HIGH-recommend перебивают trap-сигнал — место заслуживает
          # рассмотрения, trap-флаг идёт как caveat в quotes (LLM-side).
          categorize(cnt(high_recommend=2, non_high_total=1), 3, "abundant",
                     has_trap_archetype=True) == "WEAK_CONFIRMED")
    check("F-55 trap: hr=3+ → STRONG (override НЕ применяется)",
          categorize(cnt(high_recommend=3), 3, "abundant",
                     has_trap_archetype=True) == "STRONG_CONFIRMED")
    check("F-55 без trap: тот же hr=0 input → LOW_SIGNAL",
          # Регрессионный sanity: без trap_archetype поведение не меняется.
          categorize(cnt(), 3, "abundant", has_trap_archetype=False)
          == "LOW_SIGNAL")

    # ── F-55 ветка 3 (lone OUTLIER overrated) ─────────────────────────
    # Одиночная OUTLIER-критика (criticize или regret_visited) при
    # наличии HIGH-recommend и отсутствии HIGH-критики → CONTESTED.
    check("F-55 lone OUTLIER: hr=1, hneg=0, out_neg=1 → CONTESTED (вместо HIDDEN)",
          categorize(cnt(high_recommend=1, outlier_negative=1, non_high_negative=1),
                     3, "abundant") == "CONTESTED")
    check("F-55 lone OUTLIER: hr=3, hneg=0, out_neg=1 → CONTESTED (вместо STRONG)",
          # Lone OUTLIER override даже STRONG: похожий профильный голос
          # против — сильный сигнал, не шум.
          categorize(cnt(high_recommend=3, outlier_negative=1, non_high_negative=1),
                     3, "abundant") == "CONTESTED")
    check("F-55 lone OUTLIER: hr=2, hneg=0, out_neg=1, nht>0 → CONTESTED (вместо WEAK)",
          categorize(cnt(high_recommend=2, outlier_negative=1, non_high_negative=1,
                         non_high_total=1), 3, "abundant") == "CONTESTED")
    check("F-55 ветка 3 НЕ срабатывает без OUTLIER-критики (out_neg=0)",
          # nhn от MEDIUM или LOW — не из OUTLIER → ветка 3 не активна.
          # При hr=3, hneg=0 идёт стандартный STRONG.
          categorize(cnt(high_recommend=3, non_high_negative=1, non_high_total=1),
                     3, "abundant") == "STRONG_CONFIRMED")
    check("F-55 ветка 3 НЕ срабатывает при hneg>=1 (ветка 1 раньше)",
          # Ветка 1 даёт CONTESTED по другому основанию, но это не lone
          # OUTLIER. Проверяем что Ветка 1 имеет приоритет.
          categorize(cnt(high_recommend=2, high_criticize=1, outlier_negative=1,
                         non_high_negative=1), 3, "abundant") == "CONTESTED")
    check("F-55 ветка 3 НЕ срабатывает при hr=0 (требует HIGH-recommend)",
          # hr=0 → ветка 3 не активна; пусть будет LOW_SIGNAL.
          categorize(cnt(outlier_negative=1, non_high_negative=1, non_high_total=1),
                     3, "abundant") == "LOW_SIGNAL")
    check("F-55 ветка 3 в scarce: hr=1, nht>0, out_neg=1 → CONTESTED (вместо WEAK scarce)",
          # scarce WEAK срабатывает на hr=1+nht>0. F-55 ветка 3 переопределяет.
          categorize(cnt(high_recommend=1, non_high_total=1, outlier_negative=1,
                         non_high_negative=1), 3, "scarce") == "CONTESTED")

    # ── F-56 v2 UNESCO/iconic tiebreaker ─────────────────────────────
    # Auto-elevate WEAK / HIDDEN до STRONG при iconic_status + hr>=1, hneg=0.
    # Лечит «Ангкор-Ват = WEAK CONFIRMED» class абсурдных ярлыков.
    check("F-56: iconic_status + WEAK → STRONG (auto-elevate)",
          # hr=2, nht>0 → WEAK по стандарту; iconic поднимает до STRONG.
          categorize(cnt(high_recommend=2, non_high_total=1), 3, "abundant",
                     iconic_status="world_iconic") == "STRONG_CONFIRMED")
    check("F-56: iconic_status + HIDDEN_GEM → STRONG",
          # hr=1, nht=0 → HIDDEN по стандарту; iconic elevate.
          categorize(cnt(high_recommend=1), 3, "abundant",
                     iconic_status="regional_iconic") == "STRONG_CONFIRMED")
    check("F-56: iconic_status уже STRONG → STRONG (no change)",
          # hr=3+ — уже STRONG, override no-op.
          categorize(cnt(high_recommend=3), 3, "abundant",
                     iconic_status="world_iconic") == "STRONG_CONFIRMED")
    check("F-56: iconic_status + hr=0 → НЕ elevate (нет HIGH-recommend)",
          # Ключевое требование: tiebreaker не auto-include UNESCO.
          # Без хотя бы одной HIGH-рекомендации остаётся LOW_SIGNAL.
          categorize(cnt(), 3, "abundant",
                     iconic_status="world_iconic") == "LOW_SIGNAL")
    check("F-56: iconic_status + hneg>=1 → НЕ elevate (place is CONTESTED)",
          # При HIGH-критике место уже идёт в CONTESTED по ветке 1,
          # iconic не должен это override'ить (контестед — реальный сигнал).
          categorize(cnt(high_recommend=2, high_criticize=1), 3, "abundant",
                     iconic_status="world_iconic") == "CONTESTED")
    check("F-56: invalid iconic_status (string) — игнорируется",
          # Только VALID_ICONIC_STATUSES применяются.
          categorize(cnt(high_recommend=1), 3, "abundant",
                     iconic_status="famous") == "HIDDEN_GEM")
    check("F-56: iconic_status=None — стандартное поведение",
          categorize(cnt(high_recommend=2, non_high_total=1), 3, "abundant",
                     iconic_status=None) == "WEAK_CONFIRMED")
    check("F-56 + scarce: hr=1, nht>0, iconic → STRONG (override scarce WEAK)",
          # scarce WEAK обычно срабатывает; iconic поднимает выше.
          categorize(cnt(high_recommend=1, non_high_total=1), 3, "scarce",
                     iconic_status="national_iconic") == "STRONG_CONFIRMED")
    check("F-56 priority: F-55 ветка 3 раньше, hr=1+out_neg=1+iconic → CONTESTED",
          # Lone OUTLIER overrated сигнал должен победить iconic — если
          # похожий профильный голос говорит «overrated», iconic не лечит.
          categorize(cnt(high_recommend=1, outlier_negative=1, non_high_negative=1),
                     3, "abundant", iconic_status="world_iconic") == "CONTESTED")


# ─── 3. process_pois ─────────────────────────────────────────────────────

def test_process_pois():
    print("\n[3] process_pois")

    pois_in = [
        poi("Альфа", mentions=[m("HIGH", "recommend")] * 3),
        poi("Бета", mentions=[m("HIGH", "recommend")]),
    ]
    processed, issues = process_pois(pois_in, 3)
    check("2 POI обработаны", len(processed) == 2)
    check("Альфа → STRONG_CONFIRMED",
          next(p for p in processed if p["name_ru"] == "Альфа")["category"]
          == "STRONG_CONFIRMED")
    check("Бета → HIDDEN_GEM",
          next(p for p in processed if p["name_ru"] == "Бета")["category"]
          == "HIDDEN_GEM")

    # POI без name_ru → error.
    processed, issues = process_pois([poi(name_ru="")], 3)
    check("POI без name_ru → issue poi_without_name (error)",
          any(i["code"] == "poi_without_name" and i["severity"] == "error"
              for i in issues))

    # POI без региона → warning.
    processed, issues = process_pois(
        [poi("Гамма", region=None, mentions=[m("HIGH", "recommend")])], 3)
    check("POI без региона → issue poi_without_region (warning)",
          any(i["code"] == "poi_without_region" and i["severity"] == "warning"
              for i in issues))
    check("region=None в выходе", processed[0]["region"] is None)

    # POI без упоминаний → warning.
    processed, issues = process_pois([poi("Дельта", mentions=[])], 3)
    check("POI без упоминаний → issue poi_no_mentions",
          any(i["code"] == "poi_no_mentions" for i in issues))
    check("POI без упоминаний → LOW_SIGNAL",
          processed[0]["category"] == "LOW_SIGNAL")

    # Дубль имени → warning.
    processed, issues = process_pois(
        [poi("Эхо", mentions=[m("HIGH", "recommend")]),
         poi("эхо", mentions=[m("HIGH", "recommend")])], 3)
    check("дубль name_ru (casefold) → issue duplicate_poi",
          any(i["code"] == "duplicate_poi" for i in issues))

    # POI не объект → error.
    processed, issues = process_pois(["строка-вместо-объекта"], 3)
    check("POI не объект → issue poi_not_object",
          any(i["code"] == "poi_not_object" for i in issues))

    # Passthrough quotes/characteristics.
    processed, _ = process_pois(
        [poi("Фокс", mentions=[m("HIGH", "recommend")],
             quotes=["цитата 1"], characteristics="высота 3000м")], 3)
    check("quotes проброшены", processed[0]["quotes"] == ["цитата 1"])
    check("characteristics проброшены",
          processed[0]["characteristics"] == "высота 3000м")

    # iconic_exception дефолт + passthrough + диагностика.
    processed, _ = process_pois(
        [poi("Пингвины", mentions=[m("HIGH", "criticize", "h1")])], 3)
    check("iconic_exception дефолт {present:false, reason:''}",
          processed[0]["iconic_exception"] == {"present": False, "reason": ""})

    raw = poi("Пингвины", mentions=[m("HIGH", "criticize", "h1")])
    raw["iconic_exception"] = {"present": True, "reason": "топ-1 эталон"}
    processed, _ = process_pois([raw], 3)
    check("iconic_exception проброшен present=true с reason",
          processed[0]["iconic_exception"]["present"] is True
          and processed[0]["iconic_exception"]["reason"] == "топ-1 эталон")

    raw = poi("X", mentions=[m("HIGH", "recommend", "h1")])
    raw["iconic_exception"] = {"present": True, "reason": ""}
    _, issues = process_pois([raw], 3)
    check("iconic present без reason → info issue iconic_no_reason",
          any(i["code"] == "iconic_no_reason" and i["severity"] == "info"
              for i in issues))

    raw = poi("X", mentions=[m("HIGH", "recommend", "h1")])
    raw["iconic_exception"] = "не объект"
    processed, _ = process_pois([raw], 3)
    check("iconic_exception не объект → дефолт без падения",
          processed[0]["iconic_exception"] == {"present": False, "reason": ""})

    # ── F-55 trap_archetype: passthrough + override через process_pois ──
    raw = poi("Chong Khneas",
              mentions=[m("HIGH", "neutral", "h1"),
                        m("OUTLIER", "neutral", "o1")])
    raw["trap_archetype"] = {
        "archetype": "floating_village_orphan_scam",
        "reasoning": "Классический развод: лодочный тур к плавучей деревне с обязательным «сиротским приютом»",
    }
    processed, issues = process_pois([raw], 3)
    check("F-55: trap_archetype passthrough",
          processed[0]["trap_archetype"]
          == {"archetype": "floating_village_orphan_scam",
              "reasoning": raw["trap_archetype"]["reasoning"]})
    check("F-55: trap+hr=0 → RED_FLAG (через process_pois)",
          processed[0]["category"] == "RED_FLAG")

    # trap_archetype с hr=1 + non_high_negative=1 → CONTESTED.
    raw = poi("Pub Street",
              mentions=[m("HIGH", "recommend", "h1"),
                        m("OUTLIER", "criticize", "o1")])
    raw["trap_archetype"] = {
        "archetype": "pub_street_westernized_drinking",
        "reasoning": "Туристическая улица для бэкпэкеров",
    }
    processed, _ = process_pois([raw], 3)
    check("F-55: trap+hr=1+nhn>=1 → CONTESTED (через process_pois)",
          processed[0]["category"] == "CONTESTED")

    # trap_archetype с hr>=2 → override не применяется, обычные правила.
    raw = poi("Angkor Wat",
              mentions=[m("HIGH", "recommend", "h1"),
                        m("HIGH", "recommend", "h2"),
                        m("HIGH", "recommend", "h3")])
    raw["trap_archetype"] = {
        "archetype": "crowded_temple_no_atmosphere",
        "reasoning": "В midday hours переполнен — атмосферу теряет; нужен dawn arrival",
    }
    processed, _ = process_pois([raw], 3)
    check("F-55: trap+hr>=3 → STRONG (override НЕ применяется, only caveat)",
          processed[0]["category"] == "STRONG_CONFIRMED")
    check("F-55: trap_archetype проброшен даже при hr>=3",
          processed[0]["trap_archetype"]["archetype"]
          == "crowded_temple_no_atmosphere")

    # trap_archetype с пустым reasoning → info issue trap_no_reasoning.
    raw = poi("Y", mentions=[m("HIGH", "recommend", "h1")])
    raw["trap_archetype"] = {"archetype": "some_archetype", "reasoning": ""}
    _, issues = process_pois([raw], 3)
    check("F-55: trap_archetype с пустым reasoning → info issue trap_no_reasoning",
          any(i["code"] == "trap_no_reasoning" and i["severity"] == "info"
              for i in issues))

    # trap_archetype без archetype (пустой) → не активирован.
    raw = poi("Z", mentions=[m("HIGH", "recommend", "h1")])
    raw["trap_archetype"] = {"archetype": "", "reasoning": "что-то"}
    processed, _ = process_pois([raw], 3)
    check("F-55: trap_archetype без archetype → null + override не применяется",
          processed[0]["trap_archetype"] is None
          and processed[0]["category"] == "HIDDEN_GEM")

    # trap_archetype не объект → silently ignored, не падение.
    raw = poi("W", mentions=[m("HIGH", "recommend", "h1")])
    raw["trap_archetype"] = "не объект"
    processed, _ = process_pois([raw], 3)
    check("F-55: trap_archetype не объект → silently ignored, no crash",
          processed[0]["trap_archetype"] is None
          and processed[0]["category"] == "HIDDEN_GEM")

    # ── F-55 ветка 3 lone OUTLIER через process_pois ─────────────────
    # OUTLIER с criticize при hr>=1 и hneg=0 → CONTESTED override
    # стандартной категории STRONG/WEAK/HIDDEN.
    raw = poi("Муангнгой",
              mentions=[m("HIGH", "recommend", "h1"),
                        m("HIGH", "recommend", "h2"),
                        m("HIGH", "recommend", "h3"),
                        m("OUTLIER", "criticize", "fabio")])
    processed, _ = process_pois([raw], 3)
    check("F-55 ветка 3: hr=3 + lone OUTLIER criticize → CONTESTED",
          processed[0]["category"] == "CONTESTED")
    check("F-55: outlier_negative счётчик в output",
          processed[0]["outlier_negative"] == 1)

    # ── F-56 v2 iconic_status: passthrough + tiebreaker через process_pois ──
    # Кейс: Ангкор-Ват в scarce-режиме с 1 HIGH (типичный КЛТ baseline) →
    # WEAK CONFIRMED по стандарту → STRONG через iconic_status tiebreaker.
    raw = poi("Ангкор-Ват",
              mentions=[m("HIGH", "recommend", "h1"),
                        m("MEDIUM", "neutral", "med1")])
    raw["iconic_status"] = "world_iconic"
    processed, _ = process_pois([raw], 3, mode="scarce")
    check("F-56: scarce+hr=1+iconic → STRONG (auto-elevate из WEAK scarce)",
          processed[0]["category"] == "STRONG_CONFIRMED")
    check("F-56: iconic_status passthrough в output",
          processed[0]["iconic_status"] == "world_iconic")

    # Байон в scarce с 1 HIGH (HIDDEN по стандарту) → STRONG.
    raw = poi("Байон",
              mentions=[m("HIGH", "recommend", "h1")])
    raw["iconic_status"] = "regional_iconic"
    processed, _ = process_pois([raw], 3, mode="scarce")
    check("F-56: scarce+hr=1, nht=0, iconic → STRONG (из HIDDEN_GEM)",
          processed[0]["category"] == "STRONG_CONFIRMED")

    # Без HIGH-рекомендации — НЕ elevate (не auto-include UNESCO).
    raw = poi("Phnom Bakheng",
              mentions=[m("MEDIUM", "neutral", "med1")])
    raw["iconic_status"] = "national_iconic"
    processed, _ = process_pois([raw], 3, mode="scarce")
    check("F-56: hr=0+iconic → НЕ elevate (LOW_SIGNAL остаётся)",
          processed[0]["category"] == "LOW_SIGNAL")
    check("F-56: iconic_status проброшен даже при отсутствии elevate",
          processed[0]["iconic_status"] == "national_iconic")

    # Invalid iconic_status → warning + игнорировано.
    raw = poi("Y", mentions=[m("HIGH", "recommend", "h1")])
    raw["iconic_status"] = "famous_landmark"  # не из VALID_ICONIC_STATUSES
    processed, issues = process_pois([raw], 3)
    check("F-56: invalid iconic_status → warning + ignored",
          any(i["code"] == "invalid_iconic_status" for i in issues)
          and processed[0]["iconic_status"] is None
          and processed[0]["category"] == "HIDDEN_GEM")

    # iconic_status=null → стандартное поведение.
    raw = poi("Z", mentions=[m("HIGH", "recommend", "h1"),
                              m("HIGH", "recommend", "h2"),
                              m("MEDIUM", "neutral", "m1")])
    processed, _ = process_pois([raw], 3)
    check("F-56: iconic_status отсутствует → стандартное WEAK_CONFIRMED",
          processed[0]["category"] == "WEAK_CONFIRMED"
          and processed[0]["iconic_status"] is None)

    # Сортировка вынесена в order_pois — см. test_order_pois.


# ─── 4. build_aggregates ─────────────────────────────────────────────────

def test_build_aggregates():
    print("\n[4] build_aggregates")

    pois = [
        {"category": "STRONG_CONFIRMED", "region": "север"},
        {"category": "STRONG_CONFIRMED", "region": "юг"},
        {"category": "RED_FLAG", "region": "север"},
        {"category": "HIDDEN_GEM", "region": None},
        {"category": "LOW_SIGNAL", "region": "юг"},
    ]
    agg = build_aggregates(pois)
    check("total_pois = 5", agg["total_pois"] == 5)
    check("strong_confirmed = 2", agg["strong_confirmed"] == 2)
    check("red_flags = 1", agg["red_flags"] == 1)
    check("hidden_gems = 1", agg["hidden_gems"] == 1)
    check("low_signal = 1", agg["low_signal"] == 1)
    check("weak_confirmed = 0", agg["weak_confirmed"] == 0)
    check("by_region: север = 2", agg["by_region"]["север"] == 2)
    check("by_region: None → 'без_региона'",
          agg["by_region"].get("без_региона") == 1)

    check("пустой список → total_pois=0",
          build_aggregates([])["total_pois"] == 0)

    # iconic_exceptions подсчёт.
    pois_iconic = [
        {"category": "RED_FLAG", "region": "x",
         "iconic_exception": {"present": True, "reason": "r"}},
        {"category": "LOW_SIGNAL", "region": "x",
         "iconic_exception": {"present": False, "reason": ""}},
        {"category": "LOW_SIGNAL", "region": "x"},
    ]
    check("iconic_exceptions=1 (один POI с present=true)",
          build_aggregates(pois_iconic)["iconic_exceptions"] == 1)
    check("iconic_exceptions=0 без флагов",
          build_aggregates(
              [{"category": "LOW_SIGNAL", "region": "x"}]
          )["iconic_exceptions"] == 0)

    # synergy_pairs подсчёт.
    pois_synergy = [
        {"category": "WEAK_CONFIRMED", "region": "x",
         "commonly_combined_with": [{"poi_name": "Y", "why": "оператор"}]},
        {"category": "WEAK_CONFIRMED", "region": "x",
         "commonly_combined_with": [{"poi_name": "X", "why": "оператор"}]},
        {"category": "LOW_SIGNAL", "region": "x",
         "commonly_combined_with": []},
        {"category": "LOW_SIGNAL", "region": "x"},
    ]
    check("synergy_pairs=2 (два POI с непустым списком)",
          build_aggregates(pois_synergy)["synergy_pairs"] == 2)
    check("synergy_pairs=0 без флагов",
          build_aggregates(
              [{"category": "LOW_SIGNAL", "region": "x"}]
          )["synergy_pairs"] == 0)


# ─── 5. build_warnings (HIGH-когорта + anti-bloat) ───────────────────────

def test_build_warnings():
    print("\n[5] build_warnings")

    # high_authors_total=10 (>= 2*strong_min) — без cohort-warnings.
    # STRONG bloat: 6/10 = 60% > 50%.
    agg = {"total_pois": 10, "strong_confirmed": 6, "red_flags": 0,
           "high_authors_total": 10}
    w = build_warnings(agg, 0.5, 0.3, 3)
    check("STRONG 60% > 50% → warning",
          any("STRONG CONFIRMED" in x for x in w))

    # RED FLAG bloat: 4/10 = 40% > 30%.
    agg = {"total_pois": 10, "strong_confirmed": 0, "red_flags": 4,
           "high_authors_total": 10}
    w = build_warnings(agg, 0.5, 0.3, 3)
    check("RED FLAG 40% > 30% → warning",
          any("RED FLAG" in x for x in w))

    # Нет bloat, когорта норм.
    agg = {"total_pois": 10, "strong_confirmed": 3, "red_flags": 2,
           "high_authors_total": 10}
    w = build_warnings(agg, 0.5, 0.3, 3)
    check("STRONG 30%, RED 20%, когорта 10 → нет warnings", w == [])

    # Граница: ровно 50% не триггерит (строго >).
    agg = {"total_pois": 10, "strong_confirmed": 5, "red_flags": 0,
           "high_authors_total": 10}
    w = build_warnings(agg, 0.5, 0.3, 3)
    check("STRONG ровно 50% → нет warning (строго >)", w == [])

    # total_pois=0 → пусто.
    check("total_pois=0 → нет warnings",
          build_warnings({"total_pois": 0, "strong_confirmed": 0,
                          "red_flags": 0, "high_authors_total": 0},
                         0.5, 0.3, 3) == [])

    # Кастомные пороги bloat.
    agg = {"total_pois": 10, "strong_confirmed": 4, "red_flags": 0,
           "high_authors_total": 10}
    w = build_warnings(agg, 0.3, 0.3, 3)
    check("кастомный bloat_strong=0.3: 40% → warning",
          any("STRONG CONFIRMED" in x for x in w))

    # Cohort: HIGH-когорта 2 < strong_min 3 → critical «недостижима».
    agg = {"total_pois": 10, "strong_confirmed": 0, "red_flags": 0,
           "high_authors_total": 2}
    w = build_warnings(agg, 0.5, 0.3, 3)
    check("HIGH-когорта 2 < strong_min → critical «недостижима»",
          any("недостижима" in x for x in w))

    # Cohort: HIGH-когорта 4 (3 <= 4 < 6) → info «узкая».
    agg = {"total_pois": 10, "strong_confirmed": 1, "red_flags": 0,
           "high_authors_total": 4}
    w = build_warnings(agg, 0.5, 0.3, 3)
    check("HIGH-когорта 4 → info «узкая»",
          any("узкая" in x for x in w))
    check("HIGH-когорта 4 → не critical «недостижима»",
          not any("недостижима" in x for x in w))

    # Cohort: HIGH-когорта 6 (>= 2*strong_min) → нет cohort-warning.
    agg = {"total_pois": 10, "strong_confirmed": 1, "red_flags": 0,
           "high_authors_total": 6}
    w = build_warnings(agg, 0.5, 0.3, 3)
    check("HIGH-когорта 6 → нет cohort-warning",
          not any("недостижима" in x or "узкая" in x for x in w))


# ─── 6. build_diagnostic ─────────────────────────────────────────────────

def test_build_diagnostic():
    print("\n[6] build_diagnostic")

    check("пусто → status=ok",
          build_diagnostic([])["status"] == "ok")
    check("только info → status=ok",
          build_diagnostic([{"severity": "info"}])["status"] == "ok")
    check("warning → status=warning",
          build_diagnostic([{"severity": "warning"}])["status"] == "warning")
    check("error → status=error",
          build_diagnostic([{"severity": "error"}])["status"] == "error")
    check("error перебивает warning",
          build_diagnostic([{"severity": "warning"}, {"severity": "error"}])
          ["status"] == "error")
    check("issues проброшены в diagnostic",
          len(build_diagnostic([{"severity": "info"}])["issues"]) == 1)


# ─── 7. subprocess end-to-end ───────────────────────────────────────────

def run(payload, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        input=json.dumps(payload, ensure_ascii=False) if not isinstance(payload, str)
        else payload,
        capture_output=True, text=True,
    )


def test_subprocess():
    print("\n[7] subprocess end-to-end")

    payload = {
        "trip_slug": "аргентина_юг_2025-03",
        "total_authors": 10,
        "pois": [
            {"name_ru": "Альфа", "name_local": "Alpha", "region": "север",
             "mentions": [m("HIGH", "recommend", "h1"),
                          m("HIGH", "recommend", "h2"),
                          m("HIGH", "recommend", "h3")],
             "quotes": ["q1"], "characteristics": "ch1"},
            {"name_ru": "Бета", "region": "север",
             "mentions": [m("HIGH", "recommend", "h1"),
                          m("HIGH", "recommend", "h2"),
                          m("OUTLIER", "neutral", "o1")]},
            {"name_ru": "Гамма", "region": "юг",
             "mentions": [m("HIGH", "recommend", "h4")]},
            {"name_ru": "Дельта", "region": "юг",
             "mentions": [m("HIGH", "recommend", "h1"),
                          m("HIGH", "recommend", "h2"),
                          m("HIGH", "criticize", "h5")]},
            {"name_ru": "Эпсилон", "region": "юг",
             "mentions": [m("HIGH", "criticize", "h6"),
                          m("LOW", "recommend", "l1")]},
            {"name_ru": "Дзета", "region": "север",
             "mentions": [m("HIGH", "neutral", "h7")]},
        ],
    }
    r = run(payload)
    check("subprocess exit 0", r.returncode == 0, f"stderr: {r.stderr}")
    out = json.loads(r.stdout)

    cats = {p["name_ru"]: p["category"] for p in out["pois"]}
    check("Альфа → STRONG_CONFIRMED", cats["Альфа"] == "STRONG_CONFIRMED")
    check("Бета → WEAK_CONFIRMED", cats["Бета"] == "WEAK_CONFIRMED", str(cats))
    check("Гамма → HIDDEN_GEM", cats["Гамма"] == "HIDDEN_GEM")
    check("Дельта → CONTESTED", cats["Дельта"] == "CONTESTED")
    check("Эпсилон → RED_FLAG", cats["Эпсилон"] == "RED_FLAG")
    check("Дзета → LOW_SIGNAL", cats["Дзета"] == "LOW_SIGNAL")

    check("trip_slug проброшен",
          out["trip_slug"] == "аргентина_юг_2025-03")
    check("aggregates.total_pois = 6", out["aggregates"]["total_pois"] == 6)
    check("aggregates.strong_confirmed = 1",
          out["aggregates"]["strong_confirmed"] == 1)
    check("aggregates.red_flags = 1", out["aggregates"]["red_flags"] == 1)
    check("aggregates.high_authors_total = 7 (h1..h7)",
          out["aggregates"]["high_authors_total"] == 7,
          str(out["aggregates"].get("high_authors_total")))
    check("by_region.север = 3", out["aggregates"]["by_region"]["север"] == 3)
    check("region_order = [север, юг]",
          out.get("region_order") == ["север", "юг"],
          str(out.get("region_order")))
    check("diagnostic.status = ok", out["diagnostic"]["status"] == "ok")
    check("mode = abundant (HIGH-доля 7/10 ≥ 30%)",
          out["aggregates"]["mode"] == "abundant",
          str(out["aggregates"].get("mode")))
    check("когорта 7 (>= 2*strong_min) → нет cohort-warning",
          not any("недостижима" in w or "узкая" in w for w in out["warnings"]))
    check("pois отсортированы: STRONG первым",
          out["pois"][0]["category"] == "STRONG_CONFIRMED")
    check("quotes проброшены в output",
          next(p for p in out["pois"] if p["name_ru"] == "Альфа")["quotes"] == ["q1"])
    check("characteristics проброшены",
          next(p for p in out["pois"]
               if p["name_ru"] == "Альфа")["characteristics"] == "ch1")

    # regret_missed не влияет на категорию → LOW_SIGNAL.
    r = run({"pois": [{"name_ru": "Регрет", "region": "x",
                       "mentions": [m("HIGH", "regret_missed")] * 3}]})
    out = json.loads(r.stdout)
    check("3 HIGH regret_missed → LOW_SIGNAL (не в правилах)",
          out["pois"][0]["category"] == "LOW_SIGNAL")
    check("high_regret_missed=3 в выходе",
          out["pois"][0]["high_regret_missed"] == 3)

    # Пустой stdin → exit 2.
    check("пустой stdin → exit 2", run("").returncode == 2)

    # Невалидный JSON → exit 2.
    check("невалидный JSON → exit 2", run("{not json").returncode == 2)

    # pois не список → exit 2.
    check("pois отсутствует → exit 2",
          run({"trip_slug": "x"}).returncode == 2)

    # Пустой список pois → exit 1.
    check("пустой pois → exit 1", run({"pois": []}).returncode == 1)

    # diagnostic error: POI без name_ru.
    r = run({"pois": [{"name_ru": "", "region": "x",
                       "mentions": [m("HIGH", "recommend")]}]})
    check("POI без name_ru → exit 0 (diagnostic решает)", r.returncode == 0)
    out = json.loads(r.stdout)
    check("POI без name_ru → diagnostic.status=error",
          out["diagnostic"]["status"] == "error")

    # anti-bloat warning в subprocess (когорта 7 — без cohort-warning).
    big = {"pois": [
        {"name_ru": f"S{i}", "region": "x",
         "mentions": [m("HIGH", "recommend", f"h{(i + j) % 7 + 1}")
                      for j in range(3)]} for i in range(8)
    ] + [
        {"name_ru": f"L{i}", "region": "x",
         "mentions": [m("HIGH", "neutral", f"h{i % 7 + 1}")]} for i in range(2)
    ]}
    r = run(big)
    out = json.loads(r.stdout)
    check("8/10 STRONG → anti-bloat warning",
          any("размывает" in w for w in out["warnings"]))

    # Узкая когорта: 2 разных HIGH-автора → critical cohort warning.
    r = run({"pois": [
        {"name_ru": "Узкий", "region": "x",
         "mentions": [m("HIGH", "recommend", "h1"),
                      m("HIGH", "recommend", "h2")]},
    ]})
    out = json.loads(r.stdout)
    check("2 разных HIGH-автора → high_authors_total=2",
          out["aggregates"]["high_authors_total"] == 2)
    check("HIGH-когорта 2 → critical cohort warning в subprocess",
          any("недостижима" in w for w in out["warnings"]))

    # CLI override --strong-min.
    r = run({"pois": [{"name_ru": "X", "region": "x",
                       "mentions": [m("HIGH", "recommend")] * 2}]},
            "--strong-min", "2")
    out = json.loads(r.stdout)
    check("--strong-min 2: 2 рекоменд. → STRONG_CONFIRMED",
          out["pois"][0]["category"] == "STRONG_CONFIRMED")

    # Невалидный --strong-min → exit 2.
    check("--strong-min 0 → exit 2",
          run({"pois": []}, "--strong-min", "0").returncode == 2)

    # Scarce-режим: низкая доля HIGH → hr=1+nht>0 → WEAK CONFIRMED.
    scarce_payload = {"total_authors": 50, "pois": [
        {"name_ru": "Мишон", "region": "x", "mentions": [
            m("HIGH", "recommend", "h1"), m("OUTLIER", "neutral", "o1")]},
    ]}
    r = run(scarce_payload)
    out = json.loads(r.stdout)
    check("низкая доля HIGH (1/50) → mode=scarce",
          out["aggregates"]["mode"] == "scarce")
    check("scarce: hr=1+nht>0 → WEAK CONFIRMED",
          out["pois"][0]["category"] == "WEAK_CONFIRMED")
    check("scarce: high_share = 0.02 в aggregates",
          out["aggregates"]["high_share"] == 0.02)
    check("scarce: warning про режим",
          any("scarce" in w for w in out["warnings"]))

    # --mode abundant форсит на том же payload.
    r = run(scarce_payload, "--mode", "abundant")
    out = json.loads(r.stdout)
    check("--mode abundant: тот же payload → LOW SIGNAL",
          out["pois"][0]["category"] == "LOW_SIGNAL")
    check("--mode abundant: mode в output = abundant",
          out["aggregates"]["mode"] == "abundant")

    # total_authors отсутствует → fallback на абсолют.
    r = run({"pois": [{"name_ru": "X", "region": "x",
                       "mentions": [m("HIGH", "recommend", "h1")]}]})
    out = json.loads(r.stdout)
    check("без total_authors → high_share=None",
          out["aggregates"]["high_share"] is None)
    check("без total_authors, high=1 < 8 → fallback mode=scarce",
          out["aggregates"]["mode"] == "scarce")

    # Невалидный --high-share-threshold → exit 2.
    check("--high-share-threshold 0 → exit 2",
          run({"pois": []}, "--high-share-threshold", "0").returncode == 2)

    # iconic_exception: проброшен в output, считается в aggregates,
    # категорию не меняет.
    r = run({"total_authors": 26, "pois": [
        {"name_ru": "Пингвины", "region": "огненная_земля_ушуая",
         "mentions": [m("HIGH", "criticize", "h1"),
                      m("LOW", "recommend", "l1")],
         "iconic_exception": {"present": True,
                              "reason": "топ-1 пингвинья колония"}},
    ]})
    out = json.loads(r.stdout)
    check("iconic_exception проброшен в output POI",
          out["pois"][0]["iconic_exception"]["present"] is True)
    check("aggregates.iconic_exceptions = 1",
          out["aggregates"]["iconic_exceptions"] == 1)
    check("iconic не меняет категорию (RED_FLAG по правилам)",
          out["pois"][0]["category"] == "RED_FLAG")

    # commonly_combined_with: проброс в output, подсчёт synergy_pairs.
    r = run({"total_authors": 20, "pois": [
        {"name_ru": "Пролив А", "region": "регион_1",
         "mentions": [m("HIGH", "recommend", "h1")],
         "commonly_combined_with": [
             {"poi_name": "Точка Б", "why": "общий оператор катеров"}
         ]},
        {"name_ru": "Точка Б", "region": "регион_1",
         "mentions": [m("HIGH", "recommend", "h1")],
         "commonly_combined_with": [
             {"poi_name": "Пролив А", "why": "общий оператор катеров"}
         ]},
        {"name_ru": "Одиночное", "region": "регион_1",
         "mentions": [m("HIGH", "recommend", "h2")]},
    ]})
    out = json.loads(r.stdout)
    poi_a = next(p for p in out["pois"] if p["name_ru"] == "Пролив А")
    poi_solo = next(p for p in out["pois"] if p["name_ru"] == "Одиночное")
    check("commonly_combined_with проброшен в output POI",
          poi_a["commonly_combined_with"][0]["poi_name"] == "Точка Б")
    check("why проброшен",
          poi_a["commonly_combined_with"][0]["why"] == "общий оператор катеров")
    check("POI без synergy получает пустой список",
          poi_solo["commonly_combined_with"] == [])
    check("aggregates.synergy_pairs = 2 (оба POI пары помечены)",
          out["aggregates"]["synergy_pairs"] == 2)

    # commonly_combined_with: невалидные структуры игнорируются.
    r = run({"total_authors": 10, "pois": [
        {"name_ru": "X", "region": "r",
         "mentions": [m("HIGH", "recommend", "h1")],
         "commonly_combined_with": [
             "не объект",                              # игнор
             {"poi_name": "", "why": "пустое имя"},    # игнор
             {"poi_name": "Y", "why": "ok"},           # ok
         ]},
    ]})
    out = json.loads(r.stdout)
    check("невалидные элементы commonly_combined_with отфильтрованы",
          len(out["pois"][0]["commonly_combined_with"]) == 1)
    check("оставшийся элемент — корректный",
          out["pois"][0]["commonly_combined_with"][0]["poi_name"] == "Y")


# ─── 8. count_distinct_high_authors ──────────────────────────────────────

def test_count_distinct_high_authors():
    print("\n[8] count_distinct_high_authors")

    pois_in = [
        poi("A", mentions=[
            m("HIGH", "recommend", "h1"),
            m("HIGH", "recommend", "h2"),
            m("OUTLIER", "neutral", "o1")]),
        poi("B", mentions=[
            m("HIGH", "neutral", "h1"),       # h1 повторяется — не дублируется
            m("HIGH", "recommend", "h3")]),
    ]
    check("3 различных HIGH-автора (h1 не дублируется)",
          count_distinct_high_authors(pois_in) == 3,
          str(count_distinct_high_authors(pois_in)))
    check("пустой список → 0", count_distinct_high_authors([]) == 0)
    check("нет HIGH-упоминаний → 0",
          count_distinct_high_authors([poi("X", mentions=[
              m("LOW", "recommend", "l1"),
              m("OUTLIER", "neutral", "o1")])]) == 0)
    check("невалидный POI пропускается без падения",
          count_distinct_high_authors(["не-объект"]) == 0)
    check("HIGH-упоминание без author_id не считается",
          count_distinct_high_authors([poi("Y", mentions=[
              {"author_category": "HIGH", "tonality": "recommend"}])]) == 0)


# ─── 9. order_pois ───────────────────────────────────────────────────────

def test_order_pois():
    print("\n[9] order_pois")

    def p9(name, region, category, hr=0, hc=0, tm=1):
        return {"name_ru": name, "region": region, "category": category,
                "high_recommend": hr, "high_count": hc, "total_mentions": tm}

    pois = [
        p9("A", "юг", "LOW_SIGNAL"),
        p9("B", "север", "STRONG_CONFIRMED", hr=3, hc=3, tm=3),
        p9("C", "север", "LOW_SIGNAL", hc=1),
        p9("D", "юг", "HIDDEN_GEM", hr=1, hc=1),
    ]
    ordered, region_order = order_pois(pois, {"север": 2, "юг": 2})
    check("ties 2-2 → region_order по имени: север, юг",
          region_order == ["север", "юг"])
    check("первый POI — из региона север", ordered[0]["region"] == "север")
    check("внутри севера STRONG раньше LOW",
          [x["name_ru"] for x in ordered[:2]] == ["B", "C"])
    check("юг идёт после севера",
          ordered[2]["region"] == "юг" and ordered[3]["region"] == "юг")

    # Регион с большим числом POI — первым.
    pois2 = [p9("X", "малый", "LOW_SIGNAL"),
             p9("Y", "большой", "LOW_SIGNAL"),
             p9("Z", "большой", "LOW_SIGNAL")]
    _, region_order = order_pois(pois2, {"большой": 2, "малый": 1})
    check("регион с большим числом POI — первым",
          region_order == ["большой", "малый"])

    # POI без региона — в конце.
    pois3 = [p9("noreg", None, "LOW_SIGNAL"),
             p9("reg", "регион", "LOW_SIGNAL")]
    ordered, region_order = order_pois(pois3, {"регион": 1, "без_региона": 1})
    check("без_региона — последний в region_order",
          region_order[-1] == "без_региона")
    check("POI без региона — последний в списке",
          ordered[-1]["name_ru"] == "noreg")

    # Внутри региона/категории: больше high_recommend раньше.
    pois4 = [p9("less", "r", "LOW_SIGNAL", hr=0, hc=2, tm=2),
             p9("more", "r", "LOW_SIGNAL", hr=1, hc=1, tm=1)]
    ordered, _ = order_pois(pois4, {"r": 2})
    check("внутри региона: больше high_recommend раньше",
          ordered[0]["name_ru"] == "more")

    check("пустой вход → ([], [])", order_pois([], {}) == ([], []))


# ─── 10. resolve_mode ────────────────────────────────────────────────────

def test_resolve_mode():
    print("\n[10] resolve_mode")

    mode, share = resolve_mode(10, 30, 0.30, "auto")
    check("share 33% ≥ 30% → abundant", mode == "abundant")
    check("high_share вычислен",
          share is not None and abs(share - 10 / 30) < 1e-9)

    mode, _ = resolve_mode(4, 43, 0.30, "auto")
    check("share 9% < 30% → scarce", mode == "scarce")

    mode, _ = resolve_mode(3, 10, 0.30, "auto")
    check("share ровно 30% → abundant (порог >=)", mode == "abundant")

    mode, _ = resolve_mode(4, 43, 0.30, "abundant")
    check("forced abundant перебивает долю", mode == "abundant")
    mode, _ = resolve_mode(10, 10, 0.30, "scarce")
    check("forced scarce перебивает долю", mode == "scarce")

    mode, share = resolve_mode(10, None, 0.30, "auto")
    check("total_authors=None, high=10 ≥ 8 → abundant (fallback)",
          mode == "abundant")
    check("total_authors=None → high_share=None", share is None)

    mode, _ = resolve_mode(4, None, 0.30, "auto")
    check("total_authors=None, high=4 < 8 → scarce (fallback)",
          mode == "scarce")

    mode, _ = resolve_mode(4, 0, 0.30, "auto")
    check("total_authors=0 → fallback как при None", mode == "scarce")

    mode, _ = resolve_mode(4, 0, 0.30, "abundant")
    check("forced работает и без валидного total_authors",
          mode == "abundant")


# ─── 11. F-37: per-region mode ──────────────────────────────────────────

def test_count_high_authors_per_region():
    print("\n[11] F-37: count_high_authors_per_region")

    pois_in = [
        # Регион «Ангкор» — 3 distinct HIGH authors (a, b, c)
        poi(name_ru="Bayon", region="Ангкор", mentions=[
            m("HIGH", "recommend", "a"),
            m("HIGH", "recommend", "b"),
        ]),
        poi(name_ru="Ta Prohm", region="Ангкор", mentions=[
            m("HIGH", "recommend", "c"),
            m("HIGH", "recommend", "a"),  # дубль автора a, не считается
        ]),
        # Регион «Vientiane» — 1 HIGH author (d)
        poi(name_ru="That Luang", region="Vientiane", mentions=[
            m("HIGH", "neutral", "d"),
        ]),
        # POI без региона — игнорируется
        poi(name_ru="Без региона", region="", mentions=[
            m("HIGH", "recommend", "e"),
        ]),
    ]
    counts = count_high_authors_per_region(pois_in)
    check("Ангкор: 3 distinct HIGH authors",
          counts.get("Ангкор") == 3, f"got {counts.get('Ангкор')}")
    check("Vientiane: 1 HIGH author",
          counts.get("Vientiane") == 1)
    check("POI без региона не учитывается",
          "" not in counts and "без_региона" not in counts)


def test_resolve_mode_per_region():
    print("\n[12] F-37: resolve_mode_per_region")

    high_per = {"Ангкор": 5, "Vientiane": 1, "LP": 3}

    # auto: floor=3
    result = resolve_mode_per_region(high_per, 3, "auto")
    check("Ангкор (5 ≥ 3) → abundant", result["Ангкор"] == "abundant")
    check("Vientiane (1 < 3) → scarce", result["Vientiane"] == "scarce")
    check("LP (3 ≥ 3) → abundant", result["LP"] == "abundant")

    # forced abundant перебивает всё
    result = resolve_mode_per_region(high_per, 3, "abundant")
    check("forced abundant: все регионы abundant",
          all(v == "abundant" for v in result.values()))

    # forced scarce
    result = resolve_mode_per_region(high_per, 3, "scarce")
    check("forced scarce: все регионы scarce",
          all(v == "scarce" for v in result.values()))


def test_process_pois_with_per_region_mode():
    print("\n[13] F-37: process_pois с mode_per_region")

    pois_in = [
        # Vientiane: hr=0 + non_high_negative=3 (scarce ветка RED_FLAG)
        poi(name_ru="Туристическая ловушка VTE", region="Vientiane",
            mentions=[
                m("OUTLIER", "criticize", "a"),
                m("MEDIUM", "criticize", "b"),
                m("LOW", "criticize", "c"),
            ]),
        # Ангкор: hr=2 + non_high_total=1 (abundant ветка WEAK_CONFIRMED)
        poi(name_ru="Bayon", region="Ангкор", mentions=[
            m("HIGH", "recommend", "x"),
            m("HIGH", "recommend", "y"),
            m("MEDIUM", "neutral", "z"),
        ]),
    ]
    # Vientiane → scarce, Ангкор → abundant (per-region)
    mode_per_region = {"Vientiane": "scarce", "Ангкор": "abundant"}

    processed, _ = process_pois(pois_in, 3, "abundant", mode_per_region)
    # Найти каждый POI
    by_name = {p["name_ru"]: p for p in processed}
    check("Vientiane POI: scarce ветка → RED_FLAG",
          by_name["Туристическая ловушка VTE"]["category"] == "RED_FLAG",
          f"got {by_name['Туристическая ловушка VTE']['category']}")
    check("Vientiane POI: mode_used = scarce",
          by_name["Туристическая ловушка VTE"]["mode_used"] == "scarce")
    check("Ангкор POI: abundant → WEAK_CONFIRMED",
          by_name["Bayon"]["category"] == "WEAK_CONFIRMED",
          f"got {by_name['Bayon']['category']}")
    check("Ангкор POI: mode_used = abundant",
          by_name["Bayon"]["mode_used"] == "abundant")


# ─── 14. F-36: cluster units ─────────────────────────────────────────────

def test_build_clusters():
    print("\n[14] F-36: build_clusters")

    # Большой круг Ангкора: 3 POI с cluster_id, разные HIGH-rec counts.
    pois_in = [
        {
            **poi(name_ru="Bayon", region="Ангкор", mentions=[
                m("HIGH", "recommend", "a"),
                m("HIGH", "recommend", "b"),
            ]),
            "cluster_id": "big_circle",
            "cluster_name_ru": "Большой круг Ангкора",
        },
        {
            **poi(name_ru="Ta Prohm", region="Ангкор", mentions=[
                m("HIGH", "recommend", "c"),
            ]),
            "cluster_id": "big_circle",
        },
        {
            **poi(name_ru="Banteay Kdei", region="Ангкор", mentions=[
                m("HIGH", "recommend", "d"),
            ]),
            "cluster_id": "big_circle",
        },
        # POI без cluster
        poi(name_ru="Standalone", region="Ангкор", mentions=[
            m("HIGH", "recommend", "x"),
        ]),
    ]
    processed, _ = process_pois(pois_in, 3, "abundant")
    clusters, c_issues = build_clusters(processed, 3, None, "abundant")

    check("1 cluster найден", len(clusters) == 1, f"got {len(clusters)}")
    c0 = clusters[0]
    check("cluster_id = big_circle", c0["cluster_id"] == "big_circle")
    check("cluster_name_ru подхвачен",
          c0["cluster_name_ru"] == "Большой круг Ангкора")
    check("member_count = 3", c0["member_count"] == 3)
    check("aggregated high_recommend = 4",
          c0["high_recommend"] == 4, f"got {c0['high_recommend']}")
    check("cluster_category = STRONG_CONFIRMED (4 ≥ 3 high_recommend)",
          c0["cluster_category"] == "STRONG_CONFIRMED",
          f"got {c0['cluster_category']}")
    check("cluster region = Ангкор", c0["region"] == "Ангкор")
    check("Standalone POI не в clusters",
          all("Standalone" not in c.get("member_poi_names", [])
              for c in clusters))


def test_cluster_cross_region_warning():
    print("\n[15] F-36: cluster cross-region warning")

    pois_in = [
        {
            **poi(name_ru="A", region="Region1", mentions=[
                m("HIGH", "recommend", "x"),
            ]),
            "cluster_id": "broken_cluster",
        },
        {
            **poi(name_ru="B", region="Region2", mentions=[
                m("HIGH", "recommend", "y"),
            ]),
            "cluster_id": "broken_cluster",
        },
    ]
    processed, _ = process_pois(pois_in, 3, "abundant")
    clusters, issues = build_clusters(processed, 3, None, "abundant")
    check("cluster cross-region → warning issue",
          any(i.get("code") == "cluster_cross_region" for i in issues))


def test_cluster_subprocess_end_to_end():
    print("\n[16] F-36+F-37: subprocess с clusters и per-region mode")

    payload = {
        "trip_slug": "klt",
        "total_authors": 43,
        "pois": [
            # Ангкор: 3 POI в cluster, HIGH-доля высокая → abundant per-region
            {
                "name_ru": "Bayon",
                "region": "Ангкор",
                "cluster_id": "big_circle",
                "cluster_name_ru": "Большой круг Ангкора",
                "mentions": [
                    {"author_id": f"a{i}", "author_category": "HIGH",
                     "tonality": "recommend"} for i in range(1, 4)
                ],
            },
            {
                "name_ru": "Ta Prohm",
                "region": "Ангкор",
                "cluster_id": "big_circle",
                "mentions": [
                    {"author_id": f"a{i}", "author_category": "HIGH",
                     "tonality": "recommend"} for i in range(2, 5)
                ],
            },
            {
                "name_ru": "Banteay Kdei",
                "region": "Ангкор",
                "cluster_id": "big_circle",
                "mentions": [
                    {"author_id": "a5", "author_category": "HIGH",
                     "tonality": "recommend"},
                ],
            },
            # Vientiane: 1 HIGH-автор → scarce per-region
            {
                "name_ru": "Туристическая улица VTE",
                "region": "Vientiane",
                "mentions": [
                    {"author_id": "b1", "author_category": "OUTLIER",
                     "tonality": "criticize"},
                    {"author_id": "b2", "author_category": "MEDIUM",
                     "tonality": "criticize"},
                    {"author_id": "b3", "author_category": "LOW",
                     "tonality": "criticize"},
                ],
            },
        ],
    }
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
    )
    check("subprocess exit 0", result.returncode == 0,
          f"stderr: {result.stderr}")
    output = json.loads(result.stdout)

    # F-36 checks
    check("clusters[] в output (F-36)", "clusters" in output)
    check("1 cluster найден", len(output["clusters"]) == 1)
    c0 = output["clusters"][0]
    check("cluster_id = big_circle", c0["cluster_id"] == "big_circle")
    check("cluster_category = STRONG_CONFIRMED",
          c0["cluster_category"] == "STRONG_CONFIRMED",
          f"got {c0['cluster_category']}")
    check("aggregates.total_clusters = 1",
          output["aggregates"]["total_clusters"] == 1)
    check("aggregates.pois_in_clusters = 3",
          output["aggregates"]["pois_in_clusters"] == 3)

    # F-37 checks
    check("mode_per_region в aggregates (F-37)",
          "mode_per_region" in output["aggregates"])
    mpr = output["aggregates"]["mode_per_region"]
    check("Ангкор → abundant per-region", mpr.get("Ангкор") == "abundant",
          f"got {mpr}")
    check("Vientiane → scarce per-region", mpr.get("Vientiane") == "scarce")
    check("high_authors_per_region в aggregates",
          "high_authors_per_region" in output["aggregates"])

    # POI-level mode_used
    vientiane_poi = next(
        p for p in output["pois"]
        if p["name_ru"] == "Туристическая улица VTE"
    )
    check("Vientiane POI: mode_used = scarce",
          vientiane_poi["mode_used"] == "scarce")
    check("Vientiane POI: RED_FLAG по scarce-ветке (non_high_negative=3)",
          vientiane_poi["category"] == "RED_FLAG",
          f"got {vientiane_poi['category']}")


# ─── main ────────────────────────────────────────────────────────────────

def main():
    test_taxonomy_display_and_bilingual()
    test_count_mentions()
    test_categorize()
    test_process_pois()
    test_build_aggregates()
    test_build_warnings()
    test_build_diagnostic()
    test_subprocess()
    test_count_distinct_high_authors()
    test_order_pois()
    test_resolve_mode()
    test_count_high_authors_per_region()
    test_resolve_mode_per_region()
    test_process_pois_with_per_region_mode()
    test_build_clusters()
    test_cluster_cross_region_warning()
    test_cluster_subprocess_end_to_end()

    print(f"\n{'=' * 50}")
    print(f"Всего проверок: {checks_run}, провалов: {checks_failed}")
    if checks_failed:
        print("FAIL")
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
