#!/usr/bin/env python3
"""
validate_stress_output.py — валидатор контракта баз расчёта stress-YAML (basis contract).

ПОЧЕМУ. За 17 прогонов (2026-05-11…2026-09-18) портфельный уровень стресса
менял имена/состав 4 раза, и одни и те же имена значили разную базу
(price-only vs price+bond_carry) — сравнение двух прогонов давало ложный вывод
«доходность ушла в минус», хотя менялась только база. Полная спека —
docs/investment/task-stress-basis-contract.md, контракт полей —
_shared-references/yaml-schemas.md §11.2a.

ЧТО ЭТО ДЕЛАЕТ. Читает готовый stress-YAML (schema_version 2 + basis_contract)
и проверяет: (STRUCTURE) присутствие и точные имена контрактных полей;
(RECONCILE) сходимость чисел — тождество слоёв price+carry=total_return,
сверку портфельного уровня с суммой per_position снизу вверх, вероятностное
взвешивание, диапазон, robustness, проценты. Обе группы блокирующие.

ЧЕГО ЭТО НЕ ДЕЛАЕТ. Не читает архивные файлы БЕЗ basis_contract — те
отклоняются как несоответствующие контракту (это ожидаемое поведение, не
дефект: см. приёмку §4 задачи). Для чтения архива — scripts/normalize_stress.py
(отдельная задача 4). Не пересчитывает impact и не трогает беты/веса/горизонты.

Зависимости: PyYAML. Сети нет.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Sibling-импорт для positions_value_rub (RECONCILE 3.7) — тот же приём sys.path,
# что уже используют compute_per_position.py / compute_bond_carry.py / build_stress_stub.py /
# compute_portfolio_aggregates.py.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from input_contract import compute_positions_value_rub  # noqa: E402


# ─────────────────────────── допуски ───────────────────────────

TOL_RUB = 1                 # ±1 ₽, округление
TOL_PP = 0.01                # ±0.01 п.п., проценты
TOL_BASE_FRACTION = 0.005    # ±0.5% от base_value_rub, агрегатные сверки снизу вверх
TOL_PROB_SUM = 1e-6          # сумма вероятностных весов на горизонте

FORBIDDEN_PORTFOLIO_LEVEL_KEYS = {
    "delta_rub": "price_delta_rub и total_return_rub — оба явно, разные числа",
    "l1_price_only_delta_rub": "price_delta_rub",
    "l1_price_only_pct": "price_delta_pct",
    "expected_pct_pweighted": "portfolio_aggregates.<basis>.expected_pl_pct_by_horizon "
                               "(внутри per_position это же имя легитимно)",
}

FORBIDDEN_TOP_LEVEL_KEYS = {
    "expected_pl_rub": "portfolio_aggregates.{price,total_return}.expected_pl_rub_by_horizon",
    "portfolio_pl_range_rub": "portfolio_aggregates.{price,total_return}.pl_range_rub_by_horizon",
    "total_return_by_horizon_rub": "scenarios.<X>.portfolio_level_by_horizon.<hNN>.total_return_rub",
}

BASES = ("price", "total_return")


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        sys.stderr.write(
            "ERROR: модуль 'yaml' не установлен. "
            "Установить: pip install pyyaml --break-system-packages\n"
        )
        raise SystemExit(2)
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _issue(code: str, field: str, expected: Any, actual: Any) -> dict[str, Any]:
    return {"code": code, "field": field, "severity": "blocking",
            "expected": expected, "actual": actual}


def _pv(cell: Any) -> float | None:
    """Значение сценарной ячейки — плоское число или {value, ci_pct}."""
    if cell is None:
        return None
    if isinstance(cell, dict):
        return cell.get("value")
    return cell


def _close(a: float | None, b: float | None, tol: float) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol


def _horizons(data: dict) -> list[str]:
    hs = data.get("horizons") or []
    return [f"h{h}" for h in hs]


# ─────────────────────────── STRUCTURE ───────────────────────────

def check_structure(data: dict) -> list[dict]:
    issues: list[dict] = []
    horizons = _horizons(data)
    scenarios = data.get("scenarios") or {}

    # 3.1 — обязательные top-level поля контракта баз
    basis_contract = data.get("basis_contract")
    if basis_contract is None:
        issues.append(_issue("3.1", "basis_contract", "int, присутствует", None))

    layers = data.get("layers_included")
    if not isinstance(layers, dict):
        issues.append(_issue("3.1", "layers_included", "dict {price, bond_carry, dividends}", layers))
    else:
        dividends = layers.get("dividends")
        if not (isinstance(dividends, bool) and dividends is False):
            issues.append(_issue("3.1", "layers_included.dividends", "false (строго)", dividends))
        for key in ("price", "bond_carry"):
            if not isinstance(layers.get(key), bool):
                issues.append(_issue("3.1", f"layers_included.{key}", "bool", layers.get(key)))

    ppb = data.get("per_position_basis")
    if ppb != "price":
        issues.append(_issue("3.1", "per_position_basis", "price", ppb))

    base_value_rub = data.get("base_value_rub")
    if not isinstance(base_value_rub, (int, float)) or isinstance(base_value_rub, bool) or base_value_rub <= 0:
        issues.append(_issue("3.1", "base_value_rub", "int > 0", base_value_rub))

    if not data.get("base_value_note"):
        issues.append(_issue("3.1", "base_value_note", "непустая строка", data.get("base_value_note")))

    p_basis = data.get("p_basis")
    if p_basis not in ("primary_horizon", "mean_across_horizons"):
        issues.append(_issue("3.1", "p_basis", "primary_horizon | mean_across_horizons", p_basis))

    # 3.2 — запрещённые имена на портфельном уровне
    for key, replacement in FORBIDDEN_TOP_LEVEL_KEYS.items():
        if key in data:
            issues.append(_issue("3.2", key, f"использовать {replacement}", "присутствует (deprecated)"))

    for sid, sc in scenarios.items():
        if not isinstance(sc, dict):
            continue
        plbh = sc.get("portfolio_level_by_horizon") or {}
        if not isinstance(plbh, dict):
            continue
        for hk, cell in plbh.items():
            if not isinstance(cell, dict):
                continue
            for key, replacement in FORBIDDEN_PORTFOLIO_LEVEL_KEYS.items():
                if key in cell:
                    issues.append(_issue(
                        "3.2", f"scenarios.{sid}.portfolio_level_by_horizon.{hk}.{key}",
                        f"использовать {replacement}", "присутствует (deprecated)"))

    # 3.3 — basis совпадает с ключом блока
    for block_name in ("portfolio_aggregates", "robustness"):
        block = data.get(block_name) or {}
        if not isinstance(block, dict):
            continue
        for basis in BASES:
            sub = block.get(basis)
            if not isinstance(sub, dict):
                continue
            if sub.get("basis") != basis:
                issues.append(_issue(
                    "3.3", f"{block_name}.{basis}.basis", basis, sub.get("basis")))

    # 3.4 — покрытие всех горизонтов, обе базы
    for block_name in ("portfolio_aggregates", "robustness"):
        block = data.get(block_name) or {}
        if not isinstance(block, dict):
            continue
        for basis in BASES:
            sub = block.get(basis)
            if not isinstance(sub, dict):
                issues.append(_issue("3.4", f"{block_name}.{basis}", "dict с basis+by_horizon/*_by_horizon", sub))
                continue
            if block_name == "portfolio_aggregates":
                by_h_fields = ("expected_pl_rub_by_horizon", "expected_pl_pct_by_horizon",
                               "pl_range_rub_by_horizon")
                for field in by_h_fields:
                    fh = sub.get(field) or {}
                    missing = [h for h in horizons if h not in fh]
                    if missing:
                        issues.append(_issue(
                            "3.4", f"{block_name}.{basis}.{field}",
                            f"все горизонты {horizons}", f"отсутствуют {missing}"))
            else:  # robustness
                fh = sub.get("by_horizon") or {}
                missing = [h for h in horizons if h not in fh]
                if missing:
                    issues.append(_issue(
                        "3.4", f"{block_name}.{basis}.by_horizon",
                        f"все горизонты {horizons}", f"отсутствуют {missing}"))

    # 3.5 — per_position всегда price; ни одного намёка на carry/total_return/coupon
    per_position = data.get("per_position") or {}
    banned_substrings = ("carry", "total_return", "coupon")
    for ticker, pos in per_position.items():
        if not isinstance(pos, dict):
            continue
        by_h = pos.get("by_horizon") or {}
        for hk, cell in by_h.items():
            if not isinstance(cell, dict):
                continue
            for key in _flatten_keys(cell):
                low = key.lower()
                if any(b in low for b in banned_substrings):
                    issues.append(_issue(
                        "3.5", f"per_position.{ticker}.by_horizon.{hk}.{key}",
                        "ключи только про price (per_position_basis == price)",
                        "имя намекает на carry/total_return/coupon"))

    return issues


def _flatten_keys(d: dict, prefix: str = "") -> list[str]:
    out = []
    for k, v in d.items():
        full = f"{prefix}{k}"
        out.append(full)
        if isinstance(v, dict):
            out.extend(_flatten_keys(v, prefix=f"{full}."))
    return out


# ─────────────────────────── RECONCILE ───────────────────────────

def check_reconcile(data: dict, snapshot: dict | None) -> list[dict]:
    issues: list[dict] = []
    horizons = _horizons(data)
    scenarios = data.get("scenarios") or {}
    base_value_rub = data.get("base_value_rub")
    per_position = data.get("per_position") or {}
    positions_value_rub = _resolve_positions_value_rub(data, base_value_rub, snapshot)

    issues += _check_layer_identity(scenarios, horizons)
    issues += _check_bottom_up(scenarios, per_position, horizons, base_value_rub, positions_value_rub)
    issues += _check_probability_weighting(data, scenarios, horizons)
    issues += _check_horizon_collision(scenarios)
    issues += _check_range(data, scenarios, horizons)
    issues += _check_robustness(data, scenarios, horizons)
    issues += _check_percents(data, scenarios, horizons, base_value_rub)
    if snapshot is not None:
        issues += _check_coverage(data, per_position, snapshot)
        issues += _check_carry_provenance(data, snapshot)
    return issues


def _check_layer_identity(scenarios: dict, horizons: list[str]) -> list[dict]:
    """3.6 — total_return_rub == price_delta_rub + carry_rub, ±1 ₽."""
    issues = []
    for sid, sc in scenarios.items():
        plbh = (sc or {}).get("portfolio_level_by_horizon") or {}
        for hk in horizons:
            cell = plbh.get(hk)
            if not isinstance(cell, dict):
                continue
            price = cell.get("price_delta_rub")
            carry = cell.get("carry_rub")
            total = cell.get("total_return_rub")
            if price is None or carry is None or total is None:
                continue
            if not _close(total, price + carry, TOL_RUB):
                issues.append(_issue(
                    "3.6", f"scenarios.{sid}.portfolio_level_by_horizon.{hk}.total_return_rub",
                    price + carry, total))
    return issues


def _resolve_positions_value_rub(data: dict, base_value_rub: float | None,
                                  snapshot: dict | None) -> float | None:
    """Без-кэшевая база для weight_pct (compute_per_position.compute_total_value) —
    НЕ совпадает с `base_value_rub` (с кэшем, §1.1), если в портфеле есть кэш.
    Со снапшотом — точно (`compute_positions_value_rub`); без него —
    приближение через задекларированные `cash_rub_pct`/`blocked_pct` (уже
    существующие top-level поля, не из этого контракта). Перепутать эти два
    знаменателя — систематически завысить сумму на долю кэша (найдено
    2026-09-18 при построении normalize_stress.py)."""
    if snapshot is not None:
        return compute_positions_value_rub(snapshot)
    if not base_value_rub:
        return None
    cash_pct = data.get("cash_rub_pct") or 0
    blocked_pct = data.get("blocked_pct") or 0
    return base_value_rub * (1 - (cash_pct + blocked_pct) / 100.0)


def _check_bottom_up(scenarios: dict, per_position: dict, horizons: list[str],
                      base_value_rub: float | None,
                      positions_value_rub: float | None) -> list[dict]:
    """3.7 — price_delta_rub сходится с суммой по позициям, ±0.5% base_value_rub."""
    issues = []
    if not base_value_rub or not positions_value_rub:
        return issues
    tol = base_value_rub * TOL_BASE_FRACTION
    for sid, sc in scenarios.items():
        plbh = (sc or {}).get("portfolio_level_by_horizon") or {}
        for hk in horizons:
            cell = plbh.get(hk)
            if not isinstance(cell, dict) or cell.get("price_delta_rub") is None:
                continue
            bottom_up = 0.0
            for pos in per_position.values():
                if not isinstance(pos, dict):
                    continue
                weight_pct = pos.get("weight_pct")
                by_h = (pos.get("by_horizon") or {}).get(hk) or {}
                delta = _pv((by_h.get("delta_pct_by_scenario") or {}).get(sid))
                if weight_pct is None or delta is None:
                    continue
                bottom_up += (weight_pct / 100.0) * positions_value_rub * (delta / 100.0)
            reported = cell["price_delta_rub"]
            if not _close(reported, bottom_up, tol):
                issues.append(_issue(
                    "3.7", f"scenarios.{sid}.portfolio_level_by_horizon.{hk}.price_delta_rub",
                    round(bottom_up), reported))
    return issues


def _p_weight(sc: dict, hk: str) -> float | None:
    p_by_h = sc.get("p_by_horizon") or {}
    if hk in p_by_h:
        return p_by_h[hk]
    return sc.get("p")


def _check_probability_weighting(data: dict, scenarios: dict, horizons: list[str]) -> list[dict]:
    """3.8 — expected_pl_rub_by_horizon == Σ p_by_horizon × pl_rub; Σp == 1."""
    issues = []
    for hk in horizons:
        total_p = 0.0
        have_all = True
        for sc in scenarios.values():
            w = _p_weight(sc or {}, hk)
            if w is None:
                have_all = False
                continue
            total_p += w
        if have_all and not _close(total_p, 1.0, TOL_PROB_SUM):
            issues.append(_issue("3.8", f"scenarios.*.p (Σ на {hk})", 1.0, total_p))

    agg = data.get("portfolio_aggregates") or {}
    field_by_basis = {"price": "price_delta_rub", "total_return": "total_return_rub"}
    for basis, pl_field in field_by_basis.items():
        sub = agg.get(basis) or {}
        expected_by_h = sub.get("expected_pl_rub_by_horizon") or {}
        for hk in horizons:
            expected = expected_by_h.get(hk)
            if expected is None:
                continue  # null допустим — equal-weighted без --include-ev
            weighted_sum = 0.0
            ok = True
            for sid, sc in scenarios.items():
                w = _p_weight(sc or {}, hk)
                cell = (sc.get("portfolio_level_by_horizon") or {}).get(hk) or {}
                pl = cell.get(pl_field)
                if w is None or pl is None:
                    ok = False
                    break
                weighted_sum += w * pl
            if ok and not _close(expected, weighted_sum, TOL_RUB):
                issues.append(_issue(
                    "3.8", f"portfolio_aggregates.{basis}.expected_pl_rub_by_horizon.{hk}",
                    round(weighted_sum), expected))
    return issues


def _check_horizon_collision(scenarios: dict) -> list[dict]:
    """3.9 — детектор, ничего не чинит: два горизонта с идентичными факторами."""
    issues = []
    for sid, sc in scenarios.items():
        fbh = (sc or {}).get("factors_by_horizon") or {}
        keys = list(fbh.keys())
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                h1, h2 = keys[i], keys[j]
                if fbh[h1] == fbh[h2] and fbh[h1]:
                    issues.append(_issue(
                        "3.9", f"scenarios.{sid}.factors_by_horizon",
                        f"{h1} и {h2} численно различимы",
                        f"горизонты {h1}/{h2} совпадают — выбор фактора по ближайшему году "
                        f"дал один и тот же уровень для разных горизонтов"))
    return issues


def _check_range(data: dict, scenarios: dict, horizons: list[str]) -> list[dict]:
    """3.10 — pl_range_rub_by_horizon.min/max/min_scenario/max_scenario."""
    issues = []
    agg = data.get("portfolio_aggregates") or {}
    field_by_basis = {"price": "price_delta_rub", "total_return": "total_return_rub"}
    for basis, pl_field in field_by_basis.items():
        sub = agg.get(basis) or {}
        range_by_h = sub.get("pl_range_rub_by_horizon") or {}
        for hk in horizons:
            r = range_by_h.get(hk)
            if not isinstance(r, dict):
                continue
            values = {}
            for sid, sc in scenarios.items():
                cell = (sc.get("portfolio_level_by_horizon") or {}).get(hk) or {}
                pl = cell.get(pl_field)
                if pl is not None:
                    values[sid] = pl
            if not values:
                continue
            min_sid = min(values, key=values.get)
            max_sid = max(values, key=values.get)
            if not _close(r.get("min"), values[min_sid], TOL_RUB):
                issues.append(_issue("3.10", f"portfolio_aggregates.{basis}.pl_range_rub_by_horizon.{hk}.min",
                                      values[min_sid], r.get("min")))
            if not _close(r.get("max"), values[max_sid], TOL_RUB):
                issues.append(_issue("3.10", f"portfolio_aggregates.{basis}.pl_range_rub_by_horizon.{hk}.max",
                                      values[max_sid], r.get("max")))
            if r.get("min_scenario") != min_sid:
                issues.append(_issue("3.10", f"portfolio_aggregates.{basis}.pl_range_rub_by_horizon.{hk}.min_scenario",
                                      min_sid, r.get("min_scenario")))
            if r.get("max_scenario") != max_sid:
                issues.append(_issue("3.10", f"portfolio_aggregates.{basis}.pl_range_rub_by_horizon.{hk}.max_scenario",
                                      max_sid, r.get("max_scenario")))
    return issues


def _check_robustness(data: dict, scenarios: dict, horizons: list[str]) -> list[dict]:
    """3.11 — positive_or_neutral_scenarios / worst_case / best_case / spread_pct."""
    issues = []
    robustness = data.get("robustness") or {}
    field_by_basis = {"price": "price_delta_pct", "total_return": "total_return_pct"}
    for basis, pct_field in field_by_basis.items():
        sub = robustness.get(basis) or {}
        by_h = sub.get("by_horizon") or {}
        for hk in horizons:
            r = by_h.get(hk)
            if not isinstance(r, dict):
                continue
            values = {}
            for sid, sc in scenarios.items():
                cell = (sc.get("portfolio_level_by_horizon") or {}).get(hk) or {}
                pct = cell.get(pct_field)
                if pct is not None:
                    values[sid] = pct
            if not values:
                continue
            expected_count = sum(1 for v in values.values() if v >= 0)
            if r.get("positive_or_neutral_scenarios") != expected_count:
                issues.append(_issue(
                    "3.11", f"robustness.{basis}.by_horizon.{hk}.positive_or_neutral_scenarios",
                    expected_count, r.get("positive_or_neutral_scenarios")))
            worst_sid = min(values, key=values.get)
            best_sid = max(values, key=values.get)
            worst = r.get("worst_case") or {}
            best = r.get("best_case") or {}
            if worst.get("id") != worst_sid or not _close(worst.get("pl_pct"), values[worst_sid], TOL_PP):
                issues.append(_issue(
                    "3.11", f"robustness.{basis}.by_horizon.{hk}.worst_case",
                    {"id": worst_sid, "pl_pct": values[worst_sid]}, worst))
            if best.get("id") != best_sid or not _close(best.get("pl_pct"), values[best_sid], TOL_PP):
                issues.append(_issue(
                    "3.11", f"robustness.{basis}.by_horizon.{hk}.best_case",
                    {"id": best_sid, "pl_pct": values[best_sid]}, best))
            expected_spread = values[best_sid] - values[worst_sid]
            if not _close(r.get("spread_pct"), expected_spread, TOL_PP):
                issues.append(_issue(
                    "3.11", f"robustness.{basis}.by_horizon.{hk}.spread_pct",
                    round(expected_spread, 4), r.get("spread_pct")))
    return issues


def _check_percents(data: dict, scenarios: dict, horizons: list[str],
                     base_value_rub: float | None) -> list[dict]:
    """3.12 — *_pct == *_rub / base_value_rub × 100."""
    issues = []
    if not base_value_rub:
        return issues
    for sid, sc in scenarios.items():
        plbh = (sc or {}).get("portfolio_level_by_horizon") or {}
        for hk in horizons:
            cell = plbh.get(hk)
            if not isinstance(cell, dict):
                continue
            for rub_field, pct_field in (("price_delta_rub", "price_delta_pct"),
                                          ("carry_rub", "carry_pct"),
                                          ("total_return_rub", "total_return_pct")):
                rub = cell.get(rub_field)
                pct = cell.get(pct_field)
                if rub is None or pct is None:
                    continue
                expected_pct = rub / base_value_rub * 100
                if not _close(pct, expected_pct, TOL_PP):
                    issues.append(_issue(
                        "3.12", f"scenarios.{sid}.portfolio_level_by_horizon.{hk}.{pct_field}",
                        round(expected_pct, 4), pct))

    agg = data.get("portfolio_aggregates") or {}
    for basis in BASES:
        sub = agg.get(basis) or {}
        rub_by_h = sub.get("expected_pl_rub_by_horizon") or {}
        pct_by_h = sub.get("expected_pl_pct_by_horizon") or {}
        for hk in horizons:
            rub = rub_by_h.get(hk)
            pct = pct_by_h.get(hk)
            if rub is None or pct is None:
                continue
            expected_pct = rub / base_value_rub * 100
            if not _close(pct, expected_pct, TOL_PP):
                issues.append(_issue(
                    "3.12", f"portfolio_aggregates.{basis}.expected_pl_pct_by_horizon.{hk}",
                    round(expected_pct, 4), pct))
    return issues


def _check_coverage(data: dict, per_position: dict, snapshot: dict) -> list[dict]:
    """3.13 — unmapped_tickers пуст; тикеры в снапшоте; Σ weight_pct == 100 ± 0.5."""
    issues = []
    unmapped = data.get("unmapped_tickers") or []
    if unmapped:
        issues.append(_issue("3.13", "unmapped_tickers", "[]", unmapped))

    snapshot_ids = set()
    for h in snapshot.get("holdings", []):
        if h.get("is_blocked"):
            continue
        for key in ("ticker", "isin"):
            v = h.get(key)
            if v:
                snapshot_ids.add(v)

    for ticker in per_position:
        if ticker not in snapshot_ids:
            issues.append(_issue("3.13", f"per_position.{ticker}",
                                  "тикер/ISIN присутствует в снапшоте (unblocked)",
                                  "не найден в снапшоте"))

    total_weight = sum(p.get("weight_pct", 0) for p in per_position.values() if isinstance(p, dict))
    if not _close(total_weight, 100.0, 0.5):
        issues.append(_issue("3.13", "Σ per_position[*].weight_pct", "100 ± 0.5", total_weight))
    return issues


def _check_carry_provenance(data: dict, snapshot: dict) -> list[dict]:
    """3.14 — bond_carry.per_position ISIN в снапшоте; credit_review_required → carry 0."""
    issues = []
    bond_carry = data.get("bond_carry") or {}
    carry_positions = bond_carry.get("per_position") or {}
    if not carry_positions:
        return issues

    snapshot_ids = set()
    for h in snapshot.get("holdings", []):
        for key in ("ticker", "isin"):
            v = h.get(key)
            if v:
                snapshot_ids.add(v)

    for ident, pos in carry_positions.items():
        if ident in ("CASH_RUB",):
            continue
        if ident not in snapshot_ids:
            issues.append(_issue("3.14", f"bond_carry.per_position.{ident}",
                                  "ISIN присутствует в снапшоте", "не найден в снапшоте"))
        if not isinstance(pos, dict):
            continue
        flags = pos.get("flags") or []
        if "credit_review_required" in flags:
            for hk, cell in (pos.get("by_horizon") or {}).items():
                expected_carry = cell.get("expected_carry_pct")
                if expected_carry not in (0, 0.0):
                    issues.append(_issue(
                        "3.14", f"bond_carry.per_position.{ident}.by_horizon.{hk}.expected_carry_pct",
                        0, expected_carry))
    return issues


# ─────────────────────────── entrypoint ───────────────────────────

def validate(data: dict, snapshot: dict | None = None) -> list[dict]:
    issues = check_structure(data)
    issues += check_reconcile(data, snapshot)
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Валидатор контракта баз расчёта stress-YAML (basis_contract)")
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--snapshot", type=Path, default=None,
                    help="portfolio-{date}.json — включает проверки 3.13/3.14")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.input.exists():
        sys.stderr.write(f"ERROR: файл не найден: {args.input}\n")
        return 2

    data = _load_yaml(args.input)
    snapshot = None
    if args.snapshot:
        if not args.snapshot.exists():
            sys.stderr.write(f"ERROR: снапшот не найден: {args.snapshot}\n")
            return 2
        with open(args.snapshot, encoding="utf-8") as fh:
            snapshot = json.load(fh)

    issues = validate(data, snapshot)

    if args.json:
        sys.stdout.write(json.dumps({"ok": not issues, "issues": issues},
                                     ensure_ascii=False, indent=2) + "\n")
    else:
        if not issues:
            print("OK — контракт баз расчёта соблюдён.")
        else:
            print(f"БЛОКЕРЫ ({len(issues)}):")
            for i in issues:
                print(f"  [{i['code']}] {i['field']}: ожидалось {i['expected']!r}, факт {i['actual']!r}")

    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
