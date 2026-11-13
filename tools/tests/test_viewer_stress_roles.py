#!/usr/bin/env python3
"""Вьюер 3.111.0 → шаг 12: роль прогноза на «Действиях» по цепочке ссылок (schema.md §4.6) — настоящий Chromium, клик по реальной строке.

Цепочка: стресс.macro_input → macro-chain/macro-scenarios-*.yaml → forecast_files{фактор: файл прогноза} → прогноз;
«есть новее» — по superseded_by прогноза. Восстановления «по названию» больше нет (decision.md §1: без догадок).
Фикстура stress-roles — живые файлы (стресс 04.10, macro-scenarios-2026-10-04, прогнозы-входы и версии, сценарии).
Контракты:
  1. Стресс с macro_input (поле живёт в стрессе с 04.10), но макросценарии без forecast_files{} (как живые до бэкфилла шага 14): у прогнозов «стресс-тест от 04.10: ссылка на прогнозы не записана»,
     подсказки про перегон нет; сценарии стресса — по scenario_matrix_ref («сценарии стресс-теста от 04.10»); на «Стрессе» — «ссылка на прогнозы не записана».
  2. Со ссылками: ставка ЦБ — «в стрессе версия от 29.07, есть новее (17.09)» (superseded_by 07-29 → 09-17); золото — без версии;
     Brent (открыт 08.10) — «версия от 17.09, есть новее (08.10)»; санкции — superseded_by на файл вне библиотеки — «есть новее (29.10)»;
     brent-dec-2026 — «самостоятельный прогноз»; у входов — подсказка про перегон и плашка «в стресс-тесте».
  3. Карточка стресса: «стресс на прогнозах от … (макросценарии от 04.10), есть новее: …» (R27: имя файла — в подсказке строки).
  4. R20: пробой (factor_breach) по прогнозу стресса — в «Сделать»; «ревью просрочено» — в справочных «К сведению».
  5. Стресс-теста нет — роль не показывается. macro-chain приходит в /api/pv/sync. Ошибок страницы нет.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_stress_roles.py
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
    print("viewer_stress_roles: пропуск — нет playwright")
    sys.exit(0)

sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as hub_api  # noqa: E402

FIX = Path(tempfile.mkdtemp(prefix="srole-"))


def build(linked=False, with_stress=True):
    shutil.rmtree(FIX, ignore_errors=True)
    shutil.copytree(REPO / "tools/tests/fixtures/viewer-live", FIX)
    shutil.copytree(REPO / "tools/tests/fixtures/stress-roles", FIX, dirs_exist_ok=True)
    (FIX / "monitor-reports").mkdir()
    if not with_stress:
        shutil.rmtree(FIX / "Portfolio/stress")
    if linked:   # ссылки шага 14: стресс → макросценарии → прогнозы; родословная прогнозов — superseded_by
        # macro_input уже есть в стрессе (как в живом файле с 04.10) — дописываем только forecast_files{} макросценариям
        mp = FIX / "macro-chain/macro-scenarios-2026-10-04.yaml"
        files = {"brent_price": "brent-price-2026-09-17.yaml", "urals_brent_discount": "urals-brent-discount-2026-09-17.yaml",
                 "usdrub_rate": "usdrub-rate-2026-09-17.yaml", "cnyrub_rate": "cnyrub-rate-2026-09-17.yaml", "inflation_ru": "inflation-ru-2026-09-17.yaml",
                 "cbr_rate": "cbr-rate-2026-2027-2026-07-29.yaml", "budget_deficit_ru": "budget-deficit-ru-2026-09-17.yaml",
                 "xauusd_price": "xauusd-price-2026-2028-2026-09-17.yaml", "sanctions_russia": "sanctions-russia-2026-28-2026-09-17.yaml"}
        mp.write_text("forecast_files:\n" + "".join(f"  {k}: {v}\n" for k, v in files.items()) + mp.read_text(encoding="utf-8"), encoding="utf-8")
        # superseded_by у cbr 07-29 и brent 09-17 уже есть в живых файлах (с расширением и без)
    alerts = [("cbr-rate-2026-2027", "forecast", "forecasts/cbr-rate-2026-2027-2026-09-17.yaml", "/forecast-confidence-applier Обнови прогноз cbr-rate-2026-2027-2026-09-17.yaml"),
              ("brent-price", "forecast", "forecasts/brent-price-2026-10-08.yaml", "/forecast-confidence-applier Обнови прогноз brent-price-2026-10-08.yaml"),
              ("xauusd-price-2026-2028", "forecast", "forecasts/xauusd-price-2026-2028-2026-09-17.yaml", "/forecast-confidence-applier Обнови прогноз xauusd-price-2026-2028-2026-09-17.yaml"),
              ("geopolitics-ru-west", "scenario", "scenarios/scenario-geopolitics-ru-west-2026-07-01.yaml", "/scenario-builder Обнови сценарии scenario-geopolitics-ru-west-2026-07-01.yaml"),
              ("brent-dec-2026", "scenario", "scenarios/scenario-brent-dec-2026-2026-04-30.yaml", "/scenario-builder Обнови сценарии scenario-brent-dec-2026-2026-04-30.yaml"),
              ("sanctions-russia-2026-28", "forecast", "forecasts/sanctions-russia-2026-28-2026-09-17.yaml", "/forecast-confidence-applier Обнови прогноз sanctions-russia-2026-28-2026-09-17.yaml"),
              ("brent-breach", "forecast", "forecasts/brent-price-2026-10-08.yaml", "/forecast-confidence-applier Разбери пробой порога по brent-price")]
    body = "".join(f"""  - severity: HIGH
    category: {'factor_breach' if t == 'brent-breach' else 'stale'}
    target: "{t}"
    target_file: "{f}"
    target_kind: {k}
    message: "Ревью просрочено"
    detected_at: "2026-10-29"
    suggested_action: "{sa}"
