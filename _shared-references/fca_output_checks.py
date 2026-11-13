#!/usr/bin/env python3
"""fca_output_checks — pre-save проверка FCA-вывода против events-yaml-spec.md §5.

Канон живёт здесь (_shared-references/), pack.sh встраивает файл в scripts/
скилла forecast-confidence-applier через `bundle_scripts:` (образец —
constraint_engine.py, CR-A). Потребители:

  • forecast-confidence-applier/scripts/validate_fca_output.py — тонкий CLI,
    гоняется на Шаге 6 ПЕРЕД save-to-library (новый артефакт → всё blocking);
  • save-to-library/tests — drift-контракт: вердикты этого модуля сверяются
    с validate_forecast_events(_strict) на общих фикстурах.

Зона ответственности — ФОРМА вывода FCA (FCA-2: известные non-spec привычки
модели) + кросс-правила provenance ↔ sources_used/upstream_used (FCA-3,
§5.2.1). Глубокая семантика (fca_stats, конус, calibration-блоки) остаётся
в validate_forecast_events save-to-library — здесь её нет сознательно.

Stdlib-only. CLI: echo '<forecast-yaml-as-json>' | python3 fca_output_checks.py
"""
from __future__ import annotations

import json
import re
import sys

# Канон §5.2.1 (FCA-3, 2026-08-03) — зеркало VALID_PROVENANCE в assemble_artifact.py.
VALID_PROVENANCE = {
    "native_fca", "single_native", "derived_from_marginal", "inferred_from_content",
    "derived_from_upstream", "derived_from_geopolitics_translation",
}
LEGACY_PROVENANCE_MAP = {
    "source_native": "single_native",
    "inferred_from_cpi_floor": "derived_from_upstream",
    "inferred_from_upstream_dependency": "derived_from_upstream",
    "structural_derivation": "derived_from_upstream",
}
PROVENANCE_NEEDS_SOURCES = {"native_fca", "single_native", "inferred_from_content"}

_HORIZON_KEY_RE = re.compile(r"horizon_\d{4}$")


def _issue(field: str, category: str, expected: str, actual) -> dict:
    return {
        "field": field,
        "severity": "blocking",
        "category": category,
        "expected": expected,
        "actual": actual if isinstance(actual, str) else repr(actual),
    }


