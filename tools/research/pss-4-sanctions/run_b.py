#!/usr/bin/env python3
"""
Замер B — волна 12.09.2014, разложенная на «свежих» и «повторных».

Состав по первоисточникам OFAC (jl2629 + июльские):
  Directive 1 на 12.09.2014: Bank of Moscow, Gazprombank, РСХБ, СБЕРБАНК, ВЭБ, ВТБ
      → SBER новый; VTBR уже с 29.07, директива ужесточена (90 → 30 дней)
  Directive 2 добавлены: Gazprom Neft (SIBN), Transneft (TRNFP) — оба новые
      (Novatek и Rosneft там с 16.07)
  Directive 4 (новая): Gazprom, Gazprom Neft, Lukoil, Rosneft, Surgutneftegas
      → GAZP/LKOH/SNGS/SIBN новые; ROSN уже был под Dir 2 → эскалация

Гипотеза headroom: у «повторных» реакция слабее, чем у «свежих».

Оговорки, которые идут в вывод:
  • ЕС принял свой пакет тем же числом → US и EU не разделимы;
  • Минский протокол 05.09.2014 (деэскалация) попадает в окно [-7;+7] → основными
    считаем [0;+1] и [0;+5];
  • арест Евтушенкова 16.09.2014 → MTSS/AFKS исключены из контрольной корзины;
  • объявление OFAC ~23:00 МСК пятницы → реакция могла лечь на понедельник 15.09.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from event_study import (  # noqa: E402
    did_effect, event_index, fetch_returns, market_model_car, randomization,
)

FRM, TILL = "2013-06-01", "2015-06-30"
EVENT = "2014-09-12"
# Объявление OFAC ~23:00 МСК пятницы 12.09 — уже после закрытия MOEX; пакет ЕС
# вышел в тот же день днём. Поэтому считаются ОБА варианта дня 0: пятница (ловит
# реакцию на ЕС) и понедельник 15.09 (чистая реакция на объявление США).
EVENT_MONDAY = "2014-09-15"
# Даты, которые нельзя оставлять в окне оценки alpha/beta: это собственные
# санкционные шоки тех же бумаг. 16.07.2014 — Directive 1 (Газпромбанк, ВЭБ) и
# Directive 2 (Новатэк, Роснефть); 29.07.2014 — Directive 1 расширена на ВТБ.
# От чистоты этого окна прямо зависит интерпретация группы «повторных».
PRIOR_SHOCKS = ["2014-07-16", "2014-07-29"]
FRESH = ["SBER", "SIBN", "TRNFP", "GAZP", "LKOH", "SNGS"]
REPEAT = ["VTBR", "ROSN"]
PLACEBO = ["NVTK"]
CONTROL = ["MGNT", "GMKN", "CHMF", "NLMK", "MAGN", "ALRS", "IRAO", "HYDR", "RTKM"]
WINDOWS = [(0, 1), (0, 2), (0, 5), (-1, 5), (-7, 7)]
EST = (-140, -21)


def _exclusions(days: list[str], radius: int = 8) -> list[int]:
    """Индексы дней вокруг прежних санкционных шоков — вон из окна оценки."""
    out: list[int] = []
    for d in PRIOR_SHOCKS:
        try:
            i = event_index(days, d)
        except ValueError:
            continue
        out.extend(range(i - radius, i + radius + 1))
    return out


def main() -> int:
    names = FRESH + REPEAT + PLACEBO + CONTROL
    print("Загрузка MOEX ISS…", file=sys.stderr)
    ret = {t: fetch_returns(t, FRM, TILL) for t in names}
    mkt = fetch_returns("IMOEX", FRM, TILL, kind="index")
    for t in names:
        if len(ret[t]) < 200:
            print(f"  ⚠ {t}: только {len(ret[t])} дней", file=sys.stderr)

    print("\n" + "=" * 78)
    print("ЗАМЕР B — 12.09.2014: свежие vs повторные (market model против IMOEX)")
    print("=" * 78)

    per_name: dict[str, dict[tuple[int, int], float]] = {}
    for grp_name, grp in (("СВЕЖИЕ", FRESH), ("ПОВТОРНЫЕ", REPEAT), ("ПЛАЦЕБО", PLACEBO)):
        print(f"\n### {grp_name}")
        for t in grp:
            days = sorted(set(ret[t]) & set(mkt))
            e = event_index(days, EVENT)
            excl = _exclusions(days)
            row, per_name[t] = [], {}
            beta = float("nan")
            for w in WINDOWS:
                r = market_model_car(ret[t], mkt, days, e, w, EST,
                                     exclude=excl)
                if "error" in r:
                    row.append("—"); continue
                per_name[t][w] = r["car"]; beta = r["beta"]
                row.append(f"[{w[0]:+d};{w[1]:+d}] {r['car']:+6.2f} (t{r['t']:+5.2f})")
            print(f"  {t:6s} β={beta:4.2f}  " + "  ".join(row))

    # Вариант дня 0 = понедельник 15.09: объявление США пришло после закрытия
    # пятницы, поэтому «чистая» реакция на него должна лежать в понедельник.
    print("\n### CAAR по группам, день 0 = ПОНЕДЕЛЬНИК 15.09 (реакция на США)")
    hdr = f"  {'окно':10s} {'свежие':>12s} {'повторные':>12s} {'разница':>10s}"
    print(hdr)
    for w in WINDOWS:
        vals = {}
        for key, grp in (("f", FRESH), ("r", REPEAT)):
            acc = []
            for t in grp:
                d_t = sorted(set(ret[t]) & set(mkt))
                em = event_index(d_t, EVENT_MONDAY)
                rr = market_model_car(ret[t], mkt, d_t, em, w, EST,
                                      exclude=_exclusions(d_t))
                if "error" not in rr:
                    acc.append(rr["car"])
            vals[key] = statistics.mean(acc) if acc else float("nan")
        tag = f"  [{w[0]:+d};{w[1]:+d}]".ljust(12)
        print(f"{tag}{vals['f']:+11.2f}% {vals['r']:+12.2f}% "
              f"{vals['f'] - vals['r']:+9.2f}%")

    print("\n### CAAR по группам, день 0 = пятница 12.09 (ловит и пакет ЕС)")
    print(f"  {'окно':10s} {'свежие (n=6)':>16s} {'повторные (n=2)':>18s} {'разница':>10s} {'плацебо':>10s}")
    for w in WINDOWS:
        f = [per_name[t][w] for t in FRESH if w in per_name[t]]
        r_ = [per_name[t][w] for t in REPEAT if w in per_name[t]]
        p = [per_name[t][w] for t in PLACEBO if w in per_name[t]]
        mf, mr = statistics.mean(f), statistics.mean(r_)
        sef = statistics.stdev(f) / len(f) ** 0.5
        tag = f"  [{w[0]:+d};{w[1]:+d}]".ljust(12)
        print(f"{tag}{mf:+8.2f}% (SE{sef:4.2f}) {mr:+11.2f}% "
              f"{mf - mr:+9.2f}% {statistics.mean(p):+9.2f}%")

    # ── DiD: каждая группа против нейтральной корзины ──
    print("\n" + "=" * 78)
    print("ЗАМЕР B — DiD против нейтральной корзины (MGNT/GMKN/CHMF/NLMK/MAGN/ALRS/IRAO/HYDR/RTKM)")
    print("=" * 78)
    common = set(mkt)
    for t in names:
        common &= set(ret[t])
    days = sorted(common)
    e = event_index(days, EVENT)
    excl_c = _exclusions(days)
    print(f"общий календарь: {len(days)} дн; день события: {days[e]}")
    con = {t: ret[t] for t in CONTROL}
    groups = {"свежие": {t: ret[t] for t in FRESH},
              "повторные": {t: ret[t] for t in REPEAT},
              "плацебо NVTK": {t: ret[t] for t in PLACEBO}}
    for gname, g in groups.items():
        print(f"\n### {gname}")
        for w in WINDOWS:
            r = did_effect(g, con, days, e, w, EST, exclude=excl_c)
            if "error" in r:
                print(f"  [{w[0]:+d};{w[1]:+d}] {r['error']}"); continue
            print(f"  [{w[0]:+d};{w[1]:+d}]  θ_окно {r['theta_window']:+7.2f}%  (t={r['t']:+5.2f})")

        def stat(i: int, gg=g) -> float | None:
            rr = did_effect(gg, con, days, i, (0, 5), EST, exclude=excl_c)
            return None if "error" in rr else rr["theta_window"]

        rnd = randomization(stat, days, e, span=(-200, 200), guard=12)
        if "error" not in rnd:
            print(f"  рандомизация [0;+5]: {rnd['real']:+.2f}%, p={rnd['p_two_sided']:.3f}, "
                  f"перцентиль {rnd['percentile']:.1f}, "
                  f"[p5;p95]=[{rnd['pseudo_p05']:+.2f};{rnd['pseudo_p95']:+.2f}] (n={rnd['n_pseudo']})")

    # ── Прямой тест headroom: свежие против повторных ──
    print("\n" + "=" * 78)
    print("ПРЯМОЙ ТЕСТ HEADROOM: свежие (treated) против повторных (control)")
    print("=" * 78)
    for w in WINDOWS:
        r = did_effect(groups["свежие"], groups["повторные"], days, e, w,
                       EST, exclude=excl_c)
        if "error" in r:
            print(f"  [{w[0]:+d};{w[1]:+d}] {r['error']}"); continue
        print(f"  [{w[0]:+d};{w[1]:+d}]  θ {r['theta_window']:+7.2f}%  (t={r['t']:+5.2f})")

    def stat_h(i: int) -> float | None:
        rr = did_effect(groups["свежие"], groups["повторные"], days, i,
                        (0, 5), EST, exclude=excl_c)
        return None if "error" in rr else rr["theta_window"]

    rnd = randomization(stat_h, days, e, span=(-200, 200), guard=12)
    if "error" not in rnd:
        print(f"  рандомизация [0;+5]: {rnd['real']:+.2f}%, p={rnd['p_two_sided']:.3f}, "
              f"перцентиль {rnd['percentile']:.1f}, псевдо-СКО {rnd['pseudo_sd']:.2f}, "
              f"[p5;p95]=[{rnd['pseudo_p05']:+.2f};{rnd['pseudo_p95']:+.2f}] (n={rnd['n_pseudo']})")

    # ── подённая раскладка: где именно лёг эффект (пятница vs понедельник) ──
    print("\n### Подённые AR вокруг события (market model)")
    hdr_days = None
    for t in FRESH + REPEAT + PLACEBO:
        d_t = sorted(set(ret[t]) & set(mkt))
        et = event_index(d_t, EVENT)
        r = market_model_car(ret[t], mkt, d_t, et, (-2, 5), EST,
                             exclude=_exclusions(d_t))
        if "error" in r:
            continue
        if hdr_days is None:
            hdr_days = [d_t[i] for i in range(et - 2, et + 6)]
            print("         " + " ".join(f"{d[5:]:>7s}" for d in hdr_days))
        print(f"  {t:6s} " + " ".join(f"{a:+7.2f}" for a in r["ar_daily"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
