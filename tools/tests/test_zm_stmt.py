#!/usr/bin/env python3
"""Сверка выписки банка на сайте без ZenMoney и без Claude (этап «Деньги» 3.8, бэкенд): tools/hosting/notify/zm_stmt.py,
маршрут hub-notify и зона /api/zm/stmt* hub-api. Устройство — docs/zenmoney/stmt-site.md.

Контракты:
  • отчёт zm-stmt-report@1 по синтетическим файлам: Райффайзенбанк (CSV, остатков нет — сверка «нет данных»), Bank of Georgia
    (XLSX, остатки по валютам сходятся / не сходятся — расхождение на X); банки с PDF (FF, Т-Банк) сайт не разбирает —
    даже если файл похож на их выписку, ответ 422 «банк не узнан» с перечнем умеемого (только Райффайзенбанк и BOG);
  • банк не узнан → 422, нет файла → 404, плохой id → 400; путей с pdftotext и ответа 503 в модуле нет;
  • флаги — только то, что дали скрипты (строка не распознана, проверка не сошлась); счёт в отчёте — последние 4 знака;
  • сравнение с ZenMoney: по last.csv и aux/accounts.json — «есть в выписке, нет в ZenMoney» и обратное; нет выгрузки / счёт не
    сопоставился (два подходящих) → честная причина, а не молчание;
  • только чтение: после отчёта в дереве Claude-Memory не появилось ни одного нового файла, `save` не вызывался;
  • hub-api: тип по содержимому (XLSX / CSV; имя не читается; PDF — 400 «PDF на сайте не разбирается…»; zip не-xlsx, двоичный и пустой файл — 400), отдельный лимит
    тела (413), файл стирается сразу после отчёта при любом исходе (успех, 422, hub-notify недоступен), брошенный старше часа —
    при следующей загрузке; поля прокси ограничены {id}; /api/health.zm_stmt.
Данные синтетические. Сеть не нужна. Запуск: python3 tools/tests/test_zm_stmt.py
"""
import base64
import csv
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import serve  # noqa: E402
sys.path.insert(0, str(REPO / "tools/hosting/api"))
sys.path.insert(0, str(REPO / "tools/hosting/notify"))

import server  # noqa: E402
import zm_csv  # noqa: E402
import zm_stmt  # noqa: E402
import parse_raif_statement as pr  # noqa: E402  (путь к скриптам скилла добавил zm_csv)
import stmt_import  # noqa: E402

try:
    import openpyxl
except ImportError:
    openpyxl = None

MSK = timezone(timedelta(hours=3))
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=MSK)
ID = "2026-11-10-1a2b3c4d"
ACC = "40817810800000001234"          # синтетический номер: в отчёте должны остаться только последние 4 знака


def _req(port, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except ValueError:
            return e.code, {}


# ─── синтетические выписки ───────────────────────────────────────────────────

def raif_line(dt, doc, amt, text, card=""):
    inc, out = (amt, "") if not amt.startswith("-") else ("", amt[1:])
    return ";".join(f'"{x}"' for x in (dt, dt[:10], doc, inc, out, "RUB", inc, out, "RUB", " " + text, card))


RAIF_ROWS = [
    raif_line("06.10.2026 12:00", "D2", "100 000,00", f"рублевый перевод,Заработная плата за Октябрь 2026 р/с {ACC} Тест,номер счета отправителя-40702810700000000001 На счет: 40817810******1234"),
    raif_line("05.10.2026 10:00", "D1", "-250,00", "Тестовый Магазин", "*1111"),
    raif_line("07.10.2026 09:00", "D3", "-1 500,00", "Рублевый перевод между счетами Клиента Со счета: *1234 На счет: *5678"),
    raif_line("08.10.2026 09:00", "D4", "-10,00", "Что-то непонятное"),
]
RAIF_CSV = ("﻿" + ";".join(pr.HEADER) + "\r\n" + "\r\n".join(RAIF_ROWS) + "\r\n").encode("utf-8")


def bog_xlsx(path, closing_usd="90.00"):
    wb = openpyxl.Workbook()
    d = wb.active
    d.title = "Details"
    d.append(["Account Statement"])
    d.append(["Account Owner:", None, "Test Owner"])
    d.append(["Account No:", None, "GE00BG0000000000000001"])
    d.append(["Card:", None, "MC Standard Test (1111)"])
    d.append(["Filter Date From:", None, "01/03/2026"])
    d.append(["Filter Date To:", None, "31/03/2026"])
    d.append(["Starting Balance:", None, "100.00USD"])
    d.append(["End Balance:", None, f"{closing_usd}USD"])
    t = wb.create_sheet("Transactions")
    t.append(["Date", "Details", None, "GEL", "USD", "EUR", "GBP"])
    t.append(["02/03/2026", " Payment - Amount: USD10.00; Merchant: COFFEE, Georgia; MCC:5814; Date: 02/03/2026 09:00; Card No: ****1111; "
              "Payment transaction amount and currency: 10.00 USD", None, None, -10.0, None, None])
    t.append(["Balance", " ", None, 0, 90.0, 0, 0])
    wb.save(path)


def zen_csv(rows):
    cols = list(zm_csv.REQUIRED_COLUMNS)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, delimiter=";", lineterminator="\n")
    w.writeheader()
    for i, r in enumerate(rows):
        base = {c: "" for c in cols}
        base.update(createdDate=f"{r['date']} 10:{i:02d}:00", changedDate=f"{r['date']} 10:{i:02d}:00", **r)
        w.writerow(base)
    return buf.getvalue().encode("utf-8")


