"""
macro_grid_check.py — проверка файла макро-цепочки (macro-scenarios-<дата>.yaml): сетка дат уровней факторов.

Одна реализация для трёх мест: расчёт стресса (portfolio-scenario-stress/compute_horizon_factors.py),
сохранение файла (save-to-library: validate-macro-scenarios) и сборка файла (macro-forecast-chain:
check_macro_scenarios.py). Только stdlib.

Пять числовых факторов (MACRO_FACTORS); у каждого `by_scenario.<сценарий>.<дата ISO>.value` либо
`level_all_scenarios.<дата>.value`; спот — в `baseline_spot`. Отказы возвращаются одним списком;
расхождение `pct_vs_spot` с пересчётом по `value` и споту — предупреждение.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)



# ── Сетка дат макро-цепочки ──
# имя фактора в макро-файле → (каноническое имя стресса, вид движения)
MACRO_FACTORS: dict[str, tuple[str, str]] = {
    "brent_price": ("brent", "pct_from_spot"),
    "usdrub_rate": ("usdrub", "pct_from_spot"),
    "cnyrub_rate": ("cnyrub", "pct_from_spot"),
    "cbr_rate": ("cbr_rate", "pp_diff"),
    "xauusd_price": ("xauusd", "pct_from_spot"),
}
PCT_MISMATCH_PP = 0.5  # допуск расхождения pct_vs_spot файла с пересчётом, п.п.


def _iso(key: Any) -> date | None:
    """Ключ даты сетки (строка ISO или date из YAML) → date; не дата → None."""
    if isinstance(key, date):
        return date(key.year, key.month, key.day)
    if isinstance(key, str):
        try:
            return date.fromisoformat(key.strip())
        except ValueError:
            return None
    return None


def _move(level: float, spot: float, kind: str) -> float:
    return (level - spot) / spot * 100.0 if kind == "pct_from_spot" else level - spot


def _factor_grids(fnode: dict, sid: str) -> dict | None:
    """{дата: entry} сценария из by_scenario (приоритет) или level_all_scenarios."""
    bs = fnode.get("by_scenario")
    if isinstance(bs, dict):
        return bs.get(sid)
    return fnode.get("level_all_scenarios")


def _numeric_entries(grid: Any) -> tuple[dict[str, float], dict[str, Any], list[str]]:
    """(уровни {ISO: value}, исходные записи {ISO: entry}, плохие ключи дат)."""
    levels: dict[str, float] = {}
    raw: dict[str, Any] = {}
    bad: list[str] = []
    if not isinstance(grid, dict):
        return levels, raw, bad
    for k, ent in grid.items():
        d = _iso(k)
        if d is None:
            bad.append(str(k))
            continue
        v = ent.get("value") if isinstance(ent, dict) else None
        if _is_number(v):
            levels[d.isoformat()] = float(v)
            raw[d.isoformat()] = ent
    return levels, raw, bad


def validate_macro(macro: Any, scenario_ids: list[str] | None = None) -> tuple[list[str], list[str]]:
    """Проверка всего файла макро-цепочки одним проходом → (ошибки, предупреждения)."""
    errs: list[str] = []
    warns: list[str] = []
    if not isinstance(macro, dict):
        return ["файл макро-цепочки: ожидался словарь верхнего уровня"], warns
    spots = macro.get("baseline_spot")
    if not isinstance(spots, dict):
        errs.append("нет baseline_spot — добавь блок спотов в файл макро-цепочки")
        spots = {}
    factors = macro.get("factors")
    if not isinstance(factors, dict):
        errs.append("нет блока factors — нужны brent_price, usdrub_rate, cnyrub_rate, cbr_rate, xauusd_price")
        factors = {}
    if scenario_ids is None:
        ids: set[str] = set()
        for fn in factors.values():
            if isinstance(fn, dict) and isinstance(fn.get("by_scenario"), dict):
                ids |= {str(k) for k in fn["by_scenario"]}
        scenario_ids = sorted(ids)
    for mname, (_canon, kind) in MACRO_FACTORS.items():
        spot = spots.get(mname)
        if isinstance(macro.get("baseline_spot"), dict):
            if mname not in spots:
                errs.append(f"{mname}: нет спота в baseline_spot")
            elif not (_is_number(spot) and spot > 0):
                errs.append(f"{mname}: спот в baseline_spot {spot!r} не положительное число")
        fnode = factors.get(mname) if factors else None
        if factors and not isinstance(fnode, dict):
            errs.append(f"{mname}: фактор отсутствует в factors")
            continue
        if not isinstance(fnode, dict):
            continue
        if not isinstance(fnode.get("by_scenario"), dict) and not isinstance(fnode.get("level_all_scenarios"), dict):
            errs.append(f"{mname}: нет ни by_scenario, ни level_all_scenarios")
            continue
        for sid in scenario_ids:
            grid = _factor_grids(fnode, sid)
            if grid is None:
                errs.append(f"{mname}, сценарий {sid}: сценария нет в by_scenario")
                continue
            levels, raw, bad = _numeric_entries(grid)
            for b in bad:
                errs.append(f"{mname}, сценарий {sid}: ключ даты {b!r} не ISO-дата (YYYY-MM-DD)")
            if not levels and not bad:
                errs.append(f"{mname}, сценарий {sid}: нет ни одной даты с числовым value")
            elif not levels:
                errs.append(f"{mname}, сценарий {sid}: нет ни одной даты с числовым value (все ключи дат плохие)")
            if kind == "pct_from_spot" and _is_number(spot) and spot > 0:
                for d, ent in raw.items():
                    pv = ent.get("pct_vs_spot")
                    if _is_number(pv):
                        calc = _move(levels[d], float(spot), kind)
                        if abs(calc - float(pv)) > PCT_MISMATCH_PP:
                            warns.append(f"{mname}, сценарий {sid}, {d}: pct_vs_spot {pv} в файле, по value и споту "
                                         f"{calc:.2f} — файл внутренне несогласован")
    return errs, warns


def scenario_ids_from_file(macro: Any) -> list[str]:
    """Сценарии файла: `scenario_matrix.scenarios` (список id/словарей с id, либо словарь id → …), иначе пусто."""
    sm = macro.get("scenario_matrix") if isinstance(macro, dict) else None
    sc = sm.get("scenarios") if isinstance(sm, dict) else None
    out: list[str] = []
    if isinstance(sc, dict):
        out = [str(k) for k in sc]
    elif isinstance(sc, list):
        for x in sc:
            if isinstance(x, dict) and x.get("id") is not None:
                out.append(str(x["id"]))
            elif isinstance(x, (str, int)) and not isinstance(x, bool):
                out.append(str(x))
    return out


def scenario_set_errors(macro: Any) -> list[str]:
    """Набор сценариев `by_scenario` должен быть одинаков у всех факторов, где блок есть."""
    errs: list[str] = []
    factors = macro.get("factors") if isinstance(macro, dict) else None
    if not isinstance(factors, dict):
        return errs
    sets: dict[str, set[str]] = {}
    for mname in MACRO_FACTORS:
        fn = factors.get(mname)
        if isinstance(fn, dict) and isinstance(fn.get("by_scenario"), dict):
            sets[mname] = {str(k) for k in fn["by_scenario"]}
    if len({frozenset(v) for v in sets.values()}) > 1:
        union = set().union(*sets.values())
        for mname, v in sets.items():
            if v != union:
                errs.append(f"{mname}: набор сценариев в by_scenario расходится с другими факторами "
                            f"(нет: {', '.join(sorted(union - v))})")
    return errs


def check_macro_file(macro: Any, scenario_ids: list[str] | None = None) -> tuple[list[str], list[str]]:
    """Проверка при сохранении/сборке: сценарии — из `scenario_matrix.scenarios` файла, иначе из ключей
    `by_scenario` (плюс согласованность наборов между факторами). → (ошибки, предупреждения)."""
    ids = scenario_ids if scenario_ids is not None else (scenario_ids_from_file(macro) or None)
    errs, warns = validate_macro(macro, ids)
    seen = set(errs)
    for e in scenario_set_errors(macro):
        if e not in seen:
            errs.append(e)
    return errs, warns
