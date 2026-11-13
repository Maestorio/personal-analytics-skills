#!/usr/bin/env python3
"""Вьюер 3.117.0: мелкие правки на телефоне и подпись «горизонт прошёл» — настоящий Chromium (и WebKit для касания), реальные клики.

Дефекты (скриншоты владельца с iPhone, 29.10):
  1. «Источники» (Предложения на аудит): имена тем рвались по слогам на 8–10 строк. Теперь перенос по дефисам, строка источника ≤ ~4 строк.
  2. «Изменения» → «← старее / новее →»: после касания кнопка оставалась «нажатой» (общий button:hover вьюера вне @media (hover:hover)).
  3. «ИИС-3»: порядок плиток — Стоимость · Заработано / Зафиксировано · К погашению / Деньги · Дюрация.
  4. «Длинные ОФЗ vs TMON»: плитки одного ряда разной высоты (.ui-grid align-items:start).
  5. Категория монитора horizon_passed: подпись «горизонт прошёл» и подсказка в окне прогноза.
Фикстура — живые файлы viewer-live (снимки и обзоры), forecast-pairs; ИИС-блок и отчёт прогнозов дописываются в копию.
Запуск: python3 tools/tests/test_viewer_mobile_3117.py
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
    print("viewer_mobile_3117: пропуск — нет playwright")
    sys.exit(0)

sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as hub_api  # noqa: E402

FIX = Path(tempfile.mkdtemp(prefix="mob3117-"))
LONG = "xauusd-price-2026-2028-2026-07-29-v2"
FC_MD = """# Отчёт прогноза

## Не аудированные источники

| Источник | Рекомендация |
|---|---|
| Аналитик Один | Аудит желателен: уверенные прогнозы с проверяемым исходом и разной оценкой, в том числе по золоту и курсу рубля на разных горизонтах |
| Аналитик Два | Аудит желателен |
"""


def build():
    shutil.rmtree(FIX, ignore_errors=True)
    fx = REPO / "tools/tests/fixtures"
    shutil.copytree(fx / "viewer-live", FIX)
    shutil.copytree(fx / "stress-roles", FIX, dirs_exist_ok=True)
    shutil.copytree(fx / "forecast-pairs", FIX, dirs_exist_ok=True)
    (FIX / "monitor-reports").mkdir()
    for rel in ("forecasts/usd-rub-sept-2026-2026-04-30.yaml", "scenarios/scenario-usd-rub-sept-2026-2026-04-30.yaml"):
        f = FIX / rel
        f.write_text(f.read_text(encoding="utf-8").replace("status: resolved", "status: active", 1), encoding="utf-8")
    # третий обзор акций: у «Изменений» должна быть кнопка «старее»
    wr = FIX / "Portfolio/weekly-reviews"
    old = (wr / "weekly-review-stock-2026-10-01.yaml").read_text(encoding="utf-8")
    for d in ("09-24", "09-17", "09-10", "09-03", "08-27", "08-20", "08-13", "08-06", "07-30", "07-23", "07-16", "07-09", "07-02", "06-25"):   # длинный список обзоров: у выбора появляется поиск
        (wr / f"weekly-review-stock-2026-{d}.yaml").write_text(old.replace("2026-10-01", f"2026-{d}"), encoding="utf-8")
    # отчёты прогнозов с одним и тем же источником под длинными именами тем
    for stem, d in ((LONG[:-len("-2026-07-29-v2")] + "-2026-07-29-v2", "2026-07-29"), ("brent-price-2026-2027-2026-09-17-v3", "2026-09-17"), ("cbr-rate-2026-2027-2026-09-17", "2026-10-01")):
        (FIX / "forecasts" / f"{stem}-{d}.md").write_text(FC_MD, encoding="utf-8")
    # ИИС-3: блок возврата + две облигации и фонд на счёте
    sp = FIX / "Portfolio/snapshots/portfolio-2026-10-08.json"
    s = json.loads(sp.read_text(encoding="utf-8"))
    s["returns"].setdefault("by_account", {})["iis_3"] = {
        "status": "ok", "as_of": "2026-10-08", "broker": "БКС",
        "fact": {"xirr": 0.12, "pnl_rub": 80000, "years": 1.5, "net_external_deposits_rub": 500000, "current_value_rub": 600000},
        "forward": {"account_pct": 14.1, "bonds_irr_pct": 15.0},
        "locked": {"bonds_irr_pct": 13.2}, "per_bond": []}
    n = 0
    for h in s["holdings"]:
        if h.get("asset_type") == "bond" and n < 2 and h.get("duration_days"):
            h["account"] = "iis_3"; h["value_rub"] = h.get("value_rub") or 100000; n += 1
    sp.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    (FIX / "monitor-reports/monitor-report-2026-10-29.yaml").write_text("""schema_version: 1
