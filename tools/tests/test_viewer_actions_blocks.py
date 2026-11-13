#!/usr/bin/env python3
"""Вьюер 4.2.0, проход читаемости, пачка 3 «структура» (аудит 31.10: F1, F10, F15, §4 строка 12; макет владельца 03.11) — настоящий Chromium.

Фикстура: viewer-live + superseded + conditions-pack + stress-roles (ссылки стресс → макросценарии → прогнозы, у Brent,
ставки ЦБ и санкций есть новее) во временной папке; снапшот 27.10 — копия 08.10, у MDMG количество меньше (сделка после
решения «сократить» 19.09); план сайта (api/pv/plan) и журнал плана подменены в браузере.
Контракты (правила отнесения — только по полям):
  Сделать — GLRX: вердикт «продать» и план «продать» — ОДНА строка, план первым; SBER: план «привести к плану», «Сейчас» —
      срез → «продать N лотов по плану «привести к плану»» со ссылкой «Доли и цели →», фразы для Claude нет;
      стресс на заменённом прогнозе — строка «стресс посчитан на заменённом прогнозе … → перегнать» с фразой перегона.
  Проверить — строки обзора «держать» с проверкой «срочно» (YDEX, OZON, LSNGP) по пункту; «сделал» — отметка на устройстве
      (localStorage, 14 дней), строка уходит в «Сделано», счётчик −1; T со статусом «поставил заявку» — «заявка стоит с 27.10 —
      исполнилась?», «сделал» → POST api/pv/plan/set {stocks.T.user_status: DONE}.
  Ждём — YDEX: план «докупать», «Сейчас» стоит → «докупка по плану «докупать» стоит: <причина словами>»; MOEX «отложил» —
      «отложен 28.10»; ждущие условия по бумагам портфеля; пункты проверки и катализаторы строк «желательно».
  К сведению — «держать» с проверкой «желательно» (MDMG, PLZL, MBNK, NVTK): только тикеры, без прозы; не в счётчике.
  Сделано — исполнено сделкой по последнему слову (11, 03.11): PLZL обзор «сократить» 28.10 + продажа 29.10 — «сократить —
      исполнено сделкой 29.10 (обзор 28.10)», та же подпись в карточке; MDMG (решение «сократить» 23.10, продажа 27.10, обзор
      «держать» 28.10) — «решение «сократить» от 23.10 исполнено сделкой 27.10» по decision_executed_at; SBERP «сделал» 29.10 (≤ 7 дн.) — есть, MRKP 01.10 — нет;
      проданная (вариант без GLRX в снапшоте) — «продана …».
  Счётчик ярлыка = «Требует внимания» на «Сегодня» = «Сделать» + «Проверить» = числа шапки «Действия · … сделать · … проверить».
  «Сегодня»: «Файлы свежие; стресс на заменённом прогнозе …» вместо «Все файлы свежие».
  Мутанты: «держать желательно» в счётчике и «план с направлением без строки» — проверки падают.
  Телефон 390: «Акции», «Облигации», «Доли и цели» — главная колонка второй и видна без прокрутки таблицы, второстепенные
      числовые скрыты, «ещё ▾» показывает их и запоминается; на 1400 порядок прежний; подвкладка карточки «Отчёты · N» в ряду целиком.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_actions_blocks.py
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


def check(name, cond_):
    global passed, failed
    if cond_:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("viewer_actions_blocks: пропуск — нет playwright")
    sys.exit(0)

sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as hub_api  # noqa: E402

FIX = Path(tempfile.mkdtemp(prefix="vblocks-"))
TODAY = "2026-10-30"
FILES_FC = {"brent_price": "brent-price-2026-09-17.yaml", "urals_brent_discount": "urals-brent-discount-2026-09-17.yaml",
            "usdrub_rate": "usdrub-rate-2026-09-17.yaml", "cnyrub_rate": "cnyrub-rate-2026-09-17.yaml", "inflation_ru": "inflation-ru-2026-09-17.yaml",
            "cbr_rate": "cbr-rate-2026-2027-2026-07-29.yaml", "budget_deficit_ru": "budget-deficit-ru-2026-09-17.yaml",
            "xauusd_price": "xauusd-price-2026-2028-2026-09-17.yaml", "sanctions_russia": "sanctions-russia-2026-28-2026-09-17.yaml"}


MON_HZ = """schema_version: 1
type: monitor-report
generated_at: "2026-10-30T10:00:00+03:00"
producer: "forecast-monitor"
alerts:
  - severity: HIGH
    category: horizon_passed
    target: "cbr-rate-oct23-2026"
    target_file: "forecasts/cbr-rate-oct23-2026-2026-10-20.yaml"
    target_kind: forecast
    message: "Горизонт 23.10.2026 прошёл"
    suggested_action: "/save-to-library Закрой прогноз cbr-rate-oct23-2026: факт"
"""
FC_HZ = """schema_version: 1
type: forecast-events
status: active
forecast:
  date: 2026-10-20
  horizon: 2026-10-23
  domain: ru-macro
  topic: cbr-rate-oct23-2026
  central_estimate: "без изменений"
