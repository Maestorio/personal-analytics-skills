#!/usr/bin/env python3
"""Цены US eShop на экране «Присматриваюсь» (games.html, API-1 PR-9) — прогон настоящим браузером.

  1. Карточка с nsuid_us показывает цену из eshop-prices.json: скидка — новая цена, старая
     зачёркнута, «−N%», «до DD.MM»; порог — бейдж «порог $X выполнен»; предзаказ — бейдж;
     not_found — «нет в US eShop»; запись без nsuid_us — без строки цены.
  2. Строка над списком: время цен; файл старше суток — «устарели»; сбой загрузки — «не удалось».
  3. «Обновить цены»: ответ 429 → «можно снова через N мин» (страница не падает, кнопка снова
     активна).
  4. На 390 px страница не шире экрана.
  5. Чип «Со скидкой» (v1.31): счёт по sale_usd, фильтр сочетается со статусом, снимается.
Данные синтетические, во временной папке. Требует playwright + chromium; без них — пропуск.
Запуск: python3 tools/tests/test_games_eshop_layout.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import Quiet, serve  # noqa: E402  (стенд — _pages_stand, keep-alive)
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
    print("games_eshop_layout: пропуск — нет playwright")
    sys.exit(0)

WATCH = """schema_version: 1.0
updated: 2026-10-21
items:
  - title: "Undertale"
    status: хочу
    platform: switch
    nsuid_us: "70010000009921"
    added: 2026-10-20
  - title: "Metaphor"
    status: хочу
    nsuid_us: "70010000105915"
    added: 2026-10-19
  - title: "Пропала"
    status: на-карандаш
    nsuid_us: "70010000000001"
    added: 2026-10-18
  - title: "Без nsuid"
    status: хочу
    added: 2026-10-17
