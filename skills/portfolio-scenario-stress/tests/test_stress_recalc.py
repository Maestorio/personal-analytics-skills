#!/usr/bin/env python3
"""Тесты stress_recalc.py: пересчёт чисел стресс-файла без модели.

Синтетика: маленький снапшот + «стресс-файл скилла», собранный настоящими
расчётными функциями (compute_per_position → compute_bond_carry →
compute_portfolio_aggregates → assemble_stress).
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
SCRIPTS = REPO / "skills/portfolio-scenario-stress/scripts"
RECALC = SCRIPTS / "stress_recalc.py"
STUB = SCRIPTS / "build_stress_stub.py"
sys.path.insert(0, str(SCRIPTS))

import assemble_stress as asm  # noqa: E402
import compute_bond_carry as cbc  # noqa: E402
import compute_per_position as cpp  # noqa: E402
import compute_portfolio_aggregates as cpa  # noqa: E402
import stress_recalc as sr  # noqa: E402


def check(label: str, cond: bool, detail: str = "") -> bool:
    if cond:
        print(f"  ✓ {label}")
        return True
    print(f"  ✗ {label}{(' — ' + detail) if detail else ''}")
    return False


def snapshot(qty1=600000.0, with_t3=False, with_t2=True, as_of="2026-05-12"):
    h = [{"ticker": "TICK1", "name": "Один", "asset_type": "stock", "sector": "banks_finance", "value_rub": qty1,
          "is_blocked": False}]
    if with_t2:
        h.append({"ticker": "TICK2", "name": "Два", "asset_type": "stock", "sector": "oil_gas", "value_rub": 400000.0,
                  "is_blocked": False})
    if with_t3:
        h.append({"ticker": "TICK3", "name": "Три", "asset_type": "stock", "sector": "oil_gas", "value_rub": 100000.0,
                  "is_blocked": False})
    return {"schema_version": "2.0", "as_of_date": as_of, "holdings": h, "cash": {"total_rub": 100000.0}}


SSOT = """\
scenario_triggers:
  - scenario_id: A
    label: "Сценарий А"
    probability: 0.5
    p_by_horizon: {h6: 0.6, h12: 0.5}
  - scenario_id: B
    label: "Сценарий Б"
    probability: 0.5
    p_by_horizon: {h6: 0.4, h12: 0.5}
"""
MACRO = """\
baseline_spot: {brent_usd: 70, usdrub: 80, cnyrub: 11, cbr_rate_pct: 14, xauusd_usd: 3000}
scenarios:
  A: {horizon_2027_12_31: {brent_usd: 70}}
  B: {horizon_2027_12_31: {brent_usd: 60}}
