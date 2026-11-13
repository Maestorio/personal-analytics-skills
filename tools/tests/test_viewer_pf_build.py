#!/usr/bin/env python3
"""Вьюер: раздел «Загрузки» (до 3.81 «Проба сборки снапшота»; v3.43.0, API-1 PR-6) — прогон настоящим браузером.

Контракты (ответы /api/pf/* подменяются в браузере, hub-notify не нужен):
  1. Кнопка «Загрузки» в шапке открывает раздел; без сделок «Собрать» не уходит на сервер (баланс — нет) —
     «Нужны файлы: …». v3.44.0: файлы — плитки (`.pf-file`, `data-state`), вердикт с «Сохранить» сверху
     (`.pf-verdict`), сравнение плитками `.ui-stat` в `#pf-compare`, проверки — карточки `.pf-check` с меткой.
  2. Сборка: POST /api/pf/build несёт файлы base64 под ключами trades/balance и флаг кэш-расхождения;
     пока статус running — ждём; done → таблица «Собрано / Скилл» с датами, проверки, фолбэки.
  3. Решение cash_drift_changed → кнопка «Пересобрать, приняв кэш-расхождение» шлёт те же файлы
     с rebaseline_cash: true.
  4. «Сохранить как рабочий снапшот» (3.104) → POST /api/pf/save, кнопка гаснет, виден путь Portfolio/snapshots/portfolio-ДАТА.json
     (рабочая папка), слов «пробн» на странице нет; после сохранения вьюер перечитывает статус прогона и показывает строки
     «журнал решений: не обновлён: причина» (статус несёт decision_journal;
     ключа нет — строки нет); 3.105: ответ save приходит сразу, под кнопкой «обновляется…», опрос статуса каждые 3 с
     (мок: running, running, затем итог); 409 «уже есть снапшот с балансом» — понятный текст, кнопка снова доступна;
     блок-проверка → кнопка выключена сразу.
  4а. Вьюер 3.80.0: галочки «Принять текущее кэш-расхождение» в форме до запуска нет; после ЛЮБОГО прогона
     (не только при cash_fact_stale) — карточка «Кеш после сборки» с двумя полями (основной счёт `#pf-cashfact`,
     ИИС-3 `#pf-cashfact-iis`; type=number, inputmode=decimal), предзаполненными оценкой прогона (brief.auto.
     cash_main_rub / cash_iis_rub), и «Пересобрать с этим кешем»: некорректное — не уходит, пустое поле не
     передаётся, числа → POST с cash_fact и/или cash_fact_iis и теми же файлами, теги «кэш внесён» для обоих.
     Решение cash_fact_stale не даёт второго поля — его текст внутри этой же карточки. Первая сборка кеш не шлёт.
  4б. Страница Загрузки несёт две карточки загрузок (#pf-ie «Страница IE» и #pf-file «База сайта»); плитки
     #pf-compare одной высоты.
  4в. Вьюер 3.84.0: при brief.type_changes — карточка `.pf-types` «Тип бумаги изменился» перед «Кеш после сборки»
     (строки «имя · тикер», «был акция → стал фонд», подстрока «по бирже … · по сделкам …», причина словами,
     пояснение; types.online === false → «типы с биржи не запрашивались (сборка без сети)»); без type_changes нет.
  5. 390 px — не шире экрана; ошибок JS нет.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_pf_build.py
"""
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

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
    print("viewer_pf_build: пропуск — нет playwright")
    sys.exit(0)


def brief(blocked=False, decisions=()):
    return {"as_of": "2026-10-21", "blocked": blocked, "decisions": list(decisions),
            "attention_flags": [{"code": "bond_qty_vs_trades_mismatch", "message": "NorNik: 24 против 34"}],
            "checks": [{"id": "payout_exceeds_holding", "level": "warning", "message_ru": "DATA: выплата частями?"}]
            + ([{"id": "fx", "level": "block", "message_ru": "нет курса CNY"}] if blocked else []),
            "n_info": 3, "fallbacks": {"moex_down": False, "cbr_offline": True},
            "auto": {"as_of": "2026-10-21", "holdings": 64, "total_rub": 15200000, "cash_rub": 300000,
                     "cash_main_rub": 250000.5, "cash_iis_rub": 49999.5, "xirr_total": 0.041, "xirr_restricted": 0.083},
            "skill": {"as_of": "2026-10-16", "holdings": 63, "total_rub": 45590130, "cash_rub": 282455,
                      "xirr_total": 0.041, "xirr_restricted": 0.0827}}


