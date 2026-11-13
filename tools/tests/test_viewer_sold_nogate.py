#!/usr/bin/env python3
"""Вьюер, проход читаемости 4.1.0, пачка 1 («ошибки», аудит 31.10, находки F2, F5, F9) — настоящий Chromium.

Фикстура — viewer-live + superseded (живые файлы, переведённые миграциями) во временной папке; правки фикстуры повторяют живую картину:
  — GLRX продана: в последнем снапшоте (08.10) бумаги нет, доля по ie_actual 0; обзор 28.10 — SELL, проверка «срочно» (как на живых данных);
  — ранний снапшот (26.09) пишет фонды TMON и XXXXXX как stock (так писали снапшоты до 05.2026);
  — у YDEX запись per_instrument_xirr с синтетическими числами (для F9).
Контракты:
  F2. Проданная бумага (гейт модуля (б) «продана»): на «Действиях» строки GLRX в «Сделать» нет, в «Сделано» —
      «продана 08.10 — вердикт обзора 28.10 исполнен»; «N сделать» в шапке «Действий», число на ярлыке «Действий» и «Требует внимания»
      на «Сегодня» меньше на 1, чем у той же фикстуры без продажи; в «Ближайших 30 днях» срока решения GLRX нет (без продажи — есть);
      карточка: «Решение» — «Продана 08.10», последнее слово словами (R27: без «гейт»), проза обзора свёрнута («подробнее»), нет «Продать … при плане»,
      плиток «Ожидание» и «Потенциал IE» и метки «проверка перед сделкой» нет; «Акции»: число бумаг плитки = «в портфеле N» таблицы.
  F5. Гейт только у акций: тип бумаги — последний известный (фонд в текущем снапшоте — не акция, хотя ранний снапшот писал stock):
      gateOf(TMON) = null; окно «Решения»: TMON и XXXXXX — в группе «Фонды и облигации — решения без закрытия докупки» (вердикт словом,
      срок), без «докупка …», ни в одном фильтре статуса их нет; GLRX — «продана».
  F9. Плитка «Моя доходность» при живых ценах подписана «результат … по снапшоту 08.10» (таблица «Позиция → Результат» — по цене MOEX
      и отличается); без живых цен подписи нет и числа совпадают.
  Ошибок страницы нет.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_sold_nogate.py
"""
import json
import re
import shutil
import sys
import tempfile
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import quote as _q, unquote as _unq, urlparse as _up

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import serve  # noqa: E402  (стенд — _pages_stand, keep-alive)
passed = failed = 0


def check(name, cond_):
    global passed, failed
    if cond_:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("viewer_sold_nogate: пропуск — нет playwright")
    sys.exit(0)

sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as hub_api  # noqa: E402

FIX = Path(tempfile.mkdtemp(prefix="soldnogate-"))
QUOTES = json.loads((REPO / "tools/tests/fixtures/iss/quotes-tqbr.json").read_text(encoding="utf-8"))
TODAY = "2026-10-30"   # срок решения GLRX (пересмотр до 03.11) попадает в «Ближайшие 30 дней»


