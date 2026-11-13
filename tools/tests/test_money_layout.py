#!/usr/bin/env python3
"""Вёрстка графиков раздела «Деньги» — прогон НАСТОЯЩИМИ браузерами: Chromium и
WebKit (движок Safari на iPhone).

Почему два движка: 2026-10-06 на iPhone линия скользящего среднего обрывалась
за 3 месяца до края, а в Chrome всё было верно. Safari считал `width:max-content`
у flex-контейнера графика по видимой области, а не по колонкам, и слой с линией
выходил уже самих столбиков. Чтением исходника и одним Chromium это не поймать.

Что проверяется (телефон 390 и компьютер 1280, «Траты» и «Остаток», «Обзор»):
  1. страница не шире экрана;
  2. слой линии ровно той же ширины, что колонки, а колонки — вся прокрутка;
  3. линия кончается над центром последнего месяца со средним;
  4. кривая нигде не выходит за значения соседних средних (монотонность);
  5. клик по столбику не сдвигает график на экране;
  6. подписи месяцев в компактных графиках «Обзора» не наезжают друг на друга;
  7. ошибок JS нет;
  8. раскрытая категория — одна карточка (строка + подробности) с тенью,
     раскрывается и сворачивается плавно (анимация высоты);
  9. окно «к прошлому году» (все обычные траты): 12 колонок по два столбика,
     не шире экрана, без прокрутки вбок, подписи не наезжают; Esc закрывает;
 10. окно категории (money v1.13.0): 12 месяцев подряд, выбор месяцев (прокрутка
     окна не сбрасывается), подкатегория раскрывает места; окно категории поверх
     «Обычных трат», Esc закрывает по одному; факт — окно с месяцами факта;
     стрелка «все»; тулбар не шире экрана.

Данные синтетические (свой ZenMoney/audit во временной папке): 9 месяцев 2026
с пропуском, 7 месяцев 2025 (база «год назад»), месяц в минусе, одна поездка,
один факт роста — Synology не нужен.

Запуск:
    python3 tools/tests/test_money_layout.py
Требует playwright; движок, которого нет (`playwright install webkit`), —
честный пропуск этого движка, не падение.
"""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import serve  # noqa: E402  (стенд — _pages_stand, keep-alive)
passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("money_layout: пропуск — нет playwright")
    sys.exit(0)

# ── синтетические данные ────────────────────────────────────────────────────
MONTHS = ["2026-01", "2026-02", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]  # март — пропуск
REG = [120e3, 40e3, 220e3, 150e3, 80e3, 135e3, 165e3, 90e3, 110e3]
INC = [300e3, 300e3, 600e3, 120e3, 320e3, 350e3, 350e3, 330e3, 320e3]   # май — минус


PREV = {"2025-04": 100e3, "2025-05": 90e3, "2025-06": 70e3, "2025-07": 110e3, "2025-08": 120e3, "2025-09": 80e3, "2025-10": 95e3}


