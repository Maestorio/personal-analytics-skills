#!/usr/bin/env python3
"""ui-kit 1.62.0 / вьюер 3.118.0: длинный список (combo) раскрывается ПОВЕРХ содержимого везде.

Решение владельца 2026-10-30: combo (uiSelectHTML, size:'md', ≥13 вариантов) раньше вставал в поток формы и
раздвигал соседей (ряд «Изменений», шапка отчёта, карточка облигации КОРП — «Рейтинг», 17 вариантов).
Теперь: кнопка остаётся невидимой и держит высоту, список — position:fixed у поля, вниз не влезает — вверх.

Что проверяется (Chromium; 1400 и 390): координаты корня списка, его родителя, соседей до и после открытия равны (±1px);
список виден, перекрывает содержимое (elementFromPoint), bbox внутри окна; выбор доходит событием ui-select;
Esc закрывает, высота корня та же. Места:
  — вьюер «Изменения» (выбор обзора, 15 обзоров в копии фикстуры viewer-live);
  — вьюер «Акции»: фильтр «Сектор» при 17 секторах (подмена в памяти страницы);
  — вьюер: «Рейтинг» (bondRatingSelect, 17 вариантов) в прокручиваемом окне формы .ui-modal-body, соседи сверху и снизу;
  — «Еда»: «Заменить на продукт» в окне плана покупок (стенд test_food_layout) и «Продукт для …» при импорте.
Проверка падением: откат ui-kit 1.62.0 (combo снова position:static) — все «соседи не сдвинулись» падают.
ui-kit 1.65.3: список «План» в карточке бумаги (1400 и 390, план сайта подменён) — правый край не за краем окна карточки и
экрана, при нехватке места справа — по правому краю кнопки (на обеих ширинах случай «вылез бы» срабатывает: откат правки
даёт правый край 1394 при окне 1274 — падает).
Запуск: python3 tools/tests/test_select_combo_overlay.py
"""
import importlib.util as _ilu
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
    print("select_combo_overlay: пропуск — нет playwright")
    sys.exit(0)

sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as hub_api  # noqa: E402

FIX = Path(tempfile.mkdtemp(prefix="combo-ov-"))


def build():
    shutil.rmtree(FIX, ignore_errors=True)
    shutil.copytree(REPO / "tools/tests/fixtures/viewer-live", FIX)
    wr = FIX / "Portfolio/weekly-reviews"
    old = (wr / "weekly-review-stock-2026-10-01.yaml").read_text(encoding="utf-8")
    for d in ("09-24", "09-17", "09-10", "09-03", "08-27", "08-20", "08-13", "08-06", "07-30", "07-23", "07-16", "07-09", "07-02", "06-25"):
        (wr / f"weekly-review-stock-2026-{d}.yaml").write_text(old.replace("2026-10-01", f"2026-{d}"), encoding="utf-8")


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

# «Еда»: стенд test_food_layout (как в test_select_layout)
_spec = _ilu.spec_from_file_location("food_fx", Path(__file__).with_name("test_food_layout.py"))
FX = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(FX)
FX.PRODUCTS = {**FX.PRODUCTS, "products": FX.PRODUCTS["products"] + [
    {"id": f"p{i}", "name": n, "unit": "г", "category": "бакалея"} for i, n in enumerate(
        ["Рис", "Пшено", "Овсянка", "Сахар", "Соль", "Масло сливочное", "Масло оливковое", "Молоко",
         "Сметана", "Творог", "Ёжевика", "Перец"])]}
_food_root = Path(tempfile.mkdtemp()) / "Food"
FX.make_food_root(_food_root)
_fsrv = serve(FX.make_handler(_food_root))[0]
FOOD = f"http://127.0.0.1:{_fsrv.server_address[1]}/tools/food.html"
IMPORT_MD = ('# Блины проверочные\n\n```json\n' + json.dumps({"servings": 2, "ingredients": [
    {"name": "Мука", "qty": 200, "unit": "г"}, {"name": "Неведомый продукт", "qty": 1, "unit": "шт"}]},
    ensure_ascii=False) + '\n```\n')

