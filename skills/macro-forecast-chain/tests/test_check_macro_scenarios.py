#!/usr/bin/env python3
"""Тесты общего модуля _shared-references/macro_grid_check.py и CLI check_macro_scenarios.py.
Синтетика, без сети и библиотеки.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 skills/macro-forecast-chain/tests/test_check_macro_scenarios.py
"""
from __future__ import annotations

import copy
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / "skills/macro-forecast-chain/scripts/check_macro_scenarios.py"
sys.path.insert(0, str(REPO / "_shared-references"))
import macro_grid_check as mgc  # noqa: E402

fails = 0


def check(label, cond, detail=""):
    global fails
    if cond:
        print(f"  ✓ {label}")
    else:
        fails += 1
        print(f"  ✗ {label}{(' — ' + detail) if detail else ''}")


def _e(v, p=None):
    d = {"value": v}
    if p is not None:
        d["pct_vs_spot"] = p
    return d


def macro(with_matrix=True):
    g = lambda v: {"2026-12-31": _e(v), "2027-12-31": _e(v)}  # noqa: E731
    m = {
        "baseline_spot": {"brent_price": 100.0, "usdrub_rate": 80.0, "cnyrub_rate": 12.0, "cbr_rate": 14.0,
                          "xauusd_price": 4000},
        "factors": {
            "brent_price": {"by_scenario": {"A": {"2026-12-31": _e(90.0, -10.0)}, "B": g(95)}},
            "usdrub_rate": {"by_scenario": {"A": g(82), "B": g(85)}},
            "cnyrub_rate": {"by_scenario": {"A": g(12.1), "B": g(12.5)}},
            "cbr_rate": {"by_scenario": {"A": g(15), "B": g(13)}},
            "xauusd_price": {"level_all_scenarios": g(4500)},
            "sanctions_russia": {"by_scenario": {"A": "x"}},
        },
    }
    if with_matrix:
        m["scenario_matrix"] = {"scenarios": [{"id": "A"}, {"id": "B"}]}
    return m


def errs_of(m):
    return mgc.check_macro_file(m)


print("общий модуль")
e, w = errs_of(macro())
check("годный файл: ни отказов, ни предупреждений", e == [] and w == [], f"{e} {w}")
check("сценарии из scenario_matrix.scenarios", mgc.scenario_ids_from_file(macro()) == ["A", "B"])
check("нет scenario_matrix — пусто", mgc.scenario_ids_from_file(macro(False)) == [])
e, _ = errs_of(macro(False))
check("без матрицы по ключам by_scenario — годен", e == [], str(e))

m = macro(); del m["baseline_spot"]
check("нет baseline_spot", any("baseline_spot" in x for x in errs_of(m)[0]))
m = macro(); m["baseline_spot"]["brent_price"] = -1
check("спот не положительный", any("не положительное" in x for x in errs_of(m)[0]))
m = macro(); del m["baseline_spot"]["cbr_rate"]
check("нет спота фактора", any("cbr_rate: нет спота" in x for x in errs_of(m)[0]))
m = macro(); del m["factors"]["usdrub_rate"]
check("нет фактора", any("usdrub_rate: фактор отсутствует" in x for x in errs_of(m)[0]))
m = macro(); m["factors"]["brent_price"] = {"unit": "x"}
check("нет by_scenario и level_all_scenarios", any("нет ни by_scenario" in x for x in errs_of(m)[0]))
m = macro(); m["factors"]["cbr_rate"]["by_scenario"]["A"] = {"завтра": _e(15)}
check("дата не ISO", any("не ISO-дата" in x for x in errs_of(m)[0]))
m = macro(); m["factors"]["cbr_rate"]["by_scenario"]["B"] = {"2026-12-31": {"value": "много"}}
check("нет числового value", any("нет ни одной даты с числовым value" in x for x in errs_of(m)[0]))
m = macro(); del m["factors"]["cbr_rate"]["by_scenario"]["B"]
e, _ = errs_of(m)
check("сценарий матрицы пропал у фактора", any("cbr_rate, сценарий B" in x for x in e), str(e))
m = macro(False); del m["factors"]["cbr_rate"]["by_scenario"]["B"]
e, _ = errs_of(m)
check("без матрицы: разные наборы сценариев у факторов — отказ",
      any("набор сценариев" in x for x in e), str(e))
m = macro(); m["factors"]["brent_price"]["by_scenario"]["A"]["2026-12-31"]["pct_vs_spot"] = -2.0
e, w = errs_of(m)
check("расхождение pct_vs_spot — предупреждение, не отказ", e == [] and len(w) == 1 and "pct_vs_spot" in w[0], str((e, w)))
check("не словарь", errs_of([1])[0] != [])

print("CLI")


def run(m):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "macro-scenarios-2026-11-06.yaml"
        p.write_text(yaml.safe_dump(m, allow_unicode=True), encoding="utf-8")
        return subprocess.run([sys.executable, str(CLI), str(p)], capture_output=True, text=True)


