#!/usr/bin/env python3
"""Вьюер, шаг 12: «последнее слово» по полям (модуль (б), schema.md §3.5) на «Действиях», в карточке и в окне «Решения» —
настоящий Chromium, фикстура формата 2 (решения decisions/, условия conditions@2 + состояние, обзоры с recorded_at).

Бывший test_viewer_superseded (3.114: замещение строки обзора гейтом/отчётом по регулярке режима) — слой удалён (decision.md R12):
замещает только записанное решение новее обзора; отчёт без решения не замещает.
Фикстура superseded — живые файлы, переведённые миграциями шагов 5–9 (обзор акций 28.10, решения бэкфилла, conditions@2, отчёты report@1).
Контракты:
  1. Решения GMKN новее обзора нет (файл решения 29.10 убран): GMKN на «Действиях» («К сведению»), в «Сделано» его нет; отчёт 29.10 без решения не замещает.
  2. Решение GMKN 29.10 (WATCH) новее обзора 28.10: строки обзора нет, в «Сделано» — «заменено решением 29.10: наблюдать»; «к сведению» меньше на 1;
     карточка (R27): «решение 29.10 · обзор 28.10», строка решения «… 29.10: наблюдать · срок решения 13.12», «Докупка: закрыта: наблюдать, до 13.12».
  3. GMKN-повтор (приёмка decision.md §4 строка 12): обзор D (28.10), решение D+1 (29.10, доля 2 %, условие), обзор D+7 (04.11, TRIM) —
     вердикт карточки из обзора D+7, доля и условия — из решения; плашка конфликта (обзор «вниз» против решения «ровно»); строка журнала
     плана stocks.GMKN.user_status после конфликта закрывает его — плашки нет.
  4. Условия: X5 (закрыто событием done по решению) ничего не ждёт; RENI (ждущее условие) — «Ждёт условия».
  5. Интегрированный вид строк в «Действия» не даёт ни старый, ни свежий (R19).
  6. Пять бумаг с разными причинами блокировки (гейт по сроку, пауза докупки, IPO-пауза, условие «держать», условие на покупку):
     «Сейчас» вьюера = gate_aware_sizing.py --auto на тех же входах (причины и «до когда»), подписи — словами без кодов.
  7. Окно «Решения»: строки бумаг с последним словом, история решений GMKN со ссылкой на отчёт, фильтр по статусу гейта.
  8. Ошибок страницы нет.
  9. Решение владельца с карточки бумаги (no-ai-mode 2.2): кнопки «Подтверждаю держать» и «Проверить качество» у акции, облигации
     и фонда — только в режиме «без ИИ» (data-noai; при «с ИИ» кнопок нет); «Подтверждаю держать» — подтверждение, затем POST /api/pf/decision
     одна кнопка «Записать решение» (11.11): форма — вердикт (текущий, иначе «держать»), срок +60, уверенность, обязательное «почему»; доли в форме нет;
     отмена подтверждения — запроса нет; форма: вердикт, цель, срок (календарь, по умолчанию +60), заметка (обязательна, ≥ 20),
     уверенность; ошибки сервера 409/400/502 — понятным текстом; после записи решение — в «Истории» карточки; 1280 и 390 без горизонтальной прокрутки.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_last_word.py
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import quote as _q, unquote as _unq, urlparse as _up

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import serve  # noqa: E402  (стенд — _pages_stand, keep-alive)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viewer_ds import DS_SET, attr, cond, dec, day, ev  # noqa: E402
PY = sys.executable
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
    print("viewer_last_word: пропуск — нет playwright")
    sys.exit(0)

sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as hub_api  # noqa: E402

FIX = Path(tempfile.mkdtemp(prefix="lastword-"))
IV_ROWS = """
## 5. Действия с высоким приоритетом

