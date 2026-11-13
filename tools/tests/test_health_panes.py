#!/usr/bin/env python3
"""Боковые панели «Здоровья» стопкой (ui-kit 1.37.0 uiPaneHTML, health v1.41) —
настоящими браузерами Chromium + WebKit, синтетические данные, Synology не нужен.

Было (до 2026-10-07): переход маркер → лекарство / маркер → исследование ЗАМЕНЯЛ
панель, а возврат держался указателем «откуда пришёл» глубиной 1 — третья
панель теряла первую. Стало: панель из панели ложится поверх (нижняя .behind),
«← …», Escape и затемнение возвращают к нижней, ✕ закрывает все; листание
стрелками — только у панели, открытой из каталога; прокрутка панели переживает
перерисовку (переключатель «принимаю»).

Нет playwright или движка — честный пропуск, не падение.
"""
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
    print("health_panes: пропуск — нет playwright")
    sys.exit(0)

LABS = {
    "schema": "health-labs@1", "generated": "2026-07-17", "source": "test",
    "person": {"sex": "m", "age_at_export": 37},
    "categories": [{"key": "biochem", "name": "Биохимия крови"}],
    "biomarkers": [
        {"id": "glucose", "name": "Глюкоза натощак", "category": "biochem", "kind": "num", "unit": "ммоль/л",
         "ref": {"low": 4.1, "high": 6.0},
         "series": [{"date": "2025-05-05", "value": 7.0, "text": None, "unit": "ммоль/л",
                     "ref": {"low": 4.1, "high": 6.0}, "status": "high", "lab": None, "study": "sx"},
                    {"date": "2026-10-10", "value": 6.5, "text": None, "unit": "ммоль/л",
                     "ref": {"low": 4.1, "high": 6.0}, "status": "high", "lab": None}]},
        {"id": "ldh", "name": "ЛДГ", "category": "biochem", "kind": "num", "unit": "МЕ/л",
         "ref": {"low": 122, "high": 222},
         "series": [{"date": "2024-03-01", "value": 180, "text": None, "unit": "МЕ/л",
                     "ref": {"low": 122, "high": 222}, "status": "norm", "lab": None}]},
        {"id": "crp", "name": "СРБ", "category": "biochem", "kind": "num", "unit": "мг/л",
         "ref": {"low": 0, "high": 5},
         "series": [{"date": "2026-10-03", "value": 2.0, "text": None, "unit": "мг/л",
                     "ref": {"low": 0, "high": 5}, "status": "norm", "lab": None},
                    {"date": "2026-10-12", "value": 9.0, "text": None, "unit": "мг/л",
                     "ref": {"low": 0, "high": 5}, "status": "high", "lab": None}]},
        {"id": "hb", "name": "Гемоглобин", "category": "biochem", "kind": "num", "unit": "г/л",
         "ref": {"low": 130, "high": 170},
         "series": [{"date": "2023-03-14", "value": 140, "text": None, "unit": "г/л",
                     "ref": {"low": 130, "high": 170}, "status": "norm", "lab": None},
                    {"date": "2023-04-10", "value": 120, "text": None, "unit": "г/л",
                     "ref": {"low": 130, "high": 170}, "status": "low", "lab": None}]},
        {"id": "lng", "name": "Лонг-маркер", "category": "biochem", "kind": "num", "unit": "у.е.",
         "ref": {"low": 0, "high": 5},
         "series": [{"date": "2026-04-15", "value": 3.0, "text": None, "unit": "у.е.",
                     "ref": {"low": 0, "high": 5}, "status": "norm", "lab": None},
                    {"date": "2026-07-10", "value": 8.0, "text": None, "unit": "у.е.",
                     "ref": {"low": 0, "high": 5}, "status": "high", "lab": None}]},
    ]}
MED = {"id": "m0", "name": "Метформин", "inn": "метформин", "for": "", "class": "", "dose": "", "regimen": "",
       "timing": "", "form": "таблетки", "taking": False, "archived": False, "prescribedBy": "",
       "expiry": "2027-01", "affects": ["glucose"], "indications": "справка " * 400, "interactions": "",
       "notes": "", "group": ""}
SELF = {"allergies_checked": False, "allergies": [], "history": [
    {"id": "ev1", "name": "Пневмония", "kind": "illness", "group": "other", "start": "2026-10-01", "end": "2026-10-05",
     "status": "resolved", "treatment": "антибиотик", "certainty": "known", "study": "sx", "note": ""},
    {"id": "ev2", "name": "Операция", "kind": "surgery", "group": "other", "start": "2026-10-05", "end": None,
     "status": "resolved", "treatment": "", "certainty": "known", "study": None, "note": "", "window_before": 3},
    {"id": "ev3", "name": "Грипп", "kind": "illness", "group": "other", "start": "2023-03", "end": None,
     "status": "resolved", "treatment": "", "certainty": "known", "study": None, "note": ""},
    {"id": "ev4", "name": "Ожирение", "kind": "chronic", "group": "other", "start": "2025-01", "end": None,
     "status": "active", "treatment": "", "certainty": "known", "study": None, "note": "",
     "markers": ["glucose", "vitals_weight", "ghost"]},
    {"id": "ev5", "name": "Диабет", "kind": "chronic", "group": "other", "start": "2020", "end": None,
     "status": "active", "treatment": "", "certainty": "known", "study": None, "note": ""},
    {"id": "ev7", "name": "Хроника А", "kind": "chronic", "group": "other", "start": "2020", "end": None,
     "status": "active", "treatment": "", "certainty": "known", "study": None, "note": "",
     "markers": ["ldh", "glucose", "crp", "hb", "ghost"]},
    {"id": "ev8", "name": "Хроника Б", "kind": "chronic", "group": "other", "start": "2026-11-01", "end": None,
     "status": "active", "treatment": "", "certainty": "known", "study": None, "note": "",
     "markers": ["crp", "ghost"]},
    {"id": "ev6", "name": "Долгая болезнь", "kind": "illness", "group": "other", "start": "2026-03-01", "end": "2026-06-30",
     "status": "resolved", "treatment": "", "certainty": "known", "study": None, "note": ""}]}
FILES = {"anamnesis": {"schema": "health-anamnesis@1", "updated": "2026-11-02", "family": [], "self": SELF},
         "meds": {"schema": "health-meds@1", "updated": "2026-10-01", "meds": [MED]},
         "vaccinations": {"schema": "health-vaccinations@1", "updated": "2026-10-01", "vaccinations": []},
         "vitals": {"schema": "health-vitals@1", "updated": "2026-10-01", "height_cm": 180, "weight": [{"id": "w1", "date": "2024-12-01", "kg": 110}, {"id": "w2", "date": "2026-10-01", "kg": 100}]},
         "studies": {"schema": "health-studies@1", "updated": "2026-10-01", "studies": [
             {"id": "sx", "date": "2025-05-05", "kind": "УЗИ", "area": "брюшная полость", "conclusion": "норма",
              "clinic": "", "doctor": "", "file": "", "notes": ""}]}}


srv = serve(directory=REPO)[0]   # _pages_stand: очередь 128, keep-alive
URL = f"http://127.0.0.1:{srv.server_address[1]}/tools/health.html"


def wire(pg):
    def fulfill(route, obj):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(obj, ensure_ascii=False))

    pg.route("**/health-data/labs.json*", lambda r: fulfill(r, LABS))
    pg.route("**/health-data/biomarkers-info.json*", lambda r: fulfill(r, {}))
    pg.route("**/health-data/reports/**", lambda r: fulfill(r, []))
    pg.route("**/api/health*", lambda r: fulfill(r, {"health_writable": True, "health_files": list(FILES)}))

    def hd(route):
        req = route.request
        if req.method == "POST":
            return fulfill(route, {"hash": "h2"})
        name = req.url.split("path=")[1].split(".json")[0]
        if name == "labs":      # сайдкар без labs в API → страница читает прежним путём (health-data/labs.json)
            return route.fulfill(status=404, content_type="application/json", body="{}")
        return fulfill(route, {"hash": "h1", "content": json.dumps(FILES[name], ensure_ascii=False)})
    pg.route("**/api/hd/**", hd)


PANES = "[...document.querySelectorAll('.ui-pane')].map(p => p.className)"
TOP = "(() => { const p = [...document.querySelectorAll('.ui-pane')].pop(); return p ? p.querySelector('.ui-pane-title').textContent : null; })()"
BACK = "(() => { const p = [...document.querySelectorAll('.ui-pane')].pop(); const b = p && p.querySelector('.ui-pane-back'); return b ? b.textContent : null; })()"


