#!/usr/bin/env python3
"""
aggregate_positions.py

Детерминированные расчёты для portfolio-integrated-view (Шаги 1.5, 2, 3, 3.5, 4):
- Нормировка вероятностей сценариев (p_i_norm = p_i / Σ p_j)
- Stale-pipeline gate (R-PIPE): доля unresolved macro_dependency > 0.3 → FAIL
- Snapshot drift check (R-SNAP): сравнение snapshot_id stress vs review
- Per-position aggregate: macro + (div ИЛИ bond carry) + idio с CI propagation
- Joint expectation: p_joint = p_scenario × p_catalyst (с macro_dep) или p_catalyst × 0.7 (без)
- Trust matrix discount, source_quality LOW → p_joint *= 0.5
- Bond carry (R-BOND-CARRY): ytm_pct из bond-review → fallback xirr → fallback 0;
  горизонт capped до оферты/погашения, при неправдоподобном ytm (>60%) базис → coupon_pct,
  backstop-клампа |carry| ≤ 50 (защита от yield-to-offer put-облигаций)
- Portfolio aggregates: equity/bond expected return + spread с двойным CI (linear / quadratic)
- Tail-risk флаги (@1.2): детерминированный пост-процессинг поверх CI — три
  ортогональных флага (БИНАРНЫЙ скос / ЗНАК НЕ РАЗРЕШЁН / ХВОСТ ПОРТФЕЛЯ) с
  anti-fatigue (materiality floor + cap top-3). НЕ VaR — эвристика внимания.

LLM делает: чтение YAML/JSON через transport, упаковку payload, прозу §1/§9/§10, caveats.
Все числа — этот скрипт.

CLI:
    cat input.json | python3 aggregate_positions.py --pretty
    python3 aggregate_positions.py --input run.json --output result.json

Без внешних зависимостей. Совместимо со stdlib Python ≥3.8.
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
import os
import random
import re
import sys
from datetime import date, datetime
from typing import Any

# Кодлисты (`codelists.json`, загрузчик `codelists.py`) — канон в _shared-references/; в упакованном .skill — в своей
# scripts/ (pack.sh кладёт оба файла по импорту). Как у assemble_artifact: сначала каталог скрипта.
_CL_HERE = os.path.dirname(os.path.abspath(__file__))
for _cl_cand in (_CL_HERE, os.path.normpath(os.path.join(_CL_HERE, "..", "..", "..", "_shared-references"))):
    if _cl_cand not in sys.path:
        sys.path.insert(0, _cl_cand)
import codelists  # noqa: E402

# Единый словарь вердиктов (schema.md §3.4): обзор несёт только коды кодлиста verdict; прежний код — ошибка, не перевод.
_VERDICT_LEGACY_HINT = {"HOLD_ADD": "ADD", "RED_FLAG": "WATCH", "MATURE": "HOLD_TO_MAT", "HOLD_NO_OFFER": "HOLD_TO_MAT"}


def _check_verdict(verdict, ticker):
    """Вердикт обзора должен быть в кодлисте verdict (или NOT_REVIEWED); иначе понятная ошибка."""
    if verdict == "NOT_REVIEWED" or verdict in codelists.codes("verdict"):
        return verdict
    hint = (f" Прежний код заменён на {_VERDICT_LEGACY_HINT[verdict]}: перезапустите "
            f"tools/data-structures/migrations/migrate_bond_verdicts.py или пересоздайте обзор."
            if verdict in _VERDICT_LEGACY_HINT else "")
    raise ValueError(f"{ticker}: вердикт обзора {verdict!r} не из единого словаря "
                     f"({', '.join(codelists.codes('verdict'))}).{hint}")


STALE_PIPELINE_THRESHOLD = 0.3
SNAPSHOT_DRIFT_THRESHOLD_DAYS = 3
SCENARIO_P_LOW_THRESHOLD = 0.02
SCENARIO_P_MEDIUM_THRESHOLD = 0.05
DEFAULT_HORIZONS = [6, 12, 24]       # набор горизонтов по умолчанию (Phase 4)
DEFAULT_PRIMARY_HORIZON = 12         # primary по умолчанию (= «1 год»)
NULL_DEPENDENCY_DISCOUNT = 0.7
LOW_QUALITY_DISCOUNT = 0.5

# ── Bond carry sanity (Баг #1: put/offer-облигации) ──
# Для бумаг с близкой офертой MOEX отдаёт YIELD как доходность-к-ближайшему-событию
# (yield-to-offer), которая на коротком горизонте раздувается до сотен % годовых.
# Умножать её на горизонт нельзя — экономика оферты уже сидит в катализаторе offer_exit.
CARRY_YTM_SANITY_PCT = 60.0   # ytm выше → трактуем как yield-to-event, берём coupon_pct
CARRY_CAP_PCT = 50.0          # жёсткий backstop на итоговый carry (|value| ≤ cap)

# ── Total-return (2026-07): три слоя ──
# Слой 1 (цена) — stress per_position (maturity guard обнуляет гасящиеся бонды);
# Слой 2 (carry) — блок stress.bond_carry (compute_bond_carry.py) — ПРИОРИТЕТ
#   над legacy ytm×t (R-BOND-CARRY остаётся fallback для старых stress);
# Слой 3 (дивиденды) — per_stock.dividend_forward — приоритет над div_yield_12m_pct.
DIV_CONF_CI_REL = {"HIGH": 0.10, "MEDIUM": 0.25, "LOW": 0.50}  # CI-полуширина по confidence
# Дивидендный haircut в сценариях с sanctions ≥ порога (решение C, симметрично
# санкционному haircut carry-слоя). Применяется ТОЛЬКО в total_return_by_horizon
# (сценарная декомпозиция); базовый div-слой позиции остаётся сценарно-независимым.
DEFAULT_DIV_SANCTIONS_HAIRCUT = 0.25
SANCTIONS_INTENSITY_MIN = 1.0

# ── Macro Layer 1 (Баг #2: macro-marginal → L1) ──
# Имена факторов в macro-marginal.yaml (geopolitics/…) не всегда совпадают с ключами
# factor_betas в stress (geopol/…). Alias-карта сопоставляет их при расчёте L1.
#
# ⚠ Прогон 2026-08-15 (docs/investment/portfolio/piv-run-2026-08-15-review.md §3.1):
# из 5 числовых факторов macro-marginal с бетой совпадал ровно один (cbr_rate) —
# остальные приходят с суффиксом (`brent_price` против беты `brent`). L1 молча
# вырождался в L2. Пополнять карту при появлении новых имён в цепочке.
MACRO_FACTOR_ALIASES = {
    "geopolitics": "geopol",
    "sanctions_russia": "sanctions",
    "brent_price": "brent",
    "usdrub_rate": "usdrub",
    "cnyrub_rate": "cnyrub",
    "xauusd_price": "xauusd",
}

# Единицы factor_betas (контракт P0-1, SSOT — portfolio-scenario-stress/references/
# sector-sensitivities.md «Контракт единиц»): β — п.п. цены на ОДНУ единицу фактора
# в его собственной единице. Для sanctions/geopol единица — интенсивность 1.0 по
# шкале −1…+1 (бета банков ≈ −35, не −0.35). Если L1-оценка политического фактора
# когда-нибудь станет числовой, она обязана быть в той же шкале интенсивности —
# иначе overlay умножит п.п.-бету на проценты. Сейчас такие оценки качественные
# (строки) и пропускаются.

# ── MFC-4: конвертация уровень → движение (D-A = A′) ──
# unit → (кандидаты ключей в baseline_spot из stress, тип конвертации)
# pct_from_spot: движение = (level − spot) / spot × 100  (в %)
# pp_diff:       движение = level − spot                 (в п.п.)
# Таблица единиц — SSOT: _shared-references/events-yaml-spec.md §5.6
#
# Кандидатов несколько, потому что stress переименовал ключи baseline_spot между
# прогонами 2026-08-04 и 2026-08-06 (`brent_usd` → `brent_price`, `usdrub` →
# `usdrub_rate`, `cbr_rate_pct` → `cbr_rate`, …). Архивные артефакты живут в
# Claude-Memory с обоими наборами, поэтому поддерживаем оба: первый найденный
# ключ выигрывает, порядок — «исторический, затем текущий».
UNIT_SPOT_KEYS: dict[str, tuple[tuple[str, ...], str]] = {
    "usd_per_bbl":     (("brent_usd", "brent_price"),   "pct_from_spot"),
    "rub_per_usd":     (("usdrub", "usdrub_rate"),      "pct_from_spot"),
    "rub_per_cny":     (("cnyrub", "cnyrub_rate"),      "pct_from_spot"),
    "usd_per_troy_oz": (("xauusd_usd", "xauusd_price"), "pct_from_spot"),
    "rate_pct":        (("cbr_rate_pct", "cbr_rate"),   "pp_diff"),
}

# Вердикты таблицы stress.macro_blindspots, означающие «макро-матрица описывает
# меньшую часть дисперсии позиции» (PIV-5). MACRO_DOMINATES сюда НЕ входит.
BLINDSPOT_TABLE_VERDICTS = {"MIXED", "IDIOSYNCRATIC_DOMINATES"}

# ── Tail-risk флаги (output schema @1.2) ──
# Anti-fatigue defaults: флаги срабатывают редко и каждый указывает на РАЗНЫЙ
# decision-response. Все пороги — параметры compute_tail_flags(), НЕ хардкод.
TAIL_SKEW_THRESHOLD = 2.0        # Флаг 1: отношение длинного плеча CI к короткому
TAIL_WEIGHT_FLOOR_PCT = 2.0      # Флаг 2: мин. доля позиции (% портфеля) для zero-cross
TAIL_SHARE_THRESHOLD = 0.15      # Флаг 3: доля позиции во вкладе в нижний хвост портфеля
PORTFOLIO_TAIL_FLOOR = 3.0       # Флаг 3: materiality floor для Σ contrib_down (пп·доля)
TAIL_CAP = 3                     # Флаг 3: максимум топ-N контрибьюторов


# ───────────────────────────── helpers ──────────────────────────────

def _get(d: dict | None, *keys, default=None):
    if d is None:
        return default
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _ci(spec, default_lo: float = 0.0, default_hi: float = 0.0) -> list[float]:
    # spec может быть dict {value, ci_pct} или просто число
    if spec is None or spec == "":
        return [default_lo, default_hi]
    if isinstance(spec, (int, float)) and not isinstance(spec, bool):
        return [float(spec), float(spec)]
    if isinstance(spec, dict):
        raw = spec.get("ci_pct") or spec.get("ci")
        if not raw or len(raw) != 2:
            v = spec.get("value", default_lo)
            return [v, v]
        return [float(raw[0]), float(raw[1])]
    return [default_lo, default_hi]


def _value(spec, default: float = 0.0) -> float:
    # spec может быть dict {value, ci_pct} или просто число
    if spec is None or spec == "":
        return default
    if isinstance(spec, (int, float)) and not isinstance(spec, bool):
        return float(spec)
    if isinstance(spec, dict):
        return float(spec.get("value", default))
    return default


def _scale(values: list[float], factor: float) -> list[float]:
    return [v * factor for v in values]


def _parse_snapshot_date(snapshot_id: str | None) -> date | None:
    if not snapshot_id:
        return None
    # Принимаем форматы portfolio-YYYY-MM-DD.json или просто YYYY-MM-DD
    s = snapshot_id.replace("portfolio-", "").replace(".json", "").strip()
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_iso_date(s) -> date | None:
    """Толерантный парс YYYY-MM-DD (для offer_date / maturity_date / as_of)."""
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _earliest_date(*candidates) -> date | None:
    parsed = [d for d in (_parse_iso_date(c) for c in candidates) if d is not None]
    return min(parsed) if parsed else None


def _months_between(d_from: date | None, d_to: date | None) -> float | None:
    """Приблизительное число месяцев между датами (365.25/12 ≈ 30.44 дн/мес)."""
    if d_from is None or d_to is None:
        return None
    return (d_to - d_from).days / 30.4375


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _level_to_move(level: float, unit: str, baseline_spot: dict) -> float | None:
    """Конвертирует числовой уровень L1 в движение фактора по контракту §5.6."""
    entry = UNIT_SPOT_KEYS.get(unit)
    if entry is None:
        return None
    spot_keys, conv_type = entry
    spot = None
    for k in spot_keys:
        cand = baseline_spot.get(k)
        if _is_number(cand):
            spot = cand
            break
    if not _is_number(spot) or float(spot) == 0:
        return None
    if conv_type == "pct_from_spot":
        return (level - float(spot)) / float(spot) * 100.0
    else:  # pp_diff
        return level - float(spot)


def _pick_nearest_level(fcast: dict, target_year: int) -> tuple[float | None, str | None]:
    """
    Ищет level_l1_{год} в fcast, выбирает ближайший год к target_year.
    Возвращает (level, unit) или (None, None).
    """
    _PREFIX = "level_l1_"
    candidates: list[tuple[int, float]] = []
    for k, v in fcast.items():
        if k.startswith(_PREFIX) and _is_number(v):
            try:
                candidates.append((int(k[len(_PREFIX):]), float(v)))
            except ValueError:
                continue
    if not candidates:
        return None, None
    _, level = min(candidates, key=lambda yv: abs(yv[0] - target_year))
    unit = fcast.get("unit")
    return (level, unit) if isinstance(unit, str) else (None, None)


def _clamp_carry(v: float) -> tuple[float, bool]:
    """Backstop: ограничить |carry| ≤ CARRY_CAP_PCT. Возвращает (value, clamped?)."""
    if v > CARRY_CAP_PCT:
        return CARRY_CAP_PCT, True
    if v < -CARRY_CAP_PCT:
        return -CARRY_CAP_PCT, True
    return v, False


# ───────────── Phase 4 (V2-A): multiple horizons — хелперы ─────────────

_DW_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$", re.IGNORECASE)
# Разделитель диапазона date_window: '..', em/en-dash, ' - ', ' to '. Дефис без
# пробелов НЕ разделитель (иначе ломает YYYY-MM-DD / YYYY-MM). Контракт §11.3.
_DW_RANGE_SEP_RE = re.compile(r"(?:\s*\.\.\s*|\s*[—–]\s*|\s+-\s+|\s+to\s+)", re.IGNORECASE)


def _parse_one_date_token(tok: str) -> date | None:
    tok = (tok or "").strip()
    if not tok:
        return None
    m = _DW_QUARTER_RE.match(tok)
    if m:
        return date(int(m.group(1)), (int(m.group(2)) - 1) * 3 + 1, 1)
    if re.match(r"^\d{4}-\d{2}-\d{2}$", tok):
        try:
            return date.fromisoformat(tok)
        except ValueError:
            return None
    if re.match(r"^\d{4}-\d{2}$", tok):
        y, mo = int(tok[:4]), int(tok[5:7])
        return date(y, mo, 1) if 1 <= mo <= 12 else None
    if re.match(r"^\d{4}$", tok):
        return date(int(tok), 1, 1)
    return None


def _parse_date_window_start(s: str | None) -> date | None:
    """Начало окна date_window по контракту §11.3. None если непарсибельно."""
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    return _parse_one_date_token(_DW_RANGE_SEP_RE.split(s)[0].strip())


def _catalyst_in_horizon(
    catalyst: dict,
    horizon_end: date | None,
) -> tuple[bool, str | None]:
    """
    Принадлежность катализатора горизонту (§11.3): начало date_window ≤ horizon_end.
    Возвращает (in_horizon, warning).
    - horizon_end is None (конец горизонта не определён) → True без фильтра.
    - непарсибельный date_window → True + warning 'date_window_unparseable' (консервативно).
    """
    if horizon_end is None:
        return True, None
    start = _parse_date_window_start(catalyst.get("date_window"))
    if start is None:
        return True, "date_window_unparseable"
    return (start <= horizon_end), None


def _add_months_eom(d: date, months: int) -> date:
    idx = d.year * 12 + (d.month - 1) + months
    y, m = idx // 12, idx % 12 + 1
    return date(y, m, calendar.monthrange(y, m)[1])


def _normalize_horizons(payload: dict) -> tuple[list[int], int]:
    """
    Возвращает (horizons, primary_horizon). Источник: payload.horizons (нет — DEFAULT_HORIZONS).
    CLI-фильтр payload._horizon_subset (подмножество) применяется поверх.
    """
    horizons = payload.get("horizons")
    if isinstance(horizons, list) and horizons:
        horizons = sorted({int(h) for h in horizons})
    else:
        horizons = list(DEFAULT_HORIZONS)
    primary = payload.get("primary_horizon")
    if not isinstance(primary, int) or primary not in horizons:
        primary = horizons[0] if len(horizons) == 1 else (
            DEFAULT_PRIMARY_HORIZON if DEFAULT_PRIMARY_HORIZON in horizons else horizons[0])
    return horizons, primary


def _resolve_horizon_ends(
    horizons: list[int], stress: dict, review_stocks: dict, as_of: date | None,
) -> dict[str, str | None]:
    """horizon_ends: из stress/review (v2) или вычисленные от as_of (конец месяца)."""
    src = (stress.get("horizon_ends") if isinstance(stress.get("horizon_ends"), dict) else None) \
        or (_get(review_stocks, "horizon_ends") if isinstance(_get(review_stocks, "horizon_ends"), dict) else None) \
        or {}
    out: dict[str, str | None] = {}
    for h in horizons:
        hk = f"h{h}"
        v = src.get(hk)
        if isinstance(v, str):
            out[hk] = v
        elif as_of is not None:
            out[hk] = _add_months_eom(as_of, h).isoformat()
        else:
            out[hk] = None
    return out


def _available_stress_horizons(stress_per_position: dict) -> set[str] | None:
    """Множество hNN, доступных в stress. None если ни у одной позиции нет by_horizon."""
    keys: set[str] = set()
    for p in stress_per_position.values():
        bh = p.get("by_horizon") if isinstance(p, dict) else None
        if isinstance(bh, dict):
            keys.update(bh.keys())
    return keys or None


def _stress_pos_for_horizon(stress_pos: dict | None, hk: str) -> dict | None:
    """Срез stress-позиции на горизонт hk: by_horizon[hk]."""
    if stress_pos is None:
        return None
    bh = stress_pos.get("by_horizon")
    slot = (bh.get(hk) if isinstance(bh, dict) else None) or {}
    return {
        "expected_pct_pweighted": slot.get("expected_pct_pweighted"),
        "ci_pct": slot.get("ci_pct"),
        "factor_betas": stress_pos.get("factor_betas"),
        "macro_blindspot": stress_pos.get("macro_blindspot", False),
    }


def _horizon_view(per_position: list[dict], hk: str) -> list[dict]:
    """Проекция per_position на горизонт hk: total/weight для portfolio/tail/sanity.

    l1_total (@1.4) — тот же total, но с macro-центром из L1-overlay вместо
    канонического L2 (total − macro.value + macro.l1_point). None, если
    L1-точки нет. Идёт ТОЛЬКО в portfolio_by_horizon.*.l1_point — headline/
    spread/CI/tail/sanity считаются от канонического total."""
    out = []
    for p in per_position:
        slot = (p.get("by_horizon") or {}).get(hk) or {}
        total = slot.get("total") or {"value": None, "ci": [None, None]}
        m = slot.get("macro") or {}
        l1p = m.get("l1_point")
        l1_total = None
        if l1p is not None and total.get("value") is not None:
            l1_total = total["value"] - (m.get("value") or 0.0) + l1p
        out.append({
            **{k: p[k] for k in ("ticker", "asset_class", "weight_pct",
                                 "weight_source", "is_blocked") if k in p},
            "total": total,
            "l1_total": l1_total,
        })
    return out


# ────────────────────────── Шаг 1.5: Нормировка p_i ──────────────────────────

def normalize_scenario_probs(scenarios: dict,
                             horizon_keys: list[str] | None = None
                             ) -> tuple[float, str | None]:
    """
    Возвращает (S, severity). Mutates scenarios in-place: добавляет `p_norm`.

    PSS-9: при наличии `p_by_horizon` дополнительно пишет `p_norm_by_horizon`
    {hk: доля} по переданным horizon_keys. Скалярный `p_norm` сохраняется, и (S,
    severity) считаются ПО СКАЛЯРУ — иначе диагностика нормировки поменяла бы смысл.

    Смешанный вход (блок есть у части сценариев) останавливает расчёт — согласованно
    с `compute_bond_carry._p_norm`: один и тот же дефект не может давать разные ответы
    в двух ногах total-return.
    """
    if not scenarios:
        return 0.0, None
    if horizon_keys:
        for hk in horizon_keys:
            with_key = {sid: sc["p_by_horizon"][hk] for sid, sc in scenarios.items()
                        if isinstance(sc.get("p_by_horizon"), dict)
                        and hk in sc["p_by_horizon"]}
            if not with_key:
                continue
            if len(with_key) != len(scenarios):
                missing = sorted(set(scenarios) - set(with_key))
                raise SystemExit(
                    f"ERROR: p_by_horizon[{hk}] задан не у всех сценариев "
                    f"(нет у {', '.join(missing)}). Смешивать горизонтные веса со "
                    f"скаляром нельзя — задай блок всем сценариям или никому."
                )
            tot = sum(float(v or 0) for v in with_key.values())
            if tot <= 0:
                raise SystemExit(f"ERROR: сумма p_by_horizon[{hk}] = {tot}")
            for sid, v in with_key.items():
                scenarios[sid].setdefault("p_norm_by_horizon", {})[hk] = float(v or 0) / tot
    S = sum(float(sc.get("p", 0)) for sc in scenarios.values())
    if S <= 0:
        for sc in scenarios.values():
            sc["p_norm"] = 0.0
        return S, "MEDIUM"
    for sc in scenarios.values():
        sc["p_norm"] = float(sc.get("p", 0)) / S
    delta = abs(S - 1.0)
    if delta > SCENARIO_P_MEDIUM_THRESHOLD:
        return S, "MEDIUM"
    if delta > SCENARIO_P_LOW_THRESHOLD:
        return S, "LOW"
    return S, None


def merge_duplicate_holdings(holdings: list[dict]) -> tuple[list[dict], list[str]]:
    """PIV-4c: схлопывание строк одного тикера (позиция на нескольких счетах).

    weight_pct берётся из stress по тикеру, где позиция уже схлопнута, —
    вторая строка снапшота получала бы полный вес ПОВТОРНО (кейс
    RU000A1038V6 main+iis_3: Σ весов бакетов 100.85%). qty/value_rub
    суммируются, скалярные поля — от строки с большей стоимостью,
    счета — в accounts_merged. Вход не мутируется.
    """
    merged_tickers: list[str] = []
    seen: dict[str, int] = {}
    deduped: list[dict] = []
    for hold in holdings:
        t = hold.get("ticker")
        # разный is_blocked — это ОМОНИМ тикера (шрам T: AT&T vs Т-Технологии),
        # а не позиция на двух счетах; такие строки не мержатся
        prev_i = seen.get(t) if t is not None else None
        if (prev_i is not None
                and bool(deduped[prev_i].get("is_blocked"))
                == bool(hold.get("is_blocked"))):
            base = deduped[prev_i]
            merged = {**base}
            # скалярные поля — от строки с большей стоимостью
            if (hold.get("value_rub") or 0) > (base.get("value_rub") or 0):
                for k, v in hold.items():
                    merged[k] = v
            for k in ("qty", "value_rub"):
                a, b = base.get(k), hold.get(k)
                if a is not None or b is not None:
                    merged[k] = (a or 0) + (b or 0)
            accs: set[str] = set()
            for src in (base, hold):
                prev_accs = src.get("accounts_merged")
                if isinstance(prev_accs, list):
                    accs.update(map(str, prev_accs))
                else:
                    accs.add(str(src.get("account") or "?"))
            merged["accounts_merged"] = sorted(accs)
            deduped[prev_i] = merged
            if t not in merged_tickers:
                merged_tickers.append(t)
        else:
            if t is not None and t not in seen:
                seen[t] = len(deduped)
            deduped.append(hold)
    return deduped, merged_tickers


# ────────────────────── Шаг 2: cross-validate + drift ──────────────────────

def cross_validate(review_stocks: dict, scenarios: dict,
                   review_bonds: dict | None = None) -> dict:
    """Возвращает {unresolved: [...], total_with_dependency: N, share: x, missing: [...],
    total_catalysts: N, idio_layer_unlinked: bool}"""
    stress_ids = set(scenarios.keys())
    unresolved: list[dict] = []
    total = 0
    n_catalysts = 0
    per_stock = _get(review_stocks, "per_stock", default={}) or {}
    for ticker, stock in per_stock.items():
        for c in (stock.get("catalyst") or []):
            n_catalysts += 1
            dep = c.get("macro_dependency")
            if not dep:
                continue
            total += 1
            if dep not in stress_ids:
                unresolved.append({
                    "ticker": ticker,
                    "catalyst_id": c.get("id", "<no-id>"),
                    "ref": dep,
                })
    # PIV-4a: облигационные катализаторы входят только в общий счёт — их deps
    # в share гейта не участвуют (прежняя семантика доли сохранена).
    if review_bonds:
        per_bond = _get(review_bonds, "per_bond", default={}) or {}
        for bond in per_bond.values():
            n_catalysts += len(bond.get("catalyst") or [])
    share = (len(unresolved) / total) if total else 0.0
    missing = sorted({u["ref"] for u in unresolved})
    return {
        "unresolved": unresolved,
        "total_with_dependency": total,
        "share": share,
        "missing_scenario_ids": missing,
        "total_catalysts": n_catalysts,
        # «0 неразрешённых из 0» при живых катализаторах — не чистый PASS:
        # идио-слой целиком развязан со сценарным (прогон 08-06: 110/110).
        "idio_layer_unlinked": total == 0 and n_catalysts > 0,
    }


def check_snapshot_drift(stress: dict, review_stocks: dict, review_bonds: dict | None) -> dict:
    # payload-контракт — snapshot_id; сырой stress-YAML несёт portfolio_snapshot_id
    stress_id = stress.get("snapshot_id") or stress.get("portfolio_snapshot_id")
    rs_id = _get(review_stocks, "snapshot_id")
    rb_id = _get(review_bonds, "snapshot_id") if review_bonds else None
    sd = _parse_snapshot_date(stress_id)
    rs_d = _parse_snapshot_date(rs_id)
    rb_d = _parse_snapshot_date(rb_id)
    drifts = []
    if sd and rs_d:
        drifts.append(abs((sd - rs_d).days))
    if sd and rb_d:
        drifts.append(abs((sd - rb_d).days))
    max_drift = max(drifts) if drifts else 0
    return {
        "stress_snapshot_id": stress_id,
        "review_stocks_snapshot_id": rs_id,
        "review_bonds_snapshot_id": rb_id,
        "max_drift_days": max_drift,
        "drift_warning": max_drift > SNAPSHOT_DRIFT_THRESHOLD_DAYS,
    }


def _iter_catalysts(review_stocks: dict, review_bonds: dict | None):
    """(ticker, catalyst) по обоим обзорам — общий обход для валидаторов."""
    for src, key in ((review_stocks, "per_stock"), (review_bonds, "per_bond")):
        for ticker, pos in ((_get(src, key) or {}) if src else {}).items():
            if not isinstance(pos, dict):
                continue
            for c in (pos.get("catalyst") or []):
                if isinstance(c, dict):
                    yield ticker, c


def check_horizon_anchor_drift(
    horizons: list[int], stress: dict, review_stocks: dict,
    review_bonds: dict | None,
) -> dict:
    """
    R-ANCHOR (PIV-5): якоря горизонтов у stress и weekly-review могут не совпадать.

    `_resolve_horizon_ends` берёт stress первым и молча перекрывает даты обзоров.
    Прогон 08-15: у stress якорный режим (2026-12-31 / 2027-06-30 / 2028-06-30),
    у обзоров честные +6/+12/+24 (2027-02-28 / 2027-08-31 / 2028-08-31) — расхождение
    до 62 дней. Само по себе это законно (истина — stress, он несёт купонные
    расписания и maturity guard), но НЕ должно проходить молча: катализаторы обзора,
    попавшие между двумя якорями, учитываются на «не своём» горизонте.

    Возвращает расхождение по горизонтам + поимённый список задетых катализаторов
    (тех, чей in-horizon статус меняется при подмене даты).
    """
    s_ends = stress.get("horizon_ends") if isinstance(stress.get("horizon_ends"), dict) else {}
    r_ends: dict = {}
    for src in (review_stocks, review_bonds):
        cand = _get(src, "horizon_ends") if src else None
        if isinstance(cand, dict):
            for k, v in cand.items():
                r_ends.setdefault(k, v)

    by_horizon: dict[str, dict] = {}
    for h in horizons:
        hk = f"h{h}"
        sd, rd = _parse_iso_date(s_ends.get(hk)), _parse_iso_date(r_ends.get(hk))
        if sd is None or rd is None or sd == rd:
            continue
        by_horizon[hk] = {"stress": sd.isoformat(), "review": rd.isoformat(),
                          "days": abs((sd - rd).days)}

    affected: list[dict] = []
    if by_horizon:
        for ticker, c in _iter_catalysts(review_stocks, review_bonds):
            for hk, d in by_horizon.items():
                in_s, _ = _catalyst_in_horizon(c, _parse_iso_date(d["stress"]))
                in_r, _ = _catalyst_in_horizon(c, _parse_iso_date(d["review"]))
                if in_s != in_r:
                    affected.append({
                        "ticker": ticker, "catalyst_id": c.get("id"), "horizon": hk,
                        "date_window": c.get("date_window"),
                        "counted_by": "stress" if in_s else "review",
                    })

    message = None
    if by_horizon:
        worst = max(d["days"] for d in by_horizon.values())
        message = (
            f"якоря горизонтов stress и weekly-review расходятся "
            f"({', '.join(f'{hk}: {d['stress']} против {d['review']}' for hk, d in sorted(by_horizon.items()))}; "
            f"максимум {worst} дн.). За истину взят stress. "
            f"Катализаторов, меняющих горизонт из-за подмены даты: {len(affected)}. "
            f"Перечислить в §0 и оговоркой СРЕДНЕЙ серьёзности в §9."
        )
    return {
        "drift": bool(by_horizon),
        "by_horizon": by_horizon,
        "source_of_truth": "stress",
        "affected_catalysts": affected,
        "message": message,
    }


# ────────────────────── Шаг 3: per-position aggregate ──────────────────────

def _trust_key(analyst: str, subdomain: str) -> str:
    """Канонический ключ матрицы доверия: «аналитик|поддомен», регистр не важен."""
    return f"{analyst.strip().casefold()}|{subdomain.strip().casefold()}"


def _ignored_trust_keys(trust_matrix: dict | None) -> set[str]:
    """
    Множество IGNORE-ключей из матрицы. Принимает две формы:

    - `ignored` — список `{analyst, subdomain}` (канон с 2026-08-16);
    - `ignored_subdomains` — легаси-список строк «Аналитик поддомен» (так его
      собирал прогон 08-15 из INDEX.md). Разбирается по ПОСЛЕДНЕМУ пробелу:
      имена аналитиков многословны («Bank of Russia (CBR)»), поддомены — нет.
    """
    keys: set[str] = set()
    for row in (trust_matrix or {}).get("ignored") or []:
        if isinstance(row, dict) and row.get("analyst") and row.get("subdomain"):
            keys.add(_trust_key(str(row["analyst"]), str(row["subdomain"])))
    for s in (trust_matrix or {}).get("ignored_subdomains") or []:
        if isinstance(s, str) and " " in s.strip():
            analyst, _, subdomain = s.strip().rpartition(" ")
            keys.add(_trust_key(analyst, subdomain))
    return keys


def catalyst_trust_tag(catalyst: dict) -> tuple[str, str] | None:
    """`source_trust: {analyst, subdomain}` катализатора или None, если не размечен."""
    st = catalyst.get("source_trust")
    if not isinstance(st, dict):
        return None
    analyst = str(st.get("analyst") or "").strip()
    subdomain = str(st.get("subdomain") or "").strip()
    return (analyst, subdomain) if analyst and subdomain else None


def is_low_trust(catalyst: dict, trust_matrix: dict | None) -> bool:
    """
    Катализатор из IGNORE-поддомена (правило 11).

    **Матч по структурному тегу, а не по прозе (PIV-7).** Раньше сравнивался
    `catalyst.source` с элементами `ignored_subdomains` точным равенством строк, а
    `source` в живых обзорах — это URL либо фраза («advisor estimate: отчёт не
    анонсирован официально…»). Совпасть с тегом «аналитик + поддомен» такое не может
    никогда: прогон 08-15 извлёк 28 записей IGNORE и не отфильтровал НИ ОДНОГО
    катализатора из 105, а правило 11 всё это время выглядело работающим.
    Атрибуцию источника теперь проставляет производитель (`ru-portfolio-advisor`,
    Mode 1/2) полем `source_trust` — знание о том, чей это сигнал, есть у него.

    Катализатор без тега НЕ дисконтируется (переходный режим для обзоров,
    выпущенных до 2026-08-16); их доля видна в `validation.trust_coverage`.
    Легаси-путь точного совпадения по `source` сохранён.
    """
    if not trust_matrix:
        return False
    tag = catalyst_trust_tag(catalyst)
    if tag is not None:
        return _trust_key(*tag) in _ignored_trust_keys(trust_matrix)
    src = (catalyst.get("source") or "").strip()
    return bool(src) and src in set(trust_matrix.get("ignored_subdomains") or [])


def compute_trust_coverage(review_stocks: dict, review_bonds: dict | None,
                           trust_matrix: dict | None) -> dict:
    """
    Покрытие матрицы доверия: сколько катализаторов вообще атрибутировано (PIV-7).

    Без этого блока §9 может написать «низкодоверенных источников не найдено», хотя
    правильное утверждение — «атрибуция не выполнена, фильтр не мог сработать».
    Это разные вещи, и до 2026-08-16 отчёт выдавал вторую за первую.
    """
    total = tagged = ignored_n = 0
    ignored_keys = _ignored_trust_keys(trust_matrix)
    ignored_list: list[dict] = []
    for ticker, c in _iter_catalysts(review_stocks, review_bonds):
        total += 1
        tag = catalyst_trust_tag(c)
        if tag is None:
            continue
        tagged += 1
        if _trust_key(*tag) in ignored_keys:
            ignored_n += 1
            ignored_list.append({"ticker": ticker, "catalyst_id": c.get("id"),
                                 "analyst": tag[0], "subdomain": tag[1]})
    message = None
    if trust_matrix and total and not tagged:
        message = (
            f"матрица доверия не применялась: из {total} катализаторов ни один не "
            f"несёт `source_trust` — атрибуция источников не выполнена, фильтр "
            f"IGNORE не мог сработать в принципе. Писать «низкодоверенных источников "
            f"нет» НЕЛЬЗЯ; корректная формулировка — «фильтрация по доверию в этом "
            f"прогоне не работала». Производитель атрибуции — Mode 1/2 "
            f"ru-portfolio-advisor."
        )
    elif trust_matrix and total and tagged < total:
        message = (
            f"атрибутировано {tagged} из {total} катализаторов; остальные "
            f"({total - tagged}) фильтр доверия не проверял. Оговорка СРЕДНЕЙ "
            f"серьёзности в §9."
        )
    return {
        "matrix_ignored_keys": len(ignored_keys),
        "total_catalysts": total,
        "tagged": tagged,
        "untagged": total - tagged,
        "ignored_applied": ignored_n,
        "ignored_catalysts": ignored_list,
        "message": message,
    }


def aggregate_macro(
    stress_pos: dict | None,
    macro_marginal: dict | None = None,
    *,
    baseline_spot: dict | None = None,
    horizon_year: int | None = None,
) -> dict:
    if not stress_pos:
        return {
            "value": None,
            "ci": [None, None],
            "blindspot": False,
            "source": "missing",
            "layer": None,
            "coherence_gap": None,
            "l1_point": None,
            "l1_status": "no_stress_position" if macro_marginal else None,
            "l1_unmatched_factors": [],
        }
    epw = stress_pos.get("expected_pct_pweighted")
    # Поддерживаем 2 формы: number (legacy) и dict {value, ci_pct}
    if isinstance(epw, dict):
        l2_val = epw.get("value")
        ci = epw.get("ci_pct") or [None, None]
    else:
        l2_val = epw
        ci = stress_pos.get("ci_pct") or [None, None]

    float_ci = [
        float(ci[0]) if ci and ci[0] is not None else None,
        float(ci[1]) if ci and ci[1] is not None else None,
    ]

    # Layer 1: Σ_f (beta[f] × движение[f]) — только при наличии macro_marginal + factor_betas.
    # Попытка 1: новый формат level_l1_<год> + unit → конвертация против baseline_spot (D-A=A′).
    # Попытка 2: backward-compat — плоский числовой central_estimate.
    # Guard: качественные факторы (geopolitics/sanctions как строки) пропускаются.
    # MACRO_FACTOR_ALIASES сопоставляет имена из macro-marginal с ключами factor_betas.
    # Если ни один фактор не дал числовое движение → L2 fallback.
    factor_betas = stress_pos.get("factor_betas")
    # Диагностика тихого отказа overlay (PIV-5): факторы, у которых бета нашлась,
    # но числовое движение получить не удалось (нет level_l1/unit, нет ключа в
    # baseline_spot, качественная оценка строкой).
    unmatched_factors: list[str] = []
    if macro_marginal and factor_betas:
        l1_terms = []
        for f, fcast in macro_marginal.items():
            if not isinstance(fcast, dict):
                continue
            beta_key = MACRO_FACTOR_ALIASES.get(f, f)
            beta = factor_betas.get(beta_key)
            if beta is None and beta_key != f:
                beta = factor_betas.get(f)
            if beta is None:
                continue

            move = None
            # Попытка 1: level_l1_<год> + unit + baseline_spot (MFC-4 новый формат)
            if baseline_spot is not None and horizon_year is not None:
                level, unit = _pick_nearest_level(fcast, horizon_year)
                if level is not None and unit is not None:
                    move = _level_to_move(level, unit, baseline_spot)

            # Попытка 2: backward-compat — плоский числовой central_estimate
            if move is None:
                ce = fcast.get("central_estimate")
                if _is_number(ce):
                    move = float(ce)

            if move is not None:
                l1_terms.append(float(beta) * move)
            else:
                unmatched_factors.append(f)

        if l1_terms:
            l1_val = sum(l1_terms)
            l2_float = float(l2_val) if l2_val is not None else None
            coherence_gap = round(abs(l1_val - l2_float), 4) if l2_float is not None else None
            # @1.4 (единый канон центра): value ВСЕГДА Layer 2 p-weighted —
            # MC и total_return сэмплируют per-scenario дельты stress, поэтому
            # только L2-центр консистентен с MC-CI. Раньше L1 подменял value →
            # headline лежал вне собственного CI (bond m12 35.2 при CI
            # [24.8, 32.3]). L1-точка сохранена отдельным полем l1_point
            # (аналитический overlay, НЕ входит в headline/spread/CI).
            # Fallback: если L2 отсутствует — value = L1 (старое поведение).
            common = {
                "ci": float_ci,
                "blindspot": bool(stress_pos.get("macro_blindspot", False)),
                "coherence_gap": coherence_gap,
                "l1_point": round(float(l1_val), 4),
                "l1_status": "applied",
                "l1_unmatched_factors": sorted(unmatched_factors),
            }
            if l2_float is not None:
                return {"value": l2_float, "source": "stress", "layer": "L2", **common}
            return {"value": round(float(l1_val), 4),
                    "source": "macro_marginal", "layer": "L1", **common}
        # ни одного сопоставимого фактора → L2 fallback ниже

    # Layer 2 fallback (оригинальное поведение).
    # l1_status различает три случая: overlay не запрашивали (None), запрашивали, но
    # у позиции нет factor_betas (no_factor_betas), запрашивали и беты есть, но ни один
    # фактор не дал числового движения (no_factor_match) — это тихий отказ, который
    # run() обязан поднять в validation.l1_overlay.
    if not macro_marginal:
        l1_status = None
    elif not factor_betas:
        l1_status = "no_factor_betas"
    else:
        l1_status = "no_factor_match"
    return {
        "value": float(l2_val) if l2_val is not None else None,
        "ci": float_ci,
        "blindspot": bool(stress_pos.get("macro_blindspot", False)),
        "source": "stress",
        "layer": "L2",
        "coherence_gap": None,
        "l1_point": None,
        "l1_status": l1_status,
        "l1_unmatched_factors": sorted(unmatched_factors),
    }


def _carry_result(spec, eff_factor: float, source: str) -> dict:
    """Carry = basis × eff_factor с backstop-клампом |value| ≤ CARRY_CAP_PCT."""
    v_raw = _value(spec) * eff_factor
    v, clamped = _clamp_carry(v_raw)
    ci = [_clamp_carry(c)[0] for c in _scale(_ci(spec), eff_factor)]
    return {"value": v, "ci": ci, "source": source + ("_capped" if clamped else "")}


def _scenario_p_norm(scenarios: dict | None, sid: str,
                     horizon_key: str | None = None) -> float:
    sc = (scenarios or {}).get(sid) or {}
    if horizon_key is not None:
        by_h = sc.get("p_norm_by_horizon")
        if isinstance(by_h, dict) and horizon_key in by_h:
            try:
                return float(by_h[horizon_key] or 0)
            except (TypeError, ValueError):
                return 0.0
    try:
        return float(sc.get("p_norm", sc.get("p", 0)) or 0)
    except (TypeError, ValueError):
        return 0.0


def _carry_from_block(carry_slot: dict, scenarios: dict | None, source: str,
                      horizon_key: str | None = None) -> dict | None:
    """
    Слой 2: срез bond_carry.per_position.X.by_horizon.hNN → p-weighted expected
    carry + CI (линейно по границам ячеек) + сами ячейки by_scenario (для MC и
    total_return_by_horizon). Пустой срез → None (fallback на legacy-цепочку).
    """
    cells = (carry_slot or {}).get("by_scenario") or {}
    if not cells:
        return None
    total_p = sum(_scenario_p_norm(scenarios, sid, horizon_key) for sid in cells)
    if total_p <= 0:
        total_p = float(len(cells))
        weights = {sid: 1.0 / total_p for sid in cells}
    else:
        weights = {sid: _scenario_p_norm(scenarios, sid, horizon_key) / total_p
                   for sid in cells}
    val = lo = hi = 0.0
    for sid, cell in cells.items():
        w = weights[sid]
        cv = float((cell or {}).get("carry_pct", 0) or 0)
        ci = (cell or {}).get("ci_pct") or [cv, cv]
        val += w * cv
        lo += w * float(ci[0])
        hi += w * float(ci[1])
    return {
        "value": round(val, 4),
        "ci": [round(min(lo, hi), 4), round(max(lo, hi), 4)],
        "source": source,
        "by_scenario": cells,
        "flags": list((carry_slot or {}).get("flags") or []),
        "matures_within": bool((carry_slot or {}).get("matures_within", False)),
    }


def _dividend_forward_contrib(df: dict, horizon_months: float) -> dict:
    """
    Слой 3: dividend_forward → вклад за горизонт. Гейт policy_state: вклад дают
    ТОЛЬКО declared/expected; uncertain → 0 + флаг ПРОПУСКА (не «дивы = 0»).
    Проекция: год 1 × min(h,12)/12 + год 2 × (min(h,24)−12)/12; h > 24 —
    carry_forward года 2 (флаг beyond_projection). CI — относительная полоса по
    confidence (DIV_CONF_CI_REL): у блока нет явного CI по контракту схемы.
    """
    ps = str(df.get("policy_state") or "").lower()
    flags: list[str] = []
    if ps not in ("declared", "expected"):
        if ps == "uncertain":
            flags.append("dividend_missing_policy_unknown")
        return {"value": 0.0, "ci": [0.0, 0.0],
                "source": f"dividend_forward_{ps or 'invalid'}", "flags": flags}
    y1 = _value(df.get("year1_yield_pct"), 0.0)
    y2 = _value(df.get("year2_yield_pct"), 0.0) \
        if df.get("year2_basis") in ("analyst", "carry_forward") else 0.0
    h = float(horizon_months)
    m1 = min(h, 12.0) / 12.0
    m2 = max(0.0, min(h, 24.0) - 12.0) / 12.0
    m3 = max(0.0, h - 24.0) / 12.0   # год 3+ = carry_forward года 2 (LOW)
    val = y1 * m1 + y2 * (m2 + m3)
    if m3 > 0 and y2:
        flags.append("beyond_projection_carry_forward")
    rel = DIV_CONF_CI_REL.get(str(df.get("confidence") or "MEDIUM").upper(), 0.25)
    return {
        "value": round(val, 4),
        "ci": [round(val * (1 - rel), 4), round(val * (1 + rel), 4)],
        "source": "dividend_forward",
        "flags": flags,
    }


def aggregate_div_or_carry(
    asset_class: str,
    review_pos: dict | None,
    review_bond_pos: dict | None,
    holding: dict,
    horizon_months: int,
    as_of: date | None = None,
    carry_slot: dict | None = None,
    carry_kind: str | None = None,
    scenarios: dict | None = None,
) -> dict:
    factor = horizon_months / 12.0

    # ── Слой 2 (приоритет №1): блок bond_carry из stress (compute_bond_carry) ──
    # Облигации + money-market (TMON/TPAY и т.п., в carry-блоке kind=money_market).
    # Legacy ytm×t (ниже) остаётся fallback для stress без carry-блока.
    if carry_slot is not None and (asset_class == "bond"
                                   or carry_kind in ("money_market", "cash")):
        res = _carry_from_block(
            carry_slot, scenarios,
            source="bond_carry" if carry_kind == "bond" or asset_class == "bond"
            else "mm_carry",
            # PSS-9: горизонт выводится из horizon_months — отдельный параметр
            # завёл бы второй источник правды о том, какой это горизонт.
            horizon_key=f"h{horizon_months}",
        )
        if res is not None:
            return res

    if asset_class == "bond":
        rb = review_bond_pos or {}
        # (1) Горизонт carry capped до ближайшей оферты/погашения: после события бумага
        # гасится, carry за пределами не начисляется (Баг #1A).
        event_date = _earliest_date(rb.get("offer_date"), rb.get("maturity_date"))
        eff_months = horizon_months
        if event_date is not None:
            m = _months_between(as_of, event_date)
            if m is not None:
                eff_months = min(float(horizon_months), max(0.0, m))
        eff_factor = eff_months / 12.0

        # (2) Базис: ytm_pct → но если он неправдоподобно высок (yield-to-event,
        # как 414% у put-облигации) → coupon_pct (текущий купонный carry); → xirr → 0.
        ytm_spec = rb.get("ytm_pct")
        coupon_spec = rb.get("coupon_pct")
        has_ytm = ytm_spec is not None and ytm_spec != ""
        has_coupon = coupon_spec is not None and coupon_spec != ""

        if has_ytm and abs(_value(ytm_spec)) > CARRY_YTM_SANITY_PCT and has_coupon:
            return _carry_result(coupon_spec, eff_factor, "coupon_pct")
        if has_ytm:
            return _carry_result(ytm_spec, eff_factor, "ytm_pct")
        if has_coupon:
            return _carry_result(coupon_spec, eff_factor, "coupon_pct")
        xirr = holding.get("xirr")
        if xirr is not None:
            v, clamped = _clamp_carry(float(xirr) * eff_factor)
            return {
                "value": v,
                "ci": [v * 0.85, v * 1.15],
                "source": "xirr_fallback" + ("_capped" if clamped else ""),
            }
        return {"value": 0.0, "ci": [0.0, 0.0], "source": "missing"}

    # equity, fund_*, etc.
    # ── Слой 3 (приоритет №1): dividend_forward — 2-летняя forward-проекция ──
    df = (review_pos or {}).get("dividend_forward")
    if isinstance(df, dict) and df.get("policy_state"):
        return _dividend_forward_contrib(df, horizon_months)
    # Fallback (review без блока): годовой div_yield_12m_pct × h/12
    if review_pos and review_pos.get("div_yield_12m_pct"):
        spec = review_pos["div_yield_12m_pct"]
        return {
            "value": _value(spec) * factor,
            "ci": _scale(_ci(spec), factor),
            "source": "div_yield_12m_pct",
        }
    return {"value": 0.0, "ci": [0.0, 0.0], "source": "none"}


def detect_catalyst_kind(catalyst: dict) -> tuple[str, str | None]:
    """
    Возвращает (kind, legacy_warning).
    - Если поле kind задано явно и валидно — используем. legacy_warning = None.
    - Если поле kind задано, но невалидное → ValueError (не fallback в legacy).
    - Если поле kind отсутствует — fallback на legacy detection:
        - есть upside_by_scenario → quantitative + catalyst_missing_kind
        - есть p + upside_pct (или downside_pct) → binary + catalyst_missing_kind
        - иначе ValueError.
    """
    raw = catalyst.get("kind")
    if raw is not None:
        kind = str(raw).strip().lower()
        if kind in ("binary", "quantitative"):
            return kind, None
        raise ValueError(
            f"Invalid catalyst kind={raw!r} for id={catalyst.get('id')!r}: "
            f"допустимо binary | quantitative"
        )
    # Legacy detection (kind отсутствует)
    if "upside_by_scenario" in catalyst:
        return "quantitative", "catalyst_missing_kind"
    if "p" in catalyst and ("upside_pct" in catalyst or "downside_pct" in catalyst):
        return "binary", "catalyst_missing_kind"
    raise ValueError(
        f"Cannot detect catalyst kind for id={catalyst.get('id')!r}: "
        f"требуется поле kind или legacy-форма (p + upside_pct)"
    )


def _scenario_mass(active_scenarios: list[str] | None, macro_dep: str | None,
                   scenarios: dict,
                   horizon_key: str | None = None) -> tuple[float, bool, str | None]:
    """
    Возвращает (mass, scenario_resolved, fallback_reason).
    - mass = Σ p(s) для s ∈ active_scenarios; либо p(macro_dep) при legacy; либо 1.0 без привязки.
    - scenario_resolved = False если ссылка на неизвестный scenario_id.
    - fallback_reason = "unresolved" | "null_dep" | None.
    """
    def _p(sid: str) -> float:
        s = scenarios.get(sid)
        if not s:
            return 0.0
        return _scenario_p_norm(scenarios, sid, horizon_key)

    if active_scenarios:
        unresolved = [s for s in active_scenarios if s not in scenarios]
        if unresolved:
            return 0.0, False, "unresolved"
        return sum(_p(s) for s in active_scenarios), True, None
    if macro_dep:
        if macro_dep not in scenarios:
            return 0.0, False, "unresolved"
        return _p(macro_dep), True, None
    return 1.0, True, "null_dep"  # scenario-independent


def compute_catalyst_contribution(
    catalyst: dict,
    scenarios: dict,
    horizon_key: str | None = None,
) -> dict:
    """
    Считает E[contribution] + CI для одного catalyst согласно METH-1.

    binary:
      E = p × scenario_mass × upside × src_disc
      где scenario_mass:
        = Σ p(s) для s ∈ active_scenarios (если задан)
        = p(macro_dependency) (legacy)
        = 1.0 (scenario-independent)
      Для null_dep дополнительно применяется NULL_DEPENDENCY_DISCOUNT.

    quantitative:
      E = Σ_s p(s) × upside_by_scenario[s] × src_disc
      Для отсутствующих сценариев в upside_by_scenario подставляется 0.

    Возвращает dict с полями: value, ci, kind, formula, warnings.
    """
    kind, legacy_warning = detect_catalyst_kind(catalyst)
    src_q = (catalyst.get("source_quality") or "").upper()
    src_disc = LOW_QUALITY_DISCOUNT if src_q == "LOW" else 1.0
    warnings: list[str] = []
    if legacy_warning:
        warnings.append(legacy_warning)

    if kind == "binary":
        p_cat = float(catalyst.get("p", 0))
        active = catalyst.get("active_scenarios")
        macro_dep = catalyst.get("macro_dependency")
        # Backward-compat: macro_dep → active_scenarios=[macro_dep]
        # active_scenarios имеет приоритет если оба заданы.
        mass, resolved, fallback = _scenario_mass(active, macro_dep, scenarios,
                                                 horizon_key)
        if not resolved:
            # Unresolved scenario_id — fallback на null-dep дисконт
            warnings.append("scenario_unresolved")
            mass = NULL_DEPENDENCY_DISCOUNT
        elif fallback == "null_dep":
            mass = NULL_DEPENDENCY_DISCOUNT

        # Impact (upside или downside). Ключ с явным null == отсутствие
        # (боевые reviews содержат `upside_pct: null` у downside-катализаторов).
        if catalyst.get("upside_pct") is not None:
            impact = float(catalyst["upside_pct"])
            impact_ci = catalyst.get("upside_ci_pct") or [impact, impact]
        elif catalyst.get("downside_pct") is not None:
            impact = -float(catalyst["downside_pct"])
            d_ci = catalyst.get("downside_ci_pct") or [catalyst["downside_pct"], catalyst["downside_pct"]]
            impact_ci = [-float(d_ci[1]), -float(d_ci[0])]
        else:
            return {
                "value": 0.0, "ci": [0.0, 0.0], "kind": "binary",
                "formula": "skipped: no upside/downside",
                "warnings": warnings + ["missing_impact"],
            }

        factor = p_cat * mass * src_disc
        E = factor * impact
        ci_lo = factor * float(impact_ci[0])
        ci_hi = factor * float(impact_ci[1])
        formula = f"binary: p={p_cat} × mass={mass:.4f} × upside={impact} × src={src_disc}"
        return {
            "value": E,
            "ci": [min(ci_lo, ci_hi), max(ci_lo, ci_hi)],
            "kind": "binary",
            "formula": formula,
            "p": p_cat,
            "scenario_mass": round(mass, 4),
            "warnings": warnings,
        }

    elif kind == "quantitative":
        # p для quant — игнорируется (warning если присутствует)
        if "p" in catalyst and catalyst.get("p") is not None:
            warnings.append("quantitative_has_p_ignored")
        ubs = catalyst.get("upside_by_scenario") or {}
        ucbs = catalyst.get("upside_ci_by_scenario") or {}
        if not ubs:
            return {
                "value": 0.0, "ci": [0.0, 0.0], "kind": "quantitative",
                "formula": "skipped: no upside_by_scenario",
                "warnings": warnings + ["missing_upside_by_scenario"],
            }
        # Cross-check сценарных ID
        unknown_ids = [k for k in ubs.keys() if k not in scenarios]
        if unknown_ids:
            warnings.append(f"unknown_scenario_ids:{','.join(unknown_ids)}")
        missing_ids = [k for k in scenarios.keys() if k not in ubs]
        if missing_ids:
            warnings.append(f"missing_scenarios_zeroed:{','.join(missing_ids)}")

        E = 0.0
        ci_lo = 0.0
        ci_hi = 0.0
        for s_id, s_data in scenarios.items():
            p_s = _scenario_p_norm(scenarios, s_id, horizon_key)
            up_s = float(ubs.get(s_id, 0))
            ci_s = ucbs.get(s_id) or [up_s, up_s]
            E += p_s * up_s * src_disc
            ci_lo += p_s * float(ci_s[0]) * src_disc
            ci_hi += p_s * float(ci_s[1]) * src_disc
        formula = "quantitative: Σ_s p(s) × upside_s × src"
        return {
            "value": E,
            "ci": [min(ci_lo, ci_hi), max(ci_lo, ci_hi)],
            "kind": "quantitative",
            "formula": formula,
            "scenario_mass": 1.0,
            "warnings": warnings,
        }

    else:
        raise ValueError(f"Unknown catalyst kind: {kind!r}")


def aggregate_idio(
    review_pos: dict | None,
    scenarios: dict,
    trust_matrix: dict | None,
    horizon_end: date | None = None,
    horizon_key: str | None = None,
) -> dict:
    """
    horizon_end is None (default) → без фильтра по горизонту (direct-call тесты).
    horizon_end задан → принадлежность горизонту по date_window
    (§11.3): катализатор вне горизонта, если начало окна > horizon_end.
    """
    if not review_pos:
        return {
            "value": 0.0,
            "ci": [0.0, 0.0],
            "catalysts_applied": [],
            "ignored_catalysts": [],
        }
    applied: list[dict] = []
    ignored: list[dict] = []
    total = 0.0
    ci_lo = 0.0
    ci_hi = 0.0
    for c in (review_pos.get("catalyst") or []):
        in_h, dw_warn = _catalyst_in_horizon(c, horizon_end)
        if not in_h:
            ignored.append({"id": c.get("id"), "reason": "out_of_horizon"})
            continue
        if is_low_trust(c, trust_matrix):
            ignored.append({"id": c.get("id"), "reason": "trust_ignore"})
            continue
        try:
            contrib = compute_catalyst_contribution(c, scenarios, horizon_key)
        except ValueError as e:
            ignored.append({"id": c.get("id"), "reason": f"invalid_kind: {e}"})
            continue
        total += contrib["value"]
        ci_lo += contrib["ci"][0]
        ci_hi += contrib["ci"][1]
        warns = list(contrib.get("warnings", []))
        if dw_warn:
            warns.append(dw_warn)
        applied.append({
            "id": c.get("id"),
            "kind": contrib["kind"],
            "value": round(contrib["value"], 4),
            "ci": [round(contrib["ci"][0], 4), round(contrib["ci"][1], 4)],
            "formula": contrib["formula"],
            "warnings": warns,
        })
    return {
        "value": total,
        "ci": [min(ci_lo, ci_hi), max(ci_lo, ci_hi)],
        "catalysts_applied": applied,
        "ignored_catalysts": ignored,
    }


def _detect_on_iis(holding: dict, stress_pos: dict | None) -> bool:
    """
    Метка ИИС-3 по всем доступным сигналам (OR): явное поле payload → флаг stress
    (там позиция уже схлопнута по счетам) → `account` строки снапшота → список
    `accounts_merged`, который проставил merge_duplicate_holdings.
    """
    if holding.get("on_iis"):
        return True
    if stress_pos and stress_pos.get("on_iis"):
        return True
    if str(holding.get("account") or "") == "iis_3":
        return True
    merged = holding.get("accounts_merged")
    return isinstance(merged, list) and "iis_3" in [str(a) for a in merged]


def aggregate_position(
    holding: dict,
    stress_per_position: dict,
    review_stocks: dict,
    review_bonds: dict | None,
    scenarios: dict,
    trust_matrix: dict | None,
    horizons: list[int],
    horizon_ends: dict[str, str | None] | None = None,
    macro_marginal: dict | None = None,
    as_of: date | None = None,
    baseline_spot: dict | None = None,
    horizon_years: dict[str, int] | None = None,
    primary_horizon: int | None = None,
    carry_lookup: dict | None = None,
    blindspot_table: dict | None = None,
) -> dict:
    ticker = holding["ticker"]
    # Поддержка двух schema: asset_class (новая) и asset_type (legacy snapshot)
    asset_class = holding.get("asset_class")
    if not asset_class:
        # Translate asset_type → asset_class
        at = holding.get("asset_type")
        if at == "stock":
            asset_class = "equity"
        elif at == "bond":
            asset_class = "bond"
        elif at == "fund":
            asset_class = "fund_unknown"
        else:
            asset_class = "equity"  # safe default
    stress_pos = stress_per_position.get(ticker)
    review_pos = _get(review_stocks, "per_stock", ticker) if review_stocks else None
    review_bond_pos = _get(review_bonds, "per_bond", ticker) if review_bonds else None
    # idio для облигаций может быть из review_bonds (catalyst block там тоже бывает)
    idio_review = review_pos if review_pos else review_bond_pos
    horizon_years = horizon_years or {}
    horizon_ends = horizon_ends or {}
    carry_entry = (carry_lookup or {}).get(ticker)
    carry_kind = (carry_entry or {}).get("kind")

    # V2-A: каждый горизонт независимо (беты/factors зависят от горизонта; div/carry × h/12;
    # катализаторы — по date_window против конца горизонта). Беты плоские, общие на горизонты.
    by_horizon: dict[str, Any] = {}
    for h in horizons:
        hk = f"h{h}"
        # date_window in-horizon (конец горизонта)
        he = _parse_iso_date(horizon_ends.get(hk))
        stress_pos_h = _stress_pos_for_horizon(stress_pos, hk)
        macro = aggregate_macro(stress_pos_h, macro_marginal,
                                baseline_spot=baseline_spot, horizon_year=horizon_years.get(hk))
        # PIV-5: метка слепого пятна берётся из ДВУХ источников. Булев
        # per_position.macro_blindspot ставит скрипт стресса механически (R² / |beta| /
        # список идиосинкратических тикеров) — в прогоне 08-15 он стоял у 4 позиций из 68.
        # Таблица stress.macro_blindspots — разметка границ, которую пишет модель стресса,
        # и она шире: вердикты MIXED / IDIOSYNCRATIC_DOMINATES покрывали 24 позиции ≈39,5%
        # портфеля. Читать только флаг = показать 6% вместо 39,5%.
        bs_verdict = (blindspot_table or {}).get(ticker)
        if bs_verdict in BLINDSPOT_TABLE_VERDICTS and not macro["blindspot"]:
            macro["blindspot"] = True
            macro["blindspot_source"] = "stress_table"
        elif macro["blindspot"]:
            macro["blindspot_source"] = "position_flag"
        if bs_verdict is not None:
            macro["blindspot_verdict"] = bs_verdict
        carry_slot = ((carry_entry or {}).get("by_horizon") or {}).get(hk)
        divc = aggregate_div_or_carry(asset_class, review_pos, review_bond_pos,
                                      holding, h, as_of,
                                      carry_slot=carry_slot, carry_kind=carry_kind,
                                      scenarios=scenarios)
        idio = aggregate_idio(idio_review, scenarios, trust_matrix, horizon_end=he,
                              horizon_key=hk)
        macro_v = macro["value"] if macro["value"] is not None else 0.0
        macro_ci = macro["ci"] if macro["ci"][0] is not None else [0.0, 0.0]
        by_horizon[hk] = {
            "macro": macro,
            "div_or_carry": divc,
            "idio": idio,
            "total": {
                "value": macro_v + divc["value"] + idio["value"],
                "ci": [macro_ci[0] + divc["ci"][0] + idio["ci"][0],
                       macro_ci[1] + divc["ci"][1] + idio["ci"][1]],
            },
        }

    # weight ALWAYS from stress (R-SNAP)
    weight_pct = float(stress_pos.get("weight_pct")) if stress_pos and stress_pos.get("weight_pct") is not None else None

    verdict = (review_pos or review_bond_pos or {}).get("advisor_verdict", "NOT_REVIEWED")
    verdict = _check_verdict(verdict, ticker)
    priority = (review_pos or review_bond_pos or {}).get("verification_priority",
                                                          "HIGH" if verdict == "NOT_REVIEWED" else "MEDIUM")

    entry = {
        "ticker": ticker,
        "asset_class": asset_class,
        "weight_pct": weight_pct,
        "weight_source": "stress" if weight_pct is not None else "missing",
        "currency": holding.get("currency"),
        "is_blocked": bool(holding.get("is_blocked", False)),
        # ИИС-3 (PIV-5): снапшот portfolio-data-loader поля on_iis НЕ пишет — там
        # `account: "iis_3"`. Читать только holding["on_iis"] значило молча терять метку
        # ❄ и правило R10 (прогон 08-15: 0 позиций вместо 6, без единого warning).
        # Логика OR по всем сигналам — по правилу «on_iis = True, если ЛЮБАЯ часть
        # позиции на ИИС-3»: ошибка возможна только в безопасную сторону (лишнее
        # ограничение вердикта, а не потерянное).
        "on_iis": _detect_on_iis(holding, stress_pos),
        "by_horizon": by_horizon,
        "verdict": verdict,
        "verification_priority": priority,
    }
    # Дублирование primary-горизонта в плоские поля (совместимость viewer/прозы).
    pk = f"h{primary_horizon}" if (primary_horizon is not None and f"h{primary_horizon}" in by_horizon) \
        else next(iter(by_horizon))
    prim = by_horizon[pk]
    entry["macro"] = prim["macro"]
    entry["div_or_carry"] = prim["div_or_carry"]
    entry["idio"] = prim["idio"]
    entry["total"] = prim["total"]
    entry["primary_horizon_key"] = pk
    return entry


# ───────────────────── Шаг 4: portfolio aggregates ─────────────────────

def _weighted_total(positions: list[dict]) -> tuple[float | None, list[float], float]:
    items = [p for p in positions
             if p["weight_pct"] is not None and not p["is_blocked"]]
    if not items:
        return None, [0.0, 0.0], 0.0
    total_w = sum(p["weight_pct"] for p in items)
    if total_w <= 0:
        return None, [0.0, 0.0], 0.0
    val = sum(p["weight_pct"] * p["total"]["value"] for p in items) / total_w
    lo = sum(p["weight_pct"] * p["total"]["ci"][0] for p in items) / total_w
    hi = sum(p["weight_pct"] * p["total"]["ci"][1] for p in items) / total_w
    return val, [lo, hi], total_w


def _weighted_l1_point(positions: list[dict]) -> float | None:
    """Взвешенная L1-точка ноги (@1.4): total с macro-центром из L1-overlay.

    Позиции без l1_total входят своим каноническим total (L1 у них не считался).
    None, если ни одна позиция не несёт L1-точку. Информационное поле — НЕ
    участвует в headline/spread/CI."""
    items = [p for p in positions
             if p["weight_pct"] is not None and not p["is_blocked"]]
    if not items or not any(p.get("l1_total") is not None for p in items):
        return None
    total_w = sum(p["weight_pct"] for p in items)
    if total_w <= 0:
        return None
    val = sum(
        p["weight_pct"] * (p["l1_total"] if p.get("l1_total") is not None
                           else p["total"]["value"])
        for p in items
    ) / total_w
    return round(val, 4)


def compute_portfolio_aggregates(per_position: list[dict], horizon_months: int) -> dict:
    equity = [p for p in per_position if p["asset_class"] in ("equity", "fund_equity", "fund_gold", "fund_unknown")]
    bond = [p for p in per_position if p["asset_class"] in ("bond", "fund_bond")]

    eq_v, eq_ci, eq_w = _weighted_total(equity)
    bd_v, bd_ci, bd_w = _weighted_total(bond)
    eq_l1 = _weighted_l1_point(equity)
    bd_l1 = _weighted_l1_point(bond)

    # Аннуализация — ГЕОМЕТРИЧЕСКАЯ (сложный %, 2026-07): (1+r)^(12/h) − 1.
    # Честное сравнение с YTM/депозитом (те compounded); линейная ×12/h завышала
    # на длинных горизонтах (55.2% за 24 мес: линейно 27.6%/год vs 24.6% сложным).
    # На h=12 методы совпадают. Вьюер ≥2.6.3 считает ту же формулу (annualizedPct).
    exp = 12.0 / horizon_months

    def _ann_one(x: float) -> float | None:
        base = 1.0 + x / 100.0
        if base <= 0:
            return None  # потеря ≥100% за горизонт — аннуализация не определена
        return (base ** exp - 1.0) * 100.0

    def annualize(v: float | None, ci: list[float]) -> dict:
        if v is None:
            return {"value": None, "ci": [None, None]}
        return {"value": _ann_one(v),
                "ci": [_ann_one(ci[0]), _ann_one(ci[1])],
                "method": "geometric"}

    out = {
        "equity": {
            "weight_pct": eq_w,
            "expected_pct_horizon": {"value": eq_v, "ci": eq_ci},
            "expected_pct_annualized": annualize(eq_v, eq_ci),
        },
        "bond": {
            "weight_pct": bd_w,
            "expected_pct_horizon": {"value": bd_v, "ci": bd_ci},
            "expected_pct_annualized": annualize(bd_v, bd_ci),
        },
    }
    # @1.4: L1-overlay точка ноги — информационная альтернатива каноническому
    # центру (macro-marginal × беты вместо L2 p-weighted). НЕ входит в
    # headline value / spread / CI — только для coherence-анализа (§3).
    for bucket, l1 in (("equity", eq_l1), ("bond", bd_l1)):
        if l1 is not None:
            out[bucket]["l1_point"] = {
                "value": l1,
                "note": "L1-overlay (macro-marginal × беты); не входит в "
                        "headline/spread/CI",
            }

    if eq_v is not None and bd_v is not None:
        spread = eq_v - bd_v
        # Линейный CI (corr=1): [eq_lo - bd_hi, eq_hi - bd_lo]
        spread_ci_linear = [eq_ci[0] - bd_ci[1], eq_ci[1] - bd_ci[0]]
        # Квадратурный CI (corr=0): σ ≈ width/4
        sigma_eq = (eq_ci[1] - eq_ci[0]) / 4.0
        sigma_bd = (bd_ci[1] - bd_ci[0]) / 4.0
        sigma_spread = math.sqrt(sigma_eq * sigma_eq + sigma_bd * sigma_bd)
        spread_ci_quad = [spread - 2 * sigma_spread, spread + 2 * sigma_spread]
        out["spread_pp_horizon"] = {
            "point": spread,
            "ci_linear": spread_ci_linear,
            "ci_quadratic": spread_ci_quad,
        }
    else:
        out["spread_pp_horizon"] = None

    return out


# ───────────────────── Diff with previous view (IV-A) ─────────────────────

def compute_diff(per_position: list[dict], previous_view: list[dict] | None) -> dict | None:
    """
    Сравнивает текущий per_position с прошлым integrated-view.
    previous_view — список облегчённых записей: {ticker, weight_pct, verdict, total_value,
    verification_priority}. Передаётся из payload["previous_view"].
    Возвращает None если previous_view не предоставлен.
    """
    if not previous_view:
        return None

    prev_by_ticker = {p["ticker"]: p for p in previous_view if p.get("ticker")}
    curr_by_ticker = {p["ticker"]: p for p in per_position if p.get("ticker")}

    rows: list[dict] = []
    new_high_priority: list[str] = []
    verdict_changes: list[dict] = []
    large_moves: list[dict] = []

    # Текущие позиции
    for ticker, curr in curr_by_ticker.items():
        prev = prev_by_ticker.get(ticker)
        if prev is None:
            marker = "+"
        else:
            marker = "="

        curr_total = (curr.get("total") or {}).get("value")
        prev_total = prev.get("total_value") if prev else None
        curr_verdict = curr.get("verdict")
        prev_verdict = prev.get("verdict") if prev else None
        curr_prio = curr.get("verification_priority")

        rows.append({
            "ticker": ticker,
            "marker": marker,
            "verdict": curr_verdict,
            "total_value": curr_total,
            "verification_priority": curr_prio,
        })

        if marker == "+" and curr_prio == "HIGH":
            new_high_priority.append(ticker)

        if marker == "=" and curr_verdict != prev_verdict:
            verdict_changes.append({
                "ticker": ticker,
                "from": prev_verdict,
                "to": curr_verdict,
            })

        if (
            marker == "="
            and curr_total is not None
            and prev_total is not None
            and abs(curr_total - prev_total) > 5.0
        ):
            large_moves.append({
                "ticker": ticker,
                "prev": prev_total,
                "curr": curr_total,
                "delta": curr_total - prev_total,
            })

    # Ушедшие позиции
    for ticker in prev_by_ticker:
        if ticker not in curr_by_ticker:
            rows.append({
                "ticker": ticker,
                "marker": "-",
                "verdict": prev_by_ticker[ticker].get("verdict"),
                "total_value": prev_by_ticker[ticker].get("total_value"),
                "verification_priority": prev_by_ticker[ticker].get("verification_priority"),
            })

    return {
        "rows": rows,
        "new_high_priority": new_high_priority,
        "verdict_changes": verdict_changes,
        "large_moves": large_moves,
        "total_added": sum(1 for r in rows if r["marker"] == "+"),
        "total_removed": sum(1 for r in rows if r["marker"] == "-"),
        "total_changed": len(verdict_changes) + len(large_moves),
    }


# ───────────────────── Sanity checks (IV-C) ─────────────────────

def sanity_checks(per_position: list[dict], portfolio: dict) -> list[dict]:
    """
    Блокирующие HIGH-warning проверки до генерации output.
    Ловят баги и испорченные данные:
    - любой total.value > 100 или < -100
    - ширина CI > 100 п.п.
    - Σweight_pct (stress-источник) ≠ 100 ± 0.5
    """
    warnings: list[dict] = []

    for pos in per_position:
        ticker = pos.get("ticker", "?")
        total = pos.get("total") or {}
        val = total.get("value")
        ci = total.get("ci") or [None, None]

        if val is not None and (val > 100 or val < -100):
            warnings.append({
                "type": "extreme_total_pct",
                "severity": "HIGH",
                "ticker": ticker,
                "value": val,
                "message": f"{ticker}: total.value={val:.1f}% выходит за пределы ±100%",
            })

        if ci[0] is not None and ci[1] is not None:
            width = ci[1] - ci[0]
            if width > 100:
                warnings.append({
                    "type": "extreme_ci_width",
                    "severity": "HIGH",
                    "ticker": ticker,
                    "ci_width": width,
                    "message": f"{ticker}: CI width={width:.1f}pp > 100pp",
                })

    # Σ weight_pct от stress-позиций (пропускаем если есть missing — сумма законно < 100)
    has_missing = any(p.get("weight_source") == "missing" for p in per_position)
    stress_weights = [
        p["weight_pct"]
        for p in per_position
        if p.get("weight_source") == "stress" and p.get("weight_pct") is not None
    ]
    if stress_weights and not has_missing:
        w_sum = sum(stress_weights)
        if abs(w_sum - 100) > 0.5:
            warnings.append({
                "type": "weight_sum_off",
                "severity": "HIGH",
                "weight_sum": w_sum,
                "message": f"Σ weight_pct (stress) = {w_sum:.2f}% ≠ 100 ± 0.5",
            })

    # Проверяем портфельные агрегаты
    for bucket in ("equity", "bond"):
        b = (portfolio or {}).get(bucket) or {}
        h = b.get("expected_pct_horizon") or {}
        bval = h.get("value")
        bci = h.get("ci") or [None, None]
        if bval is not None and (bval > 100 or bval < -100):
            warnings.append({
                "type": "extreme_total_pct",
                "severity": "HIGH",
                "ticker": f"portfolio_{bucket}",
                "value": bval,
                "message": f"portfolio.{bucket}: expected={bval:.1f}% выходит за ±100%",
            })
        if bci[0] is not None and bci[1] is not None:
            width = bci[1] - bci[0]
            if width > 100:
                warnings.append({
                    "type": "extreme_ci_width",
                    "severity": "HIGH",
                    "ticker": f"portfolio_{bucket}",
                    "ci_width": width,
                    "message": f"portfolio.{bucket}: CI width={width:.1f}pp > 100pp",
                })

    return warnings


# ───────────────────── Tail-risk флаги (output schema @1.2) ─────────────────────

def compute_tail_flags(
    per_position: list[dict],
    portfolio: dict | None = None,
    thresholds: dict | None = None,
) -> dict:
    """
    Детерминированный пост-процессинг поверх УЖЕ посчитанных per_position чисел.
    Никакого нового моделирования, никаких новых входных данных.

    ВАЖНО (принципиальная оговорка — R1): CI в этом скилле — НЕ подогнанное
    распределение, а методологическая полоса (corr=1 линейная / corr=0
    квадратурная — SKILL.md R1). Поэтому «хвост» здесь — ЭВРИСТИЧЕСКИЙ
    указатель внимания, а НЕ VaR. Не превращать флаги в tail-метрику с мнимой
    точностью — это нарушит принцип R1 (CI = honesty, не phantom precision).

    Три ОРТОГОНАЛЬНЫХ флага (позиция может зажечь несколько), каждый
    маршрутизирует к РАЗНОМУ decision-response:

      Флаг 1 «БИНАРНЫЙ» (скос точки)
        skew = max(up_arm/down_arm, down_arm/up_arm) > skew_threshold,
        где up_arm = hi − value, down_arm = value − lo (плечи CI).
        Срабатывает независимо от размера позиции. Ставит маркер ⚡ к строке §3.

      Флаг 2 «ЗНАК НЕ РАЗРЕШЁН» (zero-cross × материальный вес)
        lo < 0 < hi  И  weight_pct ≥ weight_floor_pct.

      Флаг 3 «ХВОСТ ПОРТФЕЛЯ» (вклад в нижний хвост)
        contrib_down_i = (weight_pct_i / 100) × max(0, value_i − lo_i),
        только для позиций с lo_i < 0 (реальный loss-хвост, иначе 0).
        Условие: contrib_down_i / Σ contrib_down > tail_share_threshold,
        И Σ contrib_down ≥ portfolio_tail_floor (anti-fatigue materiality).
        Cap: максимум топ-N (tail_cap) контрибьюторов.

    Единицы: weight_pct в per_position — проценты (напр. 2.51 = 2.51%).
    contrib_down — в «пп·доля»: доля портфеля (weight_pct/100) × ширина
    нижнего плеча CI в пп.

    portfolio — принимается для совместимости сигнатуры (портфельные агрегаты
    уже доступны), в текущей версии не используется напрямую.

    Возвращает dict: {flags, portfolio_downside, thresholds, fired}.
    """
    th = {
        "skew_threshold": TAIL_SKEW_THRESHOLD,
        "weight_floor_pct": TAIL_WEIGHT_FLOOR_PCT,
        "tail_share_threshold": TAIL_SHARE_THRESHOLD,
        "portfolio_tail_floor": PORTFOLIO_TAIL_FLOOR,
        "tail_cap": TAIL_CAP,
    }
    if thresholds:
        th.update(thresholds)

    def _vals(p: dict):
        """(value, lo, hi, weight_pct) или None если blocked/нет чисел."""
        if p.get("is_blocked"):
            return None
        total = p.get("total") or {}
        val = total.get("value")
        ci = total.get("ci") or [None, None]
        lo = ci[0] if len(ci) > 0 else None
        hi = ci[1] if len(ci) > 1 else None
        if val is None or lo is None or hi is None:
            return None
        w = p.get("weight_pct")
        return float(val), float(lo), float(hi), (float(w) if w is not None else None)

    flags: list[dict] = []

    # ── Σ contrib_down по портфелю (materiality для Флага 3) ──
    contribs: list[dict] = []
    total_contrib_down = 0.0
    for p in per_position:
        v = _vals(p)
        if v is None:
            continue
        val, lo, hi, w = v
        if w is None or lo >= 0:
            continue  # нет веса или нет реального loss-хвоста
        contrib = (w / 100.0) * max(0.0, val - lo)
        if contrib <= 0:
            continue
        contribs.append({"ticker": p.get("ticker"), "contrib_down": contrib})
        total_contrib_down += contrib

    # ── Флаг 1 + Флаг 2 (per-position) ──
    for p in per_position:
        v = _vals(p)
        if v is None:
            continue
        val, lo, hi, w = v
        ticker = p.get("ticker")
        up_arm = hi - val
        down_arm = val - lo

        # Флаг 1 — БИНАРНЫЙ (скос точки)
        skew = None
        direction = None
        if down_arm > 0 and (up_arm / down_arm) > th["skew_threshold"]:
            skew = up_arm / down_arm
            direction = "вверх"
        elif up_arm > 0 and (down_arm / up_arm) > th["skew_threshold"]:
            skew = down_arm / up_arm
            direction = "вниз"
        if skew is not None:
            flags.append({
                "ticker": ticker,
                "type": "БИНАРНЫЙ",
                "code": "binary_skew",
                "marker": "⚡",
                "skew": round(skew, 2),
                "direction": direction,
                "severity": "MEDIUM",
                "action": (
                    "Точка неинформативна (схлопнутый бимодальный payoff). "
                    "Читать сценарную матрицу stress-{date}-*.yaml → "
                    f"per_position.{ticker}.by_scenario, не точку."
                ),
            })

        # Флаг 2 — ЗНАК НЕ РАЗРЕШЁН (zero-cross × материальный вес)
        if lo < 0 < hi and w is not None and w >= th["weight_floor_pct"]:
            flags.append({
                "ticker": ticker,
                "type": "ЗНАК НЕ РАЗРЕШЁН",
                "code": "sign_unresolved",
                "weight_pct": round(w, 2),
                "severity": "HIGH",
                "action": (
                    f"Знак доходности на значимой позиции (доля {w:.2f}%) "
                    "не разрешён интервалом — это реальный риск, не шум. "
                    "Учесть при сайзинге."
                ),
            })

    # ── Флаг 3 — ХВОСТ ПОРТФЕЛЯ (materiality floor + cap top-N) ──
    if total_contrib_down >= th["portfolio_tail_floor"] and total_contrib_down > 0:
        ranked = sorted(contribs, key=lambda c: c["contrib_down"], reverse=True)
        fired = [
            (c, c["contrib_down"] / total_contrib_down)
            for c in ranked
            if (c["contrib_down"] / total_contrib_down) > th["tail_share_threshold"]
        ][: th["tail_cap"]]
        for c, share in fired:
            flags.append({
                "ticker": c["ticker"],
                "type": "ХВОСТ ПОРТФЕЛЯ",
                "code": "portfolio_tail",
                "share_pct": round(share * 100, 1),
                "contrib_down": round(c["contrib_down"], 3),
                "severity": "MEDIUM",
                "action": (
                    f"Нижний хвост портфеля сконцентрирован здесь "
                    f"({share * 100:.1f}% вклада). Сюда смотреть, если хочешь "
                    "сузить хвост (хедж/трим)."
                ),
            })

    return {
        "flags": flags,
        "portfolio_downside": round(total_contrib_down, 3),
        "thresholds": th,
        "fired": len(flags) > 0,
    }


# ─────────────────────────────── main ───────────────────────────────

def _predictions_for_review(
    review_stocks: dict, review_bonds: dict | None,
    horizons: list[int], horizon_ends: dict[str, str | None],
) -> list[dict]:
    """Единый dedup-список катализаторов с полем horizons: [...] (в каких горизонтах активен)."""
    out: list[dict] = []

    def _collect(coll: dict):
        for ticker, rec in (coll or {}).items():
            if not isinstance(rec, dict):
                continue
            for c in (rec.get("catalyst") or []):
                hs = []
                for h in horizons:
                    he = _parse_iso_date(horizon_ends.get(f"h{h}"))
                    in_h, _ = _catalyst_in_horizon(c, he)
                    if in_h:
                        hs.append(h)
                if hs:
                    out.append({
                        "ticker": ticker,
                        "catalyst_id": c.get("id"),
                        "trigger": c.get("trigger"),
                        "date_window": c.get("date_window"),
                        "horizons": hs,
                    })

    _collect(_get(review_stocks, "per_stock", default={}) or {})
    _collect(_get(review_bonds, "per_bond", default={}) or {})
    return out


# ───────────────── Total return: price + carry + dividend (3 слоя) ─────────────────

def _sanctions_intensity(stress_scenarios: dict, sid: str, hk: str) -> float:
    fbh = ((stress_scenarios or {}).get(sid) or {}).get("factors_by_horizon") or {}
    v = (fbh.get(hk) or {}).get("sanctions")
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def compute_total_return_by_horizon(
    per_position: list[dict],
    stress_per_position: dict,
    stress_scenarios: dict,
    scenarios: dict,
    horizons: list[int],
    snapshot: dict,
    carry_lookup: dict | None,
    div_sanctions_haircut: float | None = None,
) -> dict | None:
    """
    total_return[hNN][scenario] = price_delta + bond_carry + dividend_income
    (§7 total-return). Идиосинкратика НЕ входит в сценарную декомпозицию
    (METH-1 живёт в per_position.total и portfolio_by_horizon) — блок несёт
    явную note об этом. Требует per-scenario срезы by_horizon; без них → None.

    Бакеты: equity / bond / cash (CASH_RUB + kind=cash|money_market? нет:
    MM-фонды остаются в своём бакете per_position; cash-бакет = CASH_RUB из
    carry-блока). Веса: позиции — stress weight_pct (R-SNAP); кэш — по
    value_rub снапшота, базис пересчёта задокументирован в weights_basis.

    div_sanctions_haircut (решение C): в сценариях с sanctions ≥
    SANCTIONS_INTENSITY_MIN дивидендный поток × (1 − haircut). None → выключен.
    """
    # v2-stress обязателен: нужны per-scenario значения на горизонт
    if not any(isinstance((p or {}).get("by_horizon"), dict)
               for p in (stress_per_position or {}).values()):
        return None

    pp_by_ticker = {p["ticker"]: p for p in per_position if p.get("ticker")}
    cash_entry = (carry_lookup or {}).get("CASH_RUB")
    cash_rub = float(_get(snapshot, "cash", "total_rub", default=0) or 0)
    holdings_value = sum(
        float(h.get("value_rub") or 0)
        for h in (snapshot.get("holdings") or [])
        if not h.get("is_blocked") and (h.get("value_rub") or 0) > 0
    )

    out: dict[str, Any] = {}
    haircut_applied: set[str] = set()
    for h in horizons:
        hk = f"h{h}"
        by_scenario: dict[str, dict] = {}
        for sid in scenarios:
            sums = {"equity": [0.0, 0.0], "bond": [0.0, 0.0]}  # [Σw×r, Σw]
            sanc = _sanctions_intensity(stress_scenarios, sid, hk)
            div_hc = (div_sanctions_haircut
                      if (div_sanctions_haircut and sanc >= SANCTIONS_INTENSITY_MIN)
                      else 0.0)
            for p in per_position:
                if p.get("is_blocked") or p.get("weight_pct") is None:
                    continue
                t = p["ticker"]
                slot = (p.get("by_horizon") or {}).get(hk) or {}
                bucket = ("bond" if p.get("asset_class") in _BOND_CLASSES
                          else "equity" if p.get("asset_class") in _EQUITY_CLASSES
                          else None)
                if bucket is None:
                    continue
                # Слой 1: price per scenario (maturity guard уже внутри stress)
                stress_pos = stress_per_position.get(t) or {}
                sslot = ((stress_pos.get("by_horizon") or {}).get(hk)) or {}
                dcell = (sslot.get("delta_pct_by_scenario") or {}).get(sid)
                price = _value(dcell, 0.0)
                # Слой 2/3: carry per scenario (bond_carry) либо div (сценарно-
                # независимый, ± haircut в санкционных сценариях)
                divc = slot.get("div_or_carry") or {}
                cells = divc.get("by_scenario")
                if isinstance(cells, dict) and sid in cells:
                    income = float((cells[sid] or {}).get("carry_pct", 0) or 0)
                else:
                    income = float(divc.get("value", 0) or 0)
                    if div_hc and bucket == "equity" and income > 0:
                        income *= (1.0 - div_hc)
                        haircut_applied.add(f"{hk}/{sid}")
                w = float(p["weight_pct"])
                sums[bucket][0] += w * (price + income)
                sums[bucket][1] += w
            row: dict[str, Any] = {}
            for b in ("equity", "bond"):
                row[b] = round(sums[b][0] / sums[b][1], 4) if sums[b][1] > 0 else None
            # cash-бакет: CASH_RUB из carry-блока (КС-траектория, допущение MM)
            cash_r = None
            if cash_entry:
                cell = (((cash_entry.get("by_horizon") or {}).get(hk) or {})
                        .get("by_scenario") or {}).get(sid)
                if cell is not None:
                    cash_r = float((cell or {}).get("carry_pct", 0) or 0)
            row["cash"] = cash_r
            # портфель целиком: стоимостной базис снапшота — V (позиции) + C (кэш)
            num = den = 0.0
            pos_num = sum(sums[b][0] for b in ("equity", "bond"))
            pos_den = sum(sums[b][1] for b in ("equity", "bond"))
            if pos_den > 0 and holdings_value > 0:
                num = holdings_value * (pos_num / pos_den)
                den = holdings_value
            if cash_r is not None and cash_rub > 0:
                num += cash_rub * cash_r
                den += cash_rub
            row["portfolio"] = round(num / den, 4) if den > 0 else None
            by_scenario[sid] = row

        # p-weighted expected по бакетам
        expected: dict[str, Any] = {}
        for b in ("equity", "bond", "cash", "portfolio"):
            vals = [(sid, by_scenario[sid].get(b)) for sid in by_scenario]
            known = [(sid, v) for sid, v in vals if v is not None]
            if not known:
                expected[b] = None
                continue
            tp = sum(_scenario_p_norm(scenarios, sid, hk) for sid, _ in known) or len(known)
            expected[b] = round(
                sum((_scenario_p_norm(scenarios, sid, hk) or 1.0 / len(known)) * v
                    for sid, v in known) / (tp if tp > 0 else 1.0), 4)

        # Три полосы (layers): p-weighted value+CI на бакет по слоям
        layers: dict[str, Any] = {}
        for b, classes in (("equity", _EQUITY_CLASSES), ("bond", _BOND_CLASSES)):
            acc = {"price": [0.0, 0.0, 0.0], "income": [0.0, 0.0, 0.0],
                   "idio": [0.0, 0.0, 0.0]}
            wsum = 0.0
            for p in per_position:
                if (p.get("is_blocked") or p.get("weight_pct") is None
                        or p.get("asset_class") not in classes):
                    continue
                slot = (p.get("by_horizon") or {}).get(hk) or {}
                w = float(p["weight_pct"])
                wsum += w
                for key, src in (("price", "macro"), ("income", "div_or_carry"),
                                 ("idio", "idio")):
                    layer = slot.get(src) or {}
                    v = layer.get("value")
                    ci = layer.get("ci") or [None, None]
                    acc[key][0] += w * float(v or 0)
                    acc[key][1] += w * float(ci[0] if ci[0] is not None else (v or 0))
                    acc[key][2] += w * float(ci[1] if ci[1] is not None else (v or 0))
            if wsum > 0:
                layers[b] = {
                    key: {"value": round(a[0] / wsum, 4),
                          "ci": [round(a[1] / wsum, 4), round(a[2] / wsum, 4)]}
                    for key, a in acc.items()
                }
        # человекочитаемые имена слоёв дохода
        if "bond" in layers:
            layers["bond"]["income_kind"] = "carry"
        if "equity" in layers:
            layers["equity"]["income_kind"] = "dividend"
        if cash_entry:
            ch = (cash_entry.get("by_horizon") or {}).get(hk) or {}
            layers["cash"] = {"income": {"value": ch.get("expected_carry_pct")},
                              "income_kind": "mm_rate",
                              "flags": ch.get("flags", [])}

        out[hk] = {"by_scenario": by_scenario, "expected": expected, "layers": layers}

    return {
        "by_horizon": out,
        "weights_basis": ("позиции — stress weight_pct (R-SNAP, % от non-cash "
                          "unblocked); портфель — стоимостной базис снапшота: "
                          f"holdings {round(holdings_value)} ₽ + кэш {round(cash_rub)} ₽"),
        "note": ("by_scenario = price_delta + bond_carry + dividend "
                 "(БЕЗ идиосинкратики — она в per_position.total и "
                 "portfolio_by_horizon по METH-1)"),
        "div_sanctions_haircut": (
            {"haircut": div_sanctions_haircut,
             "applied_in": sorted(haircut_applied)}
            if div_sanctions_haircut else None),
        "cash_included": cash_entry is not None and cash_rub > 0,
    }


SPREAD_SWITCH_SLOPE_EPS = 1e-12


def compute_spread_switch_thresholds(total_return: dict | None,
                                     scenarios: dict) -> dict | None:
    """
    Пороги переключения знака спреда «акции − облигации» по весу одного сценария
    (шаг 4 разбора 2026-10-07; та же модель, что PSS-6 reweight_stress.sensitivity).

    Модель: вес сценария s едет 0→1, остальные сохраняют взаимные пропорции текущих
    весов и делят остаток. Спред внутри сценария V_s от весов не зависит, поэтому
    S(w) = w·V_s + (1 − w)·M_s линейна, а порог — замкнутая форма
    w* = −M_s / (V_s − M_s); вне [0, 1] → None («знак не меняется ни при каком весе»).

    БАЗА — `total_return_by_horizon.by_scenario` (цена + carry + дивиденды) БЕЗ
    идиосинкратики: идио-слой в сценарную декомпозицию не входит (METH-1). Поэтому
    `spread_now` здесь — не headline-спред §2 (с идио), это напечатано в `basis`.
    Порог считается по точке, не по CI.
    """
    by_h = (total_return or {}).get("by_horizon") or {}
    if not by_h:
        return None
    out: dict[str, Any] = {}
    for hk, block in by_h.items():
        rows = (block or {}).get("by_scenario") or {}
        spreads = {
            sid: float(r["equity"]) - float(r["bond"])
            for sid, r in rows.items()
            if r and r.get("equity") is not None and r.get("bond") is not None
        }
        if len(spreads) < 2:
            continue
        raw = {sid: max(_scenario_p_norm(scenarios, sid, hk), 0.0) for sid in spreads}
        tot = sum(raw.values())
        w_now = ({sid: v / tot for sid, v in raw.items()} if tot > 0
                 else {sid: 1.0 / len(spreads) for sid in spreads})
        spread_now = sum(w_now[s] * spreads[s] for s in spreads)
        per: dict[str, Any] = {}
        for sid, v in spreads.items():
            rest = 1.0 - w_now[sid]
            if rest <= 0:
                m = None
            else:
                m = sum(w_now[t] * spreads[t] for t in spreads if t != sid) / rest
            w_flip = None
            if m is not None and abs(v - m) >= SPREAD_SWITCH_SLOPE_EPS:
                w = -m / (v - m)
                if 0.0 <= w <= 1.0:
                    w_flip = round(w, 4)
            per[sid] = {
                "spread_in_scenario_pp": round(v, 4),
                "w_now": round(w_now[sid], 4),
                "w_flip": w_flip,
                "direction": (None if w_flip is None
                              else "up" if w_flip > w_now[sid] else "down"),
            }
        out[hk] = {"spread_now_pp": round(spread_now, 4), "by_scenario": per}
    if not out:
        return None
    return {
        "by_horizon": out,
        "basis": ("спред = акции − облигации, цена + carry + дивиденды по сценариям, "
                  "БЕЗ идиосинкратики (не равен headline-спреду §2); вес одного "
                  "сценария меняется, остальные делят остаток в текущих пропорциях; "
                  "порог по точке, не по CI"),
    }


# ───────── Frontmatter-контракт вьюера (стабильность графиков, @1.3) ─────────

def _round2(v):
    return round(float(v), 2) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def build_frontmatter_contract(
    portfolio_by_horizon: dict,
    horizon_ends: dict,
    primary_horizon: int,
    ci_method: str,
    total_return: dict | None,
) -> tuple[dict, dict | None]:
    """
    Детерминированные frontmatter-блоки для integrated-view @1.3 — контракт
    стабильности графиков вьюера (tools/design-reference/INDEX.md): LLM копирует
    их в frontmatter артефакта AS-IS (никакой ручной вёрстки чисел — именно
    «плавающий» прозаический вывод ломал графики).

    Возвращает (portfolio_by_horizon_fm, total_return_fm|None):
      portfolio_by_horizon:
        primary_horizon / ci_method / horizons.{"12": {end, equity{value,ci
        [,l1_point]}, bond{value,ci[,l1_point]}, spread{value,ci}}}
        # ключи — месяцы БЕЗ префикса h; l1_point (@1.4) — информационная
        # L1-overlay точка, канон (value/spread/ci) — MC-совместимый L2-центр
      total_return:
        horizons.{"12": {expected{portfolio,equity,bond,cash},
        layers{equity{price,dividend,idio}, bond{price,carry,idio}, cash{...}}}}
    """
    horizons: dict[str, Any] = {}
    for hk, pf in (portfolio_by_horizon or {}).items():
        entry: dict[str, Any] = {"end": (horizon_ends or {}).get(hk)}
        for b in ("equity", "bond"):
            e = (pf.get(b) or {}).get("expected_pct_horizon") or {}
            if e.get("value") is not None:
                ci = e.get("ci") or [None, None]
                entry[b] = {
                    "value": _round2(e["value"]),
                    "ci": ([_round2(ci[0]), _round2(ci[1])]
                           if ci and ci[0] is not None else None),
                }
                # @1.4: L1-overlay точка — информационная, вьюер/downstream
                # читают канон из value; l1_point не входит в headline/spread/CI.
                l1 = ((pf.get(b) or {}).get("l1_point") or {}).get("value")
                if l1 is not None:
                    entry[b]["l1_point"] = _round2(l1)
        sp = pf.get("spread_pp_horizon") or {}
        if sp.get("point") is not None:
            ci = sp.get("ci") or sp.get("ci_linear")
            entry["spread"] = {
                "value": _round2(sp["point"]),
                "ci": [_round2(ci[0]), _round2(ci[1])] if ci else None,
            }
        horizons[hk[1:]] = entry
    fm_pbh = {
        "primary_horizon": primary_horizon,
        "ci_method": ci_method,
        "horizons": horizons,
    }

    fm_tr = None
    if total_return and total_return.get("by_horizon"):
        trh: dict[str, Any] = {}
        for hk, blk in total_return["by_horizon"].items():
            exp = {k: _round2(v) for k, v in (blk.get("expected") or {}).items()}
            lay: dict[str, Any] = {}
            for b, layer in (blk.get("layers") or {}).items():
                kind = layer.get("income_kind")
                row: dict[str, Any] = {}
                for key in ("price", "income", "idio"):
                    v = (layer.get(key) or {}).get("value") \
                        if isinstance(layer.get(key), dict) else None
                    if v is None:
                        continue
                    name = kind if (key == "income" and kind in
                                    ("carry", "dividend", "mm_rate")) else key
                    row[name] = _round2(v)
                if row:
                    lay[b] = row
            trh[hk[1:]] = {"expected": exp, "layers": lay}
        fm_tr = {"horizons": trh, "note": total_return.get("note")}
    return fm_pbh, fm_tr


# ───────────────────── Шаг 4 (V2-B): Monte Carlo CI ─────────────────────
#
# D4-5/6/7: stdlib random (без numpy). Общий розыгрыш сценария на path (D4-6) —
# когерентные «миры», корреляции между позициями (через macro) и катализаторами
# (через active_scenarios) возникают естественно, без явной corr_matrix. Точечные
# значения остаются аналитическими (D4-7); MC считает только CI (перцентили 2.5/97.5),
# spread CI и портфельные хвосты.

DEFAULT_MC_PATHS = 10000
DEFAULT_MC_SEED = 42
MC_DIVERGENCE_PP = 1.5            # |MC mean − analytic| по портфелю выше → warning
_EQUITY_CLASSES = {"equity", "fund_equity", "fund_gold", "fund_unknown"}
_BOND_CLASSES = {"bond", "fund_bond"}


def _percentile(sorted_vals: list[float], q: float) -> float | None:
    """Линейно-интерполированный перцентиль (q в процентах). sorted_vals — отсортирован."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (q / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _sample_tri(rnd: random.Random, ci: list, mode: float) -> float:
    """Сэмпл triangular(lo, hi, mode). Вырожденные (None/нулевая ширина) → точка."""
    if not ci or len(ci) != 2 or ci[0] is None or ci[1] is None:
        return float(mode)
    lo, hi = float(ci[0]), float(ci[1])
    if lo > hi:
        lo, hi = hi, lo
    if hi == lo:
        return lo
    m = min(max(float(mode), lo), hi)
    return rnd.triangular(lo, hi, m)


