#!/usr/bin/env python3
"""Вьюер 3.109.0: «Действия» — строка предупреждения монитора открывает сам прогноз или сценарии — настоящий Chromium, клик по реальной строке.

Дефект 29.10 (владелец): строка «монитор 26.10 · HIGH · cbr-rate-2026-2027 · пробит порог …» непонятна — какая дата прогноза, зачем его обновлять.

Контракты (фикстура viewer-live + monitor-reports/forecasts/scenarios во временной папке):
  1. В строке под названием темы мелко «прогноз от ДД.ММ · следующее ревью ДД.ММ» (ревью в прошлом — «ревью было до …»).
  2. Клик по строке (по названию темы) → окно: в сводке дата прогноза, горизонт, следующий пересмотр, статус; блок «Почему монитор просит обновить»
     с текстом предупреждения, «Проверено в сети: …» и фразой для Claude; ниже — текст прогноза (md без frontmatter).
  3. «скопировать» в строке окна не открывает (всплытие погашено).
  4. Сценарии без md (только yaml) → окно с таблицей сценариев и весов, без сырого YAML.
  5. Файла нет вовсе → строка не кликается (нет .pick), рядом «файл прогноза не найден», окно не открывается.
  6. Имя файла берётся из фразы «Обнови прогноз <файл>.yaml»: есть два файла темы — открывается названный, а не самый свежий.
  7. Тексты сценариев (scenarios/*.md) приходят в /api/pv/sync и открываются окном.
  8. Ошибок страницы нет.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_forecast_window.py
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
    print("viewer_forecast_window: пропуск — нет playwright")
    sys.exit(0)

sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as hub_api  # noqa: E402

FIX = Path(tempfile.mkdtemp(prefix="fdoc-"))
shutil.copytree(REPO / "tools/tests/fixtures/viewer-live", FIX, dirs_exist_ok=True)
for d in ("monitor-reports", "forecasts", "scenarios"):
    (FIX / d).mkdir(exist_ok=True)

(FIX / "monitor-reports/monitor-report-2026-10-29.yaml").write_text("""schema_version: 1
type: monitor-report
generated_at: "2026-10-29T15:50:00+03:00"
producer: "forecast-monitor"
horizon_window_days: 7
alerts:
  - severity: HIGH
    category: factor_breach
    target: "cbr-rate-2026-2027"
    target_file: "forecasts/cbr-rate-2026-2027-2026-09-17.yaml"
    target_kind: forecast
    message: "ЦБ 23.10.2026 сохранил ставку 14% (пауза), модальная траектория не реализована"
    detected_at: "2026-10-29"
    web_search_summary: "Интерфакс 23.10.2026: ставка 14%, следующее заседание 18.12"
    suggested_action: "/forecast-confidence-applier Обнови прогноз cbr-rate-2026-2027-2026-07-29.yaml"
  - severity: HIGH
    category: stale
    target: "geo-test"
    target_file: "scenarios/scenario-geo-test-2026-07-01.yaml"
    target_kind: scenario
    message: "Ревью просрочено на 25 дней"
    detected_at: "2026-10-29"
    suggested_action: "/scenario-builder Обнови сценарии scenario-geo-test-2026-07-01.yaml"
  - severity: HIGH
    category: stale
    target: "geo-text"
    target_file: "scenarios/scenario-geo-text-2026-07-01.yaml"
    target_kind: scenario
    message: "Ревью просрочено"
    detected_at: "2026-10-29"
    suggested_action: "/scenario-builder Обнови сценарии scenario-geo-text-2026-07-01.yaml"
  - severity: HIGH
    category: stale
    target: "ghost-topic"
    target_file: "forecasts/ghost-topic-2026-01-01.yaml"
    target_kind: forecast
    message: "Ревью просрочено на 88 дней"
    detected_at: "2026-10-29"
    suggested_action: "/forecast-confidence-applier Обнови прогноз ghost-topic-2026-01-01.yaml"
freshness_audit:
  integrated_view: { age_days: 25, due_for_refresh: false }