type: monitor-report
generated_at: "2026-10-29T15:50:00+03:00"
producer: "forecast-monitor"
horizon_window_days: 7
alerts:
  - severity: MEDIUM
    category: horizon_passed
    target: "usd-rub-sept-2026"
    target_file: "forecasts/usd-rub-sept-2026-2026-04-30.yaml"
    target_kind: forecast
    message: "Горизонт 01.09.2026 прошёл"
    detected_at: "2026-10-29"
    suggested_action: "/save-to-library Закрой прогноз usd-rub-sept-2026-2026-04-30.yaml с исходом"
freshness_audit:
  integrated_view: { age_days: 25, due_for_refresh: false }
predictions:
  total_active: 1
  overdue_count: 0
  due_30d_count: 0
  overdue_list: []
condition_events: []
outcome_log_updates: []
""", encoding="utf-8")


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


def open_tab(p, engine, tab, w, h, touch=False):
    browser = getattr(p, engine).launch()
    kw = dict(service_workers="block", viewport={"width": w, "height": h})
    if touch:
        kw.update(has_touch=True, is_mobile=True)
    ctx = browser.new_context(**kw)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/api/pv/plan*", lambda r: r.fulfill(status=502, body="{}"))
    pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, body="{}"))
    pg.goto(URL)
    pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
    pg.wait_for_function("() => state.data && state.data.portfolioLatest && state.data.monitorReport", timeout=20000)
    pg.evaluate(f"() => goToTab('{tab}')")
    pg.wait_for_timeout(500)
    return browser, pg, errs

def bg(loc):
    return loc.evaluate("e => getComputedStyle(e).backgroundColor")


def main():
    with sync_playwright() as p:
        try:
            p.chromium.launch().close()
        except Exception as e:
            print(f"viewer_mobile_3117: пропуск — {str(e).splitlines()[0][:80]}")
            return
        build()

        # 1. «Источники» — Предложения на аудит
        for (w, h, lim) in ((390, 844, 120), (1400, 1000, 120)):
            browser, pg, errs = open_tab(p, "chromium", "sources", w, h)
            pg.evaluate("() => { state.provPart = 'audit-candidates'; renderTabContent(); }")
            pg.wait_for_selector("table.src-cand tr.pick", timeout=5000)
            hs = pg.evaluate("() => [...document.querySelectorAll('table.src-cand tr.pick')].map(r => Math.round(r.getBoundingClientRect().height))")
            check(f"{w}px: строка источника не выше {lim}px ({hs})", hs and max(hs) <= lim)
            ow = pg.evaluate("() => { const t = document.querySelector('table.src-cand td.src-topics'); const cs = getComputedStyle(t); return [cs.overflowWrap, cs.wordBreak]; }")
            check(f"{w}px: темы без переноса по слогам ({ow})", ow[0] in ("normal",) and ow[1] == "normal")
            check(f"{w}px: таблица в .ui-table-wrap", pg.locator(".ui-table-wrap table.src-cand").count() >= 1)
            check(f"{w}px: страница не уехала вбок", pg.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"))
            # темы рвутся только на дефисах: ни одна строка текста темы не обрывается внутри слова
            br = pg.evaluate("""() => { const c = document.querySelector('td.src-topics .src-lines'); const out = []; const w = document.createTreeWalker(c, NodeFilter.SHOW_TEXT); let n;
              while ((n = w.nextNode())) { const t = n.textContent; let prevTop = null; for (let i = 0; i < t.length; i++) { const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + 1); const rc = r.getClientRects()[0]; if (!rc) continue;
                if (prevTop !== null && rc.top - prevTop > 4 && i > 0 && /[A-Za-z0-9]/.test(t[i]) && /[A-Za-z0-9]/.test(t[i - 1])) out.push(t.slice(Math.max(0, i - 3), i + 3)); prevTop = rc.top; } } return out; }""")
            check(f"{w}px: нет разрыва внутри слова ({br[:3]})", not br)
            check(f"{w}px: ошибок страницы нет ({errs[:2]})", not errs)
            browser.close()

        # 2. «Изменения»: после касания кнопка не «нажата» (Chromium и WebKit)
        for eng in ("chromium", "webkit"):
            try:
                browser, pg, errs = open_tab(p, eng, "diff", 390, 844, touch=True)
            except Exception as e:
                print(f"  пропуск {eng}: {str(e).splitlines()[0][:80]}")
                continue
            pg.wait_for_selector("[data-act=diff-older]", timeout=5000)
            rest = bg(pg.locator("[data-act=diff-newer]"))
            check(f"{eng}: на касании нет наведения (hover:none)", pg.evaluate("() => matchMedia('(hover:hover)').matches === false"))
            pg.locator("[data-act=diff-older]").tap()
            pg.wait_for_timeout(500)
            pg.wait_for_selector("[data-act=diff-newer]:not([disabled])", timeout=5000)
            after = bg(pg.locator("[data-act=diff-newer]"))
            check(f"{eng}: после tap фон кнопки как в покое ({rest} / {after})", rest == after)
            pg.locator("[data-act=diff-newer]").tap()
            pg.wait_for_timeout(500)
            check(f"{eng}: после tap «новее» фон «старее» как в покое", bg(pg.locator("[data-act=diff-older]")) == rest)
            check(f"{eng}: ошибок страницы нет ({errs[:2]})", not errs)
            browser.close()

        # 7. Путь владельца: «Акции» → «Фильтры» → тап мимо окна → «Облигации»: плитка не выглядит нажатой
        for eng in ("chromium", "webkit"):
            try:
                browser, pg, errs = open_tab(p, eng, "bonds", 390, 844, touch=True)
            except Exception as e:
                print(f"  пропуск {eng}: {str(e).splitlines()[0][:80]}")
                continue

            def look(sel):
                return pg.locator(sel).last.evaluate("e => { const c = getComputedStyle(e); return [c.backgroundColor, c.borderTopColor, c.boxShadow, c.color]; }")
            tile = ".ui-grid.kpi.sec-tiles button.ui-tile"
            rest = look(tile)
            tb = pg.locator(tile).last.bounding_box()
            pg.evaluate("() => goToTab('positions')"); pg.wait_for_timeout(600)
            pg.locator("button.flt-m").first.tap()
            pg.wait_for_selector("#flt-sheet", timeout=5000)
            pg.wait_for_timeout(400)
            # тап по фону в ту точку, где после перехода окажется плитка «Доходность облигаций» (или выше окна)
            top = pg.locator("#flt-sheet .ui-modal-box").first.bounding_box()["y"]
            x, y = tb["x"] + tb["width"] / 2, min(tb["y"] + tb["height"] / 2, top - 8)
            pg.touchscreen.tap(x, y)
            pg.wait_for_timeout(500)
            check(f"{eng}: тап мимо закрыл окно фильтров", pg.locator("#flt-sheet").count() == 0)
            pg.evaluate("() => goToTab('bonds')"); pg.wait_for_timeout(600)
            check(f"{eng}: плитка «Доходность облигаций» как в покое ({look(tile)} / {rest})", look(tile) == rest)
            check(f"{eng}: ошибок страницы нет ({errs[:2]})", not errs)
            browser.close()

        # 8. «Изменения» на ПК: список выбора обзора поверх содержимого, соседи не двигаются
        for (w, h) in ((1400, 1000), (390, 844)):
            browser, pg, errs = open_tab(p, "chromium", "diff", w, h)
            box = lambda sel: pg.locator(sel).first.bounding_box()
            b0 = [box(".diff-bar .ui-select"), box("[data-act=diff-newer]"), box(".diff-bar")]
            pg.locator(".diff-bar .ui-select-btn").first.click()
            pg.wait_for_selector(".diff-bar .ui-select-pop", state="visible", timeout=5000)
            pg.wait_for_timeout(300)
            b1 = [box(".diff-bar .ui-select"), box("[data-act=diff-newer]"), box(".diff-bar")]
            same = all(abs(a[k] - b[k]) <= 1 for a, b in zip(b0, b1) for k in ("x", "y", "width", "height"))
            check(f"{w}px: сегмент, «новее →» и ряд не сдвинулись при открытии списка ({b0} / {b1})", same)
            pop = pg.locator(".diff-bar .ui-select-pop").first.bounding_box()
            check(f"{w}px: список видим", pop and pop["height"] > 40)
            if w >= 1000 and pop:
                over = pg.evaluate("""([x, y]) => { const e = document.elementFromPoint(x, y); return !!(e && e.closest('.ui-select-pop')); }""", [pop["x"] + 30, pop["y"] + pop["height"] - 10])
                check("1400px: список перекрывает содержимое под собой (elementFromPoint)", over)
            check(f"{w}px: ошибок страницы нет ({errs[:2]})", not errs)
            browser.close()

        # 3. ИИС-3: порядок плиток
        want = ["Стоимость счёта", "Заработано", "Зафиксировано при покупке", "К погашению сейчас", "Деньги на счёте", "Дюрация облигаций"]
        for (w, h) in ((390, 844), (1400, 1000)):
            browser, pg, errs = open_tab(p, "chromium", "iis", w, h)
            ks = pg.evaluate("() => [...document.querySelectorAll('.ui-grid.kpi.sec-tiles > .ui-tile .ui-kicker')].map(e => e.textContent.trim())")
            check(f"{w}px: порядок плиток ИИС-3 ({ks})", ks == want)
            pos = pg.evaluate("() => [...document.querySelectorAll('.ui-grid.kpi.sec-tiles > .ui-tile')].map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.top / 10), Math.round(r.left)]; })")
            check(f"{w}px: чтение слева направо, сверху вниз ({pos})", pos == sorted(pos))
            check(f"{w}px: ошибок страницы нет ({errs[:2]})", not errs)
            browser.close()

        # 4. «Длинные ОФЗ vs TMON»: плитки ряда одной высоты
        browser, pg, errs = open_tab(p, "chromium", "bonds", 390, 844)
        n = pg.locator(".sig-stats .ui-stat").count()
        check(f"сигнал дюрации есть ({n} плиток)", n >= 2)
        if n >= 2:
            rows = pg.evaluate("""() => { const m = new Map(); for (const e of document.querySelectorAll('.sig-stats .ui-stat')) { const r = e.getBoundingClientRect(); const k = Math.round(r.top); (m.get(k) || m.set(k, []).get(k)).push(r.height); } return [...m.values()]; }""")
            check(f"высоты в ряду равны ±1px ({rows})", all(max(r) - min(r) <= 1 for r in rows) and any(len(r) > 1 for r in rows))
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # 5. horizon_passed
        browser, pg, errs = open_tab(p, "chromium", "actions", 1400, 1000)
        pg.wait_for_selector("#content .act-alert", timeout=5000)
        # R20 (уточнено 03.11, 4.2.2): «горизонт прошёл» у прогноза вне входов стресса — строка в «Проверить» (#act-check, .act-horizon[data-horizon]), не в «К сведению»
        row = pg.locator('#act-check .act-horizon[data-horizon="usd-rub-sept-2026-2026-04-30"]')
        check("«Действия»: подпись «горизонт прошёл» в «Проверить» (4.2.2)", row.count() >= 1 and "горизонт прошёл" in row.first.inner_text() and "закрой с исходом" in row.first.inner_text())
        row.first.locator("b").first.click()
        pg.wait_for_function("() => { const o = document.querySelector('#modal-overlay'); return o && !o.hidden && document.querySelector('#modal').innerText.includes('Почему монитор просит обновить'); }", timeout=5000)
        txt = pg.evaluate("() => document.querySelector('#modal .fdoc-why').innerText")
        check("окно: подпись категории", "горизонт прошёл" in txt)
        check("окно: подсказка «обновлять нечего — закрой с исходом»", "Обновлять нечего" in txt and "закрой" in txt)
        check("окно: suggested_action как есть", "/save-to-library Закрой прогноз usd-rub-sept-2026-2026-04-30.yaml с исходом" in txt)
        check("окно: кнопка команды для Claude (контур, значок, подпись «Закрыть» у прогноза с прошедшим горизонтом)", pg.locator("#modal .fdoc-why button.ui-claude-cmd").count() == 1 and pg.locator("#modal .fdoc-why button.ui-link").count() == 0
              and pg.locator("#modal .fdoc-why .ui-claude-cmd svg").count() == 1 and pg.locator("#modal .fdoc-why .ui-claude-cmd").inner_text().strip() == "Закрыть")
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()


main()
shutil.rmtree(FIX, ignore_errors=True)
print(f"Итого: {passed} из {passed + failed} прошли" if failed == 0 else f"Итого: {passed} из {passed + failed} прошли (падений: {failed})")
sys.exit(1 if failed else 0)