def _mc_sample_macro(ctx: dict, s: str, rnd: random.Random) -> float:
    """Macro-сэмпл на разыгранном сценарии s: triangular из delta_by_scenario[s]
    (сценарий уже выбран — НЕ pweighted). Если per-scenario нет (L1/missing) —
    аналитическая точка + сэмпл ширины CI вокруг неё."""
    dbs = ctx.get("delta_by_scenario") or {}
    if s in dbs and isinstance(dbs[s], dict):
        d = dbs[s]
        v = float(d.get("value", 0) or 0)
        return _sample_tri(rnd, d.get("ci_pct") or [v, v], v)
    return _sample_tri(rnd, ctx.get("macro_ci") or [None, None], ctx.get("macro_point", 0.0))


def _mc_sample_catalyst(cat: dict, s: str, scenarios: dict, rnd: random.Random) -> float:
    """Сэмпл вклада катализатора на сценарии s (паритет с аналитикой METH-1)."""
    try:
        kind, _ = detect_catalyst_kind(cat)
    except ValueError:
        return 0.0
    src_disc = LOW_QUALITY_DISCOUNT if (cat.get("source_quality") or "").upper() == "LOW" else 1.0

    if kind == "binary":
        p = float(cat.get("p", 0) or 0)
        active = cat.get("active_scenarios")
        dep = cat.get("macro_dependency")
        if active:
            resolved = all(a in scenarios for a in active)
            fires = ((s in active) and rnd.random() < p) if resolved \
                else (rnd.random() < p * NULL_DEPENDENCY_DISCOUNT)
        elif dep:
            fires = ((s == dep) and rnd.random() < p) if dep in scenarios \
                else (rnd.random() < p * NULL_DEPENDENCY_DISCOUNT)
        else:
            fires = rnd.random() < p * NULL_DEPENDENCY_DISCOUNT
        if not fires:
            return 0.0
        if cat.get("upside_pct") is not None:
            v = float(cat["upside_pct"])
            return _sample_tri(rnd, cat.get("upside_ci_pct") or [v, v], v) * src_disc
        if cat.get("downside_pct") is not None:
            d = float(cat["downside_pct"])
            return -_sample_tri(rnd, cat.get("downside_ci_pct") or [d, d], d) * src_disc
        return 0.0

    # quantitative: значение triangular из upside_ci_by_scenario[s] (сценарий уже разыгран)
    ubs = cat.get("upside_by_scenario") or {}
    ucbs = cat.get("upside_ci_by_scenario") or {}
    up = float(ubs.get(s, 0) or 0)
    return _sample_tri(rnd, ucbs.get(s) or [up, up], up) * src_disc


