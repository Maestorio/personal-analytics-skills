#!/usr/bin/env python3
"""
reweight_stress.py — перевзвешивание готового стресс-артефакта и чувствительность
к весу одного сценария (PSS-6).

ЧТО ЭТО ДЕЛАЕТ. Читает готовый stress-YAML и пересчитывает взвешенные по сценариям
величины под другие веса. Пересчёта бет, факторов и обращений к сети нет: в артефакте
уже лежит `per_position[t].by_horizon[h].delta_pct_by_scenario[s].value`, и
перевзвешивание есть переусреднение готовых чисел.

ЧЕГО ЭТО НЕ ДЕЛАЕТ. Инструмент только читает и печатает. Он НЕ пишет и НЕ изменяет
stress-YAML и ничего не сохраняет в Claude-Memory. Причина — решение D2: равные веса
Pure Shell не вероятности, и среднее по ним вводит в заблуждение, поэтому
`expected_pl_*` сознательно убраны из вывода стресса. Инструмент, дописывающий EV в
артефакт, вернул бы это через заднюю дверь. Разовый ответ на вопрос «а если веса
такие?» — отчёт, а не поле артефакта.

КАКУЮ ВЕЛИЧИНУ СЧИТАЕТ. Ценовую переоценку портфеля — Слой 1 (price). Она НЕ
сопоставима с Layer 1+2 портфеля (`portfolio_level_by_horizon[h].total_return_pct`
после basis_contract, либо legacy `expected_pct_pweighted` в архиве до него —
там купонный carry) и не с `portfolio_summary.pct_by_scenario_h12`. Дивидендов в
стрессе нет ни в старой, ни в новой схеме (Слой 3 — weekly-review). Смешение
слоёв — известный источник ошибок, поэтому имя слоя печатается в каждом выводе.

БАЗЫ. `weight_pct` считается от ПОЗИЦИОННОЙ базы (сумма незаблокированных holdings,
без кэша), а `cash_rub_pct` / `blocked_pct` / `base_value_rub`-производные проценты
артефакта (`price_delta_pct` после basis_contract, `l1_price_only_pct` в архиве до
него) — от ПОЛНОЙ базы (позиции + кэш). Складывать их нельзя: на живом файле 08-04
сумма даёт 102.6. Поэтому проценты этого инструмента — от позиционной базы, и это
печатается.

Зависимости: PyYAML. Сети нет.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover — среда без PyYAML
    sys.exit("ERROR: нужен PyYAML: pip install pyyaml --break-system-packages")


#: Допустимое отклонение Σ weight_pct от 100. Чистое округление 4 знаков по 68
#: позициям даёт ≤0.004 п.п., поэтому порог 0.05 щедр и при этом ловит реальные
#: пропуски. Прежнее значение 0.5 было бы слепо к живому случаю: артефакт
#: stress-2026-08-04 имеет Σ = 99.6701 (одна нога расщеплённой позиции не попала в
#: публикацию), и это стоит 16 753 ₽ расхождения с портфельным итогом.
WEIGHT_SUM_TOLERANCE_PP = 0.05

#: Ниже этого модуля |V_axis − M| считаем, что ожидание от веса оси не зависит.
SLOPE_EPS = 1e-12


# ─────────────────────────── чтение артефакта ───────────────────────────

def load_stress(path: Path) -> dict[str, Any]:
    """Читает stress-YAML. Принимает только schema_version == 2."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
    except FileNotFoundError:
        raise SystemExit(f"ERROR: файл не найден: {path}")
    except yaml.YAMLError as exc:
        raise SystemExit(f"ERROR: {path} не парсится как YAML: {exc}")
    if not isinstance(doc, dict):
        raise SystemExit(f"ERROR: {path} — не YAML-словарь")
    sv = doc.get("schema_version")
    if sv != 2:
        raise SystemExit(
            f"ERROR: schema_version={sv!r}, поддерживается только 2. "
            f"v1-артефакты лежат в Portfolio/stress/_archive-pre-v2/ и содержат "
            f"delta_pct_by_scenario на верхнем уровне вместо by_horizon."
        )
    for key in ("per_position", "scenarios"):
        if not isinstance(doc.get(key), dict) or not doc[key]:
            raise SystemExit(f"ERROR: в артефакте нет непустого блока {key}:")
    return doc


def weight_sum(stress: dict) -> float:
    """Σ weight_pct по позициям. Должна быть ≈100 (позиционная база)."""
    return sum(float(v.get("weight_pct") or 0) for v in stress["per_position"].values())


