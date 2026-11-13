#!/usr/bin/env python3
"""Навигация раздела (ui-kit 1.23.0: .ui-rail / .ui-mnav) — прогон НАСТОЯЩИМИ
браузерами Chromium и WebKit на games, health, food и «Деньгах».

Почему: до 1.23.0 у каждой страницы была своя навигация — рельс 212/232/236px,
нижняя панель с 760/820/860px, слои 60/70/80, и только «Еда» знала лечение
iPhone: пересоздаваемая при перерисовке fixed-панель дорисовывалась посреди
экрана. Решение владельца 2026-10-06: iPad портретом — нижняя панель, лёжа —
рельс; ширина рельса одна и задана в одном месте.

Что проверяется (7 экранов: компьютер, iPad лёжа ×2, iPad портретом ×2,
iPhone стоя и лёжа):
  1. на экране ровно одна форма навигации: рельс (компьютер, iPad лёжа) или
     нижняя панель (телефон в любом положении, iPad портретом);
  2. ширина рельса одна на все страницы (--ui-rail-w);
  3. нижняя панель одна, в <body>, слой 65, свой слой композитора;
  4. подсветка: ровно один активный пункт, в рельсе и панели — один и тот же;
  5. переход по пункту меняет подсветку, а панель НЕ пересоздаётся (тот же
     узел и те же кнопки — лечение iOS);
  6. контенту хватает места снизу: панель не закрывает конец страницы;
  7. «Еда»: на экране рецепта подсвечены «Рецепты»;
  8. ошибок JS нет.

Данные — стенды test_select_layout (health, food) и test_money_layout (их
подготовка, без их проверок); Synology не нужен.

Запуск:
    python3 tools/tests/test_nav_layout.py
Требует playwright; движок, которого нет, — честный пропуск, не падение.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _pages_stand import Checker, fixture, per_engine, settle  # noqa: E402

check = Checker()


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("nav_layout: пропуск — нет playwright")
    sys.exit(0)


SEL = fixture("test_select_layout.py", "\n# ── запуск ──")
MON = fixture("test_money_layout.py", "\nwith sync_playwright() as p:")
TOOLS = SEL["URL"].rsplit("/", 1)[0] + "/"

VIEWPORTS = [  # (имя, ширина, высота, ожидаемая форма)
    ("компьютер", 1280, 800, "rail"),
    ("iPad лёжа", 1180, 820, "rail"),
    ("старый iPad лёжа", 1024, 768, "rail"),
    ("iPad портретом", 820, 1180, "mnav"),
    ("iPad Pro 12.9 портретом", 1024, 1366, "mnav"),
    ("iPhone", 390, 844, "mnav"),
    ("iPhone лёжа", 932, 430, "mnav"),
]

STATE = """() => {
  const rail = document.querySelector('.ui-rail'), navs = document.querySelectorAll('.ui-mnav');
  const nav = navs[0], vis = (e) => !!e && e.offsetWidth > 0 && getComputedStyle(e).display !== 'none';
  const on = (sel) => [...document.querySelectorAll(sel + ' [data-ui-nav].on')].map(b => b.getAttribute('data-ui-nav'));
  const shell = document.querySelector('.ui-shell') || document.querySelector('.ui-main');
  return { rail: vis(rail), railW: rail ? Math.round(rail.getBoundingClientRect().width) : null,
           mnav: vis(nav), navs: navs.length, inBody: !!nav && nav.parentElement === document.body,
           z: nav ? getComputedStyle(nav).zIndex : null, tz: nav ? getComputedStyle(nav).transform : null,
           navH: nav ? Math.round(nav.getBoundingClientRect().height) : 0,
           padB: shell ? parseFloat(getComputedStyle(shell).paddingBottom) : 0,
           onRail: on('.ui-rail'), onNav: on('.ui-mnav') };
}"""

PAGES = {  # страница → (url, подготовка страницы, ключ пункта для перехода)
    "games": (TOOLS + "games.html", None, "library"),
    "health": (SEL["URL"], "health", "meds"),
    "food": (SEL["FOOD"], None, "recipes"),
    "money": (MON["URL"], "money", "spend"),
}


def run(eng_name, browser):
    vps = VIEWPORTS if eng_name == "chromium" else [v for v in VIEWPORTS if v[0] in WEBKIT_VPS]
    rail_ws = {}
    for vname, w, h, form in vps:
        for page, (url, prep, target) in PAGES.items():
            tag = f"{eng_name} {vname} ({w}×{h}) {page}"
            ctx = browser.new_context(viewport={"width": w, "height": h}, has_touch=form == "mnav" and w < 1000)
            ctx.add_init_script("localStorage.setItem('hub-auth','dGVzdDp0ZXN0'); localStorage.setItem('money-tab','overview');")
            pg = ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
            if prep == "health":
                SEL["wire"](pg, [])
            pg.goto(url)
            settle(pg, "!!document.querySelector('#ui-mnav [data-ui-nav].on')")
            st = pg.evaluate(STATE)
            check(f"{tag}: форма навигации — {'рельс' if form == 'rail' else 'нижняя панель'} (рельс {st['rail']}, панель {st['mnav']})",
                  st["rail"] == (form == "rail") and st["mnav"] == (form == "mnav") if page != "money"
                  else st["mnav"] == (form == "mnav"))
            check(f"{tag}: панель одна, в <body>, слой 65, свой слой композитора ({st['navs']}, {st['z']}, {st['tz']})",
                  st["navs"] == 1 and st["inBody"] and st["z"] == "65"
                  and (not st["mnav"] or st["tz"] not in (None, "none")))   # у скрытой transform не вычисляется
            if st["rail"]:
                rail_ws[page] = st["railW"]
            if form == "mnav":
                check(f"{tag}: контенту хватает места под панелью (отступ {st['padB']} ≥ панель {st['navH']})",
                      st["padB"] >= st["navH"])
            check(f"{tag}: один активный пункт, в рельсе и панели — один и тот же ({st['onRail']}, {st['onNav']})",
                  len(st["onNav"]) == 1 and (not st["onRail"] or st["onRail"] == st["onNav"]))
            # переход: панель не пересоздаётся
            pg.evaluate("() => { const n = document.getElementById('ui-mnav'); window.__nav = n;"
                        " window.__btn = n.querySelector('button'); window.__btn.__mark = 1; }")
            if st["mnav"]:
                pg.locator(f'.ui-mnav [data-ui-nav="{target}"]').click()
            elif st["rail"]:
                pg.locator(f'.ui-rail [data-ui-nav="{target}"]').click()
            else:   # «Деньги» на широком экране: рельса нет, вкладки сверху
                pg.locator(f'.ui-seg-btn[data-v="{target}"]').first.click()
            # ждём подсветку нового пункта; запас 300 мс — поздняя перерисовка успела бы пересоздать панель
            settle(pg, f"!!document.querySelector('#ui-mnav [data-ui-nav=\"{target}\"].on')", margin=300)
            st2 = pg.evaluate(STATE)
            same = pg.evaluate("() => document.getElementById('ui-mnav') === window.__nav"
                               " && document.querySelector('#ui-mnav button') === window.__btn && window.__btn.__mark === 1")
            check(f"{tag}: переход на «{target}» — подсветка переехала ({st2['onNav']})",
                  st2["onNav"] == [target] and (not st2["onRail"] or st2["onRail"] == [target]))
            check(f"{tag}: нижняя панель не пересоздана перерисовкой (iOS)", same)
            if page == "food" and form == "mnav" and vname == "iPhone":
                pg.goto(SEL["FOOD"] + "?recipe=test")
                settle(pg, "!!document.querySelector('#ui-mnav [data-ui-nav=\"recipes\"].on')", margin=300)
                check(f"{tag}: на экране рецепта подсвечены «Рецепты»", pg.evaluate(STATE)["onNav"] == ["recipes"])
            check(f"{tag}: ошибок JS нет {errs[:2]}", not errs)
            ctx.close()
    if rail_ws:
        check(f"{eng_name}: ширина рельса одна на все страницы {rail_ws}", len(set(rail_ws.values())) == 1)


WEBKIT_VPS = ("компьютер", "iPad портретом", "iPhone", "iPhone лёжа")
per_engine(run)   # Chromium и WebKit — параллельно, браузер один на движок (_pages_stand)

print(f"nav_layout: {check.passed} passed, {check.failed} failed")
sys.exit(1 if check.failed else 0)