r = run(macro())
check("годный: код 0, «ок»", r.returncode == 0 and "ок" in r.stdout, r.stdout + r.stderr)
m = macro(); del m["baseline_spot"]
r = run(m)
check("негодный: код 1, ОТКАЗ", r.returncode == 1 and "ОТКАЗ" in r.stdout, r.stdout)
m = macro(); m["factors"]["brent_price"]["by_scenario"]["A"]["2026-12-31"]["pct_vs_spot"] = -2.0
r = run(m)
check("предупреждение не ломает код", r.returncode == 0 and "ПРЕДУПРЕЖДЕНИЕ" in r.stdout, r.stdout)
r = subprocess.run([sys.executable, str(CLI), "/нет/файла.yaml"], capture_output=True, text=True)
check("нет файла: код 2", r.returncode == 2)

print("сверка матрицы прогнозов")
import os  # noqa: E402

OLD, NEW = "scenario-geopolitics-ru-west-2026-07-01", "scenario-geopolitics-ru-west-2026-11-06"


def lib(forecast_matrices: dict):
    d = tempfile.mkdtemp(prefix="lib-")
    (Path(d) / "forecasts").mkdir()
    (Path(d) / "macro-chain").mkdir()
    for n, mx in forecast_matrices.items():
        body = {"conditional_on_scenarios": {"source_matrix": f"scenarios/{mx}.yaml"}} if mx else {"forecast": {}}
        (Path(d) / "forecasts" / f"{n}.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")
    return Path(d)


def mm(matrix=NEW, ff=None):
    m = macro()
    m["scenario_matrix"]["source_file"] = f"scenarios/{matrix}.yaml"
    m["forecast_files"] = ff or {"brent_price": "brent-1", "cbr_rate": "cbr-1"}
    return m


def cli(d, m, *extra, sub="macro-chain"):
    p = Path(d) / sub
    p.mkdir(exist_ok=True)
    f = p / "macro-scenarios-2026-11-06.yaml"
    f.write_text(yaml.safe_dump(m, allow_unicode=True), encoding="utf-8")
    return subprocess.run([sys.executable, str(CLI), str(f), *extra], capture_output=True, text=True)


import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("cms", CLI)
cms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cms)

d = lib({"brent-1": OLD, "cbr-1": NEW})
r = cli(d, mm(), "--root", str(d))
check("расхождение: код 1 и текст отказа",
      r.returncode == 1 and "ОТКАЗ" in r.stdout and f"фактор brent_price: прогноз brent-1 построен на матрице {OLD}, "
      f"файл собран на матрице {NEW}" in r.stdout and f"пересобери прогноз на {NEW}" in r.stdout, r.stdout)
check("совпавший фактор не в отказе", "cbr_rate" not in r.stdout)
d = lib({"brent-1": NEW, "cbr-1": NEW})
r = cli(d, mm(), "--root", str(d))
check("совпадение: код 0, «ок»", r.returncode == 0 and "ок" in r.stdout, r.stdout)
r = cli(d, mm())
check("корень выводится из положения файла (<root>/macro-chain/)", r.returncode == 0 and "ПРЕДУПРЕЖДЕНИЕ" not in r.stdout, r.stdout)
d2 = lib({"brent-1": OLD, "cbr-1": NEW})
r = cli(d2, mm(), sub="_drafts")
check("корень из <root>/_drafts/ → отказ без --root", r.returncode == 1 and "brent-1" in r.stdout, r.stdout)
other = tempfile.mkdtemp(prefix="nolib-")
r = cli(other, mm())
check("вне библиотеки без --root: предупреждение и код 0",
      r.returncode == 0 and "ПРЕДУПРЕЖДЕНИЕ: матрица прогнозов не сверена: укажи --root" in r.stdout, r.stdout)
d = lib({"brent-1": None, "cbr-1": NEW})
r = cli(d, mm(), "--root", str(d))
check("прогноз без source_matrix не мешает", r.returncode == 0 and "ОТКАЗ" not in r.stdout, r.stdout)

e, w = cms.check_forecast_matrix(macro(False), "/x")
check("нет scenario_matrix.source_file — предупреждение", e == [] and "нет scenario_matrix.source_file" in w[0], str(w))
m = mm(); del m["forecast_files"]
m["factors"]["brent_price"]["source_files"] = ["macro-snapshots/x.md", "forecasts/brent-1.yaml"]
d = lib({"brent-1": OLD})
e, w = cms.check_forecast_matrix(m, str(d))
check("нет forecast_files — берутся source_files с forecasts/", len(e) == 1 and "brent_price" in e[0], str((e, w)))
d = lib({})
e, w = cms.check_forecast_matrix(mm(), str(d))
check("нет файла прогноза — предупреждение, не отказ", e == [] and len(w) == 2 and "не найден" in w[0], str((e, w)))

print("сторож состава пакета (pack.sh кладёт модуль по импорту в scripts/)")
for rel in ("skills/macro-forecast-chain/scripts/check_macro_scenarios.py",
            "skills/portfolio-scenario-stress/scripts/compute_horizon_factors.py",
            "skills/save-to-library/scripts/assemble_artifact.py"):
    src = (REPO / rel).read_text(encoding="utf-8")
    check(f"{rel}: import macro_grid_check в начале строки",
          re.search(r"^import macro_grid_check\b", src, re.M) is not None)
check("deploy.zsh выкладывает macro_grid_check.py на NAS",
      "macro_grid_check.py" in (REPO / "tools/deploy.zsh").read_text(encoding="utf-8"))

print(f"\nИтого: {'все зелёные' if not fails else str(fails) + ' красных'}")
sys.exit(1 if fails else 0)