def build(sold=True):
    shutil.rmtree(FIX, ignore_errors=True)
    shutil.copytree(REPO / "tools/tests/fixtures/viewer-live", FIX)
    shutil.copytree(REPO / "tools/tests/fixtures/superseded", FIX, dirs_exist_ok=True)
    (FIX / "monitor-reports").mkdir()
    sd = FIX / "Portfolio/snapshots"
    old = json.loads((sd / "portfolio-2026-09-26.json").read_text(encoding="utf-8"))
    for h in old["holdings"]:
        if h.get("ticker") in ("TMON", "XXXXXX"):
            h["asset_type"] = "stock"
    (sd / "portfolio-2026-09-26.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    cur = json.loads((sd / "portfolio-2026-10-08.json").read_text(encoding="utf-8"))
    if sold:
        cur["holdings"] = [h for h in cur["holdings"] if h.get("ticker") != "GLRX"]
        pt = (cur.get("ie_actual") or {}).get("per_ticker") or {}
        if "GLRX" in pt:
            pt["GLRX"]["real_share_pct"] = 0.0
    yd = next(h for h in cur["holdings"] if h.get("ticker") == "YDEX")
    cur.setdefault("per_instrument_xirr", {})["YDEX"] = {"xirr": 0.1, "pnl_rub": 1000.0, "buy_total_rub": 50000.0, "sell_total_rub": 0.0,
                                                         "dividends_rub": 0.0, "market_value_rub": yd["value_rub"], "first_trade_date": "2024-01-10"}
    (sd / "portfolio-2026-10-08.json").write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")


def build_bond():
    """R29 (4.2.1): погашенная облигация ЛаймЗайм04 (RU000A107795, погашение 30.10) — в снапшоте 30.10 есть, в 03.11 нет;
    обзор облигаций 28.10 — «держать до погашения», проверка «срочно» с тремя пунктами. В графике выплат 03.11 — купон
    погашенной бумаги 15.11 (после ухода — не показывать)."""
    shutil.rmtree(FIX, ignore_errors=True)
    shutil.copytree(REPO / "tools/tests/fixtures/viewer-live", FIX)
    for part in ("superseded", "bond-actions"):
        shutil.copytree(REPO / "tools/tests/fixtures" / part, FIX, dirs_exist_ok=True)
    (FIX / "monitor-reports").mkdir(exist_ok=True)
    sd = FIX / "Portfolio/snapshots"
    cur = json.loads((sd / "portfolio-2026-10-08.json").read_text(encoding="utf-8"))
    cur["as_of_date"] = "2026-10-30"
    (sd / "portfolio-2026-10-30.json").write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
    nxt = json.loads(json.dumps(cur))
    nxt["holdings"] = [h for h in nxt["holdings"] if h.get("isin") != "RU000A107795"]
    nxt["as_of_date"] = "2026-11-03"
    nxt["bond_cashflow_calendar"] = {"horizon_months": 12, "as_of": "2026-11-03",
                                     "by_month": {"2026-11": {"coupons_rub": 1500.0, "redemptions_rub": 0.0, "offers_rub": 0.0}},
                                     "detail": [{"ticker": "RU000A107795", "name": "ЛаймЗайм04", "kind": "coupon", "date": "2026-11-15", "amount_rub": 1000.0},
                                                {"ticker": "RU000A106EP1", "name": "ОФЗ", "kind": "coupon", "date": "2026-11-20", "amount_rub": 500.0}],
                                     "totals": {}, "flags": [], "notes": []}
    (sd / "portfolio-2026-11-03.json").write_text(json.dumps(nxt, ensure_ascii=False), encoding="utf-8")


def build_iis():
    """4.2.4: ушедшие бумаги на «ИИС-3» и «Фондах». Снапшот 30.10 — копия 08.10, у ОФЗ 52004 (RU000A103MX5, только ИИС-3) погашение 30.10;
    в 03.11 её нет (погашена), нет фонда TPAY основного счёта (продан) и фонда SBGB с ИИС-3 (продан), а расчёт счёта ИИС-3 перенесён
    из 30.10 и ещё помнит SBGB в other_positions (без новой выгрузки)."""
    shutil.rmtree(FIX, ignore_errors=True)
    shutil.copytree(REPO / "tools/tests/fixtures/viewer-live", FIX)
    for part in ("superseded", "bond-actions"):
        shutil.copytree(REPO / "tools/tests/fixtures" / part, FIX, dirs_exist_ok=True)
    (FIX / "monitor-reports").mkdir(exist_ok=True)
    sd = FIX / "Portfolio/snapshots"
    cur = json.loads((sd / "portfolio-2026-10-08.json").read_text(encoding="utf-8"))
    cur["as_of_date"] = "2026-10-30"
    for h in cur["holdings"]:
        if h.get("isin") == "RU000A103MX5":
            h["maturity_date"] = "2026-10-30"
    (sd / "portfolio-2026-10-30.json").write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
    nxt = json.loads(json.dumps(cur))
    nxt["holdings"] = [h for h in nxt["holdings"] if h.get("isin") != "RU000A103MX5" and h.get("ticker") not in ("TPAY", "SBGB")]
    nxt["as_of_date"] = "2026-11-03"
    nxt.setdefault("returns", {}).setdefault("by_account", {})["iis_3"] = {
        "carried_from": "2026-10-30", "as_of": "2026-10-30", "status": "unverified", "per_bond": [],
        "other_positions": [{"secid": "SBGB", "kind": "fund", "qty": 10, "value_rub": 150.0}]}
    (sd / "portfolio-2026-11-03.json").write_text(json.dumps(nxt, ensure_ascii=False), encoding="utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        have = json.loads(self.rfile.read(n) or b"{}").get("have") or {}
        if _up(self.path).path != "/api/pv/sync":
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        body = json.dumps(hub_api.pv_sync(str(FIX), have)).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = _unq(_up(self.path).path)
        f = REPO / "tools" / p[len("/tools/"):] if p.startswith("/tools/") else FIX / p.lstrip("/")
        if f.is_dir() or (p.endswith("/") and not f.exists()):
            body = ("<html><body>" + "".join(f'<a href="{_q(c.name)}{"/" if c.is_dir() else ""}">{c.name}</a>\n'
                                             for c in (sorted(f.iterdir()) if f.is_dir() else [])) + "</body></html>").encode()
            ct = "text/html"
        elif f.is_file():
            body = f.read_bytes()
            ct = {".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css",
                  ".json": "application/json", ".woff2": "font/woff2"}.get(f.suffix, "text/plain; charset=utf-8")
        else:
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)


srv = serve(Handler)[0]   # _pages_stand: очередь 128, keep-alive
URL = f"http://127.0.0.1:{srv.server_address[1]}/tools/portfolio-integrated-viewer.html"


def norm(t):
    return re.sub(r"[\s  ]+", " ", t or "").strip()


def open_page(p, quotes=False):
    browser = p.chromium.launch()
    ctx = browser.new_context(service_workers="block", viewport={"width": 1400, "height": 1000})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "502" not in m.text and "404" not in m.text else None)
    pg.route("**/api/pv/plan*", lambda r: r.fulfill(status=502, body="{}"))
    pg.route("**/api/moex/quotes*", (lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(QUOTES)))
             if quotes else (lambda r: r.fulfill(status=502, body="{}")))
    pg.goto(URL)
    pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
    pg.wait_for_function("() => state.data && state.data.portfolioLatest && state.data.weeklyReviewCurrent && state.data.decisions.length", timeout=20000)
    pg.evaluate("(d) => { state.todayOverride = d; dsInvalidate(); }", TODAY)
    if quotes:
        pg.wait_for_function("() => (currentPort()?.holdings || []).some(h => h.current_price_source === 'moex_live')", timeout=10000)
    return browser, pg, errs


