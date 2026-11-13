#!/usr/bin/env python3
"""
compute_bond_carry.py — Слой 2 total-return: детерминированный carry облигаций
(купоны + pull-to-par + реинвест погашенного тела) per bond × per horizon × per scenario.

Контракт слоёв (total-return, 2026-07):
  Слой 1 (цена)     — compute_per_position.py: delta_pct_by_scenario, price-only.
                      Для бумаг с погашением/офертой внутри горизонта price_delta
                      обнуляется (maturity guard) — их лайфцикл ПОЛНОСТЬЮ здесь.
  Слой 2 (carry)    — ЭТОТ скрипт: блок `bond_carry` в stress-YAML (аддитивный).
  Слой 3 (дивиденды) — ru-portfolio-advisor weekly-stocks-review `dividend_forward`.
  Сумма             — portfolio-integrated-view (aggregate_positions.py).

Механика на бумагу × горизонт H (мес) × сценарий s:
  • t_live = min(H, месяцев до min(offer_date, maturity_date)). Оферта консервативно
    трактуется как погашение (пут держателя; экономика решения не моделируется).
  • Купоны: фактическое расписание от next_coupon_date с шагом 12/coupon_freq_per_year
    мес, купон = coupon_pct/freq от номинала → % от текущей чистой цены.
    НЕ «YTM × t» (YTM тянет дефолтную премию). Флоатер (override → snapshot
    plan_subtype == "Флоат" → эвристика по имени, PSS-12): ставка купона
    корректируется на сценарный Δcbr(t) с полом 0.
  • Pull-to-par: только если событие внутри H → (100 − price)/price × 100.
  • Реинвест тела: событие внутри H → тело+par реинвестируется на (H − t_live):
    RUB — по сценарной траектории КС (кусочно-линейный путь Δcbr через точки
    горизонтов, средняя ставка = трапеция по [t_live, H]); FX — fx_reinvest_rate
    (параметр, default 5%) + продолжение FX-движения на реинвестированное тело.
  • FX-облигации (nominal_currency ≠ RUB/SUR): купоны и тело получают сценарное
    движение usdrub/cnyrub, линейно интерполированное на дату потока (Слой 1
    применяет FX только к цене; для гасящихся бумаг Слой 1 обнулён — FX тела здесь).
    EUR — прокси через usdrub (нет канонического eurrub-фактора) + флаг.
  • Distressed override: ytm > distressed_ytm_mult × базовой КС ИЛИ оферта ближе
    offer_days с отрицательным ytm_to_offer → наивный carry НЕ считается:
    carry = 0 (консервативный пол), флаг credit_review_required, HIGH-caveat.
    Порог ytm не применяется, если до ближайшего события (оферта или погашение)
    меньше distressed_ytm_min_days: доходность короткого срока — арифметика, не
    кредит; бумага считается обычным путём, флаг ytm_threshold_skipped_near_event.
    По той же причине такая бумага не считается high-yield для санкционного haircut.
  • Санкционный haircut (решение C): в сценариях с sanctions ≥ 1 бумаги с
    YTM-спредом к базовой КС > hy_spread_pp получают компонент
    sanctions_haircut = −haircut × (сумма остальных компонент).
  • Money-market (TPAY/TMON/LQDT/SBMM) и голый RUB-кэш: carry по сценарной
    траектории КС − mm_spread_pp (комиссия/спред RUONIA), флаги mm_proxy /
    cash_carry_assumed_mm.

Сознательно НЕ моделируется (caveats в выходе): реинвест промежуточных купонов,
амортизация, roll-down, налоги, НКД (базис — чистая цена).

Вход (JSON payload через run(); CLI собирает из файлов):
  {
    "as_of": "YYYY-MM-DD",                    # default: snapshot.as_of_date
    "snapshot": {...},                         # portfolio-{date}.json
    "scenarios": {"A": {"p": 0.25, "factors_by_horizon": {"h6": {...}}}},
    "horizon_ends": {"h6": "2026-12-31"},      # опц.; иначе as_of + NN (конец месяца)
    "baseline": {"cbr_rate_pct": 16.0},        # обязателен (уровень КС)
    "overrides": {"<ticker>": {"bond_type": "floater", "ytm_pct": ...}},  # опц.
    "params": {...}                            # см. DEFAULT_PARAMS
  }

Выход: {"bond_carry": {schema, params, per_position: {ticker: {kind, event_date,
by_horizon: {hNN: {t_live_months, matures_within, by_scenario: {s: {carry_pct,
ci_pct, components}}, expected_carry_pct, flags}}, flags}}, caveats, warnings}}

stdlib only (PyYAML — только в CLI для YAML-входов/выходов).
"""
from __future__ import annotations

import argparse
import calendar
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

# Sibling-импорт для base_value_rub (контракт баз расчёта, 2026-09-18) — тот же
# приём sys.path, что уже используется compute_per_position.py.
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from input_contract import compute_base_value_rub  # noqa: E402

