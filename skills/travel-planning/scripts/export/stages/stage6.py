"""stages/stage6.py — экстрактор + механический ассемблер финального PDF Stage 6.

**Контракт формата** артефакта `6_final_v{N}.md` (секции `## Координаты маршрута`
/ `## Дорожное досье` / опц. `## Бронирования` / `## Углубления`, YAML-шапка) —
канон `references/stage6/stage6-final.md` §8.

Stage 6 — финишная доводка устаканенного плана 5_vX. ИНВАРИАНТ (анти-дрейф):
Stage 6 **НЕ редактирует** `5_final_plan.md` — он immutable SSOT маршрута.
Финальный «ideal»-PDF собирается **механически на рендере**:

    рендер 5_vX (переиспуск билдеров stage5.py — контент Stage 5 ни разу не
    прогоняется повторно через LLM → ноль дрейфа)
  + обзорная карта после обложки/TOC (из персистнутых координат 6_final.md)
  + приложения досье / бронь / углубления (из 6_final.md)

Слияние аддитивно: ошибки LLM Stage 6 заперты в добавках (худший случай —
неверная карта, не испорченный план; таблица координат ревьюабельна по `source`).

Архитектура:
  1. `extract_content(parsed)` — распарсенный `6_final.md` → структура
     (cover, coords_section, dossier, bookings, enrichment).
  2. `parse_coords_section` / `build_route_spec` — `## Координаты маршрута`
     (таблица точек + порядок маршрута + рёбра) → spec для рендерера карты.
  3. `render_route_map` (+ геометрия) — УНИВЕРСАЛЬНЫЙ рендерер обзорной карты
     (перенесён из dev-прототипа): авто bbox / point-in-polygon заливка /
     поправка широты / кривые рёбра / типы рёбер. matplotlib → PNG.
  4. `build_pdf(s5, s6, ...)` — механический ассемблер: вызывает
     `stage5.build_pdf` с inject-пакетом (карта + приложения).
  5. `render_stage6(parsed, ...)` — entry-point, регистрируется в renderer.

Граница LLM/скрипт (см. `references/stage6/stage6-final.md` §… и architecture.md):
координаты резолвятся на КОНТЕНТ-стадии (`scripts/geocode.py` Tier-1 + модель
Tier-2) и персистятся в `6_final.md`; рендерер только ЧИТАЕТ их, не геокодит.
"""
from __future__ import annotations

import math
import re
import tempfile
from pathlib import Path
from typing import Any

# Соседние модули пакета — поддерживаем оба режима запуска.
if __package__ in (None, ""):
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from export import adapter as _adapter        # type: ignore[no-redef]
    from export import parser as _parser          # type: ignore[no-redef]
    from export import pdf_lib                     # type: ignore[no-redef]
    from export import renderer as _renderer       # type: ignore[no-redef]
    from export.stages import stage5 as _s5        # type: ignore[no-redef]
    from export.style import COLORS, REGION_PALETTE  # type: ignore[no-redef]
else:
    from .. import adapter as _adapter
    from .. import parser as _parser
    from .. import pdf_lib
    from .. import renderer as _renderer
    from . import stage5 as _s5
    from ..style import COLORS, REGION_PALETTE

# matplotlib — soft import: без него карту не строим, остальной PDF рендерится.
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch
    MATPLOTLIB_AVAILABLE = True
except Exception:
    MATPLOTLIB_AVAILABLE = False

# Контур стран — ассет РЕНДЕРА (остаётся в export/data/; газетир по D4 — в
# scripts/data/, но он для контент-стадии geocode.py, не для рендера карты).
COUNTRIES_GEOJSON = (Path(__file__).resolve().parents[1] / "data"
                     / "ne_countries.geojson")

# Стили рёбер карты (вид перехода между остановками).
if MATPLOTLIB_AVAILABLE:
    EDGE_STYLE = {
        "normal": dict(color=COLORS["primary"], lw=1.5, ls="solid"),
        "long":   dict(color=COLORS["danger"],  lw=2.3, ls="solid"),   # «узкое звено»
        "air":    dict(color=COLORS["primary"], lw=1.4, ls=(0, (5, 3))),  # перелёт
    }
RAD = 0.22  # кривизна дуги ребра

_EDGE_MODE_RE = re.compile(
    r"(KoBus|автобус|поезд|KTX|КТХ|лимузин|паром|самол[её]т|рейс|метро|AREX|ITX)", re.I)


def _short_edge_label(label: str) -> str:
    """Сжать многословную метку ребра до «режим · длительность» (как в эталоне):
    «автобус KoBus (Express Bus Terminal, Каннам) · ~2 ч 20 мин» → «автобус · ~2 ч 20 мин».
    Хвостовую важную пометку в скобках (узкое звено) сохраняем."""
    if not label:
        return label
    head, dur = label, ""
    if "·" in label:
        segs = label.split("·")
        head = segs[0]
        for seg in segs[1:]:
            if re.search(r"\d.*(ч|мин|h|min)", seg):
                dur = seg.strip()
                break
        if not dur:
            dur = segs[-1].strip()
    modes: list[str] = []
    for m in _EDGE_MODE_RE.findall(head):
        ml = m.lower()
        mm = ("KTX" if ml in ("ktx", "ктх")
              else "автобус" if ml == "kobus" else ml)
        if mm not in modes:
            modes.append(mm)
    mode = "+".join(modes[:2])
    if mode and dur:
        return f"{mode} · {dur}"
    return mode or label


