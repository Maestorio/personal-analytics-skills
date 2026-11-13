#!/usr/bin/env python3
"""Вьюер 3.122.0, «Загрузки» → панель результата сборки (браузер, /api/pf/* подменены, 1400 и 390 в светлой и тёмной теме).

Контракты:
  1. «Кэш по счетам»: строка на счёт — «в сохранённом (дд.мм) N ₽ → в этой сборке M ₽ · Δ», метка источника («внесён» / «оценка»),
     поле суммы в той же строке (#pf-cashfact, #pf-cashfact-iis, шрифт ≥16px), одна кнопка «Пересобрать с этим кешем» под строками;
     нет сохранённого — «сохранённого нет»; нет кэша ИИС-3 — строки нет; в панели нет слова «скилл».
  2. «Что изменится, если сохранить»: список позиций (продано / куплено / количество: бумага, счёт, было → стало), до 20 строк + «ещё N»;
     пусто — «позиции те же»; плитки «Стоимость с ИИС-3» (с подписью времени сохранённого) и «XIRR» двумя числами.
  3. Сборка без баланса — строки «Сверки нет…» нет; с балансом — «эта сборка сама с балансом».
  4. «Проверки»: «Нужно действие» (блок/предупреждения) и «К сведению» (флаги); одна общая строка про «Рейтинг в плане» под флагами без рейтинга;
     флаг по коду balance_absent_holdings_from_trades — не флагом, а «Источники сборки» в свёрнутом .ui-fold.
  5. Поле «Общий баланс» — в свёрнутом блоке «Сверка с «Общим балансом»», раскрывается кликом и выбором файла; сделки и ИИС-3 на виду.
  6. Решения сборки (b.decisions) — первыми строками «Нужно действие» с меткой «Решение», кнопка #pf-rebase внутри; плашки .ui-alert.pf-dec нет.
  8. 3.122.1: сборка «только сделки» поверх сохранённого того же дня с балансом / с внесённым кэшем (brief.save_block) — плашка не зелёная
     «Сохранить можно только с кэшем…», «Сохранить» неактивна, фокус на #pf-cashfact; без save_block — зелёная и активна.
     «План расходится с Numbers» (checks plan_mismatch) — не в «Нужно действие», а в «К сведению»: ««Общий баланс» отстаёт от плана на сайте по N полям: …».
  7. Не шире экрана; ошибок JS нет. Проверено падением: старая карточка «Кеш после сборки» / плитка «Кэш» / открытое поле баланса краснят тест.
Запуск: python3 tools/tests/test_viewer_pf_panel.py. Нужны playwright + chromium, без них пропуск.
"""
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
    print("viewer_pf_panel: пропуск — нет playwright")
    sys.exit(0)