def horizon_keys(stress: dict) -> list[str]:
    """Ключи горизонтов в порядке появления в первой позиции."""
    first = next(iter(stress["per_position"].values()))
    return list((first.get("by_horizon") or {}).keys())


def default_horizon(stress: dict) -> str:
    """
    Горизонт по умолчанию — primary_horizon артефакта. В артефакте это ЧИСЛО (12),
    а ключи by_horizon — строки "h12": конвертация обязательна. В репозитории уже
    был дефект ровно этого рода (f"h{h}" на строке давала "hh6").
    """
    ph = stress.get("primary_horizon")
    if ph is None:
        keys = horizon_keys(stress)
        if not keys:
            raise SystemExit("ERROR: в артефакте нет by_horizon и нет primary_horizon")
        return keys[0]
    hk = ph if isinstance(ph, str) and ph.startswith("h") else f"h{ph}"
    if hk not in horizon_keys(stress):
        raise SystemExit(
            f"ERROR: primary_horizon={ph!r} → ключ {hk!r}, которого нет в by_horizon "
            f"({', '.join(horizon_keys(stress))})"
        )
    return hk


def _total_value_rub(stress: dict) -> float | None:
    """Полная база (позиции + кэш): `portfolio_summary.total_value_rub`, а в файлах без этого блока —
    верхнеуровневый `base_value_rub` (та же величина)."""
    total = (stress.get("portfolio_summary") or {}).get("total_value_rub")
    return total if total is not None else stress.get("base_value_rub")


def positions_value_rub(stress: dict) -> tuple[float, str]:
    """
    Позиционная база в рублях и пояснение, откуда она взята.

    Прямо в артефакте её нет: есть `portfolio_summary.total_value_rub` (ПОЛНАЯ база,
    позиции + кэш) и `cash_rub_pct` от той же полной базы. Вывод через них точен лишь
    до округления cash_rub_pct до сотых — отсюда «приближённо» в подписи. Проценты
    инструмента от этого не зависят: база нужна только для рублёвого вывода.
    """
    total = _total_value_rub(stress)
    cash_pct = stress.get("cash_rub_pct")
    if total is None or cash_pct is None:
        raise SystemExit(
            "ERROR: не вывести позиционную базу — нет base_value_rub (или portfolio_summary.total_value_rub) "
            "или cash_rub_pct. Передай --positions-value явно."
        )
    val = float(total) * (1.0 - float(cash_pct) / 100.0)
    note = (f"выведена из total_value_rub={float(total):,.0f} и cash_rub_pct={cash_pct} "
            f"(приближённо: cash_rub_pct округлён до сотых)")
    return val, note


# ─────────────────────────── ядро расчёта ───────────────────────────

def portfolio_by_scenario(stress: dict) -> dict[str, dict[str, float]]:
    """
    {hk: {sid: Δ% ценовой переоценки портфеля от ПОЗИЦИОННОЙ базы}}.

    Δ%(h,s) = Σ_t weight_pct[t]/100 × delta_pct_by_scenario[t][h][s].value

    Деление на 100 — именно на сто, а не нормировка на Σ weight_pct: веса уже
    выражены в процентах от базы, и нормировка молча пересчитала бы результат на
    другую базу, спрятав недостачу веса вместо того, чтобы её показать.
    Ячейки с price_delta_zeroed участвуют как есть (там value = 0.0).
    """
    out: dict[str, dict[str, float]] = {}
    for hk in horizon_keys(stress):
        cell: dict[str, float] = {}
        for sid in stress["scenarios"]:
            total = 0.0
            for tkr, pos in stress["per_position"].items():
                node = (pos.get("by_horizon") or {}).get(hk)
                if not node:
                    raise SystemExit(f"ERROR: у {tkr} нет горизонта {hk} в by_horizon")
                dbs = node.get("delta_pct_by_scenario") or {}
                if sid not in dbs:
                    raise SystemExit(f"ERROR: у {tkr}/{hk} нет сценария {sid}")
                total += float(pos.get("weight_pct") or 0) / 100.0 * float(dbs[sid]["value"])
            cell[sid] = total
        out[hk] = cell
    return out


def portfolio_rub_by_scenario(pbs: dict[str, dict[str, float]],
                              positions_value: float) -> dict[str, dict[str, float]]:
    """{hk: {sid: Δ₽}}. Нужно для сверки с l1_price_only_delta_rub артефакта."""
    return {hk: {sid: v / 100.0 * positions_value for sid, v in cells.items()}
            for hk, cells in pbs.items()}


