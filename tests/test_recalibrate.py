#!/usr/bin/env python3
"""
Регрессионные тесты для recalibrate.py (macro-forecast-chain Phase 4).

Запуск из корня репозитория:
    python3 tests/test_recalibrate.py
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "skills" / "macro-forecast-chain" / "scripts" / "recalibrate.py"

sys.path.insert(0, str(SCRIPT.parent))
from recalibrate import (  # noqa: E402
    RecalibrateResult,
    StaleMarginalError,
    WeightValidationError,
    load_horizon_weights,
    load_weights,
    modal_scenario,
    recalibrate,
    validate_weights,
    write_yaml_preserving,
)
import recalibrate as _rc  # noqa: E402

checks_run = 0
checks_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    status = "OK" if condition else "FAIL"
    if not condition:
        checks_failed += 1
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# Fixtures helpers
# ---------------------------------------------------------------------------

def _write_scenario(path: Path, weights: dict[str, float], *,
                    under_matrix: bool = False) -> None:
    """
    Пишет scenario YAML в форме РЕАЛЬНОГО SSOT: список `scenario_triggers` с
    `scenario_id`/`probability`.

    До 2026-08-05 фикстура писала третью форму — верхнеуровневый `scenarios:`
    mapping, которой нет ни в спеке (`scenario-yaml-spec.md` §1.1), ни в одной
    живой матрице. Построчный regex-парсер `load_weights` понимал ровно её, и
    дефект «на всех шести живых файлах возвращается {}» тестами не ловился
    вообще: они проверяли парсер на форме, которой в природе не существует.

    `under_matrix=True` — форма из спеки (блок под `matrix`); по умолчанию
    верхний уровень, как во всех живых файлах.
    """
    triggers = [{"scenario_id": sid, "label": f"Scenario {sid}", "probability": w}
                for sid, w in weights.items()]
    data = {"matrix": {"scenario_triggers": triggers}} if under_matrix \
        else {"scenario_triggers": triggers}
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _write_forecast(path: Path, by_scenario_values: dict[str, dict[str, float]],
                    old_marginal: dict[str, float], method: str = "linear",
                    source_matrix: str = "scenarios/scenario.yaml",
                    modal_scenario_id: str | None = None) -> None:
    """
    Пишет forecast YAML с conditional_on_scenarios.

    by_scenario_values: {sid: {horizon: central_value}}
    old_marginal: {horizon: central_value}
    source_matrix: спека §1.3 — пересчитываются только прогнозы, привязанные к
        пересчитываемой матрице. По умолчанию имя совпадает с фикстурой сценария
        (`scenario.yaml`), которую пишет `_write_scenario` в тех же тестах.
    """
    by_scenario = {}
    for sid, hzs in by_scenario_values.items():
        by_scenario[sid] = {
            "label": f"Scenario {sid}",
            "probability": 0.25,
            "provenance": "direct",
            "values": {hz: {"central": v} for hz, v in hzs.items()},
        }
    data = {
        "schema_version": 1,
        "type": "forecast-events",
        "status": "active",
        "forecast": {
            "date": "2026-05-04",
            "central_estimate": str(list(old_marginal.values())[0]),
            "confidence": 0.45,
        },
        "conditional_on_scenarios": {
            "source_matrix": source_matrix,
            "by_scenario": by_scenario,
            "marginal": {
                "method": method,
                "modal_scenario_id": modal_scenario_id or "none",
                "values": {hz: {"central": v} for hz, v in old_marginal.items()},
            },
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _write_stress(path: Path, weights_snapshot: dict[str, float]) -> None:
    """Пишет stress YAML с weights_snapshot и modal_scenario_id."""
    modal = modal_scenario(weights_snapshot)
    data = {
        "modal_scenario_id": modal,
        "modal_probability": weights_snapshot[modal],
        "hedge_target": min(weights_snapshot, key=lambda k: weights_snapshot[k]),
        "run_metadata": {
            "weights_snapshot": {k: v for k, v in weights_snapshot.items()},
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


# ---------------------------------------------------------------------------
# 1. Valid weight sum
# ---------------------------------------------------------------------------

def test_valid_weight_sum() -> None:
    print("test_valid_weight_sum")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "sc.yaml"

        # Корректная сумма 1.0
        _write_scenario(p, {"A": 0.40, "B": 0.30, "C": 0.20, "D": 0.10})
        weights = load_weights(p)
        try:
            validate_weights(weights)
            ok = True
        except WeightValidationError:
            ok = False
        check("сумма 1.0 → нет ошибки", ok)

        # Некорректная сумма 1.1
        _write_scenario(p, {"A": 0.50, "B": 0.40, "C": 0.10, "D": 0.10})
        weights = load_weights(p)
        try:
            validate_weights(weights)
            ok = False
        except WeightValidationError:
            ok = True
        check("сумма 1.1 → WeightValidationError", ok)

        # Отсутствует сценарий D
        _write_scenario(p, {"A": 0.50, "B": 0.25, "C": 0.25})
        weights = load_weights(p)
        try:
            validate_weights(weights)
            ok = False
        except WeightValidationError as e:
            ok = "D" in str(e)
        check("отсутствует D → WeightValidationError с упоминанием D", ok)

        # Граничный случай: сумма 0.9999 → в пределах допуска 0.001
        _write_scenario(p, {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.2499})
        weights = load_weights(p)
        try:
            validate_weights(weights)
            ok = True
        except WeightValidationError:
            ok = False
        check("сумма 0.9999 (в допуске) → нет ошибки", ok)


# ---------------------------------------------------------------------------
# 2. Modal scenario change detection
# ---------------------------------------------------------------------------

def test_modal_scenario_change() -> None:
    print("test_modal_scenario_change")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        scenario_path = tmpdir / "new_scenario.yaml"
        stress_path = tmpdir / "stress.yaml"
        output_path = tmpdir / "stress_updated.yaml"

        # Старый modal: D = 0.525
        _write_stress(stress_path, {"A": 0.10, "B": 0.20, "C": 0.175, "D": 0.525})

        # Новый modal: A = 0.45
        _write_scenario(scenario_path, {"A": 0.45, "B": 0.30, "C": 0.15, "D": 0.10})

        result = recalibrate(
            scenario_yaml_path=scenario_path,
            forecasts_dir=None,
            stress_yaml_path=stress_path,
            output_path=output_path,
            strict=False,
        )

        check("modal_changed=True", result.modal_changed)
        check("old_modal=D", result.old_modal == "D")
        check("new_modal=A", result.new_modal == "A")
        check("coverage_warning присутствует", result.coverage_warning is not None)
        check("coverage_warning упоминает D→A",
              "D" in (result.coverage_warning or "") and "A" in (result.coverage_warning or ""))

        # Когда modal не меняется
        _write_scenario(scenario_path, {"A": 0.10, "B": 0.20, "C": 0.175, "D": 0.525})
        result2 = recalibrate(
            scenario_yaml_path=scenario_path,
            forecasts_dir=None,
            stress_yaml_path=stress_path,
            output_path=output_path,
            strict=False,
        )
        check("modal_changed=False когда D остаётся modal", not result2.modal_changed)
        check("coverage_warning=None при неизменном modal", result2.coverage_warning is None)


# ---------------------------------------------------------------------------
# 3. Stale marginal auto-recalculate (soft mode)
# ---------------------------------------------------------------------------

def test_stale_marginal_soft() -> None:
    print("test_stale_marginal_soft")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        scenario_path = tmpdir / "scenario.yaml"
        forecasts_dir = tmpdir / "forecasts"
        forecasts_dir.mkdir()

        # Равные веса → L2 = (10+12+11+13)/4 = 11.5
        _write_scenario(scenario_path, {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})

        forecast_path = forecasts_dir / "test-forecast.yaml"
        _write_forecast(
            forecast_path,
            by_scenario_values={
                "A": {"2026-12-31": 10.0},
                "B": {"2026-12-31": 12.0},
                "C": {"2026-12-31": 11.0},
                "D": {"2026-12-31": 13.0},
            },
            old_marginal={"2026-12-31": 11.5},
        )

        # Новые веса: A=0.4, B=0.3, C=0.2, D=0.1
        # Новый L2 = 0.4*10 + 0.3*12 + 0.2*11 + 0.1*13 = 11.1
        # Расхождение = |11.5 - 11.1| / 11.5 = 3.48% > 1% → stale
        _write_scenario(scenario_path, {"A": 0.40, "B": 0.30, "C": 0.20, "D": 0.10})

        result = recalibrate(
            scenario_yaml_path=scenario_path,
            forecasts_dir=forecasts_dir,
            strict=False,
        )

        check("soft mode: stale_recalculated не пустой", len(result.stale_recalculated) > 0)
        check("soft mode: updated_files содержит forecast", len(result.updated_files) > 0)

        s = result.stale_recalculated[0]
        check("stale: horizon='2026-12-31'", s.horizon == "2026-12-31")
        check("stale: old_value≈11.5", abs(s.old_value - 11.5) < 0.01)
        check("stale: new_value≈11.1", abs(s.new_value - 11.1) < 0.01,
              f"got {s.new_value}")
        check("stale: divergence_pct > 1%", s.divergence_pct > 1.0,
              f"got {s.divergence_pct}")

        # Проверить, что файл действительно обновлён
        with open(forecast_path, "r", encoding="utf-8") as f:
            updated = yaml.safe_load(f)
        new_central = None
        marginal_values = updated["conditional_on_scenarios"]["marginal"]["values"]
        for k, v in marginal_values.items():
            if (k.isoformat() if hasattr(k, "isoformat") else str(k)) == "2026-12-31":
                new_central = v["central"]
        check("файл обновлён: central ≈ 11.1", new_central is not None and abs(new_central - 11.1) < 0.01,
              f"got {new_central}")


# ---------------------------------------------------------------------------
# 4. --strict refuses stale
# ---------------------------------------------------------------------------

def test_strict_refuses_stale() -> None:
    print("test_strict_refuses_stale")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        scenario_path = tmpdir / "scenario.yaml"
        forecasts_dir = tmpdir / "forecasts"
        forecasts_dir.mkdir()

        # Новые веса дают расхождение > 1% vs старые L2
        _write_scenario(scenario_path, {"A": 0.40, "B": 0.30, "C": 0.20, "D": 0.10})
        forecast_path = forecasts_dir / "test-forecast.yaml"
        _write_forecast(
            forecast_path,
            by_scenario_values={
                "A": {"2026-12-31": 10.0},
                "B": {"2026-12-31": 12.0},
                "C": {"2026-12-31": 11.0},
                "D": {"2026-12-31": 13.0},
            },
            old_marginal={"2026-12-31": 11.5},  # было при равных весах
        )

        # --strict должен выбросить исключение
        raised = False
        stale_count = 0
        try:
            recalibrate(
                scenario_yaml_path=scenario_path,
                forecasts_dir=forecasts_dir,
                strict=True,
            )
        except StaleMarginalError as e:
            raised = True
            stale_count = len(e.stale)

        check("strict: StaleMarginalError выброшен", raised)
        check("strict: stale содержит 1 запись", stale_count == 1, f"got {stale_count}")

        # Файл НЕ должен быть изменён в strict режиме
        with open(forecast_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        marginal_values = data["conditional_on_scenarios"]["marginal"]["values"]
        unchanged_central = None
        for k, v in marginal_values.items():
            if (k.isoformat() if hasattr(k, "isoformat") else str(k)) == "2026-12-31":
                unchanged_central = v["central"]
        check("strict: файл НЕ изменён (central=11.5)",
              unchanged_central is not None and abs(unchanged_central - 11.5) < 0.01,
              f"got {unchanged_central}")

        # Без расхождения strict должен работать нормально
        _write_forecast(
            forecast_path,
            by_scenario_values={
                "A": {"2026-12-31": 10.0},
                "B": {"2026-12-31": 12.0},
                "C": {"2026-12-31": 11.0},
                "D": {"2026-12-31": 13.0},
            },
            # L2 при A=0.4, B=0.3, C=0.2, D=0.1 = 11.1 (совпадает → не stale)
            old_marginal={"2026-12-31": 11.1},
        )
        raised_no_stale = False
        try:
            recalibrate(
                scenario_yaml_path=scenario_path,
                forecasts_dir=forecasts_dir,
                strict=True,
            )
        except StaleMarginalError:
            raised_no_stale = True
        check("strict без stale: исключение не выброшено", not raised_no_stale)


# ---------------------------------------------------------------------------
# 5. Время выполнения < 30 секунд
# ---------------------------------------------------------------------------

def test_time_guard() -> None:
    print("test_time_guard")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        scenario_path = tmpdir / "scenario.yaml"
        forecasts_dir = tmpdir / "forecasts"
        forecasts_dir.mkdir()
        stress_path = tmpdir / "stress.yaml"
        output_path = tmpdir / "output.yaml"

        _write_scenario(scenario_path, {"A": 0.40, "B": 0.30, "C": 0.20, "D": 0.10})
        _write_stress(stress_path, {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})

        # Создаём 10 forecast YAML файлов с двумя горизонтами каждый
        for i in range(10):
            _write_forecast(
                forecasts_dir / f"forecast-{i:02d}.yaml",
                by_scenario_values={
                    "A": {"2026-12-31": 10.0 + i * 0.1, "2027-12-31": 9.0 + i * 0.1},
                    "B": {"2026-12-31": 12.0 + i * 0.1, "2027-12-31": 11.0 + i * 0.1},
                    "C": {"2026-12-31": 11.0 + i * 0.1, "2027-12-31": 10.0 + i * 0.1},
                    "D": {"2026-12-31": 13.0 + i * 0.1, "2027-12-31": 12.0 + i * 0.1},
                },
                old_marginal={"2026-12-31": 11.5, "2027-12-31": 10.5},
            )

        t0 = time.perf_counter()
        result = recalibrate(
            scenario_yaml_path=scenario_path,
            forecasts_dir=forecasts_dir,
            stress_yaml_path=stress_path,
            output_path=output_path,
            strict=False,
        )
        elapsed = time.perf_counter() - t0

        check("10 файлов обработано", len(result.updated_files) >= 10,
              f"updated: {len(result.updated_files)}")
        check(f"время < 30 сек ({elapsed:.3f}s)", elapsed < 30.0, f"{elapsed:.3f}s")
        check("output YAML создан", output_path.exists())


# ---------------------------------------------------------------------------

def _write_scenario_hz(path: Path, weights: dict[str, float],
                       pbh: dict[str, dict[str, float]],
                       dates: tuple[str, ...] = ("2026-12-31", "2027-06-30",
                                                 "2028-06-30")) -> None:
    """Матрица с p_by_horizon в форме живого SSOT 07-01: список
    scenario_triggers сверху + matrix.horizon/horizon_intermediate."""
    triggers = [{"scenario_id": sid, "probability": w,
                 "p_by_horizon": dict(pbh[sid])}
                for sid, w in weights.items()]
    data = {
        "matrix": {"horizon": dates[-1],
                   "horizon_intermediate": list(dates[:-1])},
        "scenario_triggers": triggers,
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False,
                  sort_keys=False)


#: живая форма 07-01: h6 28/12/42/18, h12 15/15/35/35, h24 24/16/36/24
_PBH_LIVE = {
    "A": {"h6": 0.28, "h12": 0.15, "h24": 0.24},
    "B": {"h6": 0.12, "h12": 0.15, "h24": 0.16},
    "C": {"h6": 0.42, "h12": 0.35, "h24": 0.36},
    "D": {"h6": 0.18, "h12": 0.35, "h24": 0.24},
}
_W_SCALAR = {"A": 0.15, "B": 0.15, "C": 0.35, "D": 0.35}


def test_per_horizon_weights_contract() -> None:
    """
    MFC-5 шаг 2 (2026-08-06): прежний полный отказ на p_by_horizon снят.
    Новый контракт: скаляр читается как раньше, load_horizon_weights отдаёт
    {дата: веса} по датам самой матрицы; дефекты формы — явный отказ, а не
    тихая деградация на скаляр.
    """
    print("test_per_horizon_weights_contract")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        # Полная матрица: 3 даты, суммы по каждому горизонту = 1.
        full = tmpdir / "full.yaml"
        _write_scenario_hz(full, _W_SCALAR, _PBH_LIVE)
        check("скаляр читается при живом p_by_horizon (отказ снят)",
              load_weights(full) == _W_SCALAR, str(load_weights(full)))
        hw = load_horizon_weights(full)
        check("load_horizon_weights: 3 даты", hw is not None and len(hw) == 3,
              str(sorted(hw) if hw else hw))
        check("h6 → первая дата (2026-12-31), веса свои",
              hw["2026-12-31"] == {"A": 0.28, "B": 0.12, "C": 0.42, "D": 0.18},
              str(hw.get("2026-12-31")))
        check("h24 → финальная дата (2028-06-30)",
              hw["2028-06-30"] == {"A": 0.24, "B": 0.16, "C": 0.36, "D": 0.24})

        # Скалярная матрица → None (прежний путь бит-в-бит).
        плоская = tmpdir / "plain.yaml"
        _write_scenario(плоская, {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})
        check("матрица без p_by_horizon → None", load_horizon_weights(плоская) is None)

        # Блок у части сценариев → отказ.
        part = tmpdir / "part.yaml"
        pbh_part = {sid: dict(_PBH_LIVE[sid]) for sid in "ABCD"}
        triggers = [{"scenario_id": sid, "probability": _W_SCALAR[sid],
                     **({"p_by_horizon": pbh_part[sid]} if sid in "AB" else {})}
                    for sid in "ABCD"]
        part.write_text(yaml.dump({
            "matrix": {"horizon": "2028-06-30",
                       "horizon_intermediate": ["2026-12-31", "2027-06-30"]},
            "scenario_triggers": triggers}, allow_unicode=True), encoding="utf-8")
        try:
            load_horizon_weights(part)
            ok, detail = False, "частичный блок принят молча"
        except SystemExit as e:
            ok, detail = "части сценариев" in str(e), str(e)[:80]
        check("частичный блок → отказ", ok, detail)

        # Разные наборы ключей → отказ.
        diff = tmpdir / "diff.yaml"
        pbh_diff = {sid: dict(_PBH_LIVE[sid]) for sid in "ABCD"}
        del pbh_diff["D"]["h24"]
        pbh_diff["D"]["h36"] = 0.24
        _write_scenario_hz(diff, _W_SCALAR, pbh_diff)
        try:
            load_horizon_weights(diff)
            ok, detail = False, "разные наборы горизонтов приняты"
        except SystemExit as e:
            ok, detail = "РАЗНЫЕ наборы" in str(e), str(e)[:80]
        check("разные наборы горизонтов → отказ", ok, detail)

        # Сумма ≠ 1 на одном горизонте → WeightValidationError с адресом.
        bad_sum = tmpdir / "badsum.yaml"
        pbh_bad = {sid: dict(_PBH_LIVE[sid]) for sid in "ABCD"}
        pbh_bad["C"]["h12"] = 0.55
        _write_scenario_hz(bad_sum, _W_SCALAR, pbh_bad)
        try:
            load_horizon_weights(bad_sum)
            ok, detail = False, "сумма 1.2 на h12 принята"
        except WeightValidationError as e:
            ok, detail = "h12" in str(e), str(e)[:80]
        check("сумма ≠ 1 на горизонте → отказ с адресом горизонта", ok, detail)

        # Дат матрицы меньше, чем горизонтов, → отказ (порядковое сопоставление).
        nodates = tmpdir / "nodates.yaml"
        nodates.write_text(
            "matrix:\n"
            "  scenario_triggers:\n"
            "    - scenario_id: A\n"
            "      probability: 1.0\n"
            "      p_by_horizon:\n"
            "        h6: 0.45\n"
            "        h24: 0.20\n",
            encoding="utf-8",
        )
        try:
            load_horizon_weights(nodates)
            ok, detail = False, "матрица без дат принята"
        except SystemExit as e:
            ok, detail = "сопоставление" in str(e), str(e)[:80]
        check("нет дат матрицы под горизонты → отказ", ok, detail)


def test_recalibrate_uses_per_horizon_weights() -> None:
    """
    [РАЗЛИЧИТЕЛЬ] Каждая дата Layer 2 пересчитана весами СВОЕГО горизонта.
    Реализация, агрегирующая все даты скаляром, обязана падать: ожидания
    посчитаны в тесте вручную по обеим моделям, и на этих данных они расходятся.
    """
    print("test_recalibrate_uses_per_horizon_weights")
    vals = {"A": 100.0, "B": 90.0, "C": 80.0, "D": 60.0}
    dates = ("2026-12-31", "2027-06-30", "2028-06-30")
    hk_of = {"2026-12-31": "h6", "2027-06-30": "h12", "2028-06-30": "h24"}
    per_date = {dt: sum(_PBH_LIVE[sid][hk_of[dt]] * vals[sid] for sid in "ABCD")
                for dt in dates}
    by_scalar = {dt: sum(_W_SCALAR[sid] * vals[sid] for sid in "ABCD")
                 for dt in dates}
    assert abs(per_date["2026-12-31"] - by_scalar["2026-12-31"]) > 1.0, \
        "фикстура выродилась: горизонтные и скалярные ожидания совпали"

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        sc = tmpdir / "scenario.yaml"
        _write_scenario_hz(sc, _W_SCALAR, _PBH_LIVE)
        fdir = tmpdir / "forecasts"
        fdir.mkdir()
        fc = fdir / "brent.yaml"
        _write_forecast(
            fc,
            {sid: {dt: vals[sid] for dt in dates} for sid in "ABCD"},
            {dt: 85.0 for dt in dates},
        )
        out = tmpdir / "macro-out.yaml"
        result = recalibrate(scenario_yaml_path=sc, forecasts_dir=fdir,
                             stress_yaml_path=None, output_path=out)
        check("файл пересчитан", str(fc) in result.updated_files,
              str(result.updated_files))
        data = yaml.safe_load(fc.read_text(encoding="utf-8"))
        got = {str(k): v["central"] for k, v in
               data["conditional_on_scenarios"]["marginal"]["values"].items()}
        for dt in dates:
            check(f"{dt}: веса своего горизонта ({per_date[dt]:.2f})",
                  abs(got[dt] - per_date[dt]) < 1e-6,
                  f"got {got[dt]}, скалярная модель дала бы {by_scalar[dt]:.2f}")
        # Снапшот горизонтных весов уехал в выходной stress-артефакт.
        out_data = yaml.safe_load(out.read_text(encoding="utf-8"))
        snap = (out_data.get("run_metadata") or {}).get("weights_by_horizon_snapshot")
        check("weights_by_horizon_snapshot записан",
              isinstance(snap, dict) and sorted(snap) == sorted(dates), str(snap))


def test_recalibrate_skips_file_with_foreign_horizon() -> None:
    """
    [РАЗЛИЧИТЕЛЬ] Решение владельца (STOP-D2 п.3): прогноз с горизонтом вне дат
    матрицы (h18-файлы: 2027-12-31) пропускается ЦЕЛИКОМ — громко, в
    skipped_files, файл не переписан даже частично.
    """
    print("test_recalibrate_skips_file_with_foreign_horizon")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        sc = tmpdir / "scenario.yaml"
        _write_scenario_hz(sc, _W_SCALAR, _PBH_LIVE)
        fdir = tmpdir / "forecasts"
        fdir.mkdir()
        h18 = fdir / "cbr-h18.yaml"
        _write_forecast(
            h18,
            {sid: {"2026-12-31": 10.0, "2027-12-31": 8.0} for sid in "ABCD"},
            {"2026-12-31": 10.0, "2027-12-31": 8.0},
        )
        before = h18.read_text(encoding="utf-8")
        result = recalibrate(scenario_yaml_path=sc, forecasts_dir=fdir,
                             stress_yaml_path=None, output_path=None)
        check("h18-файл не в updated_files", str(h18) not in result.updated_files,
              str(result.updated_files))
        check("h18-файл в skipped_files с причиной «вне дат матрицы»",
              any("cbr-h18" in s and "вне дат матрицы" in s
                  for s in result.skipped_files), str(result.skipped_files))
        check("h18-файл не переписан даже частично",
              h18.read_text(encoding="utf-8") == before)
        # 2026-12-31 у файла есть в матрице — но частичный пересчёт запрещён:
        # Layer 2 одного файла не должен жить на двух наборах убеждений.
        data = yaml.safe_load(h18.read_text(encoding="utf-8"))
        got = {str(k): v["central"] for k, v in
               data["conditional_on_scenarios"]["marginal"]["values"].items()}
        check("значения не тронуты", got == {"2026-12-31": 10.0,
                                             "2027-12-31": 8.0}, str(got))


def _write_site(path: Path, matrix: str, weights: dict, ends: dict) -> None:
    import json
    path.write_text(json.dumps({
        "schema": "stress-weights@1", "matrix": matrix, "horizon_ends": ends,
        "weights": weights, "set_at": "2026-11-06T11:13:19+03:00"}), encoding="utf-8")


def test_site_weights_single_source() -> None:
    """
    [РАЗЛИЧИТЕЛЬ] Файл сайта есть → Layer 2 посчитан весами сайта (интерполяция по дням между
    сроками, вне сроков — ближайший срок), h18-файл пересчитан, скаляр = сайт на дату h12.
    Битый файл → отказ; --no-site-weights → веса матрицы; чужой набор сценариев → отказ;
    без файла сайта — h18 пропускается как раньше.
    """
    print("test_site_weights_single_source")
    from datetime import date
    vals = {"A": 100.0, "B": 90.0, "C": 80.0, "D": 60.0}
    ends = {"h6": "2026-12-31", "h12": "2027-06-30", "h24": "2028-06-30"}
    w6 = {"A": 0.4, "B": 0.3, "C": 0.2, "D": 0.1}
    w12 = {"A": 0.1, "B": 0.2, "C": 0.3, "D": 0.4}
    w24 = {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}
    site_w = {"h6": w6, "h12": w12, "h24": w24}
    mid = "2027-03-31"  # между h6 и h12
    f = (date.fromisoformat(mid) - date(2026, 12, 31)).days / (date(2027, 6, 30) - date(2026, 12, 31)).days
    exp_mid = sum((w6[s] + (w12[s] - w6[s]) * f) * vals[s] for s in "ABCD")
    exp_after = sum(w24[s] * vals[s] for s in "ABCD")  # 2027-12-31 между h12 и h24 — для h18 интерполяция
    f18 = (date(2027, 12, 31) - date(2027, 6, 30)).days / (date(2028, 6, 30) - date(2027, 6, 30)).days
    exp_h18 = sum((w12[s] + (w24[s] - w12[s]) * f18) * vals[s] for s in "ABCD")
    exp_held = sum(w24[s] * vals[s] for s in "ABCD")

    def build(tmpdir: Path, with_site: bool):
        sc = tmpdir / "scenario.yaml"
        _write_scenario_hz(sc, _W_SCALAR, _PBH_LIVE)
        fdir = tmpdir / "forecasts"
        fdir.mkdir()
        fa = fdir / "a.yaml"
        _write_forecast(fa, {s: {mid: vals[s], "2029-12-31": vals[s]} for s in "ABCD"},
                        {mid: 85.0, "2029-12-31": 85.0})
        fb = fdir / "h18.yaml"
        _write_forecast(fb, {s: {"2027-12-31": vals[s]} for s in "ABCD"}, {"2027-12-31": 85.0})
        if with_site:
            _write_site(tmpdir / "stress-weights-scenario.json", "scenario", site_w, ends)
        return sc, fdir, fa, fb

    def central(p: Path) -> dict:
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        return {str(k): v["central"] for k, v in d["conditional_on_scenarios"]["marginal"]["values"].items()}

    with tempfile.TemporaryDirectory() as tmp:
        sc, fdir, fa, fb = build(Path(tmp), True)
        out = Path(tmp) / "out.yaml"
        r = recalibrate(scenario_yaml_path=sc, forecasts_dir=fdir, stress_yaml_path=None, output_path=out)
        check("источник весов — сайт", r.weights_source == "site" and r.weights_meta["file"] == "stress-weights-scenario.json")
        ca, cb = central(fa), central(fb)
        check("интерполированная дата — вручную", abs(ca[mid] - exp_mid) < 1e-5, f"{ca[mid]} vs {exp_mid}")
        check("дата после последнего срока — ближайший срок", abs(ca["2029-12-31"] - exp_held) < 1e-5)
        check("h18-файл пересчитан", str(fb) in r.updated_files and abs(cb["2027-12-31"] - exp_h18) < 1e-3, f"{cb} {exp_h18} {r.updated_files} {r.errors}")
        check("скаляр = сайт на дату h12 матрицы",
              all(abs(r.new_weights[s] - w12[s]) < 1e-9 for s in "ABCD"), str(r.new_weights))
        check("мета: интерполированные и удержанные даты",
              mid in r.weights_meta["interpolated"] and "2029-12-31" in r.weights_meta["held"], str(r.weights_meta))
        snap = yaml.safe_load(out.read_text(encoding="utf-8"))["run_metadata"]
        check("в выходе weights_source=site и мета", snap.get("weights_source") == "site"
              and snap["weights_source_meta"]["set_at"].startswith("2026-11-06"))

    with tempfile.TemporaryDirectory() as tmp:
        sc, fdir, fa, fb = build(Path(tmp), True)
        r = recalibrate(scenario_yaml_path=sc, forecasts_dir=fdir, stress_yaml_path=None,
                        output_path=None, use_site_weights=False)
        check("--no-site-weights: веса матрицы, h18 пропущен",
              r.weights_source == "matrix" and any("h18" in s for s in r.skipped_files))

    with tempfile.TemporaryDirectory() as tmp:
        sc, fdir, fa, fb = build(Path(tmp), False)
        r = recalibrate(scenario_yaml_path=sc, forecasts_dir=fdir, stress_yaml_path=None, output_path=None)
        check("без файла сайта: матрица, h18 пропущен, как раньше",
              r.weights_source == "matrix" and any("h18" in s and "вне дат матрицы" in s for s in r.skipped_files))

    with tempfile.TemporaryDirectory() as tmp:
        sc, fdir, fa, fb = build(Path(tmp), True)
        (Path(tmp) / "stress-weights-scenario.json").write_text('{"schema": "x"}', encoding="utf-8")
        try:
            recalibrate(scenario_yaml_path=sc, forecasts_dir=fdir, stress_yaml_path=None, output_path=None)
            ok = False
        except _rc.SiteWeightsRefused:
            ok = True
        check("битый файл сайта → отказ, не откат на матрицу", ok)
        _write_site(Path(tmp) / "stress-weights-scenario.json", "scenario",
                    {k: {"A": 0.5, "B": 0.5} for k in site_w}, ends)
        try:
            recalibrate(scenario_yaml_path=sc, forecasts_dir=fdir, stress_yaml_path=None, output_path=None)
            ok = False
        except _rc.SiteWeightsRefused as e:
            ok = "не совпадают" in str(e)
        check("другой набор сценариев → отказ", ok)


# ---------------------------------------------------------------------------
def test_reads_live_ssot_matrix() -> None:
    """
    MFC-5 [РАЗЛИЧИТЕЛЬ]: парсер обязан читать РЕАЛЬНЫЙ файл SSOT.

    До 2026-08-05 `load_weights` возвращала `{}` на всех шести живых матрицах —
    построчный regex ждал mapping-форму, а веса лежат списком. Дефект прятала
    фикстура, писавшая третью форму, которой нет ни в спеке, ни в природе:
    тесты гоняли парсер по входу, который он же и определял.

    Без Claude-Memory — пропуск, но синтетическая проверка обеих форм записи
    блока (верхний уровень и `matrix`) идёт всегда.
    """
    print("test_reads_live_ssot_matrix")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "sc.yaml"
        _write_scenario(p, {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})
        check("список на верхнем уровне (форма живых файлов)",
              load_weights(p) == {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})
        _write_scenario(p, {"A": 0.4, "B": 0.3, "C": 0.2, "D": 0.1}, under_matrix=True)
        check("список под `matrix` (форма спеки §1.1)",
              load_weights(p) == {"A": 0.4, "B": 0.3, "C": 0.2, "D": 0.1})

        # Тихое `{}` — тот самый дефект; теперь отказ с адресом проблемы.
        p.write_text("matrix:\n  axes: []\n", encoding="utf-8")
        try:
            load_weights(p)
            ok, detail = False, "вернул значение вместо отказа"
        except SystemExit as e:
            ok, detail = "scenario_triggers" in str(e), str(e)[:70]
        check("блока нет → отказ, а не пустой словарь", ok, detail)

        # Mapping-форма блока: в спеке её нет и в живых файлах тоже. Молча
        # вернуть {} нельзя — это ровно чинимый дефект.
        p.write_text("scenario_triggers:\n  A:\n    probability: 0.25\n", encoding="utf-8")
        try:
            load_weights(p)
            ok, detail = False, "принял недокументированную форму молча"
        except SystemExit as e:
            ok, detail = "список" in str(e), str(e)[:70]
        check("mapping вместо списка → отказ с указанием ожидаемой формы", ok, detail)

    live_dir = (Path.home() / "Library/CloudStorage/SynologyDrive-home"
                / "Claude-Memory/scenarios")
    files = sorted(live_dir.glob("*.yaml")) if live_dir.exists() else []
    if not files:
        print("  [SKIP] живые матрицы недоступны (нет Claude-Memory)")
        return

    # Проверяются ВСЕ живые матрицы, и ожидаемый исход зависит от их содержимого,
    # а не зашит константой. Первая версия теста ждала от конкретного файла
    # {A..D: 0.25} и сломалась в тот же день, когда владелец записал туда веса по
    # горизонтам. С MFC-5 шага 2 (2026-08-06) горизонтная матрица обязана
    # читаться ОБОИМИ путями: скаляр через load_weights + {дата: веса} через
    # load_horizon_weights с суммой 1 на каждой дате.
    import yaml as _yaml
    per_horizon, plain, bad = [], [], []
    for f in files:
        doc = _yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        trig = doc.get("scenario_triggers") or (doc.get("matrix") or {}).get("scenario_triggers") or []
        has_pbh = any(isinstance(t, dict) and t.get("p_by_horizon") for t in trig)
        try:
            got = load_weights(f)
        except SystemExit as e:
            bad.append(f"{f.name}: отказ load_weights: {str(e)[:60]}")
            continue
        if sorted(got) != ["A", "B", "C", "D"]:
            bad.append(f"{f.name}: {got}")
            continue
        try:
            validate_weights(got)
        except WeightValidationError as e:
            bad.append(f"{f.name}: {str(e)[:60]}")
            continue
        if has_pbh:
            try:
                hw = load_horizon_weights(f)
            except (SystemExit, WeightValidationError) as e:
                bad.append(f"{f.name}: горизонтные веса не прочитались: {str(e)[:60]}")
                continue
            if hw and all(sorted(w) == ["A", "B", "C", "D"] for w in hw.values()):
                per_horizon.append(f.name)
            else:
                bad.append(f"{f.name}: неполные горизонтные веса: {hw}")
        else:
            plain.append(f.name)
    check(f"все {len(files)} живых матриц обработаны по контракту "
          f"(скалярных {len(plain)}, горизонтных {len(per_horizon)})", not bad, str(bad))
    check("хотя бы одна живая матрица реально прочитана", bool(plain) or bool(per_horizon))


# ---------------------------------------------------------------------------
def test_skips_foreign_matrix() -> None:
    """
    [РАЗЛИЧИТЕЛЬ] Спека §1.3: пересчитываются ТОЛЬКО прогнозы с
    `source_matrix == эта матрица`.

    Всплыло сразу, как парсер весов начал работать: в живой библиотеке лежат
    прогнозы, привязанные к матрицам 05-04, 06-10 и 07-01 одновременно, и прогон
    с матрицей 07-01 переписывал Layer 2 у всех тридцати одного. Раньше не
    проявлялось только потому, что режим падал на пустых весах раньше.

    Реализация без фильтра пересчитает ОБА файла и упадёт здесь.
    """
    print("test_skips_foreign_matrix")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        scenario_path = tmpdir / "scenario.yaml"
        _write_scenario(scenario_path, {"A": 0.40, "B": 0.30, "C": 0.20, "D": 0.10})
        fdir = tmpdir / "forecasts"
        fdir.mkdir()
        by_sc = {"A": {"2026-12-31": 10.0}, "B": {"2026-12-31": 11.0},
                 "C": {"2026-12-31": 12.0}, "D": {"2026-12-31": 13.0}}
        _write_forecast(fdir / "mine.yaml", by_sc, {"2026-12-31": 11.5})
        _write_forecast(fdir / "foreign.yaml", by_sc, {"2026-12-31": 11.5},
                        source_matrix="scenarios/scenario-other-2026-01-01.yaml")

        result = recalibrate(scenario_yaml_path=scenario_path, forecasts_dir=fdir,
                             strict=False)
        touched = {Path(p).name for p in result.updated_files}
        check("свой прогноз пересчитан", "mine.yaml" in touched, str(touched))
        check("чужая матрица не тронута", "foreign.yaml" not in touched, str(touched))
        check("пропуск назван вслух, а не проглочен",
              any("foreign.yaml" in s for s in result.skipped_files),
              str(result.skipped_files))

        foreign = yaml.safe_load((fdir / "foreign.yaml").read_text(encoding="utf-8"))
        central = foreign["conditional_on_scenarios"]["marginal"]["values"]["2026-12-31"]["central"]
        check("значение чужого прогноза не изменилось", central == 11.5, str(central))


# ---------------------------------------------------------------------------
def test_modal_tie_refuses_to_guess() -> None:
    """
    [РАЗЛИЧИТЕЛЬ] `method: nonlinear|modal` при РАВНЫХ весах не имеет
    однозначного модального сценария, и `max(weights)` вернул бы первый ключ
    словаря — значение прогноза определял бы порядок ключей в YAML.

    Не гипотетика: пять живых прогнозов помечены `method: nonlinear`, при этом
    несут `modal_scenario_id: none` и `aggregation_formula: weighted_mean (D1
    equal weights 0.25)`, а хранимые значения — честное равновзвешенное среднее.
    Прогон «взял бы модального» и переписал бы, например, cnyrub 2026-12-31 с
    13.58 на 15.30 (значение сценария A) на всех трёх горизонтах.

    Явный `modal_scenario_id` уважается — тогда сценарий назван, а не угадан.
    """
    print("test_modal_tie_refuses_to_guess")
    equal = {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}
    by_sc = {"A": {"values": {"2026-12-31": {"central": 15.3}}},
             "B": {"values": {"2026-12-31": {"central": 12.9}}},
             "C": {"values": {"2026-12-31": {"central": 13.4}}},
             "D": {"values": {"2026-12-31": {"central": 12.8}}}}
    from recalibrate import aggregate_marginal_simple as agg
    check("равные веса + nonlinear → отказ, а не первый ключ",
          agg(by_sc, equal, "2026-12-31", "nonlinear") is None)
    check("явный modal_scenario_id → берётся он",
          agg(by_sc, equal, "2026-12-31", "nonlinear", modal_scenario_id="C") == 13.4)
    uneq = {"A": 0.4, "B": 0.3, "C": 0.2, "D": 0.1}
    check("однозначный лидер по весам → он и берётся",
          agg(by_sc, uneq, "2026-12-31", "modal") == 15.3)
    check("linear не затронут", abs(agg(by_sc, equal, "2026-12-31", "linear")
                                    - (15.3 + 12.9 + 13.4 + 12.8) / 4) < 1e-9)

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        scenario_path = tmpdir / "scenario.yaml"
        _write_scenario(scenario_path, equal)
        fdir = tmpdir / "forecasts"
        fdir.mkdir()
        vals = {"A": {"2026-12-31": 15.3}, "B": {"2026-12-31": 12.9},
                "C": {"2026-12-31": 13.4}, "D": {"2026-12-31": 12.8}}
        _write_forecast(fdir / "nl.yaml", vals, {"2026-12-31": 13.6}, method="nonlinear")
        result = recalibrate(scenario_yaml_path=scenario_path, forecasts_dir=fdir,
                             strict=False)
        got = yaml.safe_load((fdir / "nl.yaml").read_text(encoding="utf-8"))
        central = got["conditional_on_scenarios"]["marginal"]["values"]["2026-12-31"]["central"]
        check("хранимое среднее не подменено значением сценария A",
              central == 13.6, str(central))
        check("непересчитанный горизонт назван в skipped_files",
              any("nl.yaml" in s for s in result.skipped_files),
              str(result.skipped_files))


# ---------------------------------------------------------------------------
def test_noop_run_does_not_rewrite_file() -> None:
    """
    [РАЗЛИЧИТЕЛЬ] Прогон, которому нечего пересчитывать, не трогает файл.

    `yaml.dump` нормализует форматирование и уносит комментарии: безусловная
    перезапись переформатировала бы всю библиотеку на каждом запуске. На живых
    артефактах 08-05 так переписывались бы 15 файлов из 15 при нуле изменённых
    чисел.

    Сравнение обязано быть ЧИСЛОВЫМ: `round()` даёт float, и хранившееся
    `central: 11` превращается в `11.0`. Текстовое сравнение сочло бы это
    изменением — фикстура держит целое число ровно ради этой ловушки.
    """
    print("test_noop_run_does_not_rewrite_file")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        scenario_path = tmpdir / "scenario.yaml"
        _write_scenario(scenario_path, {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})
        fdir = tmpdir / "forecasts"
        fdir.mkdir()
        # Среднее (10+11+12+13)/4 = 11.5 → хранимое уже равно пересчитанному.
        by_sc = {"A": {"2026-12-31": 10.0}, "B": {"2026-12-31": 11.0},
                 "C": {"2026-12-31": 12.0}, "D": {"2026-12-31": 13.0}}
        f = fdir / "same.yaml"
        _write_forecast(f, by_sc, {"2026-12-31": 11.5})
        # Второй файл: целое хранимое значение при равном ему пересчёте.
        by_int = {sid: {"2026-12-31": 11.0} for sid in ("A", "B", "C", "D")}
        g = fdir / "int.yaml"
        _write_forecast(g, by_int, {"2026-12-31": 11})

        before_f, before_g = f.read_bytes(), g.read_bytes()
        result = recalibrate(scenario_yaml_path=scenario_path, forecasts_dir=fdir,
                             strict=False)
        check("нечего менять → updated_files пуст", result.updated_files == [],
              str(result.updated_files))
        check("файл не переписан байт-в-байт", f.read_bytes() == before_f)
        check("int 11 vs float 11.0 — не изменение", g.read_bytes() == before_g)

        # А когда есть что менять — файл переписывается.
        _write_forecast(f, by_sc, {"2026-12-31": 99.0})
        result2 = recalibrate(scenario_yaml_path=scenario_path, forecasts_dir=fdir,
                              strict=False)
        check("реальное изменение → файл в updated_files",
              [Path(p).name for p in result2.updated_files] == ["same.yaml"],
              str(result2.updated_files))


# ---------------------------------------------------------------------------
def test_previous_weights_from_live_artifact_shape() -> None:
    """
    [РАЗЛИЧИТЕЛЬ] Прежние веса берутся и из `scenarios.*.probability`, а не только
    из `run_metadata.weights_snapshot`.

    `weights_snapshot` пишет сам этот скрипт, поэтому в живых
    `macro-chain/macro-scenarios-*.yaml` его нет НИ В ОДНОМ (их собирает LLM по
    шаблону цепочки): `old_weights` были пусты всегда, `old_modal` — None, и
    диагностика «modal сменился» не срабатывала никогда. Веса при этом лежат в
    артефакте рядом.

    Реализация, читающая только weights_snapshot, падает на первой проверке.
    """
    print("test_previous_weights_from_live_artifact_shape")
    from recalibrate import load_previous_weights
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        live_like = tmpdir / "macro-scenarios.yaml"
        live_like.write_text(yaml.dump({
            "type": "macro-scenarios", "schema_version": 2,
            "scenarios": {"A": {"probability": 0.10}, "B": {"probability": 0.20},
                          "C": {"probability": 0.17}, "D": {"probability": 0.53}},
        }, allow_unicode=True), encoding="utf-8")
        w = load_previous_weights(live_like)
        check("веса подняты из scenarios.*.probability",
              w == {"A": 0.10, "B": 0.20, "C": 0.17, "D": 0.53}, str(w))
        check("modal восстановлен", modal_scenario(w) == "D")

        # weights_snapshot приоритетнее, когда он есть.
        both = tmpdir / "both.yaml"
        both.write_text(yaml.dump({
            "scenarios": {"A": {"probability": 0.9}, "B": {"probability": 0.1}},
            "run_metadata": {"weights_snapshot": {"A": 0.1, "B": 0.9}},
        }, allow_unicode=True), encoding="utf-8")
        check("weights_snapshot приоритетнее",
              load_previous_weights(both) == {"A": 0.1, "B": 0.9})

        # Легаси-написание Sc-A (D5) нормализуется — иначе modal_changed
        # срабатывал бы ложно против старых артефактов.
        legacy = tmpdir / "legacy.yaml"
        legacy.write_text(yaml.dump({"scenarios": {
            f"Sc-{s}": {"probability": p} for s, p in
            (("A", 0.25), ("B", 0.25), ("C", 0.25), ("D", 0.25))}},
            allow_unicode=True), encoding="utf-8")
        check("Sc-A → A (D5)", sorted(load_previous_weights(legacy)) == list("ABCD"),
              str(load_previous_weights(legacy)))

        # Мультидокументный файл: раньше safe_load падал ComposerError.
        multi = tmpdir / "multi.yaml"
        multi.write_text("---\nscenarios:\n  A: {probability: 0.4}\n"
                         "  B: {probability: 0.6}\n---\nsome: other\n",
                         encoding="utf-8")
        try:
            got = load_previous_weights(multi)
            ok, detail = got == {"A": 0.4, "B": 0.6}, str(got)
        except Exception as e:                                     # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {e}"
        check("мультидокумент не роняет прогон", ok, detail)

        # Битый YAML — {}, а не трейсбек.
        broken = tmpdir / "broken.yaml"
        broken.write_text("a: [1, 2\n", encoding="utf-8")
        try:
            ok, detail = load_previous_weights(broken) == {}, ""
        except Exception as e:                                     # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {e}"
        check("битый YAML → {}, без падения", ok, detail)

        check("нет файла → {}", load_previous_weights(tmpdir / "нет.yaml") == {})

    # Живые артефакты: веса восстанавливаются у ВСЕХ, кто их несёт, и ни один
    # файл не роняет прогон.
    #
    # Критерий СТРУКТУРНЫЙ, не счётный. Раньше здесь стоял допуск
    # `len(with_weights) >= len(files) - 2`, откалиброванный на «ровно два файла
    # с другой структурой» (05-04: bundles; 08-06: factors). Допуск протух, как
    # только цепочка выпустила третий такой артефакт (08-15, та же factors-форма
    # mode PARTIAL): тест упал, хотя ни данные, ни код не сломаны — веса у этой
    # формы законно живут в macro-marginal.scenario_weights_by_horizon, а не в
    # scenarios-блоке. Счётный допуск ломается при каждом росте библиотеки и не
    # отличает «источник отсутствует по форме» от «источник есть, но не прочитан»,
    # то есть от настоящего дефекта. Ниже сверяются два МНОЖЕСТВА: кто несёт
    # источник весов по структуре и у кого веса реально восстановились.
    live_dir = (Path.home() / "Library/CloudStorage/SynologyDrive-home"
                / "Claude-Memory/macro-chain")
    files = sorted(live_dir.glob("macro-scenarios-*.yaml")) if live_dir.exists() else []
    if not files:
        print("  [SKIP] живые macro-scenarios недоступны")
        return

    def _carries_weight_source(path: Path) -> bool:
        """Есть ли в файле хоть один из двух источников, которые читает загрузчик."""
        try:
            with open(path, "r", encoding="utf-8") as fh:
                docs = [d for d in yaml.safe_load_all(fh) if isinstance(d, dict)]
        except yaml.YAMLError:
            return False
        data = docs[0] if docs else {}
        if (data.get("run_metadata") or {}).get("weights_snapshot"):
            return True
        for blk in (data.get("scenarios") or {}).values():
            if isinstance(blk, dict) and isinstance(
                    blk.get("probability", blk.get("p")), (int, float)):
                return True
        return False

    got, structural = {}, {}
    for f in files:
        structural[f.name] = _carries_weight_source(f)
        try:
            got[f.name] = sorted(load_previous_weights(f))
        except Exception as e:                                     # noqa: BLE001
            got[f.name] = f"ПАДЕНИЕ {type(e).__name__}"
    crashed = [k for k, v in got.items() if isinstance(v, str)]
    check("ни один живой артефакт не роняет прогон", not crashed, str(crashed))

    expected = {k for k, v in structural.items() if v}
    actual = {k for k, v in got.items() if isinstance(v, list) and v}
    missed = sorted(expected - actual)      # источник есть, а весов нет → дефект загрузчика
    extra = sorted(actual - expected)       # весы есть, а источника нет → дефект детектора
    check(f"веса прочитаны у всех {len(expected)} несущих источник "
          f"(без источника по форме: {len(files) - len(expected)})",
          not missed and not extra,
          f"не прочитаны: {missed}; лишние: {extra}; сводка: {got}")


def test_superseded_forecasts_not_touched() -> None:
    """
    [РАЗЛИЧИТЕЛЬ] Архив не пересчитывается: `status != active` → файл не тронут.

    Найдено независимым аудитом 2026-08-05. Фильтр по `source_matrix` этот класс
    НЕ отсеивает: superseded-прогноз ссылается на ТУ ЖЕ матрицу, что и его
    активный преемник — в этом и состоит механизм supersession. В живой
    библиотеке 24 из 31 прогноза superseded, а на матрицу 07-01 ссылаются 15
    файлов, из которых 8 архивных; прогон переписал бы 2 архивных из 4
    обновлённых.

    Почему это дорого: retrospective-forecast-audit и калибровочные milestones
    читают superseded как неизменный исторический снимок. Перезапись превращает
    «что мы думали в июле» в «что мы думаем сейчас», и ошибка прогноза считается
    по подменённым числам — то есть калибровка сама себе подгоняет ответ.
    """
    print("test_superseded_forecasts_not_touched")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        scenario_path = tmpdir / "scenario.yaml"
        _write_scenario(scenario_path, {"A": 0.40, "B": 0.30, "C": 0.20, "D": 0.10})
        fdir = tmpdir / "forecasts"; fdir.mkdir()
        by_sc = {"A": {"2026-12-31": 10.0}, "B": {"2026-12-31": 11.0},
                 "C": {"2026-12-31": 12.0}, "D": {"2026-12-31": 13.0}}
        # Оба файла — ОДНА матрица, различаются только статусом.
        for name, status in (("live.yaml", "active"), ("archived.yaml", "superseded")):
            _write_forecast(fdir / name, by_sc, {"2026-12-31": 11.5})
            d = yaml.safe_load((fdir / name).read_text(encoding="utf-8"))
            d["status"] = status
            (fdir / name).write_text(yaml.dump(d, allow_unicode=True, sort_keys=False),
                                     encoding="utf-8")
        before = (fdir / "archived.yaml").read_bytes()

        result = recalibrate(scenario_yaml_path=scenario_path, forecasts_dir=fdir,
                             strict=False)
        touched = {Path(x).name for x in result.updated_files}
        check("active пересчитан", "live.yaml" in touched, str(touched))
        check("superseded не тронут", "archived.yaml" not in touched, str(touched))
        check("архив байт-в-байт прежний",
              (fdir / "archived.yaml").read_bytes() == before)
        check("пропуск назван причиной status",
              any("archived.yaml" in s and "status=superseded" in s
                  for s in result.skipped_files), str(result.skipped_files))

        # Файл без status тоже не трогаем: неизвестное состояние — не повод писать.
        _write_forecast(fdir / "nostatus.yaml", by_sc, {"2026-12-31": 11.5})
        d = yaml.safe_load((fdir / "nostatus.yaml").read_text(encoding="utf-8"))
        d.pop("status", None)
        (fdir / "nostatus.yaml").write_text(yaml.dump(d, allow_unicode=True, sort_keys=False),
                                            encoding="utf-8")
        r2 = recalibrate(scenario_yaml_path=scenario_path, forecasts_dir=fdir, strict=False)
        check("без status → пропуск, а не запись",
              "nostatus.yaml" not in {Path(x).name for x in r2.updated_files}
              and any("nostatus.yaml" in s for s in r2.skipped_files),
              str(r2.skipped_files))


def test_nan_weight_refused() -> None:
    """
    [РАЗЛИЧИТЕЛЬ] NaN в весах отвергается ЯВНО.

    `nan > 0.001` в Python — False, поэтому проверка суммы NaN пропускала.
    Достижимым это стало после перехода на yaml.safe_load: PyYAML разбирает
    `.nan` во float('nan'), прежний построчный regex требовал цифру.

    Последствия были бы тихими: `.nan` уезжает в Layer 2 marginal НА ДИСК, а
    modal_scenario() возвращает первый ключ словаря (сравнения с NaN — False),
    то есть «модальный сценарий» определялся бы порядком ключей.
    """
    print("test_nan_weight_refused")
    for bad in (float("nan"), float("inf")):
        w = {"A": bad, "B": 0.3, "C": 0.3, "D": 0.4}
        try:
            validate_weights(w)
            check(f"{bad} отвергнут", False, "принят молча")
        except WeightValidationError as e:
            check(f"{bad} отвергнут", "NaN" in str(e) or "inf" in str(e), str(e)[:70])
    check("нормальные веса по-прежнему проходят",
          validate_weights({"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}) is None)

    # Через полный путь: .nan в SSOT не должен доехать до записи в файл.
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "sc.yaml"
        p.write_text("scenario_triggers:\n"
                     "  - {scenario_id: A, probability: .nan}\n"
                     "  - {scenario_id: B, probability: 0.3}\n"
                     "  - {scenario_id: C, probability: 0.3}\n"
                     "  - {scenario_id: D, probability: 0.4}\n", encoding="utf-8")
        w = load_weights(p)
        check("PyYAML действительно даёт NaN (иначе тест вырожден)",
              w["A"] != w["A"], str(w))
        try:
            recalibrate(scenario_yaml_path=p, forecasts_dir=None, strict=False)
            check("recalibrate останавливается на NaN", False, "прошёл насквозь")
        except WeightValidationError:
            check("recalibrate останавливается на NaN", True)


# Main runner
# ---------------------------------------------------------------------------

def test_rewrite_keeps_forecast_files() -> None:
    """Шаг 14 (schema.md §4.6): перезапись макросценариев весами не теряет ссылку forecast_files и schema_version."""
    print("test_rewrite_keeps_forecast_files")
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        sc = tmpdir / "scenario.yaml"
        _write_scenario(sc, {"A": 0.40, "B": 0.30, "C": 0.20, "D": 0.10})
        prev = tmpdir / "macro-scenarios-2026-10-04.yaml"
        ff = {"brent_price": "brent-price-2026-09-17", "cbr_rate": "cbr-rate-2026-2027-2026-09-17"}
        prev.write_text(yaml.safe_dump({"schema_version": 2, "type": "macro-scenarios", "forecast_files": ff,
                                        "factors": {"brent_price": {}, "cbr_rate": {}}},
                                       allow_unicode=True, sort_keys=False), encoding="utf-8")
        out = tmpdir / "macro-out.yaml"
        recalibrate(scenario_yaml_path=sc, forecasts_dir=None, stress_yaml_path=prev, output_path=out)
        data = yaml.safe_load(out.read_text(encoding="utf-8"))
        check("forecast_files сохранён при перезаписи", data.get("forecast_files") == ff, str(data.get("forecast_files")))
        check("schema_version сохранён", data.get("schema_version") == 2)
        keys = list(data)
        check("forecast_files остаётся перед factors", keys.index("forecast_files") < keys.index("factors"))


_COMMENTED_FORECAST = """# Шапка файла: комментарий отдельной строкой
schema_version: 1
type: forecast-events
status: active   # конец строки: статус
forecast:
  date: '2026-05-04'
  central_estimate: "100.0"
  confidence: 0.60
  note: >-
    длинная строка,
    перенесённая складкой
  tags:
    - alpha
    - beta
