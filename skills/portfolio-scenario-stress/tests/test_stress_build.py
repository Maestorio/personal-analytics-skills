#!/usr/bin/env python3
"""Тесты stress_build.py: стресс-файл одной командой из суждений (priors, факторы горизонтов, fill).

Стенд — тот же, что у test_stress_recalc.py: маленький снапшот и «стресс-файл скилла», собранный
настоящими расчётными функциями. Эталон равенства — stress_recalc.recalc(extract(полный файл)).
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SCRIPTS = REPO / "skills/portfolio-scenario-stress/scripts"
BUILD = SCRIPTS / "stress_build.py"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

import stress_build as sb  # noqa: E402
import stress_judgments as sj  # noqa: E402
import stress_recalc as sr  # noqa: E402
import test_stress_recalc as tsr  # noqa: E402  — стенд: snapshot(), build_skill_stress(), константы

check = tsr.check
TODAY = "2026-06-01"
# Расчётные блоки, которые обязаны совпасть.
CALC = ("per_position", "bond_carry", "portfolio_aggregates", "unmapped_tickers", "base_value_rub",
        "cash_rub_pct", "blocked_pct", "sector_breakdown_pct", "sector_breakdown_basis", "top_risks",
        "top_resilient", "concentration_ratio", "concentration", "weight_base_note")
JUDG_KEYS = ("macro_blindspots", "caveats", "dominant_factor", "method")


def load(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8"))


class Inputs:
    """Входы stress_build, выведенные из полного стресс-файла стенда."""

    def __init__(self, d: Path, snap: dict):
        self.d = d
        self.snap = snap
        self.full_path = tsr.build_skill_stress(d, snap)
        self.full = load(self.full_path)
        pp = self.full["per_position"]
        priors = {t: {k: v[k] for k in sj.PRIOR_KEYS if k in v} for t, v in pp.items()}
        self.priors = priors
        self.hf = {"factors_by_horizon": {s: sc["factors_by_horizon"] for s, sc in self.full["scenarios"].items()},
                   "horizon_coverage": self.full["horizon_coverage"]}
        self.fill = {k: copy.deepcopy(self.full[k]) for k in JUDG_KEYS}
        self.fill["concentration"] = {"dominant_factor": self.full["concentration"]["dominant_factor"],
                                      "note": self.full["concentration"]["note"]}
        self.fill["robustness"] = {"hedge_target": self.full["robustness"]["hedge_target"],
                                   "modal_scenario": self.full["robustness"]["modal_scenario"]}
        self.fill["weight_type"] = "probability"
        self.write("snap.json", snap, json_=True)
        self.write("priors.json", priors, json_=True)
        self.write("hf.json", self.hf, json_=True)
        self.write("fill.yaml", self.fill)

    def write(self, name: str, obj, json_=False) -> Path:
        p = self.d / name
        p.write_text(json.dumps(obj, ensure_ascii=False) if json_ else yaml.safe_dump(obj, allow_unicode=True),
                     encoding="utf-8")
        return p

    def cli(self, *, fill=True, out="out.yaml", extra=None, snap="snap.json", priors="priors.json",
            hf=("--horizon-factors", "hf.json")):
        cmd = [sys.executable, str(BUILD), "--snapshot", str(self.d / snap), "--scenarios", str(self.d / "ssot.yaml"),
               "--macro-scenarios", str(self.d / "macro.yaml"),
               "--output", str(self.d / out), "--horizons", "6,12", "--primary-horizon", "12",
               "--slug", "t", "--include-ev", "--today", TODAY]
        if priors:
            cmd += ["--priors", str(self.d / priors)]
        if hf:
            cmd += [hf[0], str(self.d / hf[1])]
        if fill:
            cmd += ["--fill", str(self.d / "fill.yaml")]
        return subprocess.run(cmd + list(extra or []), capture_output=True, text=True)


def reference(inp: Inputs, snap: dict | None = None) -> dict:
    j, ctx = sr.inputs_from_stress(inp.full)
    tree, _ = sr.recalc(j, snap or inp.snap, source_name="x", source_kind="stress", ctx=ctx, weights=None,
                        weights_name=None, today=inp.full["date"], at="2026-06-01T10:00:00+03:00")
    return tree


def same_calc(a: dict, b: dict, label: str) -> bool:
    ok = True
    for k in CALC + ("robustness",):
        ok &= check(f"{label}: {k} равен", a.get(k) == b.get(k))
    for s in a["scenarios"]:
        ok &= check(f"{label}: portfolio_level {s} равен",
                    a["scenarios"][s]["portfolio_level_by_horizon"] == b["scenarios"][s]["portfolio_level_by_horizon"])
    return ok


def test_equivalence_with_recalc():
    with tempfile.TemporaryDirectory() as td:
        inp = Inputs(Path(td), tsr.snapshot())
        r = inp.cli()
        ok = check("код 0", r.returncode == 0, r.stderr)
        out = load(inp.d / "out.yaml")
        ref = reference(inp)
        ok &= same_calc(out, ref, "stress_build = recalc")
        ok &= check("блока recalc нет, нет numbers_only", "recalc" not in out and "numbers_only" not in out)
        ok &= check("date и run_id — дата прогона (--today), не дата снапшота и не RECALC; review_date +6 мес.",
                    out["run_id"] == "PSS-20260601-T" and out["date"] == TODAY and out["review_date"] == "2026-12-01"
                    and out["portfolio_snapshot_id"] == "portfolio-2026-05-12.json",
                    f"{out['run_id']} {out['date']} {out['review_date']} {out['portfolio_snapshot_id']}")
        nfc = len(inp.full["caveats"])
        ok &= check("поля суждения из fill (+ в конце запись скрипта о покрытии сроков)",
                    out["caveats"][:nfc] == inp.full["caveats"] and out["method"] == "тест"
                    and [c.get("source") for c in out["caveats"][nfc:]] == ["script"])
        ok &= check("ожидание считается (probability + include-ev)",
                    out["portfolio_aggregates"]["price"]["expected_pl_rub_by_horizon"]["h12"] is not None)
        ok &= check("сценарии/факторы/покрытие как в эталоне",
                    all(out["scenarios"][s]["factors_by_horizon"] == inp.full["scenarios"][s]["factors_by_horizon"]
                        and out["scenarios"][s]["p_by_horizon"] == inp.full["scenarios"][s]["p_by_horizon"] for s in "AB")
                    and out["horizon_coverage"] == inp.full["horizon_coverage"])
        ok &= check("--json: сводка с таблицей и топ-убытками",
                    json.loads(inp.cli(out="o2.yaml", extra=["--json"]).stdout)["top_losers"] != [])
        return ok


def test_horizon_factors_input_equals_output():
    with tempfile.TemporaryDirectory() as td:
        inp = Inputs(Path(td), tsr.snapshot())
        # вход compute_horizon_factors: уровни года FCA; выход отдаёт те же движения, что и готовый файл
        pay = {"scenarios": {"A": {"factors": {"brent": {"h6": 10.0, "h12": 20.0, "unit": "pct"}}},
                             "B": {"factors": {"brent": {"h6": -10.0, "h12": -20.0, "unit": "pct"}}}}}
        import compute_horizon_factors as chf
        try:
            res = chf.run({**pay, "as_of": "2026-05-12", "horizons": [6, 12],
                           "horizon_ends": {"h6": "2026-11-30", "h12": "2027-05-31"}, "baseline_spot": {"brent_usd": 70}})
        except SystemExit:
            res = None
        if res is None:
            return check("вход horizon-factors-input принят расчётом", False)
        inp.write("hfin.json", pay, json_=True)
        r = inp.cli(hf=("--horizon-factors-input", "hfin.json"), out="o_in.yaml")
        r2 = inp.cli(hf=("--horizon-factors", "hfout.json"), out="o_out.yaml") if inp.write("hfout.json", res, json_=True) else None
        ok = check("оба режима кода 0", r.returncode == 0 and r2.returncode == 0, r.stderr + r2.stderr)
        ok &= check("одинаковый результат", (inp.d / "o_in.yaml").read_bytes() == (inp.d / "o_out.yaml").read_bytes())
        return ok


def test_circle_extract_recalc():
    with tempfile.TemporaryDirectory() as td:
        inp = Inputs(Path(td), tsr.snapshot())
        r = inp.cli()
        out = load(inp.d / "out.yaml")
        j, ctx = sr.inputs_from_stress(out)
        tree, _ = sr.recalc(j, inp.snap, source_name="x", source_kind="stress", ctx=ctx, weights=None, weights_name=None,
                            today=out["date"], at="2026-06-01T10:00:00+03:00")
        ok = check("код 0", r.returncode == 0, r.stderr)
        ok &= same_calc(out, tree, "круг extract → recalc")
        return ok


def test_numbers_only():
    with tempfile.TemporaryDirectory() as td:
        inp = Inputs(Path(td), tsr.snapshot())
        r = inp.cli(fill=False, extra=["--weight-type", "probability"])
        ok = check("код 0 без fill", r.returncode == 0, r.stderr)
        out = load(inp.d / "out.yaml")
        ok &= check("numbers_only: true", out.get("numbers_only") is True)
        ok &= check("слоты суждения — заглушка, не TODO_LLM",
                    out["robustness"]["hedge_target"] == "ЗАПОЛНИТЬ_В_FILL" and "TODO_LLM" not in json.dumps(out, ensure_ascii=False))
        ok &= check("числа посчитаны", bool(out["per_position"]) and "portfolio_aggregates" in out)
        ok &= check("концентрация без фактора не считается, сказано в выводе",
                    "concentration_ratio" not in out and "концентрация не посчитана" in r.stdout)
        ok &= check("блока recalc нет", "recalc" not in out)
        ref = load(inp.d / "out.yaml")
        r2 = inp.cli()
        full = load(inp.d / "out.yaml")
        ok &= check("числа те же, что в итоговом режиме", ref["per_position"] == full["per_position"]
                    and ref["portfolio_aggregates"] == full["portfolio_aggregates"])
        return ok


def test_refusals():
    with tempfile.TemporaryDirectory() as td:
        inp = Inputs(Path(td), tsr.snapshot())
        ok = True
        # бумага без priors — в обоих режимах
        snap3 = tsr.snapshot(with_t3=True)
        inp.write("snap3.json", snap3, json_=True)
        for fill in (True, False):
            r = inp.cli(snap="snap3.json", fill=fill, out="x.yaml")
            ok &= check(f"бумага без priors (fill={fill}): код 1, TICK3 — Три — доля",
                        r.returncode == 1 and "TICK3" in r.stderr and "Три" in r.stderr and "%" in r.stderr, r.stderr)
            ok &= check("файл не записан", not (inp.d / "x.yaml").exists())
        # посчитанное в fill
        bad = copy.deepcopy(inp.fill)
        bad.update({"per_position": {}, "cash_rub_pct": 5, "top_risks": []})
        bad["robustness"]["price"] = {}
        bad["concentration"]["same_direction_pct"] = 1
        inp.write("fill.yaml", bad)
        r = inp.cli(out="x.yaml")
        ok &= check("посчитанное в fill: код 1 и перечень ключей",
                    r.returncode == 1 and all(k in r.stderr for k in
                                              ("per_position", "cash_rub_pct", "top_risks", "robustness.price",
                                               "concentration.same_direction_pct")), r.stderr)
        # TODO_LLM в fill
        bad = copy.deepcopy(inp.fill)
        bad["method"] = "TODO_LLM_text"
        inp.write("fill.yaml", bad)
        r = inp.cli(out="x.yaml")
        ok &= check("TODO_LLM в fill: код 1", r.returncode == 1 and "TODO_LLM" in r.stderr, r.stderr)
        # нет hedge_target
        bad = copy.deepcopy(inp.fill)
        del bad["robustness"]["hedge_target"]
        inp.write("fill.yaml", bad)
        r = inp.cli(out="x.yaml")
        ok &= check("нет robustness.hedge_target: код 1", r.returncode == 1 and "hedge_target" in r.stderr, r.stderr)
        # блокер валидатора: устаревший скаляр верхнего уровня (запрещён контрактом баз)
        bad = copy.deepcopy(inp.fill)
        bad["expected_pl_rub"] = 5
        inp.write("fill.yaml", bad)
        r = inp.cli(out="x.yaml")
        ok &= check("блокер валидатора: код 1, файл не записан",
                    r.returncode == 1 and "валидатор" in r.stderr and not (inp.d / "x.yaml").exists(), r.stderr)
        # источники факторов горизонта
        inp.write("fill.yaml", inp.fill)
        r = inp.cli(hf=None, out="x.yaml")
        ok &= check("нет источника факторов, но есть --macro-scenarios: режим сетки, отказ без политических факторов (код 1)",
                    r.returncode == 1 and "--political-from" in r.stderr and "--political-paths" in r.stderr, r.stderr)
        r = subprocess.run([sys.executable, str(BUILD), "--snapshot", str(inp.d / "snap.json"), "--scenarios",
                            str(inp.d / "ssot.yaml"), "--priors", str(inp.d / "priors.json"),
                            "--output", str(inp.d / "x.yaml")], capture_output=True, text=True)
        ok &= check("нет ни факторов, ни --macro-scenarios: код 2", r.returncode == 2, str(r.returncode))
        inp.write("hfin.json", {"scenarios": {}}, json_=True)
        r = subprocess.run([sys.executable, str(BUILD), "--snapshot", str(inp.d / "snap.json"), "--scenarios",
                            str(inp.d / "ssot.yaml"), "--priors", str(inp.d / "priors.json"), "--horizon-factors",
                            str(inp.d / "hf.json"), "--horizon-factors-input", str(inp.d / "hfin.json"),
                            "--output", str(inp.d / "x.yaml")], capture_output=True, text=True)
        ok &= check("оба источника: код 2", r.returncode == 2, str(r.returncode))
        r = inp.cli(out="stress-skill.yaml")
        ok &= check("--output = входной файл не мешает; sanity: чистый запуск код 0", r.returncode == 0, r.stderr)
        r = inp.cli(out="snap.json")
        ok &= check("--output = --snapshot: код 1", r.returncode == 1)
        return ok


def _weights(he, a6=0.9, a12=0.1):
    return {"schema": "stress-weights@1", "horizon_ends": he, "set_at": "2026-06-01T09:00:00+03:00",
            "weights": {"h6": {"A": a6, "B": round(1 - a6, 6)}, "h12": {"A": a12, "B": round(1 - a12, 6)}}}


def test_weights():
    with tempfile.TemporaryDirectory() as td:
        inp = Inputs(Path(td), tsr.snapshot())
        base = load(inp.d / "out.yaml") if (inp.d / "out.yaml").exists() else None
        r0 = inp.cli(out="base.yaml")
        base = load(inp.d / "base.yaml")
        he = base["horizon_ends"]
        ok = check("база: веса на сайте не заданы — предупреждение, посчитано на весах матрицы",
                   r0.returncode == 0 and "веса на сайте не заданы" in r0.stdout, r0.stderr)
        w = inp.write("w.json", _weights(he), json_=True)
        r = inp.cli(out="w.yaml", extra=["--weights-json", str(w)])
        out = load(inp.d / "w.yaml")
        ok &= check("совпавшие сроки: код 0, p файла", r.returncode == 0 and out["scenarios"]["A"]["p_by_horizon"] == {"h6": 0.9, "h12": 0.1}
                    and out["scenarios"]["A"]["p"] == 0.1, r.stderr)
        ok &= check("ожидание изменилось, числа по сценариям те же",
                    out["portfolio_aggregates"]["price"]["expected_pl_rub_by_horizon"] != base["portfolio_aggregates"]["price"]["expected_pl_rub_by_horizon"]
                    and out["scenarios"]["A"]["portfolio_level_by_horizon"] == base["scenarios"]["A"]["portfolio_level_by_horizon"])
        ok &= check("в выводе — веса сайта", "stress-weights:w.json" in r.stdout and "recalc" not in out)
        # другие сроки
        w2 = inp.write("w2.json", _weights({"h6": "2026-12-31", "h12": "2027-06-30"}), json_=True)
        r = inp.cli(out="w2.yaml", extra=["--weights-json", str(w2)])
        out2 = load(inp.d / "w2.yaml")
        ok &= check("другие сроки: не отказ, предупреждение, веса матрицы",
                    r.returncode == 0 and "веса сайта заданы на другие сроки" in r.stdout and out2 == base, r.stderr + r.stdout)
        # нечитаемый файл
        (inp.d / "w3.json").write_text("{не json", encoding="utf-8")
        r = inp.cli(out="w3.yaml", extra=["--weights-json", str(inp.d / "w3.json")])
        ok &= check("нечитаемые веса: не отказ, предупреждение", r.returncode == 0 and "ПРЕДУПРЕЖДЕНИЕ" in r.stdout, r.stderr)
        # поиск по library-root; имя — по правилу stress_job
        lib = inp.d / "lib"
        (lib / "scenarios").mkdir(parents=True)
        try:
            sys.path.insert(0, str(REPO / "tools/hosting/notify"))
            import stress_job as stj
            rel = stj.weights_rel(stj.matrix_name({"scenario_matrix_ref": "scenarios/ssot.yaml"}))
        except Exception:  # noqa: BLE001 — тяжёлый импорт: сверка по строке
            rel = "scenarios/stress-weights-ssot.json"
        ok &= check("имя файла весов совпадает с правилом stress_job", rel == "scenarios/stress-weights-ssot.json", rel)
        (lib / rel).write_text(json.dumps(_weights(he)), encoding="utf-8")
        r = inp.cli(out="lib.yaml", extra=["--library-root", str(lib)])
        out3 = load(inp.d / "lib.yaml")
        ok &= check("--library-root: веса найдены", r.returncode == 0 and out3 == out, r.stderr)
        (lib / rel).unlink()
        r = inp.cli(out="lib2.yaml", extra=["--library-root", str(lib)])
        ok &= check("файла нет: веса матрицы и предупреждение «веса на сайте не заданы»",
                    r.returncode == 0 and load(inp.d / "lib2.yaml") == base and "веса на сайте не заданы" in r.stdout)
        r = inp.cli(out="w2.yaml", extra=["--weights-json", str(w)])
        ok &= check("веса заданы — предупреждения «не заданы» нет",
                    r.returncode == 0 and "веса на сайте не заданы" not in r.stdout)
        return ok


def _bond_snapshot():
    snap = tsr.snapshot()
    snap["holdings"].append({
        "ticker": "FLOATB", "name": "Облигация Икс", "asset_type": "bond", "sector": "bonds_corp", "value_rub": 300000.0,
        "is_blocked": False, "current_price": 98.0, "nominal": 1000.0, "nominal_currency": "SUR", "coupon_pct": 15.0,
        "coupon_freq_per_year": 4, "next_coupon_date": "2026-08-01", "maturity_date": "2029-05-01", "offer_date": None,
        "ytm_pct": 16.0, "ytm_to_offer_pct": None, "account": "main"})
    return snap


def test_carry_overrides():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        snap = _bond_snapshot()
        inp = Inputs(d, snap)
        inp.priors["FLOATB"] = {"factor_betas": {f: 0.0 for f in sj.CANONICAL_FACTORS}, "factor_betas_method": "тест-prior",
                                "factor_betas_r2": None}
        inp.priors["FLOATB"]["factor_betas"]["cbr_rate"] = -0.5
        inp.write("priors.json", inp.priors, json_=True)
        r0 = inp.cli(out="no.yaml")
        ok = check("без overrides код 0", r0.returncode == 0, r0.stderr)
        no = load(d / "no.yaml")
        ov = inp.write("ov.json", {"FLOATB": {"bond_type": "floater"}}, json_=True)
        r1 = inp.cli(out="ov.yaml", extra=["--carry-overrides", str(ov)])
        ok &= check("с overrides код 0", r1.returncode == 0, r1.stderr)
        yes = load(d / "ov.yaml")
        ok &= check("числа купонного слоя отличаются",
                    yes["bond_carry"]["per_position"]["FLOATB"] != no["bond_carry"]["per_position"]["FLOATB"])
        ok &= check("ключ overrides сохранён в bond_carry; без overrides ключа нет",
                    yes["bond_carry"].get("overrides") == {"FLOATB": {"bond_type": "floater"}} and "overrides" not in no["bond_carry"])
        j = sj.extract(yes)
        ok &= check("extract поднимает carry.overrides", j["carry"].get("overrides") == {"FLOATB": {"bond_type": "floater"}}
                    and "overrides" not in sj.extract(no)["carry"])
        tree, _ = sr.recalc(j, snap, source_name="x", source_kind="judgments", ctx=None, weights=None, weights_name=None,
                            today=yes["date"], at="2026-06-01T10:00:00+03:00")
        ok &= check("круг extract → recalc сохраняет числа и ключ", tree["bond_carry"] == yes["bond_carry"]
                    and tree["portfolio_aggregates"] == yes["portfolio_aggregates"])
        return ok


def test_asset_type_reaches_scale_guard():
    """asset_type из priors попадает в гарды шкалы: целая бета у `fund` — отказ, у `bond_fund` законна дробная."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        snap = tsr.snapshot()
        snap["holdings"].append({"ticker": "FUNDX", "name": "Фонд", "asset_type": "fund", "sector": "funds",
                                 "value_rub": 200000.0, "is_blocked": False})
        inp = Inputs(d, snap)
        frac = {f: 0.0 for f in sj.CANONICAL_FACTORS}
        frac["sanctions"], frac["geopol"] = 0.05, 0.04  # дробные политические беты (шкала 0..1 вместо −1..+1)
        pr = {"factor_betas": frac, "factor_betas_method": "тест", "factor_betas_r2": None}
        results = {}
        for at in (None, "fund_equity", "bond_fund"):
            p = copy.deepcopy(inp.priors)
            p["FUNDX"] = copy.deepcopy(pr)
            if at:
                p["FUNDX"]["asset_type"] = at
            inp.write("priors.json", p, json_=True)
            results[at] = inp.cli(out="at.yaml")
        ok = True
        outcomes = {k: v.returncode for k, v in results.items()}
        ok &= check("asset_type влияет на расчёт (исход зависит от класса)", len(set(outcomes.values())) > 1
                    or results["bond_fund"].stderr != results["fund_equity"].stderr, str(outcomes))
        ok &= check("bond_fund проходит гард шкалы", results["bond_fund"].returncode == 0, results["bond_fund"].stderr)
        ok &= check("fund_equity с дробными политическими бетами — отказ", results["fund_equity"].returncode == 1,
                    results["fund_equity"].stderr)
        j = sj.extract({**inp.full, "per_position": {"T": {"factor_betas": {}, "asset_type": "bond_fund"}}})
        ok &= check("PRIOR_KEYS знает asset_type, extract не ломается", j["priors"]["T"].get("asset_type") == "bond_fund")
        return ok


