"""Тесты scripts/build_coherence_bundle.py — Stage P coherence-audit (детерминированная подготовка).

Покрытие: consistency gate (ok/missing/stale/conflict/degraded), нормализация дат/горизонтов,
assumption ledger (сценарии + macro-L1 уровни→дельты), contradiction candidates (конус + допуск,
sign-conflict), factor overlap (equity/bond split, reinforcing/offsetting, нулевая нога),
scenario blindspots (one-sided + locked pairs), mc_divergence, unrealizable/iis3,
consensus dispersion (understates/overstates + регрессия типа при отсутствии forecasts-dir),
e2e main() с exit-кодами 0/2.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import build_coherence_bundle as bcb  # noqa: E402

checks = 0
failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global checks, failed
    checks += 1
    if cond:
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}" + (f" — {detail}" if detail else ""))


ASOF = dt.date(2026, 7, 2)


# --------------------------------------------------------------------------- фикстуры
def make_snapshot(date="2026-07-02", holdings=None):
    return {
        "schema_version": "2.0",
        "as_of_date": date,
        "holdings": holdings if holdings is not None else [
            {"ticker": "SBER", "asset_type": "stock", "value_rub": 500000},
            {"ticker": "LKOH", "asset_type": "stock", "value_rub": 300000},
            {"ticker": "RU000A100001", "asset_type": "bond", "value_rub": 200000,
             "account": "iis_3", "duration_days": 1200, "maturity_date": "2030-01-01"},
            {"ticker": "FXUS", "asset_type": "fund", "value_rub": 100000, "is_blocked": True},
        ],
    }


def make_stress(snapshot_id="portfolio-2026-07-02.json", scenarios=None, per_position=None):
    return {
        "schema_version": 2,
        "portfolio_snapshot_id": snapshot_id,
        "dominant_factor": "usdrub",
        "concentration_ratio": 0.42,
        "baseline_spot": {"brent_usd": 80.0, "usdrub": 100.0, "cbr_rate_pct": 16.0},
        "factor_definitions": {"usdrub": "% vs spot", "cbr_rate": "п.п.", "brent": "% vs spot"},
        "scenarios": scenarios if scenarios is not None else {
            "A": {"factors_by_horizon": {
                "h6": {"usdrub": 5.0, "cbr_rate": -1.0, "brent": -10.0},
                "h12": {"usdrub": 10.0, "cbr_rate": -2.0, "brent": -5.0}}},
            "D": {"factors_by_horizon": {
                "h6": {"usdrub": 15.0, "cbr_rate": -0.5, "brent": 10.0},
                "h12": {"usdrub": 25.0, "cbr_rate": -3.0, "brent": 20.0}}},
        },
        "per_position": per_position if per_position is not None else {
            "SBER": {"weight_pct": 30.0, "factor_betas": {"usdrub": 0.5, "cbr_rate": -2.0}},
            "LKOH": {"weight_pct": 20.0, "factor_betas": {"usdrub": 0.8, "brent": 0.6}},
            "RU000A100001": {"weight_pct": 40.0, "factor_betas": {"usdrub": 0.2, "cbr_rate": -4.0}},
        },
        "bond_carry": {"per_position": {"RU000A100001": {}}},
    }


def make_weekly(snapshot_id="portfolio-2026-07-02.json", kind="stock"):
    per = {
        "SBER" if kind == "stock" else "RU000A100001": {
            "catalyst": [{"macro_dependency": "A"}, {"macro_dependency": None}],
        },
    }
    return {"schema_version": 2, "snapshot_id": snapshot_id, "per_stock": per}


def make_iv_md(snapshot_date="2026-07-02", pbh=None, tr=None):
    fm = {
        "schema_version": "integrated-view@1.3",
        "inputs": {"snapshot_date": snapshot_date},
        "portfolio_by_horizon": {"horizons": pbh or {
            "12": {"equity": {"value": 13.0, "ci": [5.0, 21.0]},
                   "bond": {"value": 18.0, "ci": [14.0, 22.0]}}}},
        "total_return": {"horizons": tr or {
            "12": {"expected": {"equity": 12.5, "bond": 25.0}}}},
        "tail_flags": {"flags": [{"ticker": "FXUS"}]},
    }
    return "---\n" + yaml.safe_dump(fm, allow_unicode=True) + "---\n\n# body\n"


def write_tree(root: Path, snapshot=None, stress=None, ws=None, wb=None, iv=None,
               date="2026-07-02"):
    (root / "Portfolio" / "snapshots").mkdir(parents=True, exist_ok=True)
    (root / "Portfolio" / "stress").mkdir(parents=True, exist_ok=True)
    (root / "Portfolio" / "weekly-reviews").mkdir(parents=True, exist_ok=True)
    (root / "Portfolio" / "integrated-views").mkdir(parents=True, exist_ok=True)
    (root / "Portfolio" / "snapshots" / f"portfolio-{date}.json").write_text(
        json.dumps(snapshot or make_snapshot(date)), encoding="utf-8")
    (root / "Portfolio" / "stress" / f"stress-{date}-test.yaml").write_text(
        yaml.safe_dump(stress or make_stress(f"portfolio-{date}.json")), encoding="utf-8")
    # стресс записан давно (до пересчёта в write_recalc): иначе пересчёт считался бы от прежней версии стресса
    _old = dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc).timestamp()
    os.utime(root / "Portfolio" / "stress" / f"stress-{date}-test.yaml", (_old, _old))
    (root / "Portfolio" / "weekly-reviews" / f"weekly-review-stock-{date}.yaml").write_text(
        yaml.safe_dump(ws or make_weekly(f"portfolio-{date}.json", "stock")), encoding="utf-8")
    (root / "Portfolio" / "weekly-reviews" / f"weekly-review-bond-{date}.yaml").write_text(
        yaml.safe_dump(wb or make_weekly(f"portfolio-{date}.json", "bond")), encoding="utf-8")
    (root / "Portfolio" / "integrated-views" / f"integrated-view-{date}.md").write_text(
        iv or make_iv_md(date), encoding="utf-8")


def prep_from_docs(docs, asof=ASOF, forecasts_dir=None):
    """Prep с готовыми docs без файлов (для юнит-уровня)."""
    p = bcb.Prep({}, asof, forecasts_dir=forecasts_dir)
    p.docs = docs
    return p


# --------------------------------------------------------------------------- [1] хелперы
print("[1] нормализация дат и горизонтов")
check("date_in из имени снапшота", bcb.date_in("portfolio-2026-07-02.json") == "2026-07-02")
check("date_in из чистой даты", bcb.date_in("2026-07-02") == "2026-07-02")
check("date_in None → None", bcb.date_in(None) is None)
check("date_in без даты → как есть", bcb.date_in("no-date-here") == "no-date-here")
check("norm_h h6 → m06", bcb.norm_h("h6") == "m06")
check("norm_h h12 → m12", bcb.norm_h("h12") == "m12")
check("norm_h 24 → m24", bcb.norm_h("24") == "m24")
check("norm_h год 2027 → y2027", bcb.norm_h("2027") == "y2027")
check("norm_h None → None", bcb.norm_h(None) is None)
check("age_days считает возраст", bcb.age_days("2026-06-25", ASOF) == 7)
check("age_days битая дата → None", bcb.age_days("не-дата", ASOF) is None)
check("as_float строка-число", bcb.as_float("3.5") == 3.5)
check("as_float мусор → None", bcb.as_float("abc") is None)

# --------------------------------------------------------------------------- [2] gate
print("\n[2] consistency gate")
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    write_tree(root)
    paths = bcb.discover(str(root))
    p = bcb.Prep(paths, ASOF)
    p.load_all()
    gate = p.consistency_gate()
    check("выровненное поколение → ok", gate["status"] == "ok", str(gate))
    check("snapshot_id нормализован", gate["snapshot_ids"]["stress"] == "2026-07-02")
    check("нет конфликта", gate["id_conflict"] is False)

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    write_tree(root, stress=make_stress("portfolio-2026-07-03.json"))
    p = bcb.Prep(bcb.discover(str(root)), ASOF)
    p.load_all()
    gate = p.consistency_gate()
    check("рассинхрон даты снапшота → stop", gate["status"] == "stop")
    check("конфликт зафиксирован", gate["id_conflict"] is True)
    check("причина называет расхождение",
          any("mismatch" in r for r in gate["reasons"]), str(gate["reasons"]))

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    write_tree(root)
    os.remove(root / "Portfolio" / "integrated-views" / "integrated-view-2026-07-02.md")
    p = bcb.Prep(bcb.discover(str(root)), ASOF)
    p.load_all()
    gate = p.consistency_gate()
    check("отсутствие обязательного входа → stop", gate["status"] == "stop")
    check("missing перечислен", "integrated_view" in gate["missing_required"])

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    old = "2026-06-01"  # 31 день до asof: снапшот протух (окно 14)
    write_tree(root, date=old, snapshot=make_snapshot(old),
               stress=make_stress(f"portfolio-{old}.json"),
               ws=make_weekly(f"portfolio-{old}.json"),
               wb=make_weekly(f"portfolio-{old}.json", "bond"),
               iv=make_iv_md(old))
    p = bcb.Prep(bcb.discover(str(root)), ASOF)
    p.load_all()
    gate = p.consistency_gate()
    check("протухшие входы → stop", gate["status"] == "stop")
    check("stale перечислены", "snapshot" in gate["stale_required"])

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    ws_nosid = make_weekly("portfolio-2026-07-02.json")
    del ws_nosid["snapshot_id"]
    write_tree(root, ws=ws_nosid)
    p = bcb.Prep(bcb.discover(str(root)), ASOF)
    p.load_all()
    gate = p.consistency_gate()
    check("нет snapshot_id у одного артефакта без конфликта → degraded",
          gate["status"] == "degraded", str(gate))
    check("degraded называет артефакт",
          any("weekly_stock" in r for r in gate["reasons"]))

# weekly как .md → narrative fallback, snapshot_id не извлекается
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    write_tree(root)
    ypath = root / "Portfolio" / "weekly-reviews" / "weekly-review-stock-2026-07-02.yaml"
    os.remove(ypath)
    mdp = root / "Portfolio" / "weekly-reviews" / "weekly-review-stock-2026-07-02.md"
    mdp.write_text("# нарратив\nпро акции", encoding="utf-8")
    paths = bcb.discover(str(root))
    paths["weekly_stock"] = str(mdp)
    p = bcb.Prep(paths, ASOF)
    p.load_all()
    gate = p.consistency_gate()
    check("weekly .md → degraded (не stop)", gate["status"] == "degraded")
    check(".md помечен в notes", any("narrative" in n for n in p.notes))

# --------------------------------------------------------------------------- [3] ledger
print("\n[3] assumption ledger")
mm = {"factors": {
    "usdrub_rate": {"level_l1_2026-12-31": 110.0, "level_l1_2027-06-30": 120.0},
    "cbr_rate": {"level_l1_2026-12-31": 14.0},
    "unknown_factor": {"level_l1_2026-12-31": 1.0},
}}
p = prep_from_docs({"stress": make_stress(), "macro_marginal": mm})
ledger = p.assumption_ledger()
sc_rows = [e for e in ledger if e["source_class"] == "scenario"]
pt_rows = [e for e in ledger if e["source_class"] == "point"]
check("сценарные строки собраны (2 сценария × 2 горизонта × 3 фактора)", len(sc_rows) == 12)
check("горизонты нормализованы", {e["horizon"] for e in sc_rows} == {"m06", "m12"})
usd_pts = [e for e in pt_rows if e["factor"] == "usdrub"]
check("L1 usdrub: уровень 110 при базе 100 → +10%",
      any(abs(e["value"] - 10.0) < 1e-6 for e in usd_pts), str(usd_pts))
check("L1 usdrub: даты упорядочены → m06/m12",
      [e["horizon"] for e in sorted(usd_pts, key=lambda x: x["horizon"])] == ["m06", "m12"])
cbr_pts = [e for e in pt_rows if e["factor"] == "cbr_rate"]
check("L1 cbr_rate: 14 при базе 16 → −2 п.п. (не %)",
      any(abs(e["value"] + 2.0) < 1e-6 for e in cbr_pts), str(cbr_pts))
check("неизвестный macro-фактор без маппинга пропущен",
      not any("unknown" in e["source"] for e in ledger))
check("L1-конвертация задокументирована в notes",
      any("LEVELS->deltas" in n for n in p.notes))

p2 = prep_from_docs({"stress": make_stress()})
check("без macro-marginal — только scenario-строки",
      all(e["source_class"] == "scenario" for e in p2.assumption_ledger()))

# --------------------------------------------------------------------------- [4] contradictions
print("\n[4] contradiction candidates")
p = prep_from_docs({"stress": make_stress()})
led_sc = p.assumption_ledger()
check("один конус без точек → кандидатов нет", p.contradiction_candidates(led_sc) == [])

# точка внутри конуса (usdrub m06: конус [5,15], точка 10) → нет кандидата
inside = led_sc + [{"source": "macro-L1:usdrub_rate", "source_class": "point",
                    "factor": "usdrub", "horizon": "m06", "value": 10.0}]
check("точка внутри конуса → нет противоречия", p.contradiction_candidates(inside) == [])

# точка вне конуса с запасом больше допуска → кандидат
outside = led_sc + [{"source": "macro-L1:usdrub_rate", "source_class": "point",
                     "factor": "usdrub", "horizon": "m06", "value": 30.0}]
cands = p.contradiction_candidates(outside)
check("точка вне конуса → кандидат", len(cands) == 1)
check("кандидат несёт конус и точку",
      cands[0]["scenario_cone"] == [5.0, 15.0] and
      cands[0]["points_outside_cone"] == {"macro-L1:usdrub_rate": 30.0})

# точка чуть за границей, внутри допуска (5% ширины конуса) → шум отфильтрован
near = led_sc + [{"source": "macro-L1:usdrub_rate", "source_class": "point",
                  "factor": "usdrub", "horizon": "m06", "value": 15.3}]
check("допуск гасит пограничный шум", p.contradiction_candidates(near) == [])

# два точечных взгляда с конфликтом знака → кандидат даже внутри конуса
sign = led_sc + [
    {"source": "macro-L1:a", "source_class": "point", "factor": "cbr_rate", "horizon": "m06", "value": 0.5},
    {"source": "macro-L1:b", "source_class": "point", "factor": "cbr_rate", "horizon": "m06", "value": -0.5},
]
sc_cands = p.contradiction_candidates(sign)
check("sign-conflict двух точек → кандидат",
      any(c["point_sign_conflict"] for c in sc_cands), str(sc_cands))
check("sign-conflict сортируется первым",
      sc_cands and sc_cands[0]["point_sign_conflict"] is True)

# --------------------------------------------------------------------------- [5] overlap
print("\n[5] factor overlap")
p = prep_from_docs({"stress": make_stress(), "snapshot": make_snapshot()})
ov = p.factor_overlap()
rows = {r["factor"]: r for r in ov["rows"]}
check("счётчики ног: 2 акции + 1 облигация",
      ov["n_equity_positions"] == 2 and ov["n_bond_positions"] == 1)
# equity usdrub = 0.5*30/100 + 0.8*20/100 = 0.31; bond usdrub = 0.2*40/100 = 0.08
check("equity-экспозиция usdrub = Σβ·вес", abs(rows["usdrub"]["equity_exposure"] - 0.31) < 1e-9)
check("bond-экспозиция usdrub", abs(rows["usdrub"]["bond_exposure"] - 0.08) < 1e-9)
check("usdrub обе ноги в одну сторону → reinforcing",
      rows["usdrub"]["both_legs"] and rows["usdrub"]["direction"] == "reinforcing")
check("cbr_rate обе ноги отрицательные → reinforcing",
      rows["cbr_rate"]["direction"] == "reinforcing")
check("brent только equity → both_legs=False, direction=None",
      rows["brent"]["both_legs"] is False and rows["brent"]["direction"] is None)
check("reinforcing-строки отсортированы наверх",
      ov["rows"][0]["direction"] == "reinforcing")
check("passthrough dominant/concentration",
      ov["stress_dominant_factor"] == "usdrub" and ov["stress_concentration_ratio"] == 0.42)

# нулевая нога: бонд с β=0 по usdrub → нога нематериальна
st0 = make_stress(per_position={
    "SBER": {"weight_pct": 30.0, "factor_betas": {"usdrub": 0.5}},
    "RU000A100001": {"weight_pct": 40.0, "factor_betas": {"usdrub": 0.0}},
})
p0 = prep_from_docs({"stress": st0, "snapshot": make_snapshot()})
r0 = {r["factor"]: r for r in p0.factor_overlap()["rows"]}
check("нулевая bond-нога → both_legs=False (нет ложного reinforcing)",
      r0["usdrub"]["both_legs"] is False)

# offsetting: ноги в разные стороны
st_off = make_stress(per_position={
    "SBER": {"weight_pct": 30.0, "factor_betas": {"brent": 0.6}},
    "RU000A100001": {"weight_pct": 40.0, "factor_betas": {"brent": -0.3}},
})
p_off = prep_from_docs({"stress": st_off, "snapshot": make_snapshot()})
r_off = {r["factor"]: r for r in p_off.factor_overlap()["rows"]}
check("разнонаправленные ноги → offsetting", r_off["brent"]["direction"] == "offsetting")

# --------------------------------------------------------------------------- [6] blindspots
print("\n[6] scenario blindspots")
p = prep_from_docs({"stress": make_stress()})
bs = p.scenario_blindspots()
os_f = {r["factor"]: r for r in bs["one_sided_factors"]}
check("cbr_rate всегда вниз → one-sided '-'",
      "cbr_rate" in os_f and os_f["cbr_rate"]["sign"] == "-")
check("usdrub всегда вверх → one-sided '+'",
      "usdrub" in os_f and os_f["usdrub"]["sign"] == "+")
check("brent меняет знак → не one-sided", "brent" not in os_f)
check("один varying фактор → locked_pairs пуст", bs["locked_pairs"] == [])

# два varying фактора, всегда в одну сторону → super-factor
st_lock = make_stress(scenarios={
    "A": {"factors_by_horizon": {"h6": {"x": 1.0, "y": 2.0}, "h12": {"x": -1.0, "y": -2.0}}},
    "D": {"factors_by_horizon": {"h6": {"x": 3.0, "y": 1.0}}},
})
bs_l = prep_from_docs({"stress": st_lock}).scenario_blindspots()
check("постоянный совместный знак → super-factor",
      any(l["relation"] == "super-factor" for l in bs_l["locked_pairs"]), str(bs_l["locked_pairs"]))

st_hedge = make_stress(scenarios={
    "A": {"factors_by_horizon": {"h6": {"x": 1.0, "y": -2.0}, "h12": {"x": -1.0, "y": 2.0}}},
})
bs_h = prep_from_docs({"stress": st_hedge}).scenario_blindspots()
check("постоянно противоположный знак → structural-hedge",
      any(l["relation"] == "structural-hedge" for l in bs_h["locked_pairs"]))

# --------------------------------------------------------------------------- [7] mc_divergence
print("\n[7] mc_divergence")
p = prep_from_docs({"integrated_view": {"frontmatter": yaml.safe_load(
    make_iv_md().split("---")[1])}})
mc = p.mc_divergence()
by_leg = {(r["horizon"], r["leg"]): r for r in mc["rows"]}
eq = by_leg[("m12", "equity")]
check("equity: gap 0.5 ≤ 2пп и CI покрывает headline → не флагнут", eq["diverges"] is False)
bd = by_leg[("m12", "bond")]
check("bond: gap 7пп → флагнут", bd["diverges"] is True)
check("bond: CI [14,22] не покрывает expected 25", bd["ci_covers_expected"] is False)
check("flagged содержит только bond",
      [r["leg"] for r in mc["flagged"]] == ["bond"])

# CI не покрывает headline при малом gap → тоже флаг
iv2 = {"portfolio_by_horizon": {"horizons": {"12": {"equity": {"value": 13.0, "ci": [14.0, 20.0]}}}},
       "total_return": {"horizons": {"12": {"expected": {"equity": 13.5}}}}}
mc2 = prep_from_docs({"integrated_view": {"frontmatter": iv2}}).mc_divergence()
check("CI не покрывает headline → diverges даже при gap<2",
      mc2["rows"][0]["diverges"] is True)

# --------------------------------------------------------------------------- [8] unrealizable + iis3
print("\n[8] unrealizable_exposure / iis3")
p = prep_from_docs({"snapshot": make_snapshot(), "stress": make_stress(),
                    "integrated_view": {"frontmatter": yaml.safe_load(make_iv_md().split("---")[1])}})
un = p.unrealizable_exposure()
check("blocked-доля: 100k из 1.1M ≈ 9.09%", abs(un["blocked_pct_snapshot"] - 9.09) < 0.01)
check("blocked-тикеры перечислены", un["blocked_tickers"] == ["FXUS"])
check("пересечение с tail-flags", un["blocked_and_tail_flagged"] == ["FXUS"])

ii = p.iis3_summary()
check("ИИС-3: одна позиция", ii["n_positions"] == 1)
check("дюрация прокинута", ii["max_duration_days"] == 1200)
check("нет ИИС-позиций → note", prep_from_docs(
    {"snapshot": {"holdings": []}}).iis3_summary()["n_positions"] == 0)

# --------------------------------------------------------------------------- [9] consensus
print("\n[9] consensus dispersion")
p = prep_from_docs({"stress": make_stress()}, forecasts_dir=None)
res = p.consensus()
check("без forecasts-dir → пустой СПИСОК (регрессия кортежа [[],[]])",
      res == [] and isinstance(res, list) and len(res) == 0)

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    fdir = root / "forecasts"
    fdir.mkdir()
    # конус usdrub m06 = [5,15] (ширина 10); аналитики: узкий и широкий диапазоны уровней
    fc = {"forecast": {"topic": "usdrub-2026"},
          "conditional_on_scenarios": {"marginal": {"values": {
              "2026-12-31": {"central": 110, "range": [104.0, 106.0]},   # дельты [4,6] ширина 2 → конус шире ×5
              "2027-06-30": {"central": 120, "range": [90.0, 140.0]},    # дельты [-10,40] ширина 50 → конус уже
          }}}}
    (fdir / "usdrub-2026-07-02.yaml").write_text(yaml.safe_dump(fc), encoding="utf-8")
    p = prep_from_docs({"stress": make_stress(),
                        "snapshot": make_snapshot()}, forecasts_dir=str(fdir))
    disp = p.consensus()
    by_h = {d["horizon"]: d for d in disp}
    check("уровни→дельты против baseline_spot",
          by_h["m06"]["consensus_range_delta"] == [4.0, 6.0], str(disp))
    check("конус шире аналитики → overstates dispersion",
          by_h["m06"]["flag"] == "stress overstates dispersion")
    check("конус уже аналитики → understates dispersion",
          by_h["m12"]["flag"] == "stress understates dispersion")
    check("note про dispersion добавлена", any("dispersion" in n for n in p.notes))

    # discount-topic отфильтрован
    (fdir / "urals-brent-discount-2026-07-02.yaml").write_text(
        yaml.safe_dump({"forecast": {"topic": "urals-brent-discount"},
                        "conditional_on_scenarios": {"marginal": {"values": {}}}}), encoding="utf-8")
    p = prep_from_docs({"stress": make_stress(), "snapshot": make_snapshot()},
                       forecasts_dir=str(fdir))
    check("discount-топик не попадает в dispersion",
          all(d["factor"] != "urals" for d in p.consensus()))

# --------------------------------------------------------------------------- [10] weekly lean + passthrough
print("\n[10] weekly_scenario_dependency / passthrough")
p = prep_from_docs({"weekly_stock": make_weekly(), "weekly_bond": make_weekly(kind="bond"),
                    "stress": make_stress(),
                    "integrated_view": {"frontmatter": yaml.safe_load(make_iv_md().split("---")[1])}})
wd = p.weekly_scenario_dependency()
check("подсчёт scenario-тегов катализаторов", wd["weekly_stock"] == {"A": 1, "none": 1})
check(".md-weekly → None", prep_from_docs(
    {"weekly_stock": {"_is_md": True}}).weekly_scenario_dependency()["weekly_stock"] is None)
pt = p.passthrough()
check("passthrough несёт concentration_ratio", pt["stress"]["concentration_ratio"] == 0.42)
check("passthrough несёт portfolio_by_horizon",
      "portfolio_by_horizon" in pt["integrated_view"])

# --------------------------------------------------------------------------- [11] joint_tail (v1.4)
print("\n[11] joint_tail")
st_jt = make_stress(per_position={
    "SBER": {"weight_pct": 30.0, "factor_betas": {"usdrub": 0.5}, "by_horizon": {
        "h12": {"delta_pct_by_scenario": {"A": {"value": -10.0}, "D": {"value": 5.0}}}}},
    "LKOH": {"weight_pct": 20.0, "factor_betas": {"usdrub": 0.8}, "by_horizon": {
        "h12": {"delta_pct_by_scenario": {"A": {"value": -20.0}, "D": {"value": 10.0}}}}},
    "RU000A100001": {"weight_pct": 40.0, "factor_betas": {"cbr_rate": -4.0}, "by_horizon": {
        "h12": {"delta_pct_by_scenario": {"A": {"value": -5.0}, "D": {"value": 3.0}}}}},
})
st_jt["scenarios"]["A"]["probability"] = 0.3
p = prep_from_docs({"stress": st_jt, "snapshot": make_snapshot()})
jt = p.joint_tail()
cells = {(c["scenario"], c["horizon"]): c for c in jt["cells"]}
a12 = cells[("A", "m12")]
# equity A: (-10·30 + -20·20)/50 = -14; bond A: -5; combined: (-14·50 + -5·40)/90 = -10
check("equity-нога: взвешенная дельта", abs(a12["equity_delta_pct"] + 14.0) < 1e-6)
check("bond-нога: взвешенная дельта", abs(a12["bond_delta_pct"] + 5.0) < 1e-6)
check("combined по стоимостному базису", abs(a12["combined_delta_pct"] + 10.0) < 1e-3)
check("обе ноги минусовые → joint_drawdown", a12["joint_drawdown"] is True)
check("вероятность сценария прокинута", a12["probability"] == 0.3)
d12 = cells[("D", "m12")]
check("обе ноги плюсовые → не joint_drawdown", d12["joint_drawdown"] is False)
check("worst = худшая joint-ячейка", jt["worst"]["scenario"] == "A")
check("счётчик joint-ячеек", jt["n_joint_drawdown_cells"] == 1)
check("сортировка: худшая combined первой", jt["cells"][0]["scenario"] == "A")
check("carry-ограничение задокументировано", "carry" in jt["note"])

check("источник вероятности подписан", a12["probability_source"] == "scalar")

# graceful: старый stress без by_horizon
p_old = prep_from_docs({"stress": make_stress(), "snapshot": make_snapshot()})
jt_old = p_old.joint_tail()
check("stress без by_horizon → пустой блок + note",
      jt_old["cells"] == [] and jt_old["worst"] is None and
      any("joint_tail" in n for n in p_old.notes))

# PSS-9: ключ ячейки — пара (сценарий, горизонт), поэтому подпись «probability»
# обязана быть весом ЭТОГО горизонта, когда задан p_by_horizon. Арифметики в
# блоке нет, но скалярная подпись рядом с горизонтной ячейкой — ложь по смыслу.
st_hz = make_stress(per_position={
    "SBER": {"weight_pct": 60.0, "factor_betas": {"usdrub": 0.5}, "by_horizon": {
        "h12": {"delta_pct_by_scenario": {"A": {"value": -10.0}, "D": {"value": 5.0}}},
        "h36": {"delta_pct_by_scenario": {"A": {"value": -12.0}, "D": {"value": 8.0}}}}},
    "RU000A100001": {"weight_pct": 40.0, "factor_betas": {"cbr_rate": -4.0}, "by_horizon": {
        "h12": {"delta_pct_by_scenario": {"A": {"value": -5.0}, "D": {"value": 3.0}}},
        "h36": {"delta_pct_by_scenario": {"A": {"value": -6.0}, "D": {"value": 4.0}}}}},
})
# Σ по горизонту намеренно != 1 (0.8+1.2 и 1.5+0.5) — нормировка обязана сработать.
# Скаляр задан и ОТЛИЧАЕТСЯ от обеих горизонтных долей: реализация, оставшаяся на
# скаляре, даёт неверное число, а не None (None прошёл бы как «поле не заполнено»).
st_hz["scenarios"]["A"].update({"probability": 0.55, "p_by_horizon": {"h12": 0.8, "h36": 1.5}})
st_hz["scenarios"]["D"].update({"probability": 0.45, "p_by_horizon": {"h12": 1.2, "h36": 0.5}})
jt_hz = prep_from_docs({"stress": st_hz, "snapshot": make_snapshot()}).joint_tail()
c_hz = {(c["scenario"], c["horizon"]): c for c in jt_hz["cells"]}
check("PSS-9: вес A на m12 = 0.8/2.0", abs(c_hz[("A", "m12")]["probability"] - 0.4) < 1e-9)
check("PSS-9: вес A на m36 = 1.5/2.0", abs(c_hz[("A", "m36")]["probability"] - 0.75) < 1e-9)
check("PSS-9: подпись источника", c_hz[("A", "m36")]["probability_source"] == "p_by_horizon")
check("PSS-9: горизонты различаются (иначе проверка вырождена)",
      c_hz[("A", "m12")]["probability"] != c_hz[("A", "m36")]["probability"])

# Блок у ЧАСТИ сценариев к подписи не годится — тихо остаёмся на скаляре.
st_part = make_stress(per_position=st_hz["per_position"])
st_part["scenarios"]["A"]["p_by_horizon"] = {"h12": 0.8, "h36": 1.5}
st_part["scenarios"]["A"]["probability"] = 0.3
jt_part = prep_from_docs({"stress": st_part, "snapshot": make_snapshot()}).joint_tail()
c_part = {(c["scenario"], c["horizon"]): c for c in jt_part["cells"]}
check("PSS-9: частичный блок → скаляр",
      c_part[("A", "m12")]["probability"] == 0.3 and
      c_part[("A", "m12")]["probability_source"] == "scalar")

# --------------------------------------------------------------------------- [12] confidence L1 (v1.4)
print("\n[12] confidence у L1-точек")
mm_c = {"factors": {"usdrub_rate": {"level_l1_2026-12-31": 130.0, "confidence": 0.72}}}
p = prep_from_docs({"stress": make_stress(), "macro_marginal": mm_c})
led = p.assumption_ledger()
pt = [e for e in led if e["source_class"] == "point"][0]
check("confidence из macro-marginal в ledger", pt["confidence"] == 0.72)
cands = p.contradiction_candidates(led)
check("point_confidence в кандидате",
      cands and cands[0]["point_confidence"] == {"macro-L1:usdrub_rate": 0.72}, str(cands))
mm_nc = {"factors": {"usdrub_rate": {"level_l1_2026-12-31": 130.0}}}
p2 = prep_from_docs({"stress": make_stress(), "macro_marginal": mm_nc})
pt2 = [e for e in p2.assumption_ledger() if e["source_class"] == "point"][0]
check("нет confidence → None (не падает)", pt2["confidence"] is None)

# --------------------------------------------------------------------------- [13] diachronic (v1.4)
print("\n[13] diachronic")
cur = {
    "contradiction_candidates": [{"factor": "usdrub", "horizon": "m06"},
                                 {"factor": "brent", "horizon": "m12"}],
    "scenario_blindspots": {"one_sided_factors": [{"factor": "cbr_rate"}]},
    "mc_divergence": {"flagged": [{"horizon": "m12", "leg": "bond"}]},
    "factor_overlap": {"rows": [
        {"factor": "usdrub", "both_legs": True, "direction": "reinforcing"},
        {"factor": "brent", "both_legs": True, "direction": "offsetting"}]},
    "consensus_dispersion": [],
}
prev_b = {
    "as_of": "2026-06-01",
    "contradiction_candidates": [{"factor": "usdrub", "horizon": "m06"},
                                 {"factor": "cbr_rate", "horizon": "m06"}],
    "scenario_blindspots": {"one_sided_factors": [{"factor": "cbr_rate"}]},
    "mc_divergence": {"flagged": []},
    "factor_overlap": {"rows": [{"factor": "usdrub", "both_legs": True, "direction": "reinforcing"}]},
    "consensus_dispersion": [{"factor": "brent", "horizon": "m06",
                              "flag": "stress understates dispersion"}],
}
with tempfile.TemporaryDirectory() as td:
    pb = Path(td) / "coherence-input-bundle-2026-06-01.json"
    pb.write_text(json.dumps(prev_b), encoding="utf-8")
    p = prep_from_docs({})
    dia = p.diachronic(cur, str(pb))
    check("prev метаданные", dia["prev_as_of"] == "2026-06-01")
    check("новое противоречие", dia["contradictions"]["new"] == ["brent/m12"])
    check("висящее противоречие", dia["contradictions"]["persisting"] == ["usdrub/m06"])
    check("закрывшееся противоречие", dia["contradictions"]["closed"] == ["cbr_rate/m06"])
    check("one-sided висит", dia["one_sided_factors"]["persisting"] == ["cbr_rate"])
    check("новый mc-флаг", dia["mc_flags"]["new"] == ["m12/bond"])
    check("offsetting не считается reinforcing-сигналом",
          dia["reinforcing_factors"]["new"] == [])
    check("consensus-флаг закрылся",
          dia["consensus_flags"]["closed"] == ["brent/m06:stress understates dispersion"])
p = prep_from_docs({})
check("нет прошлого bundle → None + note",
      p.diachronic(cur, None) is None and any("первый прогон" in n for n in p.notes))

# --------------------------------------------------------------------------- [14] watch_verdict (v1.4)
print("\n[14] watch_verdict")
wv = bcb.Prep.watch_verdict(
    {"contradiction_candidates": [1], "mc_divergence": {"flagged": []},
     "joint_tail": {"n_joint_drawdown_cells": 2}}, None)
check("первый прогон → fable_recommended", wv["fable_recommended"] is True)
check("baseline-сигнал назван", any("первый прогон" in s for s in wv["signals"]))
check("counts заполнены", wv["counts"] == {"contradictions": 1, "mc_flagged": 0,
                                           "joint_drawdown_cells": 2})
dia_quiet = {k: {"new": [], "persisting": ["x"], "closed": []}
             for k in ("contradictions", "mc_flags", "one_sided_factors",
                       "reinforcing_factors", "consensus_flags")}
wv_q = bcb.Prep.watch_verdict(
    {"contradiction_candidates": [1], "mc_divergence": {"flagged": [1]},
     "joint_tail": {"n_joint_drawdown_cells": 0}}, dia_quiet)
check("только висящие сигналы → Fable НЕ рекомендован", wv_q["fable_recommended"] is False)
check("вердикт объясняет, что false ≠ запрет", "не запрет" in wv_q["note"] or "запрет" in wv_q["note"])
dia_new = dict(dia_quiet, contradictions={"new": ["brent/m12"], "persisting": [], "closed": []})
wv_n = bcb.Prep.watch_verdict(
    {"contradiction_candidates": [1], "mc_divergence": {"flagged": []},
     "joint_tail": {}}, dia_new)
check("новое противоречие → Fable рекомендован",
      wv_n["fable_recommended"] is True and any("brent/m12" in s for s in wv_n["signals"]))

# --------------------------------------------------------------------------- [15] e2e main()
print("\n[15] e2e main() и exit-коды")
with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    write_tree(root)
    out = root / "bundle.json"
    rc = bcb.main(["--dir", str(root), "--asof", "2026-07-02", "--out", str(out)])
    check("выровненное поколение → exit 0", rc == 0)
    b = json.loads(out.read_text(encoding="utf-8"))
    check("schema_version bundle", b["schema_version"] == bcb.SCHEMA)
    check("consistency ok в bundle", b["consistency"]["status"] == "ok")
    check("generated_utc в ISO-Z", b["generated_utc"].endswith("Z") and "T" in b["generated_utc"])
    check("все v1.3/v1.4-блоки на месте",
          all(k in b for k in ("scenario_blindspots", "mc_divergence", "unrealizable_exposure",
                               "iis3", "consensus_dispersion", "factor_overlap",
                               "contradiction_candidates", "assumption_ledger",
                               "joint_tail", "diachronic", "watch_verdict")))
    check("consensus_dispersion — список (не кортеж-артефакт)",
          isinstance(b["consensus_dispersion"], list) and
          all(isinstance(x, dict) for x in b["consensus_dispersion"]))
    check("fable_task_pointer присутствует", "Stage R" in b["fable_task_pointer"])
    check("первый прогон: diachronic=None, watch рекомендует baseline",
          b["diachronic"] is None and b["watch_verdict"]["fable_recommended"] is True)

    # второй прогон: авто-дискавери прошлого bundle рядом с --out
    write_tree(root, date="2026-07-09", snapshot=make_snapshot("2026-07-09"),
               stress=make_stress("portfolio-2026-07-09.json"),
               ws=make_weekly("portfolio-2026-07-09.json"),
               wb=make_weekly("portfolio-2026-07-09.json", "bond"),
               iv=make_iv_md("2026-07-09"))
    out2 = root / f"coherence-input-bundle-2026-07-09.json"
    # прошлый bundle кладём под каноничным именем рядом
    (root / "coherence-input-bundle-2026-07-02.json").write_text(
        out.read_text(encoding="utf-8"), encoding="utf-8")
    rc2 = bcb.main(["--dir", str(root), "--asof", "2026-07-09", "--out", str(out2)])
    b2 = json.loads(out2.read_text(encoding="utf-8"))
    check("второй прогон: прошлый bundle авто-найден",
          rc2 == 0 and b2["diachronic"] is not None and
          b2["diachronic"]["prev_as_of"] == "2026-07-02", str(b2.get("diachronic")))
    check("идентичные сигналы → новых нет → Fable не рекомендован",
          b2["watch_verdict"]["fable_recommended"] is False, str(b2["watch_verdict"]))

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    write_tree(root, stress=make_stress("portfolio-2026-06-30.json"))
    out = root / "bundle.json"
    rc = bcb.main(["--dir", str(root), "--asof", "2026-07-02", "--out", str(out)])
    check("рассинхрон поколения → exit 2 (HARD STOP)", rc == 2)
    b = json.loads(out.read_text(encoding="utf-8"))
    check("bundle при stop всё же записан с диагностикой",
          b["consistency"]["status"] == "stop" and b["consistency"]["reasons"])

# --------------------------------------------------------------------------- пересчёт сайта
print("\n[R] пересчёт сайта (auto/recalc-<стресс>)")


def write_recalc(root, date="2026-07-02", snapshot_id="portfolio-2026-07-09.json", source=None, **over):
    st = make_stress(snapshot_id)
    st["run_id"] = "RECALC-x"
    st["recalc"] = {"source_stress": source or f"stress-{date}-test.yaml", "source_kind": "stress",
                    "source_snapshot_id": f"portfolio-{date}.json", "snapshot_id": snapshot_id,
                    "reason": "snapshot", "at": "2026-07-09T10:00:00+03:00", "narrative_stale": True, **over}
    d = root / "Portfolio" / "stress" / "auto"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"recalc-stress-{date}-test.yaml").write_text(yaml.safe_dump(st, allow_unicode=True), encoding="utf-8")


def load_prep(root, auto=True):
    p = bcb.Prep(bcb.discover(str(root)), ASOF, auto_recalc=auto)
    p.load_all()
    return p


with tempfile.TemporaryDirectory() as td:
    root = Path(td); write_tree(root); write_recalc(root)
    p = load_prep(root)
    prov = p._prov("stress")
    check("пересчёт взят: numbers_path", prov.get("numbers_path", "").endswith("recalc-stress-2026-07-02-test.yaml"), str(prov))
    check("числа из пересчёта", p.docs["stress"]["run_id"] == "RECALC-x")
    check("возраст — по стрессу скилла", prov["date"] == "2026-07-02" and prov["age_days"] == bcb.age_days("2026-07-02", ASOF), str(prov))
    check("path остаётся стрессом скилла", prov["path"].endswith("stress-2026-07-02-test.yaml"))
    info = prov["stress_recalc"]
    check("stress_recalc: ключи", {"source_stress", "judgments_date", "snapshot_id", "source_snapshot_id", "at",
                                   "reason", "narrative_stale", "message"} <= set(info), str(info))
    check("stress_recalc: дата суждений", info["judgments_date"] == "2026-07-02")
    check("auto/ не попадает в выбор стресса", bcb.discover(str(root))["stress"].endswith("stress-2026-07-02-test.yaml"))
    gate = p.consistency_gate()
    check("gate сравнивает snapshot_id пересчёта (конфликт со снапшотом 07-02)",
          gate["snapshot_ids"]["stress"] == "2026-07-09" and gate["id_conflict"], str(gate))
    b, _ = bcb.Prep(bcb.discover(str(root)), ASOF, auto_recalc=True).build()
    check("bundle.stress_recalc", b["stress_recalc"]["snapshot_id"] == "portfolio-2026-07-09.json")

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    write_tree(root, date="2026-07-09", snapshot=make_snapshot("2026-07-09"),
               stress=make_stress("portfolio-2026-07-02.json"))
    write_recalc(root, date="2026-07-09", snapshot_id="portfolio-2026-07-09.json")
    gate = load_prep(root).consistency_gate()
    check("gate: пересчёт на свежем снапшоте сходится", gate["snapshot_ids"]["stress"] == "2026-07-09", str(gate))

with tempfile.TemporaryDirectory() as td:
    root = Path(td); write_tree(root); write_recalc(root, source="stress-2026-06-01-other.yaml")
    p = load_prep(root)
    check("пересчёт другого стресса не взят", "numbers_path" not in p._prov("stress") and p.docs["stress"].get("run_id") != "RECALC-x")
    check("предупреждение о причине", "stress_recalc_warning" in p._prov("stress"))

with tempfile.TemporaryDirectory() as td:
    root = Path(td); write_tree(root)
    (root / "Portfolio" / "stress" / "auto").mkdir()
    (root / "Portfolio" / "stress" / "auto" / "recalc-stress-2026-07-02-test.yaml").write_text("{: [bad", encoding="utf-8")
    p = load_prep(root)
    check("битый пересчёт не роняет, предупреждение", "stress_recalc_warning" in p._prov("stress") and "numbers_path" not in p._prov("stress"))

with tempfile.TemporaryDirectory() as td:
    root = Path(td); write_tree(root); write_recalc(root)
    p = load_prep(root, auto=False)
    check("явный путь (auto_recalc=False): пересчёт не подставляется", "numbers_path" not in p._prov("stress"))

with tempfile.TemporaryDirectory() as td:
    root = Path(td); write_tree(root)
    p = load_prep(root)
    check("без auto/: поведение прежнее", "numbers_path" not in p._prov("stress") and "stress_recalc_warning" not in p._prov("stress"))

print("\n[R] выбор стресса по времени записи и устаревший пересчёт")


def _utime(path, iso):
    ts = dt.datetime.fromisoformat(iso).timestamp()
    os.utime(path, (ts, ts))


with tempfile.TemporaryDirectory() as td:
    d = Path(td) / "Portfolio" / "stress"
    d.mkdir(parents=True)
    a = d / "stress-2026-07-02-b.yaml"
    b = d / "stress-2026-07-02-a.yaml"
    for f in (a, b):
        f.write_text("a: 1", encoding="utf-8")
    _utime(a, "2026-07-02T10:00:00+00:00"); _utime(b, "2026-07-02T12:00:00+00:00")
    check("одна дата: записанный позже побеждает при любом имени", bcb.latest_stress(str(d / "stress-*.yaml")) == str(b))
    check("discover берёт стресс по той же ключевой тройке", bcb.discover(td)["stress"] == str(b))
    _utime(a, "2026-07-02T14:00:00+00:00")
    check("запись другого файла позже — он новее", bcb.latest_stress(str(d / "stress-*.yaml")) == str(a))
    _utime(a, "2026-07-02T12:00:00+00:00")
    check("равное время записи — по имени", bcb.latest_stress(str(d / "stress-*.yaml")) == str(a))
    old = d / "stress-2026-06-01-x.yaml"
    old.write_text("a: 1", encoding="utf-8"); _utime(old, "2026-12-01T00:00:00+00:00")
    check("старая дата с поздней записью не побеждает", bcb.latest_stress(str(d / "stress-*.yaml")) == str(a))
    check("нет файлов -> None", bcb.latest_stress(str(Path(td) / "нет" / "stress-*.yaml")) is None)

with tempfile.TemporaryDirectory() as td:
    root = Path(td); write_tree(root); write_recalc(root)       # at = 2026-07-09T10:00+03:00
    sp = root / "Portfolio" / "stress" / "stress-2026-07-02-test.yaml"
    _utime(sp, "2026-07-10T00:00:00+03:00")
    r = bcb.find_recalc(str(sp))
    w = r.get("warning", "")
    check("пересчёт раньше записи стресса: не взят, предупреждение",
          "path" not in r and w.startswith("stress_recalc_skipped") and "до последней записи" in w, str(r))
    p = load_prep(root)
    check("числа остаются из стресса скилла", "numbers_path" not in p._prov("stress") and p.docs["stress"].get("run_id") != "RECALC-x")
    check("предупреждение попало в provenance", "до последней записи" in p._prov("stress").get("stress_recalc_warning", ""))
    _utime(sp, "2026-07-09T10:00:00+03:00")
    check("та же секунда: пересчёт берётся", "path" in bcb.find_recalc(str(sp)))
    _utime(sp, "2026-07-09T09:00:00+03:00")
    check("пересчёт позже записи: берётся", "path" in bcb.find_recalc(str(sp)))

with tempfile.TemporaryDirectory() as td:
    root = Path(td); write_tree(root); write_recalc(root, at="2026-07-09T10:00:00")   # без пояса — МСК
    sp = root / "Portfolio" / "stress" / "stress-2026-07-02-test.yaml"
    _utime(sp, "2026-07-09T10:00:01+03:00")
    check("at без пояса считается московским (раньше записи)", "до последней записи" in bcb.find_recalc(str(sp)).get("warning", ""))
    _utime(sp, "2026-07-09T09:59:59+03:00")
    check("at без пояса: позже записи — берётся", "path" in bcb.find_recalc(str(sp)))

# --------------------------------------------------------------------------- итог
print(f"\n{'='*60}")
print(f"Всего проверок: {checks}, провалено: {failed}")
sys.exit(1 if failed else 0)