def _build_mc_contexts(
    holdings: list[dict], stress_per_position: dict,
    review_stocks: dict, review_bonds: dict | None,
    hk: str, horizon_end: date | None, trust_matrix: dict | None,
    per_position: list[dict],
    carry_lookup: dict | None = None,
) -> list[dict]:
    """Контексты MC на горизонт hk: macro per-scenario + analytic macro/div + in-horizon катализаторы."""
    pp_by_ticker = {p["ticker"]: p for p in per_position}
    contexts: list[dict] = []
    for hold in holdings:
        t = hold.get("ticker")
        entry = pp_by_ticker.get(t)
        if not entry:
            continue
        slot = (entry.get("by_horizon") or {}).get(hk) or {}
        stress_pos = stress_per_position.get(t)
        bh = stress_pos.get("by_horizon") if isinstance(stress_pos, dict) else None
        stress_slot = (bh.get(hk) if isinstance(bh, dict) else None) or stress_pos or {}
        idio_review = _get(review_stocks, "per_stock", t) or _get(review_bonds, "per_bond", t) or {}
        cats = []
        for c in (idio_review.get("catalyst") or []):
            in_h, _ = _catalyst_in_horizon(c, horizon_end)
            if not in_h or is_low_trust(c, trust_matrix):
                continue
            cats.append(c)
        macro = slot.get("macro") or {}
        # Слой 2: per-scenario carry-ячейки (bond_carry) — MC сэмплирует по
        # разыгранному сценарию s вместо сценарно-независимого div-спека.
        carry_cells = (((carry_lookup or {}).get(t) or {})
                       .get("by_horizon") or {}).get(hk, {}).get("by_scenario")
        contexts.append({
            "ticker": t,
            "weight_pct": entry.get("weight_pct"),
            "asset_class": entry.get("asset_class"),
            "is_blocked": entry.get("is_blocked", False),
            "delta_by_scenario": stress_slot.get("delta_pct_by_scenario") or {},
            "macro_point": macro.get("value") if macro.get("value") is not None else 0.0,
            "macro_ci": macro.get("ci") or [None, None],
            "div": slot.get("div_or_carry") or {"value": 0.0, "ci": [0.0, 0.0]},
            "carry_by_scenario": carry_cells if isinstance(carry_cells, dict) else None,
            "catalysts": cats,
        })
    return contexts


