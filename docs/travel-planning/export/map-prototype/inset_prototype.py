"""Standalone-прототип Level-2 регионального инсета (SYS-3 + G6).

НЕ часть скилла — dev-прототип для валидации концепта (как
`overview_map_prototype.py` для обзорной карты). Запуск:
    python3 inset_prototype.py   →  inset_prototype.png

Кейс — Сапа / долина Мыонг Хоа (maps-spec §2.3). Координаты POI — Tier-2
приближения (ОРИЕНТИР, не навигация): газетир уровень деревень не покрывает.

Что прототип проверяет: читается ли топологический инсет на ПУСТОМ фоне
(подложки нет — Natural Earth уровень страны, тайлы спека запрещает). Вывод
(2026-06-06): топология читается (трек на ЮВ, выезд к перевалу на СЗ — два
разных вектора от базы), НО подписи на плотности инсета наезжают сильнее, чем
на обзорной карте → при встройке переиспользовать `stage6._label_placements`.
Полный разбор и решение «отложить» — `../sys3-g6-inset-assessment.md`.
"""
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

NAVY = "#1f3a5f"; SAND = "#b9842b"; RED = "#b3402a"; TEXT = "#222222"; BG = "#fbfbf9"
plt.rcParams["font.family"] = "DejaVu Sans"

# (name, lon, lat, kind, note)  kind: base | trek | side | cluster
P = [
    ("Центр Сапы", 103.844, 22.336, "base", "Notre Dame, музей"),
    ("Sapa Clay House", 103.875, 22.315, "base", "база ночей · ~5 км"),
    ("Y Linh Hồ", 103.882, 22.305, "trek", "старт трека"),
    ("Lao Chải", 103.900, 22.300, "trek", "деревня трека"),
    ("Tả Van", 103.912, 22.292, "trek", "финал трека · ночёвка"),
    ("Trạm Tôn / O Quy Hồ", 103.776, 22.353, "side", "перевал · ~12 км"),
    ("Thác Bạc", 103.790, 22.350, "cluster", "водопад · одним выездом"),
]
idx = {p[0]: i for i, p in enumerate(P)}
trek = ["Y Linh Hồ", "Lao Chải", "Tả Van"]


def main() -> None:
    fig, ax = plt.subplots(figsize=(7.0, 7.4))
    fig.patch.set_facecolor(BG); ax.set_facecolor(BG)
    lons = [p[1] for p in P]; lats = [p[2] for p in P]
    mlat = sum(lats) / len(lats)
    padx = (max(lons) - min(lons)) * 0.18 + 0.01
    pady = (max(lats) - min(lats)) * 0.18 + 0.01
    ax.set_xlim(min(lons) - padx, max(lons) + padx)
    ax.set_ylim(min(lats) - pady, max(lats) + pady)
    ax.set_aspect(1 / math.cos(math.radians(mlat)))
    ax.axis("off")
    ax.set_title("Инсет: Сапа / долина Мыонг Хоа", fontsize=14,
                 color=NAVY, fontweight="bold", pad=12)

    # схематическая ось трека (пунктир-цепочка)
    tx = [P[idx[n]][1] for n in trek]; ty = [P[idx[n]][2] for n in trek]
    ax.plot(tx, ty, color=SAND, lw=2.4, ls=(0, (4, 2)), zorder=4,
            solid_capstyle="round")
    ax.text(sum(tx) / 3, sum(ty) / 3 - 0.006, "трек дня", color=SAND,
            fontsize=8.5, fontstyle="italic", ha="center", zorder=6)

    # стрелка-направление к перевалу (другой вектор от базы)
    bx, by = P[idx["Sapa Clay House"]][1], P[idx["Sapa Clay House"]][2]
    px, py = P[idx["Trạm Tôn / O Quy Hồ"]][1], P[idx["Trạm Tôn / O Quy Hồ"]][2]
    ax.add_patch(FancyArrowPatch(
        (bx, by), (px, py), arrowstyle="-|>", mutation_scale=14, color=RED,
        lw=1.6, ls=(0, (2, 2)), alpha=0.8, shrinkA=14, shrinkB=16, zorder=3))
    ax.text((bx + px) / 2 + 0.004, (by + py) / 2 + 0.006,
            "отдельный выезд\n(QL4D на Лай Чау)", color=RED, fontsize=8,
            ha="center", zorder=6)

    col = {"base": NAVY, "trek": SAND, "side": RED, "cluster": "#7a5fa0"}
    off = {"Центр Сапы": (-9, 7), "Sapa Clay House": (10, -2),
           "Y Linh Hồ": (9, 4), "Lao Chải": (9, 2), "Tả Van": (9, -2),
           "Trạm Tôn / O Quy Hồ": (-9, 8), "Thác Bạc": (-9, -8)}
    for name, lon, lat, kind, note in P:
        ax.scatter([lon], [lat], s=170, color=col[kind], edgecolor="white",
                   lw=1.4, zorder=8)
        dx, dy = off[name]
        ax.annotate(f"{name}\n{note}", (lon, lat), textcoords="offset points",
                    xytext=(dx, dy), fontsize=8, color=TEXT, fontweight="bold",
                    zorder=9, ha="left" if dx >= 0 else "right",
                    va="bottom" if dy >= 0 else "top",
                    arrowprops=dict(arrowstyle="-", lw=0.5, color="#9a9a9a",
                                    shrinkA=2, shrinkB=2))

    fig.savefig("inset_prototype.png", dpi=150, bbox_inches="tight",
                facecolor=BG)
    print("ok inset_prototype.png")


if __name__ == "__main__":
    main()
