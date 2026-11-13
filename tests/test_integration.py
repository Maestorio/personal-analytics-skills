#!/usr/bin/env python3
"""
Интеграционные тесты Phase 5.2.

Тест 1 — End-to-end: scenario YAML edit → RECALIBRATE → новый stress YAML
Тест 2 — Migration → load → aggregate_marginal → сравнение с pre-migration central_estimate
Тест 3 — Two-marginal divergence: asymmetric scenario weights

Запуск:
    python3 tests/test_integration.py
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "skills" / "macro-forecast-chain" / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "skills" / "forecast-confidence-applier" / "scripts"))

from migrate_to_conditional import migrate_forecast
from recalibrate import recalibrate, modal_scenario, StaleMarginalError
from weighted_consensus import aggregate_marginal

FIXTURES = Path(__file__).parent / "fixtures"
SCENARIO_EQ = str(FIXTURES / "scenario-equal-weights.yaml")
RU_RATES_YAML = FIXTURES / "ru-rates-2026-2027-2026-05-04.yaml"

checks_run = 0
checks_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    status = "OK" if condition else "FAIL"
    if not condition:
        checks_failed += 1
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


def _write_scenario(path: Path, weights: dict[str, float]) -> None:
    """
    Форма РЕАЛЬНОГО SSOT — список `scenario_triggers` (spec §1.1 и все шесть
    живых матриц). До 2026-08-05 здесь, как и в test_recalibrate.py, писалась
    третья форма (`scenarios:` mapping), которой нет ни в спеке, ни в природе:
    её понимал только построчный regex-парсер `load_weights`, из-за чего дефект
    «на живых матрицах возвращается {}» тестами не ловился.
    """
    data = {"scenario_triggers": [
        {"scenario_id": sid, "label": f"Scenario {sid}", "probability": w}
        for sid, w in weights.items()
    ]}
    path.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False), encoding="utf-8")


def _write_stress(path: Path, weights: dict[str, float]) -> None:
    modal = modal_scenario(weights)
    data = {
        "modal_scenario_id": modal,
        "modal_probability": weights[modal],
        "hedge_target": min(weights, key=lambda k: weights[k]),
        "run_metadata": {"weights_snapshot": dict(weights)},
    }
    path.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False), encoding="utf-8")


# ─── Тест 1: scenario YAML edit → RECALIBRATE → stress YAML ──────────────────

def test_e2e_scenario_edit_to_stress():
    """
    1. Старт: scenario c равными весами (0.25 × 4), stress YAML с modal=none.
    2. Шаг: migrating ru-rates forecast → forecast YAML с conditional_on_scenarios.
    3. Шаг: изменить веса (D=0.525, dominant).
    4. RECALIBRATE → проверить обновление stress YAML и Layer 2 marginal.
    """
    print("test_e2e_scenario_edit_to_stress")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        scenario_path = tmpdir / "scenario.yaml"
        stress_path = tmpdir / "stress.yaml"
        output_path = tmpdir / "stress_updated.yaml"
        forecasts_dir = tmpdir / "forecasts"
        forecasts_dir.mkdir()

        # Шаг 1: начальные равные веса
        _write_scenario(scenario_path, {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})
        _write_stress(stress_path, {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})

        # Шаг 2: мигрируем ru-rates fixture → forecast с conditional_on_scenarios
        orig = yaml.safe_load(RU_RATES_YAML.read_text(encoding="utf-8"))
        migrated, result = migrate_forecast(orig, SCENARIO_EQ)
        check("миграция прошла (нет критических предупреждений)",
              migrated is not None,
              f"warnings: {result.warnings}")
        check("conditional_on_scenarios создан", "conditional_on_scenarios" in migrated)

        # Спека §1.3: RECALIBRATE трогает только прогнозы, привязанные к
        # пересчитываемой матрице. Мигратор проставил имя своей фикстуры
        # (`scenario-equal-weights.yaml`) — переводим на ту матрицу, которую
        # шаг 4 и пересчитывает, иначе прогноз законно пропускается.
        migrated["conditional_on_scenarios"]["source_matrix"] = \
            f"scenarios/{scenario_path.name}"

        forecast_path = forecasts_dir / "ru-rates.yaml"
        forecast_path.write_text(
            yaml.dump(migrated, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8"
        )

        # L2 marginal при равных весах: (10.5+12.5+11.5+13.5)/4 = 12.0 для 2026-12-31
        cond = migrated["conditional_on_scenarios"]
        l2_marginal_initial = cond["marginal"]["values"].get("2026-12-31", {}).get("central")
        check("L2 marginal при равных весах ≈ 12.0",
              l2_marginal_initial is not None and abs(l2_marginal_initial - 12.0) < 0.01,
              f"got {l2_marginal_initial}")

        # Шаг 3: изменяем веса — D становится доминирующим
        new_weights = {"A": 0.10, "B": 0.20, "C": 0.175, "D": 0.525}
        _write_scenario(scenario_path, new_weights)

        # Шаг 4: RECALIBRATE
        recal_result = recalibrate(
            scenario_yaml_path=scenario_path,
            forecasts_dir=forecasts_dir,
            stress_yaml_path=stress_path,
            output_path=output_path,
            strict=False,
        )

        # Проверяем stress YAML обновлён
        check("output stress YAML создан", output_path.exists())
        updated_stress = yaml.safe_load(output_path.read_text(encoding="utf-8"))
        check("modal_scenario_id = D в новом stress",
              updated_stress.get("modal_scenario_id") == "D")
        check("modal_changed = True", recal_result.modal_changed)
        check("old_modal = none / equal (A,B,C,D по 0.25)",
              recal_result.old_modal in (None, "A", "B", "C", "D"))
        check("new_modal = D", recal_result.new_modal == "D")

        # L2 marginal в forecast после RECALIBRATE:
        # 0.10*10.5 + 0.20*12.5 + 0.175*11.5 + 0.525*13.5 = 12.63...
        expected_new_l2 = (
            new_weights["A"] * 10.5 + new_weights["B"] * 12.5
            + new_weights["C"] * 11.5 + new_weights["D"] * 13.5
        )
        updated_forecast = yaml.safe_load(forecast_path.read_text(encoding="utf-8"))
        new_l2 = (updated_forecast["conditional_on_scenarios"]["marginal"]["values"]
                  .get("2026-12-31", {}).get("central"))
        check("L2 marginal обновлён после RECALIBRATE",
              new_l2 is not None and abs(new_l2 - expected_new_l2) < 0.01,
              f"expected {expected_new_l2:.4f}, got {new_l2}")

        check("stale_recalculated не пуст (marginal пересчитан)",
              len(recal_result.stale_recalculated) > 0)


# ─── Тест 2: migration → aggregate_marginal → сравнение с Layer 1 ─────────────

def test_migration_and_aggregate_marginal_consistency():
    """
    Мигрируем ru-rates, затем вызываем aggregate_marginal() с равными весами,
    сравниваем с pre-migration central_estimate.
    """
    print("test_migration_and_aggregate_marginal_consistency")

    orig = yaml.safe_load(RU_RATES_YAML.read_text(encoding="utf-8"))
    migrated, result = migrate_forecast(orig, SCENARIO_EQ)

    cond = migrated.get("conditional_on_scenarios", {})
    by_sc = cond.get("by_scenario", {})
    horizon = "2026-12-31"
    equal_weights = {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}

    # aggregate_marginal напрямую
    agg = aggregate_marginal(by_sc, equal_weights, horizon, "linear")
    check("aggregate_marginal возвращает central",
          "central" in agg, f"got {agg}")
    # (10.5+12.5+11.5+13.5)/4 = 12.0
    check("aggregate_marginal(equal) = 12.0",
          abs(agg["central"] - 12.0) < 0.01,
          f"got {agg['central']}")

    # Layer 2 marginal в migrated совпадает с aggregate_marginal
    l2 = cond["marginal"]["values"].get(horizon, {}).get("central")
    check("Layer 2 marginal совпадает с aggregate_marginal",
          l2 is not None and abs(l2 - agg["central"]) < 0.01,
          f"L2={l2}, agg={agg['central']}")

    # coherence_diagnostic присутствует
    diag = migrated.get("coherence_diagnostic", {})
    check("coherence_diagnostic.severity присутствует",
          diag.get("severity") in ("LOW", "MEDIUM", "HIGH", "UNKNOWN"))

    # Layer 1 marginal из текстового central_estimate (приблизительно)
    layer1 = diag.get("layer1_marginal")
    if layer1 is not None:
        # Layer 1 ≈ 12.7% из "weighted median 12.7%"
        check("Layer 1 marginal ≈ 12–13%", 11.0 <= layer1 <= 14.0,
              f"got {layer1}")


# ─── Тест 3: two-marginal divergence с асимметричными весами ──────────────────

def test_two_marginal_divergence_asymmetric():
    """
    При доминировании Sc-D (p=0.525) Layer 2 marginal смещается вверх от Layer 1.
    Проверяем severity determination.
    """
    print("test_two_marginal_divergence_asymmetric")

    # by_scenario с сильным D
    by_sc = {
        "A": {"values": {"2026-12-31": {"central": 10.0}}},
        "B": {"values": {"2026-12-31": {"central": 12.0}}},
        "C": {"values": {"2026-12-31": {"central": 11.0}}},
        "D": {"values": {"2026-12-31": {"central": 15.0}}},  # D сильно выше
    }
    # layer1 = 12.0 (trust-weighted FCA, не зависит от весов)
    layer1 = 12.0

    # равные веса: L2 = (10+12+11+15)/4 = 12.0 → нет расхождения
    w_equal = {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}
    l2_equal = aggregate_marginal(by_sc, w_equal, "2026-12-31", "linear")["central"]
    divergence_equal = abs(layer1 - l2_equal) / abs(layer1) * 100
    check("равные веса: нет расхождения", divergence_equal < 1.0,
          f"divergence={divergence_equal:.2f}%")

    # несимметричные веса: D=0.525 → L2 выше 12.0
    w_skewed = {"A": 0.10, "B": 0.20, "C": 0.175, "D": 0.525}
    l2_skewed = aggregate_marginal(by_sc, w_skewed, "2026-12-31", "linear")["central"]
    check("скошенные веса: L2 > layer1",
          l2_skewed > layer1,
          f"L2={l2_skewed:.3f}, L1={layer1}")

    divergence_pct = abs(layer1 - l2_skewed) / abs(layer1) * 100
    check("расхождение >5% при доминировании D", divergence_pct > 5.0,
          f"divergence={divergence_pct:.2f}%")

    # severity
    severity = "LOW" if divergence_pct < 5 else ("MEDIUM" if divergence_pct < 15 else "HIGH")
    check("severity = MEDIUM или HIGH при ~15% расхождении",
          severity in ("MEDIUM", "HIGH"),
          f"severity={severity}, div={divergence_pct:.1f}%")


# ─── Тест 4: validate_schema end-to-end ───────────────────────────────────────

def test_validate_schema_e2e():
    """validate_schema.py корректно валидирует fixtures/ без ошибок."""
    print("test_validate_schema_e2e")

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from validate_schema import validate_directory, validate_file

    # Все fixtures должны проходить без ERROR
    result = validate_directory(FIXTURES)
    errors = result.errors
    check("fixtures/ без ошибок схемы",
          len(errors) == 0,
          f"ошибки: {[str(e) for e in errors]}")

    # Намеренно сломанный scenario YAML: сумма ≠ 1
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.yaml"
        bad.write_text(
            "scenarios:\n  A: {probability: 0.5}\n  B: {probability: 0.5}\n"
            "  C: {probability: 0.3}\n  D: {probability: 0.1}\n",
            encoding="utf-8"
        )
        r = validate_file(bad)
        check("сломанный scenario (сумма 1.4) → ERROR",
              len(r.errors) > 0,
              f"issues: {r.issues}")

    # Forecast со string вместо числа в central
    with tempfile.TemporaryDirectory() as tmp:
        bad2 = Path(tmp) / "bad2.yaml"
        bad2.write_text(
            "conditional_on_scenarios:\n"
            "  by_scenario:\n"
            "    A:\n      values:\n        '2026-12-31':\n          central: '12.5%'\n"
            "    B:\n      values:\n        '2026-12-31':\n          central: 11.0\n"
            "    C:\n      values:\n        '2026-12-31':\n          central: 11.0\n"
            "    D:\n      values:\n        '2026-12-31':\n          central: 11.0\n",
            encoding="utf-8"
        )
        r2 = validate_file(bad2)
        check("forecast со string central → ERROR",
              len(r2.errors) > 0,
              f"issues: {r2.issues}")


# ─── Runner ────────────────────────────────────────────────────────────────────

def test_isolated_type1_e2e():
    """Type 1 isolated: migrate с --isolated → schema-валидация → не блокируется."""
    print("test_isolated_type1_e2e")
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from validate_schema import validate_file

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        forecast_path = tmpdir / "russia-europe-war-2030.yaml"
        # Минимальный Type 1 forecast (long-horizon binary event).
        forecast_path.write_text(
            "schema_version: 1\n"
            "type: forecast-events\n"
            "forecast:\n"
            "  date: 2026-04-29\n"
            "  horizon: 2030-12-31\n"
            "  domain: geopolitics\n"
            "  topic: russia-europe-war-2030\n"
            "  central_estimate: 'Война РФ–НАТО: вероятность <15% к 2030-12-31'\n"
            "  confidence: 0.4\n",
            encoding="utf-8"
        )
        data = yaml.safe_load(forecast_path.read_text(encoding="utf-8"))
        updated, result = migrate_forecast(data, SCENARIO_EQ, isolated=True)

        check("Type 1: isolated=True", updated.get("isolated") is True)
        check("Type 1: isolated_reason присутствует",
              isinstance(updated.get("isolated_reason"), str))
        check("Type 1: НЕТ conditional_on_scenarios",
              "conditional_on_scenarios" not in updated)
        check("Type 1: НЕТ coherence_diagnostic",
              "coherence_diagnostic" not in updated)
        check("Type 1: EC5a в логе",
              any("EC5a" in e for e in result.log),
              f"log: {result.log}")

        # Запись и schema validation.
        forecast_path.write_text(
            yaml.dump(updated, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8"
        )
        v = validate_file(forecast_path)
        check("Type 1: validate_schema без ERROR", len(v.errors) == 0,
              f"errors: {[str(e) for e in v.errors]}")


def test_axis_dependent_placeholder_e2e():
    """axis_dependent: миграция РАЗРЕШАЕТ через weighted_mean вдоль доминантной оси (SB-1, Phase 2.6)."""
    print("test_axis_dependent_placeholder_e2e")
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from validate_schema import validate_file

    data = {
        "schema_version": 1,
        "type": "forecast-events",
        "forecast": {
            "date": "2026-05-02",
            "horizon": "2027-12-31",
            "horizons": ["2026-12-31", "2027-12-31"],
            "domain": "geopolitics",
            "topic": "sanctions-russia",
            "central_estimate": "Санкции на РФ: 8/10 баллов к 2026-12-31",
            "confidence": 0.5,
        },
        "geopolitics_translation": {
            "method": "axis_dependent",
            "scenario_rates_2026": {
                "Sc-A": "3", "Sc-B": "5", "Sc-C": "7", "Sc-D": "9",
            },
        },
    }
    updated, result = migrate_forecast(data, SCENARIO_EQ)
    cond = updated.get("conditional_on_scenarios", {})
    marg = cond.get("marginal", {})

    check("axis_dependent: method preserved",
          marg.get("method") == "axis_dependent",
          f"got {marg.get('method')}")
    # SB-1 (DONE 2026-06-09): axis_dependent больше НЕ placeholder — резолвится в weighted_mean.
    check("axis_dependent: НЕ placeholder (_todo отсутствует)",
          "_todo" not in marg,
          f"got _todo={marg.get('_todo')!r}")
    check("axis_dependent: aggregation_formula = weighted_mean",
          marg.get("aggregation_formula") == "weighted_mean",
          f"got {marg.get('aggregation_formula')}")
    check("axis_dependent: EC5c (resolved) в логе",
          any("EC5c" in e for e in result.log))

    # weighted_consensus.aggregate_marginal должна явно raise NotImplementedError.
    raised = False
    try:
        aggregate_marginal(
            cond.get("by_scenario", {}),
            {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25},
            "2026-12-31", "axis_dependent"
        )
    except NotImplementedError:
        raised = True
    check("axis_dependent: aggregate_marginal raises NotImplementedError",
          raised)


def test_stress_yaml_validation():
    """validate_stress_yaml: проверяет required fields + D2 + robustness."""
    print("test_stress_yaml_validation")
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from validate_schema import validate_file

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        # Корректный Pure Shell stress без expected_pl_*.
        ok = tmpdir / "stress-ok.yaml"
        ok.write_text(yaml.dump({
            "schema_version": 1,
            "type": "portfolio-stress-test",
            "date": "2026-05-08",
            "portfolio_snapshot_id": "portfolio-2026-05-07.json",
            "scenario_source": "macro-forecast-chain",
            "weight_type": "equal",
            "scenarios": {"Sc-A_bull": {}, "Sc-B_stress": {}, "Sc-C_war": {}, "Sc-D_base": {}},
            "per_position": {},
            "portfolio_pl_range_rub": {"min": -50000, "max": 70000},
            "robustness": {
                "worst_case": {"id": "Sc-B_stress", "pl_pct": -5.7},
                "best_case": {"id": "Sc-D_base", "pl_pct": 7.9},
                "spread": 13.6,
                "modal_scenario": "none",
            },
            "review_date": "2026-11-08",
        }, allow_unicode=True), encoding="utf-8")
        v = validate_file(ok)
        check("корректный Pure Shell stress: 0 ERROR", len(v.errors) == 0,
              f"errors: {[str(e) for e in v.errors]}")

        # D2 violation: equal weights + expected_pl_pct → WARNING.
        bad = tmpdir / "stress-d2.yaml"
        d2_data = yaml.safe_load(ok.read_text(encoding="utf-8"))
        d2_data["expected_pl_pct"] = 1.5
        bad.write_text(yaml.dump(d2_data, allow_unicode=True), encoding="utf-8")
        v = validate_file(bad)
        check("D2: equal+expected_pl_pct → WARNING",
              any(i.severity == "WARNING" and "expected_pl" in i.field
                  for i in v.issues),
              f"issues: {[str(i) for i in v.issues]}")

        # Отсутствует robustness → ERROR.
        bad2 = tmpdir / "stress-noobust.yaml"
        d2_data = yaml.safe_load(ok.read_text(encoding="utf-8"))
        del d2_data["robustness"]
        bad2.write_text(yaml.dump(d2_data, allow_unicode=True), encoding="utf-8")
        v = validate_file(bad2)
        check("отсутствует robustness → ERROR",
              any(i.field == "robustness" for i in v.errors),
              f"errors: {[str(e) for e in v.errors]}")


def main() -> None:
    print("=" * 60)
    print("test_integration.py")
    print("=" * 60)

    test_e2e_scenario_edit_to_stress()
    test_migration_and_aggregate_marginal_consistency()
    test_two_marginal_divergence_asymmetric()
    test_validate_schema_e2e()
    test_isolated_type1_e2e()
    test_axis_dependent_placeholder_e2e()
    test_stress_yaml_validation()

    print("=" * 60)
    print(f"Итого: {checks_run} проверок, {checks_failed} провалено")
    if checks_failed:
        print("СТАТУС: FAIL")
        sys.exit(1)
    else:
        print("СТАТУС: OK")


if __name__ == "__main__":
    main()
