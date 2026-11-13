#!/usr/bin/env python3
"""Блок «Выгрузка ZenMoney» вкладки «Загрузка» страницы money.html v2.6.1 — прогон настоящим браузером (playwright, Chromium, 1280 и 390).

Правило: загрузка CSV → отчёт zm-csv-report@1 → «Записать» только без стопов и после подтверждения
(docs/zenmoney/csv-site.md). Стенд — статика tools/ и поддельные /api/zm/csv-state|csv|csv-report|csv-apply
(тело каждого POST запоминается). Проверяется:
  1. Вкладка «Загрузка» (ключ csv) последняя в переключателе (1280) и в нижней навигации (390), вкладки stmt нет; state без выгрузок —
     «выгрузок ещё не было»; незавершённая загрузка — список с «Показать отчёт».
  2. aux_ok=false → жёлтая плашка «Пересчёт месяцев недоступен».
  3. Файл (set_input_files) → POST /api/zm/csv {name, b64 = содержимое} → автоматически POST csv-report {id}
     → отчёт: полнота, diff (по месяцам, потерянные теги красным, образцы в <details>), «К записи», стопы,
     вспомогательные файлы (мест без словаря).
  4. Ошибка сервера (неверные колонки) показана текстом.
  5. Отчёт со стопами: «Записать» disabled, рядом «Устрани причины…».
  6. Отчёт без стопов: «Записать» → подтверждение ui-kit с «N месяцев и M поездок» → «Отмена» не шлёт ничего;
     «Записать» → POST csv-apply {id, confirm:true} → «записано: …», данные страницы перечитаны.
  7. data-noai: подсказки noai-hide скрыты. 390 px не шире экрана, ошибок JS нет.
  10. money v2.6.1 (часть В): набранное в «что это» и датах поездки переживает перерисовку страницы — ошибка в другой строке,
     «укажи даты», событие ui-theme; фокус и позиция курсора сохраняются.
  8. money v2.4.0: в отчёте у месяца к записи — кандидаты «Разовая» (без «что это» — ошибка и ни одного POST; с текстом —
     POST /api/zm/rule {id, month, date, account, amount, payee, note}; отметка сайта со «Снять» → POST {remove, rule_id});
     блок «Новые поездки»: даты правятся, «Добавить поездку» → POST /api/zm/trip {id, name, start, end}.
  9. «Качество учёта» без аудита скилла, но с записью в site-audit.json: пометка «аудит сайта» с подсказкой, список проверок
     с числами; есть оба — аудит скилла, пометки нет, одна строка «сайт при загрузке отметил: N»; «Обзор»: месяц с итогами
     и аудитом сайта — «закрыт по сайту» без «закрыт не полностью»; без аудита сайта — прежняя плашка.
Данные синтетические. Без playwright или chromium — пропуск.
Запуск: python3 tools/tests/test_money_csv_page.py
"""
import base64
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import Checker, Quiet, per_engine, serve  # noqa: E402

try:
    import playwright.sync_api  # noqa: F401
except ImportError:
    print("money_csv_page: пропуск — нет playwright")
    sys.exit(0)

check = Checker()
CSV = "date;categoryName;payee;outcomeAccountName;outcome\n2026-10-03;Еда;Магазин;Карта;100\n".encode()
REPORT = {
    "schema": "zm-csv-report@1", "id": "2026-11-09-1a2b3c4d", "sha256": "ab", "built_at": "2026-11-09T21:40:00+03:00",
    "rows": 12345, "first": "2020-01-03", "last": "2026-11-08",
    "completeness": {"ok": True, "stops": [], "warnings": ["последняя операция 2026-11-08 — месяц 2026-11 не закончен, к записи не идёт"],
                     "prev_rows": 12290, "months_missing": []},
    "diff": {"prev": "last.csv", "added": 61, "deleted": 6, "changed": 12,
             "lost_trip_tags": [{"date": "2026-09-05", "amount": "-500", "account": "Карта", "payee": "Кафе", "tag": "#Грузия’26"}],
             "by_month": {"2026-10": {"added": 55, "deleted": 2, "changed": 3}, "2026-09": {"added": 6, "deleted": 4, "changed": 9}},
             "samples": {"deleted": [{"date": "2026-10-02", "amount": "-10", "account": "Карта", "payee": "УдалённоеМесто"}],
                         "changed": [{"date": "2026-10-04", "amount": "-20", "account": "Карта", "payee": "ИзменённоеМесто"}]}},
    "months": [{"month": "2026-10", "action": "replace", "explained": True, "changes": ["expense_rub: было 123 456, CSV 121 000"], "ops_changed_after": 3},
               {"month": "2026-09", "action": "same", "explained": True, "changes": []}],
    "trips": [{"name": "#Грузия’26", "action": "replace", "changes": ["spent_rub: было 100, CSV 120"]}],
    "checks": [{"id": "P1", "cls": "hint", "month": "2026-10", "text": "место обычно в другой категории", "count": 7,
                "sample": ["2026-10-03 · Кафе: обычно «Кафе», записано «Одежда»"]}],
    "stops": [], "aux": {"ok": True, "payee_unmapped": 7, "missing": []}}
