#!/usr/bin/env python3
"""Вьюер 3.122.1: рамка у строк «Изменений» после щелчка мышью и Esc в окне отчёта.

Решение владельца 30.10: у строк «Изменений» после щелчка и закрытия окна остаётся зелёная рамка :focus-visible;
Esc в окне отчёта заодно выводит Mac из полноэкранного режима.
Причина рамки: щелчок мышью оставлял фокус на строке (tabindex=0); окно фокус не забирает, и первое же нажатие клавиши
(Esc закрытия) включало :focus-visible на строке. Причина выхода из полноэкранного режима: Esc окна документа без preventDefault.
Контракты (Chromium и WebKit, 1400):
  1. Щелчок мышью по строке-ссылке «Изменений»: строка не в фокусе, окно открылось; Esc закрыл окно — рамки нет (ни одного :focus-visible-элемента-строки).
  2. То же, когда окно закрыто щелчком по крестику и щелчком мимо.
  3. Клавиатура: Tab доходит до строки-ссылки, рамка видна; Enter открывает окно, Esc закрывает — рамка на строке остаётся.
  4. Esc в окне документа (список «Отчёты») — defaultPrevented === true у события, окно закрыто; Esc в карточке — то же.
  5. Ошибок страницы нет.
Требует playwright + chromium (webkit — если установлен); без них — пропуск. Запуск: python3 tools/tests/test_viewer_focus_esc.py
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import quote as _q, unquote as _unq, urlparse as _up

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import serve  # noqa: E402  (стенд — _pages_stand, keep-alive)
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
    import yaml
except ImportError:
    print("viewer_diff_periods: пропуск — нет playwright/yaml")
    sys.exit(0)

sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as hub_api  # noqa: E402

FIX = Path(tempfile.mkdtemp(prefix="diffper-"))
BOND = "RU000A106E90"


def local_utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


SOLD, OLDBOND, NODATA = "SOLDX", "RU000A0ZZ001", "NODATAX"
SOLD_REC = {"xirr": 0.2337, "pnl_rub": 12345.6, "buy_total_rub": 100000.0, "sell_total_rub": 105000.0, "dividends_rub": 7000.0, "coupons_rub": 0.0,
            "amortization_rub": 0.0, "corr_buy_rub": -600.0, "corr_sell_rub": 0.0, "first_trade_date": "2025-03-10", "last_trade_date": "2026-10-12",
            "close_date": "2026-10-12", "holding_days": 581, "qty_now": 0, "market_value_rub": 0, "price_source": "closed"}
JOURNAL = [
    {"ts": local_utc(2026, 10, 29, 11, 0), "who": "site", "path": f"stocks.{SOLD}.plan_pct", "was": 1.0, "now": 0.0, "reason": None},
    {"ts": local_utc(2026, 10, 29, 11, 5), "who": "site", "path": f"stocks.{NODATA}.plan_pct", "was": 1.0, "now": 0.5, "reason": None},
    {"ts": local_utc(2026, 10, 27, 9, 0), "who": "site", "path": "stocks.GMKN.plan_pct", "was": 3.0, "now": 2.0, "reason": None},
    {"ts": local_utc(2026, 10, 28, 11, 0), "who": "site", "path": "stocks.LSNGP.plan_pct", "was": 2.0, "now": 2.5, "reason": None},
    {"ts": local_utc(2026, 10, 28, 13, 0), "who": "site", "path": "stocks.LSNGP.plan_pct", "was": 2.5, "now": 3.0, "reason": None},
    {"ts": local_utc(2026, 10, 29, 10, 0), "who": "site", "path": "stocks.GMKN.plan_pct", "was": 2.0, "now": 3.0, "reason": None},
    {"ts": local_utc(2026, 10, 29, 10, 5), "who": "site", "path": "stocks.GMKN.user_status", "was": None, "now": "DONE", "reason": None},
]


def build():
    shutil.rmtree(FIX, ignore_errors=True)
    shutil.copytree(REPO / "tools/tests/fixtures/viewer-live", FIX)
    for part in ("bond-actions", "superseded", "conditions-pack", "diff-periods"):
        shutil.copytree(REPO / "tools/tests/fixtures" / part, FIX, dirs_exist_ok=True)
    wr = FIX / "Portfolio/weekly-reviews"
    for name, (mo, d, h, mi) in {"stock-2026-10-16": (10, 16, 14, 15), "stock-2026-10-26": (10, 26, 15, 9), "stock-2026-10-28": (10, 28, 12, 8),
                                 "bond-2026-10-16": (10, 16, 14, 1), "bond-2026-10-28": (10, 28, 12, 14)}.items():
        ts = datetime(2026, mo, d, h, mi).timestamp()
        os.utime(wr / f"weekly-review-{name}.md", (ts, ts))
    cp = FIX / "Portfolio/conditions.yaml"   # условие по выпуску облигации (conditions@2): создано 20.10, закрыто владельцем 29.10
    c = yaml.safe_load(cp.read_text(encoding="utf-8"))
    c["conditions"].append({"id": "bond-test-cond", "version": 1, "key": BOND, "kind": "review", "trigger": {"type": "date", "value": "2026-11-30"},
                            "event_text": "оферта по выпуску", "while_pending": {"verdict": "HOLD"}, "on_trigger": {"action": "run_analysis", "text": "разобрать"},
                            "on_expiry": None, "not_before": None, "valid_until": None, "source": {"kind": "owner", "doc": None},
                            "created_at": "2026-10-20T00:00:00+03:00", "created_by": "owner", "withdrawn": None, "superseded_by": None, "note": "тест"})
    cp.write_text(yaml.safe_dump(c, allow_unicode=True, sort_keys=False), encoding="utf-8")
    sp = FIX / "Portfolio/conditions-state.json"
    st = json.loads(sp.read_text(encoding="utf-8"))
    st["events"].append({"condition_id": "bond-test-cond", "version": 1, "event": "done", "at": "2026-10-29T00:00:00+03:00", "by": "owner", "data": {}})
    sp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


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

def open_diff(p, w=1400, h=1000, journal="ok", via="pair", engine="chromium"):
    browser = getattr(p, engine).launch()
    ctx = browser.new_context(service_workers="block", viewport={"width": w, "height": h})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "502" not in m.text and "404" not in m.text else None)
    pg.route("**/api/pv/plan*", lambda r: r.fulfill(status=502, body="{}"))
    pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, body="{}"))
    if journal == "ok":
        pg.route("**/api/pv/plan/journal*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"entries": JOURNAL})))
    pg.goto(URL)
    pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
    pg.wait_for_function("() => state.data && state.data.portfolioLatest && state.data.weeklyReviewCurrent && state.data.weeklyBondReviewCurrent && state.data.decisions.length && state.data.conditions", timeout=20000)
    if via == "click":   # 3.120.1: реальная вкладка, без каких-либо действий — открыт «→ сейчас»
        pg.locator("#tabs .ui-tab", has_text="Изменения").first.click()
    else:   # ссылка с датой пары, как из push
        pg.evaluate("() => { state.diffDate = diffPeriods(diffPick())[1].id; goToTab('diff'); }")
    pg.wait_for_selector(".diff-bar .ui-select-t", timeout=10000)
    pg.wait_for_selector(".dif-between", timeout=10000)
    pg.wait_for_timeout(500)   # журнал плана и перерисовка
    return browser, pg, errs




ROW = ".dif-between .tl.tl-link"
OPEN = "() => !!document.querySelector('#card-layer .ui-modal') || (!!document.querySelector('#modal-overlay') && !document.querySelector('#modal-overlay').hasAttribute('hidden'))"
RING = "() => { const a = document.activeElement; return !!(a && a.matches && a.matches('.tl.pick') && a.matches(':focus-visible')); }"
ONROW = "() => { const a = document.activeElement; return !!(a && a.closest && a.closest('.tl.pick')); }"
SPY = "() => { window.__esc = null; window.addEventListener('keydown', (e) => { if (e.key === 'Escape') window.__esc = e; }, true); }"


def settle(pg, ms=500):
    pg.wait_for_timeout(ms)


def closed(pg):
    return not pg.evaluate(OPEN)


def run(p, engine):
    tag = f"[{engine} 1400] "
    browser, pg, errs = open_diff(p, 1400, 1000, via="click", engine=engine)
    pg.evaluate(SPY)
    rows = pg.locator(ROW)
    check(f"{tag}в «Изменениях» есть строки-ссылки ({rows.count()})", rows.count() > 0)
    if not rows.count():
        browser.close(); return
    # 1. мышь → Esc
    rows.first.click(); settle(pg)
    check(f"{tag}щелчок открыл окно", pg.evaluate(OPEN))
    check(f"{tag}после щелчка строка не в фокусе", not pg.evaluate(ONROW))
    pg.keyboard.press("Escape"); settle(pg)
    check(f"{tag}Esc закрыл окно", closed(pg))
    check(f"{tag}после Esc рамки на строке нет", not pg.evaluate(RING) and not pg.evaluate(ONROW))
    check(f"{tag}Esc окна: preventDefault (не выводит из полноэкранного режима)", pg.evaluate("() => !!(window.__esc && window.__esc.defaultPrevented)"))
    # 2. мышь → крестик; мышь → мимо
    rows.first.click(); settle(pg)
    btn = pg.locator("#card-layer .ui-modal [data-act=card-close], #modal-close").last
    if btn.count() and btn.is_visible():
        btn.click(); settle(pg)
    check(f"{tag}крестик закрыл окно, рамки нет", closed(pg) and not pg.evaluate(RING))
    pg.keyboard.press("Escape"); settle(pg, 200)
    check(f"{tag}затем любая клавиша — рамки нет", not pg.evaluate(RING))
    rows.first.click(); settle(pg)
    pg.mouse.click(4, 600); settle(pg)
    if not closed(pg):
        pg.keyboard.press("Escape"); settle(pg)
    check(f"{tag}после щелчка мимо и клавиши рамки нет", not pg.evaluate(RING))
    # без закрытия окна: ещё одна строка кликается, рамки нет
    rows.nth(min(1, rows.count() - 1)).click(); settle(pg)
    check(f"{tag}щелчок без закрытия: рамки нет", not pg.evaluate(RING))
    pg.keyboard.press("Escape"); settle(pg)
    while not closed(pg):
        pg.keyboard.press("Escape"); settle(pg, 300)
    # 3. клавиатура: Tab до строки
    pg.evaluate("() => { const r = document.querySelector('.dif-between .tl.tl-link'); const prev = r.previousElementSibling || r.parentElement; document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0); }")
    got = False
    pg.evaluate("() => document.body.focus()")
    for _ in range(80):
        pg.keyboard.press("Tab")
        if pg.evaluate("() => { const a = document.activeElement; return !!(a && a.classList && a.classList.contains('tl-link')); }"):
            got = True
            break
    check(f"{tag}Tab доходит до строки-ссылки", got)
    if got:
        check(f"{tag}при Tab рамка видна", pg.evaluate(RING))
        pg.keyboard.press("Enter"); settle(pg)
        check(f"{tag}Enter открыл окно", pg.evaluate(OPEN))
        pg.keyboard.press("Escape"); settle(pg)
        check(f"{tag}Esc закрыл, рамка на строке осталась (клавиатура)", closed(pg) and pg.evaluate(RING))
    # 4. Esc в окне документа и в карточке
    pg.evaluate("() => { document.activeElement && document.activeElement.blur(); }")
    pg.click("#btn-reports"); settle(pg)
    check(f"{tag}окно «Отчёты» открыто", pg.evaluate(OPEN))
    pg.evaluate("() => { window.__esc = null; }")
    pg.keyboard.press("Escape"); settle(pg)
    check(f"{tag}Esc в окне документа: окно закрыто и defaultPrevented", closed(pg) and pg.evaluate("() => !!(window.__esc && window.__esc.defaultPrevented)"))
    pg.evaluate("() => { window.__esc = null; }")
    rows.first.click(); settle(pg)
    pg.keyboard.press("Escape"); settle(pg)
    check(f"{tag}Esc у окна из «Изменений»: defaultPrevented", pg.evaluate("() => !!(window.__esc && window.__esc.defaultPrevented)"))
    check(f"{tag}ошибок страницы нет ({errs[:2]})", not errs)
    browser.close()


def main():
    with sync_playwright() as p:
        engines = []
        for eng in ("chromium", "webkit"):
            try:
                getattr(p, eng).launch().close()
                engines.append(eng)
            except Exception as e:
                print(f"viewer_focus_esc: {eng} недоступен — {str(e).splitlines()[0][:80]}")
        if "chromium" not in engines:
            print("viewer_focus_esc: пропуск — нет chromium")
            return
        build()
        for eng in engines:
            run(p, eng)
    print(f"Итого: {passed} из {passed + failed}")
    sys.exit(1 if failed else 0)


main()
