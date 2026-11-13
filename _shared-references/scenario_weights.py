#!/usr/bin/env python3
"""
scenario_weights.py — чтение файла весов сайта `stress-weights-<матрица>.json` (схема
stress-weights@1) и получение весов сценариев на произвольные даты.

Файл сайта — единый источник весов: владелец задаёт их на странице «Стресс», стресс и пересчёт
макро-цепочки читают их оттуда. Сроки сайта (hNN → дата) могут не совпадать с датами прогнозов:
между двумя соседними сроками веса интерполируются линейно по числу дней, раньше первого и
позже последнего срока берётся значение ближайшего срока.

stdlib only.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

SCHEMA = "stress-weights@1"
WEIGHT_TOL = 1e-6  # как в stress_recalc.py


class SiteWeightsError(ValueError):
    """Файл весов сайта есть, но не годится."""


def site_file_for(matrix_path) -> Path:
    """Соседний файл сайта: <папка матрицы>/stress-weights-<stem матрицы>.json."""
    p = Path(matrix_path)
    return p.parent / f"stress-weights-{p.stem}.json"


def _iso(value, where: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise SiteWeightsError(f"{where}: «{value}» — не дата ISO (ГГГГ-ММ-ДД)") from None


def load_site(path) -> dict | None:
    """None — файла нет; SiteWeightsError — файл есть, но не годится. Имя файла кладётся в `_file`."""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SiteWeightsError(f"{p.name}: не читается как JSON ({e})") from e
    if not isinstance(data, dict):
        raise SiteWeightsError(f"{p.name}: корень должен быть объектом")
    if data.get("schema") != SCHEMA:
        raise SiteWeightsError(
            f"{p.name}: schema «{data.get('schema')}», ожидается «{SCHEMA}»")
    ends = data.get("horizon_ends")
    if not isinstance(ends, dict) or not ends:
        raise SiteWeightsError(f"{p.name}: horizon_ends пуст или не объект")
    parsed = {str(h): _iso(d, f"{p.name}: horizon_ends[{h}]") for h, d in ends.items()}
    if len(set(parsed.values())) != len(parsed):
        raise SiteWeightsError(f"{p.name}: в horizon_ends есть совпадающие даты")
    weights = data.get("weights")
    if not isinstance(weights, dict) or set(weights) != set(ends):
        raise SiteWeightsError(
            f"{p.name}: ключи weights {sorted(weights) if isinstance(weights, dict) else weights} "
            f"не совпадают с horizon_ends {sorted(ends)}")
    ids = None
    for h, w in weights.items():
        if not isinstance(w, dict) or not w:
            raise SiteWeightsError(f"{p.name}: weights[{h}] пуст или не объект")
        if ids is None:
            ids = set(w)
        elif set(w) != ids:
            raise SiteWeightsError(
                f"{p.name}: набор сценариев в сроке {h} ({sorted(w)}) отличается от "
                f"остальных ({sorted(ids)})")
        for sid, v in w.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
                raise SiteWeightsError(
                    f"{p.name}: вес {sid} в сроке {h} = {v!r} — нужно число от 0 до 1")
        s = sum(w.values())
        if abs(s - 1) > WEIGHT_TOL:
            raise SiteWeightsError(f"{p.name}: сумма весов в сроке {h} = {s:.6f}, ожидается 1")
    out = dict(data)
    out["_file"] = p.name
    return out


def weights_on_dates(site: dict, dates: list[str]) -> tuple[dict[str, dict[str, float]], dict]:
    """Веса на запрошенные даты (ISO) + мета способа получения."""
    terms = sorted(((_iso(d, f"horizon_ends[{h}]"), h) for h, d in site["horizon_ends"].items()))
    out: dict[str, dict[str, float]] = {}
    exact, interp, held = [], [], []
    for ds in sorted(set(dates)):
        d = _iso(ds, "запрошенная дата")
        hit = next((h for t, h in terms if t == d), None)
        if hit is not None:
            w = {k: float(v) for k, v in site["weights"][hit].items()}
            exact.append(ds)
        elif d < terms[0][0] or d > terms[-1][0]:
            h = terms[0][1] if d < terms[0][0] else terms[-1][1]
            w = {k: float(v) for k, v in site["weights"][h].items()}
            held.append(ds)
        else:
            (t0, h0), (t1, h1) = next(
                ((a, b) for a, b in zip(terms, terms[1:]) if a[0] < d < b[0]))
            f = (d - t0).days / (t1 - t0).days
            w0, w1 = site["weights"][h0], site["weights"][h1]
            w = {k: float(w0[k]) + (float(w1[k]) - float(w0[k])) * f for k in w0}
            interp.append(ds)
        w = {k: round(v, 6) for k, v in w.items()}
        if abs(sum(w.values()) - 1) > 1e-5:
            raise SiteWeightsError(f"сумма весов на {ds} = {sum(w.values()):.6f}, ожидается 1")
        out[ds] = w
    meta = {
        "source": "site", "file": site.get("_file"), "set_at": site.get("set_at"),
        "site_dates": {h: t.isoformat() for t, h in terms},
        "exact": exact, "interpolated": interp, "held": held,
    }
    return out, meta
