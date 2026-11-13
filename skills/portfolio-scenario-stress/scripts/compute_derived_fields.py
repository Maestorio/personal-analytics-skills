#!/usr/bin/env python3
"""
compute_derived_fields.py — числа стресс-файла, которые раньше писала модель в «полях суждения».

Всё берётся из снапшота, уже посчитанных блоков (per_position, aggregates) и таблицы
references/sector-groups.yaml; ничего нового не придумывается. Что неоднозначно или требует
метки, которой нет в данных, — НЕ считается и попадает в `skipped` с причиной; поле остаётся
суждением модели.

БАЗЫ. Портфельные доли (cash_rub_pct, blocked_pct, концентрация) — от портфеля с кэшем:
base_value_rub = Σ value_rub неблокированных holdings + cash.total_rub
(input_contract.compute_base_value_rub). Веса бумаг и секторов (weight_pct) — от неблокированных
holdings без кэша (input_contract.compute_positions_value_rub), как per_position[*].weight_pct.

ЧТО СЧИТАЕТСЯ (ключ -> определение)

  cash_rub_pct     cash.total_rub / base_value_rub * 100, 2 знака.
  blocked_pct      Σ value_rub заблокированных holdings / base_value_rub * 100, 2 знака.
  blocked_rub_memo Шаблонная строка о числе заблокированных позиций и их оценке в 0 ₽; строится
                   только если Σ value_rub заблокированных == 0 и они есть; иначе пропуск.
  weight_base_note Шаблонная строка с числами: holdings без кэша, кэш и его доля от портфеля,
                   base_value_rub, Σ секторов (если sector_breakdown_pct посчитан).
  sector_breakdown_pct (+ sector_breakdown_basis: price)
      weight_pct = Σ value / holdings без кэша * 100 (2 зн.), value_rub = Σ value (целое),
      price_delta_rub_by_horizon[hNN][сценарий] = Σ value_rub * delta_pct / 100 по позициям
      сектора (целое; формула compute_portfolio_aggregates._price_delta_rub с точной value_rub
      вместо округлённого weight_pct). Сектор бумаги — по порядку:
        1. priors[t].sector_group (суждение);
        2. фонд — таблица `funds` из sector-groups.yaml;
        3. акция — holdings.sector снапшота;
        4. облигация — bonds_rub при nominal_currency ∈ {RUB, RUR, SUR}, иначе bonds_fx.
      Подпись — всегда из `groups` sector-groups.yaml. Бумага без сектора (фонд вне таблицы,
      акция без sector, облигация без nominal_currency) или с ключом вне `groups` — блоки по
      секторам не считаются, причина с тикерами в `skipped`.
  top_risks / top_resilient
      По каждому горизонту — сценарий с min (max) price_delta_rub портфеля
      (portfolio_aggregates.price.pl_range_rub_by_horizon), пять позиций с наибольшим убытком
      (прибылью) в ₽: {horizon, scenario, ticker, sector, weight_pct, delta_pct,
      price_delta_rub}. Считаются вместе с sector_breakdown_pct (та же карта секторов).
  concentration_ratio, concentration.{same_direction_pct, opposite_pct, neutral_pct,
  same_direction_incl_cnyrub_pct}
      Доля портфеля с кэшем, движущаяся в одном направлении с доминирующим фактором.
      Фактор — суждение: judgments_extra.concentration_factor (stress_recalc берёт его из
      narrative.concentration.dominant_factor); нет фактора или он не из CANONICAL_FACTORS —
      не считается. same = Σ value позиций с beta > 0 по фактору, opposite = с beta < 0,
      neutral = 100 - same - opposite, incl_cnyrub = beta > 0 по фактору ИЛИ по cnyrub;
      знаменатель — base_value_rub. concentration_ratio = same / 100, 4 знака.

НЕ СЧИТАЕТСЯ (остаётся суждением): dominant_factor, concentration.dominant_factor,
concentration.note, dominant_factor_note, hedge_*.

CLI:
  python3 compute_derived_fields.py --snapshot SNAP.json --per-position FRAG.yaml
      --aggregates FRAG.yaml [--judgments-extra EXTRA.yaml] [--sector-groups TABLE.yaml]
      [--output OUT.yaml]
  Фрагменты — те же файлы, что получает assemble_stress.py. Выход: YAML-фрагмент
  (вход assemble_stress.py --derived); причины пропусков — на stderr.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from input_contract import (  # noqa: E402
    CANONICAL_FACTORS,
    compute_base_value_rub,
    compute_positions_value_rub,
)

SECTOR_GROUPS_PATH = SCRIPTS.parent / "references" / "sector-groups.yaml"
TOP_N = 5
# Коды рубля в nominal_currency снапшота: RUB (с 2026-10) и SUR (код MOEX в старых снапшотах).
RUB_CODES = ("RUB", "RUR", "SUR")


def _pv(cell: Any) -> float | None:
    if isinstance(cell, dict):
        return cell.get("value")
    return cell


def _fmt_rub(x: float) -> str:
    return f"{round(x):,}".replace(",", " ")


def _legs(snapshot: dict) -> tuple[dict[str, dict], list[dict]]:
    """(тикер -> {value, sector, sector_ru, asset_type, nominal_currency}, заблокированные)."""
    out: dict[str, dict] = {}
    blocked: list[dict] = []
    for h in snapshot.get("holdings") or []:
        if not isinstance(h, dict):
            continue
        if h.get("is_blocked", False):
            blocked.append(h)
            continue
        t = h.get("ticker")
        if not t:
            continue
        e = out.setdefault(t, {"value": 0.0, "sector": h.get("sector"), "sector_ru": h.get("sector_ru"),
                               "asset_type": (h.get("asset_type") or "").lower(),
                               "nominal_currency": h.get("nominal_currency")})
        e["value"] += float(h.get("value_rub") or 0)
        if e["sector"] is None and h.get("sector") is not None:
            e["sector"], e["sector_ru"] = h.get("sector"), h.get("sector_ru")
    return out, blocked


class SectorTableError(ValueError):
    """Таблица секторных групп нечитаема или противоречива."""


def load_sector_groups(path: Path | None = None) -> dict:
    """Читает и проверяет sector-groups.yaml -> {"groups": {ключ: подпись}, "funds": {тикер: группа}}."""
    import yaml
    path = Path(path) if path else SECTOR_GROUPS_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise SectorTableError(f"таблица секторов нечитаема ({path}): {e}")
    except yaml.YAMLError as e:
        raise SectorTableError(f"таблица секторов — битый YAML ({path}): {e}")
    if not isinstance(raw, dict):
        raise SectorTableError(f"таблица секторов ({path}): ожидался словарь groups/funds")
    groups, funds = raw.get("groups"), raw.get("funds")
    if not isinstance(groups, dict) or not groups:
        raise SectorTableError(f"таблица секторов ({path}): нужен непустой groups")
    for k, v in groups.items():
        if not isinstance(k, str) or not isinstance(v, str) or not v.strip():
            raise SectorTableError(f"таблица секторов ({path}): groups.{k}: нужна непустая строковая подпись")
    if not isinstance(funds, dict):
        raise SectorTableError(f"таблица секторов ({path}): нужен словарь funds")
    for t, g in funds.items():
        if g not in groups:
            raise SectorTableError(f"таблица секторов ({path}): funds.{t} -> {g!r}, такой группы нет в groups")
    return {"groups": dict(groups), "funds": {str(t).upper(): g for t, g in funds.items()}}


def sector_of(ticker: str, leg: dict, prior: dict | None, table: dict) -> str | None:
    """Ключ сектора по порядку: sector_group суждения, таблица фондов, sector акции, валюта номинала
    облигации; None — сектор не определился."""
    sg = (prior or {}).get("sector_group")
    if sg:
        return str(sg)
    at = leg["asset_type"]
    if at == "fund":
        return table["funds"].get(ticker.upper())
    if at == "stock":
        return str(leg["sector"]) if leg.get("sector") else None
    if at == "bond":
        nc = leg.get("nominal_currency")
        if not nc:
            return None
        return "bonds_rub" if str(nc).upper() in RUB_CODES else "bonds_fx"
    return None


def _position_rub(per_position: dict, t: str, hk: str, sid: str, value: float) -> float | None:
    """ΔRUB позиции = value_rub (снапшот, ноги сложены) * delta_pct / 100. Это то же, что
    weight_pct/100 * positions_value * delta_pct/100, только без округления weight_pct до
    4 знаков (так считала модель в живых файлах; расхождение с формулой агрегатора — рубли)."""
    p = per_position.get(t) or {}
    d = _pv((((p.get("by_horizon") or {}).get(hk) or {}).get("delta_pct_by_scenario") or {}).get(sid))
    if d is None:
        return None
    return value * (d / 100.0)


def sector_map(snapshot: dict, per_position: dict, priors: dict | None, table: dict
               ) -> tuple[dict[str, tuple[str, str]], list[str], list[str]]:
    """({тикер: (ключ, подпись)}, [тикеры без сектора], [тикеры с ключом вне groups])."""
    legs, _ = _legs(snapshot)
    priors = priors or {}
    smap: dict[str, tuple[str, str]] = {}
    missing: list[str] = []
    unknown: list[str] = []
    for t in per_position:
        leg = legs.get(t)
        if leg is None:
            continue  # бумаги нет в снапшоте — вне разбивки
        key = sector_of(t, leg, priors.get(t) or (per_position.get(t) or {}), table)
        if key is None:
            missing.append(t)
        elif key not in table["groups"]:
            unknown.append(f"{t}={key}")
        else:
            smap[t] = (key, table["groups"][key])
    return smap, missing, unknown


def sector_breakdown(snapshot: dict, per_position: dict, smap: dict[str, tuple[str, str]],
                     scenarios: list[str], horizons: list[str]) -> dict:
    legs, _ = _legs(snapshot)
    pv = compute_positions_value_rub(snapshot)
    groups: dict[str, dict] = {}
    for t, (key, label) in smap.items():
        g = groups.setdefault(key, {"label_ru": label, "value": 0.0,
                                    "d": {hk: {s: 0.0 for s in scenarios} for hk in horizons}})
        g["value"] += legs[t]["value"]
        for hk in horizons:
            for s in scenarios:
                r = _position_rub(per_position, t, hk, s, legs[t]["value"])
                if r is not None:
                    g["d"][hk][s] += r
    out = {}
    for key, g in sorted(groups.items(), key=lambda kv: -kv[1]["value"]):
        out[key] = {
            "label_ru": g["label_ru"],
            "value_rub": round(g["value"]),
            "price_delta_rub_by_horizon": {hk: {s: round(v) for s, v in g["d"][hk].items()}
                                           for hk in horizons},
            "weight_pct": round(g["value"] / pv * 100.0, 2) if pv else 0.0,
        }
    return out


def top_lists(snapshot: dict, per_position: dict, smap: dict, aggregates: dict,
              horizons: list[str]) -> tuple[list[dict], list[dict]]:
    legs, _ = _legs(snapshot)
    rng = ((aggregates.get("portfolio_aggregates") or {}).get("price") or {}).get("pl_range_rub_by_horizon") or {}
    risks: list[dict] = []
    resil: list[dict] = []
    for hk in horizons:
        r = rng.get(hk) or {}
        for sid, bucket, neg in ((r.get("min_scenario"), risks, True), (r.get("max_scenario"), resil, False)):
            if not sid:
                continue
            rows = []
            for t in per_position:
                if t not in smap:
                    continue
                rub = _position_rub(per_position, t, hk, sid, legs[t]["value"])
                if rub is None:
                    continue
                if (neg and rub < 0) or (not neg and rub > 0):
                    rows.append((rub, t))
            rows.sort(key=lambda x: (x[0] if neg else -x[0]))
            for rub, t in rows[:TOP_N]:
                p = per_position[t]
                d = _pv(p["by_horizon"][hk]["delta_pct_by_scenario"][sid])
                bucket.append({"horizon": hk, "scenario": sid, "ticker": t, "sector": smap[t][0],
                               "weight_pct": p.get("weight_pct"), "delta_pct": d,
                               "price_delta_rub": round(rub)})
    return risks, resil


def concentration(snapshot: dict, per_position: dict, factor: str) -> dict:
    legs, _ = _legs(snapshot)
    denom = compute_base_value_rub(snapshot)
    if not denom:
        raise ValueError("нулевой знаменатель")
    same = opp = incl = 0.0
    for t, p in per_position.items():
        leg = legs.get(t)
        if leg is None:
            continue
        betas = (p or {}).get("factor_betas") or {}
        b = betas.get(factor) or 0
        if b > 0:
            same += leg["value"]
        elif b < 0:
            opp += leg["value"]
        if b > 0 or (betas.get("cnyrub") or 0) > 0:
            incl += leg["value"]
    s, o = same / denom * 100.0, opp / denom * 100.0
    return {"concentration_ratio": round(same / denom, 4),
            "concentration": {"same_direction_pct": round(s, 2), "opposite_pct": round(o, 2),
                              "neutral_pct": round(100.0 - s - o, 2),
                              "same_direction_incl_cnyrub_pct": round(incl / denom * 100.0, 2)}}


def compute_with_report(snapshot: dict, per_position: dict, bond_carry: dict | None,
                        aggregates: dict, scenarios: dict | None,
                        judgments_extra: dict | None = None,
                        sector_table: dict | None = None) -> tuple[dict, dict]:
    """(поля, {ключ: причина пропуска}). bond_carry и scenarios принимаются для единого
    интерфейса с остальными compute_*; формулы выше их не требуют. judgments_extra:
    priors{t:{sector_group}}, concentration_factor. sector_table — результат load_sector_groups
    (по умолчанию читается references/sector-groups.yaml; битая таблица — SectorTableError)."""
    extra = judgments_extra or {}
    table = sector_table if sector_table is not None else load_sector_groups()
    out: dict[str, Any] = {}
    skipped: dict[str, str] = {}
    legs, blocked = _legs(snapshot)
    pv = compute_positions_value_rub(snapshot)
    cash = float((snapshot.get("cash") or {}).get("total_rub") or 0)
    base = compute_base_value_rub(snapshot)

    if base > 0:
        out["cash_rub_pct"] = round(cash / base * 100.0, 2)
        bsum = sum(float(h.get("value_rub") or 0) for h in blocked)
        out["blocked_pct"] = round(bsum / base * 100.0, 2)
    else:
        skipped["cash_rub_pct"] = skipped["blocked_pct"] = "нет неблокированных holdings"
        bsum = 0.0
    if blocked and bsum == 0 and "cash_rub_pct" in out:
        n = len(blocked)
        noun = ("заблокированная позиция оценена" if n % 10 == 1 and n % 100 != 11 else
                "заблокированные позиции оценены" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else
                "заблокированных позиций оценены")
        out["blocked_rub_memo"] = f"{n} {noun} в 0 ₽ (--blocked-value zero) — вне базы расчёта"
    else:
        skipped["blocked_rub_memo"] = ("нет заблокированных позиций" if not blocked else
                                       "заблокированные позиции оценены ненулевой суммой — формулировки нет")

    sids = sorted((aggregates.get("scenarios") or {}).keys())
    horizons = sorted({hk for p in per_position.values() if isinstance(p, dict)
                       for hk in (p.get("by_horizon") or {})}, key=lambda h: int(h[1:]))
    priors = extra.get("priors") or {}
    smap, missing, unknown = sector_map(snapshot, per_position, priors, table)
    sb_sum = None
    if missing or unknown:
        parts = []
        if missing:
            parts.append(f"сектор не определён у {len(missing)} бумаг ({', '.join(missing[:8])}"
                         f"{'…' if len(missing) > 8 else ''}): добавить фонд в funds или задать priors[t].sector_group")
        if unknown:
            parts.append(f"ключ сектора вне groups у {len(unknown)} бумаг ({', '.join(unknown[:8])}"
                         f"{'…' if len(unknown) > 8 else ''}): добавить группу в sector-groups.yaml")
        why = "; ".join(parts)
        for k in ("sector_breakdown_pct", "top_risks", "top_resilient"):
            skipped[k] = why
    elif not sids or not horizons:
        for k in ("sector_breakdown_pct", "top_risks", "top_resilient"):
            skipped[k] = "нет сценариев/горизонтов в per_position или aggregates"
    else:
        sb = sector_breakdown(snapshot, per_position, smap, sids, horizons)
        out["sector_breakdown_pct"] = sb
        out["sector_breakdown_basis"] = "price"
        sb_sum = round(sum(v["weight_pct"] for v in sb.values()), 2)
        out["top_risks"], out["top_resilient"] = top_lists(snapshot, per_position, smap, aggregates, horizons)

    if pv > 0 and base > 0:
        note = (f"per_position[*].weight_pct и sector_breakdown_pct нормированы на unblocked holdings "
                f"{_fmt_rub(pv)} ₽ (без кэша); кэш {_fmt_rub(cash)} ₽ ({out['cash_rub_pct']}% от портфеля с кэшем) "
                f"показан отдельно; base_value_rub = {_fmt_rub(base)} ₽ (holdings + кэш) — база "
                f"cash_rub_pct, blocked_pct, концентрации, portfolio_level/portfolio_aggregates.")
        if sb_sum is not None:
            note += f" Σ секторов = {sb_sum}%."
        out["weight_base_note"] = note

    f = extra.get("concentration_factor")
    if f in CANONICAL_FACTORS and base > 0:
        out.update(concentration(snapshot, per_position, f))
    else:
        why = ("нет dominant_factor в concentration суждений — фактор концентрации не задан" if not f else
               f"фактор концентрации {f!r} не из канонических факторов")
        skipped["concentration_ratio"] = skipped["concentration"] = why
    return out, skipped


def compute(snapshot: dict, per_position: dict, bond_carry: dict | None, aggregates: dict,
            scenarios: dict | None, judgments_extra: dict | None = None,
            sector_table: dict | None = None) -> dict:
    return compute_with_report(snapshot, per_position, bond_carry, aggregates, scenarios,
                               judgments_extra, sector_table)[0]


def main() -> int:
    import yaml
    ap = argparse.ArgumentParser(description="Производные числа стресс-файла из снапшота и расчётных блоков")
    ap.add_argument("--snapshot", required=True, type=Path)
    ap.add_argument("--per-position", required=True, type=Path)
    ap.add_argument("--aggregates", required=True, type=Path)
    ap.add_argument("--judgments-extra", type=Path, default=None,
                    help="YAML: concentration_factor, priors{t:{sector_group,...}}")
    ap.add_argument("--sector-groups", type=Path, default=None,
                    help="таблица секторных групп (по умолчанию references/sector-groups.yaml)")
    ap.add_argument("--output", type=Path, default=None)
    args = ap.parse_args()
    try:
        snap = json.loads(args.snapshot.read_text(encoding="utf-8"))
        pp = yaml.safe_load(args.per_position.read_text(encoding="utf-8"))
        agg = yaml.safe_load(args.aggregates.read_text(encoding="utf-8"))
        extra = yaml.safe_load(args.judgments_extra.read_text(encoding="utf-8")) if args.judgments_extra else None
    except (OSError, ValueError, yaml.YAMLError) as e:
        sys.stderr.write(f"ОШИБКА: вход нечитаем: {e}\n")
        return 2
    pp = (pp or {}).get("per_position") or pp
    try:
        table = load_sector_groups(args.sector_groups)
    except SectorTableError as e:
        sys.stderr.write(f"ОШИБКА: {e}\n")
        return 2
    out, skipped = compute_with_report(snap, pp, None, agg, None, extra, table)
    text = yaml.safe_dump(out, allow_unicode=True, sort_keys=False, default_flow_style=False)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    for k, v in skipped.items():
        sys.stderr.write(f"пропущено {k}: {v}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