def weighted_expectation(pbs: dict[str, dict[str, float]],
                         weights: dict[str, Any]) -> dict[str, float]:
    """
    {hk: Δ%} — свёртка по весам. weights либо {sid: p}, либо {hk: {sid: p}}.
    Валидации суммы здесь НЕТ: она в CLI, чтобы библиотечный вызов считал ровно то,
    что ему дали.
    """
    out: dict[str, float] = {}
    for hk, cells in pbs.items():
        w = weights.get(hk) if _is_by_horizon(weights) else weights
        out[hk] = sum(float(w.get(sid, 0.0)) * v for sid, v in cells.items())
    return out


def _is_by_horizon(weights: dict[str, Any]) -> bool:
    return bool(weights) and all(isinstance(v, dict) for v in weights.values())


def _rest_mix(cells: dict[str, float], axis_sid: str,
              baseline: dict[str, float]) -> float:
    """
    M — ожидание по «остальным» сценариям при их взаимных пропорциях baseline.
    M = Σ_{s≠axis} (b_s / Σ b_{s≠axis}) × V_s
    """
    rest = {s: float(baseline.get(s, 0.0)) for s in cells if s != axis_sid}
    denom = sum(rest.values())
    if denom <= 0:
        raise SystemExit(
            f"ERROR: сумма baseline-весов по сценариям кроме {axis_sid} равна {denom}. "
            f"Взаимные пропорции остальных неопределены — задай baseline явно."
        )
    return sum(b / denom * cells[s] for s, b in rest.items())


def sensitivity(pbs: dict[str, dict[str, float]], axis_sid: str, horizon: str,
                baseline: dict[str, float], *, steps: int = 11) -> dict[str, Any]:
    """
    Таблица чувствительности ожидания к весу ОДНОГО сценария.

    Модель: вес axis_sid едет 0→1, остальные сохраняют ВЗАИМНЫЕ пропорции baseline и
    делят остаток (1 − w). Единственная запись, не требующая от пользователя назвать
    ещё три числа.

    E(w) = w·V_axis + (1 − w)·M — строго ЛИНЕЙНА по w, потому что V_s (портфель
    внутри сценария) от весов не зависит вовсе. Поэтому slope аналитический, а не
    снятый с таблицы, и порог имеет замкнутую форму (см. solve_for).
    """
    if steps < 2:
        raise SystemExit(f"ERROR: --steps={steps}, нужно ≥2 (шаг сетки w=i/(steps−1))")
    cells = pbs.get(horizon)
    if cells is None:
        raise SystemExit(f"ERROR: горизонта {horizon} нет в артефакте "
                         f"({', '.join(pbs)})")
    if axis_sid not in cells:
        raise SystemExit(f"ERROR: сценария {axis_sid} нет в артефакте "
                         f"({', '.join(sorted(cells))})")
    v_axis = cells[axis_sid]
    m = _rest_mix(cells, axis_sid, baseline)
    table = []
    for i in range(steps):
        w = i / (steps - 1)
        table.append({"w": w, "value": w * v_axis + (1 - w) * m})
    return {
        "axis": axis_sid, "horizon": horizon,
        "baseline_w": float(baseline.get(axis_sid, 0.0)),
        "table": table, "slope": v_axis - m, "M": m, "V_axis": v_axis,
    }


def solve_for(pbs: dict[str, dict[str, float]], axis_sid: str, horizon: str,
              baseline: dict[str, float], target: float) -> float | None:
    """
    Вес axis_sid, при котором ожидание равно target. Замкнутая форма, НЕ бисекция:
    w* = (target − M) / (V_axis − M).
    None — если E не зависит от w или решение вне [0, 1].
    """
    s = sensitivity(pbs, axis_sid, horizon, baseline, steps=2)
    denom = s["V_axis"] - s["M"]
    if abs(denom) < SLOPE_EPS:
        return None
    w = (target - s["M"]) / denom
    return w if 0.0 <= w <= 1.0 else None


def baseline_weights(stress: dict, horizon: str) -> tuple[dict[str, float], str]:
    """
    Веса из артефакта: p_by_horizon[horizon] при наличии, иначе скаляр p.
    Возвращает (веса, источник) — источник печатается, чтобы читатель знал, от чего
    отсчитывается кривая.
    """
    by_h: dict[str, float] = {}
    for sid, sc in stress["scenarios"].items():
        blk = sc.get("p_by_horizon")
        if isinstance(blk, dict) and horizon in blk:
            by_h[sid] = float(blk[horizon])
    if len(by_h) == len(stress["scenarios"]):
        return by_h, f"scenarios[*].p_by_horizon[{horizon}]"
    if by_h:
        missing = sorted(set(stress["scenarios"]) - set(by_h))
        raise SystemExit(
            f"ERROR: p_by_horizon[{horizon}] задан не у всех сценариев "
            f"(нет у {', '.join(missing)}). Частично заданные убеждения смешивать со "
            f"скаляром нельзя."
        )
    out = {}
    for sid, sc in stress["scenarios"].items():
        p = sc.get("p", sc.get("probability"))
        if p is None:
            raise SystemExit(f"ERROR: у сценария {sid} нет ни p, ни probability")
        out[sid] = float(p)
    return out, "scenarios[*].p (скаляр)"


