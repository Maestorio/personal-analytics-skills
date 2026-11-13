#!/usr/bin/env python3
"""Вьюер 3.119.0: колонка «Мой план, %» с карандашом в «Доли и цели → План» в режимах «К цели IE» и «Все бумаги» — настоящий Chromium.

Владелец: «добавь колонку мой план редактируемую — так я смогу добавлять бумагу к своему портфелю».
Контракты (фикстуры viewer-live, api/pv/plan и api/pv/plan/set подменяются в браузере):
  1. «К цели IE» и «Все бумаги»: колонка «Мой план, %» есть, у строк ячейка с ✎; значение — из plan.json.
  2. ✎ у бумаги из портфеля (SBER) открывает окно плана с её долей.
  3. ✎ у бумаги вне портфеля и вне плана (WUSH, «Все бумаги») → ввод 1,5 → ровно один POST set с stocks.WUSH.plan_pct = 1.5 и причиной;
     после ответа строка показывает 1,5, а бумага получает карточку-кандидат (клик по строке).
  4. Сортировка по колонке (клик по заголовку) ставит aria-sort; на 390 страница без горизонтальной прокрутки, колонка видна, ✎ нажимается.
  5. Ошибок страницы нет.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_plan_ie_all.py
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



def main():
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            print(f"viewer_plan_ie_all: пропуск — {str(e).splitlines()[0][:80]}")
            return
        for width in (1400, 390):
            run(browser, width)


def run(browser, width):
    ctx = browser.new_context(service_workers="block", viewport={"width": width, "height": 1000})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "502" not in m.text and "404" not in m.text else None)
    site = {"plan": None, "hash": "h1", "sets": []}

    def api_plan(route):
        return route.fulfill(status=200, content_type="application/json", body=json.dumps({"path": "Portfolio/plan.json", "hash": site["hash"], "plan": site["plan"]}))

    def api_set(route):
        b = json.loads(route.request.post_data or "{}")
        site["sets"].append(b)
        for ch in b.get("changes") or []:
            sec, tk, f = ch["path"].split(".")
            site["plan"].setdefault(sec, {}).setdefault(tk, {})[f] = ch["value"]
        site["hash"] = "h%d" % (len(site["sets"]) + 1)
        return route.fulfill(status=200, content_type="application/json", body=json.dumps({"hash": site["hash"], "plan": site["plan"], "entries": [], "timing_ms": {"save": 1, "journal": 1}}))
    pg.route("**/api/pv/plan", api_plan)
    pg.route("**/api/pv/plan/set", api_set)
    pg.route("**/api/pv/plan/journal*", lambda r: r.fulfill(status=200, content_type="application/json", body='{"entries": []}'))
    pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, body="{}"))
    pg.goto(URL)
    pg.wait_for_selector("#tabs .ui-tab, #tabs-more", timeout=20000, state="attached")
    pg.wait_for_function("() => state.data && state.data.portfolioLatest", timeout=20000)
    pg.wait_for_timeout(1500)
    pt = pg.evaluate("() => currentPort().ie_actual.per_ticker")
    stocks = {k: {"plan_pct": v.get("planned_share_pct"), "user_plan": v.get("user_plan"), "user_status": v.get("user_status"),
                  "note_ai": None, "note_ie": None, "ie_new_pct": None, "ie_old_pct": None} for k, v in pt.items() if k not in ("WUSH", "UPRO")}
    site["plan"] = {"schema_version": 1, "stocks": stocks, "classes": [], "matrix": [], "bond_buckets": [], "bonds": {}, "funds": {}, "manual_positions": [],
                    "ie_model": pg.evaluate("() => currentPort().ie_model"), "updated_at": "2026-10-28T10:00:00Z"}
    t, cand = "SBER", "WUSH"
    tag = f"[{width}] "
    check(tag + "фикстура: WUSH не в плане сайта и не в портфеле", cand not in stocks and (pt.get(cand) or {}).get("real_share_pct") in (0, None))
    pg.evaluate("async () => { await loadPlan(); }")
    pg.wait_for_timeout(300)
    SHOW = "(m) => { state.ieView = 'watch'; state.rebalMode = m; goToTab('ie-model'); renderTabContent(); }"
    HEADS = "() => [...document.querySelectorAll('.rb-table thead th')].filter(x => x.offsetParent).map(x => x.textContent.trim())"
    ROWQ = """(t) => { const r = [...document.querySelectorAll('.rb-table tbody tr')].find(x => x.innerText.split(/\\s+/).includes(t)); const c = r && r.querySelector('td[data-col=plan]');
      return c ? { txt: c.innerText.replace(/\\s+/g, ' ').trim(), pen: !!c.querySelector('.rb-pen') } : null; }"""
    for mode, tbl in (("ie", ".rb-v-watch"), ("all", ".rb-v-all")):
        pg.evaluate(SHOW, mode)
        pg.wait_for_selector(f"{tbl} tbody tr", timeout=10000)
        pg.wait_for_timeout(300)
        heads = pg.evaluate(HEADS)
        check(f"{tag}«{mode}»: колонка «Мой план, %» есть ({heads})", "Мой план, %" in heads)
        cell = pg.evaluate(ROWQ, t)
        check(f"{tag}«{mode}»: у {t} в ячейке доля плана сайта и ✎ ({cell})", bool(cell) and cell["pen"] and cell["txt"].startswith("10,5"))
        ov = pg.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        check(f"{tag}«{mode}»: страница без горизонтальной прокрутки ({ov})", ov <= 0)
        # сортировка по колонке
        pg.evaluate("() => [...document.querySelectorAll('.rb-table thead th')].find(x => x.textContent.trim() === 'Мой план, %').click()")
        pg.wait_for_timeout(300)
        srt = pg.evaluate("() => { const h = [...document.querySelectorAll('.rb-table thead th')].find(x => x.textContent.trim() === 'Мой план, %'); return h.getAttribute('aria-sort'); }")
        check(f"{tag}«{mode}»: клик по заголовку сортирует колонку ({srt})", srt in ("descending", "ascending"))
        first = pg.evaluate("""() => [...document.querySelectorAll('.rb-table tbody tr td[data-col=plan]')].map(c => parseFloat(c.innerText.replace(',', '.'))).filter(x => !isNaN(x))""")
        mono = all(first[i] >= first[i + 1] for i in range(len(first) - 1)) if srt == "descending" else all(first[i] <= first[i + 1] for i in range(len(first) - 1))
        check(f"{tag}«{mode}»: значения отсортированы ({first[:6]})", len(first) > 3 and mono)
        # ✎ у бумаги из портфеля
        pg.evaluate("""(t) => { const r = [...document.querySelectorAll('.rb-table tbody tr')].find(x => x.innerText.split(/\\s+/).includes(t)); r.querySelector('td[data-col=plan] .rb-pen').click(); }""", t)
        pg.wait_for_selector("#plan-layer .ui-modal", timeout=5000)
        v = pg.evaluate("() => document.querySelector('#plan-pct').value")
        ttl = pg.evaluate("() => document.querySelector('#plan-layer .ui-modal').innerText")
        check(f"{tag}«{mode}»: ✎ у {t} открывает окно плана с долей 10,5 ({v!r})", v == "10.5" and t in ttl)
        pg.evaluate("() => planEditClose()")
        pg.wait_for_timeout(200)

    # бумага вне портфеля и вне плана — «Все бумаги»
    pg.evaluate(SHOW, "all")
    pg.wait_for_selector(".rb-v-all tbody tr", timeout=10000)
    cell = pg.evaluate(ROWQ, cand)
    check(f"{tag}«Все бумаги»: у {cand} (вне портфеля и плана) ячейка «—» и ✎ ({cell})", bool(cell) and cell["pen"] and cell["txt"].startswith("—"))
    pg.evaluate("""(t) => { const r = [...document.querySelectorAll('.rb-table tbody tr')].find(x => x.innerText.split(/\\s+/).includes(t)); r.querySelector('td[data-col=plan] .rb-pen').click(); }""", cand)
    pg.wait_for_selector("#plan-layer .ui-modal", timeout=5000)
    pg.fill("#plan-pct", "1.5")
    pg.fill("#plan-reason", "хочу добавить в портфель")
    pg.click("#plan-layer [data-act=plan-save]")
    pg.wait_for_timeout(800)
    check(f"{tag}сохранение шлёт один POST set с stocks.{cand}.plan_pct = 1.5 и причиной ({site['sets']})",
          len(site["sets"]) == 1 and site["sets"][0]["changes"] == [{"path": f"stocks.{cand}.plan_pct", "value": 1.5}]
          and site["sets"][0].get("reason") == "хочу добавить в портфель")
    cell = pg.evaluate(ROWQ, cand)
    check(f"{tag}после ответа строка {cand} показывает 1,5 ({cell})", bool(cell) and cell["txt"].startswith("1,5"))
    check(f"{tag}бумага получила карточку-кандидат (buildPositionByTicker) ", pg.evaluate("(t) => !!buildPositionByTicker()[t]", cand))
    pg.evaluate("""(t) => { const r = [...document.querySelectorAll('.rb-table tbody tr')].find(x => x.innerText.split(/\\s+/).includes(t)); r.click(); }""", cand)
    pg.wait_for_selector(".card-win", timeout=10000)
    ct = pg.evaluate("() => document.querySelector('.card-win').innerText.replace(/\\s+/g, ' ')")
    check(f"{tag}клик по строке {cand} открывает карточку ({ct[:80]!r})", cand in ct[:200])
    # 4.4.7 (владелец 06.11): потенциал IE — только от текущей цены до цели; бумага вне модели — «нет в модели IE» на плитке веса
    pg.evaluate("() => { cardStack.length = 0; renderCards(); closeModal(); }")
    TL = """() => { const w = document.querySelector('.card-win'); return [...w.querySelectorAll('.card-tiles .ui-stat')].map(x => x.textContent.replace(/[\\s\\u00a0\\u202f]+/g, ' ').toLowerCase()); }"""   # textContent: на телефоне подпись плитки скрыта
    OPENC = "(t) => { cardStack.length = 0; renderCards(); const e = buildPositionByTicker()[t]; openCard(e, [e]); }"
    r = pg.evaluate("""(t) => { const m = ieModel().positions.find(x => x.ticker === t); const cur = ieMarketPrice(t);
      m.current_price_rub = cur * 0.5; m.growth_potential_12m_pct = 99; m.growth_potential_lt_pct = 199; m.target_price_rub = cur * 1.2; m.target_price_lt_rub = cur * 1.5;
      const a = ieTargetFor(t);
      m.current_price_rub = null; m.growth_potential_12m_pct = null; m.growth_potential_lt_pct = null; m.active_in_model = false;
      const b = ieTargetFor(t);
      const pa = currentPort().ie_actual.per_ticker[t]; if (pa) pa.ie_new_pct = null;
      if (state.plan.plan?.stocks?.[t]) state.plan.plan.stocks[t].ie_new_pct = null;
      const nq = { ticker: 'ZZZZ', name: 'Без цены', current_price_rub: 100, growth_potential_12m_pct: 30, target_price_rub: 130, active_in_model: false };
      ieModel().positions.push(nq);
      const nqr = [nq.ticker, ieMarketPrice('ZZZZ'), ieTargetFor('ZZZZ').pot, ieTargetFor('ZZZZ').target];
      ieModel().positions.pop();
      return { cur, a: [a.pot, a.potLt], b: [b.pot, b.potLt, b.inModel], f: [fmtPct(20).toLowerCase(), fmtPct(50).toLowerCase(), _iePot(20)],
        nq: nqr }; }""", t)
    near = lambda v, x: v is not None and abs(v - x) < 1e-6
    check(f"{tag}4.4.7: потенциал {t} — от текущей цены до цели (+20 % и +50 %), а не число IE (99/199) и не от цены IE ({r['a']})", bool(r["cur"]) and near(r["a"][0], 20) and near(r["a"][1], 50))
    check(f"{tag}4.4.7: цены IE и потенциала IE в строке нет, цель есть — потенциал тот же, от текущей цены ({r['b']})", near(r["b"][0], 20) and near(r["b"][1], 50) and r["b"][2] is False)
    check(f"{tag}4.4.7: у бумаги без текущей цены потенциала нет, хотя у IE он записан, цель остаётся ({r['nq']})", r["nq"][1] is None and r["nq"][2] is None and r["nq"][3] == 130)
    pg.evaluate(OPENC, t)
    pg.wait_for_selector(".card-win .card-tiles", timeout=10000)
    tiles = pg.evaluate(TL)
    pot = [x for x in tiles if x.startswith("потенциал ie")]
    wt = [x for x in tiles if x.startswith("вес: факт")]
    check(f"{tag}4.4.7: плитка «Потенциал IE 12 мес» {t} — {r['f'][0]}, долгосрок {r['f'][1]} ({pot})", len(pot) == 1 and r["f"][0] in pot[0] and "долгосрок " + r["f"][1] in pot[0])
    check(f"{tag}4.4.7: плитка «Вес: факт» — «нет в модели IE» у бумаги вне модели ({wt})", len(wt) == 1 and "нет в модели ie" in wt[0])
    ctxt = pg.evaluate("() => document.querySelector('.card-win').innerText.replace(/\\s+/g, ' ')")
    check(f"{tag}4.4.7: в карточке нет потенциала «от … ₽ у IE»", "₽ у IE" not in ctxt and "₽ в модели" not in ctxt)
    pg.evaluate("() => { cardStack.length = 0; renderCards(); closeModal(); }")
    pg.evaluate(SHOW, "all")
    pg.wait_for_selector(".rb-v-all tbody tr", timeout=10000)
    sub = pg.evaluate("""(t) => { const r = [...document.querySelectorAll('.rb-table tbody tr')].find(x => x.innerText.split(/\\s+/).includes(t)); const c = r && r.querySelector('td[data-col=t12] .ui-sub'); return c ? c.textContent.trim() : null; }""", t)
    check(f"{tag}4.4.7: «Все бумаги» — под целью {t} процент от текущей цены ({sub!r} = {r['f'][2]!r})", sub == r["f"][2])
    check(f"{tag}ошибок страницы нет ({errs[:2]})", not errs)
    ctx.close()


main()
print(f"Итого: {passed} из {passed + failed}")
sys.exit(1 if failed else 0)
