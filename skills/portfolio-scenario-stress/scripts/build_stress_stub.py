#!/usr/bin/env python3
"""
build_stress_stub.py — детерминированный stub-генератор для stress-{date}-{slug}.yaml.

Читает SSOT scenario YAML (для name + p каждого сценария) и portfolio snapshot
(для portfolio_snapshot_id), выдаёт YAML-стаб с пре-заполненными:
- Top-level: schema_version: 2, type: portfolio-stress-test (НЕ portfolio-scenario-stress!),
  date в КАВЫЧКАХ, horizons/horizon_ends/primary_horizon (Phase 4 multiple horizons),
  portfolio_snapshot_id, scenario_source, weight_type, scenario_count,
  run_id, review_date, factor_definitions (канонический template),
  macro_input — имя файла `--macro-scenarios` (ссылка стресс → макросценарии, schema.md §4.6;
  без `--macro-scenarios` — `null`, вьюер покажет «ссылка не записана»)
- scenarios[A/B/C/D]: name (из scenario_triggers[*].label, НЕ "label"!),
  p (из probability, НЕ "probability"!). v2: `factors_by_horizon: {hNN: {factor: …}}`
  и `portfolio_level_by_horizon: {hNN: {delta_rub, expected_pct_pweighted}}` — пустые,
  заполняются (рекомендуется compute_horizon_factors.py + compute_per_position.py).
- TODO_LLM плейсхолдеры: factors, per_position, sector_breakdown_pct,
  top_risks, caveats, …
- Комментарий-подсказка (не поле схемы): plan_bucket_key по облигациям снапшота
  рядом с per_position — traceability при ручной сверке корзины плана (PSS-14).

LLM должна заменить TODO_LLM значения, НЕ переименовывать поля (`label`→`name`,
`probability`→`p`, плоский `pnl_rub` без `portfolio_level` — drift, заблокирует
save-to-library validator).

CLI:
  python3 build_stress_stub.py \\
    --snapshot /path/to/portfolio-{date}.json \\
    --scenarios /path/to/scenarios/{slug}-{date}.yaml \\
    --macro-scenarios /path/to/macro-chain/macro-scenarios-{date}.yaml \\
    --output /tmp/stress-stub.yaml \\
    [--slug shell-d1] [--horizons 12,20,36 | --anchor-dates 2027-06-30,2028-06-30]
"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
from datetime import date as date_t, timedelta
from pathlib import Path
from typing import Any

# Sibling-импорт для base_value_rub (контракт баз расчёта, 2026-09-18) — тот же
# приём sys.path, что уже используют compute_per_position.py/compute_bond_carry.py.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from input_contract import compute_base_value_rub  # noqa: E402

# Canonical factors (см. portfolio-scenario-stress/SKILL.md, input-adapters.md)
CANONICAL_FACTORS = ["sanctions", "geopol", "cbr_rate", "usdrub", "cnyrub", "brent", "xauusd"]

# ── Phase 4 (schema v2): multiple horizons ── (одна константа на producer, D4-9)
DEFAULT_HORIZONS = [6, 12, 24]
DEFAULT_PRIMARY_HORIZON = 12


def parse_horizons(spec: str | None) -> list[int]:
    if not spec:
        return list(DEFAULT_HORIZONS)
    out = sorted({int(tok) for tok in spec.split(",") if tok.strip()})
    if not out:
        raise ValueError("пустой список горизонтов")
    return out


def add_months_eom(d: date_t, months: int) -> date_t:
    """d + months месяцев, округлённое до КОНЦА месяца (детерминированно)."""
    idx = d.year * 12 + (d.month - 1) + months
    year, month = idx // 12, idx % 12 + 1
    return date_t(year, month, calendar.monthrange(year, month)[1])


def compute_horizon_ends(review_date: str, horizons: list[int]) -> dict[str, str]:
    base = date_t.fromisoformat(review_date[:10])
    return {f"h{h}": add_months_eom(base, h).isoformat() for h in horizons}


def parse_anchor_dates(spec: str | None) -> list[str] | None:
    if not spec:
        return None
    return [tok.strip() for tok in spec.split(",") if tok.strip()]


def anchor_dates_to_horizons(review_date: str, dates: list[str]) -> tuple[list[int], dict[str, str]]:
    """Якорный режим (§11.6): даты-цели → (horizons N, horizon_ends), N = месяцы до цели."""
    base = date_t.fromisoformat(review_date[:10])
    seen: dict[int, str] = {}
    for ds in dates:
        d = date_t.fromisoformat(ds[:10])
        n = (d.year - base.year) * 12 + (d.month - base.month)
        if n <= 0:
            raise ValueError(f"якорная дата {ds} не в будущем относительно {review_date} (N={n})")
        if n in seen and seen[n] != d.isoformat():
            raise ValueError(f"две якорные даты дают один горизонт h{n}")
        seen[n] = d.isoformat()
    horizons = sorted(seen)
    return horizons, {f"h{n}": seen[n] for n in horizons}


def y_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def y_num(value: Any, decimals: int | None = None) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if decimals is not None:
        return f"{value:.{decimals}f}"
    if isinstance(value, float):
        s = f"{value:.6f}".rstrip("0").rstrip(".")
        return s or "0"
    return str(value)


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError:
        sys.stderr.write("ERROR: PyYAML required. pip install pyyaml --break-system-packages\n")
        sys.exit(2)
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_snapshot(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    sv = str(data.get("schema_version", ""))
    if not sv.startswith("2."):
        sys.stderr.write(f"ERROR: snapshot v={sv!r}; expected 2.x\n")
        sys.exit(1)
    return data


def extract_scenarios_from_ssot(scenarios_yaml: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract {scenario_id: {name, p}} from scenarios-{slug}.yaml SSOT."""
    out: dict[str, dict[str, Any]] = {}
    triggers = (scenarios_yaml.get("scenario_triggers") or
                scenarios_yaml.get("matrix", {}).get("scenario_triggers") or [])
    for trig in triggers:
        sid = trig.get("scenario_id")
        if not sid:
            continue
        entry = {
            "name": trig.get("label") or trig.get("name") or sid,
            "p": trig.get("probability") or trig.get("p") or 0.0,
        }
        # Веса по горизонтам (PSS-9): убеждение зависит от срока. Скаляр `p`
        # остаётся рядом — он деградация для горизонтов вне блока и база
        # диагностики нормировки. Без этой проводки веса лежали бы в SSOT и не
        # влияли ни на что: стресс брал бы скаляр на ВСЕ горизонты, и на h6
        # считалось бы убеждение с h12.
        pbh = trig.get("p_by_horizon")
        if isinstance(pbh, dict) and pbh:
            entry["p_by_horizon"] = {
                str(k): v for k, v in pbh.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            }
        out[sid] = entry
    return out


