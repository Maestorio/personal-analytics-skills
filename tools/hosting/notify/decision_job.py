"""Решение владельца с сайта (hub-notify): карточка бумаги во вьюере → `Portfolio/decisions/*.json` (`decision@1`).

    POST /api/pf/decision {"key", "verdict", "target_pct"?, "review_by"?, "note", "confidence"?}
        → 200 {"saved": путь, "decision": запись} | 400 (поле не прошло) | 409 (решение этой минуты по ключу уже есть)

Запись собирает та же функция, что и CLI `decision_write.py owner` (`decision_write.build_owner`): `source.kind: owner`,
`author: owner`, `conditions_resolved` — только условия ключа, ждущие владельца (`waits_owner`), `recorded_at` — МСК
сервера. Правила сайта сверх схемы: `review_by` — дата, по умолчанию сегодня + 60 дней, допустимо 7–180 дней;
`note` обязательна, 20–200 знаков; ключ — только A–Z, 0–9, «.», «-» (так устроен путь в JOB_WHITELIST hub-api).

Файл решения — всегда новый: существующий не перезаписывается (проверка read_fn до записи и `jobs.save_new`
с base_hash = null, где 409 hub-api не повторяется с новым хэшем). Том Claude-Memory у hub-notify на чтение —
запись только через save_fn (в бою `jobs.save_new` → hub-api /api/job/save). Журнал решений подхватит запись
при следующем «Сохранить» снапшота (pf_build.publish_journal): пересборка здесь требует выгрузки сделок прогона.

Только stdlib (+ PyYAML внутри decision_write, как у остального сайта).
"""
import importlib
import json
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MSK = timezone(timedelta(hours=3))
DECISIONS_DIR = "Portfolio/decisions"
KEY_RE = re.compile(r"^[A-Z0-9.-]+$")           # = путь в JOB_WHITELIST: ^Portfolio/decisions/…T\d{4}-[A-Z0-9.-]+\.json$
NOTE_MIN, NOTE_MAX = 20, 200
REVIEW_DEFAULT, REVIEW_MIN, REVIEW_MAX = 60, 7, 180
LOCK = threading.Lock()


class AlreadyExists(Exception):
    """Файл решения этой минуты уже есть (save_fn не перезаписывает)."""


def _dw():
    """decision_write.py: в контейнере — pdl/skills/save-to-library/scripts, в репозитории — skills/save-to-library/scripts."""
    try:
        return importlib.import_module("decision_write")
    except ImportError:
        pass
    cands = [HERE / "pdl" / "skills/save-to-library/scripts"]
    if len(HERE.parents) > 2:
        cands.append(HERE.parents[2] / "skills/save-to-library/scripts")
    for d in cands:
        if (d / "decision_write.py").is_file():
            sys.path.insert(0, str(d))
            return importlib.import_module("decision_write")
    raise ImportError("нет decision_write.py — выполни tools/deploy.zsh")


def _iso(now=None):
    return (now or datetime.now(MSK)).astimezone(MSK).strftime("%Y-%m-%dT%H:%M:%S+03:00")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def parse_body(body, today):
    """Тело запроса → entry для build_owner. BadRequest — текст для владельца."""
    if not isinstance(body, dict):
        raise ValueError("тело: ожидается объект")
    key = body.get("key")
    if not isinstance(key, str) or not KEY_RE.match(key):
        raise ValueError("key: ожидается тикер или ISIN (A–Z, 0–9, «.», «-»)")
    dw = _dw()
    verdict = body.get("verdict")
    if verdict not in dw.ds.CODELISTS["verdict"]:
        raise ValueError(f"verdict: {verdict!r} нет в кодлисте ({', '.join(dw.ds.CODELISTS['verdict'])})")
    tp = body.get("target_pct")
    if tp is not None and not (_num(tp) and 0 <= tp <= 100):
        raise ValueError("target_pct: число 0..100 или пусто")
    note = body.get("note")
    note = note.strip() if isinstance(note, str) else ""
    if len(note) < NOTE_MIN:
        raise ValueError(f"note: напиши, почему, — не меньше {NOTE_MIN} знаков (сейчас {len(note)})")
    if len(note) > NOTE_MAX:
        raise ValueError(f"note: не больше {NOTE_MAX} знаков (сейчас {len(note)})")
    t0 = datetime.strptime(today, "%Y-%m-%d").date()
    rb = body.get("review_by")
    if rb is None or rb == "":
        rb = (t0 + timedelta(days=REVIEW_DEFAULT)).isoformat()
    try:
        days = (datetime.strptime(rb, "%Y-%m-%d").date() - t0).days if isinstance(rb, str) else None
    except ValueError:
        days = None
    if days is None:
        raise ValueError("review_by: ожидается дата ГГГГ-ММ-ДД")
    if not REVIEW_MIN <= days <= REVIEW_MAX:
        raise ValueError(f"review_by: срок пересмотра — от {REVIEW_MIN} до {REVIEW_MAX} дней от сегодня (сейчас {days})")
    conf = body.get("confidence")
    if conf is not None and not (_num(conf) and 0 <= conf <= 1):
        raise ValueError("confidence: число 0..1 или пусто")
    return {"key": key, "verdict": verdict, "target_pct": tp, "review_by": rb, "note": note, "confidence": conf}


def post_decision(root, body, save_fn, now, read_fn=None):
    """Решение владельца с сайта → Portfolio/decisions/{дата}T{ЧЧММ}-{KEY}.json. → (код, объект)."""
    dw = _dw()
    now_s = _iso(now)
    try:
        entry = parse_body(body, now_s[:10])
        d, _missing = dw.build_owner(str(root), entry, now_s)
    except ValueError as e:
        return 400, {"error": str(e)}
    except dw.CmdError as e:
        return 400, {"error": str(e), **e.extra}
    rel = f"{DECISIONS_DIR}/{d['id']}.json"
    with LOCK:
        if read_fn is not None:
            exists = read_fn(rel)[0] is not None
        else:
            exists = (Path(root) / rel).is_file()
        if exists:
            return 409, {"error": "решение этой минуты по бумаге уже есть — подожди минуту", "path": rel}
        try:
            save_fn(rel, json.dumps(d, ensure_ascii=False, indent=2) + "\n")
        except AlreadyExists:
            return 409, {"error": "решение этой минуты по бумаге уже есть — подожди минуту", "path": rel}
    return 200, {"saved": rel, "decision": d}
