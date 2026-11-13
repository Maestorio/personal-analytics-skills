#!/usr/bin/env python3
"""График маркера «Здоровья» (ui-kit 1.53.0 uiTimeChartHTML, health v1.45) и пара
«давление верхнее/нижнее» одной карточкой — настоящими браузерами Chromium + WebKit,
синтетические данные, Synology не нужен.

Было (до 2026-10-23): вся история — во всю ширину; ежедневные самоизмерения давления
за 6 лет сжимались в вертикальную «пилу», линия через паузы в полтора года рисовала
тренд, которого никто не мерил; верхнее и нижнее — две карточки. Стало: длинная
плотная история — ~полгода на экран с прокруткой (открыта на последних замерах),
паузы — разрыв с подписью, частые замеры — медиана недели с усиком; редкий
показатель — как раньше во всю ширину; пара — одна строка каталога «120/80»,
второй маркер пары (ссылка из исследования) открывает ту же карточку.

Нет playwright или движка — честный пропуск, не падение.
"""
import datetime as dt
import json
import sys
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
    print("health_chart: пропуск — нет playwright")
    sys.exit(0)


def pt(date, value, lab="Самоизмерение", study=None):
    p = {"date": date, "value": value, "text": None, "unit": "мм рт. ст.", "ref": None, "status": "na", "lab": lab}
    if study:
        p["study"] = study
    return p


# давление: через день восемь месяцев 2021, ежедневно февраль 2023, потом редкие замеры
DATES = [str(dt.date(2021, 1, 1) + dt.timedelta(days=2 * i)) for i in range(120)] + \
        [str(dt.date(2023, 2, 6) + dt.timedelta(days=i)) for i in range(10)] + ["2025-10-16"]
SYS = [pt(d, 115 + i % 13) for i, d in enumerate(DATES)] + [pt("2026-10-15", 120, "Поликлиника", "sx")]
DIA = [pt(d, 70 + i % 11) for i, d in enumerate(DATES)] + [pt("2026-10-15", 80, "Поликлиника", "sx")]

LABS = {
    "schema": "health-labs@1", "generated": "2026-10-23", "source": "test",
    "person": {"sex": "m", "age_at_export": 37},
    "categories": [{"key": "exam", "name": "Общий осмотр"}, {"key": "biochem", "name": "Биохимия крови"}],
    "biomarkers": [
        {"id": "exam_bp_sys", "name": "АД систолическое", "category": "exam", "kind": "num",
         "unit": "мм рт. ст.", "ref": None, "series": SYS},
        {"id": "exam_bp_dia", "name": "АД диастолическое", "category": "exam", "kind": "num",
         "unit": "мм рт. ст.", "ref": None, "series": DIA},
        {"id": "chol", "name": "Холестерин", "category": "biochem", "kind": "num", "unit": "ммоль/л", "ref": None,
         "series": [{"date": f"{2024 + (i // 12)}-{i % 12 + 1:02d}-10", "value": 4.5 + i % 4 / 10, "text": None,
                     "unit": "ммоль/л", "ref": None, "status": "na", "lab": None} for i in range(15)]},
        {"id": "ldh", "name": "ЛДГ", "category": "biochem", "kind": "num", "unit": "МЕ/л",
         "ref": {"low": 122, "high": 222},
         "series": [{"date": d, "value": v, "text": None, "unit": "МЕ/л", "ref": {"low": 122, "high": 222},
                     "status": "norm", "lab": None} for d, v in (("2021-03-01", 170), ("2023-04-01", 190), ("2025-03-01", 180))]},
    ]}
FILES = {"anamnesis": {"schema": "health-anamnesis@1", "updated": "2026-11-02", "family": []},
         "meds": {"schema": "health-meds@1", "updated": "2026-10-01", "meds": []},
         "vaccinations": {"schema": "health-vaccinations@1", "updated": "2026-10-01", "vaccinations": []},
         "vitals": {"schema": "health-vitals@1", "updated": "2026-10-01", "height_cm": 180, "weight": []},
         "studies": {"schema": "health-studies@1", "updated": "2026-10-01", "studies": [
             {"id": "sx", "date": "2026-10-15", "kind": "Другое", "area": "диспансеризация", "conclusion": "",
              "clinic": "Поликлиника", "doctor": "", "file": "", "notes": ""}]}}


