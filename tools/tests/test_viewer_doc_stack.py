#!/usr/bin/env python3
"""Вьюер: окна стопкой — документы вместе с карточками в одном порядке слоёв. Настоящий Chromium, клики по реальным элементам.

Дефект 29.10 (владелец): отчёт, открытый из карточки бумаги, которая лежит поверх окна «Gate», рисовался в том же окне #modal — под карточкой;
«Gate» оказывался подменён. То же в цепочке «отчёт → чип бумаги → карточка → другой отчёт».

Фикстура — viewer-live + superseded (живые файлы формата 2: обзор акций 28.10, решения decisions/, отчёты GMKN 29.10 и PLZL+GMKN 02.10), копия во временной папке.
Контракты (верхнее окно определяется elementFromPoint в центре экрана):
  1. «Gate» → бумага (чип) → карточка → «Отчёты» → отчёт: отчёт ВИДЕН поверх карточки; «← К бумаге» — видна карточка; Esc — виден «Gate» (тот же заголовок);
     Esc — всё закрыто, замороженных окон нет, id окна документа один.
  2. «Отчёты» → отчёт PLZL+GMKN → чип GMKN → карточка → «Отчёты» → отчёт GMKN → чип → вторая карточка; Esc по цепочке:
     вторая карточка → отчёт GMKN → первая карточка → отчёт PLZL+GMKN → список → закрыто. Под нижним окном — оно же в прежнем виде.
  3. Клик по фону закрывает только верхний документ; под ним — карточка, ниже — «Gate».
  4. ← → при открытом документе над карточкой карточку не листают; после закрытия документа — листают только верхнюю.
  5. Документ с вкладки поверх документа заменяет его (стопка не копится): «Gate» → «Отчёты» — одно окно.
  6. Ширина 390: верхнее окно перекрывает нижнее.
  7. Ошибок страницы нет.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_doc_stack.py
"""
import json
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
    print("viewer_doc_stack: пропуск — нет playwright")
    sys.exit(0)

sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as hub_api  # noqa: E402

FIX = Path(tempfile.mkdtemp(prefix="docstack-"))


def build():
    shutil.rmtree(FIX, ignore_errors=True)
    shutil.copytree(REPO / "tools/tests/fixtures/viewer-live", FIX)
    shutil.copytree(REPO / "tools/tests/fixtures/superseded", FIX, dirs_exist_ok=True)
    (FIX / "monitor-reports").mkdir()


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



GATE = "Решения по бумагам"   # окно кнопки «Решения» (бывшее «Gate»)
R_GMKN = "Разбор GMKN"
R_PLZL = "PLZL и GMKN"   # в списке заголовок очеловечен («разбор бумаги (Mode 4): …»), в шапке окна — как в файле («Mode 4: …»)
TOP = """() => { const e = document.elementFromPoint(innerWidth / 2, innerHeight / 2); if (!e) return 'none';
  if (e.closest('#card-layer .ui-modal')) return 'card';
  const o = e.closest('.modal-overlay'); return o ? 'doc:' + o.querySelector('h2').textContent : 'other'; }"""
STATE = """() => ({ cards: cardStack.length, frozen: docFrozen.length, ids: document.querySelectorAll('[id^="modal-overlay"]').length,
  live: !!document.querySelector('#modal-overlay:not([hidden])'), open: document.querySelectorAll('.modal-overlay:not([hidden])').length })"""


def top(pg):
    return pg.evaluate(TOP)


def settle(pg, ms=450):
    pg.wait_for_timeout(ms)


def open_viewer(p, width=1400, height=1000):
    browser = p.chromium.launch()
    ctx = browser.new_context(service_workers="block", viewport={"width": width, "height": height})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "502" not in m.text and "404" not in m.text else None)
    pg.route("**/api/pv/plan*", lambda r: r.fulfill(status=502, body="{}"))
    pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, body="{}"))
    pg.goto(URL)
    pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
    pg.wait_for_function("() => state.data && state.data.portfolioLatest && state.data.weeklyReviewCurrent && state.data.decisions.length"
                         " && (state.data.advisorReports || []).length >= 2", timeout=20000)
    pg.wait_for_timeout(500)
    return browser, pg, errs