DAYS_PER_MONTH = 30.4375  # 365.25 / 12 — как в aggregate_positions.py

DEFAULT_PARAMS: dict[str, float] = {
    "fx_reinvest_rate_pct": 5.0,     # ставка реинвеста FX-тела, %/год
    "sanctions_haircut": 0.25,       # доля carry, срезаемая haircut'ом (0 → выключен)
    "hy_spread_pp": 5.0,             # YTM-спред к базовой КС, выше — high-yield
    "sanctions_intensity_min": 1.0,  # sanctions-фактор сценария ≥ порога → haircut
    "distressed_ytm_mult": 2.0,      # ytm > mult × КС → distressed override
    "distressed_ytm_min_days": 30,   # событие (оферта/погашение) ближе N дней → порог ytm не применяется
    "distressed_offer_days": 30,     # оферта ближе N дней с ytm_to_offer < 0 → distressed
    "mm_spread_pp": 1.0,             # вычет из КС для MM/кэша (комиссия фонда + спред)
    "ci_rel": 0.10,                  # относительная полуширина CI ячейки carry
    "default_coupon_freq": 2,        # fallback частоты купона
}

# Money-market тикеры — синхронно с compute_per_position.MONEY_MARKET_TICKERS.
MONEY_MARKET_TICKERS = {"TPAY", "TMON", "LQDT", "SBMM"}

# nominal_currency → канонический FX-фактор сценария. SUR/RUR — рублёвые (MOEX-конвенция).
_RUB_ALIASES = {"RUB", "SUR", "RUR", ""}
_FX_FACTOR = {"USD": "usdrub", "CNY": "cnyrub", "EUR": "usdrub"}  # EUR — прокси

CASH_KEY = "CASH_RUB"


# ───────────────────────────── date helpers ─────────────────────────────

def _parse_date(s: Any) -> date | None:
    if isinstance(s, date):
        return s
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _months_between(d_from: date, d_to: date) -> float:
    return (d_to - d_from).days / DAYS_PER_MONTH


def _add_months(d: date, months: int) -> date:
    """d + months, день сохраняется (клампится к концу месяца)."""
    idx = d.year * 12 + (d.month - 1) + months
    y, m = idx // 12, idx % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _add_months_eom(d: date, months: int) -> date:
    idx = d.year * 12 + (d.month - 1) + months
    y, m = idx // 12, idx % 12 + 1
    return date(y, m, calendar.monthrange(y, m)[1])


def _earliest(*dates: Any) -> date | None:
    parsed = [d for d in (_parse_date(x) for x in dates) if d is not None]
    return min(parsed) if parsed else None


# ───────────────── сценарная траектория фактора (кусочно-линейная) ─────────────────

class FactorPath:
    """Δфактора(t) для одного сценария: кусочно-линейный путь через (0, 0) и точки
    (NN месяцев, значение factors_by_horizon[hNN][factor]); за последней точкой — flat."""

    def __init__(self, scenario: dict, factor: str, horizon_months: dict[str, float]):
        pts: list[tuple[float, float]] = [(0.0, 0.0)]
        fbh = scenario.get("factors_by_horizon") or {}
        for hk, factors in fbh.items():
            if not isinstance(factors, dict):
                continue
            v = factors.get(factor)
            m = horizon_months.get(hk)
            if v is None or m is None:
                continue
            try:
                pts.append((float(m), float(v)))
            except (TypeError, ValueError):
                continue
        self.points = sorted(pts)

    def at(self, t: float) -> float:
        pts = self.points
        if t <= 0 or len(pts) == 1:
            return 0.0
        for i in range(1, len(pts)):
            t0, v0 = pts[i - 1]
            t1, v1 = pts[i]
            if t <= t1:
                if t1 == t0:
                    return v1
                return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
        return pts[-1][1]  # за последней точкой — flat

    def average(self, a: float, b: float) -> float:
        """Средний Δ на [a, b] — трапеции по узлам пути. a == b → точечное значение."""
        if b <= a:
            return self.at(a)
        knots = [a] + [t for t, _ in self.points if a < t < b] + [b]
        area = 0.0
        for i in range(1, len(knots)):
            t0, t1 = knots[i - 1], knots[i]
            area += (self.at(t0) + self.at(t1)) / 2.0 * (t1 - t0)
        return area / (b - a)


# ───────────────────────────── купонное расписание ─────────────────────────────

def coupon_dates(
    next_coupon: date | None,
    freq_per_year: int,
    as_of: date,
    end: date,
) -> tuple[list[date], bool]:
    """
    Даты купонов в (as_of, end] от next_coupon с шагом 12/freq мес.
    next_coupon отсутствует → первая выплата через 12/freq мес от as_of,
    возвращается estimated=True.
    """
    step = max(1, round(12 / max(1, freq_per_year)))
    estimated = False
    if next_coupon is None:
        estimated = True
        next_coupon = _add_months(as_of, step)
    out: list[date] = []
    d = next_coupon
    # догоняем будущее, если next_coupon в прошлом (устаревший снапшот)
    guard = 0
    while d <= as_of and guard < 400:
        d = _add_months(d, step)
        guard += 1
    while d <= end and guard < 400:
        out.append(d)
        d = _add_months(d, step)
        guard += 1
    return out, estimated


