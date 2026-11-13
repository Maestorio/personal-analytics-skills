#!/usr/bin/env python3
"""Быстрая загрузка вьюера с сервера (v3.46.0, 2026-10-23) — настоящим браузером против сервера «как Caddy».

Случай 2026-10-23: телефон издалека (VPN до дома) — каждый запрос 150–300 мс, вьюер на каждом открытии
качал все файлы мимо кеша: 20–30 с и «Не загрузилось с сервера (63)» по таймауту прокси DSM. Сервер теста
отдаёт листинги JSON, как Caddy (name/size/url/mod_time/is_dir), файлы — с ETag и 304, умеет «падать»
и «висеть» по заказу, считает запросы и одновременность. Контракты:
  1. первое открытие: листинги JSON (Accept: application/json, без метки в адресе), все файлы скачаны,
     копия на устройстве записана; не больше 8 запросов разом;
  2. повторное открытие: ни одного запроса файла — только листинги; то же содержимое раздела;
  3. файл изменился на сервере → скачан только он, в копии — новая версия;
  4. файл удалён на сервере → пропал со страницы и из копии;
  5. листинг папки не ответил → файлы папки из копии + предупреждение «показана копия», без «Не загрузилось»;
  6. изменившийся файл не скачался → старая копия + предупреждение; не скачался и копии нет → «Не загрузилось»;
  7. запрос, который висит, обрывается по таймауту, повтор — и загрузка не зависает;
  8. смена пароля (другой токен) → копия чужая: всё скачано заново, старые записи стёрты;
  9. «Обновить» один раз — файлы не перекачиваются; второй раз в течение минуты — перекачиваются все;
 10. HTML-листинг (без версий) → файлы качаются всегда (копии нечего сверять — устаревшего не показать);
 11. ошибок JS нет;
 12. IndexedDB недоступна или висит (WebKit) — загрузка с сервера, как без копии;
 13. одним запросом (POST /api/pv/sync, настоящий pv_sync сервера): один POST вместо листингов и файлов,
     повторно — содержимого 0, изменившийся — только он, предел ответа — пачками, sync упал (500) или
     его нет (404, старый сайдкар) — листинги, как в 3.46.0. Данные — фикстуры tools/tests/fixtures/viewer-live (копия во временной папке).
Chromium и WebKit (движок Safari — iPhone); движок, которого нет, — честный пропуск.
Запуск: python3 tools/tests/test_viewer_fast_load.py
"""
import json
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import quote as _q, unquote as _unq, urlparse as _up

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import serve  # noqa: E402  (стенд — _pages_stand, keep-alive)
FIX = REPO / "tools/tests/fixtures/viewer-live"
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
    print("viewer_fast_load: пропуск — нет playwright")
    sys.exit(0)

# Фоновые скрипты выключены во всех контекстах: тест проверяет СОБСТВЕННЫЕ откаты вьюера (копия FileCache,
# листинги вместо sync). Где Chromium умеет push, вьюер регистрирует portfolio-sw.js с офлайн-ядром, и оно
# отвечало на 500 копией раньше вьюера — проверка зависела от того, успело ли ядро встать (Mac, 2026-10-26).
# Офлайн-ядро проверяют test_offline.py и test_stack_e2e.py.
ROOT = Path(tempfile.mkdtemp())
shutil.copytree(FIX, ROOT, dirs_exist_ok=True)
S = {"log": [], "fail": set(), "hang": set(), "html": False, "inflight": 0, "max": 0, "delay": 0.0,
     "sync": False, "pv_max": None}
sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as hub_api  # noqa: E402  — /api/pv/sync тестового сервера = настоящий pv_sync
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    """/tools/* — из репозитория; остальное — из ROOT: каталог → листинг (JSON по Accept, как Caddy)."""
    # HTTP/1.1, как Caddy: на ответы HTTP/1.0 Chromium не шлёт условных запросов (ETag игнорируется)
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ct="text/plain", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_POST(self):
        """/api/pv/sync — настоящий hub-api pv_sync по ROOT; выключен (S["sync"]) — 404, как старый сайдкар."""
        p = _up(self.path).path
        body = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
        if p != "/api/pv/sync" or not S["sync"]:
            return self._send(404, b'{"error": "unknown endpoint"}', "application/json")
        if "api/pv/sync" in S["fail"]:
            S["log"].append({"path": "api/pv/sync", "url": self.path, "accept": "", "post": True})
            return self._send(500)
        have = json.loads(body or b"{}").get("have") or {}
        res = hub_api.pv_sync(str(ROOT), have, **({"max_bytes": S["pv_max"]} if S["pv_max"] else {}))
        S["log"].append({"path": "api/pv/sync", "url": self.path, "accept": "", "post": True,
                         "have": len(have), "sent": len(res["files"])})
        return self._send(200, json.dumps(res).encode(), "application/json")

    def do_GET(self):
        p = _unq(_up(self.path).path)
        if p.startswith("/tools/"):
            f = REPO / "tools" / p[len("/tools/"):]
            if not f.is_file():
                return self._send(404)
            ct = {".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css",
                  ".json": "application/json", ".woff2": "font/woff2"}.get(f.suffix, "text/plain; charset=utf-8")
            return self._send(200, f.read_bytes(), ct)
        if p.startswith("/api/"):
            return self._send(502, b"{}", "application/json")
        with LOCK:
            S["inflight"] += 1
            S["max"] = max(S["max"], S["inflight"])
        try:
            self._data(p)
        finally:
            with LOCK:
                S["inflight"] -= 1

    def _data(self, p):
        rel = p.lstrip("/")
        accept = self.headers.get("Accept", "")
        S["log"].append({"path": rel, "url": self.path, "accept": accept})
        if S["delay"]:
            time.sleep(S["delay"])
        if rel in S["hang"]:
            S["hang"].discard(rel)                 # висит один раз: повтор проходит
            time.sleep(4)
            return
        if rel in S["fail"]:
            return self._send(500)
        f = ROOT / rel
        if p.endswith("/"):
            kids = sorted(f.iterdir()) if f.is_dir() else []
            if "application/json" in accept and not S["html"]:
                arr = [{"name": c.name + ("/" if c.is_dir() else ""), "size": c.stat().st_size,
                        "url": "./" + _q(c.name) + ("/" if c.is_dir() else ""),
                        "mod_time": datetime.fromtimestamp(c.stat().st_mtime, timezone.utc).isoformat(),
                        "mode": 420, "is_dir": c.is_dir(), "is_symlink": False} for c in kids]
                return self._send(200, json.dumps(arr).encode(), "application/json")
            body = "<html><body>" + "".join(f'<a href="./{_q(c.name)}{"/" if c.is_dir() else ""}">{c.name}</a>\n'
                                            for c in kids) + "</body></html>"
            return self._send(200, body.encode(), "text/html; charset=utf-8")
        if not f.is_file():
            return self._send(404)
        st = f.stat()
        etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
        if self.headers.get("If-None-Match") == etag:
            S["log"][-1]["status"] = 304
            return self._send(304, extra={"ETag": etag})
        ct = "application/json" if f.suffix == ".json" else "text/plain; charset=utf-8"
        return self._send(200, f.read_bytes(), ct, {"ETag": etag})


# _pages_stand: очередь 128, keep-alive; quiet=False — обрыв соединения закрытой вкладкой не шум, прочие ошибки
# обработчика печатаются
srv = serve(Handler, quiet=False)[0]
URL = f"http://127.0.0.1:{srv.server_address[1]}/tools/portfolio-integrated-viewer.html"

SNAP = "Portfolio/snapshots/portfolio-2026-10-08.json"
OLD_WR = "Portfolio/weekly-reviews/weekly-review-stock-2026-10-01.yaml"
WR_NEW = "Portfolio/weekly-reviews/weekly-review-stock-2026-10-08.yaml"
COPY = """async () => { await (state.fileCacheWrite || Promise.resolve()); const m = await FileCache.all();
  return Object.fromEntries([...m.values()].map(r => [r.path, { ver: r.ver, n: r.text.length, mark: r.text.includes('fast-load-mark') }])); }"""
MAIN = "() => document.querySelector('main').textContent"


def files():
    return [e for e in S["log"] if not e["path"].endswith("/") and e["path"] and not e.get("post")]


def posts():
    return [e for e in S["log"] if e.get("post")]


def listings():
    return [e for e in S["log"] if e["path"].endswith("/")]


def open_viewer(pg, wait_tabs=True):
    S["log"].clear()
    pg.goto(URL)
    if wait_tabs:
        pg.wait_for_selector("#tabs .ui-tab", timeout=30000)
    pg.evaluate("() => state.fileCacheWrite || null")
    return pg.evaluate("() => state.netStats || null")


