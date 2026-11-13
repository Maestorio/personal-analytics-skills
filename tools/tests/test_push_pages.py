#!/usr/bin/env python3
"""Уведомления кабинета в hub и на «Играх» (ui-kit 1.57.0–1.57.1, uiPushMount/uiPushOpen) — настоящими браузерами.

Раскладка (решение владельца 2026-10-26): hub — устройство, тихий режим, все виды по разделам;
страница раздела — свои виды и журнал (вьюер — tools/tests/test_viewer_push.py). Сервер (hub-notify)
подменён ответами на /api/push/*.

Что проверяется (Chromium и WebKit; компьютер 1280 и телефон 390):
  hub:   кнопка «Уведомления» в шапке; 403 → «Нужен вход»; 200 → тихий режим выбран, «Отправлять» шлёт
         POST mode=live; раскладка 1.57.1 — «Это устройство» | «Режим», ниже карточки разделов «Портфель» | «Игры»
         (на телефоне столбиком) со ссылками «журнал →» (вьюер #tab=notify,
         games.html#notify); «Выкл» → POST settings; «убрать все» → POST prune без keep; журнала нет;
         hub.html#notify открывает окно сразу; окно не шире экрана;
  games: кнопка открывает окно «Игры»: только виды игр, журнал запрошен со section=games, строка
         «это устройство» со ссылкой в hub; строка журнала с games.html#sale закрывает окно и включает
         «Присматриваюсь» + «Со скидкой» (на уже открытой странице — через hashchange);
         games.html#notify открывает окно сразу.
Запуск: python3 tools/tests/test_push_pages.py  (нужен playwright; нет движка — пропуск).
"""
import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote as _unq, urlparse as _up

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
    print("push_pages: пропуск — нет playwright")
    sys.exit(0)

WATCH = """schema_version: 1.0
updated: 2026-10-26
items:
  - title: "Undertale"
    status: хочу
    nsuid_us: "70010000009921"
    added: 2026-10-20
  - title: "Metaphor"
    status: хочу
    nsuid_us: "70010000105915"
    added: 2026-10-19
"""
PRICES = {"schema": "eshop-prices@1", "fetched_at": "2099-01-01T08:30:00+03:00", "attempt_at": None, "status": "ok",
          "error": None, "skipped": [], "items": [
              {"title": "Undertale", "nsuid_us": "70010000009921", "sales_status": "onsale", "regular_usd": 14.99,
               "sale_usd": 9.89, "discount_pct": 34, "sale_end": "2099-11-01T15:59:59Z", "price_usd": 9.89,
               "price_target_usd": None, "target_met": False},
              {"title": "Metaphor", "nsuid_us": "70010000105915", "sales_status": "onsale", "regular_usd": 39.99,
               "sale_usd": None, "discount_pct": None, "sale_end": None, "price_usd": 39.99,
               "price_target_usd": None, "target_met": False}]}
DATA = {"/Gaming/watchlist.yaml": WATCH.encode(), "/Gaming/eshop-prices.json": json.dumps(PRICES).encode()}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        p = _unq(_up(self.path).path)
        body, ct = None, "text/plain; charset=utf-8"
        if p in DATA:
            body = DATA[p]
        elif p.startswith("/tools/"):
            f = REPO / "tools" / p[len("/tools/"):]
            if f.is_file():
                body = f.read_bytes()
                ct = {".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css",
                      ".json": "application/json", ".woff2": "font/woff2", ".png": "image/png"}.get(f.suffix, ct)
        if body is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


srv = serve(Handler)[0]   # _pages_stand: очередь 128, keep-alive
BASE = f"http://127.0.0.1:{srv.server_address[1]}/tools/"

