#!/usr/bin/env python3
"""Вьюер 3.88.0–3.90.0: «Сейчас» в «Долях и целях» считается от плана САЙТА (api/pv/plan), а не от плана в файле снапшота — настоящий Chromium.

Дефект 28.10: в снапшоте у бумаги `user_plan: KEEP`, на сайте уже `BALANCE`; таблица показывала план сайта, а «Сейчас» (движок читает снапшот)
— «держать (выше плана)»; срез то появлялся, то исчезал.

Контракты (фикстуры viewer-live, ответы api/pv/plan и api/pv/plan/set подменяются в браузере):
  1. План сайта 200 с SBER = BALANCE и долей 6 % (в снапшоте KEEP, 10,5 %) → после loadPlan снапшот в памяти несёт BALANCE, а в «Сделках» у T «Сейчас» = срез «↓ …» (не «держать»).
  2. Смена плана T встроенным списком на «держать» → POST api/pv/plan/set с одним изменением, и «Сейчас» у T сразу «держать …» без перезагрузки страницы.
  3. (3.89.0) План «ждать» → «стоит: … план «ждать»» словами без кодов; «продать» → «↓ продать всё · N лотов»; «План → К моему плану» на 1400 и 1280 без горизонтальной прокрутки.
  4. (3.90.0) Первая покупка: бумага плана BUY без позиции + гейт «держать» + живая котировка → «↑ купить … · первая покупка»; без решения → «стоит: новая, без разбора»» (R27: слова решений, без «гейт»);
     база «к цели IE» — колонка «Гейт» вместо «Мой план, %» и «Сумма, ₽».
  5. (3.95.0) Заморозка видна: сгиб «заморожено» в плитке «Сейчас по моему плану» (тикер и причина словами), клик — карточка со строкой «Для базы «Сейчас»»; «условие: разбор» для ждущих условий вида «разбор».
  6. (3.96.0) Отчёт с tickers [XXXXXX, имя фонда, ISIN фонда, FINAMAR, TMON]: три кнопки-чипа (имя и ISIN схлопнуты), тикеры фондов в тексте — ссылки, клик по TMON — карточка фонда.
  7. (3.97.0) Отчёты: порядок «дата → время записи файла → имя», время «чч:мм» в списке только при совпадении дня; parseListing несёт mtime;
     подвкладка «Отчёты · N» у акции и фонда (по тикеру, по имени фонда), клик — отчёт стопкой поверх карточки и «← К бумаге»;
     «История»: гейт автором и условие с отчётом на дату — ссылка (подсказка «ещё N»), автоматический гейт и дата без отчёта — нет.
  7б. (3.101.0) Одна карточка на оба счёта: сегмент «Основной счёт · ИИС-3» у бумаги на двух счетах (по умолчанию основной, с «ИИС-3» — ИИС-3), переключение меняет только показатели; план фонда правится ⇔ он есть на основном счёте.
  7в. (3.102.0) Ось дат графика XIRR на 390: ≤ 4 подписей «дд.мм», год в заголовке оси (два года — «мм.гг»), подписи не пересекаются и не обрезаны, запас справа ≥ 8 px;
     подвкладка «Отчёты»: вторая группа «Обзоры недели» (облигация в двух обзорах — по ISIN и тикеру), счётчик = отчёты + обзоры, клик — обзор поверх карточки и «← К бумаге», больше трёх — сгиб.
  7г. (3.103.0) Корзина облигации выводится: причина словами и источник («с Мосбиржи»), списка выбора нет; средняя цена в плитках по выбранному счёту
     («% номинала», ₽ за бумагу, «перенесена» на ИИС-3); источник «план» + выведенная иная — плашка «Сборка выводит…», «Принять выведенную» пишет type/subtype без manual;
     исключение требует причину и пишет type/subtype/manual/reason, «вернуть выведенную» — manual false; снапшот без новых полей — старый список, плитки нет;
     карточка «Загрузок» (pfBucketCard) — строки «было → стало», те же две кнопки, «без рейтинга» с фразой обзора.
  7д. (3.104.0) «Моя доходность» по выбранному счёту (by_account; < 30 дней — «% за N дней»; без by_account — подпись; iis_trades_stale), акция на двух счетах со строки «Акции»,
     «История» — ссылка только при смене, «Отчёты» без обзоров без markdown, рейтинг плана только при итоговой корзине КОРП.
  7е. (3.107.0) Облигация: ровно четыре плитки («Доходность к погашению», «Погашение», «При покупке», «Моя доходность») на обоих счетах, «При покупке» — locked_pct счёта (у линкера + реальная; нет — «—»),
     позиция счёта (стоимость, количество, доля со счётом, средняя цена, НКД, счёт) — первым блоком таблицы, общий блок «Бумага» не меняется; фонд на двух счетах — сегмент меняет позицию, результат и «Доходность» по by_account, план одинаков.
  7ж. (§10.6, 11.11) «Сейчас»: подпись неразворота («не разворачиваем до дд.мм (продано дд.мм) · снять: …», снимается правкой плана позже дня сделки), «откроется дд.мм» у недобранной заблокированной,
     пауза докупки от первой покупки после решения (buys_at), «не размещается сейчас» тремя строками, предупреждение «расчёт не сошёлся».
  8. Ошибок страницы нет.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_plan_now.py
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viewer_ds import DS_SET, attr, cond, dec, day  # noqa: E402  — фикстуры формата 2 (решения, условия, справочник)
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

ROW = """(t) => { const r = [...document.querySelectorAll('.rb-table tbody tr')].find(x => x.querySelector('.ui-sub')?.textContent.trim() === t || x.innerText.includes('\\n' + t + '\\n') || x.innerText.split(/\\s+/).includes(t));
  const c = r && r.querySelector('td[data-col=now]'); return c ? c.innerText.replace(/\\s+/g, ' ') : null; }"""


def main():
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            print(f"viewer_plan_now: пропуск — {str(e).splitlines()[0][:80]}")
            return
        ctx = browser.new_context(service_workers="block", viewport={"width": 1400, "height": 1000})
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "502" not in m.text and "404" not in m.text else None)
        site = {"plan": None, "hash": "h1", "sets": []}

        def api_plan(route):
            if site["plan"] is None:
                return route.fulfill(status=502, body="{}")
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
        pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
        pg.wait_for_function("() => state.data && state.data.portfolioLatest", timeout=20000)
        pg.wait_for_timeout(1500)
        t = "SBER"   # в фикстуре факт 10,9 %; план в снапшоте 10,5 % (держать), на сайте — 6 % и BALANCE → срез
        check("фикстура: SBER есть в снапшоте с планом KEEP", pg.evaluate("(t) => currentPort().ie_actual.per_ticker[t]?.user_plan", t) == "KEEP")
        pt = pg.evaluate("() => currentPort().ie_actual.per_ticker")
        stocks = {k: {"plan_pct": v.get("planned_share_pct"), "user_plan": v.get("user_plan"), "user_status": v.get("user_status"),
                      "note_ai": None, "note_ie": None, "ie_new_pct": None, "ie_old_pct": None} for k, v in pt.items()}
        check(f"снапшот: у {t} план «KEEP» (до плана сайта)", stocks[t]["user_plan"] == "KEEP")
        stocks[t]["user_plan"] = "BALANCE"; stocks[t]["plan_pct"] = 6.0
        site["plan"] = {"schema_version": 1, "stocks": stocks, "classes": [], "matrix": [], "bond_buckets": [], "bonds": {}, "funds": {}, "manual_positions": [],
                        "ie_model": {}, "updated_at": "2026-10-28T10:00:00Z"}
        pg.evaluate("async () => { await loadPlan(); }")
        pg.wait_for_timeout(300)
        check("после loadPlan снапшот в памяти несёт план сайта (BALANCE)", pg.evaluate("(t) => currentPort().ie_actual.per_ticker[t].user_plan", t) == "BALANCE")
        pg.evaluate("() => { state.ieView = 'work'; goToTab('ie-model'); renderTabContent(); }")
        pg.wait_for_selector(".rb-table tbody tr", timeout=10000)
        now1 = pg.evaluate(ROW, t)
        check(f"«Сделки»: у {t} «Сейчас» = срез от плана сайта ({now1!r})", bool(now1) and "↓" in now1 and "держать" not in now1)
        # 5.1.2: пометка под «Сейчас» — ПОСЛЕДНЕЕ СЛОВО модуля (б) (здесь — решение владельца «докупать» новее обзора), чьё и от какой даты;
        # план срезает, слово — «докупать» → «расходится с планом»
        own = dec(t, "ADD", day(0) + "T09:00:00+03:00", kind="owner", author="owner", note="решение владельца для теста пометки")
        pg.evaluate("(d) => { state.data.decisions = (state.data.decisions || []).concat(d); dsInvalidate(); renderTabContent(); }", own)
        pg.wait_for_selector(".rb-table tbody tr", timeout=10000)
        adv = pg.evaluate("""(t) => { const r = [...document.querySelectorAll('.rb-table tbody tr')].find(x => x.innerText.split(/\\s+/).includes(t));
          const n = r && r.querySelector('.rb-adv'); return n ? { t: n.innerText.trim(), warn: n.classList.contains('warn') } : null; }""", t)
        dd = day(0)[8:10] + "." + day(0)[5:7]
        check(f"«Сейчас» у {t}: «вы {dd}: докупать · расходится с планом →» по последнему слову ({adv})",
              bool(adv) and adv["t"].startswith(f"вы {dd}") and "докупать" in adv["t"] and "расходится с планом" in adv["t"] and adv["warn"])
        pg.evaluate("(id) => { state.data.decisions = state.data.decisions.filter(d => d.id !== id); dsInvalidate(); renderTabContent(); }", own["id"])
        pg.wait_for_selector(".rb-table tbody tr", timeout=10000)
        sel = pg.evaluate_handle("""(t) => { const r = [...document.querySelectorAll('.rb-table tbody tr')].find(x => x.innerText.split(/\\s+/).includes(t));
          return r.querySelector('td.rb-stcell button'); }""", t)
        sel.as_element().click()
        pg.wait_for_timeout(300)
        pg.evaluate("""() => { const o = [...document.querySelectorAll('.ui-select-pop:not([hidden]) button, .ui-select-pop:not([hidden]) [role=option]')].find(x => /^держать$/i.test(x.innerText.trim())); o && o.click(); }""")
        pg.wait_for_timeout(1500)
        check("смена плана списком → один POST set с user_plan KEEP",
              len(site["sets"]) == 1 and site["sets"][0]["changes"] == [{"path": f"stocks.{t}.user_plan", "value": "KEEP"}])
        now2 = pg.evaluate(ROW, t)
        check(f"после смены на «держать» «Сейчас» у {t} сразу без перезагрузки: не срез ({now2!r})", bool(now2) and "↓" not in now2 and "держать" in now2)
        # 3.89.0: слово плана «ждать» — причина словами, без кодов; «продать» — срез всей позиции
        under = [k for k, v in pt.items() if v.get("real_share_pct") is not None and v.get("planned_share_pct") is not None
                 and v["real_share_pct"] < v["planned_share_pct"] - 1 and k != t]
        sell = [k for k, v in pt.items() if v.get("real_share_pct") and k not in under and k != t][0]
        if under:
            site["plan"]["stocks"][under[0]]["user_plan"] = "WAIT"
        site["plan"]["stocks"][sell]["user_plan"] = "SELL"
        pg.evaluate("async () => { await loadPlan(); renderTabContent(); }")
        pg.wait_for_timeout(500)
        if under:
            w = pg.evaluate(ROW, under[0])
            check(f"«ждать» у {under[0]}: «стоит: … план «ждать»» словами ({w!r})", bool(w) and w.startswith("стоит:") and "план «ждать»" in w)
        hold_txt = pg.evaluate("() => [...document.querySelectorAll('.rb-now.hold')].map(x => x.innerText).join(' | ')")
        import re
        check(f"в «стоит:» нет кодов (WAIT/KEEP/gate:/review_/_condition/user_plan): {hold_txt[:120]!r}",
              not re.search(r"WAIT|KEEP|SELL|gate:|review_|_condition|user_plan|condition_hold|ipo_gate", hold_txt))
        sw = pg.evaluate(ROW, sell)
        check(f"«продать» у {sell}: «↓ продать всё · N лот…» ({sw!r})", bool(sw) and sw.startswith("↓ продать всё"))
        # 3.95.0: заморозка видна — сгиб «заморожено» в плитке «Сейчас по моему плану» (тикер, рубли, причина словами; клик — карточка), «Для базы» в карточке
        if under:
            u = under[0]
            pg.evaluate("() => { state.ieView = 'watch'; state.rebalMode = 'plan'; renderTabContent(); }")
            pg.wait_for_selector(".now-frozen", timeout=10000)
            fold = pg.evaluate("""() => { const d = document.querySelector('.now-frozen'); d.open = true;
              return { sum: d.querySelector('summary').innerText.replace(/\\s+/g, ' '), rows: [...d.querySelectorAll('.ui-row')].map(r => r.innerText.replace(/\\s+/g, ' ')) }; }""")
            check(f"плитка «Сейчас»: сгиб «заморожено: N бумаг · …» ({fold['sum']!r})", re.match(r"заморожено: \d+ бумаг", fold["sum"]) is not None)
            frow = [r for r in fold["rows"] if r.startswith(u + " ")]
            check(f"в раскрытом сгибе — {u} с причиной «план «ждать»» словами ({frow!r})", bool(frow) and "план «ждать»" in frow[0] and not re.search(r"user_plan|WAIT", frow[0]))
            pg.evaluate("(t) => { [...document.querySelectorAll('.now-frozen-row .ui-link')].find(b => b.innerText.trim() === t).click(); }", u)
            pg.wait_for_selector(".card-win", timeout=10000)
            pg.wait_for_timeout(300)
            ctf = pg.evaluate("() => document.querySelector('.card-win').innerText.replace(/\\s+/g, ' ')")
            check(f"клик по тикеру в сгибе открывает карточку {u} со строкой «Для базы «Сейчас»: заморожена — … план «ждать»» ({ctf[:60]!r} … {ctf[ctf.find("Для базы"):][:120]!r})",
                  "Для базы «Сейчас»: заморожена" in ctf and "план «ждать»" in ctf.split("Для базы «Сейчас»")[1][:160])
            pg.evaluate("() => { cardStack.length = 0; renderCards(); }")
            # «условие: разбор»: ждущее условие вида «разбор» — подстрока под «Сейчас», не блокировка
            pg.evaluate(DS_SET, {"defs": [cond("r1", u, "price_below", 3250, verdict_now=None), cond("r2", u, "date", "2026-11-30", on_verdict="HOLD", verdict_now=None),
                                          cond("b1", u, "price_below", 100, kind="trade", on_verdict="BUY", action="set_verdict", verdict_now=None)], "events": []})
            rc = pg.evaluate("(t) => ({ txt: reviewCondText(t), pure: reviewConditionsOf(t, true).length })", u)
            check(f"«условие: разбор до 30.11.2026 · разбор при цене ≤ 3 250 ₽» — дата первой, цена после, BUY-условие не входит ({rc['txt']!r})",
                  rc["txt"].replace("\u00a0", " ") == "условие: разбор до 30.11.2026 · разбор при цене ≤ 3 250 ₽" and rc["pure"] == 2)
            pg.evaluate(DS_SET, {"defs": [], "events": []})
            pg.evaluate("() => { state.ieView = 'work'; renderTabContent(); }")
            pg.wait_for_timeout(300)
        # 3.90.0: первая покупка — бумага плана BUY без позиции (UPRO: в фикстуре 0 %, плана нет); цена — живая котировка
        site["plan"]["stocks"]["UPRO"].update({"plan_pct": 2.0, "user_plan": "BUY"})
        pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(
            {"schema": "quotes@1", "fetched_at": "2026-10-28T10:00:00+03:00", "source": "moex_iss", "delayed_min": 15, "stale": False,
             "boards": {"TQBR": {"fetched_at": "2026-10-28T10:00:00+03:00", "stale": False}},
             "items": {"UPRO": {"price": 12.5, "price_kind": "last", "lot_size": 100, "board": "TQBR", "ts": "x", "prev_close": 12.4}}})))
        pg.evaluate(DS_SET, {"decisions": [dec("UPRO", "HOLD", day(-5))]})
        pg.evaluate("async () => { await loadPlan(); await loadLivePrices(); renderTabContent(); }")
        pg.wait_for_timeout(500)
        pg.evaluate("() => { state.ieView = 'work'; renderTabContent(); }")
        pg.wait_for_selector(".rb-table tbody tr", timeout=10000)
        fb = pg.evaluate(ROW, "UPRO")
        check(f"первая покупка: UPRO (план «докупать», гейт «держать», живая цена) → «↑ купить N лот… · первая покупка» ({fb!r})",
              bool(fb) and fb.startswith("↑ купить") and "первая покупка" in fb)
        px = pg.evaluate("""() => { const r = [...document.querySelectorAll('.rb-table tbody tr')].find(x => x.innerText.split(/\\s+/).includes('UPRO')); const c = r && r.querySelector('td[data-col=price]'); return c ? c.innerText.replace(/\\s+/g, ' ') : null; }""")
        check(f"первая покупка: цена кандидата — живая котировка без пометки «по цене IE» ({px!r})", bool(px) and "12,5" in px and "IE" not in px)
        pg.evaluate(DS_SET, {"decisions": []})
        pg.evaluate("() => renderTabContent()")
        pg.wait_for_timeout(300)
        nb = pg.evaluate(ROW, "UPRO")
        check(f"первая покупка без решения → «стоит: новая, без разбора» (R27) ({nb!r})", bool(nb) and nb.startswith("стоит: новая, без разбора") and "гейт" not in nb and "↑" not in nb)
        # 11.11: «без ИИ» блок гейта снимает решение владельца — в «Сейчас» у строки с причиной gate: ссылка «запиши решение →»
        # (открывает карточку и сразу раскрывает форму); при «с ИИ» ссылки нет; паузы и условия — без ссылки (решением не снять)
        check("«с ИИ»: у «стоит: новая, без разбора» ссылки «запиши решение →» нет",
              pg.evaluate("(t) => { const r = [...document.querySelectorAll('.rb-table tbody tr')].find(x => x.innerText.split(/\\s+/).includes(t)); return !!r && !r.querySelector('.rb-own-dec'); }", "UPRO"))
        pg.evaluate("() => { uiAiModeApply('off'); renderTabContent(); }")
        pg.wait_for_selector(".rb-table tbody tr .rb-own-dec", timeout=10000)
        ob = pg.evaluate("""(t) => { const r = [...document.querySelectorAll('.rb-table tbody tr')].find(x => x.innerText.split(/\\s+/).includes(t));
            const b = r && r.querySelector('.rb-own-dec'); return b ? { txt: b.innerText.trim(), cell: b.closest('.rb-now').innerText.replace(/\\s+/g, ' ').trim() } : null; }""", "UPRO")
        check(f"«без ИИ»: «стоит: новая, без разбора · запиши решение →» ({ob})", bool(ob) and ob["txt"] == "запиши решение →" and ob["cell"].startswith("стоит: новая, без разбора"))
        pg.evaluate("(t) => [...document.querySelectorAll('.rb-table tbody tr')].find(x => x.innerText.split(/\\s+/).includes(t)).querySelector('.rb-own-dec').click()", "UPRO")
        pg.wait_for_selector("#card-layer .card-owner-form:not([hidden]) textarea", timeout=5000)
        check("«без ИИ»: клик по «запиши решение →» открывает карточку бумаги с раскрытой формой решения",
              pg.evaluate("() => !!document.querySelector('#card-layer .card-owner-open[aria-expanded=true]')"))
        pg.evaluate("() => { cardStack.length = 0; renderCards(); uiAiModeApply('on'); renderTabContent(); }")
        pg.wait_for_selector(".rb-table tbody tr", timeout=10000)
        # 3.91.0: котировка без размера лота → только сумма, без «N лотов»
        pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(
            {"schema": "quotes@1", "fetched_at": "2026-10-28T10:00:00+03:00", "source": "moex_iss", "delayed_min": 15, "stale": False,
             "boards": {"TQBR": {"fetched_at": "2026-10-28T10:00:00+03:00", "stale": False}},
             "items": {"UPRO": {"price": 12.5, "price_kind": "last", "board": "TQBR", "ts": "x", "prev_close": 12.4}}})))
        pg.evaluate(DS_SET, {"decisions": [dec("UPRO", "HOLD", day(-5))]})
        pg.evaluate("async () => { state.ieView = 'work'; await loadLivePrices(); renderTabContent(); }")
        pg.wait_for_timeout(500)
        nl = pg.evaluate(ROW, "UPRO")
        check(f"первая покупка с неизвестным лотом — «купить ≈ X ₽ · первая покупка · лот уточни по котировке», без «лотов» ({nl!r})",
              bool(nl) and "первая покупка" in nl and "лот уточни по котировке" in nl and "лотов" not in nl and "лота" not in nl)
        pg.evaluate(DS_SET, {"decisions": []})
        pg.evaluate("() => renderTabContent()")
        # 3.91.0: кандидат кликабелен — открывается карточка акции с заголовком UPRO, строкой гейта и фразой для разбора
        pg.evaluate("() => { const r = [...document.querySelectorAll('.rb-table tbody tr')].find(x => x.innerText.split(/\\s+/).includes('UPRO')); r.click(); }")
        pg.wait_for_selector(".card-win", timeout=10000)
        ct = pg.evaluate("() => document.querySelector('.card-win').innerText.replace(/\\s+/g, ' ')")
        check(f"кандидат UPRO: клик по строке открывает карточку акции (заголовок UPRO, «нет в портфеле» (UPRO в моке только в плане, не в модели IE), «докупка закрыта: новая, без разбора», «Разбери UPRO») ({ct[:140]!r})",
              "UPRO" in ct[:200] and "нет в портфеле" in ct and "кандидат из модели IE" not in ct and "докупка закрыта: новая, без разбора" in ct and "Разбери UPRO" in ct)
        pg.evaluate("() => { cardStack.length = 0; renderCards(); }")
        # 3.91.0: плашка гейта у всех статусов под тикером в «Сделках»; разрешающий — tag soft
        pg.evaluate(DS_SET, {"decisions": [dec("UPRO", "HOLD", day(-5))]})
        pg.evaluate("() => renderTabContent()")
        pg.wait_for_timeout(300)
        pill = pg.evaluate("""() => { const r = [...document.querySelectorAll('.rb-table tbody tr')].find(x => x.innerText.split(/\\s+/).includes('UPRO')); const t = r && r.querySelector('.rb-gate .tag'); return t ? t.textContent + '|' + t.className : null; }""")
        check(f"плашка гейта «держать» (класс статуса gate-keep) под тикером разрешающего статуса ({pill!r})", pill == "держать|tag gate-keep")
        pg.evaluate(DS_SET, {"decisions": []})
        pg.evaluate("() => renderTabContent()")
        # база «к цели IE»: без «Сумма, ₽», с «Решение» (R27, бывш. «Гейт»); бумага без решения — «новая, без разбора»
        pg.evaluate("() => { state.ieView = 'watch'; state.rebalMode = 'ie'; renderTabContent(); }")
        pg.wait_for_selector(".rb-v-watch tbody tr", timeout=10000)
        heads = pg.evaluate("() => [...document.querySelectorAll('.rb-v-watch thead th')].map(x => x.textContent.trim())")
        check(f"«к цели IE»: колонки без «Сумма, ₽» и «План», с «Решение» и «Мой план, %» (3.119, R27) ({heads})", "Решение" in heads and "Гейт" not in heads and "Мой план, %" in heads and "Сумма, ₽" not in heads and "План" not in heads)
        gate_cell = pg.evaluate("""() => { const r = [...document.querySelectorAll('.rb-v-watch tbody tr')].find(x => x.innerText.split(/\\s+/).includes('UPRO')); const c = r && r.querySelector('td[data-col=gate]'); return c ? c.innerText.trim() : null; }""")
        check(f"«к цели IE»: UPRO без решения — «новая, без разбора» ({gate_cell!r}); плашки под тикером нет", gate_cell == "новая, без разбора"
              and pg.evaluate("() => !document.querySelector('.rb-v-watch .ui-name .rb-gate')"))
        # «План → К моему плану»: таблица без горизонтальной прокрутки на 1400 и 1280
        for w_px in (1400, 1280):
            pg.set_viewport_size({"width": w_px, "height": 1000})
            pg.evaluate("() => { state.ieView = 'watch'; state.rebalMode = 'plan'; renderTabContent(); }")
            pg.wait_for_selector(".rb-v-watch tbody tr", timeout=10000)
            pg.wait_for_timeout(400)
            sc, cl = pg.evaluate("() => { const w = document.querySelector('.rb-v-watch').closest('.ui-table-wrap'); return [w.scrollWidth, w.clientWidth]; }")
            check(f"«План → К моему плану» на {w_px} px без горизонтальной прокрутки ({sc}/{cl})", sc <= cl)
        # 3.92.0: подпись цели под «Сейчас»; окно Gate — все тикеры реестра ссылками, одно слово статуса везде
        pg.evaluate(DS_SET, {"decisions": [dec("UPRO", "HOLD", day(-5))]})
        pg.evaluate("() => { state.ieView = 'work'; state.rebalMode = 'plan'; goToTab('ie-model'); renderTabContent(); }")
        pg.wait_for_timeout(400)
        subs = pg.evaluate("() => [...document.querySelectorAll('.rb-goal')].map(x => x.textContent)")
        check(f"«Сейчас»: подпись «до X % книги после сделок · база …» под докупкой ({subs[:2]})", any(re.match(r"до [\d,]+ % книги после сделок · база [\d,]+ (млн|тыс) ₽$", x) for x in subs))
        pg.evaluate(DS_SET, {"decisions": [dec("UPRO", "HOLD", day(-5)), dec("ZZZZ", "TRIM", day(-4)), dec("QQQQ", "WATCH", day(-3))]})
        pg.evaluate("() => showGateLegendModal('')")
        pg.wait_for_timeout(300)
        gl = pg.evaluate("() => ({ rows: [...document.querySelectorAll('#modal-body .dec-row')].map(x => x.dataset.key), links: [...document.querySelectorAll('#modal-body .dec-row .gate-tk')].map(x => x.textContent), labels: [...document.querySelectorAll('#modal-body .gate-row b')].map(x => x.textContent) })")
        check(f"окно «Решения»: все бумаги с решением — строками и ссылками, в том числе вне портфеля/модели/плана ({gl['rows']} / {gl['links']})",
              sorted(gl['rows']) == ["QQQQ", "UPRO", "ZZZZ"] and sorted(gl['links']) == sorted(gl['rows']))
        same = pg.evaluate("() => Object.entries(GATE_PILL_WORD).every(([k, v]) => v === GATE_STATUS_META[k].label.toLowerCase()) && GATE_PILL_WORD.reviewed_reduce")
        check("слова статусов (R27): плашки = подписи статусов = слова решений, «сократить»/«докупать» одинаково в окне и плашке",
              same == "сократить" and "сократить" in gl["labels"] and "докупать" in gl["labels"])
        # фонд с решением: строка в «Решениях» есть, гейта у фонда нет (гейт только для акций, schema.md §3.5)
        pg.evaluate("""() => { const P = state.data.portfolioLatest?.parsed || state.data.portfolioAnchor?.parsed;
          P.holdings = (P.holdings || []).filter(h => h.ticker !== 'TMON').concat([{ ticker: 'TMON', name: 'Т-Капитал Денежный рынок', asset_type: 'fund', qty: 300, value_rub: 271000, account: 'main', current_price_source: 'moex' }]); }""")
        pg.evaluate(DS_SET, {"decisions": [dec("TMON", "HOLD", day(-5), kind="report", mode_codes=["5a"]), dec("QQQQ", "WATCH", day(-3))]})
        pg.evaluate("() => showGateLegendModal('')")
        pg.wait_for_timeout(300)
        g3 = pg.evaluate("() => ({ rows: [...document.querySelectorAll('#modal-body .dec-row')].map(x => [x.dataset.key, !!x.querySelector('.gate-badge')]) })")
        check(f"окно «Решения»: фонд TMON — строкой без значка гейта ({g3['rows']})", ["TMON", False] in g3["rows"])
        pg.evaluate("() => { showGateLegendModal(''); }")
        kind = pg.evaluate("""() => { const P = state.data.portfolioLatest?.parsed || state.data.portfolioAnchor?.parsed;
          const nk = heldNonStockKind('TMON'); const spans = _gateTickerLinks(['TMON', 'QQQQ']);
          const btn = spans.filter(x => x && x.querySelector).map(x => x.querySelector('button')).filter(Boolean);
          btn[0].click(); return { nk, n: btn.length, top: cardStack[cardStack.length - 1]?.list?.[0]?._kind }; }""")
        check(f"клик по TMON из ссылок открывает карточку ФОНДА, а не акции-кандидата ({kind})", kind["nk"] == "fund" and kind["top"] == "fund")
        pg.evaluate("() => { cardStack.length = 0; renderCards(); }")
        # проданная акция: была в прошлом снапшоте (ушла 23.07), в текущем её нет, плана «докупать» нет → гейт «продана» (модуль (б))
        pg.evaluate("""() => { const old = { name: 'portfolio-2026-07-20.json', date: '2026-07-20', parsed: { as_of_date: '2026-07-20', holdings: [{ ticker: 'QQQQ', asset_type: 'stock', qty: 10, value_rub: 1000 }] } };
          const mid = { name: 'portfolio-2026-07-23.json', date: '2026-07-23', parsed: { as_of_date: '2026-07-23', holdings: [] } };
          state.data.portfolioHistory = [...state.data.portfolioHistory, old, mid]; }""")
        pg.evaluate(DS_SET, {"decisions": [dec("QQQQ", "SELL", "2026-07-01")]})
        pg.evaluate("() => { const c = candidatePosition('QQQQ', null); openCard(c, [c]); }")
        pg.wait_for_timeout(300)
        pg.wait_for_selector(".card-win", timeout=10000)
        ct = pg.evaluate("() => document.querySelector('.card-win').innerText.replace(/\\s+/g, ' ')")
        check(f"карточка проданной бумаги вне модели IE: «нет в портфеле», «Продана 23.07», без слова «гейт» (дата — снапшот, где ушло количество), без «Разбери» ({ct[:200]!r})",
              "нет в портфеле" in ct and "Продана 23.07" in ct and "Гейт" not in ct and "кандидат из модели IE" not in ct and "Разбери QQQQ" not in ct)
        pg.evaluate("() => { state.data.portfolioHistory = state.data.portfolioHistory.filter(r => !['portfolio-2026-07-20.json', 'portfolio-2026-07-23.json'].includes(r.name)); dsInvalidate(); }")
        # 3.96.0: фонды кликабельны в отчётах — чипы в шапке (тикер, имя, ISIN фонда → один чип), клик по TMON открывает карточку фонда
        pg.evaluate("() => { cardStack.length = 0; renderCards(); closeModal(); }")
        pg.evaluate("""() => { const P = state.data.portfolioLatest?.parsed || state.data.portfolioAnchor?.parsed;
          P.holdings = (P.holdings || []).filter(h => !['TMON', 'XXXXXX', 'FINAMAR'].includes(h.ticker)).concat([
            { ticker: 'TMON', name: 'Т-Капитал Денежный рынок', asset_type: 'fund', qty: 300, value_rub: 271000, account: 'main', current_price_source: 'moex' },
            { ticker: 'XXXXXX', name: 'Рентал ПРО', isin: 'RU000A108157', asset_type: 'fund', qty: 300, value_rub: 271000, account: 'main', current_price_source: 'moex' },
            { ticker: 'FINAMAR', name: 'Финам «Алгоритм роста»', asset_type: 'fund', qty: 10, value_rub: 150000, account: 'main', current_price_source: 'cost_basis' }]);
          showAdvisorReportModal({ name: 'x.md', date: '2026-10-28', path: 'Portfolio/reports/x.md', parsed: { fm: { title: 'Отчёт', kind: 'single_analysis', tickers: ['XXXXXX', 'RENT', 'Рентал ПРО', 'RU000A108157', 'FINAMAR', 'TMON', 'Неведомый'] },
            rawText: '---\\ntitle: Отчёт\\n---\\n\\n# Отчёт\\n\\n## Контекст\\n\\nФонд XXXXXX держим, TMON — кеш, FINAMAR — по стоимости.\\n' } }); }""")
        pg.wait_for_timeout(500)
        chips = pg.evaluate("() => [...document.querySelectorAll('.rp-chips .rp-tic')].map(x => x.tagName + ':' + x.textContent)")
        check(f"отчёт: чипы фондов — XXXXXX, FINAMAR, TMON кнопками; имя, ISIN и псевдоним RENT фонда схлопнуты в чип тикера; неопознанное — серым ({chips})",
              chips == ["BUTTON:XXXXXX", "BUTTON:FINAMAR", "BUTTON:TMON", "SPAN:Неведомый"])
        links = pg.evaluate("() => [...document.querySelectorAll('.report-doc .rp-tk')].map(x => x.textContent)")
        check(f"отчёт: тикеры фондов в тексте — ссылки ({links})", sorted(links) == ["FINAMAR", "TMON", "XXXXXX"])
        pg.evaluate("() => { [...document.querySelectorAll('.rp-chips button.rp-tic')].find(x => x.textContent === 'TMON').click(); }")
        pg.wait_for_selector(".card-win", timeout=10000)
        check("клик по чипу TMON — карточка фонда поверх отчёта (отчёт остался)",
              pg.evaluate("() => cardStack[cardStack.length - 1]?.list?.[0]?._kind") == "fund" and pg.locator(".report-doc").count() == 1)
        # 3.100.0: «Цели по облигациям» — у групп корзин суммы корзин; «Что перевести» групп не берёт
        gr = pg.evaluate("""() => { const d = bucketPlanFactRows(); if (!d) return null;
          const card = buildBucketGoalsCard(); if (!card) return null;
          const sum = (keys, f) => keys.reduce((s, k) => s + (d.rowOf(k)[f] || 0), 0);
          const txt = (g) => { const r = [...card.querySelectorAll('.pf-row')].find(x => x.querySelector('.pf-grpn')?.textContent === g); return r ? r.innerText.replace(/\\s+/g, ' ') : null; };
          const vs = BUCKET_GROUPS[0][1];
          return { fx: txt('валютные'), plan: sum(vs, 'plan'), pct: sum(vs, 'aPct'), rub: sum(vs, 'aRub'), n: card.querySelectorAll('.pf-grprow').length,
                   grpEl: card.querySelectorAll('.pf-grprow.pick, .pf-grprow.rb-out').length,
                   mv: planMovesSides([{ group: 'валютные', name: 'g', plan: 99, aPct: 1, aRub: 1000 }], 1, 1000) }; }""")
        if gr is None:
            check("«Цели по облигациям»: карточка строится на тестовых данных", False)
        else:
            fm = lambda v: f"{v:.2f}".replace(".", ",")
            check(f"«Цели по облигациям»: у группы «валютные» план, факт % и ₽ — суммы USD+EUR+CNY ({gr})",
                  gr["n"] == 3 and gr["fx"] is not None and f"{round(gr['plan'])} %" in gr["fx"] and f"{fm(gr['pct'])} %" in gr["fx"] and gr["fx"].upper().startswith("ВАЛЮТНЫЕ")
                  and ("{:,}".format(round(gr["rub"])).replace(",", " ") in gr["fx"].replace("\u00a0", " ").replace("\u202f", " ")) and gr["grpEl"] == 0)
            check("«Что перевести»: строки-группы в расчёт не попадают (planMovesSides)", not gr["mv"]["sources"] and not gr["mv"]["receivers"])
        # 3.97.0: порядок отчётов по дате и времени записи; подвкладка «Отчёты»; ссылки из «Истории»
        pg.evaluate("() => { cardStack.length = 0; renderCards(); closeModal(); }")
        pl = pg.evaluate("""() => {
          const j = parseListing(JSON.stringify([{ name: 'a.md', size: 5, mod_time: '2026-10-28T13:29:00Z', is_dir: false }, { name: 'b.md', size: 7, is_dir: false }]), 'application/json', 'http://h/Portfolio/reports/');
          const h = parseListing('<a href="x.md">x.md</a>', 'text/html', 'http://h/Portfolio/reports/');
          return { j: j.map(x => [x.ver, x.mtime]), h: h.map(x => x.mtime), v1: verMtime('5|2026-10-28T13:29:00Z'), v2: verMtime('s:10:1793194140000000000') }; }""")
        check(f"parseListing: mtime из mod_time (epoch мс), без него и в автоиндексе — null; verMtime понимает «размер|mod_time» и «s:размер:ns» ({pl})",
              pl["j"][0][1] == 1793194140000 and pl["j"][1][1] is None and pl["h"] == [None] and pl["v1"] == 1793194140000 and pl["v2"] == 1793194140000)
        pg.evaluate("""() => {
          const P = state.data.portfolioLatest?.parsed || state.data.portfolioAnchor?.parsed;
          P.holdings = (P.holdings || []).filter(h => !['TMON', 'XXXXXX'].includes(h.ticker)).concat([
            { ticker: 'TMON', name: 'Т-Капитал Денежный рынок', asset_type: 'fund', qty: 300, value_rub: 271000, account: 'main', current_price_source: 'moex' },
            { ticker: 'XXXXXX', name: 'Рентал ПРО', asset_type: 'fund', qty: 300, value_rub: 271000, account: 'main', current_price_source: 'moex' }]);
          const at = (d, hh, mm) => new Date(d[0], d[1] - 1, d[2], hh, mm).getTime();
          const mk = (name, date, mtime, title, tickers, extra) => ({ type: 'advisorReport', name, path: 'Portfolio/reports/' + name, date, mtime,
            parsed: { fm: { title, kind: 'single_analysis', mode: '4 (single)', mode_codes: ['4a'], summary: 'Первая фраза итога отчёта. Вторая фраза не нужна.', tickers, ...extra }, rawText: '---\\ntitle: ' + title + '\\n---\\n\\n## Текст\\n\\nТело отчёта ' + title + '\\n' } });
          state.data.advisorReports = [
            mk('2026-10-28-b.md', '2026-10-28', at([2026, 10, 28], 9, 10), 'Утренний', ['SBER']),
            mk('2026-10-28-c.md', '2026-10-28', null, 'Без времени', ['sber']),
            mk('2026-10-14-e.md', '2026-10-14', at([2026, 10, 14], 8, 0), 'Автоматический день', ['SBER']),
            mk('2026-10-20-d.md', '2026-10-20', at([2026, 10, 28], 11, 0), 'Старый, перенесён', ['SBER']),
            mk('2026-10-28-a.md', '2026-10-28', at([2026, 10, 28], 16, 29), 'Вечерний', ['SBER', 'Т-Капитал Денежный рынок']),
          ].sort(cmpRecent);
          showReportsListModal(); }""")
        # решения SBER: 28.10 — слово владельца (время не задано — 00:00, ссылка на отчёт этой даты), 20.10 и 10.10 — разборы
        pg.evaluate(DS_SET, {"decisions": [dec("SBER", "HOLD", "2026-10-28T00:00:00+03:00", kind="owner", author="owner"),
                                           dec("SBER", "WATCH", "2026-10-20T00:00:00+03:00"), dec("SBER", "WATCH", "2026-10-10T00:00:00+03:00")]})
        pg.wait_for_timeout(400)
        lst = pg.evaluate("() => [...document.querySelectorAll('.report-item')].map(x => x.querySelector('.ri-title').textContent + '|' + x.querySelector('.ri-meta').textContent)")
        check(f"«Отчёты»: порядок — дата, внутри дня свежая запись выше, без mtime — ниже ({lst})",
              [x.split('|')[0] for x in lst] == ["Вечерний", "Утренний", "Без времени", "Старый, перенесён", "Автоматический день"])
        check(f"«Отчёты»: дата дд.мм.гггг, время «чч:мм» рядом, если день файла = дате отчёта; у перенесённого и без mtime — только дата ({lst})",
              lst[0].split('|')[1].startswith("28.10.2026 16:29 · ") and lst[1].split('|')[1].startswith("28.10.2026 09:10 · ")
              and lst[2].split('|')[1].startswith("28.10.2026 · ") and lst[3].split('|')[1].startswith("20.10.2026 · ") and lst[4].split('|')[1].startswith("14.10.2026 08:00 · "))
        pg.evaluate("() => closeModal()")
        pg.wait_for_timeout(600)   # окно списка уходит с анимацией; карточка, открытая до конца ухода, считалась бы «поверх документа»
        pg.evaluate("() => { const pbt = buildPositionByTicker(); openCard(pbt['SBER'], [pbt['SBER']]); }")
        pg.wait_for_selector(".card-win", timeout=10000)
        subs = pg.evaluate("() => [...document.querySelectorAll('.card-win .card-subs .ui-seg-btn')].map(x => x.textContent)")
        check(f"карточка акции: подвкладка «Отчёты · 5» (5 отчётов; 2 обзора недели с SBER без markdown-пары не показываются и не считаются, 3.104) после «История» ({subs})", subs[-2:] == ["История", "Отчёты · 5"])
        lk = pg.evaluate("() => document.querySelector('.card-reports-link')?.textContent || ''")
        check(f"«Главное»: строка-ссылка «разборов: 5 · последний 28.10 →» ({lk})", lk == "разборов: 5 · последний 28.10 →")
        pg.evaluate("() => document.querySelector('.card-reports-link .ui-link').click()")
        pg.wait_for_timeout(300)
        rows = pg.evaluate("() => [...document.querySelectorAll('.card-win .card-reps:not(.card-revs) .card-rep')].map(x => x.innerText.replace(/\\s+/g, ' '))")
        check(f"«Отчёты»: пять строк по cmpRecent; дата, время, заголовок, вид, режим словом (mode_codes), первая фраза ({rows[:2]})",
              len(rows) == 5 and rows[0].startswith("28.10.2026 16:29 Вечерний Разбор бумаги · разбор акции Первая фраза итога отчёта.") and "Вторая фраза" not in rows[0]
              and rows[2].startswith("28.10.2026 Без времени") and rows[3].startswith("20.10.2026 Старый, перенесён"))
        pg.evaluate("() => document.querySelectorAll('.card-win .card-rep')[0].click()")
        pg.wait_for_selector(".report-doc", timeout=5000)
        st1 = pg.evaluate("() => ({ cards: cardStack.length, ov: !document.getElementById('modal-overlay').hasAttribute('hidden'), back: [...document.querySelectorAll('#modal-body .report-head button')].map(x => x.textContent),"
                          " zOv: +getComputedStyle(document.getElementById('modal-overlay')).zIndex, zCard: +getComputedStyle(document.querySelector('.card-win').closest('[style*=\"z-index\"]') || document.querySelector('.card-win')).zIndex || 0 })")
        check(f"клик по отчёту — окно отчёта поверх карточки (карточка осталась), кнопка «← К бумаге» ({st1})",
              st1["cards"] == 1 and st1["ov"] and st1["back"] == ["← К бумаге"] and st1["zOv"] >= 300)
        pg.evaluate("() => [...document.querySelectorAll('#modal-body .report-head button')].find(x => x.textContent === '← К бумаге').click()")
        pg.wait_for_timeout(500)
        check("«← К бумаге» закрывает только отчёт: карточка на месте, подвкладка «Отчёты» сохранилась",
              pg.evaluate("() => document.getElementById('modal-overlay').hasAttribute('hidden') && cardStack.length === 1 && cardStack[0].sub === 'reports'"))
        pg.evaluate("() => document.querySelectorAll('.card-win .card-rep')[3].click()")
        pg.wait_for_selector(".report-doc", timeout=5000)
        pg.keyboard.press("Escape")
        lv = pg.evaluate("() => { const o = document.getElementById('modal-overlay'); const a = o.getAnimations().find(x => x.animationName === 'ui-modal-fade-out');"
                         " return { leave: o.classList.contains('leave'), hidden: o.hasAttribute('hidden'), fade: a ? a.currentTime : null, op: +getComputedStyle(o).opacity }; }")
        check(f"Esc в отчёте поверх карточки: окно уходит с анимацией — класс leave, hidden ещё нет, затухание идёт с начала (дефект 3.98: .enter и уход делили имя анимации, затемнение пропадало за кадр) ({lv})",
              lv["leave"] and not lv["hidden"] and lv["fade"] is not None and lv["fade"] < 170 and lv["op"] > 0.3)
        pg.wait_for_timeout(500)
        esc = pg.evaluate("() => ({ hidden: document.getElementById('modal-overlay').hasAttribute('hidden'), cards: cardStack.length })")
        check(f"Esc в отчёте поверх карточки закрывает отчёт, а не карточку ({esc})", esc["hidden"] and esc["cards"] == 1)
        pg.evaluate("() => { const b = [...document.querySelectorAll('.card-win .card-subs .ui-seg-btn')].find(x => x.textContent === 'История'); b.click(); }")
        pg.wait_for_timeout(400)
        tl = pg.evaluate("() => [...document.querySelectorAll('.card-win .tl')].map(x => [x.querySelector('.tl-d').firstChild.textContent, x.querySelector('.tl-k').textContent, x.classList.contains('pick'), x.getAttribute('title') || ''])")
        links = {(d, k): (p, t) for d, k, p, t in tl}
        check(f"«История»: решение 28.10 — ссылка с подсказкой «ещё 2 отчёта этой даты на подвкладке «Отчёты»»; 20.10 — ссылка без подсказки ({tl})",
              links.get(("28.10", "решение")) == (True, "ещё 2 отчёта этой даты на подвкладке «Отчёты»") and links.get(("20.10", "решение")) == (True, ""))
        check("«История»: решение без отчёта на дату (10.10) — не ссылка", links.get(("10.10", "решение"))[0] is False)
        check("«История»: в подвале журнала одна ui-note про ссылки", pg.locator(".card-win .card-tl-foot").count() == 1)
        pg.evaluate("() => document.querySelector('.card-win .tl.pick').click()")
        pg.wait_for_selector(".report-doc", timeout=5000)
        check("«История»: клик по связанной строке открывает отчёт этой даты (свежий по cmpRecent)",
              "Вечерний" in pg.evaluate("() => document.getElementById('modal-title').textContent"))
        pg.evaluate("() => { closeModal(); cardStack.length = 0; renderCards(); }")
        pg.wait_for_timeout(600)
        pg.evaluate("() => { const pbt = buildPositionByTicker(); openCard(pbt['TMON'], [pbt['TMON']]); }")
        pg.wait_for_selector(".card-win", timeout=10000)
        fs = pg.evaluate("() => [...document.querySelectorAll('.card-win .card-subs .ui-seg-btn')].map(x => x.textContent)")
        check(f"карточка фонда: отчёт с именем фонда в tickers найден, «Отчёты · 1» ({fs})", fs[-1] == "Отчёты · 1")
        pg.evaluate("() => { cardStack.length = 0; renderCards(); const pbt = buildPositionByTicker(); openCard(pbt['XXXXXX'], [pbt['XXXXXX']], { sub: 'reports' }); }")
        pg.wait_for_selector(".card-win", timeout=10000)
        emp = pg.evaluate("() => ({ t: document.querySelector('.card-win .card-empty')?.textContent || '', subs: [...document.querySelectorAll('.card-win .card-subs .ui-seg-btn')].map(x => x.textContent) })")
        check(f"бумага без отчётов: ярлык «Отчёты» без числа, текст «Отчётов по бумаге нет — «/ru-portfolio-advisor Разбери XXXXXX»» ({emp})",
              emp["subs"][-1] == "Отчёты" and emp["t"].startswith("Отчётов по бумаге нет — «/ru-portfolio-advisor Разбери XXXXXX»"))
        pg.evaluate("() => { cardStack.length = 0; renderCards(); }")
        # ===== 3.99.0: время событий «Истории», created_at в порядке отчётов, фонд только на ИИС-3 в отчёте =====
        pg.evaluate("""() => {
          const at = (d, hh, mm) => new Date(d[0], d[1] - 1, d[2], hh, mm).getTime();
          const mk = (name, date, mtime, title, tickers, extra) => ({ type: 'advisorReport', name, path: 'Portfolio/reports/' + name, date, mtime,
            parsed: { fm: { title, kind: 'single_analysis', mode: '4 (single)', mode_codes: ['4a'], summary: 'Фраза.', tickers, ...extra }, rawText: '---\\ntitle: ' + title + '\\n---\\n\\n## Текст\\n\\nТело ' + title + '\\n' } });
          state.data.advisorReports = [
            mk('2026-10-26-a.md', '2026-10-26', null, 'Утро с created_at', ['SBER'], { created_at: '2026-10-26T10:05' }),
            mk('2026-10-26-b.md', '2026-10-26', at([2026, 10, 26], 16, 0), 'Вечер по файлу', ['SBER']),
            mk('2026-10-26-c.md', '2026-10-26', at([2026, 10, 26], 12, 0), 'Полдень, но created_at позже', ['SBER'], { created_at: '2026-10-26T17:45' }),
          ].sort(cmpRecent);
          window.__ord = state.data.advisorReports.map(r => r.parsed.fm.title + ' ' + reportTimeLabel(r));
          }""")
        # решения SBER со временем записи; 26.10 и 08.10 — без времени (00:00: время берётся у отчёта той же даты);
        # условие c1: создано 08.10 без времени, версия 2 — 27.10 12:00
        pg.evaluate(DS_SET, {"decisions": [dec("SBER", "WATCH", "2026-10-27T09:00:00+03:00"), dec("SBER", "HOLD", "2026-10-27T15:14:00+03:00"),
                                           dec("SBER", "HOLD", "2026-10-26T00:00:00+03:00"), dec("SBER", "WATCH", "2026-10-08T00:00:00+03:00")],
                             "defs": [cond("c1", "SBER", "date", "2026-12-01", created="2026-10-08T00:00:00+03:00", created_by="owner"),
                                      cond("c1", "SBER", "date", "2026-12-01", version=2, created="2026-10-27T12:00:00+03:00", created_by="owner")], "events": []})
        pg.evaluate("() => { cardStack.length = 0; renderCards(); const pbt = buildPositionByTicker(); openCard(pbt['SBER'], [pbt['SBER']], { sub: 'hist' }); }")
        pg.wait_for_selector(".card-win .tl", timeout=10000)
        ordr = pg.evaluate("() => window.__ord")
        check(f"cmpRecent: внутри дня created_at идёт перед временем файла (17:45 → 16:00 → 10:05), метка времени — created_at, иначе файл ({ordr})",
              ordr == ["Полдень, но created_at позже 17:45", "Вечер по файлу 16:00", "Утро с created_at 10:05"])
        tl2 = pg.evaluate("() => [...document.querySelectorAll('.card-win .tl')].map(x => [x.querySelector('.tl-d').firstChild.textContent, x.querySelector('.tl-t')?.textContent || '', x.querySelector('.tl-k').textContent])")
        d27 = [r for r in tl2 if r[0] == "27.10"]
        check(f"«История»: два события одного дня со временем — по времени убыв., время мелко рядом с датой ({d27})",
              d27 == [["27.10", "15:14", "решение"], ["27.10", "12:00", "условие"], ["27.10", "09:00", "решение"]])
        d26 = [r for r in tl2 if r[0] == "26.10"]
        check(f"«История»: решение без времени берёт created_at связанного отчёта той же даты (самого свежего по cmpRecent — 17:45) ({d26})",
              d26 == [["26.10", "17:45", "решение"], ["26.10", "16:00", "разбор"], ["26.10", "10:05", "разбор"]])   # 3.120: разбор, на который ссылается гейт (17:45), слит с гейтом; остальные разборы дня — отдельными строками
        d08 = [r[2] for r in tl2 if r[0] == "08.10"]
        check(f"«История»: события одного дня без времени — от позднего этапа к раннему (условие, решение, обзор), лента идёт «новое сверху» ({d08})",
              d08[:2] == ["условие", "решение"] and d08[-1] == "обзор")
        # фонд только на ИИС-3 в отчёте — чип-кнопка → карточка фонда ИИС-3
        pg.evaluate("() => { closeModal(); cardStack.length = 0; renderCards(); }")
        pg.wait_for_timeout(500)
        pg.evaluate("""() => {
          const P = state.data.portfolioLatest?.parsed || state.data.portfolioAnchor?.parsed;
          P.holdings = (P.holdings || []).filter(h => h.ticker !== 'SBGB').concat([
            { ticker: 'SBGB', name: 'СберБанк - ОФЗ', asset_type: 'fund', qty: 1000, value_rub: 150000, account: 'iis_3', current_price_source: 'moex' }]);
          showAdvisorReportModal({ name: 'f.md', date: '2026-08-21', path: 'Portfolio/reports/f.md', parsed: { fm: { title: 'Разбор фондов портфеля', kind: 'single_analysis', tickers: ['SBGB'] },
            rawText: '---\\ntitle: Разбор фондов\\n---\\n\\n# Разбор\\n\\n## Контекст\\n\\nФонд SBGB лежит на ИИС-3.\\n' } }); }""")
        pg.wait_for_selector(".rp-chips", timeout=5000)
        sb = pg.evaluate("() => [...document.querySelectorAll('.rp-chips .rp-tic')].map(x => x.tagName + ':' + x.textContent)")
        check(f"отчёт: фонд только на ИИС-3 (SBGB) — чип-кнопка, не серый ({sb})", sb == ["BUTTON:SBGB"])
        pg.evaluate("() => [...document.querySelectorAll('.rp-chips button.rp-tic')].find(x => x.textContent === 'SBGB').click()")
        pg.wait_for_selector(".card-win", timeout=10000)
        sbc = pg.evaluate("() => ({ cards: cardStack.length, kind: cardStack[0] && cardKindOf(cardStack[0].list[cardStack[0].idx]), txt: document.querySelector('.card-win').innerText.replace(/\\s+/g, ' ') })")
        check(f"клик по SBGB — карточка фонда с пометкой ИИС-3 поверх отчёта ({sbc['kind']}, {sbc['txt'][:90]})",
              sbc["cards"] == 1 and sbc["kind"] == "fund" and "ИИС-3" in sbc["txt"])
        pg.evaluate("() => { closeModal(); cardStack.length = 0; renderCards(); }")
        # 3.101.0: одна карточка на оба счёта — сегмент счёта; план фонда правится ⇔ фонд есть на основном счёте
        pg.evaluate("() => { closeModal(); cardStack.length = 0; renderCards(); }")
        pg.wait_for_timeout(400)
        pg.evaluate("""() => {
          const P = state.data.portfolioLatest?.parsed || state.data.portfolioAnchor?.parsed;
          P.holdings = (P.holdings || []).filter(h => !['TMON', 'SBGB'].includes(h.ticker)).concat([
            { ticker: 'TMON', name: 'Т-Капитал Денежный рынок', asset_type: 'fund', qty: 300, value_rub: 271000, account: 'main', current_price_source: 'moex' },
            { ticker: 'TMON', name: 'Т-Капитал Денежный рынок', asset_type: 'fund', qty: 100, value_rub: 90000, account: 'iis_3', current_price_source: 'moex' },
            { ticker: 'SBGB', name: 'СберБанк - ОФЗ', asset_type: 'fund', qty: 1000, value_rub: 150000, account: 'iis_3', current_price_source: 'moex' }]);
          const bh = P.holdings.find(h => h.asset_type === 'bond' && h.account !== 'iis_3' && h.qty > 0);
          if (bh) { state.data.weeklyBondReviewCurrent = state.data.weeklyBondReviewCurrent || { parsed: {} };
            const W = state.data.weeklyBondReviewCurrent.parsed = state.data.weeklyBondReviewCurrent.parsed || {};
            W.per_bond = { ...(W.per_bond || {}), [bh.ticker]: { advisor_verdict: 'HOLD' } }; }
          window.__bondT = bh ? bh.ticker : null;
          if (bh) P.holdings.push({ ...bh, account: 'iis_3', qty: 5, value_rub: 5000, avg_cost_rub: null }); }""")
        card = """() => { const w = document.querySelector('.card-win'); return { seg: [...w.querySelectorAll('.card-acct .ui-seg-btn')].map(b => b.textContent + (b.getAttribute('aria-pressed') === 'true' ? '*' : '')),
            tiles: [...w.querySelectorAll('.card-tiles .ui-stat')].map(x => x.innerText.replace(/\\s+/g, ' ').toLowerCase()).join(' | '),
            dis: [...w.querySelectorAll('.card-col .ui-select-btn, .card-col input[type=checkbox]')].map(x => x.disabled), flds: w.querySelectorAll('.fd-pct, .fd-man').length,
            plan: !!w.querySelector('.card-col .ui-kicker') && [...w.querySelectorAll('.ui-kicker')].some(k => k.textContent === 'Мой план'),
            note: [...w.querySelectorAll('.ui-note')].some(n => n.textContent.includes('фонд только на ИИС-3 — вне балансировки, план не правится')),
            txt: w.innerText.replace(/\\s+/g, ' ') }; }"""
        pg.evaluate("() => { const e = buildPositionByTicker().TMON; openCard(e, [e]); }")
        pg.wait_for_selector(".card-win .card-acct", timeout=10000)
        a = pg.evaluate(card)
        check(f"3.101: фонд на обоих счетах — сегмент «Основной счёт · ИИС-3», по умолчанию основной, поля плана активны ({a['seg']}, {a['dis']})",
              a["seg"] == ["Основной счёт*", "ИИС-3"] and a["dis"] and not any(a["dis"]) and not a["note"] and "доля портфеля" in a["tiles"])
        pg.locator(".card-win .card-acct [data-v=iis_3]").click()
        pg.wait_for_timeout(300)
        b = pg.evaluate(card)
        check(f"3.101: переключение на ИИС-3 меняет плитки (доля счёта), блок «Мой план» и поля те же и активны ({b['seg']}, {b['tiles'][:80]})",
              b["seg"] == ["Основной счёт", "ИИС-3*"] and "доля счёта" in b["tiles"] and "доля портфеля" not in b["tiles"] and b["plan"] and not any(b["dis"]) and not b["note"]
              and b["flds"] == a["flds"] and ("90" in b["tiles"] or "90" in b["txt"]))
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(500)
        pg.evaluate("() => { cardStack.length = 0; renderCards(); }")
        pg.evaluate("() => { const e = buildPositionByTicker().TMON; openCard(e, [e], { account: 'iis_3' }); }")
        pg.wait_for_selector(".card-win .card-acct", timeout=10000)
        c = pg.evaluate(card)
        check(f"3.101: открытие с «ИИС-3» — выбран ИИС-3 ({c['seg']})", c["seg"] == ["Основной счёт", "ИИС-3*"] and "доля счёта" in c["tiles"])
        pg.evaluate("() => { cardStack.length = 0; renderCards(); const e = buildPositionByTicker().SBGB; openCard(e, [e], { account: 'iis_3' }); }")
        pg.wait_for_selector(".card-win", timeout=10000)
        pg.wait_for_timeout(300)
        d = pg.evaluate(card)
        check(f"3.101: фонд только на ИИС-3 — сегмента нет, тег ИИС-3, поля выключены, одна заметка ({d['seg']}, {d['dis']}, flds={d['flds']})",
              d["seg"] == [] and "ИИС-3" in d["txt"] and d["dis"] and all(d["dis"]) and d["note"] and d["flds"] == 0 and d["plan"])
        pg.evaluate("() => { cardStack.length = 0; renderCards(); const e = buildPositionByTicker().SBGB; openCard(e, [e]); }")
        pg.wait_for_selector(".card-win", timeout=10000)
        pg.wait_for_timeout(300)
        d2 = pg.evaluate(card)
        check("3.101: тот же фонд, открытый «с основного» (без параметра счёта) — те же выключенные поля: правило не зависит от точки входа", d2["dis"] and all(d2["dis"]) and d2["note"])
        # 3.122.1: у фонда только на ИИС-3 в плане осталась запись (перенос из Numbers) — строка «в плане осталось…» и «Очистить план фонда»
        pg.evaluate("() => { cardStack.length = 0; renderCards(); }")
        check("3.122.1: запись плана пуста — строки «в плане осталось» нет", pg.evaluate("() => { const e = buildPositionByTicker().SBGB; openCard(e, [e], { account: 'iis_3' }); return !document.querySelector('#fd-plan-left'); }"))
        site["plan"]["funds"]["SBGB"] = {"class": "Облигация", "currency": "RUB", "bucket": "ОФЗ/<10", "in_rebalance": None, "note": None}
        pg.evaluate("async () => { cardStack.length = 0; renderCards(); await loadPlan(); const e = buildPositionByTicker().SBGB; openCard(e, [e], { account: 'iis_3' }); }")
        pg.wait_for_selector(".card-win", timeout=10000)
        pg.wait_for_timeout(300)
        left = pg.evaluate("() => document.querySelector('#fd-plan-left')?.innerText.replace(/\\s+/g, ' ') || ''")
        check(f"3.122.1: SBGB только на ИИС-3 с корзиной в плане — «в плане осталось: … корзина ОФЗ/<10 — на ИИС-3 не используется» ({left!r})",
              "в плане осталось:" in left and "корзина ОФЗ/<10" in left and "на ИИС-3 не используется" in left and pg.locator("#fd-plan-clear").count() == 1)
        n0 = len(site["sets"])
        pg.locator("#fd-plan-clear").click()
        pg.wait_for_timeout(800)
        got = site["sets"][n0:]
        check(f"3.122.1: «Очистить план фонда» — один POST, поля записи в null, без in_rebalance (он и так пуст) ({got})",
              len(got) == 1 and sorted((c["path"], c["value"]) for c in got[0]["changes"]) == [("funds.SBGB.bucket", None), ("funds.SBGB.class", None), ("funds.SBGB.currency", None)])
        check("3.122.1: после очистки строки и кнопки нет (карточка перерисована)", pg.locator("#fd-plan-left").count() == 0 and pg.locator("#fd-plan-clear").count() == 0)
        check("3.122.1: запись плана на сайте очищена", all(site["plan"]["funds"]["SBGB"].get(f) is None for f in ("class", "currency", "bucket")))
        pg.evaluate("() => { cardStack.length = 0; renderCards(); }")
        if pg.evaluate("() => !!window.__bondT"):
            pg.evaluate("() => { cardStack.length = 0; renderCards(); const e = buildPositionByTicker()[window.__bondT]; openCard(e, [e]); }")
            pg.wait_for_selector(".card-win .card-acct", timeout=10000)
            e1 = pg.evaluate(card)
            dec1 = pg.evaluate("() => (document.querySelector('.card-win .card-decision')?.innerText || 'нет')")
            pg.locator(".card-win .card-acct [data-v=iis_3]").click()
            pg.wait_for_timeout(300)
            e2 = pg.evaluate(card)
            dec2 = pg.evaluate("() => (document.querySelector('.card-win .card-decision')?.innerText || 'нет')")
            check(f"3.101: облигация на обоих счетах — сегмент, обе плитки («Моя доходность», «При покупке») на обоих счетах, «Решение» (текст, количество основного счёта) то же ({e1['seg']}→{e2['seg']})",
                  e1["seg"] == ["Основной счёт*", "ИИС-3"] and e2["seg"] == ["Основной счёт", "ИИС-3*"] and "моя доходность" in e1["tiles"] and "моя доходность" in e2["tiles"] and "при покупке" in e1["tiles"] and "при покупке" in e2["tiles"] and "на иис" not in e2["tiles"] and dec1 == dec2)
            lines = pg.evaluate("() => [...document.querySelectorAll('.card-win .ui-kv')].map(k => k.innerText.replace(/\\s+/g, ' '))")
            check(f"3.101: строка «Счёт» облигации на ИИС-3 — «ИИС-3 · есть и на брокерском» ({[x for x in lines if x.startswith('Счёт')]})", any(x.startswith('Счёт') and 'ИИС-3 · есть и на брокерском' in x for x in lines))
            pg.evaluate("() => { cardStack.length = 0; renderCards(); const e = buildPositionByTicker()[window.__bondT]; openCard(e, [e]); }")
            pg.wait_for_selector(".card-win .card-acct", timeout=10000)
            lines = pg.evaluate("() => [...document.querySelectorAll('.card-win .ui-kv')].map(k => k.innerText.replace(/\\s+/g, ' '))")
            check(f"3.101: облигация на обоих счетах, открытая с «Облигаций» — «Счёт: брокерский · есть и на ИИС-3» ({[x for x in lines if x.startswith('Счёт')]})", any(x.startswith('Счёт') and 'брокерский · есть и на ИИС-3' in x for x in lines))
        else:
            check("3.101: в фикстуре нет облигации на основном счёте для проверки", False)
        pg.evaluate("() => { cardStack.length = 0; renderCards(); closeModal(); }")
        # 3.102.0 A: ось дат графика XIRR на телефоне — ≤ 4 подписей «дд.мм» без года, год в заголовке оси, запас справа
        pg.set_viewport_size({"width": 390, "height": 900})
        pg.wait_for_timeout(300)
        ax = """() => {
          const host = document.createElement('div'); host.id = 'axt'; host.style = 'position:fixed;left:0;top:0;width:370px;height:300px;background:#fff;z-index:9999';
          host.innerHTML = '<canvas id="cv-axt"></canvas>'; document.body.append(host);
          const mk = (ds) => ds.map((d, i) => ({ date: d, stock: 5 + i, bond: 3 + i / 2 }));
          const res = {};
          for (const [name, ds] of [['one', ['2026-04-07', '2026-05-12', '2026-06-20', '2026-07-30', '2026-08-25', '2026-09-30', '2026-10-28']],
                                    ['two', ['2025-11-03', '2025-12-15', '2026-01-20', '2026-02-27']]]) {
            host.innerHTML = '<canvas id="cv-axt"></canvas>';
            drawLineChart('cv-axt', mk(ds), [{ label: 'Акции', key: 'stock', color: '#c00' }, { label: 'Облигации', key: 'bond', color: '#00c' }], 'XIRR, % годовых');
            const ch = state.charts.get('cv-axt'); ch.update('none');
            const x = ch.scales.x, ctx = ch.ctx; ctx.save(); ctx.font = '12px sans-serif';
            const bx = x.ticks.map(t => { const w = ctx.measureText(t.label).width, c = x.getPixelForValue(t.value); return [c - w / 2, c + w / 2, t.label]; });
            ctx.restore();
            res[name] = { labels: x.ticks.map(t => t.label), title: x.options.title.display ? x.options.title.text : null, width: ch.width,
              overlap: bx.some((b, i) => i && b[0] < bx[i - 1][1] + 4), lastRight: Math.max(...bx.map(b => b[1])), areaRight: ch.chartArea.right,
              lastPt: x.getPixelForValue(x.max) };
            ch.destroy(); state.charts.delete('cv-axt');
          }
          host.remove(); return res; }"""
        axr = pg.evaluate(ax)
        o1, o2 = axr["one"], axr["two"]
        check(f"3.102: «Динамика» на 390 — не больше 4 подписей оси, формат «дд.мм» без года, год «2026» в заголовке оси ({o1['labels']}, {o1['title']})",
              0 < len(o1["labels"]) <= 4 and all(re.match(r"^\d\d\.\d\d$", t) for t in o1["labels"]) and o1["title"] == "2026")
        check(f"3.102: подписи оси не пересекаются, последняя не обрезана справа (края {round(o1['lastRight'])}/{o1['width']}), последняя точка не упирается в край (запас {round(o1['width'] - o1['areaRight'])} px)",
              not o1["overlap"] and o1["lastRight"] <= o1["width"] and o1["width"] - o1["areaRight"] >= 8)
        check(f"3.102: диапазон на два года — подписи «мм.гг», заголовка оси нет ({o2['labels']}, {o2['title']})",
              0 < len(o2["labels"]) <= 4 and all(re.match(r"^\d\d\.\d\d$", t) for t in o2["labels"]) and o2["title"] is None and not o2["overlap"])
        pg.set_viewport_size({"width": 1400, "height": 1000})
        # 3.102.0 B: подвкладка «Отчёты» — вторая группа «Обзоры недели» (облигация в двух обзорах: ключ — ISIN и тикер)
        pg.evaluate("""() => {
          const t = window.__bondT; const P = state.data.portfolioLatest?.parsed || state.data.portfolioAnchor?.parsed;
          const isin = (P.holdings || []).find(h => h.ticker === t)?.isin || null; window.__bondIsin = isin;
          const mkY = (date, per) => ({ type: 'weeklyBondReview', name: 'wb-' + date + '.yaml', date, parsed: { per_bond: per } });
          const mkM = (date) => ({ type: 'weeklyBondReviewMd', name: 'weekly-review-bond-' + date + '.md', date, parsed: { rawText: '# Обзор облигаций ' + date + '\\n\\nТекст обзора.' } });
          state.data.weeklyBondReviewCurrent = mkY('2026-10-28', { [t]: { advisor_verdict: 'HOLD', week_note: { what_happened: ['Купон выплачен без задержки. Вторая фраза.'] } } });
          state.data.weeklyBondReviewHistory = [mkY('2026-10-21', { [isin || t]: { advisor_verdict: 'HOLD_TO_MAT' } }), mkY('2026-10-14', { ZZZ: { advisor_verdict: 'HOLD' } })];
          state.data.weeklyBondReviewMdHistory = [mkM('2026-10-28'), mkM('2026-10-21'), mkM('2026-10-14')];
          state.data.weeklyBondReviewMdCurrent = state.data.weeklyBondReviewMdHistory[0];
          state.data.weeklyReviewCurrent = state.data.weeklyReviewCurrent || null;
          const e = buildPositionByTicker()[t]; cardStack.length = 0; renderCards(); openCard(e, [e], { sub: 'reports' }); }""")
        pg.wait_for_selector(".card-win .card-subs", timeout=10000)
        pg.wait_for_timeout(300)
        rv = pg.evaluate("""() => ({ subs: [...document.querySelectorAll('.card-win .card-subs .ui-seg-btn')].map(x => x.textContent),
          head: document.querySelector('.card-win .modal-section .ui-head')?.innerText.replace(/\\s+/g, ' ') || '',
          rows: [...document.querySelectorAll('.card-win .card-revs .card-rep')].map(x => x.innerText.replace(/\\s+/g, ' ')),
          fold: !!document.querySelector('.card-win .card-revs-fold') })""")
        check(f"3.102: подвкладка «Отчёты и обзоры · N» (есть обзоры недели) считает отчёты и обзоры; группа «Обзоры недели · 2» (обзоры без этой бумаги не в счёте); не свёрнута (≤ 3) ({rv['subs'][-1]}, {rv['head']})",
              rv["subs"][-1] == "Отчёты и обзоры · 2" and "Обзоры недели" in rv["head"] and rv["head"].endswith("2") and not rv["fold"])
        check(f"3.102: строка обзора — дата, «обзор облигаций за неделю», вердикт словами и первая фраза заметки недели ({rv['rows']})",
              len(rv["rows"]) == 2 and rv["rows"][0].startswith("28.10.2026") and "обзор облигаций за неделю" in rv["rows"][0] and "вердикт: Держать" in rv["rows"][0]
              and "Купон выплачен без задержки." in rv["rows"][0] and "Вторая фраза" not in rv["rows"][0] and rv["rows"][1].startswith("21.10.2026") and "Держать до погашения" in rv["rows"][1])
        pg.evaluate("() => document.querySelectorAll('.card-win .card-revs .card-rep')[1].click()")
        pg.wait_for_selector(".report-doc", timeout=5000)
        st2 = pg.evaluate("() => ({ cards: cardStack.length, title: document.getElementById('modal-title').textContent, back: [...document.querySelectorAll('#modal-body .report-head button')].map(x => x.textContent) })")
        check(f"3.102: клик по обзору — обзор поверх карточки, «← К бумаге» ({st2})", st2["cards"] == 1 and "2026-10-21" in st2["title"] and "← К бумаге" in st2["back"])
        pg.evaluate("() => [...document.querySelectorAll('#modal-body .report-head button')].find(x => x.textContent === '← К бумаге').click()")
        pg.wait_for_timeout(500)
        check("3.102: «← К бумаге» возвращает на подвкладку «Отчёты»", pg.evaluate("() => cardStack.length === 1 && cardStack[0].sub === 'reports'"))
        # больше трёх обзоров — группа свёрнута сгибом
        pg.evaluate("""() => { const t = window.__bondT; const mk = (date) => ({ type: 'weeklyBondReview', name: 'wb-' + date + '.yaml', date, parsed: { per_bond: { [t]: { advisor_verdict: 'HOLD' } } } });
          const mkM = (date) => ({ type: 'weeklyBondReviewMd', name: 'weekly-review-bond-' + date + '.md', date, parsed: { rawText: '# Обзор облигаций ' + date + '\\n\\nТекст обзора.' } });
          state.data.weeklyBondReviewHistory = [...state.data.weeklyBondReviewHistory, mk('2026-10-07'), mk('2026-09-30')];
          state.data.weeklyBondReviewMdHistory = [...state.data.weeklyBondReviewMdHistory, mkM('2026-10-07'), mkM('2026-09-30')]; renderCards(); }""")
        pg.wait_for_timeout(400)
        fl = pg.evaluate("() => ({ fold: !!document.querySelector('.card-win .card-revs-fold'), open: document.querySelector('.card-win .card-revs-fold')?.open, n: document.querySelector('.card-win .card-revs-fold summary')?.innerText.replace(/\\s+/g, ' ') })")
        check(f"3.102: обзоров больше трёх — группа свёрнута сгибом по умолчанию ({fl})", fl["fold"] and fl["open"] is False and "4" in fl["n"])
        # «История» берёт те же обзоры тем же помощником
        check("3.102: «История» и подвкладка «Отчёты» используют один помощник reviewsForTicker",
              pg.evaluate("() => reviewsForTicker(window.__bondT, { isin: window.__bondIsin }).filter(x => x.kind === 'bond').length") == 4)
        pg.evaluate("() => { cardStack.length = 0; renderCards(); closeModal(); }")

        # 3.103.0: корзина облигации выводится; исключение с причиной; принятие расхождения; средняя цена
        if pg.evaluate("() => !!window.__bondT"):
            pg.evaluate("""() => {
              const P = state.data.portfolioLatest?.parsed || state.data.portfolioAnchor?.parsed;
              const hs = P.holdings.filter(h => h.ticker === window.__bondT);
              window.__bondIsin = hs[0].isin;
              window.__bondHs = hs.map(h => ({ ...h }));
              Object.assign(hs.find(h => h.account !== 'iis_3'), { bucket_source: 'iss', bucket_reason: 'ОФЗ, до погашения 12,5 г.', plan_bucket_key: 'ОФЗ/>10', bucket_derived: 'ОФЗ/>10',
                avg_price_pct: 98.5, avg_cost_rub: 985, avg_cost_source: 'trades', avg_includes_accint: false });
              Object.assign(hs.find(h => h.account === 'iis_3'), { bucket_source: 'iss', bucket_reason: 'ОФЗ, до погашения 12,5 г.', plan_bucket_key: 'ОФЗ/>10', bucket_derived: 'ОФЗ/>10',
                avg_price_pct: 99.1, avg_cost_rub: 991, avg_cost_source: 'carried', avg_includes_accint: false });
            }""")
            isin = pg.evaluate("() => window.__bondIsin")
            site["plan"].setdefault("bonds", {})[isin] = {"name": "x", "type": "ОФЗ", "subtype": ">10", "rating": None, "action": None, "iis_qty": None}
            OPEN = "() => { cardStack.length = 0; renderCards(); const e = buildPositionByTicker()[window.__bondT]; openCard(e, [e]); }"
            KV = """() => { const w = document.querySelector('.card-win'); const kv = [...w.querySelectorAll('.ui-kv')].find(k => k.firstChild.textContent === 'Корзина');
              return { kv: kv ? kv.innerText.replace(/\\s+/g, ' ') : null, sel: kv ? !!kv.querySelector('.ui-select-btn') : null, warn: w.querySelector('.bx-warn')?.innerText.replace(/\\s+/g, ' ') || null,
                btns: [...w.querySelectorAll('.bx-edit, .bx-back')].map(b => b.textContent), form: !!w.querySelector('.bx-form'),
                tiles: [...w.querySelectorAll('.card-tiles .card-tile')].map(t => t.innerText.replace(/\\s+/g, ' ').toLowerCase()) }; }"""
            pg.evaluate(OPEN); pg.wait_for_selector(".card-win .card-acct", timeout=10000)
            k1 = pg.evaluate(KV)
            check(f"3.103: корзина «с Мосбиржи» — значение, причина словами, источник; списка выбора нет ({k1['kv']})",
                  k1["kv"] and "ОФЗ/>10" in k1["kv"] and "ОФЗ, до погашения 12,5 г." in k1["kv"] and "с Мосбиржи" in k1["kv"] and k1["sel"] is False and k1["warn"] is None and k1["btns"] == ["✎ исключение"])
            AVG = "() => [...document.querySelectorAll('.card-win .card-kv .ui-kv')].map(k => k.innerText.replace(/[\\s\\u00a0\\u202f]+/g, ' ')).filter(x => x.startsWith('Средняя цена'))"
            av = pg.evaluate(AVG)
            check(f"3.103: строка «Средняя цена» таблицы «Позиция» основного счёта — % номинала и ₽ за бумагу ({av})", len(av) == 1 and "98,50" in av[0] and "номинала" in av[0] and "985,00" in av[0] and "перенесена" not in av[0])
            check(f"3.107: плитки «Средняя цена» больше нет ({k1['tiles']})", not any(x.startswith("средняя цена") for x in k1["tiles"]))
            pg.locator(".card-win .card-acct [data-v=iis_3]").click(); pg.wait_for_timeout(300)
            av2 = pg.evaluate(AVG)
            check(f"3.103: на ИИС-3 строка берёт цену ИИС-3 и помечена «перенесена» ({av2})", len(av2) == 1 and "99,10" in av2[0] and "991,00" in av2[0] and "перенесена" in av2[0])
            # расхождение: источник «план», выведена иная
            pg.evaluate("""() => { const P = state.data.portfolioLatest?.parsed || state.data.portfolioAnchor?.parsed;
              P.holdings.filter(h => h.ticker === window.__bondT).forEach(h => Object.assign(h, { bucket_source: 'plan', plan_bucket_key: 'КОРП/AA+', bucket_derived: 'CNY', bucket_reason: 'валюта номинала CNY' })); }""")
            site["plan"]["bonds"][isin].update({"type": "КОРП", "subtype": "AA+"})
            n0 = len(site["sets"])
            pg.evaluate(OPEN); pg.wait_for_selector(".card-win .card-acct", timeout=10000)
            k2 = pg.evaluate(KV)
            check(f"3.103: источник «план», выведена иная — плашка «Сборка выводит «CNY», в плане «КОРП/AA+»», подпись источника ({k2['warn']}; {k2['kv']})",
                  k2["warn"] and "Сборка выводит «CNY», в плане «КОРП/AA+»" in k2["warn"] and "Принять выведенную" in k2["warn"] and "Оставить вручную" in k2["warn"] and "по плану (выведено иначе: CNY)" in k2["kv"])
            pg.locator(".card-win .bx-accept").click(); pg.wait_for_timeout(700)
            ch = site["sets"][-1]["changes"] if len(site["sets"]) > n0 else []
            check(f"3.103: «Принять выведенную» пишет type/subtype = выведенной, manual не ставится ({ch})",
                  [(c["path"].split(".")[-1], c["value"]) for c in ch] == [("type", "CNY"), ("subtype", None)])
            k3 = pg.evaluate(KV)
            check(f"3.103: после принятия плашки нет, корзина = CNY ({k3['warn']}; {k3['kv']})", k3["warn"] is None and k3["kv"].startswith("Корзина CNY"))
            # исключение: причина обязательна
            n1 = len(site["sets"])
            pg.locator(".card-win .bx-edit").click(); pg.wait_for_selector(".card-win .bx-form", timeout=3000)
            pg.locator(".card-win .bx-save").click(); pg.wait_for_timeout(400)
            check("3.103: исключение без причины не уходит на сервер, поле подсвечено", len(site["sets"]) == n1 and pg.evaluate("() => !!document.querySelector('.card-win .bx-why.bad')"))
            pg.locator(".card-win .bx-why").fill("кредитный риск эмитента выше рейтинга")
            pg.locator(".card-win .bx-save").click(); pg.wait_for_timeout(800)
            ch = site["sets"][-1]["changes"] if len(site["sets"]) > n1 else []
            check(f"3.103: исключение пишет type/subtype/manual/reason ({ch})",
                  [(c["path"].split(".")[-1], c["value"]) for c in ch] == [("type", "CNY"), ("subtype", None), ("manual", True), ("reason", "кредитный риск эмитента выше рейтинга")])
            k4 = pg.evaluate(KV)
            check(f"3.103: после исключения — «вручную: …», кнопка «вернуть выведенную» ({k4['kv']}, {k4['btns']})",
                  "вручную: кредитный риск эмитента выше рейтинга" in k4["kv"] and k4["btns"] == ["✎ исключение", "вернуть выведенную"] and k4["warn"] is None)
            n2 = len(site["sets"])
            pg.locator(".card-win .bx-back").click(); pg.wait_for_timeout(800)
            ch = site["sets"][-1]["changes"] if len(site["sets"]) > n2 else []
            check(f"3.103: «вернуть выведенную» — type/subtype = выведенной, manual false ({ch})",
                  [(c["path"].split(".")[-1], c["value"]) for c in ch] == [("type", "CNY"), ("subtype", None), ("manual", False), ("reason", None)])
            # «Оставить вручную» из плашки открывает то же исключение с причиной
            site["plan"]["bonds"][isin].update({"type": "КОРП", "subtype": "AA+", "manual": False, "reason": None})
            pg.evaluate("(isin) => Object.assign(state.plan.plan.bonds[isin], { type: 'КОРП', subtype: 'AA+', manual: false, reason: null })", isin)
            pg.evaluate(OPEN); pg.wait_for_selector(".card-win .bx-keep", timeout=10000)
            pg.locator(".card-win .bx-keep").click()
            check("3.103: «Оставить вручную» открывает форму исключения с полем причины", pg.evaluate("() => !!document.querySelector('.card-win .bx-form .bx-why')"))
            # рейтинг плана: список из лестницы, выбор A+ пишет bonds.<ISIN>.rating
            n4 = len(site["sets"])
            pg.evaluate(OPEN); pg.wait_for_selector(".card-win .card-acct", timeout=10000)
            rb = pg.evaluate("""() => { const kv = [...document.querySelectorAll('.card-win .ui-kv')].find(k => k.firstChild.textContent === 'Рейтинг в плане'); const b = kv?.querySelector('.ui-select-btn'); b && b.scrollIntoView({ block: 'center' }); b && b.click();
              return kv ? [...kv.querySelectorAll('.ui-opt')].map(x => x.textContent.replace('✓', '').trim()) : []; }""")
            check(f"3.103: список рейтинга плана — лестница и «нет рейтинга» ({rb[:3]}…{len(rb)})", len(rb) >= 17 and "нет рейтинга" in rb and "A+" in rb and "B-" in rb)
            pg.locator(".card-win .ui-kv:has-text('Рейтинг в плане') .ui-opt").filter(has_text=re.compile(r"^A\+$")).first.click(); pg.wait_for_timeout(800)
            ch = site["sets"][-1]["changes"] if len(site["sets"]) > n4 else []
            check(f"3.103: выбор A+ пишет bonds.<ISIN>.rating = «A+» ({ch})", [(c["path"].split(".")[-1], c["value"]) for c in ch] == [("rating", "A+")])
            rr = pg.evaluate("() => [...document.querySelectorAll('.card-win .ui-kv')].map(k => k.innerText.replace(/\\s+/g, ' ')).filter(x => x.startsWith('Рейтинг'))")
            check(f"3.103: строка «Рейтинг» показывает обзор и рейтинг плана ({rr})", any("обзор: " in x and "A+ (план)" in x for x in rr))
            # клик по строке вкладки «Облигации»: on_iis из обзора не решает — сегмент счёта, «Счёт: брокерский · есть и на ИИС-3», тега «ИИС-3» нет
            pg.evaluate("() => { closeModal(); cardStack.length = 0; renderCards(); const w = state.data.weeklyBondReviewCurrent?.parsed; if (w?.per_bond?.[window.__bondT]) w.per_bond[window.__bondT].on_iis = true; goToTab('bonds'); }")
            pg.wait_for_timeout(1500)
            clicked = pg.evaluate("""() => { const nm = buildPositionByTicker()[window.__bondT]?.name || window.__bondT;
              const tr = [...document.querySelectorAll('table tbody tr.pick, table tbody tr')].find(x => x.innerText.includes(window.__bondT) || x.innerText.includes(nm)); if (!tr) return false; tr.click(); return true; }""")
            pg.wait_for_selector(".card-win", timeout=8000); pg.wait_for_timeout(400)
            rw = pg.evaluate("""() => { const w = document.querySelector('.card-win'); return { clicked: true, seg: [...w.querySelectorAll('.card-acct .ui-seg-btn')].map(b => b.textContent), iisTag: [...w.querySelectorAll('.card-tags .tag')].some(t => /ИИС-3/.test(t.textContent)),
              acct: [...w.querySelectorAll('.ui-kv')].map(k => k.innerText.replace(/\\s+/g, ' ')).find(x => x.startsWith('Счёт')) }; }""")
            check(f"3.103: облигация на двух счетах, открытая КЛИКОМ ПО СТРОКЕ вкладки «Облигации» (обзор: on_iis) — сегмент счёта, «брокерский · есть и на ИИС-3», тега «ИИС-3» нет ({clicked}, {rw})",
                  clicked and rw["seg"] == ["Основной счёт", "ИИС-3"] and not rw["iisTag"] and rw["acct"] and "брокерский · есть и на ИИС-3" in rw["acct"])
            # ISIN облигации в тексте документа — кнопка-ссылка: в заголовке и в <code>; клик — карточка облигации поверх
            pg.evaluate("() => { closeModal(); cardStack.length = 0; renderCards(); }")
            pg.evaluate("""(isin) => { const box = document.createElement('div'); box.id = 'tst-doc'; box.style.cssText = 'position:fixed;left:0;top:0;width:900px;background:#fff;z-index:50;padding:12px';
              document.body.appendChild(box); renderReportDoc(box, '## Облигация (' + isin + ') — разбор\\n\\nТекст с кодом `' + isin + '` и обычным ' + isin + '.\\n'); }""", isin)
            dl = pg.evaluate("""(isin) => { const d = document.getElementById('tst-doc'); const h = d.querySelector('h2'); const b = h && h.querySelector('button.rp-tk');
              return { head: !!b, code: !!d.querySelector('code button.rp-tk'), n: d.querySelectorAll('button.rp-tk').length, hs: h ? getComputedStyle(h).fontSize : null, bs: b ? getComputedStyle(b).fontSize : null, htxt: h ? h.textContent : null }; }""", isin)
            check(f"3.103: ISIN облигации в заголовке, в <code> и в обычном тексте — кнопка .rp-tk; размер шрифта в заголовке сохранён ({dl})",
                  dl["head"] and dl["code"] and dl["n"] == 3 and dl["hs"] == dl["bs"] and isin in dl["htxt"])
            pg.evaluate("() => document.querySelector('#tst-doc h2 button.rp-tk').click()"); pg.wait_for_timeout(800)
            cc = pg.evaluate("() => ({ n: cardStack.length, t: document.querySelector('.card-win')?.innerText.slice(0, 80) })")
            check(f"3.103: клик по ISIN в заголовке открывает карточку облигации стопкой ({cc})", cc["n"] == 1 and isin in (cc["t"] or ""))
            pg.evaluate("() => { document.getElementById('tst-doc')?.remove(); cardStack.length = 0; renderCards(); closeModal(); }")
            # снапшот без новых полей — старый список, плитки нет
            pg.evaluate("""() => { const P = state.data.portfolioLatest?.parsed || state.data.portfolioAnchor?.parsed;
              P.holdings.filter(h => h.ticker === window.__bondT).forEach(h => { for (const f of ['bucket_source', 'bucket_reason', 'plan_bucket_key', 'bucket_derived', 'avg_price_pct', 'avg_cost_source', 'avg_includes_accint']) delete h[f]; }); }""")
            pg.evaluate(OPEN); pg.wait_for_selector(".card-win .card-acct", timeout=10000)
            k5 = pg.evaluate(KV)
            check(f"3.103: снапшот без новых полей — список выбора корзины, без плашки и «Средней цены» ({k5['kv']})",
                  k5["sel"] is True and k5["warn"] is None and not [x for x in k5["tiles"] if x.startswith("средняя цена")] and k5["btns"] == [])
            # «Загрузки»: карточка расхождений
            n3 = len(site["sets"])
            pg.evaluate("""(isin) => { const n = pfBucketCard({ bond_bucket_check: { changes: [{ isin, name: 'Тест-бонд', was: 'КОРП/AA+', now: 'CNY', reason: 'валюта номинала CNY' }],
              missing: [{ isin: 'XS0000000000', name: 'Без-рейтинга', code: 'bond_rating_missing', reason: 'нет рейтинга' }], derived: 3, attrs_missing: false } });
              n.id = 'tst-bk'; document.body.appendChild(n); }""", isin)
            t = pg.evaluate("() => document.getElementById('tst-bk').innerText.replace(/\\s+/g, ' ')")
            check(f"3.103: «Загрузки» — строка «было → стало · причина», две кнопки, «без рейтинга» с фразой обзора ({t})",
                  "Корзина облигации изменилась" in t and "КОРП/AA+ → CNY" in t and "валюта номинала CNY" in t and "Принять выведенную" in t and "Оставить вручную" in t
                  and "без рейтинга: Без-рейтинга" in t and "Обзор облигаций за неделю" in t)
            check("3.103: пустой bond_bucket_check — карточки нет", pg.evaluate("() => pfBucketCard({ bond_bucket_check: { changes: [], missing: [] } }) === null && pfBucketCard({}) === null"))
            pg.evaluate("() => document.querySelector('#tst-bk .pf-bk-accept').click()"); pg.wait_for_timeout(700)
            ch = site["sets"][-1]["changes"] if len(site["sets"]) > n3 else []
            check(f"3.103: «Принять выведенную» в «Загрузках» пишет type/subtype ({ch})", [(c["path"].split(".")[-1], c["value"]) for c in ch] == [("type", "CNY"), ("subtype", None)])
            pg.evaluate("() => { document.getElementById('tst-bk')?.remove(); cardStack.length = 0; renderCards(); closeModal(); }")
        else:
            check("3.103: в фикстуре нет облигации на основном счёте", False)
        # 3.104.0: «Моя доходность» по выбранному счёту; история обзоров — ссылка при смене; «Отчёты» без обзоров без markdown; рейтинг — только при корзине КОРП
        if pg.evaluate("() => !!window.__bondT"):
            pg.evaluate("""() => {
              const P = state.data.portfolioLatest?.parsed || state.data.portfolioAnchor?.parsed; const t = window.__bondT;
              P.flags = [];
              P.per_instrument_xirr = { [t]: { isin: window.__bondIsin, xirr: 1.11, pnl_rub: -1518, buy_total_rub: 230000, first_trade_date: '2026-10-05',
                by_account: { main: { xirr: 0.95, pnl_rub: 782, buy_total_rub: 130000, first_trade_date: '2026-10-05' },
                              iis_3: { xirr: -0.4, pnl_rub: -2300, buy_total_rub: 100000, first_trade_date: '2026-10-06' } } } };
            }""")
            OPEN4 = "() => { cardStack.length = 0; renderCards(); const e = buildPositionByTicker()[window.__bondT]; openCard(e, [e]); }"
            TL = """() => { const w = document.querySelector('.card-win'); return [...w.querySelectorAll('.card-tiles .ui-stat')].map(x => x.innerText.replace(/[\\s\\u00a0\\u202f]+/g, ' ').toLowerCase()); }"""
            pg.evaluate(OPEN4); pg.wait_for_selector(".card-win .card-acct", timeout=10000)
            tm = [x for x in pg.evaluate(TL) if x.startswith("моя доходность")]
            check(f"3.104: основной счёт, история 3 дня — крупно «% за N дней», годовых мелко, по счёту, по обоим счетам ({tm})",
                  len(tm) == 1 and "+0.6% за 3 дня" in tm[0] and "xirr годовых +95.0%" in tm[0] and "результат 782 ₽" in tm[0] and "по счёту" in tm[0]
                  and "по обоим счетам: -0.7% за 3 дня" in tm[0] and "1 518" in tm[0])
            pg.locator(".card-win .card-acct [data-v=iis_3]").click(); pg.wait_for_timeout(300)
            tl2 = pg.evaluate(TL)
            tm2 = [x for x in tl2 if x.startswith("моя доходность")]
            check(f"3.104: переключение на ИИС-3 меняет плитку (−2.3 % за 2 дня), рядом «При покупке» ({tl2})",
                  len(tm2) == 1 and "-2.3% за 2 дня" in tm2[0] and "результат" in tm2[0] and "2 300" in tm2[0] and "по счёту" in tm2[0]
                  and any(x.startswith("при покупке") for x in tl2))
            pg.evaluate("""() => { const x = currentPort().per_instrument_xirr[window.__bondT];
              const d = new Date(Date.parse(String(currentPort().as_of_date).slice(0, 10)) - 115 * 864e5).toISOString().slice(0, 10);
              x.first_trade_date = d; x.by_account.main.first_trade_date = d; }""")
            pg.evaluate(OPEN4); pg.wait_for_selector(".card-win .card-acct", timeout=10000)
            tmY = [x for x in pg.evaluate(TL) if x.startswith("моя доходность")]
            check(f"4.4.7: история 115 дней (короче года) — крупно «% за 115 дней», XIRR годовых подписью ({tmY})",
                  len(tmY) == 1 and "+0.6% за 115 дней" in tmY[0] and "xirr годовых +95.0%" in tmY[0])
            pg.evaluate("""() => { const x = currentPort().per_instrument_xirr[window.__bondT]; x.first_trade_date = '2025-01-01'; x.by_account.main.first_trade_date = '2025-01-01'; x.by_account.iis_3.first_trade_date = '2025-03-01'; }"""),
            pg.evaluate(OPEN4); pg.wait_for_selector(".card-win .card-acct", timeout=10000)
            tm3 = [x for x in pg.evaluate(TL) if x.startswith("моя доходность")]
            check(f"3.104/4.4.7: история длиннее года — XIRR годовых крупно, без «за N дней» ({tm3})",
                  len(tm3) == 1 and tm3[0].split("xirr")[0].count("+95.0%") == 1 and "за " not in tm3[0].split("xirr")[0] and "xirr, годовых" in tm3[0])
            pg.evaluate("() => { delete currentPort().per_instrument_xirr[window.__bondT].by_account; }")
            pg.evaluate(OPEN4); pg.wait_for_selector(".card-win .card-acct", timeout=10000)
            tm4 = [x for x in pg.evaluate(TL) if x.startswith("моя доходность")]
            check(f"3.104: у бумаги на двух счетах нет by_account — объединение с подписью про сборку с выгрузкой ИИС-3 ({tm4})",
                  len(tm4) == 1 and "+111.0%" in tm4[0] and "по обоим счетам — доходность по счёту появится после сборки с выгрузкой иис-3" in tm4[0])
            pg.evaluate("() => { currentPort().flags = [{ code: 'iis_trades_stale', message: 'Доходность по счетам не посчитана для 1 бумаг (' + window.__bondT + '): остаток ИИС-3 расходится.' }]; }")
            pg.evaluate(OPEN4); pg.wait_for_selector(".card-win .card-acct", timeout=10000)
            tm5 = [x for x in pg.evaluate(TL) if x.startswith("моя доходность")]
            check(f"3.104: бумага в iis_trades_stale — «сделки ИИС-3 устарели» ({tm5})", len(tm5) == 1 and "сделки иис-3 устарели" in tm5[0])
            # акция на двух счетах: строка вкладки «Акции» открывает карточку основного счёта с сегментом; доходность по счёту
            pg.evaluate("""() => { const P = state.data.portfolioLatest?.parsed || state.data.portfolioAnchor?.parsed;
              const h = P.holdings.find(x => x.ticker === 'SBER' && x.account !== 'iis_3'); window.__stockHs = h ? 1 : 0;
              if (h) P.holdings.push({ ...h, account: 'iis_3', qty: 10, value_rub: 3000, avg_cost_rub: null });
              P.per_instrument_xirr.SBER = { xirr: 0.5, pnl_rub: 400, buy_total_rub: 100000, first_trade_date: '2024-01-01',
                by_account: { main: { xirr: 0.5, pnl_rub: 700, buy_total_rub: 90000, first_trade_date: '2024-01-01' }, iis_3: { xirr: 0.2, pnl_rub: -300, buy_total_rub: 10000, first_trade_date: '2026-10-07' } } };
              closeModal(); cardStack.length = 0; renderCards(); goToTab('positions'); }""")
            pg.wait_for_timeout(1500)
            clicked = pg.evaluate("""() => { const tr = [...document.querySelectorAll('table tbody tr')].find(x => x.innerText.split(/\\s+/).includes('SBER')); if (!tr) return false; tr.click(); return true; }""")
            pg.wait_for_selector(".card-win", timeout=8000); pg.wait_for_timeout(500)
            st1 = pg.evaluate("""() => { const w = document.querySelector('.card-win'); return { seg: [...w.querySelectorAll('.card-acct .ui-seg-btn')].map(b => b.textContent + (b.getAttribute('aria-pressed') === 'true' ? '*' : '')),
              iisTag: [...w.querySelectorAll('.card-tags .tag')].some(t => /ИИС-3/.test(t.textContent)),
              tile: [...w.querySelectorAll('.card-tiles .ui-stat')].map(x => x.innerText.replace(/[\\s\\u00a0\\u202f]+/g, ' ').toLowerCase()).filter(x => x.startsWith('моя доходность')) }; }""")
            check(f"3.104: акция на двух счетах, открытая КЛИКОМ ПО СТРОКЕ вкладки «Акции» — сегмент, основной выбран, тега «ИИС-3» нет, доходность основного счёта ({clicked}, {st1})",
                  clicked and st1["seg"] == ["Основной счёт*", "ИИС-3"] and not st1["iisTag"] and len(st1["tile"]) == 1 and "+50.0%" in st1["tile"][0] and "по счёту" in st1["tile"][0]
                  and "по обоим счетам: +50.0%" in st1["tile"][0])
            pg.locator(".card-win .card-acct [data-v=iis_3]").click(); pg.wait_for_timeout(300)
            st2 = pg.evaluate("""() => [...document.querySelectorAll('.card-win .card-tiles .ui-stat')].map(x => x.innerText.replace(/[\\s\\u00a0\\u202f]+/g, ' ').toLowerCase()).filter(x => x.startsWith('моя доходность'))""")
            check(f"3.104: ИИС-3 той же акции — результат ИИС-3 ({st2})", len(st2) == 1 and "-3.0% за 1 день" in st2[0] and "по счёту" in st2[0])
            pg.evaluate("() => { cardStack.length = 0; renderCards(); closeModal(); }")
            # «История» облигации: ссылка у обзора только при смене вердикта/качества
            pg.evaluate("""() => { const t = window.__bondT;
              const mkY = (date, v) => ({ type: 'weeklyBondReview', name: 'wb-' + date + '.yaml', date, parsed: { per_bond: { [t]: { advisor_verdict: v, credit_quality: 'A' } } } });
              const mkM = (date) => ({ type: 'weeklyBondReviewMd', name: 'weekly-review-bond-' + date + '.md', date, parsed: { rawText: '# Обзор облигаций ' + date + '\\n\\nТекст.' } });
              state.data.weeklyBondReviewCurrent = mkY('2026-10-14', 'SELL'); state.data.weeklyBondReviewHistory = [mkY('2026-10-07', 'HOLD'), mkY('2026-09-30', 'HOLD')];
              state.data.weeklyBondReviewMdHistory = [mkM('2026-10-14'), mkM('2026-10-07')]; state.data.weeklyBondReviewMdCurrent = state.data.weeklyBondReviewMdHistory[0];
              cardStack.length = 0; renderCards(); const e = buildPositionByTicker()[t]; openCard(e, [e], { sub: 'hist' }); }""")
            pg.wait_for_selector(".card-win .card-tl", timeout=10000); pg.wait_for_timeout(300)
            hl = pg.evaluate("""() => [...document.querySelectorAll('.card-win .ui-row.tl')].filter(r => r.querySelector('.tl-k.rev')).map(r => [r.querySelector('.tl-d').textContent.slice(0, 5), r.classList.contains('tl-link')])""")
            check(f"3.104: «История» — ссылка только у обзора со сменой вердикта (14.10 HOLD→SELL), без смены (07.10) и первого (30.09) — без ссылки ({hl})",
                  hl == [["14.10", True], ["07.10", False], ["30.09", False]])
            ft = pg.evaluate("() => document.querySelector('.card-win .card-tl-foot')?.textContent || ''")
            check(f"3.104: подвал журнала — про смену вердикта/фундаментала ({ft})", "смене вердикта" in ft and "фундаментала" in ft)
            # «Отчёты»: обзор без markdown не показывается и не считается (30.09 — только YAML)
            pg.evaluate("""() => { cardStack.length = 0; renderCards(); const e = buildPositionByTicker()[window.__bondT]; openCard(e, [e], { sub: 'reports' }); }""")
            pg.wait_for_selector(".card-win .card-subs", timeout=10000); pg.wait_for_timeout(300)
            rv2 = pg.evaluate("""() => ({ last: [...document.querySelectorAll('.card-win .card-subs .ui-seg-btn')].map(x => x.textContent).pop(),
              rows: [...document.querySelectorAll('.card-win .card-revs .card-rep')].map(x => x.innerText.replace(/\\s+/g, ' ').slice(0, 10)) })""")
            check(f"3.104: «Отчёты» — обзор без markdown (30.09) скрыт и не в счётчике ({rv2})", rv2["last"] == "Отчёты и обзоры · 2" and rv2["rows"] == ["14.10.2026", "07.10.2026"])
            pg.evaluate("() => { cardStack.length = 0; renderCards(); closeModal(); }")
            # рейтинг плана — только при итоговой корзине КОРП: корпоративный эмитент с корзиной CNY поля не имеет
            isin4 = pg.evaluate("() => window.__bondIsin")
            RT = "() => [...document.querySelectorAll('.card-win .ui-kv')].filter(k => k.firstChild.textContent === 'Рейтинг в плане').length"
            def set_bucket(typ, sub, key, src):
                site["plan"].setdefault("bonds", {})[isin4] = {"name": "x", "type": typ, "subtype": sub, "rating": None, "action": None, "iis_qty": None, "manual": False, "reason": None}
                pg.evaluate("""([isin, typ, sub, key, src]) => { const P = state.data.portfolioLatest?.parsed || state.data.portfolioAnchor?.parsed;
                  P.holdings.filter(h => h.ticker === window.__bondT).forEach(h => Object.assign(h, { bucket_source: src, plan_bucket_key: key, bucket_derived: key, bucket_reason: 'тест' }));
                  state.plan.plan.bonds = state.plan.plan.bonds || {}; state.plan.plan.bonds[isin] = { name: 'x', type: typ, subtype: sub, rating: null, action: null, iis_qty: null, manual: false, reason: null }; }""", [isin4, typ, sub, key, src])
            set_bucket("CNY", None, "CNY", "iss")
            pg.evaluate(OPEN4); pg.wait_for_selector(".card-win .card-acct", timeout=10000)
            check("3.104: корпоративная облигация с корзиной CNY — поля «Рейтинг в плане» нет", pg.evaluate(RT) == 0)
            set_bucket("КОРП", "A", "КОРП/A", "rating")
            pg.evaluate(OPEN4); pg.wait_for_selector(".card-win .card-acct", timeout=10000)
            check("3.104: та же облигация в КОРП/A — поле «Рейтинг в плане» есть", pg.evaluate(RT) == 1)
            hint = pg.evaluate("() => [...document.querySelectorAll('.card-win .ui-note')].map(n => n.textContent).find(t => t.includes('источник корзины КОРП')) || ''")
            check(f"3.104: подсказка к рейтингу — обзор раньше плана ({hint})", "рейтинг из обзора облигаций → рейтинг плана" in hint)
            # принятие выведенной корзины CNY сразу убирает поле
            site["plan"]["bonds"][isin4].update({"type": "КОРП", "subtype": "AA+"})
            pg.evaluate("""([isin]) => { const P = state.data.portfolioLatest?.parsed || state.data.portfolioAnchor?.parsed;
              P.holdings.filter(h => h.ticker === window.__bondT).forEach(h => Object.assign(h, { bucket_source: 'plan', plan_bucket_key: 'КОРП/AA+', bucket_derived: 'CNY', bucket_reason: 'валюта номинала CNY' }));
              Object.assign(state.plan.plan.bonds[isin], { type: 'КОРП', subtype: 'AA+' }); }""", [isin4])
            pg.evaluate(OPEN4); pg.wait_for_selector(".card-win .bx-accept", timeout=10000)
            check("3.104: перед принятием корзина КОРП/AA+ — поле рейтинга есть", pg.evaluate(RT) == 1)
            pg.locator(".card-win .bx-accept").click(); pg.wait_for_timeout(900)
            check("3.104: «Принять выведенную» (CNY) сразу перерисовывает блок — поля рейтинга нет", pg.evaluate(RT) == 0)
            pg.evaluate("() => { cardStack.length = 0; renderCards(); closeModal(); }")
            # 3.107.0 A: облигация на двух счетах — ровно четыре одинаковые плитки на обоих; «При покупке» по счёту; позиция счёта — в таблице, общее — то же
            pg.evaluate("""() => { const P = state.data.portfolioLatest?.parsed || state.data.portfolioAnchor?.parsed; const t = window.__bondT;
              P.flags = [];
              const m = P.holdings.find(h => h.ticker === t && h.account !== 'iis_3'), i = P.holdings.find(h => h.ticker === t && h.account === 'iis_3');
              Object.assign(m, { locked_pct: 8.1, avg_price_pct: 98.5, avg_cost_rub: 985, avg_cost_source: 'trades', avg_includes_accint: false });
              Object.assign(i, { locked_pct: 12.19, locked_real_pct: 7.98, value_rub: 5000, qty: 5, avg_price_pct: 99.1, avg_cost_rub: 991, avg_cost_source: 'carried', avg_includes_accint: false });
              P.per_instrument_xirr = { [t]: { isin: window.__bondIsin, xirr: 1.11, pnl_rub: -1518, buy_total_rub: 230000, first_trade_date: '2025-01-01',
                by_account: { main: { xirr: 0.95, pnl_rub: 782, buy_total_rub: 130000, first_trade_date: '2025-01-01' }, iis_3: { xirr: -0.4, pnl_rub: -2300, buy_total_rub: 100000, first_trade_date: '2025-03-01' } } } }; }""")
            T7 = """() => { const w = document.querySelector('.card-win'); return { title: w.querySelector('.ui-modal-title')?.textContent || '',
              tiles: [...w.querySelectorAll('.card-tiles .ui-stat')].map(x => [x.querySelector('.ui-stat-k').textContent.toLowerCase(), x.innerText.replace(/[\\s\\u00a0\\u202f]+/g, ' ').toLowerCase()]),
              kv: Object.fromEntries([...w.querySelectorAll('.card-kv .ui-kv')].map(k => [k.firstChild.textContent, k.innerText.replace(/[\\s\\u00a0\\u202f]+/g, ' ').slice(k.firstChild.textContent.length + 1)])),
              kick: [...w.querySelectorAll('.card-kv .ui-kicker')].map(k => k.textContent) }; }"""
            pg.evaluate(OPEN4); pg.wait_for_selector(".card-win .card-acct", timeout=10000)
            b1 = pg.evaluate(T7)
            pg.locator(".card-win .card-acct [data-v=iis_3]").click(); pg.wait_for_timeout(300)
            b2 = pg.evaluate(T7)
            L = ["доходность к погашению", "погашение", "при покупке", "моя доходность"]
            check(f"3.107: на обоих счетах ровно четыре плитки в одном порядке ({[x[0] for x in b1['tiles']]} / {[x[0] for x in b2['tiles']]})",
                  [x[0] for x in b1["tiles"]] == L and [x[0] for x in b2["tiles"]] == L)
            lk1 = dict(b1["tiles"])["при покупке"]; lk2 = dict(b2["tiles"])["при покупке"]
            check(f"3.107: «При покупке» разная по счёту — 8,10 % основного, 12,19 % и реальная 7,98 % ИИС-3, подпись про цены моих покупок ({lk1} / {lk2})",
                  "8,10%" in lk1 and "годовых по ценам моих покупок" in lk1 and "реальн" not in lk1 and "12,19%" in lk2 and "реальн. 7,98%" in lk2 and "годовых по ценам моих покупок" in lk2)
            check("3.107: плиток «Цена», «Средняя цена», «Доля счёта», «Доля в облигациях» нет ни на одном счёте", not any(x[0] in ("цена", "средняя цена", "доля счёта", "доля в облигациях") for x in b1["tiles"] + b2["tiles"]))
            check(f"3.107: «Моя доходность» по счёту ({dict(b1['tiles'])['моя доходность'][:60]} / {dict(b2['tiles'])['моя доходность'][:60]})",
                  "+95.0%" in dict(b1["tiles"])["моя доходность"] and "по счёту" in dict(b1["tiles"])["моя доходность"] and "-40.0%" in dict(b2["tiles"])["моя доходность"])
            check(f"3.107: цена остаётся в заголовке карточки, % номинала ({b1['title'][:120]})", "% номинала" in b1["title"] and b1["title"] == b2["title"])
            check(f"3.107: таблица — первым блоком «Позиция» счёта, затем «Бумага» ({b1['kick']})", b1["kick"][:2] == ["Позиция", "Бумага"] and b2["kick"][:2] == ["Позиция", "Бумага"])
            check(f"3.107: «Доля» подписана счётом, «Средняя цена» меняется при переключении ({b1['kv'].get('Доля')} / {b2['kv'].get('Доля')}; {b1['kv'].get('Средняя цена')} / {b2['kv'].get('Средняя цена')})",
                  "облигаций основного счёта" in b1["kv"].get("Доля", "") and "счёта ИИС-3" in b2["kv"].get("Доля", "") and "облигаций" not in b2["kv"].get("Доля", "")
                  and "98,50 % номинала · 985,00 ₽" in b1["kv"].get("Средняя цена", "") and "99,10 % номинала · 991,00 ₽" in b2["kv"].get("Средняя цена", "") and "перенесена" in b2["kv"].get("Средняя цена", ""))
            check(f"3.107: «Стоимость», «Количество», «НКД», «Счёт» — позиция выбранного счёта и различаются ({b1['kv'].get('Количество')} / {b2['kv'].get('Количество')})",
                  b1["kv"].get("Количество") != b2["kv"].get("Количество") and b2["kv"].get("Количество", "").startswith("5 шт") and b1["kv"].get("Стоимость") != b2["kv"].get("Стоимость")
                  and b1["kv"].get("Счёт") != b2["kv"].get("Счёт") and ("НКД" in b1["kv"]) == ("НКД" in b2["kv"]))
            common = ["Тикер / ISIN", "Эмитент", "Тип", "Номинал", "Купон", "Доходность к погашению (YTM)", "Дюрация", "Рейтинг", "Кредитное качество"]
            check(f"3.107: общий блок «Бумага» при переключении не меняется ({[k for k in common if b1['kv'].get(k) != b2['kv'].get(k)]})",
                  all(b1["kv"].get(k) == b2["kv"].get(k) for k in common) and sum(1 for k in common if k in b1["kv"]) >= 4)
            pg.evaluate("() => { const P = state.data.portfolioLatest?.parsed || state.data.portfolioAnchor?.parsed; P.holdings.filter(h => h.ticker === window.__bondT).forEach(h => { delete h.locked_pct; delete h.locked_real_pct; }); }")
            pg.evaluate(OPEN4); pg.wait_for_selector(".card-win .card-acct", timeout=10000)
            n1 = dict(pg.evaluate(T7)["tiles"])["при покупке"]
            pg.locator(".card-win .card-acct [data-v=iis_3]").click(); pg.wait_for_timeout(300)
            n2 = dict(pg.evaluate(T7)["tiles"])["при покупке"]
            check(f"3.107: нет locked_pct — плитка «—» с подписью «нет данных — появится после сборки снимка» на обоих счетах ({n1} / {n2})", "—" in n1 and "нет данных — появится после сборки снимка" in n1 and "—" in n2 and "нет данных — появится после сборки снимка" in n2)
            pg.evaluate("() => { cardStack.length = 0; renderCards(); closeModal(); }")
            # 3.107.0 B: фонд на двух счетах — сегмент меняет позицию (стоимость, доля со счётом, моя доходность, результат), остальное то же
            pg.evaluate("""() => { const P = state.data.portfolioLatest?.parsed || state.data.portfolioAnchor?.parsed;
              P.holdings.filter(h => h.ticker === 'TMON').forEach(h => { h.current_price_source = 'moex_iss'; });
              const z = { sell_total_rub: 0, coupons_rub: 0, dividends_rub: 0 };
              P.per_instrument_xirr = { ...P.per_instrument_xirr, TMON: { xirr: 0.12, pnl_rub: 5000, buy_total_rub: 330000, first_trade_date: '2025-01-01', ...z,
                by_account: { main: { xirr: 0.10, pnl_rub: 4000, buy_total_rub: 250000, first_trade_date: '2025-01-01', market_value_rub: 271000, ...z },
                              iis_3: { xirr: 0.20, pnl_rub: 1000, buy_total_rub: 80000, first_trade_date: '2025-06-01', market_value_rub: 90000, ...z } } } }; }""")
            F7 = """() => { const w = document.querySelector('.card-win'); const sp = (x) => x.innerText.replace(/[\\s\\u00a0\\u202f]+/g, ' ');
              return { tiles: Object.fromEntries([...w.querySelectorAll('.card-tiles .ui-stat')].map(x => [x.querySelector('.ui-stat-k').textContent.toLowerCase(), sp(x).toLowerCase()])),
                pos: Object.fromEntries([...w.querySelectorAll('.card-col.side .ui-kv')].map(k => [k.firstChild.textContent, sp(k).slice(k.firstChild.textContent.length + 1)])),
                plan: sp(w.querySelector('.card-col:not(.side)')), subs: [...w.querySelectorAll('.card-subs .ui-seg-btn')].map(b => b.textContent) }; }"""
            pg.evaluate("() => { cardStack.length = 0; renderCards(); const e = buildPositionByTicker().TMON; openCard(e, [e]); }")
            pg.wait_for_selector(".card-win .card-acct", timeout=10000)
            f1 = pg.evaluate(F7)
            pg.locator(".card-win .card-acct [data-v=iis_3]").click(); pg.wait_for_timeout(300)
            f2 = pg.evaluate(F7)
            check(f"3.107: фонд — стоимость и доля меняются, подпись доли «без ИИС-3» / «ИИС-3» ({f1['tiles'].get('доля портфеля')} / {f2['tiles'].get('доля счёта')})",
                  "271 000" in f1["tiles"]["стоимость"] and "90 000" in f2["tiles"]["стоимость"] and "без иис-3" in f1["tiles"].get("доля портфеля", "")
                  and "доля счёта" in f2["tiles"] and "иис-3" in f2["tiles"]["доля счёта"] and "доля портфеля" not in f2["tiles"])
            check(f"3.107: фонд — «Моя доходность» по by_account ({f1['tiles']['моя доходность'][:50]} / {f2['tiles']['моя доходность'][:50]})",
                  "+10.0%" in f1["tiles"]["моя доходность"] and "+20.0%" in f2["tiles"]["моя доходность"])
            check(f"3.107: фонд — «Результат» в позиции по счёту, не по всей бумаге ({f1['pos'].get('Результат')} / {f2['pos'].get('Результат')})",
                  "4 000" in f1["pos"].get("Результат", "") and "1 000" in f2["pos"].get("Результат", ""))
            check(f"3.107: фонд — «Карта плана», блок «Мой план» и подвкладки одинаковы на обоих счетах ({f1['subs']})",
                  f1["tiles"]["карта плана"] == f2["tiles"]["карта плана"] and f1["plan"] == f2["plan"] and f1["subs"] == f2["subs"] and len(f1["subs"]) >= 2)
            pg.locator(".card-win .card-subs .ui-seg-btn").nth(1).click(); pg.wait_for_timeout(300)
            r1 = pg.evaluate("() => document.querySelector('.card-win .card-kv .ui-kicker')?.textContent + '|' + [...document.querySelectorAll('.card-win .card-kv .ui-kv')].map(k => k.innerText.replace(/\\s+/g, ' ')).join(';')")
            pg.locator(".card-win .card-acct [data-v=main]").click(); pg.wait_for_timeout(300)
            r2 = pg.evaluate("() => document.querySelector('.card-win .card-kv .ui-kicker')?.textContent + '|' + [...document.querySelectorAll('.card-win .card-kv .ui-kv')].map(k => k.innerText.replace(/\\s+/g, ' ')).join(';')")
            check(f"3.107: фонд — подвкладка «Доходность» меняется по счёту ({r1[:80]} / {r2[:80]})", r1 != r2 and "Доходность" in r1 and "80 000" in r1.replace("\u00a0", " ") and "250 000" in r2.replace("\u00a0", " "))
            pg.evaluate("() => { cardStack.length = 0; renderCards(); closeModal(); }")
        else:
            check("3.104: в фикстуре нет облигации на основном счёте", False)
        # §10.6 (11.11): подписи «Сейчас» — неразворот, «откроется ДД.ММ», каскад, плитка «не размещается сейчас» тремя строками.
        # Синтетика на одной недобранной акции: план «докупать», решений и условий нет; сделки и журнал плана подменяются во вьюере
        pg.evaluate("() => { cardStack.length = 0; renderCards(); closeModal(); }")
        pt9 = pg.evaluate("() => currentPort().ie_actual.per_ticker")
        held = set(pg.evaluate("() => currentPort().holdings.filter(h => h.asset_type === 'stock' && +h.qty > 0).map(h => h.ticker)"))
        cand = [k for k, v in pt9.items() if k in held and v.get("real_share_pct") and k != t and k in site["plan"]["stocks"] and not site["plan"]["stocks"][k].get("user_plan") in ("SELL",)]
        if not cand:
            check("§10.6: в фикстуре есть акция для синтетики", False)
        else:
            u9 = cand[-1]
            site["plan"]["stocks"][u9]["plan_pct"] = round(pt9[u9]["real_share_pct"] + 4, 2)   # недобор 4 п.п. > порога докупки
            site["plan"]["stocks"][u9]["user_plan"] = "BUY"
            pg.evaluate("async () => { await loadPlan(); }")
            SETUP = """(o) => { const at = (d) => d + 'T00:00:00+03:00', k = o.t;
              window.dsLastTradeAt = () => ({ trade: {}, sell: o.sell ? { [k]: at(o.sell) } : {}, buy: o.buys?.length ? { [k]: at(o.buys[o.buys.length - 1]) } : {},
                buys: o.buys?.length ? { [k]: o.buys.map(at) } : {} });
              state.planJournal = { entries: o.plan_at ? [{ ts: o.plan_at, who: 'site', path: 'stocks.' + k + '.user_plan', was: 'KEEP', now: 'BUY' }] : [] };
              state.data.decisions = o.decisions || []; state.data.conditions = null; dsInvalidate();
              state.ieView = 'work'; state.rebalMode = 'plan'; goToTab('ie-model'); renderTabContent();
              const a = nowAutoResult(); return { row: a.rows.find(r => r.ticker === k), cascade: a.cascade, gaps: [a.gap_gated_rub, a.gap_in_corridor_rub, a.gap_unallocated_rub, a.blocked_gap_rub] }; }"""
            sold = day(-5)
            r1 = pg.evaluate(SETUP, {"t": u9, "sell": sold})
            pg.wait_for_selector(".rb-table tbody tr", timeout=10000)
            until = day(9)
            dd = pg.evaluate("(d) => _ddmmDot(d)", until)
            sd = pg.evaluate("(d) => _ddmmDot(d)", sold)
            c1 = pg.evaluate(ROW, u9)
            check(f"неразворот: продажа 5 дней назад, недобор → строка no_reversal до {until} ({r1['row'].get('reason')!r}, {r1['row'].get('no_reversal')!r})",
                  r1["row"].get("reason") == f"no_reversal:{until}" and r1["row"]["no_reversal"]["trade"] == "sell" and r1["row"]["no_reversal"]["trade_at"] == sold)
            check(f"неразворот: «Сейчас» — «стоит: не разворачиваем до {dd} (продано {sd}) · снять: новое решение или правка плана» ({c1!r})",
                  bool(c1) and c1.startswith(f"стоит: не разворачиваем до {dd} (продано {sd}) · снять: новое решение или правка плана") and "no_reversal" not in c1)
            r2 = pg.evaluate(SETUP, {"t": u9, "sell": sold, "plan_at": day(-2) + "T12:00:00+03:00"})
            check(f"неразворот снят правкой плана после продажи (журнал: user_plan, {r2['row'].get('reason')!r})", not str(r2["row"].get("reason") or "").startswith("no_reversal"))
            r2b = pg.evaluate(SETUP, {"t": u9, "sell": sold, "plan_at": sold + "T12:00:00+03:00"})
            check("правка плана в день продажи неразворот не снимает (только позже дня сделки)", str(r2b["row"].get("reason") or "").startswith("no_reversal"))
            # «откроется»: решение BUY 19 дней назад, первая покупка 17 — пауза докупки кончается через 4 дня (< 7)
            r3 = pg.evaluate(SETUP, {"t": u9, "buys": [day(-17), day(-10)], "decisions": [dec(u9, "BUY", day(-19))]})
            pg.wait_for_selector(".rb-table tbody tr", timeout=10000)
            c3 = pg.evaluate(ROW, u9)
            op = pg.evaluate("(d) => _ddmmDot(d)", day(4))
            check(f"пауза докупки идёт от ПЕРВОЙ покупки после решения (buys_at: 17 и 10 дней назад → конец {day(4)}) ({r3['row'].get('reason')!r}, opens_on {r3['row'].get('opens_on')!r})",
                  r3["row"].get("reason") == f"add_cooldown:{day(4)}" and r3["row"].get("opens_on") == day(4))
            check(f"горизонт: у недобранной заблокированной — «· откроется {op}» ({c3!r})", bool(c3) and f"откроется {op}" in c3 and "если цена удержится" not in c3)
            r3b = pg.evaluate(SETUP, {"t": u9, "buys": [day(-25)], "decisions": [dec(u9, "BUY", day(-19))]})
            check(f"покупка ДО решения паузы не даёт ({r3b['row'].get('reason')!r})", not str(r3b["row"].get("reason") or "").startswith("add_cooldown"))
            # плитка: «не размещается сейчас» — три строки, сумма — полный разрыв; каскад сошёлся — предупреждения нет
            pg.evaluate("() => { state.ieView = 'watch'; state.rebalMode = 'plan'; renderTabContent(); }")
            pg.wait_for_selector(".now-gap", timeout=10000)
            gp = pg.evaluate("""() => { const d = document.querySelector('.now-gap'); d.open = true;
              return { sum: d.querySelector('summary').innerText.replace(/\\s+/g, ' '), rows: [...d.querySelectorAll('.ui-row')].map(r => r.innerText.replace(/\\s+/g, ' ')),
                       tile: document.querySelector('.sec-tiles')?.innerText.replace(/\\s+/g, ' ') || '' }; }""")
            check(f"плитка «Сейчас»: «не размещается сейчас» тремя строками (блокировки · коридор и «держать» · доля плана без бумаг) ({gp['rows']!r})",
                  len(gp["rows"]) == 3 and gp["rows"][0].startswith("заблокированные бумаги") and gp["rows"][1].startswith("коридор и «держать»") and gp["rows"][2].startswith("доля плана без бумаг")
                  and gp["sum"].startswith("не размещается сейчас:"))
            check("сумма трёх слагаемых = blocked_gap_rub (в пределах рубля)", abs(sum(r3["gaps"][:3]) - r3["gaps"][3]) < 1.5)
            check(f"каскад сошёлся: в плитке нет «расчёт не сошёлся» ({r3['cascade']!r})", r3["cascade"]["converged"] is True and "не сошёлся" not in gp["tile"])
            # непосчитанный каскад — предупреждение в плитке
            pg.evaluate("""() => { const f = RebalanceEngine.runAuto; window.__ra = f; RebalanceEngine.runAuto = function () { const r = f.apply(this, arguments); r.cascade = { iterations: 1, converged: false, added: [] }; return r; };
              renderTabContent(); }""")
            pg.wait_for_timeout(400)
            tile2 = pg.evaluate("() => document.querySelector('.sec-tiles')?.innerText.replace(/\\s+/g, ' ') || ''")
            check(f"каскад не сошёлся: плитка «Сейчас» — «расчёт не сошёлся — проверь вручную» ({tile2[-200:]!r})", "расчёт не сошёлся — проверь вручную" in tile2)
            pg.evaluate("() => { RebalanceEngine.runAuto = window.__ra; }")
        check(f"ошибок страницы нет {errs[:2]}", not errs)
        browser.close()


main()
srv.shutdown()
print(f"viewer_plan_now: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
