#!/usr/bin/env python3
"""Сквозная проверка кабинета на НАСТОЯЩЕЙ связке (2026-10-23): Caddy с Caddyfile (рабочим, если есть, иначе
примером) + hub-api (tools/hosting/api/server.py отдельным процессом, тома как в docker-compose) + браузер.

То, что прочие тесты проверяют по частям на подменных серверах, здесь — вместе, как на NAS:
  1. зоны: _nas/ — 404 и с паролем; без пароля приватное — 403; страницы — 200;
  2. вход через login.html настоящей формой (пароль → токен → возврат);
  3. вьюер с паролем грузится ОДНИМ запросом /api/pv/sync через Caddy (via = sync), разделы на месте;
  4. «Здоровье» читает аптечку через /api/hd/file с паролем; /api/health — pv_sync, fs_mode local;
  5. хаб: фоновый скрипт, оболочки всех страниц, прогрев (uiOfflineWarm);
  6. Caddy остановлен (NAS недоступен): хаб, вьюер, еда, путешествия, здоровье — открываются, данные из
     копии, плашка «нет связи»; отметка «куплено» — в очереди;
  7. Caddy снова поднят: очередь ушла через настоящий save_file (base_hash), файл на диске изменился,
     копия прежней версии — в .versions/; «Обновить» — свежие данные без плашки;
  3б. шаг 12: кнопка «не актуально» у сработавшего условия → POST /api/pv/cond/event через Caddy → событие owner_mark dismissed
      (с version, by owner) в conditions-state.json на диске, строка уходит из «Решений» без синка; событие уведомителя
      (внутренний маршрут) приходит хвостом GET /api/pv/cond/state?since= — условие появляется в «Решениях» без перезагрузки;
  8. ошибок JS нет.
Нужны caddy в PATH и playwright + chromium; чего-то нет — честный пропуск.
Запуск: python3 tools/tests/test_stack_e2e.py
"""
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
FIX = REPO / "tools/tests/fixtures/viewer-live"
passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name} {extra}")


caddy = shutil.which("caddy") or shutil.which("/opt/homebrew/bin/caddy")
if not caddy:
    print("stack_e2e: пропуск — нет caddy (brew install caddy)")
    sys.exit(0)
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("stack_e2e: пропуск — нет playwright")
    sys.exit(0)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PASSWORD = "stack-e2e"
TOKEN = base64.b64encode(f"hubuser:{PASSWORD}".encode()).decode()
TMP = Path(tempfile.mkdtemp(prefix="stack-e2e-"))
SRV = TMP / "srv"                                   # = /volume1/homes/hubuser/Claude-Memory
shutil.copytree(FIX, SRV, dirs_exist_ok=True)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from viewer_ds import cond as _cond, dec as _dec, ev as _ev, write_conditions, write_decisions  # noqa: E402
# шаг 12: носители формата 2 — два условия по SBER (сработавшее «ждёт владельца» и ждущее порога), одно решение
write_conditions(SRV, [_cond("e2e-px", "SBER", "price_above", 1, kind="trade", on_verdict="TRIM", action="set_verdict", text="E2E-СРЕЗ"),
                       _cond("e2e-later", "SBER", "price_above", 999999, kind="trade", on_verdict="TRIM", action="set_verdict", text="E2E-ПОТОМ")],
                 [_ev("e2e-px", "fired", "2026-10-30T10:00:00+03:00", version=1)])
write_decisions(SRV, [_dec("SBER", "HOLD", "2026-10-20T12:00:00+03:00")])
os.symlink(REPO / "tools", SRV / "tools")
(SRV / "_nas").mkdir()
(SRV / "_nas/.env").write_text("HUB_API_DSM_PASSWORD=secret\n", encoding="utf-8")
FOOD, HEALTH = SRV / "Food", SRV / "Health"
(FOOD / "recipes").mkdir(parents=True)
(FOOD / "products.json").write_text(json.dumps({"schema": "food-products@1", "updated": "2026-10-23", "products": [
    {"id": "muka", "name": "Мука", "unit": "г", "category": "бакалея"}]}, ensure_ascii=False), encoding="utf-8")
(FOOD / "shopping.json").write_text(json.dumps({"schema": "food-shopping@1", "updated": "2026-10-23", "items": [
    {"id": "i1", "name": "Хлеб-стек", "qty": 1, "unit": "шт", "bought": False}]}, ensure_ascii=False), encoding="utf-8")
