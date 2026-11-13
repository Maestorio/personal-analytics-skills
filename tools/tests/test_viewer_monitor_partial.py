#!/usr/bin/env python3
"""Вьюер 3.110.0: частичный прогон монитора не стирает полную картину «Действий» — настоящий Chromium, клик по вкладке.

Дефект 29.10 (владелец): на «Действиях» было 8 предупреждений полного отчёта 26.10; после запуска монитора по одному
файлу (отчёт 29.10, одно предупреждение) вьюер взял самый свежий отчёт и показал только его — остальные пропали.

Контракты (скрипт mergeMonitorReports во вьюере; живые отчёты 26.10-v2 и 29.10 лежат в fixtures/monitor-live):
  1. Живые отчёты: пункты «Сделать» и справочные «К сведению» = 5 HIGH + 4 MEDIUM ждут, справочный LOW по cpi-yoy-ocr-2026 (заменил MEDIUM полного),
     в «Сделано» ровно два — ai-capex-slowdown-2026 и sanctions-russia-2026-28 (владелец обновил их 29.10).
  2. Шапка: «монитор 26.10 · частично обновлён 29.10 (1 файл)».
  3. Полный из 8 + частичный по другому файлу с одним предупреждением → 9 пунктов (8+1).
  4. Файл из checked частичного без предупреждения → пункт исчезает, остальные остаются.
  5. Частичный без scope, но с оговоркой «Запуск по одному файлу (тема)» → тот же результат (обратная совместимость);
     полный без scope и без оговорки (обычный отчёт) заменяет картину целиком, как раньше.
  6. «Сделано»: новый файл темы ≥ даты отчёта → пункт в «Сделано»; клик открывает самый свежий файл темы,
     в сводке «Обновлён ДД.ММ (было: <старый файл>)», а у ожидающего — файл, названный в предупреждении.
  7. Ошибок страницы нет.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_monitor_partial.py
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
    print("viewer_monitor_partial: пропуск — нет playwright")
    sys.exit(0)

sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as hub_api  # noqa: E402

LIVE = REPO / "tools/tests/fixtures/monitor-live"


def fixture():
    fix = Path(tempfile.mkdtemp(prefix="mpart-"))
    shutil.copytree(REPO / "tools/tests/fixtures/viewer-live", fix, dirs_exist_ok=True)
    for d in ("monitor-reports", "forecasts", "scenarios"):
        (fix / d).mkdir(exist_ok=True)
    return fix


def forecast(fix, name, date, kind="forecast", md=False):
    folder = "scenarios" if kind == "scenario" else "forecasts"
    core = "matrix" if kind == "scenario" else "forecast"
    (fix / folder / name).write_text(f"""schema_version: 1
type: {'scenario-events' if kind == 'scenario' else 'forecast-events'}
status: active
{core}:
  date: {date}
  horizon: 2028-12-31
reviews:
  next_due: 2026-12-01
""", encoding="utf-8")
    if md:
        (fix / folder / name.replace(".yaml", ".md")).write_text(f"---\nschema_version: 1\nforecast_date: {date}\n---\n\n# Прогноз {date}\n\nТЕКСТ-{date}\n", encoding="utf-8")


def alert(target, file, sev="HIGH", cat="stale", kind="forecast", day="2026-10-26"):
    return f"""  - severity: {sev}
    category: {cat}
    target: "{target}"
    target_file: "{file}"
    target_kind: {kind}
    message: "сообщение {target}"
    detected_at: "{day}"
    suggested_action: "/forecast-confidence-applier Обнови прогноз {file.split('/')[-1]}"
"""


def report(day, alerts, head="", caveats=""):
    return f"""schema_version: 1
type: monitor-report
generated_at: "{day}T12:00:00+03:00"
producer: "forecast-monitor"
horizon_window_days: 7
{head}alerts:
{''.join(alerts) if alerts else '  []' + chr(10)}freshness_audit:
  integrated_view: {{ age_days: 3, due_for_refresh: false }}
predictions:
  total_active: 1
  overdue_count: 0
  due_30d_count: 0
  overdue_list: []