def run(eng_name, eng):
    try:
        br = eng.launch()
    except Exception as e:
        print(f"health_panes: пропуск {eng_name} — движок не запускается ({str(e)[:60]})")
        return
    tag = eng_name
    pg = br.new_page(viewport={"width": 1280, "height": 900})
    wire(pg)
    pg.goto(URL)
    pg.wait_for_selector('.attn-card[data-id="glucose"]', timeout=15000)
    pg.click('.attn-card[data-id="glucose"]')
    pg.wait_for_timeout(350)
    m = pg.evaluate(PANES)
    check(f"{tag}: маркер — одна панель, въезжает ({m})", len(m) == 1 and "enter" in m[0])
    check(f"{tag}: у панели из каталога — стрелки, «назад» нет",
          pg.locator(".ui-pane .ui-pane-nav").count() == 1 and pg.evaluate(BACK) is None)

    # маркер → лекарство → маркер: три панели стопкой, первая не потерялась
    pg.click('.ui-pane [data-act="med-open-from-marker"][data-id="m0"]')
    pg.wait_for_timeout(350)
    m = pg.evaluate(PANES)
    check(f"{tag}: лекарство поверх маркера ({m})",
          len(m) == 2 and "behind" in m[0] and "enter" in m[1] and "stacked" in m[1])
    check(f"{tag}: «← Глюкоза…» у лекарства ({pg.evaluate(BACK)})", "Глюкоза натощак" in (pg.evaluate(BACK) or ""))
    pg.locator(".ui-pane").nth(1).locator('[data-act="open-from-med"][data-id="glucose"]').click()
    pg.wait_for_timeout(350)
    m = pg.evaluate(PANES)
    check(f"{tag}: третья панель — маркер поверх лекарства ({len(m)})", len(m) == 3 and "behind" in m[1])
    check(f"{tag}: у маркера из лекарства — «← Метформин», без стрелок",
          "Метформин" in (pg.evaluate(BACK) or "") and pg.locator(".ui-pane").nth(2).locator(".ui-pane-nav").count() == 0)
    pg.keyboard.press("ArrowRight")
    pg.wait_for_timeout(200)
    check(f"{tag}: стрелки не листают маркер, открытый из лекарства", pg.evaluate(TOP) == "Глюкоза натощак")

    # Escape и «←» — по одной назад; нижняя возвращается на место
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(450)
    m = pg.evaluate(PANES)
    check(f"{tag}: Escape — назад к лекарству ({m})", len(m) == 2 and pg.evaluate(TOP) == "Метформин" and "behind" not in m[1])
    pg.click(".ui-pane-back")
    pg.wait_for_timeout(450)
    m = pg.evaluate(PANES)
    check(f"{tag}: «←» — назад к маркеру, стрелки на месте ({m})",
          len(m) == 1 and "behind" not in m[0] and pg.locator(".ui-pane .ui-pane-nav").count() == 1)

    # маркер → исследование: подпись «назад» с датой; ✕ закрывает всё
    pg.click('.ui-pane [data-act="study-from-marker"][data-id="sx"]')
    pg.wait_for_timeout(350)
    check(f"{tag}: исследование поверх маркера", len(pg.evaluate(PANES)) == 2 and pg.evaluate(TOP) == "брюшная полость")
    pg.locator(".ui-pane").nth(1).locator('[data-act="marker-from-study"]').first.click()
    pg.wait_for_timeout(350)
    check(f"{tag}: маркер из исследования — «← УЗИ… · дата» ({pg.evaluate(BACK)})",
          len(pg.evaluate(PANES)) == 3 and "2025" in (pg.evaluate(BACK) or ""))
    pg.locator(".ui-pane").nth(2).locator(".ui-pane-x").click()
    pg.wait_for_timeout(450)
    check(f"{tag}: ✕ закрывает все панели", pg.evaluate(PANES) == [])

    # листание стрелкой — та же панель, без повторного въезда
    pg.click('.attn-card[data-id="glucose"]')
    pg.wait_for_timeout(350)
    pg.keyboard.press("ArrowRight")
    pg.wait_for_timeout(200)
    m = pg.evaluate(PANES)
    check(f"{tag}: стрелка листает каталог в той же панели ({pg.evaluate(TOP)}, {m})",
          pg.evaluate(TOP) == "ЛДГ" and len(m) == 1 and "enter" not in m[0])
    pg.click(".ui-pane-bg", position={"x": 30, "y": 400})
    pg.wait_for_timeout(450)
    check(f"{tag}: затемнение закрывает панель", pg.evaluate(PANES) == [])

    # Escape, закрывающий панель, — с preventDefault (иначе Mac сначала выходит из
    # полноэкранного режима браузера); когда закрывать нечего — событие не трогаем
    ESC = "(() => { const e = new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}); document.dispatchEvent(e); return e.defaultPrevented; })()"
    pg.click('.attn-card[data-id="glucose"]')
    pg.wait_for_timeout(350)
    check(f"{tag}: Escape на открытой панели — defaultPrevented", pg.evaluate(ESC) is True)
    pg.wait_for_timeout(450)
    check(f"{tag}: Escape, когда закрывать нечего, — событие не тронуто", pg.evaluate(ESC) is False)

    # строка списка исследований подсвечивается целиком (hover, фон строки)
    if eng_name == "chromium":
        pg.locator('.ui-rail [data-act="tab"][data-id="studies"]').click()
        pg.wait_for_timeout(250)
        row = pg.locator(".rep-row").first
        bg0 = row.evaluate("e => getComputedStyle(e).backgroundColor")
        row.hover()
        pg.wait_for_timeout(300)
        bg1 = row.evaluate("e => getComputedStyle(e).backgroundColor")
        check(f"{tag}: hover по строке исследования меняет фон всей строки ({bg0} → {bg1})", bg0 != bg1)

    # прокрутка панели лекарства переживает перерисовку (переключатель «принимаю»)
    pg.goto(URL)
    pg.wait_for_selector('.attn-card[data-id="glucose"]', timeout=15000)
    pg.click('.attn-card[data-id="glucose"]')
    pg.wait_for_timeout(300)
    pg.click('.ui-pane [data-act="med-open-from-marker"][data-id="m0"]')
    pg.wait_for_selector('#pane-b-1 [data-act="med-toggle"]')   # под нагрузкой пауза не успевала
    pg.wait_for_timeout(400)
    pg.evaluate("document.getElementById('pane-b-1').scrollTop = 300")
    sc0 = pg.evaluate("document.getElementById('pane-b-1').scrollTop")
    # клик из JS: playwright перед кликом сам прокрутил бы к переключателю (он вверху)
    pg.evaluate("document.querySelector('.ui-pane [data-act=med-toggle]').click()")
    pg.wait_for_timeout(500)
    sc1 = pg.evaluate("document.getElementById('pane-b-1') && document.getElementById('pane-b-1').scrollTop")
    check(f"{tag}: прокрутка панели не сбросилась ({sc0} → {sc1})", sc0 > 0 and sc1 is not None and abs(sc1 - sc0) <= 1)
    pg.close()

    # формы и справка (ui-kit 1.38.0): въезжают при открытии, НЕ въезжают заново на
    # перерисовке (ввод, выбор), уходят плавно — раньше появлялись и исчезали рывком
    pg = br.new_page(viewport={"width": 1280, "height": 900})
    wire(pg)
    pg.goto(URL)
    pg.wait_for_selector('.attn-card[data-id="glucose"]', timeout=15000)
    MOD = "[...document.querySelectorAll('.ui-modal')].map(m => m.className)"
    for tab, add in (("vax", "vax-add"), ("meds", "med-add")):
        pg.locator(f'.ui-rail [data-act="tab"][data-id="{tab}"]').click()
        pg.wait_for_timeout(200)
        pg.locator(f'[data-act="{add}"]:visible').first.click()
        pg.wait_for_timeout(100)
        m = pg.evaluate(MOD)
        check(f"{tag}: форма {add} въезжает ({m})", len(m) == 1 and "enter" in m[0])
        pg.locator(".ui-modal .ui-modal-cancel").click()
        pg.wait_for_timeout(60)
        m = pg.evaluate(MOD)
        check(f"{tag}: «Отмена» в {add} — окно уходит плавно ({m})", len(m) == 1 and "leave" in m[0])
        pg.wait_for_timeout(400)
        check(f"{tag}: форма {add} закрыта", pg.evaluate(MOD) == [])
    pg.locator('[data-act="med-add"]:visible').first.click()
    pg.wait_for_timeout(100)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(60)
    check(f"{tag}: Escape — форма уходит плавно", "leave" in (pg.evaluate(MOD) or [""])[0])
    pg.wait_for_timeout(400)
    pg.click('[data-ui-help]')
    pg.wait_for_timeout(100)
    check(f"{tag}: справка въезжает", pg.evaluate("!!document.querySelector('.uh-overlay.enter')"))
    pg.click("[data-uh-close]")
    pg.wait_for_timeout(60)
    check(f"{tag}: справка уходит плавно",
          pg.evaluate("!!document.querySelector('.uh-overlay.leave')")
          and pg.evaluate("document.documentElement.style.overflow") != "hidden")
    pg.wait_for_timeout(400)
    check(f"{tag}: справка убрана", pg.evaluate("document.querySelectorAll('.uh-overlay').length") == 0)
    pg.close()

    # раздел «Я» анамнеза (контракт §13): вид по умолчанию, пометка «болел ли тогда» в истории
    pg = br.new_page(viewport={"width": 1280, "height": 900})
    wire(pg)
    pg.goto(URL)
    pg.wait_for_selector('[data-act="tab"][data-id="anamnesis"]', timeout=15000)
    pg.locator('[data-act="tab"][data-id="anamnesis"]').first.click()
    pg.wait_for_selector('[data-act="anam-view"]', timeout=15000)
    check(f"{tag}: вкладка «Анамнез» открывается на виде «Я»",
          pg.locator('[data-act="anam-view"][data-id="self"][aria-pressed="true"]').count() == 1)
    body = pg.inner_text("body")
    check(f"{tag}: «Я» — при пустых аллергиях блока нет (ни «Не заполнено», ни «Аллергий нет»), событие и ссылка на исследование",
          "Аллергии" not in body.replace("Добавить аллергию", "") and "Не заполнено" not in body and "Аллергий нет" not in body and "Пневмония" in body and "01.10.2026 – 05.10.2026" in body
          and pg.locator('[data-act="study-open"][data-id="sx"]').count() == 1)
    check(f"{tag}: кнопка «Добавить аллергию» одна", pg.locator('[data-act="an-alg-add"]').count() == 1)
    # «С какого года» — поле неполной даты в режиме «только год»
    pg.click('[data-act="an-alg-add"]')
    pg.wait_for_selector("#fv-asince", timeout=5000)
    pg.fill("#fv-asince", "0315")
    pg.wait_for_timeout(100)
    check(f"{tag}: аллергия, «0315» в поле года — подсказка «не год», скрытое пусто",
          "не год" in pg.inner_text("#fh-asince") and pg.input_value("#f-asince") == "")
    pg.fill("#fv-asince", "")
    pg.click('[data-fd-open="asince"]')
    pg.wait_for_selector(".dp-pop", timeout=3000)
    check(f"{tag}: календарь года — без переключателя точности, сразу сетка лет",
          pg.locator(".dp-pop .dp-prec").count() == 0 and pg.locator(".dp-pop .dp-yr").count() == 12)
    pg.locator('.dp-pop [data-y="2015"]').click() if pg.locator('.dp-pop [data-y="2015"]').count() else pg.locator(".dp-pop .dp-yr").first.click()
    pg.wait_for_timeout(100)
    yv = pg.input_value("#f-asince")
    check(f"{tag}: выбор года в календаре — в поле только год ({yv!r})", len(yv) == 4 and yv.isdigit() and pg.input_value("#fv-asince") == yv)
    pg.reload()
    pg.wait_for_selector(".attn-card", timeout=15000)
    pg.locator('[data-act="tab"][data-id="anamnesis"]').first.click()
    pg.wait_for_selector('[data-act="anam-view"]', timeout=15000)
    check(f"{tag}: в строке события — счётчик «показателей рядом»", "рядом" in body)
    pg.locator('[data-act="an-ev-open"][data-id="ev2"]').click()
    pg.wait_for_timeout(350)
    pt = pg.inner_text(".ui-pane")
    check(f"{tag}: панель события открывается, в ней строка СРБ со значениями до и после ({pt[:80]!r})",
          pg.evaluate(TOP) == "Операция" and pg.locator('.ui-pane [data-act="marker-from-study"][data-id="crp"]').count() == 1
          and "03.10.2026" in pt and "12.10.2026" in pt and "+7 дн." in pt)
    pg.locator('.ui-pane [data-act="marker-from-study"][data-id="crp"]').click()
    pg.wait_for_timeout(350)
    check(f"{tag}: биомаркер из события — поверх, стопкой", pg.evaluate(TOP) == "СРБ" and len(pg.evaluate(PANES)) == 2
          and "за 2 дн. до: Операция" in pg.inner_text(".ui-pane >> nth=1"))
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(350)
    check(f"{tag}: Escape возвращает к событию", pg.evaluate(TOP) == "Операция")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(350)
    check(f"{tag}: Escape закрывает панель события", len(pg.evaluate(PANES)) == 0)
    pg.click('[data-act="an-ev-add"]')
    pg.wait_for_selector("#f-evname")
    pg.fill("#f-evname", "Тест")
    pg.click('.ui-modal [data-act="an-ev-save"]')
    pg.wait_for_timeout(200)
    check(f"{tag}: без начала событие не сохраняется (форма осталась)", pg.locator("#f-evname").count() == 1)
    # «Начало» и «Окончание» — в одну строку (поля по верху на одной линии) и на 1280, и на 375
    for vw in (1280, 375):
        pg.set_viewport_size({"width": vw, "height": 900})
        pg.wait_for_timeout(150)
        bs, be = pg.locator("#fv-evs").bounding_box(), pg.locator("#fv-eve").bounding_box()
        check(f"{tag}: {vw} px — «Начало» и «Окончание» в одну строку ({bs['y']:.0f} / {be['y']:.0f}), без пересечения",
              abs(bs["y"] - be["y"]) <= 2 and bs["x"] + bs["width"] <= be["x"] + 1 and be["width"] > 100)
    pg.set_viewport_size({"width": 1280, "height": 900})
    # поле неполной даты (ui-kit 1.65.0): цифры без автомаски, подсказка, календарь с точностью
    pg.fill("#fv-evs", "032023")
    check(f"{tag}: «032023» — подсказка «март 2023 · месяц», скрытое = 2023-03",
          pg.inner_text("#fh-evs").strip() == "март 2023 · месяц" and pg.input_value("#f-evs") == "2023-03")
    pg.evaluate("document.getElementById('fv-evs').blur()")
    check(f"{tag}: после blur видимое «03.2023»", pg.input_value("#fv-evs") == "03.2023")
    pg.click('[data-fd-open="evs"]')
    pg.wait_for_selector(".dp-pop .dp-prec")
    check(f"{tag}: календарь открылся в точности «Месяц»",
          pg.locator('.dp-pop .dp-prec button.on').get_attribute("data-prec") == "m")
    pg.locator('.dp-pop .dp-prec button[data-prec="y"]').click()
    pg.locator('.dp-pop .dp-yr[data-y="2021"]').click()
    check(f"{tag}: сегмент «Год» + 2021 — #f-evs == 2021, видимое «2021», попап закрыт",
          pg.input_value("#f-evs") == "2021" and pg.input_value("#fv-evs") == "2021"
          and pg.locator(".dp-pop").count() == 0)
    pg.fill("#fv-evs", "13.2024")
    pg.evaluate("document.getElementById('fv-evs').blur()")
    check(f"{tag}: «13.2024» — после blur is-invalid, скрытое пусто",
          "is-invalid" in (pg.get_attribute("#fv-evs", "class") or "") and pg.input_value("#f-evs") == "")
    pg.fill("#fv-evs", "15032024")
    check(f"{tag}: 8 цифр «15032024» — #f-evs == 2024-03-15", pg.input_value("#f-evs") == "2024-03-15")
    pg.fill("#fv-evs", "2023")
    pg.click('.ui-modal [data-act="an-ev-save"]')
    pg.wait_for_timeout(200)
    check(f"{tag}: болезнь без окончания не сохраняется (форма осталась)", pg.locator("#f-evname").count() == 1
          and "обязательно" in pg.inner_text("body").lower())
    pg.goto(URL)
    pg.wait_for_selector('.attn-card[data-id="glucose"]', timeout=15000)
    pg.click('.attn-card[data-id="glucose"]')
    pg.wait_for_timeout(350)
    pt = pg.inner_text(".ui-pane")
    check(f"{tag}: в истории измерений «через 5 дн. после: Пневмония»", "через 5 дн. после: Пневмония" in pt)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(450)
    check(f"{tag}: давнее отклонение (гемоглобин, 2023) не карточка, счётчик «Требует внимания» считает свежие",
          pg.locator('.attn-card[data-id="hb"]').count() == 0 and pg.locator('.attn-card').count() == 3
          and pg.locator('[data-act="old-dev"]').count() == 1 and "Давние отклонения: 1" in pg.inner_text('[data-act="old-dev"]')
          and pg.locator('.old-dev-list').count() == 0)
    pg.click('[data-act="old-dev"]')
    pg.wait_for_timeout(450)
    check(f"{tag}: строка давних раскрывается списком с гемоглобином", pg.locator('.old-dev-list [data-act="open"][data-id="hb"]').count() == 1)
    pg.click('.old-dev-list [data-act="open"][data-id="hb"]')
    pg.wait_for_timeout(350)
    pt = pg.inner_text(".ui-pane")
    check(f"{tag}: событие «2023-03» без конца: точка 14.03 — «во время», 10.04 — «через 10 дн. после»",
          "во время: Грипп" in pt and "через 10 дн. после: Грипп" in pt)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(450)
    pg.click('.attn-card[data-id="lng"]')
    pg.wait_for_timeout(350)
    pt = pg.inner_text(".ui-pane")
    check(f"{tag}: длинная болезнь (>60 дн.) не даёт «во время», «через N дн. после» остаётся",
          "во время: Долгая болезнь" not in pt and "через 10 дн. после: Долгая болезнь" in pt)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(450)
    pg.click('.attn-card[data-id="glucose"]')
    pg.wait_for_timeout(350)
    check(f"{tag}: короткая болезнь даёт «во время»-пометку там, где замер в её днях",
          "через 5 дн. после: Пневмония" in pg.inner_text(".ui-pane"))
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(450)
    pg.goto(URL)
    pg.wait_for_selector('[data-act="tab"][data-id="anamnesis"]', timeout=15000)
    pg.locator('[data-act="tab"][data-id="anamnesis"]').first.click()
    pg.wait_for_selector('[data-act="an-ev-open"][data-id="ev4"]', timeout=15000)
    check(f"{tag}: хроническая без markers не открывается, с markers — «3 показателя →»",
          pg.locator('[data-act="an-ev-open"][data-id="ev5"]').count() == 0
          and "3 показателя →" in pg.inner_text('[data-act="an-ev-open"][data-id="ev4"]'))
    pg.locator('[data-act="an-ev-open"][data-id="ev4"]').click()
    pg.wait_for_timeout(350)
    pt = pg.inner_text(".ui-pane")
    rows = pg.evaluate("[...document.querySelectorAll('.ui-pane [data-an-mk-row]')].map(r => r.innerText)")
    check(f"{tag}: панель хронической — «первый замер после начала», вес с «с начала болезни» и процентом, нет данных внизу",
          pg.evaluate(TOP) == "Ожирение" and len(rows) == 2 and "первый замер после начала: 7 ммоль/л · 05.05.2025 · −0.5 ммоль/л" in rows[0]
          and "с начала болезни: 110 кг · 01.12.2024 · −10 кг (−9%)" in rows[1] and "В НАЧАЛЕ" not in pg.inner_text(".ui-pane").upper()
          and "Нет замеров после начала болезни: Показатель не найден" in pg.inner_text(".ui-pane") and "Окно анализов" not in pg.inner_text(".ui-pane"))
    circ = pg.evaluate("[...document.querySelectorAll('.ui-pane [data-an-mk-row]')].map(r => r.querySelectorAll('svg circle').length)")
    check(f"{tag}: мини-график — точка отсчёта и последующие (вес: 2 круга)", circ[1] == 2)
    pg.locator('.ui-pane [data-act="an-mk-open"][data-id="glucose"]').click()
    pg.wait_for_timeout(350)
    check(f"{tag}: показатель из хронической — карточка поверх", pg.evaluate(TOP) == "Глюкоза натощак" and len(pg.evaluate(PANES)) == 2)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(350)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(350)
    for evid in ("ev7", "ev8"):
        pg.locator('[data-act="an-ev-open"][data-id="%s"]' % evid).click()
        pg.wait_for_timeout(350)
        if evid == "ev7":
            r7 = pg.evaluate("[...document.querySelectorAll('.ui-pane [data-an-mk-row]')].map(r => r.innerText)")
            names = [x.split("\n")[0] for x in r7]
            check(f"{tag}: смена статуса первой, затем порядок markers ({names})", names == ["СРБ", "Гемоглобин", "ЛДГ", "Глюкоза натощак"])
            check(f"{tag}: подписи смены статуса", "· стал выше нормы" in r7[0] and "· стал ниже нормы" in r7[1])
            check(f"{tag}: «больше года назад» и «единственный замер»", "больше года назад" in r7[2] and "единственный замер" in r7[2]
                  and "больше года назад" not in r7[3] and "больше года назад" not in r7[0])
            c7 = pg.evaluate("[...document.querySelectorAll('.ui-pane [data-an-mk-row]')].map(r => r.querySelectorAll('svg circle').length)")
            check(f"{tag}: единственный замер — без графика, остальные по 2 круга ({c7})", c7 == [2, 2, 0, 2])
            check(f"{tag}: «Нет замеров» — ghost", "Нет замеров после начала болезни: Показатель не найден" in pg.inner_text(".ui-pane"))
        else:
            check(f"{tag}: только замеры до начала — не строкой, а в «Нет замеров»", pg.locator(".ui-pane [data-an-mk-row]").count() == 0
                  and "Нет замеров после начала болезни: СРБ, Показатель не найден" in pg.inner_text(".ui-pane"))
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(350)
    pg.click('[data-act="an-ev-edit"][data-id="3"]')
    pg.wait_for_selector("#f-evname")
    check(f"{tag}: форма хронической — поля окна скрыты, блок связанных показателей виден, чипы есть",
          not pg.locator("[data-evwin]").is_visible() and pg.locator("[data-evmk]").is_visible()
          and pg.locator("[data-evmkbox] .ui-tag").count() == 3)
    pg.locator('[data-ui-select="f-evkind"] .ui-select-btn').click()
    pg.locator('[data-ui-select="f-evkind"] .ui-opt[data-value="illness"]').click()
    pg.wait_for_timeout(100)
    check(f"{tag}: смена вида на болезнь — окно видно, связанные скрыты, введённое не потеряно",
          pg.locator("[data-evwin]").is_visible() and not pg.locator("[data-evmk]").is_visible()
          and pg.input_value("#f-evname") == "Ожирение")
    lbl = lambda: pg.text_content('[data-evd="eve"] > .fld-lbl')
    check(f"{tag}: смена вида на болезнь — подпись окончания «обязательно для болезни» ({lbl()})", lbl() == "Окончание (обязательно для болезни)")
    pg.locator('[data-ui-select="f-evkind"] .ui-select-btn').click()
    pg.locator('[data-ui-select="f-evkind"] .ui-opt[data-value="surgery"]').click()
    pg.wait_for_timeout(100)
    check(f"{tag}: смена вида обратно — подпись просто «Окончание» ({lbl()}), имя цело",
          lbl() == "Окончание" and pg.input_value("#f-evname") == "Ожирение")
    pg.locator('[data-ui-select="f-evkind"] .ui-select-btn').click()
    pg.locator('[data-ui-select="f-evkind"] .ui-opt[data-value="chronic"]').click()
    pg.wait_for_timeout(100)
    miss = pg.locator("[data-evmkbox] .ui-tag[data-mk-missing]")
    check(f"{tag}: неизвестный id в чипах — «Показатель не найден», id в title, сырого id нет",
          miss.count() == 1 and miss.inner_text().startswith("Показатель не найден") and miss.get_attribute("title") == "ghost"
          and "ghost" not in pg.inner_text("[data-evmkbox]"))
    miss.locator('[data-act="an-mk-del"]').click()
    pg.wait_for_timeout(100)
    check(f"{tag}: ✕ на неизвестном чипе убирает его", pg.locator("[data-evmkbox] .ui-tag").count() == 2
          and pg.locator("[data-evmkbox] .ui-tag[data-mk-missing]").count() == 0)
    pg.close()

    # телефон: панель во весь экран
    pg = br.new_page(viewport={"width": 390, "height": 800}, is_mobile=eng_name == "chromium", has_touch=True)
    wire(pg)
    pg.goto(URL)
    pg.wait_for_selector('.attn-card[data-id="glucose"]', timeout=15000)
    pg.click('.attn-card[data-id="glucose"]')
    pg.wait_for_timeout(350)
    w = pg.evaluate("document.querySelector('.ui-pane-box').getBoundingClientRect().width")
    check(f"{tag}: на телефоне панель во весь экран ({w})", abs(w - 390) <= 1)
    pg.close()
    br.close()