def test_horizons_from():
    """Сроки прошлого стресса переносятся как есть: метки, даты, основной горизонт, режим."""
    with tempfile.TemporaryDirectory() as td:
        inp = Inputs(Path(td), tsr.snapshot())
        prev = {"horizons": [6, 12], "horizon_ends": {"h6": "2026-12-31", "h12": "2027-06-30"},
                "primary_horizon": 6, "horizon_mode": "rolling"}
        inp.write("prev.yaml", prev)
        base = [sys.executable, str(BUILD), "--snapshot", str(inp.d / "snap.json"),
                "--scenarios", str(inp.d / "ssot.yaml"), "--macro-scenarios", str(inp.d / "macro.yaml"),
                "--priors", str(inp.d / "priors.json"), "--horizon-factors", str(inp.d / "hf.json"),
                "--fill", str(inp.d / "fill.yaml"), "--slug", "t", "--include-ev", "--today", TODAY,
                "--output", str(inp.d / "hfrom.yaml")]
        r = subprocess.run(base + ["--horizons-from", str(inp.d / "prev.yaml")], capture_output=True, text=True)
        ok = check("код 0", r.returncode == 0, r.stderr[-400:])
        out = load(inp.d / "hfrom.yaml") if r.returncode == 0 else {}
        ok &= check("метки и даты как в прошлом файле", out.get("horizon_ends") == prev["horizon_ends"]
                    and out.get("horizons") == [6, 12], str(out.get("horizon_ends")))
        ok &= check("основной горизонт перенесён, режим — anchored (даты фиксированы, метка — конвенция)",
                    out.get("primary_horizon") == 6 and out.get("horizon_mode") == "anchored",
                    f"{out.get('primary_horizon')} {out.get('horizon_mode')}")
        r = subprocess.run(base + ["--horizons-from", str(inp.d / "prev.yaml"), "--primary-horizon", "12"],
                           capture_output=True, text=True)
        ok &= check("явный --primary-horizon сильнее прошлого файла",
                    r.returncode == 0 and load(inp.d / "hfrom.yaml").get("primary_horizon") == 12, r.stderr[-300:])
        r = subprocess.run(base + ["--horizons-from", str(inp.d / "prev.yaml"), "--horizons", "6,12"],
                           capture_output=True, text=True)
        ok &= check("вместе с --horizons — отказ", r.returncode == 1 and "--horizons-from" in r.stderr, r.stderr[-300:])
        # правило сдвига: до ближайшего срока меньше 3 месяцев — все сроки уходят на 6 месяцев вперёд
        e0 = {"h6": "2027-03-31", "h12": "2027-09-30", "h24": "2028-09-30"}
        ok &= check("ровно 3 месяца до ближайшего срока — сроки прежние", sb.shift_horizons(e0, "2026-12-31") == (e0, 0))
        got, n = sb.shift_horizons(e0, "2027-01-01")
        ok &= check("меньше 3 месяцев — сдвиг на 6 месяцев, концы месяцев",
                    n == 1 and got == {"h6": "2027-09-30", "h12": "2028-03-31", "h24": "2029-03-31"}, f"{n} {got}")
        got, n = sb.shift_horizons(e0, "2027-08-15")
        ok &= check("долгий перерыв — сдвиг дважды", n == 2 and got["h6"] == "2028-03-31", f"{n} {got}")
        inp.write("near.yaml", {"horizons": [6, 12], "horizon_ends": {"h6": "2026-07-31", "h12": "2027-01-31"},
                                "primary_horizon": 12, "horizon_mode": "rolling"})
        r = subprocess.run(base + ["--horizons-from", str(inp.d / "near.yaml")], capture_output=True, text=True)
        out = load(inp.d / "hfrom.yaml") if r.returncode == 0 else {}
        ok &= check("команда: сроки сдвинуты и об этом сказано",
                    r.returncode == 0 and out.get("horizon_ends") == {"h6": "2027-01-31", "h12": "2027-07-31"}
                    and "сроки сдвинуты на 6 мес" in r.stdout, f"{out.get('horizon_ends')} {r.stderr[-300:]}")
        inp.write("bad.yaml", {"primary_horizon": 6})
        r = subprocess.run(base + ["--horizons-from", str(inp.d / "bad.yaml")], capture_output=True, text=True)
        ok &= check("прошлый файл без horizon_ends — отказ", r.returncode == 1 and "horizon_ends" in r.stderr, r.stderr[-300:])
        return ok


