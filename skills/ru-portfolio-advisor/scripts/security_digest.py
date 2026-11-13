#!/usr/bin/env python3
"""
security_digest.py — выборка по одной бумаге для разбора (C5, schema.md §6): всё, что советнику нужно о бумаге из
баз Claude-Memory, одной короткой выдачей вместо чтения файлов целиком.

Что собирает (только чтение; файлы целиком в выдачу не попадают):
  snapshot    строки последнего снапшота по ключу (счёт, количество, цена, стоимость, дата листинга), план/факт
              доли из `ie_actual.per_ticker` и `ie_goals` — цели Invest Era с потенциалом ОТ ТЕКУЩЕЙ ЦЕНЫ
              (цель ÷ текущая цена − 1; цена — живая котировка из `--quotes`, иначе цена снапшота; поля
              `growth_potential_*` снапшота посчитаны от цены IE на дату модели и в выдачу не попадают; у бумаги
              без позиции цены в снапшоте нет — потенциал считается только с `--quotes`);
  reviews     последние 3 строки обзоров недели по ключу: дата, recorded_at, вердикт, уверенность, первая фраза
              основания, файл;
  decisions   выборка решений `decisions_read.digest` (та же, что `decision_write.py digest`): последние решения,
              последнее решение с гейтом и статусами его условий;
  conditions  действующие условия ключа модулем (а) (та же выдача, что `apply_condition.py digest --key`);
  attrs       запись справочника бумаг `Portfolio/security-attrs.json` (класс, listed_at, note) или null;
  reports     последние 3 отчёта с ключом в `tickers[]`: путь, kind, дата, recorded_at, первые 300 знаков тела.
Читатели обзоров, снапшотов и шапок отчётов — общий модуль `security_sources.py`,
решений — `decisions_read.py`, условий — модуль (а) `conditions_merge.py`.

Вызов:  python3 security_digest.py --root <корень Claude-Memory> --key <тикер|ISIN> [--today ГГГГ-ММ-ДД] [--measure]
                                   [--quotes <quotes@1>]
        --quotes — файл живых цен `moex_quotes.py --emit quotes@1 --boards TQBR`: цена для `ie_goals`
                   (нужен бумаге без позиции; у бумаги портфеля заменяет цену снапшота более свежей).
        --measure — в stderr размер выдачи: байты и байты/4 ≈ токены (цель C5 — ≤ 6 000 на бумагу).
Выход — JSON в stdout; ошибка — код 1 и {"ok": false, "error": …}.

Зависимости: stdlib + PyYAML.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import conditions_merge as cm  # noqa: E402
import decisions_read as dr  # noqa: E402
import ds_schemas as ds  # noqa: E402
import time_msk  # noqa: E402
from security_sources import (  # noqa: E402
    FM_RE, apply_isin_aliases, clean, holding_key, load_reports, load_reviews, load_snapshots, resolve_kind,
    review_row,
)

REVIEWS_N = 3
REPORTS_N = 3
BODY_CHARS = 300
TOKEN_TARGET = 6000
ATTRS_REL = ("Portfolio", "security-attrs.json")
_HOLDING_FIELDS = ("account", "asset_type", "name", "isin", "qty", "current_price", "current_price_ts", "value_rub",
                   "avg_cost_rub", "listing_date", "listing_age_quarters", "first_appearance_date", "status")
_IE_FIELDS = ("real_share_pct", "planned_share_pct", "ie_new_pct", "user_plan", "user_status", "user_note_ai")


class CmdError(Exception):
    pass


def _num(x) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def load_quotes(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        q = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CmdError(f"--quotes: не удалось прочитать {path!r}: {exc}")
    if not isinstance(q, dict) or q.get("schema") != "quotes@1":
        raise CmdError(f"--quotes: {path!r} — не quotes@1 (нужен выход moex_quotes.py --emit quotes@1)")
    return q


def _ie_goals(key: str, snap: dict, pdir: Path | None, quotes: dict | None = None) -> dict | None:
    """Цели Invest Era по бумаге и потенциал от текущей цены (живая котировка, иначе цена снапшота; не оценка
    по себестоимости).

    Цель — `target_price_*` строки списка IE, иначе цена IE на дату модели × (1 + потенциал IE). Потенциал в
    выдаче — только расстояние от текущей цены до цели: число от цены на дату модели устаревает с каждым днём."""
    if pdir is None:
        return None
    try:
        doc = json.loads((pdir / "snapshots" / snap["file"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    model = doc.get("ie_model") if isinstance(doc, dict) else None
    rows = model.get("positions") if isinstance(model, dict) else None
    row = next((p for p in rows or [] if isinstance(p, dict) and p.get("ticker") == key), None)
    if row is None:
        return None
    base = _num(row.get("current_price_rub"))

    def goal(target_field: str, pot_field: str) -> float | None:
        t, pot = _num(row.get(target_field)), _num(row.get(pot_field))
        return t if t is not None else (round(base * (1 + pot / 100), 2) if base is not None and pot is not None else None)

    t12, tlt = goal("target_price_rub", "growth_potential_12m_pct"), goal("target_price_lt_rub", "growth_potential_lt_pct")
    item = ((quotes or {}).get("items") or {}).get(key) or {}
    live = _num(item.get("price")) if isinstance(item, dict) else None
    snap_price = next((_num(h.get("current_price")) for h in snap["holdings"]
                       if isinstance(h, dict) and holding_key(h) == key and _num(h.get("current_price"))
                       and h.get("current_price_source") != "cost_basis"), None)
    price = live or snap_price
    price_date = (str(item.get("ts") or quotes.get("fetched_at") or "")[:10] or None) if live else (snap["date"] if price else None)

    def pot_now(t: float | None) -> float | None:
        return round((t / price - 1) * 100, 1) if t is not None and price else None

    out = {"in_model": row.get("active_in_model") is not False, "model_date": model.get("extraction_date"),
           "target_12m_rub": t12, "target_lt_rub": tlt, "price_rub": price, "price_date": price_date,
           "price_source": ("котировка Мосбиржи" if live else "снапшот") if price else None,
           "potential_12m_pct": pot_now(t12), "potential_lt_pct": pot_now(tlt)}
    if price is None and (t12 is not None or tlt is not None):
        out["note"] = ("текущей цены нет — потенциал считается с --quotes "
                       "(moex_quotes.py --emit quotes@1 --boards TQBR): цель ÷ текущая цена − 1")
    return {k: v for k, v in out.items() if v is not None}


def _snapshot(key: str, snaps: list[dict], pdir: Path | None = None, quotes: dict | None = None) -> dict | None:
    if not snaps:
        return None
    s = snaps[-1]
    rows = [{k: h.get(k) for k in _HOLDING_FIELDS if h.get(k) is not None}
            for h in s["holdings"] if isinstance(h, dict) and holding_key(h) == key]
    ie = (s.get("ie") or {}).get(key) or {}
    return clean({"file": s["file"], "date": s["date"], "in_portfolio": bool(rows), "holdings": rows,
                  "plan": {k: ie.get(k) for k in _IE_FIELDS if ie.get(k) is not None} or None,
                  "ie_goals": _ie_goals(key, s, pdir, quotes)})


def _reviews(key: str, revs: list[dict], snaps: list[dict]) -> list[dict]:
    kind = resolve_kind(key, revs, snaps)
    last = sorted(revs, key=lambda r: (r.get("date") or "", r.get("file") or ""), reverse=True)[:REVIEWS_N]
    out = []
    for r in last:
        row = review_row(r, "bond" if kind == "bond" else "stock")
        out.append({"date": row["date"], "recorded_at": r.get("recorded_at"), "verdict": row["verdict"],
                    "confidence": row["confidence"], "basis_first": row["basis_first"], "file": row["file"]})
    return out


def _report_head(path: Path) -> tuple[dict, str]:
    """(шапка, первые BODY_CHARS знаков тела без лишних пробелов)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    m = FM_RE.match(text)
    fm = ds.report_frontmatter(text) if m else None
    body = text[m.end():] if m else text
    body = " ".join(body.split())
    return (fm if isinstance(fm, dict) else {}), body[:BODY_CHARS]