HEALTH.mkdir()
(HEALTH / "labs.json").write_text(json.dumps({"schema": "health-labs@1", "markers": []}), encoding="utf-8")
(HEALTH / "meds.json").write_text(json.dumps({"schema": "health-meds@1", "meds": [
    {"id": "m1", "name": "Витамин-стек"}]}, ensure_ascii=False), encoding="utf-8")
for _n, _d in (("vaccinations", {"schema": "health-vaccinations@1", "vaccinations": []}),
               ("vitals", {"schema": "health-vitals@1", "height_cm": None, "weight": []}),
               ("studies", {"schema": "health-studies@1", "studies": []})):
    (HEALTH / f"{_n}.json").write_text(json.dumps(_d), encoding="utf-8")
TRIP = SRV / "travel-planner/trips/altai_2027"
TRIP.mkdir(parents=True)
(TRIP / "trip.yaml").write_text("title: Алтай-стек\n", encoding="utf-8")
(TRIP / "5_final_plan_v1.md").write_text("# План\nДень 1\n", encoding="utf-8")

API_PORT, PORT = free_port(), free_port()
env = dict(os.environ, HUB_API_ROOT=str(SRV), HUB_API_HEALTH_ROOT=str(HEALTH), HUB_API_FOOD_ROOT=str(FOOD),
           HUB_API_PORT=str(API_PORT), HUB_API_CHOWN_UID=str(os.getuid()), HUB_API_CHOWN_GID=str(os.getgid()))
for k in ("HUB_API_DSM_URL", "HUB_API_DSM_ACCOUNT", "HUB_API_DSM_PASSWORD"):
    env.pop(k, None)
