#!/usr/bin/env python3
"""
assemble_stress.py — сборка итогового stress-YAML скриптом, а не моделью.

Расчётные скрипты кладут фрагменты во временные файлы; склеивает их этот скрипт.
Модель пишет только `fill.yaml` — поля суждения. Расчётные блоки в ответ модели
не выводятся и руками не переносятся: каждое число доходит до файла без
участия модели. Ничего не пересчитывается и не округляется.

CLI:
  python3 assemble_stress.py --stub STUB --per-position FRAG [--bond-carry FRAG]
      --aggregates FRAG [--horizon-factors JSON] [--derived FRAG] --fill FILL --output OUT
      [--snapshot SNAP] [--no-validate]

ТАБЛИЦА «ключ итогового файла → источник» (для расчётного блока источник один):

  schema_version … modal_flag, basis_contract, layers_included,
  per_position_basis, base_value_rub, base_value_note, p_basis,
  horizon_ends, horizons, primary_horizon, horizon_mode,
  portfolio_snapshot_id, run_id, review_date, scenario_count,
  macro_input                                       -> стаб
  baseline_spot                                     -> стаб (плейсхолдеры — fill)
  factor_definitions                                -> стаб
  scenarios.<X>.name, .p, .p_by_horizon             -> стаб (плейсхолдеры — fill)
  scenarios.<X>.factors_by_horizon                  -> --horizon-factors
                                                       (нет флага — fill)
  scenarios.<X>.portfolio_level_by_horizon          -> --aggregates
  per_position, unmapped_tickers                    -> --per-position
  bond_carry                                        -> --bond-carry
  portfolio_aggregates                              -> --aggregates
  robustness.price, robustness.total_return         -> --aggregates
  robustness.modal_scenario                         -> --aggregates ("none" для
                                                       equal; иначе слот под fill)
  robustness.hedge_target                           -> fill
  horizon_coverage                                  -> --horizon-factors
                                                       (нет флага — fill)
  scenario_source, weight_type, modal_flag          -> стаб (значения по умолчанию;
                                                       fill может переопределить)
  cash_rub_pct, blocked_pct, blocked_rub_memo, weight_base_note,
  sector_breakdown_pct, sector_breakdown_basis, top_risks, top_resilient,
  concentration_ratio, concentration.{same_direction_pct, opposite_pct,
  neutral_pct, same_direction_incl_cnyrub_pct}      -> --derived (compute_derived_fields.py;
                                                       только ключи, которые во фрагменте
                                                       есть; нет флага — fill)
  dominant_factor, macro_blindspots,
  caveats, hedge_candidates, concentration.{dominant_factor, note},
  *_note, method, notes, прочие
  дополнительные ключи (и всё, чего нет в --derived) -> fill

Правила fill (дерево накладывается на результат вглубь; списки заменяются целиком):
  * значение, пришедшее из стаба или фрагмента (не плейсхолдер TODO_LLM), fill
    менять не может; не может и добавлять ключи внутрь такого словаря;
  * плейсхолдеры TODO_LLM* (в стабе, в слотах фрагментов) — места под fill;
  * per_position, unmapped_tickers, bond_carry, portfolio_aggregates и
    scenarios.<X>.portfolio_level_by_horizon fill задавать не может вовсе;
  * ключи из --derived fill задавать не может (concentration: fill добавляет только
    остальные подключи, например note; пересечение подключей — отказ);
  * переопределяемые значения стаба: scenario_source, weight_type, modal_flag;
  * `_drop: [ключи]` — убрать необязательный блок-скелет стаба, целиком
    состоящий из плейсхолдеров.

Отказ (код 1, файл не пишется, причина — на stderr): fill трогает посчитанное;
остался TODO_LLM; не передан обязательный фрагмент; --output совпадает с входом;
блокирующая ошибка валидатора (если не --no-validate).
Код 2 — вход нечитаем / нет PyYAML.

stdout: JSON-сводка (источники блоков, размеры, результат валидации).
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

PLACEHOLDER = "TODO_LLM"
# Значения стаба, которые модель вправе переопределить в fill.
OVERRIDABLE = {("scenario_source",), ("weight_type",), ("modal_flag",)}
# Ключи, которые fill не задаёт никогда (приходят только из фрагментов).
RESERVED_TOP = ("per_position", "unmapped_tickers", "bond_carry", "portfolio_aggregates")
RESERVED_SCENARIO_KEY = "portfolio_level_by_horizon"
# Ключи --derived со вложенным словарём, где fill вправе добавить остальные подключи.
MERGE_DERIVED = ("concentration",)


class AssembleError(Exception):
    """Отказ сборки: сообщение — понятный текст для пользователя."""


def _yaml():
    try:
        import yaml  # type: ignore
    except ImportError:
        sys.stderr.write("ERROR: pyyaml не установлен: pip install pyyaml --break-system-packages\n")
        raise SystemExit(2)
    return yaml


def is_ph(v: Any) -> bool:
    return isinstance(v, str) and v.startswith(PLACEHOLDER)


def has_ph(v: Any) -> bool:
    if is_ph(v):
        return True
    if isinstance(v, dict):
        return any(has_ph(x) for x in v.values())
    if isinstance(v, list):
        return any(has_ph(x) for x in v)
    return False


def find_ph(v: Any, path: str = "") -> list[str]:
    if is_ph(v):
        return [path or "<root>"]
    out: list[str] = []
    if isinstance(v, dict):
        for k, x in v.items():
            out += find_ph(x, f"{path}.{k}" if path else str(k))
    elif isinstance(v, list):
        for i, x in enumerate(v):
            out += find_ph(x, f"{path}[{i}]")
    return out


def load_doc(path: Path, label: str) -> Any:
    yaml = _yaml()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise AssembleError(f"{label}: файл не читается ({path}): {e}")
    try:
        return yaml.safe_load(text)  # JSON — подмножество YAML
    except yaml.YAMLError as e:
        raise AssembleError(f"{label}: не разобрать ({path}): {e}")


def _need_dict(doc: Any, label: str) -> dict:
    if not isinstance(doc, dict):
        raise AssembleError(f"{label}: ожидался словарь верхнего уровня")
    return doc


# ───────────────────────── наложение fill ─────────────────────────

def overlay(base: Any, fill: Any, path: tuple, errors: list[str]) -> Any:
    """Накладывает fill на base (вглубь). Нарушения — в errors, base не портится."""
    p = ".".join(map(str, path))
    if isinstance(base, dict) and isinstance(fill, dict):
        locked_dict = not has_ph(base) and len(path) > 0
        out = dict(base)
        for k, fv in fill.items():
            if k in base:
                out[k] = overlay(base[k], fv, path + (k,), errors)
            elif locked_dict:
                errors.append(f"{p}.{k}: новый ключ внутри посчитанного блока")
            else:
                out[k] = fv
        return out
    # base — лист/список/отсутствует вид, fill — иной вид
    if path in OVERRIDABLE:
        return fill
    if has_ph(base):
        return fill  # слот/скелет с плейсхолдерами заменяется целиком
    errors.append(f"{p}: значение посчитано скриптом/стабом, fill его менять не может")
    return base


# ───────────────────────── сборка ─────────────────────────

def assemble(stub: dict, per_position_frag: dict | None, aggregates: dict | None,
             bond_carry: dict | None, horizon: dict | None, fill: dict | None,
             derived: dict | None = None) -> tuple[dict, dict]:
    """Возвращает (дерево, источники по ключам верхнего уровня)."""
    if per_position_frag is None:
        raise AssembleError("не передан обязательный фрагмент: --per-position")
    if aggregates is None:
        raise AssembleError("не передан обязательный фрагмент: --aggregates")
    fill = copy.deepcopy(fill) if fill else {}
    if not isinstance(fill, dict):
        raise AssembleError("fill: ожидался словарь верхнего уровня")

    doc: dict = copy.deepcopy(stub)
    src: dict[str, set] = {k: {"stub"} for k in doc}

    def put(key: str, value: Any, who: str) -> None:
        doc[key] = copy.deepcopy(value)
        src[key] = {who}

    # per_position
    for k in ("per_position", "unmapped_tickers"):
        if k not in per_position_frag:
            raise AssembleError(f"фрагмент --per-position не содержит ключ {k}")
        put(k, per_position_frag[k], "per-position")

    # агрегаты
    for k in ("scenarios", "portfolio_aggregates", "robustness"):
        if k not in aggregates:
            raise AssembleError(f"фрагмент --aggregates не содержит ключ {k}")
    put("portfolio_aggregates", aggregates["portfolio_aggregates"], "aggregates")
    put("robustness", aggregates["robustness"], "aggregates")
    scen = doc.get("scenarios")
    if not isinstance(scen, dict):
        raise AssembleError("стаб: нет блока scenarios")
    agg_sc = aggregates["scenarios"]
    unknown = sorted(set(agg_sc) - set(scen))
    if unknown:
        raise AssembleError(f"--aggregates: сценарии {unknown} отсутствуют в стабе")
    missing = sorted(set(scen) - set(agg_sc))
    if missing:
        raise AssembleError(f"--aggregates: нет сценариев {missing} из стаба")
    for sid, block in agg_sc.items():
        if RESERVED_SCENARIO_KEY not in block:
            raise AssembleError(f"--aggregates: у сценария {sid} нет portfolio_level_by_horizon")
        scen[sid][RESERVED_SCENARIO_KEY] = copy.deepcopy(block[RESERVED_SCENARIO_KEY])
    src["scenarios"].add("aggregates")

    # bond_carry
    if bond_carry is not None:
        if "bond_carry" not in bond_carry:
            raise AssembleError("фрагмент --bond-carry не содержит ключ bond_carry")
        put("bond_carry", bond_carry["bond_carry"], "bond-carry")

    # горизонтные факторы
    if horizon is not None:
        fbh = horizon.get("factors_by_horizon")
        if not isinstance(fbh, dict):
            raise AssembleError("фрагмент --horizon-factors не содержит factors_by_horizon")
        unknown = sorted(set(fbh) - set(scen))
        if unknown:
            raise AssembleError(f"--horizon-factors: сценарии {unknown} отсутствуют в стабе")
        for sid, v in fbh.items():
            scen[sid]["factors_by_horizon"] = copy.deepcopy(v)
        src["scenarios"].add("horizon-factors")
        if "horizon_coverage" in horizon:
            put("horizon_coverage", horizon["horizon_coverage"], "horizon-factors")

    # производные числа (compute_derived_fields.py): ключ из фрагмента fill задавать не может
    if derived is not None:
        errs_d: list[str] = []
        for k, v in derived.items():
            if k in MERGE_DERIVED and isinstance(v, dict):
                fv = fill.get(k)
                if fv is not None and not isinstance(fv, dict):
                    errs_d.append(f"{k}: приходит из --derived (словарь), fill задаёт не словарь")
                    continue
                clash = sorted(set(v) & set(fv or {}))
                if clash:
                    errs_d.append(f"{k}.{', '.join(clash)}: приходит из --derived, fill его не задаёт")
                    continue
                merged = copy.deepcopy(v)
                merged.update(copy.deepcopy(fv or {}))
                fill.pop(k, None)
                put(k, merged, "derived+fill" if fv else "derived")
            else:
                if k in fill:
                    errs_d.append(f"{k}: приходит из --derived, fill его не задаёт")
                    continue
                put(k, v, "derived")
        if errs_d:
            raise AssembleError("fill трогает посчитанное:\n  " + "\n  ".join(errs_d))

    # _drop
    drop = fill.pop("_drop", None) or []
    if not isinstance(drop, list):
        raise AssembleError("fill._drop: ожидался список ключей")
    for k in drop:
        if k not in doc:
            raise AssembleError(f"fill._drop: ключа {k} нет в стабе")
        if not (has_ph(doc[k]) and src[k] == {"stub"}):
            raise AssembleError(f"fill._drop: {k} — не блок-скелет стаба, убрать нельзя")
        del doc[k]
        del src[k]

    # запреты fill
    errors: list[str] = []
    for k in RESERVED_TOP:
        if k in fill:
            errors.append(f"{k}: приходит из расчётного фрагмента, fill его не задаёт")
    for sid, block in (fill.get("scenarios") or {}).items() if isinstance(fill.get("scenarios"), dict) else []:
        if isinstance(block, dict) and RESERVED_SCENARIO_KEY in block:
            errors.append(f"scenarios.{sid}.{RESERVED_SCENARIO_KEY}: приходит из --aggregates")
    if errors:
        raise AssembleError("fill трогает посчитанное:\n  " + "\n  ".join(errors))

    # наложение: словари блокируются по состоянию ДО fill
    result = overlay(doc, fill, (), errors)
    if errors:
        raise AssembleError("fill трогает посчитанное:\n  " + "\n  ".join(errors))
    for k in fill:
        src.setdefault(k, set()).add("fill")

    left = find_ph(result)
    if left:
        shown = ", ".join(left[:15]) + (f" … (+{len(left) - 15})" if len(left) > 15 else "")
        raise AssembleError(f"после сборки остался {PLACEHOLDER}: {shown}")
    return result, {k: "+".join(sorted(v)) for k, v in src.items() if k in result}


def dump(tree: dict) -> str:
    yaml = _yaml()
    return yaml.safe_dump(tree, allow_unicode=True, sort_keys=False, default_flow_style=False)


def validate_tree(tree: dict, snapshot: dict | None) -> list[dict]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import validate_stress_output as vso  # noqa: E402
    return vso.validate(tree, snapshot)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description="Сборка итогового stress-YAML из стаба, расчётных фрагментов и fill")
    ap.add_argument("--stub", required=True, type=Path)
    ap.add_argument("--per-position", type=Path, default=None)
    ap.add_argument("--bond-carry", type=Path, default=None)
    ap.add_argument("--aggregates", type=Path, default=None)
    ap.add_argument("--horizon-factors", type=Path, default=None)
    ap.add_argument("--derived", type=Path, default=None,
                    help="фрагмент compute_derived_fields.py: cash_rub_pct, sector_breakdown_pct, top_risks, … "
                         "Передан — эти ключи fill задавать не может; нет — берутся из fill, как раньше")
    ap.add_argument("--fill", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--snapshot", type=Path, default=None,
                    help="portfolio-{date}.json — обязателен при проверке: по нему валидатор убеждается, что "
                         "у каждой бумаги портфеля есть чувствительность (3.13) и купонный слой сходится (3.14)")
    ap.add_argument("--no-validate", action="store_true")
    args = ap.parse_args()

    try:
        inputs = {"--stub": args.stub, "--per-position": args.per_position,
                  "--bond-carry": args.bond_carry, "--aggregates": args.aggregates,
                  "--horizon-factors": args.horizon_factors, "--derived": args.derived, "--fill": args.fill,
                  "--snapshot": args.snapshot}
        out_res = args.output.resolve()
        for name, p in inputs.items():
            if p is not None and p.resolve() == out_res:
                raise AssembleError(f"--output совпадает с {name} — отказ")
        if args.per_position is None:
            raise AssembleError("не передан обязательный фрагмент: --per-position")
        if args.aggregates is None:
            raise AssembleError("не передан обязательный фрагмент: --aggregates")

        stub = _need_dict(load_doc(args.stub, "--stub"), "--stub")
        pp = _need_dict(load_doc(args.per_position, "--per-position"), "--per-position")
        agg = _need_dict(load_doc(args.aggregates, "--aggregates"), "--aggregates")
        bc = _need_dict(load_doc(args.bond_carry, "--bond-carry"), "--bond-carry") if args.bond_carry else None
        hf = _need_dict(load_doc(args.horizon_factors, "--horizon-factors"), "--horizon-factors") if args.horizon_factors else None
        dv = _need_dict(load_doc(args.derived, "--derived"), "--derived") if args.derived else None
        fill = load_doc(args.fill, "--fill")
        if fill is None:
            fill = {}
        fill = _need_dict(fill, "--fill")

        tree, sources = assemble(stub, pp, agg, bc, hf, fill, dv)

        issues: list[dict] | None = None
        if not args.no_validate:
            if not args.snapshot:
                raise AssembleError("нужен --snapshot: без снапшота не проверить, что чувствительность задана "
                                    "всем бумагам портфеля (unmapped_tickers пуст, сумма весов 100) — файл не записан")
            snap = json.loads(args.snapshot.read_text(encoding="utf-8"))
            issues = validate_tree(tree, snap)
            if issues:
                lines = [f"  [{i['code']}] {i['field']}: ожидалось {i['expected']!r}, факт {i['actual']!r}"
                         for i in issues]
                raise AssembleError(f"валидатор: блокеров {len(issues)}, файл не записан:\n" + "\n".join(lines))
    except AssembleError as e:
        sys.stderr.write(f"ОТКАЗ: {e}\n")
        return 1

    text = dump(tree)
    atomic_write(args.output, text)
    sizes = {k: len(dump({k: v}).encode("utf-8")) for k, v in tree.items()}
    summary = {
        "output": str(args.output),
        "bytes": len(text.encode("utf-8")),
        "sources": sources,
        "block_bytes": sizes,
        "validation": "skipped" if args.no_validate else "ok",
    }
    sys.stdout.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