conditional_on_scenarios:
  source_matrix: scenarios/scenario.yaml
  by_scenario:
    A:
      label: Scenario A
      probability: 0.25
      provenance: direct
      values:
        h12: {central: 100.0}
    B:
      label: Scenario B
      probability: 0.25
      provenance: direct
      values:
        h12: {central: 200.0}
    C:
      label: Scenario C
      probability: 0.25
      provenance: direct
      values:
        h12: {central: 300.0}
    D:
      label: Scenario D
      probability: 0.25
      provenance: direct
      values:
        h12: {central: 400.0}
  marginal:
    method: linear   # метод: линейный
    modal_scenario_id: none
    values:
      h12:
        central: 150.0
"""


def _setup_commented(tmpdir: Path):
    sc = tmpdir / "scenario.yaml"
    _write_scenario(sc, {"A": 0.40, "B": 0.30, "C": 0.20, "D": 0.10})
    fd = tmpdir / "forecasts"
    fd.mkdir()
    fp = fd / "f.yaml"
    fp.write_text(_COMMENTED_FORECAST, encoding="utf-8")
    return sc, fd, fp


def test_preserving_write_keeps_format() -> None:
    print("test_preserving_write_keeps_format")
    if _rc._RuamelYAML is None:
        print("  SKIP: ruamel.yaml недоступен")
        return
    with tempfile.TemporaryDirectory() as tmp:
        sc, fd, fp = _setup_commented(Path(tmp))
        before = fp.read_text(encoding="utf-8").splitlines()
        res = recalibrate(scenario_yaml_path=sc, forecasts_dir=fd)
        after = fp.read_text(encoding="utf-8").splitlines()
        check("файл пересчитан", str(fp) in res.updated_files and not res.errors, str(res.errors))
        check("предупреждения нет", res.warnings == [])
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        check("число строк то же", len(before) == len(after))
        check("меняется только строка marginal central",
              len(changed) == 1 and "central" in changed[0][1], str(changed))
        text = "\n".join(after)
        check("комментарии на месте", "# Шапка файла" in text and "# конец строки: статус" in text
              and "# метод: линейный" in text)
        check("0.60 сохранено", "confidence: 0.60" in text)
        check("кавычки сохранены", "date: '2026-05-04'" in text and 'central_estimate: "100.0"' in text)
        check("складка >- сохранена", "note: >-" in text and "    длинная строка," in text)
        check("список с отступом сохранён", "    - alpha" in text)
        new = yaml.safe_load(text)
        check("marginal = 0.7*100+0.3*200",
              abs(new["conditional_on_scenarios"]["marginal"]["values"]["h12"]["central"] - 0.4*100-0.3*200-0.2*300-0.1*400) < 1e-9)


def test_preserving_roundtrip_equals_new_data() -> None:
    print("test_preserving_roundtrip_equals_new_data")
    if _rc._RuamelYAML is None:
        print("  SKIP: ruamel.yaml недоступен")
        return
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "x.yaml"
        p.write_text("# c\na: 1\nb:\n  - 1\n  - 2\nc:\n  d: 0.50   # x\n  e: gone\n", encoding="utf-8")
        old = yaml.safe_load(p.read_text(encoding="utf-8"))
        new = {"a": 1, "b": [1, 2, 3], "c": {"d": 0.5, "f": "added"}, "g": [{"k": 1}]}
        write_yaml_preserving(p, old, new)
        text = p.read_text(encoding="utf-8")
        check("перечитанное == new_data", yaml.safe_load(text) == new)
        check("добавлен ключ", "f: added" in text)
        check("удалён ключ", "e: gone" not in text)
        check("список изменённой длины", yaml.safe_load(text)["b"] == [1, 2, 3])
        check("0.50 и комментарии у неизменного", "d: 0.50   # x" in text and "# c" in text)


def test_no_ruamel_fallback() -> None:
    print("test_no_ruamel_fallback")
    saved = _rc._RuamelYAML
    _rc._RuamelYAML = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            sc, fd, fp = _setup_commented(Path(tmp))
            old = yaml.safe_load(fp.read_text(encoding="utf-8"))
            res = recalibrate(scenario_yaml_path=sc, forecasts_dir=fd)
            expected = yaml.dump(
                _rc.recalculate_layer2(old, {"A": 0.40, "B": 0.30, "C": 0.20, "D": 0.10}, str(fp))[1],
                allow_unicode=True, default_flow_style=False, sort_keys=False)
            check("результат == прежний yaml.dump", fp.read_text(encoding="utf-8") == expected)
            check("предупреждение в warnings", _rc.NO_RUAMEL_WARNING in res.warnings, str(res.warnings))
    finally:
        _rc._RuamelYAML = saved


def test_preserving_write_tiny_and_negative_numbers() -> None:
    """Число с экспонентой без точки (`1e-05`) PyYAML читает строкой — токен
    пишется как `1.0e-05`; отрицательное число и число рядом с комментарием."""
    print("test_preserving_write_tiny_and_negative_numbers")
    if _rc._RuamelYAML is None:
        print("  SKIP: ruamel.yaml недоступен")
        return
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "x.yaml"
        src = "# шапка\na: 0.60   # комментарий\nb: 15\nc: \"строка\"\nd: -3.5\n"
        p.write_text(src, encoding="utf-8")
        old = yaml.safe_load(src)
        new = dict(old, a=1e-05, b=-2.25, d=1e+16)
        full = write_yaml_preserving(p, old, new)
        text = p.read_text(encoding="utf-8")
        check("точечная правка, не полная перезапись", full is False)
        check("перечитанное == new_data (числа, не строки)", yaml.safe_load(text) == new)
        check("комментарии и строка в кавычках на месте",
              "# шапка" in text and "# комментарий" in text and 'c: "строка"' in text)
        check("строк в файле столько же", text.count("\n") == src.count("\n"))


def test_selfcheck_restores_original() -> None:
    print("test_selfcheck_restores_original")
    with tempfile.TemporaryDirectory() as tmp:
        sc, fd, fp = _setup_commented(Path(tmp))
        orig = fp.read_text(encoding="utf-8")
        saved = _rc._render_preserving
        _rc._render_preserving = lambda path, old, new: "a: 1\n"
        try:
            res = recalibrate(scenario_yaml_path=sc, forecasts_dir=fd)
        finally:
            _rc._render_preserving = saved
        check("исходный файл цел", fp.read_text(encoding="utf-8") == orig)
        check("ошибка в errors", len(res.errors) == 1 and "самопроверка" in res.errors[0], str(res.errors))
        check("файл не в updated_files", str(fp) not in res.updated_files)
        check("нет временных файлов", [x.name for x in fd.iterdir()] == ["f.yaml"])


def main() -> None:
    print("=" * 60)
    print("test_recalibrate.py")
    print("=" * 60)

    test_valid_weight_sum()
    test_modal_scenario_change()
    test_stale_marginal_soft()
    test_strict_refuses_stale()
    test_time_guard()
    test_per_horizon_weights_contract()
    test_recalibrate_uses_per_horizon_weights()
    test_recalibrate_skips_file_with_foreign_horizon()
    test_site_weights_single_source()
    test_reads_live_ssot_matrix()
    test_skips_foreign_matrix()
    test_modal_tie_refuses_to_guess()
    test_noop_run_does_not_rewrite_file()
    test_previous_weights_from_live_artifact_shape()
    test_superseded_forecasts_not_touched()
    test_nan_weight_refused()
    test_rewrite_keeps_forecast_files()
    test_preserving_write_keeps_format()
    test_preserving_roundtrip_equals_new_data()
    test_no_ruamel_fallback()
    test_preserving_write_tiny_and_negative_numbers()
    test_selfcheck_restores_original()

    print("=" * 60)
    print(f"Итого: {checks_run} проверок, {checks_failed} провалено")
    if checks_failed:
        print("СТАТУС: FAIL")
        sys.exit(1)
    else:
        print("СТАТУС: OK")


if __name__ == "__main__":
    main()