api = subprocess.Popen([sys.executable, str(REPO / "tools/hosting/api/server.py")], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

src = REPO / "tools/hosting/Caddyfile"
src = src if src.exists() else REPO / "tools/hosting/Caddyfile.example"
hashed = subprocess.run([caddy, "hash-password", "--plaintext", PASSWORD], capture_output=True, text=True).stdout.strip()
cfg = src.read_text(encoding="utf-8")
cfg = re.sub(r"\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}|<BCRYPT_HASH_HERE>", lambda m: hashed, cfg)
cfg = cfg.replace("<VPN_IP>", "10.8.0.2").replace("<HOST>", "portfolio.example.org").replace("<BASE_DOMAIN>", "example.org")
cfg = cfg.replace(":8080 {", f":{PORT} {{", 1)
cfg = cfg.replace("root * /srv-health", f"root * {HEALTH}").replace("root * /srv-food", f"root * {FOOD}")
cfg = cfg.replace("root * /srv", f"root * {SRV}", 1)
cfg = cfg.replace("hub-api:8000", f"127.0.0.1:{API_PORT}").replace("hub-notify:8001", "127.0.0.1:9")
cfg = re.sub(r"^\s*redir @http_external .*$", "", cfg, flags=re.M)
CFG = TMP / "Caddyfile"
CFG.write_text(cfg, encoding="utf-8")
BASE = f"http://127.0.0.1:{PORT}"
T = BASE + "/tools/"
_caddy = {"p": None}


def code(path, auth=None):
    rq = urllib.request.Request(BASE + path, headers={"Authorization": "Basic " + auth} if auth else {})
    try:
        with urllib.request.urlopen(rq, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001
        return 0


def caddy_up():
    _caddy["p"] = subprocess.Popen([caddy, "run", "--config", str(CFG), "--adapter", "caddyfile"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(80):
        if code("/tools/hub.html") == 200 and code("/api/health") in (200,):
            return True
        time.sleep(0.25)
    return False


def caddy_down():
    p = _caddy["p"]
    if p:
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:  # noqa: BLE001
            p.kill()
    _caddy["p"] = None
    time.sleep(0.3)


BANNER = "() => { const b = document.getElementById('ui-offline'); return b && !b.hidden ? b.textContent : ''; }"
HAS = "(t) => document.body.innerText.includes(t)"


def main():
    try:
        if not caddy_up():
            check("Caddy и hub-api поднялись", False)
            return 1
        # 1. зоны
        check("1: /_nas/.env с паролем — 404", code("/_nas/.env", TOKEN) == 404)
        check("1: портфель без пароля — 403", code("/Portfolio/snapshots/") == 403)
        check("1: страницы и фоновый скрипт — 200",
              all(code(p) == 200 for p in ("/tools/hub.html", "/tools/portfolio-integrated-viewer.html", "/tools/sw.js",
                                           "/tools/sw-offline.js", "/tools/food.html")))
        with urllib.request.urlopen(BASE + "/api/health", timeout=5) as r:
            h = json.loads(r.read())
        check("4: /api/health через Caddy — pv_sync, fs_mode local, сбоев нет",
              h.get("pv_sync") is True and h.get("fs_mode") == "local" and h.get("fs_fallbacks") == 0, str(h)[:200])

        with sync_playwright() as p:
            try:
                br = p.chromium.launch()
            except Exception:  # noqa: BLE001
                print("stack_e2e: пропуск — нет chromium")
                return 0
            ctx = br.new_context(viewport={"width": 390, "height": 860}, is_mobile=True, has_touch=True)
            ctx.add_init_script("window.UI_OFFLINE_TEST = true;")
            pg = ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))

            # 2. вход настоящей формой
            pg.goto(T + "login.html?why=portfolio&next=" + "/tools/portfolio-integrated-viewer.html")
            pg.fill("#pass", PASSWORD)
            with pg.expect_navigation(timeout=15000):
                pg.click("#go")
            check("2: вход по паролю — токен сохранён, возврат во вьюер",
                  pg.evaluate("() => localStorage.getItem('hub-auth')") == TOKEN and "portfolio-integrated-viewer" in pg.url)

            # 3. вьюер одним запросом через Caddy + hub-api
            pg.wait_for_selector("#tabs .ui-tab", timeout=30000)
            st = pg.evaluate("() => state.netStats")
            check(f"3: вьюер — одним запросом /api/pv/sync через Caddy ({st})",
                  st and st["via"] == "sync" and st["files"] > 0 and st["fromSync"] == st["files"])
            tabs = pg.evaluate("() => document.querySelectorAll('#tabs .ui-tab').length")

            # 3б. кнопки условий → события на сервере; хвост состояния между синками
            pg.evaluate("() => goToTab('actions')")
            pg.wait_for_selector('.act-dec[data-cond="e2e-px"] [data-cond-act="dismissed"]', timeout=10000)
            n0 = pg.evaluate("() => state.netStats.files")
            pg.click('.act-dec[data-cond="e2e-px"] [data-cond-act="dismissed"]')
            pg.wait_for_function("() => !document.querySelector('.act-dec[data-cond=\"e2e-px\"]')", timeout=10000)
            evs = json.loads((SRV / "Portfolio/conditions-state.json").read_text(encoding="utf-8"))["events"]
            last = evs[-1]
            check(f"3б: «не актуально» — owner_mark dismissed с version и by owner на диске ({last})",
                  last["condition_id"] == "e2e-px" and last["event"] == "owner_mark" and last.get("version") == 1
                  and last["by"] == "owner" and last["data"] == {"mark": "dismissed"} and re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+03:00$", last["at"]))
            check("3б: строка ушла без синка (локальное состояние пересчитано)",
                  pg.evaluate("() => dsCondRows().find(r => r.id === 'e2e-px').status") == "done" and pg.evaluate("() => state.netStats.files") == n0)
            req = urllib.request.Request(f"http://127.0.0.1:{API_PORT}/api/pv/cond/event/internal", method="POST",
                                         data=json.dumps({"condition_id": "e2e-later", "version": 1, "event": "fired", "by": "notifier", "data": {"price": 1}}).encode(),
                                         headers={"Content-Type": "application/json", "Authorization": "Basic " + TOKEN})
            with urllib.request.urlopen(req, timeout=10) as r_:
                body_ = json.loads(r_.read() or b"{}")
                check(f"3б: событие уведомителя записано внутренним маршрутом ({body_})", r_.status == 200 and body_.get("event", {}).get("condition_id") == "e2e-later")
            got = pg.evaluate("() => condStateRefresh().then(n => { renderTabContent({ fade: false }); return n; })")
            pg.wait_for_selector('.act-dec[data-cond="e2e-later"]', timeout=10000)
            check(f"3б: хвост cond/state?since= (последнее время − 1 с, повторы отсекаются) принёс одно новое событие, условие ждёт владельца без перезагрузки ({got})",
                  got == 1 and pg.evaluate("() => dsCondRows().find(r => r.id === 'e2e-later').waits_owner") is True)

            # 4. «Здоровье» с паролем через /api/hd/file
            pg.goto(T + "health.html")
            pg.wait_for_load_state("load")
            pg.wait_for_timeout(2500)
            check("4: «Здоровье» — живые данные загрузились (нет «не загрузилось»)",
                  "не загрузил" not in pg.evaluate("() => document.body.innerText"))
            pg.get_by_text("Аптечка", exact=True).last.click()
            try:
                pg.wait_for_function(HAS, arg="Витамин-стек", timeout=10000)
                ok = True
            except Exception:  # noqa: BLE001
                ok = False
            check("4: «Здоровье» читает аптечку с паролем (hub-api /api/hd/file)", ok,
                  pg.evaluate("() => document.body.innerText")[:200])

            # 5. хаб: фоновый скрипт, оболочки, прогрев
            pg.goto(T + "hub.html")
            pg.wait_for_function("navigator.serviceWorker && navigator.serviceWorker.controller", timeout=20000)
            for _ in range(80):
                keys = pg.evaluate("async () => (await (await caches.open('cab-shell-v1')).keys()).map(r => r.url)")
                if sum(k.endswith(x) for k in keys for x in ("/hub.html", "/food.html", "/travel.html", "/health.html",
                                                              "/portfolio-integrated-viewer.html")) >= 5:
                    break
                time.sleep(0.25)
            check("5: оболочки страниц на устройстве", sum(k.endswith(x) for k in keys for x in (
                "/hub.html", "/food.html", "/travel.html", "/health.html", "/portfolio-integrated-viewer.html")) >= 5)
            check("5: прогрев из хаба прошёл", pg.evaluate("() => uiOfflineWarm(true)") is True)

            # 6. NAS недоступен
            caddy_down()
            check("6: Caddy остановлен", code("/tools/hub.html") == 0)
            for page, want in (("hub.html", None), ("portfolio-integrated-viewer.html", None), ("food.html", "Хлеб-стек"),
                               ("travel.html", "Алтай-стек")):
                pg.goto(T + page)
                pg.wait_for_load_state("load")
                if page == "portfolio-integrated-viewer.html":
                    pg.wait_for_selector("#tabs .ui-tab", timeout=30000)
                    ok = pg.evaluate("() => document.querySelectorAll('#tabs .ui-tab').length") == tabs
                elif want:
                    try:
                        pg.wait_for_function(HAS, arg=want, timeout=15000)
                        ok = True
                    except Exception:  # noqa: BLE001
                        ok = False
                else:
                    ok = pg.evaluate("() => !/ещё не сохранена/.test(document.body.innerText) && !!document.querySelector('.ui-top, header')")
                check(f"6: без связи — {page} открывается с данными", ok)
            pg.goto(T + "food.html")
            pg.wait_for_function(HAS, arg="Хлеб-стек", timeout=15000)
            try:
                pg.wait_for_function(BANNER, timeout=10000)
            except Exception:  # noqa: BLE001
                pass
            check("6: плашка «нет связи» с датой", "Нет связи" in pg.evaluate(BANNER))
            pg.click('[data-act="bought"][data-arg="i1"]')
            pg.wait_for_function(HAS, arg="сохранены на телефоне", timeout=10000)
            check("6: отметка «куплено» — в очереди на телефоне",
                  "shopping" in pg.evaluate("() => JSON.parse(localStorage.getItem('food-outbox') || '{}')"))

            # 7. NAS снова доступен
            check("7: Caddy поднят снова", caddy_up())
            pg.evaluate("() => window.dispatchEvent(new Event('online'))")
            pg.wait_for_function(HAS, arg="Изменения без связи отправлены", timeout=20000)
            items = json.loads((FOOD / "shopping.json").read_text(encoding="utf-8"))["items"]
            check("7: очередь ушла через настоящий save_file — на диске «куплено»", items[0]["bought"] is True)
            vers = list((FOOD / ".versions").glob("*_shopping.json")) if (FOOD / ".versions").exists() else []
            check(f"7: прежняя версия — в .versions/ ({len(vers)})", len(vers) == 1)
            pg.goto(T + "portfolio-integrated-viewer.html")
            pg.wait_for_selector("#tabs .ui-tab", timeout=30000)
            pg.wait_for_timeout(500)
            check("7: связь есть — вьюер снова одним запросом, плашки нет",
                  pg.evaluate("() => state.netStats.via") == "sync" and pg.evaluate(BANNER) == "")
            check("8: ошибок JS нет", not errs, str(errs[:3]))
            br.close()
    finally:
        caddy_down()
        api.terminate()
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"stack_e2e: {passed} OK, {failed} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
