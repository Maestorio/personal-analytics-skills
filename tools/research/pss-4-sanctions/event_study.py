#!/usr/bin/env python3
"""
event_study.py — мини event-study по данным MOEX ISS для калибровки PSS-4.

Два замера:
  A) Rusal/En+: SDN 06.04.2018 → анонс снятия 19.12.2018 → делистинг 27.01.2019.
     Валидация оценщика на апреле-2018 против опубликованных Dovbnya (2020) ≈ −20%.
  B) Волна 12.09.2014, разложенная на «свежие» и «повторные» имена.

Два оценщика:
  1. Market model CAR против IMOEX (как Dovbnya).
  2. DiD против контрольной корзины сектора (как Draca): raw returns, firm FE.

Инференция при крошечном n — рандомизационный тест: та же статистика на всех
псевдо-датах окружающего периода, эмпирический перцентиль. Параметрический t
приводится справочно.

stdlib + numpy. Сеть: iss.moex.com.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date

import numpy as np

ISS = "https://iss.moex.com/iss"
UA = {"User-Agent": "pss-4-event-study/1.0 (+claude.ai)"}
TIMEOUT = 30


# ────────────────────────────── загрузка ──────────────────────────────

def _get(url: str, tries: int = 3) -> dict:
    last = None
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=TIMEOUT))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"ISS недоступен: {url} ({last})")


# Приоритет режимов торгов. До листинговой реформы середины 2014 голубые фишки
# торговались на T+2-бордах уровней TQNE/TQNL, а не на TQBR: без них история GAZP /
# ROSN / SNGS / SIBN обрывается на 2014-06-10 и окно оценки для сентября-2014 не
# набирается. EQBR (T+0) — ещё более ранний запасной режим.
BOARD_PRIORITY = ("TQBR", "TQBS", "TQNE", "TQNL", "EQBR")


def fetch_series(secid: str, frm: str, till: str, kind: str = "share") -> dict[str, float]:
    """{YYYY-MM-DD: close} по основному режиму торгов. kind: share | index."""
    market = "shares" if kind == "share" else "index"
    # у индексов нет BOARDID/LEGALCLOSEPRICE — запрашиваем разный набор колонок
    cols = "BOARDID,TRADEDATE,CLOSE,LEGALCLOSEPRICE" if kind == "share" else "TRADEDATE,CLOSE"
    by_board: dict[str, dict[str, float]] = {b: {} for b in BOARD_PRIORITY}
    out: dict[str, float] = {}
    start = 0
    while True:
        url = (f"{ISS}/history/engines/stock/markets/{market}/securities/{secid}.json"
               f"?from={frm}&till={till}&start={start}"
               f"&iss.only=history&history.columns={cols}")
        block = _get(url)["history"]
        idx = {c: i for i, c in enumerate(block["columns"])}
        rows = block["data"]
        if not rows:
            break
        for r in rows:
            if kind == "share":
                board = r[idx["BOARDID"]]
                if board not in by_board:
                    continue
                px = r[idx["LEGALCLOSEPRICE"]] or r[idx["CLOSE"]]
                if px:
                    by_board[board][r[idx["TRADEDATE"]]] = float(px)
            else:
                px = r[idx["CLOSE"]]
                if px:
                    out[r[idx["TRADEDATE"]]] = float(px)
        start += len(rows)
    if kind == "share":
        # склейка режимов: TQBR приоритетнее, EQBR закрывает дыры до переезда на T+2
        for board in reversed(BOARD_PRIORITY):
            out.update(by_board[board])
        fetch_series.last_boards = {b: len(v) for b, v in by_board.items()}  # type: ignore[attr-defined]
        fetch_series.last_by_board = by_board                                # type: ignore[attr-defined]
    return out


def fetch_returns(secid: str, frm: str, till: str, kind: str = "share") -> dict[str, float]:
    """
    Дневные доходности, %. Для акций доходность считается ВНУТРИ каждого режима
    торгов и только потом склеивается (TQBR приоритетнее): цена T+0 и цена T+2
    различаются на базис, и межрежимная «доходность» на стыке была бы артефактом.
    """
    prices = fetch_series(secid, frm, till, kind=kind)
    if kind != "share":
        return returns(prices)
    by_board = getattr(fetch_series, "last_by_board", {"TQBR": prices})
    merged: dict[str, float] = {}
    for board in reversed(BOARD_PRIORITY):
        merged.update(returns(by_board.get(board, {})))
    return merged


def returns(series: dict[str, float]) -> dict[str, float]:
    ds = sorted(series)
    return {ds[i]: (series[ds[i]] / series[ds[i - 1]] - 1.0) * 100.0
            for i in range(1, len(ds)) if series[ds[i - 1]]}


# ────────────────────────────── механика окон ──────────────────────────────

def trading_days(*rets: dict[str, float]) -> list[str]:
    """Пересечение торговых дней всех рядов, отсортировано."""
    common = set(rets[0])
    for r in rets[1:]:
        common &= set(r)
    return sorted(common)


def event_index(days: list[str], event: str) -> int:
    """Индекс первого торгового дня >= даты события (событие в выходной/после закрытия)."""
    for i, d in enumerate(days):
        if d >= event:
            return i
    raise ValueError(f"событие {event} вне выборки")


# ────────────────────────────── оценщик 1: market model ──────────────────────────────

def market_model_car(
    stock: dict[str, float], mkt: dict[str, float], days: list[str],
    e: int, window: tuple[int, int], est: tuple[int, int],
    exclude: list[int] | None = None,
) -> dict:
    """
    CAR по market model. est=(-160,-21) — окно оценки в торговых днях от события.
    exclude — индексы дней (абсолютные), исключаемые из окна оценки (другие события).
    """
    ex = set(exclude or [])
    est_idx = [i for i in range(e + est[0], e + est[1] + 1)
               if 0 <= i < len(days) and i not in ex]
    if len(est_idx) < 60:
        return {"error": f"окно оценки {len(est_idx)} дней (<60)"}
    y = np.array([stock[days[i]] for i in est_idx])
    x = np.array([mkt[days[i]] for i in est_idx])
    X = np.column_stack([np.ones_like(x), x])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    alpha, beta = float(coef[0]), float(coef[1])
    resid = y - X @ coef
    sigma = float(np.sqrt(resid @ resid / (len(y) - 2)))

    w_idx = [i for i in range(e + window[0], e + window[1] + 1) if 0 <= i < len(days)]
    ar = [stock[days[i]] - (alpha + beta * mkt[days[i]]) for i in w_idx]
    car = float(np.sum(ar))
    # стандартная поправка на ошибку прогноза вне окна оценки
    n_w = len(w_idx)
    xbar, sxx = float(np.mean(x)), float(np.sum((x - np.mean(x)) ** 2))
    xw = np.array([mkt[days[i]] for i in w_idx])
    # Campbell-Lo-MacKinlay §4.4.3: Var(CAR) = σ²·[L2 + L2²/L1 + (Σ(x_w−x̄))²/Sxx].
    # Третий член — квадрат СУММЫ отклонений: ошибка оценки β входит в CAR через
    # сумму рыночных доходностей окна, а не поднево́ по каждому дню отдельно.
    dev_sum = float(np.sum(xw - xbar))
    var = sigma ** 2 * (n_w + n_w ** 2 / len(y) + dev_sum ** 2 / sxx)
    se = float(np.sqrt(var))
    return {"car": car, "t": car / se if se else float("nan"), "se": se,
            "alpha": alpha, "beta": beta, "sigma": sigma,
            "n_est": len(est_idx), "n_win": n_w,
            "ar_daily": [round(a, 3) for a in ar]}


def caar(cars: list[float]) -> tuple[float, float]:
    """Средний CAR по портфелю и кросс-секционная SE (n мал → справочно)."""
    a = np.array(cars, dtype=float)
    return float(a.mean()), float(a.std(ddof=1) / np.sqrt(len(a))) if len(a) > 1 else float("nan")


# ────────────────────────────── оценщик 2: DiD против корзины ──────────────────────────────

def did_effect(
    treated: dict[str, dict[str, float]], control: dict[str, dict[str, float]],
    days: list[str], e: int, window: tuple[int, int], est: tuple[int, int],
    exclude: list[int] | None = None,
) -> dict:
    """
    θ = (средняя доходность treated в окне − её норма) − (то же для control).
    Норма — среднедневная доходность в окне оценки по каждой группе.
    """
    ex = set(exclude or [])
    est_idx = [i for i in range(e + est[0], e + est[1] + 1)
               if 0 <= i < len(days) and i not in ex]
    w_idx = [i for i in range(e + window[0], e + window[1] + 1) if 0 <= i < len(days)]
    if len(est_idx) < 60 or not w_idx:
        return {"error": "недостаточно данных"}

    def grp(g: dict[str, dict[str, float]], idx: list[int]) -> np.ndarray:
        return np.array([np.mean([g[t][days[i]] for t in g]) for i in idx])

    t_est, c_est = grp(treated, est_idx), grp(control, est_idx)
    t_win, c_win = grp(treated, w_idx), grp(control, w_idx)
    theta_daily = (t_win.mean() - t_est.mean()) - (c_win.mean() - c_est.mean())
    # SE по дисперсии дифференциала в окне оценки
    diff_est = t_est - c_est
    se_daily = float(diff_est.std(ddof=1) / np.sqrt(len(w_idx)))
    n = len(w_idx)
    return {"theta_daily": float(theta_daily), "theta_window": float(theta_daily * n),
            "se_daily": se_daily, "t": float(theta_daily / se_daily) if se_daily else float("nan"),
            "n_win": n, "n_est": len(est_idx)}


# ────────────────────────────── рандомизационный тест ──────────────────────────────

def randomization(
    stat_fn, days: list[str], e_real: int, span: tuple[int, int] = (-250, 250),
    guard: int = 12, blackout: list[int] | None = None,
) -> dict:
    """
    Эмпирическое распределение статистики на псевдо-датах вокруг события.
    guard — не брать псевдо-даты ближе guard дней к реальным событиям (blackout).
    """
    bl = list(blackout or [e_real])
    real = stat_fn(e_real)
    if real is None:
        return {"error": "статистика не считается на реальном событии"}
    pseudo = []
    for i in range(e_real + span[0], e_real + span[1] + 1):
        if any(abs(i - b) <= guard for b in bl):
            continue
        if not (0 <= i < len(days)):
            continue
        v = stat_fn(i)
        if v is not None and np.isfinite(v):
            pseudo.append(v)
    if len(pseudo) < 50:
        return {"error": f"мало псевдо-дат ({len(pseudo)})"}
    p = np.array(pseudo)
    # двусторонний эмпирический p: доля |псевдо| >= |реального|
    # Минимально различимое p = 1/n_pseudo: «p = 0.000» при n=167 означает лишь
    # «< 0.006». Возвращаем и разрешение, чтобы не цитировать несуществующую точность.
    p_two = float(np.mean(np.abs(p) >= abs(real)))
    pct = float(np.mean(p <= real) * 100)
    return {"real": float(real), "n_pseudo": len(p), "p_two_sided": p_two,
            "p_resolution": 1.0 / len(p),
            "percentile": pct, "pseudo_sd": float(p.std(ddof=1)),
            "pseudo_p05": float(np.percentile(p, 5)), "pseudo_p95": float(np.percentile(p, 95))}
