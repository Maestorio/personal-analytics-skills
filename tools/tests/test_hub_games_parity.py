#!/usr/bin/env python3
"""Плитка «Игры» хаба = экран «Библиотека» games.html (hub v2.1.0 · games v2.8.2) — прогон настоящим браузером (Chromium).

Обе страницы считают слитую библиотеку одной реализацией — tools/assets/games-model.js (taste-profile: library +
library_full под оверлеем Gaming/user-state.json). Тест на синтетике сверяет числа плитки хаба с числами страницы игр:

  1. Оверлей с: игрой, добавленной на сайте как куплена; удалённой; игрой из library_full, переведённой в некупленную
     с demo: true; часами владельца поверх часов файла; старым state «играю». «N игр» (и сводка sum-games) = «Все» библиотеки,
     «N не начато» = чип «не начата» (число карточек), «M ч» = округлённая сумма часов слитых записей.
  2. Эталон числами из фикстуры (5 игр · 3 не начато · 42 ч) — паритет не должен сойтись на общей ошибке.
  3. Оверлея нет (404) или сервер отдал 500 — хаб считает по файлам скилла, как страница игр без оверлея; ничего не падает.
  4. Ассет games-model.js подключён в обеих страницах с ?v= = md5[:8] файла.
Данные синтетические. Без playwright или chromium — пропуск.
Запуск: python3 tools/tests/test_hub_games_parity.py
"""
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import Checker, Quiet, per_engine, serve  # noqa: E402

try:
    import playwright.sync_api  # noqa: F401
except ImportError:
    print("hub_games_parity: пропуск — нет playwright")
    sys.exit(0)

check = Checker()
TASTE = """updated: 2026-10-01
platforms: {primary: switch2, secondary: steam_deck}
library:
  - {title: "Alpha Quest", verdict: восторг, platform: switch, hours: 10}
  - {title: "Beta Run", verdict: понравилось, platform: switch, hours: 5}
  - {title: "Gamma Tower", verdict: нормально, platform: switch, hours: 20}
mood_clusters: {}
anti_patterns: []
"""
LIBFULL = """library_full:
  - {title: "Alpha Quest", platform: switch, hours: 10}
  - {title: "Beta Run", platform: switch, hours: 5}
  - {title: "Gamma Tower", platform: switch, hours: 20}
  - {title: "Delta Zero", platform: steam_deck, hours: 0}
  - {title: "Epsilon Demo", platform: steam_deck, hours: 7}
  - {title: "Zeta Gone", platform: switch, hours: 3}
"""
ITEMS = [
    {"title": "Alpha Quest", "state": "куплена", "hours": 12.5, "updated": "2026-11-01"},       # часы владельца поверх файла
    {"title": "Beta Run", "state": "играю", "updated": "2026-11-01"},                           # старое значение → куплена + играю
    {"title": "Eta Added", "state": "куплена", "progress": "играю", "hours": 4, "added": "2026-11-02", "updated": "2026-11-02"},   # добавлена на сайте
    {"title": "Zeta Gone", "state": "куплена", "deleted": True, "updated": "2026-11-01"},      # удалена
    {"title": "Epsilon Demo", "state": "на-карандаш", "demo": True, "updated": "2026-11-01"},  # из library_full в «Присматриваюсь»
    {"title": "Gamma Tower", "state": "куплена", "progress": "отложена", "updated": "2026-11-01"},   # отложена → бэклог
    {"title": "Delta Zero", "state": "куплена", "progress": "пройдена", "updated": "2026-11-01"},    # пройдена
    {"title": "Theta Wish", "state": "хочу", "added": "2026-11-02", "updated": "2026-11-02"},  # только список
]
DOC = {"schema": "gaming-user@1", "updated": "2026-11-02", "items": ITEMS}
# эталон: Alpha(12.5) Beta(5) Gamma(20) Delta(0) Eta(4) = 5 игр; не начаты Alpha, Gamma, Delta = 3; 41.5 → 42 ч
WITH = (5, 2, 42)          # игр · бэклог (не начата 1 + отложена 1) · часы; играю 2, пройдено 1
# без оверлея: Alpha Beta Gamma Delta Epsilon Zeta = 6; не начаты все 6; 10+5+20+0+7+3 = 45 ч
WITHOUT = (6, 6, 45)
ST = {"mode": "doc"}


class H(Quiet):
    def do_GET(self):
        if self.path.startswith("/api/gm/file"):
            b = json.dumps({"path": "Gaming/user-state.json", "hash": "h1", "content": json.dumps(DOC)}).encode()
            code = {"doc": 200, "404": 404, "500": 500}[ST["mode"]]
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        return super().do_GET()


