#!/usr/bin/env python3
"""Офлайн кабинета (ui-kit 1.54.0, фоновые скрипты sw.js / portfolio-sw.js + ядро sw-offline.js, 2026-10-23).

Решение владельца: приложение «Кабинет» (хаб, оттуда — все страницы) должно открываться без связи; отчёты
в свободной форме офлайн не держим. Сервер теста — «как Caddy» (публичное / приватное по Authorization,
/health-data/ и /Food/ со своих корней, /api/fd|hd/file, листинги JSON); «NAS недоступен» — сервер рвёт
соединения на всё (честнее эмуляции сети браузера: та может не касаться запросов фонового скрипта).
Контракты:
  1. после первого открытия хаба оболочки ВСЕХ страниц на устройстве (и тех, что не открывали);
  2. NAS недоступен: хаб, еда, вьюер, путешествия, здоровье, деньги, игры, вход — открываются из кеша;
  3. данные «Еды» и вьюера без связи — из копии, плашка «Нет связи — показаны данные … (от …)»;
  4. что не держим (Portfolio/reports/) — без связи недоступно, а не показано старым;
  5. приватная копия привязана к паролю: другой токен или без токена — не отдаётся; «Выйти» (cab-logout) —
     приватная копия стёрта, публичная — нет;
  6. связь есть — свежие данные (сначала сеть), плашки нет; 404 запоминается — без связи тот же 404;
  7. новая версия ассета (?v=) вытесняет прежнюю; 8. ошибок JS нет;
  9. прогрев из хаба (uiOfflineWarm): свежее устройство открыло только хаб — без связи еда, путешествия,
     здоровье, деньги, игры показывают то же, что при связи; раньше 6 ч повторно не греет;
 10. «Еда» без связи (food 1.38): отметка «куплено» — в очереди на телефоне, после перезагрузки без связи
     своя версия; связь вернулась — отправлена; файл успели изменить (409) — слияние, чужое не затёрто.
 16. прошлая версия ассета (ядро 1.3.0, 2026-10-29; случай: сеть не успела за 4 с — страница получила старый
     viewer.js под новым ?v=): медленная сеть (дольше 4 с, короче предела) — НОВАЯ версия, сообщения нет;
     быстрая — новая; сеть молчит дольше предела или связи нет — прежняя версия + cab-stale и один тост
     «Открыта прошлая версия страницы … Обновить» (кнопка перезагружает); предел в исходнике — 20 с.
 15. сеть висит, а не рвётся (телефон без связи, 2026-10-26: еда 10 с, вьюер не открылся за 40 с): после
     первого таймаута фоновый скрипт сеть почти не ждёт — страницы за 1–2 с, вьюер — копия с устройства,
     живые цены не запрашиваются; запись — в очередь, а не «сохраняю…» без конца.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_offline.py
"""
import base64
import hashlib
import json
import re
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote as _q, unquote as _unq, urlparse as _up

REPO = Path(__file__).resolve().parent.parent.parent
FIX = REPO / "tools/tests/fixtures/viewer-live"
sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as hub_api  # noqa: E402

passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name} {extra}")


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("offline: пропуск — нет playwright")
    sys.exit(0)

ROOT = Path(tempfile.mkdtemp())
shutil.copytree(FIX, ROOT, dirs_exist_ok=True)
(ROOT / "Portfolio/reports").mkdir(parents=True, exist_ok=True)
(ROOT / "Portfolio/reports/2026-10-01-заметка.md").write_text("---\ntitle: отчёт\n---\nтекст\n", encoding="utf-8")
FOOD = ROOT / "Food"
(FOOD / "recipes").mkdir(parents=True)
(FOOD / "products.json").write_text(json.dumps({"schema": "food-products@1", "products": [
    {"id": "muka", "name": "Мука", "unit": "г", "category": "бакалея"}]}, ensure_ascii=False), encoding="utf-8")
SHOP = {"schema": "food-shopping@1", "updated": "2026-10-23", "items": [
    {"id": "i1", "product_id": "muka", "name": "Мука", "qty": 1000, "unit": "г", "bought": False}]}
(FOOD / "shopping.json").write_text(json.dumps(SHOP, ensure_ascii=False), encoding="utf-8")
(FOOD / "recipes/blin.json").write_text(json.dumps({"schema": "food-recipe@1", "title": "Блины", "servings": 2,
    "ingredients": [{"name": "Мука", "product_id": "muka", "qty": 200, "unit": "г"}],
    "steps": [{"title": "Шаг 1", "text": "Смешать."}]}, ensure_ascii=False), encoding="utf-8")
(ROOT / "Health").mkdir()
(ROOT / "Health/labs.json").write_text(json.dumps({"schema": "health-labs@1", "markers": []}), encoding="utf-8")
(ROOT / "Health/reports").mkdir()
VITALS0 = {"schema": "health-vitals@1", "updated": "2026-10-01", "height_cm": 180, "weight": [{"date": "2026-10-01", "kg": 80}]}
(ROOT / "Health/vitals.json").write_text(json.dumps(VITALS0), encoding="utf-8")
(ROOT / "Health/reports/2026-10-01-otchet.md").write_text("# Отчёт-офлайн\n\nТекст отчёта.\n", encoding="utf-8")
for d in ("travel-planner/trips", "travel-planner/profiles", "Gaming", "ZenMoney/audit", "macro-snapshots"):
    (ROOT / d).mkdir(parents=True, exist_ok=True)
(ROOT / "Gaming/recommendations").mkdir(parents=True, exist_ok=True)
(ROOT / "Gaming/recommendations/2026-10-10-podborka.md").write_text(
    "# Подборка-офлайн\n\n## 1. Игра-офлайн\n\nТекст подборки.\n", encoding="utf-8")
TRIP = ROOT / "travel-planner/trips/kazakhstan_2027"
TRIP.mkdir(parents=True)
(TRIP / "trip.yaml").write_text("title: Казахстан-офлайн\ndates: 2027-05-01..2027-05-12\n", encoding="utf-8")
(TRIP / "0_scope_v1.md").write_text("# Scope\nАлтын-Эмель, Чарын\n", encoding="utf-8")
(TRIP / "5_final_plan_v1.md").write_text("# Финальный план\nДень 1 — Алматы\n", encoding="utf-8")
(TRIP / "5_final_plan_v1.pdf").write_bytes(b"%PDF-1.4 not kept")
POOL = [f"## Место {i}" if i % 3 == 0 else f"строка {i}" for i in range(40)]
(TRIP / "3_poi_pool.md").write_text("\n".join(POOL) + "\n", encoding="utf-8")
STAGE3 = "3_kazakhstan_mesta.html"
(TRIP / STAGE3).write_text("""<!doctype html><meta charset="utf-8"><title>Стадия 3 — тест</title>
<pre id="md"></pre><script>
/* тот же протокол, что у слоя правок выложенных HTML стадий 3–5 (stage3.py / nav-layer.js) */
var mdPath = decodeURIComponent(new URL(".", location.href).pathname).replace(/^\\/+/, "") + "3_poi_pool.md";
var state = null;
function api(u, i){ i = i || {}; i.credentials = "omit"; var t = null; try { t = localStorage.getItem("hub-auth"); } catch(e){}
  if (t){ var h = new Headers(i.headers || {}); h.set("Authorization", "Basic " + t); i.headers = h; } return fetch(u, i); }
api("/api/health").then(function(r){ return r.json(); }).then(function(){
  return api("/api/file?path=" + encodeURIComponent(mdPath)); }).then(function(r){ return r.json(); })
  .then(function(f){ state = f; document.getElementById("md").textContent = f.content; window.ready = true; })
  .catch(function(e){ window.ready = "err " + e; });
window.saveLine = function(n, txt){
  var lines = state.content.split("\\n"); lines[n] = txt; var c = lines.join("\\n");
  return api("/api/save", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: mdPath, content: c, base_hash: state.hash }) })
    .then(function(r){ return r.status === 200 ? r.json().then(function(j){ state = { content: c, hash: j.hash }; return "ok"; })
                                               : "err " + r.status; })
    .catch(function(){ return "neterr"; });
};
</script>""", encoding="utf-8")