def gate_to_report(pg):
    """Gate → чип GMKN → карточка → «Отчёты» → отчёт GMKN (окно «Gate» открывается, если ещё не открыто)."""
    if not pg.locator("#modal-body .gate-t .gate-tk").count():
        pg.click("#btn-gate-legend")
        pg.wait_for_selector("#modal-body .gate-t .gate-tk", timeout=5000)
        settle(pg)
    pg.locator("#modal-body .gate-t .gate-tk", has_text="GMKN").first.click()
    pg.wait_for_selector("#card-layer .card-win", timeout=5000)
    settle(pg)
    pg.click('#card-layer [data-act="card-sub"][data-v="reports"]')
    pg.wait_for_selector("#card-layer .card-rep", timeout=5000)
    pg.locator("#card-layer .card-rep", has_text=R_GMKN).first.click()
    pg.wait_for_selector(".report-doc", timeout=5000)
    settle(pg)


def main():
    with sync_playwright() as p:
        try:
            p.chromium.launch().close()
        except Exception as e:
            print(f"viewer_doc_stack: пропуск — {str(e).splitlines()[0][:80]}")
            return
        build()

        # 1: Gate → бумага → «Отчёты» → отчёт
        browser, pg, errs = open_viewer(p)
        pg.click("#btn-gate-legend")
        pg.wait_for_selector("#modal-body .gate-t .gate-tk", timeout=5000)
        settle(pg)
        check(f"«Gate» открыт и виден ({top(pg)!r})", top(pg) == "doc:" + GATE)
        gate_to_report(pg)
        t = top(pg)
        check(f"отчёт виден поверх карточки ({t!r})", t.startswith("doc:" + R_GMKN))
        st = pg.evaluate(STATE)
        check(f"стопка: карточка 1, замороженный «Gate» 1, окон документа в DOM 2 ({st})", st["cards"] == 1 and st["frozen"] == 1 and st["ids"] == 2)
        check("«Gate» под карточкой не подменён: его заголовок в DOM прежний",
              pg.evaluate("() => document.getElementById('modal-title-f0').textContent") == GATE)
        pg.locator("#modal-body .report-head button", has_text="← К бумаге").click()
        settle(pg, 600)
        check(f"«← К бумаге»: видна карточка ({top(pg)!r})", top(pg) == "card")
        st = pg.evaluate(STATE)
        check(f"после «← К бумаге»: «Gate» снова живое окно, замороженных нет ({st})", st["frozen"] == 0 and st["ids"] == 1 and st["live"] and st["cards"] == 1)
        pg.keyboard.press("Escape")
        settle(pg, 600)
        check(f"Esc: виден «Gate» (тот же заголовок) ({top(pg)!r})", top(pg) == "doc:" + GATE)
        pg.keyboard.press("Escape")
        settle(pg, 600)
        st = pg.evaluate(STATE)
        check(f"Esc: всё закрыто ({st})", st["cards"] == 0 and st["open"] == 0 and st["frozen"] == 0 and st["ids"] == 1)
        check(f"ошибок страницы нет ({errs[:2]})", not errs)

        # 5: документ с вкладки заменяет документ
        pg.click("#btn-gate-legend")
        pg.wait_for_selector("#modal-body .gate-t", timeout=5000)
        settle(pg)
        pg.evaluate("() => showReportsListModal()")
        settle(pg)
        st = pg.evaluate(STATE)
        check(f"документ поверх документа без карточки заменяет его: одно окно ({st}, {top(pg)!r})",
              st["ids"] == 1 and st["frozen"] == 0 and top(pg).startswith("doc:Отчёты"))
        pg.keyboard.press("Escape")
        settle(pg, 600)
        check("Esc закрыл список", pg.evaluate(STATE)["open"] == 0)
        browser.close()

        # 2: «Отчёты» → отчёт → чип → карточка → отчёт → чип → карточка; назад по цепочке
        browser, pg, errs = open_viewer(p)
        pg.click("#btn-reports")
        pg.wait_for_selector("#modal-body .report-item", timeout=5000)
        settle(pg)
        pg.locator("#modal-body .report-item", has_text=R_PLZL).first.click()
        pg.wait_for_selector(".report-doc", timeout=5000)
        settle(pg)
        check(f"отчёт из списка виден ({top(pg)!r})", (top(pg).startswith("doc:") and R_PLZL in top(pg)))
        pg.locator(".report-doc .rp-tk", has_text="GMKN").first.click()
        pg.wait_for_selector("#card-layer .card-win", timeout=5000)
        settle(pg)
        check(f"чип бумаги: видна карточка ({top(pg)!r})", top(pg) == "card")
        pg.click('#card-layer [data-act="card-sub"][data-v="reports"]')
        pg.wait_for_selector("#card-layer .card-rep", timeout=5000)
        pg.locator("#card-layer .card-rep", has_text=R_GMKN).first.click()
        pg.wait_for_selector(".report-doc", timeout=5000)
        settle(pg)
        check(f"другой отчёт из карточки виден поверх неё ({top(pg)!r})", top(pg).startswith("doc:" + R_GMKN))
        pg.evaluate("() => { document.getElementById('modal-f0').scrollTop = 240; }")
        scroll_before = pg.evaluate("() => document.getElementById('modal-f0').scrollTop")
        pg.locator("#modal-overlay .report-doc .rp-tk", has_text="GMKN").first.click()   # верхний (живой) отчёт; нижний заморожен под карточкой
        settle(pg, 600)
        st = pg.evaluate(STATE)
        check(f"чип в отчёте над карточкой: вторая карточка сверху, всего 2 ({st}, {top(pg)!r})", st["cards"] == 2 and top(pg) == "card")
        pg.keyboard.press("Escape"); settle(pg, 600)
        check(f"Esc: вторая карточка ушла, виден отчёт GMKN ({top(pg)!r})", top(pg).startswith("doc:" + R_GMKN) and pg.evaluate(STATE)["cards"] == 1)
        pg.keyboard.press("Escape"); settle(pg, 600)
        check(f"Esc: отчёт GMKN ушёл, видна первая карточка ({top(pg)!r})", top(pg) == "card")
        check(f"отчёт PLZL+GMKN под ними вернулся живым окном в прежнем виде: заголовок и прокрутка ({scroll_before})",
              pg.evaluate("() => document.getElementById('modal-title').textContent").find(R_PLZL) >= 0
              and pg.evaluate("() => document.getElementById('modal').scrollTop") == scroll_before)
        pg.keyboard.press("Escape"); settle(pg, 600)
        check(f"Esc: карточка ушла, виден отчёт PLZL+GMKN ({top(pg)!r})", (top(pg).startswith("doc:") and R_PLZL in top(pg)))
        pg.keyboard.press("Escape"); settle(pg, 600)
        check(f"Esc: из отчёта — назад к списку ({top(pg)!r})", top(pg).startswith("doc:Отчёты"))
        pg.keyboard.press("Escape"); settle(pg, 600)
        st = pg.evaluate(STATE)
        check(f"Esc: всё закрыто ({st})", st["open"] == 0 and st["cards"] == 0 and st["frozen"] == 0 and st["ids"] == 1)
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # 3 и 4: фон закрывает только верхний документ; стрелки — только верхней карточке
        browser, pg, errs = open_viewer(p)
        pg.click("#btn-gate-legend")
        pg.wait_for_selector("#modal-body .gate-t .gate-tk", timeout=5000)
        settle(pg)
        pg.evaluate("() => { const pbt = buildPositionByTicker(); const l = ['GMKN', 'NVTK', 'SBER'].map(t => pbt[t]).filter(Boolean); openCard(l[0], l); }")
        pg.wait_for_selector("#card-layer .card-win", timeout=5000)
        settle(pg)
        n = pg.evaluate("() => cardStack[0].list.length")
        check(f"карточка со списком для листания ({n} бумаг)", n >= 2)
        pg.click('#card-layer [data-act="card-sub"][data-v="reports"]')
        pg.wait_for_selector("#card-layer .card-rep", timeout=5000)
        pg.locator("#card-layer .card-rep", has_text=R_GMKN).first.click()
        pg.wait_for_selector(".report-doc", timeout=5000)
        settle(pg)
        pg.keyboard.press("ArrowRight"); settle(pg)
        check("→ при документе над карточкой: карточка не листает", pg.evaluate("() => cardStack[0].idx") == 0)
        pg.mouse.click(5, 5)
        settle(pg, 600)
        st = pg.evaluate(STATE)
        check(f"клик по фону закрыл только отчёт: видна карточка, «Gate» под ней вернулся ({st}, {top(pg)!r})",
              top(pg) == "card" and st["cards"] == 1 and st["frozen"] == 0 and st["live"])
        pg.keyboard.press("ArrowRight"); settle(pg)
        check("→ в верхней карточке листает", pg.evaluate("() => cardStack[0].idx") == 1)
        pg.keyboard.press("Escape"); settle(pg, 600)
        check(f"Esc: карточка ушла, виден «Gate» ({top(pg)!r})", top(pg) == "doc:" + GATE)
        pg.mouse.click(5, 5); settle(pg, 600)
        check("клик по фону закрыл «Gate»", pg.evaluate(STATE)["open"] == 0)
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # 6: телефон
        browser, pg, errs = open_viewer(p, 390, 844)
        gate_to_report(pg)
        check(f"390 px: отчёт перекрывает карточку ({top(pg)!r})", top(pg).startswith("doc:" + R_GMKN))
        pg.locator("#modal-body .report-head button", has_text="← К бумаге").click()
        settle(pg, 600)
        check(f"390 px: «← К бумаге» — видна карточка ({top(pg)!r})", top(pg) == "card")
        pg.keyboard.press("Escape"); settle(pg, 600)
        check(f"390 px: Esc — виден «Gate» ({top(pg)!r})", top(pg) == "doc:" + GATE)
        check("390 px: страница не шире экрана", pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1"))
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # 7 (4.2.4): карточка поверх отчёта — заднее окно сдвинуто «позади» (как в стопке ui-kit), на 1400 и 390; ушла карточка — отчёт на месте
        for w, h in ((1400, 1000), (390, 844)):
            browser, pg, errs = open_viewer(p, w, h)
            pg.evaluate("() => { const r = state.data.advisorReports[0]; showAdvisorReportModal(r); }")
            pg.wait_for_selector(".report-doc .rp-tk", timeout=6000)
            BEH = "() => { const o = document.querySelector('#modal-overlay'), m = document.querySelector('#modal'); return { behind: o.classList.contains('behind'), tr: getComputedStyle(m).transform, op: +getComputedStyle(m).opacity }; }"
            settle(pg, 700)
            b0 = pg.evaluate(BEH)
            pg.locator(".report-doc .rp-tk").first.click()
            pg.wait_for_selector("#card-layer .ui-modal", timeout=6000)
            settle(pg, 700)
            b1 = pg.evaluate(BEH)
            check(f"{w} px: карточка поверх отчёта — отчёт «позади» (сдвинут, приглушён) ({b0} → {b1})",
                  not b0["behind"] and b0["tr"] == "none" and b1["behind"] and b1["tr"] != "none" and b1["op"] < 1 and top(pg) == "card")
            pg.keyboard.press("Escape"); settle(pg, 700)
            b2 = pg.evaluate(BEH)
            check(f"{w} px: карточка закрыта — отчёт на месте ({b2})", not b2["behind"] and b2["tr"] == "none" and b2["op"] == 1)
            check(f"{w} px: ошибок страницы нет ({errs[:2]})", not errs)
            browser.close()


main()
shutil.rmtree(FIX, ignore_errors=True)
print(f"Итого: {passed} из {passed + failed} прошли" if failed == 0 else f"Итого: {passed} из {passed + failed} прошли (падений: {failed})")
sys.exit(1 if failed else 0)
