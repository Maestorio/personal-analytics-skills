#!/usr/bin/env python3
"""Вьюер 3.120.0: «Изменения» по периодам обзоров + события «разбор» и «план изменён» в «Истории» карточки.

Решение владельца 30.10: изменения не из обзора (разбор бумаги, смена гейта, условия, план) не попадали в «Изменения».
Теперь периоды: «28.10 → сейчас», затем пары «28.10 — против 26.10» …; в каждом — блок «Между обзорами» (события по бумагам).
Фикстура — ЖИВЫЕ файлы: обзоры акций 16.10, 26.10, 28.10 (+md), обзоры облигаций 16.10, 28.10, решения decisions/, conditions@2 + состояние,
отчёты 23.10 (YDEX·MDMG·PLZL) и 29.10 (GMKN); время обзоров — mtime md (как на сервере); журнал плана — мок.
Контракты:
  1. Первый пункт выбора — «28.10 → сейчас», за ним пары; по клику на вкладку открыт «→ сейчас», ссылка с датой пары открывает пару (3.120.1).
  2. «→ сейчас»: плиток сравнения нет; подзаголовок «после обзора 28.10»; GMKN — разбор и решение 29.10 (source.doc решения — этот отчёт) одной
     строкой «разбор → решение: наблюдать, срок 13.12» (клик — отчёт), смены плана после 28.10; «сработало» и «сделано» одного условия в один
     день — одной строкой «сработало и закрыто владельцем» (X5) / «… на сайте» (TMON).
  3. Пара «28.10 — против 26.10»: прежние плитки + «Между обзорами» с событиями (26.10; 28.10], без событий после 28.10;
     событие 26.10 без времени (решение CNRU) в этот период не попадает (в день обзора — «до»).
  4. Граница по времени: запись плана 28.10 11:00 (до обзора 12:08) — в паре, 28.10 13:00 — в «→ сейчас».
  5. «Сейчас» (с любой пары) возвращает на «→ сейчас», на нём кнопка неактивна; «← старее» / «новее →» листают по списку.
  6. «Облигации» — свои периоды и события; клик по событию открывает отчёт / карточку бумаги.
  7. Карточка GMKN → «История»: «разбор 29.10» одной строкой вместе с решением (гейт «на пересмотре»), строка «план изменён».
  9. 3.121.0: карточка открывается у любой бумаги блока «Между обзорами» (1400 и 390): проданная (запись per_instrument_xirr_closed +
     смена плана в периоде) → заголовок-кнопка, карточка с «Итог по бумаге»; облигация без текущего обзора и без позиции (обзор только в истории,
     условие в периоде) → карточка облигации; бумага без каких-либо данных — не кнопка.
  10. 3.122.0 (1400 и 390): смены плана одного поля между опорными событиями (разбор, гейт, условие, сделка) сливаются в одну строку
      «первое было → последнее стало · N правок»; вернулось к исходному — строки нет; опора посередине — две строки; доля и действие не сливаются;
      хвостовой стрелки «→» у строки-ссылки нет; клик по событию проданной бумаги открывает её карточку на «Истории», где все правки на месте;
      сделка (купил/продал по снапшотам) — отдельная строка и опора.
  8. Подпись «журнал плана — с 27.10» у периода раньше 27.10 и при недоступном журнале. Телефон 390: три кнопки в ряд. Ошибок нет.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_diff_periods.py
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
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
    import yaml
except ImportError:
    print("viewer_diff_periods: пропуск — нет playwright/yaml")
    sys.exit(0)

sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as hub_api  # noqa: E402

FIX = Path(tempfile.mkdtemp(prefix="diffper-"))
BOND = "RU000A106E90"


def local_utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


SOLD, OLDBOND, NODATA = "SOLDX", "RU000A0ZZ001", "NODATAX"
SOLD_REC = {"xirr": 0.2337, "pnl_rub": 12345.6, "buy_total_rub": 100000.0, "sell_total_rub": 105000.0, "dividends_rub": 7000.0, "coupons_rub": 0.0,
            "amortization_rub": 0.0, "corr_buy_rub": -600.0, "corr_sell_rub": 0.0, "first_trade_date": "2025-03-10", "last_trade_date": "2026-10-12",
            "close_date": "2026-10-12", "holding_days": 581, "qty_now": 0, "market_value_rub": 0, "price_source": "closed"}
JOURNAL = [
    {"ts": local_utc(2026, 10, 29, 11, 0), "who": "site", "path": f"stocks.{SOLD}.plan_pct", "was": 1.0, "now": 0.0, "reason": None},
    {"ts": local_utc(2026, 10, 29, 11, 5), "who": "site", "path": f"stocks.{NODATA}.plan_pct", "was": 1.0, "now": 0.5, "reason": None},
    {"ts": local_utc(2026, 10, 27, 9, 0), "who": "site", "path": "stocks.GMKN.plan_pct", "was": 3.0, "now": 2.0, "reason": None},
    {"ts": local_utc(2026, 10, 28, 11, 0), "who": "site", "path": "stocks.LSNGP.plan_pct", "was": 2.0, "now": 2.5, "reason": None},
    {"ts": local_utc(2026, 10, 28, 13, 0), "who": "site", "path": "stocks.LSNGP.plan_pct", "was": 2.5, "now": 3.0, "reason": None},
    {"ts": local_utc(2026, 10, 29, 10, 0), "who": "site", "path": "stocks.GMKN.plan_pct", "was": 2.0, "now": 3.0, "reason": None},
    {"ts": local_utc(2026, 10, 29, 10, 5), "who": "site", "path": "stocks.GMKN.user_status", "was": None, "now": "DONE", "reason": None},
]


SERA, SERB, SERC, SERD, SERT = "SERAX", "SERBX", "SERCX", "SERDX", "SERTX"
SER_ROWS = [   # (тикер, день, ч, мин, поле, было, стало) — всё после обзора 28.10 12:08, т.е. в периоде «→ сейчас»
    (SERA, 29, 10, 0, "plan_pct", 1.0, 2.0), (SERA, 29, 10, 10, "plan_pct", 2.0, 3.0), (SERA, 29, 10, 20, "plan_pct", 3.0, 1.5),
    (SERB, 29, 10, 0, "plan_pct", 1.0, 2.0), (SERB, 29, 10, 10, "plan_pct", 2.0, 1.0),
    (SERC, 29, 10, 0, "user_plan", "WAIT", "HOLD"), (SERC, 29, 10, 10, "user_plan", "HOLD", "BUY"),
    (SERC, 30, 10, 0, "user_plan", "BUY", "HOLD"), (SERC, 30, 10, 10, "user_plan", "HOLD", "SELL"),
    (SERD, 29, 10, 0, "plan_pct", 1.0, 2.0), (SERD, 29, 10, 5, "user_plan", "WAIT", "HOLD"),
    (SERD, 29, 10, 10, "plan_pct", 2.0, 4.0), (SERD, 29, 10, 15, "user_plan", "HOLD", "BUY"),
    (SERT, 29, 10, 0, "plan_pct", 1.0, 2.0), (SERT, 30, 10, 0, "plan_pct", 2.0, 3.0),
]
JOURNAL += [{"ts": local_utc(2026, 10, d, h, mi), "who": "site", "path": f"stocks.{t}.{f}", "was": a, "now": b, "reason": None} for (t, d, h, mi, f, a, b) in SER_ROWS]


def build():
    shutil.rmtree(FIX, ignore_errors=True)
    shutil.copytree(REPO / "tools/tests/fixtures/viewer-live", FIX)
    for part in ("bond-actions", "superseded", "conditions-pack", "diff-periods"):
        shutil.copytree(REPO / "tools/tests/fixtures" / part, FIX, dirs_exist_ok=True)
    wr = FIX / "Portfolio/weekly-reviews"
    for name, (mo, d, h, mi) in {"stock-2026-10-16": (10, 16, 14, 15), "stock-2026-10-26": (10, 26, 15, 9), "stock-2026-10-28": (10, 28, 12, 8),
                                 "bond-2026-10-16": (10, 16, 14, 1), "bond-2026-10-28": (10, 28, 12, 14)}.items():
        ts = datetime(2026, mo, d, h, mi).timestamp()
        os.utime(wr / f"weekly-review-{name}.md", (ts, ts))
    cp = FIX / "Portfolio/conditions.yaml"   # условие по выпуску облигации (conditions@2): создано 20.10, закрыто владельцем 29.10
    c = yaml.safe_load(cp.read_text(encoding="utf-8"))
    c["conditions"].append({"id": "bond-test-cond", "version": 1, "key": BOND, "kind": "review", "trigger": {"type": "date", "value": "2026-11-30"},
                            "event_text": "оферта по выпуску", "while_pending": {"verdict": "HOLD"}, "on_trigger": {"action": "run_analysis", "text": "разобрать"},
                            "on_expiry": None, "not_before": None, "valid_until": None, "source": {"kind": "owner", "doc": None},
                            "created_at": "2026-10-20T00:00:00+03:00", "created_by": "owner", "withdrawn": None, "superseded_by": None, "note": "тест"})
    cp.write_text(yaml.safe_dump(c, allow_unicode=True, sort_keys=False), encoding="utf-8")
    sp = FIX / "Portfolio/conditions-state.json"
    st = json.loads(sp.read_text(encoding="utf-8"))
    st["events"].append({"condition_id": "bond-test-cond", "version": 1, "event": "done", "at": "2026-10-29T00:00:00+03:00", "by": "owner", "data": {}})
    for e in st["events"]:   # как в живом состоянии: X5 «сделано» отметил владелец (TMON остаётся «сайт»)
        if e["condition_id"] == "x5-ifrs3q-review" and e["event"] == "done":
            e["by"] = "owner"
    sp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")


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

OPTS = "() => [...document.querySelectorAll('.diff-bar .ui-opt .ui-opt-t')].map(o => o.textContent)"
SELV = "() => document.querySelector('.diff-bar .ui-select-t')?.textContent"
ARR = "() => ['older','newer','now'].map(a => document.querySelector(`.diff-pager [data-act=diff-${a}]`).disabled)"
LEAD = "() => document.querySelector('.sec-head .ui-lead')?.textContent || ''"


def open_diff(p, w=1400, h=1000, journal="ok", via="pair"):
    browser = p.chromium.launch()
    ctx = browser.new_context(service_workers="block", viewport={"width": w, "height": h})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "502" not in m.text and "404" not in m.text else None)
    pg.route("**/api/pv/plan*", lambda r: r.fulfill(status=502, body="{}"))
    pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, body="{}"))
    if journal == "ok":
        pg.route("**/api/pv/plan/journal*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"entries": JOURNAL})))
    pg.goto(URL)
    pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
    pg.wait_for_function("() => state.data && state.data.portfolioLatest && state.data.weeklyReviewCurrent && state.data.weeklyBondReviewCurrent && state.data.decisions.length && state.data.conditions", timeout=20000)
    if via == "click":   # 3.120.1: реальная вкладка, без каких-либо действий — открыт «→ сейчас»
        pg.locator("#tabs .ui-tab", has_text="Изменения").first.click()
    else:   # ссылка с датой пары, как из push
        pg.evaluate("() => { state.diffDate = diffPeriods(diffPick())[1].id; goToTab('diff'); }")
    pg.wait_for_selector(".diff-bar .ui-select-t", timeout=10000)
    pg.wait_for_selector(".dif-between", timeout=10000)
    pg.wait_for_timeout(500)   # журнал плана и перерисовка
    return browser, pg, errs


def pick(pg, text):
    pg.locator(".diff-bar .ui-select-btn").first.click()
    pg.locator(f".diff-bar .ui-opt:has-text('{text}')").first.click()
    pg.wait_for_timeout(500)


def block(pg):
    return pg.locator(".dif-between").first.inner_text()


def group(pg, t):
    return pg.locator(f".dif-between .dif-evt-g[data-ticker='{t}']")


def kinds(pg, t):
    return group(pg, t).locator(".tl-k").all_inner_texts()


def dates(pg):
    return pg.evaluate("() => [...document.querySelectorAll('.dif-between .tl-d')].map(e => e.childNodes[0].textContent)")


INJECT = """([sold, rec, oldbond, nodata]) => {
  const d = state.data, port = currentPort();
  port.per_instrument_xirr_closed = { ...(port.per_instrument_xirr_closed || {}), [sold]: rec };
  (d.weeklyReviewHistory[d.weeklyReviewHistory.length - 1].parsed.per_stock ||= {})[sold] = {};
  (d.weeklyReviewHistory[d.weeklyReviewHistory.length - 1].parsed.per_stock)[nodata] = {};
  (d.weeklyBondReviewHistory[d.weeklyBondReviewHistory.length - 1].parsed.per_bond ||= {})[oldbond] = { short_name: 'Старая облигация', weight_real_pct: 0.4 };
  d.conditions.parsed.conditions.push({ id: 'old-bond-c', version: 1, key: oldbond, kind: 'review', trigger: { type: 'date', value: '2026-11-30' },
    on_trigger: { action: 'run_analysis', text: 'оферта' }, created_at: '2026-10-29T00:00:00+03:00', created_by: 'owner', withdrawn: null });
  dsInvalidate(); renderTabContent({ fade: false });
}"""


def links(p, w, h):
    browser, pg, errs = open_diff(p, w, h, via="click")
    pg.evaluate(INJECT, [SOLD, SOLD_REC, OLDBOND, NODATA])
    pg.wait_for_timeout(500)
    tag = f"[{w}] 3.121 "
    hb = group(pg, SOLD).locator(".dif-evt-open")
    check(f"{tag}проданная бумага: заголовок группы — кнопка", group(pg, SOLD).count() == 1 and hb.count() == 1)
    check(f"{tag}бумага без данных: группа есть, кнопки нет", group(pg, NODATA).count() == 1 and group(pg, NODATA).locator(".dif-evt-open").count() == 0)
    if hb.count():
        hb.click()
        pg.wait_for_selector("#card-layer .ui-modal", timeout=5000)
        pg.wait_for_timeout(500)
        pg.evaluate("() => document.querySelector('.card-win [data-act=card-sub][data-v=ret]').click()")
        pg.wait_for_timeout(300)
        blk = pg.evaluate("() => (document.querySelector('.card-win .card-closed') || {textContent: ''}).textContent").lower()
        check(f"{tag}карточка проданной: «Итог по бумаге» ({blk[:60]!r})", blk.strip().startswith("итог по бумаге"))
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(400)
    pg.click(".diff-seg [data-v=bond]")
    pg.wait_for_timeout(500)
    bh = group(pg, OLDBOND).locator(".dif-evt-open")
    check(f"{tag}облигация без текущего обзора: заголовок — кнопка", group(pg, OLDBOND).count() == 1 and bh.count() == 1)
    if bh.count():
        bh.click()
        pg.wait_for_selector("#card-layer .ui-modal", timeout=5000)
        pg.wait_for_timeout(500)
        check(f"{tag}карточка облигации открыта", "Старая облигация" in pg.locator("#card-layer .ui-modal").last.inner_text())
    check(f"{tag}не шире экрана, ошибок нет ({errs[:2]})", pg.evaluate(f"() => document.documentElement.scrollWidth <= {w}") and not errs)
    browser.close()


SER_INJECT = """([tick, sold, rec]) => {
  const d = state.data, port = currentPort();
  port.per_instrument_xirr_closed = { ...(port.per_instrument_xirr_closed || {}), [sold]: rec, };
  const ps = d.weeklyReviewHistory[d.weeklyReviewHistory.length - 1].parsed.per_stock ||= {};
  for (const t of [...tick, sold]) ps[t] = {};
  d.conditions.parsed.conditions.push({ id: 'ser-c', version: 1, key: tick[2], kind: 'trade', trigger: { type: 'date', value: '2026-11-30' },
    on_trigger: { action: 'set_verdict', verdict: 'SELL', text: 'проверка' }, created_at: '2026-10-30T00:00:00+03:00', created_by: 'owner', withdrawn: null });
  dsInvalidate();
  // сделка по SERTX: между двумя правками плана; снапшоты синтетические
  const mk = (date, qty) => ({ date, parsed: { as_of_date: date, holdings: [{ ticker: tick[4], asset_type: 'stock', qty, account: 'main' }] } });
  d.portfolioHistory.push(mk('2026-10-29', 10), mk('2026-10-30', 25));
  planJournalEnsure(); renderTabContent({ fade: false });
}"""
GLRX = SERA   # синтетическая проданная (в живой фикстуре GLRX — реальная позиция: клик открывал бы карточку и без правки)
GLRX_REC = dict(SOLD_REC, last_trade_date="2026-10-20", close_date="2026-10-20")


def collapse(p, w, h):
    browser, pg, errs = open_diff(p, w, h, via="click")
    pg.evaluate(SER_INJECT, [[SERA, SERB, SERC, SERD, SERT], GLRX, GLRX_REC])
    pg.wait_for_timeout(500)
    tag = f"[{w}] 3.122 "
    tx = lambda t: group(pg, t).locator(".tl .ui-text").all_inner_texts()
    a = tx(SERA)
    check(f"{tag}серия без опор: одна строка «1,0 % → 1,5 %» с числом правок ({a})", len(a) == 1 and "1,0 % → 1,5 %" in a[0] and "3 правки" in a[0])
    check(f"{tag}серия вернулась к исходному: строк нет, группы нет", group(pg, SERB).count() == 0)
    c = tx(SERC)
    check(f"{tag}опора (условие) посередине: две строки плана по обе стороны ({c})",
          sum("действие по плану" in x for x in c) == 2 and any("создано" in x for x in c)
          and any("→ продать" in x or "→ Продать" in x or "SELL" in x for x in c))
    dd = tx(SERD)
    check(f"{tag}доля и действие не сливаются: по строке на поле ({dd})", len(dd) == 2 and any("план изменён: 1,0 % → 4,0 %" in x for x in dd) and any("действие по плану" in x for x in dd))
    t = tx(SERT)
    kt = kinds(pg, SERT)
    check(f"{tag}сделка — отдельная строка «купил 15 шт.» и опора: правки до и после не сливаются ({t} {kt})",
          "сделка" in kt and any("купил 15 шт." in x for x in t) and sum("план изменён" in x for x in t) == 2)
    ends = pg.evaluate("() => [...document.querySelectorAll('.dif-between .tl.tl-link .ui-text')].map(e => e.textContent.trim().endsWith('→'))")
    check(f"{tag}у строк-ссылок нет хвостовой стрелки ({len(ends)})", len(ends) > 0 and not any(ends) and pg.locator(".dif-between .tl-go").count() == 0)
    g = group(pg, GLRX).locator(".tl").first
    check(f"{tag}проданная бумага: строка события есть", group(pg, GLRX).locator(".tl").count() == 1)
    g.click()
    pg.wait_for_selector("#card-layer .ui-modal", timeout=5000)
    pg.wait_for_timeout(500)
    check(f"{tag}клик по событию проданной бумаги открывает её карточку на «Истории»", pg.locator("#card-layer .card-tl").count() == 1 and SERA in pg.locator("#card-layer .ui-modal").last.inner_text())
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(300)
    # «История» остаётся полным журналом: открыть SERAX через заголовок
    group(pg, SERA).locator(".dif-evt-open").click()
    pg.wait_for_selector("#card-layer .ui-modal", timeout=5000)
    pg.wait_for_timeout(500)
    pg.evaluate("() => { const b = [...document.querySelectorAll('#card-layer .ui-modal [role=tab], #card-layer .ui-modal .ui-seg-btn')].find(x => /История/.test(x.textContent)); if (b) b.click(); }")
    pg.wait_for_timeout(500)
    rows = pg.evaluate("() => [...document.querySelectorAll('#card-layer .card-tl .tl .ui-text')].map(r => r.textContent)")
    check(f"{tag}«История» карточки — все три правки, без схлопывания ({rows})", sum("план изменён" in r for r in rows) == 3)
    check(f"{tag}не шире экрана, ошибок нет ({errs[:2]})", pg.evaluate(f"() => document.documentElement.scrollWidth <= {w}") and not errs)
    browser.close()


def main():
    with sync_playwright() as p:
        try:
            p.chromium.launch().close()
        except Exception as e:
            print(f"viewer_diff_periods: пропуск — {str(e).splitlines()[0][:80]}")
            return
        build()
        browser, pg, errs = open_diff(p)
        pg.locator(".diff-bar .ui-select-btn").first.click()
        opts = pg.evaluate(OPTS)
        pg.keyboard.press("Escape")
        check(f"список периодов: первым «28.10 → сейчас», затем пары ({opts})",
              opts[:4] == ["28.10 → сейчас", "28.10 — против 26.10", "26.10 — против 16.10", "16.10 — против 08.10"])
        check("ссылка с датой пары открывает пару «28.10 — против 26.10»", pg.evaluate(SELV) == "28.10 — против 26.10")
        check("пара: прежние плитки сравнения на месте", pg.locator(".sec-tiles").count() > 0)
        check("пара: блок «Между обзорами» после плиток", pg.evaluate("() => { const t = document.querySelector('.sec-tiles'), b = document.querySelector('.dif-between'); return !!(t && b && (t.compareDocumentPosition(b) & 4)); }"))
        txt = block(pg)
        check(f"пара 26–28: события 27–28.10 есть (LSNGP, DATA, NVTK) ({txt[:200]!r})", all(group(pg, t).count() == 1 for t in ("LSNGP", "DATA", "NVTK")))
        ds = dates(pg)
        check(f"пара 26–28: ни одного события после 28.10 и ни одного ≤ 26.10 ({sorted(set(ds))})", ds and all(d in ("27.10", "28.10") for d in ds))
        check("пара: из условий только создано/сработало/закрыто/истекло — правки (NVTK 27.10) и переносы (LSNGP 28.10) не шумят",
              "изменено" not in group(pg, "NVTK").inner_text() and "перенесено" not in group(pg, "LSNGP").inner_text())
        check("пара: гейт CNRU 26.10 без времени — в день прошлого обзора, в период не входит", group(pg, "CNRU").count() == 0)
        check("пара: от GMKN только смена плана 27.10; разбора и гейта 29.10 нет", kinds(pg, "GMKN") == ["план"] and "29.10" not in txt)
        lsn = group(pg, "LSNGP").inner_text()
        check(f"граница по времени: план LSNGP 28.10 11:00 (до обзора 12:08) — в паре, 13:00 — нет ({lsn[:160]!r})",
              "2,0 % → 2,5 %" in lsn and "2,5 % → 3,0 %" not in lsn)
        check("пара: подпись «журнал плана — с 27.10» (период начинается 26.10)", "журнал плана — с 27.10" in txt)
        check("подзаголовок вкладки — «обзор 28.10 против 26.10»", pg.evaluate(LEAD) == "обзор 28.10 против 26.10")
        check("пара: «Сейчас» активна, «новее →» активна", pg.evaluate(ARR) == [False, False, False])

        # «Сейчас» с пары
        pg.click(".diff-pager [data-act=diff-now]")
        pg.wait_for_timeout(500)
        check("«Сейчас» ведёт на «28.10 → сейчас»", pg.evaluate(SELV) == "28.10 → сейчас")
        check("на «→ сейчас»: плиток сравнения нет", pg.locator(".sec-tiles").count() == 0)
        check("на «→ сейчас» «Сейчас» и «новее →» неактивны, «старее» активна", pg.evaluate(ARR) == [False, True, True])
        check("подзаголовок — «после обзора 28.10»", pg.evaluate(LEAD) == "после обзора 28.10" and "после обзора 28.10" in block(pg))
        txt = block(pg)
        gk = kinds(pg, "GMKN")
        g29 = [r for r in group(pg, "GMKN").locator(".tl").all_inner_texts() if r.startswith("29.10")]
        check(f"GMKN: разбор и решение 29.10 (source.doc решения = этот отчёт) — одной строкой «разбор → решение: наблюдать, срок 13.12» ({gk}, {g29})",
              gk.count("решение") == 1 and "разбор" not in gk and sum("разбор → решение: наблюдать, срок 13.12" in r for r in g29) == 1
              and not any(r.split("\n")[-1].startswith("Разбор GMKN") for r in g29))
        check("GMKN: 29.10 17:40 — время отчёта", "17:40" in group(pg, "GMKN").inner_text())
        gt = group(pg, "GMKN").inner_text()
        check(f"GMKN: смены плана после 28.10 — «план изменён: 2,0 % → 3,0 %» и статус ({gt[:300]!r})", "план изменён: 2,0 % → 3,0 %" in gt and "статус: — → сделал" in gt)
        check("LSNGP: план 28.10 13:00 (после обзора 12:08) — здесь; 11:00 — нет", "2,5 % → 3,0 %" in group(pg, "LSNGP").inner_text() and "2,0 % → 2,5 %" not in group(pg, "LSNGP").inner_text())
        check("→ сейчас: события 28.10 без времени (DATA) сюда не попадают", group(pg, "DATA").count() == 0)
        check("→ сейчас: подписи «журнал плана — с 27.10» нет (журнал есть, период позже)", "журнал плана" not in txt)
        x5, tm = group(pg, "X5").inner_text(), group(pg, "TMON").inner_text()
        check(f"→ сейчас: «сработало (скрипт)» и «сделано (владелец)» X5 одного дня — одной строкой «сработало и закрыто владельцем» ({x5[:300]!r})",
              "сработало и закрыто владельцем: " in x5 and "сработало: " not in x5 and "сделано: " not in x5)
        check(f"→ сейчас: TMON (закрыто сайтом) — «сработало и закрыто на сайте» ({tm[:200]!r})", "сработало и закрыто на сайте: " in tm and "сработало: " not in tm)

        # клик по событию
        group(pg, "GMKN").locator(".tl", has_text="разбор → решение").first.click()
        pg.wait_for_selector("#modal-overlay", timeout=5000)
        pg.wait_for_timeout(400)
        check("клик по склеенной строке «разбор → решение» открывает отчёт GMKN", "Норникель" in pg.locator("#modal-overlay").inner_text())
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(400)
        pg.evaluate("() => _openSecCard('GMKN', 'stock')")   # то, что делает клик по несклеенному решению
        pg.wait_for_selector("#card-layer .ui-modal", timeout=5000)
        pg.wait_for_timeout(600)
        card = pg.locator("#card-layer .ui-modal").last.inner_text()
        check("решение без разбора в тот же день открывает карточку GMKN на «Истории»", pg.locator("#card-layer .card-tl").count() == 1 and "журнал решений по бумаге" in card.lower())
        rows29 = pg.evaluate("() => [...document.querySelectorAll('#card-layer .card-tl .tl')].filter(r => r.querySelector('.tl-d').childNodes[0].textContent === '29.10').map(r => r.innerText)")
        check(f"История GMKN: 29.10 — «разбор» одной строкой с решением ({rows29})",
              sum('разбор' in r for r in rows29) == 1 and any('разбор' in r and 'решение: наблюдать' in r for r in rows29) and not any('гейт' in r for r in rows29)
              and pg.locator("#card-layer .card-tl .tl-k.report").count() == 0)
        check("История GMKN: строка «план изменён»", any("план изменён" in r for r in rows29))
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(400)

        # листание
        pg.click(".diff-pager [data-act=diff-older]")
        pg.wait_for_timeout(400)
        check("«← старее» с «→ сейчас» → пара 28.10 против 26.10", pg.evaluate(SELV) == "28.10 — против 26.10")
        pg.click(".diff-pager [data-act=diff-older]")
        pg.wait_for_timeout(400)
        check("«← старее» → пара 26.10 против 16.10", pg.evaluate(SELV) == "26.10 — против 16.10")
        t2 = block(pg)
        ds = dates(pg)
        check(f"пара 26–16: разбор YDEX·MDMG·PLZL 23.10 в событиях ({sorted(set(ds))})", "разбор" in kinds(pg, "YDEX") and group(pg, "MDMG").count() == 1 and group(pg, "PLZL").count() == 1)
        check("пара 26–16: решение CNRU 26.10 (день обзора, время неизвестно) — здесь", group(pg, "CNRU").count() == 1)
        check("пара 26–16: событий после 26.10 нет", ds and all(d.split('.')[1] == "10" and 17 <= int(d.split('.')[0]) <= 26 for d in ds))
        pg.click(".diff-pager [data-act=diff-now]")
        pg.wait_for_timeout(400)
        check("«Сейчас» с самой старой стороны — снова «→ сейчас»", pg.evaluate(SELV) == "28.10 → сейчас")

        # облигации
        pg.click(".diff-seg [data-v=bond]")
        pg.wait_for_timeout(500)
        pg.locator(".diff-bar .ui-select-btn").first.click()
        bopts = pg.evaluate(OPTS)
        pg.keyboard.press("Escape")
        check(f"облигации — свои периоды ({bopts})", bopts == ["28.10 → сейчас", "28.10 — против 16.10"])
        check("облигации: смена вида сбрасывает на «→ сейчас»", pg.evaluate(SELV) == "28.10 → сейчас")
        pg.click(".diff-pager [data-act=diff-older]")
        pg.wait_for_timeout(400)
        check("облигации, пара: условие по выпуску 20.10", group(pg, BOND).count() == 1 and "создано" in group(pg, BOND).inner_text())
        check("облигации: акций в блоке нет", group(pg, "GMKN").count() == 0)
        pg.click(".diff-pager [data-act=diff-now]")
        pg.wait_for_timeout(400)
        check("облигации, «→ сейчас»: закрытие условия 29.10 («сделано»), создания 20.10 нет",
              "сделано" in group(pg, BOND).inner_text() and "создано" not in group(pg, BOND).inner_text())
        group(pg, BOND).locator(".tl").first.click()
        pg.wait_for_timeout(600)
        check("клик по событию облигации открывает карточку на «Истории»", pg.locator("#card-layer .card-tl").count() == 1)
        pg.keyboard.press("Escape")
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # 3.120.1: вкладка по умолчанию — «→ сейчас»; заголовок группы открывает карточку
        for (w, h) in ((1400, 1000), (390, 844)):
            browser, pg, errs = open_diff(p, w, h, via="click")
            check(f"{w}: вкладка открыта на «28.10 → сейчас» без действий", pg.evaluate(SELV) == "28.10 → сейчас" and pg.locator(".sec-tiles").count() == 0)
            check(f"{w}: «Сейчас» неактивна на старте", pg.evaluate(ARR) == [False, True, True])
            hb = group(pg, "GMKN").locator(".dif-evt-open")
            check(f"{w}: заголовок группы GMKN — кнопка", hb.count() == 1)
            check(f"{w}: зона нажатия заголовка ≥ 40px", hb.evaluate("e => e.getBoundingClientRect().height") >= 39.5)
            check(f"{w}: нет горизонтальной прокрутки", pg.evaluate(f"() => document.documentElement.scrollWidth <= {w}"))
            hb.click()
            pg.wait_for_selector("#card-layer .ui-modal", timeout=5000)
            pg.wait_for_timeout(500)
            check(f"{w}: клик по заголовку открывает карточку GMKN", "GMKN · " in pg.locator("#card-layer .ui-modal").last.inner_text())
            pg.evaluate("() => { const b = [...document.querySelectorAll('#card-layer .ui-modal [role=tab], #card-layer .ui-modal .ui-seg-btn')].find(x => /История/.test(x.textContent)); if (b) b.click(); }")
            pg.wait_for_timeout(500)
            rows = pg.evaluate("() => [...document.querySelectorAll('#card-layer .card-tl .tl')].map(r => r.innerText)")
            check(f"{w}: в «Истории» карточки — «разбор 29.10» ({len(rows)})", any("разбор" in r and "29.10" in r for r in rows))
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(400)
            group(pg, "GMKN").locator(".tl", has_text="разбор → решение").first.click()
            pg.wait_for_selector("#modal-overlay", timeout=5000)
            check(f"{w}: клик по строке события открывает отчёт, а не карточку", "Норникель" in pg.locator("#modal-overlay").inner_text() and pg.locator("#card-layer .ui-modal").count() == 0)
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(300)
            pg.click(".diff-seg [data-v=bond]")
            pg.wait_for_timeout(500)
            bh = group(pg, BOND).locator(".dif-evt-open")
            check(f"{w}: облигация в «Облигациях» — заголовок-кнопка", bh.count() == 1)
            if bh.count():
                bh.click()
                pg.wait_for_selector("#card-layer .ui-modal", timeout=5000)
                check(f"{w}: карточка облигации открыта", pg.locator("#card-layer .ui-modal").count() >= 1)
            check(f"{w}: ошибок страницы нет ({errs[:2]})", not errs)
            browser.close()

        for (w, h) in ((1400, 1000), (390, 844)):
            links(p, w, h)
            collapse(p, w, h)

        # журнал плана недоступен
        browser, pg, errs = open_diff(p, journal="none")
        check("журнал плана недоступен: подпись «журнал плана — с 27.10»", "журнал плана — с 27.10" in block(pg))
        pg.click(".diff-pager [data-act=diff-now]")
        pg.wait_for_timeout(400)
        check("журнал недоступен, «→ сейчас»: подпись есть, строк «план изменён» нет", "журнал плана — с 27.10" in block(pg) and "план изменён" not in block(pg))
        check("журнал недоступен: разбор и решение GMKN на месте (одной строкой)", "разбор → решение" in group(pg, "GMKN").inner_text())
        browser.close()

        # телефон
        browser, pg, errs = open_diff(p, 390, 844)
        boxes = pg.evaluate("() => ['older','newer','now'].map(a => { const r = document.querySelector(`.diff-pager [data-act=diff-${a}]`).getBoundingClientRect(); return [r.top, r.left, r.right, r.height]; })")
        check(f"390: три кнопки в одном ряду ({boxes})", len({round(b[0]) for b in boxes}) == 1)
        check("390: кнопки целиком в экране", all(b[1] >= 0 and b[2] <= 390 for b in boxes))
        check("390: страница не шире экрана", pg.evaluate("() => document.documentElement.scrollWidth <= 390"))
        pg.click(".diff-pager [data-act=diff-older]")
        pg.wait_for_timeout(400)
        pg.click(".diff-pager [data-act=diff-now]")
        pg.wait_for_timeout(400)
        check("390: «Сейчас» работает", pg.evaluate(SELV) == "28.10 → сейчас")
        check("390: блок событий не шире экрана", pg.evaluate("() => document.querySelector('.dif-between').getBoundingClientRect().right <= 390"))
        check(f"390: ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

    print(f"Итого: {passed} из {passed + failed}")
    sys.exit(1 if failed else 0)


main()