TOKEN = base64.b64encode(b"hubuser:pw").decode()
OTHER = base64.b64encode(b"hubuser:other").decode()
PRIVATE = ("Portfolio/", "health-data/", "ZenMoney/", "macro-snapshots/", "monitor-reports/", "forecasts/",
           "scenarios/", "domains/", "api/hd/", "api/pv/")
S = {"down": False, "hang": False, "saves": 0, "delay": {}}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ct="application/json", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _down(self):
        if S["hang"]:                      # сеть висит: соединение принято, ответа нет (телефон без связи)
            t0 = time.monotonic()
            while S["hang"] and time.monotonic() - t0 < 90:
                time.sleep(0.05)
            S["down"] = True if S["hang"] else S["down"]
        if S["down"]:                      # NAS недоступен: соединение рвётся без ответа
            self.close_connection = True
            try:
                self.connection.shutdown(2)
            except OSError:
                pass
            return True
        return False

    def _auth(self, rel):
        if rel.startswith(PRIVATE) and self.headers.get("Authorization") not in ("Basic " + TOKEN, "Basic " + OTHER):
            self._send(403)
            return False
        return True

    def do_POST(self):
        if self._down():
            return
        n = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(n)
        p = _up(self.path).path
        if p == "/api/fd/save":                    # настоящий save_file сайдкара: base_hash → 409, схема «Еды»
            b = json.loads(body or b"{}")
            try:
                h = hub_api.save_file(str(FOOD), b["path"], b["content"], b.get("base_hash"), validate=hub_api.validate_food)
            except hub_api.Conflict as e:
                return self._send(409, json.dumps({"error": "conflict", "current_hash": e.current_hash}).encode())
            except ValueError as e:
                return self._send(400, json.dumps({"error": "bad", "detail": str(e)}).encode())
            S["saves"] += 1
            return self._send(200, json.dumps({"hash": h}).encode())
        if p == "/api/save":                       # поездки и игры: настоящий save_file по ROOT (base_hash → 409)
            b = json.loads(body or b"{}")
            try:
                h = hub_api.save_file(str(ROOT), b["path"], b["content"], b.get("base_hash"))
            except hub_api.Conflict as e:
                return self._send(409, json.dumps({"error": "conflict", "current_hash": e.current_hash}).encode())
            S["saves"] += 1
            return self._send(200, json.dumps({"hash": h}).encode())
        if p == "/api/hd/save" and self._auth("api/hd/"):     # настоящий save_file сайдкара: base_hash → 409, схема «Здоровья»
            b = json.loads(body or b"{}")
            try:
                h = hub_api.save_file(str(ROOT / "Health"), b["path"], b["content"], b.get("base_hash"),
                                      validate=hub_api.validate_health)
            except hub_api.Conflict as e:
                return self._send(409, json.dumps({"error": "conflict", "current_hash": e.current_hash}).encode())
            except ValueError as e:
                return self._send(400, json.dumps({"error": "bad", "detail": str(e)}).encode())
            S["saves"] += 1
            return self._send(200, json.dumps({"hash": h}).encode())
        if p == "/api/pv/sync" and self._auth("api/pv/"):
            res = hub_api.pv_sync(str(ROOT), json.loads(body or b"{}").get("have") or {})
            return self._send(200, json.dumps(res).encode())
        return self._send(404, b"{}")

    def do_GET(self):
        if self._down():
            return
        u = _up(self.path)
        p = _unq(u.path)
        rel = p.lstrip("/")
        if p.startswith("/tools/"):
            f = REPO / "tools" / p[len("/tools/"):]
            if not f.is_file():
                return self._send(404)
            ct = {".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css",
                  ".json": "application/json", ".woff2": "font/woff2", ".png": "image/png",
                  ".md": "text/markdown; charset=utf-8"}.get(f.suffix, "application/octet-stream")
            # как Caddyfile: фоновому скрипту кабинета разрешена область «весь сайт»
            body = f.read_bytes()
            if p == "/tools/sw-offline.js":      # тест 16 не ждёт настоящих 20 с: предел ассета сокращён (константа сверяется по исходнику)
                body = body.replace(b"var ASSET_TIMEOUT_MS = 20000;", b"var ASSET_TIMEOUT_MS = 9000;")
            v = parse_qs(u.query).get("v", [""])[0]
            if p == "/tools/assets/rebalance-engine.js" and v.startswith("0.0."):   # тест 16: версия видна в теле, ответ — с задержкой
                body += f"\n/*v={v}*/".encode()
                time.sleep(S["delay"].get(v, 0))
            return self._send(200, body, ct, {"Service-Worker-Allowed": "/"} if p == "/tools/sw.js" else None)
        if not self._auth(rel):
            return
        if p in ("/api/fd/file", "/api/hd/file", "/api/file"):
            base = FOOD if p.startswith("/api/fd") else ROOT / "Health" if p.startswith("/api/hd") else ROOT
            try:
                t, h = hub_api.read_file(str(base), parse_qs(u.query).get("path", [""])[0])
            except (FileNotFoundError, IsADirectoryError):
                return self._send(404, b"{}")
            return self._send(200, json.dumps({"content": t, "hash": h}).encode())
        if p == "/api/pv/plan":                    # плана на сайте нет — сервер отвечает 404 (как настоящий без plan.json)
            return self._send(404, json.dumps({"error": "no plan"}).encode())
        if p == "/api/health":
            return self._send(200, json.dumps({"ok": True, "writable": True, "food_writable": True,
                                               "health_writable": True, "health_files": [],
                                               "food_files": ["products", "recipes", "shopping"],
                                               "food_recipe_dir": True, "pv_sync": True}).encode())
        if p.startswith("/api/"):
            return self._send(502, b"{}")
        if p.startswith("/health-data/"):
            f = ROOT / "Health" / p[len("/health-data/"):]
        else:
            f = ROOT / rel
        if f.is_dir():
            kids = sorted(c for c in f.iterdir() if not c.name.startswith("."))
            if "application/json" in self.headers.get("Accept", ""):
                arr = [{"name": c.name + ("/" if c.is_dir() else ""), "size": c.stat().st_size, "is_dir": c.is_dir(),
                        "url": "./" + _q(c.name) + ("/" if c.is_dir() else ""),
                        "mod_time": datetime.fromtimestamp(c.stat().st_mtime, timezone.utc).isoformat()} for c in kids]
                return self._send(200, json.dumps(arr).encode())
            return self._send(200, ("<html>" + "".join(f'<a href="./{_q(c.name)}">{c.name}</a>' for c in kids)
                                    + "</html>").encode(), "text/html")
        if not f.is_file():
            return self._send(404)
        ct = {".json": "application/json", ".html": "text/html; charset=utf-8"}.get(f.suffix, "text/plain; charset=utf-8")
        return self._send(200, f.read_bytes(), ct)


