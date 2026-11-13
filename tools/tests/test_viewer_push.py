#!/usr/bin/env python3
"""Push-уведомления во вьюере портфеля (v3.36.0, v3-B) — прогон настоящими браузерами (Chromium, WebKit).

Сервер уведомлений (hub-notify) подменён ответами на /api/push/*; сама отправка push в браузере
без push-сервиса не проверяема — её держит tools/tests/test_notifier.py (шифрование, VAPID).

Что проверяется (компьютер 1280 и телефон 390):
  1. в http-режиме есть кнопка «Уведомления» — ведёт в раздел «Ещё → Уведомления»; фоновый скрипт
     регистрируется на вьюер (Chromium);
  2. раздел (с v3.54.0 — общий блок ui-kit uiPushMount, раздел «portfolio»): 403 → «Нужен вход»;
     502 → «не отвечает … hub-notify»; 200 → журнал со статусами по-русски (запрос со section=portfolio),
     строка «это устройство» со ссылкой в hub; сверху одна фраза, правила — в «Как это работает» внизу;
     на компьютере две колонки, на телефоне одна; метки цен в разделе нет; режима и «убрать все» здесь
     нет — они в hub (tools/tests/test_push_pages.py);
  3. «Что присылать»: только виды портфеля (вид игр с сервера не показан), «Выкл» у вида шлёт
     POST /api/push/settings {off: [...]} со свежим с сервера списком;
  4. строка журнала с #card=ТИКЕР открывает карточку бумаги;
  5. ссылка из уведомления: адрес с #card=ТИКЕР открывает карточку, #tab=actions — раздел
     «Действия»; метка снимается из адреса; сообщение фонового скрипта «piv-open» тоже открывает карточку;
  6. раздел не шире экрана на телефоне; ошибок страницы нет;
  7. «Обновить» вьюера (v3.39.0, Chromium 1280): полная перезагрузка в тот же раздел. С v3.46.0 метки
     в адресах нет ни до, ни после «Обновить» (свежесть — cache: no-cache и сверка листингов с копией
     на устройстве, см. test_viewer_fast_load.py), старая метка piv-cb стирается.

Данные — фикстуры tools/tests/fixtures/viewer-live (как у test_viewer_live_prices.py). Сеть не нужна.
Запуск: python3 tools/tests/test_viewer_push.py  (нужен playwright; нет движка — пропуск).
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
    print("viewer_push: пропуск — нет playwright")
    sys.exit(0)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

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
                  ".json": "application/json", ".woff2": "font/woff2", ".png": "image/png"}.get(f.suffix, "text/plain; charset=utf-8")
        else:
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
URL = f"http://127.0.0.1:{srv.server_address[1]}/tools/portfolio-integrated-viewer.html"

KINDS = [{"id": "cond_date", "section": "portfolio", "label": "Условия по дате", "desc": "дата, срок, вышел отчёт"},
         {"id": "verdict", "section": "portfolio", "label": "Смена вердикта", "desc": "в свежем обзоре"},
         {"id": "stale", "section": "portfolio", "label": "Просроченные отчёты", "desc": "отдельным уведомлением утром"},
         {"id": "eshop_sale", "section": "games", "label": "Скидки на игры", "desc": "игра ушла в скидку"}]
STATUS = {"mode": "quiet", "off": ["stale"], "kinds": KINDS, "subscribed": False, "devices": [{"label": "iPhone", "added": "2026-10-16T09:00:00+03:00"}],
          "last_daily": "2026-10-16", "last_hourly": "2026-10-16T12", "version": "1.0.0", "log": [
              {"ts": "2026-10-16T08:30:00+03:00", "status": "quiet", "title": "SBER: вердикт HOLD → TRIM",
               "body": "обзор акций 08.10", "url": "/tools/portfolio-integrated-viewer.html#card=SBER", "key": "verdict:stock:SBER:2026-10-08"},
              {"ts": "2026-10-16T09:00:00+03:00", "status": "off", "title": "Просрочен отчёт: макро-снимок от 08.10 (8 дн.)",
               "body": "пора обновить", "url": "/tools/portfolio-integrated-viewer.html#tab=today", "key": "stale-run:2026-10-16"},
              {"ts": "2026-10-16T08:30:00+03:00", "status": "suppressed", "title": "Монитор: 1 новое важное предупреждение",
               "body": "рубль за порогом", "url": "/tools/portfolio-integrated-viewer.html#tab=actions", "key": "monitor:2026-10-08"}]}
CARD_OPEN = "() => document.querySelectorAll('#card-layer .ui-modal').length"
CARD_TICKER = "() => (document.querySelector('#card-layer .ui-modal:last-child') || {}).textContent || ''"
TAB_TXT = "() => document.getElementById('modal-title').textContent === 'Уведомления' ? document.getElementById('modal-body').textContent : ''"


def open_page(browser, width, push_mode, url=URL):
    opts = {"is_mobile": True, "has_touch": True} if width < 500 else {}
    # WebKit Playwright не видит запросов страницы, которой управляет фоновый скрипт, — там он выключен
    # (регистрацию проверяет Chromium; в WebKit Playwright нет PushManager — окно говорит «не умеет»)
    if browser.browser_type.name == "webkit":
        opts["service_workers"] = "block"
    ctx = browser.new_context(viewport={"width": width, "height": 900}, **opts)
    pg = ctx.new_page()
    errs, posts, gets = [], [], []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, content_type="application/json", body="{}"))

    def push(route):
        rq = route.request
        if rq.method == "POST":
            posts.append((rq.url.rsplit("/", 1)[-1], json.loads(rq.post_data or "{}")))
            if rq.url.endswith("/mode"):
                push_mode["status"]["mode"] = posts[-1][1].get("mode")
            if rq.url.endswith("/settings"):
                push_mode["status"]["off"] = posts[-1][1].get("off")
            return route.fulfill(status=200, content_type="application/json", body='{"ok":true}')
        gets.append(rq.url)
        if push_mode["code"] != 200:
            return route.fulfill(status=push_mode["code"], content_type="application/json", body="{}")
        route.fulfill(status=200, content_type="application/json", body=json.dumps(push_mode["status"]))
    pg.route("**/api/push/**", push)
    pg.goto(url)
    pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
    pg.wait_for_timeout(300)
    pg.gets = gets
    return ctx, pg, errs, posts


def open_tab(pg):
    pg.evaluate("goToTab('today')")
    pg.evaluate("document.getElementById('modal-overlay').hidden || closeModal()")
    pg.wait_for_function("() => document.getElementById('modal-overlay').hidden", timeout=4000)
    pg.click("#btn-notify")
    pg.wait_for_function("() => !document.getElementById('modal-overlay').hidden && document.querySelectorAll('#modal-body .push-box .ui-push-card').length", timeout=8000)


def run(eng_name, eng):
    try:
        browser = eng.launch()
    except Exception as e:
        print(f"  {eng_name}: пропуск — {str(e).splitlines()[0][:80]}")
        return
    for w in (1280, 390):
        tag = f"{eng_name} {w}px"
        pm = {"code": 403, "status": json.loads(json.dumps(STATUS))}
        ctx, pg, errs, posts = open_page(browser, w, pm)
        check(f"{tag}: кнопка «Уведомления» видна", pg.is_visible("#btn-notify"))
        if eng_name == "chromium":
            scope = pg.evaluate("async () => { const r = await navigator.serviceWorker.getRegistration('./portfolio-integrated-viewer.html'); return r ? r.scope : ''; }")
            check(f"{tag}: фоновый скрипт зарегистрирован на вьюер ({scope})", scope.endswith("/tools/portfolio-integrated-viewer.html"))
        open_tab(pg)
        check(f"{tag}: «Уведомления» — окно поверх страницы, раздел под ним не сменился", pg.evaluate("state.currentTab") == "today")
        check(f"{tag}: 403 → «Нужен вход»", "Нужен вход" in pg.evaluate(TAB_TXT))
        pm["code"] = 502
        open_tab(pg)
        check(f"{tag}: 502 → сервер не отвечает, назван hub-notify", "hub-notify" in pg.evaluate(TAB_TXT))
        pm["code"] = 200
        open_tab(pg)
        t = pg.evaluate(TAB_TXT)
        check(f"{tag}: журнал со статусами по-русски",
              "тихий режим — не отправлено" in t and "пропущено — такое уже было за неделю" in t
              and "выключено в настройках" in t and "SBER: вердикт HOLD → TRIM" in t)
        check(f"{tag}: журнал — только портфеля (section=portfolio)", any("section=portfolio" in u for u in pg.gets))
        check(f"{tag}: это устройство — строкой, устройства и режим — ссылкой в hub",
              "iPhone" in t and "тихий — только в журнал" in t
              and pg.evaluate("document.querySelector('.ui-push-hub').getAttribute('href')") == "hub.html#notify")
        check(f"{tag}: режима и «убрать все» во вьюере больше нет",
              pg.evaluate("!document.querySelector('.push-box [data-push-act^=\"mode\"], .push-box .ui-push-prune')"))
        check(f"{tag}: сверху одна фраза, расписание — в «Как это работает» последним блоком",
              len(pg.evaluate("document.querySelector('.ui-push-lead').textContent")) < 120
              and pg.evaluate("document.querySelector('.push-box').lastElementChild.classList.contains('push-how')"))
        check(f"{tag}: метки цен MOEX в разделе нет", pg.evaluate("!document.querySelector('#modal-body #live-src')"))
        cols = pg.evaluate("() => { const c = [...document.querySelectorAll('.ui-push-col')].map(e => Math.round(e.getBoundingClientRect().top)); return c; }")
        check(f"{tag}: {'две колонки рядом' if w > 860 else 'одна колонка'} ({cols})",
              (len(cols) == 2 and cols[0] == cols[1]) if w > 860 else (len(cols) == 2 and cols[0] < cols[1]))
        if w > 860:
            bot = pg.evaluate("() => [...document.querySelectorAll('.ui-push-col')].map(c => Math.round(c.lastElementChild.getBoundingClientRect().bottom))")
            check(f"{tag}: низы колонок вровень ({bot})", abs(bot[0] - bot[1]) <= 1)
        kinds = pg.evaluate("() => [...document.querySelectorAll('.ui-push-kind')].map(k => k.querySelector('.ui-push-kind-t').textContent + ':' + k.querySelector('.ui-seg-btn[aria-pressed=\"true\"]').textContent)")
        check(f"{tag}: виды портфеля с сервера (игр нет), просрочки выключены ({kinds})",
              kinds == ["Условия по дате:Вкл", "Смена вердикта:Вкл", "Просроченные отчёты:Выкл"])
        if w < 500:
            pg.wait_for_timeout(500)
            sw = pg.evaluate("() => document.documentElement.scrollWidth")
            check(f"{tag}: раздел не шире экрана ({sw})", sw <= w)
        if w <= 860:   # на узком экране «Что присылать» свёрнуто — раскрыть нажатием
            check(f"{tag}: «Что присылать» на телефоне свёрнуто", not pg.evaluate("document.querySelector('[data-push-fold-id=\"kinds\"]').open"))
            pg.click("[data-push-fold-id='kinds'] > summary")
        pg.click(".ui-push-kind:nth-of-type(2) .ui-seg-btn:has-text('Выкл')")
        pg.wait_for_function("() => document.querySelector(\".ui-push-kind:nth-of-type(2) [data-push-act$=':off']\")?.getAttribute('aria-pressed') === 'true'", timeout=8000)
        check(f"{tag}: «Выкл» — без плашки «… — выключено» сверху", "— выключено" not in pg.evaluate("document.getElementById('modal-body').textContent"))
        check(f"{tag}: «Выкл» у вида → POST settings со всем списком выключенных",
              ("settings", {"off": ["stale", "verdict"]}) in posts)
        pg.click(".ui-push-log-row.pick >> nth=0")
        pg.wait_for_function(CARD_OPEN, timeout=8000)
        check(f"{tag}: строка журнала → карточка SBER открыта", "SBER" in pg.evaluate(CARD_TICKER))
        check(f"{tag}: окно уведомлений под карточкой осталось", not pg.evaluate("document.getElementById('modal-overlay').hidden"))
        pg.keyboard.press("Escape")
        pg.wait_for_function("() => document.querySelectorAll('#card-layer .ui-modal').length === 0", timeout=8000)
        check(f"{tag}: Esc закрыл карточку, уведомления и раздел под ними на месте",
              not pg.evaluate("document.getElementById('modal-overlay').hidden") and pg.evaluate("state.currentTab") == "today")
        # монитор из журнала — отдельное окно ПОВЕРХ уведомлений (журнал не перерисовывается), прогноз из него — ещё одно поверх;
        # Esc снимает по одному, журнал возвращается тем же узлом
        pg.evaluate("""() => {
          state.data.monitorReport = { date: '2026-11-10', parsed: { alerts: [{ severity: 'HIGH', target: 'ZZ-test', category: 'factor_breach', message: 'тест' }] } };
          window.__nbox = document.querySelector('#modal-body .push-box');
          openFromNotify('/tools/portfolio-integrated-viewer.html#tab=actions&new=ZZ-test');
        }""")
        pg.wait_for_function("() => document.getElementById('modal-title').textContent.startsWith('Новые предупреждения')", timeout=8000)
        z1 = pg.evaluate("() => [...document.querySelectorAll('.modal-overlay')].map(o => [o.hidden, +o.dataset.z || 300])")
        check(f"{tag}: монитор — отдельное окно поверх журнала ({z1})", len(z1) == 2 and not z1[0][0] and z1[1][1] > z1[0][1])
        cls = pg.evaluate("() => [...document.querySelectorAll('.modal-overlay')].map(o => o.className)")
        check(f"{tag}: стопка ui-kit — журнал позади (.behind), монитор со светлым затемнением (.stacked) ({cls})",
              "behind" in cls[0] and "stacked" not in cls[0] and "stacked" in cls[1] and "behind" not in cls[1])
        check(f"{tag}: у монитора из журнала нет «← К уведомлениям» и «Нажми «показать»» (есть ✕)",
              "К уведомлениям" not in pg.evaluate("$('#modal-body').textContent") and "показать" not in pg.evaluate("$('#modal-body').textContent"))
        pg.evaluate("() => { docOpen({ over: true }); $('#modal-title').textContent = 'прогноз-тест'; uiShow($('#modal-overlay')); }")
        check(f"{tag}: прогноз — третье окно, предыдущие не закрыты", pg.evaluate("document.querySelectorAll('.modal-overlay').length") == 3)
        pg.keyboard.press("Escape")
        pg.wait_for_function("() => document.querySelectorAll('.modal-overlay').length === 2 && document.getElementById('modal-title').textContent.startsWith('Новые предупреждения')", timeout=8000)
        pg.keyboard.press("Escape")
        pg.wait_for_function("() => document.querySelectorAll('.modal-overlay').length === 1 && document.getElementById('modal-title').textContent === 'Уведомления'", timeout=8000)
        check(f"{tag}: Esc по одному слою, журнал вернулся тем же узлом, раздел под ним не менялся",
              pg.evaluate("window.__nbox === document.querySelector('#modal-body .push-box')") and pg.evaluate("state.currentTab") == "today")
        got = pg.evaluate("""() => { const f = window.openFromNotify; let got = null; window.openFromNotify = (u, i) => { got = i && i.key; };
          document.querySelector('#modal-body [data-push-url][data-push-key]').click(); window.openFromNotify = f; return got; }""")
        check(f"{tag}: ui-kit отдаёт ключ строки журнала в onOpen ({got})", bool(got))
        # «условие сработало» (ключ события cond:<id>@<версия>:fired, адрес #tab=actions) — карточка бумаги условия поверх журнала
        pg.evaluate("""() => { window.__cd = condDefsAll; window.condDefsAll = () => [{ id: 'zz-cond', version: 2, key: 'SBER' }];
          openFromNotify('/tools/portfolio-integrated-viewer.html#tab=actions', { key: 'cond:zz-cond@2:fired' }); window.condDefsAll = window.__cd; }""")
        pg.wait_for_function(CARD_OPEN, timeout=8000)
        check(f"{tag}: «условие сработало» → карточка SBER поверх журнала, раздел не сменился",
              "SBER" in pg.evaluate(CARD_TICKER) and not pg.evaluate("document.getElementById('modal-overlay').hidden") and pg.evaluate("state.currentTab") == "today")
        pg.keyboard.press("Escape")
        pg.wait_for_function("() => document.querySelectorAll('#card-layer .ui-modal').length === 0", timeout=8000)
        # «Решения»: после выбора типа полоска чипов остаётся там, где её прокрутили (раньше окно перерисовывалось и полоска уезжала в начало)
        pg.evaluate("closeModal()")
        pg.wait_for_function("() => document.getElementById('modal-overlay').hidden", timeout=4000)
        # в фикстурах решений нет — подставляем бумаги со статусами, чтобы в полоске было несколько типов
        pg.evaluate("""() => {
          const st = Object.keys(GATE_STATUS_META);
          window.decisionKeysAll = () => st.map((_, i) => 'ZZ' + i);
          window.gateOf = (k) => ({ status: st[+k.slice(2)], blocking: +k.slice(2) % 2 === 0 });
          window.lwCard = () => null;
          showGateLegendModal('');
        }""")
        pg.add_style_tag(content=".dec-filter{max-width:150px;overflow-x:auto;flex-wrap:nowrap}.dec-filter .ui-seg-btn{flex:none}")
        n = pg.evaluate("document.querySelectorAll('.dec-filter .ui-seg-btn').length")
        if n >= 2:
            pg.evaluate("() => { const f = document.querySelector('.dec-filter'); f.scrollLeft = 40; }")
            sx = pg.evaluate("document.querySelector('.dec-filter').scrollLeft")
            pg.evaluate("() => document.querySelector('.dec-filter .ui-seg-btn:last-child').click()")
            check(f"{tag}: полоска типов решений не прокручивается назад после выбора ({sx})",
                  sx > 0 and abs(pg.evaluate("document.querySelector('.dec-filter').scrollLeft") - sx) <= 1)
        check(f"{tag}: без ошибок страницы {errs[:2]}", not errs)
        ctx.close()

        # ссылка из уведомления при открытии
        ctx, pg, errs, _ = open_page(browser, w, pm, URL + "#card=SBER")
        pg.wait_for_function(CARD_OPEN, timeout=8000)
        check(f"{tag}: #card=SBER при открытии → карточка", "SBER" in pg.evaluate(CARD_TICKER))
        check(f"{tag}: метка снята из адреса", "#" not in pg.url)
        pg.evaluate("() => { document.querySelectorAll('#card-layer .ui-modal').forEach(m => m.remove()); cardStack.length = 0; }")
        pg.evaluate("location.hash = 'tab=actions'")
        pg.wait_for_function("() => state.currentTab === 'actions'", timeout=8000)
        check(f"{tag}: #tab=actions → раздел «Действия»", pg.evaluate("state.currentTab") == "actions")
        if eng_name == "chromium":
            pg.evaluate("() => navigator.serviceWorker.dispatchEvent(new MessageEvent('message', { data: { type: 'piv-open', url: '/tools/portfolio-integrated-viewer.html#card=SBER' } }))")
            pg.wait_for_function(CARD_OPEN, timeout=8000)
            check(f"{tag}: сообщение фонового скрипта открывает карточку", "SBER" in pg.evaluate(CARD_TICKER))
        check(f"{tag}: без ошибок страницы (ссылки) {errs[:2]}", not errs)
        ctx.close()
    browser.close()


def run_refresh(eng):
    browser = eng.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    reqs, errs = [], []
    pg.on("request", lambda r: reqs.append(r.url))
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, content_type="application/json", body="{}"))
    pg.goto(URL)
    pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
    data = lambda: [u for u in reqs if "/Portfolio/" in u]  # noqa: E731
    check("обновить: до «Обновить» данные без метки в адресе", data() and not any("_=" in u for u in data()))
    pg.evaluate("localStorage.setItem('piv-cb', '123')")       # метка от прежней версии вьюера
    pg.evaluate("goToTab('diff')")
    reqs.clear()
    with pg.expect_navigation():
        pg.click("#btn-refresh")
    pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
    check("обновить: старая метка piv-cb стёрта", pg.evaluate("localStorage.getItem('piv-cb')") is None)
    check("обновить: снова раздел «Изменения»", pg.evaluate("state.currentTab") == "diff")
    check(f"обновить: данные и листинги снова запрошены, без метки в адресе ({len(data())})",
          data() and not any("_=" in u for u in data()))
    check(f"обновить: без ошибок страницы {errs[:2]}", not errs)
    browser.close()


with sync_playwright() as p:
    run_refresh(p.chromium)
    run("chromium", p.chromium)
    run("webkit", p.webkit)

print(f"\nviewer_push: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
