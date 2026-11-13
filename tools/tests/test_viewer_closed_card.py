#!/usr/bin/env python3
"""Вьюер 3.119.0: карточка проданной бумаги — доходность и из чего она складывается — настоящий Chromium.

Владелец: «продал GLRX, хочу видеть доходность и из чего она складывается»; раньше в плитке «Моя доходность» было «—».
Запись о закрытой бумаге бывает в двух формах (читатель instrXirr): per_instrument_xirr[T] с closed: true и отдельный блок per_instrument_xirr_closed[T].
Контракты (фикстуры viewer-live; закрытая запись подставляется в снапшот в памяти для UPRO — бумага без позиции, строка кликабельна в «Все бумаги»):
  1. Обе формы: клик по строке «Все бумаги» открывает карточку; плитка «Моя доходность» = XIRR записи, подпись «итог +N ₽ · продана дд.мм»;
     вместо «Вес: факт» — «продана дд.мм».
  2. Подвкладка «Доходность»: блок «Итог по бумаге» — куплено, продано, дивиденды/купоны/амортизация, корректировки (только ≠ 0), итог, XIRR, «Держал с … по … (N дней)».
  3. Корректировки равны 0 — строки нет. Бумага без записи (WUSH) — плитка «—», блока нет, ошибок нет.
  4. Те же числа на 390.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_closed_card.py
"""
import json
import re
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import quote as _q, unquote as _unq, urlparse as _up

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import serve  # noqa: E402  (стенд — _pages_stand, keep-alive)
FIX = REPO / "tools/tests/fixtures/viewer-live"
passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("viewer_plan_now: пропуск — нет playwright")
    sys.exit(0)

sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as hub_api  # noqa: E402


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


REC = {"xirr": 0.2337, "pnl_rub": 12345.6, "buy_total_rub": 100000.0, "sell_total_rub": 105000.0, "dividends_rub": 7000.0, "coupons_rub": 0.0,
       "amortization_rub": 0.0, "corr_buy_rub": -600.0, "corr_sell_rub": 0.0, "first_trade_date": "2025-03-10", "last_trade_date": "2026-10-12",
       "close_date": "2026-10-12", "holding_days": 581, "qty_now": 0, "market_value_rub": 0, "price_source": "closed"}


def norm(t):
    return re.sub(r"[\s\u00a0\u202f]+", " ", t or "").strip()


def main():
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            print(f"viewer_closed_card: пропуск — {str(e).splitlines()[0][:80]}")
            return
        for width in (1400, 390):
            for form in ("flag", "block"):
                run(browser, width, form)


def run(browser, width, form):
    tag = f"[{width} {form}] "
    ctx = browser.new_context(service_workers="block", viewport={"width": width, "height": 1000})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "502" not in m.text and "404" not in m.text else None)
    pg.route("**/api/pv/**", lambda r: r.fulfill(status=502, body="{}"))
    pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, body="{}"))
    pg.goto(URL)
    pg.wait_for_function("() => state.data && state.data.portfolioLatest", timeout=20000)
    pg.wait_for_timeout(1500)
    t, none = "UPRO", "WUSH"
    pg.evaluate("""([t, form, rec]) => { const port = currentPort(); port.per_instrument_xirr = port.per_instrument_xirr || {};
      if (form === 'flag') port.per_instrument_xirr[t] = { ...rec, closed: true };
      else port.per_instrument_xirr_closed = { [t]: rec };
      state.ieView = 'watch'; state.rebalMode = 'all'; goToTab('ie-model'); renderTabContent(); }""", [t, form, REC])
    pg.wait_for_selector(".rb-v-all tbody tr", timeout=10000)

    def open_card(tk):
        pg.evaluate("(t) => { cardStack.length = 0; renderCards(); const r = [...document.querySelectorAll('.rb-v-all tbody tr')].find(x => x.innerText.split(/\\s+/).includes(t)); r.click(); }", tk)
        pg.wait_for_selector(".card-win", timeout=10000)
        pg.wait_for_timeout(300)

    def sub(v):
        pg.evaluate("(v) => document.querySelector('.card-win [data-act=card-sub][data-v=' + v + ']').click()", v)
        pg.wait_for_timeout(300)
    open_card(t)
    tiles = norm(pg.evaluate("() => document.querySelector('.card-win .card-tiles').textContent"))
    check(f"{tag}плитка «Моя доходность»: +23,4 % ({tiles[:200]!r})", "Моя доходность" in tiles and re.search(r"23[.,]4", tiles) is not None)
    check(f"{tag}подпись «итог +12 346 ₽ · продана 12.10» ({tiles[:240]!r})", "итог +12 346 ₽ · продана 12.10" in tiles)
    check(f"{tag}вместо «Вес: факт» — «продана 12.10»", "Вес: факт" not in tiles and "продана 12.10" in tiles)
    sub("ret")
    blk = norm(pg.evaluate("() => (document.querySelector('.card-win .card-closed') || {textContent: ''}).textContent"))
    check(f"{tag}блок «Итог по бумаге» есть ({blk[:80]!r})", blk.lower().startswith("итог по бумаге"))
    for need in ("Куплено на100 000 ₽", "Продано на105 000 ₽", "Дивиденды, купоны, амортизация7 000 ₽", "Корректировки−600 ₽", "Итог+12 346 ₽",
                 "Держал", "с 10.03.2025 по 12.10.2026 (581 день)"):
        check(f"{tag}в блоке: {need!r}", need in blk)
    check(f"{tag}в блоке XIRR +23,4 %", re.search(r"XIRR, % годовых\+23[.,]4", blk) is not None)
    # корректировки 0 — строки нет
    pg.evaluate("""([t, form]) => { const port = currentPort(); const r = form === 'flag' ? port.per_instrument_xirr[t] : port.per_instrument_xirr_closed[t];
      r.corr_buy_rub = 0; r.corr_sell_rub = 0; r.dividends_rub = 0; renderCards(); }""", [t, form])
    pg.wait_for_timeout(300)
    sub("ret")
    blk0 = norm(pg.evaluate("() => (document.querySelector('.card-win .card-closed') || {textContent: ''}).textContent"))
    check(f"{tag}корректировки и дивиденды = 0 — строк нет ({blk0[:120]!r})", blk0.lower().startswith("итог по бумаге") and "Корректировки" not in blk0 and "Дивиденды" not in blk0)
    # бумага без записи
    pg.evaluate("() => { cardStack.length = 0; renderCards(); }")
    open_card(none)
    tl = norm(pg.evaluate("() => document.querySelector('.card-win .card-tiles').textContent"))
    sub("ret")
    has = pg.evaluate("() => !!document.querySelector('.card-win .card-closed')")
    check(f"{tag}без записи: «Моя доходность» «—», блока нет ({tl[:120]!r})", re.search(r"Моя доходность\s*—", tl) is not None and not has)
    check(f"{tag}ошибок страницы нет ({errs[:2]})", not errs)
    ctx.close()


main()
srv.shutdown()
print(f"Итого: {passed} из {passed + failed}")
sys.exit(1 if failed else 0)
