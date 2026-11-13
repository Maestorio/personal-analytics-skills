"""Условие-напоминание владельца с сайта (hub-notify): «произошло X → напомни Y» → `Portfolio/conditions.yaml` (`conditions@2`).

    POST /api/pf/condition {"action": "add", "key", "trigger": "date|price_below|price_above|event", "value", "text", "valid_until"?}
        → 200 {"saved": путь, "id", "condition": запись} | 400 (поле не прошло, бумаги нет на досках) | 409 (файл условий изменился)
    POST /api/pf/condition {"action": "withdraw", "id", "reason"?}
        → 200 {"saved": путь, "id", "withdrawn": {at, by, reason}} | 400 (чужое условие, уже снято, нет такого) | 409

Запись собирает тот же писатель, что и CLI скилла: `apply_condition.py add|withdraw --by owner --emit --no-restamp --owner-only`
(в процессе, `apply_condition.run`): определение владельца — `kind: watch`, `on_trigger.action: notify_only`, `while_pending.verdict: null`
(наблюдение не закрепляет вердикт бумаги), `source.kind: owner`. Файл на mount `--emit` не пишет: текст нового
conditions.yaml и sha256 прочитанных байтов идут в вывод; hub-notify кладёт текст через hub-api /api/job/save с base_hash
(save_fn). Хэш, прочитанный с mount, сверяется с хэшем hub-api (read_fn): расходятся — зеркало отстаёт, 409 «повтори».

Бумага — любой тикер MOEX, не только держимый: существует, если на досках TQBR/TQOB/TQCB есть цена (quotes_fn)
или ключ есть в портфеле (held_fn). Условие по бумаге вне портфеля срабатывает теми же проходами hub-notify.
Снять можно только свои условия (`source.kind: owner`) — советника снимает советник.

Правила сайта сверх схемы: text обязателен, ≤ 200; цена — положительное число (у облигации — % номинала); дата триггера — не в
прошлом; valid_until — дата не раньше сегодня и не раньше даты триггера. Режим сайта (с ИИ / без) запись не гейтит:
условие владельца «навсегда».

Только stdlib (+ PyYAML внутри apply_condition, как у остального сайта).
"""
import importlib
import json
import re
import sys
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MSK = timezone(timedelta(hours=3))
DEFS_REL = "Portfolio/conditions.yaml"
KEY_RE = re.compile(r"^[A-Z0-9.-]+$")
TRIGGERS = ("date", "price_below", "price_above", "event")
TEXT_MAX = 200
EVENT_MAX = 200
REASON_DEFAULT = "снято владельцем с сайта"
LOCK = threading.Lock()


class Conflict(Exception):
    """hub-api ответил 409: файл условий изменился между чтением и записью."""


def _ac():
    """apply_condition.py: в контейнере — pdl/skills/save-to-library/scripts, в репозитории — skills/save-to-library/scripts."""
    try:
        return importlib.import_module("apply_condition")
    except ImportError:
        pass
    cands = [HERE / "pdl" / "skills/save-to-library/scripts"]
    if len(HERE.parents) > 2:
        cands.append(HERE.parents[2] / "skills/save-to-library/scripts")
    for d in cands:
        if (d / "apply_condition.py").is_file():
            sys.path.insert(0, str(d))
            return importlib.import_module("apply_condition")
    raise ImportError("нет apply_condition.py — выполни tools/deploy.zsh")


def _iso(now=None):
    return (now or datetime.now(MSK)).astimezone(MSK).strftime("%Y-%m-%dT%H:%M:%S+03:00")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _date(v):
    try:
        return date.fromisoformat(v) if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else None
    except ValueError:
        return None


