"""Сборка снапшота портфеля с сайта (API-1 PR-6, пробный режим с 2026-10-21).

Кнопка вьюера «Собрать снапшот» → POST /api/pf/build (Caddy проксирует /api/pf/* сюда, в
hub-notify, с паролем с ЛЮБОГО IP — как /api/push/*: финансовые данные). Файлы — в теле JSON
base64; запуск — тот же build_snapshot.py скилла portfolio-data-loader (deploy.zsh кладёт копию
в notify/pdl/ с раскладкой репозитория, чтобы пути скриптов к _shared-references сходились),
сухой прогон с --memory /srv (том только на чтение: прошлый снапшот, sector-overrides, прогнозы,
выгрузки ИИС-3 из Portfolio/inputs/). Сборка идёт в фоне, вьюер опрашивает статус.

«Сохранить» кладёт снапшот в рабочую Portfolio/snapshots/portfolio-ДАТА.json (имя как у скилла: его видят
вьюер, скиллы и поиск опорного снапшота). Снапшот того же дня, собранный скиллом, перезаписывается — hub-api
кладёт прежнюю версию в .versions/. Сбор без баланса поверх снапшота с балансом не пишется (409). Служебная
сводка build-summary-ДАТА-ЧЧММ-тип.json остаётся в Portfolio/snapshots/auto/. Запись — через hub-api
(/api/job/save). Блок-проверка → сохранить нельзя. После сохранения пересобирается журнал решений
(publish_journal) и пересчитываются числа стресса (stress_job.recalc → Portfolio/stress/auto/). Пробная сборка без «Сохранить» ничего не пишет.
Входы и рабочая папка прогона остаются в томе notify_data (pf/runs/<id>/) — разбор и повтор после пробного месяца.

    POST /api/pf/build   {"files": {"trades": {"name", "b64"}, "balance"?: …, "iis_trades"?: …},
                          "rebaseline_cash"?: bool,
                          "cash_fact"?: число ₽ | null,
                          "cash_fact_iis"?: число ₽ | null}        → 202 {"run"} | 400 | 409 (идёт сборка)
        cash_fact — свободные деньги ОСНОВНОГО портфеля из IntelInvest (все валюты в рублях, без ИИС-3):
        0 ≤ x < 1e9, иначе 400; → --cash-fact build_snapshot.py (только без баланса); отражается в статусе
        прогона (cash_fact) и в журнале pf_build / pf_save.
        cash_fact_iis — то же для ИИС-3 (кэш только рублёвый), 0 ≤ x < 1e9; → --cash-fact-iis; подменяет
        перенос кэша ИИС-3 из прошлого снапшота; в статусе (cash_fact_iis) и журнале.
    GET  /api/pf/status?run=<id>                                    → {"state": running|done|error, …}
    POST /api/pf/save    {"run"}                                    → {"saved": [пути]} | 409 (блок)
"""
import base64
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import stress_job  # noqa: E402 — пересчёт стресса (шаг stress_recalc)
MSK = timezone(timedelta(hours=3))


def _iso(now=None):
    """Единственная запись времени: `ГГГГ-ММ-ДДTЧЧ:ММ:СС+03:00` (МСК, schema.md §1 п.4)."""
    return (now or datetime.now(MSK)).astimezone(MSK).strftime("%Y-%m-%dT%H:%M:%S+03:00")


_CANDS = [HERE / "pdl/skills/portfolio-data-loader/scripts/build_snapshot.py"]
if len(HERE.parents) > 2:
    _CANDS.append(HERE.parents[2] / "skills/portfolio-data-loader/scripts/build_snapshot.py")
_ATTRS_CANDS = [HERE / "pdl/skills/save-to-library/scripts/security_attrs.py"]
if len(HERE.parents) > 2:
    _ATTRS_CANDS.append(HERE.parents[2] / "skills/save-to-library/scripts/security_attrs.py")
SCRIPT = next((c for c in _CANDS if c.exists()), _CANDS[0])

MAX_BODY = 30 * 1024 * 1024          # три файла base64: сделки ~0,7 МБ, баланс .numbers ~1–3 МБ
POST_STEPS = ("decision_journal", "stress_recalc")   # шаги после «Сохранить» (фоновый поток, по порядку)
_post_lock = threading.Lock()
TIMEOUT = 900                        # сборка с сетью (MOEX, ЦБ) — минуты, не часы
KEEP_RUNS = 30
AUTO_DIR = "Portfolio/snapshots/auto"
INFO_SHOWN = ("trades_changed_before_prev", "money_rows_changed_before_prev", "payouts_recorded_late",
              "trades_on_prev_snapshot_day")   # инфо-проверки, чей текст виден владельцу во вьюере