# ── факторы из сетки дат макро-файла ──
def _lv(v):
    return {"value": v}


def grid_macro() -> dict:
    """Макро-файл стенда: сетка 2026-09-30 / 2027-03-31; срок h6 (2026-11-30) внутри, h12 (2027-05-31) — позже сетки."""
    def g(a, b):
        return {"2026-09-30": _lv(a), "2027-03-31": _lv(b)}
    return {
        "baseline_spot": {"brent_usd": 70, "usdrub": 80, "cnyrub": 11, "cbr_rate_pct": 14, "xauusd_usd": 3000,
                          "brent_price": 70, "usdrub_rate": 80, "cnyrub_rate": 11, "cbr_rate": 14, "xauusd_price": 3000},
        "factors": {
            "brent_price": {"by_scenario": {"A": g(75, 85), "B": g(65, 55)}},
            "usdrub_rate": {"by_scenario": {"A": g(84, 88), "B": g(76, 72)}},
            "cnyrub_rate": {"by_scenario": {"A": g(11.5, 12), "B": g(10.5, 10)}},
            "cbr_rate": {"by_scenario": {"A": g(13, 12), "B": g(15, 16)}},
            "xauusd_price": {"level_all_scenarios": g(3300, 3600)},
        },
    }


POL = {"A": {"sanctions": {"h6": 0.5, "h12": 0.6}, "geopol": {"h6": 0.1, "h12": 0.2}},
       "B": {"sanctions": {"h6": -0.5, "h12": -0.6}, "geopol": {"h6": -0.1, "h12": -0.2}}}
SPOT = {"brent": 70, "usdrub": 80, "cnyrub": 11, "cbr_rate": 14, "xauusd": 3000}
KIND = {"cbr_rate": "pp"}


def expected_hf() -> dict:
    """Эквивалентный готовый --horizon-factors: те же правила, посчитаны здесь независимо от скрипта."""
    from datetime import date as D
    import math
    g = grid_macro()
    names = {"brent": "brent_price", "usdrub": "usdrub_rate", "cnyrub": "cnyrub_rate", "cbr_rate": "cbr_rate",
             "xauusd": "xauusd_price"}
    ends = {"h6": D(2026, 11, 30), "h12": D(2027, 5, 31)}
    d0, d1, as_of = D(2026, 9, 30), D(2027, 3, 31), D(2026, 6, 1)
    fbh = {s: {h: {} for h in ends} for s in "AB"}
    for s in "AB":
        for f, m in names.items():
            node = g["factors"][m]
            grid = node["level_all_scenarios"] if "level_all_scenarios" in node else node["by_scenario"][s]
            a, b = grid["2026-09-30"]["value"], grid["2027-03-31"]["value"]
            lv = {"h6": a + (b - a) * (ends["h6"] - d0).days / (d1 - d0).days, "h12": b}
            for h in ends:
                fbh[s][h][f] = round(lv[h] - SPOT[f] if f == "cbr_rate" else (lv[h] - SPOT[f]) / SPOT[f] * 100, 4)
                fbh[s][h].update({k: POL[s][k][h] for k in ("sanctions", "geopol")})
    ci = round(math.sqrt((ends["h12"] - as_of).days / (d1 - as_of).days), 4)
    cov = {"h6": {"status": "covered", "ci_inflation": 1.0, "warnings": [], "target_date": "2026-11-30"},
           "h12": {"status": "extrapolated", "ci_inflation": ci, "target_date": "2027-05-31",
                   "warnings": [f"{f}: сетка прогноза заканчивается 2027-03-31, горизонт 2027-05-31 — flat hold (×{ci} CI)"
                                for f in names]}}
    return {"factors_by_horizon": fbh, "horizon_coverage": cov}


def grid_inputs(td) -> Inputs:
    inp = Inputs(Path(td), tsr.snapshot())
    inp.write("macro.yaml", grid_macro())
    inp.write("polprev.yaml", {"scenarios": {s: {"factors_by_horizon": {h: {"sanctions": POL[s]["sanctions"][h],
                                                                             "geopol": POL[s]["geopol"][h], "brent": 1.0}
                                                                         for h in ("h6", "h12")}} for s in "AB"}})
    inp.write("polpaths.json", POL, json_=True)
    inp.write("hfeq.json", expected_hf(), json_=True)
    return inp