predictions:
  total_active: 1
  overdue_count: 0
  due_30d_count: 0
  overdue_list: []
condition_events: []
outcome_log_updates: []
""", encoding="utf-8")

for stamp, est, due in (("2026-09-17", "13.625% к 2026-12-31", "2026-12-17"), ("2026-07-29", "СТАРАЯ-ОЦЕНКА", "2026-10-28")):
    (FIX / f"forecasts/cbr-rate-2026-2027-{stamp}.yaml").write_text(f"""schema_version: 1
type: forecast-events
status: active
forecast:
  date: {stamp}
  horizon: 2028-12-31
  topic: cbr-rate-2026-2027
  central_estimate: "{est}"
  confidence: 0.30
reviews:
  interval_months: 3
  next_due: {due}
  last_completed: null
monitoring:
  - id: cbr-dec18
    description: "Заседание 18.12.2026 определяет значение на конец года"
    threshold: "ставка вне [13.50, 13.75]"
    check_date: 2026-12-18
""", encoding="utf-8")
    (FIX / f"forecasts/cbr-rate-2026-2027-{stamp}.md").write_text(f"""---
schema_version: 1
forecast_date: {stamp}
horizon_date: 2028-12-31
topic: cbr-rate-2026-2027
---

# Прогноз ставки ЦБ · {stamp}

ТЕКСТ-ПРОГНОЗА-{stamp}: ключевая ставка к концу года.
""", encoding="utf-8")

(FIX / "scenarios/scenario-geo-test-2026-07-01.yaml").write_text("""schema_version: 1
type: scenario-events
status: active
matrix:
  date: 2026-07-01
  horizon: 2028-12-31
  topic: geo-test
scenario_triggers:
  - scenario_id: A
    label: "Затяжная осада"
    probability: 0.15
  - scenario_id: B
    label: "Большая сделка"
    probability: 0.35
reviews:
  interval_months: 3
  next_due: 2026-10-01
  last_completed: null
""", encoding="utf-8")
(FIX / "scenarios/scenario-geo-text-2026-07-01.yaml").write_text("""schema_version: 1
type: scenario-events
status: active
matrix:
  date: 2026-07-01
  horizon: 2028-12-31
  topic: geo-text
reviews:
  next_due: 2026-10-01
""", encoding="utf-8")
(FIX / "scenarios/scenario-geo-text-2026-07-01.md").write_text("""---
schema_version: 1
type: scenario-matrix
date_created: 2026-07-01
topic: geo-text
---

# Сценарии: тест · 2026-07-01

ТЕКСТ-СЦЕНАРИЕВ: карта лагерей.
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

MODAL = "() => { const m = document.querySelector('#modal'); const o = document.querySelector('#modal-overlay'); return o && !o.hidden && m ? m.innerText : ''; }"


def row(pg, target):
    return pg.locator(f'#content .act-alert[data-target="{target}"]')


