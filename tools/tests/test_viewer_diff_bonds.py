#!/usr/bin/env python3
"""Вьюер 3.106.0/3.108.0 — вкладка «Изменения» по обзорам акций И облигаций; ссылка уведомления о смене вердиктов.

Прогон настоящими браузерами (Chromium, WebKit; 1280 и 390). Данные — фикстуры viewer-live (обзоры акций 01.10 и 08.10)
плюс три синтетических обзора облигаций (20.09, 16.10, 28.10), собранные в этом тесте.

Что проверяется:
  1. вкладка «Изменения» есть при истории хотя бы одного вида; два вида — сегмент «Акции · Облигации»,
     по умолчанию открыт тот, чей обзор свежее (облигации 28.10 новее акций 08.10); один вид — сегмента нет;
     ни одного — вкладки нет;
  2. облигации — та же раскладка, что у акций: плитки «Вердикт · Качество · Доля · Добавлено · убрано», строка на бумагу;
     вердикт словами («Докупать → Держать»), качество, доля при сдвиге от 0,25 п.п. (меньше — молчит),
     новые и ушедшие бумаги; сегмент переключает вид без перезагрузки;
  3. смена вердикта по решению владельца — по полям, не по прозе (шаг 12): строка журнала плана bonds.<ISIN>.* между обзорами
     (мок GET api/pv/plan/journal) помечает «после твоего решения ДД.ММ»; обычная смена — нет;
  4. ссылка уведомления #tab=diff&kind=bond&date=ГГГГ-ММ-ДД открывает облигации и сравнивает именно этот обзор с
     предыдущим; kind=stock — акции; метка из адреса снимается; старые ссылки (#tab=actions&new=…, #card=…) работают;
  5. подзаголовок вкладки — «обзор ДД.ММ против ДД.ММ»; на телефоне страница не шире экрана; ошибок страницы нет.
  6. 3.108.0: список «Обзор» (uiSelectHTML) — все даты вида, кроме самой старой, подпись «28.10 — против 16.10»; выбор старой даты
     меняет строки и подпись; стрелки «← старее · новее →» ходят и выключаются на краях; смена вида сбрасывает дату;
     ссылка push показывает свою дату выбранной; телефон — панель не шире экрана. Клики по настоящим элементам.
Запуск: python3 tools/tests/test_viewer_diff_bonds.py  (нужен playwright; нет движка — пропуск).
"""
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
    print("viewer_diff_bonds: пропуск — нет playwright")
    sys.exit(0)

FIX = Path(tempfile.mkdtemp(prefix="diffb-")) / "cm"
shutil.copytree(REPO / "tools/tests/fixtures/viewer-live", FIX)


def bond_review(date, rows, **extra):
    import json
    per = {}
    for isin, (name, verdict, w, q, basis) in rows.items():
        per[isin] = {"name": name, "advisor_verdict": verdict, "weight_real_pct": w, "credit_quality": q, "bond_type": "ofz"}
        if basis:
            per[isin]["advisor_verdict_basis"] = basis
    doc = {"schema_version": 2, "type": "weekly-review-bond", "review_date": date, "per_bond": per, **extra}
    (FIX / f"Portfolio/weekly-reviews/weekly-review-bond-{date}.yaml").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


bond_review("2026-09-20", {
    "RU000A0001": ("ОФЗ 26001", "HOLD", 4.0, "HIGH", None), "RU000A0002": ("ОФЗ 26002", "HOLD", 2.0, "HIGH", None),
    "RU000A0003": ("Эмитент 3", "HOLD", 1.0, "HIGH", None), "RU000A0004": ("Эмитент 4", "HOLD", 1.0, "MEDIUM", None)})
bond_review("2026-10-16", {
    "RU000A0001": ("ОФЗ 26001", "TRIM", 3.9, "HIGH", None), "RU000A0002": ("ОФЗ 26002", "HOLD", 2.0, "HIGH", None),
    "RU000A0003": ("Эмитент 3", "HOLD", 1.0, "HIGH", None), "RU000A0005": ("Эмитент 5", "BUY", 0.6, "HIGH", None)})