def test_macro_grid_mode():
    with tempfile.TemporaryDirectory() as td:
        inp = grid_inputs(td)
        r0 = inp.cli(hf=("--horizon-factors", "hfeq.json"), out="eq.yaml")
        r1 = inp.cli(hf=None, out="pf.yaml", extra=["--political-from", str(inp.d / "polprev.yaml")])
        r2 = inp.cli(hf=None, out="pp.yaml", extra=["--political-paths", str(inp.d / "polpaths.json"), "--json"])
        ok = check("коды 0 (готовый hf / --political-from / --political-paths)",
                   (r0.returncode, r1.returncode, r2.returncode) == (0, 0, 0), r0.stderr + r1.stderr + r2.stderr)
        eq, pf, pp = load(inp.d / "eq.yaml"), load(inp.d / "pf.yaml"), load(inp.d / "pp.yaml")
        ok &= check("режим сетки = эквивалентный готовый --horizon-factors (весь файл)", pf == eq and pp == eq)
        ok &= check("brent A h6 = (75+10·61/182−70)/70·100", abs(pf["scenarios"]["A"]["factors_by_horizon"]["h6"]["brent"]
                                                               - round((75 + 10 * 61 / 182 - 70) / 70 * 100, 4)) < 1e-9)
        ok &= check("политические факторы из прошлого файла как есть, лишнее (brent) не берётся",
                    pf["scenarios"]["A"]["factors_by_horizon"]["h12"]["sanctions"] == 0.6)
        ok &= check("flat hold: coverage h12 extrapolated, ci > 1",
                    pf["horizon_coverage"]["h12"]["status"] == "extrapolated" and pf["horizon_coverage"]["h12"]["ci_inflation"] > 1)
        ok &= check("сводка: источники факторов названы файлами",
                    "сетка дат macro.yaml" in r1.stdout and "--political-from polprev.yaml" in r1.stdout, r1.stdout[-500:])
        info = json.loads(r2.stdout)
        ok &= check("--json: factor_sources", info["factor_sources"] == {"numeric": "сетка дат macro.yaml",
                                                                         "political": "--political-paths polpaths.json"})
        ok &= check("--json: предупреждения flat hold в сводке",
                    any("flat hold" in w for w in info["warnings"]), str(info["warnings"]))
        r3 = inp.cli(hf=("--horizon-factors", "hfeq.json"), out="eq2.yaml")
        ok &= check("прежний режим: источник — --horizon-factors hfeq.json",
                    "--horizon-factors hfeq.json" in r3.stdout, r3.stdout[-300:])
        return ok


def test_macro_grid_refusals():
    with tempfile.TemporaryDirectory() as td:
        inp = grid_inputs(td)
        pf, pp = ["--political-from", str(inp.d / "polprev.yaml")], ["--political-paths", str(inp.d / "polpaths.json")]

        def run(extra, label, want, hf=None, code=1):
            r = inp.cli(hf=hf, out="x.yaml", extra=extra)
            good = r.returncode == code and all(w in r.stderr for w in want) and not (inp.d / "x.yaml").exists()
            return check(label, good, f"код {r.returncode}: {r.stderr[-400:]}")

        ok = run([], "нет источника политических", ["--political-from", "--political-paths"])
        ok &= run(pf + pp, "оба источника политических", ["ровно один"])
        ok &= run(pf, "политические вместе с готовым hf", ["только в режиме"], hf=("--horizon-factors", "hfeq.json"))
        inp.write("prev_bad.yaml", {"scenarios": {"A": {"factors_by_horizon": {"h6": {"sanctions": 0, "geopol": 0},
                                                                               "h24": {"sanctions": 0, "geopol": 0}}}}})
        ok &= run(["--political-from", str(inp.d / "prev_bad.yaml")], "прошлый стресс: нет сценария B и не те сроки",
                  ["сценарии", "не совпадают со сроками"])
        # смена матрицы: суждения и макро-файл, привязанные к другой матрице, не переносятся
        prev_ok = yaml.safe_load((inp.d / "polprev.yaml").read_text(encoding="utf-8"))
        inp.write("prev_other.yaml", {**prev_ok, "scenario_matrix_ref": "scenarios/other-matrix-2026-07-01.yaml"})
        ok &= run(["--political-from", str(inp.d / "prev_other.yaml")], "политические пути другой матрицы — отказ",
                  ["матрица сценариев сменилась", "other-matrix-2026-07-01", "--political-paths"])
        inp.write("prev_same.yaml", {**prev_ok, "scenario_matrix_ref": "scenarios/ssot.yaml"})
        r_same = inp.cli(hf=None, out="same.yaml", extra=["--political-from", str(inp.d / "prev_same.yaml")])
        ok &= check("политические пути той же матрицы — код 0", r_same.returncode == 0, r_same.stderr[-300:])
        m_other = grid_macro()
        m_other["scenario_matrix"] = {"source_file": "scenarios/other-matrix-2026-07-01.yaml"}
        inp.write("macro.yaml", m_other)
        ok &= run(pp, "макро-файл другой матрицы — отказ", ["матрица сценариев сменилась", "/macro-forecast-chain"])
        inp.write("macro.yaml", grid_macro())
        bad = copy.deepcopy(POL)
        bad["A"]["sanctions"]["h12"] = 1.5
        del bad["B"]["geopol"]
        inp.write("pp_bad.json", bad, json_=True)
        ok &= run(["--political-paths", str(inp.d / "pp_bad.json")], "paths: значение вне [-1, 1] и нет фактора",
                  ["A.sanctions.h12", "вне [-1, 1]", "B.geopol"])
        part = {"A": POL["A"]}
        inp.write("pp_part.json", part, json_=True)
        ok &= run(["--political-paths", str(inp.d / "pp_part.json")], "paths: нет сценария B", ["B: нет сценария"])
        m = grid_macro()
        del m["factors"]["usdrub_rate"]
        del m["factors"]["brent_price"]["by_scenario"]["B"]
        inp.write("macro.yaml", m)
        ok &= run(pf, "битый макро-файл: перечень одним списком", ["ОТКАЗ", "usdrub_rate", "brent_price, сценарий B"])
        return ok


# ── Чувствительности: перенос, справочник позиций, фиксированные (06.11.2026) ──
REFS = REPO / "skills/portfolio-scenario-stress/references"


def _fb(**kw) -> dict:
    return {**{f: 0.0 for f in sj.CANONICAL_FACTORS}, **kw}


def _strip_method(tree: dict) -> dict:
    t = copy.deepcopy(tree)
    for v in t["per_position"].values():
        v.pop("factor_betas_method", None)
    return t


def _same_numbers(a: dict, b: dict, label: str) -> bool:
    return same_calc(_strip_method(a), _strip_method(b), label)


def _finamar_snap() -> dict:
    snap = tsr.snapshot()
    snap["holdings"].append({"ticker": "FINAMAR", "name": "Финам — Алгоритм роста", "asset_type": "fund",
                             "sector": "funds", "value_rub": 300000.0, "is_blocked": False})
    return snap


def test_asset_type_in_per_position():
    with tempfile.TemporaryDirectory() as td:
        inp = Inputs(Path(td), tsr.snapshot())
        pp = inp.full["per_position"]
        ok = check("asset_type записан в каждую запись per_position (класс снапшота)",
                   all(v.get("asset_type") == "stock" for v in pp.values()), str({t: v.get("asset_type") for t, v in pp.items()}))
        p = copy.deepcopy(inp.priors)
        p["TICK1"]["asset_type"] = "fund_equity"
        inp.write("priors.json", p, json_=True)
        r = inp.cli(out="at.yaml")
        out = load(inp.d / "at.yaml")
        ok &= check("значение из priors приоритетнее снапшота", r.returncode == 0
                    and out["per_position"]["TICK1"]["asset_type"] == "fund_equity"
                    and out["per_position"]["TICK2"]["asset_type"] == "stock", r.stderr)
        j, ctx = sr.inputs_from_stress(out)
        ok &= check("extract поднимает asset_type в priors", j["priors"]["TICK1"]["asset_type"] == "fund_equity")
        tree, _ = sr.recalc(j, inp.snap, source_name="x", source_kind="stress", ctx=ctx, weights=None,
                            weights_name=None, today=out["date"], at="2026-06-01T10:00:00+03:00")
        ok &= check("круг extract -> recalc: числа те же, поле на месте",
                    tree["per_position"]["TICK1"]["asset_type"] == "fund_equity"
                    and all(tree["scenarios"][s]["portfolio_level_by_horizon"] == out["scenarios"][s]["portfolio_level_by_horizon"]
                            for s in "AB"))
        old = copy.deepcopy(inp.full)
        for v in old["per_position"].values():
            v.pop("asset_type", None)
        j2, ctx2 = sr.inputs_from_stress(old)
        tree2, _ = sr.recalc(j2, inp.snap, source_name="x", source_kind="stress", ctx=ctx2, weights=None,
                             weights_name=None, today=old["date"], at="2026-06-01T10:00:00+03:00")
        ok &= same_calc(tree2, reference(inp), "старый файл без asset_type")
        return ok


