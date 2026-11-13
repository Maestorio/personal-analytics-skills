#!/usr/bin/env python3
"""
normalize_stress.py — читалка архивных stress-YAML (до basis_contract) в
канонический вид контракта баз расчёта (Задача 4,
docs/investment/task-stress-basis-contract.md).

ПОЧЕМУ. В архиве `delta_rub` означает разное в разных прогонах (price-only в
одних, price+bond_carry в других) под ОДНИМ И ТЕМ ЖЕ именем — источник ложного
вывода «доходность ушла в минус» при сравнении двух прогонов. База
определяется АРИФМЕТИКОЙ (независимая сверка с пересчитанной снизу вверх
ценовой суммой + суммой bond_carry), а не по дате файла или имени поля —
имена полей сами были источником путаницы, доверять им нельзя.

ЧТО ДЕЛАЕТ.
  1. Находит и грузит снапшот, на который ссылается `portfolio_snapshot_id`
     (единственный надёжный численный якорь: `base_value_rub` в архивном YAML
     нигде не лежит чистым числом — иногда только в свободном тексте
     комментария `weight_base_note`, иногда отсутствует вовсе).
  2. Для каждой ячейки `scenarios.<sid>.portfolio_level_by_horizon.<hk>` с
     непустым `delta_rub` независимо пересчитывает:
       - `price_sum` — bottom-up по `per_position` (ТА ЖЕ формула, что
         RECONCILE 3.7 валидатора / `compute_portfolio_aggregates.py`):
         `Σ weight_pct/100 × positions_value_rub × delta_pct/100`, где
         `positions_value_rub` (БЕЗ кэша) — не `base_value_rub` (с кэшем),
         см. `input_contract.compute_positions_value_rub`;
       - `carry_sum` — Σ `value_rub × carry_pct/100` по позициям `bond_carry`
         (архивные записи carry не несут `value_rub` — берётся из снапшота по
         тикеру/ISIN, суммируя обе ноги main+iis_3).
  3. `basis = price`, если `delta_rub ≈ price_sum`; `total_return`, если
     `delta_rub − price_sum ≈ carry_sum`; иначе `unknown` — НЕ угадывать.
  4. Маппит известные алиасы: `l1_price_only_delta_rub`→`price_delta_rub`,
     `l1_price_only_pct`→`price_delta_pct`, `total_return_by_horizon_rub[h][X]`→
     эквивалент `portfolio_level_by_horizon`, плоский `robustness`→под
     определённую базу (только если basis файла консистентна по всем ячейкам).

ЧЕГО НЕ ДЕЛАЕТ. Не пишет в исходный файл (read-only читалка). Не
пересчитывает impact/беты/веса. Не заменяет валидатор — готовит данные для
чтения человеком/отчёта, `validate_stress_output.py` остаётся гейтом записи
НОВЫХ файлов.

CLI:
  python3 normalize_stress.py --input <stress.yaml> [--snapshots-dir DIR] [--json]
  python3 normalize_stress.py --batch "<glob>" --snapshots-dir DIR --report <out.md>

Без `--snapshots-dir` ищется `<родитель родителя input>/snapshots/` (совпадает
с раскладкой `Portfolio/stress/` + `Portfolio/snapshots/`).

stdlib only (PyYAML — только в CLI для чтения YAML).
"""
from __future__ import annotations

import argparse
import glob as glob_mod
import json
import sys
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from input_contract import compute_base_value_rub, compute_positions_value_rub  # noqa: E402

TOL_BASE_FRACTION = 0.005  # ±0.5% от base_value_rub — тот же допуск, что RECONCILE 3.7


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


def _pv(cell: Any) -> float | None:
    if cell is None:
        return None
    if isinstance(cell, dict):
        return cell.get("value")
    return cell


