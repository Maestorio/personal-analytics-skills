#!/usr/bin/env python3
"""
build_snapshot.py — сборка снапшота портфеля одной командой, без LLM (API-1b, PR-2).

Делает то, что в SKILL.md (Шаги 1–7б) сейчас оркестрирует модель: те же скрипты, в том же
порядке, с теми же флагами. В расчёты не лезет — только запуск, выбор фолбэков, сводка,
проверки (checks.py) и, по --commit, запись.

    parse_portfolio.py  → portfolio.json     (если есть --balance; нет — позиции из сделок,
                                              остальное из прошлого снапшота: assemble --holdings-from-trades)
    portfolio_returns.py → returns.json      (если есть --trades)
    moex_quotes.py      → quotes.json        (health-check; MOEX недоступен → фолбэк)
    per_security_xirr.py → per_security.json (если есть --trades; цены из quotes.json)
    iis_returns.py      → iis_returns.json   (выгрузка ИИС-3: --iis-trades или поиск)
    assemble_snapshot.py → portfolio-<дата>.json   (+ --plan Portfolio/plan.json: сверка плана → plan_check)
    checks.py           → проверки целостности (блок / предупреждение / инфо)
    [--commit] запись в пробную папку Portfolio/snapshots/auto/ (portfolio-ДАТА-ЧЧММ-skill.json + build-summary);
    [--commit --working] запись в рабочую Portfolio/snapshots/ (журнал решений собирает только сайт)

Пакет прогона (сверка «скилл против скрипта», docs/api-migration/implementation-brief.md):
    --record DIR  входы, стартовое состояние кэшей и все ответы сети → DIR
    --replay DIR  та же сборка из DIR без сети (netcache.py), дата — из manifest.json

Примеры:
    python3 build_snapshot.py --trades trades_portfolio_707160-46.xlsx \\
        --balance "Общий баланс.numbers" --memory "$CM"            # сухой прогон
    python3 build_snapshot.py … --memory "$CM" --commit --working  # + запись в рабочую папку
    python3 build_snapshot.py … --memory "$CM" --record "$CM/Portfolio/parity/2026-10-20"
    python3 build_snapshot.py --replay "$CM/Portfolio/parity/2026-10-20" --out /tmp/pdl-shadow

Код выхода: 0 — собрано (и записано при --commit); 2 — блок-проверка (не записано);
1 — ошибка шага.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MOEX_QUOTES = REPO / "_shared-references" / "moex_quotes.py"
if not MOEX_QUOTES.exists():                      # упакованный .skill: pack.sh кладёт копию рядом
    MOEX_QUOTES = HERE / "moex_quotes.py"
NETCACHE = HERE / "netcache.py"

sys.path.insert(0, str(HERE))
if (REPO / "_shared-references").is_dir() and str(REPO / "_shared-references") not in sys.path:
    sys.path.append(str(REPO / "_shared-references"))   # time_msk (в .skill — рядом, pack.sh)
import time_msk  # noqa: E402
import hub_settings  # noqa: E402
import checks as checks_mod  # noqa: E402
import parity_check as parity_mod  # noqa: E402
import security_types as st_mod  # noqa: E402
import known_splits as ks_mod  # noqa: E402
from archive_snapshot import archive as archive_day  # noqa: E402

IIS_PATTERN = "trades_portfolio_838526*.xlsx"
DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SNAP_RE = re.compile(r"^portfolio-(\d{4}-\d{2}-\d{2})\.json$")

# Флаги assemble_snapshot, требующие решения владельца (SKILL.md Шаг 6–7)
DECISIONS = {
    "cash_drift_changed": (
        "Кэш-расхождение изменилось против базы. Проверь полноту выгрузки сделок "
        "(пополнения/выводы). Если изменение осознанное — пересобрать с --rebaseline-cash."),
    "cash_fact_stale": (
        "Кэш — оценка, опора устарела. Внеси свободные деньги основного портфеля из IntelInvest "
        "(все валюты в рублях) — пересобрать с --cash-fact <сумма>; сумма станет фактом и новой "
        "опорой расхождения."),
    "split_suspected": (
        "Похоже на сплит бумаги (цена изменилась в целое число раз без записи в реестре). Подтверди сплит — "
        "запись в реестр Portfolio/known-splits.json (дата возобновления торгов и коэффициент указаны в "
        "предупреждении) — и пересобери снапшот; если это не сплит, отклони подозрение."),
    "iis_returns_mismatch": (
        "Доходность ИИС-3 не сошлась с балансом — нужна свежая выгрузка счёта ИИС-3; "
        "числа ИИС-3 в снапшот не попали."),
    "iis_composition_changed": (
        "Состав ИИС-3 изменился с последней выгрузки — нужна свежая выгрузка счёта ИИС-3."),
}

# Флаги assemble_snapshot, которые не должны тонуть в общем счёте предупреждений
# (остальные — рутина: 51 blocked-позиция, раздвоение ИИС-3 и т.п.)
ATTENTION_FLAGS = ("balance_absent_holdings_from_trades", "no_prev_snapshot_for_trades_mode",
                   "bond_qty_vs_trades_mismatch", "balance_vs_trades_mismatch",
                   "avg_cost_fallback_value_over_qty", "iis_returns_failed",
                   "moex_unavailable", "moex_quotes_failed", "cbr_offline", "asset_type_changed", "manual_value_stale",
                   "bond_bucket_changed", "bond_rating_missing")

# Поля, которые меняются от запуска к запуску при тех же входах (не входят в хеш)
VOLATILE_KEYS = ("generated_at",)


class StepError(RuntimeError):
    pass


# ───────────────────────────── утилиты ─────────────────────────────

def _load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def snapshot_hash(snap: dict) -> str:
    """sha256 снапшота без служебных полей — признак идемпотентности."""
    s = {k: v for k, v in snap.items() if k not in VOLATILE_KEYS}
    return hashlib.sha256(json.dumps(s, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def find_prev_snapshot(snapshots_dir: Path | None, as_of: str) -> Path | None:
    """Самый свежий portfolio-*.json с опорой кэша и датой ≤ as_of (как Шаг 6 SKILL.md: «самый свежий»;
    при повторном прогоне в тот же день это файл того же дня).

    Снапшоты без баланса (snapshot_type trades_holdings) пропускаются, КРОМЕ тех, где кэш внесён
    владельцем (cash_reconciliation.current_drift_rub есть): у остальных расхождения кэша нет,
    и сборка поверх такого теряет кэш и итог
    портфеля — 27.10 сайт собрал поверх снапшота скилла того же дня: cash и NAV = null,
    «баланс перенесён с 27.10» вместо 23.10."""
    if not snapshots_dir or not snapshots_dir.is_dir():
        return None
    cands = sorted(((m.group(1), p) for p in snapshots_dir.iterdir()
                    if (m := SNAP_RE.match(p.name)) and m.group(1) <= as_of), reverse=True)
    for _d, p in cands:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("snapshot_type") == "trades_holdings" and \
                    (d.get("cash_reconciliation") or {}).get("current_drift_rub") is None:
                continue
        except (OSError, ValueError, AttributeError):
            continue
        return p
    return None


def find_compare_snapshot(snapshots_dir: Path | None, as_of: str) -> Path | None:
    """База сравнения в сводке сайта: самый свежий portfolio-*.json скилла с датой ≤ as_of НЕЗАВИСИМО от типа
    (при сборке в тот же день — файл того же дня). Отдельно от find_prev_snapshot: тот выбирает опору кэша
    и пропускает снапшоты без баланса, а сравнивать надо с тем, что владелец собрал последним.
    Снапшоты сайта лежат в snapshots/auto/ (имя с временем) и SNAP_RE их не видит."""
    if not snapshots_dir or not snapshots_dir.is_dir():
        return None
    cands = sorted(((m.group(1), p) for p in snapshots_dir.iterdir()
                    if (m := SNAP_RE.match(p.name)) and m.group(1) <= as_of), reverse=True)
    return cands[0][1] if cands else None


def find_iis_trades(dirs: list[Path]) -> Path | None:
    """Последняя переданная выгрузка ИИС-3 (Шаг 4б, решение владельца 2026-10-21): не дали
    файл — берём последний из Portfolio/inputs/ (туда его кладёт импорт на сайте), а не
    «самый свежий» из папок Mac (16.10 там лежал файл от 12.10, свежий — в «Загрузках»).
    Свежесть — по папке-дате inputs/<YYYY-MM-DD>/, затем по времени изменения."""
    cands = [p for d in dirs if d and d.is_dir() for p in d.rglob(IIS_PATTERN)]

    def key(p: Path):
        return (p.parent.name if DATE_DIR_RE.match(p.parent.name) else "", p.stat().st_mtime)
    return max(cands, key=key) if cands else None


def active_tickers(returns: dict) -> list[str]:
    """Шаг 4 SKILL.md: позиции returns.snapshot_current без блокировки и с qty > 0."""
    pos = ((returns or {}).get("snapshot_current") or {}).get("positions") or []
    return [p["ticker"] for p in pos if not p.get("is_blocked") and (p.get("qty") or 0) > 0]


def secids_from_trades(returns: dict | None, prev_snap: dict | None) -> list[dict]:
    """Бумаги для котировок без баланса: активные позиции сделок + ИИС-3 прошлого снапшота
    (сделок ИИС-3 в выгрузке основного счёта нет). Формат holdings снапшота v2."""
    out, seen = [], set()
    for p in ((returns or {}).get("snapshot_current") or {}).get("positions") or []:
        if p.get("is_blocked") or not (p.get("qty") or 0) > 0 or p.get("ticker") in seen:
            continue
        seen.add(p["ticker"])
        out.append({"ticker": p["ticker"], "asset_type": p.get("type"), "status": "normal"})
    for h in (prev_snap or {}).get("holdings") or []:
        if h.get("account") == "iis_3" and h.get("status") != "blocked" and h.get("ticker") not in seen:
            seen.add(h.get("ticker"))
            out.append({"ticker": h.get("ticker"), "isin": h.get("isin"), "asset_type": h.get("asset_type"),
                        "status": "normal"})
    return out


def closed_tickers(returns: dict | None, trades_by_ticker: dict) -> list[str]:
    """Закрытые бумаги: есть покупка (или корректировка), позиции нет — ни обычной, ни заблокированной.
    «Деньги», фьючерсы (вариационная маржа) и тикеры только с дивидендами/вводом без покупок не берём."""
    held = {p.get("ticker") for p in ((returns or {}).get("snapshot_current") or {}).get("positions") or []
            if (p.get("qty") or 0) > 0}
    out = []
    for tk, trs in trades_by_ticker.items():
        if tk in held or not isinstance(tk, str) or tk.startswith("Деньги"):
            continue
        ops = {t.operation for t in trs}
        if ops & {"Начисление вариационной маржи", "Списание вариационной маржи"}:
            continue
        if ops & {"Покупка", "Корректировка"}:
            out.append(tk)
    return sorted(out)


def _health_ok(p: subprocess.CompletedProcess) -> bool:
    """moex_quotes.py --health выходит с кодом 0 и при недоступном ISS — признак в JSON
    ("ok": false). Скилл читает JSON глазами модели; здесь — разбор."""
    if p.returncode != 0:
        return False
    try:
        return bool(json.loads(p.stdout).get("ok"))
    except (ValueError, AttributeError):
        return False


def quotes_ok(path: Path) -> bool:
    """quotes.json moex_quotes.py пригоден: читается и есть хоть одна котировка."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool((d or {}).get("quotes")) if isinstance(d, dict) else False