""" for t, k, f, sa in alerts)
    (FIX / "monitor-reports/monitor-report-2026-10-29.yaml").write_text(f"""schema_version: 1
type: monitor-report
generated_at: "2026-10-29T15:50:00+03:00"
producer: "forecast-monitor"
horizon_window_days: 7
alerts:
{body}freshness_audit:
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


def role(pg, target):
    loc = row(pg, target).locator(".act-doc-role")
    return loc.text_content().strip() if loc.count() else None   # text_content: строка может лежать в свёрнутом «ещё …»


def role_tag(pg, target):
    """Плашка роли в заголовке строки (3.113): тег после тега важности."""
    tags = row(pg, target).locator(".act-alert-h .tag")
    return [tags.nth(i).text_content().strip() for i in range(tags.count())][1:]


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
    pg.evaluate("() => document.querySelectorAll('#act-info, #act-info details').forEach(d => d.open = true)")   # R20: «ревью просрочено» по прогнозам вне стресса — в справочных «К сведению»
    return browser, pg, errs


def main():
    with sync_playwright() as p:
        try:
            p.chromium.launch().close()
        except Exception as e:
            print(f"viewer_stress_roles: пропуск — {str(e).splitlines()[0][:80]}")
            return

        # 1: стресс без ссылки на макросценарии (живой до бэкфилла шага 14)
        build()
        browser, pg, errs = open_actions(p)
        check("macro-chain/*.yaml пришёл вьюеру (macroScenarios=1) и стресс-тест найден",
              pg.evaluate("() => (state.data.macroScenarios || []).length") == 1 and pg.evaluate("() => !!state.data.stressCurrent"))
        check("PV_DIRS сервера знает macro-chain", any(f == "macro-chain/" for f, _ in hub_api.PV_DIRS))
        for t in ("cbr-rate-2026-2027", "brent-price", "xauusd-price-2026-2028"):
            r = role(pg, t)
            check(f"{t}: без ссылки — «ссылка на прогнозы не записана», без догадки по названию ({r!r})", r == "стресс-тест от 04.10: ссылка на прогнозы не записана")
            check(f"{t}: без ссылки подсказки про перегон нет", row(pg, t).locator(".act-rerun").count() == 0)
        r = role(pg, "geopolitics-ru-west")
        check(f"геополитика: сценарии стресс-теста (scenario_matrix_ref) ({r!r})", r == "сценарии стресс-теста от 04.10")
        pg.evaluate("() => goToTab('scenarios')")
        pg.wait_for_timeout(300)
        ch = pg.evaluate("() => document.querySelector('.stress-chain')?.textContent || ''")
        check("«Стресс»: имя файла макросценариев — в подсказке строки, не в тексте (R27)",
              pg.evaluate("() => document.querySelector('.stress-chain')?.title") == "macro-scenarios-2026-10-04.yaml")
        check(f"«Стресс»: строка цепочки — «ссылка на прогнозы не записана» ({ch!r})", ch == "ссылка на прогнозы не записана")
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # 2–4: со ссылками
        build(linked=True)
        browser, pg, errs = open_actions(p)
        r = role(pg, "cbr-rate-2026-2027")
        check(f"ставка ЦБ: в стрессе 29.07, есть новее по superseded_by (17.09) ({r!r})",
              r == "входит в стресс-тест от 04.10 · фактор: ставка ЦБ · в стрессе версия от 29.07, есть новее (17.09)")
        r = role(pg, "xauusd-price-2026-2028")
        check(f"золото: файл из forecast_files, версия та же ({r!r})", r == "входит в стресс-тест от 04.10 · фактор: золото")
        r = role(pg, "brent-price")
        check(f"Brent (открыт 08.10): в стрессе 17.09, есть новее (08.10) ({r!r})",
              r == "входит в стресс-тест от 04.10 · фактор: Brent · в стрессе версия от 17.09, есть новее (08.10)")
        r = role(pg, "sanctions-russia-2026-28")
        check(f"санкции: superseded_by на файл вне библиотеки — «есть новее (29.10)» ({r!r})",
              r == "входит в стресс-тест от 04.10 · фактор: санкции · в стрессе версия от 17.09, есть новее (29.10)")
        r = role(pg, "brent-dec-2026")
        check(f"brent-dec-2026: самостоятельный прогноз ({r!r})", r == "самостоятельный прогноз")
        for t in ("cbr-rate-2026-2027", "brent-price", "geopolitics-ru-west"):
            h = row(pg, t).locator(".act-rerun")
            check(f"{t}: подсказка про перегон стресса с фразой из справки",
                  h.count() == 1 and "После обновления перегони макро-вход и стресс" in h.inner_text() and "/macro-forecast-chain Обнови макро-прогноз" in h.inner_text() and "/portfolio-scenario-stress Прогони стресс на 6-12-24" in h.inner_text())
        for t in ("cbr-rate-2026-2027", "xauusd-price-2026-2028", "brent-price", "geopolitics-ru-west", "sanctions-russia-2026-28"):
            tg = role_tag(pg, t)
            check(f"{t}: плашка «в стресс-тесте» рядом с важностью ({tg!r})", tg == ["в стресс-тесте"])
        tg = role_tag(pg, "brent-dec-2026")
        check(f"brent-dec-2026: плашка «самостоятельный» ({tg!r})", tg == ["самостоятельный"])
        # R20: пробой по прогнозу стресса — в работе; «ревью просрочено» — в справочных «К сведению»
        top = pg.evaluate("() => [...document.querySelectorAll('#act-do > .act-alert[data-target]')].map(e => e.dataset.target)")
        ref = pg.evaluate("() => [...document.querySelectorAll('#act-info details .act-alert[data-target]')].map(e => e.dataset.target)")
        check(f"R20: пробой Brent (вход стресса) — в «Сделать», «ревью просрочено» прогнозов и сценариев — в справочных «К сведению» ({top} / {ref})",
              top == ["brent-breach"] and all(t in ref for t in ("cbr-rate-2026-2027", "brent-price", "geopolitics-ru-west", "brent-dec-2026")))
        row(pg, "cbr-rate-2026-2027").locator("strong").click()
        pg.wait_for_function("() => { const o = document.querySelector('#modal-overlay'); return o && !o.hidden && document.querySelector('#modal').innerText.includes('Почему монитор просит обновить'); }", timeout=5000)
        txt = pg.evaluate("() => document.querySelector('#modal').innerText")
        check("окно: «В стресс-тесте» со ставкой ЦБ", re.search(r"В стресс-тесте\s+входит в стресс-тест от 04\.10 · фактор: ставка ЦБ", txt) is not None)
        check("окно: подсказка про перегон", "После обновления перегони макро-вход и стресс" in txt)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(400)
        pg.evaluate("() => goToTab('scenarios')")
        pg.wait_for_timeout(300)
        ch = pg.evaluate("() => document.querySelector('.stress-chain')?.textContent || ''")
        check("«Стресс»: имя файла макросценариев — в подсказке строки, не в тексте (R27)",
              pg.evaluate("() => document.querySelector('.stress-chain')?.title") == "macro-scenarios-2026-10-04.yaml")
        check(f"«Стресс»: «стресс на прогнозах от … (макросценарии …), есть новее: …» ({ch!r})",
              ch.startswith("стресс на прогнозах от 29.07–17.09 (макросценарии от 04.10), есть новее:")
              and "Brent (08.10)" in ch and "ставка ЦБ (17.09)" in ch and "санкции (29.10)" in ch)
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        # 7: стресс-теста нет — роли нет
        build(with_stress=False)
        browser, pg, errs = open_actions(p)
        check("нет стресс-теста: роль не показывается, подсказки нет",
              pg.locator("#content .act-doc-role").count() == 0 and pg.locator("#content .act-rerun").count() == 0)
        check("нет стресс-теста: плашки роли нет",
              pg.evaluate("() => [...document.querySelectorAll('#content .act-alert-h .tag')].every(t => !/стресс-тесте|самостоятельный/.test(t.textContent))"))
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()


main()
shutil.rmtree(FIX, ignore_errors=True)
print(f"Итого: {passed} из {passed + failed} прошли" if failed == 0 else f"Итого: {passed} из {passed + failed} прошли (падений: {failed})")
sys.exit(1 if failed else 0)