STOP_REPORT = dict(REPORT, id="2026-11-09-stopstop", stops=["потерян тег поездки у 4 операций", "необъяснимое расхождение 2026-07"])
CAND = {"date": "2026-10-15", "account": "Карта", "amount": 50000, "rub": 50000, "category": "Покупки", "payee": "Магазин-Х", "comment": ""}
REPORT_EDIT = dict(REPORT, months=[dict(REPORT["months"][0], candidates=[CAND], site_rules=[]), REPORT["months"][1]],
                   new_trips=[{"name": "#Тбилиси’26", "ops": 2, "first": "2026-09-05", "last": "2026-09-07", "start": "2026-09-05", "end": "2026-09-07"}])
AFTER_RULE = dict(REPORT_EDIT, months=[dict(REPORT["months"][0], candidates=[], site_rules=[
    {"id": "site-0123456789ab", "note": "ремонт", "date": "2026-10-15", "account": "Карта", "amount": 50000}]), REPORT["months"][1]],
    rule={"id": "site-0123456789ab", "action": "added"})
AFTER_REMOVE = dict(REPORT_EDIT, rule={"id": "site-0123456789ab", "action": "removed"})
AFTER_TRIP = dict(REPORT_EDIT, new_trips=[], trip={"name": "#Тбилиси’26", "id": "site:#Тбилиси’26"})
ST = {"state": {"last": None, "incoming": [], "aux_ok": True}, "posts": [], "csv_code": 200, "report": REPORT, "audit_gets": 0,
      "audit": {}, "rule_replies": [], "trip_reply": None}


