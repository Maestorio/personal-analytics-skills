#!/usr/bin/env python3
"""Вёрстка раздела «Еда» на телефоне — прогон настоящим браузером.

Четыре свойства, которые нельзя проверить чтением исходника, а сломать легко:

  1. Страница НЕ шире экрана. Длинный адрес в «Источниках» — единственный токен,
     который не переносится сам; он растягивал документ (замер 2026-08-02: 610 px
     при экране 390), а iOS в ответ сжимал страницу целиком — та самая белая
     полоса справа, которая держится до сведения пальцами, потому что раздел —
     одностраничное приложение и перезагрузки нет.
  2. Поля ввода на сенсорном экране ≥16px. Ниже — iOS Safari приближает страницу
     при фокусе и обратно НЕ отдаляет.
  3. Прокрутка внутри модалки переживает перерисовку. Живой случай: в
     «Запланировать» снимаешь галочку с ингредиента внизу — список прыгает
     к началу, и до следующего надо прокручивать заново.
  4. Арифметика степпера и пересчёта в модалке плана. Шаг «10% от текущего»
     на штуках доходил до 15 и дальше шагал по два: 15 → 17 → 19 → 21, и
     двадцать яиц не набирались в принципе (случай владельца 2026-08-15).
     Читая исходник, это не увидишь — нужен прогон последовательности целиком.
     Здесь же проверяется, что готовый вес крупы превращается в сухой ДО
     попадания в список покупок.

Данные синтетические (свой Food-каталог во временной папке) — тест не зависит от
Synology и от того, какие рецепты сегодня лежат у владельца.

Запуск:
    python3 tools/tests/test_food_layout.py
Требует playwright + установленный chromium; без них — честный пропуск.
"""
import json
import shutil
import sys
import tempfile
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, unquote, parse_qs

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
    print("food_layout: пропуск — нет playwright")
    sys.exit(0)

# ── синтетические данные ────────────────────────────────────────────────────
LONG_URL = ("ars.usda.gov/ARSUserFiles/80400535/Data/retn/"
            "USDA_CookingYields_MeatPoultry02.pdf")
PRODUCTS = {"schema": "food-products@1", "products": [
    {"id": "muka", "name": "Мука", "unit": "г", "category": "бакалея", "pack_size": 1000,
     "nutrition_100g": {"kcal": 334, "protein_g": 10.3, "fat_g": 1.1, "carb_g": 68.9}},
    {"id": "kefir", "name": "Кефир", "unit": "мл", "category": "молочное", "g_per_100ml": 102,
     "nutrition_100g": {"kcal": 57, "protein_g": 3, "fat_g": 3.2, "carb_g": 4}},
    # Штучный продукт — на нём проверяется шаг степпера, весовой с
    # развариванием — пересчёт готового веса в сухой (что и покупаем).
    {"id": "yaytsa", "name": "Яйца", "unit": "шт", "category": "молочное", "piece_g": 55,
     "nutrition_100g": {"kcal": 157, "protein_g": 12.7, "fat_g": 11.5, "carb_g": 0.7}},
    {"id": "grechka", "name": "Гречка", "unit": "г", "category": "бакалея", "cooked_ratio": 2.5,
     "nutrition_100g": {"kcal": 346, "protein_g": 11.7, "fat_g": 2.7, "carb_g": 75}},
]}
RECIPE = {"schema": "food-recipe@1", "id": "test", "title": "Тестовое блюдо",
          "servings": 4, "finished_g": 900,
          # Ингредиентов заведомо больше, чем влезает в модалку «Запланировать»:
          # иначе проверке прокрутки нечего проверять.
          "ingredients": (
              [{"name": "Мука", "product_id": "muka", "qty": 400, "unit": "г"},
               {"name": "Кефир", "product_id": "kefir", "qty": 500, "unit": "мл"}] +
              [{"name": f"Добавка {i}", "qty": 10 + i, "unit": "г"} for i in range(1, 11)]),
          "steps": [{"title": "Шаг 1. Замес (10 мин)", "text": "Смешать 400 г муки и 500 мл кефира."}],
          "sources": f"Выход и КБЖУ рассчитаны по коэффициентам USDA ({LONG_URL})."}
