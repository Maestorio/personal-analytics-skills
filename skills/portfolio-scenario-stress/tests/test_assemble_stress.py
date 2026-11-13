#!/usr/bin/env python3
"""Тесты для skills/portfolio-scenario-stress/scripts/assemble_stress.py.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 \
        skills/portfolio-scenario-stress/tests/test_assemble_stress.py
Зависимости: stdlib + pyyaml.

Фикстура: стаб строит НАСТОЯЩИЙ build_stress_stub.py (2 сценария × 2 горизонта,
2 позиции); агрегаты считает настоящий compute_portfolio_aggregates.compute();
per_position, bond_carry и факторы по горизонтам — словари-фикстуры в тесте
(compute_per_position / compute_bond_carry требуют priors и снапшот с
облигациями — для проверки склейки это лишний груз).
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
SCRIPTS = REPO / "skills/portfolio-scenario-stress/scripts"
ASM = SCRIPTS / "assemble_stress.py"
STUB = SCRIPTS / "build_stress_stub.py"
sys.path.insert(0, str(SCRIPTS))

import compute_portfolio_aggregates as cpa  # noqa: E402


def check(label: str, cond: bool, detail: str = "") -> bool:
    if cond:
        print(f"  ✓ {label}")
        return True
    print(f"  ✗ {label}{(' — ' + detail) if detail else ''}")
    return False


SNAPSHOT = {
    "schema_version": "2.0",
    "as_of_date": "2026-05-12",
    "holdings": [
        {"ticker": "TICK1", "name": "Один", "asset_type": "stock", "value_rub": 600000.0, "is_blocked": False},
        {"ticker": "TICK2", "name": "Два", "asset_type": "stock", "value_rub": 400000.0, "is_blocked": False},
    ],
    "cash": {"total_rub": 0.0},
}

SSOT = """\
scenario_triggers:
  - scenario_id: A
    label: "Сценарий А"
    probability: 0.5
  - scenario_id: B
    label: "Сценарий Б"
    probability: 0.5
"""

MACRO = """\
baseline_spot:
  brent_usd: 70
  usdrub: 80
  cnyrub: 11
  cbr_rate_pct: 14
  xauusd_usd: 3000
scenarios:
  A: {horizon_2027_12_31: {brent_usd: 70}}
  B: {horizon_2027_12_31: {brent_usd: 60}}
