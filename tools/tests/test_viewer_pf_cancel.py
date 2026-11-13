#!/usr/bin/env python3
"""Вьюер 3.121.0: «Остановить сборку» в разделе «Загрузки» — настоящий Chromium, ответы /api/pf/* подменены.

Контракты (1400 и 390, светлая и тёмная тема):
  1. Кнопка «Остановить сборку» видна только пока статус running; до запуска и после результата её нет.
  2. Нажатие не шлёт запрос: кнопка превращается в «Точно остановить? · Да · Нет» (без confirm()); «Нет» возвращает кнопку, запроса нет.
  3. «Да» → POST /api/pf/cancel {run}; после ответа — «Сборка остановлена, ничего не сохранено», кнопки «Сохранить» нет, и можно
     запустить новую сборку (второй POST /api/pf/build).
  4. Подтверждение переживает перерисовку опроса статуса (опрос раз в 3 с). Ответ 409 на отмену — понятный текст рядом с кнопкой.
  5. Зона нажатия кнопок ≥ 40px, страница не шире экрана, ошибок JS нет.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_pf_cancel.py
"""
import json
import os
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
    print("viewer_pf_cancel: пропуск — нет playwright")
    sys.exit(0)


def main():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "Portfolio/integrated-views").mkdir(parents=True)
    (tmp / "Portfolio/integrated-views/integrated-view-2026-10-01.md").write_text("---\n---\n", encoding="utf-8")
    os.symlink(REPO / "tools", tmp / "tools")
    up = tmp / "up"
    up.mkdir()
    (up / "trades_portfolio_707160-49.xlsx").write_bytes(b"PK\x03\x04trades")
    httpd = serve(directory=tmp)[0]   # _pages_stand: очередь 128, keep-alive
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    with sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception:  # noqa: BLE001
            print("viewer_pf_cancel: пропуск — нет chromium")
            return 0
        for width, theme in ((1400, "light"), (390, "light"), (1400, "dark"), (390, "dark")):
            tag = f"[{width} {theme}] "
            sent = []
            st = {"state": None, "cancel_status": 200}

            def api(route):
                req = route.request
                path = req.url.split("/api/pf/")[1]
                js = lambda code, o: route.fulfill(status=code, content_type="application/json", body=json.dumps(o))  # noqa: E731
                if path.startswith("build"):
                    sent.append("build")
                    st["state"] = "running"
                    return js(202, {"run": f"r{sent.count('build')}"})
                if path.startswith("cancel"):
                    sent.append(("cancel", json.loads(req.post_data)))
                    if st["cancel_status"] == 200:
                        st["state"] = "cancelled"
                        return js(200, {"run": "r1", "state": "cancelled"})
                    return js(409, {"error": "сборка уже закончилась — остановить нечего"})
                if path.startswith("status"):
                    if "run=" not in path or not st["state"]:
                        return js(404, {"error": "сборок ещё не было"})
                    o = {"run": path.split("run=")[1].split("&")[0], "state": st["state"], "started": "2026-10-30T22:10:00+03:00",
                         "files": {"trades": "trades_portfolio_707160-49.xlsx"}}
                    if st["state"] == "cancelled":
                        o["cancelled_at"] = "2026-10-30T22:11:00"
                    return js(200, o)
                return route.fulfill(status=404, body="{}")

            ctx = br.new_context(viewport={"width": width, "height": 900}, color_scheme=theme)
            page = ctx.new_page()
            errs, dialogs = [], []
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.on("dialog", lambda d: (dialogs.append(d.type), d.dismiss()))
            page.route("**/api/pf/**", api)
            page.add_init_script(f"try {{ localStorage.setItem('hub-theme', '{theme}'); }} catch (e) {{}}")   # тема вьюера — hub-theme, не prefers-color-scheme
            page.add_init_script("window.setTimeout = ((st) => (fn, ms, ...a) => st(fn, Math.min(ms || 0, 50), ...a))(window.setTimeout)")
            page.goto(base + "/tools/portfolio-integrated-viewer.html")
            page.wait_for_selector("#btn-pfbuild:not([hidden])", timeout=20000)
            page.click("#btn-pfbuild")
            page.wait_for_selector("#pf-go", timeout=5000)
            check(tag + "до запуска кнопки нет", page.query_selector("#pf-cancel-go") is None)
            page.set_input_files("#pf-trades", str(up / "trades_portfolio_707160-49.xlsx"))
            page.click("#pf-go")
            page.wait_for_selector("#pf-cancel-go", timeout=5000)
            btn = page.locator("#pf-cancel-go")
            check(tag + "во время сборки кнопка «Остановить сборку» видна", btn.inner_text() == "Остановить сборку" and btn.is_visible())
            check(tag + "зона нажатия ≥ 40px", btn.evaluate("e => e.getBoundingClientRect().height") >= 39.5)
            btn.click()
            page.wait_for_selector("#pf-cancel-yes", timeout=3000)
            page.wait_for_timeout(300)                   # несколько перерисовок опроса — подтверждение не слетает
            txt = page.inner_text("#pf-cancel")
            check(tag + f"подтверждение на месте: «Точно остановить? Да Нет» ({txt!r})",
                  "Точно остановить?" in txt and page.inner_text("#pf-cancel-yes") == "Да" and page.inner_text("#pf-cancel-no") == "Нет")
            check(tag + "запрос отмены ещё не ушёл, confirm() нет", ("cancel" not in [x[0] for x in sent if isinstance(x, tuple)]) and not dialogs)
            check(tag + "кнопки подтверждения ≥ 40px", page.locator("#pf-cancel-yes").evaluate("e => e.getBoundingClientRect().height") >= 39.5
                  and page.locator("#pf-cancel-no").evaluate("e => e.getBoundingClientRect().height") >= 39.5)
            page.click("#pf-cancel-no")
            page.wait_for_selector("#pf-cancel-go", timeout=3000)
            check(tag + "«Нет» возвращает кнопку, запроса нет", not any(isinstance(x, tuple) for x in sent))
            # 409 на отмену
            st["cancel_status"] = 409
            page.click("#pf-cancel-go")
            page.click("#pf-cancel-yes")
            page.wait_for_selector("#pf-cancel-err", timeout=3000)
            check(tag + "409: понятный текст рядом с кнопкой", "остановить нечего" in page.inner_text("#pf-cancel-err"))
            st["cancel_status"] = 200
            page.click("#pf-cancel-go") if page.query_selector("#pf-cancel-go") else None
            page.click("#pf-cancel-yes")
            page.wait_for_selector("#pf-cancelled", timeout=5000)
            check(tag + "POST /api/pf/cancel несёт run", ("cancel", {"run": "r1"}) in sent)
            res = page.inner_text("#pf-result")
            check(tag + f"строка «Сборка остановлена, ничего не сохранено» ({res[:80]!r})",
                  "Сборка остановлена, ничего не сохранено" in res and page.query_selector("#pf-save") is None
                  and page.query_selector("#pf-cancel-go") is None)
            check(tag + "не шире экрана", page.evaluate(f"document.documentElement.scrollWidth <= {width}"))
            page.click("#pf-go")
            page.wait_for_selector("#pf-cancel-go", timeout=5000)
            check(tag + "после остановки можно запустить новую сборку", sent.count("build") == 2)
            check(tag + f"ошибок JS нет ({errs[:2]}), диалогов нет", not errs and not dialogs)
            ctx.close()
        br.close()
    httpd.shutdown()
    httpd.server_close()
    print(f"viewer_pf_cancel: {passed} OK, {failed} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
