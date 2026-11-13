#!/usr/bin/env python3
"""Шапка кабинета — одна на все страницы: прогон НАСТОЯЩИМИ браузерами
(Chromium и WebKit — движок Safari на iPhone).

Почему: 2026-10-06 при разработке «Денег» выяснилось, что крошка «← Хаб» и
вся шапка на каждой странице своя (четыре вёрстки), и вели они себя по-разному
на одной и той же ширине. С ui-kit 1.17.0 шапку рисует uiTopHTML; этот тест
держит, что она и выглядит одинаково, а не только одинаково написана.

Что проверяется (компьютер 1280 и телефон 375, все шесть страниц):
  1. шапка ровно одна и не шире экрана;
  2. высота шапки и место/размер крошки «← Хаб» совпадают на всех страницах;
     на телефоне подпись «Хаб» спрятана, мишень стрелки ≥ 40px;
  3. кнопка темы: тема, hub-theme и подпись меняются, шапка после перерисовки
     страницы (health/food/money рисуют её заново) по-прежнему одна; после
     перезагрузки тема держится; обратно — светлая;
  4. travel по ссылке «поделиться» (?trip=) — без крошки, входа и справки;
  5. отвергнутый пароль (401 на приватном запросе хаба) — «Выйти» сам
     становится «Войти заново» (ui-kit 1.16.0, authFetch);
  6. вьюер портфеля (своя липкая обёртка, шапка .ui-hdr): кнопки и имя в одну
     строку на 1280/1024/768/375, не шире экрана; на телефоне имя уступает кнопкам;
  7. ошибок JS нет.

Данных нет (Synology не нужен): страницы грузятся с пустым сервером и
показывают свои состояния «нет данных» — шапка обязана быть и там.

Запуск:
    python3 tools/tests/test_topbar_layout.py
Требует playwright; движок, которого нет (`playwright install webkit`), —
честный пропуск этого движка, не падение.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import Checker, per_engine, serve, settle  # noqa: E402

check = Checker()


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("topbar_layout: пропуск — нет playwright")
    sys.exit(0)

PAGES = ("hub", "travel", "games", "health", "food", "money")


srv, _base = serve()   # корень репозитория, один сервер на процесс (_pages_stand)
BASE = _base + "/tools/"

MEASURE = """() => {
  const tops = document.querySelectorAll('.ui-top');
  const t = tops[0]; if (!t) return { n: 0 };
  const r = t.getBoundingClientRect(), c = t.querySelector('.ui-crumb');
  const cr = c && c.getBoundingClientRect(), lbl = t.querySelector('.ui-crumb-lbl');
  return { n: tops.length, h: Math.round(r.height), over: t.scrollWidth - t.clientWidth,
           doc: document.documentElement.scrollWidth - window.innerWidth,
           crumb: cr ? [Math.round(cr.x), Math.round(cr.y), Math.round(cr.width), Math.round(cr.height)] : null,
           lblShown: !!(lbl && lbl.offsetWidth > 0),
           auth: !!t.querySelector('[data-act="logout"], a[href*="login.html"]'),
           help: !!t.querySelector('[data-ui-help]'),
           theme: document.documentElement.getAttribute('data-theme') || 'light',
           themeLbl: (t.querySelector('[data-theme-lbl]') || {}).textContent || '' };
}"""

AUTH = "localStorage.setItem('hub-auth','dGVzdDp0ZXN0');"


def run(eng_name, browser):
    for w, h in ((1280, 800), (375, 740)):
        ctx = browser.new_context(viewport={"width": w, "height": h})
        ctx.add_init_script(AUTH)
        seen = {}
        for name in PAGES:
            pg = ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
            pg.goto(BASE + name + ".html")
            settle(pg, "!!document.querySelector('.ui-top [data-act=\"theme\"]')", margin=300)
            m = pg.evaluate(MEASURE)
            tag = f"{eng_name} {w}px {name}"
            check(f"{tag}: шапка ровно одна (нашлось {m['n']})", m["n"] == 1)
            if m["n"] != 1:
                pg.close()
                continue
            check(f"{tag}: шапка не шире экрана (лишних {m['over']}px)", m["over"] <= 0)
            check(f"{tag}: страница не шире экрана (лишних {m['doc']}px)", m["doc"] <= 0)
            seen[name] = m
            if name != "hub":
                check(f"{tag}: подпись «Хаб» {'видна' if w > 420 else 'спрятана'}", m["lblShown"] == (w > 420))
                if w <= 420:
                    check(f"{tag}: мишень стрелки ≥ 40px ({m['crumb']})", m["crumb"][2] >= 40 and m["crumb"][3] >= 40)
            # тема: туда, перерисовка, перезагрузка, обратно
            pg.click('.ui-top [data-act="theme"]')
            pg.wait_for_timeout(150)
            d = pg.evaluate(MEASURE)
            check(f"{tag}: тема → тёмная, подпись «Светлая тема», шапка одна ({d['theme']}, {d['themeLbl']!r}, {d['n']})",
                  d["theme"] == "dark" and d["themeLbl"] == "Светлая тема" and d["n"] == 1)
            check(f"{tag}: выбор запомнен в hub-theme",
                  pg.evaluate("localStorage.getItem('hub-theme')") == "dark")
            pg.reload()
            settle(pg, "!!document.querySelector('.ui-top [data-theme-lbl]')", margin=200)
            r = pg.evaluate(MEASURE)
            check(f"{tag}: после перезагрузки тема держится ({r['theme']}, {r['themeLbl']!r})",
                  r["theme"] == "dark" and r["themeLbl"] == "Светлая тема")
            pg.click('.ui-top [data-act="theme"]')
            pg.wait_for_timeout(150)
            l = pg.evaluate(MEASURE)
            check(f"{tag}: обратно — светлая ({l['theme']}, {l['themeLbl']!r})",
                  l["theme"] == "light" and l["themeLbl"] == "Тёмная тема"
                  and pg.evaluate("localStorage.getItem('hub-theme')") == "light")
            check(f"{tag}: ошибок JS нет {errs[:2]}", not errs)
            pg.close()
        # одинаковость между страницами
        hs = {n: m["h"] for n, m in seen.items()}
        check(f"{eng_name} {w}px: высота шапки одна на всех страницах {hs}", len(set(hs.values())) == 1)
        cr = {n: tuple(m["crumb"]) for n, m in seen.items() if m["crumb"]}
        check(f"{eng_name} {w}px: крошка «← Хаб» на одном месте и одного размера {cr}",
              len(cr) == len(PAGES) - 1 and len(set(cr.values())) == 1)
        ctx.close()

    # travel по ссылке «поделиться»
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    ctx.add_init_script(AUTH)
    pg = ctx.new_page()
    pg.goto(BASE + "travel.html?trip=test-trip")
    settle(pg, "!!document.querySelector('.ui-top')", margin=300)
    m = pg.evaluate(MEASURE)
    check(f"{eng_name} travel ?trip=: шапка без крошки, входа и справки ({m})",
          m["n"] == 1 and m["crumb"] is None and not m["auth"] and not m["help"])
    ctx.close()

    # отвергнутый пароль: приватный запрос хаба отвечает 401
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    ctx.add_init_script(AUTH + "localStorage.removeItem('hub-auth-rejected');")
    pg = ctx.new_page()
    pg.route("**/health-data/**", lambda route: route.fulfill(status=401, body=""))
    pg.goto(BASE + "hub.html")
    settle(pg, "/Войти заново/.test((document.querySelector('.ui-top') || {}).innerText || '')", margin=200)
    txt = pg.locator(".ui-top").inner_text()
    check(f"{eng_name} хаб, пароль отвергнут (401): «Выйти» → «Войти заново» ({txt!r})",
          "Войти заново" in txt and "Выйти" not in txt)
    ctx.close()
    # вьюер портфеля: своя липкая обёртка (#top-chrome) — шапка .ui-hdr в одну
    # строку на любой ширине (2026-10-06: была в две — крошка над названием, а
    # кнопки переносились); показываем все кнопки, что бывают в http-режиме
    for w in (1280, 1150, 1024, 768, 375):
        ctx = browser.new_context(viewport={"width": w, "height": 700})
        ctx.add_init_script(AUTH)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
        pg.goto(BASE + "portfolio-integrated-viewer.html")
        settle(pg, "!!document.getElementById('btn-theme') && !!document.querySelector('#auth-slot [data-act=logout], #auth-slot a[href*=\"login.html\"]')", margin=300)
        v = pg.evaluate("""() => {
          for (const id of ['btn-refresh','btn-reports','btn-gate-legend','btn-notify','btn-help','btn-theme']) document.getElementById(id).hidden = false;
          document.getElementById('reports-count').textContent = '12';
          const h = document.querySelector('header.app-header'), r = h.getBoundingClientRect();
          const items = [...h.querySelectorAll('.ui-crumb, .ui-top-sec, button:not([hidden])')].filter(e => e.offsetWidth > 0);
          const mids = items.map(e => { const b = e.getBoundingClientRect(); return Math.round(b.top + b.height / 2); });
          const name = h.querySelector('.ui-top-name');
          const sec = h.querySelector('.ui-top-sec');
          const btn = [...h.querySelectorAll('.ctrls .chip-btn')].find(e => e.offsetWidth > 0);
          return { h: Math.round(r.height), rows: Math.max(...mids) - Math.min(...mids), over: h.scrollWidth - h.clientWidth,
                   doc: document.documentElement.scrollWidth - innerWidth, n: items.length,
                   name: name && name.offsetWidth > 0 ? name.textContent : null,
                   right: Math.max(...items.map(e => Math.round(e.getBoundingClientRect().right))),
                   secR: sec && sec.offsetWidth > 0 ? Math.round(sec.getBoundingClientRect().right) : null,
                   btnL: btn ? Math.round(btn.getBoundingClientRect().left) : null };
        }""")
        tag = f"{eng_name} {w}px вьюер"
        check(f"{tag}: шапка в одну строку (разброс центров {v['rows']}px, высота {v['h']}px)", v["rows"] <= 2 and v["h"] <= 60)
        check(f"{tag}: шапка не шире экрана (лишних {v['over']}px, крайняя кнопка до {v['right']})",
              v["over"] <= 0 and v["doc"] <= 0 and v["right"] <= w)
        check(f"{tag}: плашка раздела не наезжает на кнопки (правый край {v['secR']}, первая кнопка с {v['btnL']})",
              v["secR"] is None or v["btnL"] is None or v["secR"] <= v["btnL"])
        check(f"{tag}: имя раздела {'видно' if w > 480 else 'уступает кнопкам'} ({v['name']!r})",
              (v["name"] == "Портфель") if w > 480 else v["name"] is None)
        if w == 1280:
            pg.click("#btn-theme")
            pg.wait_for_timeout(100)
            check(f"{tag}: подпись темы следует за темой",
                  pg.evaluate("document.querySelector('#btn-theme [data-theme-lbl]').textContent") == "Светлая тема")
            check(f"{tag}: тема — общая ui-kit (атрибут dark и hub-theme)",
                  pg.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"
                  and pg.evaluate("localStorage.getItem('hub-theme')") == "dark")
            pg.click("#btn-theme")
            pg.wait_for_timeout(100)
            check(f"{tag}: обратно светлая — подпись и hub-theme",
                  pg.evaluate("document.querySelector('#btn-theme [data-theme-lbl]').textContent") == "Тёмная тема"
                  and pg.evaluate("localStorage.getItem('hub-theme')") == "light")
            check(f"{tag}: Войти/Выйти — общая кнопка ui-kit",
                  pg.locator("#auth-slot [data-act=logout], #auth-slot a[href*='login.html']").count() == 1)
        check(f"{tag}: ошибок JS нет {errs[:2]}", not errs)
        ctx.close()


per_engine(run)   # Chromium и WebKit — параллельно, браузер один на движок (_pages_stand)

print(f"topbar_layout: {check.passed} passed, {check.failed} failed")
sys.exit(1 if check.failed else 0)