SHOPPING = {"schema": "food-shopping@1", "items": []}
# Второй рецепт — только ради сторожа массы: блюдо тяжелее сырых продуктов
# (400 г муки против 900 г «готового»), значит «на 100 г» считается от чужого
# знаменателя и об этом надо сказать вслух.
# Третий рецепт — БЕЗ измеренной массы. Это самый частый случай, и только на нём
# рисуется длинный чип «⚖ Взвесили готовое? Введите массу — покажу КБЖУ на 100 г»:
# 420 px в одну строку, то есть шире любого телефона. Пока фикстура была только
# с массой, чип в тест не попадал, и перелив жил незамеченным (2026-08-02).
RECIPE_NOMASS = {"schema": "food-recipe@1", "id": "nomass", "title": "Без измеренной массы",
                 "servings": 2,
                 "ingredients": [{"name": "Мука", "product_id": "muka", "qty": 300, "unit": "г"}],
                 "steps": [{"title": "Шаг 1. Смешать (5 мин)", "text": "Смешать 300 г муки."}]}
# Рецепт под модалку «Запланировать»: штуки (шаг степпера), крупа готовым весом
# с известным развариванием (195 г готовой → 78 г сухой) и она же без продукта в
# каталоге — там коэффициента нет, и делить наугад нельзя.
RECIPE_PLAN = {"schema": "food-recipe@1", "id": "plan", "title": "План и количества",
               "servings": 4,
               "ingredients": [
                   {"name": "Яйца", "product_id": "yaytsa", "qty": 4, "unit": "шт"},
                   {"name": "Гречка", "product_id": "grechka", "qty": 195, "unit": "г",
                    "state": "cooked"},
                   {"name": "Полба варёная", "qty": 300, "unit": "г", "state": "cooked"}],
               "steps": [{"title": "Шаг 1. Смешать (5 мин)", "text": "Смешать всё."}]}
RECIPE_HEAVY = {"schema": "food-recipe@1", "id": "heavy", "title": "Тяжелее продуктов",
                "servings": 2, "finished_g": 900,
                "ingredients": [{"name": "Мука", "product_id": "muka", "qty": 400, "unit": "г"}],
                "steps": [{"title": "Шаг 1. Смешать (5 мин)", "text": "Смешать 400 г муки."}]}


def make_food_root(d: Path):
    (d / "recipes").mkdir(parents=True)
    (d / "products.json").write_text(json.dumps(PRODUCTS, ensure_ascii=False), encoding="utf-8")
    (d / "shopping.json").write_text(json.dumps(SHOPPING, ensure_ascii=False), encoding="utf-8")
    (d / "recipes.json").write_text(json.dumps({"schema": "food-recipes@1", "recipes": []},
                                               ensure_ascii=False), encoding="utf-8")
    (d / "recipes" / "test.json").write_text(json.dumps(RECIPE, ensure_ascii=False), encoding="utf-8")
    (d / "recipes" / "heavy.json").write_text(json.dumps(RECIPE_HEAVY, ensure_ascii=False),
                                              encoding="utf-8")
    (d / "recipes" / "nomass.json").write_text(json.dumps(RECIPE_NOMASS, ensure_ascii=False),
                                               encoding="utf-8")
    (d / "recipes" / "plan.json").write_text(json.dumps(RECIPE_PLAN, ensure_ascii=False),
                                             encoding="utf-8")