SAVE_DIR = "Portfolio/snapshots"      # куда «Сохранить» кладёт снапшот (рабочая папка); сводка сборки остаётся в AUTO_DIR
JRN_DIR = "Portfolio/decision-journal"  # журнал решений (decision_journal_update.py)
# выкладываются только производные файлы журнала (как whitelist hub-api); ручные входы папки —
# incidents.yaml, refusals.yaml, theses.yaml — сайт не пишет никогда
JRN_NAME = re.compile(r"^(inputs|baselines|journal)\.json$|^report-\d{4}-\d{2}-\d{2}\.md$")
# что скрипт читает из Portfolio/ (ссылками на том; schema.md §4.5, §6): обзоры, снапшоты, решения, условия формата 2
# с состоянием и их годовые архивы (JRN_READS_ARCHIVE), журнал плана, реестр типов (класс бумаги решения); файла гейтов нет (шаг 8)
JRN_READS = ("weekly-reviews", "snapshots", "decisions", "conditions.yaml", "conditions-state.json",
             "plan-journal.jsonl", "security-types.json")
JRN_READS_ARCHIVE = re.compile(r"^conditions-archive-\d{4}\.yaml$")   # годовые архивы определений — по маске, сколько есть
JRN_MANUAL = ("refusals.yaml", "theses.yaml", "incidents.yaml")    # ручные входы журнала — читаются, не пишутся
EXT = {"trades": (".xlsx",), "balance": (".numbers", ".xlsx"), "iis_trades": (".xlsx",)}
ZIP_SIG = b"PK\x03\x04"              # xlsx и однофайловый .numbers — zip

_lock = threading.Lock()             # одна сборка за раз
_running = {"run": None, "proc": None, "cancel": False}
_run_done = threading.Event()        # 3.121.0: сборка завершила финализацию (статус записан, лок отпускается следом)
_run_done.set()
KILL_GRACE = 5                       # 3.121.0: секунд между SIGTERM и SIGKILL при отмене


class BadRequest(ValueError):
    pass


