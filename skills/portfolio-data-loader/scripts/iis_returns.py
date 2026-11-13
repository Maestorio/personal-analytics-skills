#!/usr/bin/env python3
"""
Доходность счёта ИИС-3 (БКС) из ОТДЕЛЬНОЙ выгрузки IntelInvest — три числа.

  А. fact    — XIRR/ROI/TWR счёта: взносы → купоны → текущая грязная стоимость.
  Б. forward — доходность к погашению держимых бумаг по СЕГОДНЯШНЕЙ цене
               (IRR: −грязная стоимость сейчас + будущие купоны и погашения).
  В. locked  — «зафиксированная при покупке»: IRR по фактическим покупкам/
               продажам + полученные купоны + будущие потоки текущего остатка.

Контракт «файл приходит только после операций» (решение владельца 2026-10-12):
покупка / продажа / взнос на счёт сразу влекут свежую выгрузку; нет нового
файла → этих операций не было. Без участия владельца на счёте случаются только
купоны, поэтому купоны ПОСЛЕ последней даты файла достраиваются по графику
MOEX (bondization × количество на дату отсечки) с пометкой synthetic. Ничего
не хранится между прогонами: каждый запуск достраивает заново, и как только
приходит файл с реальным купоном (±window_days от даты графика), синтетика по
этому купону просто не создаётся. Реальные купоны на ИИС приходят брутто и
совпадают с графиком: 26244 — 56.10 × 100 = 5 610; 52004 — 18.84 × 180 = 3 391.2.
Погашение/амортизация по графику НЕ достраиваются — только флаг (редко, и сумма
у линкера зависит от индексации).

Линкер (ОФЗ-ИН): будущий номинал индексируется по инфляции. Путь инфляции —
Layer 1 прогноз `forecasts/inflation-ru-*.yaml` (`fca_stats[*].l1_weighted`,
последнее значение держится до погашения); нет прогноза → 4% (решение
владельца). Индексационный лаг ~3 мес. не моделируется (приближение).

SBGB и прочие фонды ОФЗ: в Б — прокси «средневзвешенная YTM состава RGBI»
(веса MOEX analytics, YTM MOEX), до вычета комиссии фонда; в В не входят
(у фонда нечего фиксировать). Кэш счёта в Б — 0%.

Вход:   trades_portfolio_<id>.xlsx (одна выгрузка счёта)
Выход:  JSON для assemble_snapshot.py --iis-returns (блок returns.by_account.iis_3)

Использование:
    python3 iis_returns.py --trades docs/investment/source/trades_portfolio_838526.xlsx \\
        --forecasts-dir ~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/forecasts \\
        --output /tmp/iis_returns.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
# moex_quotes: в бандле — в scripts/ рядом (pack.sh), в репо — канон _shared-references/.
_SHARED = Path(__file__).resolve().parents[3] / "_shared-references"
if _SHARED.is_dir() and str(_SHARED) not in sys.path:
    sys.path.append(str(_SHARED))
import portfolio_returns as pr  # noqa: E402

ISS = "https://iss.moex.com/iss"
DEFAULT_INFLATION_PCT = 4.0
COUPON_MATCH_WINDOW_DAYS = 10
FUND_PROXY_INDEX = "RGBI"
FUND_PROXY_MIN_COVERAGE = 0.9

TRADE_OPS = ("Покупка", "Продажа")
REDEMPTION_OPS = ("Погашение", "Амортизация")


# =============================================================================
# Сеть (только в main / fetch_*; ядро ниже — чистые функции)
# =============================================================================


def _get_json(url: str, timeout: int = 30, retries: int = 2) -> dict:
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001 — сетевые сбои однородны
            last = e
    raise RuntimeError(f"MOEX ISS недоступен: {url}: {last}")


def _rows(block: dict) -> list[dict]:
    cols = block.get("columns") or []
    return [dict(zip(cols, r)) for r in block.get("data") or []]


def fetch_schedule(secid: str) -> dict:
    """График купонов и погашений MOEX (bondization) одной бумаги."""
    d = _get_json(f"{ISS}/securities/{secid}/bondization.json"
                  f"?iss.meta=off&iss.only=coupons,amortizations&limit=unlimited")
    return {"coupons": _rows(d.get("coupons") or {}),
            "amortizations": _rows(d.get("amortizations") or {})}


def fetch_index_weights(index_id: str) -> dict[str, float]:
    d = _get_json(f"{ISS}/statistics/engines/stock/markets/index/analytics/"
                  f"{index_id}.json?iss.meta=off&limit=100")
    return {r["secids"]: float(r["weight"]) for r in _rows(d.get("analytics") or {})
            if r.get("secids") and r.get("weight") is not None}


def fetch_bond_quotes(secids: list[str]) -> dict[str, Any]:
    import moex_quotes as mq
    # Без kind_hint="bond": он ведёт на доску TQCB (корпоративные), и ОФЗ
    # с TQOB возвращаются not_in_response. Discovery находит обе доски.
    quotes, _errs = mq.fetch_quotes(secids, fields="weekly", parallel=True)
    return quotes


# =============================================================================
# Инфляция
# =============================================================================


def inflation_path_from_forecast(fc: dict | None) -> list[tuple[dt.date, float]]:
    """[(дата горизонта, CPI г/г %)] из fca_stats Layer 1; пусто — нет данных."""
    out: list[tuple[dt.date, float]] = []
    for k, v in ((fc or {}).get("fca_stats") or {}).items():
        if not isinstance(v, dict) or v.get("kind") != "level":
            continue
        val = v.get("l1_weighted")
        if not isinstance(val, (int, float)):
            continue
        try:
            out.append((dt.date.fromisoformat(str(k)), float(val)))
        except ValueError:
            continue
    return sorted(out)


def load_inflation(forecasts_dir: str | None) -> dict:
    """Последний активный inflation-ru-*.yaml с числовым Layer 1, иначе 4%."""
    fallback = {"source": "fallback", "path": [], "flat_pct": DEFAULT_INFLATION_PCT,
                "note": f"прогноза инфляции нет — принято {DEFAULT_INFLATION_PCT}%"}
    if not forecasts_dir:
        return fallback
    try:
        import yaml
    except ImportError:
        return {**fallback, "note": fallback["note"] + " (нет PyYAML)"}
    files = sorted(Path(forecasts_dir).expanduser().glob("inflation-ru-*.yaml"),
                   reverse=True)
    for f in files:
        try:
            fc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 — битый файл пропускаем, берём следующий
            continue
        if fc.get("status") not in (None, "active"):
            continue
        path = inflation_path_from_forecast(fc)
        if path:
            return {"source": f.name, "path": [(d.isoformat(), v) for d, v in path],
                    "flat_pct": None,
                    "note": "Layer 1 l1_weighted; после последнего горизонта — "
                            "последнее значение"}
    return fallback


def _pct_at(path: list[tuple[dt.date, float]], flat: float | None, day: dt.date) -> float:
    if not path:
        return flat if flat is not None else DEFAULT_INFLATION_PCT
    for d, v in path:
        if day <= d:
            return v
    return path[-1][1]


def cpi_factor(infl: dict, start: dt.date, end: dt.date) -> float:
    """Накопленная индексация start→end: кусочно-постоянная годовая инфляция.

    Значение горизонта трактуется как инфляция г/г, действующая на отрезке ДО
    этой даты (от предыдущего горизонта); после последнего — оно же.
    """
    if end <= start:
        return 1.0
    path = [(dt.date.fromisoformat(d), v) for d, v in infl.get("path") or []]
    flat = infl.get("flat_pct")
    log_f, cur = 0.0, start
    while cur < end:
        nxt = end
        for d, _v in path:
            if d > cur:
                nxt = min(nxt, d)
                break
        pct = _pct_at(path, flat, cur + dt.timedelta(days=1))
        log_f += math.log1p(pct / 100.0) * (nxt - cur).days / 365.0
        cur = nxt
    return math.exp(log_f)


# =============================================================================
# Купоны: количество на отсечку, достройка по графику
# =============================================================================


def _d(s: Any) -> dt.date | None:
    if isinstance(s, dt.date):
        return s
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def qty_at_record(trades: list[pr.Trade], ticker: str, record: dt.date) -> float:
    """Количество, дающее право на купон: сделки СТРОГО до даты отсечки (T+1)."""
    q = 0.0
    for t in trades:
        if t.ticker != ticker or t.date >= record or t.qty is None:
            continue
        if t.operation == "Покупка":
            q += t.qty
        elif t.operation == "Продажа":
            q -= t.qty
    return q


def synthesize_coupons(
    trades: list[pr.Trade],
    schedules: dict[str, dict],
    as_of: dt.date,
    window_days: int = COUPON_MATCH_WINDOW_DAYS,
) -> tuple[list[pr.Trade], list[dict], list[dict]]:
    """Купоны по графику, которых нет в файле, — после последней даты файла.

    Возвращает (синтетические сделки, их описание, флаги). Купон считается
    покрытым, если в файле есть «Купон» по бумаге в ±window_days от даты
    графика (реальные зачисления идут ±1 день). Непокрытый купон ВНУТРИ периода
    файла не достраивается — файл авторитетен, только флаг.
    """
    last_file = max((t.date for t in trades), default=as_of)
    real: dict[str, list[dt.date]] = defaultdict(list)
    for t in trades:
        if t.operation == "Купон":
            real[t.ticker].append(t.date)
    synth: list[pr.Trade] = []
    info: list[dict] = []
    flags: list[dict] = []
    for secid, sch in schedules.items():
        name = next((t.name for t in trades if t.ticker == secid), secid)
        for c in sch.get("coupons") or []:
            cdate, rdate = _d(c.get("coupondate")), _d(c.get("recorddate"))
            value = c.get("value_rub") if c.get("value_rub") is not None else c.get("value")
            if cdate is None or cdate > as_of:
                continue
            q = qty_at_record(trades, secid, rdate or cdate)
            if q <= 1e-9:
                continue
            if any(abs((d - cdate).days) <= window_days for d in real.get(secid, [])):
                continue
            if cdate <= last_file - dt.timedelta(days=window_days):
                flags.append({"code": "iis_coupon_missing_in_file", "secid": secid,
                              "date": cdate.isoformat(),
                              "message": f"{secid}: купон {cdate} по графику MOEX "
                                         f"отсутствует в выписке — файл авторитетен, "
                                         f"не достраивается"})
                continue
            if not isinstance(value, (int, float)):
                flags.append({"code": "iis_coupon_value_unknown", "secid": secid,
                              "date": cdate.isoformat(),
                              "message": f"{secid}: сумма купона {cdate} неизвестна MOEX"})
                continue
            amount = round(float(value) * q, 2)
            note = f"синтетика: купон по графику MOEX {cdate}, {q:g} × {value}"
            synth.append(pr.Trade(
                ticker=secid, name=name, operation="Купон", date=cdate, qty=q,
                price=None, nominal=None, nkd=None, commission=0.0, amount=amount,
                amount_no_comm=amount, currency="RUB", note=note,
                rub_amount=amount, rub_rate=1.0, is_synthetic=True))
            synth.append(pr.Trade(
                ticker="Деньги (RUB)", name="Российский рубль", operation="Внесение",
                date=cdate, qty=None, price=None, nominal=None, nkd=None,
                commission=0.0, amount=amount, amount_no_comm=amount, currency="RUB",
                note=note, rub_amount=amount, rub_rate=1.0, is_synthetic=True))
            info.append({"secid": secid, "date": cdate.isoformat(), "qty": q,
                         "value_per_bond": value, "amount_rub": amount})
        for a in sch.get("amortizations") or []:
            adate = _d(a.get("amortdate"))
            if adate is None or adate > as_of or adate <= last_file:
                continue
            if qty_at_record(trades, secid, adate) > 1e-9:
                flags.append({"code": "iis_redemption_not_in_file", "secid": secid,
                              "date": adate.isoformat(),
                              "message": f"{secid}: погашение/амортизация {adate} по "
                                         f"графику после даты файла — пришли свежую "
                                         f"выгрузку, по графику не достраивается"})
    return synth, info, flags


# =============================================================================
# Будущие потоки и IRR
# =============================================================================


def is_linker(schedule: dict, name: str = "") -> bool:
    if "ОФЗ-ИН" in (name or "").upper():
        return True
    for c in schedule.get("coupons") or []:
        n = str(c.get("name") or "").upper()
        if "ОФЗ-ИН" in n:
            return True
    return False


def future_flows(
    schedule: dict, qty: float, as_of: dt.date, infl: dict, linker: bool,
) -> tuple[list[tuple[dt.date, float]], list[str]]:
    """Купоны с датой выплаты > as_of + погашения/амортизации > as_of на qty бумаг.

    Фикс-купон — сумма MOEX (неизвестная → последняя известная, с оговоркой).
    Линкер — ставка × номинал, индексированный по пути инфляции, × дни/365;
    погашение — индексированный номинал, не ниже первоначального.
    """
    notes: list[str] = []
    flows: list[tuple[dt.date, float]] = []
    if qty <= 1e-9:
        return flows, notes
    coupons = schedule.get("coupons") or []
    amorts = schedule.get("amortizations") or []
    face_now = None
    for c in coupons:
        if c.get("facevalue") is not None:
            face_now = float(c["facevalue"])
    last_known = None
    for c in coupons:
        cd = _d(c.get("coupondate"))
        v = c.get("value_rub") if c.get("value_rub") is not None else c.get("value")
        if cd is not None and cd <= as_of and isinstance(v, (int, float)):
            last_known = float(v)
    for c in coupons:
        cd = _d(c.get("coupondate"))
        if cd is None or cd <= as_of:
            continue
        if linker:
            sd = _d(c.get("startdate"))
            rate = c.get("valueprc")
            if face_now is None or rate is None or sd is None:
                notes.append(f"линкер: нет данных купона {cd}")
                continue
            per_bond = (float(rate) / 100.0 * face_now * cpi_factor(infl, as_of, cd)
                        * (cd - sd).days / 365.0)
        else:
            v = c.get("value_rub") if c.get("value_rub") is not None else c.get("value")
            if isinstance(v, (int, float)):
                per_bond = float(v)
            elif last_known is not None:
                per_bond = last_known
                notes.append(f"купон {cd} неизвестен MOEX — взят последний известный")
            else:
                notes.append(f"купон {cd} неизвестен MOEX — пропущен")
                continue
        flows.append((cd, per_bond * qty))
    for a in amorts:
        ad = _d(a.get("amortdate"))
        if ad is None or ad <= as_of:
            continue
        if linker:
            init = float(a.get("initialfacevalue") or 1000.0)
            base = float(a.get("value_rub") or a.get("value") or face_now or init)
            per_bond = max(base * cpi_factor(infl, as_of, ad), init)
        else:
            v = a.get("value_rub") if a.get("value_rub") is not None else a.get("value")
            if not isinstance(v, (int, float)):
                notes.append(f"погашение {ad} без суммы — пропущено")
                continue
            per_bond = float(v)
        flows.append((ad, per_bond * qty))
    return sorted(flows), notes


def _irr(cfs: list[tuple[dt.date, float]]) -> float | None:
    if not cfs or not any(a < 0 for _, a in cfs) or not any(a > 0 for _, a in cfs):
        return None
    try:
        return pr.xirr(sorted(cfs))
    except Exception:  # noqa: BLE001 — нет сходимости = нет числа
        return None


def _pct(x: float | None) -> float | None:
    return round(x * 100, 2) if x is not None else None


def locked_for(
    schedule: dict, name: str, qty: float, as_of: dt.date, infl: dict,
    hist: list[tuple[dt.date, float]],
) -> dict:
    """«При покупке» одной облигации счёта: IRR(исторические потоки счёта + будущие по графику на qty).

    Общий помощник ИИС-3 (compute) и основного счёта (bond_locked): hist — потоки счёта (покупки −,
    продажи/купоны/амортизации/погашения +). Линкер — ещё locked_real_pct (будущие потоки без индексации).
    → {linker, fut, notes, locked_pct, locked_real_pct и fut_real у линкера}.
    """
    linker = is_linker(schedule, name)
    fut, notes = future_flows(schedule, qty, as_of, infl, linker)
    out: dict[str, Any] = {"linker": linker, "fut": fut, "notes": notes,
                           "locked_pct": _pct(_irr(hist + fut))}
    if linker:
        zero = {"source": "real", "path": [], "flat_pct": 0.0}
        fut0, _ = future_flows(schedule, qty, as_of, zero, True)
        out["locked_real_pct"] = _pct(_irr(hist + fut0))
        out["fut_real"] = fut0
    return out


def fund_proxy_ytm(weights: dict[str, float], ytm: dict[str, float]) -> tuple[float | None, float]:
    """Средневзвешенная YTM состава индекса; (yield %, покрытие доли весов)."""
    total = sum(weights.values())
    if total <= 0:
        return None, 0.0
    covered = {s: w for s, w in weights.items() if isinstance(ytm.get(s), (int, float))}
    cov = sum(covered.values()) / total
    if not covered:
        return None, 0.0
    y = sum(w * ytm[s] for s, w in covered.items()) / sum(covered.values())
    return round(y, 2), round(cov, 4)


# =============================================================================
# Сборка
# =============================================================================


def account_flows(trades: list[pr.Trade], positions: dict, as_of: dt.date) -> dict[str, dict]:
    """Потоки и остаток ИИС-3 по каждой бумаге — для разбивки per_instrument_xirr по счетам.

    Основная выгрузка содержит и сделки ИИС-3 (сумма двух счетов), поэтому часть счёта «основной»
    получается вычитанием этих потоков из суммарных (assemble_snapshot._split_by_account). Правила
    свёртки те же, что в per_security_xirr (покупка/продажа/купон/дивиденд/амортизация/корректировка,
    суммы в рублях по курсу на дату сделки), синтетические купоны и «Деньги» не входят.
    """
    out: dict[str, dict] = {}
    for t in trades:
        if t.is_synthetic or t.ticker.startswith("Деньги") or t.date > as_of:
            continue
        amt = abs(t.rub_amount)
        signed = t.rub_amount or 0.0
        d = out.setdefault(t.ticker, {
            "qty_now": 0.0, "buy_total_rub": 0.0, "sell_total_rub": 0.0, "coupons_rub": 0.0,
            "dividends_rub": 0.0, "amortization_rub": 0.0, "corr_buy_rub": 0.0, "corr_sell_rub": 0.0,
            "first_trade_date": t.date.isoformat(), "cashflows": []})
        d["first_trade_date"] = min(d["first_trade_date"], t.date.isoformat())
        key, sign = {"Покупка": ("buy_total_rub", -1), "Продажа": ("sell_total_rub", 1),
                     "Купон": ("coupons_rub", 1), "Дивиденд": ("dividends_rub", 1),
                     "Амортизация": ("amortization_rub", 1)}.get(t.operation, (None, 0))
        if key is None and t.operation == "Корректировка" and signed != 0:
            key, sign = ("corr_buy_rub", -1) if signed > 0 else ("corr_sell_rub", 1)
        if key is None:
            continue
        d[key] += amt
        d["cashflows"].append([t.date.isoformat(), round(sign * amt, 2)])
    for (tk, _cur), p in positions.items():
        if tk in out:
            out[tk]["qty_now"] += p.qty
    for d in out.values():
        for k, v in d.items():
            if isinstance(v, float):
                d[k] = round(v, 6 if k == "qty_now" else 2)
    return out


def _iis_live_basis(lb: dict | None) -> dict | None:
    """live_basis счёта для вьюера: потоки total (= fact.xirr), кэш и позиции; ограниченная часть
    и разбивка по типам счёту не нужны."""
    if not lb:
        return None
    return {k: lb[k] for k in ("terminal_date", "cash_rub", "flows_total", "positions") if k in lb}


def compute(
    trades: list[pr.Trade],
    *,
    as_of: dt.date,
    schedules: dict[str, dict],
    dirty_now: dict[str, float],
    moex_ytm: dict[str, float | None],
    isin_of: dict[str, str],
    infl: dict,
    fund_proxy: tuple[float | None, float],
    fact_report: dict | None,
    synth_info: list[dict],
    flags: list[dict],
    source_file: str,
) -> dict:
    """Чистая сборка блока по уже полученным данным (тестируется без сети).

    trades — уже с синтетическими купонами; dirty_now — грязная стоимость
    позиции в ₽ (бумаги) на as_of; fact_report — build_report по тем же trades.
    """
    by_ticker: dict[str, list[pr.Trade]] = defaultdict(list)
    for t in trades:
        by_ticker[t.ticker].append(t)
    positions = pr.reconstruct_positions(trades, as_of)
    snap = (fact_report or {}).get("snapshot_current") or {}
    rt = (fact_report or {}).get("returns_total") or {}

    held = []
    for (ticker, _cur), p in positions.items():
        if ticker.startswith("Деньги") or p.qty <= 1e-9:
            continue
        held.append((ticker, p))

    bonds_forward_cfs: list[tuple[dt.date, float]] = []
    bonds_locked_cfs: list[tuple[dt.date, float]] = []
    per_bond: list[dict] = []
    other: list[dict] = []
    value_bonds = value_funds = 0.0
    for ticker, p in sorted(held):
        kind = pr.classify_instrument_type(by_ticker[ticker])
        val = dirty_now.get(ticker)
        if kind != "bond" or ticker not in schedules:
            other.append({"secid": ticker, "kind": kind, "qty": p.qty,
                          "value_rub": round(val, 2) if val is not None else None})
            if kind == "fund" and val is not None:
                value_funds += val
            continue
        hist: list[tuple[dt.date, float]] = []
        for t in by_ticker[ticker]:
            if t.date > as_of:
                continue
            if t.operation == "Покупка":
                hist.append((t.date, -abs(t.rub_amount)))
            elif t.operation in ("Продажа", "Купон", "Амортизация", "Погашение"):
                hist.append((t.date, abs(t.rub_amount)))
        lk = locked_for(schedules[ticker], p.name, p.qty, as_of, infl, hist)
        linker, fut, notes = lk["linker"], lk["fut"], lk["notes"]
        fwd = [(as_of, -val)] + fut if val else []
        b_fwd = _irr(fwd)
        if val:
            bonds_forward_cfs.extend(fwd)
            value_bonds += val
        bonds_locked_cfs.extend(hist + fut)
        row = {
            "secid": ticker, "isin": isin_of.get(ticker), "name": p.name,
            "qty": p.qty, "value_rub": round(val, 2) if val is not None else None,
            "linker": linker,
            "forward_pct": _pct(b_fwd), "locked_pct": lk["locked_pct"],
            "moex_ytm_pct": moex_ytm.get(ticker),
        }
        if linker:
            # Реальная доходность — та же IRR без индексации (инфляция 0%).
            row["forward_real_pct"] = _pct(_irr([(as_of, -val)] + lk["fut_real"])) if val else None
            row["locked_real_pct"] = lk["locked_real_pct"]
        if notes:
            row["notes"] = notes
        per_bond.append(row)

    cash = snap.get("cash_balance_rub")
    fwd_bonds = _irr(bonds_forward_cfs)
    proxy_y, proxy_cov = fund_proxy
    fwd_account = None
    if fwd_bonds is not None:
        total = value_bonds + value_funds + float(cash or 0.0)
        acc = value_bonds * fwd_bonds * 100
        if value_funds:
            if proxy_y is None:
                acc = None
                flags.append({"code": "iis_fund_proxy_unavailable",
                              "message": f"прокси доходности фондов ({FUND_PROXY_INDEX}) "
                                         f"недоступен — forward счёта не считается"})
            else:
                acc += value_funds * proxy_y
        fwd_account = round(acc / total, 2) if acc is not None and total else None

    return {
        "account": "iis_3",
        "broker": "БКС",
        "source_file": source_file,
        "file_last_operation": max((t.date for t in trades if not t.is_synthetic),
                                   default=None).isoformat() if trades else None,
        "as_of": as_of.isoformat(),
        "fact": {
            "period_start": rt.get("period_start"),
            "years": rt.get("years"),
            "net_external_deposits_rub": rt.get("net_external_deposits_rub"),
            "received_coupons_rub": rt.get("received_coupons_rub"),
            "synthetic_coupons_rub": round(sum(s["amount_rub"] for s in synth_info), 2),
            "current_value_rub": rt.get("current_value_rub"),
            "pnl_rub": rt.get("pnl_rub"),
            "xirr": rt.get("xirr"),
            "roi": rt.get("roi"),
            "twr_dietz_annualized": rt.get("twr_dietz_annualized"),
            "bond_value_basis": ((fact_report or {}).get("parameters") or {}).get(
                "bond_value_basis"),
        },
        "forward": {
            "bonds_irr_pct": _pct(fwd_bonds),
            "fund_proxy": {"index": FUND_PROXY_INDEX, "ytm_pct": proxy_y,
                           "coverage": proxy_cov,
                           "note": "средневзвешенная YTM состава индекса, до "
                                   "комиссии фонда"},
            "account_pct": fwd_account,
            "account_note": "облигации — IRR книги, фонды — прокси, кэш — 0%; "
                            "взвешено по грязной стоимости",
        },
        "locked": {
            "bonds_irr_pct": _pct(_irr(bonds_locked_cfs)),
            "note": "покупки по факту + полученные купоны + будущие потоки "
                    "текущего остатка; фонды и кэш не входят",
        },
        "per_bond": per_bond,
        "other_positions": other,
        "positions": [{"secid": t, "isin": isin_of.get(t), "qty": p.qty}
                      for t, p in sorted(held)],
        "account_flows": account_flows(trades, positions, as_of),
        # Вход живой доходности счёта: потоки и позиции того же расчёта, что дал fact.xirr
        "live_basis": _iis_live_basis((fact_report or {}).get("live_basis")),
        "cash_rub": cash,
        "inflation_assumption": infl,
        "synthetic_coupons": synth_info,
        "flags": flags,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trades", required=True, help="Выгрузка IntelInvest счёта ИИС-3")
    ap.add_argument("--as-of", default=None, help="Дата расчёта ISO (default: today)")
    ap.add_argument("--forecasts-dir", default=None,
                    help="Claude-Memory/forecasts — для пути инфляции линкеров")
    ap.add_argument("--cbr-offline", action="store_true")
    ap.add_argument("--output", default=None)
    ap.add_argument("--types-cache", default=None, metavar="PATH",
                    help="справочник типов Portfolio/security-types.json (тип с Мосбиржи "
                         "перебивает эвристику); нет файла — без переопределений")
    ap.add_argument("--splits-file", default=None, metavar="PATH",
                    help="реестр сплитов Portfolio/known-splits.json (дополняет встроенный набор)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    pr.load_types_cache(args.types_cache)
    pr.load_known_splits(args.splits_file)

    as_of = dt.date.fromisoformat(args.as_of) if args.as_of else dt.date.today()
    trades = pr.parse_trades(args.trades)
    trades = pr.convert_trades_to_rub(trades, cbr_offline=args.cbr_offline)
    trades, corrections = pr.apply_corrections(trades)

    by_ticker: dict[str, list[pr.Trade]] = defaultdict(list)
    for t in trades:
        by_ticker[t.ticker].append(t)
    bonds = sorted({t.ticker for t in trades if not t.ticker.startswith("Деньги")
                    and pr.classify_instrument_type(by_ticker[t.ticker]) == "bond"})
    schedules = {s: fetch_schedule(s) for s in bonds}

    synth, synth_info, flags = synthesize_coupons(trades, schedules, as_of)
    trades_all = sorted(trades + synth, key=lambda t: t.date)

    report = pr.build_report(trades_all, corrections, as_of=as_of, use_moex=True,
                             verbose=args.verbose, with_benchmarks=False,
                             cbr_offline=args.cbr_offline)

    positions = pr.reconstruct_positions(trades_all, as_of)
    held = [k[0] for k, p in positions.items()
            if not k[0].startswith("Деньги") and p.qty > 1e-9]
    accrued: dict[str, float] = {}
    last, face, face_cur, _failed = pr.fetch_moex_prices(held, accrued_out=accrued)
    quotes = fetch_bond_quotes([s for s in held if s in schedules]) if bonds else {}
    dirty_now: dict[str, float] = {}
    for (tk, _c), p in positions.items():
        if tk not in held:
            continue
        kind = pr.classify_instrument_type(by_ticker[tk])
        if tk not in last:
            flags.append({"code": "iis_no_moex_price", "secid": tk,
                          "message": f"{tk}: нет цены MOEX — forward/locked без бумаги"})
            continue
        v, _src = pr.estimate_position_value_rub(
            p, kind, None, last[tk], face.get(tk), face_cur.get(tk), as_of, {},
            moex_accrued=accrued.get(tk) if kind == "bond" else None)
        dirty_now[tk] = v
    moex_ytm = {s: getattr(q, "ytm_pct", None) for s, q in quotes.items()}
    isin_of = {s: getattr(q, "isin", None) for s, q in quotes.items()}

    fund_proxy: tuple[float | None, float] = (None, 0.0)
    if any(pr.classify_instrument_type(by_ticker[t]) == "fund" for t in held):
        try:
            w = fetch_index_weights(FUND_PROXY_INDEX)
            q2 = fetch_bond_quotes(list(w))
            y, cov = fund_proxy_ytm(w, {s: getattr(q, "ytm_pct", None)
                                        for s, q in q2.items()})
            fund_proxy = (y if cov >= FUND_PROXY_MIN_COVERAGE else None, cov)
        except RuntimeError as e:
            flags.append({"code": "iis_fund_proxy_unavailable", "message": str(e)})

    out = compute(
        trades_all, as_of=as_of, schedules=schedules, dirty_now=dirty_now,
        moex_ytm=moex_ytm, isin_of=isin_of, infl=load_inflation(args.forecasts_dir),
        fund_proxy=fund_proxy, fact_report=report, synth_info=synth_info,
        flags=flags, source_file=Path(args.trades).name,
    )
    import bond_avg_price                                # сделки ИИС-3 → средняя цена покупки облигаций (assemble)
    out["bond_trades"] = bond_avg_price.compact_trades(trades)
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        f, fw, lk = out["fact"], out["forward"], out["locked"]
        print(f"✓ {args.output} | факт XIRR {_pct(f['xirr'])}% | "
              f"к погашению сейчас {fw['account_pct']}% | "
              f"зафиксировано {lk['bonds_irr_pct']}% | синтетических купонов "
              f"{len(out['synthetic_coupons'])} | флагов {len(out['flags'])}")
    else:
        print(text)


if __name__ == "__main__":
    main()
