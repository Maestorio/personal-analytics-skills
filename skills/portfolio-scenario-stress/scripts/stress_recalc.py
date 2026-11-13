#!/usr/bin/env python3
"""
stress_recalc.py — пересчёт ЧИСЕЛ стресс-файла без модели.

Суждения (беты и позиция на санкционной шкале по бумагам, факторы сценариев, тексты)
берутся из готового стресс-файла скилла как есть; числа считают те же функции, что
в штатном прогоне (compute_per_position → compute_bond_carry →
compute_portfolio_aggregates), итог собирает assemble_stress.assemble. Новых формул нет.

CLI:
  python3 stress_recalc.py (--stress STRESS.yaml | --judgments СУЖДЕНИЯ.yaml)
      --snapshot portfolio-DATE.json
      [--weights-json ВЕСА.json] [--macro-scenarios МАКРО.yaml] --output OUT.yaml
      [--today YYYY-MM-DD] [--at ISO] [--json]

Источник суждений — ровно один из двух: полный стресс-файл (--stress; его суждения
выделяет stress_judgments.extract) или файл суждений stress-judgments@1 (--judgments).
Дальше путь общий. Что достаётся из источника:
  priors по бумагам  <- per_position[t].{factor_betas, factor_betas_method,
                        factor_betas_r2, sanctions_position}
  сценарии           <- scenarios[X].{name, p, p_by_horizon, factors_by_horizon}
  horizon_ends, baseline_spot, horizon_coverage (CI-инфляция), weight_type
  купонный слой      <- bond_carry.params и bond_carry.baseline_cbr_rate_pct
  include_ev         <- есть ли ненулевое expected_pl в portfolio_aggregates
  поля суждения (caveats, dominant_factor, notes, ...) — переносятся как есть.
Расчётные поля (cash_rub_pct, blocked_pct, sector_breakdown_pct, top_risks, top_resilient,
concentration_ratio и подключи concentration, weight_base_note, blocked_rub_memo) считает
compute_derived_fields из снапшота; фактор концентрации — concentration.dominant_factor
источника. Что посчитать не удалось, остаётся значением источника и попадает в
recalc.stale_numeric_fill_fields с причиной в recalc.notes. Блок portfolio_summary в выход
не переносится.
overrides купонного слоя (bond_type=floater и т.п. из weekly-bonds-review): необязательный
carry.overrides суждений уходит в compute_bond_carry и сохраняется в bond_carry.overrides
(только когда непуст); extract поднимает его обратно.

--weights-json: файл stress-weights@1 (читаются schema, horizon_ends, weights). Его
horizon_ends обязаны совпасть с horizon_ends стресса (метки и даты), сценарии —
с его сценариями, сумма на горизонте = 1 (допуск 1e-6), иначе отказ. p_by_horizon =
веса файла, p = вес на primary_horizon.

--macro-scenarios: новая макро-таблица. Числовые факторы сценариев (brent, usdrub, cnyrub, cbr_rate,
xauusd), baseline_spot, horizon_coverage и уровень КС купонного слоя пересчитываются по сетке дат макро-файла
на сроки источника (as_of — --today) тем же кодом, что в stress_build; sanctions и geopol остаются из источника.
Отказ (код 1, одним списком): макро-файл не проходит validate_macro или собран на другой матрице, чем стресс.
В recalc: macro_input, macro_input_was, narrative_stale: true, reason «macro» (если нет иной причины).

Бумаги без чувствительностей: блокеры покрытия валидатора (3.13) не гасятся, а
записываются в recalc.validator_open — файл неполон, пока модель не назначит беты.

Коды: 0 — посчитано; 1 — отказ (нет входа, блокер валидатора); 2 — ошибка вызова.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import assemble_stress as asm  # noqa: E402
import compute_bond_carry as cbc  # noqa: E402
import compute_derived_fields as cdf  # noqa: E402
import compute_horizon_factors as chf  # noqa: E402
import compute_per_position as cpp  # noqa: E402
import compute_portfolio_aggregates as cpa  # noqa: E402
import stress_judgments as sj  # noqa: E402
from input_contract import compute_base_value_rub  # noqa: E402

MSK = timezone(timedelta(hours=3))
# Подключи concentration, которые считает compute_derived_fields (dominant_factor и note — суждение).
CONC_DERIVED_KEYS = ("same_direction_pct", "opposite_pct", "neutral_pct", "same_direction_incl_cnyrub_pct")


class RecalcError(Exception):
    pass


def _load_yaml(path: Path, label: str) -> Any:
    import yaml
    if not path.exists():
        raise RecalcError(f"{label} не найден: {path}")
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
    except Exception as e:  # noqa: BLE001
        raise RecalcError(f"{label} нечитаем: {e}")


def _dump_yaml(tree: Any) -> str:
    import yaml
    return yaml.dump(tree, Dumper=getattr(yaml, "CSafeDumper", yaml.SafeDumper),
                     allow_unicode=True, sort_keys=False, default_flow_style=False)


# Ключи верхнего уровня итога в порядке полного файла скилла (для читаемого вывода).
TOP_ORDER = ["schema_version", "type", "date", "horizons", "horizon_ends", "primary_horizon",
             "horizon_mode", "portfolio_snapshot_id", "scenario_source", "weight_type",
             "scenario_count", "run_id", "macro_input", "review_date", "modal_flag",
             "basis_contract", "layers_included", "per_position_basis", "base_value_rub",
             "base_value_note", "p_basis", "baseline_spot", "scenarios", "factor_definitions",
             "per_position", "unmapped_tickers", "sector_breakdown_pct",
             "portfolio_aggregates", "robustness", "concentration_ratio", "dominant_factor",
             "top_risks", "macro_blindspots", "caveats", "sector_breakdown_basis", "concentration",
             "dominant_factor_note", "top_resilient", "hedge_candidates", "macro_blindspots_note",
             "bond_carry", "cash_rub_pct", "blocked_pct", "blocked_rub_memo", "weight_base_note",
             "scenario_matrix_ref", "forecast_type", "horizon_coverage", "horizon_label_note",
             "method", "notes"]


_NAME_RE = re.compile(r"^[a-z0-9-]+$")  # как stress_job._NAME_RE


def matrix_name(path: str) -> str | None:
    """Имя матрицы — как stress_job.matrix_name: без папки и расширения .yaml/.yml/.md."""
    name = re.sub(r"\.(ya?ml|md)$", "", Path(path.strip()).name)
    return name if _NAME_RE.match(name) else None


def macro_matrix_mismatch(cur: str | None, macro_yaml: Any, macro_name: str | None) -> str | None:
    """Текст отказа, если макро-файл собран на другой матрице, чем прогон (cur — имя матрицы прогона).
    Ссылки на матрицу в макро-файле нет — None."""
    if not cur:
        return None
    sm = macro_yaml.get("scenario_matrix") if isinstance(macro_yaml, dict) else None
    ref = sm.get("source_file") if isinstance(sm, dict) else None
    if isinstance(ref, str) and matrix_name(ref) not in (None, cur):
        return (f"файл макро-цепочки {macro_name or '?'} собран на матрице {matrix_name(ref)}, а прогон — на {cur}: "
                "сначала пересобери макро-прогноз на новой матрице (/macro-forecast-chain)")
    return None


def numeric_factors_from_macro(macro: dict, sids: list[str], as_of: str, horizon_ends: dict) -> tuple[dict, dict, list[str]]:
    """Числовые факторы сценариев и покрытие сроков по сетке дат макро-файла — общий код
    stress_build («из макро-файла») и пересчёта сайта. -> (factors_by_horizon, horizon_coverage, warnings)."""
    try:
        return chf.factors_from_macro(macro, sids, as_of, horizon_ends)
    except ValueError as e:
        raise RecalcError(str(e))


def apply_macro(j: dict, macro: Any, macro_name: str, today: str) -> tuple[dict, list[str]]:
    """Суждения с подставленной макро-таблицей: числовые факторы, baseline_spot, horizon_coverage, уровень КС
    купонного слоя и macro_input — по сетке макро-файла на сроки источника. sanctions/geopol не трогаются.
    Сначала проверки одним списком. -> (новые суждения, предупреждения макро-файла)."""
    if not isinstance(macro, dict):
        raise RecalcError("--macro-scenarios: ожидался словарь")
    sids = sorted(j["scenarios"])
    errs, _ = chf.validate_macro(macro, sids)
    cur = matrix_name(str((j.get("meta") or {}).get("scenario_matrix_ref") or ""))
    mm = macro_matrix_mismatch(cur, macro, macro_name)
    if mm:
        errs = list(errs) + [mm]
    if errs:
        raise RecalcError("макро-файл не годится для подстановки:\n  " + "\n  ".join(errs))
    horizon_ends = j["meta"]["horizon_ends"]
    fbh, cov, mw = numeric_factors_from_macro(macro, sids, today, horizon_ends)
    out = copy.deepcopy(j)
    for sid in sids:
        tgt = out["scenarios"][sid].setdefault("factors_by_horizon", {})
        for hk in horizon_ends:
            tgt.setdefault(hk, {}).update(fbh[sid][hk])
    out["horizon_coverage"] = cov
    bs = copy.deepcopy(macro["baseline_spot"])
    out["meta"]["baseline_spot"] = bs
    out["meta"]["macro_input"] = macro_name
    out.setdefault("carry", {})["baseline_cbr_rate_pct"] = bs.get("cbr_rate_pct", bs.get("cbr_rate"))
    return out, [f"макро-файл: {w}" for w in mw]


def inputs_from_stress(stress: dict) -> tuple[dict, dict]:
    """Полный стресс -> (суждения, контекст). Контекст — то, что есть только в полном файле."""
    try:
        j = sj.extract(stress)
    except ValueError as e:
        raise RecalcError(str(e))
    pp = stress["per_position"]
    ctx = {"prev_weight_pct": {t: (v or {}).get("weight_pct") for t, v in pp.items()}}
    return j, ctx


def _reorder(tree: dict) -> dict:
    head = [k for k in TOP_ORDER if k in tree]
    rest = [k for k in tree if k not in TOP_ORDER and k != "recalc"]
    return {k: tree[k] for k in head + rest + (["recalc"] if "recalc" in tree else [])}


WEIGHT_TOL = 1e-6  # допуск суммы весов на горизонте — как в input_contract.check_scenario_weights


def check_weights_file(w: dict, j: dict) -> dict[str, dict[str, float]]:
    """Проверяет stress-weights@1 против стресса; возвращает weights {hNN: {sid: w}}."""
    if w.get("schema") != "stress-weights@1":
        raise RecalcError(f"--weights-json: schema {w.get('schema')!r}, нужен 'stress-weights@1'")
    he, sh = w.get("horizon_ends"), j["meta"]["horizon_ends"]
    if he != sh:
        raise RecalcError(f"горизонты стресса изменились: веса заданы на {he}, стресс посчитан на "
                          f"{sh} — веса нужно пересмотреть")
    wt = w.get("weights")
    if not isinstance(wt, dict):
        raise RecalcError("--weights-json: нет weights")
    sids = set(j["scenarios"])
    for hk in sh:
        row = wt.get(hk)
        if not isinstance(row, dict):
            raise RecalcError(f"--weights-json: нет весов на горизонт {hk}")
        if set(row) != sids:
            raise RecalcError(f"--weights-json: сценарии {sorted(row)} на {hk} не совпадают со "
                              f"стрессом {sorted(sids)}")
        for sid, v in row.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
                raise RecalcError(f"--weights-json: вес {sid} на {hk} = {v!r} вне [0, 1] или не число")
        if abs(sum(row.values()) - 1.0) > WEIGHT_TOL:
            raise RecalcError(f"--weights-json: сумма весов на {hk} = {sum(row.values())}, нужно 1")
    return {hk: dict(wt[hk]) for hk in sh}


def apply_weights(scenarios: dict, wt: dict, j: dict) -> None:
    ph = f"h{j['meta']['primary_horizon']}"
    if ph not in wt:
        raise RecalcError(f"primary_horizon {ph} нет среди горизонтов стресса")
    for sid, sc in scenarios.items():
        sc["p_by_horizon"] = {hk: wt[hk][sid] for hk in j["meta"]["horizon_ends"]}
        sc["p"] = wt[ph][sid]


_EXTRAP_TYPE_RE = re.compile(r"^(H\d+|HORIZON)_EXTRAPOLATED$", re.IGNORECASE)
CAVEAT_MARK = "ЗАПОЛНИТЬ_В_FILL"  # заглушка слота суждения режима «только числа» (stress_build.MARK)


def script_caveats(tree: dict) -> list[dict]:
    """Оговорки о покрытии сроков прогнозом — по одной на срок со статусом не covered.
    Числа и даты только из tree['horizon_coverage'], без пересчётов."""
    cov = tree.get("horizon_coverage")
    if not isinstance(cov, dict):
        return []
    out = []
    for hk, c in cov.items():
        if not isinstance(c, dict) or c.get("status") == "covered":
            continue
        warns = "; ".join(str(w) for w in (c.get("warnings") or []))
        status = {"extrapolated": "срок за пределами прогноза"}.get(c.get("status"), f"покрытие прогнозом — {c.get('status')}")
        msg = (f"{hk} ({c.get('target_date')}): {status}, "
               f"неопределённость умножена на ×{c.get('ci_inflation')}. "
               + (f"{warns}. " if warns else "")
               + "Числа срока по этим факторам — продолжение последней точки прогноза, читать как направление.")
        out.append({"severity": "HIGH", "type": "HORIZON_EXTRAPOLATED", "source": "script",
                    "horizon": hk, "message": msg})
    return out


def is_extrap_caveat(c: Any) -> bool:
    """Запись о покрытии сроков: от скрипта или модельная того же типа."""
    return isinstance(c, dict) and (c.get("source") == "script"
                                    or bool(_EXTRAP_TYPE_RE.match(str(c.get("type") or ""))))


def merge_script_caveats(tree: dict) -> list | None:
    """caveats дерева без прежних записей о покрытии сроков + свежие записи скрипта (в конец).
    Нет списка caveats или в нём заглушка режима «только числа» — оставляем как есть."""
    cv = tree.get("caveats")
    if not isinstance(cv, list) or CAVEAT_MARK in json.dumps(cv, ensure_ascii=False):
        return cv
    return [c for c in cv if not is_extrap_caveat(c)] + script_caveats(tree)


def recalc(j: dict, snapshot: dict, *, source_name: str, source_kind: str, ctx: dict | None,
           weights: dict | None, weights_name: str | None, today: str, at: str,
           macro: dict | None = None) -> tuple[dict, dict]:
    """macro — {"input": имя нового макро-файла, "was": прежний macro_input, "notes": [...]}: суждения j уже
    несут подставленную таблицу (apply_macro); recalc лишь записывает происхождение пересчёта."""
    t0 = time.perf_counter()
    ctx = ctx or {}
    meta = j["meta"]
    if not isinstance(j.get("scenarios"), dict) or not j["scenarios"]:
        raise RecalcError("в источнике нет scenarios")
    horizon_ends = meta.get("horizon_ends")
    if not isinstance(horizon_ends, dict) or not horizon_ends:
        raise RecalcError("в источнике нет horizon_ends")
    weight_type = meta.get("weight_type")
    if weight_type not in ("equal", "probability"):
        raise RecalcError(f"weight_type источника {weight_type!r} не equal|probability")
    carry = j.get("carry") or {}
    base_cbr = carry.get("baseline_cbr_rate_pct")
    if base_cbr is None:
        bs = meta.get("baseline_spot") or {}
        base_cbr = bs.get("cbr_rate_pct", bs.get("cbr_rate"))
    if base_cbr is None:
        raise RecalcError("нет уровня КС: ни bond_carry.baseline_cbr_rate_pct, ни baseline_spot")

    scenarios = copy.deepcopy(j["scenarios"])
    notes: list[str] = []
    if weights is not None:
        apply_weights(scenarios, check_weights_file(weights, j), j)

    priors = copy.deepcopy(j["priors"])
    snap_tickers = {(h.get("ticker") or "").upper() for h in snapshot.get("holdings") or []}
    prev_w = ctx.get("prev_weight_pct") or {}
    dropped = [{"ticker": t, "weight_pct": prev_w.get(t)}
               for t in priors if t.upper() not in snap_tickers]
    cov = j.get("horizon_coverage")
    ci_infl = None
    if isinstance(cov, dict) and cov:
        ci_infl = {hk: float(v.get("ci_inflation", 1.0)) if isinstance(v, dict) else float(v)
                   for hk, v in cov.items()}

    try:
        per_position, _warn, unmapped = cpp.compute_per_position(
            snapshot=snapshot, scenarios=scenarios, priors=priors,
            regression_mode="priors", horizon_ci_inflation=ci_infl,
            horizon_ends=horizon_ends)
    except SystemExit as e:
        raise RecalcError(str(e.code).strip())

    known_unmapped = set(j.get("known_unmapped_tickers") or [])
    names = {(h.get("ticker") or "").upper(): h.get("name") for h in snapshot.get("holdings") or []}
    needs = [{"ticker": u["ticker"], "name": names.get(str(u["ticker"]).upper()),
              "weight_pct": u.get("weight_pct")}
             for u in unmapped
             if u.get("ticker") and "no priors" in str(u.get("reason", ""))
             and u["ticker"] not in known_unmapped]

    bond = cbc.run({"snapshot": snapshot, "scenarios": scenarios,
                    "baseline": {"cbr_rate_pct": base_cbr},
                    "horizon_ends": horizon_ends,
                    "overrides": carry.get("overrides") or None,
                    "params": carry.get("params") or {}})
    bond_block = bond["bond_carry"]
    if carry.get("overrides"):
        bond_block["overrides"] = copy.deepcopy(carry["overrides"])

    include_ev = bool(meta.get("include_ev"))
    agg = cpa.compute(snapshot, scenarios, per_position, bond_block, weight_type, include_ev)

    # Сборка: «стаб» = суждения с новыми мета-полями и весами; расчётные блоки
    # assemble() подменяет фрагментами, поля суждения остаются как были.
    nar = copy.deepcopy(j.get("narrative") or {})
    nar.pop("portfolio_summary", None)
    rob_judg = nar.pop("robustness", None) or {}
    conc_src = nar.get("concentration") if isinstance(nar.get("concentration"), dict) else {}
    try:
        derived, skipped = cdf.compute_with_report(
            snapshot, per_position, bond_block, agg, scenarios,
            {"priors": priors, "concentration_factor": conc_src.get("dominant_factor")})
    except cdf.SectorTableError as e:
        raise RecalcError(str(e))
    # Посчитанное не переносится из источника; у concentration остаются суждения (фактор, note).
    conc_rest = None
    for k in derived:
        if k == "concentration":
            conc_rest = {a: b for a, b in conc_src.items() if a not in CONC_DERIVED_KEYS}
            nar.pop("concentration", None)
        else:
            nar.pop(k, None)
    # Не посчитано: значение источника остаётся (устарело), причина — в notes. Памятка о
    # заблокированных позициях при их отсутствии не нужна — убирается, а не переносится.
    stale_fields: list[str] = []
    reported: set[str] = set()
    for k, why in skipped.items():
        if k == "blocked_rub_memo" and why.startswith("нет заблокированных"):
            nar.pop(k, None)
            continue
        if why not in reported:
            reported.add(why)
            notes.append(f"не посчитано {', '.join(x for x, w in skipped.items() if w == why)}: {why}")
        if k in nar:
            stale_fields.append(k)
    stub = {k: copy.deepcopy(v) for k, v in meta.items() if k != "include_ev"}
    stub["scenarios"] = {}
    for sid, sc in scenarios.items():
        stub["scenarios"][sid] = {k: copy.deepcopy(v) for k, v in sc.items()}
    if j.get("horizon_coverage"):
        stub["horizon_coverage"] = copy.deepcopy(j["horizon_coverage"])
    stub.update(nar)
    changed_snapshot = snapshot.get("as_of_date") is not None and \
        f"portfolio-{snapshot.get('as_of_date')}.json" != j.get("source_snapshot_id")
    stub["date"] = today
    stub["portfolio_snapshot_id"] = f"portfolio-{snapshot.get('as_of_date')}.json"
    stub["base_value_rub"] = round(compute_base_value_rub(snapshot))
    stub["run_id"] = f"RECALC-{today.replace('-', '')}-{j.get('source_run_id') or 'PSS'}"
    # Суждения внутри расчётного фрагмента (слоты TODO_LLM) — из источника.
    fill_rob = {k: rob_judg.get(k) for k in ("modal_scenario", "hedge_target")
                if asm.is_ph(agg["robustness"].get(k))}
    if any(v is None for v in fill_rob.values()):
        raise RecalcError("в robustness источника нет modal_scenario/hedge_target")
    fill: dict = {"robustness": fill_rob} if fill_rob else {}
    if conc_rest:
        fill["concentration"] = conc_rest
    tree, sources = asm.assemble(stub, {"per_position": per_position, "unmapped_tickers": unmapped},
                                 agg, bond, None, fill, derived)

    changed_weights = any(
        j["scenarios"][s].get("p") != scenarios[s].get("p")
        or j["scenarios"][s].get("p_by_horizon") != scenarios[s].get("p_by_horizon")
        for s in scenarios)
    reason = ("both" if changed_snapshot and changed_weights else
              "snapshot" if changed_snapshot else "weights" if changed_weights else "none")
    stale = changed_snapshot or changed_weights
    if macro is not None:
        stale = True
        if reason == "none":
            reason = "macro"
        notes += list(macro.get("notes") or [])
    if "caveats" in tree:
        tree["caveats"] = merge_script_caveats(tree)
    tree = _reorder(tree)
    tree["recalc"] = {
        "source_stress": source_name,
        "source_kind": source_kind,
        "source_snapshot_id": j.get("source_snapshot_id"),
        "snapshot_id": tree["portfolio_snapshot_id"],
        "weights_source": f"stress-weights:{weights_name}" if weights is not None else "stress",
        "reason": reason,
        "at": at,
        "narrative_stale": stale,
        "stale_numeric_fill_fields": stale_fields,
        "needs_judgment": needs,
        "dropped": dropped,
    }
    if macro is not None:
        tree["recalc"]["macro_input"] = macro["input"]
        tree["recalc"]["macro_input_was"] = macro.get("was")
    if weights is not None and weights.get("set_at"):
        tree["recalc"]["weights_set_at"] = weights["set_at"]
    if notes:
        tree["recalc"]["notes"] = notes
    summary = {
        "positions_computed": len(per_position), "needs_judgment": len(needs),
        "dropped": len(dropped), "reason": reason, "narrative_stale": stale,
        "weights_source": tree["recalc"]["weights_source"],
        "sources": sources, "elapsed_s": round(time.perf_counter() - t0, 3),
    }
    return tree, summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Пересчёт чисел стресс-файла на новом снапшоту/весах, без модели")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--stress", type=Path, default=None)
    src.add_argument("--judgments", type=Path, default=None)
    ap.add_argument("--snapshot", required=True, type=Path)
    ap.add_argument("--weights-json", dest="weights", type=Path, default=None)
    ap.add_argument("--macro-scenarios", type=Path, default=None,
                    help="новая макро-таблица: числовые факторы, baseline_spot и покрытие сроков по её сетке дат")
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--today", default=None, help="YYYY-MM-DD, default — сегодня (МСК)")
    ap.add_argument("--at", default=None, help="ISO-время для recalc.at, default — сейчас (+03:00)")
    ap.add_argument("--json", action="store_true")
    try:
        args = ap.parse_args()
    except SystemExit as e:
        return 2 if e.code else 0

    now = datetime.now(MSK)
    today = args.today or now.date().isoformat()
    at = args.at or now.replace(microsecond=0).isoformat()
    try:
        datetime.strptime(today, "%Y-%m-%d")
    except ValueError:
        sys.stderr.write(f"ОШИБКА: --today {today!r} не YYYY-MM-DD\n")
        return 2
    try:
        for name, p in (("--stress", args.stress), ("--judgments", args.judgments),
                        ("--snapshot", args.snapshot), ("--weights-json", args.weights),
                        ("--macro-scenarios", args.macro_scenarios)):
            if p is not None and p.resolve() == args.output.resolve():
                sys.stderr.write(f"ОТКАЗ: --output совпадает с {name}\n")
                return 1 if name in ("--stress", "--judgments") else 2
        if args.stress is not None:
            stress = _load_yaml(args.stress, "--stress")
            if not isinstance(stress, dict):
                raise RecalcError("--stress: ожидался словарь")
            judg, ctx = inputs_from_stress(stress)
            src_path, kind = args.stress, "stress"
        else:
            judg = _load_yaml(args.judgments, "--judgments")
            errs = sj.validate(judg)
            if errs:
                raise RecalcError("--judgments невалиден:\n" + "\n".join(f"  {x}" for x in errs))
            ctx, src_path, kind = None, args.judgments, "judgments"
        if not args.snapshot.exists():
            raise RecalcError(f"--snapshot не найден: {args.snapshot}")
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
        weights = json.loads(args.weights.read_text(encoding="utf-8")) if args.weights else None
        if args.weights and not isinstance(weights, dict):
            raise RecalcError("--weights-json: ожидался объект")

        macro_info = None
        if args.macro_scenarios is not None:
            macro_yaml = _load_yaml(args.macro_scenarios, "--macro-scenarios")
            was = (judg.get("meta") or {}).get("macro_input")
            judg, mnotes = apply_macro(judg, macro_yaml, args.macro_scenarios.name, today)
            macro_info = {"input": args.macro_scenarios.name, "was": was, "notes": mnotes}
        tree, summary = recalc(judg, snapshot, source_name=src_path.name, source_kind=kind, ctx=ctx,
                               weights=weights, weights_name=args.weights.name if args.weights else None,
                               today=today, at=at, macro=macro_info)
        issues = asm.validate_tree(tree, snapshot)
        if tree["recalc"]["needs_judgment"]:
            # Бумага без чувствительностей — известная неполнота: блокеры покрытия (3.13)
            # остаются открытыми и записываются в recalc, остальные отказывают как обычно.
            open_ = [i for i in issues if str(i["code"]) == "3.13"]
            issues = [i for i in issues if i not in open_]
            tree["recalc"]["validator_open"] = [
                f"[{i['code']}] {i['field']}: ожидалось {i['expected']!r}, факт {i['actual']!r}" for i in open_]
        if issues:
            lines = [f"  [{i['code']}] {i['field']}: ожидалось {i['expected']!r}, факт {i['actual']!r}"
                     for i in issues]
            raise RecalcError(f"валидатор: блокеров {len(issues)}, файл не записан:\n" + "\n".join(lines))
        summary["validation"] = "ok"
    except (RecalcError, asm.AssembleError) as e:
        sys.stderr.write(f"ОТКАЗ: {e}\n")
        return 1

    asm.atomic_write(args.output, _dump_yaml(tree))
    summary["output"] = str(args.output)
    if args.json:
        sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(f"OK: {args.output} (бумаг {summary['positions_computed']}, "
                         f"needs_judgment {summary['needs_judgment']}, dropped {summary['dropped']}, "
                         f"причина {summary['reason']}, {summary['elapsed_s']} с)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