def trade_tickers_and_ops(*paths) -> dict[str, list]:
    """Выгрузки сделок → {тикер: [Trade]} (для сверки типов и списка тикеров справочника).
    Не читается файл или нет openpyxl — пусто: справочник — страховка, сборку не валит."""
    out: dict[str, list] = {}
    try:
        import portfolio_returns as pr
        for p in paths:
            if p:
                for t in pr.parse_trades(str(p)):
                    out.setdefault(t.ticker, []).append(t)
    except Exception:                                   # noqa: BLE001
        pass
    return out


_TICKER_RE = re.compile(r"^[A-Za-z0-9]+$")


def type_lookup_tickers(trades_by_ticker: dict, prev_snap: dict | None, portfolio: dict | None) -> list[str]:
    """Тикеры для справочника типов: сделки + холдинги прошлого снапшота и баланса.
    Деньги, фьючерсы и прочие не-биржевые тикеры (пробелы, дефисы) не спрашиваем."""
    names = list(trades_by_ticker)
    for src in (prev_snap, portfolio):
        names += [h.get("ticker") for h in (src or {}).get("holdings") or [] if isinstance(h, dict)]
    return sorted({t for t in names if isinstance(t, str) and _TICKER_RE.match(t)})


def build_type_check(snapshot: dict, prev_snap: dict | None, types_path, trades_by_ticker: dict,
                     online: bool, fetched: list, failed: list, cache_label: str | None = None) -> dict:
    """Блок snapshot.type_check и флаги: сверка типа каждого холдинга с прошлым снапшотом и с эвристикой."""
    import portfolio_returns as pr
    data = st_mod.load_types(types_path) if types_path else {"by_ticker": {}}
    moex = st_mod.overrides_from(data)
    heur = {}
    for tk, tr in trades_by_ticker.items():
        try:
            heur[tk] = pr.classify_instrument_type(tr, use_overrides=False)
        except Exception:                               # noqa: BLE001
            pass
    # бумаги без сделок (из баланса или переноса): эвристика по одному тикеру (known_funds, FX/RSH, ISIN/ОФЗ);
    # дефолт «stock» и «other» — не эвристика, иначе каждая такая бумага давала бы шум
    for h in snapshot.get("holdings") or []:
        tk = h.get("ticker")
        if not isinstance(tk, str) or not tk or tk in heur or tk in trades_by_ticker:
            continue
        try:
            stub = pr.Trade(ticker=tk, name=tk, operation="", date=dt.date.today(), qty=None, price=None, nominal=None, nkd=None,
                            commission=0.0, amount=0.0, amount_no_comm=0.0, currency="RUB", note="")
            t = pr.classify_instrument_type([stub], use_overrides=False)
        except Exception:                               # noqa: BLE001
            continue
        if t in ("fund", "bond"):
            heur[tk] = t
    changes = st_mod.compare_types(snapshot.get("holdings") or [], (prev_snap or {}).get("holdings"),
                                   moex, heur)
    return {"cache": (cache_label or str(types_path)) if types_path else None, "online": online,
            "fetched": fetched, "failed": failed, "changes": changes}