def main():
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            print(f"viewer_forecast_window: пропуск — {str(e).splitlines()[0][:80]}")
            return
        ctx = browser.new_context(service_workers="block", viewport={"width": 1400, "height": 1000})
        ctx.grant_permissions(["clipboard-read", "clipboard-write"])
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
        pg.evaluate("() => document.querySelectorAll('#act-info, #act-info details').forEach(d => d.open = true)")   # R20: «ревью просрочено» по прогнозам вне стресса — в справочных «К сведению»

        # 7. тексты сценариев пришли
        check("scenarios/*.md загружен вьюером (scenarioMds)", pg.evaluate("() => (state.data.scenarioMds || []).length") == 1)

        # 1. строка с датой без клика
        line = row(pg, "cbr-rate-2026-2027").locator(".act-doc-d").inner_text()
        # (6) названа 07-29 в фразе «Обнови прогноз» — открывается она, а не самая свежая 09-17
        check(f"строка: берётся файл из фразы «Обнови прогноз», не самый свежий ({line!r})", line == "прогноз от 29.07 · ревью было до 28.10")
        check("сценарии: «сценарии от 01.07 · ревью было до 01.10»", row(pg, "geo-test").locator(".act-doc-d").inner_text() == "сценарии от 01.07 · ревью было до 01.10")

        # 2. клик по реальной строке
        row(pg, "cbr-rate-2026-2027").locator("strong").click()
        pg.wait_for_function(f"() => ({MODAL})().includes('Почему монитор просит обновить')", timeout=5000)
        txt = pg.evaluate(MODAL)
        check("окно: заголовок «Прогноз — cbr-rate-2026-2027»", "Прогноз — cbr-rate-2026-2027" in txt)
        check("окно: дата прогноза 29.07.2026 и горизонт 31.12.2028", "29.07.2026" in txt and "31.12.2028" in txt)
        check("окно: следующий пересмотр 28.10.2026 — срок прошёл", "28.10.2026" in txt and "срок прошёл" in txt)
        check("окно: ближайшая проверка события 18.12.2026 — «Заседание 18.12.2026 определяет …»", "18.12.2026 — Заседание 18.12.2026 определяет значение на конец года" in txt)
        check("окно: статус «действует»", "действует" in txt)
        check("окно: текст предупреждения и «Проверено в сети»", "модальная траектория не реализована" in txt and "Проверено в сети: Интерфакс" in txt)
        check("окно: тип «пробит порог»", "пробит порог" in txt)
        check("окно: фраза для Claude", "Что сказать Claude" in txt and "Обнови прогноз cbr-rate-2026-2027-2026-07-29.yaml" in txt)
        check("окно: текст прогноза (md) названного файла", "ТЕКСТ-ПРОГНОЗА-2026-07-29" in txt and "ТЕКСТ-ПРОГНОЗА-2026-09-17" not in txt)
        check("окно: frontmatter не сырой", "schema_version" not in txt and "horizon_date" not in txt)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(500)

        # 3. «скопировать» не открывает окно
        row(pg, "cbr-rate-2026-2027").locator(".ui-claude-cmd").first.click()
        pg.wait_for_timeout(400)
        check("«скопировать» не открывает окно", pg.evaluate(MODAL) == "")

        # 4. сценарии без md: таблица полей
        row(pg, "geo-test").locator("strong").click()
        pg.wait_for_function(f"() => ({MODAL})().includes('Почему монитор просит обновить')", timeout=5000)
        txt = pg.evaluate(MODAL)
        check("сценарии без md: заголовок «Сценарии — geo-test», дата 01.07.2026", "Сценарии — geo-test" in txt and "01.07.2026" in txt)
        check("сценарии без md: таблица «Затяжная осада · 15 %», «Большая сделка · 35 %»", "Затяжная осада" in txt and "15 %" in txt and "Большая сделка" in txt and "35 %" in txt)
        check("сценарии без md: без сырого YAML", "scenario_triggers" not in txt and "probability" not in txt)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(500)

        # 7. md сценариев
        row(pg, "geo-text").locator("strong").click()
        pg.wait_for_function(f"() => ({MODAL})().includes('Почему монитор просит обновить')", timeout=5000)
        check("сценарии с md: текст сценариев в окне", "ТЕКСТ-СЦЕНАРИЕВ" in pg.evaluate(MODAL))
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(500)

        # 5. файла нет — не кликается
        gh = row(pg, "ghost-topic")
        check("нет файла: строка без .pick", "pick" not in (gh.get_attribute("class") or ""))
        check("нет файла: «файл прогноза не найден»", "файл прогноза не найден" in gh.inner_text())
        gh.locator("strong").click()
        pg.wait_for_timeout(400)
        check("нет файла: окно не открылось", pg.evaluate(MODAL) == "")

        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()


main()
shutil.rmtree(FIX, ignore_errors=True)
print(f"Итого: {passed} из {passed + failed} прошли" if failed == 0 else f"Итого: {passed} из {passed + failed} прошли (падений: {failed})")
sys.exit(1 if failed else 0)