def month(i, m):
    if m in PREV:
        reg = PREV[m]
        return {"month": m, "as_of": m + "-28",
                "totals": {"expense_rub": reg, "income_rub": 300e3, "refunds_rub": 0, "expense_in_balance_rub": reg,
                           "income_in_balance_rub": 300e3, "expense_off_balance_rub": 0, "expense_trips_rub": 0,
                           "expense_one_off_rub": 0, "expense_regular_rub": reg, "operations": 90},
                "excluded": {}, "categories": [], "income_categories": [], "trips": [],
                "categories_regular": [{"name": "Питание", "rub": reg * 0.4, "count": 9, "share": 0.4},
                                       {"name": "Счета", "rub": reg * 0.3, "count": 3, "share": 0.3},
                                       {"name": "Транспорт", "rub": reg * 0.3, "count": 5, "share": 0.3}],
                "subcategories_regular": [{"parent": "Питание", "name": "Магазины", "rub": reg * 0.4, "count": 9}],
                "merchants": [{"name": "Магазин", "rub": reg * 0.3, "count": 6, "category": "Питание", "sub": "Магазины", "kind": "regular"},
                              {"name": "Лавка", "rub": reg * 0.1, "count": 3, "category": "Питание", "sub": "Магазины", "kind": "regular"}],
                "merchant_share_of_expense": 0.8, "unconverted": {}}
    reg, trips, one = REG[i], (150e3 if m == "2026-09" else 0), {"2026-05": 20e3, "2026-10": 30e3}.get(m, 0)
    exp = reg + trips + one
    # в апреле «Транспорт» — первая категория: порядок списка меняется с месяцем
    pf, tf = (0.2, 0.5) if m == "2026-04" else (0.5, 0.2)
    # последний месяц — в новом формате: места с kind и разовые поштучно
    extra = {"one_off": [{"name": "Холодильник.ру", "rub": one, "category": "Питание", "note": ""}],
             "merchants": [{"name": "Магазин", "rub": reg * pf * 0.5, "count": 4, "category": "Питание", "sub": "Магазины", "kind": "regular"},
                           {"name": "Лавка", "rub": reg * pf * 0.2, "count": 3, "category": "Питание", "sub": "Магазины", "kind": "regular"},
                           {"name": "Кофейня", "rub": reg * pf * 0.3, "count": 3, "category": "Питание", "sub": "Кофейни", "kind": "regular"},
                           {"name": "Холодильник.ру", "rub": one, "count": 1, "category": "Питание", "kind": "one_off"}]} \
        if m == "2026-10" else {}
    return {**{"month": m, "as_of": m + "-28",
            "totals": {"expense_rub": exp, "income_rub": INC[i], "refunds_rub": 0,
                       "expense_in_balance_rub": exp, "income_in_balance_rub": INC[i], "expense_off_balance_rub": 0,
                       "expense_trips_rub": trips, "expense_one_off_rub": one, "expense_regular_rub": reg, "operations": 100},
            "excluded": {}, "categories": [], "income_categories": [],
            "categories_regular": sorted([{"name": "Питание", "rub": reg * pf, "count": 10, "share": pf},
                                          {"name": "Счета", "rub": reg * 0.3, "count": 3, "share": 0.3},
                                          {"name": "Транспорт", "rub": reg * tf, "count": 5, "share": tf}],
                                         key=lambda c: -c["rub"]),
            "subcategories_regular": [{"parent": "Питание", "name": "Магазины", "rub": reg * pf * 0.7, "count": 7},
                                      {"parent": "Питание", "name": "Кофейни", "rub": reg * pf * 0.3, "count": 3}],
            "trips": [{"name": "#Тест'26", "rub": trips, "count": 5}] if trips else [],
            "merchants": [{"name": "Магазин", "rub": reg * pf * 0.5, "count": 4, "category": "Питание", "sub": "Магазины", "kind": "regular"},
                          {"name": "Лавка", "rub": reg * pf * 0.2, "count": 3, "category": "Питание", "sub": "Магазины", "kind": "regular"},
                          {"name": "Кофейня", "rub": reg * pf * 0.3, "count": 3, "category": "Питание", "sub": "Кофейни", "kind": "regular"}],
            "merchant_share_of_expense": 0.8, "unconverted": {}}, **extra}


SPENDING = {"schema": "zenmoney-spending@1", "updated": "2026-10-28",
            "months": [month(-1, m) for m in PREV] + [month(i, m) for i, m in enumerate(MONTHS)]}
FACTS = {"schema": "zenmoney-facts@1", "updated": "2026-10-28", "month": "2026-10", "params": {}, "not_enough_data": [],
         "flagged_categories": {"Питание": ["growth"]},
         "facts": [{"kind": "growth", "category": "Питание", "window": ["2026-05", "2026-10"], "base": ["2025-05", "2025-10"],
                    "per_month_base": 37e3, "per_month": 60e3, "growth": 0.62, "others_growth": 0.2,
                    "share_base": 0.4, "share": 0.5, "excess_rub": 15e3}]}
HISTORY = {"schema": "zenmoney-audit@1", "updated": "2026-10-28", "issues": {},
           "records": [{"month": m, "as_of": m + "-28", "mode": "month", "operations": 100, "flagged": 0,
                        "clean_share_count": 1, "clean_share_rub": 1, "expense_rub": 1e5, "correction_rub": 0,
                        "correction_transfer_out_rub": 0, "correction_share_of_expense": 0, "by_check": {},
                        "b6_count": 0, "b7_count": 0, "b7_rub": 0, "c_counts": None, "open_by_age": {}, "open_total": 0,
                        "unconverted": {}} for m in MONTHS if m != "2026-06"]}   # июнь — без аудита (как история из CSV)