bond_review("2026-10-28", {
    "RU000A0001": ("ОФЗ 26001", "SELL", 3.0, "HIGH", "SELL по итогам обзора"),                # смена советника + доля −0,9
    "RU000A0002": ("ОФЗ 26002", "HOLD", 2.1, "HIGH", None),                                  # доля +0,1 — молчит
    "RU000A0003": ("Эмитент 3", "HOLD", 1.0, "MEDIUM", None),                                # качество
    "RU000A0005": ("Эмитент 5", "HOLD", 0.6, "HIGH", "ADD исполнен: 26.10 владелец купил"),  # решение владельца — строкой журнала плана, не прозой
    "RU000A0006": ("Эмитент 6", "BUY", 0.8, "HIGH", None)},                                  # новая
    trades_since_prior=[], conditions_state=[])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        p = _unq(_up(self.path).path)
        if p == "/api/pv/plan/journal":   # решение владельца между обзорами 16.10 и 28.10 — правка плана облигации
            import json as _j
            body = _j.dumps({"entries": [{"ts": "2026-10-26T12:00:00+03:00", "who": "site", "path": "bonds.RU000A0005.action", "was": "BUY", "now": "HOLD", "reason": "купил"}]}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)
            return
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

SEG = "() => [...document.querySelectorAll('.diff-seg .ui-seg-btn')].map(b => b.textContent + ':' + b.getAttribute('aria-pressed'))"
ROWS = "() => [...document.querySelectorAll('#content .dif-row:not(.head)')].map(r => r.innerText.replace(/\\s+/g, ' ').trim())"
TILES = "() => [...document.querySelectorAll('#content .sec-tiles > *')].map(r => r.innerText.replace(/\\s+/g, ' ').trim())"
LEAD = "() => document.querySelector('.sec-head .ui-lead')?.textContent || ''"
OPTS = "() => [...document.querySelectorAll('.diff-bar .ui-opt .ui-opt-t')].map(o => o.textContent)"
SELV = "() => document.querySelector('.diff-bar .ui-select-t')?.textContent"
ARR = "() => [...document.querySelectorAll('.diff-pager .ui-pager-btn')].slice(0, 2).map(b => b.disabled)"   # [старее выключена, новее выключена]; третья кнопка «Сейчас» — в test_viewer_diff_periods
TABS = "() => [...document.querySelectorAll('#tabs .ui-tab')].map(b => b.textContent.trim().replace(/\\s+\\d+$/, ''))"