def _horizon_keys(data: dict) -> list[str]:
    keys: set[str] = set()
    for sc in (data.get("scenarios") or {}).values():
        if isinstance(sc, dict):
            keys.update((sc.get("portfolio_level_by_horizon") or {}).keys())
    return sorted(keys, key=lambda hk: int(hk[1:]))


def _value_rub_by_ident(snapshot: dict) -> dict[str, float]:
    """Σ value_rub по тикеру/ISIN, суммируя обе ноги main+iis_3 (та же
    логика, что дедуп в compute_bond_carry.py — старые архивные значения
    carry по одной ноге теряли бы вторую)."""
    out: dict[str, float] = {}
    for h in snapshot.get("holdings") or []:
        if not isinstance(h, dict) or h.get("is_blocked"):
            continue
        ident = (h.get("ticker") or "").upper()
        if ident:
            out[ident] = out.get(ident, 0.0) + float(h.get("value_rub") or 0)
    return out


def price_sum_bottom_up(per_position: dict, sid: str, hk: str,
                         positions_value_rub: float) -> float | None:
    """Та же формула, что RECONCILE 3.7 / compute_portfolio_aggregates._price_delta_rub."""
    total = 0.0
    found = False
    for pos in (per_position or {}).values():
        if not isinstance(pos, dict):
            continue
        weight_pct = pos.get("weight_pct")
        by_h = (pos.get("by_horizon") or {}).get(hk) or {}
        delta = _pv((by_h.get("delta_pct_by_scenario") or {}).get(sid))
        if weight_pct is None or delta is None:
            continue
        total += (weight_pct / 100.0) * positions_value_rub * (delta / 100.0)
        found = True
    return total if found else None


def carry_sum_from_snapshot(bond_carry: dict | None, value_by_ident: dict[str, float],
                             sid: str, hk: str) -> float | None:
    """Σ value_rub(снапшот) × carry_pct/100 по позициям bond_carry. Архивные
    записи carry несут `value_rub` только для CASH_RUB (было всегда) — для
    бумаг/MM-фондов ищем в снапшоте по тикеру/ISIN."""
    if not bond_carry:
        return None
    per_position = bond_carry.get("per_position") or {}
    if not per_position:
        return None
    total = 0.0
    found = False
    for ident, pos in per_position.items():
        if not isinstance(pos, dict):
            continue
        by_h = (pos.get("by_horizon") or {}).get(hk)
        if not by_h:
            continue
        cell = (by_h.get("by_scenario") or {}).get(sid)
        if not isinstance(cell, dict) or cell.get("carry_pct") is None:
            continue
        value_rub = pos.get("value_rub")
        if value_rub is None:
            value_rub = value_by_ident.get(str(ident).upper())
        if value_rub is None:
            continue  # тикер не нашёлся в снапшоте — эта позиция не участвует в сумме
        total += float(value_rub) * cell["carry_pct"] / 100.0
        found = True
    return total if found else None


def determine_basis(delta_rub: float | None, price_sum: float | None,
                     carry_sum: float | None, tol: float,
                     base_value_rub: float | None = None,
                     positions_value_rub: float | None = None) -> dict[str, Any]:
    if delta_rub is None or price_sum is None:
        return {"basis": "unknown", "method": 4, "reason": "delta_rub или price_sum недоступны"}
    if abs(delta_rub - price_sum) <= tol:
        return {"basis": "price", "method": 2}
    if carry_sum is not None and abs((delta_rub - price_sum) - carry_sum) <= tol:
        return {"basis": "total_return", "method": 3}
    carry_repr = "carry_sum отсутствует" if carry_sum is None else f"{carry_sum:.0f}"
    reason = (f"delta_rub={delta_rub} не сходится ни с price_sum={price_sum:.0f} "
              f"(diff={delta_rub - price_sum:.0f}), ни с price_sum+carry_sum ({carry_repr})")
    # Диагностика (НЕ официальная база — задача 4.1 знает только price/total_return):
    # исторический дефект «weight_pct домножен на base_value_rub (с кэшем) вместо
    # positions_value_rub» — та же природа, что регрессия 2026-09-18 в этой же
    # задаче, только относится к прогону, а не к моему коду. Не угадываем basis,
    # но называем находку, если числа сходятся.
    if base_value_rub and positions_value_rub and positions_value_rub != base_value_rub:
        ratio = base_value_rub / positions_value_rub
        price_sum_wrong_base = price_sum * ratio
        if abs(delta_rub - price_sum_wrong_base) <= tol:
            reason += (f"; ПОХОЖЕ на независимый исторический дефект — delta_rub ≈ "
                       f"price_sum × (base_value_rub/positions_value_rub) = "
                       f"{price_sum_wrong_base:.0f} (тот же класс ошибки, что регрессия "
                       f"positions_value_rub 2026-09-18, но в самом прогоне, не в валидаторе)")
    return {"basis": "unknown", "method": 4, "reason": reason}