def test_priors_from():
    with tempfile.TemporaryDirectory() as td:
        inp = Inputs(Path(td), tsr.snapshot())
        past = inp.full_path
        stem = past.stem
        r = inp.cli(priors=None, extra=["--priors-from", str(past), "--json"], out="a.yaml")
        ok = check("--priors-from без --priors: код 0", r.returncode == 0, r.stderr)
        out = load(inp.d / "a.yaml")
        ok &= _same_numbers(out, reference(inp), "перенос = полный --priors")
        info = json.loads(r.stdout)["priors"]
        ok &= check("сводка: перенесено 2, новых 0, изменено 0", info["carried"] == 2 and info["new"] == [] and info["changed"] == [],
                    str(info))
        ok &= check("метод: reused from <файл без расширения> | исходный",
                    out["per_position"]["TICK1"]["factor_betas_method"] == f"reused from {stem} | тест-prior",
                    out["per_position"]["TICK1"]["factor_betas_method"])
        r1 = inp.cli(priors=None, extra=["--priors-from", str(past)], out="a2.yaml")
        ok &= check("текстовая сводка «чувствительности: перенесено 2 из …, новых 0, изменено 0»",
                    f"чувствительности: перенесено 2 из {stem}, новых 0, изменено 0" in r1.stdout, r1.stdout)
        r2 = inp.cli(priors=None, extra=["--priors-from", str(inp.d / "a.yaml")], out="b.yaml")
        m = load(inp.d / "b.yaml")["per_position"]["TICK1"]["factor_betas_method"]
        ok &= check("второй перенос: префикс не удваивается", r2.returncode == 0 and m == "reused from a | тест-prior", m)
        r = inp.cli(priors=None, out="x.yaml")
        ok &= check("ни --priors, ни --priors-from: код 2", r.returncode == 2, str(r.returncode))
        # новая бумага
        snap3 = tsr.snapshot(with_t3=True)
        inp.write("snap3.json", snap3, json_=True)
        r = inp.cli(snap="snap3.json", priors=None, extra=["--priors-from", str(past)], out="x.yaml")
        ok &= check("новая бумага без записи: отказ с перечнем", r.returncode == 1 and "TICK3" in r.stderr and "Три" in r.stderr
                    and not (inp.d / "x.yaml").exists(), r.stderr)
        new3 = {"TICK3": {"factor_betas": _fb(brent=0.3), "factor_betas_method": "новый", "factor_betas_r2": None}}
        inp.write("new.json", new3, json_=True)
        r = inp.cli(snap="snap3.json", priors="new.json", extra=["--priors-from", str(past), "--json"], out="n.yaml")
        info = json.loads(r.stdout)["priors"] if r.returncode == 0 else {}
        ok &= check("запись в --priors: новых 1 (TICK3), метод не меняется",
                    r.returncode == 0 and info["new"] == ["TICK3"] and info["carried"] == 2 and info["changed"] == []
                    and load(inp.d / "n.yaml")["per_position"]["TICK3"]["factor_betas_method"] == "новый", r.stderr)
        # пересмотренная запись заменяет перенесённую целиком
        rev = {"TICK1": {"factor_betas": _fb(brent=0.9), "factor_betas_method": "пересмотр", "factor_betas_r2": None}}
        inp.write("rev.json", rev, json_=True)
        r = inp.cli(priors="rev.json", extra=["--priors-from", str(past), "--json"], out="c.yaml")
        info = json.loads(r.stdout)["priors"] if r.returncode == 0 else {}
        pos = load(inp.d / "c.yaml")["per_position"]["TICK1"] if r.returncode == 0 else {}
        ok &= check("пересмотр: изменено 1, перенесено 1, запись заменена целиком (позиции нет, метод свой)",
                    info.get("changed") == ["TICK1"] and info.get("carried") == 1 and pos.get("factor_betas_method") == "пересмотр"
                    and "sanctions_position" not in pos and pos["factor_betas"]["brent"] == 0.9, r.stderr + str(pos)[:200])
        # перенесённая бумага ушла из снапшота
        inp.write("snap1.json", tsr.snapshot(with_t2=False), json_=True)
        r = inp.cli(snap="snap1.json", priors=None, extra=["--priors-from", str(past), "--json"], out="g.yaml")
        info = json.loads(r.stdout)["priors"] if r.returncode == 0 else {}
        ok &= check("бумаги нет в снапшоте: числом, не предупреждением",
                    r.returncode == 0 and info["carried_gone"] == 1 and info["carried"] == 1
                    and not any("TICK2" in w for w in json.loads(r.stdout)["warnings"]), r.stderr)
        return ok


def test_sanctions_positions_reference():
    ref = yaml.safe_load((REFS / "sanctions-positions.yaml").read_text(encoding="utf-8"))["positions"]
    val = ref["SBER"]["position"]
    with tempfile.TemporaryDirectory() as td:
        snap = tsr.snapshot()
        snap["holdings"].append({"ticker": "SBER", "name": "Сбер", "asset_type": "stock", "sector": "banks_finance",
                                 "value_rub": 200000.0, "is_blocked": False})
        inp = Inputs(Path(td), tsr.snapshot())
        p = copy.deepcopy(inp.priors)
        p["SBER"] = {"factor_betas": _fb(brent=0.1), "factor_betas_method": "тест", "factor_betas_r2": None,
                     "sanctions_position": 0.3}
        inp.write("snap.json", snap, json_=True)
        inp.write("priors.json", p, json_=True)
        r = inp.cli(out="s.yaml", extra=["--json"])
        ok = check("код 0", r.returncode == 0, r.stderr)
        pp = load(inp.d / "s.yaml")["per_position"]
        warns = json.loads(r.stdout)["warnings"] if r.returncode == 0 else []
        ok &= check("позиция бумаги из справочника сильнее входа", pp["SBER"]["sanctions_position"] == val, str(pp["SBER"]))
        ok &= check("расхождение в предупреждениях: «SBER: было 0.3, по справочнику …»",
                    any(f"SBER: было 0.3, по справочнику {val}" in w for w in warns), str(warns))
        ok &= check("бумага вне справочника не тронута", pp["TICK1"]["sanctions_position"] == 0.3
                    and not any("TICK1:" in w and "справочник" in w for w in warns))
        return ok


def test_fixed_priors():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        inp = Inputs(d, tsr.snapshot())
        snap = _finamar_snap()
        inp.write("snap.json", snap, json_=True)
        noisy = {f: 0.0 for f in sj.CANONICAL_FACTORS}
        noisy["usdrub"], noisy["brent"] = 0.8, 0.5
        past_pp = copy.deepcopy(inp.full)
        past_pp["per_position"]["FINAMAR"] = {"factor_betas": noisy, "factor_betas_method": "модель", "factor_betas_r2": None,
                                              "asset_type": "fund_equity"}
        inp.write("past.yaml", past_pp)
        p = copy.deepcopy(inp.priors)
        p["FINAMAR"] = {"factor_betas": noisy, "factor_betas_method": "модель", "factor_betas_r2": None, "asset_type": "fund_equity"}
        inp.write("priors.json", p, json_=True)
        r = inp.cli(out="f.yaml", extra=["--json"])
        ok = check("код 0", r.returncode == 0, r.stderr)
        out = load(d / "f.yaml")
        fp = out["per_position"]["FINAMAR"]
        warns = json.loads(r.stdout)["warnings"]
        ok &= check("беты нулевые, метод из справочника, класс fund_algo",
                    all(v == 0 for v in fp["factor_betas"].values()) and set(fp["factor_betas"]) == set(sj.CANONICAL_FACTORS)
                    and "нечувствительна" in fp["factor_betas_method"] and fp["asset_type"] == "fund_algo", str(fp)[:300])
        ok &= check("--priors: предупреждение «проигнорировано» с тикером",
                    any("проигнорировано" in w and "FINAMAR" in w for w in warns), str(warns))
        cells = [c for h in fp["by_horizon"].values() for c in h["delta_pct_by_scenario"].values()]
        vals = [c.get("value") if isinstance(c, dict) else c for c in cells]
        ok &= check("дельты нулевые на всех сроках и сценариях", vals and all(v == 0 for v in vals), str(vals))
        ok &= check("macro_blindspot ставится", fp.get("macro_blindspot") is True, str(fp.get("macro_blindspot_reason")))
        bc = json.dumps(out["bond_carry"], ensure_ascii=False)
        ok &= check("купонного дохода нет (в bond_carry тикера нет)", "FINAMAR" not in bc)
        ok &= check("сектор algo_strategies с подписью, доля фонда в разбивке",
                    "Алгоритмические стратегии" in json.dumps(out["sector_breakdown_pct"], ensure_ascii=False)
                    and "Фонды акций" not in json.dumps(out["sector_breakdown_pct"], ensure_ascii=False),
                    json.dumps(out["sector_breakdown_pct"], ensure_ascii=False)[:300])
        # сильнее переноса
        r = inp.cli(priors=None, out="f2.yaml", extra=["--priors-from", str(d / "past.yaml"), "--json"])
        info = json.loads(r.stdout)["priors"] if r.returncode == 0 else {}
        fp2 = load(d / "f2.yaml")["per_position"]["FINAMAR"] if r.returncode == 0 else {}
        ok &= check("сильнее переноса: беты нулевые, в сводке fixed; перенесено 2",
                    r.returncode == 0 and info["fixed"] == ["FINAMAR"] and info["carried"] == 2
                    and all(v == 0 for v in fp2["factor_betas"].values()), r.stderr)
        # без FINAMAR в снапшоте — молча
        inp.write("priors.json", inp.priors, json_=True)
        r = inp.cli(snap="snap0.json", out="f3.yaml", extra=["--json"])
        ok &= check("бумаги нет в снапшоте: тихо пропущена",
                    r.returncode == 0 and not any("FINAMAR" in w for w in json.loads(r.stdout)["warnings"]), r.stderr)
        # битые файлы
        base = yaml.safe_load((REFS / "fixed-priors.yaml").read_text(encoding="utf-8"))

        def broken(mut, label, want):
            doc = copy.deepcopy(base)
            mut(doc)
            f = d / "fx.yaml"
            f.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
            try:
                sb.load_fixed_priors(f)
            except sb.BuildError as e:
                return check(f"битый fixed-priors ({label}): отказ", want in str(e), str(e))
            return check(f"битый fixed-priors ({label}): отказ", False, "принят")
        ok &= broken(lambda x: x["fixed"]["FINAMAR"]["factor_betas"].pop("brent"), "нет фактора", "brent")
        ok &= broken(lambda x: x["fixed"]["FINAMAR"]["factor_betas"].update(usdrub="много"), "нечисловое", "usdrub")
        ok &= broken(lambda x: x["fixed"]["FINAMAR"].update(лишнее=1), "лишний ключ", "лишний ключ")
        ok &= broken(lambda x: x.update(schema_version=2), "версия схемы", "schema_version")
        ok &= broken(lambda x: x["fixed"]["FINAMAR"].pop("asset_type"), "нет asset_type", "asset_type")
        try:
            sb.load_fixed_priors(d / "нет.yaml")
            ok &= check("нет файла: отказ", False)
        except sb.BuildError:
            ok &= check("нет файла: отказ", True)
        return ok


def test_fixed_priors_real_file():
    fx = sb.load_fixed_priors(REFS / "fixed-priors.yaml")
    f = fx.get("FINAMAR", {})
    groups = yaml.safe_load((REFS / "sector-groups.yaml").read_text(encoding="utf-8"))
    ok = check("файл читается, FINAMAR на месте, 7 нулевых факторов",
               set(f.get("factor_betas", {})) == set(sj.CANONICAL_FACTORS) and all(v == 0 for v in f["factor_betas"].values()))
    ok &= check("класс не денежный рынок и не облигационный (купонный слой не начисляет)",
                "money" not in f["asset_type"] and "bond" not in f["asset_type"] and "FINAMAR" not in sb.cbc.MONEY_MARKET_TICKERS)
    ok &= check("группа сектора есть в sector-groups.yaml, фонд сопоставлен",
                f["sector_group"] in groups["groups"] and groups["funds"]["FINAMAR"] == f["sector_group"])
    return ok



# ---------- --tables: таблицы отчёта из дерева результата ----------
import re  # noqa: E402


def _num(txt: str) -> float | None:
    """Снять форматирование: «−512 792» -> -512792, «−3,37%» -> -3.37, «—» -> None."""
    t = txt.replace("*", "").replace("\u2212", "-").replace(" ", "").replace("%", "").replace(",", ".").strip()
    return None if t in ("—", "") else float(t)


def _blocks(md: str) -> dict[str, list[list[str]]]:
    """{заголовок ##: строки таблиц (ячейки), без шапки и разделителя}."""
    out: dict[str, list[list[str]]] = {}
    cur = None
    for line in md.splitlines():
        if line.startswith("## "):
            cur = line[3:]
            out[cur] = []
        elif cur is not None and line.startswith("|") and not re.match(r"^\|[-|]+\|$", line):
            out[cur].append([c.strip() for c in line.strip("|").split("|")])
    return out


