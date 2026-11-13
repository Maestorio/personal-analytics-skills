#!/usr/bin/env python3
"""Живая доходность во вьюере (v3.45.0, 2026-10-23) — настоящим браузером против portfolio_returns.xirr.

Снапшот несёт returns.live_basis (потоки XIRR по дням + позиции конечной стоимости — кладёт загрузчик),
вьюер подставляет живые цены MOEX и решает то же уравнение. Контракты:
  1. xirrJs = portfolio_returns.xirr на тех же потоках (до 1e-6) — для нескольких наборов, в том числе
     с отрицательной доходностью;
  2. liveReturns без живых цен (или с ценами, равными снапшотным) = XIRR снапшота — total и restricted;
  3. живая цена акции/фонда меняет конечную стоимость: qty × цена; облигации, заблокированные,
     внебиржевые без котировки — по снапшоту;
  4. бумага, которую загрузчик оценил НЕ по MOEX (случай TGLD 22.10: цена последней сделки), попадает
     в fixed и считается по живой цене — ошибка цены в снапшоте исправляется сама;
  5. нет live_basis (старый снапшот) → null (плитка остаётся на XIRR снапшота);
  6. строки доходности (ЖД-1): на ценах снапшота пересчёт вьюера = загрузчик — по бумаге (per_instrument_xirr,
     в том числе на двух счетах), по типу (returns.by_type), активная часть, вся история, ИИС-3 — на синтетическом
     портфеле, собранном настоящими pr.build_report / asm._live_flows_by_ticker (допуск 1e-4);
  7. живая цена облигации (% номинала + НКД котировки, номинал котировки главнее) меняет XIRR её строки, плитки
     «Облигации» и ИИС-3; валютная облигация — по курсу ЦБ quotes.fx и НКД в ₽ (без курса или при НКД не в рублях — по снапшоту); без котировки — по снапшоту;
     старый снапшот без face/face_ccy/accrued_rub — номинал, валюта и НКД из котировки;
  8. liveApplyReturns кладёт живые значения в копию (бумага + ISIN-алиас, тип, ИИС-3, итоги) и не трогает
     исходный снапшот; перенесённый (carried_from) блок ИИС-3 живым не считается.
Данные синтетические — финансовых данных владельца в репозитории нет.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_live_xirr.py
"""
import copy
import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import serve  # noqa: E402  (стенд — _pages_stand, keep-alive)
sys.path.insert(0, str(REPO / "skills/portfolio-data-loader/scripts"))
import assemble_snapshot as asm  # noqa: E402
import iis_returns  # noqa: E402
import portfolio_returns as pr  # noqa: E402
from unittest import mock  # noqa: E402

passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name} {extra}")


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("viewer_live_xirr: пропуск — нет playwright")
    sys.exit(0)

D = dt.date.fromisoformat
TODAY = "2026-10-23"
FLOWS_T = [["2019-11-11", -100000.0], ["2020-03-02", -250000.0], ["2021-06-15", -400000.0],
           ["2022-02-20", 50000.0], ["2023-05-10", -300000.0], ["2025-01-20", -150000.0]]
FLOWS_R = [["2022-03-01", -900000.0], ["2023-05-10", -300000.0], ["2025-01-20", -150000.0]]
POS = [
    {"ticker": "SBER", "type": "stock", "qty": 1000, "value_rub": 290000.0, "price_source": "moex", "blocked": False},
    {"ticker": "TGLD", "type": "fund", "qty": 10000, "value_rub": 145800.0, "price_source": "last_trade_price",
     "blocked": False},                                        # загрузчик ошибся: 14,58 вместо MOEX
    {"ticker": "RU000A1", "type": "bond", "qty": 500, "value_rub": 510000.0, "price_source": "moex", "blocked": False},
    {"ticker": "FINAMAR", "type": "fund", "qty": 1, "value_rub": 150000.0, "price_source": "cost_basis",
     "blocked": False},
    {"ticker": "JPM", "type": "stock", "qty": 2, "value_rub": 0.0, "price_source": "blocked_zero", "blocked": True},
]
BASIS = {"terminal_date": TODAY, "cash_rub": 40000.0, "flows_total": FLOWS_T, "flows_restricted": FLOWS_R,
         "positions": POS}


def py_xirr(flows, terminal):
    return pr.xirr([(D(d), a) for d, a in flows] + [(D(TODAY), terminal)])