def parse_add(body, today):
    """Тело add → вход `apply_condition.py add`. ValueError — текст для владельца."""
    key = body.get("key")
    if not isinstance(key, str) or not KEY_RE.match(key):
        raise ValueError("key: ожидается тикер или ISIN (A–Z, 0–9, «.», «-»)")
    tt = body.get("trigger")
    if tt not in TRIGGERS:
        raise ValueError(f"trigger: {tt!r} — ожидается один из {', '.join(TRIGGERS)}")
    val = body.get("value")
    t0 = _date(today)
    if tt == "date":
        d = _date(val)
        if d is None:
            raise ValueError("value: ожидается дата ГГГГ-ММ-ДД")
        if d < t0:
            raise ValueError("value: дата в прошлом — условие сработало бы сразу")
    elif tt in ("price_below", "price_above"):
        if isinstance(val, str):
            try:
                val = float(val.replace(",", ".").replace(" ", ""))
            except ValueError:
                pass
        if not _num(val) or val <= 0 or val > 1e9:
            raise ValueError("value: ожидается положительное число — цена (у облигации — % номинала)")
    else:
        val = val.strip() if isinstance(val, str) else ""
        if not val:
            raise ValueError("value: опиши событие словами")
        if len(val) > EVENT_MAX:
            raise ValueError(f"value: событие — не больше {EVENT_MAX} знаков (сейчас {len(val)})")
    text = body.get("text")
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        raise ValueError("text: напиши, что напомнить")
    if len(text) > TEXT_MAX:
        raise ValueError(f"text: не больше {TEXT_MAX} знаков (сейчас {len(text)})")
    payload = {"key": key, "kind": "watch", "trigger": {"type": tt, "value": val},
               "while_pending": {"verdict": None, "text": ""},
               "on_trigger": {"action": "notify_only", "text": text},
               "source": {"kind": "owner", "doc": None}}
    vu = body.get("valid_until")
    if vu not in (None, ""):
        vd = _date(vu)
        if vd is None:
            raise ValueError("valid_until: ожидается дата ГГГГ-ММ-ДД или пусто")
        if vd < t0:
            raise ValueError("valid_until: срок действия уже прошёл")
        if tt == "date" and vd < _date(val):
            raise ValueError("valid_until: срок действия раньше даты условия")
        payload["valid_until"] = vu
    if tt == "event":
        payload["event_text"] = val
    return payload


def parse_withdraw(body):
    cid = body.get("id")
    if not isinstance(cid, str) or not cid.strip() or "@" in cid:
        raise ValueError("id: ожидается идентификатор условия")
    reason = body.get("reason")
    reason = reason.strip() if isinstance(reason, str) and reason.strip() else REASON_DEFAULT
    if len(reason) > TEXT_MAX:
        raise ValueError(f"reason: не больше {TEXT_MAX} знаков")
    return {"id": cid.strip(), "reason": reason}


def _exists(key, quotes_fn, held_fn):
    """Бумага существует: ключ в портфеле или на досках есть цена. → (ok, ошибка-502 | None)."""
    try:
        held = held_fn() if held_fn else None
    except Exception:  # noqa: BLE001
        held = None
    if held and key in held:
        return True, None
    try:
        q = quotes_fn() if quotes_fn else None
    except Exception:  # noqa: BLE001
        q = None
    if not q:
        return False, "котировки Мосбиржи сейчас недоступны — не могу проверить тикер, повтори позже"
    return key in q, None


def post_condition(root, body, save_fn, now, read_fn, quotes_fn=None, held_fn=None):
    """Условие владельца с сайта → Portfolio/conditions.yaml. save_fn(rel, text, base_hash). → (код, объект)."""
    if not isinstance(body, dict):
        return 400, {"error": "тело: ожидается объект"}
    action = body.get("action")
    now_s = _iso(now)
    try:
        if action == "add":
            payload = parse_add(body, now_s[:10])
        elif action == "withdraw":
            payload = parse_withdraw(body)
        else:
            return 400, {"error": "action: add или withdraw"}
    except ValueError as e:
        return 400, {"error": str(e)}
    if action == "add":
        ok, err = _exists(payload["key"], quotes_fn, held_fn)
        if err:
            return 502, {"error": err}
        if not ok:
            return 400, {"error": f"key: бумаги {payload['key']} нет на досках TQBR / TQOB / TQCB и в портфеле — проверь тикер"}
    ac = _ac()
    argv = [action, "--root", str(root), "--by", "owner", "--today", now_s[:10], "--now", now_s, "--emit", "--no-restamp"]
    if action == "withdraw":
        argv.append("--owner-only")
    with LOCK:
        code, out = ac.run(argv, json.dumps(payload, ensure_ascii=False))
        if code != 0 or not out.get("ok"):
            return 400, {"error": str(out.get("error") or "условие не записано"), **({"errors": out["errors"]} if out.get("errors") else {})}
        em = out["emitted"]
        text, cur_hash = read_fn(DEFS_REL)
        if cur_hash is None:
            return 400, {"error": f"нет файла {DEFS_REL}"}
        if cur_hash != em["base_digest"]:
            return 409, {"error": "файл условий только что менялся (или зеркало отстаёт) — подожди минуту и повтори", "path": DEFS_REL}
        try:
            save_fn(DEFS_REL, em["text"], cur_hash)
        except Conflict:
            return 409, {"error": "файл условий только что менялся — подожди минуту и повтори", "path": DEFS_REL}
    res = {"saved": DEFS_REL, "id": out["id"]}
    res["condition" if action == "add" else "withdrawn"] = out["condition"] if action == "add" else out["withdrawn"]
    if action == "add":
        res["version"] = 1
    return 200, res
