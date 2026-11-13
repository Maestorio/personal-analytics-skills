#!/usr/bin/env python3
"""
Регрессионные тесты для weighted_consensus.py.

Запуск из корня репозитория:
    python3 skills/forecast-confidence-applier/tests/test_weighted_consensus.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "forecast-confidence-applier" / "scripts" / "weighted_consensus.py"

sys.path.insert(0, str(SCRIPT.parent))
from weighted_consensus import (  # noqa: E402
    add_months,
    aggregate_marginal,
    applied_weight,
    coherence_check,
    compute,
    compute_confidence,
    compute_confidence_by_horizon,
    joint_from_axes,
    load_weights_from_scenario,
    parse_central,
    resolve_asymmetry,
    weighted_median,
    weighted_median_tie,
    weighted_quantile,
)


checks_run = 0
checks_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    status = "OK" if condition else "FAIL"
    if not condition:
        checks_failed += 1
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


def test_weighted_median_basic():
    print("test_weighted_median_basic")
    # 3 источника HIGH (вес 1.0): 80, 90, 100. Медиана = 90.
    pairs = [(80, 1.0), (90, 1.0), (100, 1.0)]
    result = weighted_median(pairs)
    check("equal weights → unweighted median", result == 90, f"got {result}")

    # MEDIUM источник (0.5) с экстремальным значением должен меньше тянуть медиану.
    pairs = [(80, 1.0), (90, 1.0), (200, 0.5)]
    result = weighted_median(pairs)
    check("medium-weight outlier → median не уезжает", result == 90, f"got {result}")

    # Ничья: вес делится ровно пополам между двумя значениями → середина, а не нижнее.
    check("ничья двух равновесных → середина",
          weighted_median([(73.94, 0.5), (85, 0.5)]) == 79.47, f"got {weighted_median([(73.94, 0.5), (85, 0.5)])}")
    check("ничья четырёх равновесных → середина средних",
          weighted_median([(79, 0.5), (85, 0.5), (87, 0.5), (93, 0.5)]) == 86.0)
    check("ничья при разных весах (1.0 против 0.5+0.5) → середина границы",
          weighted_median([(80, 1.0), (90, 0.5), (100, 0.5)]) == 85.0)
    check("пара ничьей возвращается", weighted_median_tie([(73.94, 0.5), (85, 0.5)]) == (73.94, 85))
    check("нечётное число равновесных — ничьей нет", weighted_median_tie([(80, 1.0), (90, 1.0), (100, 1.0)]) is None)
    check("перевес одной стороны — ничьей нет",
          weighted_median_tie([(80, 1.0), (90, 0.5)]) is None and weighted_median([(80, 1.0), (90, 0.5)]) == 80)
    check("равные значения по обе стороны половины — не ничья",
          weighted_median_tie([(85, 0.5), (85, 0.5)]) is None and weighted_median([(85, 0.5), (85, 0.5)]) == 85)
    r = compute({"domain": "commodity-agencies", "topic": "brent", "forecast_date": "2026-11-06", "sources": [
        {"id": "a", "value": 73.94, "applied_level": "MEDIUM", "audited": True},
        {"id": "b", "value": 85, "applied_level": "MEDIUM", "audited": True}]})
    check("compute: ничья → середина и поле weighted_median_tie",
          r["weighted_median"] == 79.47 and r.get("weighted_median_tie") == [73.94, 85], f"got {r.get('weighted_median')}, {r.get('weighted_median_tie')}")
    r = compute({"domain": "commodity-agencies", "topic": "brent", "forecast_date": "2026-11-06", "sources": [
        {"id": "a", "value": 80, "applied_level": "HIGH", "audited": True},
        {"id": "b", "value": 90, "applied_level": "HIGH", "audited": True},
        {"id": "c", "value": 100, "applied_level": "HIGH", "audited": True}]})
    check("compute: без ничьей поля weighted_median_tie нет", r["weighted_median"] == 90 and "weighted_median_tie" not in r)


def test_weighted_quantile():
    print("test_weighted_quantile")
    pairs = [(10, 1.0), (20, 1.0), (30, 1.0), (40, 1.0), (50, 1.0)]
    p10 = weighted_quantile(pairs, 0.10)
    p90 = weighted_quantile(pairs, 0.90)
    check("p10 ≤ p90", p10 <= p90, f"p10={p10}, p90={p90}")
    check("p10 в нижней части", p10 <= 20, f"got {p10}")
    check("p90 в верхней части", p90 >= 40, f"got {p90}")


def test_applied_weight_levels():
    print("test_applied_weight_levels")
    cases = [
        ({"applied_level": "HIGH", "audited": True}, 1.0),
        ({"applied_level": "MEDIUM", "audited": True}, 0.5),
        ({"applied_level": "LOW", "audited": True}, 0.0),
        ({"applied_level": "IGNORE", "audited": True}, 0.0),
        ({"applied_level": "HIGH", "audited": False}, 0.0),  # unaudited override
        ({"audited": False}, 0.0),
    ]
    for src, expected in cases:
        weight, _, is_fb = applied_weight(src)
        check(f"{src} → weight={expected}", weight == expected, f"got {weight}")
        check(f"{src} → not fallback", is_fb is False, f"got is_fallback={is_fb}")


def test_applied_weight_max_rule():
    """trust-application.md §nearest-domain: правило MAX из подходящих субдоменов."""
    print("test_applied_weight_max_rule")
    src = {
        "audited": True,
        "trust_profile": [
            {"subdomain": "long-term-russia", "level": "HIGH"},
            {"subdomain": "middle-east", "level": "MEDIUM"},
            {"subdomain": "eu-future", "level": "IGNORE"},
        ],
    }
    weight, sub, is_fb = applied_weight(src)
    check("MAX → 1.0 (HIGH)", weight == 1.0, f"got {weight}")
    check("matched_subdomain = long-term-russia", sub == "long-term-russia", f"got {sub}")
    check("MAX match → not fallback", is_fb is False, f"got {is_fb}")

    # Только LOW/IGNORE → 0.0.
    src = {"audited": True, "trust_profile": [{"subdomain": "x", "level": "LOW"}]}
    weight, _, is_fb = applied_weight(src)
    check("only LOW → 0.0", weight == 0.0, f"got {weight}")
    check("only LOW → not fallback", is_fb is False, f"got {is_fb}")

    # Аудирован, но пустой профиль → MEDIUM по дефолту с флагом fallback.
    src = {"audited": True, "trust_profile": []}
    weight, _, is_fb = applied_weight(src)
    check("audited без profile → 0.5 (MEDIUM default)", weight == 0.5, f"got {weight}")
    check("audited без profile → is_fallback=True", is_fb is True, f"got {is_fb}")


def test_confidence_formula():
    """confidence = 0.4 + 0.4 * share_HIGH - 0.2 * asymmetry"""
    print("test_confidence_formula")
    # 0 HIGH из 4 в consensus, нет asymmetry → 0.4 + 0 - 0 = 0.40
    check("0/4 HIGH, no asymmetry", compute_confidence(0, 4, False) == 0.40)
    # 4 HIGH из 4 → 0.4 + 0.4 = 0.80
    check("4/4 HIGH, no asymmetry", compute_confidence(4, 4, False) == 0.80)
    # 2 HIGH из 4 → 0.4 + 0.2 = 0.60
    check("2/4 HIGH, no asymmetry", compute_confidence(2, 4, False) == 0.60)
    # с asymmetry: 2/4 → 0.40
    check("2/4 HIGH, asymmetry → 0.40", compute_confidence(2, 4, True) == 0.40)
    # пустой consensus → 0.4
    check("empty consensus → 0.40", compute_confidence(0, 0, False) == 0.40)
    # граница: 4 HIGH + asymmetry → 0.6
    check("4/4 HIGH с asymmetry → 0.60", compute_confidence(4, 4, True) == 0.60)


def test_add_months_edge_cases():
    """Расчёт next_due на конце месяца не должен ломаться."""
    print("test_add_months_edge_cases")
    from datetime import date
    check("2026-01-31 + 1 месяц → 2026-02-28", add_months(date(2026, 1, 31), 1) == date(2026, 2, 28))
    check("2026-12-15 + 3 месяца → 2027-03-15", add_months(date(2026, 12, 15), 3) == date(2027, 3, 15))
    check("2024-01-31 + 1 месяц (high-год) → 2024-02-29", add_months(date(2024, 1, 31), 1) == date(2024, 2, 29))


def test_compute_numeric_full():
    print("test_compute_numeric_full")
    payload = {
        "query_domain": "ru-macro",
        "asymmetry_warning": False,
        "forecast_date": "2026-05-05",
        "sources": [
            {"id": "a", "value": 88, "horizon_date": "2026-12-31",
             "applied_level": "HIGH", "audited": True},
            {"id": "b", "value": 92, "horizon_date": "2026-12-31",
             "applied_level": "HIGH", "audited": True},
            {"id": "c", "value": 85, "horizon_date": "2027-06-30",
             "applied_level": "MEDIUM", "audited": True},
            {"id": "d", "value": 110, "horizon_date": "2026-09-30",
             "applied_level": "IGNORE", "audited": True},  # outlier
            {"id": "e", "value": 70, "audited": False},   # unaudited
        ],
    }
    result = compute(payload)
    check("kind = numeric", result["kind"] == "numeric")
    check("HIGH count = 2", result["n_sources"]["high"] == 2)
    check("MEDIUM count = 1", result["n_sources"]["medium"] == 1)
    check("in_consensus = 3 (HIGH+MEDIUM)", result["n_sources"]["in_consensus"] == 3)
    check("outliers = 1 (IGNORE)", result["n_sources"]["outliers"] == 1)
    check("unaudited = 1", result["n_sources"]["unaudited"] == 1)
    # weighted_median: значения [85@0.5, 88@1.0, 92@1.0]
    check("weighted_median computed", result["weighted_median"] is not None)
    # confidence = 0.4 + 0.4 * 2/3 - 0 = 0.667 → 0.67
    check("confidence = 0.67", result["confidence"] == 0.67, f"got {result['confidence']}")
    # next_due: ru-macro дефолт 3 месяца → 2026-08-05
    check("next_due = 2026-08-05", result["reviews"]["next_due"] == "2026-08-05",
          f"got {result['reviews']['next_due']}")
    check("interval_months = 3", result["reviews"]["interval_months"] == 3)
    # горизонт: взвешенное среднее
    check("horizon computed", result["horizon"] is not None)
    check("horizon min = 2026-12-31",
          result["horizon"]["min_date"] == "2026-12-31",
          f"got {result['horizon']['min_date']}")
    check("horizon max = 2027-06-30",
          result["horizon"]["max_date"] == "2027-06-30",
          f"got {result['horizon']['max_date']}")


def test_compute_emits_fallback_medium_warning():
    """Аудированный источник без applied_level и без trust_profile → fallback_medium warning."""
    print("test_compute_emits_fallback_medium_warning")
    payload = {
        "query_domain": "ru-macro",
        "asymmetry_warning": False,
        "forecast_date": "2026-05-05",
        "sources": [
            {"id": "high1", "name": "ЦБ", "value": 90, "horizon_date": "2026-12-31",
             "applied_level": "HIGH", "audited": True},
            {"id": "fb1", "name": "NoProfileSrc", "value": 95, "horizon_date": "2026-12-31",
             "audited": True, "requested_subdomain": "exotic-domain"},
            {"id": "high2", "name": "VTB", "value": 88, "horizon_date": "2026-12-31",
             "applied_level": "HIGH", "audited": True},
        ],
    }
    result = compute(payload)
    fb = [w for w in result["warnings"] if isinstance(w, dict) and w.get("type") == "fallback_medium"]
    check("ровно один fallback_medium warning", len(fb) == 1, f"got {len(fb)}: {fb}")
    check("warning.source = NoProfileSrc",
          fb and fb[0]["source"] == "NoProfileSrc",
          f"got {fb}")
    check("warning.subdomain = exotic-domain",
          fb and fb[0]["subdomain"] == "exotic-domain",
          f"got {fb}")
    # вес fallback'а = 0.5 (MEDIUM)
    fb_aw = [a for a in result["applied_weights"] if a["id"] == "fb1"]
    check("fallback applied_weight = 0.5", fb_aw and fb_aw[0]["applied_weight"] == 0.5,
          f"got {fb_aw}")


def test_compute_no_fallback_warning_when_profile_matches():
    """Источник с trust_profile, дающим MEDIUM (а не пустой профиль), НЕ должен флажиться."""
    print("test_compute_no_fallback_warning_when_profile_matches")
    payload = {
        "query_domain": "ru-macro",
        "asymmetry_warning": False,
        "forecast_date": "2026-05-05",
        "sources": [
            {"id": "src1", "name": "MidSrc", "value": 90, "horizon_date": "2026-12-31",
             "audited": True, "trust_profile": [{"subdomain": "x", "level": "MEDIUM"}]},
        ],
    }
    result = compute(payload)
    fb = [w for w in result["warnings"] if isinstance(w, dict) and w.get("type") == "fallback_medium"]
    check("0 fallback_medium warnings (есть trust_profile match)", len(fb) == 0,
          f"got {fb}")


def test_compute_qualitative():
    print("test_compute_qualitative")
    payload = {
        "query_domain": "geopolitics",
        "asymmetry_warning": True,
        "forecast_date": "2026-05-05",
        "sources": [
            {"id": "a", "position": "escalation", "applied_level": "HIGH", "audited": True},
            {"id": "b", "position": "escalation", "applied_level": "HIGH", "audited": True},
            {"id": "c", "position": "deescalation", "applied_level": "MEDIUM", "audited": True},
            {"id": "d", "position": "stalemate", "applied_level": "LOW", "audited": True},
        ],
    }
    result = compute(payload)
    check("kind = qualitative", result["kind"] == "qualitative")
    check("modal_position = escalation", result["modal_position"] == "escalation",
          f"got {result['modal_position']}")
    split = result["split_by_position"]
    check("escalation: weight_sum = 2.0", split["escalation"]["weight_sum"] == 2.0)
    check("deescalation: weight_sum = 0.5", split["deescalation"]["weight_sum"] == 0.5)
    check("stalemate not in consensus (LOW)", "stalemate" not in split)
    # confidence: 2 HIGH из 3 in_consensus, asymmetry=True → 0.4 + 0.4*2/3 - 0.2 = 0.467 → 0.47
    check("confidence = 0.47 (asymmetry penalty)", result["confidence"] == 0.47,
          f"got {result['confidence']}")
    check("asymmetry_warning passed through", result["asymmetry_warning"] is True)


def test_cli_stdin():
    """Проверяет, что скрипт работает как pipe-команда."""
    print("test_cli_stdin")
    payload = {
        "query_domain": "ru-macro",
        "forecast_date": "2026-05-05",
        "sources": [
            {"id": "a", "value": 100, "applied_level": "HIGH", "audited": True},
            {"id": "b", "value": 110, "applied_level": "MEDIUM", "audited": True},
        ],
    }
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    check("exit code = 0", proc.returncode == 0, f"stderr: {proc.stderr}")
    out = json.loads(proc.stdout)
    check("CLI returns weighted_median", out.get("weighted_median") is not None)
    check("CLI returns confidence", out.get("confidence") is not None)


def test_parse_central():
    print("test_parse_central")
    # Passthrough numerical types.
    check("float passthrough", parse_central(12.7) == 12.7)
    check("int passthrough", parse_central(88) == 88.0)

    # Real формат из events-yaml-spec.md §2.3 «{переменная}: {значение} к {дата}».
    r = parse_central("Ключевая ставка ЦБ РФ: 14.5% к 2026-12-31")
    check("spec §2.3 percent: 14.5", r == 14.5, f"got {r}")
    r = parse_central("Brent: $70–80/bbl к 2026-12-31")
    check("spec §2.3 range em-dash: 75.0", r == 75.0, f"got {r}")
    r = parse_central("USD/CNY: 13.5 к 2027-12-31")
    check("spec §2.3 plain: 13.5", r == 13.5, f"got {r}")
    r = parse_central("Война РФ–НАТО: вероятность <15% к 2030-12-31")
    check("spec §2.3 qualifier <15%: 15.0", r == 15.0, f"got {r}")
    r = parse_central("Korean-style armistice по Украине: к 2027-Q4")
    check("spec §2.3 qualitative → None", r is None, f"got {r}")

    # Edge cases: RU-decimal comma, range with parenthetical, thousands-separator.
    r = parse_central("USD/RUB: 95,5 к 2026-12-31")
    check("RU decimal '95,5' → 95.5", r == 95.5, f"got {r}")
    r = parse_central("12.5–13.0% (weighted median 12.7%)")
    check("range with parenthetical: 12.75", r == 12.75, f"got {r}")
    r = parse_central("$5,400")
    check("thousands-separator '$5,400' → 5400.0", r == 5400.0, f"got {r}")

    # Short value-only форматы (краткие, без префикса).
    check("'12.7%' → 12.7", parse_central("12.7%") == 12.7)
    check("'$88' → 88.0", parse_central("$88") == 88.0)
    check("'85-90' → 87.5", parse_central("85-90") == 87.5)
    check("'14.5' → 14.5", parse_central("14.5") == 14.5)
    check("'not_a_number' → None", parse_central("not_a_number") is None)


def _write_real_scenario_yaml(path: str, probs: dict) -> None:
    """
    Реальный формат (`references/scenario-yaml-spec.md` §1.1): список
    `scenario_triggers` на ВЕРХНЕМ уровне — так пишет генератор
    (`scenario-builder`) и так лежит во всех шести живых матрицах.

    До 2026-08-05 спека показывала блок под `matrix`, и здесь «реальным
    форматом» назывался он. Парсер `load_weights_from_scenario` устойчив к
    вложенности (ищет строки `- scenario_id:`), поэтому обе формы он читает —
    но фикстура обязана называть реальным то, что реально.
    """
    lines = ["matrix:\n", "  date: 2026-07-01\n", "scenario_triggers:\n"]
    for sid, p in probs.items():
        lines.append(f"  - scenario_id: {sid}\n")
        lines.append(f"    label: scenario_{sid}\n")
        lines.append(f"    probability: {p}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _write_nested_scenario_yaml(path: str, probs: dict) -> None:
    """Легаси-терпимость: блок под `matrix` (форма прежней спеки)."""
    lines = ["matrix:\n", "  scenario_triggers:\n"]
    for sid, p in probs.items():
        lines.append(f"    - scenario_id: {sid}\n")
        lines.append(f"      label: scenario_{sid}\n")
        lines.append(f"      probability: {p}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _write_legacy_scenario_yaml(path: str, probs: dict) -> None:
    """Legacy формат `scenarios: {A: {probability: ...}}` для backward-compat теста."""
    lines = ["scenarios:\n"]
    for sid, p in probs.items():
        lines.append(f"  {sid}:\n")
        lines.append(f"    label: scenario_{sid}\n")
        lines.append(f"    probability: {p}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def test_load_weights_from_scenario():
    print("test_load_weights_from_scenario")
    # Реальный формат из scenario-yaml-spec.md §1.1.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
        real_path = tmp.name
    try:
        probs = {"A": 0.25, "B": 0.30, "C": 0.20, "D": 0.25}
        _write_real_scenario_yaml(real_path, probs)
        w = load_weights_from_scenario(real_path)
        check("real format A = 0.25", w.get("A") == 0.25, f"got {w.get('A')}")
        check("real format B = 0.30", w.get("B") == 0.30, f"got {w.get('B')}")
        check("real format C = 0.20", w.get("C") == 0.20, f"got {w.get('C')}")
        check("real format D = 0.25", w.get("D") == 0.25, f"got {w.get('D')}")
        check("real format sum ≈ 1.0", abs(sum(w.values()) - 1.0) < 1e-9,
              f"sum={sum(w.values())}")
    finally:
        os.unlink(real_path)

    # Backward compat: legacy dict format должен тоже парситься.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
        legacy_path = tmp.name
    try:
        _write_legacy_scenario_yaml(legacy_path, {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})
        w = load_weights_from_scenario(legacy_path)
        check("legacy format всё ещё работает", len(w) == 4 and w.get("A") == 0.25,
              f"got {w}")
    finally:
        os.unlink(legacy_path)

    # Форма прежней спеки (блок под `matrix`) — читается как легаси-терпимость.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
        nested_path = tmp.name
    try:
        _write_nested_scenario_yaml(nested_path, {"A": 0.4, "B": 0.3, "C": 0.2, "D": 0.1})
        w = load_weights_from_scenario(nested_path)
        check("вложенная под matrix форма тоже читается",
              w.get("A") == 0.4 and w.get("D") == 0.1, f"got {w}")
    finally:
        os.unlink(nested_path)

    # Живые матрицы: парсер обязан читать РЕАЛЬНЫЕ файлы, а не только фикстуры.
    # Ровно на этом трижды спотыкались другие читатели (MFC-5, validate_library).
    live = (Path.home() / "Library/CloudStorage/SynologyDrive-home"
            / "Claude-Memory/scenarios")
    files = sorted(live.glob("*.yaml")) if live.exists() else []
    if files:
        bad = [f.name for f in files
               if sorted(load_weights_from_scenario(str(f))) != ["A", "B", "C", "D"]]
        check(f"все {len(files)} живых матриц читаются", not bad, str(bad))
    else:
        print("  [SKIP] живые матрицы недоступны")


def test_joint_from_axes_independent():
    print("test_joint_from_axes_independent")
    w = joint_from_axes(0.73, 0.65, rho=0.0)
    # A — стресс-полюс (обе оси HIGH): 0.73 × 0.65. До 2026-08-04 это число
    # стояло на D, то есть маппинг был зеркальным.
    check("A = 0.4745 (обе оси HIGH)", abs(w["A"] - 0.4745) < 1e-4, f"got {w['A']}")
    check("sum = 1.0", abs(sum(w.values()) - 1.0) < 1e-6, f"sum={sum(w.values())}")


def test_joint_from_axes_with_correlation():
    print("test_joint_from_axes_with_correlation")
    w0 = joint_from_axes(0.73, 0.65, rho=0.0)
    w1 = joint_from_axes(0.73, 0.65, rho=0.10)
    check("positive rho → однополюсные квадранты растут (A и D)",
          w1["A"] > w0["A"] and w1["D"] > w0["D"],
          f"A {w0['A']}→{w1['A']}, D {w0['D']}→{w1['D']}")
    check("sum = 1.0", abs(sum(w1.values()) - 1.0) < 1e-6, f"sum={sum(w1.values())}")


def test_joint_from_axes_edge_cases():
    print("test_joint_from_axes_edge_cases")
    # ev_x=0: война исключена → сценарии с x_HIGH (A, B) обнуляются
    w = joint_from_axes(0.0, 0.65, rho=0.0)
    check("ev_x=0 → A = 0 (война исключена)", abs(w["A"]) < 1e-9, f"got {w['A']}")
    check("ev_x=0 → D = 0.35 (перемирие + снятие)", abs(w["D"] - 0.35) < 1e-9,
          f"got {w['D']}")
    # ev_x=ev_y=1: война и ужесточение достоверны → весь вес на A
    w = joint_from_axes(1.0, 1.0, rho=0.0)
    check("ev_x=ev_y=1 → A = 1.0", abs(w["A"] - 1.0) < 1e-9, f"got {w['A']}")
    check("ev_x=ev_y=1 → D = 0.0", abs(w["D"]) < 1e-9, f"got {w['D']}")


def test_joint_from_axes_extreme_rho():
    print("test_joint_from_axes_extreme_rho")
    # ρ=1.0 при асимметричных ev → joint distribution не существует.
    # Должно быть ValueError (не AssertionError — иначе исчезает с python3 -O).
    raised = None
    try:
        joint_from_axes(0.5, 0.3, rho=1.0)
    except ValueError as e:
        raised = e
    except AssertionError:
        raised = "AssertionError"
    check("rho=1.0 невалидный → ValueError",
          isinstance(raised, ValueError),
          f"got {type(raised).__name__ if raised else 'None'}")
    check("ValueError text содержит rho и ev",
          isinstance(raised, ValueError) and "ρ=1" in str(raised) and "ev" in str(raised),
          f"got {raised}")

    # Симметричный частный случай: ρ=0.9, ev_x=ev_y=0.7 — joint существует.
    w = joint_from_axes(0.7, 0.7, rho=0.9)
    check("rho=0.9, ev_x=ev_y=0.7 → joint валиден",
          abs(sum(w.values()) - 1.0) < 1e-6, f"sum={sum(w.values())}")
    check("симметричный rho=0.9 → все веса ≥ 0",
          all(v >= 0 for v in w.values()), f"got {w}")


def test_joint_from_axes_numerical_tolerance():
    print("test_joint_from_axes_numerical_tolerance")
    # ρ близкий к границе допустимости → не должно падать из-за -1e-12 ошибки.
    w = joint_from_axes(0.5, 0.5, rho=0.999999)
    check("rho≈1, ev=0.5/0.5 → tolerance handles round-off",
          abs(sum(w.values()) - 1.0) < 1e-6, f"sum={sum(w.values())}")
    check("все веса в [0,1]", all(0 <= v <= 1 for v in w.values()), f"got {w}")


def test_aggregate_marginal_sum_validation():
    print("test_aggregate_marginal_sum_validation")
    by_scen = _BY_SCEN_BASE
    # weights sum=0.4 (явно битый RECALIBRATE-обновление)
    bad_weights = {"A": 0.1, "B": 0.1, "C": 0.1, "D": 0.1}
    raised = False
    try:
        aggregate_marginal(by_scen, bad_weights, "2026-12-31", "linear")
    except ValueError as e:
        raised = "sum(weights)" in str(e)
    check("sum(weights)=0.4 → ValueError с диагностикой", raised)

    # weights sum=1.0001 — в пределах tolerance, не падает
    ok_weights = {"A": 0.2501, "B": 0.25, "C": 0.25, "D": 0.25}
    try:
        aggregate_marginal(by_scen, ok_weights, "2026-12-31", "linear")
        check("sum=1.0001 в tolerance → не падает", True)
    except ValueError:
        check("sum=1.0001 в tolerance → не падает", False, "raised unexpectedly")


_BY_SCEN_BASE = {
    "A": {"values": {"2026-12-31": {"central": 10.5}}},
    "B": {"values": {"2026-12-31": {"central": 12.5}}},
    "C": {"values": {"2026-12-31": {"central": 11.5}}},
    "D": {"values": {"2026-12-31": {"central": 13.5}}},
}
_EQ_WEIGHTS = {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}


def test_aggregate_marginal_linear():
    print("test_aggregate_marginal_linear")
    result = aggregate_marginal(_BY_SCEN_BASE, _EQ_WEIGHTS, "2026-12-31", "linear")
    check("central = 12.0 (runbook exact)", abs(result["central"] - 12.0) < 1e-6,
          f"got {result['central']}")
    check("range = None (нет range в by_scen)", result["range"] is None)


def test_aggregate_marginal_linear_with_range():
    print("test_aggregate_marginal_linear_with_range")
    by_scen = {
        "A": {"values": {"2026-12-31": {"central": 10.0, "range": [8.0, 12.0]}}},
        "B": {"values": {"2026-12-31": {"central": 12.0, "range": [10.0, 14.0]}}},
        "C": {"values": {"2026-12-31": {"central": 11.0, "range": [9.0, 13.0]}}},
        "D": {"values": {"2026-12-31": {"central": 13.0, "range": [11.0, 15.0]}}},
    }
    result = aggregate_marginal(by_scen, _EQ_WEIGHTS, "2026-12-31", "linear")
    check("range[0] = min(lows) = 8.0", result["range"][0] == 8.0,
          f"got {result['range']}")
    check("range[1] = max(highs) = 15.0", result["range"][1] == 15.0,
          f"got {result['range']}")


def test_aggregate_marginal_modal():
    print("test_aggregate_marginal_modal")
    weights = {"A": 0.10, "B": 0.20, "C": 0.15, "D": 0.55}  # D доминирует
    result = aggregate_marginal(_BY_SCEN_BASE, weights, "2026-12-31", "modal")
    check("modal выбирает D (central=13.5)", result["central"] == 13.5,
          f"got {result['central']}")


def test_aggregate_marginal_nonlinear():
    print("test_aggregate_marginal_nonlinear")
    weights = {"A": 0.10, "B": 0.20, "C": 0.15, "D": 0.55}
    result = aggregate_marginal(_BY_SCEN_BASE, weights, "2026-12-31", "nonlinear")
    check("nonlinear возвращает central D", result["central"] == 13.5,
          f"got {result['central']}")
    check("nonlinear имеет note", "note" in result and "nonlinear" in result["note"],
          f"got {result.get('note')}")


def test_aggregate_marginal_raises():
    print("test_aggregate_marginal_raises")
    raised_not_impl = False
    try:
        aggregate_marginal(_BY_SCEN_BASE, _EQ_WEIGHTS, "2026-12-31", "axis_dependent")
    except NotImplementedError:
        raised_not_impl = True
    check("axis_dependent → NotImplementedError", raised_not_impl)

    raised_value = False
    try:
        aggregate_marginal(_BY_SCEN_BASE, _EQ_WEIGHTS, "2026-12-31", "unknown_method")
    except ValueError:
        raised_value = True
    check("unknown method → ValueError", raised_value)


def test_coherence_check_no_conditional():
    print("test_coherence_check_no_conditional")
    fc = {"forecast": {"central_estimate": "10.0"}}
    result = coherence_check(fc)
    check("severity = LOW", result["severity"] == "LOW", f"got {result['severity']}")
    check("warning содержит 'no conditional'",
          result.get("warning", "").startswith("no conditional"),
          f"got {result.get('warning')}")


def _make_forecast_yaml(layer1_val: float, layer2_central: float, tmp_path: str) -> dict:
    """Строит forecast_yaml dict для coherence_check тестов."""
    _write_real_scenario_yaml(tmp_path, {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})
    return {
        "forecast": {"central_estimate": str(layer1_val)},
        "conditional_on_scenarios": {
            "source_matrix": tmp_path,
            "marginal": {"method": "linear"},
            "by_scenario": {
                sid: {"values": {"2026-12-31": {"central": layer2_central}}}
                for sid in ["A", "B", "C", "D"]
            },
        },
    }


def test_coherence_check_layer1_zero():
    print("test_coherence_check_layer1_zero")
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        # layer1=0, layer2=0 → LOW (оба нулевые — действительно coherent)
        fc = _make_forecast_yaml(0.0, 0.0, tmp_path)
        r = coherence_check(fc)
        check("layer1=0, layer2=0 → severity=LOW",
              r["severity"] == "LOW", f"got {r['severity']}")
        check("layer1=0, layer2=0 → warning=None",
              r["warning"] is None, f"got {r.get('warning')}")

        # layer1=0, layer2=1.0 → UNKNOWN (нельзя посчитать %)
        fc = _make_forecast_yaml(0.0, 1.0, tmp_path)
        r = coherence_check(fc)
        check("layer1=0, layer2=1 → severity=UNKNOWN",
              r["severity"] == "UNKNOWN", f"got {r['severity']}")
        check("layer1=0, layer2=1 → divergence_abs=1.0",
              abs(r.get("divergence_abs", -1) - 1.0) < 1e-9,
              f"got {r.get('divergence_abs')}")
        check("layer1=0, layer2=1 → warning не None",
              r.get("warning") is not None, f"got {r.get('warning')}")
    finally:
        os.unlink(tmp_path)


def test_coherence_check_site_weights():
    """Единый источник весов: рядом с матрицей лежит файл сайта — Layer 2 считается на его весах на дату сравнения."""
    print("test_coherence_check_site_weights")
    import json as _json
    d = tempfile.mkdtemp()
    mpath = os.path.join(d, "scenario-x.yaml")
    try:
        fc = _make_forecast_yaml(10.0, 0.0, mpath)        # матрица: равные веса 0.25
        for sid, v in zip("ABCD", (0.0, 10.0, 20.0, 30.0)):
            fc["conditional_on_scenarios"]["by_scenario"][sid]["values"]["2026-12-31"]["central"] = v
        r0 = coherence_check(fc)
        check("без файла сайта: Layer 2 на весах матрицы (15.0)", abs(r0["layer2_marginal"] - 15.0) < 1e-9, str(r0))
        site = {"schema": "stress-weights@1", "matrix": "scenario-x",
                "horizon_ends": {"h6": "2026-12-31", "h12": "2027-06-30"},
                "weights": {"h6": {"A": 0.1, "B": 0.2, "C": 0.3, "D": 0.4}, "h12": {"A": 0.4, "B": 0.3, "C": 0.2, "D": 0.1}},
                "set_at": "2026-11-06T11:13:19+03:00"}
        spath = os.path.join(d, "stress-weights-scenario-x.json")
        with open(spath, "w", encoding="utf-8") as f:
            _json.dump(site, f)
        r1 = coherence_check(fc)
        check("файл сайта: Layer 2 на весах сайта на эту дату (20.0)", abs(r1["layer2_marginal"] - 20.0) < 1e-9, str(r1))
        site["weights"]["h6"]["A"] = 0.5                   # сумма ≠ 1
        with open(spath, "w", encoding="utf-8") as f:
            _json.dump(site, f)
        try:
            coherence_check(fc)
            refused = False
        except ValueError:
            refused = True
        check("негодный файл сайта — отказ, а не откат на матрицу", refused)
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_coherence_check_severities():
    print("test_coherence_check_severities")
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        # LOW: layer1=10, layer2=10.3 → 3% < 5%
        fc = _make_forecast_yaml(10.0, 10.3, tmp_path)
        r = coherence_check(fc)
        check("LOW: severity=LOW", r["severity"] == "LOW", f"got {r['severity']}")
        check("LOW: warning=None", r["warning"] is None, f"got {r['warning']}")

        # MEDIUM: layer1=10, layer2=11 → 10%
        fc = _make_forecast_yaml(10.0, 11.0, tmp_path)
        r = coherence_check(fc)
        check("MEDIUM: severity=MEDIUM", r["severity"] == "MEDIUM", f"got {r['severity']}")
        check("MEDIUM: divergence_pct ≈ 10", abs(r["divergence_pct"] - 10.0) < 1e-6,
              f"got {r['divergence_pct']}")

        # HIGH: layer1=10, layer2=12.5 → 25%
        fc = _make_forecast_yaml(10.0, 12.5, tmp_path)
        r = coherence_check(fc)
        check("HIGH: severity=HIGH", r["severity"] == "HIGH", f"got {r['severity']}")
        check("HIGH: warning не None", r["warning"] is not None)
    finally:
        os.unlink(tmp_path)


def test_f3_confidence_by_horizon():
    """F3: source_coverage_score (нулевой дрейф) + anchor_share + confidence_by_horizon."""
    from datetime import date
    payload = {
        "query_domain": "ru-macro", "forecast_date": "2026-07-02",
        "horizons": ["2026-12-31", "2027-06-30", "2028-06-30"],
        "sources": [
            {"id": "cbr", "value": 13.0, "horizon_date": "2026-12-31", "applied_level": "HIGH", "audited": True},
            {"id": "sber", "value": 13.1, "horizon_date": "2027-06-30", "applied_level": "MEDIUM", "audited": True},
            {"id": "bks", "value": 13.5, "horizon_date": "2028-06-30", "applied_level": "MEDIUM", "audited": True},
            {"id": "finam", "value": 12.5, "horizon_date": "2026-12-31", "applied_level": "MEDIUM", "audited": True},
        ],
    }
    r = compute(payload)
    # Нулевой дрейф: source_coverage_score — то же число, что legacy-скаляр confidence.
    check("F3 zero-drift: source_coverage_score == confidence",
          r["source_coverage_score"] == r["confidence"],
          f"{r['source_coverage_score']} vs {r['confidence']}")
    check("F3 confidence scalar unchanged (0.5)", r["confidence"] == 0.5, str(r["confidence"]))
    # anchor_share = 1.0 (HIGH) / 2.5 (total) = 0.4
    check("F3 anchor_share top/total", r["anchor_share"] == 0.4, str(r["anchor_share"]))
    cbh = r["confidence_by_horizon"]
    check("F3 near horizon = coverage (decay 0)", cbh["2026-12-31"] == 0.5, str(cbh))
    check("F3 mid horizon decayed below near", cbh["2027-06-30"] < cbh["2026-12-31"], str(cbh))
    # 2028: только 1 источник дотягивается → тонкое покрытие → cap 0.30
    check("F3 far horizon thin-coverage cap ≤0.30", cbh["2028-06-30"] <= 0.30, str(cbh))

    # Юнит: anchor_share>0.5 → cap 0.40
    fd = date(2026, 1, 1)
    cons = [{"horizon_date": date(2027, 1, 1), "weight": 1.0},
            {"horizon_date": date(2027, 1, 1), "weight": 0.5}]
    out = compute_confidence_by_horizon(0.60, 0.7, cons, fd, [date(2026, 3, 1)])
    check("F3 anchor_share>0.5 caps to 0.40", out["2026-03-01"] == 0.40, str(out))

    # Юнит: <2 источников на горизонт → ≤0.30 (даже без декэя)
    cons1 = [{"horizon_date": date(2026, 6, 1), "weight": 1.0}]
    out2 = compute_confidence_by_horizon(0.60, 0.3, cons1, fd, [date(2026, 3, 1)])
    check("F3 thin coverage (<2) caps to ≤0.30", out2["2026-03-01"] <= 0.30, str(out2))

    # Backward-compat: нет horizons в payload → confidence_by_horizon из горизонтов источников (не пусто)
    p2 = dict(payload); p2.pop("horizons")
    r2 = compute(p2)
    check("F3 fallback to source horizons when no payload.horizons",
          len(r2["confidence_by_horizon"]) >= 1, str(r2["confidence_by_horizon"]))

    # Пустой консенсус → anchor_share None, confidence_by_horizon {}
    r3 = compute({"forecast_date": "2026-07-02", "sources": []})
    check("F3 empty consensus: anchor_share None", r3["anchor_share"] is None, str(r3.get("anchor_share")))
    check("F3 empty consensus: confidence_by_horizon {}", r3["confidence_by_horizon"] == {}, str(r3.get("confidence_by_horizon")))


def test_fca1_resolve_asymmetry():
    """FCA-1: asymmetry_warning из camp_distribution, ручной bool — fallback с warning."""
    print("test_fca1_resolve_asymmetry")

    # Детерминированный расчёт из карты лагерей
    aw, warns = resolve_asymmetry({"camp_distribution": {"bull": 3, "bear": 0, "neutral": 0}})
    check("3-0-0 → asymmetry True", aw is True and warns == [], f"got {aw}, {warns}")

    aw, warns = resolve_asymmetry({"camp_distribution": {"bull": 2, "bear": 2, "neutral": 0}})
    check("2-2-0 → asymmetry False", aw is False and warns == [], f"got {aw}")

    aw, _ = resolve_asymmetry({"camp_distribution": {"bull": 7, "bear": 2, "neutral": 1}})
    check("граница 7/10 = 0.7 → True (порог включительно)", aw is True, f"got {aw}")

    aw, _ = resolve_asymmetry({"camp_distribution": {"bull": 2, "bear": 1, "neutral": 0}})
    check("2/3 ≈ 0.67 < 0.7 → False", aw is False, f"got {aw}")

    # camp_distribution приоритетнее ручного bool
    aw, warns = resolve_asymmetry({
        "camp_distribution": {"bull": 2, "bear": 2, "neutral": 1},
        "asymmetry_warning": True,
    })
    check("camp_distribution перекрывает ручной bool", aw is False and warns == [], f"got {aw}")

    # Fallback: ручной bool логируется
    aw, warns = resolve_asymmetry({"asymmetry_warning": True})
    check("ручной bool True → True + manual_asymmetry",
          aw is True and any(w.get("type") == "manual_asymmetry" for w in warns), f"{warns}")

    aw, warns = resolve_asymmetry({"asymmetry_warning": False})
    check("ручной bool False → False, но manual_asymmetry залогирован",
          aw is False and any(w.get("type") == "manual_asymmetry" for w in warns), f"{warns}")

    # Ни того ни другого — тихий default
    aw, warns = resolve_asymmetry({})
    check("нет ни camp_distribution, ни bool → False без warnings",
          aw is False and warns == [], f"{warns}")

    # Аудит 2026-08-03: битый ТИП поля — fallback с warning, не тишина
    aw, warns = resolve_asymmetry({"camp_distribution": [3, 1, 0], "asymmetry_warning": True})
    check("camp_distribution-список → fallback на bool + detail про тип",
          aw is True and warns and "не dict" in warns[0].get("detail", ""), f"{warns}")

    # Аудит 2026-08-03: произвольные имена лагерей входят в знаменатель
    aw, warns = resolve_asymmetry({"camp_distribution": {"bull": 1, "bear": 1, "neutral": 1, "mixed": 97}})
    check("нестандартный лагерь считается: 97/100 → True", aw is True and warns == [], f"{aw}")
    aw, _ = resolve_asymmetry({"camp_distribution": {"iran_side": 5, "atlantic_side": 5}})
    check("полностью предметные лагеря 5/5 → False", aw is False, f"{aw}")

    # Дефектные счётчики → fallback с detail
    aw, warns = resolve_asymmetry({
        "camp_distribution": {"bull": "3", "bear": 0},
        "asymmetry_warning": True,
    })
    check("нечисловой счётчик → fallback на bool + detail",
          aw is True and warns and "bull" in warns[0].get("detail", ""), f"{warns}")

    aw, warns = resolve_asymmetry({"camp_distribution": {"bull": 0, "bear": 0, "neutral": 0}})
    check("все счётчики 0 → fallback (False) + detail про пустоту",
          aw is False and warns and "пуст" in warns[0].get("detail", ""), f"{warns}")

    # Интеграция в compute(): warning попадает в результат, confidence чувствует штраф
    payload = {
        "forecast_date": "2026-08-01",
        "camp_distribution": {"bull": 3, "bear": 0, "neutral": 0},
        "sources": [
            {"id": "s1", "name": "S1", "value": 100, "trust": "HIGH", "weight": 1.0},
        ],
    }
    res = compute(payload)
    check("compute: computed asymmetry → в результате True",
          res["asymmetry_warning"] is True, f"got {res['asymmetry_warning']}")
    check("compute: computed путь без manual_asymmetry в warnings",
          not any(isinstance(w, dict) and w.get("type") == "manual_asymmetry"
                  for w in res["warnings"]), f"{res['warnings']}")

    res_manual = compute({
        "forecast_date": "2026-08-01",
        "asymmetry_warning": True,
        "sources": payload["sources"],
    })
    check("compute: ручной bool → manual_asymmetry в warnings",
          any(isinstance(w, dict) and w.get("type") == "manual_asymmetry"
              for w in res_manual["warnings"]), f"{res_manual['warnings']}")


def main() -> int:
    print("=" * 60)
    print("forecast-confidence-applier / weighted_consensus.py")
    print("=" * 60)

    test_weighted_median_basic()
    test_weighted_quantile()
    test_applied_weight_levels()
    test_applied_weight_max_rule()
    test_confidence_formula()
    test_add_months_edge_cases()
    test_compute_numeric_full()
    test_compute_emits_fallback_medium_warning()
    test_compute_no_fallback_warning_when_profile_matches()
    test_compute_qualitative()
    test_cli_stdin()
    test_parse_central()
    test_load_weights_from_scenario()
    test_joint_from_axes_independent()
    test_joint_from_axes_with_correlation()
    test_joint_from_axes_edge_cases()
    test_joint_from_axes_extreme_rho()
    test_joint_from_axes_numerical_tolerance()
    test_aggregate_marginal_sum_validation()
    test_aggregate_marginal_linear()
    test_aggregate_marginal_linear_with_range()
    test_aggregate_marginal_modal()
    test_aggregate_marginal_nonlinear()
    test_aggregate_marginal_raises()
    test_coherence_check_no_conditional()
    test_coherence_check_layer1_zero()
    test_coherence_check_site_weights()
    test_coherence_check_severities()
    test_f3_confidence_by_horizon()
    test_fca1_resolve_asymmetry()

    print("=" * 60)
    print(f"Итого: {checks_run - checks_failed}/{checks_run} проверок прошло")
    print("=" * 60)
    return 0 if checks_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
