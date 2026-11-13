#!/usr/bin/env python3
"""Чтение источников по бумаге — читатели выборки `security_digest.py`.

Только чтение, без записи и сети: обзоры недели (`per_stock`/`per_bond`), снапшоты портфеля (`holdings`,
`ie_actual.per_ticker`, `per_instrument_xirr`), шапки отчётов `Portfolio/reports/*.md`. Канон — здесь
(`_shared-references/`); `security_digest.py` (ru-portfolio-advisor) импортирует функции отсюда, в упакованный скилл модуль кладёт
pack.sh по импорту. Запись у обзора несёт и
`recorded_at` (время записи обзора, schema.md §4.2; у старых обзоров без него — None).

Зависимости: stdlib + PyYAML.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import math
import re
from pathlib import Path
from typing import Any

import yaml

BASIS_MAX = 200
SNAPSHOT_RE = re.compile(r"portfolio-\d{4}-\d{2}-\d{2}\.json")
# облигации: ISIN РФ-выпусков и биржевые коды ОФЗ (SU26243RMFS4); у акций ключ — короткий тикер
BOND_KEY_RE = re.compile(r"^(RU000A[0-9A-Z]{6}|SU\d{5}[A-Z]{4}\d)$")
OFZ_CODE_RE = re.compile(r"^SU\d{5}[A-Z]{4}\d$")


def _iso(x: Any) -> str | None:
    if isinstance(x, (dt.date, dt.datetime)):
        return x.isoformat()[:10]
    if isinstance(x, str) and re.match(r"\d{4}-\d{2}-\d{2}", x):
        return x[:10]
    return None


def _created_at(x: Any) -> str | None:
    """frontmatter.created_at → «YYYY-MM-DDTHH:MM» (локальное время записи); нечитаемое → None."""
    if isinstance(x, dt.datetime):
        return x.strftime("%Y-%m-%dT%H:%M")
    if isinstance(x, str):
        m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})", x.strip())
        if m:
            return f"{m.group(1)}T{m.group(2)}"
    return None


def clean(obj: Any) -> Any:
    """Привести значение YAML/JSON к чистому JSON: даты → ISO, ключи → str, NaN/inf → None."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [clean(v) for v in obj]
    if isinstance(obj, dt.datetime):
        return obj.isoformat()
    if isinstance(obj, dt.date):
        return obj.isoformat()
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def _num(x: Any) -> float | int | None:
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return x if math.isfinite(x) else None
    return None


def basis_first(text: Any, limit: int = BASIS_MAX) -> str | None:
    """Первое предложение обоснования вердикта, не длиннее limit символов (обрезка — с «…»)."""
    if not isinstance(text, str):
        return None
    t = " ".join(text.split())
    if not t:
        return None
    m = re.search(r"[.!?](?=\s+[A-ZА-ЯЁ«\"(\[\d])", t)
    first = t[: m.end()] if m else t
    if len(first) > limit:
        first = first[: limit - 1].rstrip() + "…"
    return first


def holding_key(h: dict) -> str | None:
    """Ключ бумаги по строке снапшота: тикер; биржевой код ОФЗ с известным ISIN → ISIN (как в обзорах)."""
    t = h.get("ticker") or h.get("isin")
    if not t:
        return None
    if OFZ_CODE_RE.match(str(t)) and h.get("isin"):
        return str(h["isin"])
    return str(t)


def kind_of_asset(asset_type: Any) -> str | None:
    a = str(asset_type or "").lower()
    if a == "bond":
        return "bond"
    if a == "stock":
        return "stock"
    if a.startswith("fund"):
        return "fund"
    return None


def resolve_kind(key: str, reviews: list[dict], snapshots: list[dict]) -> str:
    """Вид бумаги: обзор (per_bond/per_stock) > облигационный шаблон ключа > asset_type последнего снапшота."""
    for r in sorted(reviews, key=lambda r: (r.get("date") or "", r.get("file") or ""), reverse=True):
        if r.get("kind") in ("stock", "bond"):
            return r["kind"]
    if BOND_KEY_RE.match(key):
        return "bond"
    for s in sorted(snapshots, key=lambda s: (s.get("date") or "", s.get("file") or ""), reverse=True):
        for h in s.get("holdings") or []:
            if holding_key(h) == key and kind_of_asset(h.get("asset_type")):
                return kind_of_asset(h.get("asset_type"))
    return "stock"