# раскладка вокруг списка: сам корень, родитель, его соседи, соседи корня
RECTS = """(sel) => {
  const root = document.querySelector(sel); if (!root) return null;
  const r = (e) => { if (!e) return null; const b = e.getBoundingClientRect(); return [b.x, b.y, b.width, b.height]; };
  const par = root.parentElement;
  return { root: r(root), par: r(par), parNext: r(par.nextElementSibling), parPrev: r(par.previousElementSibling),
           next: r(root.nextElementSibling), prev: r(root.previousElementSibling), nextSib: r(root.nextElementSibling),
           grand: r(par.parentElement) };
}"""
POP = """(sel) => { const root = document.querySelector(sel); const pop = root.querySelector('.ui-select-pop');
  if (!pop || pop.hidden) return null; const b = pop.getBoundingClientRect(); const cs = getComputedStyle(pop);
  const pts = [[b.x + b.width / 2, b.y + 6], [b.x + b.width / 2, b.y + b.height - 6]];
  const hit = pts.map(([x, y]) => { const e = document.elementFromPoint(x, y); return !!(e && e.closest('.ui-select-pop') === pop); });
  return { x: b.x, y: b.y, w: b.width, h: b.height, pos: cs.position, hit, vw: innerWidth, vh: innerHeight,
           btnVis: getComputedStyle(root.querySelector('.ui-select-btn')).visibility, opts: root.querySelectorAll('.ui-opt').length }; }"""


def same(a, b):
    if a is None or b is None:
        return a == b
    return all(abs(x - y) <= 1 for x, y in zip(a, b))


def probe(pg, tag, sel, pick_text=None, stage=None):
    """открыть список в корне sel, сверить раскладку, выбрать вариант, закрыть Esc"""
    pg.evaluate("() => { window.__ev = []; document.addEventListener('ui-select', e => window.__ev.push(e.detail)); }")
    before = pg.evaluate(RECTS, sel)
    check(f"{tag}: корень списка найден", before is not None)
    if before is None:
        return
    pg.locator(f"{sel} .ui-select-btn").first.click()
    pg.wait_for_selector(f"{sel} .ui-select-pop", state="visible", timeout=5000)
    pg.wait_for_timeout(450)
    after = pg.evaluate(RECTS, sel)
    moved = [k for k in before if not same(before[k], after[k])]
    check(f"{tag}: корень, родитель и соседи не сдвинулись при открытии ({moved}: {[(before[k], after[k]) for k in moved][:2]})", not moved)
    pop = pg.evaluate(POP, sel)
    check(f"{tag}: список виден, поверх (fixed), поле осталось на месте ({pop and (pop['pos'], pop['btnVis'], round(pop['h']))})",
          pop and pop["h"] > 40 and pop["pos"] == "fixed" and pop["btnVis"] == "hidden")
    if pop:
        check(f"{tag}: список целиком в окне ({pop['x']:.0f},{pop['y']:.0f} {pop['w']:.0f}×{pop['h']:.0f} в {pop['vw']}×{pop['vh']})",
              pop["x"] >= -1 and pop["y"] >= -1 and pop["x"] + pop["w"] <= pop["vw"] + 1 and pop["y"] + pop["h"] <= pop["vh"] + 1)
        check(f"{tag}: список перекрывает содержимое под собой (elementFromPoint {pop['hit']})", all(pop["hit"]))
    opt = pg.locator(f"{sel} .ui-opt", has_text=pick_text) if pick_text else pg.locator(f"{sel} .ui-opt")
    opt.nth(2 if not pick_text else 0).click()
    pg.wait_for_timeout(300)
    ev = pg.evaluate("() => window.__ev")
    check(f"{tag}: выбор доходит событием ui-select ({ev})", len(ev) >= 1)


def open_viewer(p, tab, w, h):
    browser = p.chromium.launch()
    ctx = browser.new_context(service_workers="block", viewport={"width": w, "height": h})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/api/pv/plan*", lambda r: r.fulfill(status=502, body="{}"))
    pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, body="{}"))
    pg.goto(URL)
    pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
    pg.wait_for_function("() => state.data && state.data.portfolioLatest && state.data.weeklyReviewCurrent", timeout=20000)
    return browser, pg, errs


