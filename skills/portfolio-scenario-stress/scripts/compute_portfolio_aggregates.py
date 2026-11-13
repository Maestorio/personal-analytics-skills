#!/usr/bin/env python3
"""
compute_portfolio_aggregates.py — контракт баз расчёта (basis contract, 2026-09-18):
детерминированно собирает `scenarios.<X>.portfolio_level_by_horizon` (обе базы),
`portfolio_aggregates` и `robustness` из уже готовых фрагментов — `per_position`
(Layer 1, compute_per_position.py) + `bond_carry` (Layer 2, compute_bond_carry.py).

ПОЧЕМУ. За 17 прогонов (2026-05-11…2026-09-18) эти числа модель считала вручную —
4 сценария × 3 горизонта × 2 базы за проход — и 17 раз подряд база съезжала под
одним и тем же именем поля (сравнение прогонов давало ложный вывод «доходность
ушла в минус», хотя менялась только база). Полная спека —
docs/investment/task-stress-basis-contract.md; контракт полей —
_shared-references/yaml-schemas.md §11.2a. `validate_stress_output.py` проверяет
РЕЗУЛЬТАТ постфактум — сеть безопасности, не замена этому скрипту: он устраняет
причину, вручную считать эти ячейки больше не нужно.

`price_delta_rub` считается ТОЙ ЖЕ формулой, что RECONCILE 3.7 валидатора
(bottom-up: Σ weight_pct/100 × base_value_rub × delta_pct/100) — если аггрегатор
и валидатор используют одну формулу, 3.7 проходит по построению.

Вход (CLI собирает из файлов; run() принимает уже разобранные dict):
  --snapshot      portfolio-{date}.json (для base_value_rub — Σ value_rub
                  unblocked holdings + cash, ОДНА функция на весь скилл,
                  input_contract.compute_base_value_rub)
  --scenarios     YAML с блоком scenarios: {p, p_by_horizon (опц.)} на сценарий
  --per-position  YAML — выход compute_per_position.py ({"per_position": {...}})
  --bond-carry    YAML — выход compute_bond_carry.py ({"bond_carry": {...}}),
                  опционально (портфель без облигаций)
  --weight-type   equal | probability
  --include-ev    считать expected_pl_*_by_horizon (иначе null — см. SKILL.md,
                  Expected P&L публикуется только для probability-weighted
                  входа И по явному флагу; для Pure Shell equal-weighted это
                  осознанное решение D2, не забывчивость)
  --output        путь для YAML-фрагмента

Выход (фрагмент, копируется в соответствующие места финального stress-YAML):
  {scenarios: {<sid>: {portfolio_level_by_horizon: {hNN: {price_delta_rub,
     price_delta_pct, carry_rub, carry_pct, total_return_rub, total_return_pct}}}},
   portfolio_aggregates: {price, total_return}, robustness: {price, total_return}}

Этот скрипт НЕ эмитит top-level `basis_contract`/`layers_included`/`base_value_rub`/
`base_value_note`/`per_position_basis`/`p_basis` — это уже делает
build_stress_stub.py (та же функция, тот же снапшот → то же число; повторно
эмитить их здесь означало бы два места, считающих одно и то же, — ровно тот
класс дрейфа, ради которого пишется контракт).

stdlib only (PyYAML — только в CLI для чтения/записи YAML).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Sibling-импорт для base_value_rub — тот же приём sys.path, что уже используют
# compute_per_position.py / compute_bond_carry.py / build_stress_stub.py.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from input_contract import compute_base_value_rub, compute_positions_value_rub  # noqa: E402

BASES = ("price", "total_return")


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError:
        sys.stderr.write(
            "ERROR: модуль 'yaml' не установлен. "
            "Установить: pip install pyyaml --break-system-packages\n"
        )
        sys.exit(2)
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _dump_yaml(obj: Any) -> str:
    import yaml  # type: ignore
    return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _pv(cell: Any) -> float | None:
    """Значение сценарной ячейки — плоское число или {value, ci_pct}."""
    if cell is None:
        return None
    if isinstance(cell, dict):
        return cell.get("value")
    return cell


def _p_weight(sc: dict[str, Any], hk: str) -> float | None:
    p_by_h = sc.get("p_by_horizon") or {}
    if hk in p_by_h:
        return p_by_h[hk]
    return sc.get("p")


def _horizon_keys(per_position: dict[str, Any]) -> list[str]:
    keys: set[str] = set()
    for pos in per_position.values():
        if isinstance(pos, dict):
            keys.update((pos.get("by_horizon") or {}).keys())
    return sorted(keys, key=lambda hk: int(hk[1:]))


def _price_delta_rub(
    per_position: dict[str, Any], sid: str, hk: str, positions_value_rub: float,
) -> float:
    """Bottom-up сумма по позициям — та же формула, что RECONCILE 3.7 валидатора.

    Множитель — `positions_value_rub` (БЕЗ кэша), НЕ `base_value_rub` (с кэшем):
    `weight_pct` нормирован на без-кэшевую базу (compute_per_position.py,
    compute_total_value) — см. docstring compute_positions_value_rub в
    input_contract.py. Перепутать эти два знаменателя — систематически
    завысить сумму на долю кэша."""
    total = 0.0
    for pos in per_position.values():
        if not isinstance(pos, dict):
            continue
        weight_pct = pos.get("weight_pct")
        by_h = (pos.get("by_horizon") or {}).get(hk) or {}
        delta = _pv((by_h.get("delta_pct_by_scenario") or {}).get(sid))
        if weight_pct is None or delta is None:
            continue
        total += (weight_pct / 100.0) * positions_value_rub * (delta / 100.0)
    return total


def expected_pl(values_rub: dict[str, float], weights: dict[str, float],
                base_value_rub: float) -> tuple[int, float]:
    """Ожидание по весам сценариев на одном горизонте и базе: (₽, % от base_value_rub).

    values_rub — готовые (уже округлённые) итоги портфеля по сценариям; от весов они не зависят,
    поэтому «а что если» сайта пересчитывает только эту свёртку, а не весь стресс."""
    ev_rub = sum(weights[sid] * values_rub[sid] for sid in values_rub)
    return round(ev_rub), (round(ev_rub / base_value_rub * 100.0, 4) if base_value_rub else 0.0)


def compute(
    snapshot: dict[str, Any],
    scenarios: dict[str, Any],
    per_position: dict[str, Any],
    bond_carry: dict[str, Any] | None,
    weight_type: str,
    include_ev: bool,
) -> dict[str, Any]:
    base_value_rub = compute_base_value_rub(snapshot)
    positions_value_rub = compute_positions_value_rub(snapshot)
    horizons = _horizon_keys(per_position)
    carry_by_h = (bond_carry or {}).get("portfolio_level_by_horizon") or {}

    scenarios_out: dict[str, Any] = {}
    # По базе × горизонту × сценарию — числа, нужные и portfolio_aggregates, и robustness.
    rub_by_basis: dict[str, dict[str, dict[str, float]]] = {b: {h: {} for h in horizons} for b in BASES}
    pct_by_basis: dict[str, dict[str, dict[str, float]]] = {b: {h: {} for h in horizons} for b in BASES}

    for sid in scenarios:
        plbh: dict[str, Any] = {}
        for hk in horizons:
            price_delta_rub = _price_delta_rub(per_position, sid, hk, positions_value_rub)
            carry_cell = (carry_by_h.get(hk) or {}).get(sid) or {}
            carry_rub = carry_cell.get("carry_rub", 0) or 0
            total_return_rub = price_delta_rub + carry_rub

            price_delta_pct = (price_delta_rub / base_value_rub * 100.0) if base_value_rub else 0.0
            carry_pct = (carry_rub / base_value_rub * 100.0) if base_value_rub else 0.0
            total_return_pct = (total_return_rub / base_value_rub * 100.0) if base_value_rub else 0.0

            plbh[hk] = {
                "price_delta_rub": round(price_delta_rub),
                "price_delta_pct": round(price_delta_pct, 4),
                "carry_rub": round(carry_rub),
                "carry_pct": round(carry_pct, 4),
                "total_return_rub": round(total_return_rub),
                "total_return_pct": round(total_return_pct, 4),
            }
            rub_by_basis["price"][hk][sid] = plbh[hk]["price_delta_rub"]
            rub_by_basis["total_return"][hk][sid] = plbh[hk]["total_return_rub"]
            pct_by_basis["price"][hk][sid] = plbh[hk]["price_delta_pct"]
            pct_by_basis["total_return"][hk][sid] = plbh[hk]["total_return_pct"]
        scenarios_out[sid] = {"portfolio_level_by_horizon": plbh}

    can_compute_ev = weight_type == "probability" and include_ev

    portfolio_aggregates: dict[str, Any] = {}
    robustness: dict[str, Any] = {}
    for basis in BASES:
        expected_rub: dict[str, float | None] = {}
        expected_pct: dict[str, float | None] = {}
        pl_range: dict[str, Any] = {}
        rob_by_h: dict[str, Any] = {}
        for hk in horizons:
            values_rub = rub_by_basis[basis][hk]
            values_pct = pct_by_basis[basis][hk]

            if can_compute_ev:
                expected_rub[hk], expected_pct[hk] = expected_pl(
                    values_rub, {sid: _p_weight(scenarios[sid], hk) for sid in values_rub}, base_value_rub)
            else:
                expected_rub[hk] = None
                expected_pct[hk] = None

            min_sid = min(values_rub, key=values_rub.get)
            max_sid = max(values_rub, key=values_rub.get)
            pl_range[hk] = {"min": values_rub[min_sid], "max": values_rub[max_sid],
                             "min_scenario": min_sid, "max_scenario": max_sid}

            worst_sid = min(values_pct, key=values_pct.get)
            best_sid = max(values_pct, key=values_pct.get)
            positive_or_neutral = sum(1 for v in values_pct.values() if v >= 0)
            rob_by_h[hk] = {
                "positive_or_neutral_scenarios": positive_or_neutral,
                "worst_case": {"id": worst_sid, "pl_pct": values_pct[worst_sid]},
                "best_case": {"id": best_sid, "pl_pct": values_pct[best_sid]},
                "spread_pct": round(values_pct[best_sid] - values_pct[worst_sid], 4),
            }

        portfolio_aggregates[basis] = {
            "basis": basis,
            "expected_pl_rub_by_horizon": expected_rub,
            "expected_pl_pct_by_horizon": expected_pct,
            "pl_range_rub_by_horizon": pl_range,
        }
        robustness[basis] = {"basis": basis, "by_horizon": rob_by_h}

    # modal_scenario — детерминируем только для equal-weighted (Pure Shell D1,
    # SKILL.md правило 5a: ОБЯЗАТЕЛЬНО "none"). Для probability-weighted это
    # редакционное решение модели (какой сценарий доминирует по смыслу), не
    # арифметика — TODO_LLM.
    robustness["modal_scenario"] = "none" if weight_type == "equal" else "TODO_LLM_id_or_none"
    robustness["hedge_target"] = "TODO_LLM_text"

    return {
        "scenarios": scenarios_out,
        "portfolio_aggregates": portfolio_aggregates,
        "robustness": robustness,
    }


# ───────────────────────────── CLI ─────────────────────────────

def _unwrap(doc: dict[str, Any], key: str) -> dict[str, Any]:
    return doc[key] if isinstance(doc, dict) and key in doc else doc


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Собирает portfolio_level_by_horizon/portfolio_aggregates/robustness "
                    "из per_position + bond_carry (контракт баз расчёта)")
    ap.add_argument("--snapshot", required=True, type=Path)
    ap.add_argument("--scenarios", required=True, type=Path)
    ap.add_argument("--per-position", required=True, type=Path)
    ap.add_argument("--bond-carry", type=Path, default=None)
    ap.add_argument("--weight-type", required=True, choices=["equal", "probability"])
    ap.add_argument("--include-ev", action="store_true")
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    for label, path in (("--snapshot", args.snapshot), ("--scenarios", args.scenarios),
                        ("--per-position", args.per_position)):
        if not path.exists():
            sys.stderr.write(f"ERROR: {label} не найден: {path}\n")
            return 2
    if args.bond_carry and not args.bond_carry.exists():
        sys.stderr.write(f"ERROR: --bond-carry не найден: {args.bond_carry}\n")
        return 2

    with args.snapshot.open("r", encoding="utf-8") as f:
        snapshot = json.load(f)

    scenarios = _unwrap(_load_yaml(args.scenarios), "scenarios")
    if not isinstance(scenarios, dict) or not scenarios:
        sys.stderr.write("ERROR: scenarios пуст или не dict\n")
        return 2

    per_position = _unwrap(_load_yaml(args.per_position), "per_position")
    if not isinstance(per_position, dict) or not per_position:
        sys.stderr.write("ERROR: per_position пуст или не dict — нечего агрегировать\n")
        return 2

    bond_carry = None
    if args.bond_carry:
        bond_carry = _unwrap(_load_yaml(args.bond_carry), "bond_carry")

    result = compute(snapshot, scenarios, per_position, bond_carry,
                     args.weight_type, args.include_ev)

    for name, other in (("--snapshot", args.snapshot), ("--scenarios", args.scenarios),
                        ("--per-position", args.per_position)):
        if args.output.resolve() == other.resolve():
            sys.stderr.write(f"ERROR: --output совпадает с {name} — отказ.\n")
            return 2
    if args.output.exists():
        args.output.unlink()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        f.write("# Auto-generated by compute_portfolio_aggregates.py — copy scenarios.<X>."
                "portfolio_level_by_horizon в соответствующий сценарий стаба;\n")
        f.write("# portfolio_aggregates/robustness — как есть, top-level финального YAML.\n")
        f.write(_dump_yaml(result))

    print(f"OK: portfolio aggregates fragment → {args.output}")
    if not args.include_ev or args.weight_type == "equal":
        print("   expected_pl_*_by_horizon = null (weight_type=equal или без --include-ev, см. D2)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