TODAY2 = "2026-10-22"


def py_xirr_d(flows, lb, prices):
    """XIRR total по потокам и позициям lb: акции/фонды по ценам prices, остальное — по оценке снапшота."""
    t = lb["cash_rub"]
    for p in lb["positions"]:
        t += p["qty"] * prices[p["ticker"]] if p["ticker"] in prices and p["type"] in ("stock", "fund") and not p["blocked"] else p["value_rub"]
    return pr.xirr([(D(d), a) for d, a in flows] + [(D(lb["terminal_date"]), t)])


def terminal(prices=None, restricted=False):
    prices = prices or {}
    t = BASIS["cash_rub"]
    for p in POS:
        if restricted and p["blocked"]:
            continue
        v = p["value_rub"]
        if not p["blocked"] and p["type"] in ("stock", "fund") and p["ticker"] in prices:
            v = p["qty"] * prices[p["ticker"]]
        t += v
    return t


# ── Синтетический портфель: настоящие pr.build_report / asm._live_flows_by_ticker, сеть подменена ──────────────────
TD = dt.date(2026, 10, 22)
CASHT = "Деньги (RUB)"
BOND, BOND2 = "RU000A1ZZZ1", "RU000A1ZZZ2"      # BOND — на двух счетах; BOND2 — только на ИИС-3


def T(tk, op, day, amt, qty=1, price=1.0):
    return pr.Trade(ticker=tk, name=tk if tk == CASHT else "Бумага " + tk, operation=op, date=day, qty=qty, price=price,
                    nominal=None, nkd=None, commission=0.0, amount=amt, amount_no_comm=amt, currency="RUB", note="",
                    rub_amount=amt)


MAIN_ONLY = [
    T(CASHT, "Внесение", dt.date(2021, 6, 1), 4_000_000.0),
    T("SBER", "Покупка", dt.date(2021, 6, 2), -500000.0, 2000, 250),      # до окна 01.03.2022 — стартовая стоимость restricted
    T("SBER", "Дивиденд", dt.date(2023, 7, 20), 20000.0),
    T("TMON", "Покупка", dt.date(2023, 2, 1), -300000.0, 30000, 10),
    T("SBER", "Покупка", dt.date(2024, 5, 3), -100000.0, 340, 294),
    T(BOND, "Покупка", dt.date(2024, 1, 10), -700000.0, 700, 100),
    T(BOND, "Купон", dt.date(2024, 7, 10), 30000.0),
]
IIS_ONLY = [
    T(CASHT, "Внесение", dt.date(2025, 3, 1), 500_000.0),
    T(BOND, "Покупка", dt.date(2025, 3, 5), -200000.0, 200, 100),
    T(BOND, "Купон", dt.date(2025, 9, 5), 8000.0),
    T(BOND2, "Покупка", dt.date(2025, 4, 1), -100000.0, 100, 100),
    T(BOND2, "Купон", dt.date(2025, 10, 1), 4000.0),
]
PRICES = {"SBER": 310.0, "TMON": 11.2, BOND: 96.5, BOND2: 99.0}
ACCR = {BOND: 12.5, BOND2: 3.0}


def _fake_moex(cands, verbose=False, accrued_out=None):
    accrued_out.update(ACCR)
    last = {t: PRICES[t] for t in cands if t in PRICES}
    return last, {t: 1000.0 for t in (BOND, BOND2)}, {t: "SUR" for t in (BOND, BOND2)}, set()


def report(trades):
    with mock.patch.object(pr, "fetch_moex_prices", side_effect=_fake_moex), mock.patch.object(pr, "ensure_cbr_rates"):
        return pr.build_report(trades, [], as_of=TD, use_moex=True, with_benchmarks=False, cbr_offline=True)


def per_security(trades, rep, only=None):
    """Записи per_security как у per_security_xirr: потоки сделок + терминал (as_of, +стоимость), xirr_frac."""
    mv = {p["ticker"]: p for p in rep["snapshot_current"]["positions"]}
    out = {}
    for tk in sorted({t.ticker for t in trades if t.ticker != CASHT}):
        if only and tk not in only:
            continue
        cfs = []
        for t in trades:
            if t.ticker != tk:
                continue
            a = abs(t.rub_amount)
            cfs.append((t.date, -a if t.operation == "Покупка" else a))
        v = mv[tk]["value_rub"] if tk in mv else 0.0
        if v > 0:
            cfs.append((TD, v))
        cfs.sort(key=lambda x: x[0])
        out[tk] = {"cashflows": [(d.isoformat(), round(a, 2)) for d, a in cfs], "market_value_rub": v,
                   "xirr_frac": round(pr.xirr(cfs), 4), "qty_now": mv[tk]["qty"] if tk in mv else 0.0}
    return out