def normalize(data: dict, snapshot: dict) -> dict[str, Any]:
    base_value_rub = compute_base_value_rub(snapshot)
    positions_value_rub = compute_positions_value_rub(snapshot)
    tol = max(base_value_rub * TOL_BASE_FRACTION, 1)
    value_by_ident = _value_rub_by_ident(snapshot)
    bond_carry = data.get("bond_carry")
    horizons = _horizon_keys(data)
    scenarios = data.get("scenarios") or {}
    total_return_by_h = data.get("total_return_by_horizon_rub") or {}

    cells: dict[str, dict[str, Any]] = {}
    bases_seen: set[str] = set()
    recovered: set[str] = set()
    missing: set[str] = set()

    for sid, sc in scenarios.items():
        if not isinstance(sc, dict):
            continue
        plbh = sc.get("portfolio_level_by_horizon") or {}
        cells[sid] = {}
        for hk in horizons:
            cell = plbh.get(hk)
            if not isinstance(cell, dict):
                continue
            delta_rub = cell.get("delta_rub")
            l1_delta = cell.get("l1_price_only_delta_rub")
            l1_pct = cell.get("l1_price_only_pct")
            price_sum = price_sum_bottom_up(data.get("per_position"), sid, hk, positions_value_rub)
            carry_sum = carry_sum_from_snapshot(bond_carry, value_by_ident, sid, hk)

            verdict = determine_basis(delta_rub, price_sum, carry_sum, tol,
                                      base_value_rub, positions_value_rub)
            bases_seen.add(verdict["basis"])

            entry: dict[str, Any] = {
                "delta_rub": delta_rub,
                "price_sum_recomputed": round(price_sum) if price_sum is not None else None,
                "carry_sum_recomputed": round(carry_sum) if carry_sum is not None else None,
                **verdict,
            }
            if l1_delta is not None:
                entry["l1_price_only_delta_rub"] = l1_delta
                if price_sum is not None:
                    entry["l1_price_only_matches_recomputed_price"] = abs(l1_delta - price_sum) <= tol
            trbh = (total_return_by_h.get(hk) or {}).get(sid)
            if trbh is not None:
                entry["total_return_by_horizon_rub"] = trbh
                if price_sum is not None and carry_sum is not None:
                    entry["total_return_by_horizon_rub_matches_recomputed"] = \
                        abs(trbh - (price_sum + carry_sum)) <= tol

            normalized_cell = {}
            if price_sum is not None:
                normalized_cell["price_delta_rub"] = round(price_sum)
                normalized_cell["price_delta_pct"] = round(price_sum / base_value_rub * 100, 4) if base_value_rub else None
                recovered.add("price_delta_rub")
            if carry_sum is not None:
                normalized_cell["carry_rub"] = round(carry_sum)
                normalized_cell["carry_pct"] = round(carry_sum / base_value_rub * 100, 4) if base_value_rub else None
                recovered.add("carry_rub")
            if price_sum is not None and carry_sum is not None:
                normalized_cell["total_return_rub"] = round(price_sum + carry_sum)
                normalized_cell["total_return_pct"] = round((price_sum + carry_sum) / base_value_rub * 100, 4) if base_value_rub else None
                recovered.add("total_return_rub")
            elif verdict["basis"] == "price" and l1_pct is None:
                # basis=price и carry неизвестен (напр. нет bond_carry вовсе,
                # 05-11..06-28) → total_return не восстановить, честно молчим.
                missing.add("total_return_rub (нет bond_carry в архиве)")
            entry["normalized"] = normalized_cell

            cells[sid][hk] = entry

    bases_determined = bases_seen - {"unknown"}
    if len(bases_determined) == 1:
        file_basis = next(iter(bases_determined))
    elif not bases_determined:
        file_basis = "unknown"
    else:
        file_basis = "mixed"  # аномалия: разные ячейки одного файла дают разную базу

    robustness_note = None
    flat_robustness = data.get("robustness")
    if isinstance(flat_robustness, dict) and "by_horizon" not in flat_robustness \
            and "price" not in flat_robustness and "total_return" not in flat_robustness:
        if file_basis in ("price", "total_return"):
            robustness_note = f"плоский robustness → под {file_basis} (файл консистентен по базе)"
        else:
            robustness_note = f"плоский robustness НЕ размечен — basis файла={file_basis}, размечать нельзя"

    unknown_reasons = sorted({
        c["reason"] for sc in cells.values() for c in sc.values()
        if c["basis"] == "unknown" and c.get("reason")
    })

    return {
        "portfolio_snapshot_id": data.get("portfolio_snapshot_id"),
        "date": data.get("date"),
        "run_id": data.get("run_id") or data.get("stress_id"),
        "base_value_rub": round(base_value_rub),
        "positions_value_rub": round(positions_value_rub),
        "file_basis": file_basis,
        "cells": cells,
        "recovered_fields": sorted(recovered),
        "missing_fields": sorted(missing),
        "unknown_reasons": unknown_reasons,
        "robustness_note": robustness_note,
    }


