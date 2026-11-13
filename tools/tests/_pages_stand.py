"""Общий стенд браузерных тестов страниц кабинета (TST-1, 03.11).

Кросс-страничные тесты ui-kit (nav_layout, topbar_layout, reader_layout, select_layout, nav_top_esc) поднимали
каждый свой HTTP-сервер, гнали Chromium и WebKit по очереди и ждали фиксированными паузами. Здесь — общее:

  serve(handler, directory, key, quiet) — HTTP-сервер на эфемерном порту: очередь соединений 128 (у
      ThreadingHTTPServer по умолчанию 5) и keep-alive HTTP/1.1; один сервер на ключ за процесс, без ключа —
      новый на каждый вызов. Стенд всех браузерных тестов (кроме test_offline) и API-стендов hub-api. Причина «моргания» под нагрузкой
      (замер 03.11): при тысячах новых TCP-соединений на loopback в секунду (вьюер — ~700 файлов за загрузку,
      в HTTP/1.0 по соединению на файл) SYN теряются по всей машине — даже простаивающий сервер в чужом
      процессе отвечал через 2–4 с или «Operation timed out» за 7,8 с. Вероятное узкое место — сетевой
      фильтр Kaspersky (на машине его endpoint-security расширение). С keep-alive тот же замер — 0,01 с;
  fixture(file, marker) — подготовка стенда соседнего теста без его проверок, один раз за процесс;
  Checker — счётчик проверок, безопасный для потоков;
  per_engine(fn) — Chromium и WebKit параллельно, каждый в своём потоке со своим sync_playwright (так
      Playwright разрешает), браузер один на движок; движка нет — честный пропуск; PAGES_STAND_SERIAL=1 —
      по очереди (для отладки);
  SYNOLOGY_LOCK — вьюер на настоящих данных Synology движки проходят по очереди;
  settle / frames / scroll_still — ожидание по условию (загрузка и шрифты + условие JS; два кадра; конец
      прокрутки) вместо фиксированных пауз; settle, не дождавшись, печатает «settle: …» и не падает.

Файлы тестов остаются отдельными (реестр не меняется); стенд только общий.
"""
from __future__ import annotations

import functools
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


_NET_ERRORS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)