# места платежа последнего месяца (скилл 2.15.0) — строка в «Полноте учёта»
# замечания (money 1.24.0): октябрь — две «одинаковые» приняты как норма после аудита (снимок
# by_check их помнит, открытыми они не считаются); сентябрь — одно «без категории» открыто
HISTORY["records"][-1]["by_check"] = {"A5": {"count": 2, "rub": 500}}
# open_total=2 — устаревший снимок (раньше закрытый месяц перезакрыли позже): страница верит статусам issues → 1
HISTORY["records"][-1].update(open_total=2, open_by_age={"lt_1m": 2, "1_3m": 0, "gt_3m": 0})
HISTORY["records"][-2]["by_check"] = {"A3": {"count": 1, "rub": 4}}
HISTORY["issues"] = {"A5:x1": {"check": "A5", "month": "2026-10", "first_seen": "2026-10-28", "last_seen": "2026-10-28", "status": "accepted", "closed_at": "2026-10-29"},
                     "A5:x2": {"check": "A5", "month": "2026-10", "first_seen": "2026-10-28", "last_seen": "2026-10-28", "status": "accepted", "closed_at": "2026-10-29"},
                     "A3:y1": {"check": "A3", "month": "2026-09", "first_seen": "2025-01-15", "last_seen": "2026-10-28", "status": "open"}}
HISTORY["records"][-1]["places_counts"] = {"twins": 2, "split": 0, "unlinked": 3, "rename": 4, "bank_text": 14, "chains": None}
TRIPS = {"schema": "zenmoney-trips@1", "updated": "2026-10-28", "trips": [{
    "trip": {"id": "t1", "name": "#Тест'26"}, "period": {"start": "2026-09-04", "end": "2026-09-16", "days": 13},
    "first_purchase": "2026-06-01", "as_of": "2026-10-01",
    "totals": {"spent_rub": 150e3, "refunds_rub": 0, "compensations_rub": 0, "partner_rub": 0, "unrecorded_rub": 0,
               "per_day_during_rub": 9e3, "operations": 40},
    "by_type": [{"type": "Билеты", "rub": 70e3}, {"type": "Жильё", "rub": 40e3}, {"type": "Еда", "rub": 40e3}],
    "by_phase": {"before": 70e3, "during": 80e3, "after": 0}, "type_by_phase": [], "prepaid_by_lead": [],
    "currencies": [{"instrument": "RUB", "amount": 150e3, "rub": 150e3}], "unconverted": {}}]}

root = Path(tempfile.mkdtemp(prefix="money-layout-"))
shutil.copytree(REPO / "tools", root / "tools", ignore=shutil.ignore_patterns("tests", "_archive", "__pycache__", "hosting"))
(root / "ZenMoney/audit").mkdir(parents=True)
for name, doc in (("spending.json", SPENDING), ("history.json", HISTORY), ("trips.json", TRIPS), ("facts.json", FACTS)):
    (root / "ZenMoney/audit" / name).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


srv = serve(directory=root)[0]   # _pages_stand: очередь 128, keep-alive
URL = f"http://127.0.0.1:{srv.server_address[1]}/tools/money.html"

