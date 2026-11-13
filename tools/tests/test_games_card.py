#!/usr/bin/env python3
"""Карточка игры и оверлей Gaming/user-state.json на games.html v2.7.0 — прогон настоящим браузером (playwright, Chromium).

Страница читает слои советника (taste-profile, library_full, watchlist) и поверх них оверлей владельца
`Gaming/user-state.json` (`gaming-user@1`), правки пишет через POST /api/gm/save с base_hash. Стенд — статика tools/
и поддельные /api/gm/file|save, /api/games/nsuid-lookup (тело каждого POST запоминается и сверяется). 1280 и 390 px:

  1. Слияние: игра оверлея с state «играю» остаётся в библиотеке с отметкой «правка с сайта» и миниатюрой обложки;
     deleted скрыта; игра watchlist со state «не-интересно» уходит в слот «Не интересно».
  2. Карточка открывается с «Библиотеки» и «Присматриваюсь» — мышью и Enter; Esc закрывает, фокус возвращается.
  3. Смена состояния → один POST: path, base_hash прежний, content = gaming-user@1 (updated, items[] с полями
     карточки), state/rating/platform — из кодлистов game_state/game_rating/game_platform.
  4. 409 → страница перечитывает файл и повторяет с новым hash; 400 → текст валидатора виден, окно открыто;
     404 оверлея → первый POST с base_hash null.
  5. «Добавить игру»: пустое название — ошибка; новая запись; дубль по названию открывает существующую.
     «Найти в US eShop» заполняет nsuid/ссылку/обложку; 404 — сообщение.
  6. Оценка и платформа — uiSelect (скрытое поле .value); порог цены — целые доллары; у купленных/играю/пройдена/
     брошена пороги disabled (переключение чипа без перерисовки) и пишутся null; поле «Наиграно, ч» (подсказка из
     библиотеки, в оверлей не копируется); часы оверлея главнее; игра без часов не прячется фильтром ≥1ч/≥5ч;
     купленная игра из watchlist попадает в библиотеку.
  7. eShop: ссылка «Страница в US eShop ↗» и подпись nsuid, не поля; после 404 — поле адреса и «Найти по адресу».
  8. «Подобрать обложки и nsuid» (поддельный /api/games/nsuid-fill): одно сохранение, ничего не затирает.
  9. Фильтр по платформе и сортировка (uiSelect: часы / имя / дата) в библиотеке; на «Присматриваюсь» — платформа и
     имя; выбор помнится в localStorage.
 10. На 390 px страница не шире экрана; ошибок JS нет.
 11. Три оси (v2.7.0): статус из 5 · прохождение (только у куплена/демо) · оценка из 4; legacy-запись нормализуется при чтении и уходит
     в новом виде; библиотека по умолчанию — все купленные; фильтры «Прохождение»/«Оценка» в обеих вкладках; демо + не понравилось находится.
Данные синтетические, во временной папке. Без playwright или chromium — пропуск.
Запуск: python3 tools/tests/test_games_card.py
"""
import re
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import Checker, Quiet, per_engine, serve  # noqa: E402

try:
    import playwright.sync_api  # noqa: F401
except ImportError:
    print("games_card: пропуск — нет playwright")
    sys.exit(0)

check = Checker()
CODES = json.loads((REPO / "_shared-references/codelists.json").read_text(encoding="utf-8"))["lists"]
STATES = [c for c, e in CODES["game_state"].items() if not e.get("legacy")]   # 4 живых: хочу, на-карандаш, не-интересно, куплена («демо» — флаг demo, не статус)
RATINGS = [c for c, e in CODES["game_rating"].items() if not e.get("legacy")]
PROGS = list(CODES["game_progress"])
PLATS = list(CODES["game_platform"])
COVER = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c63"
                      "60f8cfc0f01f0005000201a5f645400000000049454e44ae426082")

TASTE = """updated: 2026-10-01
platforms: {primary: switch2, secondary: steam_deck}
library:
  - {title: "Hades", verdict: восторг, platform: switch, hours: 40}
  - {title: "Celeste", verdict: понравилось, platform: switch, hours: 12}
  - {title: "Inside", verdict: нормально, platform: switch, hours: 8}
mood_clusters: {}
anti_patterns: []
"""
LIBFULL = """library_full:
  - {title: "Hades", platform: switch, hours: 40}
  - {title: "Celeste", platform: switch, hours: 12}
  - {title: "Inside", platform: switch, hours: 8}
  - {title: "Portal", platform: steam_deck, hours: 3}
  - {title: "Tetris", platform: switch_2}
"""
WATCH = """schema_version: 1.0
updated: 2026-10-21
items:
  - title: "Undertale"
    condition: "сначала демо; брать со скидкой"
    status: хочу
    platform: switch
    nsuid_us: "70010000009921"
    added: 2026-10-20
  - title: "Metaphor"
    status: на-карандаш
    added: 2026-10-19
  - title: "Alan Wake"
    store_title: "Alan Wake Remastered"
    status: хочу
    platform: pc
    added: 2026-10-17
  - title: "Fire Emblem"
    status: хочу
    platform: switch2
    added: 2026-10-18
"""
PRICES = {"schema": "eshop-prices@1", "fetched_at": "2099-01-01T08:30:00+03:00", "status": "ok", "items": [
    {"title": "Undertale", "nsuid_us": "70010000009921", "sales_status": "onsale", "regular_usd": 14.99,
     "sale_usd": 9.89, "discount_pct": 34, "price_usd": 9.89, "target_met": False}]}
DOC = {"schema": "gaming-user@1", "updated": "2026-11-01", "items": [
    {"title": "Hades", "platform": "switch", "state": "играю", "rating": None, "note": "в процессе", "store_title": "Hades: Definitive Edition",
     "cover_url": "https://img.test/h.png", "deleted": False, "updated": "2026-11-01", "added": "2026-11-01"},
    {"title": "Metaphor", "platform": None, "state": "не-интересно", "rating": None, "note": None,
     "deleted": False, "updated": "2026-11-01", "added": "2026-11-01"},
    {"title": "Inside", "platform": "switch", "state": "куплена", "rating": None, "note": None,
     "deleted": True, "updated": "2026-11-01", "added": "2026-11-01"},
    {"title": "Fire Emblem", "platform": "switch2", "state": "куплена", "rating": None, "note": None,
     "deleted": False, "updated": "2026-11-02", "added": "2026-11-02"}]}
LOOKUP = {"nsuid_us": "70010000111111", "store_title": "Stardew Valley", "platform": "switch",
          "eshop_url": "https://www.nintendo.com/us/store/products/stardew-valley-switch/",
          "cover_url": "https://img.test/c.png"}
LOOKUP_STEAM = {"store": "steam", "steam_appid": "1145360", "store_title": "Hades", "platform": "steam_deck",
                "store_url": "https://store.steampowered.com/app/1145360/",
                "cover_url": "https://cdn.cloudflare.steamstatic.com/steam/apps/1145360/library_600x900.jpg",
                "cover_fallback_url": "https://cdn.cloudflare.steamstatic.com/steam/apps/1145360/header.jpg"}
DOC_STEAM_ITEM = {"title": "Hollow Knight", "platform": "steam_deck", "state": "хочу", "rating": None, "note": None,
                  "steam_appid": "367520", "store_title": "Hollow Knight: Silksong", "hours": 3, "deleted": False, "updated": "2026-11-03", "added": "2026-11-03"}
LOOKUP_BODIES = []
FILL = {"results": [], "done": True, "code": 200, "bodies": []}
ST = {"doc": None, "hash": "h1", "posts": [], "mode": "ok", "lookup": 200, "steam": False}