"""


def build(sold=False, reinvest=False, horizon=False, review_exec=False, hz_mon=None):
    shutil.rmtree(FIX, ignore_errors=True)
    fx = REPO / "tools/tests/fixtures"
    shutil.copytree(fx / "viewer-live", FIX)
    for part in ("superseded", "conditions-pack", "stress-roles"):
        shutil.copytree(fx / part, FIX, dirs_exist_ok=True)
    (FIX / "monitor-reports").mkdir(exist_ok=True)
    if horizon:   # R20 уточнён 03.11: «горизонт прошёл» у прогноза вне входов стресса
        (FIX / "monitor-reports/monitor-report-2026-10-30.yaml").write_text(hz_mon or MON_HZ, encoding="utf-8")
        (FIX / "forecasts").mkdir(exist_ok=True)
        (FIX / "forecasts/cbr-rate-oct23-2026-2026-10-20.yaml").write_text(FC_HZ, encoding="utf-8")
    mp = FIX / "macro-chain/macro-scenarios-2026-10-04.yaml"
    mp.write_text("forecast_files:\n" + "".join(f"  {k}: {v}\n" for k, v in FILES_FC.items()) + mp.read_text(encoding="utf-8"), encoding="utf-8")
    sd = FIX / "Portfolio/snapshots"
    cur = json.loads((sd / "portfolio-2026-10-08.json").read_text(encoding="utf-8"))
    for h in cur["holdings"]:
        if h.get("ticker") == "MDMG":
            h["qty"] = max(1, int(h["qty"]) // 2)
    if sold:
        cur["holdings"] = [h for h in cur["holdings"] if h.get("ticker") != "GLRX"]
        pt = (cur.get("ie_actual") or {}).get("per_ticker") or {}
        if "GLRX" in pt:
            pt["GLRX"]["real_share_pct"] = 0.0
    cur["as_of_date"] = "2026-10-27"
    (sd / "portfolio-2026-10-27.json").write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
    # R28 (4.2.1): «срочно» — подпись строки; в «Проверить» — только пункты verification_checklist. YDEX и LSNGP — с пунктами,
    # OZON — «срочно» без пунктов (уходит в «Ждём» при ждущем условии, иначе в «К сведению»)
    import yaml
    rp = FIX / "Portfolio/weekly-reviews/weekly-review-stock-2026-10-28.yaml"
    rv = yaml.safe_load(rp.read_text(encoding="utf-8"))
    rv["per_stock"]["YDEX"]["verification_checklist"] = ["проверить отчёт за 3 квартал"]
    rv["per_stock"]["LSNGP"]["verification_checklist"] = ["сверить дивидендную базу"]
    rv["per_stock"]["OZON"]["verification_checklist"] = []
    if review_exec:   # (11, 03.11): обзор 28.10 «сократить» по PLZL, снапшот 29.10 — количество меньше (продажа после обзора)
        rv["per_stock"]["PLZL"]["advisor_verdict"] = "TRIM"
        nx = json.loads(json.dumps(cur))
        for h in nx["holdings"]:
            if h.get("ticker") == "PLZL":
                h["qty"] = max(1, int(h["qty"]) // 2)
        nx["as_of_date"] = "2026-10-29"
        (sd / "portfolio-2026-10-29.json").write_text(json.dumps(nx, ensure_ascii=False), encoding="utf-8")
    rp.write_text(yaml.safe_dump(rv, allow_unicode=True, sort_keys=False), encoding="utf-8")
    # R30 (4.2.1): ПИК — исход «реинвестировать» в корзину ОФЗ/>10 (как после правки оркестратора); ЭСЭГ остаётся
    # прежним set_verdict BUY с датой = погашению (стрелки «→ докупать» быть не должно). reinvest=True — 20.11: ПИК
    # сработал, у ЭСЭГ цель — бумага RU000A106EP1, купленная 18.11 (реинвест исполнен сделкой)
    cp = FIX / "Portfolio/conditions.yaml"
    cd = yaml.safe_load(cp.read_text(encoding="utf-8"))
    for c in cd["conditions"]:
        if c["id"] == "pik-redemption-1911":
            c["on_trigger"] = {"action": "reinvest", "target": "ОФЗ/>10", "amount_source": "redemption",
                               "text": "Погашение ПИК К 1P5 → реинвест в ОФЗ/>10 (26247/26248), в USD не возвращать"}
        if reinvest and c["id"] == "eseg-redemption-1711":
            c["on_trigger"] = {"action": "reinvest", "target": "RU000A106EP1", "amount_source": "redemption", "text": "в юанях"}
    cp.write_text(yaml.safe_dump(cd, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if reinvest:
        nxt = json.loads(json.dumps(cur))
        for h in nxt["holdings"]:
            if h.get("isin") == "RU000A106EP1":
                h["qty"] = int(h["qty"]) + 10
        nxt["as_of_date"] = "2026-11-18"
        (sd / "portfolio-2026-11-18.json").write_text(json.dumps(nxt, ensure_ascii=False), encoding="utf-8")


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


def norm(t):
    return re.sub(r"[\s  ]+", " ", t or "").strip()


# план сайта: из ie_actual снапшота + правки под правила отнесения; журнал плана — даты статусов
PLAN_EDIT = {"SBER": {"user_plan": "BALANCE", "plan_pct": 6.0}, "GLRX": {"user_plan": "SELL", "plan_pct": 0.0},
             "YDEX": {"user_plan": "BUY", "plan_pct": 14.0}, "T": {"user_status": "ORDER"}, "MOEX": {"user_status": "DEFERRED"},
             "SBERP": {"user_status": "DONE"}, "MRKP": {"user_status": "DONE"},
             "CNRU": {"user_plan": "BALANCE", "plan_pct": 1.0, "user_status": "DONE"}}
JOURNAL = [{"ts": "2026-10-27T09:00:00Z", "who": "site", "path": "stocks.T.user_status", "was": None, "now": "ORDER"},
           {"ts": "2026-10-28T09:00:00Z", "who": "site", "path": "stocks.MOEX.user_status", "was": None, "now": "DEFERRED"},
           {"ts": "2026-10-29T09:00:00Z", "who": "site", "path": "stocks.SBERP.user_status", "was": "ORDER", "now": "DONE"},
           {"ts": "2026-10-01T09:00:00Z", "who": "site", "path": "stocks.MRKP.user_status", "was": None, "now": "DONE"},
           {"ts": "2026-10-05T09:00:00Z", "who": "site", "path": "stocks.CNRU.user_status", "was": "ORDER", "now": "DONE"}]


def open_page(p, width=1400, with_plan=True):
    browser = p.chromium.launch()
    ctx = browser.new_context(service_workers="block", viewport={"width": width, "height": 1000 if width > 500 else 844})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "502" not in m.text and "404" not in m.text else None)
    site = {"plan": None, "hash": "h1", "sets": [], "journal": [dict(x) for x in JOURNAL]}

    def api_plan(route):
        if site["plan"] is None:
            return route.fulfill(status=502, body="{}")
        return route.fulfill(status=200, content_type="application/json", body=json.dumps({"path": "Portfolio/plan.json", "hash": site["hash"], "plan": site["plan"]}))

    def api_set(route):
        b = json.loads(route.request.post_data or "{}")
        site["sets"].append(b)
        for ch in b.get("changes") or []:
            sec, tk, f = ch["path"].split(".")
            was = site["plan"].setdefault(sec, {}).setdefault(tk, {}).get(f)
            site["plan"][sec][tk][f] = ch["value"]
            site["journal"].insert(0, {"ts": "2026-10-30T09:00:00Z", "who": "site", "path": ch["path"], "was": was, "now": ch["value"]})
        site["hash"] = "h%d" % (len(site["sets"]) + 1)
        return route.fulfill(status=200, content_type="application/json", body=json.dumps({"hash": site["hash"], "plan": site["plan"], "entries": [], "timing_ms": {"save": 1, "journal": 1}}))

    pg.route("**/api/pv/plan", api_plan)
    pg.route("**/api/pv/plan/set", api_set)
    pg.route("**/api/pv/plan/journal*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"entries": site["journal"]})))
    pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, body="{}"))
    pg.goto(URL)
    pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
    pg.wait_for_function("() => state.data && state.data.portfolioLatest && state.data.weeklyReviewCurrent && state.data.decisions.length", timeout=20000)
    pg.evaluate("(d) => { state.todayOverride = d; dsInvalidate(); }", TODAY)
    if with_plan:
        pt = pg.evaluate("() => currentPort().ie_actual.per_ticker")
        stocks = {k: {"plan_pct": v.get("planned_share_pct"), "user_plan": v.get("user_plan"), "user_status": v.get("user_status"),
                      "note_ai": None, "note_ie": None, "ie_new_pct": None, "ie_old_pct": None} for k, v in pt.items()}
        for k, ch in PLAN_EDIT.items():
            stocks.setdefault(k, {}).update(ch)
        site["plan"] = {"schema_version": 1, "stocks": stocks, "classes": [], "matrix": [], "bond_buckets": [], "bonds": {}, "funds": {},
                        "manual_positions": [], "ie_model": {}, "updated_at": "2026-10-28T10:00:00Z"}
        pg.evaluate("async () => { await loadPlan(); state.planJournal = null; await planJournalLoad(true); dsInvalidate(); }")
    return browser, pg, errs, site


BLOCKS = """() => { const B = actionBlocks(); const t = (x) => x.ticker || x.it?.ticker || x.c?.key || x.key || x.a?.target || x.topic;
  const m = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v.map(t)]));
  return { n: B.n, do: m(B.do), check: m(B.check), wait: m(B.wait), info: m(B.info), done: m(B.done) }; }"""


def actions(pg):
    pg.evaluate("() => { cardStack.length = 0; renderCards(); goToTab('actions'); }")
    pg.wait_for_selector("#content #act-head", timeout=10000)
    pg.wait_for_timeout(400)


def counters(pg):
    """числа: ярлык вкладки, «Требует внимания» на «Сегодня», шапка «Действий», actionCounts()."""
    actions(pg)
    head = norm(pg.locator("#act-head .ui-h2").inner_text())
    badge = pg.evaluate("() => [...document.querySelectorAll('#tabs .ui-tab')].find(t => /Действия/.test(t.textContent))?.textContent.replace(/\\D/g, '') || '0'")
    pg.evaluate("() => goToTab('today')")
    pg.wait_for_timeout(300)
    tt = norm(pg.locator("#content").inner_text())
    m = re.search(r"Требует внимания\s+(\d+)", tt, re.I)
    num = lambda rx: int(re.search(rx, head).group(1)) if re.search(rx, head) else 0  # noqa: E731
    return {"head": head, "badge": int(badge or 0), "today": int(m.group(1)) if m else None, "today_text": tt,
            "do": num(r"(\d+) сделать"), "check": num(r"(\d+) проверить"), "wait": num(r"(\d+) ждём"), "info": num(r"(\d+) к сведению"),
            "attn": pg.evaluate("() => actionCounts().attention")}


def hold_rule(pg):
    """«держать» с проверкой «желательно» (MDMG, PLZL, MBNK, NVTK) — только в «К сведению», не в «Сделать»/«Проверить» и не в счётчике."""
    b = pg.evaluate(BLOCKS)
    holds = {"MDMG", "PLZL", "MBNK", "NVTK"}
    in_dc = {t for v in list(b["do"].values()) + list(b["check"].values()) for t in v if t in holds}
    return set(b["info"]["items"]) >= holds and not in_dc and pg.evaluate("() => actionCounts().attention") == b["n"]["do"] + b["n"]["check"]


def plan_rule(pg):
    """план с направлением и операцией «Сейчас» (SBER — срез, GLRX — «продать всё») стоит строкой в «Сделать»."""
    b = pg.evaluate(BLOCKS)
    return "SBER" in b["do"]["plans"] and pg.locator('#act-do [data-plan="SBER"]').count() == 1 \
        and pg.locator('#act-do .act-dec[data-ticker="GLRX"] .act-plan').count() == 1


def main():
    with sync_playwright() as p:
        try:
            p.chromium.launch().close()
        except Exception as e:
            print(f"viewer_actions_blocks: пропуск — {str(e).splitlines()[0][:80]}")
            return
        build()
        browser, pg, errs, site = open_page(p)
        check("план сайта применён: SBER — «привести к плану», T — «поставил заявку»",
              pg.evaluate("() => { const pt = currentPort().ie_actual.per_ticker; return pt.SBER.user_plan === 'BALANCE' && pt.T.user_status === 'ORDER'; }"))
        actions(pg)
        b = pg.evaluate(BLOCKS)
        do_t = norm(pg.locator("#act-do").inner_text())

        # Сделать
        check(f"Сделать: GLRX — вердикт «продать» и план «продать» одной строкой ({b['do']['verdicts']}, {b['do']['plans']})",
              b["do"]["verdicts"] == ["GLRX"] and "GLRX" not in b["do"]["plans"] and pg.locator('#act-do [data-ticker="GLRX"]').count() == 1)
        g = pg.evaluate("""() => { const r = document.querySelector('#act-do .act-dec[data-ticker="GLRX"]'); const kids = [...r.children].map(x => x.className);
          return { plan: kids.indexOf('act-plan'), cond: kids.findIndex(c => /ui-text/.test(c)), text: r.innerText }; }""")
        check(f"GLRX: строка плана — первой, до вердикта и основания ({g['plan']}, {g['cond']})", 0 < g["plan"] < g["cond"])
        check(f"GLRX: «продать всё [— N лотов] по плану «продать»» ({norm(g['text'])[:160]!r})",
              re.search(r"продать всё( — \d+ лот\S*)? по плану «продать»", norm(g["text"])) is not None)
        sber = norm(pg.locator('#act-do [data-plan="SBER"]').inner_text())
        check(f"Сделать: SBER — «продать N лотов по плану «привести к плану»» и ссылка «Доли и цели →» ({sber!r})",
              re.search(r"продать( \d+ лот\S*)? по плану «привести к плану»", sber) is not None and "Доли и цели →" in sber)
        check("строка плана без фразы для Claude (сделка руками)", pg.locator('#act-do [data-plan="SBER"] .act-say').count() == 0)
        check(f"Сделать: стресс на заменённом прогнозе — строка и фраза перегона ({b['do']['stress']})",
              sorted(b["do"]["stress"]) == sorted(["brent-price", "cbr-rate-2026-2027", "sanctions-russia-2026-28"])
              and "стресс посчитан на заменённом прогнозе" in do_t and "→ перегнать" in do_t
              and pg.locator("#act-do .act-stress-newer .act-say:not(.act-then) em").all_inner_texts() == ["«/macro-forecast-chain Обнови макро-прогноз»"]
              and "затем:" not in pg.locator("#act-do .act-stress-newer .act-say:not(.act-then)").inner_text()
              and "стресс сайт пересчитает сам" in pg.locator("#act-do .act-stress-newer").inner_text())
        # 4.2.4 (владелец 04.11): интегрированный вид идёт за стрессом — устарел (27.09, 33 дн.) при строке стресса: его команда второй
        # в строке стресса («затем: …» с кнопкой и подписью), своей строки нет
        th = pg.evaluate("""() => { const r = document.querySelector('#act-do .act-stress-newer'); const t = r && r.querySelector('.act-then');
          return { then: t ? t.innerText : null, cmd: t ? (t.querySelector('.ui-claude-cmd') || {}).dataset?.cmd : null,
                   own: document.querySelectorAll('#act-do > [data-stale="integratedView"]').length }; }""")
        check(f"4.2.4 вид за стрессом: «затем: «Собери интегрированный вид»» с кнопкой и подписью «интеграционный анализ от 27.09 · 33 дн. · старше 30», своей строки нет ({th})",
              th["then"] is not None and "затем:" in norm(th["then"]) and "интеграционный анализ от 27.09 · 33 дн. · старше 30" in norm(th["then"])
              and th["cmd"] == "/portfolio-integrated-view Собери интегрированный вид" and th["own"] == 0)
        check(f"Сделать: «Брент» и ставка ЦБ названы словами ({do_t[:400]!r})", "Brent" in do_t and "ставка ЦБ" in do_t)

        # «сделал» в плане старше 7 дней, а «Сейчас» всё ещё даёт операцию — строка вернулась в «Сделать» с пометкой
        cn = norm(pg.locator('#act-do [data-plan="CNRU"]').inner_text()) if pg.locator('#act-do [data-plan="CNRU"]').count() else ""
        check(f"Сделать: CNRU «сделал» 05.10 (> 7 дн.), срез по плану остался — «отмечено сделанным 05.10, но по плану ещё продать …» ({cn!r})",
              "CNRU" in b["do"]["plans"] and re.search(r"отмечено сделанным 05\.10, но по плану ещё продать", cn) is not None and "CNRU" not in b["done"]["plans"])
        check("MRKP «сделал» 01.10 без операции «Сейчас» — нигде", not any("MRKP" in v for blk in ("do", "check", "wait", "done") for v in b[blk].values()))

        # Ждём: не больше 6 строк на виду, остальное — «ещё N»; сначала с датой (ближайшая первой), потом без; условия бумаги — одной строкой
        wv = pg.evaluate("""() => { const sec = document.querySelector('#act-wait'), fold = sec.querySelector(':scope > details.act-wait-more');
          const rows = [...sec.children].filter(x => !x.classList.contains('ui-head') && x.tagName !== 'DETAILS');
          const B = actionBlocks(), pbt = buildPositionByTicker(), r = waitRowsOrdered(B, pbt, []);
          return { shown: rows.length, fold: fold ? fold.querySelector('summary').innerText : null, folded: fold ? fold.querySelectorAll(':scope > :not(summary)').length : 0,
                   total: B.n.wait, dates: r.map(x => x.date), keys: B.wait.conds.map(g => g.key),
                   multi: B.wait.conds.filter(g => g.conds.length > 1).map(g => g.key) }; }""")
        dated = [d for d in wv["dates"] if d]
        check(f"Ждём: на виду 6 строк, остальное — «ещё N» ({wv['shown']}, {wv['fold']!r}, всего {wv['total']})",
              wv["total"] > 6 and wv["shown"] == 6 and wv["fold"] and norm(wv["fold"]).startswith(f"ещё {wv['total'] - 6}") and wv["folded"] == wv["total"] - 6)
        check(f"Ждём: сначала строки с датой, ближайшая первой, потом без даты ({wv['dates']})",
              dated == sorted(dated) and wv["dates"][:len(dated)] == dated and all(d is None for d in wv["dates"][len(dated):]))
        check(f"Ждём: условия одной бумаги — одной строкой ({wv['multi']}), бумага не повторяется ({wv['keys']})",
              len(wv["keys"]) == len(set(wv["keys"])) and "RU000A106EP1" in wv["multi"])
        ep = pg.evaluate("() => { const r = document.querySelector('#act-wait [data-cond-key=\"RU000A106EP1\"]'); return r ? r.innerText : ''; }")
        check(f"Ждём RU000A106EP1: перечисление через «;» ({norm(ep)[:160]!r})", norm(ep).count(";") >= 2)

        # Проверить — только пункты «срочно» (R28): YDEX и LSNGP с пунктами; OZON «срочно» без пунктов ждёт условия — «Ждём»
        check(f"Проверить: «держать» с пунктами проверки «срочно» — YDEX, LSNGP ({b['check']['items']})",
              sorted(b["check"]["items"]) == ["LSNGP", "YDEX"])
        check(f"R28: «срочно» без пунктов — не в «Проверить»; ждёт условия — «Ждём» строкой вердикта ({b['wait']['verdicts']})",
              "OZON" not in b["check"]["items"] and "OZON" in b["wait"]["verdicts"])
        oz = norm(pg.evaluate("() => { const r = document.querySelector('#act-wait .act-dec[data-ticker=\"OZON\"]'); return r ? r.innerText : ''; }")
                  or pg.evaluate("() => { document.querySelectorAll('#act-wait details').forEach(d => d.open = true); const r = document.querySelector('#act-wait .act-dec[data-ticker=\"OZON\"]'); return r ? r.innerText : ''; }"))
        check(f"R28: флаг «срочно» остаётся подписью строки OZON ({oz[:120]!r})", "проверка: срочно" in oz and "Ждёт условия" in oz)
        nohi = pg.evaluate("""() => { const it = _actionItems().find(x => x.ticker === 'OZON'); const B0 = actionBlocks;
          window.__ai2 = _actionItems; window._actionItems = () => window.__ai2().map(x => x.ticker === 'OZON' ? { ...x, cond: null } : x);
          const B = actionBlocks(); window._actionItems = window.__ai2; return { info: B.info.items.map(x => x.ticker), check: B.check.items.map(x => x.it.ticker) }; }""")
        check(f"R28: «срочно» без пунктов и без ждущего условия — «К сведению» ({nohi})", "OZON" in nohi["info"] and "OZON" not in nohi["check"])

        # R30: условие «реинвестировать» — «Ждём» без стрелки к вердикту; set_verdict в день погашения — без стрелки
        ri = pg.evaluate("""() => { const c = dsCondRows().find(x => x.id === 'pik-redemption-1911'), e = dsCondRows().find(x => x.id === 'eseg-redemption-1711');
          return { act: condActionText(c), then: condThen(c), ethen: condThen(e), pair: conditionVerdictPair('RU000A108FX8'), ppair: conditionVerdictPair('RU000A105146'),
                   row: (document.querySelector('#act-wait [data-cond-key="RU000A105146"]') || document.querySelector('#act-wait [data-cond="pik-redemption-1911"]') || {}).innerText || '' }; }""")
        check(f"R30 Ждём: «погашение → реинвест в ОФЗ длиннее 10 лет», вердикта при срабатывании нет ({ri['act']!r}, {norm(ri['row'])[:140]!r})",
              ri["act"] == "погашение → реинвест в ОФЗ длиннее 10 лет" and ri["then"] is None and "реинвест в ОФЗ длиннее 10 лет" in norm(ri["row"])
              and "Докупать" not in ri["row"] and ri["ppair"] is None)
        check(f"R30: set_verdict «докупать» с датой = погашению — стрелки «→ докупать» нет ({ri['ethen']}, {ri['pair']})",
              ri["ethen"] is None and (ri["pair"] is None or not ri["pair"].get("triggered")))
        cw = pg.evaluate("() => [condActWord({ action: 'set_verdict', verdict: 'TRIM', target_pct: 3 }), condActWord({ action: 'set_verdict', verdict: 'SELL' })]")
        check(f"R30: слово set_verdict — само слово вердикта, не «сменить вердикт» ({cw})", cw == ["сократить до 3%", "продать"])
        t_row = norm(pg.locator('#act-check [data-plan="T"]').inner_text())
        check(f"Проверить: T — «заявка стоит с 27.10 — исполнилась?» и «сделал» ({t_row!r})",
              "заявка стоит с 27.10 — исполнилась?" in t_row and "сделал" in t_row)

        # Ждём (свёрнутое «ещё N» — раскрыть)
        pg.evaluate("() => document.querySelectorAll('#act-wait details').forEach(d => d.open = true)")
        y = norm(pg.locator('#act-wait [data-plan="YDEX"]').inner_text()) if pg.locator('#act-wait [data-plan="YDEX"]').count() else ""
        now_y = pg.evaluate("() => reasonRu(nowAutoResult().rows.find(a => a.ticker === 'YDEX').reason, 'YDEX')")
        check(f"Ждём: YDEX — «докупка по плану «докупать» стоит: …» теми же словами, что «Сейчас» ({y!r} / {now_y!r})",
              y.find("докупка по плану «докупать» стоит: ") >= 0 and norm(now_y) in y and "решение «наблюдать»" in y)
        check("Ждём: план YDEX не в «Сделать»", "YDEX" not in b["do"]["plans"])
        mo = norm(pg.locator('#act-wait [data-plan="MOEX"]').inner_text()) if pg.locator('#act-wait [data-plan="MOEX"]').count() else ""
        check(f"Ждём: MOEX «отложил» — «отложен 28.10» ({mo!r})", "отложен 28.10" in mo)
        check(f"Ждём: ждущие условия по бумагам портфеля ({len(b['wait']['conds'])})", len(b["wait"]["conds"]) >= 5 and "PLZL" in b["wait"]["conds"])
        check(f"Ждём: пункты проверки и катализаторы строк «желательно» ({b['wait']['notes']})", set(b["wait"]["notes"]) >= {"MDMG", "MBNK"})
        mb = norm(pg.locator('#act-wait [data-note="MBNK"]').inner_text())
        check(f"Ждём MBNK: катализатор с окном, не больше трёх строк ({mb[:200]!r})", "окно 2026-Q4..2027-Q4" in mb
              and pg.locator('#act-wait [data-note="MBNK"] li:not(.ui-faint)').count() <= 3)

        # К сведению
        check(f"К сведению: тикеры «держать желательно» ({b['info']['items']})", sorted(b["info"]["items"]) == ["MBNK", "MDMG", "NVTK", "PLZL"])
        info = pg.evaluate("() => { const d = document.querySelector('#act-info'); return d ? { open: d.open, btns: [...d.querySelectorAll('[data-info]')].map(x => x.dataset.info), text: d.innerText } : null; }")
        check(f"К сведению свёрнуто, строки — кнопки тикеров, прозы нет ({info and info['btns']})",
              bool(info) and not info["open"] and sorted(info["btns"]) == ["MBNK", "MDMG", "NVTK", "PLZL"] and "МСФО" not in info["text"])
        pg.evaluate("() => { document.querySelector('#act-info').open = true; }")
        ch = pg.evaluate("""() => [...document.querySelectorAll('#act-info [data-info]')].map(x => [x.classList.contains('tag') && x.classList.contains('act-info-chip'), x.title])""")
        check(f"4.2.4 «К сведению»: тикеры — чипы, в подсказке слово вердикта и дата обзора ({ch[:2]})",
              len(ch) == 4 and all(c and re.search(r"вердикт: \S+", t) and re.search(r"\d\d\.\d\d", t) for c, t in ch))
        pg.locator('#act-info [data-info="MBNK"]').click()
        pg.wait_for_selector("#card-layer .card-dec", timeout=8000)
        check("К сведению: щелчок по тикеру — карточка", "MBNK" in pg.locator("#card-layer").inner_text())
        pg.evaluate("() => { cardStack.length = 0; renderCards(); }")

        # Сделано
        actions(pg)
        b = pg.evaluate(BLOCKS)
        check(f"Сделано: MDMG — решение исполнено сделкой ({b['done']['executed']})", b["done"]["executed"] == ["MDMG"])
        pg.evaluate("() => { document.querySelector('#act-done').open = true; }")
        md = norm(pg.locator('#act-done [data-executed="MDMG"]').inner_text())
        check(f"Сделано MDMG: «решение «сократить» от 23.10 исполнено сделкой 27.10» ({md!r})", "решение «сократить» от 23.10 исполнено сделкой 27.10" in md)
        # (11): два признака — по последнему слову (обзор «держать» 28.10 после продажи: null) и по решению (27.10)
        mdc = pg.evaluate("() => { const c = lwCard('MDMG'); return [c.verdict_source.kind, c.executed_by_trade_at, (c.decision_executed_at || '').slice(0, 10)]; }")
        check(f"MDMG: executed_by_trade_at null (последнее слово — обзор), decision_executed_at 27.10 ({mdc})",
              mdc == ["review", None, "2026-10-27"])
        check(f"Сделано: план «сделал» за 7 дней — SBERP, старше — нет ({b['done']['plans']})", b["done"]["plans"] == ["SBERP"])

        # счётчики
        c = counters(pg)
        check(f"счётчик: ярлык = «Требует внимания» = attention = сделать + проверить ({c['badge']}, {c['today']}, {c['attn']}, {c['do']}+{c['check']})",
              c["badge"] == c["today"] == c["attn"] == c["do"] + c["check"] and c["attn"] > 0)
        check(f"шапка: «Действия · 30.10 · N сделать · M проверить · K ждём · L к сведению» ({c['head']!r})",
              re.fullmatch(r"Действия · 30\.10 · \d+ сделать · \d+ проверить · \d+ ждём · 4 к сведению", c["head"]) is not None)
        check("HOLD «желательно» — только в «К сведению», не в счётчике", hold_rule(pg))
        check(f"«Сегодня»: «Файлы свежие; стресс на заменённом прогнозе …» ({c['today_text'][:0]})",
              "Файлы свежие; стресс на заменённом прогнозе" in c["today_text"] or "Стресс на заменённом прогнозе" in c["today_text"])

        # «сделал» у срочной проверки — локальная отметка, строка в «Сделано», счётчик −1
        actions(pg)
        n0 = pg.evaluate("() => actionCounts().attention")
        pg.locator('#act-check [data-check^="YDEX|"] [data-check-act="done"]').click()
        pg.wait_for_timeout(400)
        check("Проверить «сделал»: строки нет, счётчик −1, отметка в localStorage",
              pg.locator('#act-check [data-check^="YDEX|"]').count() == 0 and pg.evaluate("() => actionCounts().attention") == n0 - 1
              and "YDEX|" in (pg.evaluate("() => localStorage.getItem('piv-check-done')") or ""))
        pg.evaluate("() => { document.querySelector('#act-done').open = true; }")
        check("отмеченная проверка — в «Сделано» с «вернуть»", pg.locator('#act-done [data-check^="YDEX|"] [data-check-act="undo"]').count() == 1)
        old = pg.evaluate("() => { const m = JSON.parse(localStorage.getItem('piv-check-done')); for (const k in m) m[k] = Date.now() - 15 * 864e5; localStorage.setItem('piv-check-done', JSON.stringify(m)); renderTabContent({ fade: false }); return actionCounts().attention; }")
        check(f"отметка старше 14 дней не действует — строка вернулась ({old} против {n0})", old == n0)
        pg.evaluate("() => localStorage.removeItem('piv-check-done')")

        # заявка исполнилась → статус DONE через тот же путь, что ✎ на «Долях»
        actions(pg)
        pg.locator('#act-check [data-plan="T"] [data-plan-done="T"]').click()
        pg.wait_for_function("() => !document.querySelector('#act-check [data-plan=\"T\"]')", timeout=8000)
        check(f"заявка «сделал» → POST plan/set stocks.T.user_status = DONE ({site['sets']})",
              site["sets"] and site["sets"][-1]["changes"] == [{"path": "stocks.T.user_status", "value": "DONE"}])
        check("после «сделал» T — в «Сделано» (план «сделал» за 7 дней)", "T" in pg.evaluate(BLOCKS)["done"]["plans"])

        # ссылка «Доли и цели →»
        actions(pg)
        pg.locator('#act-do [data-plan="SBER"] .act-plan-lnk').click()
        pg.wait_for_selector(".rb-table tbody tr", timeout=10000)
        check("«Доли и цели →» открывает «Доли и цели» на «Сделках» (колонка «Сейчас»)",
              pg.evaluate("() => state.currentTab === 'ie-model' && !!document.querySelector('.rb-table th[data-col=now]')"))

        # R31: «привести к плану» — направление по знаку отклонения факта от плана (вход fact_pct/plan_pct из per_ticker)
        r31 = pg.evaluate("""() => { const pt = currentPort().ie_actual.per_ticker.SBER, pc = dsPlanCtx(currentPort()).SBER;
          const base = { today: '2026-10-30', stock_keys: ['X'], snapshot_keys: ['X'],
            decisions: [{ id: 'd', key: 'X', verdict: 'TRIM', recorded_at: '2026-10-20T10:00:00+03:00', note: 'н', confidence: 0.7 }] };
          const pv = (plan) => LW.card({ ...base, plan: { X: plan } }, 'X').plan_vs_decision;
          const plq = (plan) => { const n = lwPlaquesNode(LW.card({ ...base, plan: { X: plan } }, 'X')); return n ? n.textContent : ''; };
          return { ctx: [pc.user_plan, pc.fact_pct, pc.plan_pct], real: [pt.real_share_pct, pt.planned_share_pct],
                   over: pv({ user_plan: 'BALANCE', fact_pct: 6.34, plan_pct: 5 }), overTxt: plq({ user_plan: 'BALANCE', fact_pct: 6.34, plan_pct: 5 }),
                   under: (pv({ user_plan: 'BALANCE', fact_pct: 3, plan_pct: 5 }) || {}).plan_direction,
                   buy: pv({ user_plan: 'BUY', fact_pct: 6.34, plan_pct: 5 }), buyTxt: plq({ user_plan: 'BUY', fact_pct: 6.34, plan_pct: 5 }) }; }""")
        check(f"R31: план сайта передаёт в модуль (б) доли факт/план из per_ticker ({r31['ctx']}, {r31['real']})",
              r31["ctx"] == ["BALANCE", r31["real"][0], 6.0] and isinstance(r31["ctx"][1], (int, float)))
        check(f"R31: «привести к плану» при перевесе + «сократить» — плашки «план против» нет ({r31['over']}, {r31['overTxt']!r})",
              r31["over"] is None and "план" not in r31["overTxt"])
        check(f"R31: «привести к плану» при недоборе — направление «вверх» ({r31['under']})", r31["under"] == "up")
        check(f"R31: «докупать» против «сократить» — плашка есть ({r31['buyTxt']!r})",
              (r31["buy"] or {}).get("plan_direction") == "up" and "план" in r31["buyTxt"])

        # проза строк — первая фраза + «подробнее ▾» в той же строке; id условия в прозе — текстом условия
        actions(pg)
        pr = pg.evaluate("""() => { const n = _proseNode('Короткая фраза. Вторая фраза длиннее, чтобы первая часть набрала сорок знаков. Третья фраза — хвост.', 'ui-text');
          const head = n.firstChild.textContent, more = n.querySelector('.act-more-t'), btn = n.querySelector('.act-more');
          const before = more.hidden; btn.click(); const after = more.hidden;
          const one = _proseNode('Одна фраза без продолжения.', 'ui-text');
          return { head, before, after, btn: btn.textContent, one: one.querySelector('.act-more') === null,
                   live: document.querySelectorAll('#content .act-prose .act-more').length }; }""")
        check(f"проза: первая фраза короче 40 знаков — видны две, остальное под «подробнее» ({pr['head']!r})",
              pr["head"] == "Короткая фраза. Вторая фраза длиннее, чтобы первая часть набрала сорок знаков." and pr["before"] and not pr["after"]
              and pr["btn"] == "свернуть ▴" and pr["one"])
        check(f"проза: на «Действиях» строки с «подробнее ▾» есть ({pr['live']})", pr["live"] > 0)
        nc = pg.evaluate("""() => { const c = dsCondRows().find(x => x.id === 'pik-redemption-1911');
          return { t: _noCondIds('Держать по условию pik-redemption-1911 до погашения.'), u: _noCondIds('по условию zzz-unknown-1 держим'),
                   w: condShortText(c), d: _noCondIds('Условие pik-redemption-1911 (условие) ждёт') }; }""")
        check(f"id условия в прозе — коротким текстом условия, неизвестный — как есть, без «условие условие» ({nc})",
              f"по условию «{nc['w']}»" in nc["t"] and "pik-redemption-1911" not in nc["t"] and nc["u"] == "по условию zzz-unknown-1 держим"
              and "условие условие" not in nc["d"].lower() and "Условия условие" not in nc["d"])

        # мутанты
        actions(pg)
        check("до мутанта: правило HOLD и правило плана выполняются", hold_rule(pg) and plan_rule(pg))
        pg.evaluate("""() => { window.__ai = _actionItems; window._actionItems = () => window.__ai().map(it => it.priority === 'MEDIUM' ? { ...it, priority: 'HIGH' } : it); }""")
        actions(pg)
        check("мутант «HOLD желательно в счётчике» ловится", not hold_rule(pg))
        pg.evaluate("() => { window._actionItems = window.__ai; window.__pr = _planActRows; window._planActRows = () => ({ ...window.__pr(), act: [] }); }")
        actions(pg)
        check("мутант «план с направлением без строки» ловится", not plan_rule(pg))
        pg.evaluate("() => { window._planActRows = window.__pr; }")
        actions(pg)
        check("после отката мутантов правила снова выполняются", hold_rule(pg) and plan_rule(pg))
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # R30: 20.11 — ПИК сработал: «Сделать» — «реинвестировать деньги от погашения … → ОФЗ длиннее 10 лет» и фраза
        # для Claude (брокерский счёт — режим 3); ЭСЭГ с целью-бумагой, купленной 18.11, — «Сделано» «исполнено сделкой»
        build(reinvest=True)
        browser, pg, errs, site = open_page(p)
        pg.evaluate("(d) => { state.todayOverride = d; dsInvalidate(); }", "2026-11-20")
        actions(pg)
        b = pg.evaluate(BLOCKS)
        pk = norm(pg.locator('#act-do [data-cond="pik-redemption-1911"]').inner_text()) if pg.locator('#act-do [data-cond="pik-redemption-1911"]').count() else ""
        check(f"R30 Сделать: ПИК — «реинвестировать деньги от погашения … → ОФЗ длиннее 10 лет» ({b['do']['conds']}, {pk[:200]!r})",
              "RU000A105146" in b["do"]["conds"] and re.search(r"реинвестировать деньги от погашения .+ → ОФЗ длиннее 10 лет", pk) is not None)
        say = pg.evaluate("() => { const e = document.querySelector('#act-do [data-cond=\"pik-redemption-1911\"] .act-say em'); return e ? e.innerText : ''; }")
        check(f"R30: фраза для Claude — режим 3 «ребалансировка» на брокерском счёте ({say!r})", say.startswith("«/ru-portfolio-advisor Реинвестировать") and say.endswith("ребалансировка»"))
        check(f"R30: реинвест в бумагу, купленную после срабатывания, — «Сделано» ({b['done']['reinvest']})",
              b["done"]["reinvest"] == ["RU000A108FX8"] and "RU000A108FX8" not in b["do"]["conds"])
        pg.evaluate("() => { document.querySelector('#act-done').open = true; }")
        ed = norm(pg.locator('#act-done [data-reinvest-done="eseg-redemption-1711"]').inner_text())
        check(f"R30 Сделано: «… — исполнено сделкой 18.11» ({ed!r})", "исполнено сделкой 18.11" in ed)
        check(f"ошибок страницы нет (реинвест) ({errs[:2]})", not errs)
        browser.close()

        # 4.2.2: (8) «горизонт прошёл» у прогноза вне стресса — «Проверить» с фразой «Закрой прогноз … с исходом: …»;
        # (9) счётчики «Сделать»/«Проверить» = числу строк блоков (стресс «есть новее» — одна строка на три прогноза);
        # (10) план и плашка из одного источника: смена плана через ✎ меняет строку плана и плашку вместе
        build(horizon=True)
        browser, pg, errs, site = open_page(p)
        pg.wait_for_function("() => (state.data.monitorReport?.parsed?.alerts || []).length", timeout=10000)
        actions(pg)
        b = pg.evaluate(BLOCKS)
        hz = pg.evaluate("() => { const r = document.querySelector('#act-check [data-horizon]'); return r ? { k: r.dataset.horizon, t: r.innerText, say: r.querySelector('.act-say em')?.innerText } : null; }")
        check(f"R20 (03.11): «горизонт прошёл» у прогноза вне стресса — «Проверить» ({b['check'].get('horizon')}, {hz})",
              hz is not None and hz["k"] == "cbr-rate-oct23-2026-2026-10-20" and "горизонт прошёл 23.10 → закрой с исходом" in norm(hz["t"])
              and hz["say"] == "«/save-to-library Закрой прогноз cbr-rate-oct23-2026: факт»"
              and not b["info"]["mon"])
        # VW-CLOSE 4.2.3: кнопка «Закрыть» (контур, значок) копирует suggested_action как есть
        btn = pg.evaluate("() => { const b = document.querySelector('#act-check [data-horizon] .ui-claude-cmd'); return b ? { t: b.innerText.trim(), cmd: b.dataset.cmd, svg: !!b.querySelector('svg') } : null; }")
        check(f"VW-CLOSE: «Закрыть» с data-cmd = suggested_action ({btn})",
              btn is not None and btn["t"] == "Закрыть" and btn["svg"] and btn["cmd"] == "/save-to-library Закрой прогноз cbr-rate-oct23-2026: факт")
        check("VW-CLOSE: ни одна кнопка записи не несёт .ui-claude-cmd",
              pg.evaluate("() => document.querySelectorAll('[data-cond] button.ui-btn.ui-claude-cmd, [data-cond] .cond-own .ui-claude-cmd').length") == 0)
        # 4.2.4: вкладка «Прогнозы» — у прогноза с прошедшим горизонтом строка «горизонт прошёл 23.10» и та же кнопка «Закрыть»
        pg.evaluate("() => { state.forecastsView = 'l2'; state.forecastShowAll = true; goToTab('forecasts'); }")
        pg.wait_for_timeout(400)
        fz = pg.evaluate("""() => [...document.querySelectorAll('#content .fc-hp')].map(r => { const b = r.querySelector('.ui-claude-cmd');
          return { k: r.dataset.horizon, t: r.innerText, cmd: b ? b.dataset.cmd : null, lbl: b ? b.innerText.trim() : null }; })""")
        check(f"4.2.4 «Прогнозы»: «горизонт прошёл 23.10» и «Закрыть» с data-cmd = suggested_action, одна строка ({fz})",
              len(fz) == 1 and fz[0]["k"] == "cbr-rate-oct23-2026-2026-10-20" and "горизонт прошёл 23.10" in norm(fz[0]["t"])
              and fz[0]["lbl"] == "Закрыть" and fz[0]["cmd"] == "/save-to-library Закрой прогноз cbr-rate-oct23-2026: факт")
        pg.evaluate("() => { goToTab('today'); }")
        pg.wait_for_timeout(400)
        check("4.2.4 «Сегодня»: кнопки «Закрыть» прогноза нет (правило владельца)",
              pg.evaluate("() => [...document.querySelectorAll('#content .ui-claude-cmd')].filter(b => /Закрой прогноз/.test(b.dataset.cmd || '')).length") == 0)
        # без suggested_action: исход — message алерта; без обоих — «…»
        base = MON_HZ.replace('    suggested_action: "/save-to-library Закрой прогноз cbr-rate-oct23-2026: факт"\n', '')
        for tag, mon, want in (("message", base, "с исходом: Горизонт 23.10.2026 прошёл"), ("пусто", base.replace('    message: "Горизонт 23.10.2026 прошёл"\n', ''), "с исходом: …")):
            browser.close()
            build(horizon=True, hz_mon=mon)
            browser, pg, errs, site = open_page(p)
            pg.wait_for_function("() => (state.data.monitorReport?.parsed?.alerts || []).length", timeout=10000)
            actions(pg)
            cmd = pg.evaluate("() => document.querySelector('#act-check [data-horizon] .ui-claude-cmd')?.dataset.cmd") or ""
            check(f"VW-CLOSE ({tag}): без suggested_action фраза собирается ({cmd!r})",
                  cmd == "/save-to-library Закрой прогноз cbr-rate-oct23-2026-2026-10-20 " + want)
        browser.close()
        build(horizon=True)
        browser, pg, errs, site = open_page(p)
        pg.wait_for_function("() => (state.data.monitorReport?.parsed?.alerts || []).length", timeout=10000)
        actions(pg)
        rows = pg.evaluate("() => ({ do: document.querySelectorAll('#act-do > :not(.ui-head)').length, check: document.querySelectorAll('#act-check > :not(.ui-head)').length, n: actionBlocks().n, att: actionCounts().attention, stress: actionBlocks().do.stress.length })")
        check(f"(9) счётчик «Сделать» = строкам блока, «Проверить» — тоже; стресс «есть новее» по {rows['stress']} прогнозам — одна строка ({rows})",
              rows["stress"] > 1 and rows["n"]["do"] == rows["do"] and rows["n"]["check"] == rows["check"] and rows["att"] == rows["do"] + rows["check"])
        mut = pg.evaluate("""() => { const f = window._doRowSpecs; window._doRowSpecs = (B) => [...f(B), ...B.do.stress.slice(1).map(x => ['stress', [x]])];
          const n = actionBlocks().n.do; window._doRowSpecs = f; return n; }""")
        check(f"(9) мутант «стресс по строке на прогноз» в счёте расходится со строками ({mut} против {rows['do']})", mut != rows["do"])
        # (10): SBER — план «привести к плану»; меняем через ✎ (окно плана) на «докупать» — строка плана и вход плашки вместе
        st0 = pg.evaluate("() => [lwCtx().plan.SBER.user_plan, currentPort().ie_actual.per_ticker.SBER.user_plan]")
        pg.evaluate("() => { cardStack.length = 0; renderCards(); showPlanEditModal('SBER'); }")
        pg.wait_for_selector("#plan-layer .ui-modal", timeout=5000)
        sel = pg.locator("#plan-layer .plan-form .ui-select").first
        sel.locator(".ui-select-btn").click()
        sel.locator(".ui-opt", has_text="докупать").first.click()
        pg.click("#plan-layer [data-act=plan-save]")
        pg.wait_for_function("() => currentPort().ie_actual.per_ticker.SBER.user_plan === 'BUY'", timeout=8000)
        st1 = pg.evaluate("() => [lwCtx().plan.SBER.user_plan, currentPort().ie_actual.per_ticker.SBER.user_plan, _planActRows().act.concat(_planActRows().wait).filter(x => x.ticker === 'SBER').map(x => x.plan)]")
        check(f"(10) ✎: план и вход плашки (модуль (б)) — из одного источника до и после смены ({st0} → {st1})",
              st0[0] == st0[1] == "BALANCE" and st1[0] == st1[1] == "BUY" and all(x == "BUY" for x in st1[2]))
        # самопроверка: та же правка плана на месте без смены версии плана память не обновляет — ключом служит hash плана
        mut10 = pg.evaluate("""() => { lwCtx(); const pt = currentPort().ie_actual.per_ticker.SBER; pt.user_plan = 'KEEP';
          const stale = lwCtx().plan.SBER.user_plan; pt.user_plan = 'BUY'; dsInvalidate(); return stale; }""")
        check(f"(10) самопроверка: без смены версии плана память держит прежний план ({mut10})", mut10 == "BUY")
        check(f"ошибок страницы нет (4.2.2) ({errs[:2]})", not errs)
        browser.close()

        # (11): «исполнено сделкой» по последнему слову-обзору: PLZL «сократить» 28.10, продажа в снапшоте 29.10 — «Сделано»
        build(review_exec=True)
        browser, pg, errs, site = open_page(p)
        actions(pg)
        b = pg.evaluate(BLOCKS)
        cardx = pg.evaluate("() => { const c = lwCard('PLZL'); return [c.verdict_source.kind, c.verdict, c.executed_by_trade_at, c.executed_source_kind]; }")
        check(f"(11) модуль (б): последнее слово — обзор «сократить», продажа после него — исполнено, вид review ({cardx})",
              cardx[0] == "review" and cardx[1] == "TRIM" and str(cardx[2] or "").startswith("2026-10-29") and cardx[3] == "review")
        pg.evaluate("() => { document.querySelector('#act-done').open = true; }")
        ex = norm(pg.locator('#act-done [data-executed="PLZL"]').inner_text()) if pg.locator('#act-done [data-executed="PLZL"]').count() else ""
        check(f"(11) «Сделано»: «сократить — исполнено сделкой 29.10 (обзор 28.10)», не в «Сделать» ({b['done']['executed']}, {ex!r})",
              "PLZL" in b["done"]["executed"] and "сократить — исполнено сделкой 29.10 (обзор 28.10)" in ex
              and "PLZL" not in b["do"]["verdicts"] and "MDMG" in b["done"]["executed"])
        pg.evaluate("() => { const pbt = buildPositionByTicker(); openCard(pbt.PLZL, [pbt.PLZL]); }")
        pg.wait_for_selector("#card-layer .card-dec .h3r", timeout=8000)
        h3 = norm(pg.locator("#card-layer .card-dec .h3r").first.inner_text())
        check(f"(11) карточка: та же подпись в заголовке блока «Решение» ({h3!r})", h3.startswith("сократить — исполнено сделкой 29.10 (обзор 28.10)"))
        # 4.2.4: «почему» уверенность такая — не в шапке блока, а в подсказке и под «подробнее»
        pg.evaluate("() => { cardStack.length = 0; renderCards(); const pbt = buildPositionByTicker(); (pbt.PLZL.raw = pbt.PLZL.raw || {}).confidence_basis = 'длинное-почему-теста'; openCard(pbt.PLZL, [pbt.PLZL]); }")
        pg.wait_for_selector("#card-layer .card-dec .h3r", timeout=8000)
        hd = pg.evaluate("""() => { const h = document.querySelector('#card-layer .card-dec .h3r'), f = document.querySelector('#card-layer .card-dec .card-why-fold');
          return { text: h.innerText, title: h.title, fold: f ? f.innerText + f.textContent : '' }; }""")
        check(f"4.2.4 «Решение»: шапка без «почему» ({hd['text']!r}), оно — в title и под «подробнее»",
              "длинное-почему-теста" not in hd["text"] and re.search(r"уверенность \S+$", hd["text"]) is not None
              and "длинное-почему-теста" in hd["title"] and "длинное-почему-теста" in hd["fold"])
        check(f"ошибок страницы нет (11) ({errs[:2]})", not errs)
        browser.close()

        # проданная: GLRX нет в последнем снапшоте — в «Сделано», не в «Сделать»
        build(sold=True)
        browser, pg, errs, site = open_page(p)
        actions(pg)
        b = pg.evaluate(BLOCKS)
        check(f"продана: GLRX в «Сделано», не в «Сделать» ({b['do']['verdicts']}, {b['done']['sold']})",
              "GLRX" not in b["do"]["verdicts"] and b["done"]["sold"] == ["GLRX"])
        pg.evaluate("() => { document.querySelector('#act-done').open = true; }")
        check("продана: «продана … — вердикт обзора 28.10 исполнен»", "вердикт обзора 28.10 исполнен" in norm(pg.locator('#act-done [data-sold="GLRX"]').inner_text()))
        check(f"ошибок страницы нет (продана) ({errs[:2]})", not errs)
        browser.close()

        # телефон 390: главная колонка второй, видна без прокрутки таблицы, «ещё ▾»
        build()
        browser, pg, errs, site = open_page(p, width=390)
        for tab, main in (("positions", "Вердикт"), ("bonds", "Вердикт"), ("ie-model", "Сейчас")):
            if tab == "ie-model":
                pg.evaluate("() => { state.ieView = 'work'; }")
            pg.evaluate("(t) => { cardStack.length = 0; renderCards(); goToTab(t); }", tab)
            pg.wait_for_timeout(500)
            r = pg.evaluate("""() => { const t = document.querySelector('#content .ui-table-wrap thead [data-cols-more]')?.closest('table') || document.querySelector('#content .ui-table-wrap table'); const ths = [...t.querySelectorAll('thead th')];
              const vis = ths.filter(x => x.getBoundingClientRect().width > 0);
              const more = [...t.querySelectorAll('thead th.mob-more')];
              return { names: vis.map(x => x.childNodes[0]?.textContent.trim() || x.innerText.trim()), right: vis[1]?.getBoundingClientRect().right,
                       hidden: more.map(x => x.getBoundingClientRect().width === 0), nmore: more.length, btn: !!t.querySelector('thead th [data-cols-more]') }; }""")
            check(f"390 {tab}: «{main}» — вторая колонка, правый край ≤ 390 ({r['names'][:3]}, {r['right']})",
                  len(r["names"]) > 1 and r["names"][1].startswith(main) and r["right"] is not None and r["right"] <= 390)
            check(f"390 {tab}: второстепенные числовые скрыты ({r['nmore']}), кнопка «ещё ▾» в шапке", r["nmore"] >= 2 and all(r["hidden"]) and r["btn"])
            pg.locator("#content [data-cols-more]").first.click()
            pg.wait_for_timeout(200)
            shown = pg.evaluate("() => [...document.querySelector('#content .ui-table-wrap thead [data-cols-more]').closest('table').querySelectorAll('thead th.mob-more')].every(x => x.getBoundingClientRect().width > 0)")
            check(f"390 {tab}: «ещё ▾» показывает их", shown)
            pg.evaluate("() => renderTabContent({ fade: false })")
            pg.wait_for_timeout(300)
            check(f"390 {tab}: выбор запомнен на устройстве",
                  pg.evaluate("() => { const b = document.querySelector('#content .ui-table-wrap thead [data-cols-more]'); return !!b.closest('.ui-table-wrap.cols-more') && b.textContent.startsWith('скрыть'); }"))
            pg.locator("#content [data-cols-more]").first.click()
        check("390: ширина страницы не больше экрана", pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1"))
        actions(pg)
        ph = pg.evaluate("""() => { const ps = [...document.querySelectorAll('#content .act-prose')];
          return { n: ps.length, wrap: ps.every(x => getComputedStyle(x).whiteSpace === 'normal'),
                   btn: ps.filter(x => x.querySelector('.act-more')).every(x => x.querySelector('.act-more').getBoundingClientRect().right <= innerWidth + 1),
                   w: document.documentElement.scrollWidth <= innerWidth + 1 }; }""")
        check(f"390 «Действия»: проза — первая фраза с переносом и «подробнее ▾» в экране, как на компьютере ({ph})",
              ph["n"] > 0 and ph["wrap"] and ph["btn"] and ph["w"])
        WAIT = """() => { const rows = [...document.querySelectorAll('#act-wait .act-wait')];
          return { n: rows.length, w: document.documentElement.scrollWidth <= innerWidth + 1,
            rows: rows.map(r => { const t = r.querySelector('.act-wait-trg'), a = r.querySelector('.act-wait-a'); if (!t || !a) return null;
              const tb = t.getBoundingClientRect(), ab = a.getBoundingClientRect(), cs = getComputedStyle(a);
              return { vis: ab.width > 0 && ab.right <= innerWidth + 1, under: ab.top >= tb.bottom - 2, side: ab.left >= tb.right - 2 || ab.top >= tb.bottom - 2,
                       sep: parseFloat(cs.paddingLeft) > 0 && parseFloat(cs.borderLeftWidth) > 0, h: r.getBoundingClientRect().height }; }).filter(Boolean) }; }"""
        pg.evaluate("() => { document.querySelectorAll('#act-wait details').forEach(d => d.open = true); }")
        wt = pg.evaluate(WAIT)
        check(f"4.2.4 390 «Ждём»: текст условия виден без горизонтальной прокрутки и стоит под срабатыванием ({wt['rows'][:3]})",
              wt["n"] > 0 and wt["w"] and wt["rows"] and all(r["vis"] and r["under"] and not r["sep"] for r in wt["rows"]))
        pg.evaluate("() => { cardStack.length = 0; renderCards(); const pbt = buildPositionByTicker(); openCard(pbt.YDEX, [pbt.YDEX]); }")
        pg.wait_for_selector("#card-layer .card-subs", timeout=8000)
        sub = pg.evaluate("""() => { const bs = [...document.querySelectorAll('#card-layer .card-subs .ui-seg-btn')]; const r = bs.find(b => b.dataset.v === 'reports');
          return { all: bs.every(b => b.getBoundingClientRect().right <= innerWidth + 1), text: r ? r.innerText.trim() : '' }; }""")
        check(f"390 карточка: ряд подвкладок в экране (перенос), «Отчёты · N» ({sub})", sub["all"] and re.fullmatch(r"Отчёты · \d+", sub["text"]) is not None)
        check(f"ошибок страницы нет (390) ({errs[:2]})", not errs)
        browser.close()

        browser, pg, errs, site = open_page(p, width=1400, with_plan=False)
        actions(pg)
        pg.evaluate("() => { document.querySelectorAll('#act-wait details').forEach(d => d.open = true); }")
        wt = pg.evaluate(WAIT)
        check(f"4.2.4 1400 «Ждём»: текст условия виден без горизонтальной прокрутки, отделён от срабатывания разделителем ({wt['n']} строк)",
              wt["n"] > 0 and wt["w"] and all(r["vis"] and r["side"] and r["sep"] for r in wt["rows"]))
        pg.evaluate("() => goToTab('positions')")
        pg.wait_for_timeout(400)
        n14 = pg.evaluate("() => [...document.querySelectorAll('#content thead th')].map(x => x.innerText.trim())")
        check(f"1400: порядок колонок «Акций» прежний, «ещё ▾» не видна ({n14[:3]})",
              len(n14) > 2 and not n14[1].startswith("Вердикт") and pg.evaluate("() => { const b = document.querySelector('#content [data-cols-more]'); return !b || b.getBoundingClientRect().width === 0; }"))
        browser.close()

        # 4.2.4 (владелец 04.11): одна команда — одна строка блока. Стресс 04.10 и устарел по возрасту (04.11: 31 дн., старше 30), и посчитан
        # на заменённых прогнозах — одна строка с обоими атрибутами и одной кнопкой; счётчик шапки считает её один раз
        build()
        browser, pg, errs, site = open_page(p, width=1400, with_plan=False)
        pg.evaluate("() => { state.todayOverride = '2026-11-04'; dsInvalidate(); }")
        actions(pg)
        mg = pg.evaluate("""() => { const say = ['/macro-forecast-chain Обнови макро-прогноз', '/portfolio-scenario-stress Прогони стресс на 6-12-24'];
          const cmds = [...document.querySelectorAll('#act-do .ui-claude-cmd')].filter(b => say.includes(b.dataset.cmd));
          const r = document.querySelector('#act-do [data-stale="stress"]');
          return { n: cmds.length, both: !!r && r.hasAttribute('data-stress-newer'), t: r ? r.innerText : '', rows: document.querySelectorAll('#act-do > :not(.ui-head)').length,
                   cnt: actionBlocks().n.do, stale: actionBlocks().do.stale.map(x => x.key), stress: actionBlocks().do.stress.length,
                   head: document.querySelector('#act-head').innerText }; }""")
        check(f"4.2.4 слияние: стресс устарел и на заменённых прогнозах — исходные условия есть ({mg['stale']}, {mg['stress']})", "stress" in mg["stale"] and mg["stress"] > 0)
        check(f"4.2.4 слияние: ровно две кнопки цепочки «макро-прогноз → стресс» в «Сделать», строка несёт data-stale и data-stress-newer ({mg['n']}, {mg['both']})",
              mg["n"] == 2 and mg["both"])
        check(f"4.2.4 слияние: заголовок «стресс от 04.10 устарел (31 дн., старше 30) и посчитан на заменённых прогнозах → перегнать», список «Brent: есть новее от …» ({norm(mg['t'])[:220]!r})",
              "стресс от 04.10 устарел (31 дн., старше 30) и посчитан на заменённых прогнозах → перегнать" in norm(mg["t"]) and re.search(r"Brent: есть новее от \d\d\.\d\d", norm(mg["t"])) is not None)
        check(f"4.2.4 слияние: счётчик «Сделать» = строкам блока = шапке ({mg['cnt']}, {mg['rows']}, {norm(mg['head'])[:80]!r})",
              mg["cnt"] == mg["rows"] and f"{mg['cnt']} сделать" in norm(mg["head"]))
        check(f"ошибок страницы нет (слияние) ({errs[:2]})", not errs)
        browser.close()

        # 4.2.4: устарел только интегрированный вид (стресс 04.10 свежий на 30.10, прогнозы стресса не заменены) — своей строкой
        build()
        for fp in (FIX / "forecasts").glob("*.yaml"):
            fp.write_text(re.sub(r"(?m)^superseded_by:.*\n", "", fp.read_text(encoding="utf-8")), encoding="utf-8")
        browser, pg, errs, site = open_page(p, width=1400, with_plan=False)
        actions(pg)
        iv = pg.evaluate("""() => { const r = document.querySelector('#act-do [data-stale="integratedView"]');
          return { row: r ? r.innerText : null, cmds: r ? [...r.querySelectorAll('.ui-claude-cmd')].map(b => b.dataset.cmd) : [], then: document.querySelectorAll('#act-do .act-then').length,
                   stress: actionBlocks().do.stress.length, rows: document.querySelectorAll('#act-do > :not(.ui-head)').length, cnt: actionBlocks().n.do }; }""")
        check(f"4.2.4 вид один: стресс свежий и не на заменённых — строка «отчёт устарел · интеграционный анализ» со своей кнопкой ({iv})",
              iv["stress"] == 0 and iv["row"] is not None and "интеграционный анализ" in norm(iv["row"]) and iv["cmds"] == ["/portfolio-integrated-view Собери интегрированный вид"] and iv["then"] == 0)
        check(f"4.2.4 вид один: счётчик «Сделать» = строкам ({iv['cnt']}, {iv['rows']})", iv["cnt"] == iv["rows"])
        check(f"ошибок страницы нет (вид один) ({errs[:2]})", not errs)
        browser.close()


        # 4.4.5 (владелец 06.11): до ближайшего срока стресса меньше 3 месяцев — напоминание «пересобрать»; стресс и сайт не трогаются
        build()
        browser, pg, errs, site = open_page(p, width=1400, with_plan=False)
        fn = "(a) => stressTermsDue(a[0], a[1])"
        he = {"h6": "2027-03-31", "h12": "2027-09-30"}
        r1 = pg.evaluate(fn, [he, "2026-12-31"]); r2 = pg.evaluate(fn, [he, "2027-01-01"])
        r3 = pg.evaluate(fn, [{"h6": "2027-05-31"}, "2027-02-28"]); r4 = pg.evaluate(fn, [{"h6": "2027-05-31"}, "2027-03-01"])
        r5 = pg.evaluate(fn, [{"h6": "2027-05-30", "h12": "2027-11-30"}, "2027-02-28"]); r6 = pg.evaluate(fn, [he, "2027-04-02"])
        check(f"4.4.5 stressTermsDue: порог 2026-12-31 — в день порога null, на следующий есть, from=2027-01-01 ({r1}, {r2})",
              r1 is None and r2 and r2["nearest"] == "h6" and r2["end"] == "2027-03-31" and r2["from"] == "2027-01-01" and r2["daysLeft"] == 89)
        check(f"4.4.5 stressTermsDue: конец месяца 2027-05-31 → порог 2027-02-28 ({r3}, {r4})", r3 is None and r4 and r4["from"] == "2027-03-01")
        check(f"4.4.5 stressTermsDue: 2027-05-30 → порог 2027-02-28 (день 30 обрезан) — 28.02 null; срок прошёл — daysLeft < 0 ({r5}, {r6})",
              r5 is None and r6["daysLeft"] < 0
              and pg.evaluate(fn, [None, "2027-01-01"]) is None and pg.evaluate(fn, [{}, "2027-01-01"]) is None)
        # (а) 30.10 и 06.11 — раньше порога: строки и примечания нет
        actions(pg)
        a0 = pg.evaluate("() => ({ row: document.querySelectorAll('[data-stress-terms]').length, ev: actionBlocks().do.terms.length })")
        check(f"4.4.5 до порога: строки нет ({a0})", a0["row"] == 0 and not a0["ev"])
        pg.evaluate("() => { state.todayOverride = '2026-11-06'; dsInvalidate(); goToTab('scenarios'); }")
        pg.wait_for_timeout(500)
        check("4.4.5 до порога: примечания на «Стрессе» нет", pg.locator("#stress-terms-due").count() == 0)
        # (г) слияние: стресс устарел по возрасту и на заменённых прогнозах + сроки подошли → одна строка, одна пара кнопок
        pg.evaluate("() => { state.todayOverride = '2027-01-02'; dsInvalidate(); }")
        actions(pg)
        mg = pg.evaluate("""() => { const say = ['/macro-forecast-chain Обнови макро-прогноз', '/portfolio-scenario-stress Прогони стресс на 6-12-24'];
          const cmds = [...document.querySelectorAll('#act-do .ui-claude-cmd')].filter(b => say.includes(b.dataset.cmd));
          const r = document.querySelector('#act-do [data-stress-terms]'), m = document.querySelector('#act-do [data-stale="stress"]');
          return { n: cmds.length, own: r ? r.querySelectorAll('.ui-claude-cmd').length : -1, merged: !!m && m.hasAttribute('data-stress-newer') && !m.hasAttribute('data-stress-terms'),
                   all: [...document.querySelectorAll('#act-do [data-stress-terms]')].length, stale: r && r.hasAttribute('data-stale'), t: r ? r.innerText : '',
                   rows: document.querySelectorAll('#act-do > :not(.ui-head)').length, cnt: actionBlocks().n.do, head: document.querySelector('#act-head').innerText,
                   high: r && r.classList.contains('sev-high') }; }""")
        check(f"4.4.5 сроки подошли: одна строка data-stress-terms БЕЗ команды («сдвиньте сроки»), стресс устарел и на заменённых прогнозах — своя слитая строка с цепочкой из двух кнопок ({mg['n']}, {mg['own']}, {mg['all']}, {norm(mg['t'])[:200]!r})",
              mg["n"] == 2 and mg["own"] == 0 and mg["merged"] and mg["all"] == 1 and not mg["stale"]
              and "до ближайшего срока стресса (до 31.03.2027) меньше 3 месяцев → сдвиньте сроки" in norm(mg["t"])
              and "«Стресс» → «Настройки стресса»" in norm(mg["t"]))
        check(f"4.4.5 слияние: счётчик «Сделать» = строкам = шапке ({mg['cnt']}, {mg['rows']})", mg["cnt"] == mg["rows"] and f"{mg['cnt']} сделать" in norm(mg["head"]))
        pg.evaluate("() => goToTab('scenarios')")
        pg.wait_for_timeout(500)
        nt = pg.evaluate("() => { const e = document.querySelector('#stress-terms-due'); return e ? { t: e.innerText, cmds: e.querySelectorAll('.ui-claude-cmd').length } : null; }")
        check(f"4.4.5 «Стресс»: примечание без команд, со ссылкой «Настройки стресса» ({nt})",
              nt and nt["cmds"] == 0 and "до ближайшего срока (до 31.03.2027) меньше 3 месяцев — сдвиньте сроки: «Стресс» → «Настройки стресса»" in norm(nt["t"]))
        pg.evaluate("() => document.querySelector('#stress-terms-due a').click()")
        pg.wait_for_selector("#stress-settings", timeout=5000)
        pg.evaluate("() => closeModal()")
        pg.wait_for_selector("#modal-overlay", state="hidden", timeout=5000)
        # «Сегодня»: короткая отметка
        pg.evaluate("() => goToTab('today')"); pg.wait_for_timeout(500)
        check("4.4.5 «Сегодня»: «сроки стресса подходят — сдвиньте их на «Стрессе»»", "сроки стресса подходят — сдвиньте их на «стрессе»" in norm(pg.evaluate("() => document.querySelector('#content').innerText")).lower())
        # (д) срок прошёл
        pg.evaluate("() => { state.todayOverride = '2027-04-05'; dsInvalidate(); }")
        actions(pg)
        gn = pg.evaluate("() => { const r = document.querySelector('#act-do [data-stress-terms]'); return r ? { t: r.innerText, high: r.classList.contains('sev-high') } : null; }")
        check(f"4.4.5 срок прошёл: sev-high и «прошёл» ({gn and norm(gn['t'])[:120]!r})", gn and gn["high"] and "ближайший срок стресса (31.03.2027) прошёл → сдвиньте сроки" in norm(gn["t"]))
        # одиночная строка: стресс свежий, прогнозы не заменены, срок подменён на 15.12 при дате 30.10
        for fp in (FIX / "forecasts").glob("*.yaml"):
            fp.write_text(re.sub(r"(?m)^superseded_by:.*\n", "", fp.read_text(encoding="utf-8")), encoding="utf-8")
        browser.close()
        browser, pg, errs2, site = open_page(p, width=1400, with_plan=False)
        pg.evaluate("() => { state.data.stressCurrent.parsed.horizon_ends = { h6: '2026-12-15' }; dsInvalidate(); }")
        actions(pg)
        al = pg.evaluate("""() => { const r = document.querySelector('#act-do [data-stress-terms]');
          return { r: !!r, cmds: r ? [...r.querySelectorAll('.ui-claude-cmd')].map(b => b.dataset.cmd) : [], mid: r && r.classList.contains('sev-medium'), t: r ? r.innerText : '',
                   rows: document.querySelectorAll('#act-do > :not(.ui-head)').length, cnt: actionBlocks().n.do }; }""")
        check(f"4.4.5 одиночная строка: sev-medium, команды у строки нет (сдвиг — на сайте), счётчик = строкам ({al['cmds']}, {al['mid']}, {al['cnt']}, {al['rows']})",
              al["r"] and al["mid"] and not al["cmds"] and al["cnt"] == al["rows"]
              and "сдвиньте сроки: «Стресс» → «Настройки стресса»" in norm(al["t"]))
        pg.set_viewport_size({"width": 390, "height": 844})
        actions(pg)
        sw = pg.evaluate("() => document.documentElement.scrollWidth")
        check(f"4.4.5 390: страница не шире экрана ({sw})", sw <= 390)
        check(f"ошибок страницы нет (сроки стресса) ({(errs + errs2)[:2]})", not (errs + errs2))
        browser.close()

        # 4.4.6 (владелец 06.11): матрица сценариев заменена (superseded_by) — стресс и входы остались на прежней: одна строка «Сделать»
        # с цепочкой «полный пайплайн → стресс», вместо быстрой «Обнови макро-прогноз»
        OLDM = "scenarios/scenario-geopolitics-ru-west-2026-07-01.yaml"
        NEWM = "scenarios/scenario-geopolitics-ru-west-2026-11-01.yaml"

        def build_matrix(link=True, onnew=False, cycle=False, replaced=True):
            build()
            old = FIX / OLDM
            if replaced:
                new_text = old.read_text(encoding="utf-8")
                (FIX / NEWM).write_text(re.sub(r"(?m)^status: active$", "status: active" + ("\nsuperseded_by: scenario-geopolitics-ru-west-2026-07-01.yaml" if cycle else ""), new_text, count=1), encoding="utf-8")
                old.write_text(re.sub(r"(?m)^status: active$", "status: superseded\nsuperseded_by: scenario-geopolitics-ru-west-2026-11-01", old.read_text(encoding="utf-8"), count=1), encoding="utf-8")
            if onnew:
                for fp in (FIX / "forecasts").glob("*.yaml"):
                    fp.write_text(fp.read_text(encoding="utf-8").replace(OLDM, NEWM), encoding="utf-8")
            if not link:
                mp2 = FIX / "macro-chain/macro-scenarios-2026-10-04.yaml"
                mp2.write_text(re.sub(r"(?s)\Aforecast_files:\n(?:  .*\n)+", "", mp2.read_text(encoding="utf-8")), encoding="utf-8")

        MXQ = """() => { const say = ['/macro-forecast-chain Запусти полный пайплайн: матрица сценариев заменена', '/portfolio-scenario-stress Прогони стресс на 6-12-24'];
          const rows = [...document.querySelectorAll('#act-do [data-stress-matrix]')], r = rows[0];
          return { n: rows.length, t: r ? r.innerText : '', cmds: [...document.querySelectorAll('#act-do .ui-claude-cmd')].map(b => b.dataset.cmd),
                   say, quick: document.querySelector('#act-do').innerText.includes('Обнови макро-прогноз') || document.querySelector('#act-head').parentElement.innerText.includes('Обнови макро-прогноз'),
                   rows: document.querySelectorAll('#act-do > :not(.ui-head)').length, cnt: actionBlocks().n.do, head: document.querySelector('#act-head').innerText,
                   then: !!(r && r.querySelector('.act-then')), staleKeys: r ? r.dataset.stale || null : null }; }"""
        build_matrix()
        browser, pg, errs, site = open_page(p, width=1400, with_plan=False)
        pg.evaluate("() => { state.todayOverride = '2026-11-06'; dsInvalidate(); }")
        actions(pg)
        mx = pg.evaluate(MXQ)
        t = norm(mx["t"])
        check(f"4.4.6 (а) матрица заменена: одна строка data-stress-matrix, «пересобрать прогнозы на ней», факторы под шапкой ({mx['n']}, {t[:260]!r})",
              mx["n"] == 1 and "матрица сценариев заменена (новая от 01.11)" in t and "пересобрать прогнозы на ней и перегнать стресс" in t
              and "на прежней матрице:" in t and "Brent" not in t.split("на прежней матрице:")[0] and "значения по сценариям даны для прежних осей" in t)
        check(f"4.4.6 (а) фраза строки — «Запусти полный пайплайн» и стресс ({mx['cmds'][:4]})", mx["say"][0] in mx["cmds"] and mx["say"][1] in mx["cmds"])
        check(f"4.4.6 (б) в «Действиях» нет «Обнови макро-прогноз» ({mx['quick']})", not mx["quick"] and not any("Обнови макро-прогноз" in c for c in mx["cmds"]))
        check(f"4.4.6 (б) стресс устарел/«есть новее» слиты в строку матрицы: одна пара кнопок, счётчик = строкам = шапке ({mx['cmds'].count(mx['say'][0])}, {mx['cnt']}, {mx['rows']})",
              mx["cmds"].count(mx["say"][0]) == 1 and mx["cmds"].count(mx["say"][1]) == 1 and mx["cnt"] == mx["rows"] and f"{mx['cnt']} сделать" in norm(mx["head"]))
        check(f"4.4.6 (в) интегрированный вид устарел → «затем: …» в строке матрицы, своей строки нет ({mx['then']})",
              mx["then"] and pg.locator("#act-do [data-stress-matrix] [data-then='integratedView']").count() == 1 and pg.locator("#act-do [data-stale='integratedView']").count() == 0)
        pg.evaluate("() => goToTab('today')"); pg.wait_for_timeout(500)
        check("4.4.6 (ж) «Сегодня»: «матрица сценариев заменена — пересобрать прогнозы и стресс»",
              "матрица сценариев заменена — пересобрать прогнозы и стресс" in norm(pg.evaluate("() => document.querySelector('#content').innerText")).lower())
        pg.evaluate("() => goToTab('scenarios')"); pg.wait_for_timeout(500)
        nm = pg.evaluate("() => { const e = document.querySelector('#stress-matrix-replaced'); return e ? { t: e.innerText, cmds: e.querySelectorAll('.ui-claude-cmd').length } : null; }")
        check(f"4.4.6 (ж) «Стресс»: заметка #stress-matrix-replaced без команд ({nm})",
              nm and nm["cmds"] == 0 and "Матрица сценариев заменена (новая от 01.11): стресс посчитан на прежней. Команда — на «Действиях»." in norm(nm["t"]))
        check(f"ошибок страницы нет (матрица заменена) ({errs[:2]})", not errs)
        browser.close()

        # (г) прогнозы уже на новой матрице
        build_matrix(onnew=True)
        browser, pg, errs, site = open_page(p, width=1400, with_plan=False)
        actions(pg)
        mx = pg.evaluate(MXQ); t = norm(mx["t"])
        check(f"4.4.6 (г) прогнозы уже на новой матрице: «прогнозы уже на ней → перегнать стресс», без списка факторов ({t[:200]!r})",
              mx["n"] == 1 and "прогнозы уже на ней → перегнать стресс" in t and "на прежней матрице" not in t and mx["say"][0] in mx["cmds"])
        browser.close()

        # без ссылки стресса на прогнозы
        build_matrix(link=False)
        browser, pg, errs, site = open_page(p, width=1400, with_plan=False)
        actions(pg)
        mx = pg.evaluate(MXQ)
        check(f"4.4.6 ссылка стресса на прогнозы не записана: строка матрицы со своей подстрокой ({norm(mx['t'])[:200]!r})",
              mx["n"] == 1 and "ссылка стресса на прогнозы не записана — какие прогнозы пересобирать, скажет скилл" in norm(mx["t"]))
        browser.close()

        # (д) матрица без superseded_by — строки нет, команды прежние
        build_matrix(replaced=False)
        browser, pg, errs, site = open_page(p, width=1400, with_plan=False)
        pg.evaluate("() => { state.todayOverride = '2026-11-04'; dsInvalidate(); }")
        actions(pg)
        mx = pg.evaluate(MXQ)
        check(f"4.4.6 (д) матрица не заменена: строки нет, команда прежняя «Обнови макро-прогноз» ({mx['n']}, {mx['quick']})",
              mx["n"] == 0 and mx["quick"] and mx["say"][0] not in mx["cmds"])
        pg.evaluate("() => goToTab('scenarios')"); pg.wait_for_timeout(500)
        check("4.4.6 (д) заметки на «Стрессе» нет", pg.locator("#stress-matrix-replaced").count() == 0)
        browser.close()

        # (е) цикл superseded_by не подвешивает страницу
        build_matrix(cycle=True)
        browser, pg, errs, site = open_page(p, width=1400, with_plan=False)
        actions(pg)
        mx = pg.evaluate(MXQ)
        check(f"4.4.6 (е) цикл superseded_by: страница жива, строка одна ({mx['n']})", mx["n"] == 1)
        check(f"ошибок страницы нет (цикл матриц) ({errs[:2]})", not errs)
        browser.close()

main()
shutil.rmtree(FIX, ignore_errors=True)
print(f"Итого: {passed} из {passed + failed} прошли" if failed == 0 else f"Итого: {passed} из {passed + failed} прошли (падений: {failed})")
sys.exit(1 if failed else 0)