KINDS = [{"id": "verdict", "section": "portfolio", "label": "Смена вердикта", "desc": "в свежем обзоре"},
         {"id": "stale", "section": "portfolio", "label": "Просроченные отчёты", "desc": "утром"},
         {"id": "eshop", "section": "games", "label": "Цены игр", "desc": "порог выполнен"},
         {"id": "eshop_sale", "section": "games", "label": "Скидки на игры", "desc": "игра ушла в скидку"}]
SECTIONS = [{"id": "portfolio", "label": "Портфель", "url": "/tools/portfolio-integrated-viewer.html#tab=notify"},
            {"id": "games", "label": "Игры", "url": "/tools/games.html#notify"}]
STATUS = {"mode": "quiet", "off": ["stale"], "kinds": KINDS, "sections": SECTIONS, "subscribed": False,
          "devices": [{"label": "iPhone", "added": "2026-10-16T09:00:00+03:00"}],
          "last_daily": "2026-10-26", "last_hourly": "2026-10-26T12", "version": "1.7.0", "log": [
              {"ts": "2026-10-26T08:30:00+03:00", "status": "sent", "title": "Undertale −34%: $9.89 до 01.11",
               "body": "Скидка в US eShop · было $14.99.", "url": "/tools/games.html#sale", "key": "eshop-sale:1:x",
               "kind": "eshop_sale"}]}
OVL = ".uh-overlay .ui-push"
AHEAD = [{"id": "ahead_review", "section": "portfolio", "group": "ahead", "label": "Срок решения", "desc": "за 7 дней и в день срока"},
         {"id": "ahead_offer", "section": "portfolio", "group": "ahead", "label": "Оферта облигации", "desc": "за 14 и за 3 дня"}]
STATUS_AHEAD = dict(STATUS, kinds=KINDS + AHEAD)


def open_page(browser, width, url, pm):
    opts = {"is_mobile": True, "has_touch": True} if width < 500 else {}
    if browser.browser_type.name == "webkit":
        opts["service_workers"] = "block"
    ctx = browser.new_context(viewport={"width": width, "height": 900}, **opts)
    pg = ctx.new_page()
    errs, posts, gets = [], [], []
    pg.on("pageerror", lambda e: errs.append(str(e)))

    def push(route):
        rq = route.request
        if rq.method == "POST":
            posts.append((rq.url.rsplit("/", 1)[-1], json.loads(rq.post_data or "{}")))
            if rq.url.endswith("/mode"):
                pm["status"]["mode"] = posts[-1][1].get("mode")
            if rq.url.endswith("/settings"):
                pm["status"]["off"] = posts[-1][1].get("off")
            return route.fulfill(status=200, content_type="application/json", body='{"ok":true}')
        gets.append(rq.url)
        if pm["code"] != 200:
            return route.fulfill(status=pm["code"], content_type="application/json", body="{}")
        route.fulfill(status=200, content_type="application/json", body=json.dumps(pm["status"]))
    pg.route("**/api/push/**", push)
    pg.goto(url)
    pg.wait_for_selector("[data-ui-push]", timeout=15000)
    return ctx, pg, errs, posts, gets


def open_modal(pg):
    pg.evaluate("document.querySelectorAll('.uh-overlay').forEach(o => o.remove())")
    pg.click("[data-ui-push]")
    pg.wait_for_function(f"() => document.querySelector('{OVL} .ui-push-card')", timeout=8000)


def txt(pg):
    return pg.evaluate(f"() => (document.querySelector('{OVL}') || {{}}).textContent || ''")


