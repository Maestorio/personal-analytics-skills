#!/usr/bin/env python3
"""
stress_judgments.py — файл суждений стресса (stress-judgments@1): только то, что назначает
модель, без посчитанного. Числа по нему считает stress_recalc.py (--judgments) из снапшота и весов.

Состав файла (ключи верхнего уровня):
  schema                  'stress-judgments@1'
  date, slug              дата прогона скилла и слаг (слаг — из имени файла; в extract не знаем -> None)
  source_snapshot_id      снапшот, на котором писался текст
  source_run_id           run_id исходного стресса
  meta                    метаданные стаба, которые не считаются: schema_version, type, horizons,
                          horizon_ends, primary_horizon, horizon_mode, scenario_source, weight_type,
                          scenario_count, macro_input, review_date, modal_flag, basis_contract,
                          layers_included, per_position_basis, base_value_note, p_basis,
                          baseline_spot, factor_definitions, scenario_matrix_ref, forecast_type,
                          include_ev (есть ли раскрытие ожидаемого P&L) и прочие скалярные соседи
  scenarios               {X: {name, p, p_by_horizon, factors_by_horizon}} — веса на момент прогона
  horizon_coverage        {hNN: {status, ci_inflation, warnings, target_date}}
  priors                  {тикер: {factor_betas, factor_betas_method, factor_betas_r2,
                          sanctions_position}}; on_iis берётся из снапшота и не хранится.
                          Необязательно: asset_type (fund_equity | bond_fund | fund_gold ... — класс
                          актива для гардов шкалы; приоритетнее asset_type снапшота),
                          sector_group — ключ группы из references/sector-groups.yaml,
                          переопределяет сектор бумаги; extract его не выдумывает (берёт, только
                          если уже есть). Подпись сектора всегда из таблицы групп
  known_unmapped_tickers  тикеры, уже учтённые как unmapped (чтобы не звать их needs_judgment)
  carry                   {params, baseline_cbr_rate_pct, overrides?} — параметры купонного слоя;
                          overrides (необязательно) — {тикер: {bond_type, ytm_pct, ...}} из
                          weekly-bonds-review, уходит в compute_bond_carry как есть
  narrative               всё остальное поле суждения: robustness.{hedge_target, modal_scenario},
                          top_risks, macro_blindspots, caveats, sector_breakdown_pct, method,
                          concentration*, *_note, и числа fill, привязанные к снапшоту
                          (cash_rub_pct, blocked_pct, blocked_rub_memo, concentration_ratio —
                          пересчёт заменяет их посчитанными; не посчитанные помечаются
                          recalc.stale_numeric_fill_fields). Фактор концентрации —
                          narrative.concentration.dominant_factor

НЕ входит (считается): per_position.*.{by_horizon, weight_pct, on_iis}, unmapped_tickers,
bond_carry, portfolio_aggregates, robustness.{price, total_return},
scenarios.*.portfolio_level_by_horizon, base_value_rub, portfolio_snapshot_id, run_id, recalc.

CLI:
  stress_judgments.py extract  --stress ПОЛНЫЙ.yaml --output СУЖДЕНИЯ.yaml
  stress_judgments.py validate --file СУЖДЕНИЯ.yaml
Коды: 0 — ок; 1 — отказ/ошибки валидации; 2 — ошибка вызова.
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from input_contract import CANONICAL_FACTORS  # noqa: E402

SCHEMA = "stress-judgments@1"
PRIOR_KEYS = ("factor_betas", "factor_betas_method", "factor_betas_r2", "sanctions_position",
              "sector_group", "asset_type")
# Ключи верха полного файла, которых нет в суждениях ни в meta, ни в narrative.
NOT_JUDGMENT_TOP = {"date", "run_id", "portfolio_snapshot_id", "base_value_rub", "per_position",
                    "unmapped_tickers", "bond_carry", "portfolio_aggregates", "robustness",
                    "scenarios", "horizon_coverage", "recalc"}
META_KEYS = ("schema_version", "type", "horizons", "horizon_ends", "primary_horizon", "horizon_mode",
             "scenario_source", "weight_type", "scenario_count", "macro_input", "review_date",
             "modal_flag", "basis_contract", "layers_included", "per_position_basis",
             "base_value_note", "p_basis", "baseline_spot", "factor_definitions",
             "scenario_matrix_ref", "forecast_type")
REQUIRED_TOP = ("schema", "date", "source_snapshot_id", "meta", "scenarios", "horizon_coverage",
                "priors", "carry", "narrative")
REQUIRED_META = ("horizon_ends", "primary_horizon", "weight_type", "baseline_spot", "include_ev")
REQUIRED_NARRATIVE_ROB = ("hedge_target", "modal_scenario")
SCENARIO_KEYS = ("name", "p", "p_by_horizon", "factors_by_horizon")
# Посчитанные ключи верха narrative/robustness, которых в суждениях быть не должно.
FORBIDDEN_KEYS = {"per_position", "unmapped_tickers", "bond_carry", "portfolio_aggregates",
                  "base_value_rub", "portfolio_snapshot_id", "run_id", "recalc",
                  "portfolio_level_by_horizon"}
FORBIDDEN_ROBUSTNESS = {"price", "total_return"}
FORBIDDEN_PRIOR = {"by_horizon", "weight_pct", "on_iis"}


def _is_ph(v: Any) -> bool:
    return isinstance(v, str) and v.startswith("TODO_LLM")


def extract(stress: dict) -> dict:
    """Полный стресс-файл -> файл суждений (детерминированно)."""
    if not isinstance(stress, dict):
        raise ValueError("стресс-файл: ожидался словарь")
    pp = stress.get("per_position")
    if not isinstance(pp, dict) or not pp:
        raise ValueError("в стресс-файле нет per_position — нечего брать как суждения")
    meta = {k: copy.deepcopy(stress[k]) for k in META_KEYS if k in stress}
    pa = stress.get("portfolio_aggregates") or {}
    exp = ((pa.get("price") or {}).get("expected_pl_pct_by_horizon") or {})
    meta["include_ev"] = any(v is not None for v in exp.values())
    scenarios = {}
    for sid, sc in (stress.get("scenarios") or {}).items():
        scenarios[sid] = {k: copy.deepcopy(v) for k, v in sc.items() if k != "portfolio_level_by_horizon"}
    priors = {t: {k: copy.deepcopy(v[k]) for k in PRIOR_KEYS if k in v}
              for t, v in pp.items() if isinstance(v, dict)}
    bc = stress.get("bond_carry") or {}
    carry = {"params": copy.deepcopy(bc.get("params") or {})}
    if bc.get("baseline_cbr_rate_pct") is not None:
        carry["baseline_cbr_rate_pct"] = bc["baseline_cbr_rate_pct"]
    if bc.get("overrides"):
        carry["overrides"] = copy.deepcopy(bc["overrides"])
    narrative = {k: copy.deepcopy(v) for k, v in stress.items()
                 if k not in NOT_JUDGMENT_TOP and k not in META_KEYS}
    rob = stress.get("robustness") or {}
    nr = {k: copy.deepcopy(rob[k]) for k in REQUIRED_NARRATIVE_ROB if k in rob}
    if nr:
        narrative["robustness"] = nr
    return {
        "schema": SCHEMA,
        "date": stress.get("date"),
        "slug": None,
        "source_snapshot_id": stress.get("portfolio_snapshot_id"),
        "source_run_id": stress.get("run_id"),
        "meta": meta,
        "scenarios": scenarios,
        "horizon_coverage": copy.deepcopy(stress.get("horizon_coverage") or {}),
        "priors": priors,
        "known_unmapped_tickers": sorted({str(u["ticker"]) for u in stress.get("unmapped_tickers") or []
                                          if isinstance(u, dict) and u.get("ticker")}),
        "carry": carry,
        "narrative": narrative,
    }


def validate(j: Any) -> list[str]:
    errs: list[str] = []
    if not isinstance(j, dict):
        return ["файл суждений: ожидался словарь"]
    if j.get("schema") != SCHEMA:
        errs.append(f"schema: {j.get('schema')!r}, нужно {SCHEMA!r}")
    for k in REQUIRED_TOP:
        if k not in j:
            errs.append(f"нет обязательного ключа {k}")
    if errs and any(e.startswith("нет обязательного") for e in errs):
        return errs
    meta, sc, cov, pri = j["meta"], j["scenarios"], j["horizon_coverage"], j["priors"]
    if not isinstance(meta, dict):
        return errs + ["meta: ожидался словарь"]
    for k in REQUIRED_META:
        if k not in meta:
            errs.append(f"meta: нет {k}")
    if meta.get("weight_type") not in ("equal", "probability"):
        errs.append(f"meta.weight_type {meta.get('weight_type')!r} не equal|probability")
    he = meta.get("horizon_ends")
    if not isinstance(he, dict) or not he:
        errs.append("meta.horizon_ends: нужен непустой словарь")
        he = {}
    elif any(not (isinstance(k, str) and k[:1] == "h" and k[1:].isdigit()) for k in he):
        errs.append("meta.horizon_ends: ключи должны быть вида hNN")
    if not isinstance(sc, dict) or not sc:
        errs.append("scenarios: нужен непустой словарь")
        sc = {}
    for sid, s in sc.items():
        if not isinstance(s, dict):
            errs.append(f"scenarios.{sid}: ожидался словарь")
            continue
        for k in SCENARIO_KEYS:
            if k not in s:
                errs.append(f"scenarios.{sid}: нет {k}")
        for k in ("p_by_horizon", "factors_by_horizon"):
            v = s.get(k)
            if isinstance(v, dict) and he and set(v) != set(he):
                errs.append(f"scenarios.{sid}.{k}: горизонты {sorted(v)} не совпадают с "
                            f"horizon_ends {sorted(he)}")
    if isinstance(cov, dict) and he and set(cov) != set(he):
        errs.append(f"horizon_coverage: горизонты {sorted(cov)} не совпадают с horizon_ends {sorted(he)}")
    if not isinstance(pri, dict) or not pri:
        errs.append("priors: нужен непустой словарь")
        pri = {}
    for t, p in pri.items():
        if not isinstance(p, dict) or not isinstance(p.get("factor_betas"), dict):
            errs.append(f"priors.{t}: нет factor_betas")
            continue
        if "sector_group" in p and not (isinstance(p["sector_group"], str) and p["sector_group"].strip()):
            errs.append(f"priors.{t}.sector_group: нужна непустая строка")
        miss = [f for f in CANONICAL_FACTORS if f not in p["factor_betas"]]
        if miss:
            errs.append(f"priors.{t}.factor_betas: нет факторов {miss}")
    car = j["carry"]
    if not isinstance(car, dict) or not isinstance(car.get("params"), dict):
        errs.append("carry: нужен словарь с params")
    elif car.get("overrides") is not None and not isinstance(car["overrides"], dict):
        errs.append("carry.overrides: ожидался словарь {тикер: {...}}")
    rob = (j["narrative"] or {}).get("robustness") if isinstance(j["narrative"], dict) else None
    if not isinstance(rob, dict) or any(k not in rob for k in REQUIRED_NARRATIVE_ROB):
        errs.append("narrative.robustness: нужны hedge_target и modal_scenario")
    nar = j["narrative"]
    if isinstance(nar, dict):
        for k in sorted(FORBIDDEN_KEYS & set(nar)):
            errs.append(f"narrative.{k}: посчитанный блок в файле суждений")
        if isinstance(rob, dict):
            for k in sorted(FORBIDDEN_ROBUSTNESS & set(rob)):
                errs.append(f"narrative.robustness.{k}: посчитанный блок в файле суждений")
    for t, p in pri.items():
        if isinstance(p, dict):
            for k in sorted(FORBIDDEN_PRIOR & set(p)):
                errs.append(f"priors.{t}.{k}: посчитанное поле в файле суждений")
    for sid, s in sc.items():
        if isinstance(s, dict) and "portfolio_level_by_horizon" in s:
            errs.append(f"scenarios.{sid}.portfolio_level_by_horizon: посчитанный блок в файле суждений")
    for k in sorted(FORBIDDEN_KEYS & set(meta)):
        errs.append(f"meta.{k}: посчитанный блок в файле суждений")
    return errs


def load(path: Path) -> dict:
    import yaml
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"файл не найден: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def dump(j: dict) -> str:
    import yaml
    return yaml.safe_dump(j, allow_unicode=True, sort_keys=False, default_flow_style=False)


def main() -> int:
    ap = argparse.ArgumentParser(description="Файл суждений стресса (stress-judgments@1)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--stress", required=True, type=Path)
    e.add_argument("--output", required=True, type=Path)
    v = sub.add_parser("validate")
    v.add_argument("--file", required=True, type=Path)
    try:
        args = ap.parse_args()
    except SystemExit as ex:
        return 2 if ex.code else 0
    try:
        if args.cmd == "extract":
            if args.output.resolve() == args.stress.resolve():
                sys.stderr.write("ОТКАЗ: --output совпадает с --stress\n")
                return 1
            j = extract(load(args.stress))
            j["slug"] = _slug_from_name(args.stress.name)
            errs = validate(j)
            if errs:
                sys.stderr.write("ОТКАЗ: суждения невалидны:\n" + "\n".join(f"  {x}" for x in errs) + "\n")
                return 1
            from assemble_stress import atomic_write
            atomic_write(args.output, dump(j))
            sys.stdout.write(f"OK: {args.output}\n")
            return 0
        errs = validate(load(args.file))
        if errs:
            sys.stderr.write("\n".join(errs) + "\n")
            return 1
        sys.stdout.write("OK\n")
        return 0
    except (ValueError, FileNotFoundError) as ex:
        sys.stderr.write(f"ОТКАЗ: {ex}\n")
        return 1


def _slug_from_name(name: str) -> str | None:
    stem = name.rsplit(".", 1)[0]
    parts = stem.split("-")
    if len(parts) > 4 and parts[0] == "stress" and parts[1:4] and all(p.isdigit() for p in parts[1:4]):
        return "-".join(parts[4:])
    return None


if __name__ == "__main__":
    sys.exit(main())