| Тикер | Название | Вердикт | Горизонт | Действие |
|---|---|---|---|---|
| LKOH | Лукойл | TRIM | 12 | Срезать до плана по интеграционному анализу |
"""


def build(gmkn_decision=True, repeat=False, iv=None):
    """gmkn_decision: решение GMKN 29.10 в decisions/. repeat: обзор D+7 (04.11, GMKN TRIM) и доля/условие у решения 29.10.
    iv: None | 'old' | 'fresh' — интегрированный вид."""
    import yaml
    from datetime import date
    shutil.rmtree(FIX, ignore_errors=True)
    shutil.copytree(REPO / "tools/tests/fixtures/viewer-live", FIX)
    shutil.copytree(REPO / "tools/tests/fixtures/superseded", FIX, dirs_exist_ok=True)
    (FIX / "monitor-reports").mkdir()
    pf = FIX / "Portfolio"
    gd = pf / "decisions/2026-10-29T0000-GMKN.json"
    if not gmkn_decision:
        gd.unlink()
    if repeat:
        d = json.loads(gd.read_text(encoding="utf-8"))
        d.update(target_pct=2.0, conditions_created=["gmkn-palladium"])
        gd.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        src = pf / "weekly-reviews/weekly-review-stock-2026-10-28.yaml"
        r = yaml.safe_load(src.read_text(encoding="utf-8"))
        r.update(review_date="2026-11-04", recorded_at="2026-11-04T00:00:00+03:00")
        r["per_stock"]["GMKN"]["advisor_verdict"] = "TRIM"
        r["per_stock"]["GMKN"]["advisor_verdict_basis"] = "Обзор D+7: палладий ниже, срезать к плану."
        (pf / "weekly-reviews/weekly-review-stock-2026-11-04.yaml").write_text(yaml.safe_dump(r, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if iv:
        dd = date.today().isoformat() if iv == "fresh" else "2026-09-27"
        old = pf / "integrated-views/integrated-view-2026-09-27.md"
        t = old.read_text(encoding="utf-8").replace("view_date: 2026-09-27", f"view_date: {dd}") + IV_ROWS
        old.unlink()
        (pf / f"integrated-views/integrated-view-{dd}.md").write_text(t, encoding="utf-8")


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
    """бумаги строк обзора и решений на «Действиях»: «Сделать», «Проверить», «Ждём», «К сведению»."""
    return pg.evaluate("""() => [...document.querySelectorAll('#act-do .act-dec[data-ticker], #act-wait .act-dec[data-ticker]')].map(e => e.dataset.ticker)
      .concat([...document.querySelectorAll('#act-check [data-check]')].map(e => e.dataset.check.split('|')[0]))
      .concat([...document.querySelectorAll('#act-info [data-info]')].map(e => e.dataset.info))""")


def done_text(pg, t):
    loc = pg.locator(f'#content #act-done [data-superseded="{t}"]')
    return loc.first.text_content().strip() if loc.count() else None


def tile(pg, label):
    m = re.search(r"(\d+) " + label, pg.locator("#content #act-head").inner_text(), re.I)
    return int(m.group(1)) if m else 0


def open_actions(p, journal=None):
    """journal: None → 502; список записей → ответ API журнала плана."""
    browser = p.chromium.launch()
    ctx = browser.new_context(service_workers="block", viewport={"width": 1400, "height": 1000})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "502" not in m.text and "404" not in m.text else None)
    pg.route("**/api/pv/plan", lambda r: r.fulfill(status=502, body="{}"))
    pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, body="{}"))
    pg.route("**/api/pv/plan/journal*", (lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"entries": journal})))
             if journal is not None else (lambda r: r.fulfill(status=502, body="{}")))
    pg.goto(URL)
    pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
    pg.wait_for_function("() => state.data && state.data.portfolioLatest && state.data.weeklyReviewCurrent && state.data.decisions.length", timeout=20000)
    pg.evaluate("() => { goToTab('actions'); }")
    pg.wait_for_selector("#content #act-head", timeout=10000)
    pg.wait_for_timeout(600)   # журнал плана и возможная перерисовка
    return browser, pg, errs


def card_dec(pg, t):
    pg.evaluate("(t) => { const pbt = buildPositionByTicker(); openCard(pbt[t], [pbt[t]]); }", t)
    pg.wait_for_selector("#card-layer .card-dec", timeout=8000)
    pg.wait_for_timeout(200)
    return pg.evaluate("() => document.querySelector('#card-layer .card-dec').innerText.replace(/\\s+/g, ' ')")


def main():
    with sync_playwright() as p:
        try:
            p.chromium.launch().close()
        except Exception as e:
            print(f"viewer_last_word: пропуск — {str(e).splitlines()[0][:80]}")
            return

        # 1: решения GMKN новее обзора нет — отчёт 29.10 без решения не замещает
        build(gmkn_decision=False)
        browser, pg, errs = open_actions(p)
        base_dec = tile(pg, "к сведению")   # GMKN — «держать», проверка «желательно»: «К сведению» (пачка 3 читаемости)
        rows = dec_tickers(pg)
        check(f"без решения 29.10: GMKN на «Действиях» (отчёт 29.10 без решения не замещает) ({rows})", "GMKN" in rows)
        check("в «Сделано» GMKN нет", done_text(pg, "GMKN") is None)
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # 2: решение 29.10 новее обзора 28.10
        build()
        browser, pg, errs = open_actions(p)
        rows = dec_tickers(pg)
        check(f"решение 29.10: GMKN нет в строках обзора «Действий» ({rows})", "GMKN" not in rows)
        t = done_text(pg, "GMKN") or ""
        check(f"«Сделано»: «заменено решением 29.10: наблюдать» и обзор акций 28.10 ({t!r})", "заменено решением 29.10: наблюдать" in t and "обзор акций 28.10" in t)
        check(f"«к сведению» в шапке меньше на 1 ({tile(pg, 'к сведению')} против {base_dec})", tile(pg, "к сведению") == base_dec - 1)
        pg.evaluate("() => { document.querySelector('#content #act-done').open = true; }")
        pg.locator('#content #act-done [data-superseded="GMKN"]').click()
        pg.wait_for_selector("#card-layer .card-dec", timeout=8000)
        txt = pg.evaluate("() => document.querySelector('#card-layer .card-dec').innerText.replace(/\\s+/g, ' ')")
        check(f"карточка: «решение 29.10 · обзор 28.10», строка решения «29.10: наблюдать · срок решения 13.12» ({txt[:220]!r})",
              "решение 29.10 · обзор 28.10" in txt and re.search(r"(Решение|Разбор) 29\.10: наблюдать · срок решения 13\.12", txt) is not None)
        check(f"карточка: «Докупка: закрыта: наблюдать, до 13.12» ({txt[:300]!r})", "Докупка: закрыта: наблюдать, до 13.12" in txt and "гейт" not in txt.lower())
        check("карточка: ссылка «разбор от 29.10» (source.doc решения), без пути файла", "разбор от 29.10" in txt and "Portfolio/" not in txt and ".md" not in txt)
        # 4: условия
        check("X5: условие закрыто (done по решению) — строка действия не «ждёт условия»", pg.evaluate("() => _actionItems().find(i => i.ticker === 'X5')?.cond ?? null") is None)
        check("RENI: ждущее условие — «Ждёт условия»", bool(pg.evaluate("() => _actionItems().find(i => i.ticker === 'RENI')?.cond || conditionsForTicker('RENI').some(c => c.status === 'pending')")))
        # 7: окно «Решения»
        pg.evaluate("() => { cardStack.length = 0; renderCards(); showGateLegendModal(''); }")
        pg.wait_for_timeout(300)
        win = pg.evaluate("""() => { const r = document.querySelector('#modal-body .dec-row[data-key="GMKN"]'); if (r) r.open = true;
          return { keys: [...document.querySelectorAll('#modal-body .dec-row')].map(x => x.dataset.key),
                   gm: r ? r.innerText.replace(/\\s+/g, ' ') : '', hist: r ? r.querySelectorAll('.dec-h').length : 0, doc: r ? r.querySelectorAll('.dec-doc').length : 0,
                   chips: [...document.querySelectorAll('#modal-body .dec-filter .ui-seg-btn')].map(b => b.textContent) }; }""")
        check(f"«Решения»: строки бумаг из decisions/ (GMKN, X5, TMON) ({len(win['keys'])})", all(k in win["keys"] for k in ("GMKN", "X5", "TMON")))
        check(f"«Решения»: история GMKN — все решения, у разборов ссылка «отчёт» ({win['hist']}, {win['doc']})", win["hist"] >= 5 and win["doc"] >= 2)
        check(f"«Решения»: GMKN — «докупка закрыта: наблюдать, до 13.12» из решения WATCH ({win['gm'][:160]!r})", "докупка закрыта: наблюдать, до 13.12" in win["gm"] and "гейт" not in win["gm"])
        flt = [c for c in win["chips"] if c.startswith("наблюдать")]
        check(f"«Решения»: фильтр по статусу гейта ({win['chips'][:4]})", bool(flt))
        if flt:
            pg.evaluate("(t) => [...document.querySelectorAll('#modal-body .dec-filter .ui-seg-btn')].find(b => b.textContent === t).click()", flt[0])
            pg.wait_for_timeout(200)
            sk = pg.evaluate("() => [...document.querySelectorAll('#modal-body .dec-row')].map(x => x.dataset.key)")
            check(f"фильтр «наблюдать» оставляет только такие бумаги ({sk})", "GMKN" in sk and "X5" not in sk)
        pg.evaluate("() => { state.decFilter = ''; closeModal(); }")
        check(f"ошибок страницы нет ({errs[:2]})", not errs)

        # 6: пять бумаг с разными причинами блокировки — вьюер = Python
        pg.evaluate("() => { goToTab('ie-model'); }")
        pg.wait_for_timeout(300)
        picks = pg.evaluate("""() => { const P = currentPort(), pt = P.ie_actual.per_ticker;
          const ts = P.holdings.filter(h => h.asset_type === 'stock' && +h.qty > 0 && pt[h.ticker] && h.current_price_source !== 'cost_basis').map(h => h.ticker).slice(0, 5);
          for (const t of ts) { pt[t].planned_share_pct = (pt[t].real_share_pct || 0) + 4; pt[t].user_plan = 'BUY'; }
          return ts; }""")
        today = pg.evaluate("() => dsToday()")
        lw_dec = [dec(picks[0], "HOLD", day(-120), review_by=day(-30)), dec(picks[1], "BUY", day(-3)), dec(picks[2], "HOLD", day(-5)),
                  dec(picks[3], "HOLD", day(-5)), dec(picks[4], "HOLD", day(-5))]
        lw_attrs = {picks[2]: attr("ipo", day(-200))}
        lw_defs = [cond("lw-hold", picks[3], "date", day(40), verdict_now="HOLD", on_verdict="HOLD"),
                   cond("lw-buy", picks[4], "price_below", 1, kind="trade", verdict_now=None, on_verdict="BUY", action="set_verdict", text="докупить")]
        pg.evaluate(DS_SET, {"decisions": lw_dec, "attrs": lw_attrs, "defs": lw_defs, "events": []})
        # правило 7 (§10.6 п.5): пауза докупки — от ПЕРВОЙ ПОКУПКИ после решения BUY/ADD; в фикстуре покупки по RENI нет (решение BUY
        # само по себе паузу не даёт), поэтому покупку задаём явно: у вьюера — подменой dsLastTradeAt (через buys_at, как из
        # снапшотов), у Python — парой снапшотов в папке (--snapshot): без бумаги раньше и с ней сегодня
        pg.evaluate("(t) => { const at = dsToday() + 'T00:00:00+03:00'; window.dsLastTradeAt = () => ({ trade: { [t]: at }, sell: {}, buy: { [t]: at }, buys: { [t]: [at] } }); dsInvalidate(); }", picks[1])
        js = pg.evaluate("() => { const a = nowAutoResult(); return { rows: a.rows.map(r => ({ ticker: r.ticker, reason: r.reason, unblock_by: r.unblock_by, category: r.category })),"
                         " port: currentPort(), ru: Object.fromEntries(a.rows.filter(r => r.reason).map(r => [r.ticker, reasonRu(r.reason, r.ticker)])) }; }")
        with tempfile.TemporaryDirectory() as tmp:
            tp = Path(tmp)
            cur = dict(js["port"]); cur["as_of_date"] = today
            old = dict(cur, as_of_date=day(-10), holdings=[h for h in cur["holdings"] if h.get("ticker") != picks[1]])
            (tp / f"portfolio-{day(-10)}.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
            (tp / "snap.json").write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
            (tp / f"portfolio-{today}.json").write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
            (tp / "decisions").mkdir()
            for d in lw_dec:
                (tp / "decisions" / f"{d['id']}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            (tp / "attrs.json").write_text(json.dumps({"schema_version": "security-attrs@1", "by_key": lw_attrs}), encoding="utf-8")
            import yaml
            (tp / "conditions.yaml").write_text(yaml.safe_dump({"schema_version": "conditions@2", "conditions": lw_defs}, allow_unicode=True), encoding="utf-8")
            (tp / "state.json").write_text(json.dumps({"schema_version": "conditions-state@1", "events": []}), encoding="utf-8")
            revs = sorted(str(x) for x in (FIX / "Portfolio/weekly-reviews").glob("weekly-review-stock-*.yaml"))
            cmd = [PY, str(REPO / "skills/ru-portfolio-advisor/scripts/gate_aware_sizing.py"), "--snapshot", str(tp / f"portfolio-{today}.json"),
                   "--decisions", str(tp / "decisions"), "--security-attrs", str(tp / "attrs.json"),
                   "--conditions", str(tp / "conditions.yaml"), "--conditions-state", str(tp / "state.json"), "--today", today, "--auto", "--json"]
            for rv in revs:
                cmd += ["--reviews", rv]
            proc = subprocess.run(cmd, capture_output=True, text=True)
        check(f"gate_aware_sizing --auto на тех же входах отработал ({proc.stderr[-200:]!r})", proc.returncode == 0)
        py = {r["ticker"]: r for r in json.loads(proc.stdout)["rows"]} if proc.returncode == 0 else {}
        jr = {r["ticker"]: r for r in js["rows"]}
        want = {picks[0]: "gate:review_aging", picks[1]: "add_cooldown:", picks[2]: "ipo_gate:", picks[3]: "condition_hold:lw-hold", picks[4]: "pending_buy_condition"}
        for t, w in want.items():
            j, pr = jr.get(t, {}), py.get(t, {})
            check(f"{t}: причина «{w}…» у вьюера и Python совпадает ({j.get('reason')!r} / {pr.get('reason')!r}; {j.get('unblock_by')!r} / {pr.get('unblock_by')!r})",
                  (j.get("reason") or "").startswith(w) and j.get("reason") == pr.get("reason") and j.get("unblock_by") == pr.get("unblock_by")
                  and j.get("category") == pr.get("category") == "blocked")
        same = all(jr[t].get("reason") == py.get(t, {}).get("reason") for t in jr)
        check(f"все строки «Сейчас»: причины вьюера = Python ({len(jr)} бумаг)", same and len(jr) == len(py))
        ru = " | ".join(js["ru"].get(t, "") for t in picks)
        check(f"подписи пяти причин — словами, без кодов ({ru[:200]!r})",
              not re.search(r"gate:|review_|_condition|condition_hold|ipo_gate|add_cooldown|user_plan", ru) and "IPO-пауза" in ru and "пауза после докупки" in ru)
        # 2.1 (решение 11.11): режим «без ИИ» (data-noai) блокирует теми же статусами; блок снимает решение владельца; ctx вьюера несёт ai_mode
        md = pg.evaluate("""(t) => { const run = () => ({ l0: buyLineText(t[0]), l1: buyLineText(t[1]), l2: buyLineText(t[2]), ai: lwCtx().ai_mode });
            const on = run(); uiAiModeApply('off'); const off = run(); uiAiModeApply('on'); const back = run(); return { on, off, back }; }""", picks)
        check(f"режим on: «Докупка: закрыта: срок решения вышел…» ({md['on']['l0']!r}, ctx {md['on']['ai']})",
              md["on"]["ai"] == "on" and md["on"]["l0"].startswith("Докупка: закрыта: срок решения вышел"))
        check(f"режим off: истёкший срок — «закрыта: срок решения вышел …, откроет твоё решение» ({md['off']['l0']!r}, ctx {md['off']['ai']})",
              md["off"]["ai"] == "off" and md["off"]["l0"].startswith("Докупка: закрыта: срок решения вышел")
              and md["off"]["l0"].endswith(", откроет твоё решение") and "откроет разбор" not in md["off"]["l0"])
        check(f"режим off: пауза докупки и IPO-пауза по-прежнему закрывают ({md['off']['l1']!r} / {md['off']['l2']!r})",
              md["off"]["l1"].startswith("Докупка: закрыта: пауза после докупки") and md["off"]["l2"].startswith("Докупка: закрыта: IPO-пауза"))
        check(f"возврат в on — снова блок ({md['back']['l0']!r})", md["back"] == md["on"])
        # решение владельца при «с ИИ» докупку не открывает: «подтверждено вами дд.мм — откроет разбор советника»; при off — как любое решение: блок снят
        ow_dec = lw_dec + [dec(picks[0], "HOLD", day(-1), review_by=day(60), kind="owner", author="owner", note="Подтверждено владельцем без разбора")]
        pg.evaluate(DS_SET, {"decisions": ow_dec, "attrs": lw_attrs, "defs": lw_defs, "events": []})
        mo = pg.evaluate("""(t) => { const on = buyLineText(t); uiAiModeApply('off'); const off = buyLineText(t); uiAiModeApply('on');
            return { on, off, gate: lwCard(t).gate }; }""", picks[0])
        ddmm = pg.evaluate("(d) => _ddmmDot(d)", day(-1))
        check(f"on: решение владельца новее истёкшего разбора — «закрыта: срок решения вышел …; подтверждено вами {ddmm} — откроет разбор советника» ({mo['on']!r})",
              mo["gate"]["owner_pending_review"] is True and mo["on"].startswith("Докупка: закрыта: срок решения вышел")
              and f"подтверждено вами {ddmm} — откроет разбор советника" in mo["on"] and mo["on"].count("откроет разбор") == 1)
        check(f"off: решение владельца снимает блок — «Докупка: открыта» без «подтверждено вами» и без «но …» ({mo['off']!r})",
              mo["off"] == "Докупка: открыта")
        pg.evaluate(DS_SET, {"decisions": lw_dec, "attrs": lw_attrs, "defs": lw_defs, "events": []})
        browser.close()

        # 3: GMKN-повтор — обзор D, решение D+1, обзор D+7
        build(repeat=True)
        browser, pg, errs = open_actions(p)
        txt = card_dec(pg, "GMKN")
        check(f"повтор: вердикт из обзора D+7 (04.11) — «Сократить», последнее слово «обзор 04.11» ({txt[:200]!r})",
              "Сократить" in txt and "обзор 04.11" in txt)
        check(f"повтор: доля и условия — из решения 29.10 («целевая доля 2,0%», «условий создано 1») ({txt[:300]!r})",
              re.search(r"(Решение|Разбор) 29\.10: \w+", txt) is not None and "целевая доля 2,0%" in txt and "условий создано 1" in txt)
        check(f"повтор: плашка конфликта — обзор «вниз» против решения ({txt[txt.find('Источники'):][:160]!r})",
              "Источники расходятся" in txt and "обзор 04.11" in txt and "решение 29.10" in txt)
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()
        browser, pg, errs = open_actions(p, journal=[{"ts": "2026-11-05T09:00:00+03:00", "who": "site", "path": "stocks.GMKN.user_status", "was": None, "now": "NOTED", "reason": "тест"}])
        pg.evaluate("() => planJournalLoad(true)")
        pg.wait_for_timeout(300)
        pg.evaluate("() => dsInvalidate()")
        txt = card_dec(pg, "GMKN")
        check(f"повтор: правка плана после конфликта закрывает его — плашки нет ({txt[:120]!r})", "Источники расходятся" not in txt and "Сократить" in txt)
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # 5: интегрированный вид строк не даёт (R19)
        for iv in ("old", "fresh"):
            build(iv=iv)
            browser, pg, errs = open_actions(p)
            check(f"интегрированный вид ({iv}): строк в «Действиях» нет", pg.locator('#content .act-dec[data-ticker="LKOH"]').count() == 0)
            check(f"ошибок страницы нет ({errs[:2]})", not errs)
            browser.close()


        # 9: решение владельца с карточки (no-ai-mode 2.2) — POST /api/pf/decision подменён
        build()
        from viewer_ds import at as _at
        for vw in (1280, 390):
            browser, pg, errs = open_actions(p)
            pg.set_viewport_size({"width": vw, "height": 900})
            posts, mode = [], ["ok"]

            def _decision_route(route):
                body = json.loads(route.request.post_data or "{}")
                posts.append(body)
                m = mode[0]
                if m == "409":
                    return route.fulfill(status=409, content_type="application/json", body=json.dumps({"error": "решение этой минуты по бумаге уже есть — подожди минуту"}))
                if m == "400":
                    return route.fulfill(status=400, content_type="application/json", body=json.dumps({"error": "review_by: срок пересмотра — от 7 до 180 дней от сегодня (сейчас 3)"}))
                if m == "502":
                    return route.fulfill(status=502, content_type="application/json", body="{}")
                d = dec(body["key"], body["verdict"], _at(day(0), f"12:{len(posts):02d}"), target_pct=body.get("target_pct"), review_by=body["review_by"],
                        note=body["note"], kind="owner", author="owner", confidence=body.get("confidence"))
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"saved": f"Portfolio/decisions/{d['id']}.json", "decision": d}))
            pg.route("**/api/pf/decision", _decision_route)

            def open_card(t):
                pg.evaluate("(t) => { cardStack.length = 0; renderCards(); const pbt = buildPositionByTicker(); openCard(pbt[t], [pbt[t]]); }", t)
                pg.wait_for_selector("#card-layer .card-dec", timeout=8000)
                pg.wait_for_timeout(200)

            def sub(v):
                pg.evaluate("(v) => document.querySelector('#card-layer [data-act=\"card-sub\"][data-v=\"' + v + '\"]').click()", v)
                pg.wait_for_timeout(250)

            def say():
                return pg.evaluate("() => (document.querySelector('#card-layer .card-owner-msg')?.textContent || '').trim()")

            tag = f"[{vw}] "
            # кнопки решения владельца — только в режиме «без ИИ» (решение владельца 11.11): при «с ИИ» их нет
            open_card("GMKN")
            check(tag + "режим «с ИИ»: кнопок решения владельца в карточке нет",
                  pg.locator("#card-layer .card-owner-open").count() == 0)
            nd_on = pg.evaluate("() => { const n = cardDecisionNode({ ticker: 'ZZZZ', name: 'Тест' }, 'stock'); return n ? n.textContent : null; }")
            check(tag + f"режим «с ИИ»: у бумаги без решения блока с кнопками нет ({str(nd_on)[:80]!r})", not nd_on or "Решения по бумаге ещё нет" not in nd_on)
            pg.evaluate("() => document.documentElement.setAttribute('data-noai', '')")     # дальше в блоке — режим «без ИИ»
            open_card("GMKN")
            check(tag + "режим «без ИИ»: одна кнопка «Записать решение» (кнопки «Подтверждаю держать» нет)",
                  pg.locator("#card-layer .card-owner-open").is_visible() and pg.locator("#card-layer .card-owner-open").inner_text().strip() == "Записать решение"
                  and pg.locator("#card-layer .card-owner-hold").count() == 0)
            # держимая бумага без единого решения: блок «Решение» есть — «Решения по бумаге ещё нет» и обе кнопки (первое решение с сайта)
            # (в фикстуре у всех держимых решения есть — ветку проверяем на синтетической бумаге ZZZZ: ни решения, ни продажи)
            nd = pg.evaluate("""() => { const n = cardDecisionNode({ ticker: 'ZZZZ', name: 'Тест' }, 'stock');
                const c = cardDecisionNode({ ticker: 'ZZZY', name: 'Кандидат', candidate: true }, 'fund');
                return { txt: n ? n.textContent : null, hold: 1,
                         open: n ? n.querySelectorAll('.card-owner-open').length : 0, cand: c === null }; }""")
            check(tag + f"бумага без решения: «Решения по бумаге ещё нет» и кнопка; кандидат-фонд — без блока ({str(nd['txt'])[:100]!r})",
                  (nd["txt"] or "").find("Решения по бумаге ещё нет") >= 0 and nd["hold"] == 1 and nd["open"] == 1 and nd["cand"])
            # «Подтверждаю держать» (11.11): не «да/нет», а форма с «держать» и +60 — обязательная строка «почему держу»
            HOLD_WHY = "Тезис жив, отчёт за квартал в рамках ожиданий"
            pg.click("#card-layer .card-owner-open")
            pg.wait_for_selector("#card-layer .card-owner-form:not([hidden]) textarea", timeout=4000)
            fh = pg.evaluate("""() => { const f = document.querySelector('#card-layer .card-owner-form');
                return { v: f.querySelector('[data-ui-select] input[type=hidden][id$="-verdict"]')?.value, rb: f.querySelector('input[id$="-rb"]').value,
                         lbl: [...f.querySelectorAll('.fld-lbl')].map(x => x.textContent.replace(/\\s+/g, ' ').trim()).join(' | '),
                         num: f.querySelectorAll('input[type=number]').length,
                         focus: document.activeElement === f.querySelector('textarea'), confirm: !!document.querySelector('.ui-confirm') }; }""")
            plus60 = pg.evaluate("() => _isoPlusDays(60)")
            cur = pg.evaluate("() => { const c = lwCard('GMKN'); const v = c?.decision_verdict || c?.verdict; return v === 'BUY' ? 'ADD' : v; }")
            check(tag + f"«Записать решение»: форма — вердикт текущий ({cur}), +60, «Почему» (ретро) в фокусе, доли нет, без окна «да/нет» ({fh})",
                  fh["v"] == (cur or "HOLD") and fh["rb"] == plus60 and "Почему" in fh["lbl"] and "ретро" in fh["lbl"] and "доля" not in fh["lbl"].lower()
                  and fh["num"] == 0 and fh["focus"] and not fh["confirm"])
            pg.evaluate("() => { const h = document.querySelector('#card-layer .card-owner-form [data-ui-select] input[type=hidden][id$=\"-verdict\"]'); h.value = 'HOLD'; }")
            pg.click("#card-layer .card-owner-save")
            pg.wait_for_timeout(300)
            check(tag + f"без «почему» запись не уходит ({say()!r})", posts == [] and "не меньше 20" in say())
            pg.click("#card-layer .card-owner-form .ui-btn.ghost")
            pg.wait_for_timeout(200)
            check(tag + "«Отмена» закрывает форму, запроса нет", posts == [] and pg.locator("#card-layer .card-owner-form:not([hidden])").count() == 0)
            # с причиной → POST (доли в теле нет)
            pg.click("#card-layer .card-owner-open")
            pg.wait_for_selector("#card-layer .card-owner-form:not([hidden]) textarea", timeout=4000)
            pg.evaluate("() => { const h = document.querySelector('#card-layer .card-owner-form [data-ui-select] input[type=hidden][id$=\"-verdict\"]'); h.value = 'HOLD'; }")
            pg.fill("#card-layer .card-owner-form textarea", HOLD_WHY)
            pg.click("#card-layer .card-owner-save")
            pg.wait_for_function("() => state.data.decisions.some(d => d.author === 'owner' && d.key === 'GMKN')", timeout=6000)
            check(tag + f"POST «держать»: key, HOLD, review_by +60, заметка — причина владельца, без target_pct ({posts})",
                  len(posts) == 1 and posts[0]["key"] == "GMKN" and posts[0]["verdict"] == "HOLD" and posts[0]["review_by"] == plus60
                  and posts[0]["note"] == HOLD_WHY and "target_pct" not in posts[0])
            pg.wait_for_timeout(300)
            sub("hist")
            hist = pg.evaluate("() => document.querySelector('#card-layer .card-pane')?.innerText.replace(/\\s+/g, ' ') || ''")
            check(tag + f"после записи решение и причина — в «Истории» карточки ({hist[:200]!r})", "решение: держать" in hist and HOLD_WHY in hist)
            # форма
            open_card("GMKN")
            n0 = len(posts)
            pg.click("#card-layer .card-owner-open")
            pg.wait_for_selector("#card-layer .card-owner-form:not([hidden]) textarea", timeout=4000)
            lbls = pg.evaluate("() => [...document.querySelectorAll('#card-layer .card-owner-form .fld-lbl')].map(x => x.textContent.replace(/\\s+/g, ' ').trim())")
            check(tag + f"форма: вердикт, срок, уверенность, «Почему»; доли нет ({lbls})",
                  any(x.startswith("Вердикт") for x in lbls) and not any("доля" in x.lower() for x in lbls) and any(x.startswith("Срок пересмотра") for x in lbls)
                  and any(x.startswith("Уверенность") for x in lbls) and any(x.startswith("Почему") for x in lbls))
            codes = pg.evaluate("() => [...document.querySelectorAll('#card-layer .card-owner-form [data-ui-select] .ui-select-opt, #card-layer .card-owner-form [data-ui-select] [role=option]')].length")
            hid = pg.evaluate("() => document.querySelector('#card-layer .card-owner-form input[id$=\"-rb\"]').value")
            check(tag + f"срок по умолчанию +60 дней ({hid})", hid == plus60)
            pg.fill("#card-layer .card-owner-form textarea", "коротко")
            pg.click("#card-layer .card-owner-save")
            check(tag + f"заметка короче 20 знаков — текст ошибки, запроса нет ({say()!r})", "не меньше 20" in say() and len(posts) == n0)
            pg.fill("#card-layer .card-owner-form textarea", "Тезис жив, но оценка выросла — сокращаю к плану")
            pg.evaluate("() => { document.querySelector('#card-layer .card-owner-form input[id$=\"-rb\"]').value = _isoPlusDays(3); }")
            pg.click("#card-layer .card-owner-save")
            check(tag + f"срок 3 дня — «от 7 до 180», запроса нет ({say()!r})", "от 7 до 180" in say() and len(posts) == n0)
            pg.evaluate("() => { document.querySelector('#card-layer .card-owner-form input[id$=\"-rb\"]').value = _isoPlusDays(90); }")
            pg.evaluate("() => { const h = document.querySelector('#card-layer .card-owner-form [data-ui-select] input[type=hidden][id$=\"-verdict\"]'); h.value = 'TRIM'; }")
            for m, want in (("409", "уже записано"), ("400", "срок пересмотра"), ("502", "недоступно")):
                mode[0] = m
                pg.click("#card-layer .card-owner-save")
                pg.wait_for_function("() => !/Записываю/.test(document.querySelector('#card-layer .card-owner-msg')?.textContent || '')", timeout=4000)
                check(tag + f"ответ {m} — понятный текст ({say()!r})", want in say() and "HTTP" not in say())
                check(tag + f"после {m} форма остаётся, кнопка снова доступна", pg.locator("#card-layer .card-owner-form:not([hidden])").count() == 1
                      and pg.locator("#card-layer .card-owner-save").is_enabled())
            check(tag + "ошибки не записали решение в данные", pg.evaluate("() => state.data.decisions.filter(d => d.key === 'GMKN' && d.author === 'owner').length") == 1)
            if vw == 390:
                ov = pg.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
                inside = pg.evaluate("() => { const f = document.querySelector('#card-layer .card-owner-form').getBoundingClientRect(); return f.right <= window.innerWidth + 1 && f.left >= -1; }")
                check(tag + f"форма в экране, без горизонтальной прокрутки ({ov})", ov <= 1 and inside)
                cols = pg.evaluate("() => getComputedStyle(document.querySelector('#card-layer .card-owner-grid')).gridTemplateColumns.split(' ').length")
                check(tag + f"на телефоне поля в одну колонку ({cols})", cols == 1)
            mode[0] = "ok"
            pg.click("#card-layer .card-owner-save")
            pg.wait_for_function("() => state.data.decisions.filter(d => d.key === 'GMKN' && d.author === 'owner').length === 2", timeout=6000)
            check(tag + f"POST формы: вердикт TRIM, срок +90, заметка, без доли и confidence ({posts[-1]})",
                  posts[-1] == {"key": "GMKN", "verdict": "TRIM", "review_by": pg.evaluate("() => _isoPlusDays(90)"),
                                "note": "Тезис жив, но оценка выросла — сокращаю к плану"})
            pg.wait_for_timeout(300)
            sub("hist")
            hist = pg.evaluate("() => document.querySelector('#card-layer .card-pane')?.innerText.replace(/\\s+/g, ' ') || ''")
            check(tag + "решение из формы — в «Истории» карточки", "решение: сократить" in hist and "сокращаю к плану" in hist)
            if vw == 1280:
                # уверенность уходит числом; облигация и фонд — те же кнопки
                open_card("GMKN")
                pg.click("#card-layer .card-owner-open")
                pg.wait_for_selector("#card-layer .card-owner-form:not([hidden]) textarea", timeout=4000)
                pg.fill("#card-layer .card-owner-form textarea", "Проверка уверенности: средняя, срок по умолчанию")
                pg.evaluate("() => { document.querySelector('#card-layer .card-owner-form input[type=hidden][id$=\"-conf\"]').value = '0.7'; }")
                pg.click("#card-layer .card-owner-save")
                pg.wait_for_function("() => state.data.decisions.filter(d => d.key === 'GMKN' && d.author === 'owner').length === 3", timeout=6000)
                check(tag + f"уверенность — числом ({posts[-1].get('confidence')})", posts[-1].get("confidence") == 0.7 and posts[-1]["review_by"] == plus60)
                # облигация: ключ решения — ISIN (у фикстуры нет обзора облигаций — запись строится как у окна «Решения», строка 10845)
                isin = "RU000A10TEST"
                pg.evaluate("(d) => { state.data.decisions = state.data.decisions.concat(d); dsInvalidate(); }", dec(isin, "HOLD_TO_MAT", day(-5), review_by=day(40)))
                pg.evaluate("(k) => { cardStack.length = 0; renderCards(); const e = { ...buildBondRow(k, null, null), name: 'Тест-облигация', isin: k, _kind: 'bond', accounts: { main: null, iis_3: null } }; openCard(e, [e]); }", isin)
                pg.wait_for_selector("#card-layer .card-dec", timeout=8000)
                pg.wait_for_timeout(200)
                check(tag + "карточка облигации: кнопки, ключ — ISIN", pg.locator(f'#card-layer .card-owner-dec[data-owner-dec="{isin}"] .card-owner-open').count() == 1)
                fund = pg.evaluate("() => (fundEntries()[0] || {}).ticker || null")
                pg.evaluate("() => { cardStack.length = 0; renderCards(); const f = fundEntries()[0]; openCard(f, [f]); }")
                pg.wait_for_selector("#card-layer .card-cols", timeout=8000)
                pg.wait_for_timeout(200)
                check(tag + f"карточка фонда: кнопки ({fund})", bool(fund) and pg.locator(f'#card-layer .card-owner-dec[data-owner-dec="{fund}"] .card-owner-open').count() == 1)
            errs = [e for e in errs if "409" not in e and "400" not in e]   # 409 и 400 — подставленные ответы для проверки текстов ошибок
            check(tag + f"ошибок страницы нет ({errs[:2]})", not errs)
            browser.close()


main()
shutil.rmtree(FIX, ignore_errors=True)
print(f"Итого: {passed} из {passed + failed} прошли" if failed == 0 else f"Итого: {passed} из {passed + failed} прошли (падений: {failed})")
sys.exit(1 if failed else 0)