# ───────────────────────────── carry одной облигации ─────────────────────────────

def _is_floater(holding: dict, override: dict | None) -> bool:
    """Порядок источников (PSS-12): явный override → plan_subtype снапшота →
    эвристика по имени (fallback, реальные имена ОФЗ-ПК вида «ОФЗ 29014» её не
    ловят — до фикса такие бумаги ошибочно шли по pull-to-par/фикс-купону)."""
    if override and str(override.get("bond_type", "")).lower() == "floater":
        return True
    if str(holding.get("plan_subtype") or "") == "Флоат":
        return True
    name = (holding.get("name") or "").lower()
    return "флоатер" in name or "floater" in name


def _fx_factor_for(holding: dict) -> tuple[str | None, bool]:
    """(имя FX-фактора | None для RUB, eur_proxy?)."""
    cur = (holding.get("nominal_currency") or "RUB").upper()
    if cur in _RUB_ALIASES:
        return None, False
    return _FX_FACTOR.get(cur, "usdrub"), (cur == "EUR")


def _near_event(holding: dict, override: dict | None, as_of: date, params: dict) -> bool:
    """До ближайшего события (оферта/погашение, с учётом override) < distressed_ytm_min_days."""
    ov = override or {}
    ev = _earliest(ov.get("offer_date", holding.get("offer_date")),
                   ov.get("maturity_date", holding.get("maturity_date")))
    if ev is None:
        return False
    return 0 <= (ev - as_of).days < params.get("distressed_ytm_min_days", 30)


def _ytm_over_threshold(holding: dict, override: dict | None, baseline_cbr: float,
                        params: dict) -> bool:
    ov = override or {}
    ytm = ov.get("ytm_pct", holding.get("ytm_pct"))
    if ytm is None or baseline_cbr <= 0:
        return False
    try:
        return float(ytm) > params["distressed_ytm_mult"] * baseline_cbr
    except (TypeError, ValueError):
        return False


def check_distressed(
    holding: dict, override: dict | None, baseline_cbr: float,
    as_of: date, params: dict,
) -> str | None:
    """Причина distressed-override или None."""
    ov = override or {}
    ytm = ov.get("ytm_pct", holding.get("ytm_pct"))
    if ytm is not None and baseline_cbr > 0 and not _near_event(holding, ov, as_of, params):
        try:
            if float(ytm) > params["distressed_ytm_mult"] * baseline_cbr:
                return (f"ytm {float(ytm):.1f}% > {params['distressed_ytm_mult']:g}× "
                        f"базовой КС {baseline_cbr:.1f}%")
        except (TypeError, ValueError):
            pass
    offer = _parse_date(ov.get("offer_date", holding.get("offer_date")))
    yto = ov.get("ytm_to_offer_pct", holding.get("ytm_to_offer_pct"))
    if offer is not None and yto is not None:
        try:
            days = (offer - as_of).days
            if 0 <= days <= params["distressed_offer_days"] and float(yto) < 0:
                return (f"оферта {offer.isoformat()} через {days} дн "
                        f"с ytm_to_offer {float(yto):.1f}% < 0")
        except (TypeError, ValueError):
            pass
    return None