def warnings(pg):
    return pg.evaluate("() => (state.warnings || []).join(' | ')")


def touch(rel, extra):
    f = ROOT / rel
    f.write_text(f.read_text(encoding="utf-8") + extra, encoding="utf-8")


def reset_root():
    shutil.rmtree(ROOT, ignore_errors=True)
    shutil.copytree(FIX, ROOT, dirs_exist_ok=True)
    S.update(fail=set(), hang=set(), html=False, inflight=0, max=0, delay=0.0)
    S["log"].clear()


def main():
    with sync_playwright() as p:
        ran = 0
        for name, eng in (("chromium", p.chromium), ("webkit", p.webkit)):   # webkit — движок Safari (iPhone)
            try:
                br = eng.launch()
            except Exception:  # noqa: BLE001
                print(f"viewer_fast_load: {name} — пропуск, движка нет")
                continue
            reset_root()
            run(br, name)
            br.close()
            ran += 1
    srv.shutdown()
    shutil.rmtree(ROOT, ignore_errors=True)
    if not ran:
        print("viewer_fast_load: пропуск — нет ни одного движка")
        return 0
    print(f"viewer_fast_load: {passed} OK, {failed} FAIL")
    return 1 if failed else 0


def run(br, eng):
    global check
    _check = check

    def check(name, cond, extra=""):  # noqa: F811 — имя движка в каждой строке
        _check(f"[{eng}] {name}", cond, extra)

    ctx = br.new_context(service_workers="block", viewport={"width": 390, "height": 860}, is_mobile=True, has_touch=True)
    ctx.add_init_script("window.PIV_NET_TIMEOUT_MS = 1500;")
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))

    # 1. первое открытие
    S["delay"] = 0.05
    st = open_viewer(pg)
    S["delay"] = 0.0
    n_files = len(files())
    check("1: все файлы скачаны", st and st["fetched"] == st["files"] and n_files >= st["files"] > 0, f"{st} / {n_files}")
    check("1: листинги — JSON и без метки в адресе",
          listings() and all("application/json" in e["accept"] for e in listings())
          and not any("_=" in e["url"] or "cb=" in e["url"] for e in S["log"]))
    check(f"1: не больше 8 запросов разом (было {S['max']})", 1 < S["max"] <= 8)
    copy1 = pg.evaluate(COPY)
    check("1: копия на устройстве записана — по файлу на каждый", len(copy1) == st["files"]
          and SNAP in copy1 and OLD_WR in copy1, f"{len(copy1)}")
    main1 = pg.evaluate(MAIN)

    # 2. повторное открытие — только листинги
    st = open_viewer(pg)
    check(f"2: файлы не запрошены ({len(files())}) — всё с устройства", not files() and st["fromDevice"] == st["files"])
    check("2: листинги запрошены", len(listings()) >= 5)
    check("2: раздел тот же, что из сети", pg.evaluate(MAIN) == main1)
    check("2: предупреждений нет", warnings(pg) == "", warnings(pg))

    # 3. файл изменился → скачан только он
    time.sleep(0.02)
    touch(SNAP, " \n")                            # пробелы в конце JSON — тот же снапшот, другая версия
    st = open_viewer(pg)
    check("3: скачан только изменившийся снапшот", [e["path"] for e in files()] == [SNAP], str([e["path"] for e in files()]))
    copy3 = pg.evaluate(COPY)
    check("3: в копии новая версия", copy3[SNAP]["ver"] != copy1[SNAP]["ver"]
          and copy3[SNAP]["n"] == len((ROOT / SNAP).read_text(encoding="utf-8")))

    # 4. файл удалён на сервере
    old_wr_text = (ROOT / OLD_WR).read_text(encoding="utf-8")
    (ROOT / OLD_WR).unlink()
    st = open_viewer(pg)
    copy4 = pg.evaluate(COPY)
    check("4: удалённый файл пропал из копии", OLD_WR not in copy4 and len(copy4) == len(copy1) - 1)
    check("4: и со страницы", not pg.evaluate("() => [state.data.weeklyReviewCurrent, ...state.data.weeklyReviewHistory].some(r => r && r.name === 'weekly-review-stock-2026-10-01.yaml')")
          and pg.evaluate("() => !!state.data.weeklyReviewCurrent")
          and st["files"] == len(copy1) - 1)
    (ROOT / OLD_WR).write_text(old_wr_text, encoding="utf-8")
    open_viewer(pg)

    # 5. листинг папки не ответил → копия + предупреждение
    S["fail"] = {"Portfolio/weekly-reviews/"}
    st = open_viewer(pg)
    w = warnings(pg)
    check("5: файлы папки показаны из копии", st["stale"] == 1 and not files(), f"{st}")
    # v3.50.0: короткая строка без перечня путей (было — простыня из 221 пути на телефоне)
    check("5: короткое предупреждение «копия с этого устройства», без «Не загрузилось» и без путей",
          "копия с этого устройства" in w and "Portfolio/" not in w and "Не загрузилось" not in w, w)
    check("5: обзоры на месте (раздел «Изменения» строится)", pg.evaluate(MAIN) == main1 or len(pg.evaluate(MAIN)) > 200)
    S["fail"] = set()

    # 6. изменившийся файл не скачался: старая копия; без копии — «Не загрузилось»
    touch(WR_NEW, "\n# fast-load-mark\n")
    S["fail"] = {WR_NEW}
    st = open_viewer(pg)
    w = warnings(pg)
    check("6: старая копия изменившегося файла + предупреждение", st["stale"] == 1
          and "копия с этого устройства" in w, w)
    check("6: копия не затёрта сбоем", not pg.evaluate(COPY)[WR_NEW]["mark"])
    S["fail"] = set()
    st = open_viewer(pg)
    check("6: связь вернулась — новая версия в копии, предупреждений нет",
          pg.evaluate(COPY)[WR_NEW]["mark"] and warnings(pg) == "", warnings(pg))

    ctx2 = br.new_context(service_workers="block", viewport={"width": 1280, "height": 900})
    pg2 = ctx2.new_page()
    pg2.on("pageerror", lambda e: errs.append(str(e)))
    S["fail"] = {OLD_WR}
    open_viewer(pg2)
    w = warnings(pg2)
    check("6: нет копии и не скачалось → «Не загрузилось» с именем файла", "Не загрузилось с сервера" in w and OLD_WR in w, w)
    S["fail"] = set()

    # 7. висящий запрос — таймаут, повтор, загрузка завершилась
    touch(SNAP, " ")
    S["hang"] = {SNAP}
    t0 = time.monotonic()
    st = open_viewer(pg)
    dt = time.monotonic() - t0
    check(f"7: висящий запрос оборван по таймауту и повторён ({dt:.1f} с)",
          st["fetched"] == 1 and sum(e["path"] == SNAP for e in S["log"]) == 2 and warnings(pg) == "" and dt < 12)

    # 8. другой пароль → копия чужая
    pg.evaluate("localStorage.setItem('hub-auth', btoa('hubuser:other'))")
    st = open_viewer(pg)
    check("8: другой токен — всё скачано заново", st["fetched"] == st["files"] and len(files()) == st["files"])
    marks = pg.evaluate("async () => { await state.fileCacheWrite; return [...(await FileCache.all()).values()].map(r => r.fp); }")
    check("8: в копии только записи нового токена", len(set(marks)) == 1 and marks[0] == pg.evaluate("fileCacheMark()"))
    pg.evaluate("localStorage.removeItem('hub-auth')")
    open_viewer(pg)

    # 9. «Обновить»: один раз — дёшево; второй в течение минуты — полная перекачка
    pg.evaluate("localStorage.removeItem('piv-refresh-at')")
    S["log"].clear()
    with pg.expect_navigation():
        pg.click("#btn-refresh")
    pg.wait_for_selector("#tabs .ui-tab", timeout=30000)
    st = pg.evaluate("() => state.netStats")
    check(f"9: «Обновить» — листинги заново, файлы с устройства ({len(files())})", not files() and listings() and not st["full"])
    S["log"].clear()
    with pg.expect_navigation():
        pg.click("#btn-refresh")
    pg.wait_for_selector("#tabs .ui-tab", timeout=30000)
    st = pg.evaluate("() => state.netStats")
    check("9: второе «Обновить» за минуту — все файлы заново", st["full"] and st["fetched"] == st["files"]
          and len(files()) == st["files"])
    S["log"].clear()
    pg.goto(URL)
    pg.wait_for_selector("#tabs .ui-tab", timeout=30000)
    check("9: полная перекачка разовая — следующее открытие снова с устройства",
          not pg.evaluate("() => state.netStats.full") and not files())

    # 10. HTML-листинг: версий нет — файлы качаются всегда
    S["html"] = True
    st = open_viewer(pg)
    check("10: HTML-листинг — все файлы с сервера", st["fetched"] == st["files"] and len(files()) == st["files"])
    # 304 — экономия трафика, не корректность; WebKit Playwright условных запросов не шлёт вовсе (нет
    # If-None-Match, проверено 2026-10-26) — там файл просто приходит целиком
    if eng == "chromium":
        check("10: условные запросы — неизменившиеся приходят 304", any(e.get("status") == 304 for e in files()))
    check("10: раздел тот же", len(pg.evaluate(MAIN)) > 200)
    S["html"] = False

    # 12. копии на устройстве нет вовсе (IndexedDB бросает) или она висит (WebKit) — загрузка как без неё
    for label, init in (("IndexedDB недоступна",
                         "Object.defineProperty(window, 'indexedDB', { get() { throw new Error('нет IDB'); } });"),
                        ("IndexedDB висит",
                         "Object.defineProperty(window, 'indexedDB', { get() { return { open() { return {}; } }; } });")):
        c3 = br.new_context(service_workers="block", viewport={"width": 1280, "height": 900})
        c3.add_init_script(init)
        pg3 = c3.new_page()
        pg3.on("pageerror", lambda e: errs.append(str(e)))
        t0 = time.monotonic()
        st = open_viewer(pg3)
        dt = time.monotonic() - t0
        check(f"12: {label} — всё с сервера, раздел построен ({dt:.1f} с)",
              st["fetched"] == st["files"] and len(pg3.evaluate(MAIN)) > 200 and warnings(pg3) == "" and dt < 15)
        c3.close()

    # 13. одним запросом (/api/pv/sync, v3.47.0) — тот же контекст: копия из режима листингов
    S["sync"] = True
    st = open_viewer(pg)
    check(f"13: через sync — один POST, ни листингов (кроме пробы входа), ни файлов ({st})",
          st["via"] == "sync" and len(posts()) == 1 and not files() and len(listings()) <= 1)
    check("13: версии копии из листингов серверу не подходят — всё пришло в ответе (разово)",
          st["fromSync"] == st["files"] and posts()[0]["have"] == 0)
    check("13: раздел построен", len(pg.evaluate(MAIN)) > 200 and warnings(pg) == "")
    st = open_viewer(pg)
    check(f"13: повторно — один POST с версиями, содержимого 0 ({posts()[0].get('have')} версий)",
          len(posts()) == 1 and posts()[0]["sent"] == 0 and posts()[0]["have"] == st["files"]
          and st["fromDevice"] == st["files"] and not files())
    touch(SNAP, "  ")
    st = open_viewer(pg)
    check("13: изменился файл — в ответе только он", posts()[0]["sent"] == 1 and st["fromSync"] == 1 and not files())
    check("13: и он в копии", pg.evaluate(COPY)[SNAP]["n"] == len((ROOT / SNAP).read_text(encoding="utf-8")))
    S["pv_max"] = 1
    c4 = br.new_context(service_workers="block", viewport={"width": 1280, "height": 900})
    pg4 = c4.new_page()
    pg4.on("pageerror", lambda e: errs.append(str(e)))
    st = open_viewer(pg4)
    check(f"13: предел ответа — пачками, повторами с have ({len(posts())} POST на {st['files']} файлов)",
          st["via"] == "sync" and st["fromSync"] == st["files"] and len(posts()) == st["files"] and not files())
    c4.close()
    S["pv_max"] = None
    S["fail"] = {"api/pv/sync"}
    st = open_viewer(pg)
    check(f"13: sync упал (500) — листинги, как в 3.46.0 ({st['via']})",
          st["via"] == "listings" and len(listings()) >= 5 and warnings(pg) == "")
    S["fail"] = set()
    S["sync"] = False
    st = open_viewer(pg)
    check("13: старый сайдкар (404) — листинги без повтора", st["via"] == "listings" and not posts())

    check("11: ошибок JS нет", not errs, str(errs[:3]))
    ctx.close()
    ctx2.close()
    check = _check


if __name__ == "__main__":
    sys.exit(main())
