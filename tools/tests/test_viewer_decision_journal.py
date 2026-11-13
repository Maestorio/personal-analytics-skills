#!/usr/bin/env python3
"""Вьюер 3.107.0 — «Динамика»: блок «Помогает ли система» из Portfolio/decision-journal/ (baselines.json, journal.json, report-ДАТА.md).

Прогон настоящими браузерами (Chromium, WebKit; 1280 и 390). Данные — фикстуры viewer-live плюс три синтетических файла журнала,
собранные в этом тесте (числа взяты с боевого журнала 29.10).

Что проверяется:
  1. файлы журнала подхватываются загрузкой (папка в листинге вьюера): блок `.ui-card` на «Динамике» ПОСЛЕ «Реализованной доходности»;
  2. заголовок «Помогает ли система», подзаголовок «журнал решений на 29.10.2026 · окно факта 113 дней»;
  3. таблица: «Мой факт» и три базы (B0, B1, B2) — годовых % и разница к факту в п.п. и ₽ из файла, ничего не пересчитывается;
  4. «Вердикты: акции — верных 17 из 29 созревших, облигации — 4 из 9» и «созревший — прошло 3 мес»;
  5. «пока шум — выводы после 06.01.2027» — до контрольной точки; после неё строки нет;
  6. «полный отчёт →» открывает самый свежий report-ДАТА.md в читателе (не старый);
  7. нет файлов журнала — блока нет; на телефоне страница не шире экрана; ошибок страницы нет.
Запуск: python3 tools/tests/test_viewer_decision_journal.py  (нужен playwright; нет движка — пропуск).
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
    print("viewer_decision_journal: пропуск — нет playwright")
    sys.exit(0)

FIX = Path(tempfile.mkdtemp(prefix="dj-")) / "cm"
shutil.copytree(REPO / "tools/tests/fixtures/viewer-live", FIX)
DJ = FIX / "Portfolio/decision-journal"


def put_journal():
    DJ.mkdir(parents=True, exist_ok=True)
    base = lambda ann, pp, rub: {"nav": [["2026-07-08", 1.0]], "terminal_rub": 1.0, "twr": 0.0, "twr_ann": ann, "b3_minus_base_pp_ann": pp, "b3_minus_base_rub": rub}
    (DJ / "baselines.json").write_text(json.dumps({
        "schema": "shadow-baselines@1", "window": {"t0": "2026-07-08", "end": "2026-10-29", "days": 113},
        "b3": {"nav": [["2026-07-08", 1.0]], "twr": 0.07345, "twr_ann": 0.25727},
        "bases": {"B0": base(0.23847, 1.88, 72663.76), "B1": base(0.36649, -10.92, -428580.22),
                  "B2-live": base(0.27612, -1.88, -73574.05), "B2-frozen": base(0.2393, 1.8, 64284.22)}, "flags": []}), encoding="utf-8")
    (DJ / "journal.json").write_text(json.dumps({
        "schema": "decision-journal@1", "as_of": "2026-10-29", "flags": [], "records": [{"x": "y" * 50}] * 200,
        "summary": {"stock": {"verdicts": 591, "matured_3m": 31, "hits_3m": 18, "matured_3m_clean": 29, "hits_3m_clean": 17},
                    "bond": {"verdicts": 878, "matured_3m": 10, "hits_3m": 5, "matured_3m_clean": 9, "hits_3m_clean": 4}}}), encoding="utf-8")
    (DJ / "report-2026-10-28.md").write_text("# Журнал решений — отчёт на 2026-10-28\n\n## 1. Факт против теневых баз\n\nСТАРЫЙ ОТЧЁТ\n", encoding="utf-8")
    (DJ / "report-2026-10-29.md").write_text("# Журнал решений — отчёт на 2026-10-29\n\n## 1. Факт против теневых баз\n\nСВЕЖИЙ ОТЧЁТ: окно 113 дней — это шум.\n", encoding="utf-8")


put_journal()


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

CARD = """() => { const c = document.querySelector('.dj-card'); if (!c) return null;
  const sp = (x) => x.innerText.replace(/[\\s\\u00a0\\u202f]+/g, ' ').trim();
  const secs = [...document.querySelectorAll('#content > section.ui-card')];
  return { head: c.querySelector('h2').textContent, sub: sp(c.querySelector('p.ui-note')), rows: [...c.querySelectorAll('.dj-table .ui-row')].map(sp),
    text: sp(c), btn: [...c.querySelectorAll('button')].map(b => b.textContent), after: secs.indexOf(c), heads: secs.map(s => s.querySelector('h2')?.textContent || ''),
    isCard: c.classList.contains('ui-card'), sw: document.documentElement.scrollWidth }; }"""


def open_page(browser, width):
    opts = {"is_mobile": True, "has_touch": True} if width < 500 else {}
    if browser.browser_type.name == "webkit":
        opts["service_workers"] = "block"
    ctx = browser.new_context(viewport={"width": width, "height": 900}, **opts)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, content_type="application/json", body="{}"))
    pg.goto(URL)
    pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
    pg.wait_for_timeout(500)
    return ctx, pg, errs


def run(eng_name, eng):
    try:
        browser = eng.launch()
    except Exception as e:
        print(f"  {eng_name}: пропуск — {str(e).splitlines()[0][:80]}")
        return
    for w in (1280, 390):
        tag = f"{eng_name} {w}px"
        ctx, pg, errs = open_page(browser, w)
        pg.evaluate("goToTab('history')")
        pg.wait_for_selector(".dj-card", timeout=8000)
        c = pg.evaluate(CARD)
        check(f"{tag}: блок `.ui-card` «Помогает ли система» на «Динамике» ({c and c['head']})", c and c["isCard"] and c["head"] == "Помогает ли система")
        heads = c["heads"] if c else []
        # 5.2.x: между ними может стоять панель «Стоимость портфеля» (по дневному ряду цен, VW-DAILY)
        _prev = [h for h in heads[:c["after"]] if not h.startswith("Стоимость портфеля")] if c else []
        check(f"{tag}: после «Реализованной доходности» ({heads})", c and c["after"] > 0 and _prev and "Реализованная" in _prev[-1])
        check(f"{tag}: подзаголовок ({c and c['sub']})", c and c["sub"] == "журнал решений на 29.10.2026 · окно факта 113 дней")
        rows = c["rows"] if c else []
        check(f"{tag}: «Мой факт» +25,73 % годовых ({rows[1:2]})", len(rows) == 5 and rows[1].startswith("Мой факт") and "+25,73 %" in rows[1])
        check(f"{tag}: B0 +23,85 %, факт − база +1,9 п.п. и +72 664 ₽ ({rows[2:3]})",
              len(rows) == 5 and rows[2].startswith("Ничего не делать (B0)") and "+23,85 %" in rows[2] and "+1,9 п.п." in rows[2] and "+72 664 ₽" in rows[2])
        check(f"{tag}: B1 индексы +36,65 %, −10,9 п.п., −428 580 ₽ ({rows[3:4]})",
              len(rows) == 5 and rows[3].startswith("Индексы в плановых долях (B1)") and "+36,65 %" in rows[3] and "−10,9 п.п." in rows[3] and "−428 580 ₽" in rows[3])
        check(f"{tag}: B2 — текущий план (live), не замороженный ({rows[4:5]})",
              len(rows) == 5 and rows[4].startswith("Мой план без советов (B2)") and "+27,61 %" in rows[4] and "−1,9 п.п." in rows[4] and "−73 574 ₽" in rows[4] and "23,93" not in rows[4])
        t = c["text"] if c else ""
        check(f"{tag}: вердикты «верных 17 из 29 … 4 из 9» (по очищенным от правок задним числом), подпись про 3 мес",
              "Вердикты: акции — верных 17 из 29 созревших, облигации — верных 4 из 9 созревших" in t and "созревший — прошло 3 мес" in t and "18 из 31" not in t)
        check(f"{tag}: «пока шум — выводы после 06.01.2027»", "пока шум — выводы после 06.01.2027" in t)
        check(f"{tag}: кнопка «полный отчёт →»", c and c["btn"] == ["полный отчёт →"])
        if w < 500:
            check(f"{tag}: не шире экрана ({c and c['sw']})", c and c["sw"] <= w)
        pg.click(".dj-card .dj-open")
        pg.wait_for_selector(".report-doc", timeout=6000)
        doc = pg.evaluate("() => ({ txt: document.querySelector('.report-doc').innerText, title: document.querySelector('.ui-modal-title, #modal-title')?.textContent || '' })")
        check(f"{tag}: «полный отчёт →» открывает свежий report-2026-10-29 ({doc['title']})", "СВЕЖИЙ ОТЧЁТ" in doc["txt"] and "СТАРЫЙ" not in doc["txt"] and "29" in doc["title"])
        pg.evaluate("closeModal()")
        pg.evaluate("() => { _todayIso = () => '2027-01-07'; renderTabContent(); }")
        pg.wait_for_timeout(300)
        c2 = pg.evaluate(CARD)
        check(f"{tag}: после 06.01.2027 строки «пока шум» нет, остальное на месте", c2 and "пока шум" not in c2["text"] and "Вердикты:" in c2["text"] and c2["btn"] == ["полный отчёт →"])
        check(f"{tag}: без ошибок страницы {errs[:2]}", not errs)
        ctx.close()

    # нет файлов журнала — блока нет
    shutil.rmtree(DJ)
    ctx, pg, errs = open_page(browser, 1280)
    pg.evaluate("goToTab('history')")
    pg.wait_for_timeout(600)
    check(f"{eng_name}: нет файлов журнала — блока нет, остальная «Динамика» на месте",
          pg.evaluate("() => !document.querySelector('.dj-card') && document.getElementById('content').innerText.includes('Реализованная')"))
    check(f"{eng_name}: без ошибок страницы {errs[:2]}", not errs)
    ctx.close()
    put_journal()
    browser.close()


with sync_playwright() as p:
    for name in ("chromium", "webkit"):
        print(name)
        run(name, getattr(p, name))

shutil.rmtree(FIX.parent, ignore_errors=True)
print(f"\nviewer_decision_journal: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
