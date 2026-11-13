#!/usr/bin/env python3
"""Прототип ОБЗОРНОЙ карты маршрута — УНИВЕРСАЛЬНЫЙ рендерер + экстрактор.

Цель — оценить читабельность географической стилизованной карты и заложить
архитектуру, которая НЕ переписывается под каждый план. Это dev-эксперимент
(не часть скилла), гео-контур тянется из Natural Earth.

Два слоя — и ни в одном нет пер-трип хардкода логики:
  • render_route_map(spec, ...) — УНИВЕРСАЛЬНЫЙ рендерер. Принимает чистые
    данные маршрута (узлы с координатами + порядок + подписи рёбер). Рамка
    (bbox), страна для заливки (point-in-polygon по координатам) и поправка на
    широту вычисляются АВТОМАТИЧЕСКИ. Никаких «если Страна Б — то…».
  • extract_route_spec(days) — PRODUCTION-путь: строит spec ИЗ артефакта плана
    (порядок узлов из маркеров `[[регион:]]`, координаты из поля `гео:`, рёбра
    из дневных `📍`-переездов, тип ребра по ключевым словам). Активируется,
    когда polish начнёт эмитить `гео:` (TODO #7). Это и делает скрипт
    неперезаписываемым: новый план → новый spec без правки кода.

FIXTURES ниже — throwaway тест-данные для оценки читабельности (сырые фикстуры
ещё без `гео:`-маркеров, поэтому маршрут задан вручную). В проде их роль играет
extract_route_spec.

Запуск:
    curl -s -o /tmp/ne50_countries.geojson \\
      https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson
    ~/.pyenv/versions/3.12.9/bin/python3 overview_map_prototype.py        # фикстуры
    ~/.pyenv/versions/3.12.9/bin/python3 overview_map_prototype.py --selftest-extractor
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyArrowPatch

_SKILL = Path(__file__).resolve().parents[3] / "skills" / "travel-planning" / "scripts" / "export"
sys.path.insert(0, str(_SKILL.parent))
from export.style import COLORS, REGION_PALETTE  # noqa: E402

GEOJSON = Path("/tmp/ne50_countries.geojson")
plt.rcParams["font.family"] = "DejaVu Sans"

EDGE_STYLE = {
    "normal": dict(color=COLORS["primary"], lw=1.5, ls="solid"),
    "long":   dict(color=COLORS["danger"],  lw=2.3, ls="solid"),  # «узкое звено»
    "air":    dict(color=COLORS["primary"], lw=1.4, ls=(0, (5, 3))),  # перелёт
}
RAD = 0.22  # кривизна дуги (петля не пересекается прямыми)


# ─── Геометрия (универсально, без привязки к стране) ───────────────────────

def _polys(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    return [poly[0] for poly in geom["coordinates"]]


def load_countries():
    if not GEOJSON.exists():
        sys.exit(f"нет {GEOJSON} — скачай ne_50m_admin_0_countries.geojson (см. docstring)")
    data = json.load(open(GEOJSON))
    return {(f["properties"].get("NAME") or f["properties"].get("ADMIN")): _polys(f["geometry"])
            for f in data["features"]}


def _point_in_ring(x, y, ring):
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


def _fill_countries(nodes, countries):
    """Авто-определение стран для заливки: те, что содержат узлы маршрута."""
    out = set()
    for lon, lat, *_ in nodes:
        for name, rings in countries.items():
            if any(_point_in_ring(lon, lat, r) for r in rings):
                out.add(name)
                break
    return out


def _auto_bbox(nodes):
    """Рамка из координат узлов + поля (доля размаха, с минимумом)."""
    lons = [n[0] for n in nodes]
    lats = [n[1] for n in nodes]
    span_lon, span_lat = max(lons) - min(lons), max(lats) - min(lats)
    pad_lon = max(0.4, 0.18 * span_lon)
    pad_lat = max(0.4, 0.18 * span_lat)
    return dict(lon_min=min(lons) - pad_lon, lon_max=max(lons) + pad_lon,
                lat_min=min(lats) - pad_lat, lat_max=max(lats) + pad_lat)


# ─── Универсальный рендерер ────────────────────────────────────────────────

def render_route_map(spec, countries, out_base):
    """Отрисовать обзорную карту из чистого spec. Универсально, без пер-трип кода.

    spec: {
      "title": str,
      "nodes": [(lon, lat, name, days_label, (dx, dy)), ...],
      "route": [индексы в nodes по порядку посещения; повтор = старт==финиш],
      "edges": [(label, kind in {normal,long,air}), ...]  # len == len(route)-1
      "context_layers": [...] | None  # опц. ручной гео-контекст (река/хребет)
    }
    Пишет out_base.png (голый) и out_base.pdf (голый + страница с контекстом,
    если context_layers заданы).
    """
    bbox = _auto_bbox(spec["nodes"])
    fill = _fill_countries(spec["nodes"], countries)

    def _draw(ax, with_ctx):
        ax.set_xlim(bbox["lon_min"], bbox["lon_max"])
        ax.set_ylim(bbox["lat_min"], bbox["lat_max"])
        midlat = (bbox["lat_min"] + bbox["lat_max"]) / 2
        ax.set_aspect(1 / math.cos(math.radians(midlat)))  # авто поправка широты
        ax.axis("off")
        title = spec["title"] + (" + гео-контекст" if with_ctx else "")
        ax.set_title(title, fontsize=15, color=COLORS["primary"],
                     fontweight="bold", pad=14)
        # База: соседи бледно, страна(ы) маршрута — лёгкая заливка + navy-контур.
        for name, rings in countries.items():
            if name in fill:
                continue
            for ring in rings:
                xs, ys = zip(*ring)
                ax.fill(xs, ys, color="#f2f2f0", zorder=0)
                ax.plot(xs, ys, color="#cfcfcf", lw=0.6, zorder=1)
        for name in fill:
            for ring in countries.get(name, []):
                xs, ys = zip(*ring)
                ax.fill(xs, ys, color="#e9eef4", zorder=2)
                ax.plot(xs, ys, color=COLORS["primary"], lw=1.1, zorder=3)
        if with_ctx:
            _draw_context(ax, spec.get("context_layers") or [])
        _draw_route(ax, spec)

    fig, ax = plt.subplots(figsize=(7.6, 9.0))
    fig.patch.set_facecolor(COLORS["background"])
    _draw(ax, with_ctx=False)
    fig.savefig(f"{out_base}.png", dpi=150, bbox_inches="tight",
                facecolor=COLORS["background"])
    plt.close(fig)

    pages = [False, True] if spec.get("context_layers") else [False]
    with PdfPages(f"{out_base}.pdf") as pdf:
        for with_ctx in pages:
            fig, ax = plt.subplots(figsize=(7.6, 9.0))
            fig.patch.set_facecolor(COLORS["background"])
            _draw(ax, with_ctx)
            pdf.savefig(fig, facecolor=COLORS["background"])
            plt.close(fig)


def _draw_route(ax, spec):
    nodes, route, edges = spec["nodes"], spec["route"], spec["edges"]
    pts = [(nodes[i][0], nodes[i][1]) for i in route]
    for k in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[k], pts[k + 1]
        label, kind = edges[k]
        st = EDGE_STYLE.get(kind, EDGE_STYLE["normal"])
        ax.add_patch(FancyArrowPatch(
            (x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=12,
            connectionstyle=f"arc3,rad={RAD}", lw=st["lw"], color=st["color"],
            linestyle=st["ls"], alpha=0.9, shrinkA=10, shrinkB=10, zorder=5))
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        dx, dy = x1 - x0, y1 - y0
        nlen = math.hypot(dx, dy) or 1.0
        px, py = -dy / nlen, dx / nlen
        off = RAD * 0.5 * nlen
        ax.text(mx + px * off, my + py * off, label, fontsize=7.3,
                color=st["color"], zorder=7, ha="center", va="center",
                bbox=dict(boxstyle="round,pad=0.25", fc="white",
                          ec=st["color"], alpha=0.92, lw=0.6))
    drawn = set()
    for i in route:
        if i in drawn:
            continue
        drawn.add(i)
        lon, lat, name, days, off = nodes[i]
        num = route.index(i) + 1
        col = REGION_PALETTE[i % len(REGION_PALETTE)]
        ax.scatter([lon], [lat], s=260, color=col, edgecolor="white",
                   linewidth=1.5, zorder=8)
        ax.text(lon, lat, str(num), fontsize=9, color="white",
                fontweight="bold", ha="center", va="center", zorder=9)
        ax.annotate(f"{name}\n{days}", (lon, lat), textcoords="offset points",
                    xytext=off, fontsize=8.5, color=COLORS["text"], zorder=9,
                    ha="left" if off[0] >= 0 else "right", fontweight="bold")


def _draw_context(ax, layers):
    """Ручной гео-контекст (река/хребет): generic список полилиний с подписями."""
    for ly in layers:
        xs, ys = zip(*ly["points"])
        ax.plot(xs, ys, color=ly["color"], lw=ly.get("lw", 2.0),
                alpha=ly.get("alpha", 0.7), zorder=ly.get("zorder", 4),
                solid_capstyle="round")
        if ly.get("label"):
            lx, ly_ = ly.get("label_at", ly["points"][0])
            ax.text(lx, ly_, ly["label"], fontsize=7.5, color=ly["color"],
                    style="italic", zorder=7,
                    ha=ly.get("label_ha", "left"))


# ─── PRODUCTION-путь: extract_route_spec (из артефакта плана) ───────────────

_TIME_H_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*ч")
_AIR_RE = re.compile(r"перел[её]т|самол[её]т|рейс|flight|AREX|авиа", re.IGNORECASE)
_BOTTLENECK_RE = re.compile(r"узк\w+\s+звен", re.IGNORECASE)


def _edge_from_day(day) -> tuple[str, str]:
    """Подпись+тип ребра ВХОДА в регион из дневного `📍`-переезда.

    Полностью эвристика по контенту (универсально, без привязки к стране):
      • время — макс. число часов в строке;
      • air — есть «перелёт/рейс/AREX/…»;
      • long — «узкое звено» в дне ИЛИ суммарное время ≥ 6 ч;
      • label — короткая выжимка (режим + время).
    """
    loc = next((m.content for m in day.markers if m.icon == "📍"), "")
    risk = " ".join(m.content for m in day.markers if m.icon in ("⚠️", "⚠"))
    hours = [float(h.replace(",", ".")) for h in _TIME_H_RE.findall(loc)]
    total_h = max(hours) if hours else 0.0
    is_air = bool(_AIR_RE.search(loc))
    is_long = bool(_BOTTLENECK_RE.search(loc + " " + risk)) or total_h >= 6
    kind = "air" if is_air else ("long" if is_long else "normal")
    # Режим: первое значимое слово после стрелки/двоеточия (грубо).
    mode = "перелёт" if is_air else ("автобус" if "автобус" in loc.lower()
            else ("поезд" if re.search(r"KTX|поезд|train", loc, re.I) else "переезд"))
    time_str = f"~{total_h:g} ч" if total_h else ""
    suffix = "  (узкое звено)" if (is_long and not is_air and _BOTTLENECK_RE.search(loc + risk)) else ""
    label = f"{mode} · {time_str}".rstrip(" ·") + suffix
    return label, kind


def extract_route_spec(days, *, title: str) -> dict | None:
    """Построить spec ИЗ артефакта (universal). Возвращает None, если в маркерах
    регионов нет поля `гео:` (тогда карту не строим — нужен TODO #7).

    Источник всего: `days` (список DayBlock из stage5.extract_content):
      • узлы и порядок — из последовательности регионов (`[[регион:]]`),
        старт==финиш если регион повторяется (как Сеул/Ханой);
      • координаты — из поля `гео: lat,lon` маркера региона;
      • рёбра — из дневного `📍`-переезда ВХОДА в следующий регион.
    """
    if _SKILL.name:  # импорт group_regions из stage5 (reuse, без дублирования)
        from export.stages import stage5 as _s5
    groups = _s5.group_regions(days)
    if not groups:
        return None
    # Уникальные узлы по имени (повтор региона → один пин + петля).
    order_names: list[str] = []
    coord: dict[str, tuple[float, float]] = {}
    days_label: dict[str, str] = {}
    for g in groups:
        geo = g.fields.get("гео") or g.fields.get("geo")
        if not geo:
            return None  # нет координат → карту не строим (нужен `гео:`-маркер)
        lat_s, lon_s = (p.strip() for p in geo.split(",")[:2])
        coord.setdefault(g.name, (float(lon_s), float(lat_s)))
        nums = [d.day_num for d in g.days if d.day_num]
        rng = (f"дни {nums[0]}–{nums[-1]}" if len(nums) > 1 else
               (f"день {nums[0]}" if nums else ""))
        if g.name in days_label:
            days_label[g.name] += f", {rng}"
        else:
            days_label[g.name] = rng
        order_names.append(g.name)
    uniq = list(dict.fromkeys(order_names))
    idx = {name: i for i, name in enumerate(uniq)}
    nodes = [(coord[n][0], coord[n][1], n, days_label[n], (8, 4)) for n in uniq]
    route = [idx[n] for n in order_names]
    # Ребро входа в каждый следующий регион — из его дня-входа.
    edges = []
    for g in groups[1:]:
        edges.append(_edge_from_day(g.days[0]))
    return {"title": title, "nodes": nodes, "route": route, "edges": edges,
            "context_layers": None}


# ─── FIXTURES — throwaway тест-данные (в проде их роль: extract_route_spec) ──
# Сырые фикстуры ещё без `гео:`-маркеров, поэтому маршрут задан вручную ТОЛЬКО
# здесь. Логика рендера их не знает.

_VN_CONTEXT = [
    {"points": [(103.95, 22.50), (104.30, 22.20), (104.90, 21.55),
                (105.40, 21.30), (105.85, 21.03), (106.30, 20.60)],
     "color": "#3b6ea5", "lw": 2.0, "alpha": 0.7,
     "label": "Красная река", "label_at": (104.30, 22.28)},
    {"points": [(103.55, 22.60), (103.80, 22.25), (104.05, 21.95), (104.30, 21.60)],
     "color": "#8a6d3b", "lw": 7, "alpha": 0.30, "zorder": 2,
     "label": "хр. Хоанглиенсон", "label_at": (103.50, 22.65), "label_ha": "right"},
]

FIXTURES = {
    "vietnam": {
        "title": "Северный Страна Б · сентябрь 2026\nобзорная карта маршрута",
        "nodes": [
            (105.85, 21.03, "Ханой",      "дни 1–3, 11", (6, 6)),
            (105.97, 20.23, "Ниньбинь",   "дни 4–5",     (8, -4)),
            (103.84, 22.34, "Сапа",       "дни 6–8",     (-10, 6)),
            (104.05, 21.88, "Мукангчай",  "дни 9–10",    (8, -10)),
        ],
        "route": [0, 1, 2, 3, 0],
        "edges": [("лимузин · 2 ч", "normal"), ("лимузин · 7,5–8 ч", "long"),
                  ("частная машина · 4,5–5 ч", "normal"), ("автобус · 7–8 ч", "long")],
        "context_layers": _VN_CONTEXT,
    },
    "argentina": {
        "title": "Южная Страна В · март 2025\nобзорная карта маршрута",
        # БА — шлюз страны (прилёт → внутр. перелёт в Ушуаю день 1; финал дни 12–13).
        "nodes": [
            (-68.30, -54.80, "Ушуая",         "дни 1–3",            (8, -6)),
            (-72.28, -50.34, "Эль-Калафате",  "дни 4–7",            (-10, -10)),
            (-72.89, -49.33, "Эль-Чальтен",   "дни 8–11",           (-10, 6)),
            (-58.38, -34.61, "Буэнос-Айрес",  "прилёт + дни 12–13", (8, 0)),
        ],
        "route": [3, 0, 1, 2, 3],
        "edges": [("перелёт · ~3 ч 40  (прилёт)", "air"), ("перелёт · ~1 ч 20", "air"),
                  ("автобус · ~3 ч", "normal"),
                  ("перелёт (через Эль-Калафате) · ~5–6 ч", "air")],
        "context_layers": None,
    },
    "korea": {
        "title": "Южная Страна А · март–апрель 2024\nобзорная карта маршрута",
        "nodes": [
            (126.98, 37.57, "Сеул",              "дни 1–2, 16–18", (8, 5)),
            (128.59, 38.21, "Сокчхо / Сораксан", "дни 3–5",        (8, 5)),
            (129.22, 35.86, "Кёнджу",            "дни 6–8",        (8, 2)),
            (129.08, 35.18, "Пусан",             "дни 9–12",       (8, -6)),
            (127.15, 35.82, "Чонджу",            "дни 13–15",      (-10, 0)),
        ],
        "route": [0, 1, 2, 3, 4, 0],
        "edges": [("автобус · ~2 ч 20", "normal"),
                  ("автобус, 2–3 пересадки · ~6,5–7,5 ч  (узкое звено)", "long"),
                  ("KTX · ~30 мин", "normal"), ("автобус · ~3 ч", "normal"),
                  ("KTX · ~2 ч", "normal")],
        "context_layers": None,
    },
}


def _selftest_extractor():
    """Доказать универсальность: синтетический артефакт с `гео:`-маркерами →
    extract_route_spec → готовый spec, БЕЗ единой строки пер-трип кода."""
    from export.stages import stage5 as _s5
    secs = [
        {"heading": "День 1 (01.05 Пн). Старт", "subsections": [], "level": 3,
         "body": "[[регион: Алион | гео: 10.0,20.0]]\n📍 Прилёт в Алион.\n💰 ~1 000 ₽"},
        {"heading": "День 2 (02.05 Вт). Переезд", "subsections": [], "level": 3,
         "body": "[[регион: Бевен | гео: 12.0,22.5]]\n📍 Алион → Бевен: автобус ~7 ч.\n"
                 "⚠️ Узкое звено: редкие стыковки."},
        {"heading": "День 3 (03.05 Ср). Возврат", "subsections": [], "level": 3,
         "body": "[[регион: Алион | гео: 10.0,20.0]]\n📍 Бевен → Алион: перелёт ~1 ч."},
    ]
    days = [_s5.parse_day_block(s) for s in secs]
    spec = extract_route_spec(days, title="Самотест")
    assert spec, "spec не построен"
    assert [n[2] for n in spec["nodes"]] == ["Алион", "Бевен"], spec["nodes"]
    assert spec["route"] == [0, 1, 0], spec["route"]
    assert spec["edges"][0][1] == "long" and "узкое" in spec["edges"][0][0], spec["edges"]
    assert spec["edges"][1][1] == "air", spec["edges"]
    print("selftest extract_route_spec: OK —", spec["route"], spec["edges"])


def main():
    if "--selftest-extractor" in sys.argv:
        _selftest_extractor()
        return
    countries = load_countries()
    out_dir = Path(__file__).resolve().parent
    for slug, spec in FIXTURES.items():
        render_route_map(spec, countries, str(out_dir / f"overview_{slug}"))
        print(f"OK: overview_{slug}.pdf / .png")


if __name__ == "__main__":
    main()
