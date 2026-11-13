"""Задачи сайта по расписанию (API-1, 2026-10-21): общее для цен eShop и макросреза.

hub-notify читает Claude-Memory только на чтение — результат задач пишет hub-api (зона
/api/job/*, только изнутри docker-сети): перезапись с base_hash и копией прежней версии
в .versions/, журнал прогонов — дописыванием строки в _jobs/log-ГГГГ-ММ.jsonl.

Пробный месяц (решение владельца 2026-10-21): каждая перезапись оставляет копию, каждый
прогон — строку журнала (что, когда, итог, сколько заняло, ошибка). Откат — восстановить
файл из .versions/ и выключить задачу (JOBS_OFF в окружении hub-notify).

Только stdlib.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3))


def now_iso(now=None):
    """Единственная запись времени: `ГГГГ-ММ-ДДTЧЧ:ММ:СС+03:00` (МСК, schema.md §1 п.4)."""
    return (now or datetime.now(MSK)).astimezone(MSK).strftime("%Y-%m-%dT%H:%M:%S+03:00")
API = os.environ.get("NOTIFY_API_URL", "http://hub-api:8000").rstrip("/")
# Выключатель на время пробного месяца: «eshop,macro» — обе задачи не запускаются.
JOBS_OFF = {x.strip() for x in os.environ.get("JOBS_OFF", "").split(",") if x.strip()}


class SaveError(Exception):
    pass


class ExistsError(SaveError):
    """Новый файл уже существует (save_new не перезаписывает)."""


class ConflictError(SaveError):
    """save_if: хэш файла в hub-api не равен base_hash (файл сменился)."""


def _call(method, path, payload=None, timeout=30):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except ValueError:
            return e.code, {}


def read(path):
    """→ (content, hash) или (None, None), если файла ещё нет."""
    code, body = _call("GET", "/api/job/file?path=" + urllib.parse.quote(path))
    if code == 404:
        return None, None
    if code != 200:
        raise SaveError(f"read {path}: HTTP {code} {body.get('error', '')}")
    return body["content"], body["hash"]


def save(path, content, retries=2):
    """Записать файл задачи. Гонка (409) — перечитать хэш и повторить: задача —
    единственный писатель этих файлов, конфликт значит только «файл сменился между
    чтением и записью»."""
    _, h = read(path)
    for _ in range(retries + 1):
        code, body = _call("POST", "/api/job/save", {"path": path, "content": content, "base_hash": h})
        if code == 200:
            return body["hash"]
        if code == 409:
            h = body.get("current_hash")
            continue
        raise SaveError(f"save {path}: HTTP {code} {body.get('error', '')} {body.get('detail', '')}".strip())
    raise SaveError(f"save {path}: конфликт версий не разрешился")


def save_if(path, content, base_hash):
    """Записать файл при условии base_hash (без повтора с чужим хэшем): 409 — ConflictError. Для файлов, которые правят
    и скилл, и сайт (conditions.yaml): запись строилась от конкретных прочитанных байтов."""
    code, body = _call("POST", "/api/job/save", {"path": path, "content": content, "base_hash": base_hash})
    if code == 200:
        return body["hash"]
    if code == 409:
        raise ConflictError(f"save {path}: файл изменился")
    raise SaveError(f"save {path}: HTTP {code} {body.get('error', '')} {body.get('detail', '')}".strip())


def save_new(path, content):
    """Записать НОВЫЙ файл (base_hash = null): существует — ExistsError, перезаписи нет и повтора с чужим хэшем нет.
    Для файлов-записей, которые не правятся (решения владельца)."""
    code, body = _call("POST", "/api/job/save", {"path": path, "content": content, "base_hash": None})
    if code == 200:
        return body["hash"]
    if code == 409:
        raise ExistsError(f"save {path}: файл уже есть")
    raise SaveError(f"save {path}: HTTP {code} {body.get('error', '')} {body.get('detail', '')}".strip())


def log(job, status, started, **extra):
    """Строка журнала прогона. Ошибка записи журнала не роняет задачу — только stdout."""
    now = datetime.now(MSK)
    rec = {"ts": now_iso(now), "job": job, "status": status,
           "sec": round(time.monotonic() - started, 1), **extra}
    line = json.dumps(rec, ensure_ascii=False, default=str)
    print("job", line, flush=True)
    try:
        code, body = _call("POST", "/api/job/append",
                           {"path": f"_jobs/log-{now:%Y-%m}.jsonl", "line": line})
        if code != 200:
            print(f"job log: HTTP {code} {body}", flush=True)
    except OSError as e:
        print(f"job log: {e}", flush=True)
    return rec