LABS_LONG = json.loads(json.dumps(LABS))   # + точки с длинным местом (проверка наложения)
LABS_LONG["biomarkers"] += [
    {"id": "hiv", "name": "ВИЧ", "category": "biochem", "kind": "qual", "unit": None, "ref": None,
         "series": [{"date": "2012-02-01", "value": None, "text": "Отрицательно", "unit": None, "ref": None,
                     "status": "high", "lab": "ГКБ № 71, 1-е хирургическое отделение (Москва), корпус 3"}]},
    {"id": "alt", "name": "АЛТ", "category": "biochem", "kind": "num", "unit": "Ед/л",
         "ref": {"low": 0, "high": 40},
         "series": [{"date": "2012-02-01", "value": 123.45, "text": None, "unit": "Ед/л", "ref": {"low": 0, "high": 40},
                     "status": "high", "lab": "ГКБ № 71, 1-е хирургическое отделение (Москва), корпус 3"}]},
]


def run_mobile(eng_name, eng):
    """390px: история измерений без наложения; смена вкладки — наверх; кнопка темы после крестика окна."""
    try:
        br = eng.launch()
    except Exception as e:
        print(f"health_mobile: пропуск {eng_name} — движок не запускается ({str(e)[:60]})")
        return
    tag = eng_name
    ctx = br.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    pg = ctx.new_page()
    wire(pg)
    pg.route("**/health-data/labs.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(LABS_LONG, ensure_ascii=False)))
    pg.route("**/health-data/reports/", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps([{"name": "r.md", "is_dir": False, "mod_time": "2026-10-01T00:00:00Z"}])))
    pg.route("**/health-data/reports/r.md*", lambda r: r.fulfill(status=200, content_type="text/markdown; charset=utf-8",
             body="---\ntitle: Отчёт\ndate: 2026-10-01\nmarkers: alt, nonexistent_id, glucose\n---\n# Отчёт\n\nТекст отчёта.\n"))
    pg.goto(URL)
    pg.wait_for_selector(".attn-card", timeout=15000)

    # 1. история измерений: дети строки попарно не пересекаются
    for mid in ("hiv", "alt"):
        pg.locator('.ui-mnav-btn[data-id="markers"]').tap()
        pg.wait_for_selector(f'[data-act="open"][data-id="{mid}"]', state="attached", timeout=5000)
        pg.locator(f'[data-act="open"][data-id="{mid}"]').first.evaluate("e => e.click()")
        pg.wait_for_selector(".hist-row", timeout=5000)
        pg.wait_for_timeout(400)
        boxes = pg.evaluate("""() => { const r = document.querySelector('.hist-row'); const o = [];
            for (const c of r.children) { const b = c.getBoundingClientRect(); o.push([b.left, b.top, b.right, b.bottom]); }
            return o; }""")
        bad = [(i, j) for i in range(len(boxes)) for j in range(i + 1, len(boxes))
               if min(boxes[i][2], boxes[j][2]) - max(boxes[i][0], boxes[j][0]) > 0.5
               and min(boxes[i][3], boxes[j][3]) - max(boxes[i][1], boxes[j][1]) > 0.5]
        check(f"{tag}: история «{mid}» — дети строки не перекрываются ({bad})", len(boxes) >= 4 and not bad)
        pg.reload()
        pg.wait_for_selector(".attn-card", timeout=15000)

    # 2. кнопка темы после крестика окна-читателя: ни фокус-рамки, ни залипшего фона
    theme = pg.locator("[data-ui-theme]").first
    rest = theme.evaluate("e => getComputedStyle(e).backgroundColor")
    pg.locator('.ui-mnav-btn[data-id="reports"]').tap()
    pg.wait_for_selector('[data-act="rep-open"]', timeout=5000)
    pg.locator('[data-act="rep-open"]').first.tap()
    pg.wait_for_selector(".ui-docwin-x", timeout=5000)
    pg.wait_for_timeout(800)   # окно доезжает — крестик на месте
    box = pg.locator(".ui-docwin-x").bounding_box()
    pg.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    pg.wait_for_timeout(700)
    check(f"{tag}: окно закрыто", pg.locator(".ui-docwin-x").count() == 0)
    after = theme.evaluate("e => getComputedStyle(e).backgroundColor")
    fv = pg.evaluate("() => document.activeElement && document.activeElement.matches(':focus-visible') && !!document.activeElement.closest('.ui-top')")
    check(f"{tag}: фон кнопки темы как в покое ({rest} / {after})", rest == after)
    check(f"{tag}: у кнопки шапки нет focus-visible", not fv)

    # 2б. биомаркер из отчёта — панелью поверх окна отчёта; отчёт не закрывается, Escape — назад в отчёт
    pg.locator('[data-act="rep-open"]').first.tap()
    pg.wait_for_selector('.ui-docwin [data-act="rep-marker"][data-id="alt"]', timeout=5000)
    pg.wait_for_timeout(500)
    pg.locator('.ui-docwin [data-act="rep-marker"][data-id="alt"]').evaluate("e => e.click()")
    pg.wait_for_selector(".ui-pane", timeout=5000)
    pg.wait_for_timeout(500)
    over = pg.evaluate("""() => { const p = document.querySelector('.ui-pane'), d = document.querySelector('.ui-docwin');
        if (!p || !d) return null; const b = p.querySelector('.ui-pane-box').getBoundingClientRect();
        const t = document.elementFromPoint(b.left + b.width / 2, b.top + 40);
        return { cls: p.className, zp: +getComputedStyle(p).zIndex, zd: +getComputedStyle(d).zIndex, top: !!(t && t.closest('.ui-pane')) }; }""")
    check(f"{tag}: биомаркер из отчёта — панель поверх окна отчёта, отчёт открыт ({over})",
          over is not None and "over" in over["cls"] and over["zp"] > over["zd"] and over["top"])
    nav = pg.evaluate("() => { const p = document.querySelector('.ui-pane'); return p && p.querySelector('.ui-pane-head').innerText; }")
    check(f"{tag}: у биомаркера из отчёта счётчик — по биомаркерам отчёта «1 / 2», не по каталогу ({nav!r})", nav is not None and "1 / 2" in nav)
    pg.locator('.ui-pane [data-act="next"]').evaluate("e => e.click()")
    pg.wait_for_timeout(500)
    nav2 = pg.evaluate("() => { const p = document.querySelector('.ui-pane'); return p && p.querySelector('.ui-pane-head').innerText; }")
    check(f"{tag}: ▶ — следующий биомаркер отчёта «2 / 2», отчёт под панелью ({nav2!r})",
          nav2 is not None and "2 / 2" in nav2 and "hiv" not in nav2 and pg.locator(".ui-docwin").count() == 1
          and "over" in pg.evaluate("() => document.querySelector('.ui-pane').className"))
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(500)
    check(f"{tag}: Escape закрывает панель биомаркера, отчёт остаётся", pg.locator(".ui-pane").count() == 0 and pg.locator(".ui-docwin").count() == 1)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(700)
    check(f"{tag}: второй Escape закрывает отчёт", pg.locator(".ui-docwin").count() == 0)

    # 3. смена вкладки нижним меню — прокрутка в начало
    pg.evaluate("() => window.scrollTo(0, 99999)")
    pg.wait_for_timeout(200)
    y0 = pg.evaluate("() => window.scrollY")
    btns = pg.locator(".ui-mnav-btn")
    cur = pg.evaluate("() => document.querySelector('.ui-mnav-btn.on') && [...document.querySelectorAll('.ui-mnav-btn')].indexOf(document.querySelector('.ui-mnav-btn.on'))")
    pg.evaluate("() => window.scrollTo(0, 400)")
    btns.nth(1 if cur != 1 else 2).tap()
    pg.wait_for_timeout(500)
    check(f"{tag}: после смены вкладки scrollY == 0 (до: {y0})", pg.evaluate("() => window.scrollY") == 0)

    # 4. панель хронической на 390 px: дети строки показателя не пересекаются
    pg.reload()
    pg.wait_for_selector(".attn-card", timeout=15000)
    # Хвост загрузки (список отчётов, проба сайдкара) перерисовывает страницу целиком; под нагрузкой перерисовка попадает
    # между поиском кнопки вкладки и щелчком — щелчок по уже отсоединённой кнопке до обработчика не доходит и страница
    # остаётся на «Обзоре». Поэтому щелчок повторяется, пока вкладка не откроется.
    for _ in range(6):
        pg.locator('[data-act="tab"][data-id="anamnesis"]').first.evaluate("e => e.click()")
        try:
            pg.wait_for_selector('[data-act="an-ev-open"][data-id="ev7"]', state="attached", timeout=2500)
            break
        except Exception:
            pass
    try:
        pg.wait_for_selector('[data-act="an-ev-open"][data-id="ev7"]', state="attached", timeout=5000)
    except Exception:       # вкладка так и не открылась — печатаем состояние страницы
        print("DIAG ev7:", pg.evaluate("""() => JSON.stringify({
            ev: [...document.querySelectorAll('[data-act="an-ev-open"]')].map(e => e.getAttribute('data-id')),
            attn: document.querySelectorAll('.attn-card').length, modal: document.querySelectorAll('.ui-modal').length,
            pane: document.querySelectorAll('.ui-pane').length, w: innerWidth,
            body: document.body.innerText.replace(/\\s+/g, ' ').slice(0, 700)})"""))
        raise
    pg.locator('[data-act="an-ev-open"][data-id="ev7"]').first.evaluate("e => e.click()")
    pg.wait_for_selector("[data-an-mk-row]", timeout=5000)
    pg.wait_for_timeout(500)
    bad = pg.evaluate("""() => { const o = []; document.querySelectorAll('[data-an-mk-row]').forEach((r, n) => {
        const bs = [...r.children].map(c => c.getBoundingClientRect()), rb = r.getBoundingClientRect();
        for (let i = 0; i < bs.length; i++) {
          if (bs[i].right > rb.right + 0.5 || bs[i].left < rb.left - 0.5) o.push([n, i, 'out']);
          for (let j = i + 1; j < bs.length; j++)
            if (Math.min(bs[i].right, bs[j].right) - Math.max(bs[i].left, bs[j].left) > 0.5
                && Math.min(bs[i].bottom, bs[j].bottom) - Math.max(bs[i].top, bs[j].top) > 0.5) o.push([n, i, j]); } });
        return o; }""")
    check(f"{tag}: хроническая на 390 px — дети строк не пересекаются ({bad})", not bad)
    check(f"{tag}: хроническая на 390 px — нет горизонтальной прокрутки", pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1"))
    pg.close()
    br.close()


def run_forms(eng_name, eng, mobile):
    """«Сохранить отчёт» (вкладка «Отчёты») и «Править справку» (карточка маркера): окна ui-kit, ответы сервера
    (ошибки формата, 409 «exists» с подтверждением замены, запись справки с base_hash), 390 px без горизонтальной прокрутки."""
    try:
        br = eng.launch()
    except Exception as e:
        print(f"health_forms: пропуск {eng_name} — движок не запускается ({str(e)[:60]})")
        return
    tag = eng_name + (" 390px" if mobile else "")
    ctx = br.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True) if mobile \
        else br.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    wire(pg)

    def fulfill(route, obj, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(obj, ensure_ascii=False))

    info = {"schema": "health-biomarkers-info@1", "info": {"glucose": {"what": ["Синтетика"], "up": "Синтетика вверх", "down": "Синтетика вниз"}}}
    pg.route("**/health-data/biomarkers-info.json*", lambda r: fulfill(r, info))
    pg.route("**/api/health*", lambda r: fulfill(r, {"health_writable": True, "health_files": list(FILES),
                                                     "health_report": True, "health_marker_info": True, "health_upload": True}))
    posts = []
    answers = []

    def rep(route):
        posts.append(json.loads(route.request.post_data))
        code, obj = answers.pop(0)
        fulfill(route, obj, code)
    pg.route("**/api/hd/report", rep)

    def mi_file(route):
        fulfill(route, {"hash": "hi1", "content": json.dumps(info, ensure_ascii=False)})
    pg.route(lambda u: "/api/hd/file" in u and "biomarkers-info" in u, mi_file)
    mi_posts = []

    def mi_post(route):
        mi_posts.append(json.loads(route.request.post_data))
        fulfill(route, {"path": "biomarkers-info.json", "hash": "hi2", "action": "overwrite"})
    pg.route("**/api/hd/marker-info", mi_post)

    pg.goto(URL)
    pg.wait_for_selector(".attn-card", timeout=15000)
    tap = (lambda sel: pg.locator(sel).first.evaluate("e => e.click()"))
    noscroll = lambda: pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1")

    # ── отчёты ────────────────────────────────────────────────────────────────
    tap('[data-act="tab"][data-id="reports"]' if not mobile else '.ui-mnav-btn[data-id="reports"]')
    pg.wait_for_selector("#rep-add", timeout=5000)
    check(f"{tag}: «Сохранить отчёт» — главная кнопка действия (.ui-btn, ui-kit 1.70.0)",
          {"ui-btn"} <= set((pg.get_attribute("#rep-add", "class") or "").split()))
    tap("#rep-add")
    pg.wait_for_selector(".ui-modal #rep-slot-host .ui-file", timeout=5000)
    check(f"{tag}: окно отчёта — слот файла ui-kit, текст и тема",
          pg.locator("#f-reptext").count() == 1 and pg.locator("#f-reptopic").count() == 1 and pg.locator("#rep-file[type=file]").count() == 1)
    check(f"{tag}: окно отчёта — без горизонтальной прокрутки", noscroll())
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(450)
    check(f"{tag}: Escape закрывает окно отчёта", pg.locator(".ui-modal").count() == 0)

    tap("#rep-add")
    pg.wait_for_selector("#f-reptext", timeout=5000)
    pg.click(".ui-modal-save")
    pg.wait_for_selector(".ui-modal .ui-alert", timeout=3000)
    check(f"{tag}: пустой текст — сообщение, запроса нет", not posts)
    pg.fill("#f-reptext", "---\nschema: health-report@1\n---\nтекст")
    pg.fill("#f-reptopic", "липиды")
    answers.extend([(400, {"error": "report invalid", "detail": "title: обязательно", "errors": ["title: обязательно"], "warnings": []}),
                    (409, {"error": "exists", "name": "2026-11-01-липиды.md", "current_hash": "x"}),
                    (200, {"path": "reports/2026-11-01-липиды.md", "name": "2026-11-01-липиды.md", "hash": "h", "status": "replaced", "warnings": []})])
    pg.click(".ui-modal-save")
    pg.wait_for_selector(".ui-modal .ui-alert", timeout=5000)
    check(f"{tag}: ошибка формата сервера показана в окне, текст не потерян",
          "title: обязательно" in pg.inner_text(".ui-modal .ui-alert") and "текст" in pg.input_value("#f-reptext"))
    check(f"{tag}: запрос — тема и текст, без overwrite",
          posts[0].get("topic") == "липиды" and posts[0].get("overwrite") is False and posts[0].get("content", "").startswith("---"))
    pg.click(".ui-modal-save")
    pg.wait_for_selector(".ui-confirm", timeout=5000)
    check(f"{tag}: имя занято — подтверждение замены ({pg.inner_text('.ui-confirm-box')[:40]!r})", "2026-11-01-липиды.md" in pg.inner_text(".ui-confirm-box"))
    pg.click(".ui-confirm-ok")
    pg.wait_for_selector(".ui-modal", state="detached", timeout=5000)
    check(f"{tag}: после подтверждения — повтор с overwrite: true, окно закрыто", len(posts) == 3 and posts[2].get("overwrite") is True)
    check(f"{tag}: итог — плашка «Отчёт сохранён»", "Отчёт сохранён" in pg.inner_text("body"))

    # ── справка маркера ───────────────────────────────────────────────────────
    tap('[data-act="tab"][data-id="overview"]' if not mobile else '.ui-mnav-btn[data-id="overview"]')
    pg.wait_for_selector('.attn-card[data-id="glucose"]', timeout=5000)
    pg.locator('.attn-card[data-id="glucose"]').first.evaluate("e => e.click()")
    pg.wait_for_selector('.ui-pane [data-act="mi-edit"]', timeout=5000)
    tap('.ui-pane [data-act="mi-edit"]')
    pg.wait_for_selector("#f-miwhat", timeout=5000)
    check(f"{tag}: окно справки — три поля, предзаполнено из файла",
          pg.input_value("#f-miup") == "Синтетика вверх" and pg.input_value("#f-miwhat") == "Синтетика" and pg.locator("#f-midown").count() == 1)
    check(f"{tag}: окно справки — без горизонтальной прокрутки", noscroll())
    pg.fill("#f-miup", "Новый текст причин")
    pg.fill("#f-miwhat", "Абзац один\n\nАбзац два")
    pg.click(".ui-modal-save")
    pg.wait_for_selector("#f-miwhat", state="detached", timeout=5000)
    check(f"{tag}: запись — id, абзацы списком, base_hash из свежего чтения",
          mi_posts and mi_posts[0] == {"id": "glucose", "what": ["Абзац один", "Абзац два"], "up": "Новый текст причин",
                                       "down": "Синтетика вниз", "base_hash": "hi1"})
    pg.wait_for_timeout(300)
    check(f"{tag}: справка в карточке обновилась и помечена «внесён вручную»",
          "Новый текст причин" in pg.text_content(".ui-pane") and "внесён вручную" in pg.text_content(".ui-pane"))
    pg.close()
    br.close()