def _mc_sample_income(ctx: dict, s: str, rnd: random.Random) -> float:
    """Доходный слой на path: carry-ячейка разыгранного сценария s (Слой 2)
    либо сценарно-независимый div-спек (Слой 3 / legacy)."""
    cells = ctx.get("carry_by_scenario")
    if cells and s in cells:
        cell = cells[s] or {}
        v = float(cell.get("carry_pct", 0) or 0)
        return _sample_tri(rnd, cell.get("ci_pct") or [v, v], v)
    div = ctx["div"]
    return _sample_tri(rnd, (div.get("ci") or [0, 0]), div.get("value", 0) or 0)


def mc_simulate(contexts: list[dict], scenarios: dict, paths: int, seed: int,
                horizon_key: str | None = None) -> dict:
    """
    Monte Carlo: paths путей, на каждом ОДИН сценарий s ~ p_norm (D4-6), общий для
    всех позиций/катализаторов. Возвращает per-position CI (P2.5/P97.5), equity/bond/
    spread CI, means (для divergence guard), портфельные P5/P95.
    """
    rnd = random.Random(seed)
    sids = list(scenarios)
    cum: list[float] = []
    acc = 0.0
    for sid in sids:
        acc += _scenario_p_norm(scenarios, sid, horizon_key)
        cum.append(acc)
    total_p = cum[-1] if cum else 0.0

    active_ctx = [c for c in contexts if not c.get("is_blocked")]
    pos_samples: dict[str, list[float]] = {c["ticker"]: [0.0] * paths for c in active_ctx}
    eq_samples: list[float | None] = [None] * paths
    bd_samples: list[float | None] = [None] * paths
    spread_samples: list[float] = []

    for i in range(paths):
        # розыгрыш сценария (один на path)
        if total_p > 0 and sids:
            r = rnd.random() * total_p
            s = sids[-1]
            for j, cthr in enumerate(cum):
                if r <= cthr:
                    s = sids[j]
                    break
        else:
            s = sids[0] if sids else None
        eq_num = eq_w = bd_num = bd_w = 0.0
        for ctx in active_ctx:
            tot = (_mc_sample_macro(ctx, s, rnd)
                   + _mc_sample_income(ctx, s, rnd)
                   + sum(_mc_sample_catalyst(cat, s, scenarios, rnd) for cat in ctx["catalysts"]))
            pos_samples[ctx["ticker"]][i] = tot
            w = ctx.get("weight_pct") or 0.0
            if ctx["asset_class"] in _EQUITY_CLASSES:
                eq_num += w * tot
                eq_w += w
            elif ctx["asset_class"] in _BOND_CLASSES:
                bd_num += w * tot
                bd_w += w
        eq = eq_num / eq_w if eq_w > 0 else None
        bd = bd_num / bd_w if bd_w > 0 else None
        eq_samples[i] = eq
        bd_samples[i] = bd
        if eq is not None and bd is not None:
            spread_samples.append(eq - bd)

    def _ci(vals, lo=2.5, hi=97.5):
        v = sorted(x for x in vals if x is not None)
        if not v:
            return [None, None]
        return [round(_percentile(v, lo), 4), round(_percentile(v, hi), 4)]

    def _mean(vals):
        v = [x for x in vals if x is not None]
        return round(sum(v) / len(v), 4) if v else None

    eq_sorted = sorted(x for x in eq_samples if x is not None)
    return {
        "position_ci": {t: _ci(arr) for t, arr in pos_samples.items()},
        "equity_ci": _ci(eq_samples),
        "bond_ci": _ci(bd_samples),
        "spread_ci": _ci(spread_samples),
        "equity_mean": _mean(eq_samples),
        "bond_mean": _mean(bd_samples),
        "portfolio_p5": round(_percentile(eq_sorted, 5), 4) if eq_sorted else None,
        "portfolio_p95": round(_percentile(eq_sorted, 95), 4) if eq_sorted else None,
    }


