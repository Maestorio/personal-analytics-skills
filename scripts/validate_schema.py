#!/usr/bin/env python3
"""
Валидатор схем для Phase 5.3.

Проверяет:
  - scenario YAML: sum of weights == 1.0 ± 0.001, all 4 scenarios present
  - forecast YAML с conditional_on_scenarios: all-4-scenarios, numbers in values
  - implicit_geopolitical_scenarios: primary.weight + secondary.weight == 1.0

Запуск:
    python3 scripts/validate_schema.py scenarios/foo.yaml
    python3 scripts/validate_schema.py --all-forecasts forecasts/ scenarios/
    echo $?   # 0 = OK, 1 = ошибки найдены
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

REQUIRED_SCENARIO_IDS = {"A", "B", "C", "D"}
WEIGHT_TOLERANCE = 0.001


# ── Результат валидации ────────────────────────────────────────────────────────

class ValidationIssue:
    def __init__(self, path: str, field: str, message: str, severity: str = "ERROR"):
        self.path = path
        self.field = field
        self.message = message
        self.severity = severity

    def __str__(self) -> str:
        return f"[{self.severity}] {self.path} | {self.field}: {self.message}"


class ValidationResult:
    def __init__(self):
        self.issues: list[ValidationIssue] = []

    def add(self, path: str, field: str, message: str, severity: str = "ERROR") -> None:
        self.issues.append(ValidationIssue(path, field, message, severity))

    @property
    def ok(self) -> bool:
        return not any(i.severity == "ERROR" for i in self.issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "ERROR"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "WARNING"]


# ── Валидаторы ──────────────────────────────────────────────────────────────

def validate_scenario_yaml(data: dict, file_path: str = "<unknown>") -> ValidationResult:
    """
    Проверяет scenario YAML (SSOT весов):
      - scenarios присутствует
      - все 4 ID (A, B, C, D) присутствуют
      - у каждого есть probability (число, не строка)
      - sum(probabilities) == 1.0 ± WEIGHT_TOLERANCE
    """
    result = ValidationResult()

    if "scenarios" not in data:
        result.add(file_path, "scenarios", "поле отсутствует")
        return result

    scenarios = data["scenarios"]
    present_ids = set(scenarios.keys())
    missing = REQUIRED_SCENARIO_IDS - present_ids
    if missing:
        result.add(file_path, "scenarios", f"отсутствуют сценарии: {sorted(missing)}")

    total = 0.0
    for sid, sc in scenarios.items():
        if "probability" not in sc:
            result.add(file_path, f"scenarios.{sid}.probability", "поле отсутствует")
            continue
        prob = sc["probability"]
        if not isinstance(prob, (int, float)):
            result.add(file_path, f"scenarios.{sid}.probability",
                       f"должно быть числом, получено: {type(prob).__name__} ({prob!r})")
            continue
        if prob < 0 or prob > 1:
            result.add(file_path, f"scenarios.{sid}.probability",
                       f"вне диапазона [0, 1]: {prob}")
        total += prob

    if present_ids >= REQUIRED_SCENARIO_IDS:
        if abs(total - 1.0) > WEIGHT_TOLERANCE:
            result.add(file_path, "scenarios[*].probability",
                       f"сумма весов {total:.4f} ≠ 1.0 (допуск {WEIGHT_TOLERANCE})")

    return result


def validate_conditional_on_scenarios(data: dict, file_path: str = "<unknown>") -> ValidationResult:
    """
    Проверяет блок conditional_on_scenarios в forecast YAML:
      - by_scenario содержит все 4 сценария
      - values[*].central — числа, не строки
      - marginal.values[*].central — числа
      - coherence_diagnostic.severity — допустимое значение
    """
    result = ValidationResult()

    cond = data.get("conditional_on_scenarios")
    if cond is None:
        return result  # блок отсутствует — не ошибка

    by_sc = cond.get("by_scenario", {})
    present_ids = set(by_sc.keys())
    missing = REQUIRED_SCENARIO_IDS - present_ids
    if missing:
        result.add(file_path, "conditional_on_scenarios.by_scenario",
                   f"отсутствуют сценарии: {sorted(missing)}")

    for sid, sc_data in by_sc.items():
        values = sc_data.get("values", {})
        for horizon, hdata in values.items():
            central = hdata.get("central")
            if central is None:
                result.add(file_path, f"by_scenario.{sid}.values.{horizon}.central",
                           "поле отсутствует")
            elif isinstance(central, str):
                result.add(file_path, f"by_scenario.{sid}.values.{horizon}.central",
                           f"должно быть числом, получено строку: {central!r}")
            elif not isinstance(central, (int, float)):
                result.add(file_path, f"by_scenario.{sid}.values.{horizon}.central",
                           f"ожидался int/float, получено: {type(central).__name__}")

            rng = hdata.get("range")
            if rng is not None:
                if not isinstance(rng, list) or len(rng) != 2:
                    result.add(file_path, f"by_scenario.{sid}.values.{horizon}.range",
                               "должен быть список [lo, hi]", severity="WARNING")
                else:
                    lo, hi = rng
                    if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)):
                        result.add(file_path, f"by_scenario.{sid}.values.{horizon}.range",
                                   "lo и hi должны быть числами")

    marginal = cond.get("marginal", {})
    for horizon, hdata in marginal.get("values", {}).items():
        if not isinstance(hdata, dict):
            continue
        central = hdata.get("central")
        if isinstance(central, str):
            result.add(file_path, f"conditional_on_scenarios.marginal.values.{horizon}.central",
                       f"должно быть числом, получено строку: {central!r}")

    diag = data.get("coherence_diagnostic")
    if diag is not None:
        sev = diag.get("severity")
        valid_severities = {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}
        if sev not in valid_severities:
            result.add(file_path, "coherence_diagnostic.severity",
                       f"недопустимое значение: {sev!r}. Допустимые: {valid_severities}")

    return result


def validate_isolated_forecast(data: dict, file_path: str = "<unknown>") -> ValidationResult:
    """
    Type 1 (isolated) per events-yaml-spec.md §5.5:
      - isolated: true → conditional_on_scenarios отсутствует
      - isolated_reason: непустая строка ≤200 симв
      - coherence_diagnostic не должно быть
    """
    result = ValidationResult()
    if data.get("isolated") is not True:
        return result

    reason = data.get("isolated_reason")
    if not isinstance(reason, str) or not reason.strip():
        result.add(file_path, "isolated_reason",
                   "обязательно при isolated: true (непустая строка ≤200 симв)")
    elif len(reason) > 200:
        result.add(file_path, "isolated_reason",
                   f"длина {len(reason)} > 200 симв", severity="WARNING")

    if "conditional_on_scenarios" in data:
        result.add(file_path, "conditional_on_scenarios",
                   "Type 1 (isolated) НЕ должен содержать conditional_on_scenarios")
    if "coherence_diagnostic" in data:
        result.add(file_path, "coherence_diagnostic",
                   "Type 1 (isolated) НЕ должен содержать coherence_diagnostic",
                   severity="WARNING")
    return result


def validate_stress_yaml(data: dict, file_path: str = "<unknown>") -> ValidationResult:
    """
    Stress YAML (type: portfolio-stress-test) per `_shared-references/stress-yaml-spec.md`:
      - Обязательные поля: schema_version, type, date, portfolio_snapshot_id,
        scenario_source, weight_type, scenarios, per_position, robustness, ...
      - D2: expected_pl_* отсутствует при weight_type=equal (Pure Shell)
      - robustness обязателен (Phase 2.7)
      - modal_scenario_id rule: argmax если max>0.30 else "none"
    """
    result = ValidationResult()
    if data.get("type") != "portfolio-stress-test":
        return result  # не stress YAML

    required_top = [
        "schema_version", "date", "portfolio_snapshot_id", "scenario_source",
        "weight_type", "scenarios", "per_position", "portfolio_pl_range_rub",
        "robustness", "review_date",
    ]
    for field in required_top:
        if field not in data:
            result.add(file_path, field, "обязательное поле отсутствует")

    sv = data.get("schema_version")
    v2 = (sv == 2 and not isinstance(sv, bool))
    if sv not in (1, 2) or isinstance(sv, bool):
        result.add(file_path, "schema_version",
                   f"ожидался schema_version: 1 или 2, получено {sv!r}")
    if v2:
        # Phase 4 (multiple horizons): horizon-блок обязателен, v1-поля запрещены.
        for f in ("horizons", "horizon_ends", "primary_horizon"):
            if f not in data:
                result.add(file_path, f, "v2: обязательное поле горизонтов отсутствует")
        for f in ("horizon_months", "horizon"):
            if f in data:
                result.add(file_path, f,
                           f"v1-поле '{f}' недопустимо в v2 (v1_field_in_v2)")
        horizons = data.get("horizons")
        if isinstance(horizons, list) and data.get("primary_horizon") not in horizons:
            result.add(file_path, "primary_horizon", "должно входить в horizons")

    weight_type = data.get("weight_type")
    if weight_type not in ("equal", "probability"):
        result.add(file_path, "weight_type",
                   f"должно быть 'equal' или 'probability', получено {weight_type!r}")

    # D2: Pure Shell (equal weights) — НЕ должно быть expected_pl_*.
    if weight_type == "equal":
        if "expected_pl_pct" in data or "expected_pl_rub" in data:
            result.add(file_path, "expected_pl_*",
                       "при weight_type=equal expected_pl_* не должны присутствовать (D2)",
                       severity="WARNING")

    robustness = data.get("robustness")
    if isinstance(robustness, dict):
        for sub in ("worst_case", "best_case", "spread"):
            if sub not in robustness:
                result.add(file_path, f"robustness.{sub}",
                           "обязательное подполе отсутствует")
        modal = robustness.get("modal_scenario")
        if weight_type == "equal" and modal not in (None, "none", ""):
            result.add(file_path, "robustness.modal_scenario",
                       f"при equal weights должно быть 'none', получено {modal!r}",
                       severity="WARNING")

    return result


def validate_implicit_geopolitical_scenarios(data: dict, file_path: str = "<unknown>") -> ValidationResult:
    """
    Проверяет implicit_geopolitical_scenarios в audit frontmatter:
      - agnostic_total или primary обязательны
      - primary.weight + secondary.weight == 1.0 (если secondary присутствует)
      - scenario_id — одна из A/B/C/D
    """
    result = ValidationResult()

    igs = data.get("implicit_geopolitical_scenarios")
    if igs is None:
        return result

    if igs.get("agnostic_total") is True:
        return result  # полностью агностик — OK

    primary = igs.get("primary")
    if primary is None:
        result.add(file_path, "implicit_geopolitical_scenarios.primary",
                   "обязательно при отсутствии agnostic_total")
        return result

    primary_sid = primary.get("scenario_id")
    if primary_sid not in REQUIRED_SCENARIO_IDS:
        result.add(file_path, "implicit_geopolitical_scenarios.primary.scenario_id",
                   f"недопустимый ID: {primary_sid!r}. Допустимые: A/B/C/D")

    primary_w = primary.get("weight", 0.0)
    secondary = igs.get("secondary")
    if secondary:
        secondary_sid = secondary.get("scenario_id")
        if secondary_sid not in REQUIRED_SCENARIO_IDS:
            result.add(file_path, "implicit_geopolitical_scenarios.secondary.scenario_id",
                       f"недопустимый ID: {secondary_sid!r}")
        secondary_w = secondary.get("weight", 0.0)
        total = primary_w + secondary_w
        if abs(total - 1.0) > WEIGHT_TOLERANCE:
            result.add(file_path,
                       "implicit_geopolitical_scenarios primary.weight + secondary.weight",
                       f"сумма {total:.4f} ≠ 1.0")
    else:
        if abs(primary_w - 1.0) > WEIGHT_TOLERANCE:
            result.add(file_path,
                       "implicit_geopolitical_scenarios.primary.weight",
                       f"без secondary weight должен быть 1.0, получено {primary_w}",
                       severity="WARNING")

    return result


def validate_file(file_path: Path) -> ValidationResult:
    """Валидирует один YAML файл (автоопределение типа)."""
    combined = ValidationResult()
    path_str = str(file_path)

    try:
        data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except Exception as e:
        combined.add(path_str, "<yaml>", f"ошибка парсинга YAML: {e}")
        return combined

    if not isinstance(data, dict):
        combined.add(path_str, "<root>", "корень должен быть YAML mapping")
        return combined

    # validate_scenario_yaml только для SSOT scenario YAMLs (type=scenario-events
    # или просто `scenarios:` блок без `type`). Stress YAML тоже имеет `scenarios:`
    # ключ, но это другая схема (Sc-X_label).
    if "scenarios" in data and data.get("type") != "portfolio-stress-test":
        r = validate_scenario_yaml(data, path_str)
        combined.issues.extend(r.issues)

    if "conditional_on_scenarios" in data or "forecast" in data:
        r = validate_conditional_on_scenarios(data, path_str)
        combined.issues.extend(r.issues)

    if data.get("isolated") is True:
        r = validate_isolated_forecast(data, path_str)
        combined.issues.extend(r.issues)

    if data.get("type") == "portfolio-stress-test":
        r = validate_stress_yaml(data, path_str)
        combined.issues.extend(r.issues)

    if "implicit_geopolitical_scenarios" in data:
        r = validate_implicit_geopolitical_scenarios(data, path_str)
        combined.issues.extend(r.issues)

    return combined


def validate_directory(directory: Path) -> ValidationResult:
    """Рекурсивно валидирует все *.yaml файлы в директории."""
    combined = ValidationResult()
    yamls = sorted(directory.rglob("*.yaml"))
    if not yamls:
        combined.add(str(directory), "<dir>",
                     "не найдено *.yaml файлов", severity="WARNING")
        return combined
    for f in yamls:
        r = validate_file(f)
        combined.issues.extend(r.issues)
    return combined


# ── CLI ────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Валидатор схем scenario/forecast/implicit YAML"
    )
    parser.add_argument("paths", nargs="*",
                        help="Файлы или директории для валидации")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Только итог, без деталей")
    args = parser.parse_args(argv)

    all_issues: list[ValidationIssue] = []
    files_checked = 0

    for raw_path in (args.paths or ["."]):
        p = Path(raw_path)
        if p.is_dir():
            result = validate_directory(p)
            files_checked += len(list(p.rglob("*.yaml")))
        elif p.is_file():
            result = validate_file(p)
            files_checked += 1
        else:
            print(f"[ERROR] не найден путь: {p}", file=sys.stderr)
            return 1
        all_issues.extend(result.issues)

    errors = [i for i in all_issues if i.severity == "ERROR"]
    warnings = [i for i in all_issues if i.severity == "WARNING"]

    if not args.quiet:
        for issue in all_issues:
            print(issue)

    print(
        f"\nПроверено файлов: {files_checked}  |  "
        f"Ошибок: {len(errors)}  |  Предупреждений: {len(warnings)}"
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