# ───────────────────────────── batch / report (§4.2) ─────────────────────────────

def _default_snapshots_dir(input_path: Path) -> Path:
    return input_path.resolve().parent.parent / "snapshots"


def _load_for_file(input_path: Path, snapshots_dir: Path) -> tuple[dict, dict] | None:
    data = _load_yaml(input_path)
    snap_id = data.get("portfolio_snapshot_id")
    if not snap_id:
        sys.stderr.write(f"ERROR: {input_path.name}: нет portfolio_snapshot_id\n")
        return None
    snap_path = snapshots_dir / str(snap_id).strip('"').strip("'")
    if not snap_path.exists():
        sys.stderr.write(f"ERROR: {input_path.name}: снапшот не найден: {snap_path}\n")
        return None
    with snap_path.open("r", encoding="utf-8") as f:
        snapshot = json.load(f)
    return data, snapshot


def build_report(results: list[tuple[str, dict | None, str | None]]) -> str:
    """results: [(filename, normalize()-результат|None, ошибка|None)]"""
    lines = [
        "# Регрессия normalize_stress.py по архиву (Задача 4.2)",
        "",
        "Авто-сгенерировано `normalize_stress.py --batch`. Не редактировать руками.",
        "",
        "| Файл | Дата | run_id | Базы `delta_rub` | Метод | Восстановлено | Отсутствует безвозвратно |",
        "|---|---|---|---|---|---|---|",
    ]
    unknown_notes: list[str] = []
    for fname, res, err in results:
        if err:
            lines.append(f"| {fname} | — | — | **ERROR: {err}** | — | — | — |")
            continue
        methods = sorted({c["method"] for sc in res["cells"].values() for c in sc.values()})
        lines.append(
            f"| {fname} | {res['date']} | {res['run_id']} | {res['file_basis']} | "
            f"{','.join(str(m) for m in methods)} | {', '.join(res['recovered_fields']) or '—'} | "
            f"{', '.join(res['missing_fields']) or '—'} |"
        )
        if res["file_basis"] in ("unknown", "mixed") and res.get("unknown_reasons"):
            unknown_notes.append(f"### {fname}\n\n" + "\n".join(f"- {r}" for r in res["unknown_reasons"]))
    if unknown_notes:
        lines.append("")
        lines.append("## Файлы с `basis: unknown` — детали")
        lines.append("")
        lines.append(
            "Официальная база НЕ определена (не price, не total_return) — задача 4.1 "
            "запрещает угадывать. Диагностика ниже — дополнительная находка, не "
            "замена определению; помечена отдельно, где числа совпали с известным "
            "классом ошибки (weight_pct домножен на `base_value_rub` вместо "
            "`positions_value_rub` в самом прогоне)."
        )
        lines.append("")
        lines.extend(unknown_notes)
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Нормализация архивных stress-YAML к контракту баз расчёта (Задача 4)")
    ap.add_argument("--input", type=Path)
    ap.add_argument("--batch", type=str, help="Glob-паттерн для регрессии (§4.2)")
    ap.add_argument("--snapshots-dir", type=Path, default=None)
    ap.add_argument("--report", type=Path, help="Куда сохранить .md-отчёт (только с --batch)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.input and not args.batch:
        sys.stderr.write("ERROR: нужен --input или --batch\n")
        return 2

    if args.batch:
        paths = sorted(Path(p) for p in glob_mod.glob(args.batch))
        if not paths:
            sys.stderr.write(f"ERROR: --batch не нашёл файлов: {args.batch}\n")
            return 2
        results = []
        any_error = False
        for p in paths:
            snapshots_dir = args.snapshots_dir or _default_snapshots_dir(p)
            loaded = _load_for_file(p, snapshots_dir)
            if loaded is None:
                results.append((p.name, None, "снапшот/поле не найдены"))
                any_error = True
                continue
            data, snapshot = loaded
            try:
                res = normalize(data, snapshot)
                results.append((p.name, res, None))
            except Exception as e:  # noqa: BLE001 — регрессия обязана не падать, а зафиксировать сбой
                results.append((p.name, None, f"{type(e).__name__}: {e}"))
                any_error = True

        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(build_report(results), encoding="utf-8")
            print(f"OK: отчёт → {args.report}")
        if args.json:
            print(json.dumps(
                [{"file": f, "result": r, "error": e} for f, r, e in results],
                ensure_ascii=False, indent=2, default=str))
        else:
            for fname, res, err in results:
                if err:
                    print(f"{fname}: ERROR — {err}")
                else:
                    print(f"{fname}: basis={res['file_basis']} "
                          f"recovered={res['recovered_fields']} missing={res['missing_fields']}")
        return 1 if any_error else 0

    snapshots_dir = args.snapshots_dir or _default_snapshots_dir(args.input)
    loaded = _load_for_file(args.input, snapshots_dir)
    if loaded is None:
        return 2
    data, snapshot = loaded
    result = normalize(data, snapshot)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"basis: {result['file_basis']}")
        print(f"base_value_rub={result['base_value_rub']} positions_value_rub={result['positions_value_rub']}")
        for sid, by_h in result["cells"].items():
            for hk, cell in by_h.items():
                print(f"  {sid}/{hk}: basis={cell['basis']} (метод {cell['method']}) "
                      f"delta_rub={cell['delta_rub']} price_sum={cell['price_sum_recomputed']} "
                      f"carry_sum={cell['carry_sum_recomputed']}")
        if result["recovered_fields"]:
            print(f"recovered: {', '.join(result['recovered_fields'])}")
        if result["missing_fields"]:
            print(f"missing: {', '.join(result['missing_fields'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
