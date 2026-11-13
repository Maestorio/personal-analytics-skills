#!/usr/bin/env python3
"""Тесты stress_judgments.py и входа --judgments в stress_recalc.py.

Синтетика — построитель из test_stress_recalc.py.
"""
from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_stress_recalc as tsr  # noqa: E402

SCRIPTS = tsr.SCRIPTS
JUDG = SCRIPTS / "stress_judgments.py"
sys.path.insert(0, str(SCRIPTS))
import stress_judgments as sj  # noqa: E402

check, snapshot, load = tsr.check, tsr.snapshot, tsr.load


def cli(*a):
    return subprocess.run([sys.executable, str(JUDG), *a], capture_output=True, text=True)


def judg(d: Path):
    st = tsr.build_skill_stress(d, snapshot())
    j = sj.extract(load(st))
    return st, j


def test_extract_valid_and_no_computed():
    with tempfile.TemporaryDirectory() as td:
        st, j = judg(Path(td))
        full = load(st)
        ok = check("validate чисто", sj.validate(j) == [], str(sj.validate(j)))
        ok &= check("schema", j["schema"] == "stress-judgments@1")
        ok &= check("верх не содержит посчитанного",
                    not ({"per_position", "bond_carry", "portfolio_aggregates", "unmapped_tickers",
                          "base_value_rub", "portfolio_snapshot_id", "robustness", "run_id"} & set(j)))
        ok &= check("нет by_horizon/weight_pct/on_iis в priors",
                    all(not ({"by_horizon", "weight_pct", "on_iis"} & set(p)) for p in j["priors"].values()))
        ok &= check("нет portfolio_level в сценариях",
                    all("portfolio_level_by_horizon" not in s for s in j["scenarios"].values()))
        ok &= check("robustness — только суждения",
                    set(j["narrative"]["robustness"]) == {"hedge_target", "modal_scenario"})
        ok &= check("суждения компактнее полного", len(sj.dump(j)) < len(yaml.safe_dump(full)))
        return ok


def test_recalc_judgments_equals_stress():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st, j = judg(d)
        jf = d / "j.yaml"
        jf.write_text(sj.dump(j), encoding="utf-8")
        snap = snapshot(qty1=700000.0, as_of="2026-05-20")
        r1 = tsr.run(d, st, snap, output="os.yaml")
        r2 = subprocess.run([sys.executable, str(tsr.RECALC), "--judgments", str(jf), "--snapshot",
                             str(d / "snapn.json"), "--output", str(d / "oj.yaml"), "--today", "2026-06-01",
                             "--at", "2026-06-01T10:00:00+03:00", "--json"], capture_output=True, text=True)
        os_, oj = load(d / "os.yaml"), load(d / "oj.yaml")
        ok = check("оба кода 0", r1.returncode == 0 and r2.returncode == 0, r1.stderr + r2.stderr)
        ra, rb = dict(os_.pop("recalc")), dict(oj.pop("recalc"))
        ok &= check("source_kind", ra.pop("source_kind") == "stress" and rb.pop("source_kind") == "judgments")
        ok &= check("source_stress — имя файла", ra.pop("source_stress") == "stress-skill.yaml"
                    and rb.pop("source_stress") == "j.yaml")
        ok &= check("остальной recalc равен", ra == rb, f"{ra} / {rb}")
        ok &= check("деревья равны", os_ == oj)
        return ok


def test_same_snapshot_judgments_reproduce_full():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st, j = judg(d)
        jf = d / "j.yaml"
        jf.write_text(sj.dump(j), encoding="utf-8")
        (d / "s.json").write_text(__import__("json").dumps(snapshot()))
        r = subprocess.run([sys.executable, str(tsr.RECALC), "--judgments", str(jf), "--snapshot",
                            str(d / "s.json"), "--output", str(d / "o.yaml"), "--today", "2026-06-01"],
                           capture_output=True, text=True)
        full, out = load(st), load(d / "o.yaml")
        # Расчётные поля fill (в тестовом источнике — произвольные значения модели) пересчитываются.
        derived = {"cash_rub_pct", "blocked_pct", "blocked_rub_memo", "weight_base_note", "sector_breakdown_pct",
                   "sector_breakdown_basis", "top_risks", "top_resilient", "concentration_ratio", "concentration"}
        diff = [k for k in set(full) | set(out)
                if k not in {"date", "run_id", "recalc", "caveats"} | derived and full.get(k) != out.get(k)]
        # caveats: записи модели те же, в конце добавлена запись скрипта о покрытии сроков
        diff += [] if out["caveats"][:len(full["caveats"])] == full["caveats"] else ["caveats"]
        return (check("код 0", r.returncode == 0, r.stderr) & check("все ключи равны полному", diff == [], str(diff))
                & check("расчётные поля посчитаны, portfolio_summary нет",
                        {"cash_rub_pct", "blocked_pct", "sector_breakdown_pct", "top_risks", "weight_base_note"} <= set(out)
                        and "portfolio_summary" not in out))