# ───────────────────────────── строка обзора ─────────────────────────────

def review_row(rev: dict, kind: str) -> dict:
    e = rev.get("entry") or {}
    row: dict = {
        "date": rev.get("date"),
        "file": rev.get("file"),
        "verdict": e.get("advisor_verdict"),
        "confidence": e.get("advisor_verdict_confidence"),
        "confidence_basis": e.get("confidence_basis"),
    }
    if kind == "bond":
        row["credit_quality"] = e.get("credit_quality")
        row["credit_rating"] = e.get("credit_rating")
    else:
        row["fundamental_score"] = e.get("fundamental_score")
    row.update({
        "weight_pct": e.get("weight_real_pct"),
        "plan_pct": e.get("weight_user_planned_pct"),
        "ie_pct": e.get("weight_ie_target_pct"),
        "price": e.get("current_price") if kind == "bond" else e.get("price_rub"),
        "basis_first": basis_first(e.get("advisor_verdict_basis")),
        "verification_priority": e.get("verification_priority"),
        "unconstrained_verdict": e.get("unconstrained_verdict"),
        "p_outperform_3m": e.get("p_outperform_3m"),
        "week_note": e.get("week_note"),
        "snapshot_id": rev.get("snapshot_id"),
    })
    return clean(row)


def _yaml_load(path: Path) -> Any:
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    with open(path, encoding="utf-8") as fh:
        return yaml.load(fh, Loader=loader)


def review_kind(path: Path, doc: dict) -> str | None:
    t = str(doc.get("type") or "").lower()
    if "bond" in t or "-bond-" in path.name:
        return "bond"
    if "stock" in t or "-stock-" in path.name or re.fullmatch(r"weekly-review-\d{4}-\d{2}-\d{2}\.yaml", path.name):
        return "stock"
    return None


def positions(doc: dict, kind: str) -> list[tuple[str, dict]]:
    ps = doc.get("per_stock" if kind == "stock" else "per_bond")
    if isinstance(ps, dict):
        return [(str(k), v) for k, v in ps.items() if isinstance(v, dict)]
    if isinstance(ps, list):
        out = []
        for x in ps:
            if isinstance(x, dict) and (x.get("isin") or x.get("ticker")):
                out.append((str(x.get("isin") or x.get("ticker")), x))
        return out
    return []


def load_reviews(pdir: Path, skipped: list[str]) -> tuple[dict[str, list[dict]], int]:
    """→ ({ключ: [запись обзора]}, число прочитанных файлов обзоров)."""
    by_key: dict[str, list[dict]] = {}
    n = 0
    for f in sorted(glob.glob(str(pdir / "weekly-reviews" / "weekly-review-*.yaml"))):
        p = Path(f)
        try:
            doc = _yaml_load(p)
        except Exception as e:                                   # noqa: BLE001 — битый YAML не роняет сборку
            skipped.append(f"{p.name}: нечитаемый YAML ({type(e).__name__})")
            continue
        if not isinstance(doc, dict):
            skipped.append(f"{p.name}: не словарь")
            continue
        kind = review_kind(p, doc)
        if kind is None or not positions(doc, kind):
            skipped.append(f"{p.name}: нет per_stock/per_bond")
            continue
        m = re.search(r"(\d{4}-\d{2}-\d{2})", p.name)
        date = _iso(doc.get("review_date")) or (m.group(1) if m else None)
        if not date:
            skipped.append(f"{p.name}: нет даты")
            continue
        n += 1
        for key, entry in positions(doc, kind):
            by_key.setdefault(key, []).append({"date": date, "file": p.name, "kind": kind,
                                               "snapshot_id": doc.get("snapshot_id"),
                                               "recorded_at": clean(doc.get("recorded_at")), "entry": entry})
    return by_key, n