def run_upload(eng_name, eng, mobile):
    """Форма исследования (health v3.1): слот «Файл исследования» (uiFileSlot), загрузка при «Сохранить» (POST upload),
    имя ложится в поле «Файл» записи; без файла — запись с ручным заключением; отказ сервера не теряет набранное."""
    try:
        br = eng.launch()
    except Exception as e:
        print(f"health_upload: пропуск {eng_name} — движок не запускается ({str(e)[:60]})")
        return
    tag = eng_name + (" 390px" if mobile else "")
    ctx = br.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True) if mobile \
        else br.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    wire(pg)

    def fulfill(route, obj, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(obj, ensure_ascii=False))

    pg.route("**/api/health*", lambda r: fulfill(r, {"health_writable": True, "health_files": list(FILES),
                                                     "health_report": True, "health_marker_info": True, "health_upload": True}))
    saves, ups, answers = [], [], []

    def hd_save(route):
        saves.append(json.loads(route.request.post_data))
        fulfill(route, {"hash": "h%d" % (len(saves) + 1)})
    pg.route("**/api/hd/save", hd_save)

    def hd_up(route):
        ups.append(json.loads(route.request.post_data))
        code, obj = answers.pop(0)
        fulfill(route, obj, code)
    pg.route("**/api/hd/upload", hd_up)

    pg.goto(URL)
    pg.wait_for_selector(".attn-card", timeout=15000)
    tap = (lambda sel: pg.locator(sel).first.evaluate("e => e.click()"))

    def waitfor(cond, ms=6000):
        for _ in range(ms // 100):
            if cond():
                return
            pg.wait_for_timeout(100)
    tap('.ui-mnav-btn[data-id="studies"]' if mobile else '[data-act="tab"][data-id="studies"]')
    pg.wait_for_selector('[data-act="study-add"]', timeout=5000)
    tap('[data-act="study-add"]')
    pg.wait_for_selector(".ui-modal #study-slot-host .ui-file", timeout=5000)
    check(f"{tag}: форма исследования — слот файла ui-kit и поле «Файл»",
          pg.locator("#study-file[type=file]").count() == 1 and pg.locator("#f-file").count() == 1)
    check(f"{tag}: форма исследования без горизонтальной прокрутки", pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1"))

    # исследование без файла — только ручное заключение: загрузки нет
    pg.fill("#f-conclusion", "Синтетическое заключение")
    pg.click(".ui-modal-save")
    pg.wait_for_selector(".ui-modal", state="detached", timeout=5000)
    waitfor(lambda: len(saves) >= 1)
    check(f"{tag}: без файла — запись с ручным заключением, upload не вызывался",
          not ups and saves and any(x.get("conclusion") == "Синтетическое заключение" and x.get("file") == ""
                                    for x in json.loads(saves[-1]["content"])["studies"]))

    # файл выбран: отказ сервера — набранное не теряется, запись не создана
    for _ in range(6):      # перерисовка после сохранения пересоздаёт кнопку между поиском и нажатием — нажатие повторяется
        tap('[data-act="study-add"]')
        try:
            pg.wait_for_selector("#study-file", state="attached", timeout=2500)
            break
        except Exception:
            pass
    pg.wait_for_selector("#study-file", state="attached", timeout=5000)
    pdf = b"%PDF-1.4\n% synthetic\n%%EOF\n"
    pg.set_input_files("#study-file", files=[{"name": "scan.pdf", "mimeType": "application/pdf", "buffer": pdf}])
    pg.fill("#f-conclusion", "Текст, который нельзя потерять")
    n_saves = len(saves)
    answers.append((400, {"error": "bad file", "detail": "формат не распознан: нужны PDF, JPEG, PNG или HEIC"}))
    pg.click(".ui-modal-save")
    pg.wait_for_function("() => (document.querySelector('.ui-savebar') || {}).textContent && document.querySelector('.ui-savebar').textContent.indexOf('Файл не принят') >= 0", timeout=8000)
    _st = ("Файл не принят" in pg.inner_text(".ui-savebar"), pg.locator(".ui-modal").count(),
           pg.input_value("#f-conclusion"), len(saves), n_saves)
    check(f"{tag}: отказ upload — сообщение на плашке, окно открыто, текст на месте, запись не сохранена {_st}",
          _st[0] and _st[1] == 1 and _st[2] == "Текст, который нельзя потерять" and _st[3] == _st[4])
    check(f"{tag}: запрос upload — вид, дата, b64 файла",
          ups and ups[0].get("kind") == "УЗИ" and len(ups[0].get("date", "")) == 10
          and __import__("base64").b64decode(ups[0]["b64"]) == pdf)

    # успех: имя файла ложится в запись
    answers.append((200, {"name": "2026-05-12-узи.pdf", "path": "studies/2026-05-12-узи.pdf", "type": "pdf", "status": "created"}))
    pg.click(".ui-modal-save")
    pg.wait_for_selector(".ui-modal", state="detached", timeout=5000)
    waitfor(lambda: len(saves) > n_saves)
    last = json.loads(saves[-1]["content"])["studies"]
    check(f"{tag}: после загрузки в записи file = имя с сервера, заключение сохранено",
          any(x.get("file") == "2026-05-12-узи.pdf" and x.get("conclusion") == "Текст, который нельзя потерять" for x in last))
    pg.close()
    br.close()


def run_labs(eng_name, eng, mobile):
    """Ручная точка анализа (health v3.2): форма «Добавить точку» и «Новый показатель» — только при ai_mode off;
    при on кнопок нет; точка попадает на график и в историю с пометкой «вручную»; свои точки правятся и
    удаляются, точки из документов — нет; запрос уходит в POST save с base_hash; 390 px без горизонтальной прокрутки."""
    try:
        br = eng.launch()
    except Exception as e:
        print(f"health_labs: пропуск {eng_name} — движок не запускается ({str(e)[:60]})")
        return
    tag = eng_name + (" 390px" if mobile else "")

    def new_page(mode):
        ctx = br.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True) if mobile \
            else br.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_init_script(f"localStorage.setItem('hub-auth','dGVzdDp0ZXN0'); localStorage.setItem('hub-noai','{mode}');")
        pg = ctx.new_page()
        state = {"labs": json.loads(json.dumps(LABS)), "ver": 1, "posts": [], "answer": None}

        def fulfill(route, obj, status=200):
            route.fulfill(status=status, content_type="application/json", body=json.dumps(obj, ensure_ascii=False))

        pg.route("**/health-data/biomarkers-info.json*", lambda r: fulfill(r, {}))
        pg.route("**/health-data/reports/**", lambda r: fulfill(r, []))
        pg.route("**/api/health*", lambda r: fulfill(r, {"health_writable": True, "health_files": list(FILES) + ["labs"],
                                                         "health_labs_manual": True}))
        pg.route("**/api/hub/settings*", lambda r: fulfill(r, {"path": "_hub/settings.json", "hash": "s1",
                 "settings": {"schema": "hub-settings@1", "ai_mode": mode, "off_since": None, "returned_at": None}}))

        def hd(route):
            req = route.request
            if req.method == "POST":
                body = json.loads(req.post_data)
                state["posts"].append(body)
                if state["answer"]:
                    code, obj = state["answer"]
                    return fulfill(route, obj, code)
                # серверный пересчёт статуса (арифметика по референсу) — как labs_rules.auto_status
                doc = json.loads(body["content"])
                for m in doc["biomarkers"]:
                    for pt in m["series"]:
                        if pt.get("source") == "manual":
                            r, v = pt.get("ref"), pt.get("value")
                            pt["status"] = "na" if not r or v is None else "low" if v < r["low"] else "high" if v > r["high"] else "norm"
                state["labs"] = doc
                state["ver"] += 1
                return fulfill(route, {"path": "labs.json", "hash": f"hl{state['ver']}", "normalized": True})
            name = req.url.split("path=")[1].split(".json")[0]
            if name == "labs":
                return fulfill(route, {"hash": f"hl{state['ver']}", "content": json.dumps(state["labs"], ensure_ascii=False)})
            return fulfill(route, {"hash": "h1", "content": json.dumps(FILES[name], ensure_ascii=False)})
        pg.route("**/api/hd/**", hd)
        return pg, state

    tap = lambda pg, sel: pg.locator(sel).first.evaluate("e => e.click()")
    noscroll = lambda pg: pg.evaluate("() => document.documentElement.scrollWidth <= innerWidth + 1")
    to_markers = lambda pg: tap(pg, '.ui-mnav-btn[data-id="markers"]' if mobile else '[data-act="tab"][data-id="markers"]')

    # ── ai_mode on: кнопок нет ────────────────────────────────────────────────
    pg, st = new_page("on")
    pg.goto(URL)
    pg.wait_for_selector('.attn-card[data-id="glucose"]', timeout=15000)
    pg.locator('.attn-card[data-id="glucose"]').first.evaluate("e => e.click()")
    pg.wait_for_selector(".ui-pane .hist-row", timeout=5000)
    check(f"{tag}: ai_mode on — «Добавить точку» нет", pg.locator('[data-act="lab-add"]').count() == 0)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(450)
    to_markers(pg)
    pg.wait_for_selector("#mk-count", timeout=5000)
    check(f"{tag}: ai_mode on — «Новый показатель» нет", pg.locator("#lab-newmarker").count() == 0)
    pg.context.close()

    # ── ai_mode off: форма ────────────────────────────────────────────────────
    pg, st = new_page("off")
    pg.goto(URL)
    pg.wait_for_selector('.attn-card[data-id="glucose"]', timeout=15000)
    pg.locator('.attn-card[data-id="glucose"]').first.evaluate("e => e.click()")
    pg.wait_for_selector('.ui-pane [data-act="lab-add"]', timeout=5000)
    same_btn = pg.evaluate("""() => { const a = document.querySelector('.ui-pane [data-act="lab-add"]'), g = getComputedStyle(a);
        const acc = getComputedStyle(document.body).getPropertyValue('--btn-acc').trim(), p = document.createElement('i');
        p.style.color = acc; document.body.appendChild(p); const c = getComputedStyle(p).color; p.remove();
        return a.classList.contains('ui-btn') && g.backgroundColor === c && g.borderRadius === '8px'; }""")
    check(f"{tag}: ai_mode off — «＋ Добавить точку» есть: главная кнопка .ui-btn, цвет --btn-acc", same_btn)
    n_pts = pg.locator(".ui-pane svg circle.pt").count()
    tap(pg, '.ui-pane [data-act="lab-add"]')
    pg.wait_for_selector(".ui-modal #f-labval", timeout=5000)
    tap(pg, '.ui-modal [data-dp-open="date"]')
    pg.wait_for_selector(".dp-pop", timeout=5000)
    over = pg.evaluate("""() => { const p = document.querySelector('.dp-pop'), m = document.querySelector('.ui-modal'), r = p.getBoundingClientRect();
        const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return +getComputedStyle(p).zIndex > +getComputedStyle(m).zIndex && !!top && !!top.closest('.dp-pop'); }""")
    check(f"{tag}: календарь поля «Дата» открывается ПОВЕРХ окна точки (слой календаря выше слоя окна)", over)
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)
    check(f"{tag}: Esc закрывает календарь, окно точки остаётся", pg.locator(".dp-pop").count() == 0 and pg.locator(".ui-modal #f-labval").count() == 1)
    check(f"{tag}: окно точки — дата, значение, единица (только чтение), референс, лаборатория, заметка",
          pg.locator(".ui-modal #f-date").count() == 1 and pg.locator("#f-labunit[readonly]").count() == 1
          and pg.locator("#f-labl").count() == 1 and pg.locator("#f-labh").count() == 1
          and pg.locator("#f-lablab").count() == 1 and pg.locator("#f-labnote").count() == 1)
    check(f"{tag}: единица существующего показателя подставлена", pg.input_value("#f-labunit") == "ммоль/л")
    check(f"{tag}: окно точки — без горизонтальной прокрутки", noscroll(pg))
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(450)
    check(f"{tag}: Escape закрывает окно точки", pg.locator(".ui-modal").count() == 0)

    tap(pg, '.ui-pane [data-act="lab-add"]')
    pg.wait_for_selector(".ui-modal #f-labval", timeout=5000)
    pg.fill("#f-labval", "")
    pg.click(".ui-modal-save")
    pg.wait_for_selector(".ui-modal .ui-alert", timeout=3000)
    check(f"{tag}: пустое значение — сообщение, запроса нет", not st["posts"])
    pg.fill("#f-labval", "7,5")
    pg.fill("#f-labl", "9")
    pg.fill("#f-labh", "3")
    pg.click(".ui-modal-save")
    pg.wait_for_function("() => /не может быть больше/.test((document.querySelector('.ui-modal .ui-alert') || {}).textContent || '')", timeout=3000)
    check(f"{tag}: референс «от» > «до» — отказ на странице", not st["posts"])
    pg.fill("#f-labl", "4.1")
    pg.fill("#f-labh", "6")
    pg.fill("#f-lablab", "Лаб-синтетика")
    pg.click(".ui-modal-save")
    pg.wait_for_selector(".ui-modal", state="detached", timeout=8000)
    check(f"{tag}: запрос ушёл ровно один, с base_hash текущего labs.json", len(st["posts"]) == 1 and st["posts"][0]["base_hash"] == "hl1"
          and st["posts"][0]["path"] == "labs.json")
    sent = [m for m in json.loads(st["posts"][0]["content"])["biomarkers"] if m["id"] == "glucose"][0]["series"]
    mp = [x for x in sent if x.get("source") == "manual"]
    check(f"{tag}: ручная точка: source=manual, число 7.5, единица маркера, референс, лаборатория; точки скилла не тронуты",
          len(mp) == 1 and mp[0]["value"] == 7.5 and mp[0]["unit"] == "ммоль/л" and mp[0]["ref"] == {"low": 4.1, "high": 6}
          and mp[0]["lab"] == "Лаб-синтетика" and len(sent) == 3 and sent[0]["study"] == "sx")
    pg.wait_for_function("n => document.querySelectorAll('.ui-pane svg circle.pt').length === n + 1", arg=n_pts, timeout=5000)
    check(f"{tag}: точка появилась на графике", pg.locator(".ui-pane svg circle.pt").count() == n_pts + 1)
    check(f"{tag}: последняя точка графика помечена «вручную» в подсказке",
          "вручную" in (pg.locator(".ui-pane svg circle.pt.last title").first.text_content() or ""))
    check(f"{tag}: в истории — метка «вручную» и кнопки правки/удаления только у неё",
          pg.locator(".ui-pane .lab-manual").count() == 1 and pg.locator('.ui-pane [data-act="lab-edit"]').count() == 1
          and pg.locator('.ui-pane [data-act="lab-del"]').count() == 1)
    check(f"{tag}: статус посчитан сервером (7.5 > 6 → «Выше нормы»)", "Выше" in pg.inner_text(".ui-pane .hist-row:first-child") or
          "выше" in pg.inner_text(".ui-pane .hist-row:first-child").lower())
    check(f"{tag}: без горизонтальной прокрутки после сохранения", noscroll(pg))

    # правка своей точки
    tap(pg, '.ui-pane [data-act="lab-edit"]')
    pg.wait_for_selector(".ui-modal #f-labval", timeout=5000)
    check(f"{tag}: правка — поля заполнены точкой", pg.input_value("#f-labval") == "7.5" and pg.input_value("#f-lablab") == "Лаб-синтетика")
    pg.fill("#f-labval", "5")
    pg.click(".ui-modal-save")
    pg.wait_for_selector(".ui-modal", state="detached", timeout=8000)
    sent = [m for m in json.loads(st["posts"][1]["content"])["biomarkers"] if m["id"] == "glucose"][0]["series"]
    check(f"{tag}: правка заменяет ту же точку (не дублирует)",
          len(st["posts"]) == 2 and len(sent) == 3 and [x for x in sent if x.get("source") == "manual"][0]["value"] == 5)

    # отказ сервера показан в окне, окно не закрыто
    st["answer"] = (400, {"error": "schema invalid", "detail": "маркер glucose 2026-10-10: на эту дату уже есть точка из документа"})
    tap(pg, '.ui-pane [data-act="lab-add"]')
    pg.wait_for_selector(".ui-modal #f-labval", timeout=5000)
    pg.fill("#f-labval", "3")
    pg.click(".ui-modal-save")
    pg.wait_for_function("() => /уже есть точка из документа/.test((document.querySelector('.ui-modal .ui-alert') || {}).textContent || '')", timeout=5000)
    check(f"{tag}: ответ 400 — текст сервера в окне, окно открыто", pg.locator(".ui-modal").count() == 1)
    st["answer"] = (403, {"error": "ai_mode on", "detail": "x"})
    pg.click(".ui-modal-save")
    pg.wait_for_function("() => /только при выключенном ИИ/.test((document.querySelector('.ui-modal .ui-alert') || {}).textContent || '')", timeout=5000)
    check(f"{tag}: ответ 403 — понятный текст про режим", True)
    st["answer"] = (409, {"error": "hash mismatch", "current_hash": "z"})
    pg.click(".ui-modal-save")
    pg.wait_for_function("() => /изменились с другого устройства/.test((document.querySelector('.ui-modal .ui-alert') || {}).textContent || '')", timeout=5000)
    check(f"{tag}: ответ 409 — «изменились с другого устройства»", True)
    st["answer"] = None
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(450)

    # удаление своей точки: уходит без неё
    tap(pg, '.ui-pane [data-act="lab-del"]')
    pg.wait_for_selector(".ui-confirm", timeout=5000)
    pg.click(".ui-confirm-ok")
    pg.wait_for_function("n => document.querySelectorAll('.ui-pane svg circle.pt').length === n", arg=n_pts, timeout=8000)
    sent = [m for m in json.loads(st["posts"][-1]["content"])["biomarkers"] if m["id"] == "glucose"][0]["series"]
    check(f"{tag}: удаление — точка ушла, точки из документов на месте", len(sent) == 2 and all(x.get("source") != "manual" for x in sent))
    check(f"{tag}: у точек из документов кнопок правки нет", pg.locator('.ui-pane [data-act="lab-edit"]').count() == 0)

    # «Новый показатель» — каталог
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(450)
    to_markers(pg)
    pg.wait_for_selector("#lab-newmarker", timeout=5000)
    tap(pg, "#lab-newmarker")
    pg.wait_for_selector(".ui-modal #f-labname", timeout=5000)
    check(f"{tag}: «Новый показатель» — название, категория, единица (редактируется)",
          pg.locator("#f-labcat").count() >= 1 and pg.locator("#f-labunit[readonly]").count() == 0)
    check(f"{tag}: «Новый показатель» — без горизонтальной прокрутки", noscroll(pg))
    pg.fill("#f-labname", "Показатель-синтетика")
    pg.fill("#f-labunit", "мкг/л")
    pg.fill("#f-labval", "12")
    pg.click(".ui-modal-save")
    pg.wait_for_selector(".ui-modal", state="detached", timeout=8000)
    made = [m for m in json.loads(st["posts"][-1]["content"])["biomarkers"] if m["name"] == "Показатель-синтетика"]
    check(f"{tag}: новый показатель: id латиницей, категория, единица, одна ручная точка",
          len(made) == 1 and made[0]["id"].startswith("man_") and made[0]["category"] == "biochem" and made[0]["unit"] == "мкг/л"
          and len(made[0]["series"]) == 1 and made[0]["series"][0]["source"] == "manual")
    pg.wait_for_function("() => document.body.innerText.indexOf('Показатель-синтетика') >= 0", timeout=5000)
    check(f"{tag}: новый показатель виден в каталоге", True)
    pg.context.close()
    br.close()