def _popen_run(cmd, capture_output=True, text=True, timeout=None, env=None):
    """3.121.0: как subprocess.run, но процесс — в своей группе, чтобы cancel() мог его прервать."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=text, env=env,
                         start_new_session=True)
    _running["proc"] = p
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(p, 0)
        p.communicate()
        raise
    finally:
        _running["proc"] = None
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def _kill_group(p, grace=KILL_GRACE):
    """SIGTERM группе процессов, через grace с — SIGKILL."""
    try:
        pgid = os.getpgid(p.pid)
    except OSError:
        return
    try:
        if grace:
            os.killpg(pgid, signal.SIGTERM)
            try:
                p.wait(timeout=grace)
                return
            except subprocess.TimeoutExpired:
                pass
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass


def cancel(data, run):
    """3.121.0: остановить идущую сборку — ничего не сохраняется. → (код, ответ)."""
    if not run or "/" in run or ".." in run:
        return 409, {"error": "нет такой сборки"}
    if _running["run"] != run or _run_done.is_set():
        st = read_status(data, run)
        if st and st.get("state") == "cancelled":
            return 409, {"error": "сборка уже остановлена"}
        if st and st.get("state") in ("done", "error"):
            return 409, {"error": "сборка уже закончилась — остановить нечего"}
        return 409, {"error": "такой сборки сейчас нет"}
    _running["cancel"] = True
    p = _running["proc"]
    if p is not None:
        _kill_group(p)
    _run_done.wait(KILL_GRACE + 15)
    return 200, {"run": run, "state": "cancelled"}


def runs_dir(data: Path) -> Path:
    return Path(data) / "pf" / "runs"


def _status_path(data, run):
    return runs_dir(data) / run / "status.json"


def read_status(data, run):
    if not run or "/" in run or ".." in run:
        return None
    try:
        st = json.loads(_status_path(data, run).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    # шаги после «Сохранить» идут в потоке сервера: перезапуск контейнера их обрывает, running навсегда не оставляем
    for key in POST_STEPS:
        v = st.get(key) if isinstance(st, dict) else None
        if (isinstance(v, dict) and v.get("state") == "running"
                and time.time() - float(v.get("started_ts") or 0) > TIMEOUT + 60):
            st[key] = {"state": "error", "error": "прервано (перезапуск сервера?)"}
    return st


def _write_status(data, run, st):
    p = _status_path(data, run)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def stage(data, payload, now):
    """Проверить файлы и разложить в pf/runs/<id>/inputs/ → (run, пути)."""
    files = (payload or {}).get("files") or {}
    if not isinstance(files, dict) or not files.get("trades"):
        raise BadRequest("нужен файл сделок IntelInvest (trades_portfolio_*.xlsx)")
    unknown = set(files) - set(EXT)
    if unknown:
        raise BadRequest("лишние файлы: " + ", ".join(sorted(unknown)))
    run = now.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    inp = runs_dir(data) / run / "inputs"
    inp.mkdir(parents=True)
    paths = {}
    try:
        for kind, f in files.items():
            if not f:
                continue
            name = os.path.basename(str(f.get("name") or ""))
            ext = os.path.splitext(name)[1].lower()
            if ext not in EXT[kind]:
                raise BadRequest(f"{kind}: ожидается {' или '.join(EXT[kind])}, получено «{name or '—'}»")
            try:
                raw = base64.b64decode(f.get("b64") or "", validate=True)
            except ValueError:
                raise BadRequest(f"{kind}: файл повреждён при передаче") from None
            if not raw.startswith(ZIP_SIG):
                raise BadRequest(f"{kind}: «{name}» — не {ext}-файл (нет сигнатуры zip)"
                                 + (" — в Numbers сохрани как один файл, не пакетом" if ext == ".numbers" else ""))
            paths[kind] = inp / (kind + ext)
            paths[kind].write_bytes(raw)
            paths[kind + "_name"] = name
    except BadRequest:
        shutil.rmtree(runs_dir(data) / run, ignore_errors=True)
        raise
    return run, paths


CASH_WHAT = {"cash_fact": "свободные деньги основного портфеля", "cash_fact_iis": "свободные деньги ИИС-3"}


def parse_cash_fact(payload, key="cash_fact"):
    """cash_fact / cash_fact_iis из тела запроса: None (не передан) или конечное число 0 ≤ x < 1e9; иначе BadRequest."""
    v = (payload or {}).get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or not (0 <= v < 1e9):
        raise BadRequest(f"{key}: нужно число ₽ от 0 до 1 000 000 000 ({CASH_WHAT.get(key, 'кэш')})")
    return float(v)


TYPES_NAME = "security-types.json"          # справочник типов бумаг с Мосбиржи (security_types.py)
TYPES_DEST = f"Portfolio/{TYPES_NAME}"      # куда его кладёт hub-api при «Сохранить» (JOB_WHITELIST)


def types_cache_path(data) -> Path:
    """Справочник типов живёт в томе /data (том Claude-Memory у hub-notify только на чтение:
    2026-10-28 первая сборка со справочником упала на записи в /srv). Между прогонами хранится здесь,
    в Claude-Memory уезжает через hub-api вместе со снапшотом (save)."""
    return Path(data) / "pf" / TYPES_NAME


def seed_types_cache(data, root) -> bool:
    """Нет кеша в /data, но есть справочник в Claude-Memory (его пишет и скилл) — взять его стартом."""
    dst, src = types_cache_path(data), Path(root) / TYPES_DEST
    if dst.is_file() or not src.is_file():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def command(root, work, paths, rebaseline, cash_fact=None, cash_fact_iis=None, types_cache=None):
    # nice (2026-10-23): сборка — минуты процессора на NAS с 2 ГБ; уступает DSM, SSH и сайту.
    # Предел памяти — mem_limit контейнера hub-notify в docker-compose.yml.
    cmd = (["nice", "-n", "10"] if shutil.which("nice") else []) + [
        sys.executable, str(SCRIPT), "--trades", str(paths["trades"]), "--memory", str(root),
        "--out", str(work), "--json"]
    if types_cache is not None:
        cmd += ["--types-cache", str(types_cache)]
    if "balance" in paths:
        cmd += ["--balance", str(paths["balance"])]
    if "iis_trades" in paths:
        cmd += ["--iis-trades", str(paths["iis_trades"])]
    if rebaseline:
        cmd.append("--rebaseline-cash")
    if cash_fact is not None:
        cmd += ["--cash-fact", repr(float(cash_fact))]
    if cash_fact_iis is not None:
        cmd += ["--cash-fact-iis", repr(float(cash_fact_iis))]
    return cmd


POSITIONS_DIFF_MAX = 20


def positions_diff(snap, prev):
    """Что изменится в позициях при сохранении: продано / куплено / изменилось количество.
    Ключ — (счёт, тикер); None — сравнивать не с чем (нет сохранённого снапшота или в одном из них нет позиций)."""
    now_h, was_h = (snap or {}).get("holdings"), (prev or {}).get("holdings")
    if not prev or not isinstance(now_h, list) or not isinstance(was_h, list):
        return None

    def idx(hs):
        out = {}
        for h in hs:
            key = (h.get("account") or "main", h.get("ticker"))
            out[key] = (out[key][0] + (h.get("qty") or 0), out[key][1]) if key in out else (h.get("qty") or 0, h.get("name"))
        return out
    now, was = idx(now_h), idx(was_h)
    rows = []
    for (acc, t), (q, name) in sorted(now.items(), key=lambda kv: (str(kv[0][1]), str(kv[0][0]))):
        if (acc, t) not in was:
            rows.append({"kind": "bought", "ticker": t, "name": name, "account": acc, "was": None, "now": q})
        elif abs(was[(acc, t)][0] - q) > 1e-9:
            rows.append({"kind": "qty", "ticker": t, "name": name, "account": acc, "was": was[(acc, t)][0], "now": q})
    for (acc, t), (q, name) in sorted(was.items(), key=lambda kv: (str(kv[0][1]), str(kv[0][0]))):
        if (acc, t) not in now:
            rows.append({"kind": "sold", "ticker": t, "name": name, "account": acc, "was": q, "now": None})
    order = {"sold": 0, "bought": 1, "qty": 2}
    rows.sort(key=lambda r: order[r["kind"]])
    return {"rows": rows[:POSITIONS_DIFF_MAX], "more": max(0, len(rows) - POSITIONS_DIFF_MAX), "total": len(rows)}


def _trades_only_d(d):
    """_is_trades_only для уже разобранного снапшота (⚠ SYNC с ним и с build_snapshot.is_trades_only)."""
    return (isinstance(d, dict) and d.get("snapshot_type") == "trades_holdings"
            and (d.get("cash_reconciliation") or {}).get("current_drift_rub") is None)


def save_block(snap, prev):
    """Причина, по которой save() ответит 409, известная заранее: 'balance' | 'cash_fact' | None.
    3.122.1: окно предупреждает до нажатия «Сохранить» (то же условие, что в save(): сборка — только сделки,
    а сохранённый снапшот того же дня с балансом или с внесённым кэшем)."""
    if not isinstance(snap, dict) or not isinstance(prev, dict) or not _trades_only_d(snap):
        return None
    if not snap.get("as_of_date") or prev.get("as_of_date") != snap.get("as_of_date") or _trades_only_d(prev):
        return None
    return "cash_fact" if prev.get("snapshot_type") == "trades_holdings" else "balance"


def brief(summary, snap, prev):
    """Сводка для окна: главное из build-summary + сравнение с последним сохранённым снапшотом."""
    def nums(s):
        if not s:
            return None
        r = s.get("returns") or {}
        cash = s.get("cash") or {}
        return {"as_of": s.get("as_of_date"), "holdings": len(s.get("holdings") or []),
                "generated_at": s.get("generated_at"),
                "total_rub": (s.get("balance_summary") or {}).get("total_current_rub_incl_iis"),
                "cash_rub": cash.get("total_rub"),
                "cash_main_rub": (cash.get("by_account") or {}).get("main"),
                "cash_iis_rub": (cash.get("by_account") or {}).get("iis_3"),
                # кэш по счетам и откуда он: owner_intelinvest — внесён, trades_plus_prev_drift / carried_from_prev — оценка
                "cash_by_account": cash.get("by_account"),
                "cash_source": cash.get("source"), "cash_iis_source": cash.get("iis_source"),
                "cash_fact_date": cash.get("fact_date"),
                "xirr_total": (r.get("total") or {}).get("xirr"),
                "xirr_restricted": (r.get("restricted") or {}).get("xirr")}
    return {"as_of": summary.get("as_of"), "blocked": summary.get("blocked"),
            "flags_by_severity": summary.get("flags_by_severity"),
            "decisions": summary.get("decisions") or [], "attention_flags": summary.get("attention_flags") or [],
            "checks": [c for c in summary.get("checks") or [] if c.get("level") != "info"],
            # инфо-проверки о правках выгрузки задним числом показываются во вьюере в «К сведению» (текст и таблица
            # понятны без build-summary); остальные инфо — счётчиком
            "info_checks": [c for c in summary.get("checks") or [] if c.get("level") == "info" and c.get("id") in INFO_SHOWN],
            "n_info": sum(1 for c in summary.get("checks") or [] if c.get("level") == "info" and c.get("id") not in INFO_SHOWN),
            "fallbacks": summary.get("fallbacks") or {},
            # тип бумаги с Мосбиржи (security_types.py): расхождения против прошлого снапшота/эвристики
            # и состояние опроса — карточка «Тип бумаги изменился» на «Загрузках» (вьюер 3.84)
            "type_changes": summary.get("type_changes") or [], "types": summary.get("types"),
            # корзина облигации: расхождение выведенной с планом и облигации без рейтинга — карточка
            # «Корзина облигации изменилась» на «Загрузках» (вьюер 3.103, pfBucketCard)
            "bond_bucket_check": summary.get("bond_bucket_check"),
            # сверка «без баланса ↔ снапшот того же дня с балансом» (этап 6): строка и сгиб на «Загрузках»;
            # путь отчёта — путь внутри контейнера, окну не нужен
            "parity": ({k: v for k, v in summary["parity"].items() if k != "report_path"}
                       if isinstance(summary.get("parity"), dict) else None),
            "seconds": round(sum(s.get("seconds") or 0 for s in summary.get("steps") or []), 1),
            # 3.122.1: эта сборка — только сделки, без кэша; save_block — почему «Сохранить» вернёт 409 (balance | cash_fact)
            "trades_only": _trades_only_d(snap), "save_block": save_block(snap, prev),
            "auto": nums(snap), "skill": nums(prev), "positions_diff": positions_diff(snap, prev)}


def _cache_base_as_of(inputs, compare_p):
    """Дата снапшота — опоры кэша, если она не тот же файл, что база сравнения (иначе None)."""
    cache_p = inputs.get("prev_snapshot")
    if not cache_p or not compare_p or cache_p == compare_p:
        return None
    try:
        return json.loads(Path(cache_p).read_text(encoding="utf-8")).get("as_of_date")
    except (OSError, ValueError, AttributeError):
        return None


def execute(data, root, run, paths, rebaseline, runner=None, cash_fact=None, cash_fact_iis=None):
    """Сама сборка (в фоновом потоке). Итог — в status.json прогона."""
    work = runs_dir(data) / run / "work"
    runner = runner or _popen_run
    env = dict(os.environ)
    env["PDL_CBR_CACHE"] = str(Path(data) / "pf" / "cbr_rates_cache.json")       # кэши живут между прогонами
    env["PDL_MARKET_SERIES_CACHE"] = str(Path(data) / "pf" / "market-series")
    st = read_status(data, run) or {}
    t0 = time.monotonic()
    if not Path(SCRIPT).is_file():
        # python без файла скрипта выходит с кодом 2 — тем же, что «блок-проверка» build_snapshot.py,
        # и пустой вывод ломал разбор сводки (2026-10-21: deploy.zsh не скопировал notify/pdl/)
        st.update(state="error", error=f"на сервере нет {SCRIPT} — выполни tools/deploy.zsh "
                                       "(копирует скрипты portfolio-data-loader в _nas/notify/pdl/)", sec=0.0)
        _write_status(data, run, st)
        return st
    try:
        try:
            seed_types_cache(data, root)
        except OSError:
            pass                                # без посева справочник начнётся с пустого
        p = runner(command(root, work, paths, rebaseline, cash_fact, cash_fact_iis, types_cache_path(data)),
                   capture_output=True, text=True, timeout=TIMEOUT, env=env)
        if _running["cancel"]:
            # 3.121.0: владелец остановил сборку — результат выбрасываем, рабочие файлы прогона удаляем
            st.update(state="cancelled", cancelled_at=_iso())
            shutil.rmtree(runs_dir(data) / run / "work", ignore_errors=True)
            shutil.rmtree(runs_dir(data) / run / "inputs", ignore_errors=True)
            st["sec"] = round(time.monotonic() - t0, 1)
            _write_status(data, run, st)
            return st
        (runs_dir(data) / run / "stderr.txt").write_text(p.stderr or "", encoding="utf-8")
        (runs_dir(data) / run / "stdout.txt").write_text(p.stdout or "", encoding="utf-8")
        tail = "\n".join((p.stderr or "").strip().splitlines()[-6:])
        if p.returncode in (-9, 137):
            # убит ядром: упёрся в mem_limit контейнера hub-notify (docker-compose.yml) — NAS цел
            st.update(state="error", error="сборке не хватило памяти (предел контейнера hub-notify) — "
                                           "собери снапшот скиллом на Маке или подними mem_limit")
        elif p.returncode not in (0, 2):
            st.update(state="error", error=tail or f"код {p.returncode}")
        else:
            try:
                summary = json.loads(p.stdout)
            except ValueError:
                # 2026-10-21 на NAS: «JSONDecodeError: Expecting value» без подробностей — теперь
                # видно, что скрипт напечатал вместо сводки и чем закончился stderr
                head = (p.stdout or "").strip()[:300] or "(пусто)"
                raise ValueError(f"сводка build_snapshot.py не JSON (код {p.returncode}); stdout: {head}"
                                 + (f"\nstderr: {tail}" if tail else "")) from None
            snap = json.loads(Path(summary["snapshot_path"]).read_text(encoding="utf-8"))
            prev = None
            # база сравнения — последний снапшот скилла (compare_snapshot); опора кэша (prev_snapshot) может быть
            # старше: её выбирают по наличию баланса. Старый загрузчик поля не пишет — тогда prev_snapshot
            inputs = summary.get("inputs") or {}
            prev_p = inputs.get("compare_snapshot") or inputs.get("prev_snapshot")
            try:
                prev = json.loads(Path(prev_p).read_text(encoding="utf-8")) if prev_p else None
            except (OSError, ValueError):
                prev = None                        # сравнения не будет, сборку не роняем
            b = brief(summary, snap, prev)
            b["cache_base_as_of"] = _cache_base_as_of(inputs, prev_p)
            st.update(state="done", brief=b, snapshot_path=summary["snapshot_path"])
    except subprocess.TimeoutExpired:
        st.update(state="error", error=f"сборка не уложилась в {TIMEOUT // 60} мин")
    except (OSError, ValueError, KeyError) as e:
        st.update(state="error", error=f"{type(e).__name__}: {str(e)[:900]}")
    st["sec"] = round(time.monotonic() - t0, 1)
    _write_status(data, run, st)
    return st


def publish_journal(data, root, run, as_of, save_fn, runner=subprocess.run):
    """Пересобрать журнал решений (decision_journal_update.py) и выложить в Portfolio/decision-journal/.

    Том Claude-Memory у hub-notify только на чтение, а скрипт пишет в <memory>/Portfolio/decision-journal/:
    даём ему рабочий «корень» в папке прогона — входы JRN_READS (обзоры, снапшоты, решения, условия, их архивы и состояние,
    журнал плана, реестр типов) ссылками на настоящие, ручные refusals/theses/incidents.yaml копией (их проверяет
    валидатор скрипта до сборки: ошибка — код 2 и текст в status), пустая decision-journal/ для вывода. Выкладываются только
    inputs/baselines/journal.json и report-ДАТА.md (JRN_NAME) через hub-api (save_fn, копия прежней
    версии в .versions/); incidents.yaml, refusals.yaml, theses.yaml не пишутся. Выгрузка сделок — та же,
    что собрала снапшот (pf/runs/<id>/inputs/). → {"written": [...], "stdout": сводка} или {"error": текст};
    сбой журнала сохранение снапшота не отменяет (журнал пересобирается целиком в любой момент)."""
    script = Path(SCRIPT).with_name("decision_journal_update.py")
    if not script.is_file():
        return {"error": f"нет {script} — выполни tools/deploy.zsh"}
    trades = next(iter(sorted((runs_dir(data) / run / "inputs").glob("trades.*"))), None)
    if trades is None:
        return {"error": "нет выгрузки сделок прогона"}
    work = runs_dir(data) / run / "journal-memory"
    shutil.rmtree(work, ignore_errors=True)
    port = work / "Portfolio"
    (port / "decision-journal").mkdir(parents=True)
    for name in JRN_READS:
        src = Path(root) / "Portfolio" / name
        if src.exists():
            os.symlink(src, port / name)
    for src in sorted((Path(root) / "Portfolio").glob("conditions-archive-*.yaml")):
        if JRN_READS_ARCHIVE.match(src.name):
            os.symlink(src, port / src.name)
    for name in JRN_MANUAL:
        src = Path(root) / JRN_DIR / name
        if src.is_file():
            shutil.copy2(src, port / "decision-journal" / name)
    cmd = [sys.executable, str(script), "--memory", str(work), "--trades", str(trades)]
    if as_of:
        cmd += ["--as-of", str(as_of)]
    env = dict(os.environ)
    env["PDL_CBR_CACHE"] = str(Path(data) / "pf" / "cbr_rates_cache.json")       # те же кэши, что у сборки
    env["PDL_MARKET_SERIES_CACHE"] = str(Path(data) / "pf" / "market-series")
    p = runner(cmd, capture_output=True, text=True, timeout=TIMEOUT, env=env)
    if p.returncode != 0:
        return {"error": "\n".join((p.stderr or p.stdout or "").strip().splitlines()[-4:]) or f"код {p.returncode}"}
    written = []
    for f in sorted((port / "decision-journal").iterdir()):
        if f.is_file() and JRN_NAME.match(f.name):
            save_fn(f"{JRN_DIR}/{f.name}", f.read_text(encoding="utf-8"))
            written.append(f.name)
    return {"written": written, "stdout": (p.stdout or "").strip()}


def prune(data, keep=KEEP_RUNS):
    d = runs_dir(data)
    if not d.is_dir():
        return
    for old in sorted(p for p in d.iterdir() if p.is_dir())[:-keep]:
        shutil.rmtree(old, ignore_errors=True)


def start(data, root, payload, now, log=None, background=True, runner=None):
    """→ (код, ответ). Одна сборка за раз: идёт другая — 409."""
    try:
        cash_fact = parse_cash_fact(payload)
        cash_fact_iis = parse_cash_fact(payload, "cash_fact_iis")
    except BadRequest as e:
        return 400, {"error": str(e)}
    if not _lock.acquire(blocking=False):
        return 409, {"error": "уже идёт сборка", "run": _running["run"]}
    try:
        run, paths = stage(data, payload, now)
    except BadRequest as e:
        _lock.release()
        return 400, {"error": str(e)}
    rebaseline = bool((payload or {}).get("rebaseline_cash"))
    t0 = time.monotonic()
    _running.update(run=run, proc=None, cancel=False)
    _run_done.clear()
    _write_status(data, run, {"run": run, "state": "running", "started": _iso(now),
                              "rebaseline_cash": rebaseline, "cash_fact": cash_fact,
                              "cash_fact_iis": cash_fact_iis,
                              "files": {k[:-5]: v for k, v in paths.items() if k.endswith("_name")}})

    def go():
        try:
            st = execute(data, root, run, paths, rebaseline, runner, cash_fact, cash_fact_iis)
            if log:
                b = st.get("brief") or {}
                log("pf_build", {"done": "ok", "cancelled": "cancelled"}.get(st["state"], "error"), t0, run=run,
                    blocked=b.get("blocked"), rebaseline_cash=rebaseline, cash_fact=cash_fact,
                    cash_fact_iis=cash_fact_iis,
                    error=st.get("error"))
        finally:
            _running.update(run=None, proc=None, cancel=False)
            _lock.release()
            prune(data)
            _run_done.set()
    if background:
        threading.Thread(target=go, daemon=True).start()
    else:
        go()
    return 202, {"run": run}


def _is_trades_only(text):
    """Снапшот без баланса (snapshot_type trades_holdings) и без внесённого владельцем кэша.
    ⚠ SYNC с skills/portfolio-data-loader/scripts/build_snapshot.py::is_trades_only (--commit отказывает так же)."""
    try:
        d = json.loads(text)
    except (TypeError, ValueError):
        return False
    return (isinstance(d, dict) and d.get("snapshot_type") == "trades_holdings"
            and (d.get("cash_reconciliation") or {}).get("current_drift_rub") is None)


ATTRS_DEST = "Portfolio/security-attrs.json"


def _load_security_attrs():
    """Модуль единственного писателя справочника бумаг (skills/save-to-library/scripts/security_attrs.py)."""
    import importlib.util
    path = next((c for c in _ATTRS_CANDS if c.exists()), None)
    if path is None:
        raise RuntimeError("security_attrs.py не найден (deploy.zsh кладёт его в pdl/)")
    spec = importlib.util.spec_from_file_location("security_attrs_writer", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def save_attrs(snap_text, save_fn, read_fn, now):
    """Новые держания снапшота → Portfolio/security-attrs.json: только отсутствующие ключи, существующие записи
    не трогаются. → путь | {"added": [...]} | {"skipped": причина} | {"error": …}. Файла нет — не создаём
    (разовое заполнение — миграция); конфликт версий не повторяется."""
    try:
        text, _ = read_fn(ATTRS_DEST)
        if text is None:
            return {"skipped": "справочник не заполнен"}
        mod = _load_security_attrs()
        doc = json.loads(text)
        errs = mod.ds.validate_security_attrs(doc)
        if errs:
            return {"error": "справочник не проходит валидатор: " + "; ".join(errs[:3])}
        doc, added = mod.add_missing(doc, (json.loads(snap_text) or {}).get("holdings"), _iso(now), "script")
        if not added:
            return {"added": []}
        errs = mod.ds.validate_security_attrs(doc)
        if errs:
            return {"error": "новые записи не проходят валидатор: " + "; ".join(errs[:3])}
        save_fn(ATTRS_DEST, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        return {"added": added}
    except Exception as e:  # noqa: BLE001 — сбой не роняет уже сохранённый снапшот
        return {"error": f"{type(e).__name__}: {str(e)[:300]}"}


def save(data, run, save_fn, now, log=None, root=None, read_fn=None, runner=subprocess.run, background=False):
    """Собранный снапшот → Portfolio/snapshots/ (рабочая папка, через hub-api), сводка → snapshots/auto/.

    root нужен журналу решений (корень Claude-Memory), read_fn — защите от ухудшения снапшота
    (чтение текущего файла через hub-api)."""
    t0 = time.monotonic()
    st = read_status(data, run)
    if not st:
        return 404, {"error": "нет такого прогона"}
    if st.get("state") == "cancelled":
        return 409, {"error": "сборка отменена"}
    if st.get("state") != "done":
        return 409, {"error": "сборка не завершена"}
    if any((st.get(k) or {}).get("state") == "running" for k in POST_STEPS):
        return 200, {"saved": st.get("saved"), "run": run}      # второй save: шаги уже идут, второй поток не нужен
    b = st.get("brief") or {}
    if b.get("blocked"):
        return 409, {"error": "есть блок-проверки — снапшот не сохраняется"}
    snap_text = Path(st["snapshot_path"]).read_text(encoding="utf-8")
    summ_text = (Path(st["snapshot_path"]).parent / "build-summary.json").read_text(encoding="utf-8")
    # снапшот — в рабочую папку под именем скилла (portfolio-ДАТА.json); служебная сводка — в auto/ с временем
    # запуска и вариантом (с балансом / только сделки), чтобы несколько сборок на дату не затирали друг друга
    started = st.get("started") or _iso(now)
    tag = f"{b['as_of']}-{started[11:13]}{started[14:16]}-{'bal' if 'balance' in (st.get('files') or {}) else 'trades'}"
    dest = f"{SAVE_DIR}/portfolio-{b['as_of']}.json"
    if read_fn is not None and dest.startswith(SAVE_DIR + "/") and _is_trades_only(snap_text):
        # 27.10: сайт собрал без баланса поверх снапшота того же дня с балансом — потеряны кэш и итог портфеля
        old, _ = read_fn(dest)
        if old is not None and not _is_trades_only(old):
            try:
                od = json.loads(old)
            except (TypeError, ValueError):
                od = {}
            if isinstance(od, dict) and od.get("snapshot_type") == "trades_holdings":
                # у старого нет баланса, но владелец внёс кэш
                return 409, {"reason": "cash_fact", "error": f"уже сохранён снапшот {b['as_of']} с внесённым кэшем — эта сборка "
                             "без кэша его ухудшит: впиши кэш в «Кеш после сборки» и нажми «Пересобрать с этим кешем»"}
            return 409, {"reason": "balance", "error": f"уже сохранён снапшот {b['as_of']} с «Общим балансом» — сборка "
                         "без баланса его ухудшит; собери с балансом"}
    save_fn(dest, snap_text)
    save_fn(f"{AUTO_DIR}/build-summary-{tag}.json", summ_text)
    st.update(saved=dest, saved_at=_iso(now))
    # справочник типов бумаг (обновлён сборкой в /data) — в Claude-Memory, чтобы скилл на Маке его читал;
    # его сбой не должен ронять уже сохранённый снапшот
    tc = types_cache_path(data)
    if tc.is_file():
        try:
            save_fn(TYPES_DEST, tc.read_text(encoding="utf-8"))
            st["types_saved"] = TYPES_DEST
        except Exception as e:  # noqa: BLE001
            st["types_saved"] = {"error": f"{type(e).__name__}: {str(e)[:300]}"}
    # справочник бумаг: только новые ключи держаний (read_fn нет — нечем сверить текущий файл, шаг пропускается)
    if read_fn is not None and dest.startswith(SAVE_DIR + "/"):
        st["attrs_saved"] = save_attrs(snap_text, save_fn, read_fn, now)
    # Журнал решений — после РАБОЧЕГО снапшота (читаемого вьюером и скиллами), как у скилла
    # (build_snapshot.py --commit); минуты на холодном кэше MOEX, поэтому ответ уходит сразу, а шаг идёт
    # фоновым потоком со статусом в status.json. hub-api пускает только Portfolio/decision-journal/{inputs,baselines,journal}.json + report-ДАТА.md (JOB_WHITELIST).
    steps = root is not None and not dest.startswith(AUTO_DIR + "/")
    if steps:
        t_ts = time.time()
        for key in POST_STEPS:
            st[key] = {"state": "running", "started_ts": t_ts}
    _write_status(data, run, st)
    if steps:
        def go():
            jobs = (("decision_journal", lambda: publish_journal(data, root, run, b.get("as_of"), save_fn, runner)),
                    ("stress_recalc", lambda: stress_job.recalc(root, runs_dir(data) / run / "stress", st["snapshot_path"],
                                                                save_fn, runner, now)))
            for key, fn in jobs:
                try:
                    res = fn()
                except Exception as e:  # noqa: BLE001 — производные: сбой не роняет сохранённый снапшот
                    res = {"error": f"{type(e).__name__}: {str(e)[:300]}"}
                res.setdefault("state", "error" if res.get("error") else "done")   # skipped/error шага пересчёта — свои
                with _post_lock:
                    cur = read_status(data, run) or {}
                    cur[key] = res
                    _write_status(data, run, cur)
        if background:
            threading.Thread(target=go, daemon=True).start()
        else:
            go()
        if log:
            log("pf_save", "ok", t0, run=run, path=dest, rebaseline_cash=st.get("rebaseline_cash"),
                cash_fact=st.get("cash_fact"), cash_fact_iis=st.get("cash_fact_iis"))
        return 200, {"saved": dest, "run": run}
    if log:
        log("pf_save", "ok", t0, run=run, path=dest, rebaseline_cash=st.get("rebaseline_cash"),
            cash_fact=st.get("cash_fact"), cash_fact_iis=st.get("cash_fact_iis"))
    return 200, {"saved": dest, "run": run}
