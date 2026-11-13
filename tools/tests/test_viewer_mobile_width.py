#!/usr/bin/env python3
"""Вьюер на телефоне (390 px, 29.10, iPhone): ни одна вкладка не шире экрана — Chromium и WebKit (движок Safari).

Дефект 29.10: «Динамика» прокручивалась вправо на ~240 px, полоса вкладок и карточки уезжали влево, справа пустой фон.
Виновник — скрытая подсказка значка (i) у правого края заголовка раздела: `.ui-info-pop` был visibility:hidden, но оставался
в раскладке (position:absolute, left -8px от значка, ширина до 360 px) и раздвигал прокручиваемую область страницы.
Исправление в источнике (ui-kit.css): скрытая подсказка — display:none (переход display с allow-discrete сохраняет задержки показа/скрытия).

Контракты (фикстура viewer-live, как у test_viewer_plan_now):
  1. Обход всех вкладок вьюера (buildTabs() + «Загрузки») на 390: document.documentElement.scrollWidth ≤ innerWidth + 1,
     в обоих движках; список вкладок не пуст и включает «Динамику».
  2. Синтетика: значок (i) у правого края строки (длинное пояснение, абзацы) — страница не шире экрана при скрытой подсказке;
     по клику подсказка видна, целиком внутри окна (uiInfoPlace сдвигает), закрывается кликом мимо; при наведении (hover-устройство) — видна.
  3. Ошибок страницы нет.
Требует playwright (+chromium, +webkit — нет движка: он пропускается); без playwright — пропуск.
Запуск: python3 tools/tests/test_viewer_mobile_width.py
"""
import json
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
    print("viewer_mobile_width: пропуск — нет playwright")
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

OFFENDERS = """() => { const iw = innerWidth, out = [];
  for (const e of document.querySelectorAll('body *')) { const r = e.getBoundingClientRect(); if (r.width && r.right > iw + 1) out.push(e.tagName.toLowerCase() + '.' + String(e.className).slice(0, 40) + ' r=' + Math.round(r.right)); }
  return out.slice(0, 6); }"""
INFO = """() => { const host = document.createElement('div'); host.id = 'info-host';
  host.style.cssText = 'text-align:right;padding:8px 16px;background:var(--bg)';
  host.innerHTML = '<span class="ui-info-glue">Заголовок ' + uiInfoHTML('<p><b>Первый абзац</b> с длинным пояснением, которое занимает несколько строк на узком экране.</p><p>Второй абзац.</p>', { html: true }) + '</span>';
  document.querySelector('main, #content').prepend(host); }"""


def main():
    engines = 0
    with sync_playwright() as p:
        for eng_name in ("chromium", "webkit"):
            try:
                browser = getattr(p, eng_name).launch()
            except Exception as e:
                print(f"viewer_mobile_width: пропуск движка {eng_name} — {str(e).splitlines()[0][:70]}")
                continue
            engines += 1
            ctx = browser.new_context(service_workers="block", viewport={"width": 390, "height": 844}, has_touch=False)
            pg = ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, body="{}"))
            pg.goto(URL)
            pg.wait_for_selector("#tabs .ui-tab", timeout=30000)
            pg.wait_for_function("() => state.data && state.data.portfolioLatest", timeout=30000)
            pg.wait_for_timeout(1500)
            tabs = pg.evaluate("() => buildTabs().map(t => t.id)")
            check(f"{eng_name}: вкладки найдены, «Динамика» среди них ({tabs})", len(tabs) >= 8 and "history" in tabs)
            for tab in tabs + ["pfbuild"]:
                pg.evaluate("k => goToTab(k)", tab)
                pg.wait_for_timeout(900)
                sw = pg.evaluate("document.documentElement.scrollWidth")
                check(f"{eng_name} 390: вкладка «{tab}» не шире экрана (scrollWidth {sw}) {pg.evaluate(OFFENDERS) if sw > 391 else ''}", sw <= 391)
            # синтетика: (i) у правого края
            pg.evaluate("k => goToTab(k)", "today")
            pg.wait_for_timeout(600)
            pg.evaluate(INFO)
            pg.wait_for_timeout(200)
            check(f"{eng_name}: (i) у правого края, подсказка скрыта — страница не шире экрана",
                  pg.evaluate("document.documentElement.scrollWidth") <= 391)
            check(f"{eng_name}: скрытая подсказка не занимает места (display none)",
                  pg.evaluate("getComputedStyle(document.querySelector('#info-host .ui-info-pop')).display") == "none")
            bb = pg.locator("#info-host .ui-info-btn").bounding_box()
            pg.mouse.move(bb["x"] + 8, bb["y"] + 8)   # наведение: сдвиг считается заранее, страница не растягивается ни на миг и после
            pg.wait_for_timeout(600)
            hv = pg.evaluate("""() => { const b = document.querySelector('#info-host .ui-info-pop').getBoundingClientRect(), cs = getComputedStyle(document.querySelector('#info-host .ui-info-pop'));
              return { l: b.left, r: b.right, vis: cs.visibility, sw: document.documentElement.scrollWidth }; }""")
            check(f"{eng_name}: наведение — подсказка внутри окна, страница не шире экрана ({hv})", hv["l"] >= 11 and hv["r"] <= 379 and hv["sw"] <= 391)
            pg.click("#info-host .ui-info-btn")
            pg.wait_for_timeout(500)
            r = pg.evaluate("""() => { const b = document.querySelector('#info-host .ui-info-pop').getBoundingClientRect(); const cs = getComputedStyle(document.querySelector('#info-host .ui-info-pop'));
              return { l: b.left, r: b.right, w: b.width, vis: cs.visibility, op: +cs.opacity, disp: cs.display, sw: document.documentElement.scrollWidth }; }""")
            check(f"{eng_name}: по клику подсказка видна и целиком в окне ({r})",
                  r["vis"] == "visible" and r["op"] > 0.9 and r["disp"] == "block" and r["l"] >= 11 and r["r"] <= 390 - 11 and r["sw"] <= 391)
            pg.mouse.click(5, 600)
            pg.wait_for_timeout(900)
            check(f"{eng_name}: клик мимо закрывает подсказку",
                  pg.evaluate("getComputedStyle(document.querySelector('#info-host .ui-info-pop')).display") == "none")
            check(f"{eng_name}: ошибок страницы нет {errs[:2]}", not errs)
            ctx.close()
            browser.close()
    if not engines:
        print("viewer_mobile_width: пропуск — нет ни одного движка")
        return
    srv.shutdown()


main()
print(f"viewer_mobile_width: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