def load_snapshots(pdir: Path, skipped: list[str]) -> list[dict]:
    out = []
    for f in sorted(glob.glob(str(pdir / "snapshots" / "portfolio-*.json"))):
        p = Path(f)
        if not SNAPSHOT_RE.fullmatch(p.name):
            continue                                              # .bak, -sector-fix и т.п.
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            skipped.append(f"{p.name}: нечитаемый JSON ({type(e).__name__})")
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("holdings"), list):
            skipped.append(f"{p.name}: нет holdings")
            continue
        date = _iso(doc.get("as_of_date")) or p.name[10:20]
        ie = ((doc.get("ie_actual") or {}).get("per_ticker")) if isinstance(doc.get("ie_actual"), dict) else None
        out.append({"date": date, "file": p.name, "holdings": doc["holdings"],
                    "ie": ie if isinstance(ie, dict) else {},
                    "xirr": doc.get("per_instrument_xirr") if isinstance(doc.get("per_instrument_xirr"), dict) else {}})
    out.sort(key=lambda s: (s["date"], s["file"]))
    return out


def apply_isin_aliases(snaps: list[dict]) -> int:
    """Биржевой код ОФЗ (SU26243RMFS4) → ISIN: связка берётся из любого снапшота, где ISIN указан
    (в записи позиции или в per_instrument_xirr[код].isin). В ранних снапшотах ISIN пуст — без этого
    бумага «исчезала» бы и «появлялась» заново; если ISIN-ряд того же счёта уже есть, ряд с кодом
    отбрасывается (дубль). → число подставленных ISIN."""
    alias: dict[str, str] = {}
    for s in snaps:
        for h in s["holdings"]:
            if isinstance(h, dict) and OFZ_CODE_RE.match(str(h.get("ticker") or "")) and h.get("isin"):
                alias[h["ticker"]] = h["isin"]
        for code, rec in (s.get("xirr") or {}).items():
            if OFZ_CODE_RE.match(str(code)) and isinstance(rec, dict) and rec.get("isin"):
                alias.setdefault(code, rec["isin"])
    n = 0
    for s in snaps:
        have = {(h.get("ticker"), h.get("account")) for h in s["holdings"] if isinstance(h, dict)}
        fixed = []
        for h in s["holdings"]:
            if isinstance(h, dict) and not h.get("isin") and alias.get(h.get("ticker")):
                if (alias[h["ticker"]], h.get("account")) in have:
                    continue            # снапшот дважды перечисляет выпуск (ISIN и код) — второй ряд лишний
                h = {**h, "isin": alias[h["ticker"]]}
                n += 1
            fixed.append(h)
        s["holdings"] = fixed
    return n


FM_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)


def load_reports(pdir: Path, skipped: list[str]) -> tuple[dict[str, list[dict]], int]:
    by: dict[str, list[dict]] = {}
    n = 0
    for f in sorted(glob.glob(str(pdir / "reports" / "*.md"))):
        p = Path(f)
        try:
            with open(p, encoding="utf-8") as fh:
                head = fh.read(65536)
        except (OSError, UnicodeDecodeError) as e:
            skipped.append(f"{p.name}: не читается ({type(e).__name__})")
            continue
        m = FM_RE.match(head)
        if not m:
            continue                                              # отчёт без frontmatter — не в индексе
        try:
            fm = yaml.safe_load(m.group(1))
        except Exception as e:                                    # noqa: BLE001
            skipped.append(f"{p.name}: битый frontmatter ({type(e).__name__})")
            continue
        if not isinstance(fm, dict):
            continue
        n += 1
        tk = fm.get("tickers")
        tickers = [tk] if isinstance(tk, str) else (tk if isinstance(tk, list) else [])
        mdate = re.match(r"(\d{4}-\d{2}-\d{2})", p.name)
        row = {"date": _iso(fm.get("date")) or (mdate.group(1) if mdate else None), "file": p.name,
               "title": fm.get("title"), "kind": fm.get("kind"), "mode": fm.get("mode"),
               "summary": fm.get("summary"), "created_at": _created_at(fm.get("created_at"))}
        for t in dict.fromkeys(str(x) for x in tickers if x):
            by.setdefault(t, []).append(row)
    return by, n