GEOM = """(id) => {
  const box = document.getElementById(id), cols = [...box.querySelectorAll('.ui-col')];
  const wrap = box.querySelector('.ui-cols'), svg = box.querySelector('.ui-cols-line');
  const f = cols[0].getBoundingClientRect(), l = cols[cols.length - 1].getBoundingClientRect();
  const paths = [...svg.querySelectorAll('path')];
  const sr = svg.getBoundingClientRect();
  // узлы кривой — концы отрезков M/C, в единицах viewBox
  const nodes = paths.map(p => [...p.getAttribute('d').matchAll(/(?:M|C[^ ]+ [^ ]+ )([\\d.]+),([\\d.]+)/g)].map(m => [+m[1], +m[2]]));
  let over = 0;
  paths.forEach((p, k) => {
    const L = p.getTotalLength(), ns = nodes[k];
    for (let j = 0; j <= 300; j++) {
      const pt = p.getPointAtLength(L * j / 300);
      for (let i = 0; i < ns.length - 1; i++) {
        if (pt.x < ns[i][0] || pt.x > ns[i + 1][0]) continue;
        const lo = Math.min(ns[i][1], ns[i + 1][1]) - 0.05, hi = Math.max(ns[i][1], ns[i + 1][1]) + 0.05;
        if (pt.y < lo || pt.y > hi) over++;
      }
    }
  });
  const lastNode = nodes.length ? nodes[nodes.length - 1].slice(-1)[0] : null;
  return { colsW: wrap.getBoundingClientRect().width, span: l.right - f.left, svgW: sr.width,
           lastEndPx: lastNode ? sr.left + lastNode[0] / 100 * sr.width : null,
           lastColCenter: (l.left + l.right) / 2, over: over, top: box.getBoundingClientRect().top };
}"""
OVERLAP = """(id) => {
  const ls = [...document.querySelectorAll('#' + id + ' .ui-col-lbl')].map(e => {
    const r = document.createRange(); r.selectNodeContents(e); return r.getBoundingClientRect(); });
  let bad = 0; for (let i = 0; i + 1 < ls.length; i++) if (ls[i].right > ls[i + 1].left + 0.5) bad++;
  return bad;
}"""

# окно «к прошлому году»: геометрия графика и прокрутка вбок
YOY = """() => {
  const ms = document.querySelectorAll('.ui-modal'), m = ms[ms.length - 1]; if (!m) return null;
  const box = m.querySelector('.ui-modal-box').getBoundingClientRect(), body = m.querySelector('.ui-modal-body');
  const cols = [...m.querySelectorAll('.ui-cols.yoy .ui-col')];
  const ls = cols.map(c => { const r = document.createRange(); r.selectNodeContents(c.querySelector('.ui-col-lbl')); return r.getBoundingClientRect(); });
  let over = 0; for (let i = 0; i + 1 < ls.length; i++) if (ls[i].right > ls[i + 1].left + 0.5) over++;
  return { boxL: box.left, boxR: box.right, n: cols.length, bars: cols.map(c => c.querySelectorAll('.ui-col-exp').length),
           win: m.querySelectorAll('.ui-col.win').length, hscroll: body.scrollWidth - body.clientWidth, over: over,
           text: body.innerText };
}"""

