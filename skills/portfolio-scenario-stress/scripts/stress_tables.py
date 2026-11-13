#!/usr/bin/env python3
"""
stress_tables.py — готовые markdown-таблицы отчёта из дерева результата stress_build.

Ни одного нового расчёта: все числа берутся из дерева как есть. Единственное исключение —
рублёвая дельта бумаги (в дереве её нет, есть доля и Δ%): она считается функцией
compute_derived_fields._position_rub от стоимости бумаги в снапшоте — тем же способом, что
top_risks / sector_breakdown_pct, поэтому совпадает с ними до рубля.

Формат: рубли — целые с пробелом тысяч и знаком («−512 792»), проценты — два знака со знаком
и запятой («−3,37%»), доли — два знака. Текста-рассуждений нет.
"""
from __future__ import annotations

from typing import Any

import compute_derived_fields as cdf

MINUS = "−"
MARK = "ЗАПОЛНИТЬ_В_FILL"
BASES = (("price", "price_delta", "Ценовой слой (price)"),
         ("total_return", "total_return", "Полная доходность (total_return)"))


def _comma(s: str) -> str:
    return s.replace(".", ",").replace("-", MINUS)


def f_rub(x: Any) -> str:
    """Целые рубли, пробел тысяч, знак всегда («−512 792», «+5 102 211», «0»)."""
    if x is None:
        return "—"
    n = round(x)
    if n == 0:
        return "0"
    return ("+" if n > 0 else MINUS) + f"{abs(n):,}".replace(",", " ")


def f_pct(x: Any) -> str:
    """Процент: два знака, знак, запятая («−3,37%»)."""
    return "—" if x is None else _comma(f"{x:+.2f}") + "%"


def f_share(x: Any) -> str:
    """Доля: два знака, без знака («60,00%»)."""
    return "—" if x is None else _comma(f"{x:.2f}") + "%"


def f_num(x: Any, nd: int = 4) -> str:
    return "—" if x is None else _comma(f"{x:.{nd}f}")


