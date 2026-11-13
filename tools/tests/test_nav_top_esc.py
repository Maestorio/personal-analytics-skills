#!/usr/bin/env python3
"""«Наверх», Escape и меню при открытых окнах (ui-kit 1.64.0) — настоящими
браузерами Chromium и WebKit, 390 и 1400 px.

Что закрывает. До 1.64.0 каждая страница писала это сама, и одни забывали:
games и travel гасили Escape без preventDefault (Mac сначала выходил из
полноэкранного режима), вкладки поднимались наверх плавно или не поднимались,
меню при открытом окне оставляло окно поверх нового раздела.

Проверяется:
  1. пункт меню/рельса/вкладок (другой и ТЕКУЩИЙ): scrollY == 0, прокрутка
     мгновенная — слушатель scroll не видит значений, кроме исходного и 0
     (health, food, money, games; вьюер — если смонтирован Synology);
  2. при открытой панели только для чтения пункт закрывает её и поднимает;
     при изменённой форме — uiConfirm «Закрыть без сохранения?»: «Остаться»
     оставляет форму с введённым, «Закрыть» — закрывает и переходит;
  3. Escape при открытом окне на каждой странице (health, food, money, games,
     travel, вьюер): окно закрыто и event.defaultPrevented === true;
  4. «↑ В начало» в читателе — мгновенно;
  5. ошибок JS нет.

Данные — стенды соседних тестов (select_layout: health/food/вьюер,
money_layout, doc_window: travel). Движок, которого нет, — честный пропуск.

Запуск:
    python3 tools/tests/test_nav_top_esc.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "skills" / "travel-planning" / "scripts"))
from _pages_stand import SYNOLOGY_LOCK, Checker, fixture, frames, per_engine, serve as stand_serve, settle  # noqa: E402

check = Checker()


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("nav_top_esc: пропуск — нет playwright")
    sys.exit(0)


SEL = fixture("test_select_layout.py", "\n# ── запуск ──")
MON = fixture("test_money_layout.py", "\nwith sync_playwright() as p:")
TOOLS = SEL["URL"].rsplit("/", 1)[0] + "/"
MEM = SEL["MEM"]

from test_travel_status import FAKE_NOW, TRIPS, make_root, serve  # noqa: E402

AUTH = "localStorage.setItem('hub-auth','dGVzdDp0ZXN0'); localStorage.setItem('money-tab','overview');"
TALL = "body{min-height:5200px !important}"

# окно Escape: слушатель на window (после document) видит, погасили ли событие
ESC_PROBE = "() => { window.__dp = null; window.addEventListener('keydown', e => { if (e.key === 'Escape') window.__dp = e.defaultPrevented; }); }"

# откуда пункт: видимая кнопка меню/рельса (data-ui-nav) или сегмент «Денег» на широком экране
CLICK_NAV = """(k) => {
  const all = [...document.querySelectorAll('[data-ui-nav="' + k + '"], .ui-seg-btn[data-act="tab"][data-v="' + k + '"]')];
  const b = all.find(e => e.offsetWidth > 0 && e.offsetHeight > 0);
  if (!b) return false; b.click(); return true; }"""
NAV_KEYS = """() => {
  const vis = e => e.offsetWidth > 0 && e.offsetHeight > 0;
  let ks = [...new Set([...document.querySelectorAll('[data-ui-nav]')].filter(vis).map(e => e.getAttribute('data-ui-nav')))];
  if (!ks.length) ks = [...new Set([...document.querySelectorAll('.ui-seg-btn[data-act="tab"]')].filter(vis).map(e => e.getAttribute('data-v')))];
  const cur = (document.querySelector('[data-ui-nav].on') || document.querySelector('.ui-seg-btn.on[data-act="tab"]') || {getAttribute: () => null});
  return { keys: ks, cur: cur.getAttribute('data-ui-nav') || cur.getAttribute('data-v') }; }"""


def at_top(pg, js="window.scrollY"):
    """Ждать позицию 0 (до 1 с; раньше — фиксированные 450–500 мс) и ещё 150 мс: плавная прокрутка
    успела бы оставить промежуточные значения в слушателе scroll, поздняя перерисовка — сдвинуть страницу."""
    try:
        pg.wait_for_function(f"{js} === 0", timeout=1000)
    except Exception:   # noqa: BLE001 — решает проверка
        pass
    pg.wait_for_timeout(150)


def lift(tag, pg, key, scroller="window"):
    """Прокрутить вниз, нажать пункт key: scrollY == 0 и прокрутка мгновенная."""
    pg.evaluate("() => window.scrollTo(0, 1500)")
    pg.wait_for_timeout(120)
    y0 = pg.evaluate("window.scrollY")
    pg.evaluate("() => { window.__sv = []; window.addEventListener('scroll', () => window.__sv.push(Math.round(window.scrollY))); }")
    ok = pg.evaluate(CLICK_NAV, key)
    at_top(pg)
    y1 = pg.evaluate("window.scrollY")
    sv = pg.evaluate("window.__sv")
    check(f"{tag}: пункт «{key}» найден и нажат", ok)
    check(f"{tag}: пункт «{key}» → scrollY == 0 ({y0} → {y1})", y0 > 300 and y1 == 0)
    check(f"{tag}: прокрутка мгновенная — промежуточных значений нет ({sv})", all(v in (y0, 0) for v in sv))


def new_page(browser, w, h, wire=None, init=AUTH):
    ctx = browser.new_context(viewport={"width": w, "height": h}, has_touch=w < 600)
    ctx.add_init_script(init)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    if wire:
        wire(pg)
    return ctx, pg, errs


def esc_closed(tag, pg, closed_js, what):
    pg.evaluate(ESC_PROBE)
    pg.keyboard.press("Escape")
    try:
        pg.wait_for_function(closed_js, timeout=2500)
        gone = True
    except Exception:
        gone = False
    check(f"{tag}: Escape закрывает {what}", gone)
    check(f"{tag}: Escape погашен (defaultPrevented) — Mac не выходит из полноэкранного режима", pg.evaluate("window.__dp") is True)


def confirm_flow(tag, pg, key, still_js, gone_js, typed_js):
    """Форма изменена → uiConfirm; «Остаться» — форма на месте; «Закрыть» — закрыта."""
    pg.evaluate(CLICK_NAV, key)
    try:
        pg.wait_for_selector(".ui-confirm", timeout=2500)
        asked = True
    except Exception:
        asked = False
    check(f"{tag}: изменённая форма + пункт меню → «Закрыть без сохранения?»", asked)
    if not asked:
        return
    check(f"{tag}: вопрос называется «Закрыть без сохранения?»", "Закрыть без сохранения" in pg.inner_text(".ui-confirm"))
    pg.click(".ui-confirm-no")
    pg.wait_for_timeout(300)
    check(f"{tag}: «Остаться» — форма на месте с введённым", pg.evaluate(still_js) and pg.evaluate(typed_js))
    pg.evaluate(CLICK_NAV, key)
    pg.wait_for_selector(".ui-confirm", timeout=2500)
    pg.click(".ui-confirm-ok")
    try:
        pg.wait_for_function(gone_js, timeout=4000)
        gone = True
    except Exception:
        gone = False
    check(f"{tag}: «Закрыть» — форма закрыта, переход выполнен", gone)


# ── health ──────────────────────────────────────────────────────────────────
def run_health(eng, browser, w, h):
    tag = f"{eng} {w}px health"
    ctx, pg, errs = new_page(browser, w, h, wire=lambda p: SEL["wire"](p, []))
    pg.goto(SEL["URL"])
    pg.wait_for_selector("[data-ui-nav]", state="attached", timeout=15000)
    settle(pg, "!!document.querySelector('[data-ui-nav].on')", margin=300)
    pg.add_style_tag(content=TALL)
    st = pg.evaluate(NAV_KEYS)
    other = next(k for k in st["keys"] if k != st["cur"])
    lift(tag + " другой", pg, other)
    lift(tag + " текущий", pg, other)
    # панель только для чтения
    pg.evaluate(CLICK_NAV, "markers")
    frames(pg, 150)   # вкладка рисуется синхронно; следующий клик локатором сам ждёт элемент
    pg.locator('[data-act="open"][data-id="glucose"]:visible').first.click()
    pg.wait_for_selector(".ui-pane", timeout=5000)
    pg.evaluate(CLICK_NAV, "vax")
    try:
        pg.wait_for_function("document.querySelectorAll('.ui-pane').length === 0", timeout=3000)
        closed = True
    except Exception:
        closed = False
    pg.wait_for_timeout(300)
    check(f"{tag}: открытая панель закрыта пунктом меню, подтверждения нет", closed and pg.locator(".ui-confirm").count() == 0)
    check(f"{tag}: после закрытия панели поднялись наверх и перешли ({pg.evaluate('window.scrollY')})",
          pg.evaluate("window.scrollY") == 0 and pg.evaluate(NAV_KEYS)["cur"] == "vax")
    # Escape на панели
    pg.evaluate(CLICK_NAV, "markers")
    frames(pg, 150)   # вкладка рисуется синхронно; следующий клик локатором сам ждёт элемент
    pg.locator('[data-act="open"][data-id="glucose"]:visible').first.click()
    pg.wait_for_selector(".ui-pane", timeout=5000)
    esc_closed(tag + " панель", pg, "document.querySelectorAll('.ui-pane').length === 0", "панель")
    # форма с изменением
    pg.evaluate(CLICK_NAV, "meds")
    frames(pg, 150)
    pg.locator('[data-act="med-add"]:visible').first.click()
    pg.wait_for_selector(".ui-modal", timeout=5000)
    esc_closed(tag + " форма", pg, "document.querySelectorAll('.ui-modal').length === 0", "форму")
    pg.locator('[data-act="med-add"]:visible').first.click()
    pg.wait_for_selector(".ui-modal", timeout=5000)
    pg.locator('.ui-modal input[type="text"]:visible').first.fill("Проверочное лекарство")
    confirm_flow(tag, pg, st["cur"], "document.querySelectorAll('.ui-modal').length === 1",
                 "document.querySelectorAll('.ui-modal').length === 0 && !document.querySelector('.ui-confirm')",
                 "[...document.querySelectorAll('.ui-modal input')].some(i => i.value === 'Проверочное лекарство')")
    check(f"{tag}: ошибок JS нет {errs[:2]}", not errs)
    ctx.close()


# ── food ────────────────────────────────────────────────────────────────────
def run_food(eng, browser, w, h):
    tag = f"{eng} {w}px food"
    ctx, pg, errs = new_page(browser, w, h)
    pg.goto(SEL["FOOD"])
    pg.wait_for_load_state("networkidle")
    settle(pg, "!!document.querySelector('[data-ui-nav].on')", margin=300)
    pg.add_style_tag(content=TALL)
    st = pg.evaluate(NAV_KEYS)
    other = next(k for k in st["keys"] if k != st["cur"])
    lift(tag + " другой", pg, other)
    lift(tag + " текущий", pg, other)
    pg.goto(SEL["FOOD"] + "?recipe=test")
    pg.wait_for_load_state("networkidle")
    pg.wait_for_selector("[data-act=plan-open]", timeout=10000)
    pg.add_style_tag(content=TALL)
    pg.evaluate("document.querySelector('[data-act=plan-open]').click()")
    pg.wait_for_selector(".ui-modal", timeout=5000)
    esc_closed(tag + " окно", pg, "document.querySelectorAll('.ui-modal').length === 0", "окно")
    pg.evaluate("document.querySelector('[data-act=plan-open]').click()")
    pg.wait_for_selector(".ui-modal", timeout=5000)
    pg.evaluate(CLICK_NAV, other)
    try:
        pg.wait_for_function("document.querySelectorAll('.ui-modal').length === 0", timeout=3000)
        closed = True
    except Exception:
        closed = False
    pg.wait_for_timeout(400)
    check(f"{tag}: открытое окно закрыто пунктом меню, подтверждения нет", closed and pg.locator(".ui-confirm").count() == 0)
    # редактор рецепта с правкой
    pg.goto(SEL["FOOD"] + "?recipe=test")
    pg.wait_for_selector("[data-act=edit-recipe]", timeout=10000)
    pg.evaluate("document.querySelector('[data-act=edit-recipe]').click()")
    pg.wait_for_selector("[data-act=ed-cancel]", timeout=5000)
    esc_closed(tag + " редактор", pg, "!document.querySelector('[data-act=ed-cancel]')", "редактор («Отмена»)")
    pg.evaluate("document.querySelector('[data-act=edit-recipe]').click()")
    pg.wait_for_selector("[data-act=ed-cancel]", timeout=5000)
    pg.locator('#app input:not([type=checkbox]):not([type=radio]):not([type=hidden]):not([type=file]):visible, #app textarea:visible').first.fill("Правка названия")
    confirm_flow(tag, pg, other, "!!document.querySelector('[data-act=ed-cancel]')",
                 "!document.querySelector('[data-act=ed-cancel]') && !document.querySelector('.ui-confirm')",
                 "[...document.querySelectorAll('#app input')].some(i => i.value === 'Правка названия')")
    check(f"{tag}: ошибок JS нет {errs[:2]}", not errs)
    ctx.close()


# ── money ───────────────────────────────────────────────────────────────────
def run_money(eng, browser, w, h):
    tag = f"{eng} {w}px money"
    ctx, pg, errs = new_page(browser, w, h, init="localStorage.setItem('hub-auth','dGVzdDp0ZXN0'); if (!sessionStorage.getItem('t')) { sessionStorage.setItem('t','1'); localStorage.setItem('money-tab','spend'); }")
    pg.goto(MON["URL"])
    pg.wait_for_selector("#dyn .ui-col")
    pg.add_style_tag(content=TALL)
    st = pg.evaluate(NAV_KEYS)
    other = next(k for k in st["keys"] if k != st["cur"])
    lift(tag + " другой", pg, other)
    lift(tag + " текущий", pg, other)
    pg.evaluate(CLICK_NAV, "spend")
    pg.wait_for_selector('[data-act="cat"][data-v="Питание"]')
    pg.click('[data-act="chart"][data-v="spend"]')
    pg.click('[data-act="cat"][data-v="Питание"]')
    pg.wait_for_selector(".ui-catdetail")
    pg.click('.ui-catdetail [data-act="yoy"]')
    pg.wait_for_selector(".ui-modal .ui-cols.yoy.pick")
    pg.wait_for_function("![...document.querySelectorAll('.ui-modal *')].some(e => e.getAnimations().length)")
    esc_closed(tag + " yoy", pg, "document.querySelectorAll('.ui-modal').length === 0", "окно «к прошлому году»")
    if w < 600:   # на широком сегмент вкладок закрыт окном — нажать его нельзя
        pg.click('.ui-catdetail [data-act="yoy"]')
        pg.wait_for_selector(".ui-modal .ui-cols.yoy.pick")
        pg.evaluate(CLICK_NAV, "overview")
        try:
            pg.wait_for_function("document.querySelectorAll('.ui-modal').length === 0", timeout=3000)
            closed = True
        except Exception:
            closed = False
        check(f"{tag}: окно закрыто пунктом меню, подтверждения нет", closed and pg.locator(".ui-confirm").count() == 0)
    check(f"{tag}: ошибок JS нет {errs[:2]}", not errs)
    ctx.close()


# ── games ───────────────────────────────────────────────────────────────────
def run_games(eng, browser, w, h):
    tag = f"{eng} {w}px games"
    ctx, pg, errs = new_page(browser, w, h)
    pg.goto(TOOLS + "games.html")
    settle(pg, "!!document.querySelector('[data-ui-nav].on, [data-ui-nav][aria-current]')", margin=300)
    pg.add_style_tag(content=TALL)
    st = pg.evaluate(NAV_KEYS)
    other = next(k for k in st["keys"] if k != st["cur"])
    lift(tag + " другой", pg, other)
    lift(tag + " текущий", pg, other)
    # просмотрщик документа: открываем как страница (снимаем hidden)
    pg.evaluate("document.getElementById('viewer').hidden = false")
    esc_closed(tag + " просмотрщик", pg, "document.getElementById('viewer').hidden", "просмотрщик")
    pg.evaluate("document.getElementById('viewer').hidden = false")
    pg.evaluate(CLICK_NAV, st["cur"])
    pg.wait_for_timeout(400)
    check(f"{tag}: просмотрщик закрыт пунктом меню, подтверждения нет",
          pg.evaluate("document.getElementById('viewer').hidden") and pg.locator(".ui-confirm").count() == 0)
    check(f"{tag}: ошибок JS нет {errs[:2]}", not errs)
    ctx.close()


# ── travel ──────────────────────────────────────────────────────────────────
def run_travel(eng, browser, base, w, h):
    tag = f"{eng} {w}px travel"
    ctx, pg, errs = new_page(browser, w, h, init=AUTH + FAKE_NOW)
    pg.goto(base + "/tools/travel.html")
    pg.wait_for_selector(".trip-card", timeout=15000)
    pg.evaluate("document.getElementById('viewer').hidden = false")
    esc_closed(tag + " стадия", pg, "document.getElementById('viewer').hidden", "окно стадии")
    pg.evaluate("document.getElementById('prof').hidden = false")
    esc_closed(tag + " профиль", pg, "document.getElementById('prof').hidden", "окно профиля")
    check(f"{tag}: ошибок JS нет {errs[:2]}", not errs)
    ctx.close()


# ── вьюер (нужен смонтированный Synology) ───────────────────────────────────
def run_viewer(eng, browser, url, w, h):
    tag = f"{eng} {w}px вьюер"
    ctx, pg, errs = new_page(browser, w, h)
    for attempt in range(3):
        pg.goto(url)
        pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
        try:
            pg.wait_for_function("() => !!document.querySelector('[data-ui-tab=\"positions\"]') && !!document.querySelector('[data-ui-tab=\"ie-model\"]')", timeout=15000)
            break
        except Exception:
            if attempt == 2:
                raise
    pg.wait_for_timeout(600)
    pg.add_style_tag(content=TALL)
    tabs = "(k) => { const b = document.querySelector('[data-ui-tab=\"' + k + '\"]'); if (!b) return false; b.click(); return true; }"
    cur = pg.evaluate("() => (document.querySelector('.ui-tabs [aria-current=\"page\"]') || {getAttribute: () => null}).getAttribute('data-ui-tab')")
    other = "ie-model" if cur != "ie-model" else "positions"
    for label, key in (("другая", other), ("текущая", other)):
        pg.evaluate("() => window.scrollTo(0, 1500)")
        pg.wait_for_timeout(150)
        y0 = pg.evaluate("window.scrollY")
        pg.evaluate("() => { window.__sv = []; window.addEventListener('scroll', () => window.__sv.push(Math.round(window.scrollY))); }")
        pg.evaluate(tabs, key)
        at_top(pg)
        y1, sv = pg.evaluate("window.scrollY"), pg.evaluate("window.__sv")
        check(f"{tag} {label} вкладка: scrollY == 0 ({y0} → {y1})", y0 > 300 and y1 == 0)
        check(f"{tag} {label} вкладка: мгновенно ({sv})", all(v in (y0, 0) for v in sv))
    # окно документа: Escape
    pg.evaluate("() => { document.getElementById('modal-title').textContent = 'Проверка'; uiShow(document.getElementById('modal-overlay')); }")
    pg.wait_for_timeout(300)
    esc_closed(tag + " документ", pg, "document.getElementById('modal-overlay').hasAttribute('hidden')", "окно документа")
    pg.evaluate("() => { uiShow(document.getElementById('modal-overlay')); }")
    pg.wait_for_timeout(300)
    pg.evaluate(tabs, "positions" if other != "positions" else "ie-model")
    try:
        pg.wait_for_function("document.getElementById('modal-overlay').hasAttribute('hidden')", timeout=3000)
        closed = True
    except Exception:
        closed = False
    check(f"{tag}: окно документа закрыто вкладкой, подтверждения нет", closed and pg.locator(".ui-confirm").count() == 0)
    check(f"{tag}: ошибок JS нет {errs[:2]}", not errs)
    ctx.close()


# ── читатель: «↑ В начало» ──────────────────────────────────────────────────
def run_reader(eng, browser, w, h):
    tag = f"{eng} {w}px читатель"
    ctx, pg, errs = new_page(browser, w, h)
    pg.goto(TOOLS + "games.html")
    settle(pg, "typeof uiReaderHTML === 'function'")
    md = "\n".join(f"## Глава {i}\n\n" + ("Длинный абзац, чтобы прокрутка была настоящей. " * 40) + "\n" for i in range(1, 7))
    pg.evaluate("""(md) => {
      document.body.innerHTML = '<div id="host" class="rd-host" style="width:' + Math.min(innerWidth - 20, 900) + 'px; height:600px;"></div>';
      const h = document.getElementById('host'); h.innerHTML = uiReaderHTML(md, {}); uiReaderMount(h); }""", md)
    pg.wait_for_timeout(300)
    pg.evaluate("document.getElementById('host').scrollTop = 1800")
    pg.wait_for_timeout(200)
    y0 = pg.evaluate("document.getElementById('host').scrollTop")
    pg.evaluate("() => { const h = document.getElementById('host'); window.__sv = []; h.addEventListener('scroll', () => window.__sv.push(Math.round(h.scrollTop))); }")
    clicked = pg.evaluate("() => { const b = [...document.querySelectorAll('[data-rd-top]')].find(e => e.offsetWidth > 0); if (!b) return false; b.click(); return true; }")
    at_top(pg, "document.getElementById('host').scrollTop")
    y1, sv = pg.evaluate("document.getElementById('host').scrollTop"), pg.evaluate("window.__sv")
    check(f"{tag}: кнопка «В начало» найдена", clicked)
    check(f"{tag}: «В начало» → 0 мгновенно ({y0} → {y1}, шаги {sv})", y0 > 500 and y1 == 0 and all(v in (y0, 0) for v in sv))
    ctx.close()


def run_engine(name, browser, travel_base, viewer_url):
    for w, h in ((1400, 900), (390, 844)):
        run_health(name, browser, w, h)
        run_food(name, browser, w, h)
        run_money(name, browser, w, h)
        run_games(name, browser, w, h)
        run_travel(name, browser, travel_base, w, h)
        run_reader(name, browser, w, h)
        if viewer_url:
            with SYNOLOGY_LOCK:   # вьюер — на настоящих данных Synology: движки по очереди
                run_viewer(name, browser, viewer_url, w, h)


tmp = Path(tempfile.mkdtemp())
try:
    make_root(tmp, TRIPS)
    tsrv, travel_base = serve(tmp)
    viewer_url = None
    if (MEM / "Portfolio" / "weekly-reviews").is_dir():
        _vsrv, _vbase = stand_serve(SEL["_VH"], key="viewer")
        viewer_url = _vbase + "/tools/portfolio-integrated-viewer.html"
    else:
        print("  вьюер: пропуск — Synology не смонтирован")
    # Chromium и WebKit — параллельно, браузер один на движок (_pages_stand)
    per_engine(lambda name, browser: run_engine(name, browser, travel_base, viewer_url))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"nav_top_esc: {check.passed} passed, {check.failed} failed")
sys.exit(1 if check.failed else 0)