def _find(blocks: dict, start: str) -> list[list[str]]:
    return next(v for k, v in blocks.items() if k.startswith(start))


def test_tables():
    with tempfile.TemporaryDirectory() as td:
        inp = Inputs(Path(td), tsr.snapshot(with_t3=True))
        pri = json.loads((inp.d / "priors.json").read_text(encoding="utf-8"))
        pri["TICK3"] = copy.deepcopy(pri["TICK2"])
        inp.write("priors.json", pri, json_=True)
        ok = True
        for fill in (True, False):
            lab = "итоговый" if fill else "только числа"
            r = inp.cli(fill=fill, extra=["--tables", str(inp.d / "t.md")])
            ok &= check(f"{lab}: код 0, файл таблиц записан", r.returncode == 0 and (inp.d / "t.md").is_file(), r.stderr)
            md = (inp.d / "t.md").read_text(encoding="utf-8")
            out = load(inp.d / "out.yaml")
            bl = _blocks(md)
            heads = list(bl)
            for pref in ("Итоги портфеля", "Позиция × сценарий", "Секторальная", "Top-5 уязвимых", "Top-5 выигрывающих",
                         "Концентрация", "Портфельные метрики", "Покрытие сроков", "Купонный слой"):
                ok &= check(f"{lab}: блок «{pref}»", any(h.startswith(pref) for h in heads), str(heads))
            if fill:
                ok &= check("итоговый: концентрация — таблица",
                            len(_find(bl, "Концентрация")) >= 5 and "не посчитана" not in md)
            else:
                ok &= check("только числа: концентрация заменена пояснением",
                            _find(bl, "Концентрация") == [] and "Концентрация не посчитана" in md)
            ph = f"h{out['primary_horizon']}"
            sids = list(out["scenarios"])
            hks = list(out["horizon_ends"])
            # итоги: все ячейки обеих баз
            rows_t = [x for x in _find(bl, "Итоги портфеля") if x[0] != "Сценарий"]
            it = iter(rows_t)
            ok_t = True

            def _cell(cell):
                m = re.match(r"^(\S.*?) \((.*)\)$", cell)
                return _num(m.group(1)), _num(m.group(2))
            for basis, key in (("price", "price_delta"), ("total_return", "total_return")):
                for sid in sids:
                    row = next(it)
                    ok_t &= row[0].startswith(sid + " ")
                    for hk, cell in zip(hks, row[1:]):
                        cr, cp = _cell(cell)
                        pl = out["scenarios"][sid]["portfolio_level_by_horizon"][hk]
                        ok_t &= cr == pl[key + "_rub"] and abs(cp - pl[key + "_pct"]) <= 0.0051
                ag = out["portfolio_aggregates"][basis]
                if any(v is not None for v in ag["expected_pl_rub_by_horizon"].values()):
                    ex = next(it)
                    ok_t &= ex[0].startswith("**Ожидание")
                    for hk, cell in zip(hks, ex[1:]):
                        cr, cp = _cell(cell)
                        ok_t &= cr == ag["expected_pl_rub_by_horizon"][hk] \
                            and abs(cp - ag["expected_pl_pct_by_horizon"][hk]) <= 0.0051
            ok_t &= next(it, None) is None
            ok &= check(f"{lab}: итоги портфеля (все ячейки, обе базы, ожидание) = дерево", ok_t)
            # позиция × сценарий
            prow = _find(bl, "Позиция × сценарий")
            body = [x for x in prow[1:] if not x[0].startswith("**")] if prow and prow[0][0] == "Тикер" else \
                [x for x in prow if not x[0].startswith("**") and x[0] != "Тикер"]
            pp = out["per_position"]
            ok &= check(f"{lab}: число строк = число бумаг ({len(pp)})", len(body) == len(pp), f"{len(body)}")
            weights = [_num(x[2]) for x in body]
            ok &= check(f"{lab}: сортировка по доле по убыванию", weights == sorted(weights, reverse=True))
            ok_p = True
            sums = {s: 0 for s in sids}
            for x in body:
                p = pp[x[0]]
                ok_p &= abs(_num(x[2]) - p["weight_pct"]) <= 0.0051
                for i, s in enumerate(sids):
                    d = p["by_horizon"][ph]["delta_pct_by_scenario"][s]["value"]
                    ok_p &= abs(_num(x[3 + 2 * i]) - d) <= 0.0051
                    sums[s] += _num(x[4 + 2 * i])
            ok &= check(f"{lab}: позиции: доля и Δ% = дерево", ok_p)
            # Δ₽ позиции = то, что считает compute_derived_fields (top_risks / сектора) — до рубля
            tr = {(x["ticker"], x["scenario"]): x["price_delta_rub"] for x in out["top_risks"] + out["top_resilient"]
                  if x["horizon"] == ph}
            ok_r = True
            for x in body:
                for i, s in enumerate(sids):
                    if (x[0], s) in tr:
                        ok_r &= _num(x[4 + 2 * i]) == tr[(x[0], s)]
            ok &= check(f"{lab}: Δ₽ бумаг = top_risks/top_resilient до рубля", ok_r and bool(tr))
            for s in sids:
                pl = out["scenarios"][s]["portfolio_level_by_horizon"][ph]["price_delta_rub"]
                ok &= check(f"{lab}: Σ Δ₽ бумаг в {s} = портфельному (±{len(pp)} ₽)", abs(sums[s] - pl) <= len(pp),
                            f"{sums[s]} vs {pl}")
            # итоговая строка таблицы позиций
            totrow = next(x for x in prow if x[0].startswith("**Итого"))
            ok &= check(f"{lab}: итоговая строка = Σ строк",
                        all(_num(totrow[4 + 2 * i]) == sums[s] for i, s in enumerate(sids)))
            # секторы
            sec = [x for x in _find(bl, "Секторальная") if x[0] != "Сектор"]
            sbp = out["sector_breakdown_pct"]
            ok_s = len(sec) == len(sbp)
            for x in sec:
                v = next(v for v in sbp.values() if v["label_ru"] == x[0])
                ok_s &= abs(_num(x[1]) - v["weight_pct"]) <= 0.0051
                ok_s &= all(_num(x[2 + i]) == v["price_delta_rub_by_horizon"][ph][s] for i, s in enumerate(sids))
            ok &= check(f"{lab}: секторы = sector_breakdown_pct", ok_s)
            # Top-5
            for pref, key in (("Top-5 уязвимых", "top_risks"), ("Top-5 выигрывающих", "top_resilient")):
                rows = [x for x in _find(bl, pref) if x[0] != "#"]
                want = [x for x in out[key] if x["horizon"] == ph]
                good = len(rows) == len(want) and all(
                    r_[1] == w_["ticker"] and _num(r_[5]) == w_["price_delta_rub"]
                    and abs(_num(r_[4]) - w_["delta_pct"]) <= 0.0051 for r_, w_ in zip(rows, want))
                ok &= check(f"{lab}: {pref} = {key} дерева", good and bool(want))
            # сводка команды = top_risks до рубля
            info = json.loads(inp.cli(fill=fill, out="o3.yaml", extra=["--json"]).stdout)
            want = [x for x in out["top_risks"] if x["horizon"] == ph]
            got = info["top_losers"]
            ok &= check(f"{lab}: сводка «Топ-5» = top_risks до рубля",
                        [(g["ticker"], g["rub"]) for g in got] == [(w["ticker"], w["price_delta_rub"]) for w in want]
                        and bool(got), f"{got} vs {want}")
            r2 = inp.cli(fill=fill, out="o3.yaml")
            line = next(x for x in r2.stdout.splitlines() if x.startswith("Топ-5 бумаг"))
            ok &= check(f"{lab}: текстовая сводка несёт рубли top_risks",
                        all(f"{w['ticker']} {w['price_delta_rub']:,} ₽" in line for w in want), line)
            # остальные блоки
            cov = [x for x in _find(bl, "Покрытие") if x[0] != "Срок"]
            ok &= check(f"{lab}: покрытие сроков", [(x[0], x[1], x[2], _num(x[3])) for x in cov] ==
                        [(hk, out["horizon_ends"][hk], out["horizon_coverage"][hk]["status"],
                          round(out["horizon_coverage"][hk]["ci_inflation"], 4)) for hk in hks])
            car = [x for x in _find(bl, "Купонный") if x[0] != "Сценарий"]
            cp = out["bond_carry"]["portfolio_level_by_horizon"]
            ok &= check(f"{lab}: купонный слой = bond_carry", all(
                _num(re.match(r"^(.*?) \(", x[1 + i])[1]) == cp[hk][x[0].split()[0]]["carry_rub"]
                for x in car for i, hk in enumerate(hks)))
            if fill:
                cc = {x[0]: x[1] for x in _find(bl, "Концентрация") if x[0] != "Показатель"}
                ok &= check("итоговый: концентрация = дерево",
                            _num(cc["concentration_ratio"]) == out["concentration_ratio"]
                            and abs(_num(cc["В ту же сторону"]) - out["concentration"]["same_direction_pct"]) <= 0.0051
                            and cc["Фактор"] == out["concentration"]["dominant_factor"])
        # --tables не должен совпадать с --output
        r = inp.cli(extra=["--tables", str(inp.d / "out.yaml")])
        ok &= check("--tables = --output — отказ", r.returncode == 1)
        return ok


def test_script_caveats_in_build():
    with tempfile.TemporaryDirectory() as td:
        inp = Inputs(Path(td), tsr.snapshot())
        f = copy.deepcopy(inp.fill)
        f["caveats"] = f["caveats"] + [{"severity": "HIGH", "type": "H12_EXTRAPOLATED", "message": "ci_inflation 9.9"}]
        inp.write("fill.yaml", f)
        r = inp.cli()
        out = load(inp.d / "out.yaml")
        ok = check("fill с записью о покрытии — не отказ", r.returncode == 0, r.stderr)
        ok &= check("предупреждение в выжимке", "оговорку о покрытии сроков пишет скрипт — запись H12_EXTRAPOLATED из fill отброшена" in r.stdout, r.stdout)
        ok &= check("в файле запись скрипта вместо неё",
                    "9.9" not in json.dumps(out["caveats"]) and sum(c.get("source") == "script" for c in out["caveats"]) == 1)
        r = inp.cli(fill=False, extra=["--weight-type", "probability"])
        out = load(inp.d / "out.yaml")
        ok &= check("только числа: код 0, оговорок скрипта нет", r.returncode == 0 and "caveats" not in out, r.stderr)
        return ok