def compute_bond_cell(
    holding: dict,
    scenario: dict,
    cbr_path: FactorPath,
    fx_path: FactorPath | None,
    as_of: date,
    horizon_end: date,
    baseline_cbr: float,
    params: dict,
    *,
    floater: bool,
    hy_bond: bool,
) -> dict:
    """Carry (% от текущей стоимости позиции) одной облигации на (горизонт × сценарий)."""
    H = _months_between(as_of, horizon_end)
    price = holding.get("current_price")
    price = float(price) if price else 100.0
    freq = int(holding.get("coupon_freq_per_year") or params["default_coupon_freq"])
    coupon_rate = float(holding.get("coupon_pct") or 0.0)

    event = _earliest(holding.get("offer_date"), holding.get("maturity_date"))
    matures = event is not None and event <= horizon_end
    t_live = min(H, max(0.0, _months_between(as_of, event))) if event else H
    flow_end = min(event, horizon_end) if event else horizon_end

    flags: list[str] = []
    comp = {"coupons": 0.0, "pull_to_par": 0.0, "fx_income": 0.0, "reinvest": 0.0}

    # ── купоны ──
    dates, estimated = coupon_dates(
        _parse_date(holding.get("next_coupon_date")), freq, as_of, flow_end)
    if estimated:
        flags.append("coupon_schedule_estimated")
    for d in dates:
        t = _months_between(as_of, d)
        rate = coupon_rate
        if floater:
            rate = max(0.0, coupon_rate + cbr_path.at(t))
        base_pct = (rate / freq) * 100.0 / price  # % от чистой цены за один купон
        comp["coupons"] += base_pct
        if fx_path is not None:
            comp["fx_income"] += base_pct * fx_path.at(t) / 100.0
    if floater and dates:
        flags.append("floater_coupon_adjusted")

    # ── pull-to-par + FX тела + реинвест (только при событии внутри горизонта) ──
    if matures:
        pull = (100.0 - price) / price * 100.0
        comp["pull_to_par"] += pull
        fx_body = 0.0
        if fx_path is not None:
            fx_body = (100.0 / price) * fx_path.at(t_live)
            comp["fx_income"] += fx_body
        if H - t_live > 1e-9:
            base = 1.0 + (pull + fx_body) / 100.0  # тело+par на момент t_live
            if fx_path is None:
                avg_rate = baseline_cbr + cbr_path.average(t_live, H)
                comp["reinvest"] += base * avg_rate * (H - t_live) / 12.0
            else:
                comp["reinvest"] += (base * params["fx_reinvest_rate_pct"]
                                     * (H - t_live) / 12.0)
                # продолжение FX-движения на реинвестированное тело
                comp["reinvest"] += base * (fx_path.at(H) - fx_path.at(t_live))
            flags.append("reinvested")

    # ── санкционный haircut (решение C): явный отрицательный компонент ──
    subtotal = sum(comp.values())
    haircut = 0.0
    sanctions_now = _sanctions_at_horizon(scenario, horizon_end, as_of)
    if (hy_bond and params["sanctions_haircut"] > 0
            and sanctions_now >= params["sanctions_intensity_min"]
            and subtotal > 0):
        haircut = -params["sanctions_haircut"] * subtotal
        flags.append("sanctions_haircut_applied")

    carry = subtotal + haircut
    half = abs(carry) * params["ci_rel"]
    cell = {
        "carry_pct": round(carry, 4),
        "ci_pct": [round(carry - half, 4), round(carry + half, 4)],
        "components": {k: round(v, 4) for k, v in comp.items()},
    }
    if haircut:
        cell["components"]["sanctions_haircut"] = round(haircut, 4)
    return {"cell": cell, "flags": flags, "t_live_months": round(t_live, 2),
            "matures_within": matures}


def _sanctions_at_horizon(scenario: dict, horizon_end: date, as_of: date) -> float:
    """Sanctions-intensity сценария на горизонте (ближайший hNN по месяцам)."""
    fbh = scenario.get("factors_by_horizon") or {}
    target = _months_between(as_of, horizon_end)
    best_v, best_d = 0.0, None
    for hk, factors in fbh.items():
        if not isinstance(factors, dict) or not hk.startswith("h"):
            continue
        try:
            m = float(hk[1:])
        except ValueError:
            continue
        v = factors.get("sanctions")
        if v is None:
            continue
        d = abs(m - target)
        if best_d is None or d < best_d:
            best_d, best_v = d, float(v)
    return best_v


# ───────────────────────────── MM / cash carry ─────────────────────────────

def compute_mm_cell(
    cbr_path: FactorPath, as_of: date, horizon_end: date,
    baseline_cbr: float, params: dict,
) -> dict:
    H = _months_between(as_of, horizon_end)
    avg_rate = baseline_cbr + cbr_path.average(0.0, H) - params["mm_spread_pp"]
    carry = avg_rate * H / 12.0
    half = abs(carry) * params["ci_rel"]
    return {
        "carry_pct": round(carry, 4),
        "ci_pct": [round(carry - half, 4), round(carry + half, 4)],
        "components": {"mm_rate": round(carry, 4)},
    }


# ───────────────────────────── сборка позиции ─────────────────────────────

def _zero_cell(params: dict) -> dict:
    return {"carry_pct": 0.0, "ci_pct": [0.0, 0.0],
            "components": {"coupons": 0.0, "pull_to_par": 0.0,
                           "fx_income": 0.0, "reinvest": 0.0}}


