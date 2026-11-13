#!/usr/bin/env python3
"""
coverage_report.py

Детерминированные расчёты для macro-forecast-chain:
- Шаг 2.3: age × horizon-coverage → итоговый статус (worst-of-two)
- Шаг 3: Coverage Score, ranking блокирующих проблем
- Шаг 3.5: автоматическая рекомендация режима (FULL / QUICK-REFRESH / PARTIAL)
- Шаг 6: consistency check по правилам пар факторов и тройных комбинаций

LLM делает: чтение прогнозов через transport, парсинг YAML, формирование
текстового Coverage Report. Все статусы и рекомендации — этот скрипт.

Двухслойная архитектура (events-yaml-spec.md §5):
  Источник данных для payload зависит от Layer:
    - Layer 1 marginal: forecast.central_estimate из forecast YAML →
      агрегируется в macro-chain/macro-marginal-{date}.yaml
    - Layer 2 conditional: by_scenario из conditional_on_scenarios →
      агрегируется в macro-chain/macro-scenarios-{date}.yaml
  Скрипт принимает payload в одинаковом формате (factors[]) — LLM
  упаковывает данные из нужного source независимо от Layer.

RECALIBRATE-mode (D7 lazy aggregation): payload может содержать
  `mode: "RECALIBRATE"` — coverage check пропускается (lazy update),
  возвращается mode_recommendation = "RECALIBRATE".

Пробой по монитору (`--monitor-report`): прогноз, у которого в последнем отчёте монитора стоит
алерт `category: factor_breach`, — STALE независимо от даты, причина «пробой по монитору от <дата
отчёта>». Источник — сам отчёт (`monitor-reports/monitor-report-*.yaml`, поле `alerts[]`), файла
флагов нет. Вход — папка `monitor-reports/` (последний полный отчёт + частичные новее него, как во
вьюере) или один файл отчёта. Фактор сверяется по `forecast_file` (путь прогноза, из которого взят
фактор) с `target_file` алерта: пробой по старому файлу темы при новом прогнозе не действует.

Расхождение со спотом (`--spot`): центр ближайшего неистёкшего level-горизонта (`fca_stats[h].l1_weighted`,
при пустом — `l1_unweighted`) дальше от спота последнего макроснимка, чем порог фактора
(`DEFAULT_SPOT_GAP_THRESHOLDS`, переопределение `spot_gap_overrides`), — STALE независимо от даты,
`spot_check.status: stale_vs_spot`. Спот — папка `macro-snapshots/` (самый свежий из `ru-*.md` скилла и
`auto/ru-*.json` сайта, при равной дате JSON) или один файл. `fca_stats` — из входа фактора или из файла
`forecast_file` (корень `--root`). Фактор без спота в панели, событийный прогноз — `status: n/a` с причиной.

Матрица сценариев (`--root`, поле `source_matrix` фактора или `scenario_matrix` входа): прогноз, чьи
значения по сценариям построены на матрице, заменённой новой (`superseded_by` / `status: superseded`
в файле матрицы, либо имя матрицы прогноза не совпадает с `scenario_matrix`), — STALE независимо
от даты, `matrix_check.status: replaced`; режим всегда FULL (RECALIBRATE и сборка «как есть» значения
по сценариям не обновляют). Матрица прогноза — `source_matrix` фактора или
`conditional_on_scenarios.source_matrix` файла `forecast_file`; не нашлась — `unchecked`.

CLI:
    cat input.json | python3 coverage_report.py --pretty
    python3 coverage_report.py --input run.json --output plan.json
    python3 coverage_report.py --input run.json --monitor-report Claude-Memory/monitor-reports
    python3 coverage_report.py --input run.json --spot Claude-Memory/macro-snapshots --root Claude-Memory

Без внешних зависимостей; `--monitor-report` требует PyYAML.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from typing import Any

# Пороги по фактору из staleness-config.md.
DEFAULT_STALENESS_THRESHOLDS = {
    "cbr_rate": 45,
    "inflation_ru": 45,
    "usdrub": 45,
    "cnyrub": 45,
    "brent": 45,
    "urals_discount": 60,
    "xauusd": 60,
    "budget_deficit": 90,
    "sanctions": 90,
    "geopolitics": 90,
}
DEFAULT_SECTOR_THRESHOLD = 90  # для sector_*

DEFAULT_TARGET_HORIZONS = ["2026-12-31", "2027-12-31"]


def parse_date(s: Any) -> date | None:
    if s is None or s == "":
        return None
    if isinstance(s, date):
        return s
    if isinstance(s, datetime):
        return s.date()
    return datetime.strptime(str(s), "%Y-%m-%d").date()


def threshold_for(factor: str, overrides: dict | None = None) -> int:
    """Возвращает порог staleness в днях для конкретного фактора."""
    if overrides and factor in overrides:
        return overrides[factor]
    if factor in DEFAULT_STALENESS_THRESHOLDS:
        return DEFAULT_STALENESS_THRESHOLDS[factor]
    if factor.startswith("sector_"):
        return DEFAULT_SECTOR_THRESHOLD
    return 45  # консервативный дефолт


def age_status(days: int, threshold: int) -> str:
    """Шаг 2.3: FRESH/AGING/STALE/VERY_STALE."""
    if days <= threshold * 0.75:
        return "FRESH"
    if days <= threshold:
        return "AGING"
    if days <= threshold * 2:
        return "STALE"
    return "VERY_STALE"


def horizon_status(horizon_dates: list[str | date], target_horizons: list[date]) -> str:
    """COVERS если max(horizon_dates) >= max(target_horizons), иначе INSUFFICIENT_HORIZON."""
    if not horizon_dates or not target_horizons:
        return "INSUFFICIENT_HORIZON"
    parsed = [parse_date(h) for h in horizon_dates if h is not None]
    parsed = [p for p in parsed if p is not None]
    if not parsed:
        return "INSUFFICIENT_HORIZON"
    max_h = max(parsed)
    max_target = max(target_horizons)
    return "COVERS" if max_h >= max_target else "INSUFFICIENT_HORIZON"


# ---------------------------------------------------------------------------
# Пробой по монитору: алерты factor_breach последнего отчёта монитора
# ---------------------------------------------------------------------------

BREACH_CATEGORY = "factor_breach"  # кодлист alert_kind (_shared-references/codelists.json)
_REPORT_DATE_RE = re.compile(r"monitor-report-(\d{4}-\d{2}-\d{2})")
_PARTIAL_CAVEAT_RE = re.compile(r"запуск по одному файлу|частичн\w+ прогон", re.IGNORECASE)
_TRAILING_DATE_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")


def file_stem(path: Any) -> str:
    """`forecasts/brent-price-2026-09-17.yaml` -> `brent-price-2026-09-17`."""
    base = str(path or "").strip().replace("\\", "/").split("/")[-1]
    for ext in (".yaml", ".yml", ".md"):
        if base.endswith(ext):
            return base[: -len(ext)]
    return base


def file_topic(path: Any) -> str:
    """Тема файла: имя без расширения, префикса `scenario-` и даты в конце (как `_mrTopic` вьюера)."""
    stem = file_stem(path)
    if stem.startswith("scenario-"):
        stem = stem[len("scenario-"):]
    return _TRAILING_DATE_RE.sub("", stem)


def _keys(x: Any) -> set[str]:
    return {file_stem(x), file_topic(x)} if str(x or "").strip() else set()


def _report_date(name: str, doc: dict) -> str:
    m = _REPORT_DATE_RE.search(name)
    if m:
        return m.group(1)
    return str(doc.get("generated_at") or "")[:10]


def _report_ts(doc: dict, name: str) -> datetime:
    raw = doc.get("generated_at")
    if isinstance(raw, datetime):
        ts = raw
    else:
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            ts = datetime.fromisoformat(_report_date(name, doc) or "1970-01-01")
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _report_scope(doc: dict) -> tuple[bool, set[str]]:
    """(частичный ли отчёт, ключи проверенных файлов) — правило schema §8 / `_mrScope` вьюера."""
    caveats = doc.get("caveats") if isinstance(doc.get("caveats"), list) else []
    texts = [str(c.get("message", "") if isinstance(c, dict) else c) for c in caveats]
    cav = next((t for t in texts if _PARTIAL_CAVEAT_RE.search(t)), None)
    scope = str(doc.get("scope") or "").lower()
    if not (scope == "partial" or (not scope and cav)):
        return False, set()
    checked = [c for c in (doc.get("checked") or []) if c] if isinstance(doc.get("checked"), list) else []
    if not checked:
        m = re.search(r"\(([^)]+)\)", cav or "")
        checked = [t.strip() for t in re.split(r"[,;]", m.group(1))] if m else []
        checked += [a.get("target_file") or a.get("target") for a in (doc.get("alerts") or [])
                    if isinstance(a, dict)]
    keys: set[str] = set()
    for c in checked:
        keys |= _keys(c)
    return True, keys


def _load_report(path: str) -> dict:
    import yaml  # PyYAML — только для --monitor-report
    with open(path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: не YAML-словарь")
    return doc


def merged_monitor_alerts(path: str) -> dict:
    """Алерты последнего отчёта монитора одной картиной.

    path — папка `monitor-reports/` или один файл отчёта. Для папки: база — последний полный отчёт
    (по `generated_at`), поверх по порядку частичные новее него; алерты по файлам из `checked`
    частичного заменяются его алертами (schema §8, зеркало `mergeMonitorReports` вьюера).
    Возвращает {"alerts": [... + _report_date, _report_file], "base": имя, "partials": [имена]}."""
    if os.path.isdir(path):
        names = sorted(n for n in os.listdir(path)
                       if n.startswith("monitor-report-") and n.endswith((".yaml", ".yml")))
        recs = [(n, _load_report(os.path.join(path, n))) for n in names]
    else:
        recs = [(os.path.basename(path), _load_report(path))]
    if not recs:
        return {"alerts": [], "base": None, "partials": []}
    recs.sort(key=lambda r: (_report_ts(r[1], r[0]), r[0]))
    scopes = [_report_scope(doc) for _, doc in recs]
    base_i = max((i for i, (partial, _) in enumerate(scopes) if not partial), default=0)

    def mark(alerts, name, doc):
        return [{**a, "_report_date": _report_date(name, doc), "_report_file": name}
                for a in (alerts or []) if isinstance(a, dict)]

    base_name, base_doc = recs[base_i]
    alerts = mark(base_doc.get("alerts"), base_name, base_doc)
    partials = []
    for i in range(base_i + 1, len(recs)):
        partial, keys = scopes[i]
        if not partial:
            continue
        name, doc = recs[i]
        partials.append(name)
        alerts = [a for a in alerts
                  if not (_keys(a.get("target_file")) | _keys(a.get("target"))) & keys]
        alerts += mark(doc.get("alerts"), name, doc)
    return {"alerts": alerts, "base": base_name, "partials": partials}


def breach_alerts(merged: dict) -> list[dict]:
    """Только пробои (`category: factor_breach`) из сведённых алертов."""
    return [a for a in merged.get("alerts") or [] if a.get("category") == BREACH_CATEGORY]


def match_breach(factor: dict, breaches: list[dict]) -> dict | None:
    """Пробой, относящийся к прогнозу фактора, или None.

    Сверка по `forecast_file` фактора: тот же файл, что `target_file` алерта. Алерт без `target_file` —
    по теме (`target`), если прогноз не новее отчёта. Без `forecast_file` у фактора — не сверяется."""
    ff = factor.get("forecast_file")
    if not ff:
        return None
    stem, topic = file_stem(ff), file_topic(ff)
    fdate = parse_date(factor.get("forecast_date"))
    for a in breaches:
        tf = a.get("target_file")
        if tf:
            if file_stem(tf) == stem:
                return a
            continue
        rd = parse_date(a.get("_report_date"))
        if file_topic(a.get("target")) == topic and (fdate is None or rd is None or fdate <= rd):
            return a
    return None


def apply_breach(row: dict, breach: dict) -> dict:
    """Пробой → статус не лучше STALE; причина «пробой по монитору от <дата отчёта>»."""
    reason = f"пробой по монитору от {breach.get('_report_date')}"
    row["monitor_breach"] = {
        "report_date": breach.get("_report_date"),
        "report_file": breach.get("_report_file"),
        "target_file": breach.get("target_file"),
        "severity": breach.get("severity"),
    }
    row["stale_reason"] = reason
    status = row["overall_status"]
    if status in ("✓ FRESH", "✓ AGING"):
        row["overall_status"] = "⚠ STALE"
    elif status == "⚠ FRESH-but-short":
        row["overall_status"] = "⚠ STALE+SHORT"
    row["is_blocking"] = True
    row["caveats"] = [f"MONITOR_BREACH: {reason}"] + list(row.get("caveats") or [])
    return row

# ---------------------------------------------------------------------------
# Расхождение центра прогноза со спотом последнего макроснимка
# ---------------------------------------------------------------------------

# Порог расхождения по фактору (staleness-config.md «Расхождение со спотом»):
# "pct" — |центр − спот| / спот в %, "pp" — |центр − спот| в п.п.
DEFAULT_SPOT_GAP_THRESHOLDS = {
    "brent": {"kind": "pct", "value": 15.0},
    "usdrub": {"kind": "pct", "value": 7.0},
    "cnyrub": {"kind": "pct", "value": 7.0},
    "cbr_rate": {"kind": "pp", "value": 1.5},
    "inflation_ru": {"kind": "pp", "value": 1.5},
}
SPOT_MAX_AGE_DAYS = 10  # спот старше — сигнал считается, с пометкой «спот от <дата>»

# Строка панели macro-ru-watcher → фактор цепочки (по подписи и по ключу JSON).
SPOT_LABELS = {
    "Ключевая ставка ЦБ": "cbr_rate",
    "Инфляция (г/г)": "inflation_ru",
    "USD/RUB": "usdrub",
    "CNY/RUB": "cnyrub",
    "Brent": "brent",
}
SPOT_KEYS = {"cbr_key": "cbr_rate", "infl_yoy": "inflation_ru", "usd_rub": "usdrub",
             "cny_rub": "cnyrub", "brent": "brent"}

_SNAP_NAME_RE = re.compile(r"^ru-(\d{4}-\d{2}-\d{2})\.(md|json)$")
_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
_ISO_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def spot_gap_threshold(factor: str, overrides: dict | None = None) -> dict | None:
    """Порог расхождения со спотом; override — число в единицах порога фактора."""
    base = DEFAULT_SPOT_GAP_THRESHOLDS.get(factor)
    if base is None:
        return None
    if overrides and factor in overrides and overrides[factor] is not None:
        return {"kind": base["kind"], "value": float(overrides[factor])}
    return dict(base)


def parse_spot_number(cell: Any) -> float | None:
    """Первое число ячейки «Текущее»: `$115.46 (ICE…)` → 115.46, `14.00% (на 29.10)` → 14.0."""
    m = _NUM_RE.search(str(cell or "").replace("$", "").replace("−", "-"))
    return float(m.group(0).replace(",", ".")) if m else None


def _spot_from_json(path: str, snap_date: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    snap_date = str(doc.get("date") or snap_date)
    values: dict = {}
    for r in doc.get("rows") or []:
        if not isinstance(r, dict):
            continue
        factor = SPOT_LABELS.get(str(r.get("label") or "").strip()) or SPOT_KEYS.get(r.get("key"))
        if factor is None or r.get("value") is None:
            continue
        m = _ISO_PREFIX_RE.match(str(r.get("as_of") or ""))
        values[factor] = {"value": float(r["value"]), "date": m.group(1) if m else snap_date}
    return {"date": snap_date, "source": path, "values": values}


def _spot_from_md(path: str, snap_date: str) -> dict:
    """Таблица `## Snapshot` среза macro-ru-watcher, колонка «Текущее»."""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    values: dict = {}
    in_sec, col = False, None
    for ln in lines:
        if ln.startswith("## "):
            in_sec = ln.strip() == "## Snapshot"
            col = None
            continue
        if not in_sec or not ln.strip().startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if col is None:
            if "Текущее" in cells:
                col = cells.index("Текущее")
            continue
        if len(cells) <= col or set(cells[0]) <= set("-: "):
            continue
        factor = SPOT_LABELS.get(cells[0])
        num = parse_spot_number(cells[col]) if factor else None
        if num is not None:
            values[factor] = {"value": num, "date": snap_date}
    return {"date": snap_date, "source": path, "values": values}


def load_spot(path: str) -> dict:
    """Спот из последнего макроснимка.

    path — папка `macro-snapshots/` или один файл `ru-<дата>.json|.md`. В папке кандидаты —
    срезы скилла `ru-*.md` и автосрезы сайта `auto/ru-*.json|.md`; берётся самый свежий по дате,
    при равной дате — JSON (машиночитаемый). Возвращает {date, source, values: {фактор: {value, date}}}."""
    if os.path.isdir(path):
        cands = []
        for sub in ("", "auto"):
            d = os.path.join(path, sub) if sub else path
            if not os.path.isdir(d):
                continue
            for n in os.listdir(d):
                m = _SNAP_NAME_RE.match(n)
                if m:
                    cands.append((m.group(1), m.group(2) == "json", os.path.join(d, n)))
        if not cands:
            raise ValueError(f"{path}: нет снимков ru-<дата>.md|.json")
        snap_date, _, file = max(cands)
    else:
        file = path
        m = _SNAP_NAME_RE.match(os.path.basename(path))
        snap_date = m.group(1) if m else ""
    if file.endswith(".json"):
        return _spot_from_json(file, snap_date)
    return _spot_from_md(file, snap_date)


def _resolve_forecast(ff: str, root: str | None) -> str | None:
    cands = [ff]
    if root:
        cands += [os.path.join(root, ff), os.path.join(root, "forecasts", os.path.basename(ff))]
    return next((c for c in cands if c and os.path.isfile(c)), None)


def factor_fca_stats(factor: dict, root: str | None) -> tuple[dict | None, str | None]:
    """fca_stats фактора: из входа или из файла прогноза (`forecast_file`, корень `--root`)."""
    if isinstance(factor.get("fca_stats"), dict):
        return factor["fca_stats"], None
    ff = factor.get("forecast_file")
    if not ff:
        return None, "нет fca_stats во входе и forecast_file"
    path = _resolve_forecast(str(ff), root)
    if path is None:
        return None, f"файл прогноза {ff} не найден"
    import yaml  # PyYAML — только когда fca_stats читается из файла
    with open(path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    stats = doc.get("fca_stats") if isinstance(doc, dict) else None
    if not isinstance(stats, dict):
        return None, "у прогноза нет fca_stats"
    return stats, None


def spot_center(stats: dict, today: date) -> tuple[dict | None, str | None]:
    """Центр ближайшего неистёкшего level-горизонта: l1_weighted, при пустом — l1_unweighted."""
    levels = []
    for h, s in stats.items():
        try:
            hd = parse_date(h)
        except ValueError:
            continue
        if hd is None or hd < today or not isinstance(s, dict) or s.get("kind") != "level":
            continue
        for fld in ("l1_weighted", "l1_unweighted"):
            v = s.get(fld)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                levels.append((hd, float(v), fld))
                break
    if not levels:
        has_level = any(isinstance(s, dict) and s.get("kind") == "level" for s in stats.values())
        return None, ("нет неистёкшего level-горизонта с центром" if has_level
                      else "прогноз событийный (нет level-горизонтов)")
    hd, v, fld = min(levels)
    return {"horizon": hd.isoformat(), "center": v, "center_field": fld}, None


def spot_check(factor: dict, spot: dict, today: date, overrides: dict | None,
               root: str | None) -> dict:
    """spot_check фактора: {spot, spot_date, center, horizon, gap, threshold, status, notes}."""
    name = factor["name"]
    out = {"spot": None, "spot_date": None, "center": None, "horizon": None, "gap": None,
           "threshold": None, "status": "n/a", "notes": []}
    thr = spot_gap_threshold(name, overrides)
    sp = (spot.get("values") or {}).get(name)
    if thr is None:
        out["notes"].append("спота фактора в макропанели нет")
        return out
    if sp is None:
        out["notes"].append(f"в снимке {spot.get('date')} нет значения фактора")
        return out
    out["threshold"] = thr
    out["spot"], out["spot_date"] = sp["value"], sp.get("date") or spot.get("date")
    try:
        stats, why = factor_fca_stats(factor, root)
    except Exception as e:  # OSError, yaml.YAMLError
        stats, why = None, f"прогноз не прочитан: {e}"
    if stats is None:
        out["notes"].append(why)
        return out
    c, why = spot_center(stats, today)
    if c is None:
        out["notes"].append(why)
        return out
    out.update(horizon=c["horizon"], center=c["center"], center_field=c["center_field"])
    if c["center_field"] != "l1_weighted":
        out["notes"].append(f"l1_weighted пуст — центр {c['center_field']}")
    spot_v = out["spot"]
    if thr["kind"] == "pct":
        if spot_v == 0:
            out["notes"].append("спот 0 — относительное расхождение не считается")
            return out
        gap = abs(c["center"] - spot_v) / abs(spot_v) * 100
    else:
        gap = abs(c["center"] - spot_v)
    out["gap"] = round(gap, 2)
    sd = parse_date(str(out["spot_date"])[:10]) if out["spot_date"] else None
    if sd is not None and (today - sd).days > SPOT_MAX_AGE_DAYS:
        out["notes"].append(f"спот от {sd.isoformat()}")
    out["status"] = "stale_vs_spot" if gap > thr["value"] else "ok"
    return out


def _fmt_gap(v: float, kind: str) -> str:
    return f"{v:g} %" if kind == "pct" else f"{v:g} п.п."


def apply_spot_gap(row: dict, sc: dict) -> dict:
    """Расхождение со спотом → статус не лучше STALE; причина «центр <x> против спота <y> (<дата>), …»."""
    kind = sc["threshold"]["kind"]
    reason = (f"центр {sc['center']:g} против спота {sc['spot']:g} ({sc['spot_date']}), "
              f"расхождение {_fmt_gap(sc['gap'], kind)} > {_fmt_gap(sc['threshold']['value'], kind)}")
    row["stale_reason"] = "; ".join(x for x in (row.get("stale_reason"), reason) if x)
    status = row["overall_status"]
    if status in ("✓ FRESH", "✓ AGING"):
        row["overall_status"] = "⚠ STALE"
    elif status == "⚠ FRESH-but-short":
        row["overall_status"] = "⚠ STALE+SHORT"
    row["is_blocking"] = True
    row["caveats"] = [f"STALE_VS_SPOT: {reason}"] + list(row.get("caveats") or [])
    return row



def _stem(x: Any) -> str | None:
    """Имя файла матрицы без папки и расширения (.yaml/.yml/.md)."""
    if not x:
        return None
    b = os.path.basename(str(x).strip())
    for ext in (".yaml", ".yml", ".md"):
        if b.endswith(ext):
            b = b[: -len(ext)]
    return b or None


def _find_matrix_file(ref: str, root: str | None) -> str | None:
    names = [ref] if os.path.splitext(ref)[1] else [ref, ref + ".yaml"]
    cands: list[str] = []
    for n in names:
        if root:
            cands += [os.path.join(root, n), os.path.join(root, "scenarios", os.path.basename(n))]
    return next((c for c in cands if os.path.isfile(c)), None)


def _read_yaml(path: str) -> dict:
    import yaml  # лениво, как в factor_fca_stats
    with open(path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return doc if isinstance(doc, dict) else {}


def matrix_check(factor: dict, root: str | None, active_matrix: str | None = None) -> dict:
    """Матрица прогноза против действующей: ok | replaced | n/a | unchecked (исключений наружу нет)."""
    res: dict = {"source_matrix": None, "status": "unchecked", "active": None, "notes": []}
    try:
        src = factor.get("source_matrix")
        if not src:
            ff = factor.get("forecast_file")
            if not ff:
                res["notes"].append("нет forecast_file — матрица прогноза не сверена")
                return res
            path = _resolve_forecast(str(ff), root)
            if path is None:
                res["notes"].append(f"файл прогноза {ff} не найден")
                return res
            cos = _read_yaml(path).get("conditional_on_scenarios")
            src = cos.get("source_matrix") if isinstance(cos, dict) else None
            if not src:
                res["status"] = "n/a"
                res["notes"].append("прогноз не привязан к матрице")
                return res
        src = str(src)
        res["source_matrix"] = _stem(src)
        active_stem = _stem(active_matrix)
        # цепочка superseded_by
        chain_end: str | None = None
        replaced = False
        found = False
        ref, seen = src, set()
        while ref:
            st = _stem(ref)
            if st in seen:
                res["notes"].append("цикл superseded_by")
                break
            seen.add(st)
            fpath = _find_matrix_file(ref, root)
            if fpath is None:
                if found:
                    chain_end = st
                break
            found = True
            doc = _read_yaml(fpath)
            nxt = doc.get("superseded_by")
            nxt = str(nxt).strip() if nxt else ""
            if nxt:
                replaced = True
                chain_end = _stem(nxt)
                ref = nxt
            else:
                if str(doc.get("status") or "").strip().lower() == "superseded":
                    replaced = True
                    chain_end = None
                    res["notes"].append("матрица помечена superseded без superseded_by")
                else:
                    chain_end = st
                break
        if active_stem and active_stem != res["source_matrix"]:
            res["status"] = "replaced"
            res["active"] = chain_end if (replaced and chain_end) else active_stem
        elif replaced:
            res["status"] = "replaced"
            res["active"] = chain_end
        elif found or active_stem:
            res["status"] = "ok"
            res["active"] = chain_end or active_stem
        else:
            res["notes"].append(f"файл матрицы {src} не найден")
    except Exception as e:  # noqa: BLE001
        res["status"] = "unchecked"
        res["notes"].append(f"матрица не сверена: {e}")
    return res


def apply_matrix_replaced(row: dict, mc: dict) -> dict:
    """Прогноз на заменённой матрице → статус не лучше STALE, блокирует, caveat MATRIX_REPLACED."""
    reason = f"прогноз построен на заменённой матрице {mc['source_matrix']}"
    if mc.get("active"):
        reason += f", действует {mc['active']}"
    row["stale_reason"] = "; ".join(x for x in (row.get("stale_reason"), reason) if x)
    status = row["overall_status"]
    if status in ("✓ FRESH", "✓ AGING"):
        row["overall_status"] = "⚠ STALE"
    elif status == "⚠ FRESH-but-short":
        row["overall_status"] = "⚠ STALE+SHORT"
    row["is_blocking"] = True
    row["caveats"] = [f"MATRIX_REPLACED: {reason} — пересобрать на действующей матрице; "
                      "пересчёт весов (RECALIBRATE) значения по сценариям не обновляет"] \
        + list(row.get("caveats") or [])
    return row


# ---------------------------------------------------------------------------
# Шаг 2.3 — статус фактора
# ---------------------------------------------------------------------------

def evaluate_factor(factor: dict, today: date, target_horizons: list[date],
                    overrides: dict | None) -> dict:
    """
    Возвращает row отчёта для одного фактора.
    factor: {name, needed, forecast_date, horizon_dates, method, confidence,
             schema_version}
    Свежесть — по датам самого прогноза (forecast_date, horizon_dates); файла флагов
    устаревания нет (stale_flags.yaml упразднён, R15), поле `monitor_flag` во входе игнорируется.
    Пробой по монитору накладывает `compute` (apply_breach) поверх этой строки.
    """
    name = factor["name"]
    if not factor.get("needed", True):
        return {
            "factor": name,
            "overall_status": "— NOT NEEDED",
            "age_status": None, "horizon_status": None,
            "is_blocking": False,
            "caveats": [],
        }

    forecast_date = parse_date(factor.get("forecast_date"))
    if forecast_date is None:
        return {
            "factor": name,
            "overall_status": "✗ MISSING",
            "age_status": None, "horizon_status": None,
            "age_days": None,
            "method": None, "confidence": None,
            "max_horizon": None,
            "is_blocking": True,
            "caveats": ["MISSING — прогноз отсутствует"],
        }

    age_days = (today - forecast_date).days
    threshold = threshold_for(name, overrides)
    age = age_status(age_days, threshold)

    h_status = horizon_status(factor.get("horizon_dates") or [], target_horizons)

    method = factor.get("method")
    confidence = factor.get("confidence")
    schema_version = factor.get("schema_version")

    caveats: list[str] = []

    # Backward compatibility: method отсутствует или пустая строка → trakt as manual.
    # Источник правила — SKILL.md §2.2a "Интерпретация confidence по method".
    legacy_no_method = method in (None, "")
    if legacy_no_method:
        method = "manual"
        caveats.append(
            "LEGACY_FORMAT_NO_METHOD: method отсутствует, treat as manual — обновить запись"
        )

    # Worst-of-two.
    if method == "fca" and confidence is None:
        overall = "⚠ BROKEN"
        is_blocking = True
        caveats.append("BROKEN_RECORD: fca-прогноз без confidence — нужен rebuild")
    elif age == "VERY_STALE" and h_status == "INSUFFICIENT_HORIZON":
        overall = "⚠ STALE+SHORT"
        is_blocking = True
        caveats.append("VERY_STALE и недостаточный horizon — rebuild целиком")
    elif age in ("STALE", "VERY_STALE") and h_status == "INSUFFICIENT_HORIZON":
        overall = "⚠ STALE+SHORT"
        is_blocking = True
        caveats.append("STALE и недостаточный horizon — rebuild")
    elif age in ("STALE", "VERY_STALE"):
        overall = "⚠ STALE"
        is_blocking = True
    elif h_status == "INSUFFICIENT_HORIZON":
        overall = "⚠ FRESH-but-short"
        is_blocking = True
        max_h = max(parse_date(h) for h in factor.get("horizon_dates") or []
                     if parse_date(h) is not None)
        max_target = max(target_horizons)
        caveats.append(
            f"INSUFFICIENT_HORIZON: max {max_h}, нужно {max_target} — extend"
        )
    elif age == "AGING":
        overall = "✓ AGING"
        is_blocking = False
    else:
        overall = "✓ FRESH"
        is_blocking = False

    if method == "manual" and confidence is None:
        caveats.append("NO_CONFIDENCE: manually-quoted без FCA-агрегации")
    if schema_version is not None and str(schema_version) != "1":
        caveats.append(f"LEGACY_FORMAT: schema_version={schema_version}, нужна миграция")

    return {
        "factor": name,
        "age_status": age,
        "horizon_status": h_status,
        "overall_status": overall,
        "age_days": age_days,
        "threshold_days": threshold,
        "method": method,
        "confidence": confidence,
        "forecast_date": forecast_date.isoformat(),
        "max_horizon": (
            max(parse_date(h) for h in factor.get("horizon_dates") or []
                if parse_date(h) is not None).isoformat()
            if factor.get("horizon_dates") else None
        ),
        "is_blocking": is_blocking,
        "caveats": caveats,
    }


# ---------------------------------------------------------------------------
# Шаг 3.5 — рекомендация режима
# ---------------------------------------------------------------------------

def recommend_mode(rows: list[dict]) -> dict:
    """Auto-recommendation: PARTIAL / QUICK-REFRESH / FULL."""
    needed = [r for r in rows if r["overall_status"] != "— NOT NEEDED"]
    missing = sum(1 for r in needed if r["overall_status"] == "✗ MISSING")
    stale = sum(1 for r in needed if "STALE" in r["overall_status"]
                or "BROKEN" in r["overall_status"]
                or "FRESH-but-short" in r["overall_status"])
    critical = sum(1 for r in needed if "BROKEN" in r["overall_status"])

    mrep = [r for r in needed if (r.get("matrix_check") or {}).get("status") == "replaced"]
    if mrep:
        act = next(((r["matrix_check"].get("active")) for r in mrep if r["matrix_check"].get("active")), None)
        parts = []
        if missing:
            parts.append(f"{missing} MISSING")
        if critical:
            parts.append(f"{critical} critical")
        reason = (f"матрица сценариев заменена: пересобрать {len(mrep)} прогноз(ов) на действующей матрице "
                  f"{act or 'не определена'}; пересчёт весов (RECALIBRATE) и сборка «как есть» значения "
                  "по сценариям не обновляют")
        if parts:
            reason += "; " + ", ".join(parts)
        return {"mode": "FULL", "reason": reason, "missing": missing, "stale": stale,
                "critical": critical, "matrix_replaced": len(mrep), "recalibrate_applicable": False}

    if missing == 0 and stale == 0:
        mode = "PARTIAL"
        reason = "всё FRESH, можно сразу собрать матрицу"
    elif missing == 0 and 1 <= stale <= 3 and critical == 0:
        mode = "QUICK-REFRESH"
        reason = f"пересобрать {stale} протухших, остальное FRESH"
    else:
        mode = "FULL"
        reason_parts = []
        if missing:
            reason_parts.append(f"{missing} MISSING")
        if stale:
            reason_parts.append(f"{stale} STALE/BROKEN")
        if critical:
            reason_parts.append(f"{critical} critical")
        reason = "существенные пробелы: " + ", ".join(reason_parts)

    return {"mode": mode, "reason": reason,
            "missing": missing, "stale": stale, "critical": critical}


# ---------------------------------------------------------------------------
# Шаг 6 — consistency check
# ---------------------------------------------------------------------------

def _get(scenario: dict, key: str, default: float = 0.0) -> float:
    v = scenario.get(key, default)
    if v is None:
        return default
    return float(v)


def check_consistency_pair(scenario: dict) -> list[dict]:
    """
    Прогон по правилам из consistency-rules.md (пары факторов + тройные).
    Возвращает список нарушений.
    """
    violations = []
    brent = _get(scenario, "brent_pct_change")
    usdrub = _get(scenario, "usdrub_pct_change")
    rate_bps = _get(scenario, "rate_bps_change")
    inflation = _get(scenario, "inflation_ru_pct")
    xauusd = _get(scenario, "xauusd_pct_change")
    budget = _get(scenario, "budget_deficit_gdp_pct")
    sanc_esc = bool(scenario.get("sanctions_escalation", False))
    geopol_esc = bool(scenario.get("geopol_escalation", False))

    # Нефть ↔ Рубль.
    if brent > 20 and usdrub > 10:
        violations.append({
            "rule": "oil_rub_extreme_divergence",
            "severity": "critical",
            "message": "Нефть +20% при слабеющем рубле — требует очень специфического обоснования",
        })
    elif brent > 10 and usdrub > 5:
        violations.append({
            "rule": "oil_rub_divergence",
            "severity": "medium",
            "message": "Нефть↑ + рубль↓ — нетипично. Обычно нефть↑ укрепляет рубль",
        })
    elif brent < -15 and usdrub < -5:
        violations.append({
            "rule": "oil_drop_rub_strength",
            "severity": "medium",
            "message": "Нефть↓ + рубль↑ — нетипично",
        })

    # Ставка ЦБ ↔ Инфляция.
    if rate_bps < -500:
        violations.append({
            "rule": "extreme_rate_cut",
            "severity": "critical",
            "message": "Снижение ставки >500 б.п. — экстремальный сценарий",
        })
    elif rate_bps < -300 and inflation > 9:
        violations.append({
            "rule": "rate_cut_high_inflation",
            "severity": "medium",
            "message": "ЦБ снижает ставку >300 б.п. при инфляции выше 9% — нетипично",
        })
    elif rate_bps > 200 and 0 < inflation < 5:
        violations.append({
            "rule": "rate_hike_low_inflation",
            "severity": "medium",
            "message": "ЦБ повышает ставку при инфляции <5% — нетипично",
        })

    # Ставка ЦБ ↔ USD/RUB.
    if rate_bps < -200 and usdrub > 10:
        violations.append({
            "rule": "rate_cut_weak_rub",
            "severity": "medium",
            "message": "ЦБ снижает ставку при слабеющем рубле — риск ускорения инфляции",
        })

    # Brent ↔ Бюджетный дефицит.
    if brent < -20 and budget < -2:
        violations.append({
            "rule": "oil_drop_deficit_narrowing",
            "severity": "low",
            "message": "Нефть -20% + дефицит бюджета сужается — нетипично",
        })

    # Санкции ↔ Геополитика.
    if not sanc_esc and geopol_esc:
        violations.append({
            "rule": "geopol_without_sanctions",
            "severity": "medium",
            "message": "Геополитическая эскалация без ужесточения санкций — исторически редко",
        })
    elif sanc_esc and not geopol_esc:
        violations.append({
            "rule": "sanctions_without_geopol",
            "severity": "low",
            "message": "Ужесточение санкций без геополитической эскалации — возможно",
        })

    # Золото ↔ Геополитика.
    if xauusd < -10 and geopol_esc:
        violations.append({
            "rule": "gold_drop_geopol_escalation",
            "severity": "low",
            "message": "Золото падает при геополитической эскалации — нетипично для safe-haven",
        })

    # Инфляция ↔ USD/RUB.
    if usdrub > 15 and 0 < inflation < 6:
        violations.append({
            "rule": "weak_rub_low_inflation",
            "severity": "medium",
            "message": "Рубль слабеет >15% при инфляции <6% — нетипично",
        })

    # Тройные комбинации.
    if brent < -20 and usdrub > 20 and inflation > 10:
        violations.append({
            "rule": "stress_2022_pattern",
            "severity": "critical",
            "message": "Нефть -20% + рубль -20% + инфляция >10% — стрессовый сценарий 2022-типа",
        })
    if rate_bps < -300 and usdrub > 10 and inflation > 8:
        violations.append({
            "rule": "triple_contradiction",
            "severity": "critical",
            "message": "ЦБ снижает ставку при слабом рубле и высокой инфляции — крайне нетипично",
        })

    return violations


def check_consistency(scenarios: dict) -> dict:
    """
    Прогон всех сценариев. Возвращает свод + по сценариям.
    """
    by_scenario = {}
    counts = {"critical": 0, "medium": 0, "low": 0}
    for label, sc in scenarios.items():
        v = check_consistency_pair(sc)
        by_scenario[label] = v
        for it in v:
            counts[it["severity"]] = counts.get(it["severity"], 0) + 1
    return {
        "violations_by_scenario": by_scenario,
        "counts": counts,
        "compatible": counts["critical"] == 0,
        "total": sum(counts.values()),
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def compute(payload: dict, monitor: dict | None = None, spot: dict | None = None,
            root: str | None = None) -> dict:
    """monitor — результат `merged_monitor_alerts` (или None: пробой не сверяется);
    spot — результат `load_spot` или `payload["spot"]` (нет обоих — расхождение не сверяется);
    root — корень Claude-Memory для чтения `fca_stats` из `forecast_file`."""
    # RECALIBRATE-mode (D7): lazy update, coverage check пропускается.
    if payload.get("mode") == "RECALIBRATE":
        return {
            "today": (parse_date(payload.get("today")) or date.today()).isoformat(),
            "rows": [],
            "summary": {
                "needed_total": 0,
                "ready_for_stress_test": True,
                "blocking_issues": [],
                "coverage_score": "N/A (RECALIBRATE)",
                "note": "RECALIBRATE-mode: coverage check skipped (D7 lazy aggregation)",
            },
            "mode_recommendation": {
                "recommended_mode": "RECALIBRATE",
                "rationale": "weight-only update; no FCA recomputation needed",
            },
        }

    today = parse_date(payload.get("today")) or date.today()
    target_horizons_raw = payload.get("chain_target_horizons") or DEFAULT_TARGET_HORIZONS
    target_horizons = [parse_date(h) for h in target_horizons_raw]
    target_horizons = [h for h in target_horizons if h is not None]

    overrides = payload.get("staleness_overrides") or {}

    factors = payload.get("factors") or []
    rows = [evaluate_factor(f, today, target_horizons, overrides) for f in factors]

    monitor_out = None
    if monitor is not None:
        breaches = breach_alerts(monitor)
        used: set[int] = set()
        for f, row in zip(factors, rows):
            if row["overall_status"] in ("— NOT NEEDED", "✗ MISSING"):
                continue
            b = match_breach(f, breaches)
            if b is not None:
                used.add(id(b))
                apply_breach(row, b)
        monitor_out = {
            "base_report": monitor.get("base"),
            "partial_reports": monitor.get("partials") or [],
            "breaches": len(breaches),
            "unmatched_breaches": [
                {"target": b.get("target"), "target_file": b.get("target_file"),
                 "report_date": b.get("_report_date")}
                for b in breaches if id(b) not in used
            ],
            "factors_without_forecast_file": [
                f.get("name") for f, row in zip(factors, rows)
                if not f.get("forecast_file")
                and row["overall_status"] not in ("— NOT NEEDED", "✗ MISSING")
            ],
        }

    if spot is None and isinstance(payload.get("spot"), dict):
        spot = payload["spot"]
    spot_out = None
    if spot is not None:
        gap_overrides = payload.get("spot_gap_overrides") or {}
        for f, row in zip(factors, rows):
            if row["overall_status"] in ("— NOT NEEDED", "✗ MISSING"):
                continue
            sc = spot_check(f, spot, today, gap_overrides, root)
            row["spot_check"] = sc
            if sc["status"] == "stale_vs_spot":
                apply_spot_gap(row, sc)
        spot_out = {"source": spot.get("source"), "date": spot.get("date")}

    matrix_out = None
    if root is not None or payload.get("scenario_matrix") or any(f.get("source_matrix") for f in factors):
        active_in = payload.get("scenario_matrix")
        active_in = active_in if isinstance(active_in, str) else None
        replaced_f, unchecked_f, actives = [], [], []
        for f, row in zip(factors, rows):
            if row["overall_status"] in ("— NOT NEEDED", "✗ MISSING"):
                continue
            mc = matrix_check(f, root, active_in)
            if mc["status"] != "n/a":
                row["matrix_check"] = mc
            if mc["status"] == "replaced":
                apply_matrix_replaced(row, mc)
                replaced_f.append(row["factor"])
            elif mc["status"] == "unchecked":
                unchecked_f.append(row["factor"])
            if mc.get("active"):
                actives.append(mc["active"])
        matrix_out = {"active": (_stem(active_in) or (actives[-1] if actives else None)),
                      "replaced": replaced_f, "unchecked": unchecked_f}

    needed = [r for r in rows if r["overall_status"] != "— NOT NEEDED"]
    fresh = sum(1 for r in needed if r["overall_status"].startswith("✓ FRESH"))
    aging = sum(1 for r in needed if r["overall_status"] == "✓ AGING")
    stale = sum(1 for r in needed if "STALE" in r["overall_status"])
    missing = sum(1 for r in needed if r["overall_status"] == "✗ MISSING")
    broken = sum(1 for r in needed if "BROKEN" in r["overall_status"])
    insufficient = sum(1 for r in needed if "FRESH-but-short" in r["overall_status"])

    blocking_issues = [
        f'{r["factor"]}: {", ".join(r["caveats"]) or r["overall_status"]}'
        for r in needed if r["is_blocking"]
    ]

    coverage_summary = {
        "needed_total": len(needed),
        "fresh": fresh,
        "aging": aging,
        "stale": stale,
        "missing": missing,
        "broken": broken,
        "insufficient_horizon": insufficient,
        "ready_for_stress_test": (
            missing == 0 and stale == 0 and broken == 0 and insufficient == 0
        ),
        "blocking_issues": blocking_issues,
        "stale_vs_spot": [r["factor"] for r in needed
                          if (r.get("spot_check") or {}).get("status") == "stale_vs_spot"],
        "matrix_replaced": [r["factor"] for r in needed
                            if (r.get("matrix_check") or {}).get("status") == "replaced"],
        "coverage_score": f"{len(needed) - missing - broken - stale - insufficient}/{len(needed)}",
    }

    mode_rec = recommend_mode(rows)

    out = {
        "today": today.isoformat(),
        "rows": rows,
        "summary": coverage_summary,
        "mode_recommendation": mode_rec,
    }
    if monitor_out is not None:
        out["monitor"] = monitor_out
    if spot_out is not None:
        out["spot"] = spot_out
    if matrix_out is not None:
        out["matrix"] = matrix_out

    scenarios = payload.get("scenarios_to_check")
    if scenarios:
        out["consistency"] = check_consistency(scenarios)

    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Coverage report + consistency check for macro-forecast-chain.",
    )
    parser.add_argument("--input", "-i")
    parser.add_argument("--output", "-o")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument(
        "--monitor-report",
        help="папка monitor-reports/ (последний полный отчёт + частичные новее) или один файл "
             "отчёта монитора: прогноз с пробоем (factor_breach) — STALE",
    )
    parser.add_argument(
        "--spot",
        help="папка macro-snapshots/ (самый свежий срез скилла или автосрез сайта) или один файл "
             "ru-<дата>.json|.md: центр прогноза дальше от спота, чем порог фактора, — STALE",
    )
    parser.add_argument("--root", help="корень Claude-Memory: fca_stats читается из forecast_file фактора, "
                        "и матрица прогноза сверяется с действующей")
    args = parser.parse_args(argv)

    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            payload = json.load(f)
    else:
        payload = json.load(sys.stdin)

    monitor = None
    if args.monitor_report:
        try:
            monitor = merged_monitor_alerts(args.monitor_report)
        except Exception as e:  # OSError, ValueError, ImportError, yaml.YAMLError
            print(f"отчёт монитора не прочитан: {e}", file=sys.stderr)
            return 2

    spot = None
    if args.spot:
        try:
            spot = load_spot(args.spot)
        except Exception as e:  # OSError, ValueError, json.JSONDecodeError
            print(f"макроснимок не прочитан: {e}", file=sys.stderr)
            return 2

    result = compute(payload, monitor, spot, args.root)
    indent = 2 if args.pretty else None
    serialized = json.dumps(result, ensure_ascii=False, indent=indent)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(serialized)
            f.write("\n")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    sys.exit(main())