def _apply_mc_ci(per_position: list[dict], pf: dict, mc: dict, hk: str) -> None:
    """Перезаписывает CI результатами MC (точечные значения не трогаются, D4-7)."""
    pos_ci = mc.get("position_ci") or {}
    for p in per_position:
        slot = (p.get("by_horizon") or {}).get(hk)
        if slot and p["ticker"] in pos_ci:
            slot["total"]["ci"] = pos_ci[p["ticker"]]   # flat total — тот же объект для primary
    eq = (pf.get("equity") or {}).get("expected_pct_horizon")
    if eq and mc["equity_ci"][0] is not None:
        eq["ci"] = mc["equity_ci"]
    bd = (pf.get("bond") or {}).get("expected_pct_horizon")
    if bd and mc["bond_ci"][0] is not None:
        bd["ci"] = mc["bond_ci"]
    sp = pf.get("spread_pp_horizon")
    if sp is not None and mc["spread_ci"][0] is not None:
        # v2: единый ci из joint-сэмплов вместо пары linear/quadratic
        sp.pop("ci_linear", None)
        sp.pop("ci_quadratic", None)
        sp["ci"] = mc["spread_ci"]
        sp["ci_method"] = "mc"


#: Severity, при которых флаг снапшота — фон, а не сигнал. Всё остальное, включая
#: незнакомые имена, считается требующим внимания: смысл проброса в том, чтобы
#: флаг не исчез молча, а новая severity в загрузчике — ровно такой случай.
_QUIET_SNAPSHOT_SEVERITIES = {"info", "debug"}


