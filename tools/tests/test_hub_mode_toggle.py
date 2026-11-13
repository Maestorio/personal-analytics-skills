#!/usr/bin/env python3
"""Режим сайта «с ИИ / без ИИ» (ui-kit 1.67.0) на хабе — НАСТОЯЩИЙ Chromium (playwright).

Правило: атрибут data-noai на <html> ставится синхронно из кэша localStorage["hub-noai"], команды для Claude
(.ui-claude-cmd, .noai-hide) при нём скрыты, кнопка «Режим» в шапке хаба переключает режим через подтверждение
(с ИИ → без ИИ) или окно «Вернуться к ИИ» (без ИИ → с ИИ), событие "ui-noai" сообщает страницам о смене.

Что проверяется:
  1. кэш off до загрузки: data-noai есть, кнопка «Режим: без ИИ» с классом is-off, .ui-claude-cmd и .noai-hide
     скрыты (и видны после снятия атрибута), renderReports на месте, ошибок JS нет;
  2. без кэша: «Режим: с ИИ», атрибута нет; клик → .ui-confirm про выключение ИИ; «Оставить» закрывает без смены;
  3. кэш off: клик → окно #ui-noai-return «Вернуться к ИИ»; без API — текст про недоступность или «момент
     выключения: «Нет входа» (кэш без токена), «не записал» или «не ответил»; noai-return-close закрывает окно;
  4. uiAiModeApply("off"/"on") ставит/снимает атрибут и кэш, слушатель "ui-noai" получает detail;
  5. поддельный API: GET ../api/hub/settings отдаёт ai_mode off → при пустом кэше и токене hub-auth атрибут
     появляется, кэш становится "off";
  6. ошибок JS в консоли нет.

Запрос ../api/hub/* без поддельного API → 404, ui-kit остаётся на кэше. Synology не нужен.

Запуск:
    python3 tools/tests/test_hub_mode_toggle.py
Требует playwright; движок, которого нет, — честный пропуск.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _pages_stand import Checker, Quiet, per_engine, serve, settle  # noqa: E402

check = Checker()

try:
    from playwright.sync_api import sync_playwright  # noqa: F401
except ImportError:
    print("hub_mode_toggle: пропуск — нет playwright")
    sys.exit(0)

TOOLS = HERE.parent
_, BASE = serve(directory=TOOLS, key="hub-mode-plain")
HUB = BASE + "/hub.html"


class FakeApi(Quiet):
    """Статика tools/ + GET /api/hub/settings с ai_mode off."""
    def do_GET(self):
        if self.path.split("?")[0] == "/api/hub/settings":
            body = json.dumps({"hash": "h1", "settings": {"schema": "hub-settings@1", "ai_mode": "off",
                                                          "off_since": "2026-11-01T10:00:00+03:00",
                                                          "by": "site", "note": None}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


_, FAKE = serve(handler=FakeApi, directory=TOOLS, key="hub-mode-fake")

VIS = "(sel) => { const e = document.querySelector(sel); return !!e && getComputedStyle(e).display !== 'none'; }"
INJECT = """() => { const b = document.createElement('button'); b.className = 'ui-claude-cmd'; b.textContent = 'cmd'; document.body.appendChild(b);
  const d = document.createElement('div'); d.className = 'noai-hide'; d.textContent = 'hint'; document.body.appendChild(d); }"""


def open_hub(browser, init, url=HUB):
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    ctx.add_init_script(init)
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "404" not in m.text else None)
    pg.goto(url)
    settle(pg, "!!document.querySelector('[data-act=\"ai-mode\"]')")
    return ctx, pg, errs


def run(eng, browser):
    if eng != "chromium":
        return
    # 1. кэш off
    ctx, pg, errs = open_hub(browser, "localStorage.setItem('hub-noai','off');")
    check("1: у <html> есть data-noai", pg.evaluate("document.documentElement.hasAttribute('data-noai')"))
    check("1: кнопка «Режим: без ИИ» в шапке", pg.locator('[data-act="ai-mode"]').first.inner_text().strip().endswith("Режим: без ИИ"))
    check("1: у кнопки класс is-off", pg.evaluate("document.querySelector('[data-act=\"ai-mode\"]').classList.contains('is-off')"))
    pg.evaluate(INJECT)
    check("1: .ui-claude-cmd скрыт при data-noai", not pg.evaluate(VIS, ".ui-claude-cmd"))
    check("1: .noai-hide скрыт при data-noai", not pg.evaluate(VIS, ".noai-hide"))
    pg.evaluate("document.documentElement.removeAttribute('data-noai')")
    check("1: .ui-claude-cmd виден без атрибута", pg.evaluate(VIS, ".ui-claude-cmd"))
    check("1: .noai-hide виден без атрибута", pg.evaluate(VIS, ".noai-hide"))
    check("1: renderReports есть в коде хаба (внутри оболочки, снаружи не виден)", "function renderReports(" in pg.content())
    check(f"1: ошибок JS нет {errs[:2]}", not errs)
    ctx.close()

    # 2. режим on: подтверждение выключения
    ctx, pg, errs = open_hub(browser, "try{localStorage.removeItem('hub-noai')}catch(e){}")
    check("2: подпись «Режим: с ИИ»", pg.locator('[data-act="ai-mode"]').first.inner_text().strip().endswith("Режим: с ИИ"))
    check("2: атрибута нет", not pg.evaluate("document.documentElement.hasAttribute('data-noai')"))
    pg.locator('[data-act="ai-mode"]').first.click()
    pg.wait_for_selector(".ui-confirm", timeout=5000)
    check("2: .ui-confirm с заголовком про выключение ИИ", "Выключить ИИ" in pg.locator(".ui-confirm").first.inner_text())
    check("2: подтверждение появляется с анимацией ui-kit (.ui-confirm.enter)", pg.locator(".ui-confirm.enter").count() == 1)
    pg.locator(".ui-confirm-no").first.click()
    settle(pg, "!document.querySelector('.ui-confirm')")
    check("2: «Оставить» закрывает окно", pg.locator(".ui-confirm").count() == 0)
    check("2: атрибут не появился", not pg.evaluate("document.documentElement.hasAttribute('data-noai')"))
    check(f"2: ошибок JS нет {errs[:2]}", not errs)
    ctx.close()

    # 3. кэш off: окно возврата
    ctx, pg, errs = open_hub(browser, "localStorage.setItem('hub-noai','off');")
    pg.locator('[data-act="ai-mode"]').first.click()
    pg.wait_for_selector("#ui-noai-return .ui-modal", state="attached", timeout=5000)
    txt = pg.locator("#ui-noai-return").inner_text()
    check("3: окно «Вернуться к ИИ»", "Вернуться к ИИ" in txt)
    settle(pg, "!document.querySelector('#ui-noai-return .ui-state')?.textContent.includes('Считаю')")
    txt = pg.locator("#ui-noai-return").inner_text()
    check("3: без API и без входа — «Нет входа» / без момента выключения — «не записал» / сеть — «не ответил»",
          "Нет входа" in txt or "не записал" in txt or "не ответил" in txt)
    check("3: окно появляется с анимацией ui-kit (.ui-modal.enter)", pg.locator("#ui-noai-return .ui-modal.enter").count() == 1)
    check("3: фокус на крестике окна", pg.evaluate("document.activeElement && document.activeElement.classList.contains('ui-modal-x')"))
    pg.locator('#ui-noai-return button[data-act="noai-return-close"]').first.click()
    check("3: noai-return-close закрывает окно", pg.locator("#ui-noai-return").count() == 0)
    pg.locator("[data-act='ai-mode']").first.click()
    pg.wait_for_selector("#ui-noai-return .ui-modal", state="attached", timeout=5000)
    pg.keyboard.press("Escape")
    settle(pg, "!document.querySelector('#ui-noai-return')")
    check("3: Esc закрывает окно возврата", pg.locator("#ui-noai-return").count() == 0)
    check("3: после Esc фокус вернулся на кнопку режима", pg.evaluate("document.activeElement && document.activeElement.getAttribute('data-act') === 'ai-mode'"))
    check(f"3: ошибок JS нет {errs[:2]}", not errs)
    ctx.close()

    # 4. событие
    ctx, pg, errs = open_hub(browser, "try{localStorage.removeItem('hub-noai')}catch(e){}")
    pg.evaluate("window.__ev = []; document.addEventListener('ui-noai', e => window.__ev.push(e.detail));")
    pg.evaluate("uiAiModeApply('off')")
    check("4: off ставит data-noai", pg.evaluate("document.documentElement.hasAttribute('data-noai')"))
    check("4: кэш hub-noai = off", pg.evaluate("localStorage.getItem('hub-noai')") == "off")
    check("4: подпись кнопки сменилась", pg.locator('[data-noai-lbl]').first.inner_text().strip() == "Режим: без ИИ")
    pg.evaluate("uiAiModeApply('on')")
    check("4: on снимает data-noai", not pg.evaluate("document.documentElement.hasAttribute('data-noai')"))
    check("4: слушатель ui-noai получил off, on", pg.evaluate("window.__ev") == ["off", "on"])
    check(f"4: ошибок JS нет {errs[:2]}", not errs)
    ctx.close()

    # 5. поддельный API
    ctx, pg, errs = open_hub(browser, "localStorage.setItem('hub-auth','dGVzdDp0ZXN0'); localStorage.removeItem('hub-noai');",
                             FAKE + "/hub.html")
    settle(pg, "document.documentElement.hasAttribute('data-noai')")
    check("5: GET settings off → data-noai появился", pg.evaluate("document.documentElement.hasAttribute('data-noai')"))
    check("5: кэш стал off", pg.evaluate("localStorage.getItem('hub-noai')") == "off")
    check(f"5: ошибок JS нет {errs[:2]}", not errs)
    ctx.close()


per_engine(run, engines=("chromium",))
print(f"\nhub_mode_toggle: {check.passed} passed, {check.failed} failed")
sys.exit(1 if check.failed else 0)