class _Srv(ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True
    quiet = True

    def handle_error(self, request, client_address):
        # браузер рвёт соединения при закрытии вкладки — не шум; quiet=False — прочие ошибки обработчика
        # печатаются трассировкой (API-стенды, test_viewer_fast_load)
        if not self.quiet and not isinstance(sys.exc_info()[1], _NET_ERRORS):
            super().handle_error(request, client_address)


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_head(self):
        # В HTTP/1.1 браузер шлёт условные запросы, а SimpleHTTPRequestHandler сверяет If-Modified-Since с mtime
        # с точностью до секунды: файл, переписанный тестом в ту же секунду, ушёл бы ответом 304 — устаревшим
        # (Caddy сверяет ETag). Поэтому раздача папки всегда отвечает 200.
        del self.headers["If-Modified-Since"]
        return super().send_head()


def keepalive(handler):
    """Обработчик с HTTP/1.1 keep-alive: браузер держит несколько соединений и гонит запросы по ним, а не
    открывает новое TCP-соединение на каждый файл (вьюер — ~700 файлов за загрузку). Ответ без
    Content-Length закрывает соединение, как в HTTP/1.0 (иначе браузер ждал бы конца тела). Ответ на запрос
    с телом (POST/PUT…) тоже закрывает: обработчик стенда мог не дочитать тело, и его остаток стал бы началом
    следующего запроса на том же соединении."""
    class KeepAlive(handler):
        protocol_version = "HTTP/1.1"

        def send_header(self, keyword, value):
            if keyword.lower() == "content-length":
                self._ka_len = True
            super().send_header(keyword, value)

        def end_headers(self):
            if not getattr(self, "_ka_len", False) or self.command not in ("GET", "HEAD"):
                super().send_header("Connection", "close")
                self.close_connection = True
            self._ka_len = False
            super().end_headers()
    KeepAlive.__name__ = "KeepAlive" + handler.__name__
    return KeepAlive


_servers: dict = {}
_lock = threading.RLock()   # fixture() может звать serve() внутри себя


def serve(handler=None, directory=None, key=None, quiet=True):
    """(сервер, база «http://127.0.0.1:порт»). handler — класс обработчика (с directory — класс на основе
    SimpleHTTPRequestHandler, раздающий эту папку); без handler — раздача directory (по умолчанию корень
    репозитория, ключ — папка). key — один сервер на ключ за процесс; без ключа — новый сервер. quiet=False —
    ошибки обработчика (кроме обрыва соединения) печатаются. Соединения — keep-alive."""
    if handler is None:
        directory = str(directory or REPO)
        handler = functools.partial(keepalive(Quiet), directory=directory)
        key = key or ("dir", directory)
    elif isinstance(handler, type):
        handler = keepalive(handler)
        if directory is not None:
            handler = functools.partial(handler, directory=str(directory))
    with _lock:
        if key is not None and key in _servers:
            return _servers[key]
        srv = _Srv(("127.0.0.1", 0), handler)
        srv.quiet = quiet
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        out = (srv, f"http://127.0.0.1:{srv.server_address[1]}")
        if key is not None:
            _servers[key] = out
        return out


_fixtures: dict = {}


def fixture(name, marker):
    """Подготовка стенда из соседнего теста (код до marker) — без запуска его проверок; один раз."""
    with _lock:
        if name not in _fixtures:
            path = HERE / name
            ns = {"__file__": str(path), "__name__": "fixture_" + path.stem}
            exec(compile(path.read_text(encoding="utf-8").split(marker)[0], str(path), "exec"), ns)
            _fixtures[name] = ns
        return _fixtures[name]


class Checker:
    """check(name, cond) с подсчётом; безопасен, когда движки идут в разных потоках."""

    def __init__(self):
        self.passed = self.failed = 0
        self._lock = threading.Lock()

    def __call__(self, name, cond, extra=""):
        with self._lock:
            if cond:
                self.passed += 1
            else:
                self.failed += 1
                print(f"  FAIL: {name}{(' ' + extra) if extra else ''}", flush=True)
        return bool(cond)


def per_engine(fn, engines=("chromium", "webkit")):
    """fn(eng_name, browser) на каждом движке; движки — параллельно, каждый в своём потоке.
    Исключение в потоке не теряется: пробрасывается после завершения всех движков."""
    from playwright.sync_api import sync_playwright

    errors = []

    def one(name):
        try:
            with sync_playwright() as p:
                try:
                    browser = getattr(p, name).launch()
                except Exception as e:   # движок не установлен — честный пропуск
                    print(f"  {name}: пропуск — {str(e).splitlines()[0][:80]}", flush=True)
                    return
                try:
                    fn(name, browser)
                finally:
                    browser.close()
        except BaseException as e:   # noqa: BLE001
            errors.append((name, e))

    if os.environ.get("PAGES_STAND_SERIAL") or len(engines) == 1:
        for n in engines:
            one(n)
    else:
        ts = [threading.Thread(target=one, args=(n,)) for n in engines]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    if errors:
        name, e = errors[0]
        raise RuntimeError(f"движок {name}: {e!r}") from e



READY = "document.readyState === 'complete' && (!document.fonts || document.fonts.status === 'loaded')"


def settle(pg, cond="true", timeout=10000, margin=150):
    """Дождаться готовности страницы вместо фиксированной паузы: загрузка и шрифты, условие cond
    (выражение JS), два кадра отрисовки и короткий запас margin мс. Не бросает: вернёт False, если
    условие не наступило за timeout, — тогда решает проверка теста, как и при прежней паузе."""
    ok = True
    try:
        pg.wait_for_function(f"() => {READY} && ({cond})", timeout=timeout)
    except Exception:   # noqa: BLE001
        ok = False
        # не падение, но потерянные секунды: видно в выводе теста, чтобы условие поправить
        print(f"  settle: условие не наступило за {timeout} мс — {cond[:90]}", flush=True)
    try:
        pg.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(1))))")
    except Exception:   # noqa: BLE001
        pass
    if margin:
        pg.wait_for_timeout(margin)
    return ok


# Вьюер портфеля в select_layout и nav_top_esc читает настоящие данные с Synology-зеркала (десятки файлов на
# загрузку). Два движка разом грузили его дольше 20 с и падали по таймауту ожидания вкладок — поэтому
# вьюерные части движки проходят по очереди (остальные страницы — параллельно).
SYNOLOGY_LOCK = threading.Lock()


def frames(pg, margin=0):
    """Два кадра отрисовки (layout, наблюдатели и обработчики после вставки разметки отработали) и запас
    margin мс — вместо фиксированной паузы после синхронной перерисовки."""
    pg.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(1))))")
    if margin:
        pg.wait_for_timeout(margin)


def scroll_still(pg, el_js="document.scrollingElement", limit_ms=2000, margin=100):
    """Дождаться конца прокрутки (плавный прыжок к главе) вместо фиксированной паузы: позиция el_js сдвинулась
    и 8 кадров не меняется; не сдвинулась за 400 мс — прокрутки нет. Потом запас margin мс (подсветка и
    подписи обновляются по событию scroll)."""
    pg.evaluate("""(limit) => new Promise(res => {
      const pos = () => { const e = %s; return e ? e.scrollTop : 0; };
      let last = pos(), still = 0, moved = false; const t0 = performance.now();
      const f = () => { const p = pos(); if (p !== last) { moved = true; still = 0; last = p; } else still++;
        const dt = performance.now() - t0;
        if ((moved && still >= 8) || (!moved && dt > 400) || dt > limit) return res(p);
        requestAnimationFrame(f); };
      requestAnimationFrame(f); })""" % el_js, limit_ms)
    if margin:
        pg.wait_for_timeout(margin)