class _Srv(ThreadingHTTPServer):
    request_queue_size = 256
    daemon_threads = True

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, OSError)):
            super().handle_error(request, client_address)


srv = _Srv(("127.0.0.1", 0), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
T = BASE + "/tools/"
PAGES = ["hub.html", "travel.html", "food.html", "health.html", "money.html", "games.html",
         "portfolio-integrated-viewer.html", "login.html"]

FETCH = """async ([url, auth]) => {
  try { const r = await fetch(url, { cache: 'no-store', credentials: 'omit',
                                     headers: auth ? { Authorization: 'Basic ' + auth } : {} });
        return { ok: r.ok, status: r.status, text: (await r.text()).slice(0, 200) }; }
  catch (e) { return { err: String(e) }; } }"""
SHELL_KEYS = "async () => (await (await caches.open('cab-shell-v1')).keys()).map(r => r.url)"
FOOD_HAS = "(t) => document.body.innerText.includes(t)"
WARMED = ["food.html", "travel.html", "health.html", "money.html", "games.html"]
# текст страницы без плашки «нет связи» и без версии в подвале (остальное обязано совпасть)
# состояние данных в подвале («данные живые» / «копия от …») отличается при связи и без неё по замыслу — в сравнение не входит
MAIN_TEXT = """() => { const b = document.body.cloneNode(true); b.querySelectorAll('#ui-offline, .ui-foot-state, script, iframe').forEach(e => e.remove());
  return b.innerText.replace(/\\s+/g, ' ').trim(); }"""
BANNER = "() => { const b = document.getElementById('ui-offline'); return b && !b.hidden ? b.textContent : ''; }"


def stable_text(pg, limit_s=8.0):
    """Текст страницы, когда он перестал меняться (две одинаковые выборки через 0,5 с): страницы
    дорисовываются по поздним запросам («Игры» — «Пока пусто.» после списка желаний)."""
    pg.wait_for_load_state("networkidle")
    prev, t0 = None, time.monotonic()
    while time.monotonic() - t0 < limit_s:
        cur = pg.evaluate(MAIN_TEXT)
        if cur == prev:
            return cur
        prev = cur
        pg.wait_for_timeout(500)
    return prev


def wait_sw(pg):
    pg.wait_for_function("navigator.serviceWorker && navigator.serviceWorker.controller", timeout=20000)
    for _ in range(80):                                    # precache — фоном при установке
        keys = pg.evaluate(SHELL_KEYS)
        if sum(any(k.endswith("/tools/" + p) for k in keys) for p in PAGES) == len(PAGES):
            return keys
        time.sleep(0.25)
    return pg.evaluate(SHELL_KEYS)


def main():
    with sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception:  # noqa: BLE001
            print("offline: пропуск — нет chromium")
            return 0
        ctx = br.new_context(viewport={"width": 390, "height": 860}, is_mobile=True, has_touch=True)
        ctx.add_init_script(f"window.UI_OFFLINE_TEST = true; try {{ localStorage.setItem('hub-auth', '{TOKEN}'); }} catch (e) {{}}")
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))

        # 1. хаб при связи — фоновый скрипт ставит оболочки всех страниц
        pg.goto(T + "hub.html")
        keys = wait_sw(pg)
        missing = [x for x in PAGES if not any(k.endswith("/tools/" + x) for k in keys)]
        check(f"1: оболочки всех страниц на устройстве после хаба (нет: {missing})", not missing)
        check("1: ассеты страниц и шрифты из стилей тоже", any("/assets/ui-kit.js?v=" in k for k in keys)
              and any("/assets/fonts/" in k for k in keys) and any("/assets/viewer.js?v=" in k for k in keys))
        HV = ["00-about", "01-run", "02-models", "03-fresh", "04-tabs", "05-now", "06-gates", "07-conditions", "08-site", "09-limits", "10-new"]
        for _ in range(40):                                # части справки вьюера — часть precache (CAB_PAGES)
            keys = pg.evaluate(SHELL_KEYS)
            if all(any(k.endswith(f"/tools/assets/help/viewer/{n}.md") for k in keys) for n in HV):
                break
            time.sleep(0.25)
        miss_hv = [n for n in HV if not any(k.endswith(f"/tools/assets/help/viewer/{n}.md") for k in keys)]
        check(f"1: все 10 частей справки вьюера в оболочке после хаба (нет: {miss_hv}), старого viewer-help.md нет",
              not miss_hv and not any(k.endswith("/tools/viewer-help.md") for k in keys))

        # 1б. всё, что страница читает при загрузке, держится офлайн (CAB_KEEP) или стоит в NOT_KEPT с причиной
        #     (ядро 1.4.1–1.4.2, 2026-11-05; случай: «Здоровье» без связи висело на «Загружаю данные…» — список
        #     отчётов шёл мимо копии; так же мимо шёл план вьюера). Запросы снимаются в браузере
        #     при связи, регэкспы — из ядра: новый файл на странице без строки в CAB_KEEP краснеет здесь.
        _core = (REPO / "tools/sw-offline.js").read_text(encoding="utf-8")
        def _rx(name):
            src = re.search(r"var " + name + r" = \[(.*?)\];", _core, re.S).group(1)
            return [re.compile(x.replace("\\/", "/")) for x in re.findall(r"/(\^?.*?\$)/[a-z]*", src)]
        KEEP_RX, NEVER_RX = _rx("CAB_KEEP"), _rx("CAB_NEVER")
        NOT_KEPT = {"/api/moex/quotes": "живые котировки — без связи вьюер их не запрашивает",
                    # исходники исследований «Здоровья» (PDF, сканы) не держим — решение владельца 2026-11-05
                    "/health-data/studies/": "исходники исследований",
                    "/api/pf/status": "сборка снимка — только при связи",
                    "/api/push/status": "уведомления — только при связи",
                    "/api/zm/csv-state": "состояние выгрузки CSV — только при связи (устаревшее вводило бы в заблуждение)"}
        def _not_kept(d):
            return any(d == k or (k.endswith("/") and d.startswith(k)) for k in NOT_KEPT)
        check(f"1б: регэкспы CAB_KEEP прочитаны из ядра ({len(KEEP_RX)})", len(KEEP_RX) >= 15)
        TABS_SEL = ".ui-tab, .ui-mnav-btn, [data-act='tab']"
        TABS_JS = ("() => [...document.querySelectorAll(\"" + TABS_SEL + "\")].filter(e => e.offsetParent)"
                   ".map(e => (e.getAttribute('data-id') || e.getAttribute('data-tab') || e.textContent || '').trim().slice(0, 40))")
        TAB_CLICK_JS = "(i) => [...document.querySelectorAll(\"" + TABS_SEL + "\")].filter(e => e.offsetParent)[i].click()"
        for x in [p_ for p_ in PAGES if p_ != "login.html"] + ["travel.html?trip=kazakhstan_2027"]:
            pg.evaluate("() => Object.keys(localStorage).filter(k => k.includes('-cache:')).forEach(k => localStorage.removeItem(k))")
            seen = []                                    # ↑ TTL-кеш страниц (uiFetchText) иначе прячет запросы
            h = lambda r: seen.append((r.method, r.url))
            pg.on("request", h)
            pg.goto(T + x)
            stable_text(pg)
            # обход вкладок (верхних, нижнего меню, data-act="tab"): у раздела свои запросы — без обхода их не видно
            tabs_done = set()
            for _ in range(60):
                labels = pg.evaluate(TABS_JS)
                todo = [i for i, l in enumerate(labels) if l and l not in tabs_done]
                if not todo:
                    break
                tabs_done.add(labels[todo[0]])
                pg.evaluate(TAB_CLICK_JS, todo[0])
                pg.wait_for_timeout(300)
                pg.wait_for_load_state("networkidle")
            pg.remove_listener("request", h)
            data = {_unq(_up(u).path) for m, u in seen if m == "GET" and u.startswith(BASE + "/")
                    and not _up(u).path.startswith("/tools/")}
            miss = sorted(d for d in data if not _not_kept(d) and (any(r.search(d) for r in NEVER_RX)
                                                                    or not any(r.search(d) for r in KEEP_RX)))
            check(f"1б: {x} — всё, что читает при загрузке ({len(data)}), держится офлайн (мимо копии: {miss})",
                  len(data) >= 1 and not miss)
        # при связи — открыть страницы с данными (копия заполняется на ходу)
        pg.goto(T + "food.html")
        pg.wait_for_function(FOOD_HAS, arg="Мука", timeout=20000)
        check("3: «Еда» при связи — список покупок, плашки нет", pg.evaluate(BANNER) == "")
        pg.goto(T + "portfolio-integrated-viewer.html")
        pg.wait_for_selector("#tabs .ui-tab", timeout=30000)
        tabs_online = pg.evaluate("() => document.querySelectorAll('#tabs .ui-tab').length")
        check("вьюер при связи — признака «без связи» нет (html без pv-offline)",
              not pg.evaluate("() => document.documentElement.classList.contains('pv-offline')"))
        r = pg.evaluate(FETCH, ["../Portfolio/reports/2026-10-01-%D0%B7%D0%B0%D0%BC%D0%B5%D1%82%D0%BA%D0%B0.md", TOKEN])
        check("4: отчёт при связи читается", r.get("ok"), str(r))
        r = pg.evaluate(FETCH, ["../Portfolio/snapshots/portfolio-2026-10-08.json", TOKEN])
        check("5: приватный файл при связи с паролем", r.get("ok"), str(r))

        # 2–5. NAS недоступен
        S["down"] = True
        for x in PAGES:
            pg.goto(T + x)
            pg.wait_for_load_state("load")
            ok = pg.evaluate("() => !/ещё не сохранена/.test(document.body.innerText) && document.title.length > 0"
                             " && (typeof uiOfflineInit === 'function' || !document.querySelector('script[src*=\"ui-kit.js\"]'))")
            check(f"2: {x} открывается без связи", ok)
        pg.goto(T + "food.html")
        try:
            pg.wait_for_function(FOOD_HAS, arg="Мука", timeout=20000)
            ok = True
        except Exception:  # noqa: BLE001
            ok = False
        check("3: «Еда» без связи — список покупок из копии", ok)
        pg.wait_for_function(BANNER, timeout=10000)
        b = pg.evaluate(BANNER)
        check(f"3: плашка «нет связи» с датой копии ({b})", "Нет связи" in b and "(от " in b)
        pg.goto(T + "portfolio-integrated-viewer.html")
        pg.wait_for_selector("#tabs .ui-tab", timeout=30000)
        check("3: вьюер без связи — разделы на месте",
              pg.evaluate("() => document.querySelectorAll('#tabs .ui-tab').length") == tabs_online)
        r = pg.evaluate(FETCH, ["../Portfolio/reports/2026-10-01-%D0%B7%D0%B0%D0%BC%D0%B5%D1%82%D0%BA%D0%B0.md", TOKEN])
        check("4: отчёт в свободной форме без связи недоступен (не держим)", "err" in r, str(r))
        r = pg.evaluate(FETCH, ["../Portfolio/snapshots/portfolio-2026-10-08.json", TOKEN])
        check("5: приватная копия — тем же паролем", bool(r.get("ok")), str(r))
        r = pg.evaluate(FETCH, ["../Portfolio/snapshots/portfolio-2026-10-08.json", OTHER])
        check("5: другим паролем — не отдаётся", "err" in r, str(r))
        r = pg.evaluate(FETCH, ["../Portfolio/snapshots/portfolio-2026-10-08.json", ""])
        check("5: без пароля — не отдаётся", "err" in r, str(r))
        r = pg.evaluate(FETCH, ["../api/fd/file?path=products.json", ""])
        check("3: публичная копия («Еда», чтение через /api/fd/file) — без пароля", r.get("ok"), str(r))

        # «Выйти» — приватное стёрто, публичное осталось
        pg.evaluate("() => navigator.serviceWorker.controller.postMessage({ type: 'cab-logout' })")
        time.sleep(0.5)
        r = pg.evaluate(FETCH, ["../Portfolio/snapshots/portfolio-2026-10-08.json", TOKEN])
        check("5: после «Выйти» приватной копии нет", "err" in r, str(r))
        r = pg.evaluate(FETCH, ["../api/fd/file?path=products.json", ""])
        check("5: публичная копия после «Выйти» на месте", r.get("ok"), str(r))

        # 6. связь вернулась — сначала сеть: свежее, плашки нет; 404 — копия удалена
        S["down"] = False
        shop = dict(SHOP, items=SHOP["items"] + [{"id": "i2", "name": "Сахар-свежий", "qty": 1, "unit": "кг", "bought": False}])
        (FOOD / "shopping.json").write_text(json.dumps(shop, ensure_ascii=False), encoding="utf-8")
        pg.goto(T + "food.html")
        pg.wait_for_function(FOOD_HAS, arg="Сахар-свежий", timeout=20000)
        check("6: связь есть — свежий список (новая позиция), плашки нет", pg.evaluate(BANNER) == "")
        (FOOD / "recipes/blin.json").unlink()
        pg.evaluate(FETCH, ["../Food/recipes/blin.json", ""])
        S["down"] = True
        r = pg.evaluate(FETCH, ["../Food/recipes/blin.json", ""])
        check("6: файл удалён на сервере — без связи тот же 404, а не старое содержимое", r.get("status") == 404, str(r))
        S["down"] = False

        # 7. версии ассетов
        pg.evaluate(FETCH, ["assets/rebalance-engine.js?v=0.0.1", ""])
        pg.evaluate(FETCH, ["assets/rebalance-engine.js?v=0.0.2", ""])
        time.sleep(0.3)
        ks = [k for k in pg.evaluate(SHELL_KEYS) if "/assets/rebalance-engine.js" in k]
        check(f"7: в кеше одна версия ассета — последняя ({ks})", ks == [T + "assets/rebalance-engine.js?v=0.0.2"])

        # 9. прогрев из хаба: свежее устройство открыло ТОЛЬКО хаб — без связи открываются и те страницы,
        #    которых не открывали, и показывают то же, что при связи
        ref = {}
        c0 = br.new_context(viewport={"width": 390, "height": 860}, is_mobile=True, has_touch=True)
        c0.add_init_script(f"try {{ localStorage.setItem('hub-auth', '{TOKEN}'); }} catch (e) {{}}")
        p0 = c0.new_page()                                   # эталон: без фонового скрипта, при связи
        for x in WARMED:
            p0.goto(T + x)
            ref[x] = stable_text(p0)
        c0.close()
        c2 = br.new_context(viewport={"width": 390, "height": 860}, is_mobile=True, has_touch=True)
        c2.add_init_script(f"window.UI_OFFLINE_TEST = true; try {{ localStorage.setItem('hub-auth', '{TOKEN}'); }} catch (e) {{}}")
        p2 = c2.new_page()
        p2.on("pageerror", lambda e: errs.append(str(e)))
        p2.goto(T + "hub.html")
        wait_sw(p2)
        t0 = time.monotonic()
        warmed = p2.evaluate("() => uiOfflineWarm(true)")
        check(f"9: прогрев прошёл ({time.monotonic() - t0:.1f} с)", warmed is True)
        check("9: повторный прогрев раньше 6 ч — не запускается", p2.evaluate("() => uiOfflineWarm()") is False)
        check("9: поездка из фикстуры видна при связи (иначе сравнивать нечего)", "kazakhstan" in ref["travel.html"].lower()
              or "казахстан" in ref["travel.html"].lower(), ref["travel.html"][:200])
        S["down"] = True
        for x in WARMED:
            p2.goto(T + x)
            got = stable_text(p2)
            _d = next((k for k in range(min(len(got), len(ref[x]))) if got[k] != ref[x][k]), min(len(got), len(ref[x])))
            check(f"9: {x} без связи после прогрева — как при связи", got == ref[x],
                  f"\n      при связи: …{ref[x][max(0, _d - 60):_d + 120]!r}\n      без связи: …{got[max(0, _d - 60):_d + 120]!r}")
        r = p2.evaluate(FETCH, ["../travel-planner/trips/kazakhstan_2027/5_final_plan_v1.md", ""])
        check("9: план поездки (стадия 5) без связи — сохранён прогревом, хотя панель не открывали",
              r.get("ok") and "Финальный план" in (r.get("text") or ""), str(r))
        r = p2.evaluate(FETCH, ["../travel-planner/trips/kazakhstan_2027/5_final_plan_v1.pdf", ""])
        check("9: PDF поездки офлайн не держим", "err" in r, str(r))
        S["down"] = False
        c2.close()

        # 10. запись «Еды» без связи (food 1.38): очередь на телефоне, отправка при связи, слияние при 409
        def shop_items():
            return {i["id"]: i for i in json.loads((FOOD / "shopping.json").read_text(encoding="utf-8"))["items"]}
        c3 = br.new_context(viewport={"width": 390, "height": 860}, is_mobile=True, has_touch=True)
        c3.add_init_script("window.UI_OFFLINE_TEST = true;")
        p3 = c3.new_page()
        p3.on("pageerror", lambda e: errs.append(str(e)))
        p3.goto(T + "hub.html")
        wait_sw(p3)
        for case in ("без конфликта", "с конфликтом"):
            base = {"schema": "food-shopping@1", "updated": "2026-10-23", "items": [
                {"id": "i1", "name": "Хлеб-тест", "qty": 1, "unit": "шт", "bought": False},
                {"id": "i2", "name": "Сыр-тест", "qty": 1, "unit": "шт", "bought": False}]}
            (FOOD / "shopping.json").write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
            p3.goto(T + "food.html")
            p3.wait_for_function(FOOD_HAS, arg="Хлеб-тест", timeout=20000)
            S["down"] = True
            saves0 = S["saves"]
            p3.click('[data-act="bought"][data-arg="i1"]')
            p3.wait_for_function(FOOD_HAS, arg="сохранены на телефоне", timeout=10000)
            ob = p3.evaluate("() => JSON.parse(localStorage.getItem('food-outbox') || '{}')")
            check(f"10 ({case}): без связи отметка в очереди на телефоне",
                  ob.get("shopping", {}).get("doc", {}).get("items", [{}])[0].get("bought") is True)
            p3.goto(T + "food.html")
            p3.wait_for_function(FOOD_HAS, arg="Хлеб-тест", timeout=20000)
            check(f"10 ({case}): перезагрузка без связи — своя версия (1 из 2 куплено)",
                  p3.evaluate(FOOD_HAS, "1 из 2 куплено"), p3.evaluate(MAIN_TEXT)[:300])
            if case == "с конфликтом":                # пока телефон без связи — правка с другого устройства
                other = json.loads((FOOD / "shopping.json").read_text(encoding="utf-8"))
                other["items"].append({"id": "i3", "name": "Молоко-другое", "qty": 1, "unit": "л", "bought": False})
                other["items"][1]["qty"] = 3
                (FOOD / "shopping.json").write_text(json.dumps(other, ensure_ascii=False), encoding="utf-8")
            S["down"] = False
            p3.evaluate("() => window.dispatchEvent(new Event('online'))")
            want = "объединены" if case == "с конфликтом" else "отправлены"
            p3.wait_for_function(FOOD_HAS, arg=want, timeout=20000)
            it = shop_items()
            check(f"10 ({case}): связь вернулась — отметка на сервере", it["i1"]["bought"] is True and S["saves"] > saves0)
            if case == "с конфликтом":
                check("10: чужие правки не затёрты — новая позиция и чужое количество на месте",
                      "i3" in it and it["i2"]["qty"] == 3, str(it))
                check("10: и на экране объединённый список", p3.evaluate(FOOD_HAS, "Молоко-другое"))
            check(f"10 ({case}): очередь пуста", p3.evaluate("() => localStorage.getItem('food-outbox')") is None)
        c3.close()

        # 11. HTML стадии поездки без связи + очередь правок фонового скрипта (ядро 1.1.0, ui-kit 1.56.0)
        def pool():
            return (TRIP / "3_poi_pool.md").read_text(encoding="utf-8").split("\n")
        c5 = br.new_context(viewport={"width": 390, "height": 860}, is_mobile=True, has_touch=True)
        c5.add_init_script("window.UI_OFFLINE_TEST = true;")
        p5 = c5.new_page()
        p5.on("pageerror", lambda e: errs.append(str(e)))
        p5.goto(T + "hub.html")
        wait_sw(p5)
        scopes = p5.evaluate("async () => (await navigator.serviceWorker.getRegistrations()).map(r => new URL(r.scope).pathname)")
        check(f"11: фоновый скрипт — на весь сайт (область /) ({scopes})", "/" in scopes and "/tools/" not in scopes)
        p5.evaluate("() => uiOfflineWarm(true)")
        STAGE_URL = BASE + "/travel-planner/trips/kazakhstan_2027/" + STAGE3
        p5.goto(STAGE_URL)
        p5.wait_for_function("window.ready === true", timeout=15000)
        check("11: страницей стадии управляет фоновый скрипт", p5.evaluate("() => !!navigator.serviceWorker.controller"))
        S["down"] = True
        p5.reload()
        try:
            p5.wait_for_function("window.ready === true", timeout=15000)
            ok = True
        except Exception:  # noqa: BLE001
            ok = False
        check("11: без связи HTML стадии открывается, слой правок читает md из копии", ok)
        r = p5.evaluate("() => saveLine(10, 'КОММЕНТ-офлайн')")
        check(f"11: без связи «Сохранить» — принято в очередь ({r})", r == "ok" and pool()[10] == "строка 10")
        p5.reload()
        p5.wait_for_function("window.ready === true", timeout=15000)
        check("11: перезагрузка без связи — правка на месте (своя версия из очереди)",
              "КОММЕНТ-офлайн" in p5.evaluate("() => document.getElementById('md').textContent"))
        r = p5.evaluate("() => saveLine(12, 'ВТОРАЯ-офлайн')")
        check("11: вторая правка поверх неотправленной — тоже в очередь", r == "ok")
        other = pool(); other[30] = "ПРАВКА-с-другого-устройства"
        (TRIP / "3_poi_pool.md").write_text("\n".join(other), encoding="utf-8")
        S["down"] = False
        p5.goto(T + "travel.html")
        p5.evaluate("() => window.dispatchEvent(new Event('online'))")
        try:
            p5.wait_for_function("() => /отправлены/.test((document.getElementById('ui-notice') || {}).textContent || '')", timeout=20000)
            note = p5.evaluate("() => document.getElementById('ui-notice').textContent")
        except Exception:  # noqa: BLE001
            note = ""
        cur = pool()
        check(f"11: связь вернулась — правки ушли сами, объединены с чужой ({note[:60]!r})",
              cur[10] == "КОММЕНТ-офлайн" and cur[12] == "ВТОРАЯ-офлайн" and cur[30] == "ПРАВКА-с-другого-устройства"
              and "объединены" in note, str(cur[8:14] + cur[29:31]))
        # 12. правка той же строки с двух сторон — не затирается
        p5.goto(STAGE_URL)
        p5.wait_for_function("window.ready === true", timeout=15000)
        S["down"] = True
        p5.evaluate("() => saveLine(20, 'МОЁ-офлайн')")
        other = pool(); other[20] = "ИХ-правка"
        (TRIP / "3_poi_pool.md").write_text("\n".join(other), encoding="utf-8")
        S["down"] = False
        p5.goto(T + "travel.html")
        p5.evaluate("() => window.dispatchEvent(new Event('online'))")
        try:
            p5.wait_for_function("() => /не отправлена/.test((document.getElementById('ui-notice') || {}).textContent || '')", timeout=20000)
            ok = True
        except Exception:  # noqa: BLE001
            ok = False
        check("12: та же строка изменена с другого устройства — правка не затёрла чужую, сообщение о конфликте",
              ok and pool()[20] == "ИХ-правка")

        # 13. уведомление «нет связи»: крестик → метка «офлайн», на других страницах тоже; связь — всё убрано
        S["down"] = True
        p5.goto(T + "food.html")
        p5.wait_for_function(BANNER, timeout=15000)
        check("13: «нет связи» — плашка внизу во всю ширину",
              p5.evaluate("() => { const b = document.getElementById('ui-offline'); return b.classList.contains('ui-toast') && b.getBoundingClientRect().width > innerWidth * .85; }"))
        p5.click("#ui-offline [data-offline-close]")
        check("13: после крестика — маленькая метка «офлайн»",
              p5.evaluate("() => document.getElementById('ui-offline').classList.contains('ui-toast-chip')"))
        p5.goto(T + "travel.html")
        p5.wait_for_timeout(2500)
        check("13: на другой странице без связи — снова метка, не большая плашка",
              p5.evaluate("() => { const b = document.getElementById('ui-offline'); return !b || b.classList.contains('ui-toast-chip'); }"))
        S["down"] = False
        p5.goto(T + "food.html")
        p5.wait_for_timeout(2500)
        check("13: связь есть — ни плашки, ни метки", p5.evaluate(
            "() => { const b = document.getElementById('ui-offline'); return !b || b.hidden; }"))
        c5.close()

        # 14. вьюер без связи — сразу копия с устройства, без сверки файлов по одному
        S["down"] = True
        t0 = time.monotonic()
        pg.goto(T + "portfolio-integrated-viewer.html")
        pg.wait_for_selector("#tabs .ui-tab", timeout=30000)
        dt = time.monotonic() - t0
        st = pg.evaluate("() => state.netStats")
        check(f"14: вьюер без связи — копия с устройства за {dt:.1f} с ({st and st.get('via')})",
              st and st["via"] == "device" and dt < 6)
        check("14: без перечня путей над разделами", not pg.evaluate("() => (state.warnings || []).some(w => /Portfolio\\//.test(w))"))
        S["down"] = False

        # 15. сеть висит, а не рвётся
        pg.goto(T + "portfolio-integrated-viewer.html")    # при связи: проба входа вьюера в копии
        pg.wait_for_selector("#tabs .ui-tab", timeout=30000)
        pg.goto(T + "hub.html")                            # при связи: метка «связи нет» снята
        pg.wait_for_timeout(1500)
        S["hang"] = True
        t0 = time.monotonic()
        pg.goto(T + "food.html", wait_until="domcontentloaded", timeout=30000)
        pg.wait_for_function(FOOD_HAS, arg="Мука", timeout=30000)
        dt_food = time.monotonic() - t0
        check(f"15: сеть висит — первая страница {dt_food:.1f} с (один таймаут, дальше копия)", dt_food < 7)
        t0 = time.monotonic()
        pg.goto(T + "hub.html", wait_until="domcontentloaded", timeout=30000)
        pg.wait_for_function(BANNER, timeout=15000)
        dt_hub = time.monotonic() - t0
        check(f"15: следующая страница — связи нет уже известно, {dt_hub:.1f} с", dt_hub < 3)
        t0 = time.monotonic()
        pg.goto(T + "portfolio-integrated-viewer.html", wait_until="domcontentloaded", timeout=30000)
        pg.wait_for_selector("#tabs .ui-tab", timeout=60000)
        dt_v = time.monotonic() - t0
        st = pg.evaluate("() => state.netStats")
        check(f"15: вьюер — копия с устройства за {dt_v:.1f} с ({st and st.get('via')})",
              st and st["via"] == "device" and dt_v < 5)
        live = pg.evaluate("() => ({ busy: state.live.busy, status: state.live.status })")
        check(f"15: живые цены без связи не запрашиваются ({live})", not live["busy"] and live["status"] == "off")
        hid = pg.evaluate("""() => { const b = document.createElement('button'); b.setAttribute('data-plan-edit', ''); document.body.append(b);
          const d = getComputedStyle(b).display; b.remove();
          return { cls: document.documentElement.classList.contains('pv-offline'), ed: planEditable(), d }; }""")
        check(f"15: вьюер без связи — план не правится, кнопки правки спрятаны (вьюер 4.3.0; {hid})",
              hid["cls"] and hid["ed"] is False and hid["d"] == "none")
        r = pg.evaluate("""async (auth) => { const t = Date.now();
          const r = await fetch('/api/save', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Basic ' + auth },
            body: JSON.stringify({ path: 'travel-planner/trips/kazakhstan_2027/0_scope_v1.md', content: 'x', base_hash: 'h' }) });
          return { ms: Date.now() - t, queued: r.headers.get('X-Cab-Queued') }; }""", TOKEN)
        check(f"15: запись без ответа сервера — в очередь за {r['ms']} мс", r["queued"] == "1" and r["ms"] < 3000)
        pg.evaluate("async () => (await caches.open('cab-outbox-v1')).keys().then(ks => Promise.all(ks.map(k => caches.open('cab-outbox-v1').then(c => c.delete(k)))))")
        pg.goto(T + "portfolio-integrated-viewer.html", wait_until="domcontentloaded", timeout=30000)
        pg.wait_for_selector("#tabs .ui-tab", timeout=60000)
        S["hang"] = False                                   # связь вернулась: «online» → проба плана → признак снят сам (4.4.1)
        pg.evaluate("() => window.dispatchEvent(new Event('online'))")
        try:
            pg.wait_for_function("() => !document.documentElement.classList.contains('pv-offline') && state.offline === false", timeout=10000)
            back = True
        except Exception:  # noqa: BLE001
            back = False
        check("15: связь вернулась — вьюер снял признак «без связи» сам, без «Обновить» (4.4.1)", back)
        S["hang"] = False
        S["down"] = False

        # 15б. «Здоровье» при висящей сети (ядро 1.4.1, health v1.56; случай 2026-11-05: открыто при связи, потом
        #      без связи — «Загружаю данные…» дольше минуты: список отчётов и анамнез шли мимо копии и держали
        #      всю загрузку). Сначала при связи — копия; потом сеть висит — страница с данными, а не вечная загрузка
        HEALTH_READY = "() => document.body && /Здоровье/.test(document.body.innerText) && !/Загружаю данные/.test(document.body.innerText)"
        pg.goto(T + "health.html")
        pg.wait_for_function(HEALTH_READY, timeout=30000)
        stable_text(pg)
        pg.evaluate("async () => { const c = await caches.open('cab-state-v1'); await c.put('https://cab.state/offline', new Response('0')); }")
        S["hang"] = True
        t0 = time.monotonic()
        pg.goto(T + "health.html", wait_until="domcontentloaded", timeout=30000)
        try:
            pg.wait_for_function(HEALTH_READY, timeout=20000)
        except Exception:
            pass
        dt_h = time.monotonic() - t0
        check(f"15б: «Здоровье» при висящей сети — данные за {dt_h:.1f} с, не «Загружаю данные…»", dt_h < 12
              and not pg.evaluate("() => /Загружаю данные/.test(document.body.innerText)"))
        S["hang"] = False
        S["down"] = False

        # 15в. «Здоровье» без связи — правка в очередь, как у «Еды» (health v1.57, 2026-11-05): вес записан без
        #      связи → «сохранено на телефоне»; перезагрузка без связи — своя версия; на сервере тем временем
        #      дописали другой вес (409) — при связи правка ушла сама и объединена, чужая запись не затёрта
        HV = ROOT / "Health/vitals.json"
        HV.write_text(json.dumps(VITALS0), encoding="utf-8")
        pg.goto(T + "health.html")
        pg.wait_for_function(HEALTH_READY, timeout=30000)
        stable_text(pg)
        S["down"] = True
        pg.locator('[data-act="weight-add"]').first.click()
        pg.fill("#f-kg", "77,4")
        pg.locator('[data-act="weight-save"]').first.click()
        pg.wait_for_function("() => /сохранены на телефоне/.test(document.body.innerText)", timeout=15000)
        ob = pg.evaluate("() => JSON.parse(localStorage.getItem('health-outbox') || '{}')")
        check("15в: вес без связи — в очереди на телефоне, файл на сервере не тронут",
              "vitals" in ob and any(w.get("kg") == 77.4 for w in ob["vitals"]["doc"]["weight"])
              and json.loads(HV.read_text(encoding="utf-8")) == VITALS0)
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_function(HEALTH_READY, timeout=20000)
        pg.wait_for_function("() => /77[,.]4/.test(document.body.innerText)", timeout=10000)
        check("15в: перезагрузка без связи — своя версия и пометка «отправятся сами»",
              pg.evaluate("() => /отправятся сами/.test(document.body.innerText)"))
        other = dict(VITALS0, weight=VITALS0["weight"] + [{"date": "2026-10-15", "kg": 79}])
        HV.write_text(json.dumps(other), encoding="utf-8")       # правка с другого устройства
        S["down"] = False
        pg.evaluate("() => window.dispatchEvent(new Event('online'))")
        pg.wait_for_function("() => localStorage.getItem('health-outbox') === null", timeout=20000)
        got = json.loads(HV.read_text(encoding="utf-8"))
        kgs = sorted(w["kg"] for w in got.get("weight", []))
        check(f"15в: связь — правка ушла сама и объединена с чужой ({kgs})", kgs == [77.4, 79, 80])
        pg.wait_for_function("() => /объединены/.test(document.body.innerText)", timeout=10000)
        check("15в: сообщение «отправлены и объединены»", True)
        HV.write_text(json.dumps(VITALS0), encoding="utf-8")

        # 15г. запись при висящей сети (food v1.48, health v1.57; 2026-11-06): страница открыта при связи, потом сеть
        #      повисла — «Сохраняю…» не вечное: не позже SAVE_WAIT_MS (8 с) правка в очереди, при связи уходит сама
        base = {"schema": "food-shopping@1", "updated": "2026-11-06", "items": [
            {"id": "h1", "name": "Хлеб-висит", "qty": 1, "unit": "шт", "bought": False}]}
        (FOOD / "shopping.json").write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
        pg.evaluate("() => localStorage.removeItem('food-outbox')")
        pg.goto(T + "food.html")
        pg.wait_for_function(FOOD_HAS, arg="Хлеб-висит", timeout=20000)
        S["hang"] = True
        t0 = time.monotonic()
        pg.click('[data-act="bought"][data-arg="h1"]')
        pg.wait_for_function(FOOD_HAS, arg="сохранены на телефоне", timeout=15000)
        dt_q = time.monotonic() - t0
        check(f"15г: «Еда» — запись без ответа сервера в очереди за {dt_q:.1f} с (≤ 8 с + запас)", dt_q < 11)
        S["hang"] = False
        S["down"] = False
        pg.evaluate("() => window.dispatchEvent(new Event('online'))")
        pg.wait_for_function("() => localStorage.getItem('food-outbox') === null", timeout=20000)
        got = json.loads((FOOD / "shopping.json").read_text(encoding="utf-8"))
        check("15г: «Еда» — связь вернулась, отметка ушла сама", got["items"][0]["bought"] is True)
        HV.write_text(json.dumps(VITALS0), encoding="utf-8")
        pg.goto(T + "health.html")
        pg.wait_for_function(HEALTH_READY, timeout=30000)
        stable_text(pg)
        S["hang"] = True
        t0 = time.monotonic()
        pg.locator('[data-act="weight-add"]').first.click()
        pg.fill("#f-kg", "76,1")
        pg.locator('[data-act="weight-save"]').first.click()
        pg.wait_for_function("() => /сохранены на телефоне/.test(document.body.innerText)", timeout=15000)
        dt_q = time.monotonic() - t0
        check(f"15г: «Здоровье» — запись без ответа сервера в очереди за {dt_q:.1f} с", dt_q < 11)
        S["hang"] = False
        S["down"] = False
        pg.evaluate("() => window.dispatchEvent(new Event('online'))")
        pg.wait_for_function("() => localStorage.getItem('health-outbox') === null", timeout=20000)
        check("15г: «Здоровье» — связь вернулась, вес ушёл сам",
              any(w["kg"] == 76.1 for w in json.loads(HV.read_text(encoding="utf-8"))["weight"]))
        HV.write_text(json.dumps(VITALS0), encoding="utf-8")

        # 16. прошлая версия ассета: медленная сеть — новая, молчит / нет связи — прежняя + cab-stale + тост
        core = (REPO / "tools/sw-offline.js").read_text(encoding="utf-8")
        check("16: предел ожидания ассета в исходнике — 20 с",
              "var ASSET_TIMEOUT_MS = 20000;" in core)
        pg.goto(T + "hub.html")
        pg.wait_for_timeout(2500)                          # связь есть: метка «связи нет» снята, ядро ждёт полный предел
        AF = """async (v) => { const t = Date.now();
          try { const r = await fetch('assets/rebalance-engine.js?v=' + v, { cache: 'no-store' }); const x = await r.text();
                return { tail: x.slice(-14), ms: Date.now() - t }; } catch (e) { return { err: String(e), ms: Date.now() - t }; } }"""
        pg.evaluate("""() => { window.__stale = [];
          navigator.serviceWorker.addEventListener('message', e => { if (e.data && e.data.type === 'cab-stale') window.__stale.push(e.data); }); }""")
        S["delay"] = {"0.0.7": 6, "0.0.8": 14}
        r0 = pg.evaluate(AF, "0.0.5")
        r1 = pg.evaluate(AF, "0.0.6")
        check(f"16: быстрая сеть — новая версия, сообщения нет ({r1})", "v=0.0.6" in r1.get("tail", "") and not pg.evaluate("() => window.__stale.length"))
        r2 = pg.evaluate(AF, "0.0.7")
        check(f"16: медленная сеть (6 с > 4 с, меньше предела) — НОВАЯ версия, не прежняя ({r2})",
              "v=0.0.7" in r2.get("tail", "") and r2["ms"] >= 5500)
        check("16: медленная сеть — cab-stale нет", not pg.evaluate("() => window.__stale.length"))
        r3 = pg.evaluate(AF, "0.0.8")
        check(f"16: сеть молчит дольше предела — прежняя версия за предел ({r3})", "v=0.0.7" in r3.get("tail", "") and 8000 <= r3["ms"] < 13000)
        pg.wait_for_function("() => window.__stale.length >= 1", timeout=5000)
        st = pg.evaluate("() => window.__stale[0]")
        check(f"16: cab-stale: url / served / wanted ({st})", "v=0.0.8" in st.get("url", "") and "v=0.0.7" in st.get("served", "")
              and "v=0.0.8" in st.get("wanted", ""))
        pg.wait_for_selector("#ui-stale", timeout=5000)
        pg.wait_for_timeout(3600)                           # второе (повторное) сообщение тост не множит
        check("16: тост один, с текстом и кнопкой «Обновить»", pg.evaluate(
            "() => { const t = document.querySelectorAll('#ui-stale'); return t.length === 1 && t[0].classList.contains('ui-toast') "
            "&& /Открыта прошлая версия страницы/.test(t[0].textContent) && !!t[0].querySelector('[data-stale-reload]'); }"))
        pg.evaluate("() => { window.__marker = 1; }")
        pg.click("#ui-stale [data-stale-reload]")
        pg.wait_for_load_state("load")
        pg.wait_for_timeout(500)
        check("16: «Обновить» перезагружает страницу", pg.evaluate("() => window.__marker === undefined"))
        # запоздавший ответ 0.0.8 лёг в кеш (и вытеснил 0.0.7) — следующий промах точной версии пойдёт от него;
        # ждём именно этого (TST-1: раньше — фиксированные 11 с с запасом на 14-секундную задержку сервера)
        pg.wait_for_function("""async () => { const ks = (await (await caches.open('cab-shell-v1')).keys()).map(r => r.url)
          .filter(u => u.includes('rebalance-engine.js?v=')); return ks.some(u => u.includes('v=0.0.8')) && !ks.some(u => u.includes('v=0.0.7')); }""",
                             timeout=15000, polling=250)
        pg.wait_for_timeout(300)
        pg.evaluate("""() => { window.__stale = [];
          navigator.serviceWorker.addEventListener('message', e => { if (e.data && e.data.type === 'cab-stale') window.__stale.push(e.data); }); }""")
        S["delay"] = {}
        S["down"] = True
        r4 = pg.evaluate(AF, "0.0.9")
        check(f"16: связи нет — прежняя версия, а не ошибка ({r4})", "v=0.0." in r4.get("tail", "") and "err" not in r4)
        pg.wait_for_function("() => window.__stale.length >= 1", timeout=5000)
        check("16: связи нет — cab-stale", pg.evaluate("() => window.__stale[0].wanted.includes('v=0.0.9')"))
        # штатный офлайн: плашка «Нет связи» (или метка «офлайн») уже на экране / navigator.onLine === false — тоста «прошлая версия» нет
        pg.evaluate("() => { const t = document.getElementById('ui-stale'); t && t.remove(); }")
        pg.evaluate("() => { uiStaleShow(); }")
        check("16: связь есть, плашки нет — тост «прошлая версия» показывается как раньше", pg.evaluate("() => !!document.getElementById('ui-stale') && !document.getElementById('ui-stale').hidden"))
        pg.evaluate("() => { uiOfflineShow(null); }")
        check("16: пришла плашка «Нет связи» — тост «прошлая версия» скрыт", pg.evaluate("() => document.getElementById('ui-stale').hidden"))
        pg.evaluate("() => { document.getElementById('ui-stale').remove(); uiStaleShow(); }")
        check("16: плашка «Нет связи» на экране — тоста «прошлая версия» нет", pg.evaluate("() => !document.getElementById('ui-stale')"))
        pg.evaluate("() => { sessionStorage.setItem('ui-offline-dismissed', '1'); uiOfflineShow(null); uiStaleShow(); }")
        check("16: плашка закрыта, остался значок «офлайн» — тоста «прошлая версия» нет", pg.evaluate("() => !document.getElementById('ui-stale') && document.getElementById('ui-offline').classList.contains('ui-toast-chip')"))
        pg.evaluate("() => { uiOfflineGone(); Object.defineProperty(navigator, 'onLine', { get: () => false, configurable: true }); uiStaleShow(); }")
        check("16: navigator.onLine === false — тоста нет", pg.evaluate("() => !document.getElementById('ui-stale')"))
        pg.evaluate("() => { delete navigator.onLine; uiOfflineGone(); }")
        S["down"] = False
        pg.goto(T + "hub.html")
        pg.wait_for_timeout(1500)

        check("8: ошибок JS нет", not errs, str(errs[:3]))
        br.close()
    srv.shutdown()
    shutil.rmtree(ROOT, ignore_errors=True)
    print(f"offline: {passed} OK, {failed} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
