#!/usr/bin/env python3
"""
netcache.py — запись и повтор ответов сети для скриптов загрузчика (API-1b, PR-2).

Зачем: сверка «скилл против скрипта» (docs/api-migration/implementation-brief.md, PR-4)
должна идти на ТЕХ ЖЕ ответах MOEX ISS и ЦБ. Отдельный поход в сеть через 10 минут даёт
другие цены — сверка тонет в шуме. Все сетевые вызовы загрузчика идут через
urllib.request.urlopen (portfolio_returns, per_security_xirr, iis_returns, market_series,
moex_quotes), поэтому одна подмена этой функции покрывает всю цепочку без правки
расчётных скриптов.

Режимы (каталог DIR — `net/` пакета прогона):
  record — настоящий запрос; тело и заголовки ответа сохраняются в DIR.
  replay — ответ берётся из DIR; сеть не трогается НИКОГДА. Нет записи → URLError
           с адресом (скрипт падает или уходит в свой фолбэк — как при сбое сети,
           молча в сеть не идёт).

CLI — обёртка запуска скрипта:
  python3 netcache.py run --record DIR -- scripts/portfolio_returns.py --trades … --format json
  python3 netcache.py run --replay DIR -- scripts/portfolio_returns.py …
  python3 netcache.py ls DIR          # что записано

Ключ записи — метод + URL с отсортированными параметрами запроса + sha256 тела.
Только stdlib.
"""
from __future__ import annotations

import argparse
import email.message
import hashlib
import io
import json
import os
import runpy
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

INDEX = "index.json"
_lock = threading.Lock()
_real_urlopen = urllib.request.urlopen


def _canon_url(url: str) -> str:
    """URL с отсортированными параметрами: порядок параметров не меняет ключ."""
    p = urllib.parse.urlsplit(url)
    q = urllib.parse.urlencode(sorted(urllib.parse.parse_qsl(p.query, keep_blank_values=True)))
    return urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), p.path, q, ""))


def _request_parts(url_or_req, data) -> tuple[str, str, bytes]:
    if isinstance(url_or_req, urllib.request.Request):
        url = url_or_req.full_url
        body = url_or_req.data if data is None else data
        method = url_or_req.get_method()
    else:
        url = str(url_or_req)
        body = data
        method = "POST" if body is not None else "GET"
    if isinstance(body, str):
        body = body.encode("utf-8")
    return method.upper(), url, body or b""


def request_key(method: str, url: str, body: bytes) -> str:
    h = hashlib.sha256()
    h.update(method.encode())
    h.update(b"\n")
    h.update(_canon_url(url).encode())
    h.update(b"\n")
    h.update(hashlib.sha256(body).digest())
    return h.hexdigest()[:32]


class _Response(io.BytesIO):
    """Минимальная замена http.client.HTTPResponse: read/status/getcode/headers/info,
    контекстный менеджер. Скрипты загрузчика больше ничего не используют."""

    def __init__(self, body: bytes, status: int, headers: dict, url: str):
        super().__init__(body)
        self.status = status
        self.code = status
        self.reason = "OK" if status == 200 else ""
        self.url = url
        msg = email.message.Message()
        for k, v in headers.items():
            msg[k] = v
        self.headers = msg
        self.msg = msg

    def getcode(self):
        return self.status

    def info(self):
        return self.headers

    def geturl(self):
        return self.url

    def getheader(self, name, default=None):
        return self.headers.get(name, default)


def _load_index(d: Path) -> dict:
    f = d / INDEX
    if not f.exists():
        return {}
    return json.loads(f.read_text(encoding="utf-8"))


def _save_index(d: Path, idx: dict) -> None:
    tmp = d / (INDEX + ".tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, d / INDEX)


def install(mode: str, directory: str | os.PathLike) -> None:
    """Подменить urllib.request.urlopen в текущем процессе."""
    if mode not in ("record", "replay"):
        raise ValueError(f"netcache: неизвестный режим {mode!r}")
    d = Path(directory)
    if mode == "record":
        d.mkdir(parents=True, exist_ok=True)
        if not (d / INDEX).exists():          # пустой индекс: все запросы упали — тоже результат
            _save_index(d, {})
    elif not (d / INDEX).exists():
        raise FileNotFoundError(f"netcache: в {d} нет {INDEX} — нечего повторять")
    else:
        # Повтор не ждёт: паузы в скриптах загрузчика — только между повторами запроса,
        # а ответ при повторе всё равно тот же.
        time.sleep = lambda _s: None

    def urlopen(url, data=None, timeout=None, *args, **kwargs):
        method, full_url, body = _request_parts(url, data)
        key = request_key(method, full_url, body)
        if mode == "replay":
            with _lock:
                entry = _load_index(d).get(key)
            if entry is None:
                raise urllib.error.URLError(f"netcache replay: нет записи для {method} {full_url}")
            raw = (d / entry["file"]).read_bytes()
            if entry["status"] >= 400:
                raise urllib.error.HTTPError(full_url, entry["status"], "netcache replay",
                                             entry.get("headers") or {}, io.BytesIO(raw))
            return _Response(raw, entry["status"], entry.get("headers") or {}, full_url)

        # record
        try:
            resp = _real_urlopen(url, data, timeout, *args, **kwargs) if timeout is not None \
                else _real_urlopen(url, data, *args, **kwargs)
            raw = resp.read()
            status = getattr(resp, "status", None) or resp.getcode() or 200
            headers = {k: v for k, v in resp.headers.items()
                       if k.lower() in ("content-type", "content-encoding", "content-length")}
            resp.close()
        except urllib.error.HTTPError as e:
            raw = e.read() if e.fp else b""
            status, headers = e.code, {}
            _store(d, key, method, full_url, status, headers, raw)
            raise
        _store(d, key, method, full_url, status, headers, raw)
        return _Response(raw, status, headers, full_url)

    urllib.request.urlopen = urlopen


def _store(d: Path, key, method, url, status, headers, raw) -> None:
    fname = f"{key}.bin"
    (d / fname).write_bytes(raw)
    with _lock:
        idx = _load_index(d)
        idx[key] = {"method": method, "url": _canon_url(url), "status": status,
                    "headers": headers, "file": fname, "bytes": len(raw)}
        _save_index(d, idx)


def run_script(mode: str, directory: str, script: str, argv: list[str]) -> None:
    """Запустить скрипт как __main__ с подменённой сетью (тот же процесс)."""
    install(mode, directory)
    script_path = str(Path(script).resolve())
    sys.argv = [script_path, *argv]
    sys.path.insert(0, str(Path(script_path).parent))
    runpy.run_path(script_path, run_name="__main__")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="запустить скрипт с записью или повтором сети")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--record", metavar="DIR")
    g.add_argument("--replay", metavar="DIR")
    r.add_argument("script")
    r.add_argument("args", nargs=argparse.REMAINDER)
    ls = sub.add_parser("ls", help="показать записанное")
    ls.add_argument("dir")
    a = ap.parse_args()
    if a.cmd == "ls":
        for k, e in sorted(_load_index(Path(a.dir)).items(), key=lambda kv: kv[1]["url"]):
            print(f'{e["status"]} {e["method"]} {e["url"]} ({e["bytes"]} B)')
        return 0
    args = a.args[1:] if a.args[:1] == ["--"] else a.args
    mode, d = ("record", a.record) if a.record else ("replay", a.replay)
    run_script(mode, d, a.script, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
