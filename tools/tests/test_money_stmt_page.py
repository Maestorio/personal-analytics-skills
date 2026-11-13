#!/usr/bin/env python3
"""Блок «Выписка банка» вкладки «Загрузка» страницы money.html v2.6.1 — прогон настоящим браузером (playwright, Chromium, 1280 и 390).

Правило: выписка банка → отчёт zm-stmt-report@1 (docs/zenmoney/stmt-site.md). Только чтение: страница шлёт ровно два POST
(/api/zm/stmt и /api/zm/stmt-report), ничего больше. Стенд — статика tools/ и поддельные маршруты зоны /api/zm/ (тело каждого POST
запоминается). Проверяется:
  1. Отдельной вкладки выписки нет: вкладка «Загрузка» (ключ csv) последняя в переключателе (1280) и в нижней навигации (390),
     в ней два блока — первым «Выгрузка ZenMoney (CSV)», вторым «Выписка банка (CSV, XLSX)»; слот «Выписка банка» принимает
     только .xlsx,.csv (обязательно, «Файл не выбран»), кнопка «Проверить выписку» неактивна без файла, активна с файлом,
     «убрать» гасит её; цвет кнопки — токен --btn-acc, как у «Проверить выгрузку»; после кнопки нет плашек.
     Старый ключ money-tab=stmt открывает «Загрузку».
  2. Файл → POST /api/zm/stmt {name, b64 = содержимое} → автоматически POST /api/zm/stmt-report {id}; в отчёте: плашка
     результата (.ui-alert.ui-mt-m) с банком, счётом, периодом и «Остатки сходятся», таблица остатков, «Что отметили скрипты»,
     сравнение с ZenMoney (две свёрнутые/раскрытые таблицы «есть в выписке, нет в ZenMoney» и обратная), таблица операций; числа
     с неразрывными пробелами и запятой («98 240,00», минус настоящий); 390 — страница не шире экрана, широкая таблица
     операций прокручивается внутри своей обёртки.
  3. Расхождение остатков → предупреждающая плашка «расхождение на 5,00 USD»; Райффайзенбанк — остатков нет («нет данных»,
     строки «Итоги справки» нет), сравнение недоступно — причина текстом.
  4. Отказы: сервер не принял файл (400, в том числе PDF: «PDF на сайте не разбирается…») и не разобрал (422 «банк не узнан») —
     текст в красной плашке; файл больше 8 МБ — отказ на клиенте без единого POST.
  4а. Блоки независимы: отчёт выписки и её файл остаются, когда выгрузка CSV отвечает ошибкой, и наоборот; ошибка выписки
     не стирает ошибку, файл и состояние выгрузки; на 390 страница не шире экрана с двумя блоками.
  5. data-noai: подсказка «/zenmoney-analyst внеси операции из выписки» скрыта. Ошибок JS нет.
Данные синтетические. Без playwright или chromium — пропуск.
Запуск: python3 tools/tests/test_money_stmt_page.py
"""
import base64
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
    print("money_stmt_page: пропуск — нет playwright")
    sys.exit(0)

check = Checker()
FILE = "date;x\n1;2\n".encode()
OPS = [{"date": "2026-03-%02d" % (i % 28 + 1), "time": None, "amount": "-1234567.89" if i == 0 else "-10.00", "currency": "USD",
        "text": "Payment - Amount: USD10.00; Merchant: COFFEE, Georgia; Card No: ****1111; очень длинное описание операции для проверки ширины таблицы на узком экране"}
       for i in range(30)]