def compute_share_bases(snapshot: dict, per_position: list[dict]) -> dict:
    """
    Все базы долей, которые артефакт вправе цитировать (PIV-6a).

    «Доля акций» в отчёте законно существует в нескольких базах, и шаблон требует
    обязательный блок сверки базисов. Прогон 08-15 этот блок написал (три базы:
    34,8% / 37,54% / 100%), а в §5 привёл ЧЕТВЁРТУЮ — 34,51% (акции от основного
    счёта, из обзора) — мимо собственной таблицы. Блок сверки для того и заведён,
    чтобы такие вхождения ловить, поэтому базы считает скрипт: проза цитирует
    отсюда и ниоткуда больше.
    """
    holdings = snapshot.get("holdings") or []
    by_type: dict[str, float] = {}
    total_unblocked = 0.0
    for h in holdings:
        if h.get("is_blocked"):
            continue
        v = h.get("value_rub")
        if not _is_number(v):
            continue
        by_type[str(h.get("asset_type") or "unknown")] = \
            by_type.get(str(h.get("asset_type") or "unknown"), 0.0) + float(v)
        total_unblocked += float(v)

    def _pct(part: float, whole: float) -> float | None:
        return round(part / whole * 100.0, 4) if whole else None

    # База 2 — веса стресса (та, на которой стоят §2/§3/§4).
    w: dict[str, float] = {}
    for p in per_position:
        if p.get("is_blocked") or not p.get("weight_pct"):
            continue
        cls = p.get("asset_class") or "unknown"
        bucket = ("equity" if cls in ("equity", "fund_equity")
                  else "bond" if cls in ("bond", "fund_bond") else "other")
        w[bucket] = w.get(bucket, 0.0) + float(p["weight_pct"])

    # База 3 — основной счёт из balance_summary (источник числа 34,51% в §5).
    main = _get(snapshot, "balance_summary", "by_account", "main") or {}
    main_total = main.get("total_rub")
    main_shares = {}
    if _is_number(main_total) and float(main_total):
        for key, name in (("stocks_rub", "equity"), ("bonds_rub", "bond"),
                          ("funds_rub", "fund"), ("cash_rub", "cash")):
            if _is_number(main.get(key)):
                main_shares[name] = _pct(float(main[key]), float(main_total))

    return {
        "unblocked_holdings": {
            "label": "Бумаги без кэша (holdings снапшота, без заблокированных)",
            "basis_rub": round(total_unblocked, 2),
            "shares_pct": {("equity" if k == "stock" else "bond" if k == "bond"
                            else "fund" if k == "fund" else k): _pct(v, total_unblocked)
                           for k, v in sorted(by_type.items())},
            "used_in": "«Базовые суммы» шапки",
        },
        "stress_weights": {
            "label": "Полный портфель по стресс-тесту (после маршрутизации фондов)",
            "basis_rub": None,
            "shares_pct": {k: round(v, 4) for k, v in sorted(w.items())},
            "used_in": "§2, §3, §4 — все агрегаты",
        },
        "main_account": {
            "label": "Основной счёт (balance_summary.by_account.main)",
            "basis_rub": float(main_total) if _is_number(main_total) else None,
            "shares_pct": main_shares,
            "used_in": "§5 — сверка с моделью IE и цель по доле акций",
        },
    }