def type_check_flags(tc: dict, n_asked: int) -> list[dict]:
    flags = []
    if tc["changes"]:
        flags.append({"step": "build_snapshot", "severity": "warn", "code": "asset_type_changed",
                      "message": "Тип бумаги изменился: "
                                 + "; ".join(st_mod.change_text(c) for c in tc["changes"])
                                 + ". Проверить до перевода снапшота в рабочий."})
    if tc.get("errors"):
        # шаг справочника сломался (не записался / упал) — это не «биржа лежит», а дефект окружения
        flags.append({"step": "build_snapshot", "severity": "warning", "code": "types_step_failed",
                      "message": "Шаг типов бумаг не отработал: " + "; ".join(tc["errors"])[:600]
                                 + ". Типы — по справочнику и эвристике."})
    elif tc["online"] and tc["failed"] and n_asked and len(tc["failed"]) >= n_asked:
        flags.append({"step": "build_snapshot", "severity": "info", "code": "moex_types_unavailable",
                      "message": "Типы бумаг с Мосбиржи не получены (ошибки по всем тикерам): "
                                 "использованы справочник и эвристика."})
    return flags


def _flag_codes(snap: dict) -> list[str]:
    return [f.get("code") for f in snap.get("data_quality_flags") or [] if f.get("code")]


# ───────────────────────────── запуск шагов ─────────────────────────────

class Runner:
    """Запуск скриптов: в обычном режиме — как есть; с пакетом — через netcache."""

    def __init__(self, work: Path, net_mode: str | None, net_dir: Path | None, env: dict):
        self.work, self.net_mode, self.net_dir, self.env = work, net_mode, net_dir, env
        self.log: list[dict] = []

    def run(self, name: str, script: Path, args: list[str], stdout: Path | None = None,
            check: bool = True) -> subprocess.CompletedProcess:
        cmd = [sys.executable, str(script), *args]
        if self.net_mode:
            cmd = [sys.executable, str(NETCACHE), "run", f"--{self.net_mode}", str(self.net_dir),
                   "--", str(script), *args]
        t0 = time.monotonic()
        p = subprocess.run(cmd, cwd=str(self.work), env=self.env, text=True,
                           capture_output=True)
        if stdout is not None:
            stdout.write_text(p.stdout, encoding="utf-8")
        (self.work / f"{name}.stderr.txt").write_text(p.stderr or "", encoding="utf-8")
        self.log.append({"step": name, "script": script.name, "args": args, "rc": p.returncode,
                         "seconds": round(time.monotonic() - t0, 1)})
        if check and p.returncode != 0:
            tail = "\n".join((p.stderr or "").strip().splitlines()[-8:])
            raise StepError(f"шаг {name} ({script.name}) завершился с кодом {p.returncode}:\n{tail}")
        return p


def is_trades_only(snap) -> bool:
    """Снапшот без баланса (snapshot_type trades_holdings) и без внесённого владельцем кэша
    (cash_reconciliation.current_drift_rub пуст).
    ⚠ SYNC с tools/hosting/notify/pf_build.py::_is_trades_only — правило одно и то же."""
    return (isinstance(snap, dict) and snap.get("snapshot_type") == "trades_holdings"
            and (snap.get("cash_reconciliation") or {}).get("current_drift_rub") is None)


def downgrade_refusal(new: dict, old_path: Path, as_of: str) -> str | None:
    """Сборка «только сделки» поверх сохранённого снапшота того же дня с балансом или с внесённым кэшем
    ухудшает его (теряются кэш и итог портфеля) → текст отказа по-русски; иначе None.
    ⚠ SYNC с pf_build.save (409 reason balance / cash_fact), поведение то же."""
    if not old_path.is_file() or not is_trades_only(new):
        return None
    try:
        old = _load_json(old_path)
    except (OSError, ValueError):
        return None
    if not isinstance(old, dict) or is_trades_only(old):
        return None
    if old.get("snapshot_type") == "trades_holdings":
        return (f"уже сохранён снапшот {as_of} с внесённым кэшем — эта сборка без кэша его ухудшит: "
                "впиши кэш (--cash-fact) и собери снова; осознанная перезапись — --allow-downgrade")
    return (f"уже сохранён снапшот {as_of} с «Общим балансом» — сборка без баланса его ухудшит: "
            "собери с балансом (--balance); осознанная перезапись — --allow-downgrade")


def commit_snapshot(snap_path: Path, snapshots_dir: Path, as_of: str) -> tuple[Path, dict]:
    """Шаг 7: снапшот на место атомарно (временный файл + rename в той же папке).
    Снапшот за эту дату уже есть → сначала прежняя версия уходит в `.versions/`
    (archive_snapshot.py, PDL-SNAPV: перезапись 16.10 сделала обзоры невоспроизводимыми),
    затем перезапись под тем же именем. Возвращает (путь, результат архивации)."""
    dest = snapshots_dir / f"portfolio-{as_of}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    archived = archive_day(str(snapshots_dir), as_of)
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.copy2(snap_path, tmp)
    os.replace(tmp, dest)
    return dest, archived


def commit_guarded(snapshot: dict, snap_path: Path, snapshots_dir: Path, as_of: str,
                   allow_downgrade: bool = False) -> tuple[Path, dict]:
    """commit_snapshot с проверкой «не ухудшает сохранённый снапшот дня»: отказ (StepError, код выхода 1) —
    до архивации и записи, ничего не пишется. allow_downgrade — осознанная перезапись (прежняя версия в .versions/)."""
    if not allow_downgrade:
        refusal = downgrade_refusal(snapshot, snapshots_dir / f"portfolio-{as_of}.json", as_of)
        if refusal:
            raise StepError(f"--commit отказан, ничего не записано: {refusal}")
    return commit_snapshot(snap_path, snapshots_dir, as_of)


def probe_paths(snapshots_dir: Path, as_of: str, now: dt.datetime | None = None) -> tuple[Path, Path]:
    """Пробная папка скилла: snapshots/auto/portfolio-ДАТА-ЧЧММ-skill.json и build-summary рядом с тем же суффиксом.
    Имя не совпадает с SNAP_RE (рабочие читатели смотрят только snapshots/, не auto/)."""
    tag = f"{as_of}-{(now or dt.datetime.now()).strftime('%H%M')}-skill"
    auto = snapshots_dir / "auto"
    return auto / f"portfolio-{tag}.json", auto / f"build-summary-{tag}.json"