"""

PER_POSITION = {
    "per_position": {
        "TICK1": {"weight_pct": 60, "by_horizon": {
            "h6": {"delta_pct_by_scenario": {"A": -10.0, "B": 8.0}},
            "h12": {"delta_pct_by_scenario": {"A": -20.0, "B": 15.0}}}},
        "TICK2": {"weight_pct": 40, "by_horizon": {
            "h6": {"delta_pct_by_scenario": {"A": 5.0, "B": -2.0}},
            "h12": {"delta_pct_by_scenario": {"A": 10.0, "B": -5.0}}}},
    },
    "unmapped_tickers": [],
}

BOND_CARRY = {"bond_carry": {
    "schema": 1,
    "portfolio_level_by_horizon": {
        "h6": {"A": {"carry_rub": 5000}, "B": {"carry_rub": 3000}},
        "h12": {"A": {"carry_rub": 10000}, "B": {"carry_rub": 6000}}},
    "per_position": {}, "warnings": []}}

HORIZON = {
    "factors_by_horizon": {
        "A": {"h6": {"brent": 1.5, "usdrub": 2.0}, "h12": {"brent": 3.0, "usdrub": 4.0}},
        "B": {"h6": {"brent": -1.5, "usdrub": -2.0}, "h12": {"brent": -3.0, "usdrub": -4.0}}},
    "horizon_coverage": {"h6": {"status": "covered", "ci_inflation": 1.0},
                          "h12": {"status": "extrapolated", "ci_inflation": 1.2842}},
    "warnings": [], "as_of": "2026-05-12", "horizons": [6, 12]}

FILL = {
    "_drop": ["sector_breakdown_pct"],
    "sector_breakdown_pct": {"Финансы": {"weight_pct": 60}, "Прочее": {"weight_pct": 40}},
    "sector_breakdown_basis": "price",
    "concentration_ratio": 0.6,
    "dominant_factor": "brent",
    "top_risks": [{"ticker": "TICK1", "scenario": "A", "delta_pct": -20.0, "weight_pct": 60}],
    "macro_blindspots": [],
    "caveats": [{"severity": "HIGH", "message": "priors-only"}],
    "robustness": {"hedge_target": "A"},
    "method": "тест",
}


class Env:
    """Временная папка с настоящим стабом и фрагментами."""

    def __init__(self, td: str, weight_type: str = "equal"):
        self.d = Path(td)
        (self.d / "snap.json").write_text(json.dumps(SNAPSHOT))
        (self.d / "ssot.yaml").write_text(SSOT)
        (self.d / "macro.yaml").write_text(MACRO)
        r = subprocess.run([sys.executable, str(STUB), "--snapshot", str(self.d / "snap.json"),
                            "--scenarios", str(self.d / "ssot.yaml"), "--macro-scenarios", str(self.d / "macro.yaml"),
                            "--output", str(self.d / "stub.yaml"), "--today", "2026-05-12",
                            "--slug", "t", "--horizons", "6,12", "--primary-horizon", "12"],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        agg = cpa.compute(SNAPSHOT, {"A": {"p": 0.5}, "B": {"p": 0.5}}, PER_POSITION["per_position"],
                          BOND_CARRY["bond_carry"], weight_type, False)
        self.dump("pp.yaml", PER_POSITION)
        self.dump("bc.yaml", BOND_CARRY)
        self.dump("agg.yaml", agg)
        (self.d / "hf.json").write_text(json.dumps(HORIZON, ensure_ascii=False))
        self.dump("fill.yaml", FILL)

    def dump(self, name: str, obj) -> None:
        (self.d / name).write_text(yaml.safe_dump(obj, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def run(self, skip: tuple = (), extra: list[str] | None = None, output: str = "out.yaml",
            overrides: dict | None = None) -> subprocess.CompletedProcess:
        files = {"--stub": "stub.yaml", "--per-position": "pp.yaml", "--bond-carry": "bc.yaml",
                 "--aggregates": "agg.yaml", "--horizon-factors": "hf.json", "--fill": "fill.yaml",
                 "--snapshot": "snap.json"}
        files.update(overrides or {})
        args = [sys.executable, str(ASM)]
        for flag, name in files.items():
            if flag not in skip:
                args += [flag, str(self.d / name)]
        args += ["--output", str(self.d / output)] + (extra or [])
        return subprocess.run(args, capture_output=True, text=True)

    def out(self, name: str = "out.yaml") -> dict:
        return yaml.safe_load((self.d / name).read_text(encoding="utf-8"))


def test_assembles_expected_tree() -> bool:
    print("\n[test_assembles_expected_tree]")
    with tempfile.TemporaryDirectory() as td:
        e = Env(td)
        r = e.run()
        ok = check("exit 0", r.returncode == 0, r.stderr[:400])
        if not ok:
            return False
        t = e.out()
        stub = yaml.safe_load((e.d / "stub.yaml").read_text(encoding="utf-8"))
        ok &= check("per_position == фрагмент", t["per_position"] == PER_POSITION["per_position"])
        ok &= check("unmapped_tickers == фрагмент", t["unmapped_tickers"] == [])
        ok &= check("bond_carry == фрагмент (как есть)", t["bond_carry"] == BOND_CARRY["bond_carry"])
        agg = yaml.safe_load((e.d / "agg.yaml").read_text(encoding="utf-8"))
        ok &= check("portfolio_aggregates == фрагмент", t["portfolio_aggregates"] == agg["portfolio_aggregates"])
        ok &= check("robustness.price/total_return == фрагмент",
                    all(t["robustness"][b] == agg["robustness"][b] for b in ("price", "total_return")))
        ok &= check("modal_scenario none (equal), hedge_target из fill",
                    t["robustness"]["modal_scenario"] == "none" and t["robustness"]["hedge_target"] == "A")
        ok &= check("portfolio_level_by_horizon == фрагмент",
                    all(t["scenarios"][s]["portfolio_level_by_horizon"] == agg["scenarios"][s]["portfolio_level_by_horizon"]
                        for s in ("A", "B")))
        ok &= check("factors_by_horizon и horizon_coverage из --horizon-factors",
                    t["scenarios"]["A"]["factors_by_horizon"] == HORIZON["factors_by_horizon"]["A"]
                    and t["horizon_coverage"] == HORIZON["horizon_coverage"])
        ok &= check("name/p/p_by_horizon из стаба",
                    t["scenarios"]["A"]["name"] == "Сценарий А" and t["scenarios"]["A"]["p"] == 0.5)
        ok &= check("метаданные стаба на месте",
                    all(t[k] == stub[k] for k in ("schema_version", "type", "date", "horizons", "horizon_ends",
                                                  "base_value_rub", "baseline_spot", "factor_definitions")))
        ok &= check("поля fill на месте", t["top_risks"] == FILL["top_risks"] and t["method"] == "тест"
                    and t["dominant_factor"] == "brent")
        ok &= check("_drop убрал плейсхолдер стаба, ключ задан в fill своей формой",
                    t["sector_breakdown_pct"] == FILL["sector_breakdown_pct"])
        ok &= check("TODO_LLM не осталось", "TODO_LLM" not in (e.d / "out.yaml").read_text(encoding="utf-8"))
        summ = json.loads(r.stdout)
        ok &= check("сводка: источники и валидация",
                    summ["sources"]["per_position"] == "per-position" and summ["validation"] == "ok"
                    and summ["sources"]["bond_carry"] == "bond-carry")
        return ok


def test_fill_cannot_override_computed() -> bool:
    print("\n[test_fill_cannot_override_computed]")
    cases = {
        "per_position": {"per_position": {"TICK1": {"weight_pct": 1}}},
        "bond_carry": {"bond_carry": {"schema": 2}},
        "portfolio_aggregates": {"portfolio_aggregates": {"price": {}}},
        "portfolio_level_by_horizon": {"scenarios": {"A": {"portfolio_level_by_horizon": {"h6": {}}}}},
        "лист aggregates (robustness.price.basis)": {"robustness": {"price": {"basis": "x"}}},
        "factors_by_horizon": {"scenarios": {"A": {"factors_by_horizon": {"h6": {"brent": 99}}}}},
        "стаб (base_value_rub)": {"base_value_rub": 1},
        "стаб (name сценария)": {"scenarios": {"A": {"name": "чужое"}}},
        "новый ключ внутри посчитанного (per_position)": {"per_position": {}, "unmapped_tickers": ["X"]},
        "horizon_coverage": {"horizon_coverage": {"h6": {"status": "x"}}},
    }
    ok = True
    for label, patch in cases.items():
        with tempfile.TemporaryDirectory() as td:
            e = Env(td)
            e.dump("fill.yaml", {**FILL, **patch} if "scenarios" not in patch and "robustness" not in patch
                   else {**FILL, **{k: (patch[k] if k != "robustness" else {**FILL["robustness"], **patch[k]})
                                    for k in patch}})
            r = e.run()
            ok &= check(f"отказ: {label}", r.returncode == 1 and not (e.d / "out.yaml").exists()
                        and "ОТКАЗ" in r.stderr, f"rc={r.returncode} {r.stderr[:200]}")
    return ok


def test_overridable_stub_defaults() -> bool:
    print("\n[test_overridable_stub_defaults]")
    with tempfile.TemporaryDirectory() as td:
        e = Env(td)
        e.dump("fill.yaml", {**FILL, "scenario_source": "scenario-builder"})
        r = e.run()
        return check("scenario_source переопределяется", r.returncode == 0
                     and e.out()["scenario_source"] == "scenario-builder", r.stderr[:300])


def test_leftover_todo_refused() -> bool:
    print("\n[test_leftover_todo_refused]")
    with tempfile.TemporaryDirectory() as td:
        e = Env(td)
        f = dict(FILL)
        f.pop("top_risks")
        e.dump("fill.yaml", f)
        r = e.run()
        ok = check("не заполнен top_risks → отказ", r.returncode == 1 and "TODO_LLM" in r.stderr
                   and "top_risks" in r.stderr and not (e.d / "out.yaml").exists(), r.stderr[:300])
        f2 = dict(FILL)
        f2["method"] = "TODO_LLM_потом"
        e.dump("fill.yaml", f2)
        r = e.run()
        ok &= check("TODO_LLM внутри fill → отказ", r.returncode == 1 and "TODO_LLM" in r.stderr)
        f3 = {k: v for k, v in FILL.items() if k != "robustness"}
        e.dump("fill.yaml", f3)
        r = e.run()
        ok &= check("не задан hedge_target → отказ", r.returncode == 1 and "robustness.hedge_target" in r.stderr,
                    r.stderr[:300])
        return ok


def test_probability_modal_slot_needs_fill() -> bool:
    print("\n[test_probability_modal_slot_needs_fill]")
    with tempfile.TemporaryDirectory() as td:
        e = Env(td, weight_type="probability")
        r = e.run()
        ok = check("probability: modal_scenario — слот под fill → отказ без него",
                   r.returncode == 1 and "modal_scenario" in r.stderr, r.stderr[:300])
        e.dump("fill.yaml", {**FILL, "weight_type": "probability",
                              "robustness": {"hedge_target": "A", "modal_scenario": "none"}})
        r = e.run()
        ok &= check("с fill собирается", r.returncode == 0 and e.out()["robustness"]["modal_scenario"] == "none",
                    r.stderr[:300])
        return ok


def test_missing_required_fragment() -> bool:
    print("\n[test_missing_required_fragment]")
    ok = True
    for flag in ("--per-position", "--aggregates"):
        with tempfile.TemporaryDirectory() as td:
            e = Env(td)
            r = e.run(skip=(flag,))
            ok &= check(f"нет {flag} → отказ 1", r.returncode == 1 and flag in r.stderr
                        and not (e.d / "out.yaml").exists(), r.stderr[:200])
    with tempfile.TemporaryDirectory() as td:
        e = Env(td)
        r = e.run(skip=("--bond-carry", "--horizon-factors"))
        ok &= check("без --bond-carry и --horizon-factors → отказ (факторы остались TODO_LLM)",
                    r.returncode == 1 and "factors_by_horizon" in r.stderr, r.stderr[:300])
    with tempfile.TemporaryDirectory() as td:
        e = Env(td)
        r = e.run(skip=("--bond-carry",))
        ok &= check("без --bond-carry (портфель без облигаций) собирается, bond_carry нет",
                    r.returncode == 0 and "bond_carry" not in e.out(), r.stderr[:200])
    return ok


def test_output_equals_input_refused() -> bool:
    print("\n[test_output_equals_input_refused]")
    ok = True
    for flag, name in (("--stub", "stub.yaml"), ("--per-position", "pp.yaml"), ("--aggregates", "agg.yaml"),
                       ("--bond-carry", "bc.yaml"), ("--horizon-factors", "hf.json"), ("--fill", "fill.yaml")):
        with tempfile.TemporaryDirectory() as td:
            e = Env(td)
            before = (e.d / name).read_bytes()
            r = e.run(output=name)
            ok &= check(f"--output = {flag} → отказ, вход цел", r.returncode == 1
                        and (e.d / name).read_bytes() == before, r.stderr[:200])
    return ok


def test_validator_blocks_and_no_validate() -> bool:
    print("\n[test_validator_blocks_and_no_validate]")
    with tempfile.TemporaryDirectory() as td:
        e = Env(td)
        agg = yaml.safe_load((e.d / "agg.yaml").read_text(encoding="utf-8"))
        agg["scenarios"]["A"]["portfolio_level_by_horizon"]["h6"]["total_return_rub"] += 777  # ломает тождество баз
        e.dump("agg.yaml", agg)
        r = e.run()
        ok = check("блокер валидатора → код 1, файла нет", r.returncode == 1 and "валидатор" in r.stderr
                   and not (e.d / "out.yaml").exists(), r.stderr[:300])
        r = e.run(extra=["--no-validate"])
        ok &= check("--no-validate → файл записан", r.returncode == 0 and (e.d / "out.yaml").exists()
                    and json.loads(r.stdout)["validation"] == "skipped", r.stderr[:200])
        return ok


def test_every_position_needs_sensitivity() -> bool:
    """Чувствительность — у каждой бумаги портфеля: без снапшота покрытие не проверить, а бумага в
    unmapped_tickers выпала бы из расчёта вместе со своим весом — в обоих случаях файл не пишется."""
    print("\n[test_every_position_needs_sensitivity]")
    with tempfile.TemporaryDirectory() as td:
        e = Env(td)
        r = e.run(skip=("--snapshot",))
        ok = check("без --snapshot → код 1, файла нет", r.returncode == 1 and "нужен --snapshot" in r.stderr
                   and not (e.d / "out.yaml").exists(), r.stderr[:300])
        r = e.run(skip=("--snapshot",), extra=["--no-validate"])
        ok &= check("--no-validate снапшота не требует", r.returncode == 0, r.stderr[:200])
        (e.d / "out.yaml").unlink()
        pp = yaml.safe_load((e.d / "pp.yaml").read_text(encoding="utf-8"))
        pp["unmapped_tickers"] = ["TICKX"]
        e.dump("pp.yaml", pp)
        r = e.run()
        ok &= check("непустой unmapped_tickers → блокер валидатора, файла нет",
                    r.returncode == 1 and "unmapped_tickers" in r.stderr and not (e.d / "out.yaml").exists(), r.stderr[:300])
        return ok


def test_deterministic_and_atomic() -> bool:
    print("\n[test_deterministic_and_atomic]")
    with tempfile.TemporaryDirectory() as td:
        e = Env(td)
        r1 = e.run(output="o1.yaml")
        r2 = e.run(output="o2.yaml")
        ok = check("оба прогона успешны", r1.returncode == 0 and r2.returncode == 0)
        ok &= check("файлы побайтно равны", (e.d / "o1.yaml").read_bytes() == (e.d / "o2.yaml").read_bytes())
        ok &= check("порядок ключей: стаб, затем добавленные",
                    list(e.out("o1.yaml"))[:3] == ["schema_version", "type", "date"])
        ok &= check("временных файлов не осталось", not list(e.d.glob(".*.tmp")))
        # неудачная сборка не трогает существующий выход
        (e.d / "keep.yaml").write_text("keep: 1\n")
        e.dump("fill.yaml", {})
        r = e.run(output="keep.yaml")
        ok &= check("отказ не затирает существующий выход", r.returncode == 1
                    and (e.d / "keep.yaml").read_text() == "keep: 1\n")
        return ok


TESTS = [
    test_assembles_expected_tree,
    test_fill_cannot_override_computed,
    test_overridable_stub_defaults,
    test_leftover_todo_refused,
    test_probability_modal_slot_needs_fill,
    test_missing_required_fragment,
    test_output_equals_input_refused,
    test_validator_blocks_and_no_validate,
    test_every_position_needs_sensitivity,
    test_deterministic_and_atomic,
]


def main() -> int:
    passed = failed = 0
    for t in TESTS:
        try:
            ok = t()
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  ✗ {t.__name__}: {type(e).__name__}: {e}")
            ok = False
        passed += ok
        failed += not ok
    print(f"\n{'=' * 50}\nPassed: {passed}/{len(TESTS)}; Failed: {failed}")
    print(f"Итого: {passed} из {len(TESTS)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