def _table(head: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return out


def _pv(cell: Any) -> Any:
    return cell.get("value") if isinstance(cell, dict) else cell


def _names(snapshot: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in snapshot.get("holdings") or []:
        t = h.get("ticker")
        if t and t not in out and h.get("name"):
            out[t] = str(h["name"])
    return out


def position_rows(tree: dict, snapshot: dict) -> list[dict]:
    """Бумаги основного срока: {ticker, name, weight, cells{sid: (delta_pct, delta_rub)}}.
    Δ₽ = cdf._position_rub (стоимость бумаги из снапшота × Δ%), округление до рубля — как в top_risks."""
    ph = f"h{tree['primary_horizon']}"
    sids = list(tree["scenarios"])
    legs, _ = cdf._legs(snapshot)
    names = _names(snapshot)
    rows = []
    for t, p in tree["per_position"].items():
        cells = {}
        for sid in sids:
            d = _pv((((p.get("by_horizon") or {}).get(ph) or {}).get("delta_pct_by_scenario") or {}).get(sid))
            leg = legs.get(t)
            rub = cdf._position_rub(tree["per_position"], t, ph, sid, leg["value"]) if leg is not None else None
            cells[sid] = (d, None if rub is None else round(rub))
        rows.append({"ticker": t, "name": names.get(t, ""), "weight": p.get("weight_pct"), "cells": cells})
    rows.sort(key=lambda r: (-(r["weight"] if r["weight"] is not None else -1.0), r["ticker"]))
    return rows


def build_tables(tree: dict, snapshot: dict, info: dict) -> str:
    ph = f"h{tree['primary_horizon']}"
    sids = list(tree["scenarios"])
    hks = list(tree["horizon_ends"])
    sname = {s: tree["scenarios"][s]["name"] for s in sids}
    numbers_only = bool(tree.get("numbers_only"))
    pa = tree.get("portfolio_aggregates") or {}
    L: list[str] = []

    def sec(title: str) -> None:
        L.extend(["", f"## {title}", ""])

    L.append(f"<!-- таблицы stress_build: снапшот {tree['portfolio_snapshot_id']}, основной срок {ph}"
             f"{', режим только числа' if numbers_only else ''} -->")

    # 1. Итоги портфеля по срокам
    sec("Итоги портфеля по срокам (₽ и %, обе базы)")
    for basis, key, label in BASES:
        L += [f"**{label}**", ""]
        rows = []
        for sid in sids:
            pl = tree["scenarios"][sid]["portfolio_level_by_horizon"]
            rows.append([f"{sid} {sname[sid]}"] + [f"{f_rub(pl[hk][key + '_rub'])} ({f_pct(pl[hk][key + '_pct'])})"
                                                   for hk in hks])
        agg = pa.get(basis) or {}
        er, ep = agg.get("expected_pl_rub_by_horizon") or {}, agg.get("expected_pl_pct_by_horizon") or {}
        if any(er.get(hk) is not None for hk in hks):
            rows.append(["**Ожидание (по весам)**"] + [f"{f_rub(er.get(hk))} ({f_pct(ep.get(hk))})" for hk in hks])
        L += _table(["Сценарий"] + hks, rows) + [""]
    w = info["weights"]
    wline = f"Веса: {w['source']}" + (f" (set_at {w['set_at']})" if w.get("set_at") else "") + f"; тип {info['weight_type']}; p по срокам: "
    wline += "; ".join(f"{s}: " + "/".join(str(tree['scenarios'][s]['p_by_horizon'].get(hk)) for hk in hks) for s in sids)
    L.append(wline + f" ({'/'.join(hks)}).")

    # 2. Позиция × сценарий
    sec(f"Позиция × сценарий, ΔP&L ({ph}, ценовой слой)")
    prow = position_rows(tree, snapshot)
    head = ["Тикер", "Название", "Доля"]
    for s in sids:
        head += [f"{s} Δ%", f"{s} Δ₽"]
    body = []
    tot = {s: 0 for s in sids}
    tw = 0.0
    for r in prow:
        row = [r["ticker"], r["name"], f_share(r["weight"])]
        for s in sids:
            d, rub = r["cells"][s]
            row += [f_pct(d), f_rub(rub)]
            tot[s] += rub or 0
        tw += r["weight"] or 0
        body.append(row)
    body.append(["**Итого**", f"бумаг: {len(prow)}", f_share(tw)] + sum(([ "—", f_rub(tot[s])] for s in sids), []))
    L += _table(head, body)

    # 3. Секторы
    sec(f"Секторальная сводка ({ph}, ценовая база)")
    sb = tree.get("sector_breakdown_pct")
    if not isinstance(sb, dict) or not sb:
        L.append("Секторальная сводка в дереве не посчитана.")
    else:
        body = []
        for _, v in sorted(sb.items(), key=lambda kv: -(kv[1].get("weight_pct") or 0)):
            cell = (v.get("price_delta_rub_by_horizon") or {}).get(ph) or {}
            body.append([v.get("label_ru", ""), f_share(v.get("weight_pct"))] + [f_rub(cell.get(s)) for s in sids])
        L += _table(["Сектор", "Доля"] + [f"{s} Δ₽" for s in sids], body)

    # 4. Top-5
    labels = {k: v.get("label_ru", k) for k, v in (sb or {}).items()} if isinstance(sb, dict) else {}
    for key, title in (("top_risks", "Top-5 уязвимых"), ("top_resilient", "Top-5 выигрывающих")):
        rows = [x for x in (tree.get(key) or []) if x.get("horizon") == ph]
        scen = rows[0]["scenario"] if rows else None
        sec(f"{title} ({ph}" + (f", сценарий {scen}" if scen else "") + ")")
        if not rows:
            L.append("Строк нет: в дереве для основного срока список пуст.")
            continue
        L += _table(["#", "Тикер", "Сектор", "Доля", "Δ%", "Δ₽"],
                    [[str(i), x["ticker"], labels.get(x.get("sector"), x.get("sector") or ""), f_share(x.get("weight_pct")),
                      f_pct(x.get("delta_pct")), f_rub(x.get("price_delta_rub"))] for i, x in enumerate(rows, 1)])

    # 5. Концентрация
    sec("Концентрация")
    conc = tree.get("concentration")
    if "concentration_ratio" not in tree or not isinstance(conc, dict):
        L.append("Концентрация не посчитана: в режиме «только числа» нет фактора концентрации (concentration.dominant_factor в fill).")
    else:
        L += _table(["Показатель", "Значение"], [
            ["Фактор", str(conc.get("dominant_factor", "—"))],
            ["concentration_ratio", f_num(tree["concentration_ratio"])],
            ["В ту же сторону", f_share(conc.get("same_direction_pct"))],
            ["В ту же сторону, с cnyrub", f_share(conc.get("same_direction_incl_cnyrub_pct"))],
            ["В обратную сторону", f_share(conc.get("opposite_pct"))],
            ["Нейтрально", f_share(conc.get("neutral_pct"))]])

    # 6. Метрики и robustness
    sec("Портфельные метрики и robustness")
    L += ["**Диапазон P&L по срокам**", ""]
    body = []
    for basis, _, label in BASES:
        agg = pa.get(basis) or {}
        rng = agg.get("pl_range_rub_by_horizon") or {}
        er = agg.get("expected_pl_rub_by_horizon") or {}
        ep = agg.get("expected_pl_pct_by_horizon") or {}
        for hk in hks:
            r = rng.get(hk) or {}
            body.append([basis, hk, f"{r.get('min_scenario', '—')} {f_rub(r.get('min'))}",
                         f"{r.get('max_scenario', '—')} {f_rub(r.get('max'))}",
                         f"{f_rub(er.get(hk))} ({f_pct(ep.get(hk))})" if er.get(hk) is not None else "—"])
    L += _table(["База", "Срок", "Худший сценарий", "Лучший сценарий", "Ожидание"], body) + [""]
    rob = tree.get("robustness") or {}
    L += ["**Robustness**", ""]
    body = []
    for basis, _, _ in BASES:
        bh = ((rob.get(basis) or {}).get("by_horizon")) or {}
        for hk in hks:
            c = bh.get(hk)
            if not c:
                continue
            body.append([basis, hk, str(c.get("positive_or_neutral_scenarios")),
                         f"{c['worst_case']['id']} {f_pct(c['worst_case']['pl_pct'])}",
                         f"{c['best_case']['id']} {f_pct(c['best_case']['pl_pct'])}", f_num(c.get("spread_pct"), 2) + " п.п."])
    if body:
        L += _table(["База", "Срок", "Сценариев с P&L ≥ 0", "Худший", "Лучший", "Разброс"], body) + [""]
    extra = [[k, str(rob[k])] for k in ("hedge_target", "modal_scenario") if rob.get(k) not in (None, MARK)]
    if extra:
        L += _table(["Поле", "Значение"], extra)
    else:
        L.append("hedge_target и modal_scenario не заданы (режим «только числа»).")

    # 7. Покрытие сроков
    sec("Покрытие сроков прогнозом")
    cov = tree.get("horizon_coverage") or {}
    L += _table(["Срок", "Дата", "Статус", "Множитель CI"],
                [[hk, str(tree["horizon_ends"].get(hk, "—")), str((cov.get(hk) or {}).get("status", "—")),
                  f_num((cov.get(hk) or {}).get("ci_inflation"))] for hk in hks])

    # 8. Купонный слой
    sec("Купонный слой (carry, портфель целиком)")
    cr = (tree.get("bond_carry") or {}).get("portfolio_level_by_horizon")
    if not isinstance(cr, dict) or not cr:
        L.append("Купонный слой в дереве не посчитан.")
    else:
        body = []
        for sid in sids:
            body.append([f"{sid} {sname[sid]}"] + [
                f"{f_rub(((cr.get(hk) or {}).get(sid) or {}).get('carry_rub'))} ({f_pct(((cr.get(hk) or {}).get(sid) or {}).get('carry_pct'))})"
                for hk in hks])
        L += _table(["Сценарий"] + hks, body)

    # 9. Вклад факторов
    fp = info.get("factor_probes")
    if fp and fp.get("ranking"):
        sec(f"Вклад факторов ({fp['horizon']}, ценовой слой)")
        pp = lambda v: "—" if v is None else _comma(f"{v:+.2f}")  # noqa: E731
        body = []
        for f in fp["ranking"]:
            c = fp["by_factor"][f]
            body.append([f] + [pp(c["by_scenario_pp"].get(s)) for s in sids]
                        + [pp(c["expected_pp"]), _comma(f"{c['abs_weighted_pp']:.2f}")])
        L += _table(["Фактор"] + [f"{s}, п.п." for s in sids] + ["Ожидание, п.п.", "Взвешенный |вклад|, п.п."], body) + [""]
        names = {"rub": "рубль", "gold": "золото"}
        for k, v in (fp.get("probes") or {}).items():
            L.append(f"Проба «{names.get(k, k)} = 0» ({'+'.join(v['factors'])}): "
                     f"по цене {f_pct(v['expected_price_pct']['base'])} → {f_pct(v['expected_price_pct']['without'])}; "
                     f"по полной доходности {f_pct(v['expected_total_pct']['base'])} → {f_pct(v['expected_total_pct']['without'])}.")
            L.append("")
        w = fp["worst_scenario"]
        neg = [(fp["by_factor"][f]["by_scenario_pp"].get(w), f) for f in fp["ranking"]]
        neg = [x for x in neg if x[0] is not None]
        if neg:
            v, f = min(neg, key=lambda x: (x[0], x[1]))
            L.append(f"Худший сценарий {w}: наибольший отрицательный вклад — {f} ({pp(v)} п.п.)." if v < 0
                     else f"Худший сценарий {w}: отрицательного вклада факторов нет.")
    return "\n".join(L) + "\n"
