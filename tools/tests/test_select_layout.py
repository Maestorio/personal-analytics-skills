#!/usr/bin/env python3
"""Выпадающий список кабинета (ui-kit uiSelectHTML, 1.20.0) — прогон НАСТОЯЩИМИ
браузерами Chromium и WebKit (движок Safari на iPhone) на страницах, где он
стоит в формах и панелях фильтров.

Почему: 2026-10-06 нативные <select> «Здоровья» (и далее «Еды») переведены на
общий список, как на «Деньгах». Самое хрупкое — формы: они НЕ перерисовываются
при выборе (пропал бы набранный текст), код сохранения читает .value полей, а
подстановка «по прежнему лекарству» ловит "change". Общий список обязан вести
себя как <select> во всём, что видит код страницы.

Что проверяется (компьютер 1280 и телефон 390):
  1. панели фильтров: «Сортировка» биомаркеров и «Назначение» аптечки —
     выбор меняет список (общий обработчик "change" страницы);
  2. форма лекарства: длинный список «Заполнить по прежнему» с поиском
     («нур» → только подходящие, Enter — первый), подстановка срабатывает;
  3. выбор в форме не стирает набранное в других полях; сохранение отправляет
     именно выбранные «Назначение» и «Форму» (перехват POST /api/hd/save);
  4. раскрытая часть не обрезается окном формы и целиком на экране (у нижних
     полей — раскрывается вверх);
  5. клавиатура: ↓ открывает, ↓/Enter выбирают, Esc закрывает список, а не
     окно формы;
  6. форма исследования: вид по умолчанию сохраняется как раньше; значения вне
     словарей (форма «порошок», группа, вид) показываются и не затираются;
  7. телефон: мишень ≥ 44px, длинный список — шторкой у верха, поиск 16px;
  8. «Еда»: «заменить на другое» в плане и сопоставление ингредиентов при
     импорте — поиск по сотне продуктов, выбор доходит до плана и до
     сохранённого рецепта (перехват POST /api/fd/*);
  9. вьюер портфеля (реальные данные Synology; нет монтирования — пропуск):
     сектор/риск сужают таблицу и «все» возвращает её, версия отчёта
     переключается, окно не закрывается; справка — общий читатель с оглавлением;
  9б. удаление — общее окно подтверждения (uiConfirm): название, Esc/«Отмена» —
      «нет», «Удалить» — сохранено; нативных диалогов нет;
  10. окно документа «Здоровья» — общее .ui-docwin: слой поверх форм, имя
      отчёта на телефоне в две строки, «Открыть отдельно» — своей строкой; Esc и ✕;
  11. ошибок JS нет.

Данные синтетические (подмена ответов в браузере) — Synology и сайдкар не нужны.

Запуск:
    python3 tools/tests/test_select_layout.py
Требует playwright; движок, которого нет, — честный пропуск, не падение.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import SYNOLOGY_LOCK, Checker, frames, per_engine, serve, settle  # noqa: E402

check = Checker()


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("select_layout: пропуск — нет playwright")
    sys.exit(0)

LABS = {
    "schema": "health-labs@1", "generated": "2026-07-17", "source": "test",
    "person": {"sex": "m", "age_at_export": 37},
    "categories": [{"key": "biochem", "name": "Биохимия крови"}],
    "biomarkers": [
        {"id": "glucose", "name": "Глюкоза натощак", "category": "biochem", "kind": "num", "unit": "ммоль/л",
         "ref": {"low": 4.1, "high": 6.0},
         "series": [{"date": "2025-10-14", "value": 5.0, "text": None, "unit": "ммоль/л",
                     "ref": {"low": 4.1, "high": 6.0}, "status": "norm", "lab": None}]},
        {"id": "ldh", "name": "ЛДГ", "category": "biochem", "kind": "num", "unit": "МЕ/л",
         "ref": {"low": 122, "high": 222},
         "series": [{"date": "2024-03-01", "value": 240, "text": None, "unit": "МЕ/л",
                     "ref": {"low": 122, "high": 222}, "status": "high", "lab": None}]},
    ]}
NAMES = ["Нурофен", "Нурофен Экспресс", "Парацетамол", "Ибупрофен", "Лоратадин", "Супрастин", "Called Ё-тест Ёлка",
         "Мирамистин", "Називин", "Аквамарис", "Смекта", "Энтеросгель", "Мезим", "Пантенол", "Визин"]
MEDS = {"schema": "health-meds@1", "updated": "2026-10-01", "meds": [
    {"id": f"m{i}", "name": n, "inn": "", "for": "простуда" if i % 2 else "", "class": "", "dose": "200 мг" if i == 0 else "",
     "regimen": "", "timing": "", "form": "таблетки", "taking": False, "archived": i == 3, "prescribedBy": "",
     "expiry": "2027-01", "affects": [], "indications": "справка-" + n, "interactions": "", "notes": "",
     "group": "pain" if i < 4 else ("allergy" if i < 6 else "")}
    for i, n in enumerate(NAMES)] + [
    # значения вне словарей формы — их правка рукой не должна затирать
    {"id": "mx", "name": "Порошок-тест", "inn": "", "for": "", "class": "", "dose": "", "regimen": "", "timing": "",
     "form": "порошок", "taking": False, "archived": False, "prescribedBy": "", "expiry": "2027-01", "affects": [],
     "indications": "", "interactions": "", "notes": "", "group": "vitamins"}]}
FILES = {"meds": MEDS,
         "anamnesis": {"schema": "health-anamnesis@1", "updated": "2026-11-02", "family": []},
         "vaccinations": {"schema": "health-vaccinations@1", "updated": "2026-10-01", "vaccinations": []},
         "vitals": {"schema": "health-vitals@1", "updated": "2026-10-01", "height_cm": 180, "weight": []},
         "studies": {"schema": "health-studies@1", "updated": "2026-10-01", "studies": [
             {"id": "sx", "date": "2025-05-05", "kind": "Денситометрия", "area": "поясница", "conclusion": "норма",
              "clinic": "", "doctor": "", "file": "scan.pdf", "notes": ""}]}}
REPORT = "2026-08-04-otchet.md"
REPORT_MD = ("# 2026-08-04 Очень длинное название отчёта о здоровье, чтобы проверить перенос\n\n"
             "## Глава первая\n\nТекст отчёта.\n\n## Глава вторая\n\nЕщё текст.\n")


srv, _base = serve()   # корень репозитория (_pages_stand: очередь соединений 128, один на процесс)
URL = _base + "/tools/health.html"


def wire(pg, saved):
    def fulfill(route, obj, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(obj, ensure_ascii=False))

    pg.route("**/health-data/labs.json*", lambda r: fulfill(r, LABS))
    pg.route("**/health-data/biomarkers-info.json*", lambda r: fulfill(r, {}))
    def reports(route):
        if route.request.url.split("?")[0].endswith("/reports/"):
            return fulfill(route, [{"name": REPORT, "is_dir": False}])
        return route.fulfill(status=200, content_type="text/markdown; charset=utf-8", body=REPORT_MD)
    pg.route("**/health-data/reports/**", reports)
    pg.route("**/health-data/studies/**", lambda r: r.fulfill(status=200, content_type="application/pdf", body=b"%PDF-1.4\n%%EOF"))
    pg.route("**/api/health*", lambda r: fulfill(r, {"health_writable": True, "health_files": list(FILES)}))

    def hd(route):
        req = route.request
        if req.method == "POST":
            body = json.loads(req.post_data)
            saved.append(body)
            return fulfill(route, {"hash": "h2"})
        name = req.url.split("path=")[1].split(".json")[0]
        if name == "labs":      # сайдкар без labs в API → страница читает прежним путём (health-data/labs.json)
            return route.fulfill(status=404, content_type="application/json", body="{}")
        return fulfill(route, {"hash": "h1", "content": json.dumps(FILES[name], ensure_ascii=False)})

    pg.route("**/api/hd/**", hd)


SEL_STATE = """(id) => {
  const h = document.getElementById(id); if (!h) return null;
  const root = h.closest('.ui-select'), b = root.querySelector('.ui-select-btn'), pop = root.querySelector('.ui-select-pop');
  const br = b.getBoundingClientRect(), pr = pop.hidden ? null : pop.getBoundingClientRect();
  const q = root.querySelector('.ui-select-q');
  return { value: h.value, label: root.querySelector('.ui-select-t').textContent, open: !pop.hidden,
           btnH: Math.round(br.height), sheet: root.classList.contains('sheet'),
           pop: pr && { top: Math.round(pr.top), bottom: Math.round(pr.bottom), left: Math.round(pr.left), right: Math.round(pr.right) },
           btnTop: Math.round(br.top), btnBottom: Math.round(br.bottom),
           vis: [...root.querySelectorAll('.ui-opt')].filter(o => !o.hidden).map(o => o.querySelector('.ui-opt-t').textContent),
           qFont: q ? getComputedStyle(q).fontSize : null, qFocused: !!q && document.activeElement === q };
}"""


def wait_saved(pg, saved, n0, limit_ms=2000):
    """Дождаться перехваченного POST (len(saved) > n0) вместо фиксированных 400 мс; затем два кадра —
    страница успевает отрисовать итог сохранения. Не дождались — решает проверка (TST-1)."""
    for _ in range(limit_ms // 50):
        if len(saved) > n0:
            break
        pg.wait_for_timeout(50)
    frames(pg, 80)


def open_sel(pg, sid):
    pg.locator(f"#{sid} ~ .ui-select-btn").click()
    frames(pg, 40)   # список раскрывается синхронно по клику: два кадра + запас (было 120 мс)


def pick(pg, sid, text):
    open_sel(pg, sid)
    pg.locator(f"#{sid} ~ .ui-select-pop .ui-opt", has_text=text).first.click()
    frames(pg, 60)   # "change" и перерисовка страницы синхронны: два кадра + запас (было 150 мс)


def run(eng_name, browser):
    for w, h in ((1280, 820), (390, 760)):
        tag = f"{eng_name} {w}px"
        phone = w <= 600
        ctx = browser.new_context(viewport={"width": w, "height": h}, has_touch=phone)
        ctx.add_init_script("localStorage.setItem('hub-auth','dGVzdDp0ZXN0');")
        pg = ctx.new_page()
        errs, saved = [], []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        dialogs = []
        pg.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))   # нативных быть не должно
        wire(pg, saved)
        pg.goto(URL)
        settle(pg, "!!document.querySelector('[data-act=\"tab\"][data-id=\"markers\"]')", margin=300)

        # 1. сортировка биомаркеров (панель фильтров, обычный размер)
        pg.evaluate("document.querySelector('[data-act=\"tab\"][data-id=\"markers\"]').click()")
        pg.wait_for_timeout(300)
        s = pg.evaluate(SEL_STATE, "sort")
        check(f"{tag}: «Сортировка» — общий список, нативного <select> нет",
              s is not None and pg.locator("select").count() == 0)
        if s:
            check(f"{tag}: «Сортировка» мишень {'≥ 44' if phone else '≥ 36'}px ({s['btnH']})",
                  s["btnH"] >= (44 if phone else 36))
            pick(pg, "sort", "по отклонению")
            s2 = pg.evaluate(SEL_STATE, "sort")
            order = pg.evaluate("[...document.querySelectorAll('[data-act=\"open\"]')].map(e => e.textContent).join('|')")
            check(f"{tag}: выбор «по отклонению» применён ({s2['value']}, {s2['label']!r})",
                  s2["value"] == "dev" and s2["label"] == "по отклонению" and not s2["open"])
            check(f"{tag}: список биомаркеров перестроен (ЛДГ вне нормы — первым)",
                  order.find("ЛДГ") != -1 and order.find("ЛДГ") < order.find("Глюкоза"))

        # 1б. назначение в аптечке
        pg.evaluate("document.querySelector('[data-act=\"tab\"][data-id=\"meds\"]').click()")
        pg.wait_for_timeout(300)
        g = pg.evaluate(SEL_STATE, "med-group-sel")
        check(f"{tag}: «Назначение» аптечки — общий список", g is not None)
        if g:
            pick(pg, "med-group-sel", "Аллергия")
            g2 = pg.evaluate(SEL_STATE, "med-group-sel")
            shown = pg.evaluate("document.body.innerText")
            check(f"{tag}: фильтр «Аллергия» применён ({g2['value']})",
                  g2["value"] == "allergy" and "Лоратадин" in shown and "Смекта" not in shown)
            pick(pg, "med-group-sel", "Назначение: все")

        # 2. форма нового лекарства: подстановка с поиском
        pg.evaluate("document.querySelector('[data-act=\"med-add\"]').click()")
        pg.wait_for_timeout(300)
        # окно формы — общее ui-kit (uiModalHTML): кнопки закреплены, на телефоне — весь экран
        mw = pg.evaluate("""() => { const b = document.querySelector('.ui-modal-box'); if (!b) return null;
          const r = b.getBoundingClientRect(), sv = document.querySelector('.ui-modal-save').getBoundingClientRect(),
                bd = document.querySelector('.ui-modal-body');
          return { w: Math.round(r.width), h: Math.round(r.height), saveIn: sv.bottom <= innerHeight && sv.top >= 0,
                   scrolls: bd.scrollHeight > bd.clientHeight, vw: innerWidth, vh: innerHeight }; }""")
        check(f"{tag}: форма — общее окно ui-kit ({mw})", mw is not None)
        if mw:
            check(f"{tag}: «Сохранить» видна без прокрутки длинной формы (поля прокручиваются: {mw['scrolls']})", mw["saveIn"])
            if phone:
                check(f"{tag}: телефон — форма во весь экран ({mw['w']}×{mw['h']} при {mw['vw']}×{mw['vh']})",
                      mw["w"] == mw["vw"] and mw["h"] == mw["vh"])
        t = pg.evaluate(SEL_STATE, "f-tpl")
        check(f"{tag}: «Заполнить по прежнему» — общий список", t is not None)
        if t:
            open_sel(pg, "f-tpl")
            t1 = pg.evaluate(SEL_STATE, "f-tpl")
            check(f"{tag}: длинный список открывается с поиском, курсор в поле ({t1['qFocused']})", t1["qFocused"])
            # длинный список в форме — одна строка (ui-kit 1.29.0, решение владельца):
            # поле ввода встаёт на место кнопки, подсказки — под ним ПОВЕРХ содержимого
            # (ui-kit 1.62.0: кнопка невидима и держит высоту), не заходя на шапку окна
            # («Новое лекарство»)
            cb2 = pg.evaluate("""() => { const h = document.getElementById('f-tpl'), root = h.closest('.ui-select');
              const head = document.querySelector('.ui-modal-head').getBoundingClientRect();
              const q = root.querySelector('.ui-select-q').getBoundingClientRect();
              return { combo: root.classList.contains('combo'), btnHidden: getComputedStyle(root.querySelector('.ui-select-btn')).visibility === 'hidden',
                       qTop: Math.round(q.top), headBottom: Math.round(head.bottom), inFlow: getComputedStyle(root.querySelector('.ui-select-pop')).position === 'fixed' }; }""")
            check(f"{tag}: «Заполнить по прежнему» — одна строка: поле ввода на месте кнопки, подсказки поверх ({cb2})",
                  cb2["combo"] and cb2["btnHidden"] and cb2["inFlow"])
            check(f"{tag}: поле ввода не под шапкой окна ({cb2['qTop']} ≥ {cb2['headBottom']})", cb2["qTop"] >= cb2["headBottom"])
            if phone:
                check(f"{tag}: телефон — шрифт поиска 16px ({t1['qFont']})", t1["qFont"] == "16px")
            cb = pg.locator("#f-tpl ~ .ui-select-pop .ui-select-close")
            box = cb.bounding_box()
            check(f"{tag}: у поиска есть крестик «закрыть» ({box and round(box['height'])}px)",
                  box is not None and box["height"] >= (44 if phone else 34))
            cb.click()
            pg.wait_for_timeout(120)
            check(f"{tag}: крестик закрыл список одним касанием, окно формы на месте",
                  not pg.evaluate(SEL_STATE, "f-tpl")["open"] and pg.locator("[data-act=\"med-save\"]").count() == 1)
            open_sel(pg, "f-tpl")
            pg.keyboard.type("нур")
            pg.wait_for_timeout(100)
            t2 = pg.evaluate(SEL_STATE, "f-tpl")
            check(f"{tag}: «нур» → только Нурофены ({t2['vis']})",
                  t2["vis"] == ["Нурофен · 200 мг", "Нурофен Экспресс"])
            pg.keyboard.type("ZZZ")
            pg.wait_for_timeout(80)
            check(f"{tag}: ничего не найдено — пустой список с подсказкой",
                  pg.evaluate(SEL_STATE, "f-tpl")["vis"] == []
                  and pg.locator("#f-tpl ~ .ui-select-pop .ui-select-none").is_visible())
            pg.fill("#f-tpl ~ .ui-select-pop .ui-select-q", "ёлка")
            pg.wait_for_timeout(80)
            check(f"{tag}: поиск не различает е/ё и регистр",
                  pg.evaluate(SEL_STATE, "f-tpl")["vis"] == ["Called Ё-тест Ёлка"])
            pg.fill("#f-tpl ~ .ui-select-pop .ui-select-q", "нур")
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(300)
            check(f"{tag}: Enter — первый найденный, подстановка сработала (название и справка)",
                  pg.input_value("#f-name") == "Нурофен"
                  and pg.evaluate("document.querySelector('#f-tpl') !== null"))
            check(f"{tag}: окно формы не закрылось",
                  pg.locator("[data-act=\"med-save\"]").count() == 1)

        # 3. выбор не стирает набранное; сохраняется выбранное
        pg.fill("#f-name", "Тестовое лекарство")
        pg.fill("#f-dose", "5 мг")
        pick(pg, "f-group", "Глаза")
        pick(pg, "f-form", "капли")
        check(f"{tag}: выбор в списках не стёр набранное в полях",
              pg.input_value("#f-name") == "Тестовое лекарство" and pg.input_value("#f-dose") == "5 мг")
        fs = pg.evaluate(SEL_STATE, "f-form")
        check(f"{tag}: «Форма» — подпись и значение на месте ({fs['value']}, {fs['label']!r})",
              fs["value"] == "капли" and fs["label"] == "капли")

        # 4. раскрытая часть целиком на экране (нижнее поле формы)
        open_sel(pg, "f-form")
        o = pg.evaluate(SEL_STATE, "f-form")
        vh = pg.evaluate("innerHeight")
        check(f"{tag}: список «Форма» целиком на экране ({o['pop']}, экран {vh})",
              o["pop"] is not None and o["pop"]["top"] >= 0 and o["pop"]["bottom"] <= vh and o["pop"]["right"] <= w)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(100)
        check(f"{tag}: Esc закрыл список, а не окно формы",
              not (pg.evaluate(SEL_STATE, "f-form") or {"open": True})["open"]
              and pg.locator("[data-act=\"med-save\"]").count() == 1)
        if pg.locator("[data-act=\"med-save\"]").count() == 0:
            print(f"  {tag}: окно формы закрыто — дальнейшие шаги формы пропущены")
            ctx.close()
            continue

        # 5. клавиатура (на компьютере)
        if not phone:
            pg.locator("#f-form ~ .ui-select-btn").focus()
            pg.keyboard.press("ArrowDown")
            pg.wait_for_timeout(80)
            pg.keyboard.press("ArrowDown")
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(120)
            k = pg.evaluate(SEL_STATE, "f-form")
            check(f"{tag}: клавиатура ↓ ↓ Enter — выбран следующий вариант ({k['value']})",
                  k["value"] == "другое" and not k["open"])
            pick(pg, "f-form", "капли")

        # «Назначение» — обычный список без поиска; раскрытие — в пределах полей окна
        open_sel(pg, "f-group")
        gp = pg.evaluate("""() => { const root = document.getElementById('f-group').closest('.ui-select');
          const pop = root.querySelector('.ui-select-pop').getBoundingClientRect(), body = document.querySelector('.ui-modal-body').getBoundingClientRect();
          return { search: !!root.querySelector('.ui-select-q'), top: Math.round(pop.top), bottom: Math.round(pop.bottom),
                   bTop: Math.round(body.top), bBottom: Math.round(body.bottom),
                   rowH: Math.round(root.querySelector('.ui-opt').getBoundingClientRect().height) }; }""")
        check(f"{tag}: «Назначение» — без поиска, список в пределах полей окна, не на шапке ({gp})",
              not gp["search"] and gp["top"] >= gp["bTop"] - 1 and gp["bottom"] <= gp["bBottom"] + 1)
        check(f"{tag}: строки списка в форме — низкие, как подсказки «Еды» ({gp['rowH']}px)", gp["rowH"] <= 40)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(100)
        n0 = len(saved)
        pg.click("[data-act=\"med-save\"]")
        wait_saved(pg, saved, n0)
        med = None
        if saved:
            doc = json.loads(saved[-1]["content"])
            med = [m for m in doc["meds"] if m["name"] == "Тестовое лекарство"]
        check(f"{tag}: сохранение отправило выбранные «Назначение» и «Форму» ({med and med[0]['group']}, {med and med[0]['form']})",
              bool(med) and med[0]["group"] == "eye" and med[0]["form"] == "капли" and med[0]["dose"] == "5 мг")

        # 6. форма исследования: вид по умолчанию (УЗИ) уходит как раньше
        pg.evaluate("document.querySelector('[data-act=\"tab\"][data-id=\"studies\"]').click()")
        pg.wait_for_timeout(300)
        pg.evaluate("document.querySelector('[data-act=\"study-add\"]').click()")
        pg.wait_for_timeout(300)
        k0 = pg.evaluate(SEL_STATE, "f-kind")
        check(f"{tag}: «Вид» исследования — общий список, по умолчанию УЗИ ({k0 and k0['value']})",
              k0 is not None and k0["value"] == "УЗИ" and k0["label"] == "УЗИ")
        n0 = len(saved)
        pick(pg, "f-kind", "ЭКГ")
        pg.click("[data-act=\"study-save\"]")
        wait_saved(pg, saved, n0)
        st = json.loads(saved[-1]["content"])["studies"] if len(saved) > n0 else []
        check(f"{tag}: исследование сохранено с выбранным видом ({st and st[-1]['kind']})",
              bool(st) and st[-1]["kind"] == "ЭКГ")

        # клик по затемнению закрывает форму (на компьютере — вокруг окна есть поле)
        if not phone:
            pg.evaluate("document.querySelector('[data-act=\"tab\"][data-id=\"meds\"]').click()")
            pg.wait_for_timeout(200)
            pg.evaluate("document.querySelector('[data-act=\"med-add\"]').click()")
            pg.wait_for_timeout(300)
            pg.mouse.click(8, h - 8)
            pg.wait_for_timeout(200)
            check(f"{tag}: клик по затемнению закрыл форму", pg.locator(".ui-modal").count() == 0)
        # 7. значения вне словарей: показываются «нет в списке» и не затираются
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(150)
        def act(a, i):
            pg.evaluate("([a, i]) => { const b = document.createElement('button'); b.setAttribute('data-act', a);"
                        " b.setAttribute('data-id', i); document.body.append(b); b.click(); b.remove(); }", [a, i])
            pg.wait_for_timeout(300)
        act("med-edit", "mx")
        f = pg.evaluate(SEL_STATE, "f-form")
        g = pg.evaluate(SEL_STATE, "f-group")
        check(f"{tag}: форма «порошок» вне списка — показана ({f and f['label']!r}, {f and f['value']!r})",
              f is not None and f["value"] == "порошок" and f["label"] == "порошок")
        check(f"{tag}: группа вне словаря сохраняет значение ({g and g['value']!r})", g is not None and g["value"] == "vitamins")
        n0 = len(saved)
        pg.click("[data-act=\"med-save\"]")
        wait_saved(pg, saved, n0)
        mx = [m for m in json.loads(saved[-1]["content"])["meds"] if m["id"] == "mx"] if len(saved) > n0 else []
        check(f"{tag}: сохранение без правок не затёрло «порошок» и группу ({mx and (mx[0]['form'], mx[0]['group'])})",
              bool(mx) and mx[0]["form"] == "порошок" and mx[0]["group"] == "vitamins")
        act("study-edit", "sx")
        k = pg.evaluate(SEL_STATE, "f-kind")
        check(f"{tag}: вид «Денситометрия» вне списка — показан ({k and k['label']!r})",
              k is not None and k["value"] == "Денситометрия")
        n0 = len(saved)
        pg.click("[data-act=\"study-save\"]")
        wait_saved(pg, saved, n0)
        sx = [x for x in json.loads(saved[-1]["content"])["studies"] if x["id"] == "sx"] if len(saved) > n0 else []
        check(f"{tag}: исследование сохранено с прежним видом ({sx and sx[0]['kind']})",
              bool(sx) and sx[0]["kind"] == "Денситометрия")

        # 7б. удаление — общее окно подтверждения ui-kit (uiConfirm), не confirm()
        cf = """() => { const o = document.querySelector('.ui-confirm'); if (!o) return null;
          return { name: (o.querySelector('.ui-confirm-n') || {}).textContent || '',
                   focusNo: document.activeElement === o.querySelector('.ui-confirm-no') }; }"""
        n0 = len(saved)
        act("med-del", "m0")
        c = pg.evaluate(cf)
        check(f"{tag}: удаление лекарства — своё окно с названием, фокус на «Отмене» ({c})",
              c is not None and c["name"] == "Нурофен" and c["focusNo"])
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(150)
        check(f"{tag}: Esc — «нет»: окно закрыто, ничего не сохранено",
              pg.evaluate(cf) is None and len(saved) == n0)
        act("med-del", "m0")
        pg.click(".ui-confirm-no")
        pg.wait_for_timeout(150)
        check(f"{tag}: «Отмена» — ничего не сохранено", pg.evaluate(cf) is None and len(saved) == n0)
        act("med-del", "m0")
        pg.click(".ui-confirm-ok")
        wait_saved(pg, saved, n0)
        gone = len(saved) > n0 and not [m for m in json.loads(saved[-1]["content"])["meds"] if m["id"] == "m0"]
        check(f"{tag}: «Удалить» — лекарство удалено и сохранено", gone)
        check(f"{tag}: нативных диалогов не было {dialogs[:1]}", not dialogs)
        # плашка сохранения — общая ui-kit: ошибка записи видна и убирается «Понятно»
        pg.route("**/api/hd/save", lambda r: r.fulfill(status=409, content_type="application/json", body="{}"))
        act("med-del", "m1")
        pg.click(".ui-confirm-ok")
        pg.wait_for_timeout(400)
        sb = pg.evaluate("""() => { const b = document.querySelector('.ui-savebar'); if (!b) return null; const r = b.getBoundingClientRect();
          return { err: b.classList.contains('err'), text: b.textContent, inView: r.bottom <= innerHeight && r.top >= 0,
                   z: getComputedStyle(b).zIndex }; }""")
        check(f"{tag}: ошибка записи — плашка ui-kit с текстом, на экране ({sb})",
              sb is not None and sb["err"] and "изменились" in sb["text"] and sb["inView"] and sb["z"] == "1050")
        if sb:
            pg.click(".ui-savebar-x")
            pg.wait_for_timeout(150)
            check(f"{tag}: «Понятно» убрал плашку", pg.locator(".ui-savebar").count() == 0)
        pg.unroute("**/api/hd/save")

        # 8. окно документа — общее ui-kit .ui-docwin (ui-kit 1.22.0)
        act("rep-open", REPORT)
        pg.wait_for_timeout(500)
        dw = pg.evaluate("""() => { const w = document.querySelector('.ui-docwin'); if (!w) return null;
          const t = w.querySelector('.ui-docwin-title'), b = w.querySelector('.ui-docwin-box').getBoundingClientRect();
          return { z: getComputedStyle(w).zIndex, title: t.textContent, lines: Math.round(t.getBoundingClientRect().height / parseFloat(getComputedStyle(t).lineHeight)),
                   ellipsis: getComputedStyle(t).whiteSpace === 'nowrap', toc: !!w.querySelector('.rd'), w: Math.round(b.width), h: Math.round(b.height),
                   sub: (w.querySelector('.ui-docwin-sub') || {}).textContent || '' }; }""")
        check(f"{tag}: отчёт открыт в общем окне .ui-docwin, слой 215 поверх форм ({dw and dw['z']})",
              dw is not None and dw["z"] == "215" and dw["toc"])
        if dw:
            check(f"{tag}: имя отчёта целиком в заголовке", dw["title"].startswith("2026-08-04 Очень длинное"))
            if phone:
                check(f"{tag}: телефон — окно во весь экран, имя в две строки, не многоточием ({dw['w']}×{dw['h']}, {dw['lines']} стр.)",
                      dw["w"] == w and not dw["ellipsis"] and dw["lines"] >= 2)
            else:
                check(f"{tag}: компьютер — окно 1000px по центру ({dw['w']})", dw["w"] == 1000)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
        check(f"{tag}: Esc закрыл окно документа", pg.locator(".ui-docwin").count() == 0)
        act("study-file", "sx")
        pg.wait_for_timeout(500)
        lk = pg.evaluate("""() => { const h = document.querySelector('.ui-docwin-head'); if (!h) return null;
          const a = h.querySelector('.ui-docwin-link'), t = h.querySelector('.ui-docwin-titles'), x = h.querySelector('.ui-docwin-x');
          return { link: a && a.textContent, below: a && t && a.getBoundingClientRect().top >= t.getBoundingClientRect().bottom - 1,
                   xRight: x && Math.round(innerWidth - x.getBoundingClientRect().right) }; }""")
        check(f"{tag}: файл исследования — ссылка «Открыть отдельно» в шапке ({lk})",
              lk is not None and lk["link"] == "Открыть отдельно ↗")
        if lk and phone:
            check(f"{tag}: телефон — имени своя строка, ссылка и ✕ ниже ({lk})", lk["below"] and lk["xRight"] < 40)
        pg.click(".ui-docwin-x")
        pg.wait_for_timeout(200)
        check(f"{tag}: ✕ закрыл окно документа", pg.locator(".ui-docwin").count() == 0)

        check(f"{tag}: ошибок JS нет {errs[:2]}", not errs)
        ctx.close()


# ── «Еда»: замена продукта в плане и сопоставление при импорте ──────────────
# Стенд — из test_food_layout (свой каталог во временной папке); продуктов
# добавлено до 16, чтобы список включил поиск, как у владельца (их сотни).
import importlib.util as _ilu
import tempfile as _tf
_spec = _ilu.spec_from_file_location("food_fx", Path(__file__).with_name("test_food_layout.py"))
FX = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(FX)
FX.PRODUCTS = {**FX.PRODUCTS, "products": FX.PRODUCTS["products"] + [
    {"id": f"p{i}", "name": n, "unit": "г", "category": "бакалея"} for i, n in enumerate(
        ["Рис", "Пшено", "Овсянка", "Сахар", "Соль", "Масло сливочное", "Масло оливковое", "Молоко",
         "Сметана", "Творог", "Ёжевика", "Перец"])]}
_food_root = Path(_tf.mkdtemp()) / "Food"
FX.make_food_root(_food_root)
_fsrv, _fbase = serve(FX.make_handler(_food_root), key="food")
FOOD = _fbase + "/tools/food.html"
IMPORT_MD = ('# Блины проверочные\n\n```json\n' + json.dumps({"servings": 2, "ingredients": [
    {"name": "Мука", "qty": 200, "unit": "г"}, {"name": "Неведомый продукт", "qty": 1, "unit": "шт"}]},
    ensure_ascii=False) + '\n```\n')


def run_food(eng_name, browser):
    for w, h in ((1280, 820), (390, 760)):
        tag = f"{eng_name} {w}px еда"
        phone = w <= 600
        ctx = browser.new_context(viewport={"width": w, "height": h}, has_touch=phone)
        pg = ctx.new_page()
        errs, saved = [], []
        pg.on("pageerror", lambda e: errs.append(str(e)))

        def save(route):
            if route.request.method == "POST":
                saved.append(json.loads(route.request.post_data))
                return route.fulfill(status=200, content_type="application/json", body='{"hash":"y"}')
            return route.fallback()
        pg.route("**/api/fd/**", save)

        # замена продукта в плане покупок
        pg.goto(FOOD + "?recipe=plan")
        settle(pg, "!!document.querySelector('[data-act=plan-open]')", margin=300)
        pg.evaluate("document.querySelector('[data-act=plan-open]').click()")
        pg.wait_for_timeout(300)
        pg.evaluate("document.querySelector('[data-act=plan-swap]').click()")
        pg.wait_for_timeout(200)
        sw = pg.evaluate(SEL_STATE, "f-swap")
        check(f"{tag}: «заменить на другое» — общий список, нативного <select> нет",
              sw is not None and pg.locator("select").count() == 0)
        if sw:
            open_sel(pg, "f-swap")
            o = pg.evaluate(SEL_STATE, "f-swap")
            check(f"{tag}: замена — список с поиском (продуктов 16), курсор в поле", o["qFocused"])
            pg.keyboard.type("ежев")
            pg.wait_for_timeout(80)
            check(f"{tag}: «ежев» находит «Ёжевика» ({pg.evaluate(SEL_STATE, 'f-swap')['vis']})",
                  pg.evaluate(SEL_STATE, "f-swap")["vis"] == ["Ёжевика"])
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(300)
            body = pg.evaluate("(document.getElementById('plan-body') || document.body).innerText")
            check(f"{tag}: строка плана заменена на выбранный продукт", "куплю: Ёжевика" in body)
            check(f"{tag}: окно плана не закрылось", pg.evaluate("!!document.getElementById('plan-body')"))

        # удаление продукта — общее окно подтверждения с предупреждением
        pg.goto(FOOD)
        settle(pg, "!!document.querySelector('[data-act=nav][data-arg=recipes]')", margin=300)
        pg.evaluate("() => { const b = document.createElement('button'); b.setAttribute('data-act', 'prod-edit');"
                    " b.setAttribute('data-arg', 'muka'); document.body.append(b); b.click(); b.remove(); }")
        pg.wait_for_timeout(300)
        pg.evaluate("document.querySelector('[data-act=prod-del]').click()")
        pg.wait_for_timeout(200)
        cw = pg.evaluate("""() => { const o = document.querySelector('.ui-confirm'); return o && { name: o.querySelector('.ui-confirm-n').textContent,
          warn: (o.querySelector('.ui-confirm-w') || {}).textContent || '' }; }""")
        check(f"{tag}: удаление продукта — своё окно: название и какие рецепты ссылаются ({cw})",
              cw is not None and cw["name"] == "Мука" and "ссылаются рецепты" in cw["warn"])
        n0 = len(saved)
        pg.click(".ui-confirm-ok")
        pg.wait_for_timeout(500)
        prods = [json.loads(b["content"]) for b in saved[n0:] if "content" in b]
        check(f"{tag}: «Удалить» — продукт убран из каталога",
              any(isinstance(x, dict) and "products" in x and not [p for p in x["products"] if p["id"] == "muka"] for x in prods))

        # сопоставление ингредиентов при импорте рецепта
        pg.goto(FOOD)
        settle(pg, "!!document.querySelector('[data-act=nav][data-arg=recipes]')", margin=300)
        pg.evaluate("document.querySelector('[data-act=nav][data-arg=recipes]').click()")
        pg.wait_for_timeout(250)
        pg.evaluate("document.querySelector('[data-act=import-open]').click()")
        pg.wait_for_timeout(250)
        pg.fill("#f-import", IMPORT_MD)
        pg.evaluate("document.querySelector('[data-act=import-parse]').click()")
        pg.wait_for_timeout(300)
        m0, m1 = pg.evaluate(SEL_STATE, "f-map-0"), pg.evaluate(SEL_STATE, "f-map-1")
        check(f"{tag}: импорт — списки сопоставления общие ({m0 and m0['label']!r}, {m1 and m1['label']!r})",
              m0 is not None and m1 is not None and pg.locator("select").count() == 0)
        if m0 and m1:
            check(f"{tag}: «Мука» найдена сама, «Неведомый» — не связан",
                  m0["value"] == "muka" and m1["value"] == "")
            open_sel(pg, "f-map-1")
            pg.keyboard.type("кеф")
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(200)
            check(f"{tag}: выбран «Кефир» для «Неведомого»", pg.evaluate(SEL_STATE, "f-map-1")["value"] == "kefir")
            n0 = len(saved)
            pg.evaluate("document.querySelector('[data-act=import-save]').click()")
            wait_saved(pg, saved, n0, limit_ms=5000)
            rec = None
            for b in saved:
                try:
                    c = json.loads(b.get("content", "{}"))
                except Exception:
                    continue
                if c.get("title") == "Блины проверочные":
                    rec = c
            ids = [g.get("product_id") for g in (rec or {}).get("ingredients", [])]
            check(f"{tag}: рецепт сохранён с выбранными продуктами ({ids})", ids == ["muka", "kefir"])
        check(f"{tag}: ошибок JS нет {errs[:2]}", not errs)
        ctx.close()


# ── вьюер портфеля: сектор/риск и версия отчёта (ui-kit подключён с 2.19.0) ──
# Синтетики под вьюер нет (он читает десяток видов отчётов) — берём реальные
# данные Synology, как контракт-тест берёт реальные trip.yaml. Нет монтирования —
# честный пропуск вьюера, не падение. Каталоги — HTML-листингом, как у Caddy.
from http.server import BaseHTTPRequestHandler as _BH
from urllib.parse import unquote as _unq, urlparse as _up, quote as _q
MEM = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory"


class _VH(_BH):
    def log_message(self, *a):
        pass

    def do_GET(self):
        p = _unq(_up(self.path).path)
        f = REPO / "tools" / p[len("/tools/"):] if p.startswith("/tools/") else MEM / p.lstrip("/")
        if f.is_dir():
            if "json" in (self.headers.get("Accept") or ""):
                body = json.dumps([{"name": c.name + ("/" if c.is_dir() else ""), "is_dir": c.is_dir()}
                                   for c in sorted(f.iterdir())]).encode()
                ct = "application/json"
            else:
                body = ("<html><body>" + "".join(f'<a href="{_q(c.name)}{"/" if c.is_dir() else ""}">{c.name}</a>\n'
                                                 for c in sorted(f.iterdir())) + "</body></html>").encode()
                ct = "text/html"
        elif f.is_file():
            body = f.read_bytes()
            ct = {".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css",
                  ".json": "application/json", ".woff2": "font/woff2"}.get(f.suffix, "text/plain; charset=utf-8")
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_viewer(eng_name, browser):
    if not (MEM / "Portfolio" / "weekly-reviews").is_dir():
        print(f"  {eng_name}: пропуск вьюера — Synology не смонтирован")
        return
    _vsrv, _vbase = serve(_VH, key="viewer")   # один сервер вьюера на процесс, движки делят его
    url = _vbase + "/tools/portfolio-integrated-viewer.html"
    rows = "() => document.querySelectorAll('main tbody tr').length"
    # сбой загрузки папки не глотается молча (viewer 2.23.11): разовый 500 лечится повтором —
    # предупреждения нет; постоянный 500 — предупреждение с названием папки над вкладками
    for mode in ("once", "always"):
        pgf = browser.new_page(viewport={"width": 1280, "height": 900})
        hits = {"n": 0}

        def make_flaky(mode, hits):
            # Playwright зовёт обработчик как handler(route, request): лишние позиционные
            # аргументы с умолчаниями перетираются — поэтому замыкание, а не mode=mode
            def flaky(route):
                hits["n"] += 1
                if mode == "always" or hits["n"] == 1:
                    route.fulfill(status=500, body="boom")
                else:
                    route.continue_()
            return flaky
        flaky = make_flaky(mode, hits)
        pgf.route("**/macro-snapshots/", flaky)
        pgf.goto(url)
        pgf.wait_for_selector("#tabs .ui-tab", timeout=20000)
        if mode == "always":
            try:
                pgf.wait_for_function("() => /Не загрузилось/.test((document.querySelector('#banners') || {}).textContent || '')",
                                      timeout=15000)
            except Exception:
                pass  # итог ниже проверит check по тексту баннера
        else:
            # разовый сбой: ждём повтора запроса (hits ≥ 2) и загрузки вкладок, затем запас — предупреждение
            # появилось бы сразу после неудачного повтора (раньше — фиксированные 3 с)
            for _ in range(60):
                if hits["n"] >= 2:
                    break
                pgf.wait_for_timeout(50)
            settle(pgf, "!!document.querySelector('[data-ui-tab=\"positions\"]')", timeout=5000, margin=800)
        warn = pgf.evaluate("() => (document.querySelector('#banners .ui-alert.warn') || {}).textContent || ''")
        if mode == "once":
            check(f"{eng_name} вьюер: разовый сбой папки вылечен повтором, предупреждения нет ({hits['n']} запр.)",
                  hits["n"] >= 2 and "macro-snapshots" not in warn)
        else:
            check(f"{eng_name} вьюер: постоянный сбой папки — предупреждение с её названием",
                  "Не загрузилось с сервера" in warn and "macro-snapshots/" in warn)
        pgf.close()
    for w in (1280, 390):
        tag = f"{eng_name} {w}px вьюер"
        pg = browser.new_page(viewport={"width": w, "height": 900})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        # вкладки строятся по данным с Synology-зеркала; загрузчик вьюера глотает сбой запроса
        # (fetchDirListing → []), и при сбое пропадают папки снапшотов/macro — вкладок «Акции»/«IE Model»
        # нет. Случайный сбой окружения, не регрессия: до 3 загрузок, ждём сами нужные вкладки.
        # viewer 3.0.0: строка разделов — ui-kit .ui-tabs (кнопки [data-ui-tab]), без эмодзи;
        # «IE Model» стала «Доли и цели» (ребалансировка, без фильтров-списков)
        for attempt in range(3):
            pg.goto(url)
            pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
            try:
                pg.wait_for_function("() => !!document.querySelector('[data-ui-tab=\"positions\"]') && !!document.querySelector('[data-ui-tab=\"ie-model\"]')",
                                     timeout=15000)
                break
            except Exception:
                if attempt == 2:
                    raise
        pg.wait_for_timeout(500)
        pg.evaluate("goToTab('ie-model')")
        pg.wait_for_timeout(400)
        check(f"{tag} «Доли и цели»: таблица долей есть, нативных списков нет",
              pg.evaluate(rows) > 0 and pg.locator("select").count() == 0)
        for tab, n_exp in (("Акции", 1),):
            pg.evaluate("(t) => document.querySelector(`[data-ui-tab=\"${t}\"]`).click()", "positions")
            pg.wait_for_timeout(400)
            # viewer 3.27.0: на телефоне панель фильтров спрятана — кнопка «Фильтры» у поиска
            # открывает окно-шторку; на компьютере панель над таблицей, кнопки нет
            vis = pg.evaluate("() => ({ home: !!document.querySelector('.flt-home')?.offsetParent, btn: !!document.querySelector('.ui-fbtn')?.offsetParent })")
            if w < 600:
                check(f"{tag} «{tab}»: панель фильтров спрятана, кнопка «Фильтры» видна", not vis["home"] and vis["btn"])
                pg.locator(".ui-fbtn").click()
                pg.wait_for_timeout(450)
                check(f"{tag} «{tab}»: «Фильтры» открывает окно с панелью", pg.locator("#flt-sheet .filters").count() == 1)
            else:
                check(f"{tag} «{tab}»: панель фильтров видна, кнопки «Фильтры» нет", vis["home"] and not vis["btn"])
            sels = pg.locator(".filters .ui-select")
            check(f"{tag} «{tab}»: фильтры — общие списки ({sels.count()}), нативных нет",
                  sels.count() == n_exp and pg.locator("select").count() == 0)
            for k in range(sels.count()):
                r0 = pg.evaluate(rows)
                sels.nth(k).locator(".ui-select-btn").click()
                pg.wait_for_timeout(120)
                opt = sels.nth(k).locator(".ui-opt").nth(1)
                name = opt.locator(".ui-opt-t").inner_text()
                opt.click()
                pg.wait_for_timeout(350)
                r1 = pg.evaluate(rows)
                lbl = pg.locator(".filters .ui-select").nth(k).locator(".ui-select-t").inner_text()
                check(f"{tag} «{tab}» #{k}: «{name}» сужает таблицу ({r0} → {r1}), подпись на месте",
                      0 < r1 < r0 and lbl == name)
                pg.locator(".filters .ui-select").nth(k).locator(".ui-select-btn").click()
                pg.wait_for_timeout(120)
                pg.locator(".filters .ui-select").nth(k).locator(".ui-opt").nth(0).click()
                pg.wait_for_timeout(350)
                check(f"{tag} «{tab}» #{k}: «все» возвращает таблицу", pg.evaluate(rows) == r0)
            if w < 600:
                check(f"{tag} «{tab}»: окно фильтров пережило выбор (открыто заново с новой панелью)", pg.locator("#flt-sheet .filters").count() == 1)
                pg.keyboard.press("Escape")
                pg.wait_for_timeout(250)
                check(f"{tag} «{tab}»: Esc закрывает окно фильтров, панель вернулась в карточку",
                      pg.locator("#flt-sheet").count() == 0 and pg.locator(".flt-home .filters").count() == 1)
        # версия отчёта в окне документа
        pg.evaluate("document.querySelector('[data-ui-tab=\"positions\"]').click()")
        pg.wait_for_timeout(300)
        pg.evaluate("[...document.querySelectorAll('button')].find(b => /полный отчёт/i.test(b.textContent)).click()")
        pg.wait_for_timeout(700)
        vs = pg.locator(".report-head .ui-select")
        if vs.count():
            vs.locator(".ui-select-btn").click()
            pg.wait_for_timeout(150)
            opt = vs.locator(".ui-opt").nth(1)
            name = opt.locator(".ui-opt-t").inner_text()
            opt.click()
            pg.wait_for_timeout(700)
            check(f"{tag}: версия отчёта переключилась на «{name}», окно открыто",
                  pg.locator(".report-head .ui-select .ui-select-t").inner_text() == name
                  and pg.evaluate("!document.getElementById('modal-overlay').hidden"))
        else:
            check(f"{tag}: у обзора акций одна версия — списка версий нет (не ошибка)", True)
        # справка — общий читатель ui-kit (uiHelpOpen) с оглавлением (viewer 2.21.0)
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
        pg.evaluate("() => { const o = document.getElementById('modal-overlay'); if (o) o.hidden = true; }")
        pg.click("#btn-help")
        settle(pg, "!!document.querySelector('.uh-overlay .uh-err') || document.querySelectorAll('.uh-overlay .rd-doc h2').length >= 5", margin=300)
        hp = pg.evaluate("""() => { const o = document.querySelector('.uh-overlay'); if (!o) return null;
          return { toc: !!o.querySelector('.rd-has-toc, .rd-toc, .rd-bar'), h2: o.querySelectorAll('.rd-doc h2').length,
                   err: !!o.querySelector('.uh-err') }; }""")
        check(f"{tag}: справка — общий читатель с оглавлением ({hp})", bool(hp) and hp["toc"] and hp["h2"] >= 5 and not hp["err"])
        # справка из 11 частей (assets/help/viewer/NN-slug.md), режим «по разделам»: 10 разделов + «О справке», один открыт
        SEC = r"""() => { const o = document.querySelector('.uh-overlay'); if (!o) return null;
          const on = [...o.querySelectorAll('.rd-sec.is-on')];
          return { h2: o.querySelectorAll('.rd-doc h2').length, on: on.length, onTitle: on[0] ? (on[0].querySelector('h2,h3') || on[0]).textContent.trim() : '',
                   toc: [...o.querySelectorAll('.rd-toc li.lvl-2 a')].map(a => a.textContent.trim()),
                   raw: /\{#[a-z-]+\}|<\/?details|<summary/.test(o.querySelector('.rd-doc').textContent), err: !!o.querySelector('.uh-err') }; }"""
        sec = pg.evaluate(SEC)
        check(f"{tag}: справка из частей — 10 разделов и «О справке» в оглавлении, один раздел на экране, сырой разметки нет ({sec and (sec['h2'], sec['on'], len(sec['toc']))})",
              bool(sec) and sec["h2"] == 10 and sec["on"] == 1 and len(sec["toc"]) >= 11 and any("О справке" in t for t in sec["toc"])
              and not sec["raw"] and not sec["err"])
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
        # «Mode N → справка» открывает раздел 2 на таблице режимов, окно Gate — раздел 6
        pg.evaluate("() => openModesHelp(null)")
        settle(pg, "!!document.querySelector('.uh-overlay .rd-sec.is-on #modes')", margin=400)
        sm = pg.evaluate(SEC)
        check(f"{tag}: openModesHelp — открыт раздел 2 (модели), таблица режимов на экране ({sm and sm['onTitle']})",
              bool(sm) and sm["on"] == 1 and "Модели и режимы" in sm["onTitle"] and pg.evaluate(
                  "() => { const h = document.querySelector('.uh-overlay #modes'); return !!h && h.getBoundingClientRect().height > 0; }"))
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
        pg.evaluate("() => openGatesHelp(null)")
        settle(pg, "/Решения/.test((document.querySelector('.uh-overlay .rd-sec.is-on h2') || {}).textContent || '')", margin=400)
        sg = pg.evaluate(SEC)
        check(f"{tag}: openGatesHelp — открыт раздел 6 (решения и докупка; R27: слова «гейт» в заголовке нет) ({sg and sg['onTitle']})", bool(sg) and sg["on"] == 1 and "Решения" in sg["onTitle"])
        # поиск по всему документу: счётчик и «·N» у разделов
        pg.locator(".uh-overlay input[data-rd-q]:visible").first.fill("докупк")   # R27: «гейт» ушёл из справки, ищем «докупка/докупку» (7 разделов)
        pg.wait_for_timeout(600)
        sq = pg.evaluate(r"""() => { const o = document.querySelector('.uh-overlay');
          return { cnt: (o.querySelector('.ui-qbox') || o).textContent, marks: o.querySelectorAll('mark.rd-hit').length,
                   dots: [...o.querySelectorAll('.rd-toc a')].filter(a => /·\s*\d+/.test(a.textContent)).length }; }""")
        check(f"{tag}: поиск «докупк» по всей справке — подсветка есть, «·N» у нескольких разделов ({sq})", sq["marks"] > 0 and sq["dots"] >= 3)
        pg.keyboard.press("Escape")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(200)
        check(f"{tag}: Esc закрыл справку, вьюер на месте",
              pg.locator(".uh-overlay").count() == 0 and pg.locator("#tabs .ui-tab").count() > 0)
        check(f"{tag}: ошибок JS нет {errs[:2]}", not errs)
        pg.close()
    # карточка бумаги на телефоне (viewer 3.2.1): открытая из прокрученной таблицы, она стоит
    # поверх экрана, а не вверху документа (на iPhone так было с блокировкой фона
    # overflow:hidden на html/body); после закрытия прокрутка на прежнем месте
    pm = browser.new_page(viewport={"width": 390, "height": 844}, has_touch=True)
    pm.on("pageerror", lambda e: errs.append(str(e)))
    pm.goto(url)
    pm.wait_for_function("() => typeof state !== 'undefined' && state.files.length > 0", timeout=30000)
    pm.wait_for_timeout(500)
    # широкая таблица на телефоне (viewer 3.4.0, ui-kit 1.43.0): копия шапки липнет под закреплённой
    # частью и едет вбок вместе с таблицей; смена горизонта не сбрасывает прокрутку вбок.
    # Вьюер 4.2.0 (F10): на телефоне второстепенные колонки под «ещё ▾» — раскрываем их, чтобы таблица была широкой
    pm.evaluate("localStorage.setItem('piv-cols-more-positions', '1'); goToTab('positions')")
    pm.wait_for_timeout(500)
    sh = pm.evaluate("""() => new Promise(res => { const w = document.querySelector('#content .ui-table-wrap'); w.scrollLeft = 120;
      scrollTo(0, w.getBoundingClientRect().top + scrollY + 500);
      setTimeout(() => { const h = w.previousElementSibling, ok = h && h.classList.contains('ui-table-shead');
        const a = ok && h.querySelector('th:nth-child(2)').getBoundingClientRect(), c = w.querySelector('tbody td:nth-child(2)').getBoundingClientRect();
        res({ ok, top: ok && Math.round(h.getBoundingClientRect().top), chrome: Math.round(document.getElementById('top-chrome').getBoundingClientRect().bottom),
              dx: ok && Math.abs(a.left - c.left), dw: ok && Math.abs(a.width - c.width) }); }, 400); })""")
    check(f"  {eng_name} телефон «Акции»: шапка широкой таблицы липнет под закреплённой частью и совпадает с колонками ({sh})",
          sh["ok"] and abs(sh["top"] - sh["chrome"]) < 2 and sh["dx"] < 1.5 and sh["dw"] < 1.5)
    pm.evaluate("setHorizon(6)")
    pm.wait_for_timeout(400)
    sl = pm.evaluate("document.querySelector('#content .ui-table-wrap').scrollLeft")
    pm.evaluate("setHorizon(12)")
    check(f"  {eng_name} телефон «Акции»: смена горизонта не сбрасывает прокрутку таблицы вбок ({sl})", sl >= 100)
    pm.evaluate("scrollTo(0, 0)")
    for tab in ("positions", "bonds", "ie-model"):
        pm.evaluate(f"goToTab('{tab}')")
        pm.wait_for_timeout(400)
        rws = pm.locator("#content tbody tr.pick")
        if rws.count() < 6:
            check(f"  {eng_name} телефон «{tab}»: строк мало для проверки ({rws.count()}) — пропуск", True)
            continue
        rws.nth(min(10, rws.count() - 1)).scroll_into_view_if_needed()
        y0 = pm.evaluate("scrollY")
        # клик по первой ячейке строки: центр широкой строки «Долей и целей» может попасть на встроенный список «План» (он правит план, а не открывает карточку)
        rws.nth(min(10, rws.count() - 1)).locator("td").first.click()
        pm.wait_for_timeout(600)
        box = pm.evaluate("""() => { const b = document.querySelector('#card-layer .ui-modal-box');
          if (!b) return null; const r = b.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, ih: innerHeight }; }""")
        check(f"  {eng_name} телефон «{tab}»: карточка из прокрученной таблицы (y={y0}) — поверх экрана ({box})",
              y0 > 200 and box and abs(box["top"]) < 2 and box["bottom"] > box["ih"] - 2)
        # сворачивание шапки (viewer 3.3.0, ui-kit 1.42.0 .ui-modal.fold): прокручивается всё окно,
        # плитки уходят, подвкладки липнут под шапкой, строка под названием — сводка
        fd = pm.evaluate("""() => { const m = [...document.querySelectorAll('#card-layer .ui-modal')].pop(), box = m.querySelector('.ui-modal-box');
          const r0 = m.querySelector('.ui-modal-stick').getBoundingClientRect().top; box.scrollTop = 600;
          return new Promise(res => setTimeout(() => res({ r0, folded: m.classList.contains('folded'), st: box.scrollTop,
            stick: m.querySelector('.ui-modal-stick').getBoundingClientRect().top, head: m.querySelector('.ui-modal-head').getBoundingClientRect().bottom,
            titleLines: Math.round(m.querySelector('.ui-modal-title').getBoundingClientRect().height / parseFloat(getComputedStyle(m.querySelector('.ui-modal-title')).lineHeight)) }), 400)); }""")
        check(f"  {eng_name} телефон «{tab}»: шапка сворачивается — прокручивается окно, подвкладки под шапкой, сводка вместо строки ({fd})",
              fd["st"] > 100 and fd["folded"] and abs(fd["stick"] - fd["head"]) < 2 and fd["r0"] > fd["head"] + 60 and fd["titleLines"] <= 2)
        pm.keyboard.press("Escape")
        pm.wait_for_timeout(600)
        y1 = pm.evaluate("scrollY")
        check(f"  {eng_name} телефон «{tab}»: после закрытия прокрутка на месте ({y0} → {y1}), фон разблокирован",
              abs(y1 - y0) < 2 and pm.evaluate("document.body.style.position") == "")
    pm.close()


# ── запуск ── (маркер: соседние тесты берут стенд выше этой строки через _pages_stand.fixture)
def run_all(eng_name, browser):
    # вьюер — на настоящих данных Synology: движки по очереди (SYNOLOGY_LOCK); чтобы не ждать друг друга,
    # Chromium начинает с вьюера, WebKit кончает им
    def viewer():
        with SYNOLOGY_LOCK:
            run_viewer(eng_name, browser)
    if eng_name == "chromium":
        viewer()
    run(eng_name, browser)
    run_food(eng_name, browser)
    if eng_name != "chromium":
        viewer()


per_engine(run_all)   # Chromium и WebKit — параллельно, браузер один на движок

print(f"select_layout: {check.passed} passed, {check.failed} failed")
sys.exit(1 if check.failed else 0)