# ─────────────────────────── CLI ───────────────────────────

def _load_weights_arg(raw: str) -> dict[str, Any]:
    p = Path(raw)
    text = p.read_text(encoding="utf-8") if p.exists() else raw
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: --weights не разобрать как JSON: {exc}")
    if not isinstance(obj, dict) or not obj:
        raise SystemExit("ERROR: --weights должен быть непустым JSON-объектом")
    return obj


def _validate_weights(weights: dict[str, Any], stress: dict) -> None:
    """Сумма и наборы ключей. Молча нормировать нельзя: просили конкретные веса."""
    sids = set(stress["scenarios"])
    hks = set(horizon_keys(stress))
    per_h = weights if _is_by_horizon(weights) else {"*": weights}
    if _is_by_horizon(weights):
        extra, missing = set(weights) - hks, hks - set(weights)
        if extra or missing:
            raise SystemExit(
                f"ERROR: набор горизонтов в --weights не совпадает с артефактом. "
                f"Лишние: {sorted(extra) or '—'}. Недостающие: {sorted(missing) or '—'}."
            )
    for hk, w in per_h.items():
        extra, missing = set(w) - sids, sids - set(w)
        if extra or missing:
            where = "" if hk == "*" else f" на горизонте {hk}"
            raise SystemExit(
                f"ERROR: набор сценариев в --weights{where} не совпадает с артефактом. "
                f"Лишние: {sorted(extra) or '—'}. Недостающие: {sorted(missing) or '—'}."
            )
        total = sum(float(x) for x in w.values())
        if abs(total - 1.0) > 1e-6:
            where = "" if hk == "*" else f" на горизонте {hk}"
            raise SystemExit(
                f"ERROR: сумма весов{where} = {total:.6f}, ожидается 1.0 ± 1e-6. "
                f"Нормировать за тебя не буду — веса заданы осознанно."
            )