def extract_factors_from_macro_scenarios(
    macro_yaml: dict[str, Any],
    scenario_id: str,
    horizon_key: str = "horizon_2027_12_31",
) -> dict[str, Any]:
    """Попытка вытащить абсолютные значения факторов для сценария.

    Возвращает {factor_name: value_or_None}. Конвертация в delta (% change)
    оставлена LLM, т.к. требует baseline.
    """
    scenarios = macro_yaml.get("scenarios") or {}
    sc = scenarios.get(scenario_id)
    if not isinstance(sc, dict):
        return {}
    horizon = sc.get(horizon_key) or {}
    if not isinstance(horizon, dict):
        return {}
    # Map macro-scenarios fields → canonical factor names
    return {
        "brent_usd_absolute": horizon.get("brent_usd"),
        "usdrub_absolute": horizon.get("usdrub"),
        "cnyrub_absolute": horizon.get("cnyrub"),
        "cbr_rate_absolute": horizon.get("cbr_rate_pct"),
        "xauusd_absolute": horizon.get("xauusd"),
        "sanctions_intensity": horizon.get("sanctions_intensity"),
        "conflict_intensity": horizon.get("conflict_intensity"),
        "inflation_ru_pct": horizon.get("inflation_ru_pct"),
    }


def build_stub(
    *,
    snapshot: dict[str, Any],
    scenarios_yaml: dict[str, Any],
    macro_yaml: dict[str, Any] | None,
    slug: str,
    horizons: list[int],
    primary_horizon: int,
    today_iso: str,
    horizon_ends: dict[str, str] | None = None,
    macro_input: str | None = None,
) -> str:
    """Сгенерировать полный YAML-стаб (schema v2). macro_input — имя файла макросценариев (без пути)."""
    as_of = snapshot.get("as_of_date") or today_iso
    snapshot_id = f"portfolio-{as_of}.json"
    # Run ID format: PSS-YYYYMMDD-{SLUG}
    run_id = f"PSS-{as_of.replace('-', '')}-{slug.upper().replace('-', '_')}"
    # Review date = date + 6 months
    try:
        date_obj = date_t.fromisoformat(as_of)
        review_dt = date_obj + timedelta(days=180)
        review_date = review_dt.isoformat()
    except ValueError:
        review_date = today_iso

    # v2: horizon_ends — дата-арифметика от as_of (или явные якорные даты); хардкод убран.
    h_ends = horizon_ends or compute_horizon_ends(as_of, horizons)
    if primary_horizon not in horizons:
        primary_horizon = horizons[0]
    horizon_keys = [f"h{h}" for h in horizons]

    # Scenarios SSOT
    scenarios = extract_scenarios_from_ssot(scenarios_yaml)
    if not scenarios:
        sys.stderr.write("WARN: scenario_triggers not found in --scenarios YAML\n")

    out: list[str] = []
    out.append(f"# stress-{as_of}-{slug}.yaml")
    out.append(f"# Generated by build_stress_stub.py from {snapshot_id}.")
    out.append(f"# Итоговый файл собирает assemble_stress.py: расчётные фрагменты вставляет скрипт,")
    out.append(f"# модель пишет только fill.yaml (поля суждения) и НЕ переименовывает поля")
    out.append(f"# (label→name, probability→p — drift). Validator save-to-library блокирует drift / TODO_LLM.")
    out.append("")
    out.append("schema_version: 2")
    out.append("type: portfolio-stress-test  # НЕ portfolio-scenario-stress (drift!)")
    out.append(f"date: {y_str(as_of)}")
    # v2 (Phase 4): multiple horizons. horizon / horizon_months удалены.
    out.append(f"horizons: [{', '.join(str(h) for h in horizons)}]")
    out.append("horizon_ends:")
    for hk in horizon_keys:
        out.append(f"  {hk}: {y_str(h_ends[hk])}")
    out.append(f"primary_horizon: {primary_horizon}")
    out.append(f"horizon_mode: {'anchored' if horizon_ends else 'rolling'}  # rolling=скользящий (default), anchored=якорный (--anchor-dates)")
    out.append(f"portfolio_snapshot_id: {y_str(snapshot_id)}")
    out.append("scenario_source: macro-forecast-chain  # или: scenario-builder / forecast-confidence-applier / manual / hybrid")
    out.append("weight_type: equal  # equal (0.25 × 4) или probability (если Σ p != 1.0 после weight)")
    out.append(f"scenario_count: {len(scenarios) if scenarios else 4}")
    out.append(f"run_id: {y_str(run_id)}")
    if macro_input:
        out.append(f"macro_input: {y_str(macro_input)}  # ссылка на макросценарии (§4.6); версии прогнозов не копируются")
    else:
        out.append("macro_input: null  # нет --macro-scenarios: ссылка не записана")
    out.append(f"review_date: {y_str(review_date)}  # date + 6 months — для retrospective audit")
    out.append('modal_flag: no_modal  # или: bull / base / bear если был calibrated_modal')
    out.append("")

    # === Контракт баз расчёта (basis contract, 2026-09-18, §11.2a yaml-schemas.md) ===
    # base_value_rub — знаменатель ВСЕХ pct-полей, посчитан здесь один раз
    # (compute_base_value_rub), а не заново в каждом скрипте/голове модели.
    base_value_rub = compute_base_value_rub(snapshot)
    out.append("# === Контракт баз расчёта (basis_contract) — §11.2a yaml-schemas.md ===")
    out.append("basis_contract: 1")
    out.append("layers_included: {price: true, bond_carry: true, dividends: false}  # dividends всегда false")
    out.append("per_position_basis: price  # инвариант — per_position никогда не несёт carry/total-return")
    out.append(f"base_value_rub: {round(base_value_rub)}  # Σ value_rub unblocked holdings + cash, посчитано детерминированно")
    out.append('base_value_note: "holdings unblocked + кэш; blocked исключены"')
    out.append("p_basis: primary_horizon  # что значит scenarios.<X>.p — primary_horizon | mean_across_horizons")
    out.append("")

    # === baseline_spot (§11.2) — ОБЯЗАТЕЛЕН ===
    # Потребители: L1-overlay integrated-view (MFC-4: уровень→движение против спота)
    # и compute_bond_carry.py (уровень КС для реинвеста/MM/distressed-порога).
    # Без него L1-overlay молча деградирует в L2 (боевой инцидент: stress-2026-07-02
    # ушёл без baseline_spot → мёртвый L1).
    out.append("# baseline_spot — споты на дату стресса (ЕДИНЫЙ на все горизонты, §11.2).")
    out.append("# ОБЯЗАТЕЛЕН: его читают L1-overlay integrated-view и compute_bond_carry.py.")
    baseline = (macro_yaml or {}).get("baseline_spot")
    _BASELINE_KEYS = ["brent_usd", "usdrub", "cnyrub", "cbr_rate_pct", "xauusd_usd"]
    out.append("baseline_spot:")
    if isinstance(baseline, dict) and baseline:
        for k, v in baseline.items():
            out.append(f"  {k}: {v}")
    else:
        for k in _BASELINE_KEYS:
            out.append(f"  {k}: TODO_LLM_float_spot")
        out.append("  # Источник: macro-chain/macro-scenarios-{date}.yaml → baseline_spot,")
        out.append("  # или macro-snapshots/ru-{date}.md. Не выдумывать — брать из источника.")
    out.append("")

    # === scenarios block (v2) ===
    out.append("# === scenarios block (v2) — name (НЕ label), p (НЕ probability) ===")
    out.append("# Имена / вероятности взяты из SSOT scenario_triggers[*].label / .probability.")
    out.append("# factors_by_horizon[hNN] — % DELTA от baseline на КАЖДЫЙ горизонт (§11.2).")
    out.append("# factors_by_horizon вставляет assemble_stress.py из compute_horizon_factors.py")
    out.append("# (--horizon-factors; per-year уровни FCA → движения; coverage-чек + CI-инфляция).")
    out.append("# portfolio_level_by_horizon[hNN]: {price_delta_rub/pct, carry_rub/pct,")
    out.append("# total_return_rub/pct} — обе базы явно, total_return = price_delta + carry")
    out.append("# (±1 ₽). Заполняется compute_portfolio_aggregates.py из per_position +")
    out.append("# bond_carry — вставляет assemble_stress.py (--aggregates), вручную не считать (RECONCILE 3.6/3.7).")
    out.append("scenarios:")
    scen_ids = sorted(scenarios.keys()) if scenarios else ["A", "B", "C", "D"]
    for sid in scen_ids:
        sc = scenarios.get(sid) if scenarios else None
        out.append(f"  {sid}:")
        if sc:
            out.append(f"    name: {y_str(sc['name'])}")
            out.append(f"    p: {y_num(sc['p'], 4)}")
            # PSS-9: горизонтные веса из SSOT. Выводятся ТОЛЬКО те горизонты,
            # что реально считаются в этом прогоне: блок, покрывающий не все
            # горизонты, движок останавливает (смешивать горизонтные веса со
            # скаляром нельзя), а лишний ключ вводил бы в заблуждение.
            pbh = sc.get("p_by_horizon") or {}
            covered = {hk: pbh[hk] for hk in horizon_keys if hk in pbh}
            if covered and len(covered) == len(horizon_keys):
                out.append(f"    p_by_horizon:  # веса по горизонтам из SSOT (PSS-9)")
                for hk in horizon_keys:
                    out.append(f"      {hk}: {y_num(covered[hk], 4)}")
            elif pbh:
                missing = [hk for hk in horizon_keys if hk not in pbh]
                out.append(f"    # ⚠️ p_by_horizon в SSOT есть, но не покрывает "
                           f"{', '.join(missing)} — веса по горизонтам НЕ перенесены,")
                out.append(f"    #    расчёт пойдёт по скаляру p. Задай блок на все "
                           f"горизонты прогона или убери его совсем.")
        else:
            out.append(f"    name: TODO_LLM_scenario_name")
            out.append(f"    p: TODO_LLM_float_0_to_1")
        # Hint with absolute values from macro-scenarios if available
        if sc and macro_yaml:
            abs_vals = extract_factors_from_macro_scenarios(macro_yaml, sid)
            if abs_vals:
                out.append(f"    # Absolute values @ {h_ends[f'h{primary_horizon}']} (из macro-scenarios; для подсчёта delta):")
                for k, v in abs_vals.items():
                    if v is not None:
                        out.append(f"    #   {k}: {v}")
        out.append(f"    factors_by_horizon:  # % delta от baseline на каждый горизонт")
        for hk in horizon_keys:
            out.append(f"      {hk}:")
            for f in CANONICAL_FACTORS:
                out.append(f"        {f}: TODO_LLM_float_pct_delta")
        out.append(f"    portfolio_level_by_horizon:  # заполняет compute_portfolio_aggregates.py")
        for hk in horizon_keys:
            out.append(f"      {hk}:")
            out.append(f"        price_delta_rub: TODO_LLM_int")
            out.append(f"        price_delta_pct: TODO_LLM_float")
            out.append(f"        carry_rub: TODO_LLM_int  # из bond_carry.portfolio_level_by_horizon, 0 если нет облигаций")
            out.append(f"        carry_pct: TODO_LLM_float")
            out.append(f"        total_return_rub: TODO_LLM_int  # == price_delta_rub + carry_rub, ±1 ₽")
            out.append(f"        total_return_pct: TODO_LLM_float")
        out.append("")

    # === factor_definitions ===
    out.append("# === factor_definitions — канонический template для viewer ===")
    out.append("factor_definitions:")
    # (unit, display_label, if_positive, if_negative) — unit машинный, display_label
    # человекочитаемый ярлык единицы для viewer (U3, Фаза 4.1 Блок D).
    factor_meta = {
        "sanctions": ("intensity_-1_to_1", "усл. шкала −1…+1", "санкционное давление растёт", "санкции ослабевают"),
        "geopol":    ("intensity_-1_to_1", "усл. шкала −1…+1", "геополитика обостряется",     "геополитика разряжается"),
        "cbr_rate":  ("pct_delta",         "п.п.",             "ЦБ ужесточает ДКП",            "ЦБ смягчает ДКП"),
        "usdrub":    ("pct_delta",         "%",                "USD/RUB растёт (рубль слабее)","USD/RUB падает (рубль крепче)"),
        "cnyrub":    ("pct_delta",         "%",                "CNY/RUB растёт",               "CNY/RUB падает"),
        "brent":     ("pct_delta",         "%",                "нефть растёт",                 "нефть падает"),
        "xauusd":    ("pct_delta",         "%",                "золото растёт",                "золото падает"),
    }
    for f, (unit, label, ifp, ifn) in factor_meta.items():
        out.append(f"  {f}:")
        out.append(f"    unit: {unit}")
        out.append(f"    display_label: {y_str(label)}")
        out.append(f"    if_positive: {y_str(ifp)}")
        out.append(f"    if_negative: {y_str(ifn)}")
    out.append("")

    # === per_position ===
    out.append("# === per_position — заполняется через compute_per_position.py ===")
    out.append("# Запуск:")
    out.append("# python3 skills/portfolio-scenario-stress/scripts/compute_per_position.py \\")
    out.append("#   --snapshot {snapshot.json} \\")
    out.append("#   --scenarios {scenarios-fragment.yaml — содержит p+factors} \\")
    out.append("#   --priors {betas-priors.json} \\")
    out.append("#   --output /tmp/per_position-fragment.yaml")
    out.append("# Фрагмент вставляет assemble_stress.py (--per-position), вручную не переносить.")
    out.append("per_position: TODO_LLM_dict_ticker_to_position_record_from_compute_per_position")
    out.append("")
    out.append("# unmapped_tickers — из output compute_per_position.py (даже если пуст — массив [])")
    out.append("unmapped_tickers: TODO_LLM_list_of_tickers_without_priors_or_empty_array")
    out.append("")

    # plan_bucket_key traceability (PSS-14): справочный комментарий, НЕ поле
    # схемы — необязателен, помогает сверить облигацию с корзиной плана
    # («ОФЗ/>10», «USD», …) при заполнении per_position вручную.
    bond_holdings = [h for h in snapshot.get("holdings", [])
                     if h.get("asset_type") == "bond" and h.get("ticker")]
    if bond_holdings:
        out.append("# plan_bucket_key по облигациям снапшота (traceability, справочно, PSS-14):")
        seen_tickers: set[str] = set()
        for h in bond_holdings:
            ticker = h["ticker"]
            if ticker in seen_tickers:
                continue
            seen_tickers.add(ticker)
            bucket_key = h.get("plan_bucket_key") or "null"
            out.append(f"#   {ticker} ({h.get('name') or '?'}): {bucket_key}")
        out.append("")

    # === Aggregate blocks (TODO_LLM) ===
    out.append("# === Aggregates / risks / caveats — LLM заполняет ===")
    out.append("sector_breakdown_pct: TODO_LLM_dict_sector_to_weight_and_metrics")
    out.append("")
    out.append("# portfolio_aggregates / robustness — заполняет compute_portfolio_aggregates.py")
    out.append("# из portfolio_level_by_horizon (обе базы, по всем горизонтам). Deprecated")
    out.append("# скаляры portfolio_pl_range_rub/expected_pl_rub — НЕ использовать (§11.2a).")
    out.append("portfolio_aggregates:")
    for basis in ("price", "total_return"):
        out.append(f"  {basis}:")
        out.append(f"    basis: {basis}")
        out.append(f"    expected_pl_rub_by_horizon: {{{', '.join(f'{hk}: TODO_LLM_int_or_null' for hk in horizon_keys)}}}")
        out.append(f"    expected_pl_pct_by_horizon: {{{', '.join(f'{hk}: TODO_LLM_float_or_null' for hk in horizon_keys)}}}")
        out.append(f"    pl_range_rub_by_horizon:")
        for hk in horizon_keys:
            out.append(f"      {hk}: {{min: TODO_LLM_int, max: TODO_LLM_int, min_scenario: TODO_LLM_id, max_scenario: TODO_LLM_id}}")
    out.append("")
    out.append("robustness:")
    for basis in ("price", "total_return"):
        out.append(f"  {basis}:")
        out.append(f"    basis: {basis}")
        out.append(f"    by_horizon:")
        for hk in horizon_keys:
            out.append(f"      {hk}: {{positive_or_neutral_scenarios: TODO_LLM_int, "
                       f"worst_case: {{id: TODO_LLM_id, pl_pct: TODO_LLM_float}}, "
                       f"best_case: {{id: TODO_LLM_id, pl_pct: TODO_LLM_float}}, "
                       f"spread_pct: TODO_LLM_float}}")
    out.append("  modal_scenario: none  # id или none — none обязателен при modal_flag: no_modal")
    out.append("  hedge_target: TODO_LLM_text")
    out.append("")
    out.append("concentration_ratio: TODO_LLM_float_0_to_1")
    out.append("dominant_factor: TODO_LLM_factor_name_from_canonical_7")
    out.append("")
    out.append("top_risks:")
    out.append("  - ticker: TODO_LLM_ticker")
    out.append("    scenario: TODO_LLM_scenario_id")
    out.append("    delta_pct: TODO_LLM_float")
    out.append("    weight_pct: TODO_LLM_float")
    out.append("")
    out.append("macro_blindspots:  # может быть пустым массивом [] если все позиции macro-sensitive")
    out.append("  - ticker: TODO_LLM_ticker_or_remove_block_if_empty")
    out.append("    reason: TODO_LLM_text_idiosyncratic_factor")
    out.append("")
    out.append("# caveats: МИНИМУМ 1 запись severity: HIGH")
    out.append("caveats:")
    out.append("  - severity: HIGH")
    out.append("    message: TODO_LLM_severity_assessment_of_methodology_limits")
    out.append("")
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--scenarios", required=True, type=Path,
                        help="scenarios-{slug}.yaml SSOT (для scenario_triggers[*].label/probability)")
    parser.add_argument("--macro-scenarios", type=Path, default=None,
                        help="macro-scenarios-{date}.yaml (optional, для абсолютных значений факторов)")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--slug", default="shell-d1",
                        help="Слаг для filename / run_id (e.g., shell-d1-20mo)")
    parser.add_argument("--horizons", default=None,
                        help="Скользящий режим: список горизонтов в месяцах (default: 6,12,24)")
    parser.add_argument("--anchor-dates", default=None,
                        help="Якорный режим (§11.6): даты-цели через запятую (YYYY-MM-DD)")
    parser.add_argument("--primary-horizon", type=int, default=DEFAULT_PRIMARY_HORIZON)
    parser.add_argument("--today", default=None)
    args = parser.parse_args()

    snapshot = load_snapshot(args.snapshot)
    scenarios_yaml = load_yaml(args.scenarios)
    macro_yaml = load_yaml(args.macro_scenarios) if args.macro_scenarios else None
    today_iso = args.today or date_t.today().isoformat()

    as_of = snapshot.get("as_of_date") or today_iso
    anchor = parse_anchor_dates(args.anchor_dates)
    if anchor:
        horizons, horizon_ends = anchor_dates_to_horizons(as_of, anchor)
    else:
        horizons, horizon_ends = parse_horizons(args.horizons), None

    stub = build_stub(
        snapshot=snapshot,
        scenarios_yaml=scenarios_yaml,
        macro_yaml=macro_yaml,
        slug=args.slug,
        horizons=horizons,
        primary_horizon=args.primary_horizon,
        today_iso=today_iso,
        horizon_ends=horizon_ends,
        macro_input=args.macro_scenarios.name if args.macro_scenarios else None,
    )
    args.output.write_text(stub, encoding="utf-8")

    sc = extract_scenarios_from_ssot(scenarios_yaml)
    summary = {
        "output": str(args.output),
        "scenarios_loaded": list(sc.keys()),
        "macro_scenarios_used": args.macro_scenarios is not None,
        "snapshot_date": snapshot.get("as_of_date"),
    }
    sys.stdout.write(json.dumps(summary, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