def build_synth():
    all_tr = MAIN_ONLY + IIS_ONLY
    rep, rep_iis = report(all_tr), report(IIS_ONLY)
    ps = per_security(all_tr, rep)
    ps_iis = per_security(IIS_ONLY, rep_iis)
    pi = {}
    for tk, r in ps.items():
        pi[tk] = {"xirr": r["xirr_frac"], "qty_now": r["qty_now"], "market_value_rub": r["market_value_rub"],
                  "pnl_rub": 1000.0}
    iis_flows = {tk: {"cashflows": r["cashflows"][:-1] if r["market_value_rub"] > 0 else r["cashflows"],
                      "qty_now": r["qty_now"]} for tk, r in ps_iis.items()}
    pi[BOND]["by_account"] = {"main": {"qty_now": ps[BOND]["qty_now"] - ps_iis[BOND]["qty_now"], "market_value_rub": 0.0, "pnl_rub": 0.0},
                              "iis_3": {"qty_now": ps_iis[BOND]["qty_now"], "market_value_rub": 0.0, "pnl_rub": 0.0}}
    pi["RU000A1ALIAS"] = {**pi[BOND], "alias_of": BOND}
    fl_t, fl_a = asm._live_flows_by_ticker(ps, pi, iis_flows, TD.isoformat())
    lb = {**rep["live_basis"], "flows_by_ticker": fl_t, "flows_by_ticker_account": fl_a}
    snap = {"per_instrument_xirr": pi,
            "returns": {"live_basis": lb, "by_account": {"iis_3": {"status": "ok", "fact": {"xirr": rep_iis["returns_total"]["xirr"], "pnl_rub": 100.0, "current_value_rub": 1.0},
                                                                   "live_basis": iis_returns._iis_live_basis(rep_iis["live_basis"])}},
                        "total": {"xirr": rep["returns_total"]["xirr"], "pnl_rub": 10.0}, "restricted": {"xirr": rep["returns_restricted"]["xirr"], "pnl_rub": 5.0},
                        "by_type": {t: {"xirr": v["xirr"], "pnl_rub": 1.0} for t, v in rep["returns_by_type_restricted"].items()}}}
    return rep, rep_iis, ps, ps_iis, pi, snap, lb


def quotes_at_snapshot(positions):
    """quotes@1 с ценами, при которых qty × (цена/100 × номинал + НКД) = value_rub позиции (облигации), qty × цена (акции/фонды)."""
    items = {}
    for p in positions:
        if p["blocked"] or not p["qty"]:
            continue
        u = p["value_rub"] / p["qty"]
        if p["type"] == "bond":
            items[p["ticker"]] = {"price": (u - p["accrued_rub"]) / p["face"] * 100, "face_value": p["face"], "accrued_int": p["accrued_rub"], "face_unit": "SUR"}
        else:
            items[p["ticker"]] = {"price": u}
    return {"items": items, "fetched_at": "2026-10-22T12:00:00+03:00"}