def _p_norm(scenarios: dict, horizon_key: str | None = None) -> dict[str, float]:
    """
    Нормированные веса сценариев. PSS-9: если задан horizon_key и у сценариев есть
    `p_by_horizon[hk]` — берутся горизонтные веса, иначе скаляр `p`/`probability`
    (прежнее поведение бит-в-бит).

    Смешанный вход — блок есть у части сценариев или ключа hk нет у части —
    останавливает расчёт. Частично заданные убеждения молча усреднять со скаляром
    нельзя: получится правдоподобное число на смеси двух разных убеждений.
    SystemExit, а не ValueError: соглашение модуля, сырой ValueError вылезет
    трейсбеком вместо внятного сообщения.
    """
    if horizon_key is not None:
        have = {sid: sc.get("p_by_horizon") for sid, sc in scenarios.items()}
        with_key = {sid: blk[horizon_key] for sid, blk in have.items()
                    if isinstance(blk, dict) and horizon_key in blk}
        if with_key and len(with_key) != len(scenarios):
            missing = sorted(set(scenarios) - set(with_key))
            raise SystemExit(
                f"ERROR: p_by_horizon[{horizon_key}] задан не у всех сценариев "
                f"(нет у {', '.join(missing)}). Смешивать горизонтные веса со "
                f"скаляром нельзя — задай блок всем сценариям или никому."
            )
        if with_key:
            ps = {sid: float(v or 0) for sid, v in with_key.items()}
            total = sum(ps.values())
            if total <= 0:
                raise SystemExit(
                    f"ERROR: сумма p_by_horizon[{horizon_key}] = {total}; "
                    f"нормировать нечего."
                )
            return {sid: v / total for sid, v in ps.items()}
    ps = {sid: float(sc.get("p", sc.get("probability", 0)) or 0)
          for sid, sc in scenarios.items()}
    total = sum(ps.values())
    if total <= 0:
        n = len(ps) or 1
        return {sid: 1.0 / n for sid in ps}
    return {sid: p / total for sid, p in ps.items()}


def _resolve_horizon_ends(
    scenarios: dict, horizon_ends_in: dict | None, as_of: date,
) -> dict[str, date]:
    """{hNN: date}: из payload.horizon_ends или as_of + NN (конец месяца)."""
    keys: set[str] = set()
    for sc in scenarios.values():
        fbh = (sc or {}).get("factors_by_horizon")
        if isinstance(fbh, dict):
            keys.update(k for k in fbh if isinstance(k, str) and k.startswith("h"))
    if horizon_ends_in:
        keys.update(k for k in horizon_ends_in if isinstance(k, str) and k.startswith("h"))
    out: dict[str, date] = {}
    for hk in keys:
        d = _parse_date((horizon_ends_in or {}).get(hk))
        if d is None:
            try:
                d = _add_months_eom(as_of, int(hk[1:]))
            except ValueError:
                continue
        out[hk] = d
    return dict(sorted(out.items(), key=lambda kv: kv[1]))


def _portfolio_level_carry_by_horizon(
    per_position: dict[str, Any], horizon_ends: dict[str, date],
    scenarios: dict[str, Any], base_value_rub: float,
) -> dict[str, Any]:
    """Портфельный ролл-ап Layer 2: Σ value_rub × carry_pct/100 по всем позициям
    (бумаги, MM-фонды, кэш — единообразно, у всех одна форма entry). carry_pct
    результата — от base_value_rub, чтобы иметь общий знаменатель с Layer 1."""
    out: dict[str, Any] = {}
    for hk in horizon_ends:
        cell: dict[str, Any] = {}
        for sid in scenarios:
            carry_rub = 0.0
            for pos in per_position.values():
                by_h = (pos.get("by_horizon") or {}).get(hk)
                if not by_h:
                    continue
                sc_cell = (by_h.get("by_scenario") or {}).get(sid)
                if not sc_cell:
                    continue
                value_rub = pos.get("value_rub") or 0.0
                carry_rub += value_rub * (sc_cell.get("carry_pct", 0.0) / 100.0)
            carry_pct = (carry_rub / base_value_rub * 100.0) if base_value_rub else 0.0
            cell[sid] = {"carry_rub": round(carry_rub), "carry_pct": round(carry_pct, 4)}
        out[hk] = cell
    return out


