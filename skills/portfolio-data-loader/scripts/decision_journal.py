#!/usr/bin/env python3
"""Журнал решений AIR-1 (этап 4): вердикты системы и решения по бумаге ↔ действия владельца ↔ B2 ↔ исходы.

План: docs/investment/portfolio/air-1-decision-journal-plan.md §3–§5, §7а; схема данных — schema.md §4.5. Журнал
целиком пересобирается из источников при каждом прогоне — ручного ведения и накопленного состояния нет. Пишет только
сборка (сайт, pf_build.publish_journal → decision_journal_update.py). Ручные входы (`refusals.yaml`, `theses.yaml`,
`incidents.yaml`, пишет save-to-library Workflow P) проверяет валидатор ds_schemas до сборки.

Источники:
  * weekly-reviews/weekly-review-{stock,bond}-*.yaml (+ легаси weekly-review-YYYY-MM-DD.yaml = акции);
  * решения по бумаге Portfolio/decisions/*.json (decision@1) — через decisions_read;
  * определения условий Portfolio/conditions.yaml и годовые архивы conditions-archive-ГГГГ.yaml (conditions@2)
    + состояние conditions-state.json — модулем (а);
  * журнал плана Portfolio/plan-journal.jsonl (ts с поясом; старые строки без пояса — UTC);
  * реестр типов Portfolio/security-types.json — класс бумаги решения;
  * входы shadow_inputs (история плана, дивиденды) и выгрузка сделок (сопоставление);
  * ряды market_series — исходы акций против MCFTR, облигаций — против индекса корзины.

Решения, зафиксированные здесь:
  * Эпизод обзора = подряд идущие обзоры одного типа с тем же тикером и тем же направлением
    (maps.verdict_direction кодлистов: up = «+», down = «−», flat — не эпизод). Метрики попаданий (summary) —
    только по эпизодам обзоров, исход от первого обзора эпизода: один TRIM MDMG в 10 обзорах = одно наблюдение.
  * Эпизод решения (kind: decision) = одно направленное решение по бумаге; окно — от recorded_at до следующего
    решения по той же бумаге, не дальше срока пересмотра (review_by, иначе recorded_at + defaults.review_days) и as_of.
    В summary не входит (своя сводка decisions_summary), вопрос об отказе по нему — только если его не покрывает
    эпизод обзора той же бумаги и направления.
  * Вердикт системы = unconstrained_verdict, если записан, иначе advisor_verdict. Обзор с полем
    revision → revised_post_hoc: правка могла заменить вердикт системы решением владельца.
  * Исполнение: сделка по тому же тикеру/ISIN в окне [дата обзора, следующий обзор того же типа).
  * Без сделки направленный вердикт получает (по порядку):
      deferred_by_condition — на конец окна по бумаге есть действующее условие формата 2 (модуль (а) на срезе
        определений и событий не позже конца окна), созданное решением по этой бумаге (conditions_created[] решения
        или source.decision_id определения; у эпизода решения — именно этим решением), или ждущее владельца;
      owner_decided — в окне (после начала, не позже конца) владелец отметился по бумаге: событие состояния
        owner_mark (любая отметка) или done by: owner по условию этой бумаги, либо строка журнала плана по бумаге
        (stocks.<бумага>.user_status | user_plan, bonds.<ISIN>.*, funds.<тикер>.* — как owner_decided уведомителя);
      ignored — ничего из этого.
  * Вопрос об отказе (§7а): только по ignored без ответа в refusals.yaml — один раз на эпизод, независимо от исхода.
  * Исходы облигаций (AIR-1b): полная доходность бумаги (грязная цена + купоны и амортизации, ISS
    history + bondization) минус индекс корзины: ОФЗ — RGBITR, корп. — RUCBTRNS, флоатеры — RUSFAR,
    CNY — RUCNYTR (обе стороны в CNY). USD/EUR — индекса нет → null + флаг.
  * Коды concordance (followed, contrary, deferred_by_condition, owner_decided, ignored, acted_on_hold, n/a) —
    словарь модуля, кодлиста для них нет.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Кодлисты (`codelists.json`, загрузчик `codelists.py`) — канон в _shared-references/; в упакованном
# .skill — в своей scripts/ (pack.sh кладёт оба файла). Как у constraint_engine: сначала каталог скрипта.
_SHARED = Path(__file__).resolve().parents[3] / "_shared-references"
if _SHARED.is_dir() and str(_SHARED) not in sys.path:
    sys.path.append(str(_SHARED))
import codelists  # noqa: E402
import conditions_merge as cm  # noqa: E402
import decisions_read as dr  # noqa: E402
import ds_schemas as ds  # noqa: E402
import time_msk  # noqa: E402

# Направление вердикта эпизода — maps.verdict_direction (legacy-коды облигаций — со своим направлением до миграции).
_DIRECTION = codelists.map_("verdict_direction")
PLUS = {v for v, d in _DIRECTION.items() if d == "up"}
MINUS = {v for v, d in _DIRECTION.items() if d == "down"}
HORIZONS = {"1m": 30, "3m": 91, "12m": 365}
DIVIDEND_TAX = 0.13
STALE_MACRO_DAYS = 14
B2_BAND_REL = 0.25           # D-2: рукав внутри класса вне ±25% своей доли
REVIEW_DAYS = codelists.defaults()["review_days"]   # срок решения без review_by
DECISION_QUESTION_DAYS = 14  # вопрос по эпизоду решения живёт две недели после конца окна
CONDITIONS_SCHEMA = "conditions@2"
CONDITIONS_ARCHIVE = re.compile(r"^conditions-archive-\d{4}\.yaml$")   # годовой архив определений
PLAN_JOURNAL_REL = "plan-journal.jsonl"

MEMORY_ROOT = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory"
REPO_ROOT = Path(__file__).resolve().parents[3]


def direction(verdict: str | None) -> str | None:
    v = (verdict or "").upper()
    return "+" if v in PLUS else "-" if v in MINUS else None


# ---------------------------------------------------------------- обзоры

def review_kind(path: Path, doc: dict) -> str | None:
    t = (doc.get("type") or "").lower()
    if "bond" in t or "-bond-" in path.name:
        return "bond"
    if "stock" in t or "-stock-" in path.name or re.fullmatch(r"weekly-review-\d{4}-\d{2}-\d{2}\.yaml", path.name):
        return "stock"
    return None


def _iso(x: Any) -> str | None:
    if isinstance(x, (dt.date, dt.datetime)):
        return x.isoformat()[:10]
    if isinstance(x, str) and re.match(r"\d{4}-\d{2}-\d{2}", x):
        return x[:10]
    return None


def macro_as_of(doc: dict) -> str | None:
    mc = doc.get("macro_context")
    if isinstance(mc, dict) and _iso(mc.get("as_of")):
        return _iso(mc.get("as_of"))
    for k in ("macro_input", "macro_source"):
        v = doc.get(k)
        if isinstance(v, str):
            m = re.search(r"(\d{4}-\d{2}-\d{2})", v)
            if m:
                return m.group(1)
    return None


def load_reviews(review_dir: Path) -> list[dict]:
    """[{kind, date, path, doc}] по возрастанию даты; .bak и .md игнорируются."""
    import yaml
    out = []
    for f in sorted(glob.glob(str(review_dir / "weekly-review-*.yaml"))):
        p = Path(f)
        with open(p, encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
        kind = review_kind(p, doc)
        m = re.search(r"(\d{4}-\d{2}-\d{2})", p.name)
        date = _iso(doc.get("review_date")) or (m.group(1) if m else None)
        if kind and date:
            out.append({"kind": kind, "date": date, "path": p, "doc": doc})
    out.sort(key=lambda r: (r["kind"], r["date"], r["path"].name))
    return out


def positions(doc: dict, kind: str) -> list[tuple[str, dict]]:
    ps = doc.get("per_stock" if kind == "stock" else "per_bond") or {}
    if isinstance(ps, dict):
        return [(k, v) for k, v in ps.items() if isinstance(v, dict)]
    return [((x.get("isin") or x.get("ticker")), x) for x in ps if isinstance(x, dict) and (x.get("isin") or x.get("ticker"))]


# ---------------------------------------------------------------- сделки

def trades_index(trades) -> dict[str, list[tuple[dt.date, str, float]]]:
    """тикер → [(дата, buy|sell, руб)] по реальным сделкам; дубль под ключом "name:<название>".

    Зачем имя: обзоры облигаций и снапшот держат ОФЗ по ISIN (RU000A106E90), а выгрузка
    IntelInvest — по биржевому коду (SU26243RMFS4); общее у них только название «ОФЗ 26243»."""
    idx: dict[str, list[tuple[dt.date, str, float]]] = {}
    for t in trades:
        if t.operation not in ("Покупка", "Продажа") or t.ticker.startswith("Деньги"):
            continue
        side = "buy" if t.operation == "Покупка" else "sell"
        row = (t.date, side, abs(t.rub_amount))
        idx.setdefault(t.ticker, []).append(row)
        if t.name:
            idx.setdefault("name:" + t.name.strip(), []).append(row)
    return idx


def owner_action(tidx, key: str, d0: dt.date, d1: dt.date | None, name: str | None = None) -> dict:
    src = tidx.get(key)
    if not src and name:
        src = tidx.get("name:" + name.strip())
    rows = [r for r in (src or []) if d0 <= r[0] and (d1 is None or r[0] < d1)]
    buy = sum(r[2] for r in rows if r[1] == "buy")
    sell = sum(r[2] for r in rows if r[1] == "sell")
    act = "none" if not rows else "bought" if buy > sell else "sold"
    return {"action": act, "buy_rub": round(buy, 2), "sell_rub": round(sell, 2), "trades": len(rows)}


def concordance(dir_: str | None, act: str, no_trade: str = "ignored") -> str:
    """no_trade — код для направленного вердикта без сделки (no_trade_code: deferred_by_condition | owner_decided |
    ignored)."""
    if dir_ is None:
        return "acted_on_hold" if act != "none" else "n/a"
    if act == "none":
        return no_trade
    if (dir_ == "+" and act == "bought") or (dir_ == "-" and act == "sold"):
        return "followed"
    return "contrary"


# ---------------------------------------------------------------- решения, условия, журнал плана

def moment(v: Any) -> dt.datetime | None:
    """Время с поясом → datetime (как _moment уведомителя): `+03:00`, `Z`, без пояса — UTC (старый журнал плана);
    дата без времени — начало дня МСК (нижняя граница окна щедрая: реакция в день обзора считается). Не разобрать — None."""
    if isinstance(v, dt.datetime):
        v = v.isoformat()
    elif isinstance(v, dt.date):
        v = v.isoformat()
    if not isinstance(v, str) or not v.strip():
        return None
    s = v.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            s = time_msk.day_start_iso(s)
        return dt.datetime.fromisoformat(time_msk.to_msk_iso(s))
    except (ValueError, TypeError):
        return None


def review_moment(r: dict) -> dt.datetime | None:
    """Момент обзора: recorded_at, иначе начало дня review_date."""
    return moment((r.get("doc") or {}).get("recorded_at")) or moment(r.get("date"))


def _day_end(d: dt.date | str) -> dt.datetime:
    return dt.datetime.fromisoformat(time_msk.day_end_iso(d))


def owner_context(decisions=None, defs=None, events=None, journal=None, types=None) -> dict:
    """Вход «что решил владелец и система»: решения (decision@1), определения условий (все версии conditions@2),
    события состояния, строки журнала плана, реестр типов {ключ: stock|bond|fund}. Пустой — журнал как раньше."""
    defs = [d for d in defs or [] if isinstance(d, dict) and d.get("id")]
    ids_by_key: dict[str, set] = {}
    for d in defs:
        ids_by_key.setdefault(d.get("key"), set()).add(d["id"])
    return {"decisions": sorted((d for d in decisions or [] if isinstance(d, dict)),
                                key=lambda d: (d.get("key") or "", d.get("recorded_at") or "")),
            "defs": defs, "ids_by_key": ids_by_key,
            "events": [e for e in events or [] if isinstance(e, dict) and e.get("condition_id")],
            "journal": [j for j in journal or [] if isinstance(j, dict)], "types": types or {}}


def _defs_at(ctx: dict, key: str, hi: dt.datetime) -> list[dict]:
    """Версии определений условий бумаги, созданные не позже hi; снятие позже hi — ещё не снято."""
    ids = ctx["ids_by_key"].get(key) or set()
    out = []
    for d in ctx["defs"]:
        if d["id"] not in ids:
            continue
        c = moment(d.get("created_at"))
        if c is not None and c > hi:
            continue
        wd = d.get("withdrawn")
        if isinstance(wd, dict) and (moment(wd.get("at")) or hi) > hi:
            d = {**d, "withdrawn": None}
        out.append(d)
    return out


def deferred_by_condition(ctx: dict, key: str, hi: dt.datetime, decision_ids: set | None = None) -> bool:
    """Есть ли на момент hi по бумаге действующее условие, созданное решением (decision_ids; None — любым решением
    этой бумаги не позже hi) или ждущее владельца. Модуль (а) на срезе: определения и события не позже hi, today = дата hi."""
    defs = _defs_at(ctx, key, hi)
    if not defs:
        return False
    if decision_ids is None:
        decision_ids = {d["id"] for d in ctx["decisions"]
                        if d.get("key") == key and (moment(d.get("recorded_at")) or hi) <= hi}
    linked = {c for d in ctx["decisions"] if d.get("id") in decision_ids for c in d.get("conditions_created") or []}
    linked |= {d["id"] for d in defs if (d.get("source") or {}).get("decision_id") in decision_ids}
    ids = {d["id"] for d in defs}
    events = [e for e in ctx["events"] if e["condition_id"] in ids and (moment(e.get("at")) or hi) <= hi]
    rows = cm.merge(defs, {"events": events}, hi.date().isoformat())
    return any(r["active"] and (r["id"] in linked or r["waits_owner"]) for r in rows)


# ⚠ SYNC: правило R24 «владелец решил сам» — одно в трёх местах: здесь (owner_marked), owner_decided() в
# tools/hosting/notify/notifier.py и ownerDecided() в tools/assets/viewer.js; сторож паритета —
# tools/tests/test_owner_decided_parity.py.
OWNER_MARKS = (cm.MARK_DISMISSED, cm.MARK_DEFERRED)   # отложить — тоже решение владельца (R24)
OWNER_PLAN_FIELDS = ("user_status", "user_plan", "action")  # action — план владельца по облигации; plan_pct и справочные поля — нет


def _plan_path_of(path: str, key: str) -> bool:
    return any(path == f"{s}.{key}.{f}" for s in ("stocks", "bonds", "funds") for f in OWNER_PLAN_FIELDS)


def owner_marked(ctx: dict, key: str, lo: dt.datetime, hi: dt.datetime) -> bool:
    """В (lo, hi] владелец решил сам по бумаге (R24): done by: owner или owner_mark с mark dismissed/deferred по
    условию бумаги (любая версия определения с key = бумага), либо строка журнала плана
    stocks|bonds|funds.<бумага>.user_status|user_plan|action."""
    def between(v):
        m = moment(v)
        return m is not None and lo < m <= hi

    ids = ctx["ids_by_key"].get(key) or set()
    for e in ctx["events"]:
        ev = e.get("event")
        if e["condition_id"] in ids and ((ev == cm.EV_OWNER_MARK and (e.get("data") or {}).get("mark") in OWNER_MARKS)
                                         or (ev == cm.EV_DONE and e.get("by") == "owner")) and between(e.get("at")):
            return True
    return any(isinstance(j.get("path"), str) and _plan_path_of(j["path"], key) and between(j.get("ts"))
               for j in ctx["journal"])


def no_trade_code(ctx: dict | None, key: str, lo: dt.datetime | None, hi: dt.datetime | None,
                  decision_ids: set | None = None) -> str:
    """Код направленного вердикта без сделки: deferred_by_condition → owner_decided → ignored (см. докстринг)."""
    if not ctx or lo is None or hi is None:
        return "ignored"
    if deferred_by_condition(ctx, key, hi, decision_ids):
        return "deferred_by_condition"
    if owner_marked(ctx, key, lo, hi):
        return "owner_decided"
    return "ignored"


def load_owner(root: Path) -> tuple[dict, list[str]]:
    """Решения (decisions_read), условия (conditions@2 + годовые архивы + состояние), журнал плана и реестр типов корня.
    Нечитаемое — флаг, не падение: журнал тогда различает меньше (отложенное условием считается проигнорированным)."""
    flags: list[str] = []
    port = Path(root) / "Portfolio"
    decisions: list[dict] = []
    if (port / "decisions").is_dir():
        decisions, invalid = dr.load(str(root))
        for x in invalid:
            flags.append(f"решение {x['file']} не прошло валидатор: {'; '.join(x['errors'][:2])}")
    else:
        flags.append("нет папки Portfolio/decisions/ — эпизодов решений нет")
    defs: list[dict] = []
    events: list[dict] = []
    # годовые архивы определений (прошлые годы) — вместе с текущими, как condDefsAll() вьюера: условие из архива
    # откладывает эпизод своего (старого) окна
    for apath in sorted(port.glob("conditions-archive-*.yaml")):
        if not CONDITIONS_ARCHIVE.match(apath.name):
            continue
        adoc = cm.load_yaml(str(apath))
        if isinstance(adoc, dict) and adoc.get("schema_version") == CONDITIONS_SCHEMA:
            defs.extend(adoc.get("conditions") or [])
        else:
            sv = adoc.get("schema_version") if isinstance(adoc, dict) else None
            flags.append(f"{apath.name} формата {sv!r}, нужен {CONDITIONS_SCHEMA}: определения архива не учтены")
    cpath = port / "conditions.yaml"
    if cpath.is_file():
        doc = cm.load_yaml(str(cpath))
        if isinstance(doc, dict) and doc.get("schema_version") == CONDITIONS_SCHEMA:
            defs.extend(doc.get("conditions") or [])
            spath = port / "conditions-state.json"
            if spath.is_file():
                events = (json.loads(spath.read_text(encoding="utf-8")) or {}).get("events") or []
        else:
            sv = doc.get("schema_version") if isinstance(doc, dict) else None
            flags.append(f"conditions.yaml формата {sv!r}, нужен {CONDITIONS_SCHEMA}: «отложено условием» не различается")
    journal: list[dict] = []
    jpath = port / PLAN_JOURNAL_REL
    if jpath.is_file():
        for ln in jpath.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if isinstance(row, dict):
                journal.append(row)
    return owner_context(decisions, defs, events, journal, dr.key_types(str(root))), flags


def load_manual(jdir: Path) -> tuple[dict, dict | None, dict | None, list[str]]:
    """Ручные входы журнала: (refusals {episode_id: причина}, theses-документ, incidents-документ, ошибки валидатора).
    Ошибки — до сборки: вызывающий останавливается с понятным текстом (сегодня запись без episode_id роняла скрипт)."""
    errs: list[str] = []
    docs: dict[str, Any] = {}
    for kind in ("refusals", "theses", "incidents"):
        p = Path(jdir) / f"{kind}.yaml"
        if not p.is_file():
            docs[kind] = None
            continue
        try:
            docs[kind] = cm.load_yaml(str(p))
        except Exception as exc:  # noqa: BLE001 — битый YAML = ошибка входа
            errs.append(f"{p.name}: не читается: {exc}")
            docs[kind] = None
            continue
        errs += [f"{p.name}: {e}" for e in ds.validate_journal_manual(kind, docs[kind])]
    refusals = {}
    if not errs:
        refusals = {e["episode_id"]: e.get("reason") or "пропущено"
                    for e in (docs["refusals"] or {}).get("refusals") or []}
    return refusals, docs["theses"], docs["incidents"], errs


def key_class(ctx: dict, key: str) -> str:
    t = dr.key_type(ctx.get("types") or {}, key)
    return t if t in ("stock", "bond", "fund") else "other"


def decision_records(ctx: dict) -> list[dict]:
    """Все решения по бумаге строкой журнала (вместо прежних смен гейтов из файла гейтов)."""
    out = []
    for d in ctx["decisions"]:
        src = d.get("source") or {}
        out.append({"decision_id": d.get("id"), "date": (d.get("recorded_at") or "")[:10],
                    "recorded_at": d.get("recorded_at"), "recorded_at_estimated": bool(d.get("recorded_at_estimated")),
                    "kind": "decision", "position": d.get("key"), "class": key_class(ctx, d.get("key")),
                    "verdict": d.get("verdict"), "direction": direction(d.get("verdict")),
                    "review_by": d.get("review_by"), "target_pct": d.get("target_pct"),
                    "source": {"kind": src.get("kind"), "doc": src.get("doc"), "mode_codes": src.get("mode_codes")},
                    "author": d.get("author"), "conditions_created": d.get("conditions_created") or [],
                    "conditions_resolved": d.get("conditions_resolved") or []})
    return sorted(out, key=lambda x: (x["recorded_at"] or "", x["decision_id"] or ""))


def build_decision_episodes(ctx: dict, tidx, reviews: list[dict], series: dict, divs: dict, as_of: dt.date,
                            refusals: dict) -> list[dict]:
    """Эпизоды направленных решений по бумаге (см. докстринг): окно [recorded_at, следующее решение | срок | as_of]."""
    rows_by_key: dict[str, dict] = {}
    for r in reviews:
        for k, x in positions(r["doc"], r["kind"]):
            rows_by_key[k] = x                              # последняя строка обзора: имя, валюта облигации
    by_key: dict[str, list[dict]] = {}
    for d in ctx["decisions"]:
        by_key.setdefault(d.get("key"), []).append(d)
    eps = []
    for key, lst in by_key.items():
        lst.sort(key=lambda d: d["recorded_at"])
        for i, d in enumerate(lst):
            dir_ = direction(d.get("verdict"))
            if dir_ is None:
                continue
            lo = moment(d["recorded_at"])
            d0 = lo.date()
            rb = dt.date.fromisoformat(d["review_by"]) if d.get("review_by") else d0 + dt.timedelta(days=REVIEW_DAYS)
            ends = [_day_end(rb), _day_end(as_of)]
            if i + 1 < len(lst):
                ends.append(moment(lst[i + 1]["recorded_at"]))
            hi = min(ends)
            closed = hi < _day_end(as_of)
            last = hi.date()
            x = rows_by_key.get(key) or {}
            act = owner_action(tidx, key, d0, last + dt.timedelta(days=1), x.get("name"))
            cls = key_class(ctx, key)
            if cls == "stock":
                outc = stock_outcome(series, divs, key, d0.isoformat(), as_of)
            elif cls == "bond":
                outc = bond_outcome(series, key, x, d0.isoformat(), as_of)
            else:
                outc = {"rel_1m": None, "rel_3m": None, "rel_12m": None}
            eid = f"decision:{d['id']}"
            src = d.get("source") or {}
            eps.append({
                "episode_id": eid, "kind": "decision", "class": cls, "position": key,
                "position_name": x.get("name") or key, "direction": dir_, "verdict": d["verdict"],
                "first_date": d0.isoformat(), "last_date": last.isoformat(), "reviews": 0,
                "window_closed": closed,
                "concordance": concordance(dir_, act["action"], no_trade_code(ctx, key, lo, hi, {d["id"]})),
                "owner_reason": refusals.get(eid), "owner": act,
                "outcome": outc | {"hit_3m": hit(dir_, outc.get("rel_3m"))},
                "revised_post_hoc": False, "decision_ids": [d["id"]], "decision_id": d["id"],
                "review_by": d.get("review_by"), "source": {"kind": src.get("kind"), "doc": src.get("doc")},
                "recorded_at_estimated": bool(d.get("recorded_at_estimated")),
            })
    return eps


def decision_questions(dec_eps: list[dict], review_eps: list[dict], as_of: dt.date) -> list[dict]:
    """Вопросы по эпизодам решений: ignored, без ответа, окно закрыто не раньше DECISION_QUESTION_DAYS назад и нет
    эпизода обзора той же бумаги и направления, пересекающего окно (вопрос задаётся там — один раз)."""
    out = []
    for e in dec_eps:
        if e["concordance"] != "ignored" or e["owner_reason"] is not None or not e["window_closed"]:
            continue
        if any(r["position"] == e["position"] and r["direction"] == e["direction"]
               and r["first_date"] <= e["last_date"] and r["last_date"] >= e["first_date"] for r in review_eps):
            continue
        if (as_of - dt.date.fromisoformat(e["last_date"])).days > DECISION_QUESTION_DAYS:
            e["owner_reason"] = "не спрашивалось (вне окна вопроса)"
            continue
        out.append({"episode_id": e["episode_id"], "class": e["class"], "position": e["position"],
                    "verdict": e["verdict"], "first_date": e["first_date"],
                    "question": f"{e['first_date']} решение {e['verdict']} {e['position_name']} — не сделано "
                                f"до {e['last_date']}. Сознательно? (одна фраза или «пропустить»)"})
    return out


# ---------------------------------------------------------------- B2 и исходы

def b2_action(real_pct: float | None, plan_pct: float | None) -> str | None:
    """Что сделала бы B2 с акцией на дату обзора по правилу полос (доли внутри акций)."""
    if real_pct is None or plan_pct is None:
        return None
    if plan_pct <= 0:
        return "trim" if real_pct > 0.1 else "none"
    if real_pct < plan_pct * (1 - B2_BAND_REL):
        return "add"
    if real_pct > plan_pct * (1 + B2_BAND_REL):
        return "trim"
    return "none"


def plan_pct_from_history(hist: list[dict], ticker: str, d: str) -> float | None:
    best = None
    for p in hist:
        if p["date"] <= d and p.get("stocks"):
            best = p
    if not best:
        return None
    return round(best["stocks"].get(ticker, 0.0) * 100, 4)


def _prev(points, iso):
    v = None
    for d, x in points:
        if d <= iso:
            v = x
        else:
            break
    return v


def stock_outcome(series: dict, divs: dict, ticker: str, d0: str, as_of: dt.date) -> dict:
    """Доходность акции (цена + дивиденды брутто) минус MCFTR, п.п., по горизонтам; null, если не созрело."""
    px = series.get("share:" + ticker) or []
    ix = series.get("index:MCFTR") or []
    out: dict[str, float | None] = {}
    p0, i0 = _prev(px, d0), _prev(ix, d0)
    for h, days in HORIZONS.items():
        d1 = (dt.date.fromisoformat(d0) + dt.timedelta(days=days))
        if d1 > as_of or p0 is None or i0 is None:
            out["rel_" + h] = None
            continue
        p1, i1 = _prev(px, d1.isoformat()), _prev(ix, d1.isoformat())
        if p1 is None or i1 is None:
            out["rel_" + h] = None
            continue
        div = sum(x["dps_gross"] for x in divs.get(ticker, []) if d0 < x["date"] <= d1.isoformat())
        r_s = (p1 + div) / p0 - 1
        out["rel_" + h] = round((r_s - (i1 / i0 - 1)) * 100, 3)
    return out


def bond_benchmark(x: dict) -> str | None:
    """Индекс корзины облигации для исхода (AIR-1b). USD/EUR — индекса нет → None."""
    cur = (x.get("nominal_currency") or "RUB").upper()
    if cur in ("USD", "EUR"):
        return None
    if cur == "CNY":
        return "index:RUCNYTR"                          # индекс и бумага — оба в CNY
    name = (x.get("name") or "").strip()
    floater = bool(x.get("is_floater")) or name.startswith("ОФЗ 29") or x.get("bond_type") == "floater"
    if floater:
        return "rate_index:RUSFAR"                      # флоатер ≈ денежный рынок
    if name.startswith("ОФЗ") or x.get("bond_type") == "ofz":
        return "index:RGBITR"
    return "index:RUCBTRNS"


def _rate_growth(points, d0: str, d1: str) -> float | None:
    """Множитель роста по ставке (% годовых, forward-fill) с d0 по d1, actual/365."""
    if not points:
        return None
    g, d = 1.0, dt.date.fromisoformat(d0)
    end = dt.date.fromisoformat(d1)
    while d < end:
        r = _prev(points, d.isoformat())
        if r is None:
            return None
        g *= 1 + r / 100 / 365
        d += dt.timedelta(days=1)
    return g


def bond_outcome(series: dict, key: str, x: dict, d0: str, as_of: dt.date) -> dict:
    """Полная доходность облигации (грязная цена + купоны и амортизации) минус индекс корзины, п.п."""
    bench = bond_benchmark(x)
    px = series.get("bond:" + key) or []
    cfs = series.get("bond_cf:" + key) or []
    mat = _iso(x.get("maturity_date"))
    out: dict[str, Any] = {"benchmark": bench}
    p0 = _prev(px, d0)
    for h, days in HORIZONS.items():
        d1 = (dt.date.fromisoformat(d0) + dt.timedelta(days=days)).isoformat()
        out["rel_" + h] = None
        if bench is None or p0 is None or dt.date.fromisoformat(d1) > as_of:
            continue
        p1 = 0.0 if (mat and mat <= d1) else _prev(px, d1)   # погашена: номинал пришёл амортизацией
        if p1 is None:
            continue
        cf = sum(v for d, v in cfs if d0 < d <= d1)
        r_b = (p1 + cf) / p0 - 1
        if bench.startswith("rate_index:"):
            g = _rate_growth(series.get(bench) or [], d0, d1)
            r_i = None if g is None else g - 1
        else:
            pts = series.get(bench) or []
            i0, i1 = _prev(pts, d0), _prev(pts, d1)
            r_i = None if i0 is None or i1 is None else i1 / i0 - 1
        if r_i is not None:
            out["rel_" + h] = round((r_b - r_i) * 100, 3)
    return out


def bond_series_specs(reviews: list[dict]) -> list[tuple[str, str]]:
    """Ряды для исходов облигаций: цена и выплаты по каждому ISIN + индексы корзин."""
    keys = sorted({k for r in reviews if r["kind"] == "bond" for k, _ in positions(r["doc"], "bond")})
    return ([("index", "RGBITR"), ("index", "RUCBTRNS"), ("index", "RUCNYTR"), ("rate_index", "RUSFAR")]
            + [("bond", k) for k in keys] + [("bond_cf", k) for k in keys])


def series_specs(reviews: list[dict], owner: dict | None = None) -> list[tuple[str, str]]:
    """Все ряды журнала: MCFTR, акции обзоров и решений, облигации обзоров и решений с индексами корзин."""
    ctx = owner or {}
    stocks = {k for r in reviews if r["kind"] == "stock" for k, _ in positions(r["doc"], "stock")}
    bonds = {k for r in reviews if r["kind"] == "bond" for k, _ in positions(r["doc"], "bond")}
    for d in ctx.get("decisions") or []:
        if direction(d.get("verdict")) is None:
            continue
        c = key_class(ctx, d.get("key")) if "types" in ctx else None
        (stocks if c == "stock" else bonds if c == "bond" else set()).add(d.get("key"))
    out = [("index", "MCFTR")] + [("share", t) for t in sorted(stocks)]
    out += [("index", "RGBITR"), ("index", "RUCBTRNS"), ("index", "RUCNYTR"), ("rate_index", "RUSFAR")]
    out += [("bond", k) for k in sorted(bonds)] + [("bond_cf", k) for k in sorted(bonds)]
    return out


def hit(dir_: str | None, rel: float | None) -> bool | None:
    if dir_ is None or rel is None:
        return None
    return rel > 0 if dir_ == "+" else rel < 0


# ---------------------------------------------------------------- сборка

def build_records(reviews: list[dict], tidx, hist: list[dict], series: dict, divs: dict,
                  as_of: dt.date, owner: dict | None = None) -> tuple[list[dict], list[str]]:
    """Записи вердикт × позиция × обзор. owner (owner_context) — различение «без сделки» (no_trade_code);
    окно записи — (момент обзора, момент следующего обзора того же типа | конец дня as_of]."""
    flags: list[str] = []
    recs: list[dict] = []
    by_kind: dict[str, list[dict]] = {}
    for r in reviews:
        by_kind.setdefault(r["kind"], []).append(r)
    fx_no_bench: set[str] = set()
    for kind, lst in by_kind.items():
        for i, r in enumerate(lst):
            doc, d = r["doc"], r["date"]
            nxt = dt.date.fromisoformat(lst[i + 1]["date"]) if i + 1 < len(lst) else None
            lo = review_moment(r)
            hi = review_moment(lst[i + 1]) if i + 1 < len(lst) else _day_end(as_of)
            mac = macro_as_of(doc)
            stale = (dt.date.fromisoformat(d) - dt.date.fromisoformat(mac)).days if mac else None
            revised = bool(doc.get("revision"))
            high_data = any((c.get("severity") == "HIGH" and re.search(r"расхожд|баз[аы]|устар", c.get("message") or "", re.I))
                            for c in (doc.get("caveats") or []) if isinstance(c, dict))
            producer = str(doc.get("producer") or "")
            pos = positions(doc, kind)
            if not pos:
                flags.append(f"{r['path'].name}: нет позиций")
            for key, x in pos:
                sys_verdict = x.get("unconstrained_verdict") or x.get("advisor_verdict")
                dir_ = direction(sys_verdict)
                act = owner_action(tidx, key, dt.date.fromisoformat(d), nxt, x.get("name"))
                real = x.get("weight_real_pct") if kind == "stock" else None
                plan = (x.get("weight_user_planned_pct") if x.get("weight_user_planned_pct") is not None
                        else plan_pct_from_history(hist, key, d)) if kind == "stock" else None
                if kind == "stock":
                    outc = stock_outcome(series, divs, key, d, as_of)
                else:
                    outc = bond_outcome(series, key, x, d, as_of)
                    if outc["benchmark"] is None:
                        fx_no_bench.add(x.get("name") or key)
                h3 = hit(dir_, outc.get("rel_3m"))
                err = None
                if high_data or (stale is not None and stale > STALE_MACRO_DAYS):
                    err = "data"
                elif h3 is False:
                    err = "forecast"
                recs.append({
                    "decision_id": f"{r['path'].stem}/{key}",
                    "date": d, "kind": "verdict", "class": kind, "position": key,
                    "position_name": x.get("name") or key,
                    "source": r["path"].name, "revised_post_hoc": revised,
                    "system": {
                        "verdict": sys_verdict, "verdict_published": x.get("advisor_verdict"),
                        "direction": dir_, "confidence": x.get("advisor_verdict_confidence"),
                        "p_outperform_3m": x.get("p_outperform_3m"),
                        "model": producer.split(" ")[0] or None,
                        "advisor_version": doc.get("advisor_version"),
                    },
                    "inputs": {"snapshot_date": _iso(doc.get("snapshot_date")), "macro_as_of": mac,
                               "staleness_days": stale},
                    "owner": act | {"concordance": concordance(
                        dir_, act["action"],
                        no_trade_code(owner, key, lo, hi) if dir_ and act["action"] == "none" else "ignored")},
                    "window": [lo.isoformat() if lo else None, hi.isoformat() if hi else None],
                    "b2": {"action": b2_action(real, plan), "real_pct": real, "plan_pct": plan},
                    "outcome": outc | {"hit_3m": h3},
                    "error_category": err,
                })
    if fx_no_bench:
        flags.append(f"исходы USD/EUR-облигаций не считаются — нет индекса корзины (бумаг: {len(fx_no_bench)})")
    return recs, flags


def build_episodes(recs: list[dict], reviews: list[dict], refusals: dict, owner: dict | None = None) -> list[dict]:
    """Эпизоды направленных вердиктов обзоров (см. докстринг). Без сделки — no_trade_code на окне эпизода
    (от момента первого обзора до конца окна последнего)."""
    order: dict[str, list[str]] = {}
    for r in reviews:
        order.setdefault(r["kind"], [])
        if r["date"] not in order[r["kind"]]:
            order[r["kind"]].append(r["date"])
    pos_idx = {k: {d: i for i, d in enumerate(v)} for k, v in order.items()}
    by_pos: dict[tuple[str, str], list[dict]] = {}
    for x in recs:
        by_pos.setdefault((x["class"], x["position"]), []).append(x)
    eps = []
    for (cls, key), lst in by_pos.items():
        lst.sort(key=lambda x: x["date"])
        cur: list[dict] = []

        def close():
            if not cur:
                return
            first = cur[0]
            eid = f"{cls}:{key}:{first['date']}:{first['system']['direction']}"
            acts = [c["owner"]["concordance"] for c in cur]
            if "followed" in acts:
                conc = "followed"
            elif "contrary" in acts:
                conc = "contrary"
            else:
                w0, w1 = (first.get("window") or [None, None]), (cur[-1].get("window") or [None, None])
                conc = no_trade_code(owner, key, moment(w0[0]), moment(w1[1]))
            ref = refusals.get(eid)
            eps.append({
                "episode_id": eid, "kind": "review", "class": cls, "position": key, "position_name": first["position_name"],
                "direction": first["system"]["direction"], "verdict": first["system"]["verdict"],
                "first_date": first["date"], "last_date": cur[-1]["date"], "reviews": len(cur),
                "concordance": conc, "owner_reason": ref,
                "outcome": first["outcome"],
                "revised_post_hoc": any(c["revised_post_hoc"] for c in cur),
                "decision_ids": [c["decision_id"] for c in cur],
            })
            cur.clear()

        prev_i = None
        for x in lst:
            d_ = x["system"]["direction"]
            i = pos_idx[cls][x["date"]]
            if d_ is None:
                close()
            elif cur and (d_ != cur[-1]["system"]["direction"] or prev_i is None or i != prev_i + 1):
                close()
                cur.append(x)
            else:
                cur.append(x)
            prev_i = i
        close()
    eps.sort(key=lambda e: (e["first_date"], e["episode_id"]))
    return eps


QUESTION_WINDOW_REVIEWS = 2   # вопрос живёт два обзора своего типа, потом — «не спрашивалось»


def pending_questions(eps: list[dict], review_dates_by_kind: dict[str, list[str]]) -> list[dict]:
    """§7а: неисполненные эпизоды без ответа — один раз на эпизод, пока память свежа.
    Эпизод из самого свежего обзора ещё не созрел (окно исполнения не закрыто); эпизоды
    старше QUESTION_WINDOW_REVIEWS обзоров не спрашиваются — причину уже не вспомнить, а
    бэклог из десятков вопросов — ровно то «напоминание 5 раз», от которого владелец отказался
    (первый прогон 2026-10-07 дал бы 64 вопроса с мая)."""
    out = []
    for e in eps:
        if e["concordance"] != "ignored" or e["owner_reason"] is not None:
            continue
        dates = review_dates_by_kind.get(e["class"], [])
        if not dates or e["first_date"] >= dates[-1]:
            continue
        window = dates[-1 - QUESTION_WINDOW_REVIEWS:-1]
        if e["first_date"] not in window:
            e["owner_reason"] = "не спрашивалось (вне окна вопроса)"
            continue
        out.append({"episode_id": e["episode_id"], "class": e["class"], "position": e["position"],
                    "verdict": e["verdict"], "first_date": e["first_date"],
                    "question": f"{e['first_date']} предлагал {e['verdict']} {e['position_name']} — не сделано. "
                                f"Сознательно? (одна фраза или «пропустить»)"})
    return out


def plan_change_records(hist: list[dict]) -> list[dict]:
    out = []
    for a, b in zip(hist, hist[1:]):
        sa, sb = a.get("stocks") or {}, b.get("stocks") or {}
        ch = {t: [round(sa.get(t, 0) * 100, 2), round(sb.get(t, 0) * 100, 2)]
              for t in sorted(set(sa) | set(sb)) if abs(sa.get(t, 0) - sb.get(t, 0)) > 1e-6}
        bch = None
        if a.get("bond_buckets") != b.get("bond_buckets"):
            bch = {"from": a.get("bond_buckets"), "to": b.get("bond_buckets")}
        if ch or bch or a.get("classes") != b.get("classes"):
            out.append({"decision_id": f"plan/{b['date']}", "date": b["date"], "kind": "plan_change",
                        "stocks_pct_within_class": ch or None, "bond_buckets": bch,
                        "classes": b.get("classes") if a.get("classes") != b.get("classes") else None})
    return out


def incidents_monthly(reviews: list[dict], recs: list[dict], since: str, incidents: dict | None = None) -> dict:
    """Источники D-5: флаги данных в обзорах, коммиты fix: в advisor/data-loader, ретро-документы (авто) и записи
    владельца `incidents.yaml` (manual: записи без `corrects` — уточнение прежней записи новым инцидентом не считается)."""
    months: dict[str, dict[str, int]] = {}

    def bump(m: str, k: str, n: int = 1):
        months.setdefault(m, {"data_flags": 0, "fix_commits": 0, "retro_docs": 0, "manual": 0})[k] += n

    for x in (incidents or {}).get("incidents") or []:
        d = _iso(x.get("date"))
        if d and d >= since[:10] and not x.get("corrects"):
            bump(d[:7], "manual")

    for r in reviews:
        if r["date"] >= since:
            n = sum(1 for x in recs if x["source"] == r["path"].name and x["error_category"] == "data")
            if n:
                bump(r["date"][:7], "data_flags", 1)        # обзор с проблемой данных — одно событие
    try:
        log = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "log", f"--since={since}", "--format=%ad %s", "--date=short", "--",
             "skills/ru-portfolio-advisor", "skills/portfolio-data-loader"],
            capture_output=True, text=True, timeout=30).stdout
        for line in log.splitlines():
            d, _, subj = line.partition(" ")
            if subj.lower().startswith("fix"):
                bump(d[:7], "fix_commits")
    except Exception:  # noqa: BLE001
        pass
    for f in glob.glob(str(REPO_ROOT / "docs/investment/**/*retro*.md"), recursive=True):
        m = re.search(r"(\d{4}-\d{2})-\d{2}", Path(f).name)
        if m and m.group(1) >= since[:7]:
            bump(m.group(1), "retro_docs")
    return dict(sorted(months.items()))


def summarize(eps: list[dict], recs: list[dict]) -> dict:
    out: dict[str, Any] = {}
    for cls in ("stock", "bond"):
        e = [x for x in eps if x["class"] == cls and x.get("kind", "review") == "review"]
        mat = [x for x in e if x["outcome"].get("hit_3m") is not None]
        clean = [x for x in mat if not x["revised_post_hoc"]]
        conc: dict[str, int] = {}
        for x in e:
            conc[x["concordance"]] = conc.get(x["concordance"], 0) + 1
        r = [x for x in recs if x["class"] == cls]
        out[cls] = {
            "verdicts": len(r),
            "hold_share": round(sum(1 for x in r if x["system"]["direction"] is None) / len(r), 3) if r else None,
            "episodes": len(e), "matured_3m": len(mat),
            "hits_3m": sum(1 for x in mat if x["outcome"]["hit_3m"]),
            "matured_3m_clean": len(clean), "hits_3m_clean": sum(1 for x in clean if x["outcome"]["hit_3m"]),
            "concordance": conc,
        }
    return out


def summarize_decisions(dec_eps: list[dict], decs: list[dict]) -> dict:
    conc: dict[str, int] = {}
    for x in dec_eps:
        conc[x["concordance"]] = conc.get(x["concordance"], 0) + 1
    return {"decisions": len(decs), "directed": sum(1 for d in decs if d["direction"]), "episodes": len(dec_eps),
            "closed": sum(1 for x in dec_eps if x["window_closed"]), "concordance": conc}


def build(reviews, trades, inputs: dict, series: dict, owner: dict | None, refusals: dict,
          as_of: dt.date, incidents: dict | None = None) -> dict:
    """owner — owner_context (решения, условия, журнал плана, типы); пустой/None — без эпизодов решений,
    «без сделки» = ignored, как до шага 13."""
    hist, divs = inputs["plan_history"], inputs["dividends"]
    tidx = trades_index(trades)
    ctx = owner if owner and "ids_by_key" in owner else owner_context(**(owner or {}))
    recs, flags = build_records(reviews, tidx, hist, series, divs, as_of, ctx)
    eps = build_episodes(recs, reviews, refusals, ctx)
    dec_eps = build_decision_episodes(ctx, tidx, reviews, series, divs, as_of, refusals)
    latest: dict[str, str] = {}
    dates_by_kind: dict[str, list[str]] = {}
    for r in reviews:
        latest[r["kind"]] = max(latest.get(r["kind"], ""), r["date"])
        if r["date"] not in dates_by_kind.setdefault(r["kind"], []):
            dates_by_kind[r["kind"]].append(r["date"])
    for v in dates_by_kind.values():
        v.sort()
    since = min((r["date"] for r in reviews), default=as_of.isoformat())
    last_trade = max((t.date for t in trades), default=None)
    if last_trade and reviews and last_trade.isoformat() < max(latest.values()):
        flags.append(f"выгрузка сделок кончается {last_trade}: исполнение после этой даты не видно — приложи свежую")
    decs = decision_records(ctx)
    questions = pending_questions(eps, dates_by_kind) + decision_questions(dec_eps, eps, as_of)
    all_eps = sorted(eps + dec_eps, key=lambda e: (e["first_date"], e["episode_id"]))
    return {
        "schema": "decision-journal@1",
        "as_of": as_of.isoformat(),
        "summary": summarize(eps, recs),
        "decisions_summary": summarize_decisions(dec_eps, decs),
        "pending_questions": questions,
        "episodes": all_eps,
        "records": recs,
        "plan_changes": plan_change_records(hist),
        "decisions": decs,
        "incidents_monthly": incidents_monthly(reviews, recs, since, incidents),
        "flags": flags,
    }


def main(argv: list[str] | None = None) -> int:
    import market_series as ms
    from portfolio_returns import apply_corrections, convert_trades_to_rub, parse_trades
    from shadow_inputs import newest_trades_export

    ap = argparse.ArgumentParser(description="Журнал решений AIR-1.")
    ap.add_argument("--inputs", type=Path, required=True, help="JSON из shadow_inputs.py --out")
    ap.add_argument("--trades", type=Path)
    ap.add_argument("--memory", type=Path, default=MEMORY_ROOT)
    ap.add_argument("--as-of", type=dt.date.fromisoformat, default=dt.date.today())
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)

    port = a.memory / "Portfolio"
    refusals, _theses, incidents, errs = load_manual(port / "decision-journal")
    if errs:
        print("Ручные входы журнала не прошли валидатор (save-to-library Workflow P):\n  " + "\n  ".join(errs),
              file=sys.stderr)
        return 2
    reviews = load_reviews(port / "weekly-reviews")
    owner, oflags = load_owner(a.memory)
    inputs = json.loads(a.inputs.read_text(encoding="utf-8"))
    tpath = a.trades or newest_trades_export()
    trades = convert_trades_to_rub(apply_corrections(parse_trades(str(tpath)))[0], cbr_offline=a.offline)

    since = dt.date.fromisoformat(min(r["date"] for r in reviews)) - dt.timedelta(days=10)
    got = ms.get_many(series_specs(reviews, owner), since, a.as_of, offline=a.offline)
    series = {k: s.points for k, s in got.items()}
    res = build(reviews, trades, inputs, series, owner, refusals, a.as_of, incidents)
    res["flags"] = [f"ряд пуст: {k}" for k, s in got.items() if not s.points] + oflags + res["flags"]
    if a.out:
        a.out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"summary": res["summary"], "pending_questions": res["pending_questions"][:10],
                      "pending_total": len(res["pending_questions"]),
                      "plan_changes": len(res["plan_changes"]), "decisions": res["decisions_summary"],
                      "incidents_monthly": res["incidents_monthly"], "flags": res["flags"]},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
