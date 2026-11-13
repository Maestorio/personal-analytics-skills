#!/usr/bin/env python3
"""DEV-инструмент: собрать забандленные геоданные для карт Stage 5 (Фаза 2A).

Не часть скилла — запускается вручную при обновлении геоданных. Тянет Natural
Earth, обрезает до компактного вида, кладёт РАНТАЙМ-ассеты в скилл:

    skills/travel-planning/scripts/export/data/ne_countries.geojson  — контур
        стран (только NAME + упрощённая Douglas-Peucker геометрия) для заливки;
        ассет РЕНДЕРА (Export), остаётся в export/data/;
    skills/travel-planning/scripts/data/gazetteer.json               — газетир
        Tier-1 (name/ascii/lat/lon/country) для детерминированного геокодинга;
        ассет КОНТЕНТ-СТАДИИ (Stage 6 geocode.py, D4), лежит в scripts/data/.

Источники (скачать в /tmp заранее):
    ne_50m_admin_0_countries.geojson
    ne_10m_populated_places_simple.geojson
(URL — см. overview_map_prototype.py docstring).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.setrecursionlimit(100000)

SRC_COUNTRIES = Path("/tmp/ne50_countries.geojson")
SRC_PLACES = Path("/tmp/ne10_places.geojson")
_SKILL_SCRIPTS = (Path(__file__).resolve().parents[3]
                  / "skills" / "travel-planning" / "scripts")
# Контур стран — ассет рендера (Export); газетир — ассет контент-стадии (D4).
OUT_DIR = _SKILL_SCRIPTS / "export" / "data"       # ne_countries.geojson
GAZETTEER_DIR = _SKILL_SCRIPTS / "data"            # gazetteer.json

DP_EPS = 0.02  # градусы; упрощение контура (на масштабе страны незаметно)


def _perp(p, a, b):
    """Перпендикулярное расстояние точки p от отрезка a-b (в градусах, грубо)."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


def _dp(points, eps):
    """Douglas-Peucker (итеративно — без переполнения рекурсии)."""
    if len(points) < 3:
        return points[:]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        dmax, idx = 0.0, 0
        for i in range(lo + 1, hi):
            d = _perp(points[i], points[lo], points[hi])
            if d > dmax:
                dmax, idx = d, i
        if dmax > eps and idx:
            keep[idx] = True
            stack.append((lo, idx))
            stack.append((idx, hi))
    return [p for p, k in zip(points, keep) if k]


def _simplify_geom(geom):
    """Упростить кольца Polygon/MultiPolygon (только exterior, как в рендере)."""
    def ring(r):
        out = _dp([(c[0], c[1]) for c in r], DP_EPS)
        return [[round(x, 4), round(y, 4)] for x, y in out]
    if geom["type"] == "Polygon":
        return {"type": "Polygon", "coordinates": [ring(geom["coordinates"][0])]}
    return {"type": "MultiPolygon",
            "coordinates": [[ring(poly[0])] for poly in geom["coordinates"]]}


def build_countries():
    data = json.load(open(SRC_COUNTRIES))
    feats = []
    pts_before = pts_after = 0
    for f in data["features"]:
        name = f["properties"].get("NAME") or f["properties"].get("ADMIN")
        g = f["geometry"]
        pts_before += sum(len(r) for r in _rings(g))
        sg = _simplify_geom(g)
        pts_after += sum(len(r) for r in _rings(sg))
        feats.append({"type": "Feature", "properties": {"NAME": name},
                      "geometry": sg})
    out = {"type": "FeatureCollection", "features": feats}
    path = OUT_DIR / "ne_countries.geojson"
    path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    print(f"countries: {len(feats)} стран, точек {pts_before}→{pts_after} "
          f"({pts_after * 100 // pts_before}%), {path.stat().st_size // 1024} KB")


def _rings(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    return [poly[0] for poly in geom["coordinates"]]


def build_gazetteer():
    data = json.load(open(SRC_PLACES))
    rows = []
    for f in data["features"]:
        p = f["properties"]
        name = p.get("name")
        if not name:
            continue
        rows.append({
            "n": name,
            "a": p.get("nameascii") or name,
            "lat": round(float(p["latitude"]), 4),
            "lon": round(float(p["longitude"]), 4),
            "c": p.get("adm0name") or "",
        })
    GAZETTEER_DIR.mkdir(parents=True, exist_ok=True)
    path = GAZETTEER_DIR / "gazetteer.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")
    print(f"gazetteer: {len(rows)} городов, {path.stat().st_size // 1024} KB")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not SRC_COUNTRIES.exists() or not SRC_PLACES.exists():
        sys.exit("нет исходников в /tmp — скачай ne_50m_admin_0_countries.geojson "
                 "и ne_10m_populated_places_simple.geojson")
    build_countries()
    build_gazetteer()
    print("OK →", OUT_DIR)


if __name__ == "__main__":
    main()