def commit_probe(snap_path: Path, snapshots_dir: Path, as_of: str,
                 now: dt.datetime | None = None) -> tuple[Path, Path]:
    """`--commit` без `--working`: снапшот в пробную папку (атомарно). Рабочий, журнал и индекс не трогаются.
    Возвращает (путь снапшота, путь сводки рядом)."""
    dest, summ = probe_paths(snapshots_dir, as_of, now)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.copy2(snap_path, tmp)
    os.replace(tmp, dest)
    return dest, summ


# ───────────────────────────── сборка ─────────────────────────────

PARITY_KNOWN_NOBALANCE = HERE.parent / "references" / "parity-known-diffs-nobalance.yaml"


def run_parity(snapshot: dict, against: Path | None, snapshots_dir: Path | None, as_of: str,
               report_path: Path) -> dict | None:
    """Поле за полем: сборка без баланса против снапшота того же дня с балансом (этап 6 ухода от Numbers).
    against не задан → {snapshots_dir}/portfolio-{as_of}.json, если в нём есть баланс (parity.auto);
    нет такого или сама сборка с балансом → None. Расхождения не блокируют. Сводка — в снапшот и build-summary,
    отчёт — report_path (parity-report.md)."""
    auto = False
    if against is None:
        cand = snapshots_dir / f"portfolio-{as_of}.json" if snapshots_dir else None
        if not cand or not cand.is_file() or (snapshot.get("input_files") or {}).get("balance"):
            return None
        try:
            if not (_load_json(cand).get("input_files") or {}).get("balance"):
                return None
        except (OSError, ValueError):
            return None
        against, auto = cand, True
    try:
        ref = _load_json(against)
    except (OSError, ValueError) as e:
        return {"against": str(against), "auto": auto, "error": f"снапшот для сверки не прочитан: {e}"}
    a = parity_mod.canon(ref)
    b = parity_mod.canon(json.loads(json.dumps(snapshot)))
    known = parity_mod.load_known(PARITY_KNOWN_NOBALANCE)
    res = parity_mod.classify(parity_mod.compare(a, b), known)
    n = parity_mod._count_leaves(a)
    diverged = [p for p, *_ in res["differs"]]
    report_path.write_text(parity_mod.render(res, str(against), "сборка без баланса", n), encoding="utf-8")
    return {
        "against": str(against), "against_date": ref.get("as_of_date"),
        "same_day": ref.get("as_of_date") == as_of, "auto": auto,
        "matched": max(n - len(res["tolerated"]) - len(res["known"]) - len(diverged), 0),
        "within_tol": len(res["tolerated"]), "known": len(res["known"]), "diverged": len(diverged),
        "diverged_paths": diverged[:50], "report_path": str(report_path),
    }