def run_redraw(eng_name, eng):
    """Поздняя перерисовка страницы (render(): приход данных, смена режима, фон) не стирает набранное в открытой форме:
    исследование, лекарство, прививка, вес, давление, событие анамнеза, отчёт — текст, выбор в списке и дата на месте."""
    try:
        br = eng.launch()
    except Exception as e:
        print(f"health_redraw: пропуск {eng_name} — движок не запускается ({str(e)[:60]})")
        return
    ctx = br.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    wire(pg)
    pg.route("**/api/health*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(
        {"health_writable": True, "health_files": list(FILES), "health_report": True, "health_marker_info": True})))
    pg.goto(URL)
    pg.wait_for_selector(".attn-card", timeout=15000)
    pg.wait_for_timeout(1700)       # дождаться и поздней перерисовки загрузки (REPORTS_WAIT_MS)
    # действия страницы — по data-act на документе: временная кнопка, клик (S и ACTS снаружи не видны)
    fire = lambda a: pg.evaluate("a => { const b = document.createElement('button'); b.setAttribute('data-act', a); document.body.appendChild(b); b.click(); b.remove(); }", a)
    late = lambda: pg.evaluate("() => document.dispatchEvent(new CustomEvent('ui-theme', { detail: document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark' }))")
    for act in ["study-add", "med-add", "vax-add", "weight-add", "bp-add", "an-ev-add", "rep-add"]:
        fire(act)
        pg.wait_for_selector(".ui-modal", timeout=5000)
        ids = pg.evaluate("""() => [...document.querySelectorAll('.ui-modal input:not([type=hidden]):not([type=file]):not([type=time]):not([type=date]):not([type=radio]):not([type=checkbox]):not([data-dpv]):not(.ui-select-q), .ui-modal textarea')]
                               .filter(e => e.id).map(e => e.id)""")
        typed = {}
        for i, fid in enumerate(ids[:3]):
            typed[fid] = ("%d" % (70 + i)) if pg.get_attribute("#" + fid, "type") == "number" else "набрано-%s-%d" % (act, i)
            pg.fill("#" + fid, typed[fid])
        pg.locator("#" + ids[0]).focus() if ids else None
        late()
        pg.wait_for_timeout(50)
        got = {fid: pg.input_value("#" + fid) for fid in typed}
        check(f"{eng_name}: {act} — набранное переживает поздний render() {got if got != typed else ''}", bool(typed) and got == typed)
        check(f"{eng_name}: {act} — фокус остался в поле", not ids or pg.evaluate("document.activeElement.id") == ids[0])
        if act == "study-add":
            pg.evaluate("document.querySelector('[data-ui-select=\"f-kind\"] .ui-opt[data-value=\"МРТ\"]').click()")
            kind = pg.input_value("#f-kind")
            late()
            pg.wait_for_timeout(50)
            check(f"{eng_name}: study-add — выбранный вид исследования переживает render() ({kind})",
                  kind != "УЗИ" and pg.input_value("#f-kind") == kind
                  and pg.text_content('[data-ui-select="f-kind"] .ui-select-t') == kind)
        pg.keyboard.press("Escape")
        pg.wait_for_selector(".ui-modal", state="detached", timeout=5000)
    # закрытая форма не оставляет черновика: новая форма открывается пустой
    fire("study-add")
    pg.wait_for_selector("#f-area", timeout=5000)
    check(f"{eng_name}: новая форма после закрытия — пустая", pg.input_value("#f-area") == "")
    ctx.close()
    br.close()


with sync_playwright() as pw:
    run_mobile("chromium", pw.chromium)
    run_mobile("webkit", pw.webkit)
    run("chromium", pw.chromium)
    run("webkit", pw.webkit)
    run_forms("chromium", pw.chromium, False)
    run_forms("chromium", pw.chromium, True)
    run_forms("webkit", pw.webkit, False)
    run_forms("webkit", pw.webkit, True)
    run_upload("chromium", pw.chromium, False)
    run_upload("chromium", pw.chromium, True)
    run_upload("webkit", pw.webkit, False)
    run_upload("webkit", pw.webkit, True)
    run_redraw("chromium", pw.chromium)
    run_redraw("webkit", pw.webkit)
    run_labs("chromium", pw.chromium, False)
    run_labs("chromium", pw.chromium, True)
    run_labs("webkit", pw.webkit, False)
    run_labs("webkit", pw.webkit, True)
srv.shutdown()
print(f"health_panes: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
