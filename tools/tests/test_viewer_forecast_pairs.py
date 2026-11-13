#!/usr/bin/env python3
"""Вьюер 3.115.0: прогноз и сценарии одной темы — одна строка на «Действиях» — настоящий Chromium, клик по реальной строке.

Дефект 29.10 (владелец): по одной теме монитор даёт два предупреждения (прогноз и сценарии), фраза «Обнови сценарии …» читается как «а почему не прогноз»;
у строки сценариев стояло «прогноз от».
Правило пары: тема = имя файла без «scenario-» и без даты. На живых данных пара по имени одна — usd-rub-sept-2026 (прогноз и сценарии 30.04);
brent-dec-2026 — только сценарии; ai-capex: прогноз ai-capex-slowdown-2026, сценарии ai-capex-scenarios-2026 — темы разные, не склеиваются.
Фикстура — ЖИВЫЕ forecasts/scenarios пары usd-rub-sept-2026 + stress-roles (стресс 04.10, сценарии brent-dec-2026 и геополитики); отчёт монитора
собран по образцу живого 26.10-v2 (предупреждения по обоим файлам); статус файлов пары в живых данных resolved — в вариантах подменяется.
Контракты:
  1. Пара → одна строка: заголовок по теме, «прогноз от 30.04 · сценарии от 30.04», важность — максимальная (HIGH при MEDIUM+HIGH), одна плашка роли.
  2. Фразы для Claude — по числу предупреждений: оба файла — две («Обнови прогноз …», «Обнови сценарии …»); одно предупреждение — одна, строка не пара.
  3. Одиночные сценарии (brent-dec-2026) — «сценарии от 30.04».
  4. Окно пары — две вкладки «Прогноз · Сценарии»: каждая показывает свой документ и свою фразу.
  5. Оба файла сделаны (resolved) — пара одна строка в «Сделано»; сделан один — пара остаётся на «Действиях», сделанный файл помечен.
  6. Плашка роли пары — «в стресс-тесте», если хотя бы один файл входит в стресс (сценарии геополитики + прогноз-заглушка той же темы).
  7. Ошибок страницы нет.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_forecast_pairs.py
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
    print("viewer_forecast_pairs: пропуск — нет playwright")
    sys.exit(0)

sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as hub_api  # noqa: E402

FIX = Path(tempfile.mkdtemp(prefix="fpairs-"))
GEO_STUB = """schema_version: 1
type: forecast-events
forecast_ref: geopolitics-ru-west-2026-07-01.md
status: active

forecast:
  date: 2026-07-01
  horizon: 2026-12-31
  topic: geopolitics-ru-west
  central_estimate: "заглушка для проверки роли пары"
"""


def alert(target, kind, sev, sa, msg):
    folder = "scenarios" if kind == "scenario" else "forecasts"
    return f"""  - severity: {sev}
    category: stale
    target: "{target}"
    target_file: "{folder}/{sa[1]}"
    target_kind: {kind}
    message: "{msg}"
    detected_at: "2026-10-29"
    suggested_action: "{sa[0]}"
"""


def build(fc_status="active", sc_status="active", fc_alert=True, fc_sev="MEDIUM", sc_sev="HIGH", geo_pair=False):
    shutil.rmtree(FIX, ignore_errors=True)
    fx = REPO / "tools/tests/fixtures"
    shutil.copytree(fx / "viewer-live", FIX)
    shutil.copytree(fx / "stress-roles", FIX, dirs_exist_ok=True)
    shutil.copytree(fx / "forecast-pairs", FIX, dirs_exist_ok=True)
    (FIX / "monitor-reports").mkdir()
    for rel, st in (("forecasts/usd-rub-sept-2026-2026-04-30.yaml", fc_status), ("scenarios/scenario-usd-rub-sept-2026-2026-04-30.yaml", sc_status)):
        f = FIX / rel
        f.write_text(f.read_text(encoding="utf-8").replace("status: resolved", f"status: {st}", 1), encoding="utf-8")
    if geo_pair:
        (FIX / "forecasts/geopolitics-ru-west-2026-07-01.yaml").write_text(GEO_STUB, encoding="utf-8")
    FC = ("/forecast-confidence-applier Обнови прогноз usd-rub-sept-2026-2026-04-30.yaml", "usd-rub-sept-2026-2026-04-30.yaml")
    SC = ("/scenario-builder Обнови сценарии scenario-usd-rub-sept-2026-2026-04-30.yaml", "scenario-usd-rub-sept-2026-2026-04-30.yaml")
    rows = []
    if fc_alert:
        rows.append(alert("usd-rub-sept-2026", "forecast", fc_sev, FC, "Ревью прогноза просрочено"))
    rows.append(alert("usd-rub-sept-2026", "scenario", sc_sev, SC, "Ревью просрочено на 55 дней; горизонт 01.09.2026 прошёл"))
    rows.append(alert("brent-dec-2026", "scenario", "HIGH",
                      ("/scenario-builder Обнови сценарии scenario-brent-dec-2026-2026-04-30.yaml", "scenario-brent-dec-2026-2026-04-30.yaml"), "Ревью просрочено"))
    if geo_pair:
        rows.append(alert("geopolitics-ru-west", "scenario", "HIGH",
                          ("/scenario-builder Обнови сценарии scenario-geopolitics-ru-west-2026-07-01.yaml", "scenario-geopolitics-ru-west-2026-07-01.yaml"), "Ревью просрочено"))
        rows.append(alert("geopolitics-ru-west", "forecast", "MEDIUM",
                          ("/forecast-confidence-applier Обнови прогноз geopolitics-ru-west-2026-07-01.yaml", "geopolitics-ru-west-2026-07-01.yaml"), "Ревью просрочено"))
    (FIX / "monitor-reports/monitor-report-2026-10-29.yaml").write_text(f"""schema_version: 1