def build(opts: argparse.Namespace) -> dict:
    replay = Path(opts.replay) if opts.replay else None
    record = Path(opts.record) if opts.record else None
    manifest: dict = _load_json(replay / "manifest.json") if replay else {}

    as_of = manifest.get("as_of") or opts.as_of or dt.date.today().isoformat()
    for flag, key, what in (("--cash-fact", "cash_fact", "свободные деньги основного портфеля из IntelInvest"),
                            ("--cash-fact-iis", "cash_fact_iis", "свободные деньги ИИС-3")):
        cf = getattr(opts, key) if getattr(opts, key, None) is not None else manifest.get(key)
        if cf is not None:
            try:
                ok = isinstance(cf, (int, float)) and not isinstance(cf, bool) and 0 <= float(cf) < float("inf")
            except (TypeError, ValueError):
                ok = False
            if not ok:
                raise StepError(f"{flag}: нужно неотрицательное число ₽ ({what}), получено {cf!r}")
    work = Path(opts.out) if opts.out else Path(tempfile.mkdtemp(prefix="pdl-build-"))
    work.mkdir(parents=True, exist_ok=True)
    memory = Path(opts.memory) if opts.memory else None
    snapshots_dir = memory / "Portfolio" / "snapshots" if memory else None
    if opts.commit and memory and not replay:
        hub_settings.require_ai(memory, "build_snapshot.py --commit", "запись снапшота", zones=("Portfolio", "scenarios"))   # вход — вывод модели: при «без ИИ» отказ

    # ── входы ──
    if replay:
        inp = replay / "inputs"
        m_in = manifest.get("inputs") or {}
        trades = inp / m_in["trades"] if m_in.get("trades") else None
        balance = inp / m_in["balance"] if m_in.get("balance") else None
        iis_trades = inp / m_in["iis_trades"] if m_in.get("iis_trades") else None
        prev = inp / m_in["prev_snapshot"] if m_in.get("prev_snapshot") else None
        compare = inp / m_in["compare_snapshot"] if m_in.get("compare_snapshot") else None
        overrides = inp / m_in["sector_overrides"] if m_in.get("sector_overrides") else None
        forecasts_dir = inp / "forecasts" if (inp / "forecasts").is_dir() else None
        carry_dir = inp / "snapshots"
        # план пакета лежит в caches-start/plan.json (записан при --record): повтор идёт тем же путём «сделки + план»;
        # пакет без плана — как раньше, без плана
        _pp = replay / "caches-start" / "plan.json"
        plan_file = Path(opts.plan) if opts.plan else (_pp if _pp.is_file() else None)
    else:
        trades = Path(opts.trades) if opts.trades else None
        balance = Path(opts.balance) if opts.balance else None
        iis_trades = Path(opts.iis_trades) if opts.iis_trades else None
        if iis_trades is None and trades is not None and not opts.no_iis_search:
            dirs = [Path(d) for d in (opts.iis_dir or [])]
            if memory:
                dirs.append(memory / "Portfolio" / "inputs")
            iis_trades = find_iis_trades(dirs)
        prev = Path(opts.prev_snapshot) if opts.prev_snapshot else find_prev_snapshot(snapshots_dir, as_of)
        compare = find_compare_snapshot(snapshots_dir, as_of)
        overrides = Path(opts.sector_overrides) if opts.sector_overrides else (
            memory / "sector-overrides.yaml" if memory and (memory / "sector-overrides.yaml").exists() else None)
        forecasts_dir = memory / "forecasts" if memory and (memory / "forecasts").is_dir() else None
        plan_file = Path(opts.plan) if opts.plan else (
            memory / "Portfolio" / "plan.json" if memory and (memory / "Portfolio" / "plan.json").is_file() else None)
        carry_dir = snapshots_dir

    if trades is None and balance is None:
        raise StepError("нужен хотя бы один файл: --trades (сделки IntelInvest) и/или --balance "
                        "(Общий баланс.numbers)")
    for label, p in (("trades", trades), ("balance", balance), ("iis_trades", iis_trades)):
        if p is not None and not p.is_file():
            raise StepError(f"файл {label} не найден: {p}")

    # Входы — в рабочую папку под именами, которые даёт им скилл (/tmp/trades.xlsx,
    # /tmp/balance.<ext>): они попадают в snapshot.input_files, и сверка не должна их ловить.
    staged: dict[str, Path] = {}
    if trades:
        staged["trades"] = work / "trades.xlsx"
        shutil.copy2(trades, staged["trades"])
    if balance:
        staged["balance"] = work / f"balance{balance.suffix.lower()}"
        shutil.copy2(balance, staged["balance"])
    if iis_trades:
        staged["iis_trades"] = work / "iis_trades.xlsx"
        shutil.copy2(iis_trades, staged["iis_trades"])

    # ── пакет прогона: стартовое состояние кэшей ──
    env = dict(os.environ)
    env["PDL_AS_OF"] = as_of            # parse_portfolio: extraction_date = дата снапшота
    net_mode = net_dir = None
    types_path = (Path(opts.types_cache) if opts.types_cache else
                  (memory / "Portfolio" / "security-types.json" if memory else None))
    splits_path = (Path(opts.splits_file) if opts.splits_file else
                   (memory / "Portfolio" / "known-splits.json" if memory else None))
    if record or replay:
        bundle = record or replay
        net_mode, net_dir = ("record", record / "net") if record else ("replay", replay / "net")
        caches = work / "caches"
        if caches.exists():
            shutil.rmtree(caches)
        if record:
            start = record / "caches-start"
            start.mkdir(parents=True, exist_ok=True)
            cbr_src = Path(os.environ.get("PDL_CBR_CACHE") or "/tmp/cbr_rates_cache.json")
            if cbr_src.is_file():
                shutil.copy2(cbr_src, start / "cbr_rates_cache.json")
            if plan_file and plan_file.is_file():
                shutil.copy2(plan_file, start / "plan.json")
            ms_src = Path(os.environ.get("PDL_MARKET_SERIES_CACHE")
                          or Path.home() / ".cache" / "claude-skills" / "market-series")
            if ms_src.is_dir():
                shutil.copytree(ms_src, start / "market-series", dirs_exist_ok=True)
            if splits_path and splits_path.is_file():
                shutil.copy2(splits_path, start / "known-splits.json")      # реестр сплитов — вход прогона
        shutil.copytree(bundle / "caches-start", caches) if (bundle / "caches-start").is_dir() \
            else caches.mkdir(parents=True)
        (caches / "market-series").mkdir(exist_ok=True)
        types_src = Path(opts.types_cache) if opts.types_cache else (
            memory / "Portfolio" / "security-types.json" if memory else None)
        if record and types_src and types_src.is_file():
            shutil.copy2(types_src, record / "caches-start" / "security-types.json")
        # справочник типов: при повторе — пост-обновления записи (иначе стартовый)
        for cand in ((bundle / "security-types.json", bundle / "caches-start" / "security-types.json")):
            if cand.is_file():
                shutil.copy2(cand, caches / "security-types.json")
                break
        types_path = caches / "security-types.json"
        splits_path = caches / "known-splits.json"       # из пакета; нет в пакете — встроенный набор
        env["PDL_CBR_CACHE"] = str(caches / "cbr_rates_cache.json")
        env["PDL_MARKET_SERIES_CACHE"] = str(caches / "market-series")

    # реестр сплитов: невалидный файл — сборка останавливается до всех шагов, снапшот не пишется
    if splits_path and not splits_path.is_file():
        splits_path = None
    try:
        splits_registry, splits_dismissed = ks_mod.load(splits_path)
    except ks_mod.KnownSplitsError as e:
        raise StepError(str(e)) from e
    splits_args = ["--splits-file", str(splits_path)] if splits_path else []

    runner = Runner(work, net_mode, net_dir, env)
    decisions_made: dict = dict(manifest.get("decisions") or {})
    flags_extra: list[dict] = []

    # ── MOEX: health-check, повтор, фолбэк (Шаг 3 / Шаг 5 SKILL.md) ──
    if "moex_down" in decisions_made:
        moex_down = decisions_made["moex_down"]
    elif opts.no_moex:
        moex_down = True
    else:
        moex_down = True
        for attempt in range(2):
            if _health_ok(runner.run("moex_health", MOEX_QUOTES, ["--health"], check=False)):
                moex_down = False
                break
            if attempt == 0 and not replay:
                time.sleep(3)
    decisions_made["moex_down"] = moex_down
    if moex_down:
        flags_extra.append({"step": "build_snapshot", "severity": "warning", "code": "moex_unavailable",
                            "message": "MOEX ISS недоступен, цены из last_trade_price; облигационные "
                                       "поля MOEX (купон, НКД, YTM) не заполнены."})
    cbr_offline = bool(decisions_made.get("cbr_offline") or opts.cbr_offline)

    # ── Шаг 2: баланс ──
    portfolio_json = work / "portfolio.json"
    if balance:
        runner.run("parse_portfolio", HERE / "parse_portfolio.py", [str(staged["balance"])],
                   stdout=portfolio_json)

    # ── Тип бумаги с Мосбиржи: справочник обновляется ДО шагов возвратов (сеть — только здесь) ──
    prev_for_types = _load_json(prev) if prev else None
    trades_by_ticker = trade_tickers_and_ops(staged.get("trades"), staged.get("iis_trades"))
    types_online = bool(types_path) and not opts.no_moex and not moex_down and not replay
    types_asked = type_lookup_tickers(trades_by_ticker, prev_for_types,
                                      _load_json(portfolio_json) if balance else None)
    types_fetched: list = []
    types_failed: list = []
    types_errors: list = []
    if types_online and types_asked:
        p = runner.run("security_types", HERE / "security_types.py",
                       ["refresh", "--cache", str(types_path), "--tickers", ",".join(types_asked),
                        "--today", as_of], check=False)
        try:
            r = json.loads(p.stdout)
            types_fetched, types_failed = list(r.get("fetched") or []), list(r.get("failed") or [])
            types_errors = [str(x) for x in (r.get("errors") or [])]
        except ValueError:
            types_failed = list(types_asked)
            types_errors = [f"security_types.py: код {p.returncode}, вывод не JSON: "
                            + ((p.stderr or "").strip().splitlines() or ["?"])[-1][:200]]
        if record and types_path.is_file():
            shutil.copy2(types_path, record / "security-types.json")
    types_args = ["--types-cache", str(types_path)] if types_path else []
    types_args += splits_args          # те же четыре скрипта принимают и --splits-file

    # ── Шаг 3: доходности ──
    returns_json = work / "returns.json"
    if trades:
        def returns_args(offline: bool) -> list[str]:
            a = ["--trades", str(staged["trades"]), "--as-of", as_of, "--format", "json", *types_args]
            if moex_down:
                a.append("--no-moex")
            if offline:
                a.append("--cbr-offline")
            return a
        p = runner.run("portfolio_returns", HERE / "portfolio_returns.py", returns_args(cbr_offline),
                       stdout=returns_json, check=False)
        if p.returncode != 0 and not cbr_offline and re.search(r"cbr|503", p.stderr or "", re.I):
            cbr_offline = True              # Шаг 3: «Если ЦБ РФ возвращает 503»
            runner.run("portfolio_returns_cbr_offline", HERE / "portfolio_returns.py",
                       returns_args(True), stdout=returns_json)
        elif p.returncode != 0:
            raise StepError("шаг portfolio_returns завершился с кодом "
                            f"{p.returncode}:\n" + "\n".join((p.stderr or "").splitlines()[-8:]))
    decisions_made["cbr_offline"] = cbr_offline
    if cbr_offline:
        flags_extra.append({"step": "build_snapshot", "severity": "warning", "code": "cbr_offline",
                            "message": "ЦБ РФ недоступен, курсы из bundled cache."})
    returns = _load_json(returns_json) if trades else None

    # ── Шаг 4б: ИИС-3 ──
    iis_json = work / "iis_returns.json"
    if "iis_trades" in staged:
        a = ["--trades", str(staged["iis_trades"]), "--as-of", as_of, "--output", str(iis_json), *types_args]
        if forecasts_dir:
            a += ["--forecasts-dir", str(forecasts_dir)]
        if cbr_offline:
            a.append("--cbr-offline")
        p = runner.run("iis_returns", HERE / "iis_returns.py", a, check=False)
        if p.returncode != 0:
            # Шаг 4б: нет расчёта → assemble переносит блок ИИС-3 из прошлого снапшота
            iis_json.unlink(missing_ok=True)
            reason = ((p.stderr or "").strip().splitlines() or ["?"])[-1]
            # Текст сетевой ошибки зависит от среды (прокси, netcache) — во флаг не берём,
            # иначе сверка записи и повтора ловит его как расхождение.
            reason = re.split(r":? ?<urlopen error|: HTTP Error", reason)[0][:300]
            flags_extra.append({"step": "build_snapshot", "severity": "warning", "code": "iis_returns_failed",
                                "message": "Расчёт доходности ИИС-3 не выполнен, блок перенесён из прошлого "
                                           f"снапшота: {reason}"})

    # ── Шаг 5: котировки ──
    quotes_json = work / "quotes.json"
    # Без баланса (решение 2026-10-21) список бумаг — из сделок + ИИС-3 прошлого снапшота,
    # в формате снапшота v2 (его понимает moex_quotes.py --from-portfolio).
    quotes_src = portfolio_json
    if not balance and trades:
        quotes_src = work / "secids-from-trades.json"
        _write_json(quotes_src, {"holdings": secids_from_trades(returns, _load_json(prev) if prev else None)})
    if moex_down or not (balance or trades):
        quotes_json.write_text("{}", encoding="utf-8")
    else:
        # Шаг 5: MOEX не ответил → флаг и дальше без котировок, сборку не роняем.
        # Живой случай 2026-10-21: health прошёл, а через 17 с все 65 запросов котировок
        # упали разом (сбой VPN) — moex_quotes.py вышел с кодом 1, сборка остановилась.
        ok = False
        for attempt in range(2):
            p = runner.run("moex_quotes" if attempt == 0 else "moex_quotes_retry", MOEX_QUOTES,
                           ["--fields", "weekly", "--from-portfolio", str(quotes_src), "--json"],
                           stdout=quotes_json, check=False)
            ok = quotes_ok(quotes_json)
            if ok:
                break
            if attempt == 0 and not replay:
                time.sleep(5)
        if not ok:
            quotes_json.write_text("{}", encoding="utf-8")
            flags_extra.append({"step": "build_snapshot", "severity": "warning", "code": "moex_quotes_failed",
                                "message": "Котировки MOEX не получены (две попытки): облигационные поля "
                                           "MOEX (купон, НКД, YTM) не заполнены, цены — из доходностей."})

    # ── Шаг 4: per-security XIRR (после котировок: одна цена в holdings и per_instrument_xirr, случай 27.10) ──
    per_security_json = work / "per_security.json"
    if trades:
        tickers = active_tickers(returns)
        if tickers:
            a = ["--trades", str(staged["trades"]), "--tickers", ",".join(tickers), "--as-of", as_of,
                 "--format", "json", *types_args]
            if balance:
                a += ["--common", str(portfolio_json)]
            if moex_down:
                a.append("--no-moex")
            elif quotes_ok(quotes_json):
                a += ["--quotes", str(quotes_json)]
            if cbr_offline:
                a.append("--cbr-offline")
            runner.run("per_security_xirr", HERE / "per_security_xirr.py", a, stdout=per_security_json)
        else:
            per_security_json.write_text("{}", encoding="utf-8")
    # проданные и погашенные бумаги — отдельный прогон без сети (терминала у них нет): per_instrument_xirr_closed
    per_security_closed_json = work / "per_security_closed.json"
    closed = closed_tickers(returns, trades_by_ticker) if trades else []
    if closed:
        a = ["--trades", str(staged["trades"]), "--tickers", ",".join(closed), "--as-of", as_of,
             "--format", "json", "--no-moex", *types_args]
        if cbr_offline:
            a.append("--cbr-offline")
        runner.run("per_security_closed", HERE / "per_security_xirr.py", a, stdout=per_security_closed_json)

    # ── Шаг 6: сборка ──
    snap_path = work / f"portfolio-{as_of}.json"
    a = ["--quotes", str(quotes_json), "--output", str(snap_path), "--as-of", as_of]
    a += ["--portfolio", str(portfolio_json)] if balance else ["--portfolio", str(work / "_none.json")]
    a += ["--returns", str(returns_json)] if trades else ["--returns", str(work / "_none.json")]
    if trades:
        a += ["--per-security", str(per_security_json), "--trades", str(staged["trades"])]
        if closed:
            a += ["--per-security-closed", str(per_security_closed_json)]
    if balance:
        a += ["--balance", str(staged["balance"])]
    elif trades:
        a.append("--holdings-from-trades")       # позиции из сделок, остальное — из прошлого снапшота
    if prev:
        a += ["--prev-snapshot", str(prev)]
    if overrides:
        a += ["--sector-overrides", str(overrides)]
    if carry_dir and carry_dir.is_dir():
        a += ["--snapshots-dir", str(carry_dir)]
    if iis_json.exists():
        a += ["--iis-returns", str(iis_json)]
    if moex_down:
        a.append("--no-bond-locked")           # график MOEX недоступен — «При покупке» основного счёта не считаем
    elif forecasts_dir:
        a += ["--forecasts-dir", str(forecasts_dir)]
    if plan_file:
        a += ["--plan", str(plan_file)]
        if opts.plan_primary:
            a.append("--plan-primary")
    # корзина облигации: assemble ищет справочник типов и обзоры «рядом с --plan», а на сайте план — копия в папке
    # прогона; передаём явно (справочник уже обновлён шагом типов выше; в повторе — из пакета)
    if types_path and types_path.is_file():
        a += ["--types-cache", str(types_path)]
    a += splits_args
    reviews_dir = (replay / "caches-start" / "weekly-reviews") if replay else (
        memory / "Portfolio" / "weekly-reviews" if memory else None)
    if reviews_dir and reviews_dir.is_dir():
        a += ["--reviews-dir", str(reviews_dir)]
    rebaseline = bool(opts.rebaseline_cash or manifest.get("rebaseline_cash"))
    if rebaseline:
        a.append("--rebaseline-cash")
    cash_fact = opts.cash_fact if opts.cash_fact is not None else manifest.get("cash_fact")
    if cash_fact is not None:
        a += ["--cash-fact", repr(float(cash_fact))]
    cash_fact_iis = opts.cash_fact_iis if getattr(opts, "cash_fact_iis", None) is not None else manifest.get("cash_fact_iis")
    if cash_fact_iis is not None:
        a += ["--cash-fact-iis", repr(float(cash_fact_iis))]
    runner.run("assemble_snapshot", HERE / "assemble_snapshot.py", a)
    snapshot = _load_json(snap_path)
    # ── сверка типов бумаг: прошлый снапшот / биржа / эвристика ──
    snapshot["type_check"] = build_type_check(snapshot, prev_for_types, types_path if types_path and
                                              types_path.is_file() else None, trades_by_ticker,
                                              types_online, types_fetched, types_failed,
                                              "bundle:caches/security-types.json" if net_mode else None)
    snapshot["type_check"]["errors"] = types_errors
    snapshot["known_splits"] = {"source": "file" if splits_path else "builtin",
                                "file": splits_path.name if splits_path else None,
                                "count": sum(len(v) for v in splits_registry.values())}
    flags_extra += type_check_flags(snapshot["type_check"], len(types_asked))
    snapshot.setdefault("data_quality_flags", []).extend(flags_extra)
    # сверка «без баланса ↔ с балансом» того же дня: не блокирует, нужна для решения о переключении источника
    parity = run_parity(snapshot, Path(opts.parity_against) if getattr(opts, "parity_against", None) else None,
                        snapshots_dir, as_of, work / "parity-report.md")
    snapshot["parity"] = {k: v for k, v in parity.items() if k != "report_path"} if parity else None   # путь отчёта — в сводке
    _write_json(snap_path, snapshot)

    # ── проверки ──
    prev_snap = _load_json(prev) if prev else None
    trades_info = checks_mod.inspect_trades(staged["trades"]) if trades else None
    check_results = checks_mod.run_all(snapshot, prev_snap, trades_info=trades_info,
                                       as_of=as_of, returns=returns,
                                       splits=splits_registry, dismissed=splits_dismissed)
    # что эта сборка сочла подозрительным (дубли выплат) — следующая сборка по этому узнаёт чистку дублей
    snapshot["build_suspects"] = checks_mod.suspects_for_snapshot(check_results)
    _write_json(snap_path, snapshot)

    # ── пакет: входы и манифест ──
    if record:
        rin = record / "inputs"
        rin.mkdir(parents=True, exist_ok=True)
        m_in = {}
        for key, src in (("trades", trades), ("balance", balance), ("iis_trades", iis_trades),
                         ("prev_snapshot", prev), ("sector_overrides", overrides)):
            if src:
                shutil.copy2(src, rin / src.name)
                m_in[key] = src.name
        if carry_dir and carry_dir.is_dir():          # источники переноса блока ИИС-3
            (rin / "snapshots").mkdir(exist_ok=True)
            for p in sorted(carry_dir.glob("portfolio-*.json"), reverse=True)[:3]:
                shutil.copy2(p, rin / "snapshots" / p.name)
        if forecasts_dir:
            shutil.copytree(forecasts_dir, rin / "forecasts", dirs_exist_ok=True)
        _write_json(record / "manifest.json", {
            "kind": "pdl-run-bundle@1", "as_of": as_of,
            "created_at": time_msk.now_iso(),
            "inputs": m_in, "decisions": decisions_made, "rebaseline_cash": rebaseline,
            "cash_fact": cash_fact, "cash_fact_iis": cash_fact_iis,
        })
        shutil.copy2(snap_path, record / "script-snapshot.json")

    # ── сводка ──
    codes = _flag_codes(snapshot)
    codes += [r["id"] for r in check_results if r["id"] == "split_suspected"]   # решение владельца, а не флаг снапшота
    by_sev: dict[str, int] = {}
    for f in snapshot.get("data_quality_flags") or []:
        sev = {"warn": "warning"}.get(f.get("severity"), f.get("severity") or "info")
        by_sev[sev] = by_sev.get(sev, 0) + 1
    xirr = ((snapshot.get("returns") or {}).get("restricted") or {}).get("xirr")
    summary = {
        "kind": "pdl-build-summary@1",
        "as_of": as_of,
        "mode": "replay" if replay else ("record" if record else "live"),
        "inputs": {k: (str(v) if v else None) for k, v in
                   (("trades", trades), ("balance", balance), ("iis_trades", iis_trades),
                    ("prev_snapshot", prev), ("compare_snapshot", compare), ("sector_overrides", overrides))},
        "snapshot_path": str(snap_path),
        "snapshot_sha256": snapshot_hash(snapshot),
        "holdings": len(snapshot.get("holdings") or []),
        "xirr_restricted": xirr,
        "flags_by_severity": by_sev,
        "decisions": [{"code": c, "message_ru": DECISIONS[c]} for c in dict.fromkeys(codes) if c in DECISIONS],
        "attention_flags": [{"code": f.get("code"), "message": f.get("message")}
                            for f in snapshot.get("data_quality_flags") or []
                            if f.get("code") in ATTENTION_FLAGS],
        "checks": check_results,
        "blocked": any(c["level"] == "block" for c in check_results),
        "fallbacks": decisions_made,
        "steps": runner.log,
        "plan_check": ({k: v for k, v in snapshot["plan_check"].items() if k != "diff"}
                       if snapshot.get("plan_check") else None),
        "parity": parity,
        "type_changes": snapshot["type_check"]["changes"],
        "types": {"online": snapshot["type_check"]["online"], "fetched": len(types_fetched),
                  "failed": len(types_failed)},
        "committed": False,
    }

    # ── Шаг 7 / 7б: запись ──
    if opts.commit:
        if replay:
            raise StepError("--commit с --replay запрещён: повтор пакета не пишет в Claude-Memory")
        if not memory:
            raise StepError("--commit требует --memory")
        if summary["blocked"]:
            summary["commit_refused"] = "есть блок-проверки — снапшот не записан"
        else:
            if not opts.working:
                dest, summ = commit_probe(snap_path, snapshots_dir, as_of)
                summary["committed"] = str(dest)
                summary["commit_kind"] = "probe"
                summary["probe_summary"] = str(summ)
            else:
                dest, archived = commit_guarded(snapshot, snap_path, snapshots_dir, as_of, opts.allow_downgrade)
                summary["committed"] = str(dest)
                summary["commit_kind"] = "working"
                summary["archived_previous"] = archived

    _write_json(work / "build-summary.json", summary)
    if summary.get("commit_kind") == "probe":
        sp = Path(summary["probe_summary"])
        sp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(work / "build-summary.json", sp)
    if record:
        shutil.copy2(work / "build-summary.json", record / "script-build-summary.json")
    return summary