def main():
    with sync_playwright() as p:
        try:
            p.chromium.launch().close()
        except Exception as e:
            print(f"select_combo_overlay: пропуск — {str(e).splitlines()[0][:80]}")
            return
        build()
        for (w, h) in ((1400, 1000), (390, 844)):
            # 1. «Изменения»
            browser, pg, errs = open_viewer(p, "diff", w, h)
            pg.evaluate("() => goToTab('diff')"); pg.wait_for_timeout(600)
            probe(pg, f"{w}px «Изменения»", ".diff-bar .ui-select")
            check(f"{w}px «Изменения»: ошибок страницы нет ({errs[:2]})", not errs)

            # 2. «Акции»: фильтр «Сектор» при 17 секторах
            pg.evaluate("""() => { const ps = state.data.weeklyReviewCurrent.parsed.per_stock, k0 = Object.keys(ps)[0];
              for (let i = 0; i < 17; i++) ps['ZZ' + i] = Object.assign({}, ps[k0], { ticker: 'ZZ' + i, sector_ru: 'Тестовый сектор ' + (i + 1), sector: 'zz' + i });
              goToTab('positions'); }""")
            pg.wait_for_timeout(700)
            if w <= 600 and pg.locator("button.flt-m").count():
                pg.locator("button.flt-m").first.click()
                pg.wait_for_selector("#flt-sheet", timeout=5000)
                pg.wait_for_timeout(400)
            n = pg.evaluate("() => { const c = [...document.querySelectorAll('.filters .ui-select.combo')]; return c.length; }")
            check(f"{w}px «Акции»: фильтр «Сектор» — длинный список (combo: {n})", n >= 1)
            if n:
                pg.evaluate("() => { document.querySelector('.filters .ui-select.combo').id = 'sector-combo'; }")
                probe(pg, f"{w}px «Акции» Сектор", "#sector-combo", pick_text="Тестовый сектор 5")
            check(f"{w}px «Акции»: ошибок страницы нет ({errs[:2]})", not errs)

            # 3. «Рейтинг» в окне формы с прокруткой: соседи сверху и снизу
            pg.evaluate("""() => {
              window.planSetBatch = async () => ({ ok: true }); window.planRefreshAll = () => {};
              const body = '<div class="ui-field"><div class="fld-lbl">Выше</div><input class="fld" value="сосед сверху"></div>' +
                '<div class="bx-row" id="rt-host"></div>' +
                '<div class="ui-field"><div class="fld-lbl">Ниже</div><input class="fld" value="сосед снизу"></div>' +
                '<div style="height:900px">тело окна длиннее экрана: оно прокручивается</div>';
              document.body.insertAdjacentHTML('beforeend', uiModalHTML({ title: 'Облигация КОРП', body, z: 400 }));
              const host = document.getElementById('rt-host'); host.appendChild(bondRatingSelect('RU000A0TEST1', 'A', true));
              host.querySelector('.ui-select').id = 'rating-combo'; }""")
            pg.wait_for_timeout(300)
            nopt = pg.evaluate("() => document.querySelectorAll('#rating-combo .ui-opt').length")
            check(f"{w}px «Рейтинг»: 17 вариантов ({nopt}), combo", nopt == 17 and pg.locator("#rating-combo.combo").count() == 1)
            probe(pg, f"{w}px «Рейтинг» в окне формы", "#rating-combo", pick_text="BBB+")
            # Esc закрывает список, окно остаётся
            pg.locator("#rating-combo .ui-select-btn").first.click(); pg.wait_for_timeout(200)
            pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
            check(f"{w}px «Рейтинг»: Esc закрыл список",
                  pg.evaluate("() => document.querySelector('#rating-combo .ui-select-pop').hidden"))
            check(f"{w}px «Рейтинг»: ошибок страницы нет ({errs[:2]})", not errs)
            browser.close()

        # 5. ui-kit 1.65.3: список «План» в карточке бумаги — правый край не за краем окна карточки и экрана; если от левого
        # края кнопки список вылез бы за край — он выровнен по правому краю кнопки (откат на «всегда от левого края» — падает)
        for (w, h) in ((1400, 1000), (390, 844)):
            browser = p.chromium.launch()
            ctx = browser.new_context(service_workers="block", viewport={"width": w, "height": h})
            pg = ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            site = {"plan": None}
            pg.route("**/api/pv/plan", lambda r: r.fulfill(status=502, body="{}") if site["plan"] is None else r.fulfill(
                status=200, content_type="application/json", body=json.dumps({"path": "Portfolio/plan.json", "hash": "h1", "plan": site["plan"]})))
            pg.route("**/api/pv/plan/journal*", lambda r: r.fulfill(status=200, content_type="application/json", body='{"entries": []}'))
            pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, body="{}"))
            pg.goto(URL)
            pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
            pg.wait_for_function("() => state.data && state.data.portfolioLatest && state.data.weeklyReviewCurrent", timeout=20000)
            pt = pg.evaluate("() => currentPort().ie_actual.per_ticker")
            site["plan"] = {"schema_version": 1, "stocks": {k: {"plan_pct": v.get("planned_share_pct"), "user_plan": v.get("user_plan") or "KEEP",
                                                               "user_status": v.get("user_status")} for k, v in pt.items()},
                            "classes": [], "matrix": [], "bond_buckets": [], "bonds": {}, "funds": {}, "manual_positions": [], "ie_model": {},
                            "updated_at": "2026-10-28T10:00:00Z"}
            pg.evaluate("async () => { await loadPlan(); dsInvalidate(); }")
            t0 = next(iter(pt))
            pg.evaluate("(t) => { goToTab('positions'); const pbt = buildPositionByTicker(); openCard(pbt[t], [pbt[t]]); }", t0)
            pg.wait_for_selector("#card-layer .card-pane", timeout=8000)
            pg.wait_for_timeout(400)
            sel = pg.evaluate("""(t) => { const r = [...document.querySelectorAll('#card-layer .ui-select')].find(x => /^План /.test(x.querySelector('.ui-select-btn')?.getAttribute('aria-label') || x.textContent) || x.querySelector('input[name^="ie-pl-"]'));
              if (!r) return null; r.id = 'card-plan-sel'; r.scrollIntoView({ block: 'center' }); return true; }""", t0)
            check(f"{w}px карточка {t0}: список «План» есть", sel is True)
            if sel:
                pg.locator("#card-plan-sel .ui-select-btn").first.click()
                pg.wait_for_selector("#card-plan-sel .ui-select-pop", state="visible", timeout=5000)
                pg.wait_for_timeout(300)
                g = pg.evaluate("""() => { const root = document.getElementById('card-plan-sel'), b = root.querySelector('.ui-select-btn').getBoundingClientRect(),
                  p = root.querySelector('.ui-select-pop').getBoundingClientRect(), m = root.closest('.ui-card, .ui-modal-body, .ui-modal').getBoundingClientRect();
                  return { bl: b.left, br: b.right, pl: p.left, pr: p.right, pw: p.width, mr: m.right, vw: innerWidth }; }""")
                over = g["bl"] + g["pw"] > min(g["mr"], g["vw"] - 8) + 1
                check(f"{w}px карточка: список «План» не за краем окна карточки и экрана ({g})",
                      g["pr"] <= g["mr"] + 1 and g["pr"] <= g["vw"] + 1 and g["pl"] >= -1)
                check(f"{w}px карточка: вылез бы от левого края кнопки — выровнен по правому краю кнопки ({over}, {g['pr']:.0f} / {g['br']:.0f})",
                      (abs(g["pr"] - g["br"]) <= 1 or g["pl"] <= 9) if over else abs(g["pl"] - g["bl"]) <= 1)
                pg.keyboard.press("Escape")
            check(f"{w}px карточка: ошибок страницы нет ({errs[:2]})", not errs)
            browser.close()

        # 4. «Еда»
        for (w, h) in ((1400, 900), (390, 760)):
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport={"width": w, "height": h})
            pg = ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.route("**/api/fd/**", lambda r: r.fulfill(status=200, content_type="application/json", body='{"hash":"y"}') if r.request.method == "POST" else r.fallback())
            pg.goto(FOOD + "?recipe=plan"); pg.wait_for_timeout(900)
            pg.evaluate("document.querySelector('[data-act=plan-open]').click()"); pg.wait_for_timeout(300)
            pg.evaluate("document.querySelector('[data-act=plan-swap]').click()"); pg.wait_for_timeout(250)
            pg.evaluate("() => { document.getElementById('f-swap').closest('.ui-select').id = 'swap-combo'; }")
            check(f"{w}px «Еда» замена: combo", pg.locator("#swap-combo.combo").count() == 1)
            probe(pg, f"{w}px «Еда» Заменить на продукт", "#swap-combo", pick_text="Ёжевика")
            check(f"{w}px «Еда» замена: ошибок страницы нет ({errs[:2]})", not errs)
            browser.close()

    shutil.rmtree(FIX, ignore_errors=True)


main()
print(f"Итого: {passed} из {passed + failed} прошли" if failed == 0 else f"Итого: {passed} из {passed + failed} прошли (падений: {failed})")
sys.exit(1 if failed else 0)