ENGINES = 0
with sync_playwright() as p:
    for eng_name in ("chromium", "webkit"):
        eng = getattr(p, eng_name)
        try:
            browser = eng.launch()
        except Exception:
            print(f"money_layout: пропуск движка {eng_name} — не установлен (playwright install {eng_name})")
            continue
        ENGINES += 1
        for w, h in ((390, 844), (1280, 900)):
            tag = f"{eng_name} {w}"
            ctx = browser.new_context(viewport={"width": w, "height": h})
            ctx.add_init_script("localStorage.setItem('hub-auth','dGVzdDp0ZXN0'); if (!sessionStorage.getItem('t')) { sessionStorage.setItem('t','1'); localStorage.setItem('money-tab','spend'); }")
            pg = ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(URL)
            pg.wait_for_selector("#dyn .ui-col")
            check(f"{tag}: страница не шире экрана",
                  pg.evaluate("document.documentElement.scrollWidth") <= w + 1)
            for mode in ("spend", "net"):
                if mode == "net":
                    pg.click('[data-act="chart"][data-v="net"]')
                    pg.wait_for_timeout(100)
                g = pg.evaluate(GEOM, "dyn")
                check(f"{tag} {mode}: колонки занимают всю ширину прокрутки ({g['colsW']:.0f} = {g['span']:.0f})",
                      abs(g["colsW"] - g["span"]) <= 1)
                check(f"{tag} {mode}: слой линии той же ширины, что колонки ({g['svgW']:.0f} = {g['colsW']:.0f})",
                      abs(g["svgW"] - g["colsW"]) <= 1)
                check(f"{tag} {mode}: линия кончается над последним месяцем ({g['lastEndPx']} ≈ {g['lastColCenter']:.0f})",
                      g["lastEndPx"] is not None and abs(g["lastEndPx"] - g["lastColCenter"]) <= 1.5)
                check(f"{tag} {mode}: кривая не выходит за соседние средние", g["over"] == 0)
            # телефон (2026-10-07, iPhone): переключатель периода и список — не шире экрана
            tbr = pg.evaluate("Math.max(...[...document.querySelectorAll('.ui-toolbar, .ui-toolbar *')].map(e => e.getBoundingClientRect().right))")
            check(f"{tag}: тулбар не шире экрана ({tbr:.0f} ≤ {w})", tbr <= w + 0.5)
            pg.click('[data-act="chart"][data-v="spend"]')
            pg.click('[data-act="cat"][data-v="Питание"]')
            pg.wait_for_selector(".ui-catdetail")
            check(f"{tag}: раскрытие категории плавное (идёт анимация высоты)",
                  pg.evaluate("document.querySelector('.ui-catdetail').getAnimations().length") > 0)
            pg.wait_for_function("!document.querySelector('.ui-catdetail').getAnimations().length")
            card = pg.evaluate("(() => { const c = document.querySelector('.ui-catopen'); return c && { row: !!c.querySelector('.ui-catrow.on'), det: !!c.querySelector('.ui-catdetail'), sh: getComputedStyle(c).boxShadow }; })()")
            check(f"{tag}: раскрытая категория — карточка с тенью {card}",
                  bool(card) and card["row"] and card["det"] and card["sh"] not in ("", "none"))
            det = pg.inner_text(".ui-catdetail")
            check(f"{tag}: карточка — история, подкатегории и «Где платил»; разовой нет",
                  "Магазин" in det and "Подкатегории" in det.title() and "Холодильник" not in det)
            # окно категории «к прошлому году»: 12 месяцев подряд (не календарный год), по два столбика
            pg.click('.ui-catdetail [data-act="yoy"]')
            pg.wait_for_selector(".ui-modal .ui-cols.yoy.pick")
            pg.wait_for_function("![...document.querySelectorAll('.ui-modal *')].some(e => e.getAnimations().length)")
            y = pg.evaluate(YOY)
            first = pg.evaluate("document.querySelector('.ui-modal .ui-col').dataset.v")
            check(f"{tag}: окно категории — 12 месяцев с ноября 2025 по два столбика ({y['n']}, {first})", y["n"] == 12 and set(y["bars"]) == {2} and first == "2025-11")
            check(f"{tag}: окно в пределах экрана ({y['boxL']:.0f}…{y['boxR']:.0f})", y["boxL"] >= -0.5 and y["boxR"] <= w + 0.5)
            check(f"{tag}: в окне нет прокрутки вбок ({y['hscroll']})", y["hscroll"] <= 0)
            check(f"{tag}: подписи месяцев в окне не наезжают ({y['over']})", y["over"] == 0)
            check(f"{tag}: в окне подкатегории", "Магазины" in y["text"] and "Кофейни" in y["text"])
            # подкатегория → её места; выбор месяцев пересчитывает итог, прокрутка окна не сбрасывается
            pg.click('.ui-modal [data-act="yoy-sub"][data-v="Магазины"]')
            pg.wait_for_selector(".ui-modal .ui-catplaces")
            pls = pg.inner_text(".ui-modal .ui-catplaces")
            check(f"{tag}: места подкатегории в окне, разовой нет", "Магазин" in pls and "Лавка" in pls and "Холодильник" not in pls)
            # суммы с долей «12,3 (14%)» (v1.16.0) помещаются в колонки: ячейка не шире себя, имя не пропало
            pg.evaluate("document.fonts.ready.then(() => 0)")  # ширина ячеек зависит от шрифта: под нагрузкой он грузится позже
            pg.wait_for_timeout(300)
            fit = pg.evaluate("""() => { const m = [...document.querySelectorAll('.ui-modal')].pop();
              const cs = [...m.querySelectorAll('.ui-row:not(.head) > .ui-r')];
              return { n: cs.filter(c => c.textContent.includes('%)')).length,
                       over: cs.filter(c => c.scrollWidth > c.clientWidth + 0.5).map(c => c.textContent),
                       name: Math.min(...[...m.querySelectorAll('.ui-row:not(.head) > .ui-ell')].map(e => e.getBoundingClientRect().width)) }; }""")
            check(f"{tag}: доли в строках окна есть и помещаются ({fit['n']}, {fit['over']}, имя {fit['name']:.0f}px)",
                  fit["n"] >= 4 and not fit["over"] and fit["name"] >= 60)
            # с «Трат» окно открывается на месяцах выбранного периода (режим «месяц» → октябрь); снимаем его — дальше тест как раньше
            dflt = pg.evaluate("[...document.querySelectorAll('.ui-modal .ui-col.win')].map(c => c.dataset.v)")
            check(f"{tag}: окно категории открылось на выбранном месяце {dflt}", dflt == ["2026-10"])
            pg.click('.ui-modal .ui-col[data-v="2026-10"]')
            pg.evaluate("document.getElementById('yoyb-0').scrollTop = 40")
            sc0 = pg.evaluate("document.getElementById('yoyb-0').scrollTop")
            ctop = pg.evaluate("document.querySelector('.ui-modal .ui-cols').getBoundingClientRect().top")
            pg.click('.ui-modal .ui-col[data-v="2026-05"]')
            pg.click('.ui-modal .ui-col[data-v="2026-07"]')
            # итог — под графиком: выбор месяцев не двигает столбики (телефон, 2026-10-07)
            ctop2 = pg.evaluate("document.querySelector('.ui-modal .ui-cols').getBoundingClientRect().top")
            check(f"{tag}: выбор месяцев не двигает график в окне ({ctop:.0f} → {ctop2:.0f})", abs(ctop2 - ctop) <= 1)
            chosen = pg.evaluate("[...document.querySelectorAll('.ui-modal .ui-col.win')].map(c => c.dataset.v)")
            check(f"{tag}: в окне выбраны два месяца {chosen}", chosen == ["2026-05", "2026-07"])
            check(f"{tag}: итог — за выбранные месяцы", "Май, июл:" in pg.inner_text(".ui-modal .ui-modal-body"))
            check(f"{tag}: прокрутка окна не сбросилась ({sc0} → {pg.evaluate('document.getElementById(`yoyb-0`).scrollTop')})",
                  abs(pg.evaluate("document.getElementById('yoyb-0').scrollTop") - sc0) <= 1)
            pg.click('.ui-modal .ui-legend [data-act="yoy-m"]')
            check(f"{tag}: «все 12 месяцев» снимает выбор", pg.locator(".ui-modal .ui-col.win").count() == 0)
            check(f"{tag}: страница под окном не шире экрана", pg.evaluate("document.documentElement.scrollWidth") <= w + 1)
            pg.keyboard.press("Escape")
            pg.wait_for_selector(".ui-modal", state="detached")
            check(f"{tag}: Esc закрывает окно", pg.locator(".ui-modal").count() == 0)
            check(f"{tag}: «прочие» не в общем «Где тратил»",
                  pg.evaluate("[...document.querySelectorAll('.ui-card .ui-two .ui-ell')].every(e => e.textContent !== 'прочие' && e.textContent !== 'без места')"))
            check(f"{tag}: разовая названа в «Вне обычных»", "Холодильник.ру" in pg.inner_text("body"))
            # раскрытых может быть несколько; стрелка в шапке сворачивает все и раскрывает все
            pg.click('[data-act="cat"][data-v="Транспорт"]')
            pg.wait_for_selector('.ui-catopen #cr-' + pg.evaluate("encodeURIComponent('Транспорт').replace(/%/g,'_')"))
            check(f"{tag}: открыты две категории сразу", pg.locator(".ui-catopen").count() == 2)
            pg.evaluate("document.getElementById('cat-all').scrollIntoView({block:'center'})")
            btop = pg.evaluate("document.getElementById('cat-all').getBoundingClientRect().top")
            pg.click('[data-act="cat-all"]')
            pg.wait_for_selector(".ui-catdetail", state="detached")
            check(f"{tag}: стрелка «все» свернула все", pg.locator(".ui-catopen").count() == 0)
            atop = pg.evaluate("document.getElementById('cat-all').getBoundingClientRect().top")
            check(f"{tag}: после «свернуть все» кнопка на месте ({btop:.0f} → {atop:.0f})", abs(atop - btop) <= 1)
            pg.click('[data-act="cat-all"]')
            pg.wait_for_selector(".ui-catopen")
            check(f"{tag}: стрелка «все» раскрыла все", pg.locator(".ui-catopen").count() == pg.locator(".ui-catrow[data-v]").count())
            pg.click('[data-act="cat-all"]')
            pg.wait_for_selector(".ui-catdetail", state="detached")
            # окно «Обычные траты» под графиком; категория в нём — её окно поверх, Esc закрывает только верхнее
            pg.click('[data-act="yoy"][data-v=""]')
            pg.wait_for_selector(".ui-modal .ui-cols.yoy")
            pg.wait_for_function("![...document.querySelectorAll('.ui-modal *')].some(e => e.getAnimations().length)")
            y = pg.evaluate(YOY)
            check(f"{tag}: окно «Обычные траты» — 12 колонок, категории ({y['n']})", y["n"] == 12 and "Транспорт" in y["text"])
            check(f"{tag}: «Обычные траты» тоже открылись на выбранном месяце",
                  pg.evaluate("[...document.querySelectorAll('.ui-modal .ui-col.win')].map(c => c.dataset.v)") == ["2026-10"])
            pg.locator(".ui-modal").nth(0).locator('.ui-col[data-v="2026-10"]').click()
            pg.locator(".ui-modal").nth(0).locator('.ui-col[data-v="2026-05"]').click()
            pg.click('.ui-modal [data-act="yoy-cat"][data-v="Питание"]')
            pg.wait_for_function("document.querySelectorAll('.ui-modal').length === 2")
            top_ = pg.evaluate("[...document.querySelectorAll('.ui-modal-title')].map(e => e.textContent)")
            check(f"{tag}: категория открылась поверх {top_}", len(top_) == 2 and top_[1].startswith("Питание"))
            check(f"{tag}: нижнее окно — «позади» (сдвинуто), верхнее въезжает",
                  pg.evaluate("(() => { const m = document.querySelectorAll('.ui-modal'); return m[0].classList.contains('behind') && m[1].classList.contains('enter'); })()"))
            # выбор месяцев в окне категории не трогает выбор в «Обычных тратах» (2026-10-07)
            for mm in ("2026-05", "2026-06", "2026-07"):
                pg.locator(".ui-modal").nth(1).locator(f'.ui-col[data-v="{mm}"]').click()
            wins = pg.evaluate("[...document.querySelectorAll('.ui-modal')].map(m => [...m.querySelectorAll('.ui-col.win')].map(c => c.dataset.v))")
            check(f"{tag}: выбор в окнах независим {wins}", wins == [["2026-05"], ["2026-05", "2026-06", "2026-07"]])
            pg.keyboard.press("Escape")
            pg.wait_for_function("document.querySelectorAll('.ui-modal').length === 1")
            check(f"{tag}: Esc закрыл только окно категории, выбор внизу прежний",
                  pg.evaluate("[...document.querySelectorAll('.ui-modal .ui-col.win')].map(c => c.dataset.v)") == ["2026-05"]
                  and not pg.evaluate("document.querySelector('.ui-modal').classList.contains('behind')"))
            pg.keyboard.press("Escape")
            pg.wait_for_selector(".ui-modal", state="detached")
            check(f"{tag}: второй Esc закрыл «Обычные траты»", pg.locator(".ui-modal").count() == 0)
            # «Все годы»: плитка категории целиком открывает её окно
            pg.locator('[data-act="period"][data-v="years"]:visible').first.click()
            pg.wait_for_selector('[data-act="yoy-tile"]')
            check(f"{tag}: в плитках «Все годы» столбики не кнопки",
                  pg.evaluate("document.querySelectorAll('[data-act=yoy-tile] button').length") == 0)
            pg.locator('[data-act="yoy-tile"][data-v="Транспорт"]').click()
            pg.wait_for_selector(".ui-modal .ui-cols.yoy")
            check(f"{tag}: плитка открыла окно категории", pg.inner_text(".ui-modal-title").startswith("Транспорт"))
            pg.keyboard.press("Escape")
            pg.wait_for_selector(".ui-modal", state="detached")
            pg.locator('[data-act="period"][data-v="month"]:visible').first.click()
            pg.wait_for_selector("#dyn .ui-col")
            # клик по столбику не двигает график
            pg.evaluate("document.getElementById('dyn').scrollIntoView({block:'center'})")
            before = pg.evaluate(GEOM, "dyn")["top"]
            pg.locator("#dyn .ui-col:not(.gap)").nth(2).click()
            pg.wait_for_timeout(100)
            check(f"{tag}: клик по столбику не сдвигает график", abs(pg.evaluate(GEOM, "dyn")["top"] - before) <= 1)
            # список месяцев: у месяца без аудита — число операций из итогов (2026-10-06)
            jun = pg.evaluate("[...document.querySelectorAll('[role=option], .ui-select-opt, li')].map(e => e.textContent).filter(t => t.includes('Июнь 2026'))")
            check(f"{tag}: месяц без аудита — с числом операций {jun[:1]}", bool(jun) and all("операц" in t for t in jun))
            # обзор: компактные графики
            pg.evaluate("localStorage.setItem('money-tab','overview')")
            pg.reload()
            pg.wait_for_selector("#ov-reg .ui-col")
            for cid in ("ov-reg", "ov-left"):
                check(f"{tag} {cid}: подписи месяцев не наезжают", pg.evaluate(OVERLAP, cid) == 0)
                g = pg.evaluate(GEOM, cid)
                check(f"{tag} {cid}: слой линии той же ширины, что колонки", abs(g["svgW"] - g["colsW"]) <= 1)
            # факт о категории → окно категории поверх Обзора, месяцы факта выбраны
            pg.click('[data-act="yoy-fact"]')
            pg.wait_for_selector(".ui-modal .ui-cols.yoy")
            win = pg.evaluate("[...document.querySelectorAll('.ui-modal .ui-col.win')].map(c => c.dataset.v)")
            check(f"{tag}: факт — окно категории с месяцами факта {win}, Обзор на месте",
                  win == ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"] and pg.locator("#ov-reg").count() == 1
                  and "+62%" in pg.inner_text(".ui-modal"))
            pg.click('.ui-modal-x')
            pg.wait_for_selector(".ui-modal", state="detached")
            check(f"{tag}: ✕ закрывает окно", pg.locator(".ui-modal").count() == 0)
            # «Качество учёта»: места платежа — число и разбивка, страница не шире экрана
            pg.evaluate("localStorage.setItem('money-tab','quality')")
            pg.reload()
            pg.wait_for_selector(".ui-fold")
            q = pg.inner_text(".ui-main")
            check(f"{tag}: места платежа — 23 места, разбивка и подсказка",
                  "23 места поправить" in q and "совместить 2, переименовать 18, без места 3" in q and "проверь места платежа" in q)
            check(f"{tag}: принятые как норма — «разобрано», не открыты",
                  "Одинаковые операции (вопрос) · разобрано" in q and "Замечаний нет — всё разобрано · за месяц принято как есть 2" in q
                  and "исправить в приложении" not in q)
            check(f"{tag}: «Открыто замечаний» называет месяц", "по всей истории: Сентябрь 2026 — 1" in q)
            ot = pg.evaluate("[...document.querySelectorAll('.ui-tile')].map(t => t.innerText).filter(t => /открыто замечаний/i.test(t))[0] || ''")
            check(f"{tag}: «Открыто замечаний» — по статусам (1), не по снимку записи (2): {ot[:60]!r}",
                  ot.split("\n")[1].strip() == "1" and "дольше 1" in ot)
            pg.click('.ui-tile [data-act="quality-month"]')
            pg.wait_for_timeout(200)
            q2 = pg.inner_text(".ui-main")
            check(f"{tag}: клик по месяцу — «Качество» за сентябрь с открытым замечанием",
                  "1 замечание на 4,00 ₽ открыто" in q2 and not re.search(r"(?<![\d,])0,0 тыс", q2) and " открыто — исправить в приложении ZenMoney" in q2 and "Без категории · " not in q2)
            check(f"{tag}: «Качество» без прокрутки вбок",
                  pg.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0)
            check(f"{tag}: ошибок JS нет {errs[:1]}", not errs)
            ctx.close()
        browser.close()

srv.shutdown()
shutil.rmtree(root, ignore_errors=True)
if not ENGINES:
    print("money_layout: пропуск — ни одного движка")
    sys.exit(0)
print(f"\nmoney_layout: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