srv = serve(directory=REPO)[0]   # _pages_stand: очередь 128, keep-alive
URL = f"http://127.0.0.1:{srv.server_address[1]}/tools/health.html"


def wire(pg):
    def fulfill(route, obj):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(obj, ensure_ascii=False))

    pg.route("**/health-data/labs.json*", lambda r: fulfill(r, LABS))
    pg.route("**/health-data/biomarkers-info.json*", lambda r: fulfill(r, {}))
    pg.route("**/health-data/reports/**", lambda r: fulfill(r, []))
    pg.route("**/api/health*", lambda r: fulfill(r, {"health_writable": True, "health_files": list(FILES)}))
    def hd(r):
        name = r.request.url.split("path=")[1].split(".json")[0]
        if name == "labs":      # сайдкар без labs в API → страница читает прежним путём (health-data/labs.json)
            return r.fulfill(status=404, content_type="application/json", body="{}")
        return fulfill(r, {"hash": "h1", "content": json.dumps(FILES[name], ensure_ascii=False)})
    pg.route("**/api/hd/**", hd)


SC = "(() => { const e = document.querySelector('.ui-pane .ui-tchart-sc'); return e ? {wide: e.classList.contains('wide'), left: e.scrollLeft, cw: e.clientWidth, sw: e.scrollWidth} : null; })()"
TITLE = "(() => { const p = [...document.querySelectorAll('.ui-pane')].pop(); return p ? p.querySelector('.ui-pane-title').textContent : null; })()"


def open_markers(pg):
    pg.goto(URL)
    pg.wait_for_selector('[data-act="tab"][data-id="markers"]', state="attached", timeout=15000)
    pg.locator('[data-act="tab"][data-id="markers"]:visible').first.click()
    pg.wait_for_selector(".mrow")