def _cny_inputs(td) -> Inputs:
    """Стенд с cnyrub и xauusd в факторах и бетах (в базовом стенде их нет)."""
    inp = Inputs(Path(td), tsr.snapshot())
    for s_, sg in (("A", 1.0), ("B", -1.0)):
        for hk in ("h6", "h12"):
            inp.hf["factors_by_horizon"][s_][hk].update({"cnyrub": 4.0 * sg, "xauusd": 6.0 * sg, "geopol": 0.0})
    for pr in inp.priors.values():
        pr["factor_betas"].update({"cnyrub": 0.2, "xauusd": 0.1, "geopol": 50.0})
    inp.write("hf.json", inp.hf, json_=True)
    inp.write("priors.json", inp.priors, json_=True)
    return inp


def _tree_without(inp: Inputs, factors: set[str]) -> dict:
    ctx_j, _ = sr.inputs_from_stress(inp.full)
    j = copy.deepcopy(ctx_j)
    for sc in j["scenarios"].values():
        sc["factors_by_horizon"] = copy.deepcopy(inp.hf["factors_by_horizon"][[k for k in j["scenarios"] if j["scenarios"][k] is sc][0]])
        for cell in sc["factors_by_horizon"].values():
            for f in factors:
                if f in cell:
                    cell[f] = 0.0
    for t, pr in j["priors"].items():
        pr["factor_betas"] = inp.priors[t]["factor_betas"]
    tree, _ = sr.recalc(j, inp.snap, source_name="t", source_kind="judgments", ctx=None, weights=None,
                        weights_name=None, today=TODAY, at=TODAY)
    return tree


def test_factor_probes():
    with tempfile.TemporaryDirectory() as td:
        inp = _cny_inputs(td)
        before = Path(inp.d / "fill.yaml").read_bytes()
        r = inp.cli(extra=["--json", "--tables", str(inp.d / "t.md")])
        ok = check("код 0", r.returncode == 0, r.stderr)
        info = json.loads(r.stdout)
        fp = info["factor_probes"]
        out = load(inp.d / "out.yaml")
        base = _tree_without(inp, set())
        ph = "h12"
        pct = lambda t, s: t["scenarios"][s]["portfolio_level_by_horizon"][ph]["price_delta_rub"] / t["base_value_rub"] * 100  # noqa: E731
        ok &= check("основной срок и слой", fp["horizon"] == ph and fp["basis"] == "price")
        ok &= check("фактор с нулевыми движениями даёт нулевой вклад",
                    all(v == 0 for v in fp["by_factor"]["geopol"]["by_scenario_pp"].values())
                    and fp["by_factor"]["geopol"]["abs_weighted_pp"] == 0)
        for f in ("brent", "usdrub"):
            t = _tree_without(inp, {f})
            ok &= check(f"{f}: by_scenario_pp = база − пересчёт без фактора",
                        all(abs(fp["by_factor"][f]["by_scenario_pp"][s] - (pct(base, s) - pct(t, s))) < 1e-3 for s in "AB"))
        ok &= check("ранжирование по убыванию взвешенного |вклада|",
                    [fp["by_factor"][f]["abs_weighted_pp"] for f in fp["ranking"]]
                    == sorted([fp["by_factor"][f]["abs_weighted_pp"] for f in fp["ranking"]], reverse=True))
        t = _tree_without(inp, {"usdrub", "cnyrub"})
        rub = fp["probes"]["rub"]
        ok &= check("проба «рубль» = пересчёт с обоими обнулёнными", rub["factors"] == ["usdrub", "cnyrub"]
                    and all(abs(rub["by_scenario_pct_without"][s] - pct(t, s)) < 1e-3 for s in "AB")
                    and abs(rub["expected_price_pct"]["without"]
                            - t["portfolio_aggregates"]["price"]["expected_pl_pct_by_horizon"][ph]) < 1e-3
                    and abs(rub["expected_total_pct"]["without"]
                            - t["portfolio_aggregates"]["total_return"]["expected_pl_pct_by_horizon"][ph]) < 1e-3)
        ok &= check("проба «золото» = xauusd", fp["probes"]["gold"]["factors"] == ["xauusd"])
        ok &= check("worst_scenario совпадает с выжимкой", fp["worst_scenario"] == info["worst_scenario"])
        ok &= check("в YAML нет ключа factor_probes и нет новых верхних ключей", "factor_probes" not in out
                    and set(out) <= set(sr.TOP_ORDER) | {"numbers_only"})
        ok &= check("исходные суждения (fill) не изменились", Path(inp.d / "fill.yaml").read_bytes() == before)
        md = (inp.d / "t.md").read_text(encoding="utf-8")
        ok &= check("блок «Вклад факторов» в файле таблиц", "## Вклад факторов (h12, ценовой слой)" in md
                    and "Проба «рубль = 0»" in md and "Худший сценарий" in md.split("## Вклад факторов")[1])
        txt = inp.cli().stdout
        ok &= check("выжимка: вклад и пробы", "Вклад факторов (h12" in txt and "пробы: без рубля" in txt, txt)
        # без ожидания (equal без --include-ev) — не падает
        cmd_extra = ["--weight-type", "equal"]
        inp.write("fill.yaml", {k: v for k, v in inp.fill.items() if k != "weight_type"})
        r2 = subprocess.run([sys.executable, str(BUILD), "--snapshot", str(inp.d / "snap.json"), "--scenarios", str(inp.d / "ssot.yaml"),
                             "--macro-scenarios", str(inp.d / "macro.yaml"), "--output", str(inp.d / "o3.yaml"), "--horizons", "6,12",
                             "--primary-horizon", "12", "--slug", "t", "--today", TODAY, "--priors", str(inp.d / "priors.json"),
                             "--horizon-factors", str(inp.d / "hf.json"), "--json", *cmd_extra],
                            capture_output=True, text=True)
        ok &= check("equal без --include-ev: код 0", r2.returncode == 0, r2.stderr)
        if r2.returncode == 0:
            rub2 = json.loads(r2.stdout)["factor_probes"]["probes"]["rub"]
            ok &= check("equal без --include-ev: ожидание None, пробы по сценариям есть",
                        rub2["expected_price_pct"] == {"base": None, "without": None} and rub2["by_scenario_pct_without"])
        return ok


def test_tables_without_probes():
    with tempfile.TemporaryDirectory() as td:
        inp = Inputs(Path(td), tsr.snapshot())
        r = inp.cli(extra=["--json"])
        info = json.loads(r.stdout)
        info.pop("factor_probes")
        import stress_tables as stt_
        md = stt_.build_tables(load(inp.d / "out.yaml"), inp.snap, info)
        return check("без factor_probes блока нет, таблицы строятся", "Вклад факторов" not in md and "Купонный слой" in md)


# ── файл сроков сайта (scenarios/horizons.json) ──
SITE_ENDS = {"h6": "2026-12-31", "h12": "2027-06-30"}