def open_page(browser, width, hash_=""):
    opts = {"is_mobile": True, "has_touch": True} if width < 500 else {}
    if browser.browser_type.name == "webkit":
        opts["service_workers"] = "block"
    ctx = browser.new_context(viewport={"width": width, "height": 900}, **opts)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, content_type="application/json", body="{}"))
    pg.goto(URL + hash_)
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
        check(f"{tag}: вкладка «Изменения» есть", "Изменения" in pg.evaluate(TABS))
        pg.evaluate("() => { state.diffDate = diffPeriods(diffPick())[1].id; goToTab('diff'); }")   # 3.120.1: по умолчанию «→ сейчас»; эти проверки — про пару обзоров, открываем её ссылкой с датой
        pg.wait_for_timeout(400)
        check(f"{tag}: два вида — сегмент, по умолчанию облигации (обзор свежее) ({pg.evaluate(SEG)})",
              pg.evaluate(SEG) == ["Акции:false", "Облигации:true"])
        rows = pg.evaluate(ROWS)
        check(f"{tag}: плитки облигаций {pg.evaluate(TILES)}",
              pg.evaluate(TILES) == ["ВЕРДИКТ 2", "КАЧЕСТВО 1", "ДОЛЯ 1", "ДОБАВЛЕНО · УБРАНО 1"])
        check(f"{tag}: вердикт словами и без пометки у смены советника ({rows})",
              any("ОФЗ 26001" in r and "вердикт Сократить → Продать" in r and "после твоего решения" not in r for r in rows))
        check(f"{tag}: доля сдвинулась на 0,9 п.п. — строка; на 0,1 — молчит",
              any("ОФЗ 26001" in r and "доля 3,9% → 3,0%" in r and "−0,9 п.п." in r for r in rows) and not any("ОФЗ 26002" in r for r in rows))
        check(f"{tag}: качество словами", any("Эмитент 3" in r and "кредитное качество высокое → среднее" in r for r in rows))
        check(f"{tag}: решение владельца помечено датой",
              any("Эмитент 5" in r and "вердикт Докупать → Держать" in r and "после твоего решения 26.10" in r for r in rows))
        check(f"{tag}: новая бумага в обзоре", any("Эмитент 6" in r and "новая в обзоре" in r for r in rows))
        check(f"{tag}: подзаголовок вкладки — «обзор 28.10 против 16.10»", pg.evaluate(LEAD) == "обзор 28.10 против 16.10")
        # 3.108.0: выбор обзора вручную — список «Обзор» и стрелки «← старее · новее →» (настоящие клики)
        check(f"{tag}: список — все даты, кроме самой старой (20.09), от свежей к старой ({pg.evaluate(OPTS)})",
              pg.evaluate(OPTS) == ["28.10 → сейчас", "28.10 — против 16.10", "16.10 — против 20.09"] and pg.evaluate(SELV) == "28.10 — против 16.10")
        check(f"{tag}: стрелки на свежем обзоре — «новее» включена (есть «→ сейчас»), «старее» тоже ({pg.evaluate(ARR)})", pg.evaluate(ARR) == [False, False])
        pg.click(".diff-bar .ui-select-btn")
        pg.click(".diff-bar .ui-opt:has-text('16.10 — против')")
        pg.wait_for_timeout(300)
        rows16 = pg.evaluate(ROWS)
        check(f"{tag}: выбор 16.10 меняет строки (Эмитент 5 новая, Эмитент 4 убрана) и подпись ({rows16})",
              any("Эмитент 5" in r and "новая" in r for r in rows16) and any("Эмитент 4" in r and "убрана" in r for r in rows16)
              and not any("Эмитент 6" in r for r in rows16) and pg.evaluate(LEAD) == "обзор 16.10 против 20.09"
              and pg.evaluate(SELV) == "16.10 — против 20.09")
        check(f"{tag}: на самом старом из доступных «старее» выключена, «новее» нет ({pg.evaluate(ARR)})", pg.evaluate(ARR) == [True, False])
        pg.click(".diff-pager [data-act=diff-newer]")
        pg.wait_for_timeout(300)
        check(f"{tag}: «новее →» возвращает 28.10 против 16.10", pg.evaluate(LEAD) == "обзор 28.10 против 16.10" and pg.evaluate(ARR) == [False, False])
        pg.click(".diff-pager [data-act=diff-older]")
        pg.wait_for_timeout(300)
        check(f"{tag}: «← старее» открывает 16.10 против 20.09", pg.evaluate(LEAD) == "обзор 16.10 против 20.09" and pg.evaluate(SELV) == "16.10 — против 20.09")
        pg.click(".diff-seg .ui-seg-btn:has-text('Акции')")
        pg.wait_for_timeout(300)
        check(f"{tag}: смена вида сбрасывает дату — акции 08.10 против 01.10, одна пара и «→ сейчас», «старее» выключена",
              pg.evaluate(LEAD) == "после обзора 08.10" and pg.evaluate(OPTS) == ["08.10 → сейчас", "08.10 — против 01.10"] and pg.evaluate(ARR) == [False, True])   # 3.120.1: сброс — на «→ сейчас»
        pg.click(".diff-seg .ui-seg-btn:has-text('Облигации')")
        pg.wait_for_timeout(300)
        check(f"{tag}: обратно в облигации — снова «→ сейчас» после обзора 28.10", pg.evaluate(LEAD) == "после обзора 28.10")
        if w < 500:
            check(f"{tag}: панель выбора обзора не шире экрана", pg.evaluate("document.querySelector('.diff-bar').getBoundingClientRect().right") <= w)
        pg.click(".diff-seg .ui-seg-btn:has-text('Акции')")
        pg.wait_for_timeout(300)
        check(f"{tag}: сегмент «Акции» переключает вид без перезагрузки",
              pg.evaluate(SEG) == ["Акции:true", "Облигации:false"] and "Между обзорами" in pg.evaluate("document.getElementById('content').innerText"))
        if w < 500:
            check(f"{tag}: не шире экрана", pg.evaluate("document.documentElement.scrollWidth") <= w)
        check(f"{tag}: без ошибок страницы {errs[:2]}", not errs)
        ctx.close()

    # ссылки уведомлений
    ctx, pg, errs = open_page(browser, 1280)
    pg.evaluate("location.hash = '#tab=diff&kind=bond&date=2026-10-16'")
    pg.wait_for_timeout(600)
    rows = pg.evaluate(ROWS)
    check(f"{eng_name}: ссылка kind=bond&date=16.10 — облигации, обзор 16.10 против 20.09 ({rows})",
          pg.evaluate("state.currentTab") == "diff" and pg.evaluate(SEG) == ["Акции:false", "Облигации:true"]
          and any("ОФЗ 26001" in r and "Держать → Сократить" in r for r in rows) and any("Эмитент 5" in r and "новая" in r for r in rows)
          and any("Эмитент 4" in r and "убрана" in r for r in rows))
    check(f"{eng_name}: ссылка 16.10 — список показывает её выбранной, подпись «16.10 против 20.09»",
          pg.evaluate(SELV) == "16.10 — против 20.09" and pg.evaluate(LEAD) == "обзор 16.10 против 20.09")
    check(f"{eng_name}: метка снята из адреса", "diff" not in pg.evaluate("location.hash"))
    pg.evaluate("location.hash = '#tab=diff&kind=stock&date=2026-10-08'")
    pg.wait_for_timeout(600)
    check(f"{eng_name}: ссылка kind=stock — акции", pg.evaluate(SEG) == ["Акции:true", "Облигации:false"])
    pg.evaluate("location.hash = '#tab=diff'")
    pg.wait_for_timeout(600)
    check(f"{eng_name}: ссылка без вида — свежий вид (облигации)", pg.evaluate(SEG) == ["Акции:false", "Облигации:true"])
    pg.evaluate("location.hash = '#tab=actions&new=usdrub%7Cbrent'")
    pg.wait_for_timeout(600)
    check(f"{eng_name}: прежняя ссылка монитора (#tab=actions&new=…) работает", pg.evaluate("state.currentTab") == "actions")
    pg.evaluate("location.hash = '#card=GLRX'")
    pg.wait_for_timeout(600)
    check(f"{eng_name}: прежняя ссылка #card= открывает карточку", pg.evaluate("document.querySelectorAll('#card-layer .ui-modal').length") >= 1)

    # 4.2.4: md-отчёт облигаций — ISIN и краткое название (точная фраза) становятся ссылками на карточку облигации; клик открывает карточку поверх отчёта
    pg.evaluate("() => { cardStack.length = 0; renderCards(); closeModal(); state.data.weeklyBondReviewCurrent.parsed.per_bond.RU000A0002.isin = 'RU0009999999'; }")
    pg.evaluate("(md) => showMdReportModal({ date: '2026-10-28', parsed: { rawText: md } }, 'bond')",
                "## Вывод\n\nПозиция ОФЗ 26001 остаётся, RU0009999999 без изменений, а Эмитент 3 — под наблюдением. Про ОФЗ 260010 и слово Эмитент речи нет.\n")
    pg.wait_for_selector(".report-doc", timeout=6000)
    lk = pg.evaluate("() => [...document.querySelectorAll('.report-doc .rp-tk')].map(x => x.textContent)")
    check(f"{eng_name}: в md-отчёте облигаций название и ISIN — ссылки, префикс «ОФЗ 260010» и слово «Эмитент» — нет ({lk})",
          lk == ["ОФЗ 26001", "RU0009999999", "Эмитент 3"])
    pg.click(".report-doc .rp-tk >> text=RU0009999999")
    pg.wait_for_selector("#card-layer .ui-modal", timeout=6000)
    pg.wait_for_timeout(400)
    st = pg.evaluate("() => ({ cards: cardStack.length, doc: !!document.querySelector('.report-doc'), title: document.querySelector('#card-layer .ui-modal')?.innerText.slice(0, 80) || '' })")
    check(f"{eng_name}: клик по ISIN открывает карточку облигации поверх открытого отчёта ({st})", st["cards"] == 1 and st["doc"] and "ОФЗ 26002" in st["title"])
    pg.evaluate("() => { cardStack.length = 0; renderCards(); closeModal(); }")

    # один вид и ни одного
    pg.evaluate("() => { state.data.weeklyReviewHistory = []; closeModal && closeModal(); renderTabs(); state.diffDate = diffPeriods(diffPick())[1].id; goToTab('diff'); }")
    pg.wait_for_timeout(500)
    check(f"{eng_name}: только облигации — вкладка есть, сегмента нет",
          "Изменения" in pg.evaluate(TABS) and pg.evaluate(SEG) == [] and "Что изменилось по облигациям" in pg.evaluate("document.getElementById('content').innerText"))
    pg.evaluate("() => { state.data.weeklyBondReviewHistory = []; renderTabs(); }")
    check(f"{eng_name}: ни у одного вида истории — вкладки нет", "Изменения" not in pg.evaluate(TABS))
    check(f"{eng_name}: без ошибок страницы {errs[:2]}", not errs)
    ctx.close()
    browser.close()


with sync_playwright() as p:
    for name in ("chromium", "webkit"):
        print(name)
        run(name, getattr(p, name))

shutil.rmtree(FIX.parent, ignore_errors=True)
print(f"\nviewer_diff_bonds: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