class H(Quiet):
    def _j(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/zm/csv-state"):
            return self._j(200, ST["state"])
        if "/ZenMoney/audit/" in self.path:
            ST["audit_gets"] += 1
            name = self.path.split("/ZenMoney/audit/")[1].split("?")[0]
            return self._j(200, ST["audit"][name]) if name in ST["audit"] else self._j(404, {})
        return super().do_GET()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        ST["posts"].append((self.path.split("?")[0], body))
        if self.path.startswith("/api/zm/rule"):
            return self._j(200, ST["rule_replies"].pop(0))
        if self.path.startswith("/api/zm/trip"):
            return self._j(200, ST["trip_reply"])
        if self.path.startswith("/api/zm/csv-report"):
            return self._j(200, ST["report"])
        if self.path.startswith("/api/zm/csv-apply"):
            return self._j(200, {"written": {"months": ["2026-10"], "trips": ["#Грузия’26"]}, "versions": ["v1"]})
        if self.path.startswith("/api/zm/csv"):
            if ST["csv_code"] != 200:
                return self._j(400, {"error": "нет колонки outcomeAccountName"})
            return self._j(200, {"id": ST["report"]["id"], "rows": 12345, "first": "2020-01-03", "last": "2026-11-08", "sha256": "ab"})
        return self._j(404, {})


def posts(path):
    return [b for p, b in ST["posts"] if p == path]


def scenario(br, base, W, hgt):
    n = f"{W}px"
    ctx = br.new_context(viewport={"width": W, "height": hgt})
    ctx.add_init_script("localStorage.setItem('hub-auth','dGVzdDp0ZXN0'); localStorage.setItem('money-tab','csv');")
    errs = []

    def load(state=None, report=None):
        ST.update(state=state or {"last": None, "incoming": [], "aux_ok": True}, report=report or REPORT, csv_code=200, audit_gets=0,
                  audit={})
        ST["posts"].clear()
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
        pg.goto(base + "/tools/money.html")
        pg.wait_for_selector("#csv-state", timeout=15000)
        return pg

    def upload(pg):
        pg.set_input_files("#csv-file", files=[{"name": "zen_2026.csv", "mimeType": "text/csv", "buffer": CSV}])
        pg.click("#csv-pick")

    # 1. вкладка, состояние без выгрузок
    pg = load()
    tabs = pg.evaluate("[...document.querySelectorAll('[data-act=\"tab\"]')].filter(e => e.offsetParent).map(e => e.getAttribute('data-v'))")
    labels = pg.evaluate("[...document.querySelectorAll('[data-act=\"tab\"]')].filter(e => e.offsetParent).map(e => e.textContent.trim())")
    check(f"{n} вкладка «Загрузка» (ключ csv) последняя, подпись «Загрузка», вкладки stmt нет ({tabs} {labels})",
          tabs and tabs[-1] == "csv" and "stmt" not in tabs and "Загрузка" in labels and "Выгрузка" not in labels)
    check(f"{n} в «Загрузке» первым блоком выгрузка ZenMoney, вторым выписка банка",
          pg.evaluate("[...document.querySelectorAll('main h2.ui-h2')].map(e => e.textContent.trim()).slice(0, 2)") == ["Выгрузка ZenMoney (CSV)", "Выписка банка (CSV, XLSX)"])
    check(f"{n} state без выгрузок", "выгрузок ещё не было" in pg.inner_text("#csv-state"))
    check(f"{n} aux_ok — жёлтой плашки нет", pg.query_selector("#csv-aux-warn") is None)
    check(f"{n} «Записать» нет до отчёта", pg.query_selector("#csv-apply") is None)
    check(f"{n} слот: «обязательно», «Файл не выбран», кнопка «Проверить выгрузку» неактивна без файла",
          "обязательно" in pg.inner_text("#csv-slot-host") and "Файл не выбран" in pg.inner_text("#csv-slot-host")
          and "Проверить выгрузку" in pg.inner_text("#csv-pick") and pg.is_disabled("#csv-pick"))
    pg.set_input_files("#csv-file", files=[{"name": "zen_2026.csv", "mimeType": "text/csv", "buffer": CSV}])
    check(f"{n} слот с файлом: имя, «убрать», кнопка активна",
          "zen_2026.csv" in pg.inner_text("#csv-slot-host") and not pg.is_disabled("#csv-pick")
          and pg.get_attribute("#csv-slot-host .ui-file", "data-state") == "set")
    pg.click("#csv-slot-host .ui-file-rm")
    check(f"{n} «убрать» — слот пуст, кнопка снова неактивна",
          "Файл не выбран" in pg.inner_text("#csv-slot-host") and pg.is_disabled("#csv-pick") and not posts("/api/zm/csv"))
    pg.close()

    # 2. aux_ok=false и незавершённая загрузка
    pg = load({"last": {"name": "2026-10-01-0a1b2c3d", "sha256": "x", "written_at": "2026-10-01T10:00:00+03:00", "rows": 12290, "last_op": "2026-09-30"}, "incoming": ["2026-11-09-1a2b3c4d"], "aux_ok": False})
    check(f"{n} жёлтая плашка aux", "Пересчёт месяцев недоступен" in pg.inner_text("#csv-aux-warn") and "aux" in pg.inner_text("#csv-aux-warn"))
    _st = pg.inner_text("#csv-state")
    check(f"{n} последняя выгрузка: дата словами, число операций, последняя операция; служебного кода нет",
          "1 октября 2026 в 10:00" in _st and "12290 операций" in _st.replace("\u00a0", "").replace("\u202f", "").replace("12 290", "12290") and "30 сентября 2026" in _st and "0a1b2c3d" not in _st, _st)
    check(f"{n} незавершённая загрузка: дата словами, без кода", "9 ноября 2026" in pg.inner_text("#csv-incoming") and "1a2b3c4d" not in pg.inner_text("#csv-incoming"))
    pg.click('#csv-incoming [data-act="csv-show"]')
    pg.wait_for_selector("#csv-diff", timeout=5000)
    check(f"{n} «Показать отчёт» → csv-report с id", posts("/api/zm/csv-report") == [{"id": REPORT["id"]}])
    pg.close()

    # 3. загрузка файла → отчёт
    pg = load()
    upload(pg)
    pg.wait_for_selector("#csv-diff", timeout=5000)
    up = posts("/api/zm/csv")
    check(f"{n} POST csv: имя и b64 = содержимое файла", len(up) == 1 and up[0]["name"] == "zen_2026.csv" and base64.b64decode(up[0]["b64"]) == CSV)
    check(f"{n} отчёт запрошен автоматически с id", posts("/api/zm/csv-report") == [{"id": REPORT["id"]}])
    t = pg.inner_text("#csv-complete")
    check(f"{n} полнота: строки, период, предупреждение", "12\u00a0345" in t and "2020-01-03" in t and "2026-11-08" in t and "не закончен" in t, t)
    d = pg.inner_text("#csv-diff")
    check(f"{n} diff: итоги и таблица по месяцам", "61" in d and "2026-10" in d and "55" in d and pg.query_selector("#csv-diff table") is not None, d)
    check(f"{n} потерянные теги — красным списком", "#Грузия’26" in pg.inner_text("#csv-lost") and "ui-alert" in (pg.get_attribute("#csv-lost", "class") or ""))
    check(f"{n} образцы — в <details>, свёрнуты", pg.evaluate("[...document.querySelectorAll('#csv-diff details')].length === 2 && [...document.querySelectorAll('#csv-diff details')].every(x => !x.open)"))
    w = pg.inner_text("#csv-towrite")
    check(f"{n} «К записи»: месяц с action и объяснимостью, изменения, поездка", "Октябрь 2026" in w and "будет перезаписан" in w and "replace" not in w and "расход: было 123 456, в выгрузке 121 000" in w and "Без изменений: 1 месяц" in w and "Сентябрь 2026" not in w and "объяснимо" in w and "было 123 456" in w and "#Грузия’26" in w, w)
    ck = pg.text_content("#csv-checks") or ""
    check(f"{n} «На что взглянуть»: месяц, текст проверки, число, пример и хвост «ещё 6»",
          "Октябрь 2026" in ck and "место обычно в другой категории" in ck and "обычно «Кафе»" in ck and "ещё 6" in ck, ck)
    check(f"{n} вспомогательные файлы: мест без словаря 7", "Мест без словаря: 7" in pg.inner_text("#csv-aux"))
    check(f"{n} стопов нет, «Записать» активна", pg.query_selector("#csv-stops") is None and not pg.is_disabled("#csv-apply") and pg.query_selector("#csv-stop-hint") is None)
    if W == 1280:
        pg.screenshot(path=os.environ["CSV_SHOT_1280"], full_page=True)
    else:
        pg.screenshot(path=os.environ["CSV_SHOT_390"], full_page=True)
        check(f"{n} не шире экрана", pg.evaluate("document.documentElement.scrollWidth") <= W + 1)

    # 6. подтверждение: отмена — ничего; «Записать» — apply
    pg.click("#csv-apply")
    pg.wait_for_selector(".ui-confirm-box", timeout=5000)
    ct = pg.inner_text(".ui-confirm-box")
    check(f"{n} подтверждение: 1 месяц и 1 поездка, копии в .versions/", "1 месяц" in ct and "1 поездка" in ct and ".versions/" in ct, ct)
    pg.click(".ui-confirm-no")
    pg.wait_for_function("!document.querySelector('.ui-confirm')")
    check(f"{n} «Отмена» — apply не отправлен", posts("/api/zm/csv-apply") == [])
    gets = ST["audit_gets"]
    pg.click("#csv-apply")
    pg.wait_for_selector(".ui-confirm-box")
    pg.click(".ui-confirm-ok")
    pg.wait_for_selector("#csv-done", timeout=5000)
    check(f"{n} POST csv-apply {{id, confirm:true}}", posts("/api/zm/csv-apply") == [{"id": REPORT["id"], "confirm": True}])
    check(f"{n} итог «записано»", "записано: 1 месяц, 1 поездка" in pg.inner_text("#csv-done"), pg.inner_text("#csv-done"))
    pg.wait_for_timeout(300)
    check(f"{n} данные страницы перечитаны после записи", ST["audit_gets"] > gets)

    # 7. noai
    pg.evaluate("localStorage.setItem('hub-noai','off')")
    pg.reload()
    pg.wait_for_selector("#csv-state")
    upload(pg)
    pg.wait_for_selector("#csv-aux", timeout=5000)
    check(f"{n} noai: подсказки для Claude скрыты", pg.evaluate("[...document.querySelectorAll('#csv-aux .noai-hide')].every(e => getComputedStyle(e).display === 'none')")
          and pg.query_selector("#csv-aux .noai-hide") is not None)
    pg.close()

    # 4. ошибка сервера
    pg = load()
    ST["csv_code"] = 400
    upload(pg)
    pg.wait_for_selector("#csv-err", timeout=5000)
    check(f"{n} ошибка сервера текстом", "нет колонки outcomeAccountName" in pg.inner_text("#csv-err"))
    check(f"{n} после ошибки отчёта нет", pg.query_selector("#csv-diff") is None)
    pg.close()

    # 5. стопы
    pg = load(report=STOP_REPORT)
    upload(pg)
    pg.wait_for_selector("#csv-stops", timeout=5000)
    check(f"{n} стопы красным списком", "необъяснимое расхождение 2026-07" in pg.inner_text("#csv-stops"))
    check(f"{n} при стопах «Записать» disabled + текст", pg.is_disabled("#csv-apply") and "Устрани причины в ZenMoney" in pg.inner_text("#csv-stop-hint"))
    pg.close()
    # 8. «Разовая» и «Новые поездки»
    pg = load(report=REPORT_EDIT)
    upload(pg)
    pg.wait_for_selector("#csv-newtrips", timeout=5000)
    w = pg.inner_text("#csv-towrite")
    check(f"{n} кандидат: сумма, дата, категория, место, кнопка «Разовая» и поле «Что это»",
          "крупные траты" in w.lower() and "2026-10-15" in w and "Магазин-Х" in w and "Покупки" in w
          and pg.query_selector('[data-act="csv-rule"]') is not None and "что это" in w.lower(), w)
    check(f"{n} «Разовая» есть только у месяца к записи", len(pg.query_selector_all('[data-act="csv-rule"]')) == 1)
    pg.click('[data-act="csv-rule"]')
    pg.wait_for_selector("#csv-err", timeout=3000)
    check(f"{n} «Разовая» без «что это» — ошибка, POST не ушёл", "что это" in pg.inner_text("#csv-err") and posts("/api/zm/rule") == [])
    ST["rule_replies"][:] = [AFTER_RULE]
    pg.fill("#csv-note-2026-10-0", "ремонт")
    pg.click('[data-act="csv-rule"]')
    pg.wait_for_selector(".csv-siterule", timeout=5000)
    check(f"{n} POST rule: месяц, дата, счёт, сумма, место, заметка",
          posts("/api/zm/rule") == [{"id": REPORT["id"], "month": "2026-10", "date": "2026-10-15", "account": "Карта", "amount": 50000,
                                     "payee": "Магазин-Х", "note": "ремонт"}], posts("/api/zm/rule"))
    check(f"{n} после отметки: кандидата нет, строка «Отмечено с сайта» с заметкой и «Снять»",
          pg.query_selector('[data-act="csv-rule"]') is None and "ремонт" in pg.inner_text(".csv-siterule")
          and "Снять" in pg.inner_text(".csv-siterule"))
    ST["rule_replies"][:] = [AFTER_REMOVE]
    check(f"{n} «Снять» — опасная кнопка (красная): это удаление отметки",
          "danger" in (pg.get_attribute('[data-act="csv-rule-remove"]', "class") or ""))
    pg.click('[data-act="csv-rule-remove"]')
    pg.wait_for_selector(".ui-confirm", timeout=5000)
    check(f"{n} «Снять» спрашивает подтверждение, до ответа запроса нет",
          "разовая" in pg.inner_text(".ui-confirm") and not any(x.get("remove") for x in posts("/api/zm/rule")))
    pg.click(".ui-confirm-ok")
    pg.wait_for_selector('[data-act="csv-rule"]', timeout=5000)
    check(f"{n} POST rule remove: rule_id отметки",
          posts("/api/zm/rule")[-1] == {"id": REPORT["id"], "remove": True, "rule_id": "site-0123456789ab"})
    nt = pg.inner_text("#csv-newtrips")
    check(f"{n} «Новые поездки»: тег, число операций, даты в полях",
          "#Тбилиси’26" in nt and "операций 2" in nt and pg.input_value("#f-csvts0") == "2026-09-05"
          and pg.input_value("#f-csvte0") == "2026-09-07" and pg.input_value("#fv-csvts0") == "05.09.2026", nt)
    _ys = pg.evaluate("[...document.querySelectorAll('.ui-daterow > *')].map(e => Math.round(e.getBoundingClientRect().bottom))")
    check(f"{n} даты поездки — стандартное поле ui-kit; начало, конец и кнопка {'в одну строку' if W > 600 else 'друг под другом'}",
          pg.query_selector("#csv-newtrips .dp-wrap [data-dp-open]") is not None and not pg.query_selector('#csv-newtrips input[type="date"]')
          and ((len(set(_ys)) == 1) if W > 600 else (len(set(_ys)) == 3)), str(_ys))
    ST["trip_reply"] = AFTER_TRIP
    pg.click('#csv-newtrips [data-dp-open="csvte0"]')
    check(f"{n} кнопка ▤ открывает календарь ui-kit, Esc закрывает", pg.query_selector(".dp-pop") is not None)
    pg.keyboard.press("Escape")
    check(f"{n} календарь закрыт", pg.query_selector(".dp-pop") is None)
    pg.fill("#fv-csvts0", "")
    pg.type("#fv-csvts0", "04092026")
    check(f"{n} ручной ввод: маска ДД.ММ.ГГГГ и ISO в скрытом поле",
          pg.input_value("#fv-csvts0") == "04.09.2026" and pg.input_value("#f-csvts0") == "2026-09-04")
    pg.click('[data-act="csv-trip"]')
    pg.wait_for_function("!document.querySelector('#csv-newtrips')", timeout=5000)
    check(f"{n} POST trip: имя и исправленные даты",
          posts("/api/zm/trip") == [{"id": REPORT["id"], "name": "#Тбилиси’26", "start": "2026-09-04", "end": "2026-09-07"}], posts("/api/zm/trip"))
    if W == 390:
        check(f"{n} отчёт с кандидатами не шире экрана", pg.evaluate("document.documentElement.scrollWidth") <= W + 1)
    pg.close()
    check(f"{n} ошибок JS нет", not errs, str(errs[:3]))
    ctx.close()


def month_row(m):
    reg = 100000
    return {"month": m, "as_of": m + "-28",
            "totals": {"expense_rub": reg, "income_rub": 300e3, "refunds_rub": 0, "expense_in_balance_rub": reg,
                       "income_in_balance_rub": 300e3, "expense_off_balance_rub": 0, "expense_trips_rub": 0,
                       "expense_one_off_rub": 0, "expense_regular_rub": reg, "operations": 90},
            "excluded": {}, "categories": [], "income_categories": [], "trips": [],
            "categories_regular": [{"name": "Питание", "rub": reg * 0.6, "count": 9, "share": 0.6},
                                   {"name": "Счета", "rub": reg * 0.4, "count": 3, "share": 0.4}],
            "subcategories_regular": [], "merchants": [], "merchant_share_of_expense": 0.8, "unconverted": {}}


def hist_rec(m):
    return {"month": m, "as_of": m + "-28", "mode": "month", "operations": 100, "flagged": 0, "clean_share_count": 1,
            "clean_share_rub": 1, "expense_rub": 1e5, "correction_rub": 0, "correction_transfer_out_rub": 0,
            "correction_share_of_expense": 0, "by_check": {}, "b6_count": 0, "b7_count": 0, "b7_rub": 0, "c_counts": None,
            "open_by_age": {}, "open_total": 0, "unconverted": {}}


def scenario_site_audit(br, base, W, hgt):
    """«Качество учёта» и «Обзор» при аудите сайта (site-audit.json) и без него."""
    n = f"{W}px"
    last = date.today().replace(day=1) - timedelta(days=1)          # прошлый календарный месяц — его проверяет «закрыт ли»
    M = f"{last.year}-{last.month:02d}"
    prev = last.replace(day=1) - timedelta(days=1)
    P = f"{prev.year}-{prev.month:02d}"
    SPEND = {"schema": "zenmoney-spending@1", "updated": M + "-28", "months": [month_row(P), month_row(M)]}
    SA = {"schema": "zenmoney-site-audit@1", "updated": M + "-29", "months": {M: {
        "as_of": M + "-29", "export_id": "2026-11-09-1a2b3c4d", "stops_overridden": [],
        "checks": [{"id": "P1", "cls": "hint", "count": 7, "text": "место обычно в другой категории"},
                   {"id": "D13", "cls": "warn", "count": 2, "text": "возможный дубль операции"}]}}}
    errs = []

    def open_tab(tab, audit):
        ctx = br.new_context(viewport={"width": W, "height": hgt})
        ctx.add_init_script(f"localStorage.setItem('hub-auth','dGVzdDp0ZXN0'); localStorage.setItem('money-tab','{tab}');")
        ST["audit"] = audit
        ST["audit_gets"] = 0
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/tools/money.html")
        pg.wait_for_selector(".ui-status, #site-audit, .ui-empty, .ui-tile", timeout=15000)
        pg.wait_for_timeout(400)
        return ctx, pg

    # только аудит сайта (аудита скилла нет) → пометка и список проверок
    ctx, pg = open_tab("quality", {"spending.json": SPEND, "site-audit.json": SA})
    body = pg.inner_text("#app")
    check(f"{n} качество: пометка «аудит сайта» и проверки с числами",
          pg.query_selector("#site-audit .ui-tag") is not None and "аудит сайта" in pg.inner_text("#site-audit .ui-tag")
          and "место обычно в другой категории" in body and "возможный дубль операции" in body, body[:400])
    tip = pg.get_attribute("#site-audit .ui-tag", "title") or ""
    check(f"{n} подсказка: «аудит скилла полнее и при появлении заменит этот»", "аудит скилла полнее и при появлении заменит этот" in tip, tip)
    check(f"{n} числа проверок видны", "7" in pg.inner_text("#site-audit") and "2" in pg.inner_text("#site-audit"))
    ctx.close()

    # есть аудит скилла и аудит сайта → скилла; пометки нет, одна строка про сайт
    hist = {"schema": "zenmoney-audit@1", "updated": M + "-28", "issues": {}, "records": [hist_rec(P), hist_rec(M)]}
    ctx, pg = open_tab("quality", {"spending.json": SPEND, "history.json": hist, "site-audit.json": SA})
    check(f"{n} качество при аудите скилла: пометки «аудит сайта» нет, список проверок сайта не показан",
          pg.query_selector("#site-audit") is None and pg.query_selector(".ui-tag[title*='аудит скилла полнее']") is None
          and "возможный дубль операции" not in pg.inner_text("#app"))
    check(f"{n} качество при аудите скилла: «сайт при загрузке отметил: 9»",
          pg.query_selector("#site-audit-line") is not None and "сайт при загрузке отметил: 9" in pg.inner_text("#site-audit-line"))
    ctx.close()

    # «Обзор»: закрыт по сайту — без красной плашки
    ctx, pg = open_tab("overview", {"spending.json": SPEND, "site-audit.json": SA})
    st = pg.inner_text(".ui-status")
    check(f"{n} обзор: «закрыт по сайту» с пометкой, без «закрыт не полностью»",
          "по сайту" in st and "закрыт не полностью" not in st and "ещё не закрыт" not in st
          and pg.query_selector(".ui-status .ui-tag") is not None, st)
    ctx.close()
    # без аудита сайта и без аудита скилла — прежняя плашка
    ctx, pg = open_tab("overview", {"spending.json": SPEND})
    check(f"{n} обзор без аудита: «закрыт не полностью»", "закрыт не полностью" in pg.inner_text(".ui-status"), pg.inner_text(".ui-status"))
    ctx.close()
    check(f"{n} аудит сайта: ошибок JS нет", not errs, str(errs[:3]))


CAND2 = dict(CAND, date="2026-10-20", amount=30000, rub=30000, payee="Магазин-Y")
REPORT_TWO = dict(REPORT_EDIT, months=[dict(REPORT["months"][0], candidates=[CAND, CAND2], site_rules=[]), REPORT["months"][1]])


def scenario_keep(br, base, W, hgt):
    """Набранное в полях отчёта переживает перерисовку: ошибка в другой строке, смена темы, поздний ответ (часть В)."""
    n = f"{W}px keep"
    ctx = br.new_context(viewport={"width": W, "height": hgt})
    ctx.add_init_script("localStorage.setItem('hub-auth','dGVzdDp0ZXN0'); localStorage.setItem('money-tab','csv');")
    errs = []
    ST.update(state={"last": None, "incoming": [], "aux_ok": True}, report=REPORT_TWO, csv_code=200, audit_gets=0, audit={})
    ST["posts"].clear()
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(base + "/tools/money.html")
    pg.wait_for_selector("#csv-state", timeout=15000)
    pg.set_input_files("#csv-file", files=[{"name": "zen_2026.csv", "mimeType": "text/csv", "buffer": CSV}])
    pg.click("#csv-pick")
    pg.wait_for_selector("#csv-newtrips", timeout=5000)
    # текст в поле A, ошибка в строке B (пустое «что это») -> перерисовка
    pg.fill("#csv-note-2026-10-0", "ремонт кухни")
    pg.click('[data-act="csv-rule"][data-v="2026-10|1"]')
    pg.wait_for_selector("#csv-err", timeout=3000)
    check(f"{n} ошибка в строке B не стирает текст в строке A", pg.input_value("#csv-note-2026-10-0") == "ремонт кухни",
          pg.input_value("#csv-note-2026-10-0"))
    # даты поездки + ошибка «укажи даты» (начало позже конца) -> перерисовка
    pg.fill("#fv-csvts0", "")
    pg.type("#fv-csvts0", "10092026")
    pg.click('[data-act="csv-trip"]')
    pg.wait_for_selector("#csv-err", timeout=3000)
    check(f"{n} ошибка «укажи даты» не стирает ни даты, ни текст в «что это»",
          pg.input_value("#f-csvts0") == "2026-09-10" and pg.input_value("#fv-csvts0") == "10.09.2026"
          and pg.input_value("#csv-note-2026-10-0") == "ремонт кухни",
          pg.input_value("#f-csvts0") + " " + pg.input_value("#csv-note-2026-10-0"))
    # смена темы (событие ui-theme) при фокусе в поле: текст, фокус и курсор на месте
    pg.fill("#csv-note-2026-10-1", "подарок")
    pg.focus("#csv-note-2026-10-1")
    pg.evaluate("(function(){var e=document.getElementById('csv-note-2026-10-1');e.setSelectionRange(3,3);})()")
    pg.evaluate("document.dispatchEvent(new CustomEvent('ui-theme',{detail:'dark'}))")
    check(f"{n} смена темы не стирает текст в обоих полях и даты",
          pg.input_value("#csv-note-2026-10-0") == "ремонт кухни" and pg.input_value("#csv-note-2026-10-1") == "подарок"
          and pg.input_value("#f-csvts0") == "2026-09-10" and pg.input_value("#fv-csvts0") == "10.09.2026")
    cur = pg.evaluate("(function(){var a=document.activeElement;return [a&&a.id,a&&a.selectionStart];})()")
    check(f"{n} фокус и позиция курсора сохранены ({cur})", cur == ["csv-note-2026-10-1", 3])
    check(f"{n} ошибок JS нет", not errs, str(errs[:3]))
    ctx.close()


def run(name, br):
    tmp = Path(tempfile.mkdtemp())
    os.symlink(REPO / "tools", tmp / "tools")
    srv, base = serve(H, directory=tmp)
    try:
        scenario(br, base, 1280, 900)
        scenario(br, base, 390, 844)
        scenario_keep(br, base, 1280, 900)
        scenario_keep(br, base, 390, 844)
        scenario_site_audit(br, base, 1280, 900)
        scenario_site_audit(br, base, 390, 844)
    finally:
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    shots = Path("/tmp/claude-0/-home-user-claude-skills/8c4e6278-d843-55d8-8d39-e71df073993d/scratchpad")
    shots.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("CSV_SHOT_1280", str(shots / "money-csv-1280.png"))
    os.environ.setdefault("CSV_SHOT_390", str(shots / "money-csv-390.png"))
    per_engine(run, engines=("chromium",))
    print(f"money_csv_page: {check.passed} OK, {check.failed} FAIL")
    sys.exit(1 if check.failed else 0)