def main():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "Portfolio/integrated-views").mkdir(parents=True)
    (tmp / "Portfolio/integrated-views/integrated-view-2026-10-01.md").write_text("---\n---\n", encoding="utf-8")
    os.symlink(REPO / "tools", tmp / "tools")
    up = tmp / "up"
    up.mkdir()
    (up / "trades_portfolio_707160-49.xlsx").write_bytes(b"PK\x03\x04trades")
    (up / "Общий баланс.numbers").write_bytes(b"PK\x03\x04balance")
    httpd = serve(directory=tmp)[0]   # _pages_stand: очередь 128, keep-alive
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    sent, polls = [], {"n": 0}
    scenario = {"brief": brief(decisions=[{"code": "cash_drift_changed", "message_ru": "Кэш-расхождение изменилось."}])}

    def api(route):
        req = route.request
        path = req.url.split("/api/pf/")[1]
        if path.startswith("build"):
            sent.append(json.loads(req.post_data))
            polls["n"] = 0
            return route.fulfill(status=202, content_type="application/json", body=json.dumps({"run": f"r{len(sent)}"}))
        if path.startswith("status"):
            if "run=" not in path:
                return route.fulfill(status=404, content_type="application/json", body='{"error": "сборок ещё не было"}')
            polls["n"] += 1
            run = path.split("run=")[1].split("&")[0]
            st = {"run": run, "state": "running", "started": "2026-10-21T22:10:00+03:00"}
            if polls["n"] >= 2:
                st.update(state="done", brief=scenario["brief"],
                          files=scenario.get("files") or {"trades": "trades_portfolio_707160-49.xlsx",
                                                          "balance": "Общий баланс.numbers"},
                          rebaseline_cash=sent[-1].get("rebaseline_cash"), cash_fact=sent[-1].get("cash_fact"), cash_fact_iis=sent[-1].get("cash_fact_iis"), sec=95)
                if scenario.get("saved"):
                    st.update(scenario["saved"])
                    scenario["post"]["n"] += 1
                    if scenario["post"]["n"] <= 2:
                        st.update(decision_journal={"state": "running"})
                    else:
                        st.update(decision_journal={"state": "error", "error": "нет выгрузки сделок прогона"})
                    scenario["post"]["seen"] = scenario["post"].get("seen", []) + [scenario["post"]["n"]]
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(st))
        if path.startswith("save"):
            sent.append({"save": json.loads(req.post_data)})
            if scenario.get("save409"):
                if scenario["save409"] == "cash_fact":
                    return route.fulfill(status=409, content_type="application/json", body=json.dumps({"reason": "cash_fact", "error":
                        "уже сохранён снапшот 2026-10-21 с внесённым кэшем — эта сборка без кэша его ухудшит: впиши кэш в «Кеш после сборки» и нажми «Пересобрать с этим кешем»"}))
                return route.fulfill(status=409, content_type="application/json", body=json.dumps({"reason": "balance", "error":
                    "уже сохранён снапшот 2026-10-21 с «Общим балансом» — сборка без баланса его ухудшит; собери с балансом"}))
            # шаги после сохранения идут в фоне: первые два опроса статуса — running, дальше итог
            scenario["post"] = {"n": 0}
            scenario["saved"] = {"saved": "Portfolio/snapshots/portfolio-2026-10-21.json"}
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps({"saved": "Portfolio/snapshots/portfolio-2026-10-21.json"}))
        return route.fulfill(status=404, body="{}")

    with sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception:  # noqa: BLE001
            print("viewer_pf_build: пропуск — нет chromium")
            return 0
        page = br.new_page(viewport={"width": 390, "height": 844})
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.route("**/api/pf/**", api)
        page.add_init_script("window.setTimeout = ((st) => (fn, ms, ...a) => st(fn, Math.min(ms || 0, 50), ...a))(window.setTimeout)")
        page.goto(base + "/tools/portfolio-integrated-viewer.html")
        page.wait_for_selector("#btn-pfbuild:not([hidden])", timeout=20000)
        page.click("#btn-pfbuild")
        page.wait_for_selector("#pf-go", timeout=5000)
        check("нет галочки кэш-расхождения до запуска", page.query_selector("#pf-rebaseline") is None
              and "Принять текущее кэш-расхождение" not in page.inner_text(".pf-box, #tab-content, body"))
        check("две карточки загрузок на странице", page.query_selector("#pf-ie") is not None and page.query_selector("#pf-file") is not None
              and "Импорт страницы IE" in page.inner_text("#pf-ie") and "Загрузить JSON" in page.inner_text("#pf-file"))
        page.click("#pf-go")
        check("без файлов — подсказка, на сервер не ушло",
              "Нужны файлы: Сделки IntelInvest." in page.inner_text("#pf-msg") and not sent)

        page.set_input_files("#pf-trades", str(up / "trades_portfolio_707160-49.xlsx"))
        page.set_input_files("#pf-balance", str(up / "Общий баланс.numbers"))
        page.click("#pf-go")
        page.wait_for_selector("#pf-result", timeout=10000)
        b0 = sent[0]
        check("файлы base64 и флаг", b0["files"]["trades"]["name"] == "trades_portfolio_707160-49.xlsx"
              and base64.b64decode(b0["files"]["balance"]["b64"]) == b"PK\x03\x04balance"
              and b0["rebaseline_cash"] is False and "iis_trades" not in b0["files"])
        res = page.inner_text("#pf-result")
        check("сравнение плитками с датами", page.query_selector("#pf-compare .ui-stat") is not None
              and "Собрано на 21.10.2026" in res and "от 16.10.2026" in res)
        check("плитки файлов: выбранный файл назван, тег варианта", "trades_portfolio_707160-49.xlsx" in page.inner_text(".pf-files")
              and page.get_attribute("label[for=pf-trades]", "data-state") == "set" and "с балансом" in res)
        check("вердикт и «Сохранить» сверху, проверки карточками с меткой",
              page.query_selector(".pf-verdict #pf-save") is not None
              and page.locator(".pf-check").count() == 3 and "Внимание" in page.text_content(".pf-checks")   # решение cash_drift_changed — первая строка «Нужно действие»
              and page.locator("#pf-checks-act > li").first.locator("#pf-rebase").count() == 1)
        check("числа сравнения: стоимость, XIRR двумя числами", "15 200 000" in res.replace("\xa0", " ").replace("\u202f", " ") and "4,10% · 8,30%" in res and "4,10% · 8,27%" in res)
        check("слова «скилл» в панели нет, заголовок «Что изменится, если сохранить»",
              "скилл" not in res.lower() and "Что изменится, если сохранить" in res and "Сравнение со" not in res)
        check("проверки, флаг и фолбэк", "DATA: выплата частями?" in res and "NorNik: 24 против 34" in res
              and "ЦБ офлайн" in res and "ещё 3 инфо" in res)

        page.click("#pf-rebase")
        page.wait_for_function("document.querySelector('#pf-result') && document.querySelector('#pf-result').innerText.indexOf('кэш-расхождение принято') >= 0", timeout=10000)
        check("пересборка с rebaseline_cash и теми же файлами",
              len(sent) == 2 and sent[1]["rebaseline_cash"] is True and sent[1]["files"] == sent[0]["files"])

        check("кнопка «Сохранить как рабочий снапшот», слов про пробную папку нет", page.inner_text("#pf-save") == "Сохранить как рабочий снапшот"
              and "пробн" not in page.inner_text("body").lower() and page.locator(".pf-save-l").count() == 0)
        scenario["save409"] = True
        page.click("#pf-save")
        page.wait_for_function("document.querySelector('.pf-saved').innerText.indexOf('Не сохранилось') >= 0", timeout=5000)
        t409 = page.inner_text(".pf-saved")
        check(f"409: понятный текст, кнопка снова доступна ({t409})",
              "уже сохранён снапшот 2026-10-21 с «Общим балансом»" in t409 and "собери с балансом" in t409 and not page.is_disabled("#pf-save"))
        scenario["save409"] = "cash_fact"
        page.evaluate("window.scrollTo(0, 0)")
        page.click("#pf-save")
        page.wait_for_function("document.querySelector('.pf-saved').innerText.indexOf('внесённым кэшем') >= 0", timeout=5000)
        page.wait_for_timeout(900)
        t409c = page.inner_text(".pf-saved")
        check(f"409 cash_fact: текст сервера как есть, про «Общий баланс» ни слова, прокрутка к «Кэш по счетам» ({t409c})",
              "Пересобрать с этим кешем" in t409c and "Общим балансом" not in t409c
              and page.evaluate("(() => { const r = document.querySelector('.pf-cash').getBoundingClientRect(); return r.top < innerHeight && r.bottom > 0; })()"))
        scenario["save409"] = False
        page.click("#pf-save")
        page.wait_for_function("document.getElementById('pf-save').textContent === 'Сохранено'", timeout=5000)
        page.wait_for_selector(".pf-save-l", timeout=5000)
        first = page.locator(".pf-save-l").all_inner_texts()
        check(f"сразу после ответа save — «обновляется…», не итог ({first})",
              first == ["журнал решений: обновляется…"] or "обновляется…" in " ".join(first))
        page.wait_for_function("document.querySelectorAll('.pf-save-l.bad').length === 1", timeout=10000)
        check("сохранение: путь рабочей папки, кнопка погасла",
              "Portfolio/snapshots/portfolio-2026-10-21.json" in page.inner_text("#pf-result") and "snapshots/auto" not in page.inner_text(".pf-saved")
              and page.is_disabled("#pf-save") and sent[-1] == {"save": {"run": "r2"}})
        lines = page.locator(".pf-save-l").all_inner_texts()
        check(f"после сохранения — статус перечитан: журнал решений не обновлён с причиной ({lines})",
              lines == ["журнал решений: не обновлён: нет выгрузки сделок прогона"]
              and page.locator(".pf-save-l.bad").count() == 1)
        check("не шире экрана", page.evaluate("document.documentElement.scrollWidth") <= 390)

        scenario["saved"] = None
        scenario["brief"] = brief(blocked=True)
        page.click("#pf-go")
        page.wait_for_function("document.querySelector('#pf-result') && document.querySelector('#pf-result').innerText.indexOf('блок-проверки') >= 0", timeout=10000)
        check("блок → сохранить нельзя", page.is_disabled("#pf-save") and "нет курса CNY" in page.inner_text("#pf-result"))

        # тексты проверок сборки 11.11: дубли выплат — таблица, инфо о правках задним числом — в «К сведению»
        pay = {"id": "payout_exceeds_holding", "level": "warning",
               "message_ru": "Похоже на дубли выплат: ...\nNVTK · 09.11\nЧто сделать: в IntelInvest оставить одну строку на дату, лишнюю удалить и пересобрать. Если брокер платил частями — сумма строк должна равняться пришедшему на счёт.",
               "details": {"items": [{"ticker": "NVTK", "name": "Новатэк", "date": "2026-11-09", "operation": "Дивиденд", "held": 82,
                                      "paid_qty": 164, "currency": "RUB", "kind": "differing",
                                      "rows": [{"amount": 2533.0, "qty": 82, "new": False}, {"amount": 2911.0, "qty": 82, "new": True}]}]}}
        money = {"id": "money_rows_changed_before_prev", "level": "info",
                 "message_ru": "В истории денежных операций (до прошлой сборки, 10.11) появились или исчезли строки:\nдобавлено: доход — 1 стр. на 1 850 ₽\nКэш после правок сходится с вашим фактом так же, как раньше: расхождение +369 418,19 ₽ (было +369 418,19 ₽) — ничего не сломалось."}
        scenario["brief"] = brief()
        scenario["brief"]["checks"] = [pay]
        scenario["brief"]["info_checks"] = [money]
        page.click("#pf-go")
        page.wait_for_selector(".pf-payout-tbl", timeout=10000)
        tbl = page.inner_text(".pf-payout-tbl")
        check("дубли выплат: таблица с бумагой, датой, на руках, выплачено, строками и пометкой «новая»",
              "NVTK" in tbl and "Новатэк" in tbl and "09.11" in tbl and "82 шт" in tbl and "164 шт" in tbl
              and "2 533" in tbl.replace("\xa0", " ") and "2 911" in tbl.replace("\xa0", " ")
              and page.locator(".pf-payout-tbl .pf-new").count() == 1
              and "новая с прошлой сборки" in page.inner_text(".pf-payout-tbl .pf-new"))
        act = page.inner_text("#pf-checks-act")
        check("дубли выплат: заголовок, одна фраза и «Что сделать» под таблицей",
              "Похоже на дубли выплат" in act and "обычно повторный импорт" in act and "Что сделать: в IntelInvest" in act
              and "частями, строки с разными суммами" in act)
        inf = page.inner_text("#pf-checks-info")
        check("инфо о правках до прошлой сборки — в «К сведению» построчно, с ответом про кэш",
              "В истории денежных операций" in inf and "добавлено: доход" in inf and "ничего не сломалось" in inf)
        check("таблица не шире экрана", page.evaluate("document.documentElement.scrollWidth") <= 390)

        # «Кеш после сборки»: карточка после любого прогона, два поля, предзаполнены оценкой прогона
        scenario["brief"] = brief(decisions=[{"code": "cash_fact_stale", "message_ru": "Кэш — оценка, опора устарела."}])
        n0 = len(sent)
        page.click("#pf-go")
        page.wait_for_selector(".pf-cash .ui-alert", timeout=10000)
        check("поля: два number, предзаполнены оценкой, кнопка",
              page.get_attribute("#pf-cashfact", "type") == "number" and page.get_attribute("#pf-cashfact-iis", "type") == "number"
              and page.get_attribute("#pf-cashfact", "inputmode") == "decimal"
              and page.input_value("#pf-cashfact") == "250000.5" and page.input_value("#pf-cashfact-iis") == "49999.5"
              and "Кэш по счетам" in page.text_content("#pf-result")
              and page.inner_text("#pf-cashfact-go") == "Пересобрать с этим кешем")
        check("cash_fact_stale: одно поле основного счёта, текст решения внутри карточки",
              page.locator("#pf-cashfact").count() == 1 and "Кэш — оценка, опора устарела." in page.inner_text(".pf-cash")
              and page.locator(".pf-dec").count() == 0)
        check("первая сборка кеш не шлёт", "cash_fact" not in sent[n0] and "cash_fact_iis" not in sent[n0])
        page.fill("#pf-cashfact", "-5")
        page.click("#pf-cashfact-go")
        check("некорректное → ошибка ввода, на сервер не ушло",
              "нужно число" in page.inner_text("#pf-cashfact-err") and len(sent) == n0 + 1)
        page.fill("#pf-cashfact", "")
        page.fill("#pf-cashfact-iis", "12345")
        page.click("#pf-cashfact-go")
        page.wait_for_function("document.querySelector('#pf-result') && document.querySelector('#pf-result').innerText.indexOf('кэш ИИС-3 внесён') >= 0", timeout=10000)
        check("пустое поле не передаётся: только cash_fact_iis",
              len(sent) == n0 + 2 and "cash_fact" not in sent[-1] and sent[-1]["cash_fact_iis"] == 12345
              and sent[-1]["files"] == sent[0]["files"] and sent[-1]["rebaseline_cash"] is False)
        page.fill("#pf-cashfact", "330000")
        page.fill("#pf-cashfact-iis", "41000.5")
        page.click("#pf-cashfact-go")
        page.wait_for_function("document.querySelector('#pf-result') && document.querySelector('#pf-result').innerText.indexOf('кэш внесён') >= 0", timeout=10000)
        check("оба кеша в POST, теги для обоих",
              len(sent) == n0 + 3 and sent[-1]["cash_fact"] == 330000 and sent[-1]["cash_fact_iis"] == 41000.5
              and "кэш ИИС-3 внесён" in page.inner_text("#pf-result"))
        rows = page.eval_on_selector_all("#pf-compare > *", "els => els.map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.top), Math.round(r.height)]; })")
        by_top = {}
        for top, h in rows:
            by_top.setdefault(top, set()).add(h)
        check("плитки сравнения: в каждом ряду одной высоты", rows and all(len(v) == 1 for v in by_top.values()))
        # «Тип бумаги изменился» (3.84.0): карточка при type_changes из build-summary, слова типов, подстроки, причины
        check("без type_changes карточки типов нет", page.query_selector(".pf-types") is None)
        tb = brief()
        tb["type_changes"] = [
            {"ticker": "TMON", "name": "TMON ETF", "was": "stock", "now": "fund", "moex": "fund", "heur": "stock", "reason": "prev_vs_now"},
            {"ticker": "NEWB", "name": "NEWB", "was": None, "now": "bond", "moex": "bond", "heur": "stock", "reason": "moex_vs_heuristic"}]
        tb["types"] = {"online": False, "fetched": 0, "failed": 0}
        scenario["brief"] = tb
        page.click("#pf-go")
        page.wait_for_selector(".pf-types", timeout=10000)
        ty = page.inner_text(".pf-types")
        check("карточка типов: заголовок, строки, слова вместо stock/fund/bond",
              "Тип бумаги изменился" in ty and "TMON ETF · TMON" in ty and "был акция → стал фонд" in ty
              and "стал облигация" in ty and page.locator(".pf-types .ui-row").count() == 2
              and "stock" not in ty and "fund" not in ty and "bond" not in ty)
        check("подстроки «по бирже / по сделкам» и причины словами",
              "по бирже: фонд · по сделкам: акция" in ty and "против прошлого снапшота" in ty
              and "новая бумага: биржа и эвристика разошлись" in ty)
        check("пояснение и «без сети»", "Проверь, прежде чем делать снапшот рабочим" in ty
              and "Тип с Мосбиржи обновляется только при сборке на сайте" in ty
              and "типы с биржи не запрашивались (сборка без сети)" in ty)
        check("карточка типов стоит перед «Кэш по счетам»", page.evaluate(
            "document.querySelector('.pf-types').compareDocumentPosition(document.querySelector('.pf-cash')) & Node.DOCUMENT_POSITION_FOLLOWING") > 0)
        check("карточка типов не шире экрана", page.evaluate("document.documentElement.scrollWidth") <= 390)
        tb["types"] = {"online": True, "fetched": 3, "failed": 0}
        page.click("#pf-go")
        page.wait_for_function("document.querySelector('.pf-types') && document.querySelector('.pf-types').innerText.indexOf('сборка без сети') < 0", timeout=10000)
        check("онлайн-сборка: строки «без сети» нет", "сборка без сети" not in page.inner_text(".pf-types"))
        # Строка паритета (3.85.0): brief.parity — итог и сгиб с путями; null — «сверки нет»
        tb["parity"] = None
        page.click("#pf-go")
        page.wait_for_function("document.querySelector('#pf-parity') && document.querySelector('#pf-parity').innerText.indexOf('Сверки нет') >= 0", timeout=10000)
        check("parity null у сборки с балансом: «эта сборка сама с балансом», сгиба нет",
              "эта сборка сама с балансом" in page.inner_text("#pf-parity") and page.query_selector("#pf-parity-fold") is None)
        scenario["files"] = {"trades": "trades_portfolio_707160-49.xlsx"}           # сервер ответил: сборка без баланса
        page.click("#pf-go")
        page.wait_for_function("document.querySelector('#pf-result') && !document.querySelector('#pf-parity')", timeout=10000)
        check("parity null без баланса (штатный режим): строки «Сверки нет» нет совсем",
              "Сверки нет" not in page.inner_text("#pf-result") and page.query_selector("#pf-parity-fold") is None)
        tb["parity"] = {"against": "/x.json", "against_date": "2026-10-28", "same_day": True, "auto": True, "matched": 1432,
                        "within_tol": 12, "known": 38, "diverged": 0, "diverged_paths": []}
        page.click("#pf-go")
        page.wait_for_function("document.querySelector('#pf-parity') && document.querySelector('#pf-parity').innerText.indexOf('совпало') >= 0", timeout=10000)
        check("parity без расхождений: итоговая строка, без сгиба",
              "Поле за полем против снапшота 28.10.2026: совпало 1432 · в допуске 12 · известных 38 · расходится 0" in page.inner_text("#pf-parity")
              and page.query_selector("#pf-parity-fold") is None)
        paths = ["$.holdings[FINAMAR|main].value_rub", "$.data_quality_flags[balance_vs_trades_mismatch|assemble_balance|" + "очень длинный текст " * 8 + "]"]
        tb["parity"] = {**tb["parity"], "diverged": 7, "diverged_paths": paths}
        page.click("#pf-go")
        page.wait_for_selector("#pf-parity-fold", timeout=10000)
        check("parity с расхождениями: строка с числом и сгиб «Где расходится · 2 из 7»",
              "расходится 7" in page.inner_text("#pf-parity") and "Где расходится · 2 из 7" in page.inner_text("#pf-parity-fold > summary"))
        page.click("#pf-parity-fold > summary")
        check("сгиб раскрывается: пути списком, моноширинно, страница не шире экрана",
              page.locator(".pf-parity-paths li").count() == 2 and "FINAMAR" in page.inner_text(".pf-parity-paths")
              and "monospace" in page.evaluate("getComputedStyle(document.querySelector('.pf-parity-paths')).fontFamily")
              and page.evaluate("document.documentElement.scrollWidth") <= 390)
        check("карточка «Общий баланс»: «по желанию: только для сверки с базой сайта»",
              "только для сверки с базой сайта" in page.inner_text("label[for=pf-balance]"))
        check("ошибок JS нет", not errs)
        if errs:
            print("  ", errs[:3])
        br.close()
    httpd.shutdown()
    httpd.server_close()
    print(f"viewer_pf_build: {passed} OK, {failed} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