def run(payload: dict) -> dict:
    snapshot = payload.get("snapshot") or {}
    scenarios = payload.get("scenarios") or {}
    if not scenarios:
        raise SystemExit("ERROR: scenarios обязательны (factors_by_horizon per scenario)")

    as_of = _parse_date(payload.get("as_of") or snapshot.get("as_of_date"))
    if as_of is None:
        raise SystemExit("ERROR: as_of не задан и отсутствует в snapshot.as_of_date "
                         "(детерминизм без Date.now())")

    baseline = payload.get("baseline") or {}
    baseline_cbr = baseline.get("cbr_rate_pct")
    if baseline_cbr is None:
        raise SystemExit("ERROR: baseline.cbr_rate_pct обязателен (уровень КС для "
                         "реинвеста, MM-carry и distressed-порога)")
    baseline_cbr = float(baseline_cbr)

    params = dict(DEFAULT_PARAMS)
    params.update(payload.get("params") or {})
    overrides = payload.get("overrides") or {}

    horizon_ends = _resolve_horizon_ends(scenarios, payload.get("horizon_ends"), as_of)
    if not horizon_ends:
        raise SystemExit("ERROR: не удалось определить горизонты (нет factors_by_horizon "
                         "в сценариях и нет horizon_ends)")
    horizon_months = {hk: _months_between(as_of, d) for hk, d in horizon_ends.items()}
    # PSS-9: веса на КАЖДЫЙ горизонт. Один набор на все горизонты означал бы, что
    # ценовая нога и carry считаются на разных убеждениях, когда заданы
    # p_by_horizon. Вычисляется здесь, потому что hk появляется только в циклах ниже.
    p_norm_by_h = {hk: _p_norm(scenarios, hk) for hk in horizon_ends}

    # Пути факторов на сценарий (общие для всех бумаг)
    cbr_paths = {sid: FactorPath(sc, "cbr_rate", horizon_months)
                 for sid, sc in scenarios.items()}
    fx_paths = {
        sid: {f: FactorPath(sc, f, horizon_months) for f in ("usdrub", "cnyrub")}
        for sid, sc in scenarios.items()
    }

    per_position: dict[str, Any] = {}
    caveats: list[dict] = []
    warnings: list[str] = []
    eur_proxied: list[str] = []
    price_assumed: list[str] = []

    holdings = snapshot.get("holdings") or []

    # Стоимость по тикеру ДО дедупа — бумага на main+iis_3 несёт две записи с
    # одинаковыми bond-полями, но РАЗНОЙ value_rub, а дедуп ниже видит только
    # первую и `continue`-ит вторую. Без этой суммы portfolio_level_by_horizon
    # (ниже) потерял бы стоимость второй ноги — тот же класс потери, что уже
    # ловился на per_position (2026-08-04, потеря 0.33% позиционной части).
    def _value_by_ticker(asset_type: str, tickers: set[str] | None = None) -> dict[str, float]:
        out: dict[str, float] = {}
        for hh in holdings:
            if tickers is None:
                if (hh.get("asset_type") or "").lower() != asset_type:
                    continue
            elif (hh.get("ticker") or "").upper() not in tickers:
                continue
            if hh.get("is_blocked") or (hh.get("value_rub") or 0) <= 0:
                continue
            t = (hh.get("ticker") or "").upper()
            if t:
                out[t] = out.get(t, 0.0) + float(hh["value_rub"])
        return out

    bond_value_by_ticker = _value_by_ticker("bond")
    mm_value_by_ticker = _value_by_ticker("", tickers=MONEY_MARKET_TICKERS)

    # ── облигации (dedup по тикеру: main + iis_3 несут идентичные bond-поля) ──
    seen: set[str] = set()
    for h in holdings:
        if (h.get("asset_type") or "").lower() != "bond":
            continue
        if h.get("is_blocked") or (h.get("value_rub") or 0) <= 0:
            continue
        ticker = (h.get("ticker") or "").upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)

        ov = overrides.get(ticker)
        floater = _is_floater(h, ov)
        fx_name, eur_proxy = _fx_factor_for(h)
        if eur_proxy:
            eur_proxied.append(ticker)
        if not h.get("current_price"):
            price_assumed.append(ticker)

        distressed_reason = check_distressed(h, ov, baseline_cbr, as_of, params)

        ytm = (ov or {}).get("ytm_pct", h.get("ytm_pct"))
        # у события ближе distressed_ytm_min_days доходность раздута коротким сроком — спред по ней не меряется
        hy_bond = (ytm is not None and baseline_cbr > 0
                   and float(ytm) - baseline_cbr > params["hy_spread_pp"]
                   and not _near_event(h, ov, as_of, params))

        event = _earliest(h.get("offer_date"), h.get("maturity_date"))
        pos_flags: list[str] = []
        if eur_proxy:
            pos_flags.append("eur_fx_proxy_usdrub")
        if not h.get("current_price"):
            pos_flags.append("price_missing_assumed_par")
        if distressed_reason:
            pos_flags.append("credit_review_required")
        elif (_ytm_over_threshold(h, ov, baseline_cbr, params)
              and _near_event(h, ov, as_of, params)):
            pos_flags.append("ytm_threshold_skipped_near_event")

        by_horizon: dict[str, Any] = {}
        for hk, hend in horizon_ends.items():
            by_scenario: dict[str, Any] = {}
            h_flags: set[str] = set()
            t_live = None
            matures = False
            for sid, sc in scenarios.items():
                if distressed_reason:
                    by_scenario[sid] = _zero_cell(params)
                    ev = event
                    t_live = (round(min(horizon_months[hk],
                                        max(0.0, _months_between(as_of, ev))), 2)
                              if ev else round(horizon_months[hk], 2))
                    matures = ev is not None and ev <= hend
                    continue
                res = compute_bond_cell(
                    h, sc, cbr_paths[sid],
                    fx_paths[sid].get(fx_name) if fx_name else None,
                    as_of, hend, baseline_cbr, params,
                    floater=floater, hy_bond=hy_bond,
                )
                by_scenario[sid] = res["cell"]
                h_flags.update(res["flags"])
                t_live = res["t_live_months"]
                matures = res["matures_within"]
            expected = round(sum(p_norm_by_h[hk][sid] * by_scenario[sid]["carry_pct"]
                                 for sid in by_scenario), 4)
            by_horizon[hk] = {
                "t_live_months": t_live,
                "matures_within": matures,
                "by_scenario": by_scenario,
                "expected_carry_pct": expected,
                "flags": sorted(h_flags),
            }

        entry: dict[str, Any] = {
            "kind": "bond",
            "event_date": event.isoformat() if event else None,
            "value_rub": round(bond_value_by_ticker.get(ticker, 0.0), 2),
            "by_horizon": by_horizon,
            "flags": pos_flags,
        }
        if distressed_reason:
            entry["credit_review_reason"] = distressed_reason
            caveats.append({
                "severity": "HIGH",
                "message": (f"{ticker}: distressed override — наивный carry не посчитан "
                            f"({distressed_reason}). Carry = 0 (консервативный пол), "
                            f"нужен кредитный разбор (credit_review_required)."),
            })
        per_position[ticker] = entry

    # ── money-market фонды (по тикеру, независимо от asset_type в снапшоте) ──
    mm_seen: set[str] = set()
    for h in holdings:
        ticker = (h.get("ticker") or "").upper()
        if ticker not in MONEY_MARKET_TICKERS or ticker in mm_seen:
            continue
        if h.get("is_blocked") or (h.get("value_rub") or 0) <= 0:
            continue
        mm_seen.add(ticker)
        by_horizon = {}
        for hk, hend in horizon_ends.items():
            by_scenario = {sid: compute_mm_cell(cbr_paths[sid], as_of, hend,
                                                baseline_cbr, params)
                           for sid in scenarios}
            by_horizon[hk] = {
                "t_live_months": round(horizon_months[hk], 2),
                "matures_within": False,
                "by_scenario": by_scenario,
                "expected_carry_pct": round(
                    sum(p_norm_by_h[hk][sid] * by_scenario[sid]["carry_pct"]
                        for sid in by_scenario), 4),
                "flags": ["mm_proxy"],
            }
        per_position[ticker] = {"kind": "money_market", "event_date": None,
                                "value_rub": round(mm_value_by_ticker.get(ticker, 0.0), 2),
                                "by_horizon": by_horizon, "flags": ["mm_proxy"]}

    # ── голый RUB-кэш: carry по КС-траектории (решение владельца 2026-07-02) ──
    cash_rub = ((snapshot.get("cash") or {}).get("total_rub") or 0)
    if cash_rub and cash_rub > 0:
        by_horizon = {}
        for hk, hend in horizon_ends.items():
            by_scenario = {sid: compute_mm_cell(cbr_paths[sid], as_of, hend,
                                                baseline_cbr, params)
                           for sid in scenarios}
            by_horizon[hk] = {
                "t_live_months": round(horizon_months[hk], 2),
                "matures_within": False,
                "by_scenario": by_scenario,
                "expected_carry_pct": round(
                    sum(p_norm_by_h[hk][sid] * by_scenario[sid]["carry_pct"]
                        for sid in by_scenario), 4),
                "flags": ["cash_carry_assumed_mm"],
            }
        per_position[CASH_KEY] = {
            "kind": "cash", "event_date": None, "by_horizon": by_horizon,
            "value_rub": round(float(cash_rub), 2),
            "flags": ["cash_carry_assumed_mm"],
        }
        caveats.append({
            "severity": "MEDIUM",
            "message": (f"Голый RUB-кэш ({round(float(cash_rub)):,} ₽) получает carry по "
                        f"КС − {params['mm_spread_pp']:g} пп как «мог бы лежать в MM-фонде» "
                        f"— это допущение размещения, не факт (cash_carry_assumed_mm)."),
        })

    if eur_proxied:
        warnings.append(f"EUR-облигации через usdrub-прокси (нет eurrub-фактора): "
                        f"{', '.join(sorted(eur_proxied))}")
    if price_assumed:
        warnings.append(f"Нет current_price, принята цена 100 (par): "
                        f"{', '.join(sorted(price_assumed))}")

    caveats.append({
        "severity": "HIGH",
        "message": ("Слой 2 сознательно НЕ моделирует: реинвест промежуточных купонов "
                    "(~1–1.5 пп на 24 мес в верхней оценке), амортизацию, roll-down, "
                    "налоги; базис — чистая цена (НКД < 0.5 пп). Доход аккумулирующих "
                    "фондов (TLCB/SBGB) не входит в carry-слой (задача в TODO)."),
    })

    base_value_rub = compute_base_value_rub(snapshot)
    portfolio_level_by_horizon = _portfolio_level_carry_by_horizon(
        per_position, horizon_ends, scenarios, base_value_rub)

    return {
        "bond_carry": {
            "schema": "bond-carry@1",
            "as_of": as_of.isoformat(),
            "baseline_cbr_rate_pct": baseline_cbr,
            "horizon_ends": {hk: d.isoformat() for hk, d in horizon_ends.items()},
            "params": params,
            "base_value_rub": round(base_value_rub),
            "per_position": per_position,
            # Контракт баз расчёта (2026-09-18): portfolio_level_by_horizon[hNN][sid]
            # = {carry_rub, carry_pct} — Σ value_rub × carry_pct/100 по позициям,
            # carry_pct от base_value_rub (не от суммы позиций — иначе процент без
            # общего знаменателя). compute_portfolio_aggregates.py копирует это
            # as-is в scenarios.<X>.portfolio_level_by_horizon.<hNN>, без пересчёта.
            "portfolio_level_by_horizon": portfolio_level_by_horizon,
            "caveats": caveats,
            "warnings": warnings,
        }
    }