type: monitor-report
generated_at: "2026-10-29T15:50:00+03:00"
producer: "forecast-monitor"
horizon_window_days: 7
alerts:
{"".join(rows)}freshness_audit:
  integrated_view: {{ age_days: 25, due_for_refresh: false }}
predictions:
  total_active: 1
  overdue_count: 0
  due_30d_count: 0
  overdue_list: []
condition_events: []
outcome_log_updates: []
""", encoding="utf-8")


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


def row(pg, target):
    return pg.locator(f'#content .act-alert[data-target="{target}"]')


def open_actions(p):
    browser = p.chromium.launch()
    ctx = browser.new_context(service_workers="block", viewport={"width": 1400, "height": 1000})
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "502" not in m.text and "404" not in m.text else None)
    pg.route("**/api/pv/plan*", lambda r: r.fulfill(status=502, body="{}"))
    pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, body="{}"))
    pg.goto(URL)
    pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
    pg.wait_for_function("() => state.data && state.data.portfolioLatest && state.data.monitorReport", timeout=20000)
    pg.evaluate("() => { goToTab('actions'); }")
    pg.wait_for_selector("#content .act-alert", timeout=10000)
    pg.evaluate("() => document.querySelectorAll('#act-info, #act-info details').forEach(d => d.open = true)")   # R20: «ревью просрочено» по прогнозам и сценариям вне стресса — в справочных «К сведению»
    return browser, pg, errs


def tags(pg, target):
    t = row(pg, target).locator(".act-alert-h .tag")
    return [t.nth(i).text_content().strip() for i in range(t.count())]


def says(pg, target):
    s = row(pg, target).locator(".act-say em")
    return [s.nth(i).text_content().strip() for i in range(s.count())]


def main():
    with sync_playwright() as p:
        try:
            p.chromium.launch().close()
        except Exception as e:
            print(f"viewer_forecast_pairs: пропуск — {str(e).splitlines()[0][:80]}")
            return

        # 1–4: оба файла пары активны, предупреждения MEDIUM (прогноз) и HIGH (сценарии)
        build()
        browser, pg, errs = open_actions(p)
        r = row(pg, "usd-rub-sept-2026")
        check(f"пара — ровно одна строка ({r.count()})", r.count() == 1)
        check("отдельной строки сценариев нет (на «Действиях» одна строка с темой usd-rub-sept-2026)",
              pg.locator('#content :is(#act-do, #act-info) .act-alert[data-targets="usd-rub-sept-2026|usd-rub-sept-2026"]').count() == 1)
        check(f"заголовок по теме ({r.locator('strong').first.text_content()!r})", r.locator("strong").first.text_content().strip() == "usd-rub-sept-2026")
        line = r.locator(".act-doc-d").first.text_content().strip()
        check(f"под названием «прогноз от 30.04 · сценарии от 30.04» ({line!r})", line == "прогноз от 30.04 · сценарии от 30.04")
        tg = tags(pg, "usd-rub-sept-2026")
        check(f"важность — максимальная (HIGH → «важно», R27: слово, код — в подсказке), плашка роли одна ({tg})", tg[:1] == ["важно"] and len(tg) == 2 and tg[1] == "самостоятельный")
        sy = says(pg, "usd-rub-sept-2026")
        check(f"две фразы для Claude — прогноз и сценарии ({sy})", len(sy) == 2
              and "Обнови прогноз usd-rub-sept-2026-2026-04-30.yaml" in sy[0] and "Обнови сценарии scenario-usd-rub-sept-2026-2026-04-30.yaml" in sy[1])
        b = row(pg, "brent-dec-2026").locator(".act-doc-d").first.text_content().strip()
        check(f"одиночные сценарии brent-dec-2026: «сценарии от 30.04» ({b!r})", b.startswith("сценарии от 30.04") and "прогноз от" not in b)   # хвост «· ревью было до …» — от _docRowLine
        # окно пары
        r.locator("strong").first.click()
        pg.wait_for_function("() => { const o = document.querySelector('#modal-overlay'); return o && !o.hidden && document.querySelector('#modal').innerText.includes('Почему монитор просит обновить'); }", timeout=5000)
        tabs = pg.locator("#modal .fdoc-tabs .ui-seg-btn")
        check(f"окно пары: две вкладки «Прогноз» и «Сценарии» ({[tabs.nth(i).text_content() for i in range(tabs.count())]})",
              tabs.count() == 2 and tabs.nth(0).text_content() == "Прогноз" and tabs.nth(1).text_content() == "Сценарии")
        txt = pg.evaluate("() => document.querySelector('#modal').innerText")
        check("вкладка «Прогноз»: прогноз от 30.04, файл прогноза, своя фраза", "Прогноз от" in txt and "usd-rub-sept-2026-2026-04-30.yaml" in txt
              and "Обнови прогноз usd-rub-sept-2026-2026-04-30.yaml" in txt and "Обнови сценарии" not in txt)
        check("заголовок окна — «Прогноз — usd-rub-sept-2026»", pg.locator("#modal-title").text_content().startswith("Прогноз —"))
        tabs.nth(1).click()
        pg.wait_for_timeout(300)
        txt = pg.evaluate("() => document.querySelector('#modal').innerText")
        check("вкладка «Сценарии»: сценарии от 30.04, файл scenario-…, своя фраза и свой текст предупреждения",
              "Сценарии от" in txt and "scenario-usd-rub-sept-2026-2026-04-30.yaml" in txt and "Обнови сценарии scenario-usd-rub-sept-2026-2026-04-30.yaml" in txt
              and "горизонт 01.09.2026 прошёл" in txt and "Обнови прогноз" not in txt)
        check("заголовок окна — «Сценарии — usd-rub-sept-2026»", pg.locator("#modal-title").text_content().startswith("Сценарии —"))
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # 2: предупреждение только по сценариям — одна фраза, строка не пара, подпись «сценарии от»
        build(fc_alert=False)
        browser, pg, errs = open_actions(p)
        r = row(pg, "usd-rub-sept-2026")
        check(f"одно предупреждение: строка одна и не пара ({r.count()})", r.count() == 1 and pg.locator("#content .act-pair").count() == 0)
        check(f"подпись «сценарии от 30.04» ({r.locator('.act-doc-d').first.text_content()!r})", r.locator(".act-doc-d").first.text_content().strip().startswith("сценарии от 30.04") and "прогноз от" not in r.locator(".act-doc-d").first.text_content())
        sy = says(pg, "usd-rub-sept-2026")
        check(f"одна фраза — по файлу сценариев ({sy})", len(sy) == 1 and "Обнови сценарии scenario-usd-rub-sept-2026-2026-04-30.yaml" in sy[0])
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # 5: оба файла разрешены (живое состояние) — пара одна строка в «Сделано»
        build(fc_status="resolved", sc_status="resolved")
        browser, pg, errs = open_actions(p)
        check("оба сделаны: пара в «Сделано» одной строкой, на «Действиях» её нет",
              pg.locator("#content #act-done .act-pair").count() == 1 and pg.locator("#content :is(#act-do, #act-info) .act-pair").count() == 0)
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()
        # 5: сделан один (прогноз) — пара остаётся на «Действиях», сделанный файл помечен
        build(fc_status="resolved", sc_status="active")
        browser, pg, errs = open_actions(p)
        r = pg.locator("#content :is(#act-do, #act-info) .act-pair")
        check("сделан один файл: пара остаётся на «Действиях»", r.count() == 1)
        check("помечено «Прогноз — сделано», фраза осталась одна — по сценариям",
              "Прогноз — сделано" in r.inner_text() and r.locator(".act-say").count() == 1 and "Обнови сценарии" in r.locator(".act-say em").text_content())
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # 6: роль пары — хотя бы один файл входит в стресс
        build(geo_pair=True)
        browser, pg, errs = open_actions(p)
        tg = tags(pg, "geopolitics-ru-west")
        check(f"пара геополитики: одна плашка «в стресс-тесте» ({tg})", tg[:1] == ["важно"] and tg[1:] == ["в стресс-тесте"])
        check("пара геополитики: подсказка про перегон стресса одна", row(pg, "geopolitics-ru-west").locator(".act-rerun").count() == 1)
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()


main()
shutil.rmtree(FIX, ignore_errors=True)
print(f"Итого: {passed} из {passed + failed} прошли" if failed == 0 else f"Итого: {passed} из {passed + failed} прошли (падений: {failed})")
sys.exit(1 if failed else 0)