def check_fca_output(data: dict) -> dict:
    """Проверка формы FCA-вывода. Новый артефакт → все нарушения blocking.

    Возвращает {"valid": bool, "blocking_count": int, "issues": [...]},
    каждый issue несёт category ∈ {nonstandard_field_names,
    nonstandard_structure, coherence_misplaced, cross_validation}.
    """
    issues: list[dict] = []
    if not isinstance(data, dict):
        return {
            "valid": False,
            "blocking_count": 1,
            "issues": [_issue("<root>", "nonstandard_structure", "dict", type(data).__name__)],
        }

    cond = data.get("conditional_on_scenarios")
    if cond is None:
        # Type 1 isolated — форма by_scenario не проверяется, это зона save-to-library.
        return {"valid": True, "blocking_count": 0, "issues": []}
    if not isinstance(cond, dict):
        issues.append(_issue(
            "conditional_on_scenarios", "nonstandard_structure", "dict", type(cond).__name__,
        ))
        return {"valid": False, "blocking_count": len(issues), "issues": issues}

    if "coherence_diagnostic" in cond:
        issues.append(_issue(
            "conditional_on_scenarios.coherence_diagnostic",
            "coherence_misplaced",
            "coherence_diagnostic на top-level forecast YAML (§5.1)",
            "вложен в conditional_on_scenarios",
        ))

    by_scenario = cond.get("by_scenario")
    if not isinstance(by_scenario, dict):
        issues.append(_issue(
            "conditional_on_scenarios.by_scenario", "nonstandard_structure",
            "dict с ключами A, B, C, D", type(by_scenario).__name__,
        ))
        by_scenario = {}

    for sid, entry in sorted(by_scenario.items()):
        prefix = f"conditional_on_scenarios.by_scenario.{sid}"
        if not isinstance(entry, dict):
            issues.append(_issue(prefix, "nonstandard_structure", "dict", type(entry).__name__))
            continue

        provenance = entry.get("provenance")
        if provenance not in VALID_PROVENANCE:
            if provenance in LEGACY_PROVENANCE_MAP:
                actual = (
                    f"legacy '{provenance}' → '{LEGACY_PROVENANCE_MAP[provenance]}' (§5.2.1)"
                )
            else:
                actual = str(provenance)
            issues.append(_issue(
                f"{prefix}.provenance", "nonstandard_field_names",
                f"one of {sorted(VALID_PROVENANCE)}", actual,
            ))

        # non-spec структура значений: horizon_2026 вместо values."YYYY-MM-DD"
        horizon_keys = [k for k in entry if _HORIZON_KEY_RE.match(str(k))]
        if horizon_keys:
            issues.append(_issue(
                prefix, "nonstandard_structure",
                'values: {"YYYY-MM-DD": {central, range}} (§5.1)',
                f"non-spec ключи {horizon_keys}",
            ))

        vals = entry.get("values")
        if isinstance(vals, dict):
            for hk, hv in vals.items():
                if not isinstance(hv, dict):
                    continue
                bad = sorted(set(hv) & {"central_estimate", "p10", "p90"})
                if bad:
                    issues.append(_issue(
                        f"{prefix}.values.{hk}", "nonstandard_field_names",
                        "{central, range: [lo, hi]} (§5.1)", f"non-spec ключи {bad}",
                    ))
                if "unit" in hv:
                    issues.append(_issue(
                        f"{prefix}.values.{hk}.unit", "nonstandard_field_names",
                        "unit один на блок conditional_on_scenarios (§5.2)",
                        "unit внутри значения горизонта",
                    ))

        sources = entry.get("sources_used")
        if isinstance(sources, int) and not isinstance(sources, bool):
            issues.append(_issue(
                f"{prefix}.sources_used", "nonstandard_field_names",
                "список объектов {source_id, camp_weight, reasoning} (§5.2)",
                f"число {sources} (детали не в sources_used_detail)",
            ))

        upstream = entry.get("upstream_used")
        if upstream is not None:
            if not isinstance(upstream, list) or any(not isinstance(u, dict) for u in upstream):
                issues.append(_issue(
                    f"{prefix}.upstream_used", "nonstandard_structure",
                    "list of {factor, value, unit?, source_file?} (§5.2.1)",
                    type(upstream).__name__,
                ))
                upstream = None
            else:
                for ui, u in enumerate(upstream):
                    if not isinstance(u.get("factor"), str) or not u.get("factor"):
                        issues.append(_issue(
                            f"{prefix}.upstream_used[{ui}].factor",
                            "nonstandard_structure", "non-empty string", u.get("factor"),
                        ))
                    uv = u.get("value")
                    if isinstance(uv, bool) or not isinstance(uv, (int, float)):
                        issues.append(_issue(
                            f"{prefix}.upstream_used[{ui}].value",
                            "nonstandard_structure", "number", uv,
                        ))

        # Кросс-правила §5.2.1 (pre-save нового артефакта → blocking)
        if provenance in PROVENANCE_NEEDS_SOURCES:
            if not (isinstance(sources, list) and len(sources) > 0):
                issues.append(_issue(
                    f"{prefix}.sources_used", "cross_validation",
                    f"непустой список объектов при provenance: {provenance} (§5.2.1)",
                    f"{type(sources).__name__}",
                ))
        elif provenance == "derived_from_upstream":
            if not (isinstance(upstream, list) and len(upstream) > 0):
                issues.append(_issue(
                    f"{prefix}.upstream_used", "cross_validation",
                    "непустой upstream_used при provenance: derived_from_upstream (§5.2.1)",
                    f"{type(upstream).__name__ if upstream is not None else None}",
                ))

    return {
        "valid": not issues,
        "blocking_count": len(issues),
        "issues": issues,
    }


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception as e:  # noqa: BLE001 — CLI-гейт, любой сбой парсинга фатален
        print(json.dumps({
            "valid": False, "blocking_count": 1,
            "issues": [_issue("<stdin>", "nonstandard_structure", "valid JSON", str(e)[:120])],
        }, ensure_ascii=False, indent=2))
        return 1
    result = check_fca_output(data)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