def test_validate_catches():
    with tempfile.TemporaryDirectory() as td:
        _, j = judg(Path(td))
        def bad(mod):
            x = copy.deepcopy(j)
            mod(x)
            return sj.validate(x)
        ok = True
        cases = {
            "нет ключа": (lambda x: x.pop("carry"), "carry"),
            "чужая schema": (lambda x: x.update(schema="stress-judgments@2"), "schema"),
            "нет фактора": (lambda x: x["priors"]["TICK1"]["factor_betas"].pop("xauusd"), "xauusd"),
            "сценарий без горизонта": (lambda x: x["scenarios"]["A"]["factors_by_horizon"].pop("h12"), "h12"),
            "горизонты покрытия": (lambda x: x["horizon_coverage"].pop("h6"), "horizon_coverage"),
            "горизонты весов": (lambda x: x["scenarios"]["B"]["p_by_horizon"].update(h99=0.1), "p_by_horizon"),
            "посчитанное в priors": (lambda x: x["priors"]["TICK1"].update(weight_pct=1.0), "weight_pct"),
            "посчитанное в narrative": (lambda x: x["narrative"].update(bond_carry={}), "bond_carry"),
        }
        for name, (mod, needle) in cases.items():
            errs = bad(mod)
            ok &= check(f"ловит: {name}", any(needle in e for e in errs), str(errs))
        return ok


def test_cli_codes():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st, j = judg(d)
        out = d / "j.yaml"
        r = cli("extract", "--stress", str(st), "--output", str(out))
        ok = check("extract 0", r.returncode == 0, r.stderr)
        ok &= check("validate 0", cli("validate", "--file", str(out)).returncode == 0)
        before = st.read_bytes()
        r = cli("extract", "--stress", str(st), "--output", str(st))
        ok &= check("output = stress -> 1, файл цел", r.returncode == 1 and st.read_bytes() == before)
        x = copy.deepcopy(j)
        x["schema"] = "zzz"
        (d / "bad.yaml").write_text(sj.dump(x), encoding="utf-8")
        ok &= check("validate невалидного -> 1", cli("validate", "--file", str(d / "bad.yaml")).returncode == 1)
        ok &= check("validate без --file -> 2", cli("validate").returncode == 2)
        ok &= check("нет файла -> 1", cli("validate", "--file", str(d / "none.yaml")).returncode == 1)
        (d / "s.json").write_text(__import__("json").dumps(snapshot()))
        base = [sys.executable, str(tsr.RECALC), "--snapshot", str(d / "s.json")]
        r = subprocess.run(base + ["--judgments", str(d / "bad.yaml"), "--output", str(d / "o1.yaml")],
                           capture_output=True, text=True)
        ok &= check("recalc: невалидные суждения -> 1 с текстом", r.returncode == 1 and "schema" in r.stderr
                    and not (d / "o1.yaml").exists())
        r = subprocess.run(base + ["--judgments", str(out), "--stress", str(st), "--output", str(d / "o2.yaml")],
                           capture_output=True, text=True)
        ok &= check("--stress + --judgments -> 2", r.returncode == 2 and not (d / "o2.yaml").exists())
        r = subprocess.run(base + ["--output", str(d / "o3.yaml")], capture_output=True, text=True)
        ok &= check("ни одного источника -> 2", r.returncode == 2)
        r = subprocess.run(base + ["--judgments", str(out), "--output", str(out)], capture_output=True, text=True)
        ok &= check("--output = --judgments -> 1", r.returncode == 1)
        return ok


def test_extract_deterministic():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st, _ = judg(d)
        cli("extract", "--stress", str(st), "--output", str(d / "a.yaml"))
        cli("extract", "--stress", str(st), "--output", str(d / "b.yaml"))
        return check("байт-в-байт", (d / "a.yaml").read_bytes() == (d / "b.yaml").read_bytes())


def test_macro_scenarios_judgments_equals_stress():
    """Подстановка макро-таблицы из файла суждений даёт те же числа, что из полного стресса."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st, j = judg(d)
        jf = d / "j.yaml"
        jf.write_text(sj.dump(j), encoding="utf-8")
        (d / "macro-new.yaml").write_text(yaml.safe_dump(tsr.macro_ab()), encoding="utf-8")
        (d / "s.json").write_text(__import__("json").dumps(snapshot()))
        base = ["--snapshot", str(d / "s.json"), "--macro-scenarios", str(d / "macro-new.yaml"),
                "--today", "2026-06-01", "--at", "2026-06-01T10:00:00+03:00"]
        r1 = subprocess.run([sys.executable, str(SCRIPTS / "stress_recalc.py"), "--stress", str(st), *base,
                             "--output", str(d / "a.yaml")], capture_output=True, text=True)
        r2 = subprocess.run([sys.executable, str(SCRIPTS / "stress_recalc.py"), "--judgments", str(jf), *base,
                             "--output", str(d / "b.yaml")], capture_output=True, text=True)
        ok = check("оба кода 0", r1.returncode == 0 and r2.returncode == 0, r1.stderr[-300:] + r2.stderr[-300:])
        a, b = load(d / "a.yaml"), load(d / "b.yaml")
        keys = ("per_position", "bond_carry", "portfolio_aggregates", "scenarios", "horizon_coverage", "baseline_spot", "macro_input")
        ok &= check("числа, факторы и происхождение равны: " + ", ".join(keys), all(a.get(k) == b.get(k) for k in keys))
        ok &= check("recalc.macro_input_was из суждений тот же", a["recalc"]["macro_input_was"] == b["recalc"]["macro_input_was"]
                    and b["recalc"]["reason"] == "macro")
        return ok


TESTS = [
    test_extract_valid_and_no_computed,
    test_recalc_judgments_equals_stress,
    test_same_snapshot_judgments_reproduce_full,
    test_validate_catches,
    test_cli_codes,
    test_extract_deterministic,
    test_macro_scenarios_judgments_equals_stress,
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