"""
FBH = {
    "A": {"h6": {"brent": 10.0, "usdrub": 5.0, "cbr_rate": -1.0}, "h12": {"brent": 20.0, "usdrub": 8.0, "cbr_rate": -2.0}},
    "B": {"h6": {"brent": -10.0, "usdrub": -5.0, "cbr_rate": 1.0}, "h12": {"brent": -20.0, "usdrub": -8.0, "cbr_rate": 2.0}},
}
COVERAGE = {"h6": {"status": "covered", "ci_inflation": 1.0},
            "h12": {"status": "extrapolated", "ci_inflation": 1.2842}}
PRIORS = {
    "TICK1": {"factor_betas": {"brent": 0.5, "usdrub": 0.1}, "factor_betas_method": "тест-prior",
              "factor_betas_r2": 0.4, "sanctions_position": 0.3},
    "TICK2": {"factor_betas": {"brent": -0.2, "usdrub": 0.3}, "factor_betas_method": "тест-prior",
              "factor_betas_r2": 0.2, "sanctions_position": 0.5},
}
FILL = {
    "sector_breakdown_pct": {"Финансы": {"weight_pct": 60}, "Прочее": {"weight_pct": 40}},
    "sector_breakdown_basis": "price", "concentration_ratio": 0.6, "dominant_factor": "brent",
    "top_risks": [{"ticker": "TICK1", "scenario": "A", "delta_pct": -20.0, "weight_pct": 60}],
    "macro_blindspots": [], "caveats": [{"severity": "HIGH", "message": "priors-only"}],
    "robustness": {"hedge_target": "A"}, "method": "тест",
    "concentration": {"dominant_factor": "usdrub", "note": "текст модели"},
}


def build_skill_stress(d: Path, snap: dict) -> Path:
    """Стресс-файл «как от скилла»: стаб + фактические расчётные функции + fill."""
    (d / "snap0.json").write_text(json.dumps(snap))
    (d / "ssot.yaml").write_text(SSOT)
    (d / "macro.yaml").write_text(MACRO)
    r = subprocess.run([sys.executable, str(STUB), "--snapshot", str(d / "snap0.json"),
                        "--scenarios", str(d / "ssot.yaml"), "--macro-scenarios", str(d / "macro.yaml"),
                        "--output", str(d / "stub.yaml"), "--today", "2026-05-12", "--slug", "t",
                        "--horizons", "6,12", "--primary-horizon", "12"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    stub = yaml.safe_load((d / "stub.yaml").read_text(encoding="utf-8"))
    sc = {s: {"name": stub["scenarios"][s]["name"], "p": stub["scenarios"][s]["p"],
              "p_by_horizon": stub["scenarios"][s]["p_by_horizon"], "factors_by_horizon": FBH[s]}
          for s in "AB"}
    he = stub["horizon_ends"]
    pp, _w, unm = cpp.compute_per_position(snap, sc, PRIORS, "priors", horizon_ci_inflation={"h6": 1.0, "h12": 1.2842},
                                           horizon_ends=he)
    bond = cbc.run({"snapshot": snap, "scenarios": sc, "baseline": {"cbr_rate_pct": 14.0},
                    "horizon_ends": he, "params": {}})
    agg = cpa.compute(snap, sc, pp, bond["bond_carry"], "probability", True)
    fill = copy.deepcopy(FILL)
    fill["robustness"]["modal_scenario"] = "none"
    fill["weight_type"] = "probability"
    tree, _ = asm.assemble(stub, {"per_position": pp, "unmapped_tickers": unm}, agg, bond,
                             {"factors_by_horizon": FBH, "horizon_coverage": COVERAGE}, fill)
    out = d / "stress-skill.yaml"
    out.write_text(asm.dump(tree), encoding="utf-8")
    return out


def run(d: Path, stress: Path, snap: dict, output: str = "out.yaml", extra=None, name="snapn.json"):
    (d / name).write_text(json.dumps(snap))
    r = subprocess.run([sys.executable, str(RECALC), "--stress", str(stress), "--snapshot", str(d / name),
                        "--output", str(d / output), "--today", "2026-06-01", "--at", "2026-06-01T10:00:00+03:00",
                        "--json", *(extra or [])], capture_output=True, text=True)
    return r


def load(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8"))


CALC_BLOCKS = ("per_position", "bond_carry", "portfolio_aggregates", "robustness", "unmapped_tickers")


def test_same_snapshot_reproduces():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st = build_skill_stress(d, snapshot())
        r = run(d, st, snapshot())
        src, out = load(st), load(d / "out.yaml")
        ok = check("код 0", r.returncode == 0, r.stderr)
        for b in CALC_BLOCKS:
            ok &= check(f"блок {b} равен", src.get(b) == out.get(b))
        for s in src["scenarios"]:
            ok &= check(f"portfolio_level {s} равен",
                        src["scenarios"][s]["portfolio_level_by_horizon"] == out["scenarios"][s]["portfolio_level_by_horizon"])
        ok &= check("reason none, narrative_stale false",
                    out["recalc"]["reason"] == "none" and out["recalc"]["narrative_stale"] is False)
        return ok


def test_changed_quantity_changes_numbers():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st = build_skill_stress(d, snapshot())
        r = run(d, st, snapshot(qty1=900000.0, as_of="2026-05-20"))
        src, out = load(st), load(d / "out.yaml")
        ok = check("код 0", r.returncode == 0, r.stderr)
        ok &= check("доля TICK1 выросла", out["per_position"]["TICK1"]["weight_pct"] > src["per_position"]["TICK1"]["weight_pct"])
        ok &= check("итоги изменились",
                    out["scenarios"]["A"]["portfolio_level_by_horizon"] != src["scenarios"]["A"]["portfolio_level_by_horizon"])
        ok &= check("снапшот в метаданных", out["portfolio_snapshot_id"] == "portfolio-2026-05-20.json"
                    and out["recalc"]["reason"] == "snapshot" and out["recalc"]["narrative_stale"] is True)
        return ok


def test_new_ticker_needs_judgment():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st = build_skill_stress(d, snapshot())
        r = run(d, st, snapshot(with_t3=True))
        out = load(d / "out.yaml")
        ok = check("код 0", r.returncode == 0, r.stderr)
        nj = out["recalc"]["needs_judgment"]
        ok &= check("TICK3 в needs_judgment", [x["ticker"] for x in nj] == ["TICK3"] and nj[0]["name"] == "Три", str(nj))
        ok &= check("остальные посчитаны", set(out["per_position"]) == {"TICK1", "TICK2"})
        ok &= check("неполнота покрытия записана в recalc.validator_open",
                    len(out["recalc"]["validator_open"]) == 2 and all("3.13" in x for x in out["recalc"]["validator_open"]))
        return ok


def test_vanished_ticker_dropped():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st = build_skill_stress(d, snapshot())
        r = run(d, st, snapshot(with_t2=False))
        out = load(d / "out.yaml")
        ok = check("код 0", r.returncode == 0, r.stderr)
        ok &= check("TICK2 в dropped", [x["ticker"] for x in out["recalc"]["dropped"]] == ["TICK2"])
        ok &= check("TICK2 нет в per_position", "TICK2" not in out["per_position"])
        return ok


def test_output_equals_stress_refused():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st = build_skill_stress(d, snapshot())
        before = st.read_text(encoding="utf-8")
        r = run(d, st, snapshot(), output=st.name)
        ok = check("отказ кодом 1", r.returncode == 1, str(r.returncode))
        ok &= check("файл не тронут", st.read_text(encoding="utf-8") == before)
        return ok


def test_recalc_block_and_judgment_carried():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st = build_skill_stress(d, snapshot())
        run(d, st, snapshot(qty1=700000.0, as_of="2026-05-20"))
        src, out = load(st), load(d / "out.yaml")
        rc = out["recalc"]
        ok = check("recalc заполнен", rc["source_stress"] == "stress-skill.yaml"
                   and rc["source_snapshot_id"] == "portfolio-2026-05-12.json"
                   and rc["snapshot_id"] == "portfolio-2026-05-20.json"
                   and rc["weights_source"] == "stress" and rc["at"] == "2026-06-01T10:00:00+03:00"
                   and rc["needs_judgment"] == [] and rc["dropped"] == [])
        for k in ("macro_blindspots", "factor_definitions", "horizon_coverage", "dominant_factor"):
            ok &= check(f"{k} перенесён как есть", src.get(k) == out.get(k))
        ok &= check("caveats: записи модели перенесены, в конце добавлена запись скрипта",
                    out["caveats"][:len(src["caveats"])] == src["caveats"]
                    and [c.get("source") for c in out["caveats"][len(src["caveats"]):]] == ["script"])
        ok &= check("concentration: суждения перенесены", out["concentration"]["dominant_factor"] == "usdrub"
                    and out["concentration"]["note"] == "текст модели")
        ok &= check("date и run_id", out["date"] == "2026-06-01" and out["run_id"].startswith("RECALC-"))
        return ok


def test_derived_fields_computed():
    """Расчётные поля считает compute_derived_fields: доли кэша/блокировок и концентрация — от портфеля
    с кэшем, веса секторов — от позиций; portfolio_summary в выход не переносится; всё посчитано."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st = build_skill_stress(d, snapshot())
        src = load(st)
        src["portfolio_summary"] = {"total_value_rub": 1, "worst_scenario": "A"}
        st.write_text(yaml.safe_dump(src, allow_unicode=True, sort_keys=False), encoding="utf-8")
        r = run(d, st, snapshot(qty1=700000.0, as_of="2026-05-20"))
        out = load(d / "out.yaml")
        ok = check("код 0", r.returncode == 0, r.stderr)
        ok &= check("cash_rub_pct = 100000 / 1200000", out["cash_rub_pct"] == 8.33, str(out.get("cash_rub_pct")))
        ok &= check("blocked_pct = 0.0", out["blocked_pct"] == 0.0)
        sb = out["sector_breakdown_pct"]
        ok &= check("секторы: ключи из снапшота, подписи из таблицы, веса от позиций без кэша",
                    sb["banks_finance"]["label_ru"] == "Банки и финансы" and sb["oil_gas"]["label_ru"] == "Нефтегаз"
                    and sb["banks_finance"]["weight_pct"] == 63.64 and sb["oil_gas"]["weight_pct"] == 36.36, str(sb))
        ok &= check("top_risks/top_resilient посчитаны", out["top_risks"] != src["top_risks"] and out["top_resilient"])
        c = out["concentration"]
        ok &= check("concentration: числа посчитаны, фактор и note из суждений",
                    set(c) == {"same_direction_pct", "opposite_pct", "neutral_pct", "same_direction_incl_cnyrub_pct",
                               "dominant_factor", "note"} and c["note"] == "текст модели" and c["dominant_factor"] == "usdrub")
        ok &= check("concentration_ratio = same / 100", out["concentration_ratio"] == round(c["same_direction_pct"] / 100, 4))
        ok &= check("portfolio_summary в выходе нет", "portfolio_summary" not in out)
        ok &= check("stale_numeric_fill_fields пуст, notes нет",
                    out["recalc"]["stale_numeric_fill_fields"] == [] and "notes" not in out["recalc"])
        return ok


