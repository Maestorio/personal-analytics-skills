#!/usr/bin/env python3
"""Вьюер 3.115.0: вердикты обзора облигаций на «Действиях» — настоящий Chromium, клик по реальным строкам.

Дефект: _actionItems брал только per_stock обзора акций; HIGH/MEDIUM и BUY/SELL/TRIM/ADD обзора облигаций на «Действиях» не попадали.

Фикстура — ЖИВЫЕ файлы: обзор облигаций 28.10 (yaml+md, 40 бумаг, 8 с HIGH/MEDIUM, одна HIGH ADD — RU000A10ERE6), обзор акций 28.10,
решения decisions/ и conditions@2 (superseded, формат 2), снапшот viewer-live.
Контракты:
  1. Бумага с HIGH ADD есть в «Сделать» с подписью «обзор облигаций 28.10»; в действия вошли все HIGH/MEDIUM/действия обзора;
     HOLD/HOLD_TO_MAT с проверкой «желательно» — в «К сведению», с проверкой «срочно» — пунктами в «Проверить» (пачка 3 читаемости).
  2. Бумага с LOW HOLD на «Действиях» не появляется.
  3. Клик по строке облигации открывает её карточку.
  4. «N сделать» в шапке и «к вниманию» actionCounts выросли на число строк облигаций в «Сделать» и «Проверить», против прогона без обзора облигаций.
  5. Решение по облигации (MEDIUM) от 29.10 (decision@1, ключ — ISIN) — последнее слово новее обзора: строка уходит в «Сделано»
     с «заменено решением 29.10: держать»; отчёт режима 4 без записанного решения строку не замещает (decision.md §1 следствие 1).
  6. Ошибок страницы нет.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_bond_actions.py
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viewer_ds import dec, write_decisions  # noqa: E402
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
    print("viewer_bond_actions: пропуск — нет playwright")
    sys.exit(0)

sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as hub_api  # noqa: E402

FIX = Path(tempfile.mkdtemp(prefix="bondact-"))
SUPERSEDER = "RU000A10CT33"   # HOLD / MEDIUM, условий нет
REPORT = """---
title: "Разбор облигации RU000A10CT33"
date: "2026-10-29"
created_at: "2026-10-29T12:00"
model: "claude-sonnet-5-5"
author: "ru-portfolio-advisor"
kind: "single_analysis"
summary: "Разбор облигации: держим, докупать нет оснований."
mode: "4 (single)"
mode_codes: ["4b"]
schema_version: "report@1"
recorded_at: "2026-10-29T12:00:00+03:00"
tickers: ["RU000A10CT33"]
horizon_months: 12
---

# Разбор облигации RU000A10CT33