REPORT = {
    "schema": "zm-stmt-report@1", "id": "2026-11-10-1a2b3c4d", "built_at": "2026-11-10T12:00:00+03:00", "format": "xlsx",
    "bank": "bog", "bank_name": "Bank of Georgia (BOG)", "account": "…0001", "kind": "current", "currencies": ["GEL", "USD"],
    "period": {"from": "2026-03-01", "to": "2026-03-31"}, "ops_count": 30, "checks_ok": True,
    "balances": [{"currency": "USD", "opening": "100098240.00", "sum_ops": "-10.00", "closing": "100098230.00", "calc": "100098230.00",
                  "diff": "0.00", "status": "match", "note": None},
                 {"currency": "GEL", "opening": "0.00", "sum_ops": "0.00", "closing": "0.00", "calc": "0.00", "diff": "0.00", "status": "match", "note": None}],
    "footer": None,
    "flags": [{"kind": "unknown-row", "title": "строка не распознана", "date": "2026-03-05", "detail": "GEL 3.00: что-то новое"}],
    "operations": OPS, "operations_truncated": False,
    "compare": {"available": True, "reason": None, "window": {"from": "2026-03-01", "to": "2026-03-31"}, "accounts": {"USD": "BOG USD"},
                "bank_ops": 30, "zen_ops": 29, "matched": 28, "other": {"differs": 1},
                "missing_in_zen": [{"date": "2026-03-02", "amount": "-10.00", "currency": "USD", "text": "COFFEE"}], "missing_in_zen_total": 1,
                "missing_in_bank": [{"date": "2026-03-09", "amount": "-77.00", "currency": "USD", "text": "Лишнее место"}], "missing_in_bank_total": 1}}
MISMATCH = dict(REPORT, checks_ok=False, balances=[dict(REPORT["balances"][0], status="mismatch", diff="-5.00", closing="100098225.00"), REPORT["balances"][1]])
RAIF = dict(REPORT, bank="raif", bank_name="Райффайзенбанк", format="csv", currencies=["RUB"], footer=None,
            balances=[{"currency": "RUB", "opening": None, "sum_ops": "700.00", "closing": None, "calc": None, "diff": None, "status": "unavailable",
                       "note": "в выписке Райффайзенбанка нет остатков"}],
            compare={"available": False, "reason": "счёт не сопоставлен (несколько подходящих счетов: RUB) — сравнение с ZenMoney недоступно"})
ST = {"csv_code": 200, "posts": [], "up": (200, {"id": REPORT["id"], "format": "xlsx", "size": 3}), "rep": (200, REPORT)}


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
            return self._j(200, {"last": None, "incoming": [], "aux_ok": True})
        return super().do_GET()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        ST["posts"].append((self.path.split("?")[0], body))
        if self.path.startswith("/api/zm/csv"):
            return self._j(ST["csv_code"], {"error": "нет колонки outcomeAccountName"} if ST["csv_code"] != 200 else {"id": "x"})
        if self.path.startswith("/api/zm/stmt-report"):
            return self._j(*ST["rep"])
        if self.path.startswith("/api/zm/stmt"):
            return self._j(*ST["up"])
        return self._j(404, {})


def posts(path):
    return [b for p, b in ST["posts"] if p == path]