_AIRPORT_RE = re.compile(r"инчхон|incheon|\bICN\b|аэропорт|airport|кимпо|gimpo", re.I)


def _strip_airport_route(spec: dict) -> dict:
    """Убрать узлы-аэропорты (Инчхон/ICN) из маршрута карты: это точки прилёта/
    вылета, а не базы; их международные рёбра дают наложение подписей у Сеула."""
    nodes, route, edges = spec["nodes"], spec["route"], spec["edges"]
    air = {i for i, n in enumerate(nodes) if _AIRPORT_RE.search(str(n[2]) or "")}
    if not air:
        return spec
    keep = [k for k, ni in enumerate(route) if ni not in air]
    new_route = [route[k] for k in keep]
    new_edges = [edges[a] if (b == a + 1 and a < len(edges)) else ("", "normal")
                 for a, b in zip(keep, keep[1:])]
    return {**spec, "route": new_route, "edges": new_edges}


# ===========================================================================
# Геометрия карты (универсально, без привязки к стране) — из dev-прототипа
# ===========================================================================


def _polys(geom: dict) -> list:
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    return [poly[0] for poly in geom["coordinates"]]


def load_countries(path: str | Path | None = None) -> dict | None:
    """Загрузить контур стран из забандленного `ne_countries.geojson`.

    None, если файл отсутствует (карта тогда не строится — graceful).
    """
    import json
    p = Path(path) if path else COUNTRIES_GEOJSON
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    return {(f["properties"].get("NAME") or f["properties"].get("ADMIN")): _polys(f["geometry"])
            for f in data["features"]}


def _point_in_ring(x: float, y: float, ring: list) -> bool:
    """Ray-casting: точка (x=lon, y=lat) внутри кольца?"""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _fill_countries(nodes: list, countries: dict) -> set:
    """Авто-определение стран для заливки: те, что содержат узлы маршрута."""
    out: set = set()
    for lon, lat, *_ in nodes:
        for name, rings in countries.items():
            if any(_point_in_ring(lon, lat, r) for r in rings):
                out.add(name)
                break
    return out


def _auto_bbox(nodes: list) -> dict:
    """Рамка из координат узлов + поля (доля размаха, с минимумом)."""
    lons = [n[0] for n in nodes]
    lats = [n[1] for n in nodes]
    span_lon, span_lat = max(lons) - min(lons), max(lats) - min(lats)
    pad_lon = max(0.4, 0.18 * span_lon)
    pad_lat = max(0.4, 0.18 * span_lat)
    return dict(lon_min=min(lons) - pad_lon, lon_max=max(lons) + pad_lon,
                lat_min=min(lats) - pad_lat, lat_max=max(lats) + pad_lat)


# ===========================================================================
# Универсальный рендерер карты (matplotlib → PNG) — из dev-прототипа
# ===========================================================================


def render_route_map(spec: dict, countries: dict, out_base: str) -> str | None:
    """Отрисовать обзорную карту из чистого spec → `{out_base}.png`.

    spec: {title, nodes:[(lon,lat,name,days_label,(dx,dy))], route:[idx...],
           edges:[(label,kind)], context_layers}. bbox / страны заливки /
           поправка широты вычисляются автоматически (без пер-трип кода).
    Возвращает путь к PNG или None (нет matplotlib).
    """
    if not MATPLOTLIB_AVAILABLE:
        return None
    plt.rcParams["font.family"] = "DejaVu Sans"
    spec = _strip_airport_route(spec)
    # bbox по рисуемым (маршрутным) узлам — без аэропорта.
    bbox = _auto_bbox([spec["nodes"][i] for i in spec["route"]] or spec["nodes"])
    fill = _fill_countries(spec["nodes"], countries)

    # Фон карты = бумага HTML-экспорта (--paper), не белый: PNG сливается
    # с листом документа; в тёмной теме остаётся светлой «печатной вклейкой».
    map_bg = "#fbf9f4"
    fig, ax = plt.subplots(figsize=(7.6, 9.0))
    fig.patch.set_facecolor(map_bg)
    ax.set_xlim(bbox["lon_min"], bbox["lon_max"])
    ax.set_ylim(bbox["lat_min"], bbox["lat_max"])
    midlat = (bbox["lat_min"] + bbox["lat_max"]) / 2
    ax.set_aspect(1 / math.cos(math.radians(midlat)))  # авто поправка широты
    ax.axis("off")
    ax.set_title(spec["title"], fontsize=15, color=COLORS["primary"],
                 fontweight="bold", pad=14)
    # База: соседи бледно, страна(ы) маршрута — лёгкая заливка + navy-контур.
    # Палитра тёплая (бежевая), под дизайн-систему: холодные серо-голубые
    # заливки читались как «белые/холодные» пятна на тёплом листе. Соседи —
    # тёплый серо-беж, страна маршрута — песочная заливка (выделена контуром).
    for name, rings in countries.items():
        if name in fill:
            continue
        for ring in rings:
            xs, ys = zip(*ring)
            ax.fill(xs, ys, color="#efe8d8", zorder=0)
            ax.plot(xs, ys, color="#d7cdb8", lw=0.6, zorder=1)
    for name in fill:
        for ring in countries.get(name, []):
            xs, ys = zip(*ring)
            ax.fill(xs, ys, color="#e8dcc2", zorder=2)
            ax.plot(xs, ys, color=COLORS["primary"], lw=1.1, zorder=3)
    _draw_route(ax, spec, bbox)

    fig.savefig(f"{out_base}.png", dpi=150, bbox_inches="tight",
                facecolor=map_bg)
    plt.close(fig)
    return f"{out_base}.png"