condition_events: []
outcome_log_updates: []
{caveats}"""


class Handler(BaseHTTPRequestHandler):
    fix = None

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        have = json.loads(self.rfile.read(n) or b"{}").get("have") or {}
        if _up(self.path).path != "/api/pv/sync":
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        body = json.dumps(hub_api.pv_sync(str(self.server.fix), have)).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = _unq(_up(self.path).path)
        f = REPO / "tools" / p[len("/tools/"):] if p.startswith("/tools/") else self.server.fix / p.lstrip("/")
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


MODAL = "() => { const m = document.querySelector('#modal'); const o = document.querySelector('#modal-overlay'); return o && !o.hidden && m ? m.innerText : ''; }"
errs = []


def open_actions(browser, fix):
    srv = serve(Handler)[0]   # _pages_stand: новый сервер на вызов, очередь 128, keep-alive
    srv.fix = fix
    ctx = browser.new_context(service_workers="block", viewport={"width": 1400, "height": 1000})
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "502" not in m.text and "404" not in m.text else None)
    pg.route("**/api/pv/plan*", lambda r: r.fulfill(status=502, body="{}"))
    pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, body="{}"))
    pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/tools/portfolio-integrated-viewer.html")
    pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
    pg.wait_for_function("() => state.data && state.data.portfolioLatest && state.data.monitorReport", timeout=20000)
    # реальная вкладка «Действия»
    pg.locator('#tabs .ui-tab', has_text="Действия").first.click()
    pg.wait_for_selector("#content #act-head", timeout=10000)
    return pg, ctx, srv


def targets(pg, sel):
    return pg.evaluate("(s) => [...document.querySelectorAll(s)].map(e => e.dataset.target)", sel)


PENDING = "#content #act-do .act-alert[data-target], #content #act-info .act-alert[data-target]"   # «Сделать» + справочные «К сведению»
DONE = "#content #act-done .act-alert[data-target]"


def main():
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            print(f"viewer_monitor_partial: пропуск — {str(e).splitlines()[0][:80]}")
            return

        # ---- 1-2. живые отчёты 26.10-v2 + 29.10 ----
        fix = fixture()
        for f in LIVE.glob("monitor-report-*.yaml"):
            shutil.copy(f, fix / "monitor-reports" / f.name)
        base = __import__("re").findall(r'target_file: "([^"]+)"', (LIVE / "monitor-report-2026-10-26-v2.yaml").read_text(encoding="utf-8"))
        for tf in dict.fromkeys(base):
            forecast(fix, tf.split("/")[-1], "2026-07-01", "scenario" if tf.startswith("scenarios/") else "forecast")
        forecast(fix, "ai-capex-slowdown-2026-2026-10-29.yaml", "2026-10-29", md=True)   # обновил владелец 29.10
        forecast(fix, "sanctions-russia-2026-28-2026-10-29.yaml", "2026-10-29")
        pg, ctx, srv = open_actions(browser, fix)
        pend = targets(pg, PENDING)
        pg.locator("#act-done > summary").first.click()
        pg.wait_for_timeout(200)
        done = targets(pg, DONE)
        check(f"живые: ждут 9 (5 HIGH + 4 MEDIUM) + справочный LOW cpi-yoy-ocr-2026 ({len(pend)}: {pend})",
              len(pend) == 10 and pend[-1] == "cpi-yoy-ocr-2026" and pend[:9] == [t for t in pend[:9] if t != "cpi-yoy-ocr-2026"])
        check("живые: cpi-yoy-ocr-2026 — LOW 29.10 вместо MEDIUM 26.10",
              pg.evaluate("() => (state.data.monitorReport.parsed.alerts.filter(a => a.target === 'cpi-yoy-ocr-2026').map(a => a.severity + a._mrDate))") == ["LOW2026-10-29"])
        check(f"живые: в «Сделано» ровно ai-capex-slowdown-2026 и sanctions-russia-2026-28 ({done})",
              sorted(set(done)) == ["ai-capex-slowdown-2026", "sanctions-russia-2026-28"])
        check("живые: все 12 предупреждений на месте (11 + 1 LOW вместо MEDIUM)", pg.evaluate("() => state.data.monitorReport.parsed.alerts.length") == 12)
        check("живые: HIGH ждут 5 — cbr, ai-capex-scenarios, brent, geopolitics, usd-rub",
              pg.evaluate("() => state.data.monitorReport.parsed.alerts.filter(a => a.severity === 'HIGH' && !monitorAlertDone(a, state.data.monitorReport.date)).map(a => a.target).sort()")
              == ["ai-capex-scenarios-2026", "brent-dec-2026", "cbr-rate-2026-2027", "geopolitics-ru-west", "usd-rub-sept-2026"])
        tile = pg.locator("#content #act-head").inner_text()
        check(f"шапка плитки: «монитор 26.10 · частично обновлён 29.10 (1 файл)» ({tile!r})", "монитор 26.10 · частично обновлён 29.10 (1 файл)" in tile)
        check("шапка: цель вкладки и источник пишут то же", pg.evaluate("() => monitorLabel()") == "монитор 26.10 · частично обновлён 29.10 (1 файл)")
        # 6. «Сделано» открывает самый свежий файл темы
        pg.locator('#act-done .act-alert[data-target="ai-capex-slowdown-2026"] strong').click()
        pg.wait_for_function(f"() => ({MODAL})().includes('Почему монитор просит обновить')", timeout=5000)
        txt = pg.evaluate(MODAL)
        check("сделано: открыт файл 29.10, не названный в предупреждении 30.04", "ai-capex-slowdown-2026-2026-10-29.yaml" in txt and "ТЕКСТ-2026-10-29" in txt)
        check("сделано: «Обновлён 29.10 (было: ai-capex-slowdown-2026-2026-04-30.yaml)»", "29.10 (было: ai-capex-slowdown-2026-2026-04-30.yaml)" in txt)
        check("сделано: в окне «Сделано: новый файл …»", "Сделано: новый файл" in txt)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(400)
        # ожидающий открывает названный файл (R20: «ревью просрочено» по прогнозу вне стресса — в справочных «К сведению»)
        pg.evaluate("() => document.querySelectorAll('#act-info, #act-info details').forEach(d => d.open = true)")
        pg.locator('#act-info .act-alert[data-target="cbr-rate-2026-2027"] strong').click()
        pg.wait_for_function(f"() => ({MODAL})().includes('Почему монитор просит обновить')", timeout=5000)
        txt = pg.evaluate(MODAL)
        check("ожидающий: файл из предупреждения, без «Обновлён»", "cbr-rate-2026-2027-2026-09-17.yaml" in txt and "Обновлён" not in txt)
        ctx.close(); srv.shutdown(); shutil.rmtree(fix, ignore_errors=True)

        # ---- синтетика: 8 полных + частичные ----
        topics = [f"t{i}" for i in range(1, 9)]

        def synth(partial_text, extra_forecasts=()):
            fx = fixture()
            for t in topics + ["t9"]:
                forecast(fx, f"{t}-2026-04-30.yaml", "2026-04-30")
            for name, date in extra_forecasts:
                forecast(fx, name, date)
            (fx / "monitor-reports/monitor-report-2026-10-26.yaml").write_text(
                report("2026-10-26", [alert(t, f"forecasts/{t}-2026-04-30.yaml") for t in topics]), encoding="utf-8")
            (fx / "monitor-reports/monitor-report-2026-10-29.yaml").write_text(partial_text, encoding="utf-8")
            return fx

        # 3. 8 + 1
        fx = synth(report("2026-10-29", [alert("t9", "forecasts/t9-2026-04-30.yaml", day="2026-10-29")],
                          head='scope: partial\nchecked: ["forecasts/t9-2026-04-30.yaml"]\n'))
        pg, ctx, srv = open_actions(browser, fx)
        got = sorted(targets(pg, PENDING))
        check(f"8 полных + 1 частичный по другому файлу → 9 ({got})", got == sorted(topics + ["t9"]))
        check("сведённый список: 9 предупреждений в отчёте", pg.evaluate("() => state.data.monitorReport.parsed.alerts.length") == 9)
        check("R20: «ревью просрочено» по прогнозам вне стресса в «важное» не входит (actionCounts().high = 0)", pg.evaluate("() => actionCounts().high") == 0)
        ctx.close(); srv.shutdown(); shutil.rmtree(fx, ignore_errors=True)

        # 4. файл из checked без предупреждения — пункт исчезает
        fx = synth(report("2026-10-29", [], head='scope: partial\nchecked: ["forecasts/t3-2026-04-30.yaml"]\n'))
        pg, ctx, srv = open_actions(browser, fx)
        got = sorted(targets(pg, PENDING))
        check(f"checked без алерта: t3 исчез, остальные 7 на месте ({got})", got == sorted(t for t in topics if t != "t3"))
        ctx.close(); srv.shutdown(); shutil.rmtree(fx, ignore_errors=True)

        # 5. без scope, но с оговоркой — тоже частичный
        fx = synth(report("2026-10-29", [], caveats='caveats:\n  - { severity: INFO, message: "Запуск по одному файлу (t5): остальные прогнозы не проверялись" }\n'))
        pg, ctx, srv = open_actions(browser, fx)
        got = sorted(targets(pg, PENDING))
        check(f"без scope + «Запуск по одному файлу (t5)»: t5 исчез, 7 остались ({got})", got == sorted(t for t in topics if t != "t5"))
        ctx.close(); srv.shutdown(); shutil.rmtree(fx, ignore_errors=True)

        # 5b. обычный отчёт без scope — полный, заменяет картину
        fx = synth(report("2026-10-29", [alert("t9", "forecasts/t9-2026-04-30.yaml", day="2026-10-29")]))
        pg, ctx, srv = open_actions(browser, fx)
        got = sorted(targets(pg, PENDING))
        check(f"без scope и без оговорки — полный: остаётся один t9 ({got})", got == ["t9"])
        ctx.close(); srv.shutdown(); shutil.rmtree(fx, ignore_errors=True)

        # 6. новый файл темы → «Сделано»; частичный по другому файлу
        fx = synth(report("2026-10-29", [alert("t9", "forecasts/t9-2026-04-30.yaml", day="2026-10-29")],
                          head='scope: partial\nchecked: ["forecasts/t9-2026-04-30.yaml"]\n'),
                   extra_forecasts=[("t5-2026-10-28.yaml", "2026-10-28")])
        pg, ctx, srv = open_actions(browser, fx)
        check("новый файл темы t5 → в «Сделано», ждут 8 из 9", targets(pg, PENDING) and sorted(targets(pg, PENDING)) == sorted(t for t in topics + ["t9"] if t != "t5"))
        pg.locator("#act-done > summary").first.click()
        pg.wait_for_timeout(200)
        check(f"«Сделано» = t5 ({targets(pg, DONE)})", targets(pg, DONE) == ["t5"])
        ctx.close(); srv.shutdown(); shutil.rmtree(fx, ignore_errors=True)

        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()


main()
print(f"Итого: {passed} из {passed + failed} прошли" if failed == 0 else f"Итого: {passed} из {passed + failed} прошли (падений: {failed})")
sys.exit(1 if failed else 0)