def _header(stress: dict, path: Path, pos_val: float, pos_note: str) -> list[str]:
    """Шапка вывода. Печатается ВСЕГДА: без неё ценовое число подставляют вместо
    total-return — это уже случалось."""
    wsum = weight_sum(stress)
    total = _total_value_rub(stress)
    lines = [
        f"Артефакт:  {path.name}  (schema 2, дата {stress.get('date')})",
        "Величина:  ЦЕНОВАЯ ПЕРЕОЦЕНКА ПОРТФЕЛЯ (Слой 1), % от позиционной базы.",
        "           НЕ сопоставима с expected_pct_pweighted артефакта — там",
        "           total-return с купонным carry и дивидендами.",
        f"Базы:      позиционная {pos_val:,.0f} ₽ ({pos_note})",
        f"           полная {float(total):,.0f} ₽ (позиции + кэш)" if total else "",
        f"Σ weight_pct: {wsum:.4f}%",
    ]
    if abs(wsum - 100.0) > WEIGHT_SUM_TOLERANCE_PP:
        lines.append(
            f"⚠️  Σ weight_pct отклоняется от 100 на {abs(wsum - 100.0):.4f} п.п. — "
            f"это ≈{abs(wsum - 100.0) / 100 * pos_val:,.0f} ₽ непокрытой стоимости. "
            f"Чистое округление даёт ≤0.01 п.п.; большее означает, что часть позиции "
            f"не попала в per_position (например, нога, разложенная по счетам)."
        )
    return [l for l in lines if l]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Перевзвешивание стресс-артефакта и чувствительность к весу "
                    "одного сценария. Только читает и печатает.")
    ap.add_argument("--stress", required=True, type=Path, help="готовый stress-YAML")
    ap.add_argument("--weights", default=None,
                    help='JSON или путь: {"A":0.4,...} либо {"h6":{...},...}')
    ap.add_argument("--sensitivity", default=None, metavar="SID",
                    help="таблица чувствительности к весу сценария SID")
    ap.add_argument("--target", type=float, default=None,
                    help="решить E(w) = target (только с --sensitivity)")
    ap.add_argument("--horizon", default=None, metavar="hNN",
                    help="горизонт; default — primary_horizon артефакта")
    ap.add_argument("--steps", type=int, default=11, help="точек в таблице (≥2)")
    ap.add_argument("--positions-value", type=float, default=None,
                    help="позиционная база в ₽; default — вывести из артефакта")
    args = ap.parse_args()

    if args.target is not None and not args.sensitivity:
        raise SystemExit("ERROR: --target работает только вместе с --sensitivity")
    if not args.weights and not args.sensitivity:
        raise SystemExit("ERROR: нечего делать — задай --weights или --sensitivity")

    stress = load_stress(args.stress)
    if args.positions_value is not None:
        pos_val, pos_note = args.positions_value, "задана флагом --positions-value"
    else:
        pos_val, pos_note = positions_value_rub(stress)

    pbs = portfolio_by_scenario(stress)
    hk = args.horizon or default_horizon(stress)
    if hk not in pbs:
        raise SystemExit(f"ERROR: горизонта {hk} нет в артефакте ({', '.join(pbs)})")

    out = _header(stress, args.stress, pos_val, pos_note)
    out.append("")

    if args.weights:
        weights = _load_weights_arg(args.weights)
        _validate_weights(weights, stress)
        exp = weighted_expectation(pbs, weights)
        rub = portfolio_rub_by_scenario(pbs, pos_val)
        out.append("── Ожидание под заданными весами ──")
        for k in pbs:
            per_s = "  ".join(f"{s}={pbs[k][s]:+7.2f}%" for s in sorted(pbs[k]))
            out.append(f"  {k:4s}  {exp[k]:+7.2f}%  ({exp[k] / 100 * pos_val:+12,.0f} ₽)"
                       f"   по сценариям: {per_s}")
        out.append("")
        out.append("  Сценарные Δ₽ (для сверки: price_delta_rub после basis_contract,")
        out.append("  l1_price_only_delta_rub в архиве до него):")
        for k in pbs:
            out.append("    " + k.ljust(4) + "  " +
                       "  ".join(f"{s}={rub[k][s]:+12,.0f}" for s in sorted(rub[k])))
        out.append("")

    if args.sensitivity:
        base, src = baseline_weights(stress, hk)
        if abs(sum(base.values()) - 1.0) > 1e-6:
            out.append(f"⚠️  Σ baseline = {sum(base.values()):.6f} ≠ 1: кривая в точке "
                       f"baseline_w не совпадёт со свёрткой по этим же весам.")
        s = sensitivity(pbs, args.sensitivity, hk, base, steps=args.steps)
        out.append(f"── Чувствительность к весу сценария {s['axis']} на {hk} ──")
        out.append(f"  baseline_w = {s['baseline_w']:.4f}   источник: {src}")
        out.append(f"  V_axis = {s['V_axis']:+.2f}%   M (остальные) = {s['M']:+.2f}%"
                   f"   наклон = {s['slope']:+.2f} п.п. на единицу веса")
        out.append("  Модель: вес оси едет 0→1, остальные делят остаток в пропорциях"
                   " baseline. E(w) линейна.")
        out.append("")
        for row in s["table"]:
            bar = "" if abs(row["w"] - s["baseline_w"]) > 1e-9 else "   ← baseline"
            out.append(f"    w={row['w']:.2f}   E={row['value']:+7.2f}%"
                       f"   ({row['value'] / 100 * pos_val:+12,.0f} ₽){bar}")
        if args.target is not None:
            w = solve_for(pbs, args.sensitivity, hk, base, args.target)
            out.append("")
            if w is None:
                out.append(f"  E(w) = {args.target:+.2f}% недостижимо на w ∈ [0,1] "
                           f"(диапазон {min(s['M'], s['V_axis']):+.2f}…"
                           f"{max(s['M'], s['V_axis']):+.2f}%).")
            else:
                out.append(f"  E(w) = {args.target:+.2f}%  при  w({s['axis']}) = "
                           f"{w:.4f}  ({w * 100:.2f}%)")

    print("\n".join(out))
    return 0


def _cli() -> int:
    """
    Обёртка над main(): переводит отказы в код возврата 2.

    Библиотечные функции поднимают SystemExit со СТРОКОЙ — так сообщение доступно
    вызывающему коду и тестам через исключение. Но `sys.exit("текст")` даёт код 1,
    неотличимый от падения интерпретатора, поэтому на границе CLI строка печатается
    в stderr, а наружу уходит 2 — «вход не принят», отдельно от 1 «сломалось».
    """
    try:
        return main()
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, str):
            print(code, file=sys.stderr)
            return 2
        return 0 if code is None else int(code)


if __name__ == "__main__":
    sys.exit(_cli())