def _draw_route(ax, spec: dict, bbox: dict) -> None:
    nodes, route, edges = spec["nodes"], spec["route"], spec["edges"]
    pts = [(nodes[i][0], nodes[i][1]) for i in route]
    for k in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[k], pts[k + 1]
        label, kind = edges[k] if k < len(edges) else ("", "normal")
        label = _short_edge_label(label)
        st = EDGE_STYLE.get(kind, EDGE_STYLE["normal"])
        ax.add_patch(FancyArrowPatch(
            (x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=12,
            connectionstyle=f"arc3,rad={RAD}", lw=st["lw"], color=st["color"],
            linestyle=st["ls"], alpha=0.9, shrinkA=10, shrinkB=10, zorder=5))
        if not label:
            continue
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        dx, dy = x1 - x0, y1 - y0
        nlen = math.hypot(dx, dy) or 1.0
        px, py = -dy / nlen, dx / nlen
        off = RAD * 0.5 * nlen
        ax.text(mx + px * off, my + py * off, label, fontsize=7.3,
                color=st["color"], zorder=7, ha="center", va="center",
                bbox=dict(boxstyle="round,pad=0.25", fc="white",
                          ec=st["color"], alpha=0.92, lw=0.6))
    # Узлы рисуем один раз (повтор route-индекса = старт==финиш). Геометрия
    # выноса подписей — де-коллизия близких пинов (Сеул/Инчхон) веером с
    # лидер-линиями; считается из реальной рамки (SYS-1/A2/A3).
    drawn_idx: list[int] = []
    seen: set = set()
    for i in route:
        if i not in seen:
            seen.add(i)
            drawn_idx.append(i)
    drawn_pts = [(nodes[i][0], nodes[i][1]) for i in drawn_idx]
    places = _label_placements(drawn_pts, bbox)
    for slot, i in enumerate(drawn_idx):
        lon, lat, name, days, _baked = nodes[i]
        num = route.index(i) + 1
        col = REGION_PALETTE[i % len(REGION_PALETTE)]
        ax.scatter([lon], [lat], s=260, color=col, edgecolor="white",
                   linewidth=1.5, zorder=8)
        ax.text(lon, lat, str(num), fontsize=9, color="white",
                fontweight="bold", ha="center", va="center", zorder=9)
        label = f"{name}\n{days}" if days else name
        pl = places[slot]
        arrowprops = (dict(arrowstyle="-", lw=0.6, color="#9a9a9a",
                           shrinkA=3, shrinkB=2, alpha=0.9)
                      if pl["leader"] else None)
        ax.annotate(label, (lon, lat), textcoords="offset points",
                    xytext=pl["off"], fontsize=8.5, color=COLORS["text"],
                    zorder=9, ha=pl["ha"], va=pl["va"], fontweight="bold",
                    arrowprops=arrowprops)


# Радиус выноса подписи (точки): компактный для одиночного пина, больший —
# для пинов в кластере (чтобы метки разъехались) + лидер-линия к пину.
_LBL_R_ISO = 11.0
_LBL_R_CLUSTER = 30.0
# Доля диагонали рамки (с поправкой на широту), ближе которой пины считаются
# «близкими» (их подписи, вероятно, наезжают) → кластер с веером + лидерами.
# Общая геометрическая эвристика, не привязка к конкретному маршруту.
_CLUSTER_FRAC = 0.14


def _placement(ang: float, r: float, *, leader: bool) -> dict:
    """Угол+радиус → смещение подписи (точки) + выравнивание + флаг лидера."""
    dx, dy = r * math.cos(ang), r * math.sin(ang)
    return {"off": (dx, dy), "leader": leader,
            "ha": "left" if dx >= 0 else "right",
            "va": "bottom" if dy >= 0 else "top"}


def _label_placements(pts: list, bbox: dict) -> list:
    """Геометрия выноса подписей пинов: де-коллизия близких узлов.

    `pts` — `(lon, lat)` ОТРИСОВАННЫХ узлов в порядке отрисовки. Возвращает по
    одному dict на узел (`off` в точках, `ha`/`va`, `leader`). Чистая геометрия,
    детерминированно (без matplotlib) — тестируемо.

    Узлы, чьё попарное расстояние (с поправкой cos(lat)) меньше доли диагонали
    рамки, собираются в кластер; их подписи раскидываются наружу от центроида
    кластера (Сеул/Инчхон расходятся) + лидер-линия пин→подпись. Одиночные —
    компактный вынос наружу от центра маршрута, без лидера.
    """
    n = len(pts)
    if n == 0:
        return []
    midlat = (bbox["lat_min"] + bbox["lat_max"]) / 2
    cosf = math.cos(math.radians(midlat)) or 1e-6
    cpts = [(p[0] * cosf, p[1]) for p in pts]  # плоские «км-подобные» координаты
    diag = math.hypot((bbox["lon_max"] - bbox["lon_min"]) * cosf,
                      bbox["lat_max"] - bbox["lat_min"]) or 1.0
    thresh = _CLUSTER_FRAC * diag

    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(n):
        for j in range(i + 1, n):
            if math.hypot(cpts[i][0] - cpts[j][0], cpts[i][1] - cpts[j][1]) < thresh:
                ra, rb = find(i), find(j)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
    clusters: dict = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(i)

    gx = sum(c[0] for c in cpts) / n  # центроид маршрута (для одиночных)
    gy = sum(c[1] for c in cpts) / n

    out: list = [None] * n
    for members in clusters.values():
        if len(members) == 1:
            i = members[0]
            vx, vy = cpts[i][0] - gx, cpts[i][1] - gy
            ang = math.atan2(vy, vx) if (vx or vy) else math.radians(35)
            out[i] = _placement(ang, _LBL_R_ISO, leader=False)
            continue
        cx = sum(cpts[k][0] for k in members) / len(members)
        cy = sum(cpts[k][1] for k in members) / len(members)
        # Базовый угол — наружу от центроида кластера; вырожденные (совпавшие)
        # узлы получают равномерный веер по порядку.
        m = len(members)
        for slot, k in enumerate(members):
            vx, vy = cpts[k][0] - cx, cpts[k][1] - cy
            ang = (math.atan2(vy, vx) if (abs(vx) > 1e-9 or abs(vy) > 1e-9)
                   else 2 * math.pi * slot / m)
            out[k] = _placement(ang, _LBL_R_CLUSTER, leader=True)
    return out


# ===========================================================================
# `## Координаты маршрута` → spec карты
# ===========================================================================

# Ключевые слова для типа ребра. air имеет приоритет над long.
_AIR_RE = re.compile(r"перел[её]т|самол[её]т|рейс|flight|авиа|AREX", re.IGNORECASE)
_LONG_RE = re.compile(r"узк\w+\s+звен|\blong\b", re.IGNORECASE)

# Смещения подписей пинов — чередуем, чтобы метки реже наезжали.
_PIN_OFFSETS = [(8, 5), (8, -9), (-10, 6), (-10, -9), (8, 2), (-10, 0)]


def _edge_kind(text: str) -> str:
    if _AIR_RE.search(text):
        return "air"
    if _LONG_RE.search(text):
        return "long"
    return "normal"


def _col_index(header: list[str], *keys: str) -> int | None:
    """Индекс колонки таблицы по вхождению любого из ключей в заголовок."""
    for i, h in enumerate(header):
        low = h.strip().lower()
        if any(k in low for k in keys):
            return i
    return None


def _to_float(s: str) -> float | None:
    s = (s or "").strip().replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def parse_coords_section(body: str) -> dict | None:
    """Распарсить тело `## Координаты маршрута` в данные карты.

    Возвращает {rows, route, edges} либо None, если таблицы координат нет:
      - rows  — [{name, lat, lon, source, days}] (порядок таблицы);
      - route — список 0-based индексов в rows (повтор = старт==финиш);
      - edges — [(label, kind)] длиной len(route)-1.
    """
    if not body or not body.strip():
        return None
    # 1) Таблица точек.
    blocks = _s5.extract_tables_and_text(body)
    table = next((b for b in blocks if b["type"] == "table" and b["rows"]), None)
    if not table:
        return None
    header = table["rows"][0]
    ci_name = _col_index(header, "точк", "регион", "место", "пункт", "name")
    ci_lat = _col_index(header, "lat", "шир")
    ci_lon = _col_index(header, "lon", "lng", "долг")
    ci_src = _col_index(header, "источник", "source")
    ci_days = _col_index(header, "дни", "день", "days")
    if ci_name is None or ci_lat is None or ci_lon is None:
        return None
    rows: list[dict] = []
    for r in table["rows"][1:]:
        if max(ci_name, ci_lat, ci_lon) >= len(r):
            continue
        lat = _to_float(r[ci_lat])
        lon = _to_float(r[ci_lon])
        name = (r[ci_name] or "").strip()
        if lat is None or lon is None or not name:
            continue
        rows.append({
            "name": name, "lat": lat, "lon": lon,
            "source": (r[ci_src].strip() if ci_src is not None and ci_src < len(r) else ""),
            "days": (r[ci_days].strip() if ci_days is not None and ci_days < len(r) else ""),
        })
    if not rows:
        return None

    n = len(rows)
    # 2) Порядок маршрута: строка «**Маршрут:** 1 → 2 → … → 1».
    route: list[int] = []
    mr = re.search(r"маршрут\s*:?\s*\**\s*(.+)", body, re.IGNORECASE)
    if mr:
        nums = [int(x) for x in re.findall(r"\d+", mr.group(1))]
        route = [x - 1 for x in nums if 1 <= x <= n]
    if not route:
        route = list(range(n))  # fallback: по порядку таблицы

    # 3) Рёбра: нумерованный список после «**Рёбра:**».
    edges: list[tuple[str, str]] = []
    er = re.search(r"р[её]бр\w*\s*:?", body, re.IGNORECASE)
    edge_zone = body[er.end():] if er else ""
    for line in edge_zone.splitlines():
        m = re.match(r"^\s*\d+[.)]\s+(.*)$", line)
        if not m:
            continue
        raw = m.group(1).strip()
        kind = _edge_kind(raw)
        # Подпись — после « — »/« - » (эндпоинты A → B слева отбрасываем).
        label = raw
        ds = re.split(r"\s+[—–-]\s+", raw, maxsplit=1)
        if len(ds) == 2:
            label = ds[1].strip()
        # Срезать хвостовой «(kind-маркер)» — стиль ребра его уже кодирует.
        label = re.sub(r"\s*\((?:обычн\w*|узк\w+\s+звен\w*|перел[её]т\w*|normal|long|air)\)\s*$",
                       "", label, flags=re.IGNORECASE).strip()
        edges.append((label, kind))
    # Выровнять длину рёбер под маршрут (len(route)-1).
    need = max(0, len(route) - 1)
    if len(edges) < need:
        edges += [("", "normal")] * (need - len(edges))
    elif len(edges) > need:
        edges = edges[:need]
    return {"rows": rows, "route": route, "edges": edges}


def _compact_days_label(s: str) -> str:
    """Сжать подпись дней пина для карты (A1): убрать парентезы-шум
    «(прилёт)/(вылет)/(блок N)» и схлопнуть повтор «день X, день Y» → «дни X, Y».

    «день 1 (прилёт), день 19 (вылет)» → «дни 1, 19»;
    «дни 1–2 (блок 1), дни 16–18 (блок 2)» → «дни 1–2, 16–18»;
    «дни 1–3, 11» → «дни 1–3, 11» (без изменений).
    """
    if not s or not s.strip():
        return s
    s = re.sub(r"\s*\([^)]*\)", "", s)            # срезать «(прилёт)» и т.п.
    s = re.sub(r"\s{2,}", " ", s)
    parts = [p.strip() for p in s.split(",") if p.strip()]
    parts = [re.sub(r"^(?:дни|день)\s+", "", p).strip() for p in parts]
    parts = [p for p in parts if p]
    return ("дни " + ", ".join(parts)) if parts else ""


def build_route_spec(body: str, *, title: str,
                     region_groups: list | None = None) -> dict | None:
    """`## Координаты маршрута` → spec для `render_route_map`.

    Подписи дней для пинов берутся из колонки «Дни» таблицы; если её нет —
    обогащаются из регион-групп 5_vX (по совпадению имени), иначе пусто.
    Подписи компактизируются для карты (A1).
    """
    data = parse_coords_section(body)
    if not data:
        return None
    days_by_name = _days_labels_from_groups(region_groups or [])
    nodes = []
    for i, row in enumerate(data["rows"]):
        days = row["days"] or days_by_name.get(_norm(row["name"]), "")
        nodes.append((row["lon"], row["lat"], row["name"], _compact_days_label(days),
                      _PIN_OFFSETS[i % len(_PIN_OFFSETS)]))
    return {"title": title, "nodes": nodes, "route": data["route"],
            "edges": data["edges"], "context_layers": None}


def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _days_labels_from_groups(region_groups: list) -> dict:
    """{нормализованное имя региона → строка дней} из регион-групп 5_vX."""
    out: dict = {}
    for g in region_groups:
        nums = [d.day_num for d in g.days if d.day_num]
        if not nums:
            continue
        rng = (f"дни {nums[0]}–{nums[-1]}" if len(nums) > 1 else f"день {nums[0]}")
        key = _norm(re.sub(r"\s*\([^)]*\)\s*$", "", g.name))
        if key in out:
            out[key] += f", {rng}"
        else:
            out[key] = rng
    return out


# ===========================================================================
# extract_route_spec — fallback-путь из `гео:`-маркеров дней 5_vX (из прототипа)
# ===========================================================================

_TIME_H_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*ч")
_BOTTLENECK_RE = re.compile(r"узк\w+\s+звен", re.IGNORECASE)


def _edge_from_day(day) -> tuple[str, str]:
    """Подпись+тип ребра ВХОДА в регион из дневного `📍`-переезда (эвристика)."""
    loc = next((m.content for m in day.markers if m.icon == "📍"), "")
    risk = " ".join(m.content for m in day.markers if m.icon in ("⚠️", "⚠"))
    hours = [float(h.replace(",", ".")) for h in _TIME_H_RE.findall(loc)]
    total_h = max(hours) if hours else 0.0
    is_air = bool(_AIR_RE.search(loc))
    is_long = bool(_BOTTLENECK_RE.search(loc + " " + risk)) or total_h >= 6
    kind = "air" if is_air else ("long" if is_long else "normal")
    mode = ("перелёт" if is_air else ("автобус" if "автобус" in loc.lower()
            else ("поезд" if re.search(r"KTX|поезд|train", loc, re.I) else "переезд")))
    time_str = f"~{total_h:g} ч" if total_h else ""
    label = f"{mode} · {time_str}".rstrip(" ·")
    return label, kind


def extract_route_spec(days: list, *, title: str) -> dict | None:
    """Spec ИЗ `гео:`-маркеров регионов 5_vX (fallback, если 6_final без координат).

    None, если регионы дней не несут поля `гео: lat,lon`.
    """
    groups = _s5.group_regions(days)
    if not groups:
        return None
    order_names: list[str] = []
    coord: dict[str, tuple[float, float]] = {}
    days_label: dict[str, str] = {}
    for g in groups:
        geo = g.fields.get("гео") or g.fields.get("geo")
        if not geo:
            return None
        try:
            lat_s, lon_s = (p.strip() for p in geo.split(",")[:2])
            coord.setdefault(g.name, (float(lon_s), float(lat_s)))
        except (ValueError, IndexError):
            return None
        nums = [d.day_num for d in g.days if d.day_num]
        rng = (f"дни {nums[0]}–{nums[-1]}" if len(nums) > 1
               else (f"день {nums[0]}" if nums else ""))
        days_label[g.name] = (days_label.get(g.name) + f", {rng}"
                              if g.name in days_label else rng)
        order_names.append(g.name)
    uniq = list(dict.fromkeys(order_names))
    idx = {name: i for i, name in enumerate(uniq)}
    nodes = [(coord[nm][0], coord[nm][1], nm, _compact_days_label(days_label[nm]),
              _PIN_OFFSETS[i % len(_PIN_OFFSETS)]) for i, nm in enumerate(uniq)]
    route = [idx[nm] for nm in order_names]
    edges = [_edge_from_day(g.days[0]) for g in groups[1:]]
    return {"title": title, "nodes": nodes, "route": route, "edges": edges,
            "context_layers": None}


# ===========================================================================
# Экстрактор `6_final.md`
# ===========================================================================


def extract_content(parsed: dict) -> dict:
    """Распарсенный `6_final.md` → структура для ассемблера.

    Ключи: cover, title, coords_section (body), dossier [{title, body}],
    bookings (body|None), enrichment [{title, body}], extra, frontmatter.
    """
    sections = parsed.get("sections") or []
    fm = parsed.get("frontmatter") or {}
    out: dict[str, Any] = {
        "title": parsed.get("title"),
        "frontmatter": fm,
        "cover": _build_cover(fm),
        "coords_section": None,
        "dossier": [],
        "bookings": None,
        "enrichment": [],
        "extra": [],
    }
    for sec in sections:
        h = (sec.get("heading") or "").strip()
        low = h.lower()
        if low.startswith("координаты"):
            out["coords_section"] = sec["body"]
        elif "досье" in low:
            out["dossier"] = [{"title": ss["heading"], "body": ss["body"]}
                              for ss in sec.get("subsections", [])]
            if not out["dossier"] and sec["body"].strip():
                out["dossier"] = [{"title": "Дорожное досье", "body": sec["body"]}]
        elif low.startswith("брониров"):
            out["bookings"] = sec["body"]
            out["bookings_subsections"] = [
                {"title": ss["heading"], "body": ss["body"]}
                for ss in sec.get("subsections", [])
            ]
        elif low.startswith("углублени") or "enrichment" in low:
            out["enrichment"] = [{"title": ss["heading"], "body": ss["body"]}
                                 for ss in sec.get("subsections", [])]
            if not out["enrichment"] and sec["body"].strip():
                out["enrichment"] = [{"title": h, "body": sec["body"]}]
        else:
            out["extra"].append({"heading": h, "body": sec["body"],
                                 "subsections": sec.get("subsections", [])})
    return out


def _build_cover(fm: dict) -> dict:
    return {
        "trip_id": fm.get("trip_id") or "",
        "created": fm.get("created"),
        "source_plan": fm.get("source_plan"),
        "coords_source_summary": fm.get("coords_source_summary"),
        "travelers_profile": fm.get("travelers_profile"),
        "booking_incorporated": fm.get("booking_incorporated"),
        "enrichment_requested": fm.get("enrichment_requested") or [],
    }


# ===========================================================================
# Ассемблер финального PDF
# ===========================================================================


def _map_title(s5: dict, s6: dict) -> str:
    """Заголовок карты: человекочитаемое гео + «обзорная карта маршрута»."""
    if __package__ in (None, ""):
        from export import cover_common
    else:
        from .. import cover_common
    trip_id = s6["cover"].get("trip_id") or s5["cover"].get("trip_id") or ""
    geo = cover_common.humanize_trip_geo(trip_id)
    return f"{geo}\nобзорная карта маршрута"


# Набор дорожного документа для печатной ветки — один на модуль: карта, текстовые
# фильтры и тело обязаны собираться по одному и тому же drop, иначе разъедутся.
_TRIP_DROP = _s5.TRIP_DROP_PDF


def _build_map_flowables(s5: dict, s6: dict, tmpdir: str, styles,
                         *, soft_break: bool = False) -> list | None:
    """Собрать flowables обзорной карты (плашка + PNG + подпись) или None.

    `soft_break=True` — начинать карту с условного разрыва: если под обложкой
    осталось место, карта садится туда. Обложка дорожного документа после чистки
    занимает верхнюю пятую часть листа, и жёсткий разрыв оставлял её почти
    пустой, а карту — одинокой на следующей странице."""
    if not MATPLOTLIB_AVAILABLE:
        return None
    title = _map_title(s5, s6)
    region_groups = _s5.group_regions(s5.get("days") or [])
    spec = None
    if s6.get("coords_section"):
        spec = build_route_spec(s6["coords_section"], title=title,
                                region_groups=region_groups)
    if not spec:  # fallback: гео:-маркеры 5_vX
        spec = extract_route_spec(s5.get("days") or [], title=title)
    if not spec:
        return None
    countries = load_countries()
    if not countries:
        return None
    base = Path(tmpdir) / "overview"
    try:
        png = render_route_map(spec, countries, str(base))
    except Exception:
        return None
    if not png or not Path(png).exists():
        return None
    return [
        (pdf_lib.cond_page_break(_s5._SECTION_MIN_SPACE_PT) if soft_break
         else pdf_lib.page_break()),
        pdf_lib.section_bar("Обзорная карта маршрута", anchor_slug="overview-map",
                            outline_level=0),
        pdf_lib.spacer(6),
        pdf_lib.map_image(png),
        pdf_lib.spacer(4),
        pdf_lib.para(
            "Пины — порядок остановок; красным выделены узкие звенья переездов, "
            "пунктиром — перелёты. Координаты — ориентир, не для навигации.",
            styles["small"], highlight_todo=False,
        ),
    ]


# Отступ под-секции в видимом TOC (nbsp — не схлопывается reportlab'ом).
_TOC_INDENT = "    "


def _build_appendix_flowables(s6: dict, styles, recipient: str,
                              *, soft_break: bool = False) -> tuple[list, list]:
    """Flowables приложений (досье / бронь / углубления) + записи TOC.

    Каждая H3-под-секция получает якорь + `outline_level=1` (вложена под
    H2-плашку в PDF-outline) и вложенную запись в TOC (с отступом) — чтобы
    под-секции досье/углублений были видны и в «Содержании», и в боковой
    панели закладок.
    """
    flows: list = []
    toc: list[tuple[str, str]] = []

    def _section(title: str, slug: str) -> None:
        # Досье, брони и углубления — такие же секции, как тело плана: разрыв
        # перед ними подчиняется тому же правилу (см. `_SECTION_MIN_SPACE_PT`),
        # иначе приложения снова набирали листы с тремя строками.
        flows.append(pdf_lib.cond_page_break(_s5._SECTION_MIN_SPACE_PT)
                     if soft_break else pdf_lib.page_break())
        flows.append(pdf_lib.section_bar(title, anchor_slug=slug, outline_level=0))
        flows.append(pdf_lib.spacer(4))
        toc.append((title, slug))

    def _subsections(subs: list, slug_prefix: str) -> None:
        for i, sub in enumerate(subs, start=1):
            slug = f"{slug_prefix}-{i}"
            flows.append(pdf_lib.heading_paragraph(
                sub["title"], styles["h3"], anchor_slug=slug, outline_level=1))
            toc.append((_TOC_INDENT + sub["title"], slug))
            # `air=True`: справочное тело досье/углублений рендерится с доп.
            # отбоем (под-заголовок ↔ проза ↔ bullets), чтобы не «сплошняком».
            flows.append(pdf_lib.spacer(2))
            _s5._render_markdown_body(flows, sub["body"], styles, air=True)

    # Дорожное досье.
    if s6.get("dossier"):
        _section("Дорожное досье", "dossier")
        _subsections(s6["dossier"], "dossier")

    # Бронирования (только если есть факты брони).
    if s6.get("bookings") and s6["bookings"].strip():
        _section("Бронирования", "bookings")
        _s5._render_markdown_body(flows, s6["bookings"], styles)
        _subsections(s6.get("bookings_subsections") or [], "bookings")

    # Углубления (enrichment по явному запросу).
    if s6.get("enrichment"):
        _section("Углубления", "enrichment")
        _subsections(s6["enrichment"], "enrichment")

    return flows, toc


def build_pdf(s5_extracted: dict, s6_extracted: dict, output_path: str | Path,
              *, recipient: str = "self") -> str:
    """Собрать финальный «ideal»-PDF: механический рендер 5_vX + карта + приложения.

    Маршрут/дни 5_vX рендерятся билдерами `stage5.build_pdf` БЕЗ повторного
    прогона через LLM (ноль дрейфа); добавки Stage 6 встраиваются через inject.
    """
    if not pdf_lib.REPORTLAB_AVAILABLE:
        raise RuntimeError(
            "Stage 6 PDF требует reportlab. Поставь: "
            "pip install reportlab --break-system-packages"
        )
    styles = pdf_lib.get_styles()
    # Приложения Stage 6 (досье, бронирования, углубления) собираются здесь, до
    # `stage5.build_pdf`, поэтому текстовые фильтры дорожного документа к ним
    # надо применить отдельно — иначе метки TODO и ссылки на стадии выживали
    # ровно в той части, которую читают в поездке чаще всего.
    s6_extracted = _s5.apply_trip_text_filters(s6_extracted, _TRIP_DROP)
    s6cover = s6_extracted["cover"]
    created = s6cover.get("created")
    # Подвал дорожного документа: «финал · создан ДАТА». Имя исходного 5_vX на
    # бумаге не печатаем — это внутренний адрес пайплайна, повторённый на каждой
    # из трёх десятков страниц. Провенанс не теряется: он уходит в метаданные
    # PDF (`subject`), где его видно в свойствах файла и не видно читателю.
    footer_bits = ["финал"]
    if created:
        footer_bits.append(f"создан {created}")
    prov = f"из {s6cover['source_plan']}" if s6cover.get("source_plan") else ""
    inject: dict = {
        "footer": " · ".join(footer_bits),
        "subject": " · ".join(x for x in ("финал", prov, f"создан {created}" if created else "") if x),
        "title": f"Финал — {s6cover.get('trip_id') or s5_extracted['cover'].get('trip_id', '')}",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        map_flowables = _build_map_flowables(
            s5_extracted, s6_extracted, tmpdir, styles,
            soft_break="hard_breaks" in _TRIP_DROP)
        if map_flowables:
            inject["map_flowables"] = map_flowables
            inject["map_toc"] = [("Обзорная карта маршрута", "overview-map")]
        app_flows, app_toc = _build_appendix_flowables(
            s6_extracted, styles, recipient,
            soft_break="hard_breaks" in _TRIP_DROP)
        if app_flows:
            inject["appendix_flowables"] = app_flows
            inject["appendix_toc"] = app_toc
        # PNG читается reportlab'ом во время build_doc — он внутри stage5.build_pdf,
        # т.е. в пределах этого `with` (tmpdir ещё жив).
        # Печатный дорожный документ: планировочная кухня плюс TODO/чеклист —
        # на бумаге отметки не поставить, там они мёртвый груз (в HTML,
        # наоборот, остаются: см. stage5.TRIP_DROP_HTML).
        return _s5.build_pdf(s5_extracted, output_path, recipient=recipient,
                             drop=_TRIP_DROP,
                             inject=inject)


# ===========================================================================
# Entry-point + регистрация
# ===========================================================================


def _load_source_plan(parsed: dict, source_file: str | Path | None) -> dict | None:
    """Найти и распарсить устаканенный 5_vX по `source_plan` из YAML 6_final.

    Приоритет: явный `source_plan` рядом с 6_final → glob `5_*_v*.md` (latest)
    в той же папке → None.
    """
    fm = parsed.get("frontmatter") or {}
    src_dir = Path(source_file).parent if source_file else None
    src_plan = fm.get("source_plan")
    candidates: list[Path] = []
    declared_missing = False
    if src_dir:
        if src_plan:
            p = src_dir / str(src_plan)
            if p.exists():
                candidates.append(p)
            else:
                # Объявленного плана нет — НЕ подставляем соседний по glob'у.
                # На обложку печатается `source_plan` из YAML, а не имя файла,
                # который реально отрендерили: подмена дала бы документ, врущий
                # о собственном происхождении («собран из v9», а внутри v2).
                declared_missing = True
        if not candidates and not declared_missing:
            globbed = sorted(src_dir.glob("5_*_v*.md")) or sorted(src_dir.glob("5_*.md"))
            globbed = [g for g in globbed if not g.stem.endswith("_export")]
            if globbed:
                candidates.append(max(globbed, key=_plan_version))
    if not candidates:
        # Не просто None: вызывающий по нему не отличит «нет 5_vX вовсе» от
        # «указан не тот файл», и человек получит одинаковое «требуется 5_vX».
        # Кладём в parsed отчёт о поиске — из него строится внятная просьба.
        parsed["_source_plan_miss"] = {
            "declared": str(src_plan) if src_plan else None,
            "looked_in": str(src_dir) if src_dir else None,
            "seen": sorted(p.name for p in src_dir.glob("5_*.md")) if src_dir else [],
        }
        return None
    return _parser.parse_stage_file(candidates[0])


def source_plan_request(parsed: dict) -> str:
    """Текст просьбы о недостающем 5_vX — с тем, что именно искали и что нашли.

    Stage 6 механически наследует тело плана, поэтому без 5_vX он не деградирует,
    а не собирается вовсе. Сообщение обязано говорить, какой файл принести.
    """
    miss = parsed.get("_source_plan_miss") or {}
    declared, where, seen = miss.get("declared"), miss.get("looked_in"), miss.get("seen") or []
    out = ["Stage 6 нечего рендерить: не найден устаканенный план 5_vX."]
    if declared:
        out.append(f"В YAML 6_final.md указан `source_plan: {declared}`, "
                   f"но такого файла рядом нет.")
    else:
        out.append("В YAML 6_final.md не заполнено поле `source_plan`.")
    if where:
        out.append(f"Искали в: {where}")
    out.append("Рядом лежат: " + (", ".join(seen) if seen else "ни одного 5_*.md"))
    out.append("Нужно: положить файл плана в эту папку и указать его имя в "
               "`source_plan`, либо передать путь явно через --input/source_file.")
    return "\n".join(out)


def _plan_version(path: Path) -> int:
    m = re.search(r"_v(\d+)\.md$", path.name)
    return int(m.group(1)) if m else 0


def render_stage6(
    parsed: dict,
    *,
    recipient: str = "self",
    output_path: str | Path,
    source_file: str | Path | None = None,
    **_kw: Any,
) -> "_renderer.RenderRequest":
    """Entry-point Stage 6: 6_final.md (+ устаканенный 5_vX) → финальный PDF.

    `parsed` — распарсенный `6_final.md`. 5_vX резолвится из YAML `source_plan`
    рядом с 6_final (immutable, читается, не правится). Контент 5_vX рендерится
    механически; добавки Stage 6 — поверх (карта/досье/бронь/углубления).
    """
    s6 = extract_content(parsed)
    s5_parsed = _load_source_plan(parsed, source_file)
    if s5_parsed is None:
        raise FileNotFoundError(source_plan_request(parsed))
    s5_parsed = _adapter.adapt_for_recipient(s5_parsed, recipient)
    s5 = _s5.extract_content(s5_parsed, input_path=[source_file, output_path])
    pdf_path = build_pdf(s5, s6, output_path, recipient=recipient)
    return _renderer.RenderRequest(
        format="pdf",
        output_path=pdf_path,
        content={
            "stage": "6_final",
            "trip_id": parsed.get("trip_id"),
            "recipient": recipient,
            "source_plan": s6["cover"].get("source_plan"),
            "days_count": len(s5.get("days") or []),
            "dossier_sections": len(s6.get("dossier") or []),
            "has_map": bool(MATPLOTLIB_AVAILABLE and s6.get("coords_section")),
            "bookings": bool(s6.get("bookings")),
            "enrichment_sections": len(s6.get("enrichment") or []),
        },
        metadata={
            "trip_id": parsed.get("trip_id"),
            "stage": parsed.get("stage"),
            "recipient": recipient,
            "font_family": pdf_lib._ACTIVE_FAMILY,
        },
        notes=[],
    )


# Регистрация — на import-time модуля.
_renderer.register_renderer("6_final", "pdf", render_stage6)