def scenario(br, base, W, hgt):
    n = f"{W}px"
    ctx = br.new_context(viewport={"width": W, "height": hgt})
    ctx.add_init_script("localStorage.setItem('hub-auth','dGVzdDp0ZXN0'); localStorage.setItem('money-tab','stmt');   /* старый ключ -> «Загрузка» */")
    errs = []

    def load(up=None, rep=None):
        ST["up"] = up or (200, {"id": REPORT["id"], "format": "xlsx", "size": 3})
        ST["rep"] = rep or (200, REPORT)
        ST["posts"].clear()
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
        pg.goto(base + "/tools/money.html")
        pg.wait_for_selector("#stmt-pick", timeout=15000)
        return pg

    def upload(pg, buf=FILE, name="stmt_2026.xlsx"):
        pg.set_input_files("#stmt-file", files=[{"name": name, "mimeType": "application/octet-stream", "buffer": buf}])
        pg.click("#stmt-pick")

    # 1. вкладка, слот, кнопка
    pg = load()
    tabs = pg.evaluate("[...document.querySelectorAll('[data-act=\"tab\"]')].filter(e => e.offsetParent).map(e => e.getAttribute('data-v'))")
    check(f"{n} вкладка «Загрузка» (ключ csv) последняя, вкладки stmt нет, всего пять ({tabs})", tabs and tabs[-1] == "csv" and "stmt" not in tabs and len(tabs) == 5)
    labels = pg.evaluate("[...document.querySelectorAll('[data-act=\"tab\"]')].filter(e => e.offsetParent).map(e => e.textContent.trim())")
    check(f"{n} подпись «Загрузка», подписей «Выписка»/«Сверка выписки»/«Выгрузка» нет ({labels})",
          "Загрузка" in labels and not {"Выписка", "Сверка выписки", "Выгрузка"} & set(labels))
    order = pg.evaluate("[...document.querySelectorAll('main h2.ui-h2')].map(e => e.textContent.trim())")
    check(f"{n} порядок блоков: сначала выгрузка ZenMoney, потом выписка банка ({order})", order[:2] == ["Выгрузка ZenMoney (CSV)", "Выписка банка (CSV, XLSX)"])
    check(f"{n} состояние сохранённого ключа stmt -> активна «Загрузка»", pg.evaluate("localStorage.getItem('money-tab')") in ("stmt", "csv")
          and pg.query_selector("#blk-stmt #stmt-pick") is not None and pg.query_selector("#blk-csv #csv-pick") is not None)
    host = pg.inner_text("#stmt-slot-host")
    check(f"{n} слот: «обязательно», «Файл не выбран», кнопка «Проверить выписку» неактивна без файла",
          "обязательно" in host and "Файл не выбран" in host and "Проверить выписку" in pg.inner_text("#stmt-pick") and pg.is_disabled("#stmt-pick"), host)
    check(f"{n} слот принимает только XLSX и CSV (PDF сайт не разбирает)", pg.get_attribute("#stmt-file", "accept") == ".xlsx,.csv")
    pg.set_input_files("#stmt-file", files=[{"name": "stmt_2026.xlsx", "mimeType": "application/octet-stream", "buffer": FILE}])
    check(f"{n} с файлом: имя, кнопка активна", "stmt_2026.xlsx" in pg.inner_text("#stmt-slot-host") and not pg.is_disabled("#stmt-pick"))
    same = pg.evaluate("""() => { const p = document.createElement('div'); p.style.background = 'var(--btn-acc)'; document.body.appendChild(p);
        const a = getComputedStyle(p).backgroundColor, b = getComputedStyle(document.getElementById('stmt-pick')).backgroundColor; p.remove(); return [a, b]; }""")
    check(f"{n} кнопка цвета --btn-acc, класс ui-btn lg, как у «Проверить выгрузку» ({same})",
          same[0] == same[1] and pg.get_attribute("#stmt-pick", "class") == "ui-btn lg")
    pg.click("#stmt-slot-host .ui-file-rm")
    check(f"{n} «убрать» — слот пуст, кнопка неактивна, POST не было", "Файл не выбран" in pg.inner_text("#stmt-slot-host") and pg.is_disabled("#stmt-pick") and not ST["posts"])
    check(f"{n} до отчёта плашек нет", pg.query_selector("#stmt-err") is None and pg.query_selector("#stmt-sum") is None)
    pg.close()

    # 2. файл → отчёт
    pg = load()
    upload(pg)
    pg.wait_for_selector("#stmt-sum", timeout=5000)
    up = posts("/api/zm/stmt")
    check(f"{n} POST stmt: имя и b64 = содержимое файла", len(up) == 1 and up[0]["name"] == "stmt_2026.xlsx" and base64.b64decode(up[0]["b64"]) == FILE)
    check(f"{n} отчёт запрошен автоматически с id", posts("/api/zm/stmt-report") == [{"id": REPORT["id"]}])
    check(f"{n} страница шлёт только эти два POST (в ZenMoney, историю и карту — ничего)", [p for p, _ in ST["posts"]] == ["/api/zm/stmt", "/api/zm/stmt-report"])
    s = pg.inner_text("#stmt-sum")
    check(f"{n} плашка результата: банк, счёт, период, число операций, «Остатки сходятся»",
          "Bank of Georgia" in s and "…0001" in s and "01.03.2026" in s and "31.03.2026" in s and "30 операций" in s and "Остатки сходятся" in s, s)
    check(f"{n} плашка — .ui-alert с отступом ui-mt-m, не красная", pg.evaluate("(() => { const e = document.getElementById('stmt-sum'); return e.classList.contains('ui-alert') && e.classList.contains('ui-mt-m') && !e.classList.contains('warn'); })()"))
    b = pg.inner_text("#stmt-bal")
    check(f"{n} остатки: числа с пробелами и запятой, итог «сходится»", "100 098 240,00" in b and "−10,00" in b and "сходится" in b, b)
    check(f"{n} флаги скриптов: заголовок, дата, текст", "строка не распознана" in pg.inner_text("#stmt-flags") and "05.03.2026" in pg.inner_text("#stmt-flags"))
    c = pg.inner_text("#stmt-cmp")
    check(f"{n} сравнение: счёт ZenMoney, пары, обе стороны расхождений",
          "BOG USD" in c and "28" in c and "Есть в выписке, нет в ZenMoney (1)" in c and "Есть в ZenMoney, нет в выписке (1)" in c and "Лишнее место" in c and "сумма отличается" in c, c)
    ops = pg.inner_text("#stmt-ops")
    check(f"{n} таблица операций: 30 строк, дата по-русски, сумма с минусом и пробелами", pg.evaluate("document.querySelectorAll('#stmt-ops tbody tr').length") == 30
          and "02.03.2026" in ops and "−1 234 567,89" in ops, ops[:200])
    check(f"{n} внизу «Только чтение… файл удалён»", "ничего не записано" in pg.inner_text("#stmt-note") and "удалён" in pg.inner_text("#stmt-note"))
    if W == 390:
        check(f"{n} страница не шире экрана", pg.evaluate("document.documentElement.scrollWidth") <= W + 1)
        check(f"{n} таблица операций шире экрана прокручивается внутри обёртки",
              pg.evaluate("(() => { const w = document.querySelector('#stmt-ops .ui-table-wrap'); return w.scrollWidth > w.clientWidth && getComputedStyle(w).overflowX === 'auto'; })()"))
    shot = os.environ.get("STMT_SHOT_" + str(W))
    if shot:
        pg.screenshot(path=shot, full_page=True)
    # noai
    pg.evaluate("localStorage.setItem('hub-noai','off')")
    pg.reload()
    pg.wait_for_selector("#stmt-pick")
    upload(pg)
    pg.wait_for_selector("#stmt-note", timeout=5000)
    check(f"{n} noai: подсказка про скилл скрыта, но есть в разметке",
          pg.evaluate("[...document.querySelectorAll('#stmt-note .noai-hide')].every(e => getComputedStyle(e).display === 'none')") and pg.query_selector("#stmt-note .noai-hide") is not None
          and "/zenmoney-analyst" in pg.text_content("#stmt-note"))
    pg.evaluate("localStorage.removeItem('hub-noai')")
    pg.close()

    # 3. расхождение остатков, Т-Банк с итогами справки и недоступным сравнением
    pg = load(rep=(200, MISMATCH))
    upload(pg)
    pg.wait_for_selector("#stmt-sum", timeout=5000)
    s = pg.inner_text("#stmt-sum")
    check(f"{n} расхождение: плашка предупреждения и «расхождение на 5,00 USD»", "расхождение на 5,00 USD" in s and "warn" in (pg.get_attribute("#stmt-sum", "class") or "")
          and "расхождение на 5,00" in pg.inner_text("#stmt-bal"), s)
    pg.close()
    pg = load(rep=(200, RAIF))
    upload(pg)
    pg.wait_for_selector("#stmt-sum", timeout=5000)
    check(f"{n} Райффайзенбанк: «нет данных» по остаткам, строки «Итоги справки» нет, причина недоступности сравнения",
          "нет данных" in pg.inner_text("#stmt-bal") and pg.query_selector("#stmt-footer") is None
          and "счёт не сопоставлен" in pg.inner_text("#stmt-cmp") and "Сверка остатков: в этой выписке нет данных" in pg.inner_text("#stmt-sum"))
    pg.close()

    # 4. отказы
    pg = load(up=(400, {"error": "bad statement", "detail": "PDF на сайте не разбирается — поддержаны CSV Райффайзенбанка и XLSX BOG"}))
    upload(pg)
    pg.wait_for_selector("#stmt-err", timeout=5000)
    check(f"{n} сервер не принял файл: причина в красной плашке с отступом, отчёт не запрошен",
          "Выписка не принята" in pg.inner_text("#stmt-err") and "PDF на сайте не разбирается" in pg.inner_text("#stmt-err") and "Claude" not in pg.inner_text("#stmt-err") and not posts("/api/zm/stmt-report")
          and "ui-mt-m" in (pg.get_attribute("#stmt-err", "class") or ""))
    pg.close()
    for code, text in ((422, "банк не узнан: нужен образец для нового разбора"),):
        pg = load(rep=(code, {"error": text}))
        upload(pg)
        pg.wait_for_selector("#stmt-err", timeout=5000)
        check(f"{n} {code}: текст сервера в плашке", "Выписка не разобрана" in pg.inner_text("#stmt-err") and text in pg.inner_text("#stmt-err"), pg.inner_text("#stmt-err"))
        pg.close()
    pg = load()
    upload(pg, buf=b"x" * (8 * 1024 * 1024 + 1))
    pg.wait_for_selector("#stmt-err", timeout=5000)
    check(f"{n} файл больше 8 МБ: отказ на клиенте, ни одного POST", "больше 8" in pg.inner_text("#stmt-err") and not ST["posts"])
    pg.close()
    # 4а. независимость блоков
    pg = load()
    upload(pg)
    pg.wait_for_selector("#stmt-sum", timeout=5000)
    ST["csv_code"] = 400
    pg.set_input_files("#csv-file", files=[{"name": "zen_2026.csv", "mimeType": "text/csv", "buffer": FILE}])
    pg.click("#csv-pick")
    pg.wait_for_selector("#csv-err", timeout=5000)
    check(f"{n} ошибка выгрузки не стирает отчёт, файл и кнопку выписки",
          pg.query_selector("#stmt-sum") is not None and "stmt_2026.xlsx" in pg.inner_text("#stmt-slot-host") and not pg.is_disabled("#stmt-pick"))
    ST["rep"] = (422, {"error": "банк не узнан: нужен образец для нового разбора"})
    pg.click("#stmt-pick")
    pg.wait_for_selector("#stmt-err", timeout=5000)
    check(f"{n} ошибка выписки не стирает ошибку, файл и кнопку выгрузки",
          pg.query_selector("#csv-err") is not None and "zen_2026.csv" in pg.inner_text("#csv-slot-host") and not pg.is_disabled("#csv-pick")
          and pg.query_selector("#stmt-sum") is None)
    check(f"{n} плашки обоих блоков — .ui-alert с отступом ui-mt-m",
          pg.evaluate("['csv-err', 'stmt-err'].every(i => { const e = document.getElementById(i); return e.classList.contains('ui-alert') && e.classList.contains('ui-mt-m'); })"))
    colors = pg.evaluate("['csv-pick', 'stmt-pick'].map(i => getComputedStyle(document.getElementById(i)).backgroundColor)")
    check(f"{n} кнопки обоих блоков одного цвета и одной конструкции ({colors})",
          colors[0] == colors[1] and pg.get_attribute("#csv-pick", "class") == pg.get_attribute("#stmt-pick", "class"))
    if W == 390:
        check(f"{n} два блока: страница не шире экрана", pg.evaluate("document.documentElement.scrollWidth") <= W + 1)
    ST["csv_code"] = 200
    pg.close()
    check(f"{n} ошибок JS нет", not errs, str(errs[:3]))
    ctx.close()


def run(name, br):
    tmp = Path(tempfile.mkdtemp())
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
    print(f"money_stmt_page: {check.passed} OK, {check.failed} FAIL")
    sys.exit(1 if check.failed else 0)