def make_handler(food_root: Path):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body=b"", ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self):
            p = unquote(urlparse(self.path).path)
            # право на запись страница выводит из успеха /api/fd/file
            if p.startswith("/api/fd/file"):
                rel = parse_qs(urlparse(self.path).query).get("path", [""])[0]
                f = food_root / rel
                if not f.is_file():
                    return self._send(404)
                return self._send(200, json.dumps(
                    {"content": f.read_text(encoding="utf-8"), "hash": "x"}).encode())
            if p.startswith("/api/"):
                return self._send(200, json.dumps(
                    {"ok": True, "writable": True, "health_writable": False,
                     "health_files": [], "food_files": ["products", "recipes", "shopping"]}).encode())
            if p.startswith("/Food/"):
                f = food_root / p[len("/Food/"):]
            elif p.startswith("/tools/"):
                f = REPO / "tools" / p[len("/tools/"):]
            else:
                return self._send(404)
            if f.is_dir():   # зеркало листинга Caddy (file_server browse)
                return self._send(200, json.dumps(
                    [{"name": c.name, "is_dir": c.is_dir()} for c in sorted(f.iterdir())]).encode())
            if not f.is_file():
                return self._send(404)
            ctype = {".html": "text/html; charset=utf-8", ".json": "application/json",
                     ".css": "text/css", ".js": "application/javascript",
                     ".woff2": "font/woff2"}.get(f.suffix, "application/octet-stream")
            return self._send(200, f.read_bytes(), ctype)
    return H


def goto(pg, url, settle_ms, ready=None):
    """Загрузка страницы без гонки: ждём конец сетевых запросов (данные
    рецепта приходят fetch'ем) и, если задан, элемент `ready` — признак, что
    экран дорисован; потом короткая пауза. Одна фиксированная пауза падала
    под нагрузкой: «чип на месте» не успевал появиться при параллельном
    прогоне тестов (2026-09-30). Не дождались `ready` — не падаем здесь:
    следующая проверка честно покажет пустой экран."""
    pg.goto(url)
    pg.wait_for_load_state("networkidle")
    if ready:
        try:
            pg.wait_for_selector(ready, timeout=15000)
        except Exception:
            pass
    pg.wait_for_timeout(settle_ms)