def write_terms(inp: Inputs, ends=None, primary=12, set_at="2026-11-06T21:30:00+03:00", **extra) -> Path:
    root = inp.d / "lib"
    (root / "scenarios").mkdir(parents=True, exist_ok=True)
    doc = {"schema": "horizons@1", "horizon_ends": ends or SITE_ENDS, "primary_horizon": primary,
           "set_at": set_at, "reason": "тест", "history": []}
    doc.update(extra)
    (root / "scenarios/horizons.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return root


def terms_cmd(inp: Inputs, root: Path | None, extra=None, out="t.yaml"):
    cmd = [sys.executable, str(BUILD), "--snapshot", str(inp.d / "snap.json"), "--scenarios", str(inp.d / "ssot.yaml"),
           "--macro-scenarios", str(inp.d / "macro.yaml"), "--priors", str(inp.d / "priors.json"),
           "--political-paths", str(inp.d / "polpaths.json"), "--fill", str(inp.d / "fill.yaml"),
           "--slug", "t", "--include-ev", "--today", TODAY, "--output", str(inp.d / out)]
    if root is not None:
        cmd += ["--library-root", str(root)]
    return subprocess.run(cmd + list(extra or []), capture_output=True, text=True)


def test_site_terms():
    """Файл сроков сайта задаёт сроки прогона; без него поведение прежнее."""
    with tempfile.TemporaryDirectory() as td:
        inp = grid_inputs(td)
        root = write_terms(inp)
        r = terms_cmd(inp, root)
        out = load(inp.d / "t.yaml") if r.returncode == 0 else {}
        ok = check("сроки, основной срок и режим — из файла", r.returncode == 0 and out.get("horizon_ends") == SITE_ENDS
                   and out.get("horizons") == [6, 12] and out.get("primary_horizon") == 12
                   and out.get("horizon_mode") == "anchored", r.stderr[-400:])
        ok &= check("в сводке сказано, откуда сроки", "Сроки: файл сроков сайта от 06.11" in r.stdout, r.stdout[-500:])
        ok &= check("в YAML стресса нет новых полей про сроки сайта",
                    not [k for k in out if "terms" in k or "site" in k], str([k for k in out if "terms" in k or "site" in k]))
        write_terms(inp, primary=6)
        r = terms_cmd(inp, root)
        ok &= check("основной срок — из файла (6)", r.returncode == 0 and load(inp.d / "t.yaml")["primary_horizon"] == 6, r.stderr[-300:])
        write_terms(inp)
        # явные опции: те же сроки — ок, другие — отказ с текстом
        r = terms_cmd(inp, root, ["--anchor-dates", "2026-12-31,2027-06-30", "--primary-horizon", "12"])
        ok &= check("--anchor-dates с теми же датами — код 0", r.returncode == 0, r.stderr[-300:])
        r = terms_cmd(inp, root, ["--horizons", "6,12"])
        ok &= check("--horizons, дающий другие даты, — отказ с адресом настройки", r.returncode == 1
                    and "сроки заданы на сайте (scenarios/horizons.json: h6 2026-12-31, h12 2027-06-30" in r.stderr
                    and "«Стресс» → «Настройки стресса»" in r.stderr, r.stderr[-400:])
        r = terms_cmd(inp, root, ["--anchor-dates", "2026-12-31,2027-07-31"])
        ok &= check("--anchor-dates с другой датой — отказ", r.returncode == 1 and "сроки заданы на сайте" in r.stderr)
        r = terms_cmd(inp, root, ["--primary-horizon", "6"])
        ok &= check("другой основной срок — отказ", r.returncode == 1 and "сроки заданы на сайте" in r.stderr)
        # автосдвиг не применяется; ближайший срок близко — предупреждение
        write_terms(inp, ends={"h6": "2026-07-31", "h12": "2027-01-31"})
        r = terms_cmd(inp, root)
        out = load(inp.d / "t.yaml") if r.returncode == 0 else {}
        ok &= check("срок близко: сдвига нет, есть предупреждение про сайт", r.returncode == 0
                    and out.get("horizon_ends") == {"h6": "2026-07-31", "h12": "2027-01-31"}
                    and "сроки пора сдвинуть на сайте: «Стресс» → «Настройки стресса»" in r.stdout
                    and "сроки сдвинуты на" not in r.stdout, r.stdout[-600:] + r.stderr[-300:])
        # --horizons-from: сроки из файла, расхождение с прошлым стрессом названо
        write_terms(inp)
        inp.write("prev.yaml", {"horizons": [6, 12], "horizon_ends": {"h6": "2026-11-30", "h12": "2027-05-31"},
                                "primary_horizon": 12, "horizon_mode": "rolling"})
        r = terms_cmd(inp, root, ["--horizons-from", str(inp.d / "prev.yaml")])
        out = load(inp.d / "t.yaml") if r.returncode == 0 else {}
        ok &= check("--horizons-from при файле: сроки из файла и предупреждение «было … стало …»", r.returncode == 0
                    and out.get("horizon_ends") == SITE_ENDS
                    and "сроки изменены на сайте 06.11: было h6 2026-11-30, h12 2027-05-31, стало h6 2026-12-31, h12 2027-06-30" in r.stdout,
                    r.stdout[-700:] + r.stderr[-300:])
        r = terms_cmd(inp, root, ["--horizons-from", str(inp.d / "prev.yaml")])
        ok &= check("«из прошлого стресса» не пишется, когда сроки из файла", "из прошлого стресса" not in r.stdout)
        # политические пути прошлого стресса на других сроках
        prev_pol = {"horizon_ends": {"h6": "2026-11-30", "h12": "2027-05-31"},
                    "scenarios": {s: {"factors_by_horizon": {h: {"sanctions": POL[s]["sanctions"][h], "geopol": POL[s]["geopol"][h]}
                                                             for h in ("h6", "h12")}} for s in "AB"}}
        inp.write("polprev2.yaml", prev_pol)
        cmd = [sys.executable, str(BUILD), "--snapshot", str(inp.d / "snap.json"), "--scenarios", str(inp.d / "ssot.yaml"),
               "--macro-scenarios", str(inp.d / "macro.yaml"), "--priors", str(inp.d / "priors.json"),
               "--political-from", str(inp.d / "polprev2.yaml"), "--fill", str(inp.d / "fill.yaml"), "--slug", "t",
               "--include-ev", "--today", TODAY, "--output", str(inp.d / "t2.yaml"), "--library-root", str(root)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        ok &= check("--political-from со старыми сроками: предупреждение «пути перенесены со сроков … — пересмотри»",
                    r.returncode == 0 and "санкционный и геополитический пути перенесены со сроков" in r.stdout
                    and "пересмотри их под новые" in r.stdout, r.stdout[-700:] + r.stderr[-300:])
        # невалидный файл: как будто файла нет + предупреждение
        for label, doc in (("даты не по возрастанию", {"h6": "2027-06-30", "h12": "2026-12-31"}),
                           ("не дата", {"h6": "2026-13-45", "h12": "2027-06-30"})):
            write_terms(inp, ends=doc)
            r = terms_cmd(inp, root, ["--horizons", "6,12", "--primary-horizon", "12"])
            ok &= check(f"невалидный файл ({label}): прогон идёт по опциям, предупреждение с причиной", r.returncode == 0
                        and "файл сроков сайта невалиден" in r.stdout
                        and load(inp.d / "t.yaml")["horizon_ends"] == {"h6": "2026-11-30", "h12": "2027-05-31"}, r.stdout[-500:] + r.stderr[-300:])
        write_terms(inp, primary=24)
        r = terms_cmd(inp, root, ["--horizons", "6,12", "--primary-horizon", "12"])
        ok &= check("основной срок вне набора — файл невалиден", r.returncode == 0 and "primary_horizon" in r.stdout, r.stdout[-400:])
        # файла нет: прежнее поведение, строки про сроки в сводке нет
        (root / "scenarios/horizons.json").unlink()
        r = terms_cmd(inp, root, ["--horizons", "6,12", "--primary-horizon", "12"])
        ok &= check("файла нет — как раньше (без строки «Сроки:»)", r.returncode == 0 and "Сроки:" not in r.stdout
                    and "сайта" not in r.stdout, r.stdout[-400:])
        r = terms_cmd(inp, root, ["--horizons-from", str(inp.d / "prev.yaml")])
        ok &= check("файла нет, --horizons-from: «из прошлого стресса prev.yaml»", r.returncode == 0
                    and "Сроки: из прошлого стресса prev.yaml" in r.stdout, r.stdout[-400:])
        return ok


def test_horizons_file_rules():
    """Правила файла сроков — те же, что у сайта."""
    good = {"schema": "horizons@1", "horizon_ends": {"h6": "2027-05-06", "h12": "2027-11-06", "h24": "2028-11-06"},
            "primary_horizon": 12}
    ok = check("валидный файл — без ошибок", sb.horizons_file_errors(good) == [])

    def bad(label, **chg):
        d = copy.deepcopy(good)
        d.update(chg)
        return check(f"отказ: {label}", sb.horizons_file_errors(d) != [], str(d))
    ok &= bad("чужая schema", schema="horizons@2")
    ok &= bad("пустые сроки", horizon_ends={})
    ok &= bad("семь сроков", horizon_ends={f"h{i}": f"202{i}-01-01" for i in range(1, 8)}, primary_horizon=1)
    ok &= bad("ключ не вида hN", horizon_ends={"six": "2027-05-06"}, primary_horizon=6)
    ok &= bad("h0", horizon_ends={"h0": "2027-05-06"}, primary_horizon=0)
    ok &= bad("дата не ГГГГ-ММ-ДД", horizon_ends={"h6": "06.05.2027"}, primary_horizon=6)
    ok &= bad("несуществующая дата", horizon_ends={"h6": "2027-02-30"}, primary_horizon=6)
    ok &= bad("равные даты", horizon_ends={"h6": "2027-05-06", "h12": "2027-05-06"})
    ok &= bad("основной срок вне набора", primary_horizon=18)
    ok &= bad("основной срок — строка", primary_horizon="12")
    ok &= bad("основной срок — булево", primary_horizon=True)
    ok &= check("порядок по номеру, а не по порядку ключей",
                sb.horizons_file_errors({**good, "horizon_ends": {"h12": "2027-11-06", "h6": "2027-05-06"}}) == [])
    return ok


def test_recalc_macro_equals_build():
    """stress_recalc --macro-scenarios над стрессом даёт те же числа, что stress_build с тем же макро-файлом,
    суждениями, сроками и --today."""
    with tempfile.TemporaryDirectory() as td:
        inp = grid_inputs(td)
        rb = inp.cli(hf=None, out="built.yaml", extra=["--political-paths", str(inp.d / "polpaths.json")])
        built = load(inp.d / "built.yaml")
        # источник: стресс скилла со старыми числовыми факторами, теми же суждениями и политическими путями
        src = copy.deepcopy(inp.full)
        for sid in "AB":
            for hk in ("h6", "h12"):
                src["scenarios"][sid]["factors_by_horizon"][hk].update(
                    {k: POL[sid][k][hk] for k in ("sanctions", "geopol")})
        src["horizon_ends"] = dict(built["horizon_ends"])
        src["baseline_spot"] = {"brent_usd": 60, "usdrub": 90, "cnyrub": 12, "cbr_rate_pct": 16, "xauusd_usd": 2500}
        src["bond_carry"]["baseline_cbr_rate_pct"] = 16
        inp.write("src.yaml", src)
        inp.write("macro-new.yaml", grid_macro())
        r = subprocess.run([sys.executable, str(SCRIPTS / "stress_recalc.py"), "--stress", str(inp.d / "src.yaml"),
                            "--snapshot", str(inp.d / "snap.json"), "--macro-scenarios", str(inp.d / "macro-new.yaml"),
                            "--output", str(inp.d / "rc.yaml"), "--today", TODAY, "--at", "2026-06-01T10:00:00+03:00", "--json"],
                           capture_output=True, text=True)
        ok = check("оба кода 0", rb.returncode == 0 and r.returncode == 0, rb.stderr[-300:] + r.stderr[-400:])
        rc = load(inp.d / "rc.yaml")
        ok &= same_calc(rc, built, "recalc --macro-scenarios = stress_build")
        ok &= check("числовые факторы и политические пути равны",
                    all(rc["scenarios"][s]["factors_by_horizon"] == built["scenarios"][s]["factors_by_horizon"] for s in "AB"))
        ok &= check("baseline_spot и horizon_coverage равны", rc["baseline_spot"] == built["baseline_spot"]
                    and rc["horizon_coverage"] == built["horizon_coverage"])
        ok &= check("оговорка о покрытии сроков пересобрана скриптом (как у stress_build)",
                    [c for c in rc["caveats"] if c.get("source") == "script"] == [c for c in built["caveats"] if c.get("source") == "script"])
        ok &= check("уровень КС купонного слоя — из новой таблицы", rc["bond_carry"]["baseline_cbr_rate_pct"]
                    == built["bond_carry"]["baseline_cbr_rate_pct"] == 14)
        ok &= check("происхождение пересчёта: macro_input, macro_input_was, reason macro, текст устарел",
                    rc["macro_input"] == "macro-new.yaml" and rc["recalc"]["macro_input"] == "macro-new.yaml"
                    and rc["recalc"]["macro_input_was"] == "macro.yaml" and rc["recalc"]["reason"] == "macro"
                    and rc["recalc"]["narrative_stale"] is True,
                    str({k: rc["recalc"].get(k) for k in ("macro_input", "macro_input_was", "reason", "narrative_stale")}))
        ok &= check("--json: reason macro", json.loads(r.stdout)["reason"] == "macro")
        return ok


TESTS = [
    test_equivalence_with_recalc,
    test_horizon_factors_input_equals_output,
    test_circle_extract_recalc,
    test_numbers_only,
    test_refusals,
    test_weights,
    test_carry_overrides,
    test_asset_type_reaches_scale_guard,
    test_horizons_from,
    test_macro_grid_mode,
    test_macro_grid_refusals,
    test_site_terms,
    test_horizons_file_rules,
    test_recalc_macro_equals_build,
    test_asset_type_in_per_position,
    test_priors_from,
    test_sanctions_positions_reference,
    test_fixed_priors,
    test_fixed_priors_real_file,
    test_tables,
    test_script_caveats_in_build,
    test_factor_probes,
    test_tables_without_probes,
]


def main() -> int:
    passed = failed = 0
    for t in TESTS:
        print(f"\n[{t.__name__}]")
        try:
            ok = t()
        except Exception as e:  # noqa: BLE001
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