def counts(pg):
    """счётчики «Действий» и «Сегодня», строки 30 дней по GLRX."""
    pg.evaluate("() => { goToTab('actions'); }")
    pg.wait_for_selector("#content #act-head", timeout=10000)
    pg.wait_for_timeout(400)
    head = norm(pg.locator("#content #act-head").inner_text())
    m = re.search(r"(\d+) сделать", head)
    up = pg.evaluate("() => { const c = buildUpcomingCard(); return c ? c.innerText : ''; }")
    return {"dec": int(m.group(1)) if m else None, "attn": pg.evaluate("() => actionCounts().attention"),
            "badge": pg.evaluate("() => (document.querySelector('#tabs .ui-tab[data-tab=actions] .ui-tab-n, #tabs [data-tab=actions] .badge') || {}).textContent || ''"),
            "rows": pg.evaluate("() => [...document.querySelectorAll('#act-do .act-dec[data-ticker]')].map(e => e.dataset.ticker)"),
            "sold": pg.evaluate("() => { const x = document.querySelector('#act-done [data-sold=GLRX]'); return x ? x.textContent : null; }"),
            "up_glrx": [ln for ln in up.split("\n") if "GLRX" in ln or "Glorax" in ln], "up": up}


def main():
    with sync_playwright() as p:
        try:
            p.chromium.launch().close()
        except Exception as e:
            print(f"viewer_sold_nogate: пропуск — {str(e).splitlines()[0][:80]}")
            return

        # база: та же фикстура без продажи
        build(sold=False)
        browser, pg, errs = open_page(p)
        base = counts(pg)
        check(f"без продажи: GLRX в «Сделать» ({base['rows']})", "GLRX" in base["rows"])
        check(f"без продажи: срок решения GLRX в «Ближайших 30 днях» ({base['up'][:200]!r})", "истекает срок решения" in base["up"] and "GLRX" in base["up"])
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        build(sold=True)
        browser, pg, errs = open_page(p)
        check("GLRX: гейт «продана», дата продажи — снапшот 08.10", pg.evaluate("() => JSON.stringify(divestedOf('GLRX'))") == '{"sold":"2026-10-08","kind":"sold"}')
        s = counts(pg)
        check(f"F2: GLRX нет в «Сделать» ({s['rows']})", "GLRX" not in s["rows"])
        check(f"F2: «Сделано» — «продана 08.10 — вердикт обзора 28.10 исполнен» ({s['sold']!r})", "продана 08.10 — вердикт обзора 28.10 исполнен" in norm(s["sold"] or ""))
        check(f"F2: «сделать» в шапке «Действий» меньше на 1 ({s['dec']} против {base['dec']})", s["dec"] == base["dec"] - 1)
        check(f"F2: «Требует внимания» (и ярлык «Действий») меньше на 1 ({s['attn']} против {base['attn']})", s["attn"] == base["attn"] - 1)
        check(f"F2: в «Ближайших 30 днях» срока решения проданной бумаги нет ({s['up_glrx']})", not any("срок решения" in x for x in s["up_glrx"]) and "«Продана»" not in s["up"])
        pg.evaluate("() => { goToTab('today'); }")
        pg.wait_for_timeout(400)
        tt = norm(pg.locator("#content").inner_text())
        m = re.search(r"Требует внимания\s+(\d+)", tt, re.I)
        check(f"F2: плитка «Требует внимания» на «Сегодня» = {s['attn']} ({m.group(1) if m else None})", m is not None and int(m.group(1)) == s["attn"])

        # карточка проданной бумаги — клик по строке «Сделано»
        pg.evaluate("() => { goToTab('actions'); }")
        pg.wait_for_selector("#content #act-done", timeout=10000)
        pg.evaluate("() => { document.querySelector('#content #act-done').open = true; }")
        pg.locator('#content #act-done [data-sold="GLRX"]').click()
        pg.wait_for_selector("#card-layer .card-dec", timeout=8000)
        pg.wait_for_timeout(300)
        dec = norm(pg.evaluate("() => [...document.querySelector('#card-layer .card-dec').children].map(x => x.textContent).join(' ')"))
        tiles = norm(pg.evaluate("() => document.querySelector('#card-layer .card-tiles').innerText"))
        tags = norm(pg.evaluate("() => document.querySelector('#card-layer .card-tags').innerText"))
        fold = pg.evaluate("() => { const d = document.querySelector('#card-layer .card-dec details.card-sold-why'); return d ? { open: d.open, sum: d.querySelector('summary').innerText } : null; }")
        check(f"F2 карточка: «Решение» — «Продана 08.10», последнее слово — обзор 28.10 «продать», без «гейт» ({dec[:200]!r})",
              dec.startswith("Решение Продана 08.10 Последнее слово — обзор 28.10: «продать»") and "гейт" not in dec.lower())
        check(f"F2 карточка: нет «Продать … при плане» и инструкции обзора на виду ({dec[:300]!r})", "при плане" not in dec and "Перед любой сделкой" not in dec)
        check(f"F2 карточка: проза обзора свёрнута «подробнее ▾» ({fold})", bool(fold) and not fold["open"] and "подробнее" in fold["sum"])
        check(f"F2 карточка: плиток «Ожидание» и «Потенциал IE» нет ({tiles[:200]!r})", "Ожидание" not in tiles and "Потенциал IE" not in tiles)
        check(f"F2 карточка: метки «проверка перед сделкой» нет ({tags!r})", "проверка перед сделкой" not in tags)
        pg.evaluate("() => { cardStack.length = 0; renderCards(); }")

        # «Акции»: плитка и таблица
        pg.evaluate("() => { goToTab('positions'); }")
        pg.wait_for_timeout(500)
        tt = norm(pg.locator("#content").inner_text())
        a = re.search(r"портфеля · (\d+) бумаг", tt)
        b = re.search(r"(\d+) из (\d+) · в портфеле (\d+), продана (\d+)", tt)
        check(f"F2 «Акции»: число бумаг плитки = «в портфеле N» таблицы, проданная названа ({a and a.group(0)!r}, {b and b.group(0)!r})",
              bool(a and b) and a.group(1) == b.group(3) and b.group(4) == "1" and int(b.group(2)) == int(b.group(3)) + 1)

        # F5: окно «Решения»
        check("F5: gateOf(TMON) и gateOf(XXXXXX) — нет (фонд в текущем снапшоте; ранний снапшот писал stock)",
              pg.evaluate("() => gateOf('TMON') === null && gateOf('XXXXXX') === null && lwCard('TMON').gate.applicable === false"))
        pg.evaluate("() => { state.decFilter = ''; showGateLegendModal(''); }")
        pg.wait_for_timeout(300)
        w = pg.evaluate("""() => ({
          main: [...document.querySelectorAll('#modal-body .dec-list .dec-row')].map(x => x.dataset.key),
          other: [...document.querySelectorAll('#modal-body .dec-nogate .dec-row')].map(x => x.dataset.key),
          head: (document.querySelector('#modal-body .dec-nogate .ui-kicker') || {}).textContent || '',
          tmon: (document.querySelector('#modal-body .dec-nogate .dec-row[data-key=TMON] summary') || {}).innerText || '',
          glrx: (document.querySelector('#modal-body .dec-list .dec-row[data-key=GLRX] summary') || {}).innerText || '',
          chips: [...document.querySelectorAll('#modal-body .dec-filter .ui-seg-btn')].map(b => [b.dataset.decFilter, b.textContent]) })""")
        check(f"F5: TMON и XXXXXX — в группе «Фонды и облигации — решения без закрытия докупки» ({w['other']}, {w['head']!r})",
              "TMON" in w["other"] and "XXXXXX" in w["other"] and "TMON" not in w["main"] and w["head"].startswith("Фонды и облигации — решения без закрытия докупки"))
        tm = norm(w["tmon"])
        check(f"F5: строка фонда — вердикт словом и дата, без статуса гейта ({tm!r})", "гейт" not in tm and "докупка" not in tm and re.search(r"Держать|Докупать|Наблюдать|Сократить|Продать", tm) is not None and "от " in tm)
        check(f"F5: GLRX в акциях — «продана» ({norm(w['glrx'])!r})", "продана" in norm(w["glrx"]) and "гейт" not in norm(w["glrx"]))
        leak = []
        for v, t in w["chips"]:
            if not v:
                continue
            pg.evaluate("(v) => document.querySelector(`#modal-body .dec-filter .ui-seg-btn[data-dec-filter='${v}']`).click()", v)
            pg.wait_for_timeout(150)
            ks = pg.evaluate("() => [...document.querySelectorAll('#modal-body .dec-row')].map(x => x.dataset.key)")
            if "TMON" in ks or "XXXXXX" in ks:
                leak.append(t)
        check(f"F5: ни в одном фильтре статуса фондов нет ({[t for _, t in w['chips']]}; утечки {leak})", not leak and len(w["chips"]) > 1)
        pg.evaluate("() => { state.decFilter = ''; closeModal(); }")
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # F9: результат плитки и таблицы
        for quotes in (False, True):
            browser, pg, errs = open_page(p, quotes=quotes)
            pg.evaluate("() => { const pbt = buildPositionByTicker(); openCard(pbt.YDEX, [pbt.YDEX]); }")
            pg.wait_for_selector("#card-layer .card-tiles", timeout=8000)
            pg.wait_for_timeout(300)
            r = pg.evaluate("""() => { const t = [...document.querySelectorAll('#card-layer .card-tile')].find(x => /Моя доходность/.test(x.textContent));
              const kv = [...document.querySelectorAll('#card-layer .ui-kv')].find(x => x.firstChild && x.firstChild.textContent === 'Результат');
              return { tile: t ? t.textContent : '', res: kv ? kv.lastChild.textContent : '' }; }""")
            tile, res = norm(r["tile"]), norm(r["res"])
            if quotes:
                check(f"F9 живые цены: плитка «результат 1 000 ₽ по снапшоту 08.10» ({tile!r})", "результат 1 000 ₽ по снапшоту 08.10" in tile)
                check(f"F9 живые цены: таблица «Результат» — по цене MOEX, другое число ({res!r})", res and res != "1 000 ₽")
            else:
                check(f"F9 без живых цен: подписи «по снапшоту» нет, числа совпадают ({tile!r}, {res!r})", "по снапшоту" not in tile and "результат 1 000 ₽" in tile and res == "1 000 ₽")
            check(f"ошибок страницы нет ({errs[:2]})", not errs)
            browser.close()

        # R29: погашенная облигация — карточка, таблица «Облигации», «Действия», «Выплаты», «Сегодня»
        build_bond()
        browser, pg, errs = open_page(p)
        pg.evaluate("(d) => { state.todayOverride = d; dsInvalidate(); }", "2026-11-03")
        k = "RU000A107795"
        cd = pg.evaluate("(k) => { const c = lwCard(k); return { held: c.held, kind: c.left_kind, at: c.left_at, dv: divestedOf(k), gate: c.gate.applicable }; }", k)
        check(f"R29: модуль (б) — облигация ушла в день погашения или позже: held false, redeemed, без гейта ({cd})",
              cd["held"] is False and cd["kind"] == "redeemed" and cd["dv"] == {"sold": "2026-11-03", "kind": "redeemed"} and cd["gate"] is False)
        pg.evaluate("() => { cardStack.length = 0; renderCards(); goToTab('actions'); }")
        pg.wait_for_selector("#content #act-head", timeout=10000)
        b = pg.evaluate("() => { const B = actionBlocks(); return { check: B.check.items.map(x => x.it.ticker), sold: B.done.sold.map(x => x.ticker), wait: B.wait.notes.map(x => x.it.ticker) }; }")
        check(f"R29 «Действия»: пункты проверки погашенной — не в «Проверить», строка в «Сделано» ({b})", k not in b["check"] and k in b["sold"] and k not in b["wait"])
        pg.evaluate("() => { document.querySelector('#content #act-done').open = true; }")
        sd_ = norm(pg.locator(f'#content #act-done [data-sold="{k}"]').inner_text())
        check(f"R29 «Сделано»: «погашена 03.11 — обзор 28.10 исполнен» ({sd_!r})", "погашена 03.11 — обзор 28.10 исполнен" in sd_)
        pg.locator(f'#content #act-done [data-sold="{k}"]').click()
        pg.wait_for_selector("#card-layer .card-dec", timeout=8000)
        pg.wait_for_timeout(300)
        dec = norm(pg.evaluate("() => document.querySelector('#card-layer .card-dec').textContent"))
        tiles = norm(pg.evaluate("() => document.querySelector('#card-layer .card-tiles').textContent"))
        kv = norm(pg.evaluate("() => (document.querySelector('#card-layer .card-kv') || {}).textContent || ''"))
        check(f"R29 карточка: «Решение» — «Погашена 03.11» ({dec[:120]!r})", dec.startswith("Решение") and "Погашена 03.11" in dec and "Держать до погашения" not in dec.split("Последнее слово")[0])
        check(f"R29 карточка: без доходности к погашению, дюрации и «При покупке», «Моя доходность» есть ({tiles[:160]!r} | {kv[:160]!r})",
              "Доходность к погашению" not in tiles and "При покупке" not in tiles and "Моя доходность" in tiles
              and "Дюрация" not in kv and "Доля" not in kv and "YTM" not in kv)
        check(f"4.2.4 карточка: плитка «Погашена 03.11» вместо «Погашение»/срока/купона ({tiles[:160]!r})",
              "Погашена 03.11" in tiles and "Погашение" not in tiles and "до погашения" not in tiles and "дюр." not in tiles)
        al = pg.evaluate("(k) => { const a = _bondLinkAliases(buildPositionByTicker(), new Set()); return Object.keys(a).length ? Object.entries(a).filter(([t]) => /\\d/.test(t)).slice(0, 40).every(([t, f]) => { const e = f(); return e && e._kind === 'bond'; }) : false; }", k)
        check("4.2.4 слой ссылок отчёта облигаций: у погашенной и обычных бумаг ISIN/названия дают запись-облигацию", al is True)
        pg.evaluate("() => { cardStack.length = 0; renderCards(); goToTab('bonds'); }")
        pg.wait_for_timeout(500)
        bt = norm(pg.locator("#content").inner_text())
        m = re.search(r"(\d+) из (\d+) · в портфеле (\d+), погашено (\d+)", bt)
        check(f"R29 «Облигации»: подзаголовок «в портфеле N, погашено 1», строка остаётся ({m and m.group(0)!r})",
              bool(m) and m.group(4) == "1" and int(m.group(2)) == int(m.group(3)) + 1)
        check("R29 «Облигации»: фильтр «Нет в портфеле»", "Нет в портфеле" in bt)
        pay = pg.evaluate("() => { const port = currentPort(); const r = payoutsCalendarFor(port.bond_cashflow_calendar, port, 'all'); return r.by_month['2026-11']; }")
        check(f"R29 «Выплаты»: купон погашенной бумаги после ухода не считается ({pay})", pay and pay["coupons_rub"] == 500.0)
        pg.evaluate("() => { goToTab('today'); }")
        pg.wait_for_timeout(400)
        up = norm(pg.locator("#content").inner_text())
        check("R29 «Сегодня»: выплат и сроков погашенной бумаги нет", "ЛаймЗайм04" not in up)
        check(f"ошибок страницы нет (погашенная) ({errs[:2]})", not errs)
        browser.close()

        # 4.2.4: «ИИС-3» и «Фонды» — ушедшая бумага строкой «Нет в портфеле», не как живая
        build_iis()
        browser, pg, errs = open_page(p)
        pg.evaluate("(d) => { state.todayOverride = d; dsInvalidate(); }", "2026-11-03")
        dv = pg.evaluate("() => ({ b: divestedOf('RU000A103MX5'), t: divestedOf('TPAY'), s: divestedOf('SBGB') })")
        check(f"4.2.4 модуль (б): ОФЗ 52004 погашена, TPAY и SBGB проданы ({dv})",
              (dv["b"] or {}).get("kind") == "redeemed" and (dv["t"] or {}).get("kind") == "sold" and (dv["s"] or {}).get("kind") == "sold")
        pg.evaluate("() => { goToTab('iis'); }")
        pg.wait_for_timeout(500)
        ii = pg.evaluate("""() => { const t = document.querySelector('#iis-table'); const rows = [...t.querySelectorAll('tbody tr')];
          return { gone: rows.filter(r => r.dataset.gone).map(r => [r.dataset.gone, r.innerText]), sbgb: rows.filter(r => /SBGB/.test(r.innerText)).length,
                   head: t.closest('.ui-card').querySelector('.ui-head').innerText, n: rows.length }; }""")
        gone = dict(ii["gone"])
        check(f"4.2.4 «ИИС-3»: погашенная ОФЗ 52004 и проданный SBGB — строки «Нет в портфеле» с датой ухода ({ii['gone']})",
              set(gone) == {"RU000A103MX5", "SBGB"} and "погашена 03.11" in norm(gone["RU000A103MX5"]) and "продана 03.11" in norm(gone["SBGB"]))
        check(f"4.2.4 «ИИС-3»: SBGB из перенесённого расчёта не строкой живой бумаги (одна строка, без стоимости) ({ii['sbgb']}, {norm(gone.get('SBGB', ''))!r})",
              ii["sbgb"] == 1 and "150" not in norm(gone.get("SBGB", "")))
        m = re.search(r"(\d+) из (\d+) · в портфеле (\d+), погашено/продано (\d+)", norm(ii["head"]))
        check(f"4.2.4 «ИИС-3»: подзаголовок «в портфеле N, погашено/продано 2» и фильтр «Нет в портфеле» ({norm(ii['head'])!r})",
              bool(m) and m.group(4) == "2" and int(m.group(2)) == int(m.group(3)) + 2 and "Нет в портфеле" in ii["head"])
        pg.locator("#content .ui-card:has(#iis-table) .filters input[type=checkbox]").check()
        pg.wait_for_timeout(300)
        only = pg.evaluate("() => [...document.querySelectorAll('#iis-table tbody tr')].map(r => r.dataset.gone || null)")
        check(f"4.2.4 «ИИС-3»: фильтр «Нет в портфеле» оставляет только ушедшие ({only})", sorted(only) == ["RU000A103MX5", "SBGB"])
        pg.evaluate("() => { state.filterStates.iis.goneOnly = false; goToTab('funds'); }")
        pg.wait_for_timeout(500)
        fu = pg.evaluate("""() => { const t = document.querySelector('#funds-table'); const rows = [...t.querySelectorAll('tbody tr')];
          return { gone: rows.filter(r => r.dataset.gone).map(r => [r.dataset.gone, r.innerText]), head: t.closest('.ui-card').innerText.split('\\n').slice(0, 6).join(' '),
                   flt: t.closest('.ui-card').innerText.includes('Нет в портфеле') }; }""")
        fg = dict(fu["gone"])
        check(f"4.2.4 «Фонды»: проданный TPAY — строка «продана 03.11» без стоимости; SBGB (только ИИС-3) — не здесь ({fu['gone']})",
              set(fg) == {"TPAY"} and "продана 03.11" in norm(fg["TPAY"]))
        m = re.search(r"(\d+) из (\d+) · в портфеле (\d+), продано (\d+)", norm(fu["head"]))
        check(f"4.2.4 «Фонды»: подзаголовок «в портфеле N, продано 1» и фильтр «Нет в портфеле» ({norm(fu['head'])[:200]!r})",
              bool(m) and m.group(4) == "1" and int(m.group(2)) == int(m.group(3)) + 1 and fu["flt"])
        pg.evaluate("() => { state.filterStates.funds.goneOnly = true; renderTabContent(); }")
        pg.wait_for_timeout(300)
        only = pg.evaluate("() => [...document.querySelectorAll('#funds-table tbody tr')].map(r => r.dataset.gone || null)")
        check(f"4.2.4 «Фонды»: фильтр «Нет в портфеле» — только TPAY ({only})", only == ["TPAY"])
        pg.locator('#funds-table tbody tr[data-gone="TPAY"]').click()
        pg.wait_for_selector("#card-layer .card-tiles", timeout=8000)
        ct = norm(pg.evaluate("() => document.querySelector('#card-layer .card-tiles').textContent"))
        check(f"4.2.4 «Фонды»: клик по ушедшему — карточка «Продана 03.11» ({ct[:120]!r})", "Продана 03.11" in ct)
        pg.evaluate("() => { cardStack.length = 0; renderCards(); state.filterStates.funds.goneOnly = false; goToTab('bonds'); }")
        pg.wait_for_timeout(500)
        bt = norm(pg.locator("#content").inner_text())
        check("4.2.4 «Облигации»: погашенная бумага ИИС-3 — не в таблице основного счёта (её строка на «ИИС-3»)", "погашено" not in bt and "ОФЗ 52004" not in bt)
        check(f"ошибок страницы нет (ИИС-3 / Фонды) ({errs[:2]})", not errs)
        browser.close()


main()
shutil.rmtree(FIX, ignore_errors=True)
print(f"Итого: {passed} из {passed + failed} прошли" if failed == 0 else f"Итого: {passed} из {passed + failed} прошли (падений: {failed})")
sys.exit(1 if failed else 0)