def _reports(key: str, rows: list[dict], pdir: Path) -> list[dict]:
    rows = sorted(rows, key=lambda r: (r.get("created_at") or r.get("date") or "", r.get("file") or ""),
                  reverse=True)[:REPORTS_N]
    out = []
    for r in rows:
        fm, head = _report_head(pdir / "reports" / r["file"])
        out.append({"path": f"Portfolio/reports/{r['file']}", "kind": r.get("kind"), "date": r.get("date"),
                    "recorded_at": fm.get("recorded_at"), "mode_codes": fm.get("mode_codes"), "head": head})
    return out


def _attrs(root: str, key: str) -> dict:
    path = os.path.join(root, *ATTRS_REL)
    if not os.path.isfile(path):
        return {"missing": True, "record": None}
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    rec = ((doc or {}).get("by_key") or {}).get(key)
    return {"missing": False, "record": rec}


def build(root: str, key: str, today: str, quotes: dict | None = None) -> dict:
    root = os.path.abspath(os.path.expanduser(root))
    pdir = Path(root) / "Portfolio"
    if not pdir.is_dir():
        raise CmdError(f"в корне {root} нет папки Portfolio/ — неверный --root или mount не подключён")
    skipped: list[str] = []
    rev_by, _ = load_reviews(pdir, skipped)
    snaps = load_snapshots(pdir, skipped)
    apply_isin_aliases(snaps)
    rep_by, _ = load_reports(pdir, skipped)
    rows, cond_missing = dr.conditions_rows(root, today)
    conds = cm.select(rows, keys=[key], only_active=True)
    return {
        "ok": True, "key": key, "today": today,
        "snapshot": _snapshot(key, snaps, pdir, quotes),
        "reviews": _reviews(key, rev_by.get(key, []), snaps),
        "decisions": dr.digest(root, key, today, limit=3),
        "conditions": {"missing": cond_missing, "count": len(conds),
                       "items": [{k: c[k] for k in ("id", "kind", "trigger", "status", "waits_owner", "verdict_now",
                                                    "verdict_on_trigger", "action_code", "valid_until", "text", "note")}
                                 for c in conds]},
        "attrs": _attrs(root, key),
        "reports": _reports(key, rep_by.get(key, []), pdir),
        "skipped_files": len(skipped),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Выборка по одной бумаге для разбора (C5)")
    ap.add_argument("--root", required=True, help="корень Claude-Memory (в Cowork — $HOME/mnt/Claude-Memory)")
    ap.add_argument("--key", required=True, help="тикер или ISIN")
    ap.add_argument("--today", default=None, help="дата оценки условий и гейта ГГГГ-ММ-ДД (по умолчанию сегодня, МСК)")
    ap.add_argument("--measure", action="store_true", help="в stderr: байты выдачи и байты/4 ≈ токены")
    ap.add_argument("--quotes", default=None, help="живые цены quotes@1 (moex_quotes.py --emit quotes@1) — цена для ie_goals")
    a = ap.parse_args(argv)
    today = a.today or time_msk.today_iso()
    try:
        if not ds.is_date(today):
            raise CmdError(f"--today: ожидается ГГГГ-ММ-ДД, получено {today!r}")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", a.key):
            raise CmdError(f"--key: ожидается тикер или ISIN, получено {a.key!r}")
        out, code = build(a.root, a.key, today, load_quotes(a.quotes)), 0
    except (CmdError, ValueError, OSError) as exc:
        out, code = {"ok": False, "error": str(exc)}, 1
    text = json.dumps(out, ensure_ascii=False, indent=1)
    print(text)
    if a.measure:
        n = len(text.encode("utf-8"))
        sys.stderr.write(f"measure: {n} байт ≈ {n // 4} токенов (цель ≤ {TOKEN_TARGET})\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