def main():
    tmp = Path(tempfile.mkdtemp())
    try:
        food = tmp / "Food"
        make_food_root(food)
        # _pages_stand: очередь 128 (у ThreadingHTTPServer по умолчанию 5 — под параллельным прогоном
        # сервер сбрасывал соединения, рецепт не грузился) и keep-alive
        srv = serve(make_handler(food))[0]
        port = srv.server_address[1]
        base = f"http://127.0.0.1:{port}/tools/food.html"

        with sync_playwright() as pw:
            try:
                br = pw.chromium.launch()
            except Exception as e:
                print(f"food_layout: пропуск — chromium не запускается ({str(e)[:60]})")
                return 0
            # ── 1. ширина документа на четырёх телефонах ──
            for w in (320, 375, 390, 430):
                pg = br.new_page(viewport={"width": w, "height": 800},
                                 is_mobile=True, has_touch=True)
                goto(pg, base + "?recipe=test", 900, ready=".sc-read")
                over = pg.evaluate("document.documentElement.scrollWidth - "
                                   "document.documentElement.clientWidth")
                check(f"{w}px: документ не шире экрана (длинный URL в источниках)", over <= 1)
                # Рецепт без измеренной массы: там длинный чип «Взвесили готовое?»
                goto(pg, base + "?recipe=nomass", 700, ready="[data-act=weigh-open]")
                check(f"{w}px: документ не шире экрана (длинный чип «Взвесили готовое?»)",
                      pg.evaluate("document.documentElement.scrollWidth - "
                                  "document.documentElement.clientWidth") <= 1)
                check(f"{w}px: чип на месте (проверка не на пустом экране)",
                      pg.locator("[data-act=weigh-open]").count() > 0)
                goto(pg, base + "?recipe=test", 700)
                if w == 390:
                    # ссылка стала ссылкой, показ короткий, адрес целый
                    a = pg.query_selector(".sc-read a[target=_blank]")
                    check("адрес в источниках стал ссылкой", a is not None)
                    if a:
                        check("показ сокращён", len(a.inner_text()) < len(LONG_URL))
                        check("в href — полный адрес",
                              (a.get_attribute("href") or "").endswith(LONG_URL))
                        check("полный адрес доступен в title",
                              (a.get_attribute("title") or "").endswith(LONG_URL))
                    # ── 2. поля ввода на сенсорном экране ──
                    check("эмуляция телефона: pointer:coarse",
                          pg.evaluate("matchMedia('(hover:none) and (pointer:coarse)').matches"))
                    # Поля живут не на карточке рецепта, а на экранах поиска и
                    # правки — там их и меряем (иначе список пуст и проверка
                    # молча проходит ни на чём).
                    probe = ("Array.from(document.querySelectorAll("
                             "'input:not([type=checkbox]):not([type=radio]):not([type=hidden]),textarea'))"
                             ".map(e => parseFloat(getComputedStyle(e).fontSize))")
                    pg.evaluate("document.querySelector('[data-act=edit-recipe]').click()")
                    pg.wait_for_timeout(500)
                    ed = pg.evaluate(probe)
                    check("экран правки: поля найдены", len(ed) >= 5)
                    check("экран правки: все поля ≥16px (иначе iOS зумит и не возвращает)",
                          bool(ed) and min(ed) >= 16)
                    check("экран правки: документ не шире экрана",
                          pg.evaluate("document.documentElement.scrollWidth - "
                                      "document.documentElement.clientWidth") <= 1)
                    # Каталог продуктов — там всегда есть поиск (список покупок
                    # в фикстуре пуст, полей на нём нет вовсе).
                    goto(pg, base, 700)
                    pg.evaluate("""() => {
                      const b = Array.from(document.querySelectorAll('.ui-mnav-btn'))
                        .find(x => /Продукты/.test(x.textContent));
                      if (b) b.click(); }""")
                    pg.wait_for_timeout(400)
                    sizes = pg.evaluate(probe)
                    check("каталог продуктов: поле поиска найдено", len(sizes) >= 1)
                    check("каталог продуктов: все поля ≥16px",
                          bool(sizes) and min(sizes) >= 16)
                    # печать длинного адреса тоже не рвёт лист
                    goto(pg, base + "?recipe=test&print=1", 700)
                    check("печатный вид: документ не шире экрана",
                          pg.evaluate("document.documentElement.scrollWidth - "
                                      "document.documentElement.clientWidth") <= 1)
                pg.close()

            # ── 2.5. сторож массы готового блюда ──
            pg = br.new_page(viewport={"width": 390, "height": 800},
                             is_mobile=True, has_touch=True)
            goto(pg, base + "?recipe=heavy", 900)
            txt = pg.evaluate("document.querySelector('.sc-read').innerText")
            check("блюдо тяжелее продуктов → сказано вслух",
                  "тяжелее продуктов" in txt)
            check("сказано, НА СКОЛЬКО тяжелее", "500 г" in txt)
            goto(pg, base + "?recipe=test", 900)
            check("нормальное блюдо сторож не трогает",
                  "тяжелее продуктов" not in pg.evaluate(
                      "document.querySelector('.sc-read').innerText"))
            pg.close()

            # ── 2.9. нажатие пункта меню/рельса — к верху, даже на текущей вкладке ──
            for w, sel in ((390, ".ui-mnav"), (1400, ".ui-rail")):
                pg = br.new_page(viewport={"width": w, "height": 800},
                                 is_mobile=(w == 390), has_touch=(w == 390))
                goto(pg, base, 900)
                pg.evaluate("document.body.style.minHeight = '4000px'")
                items = pg.evaluate("document.querySelectorAll('%s [data-act=nav]').length" % sel)
                check(f"{w}px: в {sel} есть пункты", items >= 2)
                if items >= 2:
                    for which, label in ((".active, [aria-current]", "текущей"), (None, "другой")):
                        pg.evaluate("window.scrollTo(0, 600)")
                        pg.wait_for_timeout(100)
                        check(f"{w}px: прокручено вниз", pg.evaluate("window.scrollY") > 0)
                        pg.evaluate("""([sel, cur]) => {
                          const all = [...document.querySelectorAll(sel + ' [data-act=nav]')];
                          const c = cur ? all.find(e => e.matches('.active,[aria-current]')) : null;
                          const t = cur ? (c || all[0]) : all.find(e => e !== (all.find(x => x.matches('.active,[aria-current]')) || all[0]));
                          t.click(); }""", [sel, which is not None])
                        pg.wait_for_timeout(300)
                        check(f"{w}px: нажатие на пункт {label} вкладки → scrollY == 0",
                              pg.evaluate("window.scrollY") == 0)
                pg.close()

            # ── 3. прокрутка внутри модалки переживает перерисовку ──
            pg = br.new_page(viewport={"width": 390, "height": 620},
                             is_mobile=True, has_touch=True)
            goto(pg, base + "?recipe=test", 900)
            opened = pg.evaluate("""() => {
              const b = document.querySelector('[data-act=plan-open]');
              if (!b) return false; b.click(); return true; }""")
            check("модалка «Запланировать» открылась", opened)
            if opened:
                pg.wait_for_timeout(400)
                pg.evaluate("document.querySelector('.ui-modal-body').scrollTop = 99999")
                pg.wait_for_timeout(150)
                before = pg.evaluate("document.querySelector('.ui-modal-body').scrollTop")
                check("список длиннее модалки (иначе тест ничего не проверяет)", before > 0)
                pg.evaluate("""() => {
                  const c = document.querySelectorAll('[data-act=plan-check]');
                  c[c.length - 1].click(); }""")
                pg.wait_for_timeout(300)
                after = pg.evaluate("document.querySelector('.ui-modal-body').scrollTop")
                check("галочка не отматывает список к началу", abs(after - before) <= 2)
                pg.evaluate("""() => {
                  const a = document.querySelectorAll('[data-act=plan-amt]');
                  if (a.length) a[a.length - 1].click(); }""")
                pg.wait_for_timeout(300)
                check("правка количества тоже не отматывает",
                      abs(pg.evaluate("document.querySelector('.ui-modal-body').scrollTop") - before) <= 2)
                # а вот ПЕРЕОТКРЫТИЕ обязано показать начало списка
                pg.evaluate("document.querySelector('.ui-modal-x').click()")
                pg.wait_for_timeout(250)
                pg.evaluate("document.querySelector('[data-act=plan-open]').click()")
                pg.wait_for_timeout(400)
                check("переоткрытая модалка — с начала",
                      pg.evaluate("document.querySelector('.ui-modal-body').scrollTop") == 0)
            pg.close()

            # ── 4. арифметика модалки «Запланировать» ──
            # Кнопка после каждого нажатия пересоздаётся (patchPlan переписывает
            # тело модалки), поэтому ищем её заново на каждом шаге — иначе клики
            # уходили бы в открепившийся от документа узел.
            js_plus = """(name) => {
              const find = () => Array.from(document.querySelectorAll('[data-act=plan-amt]'))
                .find(b => b.getAttribute('data-arg').endsWith(':+')
                        && b.parentElement.parentElement.parentElement.innerText.includes(name));
              const b = find();
              if (!b) return null;
              b.click();
              const a = find();
              return a ? a.parentElement.querySelector('span.num').innerText.trim() : null;
            }"""
            js_val = """(name) => {
              const b = Array.from(document.querySelectorAll('[data-act=plan-amt]'))
                .find(x => x.getAttribute('data-arg').endsWith(':+')
                        && x.parentElement.parentElement.parentElement.innerText.includes(name));
              return b ? b.parentElement.querySelector('span.num').innerText.trim() : null;
            }"""
            pg = br.new_page(viewport={"width": 390, "height": 800},
                             is_mobile=True, has_touch=True)
            goto(pg, base + "?recipe=plan", 900)
            opened = pg.evaluate("""() => {
              const b = document.querySelector('[data-act=plan-open]');
              if (!b) return false; b.click(); return true; }""")
            check("модалка плана открылась (рецепт с количествами)", opened)
            if opened:
                pg.wait_for_timeout(400)
                check("яйца пришли в план рецептурным количеством",
                      pg.evaluate(js_val, "Яйца") == "4 шт")
                seq = [pg.evaluate(js_plus, "Яйца") for _ in range(16)]
                # Главное свойство: КАЖДОЕ целое достижимо. Проверяем всю
                # последовательность, а не только конец: прежний шаг «10%»
                # давал 15 → 17 → 19 и мимо двадцати.
                check("шаг штук — ровно по одной, все числа достижимы",
                      seq == [f"{n} шт" for n in range(5, 21)])
                check("двадцать яиц набираются кнопкой", seq[-1] == "20 шт")
                # Готовый вес крупы → сухой: покупаем то, что кладём в корзину.
                # 195 г из рецепта на порциях 1:1 округляются до 200 (кухонная
                # точность roundQty), делятся на 2,5 и снова округляются: 80 г.
                check("готовый вес пересчитан в сухой (200 / 2,5)",
                      pg.evaluate(js_val, "Гречка") == "80 г")
                body = pg.evaluate("document.getElementById('plan-body').innerText")
                check("сказано, откуда взялось число", "200 г готовой" in body)
                # Без коэффициента делить наугад нельзя — берём как есть и
                # помечаем строку, чтобы человек проверил.
                check("готовый вес без разваривания не делится втихую",
                      pg.evaluate(js_val, "Полба") == "300 г")
                check("строка без разваривания помечена", "разваривание" in body)
                # Правка руками снимает подпись про пересчёт: она объясняла
                # ИСХОДНОЕ число, а не то, что человек набрал сам.
                pg.evaluate(js_plus, "Гречка")
                pg.wait_for_timeout(150)
                check("после правки руками подпись про пересчёт снимается",
                      "200 г готовой" not in pg.evaluate(
                          "document.getElementById('plan-body').innerText"))
            pg.close()

            # ── крестик очистки поиска (ui-kit 1.5.0) ──
            # Клик по ✕: поле пустое, фильтр снят (обработчик ввода страницы
            # отработал на синтетический «input»); ui-kit 1.50.0 — курсор в поле не ставится
            # (крестик — «убрать поиск», на телефоне не всплывает клавиатура).
            pg = br.new_page(viewport={"width": 1280, "height": 900})
            goto(pg, base, 900)
            for scr, fid in (("recipes", "f-rec-q"), ("products", "f-prod-q")):
                pg.locator(f'[data-act="nav"][data-arg="{scr}"]:visible').first.click()
                pg.wait_for_timeout(300)
                x = pg.locator(f'[data-ui-search-x="{fid}"]')
                check(f"{fid}: у пустого поиска крестика не видно", not x.is_visible())
                pg.fill(f"#{fid}", "zzz-нет-такого")
                pg.wait_for_timeout(200)
                check(f"{fid}: с текстом крестик виден", x.is_visible())
                x.click()
                pg.wait_for_timeout(200)
                check(f"{fid}: крестик очищает поле", pg.input_value(f"#{fid}") == "")
                check(f"{fid}: после очистки курсора в поле нет",
                      pg.evaluate("document.activeElement && document.activeElement.id") != fid)
                check(f"{fid}: после очистки крестик снова скрыт", not x.is_visible())
                # ui-kit 1.50.1: Enter в поле поиска — выйти из поля (на телефоне прячется клавиатура)
                pg.fill(f"#{fid}", "zzz")
                pg.press(f"#{fid}", "Enter")
                pg.wait_for_timeout(150)
                check(f"{fid}: Enter убирает курсор из поиска, текст остаётся",
                      pg.evaluate("document.activeElement && document.activeElement.id") != fid
                      and pg.input_value(f"#{fid}") == "zzz")
                x.click()
                pg.wait_for_timeout(200)
            q_state = pg.evaluate("document.body.innerText.indexOf('zzz-нет-такого') < 0")
            check("после очистки строка запроса нигде не осталась", q_state)
            pg.close()

            # ── окна стопкой (ui-kit 1.36.0, 2026-10-07) ──
            # «Править» из карточки и «Завести продукт» из подбора открывают форму
            # ПОВЕРХ (нижнее окно — .behind), «Отмена»/Escape закрывают только
            # верхнее и возвращают к нижнему; одиночное окно въезжает (.enter).
            js_mods = "[...document.querySelectorAll('.ui-modal')].map(m => m.className)"
            pg = br.new_page(viewport={"width": 1280, "height": 900})
            goto(pg, base, 900)
            pg.locator('[data-act="nav"][data-arg="products"]:visible').first.click()
            pg.wait_for_timeout(300)
            pg.locator('[data-act="prod-card"]').first.click()
            pg.wait_for_timeout(300)
            m = pg.evaluate(js_mods)
            check(f"карточка продукта — одно окно, въезжает ({m})", len(m) == 1 and "enter" in m[0])
            pg.click('.ui-modal [data-act="prod-card-edit"]')
            pg.wait_for_timeout(300)
            m = pg.evaluate(js_mods)
            check(f"«Править» — форма поверх карточки ({m})",
                  len(m) == 2 and "behind" in m[0] and "enter" in m[1] and "stacked" in m[1])
            pg.locator(".ui-modal").nth(1).locator(".ui-modal-cancel").click()
            pg.wait_for_timeout(450)
            m = pg.evaluate(js_mods)
            check(f"«Отмена» — назад к карточке ({m})", len(m) == 1 and "behind" not in m[0]
                  and pg.locator('.ui-modal [data-act="prod-card-edit"]').count() == 1)
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(450)
            check("Escape закрывает карточку", pg.evaluate(js_mods) == [])
            goto(pg, base + "?recipe=test", 900, ready=".sc-read")
            pg.locator('[data-act="ing-link"]').first.click()
            pg.wait_for_timeout(300)
            pg.click('.ui-modal [data-act="ing-link-new"]')
            pg.wait_for_timeout(300)
            m = pg.evaluate(js_mods)
            check(f"«Завести продукт» — форма поверх подбора ({m})", len(m) == 2 and "behind" in m[0])
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(450)
            check("Escape — назад к подбору",
                  len(pg.evaluate(js_mods)) == 1 and pg.locator('.ui-modal [data-act="ing-link-new"]').count() == 1)
            pg.close()

            # ── тёмная тема: текст модалок читается ──
            # Модалки рендерятся соседями обёртки-темы и наследуют цвет от body.
            # Без color на body они получали чёрный по умолчанию — чёрный текст
            # на тёмной модалке (случай 2026-10-02, «Добавить в список»).
            # Контраст ≥ 4.5 — порог WCAG AA для обычного текста.
            js_contrast = """sel => {
              const el = document.querySelector(sel); if (!el) return null;
              const rgb = s => s.match(/[\\d.]+/g).map(Number);
              const lum = c => { const a = c.slice(0,3).map(v => { v /= 255;
                return v <= .03928 ? v/12.92 : Math.pow((v+.055)/1.055, 2.4); });
                return .2126*a[0] + .7152*a[1] + .0722*a[2]; };
              let b = el, bg;
              while (b) { const c = rgb(getComputedStyle(b).backgroundColor);
                if (c.length < 4 || c[3] > .5) { bg = c; break; } b = b.parentElement; }
              const L1 = lum(rgb(getComputedStyle(el).color)), L2 = lum(bg || [255,255,255]);
              return (Math.max(L1,L2) + .05) / (Math.min(L1,L2) + .05);
            }"""
            ctx = br.new_context(viewport={"width": 390, "height": 800})
            ctx.add_init_script("try{localStorage.setItem('hub-theme','dark')}catch(e){}")
            pg = ctx.new_page()
            goto(pg, base, 900)
            pg.locator('[data-act="nav"][data-arg="shopping"]:visible').first.click()
            pg.wait_for_timeout(300)
            pg.locator('[data-act="add-open"]:visible').first.click()
            pg.wait_for_timeout(300)
            pg.locator(".ui-modal input").first.type("Ке")
            pg.wait_for_timeout(300)
            cr_title = pg.evaluate(js_contrast, ".ui-modal-title")
            cr_sug = pg.evaluate(js_contrast, ".ui-modal .sug-row span")
            check(f"тёмная тема: заголовок модалки читается (контраст {cr_title and round(cr_title, 2)})",
                  cr_title is not None and cr_title >= 4.5)
            check(f"тёмная тема: подсказка каталога читается (контраст {cr_sug and round(cr_sug, 2)})",
                  cr_sug is not None and cr_sug >= 4.5)
            ctx.close()
            br.close()
        srv.shutdown()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nfood_layout: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