# ───────────────────────────── вывод ─────────────────────────────

LEVEL_RU = {"block": "⛔ блок", "warning": "⚠️ предупреждение", "info": "ℹ️ инфо"}


def render(summary: dict) -> str:
    x = summary.get("xirr_restricted")
    lines = [
        f"Снапшот собран: portfolio-{summary['as_of']}.json ({summary['mode']})",
        f"Позиций: {summary['holdings']} | XIRR (restricted): "
        + (f"{x * 100:.2f}%" if isinstance(x, (int, float)) else "n/a")
        + " | флаги: " + (", ".join(f"{k} {v}" for k, v in sorted(summary["flags_by_severity"].items())) or "нет"),
    ]
    fb = summary.get("fallbacks") or {}
    if fb.get("moex_down") or fb.get("cbr_offline"):
        lines.append("Фолбэки: " + ", ".join(n for n, on in (("MOEX недоступен", fb.get("moex_down")),
                                                          ("ЦБ офлайн", fb.get("cbr_offline"))) if on))
    for d in summary["decisions"]:
        lines.append(f"Нужно решение [{d['code']}]: {d['message_ru']}")
    for f in summary.get("attention_flags") or []:
        lines.append(f"Флаг загрузчика [{f['code']}]: {f['message']}")
    pc = summary.get("plan_check")
    if pc and pc.get("source") != "error":
        if pc.get("source") == "plan_primary":
            lines.append("План: главный источник — plan.json")
        lines.append(f"План: {pc.get('plan_file')} от {pc.get('plan_updated_at')}, расхождений {pc.get('n_diff')}"
                     + (" (план из plan.json применён, Numbers не приложен)"
                        if pc.get("source") == "plan_only" and pc.get("applied")
                        else " (Numbers не приложен — сверять не с чем)" if pc.get("source") == "plan_only" else ""))
    pr = summary.get("parity")
    if pr and pr.get("error"):
        lines.append(f"Сверка с балансом: {pr['error']}")
    elif pr:
        lines.append(f"Сверка с балансом ({pr.get('against_date')}{'' if pr.get('same_day') else ', другой день'}): "
                     f"совпало {pr.get('matched')}, в допуске {pr.get('within_tol')}, известных {pr.get('known')}, "
                     f"расходится {pr.get('diverged')}" + (f" — {pr.get('report_path')}" if pr.get("diverged") else ""))
    shown = [c for c in summary["checks"] if c["level"] != "info"]
    if shown:
        lines.append("Проверки:")
        lines += [f"  {LEVEL_RU[c['level']]} [{c['id']}] {c['message_ru']}" for c in shown]
    n_info = sum(1 for c in summary["checks"] if c["level"] == "info")
    if n_info:
        lines.append(f"  ℹ️ ещё {n_info} инфо — в build-summary.json")
    if summary.get("commit_kind") == "probe":
        lines.append(f"Записано в пробную папку: {summary['committed']} (сводка — {summary['probe_summary']}). "
                     "Рабочий снапшот, журнал решений и индекс не тронуты; читатели (советник, стресс, вьюер) берут рабочую "
                     "папку. Сделать рабочим: «сохрани как рабочий» (--commit --working) или «Сохранить» на сайте.")
    elif summary.get("committed"):
        lines.append(f"Записано: {summary['committed']}")
        arc = summary.get("archived_previous") or {}
        if arc.get("archived"):
            lines.append(f"Снапшот за {summary['as_of']} перезаписан; прежняя версия (собрана "
                         f"{arc.get('generated_at')}) — в .versions/; обзоры, вышедшие до "
                         "перезаписи, строились на ней.")
    elif summary.get("commit_refused"):
        lines.append(f"НЕ записано: {summary['commit_refused']}")
    lines.append(f"Сводка: {Path(summary['snapshot_path']).parent / 'build-summary.json'}")
    return "\n".join(lines)


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Сборка снапшота портфеля без LLM (API-1b).")
    ap.add_argument("--trades", help="trades_portfolio_*.xlsx (IntelInvest)")
    ap.add_argument("--balance", help="Общий баланс.numbers или .xlsx")
    ap.add_argument("--iis-trades", help="trades_portfolio_838526*.xlsx (БКС-ИИС-3); нет — последняя из "
                                         "<memory>/Portfolio/inputs/, нет и там — блок из прошлого снапшота")
    ap.add_argument("--iis-dir", action="append", help="доп. папка для поиска выгрузки ИИС-3")
    ap.add_argument("--no-iis-search", action="store_true", help="не искать выгрузку ИИС-3")
    ap.add_argument("--memory", help="корень Claude-Memory (прошлый снапшот, overrides, forecasts, запись)")
    ap.add_argument("--prev-snapshot", help="явно: предыдущий снапшот")
    ap.add_argument("--sector-overrides", help="явно: sector-overrides.yaml")
    ap.add_argument("--plan", help="явно: plan.json (default: {memory}/Portfolio/plan.json, если есть)")
    ap.add_argument("--plan-primary", action="store_true",
                    help="plan.json — главный источник плана при наличии Numbers (Numbers только для сверки); "
                         "default: выключен. Без баланса (сделки) план из plan.json главный всегда")
    ap.add_argument("--parity-against", metavar="PATH",
                    help="снапшот того же дня с балансом для сверки поле за полем (default: "
                         "{memory}/Portfolio/snapshots/portfolio-{as_of}.json, если в нём есть баланс)")
    ap.add_argument("--as-of", help="дата снапшота YYYY-MM-DD (default: сегодня)")
    ap.add_argument("--out", help="рабочая папка (default: временная)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--record", metavar="DIR", help="записать пакет прогона")
    g.add_argument("--replay", metavar="DIR", help="повторить пакет прогона без сети")
    ap.add_argument("--no-moex", action="store_true", help="не ходить в MOEX (фолбэк сразу)")
    ap.add_argument("--types-cache", metavar="PATH",
                    help="справочник типов бумаг (default: {memory}/Portfolio/security-types.json)")
    ap.add_argument("--splits-file", metavar="PATH",
                    help="реестр сплитов (default: {memory}/Portfolio/known-splits.json, если файл есть); "
                         "дополняет встроенный набор")
    ap.add_argument("--cbr-offline", action="store_true", help="курсы ЦБ только из кэша")
    ap.add_argument("--rebaseline-cash", action="store_true", help="принять текущее кэш-расхождение")
    ap.add_argument("--cash-fact", type=float, default=None, metavar="RUB",
                    help="свободные деньги основного портфеля из IntelInvest, ₽ (все валюты в рублях); "
                         "только без баланса — становится фактом кэша")
    ap.add_argument("--cash-fact-iis", type=float, default=None, metavar="RUB",
                    help="свободные деньги ИИС-3, ₽ (только рублёвый кэш); только без баланса — подменяет перенос из прошлого снапшота")
    ap.add_argument("--commit", action="store_true",
                    help="записать снапшот в пробную папку Portfolio/snapshots/auto/ (рабочий, журнал и индекс не трогать)")
    ap.add_argument("--working", action="store_true",
                    help="с --commit: рабочая папка Portfolio/snapshots/, защита от ухудшения")
    ap.add_argument("--allow-downgrade", action="store_true",
                    help="при --commit --working осознанно перезаписать сохранённый снапшот того же дня с балансом или кэшем "
                         "сборкой «только сделки» (прежняя версия уйдёт в .versions/)")
    ap.add_argument("--json", action="store_true", help="вывести build-summary.json вместо текста")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    opts = parse_args(argv)
    try:
        summary = build(opts)
    except StepError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2) if opts.json else render(summary))
    return 2 if summary["blocked"] else 0


if __name__ == "__main__":
    sys.exit(main())
