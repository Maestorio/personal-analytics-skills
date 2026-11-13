"""Стресс и сплиты на стороне сайта (hub-notify): пересчёт стресса, веса сценариев, подтверждение сплита.

Три функции, одна цель — числа стресса и реестр сплитов обновляются с сайта без модели:

  · recalc — после «Сохранить» рабочего снапшота (шаг stress_recalc в pf_build.POST_STEPS) и по запросу весов:
    запускает stress_recalc.py скилла portfolio-scenario-stress отдельным процессом над самым свежим
    стресс-файлом скилла (Portfolio/stress/stress-ДАТА*.yaml) и кладёт результат в
    Portfolio/stress/auto/recalc-<имя стресса>.yaml (один текущий файл на исходный стресс; прежние версии —
    в .versions/ у hub-api). Суждения (беты, тексты) берутся из исходного стресса как есть.
  · веса сценариев — scenarios/stress-weights-<матрица>.json (stress-weights@1): убеждения владельца по
    ДВУМ осям матрицы на каждый горизонт → веса четырёх сценариев (scenario_axis_weights, ρ = 0).
    Матрица читается только ради соответствия «сценарий ↔ полюса осей»; её собственные веса не трогаются.
  · сплиты — Portfolio/known-splits.json (known-splits@1): add / dismiss через чистые функции
    known_splits.apply_add / apply_dismiss.

Запись в библиотеку — только через save_fn (в бою jobs.save → hub-api /api/job/save): том Claude-Memory
у hub-notify на чтение. Сбой пересчёта вызывающего не роняет — возвращается {state: "error", error}.

    POST /api/pf/stress/weights  {"axis_beliefs": {"h6": {"ev_x": 0.35, "ev_y": 0.6}, …},
                                  "apply": bool, "reason"?: str (при apply обязателен, ≤ 300)}
        apply=false («а что если»): ничего не пишет → 200 {"weights", "summary"}
        apply=true: пишет файл весов, затем пересчёт → 200 {"weights", "summary", "saved": [пути], "recalc"}
            (ошибка пересчёта после записи — 200, recalc.state = "error": веса сохранены)
        summary = {"source_stress", "snapshot_id", "weights_source", "reason", "needs_judgment": N,
                   "dropped": N, "horizons": {"h6": {"modal": {"scenario": "C", "weight": 0.39},
                       "price": {"expected_pl_pct": 2.8, "expected_pl_rub": 427418},
                       "total_return": {"expected_pl_pct": 6.1, "expected_pl_rub": 927365}}, …}}
            modal — сценарий с наибольшим весом на горизонте; expected_* — из portfolio_aggregates
            пересчитанного файла (None, если у стресса нет EV-слоя).
    GET  /api/pf/stress/weights → {"weights": файл|null, "horizon_ends", "matrix", "horizons_changed",
                                   "recalc_stale", "recalc_refreshing", "terms", "terms_mismatch", "terms_history",
                                   "macro", "refresh"}
        recalc_stale — файл пересчёта сделан раньше последней записи стресса (стресс заменили под тем же именем);
        сайт тут же пересчитывает его фоном (recalc_refreshing), страница перечитывает файл пересчёта.
        terms = {"horizon_ends", "primary_horizon", "set_at", "reason", "source": "site"|"stress"} — сроки из файла
        scenarios/horizons.json (horizons@1), а без него — сроки стресса; terms_mismatch — файл есть и сроки другие.
        macro = {"used", "latest", "newer", "blocked": null|"matrix", "error"}; refresh = {"state": idle|running|error,
        "reason": stress_replaced|macro|manual|null, "error", "at"} — состояние фонового пересчёта сайта.
    POST /api/pf/stress/terms {"horizon_ends": {"h6": "ГГГГ-ММ-ДД", …}, "primary_horizon": 12, "reason"?: str, "confirm": bool}
        confirm=false → 200 {"check": {"ok", "horizon_ends", "primary_horizon", "months", "same_as_current"}};
        confirm=true (reason обязателен) → пишет scenarios/horizons.json: 200 {"terms", "saved"}; веса и стресс не трогает.
    POST /api/pf/stress/recalc {} → полный пересчёт сейчас: 200 {"recalc", "summary"} | 502 | 409
    POST /api/pf/splits {"action": "add"|"dismiss", "ticker", "date", "ratio", "note"?}
        → 200 {"saved", "splits", "dismissed"} | 400 | 409 (дубль)

Только stdlib (+ PyYAML, как у остального сайта).
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
MSK = timezone(timedelta(hours=3))

STRESS_DIR = "Portfolio/stress"
STRESS_AUTO_DIR = "Portfolio/stress/auto"
SNAP_DIR = "Portfolio/snapshots"
SPLITS_REL = "Portfolio/known-splits.json"
WEIGHTS_DIR = "scenarios"
TERMS_REL = "scenarios/horizons.json"      # сроки прогонов (horizons@1): пишет только сайт
TERMS_SCHEMA = "horizons@1"
TERMS_HISTORY_KEEP = 20
MACRO_DIR = "macro-chain"
TIMEOUT = 300                       # пересчёт — секунды; запас на холодный контейнер
HISTORY_KEEP = 50
REASON_MAX = 300
_STRESS_RE = re.compile(r"^stress-(\d{4}-\d{2}-\d{2})[A-Za-z0-9_.-]*\.yaml$")
_SNAP_RE = re.compile(r"^portfolio-(\d{4}-\d{2}-\d{2})\.json$")
_NAME_RE = re.compile(r"^[a-z0-9-]+$")      # как в JOB_WHITELIST hub-api
_MACRO_RE = re.compile(r"^macro-scenarios-(\d{4}-\d{2}-\d{2})[A-Za-z0-9_.-]*\.ya?ml$")
_HKEY_RE = re.compile(r"^h([1-9]\d*)$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Один замок на всё, что пишет стресс-артефакты: пересчёт после «Сохранить», «Применить» и «а что если».
# RLock — recalc берёт его внутри уже захваченных маршрутов.
LOCK = threading.RLock()


class StressJobError(Exception):
    """Ошибка запроса/состояния; code — HTTP-статус для маршрута."""

    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


def _cands(rel):
    c = [HERE / "pdl" / rel]
    if len(HERE.parents) > 2:
        c.append(HERE.parents[2] / rel)
    return c


def _script():
    rel = "skills/portfolio-scenario-stress/scripts/stress_recalc.py"
    cands = _cands(rel)
    return next((c for c in cands if c.exists()), cands[0])


def _import_shared(name, rel_dirs):
    """Модуль из _shared-references / скрипта скилла: в контейнере — pdl/…, в репозитории — корень."""
    import importlib
    try:
        return importlib.import_module(name)
    except ImportError:
        pass
    for rel in rel_dirs:
        for d in _cands(rel):
            if (d / f"{name}.py").is_file():
                sys.path.insert(0, str(d))
                return importlib.import_module(name)
    raise ImportError(f"нет модуля {name} — выполни tools/deploy.zsh")


def _axis_weights():
    return _import_shared("scenario_axis_weights", ["_shared-references"])


def _known_splits():
    return _import_shared("known_splits", ["skills/portfolio-data-loader/scripts"])


def _iso(now=None):
    return (now or datetime.now(MSK)).astimezone(MSK).strftime("%Y-%m-%dT%H:%M:%S+03:00")


def _yaml():
    import yaml
    return yaml


# ───────────────────────────── кэш разобранных файлов ─────────────────────────────
# На NAS PyYAML разбирает 350 КБ стресса секундами; файл меняется редко. Ключ — (путь, mtime_ns, размер):
# файл не менялся — повторного разбора нет. Возвращается ОБЩЕЕ дерево: вызывающие его не изменяют.

CACHE_MAX = 6
_CACHE = OrderedDict()
_CACHE_LOCK = threading.Lock()
_WARM = {}                  # путь → (sha1 текста, дерево): прогрев после recalc, см. warm_cache


def _parse_yaml(text):
    y = _yaml()
    return y.load(text, Loader=getattr(y, "CSafeLoader", y.SafeLoader))


def _parse_json(text):
    return json.loads(text)


def _file_key(path):
    st = os.stat(path)
    return (str(path), st.st_mtime_ns, st.st_size), st


def cached_load(path, kind="yaml"):
    """Разобранный YAML/JSON-файл с кэшем по (путь, mtime_ns, размер). Нет файла → OSError, битый → ValueError/YAMLError."""
    key, st = _file_key(path)
    key = key + (kind,)
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
        warm = _WARM.get(str(path)) if kind == "yaml" else None
    text = Path(path).read_text(encoding="utf-8")
    if warm and warm[0] == hashlib.sha1(text.encode("utf-8")).hexdigest():
        with _CACHE_LOCK:                          # файл на томе байт в байт тот, что сохранил recalc
            _put(key, warm[1])
            if _WARM.get(str(path)) is warm:
                del _WARM[str(path)]
        return warm[1]
    tree = (_parse_yaml if kind == "yaml" else _parse_json)(text)
    with _CACHE_LOCK:
        _put(key, tree)
    return tree


def _put(key, tree):
    for k in [k for k in _CACHE if k[0] == key[0] and k != key]:     # старая версия того же файла не нужна
        del _CACHE[k]
    _CACHE[key] = tree
    _CACHE.move_to_end(key)
    while len(_CACHE) > CACHE_MAX:
        _CACHE.popitem(last=False)


def warm_cache(root, rel, text, tree):
    """Положить в кэш дерево только что сохранённого через save_fn файла без повторного разбора.

    Запись идёт через hub-api — mtime у файла на томе появится позже и неизвестен, поэтому тут только заявка:
    при первом чтении файла его текст сверяется по sha1 с сохранённым, и совпавшее дерево берётся без разбора."""
    with _CACHE_LOCK:
        _WARM[str(Path(root) / rel)] = (hashlib.sha1(text.encode("utf-8")).hexdigest(), tree)
        while len(_WARM) > CACHE_MAX:
            _WARM.pop(next(iter(_WARM)))


def clear_cache():
    with _CACHE_LOCK:
        _CACHE.clear()
        _WARM.clear()


PREWARM = True
_prewarming = set()


def prewarm(root):
    """Фоновая нить: прогреть то, что понадобится ползунку (файл пересчёта и снапшот). Один запуск на корень."""
    if not PREWARM or str(root) in _prewarming:
        return
    _prewarming.add(str(root))

    def work():
        try:
            st = latest_skill_stress(root)
            if st is not None:
                rp = Path(root) / STRESS_AUTO_DIR / f"recalc-{st.stem}.yaml"
                for p, kind in ((st, "yaml"), (rp, "yaml"), (latest_snapshot(root), "json")):
                    if p is not None and Path(p).is_file():
                        cached_load(p, kind)
        except Exception:  # noqa: BLE001 — прогрев необязателен
            pass
        finally:
            _prewarming.discard(str(root))

    threading.Thread(target=work, daemon=True, name="stress-prewarm").start()


# ───────────────────────────── поиск входов ─────────────────────────────

def latest_skill_stress(root):
    """Путь самого свежего Portfolio/stress/stress-*.yaml; auto/ не считается.

    Порядок: дата в имени → время записи файла → имя. Дата остаётся первой: время записи старого файла меняет
    любая его перезапись (миграция), и самым свежим он от этого не становится. Время записи решает только
    между файлами одной даты — второй прогон за день новее первого при любом имени."""
    d = Path(root) / STRESS_DIR
    if not d.is_dir():
        return None
    best = None
    for p in d.iterdir():
        m = _STRESS_RE.match(p.name)
        if not (m and p.is_file()):
            continue
        try:
            key = (m.group(1), p.stat().st_mtime_ns, p.name)
        except OSError:
            continue
        if best is None or key > best[0]:
            best = (key, p)
    return best[1] if best else None


# время пересчёта из блока recalc верхнего уровня: «recalc:» и первая строка «  at: …» внутри него
_RECALC_AT_RE = re.compile(r"^recalc:[ \t]*\n(?:[ \t]+.*\n)*?[ \t]+at:[ \t]*['\"]?([^'\"\n]+)", re.M)


def recalc_is_stale(stress_path, rc):
    """Пересчёт сделан раньше последней записи файла стресса (с точностью до секунды) → True.

    Так бывает, когда стресс заменили под тем же именем: файл пересчёта привязан к стрессу именем и остаётся
    от прежней версии суждений. rc — блок recalc файла пересчёта. Времени нет или оно не читается → False."""
    at = (rc or {}).get("at") if isinstance(rc, dict) else None
    try:
        t = at if isinstance(at, datetime) else datetime.fromisoformat(str(at))
        if t.tzinfo is None:
            t = t.replace(tzinfo=MSK)
        return t.timestamp() < int(Path(stress_path).stat().st_mtime)
    except (TypeError, ValueError, OSError):
        return False


def stale_recalc(root, stress):
    """Файл пересчёта свежего стресса есть, но сделан до последней записи стресса → True."""
    rp = Path(root) / STRESS_AUTO_DIR / f"recalc-{stress.stem}.yaml"
    try:
        if not rp.is_file():
            return False
        m = _RECALC_AT_RE.search(rp.read_text(encoding="utf-8"))   # без разбора YAML: на NAS он идёт секунды
    except (OSError, ValueError):   # нечитаемый пересчёт устаревшим не считаем: его заменит следующий пересчёт
        return False
    return bool(m) and recalc_is_stale(stress, {"at": m.group(1).strip()})


_refreshing = set()
_refresh_tried = {}          # (корень, имя стресса, mtime_ns, макро-файл) → время последней попытки, monotonic
_refresh_state = {}          # корень → {state, reason, error, at}: состояние пересчёта сайта (в памяти процесса)
_macro_errors = {}           # _macro_err_key → хвост ошибки: эта версия макро-файла в этот стресс не подставилась
REFRESH_RETRY_S = 600


def _macro_err_key(root, stress, latest_name):
    """Ключ ошибки подстановки: стресс и ВЕРСИЯ макро-файла (имя + время записи) — пересобранная под тем же
    именем макро-таблица получает новую попытку."""
    try:
        mt = (Path(root) / MACRO_DIR / latest_name).stat().st_mtime_ns if latest_name else 0
    except OSError:
        mt = 0
    return (str(root), stress.name, latest_name, mt)


def _set_refresh(root, state, reason, error=None):
    _refresh_state[str(root)] = {"state": state, "reason": reason, "error": error, "at": _iso()}


def refresh_state(root):
    st = _refresh_state.get(str(root))
    return dict(st) if st else {"state": "idle", "reason": None, "error": None, "at": None}


def refresh_reason(root, stress):
    """Зачем сайту пересчитывать сам: первая подходящая причина или None."""
    if stale_recalc(root, stress):
        return "stress_replaced"
    ms = macro_state(root, stress)
    if ms["newer"] and not ms["blocked"] and _macro_err_key(root, stress, ms["latest"]) not in _macro_errors:
        return "macro"
    return None


def refresh_if_needed(root, work_dir, save_fn, runner, wait=False):
    """Пересчитать фоном на свежем снапшоте и весах сайта, если есть причина: пересчёт устарел (стресс заменили
    под тем же именем) или появилась более новая макро-таблица, которую можно подставить.

    → причина (строка) если пересчёт запущен или уже идёт, иначе None. Повтор для той же комбинации (версия стресса,
    макро-файл) — не чаще REFRESH_RETRY_S: неудачный пересчёт не запускается каждым открытием вкладки.
    wait=True — дождаться (тесты)."""
    stress = latest_skill_stress(root)
    if stress is None:
        return None
    reason = refresh_reason(root, stress)
    if reason is None:
        return None
    if str(root) in _refreshing:
        return (_refresh_state.get(str(root)) or {}).get("reason") or reason
    try:
        key = (str(root), stress.name, stress.stat().st_mtime_ns) + _macro_err_key(root, stress, macro_state(root, stress)["latest"])[2:]
    except OSError:
        return None
    last = _refresh_tried.get(key)
    if last is not None and time.monotonic() - last < REFRESH_RETRY_S:
        return None
    snap = latest_snapshot(root)
    if snap is None:
        return None
    _refresh_tried.clear()
    _refresh_tried[key] = time.monotonic()
    _refreshing.add(str(root))
    _set_refresh(root, "running", reason)

    def work():
        try:
            summ = recalc(root, work_dir, snap, save_fn, runner, None)
            if summ.get("state") == "error":
                _set_refresh(root, "error", reason, summ.get("error"))
            else:
                _set_refresh(root, "idle", reason)
        except Exception as e:  # noqa: BLE001 — фон вызывающего не роняет
            _set_refresh(root, "error", reason, f"{type(e).__name__}: {str(e)[:300]}")
        finally:
            _refreshing.discard(str(root))

    th = threading.Thread(target=work, daemon=True, name="stress-refresh")
    th.start()
    if wait:
        th.join()
    return reason


def refresh_stale(root, work_dir, save_fn, runner, wait=False):
    """Прежнее имя refresh_if_needed → True, если пересчёт запущен."""
    return bool(refresh_if_needed(root, work_dir, save_fn, runner, wait=wait))


# ───────────────────────────── сроки (scenarios/horizons.json) ─────────────────────────────

def check_terms(doc):
    """Одна проверка файла сроков (правила §1) → текст причины или None. Нормализации не делает."""
    if not isinstance(doc, dict):
        return "ожидался объект"
    if doc.get("schema") != TERMS_SCHEMA:
        return f"schema должна быть {TERMS_SCHEMA}"
    return check_horizon_set(doc.get("horizon_ends"), doc.get("primary_horizon"))


def check_horizon_set(he, primary):
    if not isinstance(he, dict) or not 1 <= len(he) <= 6:
        return "horizon_ends: объект из 1–6 сроков вида h6, h12"
    items = []
    for k, v in he.items():
        m = _HKEY_RE.match(k) if isinstance(k, str) else None
        if not m:
            return f"horizon_ends: метка {k!r} не вида hN (N — целое больше нуля)"
        if not isinstance(v, str) or not _DATE_RE.match(v):
            return f"{k}: дата ГГГГ-ММ-ДД, получено {v!r}"
        try:
            d = datetime.strptime(v, "%Y-%m-%d").date()
        except ValueError:
            return f"{k}: {v} — такой даты нет"
        items.append((int(m.group(1)), k, d))
    items.sort()
    for (_, ka, da), (_, kb, db) in zip(items, items[1:]):
        if not da < db:
            return f"{kb} ({db.isoformat()}) должен быть позже {ka} ({da.isoformat()})"
    if isinstance(primary, bool) or not isinstance(primary, int) or f"h{primary}" not in he:
        return f"primary_horizon: целое, срок h{primary} должен быть среди {sorted(he)}"
    return None


def _ordered(he):
    return {k: he[k] for k in sorted(he, key=lambda k: int(k[1:]))}


def read_terms(root):
    """→ (файл сроков | None, предупреждение | None). Нет файла — (None, None); невалидный — (None, причина)."""
    p = Path(root) / TERMS_REL
    if not p.is_file():
        return None, None
    try:
        doc = cached_load(p, "json")
    except (OSError, ValueError) as e:
        return None, f"{TERMS_REL} не читается: {str(e)[:120]}"
    err = check_terms(doc)
    if err:
        return None, f"{TERMS_REL} не принят: {err}"
    return doc, None


def same_terms(a, b):
    """Сроки совпадают: равны множества меток и даты по каждой (primary_horizon не входит)."""
    return isinstance(a, dict) and isinstance(b, dict) and a == b


def _today(now=None):
    return (now or datetime.now(MSK)).astimezone(MSK).date()


def _months(he, today):
    return {k: round((datetime.strptime(v, "%Y-%m-%d").date() - today).days / 30.4375, 1) for k, v in _ordered(he).items()}


def current_terms(root):
    """Действующие сроки для сравнения: файл сайта, а без него сроки свежего стресса. → dict | None."""
    doc, _ = read_terms(root)
    if doc:
        return doc["horizon_ends"]
    st = latest_skill_stress(root)
    if st is None:
        return None
    try:
        he = load_stress(st).get("horizon_ends")
    except (StressJobError, OSError, ValueError):
        return None
    return he if isinstance(he, dict) else None


def post_terms(root, body, save_fn, now):
    """POST /api/pf/stress/terms. → (код, объект). Пишет только scenarios/horizons.json."""
    if not isinstance(body, dict):
        return 400, {"error": "тело должно быть объектом"}
    confirm = body.get("confirm", False)
    if not isinstance(confirm, bool):
        return 400, {"error": "confirm: true или false"}
    he, primary = body.get("horizon_ends"), body.get("primary_horizon")
    err = check_horizon_set(he, primary)
    if err:
        return 400, {"error": err}
    today = _today(now)
    for k, v in _ordered(he).items():
        if datetime.strptime(v, "%Y-%m-%d").date() <= today:
            return 400, {"error": f"{k}: дата {v} не позже сегодняшней ({today.isoformat()})"}
    he = _ordered(he)
    if not confirm:
        return 200, {"check": {"ok": True, "horizon_ends": he, "primary_horizon": primary,
                               "months": _months(he, today), "same_as_current": same_terms(he, current_terms(root))}}
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return 400, {"error": "нужна причина (reason): зачем сдвигаются сроки"}
    reason = reason.strip()
    if len(reason) > REASON_MAX:
        return 400, {"error": f"reason длиннее {REASON_MAX} символов"}
    with LOCK:
        old, _ = read_terms(root)
        hist = []
        if old:
            hist = [h for h in (old.get("history") or []) if isinstance(h, dict)]
            hist.append({k: old.get(k) for k in ("set_at", "horizon_ends", "primary_horizon", "reason")})
        doc = {"schema": TERMS_SCHEMA, "horizon_ends": he, "primary_horizon": primary, "set_at": _iso(now),
               "reason": reason, "history": hist[-TERMS_HISTORY_KEEP:]}
        save_fn(TERMS_REL, json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    return 200, {"terms": doc, "saved": [TERMS_REL]}


# ───────────────────────────── макро-таблица ─────────────────────────────

def _macro_key(p):
    m = _MACRO_RE.match(p.name)
    try:
        return (m.group(1) if m else "", p.stat().st_mtime_ns, p.name)
    except OSError:
        return (m.group(1) if m else "", 0, p.name)


def latest_macro(root):
    """Самый свежий macro-chain/macro-scenarios-ДАТА*.yaml: дата в имени → время записи → имя."""
    d = Path(root) / MACRO_DIR
    if not d.is_dir():
        return None
    best = None
    for p in d.iterdir():
        if _MACRO_RE.match(p.name) and p.is_file():
            key = _macro_key(p)
            if best is None or key > best[0]:
                best = (key, p)
    return best[1] if best else None


_MACRO_MATRIX_RE = re.compile(r"^scenario_matrix:[ \t]*\n(?:[ \t]+.*\n)*?[ \t]+source_file:[ \t]*['\"]?([^'\"\n#]+)", re.M)
_RECALC_MACRO_RE = re.compile(r"^recalc:[ \t]*\n(?:[ \t]+.*\n)*?[ \t]+macro_input:[ \t]*['\"]?([^'\"\n#]+)", re.M)


def _name_of_matrix(ref):
    name = re.sub(r"\.(ya?ml|md)$", "", Path(str(ref).strip()).name)
    return name if _NAME_RE.match(name) else None


def macro_matrix(path):
    """Имя матрицы макро-файла из scenario_matrix.source_file — регуляркой, без полного разбора YAML."""
    try:
        m = _MACRO_MATRIX_RE.search(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return _name_of_matrix(m.group(1)) if m else None


def macro_state(root, stress):
    """→ {"used", "latest", "newer", "blocked"}; used — макро-таблица действующих чисел: пересчёта (если он не
    устарел), иначе самого стресса. blocked "matrix" — матрица макро-файла не та, что у стресса."""
    latest = latest_macro(root)
    used = None
    numbers_at = None          # когда посчитаны действующие числа: время свежего пересчёта, иначе запись стресса
    rp = Path(root) / STRESS_AUTO_DIR / f"recalc-{stress.stem}.yaml"
    try:
        if rp.is_file() and not stale_recalc(root, stress):
            text = rp.read_text(encoding="utf-8")
            m = _RECALC_MACRO_RE.search(text)
            if m:
                used = Path(m.group(1).strip()).name
            a = _RECALC_AT_RE.search(text)
            if a:
                t = datetime.fromisoformat(a.group(1).strip())
                numbers_at = (t if t.tzinfo else t.replace(tzinfo=MSK)).timestamp()
    except (OSError, ValueError):
        used = None
    if numbers_at is None:
        try:
            numbers_at = stress.stat().st_mtime
        except OSError:
            numbers_at = None
    try:
        mi = load_stress(stress).get("macro_input")
    except (StressJobError, OSError, ValueError):
        mi = None
    own = Path(mi).name if isinstance(mi, str) and mi.strip() else None     # макро-таблица самого стресса скилла
    if used is None:
        used = own
    newer = blocked = False
    if latest is not None and latest.name != used:
        up = Path(root) / MACRO_DIR / used if used else None
        newer = up is None or not up.is_file() or _macro_key(latest) > _macro_key(up)
    elif latest is not None and numbers_at is not None:
        # тот же файл перезаписан после расчёта действующих чисел: макро-таблицу пересобрали под прежним именем
        try:
            newer = int(latest.stat().st_mtime) > int(numbers_at)
        except OSError:
            newer = False
    if latest is not None:
        try:
            cur = matrix_name(load_stress(stress))
        except (StressJobError, OSError, ValueError):
            cur = None
        mm = macro_matrix(latest)
        blocked = bool(cur and mm and mm != cur)
    # apply — подставлять ли latest в КАЖДЫЙ пересчёт: источник пересчёта — всегда стресс скилла со своей
    # макро-таблицей, поэтому решает сравнение с ней, а не с тем, что подставлено в прошлый раз (иначе следующий
    # пересчёт по снапшоту или весам вернул бы числа на прежнюю таблицу)
    apply = False
    if latest is not None and not blocked:
        try:
            if latest.name != own:
                op = Path(root) / MACRO_DIR / own if own else None
                apply = op is None or not op.is_file() or _macro_key(latest) > _macro_key(op)
            else:
                apply = int(latest.stat().st_mtime) > int(stress.stat().st_mtime)
        except OSError:
            apply = False
    return {"used": used, "latest": latest.name if latest else None, "newer": bool(newer),
            "blocked": "matrix" if blocked else None, "apply": bool(apply)}


def latest_snapshot(root):
    """Самый свежий рабочий Portfolio/snapshots/portfolio-ДАТА.json (auto/ не считается)."""
    d = Path(root) / SNAP_DIR
    if not d.is_dir():
        return None
    best = None
    for p in d.iterdir():
        m = _SNAP_RE.match(p.name)
        if m and p.is_file() and (best is None or m.group(1) > best[0]):
            best = (m.group(1), p)
    return best[1] if best else None


def load_stress(path):
    doc = cached_load(path)
    if not isinstance(doc, dict):
        raise StressJobError(f"стресс-файл {Path(path).name}: ожидался словарь", 500)
    return doc


def matrix_name(stress_doc):
    """Имя матрицы из scenario_matrix_ref (путь или имя): без папки и расширения."""
    ref = stress_doc.get("scenario_matrix_ref")
    if not isinstance(ref, str) or not ref.strip():
        return None
    name = Path(ref.strip()).name
    name = re.sub(r"\.(ya?ml|md)$", "", name)
    return name if _NAME_RE.match(name) else None


def weights_rel(matrix):
    return f"{WEIGHTS_DIR}/stress-weights-{matrix}.json"


def read_weights(root, matrix):
    """Файл весов сайта для матрицы или None (нет/нечитаем)."""
    if not matrix:
        return None
    p = Path(root) / weights_rel(matrix)
    try:
        d = cached_load(p, "json")
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def load_matrix(root, matrix):
    p = Path(root) / WEIGHTS_DIR / f"{matrix}.yaml"
    if not p.is_file():
        raise StressJobError(f"матрица сценариев {p.name} не найдена в библиотеке", 409)
    doc = cached_load(p)
    if not isinstance(doc, dict):
        raise StressJobError(f"матрица {p.name}: ожидался словарь", 409)
    return doc


# ───────────────────────────── веса из убеждений ─────────────────────────────

def weights_from_beliefs(matrix_doc, axis_beliefs):
    """{hNN: {id сценария: вес}} из {hNN: {ev_x, ev_y}} через scenario_axis_weights (ρ = 0).

    Соответствие «сценарий ↔ полюса осей» — из объявленной полярности матрицы; не объявлена — отказ
    (канон по умолчанию на чужую матрицу зеркалит веса молча)."""
    saw = _axis_weights()
    mapping = saw.mapping_from_matrix(matrix_doc)
    if mapping is None:
        raise StressJobError("в матрице не объявлена полярность (matrix.polarity) — веса по осям не выводятся", 409)
    out = {}
    for h, b in axis_beliefs.items():
        try:
            out[h] = saw.weights_from_axes(b["ev_x"], b["ev_y"], 0.0, mapping)
        except saw.AxisWeightsError as e:
            raise StressJobError(f"{h}: {e}", 400) from None
    return out


def _num01(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and 0 <= v <= 1


def check_body(body, horizon_ends):
    """Проверка тела POST /api/pf/stress/weights → (axis_beliefs, apply, reason). Ошибка — StressJobError 400."""
    if not isinstance(body, dict):
        raise StressJobError("тело должно быть объектом")
    ab = body.get("axis_beliefs")
    if not isinstance(ab, dict) or not ab:
        raise StressJobError("нужен axis_beliefs: {горизонт: {ev_x, ev_y}}")
    want, got = set(horizon_ends), set(ab)
    if got != want:
        raise StressJobError(f"горизонты не совпадают со стрессом: нужны {sorted(want)}, получены {sorted(got)}")
    clean = {}
    for h in sorted(want, key=lambda k: int(k[1:])):
        b = ab[h]
        if not isinstance(b, dict) or set(b) != {"ev_x", "ev_y"}:
            raise StressJobError(f"{h}: нужны ровно ev_x и ev_y")
        for k in ("ev_x", "ev_y"):
            if not _num01(b[k]):
                raise StressJobError(f"{h}.{k}: число от 0 до 1, получено {b[k]!r}")
        clean[h] = {"ev_x": float(b["ev_x"]), "ev_y": float(b["ev_y"])}
    apply = body.get("apply", False)
    if not isinstance(apply, bool):
        raise StressJobError("apply: true или false")
    reason = body.get("reason")
    if apply:
        if not isinstance(reason, str) or not reason.strip():
            raise StressJobError("при apply нужна причина (reason): зачем меняются веса")
        reason = reason.strip()
        if len(reason) > REASON_MAX:
            raise StressJobError(f"reason длиннее {REASON_MAX} символов")
    else:
        reason = reason.strip() if isinstance(reason, str) else ""
    return clean, apply, reason


# ───────────────────────────── пересчёт ─────────────────────────────

def _tail(p):
    return "\n".join((p.stderr or p.stdout or "").strip().splitlines()[-4:]) or f"код {p.returncode}"


def _run(root, work_dir, snapshot_path, save_fn, runner, now, weights_path, write, retry_macro=False):
    """→ (сводка, дерево результата | None). Никогда не бросает: сбой — state=error."""
    t0 = time.monotonic()
    summ = {"state": "error", "source_stress": None, "snapshot_id": None, "path": None, "reason": None,
            "needs_judgment": None, "dropped": None, "weights_source": None, "seconds": 0.0}

    def done(**kw):
        summ.update(kw)
        summ["seconds"] = round(time.monotonic() - t0, 1)
        return summ, summ.pop("_tree", None)

    try:
        stress = latest_skill_stress(root)
        if stress is None:
            return done(state="skipped", reason="нет стресс-файла скилла в Portfolio/stress/")
        summ["source_stress"] = stress.name
        script = _script()
        if not script.is_file():
            return done(error=f"нет {script} — выполни tools/deploy.zsh")
        if not Path(snapshot_path).is_file():
            return done(error=f"нет снапшота {snapshot_path}")
        wp = weights_path
        if wp is None:
            # Веса владельца подставляются только на те сроки, на которые заданы. У нового стресса скилла
            # сроки могут быть другими — тогда считаем на его собственных весах и говорим об этом
            # (weights_ignored), а не роняем пересчёт: числа по новому снапшоту нужны в любом случае.
            sdoc = load_stress(stress)
            w = Path(root) / weights_rel(matrix_name(sdoc) or "-")
            if w.is_file():
                try:
                    wdoc = cached_load(w, "json")
                except (OSError, ValueError):
                    wdoc = None
                if isinstance(wdoc, dict) and wdoc.get("horizon_ends") == (sdoc or {}).get("horizon_ends"):
                    wp = w
                else:
                    summ["weights_ignored"] = "horizons_changed" if isinstance(wdoc, dict) else "unreadable"
        Path(work_dir).mkdir(parents=True, exist_ok=True)
        fd, out = tempfile.mkstemp(dir=str(work_dir), prefix="stress-recalc-", suffix=".yaml")
        os.close(fd)
        try:
            cmd = [sys.executable, str(script), "--stress", str(stress), "--snapshot", str(snapshot_path),
                   "--output", out, "--today", (now or datetime.now(MSK)).astimezone(MSK).date().isoformat(),
                   "--at", _iso(now)]
            if wp is not None:
                cmd += ["--weights-json", str(wp)]
            ms = macro_state(root, stress)
            # макро-таблица новее той, что у стресса скилла, и эта её версия ещё не давала отказа
            use_macro = ms["apply"] and (retry_macro or _macro_err_key(root, stress, ms["latest"]) not in _macro_errors)
            p = None
            if use_macro:
                p = runner(cmd + ["--macro-scenarios", str(Path(root) / MACRO_DIR / ms["latest"])],
                           capture_output=True, text=True, timeout=TIMEOUT, env=dict(os.environ))
                if p.returncode != 0:
                    # негодная макро-таблица не должна ронять пересчёт по новому снапшоту и весам
                    tail = _tail(p)
                    _macro_errors[_macro_err_key(root, stress, ms["latest"])] = tail
                    summ["macro_error"] = tail
                    p = None
                else:
                    _macro_errors.pop(_macro_err_key(root, stress, ms["latest"]), None)
                    summ["macro_input"] = ms["latest"]
            if p is None:
                p = runner(cmd, capture_output=True, text=True, timeout=TIMEOUT, env=dict(os.environ))
            if p.returncode != 0:
                return done(error=_tail(p))
            text = Path(out).read_text(encoding="utf-8")
            if not text.strip():
                return done(error="пересчёт не вернул файл")
            tree = _parse_yaml(text)
        finally:
            try:
                os.unlink(out)
            except OSError:
                pass
        rc = (tree or {}).get("recalc") or {}
        dest = f"{STRESS_AUTO_DIR}/recalc-{stress.stem}.yaml"
        if write:
            save_fn(dest, text)
            warm_cache(root, dest, text, tree)
        return done(state="done", path=dest if write else None, snapshot_id=rc.get("snapshot_id"),
                    reason=rc.get("reason"), weights_source=rc.get("weights_source"),
                    needs_judgment=len(rc.get("needs_judgment") or []), dropped=len(rc.get("dropped") or []),
                    _tree=tree)
    except Exception as e:  # noqa: BLE001 — сбой пересчёта вызывающего не роняет
        return done(error=f"{type(e).__name__}: {str(e)[:300]}")


def recalc(root, work_dir, snapshot_path, save_fn, runner, now, weights_path=None, write=True):
    """Пересчитать числа свежего стресса скилла на снапшоте.

    weights_path — файл stress-weights@1; не задан — scenarios/stress-weights-<матрица>.json из root, если есть.
    write=True и код 0 → Portfolio/stress/auto/recalc-<стресс>.yaml через save_fn.
    → {state: done|error|skipped, source_stress, snapshot_id, path, reason, needs_judgment, dropped,
       weights_source, seconds, error?, weights_ignored?: horizons_changed|unreadable — файл весов есть,
       но задан на другие сроки (или не читается): посчитано на весах самого стресса,
       macro_input?: имя подставленной новой макро-таблицы, macro_error?: хвост отказа скрипта с макро — пересчёт
       тогда повторён без неё}"""
    with LOCK:
        summ, _ = _run(root, work_dir, snapshot_path, save_fn, runner, now, weights_path, write)
    return summ


def _summary(tree, weights, summ):
    """Что странице нужно для показа «а что если»: см. докстринг модуля."""
    agg = (tree or {}).get("portfolio_aggregates") or {}
    hz = {}
    for h, row in weights.items():
        sid = max(sorted(row), key=lambda s: row[s])
        item = {"modal": {"scenario": sid, "weight": row[sid]}}
        for basis in ("price", "total_return"):
            blk = agg.get(basis) or {}
            item[basis] = {"expected_pl_pct": (blk.get("expected_pl_pct_by_horizon") or {}).get(h),
                           "expected_pl_rub": (blk.get("expected_pl_rub_by_horizon") or {}).get(h)}
        hz[h] = item
    return {"source_stress": summ.get("source_stress"), "snapshot_id": summ.get("snapshot_id"),
            "weights_source": summ.get("weights_source"), "reason": summ.get("reason"),
            "needs_judgment": summ.get("needs_judgment"), "dropped": summ.get("dropped"), "horizons": hz}


# ───────────────────────────── маршруты ─────────────────────────────

def _terms_block(root, he, primary):
    """→ (terms, terms_mismatch, terms_history) для ответа GET: файл сроков или, без него, сроки стресса."""
    doc, warn = read_terms(root)
    if doc:
        terms = {"horizon_ends": doc["horizon_ends"], "primary_horizon": doc["primary_horizon"],
                 "set_at": doc.get("set_at"), "reason": doc.get("reason"), "source": "site"}
        hist = [h for h in (doc.get("history") or []) if isinstance(h, dict)]
        return terms, he is not None and not same_terms(doc["horizon_ends"], he), hist
    if he is None:
        return None, False, []
    return {"horizon_ends": he, "primary_horizon": primary, "set_at": None, "reason": None, "source": "stress"}, False, []


def get_weights(root, refresh=None):
    """refresh = (work_dir, save_fn, runner): устаревший пересчёт (стресс заменили под тем же именем) или новая
    макро-таблица — сайт пересчитывает сам, фоном; в ответе recalc_stale, recalc_refreshing и refresh.
    Без refresh — только признаки."""
    stress = latest_skill_stress(root)
    if stress is None:
        terms, _, hist = _terms_block(root, None, None)
        return 200, {"weights": None, "horizon_ends": None, "matrix": None, "horizons_changed": False,
                     "terms": terms, "terms_mismatch": False, "terms_history": hist, "macro": None,
                     "refresh": refresh_state(root)}
    stale = stale_recalc(root, stress)
    started = bool(refresh and refresh_if_needed(root, *refresh))
    refreshing = bool(stale and started)
    doc = load_stress(stress)
    m = matrix_name(doc)
    w = read_weights(root, m)
    he = doc.get("horizon_ends")
    axes, names = _axes_and_names(root, m, doc)
    terms, mismatch, hist = _terms_block(root, he, doc.get("primary_horizon"))
    ms = macro_state(root, stress)
    ms["error"] = _macro_errors.get(_macro_err_key(root, stress, ms["latest"]))
    prewarm(root)
    return 200, {"weights": w, "horizon_ends": he, "matrix": m, "stress": stress.name,
                 "horizons_changed": bool(w) and w.get("horizon_ends") != he,
                 "axes": axes, "scenario_names": names,
                 "recalc_stale": stale, "recalc_refreshing": refreshing,
                 "terms": terms, "terms_mismatch": mismatch, "terms_history": hist,
                 "macro": ms, "refresh": refresh_state(root),
                 # диагностика выкладки: False — PyYAML в контейнере без libyaml, большие файлы разбираются
                 # чистым Python (на NAS — секунды); кэш и быстрый «а что если» работают в обоих случаях
                 "yaml_c": hasattr(_yaml(), "CSafeLoader")}


def post_recalc(root, work_dir, save_fn, runner, now):
    """POST /api/pf/stress/recalc: полный пересчёт сейчас на свежем снапшоте и весах сайта (с подхватом макро).
    → (код, объект); пишет только файл пересчёта."""
    stress = latest_skill_stress(root)
    if stress is None:
        return 409, {"error": "нет стресс-файла скилла — пересчитывать нечего"}
    snap = latest_snapshot(root)
    if snap is None:
        return 409, {"error": "нет рабочего снапшота портфеля"}
    with LOCK:
        _set_refresh(root, "running", "manual")
        try:
            # ручной пересчёт пробует макро-таблицу заново, даже если эта её версия уже давала отказ
            summ, tree = _run(root, work_dir, snap, save_fn, runner, now, None, write=True, retry_macro=True)
        except BaseException:
            _set_refresh(root, "error", "manual", "пересчёт прерван")
            raise
        if summ["state"] != "done":
            err = str(summ.get("error") or summ.get("reason"))
            _set_refresh(root, "error", "manual", err)
            return 502, {"error": "пересчёт не удался: " + err, "recalc": summ}
        _set_refresh(root, "idle", "manual")
    weights = {}                      # веса, на которых посчитан файл пересчёта: p_by_horizon сценариев
    for sid, sc in ((tree or {}).get("scenarios") or {}).items():
        for h, v in ((sc or {}).get("p_by_horizon") or {}).items():
            weights.setdefault(h, {})[sid] = v
    return 200, {"recalc": summ, "summary": _summary(tree, weights, summ)}


def _axes_and_names(root, matrix, stress_doc):
    """axes = {x|y: {high: [id сценариев], low: [...]}} из объявленной полярности матрицы (None, если её нет
    или матрица недоступна); scenario_names = {id: название} из стресс-файла."""
    names = {}
    for sid, sc in (stress_doc.get("scenarios") or {}).items():
        if isinstance(sc, dict):
            n = sc.get("name") or sc.get("label")
            if isinstance(n, str) and n.strip():
                names[str(sid)] = n.strip()
    axes = None
    if matrix:
        try:
            mapping = _axis_weights().mapping_from_matrix(load_matrix(root, matrix))
        except (StressJobError, ImportError, OSError, ValueError):
            mapping = None
        if mapping:
            axes = {ax: {pole: sorted(i for i, poles in mapping.items() if poles[k] == pole)
                         for pole in ("high", "low")} for k, ax in enumerate(("x", "y"))}
    return axes, names


def _what_if(root, stress, snap, matrix, weights, reason):
    """«А что если» без пересчёта: числа по сценариям от весов не зависят — меняется только их свёртка.

    Источник чисел — файл пересчёта (если он на самом свежем рабочем снапшоте), иначе стресс-файл скилла; в сводке
    честно snapshot_id этого источника. Формула — cpa.expected_pl из скрипта скилла. None → быстрый путь
    неприменим (нет EV-слоя в источнике, чужие сценарии/сроки), вызывающий считает полным пересчётом."""
    cpa = _import_shared("compute_portfolio_aggregates", ["skills/portfolio-scenario-stress/scripts"])
    ic = _import_shared("input_contract", ["skills/portfolio-scenario-stress/scripts"])
    rp = Path(root) / STRESS_AUTO_DIR / f"recalc-{stress.stem}.yaml"
    tree, from_recalc = None, False
    if rp.is_file():
        t = cached_load(rp)
        rc0 = t.get("recalc") if isinstance(t, dict) else None
        # пересчёт от прежней версии стресса (заменён под тем же именем) источником не служит
        if isinstance(rc0, dict) and rc0.get("snapshot_id") == snap.name and not recalc_is_stale(stress, rc0):
            tree, from_recalc = t, True
    if tree is None:
        tree = load_stress(stress)
    rc = tree.get("recalc") or {}
    sc = tree.get("scenarios")
    agg = tree.get("portfolio_aggregates")
    if not isinstance(sc, dict) or not isinstance(agg, dict):
        return None
    base = None
    if from_recalc:
        base = ic.compute_base_value_rub(cached_load(snap, "json"))
    if not base:
        base = tree.get("base_value_rub")
    if not base:
        return None
    cells = {"price": "price_delta_rub", "total_return": "total_return_rub"}
    hz = {}
    for h, row in weights.items():
        if set(row) != set(sc):
            return None
        sid = max(sorted(row), key=lambda s: row[s])
        item = {"modal": {"scenario": sid, "weight": row[sid]}}
        for basis, field in cells.items():
            ev = (agg.get(basis) or {}).get("expected_pl_rub_by_horizon") or {}
            if ev.get(h) is None:                 # у источника нет EV-слоя на этом сроке
                item[basis] = {"expected_pl_pct": None, "expected_pl_rub": None}
                continue
            vals = {}
            for s_id, s in sc.items():
                cell = ((s or {}).get("portfolio_level_by_horizon") or {}).get(h) or {}
                v = cpa._pv(cell.get(field))
                if v is None:
                    return None
                vals[s_id] = v
            rub, pct = cpa.expected_pl(vals, row, base)
            item[basis] = {"expected_pl_pct": pct, "expected_pl_rub": rub}
        hz[h] = item
    return {"source_stress": stress.name,
            "snapshot_id": rc.get("snapshot_id") if from_recalc else tree.get("portfolio_snapshot_id"),
            "weights_source": f"stress-weights:{Path(weights_rel(matrix)).name}", "reason": "weights",
            "needs_judgment": len(rc["needs_judgment"]) if isinstance(rc.get("needs_judgment"), list) else None,
            "dropped": len(rc["dropped"]) if isinstance(rc.get("dropped"), list) else None, "horizons": hz}


def post_weights(root, work_dir, body, save_fn, runner, now):
    """См. докстринг модуля. → (код, объект)."""
    try:
        stress = latest_skill_stress(root)
        if stress is None:
            raise StressJobError("нет стресс-файла скилла — пересчитывать нечего", 409)
        sdoc = load_stress(stress)
        he = sdoc.get("horizon_ends")
        if not isinstance(he, dict) or not he:
            raise StressJobError("в стресс-файле нет horizon_ends", 409)
        m = matrix_name(sdoc)
        if not m:
            raise StressJobError("в стресс-файле нет scenario_matrix_ref — матрица неизвестна", 409)
        beliefs, apply, reason = check_body(body, he)
        weights = weights_from_beliefs(load_matrix(root, m), beliefs)
        snap = latest_snapshot(root)
        if snap is None:
            raise StressJobError("нет рабочего снапшота портфеля", 409)
        now_s = _iso(now)
        old = read_weights(root, m)
        doc = {"schema": "stress-weights@1", "matrix": m, "horizon_ends": dict(he), "axis_beliefs": beliefs,
               "weights": weights, "set_at": now_s, "reason": reason, "weight_history": []}
        if apply and old:
            hist = [h for h in (old.get("weight_history") or []) if isinstance(h, dict)]
            hist.append({k: old.get(k) for k in ("set_at", "reason", "axis_beliefs", "weights", "horizon_ends")})
            doc["weight_history"] = hist[-HISTORY_KEEP:]
        elif old and not apply:
            doc["weight_history"] = old.get("weight_history") or []
    except StressJobError as e:
        return e.code, {"error": str(e)}
    if not apply:
        try:
            summary = _what_if(root, stress, snap, m, weights, reason)
        except Exception:  # noqa: BLE001 — быстрый путь необязателен: любой сбой → прежний полный пересчёт
            summary = None
        if summary is not None:
            return 200, {"weights": weights, "summary": summary}
    with LOCK:
        Path(work_dir).mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(work_dir), prefix="stress-weights-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=1)
            saved = []
            if apply:
                save_fn(weights_rel(m), json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
                saved.append(weights_rel(m))
            summ, tree = _run(root, work_dir, snap, save_fn, runner, now, Path(tmp), write=apply)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    if summ["state"] != "done":
        if apply:    # веса уже записаны — честно сообщаем
            return 200, {"weights": weights, "saved": saved, "recalc": summ, "summary": None,
                         "note": "веса сохранены, пересчёт не удался: " + str(summ.get("error") or summ.get("reason"))}
        return 502, {"error": "пересчёт не удался: " + str(summ.get("error") or summ.get("reason")), "recalc": summ}
    out = {"weights": weights, "summary": _summary(tree, weights, summ)}
    if apply:
        out["saved"] = saved + ([summ["path"]] if summ.get("path") else [])
        out["recalc"] = summ
    return 200, out


def post_splits(root, body, save_fn, now, read_fn=None):
    """Подтвердить/отклонить сплит с сайта → Portfolio/known-splits.json. → (код, объект)."""
    ks = _known_splits()
    if not isinstance(body, dict) or body.get("action") not in ("add", "dismiss"):
        return 400, {"error": "action: add или dismiss"}
    entry = {"ticker": body.get("ticker"), "date": body.get("date"), "ratio": body.get("ratio"),
             "note": body.get("note") or "", "added_by": "site"}
    if not isinstance(entry["note"], str):
        return 400, {"error": "note: строка"}
    with LOCK:
        try:
            if read_fn is not None:
                text, _ = read_fn(SPLITS_REL)
            else:
                p = Path(root) / SPLITS_REL
                text = p.read_text(encoding="utf-8") if p.is_file() else None
            if text is None:
                doc = {"schema": ks.SCHEMA, "splits": [], "dismissed": []}
            else:
                try:
                    doc = json.loads(text)
                except ValueError as e:
                    raise ks.KnownSplitsError(f"{SPLITS_REL} не читается: {e}") from None
                ks.validate_doc(doc)
            ts = _iso(now)
            new = ks.apply_add(doc, entry, ts) if body["action"] == "add" else ks.apply_dismiss(doc, entry, ts)
        except ks.DuplicateSplitError as e:
            return 409, {"error": str(e)}
        except ks.KnownSplitsError as e:
            return 400, {"error": str(e)}
        save_fn(SPLITS_REL, json.dumps(new, ensure_ascii=False, indent=2) + "\n")
    return 200, {"saved": SPLITS_REL, "splits": len(new["splits"]), "dismissed": len(new["dismissed"])}