def test_underived_fields_stay_stale_with_reason():
    """Нет сектора у акции и нет фактора концентрации: поля остаются значениями источника,
    попадают в stale_numeric_fill_fields, причина — в recalc.notes."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st = build_skill_stress(d, snapshot())
        src = load(st)
        src["concentration"].pop("dominant_factor")
        st.write_text(yaml.safe_dump(src, allow_unicode=True, sort_keys=False), encoding="utf-8")
        snap = snapshot(qty1=700000.0, as_of="2026-05-20")
        snap["holdings"][0].pop("sector")
        r = run(d, st, snap)
        out = load(d / "out.yaml")
        ok = check("код 0", r.returncode == 0, r.stderr)
        ok &= check("секторные блоки — как в источнике", out["sector_breakdown_pct"] == src["sector_breakdown_pct"]
                    and out["top_risks"] == src["top_risks"])
        ok &= check("концентрация — как в источнике", out["concentration_ratio"] == src["concentration_ratio"]
                    and out["concentration"] == src["concentration"])
        stale = set(out["recalc"]["stale_numeric_fill_fields"])
        ok &= check("stale = не посчитанное", {"sector_breakdown_pct", "top_risks", "concentration_ratio",
                                               "concentration"} <= stale and "cash_rub_pct" not in stale, str(stale))
        notes = " ".join(out["recalc"]["notes"])
        ok &= check("причины в notes: тикер без сектора и нет фактора", "TICK1" in notes and "dominant_factor" in notes, notes)
        ok &= check("cash_rub_pct всё равно посчитан", out["cash_rub_pct"] == 8.33)
        return ok


def wfile(d: Path, st: dict, mod=None, name="w.json") -> Path:
    w = {"schema": "stress-weights@1", "matrix": "m", "horizon_ends": st["horizon_ends"],
         "weights": {hk: {s: st["scenarios"][s]["p_by_horizon"][hk] for s in st["scenarios"]}
                     for hk in st["horizon_ends"]}, "set_at": "2026-06-01T09:00:00+03:00"}
    if mod:
        mod(w)
    (d / name).write_text(json.dumps(w))
    return d / name


def test_weights_json_valid():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st = build_skill_stress(d, snapshot())
        src = load(st)
        def mod(w):
            w["weights"]["h12"] = {"A": 0.8, "B": 0.2}
        f = wfile(d, src, mod)
        r = run(d, st, snapshot(), extra=["--weights-json", str(f)])
        out = load(d / "out.yaml")
        ok = check("код 0", r.returncode == 0, r.stderr)
        ok &= check("p_by_horizon из файла, p = вес primary",
                    out["scenarios"]["A"]["p_by_horizon"]["h12"] == 0.8 and out["scenarios"]["A"]["p"] == 0.8)
        ok &= check("центральные значения не изменились",
                    all(out["scenarios"][s]["portfolio_level_by_horizon"] == src["scenarios"][s]["portfolio_level_by_horizon"]
                        for s in "AB") and out["per_position"] != {} and
                    all(out["per_position"][t]["by_horizon"]["h12"]["delta_pct_by_scenario"]
                        == src["per_position"][t]["by_horizon"]["h12"]["delta_pct_by_scenario"] for t in src["per_position"]))
        ok &= check("EV изменился", out["portfolio_aggregates"] != src["portfolio_aggregates"])
        rc = out["recalc"]
        ok &= check("recalc: источник, дата, причина",
                    rc["weights_source"] == "stress-weights:w.json" and rc["weights_set_at"] == "2026-06-01T09:00:00+03:00"
                    and rc["reason"] == "weights")
        return ok


def test_weights_json_same_as_stress():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st = build_skill_stress(d, snapshot())
        src = load(st)
        f = wfile(d, src)
        r = run(d, st, snapshot(), extra=["--weights-json", str(f)])
        out = load(d / "out.yaml")
        ok = check("код 0", r.returncode == 0, r.stderr)
        ok &= check("reason none", out["recalc"]["reason"] == "none")
        ok &= check("расчётные блоки равны", all(src[b] == out[b] for b in CALC_BLOCKS))
        return ok


def test_weights_json_refusals():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st = build_skill_stress(d, snapshot())
        src = load(st)
        cases = {
            "даты": lambda w: w["horizon_ends"].update({"h12": "2030-01-31"}),
            "сценарии": lambda w: w["weights"]["h6"].update({"Z": 0.0}),
            "сумма": lambda w: w["weights"]["h6"].update({"A": 0.1, "B": 0.1}),
            "вне [0,1]": lambda w: w["weights"]["h6"].update({"A": 1.5, "B": -0.5}),
            "нет горизонта": lambda w: w["weights"].pop("h12"),
        }
        ok = True
        for i, (name, mod) in enumerate(cases.items()):
            f = wfile(d, src, mod, name=f"w{i}.json")
            r = run(d, st, snapshot(), output=f"o{i}.yaml", extra=["--weights-json", str(f)])
            ok &= check(f"отказ: {name}", r.returncode == 1 and not (d / f"o{i}.yaml").exists(), r.stderr[:120])
            if name == "даты":
                ok &= check("текст про пересмотр", "нужно пересмотреть" in r.stderr)
        return ok


def test_deterministic():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st = build_skill_stress(d, snapshot())
        run(d, st, snapshot(qty1=700000.0), output="a.yaml")
        run(d, st, snapshot(qty1=700000.0), output="b.yaml")
        return check("байт-в-байт", (d / "a.yaml").read_bytes() == (d / "b.yaml").read_bytes())


def test_script_caveats():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st = build_skill_stress(d, snapshot())
        run(d, st, snapshot(), output="a.yaml")
        a = load(d / "a.yaml")
        sc = [c for c in a["caveats"] if c.get("source") == "script"]
        cov = a["horizon_coverage"]["h12"]
        ok = check("одна запись скрипта — для h12 (h6 covered записи не даёт)",
                   len(sc) == 1 and sc[0]["horizon"] == "h12" and sc[0]["type"] == "HORIZON_EXTRAPOLATED"
                   and sc[0]["severity"] == "HIGH" and a["caveats"][-1] is not None and a["caveats"][-1]["source"] == "script")
        ok &= check("числа записи равны horizon_coverage",
                    f"×{cov['ci_inflation']}" in sc[0]["message"] and "срок за пределами прогноза" in sc[0]["message"]
                    and str(cov.get("target_date")) in sc[0]["message"], sc[0]["message"])
        ok &= check("h6 в сообщениях нет", all("h6 " not in c["message"] for c in sc))
        # повторный пересчёт результата не плодит дубли
        run(d, d / "a.yaml", snapshot(), output="b.yaml")
        b = load(d / "b.yaml")
        ok &= check("повторный recalc: записей скрипта по-прежнему одна, список тот же",
                    sum(c.get("source") == "script" for c in b["caveats"]) == 1 and b["caveats"] == a["caveats"])
        # запись модели H24_EXTRAPOLATED заменяется записью скрипта
        t = load(st)
        t["caveats"].append({"severity": "HIGH", "type": "h24_extrapolated", "message": "ci_inflation 1.284 устарело"})
        t["caveats"].append({"severity": "LOW", "type": "OTHER", "message": "прочее"})
        (d / "m.yaml").write_text(asm.dump(t), encoding="utf-8")
        run(d, d / "m.yaml", snapshot(), output="c.yaml")
        c = load(d / "c.yaml")
        ok &= check("запись модели того же типа убрана, прочая осталась, скрипта — одна",
                    not any(x.get("message", "").startswith("ci_inflation 1.284") for x in c["caveats"])
                    and any(x.get("type") == "OTHER" for x in c["caveats"])
                    and sum(x.get("source") == "script" for x in c["caveats"]) == 1)
        # полностью покрытые сроки записей не дают
        t = load(st)
        for hk in t["horizon_coverage"]:
            t["horizon_coverage"][hk]["status"] = "covered"
        tree = copy.deepcopy(t)
        ok &= check("script_caveats: все covered — пусто", sr.script_caveats(tree) == [])
        ok &= check("script_caveats: без warnings нет пустого предложения", ". ." not in
                    " ".join(c["message"] for c in sr.script_caveats(load(st))))
        # «только числа»: заглушка / отсутствие caveats — не падает, записей нет
        ok &= check("заглушка caveats не меняется",
                    sr.merge_script_caveats({"caveats": [sr.CAVEAT_MARK], "horizon_coverage": load(st)["horizon_coverage"]})
                    == [sr.CAVEAT_MARK])
        ok &= check("нет caveats — не падает", sr.merge_script_caveats({"horizon_coverage": {}}) is None)
        return ok


def macro_ab() -> dict:
    """Макро-файл стенда (сценарии A, B): сетка 2026-09-30 / 2027-03-31, сроки стенда h6 2026-11-30 и h12 2027-05-31."""
    def g(a, b):
        return {"2026-09-30": {"value": a}, "2027-03-31": {"value": b}}
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


def test_macro_scenarios_option():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        st = build_skill_stress(d, snapshot())
        src = load(st)
        (d / "macro-new.yaml").write_text(yaml.safe_dump(macro_ab()), encoding="utf-8")
        r = run(d, st, snapshot(), output="m.yaml", extra=["--macro-scenarios", str(d / "macro-new.yaml")])
        ok = check("код 0", r.returncode == 0, r.stderr[-400:])
        out = load(d / "m.yaml")
        ok &= check("числовые факторы пересчитаны по сетке макро-файла, а не взяты из источника",
                    out["scenarios"]["A"]["factors_by_horizon"]["h6"]["brent"] != src["scenarios"]["A"]["factors_by_horizon"]["h6"]["brent"]
                    and abs(out["scenarios"]["A"]["factors_by_horizon"]["h12"]["brent"] - round((85 - 70) / 70 * 100, 4)) < 1e-9,
                    str(out["scenarios"]["A"]["factors_by_horizon"]["h12"]))
        ok &= check("санкционные и геополитические пути остаются из источника",
                    all(out["scenarios"][s]["factors_by_horizon"][h].get(k) == src["scenarios"][s]["factors_by_horizon"][h].get(k)
                        for s in "AB" for h in ("h6", "h12") for k in ("sanctions", "geopol")))
        ok &= check("сроки, baseline_spot и macro_input верхнего уровня обновлены",
                    out["horizon_ends"] == src["horizon_ends"] and out["baseline_spot"]["brent_usd"] == 70
                    and out["macro_input"] == "macro-new.yaml")
        ok &= check("horizon_coverage: h12 за сеткой — extrapolated, CI > 1", out["horizon_coverage"]["h12"]["status"] == "extrapolated"
                    and out["horizon_coverage"]["h12"]["ci_inflation"] > 1)
        ok &= check("recalc: macro_input, macro_input_was, reason macro, narrative_stale",
                    out["recalc"]["macro_input"] == "macro-new.yaml" and out["recalc"]["macro_input_was"] == src.get("macro_input")
                    and out["recalc"]["reason"] == "macro" and out["recalc"]["narrative_stale"] is True, str(out["recalc"]))
        ok &= check("оговорка о покрытии сроков пересобрана (одна запись скрипта)",
                    sum(c.get("source") == "script" for c in out["caveats"]) == 1)
        # причина «macro» не перекрывает существующие: новый снапшот остаётся «snapshot»
        r = run(d, st, snapshot(as_of="2026-05-20"), output="m2.yaml", extra=["--macro-scenarios", str(d / "macro-new.yaml")])
        ok &= check("снапшот сменился: reason остаётся snapshot, macro_input записан",
                    r.returncode == 0 and load(d / "m2.yaml")["recalc"]["reason"] == "snapshot"
                    and load(d / "m2.yaml")["recalc"]["macro_input"] == "macro-new.yaml")
        # без опции — блока macro_input в recalc нет
        run(d, st, snapshot(), output="n.yaml")
        ok &= check("без опции: полей macro_input нет в recalc", "macro_input" not in load(d / "n.yaml")["recalc"])
        # отказы: одним списком, файл не пишется
        bad = macro_ab()
        del bad["factors"]["usdrub_rate"]
        bad["scenario_matrix"] = {"source_file": "scenarios/other-matrix-2026-07-01.yaml"}
        src2 = copy.deepcopy(src)
        src2["scenario_matrix_ref"] = "scenarios/ssot.yaml"
        (d / "src2.yaml").write_text(asm.dump(src2), encoding="utf-8")
        (d / "macro-bad.yaml").write_text(yaml.safe_dump(bad), encoding="utf-8")
        r = run(d, d / "src2.yaml", snapshot(), output="x.yaml", extra=["--macro-scenarios", str(d / "macro-bad.yaml")])
        ok &= check("битый макро-файл и другая матрица — отказ 1 одним списком, файла нет", r.returncode == 1
                    and "usdrub_rate" in r.stderr and "other-matrix-2026-07-01" in r.stderr and not (d / "x.yaml").exists(),
                    r.stderr[-500:])
        r = run(d, st, snapshot(), output="x.yaml", extra=["--macro-scenarios", str(d / "нет.yaml")])
        ok &= check("макро-файла нет — отказ 1", r.returncode == 1 and "не найден" in r.stderr)
        r = run(d, st, snapshot(), output="macro-new.yaml", extra=["--macro-scenarios", str(d / "macro-new.yaml")])
        ok &= check("--output = --macro-scenarios — отказ", r.returncode != 0 and "совпадает" in r.stderr)
        return ok


TESTS = [
    test_script_caveats,
    test_same_snapshot_reproduces,
    test_changed_quantity_changes_numbers,
    test_new_ticker_needs_judgment,
    test_vanished_ticker_dropped,
    test_output_equals_stress_refused,
    test_recalc_block_and_judgment_carried,
    test_derived_fields_computed,
    test_underived_fields_stay_stale_with_reason,
    test_weights_json_valid,
    test_weights_json_same_as_stress,
    test_weights_json_refusals,
    test_deterministic,
    test_macro_scenarios_option,
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