def brief(**kw):
    rows = [{"kind": "sold", "ticker": "OLDX", "name": "Старая бумага", "account": "main", "was": 10, "now": None},
            {"kind": "bought", "ticker": "NEWB", "name": "NEWB", "account": "iis_3", "was": None, "now": 5},
            {"kind": "qty", "ticker": "SBER", "name": "Сбербанк", "account": "main", "was": 1800, "now": 1851}]
    b = {"as_of": "2026-10-30", "blocked": False, "decisions": [],
         "attention_flags": [{"code": "balance_absent_holdings_from_trades", "message": "«Общий баланс» не приложен: позиции из сделок; кеш — факт."},
                             {"code": "bond_rating_missing", "message": "Облигация А: рейтинга нет"},
                             {"code": "bond_rating_missing", "message": "Облигация Б: рейтинга нет"},
                             {"code": "bond_qty_vs_trades_mismatch", "message": "NorNik: 24 против 34"}],
         "checks": [{"id": "payout", "level": "warning", "message_ru": "DATA: выплата частями?"}],
         "n_info": 0, "fallbacks": {},
         "auto": {"as_of": "2026-10-30", "holdings": 120, "generated_at": "2026-10-30T12:28:21", "total_rub": 15200000,
                  "cash_rub": 223133, "cash_main_rub": 200644, "cash_iis_rub": 22489, "cash_source": "owner_intelinvest",
                  "cash_iis_source": "carried_from_prev", "xirr_total": 0.041, "xirr_restricted": 0.083},
         "skill": {"as_of": "2026-10-29", "holdings": 120, "generated_at": "2026-10-29T09:05:00", "total_rub": 15100000,
                   "cash_rub": 217273, "cash_main_rub": 190000, "cash_iis_rub": 27273, "xirr_total": 0.04, "xirr_restricted": 0.0827},
         "positions_diff": {"rows": rows, "more": 0, "total": 3}, "parity": None}
    b.update(kw)
    return b


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

    with sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception:  # noqa: BLE001
            print("viewer_pf_panel: пропуск — нет chromium")
            return 0
        for width, theme in ((1400, "light"), (390, "light"), (1400, "dark"), (390, "dark")):
            tag = f"[{width} {theme}] "
            sent = []
            sc = {"brief": brief(), "files": {"trades": "trades_portfolio_707160-49.xlsx"}}

            def api(route):
                req = route.request
                path = req.url.split("/api/pf/")[1]
                js = lambda code, o: route.fulfill(status=code, content_type="application/json", body=json.dumps(o))  # noqa: E731
                if path.startswith("build"):
                    sent.append(json.loads(req.post_data))
                    return js(202, {"run": f"r{len(sent)}"})
                if path.startswith("status"):
                    if "run=" not in path:
                        return js(404, {"error": "сборок ещё не было"})
                    return js(200, {"run": "r1", "state": "done", "started": "2026-10-30T22:10:00+03:00", "brief": sc["brief"],
                                    "files": sc["files"], "rebaseline_cash": sent[-1].get("rebaseline_cash"), "cash_fact": sent[-1].get("cash_fact"), "cash_fact_iis": sent[-1].get("cash_fact_iis"), "sec": 90})
                return route.fulfill(status=404, body="{}")

            ctx = br.new_context(viewport={"width": width, "height": 900}, color_scheme=theme)
            page = ctx.new_page()
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.route("**/api/pf/**", api)
            page.add_init_script(f"try {{ localStorage.setItem('hub-theme', '{theme}'); }} catch (e) {{}}")   # тема вьюера — hub-theme, не prefers-color-scheme
            page.add_init_script("window.setTimeout = ((st) => (fn, ms, ...a) => st(fn, Math.min(ms || 0, 50), ...a))(window.setTimeout)")
            page.goto(base + "/tools/portfolio-integrated-viewer.html")
            page.wait_for_selector("#btn-pfbuild:not([hidden])", timeout=20000)
            page.click("#btn-pfbuild")
            page.wait_for_selector("#pf-go", timeout=5000)
            dark = page.evaluate("(() => { const m = getComputedStyle(document.body).backgroundColor.match(/\\d+/g).map(Number); return (m[0] + m[1] + m[2]) / 3 < 128; })()")
            check(tag + "тема применилась", dark == (theme == "dark"))

            # --- п.5: поле «Общий баланс» в свёрнутом блоке
            check(tag + "блок «Сверка с «Общим балансом»» свёрнут, поле баланса внутри",
                  page.evaluate("document.getElementById('pf-bal-fold').open") is False
                  and page.evaluate("!!document.querySelector('#pf-bal-fold #pf-balance')")
                  and "Сверка с «Общим балансом»" in page.inner_text("#pf-bal-fold > summary")
                  and not page.is_visible("label[for=pf-balance]"))
            check(tag + "сделки и ИИС-3 на виду", page.is_visible("label[for=pf-trades]") and page.is_visible("label[for=pf-iis_trades]")
                  and not page.evaluate("!!document.querySelector('#pf-bal-fold #pf-trades, #pf-bal-fold #pf-iis_trades')"))
            page.click("#pf-bal-fold > summary")
            check(tag + "клик по заголовку раскрывает; подсказка прежняя",
                  page.evaluate("document.getElementById('pf-bal-fold').open") is True and page.is_visible("label[for=pf-balance]")
                  and "только для сверки с базой сайта" in page.inner_text("label[for=pf-balance]"))
            page.click("#pf-bal-fold > summary")
            page.set_input_files("#pf-balance", str(up / "Общий баланс.numbers"))
            check(tag + "выбор файла раскрывает блок", page.evaluate("document.getElementById('pf-bal-fold').open") is True)
            page.click("label[for=pf-balance] .pf-file-rm")
            page.click("#pf-bal-fold > summary")
            page.reload()
            page.wait_for_selector("#pf-go", timeout=20000) if page.query_selector("#pf-go") else None
            if not page.query_selector("#pf-go"):
                page.click("#btn-pfbuild")
                page.wait_for_selector("#pf-go", timeout=5000)

            # --- сборка без баланса
            page.set_input_files("#pf-trades", str(up / "trades_portfolio_707160-49.xlsx"))
            page.click("#pf-go")
            page.wait_for_selector("#pf-result", timeout=10000)
            res = page.inner_text("#pf-result")
            check(tag + "слова «скилл» в панели нет", "скилл" not in res.lower() and "Кеш после сборки" not in res)
            check(tag + "«Сверки нет…» без баланса нет", "Сверки нет" not in res and page.query_selector("#pf-parity") is None)
            check(tag + "заголовок и подзаголовок «Что изменится, если сохранить»",
                  "Что изменится, если сохранить" in res and "с сохранённым снапшотом от 29.10.2026" in res)
            rows = page.locator(".pf-cash-row")
            check(tag + "«Кэш по счетам»: две строки, плитки «Кэш» нет", "Кэш по счетам" in page.inner_text(".pf-cash") and rows.count() == 2
                  and page.locator("#pf-compare .ui-stat-k", has_text="Кэш").count() == 0)
            norm = lambda t: t.replace("\xa0", " ").replace(" ", " ")  # noqa: E731
            r0, r1 = norm(rows.nth(0).inner_text()), norm(rows.nth(1).inner_text())
            check(tag + f"основной: сохранённое → сборка · Δ, метка «внесён» ({r0!r})",
                  "Основной счёт" in r0 and "в сохранённом (29.10) 190 000 ₽" in r0 and "в этой сборке 200 644 ₽" in r0
                  and "+10 644 ₽" in r0 and "внесён" in r0)
            check(tag + f"ИИС-3: Δ отрицательная, метка «оценка» ({r1!r})",
                  "ИИС-3" in r1 and "27 273 ₽" in r1 and "22 489 ₽" in r1 and "−4 784 ₽" in r1 and "оценка" in r1)
            check(tag + "поля в той же строке, значения предзаполнены, шрифт ≥16px, одна кнопка",
                  page.evaluate("!!document.querySelector('.pf-cash-row #pf-cashfact') && !!document.querySelector('.pf-cash-row #pf-cashfact-iis')")
                  and page.input_value("#pf-cashfact") == "200644" and page.input_value("#pf-cashfact-iis") == "22489"
                  and page.evaluate("parseFloat(getComputedStyle(document.getElementById('pf-cashfact')).fontSize)") >= 16
                  and page.locator("#pf-cashfact-go").count() == 1 and page.inner_text("#pf-cashfact-go") == "Пересобрать с этим кешем")
            pos = norm(page.inner_text("#pf-posdiff"))
            check(tag + f"список позиций: продано / куплено / количество со счётом и было → стало ({pos!r})",
                  page.locator(".pf-pos").count() == 3 and "продано" in pos and "Старая бумага · OLDX" in pos and "было 10 → нет" in pos
                  and "куплено" in pos and "NEWB" in pos and "ИИС-3" in pos and "новая: 5" in pos
                  and "количество" in pos and "1 800 → 1 851" in norm(pos) and "основной" in pos)
            tiles = norm(page.inner_text("#pf-compare"))
            check(tag + f"плитки: стоимость с подписью времени, одна плитка XIRR двумя числами ({tiles!r})",
                  page.locator("#pf-compare .ui-stat").count() == 2 and "изменение цен и сделок с 29.10 09:05" in tiles
                  and "4,10% · 8,30%" in tiles and "вся история · активная часть" in tiles and "+0,10 пп · +0,03 пп" in tiles
                  and "+100 000 ₽" in tiles)
            # проверки
            check(tag + "«Нужно действие»: предупреждение; «К сведению»: флаги",
                  "Нужно действие" in res and "К сведению" in res and page.locator("#pf-checks-act .pf-check").count() == 1
                  and "DATA: выплата частями?" in page.inner_text("#pf-checks-act")
                  and "NorNik: 24 против 34" in page.inner_text("#pf-checks-info"))
            check(tag + "одна общая строка про рейтинг, после флагов без рейтинга",
                  page.locator(".pf-rating-hint").count() == 1 and "Мой план" in page.inner_text(".pf-rating-hint")
                  and "Рейтинг в плане" in page.inner_text(".pf-rating-hint")
                  and page.locator("#pf-checks-info .pf-check", has_text="рейтинга нет").count() == 2
                  and page.evaluate("document.querySelector('.pf-rating-hint').previousElementSibling.innerText.indexOf('Облигация Б') >= 0"))
            check(tag + "«Источники сборки» в свёрнутом сгибе, не флагом",
                  page.evaluate("document.getElementById('pf-sources-fold').open") is False
                  and "Источники сборки" in page.inner_text("#pf-sources-fold > summary")
                  and "не приложен" not in page.inner_text("#pf-checks-info")
                  and not page.is_visible("#pf-sources-fold .pf-sources"))
            page.click("#pf-sources-fold > summary")
            check(tag + "сгиб раскрывается: текст флага",
                  "кеш — факт" in page.inner_text("#pf-sources-fold .pf-sources") and page.is_visible("#pf-sources-fold .pf-sources"))
            check(tag + "не шире экрана", page.evaluate(f"document.documentElement.scrollWidth <= {width}"))
            # пересборка с кэшем из строки
            page.fill("#pf-cashfact", "210000")
            page.click("#pf-cashfact-go")
            page.wait_for_function("document.querySelector('#pf-result') && document.querySelector('#pf-result').innerText.indexOf('кэш внесён') >= 0", timeout=10000)
            check(tag + "пересборка шлёт cash_fact из поля строки, ИИС-3 — своё значение",
                  sent[-1].get("cash_fact") == 210000 and sent[-1].get("cash_fact_iis") == 22489)

            # --- ничего не изменилось, сохранённого нет, нет ИИС-3
            b2 = brief(attention_flags=[], checks=[], positions_diff={"rows": [], "more": 0, "total": 0})
            b2["skill"] = None
            b2["auto"] = {**b2["auto"], "cash_iis_rub": None, "cash_source": "trades_plus_prev_drift"}
            sc["brief"] = b2
            page.click("#pf-go")
            page.wait_for_function("document.querySelector('#pf-posdiff') && document.querySelector('#pf-posdiff').innerText.indexOf('позиции те же') >= 0", timeout=10000)
            res = norm(page.inner_text("#pf-result"))
            check(tag + "«позиции те же»; сохранённого нет; строки ИИС-3 нет; метка «оценка»; блоков проверок нет",
                  page.locator(".pf-pos").count() == 0 and "сохранённого нет" in res and page.locator(".pf-cash-row").count() == 1
                  and "оценка" in page.inner_text(".pf-cash-row") and "Нужно действие" not in res and "К сведению" not in res)

            # --- 20 строк + «ещё N»
            many = [{"kind": "bought", "ticker": f"T{i:02d}", "name": f"T{i:02d}", "account": "main", "was": None, "now": i + 1} for i in range(20)]
            sc["brief"] = brief(positions_diff={"rows": many, "more": 5, "total": 25})
            page.click("#pf-go")
            page.wait_for_function("document.querySelectorAll('.pf-pos').length === 20", timeout=10000)
            check(tag + "20 строк и «ещё 5»", "ещё 5" in page.inner_text(".pf-pos-more") and page.locator(".pf-pos").count() == 20)

            # --- решения сборки — внутри «Нужно действие», первыми строками; отдельной жёлтой плашки нет
            dec_msg = "Кэш-расхождение изменилось: пополнения и выводы в выгрузке полные?"
            sc["brief"] = brief(decisions=[{"code": "cash_drift_changed", "message_ru": dec_msg}])
            n0 = len(sent)
            page.click("#pf-go")
            page.wait_for_selector("#pf-checks-act .pf-dec", timeout=10000)
            first = page.locator("#pf-checks-act > li").first
            check(tag + "решение — первая строка «Нужно действие», метка «Решение», вид строки проверки, дальше обычная проверка",
                  page.locator("#pf-checks-act > li").count() == 2 and "pf-dec" in (first.get_attribute("class") or "")
                  and "pf-check" in (first.get_attribute("class") or "") and first.locator(".pf-lvl").inner_text().strip().lower() == "решение"
                  and dec_msg.split(":")[0] in first.inner_text() and "DATA: выплата частями?" in page.locator("#pf-checks-act > li").nth(1).inner_text())
            check(tag + "кнопка pf-rebase внутри строки решения; отдельной плашки .ui-alert.pf-dec и «Нужно решение» нет",
                  first.locator("#pf-rebase").count() == 1 and page.locator(".ui-alert.pf-dec").count() == 0
                  and "Нужно решение" not in page.inner_text("#pf-result")
                  and page.evaluate("document.querySelector('.pf-dec').closest('#pf-checks-act') !== null"))
            check(tag + "решение в блоке на экране не шире окна", page.evaluate(f"document.documentElement.scrollWidth <= {width}"))
            page.click("#pf-rebase")
            page.wait_for_function("document.querySelector('#pf-result') && document.querySelector('#pf-result').innerText.indexOf('кэш-расхождение принято') >= 0", timeout=10000)
            check(tag + "pf-rebase запускает пересборку с rebaseline_cash", len(sent) == n0 + 2 and sent[-1].get("rebaseline_cash") is True and sent[-2].get("rebaseline_cash") is False)
            # решения есть, проверок «нужно действие» нет — блок всё равно показан
            sc["brief"] = brief(checks=[], decisions=[{"code": "type_changed", "message_ru": "Тип бумаги изменился: X"}])
            page.click("#pf-go")
            page.wait_for_function("document.querySelector('#pf-checks-act .pf-dec') && document.querySelector('#pf-checks-act').innerText.indexOf('Тип бумаги изменился') >= 0", timeout=10000)
            check(tag + "только решение: блок «Нужно действие» есть, одна строка",
                  "Нужно действие" in page.inner_text("#pf-result") and page.locator("#pf-checks-act > li").count() == 1
                  and page.locator("#pf-rebase").count() == 0)

            # --- 3.122.1: сохранить нельзя заранее — плашка не зелёная, кнопка неактивна, фокус на поле кэша основного счёта
            for reason in ("balance", "cash_fact"):
                sc["brief"] = brief(trades_only=True, save_block=reason)
                page.click("#pf-go")
                page.wait_for_function("document.querySelector('#pf-verdict.warn')", timeout=10000)
                vt = norm(page.inner_text("#pf-verdict"))
                check(tag + f"{reason}: плашка предупреждения (не зелёная, не блок), текст про кэш",
                      "Сохранить можно только с кэшем: внеси суммы из IntelInvest и нажми «Пересобрать с этим кешем»" in vt
                      and "можно сохранить" not in vt.replace("Сохранить можно только", "") and "block" not in (page.get_attribute("#pf-verdict", "class") or ""))
                check(tag + f"{reason}: «Сохранить» неактивна", page.evaluate("document.getElementById('pf-save').disabled") is True)
                page.wait_for_timeout(300)
                check(tag + f"{reason}: фокус на поле кэша основного счёта", page.evaluate("document.activeElement && document.activeElement.id") == "pf-cashfact")
            sc["brief"] = brief(trades_only=True, save_block=None)
            page.click("#pf-go")
            page.wait_for_function("document.querySelector('#pf-verdict') && !document.querySelector('#pf-verdict.warn')", timeout=10000)
            check(tag + "нет сохранённого того же дня: плашка зелёная, «Сохранить» активна",
                  "Блок-проверок нет — можно сохранить" in page.inner_text("#pf-verdict") and page.evaluate("document.getElementById('pf-save').disabled") is False)

            # --- 3.122.1: «план расходится с Numbers» — к сведению, словами «Общий баланс отстаёт»
            sc["brief"] = brief(checks=[
                {"id": "payout", "level": "warning", "message_ru": "DATA: выплата частями?"},
                {"id": "plan_mismatch", "level": "warning", "message_ru": "план в plan.json расходится с Numbers по 3 полям: stocks.A.plan_pct, stocks.B.plan_pct, funds.SBGB.bucket.",
                 "details": {"n_diff": 3, "paths": ["stocks.A.plan_pct", "stocks.B.plan_pct", "funds.SBGB.bucket"]}}])
            page.click("#pf-go")
            page.wait_for_function("document.querySelector('#pf-checks-info') && document.querySelector('#pf-checks-info').innerText.indexOf('отстаёт от плана') >= 0", timeout=10000)
            act, inf = page.inner_text("#pf-checks-act"), norm(page.inner_text("#pf-checks-info"))
            check(tag + f"план расходится: в «Нужно действие» его нет, остальное на месте ({act!r})", "расходится" not in act and "DATA: выплата частями?" in act and page.locator("#pf-checks-act > li").count() == 1)
            check(tag + f"в «К сведению»: «Общий баланс» отстаёт от плана на сайте по 3 полям: пути ({inf!r})",
                  "«Общий баланс» отстаёт от плана на сайте по 3 полям: stocks.A.plan_pct, stocks.B.plan_pct, funds.SBGB.bucket" in inf and "расходится" not in inf)
            check(tag + "не шире экрана", page.evaluate(f"document.documentElement.scrollWidth <= {width}"))

            # --- с балансом
            sc["brief"] = brief()
            sc["files"] = {"trades": "trades_portfolio_707160-49.xlsx", "balance": "Общий баланс.numbers"}
            page.click("#pf-go")
            page.wait_for_function("document.querySelector('#pf-parity')", timeout=10000)
            check(tag + "с балансом: «эта сборка сама с балансом»", "эта сборка сама с балансом" in page.inner_text("#pf-parity"))
            check(tag + "ошибок JS нет", not errs)
            ctx.close()
        br.close()
    httpd.shutdown()
    httpd.server_close()
    print(f"viewer_pf_panel: {passed} OK, {failed} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
