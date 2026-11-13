#!/usr/bin/env python3
"""Вьюер 3.115.0 → шаг 12: пакет условий на строках модуля (а) — «Чего ждём» у фонда, отчёт-источник условия, кнопки владельца — настоящий Chromium.

Фикстура — живые файлы, переведённые в формат 2: conditions@2 + conditions-state (TMON и X5 закрыты задачей сайта по решению —
событие done by site с data.decision_id), решения decisions/ (TMON 28.10 по отчёту «Парковка кэша», X5 29.10 по разбору МСФО),
отчёты report@1 28.10, 23.10, 29.10; обзор акций 28.10, снапшот и обзоры viewer-live.
Контракты:
  1. Карточка фонда TMON: условие закрыто — «Чего ждём» нет.
  2. Вариант «сработало, не закрыто» (событие done убрано): «Чего ждём» есть, метка «сработало», кнопки «сделал / отложить до /
     не актуально», «открыть заново» у датного условия нет — подсказки нет, пока условие не закрыто.
  3. Окно закрытого TMON: «решено: отчёт 28.10» (решение из data.decision_id → source.doc) открывает «Парковка кэша…»;
     у датного закрытого — подсказка «перенести срок — через разбор» вместо «открыть заново».
  4. Карточка YDEX: «создано 23.10 · разбор бумаги» одной ссылкой на отчёт (source.doc определения), «решено» нет.
  5. Окно условия: у закрытого X5 — «решено: отчёт 29.10»; у NVTK (ждёт отчёта) — строки источника нет, из кнопок
     владельца — только «вышел» (R32).
  6. «Вышел» в «Чего ждём» карточки NVTK: POST api/pv/cond/event {event_found, version} → строка пересчитана модулем (а):
     «сработало», кнопки «сделал / отложить до / не актуально».
  7. Ошибок страницы нет.
  8. Условия-напоминания владельца с сайта (задача 2.4 «без ИИ», POST /api/pf/condition подменён): форма «Новое условие» на «Действиях»
     (1280 и 390: без горизонтальной прокрутки), кнопка «＋ Напоминание» в карточке бумаги с предзаполненным тикером, бумага ВНЕ портфеля
     (ZZZZ): условие видно в «Всех условиях», карточка открывается как кандидат и показывает «сейчас X · ещё ±N %» по живой котировке
     (livePriceOf берёт её из state.live.quotes.items), «снять» — только у условий владельца, ошибки сервера (409/400/сеть) — текстом.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_conditions_pack.py
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
    print("viewer_conditions_pack: пропуск — нет playwright")
    sys.exit(0)

sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as hub_api  # noqa: E402

FIX = Path(tempfile.mkdtemp(prefix="condpack-"))


def build(tmon_fired=False):
    shutil.rmtree(FIX, ignore_errors=True)
    fx = REPO / "tools/tests/fixtures"
    shutil.copytree(fx / "viewer-live", FIX)
    shutil.copytree(fx / "superseded", FIX, dirs_exist_ok=True)
    shutil.copytree(fx / "conditions-pack", FIX, dirs_exist_ok=True)
    (FIX / "monitor-reports").mkdir()
    if tmon_fired:   # закрытие убрано — условие сработало и ждёт владельца
        f = FIX / "Portfolio/conditions-state.json"
        st = json.loads(f.read_text(encoding="utf-8"))
        st["events"] = [e for e in st["events"] if not (e["condition_id"] == "tmon-date-3110" and e["event"] == "done")]
        f.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


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

CLIP = "() => { window.__clip = []; Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: (t) => { window.__clip.push(t); return Promise.resolve(); } } }); }"


def open_page(p, tab):
    browser = p.chromium.launch()
    ctx = browser.new_context(service_workers="block", viewport={"width": 1400, "height": 1000})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "502" not in m.text and "404" not in m.text else None)
    pg.route("**/api/pv/plan*", lambda r: r.fulfill(status=502, body="{}"))
    pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, body="{}"))
    pg.add_init_script(f"({CLIP})()")
    pg.goto(URL)
    pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
    pg.wait_for_function("() => state.data && state.data.portfolioLatest && state.data.weeklyReviewCurrent && state.data.conditions && state.data.conditionsState && (state.data.advisorReports || []).length >= 3", timeout=20000)
    pg.evaluate(f"() => {{ goToTab('{tab}'); }}")
    pg.wait_for_timeout(600)
    return browser, pg, errs


def open_row(pg, table_sel, ticker):
    pg.locator(f"{table_sel} tr.pick", has_text=ticker).first.click()
    pg.wait_for_selector("#card-layer .card-pane", timeout=8000)
    pg.wait_for_timeout(300)


def main():
    with sync_playwright() as p:
        try:
            p.chromium.launch().close()
        except Exception as e:
            print(f"viewer_conditions_pack: пропуск — {str(e).splitlines()[0][:80]}")
            return

        # 1: живой вариант — условие TMON закрыто, блока у фонда нет
        build()
        browser, pg, errs = open_page(p, "funds")
        open_row(pg, "#funds-table", "TMON")
        check("закрытое условие TMON: «Чего ждём» в карточке фонда нет", pg.locator("#card-layer .card-wait").count() == 0)

        def modal(cid):
            pg.evaluate("(id) => { cardStack.length = 0; renderCards(); showConditionModal(dsCondRows().find(c => c.id === id)); }", cid)
            pg.wait_for_timeout(300)
            return pg.locator("#modal-body")
        m = modal("tmon-date-3110")
        done = m.locator(".cond-src-done")
        check(f"окно закрытого TMON: «решено: отчёт 28.10» ({done.first.text_content() if done.count() else None!r})",
              done.count() == 1 and done.first.text_content().strip() == "решено: отчёт 28.10")
        check("окно закрытого датного TMON: подсказка «перенести срок — через разбор», кнопки «открыть заново» нет",
              m.locator(".cond-reopen-hint").count() == 1 and m.locator('[data-cond-act="reopened"]').count() == 0)
        done.first.click()
        pg.wait_for_function("() => /Парковка кэша/.test(document.querySelector('#modal-title').textContent)", timeout=5000)
        check("клик по «решено» открывает отчёт «Парковка кэша…»", True)
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # 2: вариант «сработало, не закрыто»
        build(tmon_fired=True)
        browser, pg, errs = open_page(p, "funds")
        open_row(pg, "#funds-table", "TMON")
        check("карточка фонда TMON: блок «Чего ждём» есть", pg.locator("#card-layer .card-wait .card-cond").count() == 1)
        badge = pg.locator("#card-layer .card-wait .cond-badge").first.text_content()
        check(f"метка «сработало» ({badge!r})", badge.startswith("сработало"))
        btns = pg.evaluate("() => [...document.querySelectorAll('#card-layer .card-wait .cond-owner .ui-btn')].map(b => b.textContent)")
        check(f"кнопки владельца у датного сработавшего — «сделал / отложить до / не актуально», без «открыть заново» ({btns})",
              btns == ["сделал", "отложить до", "не актуально"])
        check("источник «создано» у TMON нет (условие из миграции)", pg.locator("#card-layer .card-wait .cond-src-made").count() == 0)
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # 3: YDEX — «создано: разбор 23.10»
        build()
        browser, pg, errs = open_page(p, "positions")
        open_row(pg, "#content table", "YDEX")
        made = pg.locator("#card-layer .card-wait .cond-src-made")
        check(f"YDEX: «создано 23.10 · разбор бумаги» — одна ссылка на отчёт (R27, F7: без второй строки «создано: разбор») ({made.first.text_content() if made.count() else None!r})",
              made.count() == 1 and made.first.text_content().strip().startswith("создано 23.10 · ")
              and pg.locator("#card-layer .card-wait .card-cond .cond-made").count() == 1)
        check("YDEX: «решено» нет", pg.locator("#card-layer .card-wait .cond-src-done").count() == 0)
        check(f"ошибок страницы нет ({errs[:2]})", not errs)

        # 4: окно условия
        def modal2(cid):
            pg.evaluate("(id) => { cardStack.length = 0; renderCards(); showConditionModal(dsCondRows().find(c => c.id === id)); }", cid)
            pg.wait_for_timeout(300)
            return pg.locator("#modal-body")
        m = modal2("x5-ifrs3q-review")
        check("окно закрытого X5: «решено: отчёт 29.10»", m.locator(".cond-src-done").count() == 1 and m.locator(".cond-src-done").first.text_content().strip() == "решено: отчёт 29.10")
        m = modal2("nvtk-sellgate")
        check("окно условия без отчёта (NVTK): строки источника нет", m.locator(".cond-src-made, .cond-src-done").count() == 0)
        acts = pg.evaluate("() => [...document.querySelectorAll('#modal-body .cond-owner .ui-btn')].map(b => b.dataset.condAct + ':' + b.textContent)")
        check(f"окно ждущего NVTK («вышел отчёт»): из кнопок владельца — только «вышел» (R32) ({acts})", acts == ["found:вышел"])
        m = modal2("ydex-q3-ifrs-guidance")
        check("окно YDEX: «создано: разбор 23.10»", m.locator(".cond-src-made").count() == 1)
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # 5 (R32): кнопка «вышел» у ждущего «вышел отчёт» в «Чего ждём» карточки → POST event_found → «сработало · ждёт владельца»
        build()
        browser, pg, errs = open_page(p, "positions")
        posted = []

        def cond_event(route):
            body = json.loads(route.request.post_data or "{}")
            posted.append(body)
            ev = {"condition_id": body["condition_id"], "version": body.get("version"), "event": body["event"],
                  "at": pg.evaluate("() => _mskIso(Date.now())"), "by": "owner", "data": body.get("data") or {}}
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"event": ev, "events": 1}))
        pg.route("**/api/pv/cond/event", cond_event)
        open_row(pg, "#content table", "NVTK")
        cond = pg.locator('#card-layer .card-wait .card-cond[data-cond="nvtk-sellgate"]')
        check("NVTK: условие ждёт, у него кнопка «вышел»",
              cond.get_attribute("data-cond-status") == "pending" and cond.locator('[data-cond-act="found"]').count() == 1)
        cond.locator('[data-cond-act="found"]').click()
        pg.wait_for_function("() => document.querySelector('#card-layer .card-wait .card-cond[data-cond=\"nvtk-sellgate\"]')?.dataset.condStatus === 'fired'", timeout=5000)
        check(f"POST api/pv/cond/event: event_found, условие и версия ({posted})",
              len(posted) == 1 and posted[0]["event"] == "event_found" and posted[0]["condition_id"] == "nvtk-sellgate"
              and isinstance(posted[0].get("version"), int))
        cond = pg.locator('#card-layer .card-wait .card-cond[data-cond="nvtk-sellgate"]')
        badge = cond.locator(".cond-badge").first.text_content()
        btns = cond.locator(".cond-owner .ui-btn").all_text_contents()
        check(f"после «вышел» — «сработало», обычные кнопки «сделал / отложить до / не актуально» ({badge!r}, {btns})",
              badge.startswith("сработало") and btns == ["сделал", "отложить до", "не актуально"])
        row = pg.evaluate("() => { const c = dsCondRows().find(x => x.id === 'nvtk-sellgate'); return [c.status, c.waits_owner, c.fired_by_deadline]; }")
        check(f"модуль (а): сработало, ждёт владельца, не по сроку ({row})", row == ["fired", True, False])
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()


        # 8: условия-напоминания владельца (POST /api/pf/condition подменён сервером-заглушкой)
        for vw, label in ((1400, "1400"), (390, "390")):
            build()
            browser, pg, errs = open_page(p, "actions")
            if vw != 1400:
                pg.set_viewport_size({"width": vw, "height": 844})
                pg.evaluate("() => { goToTab('actions'); }")
                pg.wait_for_timeout(400)
            tag = f"[{label}] "
            posts = []
            mode = {"status": 200}

            def cond_route(route):
                body = json.loads(route.request.post_data or "{}")
                posts.append(body)
                if mode["status"] == 409:
                    return route.fulfill(status=409, content_type="application/json", body=json.dumps({"error": "файл условий только что менялся — подожди минуту и повтори"}))
                if mode["status"] == 400:
                    return route.fulfill(status=400, content_type="application/json", body=json.dumps({"error": "key: бумаги QQQQ нет на досках TQBR / TQOB / TQCB и в портфеле — проверь тикер"}))
                now = pg.evaluate("() => _mskIso(Date.now())")
                if body["action"] == "add":
                    c = {"id": f"c-{now[:10]}-{body['key'].lower()}-1", "version": 1, "key": body["key"], "kind": "watch",
                         "trigger": {"type": body["trigger"], "value": body["value"]}, "while_pending": {"verdict": None, "text": ""},
                         "on_trigger": {"action": "notify_only", "text": body["text"]}, "source": {"kind": "owner", "doc": None}, "context": None,
                         "created_at": now, "created_by": "owner", "withdrawn": None, "superseded_by": None}
                    if body.get("valid_until"):
                        c["valid_until"] = body["valid_until"]
                    return route.fulfill(status=200, content_type="application/json", body=json.dumps({"saved": "Portfolio/conditions.yaml", "id": c["id"], "version": 1, "condition": c}))
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(
                    {"saved": "Portfolio/conditions.yaml", "id": body["id"], "withdrawn": {"at": now, "by": "owner", "reason": body.get("reason") or "снято владельцем с сайта"}}))
            pg.route("**/api/pf/condition", cond_route)
            # живая котировка бумаги вне портфеля — как после loadLivePrices (ответ quotes@1 целиком лежит в state.live.quotes)
            pg.evaluate("() => { state.live.quotes = { schema: 'quotes@1', items: { ZZZZ: { price: 300 } } }; }")
            check(tag + "livePriceOf: бумага вне портфеля — цена доски", pg.evaluate("() => livePriceOf('ZZZZ')") == 300)
            check(tag + "livePriceOf: неизвестный тикер — null", pg.evaluate("() => livePriceOf('NOPE')") is None)
            held_ok = pg.evaluate("() => { const h = currentPort().holdings.find(x => x.current_price != null && x.current_price_source !== 'cost_basis'); return h ? [h.ticker, h.current_price, livePriceOf(h.ticker)] : null; }")
            check(tag + f"livePriceOf: держимая бумага — как раньше, цена снапшота ({held_ok})", bool(held_ok) and held_ok[1] == held_ok[2])
            pg.evaluate("() => { const h = currentPort().holdings[0]; window.__h0 = [h.ticker, h.current_price_source]; h.current_price_source = 'cost_basis'; state.live.quotes.items[h.ticker] = { price: 777 }; }")
            frozen = pg.evaluate("() => livePriceOf(__h0[0])")
            pg.evaluate("() => { const h = currentPort().holdings[0]; h.current_price_source = __h0[1]; }")
            check(tag + f"livePriceOf: держимая позиция без цены (cost_basis) — null, не котировка доски ({frozen})", frozen is None)

            check(tag + "«Новое условие» на «Действиях» есть", pg.locator("#act-newcond").count() == 1)
            pg.locator("#act-newcond > summary").click()
            pg.wait_for_timeout(200)
            form = pg.locator("#act-newcond .cond-add-form")
            check(tag + "форма видна", form.is_visible())
            ow = pg.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1")
            check(tag + "нет горизонтальной прокрутки при открытой форме", ow)
            form.locator('[data-cond-add="key"]').fill("zzzz")
            check(tag + "тикер приводится к верхнему регистру", form.locator('[data-cond-add="key"]').input_value() == "ZZZZ")
            form.locator('[data-cond-add="value"]').fill("250")
            hint = form.locator(".cond-add-hint").text_content()
            check(f"{tag}подсказка цены: «сейчас 300 · ещё −16,7 %» ({hint!r})", "сейчас 300" in hint and "16,7" in hint)
            # обязательные поля: без текста — ошибка на месте, запроса нет
            form.locator('[data-cond-add="save"]').click()
            pg.wait_for_timeout(150)
            check(tag + "без «что напомнить» — понятная ошибка, запроса нет",
                  "Напиши, что напомнить" in form.locator(".card-owner-msg").text_content() and not posts)
            form.locator('[data-cond-add="text"]').fill("Сбер подешевел — смотреть покупку")
            # 400: сервер не знает бумагу
            mode["status"] = 400
            form.locator('[data-cond-add="save"]').click()
            pg.wait_for_function("() => /Сервер не принял/.test(document.querySelector('#act-newcond .card-owner-msg')?.textContent || '')", timeout=5000)
            check(tag + "400: текст сервера показан", "проверь тикер" in form.locator(".card-owner-msg").text_content())
            mode["status"] = 409
            form.locator('[data-cond-add="save"]').click()
            pg.wait_for_function("() => /подожди минуту/.test(document.querySelector('#act-newcond .card-owner-msg')?.textContent || '')", timeout=5000)
            check(tag + "409: «подожди минуту» — человеческим текстом", True)
            mode["status"] = 200
            n0 = len(posts)
            form.locator('[data-cond-add="save"]').click()
            pg.wait_for_function("() => document.querySelector('#act-newcond .cond-add-done')?.textContent.includes('Условие записано')", timeout=5000)
            last = posts[-1]
            check(f"{tag}POST api/pf/condition: add, тикер, триггер, число, текст ({last})",
                  len(posts) == n0 + 1 and last == {"action": "add", "key": "ZZZZ", "trigger": "price_below", "value": 250, "text": "Сбер подешевел — смотреть покупку"})
            row = pg.evaluate("() => { const c = dsCondRows().find(x => x.key === 'ZZZZ'); return c ? [c.status, c.kind, c.verdict_now, c.action_code] : null; }")
            check(f"{tag}модуль (а): условие ждёт, kind watch, вердикта нет ({row})", row == ["pending", "watch", None, "notify_only"])
            # «Все условия»: строка бумаги вне портфеля с живой ценой
            pg.locator("details.act-fold", has_text="Все условия").locator("> summary").click()
            pg.wait_for_timeout(200)
            crow = pg.locator('.cond-row[data-cond^="c-"]', has_text="ZZZZ")
            txt = crow.first.text_content() if crow.count() else ""
            check(f"{tag}«Все условия»: строка ZZZZ с «сейчас 300 · ещё −16,7 %» ({txt[:120]!r})", crow.count() == 1 and "сейчас 300" in txt and "16,7" in txt)
            check(tag + "у строки владельца есть «снять»", crow.locator('[data-cond-act="withdraw"]').count() == 1)
            others = pg.locator('.cond-row[data-cond]:not([data-cond^="c-"]) [data-cond-act="withdraw"]').count()
            check(tag + "у условий советника «снять» нет", others == 0)
            # карточка-кандидат
            pg.locator("#act-newcond [data-cond-open-card]").click()
            pg.wait_for_selector("#card-layer .card-pane", timeout=8000)
            pg.wait_for_timeout(300)
            cand = pg.evaluate("() => cardStack.length ? !!cardStack[cardStack.length - 1].pos?.candidate || !!cardStack[cardStack.length - 1].list?.[0]?.candidate : null")
            wait = pg.locator("#card-layer .card-wait .card-cond")
            wtxt = wait.first.text_content() if wait.count() else ""
            check(f"{tag}карточка ZZZZ открыта (кандидат), «Чего ждём»: «цена ≤ 250 (сейчас 300 · ещё −16,7 %)» ({wtxt[:140]!r}, candidate={cand})",
                  wait.count() == 1 and "цена ≤ 250" in wtxt and "сейчас 300" in wtxt and "16,7" in wtxt)
            check(tag + "в карточке: «Тогда» с текстом напоминания, вердикта «Пока ждём» нет",
                  "Сбер подешевел" in wtxt and "Пока ждём" not in wtxt)
            check(tag + "в карточке ZZZZ есть кнопка «＋ Напоминание»", pg.locator('#card-layer [data-cond-add-open="ZZZZ"]').count() == 1)
            # снять своё (два шага)
            pg.locator('#card-layer .card-wait [data-cond-act="withdraw"]').click()
            pg.locator('#card-layer .card-wait [data-cond-act="withdraw-yes"]').click()
            pg.wait_for_function("() => !document.querySelector('#card-layer .card-wait .card-cond')", timeout=5000)
            check(f"{tag}POST api/pf/condition: withdraw, id условия ({posts[-1]})", posts[-1]["action"] == "withdraw" and posts[-1]["id"].startswith("c-") and "zzzz" in posts[-1]["id"])
            st = pg.evaluate("() => dsCondRows().find(x => x.key === 'ZZZZ')?.status")
            check(f"{tag}после «снять» условие снято в списках ({st})", st == "withdrawn")
            real = [e for e in errs if not re.search(r"status of (400|409)", e)]   # 400/409 — подстроены тестом (текст ошибки сервера)
            check(f"{tag}ошибок страницы нет ({real[:2]})", not real)
            browser.close()

        # 8б: карточка бумаги из портфеля — «＋ Напоминание» с предзаполненным тикером; у условия советника «снять» нет; режим «без ИИ» не влияет
        build()
        browser, pg, errs = open_page(p, "positions")
        posts = []

        def cond_route2(route):
            body = json.loads(route.request.post_data or "{}")
            posts.append(body)
            now = pg.evaluate("() => _mskIso(Date.now())")
            c = {"id": f"c-{now[:10]}-ydex-1", "version": 1, "key": body["key"], "kind": "watch", "trigger": {"type": body["trigger"], "value": body["value"]},
                 "while_pending": {"verdict": None, "text": ""}, "on_trigger": {"action": "notify_only", "text": body["text"]},
                 "source": {"kind": "owner", "doc": None}, "context": None, "created_at": now, "created_by": "owner", "withdrawn": None, "superseded_by": None,
                 "event_text": body["value"]}
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"saved": "Portfolio/conditions.yaml", "id": c["id"], "version": 1, "condition": c}))
        pg.route("**/api/pf/condition", cond_route2)
        for ai in ("on", "off"):
            pg.evaluate("(m) => { window.uiAiMode = () => m; }", ai)
            open_row(pg, "#content table", "YDEX")
            btn = pg.locator('#card-layer [data-cond-add-open="YDEX"]')
            check(f"[ai={ai}] карточка YDEX: «＋ Напоминание» есть", btn.count() == 1)
            btn.click()
            f2 = pg.locator("#card-layer .cond-add-form")
            check(f"[ai={ai}] тикер предзаполнен и не правится", f2.locator('[data-cond-add="key"]').input_value() == "YDEX" and f2.locator('[data-cond-add="key"]').get_attribute("readonly") is not None)
            pg.evaluate("() => { cardStack.length = 0; renderCards(); }")
        open_row(pg, "#content table", "YDEX")
        pg.locator('#card-layer [data-cond-add-open="YDEX"]').click()
        f2 = pg.locator("#card-layer .cond-add-form")
        sel = f2.locator(".ui-select").first
        sel.locator("button").first.click()
        pg.locator('.ui-select-opt[data-value="event"], [role="option"][data-value="event"]').first.click()
        f2.locator('[data-cond-add="value"]').fill("выйдет отчёт МСФО за 9М")
        f2.locator('[data-cond-add="text"]').fill("Разобрать отчёт")
        f2.locator('[data-cond-add="save"]').click()
        pg.wait_for_function("() => [...document.querySelectorAll('#card-layer .card-wait .card-cond')].some(n => /Разобрать отчёт/.test(n.textContent))", timeout=5000)
        check(f"POST: событие — триггер event и текст события ({posts[-1]})", posts[-1] == {"action": "add", "key": "YDEX", "trigger": "event", "value": "выйдет отчёт МСФО за 9М", "text": "Разобрать отчёт"})
        check("после записи условие видно в «Чего ждём» карточки (данные не перечитывались)", True)
        pg.evaluate("() => { cardStack.length = 0; renderCards(); showConditionModal(dsCondRows().find(c => c.id === 'nvtk-sellgate')); }")
        pg.wait_for_timeout(300)
        check("окно условия советника (NVTK): «снять» нет", pg.locator("#modal-body [data-cond-withdraw]").count() == 0)
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # 8в: облигация вне портфеля — карточка облигационного вида (цена % номинала, НКД, YTM, дюрация из котировки quotes@1),
        # условия и «＋ Напоминание», без позиции/доходности/решения; подсказка у «событие» при «без ИИ» (при «с ИИ» — нет)
        build()
        browser, pg, errs = open_page(p, "actions")
        bposts = []

        def cond_route3(route):
            body = json.loads(route.request.post_data or "{}")
            bposts.append(body)
            now = pg.evaluate("() => _mskIso(Date.now())")
            c = {"id": f"c-{now[:10]}-{body['key'].lower()}-1", "version": 1, "key": body["key"], "kind": "watch",
                 "trigger": {"type": body["trigger"], "value": body["value"]}, "while_pending": {"verdict": None, "text": ""},
                 "on_trigger": {"action": "notify_only", "text": body["text"]}, "source": {"kind": "owner", "doc": None}, "context": None,
                 "created_at": now, "created_by": "owner", "withdrawn": None, "superseded_by": None}
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"saved": "Portfolio/conditions.yaml", "id": c["id"], "version": 1, "condition": c}))
        pg.route("**/api/pf/condition", cond_route3)
        BK = "RU000A10ZZZ1"
        pg.evaluate("""(k) => { state.live.quotes = { schema: 'quotes@1', fx: { CNY: 12.5, date: '2026-11-11' }, items: { [k]: { price: 96.15, board: 'TQOB', isin: k,
            accrued_int: 368.14, face_value: 1000, face_unit: 'CNY', currency_id: 'SUR', lot_size: 1, prev_close: 96.61, ts: '2026-11-11 19:52:02',
            yield_pct: 8.42, yield_offer_pct: null, duration_days: 730 } } }; }""", BK)
        pg.locator("#act-newcond > summary").click()
        pg.wait_for_timeout(200)
        form = pg.locator("#act-newcond .cond-add-form")
        offh = form.locator('[data-cond-add="event-off-hint"]')
        for ai in ("on", "off"):
            pg.evaluate("(m) => { window.uiAiMode = () => m; }", ai)
            form.locator(".ui-select").first.locator("button").first.click()
            pg.locator('.ui-select-opt[data-value="event"], [role="option"][data-value="event"]').first.click()
            pg.wait_for_timeout(100)
            vis, txt = offh.is_visible(), (offh.text_content() or "")
            if ai == "on":
                check(f"[ai=on] «событие»: подсказки «без ИИ» нет ({vis}, {txt!r})", not vis and not txt)
            else:
                check(f"[ai=off] «событие»: подсказка «без ИИ событие ищет только монитор с ИИ — сработает по сроку; лучше выбрать «дата» или «цена»» ({txt!r})",
                      vis and txt == "без ИИ событие ищет только монитор с ИИ — сработает по сроку; лучше выбрать «дата» или «цена»")
            form.locator(".ui-select").first.locator("button").first.click()
            pg.locator('.ui-select-opt[data-value="price_below"], [role="option"][data-value="price_below"]').first.click()
            pg.wait_for_timeout(100)
            check(f"[ai={ai}] «цена»: подсказки «без ИИ» нет", not offh.is_visible())
        pg.evaluate("() => { window.uiAiMode = () => 'on'; }")
        form.locator('[data-cond-add="key"]').fill(BK)
        form.locator('[data-cond-add="value"]').fill("95")
        form.locator('[data-cond-add="text"]').fill("Юаневая ОФЗ подешевела — смотреть")
        form.locator('[data-cond-add="save"]').click()
        pg.wait_for_function("() => document.querySelector('#act-newcond .cond-add-done')?.textContent.includes('Условие записано')", timeout=5000)
        check(f"облигация: POST add с ISIN ({bposts[-1] if bposts else None})", bool(bposts) and bposts[-1]["key"] == BK and bposts[-1]["value"] == 95)
        pg.locator("#act-newcond [data-cond-open-card]").click()
        pg.wait_for_selector("#card-layer .card-pane", timeout=8000)
        pg.wait_for_timeout(300)
        kind = pg.evaluate("() => { const L = cardStack[cardStack.length - 1]; return L ? [L.list[L.idx]._kind, cardKindOf(L.list[L.idx]), !!L.list[L.idx].candidate] : null; }")
        check(f"облигация вне портфеля: карточка облигационного вида ({kind})", kind == ["bondcand", "bondcand", True])
        tiles = pg.locator("#card-layer .card-tiles .card-tile").all_text_contents()
        tj = " | ".join(tiles)
        check(f"плитки: цена 96,15 % и ≈ 12 019 ₽ по курсу ЦБ, НКД 368,14 ₽, доходность 8,42 %, дюрация 730 дн. ≈ 2,0 г. ({tj!r})",
              len(tiles) == 4 and "96,15 %" in tiles[0] and "12" in tiles[0] and "по курсу ЦБ" in tiles[0]
              and "368,14 ₽" in tiles[1] and "8,42 %" in tiles[2] and "730 дн." in tiles[3] and "2,0 г." in tiles[3])
        subs = pg.locator("#card-layer .card-subs .ui-seg-btn").all_text_contents()
        check(f"подвкладки: только «Главное» — без доходности, рисков, истории ({subs})", subs == ["Главное"])
        pane = pg.locator("#card-layer .card-pane").first.text_content() or ""
        check("нет позиции, доходности и решения: блоков «Решение», «Позиция», «Моя доходность» нет",
              pg.locator("#card-layer .card-dec").count() == 0 and "Моя доходность" not in tj and "Стоимость" not in pane and "Облигации нет в портфеле" in pane)
        wait = pg.locator("#card-layer .card-wait .card-cond")
        wtxt = wait.first.text_content() if wait.count() else ""
        check(f"«Чего ждём»: условие на облигацию с живой ценой ({wtxt[:120]!r})", wait.count() == 1 and "95" in wtxt and "Юаневая ОФЗ" in wtxt)
        check("кнопка «＋ Напоминание» с ISIN облигации", pg.locator(f'#card-layer [data-cond-add-open="{BK}"]').count() == 1)
        kv = pg.locator("#card-layer .card-kv").first.text_content() or ""
        check(f"сбоку — номинал 1 000 CNY, ISIN ({kv[:120]!r})", "1 000 CNY" in kv.replace("\u00a0", " ") and BK in kv)
        title = pg.locator("#card-layer .ui-modal").last.text_content() or ""
        check("в шапке — «облигация вне портфеля», YTM и дюрация", "облигация вне портфеля" in title and "YTM 8,42%" in title)
        # строка «Всех условий» открывает ту же карточку
        pg.evaluate("() => { cardStack.length = 0; renderCards(); }")
        pg.locator("details.act-fold", has_text="Все условия").locator("> summary").click()
        pg.wait_for_timeout(200)
        crow = pg.locator('.cond-row[data-cond^="c-"]', has_text=BK)
        check("«Все условия»: строка облигации кликабельна (карточка)", crow.count() == 1 and "pick" in (crow.first.get_attribute("class") or ""))
        crow.first.click()
        pg.wait_for_selector("#card-layer .card-pane", timeout=8000)
        check("из «Всех условий» — та же облигационная карточка", pg.evaluate("() => cardKindOf(cardStack[cardStack.length - 1].list[0])") == "bondcand")
        # фонд/акция вне портфеля — как раньше, карточка-кандидат акции
        check("акция/фонд вне портфеля — по-прежнему кандидат акции",
              pg.evaluate("() => { state.live.quotes.items.QQQF = { price: 10, board: 'TQBR' }; return outsideCandidate('QQQF', currentPort())._kind; }") == "stock")
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()


main()
shutil.rmtree(FIX, ignore_errors=True)
print(f"Итого: {passed} из {passed + failed} прошли" if failed == 0 else f"Итого: {passed} из {passed + failed} прошли (падений: {failed})")
sys.exit(1 if failed else 0)