def main():
    httpd = serve(directory=REPO)[0]   # _pages_stand: очередь 128, keep-alive
    url = f"http://127.0.0.1:{httpd.server_address[1]}/tools/portfolio-integrated-viewer.html"
    with sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception:  # noqa: BLE001
            print("viewer_live_xirr: пропуск — нет chromium")
            return 0
        pg = br.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("**/api/**", lambda r: r.fulfill(status=502, body="{}"))
        pg.goto(url)
        pg.wait_for_function("typeof liveReturns === 'function' && typeof xirrJs === 'function'", timeout=20000)
        js = lambda expr, arg=None: pg.evaluate(expr, arg)  # noqa: E731

        # 1. xirrJs = portfolio_returns.xirr
        for name, flows, term in (("рост", FLOWS_T, 1_600_000.0), ("убыток", FLOWS_T, 700_000.0),
                                  ("restricted", FLOWS_R, 1_500_000.0)):
            a = js("([f, t, d]) => xirrJs([...f, [d, t]])", [flows, term, TODAY])
            b = py_xirr(flows, term)
            check(f"xirrJs = portfolio_returns.xirr ({name})", a is not None and abs(a - b) < 1e-6, f"{a} vs {b}")

        # 2. без живых цен — XIRR снапшота (total с заблокированными, restricted без них)
        q0 = js("([b, d]) => liveReturns(b, {items: {}}, d)", [BASIS, TODAY])
        check("без цен: total = XIRR снапшота", abs(q0["total"] - py_xirr(FLOWS_T, terminal())) < 1e-6)
        check("без цен: restricted = XIRR снапшота",
              abs(q0["restricted"] - py_xirr(FLOWS_R, terminal(restricted=True))) < 1e-6)
        check("без цен: ничего не подставлено", q0["applied"] == 0 and q0["fixed"] == [])

        # 3–4. живые цены: акция и фонд пересчитаны, облигация/заблок./FINAMAR без котировки — нет
        quotes = {"items": {"SBER": {"price": 300.0}, "TGLD": {"price": 12.96}, "RU000A1": {"price": 99.0},
                            "JPM": {"price": 27000.0}}, "fetched_at": "2026-10-23T12:00:00+03:00"}
        q1 = js("([b, q, d]) => liveReturns(b, q, d)", [BASIS, quotes, TODAY])
        lp = {"SBER": 300.0, "TGLD": 12.96}
        check("живые цены: total по qty × цена акций и фондов",
              abs(q1["total"] - py_xirr(FLOWS_T, terminal(lp))) < 1e-6, f"{q1['total']}")
        check("живые цены: restricted", abs(q1["restricted"] - py_xirr(FLOWS_R, terminal(lp, True))) < 1e-6)
        check("облигация и заблокированная — по снапшоту (подставлено 2: SBER, TGLD)", q1["applied"] == 2)
        check("ошибка цены снапшота исправлена живой ценой: TGLD в fixed", q1["fixed"] == ["TGLD"])
        check("стоимость на живых ценах", abs(q1["value_rub"] - terminal(lp)) < 0.01)

        # 5. старый снапшот без live_basis
        check("нет live_basis → null", js("() => liveReturns(null, {items: {}})") is None
              and js("() => liveReturns({flows_total: []}, {items: {}})") is None)

        # 6. ЖД-1: пересчёт вьюера на ценах снапшота = загрузчик по всем строкам доходности
        rep, rep_iis, ps, ps_iis, pi, snap, lb = build_synth()
        qs = quotes_at_snapshot(lb["positions"])
        r6 = js("([b, q, d, s]) => liveReturns(b, q, d, s)", [lb, qs, TODAY2, snap])
        tol = 1e-4
        check("снапшотные цены: total = returns_total.xirr загрузчика", abs(r6["total"] - rep["returns_total"]["xirr"]) < tol, f"{r6['total']} vs {rep['returns_total']['xirr']}")
        check("снапшотные цены: restricted = returns_restricted.xirr", abs(r6["restricted"] - rep["returns_restricted"]["xirr"]) < tol)
        for t, v in rep["returns_by_type_restricted"].items():
            if v["xirr"] is None:
                continue
            check(f"снапшотные цены: тип {t} = returns_by_type_restricted.xirr", abs(r6["by_type"][t]["xirr"] - v["xirr"]) < tol, f"{r6['by_type'].get(t)} vs {v['xirr']}")
        for tk in ("SBER", "TMON", BOND, BOND2):
            check(f"снапшотные цены: бумага {tk} = xirr_frac per_security", abs(r6["by_ticker"][tk]["xirr"] - ps[tk]["xirr_frac"]) < tol,
                  f"{r6['by_ticker'].get(tk)} vs {ps[tk]['xirr_frac']}")
        check("снапшотные цены: ИИС-3 = fact.xirr счёта", abs(r6["iis_3"]["xirr"] - rep_iis["returns_total"]["xirr"]) < tol)
        check("бумага на двух счетах: потоки счетов сложены в потоки бумаги",
              abs(sum(a for _d, a in lb["flows_by_ticker_account"][BOND]["main"]) + sum(a for _d, a in lb["flows_by_ticker_account"][BOND]["iis_3"])
                  - sum(a for _d, a in lb["flows_by_ticker"][BOND])) < 0.01)
        check("бумага на двух счетах: xirr счетов посчитаны", set(r6["by_ticker"][BOND]["by_account"]) == {"main", "iis_3"}
              and all(v["xirr"] is not None for v in r6["by_ticker"][BOND]["by_account"].values()))
        check("алиас ISIN в by_ticker отдельно не считается (потоки только под SECID)", "RU000A1ALIAS" not in r6["by_ticker"])

        # 7. живая цена облигации
        q7 = copy.deepcopy(qs)
        q7["items"][BOND] = {"price": 99.2, "face_value": 1000, "accrued_int": 14.0, "face_unit": "SUR"}
        q7["items"]["SBER"] = {"price": 330.0}
        r7 = js("([b, q, d, s]) => liveReturns(b, q, d, s)", [lb, q7, TODAY2, snap])
        pos = {p["ticker"]: p for p in lb["positions"]}
        v_bond = pos[BOND]["qty"] * (99.2 / 100 * 1000 + 14.0)
        want_b = pr.xirr([(D(d), a) for d, a in lb["flows_by_ticker"][BOND]] + [(D(TODAY2), v_bond)])
        check("облигация: XIRR строки = потоки + qty × (цена/100 × номинал + НКД) котировки", abs(r7["by_ticker"][BOND]["xirr"] - want_b) < 1e-6, f"{r7['by_ticker'][BOND]['xirr']} vs {want_b}")
        check("облигация: цена выше — XIRR строки выше, чем на ценах снапшота", r7["by_ticker"][BOND]["xirr"] > r6["by_ticker"][BOND]["xirr"])
        check("облигация: pnl строки сдвинут на разницу стоимости", abs(r7["by_ticker"][BOND]["pnl_rub"] - (1000.0 + v_bond - pi[BOND]["market_value_rub"])) < 0.01)
        want_t = pr.xirr([(D(d), a) for d, a in lb["flows_by_type"]["bond"]] + [(D(TODAY2), sum(
            p["qty"] * (99.2 / 100 * 1000 + 14.0) if p["ticker"] == BOND else p["value_rub"] for p in lb["positions"] if p["type"] == "bond" and not p["blocked"]))])
        check("облигация: XIRR типа «bond» пересчитан по живой стоимости облигаций", abs(r7["by_type"]["bond"]["xirr"] - want_t) < 1e-6)
        check("облигация: ИИС-3 и итоги меняются от живой цены", r7["iis_3"]["xirr"] != r6["iis_3"]["xirr"] and r7["total"] != r6["total"] and r7["applied_bonds"] == 2)
        check("в бумагах на двух счетах стоимость счёта = количество счёта × живая стоимость",
              abs(r7["by_ticker"][BOND]["by_account"]["iis_3"]["market_value_rub"] - pi[BOND]["by_account"]["iis_3"]["qty_now"] * (99.2 / 100 * 1000 + 14.0)) < 0.01)
        # валютная облигация: номинал/валюта/НКД — из котировки, курс ЦБ — quotes.fx; без курса, без котировки — по снапшоту
        q_usd = copy.deepcopy(q7)
        q_usd["items"][BOND] = {"price": 99.2, "face_value": 1000, "accrued_int": 14.0, "face_unit": "USD", "currency_id": "SUR"}
        q_usd["fx"] = {"USD": 80.0, "EUR": 90.0, "CNY": 11.0, "date": TODAY2}
        rx = js("([b, q, d, s]) => liveReturns(b, q, d, s)", [lb, q_usd, TODAY2, snap])
        v_fx = pos[BOND]["qty"] * (99.2 / 100 * 1000 * 80.0 + 14.0)
        want_fx = pr.xirr([(D(d), a) for d, a in lb["flows_by_ticker"][BOND]] + [(D(TODAY2), v_fx)])
        check("валютная облигация: XIRR строки = потоки + qty × (цена/100 × номинал × курс ЦБ + НКД в ₽)",
              BOND in rx["by_ticker"] and abs(rx["by_ticker"][BOND]["xirr"] - want_fx) < 1e-6, rx["by_ticker"].get(BOND))
        check("валютная облигация: стоимость меняет итог и считается живой (applied_bonds)", rx["total"] != r6["total"] and rx["applied_bonds"] == 2)
        q_nofx = copy.deepcopy(q_usd)
        del q_nofx["fx"]
        rnf = js("([b, q, d, s]) => liveReturns(b, q, d, s)", [lb, q_nofx, TODAY2, snap])
        check("валютная облигация без курса ЦБ — по снапшоту: строки нет", BOND not in rnf["by_ticker"] and rnf["applied_bonds"] == 1)
        q_cur = copy.deepcopy(q_usd)
        q_cur["items"][BOND]["currency_id"] = "CNY"
        rcu = js("([b, q, d, s]) => liveReturns(b, q, d, s)", [lb, q_cur, TODAY2, snap])
        check("НКД котировки не в рублях (currency_id CNY) — по снапшоту", BOND not in rcu["by_ticker"])
        q_no = copy.deepcopy(q7)
        del q_no["items"][BOND]
        rn = js("([b, q, d, s]) => liveReturns(b, q, d, s)", [lb, q_no, TODAY2, snap])
        check("облигации нет в котировках — строки нет, итог по её снапшотной стоимости", BOND not in rn["by_ticker"] and rn["applied_bonds"] == 1)
        lb_old = {k: v for k, v in lb.items() if k not in ("flows_by_type", "flows_by_ticker", "flows_by_ticker_account")}
        for p in lb_old["positions"]:
            for k in ("face", "face_ccy", "accrued_rub"):
                p.pop(k, None)
        r_old = js("([b, q, d, s]) => liveReturns(b, q, d, s)", [lb_old, q7, TODAY2, {"per_instrument_xirr": pi}])
        check("снапшот без face/face_ccy/accrued_rub: номинал, валюта и НКД берутся из котировки — итог как с полями; строк по типам и бумагам нет",
              "by_type" not in r_old and "by_ticker" not in r_old and r_old["applied_bonds"] == r7["applied_bonds"]
              and abs(r_old["total"] - r7["total"]) < 1e-9)

        # 8. liveApplyReturns: копия, алиас, исходник цел
        snap_live = copy.deepcopy(snap)
        before = json.dumps(snap, sort_keys=True)
        snap_live = js("([s, r]) => { liveApplyReturns(s, r); return s; }", [snap_live, r7])
        check("liveApplyReturns: бумага, ISIN-алиас, тип, итоги, ИИС-3 получили живые значения",
              snap_live["per_instrument_xirr"][BOND]["xirr"] == r7["by_ticker"][BOND]["xirr"]
              and snap_live["per_instrument_xirr"]["RU000A1ALIAS"]["xirr"] == r7["by_ticker"][BOND]["xirr"]
              and snap_live["per_instrument_xirr"][BOND]["live_ret"] is True
              and snap_live["per_instrument_xirr"][BOND]["by_account"]["iis_3"]["xirr"] == r7["by_ticker"][BOND]["by_account"]["iis_3"]["xirr"]
              and snap_live["returns"]["by_type"]["bond"]["xirr"] == r7["by_type"]["bond"]["xirr"]
              and snap_live["returns"]["total"]["xirr"] == r7["total"] and snap_live["returns"]["restricted"]["xirr"] == r7["restricted"]
              and snap_live["returns"]["by_account"]["iis_3"]["fact"]["xirr"] == r7["iis_3"]["xirr"]
              and snap_live["returns"]["by_account"]["iis_3"]["fact"]["current_value_rub"] == r7["iis_3"]["value_rub"])
        check("liveApplyReturns: pnl_rub типа и итогов сдвинут на разницу конечной стоимости",
              abs(snap_live["returns"]["by_type"]["bond"]["pnl_rub"] - (1.0 + r7["by_type"]["bond"]["d_value"])) < 1e-6
              and abs(snap_live["returns"]["total"]["pnl_rub"] - (10.0 + r7["d_total"])) < 1e-6)
        check("liveApplyReturns копию не путает с исходным: исходный снапшот не тронут", json.dumps(snap, sort_keys=True) == before)
        snap_c = copy.deepcopy(snap)
        snap_c["returns"]["by_account"]["iis_3"]["carried_from"] = "2026-10-01"
        rc = js("([b, q, d, s]) => liveReturns(b, q, d, s)", [lb, q7, TODAY2, snap_c])
        check("перенесённый блок ИИС-3 (carried_from) живым не считается", "iis_3" not in rc)
        check("ошибок JS нет", not errs, str(errs[:2]))
        br.close()
    httpd.shutdown()
    print(f"viewer_live_xirr: {passed} OK, {failed} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