# ───────────────────────────── CLI ─────────────────────────────

def _load_any(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError:
            sys.stderr.write("ERROR: pyyaml не установлен (нужен для YAML-входа). "
                             "pip install pyyaml --break-system-packages\n")
            sys.exit(2)
        return yaml.safe_load(text)
    return json.loads(text)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Bond carry (Слой 2 total-return): купоны + pull-to-par + реинвест "
                    "per bond × horizon × scenario. Выход — блок bond_carry для stress-YAML.")
    ap.add_argument("--snapshot", required=True, type=Path, help="portfolio-{date}.json")
    ap.add_argument("--scenarios", required=True, type=Path,
                    help="YAML/JSON со scenarios (p + factors_by_horizon), напр. стаб stress")
    ap.add_argument("--baseline", type=Path, default=None,
                    help="JSON/YAML с baseline (мин. cbr_rate_pct); либо --baseline-cbr")
    ap.add_argument("--baseline-cbr", type=float, default=None,
                    help="Уровень ключевой ставки, %% (альтернатива --baseline)")
    ap.add_argument("--horizon-ends", type=Path, default=None,
                    help="JSON {hNN: YYYY-MM-DD}; default — as_of + NN (конец месяца)")
    ap.add_argument("--overrides", type=Path, default=None,
                    help="JSON {ticker: {bond_type, ytm_pct, ...}} из weekly-bonds-review")
    ap.add_argument("--output", type=Path, default=None,
                    help="Файл выхода (.yaml → YAML-фрагмент, иначе JSON); default stdout JSON")
    ap.add_argument("--pretty", action="store_true")
    for key, default in DEFAULT_PARAMS.items():
        ap.add_argument(f"--{key.replace('_', '-')}", type=float, default=None,
                        help=f"параметр (default {default})")
    args = ap.parse_args()

    snapshot = _load_any(args.snapshot)
    scen_doc = _load_any(args.scenarios)
    scenarios = scen_doc.get("scenarios", scen_doc)

    baseline: dict[str, Any] = {}
    if args.baseline:
        baseline = _load_any(args.baseline)
        baseline = baseline.get("baseline_spot", baseline)
    if args.baseline_cbr is not None:
        baseline["cbr_rate_pct"] = args.baseline_cbr
    if not baseline.get("cbr_rate_pct") and isinstance(scen_doc, dict):
        bs = scen_doc.get("baseline_spot")
        if isinstance(bs, dict) and bs.get("cbr_rate_pct") is not None:
            baseline["cbr_rate_pct"] = bs["cbr_rate_pct"]

    horizon_ends = None
    if args.horizon_ends:
        horizon_ends = _load_any(args.horizon_ends)
    elif isinstance(scen_doc, dict) and isinstance(scen_doc.get("horizon_ends"), dict):
        horizon_ends = scen_doc["horizon_ends"]

    params = {k: v for k in DEFAULT_PARAMS
              if (v := getattr(args, k)) is not None}

    payload = {
        "snapshot": snapshot,
        "scenarios": scenarios,
        "baseline": baseline,
        "horizon_ends": horizon_ends,
        "overrides": _load_any(args.overrides) if args.overrides else None,
        "params": params,
    }
    result = run(payload)

    if args.output and args.output.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError:
            sys.stderr.write("ERROR: pyyaml не установлен для YAML-выхода.\n")
            return 2
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as f:
            f.write("# Auto-generated by compute_bond_carry.py — блок bond_carry "
                    "для stress-YAML (Слой 2 total-return)\n")
            f.write(yaml.safe_dump(result, allow_unicode=True, sort_keys=False,
                                   default_flow_style=False))
        print(f"OK: bond_carry → {args.output}")
    else:
        text = json.dumps(result, ensure_ascii=False,
                          indent=2 if args.pretty else None)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
            print(f"OK: bond_carry → {args.output}")
        else:
            sys.stdout.write(text + "\n")

    bc = result["bond_carry"]
    n_bonds = sum(1 for v in bc["per_position"].values() if v["kind"] == "bond")
    n_distressed = sum(1 for v in bc["per_position"].values()
                       if "credit_review_required" in v.get("flags", []))
    sys.stderr.write(f"Позиций: {len(bc['per_position'])} (облигаций {n_bonds}, "
                     f"distressed {n_distressed}); warnings: {len(bc['warnings'])}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