Тело отчёта.
"""


def build(bonds=True, report=False, decision=False):
    shutil.rmtree(FIX, ignore_errors=True)
    fx = REPO / "tools/tests/fixtures"
    shutil.copytree(fx / "viewer-live", FIX)
    shutil.copytree(fx / "superseded", FIX, dirs_exist_ok=True)
    if bonds:
        shutil.copytree(fx / "bond-actions", FIX, dirs_exist_ok=True)
    (FIX / "monitor-reports").mkdir()
    if report:
        (FIX / "Portfolio/reports/2026-10-29-single-analysis-bond-ct33.md").write_text(REPORT, encoding="utf-8")
    if decision:
        write_decisions(FIX, [dec(SUPERSEDER, "HOLD", "2026-10-29T12:00:00+03:00", doc="Portfolio/reports/2026-10-29-single-analysis-bond-ct33.md", mode_codes=["4b"])])


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


def dec_tickers(pg):
    """бумаги строк обзора на «Действиях»: «Сделать», «Проверить» (пункты проверки) и «К сведению» (тикеры)."""
    return pg.evaluate("""() => [...document.querySelectorAll('#act-do .act-dec[data-ticker]')].map(e => e.dataset.ticker)
      .concat([...document.querySelectorAll('#act-check [data-check]')].map(e => e.dataset.check.split('|')[0]))
      .concat([...document.querySelectorAll('#act-info [data-info]')].map(e => e.dataset.info))""")


def tile(pg, label):
    m = re.search(r"(\d+) " + label, pg.locator("#content #act-head").inner_text(), re.I)
    return int(m.group(1)) if m else 0


def open_actions(p):
    browser = p.chromium.launch()
    ctx = browser.new_context(service_workers="block", viewport={"width": 1400, "height": 1000})
    pg = ctx.new_page()
    # «Сегодня» — 30.10: обзоры фикстуры от 28.10 свежие. Без фиксации с 12.11 обзор облигаций
    # стал «устаревшим» и добавлял строку «Сделать», которой нет в опоре без обзора (тест падал по календарю).
    pg.clock.set_fixed_time("2026-10-30T12:00:00+03:00")
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "502" not in m.text and "404" not in m.text else None)
    pg.route("**/api/pv/plan*", lambda r: r.fulfill(status=502, body="{}"))
    pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, body="{}"))
    pg.goto(URL)
    pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
    pg.wait_for_function("() => state.data && state.data.portfolioLatest && state.data.weeklyReviewCurrent && state.data.decisions.length", timeout=20000)
    pg.evaluate("() => { goToTab('actions'); }")
    pg.wait_for_selector("#content #act-head", timeout=10000)
    pg.wait_for_timeout(600)
    return browser, pg, errs


def main():
    with sync_playwright() as p:
        try:
            p.chromium.launch().close()
        except Exception as e:
            print(f"viewer_bond_actions: пропуск — {str(e).splitlines()[0][:80]}")
            return

        # опора: без обзора облигаций
        build(bonds=False)
        browser, pg, errs = open_actions(p)
        base_dec = tile(pg, "сделать")
        base_att = pg.evaluate("() => actionCounts().attention")
        browser.close()

        build()
        browser, pg, errs = open_actions(p)
        check("обзор облигаций загружен (28.10, 40 бумаг)", pg.evaluate("() => Object.keys(state.data.weeklyBondReviewCurrent.parsed.per_bond).length") == 40)
        items = pg.evaluate("() => _actionItems().filter(i => i.source === 'обзор облигаций').map(i => i.ticker)")
        check(f"в действия вошли 8 бумаг обзора облигаций с HIGH/MEDIUM ({len(items)})", len(items) == 8)
        low = pg.evaluate("""() => Object.entries(state.data.weeklyBondReviewCurrent.parsed.per_bond)
            .filter(([k, v]) => v.verification_priority === 'LOW' && v.advisor_verdict === 'HOLD').map(([k]) => k)""")
        check("в обзоре есть бумаги LOW HOLD", len(low) > 0)
        rows = dec_tickers(pg)
        vis = pg.evaluate("() => _actionItems().filter(i => i.source === 'обзор облигаций' && !i.superseded && !i.cond).map(i => i.ticker)")
        bb = pg.evaluate("""() => { const B = actionBlocks(), bond = (it) => it.source === 'обзор облигаций';
          return { do: B.do.verdicts.filter(x => bond(x.it)).map(x => x.it.ticker), check: B.check.items.filter(x => bond(x.it)).map(x => x.it.ticker),
                   info: B.info.items.filter(bond).map(it => [it.ticker, it.verdict, it.priority]) }; }""")
        check(f"HIGH ADD RU000A10ERE6 в «Сделать» ({rows})", "RU000A10ERE6" in rows and bb["do"] == ["RU000A10ERE6"])
        check(f"HOLD_TO_MAT «срочно» — пунктами в «Проверить» ({bb['check']})", bb["check"] and set(bb["check"]) == {"RU000A107795"})
        check(f"HOLD/HOLD_TO_MAT «желательно» — в «К сведению» ({bb['info']})", bb["info"] and all(v in ("HOLD", "HOLD_TO_MAT") and pr != "HIGH" for _, v, pr in bb["info"]))
        row = pg.locator('#act-do .act-dec[data-ticker="RU000A10ERE6"]')
        check(f"подпись источника «обзор облигаций 28.10» ({row.locator('.act-src').text_content() if row.count() else None!r})",
              row.count() == 1 and row.locator(".act-src").text_content().strip() == "обзор облигаций 28.10")
        check("LOW HOLD на «Действиях» нет", not any(t in rows for t in low))
        check(f"строки облигаций без условия = {len(vis)}", all(t in rows for t in vis))
        check(f"«сделать» в шапке выросло на {len(bb['do'])} ({tile(pg, 'сделать')} против {base_dec})", tile(pg, "сделать") == base_dec + len(bb["do"]))
        check(f"«к вниманию» (actionCounts) выросло на строки «Сделать» + «Проверить» ({pg.evaluate('() => actionCounts().attention')} против {base_att})",
              pg.evaluate("() => actionCounts().attention") == base_att + len(bb["do"]) + len(bb["check"]))
        row.click()
        pg.wait_for_selector("#card-layer .card-pane", timeout=8000)
        check("клик по строке открывает карточку облигации", pg.evaluate("() => cardKindOf(cardStack[cardStack.length - 1].list[cardStack[cardStack.length - 1].idx])") == "bond")
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # 5: отчёт без решения не замещает; решение 29.10 по ISIN — замещает
        build(report=True)
        browser, pg, errs = open_actions(p)
        check(f"отчёт 29.10 без записанного решения строку не замещает ({SUPERSEDER})", SUPERSEDER in dec_tickers(pg))
        browser.close()
        build(report=True, decision=True)
        browser, pg, errs = open_actions(p)
        rows = dec_tickers(pg)
        loc = pg.locator(f'#content #act-done [data-superseded="{SUPERSEDER}"]')
        t = loc.first.text_content().strip() if loc.count() else ""
        check(f"{SUPERSEDER} ушла из строк обзора на «Действиях» ({rows})", SUPERSEDER not in rows)
        check(f"в «Сделано»: «заменено решением 29.10: держать» и «обзор облигаций 28.10» ({t!r})", "заменено решением 29.10: держать" in t and "обзор облигаций 28.10" in t)
        check("прочие бумаги обзора облигаций на месте", "RU000A10ERE6" in rows)
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()


main()
shutil.rmtree(FIX, ignore_errors=True)
print(f"Итого: {passed} из {passed + failed} прошли" if failed == 0 else f"Итого: {passed} из {passed + failed} прошли (падений: {failed})")
sys.exit(1 if failed else 0)