def compute_layer_shares(portfolio_by_horizon: dict, total_return: dict | None,
                         horizons: list[int]) -> dict:
    """
    Доли слоёв с ЯВНЫМ знаменателем (PIV-6b).

    §4 прогона 08-15 в одном предложении сопоставил «67% облигационного ожидания —
    купоны» и «46% акционного — катализаторы»: 67% считалось от 16,93 (без идио),
    46% — от 20,64 (с идио). Вывод от этого не менялся, но пара формально
    неоднородна. Здесь обе доли считаются от ОДНОГО знаменателя — заголовочного
    ожидания ноги (с идио), — и знаменатель назван в самих данных.
    """
    out: dict[str, Any] = {}
    tr_by_h = (total_return or {}).get("by_horizon") or {}
    for h in horizons:
        hk = f"h{h}"
        pf, tr = portfolio_by_horizon.get(hk) or {}, tr_by_h.get(hk) or {}
        layers = tr.get("layers") or {}
        expected = tr.get("expected") or {}
        buckets: dict[str, Any] = {}
        for bucket in ("equity", "bond"):
            headline = ((pf.get(bucket) or {}).get("expected_pct_horizon") or {}).get("value")
            lay = layers.get(bucket) or {}
            vals = {name: (spec.get("value") if isinstance(spec, dict) else spec)
                    for name, spec in lay.items() if name != "income_kind"}
            vals = {k: v for k, v in vals.items() if _is_number(v)}
            if headline is None or not vals:
                continue
            buckets[bucket] = {
                "headline_with_idio": round(float(headline), 4),
                "expected_without_idio": (round(float(expected[bucket]), 4)
                                          if _is_number(expected.get(bucket)) else None),
                "income_kind": lay.get("income_kind"),
                "layers_pp": {k: round(float(v), 4) for k, v in vals.items()},
                "share_of_headline": {
                    k: (round(float(v) / float(headline), 4) if float(headline) else None)
                    for k, v in vals.items()},
            }
        if buckets:
            out[hk] = {
                "denominator": "headline_with_idio",
                "note": ("Доли слоёв цитировать ТОЛЬКО из share_of_headline — "
                         "у всех слоёв и обеих ног знаменатель один "
                         "(заголовочное ожидание ноги, с идиосинкратикой)."),
                "buckets": buckets,
            }
    return out


def _l1_overlay_report(per_position: list[dict], macro_marginal: dict | None,
                       primary_key: str) -> dict:
    """
    PIV-5: L1-overlay передали — посчитался ли он хоть на одной позиции.

    Отказ overlay был беззвучным: `layer: "L2"`, `coherence_gap: null`, ноль warning'ов.
    Прогон с overlay отрапортовал бы «L1 подключён», выдав чистый L2 (прогон 08-15:
    0 позиций из 68 — имена факторов macro-marginal не совпали ни с ключами factor_betas,
    ни с ключами baseline_spot). Здесь этот случай становится явным сообщением.
    """
    if not macro_marginal:
        return {"requested": False, "applied_positions": 0, "message": None}
    applied = with_betas = 0
    unmatched: set[str] = set()
    for p in per_position:
        m = _get(p, "by_horizon", primary_key, "macro") or p.get("macro") or {}
        st = m.get("l1_status")
        if st == "applied":
            applied += 1
            with_betas += 1
        elif st == "no_factor_match":
            with_betas += 1
        for f in (m.get("l1_unmatched_factors") or []):
            unmatched.add(str(f))
    message = None
    if with_betas and not applied:
        message = (
            f"L1-overlay передан, но НЕ применился ни на одной из {with_betas} позиций "
            f"с factor_betas — ни один фактор не дал числового движения "
            f"(нерастворённые: {sorted(unmatched)}). Результат — чистый Layer 2. "
            f"Писать «подключён L1» нельзя: проверь имена факторов против "
            f"MACRO_FACTOR_ALIASES и ключи baseline_spot против UNIT_SPOT_KEYS. "
            f"Это HIGH-оговорка §0/§9."
        )
    elif applied and unmatched:
        message = (
            f"L1-overlay применён на {applied} позициях, но факторы {sorted(unmatched)} "
            f"в расчёт не вошли (нет числового уровня либо ключа в baseline_spot) — "
            f"L1-точка построена на неполном наборе. Оговорка СРЕДНЕЙ серьёзности."
        )
    return {
        "requested": True,
        "applied_positions": applied,
        "positions_with_betas": with_betas,
        "unmatched_factors": sorted(unmatched),
        "message": message,
    }


def _blindspot_coverage(per_position: list[dict], blindspot_table: dict[str, str],
                        primary_key: str) -> dict:
    """PIV-5: сколько позиций (и какой вес) помечено слепым пятном и откуда сигнал."""
    by_source: dict[str, list[str]] = {"position_flag": [], "stress_table": []}
    weight = 0.0
    for p in per_position:
        m = _get(p, "by_horizon", primary_key, "macro") or p.get("macro") or {}
        if not m.get("blindspot"):
            continue
        by_source.setdefault(m.get("blindspot_source") or "position_flag", []).append(p["ticker"])
        if not p.get("is_blocked") and p.get("weight_pct"):
            weight += float(p["weight_pct"])
    return {
        "table_rows": len(blindspot_table),
        "flagged_total": sum(len(v) for v in by_source.values()),
        "from_position_flag": sorted(by_source.get("position_flag") or []),
        "from_stress_table": sorted(by_source.get("stress_table") or []),
        "flagged_weight_pct": round(weight, 4),
    }


def stress_recalc_info(stress: dict) -> dict | None:
    """Сведения о пересчёте сайта, если в payload положен файл recalc-<стресс>.yaml, иначе None.

    Возраст стресса считается по дате суждений (стресс скилла `source_stress`), а не по дате пересчёта:
    пересчёт обновляет числа на свежем снапшоте и весах сайта, суждения остаются прежними.
    """
    rc = stress.get("recalc")
    if not isinstance(rc, dict) or not rc.get("source_stress"):
        return None
    src = str(rc["source_stress"])
    m = re.search(r"stress-(\d{4}-\d{2}-\d{2})", src)
    return {
        "source_stress": src,
        "judgments_date": m.group(1) if m else None,
        "snapshot_id": rc.get("snapshot_id"),
        "source_snapshot_id": rc.get("source_snapshot_id"),
        "at": rc.get("at"),
        "reason": rc.get("reason"),
        "weights_source": rc.get("weights_source"),
        "message": (f"числа стресса — пересчёт сайта от {rc.get('at')} на снапшоте {rc.get('snapshot_id')}; "
                    f"суждения — {src}" + (f" от {m.group(1)}" if m else "")
                    + ": возраст стресса считать по дате суждений"),
    }


def _horizons_file_ok(doc) -> bool:
    """Файл сроков сайта horizons@1 валиден (правила те же, что у сайта): 1–6 сроков hN, даты по возрастанию N
    строго возрастают, основной срок — один из них. Невалидный файл считается отсутствующим."""
    if not isinstance(doc, dict) or doc.get("schema") != "horizons@1":
        return False
    he = doc.get("horizon_ends")
    if not isinstance(he, dict) or not 1 <= len(he) <= 6:
        return False
    rows = []
    for k, v in he.items():
        m = re.fullmatch(r"h(\d+)", str(k))
        if not m or int(m.group(1)) <= 0 or not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            return False
        if _parse_iso_date(v) is None:
            return False
        rows.append((int(m.group(1)), v))
    rows.sort()
    if any(not b[1] > a[1] for a, b in zip(rows, rows[1:])):
        return False
    ph = doc.get("primary_horizon")
    return isinstance(ph, int) and not isinstance(ph, bool) and f"h{ph}" in he


def check_stress_terms(stress: dict, horizons_doc) -> dict | None:
    """STRESS_TERMS_MISMATCH: сроки стресса не совпадают со сроками сайта (payload.horizons_file). Сравниваются
    метки и даты, основной срок не входит. Нет файла, он невалиден, у стресса нет horizon_ends или всё
    совпало — None."""
    if not _horizons_file_ok(horizons_doc):
        return None
    he = stress.get("horizon_ends") if isinstance(stress, dict) else None
    if not isinstance(he, dict) or not he:
        return None
    st = {str(k): str(v)[:10] for k, v in he.items()}
    site = dict(horizons_doc["horizon_ends"])
    if st == site:
        return None

    def txt(d: dict) -> str:
        return ", ".join(f"{k} {v}" for k, v in sorted(d.items(), key=lambda kv: int(kv[0][1:]) if re.fullmatch(r"h\d+", kv[0]) else 0))
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(horizons_doc.get("set_at") or ""))
    set_ru = f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else "?"
    return {
        "code": "STRESS_TERMS_MISMATCH",
        "stress": st, "site": site, "set_at": horizons_doc.get("set_at"),
        "message": (f"стресс посчитан на сроки {txt(st)}, действующие сроки {txt(site)} (заданы на сайте {set_ru}) — "
                    "числа стресса относятся к прежним срокам; сказать об этом в §0 и оговоркой в §9"),
    }


def collect_snapshot_quality_flags(snapshot: dict) -> list[dict]:
    """
    Достаёт из снапшота `data_quality_flags`, которые загрузчик пометил как
    требующие внимания, чтобы §0 отчёта не мог заявить «нарушений нет», пока они
    лежат в исходных данных.

    Реальный случай 2026-08-04: загрузчик записал `iis_split_position` (ОФЗ 26238
    разложена по двум счетам) и `ie_model_total_mismatch` (сумма целей модели
    93%, а не 100%) — оба severity `warn`. Ни один не доехал ни до стресса, ни до
    сводного обзора, при том что §0 утверждал «нарушений нет», а §5 считал
    отклонения от неполной модели.
    """
    flags = snapshot.get("data_quality_flags")
    if not isinstance(flags, list):
        return []
    out: list[dict] = []
    for flag in flags:
        if not isinstance(flag, dict):
            # Не-словарь предъявляем как есть: тихо выбросить его — тот же дефект.
            out.append({"severity": "unknown", "code": None,
                        "message": str(flag), "step": None})
            continue
        severity = str(flag.get("severity") or "unknown").strip().lower()
        if severity in _QUIET_SNAPSHOT_SEVERITIES:
            continue
        out.append({
            "severity": severity,
            "code": flag.get("code"),
            "step": flag.get("step"),
            "message": flag.get("message"),
        })
    return out


_V1_HINT = ("v1 снят V2-CUTOVER 2026-08-03; мигрировать: "
            "skills/portfolio-scenario-stress/scripts/migrate_v1_to_v2.py")


def _reject_v1(stress: dict, review_stocks: dict, review_bonds: dict | None) -> dict | None:
    """Вход не schema 2 (stress / review без schema_version 2) → понятная ошибка."""
    bad: list[str] = []
    for name, doc in (("stress", stress), ("review_stocks", review_stocks),
                      ("review_bonds", review_bonds)):
        sv = doc.get("schema_version") if doc else 2
        if sv != 2 or isinstance(sv, bool):
            bad.append(f"{name} (schema_version={sv!r})")
    if not bad:
        return None
    return {
        "error": "schema_v1_not_supported",
        "message": f"Вход не schema 2: {', '.join(bad)}. {_V1_HINT}.",
        "invalid_inputs": bad,
    }