def hub_nums(page):
    page.goto(page.base + "/tools/hub.html")
    page.wait_for_function("/бэклог \\d/.test(document.getElementById('games-split').textContent)", timeout=15000)
    t = page.inner_text("#games-split")
    m = re.match(r"играю (\d+) · бэклог (\d+) · пройдено (\d+)$", t.strip())
    cnt = int(re.match(r"(\d+)", page.inner_text("#games-count")).group(1))
    page.stats = (int(m.group(1)), int(m.group(2)), int(m.group(3)), page.inner_text("#games-plats"))
    return cnt, int(page.inner_text("#sum-games")), page.stats[1], int(re.match(r"(\d+) ч$", page.inner_text("#games-hours").strip()).group(1))


def games_nums(page):
    page.add_init_script("sessionStorage.setItem('games-screen','library')")
    page.goto(page.base + "/tools/games.html")
    page.wait_for_function("document.querySelectorAll('#lib-grid .gcard').length >= 1", timeout=15000)
    total = int(page.inner_text("#lib-total"))
    hours = page.evaluate("Math.round(__libm.rows.reduce(function(a, g){ return a + (+g.hours || 0); }, 0))")
    # чип «не начата» — число карточек без других фильтров
    page.stats = tuple(page.evaluate("(k) => __libm.rows.filter(function(g){ return k.indexOf(g.progress || 'не-начата') >= 0; }).length", ks)
                       for ks in (["играю"], ["не-начата", "отложена"], ["пройдена"]))
    page.click('#gfilters [data-key="не-начата"]')
    page.wait_for_timeout(200)
    page.ns_cards = len(page.query_selector_all("#lib-grid .gcard"))
    return total, page.stats[1], hours


def run(name, br):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "Gaming").mkdir()
    (tmp / "Gaming" / "taste-profile.yaml").write_text(TASTE, encoding="utf-8")
    (tmp / "Gaming" / "library_full.yaml").write_text(LIBFULL, encoding="utf-8")
    os.symlink(REPO / "tools", tmp / "tools")
    srv, base = serve(H, directory=tmp)
    try:
        for mode, exp in (("doc", WITH), ("404", WITHOUT), ("500", WITHOUT)):
            ST["mode"] = mode
            ctx = br.new_context(viewport={"width": 1280, "height": 900})
            errs = []
            hp = ctx.new_page()
            hp.base = base
            hp.on("pageerror", lambda e: errs.append(str(e)))
            cnt, summ, ns, hrs = hub_nums(hp)
            gp = ctx.new_page()
            gp.base = base
            gp.on("pageerror", lambda e: errs.append(str(e)))
            total, gns, ghrs = games_nums(gp)
            check(f"оверлей {mode}: плитка «N игр» = «Все» библиотеки", cnt == total and summ == total, f"{cnt}/{summ}/{total}")
            check(f"оверлей {mode}: «бэклог» плитки = не начата + отложена; «не начата» = карточки чипа",
                  ns == gns and gp.ns_cards == (1 if mode == "doc" else 6) and (mode != "doc" or hp.stats[:3] == (2, 2, 1)), f"{ns}/{gns}/{gp.ns_cards}/{hp.stats}")
            check(f"оверлей {mode}: «играю · бэклог · пройдено» плитки = счёт по слитым записям страницы игр", hp.stats[:3] == gp.stats, f"{hp.stats}/{gp.stats}")
            check(f"оверлей {mode}: платформы плитки — из данных библиотеки, Switch одним словом, по убыванию числа игр",
                  hp.stats[3] == "Switch · Steam Deck", hp.stats[3])
            check(f"оверлей {mode}: часы плитки = сумма часов слитых записей страницы игр", hrs == ghrs, f"{hrs}/{ghrs}")
            check(f"оверлей {mode}: эталон числами {exp}", (cnt, ns, hrs) == exp, f"{(cnt, ns, hrs)}")
            check(f"оверлей {mode}: ошибок JS нет", not errs, str(errs[:3]))
            ctx.close()
    finally:
        srv.shutdown()
        srv.server_close()


md5 = hashlib.md5((REPO / "tools/assets/games-model.js").read_bytes()).hexdigest()[:8]
for page in ("hub.html", "games.html"):
    html = (REPO / "tools" / page).read_text(encoding="utf-8")
    i = html.find(f'assets/games-model.js?v={md5}')
    check(f"{page}: подключает games-model.js?v=<md5[:8]> после codelists.js", i > 0 and 0 < html.find("assets/codelists.js") < i)
check("hub.html: старого счёта регуляркой по library_full.yaml нет", "match(/\\{title:/g)" not in (REPO / "tools/hub.html").read_text(encoding="utf-8"))

if __name__ == "__main__":
    per_engine(run, engines=("chromium",))
    print(f"hub_games_parity: {check.passed} OK, {check.failed} FAIL")
    sys.exit(1 if check.failed else 0)