def make_root(files=None, last=None, accounts=None):
    root = Path(tempfile.mkdtemp(prefix="zmstmt-"))
    (root / zm_stmt.STMT_DIR).mkdir(parents=True)
    for name, raw in (files or {}).items():
        (root / zm_stmt.STMT_DIR / name).write_bytes(raw)
    if last is not None:
        (root / "ZenMoney/csv").mkdir(parents=True, exist_ok=True)
        (root / "ZenMoney/csv/last.csv").write_bytes(last)
    if accounts is not None:
        (root / "ZenMoney/csv/aux").mkdir(parents=True, exist_ok=True)
        (root / "ZenMoney/csv/aux/accounts.json").write_text(json.dumps({"data": accounts}), encoding="utf-8")
    return root


def tree(root):
    return sorted(str(p.relative_to(root)) for p in Path(root).rglob("*") if p.is_file())


def acct(i, name, ccy):
    return {"id": i, "name": name, "instrument": ccy, "type": "ccard", "isSavings": False, "isArchived": False}


def no_save(path, content):
    raise AssertionError(f"отчёт обязан быть только чтением, а вызван save({path})")


class Report(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(getattr(self, "root", "/nonexistent"), ignore_errors=True)

    def run_route(self, root, id_=ID, body=None):
        return zm_stmt.route_report(root, body if body is not None else {"id": id_}, NOW, lambda p: (None, None), no_save)

    def test_raif_csv_report(self):
        self.root = make_root({f"{ID}.csv": RAIF_CSV})
        before = tree(self.root)
        code, rep = self.run_route(self.root)
        self.assertEqual(code, 200, rep)
        self.assertEqual((rep["schema"], rep["bank"], rep["format"]), ("zm-stmt-report@1", "raif", "csv"))
        self.assertEqual(rep["account"], "1234")                               # счёт — последние знаки (у Райфа в тексте и так 4)
        self.assertNotIn(ACC, str(rep["account"]))                            # поле «счёт» не несёт номер целиком; описание операций — текст банка как есть
        self.assertEqual((rep["period"], rep["ops_count"], rep["currencies"]), ({"from": "2026-10-05", "to": "2026-10-08"}, 4, ["RUB"]))
        self.assertEqual([o["date"] for o in rep["operations"]], ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"])
        self.assertEqual(rep["operations"][0]["amount"], "-250.00")
        self.assertEqual(rep["operations"][1]["amount"], "100000.00")
        b = rep["balances"][0]
        self.assertEqual((b["status"], b["opening"], b["diff"]), ("unavailable", None, None))   # у Райфа остатков в выписке нет
        self.assertIn("нет остатков", b["note"])
        kinds = [f["kind"] for f in rep["flags"]]
        self.assertIn("unknown-row", kinds)                                   # «Что-то непонятное» — флаг нормализатора
        self.assertEqual(next(f for f in rep["flags"] if f["kind"] == "unknown-row")["title"], "строка не распознана")
        self.assertFalse(rep["compare"]["available"])
        self.assertIn("last.csv", rep["compare"]["reason"])
        self.assertEqual(tree(self.root), before)                             # ничего не записано

    @unittest.skipIf(openpyxl is None, "нет openpyxl")
    def test_bog_xlsx_balances_match_and_mismatch(self):
        self.root = make_root()
        p = self.root / zm_stmt.STMT_DIR / f"{ID}.xlsx"
        bog_xlsx(p)
        code, rep = self.run_route(self.root)
        self.assertEqual(code, 200, rep)
        self.assertEqual((rep["bank"], rep["format"], rep["account"]), ("bog", "xlsx", "…0001"))
        usd = next(b for b in rep["balances"] if b["currency"] == "USD")
        self.assertEqual((usd["opening"], usd["sum_ops"], usd["closing"], usd["diff"], usd["status"]), ("100.00", "-10.00", "90.00", "0.00", "match"))
        self.assertTrue(rep["checks_ok"])
        self.assertEqual(rep["flags"], [])
        # исходящий остаток банка не сходится с расчётом: расхождение называется числом
        bog_xlsx(p, closing_usd="85.00")
        code, rep = self.run_route(self.root)
        self.assertEqual(code, 200, rep)
        usd = next(b for b in rep["balances"] if b["currency"] == "USD")
        self.assertEqual((usd["status"], usd["diff"]), ("mismatch", "-5.00"))
        self.assertFalse(rep["checks_ok"])
        self.assertIn("check-failed", [f["kind"] for f in rep["flags"]])

    def test_pdf_banks_are_not_site_banks(self):
        """Файл, по шапке похожий на FF или Т-Банк, сайт не разбирает: 422 «банк не узнан», перечень — только Райф и BOG."""
        self.root = make_root({f"{ID}.csv": b"a;b\n1;2\n"})
        old_head = stmt_import._read_head
        self.addCleanup(lambda: setattr(stmt_import, "_read_head", old_head))
        for head in ("Freedom Bank Kazakhstan", "АО «ТБанк»"):
            stmt_import._read_head = lambda p, limit=4000, h=head: h
            code, b = self.run_route(self.root)
            self.assertEqual(code, 422, head)
            self.assertIn("банк не узнан", b["error"])
            self.assertNotIn("Freedom", b["error"])
            self.assertNotIn("Т-Банк", b["error"])
        self.assertEqual(zm_stmt.SITE_BANKS, ("raif", "bog"))
        self.assertEqual(zm_stmt.EXTS, ("xlsx", "csv"))
        self.assertFalse(hasattr(zm_stmt, "shutil"))                            # проверки pdftotext в модуле нет

    def test_refusals(self):
        self.root = make_root({f"{ID}.csv": b"a;b\n1;2\n"})
        code, b = self.run_route(self.root)
        self.assertEqual(code, 422)                                           # банк не узнан, перечень умеемого
        self.assertIn("банк не узнан", b["error"])
        self.assertIn("Райффайзенбанк", b["error"])
        self.assertEqual(self.run_route(self.root, "2026-11-10-ffffffff")[0], 404)
        self.assertEqual(self.run_route(self.root, body={"id": "../x"})[0], 400)
        self.assertEqual(self.run_route(self.root, body={})[0], 400)
        # парсер банка отказал (чужая шапка колонок) — понятная причина, не 500
        (self.root / zm_stmt.STMT_DIR / f"{ID}.csv").write_bytes(
            ("﻿" + ";".join(pr.HEADER[:-1]) + "\n1;2\n").encode("utf-8"))
        code, b = self.run_route(self.root)
        self.assertIn(code, (422,))

    def test_compare_with_zenmoney_csv(self):
        accounts = [acct("a1", "Райффайзен карта", "RUB"), acct("a2", "Наличные", "RUB")]
        last = zen_csv([
            {"date": "2026-10-05", "categoryName": "Покупки", "payee": "Тестовый Магазин", "outcomeAccountName": "Райффайзен карта", "outcome": "250", "outcomeCurrencyShortTitle": "RUB"},
            {"date": "2026-10-09", "categoryName": "Еда", "payee": "Лишнее место", "outcomeAccountName": "Райффайзен карта", "outcome": "77", "outcomeCurrencyShortTitle": "RUB"},
            {"date": "2026-10-20", "categoryName": "Еда", "payee": "Вне окна", "outcomeAccountName": "Райффайзен карта", "outcome": "5", "outcomeCurrencyShortTitle": "RUB"},
            {"date": "2026-10-05", "categoryName": "Еда", "payee": "Чужой счёт", "outcomeAccountName": "Наличные", "outcome": "999", "outcomeCurrencyShortTitle": "RUB"},
        ])
        self.root = make_root({f"{ID}.csv": RAIF_CSV}, last=last, accounts=accounts)
        before = tree(self.root)
        code, rep = self.run_route(self.root)
        self.assertEqual(code, 200, rep)
        c = rep["compare"]
        self.assertTrue(c["available"], c)
        self.assertEqual(c["window"], {"from": "2026-10-05", "to": "2026-10-08"})
        self.assertEqual(c["accounts"], {"RUB": "Райффайзен карта"})
        self.assertEqual(c["matched"], 1)                                      # покупка 250 нашла пару
        self.assertEqual([(o["date"], o["amount"]) for o in c["missing_in_zen"]], [("2026-10-06", "100000.00")])   # зарплата — нет в ZenMoney
        # ZenMoney-операции 09.10 и 20.10 вне окна выписки (05–08.10) — в «нет в выписке» не попадают; чужой счёт игнорируется
        self.assertEqual(c["missing_in_bank"], [])
        self.assertEqual(c["missing_in_bank_total"], 0)
        self.assertEqual(tree(self.root), before)

    def test_compare_missing_in_bank_inside_window(self):
        accounts = [acct("a1", "Райффайзен карта", "RUB")]
        last = zen_csv([
            {"date": "2026-10-07", "categoryName": "Еда", "payee": "Лишнее место", "outcomeAccountName": "Райффайзен карта", "outcome": "77", "outcomeCurrencyShortTitle": "RUB"},
        ])
        self.root = make_root({f"{ID}.csv": RAIF_CSV}, last=last, accounts=accounts)
        code, rep = self.run_route(self.root)
        c = rep["compare"]
        self.assertEqual([(o["date"], o["amount"], o["currency"], o["text"]) for o in c["missing_in_bank"]],
                         [("2026-10-07", "-77.00", "RUB", "Лишнее место")])
        self.assertEqual(c["matched"], 0)

    def test_compare_account_not_matched(self):
        two = [acct("a1", "Райффайзен карта", "RUB"), acct("a2", "Райффайзен вклад", "RUB")]
        self.root = make_root({f"{ID}.csv": RAIF_CSV}, last=zen_csv([]), accounts=two)
        c = self.run_route(self.root)[1]["compare"]
        self.assertFalse(c["available"])
        self.assertIn("счёт не сопоставлен", c["reason"])
        self.assertIn("сравнение с ZenMoney недоступно", c["reason"])
        shutil.rmtree(self.root)
        self.root = make_root({f"{ID}.csv": RAIF_CSV}, last=zen_csv([]), accounts=[acct("a3", "Другой банк", "RUB")])
        c = self.run_route(self.root)[1]["compare"]
        self.assertFalse(c["available"])
        self.assertIn("подходящего счёта нет", c["reason"])
        shutil.rmtree(self.root)
        self.root = make_root({f"{ID}.csv": RAIF_CSV}, last=zen_csv([]))
        self.assertIn("accounts.json", self.run_route(self.root)[1]["compare"]["reason"])

    def test_journal_has_no_private_text(self):
        self.root = make_root({f"{ID}.csv": RAIF_CSV})
        lines = []
        zm_stmt.route_report(self.root, {"id": ID}, NOW, lambda p: (None, None), no_save, lambda *a, **k: lines.append((a, k)))
        self.assertEqual(len(lines), 1)
        blob = json.dumps(lines, ensure_ascii=False, default=str)
        self.assertIn("raif", blob)
        for secret in ("Тестовый Магазин", ACC, "100000", "1234"):
            self.assertNotIn(secret, blob)

    def test_number_text_helpers(self):
        self.assertEqual(zm_stmt._mask("GE00BG0000000000000001"), "…0001")
        self.assertEqual(zm_stmt._mask("123"), "123")
        self.assertIsNone(zm_stmt._mask(None))
        self.assertEqual(zm_stmt._iso("03.10.2026"), "2026-10-03")
        self.assertIsNone(zm_stmt._iso("не дата"))


class HubApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.old_root = server.ROOT
        server.ROOT = cls.tmp
        cls.httpd = serve(server.Handler, quiet=False)[0]
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        server.ROOT = cls.old_root
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        shutil.rmtree(Path(self.tmp, server.ZM_STMT_DIR), ignore_errors=True)

    def files(self):
        d = Path(self.tmp, server.ZM_STMT_DIR)
        return sorted(p.name for p in d.iterdir()) if d.is_dir() else []

    def upload(self, raw, name="выписка.csv"):
        return _req(self.port, "POST", "/api/zm/stmt", {"name": name, "b64": base64.b64encode(raw).decode()})

    def test_type_by_content_not_by_name(self):
        xlsx = io.BytesIO()
        import zipfile
        with zipfile.ZipFile(xlsx, "w") as z:
            z.writestr("xl/workbook.xml", "<x/>")
        cases = [(xlsx.getvalue(), "xlsx"), ("a;b\n1;2\n".encode(), "csv"),
                 ("﻿a;b\r\n1;2\r\n".encode("utf-8"), "csv"), ("дата;сумма\n1;2\n".encode("cp1251"), "csv")]
        for raw, fmt in cases:
            c, b = self.upload(raw, name="x.csv" if fmt != "csv" else "x.pdf")     # имя врёт — тип берётся из содержимого
            self.assertEqual(c, 200, b)
            self.assertEqual((b["format"], b["size"]), (fmt, len(raw)))
            self.assertTrue(Path(self.tmp, f"{server.ZM_STMT_DIR}/{b['id']}.{fmt}").is_file())
            self.assertEqual(Path(self.tmp, f"{server.ZM_STMT_DIR}/{b['id']}.{fmt}").read_bytes(), raw)
        today = datetime.now(MSK).strftime("%Y-%m-%d")
        self.assertTrue(b["id"].startswith(today + "-"))

    def test_pdf_rejected_at_input(self):
        """PDF отклоняется на входе тем же кодом, что остальные отказы по типу файла (400), текстом без упоминания Claude."""
        want = "PDF на сайте не разбирается — поддержаны CSV Райффайзенбанка и XLSX BOG"
        for raw, name in (("%PDF-1.7 тело".encode(), "x.pdf"), (b"%PDF-1.4\n" + b"x" * 500, "выписка.csv")):
            c, b = self.upload(raw, name=name)
            self.assertEqual(c, 400, b)
            self.assertEqual(b["detail"], want)
            self.assertNotIn("Claude", b["detail"])
        self.assertEqual(self.files(), [])

    def test_rejects(self):
        notbook = io.BytesIO()
        import zipfile
        with zipfile.ZipFile(notbook, "w") as z:
            z.writestr("a.txt", "x")
        for raw, why in ((b"", "пуст"), (notbook.getvalue(), "xlsx"), (b"\x00\x01\x02" * 100, "двоичный"), ("просто текст без таблицы".encode(), "выписку"),
                         ("\xff\xfe".encode("latin-1") * 4, "выписку")):
            c, b = self.upload(raw)
            self.assertEqual(c, 400, (raw[:10], b))
            self.assertIn(why, b["detail"])
        self.assertEqual(_req(self.port, "POST", "/api/zm/stmt", {"name": "x", "b64": "!!!"})[0], 400)
        self.assertEqual(_req(self.port, "POST", "/api/zm/stmt", {"name": "x"})[0], 400)
        self.assertEqual(self.files(), [])                                      # отказанное на диск не попало

    def test_body_limit(self):
        old = server.ZM_STMT_MAX_BYTES
        server.ZM_STMT_MAX_BYTES = 2000
        try:
            c, b = self.upload(b"a;b\n1;2\n" + b"x" * 3000)
        finally:
            server.ZM_STMT_MAX_BYTES = old
        self.assertEqual((c, b["error"]), (413, "body too large"))
        self.assertEqual(self.files(), [])
        self.assertEqual(self.upload(b"a;b\n1;2\n" + b"x" * 3000)[0], 200)            # штатный лимит не мешает
        self.assertLess(server.ZM_STMT_MAX_BYTES, server.ZM_CSV_MAX_BYTES)        # у выписок свой, меньший лимит

    def test_stale_swept_on_next_upload(self):
        c, b = self.upload(b"a;b\n1;2a\n")
        stale = Path(self.tmp, f"{server.ZM_STMT_DIR}/{b['id']}.csv")
        old = time.time() - server.ZM_STMT_TTL - 60
        os.utime(stale, (old, old))
        c, b2 = self.upload(b"a;b\n1;2b\n")
        self.assertEqual(c, 200)
        self.assertFalse(stale.exists())                                         # брошенный старше часа стёрт
        self.assertEqual(self.files(), [f"{b2['id']}.csv"])

    def _proxy(self, fake):
        calls, orig = [], urllib.request.urlopen

        def wrapped(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else req
            if url.startswith(server.NOTIFY_URL):
                calls.append((url[len(server.NOTIFY_URL):], json.loads(req.data), timeout))
                return fake(url)
            return orig(req, timeout=timeout)
        urllib.request.urlopen = wrapped
        self.addCleanup(lambda: setattr(urllib.request, "urlopen", orig))
        return calls

    class _Resp:
        status = 200

        def read(self):
            return b'{"schema": "zm-stmt-report@1"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def test_report_proxy_deletes_file_after(self):
        calls = self._proxy(lambda url: self._Resp())
        c, b = self.upload(b"a;b\n1;2x\n")
        i = b["id"]
        c, rep = _req(self.port, "POST", "/api/zm/stmt-report", {"id": i, "лишнее": 1, "confirm": True})
        self.assertEqual((c, rep["schema"]), (200, "zm-stmt-report@1"))
        self.assertEqual(calls, [("/internal/zm-stmt-report", {"id": i}, 120)])   # лишние поля отброшены
        self.assertEqual(self.files(), [])                                          # файл стёрт сразу после ответа

    def test_report_proxy_deletes_on_refusal_and_on_notify_down(self):
        def refuse(url):
            raise urllib.error.HTTPError(url, 422, "x", {}, io.BytesIO(json.dumps({"error": "банк не узнан"}, ensure_ascii=False).encode("utf-8")))
        self._proxy(refuse)
        i = self.upload(b"a;b\n1;2y\n")[1]["id"]
        c, b = _req(self.port, "POST", "/api/zm/stmt-report", {"id": i})
        self.assertEqual((c, b["error"]), (422, "банк не узнан"))                   # код и причина hub-notify доходят до страницы
        self.assertEqual(self.files(), [])
        # hub-notify недоступен: подменяем на OSError
        orig = urllib.request.urlopen

        def down(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else req
            if url.startswith(server.NOTIFY_URL):
                raise OSError("нет связи")
            return orig(req, timeout=timeout)
        urllib.request.urlopen = down
        self.addCleanup(lambda: setattr(urllib.request, "urlopen", orig))
        i = self.upload(b"a;b\n1;2z\n")[1]["id"]
        c, b = _req(self.port, "POST", "/api/zm/stmt-report", {"id": i})
        self.assertEqual(c, 502)
        self.assertIn("hub-notify", b["error"])
        self.assertEqual(self.files(), [])                                          # и тут не оставляем выписку на диске

    def test_report_bad_id_and_health(self):
        self.assertEqual(_req(self.port, "POST", "/api/zm/stmt-report", {"id": "../../x"})[0], 400)
        self.assertEqual(_req(self.port, "POST", "/api/zm/stmt-report", {})[0], 400)
        c, h = _req(self.port, "GET", "/api/health")
        self.assertEqual(c, 200)
        self.assertTrue(h.get("zm_stmt"))

    def test_zone_is_not_job_writable(self):
        # временная зона не входит в белый список задач: через /api/job/save выписку не подложить
        path = f"{server.ZM_STMT_DIR}/{ID}.csv"
        self.assertFalse(any(rx.match(path) for rx in server.JOB_WHITELIST))


if __name__ == "__main__":
    unittest.main(verbosity=1)