def run(eng_name, eng):
    try:
        browser = eng.launch()
    except Exception as e:  # noqa: BLE001
        print(f"  {eng_name}: пропуск — {str(e).splitlines()[0][:80]}")
        return
    for w in (1280, 390):
        tag = f"{eng_name} {w}px"
        # ── hub ──
        pm = {"code": 403, "status": json.loads(json.dumps(STATUS))}
        ctx, pg, errs, posts, gets = open_page(browser, w, BASE + "hub.html", pm)
        check(f"{tag} hub: кнопка «Уведомления» в шапке", pg.get_attribute("[data-ui-push]", "data-ui-push") == "all")
        open_modal(pg)
        check(f"{tag} hub: 403 → «Нужен вход»", "Нужен вход" in txt(pg))
        pm["code"] = 200
        open_modal(pg)
        t = txt(pg)
        check(f"{tag} hub: устройства и последние проверки", "iPhone" in t and "утренняя 26.10" in t)
        mode_on = f"() => document.querySelector('{OVL} [data-push-act^=\"mode\"][aria-pressed=\"true\"]').textContent"
        check(f"{tag} hub: тихий режим выбран", pg.evaluate(mode_on) == "Тихий режим")
        secs = pg.evaluate(f"() => [...document.querySelectorAll('{OVL} [data-push-sec]')].map(s => s.querySelector('h2').textContent + '→' + s.querySelector('.ui-push-head a').getAttribute('href') + ':' + s.querySelectorAll('.ui-push-kind').length)")
        check(f"{tag} hub: раздел — своя карточка со ссылкой на журнал ({secs})",
              secs == ["Портфель→/tools/portfolio-integrated-viewer.html#tab=notify:2", "Игры→/tools/games.html#notify:2"])
        # раскладка 1.57.1: «Это устройство» | «Режим», ниже «Портфель» | «Игры»; на телефоне — столбиком
        box = pg.evaluate(f"""() => [...document.querySelectorAll('{OVL} .ui-push-card')].map(c => {{
            const r = c.getBoundingClientRect(); return [c.querySelector('h2').textContent, Math.round(r.left), Math.round(r.top), Math.round(r.bottom)]; }})""")
        names = [b[0] for b in box]
        check(f"{tag} hub: порядок карточек ({names})", names == ["Это устройство", "Режим", "Портфель", "Игры"])
        d, m, pf, gm = box
        if w >= 1000:
            check(f"{tag} hub: устройство и режим в одном ряду", d[2] == m[2] and m[1] > d[1])
            check(f"{tag} hub: портфель и игры в одном ряду ниже", pf[2] == gm[2] and gm[1] > pf[1] and pf[2] >= max(d[3], m[3]))
        else:
            check(f"{tag} hub: на телефоне столбиком", d[1] == m[1] == pf[1] == gm[1] and d[3] <= m[2] <= m[3] <= pf[2] <= pf[3] <= gm[2])
        check(f"{tag} hub: все четыре вида", len(pg.query_selector_all(f"{OVL} .ui-push-kind")) == 4)
        check(f"{tag} hub: журнала нет", "Журнал" not in t)
        if w < 500:
            sw = pg.evaluate("() => document.documentElement.scrollWidth")
            check(f"{tag} hub: окно не шире экрана ({sw})", sw <= w)
        pg.click(f"{OVL} [data-push-act='mode:live']")
        pg.wait_for_function(f"() => /Отправка включена/.test(document.querySelector('{OVL}').textContent)", timeout=8000)
        check(f"{tag} hub: «Отправлять» → POST mode=live", ("mode", {"mode": "live"}) in posts)
        pg.click(f"{OVL} [data-push-act='kind:eshop_sale:off']")
        pg.wait_for_function(f"() => document.querySelector(\"{OVL} [data-push-act='kind:eshop_sale:off']\")?.getAttribute('aria-pressed') === 'true'", timeout=8000)
        check(f"{tag} hub: «Выкл» — без плашки «… — выключено» сверху (виден переключатель)",
              "— выключено" not in pg.evaluate(f"() => document.querySelector('{OVL}').textContent"))
        check(f"{tag} hub: «Выкл» → POST settings", ("settings", {"off": ["stale", "eshop_sale"]}) in posts)
        pg.click(f"{OVL} .ui-push-prune")
        pg.wait_for_function(f"() => /Все устройства убраны/.test(document.querySelector('{OVL}').textContent)", timeout=8000)
        check(f"{tag} hub: «убрать все» → POST prune без keep", ("prune", {}) in posts)
        check(f"{tag} hub: без ошибок страницы {errs[:2]}", not errs)
        ctx.close()

        pm = {"code": 200, "status": json.loads(json.dumps(STATUS))}
        ctx, pg, errs, posts, gets = open_page(browser, w, BASE + "hub.html#notify", pm)
        pg.wait_for_function(f"() => document.querySelector('{OVL} .ui-push-card')", timeout=8000)
        check(f"{tag} hub: #notify открывает окно сразу, метка снята", "#" not in pg.url)
        ctx.close()

        # ── страница раздела «Портфель» с группой «Напоминать заранее» (как во вьюере): uiPushMount в свободном узле ──
        pm = {"code": 200, "status": json.loads(json.dumps(STATUS_AHEAD))}
        ctx, pg, errs, posts, gets = open_page(browser, w, BASE + "hub.html", pm)
        pg.evaluate("""() => { const d = document.createElement('div'); d.id = 'pfpush'; document.body.appendChild(d);
                               uiPushMount(d, { section: 'portfolio' }); }""")
        pg.wait_for_function("() => document.querySelector('#pfpush .ui-push-card')", timeout=8000)
        P = "#pfpush"
        box = pg.evaluate(f"""() => [...document.querySelectorAll('{P} .ui-push-card')].map(c => {{
            const r = c.getBoundingClientRect(); return [c.querySelector('h2').textContent, Math.round(r.left), Math.round(r.top), Math.round(r.bottom)]; }})""")
        base = pg.evaluate("() => Math.round(document.getElementById('pfpush').getBoundingClientRect().top)")
        names = [b[0] for b in box]
        check(f"{tag} раздел: карточки «Что присылать», «Это устройство», «Напоминать заранее», журнал ({names})",
              [n.split(" ·")[0] for n in names] == ["Что присылать", "Это устройство", "Напоминать заранее", "Журнал"])
        kd, dv, ah = box[0], box[1], box[2]
        kinds_of = lambda sec: pg.evaluate(f"() => [...document.querySelectorAll('{P} [data-push-fold=\"{sec}\"] .ui-push-kind-t')].map(e => e.textContent)")
        check(f"{tag} раздел: виды разложены по группам ({kinds_of('kinds')} / {kinds_of('ahead')})",
              kinds_of("kinds") == ["Смена вердикта", "Просроченные отчёты"] and kinds_of("ahead") == ["Срок решения", "Оферта облигации"])
        is_open = lambda sec: pg.evaluate(f"() => document.querySelector('{P} [data-push-fold-id=\"{sec}\"]').open")
        if w >= 1000:
            check(f"{tag} раздел: «Напоминать заранее» в правой колонке под «Этим устройством»",
                  ah[1] == dv[1] and ah[1] > kd[1] and ah[2] >= dv[3])
            check(f"{tag} раздел: на компьютере обе группы раскрыты, сгиб не нажимается", is_open("kinds") and is_open("ahead")
                  and pg.evaluate(f"() => getComputedStyle(document.querySelector('{P} [data-push-fold-id=\"ahead\"] > summary')).pointerEvents") == "none")
        else:
            check(f"{tag} раздел: на телефоне обе группы свёрнуты", not is_open("kinds") and not is_open("ahead"))
            jr = [b for b in box if b[0].startswith("Журнал")][0]
            check(f"{tag} раздел: журнал виден без долгой прокрутки (верх {jr[2] - base}px от начала блока)", jr[2] - base < 700)
            pg.click(f"{P} [data-push-fold-id='ahead'] > summary")
            pg.wait_for_function(f"() => document.querySelector('{P} [data-push-fold-id=\"ahead\"]').open")
            check(f"{tag} раздел: нажатие раскрывает группу, соседняя остаётся свёрнутой", is_open("ahead") and not is_open("kinds"))
            pg.click(f"{P} [data-push-act='kind:ahead_offer:off']")
            pg.wait_for_function(f"() => /Оферта облигации/.test(document.querySelector('{P}').textContent) && document.querySelector('{P} [data-push-act=\"kind:ahead_offer:off\"][aria-pressed=\"true\"]')", timeout=8000)
            check(f"{tag} раздел: переключатель вида — POST settings, после перерисовки группа осталась раскрытой",
                  ("settings", {"off": ["stale", "ahead_offer"]}) in posts and is_open("ahead") and not is_open("kinds"))
            sw = pg.evaluate("() => document.documentElement.scrollWidth")
            check(f"{tag} раздел: не шире экрана ({sw})", sw <= w)
        check(f"{tag} раздел: без ошибок страницы {errs[:2]}", not errs)
        ctx.close()

        # ── games ──
        pm = {"code": 200, "status": json.loads(json.dumps(STATUS))}
        ctx, pg, errs, posts, gets = open_page(browser, w, BASE + "games.html", pm)
        pg.wait_for_function("document.querySelectorAll('.sc-watch .w-price').length >= 1", timeout=15000)
        open_modal(pg)
        t = txt(pg)
        kinds = pg.evaluate(f"() => [...document.querySelectorAll('{OVL} .ui-push-kind-t')].map(e => e.textContent)")
        check(f"{tag} games: окно «Игры», только виды игр ({kinds})",
              pg.evaluate("document.querySelector('.uh-overlay .uh-title').textContent") == "Игры"
              and kinds == ["Цены игр", "Скидки на игры"])
        gopen = pg.evaluate(f"() => [...document.querySelectorAll('{OVL} [data-push-fold-id]')].map(d => d.getAttribute('data-push-fold-id') + ':' + d.open)")
        check(f"{tag} games: группы «заранее» нет; «Что присылать» {'раскрыта' if w >= 1000 else 'свёрнута на телефоне'} ({gopen})",
              gopen == ["kinds:" + ("true" if w >= 1000 else "false")]
              and "Напоминать заранее" not in t)
        check(f"{tag} games: журнал запрошен со section=games", any("section=games" in u for u in gets))
        check(f"{tag} games: журнал и ссылка в hub", "Undertale −34%" in t
              and pg.evaluate(f"document.querySelector('{OVL} .ui-push-hub').getAttribute('href')") == "hub.html#notify")
        if w < 500:
            sw = pg.evaluate("() => document.documentElement.scrollWidth")
            check(f"{tag} games: окно не шире экрана ({sw})", sw <= w)
        pg.click(f"{OVL} .ui-push-log-row.pick")
        pg.wait_for_function("() => !document.querySelector('.uh-overlay:not(.leave)') && document.body.getAttribute('data-screen') === 'watch'",
                             timeout=8000)
        titles = pg.evaluate("() => [...document.querySelectorAll('.sc-watch .wcard .gt')].map(e => e.textContent)")
        check(f"{tag} games: строка журнала → «Присматриваюсь», только со скидкой ({titles})",
              titles == ["Undertale"] and "on" in pg.get_attribute("#w-sale-chip", "class"))
        check(f"{tag} games: без ошибок страницы {errs[:2]}", not errs)
        ctx.close()

        ctx, pg, errs, posts, gets = open_page(browser, w, BASE + "games.html#notify", pm)
        pg.wait_for_function(f"() => document.querySelector('{OVL} .ui-push-card')", timeout=8000)
        check(f"{tag} games: #notify открывает окно сразу", "Игры" in pg.evaluate("document.querySelector('.uh-overlay .uh-title').textContent"))
        ctx.close()
    browser.close()


with sync_playwright() as p:
    run("chromium", p.chromium)
    run("webkit", p.webkit)
srv.shutdown()
print(f"push_pages: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
