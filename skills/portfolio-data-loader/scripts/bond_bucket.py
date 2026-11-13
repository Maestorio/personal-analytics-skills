#!/usr/bin/env python3
"""
bond_bucket.py — корзина облигации выводится из данных Мосбиржи и рейтинга, а не вводится руками.

Контракт (SSOT — docs/investment/portfolio/bond-subtypes-plan.md §4.5): пара (Тип, Подтип) =
  • валюта номинала не RUB → USD / EUR / CNY (подтипа нет);
  • эмитент Минфин РФ (ОФЗ) → ОФЗ/Флоат (переменный купон) либо ОФЗ/>10, ОФЗ/<10 по годам до погашения
    от даты снапшота (≥10 лет — «>10»);
  • прочее корпоративное → КОРП/<корзина по лестнице рейтингов>; рейтинг: rating последнего
    обзора облигаций (per_bond[ISIN].rating.value, не позднее даты снапшота) → plan.bonds[ISIN].rating → нет →
    подтип пуст;
  • иностранный суверен / регион (issuer_type gov_other) вывести нельзя — только вручную.
Ручная корзина — plan.bonds[ISIN].manual = true (+ reason): перебивает вывод.

Модуль — чистые функции (без сети и записи); данные приносит assemble_snapshot.py: справочник
Portfolio/security-types.json (блок "bond", security_types.py) и обзор облигаций (weekly-reviews).
Только stdlib + PyYAML (чтение обзора).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from parse_portfolio import RATING_LADDER, rating_to_corp_bucket

OFZ_SPLIT_YEARS = 10.0
RATING_AGENCIES = ("АКРА", "Эксперт РА", "НКР", "НРА")
NO_RATING = "нет рейтинга"
FX_BUCKETS = ("USD", "EUR", "CNY")

SRC_ISS, SRC_RATING, SRC_MANUAL, SRC_PLAN = "iss", "rating", "manual", "plan"


def _key(typ: str | None, sub: str | None) -> str | None:
    return None if not typ else (f"{typ}/{sub}" if sub else typ)


def _pdate(v: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _ru_num(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def _ru_date(d: Any) -> str:
    p = _pdate(d)
    return p.strftime("%d.%m.%Y") if p else str(d)


# ───────────────────────────── источники данных ─────────────────────────────

def attrs_by_isin(types_data: dict | None) -> dict[str, dict]:
    """ISIN → блок "bond" справочника типов (запись справочника ключуется SECID, ISIN — в поле isin)."""
    out: dict[str, dict] = {}
    for tk, e in ((types_data or {}).get("by_ticker") or {}).items():
        if not isinstance(e, dict) or not isinstance(e.get("bond"), dict):
            continue
        isin = e.get("isin") or tk
        out[isin] = e["bond"]
        out.setdefault(tk, e["bond"])
    return out


def normalize_rating(v: Any) -> str | None:
    """Значение рейтинга как в лестнице (AA-, A+ …) либо None; «нет рейтинга» → None."""
    if v is None:
        return None
    r = str(v).strip().upper().replace("−", "-").replace("–", "-")
    return r if r in RATING_LADDER else None


def load_review_ratings(reviews_dir: str | Path | None, as_of: str | None = None) -> dict[str, dict]:
    """ISIN → {value, agency, date, source, review} из ПОСЛЕДНЕГО обзора облигаций (по review_date не
    позднее as_of; позднее — не берём: рейтинг из будущего относительно снапшота). Нет папки / файла /
    PyYAML — пусто. Записи без rating.value пропускаются."""
    if not reviews_dir:
        return {}
    d = Path(reviews_dir)
    if not d.is_dir():
        return {}
    try:
        import yaml
    except ImportError:
        return {}
    cut = (as_of or "9999-12-31")[:10]
    files = sorted(d.glob("weekly-review-bond-*.yaml"), reverse=True)
    for f in files:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", f.name)
        if not m or m.group(1) > cut:
            continue
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        out: dict[str, dict] = {}
        for isin, b in (doc.get("per_bond") or {}).items():
            r = (b or {}).get("rating") if isinstance(b, dict) else None
            if isinstance(r, dict) and r.get("value") not in (None, ""):
                out[str(isin)] = {"value": r.get("value"), "agency": r.get("agency"),
                                  "date": str(r.get("date") or "") or None,
                                  "source": r.get("source"), "review": f.name}
        return out                                      # последний обзор — единственный источник
    return {}


# ───────────────────────────── вывод корзины ─────────────────────────────

def years_to(maturity: Any, as_of: Any) -> float | None:
    m, a = _pdate(maturity), _pdate(as_of)
    if not m or not a:
        return None
    return (m - a).days / 365.25


def derive_bucket(attrs: dict | None, *, nominal_currency: str | None, maturity_date: Any, as_of: Any,
                  plan_rating: Any = None, review_rating: dict | None = None) -> dict:
    """Выведенная корзина. → {type, subtype, key, source, reason, codes[]}.
    key None — вывести нельзя (reason говорит почему); codes: bond_rating_missing /
    bond_rating_below_ladder / bond_issuer_not_derivable."""
    res: dict = {"type": None, "subtype": None, "key": None, "source": None, "reason": None, "codes": []}
    if not isinstance(attrs, dict):
        res["reason"] = "нет данных Мосбиржи по бумаге"
        return res
    unit = (attrs.get("faceunit") or nominal_currency or "RUB")
    unit = {"SUR": "RUB", "RUR": "RUB"}.get(str(unit).upper(), str(unit).upper())
    if unit != "RUB":
        if unit in FX_BUCKETS:
            res.update(type=unit, key=unit, source=SRC_ISS, reason=f"валюта номинала {unit}")
        else:
            res["reason"] = f"валюта номинала {unit} вне корзин плана"
            res["codes"].append("bond_issuer_not_derivable")
        return res
    issuer = attrs.get("issuer_type")
    if issuer == "ofz":
        res["type"] = "ОФЗ"
        if attrs.get("is_floater"):
            res.update(subtype="Флоат", source=SRC_ISS, reason="ОФЗ, переменный купон")
        else:
            yrs = years_to(attrs.get("matdate") or maturity_date, as_of)
            if yrs is None:
                res["type"] = None
                res["reason"] = "ОФЗ, срок до погашения неизвестен"
                res["codes"].append("bond_issuer_not_derivable")
                return res
            sub = ">10" if yrs >= OFZ_SPLIT_YEARS else "<10"
            res.update(subtype=sub, source=SRC_ISS, reason=f"ОФЗ, до погашения {_ru_num(yrs)} г.")
        res["key"] = _key(res["type"], res["subtype"])
        return res
    if issuer == "gov_other":
        res["reason"] = "иностранный суверен или регион — корзина только вручную"
        res["codes"].append("bond_issuer_not_derivable")
        return res
    # корпоративная
    res["type"] = "КОРП"
    raw, who = None, None
    if review_rating and review_rating.get("value") not in (None, ""):
        raw = review_rating["value"]
        ag, dd = review_rating.get("agency"), review_rating.get("date")
        who = ", ".join(x for x in (ag, _ru_date(dd) if dd else None, "обзор") if x)
    elif plan_rating not in (None, ""):
        raw, who = plan_rating, "план"
    if raw is None or str(raw).strip().lower() == NO_RATING:
        res["type"] = None
        res["reason"] = "КОРП, рейтинга нет — подтип не вывести"
        res["codes"].append("bond_rating_missing")
        return res
    nr = normalize_rating(raw)
    bucket = rating_to_corp_bucket(nr) if nr else None
    if bucket is None:
        res["type"] = None
        res["reason"] = f"КОРП, рейтинг {raw} ({who}) вне лестницы — подтип не вывести"
        res["codes"].append("bond_rating_below_ladder")
        return res
    res.update(subtype=bucket, key=_key("КОРП", bucket), source=SRC_RATING,
               reason=f"КОРП, рейтинг {nr} ({who})")
    return res


# ───────────────────────────── применение к holdings ─────────────────────────────

def apply_bond_buckets(holdings: list[dict], plan_bonds: dict | None, attrs: dict[str, dict],
                       review_ratings: dict[str, dict], as_of: Any, attrs_missing: bool = False
                       ) -> tuple[dict, list[dict]]:
    """Проставляет на каждый holding-облигацию bucket_source / bucket_derived / bucket_reason и, где корзина
    ещё не задана планом, — plan_bucket/plan_subtype/plan_bucket_key. Итоговый ключ:
      manual  → из плана (plan.bonds[ISIN].manual = true);
      иначе, выведенная == плановая → она (источник iss / rating);
      плана нет → выведенная;
      выведенная ≠ плановой → плановая (старое поведение) + запись в changes (решает владелец);
      вывести нельзя / нет данных Мосбиржи → плановая, источник plan.
    → (блок bond_bucket_check, flags[{severity, code, message}])."""
    plan_bonds = plan_bonds or {}
    changes: list[dict] = []
    missing: list[dict] = []
    derived_n = 0
    seen_flag: set[tuple[str, str]] = set()
    flags: list[dict] = []
    for h in holdings:
        if h.get("asset_type") != "bond":
            continue
        isin = h.get("isin") or h.get("ticker")
        pe = plan_bonds.get(isin) or plan_bonds.get(h.get("ticker")) or {}
        cur_t, cur_s = h.get("plan_bucket"), h.get("plan_subtype")
        cur_key = h.get("plan_bucket_key")
        a = attrs.get(isin) or attrs.get(h.get("ticker"))
        d = derive_bucket(a, nominal_currency=h.get("nominal_currency"),
                          maturity_date=h.get("maturity_date"), as_of=as_of,
                          plan_rating=pe.get("rating") if pe.get("rating") not in (None, "") else None,
                          review_rating=review_ratings.get(isin) or review_ratings.get(h.get("ticker")))
        h["bucket_derived"] = d["key"]
        name = h.get("name") or isin
        if pe.get("manual") is True:
            h["bucket_source"] = SRC_MANUAL
            why = str(pe.get("reason") or "").strip()
            h["bucket_reason"] = "вручную: " + (why or "причина не указана")
            continue
        if d["key"] is None:
            h["bucket_source"] = SRC_PLAN
            h["bucket_reason"] = (f"{d['reason']}; корзина из плана" if cur_key
                                  else f"{d['reason']}; корзины нет")
            for code in d["codes"]:
                if (isin, code) in seen_flag:
                    continue
                seen_flag.add((isin, code))
                missing.append({"isin": isin, "name": name, "code": code, "reason": d["reason"]})
                if code == "bond_rating_missing":
                    flags.append({"severity": "info", "code": code,
                                  "message": f"{name}: рейтинга нет ни в плане, ни в обзоре облигаций — "
                                             f"подтип КОРП не вывести (корзина в плане: {cur_key or 'нет'})."})
            continue
        derived_n += 1
        if not cur_key:                                       # плановой корзины нет → выведенная
            h["plan_bucket"], h["plan_subtype"], h["plan_bucket_key"] = d["type"], d["subtype"], d["key"]
            h["bucket_source"], h["bucket_reason"] = d["source"], d["reason"]
        elif cur_key == d["key"]:
            h["bucket_source"], h["bucket_reason"] = d["source"], d["reason"]
        else:
            h["bucket_source"] = SRC_PLAN
            h["bucket_reason"] = f"план: {cur_key}; выведено: {d['key']} ({d['reason']})"
            if (isin, "changed") not in seen_flag:
                seen_flag.add((isin, "changed"))
                changes.append({"isin": isin, "name": name, "was": cur_key, "now": d["key"],
                                "reason": d["reason"]})
                flags.append({"severity": "warn", "code": "bond_bucket_changed",
                              "message": f"{name}: корзина в плане {cur_key}, выведена {d['key']} "
                                         f"({d['reason']}); в снапшоте — по плану, решает владелец."})
    block = {"changes": changes, "missing": missing, "derived": derived_n, "attrs_missing": bool(attrs_missing)}
    return block, flags


def read_types_cache(path: str | Path | None) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    except (OSError, ValueError, TypeError):
        return {}