def run(eng_name, eng):
    try:
        br = eng.launch()
    except Exception as e:
        print(f"health_chart: пропуск {eng_name} — движок не запускается ({str(e)[:60]})")
        return
    tag = eng_name
    pg = br.new_page(viewport={"width": 1280, "height": 900})
    wire(pg)
    open_markers(pg)
    rows = pg.evaluate("[...document.querySelectorAll('.mrow')].map(r => [r.dataset.id, r.querySelector('.mrow-name').textContent, r.querySelector('.mval').textContent])")
    ids = [r[0] for r in rows]
    check(f"{tag}: пара — одна строка каталога ({ids})", "exam_bp_sys" in ids and "exam_bp_dia" not in ids)
    bp = [r for r in rows if r[0] == "exam_bp_sys"]
    check(f"{tag}: строка пары — «Артериальное давление» 120/80 ({bp})",
          bool(bp) and bp[0][1] == "Артериальное давление" and bp[0][2] == "120/80")

    pg.fill("#q", "диастол")
    pg.wait_for_timeout(100)
    check(f"{tag}: поиск по имени второго маркера находит пару",
          pg.evaluate("[...document.querySelectorAll('.mrow')].map(r => r.dataset.id)") == ["exam_bp_sys"])
    pg.fill("#q", "")
    pg.wait_for_timeout(100)

    pg.click('.mrow[data-id="exam_bp_sys"]')
    pg.wait_for_timeout(450)
    check(f"{tag}: карточка пары ({pg.evaluate(TITLE)})", pg.evaluate(TITLE) == "Артериальное давление")
    sc = pg.evaluate(SC)
    check(f"{tag}: длинная плотная история — шире экрана ({sc})", bool(sc) and sc["wide"] and sc["sw"] > sc["cw"] * 1.3)
    check(f"{tag}: график открыт на последних замерах ({sc})", bool(sc) and sc["left"] + sc["cw"] >= sc["sw"] - 2)
    n = pg.evaluate("[...document.querySelectorAll('.ui-pane .ui-tchart')].map(c => [c.querySelectorAll('line.wh').length, c.querySelectorAll('text.brk').length, c.querySelectorAll('path.ln.alt').length])")
    check(f"{tag}: медианы недель, разрывы пауз, вторая линия пунктиром ({n})",
          len(n) == 1 and n[0][0] >= 6 and n[0][1] >= 2 and n[0][2] == 1)
    seg = pg.evaluate("[...document.querySelectorAll('.ui-pane [data-tc-mode]')].map(b => [b.textContent, b.getAttribute('aria-pressed')])")
    check(f"{tag}: у длинной плотной истории — переключатель, выбрано «полгода» ({seg})",
          seg == [["полгода", "true"], ["вся история", "false"]])
    pg.click('.ui-pane [data-tc-mode="all"]')
    pg.wait_for_timeout(150)
    sc = pg.evaluate(SC)
    lg = pg.evaluate("document.querySelector('.ui-pane .ui-tchart-lg').textContent")
    check(f"{tag}: «вся история» — без прокрутки, медианы месяцев ({sc}, {lg})",
          bool(sc) and not sc["wide"] and sc["sw"] <= sc["cw"] + 1 and "месяц: медиана" in lg
          and pg.evaluate("document.querySelectorAll('.ui-pane line.wh').length") >= 4)
    pg.click('.ui-pane [data-tc-mode="win"]')
    pg.wait_for_timeout(150)
    sc = pg.evaluate(SC)
    check(f"{tag}: обратно «полгода» — снова прокрутка ({sc})", bool(sc) and sc["wide"])
    h = pg.evaluate("[...document.querySelectorAll('.ui-pane-body .hist-row')].slice(0, 2).map(r => r.children[1].textContent)")
    check(f"{tag}: история — «верхнее/нижнее» в строке ({h})", bool(h) and h[0].startswith("120/80"))

    # редкий показатель — как раньше: во всю ширину, без прокрутки
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(450)
    pg.click('.mrow[data-id="ldh"]')
    pg.wait_for_timeout(450)
    sc = pg.evaluate(SC)
    check(f"{tag}: редкий показатель — без прокрутки ({sc})", bool(sc) and not sc["wide"] and sc["sw"] <= sc["cw"] + 1)
    check(f"{tag}: у редкого — без переключателя", pg.locator(".ui-pane [data-tc-mode]").count() == 0)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(450)
    pg.click('.mrow[data-id="chol"]')
    pg.wait_for_timeout(450)
    sc = pg.evaluate(SC)
    check(f"{tag}: 15 замеров за 15 месяцев — вся история, без прокрутки и переключателя ({sc})",
          bool(sc) and not sc["wide"] and pg.locator(".ui-pane [data-tc-mode]").count() == 0)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(450)

    # второй маркер пары из исследования открывает карточку пары
    pg.locator('[data-act="tab"][data-id="studies"]:visible').first.click()
    pg.wait_for_timeout(200)
    pg.locator('[data-act="study-open"]').first.click()
    pg.wait_for_timeout(450)
    link = pg.locator('.ui-pane [data-act="marker-from-study"][data-id="exam_bp_dia"]')
    if link.count():
        link.click()
        pg.wait_for_timeout(450)
        check(f"{tag}: нижнее из исследования → карточка пары ({pg.evaluate(TITLE)})",
              pg.evaluate(TITLE) == "Артериальное давление")
    else:
        check(f"{tag}: в исследовании есть ссылка на нижнее давление", False)
    pg.close()

    # телефон: прокручивается график, а не страница
    pg = br.new_page(viewport={"width": 390, "height": 800}, is_mobile=eng_name == "chromium", has_touch=True)
    wire(pg)
    open_markers(pg)
    pg.click('.mrow[data-id="exam_bp_sys"]')
    pg.wait_for_timeout(450)
    sc = pg.evaluate(SC)
    doc = pg.evaluate("document.documentElement.scrollWidth")
    check(f"{tag}: на телефоне документ не шире экрана ({doc}), график листается ({sc})",
          doc <= 390 and bool(sc) and sc["wide"] and sc["left"] > 0)
    pg.close()
    br.close()


with sync_playwright() as pw:
    run("chromium", pw.chromium)
    run("webkit", pw.webkit)
srv.shutdown()
print(f"health_chart: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
