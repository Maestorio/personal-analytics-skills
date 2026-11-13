#!/usr/bin/env python3
"""
Замер A — Rusal/En+: SDN 06.04.2018 → анонс снятия 19.12.2018 → делистинг 27.01.2019.

Логика:
  1. Валидация оценщика на 06.04.2018 против Dovbnya (2020): CAAR ≈ −20% к дню +5.
  2. Тем же оценщиком — окна снятия.
  3. Round trip: накопленная сверхдоходность от назначения до делистинга — сколько
     процентов нанесённого ущерба вернул релиф. Это и есть прямая оценка того,
     что в модели названо «сколько ущерба реализовано и не отыграно».
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from event_study import (  # noqa: E402
    caar, did_effect, event_index, fetch_returns, market_model_car, randomization,
)

FRM, TILL = "2016-06-01", "2019-07-31"
TREATED = ["RUAL", "ENPL"]
CONTROL = ["GMKN", "CHMF", "NLMK", "MAGN", "PLZL", "ALRS"]
EVENTS = {
    "SDN 06.04.2018": "2018-04-06",
    "анонс снятия 19.12.2018": "2018-12-19",
    "делистинг 27.01.2019": "2019-01-27",
}
WINDOWS = [(0, 1), (-1, 1), (0, 5), (0, 7), (-7, 7)]
EST = (-140, -21)

# Валидация оценщика. Dovbnya (2020) публикует CAAR ≈ −20% по ШЕСТИ листингованным
# целям волны 06.04.2018; наши TREATED — только два имени эпицентра, поэтому прямое
# сравнение некорректно. Помимо Rusal/En+ под санкции попали ГАЗ (GAZA) и Мостотрест
# (MSTT), а через назначенных руководителей волна задела SNGS и GAZP. Точный состав
# шести целей у автора не опубликован → считаем вилку по правдоподобным наборам.
VALIDATION_SETS = [
    ["RUAL", "ENPL"],
    ["RUAL", "ENPL", "GAZA", "MSTT"],
    ["RUAL", "ENPL", "GAZA", "MSTT", "SNGS", "GAZP"],
]
VALIDATION_EXTRA = ["GAZA", "MSTT", "SNGS", "GAZP"]

# Полная лестница решений OFAC по Rusal/En+ (пресс-релизы OFAC, обзоры Baker
# McKenzie и Davis Polk). Используется и как замер, и как blackout рандомизации:
# иначе реальные даты решений остаются в пуле псевдо-дат нулевого распределения.
LADDER = [
    ("06.04.2018 назначение SDN", "2018-04-06"),
    ("23.04.2018 генлицензии + условия снятия", "2018-04-23"),
    ("23.10.2018 продление лицензий", "2018-10-23"),
    ("12.11.2018 продление лицензий", "2018-11-12"),
    ("12.12.2018 продление лицензий", "2018-12-12"),
    ("19.12.2018 анонс делистинга", "2018-12-19"),
    ("27.01.2019 фактический делистинг", "2019-01-27"),
]
LADDER_DATES = [d for _, d in LADDER]
# Радиус исключения вокруг реального события при построении окна оценки.
# Один на весь файл: разные радиусы в соседних блоках — источник расхождений.
EXCL_RADIUS = 10


def main() -> int:
    print("Загрузка MOEX ISS…", file=sys.stderr)
    ret = {t: fetch_returns(t, FRM, TILL)
           for t in TREATED + CONTROL + VALIDATION_EXTRA}
    ret["IMOEX"] = fetch_returns("IMOEX", FRM, TILL, kind="index")
    for t in TREATED + CONTROL + ["IMOEX"]:
        ds = sorted(ret[t])
        print(f"  {t:6s} {len(ds):5d} дн  {ds[0]} … {ds[-1]}", file=sys.stderr)

    mkt = ret["IMOEX"]
    # blackout: даты всех трёх событий в календаре каждой бумаги
    print("\n" + "=" * 78)
    print("ЗАМЕР A — Rusal / En+ (market model против IMOEX)")
    print("=" * 78)

    car_store: dict[tuple[str, str, tuple[int, int]], float] = {}
    for ename, edate in EVENTS.items():
        print(f"\n### {ename}")
        for w in WINDOWS:
            cars, line = [], []
            for t in TREATED:
                days = sorted(set(ret[t]) & set(mkt))
                try:
                    e = event_index(days, edate)
                except ValueError:
                    line.append(f"{t}: нет данных"); continue
                bl = []
                for d2 in LADDER_DATES:
                    try:
                        bl.append(event_index(days, d2))
                    except ValueError:
                        pass
                excl = [i for b in bl
                        for i in range(b - EXCL_RADIUS, b + EXCL_RADIUS + 1)]
                r = market_model_car(ret[t], mkt, days, e, w, EST, exclude=excl)
                if "error" in r:
                    line.append(f"{t}: {r['error']}"); continue
                cars.append(r["car"]); car_store[(ename, t, w)] = r["car"]
                line.append(f"{t}: {r['car']:+7.2f}% (t={r['t']:+5.2f}, β={r['beta']:.2f}, "
                            f"n_est={r['n_est']})")
            tag = f"[{w[0]:+d};{w[1]:+d}]"
            if cars:
                m, se = caar(cars)
                print(f"  {tag:10s} CAAR {m:+7.2f}%   " + " | ".join(line))
            else:
                print(f"  {tag:10s} — " + " | ".join(line))

    # ── Валидация оценщика против опубликованного Dovbnya (2020) ──
    print("\n" + "=" * 78)
    print("ВАЛИДАЦИЯ: CAAR волны 06.04.2018 при разном составе портфеля")
    print("опубликовано у Dovbnya (2020): ≈ −20% по 6 листингованным целям")
    print("=" * 78)
    per_ticker: dict[str, float] = {}
    for t in TREATED + VALIDATION_EXTRA:
        d_t = sorted(set(ret[t]) & set(mkt))
        try:
            ei = event_index(d_t, "2018-04-06")
        except ValueError:
            continue
        rr = market_model_car(ret[t], mkt, d_t, ei, (0, 5), EST)
        if "error" not in rr:
            per_ticker[t] = rr["car"]
            print(f"  {t:6s} CAR[0;+5] {rr['car']:+7.2f}%  (t={rr['t']:+5.2f}, "
                  f"β={rr['beta']:+.2f})")
    print()
    for vs in VALIDATION_SETS:
        vals = [per_ticker[t] for t in vs if t in per_ticker]
        if len(vals) == len(vs):
            print(f"  {'+'.join(vs):40s} CAAR {float(np.mean(vals)):+7.2f}%  (n={len(vs)})")

    # ── DiD против корзины сектора ──
    print("\n" + "=" * 78)
    print("ЗАМЕР A — DiD против корзины (GMKN/CHMF/NLMK/MAGN/PLZL/ALRS)")
    print("=" * 78)
    common = set(mkt)
    for t in TREATED + CONTROL:
        common &= set(ret[t])
    days = sorted(common)
    print(f"общий календарь: {len(days)} дн, {days[0]} … {days[-1]}")
    tre = {t: ret[t] for t in TREATED}
    con = {t: ret[t] for t in CONTROL}
    for ename, edate in EVENTS.items():
        e = event_index(days, edate)
        bl = [event_index(days, d) for d in LADDER_DATES]
        excl = [i for b in bl
                for i in range(b - EXCL_RADIUS, b + EXCL_RADIUS + 1)]
        print(f"\n### {ename}  (день события в календаре: {days[e]})")
        for w in WINDOWS:
            r = did_effect(tre, con, days, e, w, EST, exclude=excl)
            if "error" in r:
                print(f"  [{w[0]:+d};{w[1]:+d}] {r['error']}"); continue
            print(f"  [{w[0]:+d};{w[1]:+d}]  θ_окно {r['theta_window']:+7.2f}%  "
                  f"(θ/день {r['theta_daily']:+5.2f}, t={r['t']:+5.2f}, n={r['n_win']})")

        # рандомизационный тест на окне (0;+5)
        def stat(i: int, w=(0, 5)) -> float | None:
            rr = did_effect(tre, con, days, i, w, EST, exclude=excl)
            return None if "error" in rr else rr["theta_window"]

        bl_all = []
        for d2 in LADDER_DATES:
            try:
                bl_all.append(event_index(days, d2))
            except ValueError:
                pass
        rnd = randomization(stat, days, e, span=(-220, 220), guard=12, blackout=bl_all)
        if "error" in rnd:
            print(f"  рандомизация: {rnd['error']}")
        else:
            print(f"  рандомизация [0;+5]: реальное {rnd['real']:+.2f}%, "
                  f"p(двуст.)={rnd['p_two_sided']:.3f}, перцентиль {rnd['percentile']:.1f}, "
                  f"псевдо-СКО {rnd['pseudo_sd']:.2f}, "
                  f"[p5;p95]=[{rnd['pseudo_p05']:+.2f};{rnd['pseudo_p95']:+.2f}] "
                  f"(n={rnd['n_pseudo']})")

    # ── Round trip: от назначения до делистинга ──
    print("\n" + "=" * 78)
    print("ROUND TRIP — накопленная сверхдоходность от SDN до делистинга")
    print("=" * 78)
    e0 = event_index(days, "2018-04-06")
    e2 = event_index(days, "2019-01-27")
    est_pre = (-140, -21)
    for t in TREATED:
        d_t = sorted(set(ret[t]) & set(mkt))
        i0 = event_index(d_t, "2018-04-06")
        i2 = event_index(d_t, "2019-01-27")
        w = (0, i2 - i0 + 5)
        r = market_model_car(ret[t], mkt, d_t, i0, w, est_pre)
        if "error" in r:
            print(f"  {t}: {r['error']}"); continue
        print(f"  {t}: CAR[SDN → делистинг+5] = {r['car']:+7.2f}%  "
              f"({r['n_win']} торг. дней, β={r['beta']:.2f} оценена ДО апреля-2018)")
    n_days = e2 - e0 + 5
    r = did_effect(tre, con, days, e0, (0, n_days), est_pre)
    if "error" not in r:
        print(f"  DiD корзина: θ_окно {r['theta_window']:+7.2f}% за {r['n_win']} дн "
              f"(θ/день {r['theta_daily']:+.3f})")

    # ── Лестница предвосхищённости: все решения OFAC по Rusal/En+ 2018–2019 ──
    # Даты по пресс-релизам OFAC / обзорам Baker McKenzie и Davis Polk.
    print("\n" + "=" * 78)
    print("ЛЕСТНИЦА РЕШЕНИЙ OFAC — где именно лёг релиф (окно [0;+1])")
    print("=" * 78)
    ladder, all_dates = LADDER, LADDER_DATES
    print(f"{'событие':44s} {'RUAL':>9s} {'ENPL':>9s} {'CAAR':>9s}")
    totals: dict[str, float] = {}
    for label, dt in ladder:
        cars: list[float | None] = []
        for t in TREATED:
            d_t = sorted(set(ret[t]) & set(mkt))
            ei = event_index(d_t, dt)
            bl = [event_index(d_t, x) for x in all_dates if x >= d_t[0]]
            excl = [i for b in bl
                    for i in range(b - EXCL_RADIUS, b + EXCL_RADIUS + 1)]
            rr = market_model_car(ret[t], mkt, d_t, ei, (0, 1), EST, exclude=excl)
            cars.append(None if "error" in rr else rr["car"])
        ok = [c for c in cars if c is not None]
        m = float(np.mean(ok)) if ok else float("nan")
        totals[label] = m
        fmt = lambda c: f"{c:+9.2f}" if c is not None else "        —"  # noqa: E731
        print(f"{label:44s} {fmt(cars[0])} {fmt(cars[1])} {m:+9.2f}")
    neg = totals["06.04.2018 назначение SDN"]
    pos = sum(v for k, v in totals.items() if k != "06.04.2018 назначение SDN")
    print(f"\nсумма релиф-событий {pos:+.2f}%  против назначения {neg:+.2f}%  "
          f"→ отыграно {abs(pos / neg) * 100:.0f}% нанесённого ущерба "
          f"(оба члена — окно [0;+1], один оценщик)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
