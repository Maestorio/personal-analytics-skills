#!/usr/bin/env python3
"""
compute_horizon_factors.py — детерминированный деривер factors_by_horizon для stress v2.

Phase 4 (D4-3). Превращает per-scenario per-factor **уровни года FCA** (механика
MFC-4) в **движения фактора по горизонтам** (% от baseline_spot / п.п. по контракту
единиц _shared-references/events-yaml-spec.md §5.6). Никакой ручной арифметики у LLM.

Логика по фактору:
  • значение-dict с явным путём {h6: -0.3, h12: -0.6, h24: -0.9} → берётся как есть
        (P0-2: политические дилы; недостающий горизонт → ближайший заданный + warning);
  • значение-dict с level_l1_<год> + unit (brent)  → выбирается год, ближайший к концу
        горизонта; уровень→движение против baseline_spot (unit: intensity → уровень
        берётся как есть: интенсивность уже задана относительно сегодняшнего состояния);
  • значение-число (sanctions: 0.3)               → горизонт-инвариантно, копируется во все
        hNN; для sanctions/geopol на мультигоризонтном прогоне + warning (P0-2: «разрядка
        через полгода = разрядка через два года» — почти всегда неверно);
  • строка / нет level / нет unit                  → пропускается (качественный фактор) + note.

Coverage-чек (инвариант «покрытие макро-прогноза ≥ горизонта анализа»): если для
горизонта нужного года FCA нет — берётся ближайший доступный, CI инфлируется
×√(h_target / h_source), горизонт помечается `extrapolated` + warning. Сводка — в
блоке `horizon_coverage` (худший статус и max ci_inflation на горизонт).

Выбор целевого года: если дан `horizon_ends[hNN]` (якорный режим §11.6) — год его
даты; иначе год даты `as_of + h месяцев` (скользящий).

Вход (JSON, stdin или --input):
  {
    "as_of": "2026-06-15",
    "horizons": [12, 20, 36],
    "horizon_ends": {"h12": "2027-06-30", ...},   # опц.; приоритет над as_of+h
    "baseline_spot": {"brent_usd": 94.11, "usdrub": 88.0, "cbr_rate_pct": 14.5, ...},
    "scenarios": {
      "A": {"factors": {
         "brent":    {"level_l1_2026": 68, "level_l1_2027": 72, "unit": "usd_per_bbl"},
         "cbr_rate": {"level_l1_2027": 9.5, "unit": "rate_pct"},
         "sanctions": {"h6": 0.3, "h12": 0.5, "h24": 0.7},
         "geopol":    0.3
      }}, ...
    }
  }

Выход (JSON):
  {
    "factors_by_horizon": {"A": {"h12": {"brent": -27.7, ...}, "h20": {...}, ...}, ...},
    "horizon_coverage": {"h12": {"status": "covered", "ci_inflation": 1.0, "warnings": []}, ...},
    "warnings": [...]
  }

Сетка дат макро-цепочки (macro-scenarios-<дата>.yaml): `grid_move`, `validate_macro`,
`factors_from_macro` — линейная интерполяция УРОВНЯ по датам между точками сетки, flat hold
после последней точки (CI × sqrt(дней до конца срока / дней до последней точки)), интерполяция
от спота до первой точки, если срок раньше сетки. CLI: `--check-macro FILE [--scenarios A,B]`.

stdlib only (yaml — только в режиме --check-macro, как и у остальных скриптов скилла).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import date
from typing import Any

# Общий модуль проверки макро-файла: сначала каталог скрипта (пакет .skill), затем _shared-references/ репозитория.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import macro_grid_check as _mgc  # noqa: E402

MACRO_FACTORS = _mgc.MACRO_FACTORS
PCT_MISMATCH_PP = _mgc.PCT_MISMATCH_PP
_is_number = _mgc._is_number
_iso = _mgc._iso
_move = _mgc._move
_factor_grids = _mgc._factor_grids
_numeric_entries = _mgc._numeric_entries
validate_macro = _mgc.validate_macro

# ── Контракт единиц (SSOT: _shared-references/events-yaml-spec.md §5.6) ──
# Копия из aggregate_positions.py — НЕ импортируем через границу скиллов (D4-3).
UNIT_SPOT_KEYS: dict[str, tuple[str, str]] = {
    "usd_per_bbl":     ("brent_usd",    "pct_from_spot"),
    "rub_per_usd":     ("usdrub",       "pct_from_spot"),
    "rub_per_cny":     ("cnyrub",       "pct_from_spot"),
    "usd_per_troy_oz": ("xauusd_usd",   "pct_from_spot"),
    "rate_pct":        ("cbr_rate_pct", "pp_diff"),
}

MAX_CI_INFLATION = 3.0
_LEVEL_PREFIX = "level_l1_"

# ── P0-2: политические факторы и их единица ──
# sanctions/geopol измеряются в интенсивности [-1..+1] ОТНОСИТЕЛЬНО сегодняшнего
# состояния, поэтому уровень уже является движением — baseline_spot им не нужен.
POLITICAL_FACTORS = ("sanctions", "geopol")
# Канон единицы — `intensity` (SSOT: events-yaml-spec.md §5.6). Алиас
# `intensity_-1_to_1` принимается намеренно: ровно эта строка стоит в
# `factor_definitions[f].unit` (display-метаданные для вьюера), и автор, скопировав
# её в блок level_l1_<год>, должен получить правильный расчёт, а не тихий пропуск
# фактора. По тому же критерию принята «ед. intensity-delta» — она стоит в
# factor_definitions живых stress-артефактов. Спекулятивных значений здесь
# быть не должно: непокрытый алиас не ловится тестами и создаёт ложную полноту.
INTENSITY_UNITS = {"intensity", "intensity_-1_to_1", "ед. intensity-delta"}
_H_KEY_RE = re.compile(r"^h(\d+)$")


def _add_months(d: date, months: int) -> date:
    """d + months месяцев (день не важен — нужен только год/месяц)."""
    idx = d.year * 12 + (d.month - 1) + months
    return date(idx // 12, idx % 12 + 1, 1)


def _level_to_move(level: float, unit: str, baseline_spot: dict) -> float | None:
    """Уровень → движение фактора по контракту §5.6 (pct_from_spot / pp_diff)."""
    if unit in INTENSITY_UNITS:
        # Интенсивность задана относительно текущего состояния → уже движение.
        return float(level)
    entry = UNIT_SPOT_KEYS.get(unit)
    if entry is None:
        return None
    spot_key, conv = entry
    spot = baseline_spot.get(spot_key)
    if not _is_number(spot) or float(spot) == 0:
        return None
    if conv == "pct_from_spot":
        return (level - float(spot)) / float(spot) * 100.0
    return level - float(spot)  # pp_diff


def _available_levels(fcast: dict) -> dict[int, float]:
    """{год: уровень} из ключей level_l1_<год> (только числовые)."""
    out: dict[int, float] = {}
    for k, v in fcast.items():
        if k.startswith(_LEVEL_PREFIX) and _is_number(v):
            try:
                out[int(k[len(_LEVEL_PREFIX):])] = float(v)
            except ValueError:
                continue
    return out


def _explicit_horizon_path(fval: dict) -> dict[int, float]:
    """{месяцы: значение} из явных ключей hNN (P0-2). Не-числовые значения игнорируются."""
    out: dict[int, float] = {}
    for k, v in fval.items():
        m = _H_KEY_RE.match(str(k))
        if m and _is_number(v):
            out[int(m.group(1))] = float(v)
    return out


def _path_value(path: dict[int, float], h: int) -> tuple[float, str | None]:
    """
    Значение явного пути на горизонте h. Возвращает (значение, пометка_или_None).

    Точка задана → берётся как есть. Горизонт ВНУТРИ пути → линейная интерполяция
    между соседними точками: брать «ближайшую» точку, когда путь горизонт
    охватывает, значит выбрасывать вторую известную точку (при пути {h6, h24}
    запрошенный h12 получил бы значение h6 целиком). Горизонт ВНЕ пути → плоская
    экстраполяция от крайней точки.
    """
    if h in path:
        return path[h], None
    lo = [x for x in path if x < h]
    hi = [x for x in path if x > h]
    if lo and hi:
        a, b = max(lo), min(hi)
        w = (h - a) / (b - a)
        return path[a] + (path[b] - path[a]) * w, f"интерполяция h{a}→h{b}"
    near = min(path, key=lambda x: (abs(x - h), x))
    return path[near], f"плоская экстраполяция от h{near}"


def _pick_nearest_year(levels: dict[int, float], target_year: int) -> int:
    """Год из levels, ближайший к target_year (тай-брейк — меньший |Δ|, затем меньший год)."""
    return min(levels, key=lambda y: (abs(y - target_year), y))


def _ci_inflation(h_target_months: int, source_year: int, target_year: int) -> float:
    """×√(h_target / h_source). source==target → 1.0. Клампится в [1.0, MAX]."""
    if source_year == target_year:
        return 1.0
    h_source = h_target_months + (source_year - target_year) * 12
    h_source = max(h_source, 1)
    infl = math.sqrt(h_target_months / h_source)
    return round(min(max(infl, 1.0), MAX_CI_INFLATION), 4)


def _target_year(as_of: date, h_months: int, horizon_end: str | None) -> int:
    """Год конца горизонта: из horizon_end (якорный) или as_of + h (скользящий)."""
    if horizon_end:
        try:
            return date.fromisoformat(horizon_end[:10]).year
        except ValueError:
            pass
    return _add_months(as_of, h_months).year


def compute_factors_by_horizon(
    scenarios: dict[str, Any],
    baseline_spot: dict[str, Any],
    horizons: list[int],
    as_of: date,
    horizon_ends: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """
    Возвращает (factors_by_horizon, horizon_coverage, warnings).
      factors_by_horizon: {scenario_id: {hNN: {factor: move}}}
      horizon_coverage:   {hNN: {status, ci_inflation, target_year, source_years, warnings}}
    """
    horizon_ends = horizon_ends or {}
    factors_by_horizon: dict[str, Any] = {}
    # Накопитель coverage по горизонтам (агрегируем по всем сценариям/факторам).
    cov: dict[str, dict[str, Any]] = {
        f"h{h}": {
            "status": "covered",
            "ci_inflation": 1.0,
            "target_year": _target_year(as_of, h, horizon_ends.get(f"h{h}")),
            "source_years": {},
            "warnings": [],
        }
        for h in horizons
    }
    warnings: list[str] = []

    for sid, sc in scenarios.items():
        factors = (sc or {}).get("factors") or {}
        by_h: dict[str, dict[str, float]] = {f"h{h}": {} for h in horizons}

        for fname, fval in factors.items():
            # (1) Число → горизонт-инвариантный фактор.
            if _is_number(fval):
                for h in horizons:
                    by_h[f"h{h}"][fname] = round(float(fval), 4)
                if fname in POLITICAL_FACTORS and len(horizons) > 1 and float(fval) != 0.0:
                    warnings.append(
                        f"{sid}.{fname}: скаляр {float(fval):g} скопирован на все "
                        f"горизонты (h{horizons[0]}…h{horizons[-1]}) — интенсивность не "
                        f"растёт со временем. Задай путь {{h{horizons[0]}: …, "
                        f"h{horizons[-1]}: …}} или level_l1_<год> + unit: intensity (P0-2)."
                    )
                continue
            # (2) dict с явным путём по горизонтам (P0-2) → приоритет над уровнями года.
            path = _explicit_horizon_path(fval) if isinstance(fval, dict) else {}
            if path:
                # Смешанная форма неоднозначна: какой источник главнее для горизонта,
                # который путь не покрывает, — вопрос без правильного ответа, а любой
                # выбор молча даёт неверный политический фактор. Отказываемся считать.
                mixed = _available_levels(fval) if isinstance(fval, dict) else {}
                if mixed:
                    raise SystemExit(
                        f"ERROR: {sid}.{fname} задан ОДНОВРЕМЕННО явным путём "
                        f"({sorted(path)}) и уровнями года ({sorted(mixed)}). Формы "
                        f"взаимоисключающие — оставь одну."
                    )
                for h in horizons:
                    hk = f"h{h}"
                    value, how = _path_value(path, h)
                    by_h[hk][fname] = round(value, 4)
                    if how:
                        warnings.append(
                            f"{sid}.{fname} {hk}: горизонт не задан в пути "
                            f"({sorted(path)}) — {how}"
                        )
                continue
            # (3) dict с уровнями года → дерlive per horizon.
            if isinstance(fval, dict):
                levels = _available_levels(fval)
                unit = fval.get("unit")
                if not levels or not isinstance(unit, str):
                    warnings.append(
                        f"{sid}.{fname}: нет level_l1_<год>+unit — пропущен (качественный?)"
                    )
                    continue
                for h in horizons:
                    hk = f"h{h}"
                    ty = cov[hk]["target_year"]
                    src_year = _pick_nearest_year(levels, ty)
                    move = _level_to_move(levels[src_year], unit, baseline_spot)
                    if move is None:
                        warnings.append(
                            f"{sid}.{fname} {hk}: unit={unit!r} нет в baseline_spot — пропущен"
                        )
                        continue
                    by_h[hk][fname] = round(move, 4)
                    if src_year != ty:
                        infl = _ci_inflation(h, src_year, ty)
                        cov[hk]["status"] = "extrapolated"
                        cov[hk]["ci_inflation"] = max(cov[hk]["ci_inflation"], infl)
                        cov[hk]["source_years"][fname] = src_year
                        w = (f"{fname}: год {ty} недоступен, взят {src_year} "
                             f"(×{infl} CI)")
                        if w not in cov[hk]["warnings"]:
                            cov[hk]["warnings"].append(w)
                continue
            # (4) Иначе (строка/None) → качественный, пропуск.
            warnings.append(f"{sid}.{fname}: значение не число и не dict — пропущен")

        factors_by_horizon[sid] = by_h

    return factors_by_horizon, cov, warnings


# ── Сетка дат макро-цепочки ──
# Проверка файла и разбор сетки — общий модуль _shared-references/macro_grid_check.py (его же зовёт
# save-to-library при сохранении файла); здесь только расчёт движения по сетке.
def grid_move(levels: dict[str, float], spot: float, kind: str, as_of: str, horizon_end: str,
              name: str = "") -> tuple[float, bool, float, str | None]:
    """
    Движение фактора на конец срока по сетке уровней {дата ISO: уровень}.
    Возвращает (движение, extrapolated, ci_inflation, предупреждение|None); движение округлено до 4 знаков.
    """
    pts = sorted((date.fromisoformat(k), float(v)) for k, v in levels.items())
    a, e = date.fromisoformat(as_of[:10]), date.fromisoformat(horizon_end[:10])
    first, last = pts[0], pts[-1]
    pre = f"{name}: " if name else ""
    warn = None
    infl = 1.0
    extrap = False
    for d, v in pts:
        if d == e:
            return round(_move(v, spot, kind), 4), False, 1.0, None
    if e < first[0]:
        span = (first[0] - a).days
        w = min(max((e - a).days / span, 0.0), 1.0) if span > 0 else 1.0
        level = spot + (first[1] - spot) * w
        warn = (f"{pre}горизонт {e.isoformat()} раньше первой точки сетки {first[0].isoformat()} "
                f"— интерполяция от спота")
    elif e > last[0]:
        level = last[1]
        extrap = True
        base = (last[0] - a).days
        infl = round(min(max(math.sqrt((e - a).days / base), 1.0), MAX_CI_INFLATION), 4) if base > 0 \
            else MAX_CI_INFLATION
        warn = (f"{pre}сетка прогноза заканчивается {last[0].isoformat()}, горизонт {e.isoformat()} "
                f"— flat hold (×{infl} CI)")
    else:
        level = last[1]
        for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
            if d0 < e < d1:
                level = v0 + (v1 - v0) * (e - d0).days / (d1 - d0).days
                break
    return round(_move(level, spot, kind), 4), extrap, infl, warn


def factors_from_macro(macro: dict, scenario_ids: list[str], as_of: str, horizon_ends: dict[str, str]
                       ) -> tuple[dict, dict, list[str]]:
    """
    Числовые факторы всех сценариев по сетке дат макро-файла.
    Возвращает (factors_by_horizon {sid: {hNN: {фактор: движение}}}, horizon_coverage, warnings).
    Предварительно проверяет файл: ошибки → ValueError с перечнем строк.
    """
    errs, warns = validate_macro(macro, scenario_ids)
    if errs:
        raise ValueError("макро-файл не годится для расчёта:\n  " + "\n  ".join(errs))
    hks = sorted(horizon_ends, key=lambda k: int(k[1:]))
    fbh: dict = {sid: {hk: {} for hk in hks} for sid in scenario_ids}
    cov: dict = {hk: {"status": "covered", "ci_inflation": 1.0, "warnings": [],
                      "target_date": str(horizon_ends[hk])[:10]} for hk in hks}
    for mname, (canon, kind) in MACRO_FACTORS.items():
        fnode = macro["factors"][mname]
        spot = float(macro["baseline_spot"][mname])
        for sid in scenario_ids:
            levels, _raw, _bad = _numeric_entries(_factor_grids(fnode, sid))
            for hk in hks:
                move, extrap, infl, w = grid_move(levels, spot, kind, as_of, horizon_ends[hk], canon)
                fbh[sid][hk][canon] = move
                c = cov[hk]
                if extrap:
                    c["status"] = "extrapolated"
                c["ci_inflation"] = max(c["ci_inflation"], infl)
                if w and w not in c["warnings"]:
                    c["warnings"].append(w)
    return fbh, cov, warns


def run(payload: dict) -> dict:
    as_of_raw = payload.get("as_of")
    if not as_of_raw:
        raise SystemExit("ERROR: поле 'as_of' обязательно (детерминизм без Date.now())")
    try:
        as_of = date.fromisoformat(str(as_of_raw)[:10])
    except ValueError:
        raise SystemExit(f"ERROR: as_of={as_of_raw!r} не ISO YYYY-MM-DD")
    horizons = payload.get("horizons") or [6, 12, 24]
    horizons = sorted({int(h) for h in horizons})
    baseline_spot = payload.get("baseline_spot") or {}
    scenarios = payload.get("scenarios") or {}
    horizon_ends = payload.get("horizon_ends") or {}

    fbh, cov, warnings = compute_factors_by_horizon(
        scenarios, baseline_spot, horizons, as_of, horizon_ends
    )
    return {
        "factors_by_horizon": fbh,
        "horizon_coverage": cov,
        "warnings": warnings,
        "as_of": as_of.isoformat(),
        "horizons": horizons,
    }


def _cli() -> None:
    ap = argparse.ArgumentParser(description="Derive stress factors_by_horizon from FCA year-levels")
    ap.add_argument("--input", help="JSON payload file (default: stdin)")
    ap.add_argument("--output", help="Output JSON file (default: stdout)")
    ap.add_argument("--pretty", action="store_true")
    ap.add_argument("--check-macro", help="проверить файл макро-цепочки (macro-scenarios-<дата>.yaml) и выйти")
    ap.add_argument("--scenarios", help="id сценариев матрицы через запятую (для --check-macro)")
    args = ap.parse_args()

    if args.check_macro:
        import yaml
        with open(args.check_macro, "r", encoding="utf-8") as f:
            macro = yaml.safe_load(f)
        ids = [x.strip() for x in args.scenarios.split(",") if x.strip()] if args.scenarios else None
        errs, warns = validate_macro(macro, ids)
        for w in warns:
            sys.stdout.write(f"ПРЕДУПРЕЖДЕНИЕ: {w}\n")
        if errs:
            sys.stdout.write("ОТКАЗ:\n  " + "\n  ".join(errs) + "\n")
            sys.exit(1)
        sys.stdout.write("ок\n")
        sys.exit(0)

    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            payload = json.load(f)
    else:
        payload = json.load(sys.stdin)

    result = run(payload)
    kw = {"ensure_ascii": False}
    if args.pretty:
        kw["indent"] = 2
    text = json.dumps(result, **kw)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text + "\n")


if __name__ == "__main__":
    _cli()
