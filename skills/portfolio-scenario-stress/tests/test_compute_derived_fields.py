#!/usr/bin/env python3
"""Тесты для skills/portfolio-scenario-stress/scripts/compute_derived_fields.py и его подключения
в assemble_stress.py (--derived).

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 \
        skills/portfolio-scenario-stress/tests/test_compute_derived_fields.py
Зависимости: stdlib + pyyaml.

Синтетика: снапшот с акциями (sector — ключи references/sector-groups.yaml), облигациями
(nominal_currency), фондом денежного рынка из таблицы фондов, фондом вне таблицы, бумагой на двух счетах, заблокированными позициями и кэшем.
Живые файлы (stress-2026-11-04 / 10-04) сверяются отдельным прогоном, не в тесте: библиотека
Claude-Memory недоступна из тестов.
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
SCRIPTS = HERE.parent / "scripts"
CDF = SCRIPTS / "compute_derived_fields.py"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

import compute_derived_fields as cdf  # noqa: E402
import compute_portfolio_aggregates as cpa  # noqa: E402
import input_contract as ic  # noqa: E402
import stress_judgments as sj  # noqa: E402


def check(label: str, cond: bool, detail: str = "") -> bool:
    if cond:
        print(f"  ✓ {label}")
        return True
    print(f"  ✗ {label}{(' — ' + detail) if detail else ''}")
    return False


def H(ticker, value, at="stock", sector=None, nominal=None, account="main", blocked=False, sector_ru=None):
    return {"ticker": ticker, "asset_type": at, "value_rub": value, "sector": sector,
            "sector_ru": sector_ru, "nominal_currency": nominal, "account": account,
            "is_blocked": blocked}


def snapshot(holdings=None, cash=100.0):
    return {"schema_version": "2.0", "as_of_date": "2026-11-03",
            "holdings": holdings if holdings is not None else [
                H("BNK", 500.0, sector="banks_finance", sector_ru="Банки"),
                H("OIL", 200.0, sector="oil_gas", sector_ru="Нефтегаз"),
                H("OFZ", 150.0, at="bond", nominal="SUR"),
                H("FXB", 100.0, at="bond", nominal="CNY"),
                H("TMON", 50.0, at="fund"),
            ],
            "cash": {"total_rub": cash}}


def pos(value_total, d_a, d_b, betas=None):
    return {"weight_pct": None, "factor_betas": betas or {},
            "by_horizon": {"h6": {"delta_pct_by_scenario": {"A": {"value": d_a}, "B": d_b}},
                           "h12": {"delta_pct_by_scenario": {"A": {"value": d_a * 2}, "B": d_b * 2}}}}


def build_pp(snap):
    """per_position по снапшоту: вес = value / Σ unblocked (как compute_per_position)."""
    vals: dict[str, float] = {}
    for h in snap["holdings"]:
        if not h.get("is_blocked"):
            vals[h["ticker"]] = vals.get(h["ticker"], 0) + h["value_rub"]
    tot = sum(vals.values())
    out = {}
    for i, (t, v) in enumerate(sorted(vals.items())):
        p = pos(v, -10.0 - i, 5.0 + i, {"usdrub": [0.5, -0.3, 0.0, 0.2, 0.0][i % 5], "cnyrub": 0.0})
        p["weight_pct"] = round(v / tot * 100, 4)
        out[t] = p
    return out


def full(snap=None, extra=None):
    snap = snap or snapshot()
    pp = build_pp(snap)
    scen = {"A": {"p": 0.5}, "B": {"p": 0.5}}
    agg = cpa.compute(snap, scen, pp, None, "equal", False)
    return snap, pp, agg, cdf.compute_with_report(snap, pp, None, agg, scen, extra)


def test_cash_and_blocked() -> bool:
    print("\n[test_cash_and_blocked]")
    snap = snapshot(cash=100.0)
    snap["holdings"] += [H("FRZ1", 0.0, blocked=True), H("FRZ2", 0.0, blocked=True)]
    _, _, _, (out, sk) = full(snap)
    ok = check("cash = 100 / 1100 портфеля с кэшем = 9.09", out["cash_rub_pct"] == 9.09, str(out.get("cash_rub_pct")))
    ok &= check("blocked_pct 0.0", out["blocked_pct"] == 0.0)
    ok &= check("memo про 2 позиции", out["blocked_rub_memo"].startswith("2 заблокированные позиции оценены в 0 ₽"),
                out.get("blocked_rub_memo", ""))
    snap = snapshot(cash=100.0)
    snap["holdings"].append(H("FRZ1", 0.0, blocked=True))
    out = full(snap)[3][0]
    ok &= check("1 -> 'заблокированная позиция оценена'", out["blocked_rub_memo"].startswith("1 заблокированная позиция оценена"))
    snap["holdings"] += [H(f"F{i}", 0.0, blocked=True) for i in range(10)]  # итого 11
    ok &= check("11 -> 'заблокированных позиций оценены'",
                full(snap)[3][0]["blocked_rub_memo"].startswith("11 заблокированных позиций оценены"))
    # нет кэша, нет заблокированных
    snap = snapshot(cash=0.0)
    out, sk = full(snap)[3]
    ok &= check("нет кэша -> 0.0", out["cash_rub_pct"] == 0.0)
    ok &= check("нет заблокированных -> blocked_pct 0.0, memo пропущен",
                out["blocked_pct"] == 0.0 and "blocked_rub_memo" not in out and "blocked_rub_memo" in sk)
    # заблокированные с ненулевой оценкой: процент считается, формулировки нет
    snap = snapshot()
    snap["holdings"].append(H("FRZ", 50.0, blocked=True))
    out, sk = full(snap)[3]
    ok &= check("blocked_pct по сумме 50/1100 портфеля с кэшем = 4.55, memo пропущен",
                out["blocked_pct"] == 4.55 and "blocked_rub_memo" not in out)
    return ok


def test_weight_base_note() -> bool:
    print("\n[test_weight_base_note]")
    out = full(snapshot(cash=100.0))[3][0]
    note = out["weight_base_note"]
    ok = check("числа: 1 000 ₽ holdings, 100 ₽ кэш (9.09% от портфеля с кэшем), база 1 100 ₽",
               "1 000 ₽ (без кэша)" in note and "кэш 100 ₽ (9.09% от портфеля с кэшем)" in note
               and "base_value_rub = 1 100 ₽" in note, note)
    ok &= check("Σ секторов в строке", "Σ секторов = 100.0%" in note, note)
    return ok


def test_sector_breakdown_and_map() -> bool:
    print("\n[test_sector_breakdown_and_map]")
    snap, pp, agg, (out, sk) = full()
    sb = out["sector_breakdown_pct"]
    ok = check("ключи: акции по sector, облигации по валюте номинала, MM",
               set(sb) == {"banks_finance", "oil_gas", "bonds_rub", "bonds_fx", "money_market"}, str(set(sb)))
    ok &= check("SUR -> bonds_rub, CNY -> bonds_fx", sb["bonds_rub"]["value_rub"] == 150 and sb["bonds_fx"]["value_rub"] == 100)
    ok &= check("weight_pct = value / holdings", sb["banks_finance"]["weight_pct"] == 50.0 and sb["money_market"]["weight_pct"] == 5.0)
    ok &= check("Σ weight_pct = 100", abs(sum(v["weight_pct"] for v in sb.values()) - 100.0) < 0.01)
    ok &= check("label_ru — всегда из таблицы групп, не из sector_ru снапшота",
                sb["banks_finance"]["label_ru"] == "Банки и финансы" and sb["bonds_rub"]["label_ru"] == "Облигации в рублях"
                and sb["money_market"]["label_ru"] == "Денежный рынок")
    # ΔRUB сектора = value * delta / 100
    d = pp["BNK"]["by_horizon"]["h6"]["delta_pct_by_scenario"]["A"]["value"]
    ok &= check("ΔRUB h6/A банков = 500 * delta/100", sb["banks_finance"]["price_delta_rub_by_horizon"]["h6"]["A"] == round(500 * d / 100))
    ok &= check("sector_breakdown_basis = price", out["sector_breakdown_basis"] == "price")
    # Σ ΔRUB по секторам ~ portfolio_level (допуск округления)
    tot = sum(v["price_delta_rub_by_horizon"]["h12"]["B"] for v in sb.values())
    pl = agg["scenarios"]["B"]["portfolio_level_by_horizon"]["h12"]["price_delta_rub"]
    ok &= check("Σ секторов совпадает с portfolio_level (±5 ₽)", abs(tot - pl) <= 5, f"{tot} vs {pl}")
    return ok


def test_fund_outside_table_blocks_breakdown() -> bool:
    print("\n[test_fund_outside_table_blocks_breakdown]")
    snap = snapshot()
    snap["holdings"].append(H("GLD", 100.0, at="fund"))
    _, pp, agg, (out, sk) = full(snap)
    ok = check("блок секторов, top_* не считаются", all(k not in out for k in ("sector_breakdown_pct", "top_risks", "top_resilient")))
    ok &= check("причина называет тикер и таблицу фондов", "GLD" in sk["sector_breakdown_pct"] and "funds" in sk["sector_breakdown_pct"])
    ok &= check("cash и weight_base_note остаются, без Σ секторов",
                "cash_rub_pct" in out and "Σ секторов" not in out["weight_base_note"])
    out = cdf.compute(snap, pp, None, agg, None, {"priors": {"GLD": {"sector_group": "funds_gold"}}})
    ok &= check("sector_group суждения у фонда вне таблицы — считается, подпись из таблицы",
                out["sector_breakdown_pct"]["funds_gold"]["label_ru"] == "Золото (фонд)"
                and out["sector_breakdown_pct"]["funds_gold"]["value_rub"] == 100)
    out = cdf.compute(snap, pp, None, agg, None, {"priors": {"GLD": {"sector_group": "funds_gold"},
                                                            "TMON": {"sector_group": "bond_funds"},
                                                            "OIL": {"sector_group": "metals_mining"}}})
    sb = out["sector_breakdown_pct"]
    ok &= check("sector_group переопределяет таблицу фондов и sector акции",
                "money_market" not in sb and sb["bond_funds"]["value_rub"] == 50 and "oil_gas" not in sb
                and sb["metals_mining"]["value_rub"] == 200)
    sk2 = cdf.compute_with_report(snap, pp, None, agg, None, {"priors": {"GLD": {"sector_group": "cash_like"}}})[1]
    ok &= check("sector_group вне groups -> пропуск с тикером и ключом",
                "GLD=cash_like" in sk2["sector_breakdown_pct"] and "groups" in sk2["sector_breakdown_pct"])
    s3 = snapshot([H("S", 100.0, sector="banks", sector_ru="Банки")])
    _, _, _, (o3, sk3) = full(s3)
    ok &= check("sector акции снапшота вне groups -> пропуск", "S=banks" in sk3["sector_breakdown_pct"] and "sector_breakdown_pct" not in o3)
    s2 = snapshot([H("X", 100.0), H("B", 100.0, at="bond")])
    _, pp2, agg2, (o2, sk2) = full(s2)
    ok &= check("акция без sector и облигация без nominal_currency -> пропуск",
                "X" in sk2["sector_breakdown_pct"] and "B" in sk2["sector_breakdown_pct"])
    return ok


def test_sector_table() -> bool:
    print("\n[test_sector_table]")
    t = cdf.load_sector_groups()
    g, f = t["groups"], t["funds"]
    ok = check("группы бумаг и фондов на месте", {"funds_gold", "bond_funds", "funds_real_estate", "funds_equity", "money_market",
                                                  "bonds_rub", "bonds_fx", "real_estate", "gold_miners", "algo_strategies"} <= set(g))
    ok &= check("фонды: утверждённая раскладка", f == {"TGLD": "funds_gold", "TLCB": "bond_funds", "SBGB": "bond_funds",
                                                      "XXXXXX": "funds_real_estate", "FINAMAR": "algo_strategies",
                                                      "TMON": "money_market", "TPAY": "money_market"}, str(f))
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)

        def bad(name, text):
            (d / name).write_text(text, encoding="utf-8")
            try:
                cdf.load_sector_groups(d / name)
            except cdf.SectorTableError as e:
                return str(e)
            return None
        e1 = bad("a.yaml", "groups: [unclosed\nfunds: {")
        ok &= check("битый YAML -> SectorTableError", e1 is not None and "YAML" in e1, str(e1))
        e2 = bad("b.yaml", "groups: {a: Метка}\nfunds: {T1: b}\n")
        ok &= check("группа фонда вне groups -> ошибка с тикером", e2 is not None and "T1" in e2 and "groups" in e2, str(e2))
        ok &= check("пустой groups -> ошибка", bad("c.yaml", "groups: {}\nfunds: {}\n") is not None)
        ok &= check("не словарь -> ошибка", bad("d.yaml", "- не словарь\n") is not None)
        try:
            cdf.load_sector_groups(d / "нет.yaml")
            ok &= check("нет файла -> ошибка", False)
        except cdf.SectorTableError:
            ok &= check("нет файла -> ошибка", True)
        (d / "ok.yaml").write_text("groups: {banks_finance: Мои банки, oil_gas: Н, bonds_rub: О, bonds_fx: В, money_market: Д}\n"
                                   "funds: {TMON: money_market}\n", encoding="utf-8")
        snap, pp, agg, _ = full()
        out = cdf.compute(snap, pp, None, agg, None, None, cdf.load_sector_groups(d / "ok.yaml"))
        ok &= check("подпись из переданной таблицы", out["sector_breakdown_pct"]["banks_finance"]["label_ru"] == "Мои банки")
    return ok


def test_single_position_and_two_accounts() -> bool:
    print("\n[test_single_position_and_two_accounts]")
    snap = snapshot([H("ONE", 400.0, sector="banks_finance", sector_ru="Банки")], cash=0.0)
    _, pp, agg, (out, sk) = full(snap)
    sb = out["sector_breakdown_pct"]
    ok = check("одна бумага: сектор 100%", list(sb) == ["banks_finance"] and sb["banks_finance"]["weight_pct"] == 100.0)
    ok &= check("top_risks: одна запись на горизонт при убытке", [r["ticker"] for r in out["top_risks"] if r["horizon"] == "h6"] == ["ONE"])
    # бумага на двух счетах: ноги складываются
    snap = snapshot([H("TWO", 300.0, sector="banks_finance", sector_ru="Банки"),
                     H("TWO", 100.0, sector="banks_finance", sector_ru="Банки", account="iis_3"),
                     H("OIL", 100.0, sector="oil_gas")], cash=0.0)
    _, pp, agg, (out, sk) = full(snap)
    sb = out["sector_breakdown_pct"]
    ok &= check("две ноги = одна запись, value 400", sb["banks_finance"]["value_rub"] == 400 and sb["banks_finance"]["weight_pct"] == 80.0)
    ok &= check("ΔRUB от суммарной стоимости ноги", sb["banks_finance"]["price_delta_rub_by_horizon"]["h6"]["A"] == round(400 * pp["TWO"]["by_horizon"]["h6"]["delta_pct_by_scenario"]["A"]["value"] / 100))
    ok &= check("в top_risks тикер один раз на горизонт", sum(1 for r in out["top_risks"] if r["horizon"] == "h6" and r["ticker"] == "TWO") == 1)
    return ok


def test_top_lists() -> bool:
    print("\n[test_top_lists]")
    snap = snapshot([H(f"S{i}", 100.0 * (i + 1), sector="banks_finance", sector_ru="Банки") for i in range(7)], cash=0.0)
    pp = build_pp(snap)
    scen = {"A": {"p": 0.5}, "B": {"p": 0.5}}
    agg = cpa.compute(snap, scen, pp, None, "equal", False)
    out = cdf.compute(snap, pp, None, agg, scen)
    r6 = [r for r in out["top_risks"] if r["horizon"] == "h6"]
    ok = check("по 5 на горизонт, сценарий — худший по портфелю", len(r6) == 5 and {r["scenario"] for r in r6} == {"A"})
    ok &= check("сортировка по ΔRUB: от большего убытка", [r["price_delta_rub"] for r in r6] == sorted(r["price_delta_rub"] for r in r6))
    ok &= check("все убыточные", all(r["price_delta_rub"] < 0 for r in r6))
    t6 = [r for r in out["top_resilient"] if r["horizon"] == "h6"]
    ok &= check("устойчивые: лучший сценарий B, ΔRUB по убыванию, >0",
                {r["scenario"] for r in t6} == {"B"} and [r["price_delta_rub"] for r in t6] == sorted((r["price_delta_rub"] for r in t6), reverse=True)
                and all(r["price_delta_rub"] > 0 for r in t6))
    ok &= check("форма записи", set(r6[0]) == {"horizon", "scenario", "ticker", "sector", "weight_pct", "delta_pct", "price_delta_rub"})
    # меньше пяти убыточных — берём сколько есть
    snap = snapshot([H("S0", 100.0, sector="banks_finance"), H("S1", 100.0, sector="banks_finance")], cash=0.0)
    pp = build_pp(snap)
    pp["S1"] = pos(100.0, 3.0, 4.0)
    pp["S1"]["weight_pct"] = 50.0
    agg = cpa.compute(snap, scen, pp, None, "equal", False)
    out = cdf.compute(snap, pp, None, agg, scen)
    ok &= check("убыточных меньше пяти: только они", [r["ticker"] for r in out["top_risks"] if r["horizon"] == "h6"] == ["S0"])
    return ok


def test_concentration() -> bool:
    print("\n[test_concentration]")
    snap = snapshot([H("P", 300.0, sector="banks_finance"), H("N", 100.0, sector="banks_finance"),
                     H("Z", 100.0, sector="banks_finance"), H("CNY", 100.0, sector="banks_finance")], cash=100.0)
    pp = build_pp(snap)
    for t, b in (("P", 1.0), ("N", -1.0), ("Z", 0.0), ("CNY", 0.0)):
        pp[t]["factor_betas"] = {"usdrub": b, "cnyrub": 1.0 if t == "CNY" else 0.0}
    scen = {"A": {"p": 0.5}, "B": {"p": 0.5}}
    agg = cpa.compute(snap, scen, pp, None, "equal", False)
    out, sk = cdf.compute_with_report(snap, pp, None, agg, scen)
    ok = check("нет фактора — не считается", "concentration_ratio" not in out and "concentration" not in out
               and "dominant_factor" in sk["concentration_ratio"])
    out, sk = cdf.compute_with_report(snap, pp, None, agg, scen, {"concentration_factor": "не_фактор"})
    ok &= check("фактор не из канонических — не считается", "concentration_ratio" not in out and "не_фактор" in sk["concentration"])
    out = cdf.compute(snap, pp, None, agg, scen, {"concentration_factor": "usdrub"})
    c = out["concentration"]
    ok &= check("знаменатель — портфель с кэшем (700)", ic.compute_base_value_rub(snap) == 700.0)
    ok &= check("same 300/700 = 42.86, opposite 14.29", c["same_direction_pct"] == 42.86 and c["opposite_pct"] == 14.29, str(c))
    ok &= check("neutral = 100 - same - opposite (включает кэш, 300/700 и 100/700)", c["neutral_pct"] == 42.86, str(c))
    ok &= check("incl_cnyrub: + позиция с beta>0 только к юаню -> 400/700 = 57.14", c["same_direction_incl_cnyrub_pct"] == 57.14)
    ok &= check("concentration_ratio = same / 100", out["concentration_ratio"] == 0.4286)
    ok &= check("подключи — только числа (dominant_factor и note остаются суждением)",
                set(c) == {"same_direction_pct", "opposite_pct", "neutral_pct", "same_direction_incl_cnyrub_pct"})
    return ok


def test_cli_yaml_fragment() -> bool:
    print("\n[test_cli_yaml_fragment]")
    snap, pp, agg, _ = full()
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "snap.json").write_text(json.dumps(snap))
        (d / "pp.yaml").write_text(yaml.safe_dump({"per_position": pp}, allow_unicode=True))
        (d / "agg.yaml").write_text(yaml.safe_dump(agg, allow_unicode=True))
        r = subprocess.run([sys.executable, str(CDF), "--snapshot", str(d / "snap.json"), "--per-position", str(d / "pp.yaml"),
                            "--aggregates", str(d / "agg.yaml")], capture_output=True, text=True)
        ok = check("exit 0", r.returncode == 0, r.stderr[:300])
        frag = yaml.safe_load(r.stdout)
        ok &= check("фрагмент несёт посчитанные ключи", {"cash_rub_pct", "blocked_pct", "sector_breakdown_pct", "top_risks", "weight_base_note"} <= set(frag))
        ok &= check("пропущенное названо на stderr", "concentration_ratio" in r.stderr)
        r2 = subprocess.run([sys.executable, str(CDF), "--snapshot", str(d / "nope.json"), "--per-position", str(d / "pp.yaml"),
                             "--aggregates", str(d / "agg.yaml")], capture_output=True, text=True)
        ok &= check("нечитаемый вход -> код 2", r2.returncode == 2)
        return ok


def test_judgments_sector_group() -> bool:
    print("\n[test_judgments_sector_group]")
    stress = {"date": "2026-11-04", "portfolio_snapshot_id": "portfolio-2026-11-03.json",
              "per_position": {"A": {"factor_betas": {}, "sanctions_position": 0.1, "sector_group": "funds_gold"},
                               "B": {"factor_betas": {}}}}
    j = sj.extract(stress)
    ok = check("extract берёт sector_group, если есть", j["priors"]["A"]["sector_group"] == "funds_gold")
    ok &= check("extract не выдумывает метку", "sector_group" not in j["priors"]["B"])
    j2 = {"schema": sj.SCHEMA, "date": "d", "source_snapshot_id": "s",
          "meta": {"horizon_ends": {"h6": "2027-01-01"}, "primary_horizon": 6, "weight_type": "equal",
                   "baseline_spot": {}, "include_ev": False},
          "scenarios": {"A": {"name": "a", "p": 1, "p_by_horizon": {"h6": 1}, "factors_by_horizon": {"h6": {}}}},
          "horizon_coverage": {"h6": {}},
          "priors": {"A": {"factor_betas": {f: 0 for f in sj.CANONICAL_FACTORS}}},
          "carry": {"params": {}}, "narrative": {"robustness": {"hedge_target": "A", "modal_scenario": "none"}}}
    ok &= check("validate допускает отсутствие метки", sj.validate(j2) == [])
    j3 = copy.deepcopy(j2)
    j3["priors"]["A"]["sector_group"] = "funds_gold"
    ok &= check("validate принимает строку", sj.validate(j3) == [])
    j3["priors"]["A"]["sector_group"] = ""
    ok &= check("validate отвергает пустую/нестроковую метку", any("sector_group" in e for e in sj.validate(j3)))
    return ok


# ───────────────────── подключение: assemble_stress --derived ─────────────────────

def _env():
    import test_assemble_stress as tas
    return tas


def test_assemble_with_derived() -> bool:
    print("\n[test_assemble_with_derived]")
    tas = _env()
    derived = {"cash_rub_pct": 0.0, "blocked_pct": 0.0,
               "sector_breakdown_pct": {"banks_finance": {"label_ru": "Банки и финансы", "value_rub": 600, "weight_pct": 60.0,
                                                  "price_delta_rub_by_horizon": {}}},
               "sector_breakdown_basis": "price",
               "top_risks": [{"horizon": "h6", "scenario": "A", "ticker": "TICK1", "sector": "banks_finance",
                              "weight_pct": 60.0, "delta_pct": -10.0, "price_delta_rub": -60}],
               "concentration_ratio": 0.6,
               "concentration": {"same_direction_pct": 60.0, "opposite_pct": 0.0, "neutral_pct": 40.0,
                                 "same_direction_incl_cnyrub_pct": 60.0}}
    ok = True
    with tempfile.TemporaryDirectory() as td:
        e = tas.Env(td)
        e.dump("derived.yaml", derived)
        # fill из набора модели задаёт те же ключи -> отказ
        r = e.run(extra=["--derived", str(e.d / "derived.yaml")])
        ok &= check("fill с расчётными ключами при --derived -> отказ 1", r.returncode == 1
                    and "приходит из --derived" in r.stderr, r.stderr[:300])
        ok &= check("отказ называет ключи", all(k in r.stderr for k in ("sector_breakdown_pct", "concentration_ratio", "top_risks")))
        ok &= check("файл не записан", not (e.d / "out.yaml").exists())
        # fill только с суждениями
        fill = {"dominant_factor": "brent", "macro_blindspots": [],
                "caveats": [{"severity": "HIGH", "message": "x"}], "robustness": {"hedge_target": "A"},
                "concentration": {"dominant_factor": "usdrub", "note": "текст модели"}}
        e.dump("fill2.yaml", fill)
        r = e.run(extra=["--derived", str(e.d / "derived.yaml")], overrides={"--fill": "fill2.yaml"})
        ok &= check("fill без расчётных ключей — собралось", r.returncode == 0, r.stderr[:400])
        t = e.out()
        ok &= check("ключи из --derived как есть", t["sector_breakdown_pct"] == derived["sector_breakdown_pct"]
                    and t["top_risks"] == derived["top_risks"] and t["concentration_ratio"] == 0.6
                    and t["cash_rub_pct"] == 0.0)
        ok &= check("concentration: посчитанные подключи + подключи fill",
                    t["concentration"] == {**derived["concentration"], "dominant_factor": "usdrub", "note": "текст модели"})
        s = json.loads(r.stdout)["sources"]
        ok &= check("источники в сводке", s["sector_breakdown_pct"] == "derived" and s["concentration"] == "derived+fill"
                    and s["dominant_factor"] == "fill+stub")
        # пересечение подключей concentration -> отказ
        fill3 = copy.deepcopy(fill)
        fill3["concentration"]["same_direction_pct"] = 1.0
        e.dump("fill3.yaml", fill3)
        r = e.run(extra=["--derived", str(e.d / "derived.yaml")], overrides={"--fill": "fill3.yaml"})
        ok &= check("fill трогает посчитанное подключо concentration -> отказ", r.returncode == 1
                    and "concentration.same_direction_pct" in r.stderr, r.stderr[:300])
        # _drop расчётного ключа нельзя
        fill4 = copy.deepcopy(fill)
        fill4["_drop"] = ["top_risks"]
        e.dump("fill4.yaml", fill4)
        r = e.run(extra=["--derived", str(e.d / "derived.yaml")], overrides={"--fill": "fill4.yaml"})
        ok &= check("_drop посчитанного ключа -> отказ", r.returncode == 1, r.stderr[:200])
    return ok


def test_assemble_without_derived_unchanged() -> bool:
    print("\n[test_assemble_without_derived_unchanged]")
    tas = _env()
    with tempfile.TemporaryDirectory() as td:
        e = tas.Env(td)
        r = e.run()
        ok = check("без --derived — прежнее поведение: ключи из fill", r.returncode == 0, r.stderr[:300])
        t = e.out()
        ok &= check("sector_breakdown_pct/top_risks/concentration_ratio из fill",
                    t["sector_breakdown_pct"] == tas.FILL["sector_breakdown_pct"] and t["top_risks"] == tas.FILL["top_risks"]
                    and t["concentration_ratio"] == 0.6)
        ok &= check("источник — fill", json.loads(r.stdout)["sources"]["sector_breakdown_pct"] == "fill")
    return ok


TESTS = [
    test_cash_and_blocked,
    test_weight_base_note,
    test_sector_breakdown_and_map,
    test_fund_outside_table_blocks_breakdown,
    test_sector_table,
    test_single_position_and_two_accounts,
    test_top_lists,
    test_concentration,
    test_cli_yaml_fragment,
    test_judgments_sector_group,
    test_assemble_with_derived,
    test_assemble_without_derived_unchanged,
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