class H(Quiet):
    def _j(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/gm/file"):
            if ST["doc"] is None:
                return self._j(404, {"error": "нет файла"})
            return self._j(200, {"path": "Gaming/user-state.json", "hash": ST["hash"], "content": json.dumps(ST["doc"])})
        return super().do_GET()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path.startswith("/api/gm/save"):
            ST["posts"].append(body)
            if ST["mode"] == "409":
                ST["mode"], ST["hash"] = "ok", "h-race"
                return self._j(409, {"error": "conflict"})
            if ST["mode"] == "400":
                return self._j(400, {"error": "items[0].note: длиннее 500 знаков"})
            ST["doc"] = json.loads(body["content"])
            ST["hash"] = "h%d" % (len(ST["posts"]) + 1)
            return self._j(200, {"hash": ST["hash"]})
        if self.path.startswith("/api/games/nsuid-lookup"):
            LOOKUP_BODIES.append(body)
            return self._j(200, LOOKUP_STEAM if ST["steam"] else LOOKUP) if ST["lookup"] == 200 else self._j(404, {"error": "not found"})
        if self.path.startswith("/api/games/nsuid-fill"):
            FILL["bodies"].append(body)
            if FILL["code"] != 200:
                return self._j(FILL["code"], {"error": "x"})
            return self._j(200, {"results": FILL["results"], "done": FILL["done"]})
        return self._j(404, {})


def reset(doc, mode="ok"):
    ST.update(doc=copy.deepcopy(doc), hash="h1", mode=mode, lookup=200, steam=False)
    FILL.update(results=[], done=True, code=200, bodies=[])
    ST["posts"].clear()


def last_doc():
    return json.loads(ST["posts"][-1]["content"])


def gone(page):
    page.wait_for_function("!document.getElementById('gm-card')", timeout=5000)


def titles(page, sel):
    return [e.inner_text() for e in page.query_selector_all(sel)]


def opened(page, name):
    page.wait_for_selector("#gm-card .ui-modal-box", timeout=5000)
    return page.inner_text("#gm-card .ui-modal-title") == name


FILT = ('#gfilters', '#vfilters', '#pfilters', '#wfilters', '#wpfilters', '[data-ui-select="gm-lib-sort"]', '[data-ui-select="gm-w-sort"]')


def fc(page, sel):
    """Клик по чипу/сортировке фильтров: >600 px они в потоке над сеткой — просто клик; ≤600 px — в шторке «Фильтры»: открыть, кликнуть, закрыть «Готово»."""
    if page.viewport_size["width"] > 600:
        page.click(sel)
        return
    btn = "#w-fbtn" if sel.startswith(('#wf', '#wr', '#wp', '#w-demo-chip', '#w-sale-chip', '[data-ui-select="gm-w-sort"]')) else "#lib-fbtn"
    fresh = page.query_selector("#gm-fwin") is None
    if fresh:
        page.click(btn)
        page.wait_for_selector("#gm-fwin .ui-modal-box")
    page.click(sel)
    if not sel.endswith(".ui-select-btn"):
        page.click('#gm-fwin .ui-modal-save')
        page.wait_for_function("!document.getElementById('gm-fwin')", timeout=5000)


def scenario(br, base, W, hgt):
    n = f"{W}px"
    ctx = br.new_context(viewport={"width": W, "height": hgt})
    ctx.route("https://img.test/*", lambda r: r.fulfill(status=200, content_type="image/png", body=COVER))
    ctx.route("https://img.test/bad*", lambda r: r.fulfill(status=404, body=b""))
    ctx.route("https://cdn.cloudflare.steamstatic.com/**", lambda r: r.fulfill(
        status=404 if "library_600x900" in r.request.url else 200, content_type="image/jpeg", body=b"" if "library_600x900" in r.request.url else COVER))
    errs = []

    def load(screen, doc=DOC, c=None):
        reset(doc) if doc is not None else (ST.update(doc=None, hash="h1", mode="ok", lookup=200), ST["posts"].clear())
        pg = (c or ctx).new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
        pg.add_init_script(f"sessionStorage.setItem('games-screen','{screen}')")
        pg.goto(base + "/tools/games.html")
        pg.wait_for_function("document.querySelectorAll('.sc-%s .gcard').length >= 1" % screen, timeout=15000)
        pg.wait_for_timeout(150)
        return pg

    # ── библиотека: слияние, миниатюра, открытие мышью/Enter, Esc и фокус
    pg = load("library")
    t = titles(pg, "#lib-grid .gcard .gt")
    check(f"{n} слияние: Hades (legacy играю) остался в библиотеке", any("Hades" in x for x in t))
    check(f"{n} слияние: deleted Inside скрыта", not any("Inside" in x for x in t))
    check(f"{n} отметка «правка с сайта» у Hades", "с сайта" in pg.inner_text('#lib-grid .gcard[data-k="hades"]'))
    check(f"{n} у Celeste (без правок) отметки нет", "с сайта" not in pg.inner_text('#lib-grid .gcard[data-k="celeste"]'))
    check(f"{n} миниатюра обложки у игры с cover_url", pg.query_selector('#lib-grid .gcard[data-k="hades"] .gthumb img') is not None)
    check(f"{n} без cover_url — заглушка с буквой, без картинки", pg.query_selector('#lib-grid .gcard[data-k="celeste"] .gthumb img') is None
          and pg.inner_text('#lib-grid .gcard[data-k="celeste"] .gthumb .gph').strip().upper() == "C")
    pg.click('#lib-grid .gcard[data-k="celeste"]')
    check(f"{n} карточка с библиотеки (мышь)", opened(pg, "Celeste"))
    pg.keyboard.press("Escape")
    gone(pg)
    check(f"{n} Esc закрывает карточку", pg.query_selector("#gm-card") is None)
    check(f"{n} после мыши+Esc фокус на карточку не возвращается, рамки :focus-visible нет",
          pg.evaluate("document.activeElement.classList.contains('gcard')") is False
          and pg.evaluate("document.querySelector('.gcard:focus-visible')") is None)
    pg.focus('#lib-grid .gcard[data-k="hades"]')
    pg.keyboard.press("Enter")
    check(f"{n} карточка с библиотеки (Enter)", opened(pg, "Hades"))
    check(f"{n} у игры советника поля «Название» нет, имя в шапке с подсказкой про ключ",
          pg.query_selector("#gm-title") is None and "ключ к файлам советника" in pg.inner_text("#gm-card .ui-modal-sub"))
    check(f"{n} legacy state «играю» из оверлея прочитан как статус «куплена» + прохождение «играю»",
          pg.get_attribute('#gm-own .gm-opt[data-v="куплена"]', "aria-pressed") == "true" and pg.input_value("#gm-progress") == "играю")
    check(f"{n} кнопки «Статус»: слева «демо» · «куплена», справа остальные живые коды game_state (хочу · на карандаше · не хочу)",
          [e.get_attribute("data-v") for e in pg.query_selector_all("#gm-own .gm-opt")] == ["демо", "куплена"]
          and [e.get_attribute("data-v") for e in pg.query_selector_all("#gm-state .gm-opt")] == [c for c in STATES if c != "куплена"]
          and "статус" in pg.inner_text("#gm-card").lower())
    check(f"{n} у «куплена» правая группа статуса неактивна (disabled, приглушена), ничего в ней не выбрано",
          all(e.is_disabled() for e in pg.query_selector_all("#gm-state .gm-opt"))
          and not pg.query_selector_all('#gm-state .gm-opt[aria-pressed="true"]') and "off" in (pg.get_attribute("#gm-state", "class") or ""))
    check(f"{n} «Прохождение» — uiSelect по кодлисту game_progress",
          [e.get_attribute("data-value") for e in pg.query_selector_all('[data-ui-select="gm-progress"] .ui-opt')] == PROGS
          and pg.query_selector("select#gm-progress") is None)
    check(f"{n} оценка — uiSelect: «без оценки» первым, далее кодлист game_rating",
          [e.get_attribute("data-value") for e in pg.query_selector_all('[data-ui-select="gm-rating"] .ui-opt')] == [""] + RATINGS
          and pg.query_selector('#gm-rating[type="hidden"]') is not None and pg.query_selector("select#gm-rating") is None)
    check(f"{n} платформа — uiSelect по кодлисту game_platform, не нативный <select>",
          [e.get_attribute("data-value") for e in pg.query_selector_all('[data-ui-select="gm-plat"] .ui-opt')] == [""] + PLATS
          and pg.input_value("#gm-plat") == "switch" and pg.query_selector("select#gm-plat") is None)
    check(f"{n} у «играю» полей порогов в DOM нет, «Наиграно» видно",
          pg.query_selector("#gm-price") is None and pg.query_selector("#gm-disc") is None
          and pg.is_visible("#gm-hours") and "из библиотеки: 40 ч" in pg.inner_text("#gm-hours-host") and pg.input_value("#gm-hours") == "")

    # ── смена состояния → POST по схеме
    pg.click('[data-ui-select="gm-progress"] .ui-select-btn')
    pg.click('[data-ui-select="gm-progress"] .ui-opt[data-value="пройдена"]')
    pg.click('[data-ui-select="gm-rating"] .ui-select-btn')
    pg.click('[data-ui-select="gm-rating"] .ui-opt[data-value="восторг"]')
    check(f"{n} выбор оценки пишет значение в скрытое поле", pg.input_value("#gm-rating") == "восторг")
    pg.fill("#gm-hours", "42.5")
    pg.fill("#gm-note", "прошёл за выходные")
    pg.click('#gm-card [data-act="gm-save"]')
    gone(pg)
    p = ST["posts"][-1]
    d = last_doc()
    hd = [i for i in d["items"] if i["title"] == "Hades"][0]
    check(f"{n} POST: path и прежний base_hash", p["path"] == "Gaming/user-state.json" and p["base_hash"] == "h1")
    check(f"{n} POST: schema gaming-user@1, updated, items[]", d["schema"] == "gaming-user@1" and d["updated"] and len(d["items"]) == 4)
    check(f"{n} POST: поля записи Hades", hd["state"] == "куплена" and hd["progress"] == "пройдена" and hd["rating"] == "восторг" and hd["note"] == "прошёл за выходные"
          and hd["hours"] == 42.5 and hd["price_target_usd"] is None and hd["discount_target_pct"] is None
          and hd["platform"] == "switch" and hd["deleted"] is False and hd["added"] == "2026-11-01" and hd["updated"] != "2026-11-01")
    check(f"{n} POST: у записи все поля карточки", all(k in hd for k in (
        "title", "platform", "state", "rating", "progress", "note", "hours", "price_target_usd", "discount_target_pct", "nsuid_us",
        "eshop_url", "cover_url", "store_title", "deleted", "updated", "added")))
    check(f"{n} POST: enum из кодлистов", all(i["state"] in STATES and (i["rating"] is None or i["rating"] in RATINGS)
                                              and (i["platform"] is None or i["platform"] in PLATS) for i in d["items"]))
    check(f"{n} POST: чужие записи (Metaphor, deleted Inside) не потеряны",
          {i["title"] for i in d["items"]} == {"Hades", "Metaphor", "Inside", "Fire Emblem"})
    pg.wait_for_timeout(200)
    check(f"{n} после сохранения оценка видна на карточке", "восторг" in pg.inner_text('#lib-grid .gcard[data-k="hades"]'))
    pg.close()

    # ── «Присматриваюсь»: слияние, открытие мышью/Enter, 409, 400
    pg = load("watch")
    open_t = titles(pg, "#w-want .gt, #w-pencil .gt")
    check(f"{n} watch: Undertale в работе", any("Undertale" in x for x in open_t))
    check(f"{n} watch: Metaphor (не-интересно в оверлее) не в «В работе»", not any("Metaphor" in x for x in open_t))
    fc(pg, '#wfilters .vchip[data-key="nope"]')
    check(f"{n} watch: Metaphor — в слоте «Не хочу»",
          any("Metaphor" in x for x in titles(pg, "#w-nope .gt")) and pg.query_selector("#w-nope .wcard.st-nope") is not None)
    check(f"{n} watch: у Metaphor отметка «правка с сайта»", "с сайта" in pg.inner_text("#w-nope"))
    fc(pg, '#wfilters .vchip[data-key="open"]')
    pg.click('.sc-watch .wcard[data-k="undertale"]')
    check(f"{n} карточка с «Присматриваюсь» (мышь)", opened(pg, "Undertale"))
    pg.keyboard.press("Escape")
    gone(pg)
    check(f"{n} watch: после мыши+Esc фокус на карточку не вернулся", pg.evaluate("document.activeElement.classList.contains('gcard')") is False)
    pg.focus('.sc-watch .wcard[data-k="undertale"]')
    pg.keyboard.press("Enter")
    check(f"{n} карточка с «Присматриваюсь» (Enter)", opened(pg, "Undertale"))
    check(f"{n} условие покупки советника — в сгибе «От советника», свёрнуто",
          pg.query_selector("#gm-card details.gm-adv") is not None and not pg.evaluate("document.querySelector('#gm-card details.gm-adv').open")
          and "сначала демо" in pg.text_content("#gm-card details.gm-adv"))
    check(f"{n} у «хочу» пороги включены; цена — целые доллары (step=1, min=1)",
          pg.get_attribute("#gm-price", "step") == "1" and pg.get_attribute("#gm-price", "min") == "1"
          and pg.get_attribute("#gm-price", "inputmode") == "numeric" and pg.query_selector("#gm-hours") is None)
    pg.fill("#gm-price", "9.5")
    pg.click('#gm-own .gm-opt[data-v="куплена"]')
    check(f"{n} чип «куплена»: порогов в DOM нет, окно не закрыто, «Наиграно» появилось",
          pg.query_selector("#gm-price") is None and pg.query_selector("#gm-disc") is None and pg.query_selector("#gm-card") is not None and pg.is_visible("#gm-hours"))
    pg.click('#gm-own .gm-opt[data-v="куплена"]')            # повторный клик снимает «куплена»
    check(f"{n} «куплена» снята: правая группа вернулась на «хочу», пороги есть, набранное не потеряно, поля часов нет",
          pg.get_attribute('#gm-state .gm-opt[data-v="хочу"]', "aria-pressed") == "true" and pg.is_enabled('#gm-state .gm-opt[data-v="хочу"]')
          and pg.input_value("#gm-price") == "9.5" and pg.query_selector("#gm-hours") is None)
    pg.click('#gm-own .gm-opt[data-v="куплена"]')
    ST["mode"] = "409"
    pg.click('#gm-card [data-act="gm-save"]')
    gone(pg)
    check(f"{n} 409 → два POST, второй с новым hash", len(ST["posts"]) == 2 and ST["posts"][0]["base_hash"] == "h1"
          and ST["posts"][1]["base_hash"] == "h-race")
    ut = [i for i in last_doc()["items"] if i["title"] == "Undertale"][0]
    check(f"{n} 409: повтор принёс правку (куплена, пороги null)", ut["state"] == "куплена" and ut["price_target_usd"] is None
          and ut["discount_target_pct"] is None and ut["hours"] is None)
    pg.wait_for_timeout(200)
    check(f"{n} Undertale ушла из «Присматриваюсь»", not any("Undertale" in x for x in titles(pg, ".sc-watch .wcard .gt")))
    fc(pg, '#wfilters .vchip[data-key="nope"]')
    pg.click('.sc-watch .wcard[data-k="metaphor"]')
    opened(pg, "Metaphor")
    pg.fill("#gm-price", "9.5")
    pg.click('#gm-card [data-act="gm-save"]')
    gone(pg)
    mp = [i for i in last_doc()["items"] if i["title"] == "Metaphor"][0]
    check(f"{n} порог цены округлён до целого при сохранении", mp["price_target_usd"] == 10 and isinstance(mp["price_target_usd"], int))
    pg.click('.sc-watch .wcard[data-k="metaphor"]')
    opened(pg, "Metaphor")
    check(f"{n} при повторном открытии порог показан целым", pg.input_value("#gm-price") == "10")
    ST["mode"] = "400"
    pg.click('#gm-card [data-act="gm-save"]')
    pg.wait_for_function("document.getElementById('gm-msg').textContent.indexOf('длиннее 500') >= 0", timeout=5000)
    check(f"{n} 400: текст валидатора виден, окно открыто",
          "не прошёл проверку" in pg.inner_text("#gm-msg") and pg.query_selector("#gm-card") is not None)
    pg.keyboard.press("Escape")
    check(f"{n} watch: не шире экрана", pg.evaluate("document.documentElement.scrollWidth") <= W)
    pg.close()

    # ── «демо» — флаг demo при некупленном статусе: игра в группе своего статуса, бейдж «демо» у платформы, переключатель «Демо (N)»;
    #    пороги + часы + оценка; «куплена» гасит правую группу, уводит в библиотеку и снимает флаг
    DDEMO = copy.deepcopy(DOC)
    DDEMO["items"].append({"title": "Dave Demo", "platform": "switch", "state": "на-карандаш", "demo": True, "rating": "норм", "note": "играл в демо",
                           "hours": 2, "price_target_usd": 15, "deleted": False, "updated": "2026-11-05", "added": "2026-11-05"})
    DDEMO["items"].append({"title": "Old Demo", "platform": "switch", "state": "демо", "rating": "не понравилось", "deleted": False,
                           "updated": "2026-11-05", "added": "2026-11-05"})                    # старое значение: читается как не хочу + demo
    pg = load("watch", doc=DDEMO)
    check(f"{n} демо: отдельной группы «Демо» и чипа статуса «Демо» нет",
          pg.query_selector("#w-demo") is None and pg.query_selector("#w-demo-head") is None and pg.query_selector('#wfilters .vchip[data-key="demo"]') is None)
    check(f"{n} демо: переключатель «Демо (1)» (число — с учётом «В работе», Old Demo там нет) в ряду «Статус», с классом того же устройства, что «Со скидкой»",
          "Демо (1)" in pg.inner_text("#w-demo-chip") and (pg.is_visible("#w-demo-chip") or W <= 600) and "w-sale" in pg.get_attribute("#w-demo-chip", "class"))
    check(f"{n} демо: игра с флагом лежит в группе своего статуса («На карандаше»), не в библиотеке",
          any(x.strip() == "Dave" for x in titles(pg, "#w-pencil .gt")) and pg.query_selector('#lib-grid .gcard[data-k="dave demo"]') is None)
    check(f"{n} демо: «В работе» = хочу + на карандаше (Dave Demo входит, Old Demo — нет)",
          any(x.strip() == "Dave" for x in titles(pg, ".sc-watch .wcard .gt")) and not any(x.strip() == "Old" for x in titles(pg, ".sc-watch .wcard .gt")))
    check(f"{n} демо: хвост «Demo» в названии на плитке скрыт (ключ записи прежний — «dave demo»)",
          pg.inner_text('.sc-watch .wcard[data-k="dave demo"] .gt').strip() == "Dave")
    check(f"{n} демо: бейдж «демо» под названием в строке платформы, внутри подписи платформы; у игр без флага его нет",
          pg.query_selector('.sc-watch .wcard[data-k="dave demo"] .gm .sub .vbadge.demo') is not None
          and pg.query_selector('.sc-watch .wcard[data-k="undertale"] .vbadge.demo') is None
          and pg.query_selector('#lib-grid .vbadge.demo') is None)
    btn_before = pg.query_selector('#wfilters .vchip[data-key="want"]')
    fc(pg, "#w-demo-chip")
    check(f"{n} демо: переключатель включён — остаются только игры с флагом, чип подсвечен",
          "on" in pg.get_attribute("#w-demo-chip", "class").split()
          and [x.strip() for x in titles(pg, ".sc-watch .wcard .gt")] == ["Dave"])
    check(f"{n} демо: кнопки статуса не пересоздались (тот же узел)", btn_before is not None and btn_before.evaluate("e => e.isConnected"))
    fc(pg, '#wfilters .vchip[data-key="nope"]')
    check(f"{n} демо: складывается со статусом — в «Не хочу» с флагом только Old Demo (старое «демо» + «не понравилось» = не хочу), в группе «Не хочу»",
          [x.strip() for x in titles(pg, ".sc-watch .wcard .gt")] == ["Old"] and "Демо (1)" in pg.inner_text("#w-demo-chip")
          and any(x.strip() == "Old" for x in titles(pg, "#w-nope .gt")))
    fc(pg, '#wfilters .vchip[data-key="open"]')
    fc(pg, "#w-demo-chip")
    check(f"{n} демо: выключен — снова весь список", "on" not in pg.get_attribute("#w-demo-chip", "class").split()
          and any("Undertale" in x for x in titles(pg, ".sc-watch .wcard .gt")))
    pg.click('.sc-watch .wcard[data-k="dave demo"]')
    check(f"{n} демо: карточка открылась", opened(pg, "Dave Demo"))
    check(f"{n} демо: в карточке выбрано «демо» слева и «на карандаше» справа; пороги, часы и оценка есть",
          pg.get_attribute('#gm-own .gm-opt[data-v="демо"]', "aria-pressed") == "true"
          and pg.get_attribute('#gm-state .gm-opt[data-v="на-карандаш"]', "aria-pressed") == "true" and pg.is_enabled('#gm-state .gm-opt[data-v="хочу"]')
          and pg.query_selector("#gm-price") is not None and pg.query_selector("#gm-disc") is not None
          and pg.input_value("#gm-hours") == "2" and pg.input_value("#gm-rating") == "норм" and pg.query_selector("#gm-progress") is not None)
    pg.click('#gm-own .gm-opt[data-v="демо"]')
    check(f"{n} демо: повторный клик снимает «демо» — «Наиграно» и «Прохождение» уходят, правая группа осталась выбранной",
          pg.query_selector("#gm-hours") is None and pg.query_selector("#gm-progress") is None
          and pg.get_attribute('#gm-state .gm-opt[data-v="на-карандаш"]', "aria-pressed") == "true")
    pg.click('#gm-own .gm-opt[data-v="демо"]')
    pg.click('#gm-own .gm-opt[data-v="куплена"]')
    check(f"{n} демо → куплена: «демо» снято (взаимоисключение), правая группа погашена, пороги ушли, часы и оценка на месте",
          pg.get_attribute('#gm-own .gm-opt[data-v="демо"]', "aria-pressed") == "false"
          and all(e.is_disabled() for e in pg.query_selector_all("#gm-state .gm-opt"))
          and pg.query_selector("#gm-price") is None and pg.input_value("#gm-hours") == "2" and pg.input_value("#gm-rating") == "норм")
    pg.click('#gm-card [data-act="gm-save"]')
    gone(pg)
    dd = [i for i in last_doc()["items"] if i["title"] == "Dave Demo"][0]
    check(f"{n} демо → куплена: POST с state, оценкой, часами и заметкой, флага demo нет",
          dd["state"] == "куплена" and dd["rating"] == "норм" and dd["hours"] == 2 and dd["note"] == "играл в демо" and "demo" not in dd)
    pg.wait_for_timeout(200)
    check(f"{n} демо → куплена: ушла из «Присматриваюсь»", not any("Dave Demo" in x for x in titles(pg, ".sc-watch .wcard .gt")))
    lg = pg.query_selector('#lib-grid .gcard[data-k="dave demo"]')
    check(f"{n} демо → куплена: игра в библиотеке с оценкой «норм», без бейджа «демо»", lg is not None and "норм" in lg.inner_text()
          and pg.query_selector('#lib-grid .gcard[data-k="dave demo"] .vbadge.demo') is None)
    pg.close()
    # отметка «демо» в карточке некупленной игры → в POST demo true, статус правой группы сохранён
    pg = load("watch")
    pg.click('.sc-watch .wcard[data-k="undertale"]')
    opened(pg, "Undertale")
    pg.click('#gm-own .gm-opt[data-v="демо"]')
    pg.click('#gm-state .gm-opt[data-v="хочу"]')
    pg.click('#gm-card [data-act="gm-save"]')
    gone(pg)
    ud = [i for i in last_doc()["items"] if i["title"] == "Undertale"][0]
    check(f"{n} демо: отметка в карточке → в POST demo true и state «хочу»", ud["demo"] is True and ud["state"] == "хочу")
    pg.wait_for_timeout(200)
    check(f"{n} демо: после сохранения у плитки бейдж «демо», появился переключатель «Демо (1)»",
          pg.query_selector('.sc-watch .wcard[data-k="undertale"] .vbadge.demo') is not None and "Демо (1)" in pg.inner_text("#w-demo-chip"))
    pg.close()

    # ── добавить игру, дубль, поиск в US eShop
    pg = load("library")
    pg.click('.sc-library [data-act="g-add"]')
    pg.wait_for_selector("#gm-title")
    pg.click('#gm-card [data-act="gm-save"]')
    check(f"{n} пустое название — ошибка, POST не ушёл", "название" in pg.inner_text("#gm-msg") and not ST["posts"])
    pg.fill("#gm-title", "celeste")
    pg.click('#gm-card [data-act="gm-save"]')
    pg.wait_for_function("document.querySelector('#gm-card .ui-modal-title') && document.querySelector('#gm-card .ui-modal-title').textContent === 'Celeste'", timeout=5000)
    pg.wait_for_timeout(150)
    check(f"{n} дубль по названию открыл существующую карточку, POST не ушёл",
          "уже есть" in pg.inner_text("#gm-msg") and not ST["posts"])
    pg.keyboard.press("Escape")
    gone(pg)
    pg.click('.sc-library [data-act="g-add"]')
    pg.wait_for_selector("#gm-title")
    pg.fill("#gm-title", "Stardew Valley")
    ST["lookup"] = 404
    check(f"{n} eShop: нет текстовых полей nsuid/ссылки, поле адреса скрыто",
          pg.query_selector("#gm-nsuid") is None and not pg.is_visible("#gm-url") and pg.query_selector("#gm-link a") is None)
    pg.click('#gm-card [data-act="gm-lookup"]')
    pg.wait_for_function("document.getElementById('gm-msg').textContent.indexOf('не найдена') >= 0", timeout=5000)
    check(f"{n} lookup 404 — сообщение, появилось поле адреса и «Найти по адресу», nsuid пуст",
          pg.is_visible("#gm-url") and pg.is_visible('[data-act="gm-lookup-url"]') and pg.text_content("#gm-cap") == ""
          and "вставьте адрес страницы в us eshop или steam" in pg.text_content("#gm-urlbox").lower())
    pg.fill("#gm-url", "https://www.nintendo.com/us/store/products/stardew-valley-switch/")
    ST["lookup"] = 200
    pg.click('#gm-card [data-act="gm-lookup-url"]')
    pg.wait_for_function("document.getElementById('gm-cap').textContent.indexOf('70010000111111') >= 0", timeout=5000)
    check(f"{n} поиск по адресу: тело запроса с eshop_url", LOOKUP_BODIES[-1].get("eshop_url", "").startswith("https://www.nintendo.com/")
          and LOOKUP_BODIES[-1].get("title") == "Stardew Valley")
    lk = pg.query_selector("#gm-link a")
    check(f"{n} lookup 200: ссылка «Страница в US eShop ↗» (_blank, noopener), подпись nsuid, обложка, платформа",
          lk is not None and "Страница в US eShop" in lk.inner_text() and lk.get_attribute("target") == "_blank"
          and "noopener" in lk.get_attribute("rel") and "nintendo.com" in lk.get_attribute("href")
          and pg.text_content("#gm-cap") == "nsuid 70010000111111" and pg.query_selector("#gm-cov img") is not None
          and pg.input_value("#gm-plat") == "switch" and "Switch" in pg.inner_text('[data-ui-select="gm-plat"] .ui-select-t')
          and pg.inner_text("#gm-store") == "" and not pg.is_visible("#gm-url"))
    pg.click('#gm-card [data-act="gm-save"]')
    gone(pg)
    sv = [i for i in last_doc()["items"] if i["title"] == "Stardew Valley"]
    check(f"{n} новая запись в POST: nsuid, обложка, added, не deleted",
          len(sv) == 1 and sv[0]["nsuid_us"] == "70010000111111" and sv[0]["cover_url"] == LOOKUP["cover_url"]
          and sv[0]["store_title"] == "Stardew Valley" and sv[0]["added"] and sv[0]["deleted"] is False
          and sv[0]["state"] in STATES and ST["posts"][-1]["base_hash"] == "h1"
          and sv[0]["eshop_url"].startswith("https://www.nintendo.com/") and sv[0]["platform"] == "switch")
    fc(pg, '#vfilters .vchip[data-key="unrated"]')   # новая игра без оценки и часов — в «Без оценки»
    pg.wait_for_function("document.querySelector('#lib-grid .gcard[data-k=\"stardew valley\"]')", timeout=5000)
    check(f"{n} новая игра видна в библиотеке с миниатюрой",
          pg.query_selector('#lib-grid .gcard[data-k="stardew valley"] .gthumb img') is not None)
    check(f"{n} не шире экрана", pg.evaluate("document.documentElement.scrollWidth") <= W)
    pg.close()

    # ── миниатюра: размер, высота карточки, onerror → запасной адрес → заглушка
    pg = load("library")
    th = pg.evaluate("""(() => { const r = document.querySelector('#lib-grid .gcard[data-k="hades"] .gthumb').getBoundingClientRect(); return [r.width, r.height]; })()""")
    want = 56 if W <= 600 else 72
    check(f"{n} миниатюра квадратная {want}x{want} (получено {th})", round(th[0]) == round(th[1]) == want)
    rad = pg.evaluate("getComputedStyle(document.querySelector('#lib-grid .gcard[data-k=\"hades\"] .gthumb')).borderRadius")
    check(f"{n} скругление миниатюры 10px", rad == "10px")
    hh = pg.evaluate("""(() => { const d = document.createElement('div'); d.style.cssText = 'position:absolute;left:0;top:0;width:300px'; document.body.appendChild(d);
      const m = {}; [['c', {cover: 'https://img.test/ok.png'}], ['n', {}]].forEach(([k, o]) => { d.innerHTML = __gameCard('Same title', '1ч', 'восторг', o);
      m[k] = d.firstChild.getBoundingClientRect().height; }); d.remove(); return m; })()""")
    check(f"{n} высота карточки с обложкой и без равна ±2 ({hh})", abs(hh["c"] - hh["n"]) <= 2)
    pg.evaluate("""(() => { const d = document.createElement('div'); d.id = 'fbbox'; document.body.appendChild(d);
      d.innerHTML = __gameCard('Aa', '', null, {cover: 'https://img.test/bad1.png', cover_fallback_url: 'https://img.test/good.png'}) +
        __gameCard('Bb', '', null, {cover: 'https://img.test/bad2.png', cover_fallback_url: 'https://img.test/bad3.png'}) +
        __gameCard('Cc', '', null, {steam_appid: '367520'}) + __gameCard('Dd', '', null, {cover: 'https://img.test/bad4.png'}); })()""")
    pg.wait_for_function("document.querySelectorAll('#fbbox .gcard')[1].querySelector('.gthumb img') === null", timeout=8000)
    src = lambda i: pg.evaluate("(i) => { const e = document.querySelectorAll('#fbbox .gcard')[i].querySelector('.gthumb img'); return e && e.getAttribute('src'); }", i)
    pg.wait_for_function("document.querySelectorAll('#fbbox .gcard')[3].querySelector('.gthumb img') === null", timeout=8000)
    pg.wait_for_function("(document.querySelectorAll('#fbbox .gcard')[2].querySelector('.gthumb img')||{}).src === 'https://cdn.cloudflare.steamstatic.com/steam/apps/367520/header.jpg'", timeout=8000)
    check(f"{n} onerror: основной адрес не загрузился → запасной", (src(0) or "").endswith("good.png"))
    check(f"{n} onerror: и запасной не загрузился → картинка убрана, заглушка с буквой",
          src(1) is None and pg.inner_text("#fbbox .gcard:nth-child(2) .gthumb .gph").strip().upper() == "B" and src(3) is None)
    check(f"{n} steam_appid без cover_url: library_600x900 → запасной header.jpg", "367520/header.jpg" in (src(2) or ""))
    check(f"{n} миниатюра lazy", pg.get_attribute('#lib-grid .gcard[data-k="hades"] .gthumb img', "loading") == "lazy")
    pg.close()

    # ── вёрстка карточек библиотеки: обложка + оценка + пометка «с сайта» не режутся
    ov = [dict(i, rating=RATINGS[k], hours=105 + k, cover_url="https://img.test/h.png", state="играю") for k, i in enumerate(
        [{"title": "Hades", "platform": "switch"}, {"title": "Celeste", "platform": "switch"}, {"title": "Inside", "platform": "switch"}])]
    for i in ov:
        i.update(note=None, deleted=False, updated="2026-11-01", added="2026-11-01")
    pg = load("library", doc=dict(DOC, items=ov))
    bad = pg.evaluate("""(() => { const out = []; document.querySelectorAll('#lib-grid .gcard').forEach(c => {
      const cr = c.getBoundingClientRect(); let ok = c.scrollWidth <= c.clientWidth;
      c.querySelectorAll('.vbadge, .g-ed, .gthumb').forEach(e => { const r = e.getBoundingClientRect(); if (r.left < cr.left - 0.5 || r.right > cr.right + 0.5) ok = false; });
      const nw = c.querySelector('.sub .nw'); if (nw && nw.getClientRects().length > 1) ok = false;
      if (!ok) out.push(c.dataset.k); }); return out; })()""")
    cnt = pg.evaluate("document.querySelectorAll('#lib-grid .gcard .vbadge').length")
    check(f"{n} карточки библиотеки (обложка+оценка+«с сайта»): scrollWidth<=clientWidth, чип и метка внутри, «Switch · 105ч» не ломается ({cnt} с чипом, плохие: {bad})",
          cnt >= 3 and not bad)
    pg.close()

    # ── legacy-состояние «брошена» в оверлее → «куплена», оценка цела
    leg = dict(DOC["items"][0], title="Celeste", state="брошена", rating="нормально")
    pg = load("library", doc=dict(DOC, items=DOC["items"] + [leg]))
    pg.click('#lib-grid .gcard[data-k="celeste"]')
    opened(pg, "Celeste")
    check(f"{n} legacy «брошена» показана как «куплена»", pg.get_attribute('#gm-own .gm-opt[data-v="куплена"]', "aria-pressed") == "true"
          and pg.query_selector('#gm-state .gm-opt[data-v="брошена"]') is None)
    pg.fill("#gm-note", "x")
    pg.click('#gm-card [data-act="gm-save"]')
    gone(pg)
    ce = [i for i in last_doc()["items"] if i["title"] == "Celeste"][0]
    check(f"{n} legacy при сохранении уходит как «куплена», оценка не тронута", ce["state"] == "куплена" and ce["rating"] == "нормально" and ce["progress"] == "брошена")
    pg.close()

    # ── имя: «в магазине», переименование записи с сайта, read-only у игр советника
    pg = load("library")
    pg.click('#lib-grid .gcard[data-k="celeste"]')
    opened(pg, "Celeste")
    check(f"{n} игра из библиотеки: поля имени нет, подсказка про ключ",
          pg.query_selector("#gm-title") is None and "ключ к файлам советника" in pg.inner_text("#gm-card") and pg.inner_text("#gm-store") == "")
    pg.keyboard.press("Escape")
    gone(pg)
    pg.close()
    pg = load("watch", doc=dict(DOC, items=DOC["items"] + [DOC_STEAM_ITEM]))
    pg.click('.sc-watch .wcard[data-k="undertale"]')
    opened(pg, "Undertale")
    check(f"{n} игра из watchlist: поля имени нет", pg.query_selector("#gm-title") is None)
    pg.keyboard.press("Escape")
    gone(pg)
    pg.click('.sc-watch .wcard[data-k="hollow knight"]')
    opened(pg, "Hollow Knight")
    check(f"{n} запись с сайта: имя редактируемо, строка «в магазине: …» при отличающемся store_title",
          not pg.is_disabled("#gm-title") and pg.inner_text("#gm-store") == "в магазине: Hollow Knight: Silksong")
    pg.fill("#gm-title", "undertale")
    pg.click('#gm-card [data-act="gm-save"]')
    pg.wait_for_function("document.getElementById('gm-msg').textContent.indexOf('уже есть') >= 0", timeout=5000)
    check(f"{n} переименование в существующее имя — отказ, POST не ушёл", not ST["posts"] and pg.query_selector("#gm-card") is not None)
    pg.fill("#gm-title", "Hollow Knight 2")
    pg.click('#gm-card [data-act="gm-save"]')
    gone(pg)
    its = last_doc()["items"]
    old = [i for i in its if i["title"] == "Hollow Knight"]
    new = [i for i in its if i["title"] == "Hollow Knight 2"]
    check(f"{n} переименование: старая запись deleted, новая с теми же полями и прежним added",
          len(old) == 1 and old[0]["deleted"] is True and len(new) == 1 and new[0]["deleted"] is False
          and new[0]["steam_appid"] == "367520" and new[0]["platform"] == "steam_deck" and new[0]["added"] == "2026-11-03"
          and new[0]["store_title"] == "Hollow Knight: Silksong" and new[0]["state"] == "хочу")
    pg.wait_for_timeout(200)
    check(f"{n} после переименования в списке новое имя, старого нет", pg.query_selector('.sc-watch .wcard[data-k="hollow knight 2"]') is not None
          and pg.query_selector('.sc-watch .wcard[data-k="hollow knight"]') is None)
    pg.close()

    # ── Steam: запись оверлея со steam_appid
    pg = load("watch", doc=dict(DOC, items=DOC["items"] + [DOC_STEAM_ITEM]))
    check(f"{n} Steam-запись в «Присматриваюсь»: обложка из appid", pg.query_selector('.sc-watch .wcard[data-k="hollow knight"] .gthumb img') is not None)
    pg.click('.sc-watch .wcard[data-k="hollow knight"]')
    opened(pg, "Hollow Knight")
    lk = pg.query_selector("#gm-link a")
    check(f"{n} Steam-запись: ссылка «Страница в Steam ↗» и подпись appid, без eShop",
          lk is not None and "Страница в Steam" in lk.inner_text() and lk.get_attribute("href") == "https://store.steampowered.com/app/367520/"
          and pg.text_content("#gm-cap") == "appid 367520" and "eShop" not in pg.inner_text("#gm-link"))
    _lk, _bt = pg.evaluate("(() => { const r = e => e.getBoundingClientRect(); const l = r(document.querySelector('#gm-link a')), b = r(document.querySelector('#gm-card [data-act=\"gm-lookup\"]')); return [[l.right, l.top, l.bottom], [b.left, b.top, b.bottom]]; })()")
    check(f"{n} «Найти обложку и магазин» — справа от ссылки на магазин в той же строке; номер магазина не показан",
          (W <= 600 or (_bt[0] >= _lk[0] and _bt[1] < _lk[2] and _bt[2] > _lk[1])) and not pg.is_visible("#gm-cap"), f"{_lk} {_bt}")   # на телефоне кнопка может перенестись под ссылку
    check(f"{n} в окне карточки миниатюра 72x72", pg.evaluate("(() => { const e = document.querySelector('#gm-cov .gthumb'); return e.offsetWidth === 72 && e.offsetHeight === 72; })()"))
    check(f"{n} кнопка «Найти обложку и магазин»", "Найти обложку и магазин" in pg.inner_text("#gm-card"))
    pg.keyboard.press("Escape")
    gone(pg)
    pg.close()

    # ── поиск возвращает Steam: steam_appid строкой, eshop_url не пишется
    pg = load("library")
    pg.click('.sc-library [data-act="g-add"]')
    pg.wait_for_selector("#gm-title")
    pg.fill("#gm-title", "Hades II")
    pg.click('[data-ui-select="gm-plat"] .ui-select-btn')
    pg.click('[data-ui-select="gm-plat"] .ui-opt[data-value="steam_deck"]')
    ST["steam"] = True
    pg.click('#gm-card [data-act="gm-lookup"]')
    pg.wait_for_function("document.getElementById('gm-cap').textContent.indexOf('1145360') >= 0", timeout=5000)
    lk = pg.query_selector("#gm-link a")
    check(f"{n} lookup (steam): в запрос ушла платформа steam_deck", LOOKUP_BODIES[-1].get("platform") == "steam_deck")
    check(f"{n} lookup (steam): ссылка Steam, подпись appid, подсказка «В Steam», обложка",
          lk is not None and lk.get_attribute("href") == "https://store.steampowered.com/app/1145360/" and "Steam" in lk.inner_text()
          and pg.text_content("#gm-cap") == "appid 1145360" and "в магазине: Hades" in pg.inner_text("#gm-store") and pg.query_selector("#gm-cov .gthumb img") is not None)
    pg.click('#gm-card [data-act="gm-save"]')
    gone(pg)
    sv = [i for i in last_doc()["items"] if i["title"] == "Hades II"]
    check(f"{n} POST из ответа Steam: steam_appid строкой цифр, cover_url, store_title; eshop_url и nsuid пусты, запасной адрес не сохранён",
          len(sv) == 1 and sv[0]["steam_appid"] == "1145360" and isinstance(sv[0]["steam_appid"], str) and sv[0]["cover_url"] == LOOKUP_STEAM["cover_url"]
          and sv[0]["store_title"] == "Hades" and not sv[0].get("eshop_url") and not sv[0].get("nsuid_us") and "cover_fallback_url" not in sv[0])
    pg.close()

    # ── фильтр часов, купленная из watchlist, ссылка eShop в готовой записи, поле часов
    pg = load("library")
    t = titles(pg, "#lib-grid .gcard .gt")
    check(f"{n} по умолчанию — ВСЕ купленные: игры без оценки и часов (Tetris, Portal, Fire Emblem) и с оценкой (Celeste) на месте",
          all(any(x2 in x for x in t) for x2 in ("Tetris", "Portal", "Fire Emblem", "Celeste")) and not any("Inside" in x for x in t))
    check(f"{n} фильтра «Наиграно» нет", pg.query_selector("#hfilters") is None)
    fc(pg, '#vfilters .vchip[data-key="unrated"]')
    t = titles(pg, "#lib-grid .gcard .gt")
    check(f"{n} «без оценки»: Fire Emblem (куплена в оверлее, нет в профиле и library_full) и Portal в списке, Celeste (оценка) нет",
          any("Fire Emblem" in x for x in t) and any("Portal" in x for x in t) and not any("Celeste" in x for x in t))
    pg.click('#lib-grid .gcard[data-k="portal"]')
    opened(pg, "Portal")
    pg.keyboard.press("Escape")
    gone(pg)
    pg.click('#lib-grid .gcard[data-k="fire emblem"]')
    opened(pg, "Fire Emblem")
    check(f"{n} Fire Emblem: состояние «куплена», порогов нет, часы пустые без подсказки",
          pg.get_attribute('#gm-own .gm-opt[data-v="куплена"]', "aria-pressed") == "true" and pg.query_selector("#gm-price") is None
          and pg.input_value("#gm-hours") == "" and "из библиотеки" not in pg.inner_text("#gm-hours-host"))
    pg.keyboard.press("Escape")
    gone(pg)
    pg.click('#lib-grid .gcard[data-k="portal"]')
    opened(pg, "Portal")
    check(f"{n} Portal: подсказка «из библиотеки: 3 ч», поле пустое", "из библиотеки: 3 ч" in pg.inner_text("#gm-hours-host")
          and pg.input_value("#gm-hours") == "")
    pg.click('[data-ui-select="gm-progress"] .ui-select-btn')
    pg.click('[data-ui-select="gm-progress"] .ui-opt[data-value="играю"]')
    pg.click('#gm-card [data-act="gm-save"]')
    gone(pg)
    po = [i for i in last_doc()["items"] if i["title"] == "Portal"][0]
    check(f"{n} часы из библиотеки в оверлей не скопированы", po["hours"] is None)
    pg.click('#lib-grid .gcard[data-k="portal"]')
    opened(pg, "Portal")
    pg.fill("#gm-hours", "30")
    pg.click('#gm-card [data-act="gm-save"]')
    gone(pg)
    pg.wait_for_timeout(150)
    check(f"{n} часы оверлея главнее: в карточке списка «30ч»", "30ч" in pg.inner_text('#lib-grid .gcard[data-k="portal"]'))
    pg.close()

    # ── платформа и сортировка в библиотеке; localStorage
    pg = load("library")
    fc(pg, '#vfilters .vchip[data-key="unrated"]')
    chips = titles(pg, "#pfilters .vchip")
    check(f"{n} чипы платформ: только встречающиеся, со счётчиком", chips[0].startswith("Все (") and any(c.startswith("Steam Deck (1)") for c in chips)
          and any(c.startswith("Switch (") for c in chips) and not any(c.startswith("Switch 2") for c in chips)
          and not any(c.startswith("Xbox") for c in chips))
    fc(pg, '#pfilters .vchip[data-key="steam_deck"]')
    t = titles(pg, "#lib-grid .gcard .gt")
    check(f"{n} фильтр платформы: только Steam Deck", len(t) == 1 and "Portal" in t[0])
    check(f"{n} выбор платформы запомнен в localStorage", pg.evaluate("localStorage.getItem('games-lib-plat')") == "steam_deck")
    fc(pg, '#pfilters .vchip[data-key="all"]')
    fc(pg, '[data-ui-select="gm-lib-sort"] .ui-select-btn')
    check(f"{n} сортировка — uiSelect: часы / имя / дата",
          [e.get_attribute("data-value") for e in pg.query_selector_all('[data-ui-select="gm-lib-sort"] .ui-opt')] == ["hours", "name", "date"])
    fc(pg, '[data-ui-select="gm-lib-sort"] .ui-opt[data-value="hours"]')
    t = titles(pg, "#lib-grid .gcard .gt")
    check(f"{n} сортировка по часам: Portal (3 ч) первой, игры без часов — в конце", "Portal" in t[0] and "Portal" not in t[-1]
          and any("Tetris" in x for x in t[-2:]) and any("Fire Emblem" in x for x in t[-2:]))
    fc(pg, '[data-ui-select="gm-lib-sort"] .ui-select-btn')
    fc(pg, '[data-ui-select="gm-lib-sort"] .ui-opt[data-value="name"]')
    t = titles(pg, "#lib-grid .gcard .gt")
    check(f"{n} сортировка по имени — алфавитный порядок", t == sorted(t, key=str.lower) and len(t) >= 3, str(t))
    fc(pg, '[data-ui-select="gm-lib-sort"] .ui-select-btn')
    fc(pg, '[data-ui-select="gm-lib-sort"] .ui-opt[data-value="date"]')
    t = titles(pg, "#lib-grid .gcard .gt")
    check(f"{n} сортировка по дате правки: Fire Emblem (правка 2026-11-02) первой", "Fire Emblem" in t[0], str(t))
    check(f"{n} выбор сортировки запомнен", pg.evaluate("localStorage.getItem('games-lib-sort')") == "date")
    pg.reload()
    pg.wait_for_function("document.querySelectorAll('.sc-library .gcard').length >= 1", timeout=15000)
    check(f"{n} после перезагрузки сортировка применена", pg.input_value("#gm-lib-sort") == "date")
    pg.evaluate("localStorage.clear()")
    pg.close()

    # ── «Присматриваюсь»: платформа и сортировка в слотах
    pg = load("watch")
    fc(pg, '#wfilters .vchip[data-key="open"]')
    fc(pg, '#wpfilters .vchip[data-key="switch"]')
    check(f"{n} watch: фильтр платформы Switch — только Undertale", titles(pg, "#w-want .gt, #w-pencil .gt") == ["Undertale"])
    fc(pg, '#wpfilters .vchip[data-key="all"]')
    fc(pg, '[data-ui-select="gm-w-sort"] .ui-select-btn')
    fc(pg, '[data-ui-select="gm-w-sort"] .ui-opt[data-value="name"]')
    t = titles(pg, "#w-want .gt")
    check(f"{n} watch: сортировка по имени внутри слота «Хочу»", t == ["Alan Wake", "Undertale"], str(t))
    pg.evaluate("localStorage.clear()")
    pg.close()

    # ── массовый подбор обложек
    pg = load("library")
    fc(pg, '#vfilters .vchip[data-key="unrated"]')
    FILL["results"] = [{"title": "Portal", "nsuid_us": "70010000222222", "store_title": "Portal: Companion", "platform": "switch",
                        "eshop_url": "https://www.nintendo.com/us/store/products/portal-switch/", "cover_url": "https://img.test/p.png"},
                       {"title": "Tetris", "error": "not found"}]
    FILL["done"] = False
    pg.click('.sc-library [data-act="g-fill"]')
    pg.wait_for_function("document.getElementById('gm-bar').textContent.indexOf('Обложек найдено') >= 0", timeout=8000)
    bar = pg.inner_text("#gm-bar")
    sent = [it["title"] for it in FILL["bodies"][-1]["items"]]
    check(f"{n} массовый подбор: запрос без игр с обложкой (Hades), с title/platform/eshop_url",
          "Hades" not in sent and "Portal" in sent and all({"title", "platform", "eshop_url"} <= set(it) for it in FILL["bodies"][-1]["items"]))
    check(f"{n} итог: «найдено N из M», не нашлось: Tetris, done=false — подсказка нажать ещё раз",
          "найдено 1 из" in bar and "не нашлось" in bar and "Tetris" in bar and "ещё раз" in bar, bar)
    check(f"{n} массовый подбор: одно сохранение", len(ST["posts"]) == 1)
    d = last_doc()
    po = [i for i in d["items"] if i["title"] == "Portal"]
    hd = [i for i in d["items"] if i["title"] == "Hades"][0]
    check(f"{n} Portal создан в оверлее с nsuid/обложкой/состоянием «куплена»; Hades не затёрт (обложка прежняя)",
          len(po) == 1 and po[0]["nsuid_us"] == "70010000222222" and po[0]["cover_url"] == "https://img.test/p.png" and po[0]["state"] == "куплена"
          and hd["cover_url"] == "https://img.test/h.png" and hd["state"] == "куплена" and hd["progress"] == "играю" and hd["note"] == "в процессе")
    pg.wait_for_timeout(150)
    check(f"{n} после подбора у Portal миниатюра", pg.query_selector('#lib-grid .gcard[data-k="portal"] .gthumb img') is not None)
    FILL["code"] = 404
    pg.click('.sc-library [data-act="g-fill"]')
    pg.wait_for_function("document.getElementById('gm-bar').textContent.indexOf('404') >= 0", timeout=8000)
    check(f"{n} подбор: 404 маршрута — сообщение, без падения", len(ST["posts"]) == 1)
    FILL["code"] = 200
    # ── cover_tried: у ненайденных — сегодня; повторный подбор их не шлёт; старше 30 дней — шлёт снова
    tdy = pg.evaluate("(() => { const d = new Date(), z = n => (n < 10 ? '0' : '') + n; return d.getFullYear() + '-' + z(d.getMonth() + 1) + '-' + z(d.getDate()); })()")
    tt = [i for i in d["items"] if i["title"] == "Tetris"]
    check(f"{n} cover_tried: у ненайденного Tetris в документе — сегодня, у найденного Portal нет", len(tt) == 1 and tt[0].get("cover_tried") == tdy
          and not po[0].get("cover_tried"), str(tt))
    FILL["results"] = []
    FILL["done"] = True
    pg.click('.sc-library [data-act="g-fill"]')
    pg.wait_for_function("document.getElementById('gm-bar').textContent.indexOf('пропущено') >= 0", timeout=8000)
    sent2 = [it["title"] for it in FILL["bodies"][-1]["items"]]
    check(f"{n} второй подбор: Tetris не отправлен, сообщение «пропущено 1 (искали недавно)»",
          "Tetris" not in sent2 and "пропущено 1 (искали недавно)" in pg.inner_text("#gm-bar"), f"{sent2} {pg.inner_text('#gm-bar')}")
    tt = [i for i in last_doc()["items"] if i["title"] == "Tetris"]
    check(f"{n} игры без ответа сервера (done=true, пусто) тоже помечены, у Tetris дата прежняя", len(tt) == 1 and tt[0]["cover_tried"] == tdy)
    pg.click('#lib-grid .gcard[data-k="tetris"]')
    opened(pg, "Tetris")
    tx = pg.inner_text("#gm-tried")
    check(f"{n} карточка с cover_tried: «обложка не нашлась ДД.ММ — вставь адрес страницы»",
          tx == f"обложка не нашлась {tdy[8:10]}.{tdy[5:7]} — вставь адрес страницы" and pg.is_visible("#gm-tried"), tx)
    pg.click('[data-act="gm-lookup"]')
    pg.wait_for_function("document.getElementById('gm-msg').textContent.indexOf('Найдено') >= 0", timeout=8000)
    check(f"{n} успешный поиск в карточке прячет строку «не нашлась»; кнопка работала при свежем cover_tried", not pg.is_visible("#gm-tried"))
    npost = len(ST["posts"])
    pg.evaluate("document.getElementById('gm-bar').innerHTML = ''")    # тост «ничего не найдено» не автоскрывается
    pg.click('#gm-card [data-act="gm-save"]')
    gone(pg)
    tt = [i for i in last_doc()["items"] if i["title"] == "Tetris"]
    check(f"{n} после сохранения у Tetris cover_tried = null, обложка/nsuid из поиска", len(ST["posts"]) == npost + 1 and tt[0]["cover_tried"] is None and tt[0]["nsuid_us"] == "70010000111111")
    # старше 30 дней — снова в выборке
    old = [i for i in ST["doc"]["items"] if i["title"] == "Tetris"][0]
    old["cover_tried"] = "2020-01-01"; old["nsuid_us"] = None; old["cover_url"] = None
    pg.reload()
    pg.wait_for_function("document.querySelectorAll('.sc-library .gcard').length >= 1", timeout=15000)
    pg.wait_for_timeout(150)
    fc(pg, '#vfilters .vchip[data-key="unrated"]')
    pg.click('.sc-library [data-act="g-fill"]')
    pg.wait_for_function("document.getElementById('gm-bar').textContent.indexOf('Обложек найдено') >= 0", timeout=8000)
    sent3 = [it["title"] for it in FILL["bodies"][-1]["items"]]
    check(f"{n} cover_tried старше 30 дней: Tetris отправляется снова", "Tetris" in sent3, str(sent3))
    pg.close()
    pg = load("watch")
    FILL["results"] = [{"title": "Undertale", "nsuid_us": "70010000009921", "store_title": "UNDERTALE", "cover_url": "https://img.test/u.png",
                        "eshop_url": "https://www.nintendo.com/us/store/products/undertale-switch/", "platform": "switch"}]
    pg.click('.sc-watch [data-act="g-fill"]')
    pg.wait_for_function("document.getElementById('gm-bar').textContent.indexOf('Обложек найдено') >= 0", timeout=8000)
    ut = [i for i in last_doc()["items"] if i["title"] == "Undertale"]
    check(f"{n} watch: подбор создал запись с прежним статусом «хочу»", len(ut) == 1 and ut[0]["state"] == "хочу" and ut[0]["cover_url"] == "https://img.test/u.png"
          and ut[0]["eshop_url"].endswith("undertale-switch/") and ut[0]["nsuid_us"] is None)
    pg.close()

    # ── файла оверлея нет (404): страница как раньше, первый POST с base_hash null
    pg = load("library", doc=None)
    check(f"{n} 404 оверлея: без отметок «правка с сайта»", pg.query_selector("#lib-grid .g-ed") is None)
    pg.click('#lib-grid .gcard[data-k="celeste"]')
    opened(pg, "Celeste")
    pg.click('[data-ui-select="gm-progress"] .ui-select-btn')
    pg.click('[data-ui-select="gm-progress"] .ui-opt[data-value="пройдена"]')
    pg.click('#gm-card [data-act="gm-save"]')
    gone(pg)
    check(f"{n} 404 оверлея: первый POST с base_hash null", ST["posts"][0]["base_hash"] is None
          and last_doc()["schema"] == "gaming-user@1" and len(last_doc()["items"]) == 1)
    pg.close()

    # ── v2.4: живой заголовок «Новая игра», сетка, без прокрутки окна, Switch одним чипом, окно фильтров на телефоне
    pg = load("library")
    pg.click('.sc-library [data-act="g-add"]')
    pg.wait_for_selector("#gm-title")
    ttl = lambda: pg.inner_text("#gm-card .ui-modal-title")
    check(f"{n} новая игра: шапка «Новая игра», серая (.ph)", ttl() == "Новая игра" and pg.evaluate("document.querySelector('#gm-card .ui-modal-title').classList.contains('ph')"))
    pg.fill("#gm-title", "Stardew")
    check(f"{n} новая игра: шапка живо повторяет поле «Название»", ttl() == "Stardew" and not pg.evaluate("document.querySelector('#gm-card .ui-modal-title').classList.contains('ph')"))
    pg.fill("#gm-title", "")
    check(f"{n} новая игра: пустое поле → снова серая «Новая игра»", ttl() == "Новая игра" and pg.evaluate("document.querySelector('#gm-card .ui-modal-title').classList.contains('ph')"))
    if W > 600:
        pg.set_viewport_size({"width": W, "height": 860})
        pg.wait_for_timeout(100)
        ov = lambda: pg.evaluate("(() => { const b = document.querySelector('#gm-card .ui-modal-body'); return [b.scrollHeight, b.clientHeight]; })()")
        sh = ov()
        check(f"{n} окно «Новая игра» на 1280x860 без прокрутки ({sh})", sh[0] <= sh[1] + 2)
    pg.keyboard.press("Escape")
    gone(pg)
    if W > 600:
        for sel, nm in (('#lib-grid .gcard[data-k="hades"]', "Hades"), ('#lib-grid .gcard[data-k="portal"]', "Portal")):
            if pg.query_selector(sel) is None:
                fc(pg, '#vfilters .vchip[data-key="unrated"]')
            pg.click(sel)
            opened(pg, nm)
            sh = pg.evaluate("(() => { const b = document.querySelector('#gm-card .ui-modal-body'); return [b.scrollHeight, b.clientHeight]; })()")
            check(f"{n} окно «{nm}» на 1280x860 без вертикальной прокрутки ({sh})", sh[0] <= sh[1] + 2)
            pg.keyboard.press("Escape")
            gone(pg)
    pg.close()

    pg = load("library")
    pg.evaluate("document.getElementById('lib-grid').innerHTML = Array.from({length: 9}, (_, i) => __gameCard('Длинное название игры номер ' + i, 'Switch · 10ч', 'восторг', {})).join('')")
    cols = pg.evaluate("(() => { const c = [...document.querySelectorAll('#lib-grid .gcard')], t = c[0].offsetTop; return new Set(c.filter(x => x.offsetTop === t).map(x => x.offsetLeft)).size; })()")
    check(f"{n} сетка библиотеки: в первой строке {cols} колонок ({'≤3' if W > 600 else '≤2'}), без переполнения",
          cols <= (3 if W > 600 else 2) and cols >= 1 and pg.evaluate("document.documentElement.scrollWidth") <= W)
    pg.close()

    pg = load("library")
    exp, has2 = 4, True      # Hades, Celeste, Tetris (switch) + Fire Emblem (switch2, правка с сайта); Inside удалена
    ch = pg.evaluate("[...document.querySelectorAll('#pfilters .vchip')].map(c => c.textContent)")   # без других фильтров: числа по всей библиотеке
    check(f"{n} чип «Switch ({exp})» объединяет Switch и Switch 2", has2 and f"Switch ({exp})" in ch and not any(c.startswith("Switch 2") for c in ch))
    leg = pg.evaluate("[...document.querySelectorAll('#plat-legend > span')].map(s => s.textContent.trim())")
    segs = pg.evaluate("document.querySelectorAll('#plat-bar > div').length")
    allc = pg.evaluate("document.querySelector('#pfilters .vchip[data-key=\"all\"]').textContent")
    fc(pg, '#vfilters .vchip[data-key="unrated"]')
    shown_t = titles(pg, "#lib-grid .gcard .gt")
    check(f"{n} числа на чипах — с учётом остальных фильтров: «без оценки» → «Все» платформ = числу плиток, чипы не пересозданы",
          pg.inner_text('#pfilters .vchip[data-key="all"]') == f"Все ({len(shown_t)})" and len(shown_t) < int(allc.split("(")[1].rstrip(")"))
          and pg.inner_text('#vfilters .vchip[data-key="all"]') == allc, pg.inner_text("#pfilters"))
    check(f"{n} полоса «всего»: подпись из слитых записей — «Switch · {exp}» одним пунктом, Switch 2 отдельно нет, сегментов = пунктов, сумма = «Все» чипов",
          f"Switch · {exp}" in leg and not any(x.startswith("Switch 2") for x in leg) and segs == len(leg)
          and sum(int(x.rsplit("· ", 1)[1]) for x in leg) == int(allc.split("(")[1].rstrip(")")), str(leg) + " " + allc)
    check(f"{n} в подписи полосы нет «switch_2», игра с таким значением учтена в «Switch»", not any("switch_2" in x.lower() for x in leg) and any("Tetris" in x for x in shown_t), str(leg))
    np_ = pg.evaluate("['switch_2', 'Switch 2', 'Nintendo Switch 2', 'steam-deck', 'Xbox Series X', 'мусор', 'NS', 'PC', 'Windows', null].map(__normPlat)")
    check(f"{n} normPlat: {np_}", np_ == ["switch2", "switch2", "switch2", "steam_deck", "xbox", None, "switch", "pc", "pc", None])
    check(f"{n} «всего» в шапке = сумме подписи", int(pg.inner_text("#lib-total")) == sum(int(x.rsplit("· ", 1)[1]) for x in leg))
    fc(pg, '#pfilters .vchip[data-key="switch"]')
    shown = titles(pg, "#lib-grid .gcard .gt")
    check(f"{n} фильтр «Switch» пропускает обе платформы, Steam Deck нет",
          any("Fire Emblem" in x for x in shown) and any("Tetris" in x for x in shown) and not any("Portal" in x for x in shown), str(shown))
    pg.close()

    pg = load("library")
    pg.evaluate("localStorage.clear()")      # платформа/сортировка прошлых проверок запомнены — начинаем с дефолтов
    pg.reload()
    pg.wait_for_function("document.querySelectorAll('.sc-library .gcard').length >= 1", timeout=15000)
    pg.wait_for_timeout(150)
    vis = lambda sel: pg.evaluate("(s) => [...document.querySelectorAll(s)].some(e => e.offsetParent !== null && getComputedStyle(e).visibility !== 'hidden')", sel)
    pnum = lambda sel: pg.evaluate("(s) => { const e = document.querySelector(s); return e ? e.textContent.trim() : null; }", sel)
    if W > 600:
        check(f"{n} компьютер: чипы и сортировка в потоке, поле поиска в .ui-qrow, кнопок «Фильтры»/«Сброс» нет",
              pg.is_visible("#lib-qrow #lib-q") and not vis(".ui-fbtn")
              and not vis(".ui-freset") and vis("#vfilters .vchip") and vis("#pfilters .vchip") and vis("#lib-sort")
              and pg.query_selector(".sc-library .fgroup-slot #lib-fgroup") is not None and pg.query_selector("#gm-fwin") is None)
        check(f"{n} компьютер: ни одна .ui-fbtn не видна", not vis(".ui-fbtn") and not vis(".ui-freset"))
    else:
        check(f"{n} строка поиска и фильтров: поле, «Фильтры» без бейджа, «Сброс» скрыт; чипов в потоке нет",
              pg.is_visible("#lib-qrow #lib-q") and pg.get_attribute("#lib-q", "type") == "search" and pg.get_attribute("#lib-q", "placeholder") == "Поиск по названию"
              and pg.is_visible("#lib-fbtn.ui-fbtn") and pg.query_selector("#lib-fbtn .ui-fbtn-n") is None and not pg.is_visible("#lib-freset")
              and not vis("#vfilters .vchip") and not vis("#pfilters .vchip") and not vis("#lib-sort")
              and pg.inner_text("#lib-fbtn").strip() == "Фильтры" and "·" not in pg.inner_text("#lib-qrow"))
    shots = os.environ.get("GAMES_SHOTS")   # скриншоты для приёмки: GAMES_SHOTS=<каталог>
    if shots:
        pg.screenshot(path=f"{shots}/games-lib-{W}-v251.png")
    pg.fill("#lib-q", "hAdEs")
    check(f"{n} поиск «hAdEs» оставляет Hades", titles(pg, "#lib-grid .gcard .gt") == ["Hades"], str(titles(pg, "#lib-grid .gcard .gt")))
    pg.fill("#lib-q", "definitive")
    check(f"{n} поиск по store_title («definitive» → Hades)", titles(pg, "#lib-grid .gcard .gt") == ["Hades"], str(titles(pg, "#lib-grid .gcard .gt")))
    pg.fill("#lib-q", "")
    check(f"{n} пустой поиск возвращает список", len(titles(pg, "#lib-grid .gcard .gt")) >= 2)
    if W <= 600:
        pg.click("#lib-fbtn")
        pg.wait_for_selector("#gm-fwin .ui-modal-box")
        check(f"{n} шторка «Фильтры» открыта, чипы и сортировка в ней видны",
              pg.evaluate("document.querySelector('#gm-fwin .ui-modal').classList.contains('sheet')")
              and vis("#gm-fwin #vfilters .vchip") and vis("#gm-fwin #pfilters .vchip") and pg.query_selector("#gm-fwin #lib-sort") is not None
              and pg.is_visible('#gm-fwin [data-act="gm-freset"]') and pg.is_visible('#gm-fwin .ui-modal-save'))
        if shots and W <= 600:
            pg.wait_for_timeout(500)
            pg.screenshot(path=f"{shots}/games-sheet-{W}.png")
        if W <= 600:
            bx = pg.evaluate("(() => { const r = document.querySelector('#gm-fwin .ui-modal-box').getBoundingClientRect(); return [r.bottom, innerHeight]; })()")
            check(f"{n} телефон: шторка прижата к низу ({bx})", abs(bx[0] - bx[1]) <= 2)
        else:
            bx = pg.evaluate("(() => { const r = document.querySelector('#gm-fwin .ui-modal-box').getBoundingClientRect(); return [r.left, innerWidth - r.right, r.bottom, innerHeight]; })()")
            check(f"{n} десктоп: шторка — окно по центру, не у низа ({bx})", abs(bx[0] - bx[1]) <= 40 and bx[2] < bx[3] - 20)
        pg.click('#gm-fwin #vfilters .vchip[data-key="all"]')
        pg.click('#gm-fwin #vfilters .vchip[data-key="unrated"]')
        check(f"{n} чип в шторке работает (грид перерисован)", (lambda m: bool(m) and int(m.group(1)) < int(m.group(2)))(re.search(r"Показаны (\d+) из (\d+)", pg.inner_text("#lib-note"))))
        pg.keyboard.press("Escape")
        pg.wait_for_function("!document.getElementById('gm-fwin')", timeout=5000)
        check(f"{n} Esc закрывает шторку, группа вернулась на место и скрыта; бейдж 1, «Сброс» виден; фокус не на кнопке (мышь)",
              not vis("#vfilters .vchip") and pg.query_selector(".sc-library .fgroup-slot #lib-fgroup") is not None
              and pnum("#lib-fbtn .ui-fbtn-n") == "1" and pg.is_visible("#lib-freset")
              and pg.evaluate("document.activeElement.id") != "lib-fbtn")
        pg.click("#lib-freset")
        check(f"{n} «Сброс» снимает бейдж и прячется, вердикт «Все»",
              pg.query_selector("#lib-fbtn .ui-fbtn-n") is None and not pg.is_visible("#lib-freset")
              and pg.evaluate("document.querySelector('#vfilters .vchip.on').getAttribute('data-key')") == "all")
        pg.evaluate("localStorage.setItem('games-lib-plat', 'steam_deck')")
        pg.reload()
        pg.wait_for_function("document.getElementById('lib-total').textContent.trim() !== '—'", timeout=15000)
        pg.wait_for_timeout(150)
        check(f"{n} сохранённая платформа даёт бейдж 1 и «Сброс»", pnum("#lib-fbtn .ui-fbtn-n") == "1" and pg.is_visible("#lib-freset"))
        pg.click("#lib-freset")
        check(f"{n} «Сброс» очищает и сохранённую платформу", pg.evaluate("localStorage.getItem('games-lib-plat')") == "all" and pg.query_selector("#lib-fbtn .ui-fbtn-n") is None)
        pg.click("#lib-fbtn")
        pg.wait_for_selector("#gm-fwin .ui-modal-box")
        pg.click('#gm-fwin #vfilters .vchip[data-key="unrated"]')
        pg.click('#gm-fwin [data-act="gm-freset"]')
        check(f"{n} «Сбросить» в шторке вернул вердикт «Все»", pg.evaluate("document.querySelector('#vfilters .vchip.on').getAttribute('data-key')") == "all")
        pg.click("#gm-fwin .ui-modal-save")
        pg.wait_for_function("!document.getElementById('gm-fwin')", timeout=5000)
        pg.click("#lib-fbtn")
        pg.wait_for_selector("#gm-fwin .ui-modal-box")
        pg.evaluate("document.querySelector('#lib-grid .gcard').dispatchEvent(new MouseEvent('click', {bubbles: true}))")
        pg.wait_for_selector("#gm-card .ui-modal-box", timeout=5000)
        check(f"{n} открыта карточка — шторка закрылась", pg.query_selector("#gm-fwin") is None and pg.query_selector(".sc-library .fgroup-slot #lib-fgroup") is not None)
        pg.keyboard.press("Escape")
        gone(pg)
    else:
        # компьютер: чипы в потоке работают без шторки, смена ширины переносит узлы без потери состояния
        pg.click('#vfilters .vchip[data-key="unrated"]')
        check(f"{n} чип в потоке работает (грид перерисован)", (lambda m: bool(m) and int(m.group(1)) < int(m.group(2)))(re.search(r"Показаны (\d+) из (\d+)", pg.inner_text("#lib-note"))))
        pg.set_viewport_size({"width": 390, "height": 844})
        pg.wait_for_timeout(200)
        check(f"{n} →390: группы скрыты, «Фильтры» с бейджем 1 и «Сброс» видны, состояние сохранено",
              not vis("#vfilters .vchip") and pg.is_visible("#lib-fbtn") and pnum("#lib-fbtn .ui-fbtn-n") == "1" and pg.is_visible("#lib-freset"))
        pg.click("#lib-fbtn")
        pg.wait_for_selector("#gm-fwin .ui-modal-box")
        check(f"{n} →390: в шторке чип «без вердикта» включён", pg.evaluate("document.querySelector('#gm-fwin #vfilters .vchip.on').getAttribute('data-key')") == "unrated")
        pg.set_viewport_size({"width": 1280, "height": 900})
        pg.wait_for_function("!document.getElementById('gm-fwin')", timeout=5000)
        check(f"{n} →1280: шторка закрылась, узлы вернулись в поток, чип «без вердикта» включён, кнопок нет",
              pg.query_selector(".sc-library .fgroup-slot #lib-fgroup") is not None and vis("#vfilters .vchip") and not vis(".ui-fbtn")
              and pg.evaluate("document.querySelector('#vfilters .vchip.on').getAttribute('data-key')") == "unrated")
        pg.click('#vfilters .vchip[data-key="all"]')
    check(f"{n} не шире экрана", pg.evaluate("document.documentElement.scrollWidth") <= W)
    pg.close()
    pg = load("watch")
    pg.evaluate("localStorage.clear()")
    pg.reload()
    pg.wait_for_function("document.querySelectorAll('.sc-watch .gcard').length >= 1", timeout=15000)
    pg.wait_for_timeout(150)
    if W > 600:
        check(f"{n} watch: компьютер — поиск и чипы в потоке, кнопок «Фильтры»/«Сброс» нет",
              pg.is_visible("#w-q") and vis("#wfilters .vchip") and vis("#wpfilters .vchip") and vis("#w-sort") and not vis(".ui-fbtn") and not vis(".ui-freset"))
        fc(pg, '#wfilters .vchip[data-key="want"]')
        check(f"{n} watch: чип «Хочу» в потоке фильтрует", pg.evaluate("document.querySelector('#wfilters .vchip.on').getAttribute('data-key')") == "want")
    else:
        check(f"{n} watch: строка поиска, «Фильтры» без бейджа, чипов в потоке нет",
              pg.is_visible("#w-q") and pg.query_selector("#w-fbtn .ui-fbtn-n") is None and not pg.is_visible("#w-freset") and not vis("#wfilters .vchip"))
        fc(pg, '#wfilters .vchip[data-key="want"]')
        check(f"{n} watch: после выбора «Хочу» бейдж 1 и «Сброс»", pg.inner_text("#w-fbtn .ui-fbtn-n") == "1" and pg.is_visible("#w-freset"))
        pg.click("#w-freset")
        check(f"{n} watch: «Сброс» убирает бейдж", pg.query_selector("#w-fbtn .ui-fbtn-n") is None and not pg.is_visible("#w-freset"))
    pg.fill("#w-q", "remastered")
    check(f"{n} watch: поиск по store_title («remastered» → Alan Wake)", titles(pg, ".sc-watch .wcard .gt") == ["Alan Wake"], str(titles(pg, ".sc-watch .wcard .gt")))
    pg.fill("#w-q", "ALAN")
    check(f"{n} watch: поиск по названию без регистра", titles(pg, ".sc-watch .wcard .gt") == ["Alan Wake"], str(titles(pg, ".sc-watch .wcard .gt")))
    pg.fill("#w-q", "")
    check(f"{n} watch: чип «Switch (1)»", "Switch (1)" in pg.evaluate("[...document.querySelectorAll('#wpfilters .vchip')].map(c => c.textContent)"))
    pg.close()
    # ── запись из watchlist.yaml, купленная на сайте (оверлей: куплена, switch2, 5 ч, заметка) — карточка из библиотеки редактируема
    FEW = "Fire Emblem: Fortune's Weave"
    doc_fe = copy.deepcopy(DOC)
    doc_fe["items"].append({"title": FEW, "platform": "switch2", "state": "куплена", "rating": None, "note": "Куплена была в Ростове",
                            "hours": 5, "deleted": False, "updated": "2026-11-05", "added": "2026-11-05"})
    watch_fe = WATCH + '  - title: "Fire Emblem: Fortune\'s Weave"\n    status: хочу\n    platform: switch2\n    added: 2026-10-30\n'
    ctx.route("**/Gaming/watchlist.yaml*", lambda r: r.fulfill(status=200, content_type="text/yaml; charset=utf-8", body=watch_fe.encode()))
    pg = load("library", doc_fe)
    kk = "fire emblem fortune s weave"
    sel_c = f'#lib-grid .gcard[data-k="{kk}"]'
    fc(pg, '#vfilters .vchip[data-key="unrated"]')    # без оценки — в разделе «Без оценки»
    check(f"{n} запись советника, купленная на сайте, в библиотеке", pg.query_selector(sel_c) is not None)
    ct = pg.inner_text(sel_c)
    check(f"{n} подпись: «Switch 2 · 5ч с сайта» (кодлист, разделитель перед пометкой)", "Switch 2" in ct and "Switch2" not in ct and "5ч с сайта" in " ".join(ct.split()), repr(ct))
    check(f"{n} подпись Portal — «Steam Deck» по кодлисту",
          "Steam Deck" in pg.inner_text('#lib-grid .gcard[data-k="portal"]'))
    pg.click(sel_c)
    check(f"{n} карточка открылась по клику на карточку", opened(pg, FEW))
    check(f"{n} запись советника: имя read-only (поля «Название» нет), состояние/оценка/платформа/часы/заметка доступны",
          pg.query_selector("#gm-title") is None and pg.get_attribute('#gm-own .gm-opt[data-v="демо"]', "disabled") is None
          and pg.get_attribute('#gm-own .gm-opt[data-v="куплена"]', "aria-pressed") == "true"
          and pg.is_enabled("#gm-hours") and pg.is_enabled("#gm-note") and pg.input_value("#gm-hours") == "5"
          and pg.input_value("#gm-note") == "Куплена была в Ростове" and pg.input_value("#gm-plat") == "switch2"
          and pg.is_enabled('[data-ui-select="gm-rating"] .ui-select-btn') and pg.is_enabled('[data-ui-select="gm-plat"] .ui-select-btn')
          and pg.is_enabled('#gm-card [data-act="gm-save"]'))
    pg.click('[data-ui-select="gm-rating"] .ui-select-btn')
    pg.click('[data-ui-select="gm-rating"] .ui-opt[data-value="понравилось"]')
    pg.fill("#gm-hours", "12")
    pg.click('#gm-card [data-act="gm-save"]')
    gone(pg)
    fe = [i for i in last_doc()["items"] if i["title"] == FEW]
    check(f"{n} POST ушёл: запись обновлена (оценка, часы 12, заметка и платформа сохранены), дубликата нет",
          len(ST["posts"]) == 1 and len(fe) == 1 and fe[0]["rating"] == "понравилось" and fe[0]["hours"] == 12
          and fe[0]["note"] == "Куплена была в Ростове" and fe[0]["platform"] == "switch2" and fe[0]["state"] == "куплена")
    check(f"{n} с оценкой карточка ушла из «Без оценки»", pg.query_selector(sel_c) is None)
    fc(pg, '#vfilters .vchip[data-key="all"]')
    check(f"{n} карточка в сетке перерисована: 12ч, вердикт «понравилось», пометка «с сайта»",
          "12ч" in pg.inner_text(sel_c) and "5ч" not in pg.inner_text(sel_c).replace("12ч", "") and "с сайта" in pg.inner_text(sel_c), repr(pg.inner_text(sel_c)))
    pg.close()
    if W <= 600:
        # касание на телефоне: tap по карточке открывает карточку игры и ставит PTR (фокус после закрытия не остаётся на карточке)
        tctx = br.new_context(viewport={"width": W, "height": hgt}, has_touch=True)
        tctx.route("**/Gaming/watchlist.yaml*", lambda r: r.fulfill(status=200, content_type="text/yaml; charset=utf-8", body=watch_fe.encode()))
        pg = load("library", doc_fe, tctx)
        fc(pg, '#vfilters .vchip[data-key="unrated"]')
        pg.tap(sel_c)
        check(f"{n} касание по карточке открывает карточку", opened(pg, FEW))
        pg.keyboard.press("Escape")
        gone(pg)
        check(f"{n} после закрытия фокус не остался на карточке (касание)", pg.evaluate("!document.activeElement || !document.activeElement.classList.contains('gcard')"))
        pg.close()
        tctx.close()
    ctx.unroute("**/Gaming/watchlist.yaml*")

    # ── три оси: статус · прохождение · оценка (games v2.7.0)
    def it3(title, state, rating=None, progress=None, **kw):
        d = {"title": title, "platform": "switch", "state": state, "rating": rating, "note": None, "deleted": False,
             "updated": "2026-11-05", "added": "2026-11-05"}
        if progress is not None:
            d["progress"] = progress
        d.update(kw)
        return d
    D3 = dict(DOC, items=[
        it3("Portal", "играю", "брошено"),                       # legacy: статус «играю» + оценка «брошено» → куплена, играю, без оценки
        it3("Tetris", "куплена", "брошено"),                     # legacy: оценка «брошено» → прохождение «брошена»
        it3("Celeste", "куплена", None, "пройдена"),
        it3("Undertale", "на-карандаш", "не понравилось", demo=True),   # демо + не понравилось — находится в «Присматриваюсь»
        it3("Metaphor", "не-интересно")])
    pg = load("library", doc=D3)
    t = titles(pg, "#lib-grid .gcard .gt")
    check(f"{n} три оси: библиотека по умолчанию показывает все купленные, в т. ч. без оценки (Portal, Tetris, Fire Emblem-нет в этом doc)",
          all(any(x2 in x for x in t) for x2 in ("Portal", "Tetris", "Celeste", "Hades", "Inside")))
    check(f"{n} три оси: Undertale (демо) и Metaphor (не хочу) — не в библиотеке", not any("Undertale" in x or "Metaphor" in x for x in t))
    capt = lambda k: pg.inner_text(f'#lib-grid .gcard[data-k="{k}"] .g-prog') if pg.query_selector(f'#lib-grid .gcard[data-k="{k}"] .g-prog') else ""
    check(f"{n} три оси: подпись прохождения на плитке (Portal «играю», Tetris «брошена», Celeste «пройдена»), у «не начата» её нет",
          capt("portal") == "играю" and capt("tetris") == "брошена" and capt("celeste") == "пройдена" and capt("hades") == "")
    check(f"{n} три оси: legacy-оценка «брошено» плитки не показывает (бейджа нет)", pg.query_selector('#lib-grid .gcard[data-k="tetris"] .vbadge') is None
          and pg.query_selector('#lib-grid .gcard[data-k="portal"] .vbadge') is None)
    gch = titles(pg, "#gfilters .vchip")
    vch = titles(pg, "#vfilters .vchip")
    check(f"{n} три оси: ряд «Статус» библиотеки — только встречающиеся значения («отложена» нет: таких игр нет), со счётчиками ({gch})",
          [c.split(" (")[0] for c in gch] == ["Все", "не начата", "играю", "пройдена", "брошена"] and all(c.endswith(")") for c in gch)
          and "СТАТУС" in pg.inner_text("#gfilters").upper() and "ПРОХОЖДЕНИЕ" not in pg.inner_text("#gfilters").upper())
    check(f"{n} три оси: «Оценка» — все · встречающиеся оценки · без оценки ({vch})",
          [c.split(" (")[0] for c in vch] == ["Все", "восторг", "понравилось", "нормально", "без оценки"])
    check(f"{n} три оси: в фильтрах нет «Наиграно» и «Вердикт»", pg.query_selector("#hfilters") is None and "Вердикт" not in pg.inner_text(".sc-library"))
    fc(pg, '#gfilters .vchip[data-key="брошена"]')
    check(f"{n} три оси: фильтр «брошена» — только Tetris", titles(pg, "#lib-grid .gcard .gt") == ["Tetris"] or [x.strip() for x in titles(pg, "#lib-grid .gcard .gt")] == ["Tetris"])
    check(f"{n} три оси: число активных фильтров = 1", pg.inner_text("#lib-fbtn .ui-fbtn-n").strip() == "1")
    fc(pg, '#gfilters .vchip[data-key="играю"]')
    check(f"{n} три оси: фильтр «играю» — только Portal", [x.strip() for x in titles(pg, "#lib-grid .gcard .gt")] == ["Portal"])
    fc(pg, '#gfilters .vchip[data-key="не-начата"]')
    t = titles(pg, "#lib-grid .gcard .gt")
    check(f"{n} три оси: фильтр «не начата» — Hades и Celeste-нет (она пройдена)", any("Hades" in x for x in t) and not any("Celeste" in x or "Portal" in x or "Tetris" in x for x in t))
    fc(pg, '#vfilters .vchip[data-key="восторг"]')
    t = titles(pg, "#lib-grid .gcard .gt")
    check(f"{n} три оси: «не начата» + оценка «восторг» — Hades; счётчик фильтров 2", [x.strip() for x in t] == ["Hades"] and pg.inner_text("#lib-fbtn .ui-fbtn-n").strip() == "2")
    fc(pg, '#gfilters .vchip[data-key="all"]')
    fc(pg, '#vfilters .vchip[data-key="unrated"]')
    t = titles(pg, "#lib-grid .gcard .gt")
    check(f"{n} три оси: «без оценки» — Portal и Tetris, не Hades и не Celeste (оценка советника)", any("Portal" in x for x in t) and any("Tetris" in x for x in t)
          and not any("Hades" in x or "Celeste" in x for x in t))
    fc(pg, '#vfilters .vchip[data-key="all"]')
    # карточка legacy-записи: прохождение прочитано, при сохранении уходит в новом виде
    pg.click('#lib-grid .gcard[data-k="tetris"]')
    opened(pg, "Tetris")
    check(f"{n} три оси: карточка Tetris — статус «куплена», прохождение «брошена», оценки нет",
          pg.get_attribute('#gm-own .gm-opt[data-v="куплена"]', "aria-pressed") == "true" and pg.input_value("#gm-progress") == "брошена" and pg.input_value("#gm-rating") == "")
    check(f"{n} три оси: оценка в карточке — «без оценки» + 4 живых, «брошено» нет",
          [e.get_attribute("data-value") for e in pg.query_selector_all('[data-ui-select="gm-rating"] .ui-opt')] == [""] + RATINGS)
    pg.click('#gm-own .gm-opt[data-v="демо"]')
    check(f"{n} три оси: «демо» — «Прохождение» и «Наиграно» на месте", pg.query_selector("#gm-progress") is not None and pg.query_selector("#gm-hours") is not None)
    pg.click('#gm-state .gm-opt[data-v="хочу"]')
    pg.click('#gm-own .gm-opt[data-v="демо"]')
    check(f"{n} три оси: у «хочу» без «демо» блока «Прохождение» нет, пороги есть", pg.query_selector("#gm-progress") is None and "прохождение" not in pg.inner_text("#gm-card").lower()
          and pg.query_selector("#gm-price") is not None)
    pg.click('#gm-own .gm-opt[data-v="куплена"]')
    check(f"{n} три оси: обратно «куплена» — прохождение вернулось с прежним значением", pg.input_value("#gm-progress") == "брошена")
    pg.fill("#gm-note", "ещё раз")
    pg.click('#gm-card [data-act="gm-save"]')
    gone(pg)
    d = last_doc()
    tt = [i for i in d["items"] if i["title"] == "Tetris"][0]
    check(f"{n} три оси: legacy-запись Tetris ушла на сервер в новом виде (куплена, брошена, оценка null)",
          tt["state"] == "куплена" and tt["progress"] == "брошена" and tt["rating"] is None)
    check(f"{n} три оси: legacy Portal в том же файле нормализован (куплена, играю, null)",
          [(i["state"], i["progress"], i["rating"]) for i in d["items"] if i["title"] == "Portal"] == [("куплена", "играю", None)])
    # смена статуса на некупленный → progress в данных null
    pg.click('#lib-grid .gcard[data-k="celeste"]')
    opened(pg, "Celeste")
    pg.click('#gm-own .gm-opt[data-v="куплена"]')            # снять «куплена»: правая группа вернулась на «на карандаше»
    pg.click('#gm-state .gm-opt[data-v="на-карандаш"]')
    pg.click('#gm-card [data-act="gm-save"]')
    gone(pg)
    ce = [i for i in last_doc()["items"] if i["title"] == "Celeste"][0]
    check(f"{n} три оси: Celeste → «на карандаше»: progress null, статус записан", ce["state"] == "на-карандаш" and ce["progress"] is None)
    pg.close()

    # «Присматриваюсь»: статус и оценка; «демо + не понравилось» находится
    pg = load("watch", doc=D3)
    check(f"{n} три оси: подпись состояния «не интересно» везде — «не хочу»",
          "Не хочу" in pg.inner_text("#wfilters") and "интересно" not in pg.inner_text("#wfilters").lower())
    check(f"{n} три оси: у «Присматриваюсь» фильтра «Оценка» нет (оценка — для купленных)", pg.query_selector("#wrfilters") is None)
    fc(pg, '#w-demo-chip')
    check(f"{n} три оси: переключатель «Демо» находит Undertale", [x.strip() for x in titles(pg, ".sc-watch .wcard .gt")] == ["Undertale"])
    fc(pg, '#w-demo-chip')
    pg.close()

    check(f"{n} ошибок JS нет", not errs, str(errs[:3]))
    ctx.close()


def run(name, br):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "Gaming").mkdir()
    for f, txt in (("taste-profile.yaml", TASTE), ("library_full.yaml", LIBFULL), ("watchlist.yaml", WATCH),
                   ("eshop-prices.json", json.dumps(PRICES))):
        (tmp / "Gaming" / f).write_text(txt, encoding="utf-8")
    os.symlink(REPO / "tools", tmp / "tools")
    srv, base = serve(H, directory=tmp)
    try:
        scenario(br, base, 1280, 900)
        scenario(br, base, 390, 844)
    finally:
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    per_engine(run, engines=("chromium",))
    print(f"games_card: {check.passed} OK, {check.failed} FAIL")
    sys.exit(1 if check.failed else 0)