def run(payload: dict) -> dict:
    snapshot = payload.get("snapshot") or {}
    stress = payload.get("stress") or {}
    review_stocks = payload.get("review_stocks") or {}
    review_bonds = payload.get("review_bonds") or None
    trust_matrix = payload.get("trust_matrix") or None

    # v1-артефакты не принимаются (V2-CUTOVER 2026-08-03): понятная ошибка, не трейсбек.
    v1_err = _reject_v1(stress, review_stocks, review_bonds)
    if v1_err:
        return v1_err

    # V2-A: список горизонтов.
    horizons, primary_horizon = _normalize_horizons(payload)
    subset = payload.get("_horizon_subset")
    if subset:
        filtered = [h for h in horizons if h in set(subset)]
        if filtered:
            horizons = filtered
            if primary_horizon not in horizons:
                primary_horizon = horizons[0]

    scenarios = stress.get("scenarios") or {}
    p_sum, p_severity = normalize_scenario_probs(scenarios,
                                                 [f"h{h}" for h in horizons])
    cv = cross_validate(review_stocks, scenarios, review_bonds)
    drift = check_snapshot_drift(stress, review_stocks, review_bonds)

    stale_gate = "FAIL" if cv["share"] > STALE_PIPELINE_THRESHOLD else "PASS"
    stale_message = None
    if stale_gate == "FAIL":
        stale_message = (
            f"unresolved macro_dependency: {len(cv['unresolved'])} из "
            f"{cv['total_with_dependency']} ({cv['share']:.0%}). "
            f"Отсутствующие scenario IDs: {cv['missing_scenario_ids']}. "
            f"Запусти RECALIBRATE-mode (macro-forecast-chain) на active forecasts "
            f"или обнови weekly-review через ru-portfolio-advisor перед integrated-view."
        )
    elif cv["idio_layer_unlinked"]:
        # PIV-4a: гейт формально PASS («0 из 0»), но идио-слой целиком без
        # сценарной привязки — каждый катализатор получит плоский дисконт 0.7.
        stale_message = (
            f"идио-слой развязан со сценарным: 0 из {cv['total_catalysts']} "
            f"катализаторов несут macro_dependency — все получат плоский дисконт "
            f"{NULL_DEPENDENCY_DISCOUNT} вместо сценарной массы. Это HIGH-оговорка "
            f"§0/§9, а не чистый PASS. Производитель привязки — Mode 1/2 "
            f"ru-portfolio-advisor (сценарные ID — из SSOT-матрицы scenarios/)."
        )

    macro_marginal = payload.get("macro_marginal") or None
    baseline_spot: dict | None = stress.get("baseline_spot") or None

    # Опорная дата для capping bond-carry до оферты/погашения: snapshot → review → stress.
    as_of = _parse_iso_date(snapshot.get("as_of_date")) \
        or _parse_iso_date(_get(review_stocks, "review_date")) \
        or _parse_iso_date(stress.get("date"))

    stress_per_position = stress.get("per_position") or {}
    # Слой 2: блок bond_carry из stress (compute_bond_carry.py) — приоритетный
    # источник carry для облигаций/MM/кэша; старый stress без блока → legacy R-BOND-CARRY.
    carry_lookup = _get(stress, "bond_carry", "per_position") or None

    # Fail-fast: запрошенные горизонты vs доступные в stress (R: покрытие ≥ запрос).
    avail = _available_stress_horizons(stress_per_position)
    fail_msg = None
    if avail is not None:
        missing = [f"h{h}" for h in horizons if f"h{h}" not in avail]
        if missing:
            fail_msg = (f"Запрошены горизонты {sorted(missing)}, в stress доступны "
                        f"{sorted(avail)}. Перегенерируй stress с нужными горизонтами.")
    if fail_msg:
        return {
            "error": "horizon_mismatch",
            "message": fail_msg,
            "requested_horizons": horizons,
            "available_stress_horizons": sorted(avail) if avail else None,
        }

    horizon_ends = _resolve_horizon_ends(horizons, stress, review_stocks, as_of)
    horizon_years: dict[str, int] = {}
    for h in horizons:
        hk = f"h{h}"
        he = _parse_iso_date(horizon_ends.get(hk))
        if he is not None:
            horizon_years[hk] = he.year
        elif as_of is not None and h > 0:
            horizon_years[hk] = (as_of.year * 12 + as_of.month - 1 + h) // 12

    holdings = snapshot.get("holdings") or []

    # ── PIV-4b: маршрутизация фондов по справочнику fund_classification ──
    # Payload-ключ той же формы, что секция в sector-overrides.yaml:
    # {cash_equivalent: {tickers: [...]}, gold: ..., bond_bucket: ..., equity_bucket: ...}
    # (голый список вместо {tickers: [...]} тоже принимается). Без ключа —
    # прежнее поведение бит-в-бит: asset_type=fund → fund_unknown → equity.
    fund_unrouted: list[str] = []
    fc = payload.get("fund_classification") or None
    if fc:
        _FC_CLASS = {"cash_equivalent": "cash_equivalent", "gold": "gold",
                     "bond_bucket": "fund_bond", "equity_bucket": "fund_equity"}
        fc_map: dict[str, str] = {}
        for group, cls in _FC_CLASS.items():
            entry = fc.get(group)
            tickers = (entry.get("tickers") if isinstance(entry, dict) else entry) or []
            for t in tickers:
                fc_map[t] = cls
        routed: list[dict] = []
        for hold in holdings:
            t = hold.get("ticker")
            cls = fc_map.get(t)
            if cls is not None:
                # копия: вход не мутируется; справочник — SSOT, перекрывает
                # и legacy-трансляцию, и явный asset_class payload'а
                hold = {**hold, "asset_class": cls}
            elif (hold.get("asset_type") == "fund"
                  and hold.get("asset_class") in (None, "fund_unknown")
                  and not hold.get("is_blocked")):
                fund_unrouted.append(t)
            routed.append(hold)
        holdings = routed
        fund_unrouted = sorted(set(fund_unrouted))

    holdings, merged_tickers = merge_duplicate_holdings(holdings)

    # PIV-5: таблица границ стресса (ticker → verdict). Живёт рядом с булевым
    # per_position.macro_blindspot и шире его — см. BLINDSPOT_TABLE_VERDICTS.
    blindspot_table: dict[str, str] = {}
    for row in (stress.get("macro_blindspots") or []):
        if isinstance(row, dict) and row.get("ticker"):
            v = row.get("verdict")
            blindspot_table[str(row["ticker"])] = str(v) if v is not None else "UNSPECIFIED"

    per_position = [aggregate_position(
        holding=hold,
        stress_per_position=stress_per_position,
        review_stocks=review_stocks,
        review_bonds=review_bonds,
        scenarios=scenarios,
        trust_matrix=trust_matrix,
        horizons=horizons,
        horizon_ends=horizon_ends,
        macro_marginal=macro_marginal,
        as_of=as_of,
        baseline_spot=baseline_spot,
        horizon_years=horizon_years,
        primary_horizon=primary_horizon,
        carry_lookup=carry_lookup,
        blindspot_table=blindspot_table,
    ) for hold in holdings]

    # V2-B: режим CI (default mc). Точечные значения всегда аналитические (D4-7).
    ci_mode = payload.get("ci_mode", "mc")
    mc_paths = int(payload.get("mc_paths", DEFAULT_MC_PATHS))
    mc_seed = int(payload.get("mc_seed", DEFAULT_MC_SEED))
    use_mc = (ci_mode == "mc") and bool(scenarios)
    mc_divergence: list[dict] = []

    primary_key = f"h{primary_horizon}"
    # Портфельные агрегаты / tail / sanity — на каждый горизонт (через проекцию total).
    portfolio_by_horizon: dict[str, Any] = {}
    tail_by_horizon: dict[str, Any] = {}
    sanity_by_horizon: dict[str, Any] = {}
    for h in horizons:
        hk = f"h{h}"
        pf = compute_portfolio_aggregates(_horizon_view(per_position, hk), h)
        if use_mc:
            # MC: перезаписываем CI (точку — нет). Под-сид seed+h (детерминизм по горизонтам).
            he = _parse_iso_date(horizon_ends.get(hk))
            contexts = _build_mc_contexts(holdings, stress_per_position, review_stocks,
                                          review_bonds, hk, he, trust_matrix, per_position,
                                          carry_lookup=carry_lookup)
            mc = mc_simulate(contexts, scenarios, mc_paths, mc_seed + h,
                             horizon_key=hk)
            _apply_mc_ci(per_position, pf, mc, hk)
            for bucket, mean_key, ci_key in (("equity", "equity_mean", "equity_ci"),
                                             ("bond", "bond_mean", "bond_ci")):
                pt = ((pf.get(bucket) or {}).get("expected_pct_horizon") or {}).get("value")
                mc_mean = mc.get(mean_key)
                if pt is not None and mc_mean is not None and abs(mc_mean - pt) > MC_DIVERGENCE_PP:
                    mc_divergence.append({"horizon": hk, "bucket": bucket,
                                          "analytic": round(pt, 4), "mc_mean": mc_mean})
        portfolio_by_horizon[hk] = pf
        # tail/sanity ПОСЛЕ применения MC-CI (Φ читают готовый CI из проекции).
        view2 = _horizon_view(per_position, hk)
        tail_by_horizon[hk] = compute_tail_flags(view2, pf, thresholds=payload.get("tail_thresholds"))
        sanity_by_horizon[hk] = sanity_checks(view2, pf)

    portfolio = portfolio_by_horizon.get(primary_key) or next(iter(portfolio_by_horizon.values()))
    tail_flags = tail_by_horizon.get(primary_key) or next(iter(tail_by_horizon.values()))
    sanity_warnings = sanity_by_horizon.get(primary_key) or next(iter(sanity_by_horizon.values()))

    diff = compute_diff(per_position, payload.get("previous_view"))
    predictions = _predictions_for_review(review_stocks, review_bonds, horizons, horizon_ends)

    # ── PIV-5: L1-overlay — запрошен и не применился = тихий отказ, а не «L1 ≈ L2» ──
    l1_overlay = _l1_overlay_report(per_position, macro_marginal, primary_key)
    # ── PIV-5: расхождение якорей горизонтов stress vs review ──
    anchor_drift = check_horizon_anchor_drift(
        horizons, stress, review_stocks, review_bonds)
    # ── PIV-5: покрытие метки слепого пятна (флаг позиции vs таблица стресса) ──
    blindspot_coverage = _blindspot_coverage(per_position, blindspot_table, primary_key)
    # ── PIV-7: покрытие матрицы доверия (атрибутирован ли источник катализатора) ──
    trust_coverage = compute_trust_coverage(review_stocks, review_bonds, trust_matrix)

    # Total return (§7): price + carry + dividend по сценариям/бакетам.
    # Дивидендный haircut в санкционных сценариях — payload.div_sanctions_haircut
    # (default DEFAULT_DIV_SANCTIONS_HAIRCUT; null/0 → выключен).
    div_hc = payload.get("div_sanctions_haircut", DEFAULT_DIV_SANCTIONS_HAIRCUT)
    total_return = compute_total_return_by_horizon(
        per_position, stress_per_position, scenarios, scenarios,
        horizons, snapshot, carry_lookup,
        div_sanctions_haircut=(float(div_hc) if div_hc else None),
    )

    # Шаг 4 разбора 2026-10-07: пороги переключения знака спреда по весу сценария.
    spread_switch = compute_spread_switch_thresholds(total_return, scenarios)

    # PIV-6: базы долей и доли слоёв — считает скрипт, проза цитирует отсюда.
    share_bases = compute_share_bases(snapshot, per_position)
    layer_shares = compute_layer_shares(portfolio_by_horizon, total_return, horizons)

    # Frontmatter-контракт вьюера (@1.3): готовые блоки, LLM копирует AS-IS.
    fm_pbh, fm_tr = build_frontmatter_contract(
        portfolio_by_horizon, horizon_ends, primary_horizon,
        "mc" if use_mc else "analytic", total_return,
    )

    return {
        "diff": diff,
        "validation": {
            "scenario_p_sum": p_sum,
            "scenario_p_warning_severity": p_severity,
            "snapshot_drift": drift,
            "unresolved_macro_dependency": cv["unresolved"],
            "unresolved_share": cv["share"],
            "missing_scenario_ids": cv["missing_scenario_ids"],
            "stale_pipeline_gate": stale_gate,
            "stale_pipeline_message": stale_message,
            "idio_layer_unlinked": cv["idio_layer_unlinked"],
            "total_catalysts": cv["total_catalysts"],
            "fund_unrouted": fund_unrouted,
            "merged_duplicate_tickers": merged_tickers,
            "sanity_warnings": sanity_warnings,
            # PIV-5: три тихих отказа, вскрытых прогоном 2026-08-15. Каждый обязан
            # доехать до §0/§9 — см. docs/investment/portfolio/piv-run-2026-08-15-review.md
            "l1_overlay": l1_overlay,
            "horizon_anchor_drift": anchor_drift,
            "blindspot_coverage": blindspot_coverage,
            "trust_coverage": trust_coverage,
            # Флаги качества из снапшота: §0 обязан их перечислить, иначе
            # «нарушений нет» — утверждение о собственных проверках обзора,
            # выданное за утверждение о данных.
            "snapshot_quality_flags": collect_snapshot_quality_flags(snapshot),
            # Числа стресса взяты из пересчёта сайта (Portfolio/stress/auto/recalc-<стресс>.yaml) — ключ есть
            # только тогда; у стресса скилла его нет.
            **({"stress_recalc": stress_recalc_info(stress)} if stress_recalc_info(stress) else {}),
            # Сроки сайта (payload.horizons_file = scenarios/horizons.json) не совпали со сроками стресса — ключ есть
            # только тогда.
            **({"stress_terms_mismatch": tm} if (tm := check_stress_terms(stress, payload.get("horizons_file"))) else {}),
        },
        "per_position": per_position,
        "portfolio": portfolio,                 # flat = primary_horizon (совместимость)
        "tail_flags": tail_flags,               # flat = primary_horizon
        "horizon_months": primary_horizon,      # flat = primary_horizon (совместимость)
        # ── V2-A: multiple horizons ──
        "horizons": horizons,
        "primary_horizon": primary_horizon,
        "horizon_ends": horizon_ends,
        "review_schema": "v2",   # константа: v1 снят (читают сводка и потребители выхода)
        "portfolio_by_horizon": portfolio_by_horizon,
        "tail_flags_by_horizon": tail_by_horizon,
        "sanity_by_horizon": sanity_by_horizon,
        "predictions_for_review": predictions,
        # ── PIV-6: единственный источник долей для прозы ──
        "share_bases": share_bases,       # §5 и блок сверки базисов цитируют отсюда
        "layer_shares": layer_shares,     # доли слоёв с общим знаменателем
        # ── Total return (три слоя): price + carry + dividend ──
        "total_return_by_horizon": total_return,   # None без per-scenario срезов
        # Пороги знака спреда по весу сценария — §2 «Когда вывод переворачивается»
        "spread_switch": spread_switch,            # None без per-scenario срезов
        "carry_source": "bond_carry" if carry_lookup else "legacy_r_bond_carry",
        # ── Frontmatter-контракт вьюера (@1.3): копировать в frontmatter AS-IS ──
        "frontmatter_portfolio_by_horizon": fm_pbh,
        "frontmatter_total_return": fm_tr,
        # ── V2-B: Monte Carlo CI ──
        "ci_method": "mc" if use_mc else "analytic",
        "mc": {"paths": mc_paths, "seed": mc_seed} if use_mc else None,
        "mc_divergence": mc_divergence,
    }


def format_summary(result: dict) -> str:
    """
    Человекочитаемая сводка прогона (PIV-5).

    Заведено по итогам прогона 2026-08-15: из 36 команд сессии большинство ушло не на
    расчёт, а на ЧТЕНИЕ результата ad-hoc однострочниками, и три из них упали (`None`
    в весах заблокированных, вложенность total_return_by_horizon). Сводка закрывает
    этот сценарий штатно; JSON остаётся источником истины для вьюера.
    """
    if result.get("error"):
        return f"ОШИБКА {result['error']}: {result.get('message')}"
    L: list[str] = []
    v = result.get("validation") or {}
    hz, prim = result.get("horizons") or [], result.get("primary_horizon")
    ends = result.get("horizon_ends") or {}
    L.append(f"Горизонты: {hz} (основной {prim}) · CI: {result.get('ci_method')} "
             f"· carry: {result.get('carry_source')} · review: {result.get('review_schema')}")

    L.append("\n── Валидация ──")
    L.append(f"  стейл-гейт: {v.get('stale_pipeline_gate')}"
             f" · Σp = {round(v.get('scenario_p_sum') or 0, 4)}"
             f" · дрейф снапшота: {(v.get('snapshot_drift') or {}).get('max_drift_days')}д")
    for label, msg in (("стейл-гейт", v.get("stale_pipeline_message")),
                       ("L1-overlay", (v.get("l1_overlay") or {}).get("message")),
                       ("матрица доверия", (v.get("trust_coverage") or {}).get("message")),
                       ("якоря горизонтов", (v.get("horizon_anchor_drift") or {}).get("message"))):
        if msg:
            L.append(f"  ⚠ {label}: {msg}")
    for key, label in (("fund_unrouted", "фонды вне справочника"),
                       ("merged_duplicate_tickers", "схлопнутые дубли"),
                       ("missing_scenario_ids", "отсутствующие сценарии")):
        if v.get(key):
            L.append(f"  ⚠ {label}: {v[key]}")
    for f in (v.get("snapshot_quality_flags") or []):
        L.append(f"  ⚑ снапшот [{f.get('severity')}] {f.get('code')}")
    if v.get("stress_recalc"):
        L.append(f"  ↻ {v['stress_recalc']['message']}")
    if v.get("stress_terms_mismatch"):
        L.append(f"  ⚠ {v['stress_terms_mismatch']['code']}: {v['stress_terms_mismatch']['message']}")
    for w in (v.get("sanity_warnings") or []):
        L.append(f"  ⚑ sanity: {w.get('code') or w}")
    bc = v.get("blindspot_coverage") or {}
    if bc.get("flagged_total"):
        L.append(f"  слепые пятна: {bc['flagged_total']} поз. ({bc.get('flagged_weight_pct')}% портфеля)"
                 f" — флаг позиции {len(bc.get('from_position_flag') or [])},"
                 f" таблица стресса {len(bc.get('from_stress_table') or [])}")

    L.append("\n── Портфель по горизонтам (акции / облигации / спред) ──")
    for h in hz:
        hk = f"h{h}"
        pf = (result.get("portfolio_by_horizon") or {}).get(hk) or {}
        eq, bd = pf.get("equity") or {}, pf.get("bond") or {}
        sp = pf.get("spread_pp_horizon") or {}
        def fmt(d):
            val = (d.get("expected_pct_horizon") or {}).get("value")
            ci = (d.get("expected_pct_horizon") or {}).get("ci") or [None, None]
            if val is None:
                return "н/д"
            lo, hi = (f"{c:+.1f}" if c is not None else "н/д" for c in ci)
            return f"{val:+6.2f}% [{lo}; {hi}]"
        star = " ←" if h == prim else ""
        L.append(f"  {hk} до {ends.get(hk)}: {fmt(eq)} / {fmt(bd)}"
                 f" / спред {(sp.get('point') or 0):+.2f} пп{star}")

    tr = ((result.get("total_return_by_horizon") or {}).get("by_horizon") or {})
    if tr:
        L.append("\n── Полная доходность без идио (цена + доход) ──")
        for h in hz:
            e = (tr.get(f"h{h}") or {}).get("expected") or {}
            L.append(f"  h{h}: акции {e.get('equity')} · облигации {e.get('bond')}"
                     f" · кэш {e.get('cash')} · портфель {e.get('portfolio')}")

    sw = ((result.get("spread_switch") or {}).get("by_horizon") or {}).get(f"h{prim}")
    if sw:
        L.append(f"\n── Когда знак спреда (акции − облигации, без идио) меняется, h{prim} ──")
        L.append(f"  сейчас {sw['spread_now_pp']:+.2f} пп")
        for sid, c in sorted(sw["by_scenario"].items()):
            if c["w_flip"] is None:
                tail = "не меняется ни при каком весе"
            else:
                arrow = "вырастет" if c["direction"] == "up" else "упадёт"
                tail = f"меняется, если вес {arrow} до {c['w_flip']:.0%}"
            L.append(f"  {sid}: внутри сценария {c['spread_in_scenario_pp']:+.2f} пп, "
                     f"вес сейчас {c['w_now']:.0%} → {tail}")

    tf = result.get("tail_flags") or {}
    flags = tf.get("flags") or []
    L.append(f"\n── Tail-флаги на h{prim}: {len(flags)} "
             f"(вклад в нижний хвост {tf.get('portfolio_downside')}) ──")
    for f in flags:
        L.append(f"  {f.get('ticker'):<14} {f.get('type')} ({f.get('severity')})")

    pos = result.get("per_position") or []
    active = [p for p in pos if p.get("weight_pct") and not p.get("is_blocked")]
    L.append(f"\nПозиций: {len(pos)} (активных с весом {len(active)}, "
             f"на ИИС-3 {sum(1 for p in pos if p.get('on_iis'))})")
    return "\n".join(L)


def _cli():
    ap = argparse.ArgumentParser(description="Portfolio integrated view aggregator")
    ap.add_argument("--input", help="JSON payload file (default: stdin)")
    ap.add_argument("--output", help="Output file (default: stdout)")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    ap.add_argument("--horizon", action="append", type=int,
                    help="V2-A: ограничить расчёт подмножеством горизонтов (повторяемо: --horizon 12 --horizon 36)")
    ap.add_argument("--all-horizons", action="store_true",
                    help="V2-A: считать все горизонты (default)")
    ap.add_argument("--ci-mode", choices=["mc", "analytic"], default=None,
                    help="V2-B: mc (Monte Carlo, default) | analytic (аналитический CI, регрессия/отладка)")
    ap.add_argument("--mc-paths", type=int, default=None, help="V2-B: число путей MC (default 10000)")
    ap.add_argument("--mc-seed", type=int, default=None, help="V2-B: сид MC (default 42)")
    ap.add_argument("--summary", action="store_true",
                    help="Человекочитаемая сводка вместо JSON (валидация, портфель по "
                         "горизонтам, tail-флаги). Для чтения глазами, не для вьюера")
    args = ap.parse_args()

    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            payload = json.load(f)
    else:
        payload = json.load(sys.stdin)

    if args.horizon and not args.all_horizons:
        payload["_horizon_subset"] = args.horizon
    if args.ci_mode is not None:
        payload["ci_mode"] = args.ci_mode
    if args.mc_paths is not None:
        payload["mc_paths"] = args.mc_paths
    if args.mc_seed is not None:
        payload["mc_seed"] = args.mc_seed

    result = run(payload)

    if args.summary:
        text = format_summary(result)
    else:
        out_kwargs = {"ensure_ascii": False}
        if args.pretty:
            out_kwargs["indent"] = 2
        text = json.dumps(result, **out_kwargs)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)
        sys.stdout.write("\n")


if __name__ == "__main__":
    _cli()