"""


def prices(fetched_at, status="ok"):
    return {"schema": "eshop-prices@1", "fetched_at": fetched_at, "attempt_at": "2026-10-22T08:30:00+03:00"
            if status != "ok" else None, "status": status, "error": None, "items": [
                {"title": "Undertale", "nsuid_us": "70010000009921", "sales_status": "onsale", "regular_usd": 14.99,
                 "sale_usd": 9.89, "discount_pct": 34, "sale_end": "2026-11-01T15:59:59Z", "price_usd": 9.89,
                 "price_target_usd": 10.0, "target_met": True},
                {"title": "Metaphor", "nsuid_us": "70010000105915", "sales_status": "preorder", "regular_usd": 39.99,
                 "sale_usd": None, "discount_pct": None, "sale_end": None, "price_usd": 39.99,
                 "price_target_usd": None, "discount_target_pct": 50, "target_met": False},
                {"title": "Пропала", "nsuid_us": "70010000000001", "sales_status": "not_found", "regular_usd": None,
                 "sale_usd": None, "discount_pct": None, "sale_end": None, "price_usd": None,
                 "price_target_usd": None, "target_met": False}], "skipped": []}


POST = {"code": 429, "then": None}    # then(): что сервер «загрузил» перед ответом 200


class H(Quiet):   # раздача папки _pages_stand: без ложных 304 при keep-alive
    def log_message(self, *a):
        pass

    def end_headers(self):
        if self.command == "GET":              # как Caddy: файл цен браузер вправе держать в кеше
            self.send_header("Cache-Control", "max-age=3600")
        super().end_headers()

    def do_POST(self):
        if POST["then"]:
            POST["then"]()
        b = json.dumps({"ok": POST["code"] == 200, "retry_after": 420}).encode()
        self.send_response(POST["code"])
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


def run(page, base, root, prices_doc):
    (root / "Gaming/eshop-prices.json").write_text(json.dumps(prices_doc), encoding="utf-8")
    page.goto("about:blank")                   # с …#sale на тот же адрес — иначе лишь смена якоря
    page.goto(base + "/tools/games.html")
    page.wait_for_function("document.querySelectorAll('.sc-watch .w-price').length >= 3", timeout=15000)


def main():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "Gaming").mkdir()
    (tmp / "Gaming/watchlist.yaml").write_text(WATCH, encoding="utf-8")
    os.symlink(REPO / "tools", tmp / "tools")
    httpd = serve(H, directory=tmp)[0]   # _pages_stand: очередь 128, keep-alive
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    with sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception:  # noqa: BLE001
            print("games_eshop_layout: пропуск — нет chromium")
            return 0
        page = br.new_page(viewport={"width": 390, "height": 844})
        page.add_init_script("sessionStorage.setItem('games-screen', 'watch')")
        run(page, base, tmp, prices("2099-01-01T08:30:00+03:00"))
        cards = {c.query_selector(".gt").inner_text(): c.inner_text() for c in page.query_selector_all(".sc-watch .wcard")}
        u = cards.get("Undertale", "")
        check("скидка: новая цена, %, до", "$9.89" in u and "$14.99" in u and "−34%" in u and "до 01.11" in u)
        check("порог выполнен", "порог $10.00 выполнен" in u)
        check("порог в процентах на карточке", "порог −50%" in cards.get("Metaphor", "")
              and "выполнен" not in cards.get("Metaphor", ""))
        check("предзаказ с ценой", "$39.99" in cards.get("Metaphor", "") and "предзаказ" in cards.get("Metaphor", ""))
        check("not_found", "нет в US eShop" in cards.get("Пропала", ""))
        check("без nsuid — без цены", "$" not in cards.get("Без nsuid", "x$"))
        bar = page.inner_text("#eshop-bar")
        check("строка времени", "Цены US eShop на 01.01 08:30" in bar and "устарели" not in bar)
        page.click("#eshop-refresh")
        page.wait_for_function("document.getElementById('eshop-msg').textContent.indexOf('через') >= 0", timeout=5000)
        check("429 → через 7 мин", "через 7 мин" in page.inner_text("#eshop-msg"))
        check("кнопка снова активна", page.is_enabled("#eshop-refresh"))
        check("не шире экрана", page.evaluate("document.documentElement.scrollWidth") <= 390)
        page.click("#w-fbtn")                       # на 390 px чипы фильтров живут в окне «Фильтры»
        page.wait_for_selector("#gm-fwin .ui-modal-box")
        chip = page.query_selector("#w-sale-chip")
        check("чип «Со скидкой» виден, счёт 1", chip.is_visible() and chip.inner_text() == "Со скидкой (1)")
        chip.click()
        titles = [c.inner_text() for c in page.query_selector_all(".sc-watch .wcard .gt")]
        check("со скидкой — только Undertale", titles == ["Undertale"])
        page.click('#wfilters .vchip[data-key="pencil"]')
        check("статус + скидка сочетаются (на карандаше без скидок — пусто)",
              page.query_selector_all(".sc-watch .wcard") == [] and "on" in chip.get_attribute("class"))
        chip.click()
        check("снятие фильтра возвращает список", len(page.query_selector_all(".sc-watch .wcard")) == 1)
        page.click('#gm-fwin .ui-modal-save')

        # «Обновить цены» → 200: новое время сразу, без перезагрузки (26.10: до v1.36 оставалось
        # старое — файл брался из кеша браузера по тому же адресу)
        POST["code"] = 200
        POST["then"] = lambda: (tmp / "Gaming/eshop-prices.json").write_text(
            json.dumps(prices("2099-01-01T11:25:00+03:00")), encoding="utf-8")
        page.wait_for_timeout(50)
        page.click("#eshop-refresh")
        try:
            page.wait_for_function("document.getElementById('eshop-when').textContent.indexOf('11:25') >= 0",
                                   timeout=5000)
        except Exception:  # noqa: BLE001
            pass
        check("после обновления — новое время без перезагрузки", "на 01.01 11:25" in page.inner_text("#eshop-bar"))
        POST["code"], POST["then"] = 429, None

        # ссылка из push «Скидки на игры»: сразу «Присматриваюсь» с включённым «Со скидкой»
        page.evaluate("sessionStorage.setItem('games-screen', 'overview')")
        page.goto("about:blank")
        page.goto(base + "/tools/games.html#sale")
        page.wait_for_function("document.querySelectorAll('.sc-watch .w-price').length >= 1", timeout=15000)
        titles = [c.inner_text() for c in page.query_selector_all(".sc-watch .wcard .gt")]
        check("#sale — экран «Присматриваюсь», только со скидкой",
              page.evaluate("document.body.getAttribute('data-screen')") == "watch" and titles == ["Undertale"]
              and "on" in page.get_attribute("#w-sale-chip", "class"))

        page = br.new_context(viewport={"width": 390, "height": 844}).new_page()   # без кеша прошлых загрузок
        page.add_init_script("sessionStorage.setItem('games-screen', 'watch')")
        run(page, base, tmp, prices("2026-10-20T08:30:00+03:00", status="unavailable"))
        bar = page.inner_text("#eshop-bar")
        check("старые цены помечены", "устарели" in bar and "не удалось" in bar)
        br.close()
    httpd.shutdown()
    httpd.server_close()
    print(f"games_eshop_layout: {passed} OK, {failed} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
