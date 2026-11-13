#!/usr/bin/env python3
"""Задачи сайта по расписанию (API-1, пробный месяц с 2026-10-21): цены US eShop и макросрез.

Контракты:
  • hub-api, зона /api/job/*: только изнутри docker-сети (X-Forwarded-For от Caddy → 403);
    whitelist — eshop-prices.json и macro-snapshots/auto/ru-<дата>.md|json; перезапись — с
    base_hash и копией в .versions/; битый JSON → 400 без записи; журнал _jobs/log-ГГГГ-ММ.jsonl —
    только дописывание строки-JSON; кнопка /api/games/eshop-refresh — проброс в hub-notify
    с его кодом ответа (429 «рано» доходит до страницы);
  • eshop.py: цели — «хочу»/«на-карандаш» (в т. ч. с флагом demo; старое «демо» читается как на-карандаш) с nsuid_us; разбор живого ответа 21.10 (фикстура PR-7);
    скидка вне окна start..end не считается; not_found — без цены; порог; пачки по 50 id;
    сбой источника → status «unavailable» с прошлыми ценами и прошлым fetched_at; push —
    только когда порог выполнен впервые;
  • notifier: задачи в 08:30, повтор один раз в 09:00, после успеха — до завтра; макро только
    по будням; JOBS_OFF выключает; кнопка — не чаще раза в 10 минут и не параллельно;
  • macro_job: пишет в macro-snapshots/auto/, не рядом со срезами скилла; импортируется из /app/
    (корень контейнера) без IndexError;
  • eshop_lookup: nsuid только у объекта с urlKey == slug (на странице есть чужие); fill
    вставляет строки после title и не трогает остальной текст.
Сеть не нужна. Запуск: python3 tools/tests/test_site_jobs.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import serve  # noqa: E402  (стенд — _pages_stand, keep-alive)
sys.path.insert(0, str(REPO / "tools/hosting/api"))
sys.path.insert(0, str(REPO / "tools/hosting/notify"))
sys.path.insert(0, str(REPO / "tools"))

import server      # noqa: E402
import eshop       # noqa: E402
import jobs        # noqa: E402
import macro_job   # noqa: E402
import prices_job  # noqa: E402
import notifier    # noqa: E402
import eshop_lookup as el  # noqa: E402
import decision_job as dj  # noqa: E402
import condition_job as cj  # noqa: E402
sys.path.insert(0, str(REPO / "_shared-references"))
sys.path.insert(0, str(REPO / "tools/data-structures/migrations"))
import ds_schemas as ds  # noqa: E402
import migrate_conditions_v2 as mg  # noqa: E402

MSK = timezone(timedelta(hours=3))
FIX = REPO / "tools/tests/fixtures/eshop/price-us-2026-10-21.json"
NOW = datetime(2026, 10, 21, 8, 30, tzinfo=MSK)


def _req(port, method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


class JobZone(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.old_root = server.ROOT
        server.ROOT = cls.tmp
        cls.httpd = serve(server.Handler, quiet=False)[0]   # _pages_stand: очередь 128, keep-alive
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        server.ROOT = cls.old_root
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_create_overwrite_backup(self):
        p = "Gaming/eshop-prices.json"
        self.assertEqual(_req(self.port, "GET", "/api/job/file?path=" + p)[0], 404)
        c, b = _req(self.port, "POST", "/api/job/save", {"path": p, "content": '{"a": 1}', "base_hash": None})
        self.assertEqual(c, 200)
        c, b2 = _req(self.port, "POST", "/api/job/save", {"path": p, "content": '{"a": 2}', "base_hash": b["hash"]})
        self.assertEqual(c, 200)
        self.assertEqual(_req(self.port, "GET", "/api/job/file?path=" + p)[1]["content"], '{"a": 2}')
        backups = list(Path(self.tmp, ".versions/Gaming").glob("*_eshop-prices.json"))
        self.assertEqual(len(backups), 1)                      # прошлая версия сохранена
        self.assertEqual(backups[0].read_text(), '{"a": 1}')

    def test_overlay_readable_not_writable(self):
        """Кнопка «Обновить цены» (2026-11-09): hub-notify читал Gaming/user-state.json через /api/job/file
        и получал 403 «path not in whitelist» — пороги и nsuid оверлея недоступны ценам. Чтение оверлея в зоне
        задач разрешено, запись — нет (его пишет только страница через /api/gm/save)."""
        p = "Gaming/user-state.json"
        Path(self.tmp, "Gaming").mkdir(parents=True, exist_ok=True)
        Path(self.tmp, p).write_text('{"schema": "gaming-user@1", "items": []}', encoding="utf-8")
        c, b = _req(self.port, "GET", "/api/job/file?path=" + p)
        self.assertEqual(c, 200)
        self.assertIn("gaming-user@1", b["content"])
        c, _ = _req(self.port, "POST", "/api/job/save", {"path": p, "content": "{}", "base_hash": b["hash"]})
        self.assertEqual(c, 403)

    def test_through_caddy_is_forbidden(self):              # X-Forwarded-For = пришло снаружи
        h = {"X-Forwarded-For": "1.2.3.4"}
        self.assertEqual(_req(self.port, "GET", "/api/job/file?path=Gaming/eshop-prices.json", headers=h)[0], 403)
        c, _ = _req(self.port, "POST", "/api/job/save",
                    {"path": "macro-snapshots/auto/ru-2026-10-21.md", "content": "x", "base_hash": None}, h)
        self.assertEqual(c, 403)

    def test_whitelist_and_json(self):
        for p in ("Gaming/watchlist.yaml", "macro-snapshots/ru-2026-10-21.md", "Portfolio/x.json"):
            c, _ = _req(self.port, "POST", "/api/job/save", {"path": p, "content": "x", "base_hash": None})
            self.assertEqual(c, 403, p)
        c, _ = _req(self.port, "POST", "/api/job/save",
                    {"path": "macro-snapshots/auto/ru-2026-10-22.json", "content": "{битый", "base_hash": None})
        self.assertEqual(c, 400)
        self.assertFalse(Path(self.tmp, "macro-snapshots/auto/ru-2026-10-22.json").exists())

    def test_owner_decision_new_file_only(self):
        """Решение владельца с сайта (decision_job): путь Portfolio/decisions/{дата}T{ЧЧММ}-{KEY}.json в зоне задач;
        файл всегда новый — повтор с base_hash=null при существующем файле = 409 (не перезапись), с чужим хэшем
        перезапись тоже невозможна для решения (запись создаёт только save_new)."""
        p = "Portfolio/decisions/2026-11-11T1015-GMKN.json"
        body = {"path": p, "content": '{"id": "2026-11-11T1015-GMKN"}', "base_hash": None}
        c, b = _req(self.port, "POST", "/api/job/save", body)
        self.assertEqual(c, 200)
        c, b2 = _req(self.port, "POST", "/api/job/save", {**body, "content": '{"id": "другое"}'})
        self.assertEqual(c, 409)                                        # существует — создание не перезаписывает
        self.assertEqual(Path(self.tmp, p).read_text(), '{"id": "2026-11-11T1015-GMKN"}')
        for bad in ("Portfolio/decisions/2026-11-11T1015-gmkn.json", "Portfolio/decisions/2026-11-11T1015-.json",
                    "Portfolio/decisions/x.json", "Portfolio/decisions/sub/2026-11-11T1015-GMKN.json",
                    "Portfolio/decisions/2026-11-11T1015-GMKN.json.tmp"):
            c, _ = _req(self.port, "POST", "/api/job/save", {"path": bad, "content": "{}", "base_hash": None})
            self.assertEqual(c, 403, bad)

    def test_log_append_only(self):
        p = "_jobs/log-2026-10.jsonl"
        for i in range(2):
            self.assertEqual(_req(self.port, "POST", "/api/job/append", {"path": p, "line": json.dumps({"i": i})})[0], 200)
        self.assertEqual(Path(self.tmp, p).read_text().splitlines(), ['{"i": 0}', '{"i": 1}'])
        self.assertEqual(_req(self.port, "POST", "/api/job/append",
                              {"path": "Gaming/eshop-prices.json", "line": "{}"})[0], 403)
        self.assertEqual(_req(self.port, "POST", "/api/job/append", {"path": p, "line": "не json"})[0], 400)
        self.assertFalse(Path(self.tmp, ".versions/_jobs").exists())     # журнал без копий

    def test_refresh_passes_notify_answer(self):
        class Fake(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                b = json.dumps({"ok": False, "retry_after": 300}).encode()
                self.send_response(429)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
        fake = serve(Fake, quiet=False)[0]
        old = server.NOTIFY_URL
        server.NOTIFY_URL = f"http://127.0.0.1:{fake.server_address[1]}"
        try:
            c, b = _req(self.port, "POST", "/api/games/eshop-refresh", {})
            self.assertEqual((c, b["retry_after"]), (429, 300))
        finally:
            server.NOTIFY_URL = old
            fake.shutdown()
            fake.server_close()


WL = {"items": [
    {"title": "Undertale", "status": "хочу", "nsuid_us": "70010000009921", "price_target_usd": 10},
    {"title": "Skyrim", "status": "на-карандаш", "nsuid_us": 70070000015127},
    {"title": "Нет nsuid", "status": "хочу"},
    {"title": "Отказ", "status": "не-интересно", "nsuid_us": "70010000058660"},
    {"title": "Пропала", "status": "хочу", "nsuid_us": "70010000000001"},
]}


class Eshop(unittest.TestCase):
    def setUp(self):
        self.resp = json.loads(FIX.read_text())

    def test_targets(self):
        tg, sk = eshop.targets(WL)
        self.assertEqual([t["title"] for t in tg], ["Undertale", "Skyrim", "Пропала"])
        self.assertEqual(tg[1]["nsuid_us"], "70070000015127")            # число из YAML → строка
        self.assertEqual(sk, [{"title": "Нет nsuid", "reason": "нет nsuid_us"}])

    def test_targets_include_demo(self):
        """«демо» (играл, не купил) тоже ждёт цену: берётся и из watchlist, и из оверлея."""
        tg, _ = eshop.targets({"items": [{"title": "Демка", "status": "демо", "nsuid_us": "70010000012345"}]})
        self.assertEqual([t["title"] for t in tg], ["Демка"])
        over = {"items": [{"title": "Dave", "state": "демо", "nsuid_us": "70010000099999", "deleted": False},
                          {"title": "Flagged", "state": "на-карандаш", "demo": True, "nsuid_us": "70010000077777", "deleted": False},
                          {"title": "Flagged Want", "state": "хочу", "demo": True, "nsuid_us": "70010000066666", "deleted": False},
                          {"title": "Flagged Nope", "state": "не-интересно", "demo": True, "nsuid_us": "70010000055555", "deleted": False},
                          {"title": "Old Nope", "state": "демо", "rating": "не понравилось", "nsuid_us": "70010000044444", "deleted": False},
                          {"title": "Куплена", "state": "куплена", "nsuid_us": "70010000088888", "deleted": False}]}
        tg, _ = eshop.targets({}, over)
        # флаг demo цель не отменяет и не создаёт; старое «демо» = на-карандаш (при «не понравилось» — не хочу, цели нет)
        self.assertEqual([t["title"] for t in tg], ["Dave", "Flagged", "Flagged Want"])

    def test_report_from_live_answer(self):
        tg, sk = eshop.targets(WL)
        rep = eshop.report(tg, sk, [self.resp], NOW)
        by = {i["title"]: i for i in rep["items"]}
        u = by["Undertale"]
        self.assertEqual((u["regular_usd"], u["sale_usd"], u["discount_pct"], u["sale_end"][:10]),
                         (14.99, 9.89, 34, "2026-11-01"))
        self.assertTrue(u["target_met"])                               # 9.89 ≤ 10
        self.assertFalse(by["Skyrim"]["target_met"])                   # порога нет
        self.assertEqual((by["Пропала"]["sales_status"], by["Пропала"]["price_usd"]), ("not_found", None))

    def test_discount_outside_window_ignored(self):
        later = datetime(2026, 11, 5, 9, 0, tzinfo=MSK)                # скидка Undertale кончилась 01.11
        u = eshop.parse(self.resp, later)["70010000009921"]
        self.assertEqual((u["sale_usd"], u["regular_usd"]), (None, 14.99))

    def test_changed_format_raises(self):
        with self.assertRaises(ValueError):
            eshop.parse({"error": {"code": 4004}}, NOW)

    def test_batches_of_50(self):
        calls = []

        def opener(url, timeout=0):
            calls.append(url.split("ids=")[1].count(",") + 1)
            return io.BytesIO(b'{"prices": []}')
        eshop.fetch([str(70010000000000 + i) for i in range(51)], opener)
        self.assertEqual(calls, [50, 1])

    def test_unavailable_keeps_old_prices(self):
        old = eshop.report(*eshop.targets(WL), [self.resp], NOW)
        bad = eshop.unavailable(old, "HTTP 503", NOW + timedelta(days=1))
        self.assertEqual((bad["status"], bad["fetched_at"], len(bad["items"])),
                         ("unavailable", old["fetched_at"], len(old["items"])))
        self.assertFalse(eshop.fresh(bad, NOW + timedelta(days=1, hours=1)))   # время цен не обновилось

    def test_target_event_only_first_time(self):
        rep = eshop.report(*eshop.targets(WL), [self.resp], NOW)
        evs = eshop.target_events(None, rep)
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["kind"], "eshop")
        self.assertEqual(evs[0]["title"], "Undertale −34%: $9.89")                  # заголовок ≤ 32 знаков, конец скидки — в теле
        self.assertIn("до 01.11", evs[0]["body"])
        self.assertEqual(eshop.target_events(rep, rep), [])

    def test_sale_event_new_sale_only(self):
        rep = eshop.report(*eshop.targets(WL), [self.resp], NOW)
        sales = [i for i in rep["items"] if i["sale_usd"] is not None]
        sale = next(i for i in sales if i["target_met"])                           # Undertale, порог $10
        plain = {**rep, "items": [{**i, "sale_usd": None, "sale_end": None, "discount_pct": None, "target_met": False}
                                  for i in rep["items"]]}
        no_tgt = {**rep, "items": [{**i, "price_target_usd": None, "target_met": False} for i in rep["items"]]}
        evs = eshop.sale_events({**plain, "items": [{**i, "price_target_usd": None} for i in plain["items"]]}, no_tgt)
        self.assertEqual(len(evs), len(sales))
        self.assertEqual({(e["kind"], e["url"]) for e in evs}, {("eshop_sale", "/tools/games.html#sale")})
        self.assertTrue(any(f"${sale['sale_usd']:.2f}" in e["title"] and "до 01.11" in e["body"] for e in evs))
        self.assertEqual(eshop.sale_events(no_tgt, no_tgt), [])                     # та же скидка — молчим
        nxt = {**no_tgt, "items": [{**i, "sale_end": "2026-12-01T15:59:59Z"} if i["sale_usd"] is not None else i
                                   for i in no_tgt["items"]]}
        self.assertEqual(len(eshop.sale_events(no_tgt, nxt)), len(sales))             # следующая распродажа — снова
        # порог выполнен впервые в этот же прогон — только уведомление «eshop», без дубля
        self.assertNotIn(sale["nsuid_us"], {e["key"].split(":")[1] for e in eshop.sale_events(plain, rep)})
        self.assertIsNone(eshop.sale_summary(evs[:1]))
        self.assertIn("Скидки на 2 игры", eshop.sale_summary(evs[:1] * 2)["title"])

    def test_percent_threshold_and_texts(self):
        tg, sk = eshop.targets(WL)
        u = next(t for t in tg if t["nsuid_us"] == "70010000009921")                # Undertale, −34%
        rest = [t for t in tg if t is not u]
        wl = {"items": [{"title": "Undertale", "status": "хочу", "nsuid_us": "70010000009921", "discount_target_pct": -30}]}
        self.assertEqual(eshop.targets(wl)[0][0]["discount_target_pct"], 30)          # «−30» в YAML → 30
        pct = eshop.report([{**u, "price_target_usd": None, "discount_target_pct": 30}] + rest, sk, [self.resp], NOW)
        self.assertTrue(pct["items"][0]["target_met"])                                # 34% ≥ 30%
        ev = eshop.target_events(None, pct)
        self.assertEqual(ev[0]["title"], "Undertale −34%: $9.89")
        self.assertEqual(ev[0]["body"], "Порог −30% выполнен · было $14.99 · до 01.11\nИгры → Присматриваюсь")
        both = eshop.report([{**u, "price_target_usd": 5.0, "discount_target_pct": 50}] + rest, sk, [self.resp], NOW)
        self.assertFalse(both["items"][0]["target_met"])                             # $9.89 > $5, 34% < 50%
        plain = {**both, "items": [{**x, "sale_usd": None, "sale_end": None, "discount_pct": None} for x in both["items"]]}
        sv = [e for e in eshop.sale_events(plain, both) if "Undertale" in e["title"]]
        self.assertIn("до порога $5.00 или −50% не дотянула", sv[0]["body"])           # скидка без пробития — всё равно push
        met_before = {**both, "items": [{**x, "target_met": True} for x in both["items"]]}
        prev = {**plain, "items": [{**x, "target_met": True} for x in plain["items"]]}
        sv = [e for e in eshop.sale_events(prev, met_before) if "Undertale" in e["title"]]
        self.assertIn("порог $5.00 или −50% выполнен", sv[0]["body"])                  # порог выполнен раньше — в тексте скидки

    def test_run_overlay_read_error_is_soft(self):
        """Ошибка чтения оверлея (SaveError hub-api, не OSError) роняла весь прогон — цены по watchlist без оверлея."""
        store = {}

        def read(p):
            if p == eshop.OVERLAY_PATH:
                raise RuntimeError("read Gaming/user-state.json: HTTP 403 path not in whitelist")
            return store.get(p), None
        rep, _, summ = eshop.run(lambda: WL, read, lambda p, c: store.__setitem__(p, c),
                                 NOW, lambda url, timeout=0: io.BytesIO(json.dumps(self.resp).encode()))
        self.assertEqual(summ["status"], "ok")
        self.assertIn("Gaming/eshop-prices.json", store)

    def test_run_source_down(self):
        store = {}

        def opener(url, timeout=0):
            raise urllib.error.URLError("timed out")
        rep, evs, summ = eshop.run(lambda: WL, lambda p: (store.get(p), None),
                                   lambda p, c: store.__setitem__(p, c), NOW, opener)
        self.assertEqual((summ["status"], rep["status"], evs), ("error", "unavailable", []))
        self.assertIn("Gaming/eshop-prices.json", store)


    def test_run_counts_preorder_apart(self):
        """Журнал 2026-10-21: предзаказ Metaphor считался в not_found."""
        resp = json.loads(json.dumps(self.resp))
        for pr in resp["prices"]:
            if str(pr["title_id"]) == "70070000015127":
                pr["sales_status"] = "preorder"
        store = {}
        _, _, summ = eshop.run(lambda: WL, lambda p: (store.get(p), None), lambda p, c: store.__setitem__(p, c),
                               NOW, lambda url, timeout=0: io.BytesIO(json.dumps(resp).encode()))
        self.assertEqual((summ["not_found"], summ["preorder"]), (1, 1))


class Schedule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = (notifier.DATA, jobs._call, jobs.JOBS_OFF)
        notifier.DATA = Path(self.tmp)
        jobs._call = lambda *a, **k: (200, {})                         # журнал в hub-api — заглушка

    def tearDown(self):
        notifier.DATA, jobs._call, jobs.JOBS_OFF = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def at(self, h, m, day=21):
        return datetime(2026, 10, day, h, m, tzinfo=MSK)

    def test_due_retry_and_done(self):
        js = {}
        self.assertFalse(notifier.job_due(js, self.at(8, 29), "eshop"))
        self.assertTrue(notifier.job_due(js, self.at(8, 30), "eshop"))
        notifier._mark(js, "eshop", self.at(8, 30), ok=False)
        self.assertFalse(notifier.job_due(js, self.at(8, 45), "eshop"))      # повтор не раньше 09:00
        self.assertTrue(notifier.job_due(js, self.at(9, 0), "eshop"))
        notifier._mark(js, "eshop", self.at(9, 0), ok=False)
        self.assertFalse(notifier.job_due(js, self.at(12, 0), "eshop"))      # одного повтора хватит
        self.assertTrue(notifier.job_due(js, self.at(8, 31, day=22), "eshop"))
        notifier._mark(js, "eshop", self.at(8, 31, day=22), ok=True)
        self.assertFalse(notifier.job_due(js, self.at(9, 5, day=22), "eshop"))

    def test_macro_weekdays_and_off(self):
        self.assertFalse(notifier.job_due({}, self.at(9, 0, day=24), "macro"))    # суббота
        self.assertTrue(notifier.job_due({}, self.at(9, 0, day=23), "macro"))
        jobs.JOBS_OFF = {"macro"}
        self.assertFalse(notifier.job_due({}, self.at(9, 0, day=23), "macro"))

    def test_tick_marks_state(self):
        ran = []
        notifier.jobs_tick(self.at(8, 30), runners={"eshop": lambda now: ran.append(now) or {"status": "ok"}})
        notifier.jobs_tick(self.at(8, 31), runners={"eshop": lambda now: ran.append(now) or {"status": "ok"}})
        self.assertEqual(len(ran), 1)
        self.assertEqual(json.loads(Path(self.tmp, "jobs.json").read_text())["eshop"]["ok_date"], "2026-10-21")

    def test_refresh_rate_limit_and_lock(self):
        ok = lambda now: {"status": "ok", "items": 3, "ts": now.isoformat()}  # noqa: E731
        self.assertEqual(notifier.eshop_refresh(self.at(12, 0), ok)[0], 200)
        c, b = notifier.eshop_refresh(self.at(12, 5), ok)
        self.assertEqual((c, b["retry_after"]), (429, 301))
        self.assertEqual(notifier.eshop_refresh(self.at(12, 11), ok)[0], 200)
        notifier._jobs_lock.acquire()
        try:
            self.assertEqual(notifier.eshop_refresh(self.at(12, 30), ok)[0], 409)
        finally:
            notifier._jobs_lock.release()

    def test_eshop_kind_listed(self):
        self.assertIn("eshop", notifier.KIND_IDS)


class MacroJob(unittest.TestCase):
    def test_writes_to_auto_folder(self):
        saved = {}
        rep = {"rows": [{"key": "usd_rub", "value": 84.0, "flag": ""},
                        {"key": "infl_week", "value": None, "flag": ""}]}
        summ = macro_job.run("/нет", lambda p, c: saved.__setitem__(p, c), "2026-10-21",
                             make=lambda d, h, i, infl_cbr: ("# md", rep))
        self.assertEqual(sorted(saved), ["macro-snapshots/auto/ru-2026-10-21.json",
                                         "macro-snapshots/auto/ru-2026-10-21.md"])
        self.assertEqual((summ["status"], summ["missing"]), ("ok", ["infl_week"]))

    def test_imports_from_container_root(self):
        """В контейнере модуль лежит в /app/: импорт не должен искать каталоги выше корня
        (2026-10-21 HERE.parents[2] → IndexError, hub-notify падал по кругу)."""
        src_path = os.path.join(os.path.dirname(macro_job.__file__), "macro_job.py")
        src = open(src_path, encoding="utf-8").read()
        before = list(sys.path)
        try:
            exec(compile(src, "/app/macro_job.py", "exec"), {"__file__": "/app/macro_job.py", "__name__": "mj"})
        finally:
            sys.path[:] = before


class PricesJob(unittest.TestCase):
    """Дневной ряд цен закрытия (prices_job): только вперёд, одна строка на торговую дату."""
    DAY = datetime(2026, 11, 11, 19, 0, tzinfo=MSK)          # среда
    HOLD = [{"ticker": "SBER", "asset_type": "stock", "qty": 10, "current_price_source": "moex_iss"},
            {"ticker": "SU26243RMFS4", "isin": "RU000A106E90", "asset_type": "bond", "qty": 5,
             "nominal_currency": "RUB", "current_price_source": "moex_iss"},
            {"ticker": "RU000A10XYZ1", "isin": "RU000A10XYZ1", "asset_type": "bond", "qty": 1,
             "nominal_currency": "USD", "current_price_source": "moex_iss"},
            {"ticker": "NOPRICE", "asset_type": "stock", "qty": 3, "current_price_source": "moex_iss"}]

    @staticmethod
    def quotes(kind="last", ts="2026-11-11 18:49:59"):
        d = kind == "prev_close"
        t = "2026-11-10" if d else ts
        return {"schema": "quotes@1", "fx": {"USD": 80.5, "date": "2026-11-11"}, "items": {
            "SBER": {"price": 300.1, "price_kind": kind, "ts": t},
            "RU000A106E90": {"price": 67.6, "price_kind": kind, "ts": t, "isin": "RU000A106E90",
                             "accrued_int": 43.5, "face_value": 1000.0, "face_unit": "SUR", "currency_id": "SUR"},
            "XS-USD": {"price": 98.0, "price_kind": kind, "ts": t, "isin": "RU000A10XYZ1",
                       "accrued_int": 1.2, "face_value": 1000.0, "face_unit": "USD", "currency_id": "SUR"}}}

    def setUp(self):
        self.old = prices_job.holdings
        prices_job.holdings = lambda root: self.HOLD
        self.files = {}

    def tearDown(self):
        prices_job.holdings = self.old

    def go(self, q, now=None):
        return prices_job.run("/нет", "http://x/q?boards=TQBR", now or self.DAY, fetch=lambda url: q,
                              read=lambda p: (self.files.get(p), None),
                              save=lambda p, c: self.files.__setitem__(p, c))

    def test_holdings_only_exchange_priced(self):
        """Держимые — только с биржевой оценкой (moex_*): cost_basis (заморозка), last_trade (внебиржевой FINAMAR),
        заблокированные и проданные в ряд не идут — иначе каждый день «missing» и статус partial."""
        tmp = tempfile.mkdtemp()
        try:
            sd = os.path.join(tmp, "Portfolio", "snapshots")
            os.makedirs(sd)
            hs = [{"ticker": "SBER", "qty": 10, "current_price_source": "moex_iss"},
                  {"ticker": "FINAMAR", "qty": 5, "current_price_source": "last_trade"},
                  {"ticker": "FXUS", "qty": 7, "current_price_source": "cost_basis"},
                  {"ticker": "ABT", "qty": 2, "current_price_source": "moex_iss", "status": "blocked"},
                  {"ticker": "GONE", "qty": 0, "current_price_source": "moex_iss"}]
            with open(os.path.join(sd, "portfolio-2026-11-11.json"), "w", encoding="utf-8") as f:
                json.dump({"as_of_date": "2026-11-11", "holdings": hs}, f)
            prices_job.holdings = self.old   # настоящая функция, не подмена из setUp
            self.assertEqual([h["ticker"] for h in prices_job.holdings(tmp)], ["SBER"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_row_from_snapshot_and_quotes(self):
        summ = self.go(self.quotes())
        self.assertEqual((summ["status"], summ["items"], summ["missing"], summ["fx"]), ("partial", 3, ["NOPRICE"], ["USD"]))
        (line,) = self.files["Portfolio/prices/daily-2026.jsonl"].splitlines()
        row = json.loads(line)
        self.assertEqual((row["date"], row["recorded_at"]), ("2026-11-11", "2026-11-11T19:00:00+03:00"))
        self.assertEqual(row["items"]["SBER"], {"close": 300.1, "kind": "last"})
        # облигация — по ISIN, ключ — ticker снапшота; НКД, номинал и валюта номинала записаны
        self.assertEqual(row["items"]["SU26243RMFS4"], {"close": 67.6, "kind": "last", "accrued": 43.5,
                                                         "face": 1000.0, "face_unit": "SUR"})
        self.assertEqual(row["items"]["RU000A10XYZ1"]["face_unit"], "USD")
        self.assertEqual(row["fx"], {"USD": 80.5, "date": "2026-11-11"})
        self.assertEqual(row["missing"], ["NOPRICE"])

    def test_fx_param_only_for_bond_currencies(self):
        self.assertEqual(prices_job.fx_codes(self.HOLD), ["USD"])
        self.assertTrue(prices_job.quotes_url("http://x/q?boards=TQBR", self.HOLD).endswith("&fx=USD"))
        self.assertEqual(prices_job.quotes_url("http://x/q?boards=TQBR", self.HOLD[:1]), "http://x/q?boards=TQBR")

    def test_holiday_prev_close_writes_nothing(self):
        summ = self.go(self.quotes("prev_close"))
        self.assertEqual(summ["status"], "skip")
        self.assertEqual(self.files, {})

    def test_weekend_writes_nothing(self):
        sat = datetime(2026, 11, 14, 19, 0, tzinfo=MSK)
        self.assertEqual(self.go(self.quotes(ts="2026-11-14 18:49:59"), sat)["status"], "skip")
        self.assertEqual(self.files, {})

    def test_same_date_twice_keeps_one_line(self):
        self.go(self.quotes())
        again = self.go(self.quotes(), self.DAY.replace(hour=20))
        self.assertEqual(again["status"], "skip")
        self.assertEqual(len(self.files["Portfolio/prices/daily-2026.jsonl"].splitlines()), 1)

    def test_next_day_appends_old_rows_untouched(self):
        self.go(self.quotes())
        first = self.files["Portfolio/prices/daily-2026.jsonl"]
        d2 = self.DAY.replace(day=12)
        self.go(self.quotes(ts="2026-11-12 18:49:59"), d2)
        lines = self.files["Portfolio/prices/daily-2026.jsonl"].splitlines()
        self.assertEqual((len(lines), lines[0] + "\n"), (2, first))
        self.assertEqual(json.loads(lines[1])["date"], "2026-11-12")

    def test_save_goes_through_jobs_with_base_hash(self):
        calls = []
        old = jobs._call
        def fake(method, path, payload=None, timeout=30):
            calls.append((method, path, payload))
            if method == "GET":
                return 404, {}
            return 200, {"hash": "h1"}
        jobs._call = fake
        try:
            prices_job.run("/нет", "http://x/q?boards=TQBR", self.DAY, fetch=lambda url: self.quotes())
        finally:
            jobs._call = old
        post = [c for c in calls if c[0] == "POST"]
        self.assertEqual(len(post), 1)
        self.assertEqual((post[0][1], post[0][2]["path"], post[0][2]["base_hash"]),
                         ("/api/job/save", "Portfolio/prices/daily-2026.jsonl", None))

    def test_runner_and_schedule(self):
        self.assertIn("prices", notifier.RUNNERS)
        at = lambda h, m, day=11: datetime(2026, 11, day, h, m, tzinfo=MSK)   # noqa: E731
        self.assertFalse(notifier.job_due({}, at(18, 59), "prices"))
        self.assertTrue(notifier.job_due({}, at(19, 0), "prices"))
        js = {}
        notifier._mark(js, "prices", at(19, 0), ok=False)
        self.assertFalse(notifier.job_due(js, at(19, 30), "prices"))
        self.assertTrue(notifier.job_due(js, at(20, 0), "prices"))
        self.assertFalse(notifier.job_due({}, at(19, 30, day=14), "prices"))   # суббота
        # skip (выходной/праздник) — не ошибка: повтор в 20:00 не нужен
        notifier._mark(js2 := {}, "prices", at(19, 0), ok=True)
        self.assertFalse(notifier.job_due(js2, at(20, 0), "prices"))


PAGE = ('<html><script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"pageProps": {
    "initialApolloState": {
        'Product:{"sku":"1"}': {"nsuid": "70010000000999", "name": "Чужая игра", "urlKey": "other-switch"},
        'Product:{"sku":"7100009921"}': {"nsuid": "70010000009921", "name": "Undertale ", "urlKey": "undertale-switch",
                                         "platform": {"code": "NINTENDO_SWITCH"}}}}}}) + "</script></html>")


FIXTURE_COND = REPO / "tools/data-structures/tests/fixtures/conditions_v12.yaml"
DEC_NOW = datetime(2026, 12, 31, 17, 40, tzinfo=MSK)


class DecisionJob(unittest.TestCase):
    """POST /api/pf/decision (decision_job.post_decision): решение владельца → decision@1, author owner."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="decision-job-"))
        (self.root / "Portfolio").mkdir()
        defs, state, _, _ = mg.migrate(ds.load_yaml(str(FIXTURE_COND)))
        (self.root / "Portfolio/conditions.yaml").write_text(mg._dump_yaml(defs), encoding="utf-8")
        (self.root / "Portfolio/conditions-state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        self.saved = {}

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def save(self, rel, content):
        if rel in self.saved:
            raise dj.AlreadyExists(rel)
        self.saved[rel] = content

    def read(self, rel):
        return (self.saved.get(rel), None)

    def post(self, body, now=DEC_NOW):
        return dj.post_decision(self.root, body, self.save, now, read_fn=self.read)

    BODY = {"key": "AAAA", "verdict": "HOLD", "target_pct": 4.5, "review_by": "2027-02-15",
            "note": "Подтверждено владельцем без разбора", "confidence": 0.7}

    def test_valid_record(self):
        code, j = self.post(self.BODY)
        self.assertEqual(code, 200, j)
        rel = "Portfolio/decisions/2026-12-31T1740-AAAA.json"
        self.assertEqual(j["saved"], rel)
        d = json.loads(self.saved[rel])
        self.assertEqual(d, j["decision"])
        self.assertEqual(ds.validate_decision(d), [])
        self.assertEqual((d["author"], d["source"], d["recorded_at"], d["id"]),
                         ("owner", {"kind": "owner", "doc": None, "mode_codes": [], "stress_id": None},
                          "2026-12-31T17:40:00+03:00", "2026-12-31T1740-AAAA"))
        self.assertEqual((d["verdict"], d["target_pct"], d["review_by"], d["confidence"]), ("HOLD", 4.5, "2027-02-15", 0.7))

    def test_conditions_resolved_only_waits_owner(self):
        import conditions_merge as cm
        sp = self.root / "Portfolio/conditions-state.json"          # одно условие владелец отложил — оно не «ждёт владельца»
        st = json.loads(sp.read_text(encoding="utf-8"))
        st["events"].append({"condition_id": "aaaa-below-100", "version": 1, "event": "owner_mark", "at": "2026-12-30T10:00:00+03:00",
                             "by": "owner", "data": {"mark": "deferred", "until": "2027-01-15"}})
        sp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        rows, _, _ = dj._dw()._conditions(str(self.root), "2026-12-31")
        waits = [r["id"] for r in cm.select(rows, keys=["AAAA"]) if r["waits_owner"]]
        other = [r["id"] for r in cm.select(rows, keys=["AAAA"]) if not r["waits_owner"]]
        self.assertTrue(waits and other, (waits, other))                    # фикстура даёт и ждущее владельца, и нет
        d = self.post(self.BODY)[1]["decision"]
        self.assertEqual(d["conditions_resolved"], waits)
        self.assertFalse(set(d["conditions_resolved"]) & set(other))
        self.assertEqual(self.post({**self.BODY, "key": "ZZZZ"}, DEC_NOW + timedelta(minutes=1))[1]["decision"]["conditions_resolved"], [])

    def test_review_by_default_plus_60(self):
        b = {k: v for k, v in self.BODY.items() if k != "review_by"}
        d = self.post(b)[1]["decision"]
        self.assertEqual(d["review_by"], "2027-03-01")                      # 2026-12-31 + 60 дней
        b2 = dict(b, key="BBBB", review_by="")
        self.assertEqual(self.post(b2)[1]["decision"]["review_by"], "2027-03-01")

    def test_minimal_body_without_optional(self):
        code, j = self.post({"key": "AAAA", "verdict": "WATCH", "note": "ждём дивидендную политику компании"})
        self.assertEqual(code, 200, j)
        d = j["decision"]
        self.assertIsNone(d["target_pct"])
        self.assertNotIn("confidence", d)

    def test_same_minute_409_no_overwrite(self):
        self.assertEqual(self.post(self.BODY)[0], 200)
        first = dict(self.saved)
        code, j = self.post(dict(self.BODY, note="Другая заметка, но та же минута записи"), DEC_NOW + timedelta(seconds=20))
        self.assertEqual(code, 409)
        self.assertIn("уже есть", j["error"])
        self.assertEqual(self.saved, first)                                  # файл не тронут
        self.assertEqual(self.post(dict(self.BODY), DEC_NOW + timedelta(minutes=1))[0], 200)   # другая минута — новый файл
        self.assertEqual(len(self.saved), 2)

    def test_race_save_exists_is_409(self):
        """read_fn увидел «нет», но save_fn (hub-api) ответил 409 — гонка двух вкладок: тоже 409, не 500."""
        code, j = dj.post_decision(self.root, self.BODY, lambda *a: (_ for _ in ()).throw(dj.AlreadyExists("x")), DEC_NOW,
                                   read_fn=lambda rel: (None, None))
        self.assertEqual(code, 409)

    def test_bad_input_400_nothing_saved(self):
        bad = [dict(self.BODY, verdict="HOLD_ADD"), dict(self.BODY, verdict=None), dict(self.BODY, key=None),
               dict(self.BODY, key="aaaa"), dict(self.BODY, key="AA/AA"),
               dict(self.BODY, review_by="2027-01-03"),                       # 3 дня < 7
               dict(self.BODY, review_by="2027-07-01"),                       # 181 день > 180
               dict(self.BODY, review_by="2026-12-01"), dict(self.BODY, review_by="не дата"),
               dict(self.BODY, note=""), dict(self.BODY, note="коротко"), dict(self.BODY, note="я" * 201), dict(self.BODY, note=None),
               dict(self.BODY, target_pct=101), dict(self.BODY, target_pct="5"), dict(self.BODY, confidence=1.5), [1, 2]]
        for b in bad:
            code, j = self.post(b)
            self.assertEqual(code, 400, (b, j))
            self.assertTrue(j.get("error"), b)
        self.assertEqual(self.saved, {})

    def test_review_by_edges(self):
        self.assertEqual(self.post(dict(self.BODY, review_by="2027-01-07"))[0], 200)                  # ровно 7 дней
        self.assertEqual(self.post(dict(self.BODY, review_by="2027-06-29"), DEC_NOW + timedelta(minutes=1))[0], 200)   # ровно 180
        self.assertEqual(self.post(dict(self.BODY, review_by="2027-06-30"), DEC_NOW + timedelta(minutes=2))[0], 400)

    def test_save_new_maps_409_to_exists(self):
        """jobs.save_new: base_hash=null, 409 hub-api → ExistsError (повтор с чужим хэшем, как у jobs.save, исключён)."""
        calls = []
        old = jobs._call
        try:
            jobs._call = lambda m, path, payload=None, timeout=30: (calls.append(payload), (409, {"current_hash": "h"}))[1]
            with self.assertRaises(jobs.ExistsError):
                jobs.save_new("Portfolio/decisions/2026-11-11T1015-GMKN.json", "{}")
            self.assertEqual(len(calls), 1)
            self.assertIsNone(calls[0]["base_hash"])
            jobs._call = lambda m, path, payload=None, timeout=30: (502, {})
            with self.assertRaises(jobs.SaveError):
                jobs.save_new("Portfolio/decisions/2026-11-11T1015-GMKN.json", "{}")
            jobs._call = lambda m, path, payload=None, timeout=30: (200, {"hash": "abc"})
            self.assertEqual(jobs.save_new("Portfolio/decisions/2026-11-11T1015-GMKN.json", "{}"), "abc")
        finally:
            jobs._call = old

    def test_route_wired_in_notifier(self):
        src = (REPO / "tools/hosting/notify/notifier.py").read_text(encoding="utf-8")
        self.assertIn('u.path == "/api/pf/decision"', src)
        self.assertIn("decision_job.post_decision(", src)
        self.assertIn("jobs.save_new", src)                                   # запись — только новым файлом
        deploy = (REPO / "tools/deploy.zsh").read_text(encoding="utf-8")
        for f in ("decision_job.py", "decision_write.py", "decisions_read.py", "last_word.py", "ds_schemas.py",
                  "conditions_merge.py", "codelists.py", "codelists.json", "time_msk.py", "hub_settings.py"):
            self.assertIn(f, deploy, f)                                       # всё, что тянет сборка записи, выкладывается в pdl/


class ConditionJob(unittest.TestCase):
    """POST /api/pf/condition (condition_job.post_condition): условие-напоминание владельца, add / withdraw."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="condition-job-"))
        (self.root / "Portfolio").mkdir()
        defs, state, _, _ = mg.migrate(ds.load_yaml(str(FIXTURE_COND)))
        self.defs_path = self.root / "Portfolio/conditions.yaml"
        self.defs_path.write_text(mg._dump_yaml(defs), encoding="utf-8")
        (self.root / "Portfolio/conditions-state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        self.saves = []                                    # (rel, text, base_hash)
        self.hub = None                                    # хэш файла «в hub-api»; None — как на mount
        self.conflict = False
        self.quotes = {"SBER": 300.0, "OFZ26238": 62.5, "ZZZZ": 12.0}
        self.held = {"AAAA"}

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _hash(self):
        import hashlib
        return hashlib.sha256(self.defs_path.read_bytes()).hexdigest()

    def read(self, rel):
        return self.defs_path.read_text(encoding="utf-8"), (self.hub or self._hash())

    def save(self, rel, text, base_hash):
        if self.conflict:
            raise cj.Conflict(rel)
        self.saves.append((rel, text, base_hash))
        self.defs_path.write_text(text, encoding="utf-8")   # как hub-api: файл на mount обновляется
        return "h"

    def post(self, body, now=DEC_NOW):
        return cj.post_condition(self.root, body, self.save, now, self.read,
                                 quotes_fn=lambda: self.quotes, held_fn=lambda: self.held)

    ADD = {"action": "add", "key": "SBER", "trigger": "price_below", "value": 280,
           "text": "Сбер дошёл до 280 — посмотреть докупку"}

    def doc(self):
        return ds.load_yaml(str(self.defs_path))

    def test_add_price_not_held(self):
        """Бумага вне портфеля (SBER не в held): цена на доске есть — условие записывается."""
        code, j = self.post(self.ADD)
        self.assertEqual(code, 200, j)
        c = j["condition"]
        self.assertEqual(j["saved"], "Portfolio/conditions.yaml")
        self.assertEqual((c["key"], c["kind"], c["source"], c["created_by"], c["trigger"]),
                         ("SBER", "watch", {"kind": "owner", "doc": None}, "owner", {"type": "price_below", "value": 280}))
        self.assertEqual((c["on_trigger"]["action"], c["on_trigger"]["text"]), ("notify_only", self.ADD["text"]))
        self.assertIsNone(c["while_pending"]["verdict"])                     # наблюдение вердикт не закрепляет
        self.assertTrue(c["id"].startswith("c-2026-12-31-sber-"))
        self.assertEqual(len(self.saves), 1)
        rel, text, base = self.saves[0]
        self.assertEqual(rel, "Portfolio/conditions.yaml")
        self.assertEqual(ds.validate_conditions_file(self.doc()), [])
        self.assertTrue(base and base != self._hash())                       # запись — от прочитанного хэша

    def test_add_all_trigger_types(self):
        for i, (tt, val) in enumerate((("date", "2027-01-20"), ("price_above", "350,5"), ("event", "выйдет отчёт МСФО за 9М"))):
            code, j = self.post(dict(self.ADD, trigger=tt, value=val, key="OFZ26238" if tt == "price_above" else "SBER"),
                                DEC_NOW + timedelta(minutes=i))
            self.assertEqual(code, 200, (tt, j))
            self.assertEqual(j["condition"]["trigger"]["type"], tt)
        last = j["condition"]
        self.assertEqual(last["event_text"], "выйдет отчёт МСФО за 9М")
        self.assertEqual(ds.validate_conditions_file(self.doc()), [])

    def test_add_held_without_quote_ok_unknown_400(self):
        self.quotes = {"SBER": 300.0}
        self.assertEqual(self.post(dict(self.ADD, key="AAAA"))[0], 200)       # держимая бумага без цены на досках — можно
        code, j = self.post(dict(self.ADD, key="NOPE"))
        self.assertEqual(code, 400)
        self.assertIn("нет на досках", j["error"])
        self.assertEqual(len(self.saves), 1)

    def test_add_quotes_down_502(self):
        self.quotes = {}
        code, j = self.post(self.ADD)
        self.assertEqual(code, 502)
        self.assertIn("котировки", j["error"])
        self.assertEqual(self.saves, [])

    def test_add_valid_until(self):
        code, j = self.post(dict(self.ADD, valid_until="2027-03-01"))
        self.assertEqual((code, j["condition"]["valid_until"]), (200, "2027-03-01"))

    def test_bad_input_400_nothing_saved(self):
        bad = [dict(self.ADD, key="sber"), dict(self.ADD, key=None), dict(self.ADD, key="SB/ER"),
               dict(self.ADD, trigger="price_up"), dict(self.ADD, value=0), dict(self.ADD, value=-5), dict(self.ADD, value="много"),
               dict(self.ADD, value=True), dict(self.ADD, trigger="date", value="2026-12-30"),   # дата в прошлом
               dict(self.ADD, trigger="date", value="31.12.2027"), dict(self.ADD, trigger="event", value="  "),
               dict(self.ADD, trigger="event", value="я" * 201),
               dict(self.ADD, text=""), dict(self.ADD, text=None), dict(self.ADD, text="я" * 201),
               dict(self.ADD, valid_until="2026-12-01"), dict(self.ADD, valid_until="не дата"),
               dict(self.ADD, trigger="date", value="2027-02-01", valid_until="2027-01-15"),
               dict(self.ADD, action="edit"), {"action": None}, [1], "x"]
        for b in bad:
            code, j = self.post(b)
            self.assertEqual(code, 400, (b, j))
            self.assertTrue(j.get("error"), b)
        self.assertEqual(self.saves, [])

    def test_mode_does_not_gate(self):
        """Работает в обоих режимах сайта: в writer нет гейта по ai_mode (--by owner), job его тоже не читает."""
        src = (REPO / "tools/hosting/notify/condition_job.py").read_text(encoding="utf-8")
        self.assertNotIn("ai_mode", src)
        self.assertEqual(self.post(self.ADD)[0], 200)

    def _own_id(self):
        return self.post(self.ADD)[1]["id"]

    def test_withdraw_own(self):
        cid = self._own_id()
        code, j = self.post({"action": "withdraw", "id": cid}, DEC_NOW + timedelta(minutes=5))
        self.assertEqual(code, 200, j)
        self.assertEqual((j["id"], j["withdrawn"]["by"], j["withdrawn"]["reason"]), (cid, "owner", cj.REASON_DEFAULT))
        last = [c for c in self.doc()["conditions"] if c["id"] == cid][-1]
        self.assertEqual(last["withdrawn"]["by"], "owner")
        self.assertEqual(self.post({"action": "withdraw", "id": cid, "reason": "уже купил"})[0], 400)   # повторное снятие

    def test_withdraw_advisor_condition_400(self):
        before = self.defs_path.read_text(encoding="utf-8")
        code, j = self.post({"action": "withdraw", "id": "aaaa-below-100", "reason": "x"})
        self.assertEqual(code, 400)
        self.assertIn("снять можно только своё", j["error"])
        self.assertEqual((self.saves, self.defs_path.read_text(encoding="utf-8")), ([], before))

    def test_withdraw_unknown_and_bad_id_400(self):
        for b in ({"action": "withdraw", "id": "нет-такого"}, {"action": "withdraw", "id": ""}, {"action": "withdraw", "id": "a@2"},
                  {"action": "withdraw"}, {"action": "withdraw", "id": "x", "reason": "я" * 201}):
            self.assertEqual(self.post(b)[0], 400, b)

    def test_conflict_409_when_hub_hash_differs(self):
        """Зеркало отстаёт или файл правил скилл между чтением и записью: хэш hub-api ≠ хэшу прочитанных байтов."""
        self.hub = "0" * 64
        code, j = self.post(self.ADD)
        self.assertEqual(code, 409)
        self.assertIn("повтори", j["error"])
        self.assertEqual(self.saves, [])

    def test_conflict_409_when_save_raises(self):
        self.conflict = True
        code, j = self.post(self.ADD)
        self.assertEqual(code, 409)
        self.assertIn("повтори", j["error"])

    def test_no_defs_file_400(self):
        self.defs_path.unlink()
        self.assertEqual(self.post(self.ADD)[0], 400)

    def test_save_cas_maps_409(self):
        calls = []
        old = jobs._call
        try:
            jobs._call = lambda m, path, payload=None, timeout=30: (calls.append(payload), (409, {"current_hash": "h"}))[1]
            with self.assertRaises(jobs.ConflictError):
                jobs.save_if("Portfolio/conditions.yaml", "x", "abc")
            self.assertEqual((len(calls), calls[0]["base_hash"]), (1, "abc"))       # без повтора с чужим хэшем
            jobs._call = lambda m, path, payload=None, timeout=30: (502, {})
            with self.assertRaises(jobs.SaveError):
                jobs.save_if("Portfolio/conditions.yaml", "x", "abc")
            jobs._call = lambda m, path, payload=None, timeout=30: (200, {"hash": "new"})
            self.assertEqual(jobs.save_if("Portfolio/conditions.yaml", "x", "abc"), "new")
        finally:
            jobs._call = old

    def test_route_wired_in_notifier_and_deploy(self):
        src = (REPO / "tools/hosting/notify/notifier.py").read_text(encoding="utf-8")
        self.assertIn('u.path == "/api/pf/condition"', src)
        self.assertIn("condition_job.post_condition(", src)
        self.assertIn("jobs.save_if", src)                                    # запись — только от прочитанного хэша
        self.assertIn("quotes_fn=fetch_prices", src)                          # существование бумаги — по котировкам досок
        deploy = (REPO / "tools/deploy.zsh").read_text(encoding="utf-8")
        for f in ("condition_job.py", "apply_condition.py", "conditions_merge.py", "decisions_read.py", "ds_schemas.py",
                  "codelists.py", "time_msk.py", "hub_settings.py"):
            self.assertIn(f, deploy, f)                                       # всё, что тянет писатель условий, выкладывается в pdl/

    def test_job_runs_from_container_layout(self):
        """В контейнере модули лежат в pdl/…; _ac() находит writer и там, и в репозитории."""
        self.assertTrue(hasattr(cj._ac(), "run"))


class Lookup(unittest.TestCase):
    def test_extract_matches_url_key_only(self):
        hit = el.extract(PAGE, "undertale-switch")
        self.assertEqual((hit["nsuid"], hit["store_title"], hit["platform"]),
                         ("70010000009921", "Undertale", "NINTENDO_SWITCH"))       # хвостовой пробел срезан
        self.assertIsNone(el.extract(PAGE, "nope-switch"))
        self.assertEqual(el.slug_of("https://www.nintendo.com/us/store/products/undertale-switch/"),
                         "undertale-switch")

    def test_candidates(self):
        self.assertEqual(el.candidates("Fire Emblem: Fortune's Weave", "switch_2"),
                         ["fire-emblem-fortunes-weave-switch-2", "fire-emblem-fortunes-weave-switch"])
        self.assertEqual(el.candidates("Bō: Path of the Teal Lotus", None)[0], "bo-path-of-the-teal-lotus-switch")

    def test_fill_inserts_after_title(self):
        text = ('items:\n  # ── хочу\n  - title: "Undertale"\n    status: хочу\n    note: "x"\n\n'
                '  - title: "Уже есть"\n    status: хочу\n    nsuid_us: "1"\n'
                '  - title: "Отказ"\n    status: не-интересно\n')
        seen = []
        new, rep = el.fill(text, lambda it: seen.append(it["title"]) or el.extract(PAGE, "undertale-switch"),
                           pause=0, log=lambda *a: None)
        self.assertEqual(seen, ["Undertale"])
        self.assertIn('  - title: "Undertale"\n    store_title: "Undertale"\n    nsuid_us: "70010000009921"\n'
                      '    eshop_url: https://www.nintendo.com/us/store/products/undertale-switch/\n    status: хочу', new)
        self.assertEqual(new.replace('    store_title: "Undertale"\n    nsuid_us: "70010000009921"\n'
                                     '    eshop_url: https://www.nintendo.com/us/store/products/undertale-switch/\n', ""),
                         text)


if __name__ == "__main__":
    unittest.main(verbosity=1)
