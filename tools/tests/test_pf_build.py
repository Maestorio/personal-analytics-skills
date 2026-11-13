#!/usr/bin/env python3
"""Сборка снапшота с вьюера (hub-notify pf_build.py, API-1 PR-6, пробный режим с 2026-10-21).

Контракты:
  • файлы: сделки IntelInvest обязательны; «Общий баланс» (.numbers или .xlsx) и ИИС-3 (.xlsx) — нет
    (без баланса позиции из сделок — assemble --holdings-from-trades); лишний вид,
    чужое расширение или не-zip (пакет .numbers, переименованный файл) → 400, папка прогона не остаётся;
  • одна сборка за раз: вторая, пока идёт первая, → 409;
  • сквозной прогон НАСТОЯЩЕГО build_snapshot.py в раскладке контейнера (pdl/skills/…/scripts +
    pdl/_shared-references/moex_quotes.py — как кладёт deploy.zsh) на синтетической выгрузке, без сети
    (--no-moex --cbr-offline подмешиваются раннером теста): статус done, сводка с числами снапшота,
    сравнение с прошлым снапшотом из --memory, кэши ЦБ — в томе данных, не в /tmp;
  • cash_fact (свободные деньги основного портфеля из IntelInvest, решение 27.10) → --cash-fact, статус
    и журнал; не число / <0 / ≥1e9 / bool → 400 без папки прогона;
  • cash_fact_iis (свободные деньги ИИС-3, вьюер 3.80.0) → --cash-fact-iis, статус и журнал; те же границы,
    независим от cash_fact (можно передать один из двух); brief.auto несёт cash_main_rub / cash_iis_rub;
  • упавшая сборка → state error с хвостом stderr, не «done»;
  • «Сохранить» пишет снапшот в РАБОЧУЮ Portfolio/snapshots/portfolio-ДАТА.json (то же имя, что у скилла:
    SNAP_RE загрузчика видит его как обычный), а build-summary-ДАТА-ЧЧММ-тип.json — в Portfolio/snapshots/auto/;
    пробная сборка без «Сохранить» ничего не пишет; сбор только по сделкам не перезаписывает снапшот того же
    дня с балансом (409, случай 27.10); блок-проверка → 409 без записи, незавершённая сборка → 409; журнал _jobs
    получает pf_build и pf_save;
  • hub-api: whitelist /api/job/* пускает Portfolio/snapshots/auto/; рабочую Portfolio/snapshots/portfolio-ДАТА.json —
    только после правки server.py (JOB_WHITELIST), пока тест фиксирует нынешнее состояние (test_auto_only);
    индекс по бумаге упразднён (шаг 15): publish_securities, SEC_DIR и запись Portfolio/securities/ в whitelist
    удалены, у шага «Сохранить» один шаг POST_STEPS — журнал; после «Сохранить» в рабочую папку журнал
    пересобирается (при root);
  • журнал решений (Шаг 7б скилла на сайте): после «Сохранить» publish_journal запускает
    decision_journal_update.py с --memory = рабочий корень в папке прогона (обзоры/снапшоты/gate-reviews —
    ссылки на настоящие, refusals/theses копией) и --trades = выгрузка прогона; через save_fn уходят ТОЛЬКО
    inputs/baselines/journal.json и report-ДАТА.md (ручные incidents/refusals/theses.yaml не пишутся,
    чужие файлы в папке вывода игнорируются); whitelist hub-api пускает ровно их; сбой шага
    (нет скрипта, код ≠ 0, исключение) — st["decision_journal"] = {error}, сохранение снапшота 200;
    без root журнал не запускается; deploy.zsh копирует скрипты загрузчика списком *.py (decision_journal*,
    shadow_*, market_series — в составе).
Сеть не нужна. Запуск: python3 tools/tests/test_pf_build.py
"""
import base64
import importlib
import io
import json
import time
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "tools/hosting/notify"))
sys.path.insert(0, str(REPO / "tools/hosting/api"))
sys.path.insert(0, str(REPO / "skills/portfolio-data-loader/tests"))
import pf_build  # noqa: E402
import server  # noqa: E402

MSK = timezone(timedelta(hours=3))
NOW = datetime(2026, 10, 21, 22, 0, tzinfo=MSK)


def zip_bytes():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("x", "y")
    return b.getvalue()


def f(name, raw=None):
    return {"name": name, "b64": base64.b64encode(raw if raw is not None else zip_bytes()).decode()}


def fake_runner(summary_extra=None, rc=0, stderr=""):
    """Подмена subprocess.run: пишет снапшот и build-summary, как build_snapshot.py --json."""
    def run(cmd, **kw):
        work = Path(cmd[cmd.index("--out") + 1])
        work.mkdir(parents=True, exist_ok=True)
        snap = {"as_of_date": "2026-10-21", "holdings": [{}, {}], "cash": {"total_rub": 1000.0},
                "balance_summary": {"total_current_rub_incl_iis": 5e6},
                "returns": {"total": {"xirr": 0.04}, "restricted": {"xirr": 0.08}}}
        (work / "portfolio-2026-10-21.json").write_text(json.dumps(snap), encoding="utf-8")
        summ = {"as_of": "2026-10-21", "blocked": False, "checks": [], "decisions": [],
                "snapshot_path": str(work / "portfolio-2026-10-21.json"), "inputs": {}, "steps": []}
        summ.update(summary_extra or {})
        (work / "build-summary.json").write_text(json.dumps(summ), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, rc, json.dumps(summ) if rc in (0, 2) else "", stderr)
    return run


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data, self.root = self.tmp / "data", self.tmp / "cm"
        self.data.mkdir()
        self.root.mkdir()
        self.logs, self.saved = [], {}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def log(self, job, status, started, **extra):
        self.logs.append((job, status, extra))

    def start(self, files, runner, **kw):
        return pf_build.start(self.data, self.root, {"files": files, **kw}, NOW, log=self.log,
                              background=False, runner=runner)


class Stage(Base):
    def test_trades_required(self):
        code, j = self.start({"balance": f("b.numbers")}, fake_runner())
        self.assertEqual(code, 400)
        self.assertIn("сделок", j["error"])

    def test_balance_optional(self):
        code, j = self.start({"trades": f("t.xlsx")}, fake_runner())
        self.assertEqual(code, 202)
        cmd = pf_build.command("/srv", Path("/w"), {"trades": Path("t.xlsx")}, False)
        self.assertNotIn("--balance", cmd)

    def test_bad_ext_and_not_zip(self):
        self.assertEqual(self.start({"trades": f("t.csv")}, fake_runner())[0], 400)
        code, j = self.start({"trades": f("t.xlsx"), "balance": f("b.numbers", b"not a zip")}, fake_runner())
        self.assertEqual(code, 400)
        self.assertIn("один файл", j["error"])                   # подсказка про пакет Numbers
        self.assertEqual(self.start({"trades": f("t.xlsx"), "balance": f("b.xlsx"), "other": f("o.xlsx")}, fake_runner())[0], 400)
        runs = pf_build.runs_dir(self.data)
        self.assertEqual(list(runs.iterdir()) if runs.exists() else [], [])   # мусора не осталось

    def test_one_build_at_a_time(self):
        pf_build._lock.acquire()
        try:
            self.assertEqual(self.start({"trades": f("t.xlsx"), "balance": f("b.xlsx")}, fake_runner())[0], 409)
        finally:
            pf_build._lock.release()


class Flow(Base):
    def test_done_brief_and_save_to_working_folder(self):
        code, j = self.start({"trades": f("t.xlsx"), "balance": f("Общий баланс.numbers")}, fake_runner(),
                             rebaseline_cash=True)
        self.assertEqual(code, 202)
        st = pf_build.read_status(self.data, j["run"])
        self.assertEqual(st["state"], "done")
        self.assertEqual((st["brief"]["auto"]["holdings"], st["brief"]["auto"]["xirr_restricted"]), (2, 0.08))
        self.assertIn("cash_main_rub", st["brief"]["auto"])                # вьюер предзаполняет «Кэш по счетам»
        self.assertIn("cash_iis_rub", st["brief"]["auto"])
        self.assertEqual(st["files"], {"trades": "t.xlsx", "balance": "Общий баланс.numbers"})
        self.assertTrue(st["rebaseline_cash"])
        self.assertEqual(self.saved, {})                                  # пробная сборка без «Сохранить» ничего не пишет
        code, r = pf_build.save(self.data, j["run"], self.saved.__setitem__, NOW, log=self.log)
        self.assertEqual((code, r), (200, {"saved": "Portfolio/snapshots/portfolio-2026-10-21.json", "run": j["run"]}))
        # снапшот — в рабочую папку под именем скилла, служебная сводка — в auto/ с временем и вариантом
        self.assertEqual(sorted(self.saved), ["Portfolio/snapshots/auto/build-summary-2026-10-21-2200-bal.json",
                                              "Portfolio/snapshots/portfolio-2026-10-21.json"])
        self.assertEqual([x[0] for x in self.logs], ["pf_build", "pf_save"])
        # имя рабочего файла видит SNAP_RE загрузчика (прошлый/сравниваемый снапшот)
        sys.path.insert(0, str(REPO / "skills/portfolio-data-loader/scripts"))
        import build_snapshot
        self.assertTrue(build_snapshot.SNAP_RE.match("portfolio-2026-10-21.json"))
        # с root: после сохранения в рабочую папку пересобирается журнал решений
        called = []

        def runner(cmd, **kw):
            called.append(Path(cmd[1]).name)
            return subprocess.CompletedProcess(cmd, 1, "", "stop")
        code, _ = pf_build.save(self.data, j["run"], self.saved.__setitem__, NOW, root=self.root,
                                read_fn=lambda p: (None, None), runner=runner)
        self.assertEqual(code, 200)
        self.assertEqual(called, ["decision_journal_update.py"])
        st = pf_build.read_status(self.data, j["run"])
        self.assertNotIn("securities_index", st)
        self.assertIn("error", st["decision_journal"])

    def test_trades_only_does_not_overwrite_balance_snapshot(self):
        code, j = self.start({"trades": f("t.xlsx")}, fake_runner())
        snap = Path(pf_build.read_status(self.data, j["run"])["snapshot_path"])
        d = json.loads(snap.read_text(encoding="utf-8"))
        d["snapshot_type"] = "trades_holdings"
        snap.write_text(json.dumps(d), encoding="utf-8")
        with_balance = json.dumps({"snapshot_type": "full", "as_of_date": "2026-10-21"})
        code, r = pf_build.save(self.data, j["run"], self.saved.__setitem__, NOW, root=self.root,
                                read_fn=lambda p: (with_balance, "h"))
        self.assertEqual(code, 409)
        self.assertEqual(self.saved, {})
        self.assertEqual(r["reason"], "balance")
        self.assertIn("с «Общим балансом»", r["error"])
        # у прежнего баланса нет, но владелец внёс кэш: другая причина и другой текст (29.10)
        with_cash = json.dumps({"snapshot_type": "trades_holdings", "cash_reconciliation": {"current_drift_rub": 0.0}})
        code, r = pf_build.save(self.data, j["run"], self.saved.__setitem__, NOW, root=self.root,
                                read_fn=lambda p: (with_cash, "h"))
        self.assertEqual((code, self.saved, r["reason"]), (409, {}, "cash_fact"))
        self.assertIn("внесённым кэшем", r["error"])
        self.assertIn("Пересобрать с этим кешем", r["error"])
        self.assertNotIn("Общим балансом", r["error"])
        # прежний — тоже без баланса: перезапись разрешена
        code, _ = pf_build.save(self.data, j["run"], self.saved.__setitem__, NOW,
                                read_fn=lambda p: (json.dumps(d), "h"))
        self.assertEqual(code, 200)

    def test_compare_base_is_latest_skill_snapshot_not_cache_base(self):
        # 28.10: последний снапшот скилла — без баланса (28.10), опора кэша — 23.10; сравнивать надо с 28.10,
        # а подпись несёт дату опоры кэша
        skill = self.tmp / "portfolio-2026-10-28.json"
        cache = self.tmp / "portfolio-2026-10-23.json"
        skill.write_text(json.dumps({"as_of_date": "2026-10-28", "holdings": [{}] * 5}), encoding="utf-8")
        cache.write_text(json.dumps({"as_of_date": "2026-10-23", "holdings": [{}] * 9}), encoding="utf-8")
        run = fake_runner({"inputs": {"prev_snapshot": str(cache), "compare_snapshot": str(skill)}})
        code, j = self.start({"trades": f("t.xlsx")}, run)
        st = pf_build.read_status(self.data, j["run"])
        self.assertEqual((st["brief"]["skill"]["as_of"], st["brief"]["skill"]["holdings"]), ("2026-10-28", 5))
        self.assertEqual(st["brief"]["cache_base_as_of"], "2026-10-23")
        # старый загрузчик без compare_snapshot: сравнение с prev_snapshot, отдельной опоры кэша нет
        run = fake_runner({"inputs": {"prev_snapshot": str(cache)}})
        code, j = self.start({"trades": f("t.xlsx")}, run)
        st = pf_build.read_status(self.data, j["run"])
        self.assertEqual(st["brief"]["skill"]["as_of"], "2026-10-23")
        self.assertIsNone(st["brief"]["cache_base_as_of"])
        # база сравнения и опора кэша — один файл: подписи про кэш нет
        run = fake_runner({"inputs": {"prev_snapshot": str(cache), "compare_snapshot": str(cache)}})
        code, j = self.start({"trades": f("t.xlsx")}, run)
        self.assertIsNone(pf_build.read_status(self.data, j["run"])["brief"]["cache_base_as_of"])

    def test_command_flags(self):
        cmd = pf_build.command("/srv", Path("/w"), {"trades": Path("t.xlsx"), "iis_trades": Path("i.xlsx")}, True)
        self.assertIn("--rebaseline-cash", cmd)
        self.assertEqual(cmd[cmd.index("--memory") + 1], "/srv")
        self.assertNotIn("--commit", cmd)                         # пишет только «Сохранить», через hub-api
        self.assertIn("--iis-trades", cmd)
        if shutil.which("nice"):                                  # уступает DSM/SSH/сайту (NAS 2 ГБ)
            self.assertEqual(cmd[:3], ["nice", "-n", "10"])

    def test_cash_fact_to_argument_status_and_log(self):
        # решение владельца 27.10: кэш при устаревании оценки вносится из IntelInvest → --cash-fact
        seen = []
        inner = fake_runner()

        def run(cmd, **kw):
            seen.append(cmd)
            return inner(cmd, **kw)
        code, j = self.start({"trades": f("t.xlsx")}, run, cash_fact=330000)
        self.assertEqual(code, 202)
        cmd = seen[0]
        self.assertEqual(cmd[cmd.index("--cash-fact") + 1], "330000.0")
        self.assertEqual(pf_build.read_status(self.data, j["run"])["cash_fact"], 330000.0)
        self.assertEqual(self.logs[-1][2]["cash_fact"], 330000.0)
        code, j = self.start({"trades": f("t.xlsx")}, run)                      # без поля — без аргумента
        self.assertNotIn("--cash-fact", seen[-1])
        self.assertIsNone(pf_build.read_status(self.data, j["run"])["cash_fact"])
        self.assertEqual(self.start({"trades": f("t.xlsx")}, run, cash_fact=0)[0], 202)   # ноль — допустимое число
        code, _ = pf_build.save(self.data, j["run"], self.saved.__setitem__, NOW, log=self.log)
        self.assertIn("cash_fact", self.logs[-1][2])

    def test_cash_fact_invalid_is_400(self):
        for bad in (-1, "300000", float("nan"), float("inf"), 1e9, True, [1]):
            code, j = self.start({"trades": f("t.xlsx")}, fake_runner(), cash_fact=bad)
            self.assertEqual(code, 400, bad)
            self.assertIn("cash_fact", j["error"])
        runs = pf_build.runs_dir(self.data)
        self.assertEqual(list(runs.iterdir()) if runs.exists() else [], [])

    def test_cash_fact_iis_to_argument_status_and_log(self):
        seen = []
        inner = fake_runner()

        def run(cmd, **kw):
            seen.append(cmd)
            return inner(cmd, **kw)
        code, j = self.start({"trades": f("t.xlsx")}, run, cash_fact_iis=41000.5)
        self.assertEqual(code, 202)
        self.assertEqual(seen[0][seen[0].index("--cash-fact-iis") + 1], "41000.5")
        self.assertNotIn("--cash-fact", seen[0])                                  # независим от основного
        st = pf_build.read_status(self.data, j["run"])
        self.assertEqual((st["cash_fact_iis"], st["cash_fact"]), (41000.5, None))
        self.assertEqual(self.logs[-1][2]["cash_fact_iis"], 41000.5)
        code, j = self.start({"trades": f("t.xlsx")}, run, cash_fact=330000, cash_fact_iis=0)   # оба; ноль — число
        self.assertEqual(code, 202)
        self.assertEqual(seen[-1][seen[-1].index("--cash-fact") + 1], "330000.0")
        self.assertEqual(seen[-1][seen[-1].index("--cash-fact-iis") + 1], "0.0")
        code, j = self.start({"trades": f("t.xlsx")}, run)
        self.assertNotIn("--cash-fact-iis", seen[-1])
        self.assertIsNone(pf_build.read_status(self.data, j["run"])["cash_fact_iis"])
        pf_build.save(self.data, j["run"], self.saved.__setitem__, NOW, log=self.log)
        self.assertIn("cash_fact_iis", self.logs[-1][2])

    def test_cash_fact_iis_invalid_is_400(self):
        for bad in (-1, "300000", float("nan"), float("inf"), 1e9, True, [1]):
            code, j = self.start({"trades": f("t.xlsx")}, fake_runner(), cash_fact_iis=bad)
            self.assertEqual(code, 400, bad)
            self.assertIn("cash_fact_iis", j["error"])
        runs = pf_build.runs_dir(self.data)
        self.assertEqual(list(runs.iterdir()) if runs.exists() else [], [])

    def test_command_cash_flags(self):
        cmd = pf_build.command("/srv", Path("/w"), {"trades": Path("t.xlsx")}, False, 1.0, 2.0)
        self.assertEqual((cmd[cmd.index("--cash-fact") + 1], cmd[cmd.index("--cash-fact-iis") + 1]), ("1.0", "2.0"))
        self.assertNotIn("--types-cache", cmd)
        cmd = pf_build.command("/srv", Path("/w"), {"trades": Path("t.xlsx")}, False, types_cache=Path("/data/pf/x.json"))
        self.assertEqual(cmd[cmd.index("--types-cache") + 1], "/data/pf/x.json")

    def test_types_cache_in_data_volume_seeded_and_published(self):
        # 2026-10-28: том Claude-Memory (/srv) у hub-notify только на чтение — справочник типов живёт в /data/pf,
        # стартует из Portfolio/security-types.json (его пишет и скилл) и уезжает в Claude-Memory при «Сохранить»
        seed = self.root / "Portfolio" / "security-types.json"
        seed.parent.mkdir(parents=True, exist_ok=True)
        seed.write_text('{"by_ticker": {"SBER": {"type": "stock"}}}', encoding="utf-8")
        seen = []

        def runner(cmd, **kw):
            seen.append(cmd)
            return fake_runner()(cmd, **kw)
        code, j = self.start({"trades": f("t.xlsx")}, runner)
        self.assertEqual(code, 202)
        cache = pf_build.types_cache_path(self.data)
        self.assertEqual(seen[0][seen[0].index("--types-cache") + 1], str(cache))
        self.assertEqual(cache.read_text(encoding="utf-8"), seed.read_text(encoding="utf-8"))   # посев
        cache.write_text('{"by_ticker": {"SBER": {"type": "stock"}, "TMON": {"type": "fund"}}}', encoding="utf-8")
        code, r = pf_build.save(self.data, j["run"], self.saved.__setitem__, NOW, log=self.log)
        self.assertEqual(code, 200)
        self.assertIn("Portfolio/security-types.json", self.saved)
        self.assertIn('"TMON"', self.saved["Portfolio/security-types.json"])
        self.assertEqual(pf_build.read_status(self.data, j["run"])["types_saved"], "Portfolio/security-types.json")
        # второй прогон: кеш уже есть — посев не перезаписывает обновлённый справочник
        self.assertFalse(pf_build.seed_types_cache(self.data, self.root))
        self.assertIn('"TMON"', cache.read_text(encoding="utf-8"))

    def test_save_without_types_cache(self):
        code, j = self.start({"trades": f("t.xlsx")}, fake_runner())
        code, r = pf_build.save(self.data, j["run"], self.saved.__setitem__, NOW, log=self.log)
        self.assertEqual(code, 200)
        self.assertNotIn("Portfolio/security-types.json", self.saved)
        self.assertNotIn("types_saved", pf_build.read_status(self.data, j["run"]))

    def test_oom_message(self):
        # убит ядром по mem_limit контейнера → понятная причина, а не «код -9»
        code, j = self.start({"trades": f("t.xlsx")}, fake_runner(rc=-9))
        st = pf_build.read_status(self.data, j["run"])
        self.assertEqual(st["state"], "error")
        self.assertIn("не хватило памяти", st["error"])

    def test_blocked_not_saved(self):
        _, j = self.start({"trades": f("t.xlsx"), "balance": f("b.xlsx")}, fake_runner({"blocked": True}))
        code, _ = pf_build.save(self.data, j["run"], self.saved.__setitem__, NOW)
        self.assertEqual((code, self.saved), (409, {}))

    def test_failed_build_is_error(self):
        _, j = self.start({"trades": f("t.xlsx"), "balance": f("b.xlsx")}, fake_runner(rc=1, stderr="Traceback\nValueError: плохая выгрузка"))
        st = pf_build.read_status(self.data, j["run"])
        self.assertEqual(st["state"], "error")
        self.assertIn("плохая выгрузка", st["error"])
        self.assertEqual(pf_build.save(self.data, j["run"], self.saved.__setitem__, NOW)[0], 409)

    def test_not_json_summary_explained(self):
        """2026-10-21 на NAS окно показало голое «JSONDecodeError: Expecting value» — теперь видно,
        что напечатал скрипт и чем кончился stderr."""
        def run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, "", "предупреждение\nпоследняя строка stderr")
        _, j = self.start({"trades": f("t.xlsx")}, run)
        st = pf_build.read_status(self.data, j["run"])
        self.assertEqual(st["state"], "error")
        self.assertIn("не JSON", st["error"])
        self.assertIn("(пусто)", st["error"])
        self.assertIn("последняя строка stderr", st["error"])

    def test_missing_script_is_explained(self):
        """2026-10-21 на NAS: deploy.zsh не скопировал notify/pdl/, python вышел с кодом 2 (как
        «блок-проверка»), и окно показало «JSONDecodeError» вместо причины."""
        old = pf_build.SCRIPT
        pf_build.SCRIPT = self.tmp / "нет" / "build_snapshot.py"
        try:
            _, j = self.start({"trades": f("t.xlsx")}, fake_runner())
        finally:
            pf_build.SCRIPT = old
        st = pf_build.read_status(self.data, j["run"])
        self.assertEqual(st["state"], "error")
        self.assertIn("deploy.zsh", st["error"])

    def test_status_rejects_path_tricks(self):
        self.assertIsNone(pf_build.read_status(self.data, "../x"))


class RealScriptInContainerLayout(Base):
    """build_snapshot.py из раскладки deploy.zsh (pdl/…), синтетическая выгрузка, без сети."""

    def test_end_to_end(self):
        app = self.tmp / "app"
        scripts = app / "pdl/skills/portfolio-data-loader/scripts"
        scripts.mkdir(parents=True)
        for p in (REPO / "skills/portfolio-data-loader/scripts").glob("*.py"):
            shutil.copy2(p, scripts / p.name)
        (app / "pdl/_shared-references").mkdir()
        for shared in ("moex_quotes.py", "time_msk.py", "codelists.py", "codelists.json", "hub_settings.py"):
            shutil.copy2(REPO / "_shared-references" / shared, app / "pdl/_shared-references" / shared)
        tb = importlib.import_module("test_build_snapshot")
        trades = self.tmp / "trades_portfolio_707160-1.xlsx"
        tb.write_trades(trades)
        snaps = self.root / "Portfolio/snapshots"
        snaps.mkdir(parents=True)
        (snaps / "portfolio-2026-10-16.json").write_text(json.dumps(
            {"as_of_date": "2026-10-16", "holdings": [{}], "cash": {"total_rub": 1.0}}), encoding="utf-8")
        old = pf_build.SCRIPT
        pf_build.SCRIPT = scripts / "build_snapshot.py"

        def offline(cmd, **kw):
            return subprocess.run(cmd + ["--no-moex", "--cbr-offline", "--as-of", "2026-10-21"], **kw)
        try:
            code, j = self.start({"trades": f(trades.name, trades.read_bytes())}, offline)
        finally:
            pf_build.SCRIPT = old
        self.assertEqual(code, 202)
        st = pf_build.read_status(self.data, j["run"])
        self.assertEqual(st["state"], "done", st.get("error"))
        b = st["brief"]
        self.assertEqual(b["as_of"], "2026-10-21")
        self.assertEqual(b["auto"]["holdings"], 2)                # без баланса — позиции из сделок (SBER, GAZP)
        self.assertIn("balance_absent_holdings_from_trades", [x["code"] for x in b["attention_flags"]])
        self.assertEqual(b["skill"]["as_of"], "2026-10-16")       # сравнение с прошлым снапшотом
        self.assertTrue(b["fallbacks"].get("moex_down"))
        self.assertTrue((self.data / "pf").is_dir())
        self.assertIn("parity", b)                                # сверки нет (снапшота с балансом на дату нет) — null
        self.assertIsNone(b["parity"])
        MSK_RE = r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+03:00$"                  # время записи — МСК с поясом (schema.md §1 п.4)
        self.assertRegex(st["started"], MSK_RE)
        snaps_out = list((self.data / "pf" / "runs" / j["run"]).rglob("portfolio-2026-10-21*.json"))
        self.assertTrue(snaps_out, "снапшот прогона не найден")
        self.assertRegex(json.loads(snaps_out[0].read_text(encoding="utf-8"))["generated_at"], MSK_RE)

    def test_brief_carries_parity_without_server_path(self):
        par = {"against": "/x.json", "against_date": "2026-10-28", "same_day": True, "auto": True, "matched": 10,
               "within_tol": 1, "known": 2, "diverged": 1, "diverged_paths": ["$.cash.total_rub"],
               "report_path": "/data/pf/runs/r/work/parity-report.md"}
        base = {"as_of": "2026-10-28", "checks": [], "steps": [], "parity": par}
        b = pf_build.brief(base, None, None)
        self.assertEqual((b["parity"]["diverged"], b["parity"]["diverged_paths"]), (1, ["$.cash.total_rub"]))
        self.assertNotIn("report_path", b["parity"])              # путь внутри контейнера окну не нужен
        self.assertIsNone(pf_build.brief({**base, "parity": None}, None, None)["parity"])
        self.assertIsNone(pf_build.brief({k: v for k, v in base.items() if k != "parity"}, None, None)["parity"])

    def test_brief_shows_backdated_info_checks_rest_counted(self):
        shown = {"id": "trades_changed_before_prev", "level": "info", "message_ru": "Удалено/изменено задним числом: …"}
        other = {"id": "xirr_vs_prev", "level": "info", "message_ru": "XIRR"}
        warn = {"id": "payout_exceeds_holding", "level": "warning", "message_ru": "x", "details": {"items": []}}
        b = pf_build.brief({"as_of": "2026-11-11", "checks": [shown, other, warn], "steps": []}, None, None)
        self.assertEqual([c["id"] for c in b["checks"]], ["payout_exceeds_holding"])
        self.assertEqual([c["id"] for c in b["info_checks"]], ["trades_changed_before_prev"])
        self.assertEqual(b["n_info"], 1)                                      # остальные инфо — счётчиком

    def test_brief_carries_bond_bucket_check(self):
        chk = {"changes": [{"isin": "RU000A1", "name": "Б", "was": "КОРП/A", "now": "КОРП/AA+", "reason": "x"}],
               "missing": [], "derived": 3, "attrs_missing": False}
        base = {"as_of": "2026-10-28", "checks": [], "steps": [], "bond_bucket_check": chk}
        self.assertEqual(pf_build.brief(base, None, None)["bond_bucket_check"], chk)   # иначе карточка на «Загрузках» не появится
        self.assertIsNone(pf_build.brief({k: v for k, v in base.items() if k != "bond_bucket_check"},
                                         None, None)["bond_bucket_check"])


class SecuritiesRemoved(Base):
    """Индекс по бумаге упразднён: ни публикации, ни шага, ни записи в whitelist hub-api."""

    def test_removed(self):
        self.assertFalse(hasattr(pf_build, "publish_securities"))
        self.assertFalse(hasattr(pf_build, "SEC_DIR"))
        self.assertEqual(pf_build.POST_STEPS, ("decision_journal", "stress_recalc"))
        ok = lambda p: server.is_allowed(p, server.JOB_WHITELIST)   # noqa: E731
        self.assertFalse(ok("Portfolio/securities/YDEX.json"))
        self.assertFalse(ok("Portfolio/securities/index.json"))


class Journal(Base):
    """Журнал решений на сайте: скрипт пишет в рабочий корень, наружу — только производные файлы через save_fn."""

    def prepare(self):
        port = self.root / "Portfolio"
        (port / "weekly-reviews").mkdir(parents=True)
        (port / "snapshots").mkdir()
        (port / "decision-journal").mkdir()
        (port / "decisions").mkdir()                                       # шаг 13: решения, условия, журнал плана
        (port / "conditions.yaml").write_text("schema_version: conditions@2\nconditions: []\n", encoding="utf-8")
        (port / "conditions-state.json").write_text('{"events": []}', encoding="utf-8")
        (port / "plan-journal.jsonl").write_text("", encoding="utf-8")
        (port / "security-types.json").write_text("{}", encoding="utf-8")
        for n in ("conditions-archive-2025.yaml", "conditions-archive-2024.yaml", "conditions-archive-old.yaml"):
            (port / n).write_text("schema_version: conditions@2\nconditions: []\n", encoding="utf-8")
        (port / "gate-reviews.yaml").write_text("gates: []\n", encoding="utf-8")   # упразднён: скрипту не отдаётся
        for n in ("refusals.yaml", "theses.yaml", "incidents.yaml"):
            (port / "decision-journal" / n).write_text(f"# {n}\n", encoding="utf-8")
        code, j = self.start({"trades": f("t.xlsx")}, fake_runner())
        self.assertEqual(code, 202)
        return j["run"]

    def jrunner(self, rc=0, extra=None):
        seen = {}

        def run(cmd, **kw):
            mem = Path(cmd[cmd.index("--memory") + 1])
            seen.update(cmd=cmd, mem=mem, env=kw.get("env") or {})
            d = mem / "Portfolio" / "decision-journal"
            seen["manual"] = sorted(p.name for p in d.iterdir())
            seen["reviews_link"] = (mem / "Portfolio/weekly-reviews").is_symlink()
            seen["gate_seen"] = (mem / "Portfolio/gate-reviews.yaml").exists()
            seen["links"] = {n: (mem / "Portfolio" / n).is_symlink() for n in pf_build.JRN_READS}
            seen["archives"] = sorted(p.name for p in (mem / "Portfolio").glob("conditions-archive-*") if p.is_symlink())
            for n in ("inputs.json", "baselines.json", "journal.json", "report-2026-10-21.md", *(extra or [])):
                (d / n).write_text("{}" if n.endswith(".json") else "# r\n", encoding="utf-8")
            (d / "refusals.yaml").write_text("# изменён скриптом\n", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, rc, "Журнал: ок", "" if rc == 0 else "boom\nстрока ошибки")
        return run, seen

    def test_publish_only_derived_files(self):
        run = self.prepare()
        r, seen = self.jrunner(extra=["stray.txt", "incidents.yaml"])
        out = pf_build.publish_journal(self.data, self.root, run, "2026-10-21", self.saved.__setitem__, r)
        self.assertEqual(sorted(self.saved), [f"Portfolio/decision-journal/{n}" for n in
                                              ("baselines.json", "inputs.json", "journal.json", "report-2026-10-21.md")])
        self.assertEqual(out["written"], ["baselines.json", "inputs.json", "journal.json", "report-2026-10-21.md"])
        # ручные входы скопированы все три (incidents.yaml с шага 13 читается: инциденты владельца по месяцам)
        self.assertEqual(seen["manual"], ["incidents.yaml", "refusals.yaml", "theses.yaml"])
        self.assertTrue(seen["reviews_link"])
        # шаг 13: решения, условия формата 2 с состоянием, журнал плана, реестр типов — ссылками; файла гейтов нет
        self.assertEqual(seen["links"], {n: True for n in ("weekly-reviews", "snapshots", "decisions", "conditions.yaml",
                                                          "conditions-state.json", "plan-journal.jsonl",
                                                          "security-types.json")})
        self.assertFalse(seen["gate_seen"])
        # годовые архивы определений условий — ссылками по маске conditions-archive-ГГГГ.yaml; чужое имя — нет
        self.assertEqual(seen["archives"], ["conditions-archive-2024.yaml", "conditions-archive-2025.yaml"])
        cmd = seen["cmd"]
        self.assertEqual(cmd[cmd.index("--as-of") + 1], "2026-10-21")
        self.assertTrue(cmd[cmd.index("--trades") + 1].endswith("inputs/trades.xlsx"))
        self.assertNotEqual(seen["mem"], self.root)                            # том Claude-Memory скрипту не отдаётся
        self.assertIn(str(self.data), seen["env"]["PDL_MARKET_SERIES_CACHE"])
        # настоящие ручные файлы не тронуты
        self.assertEqual((self.root / "Portfolio/decision-journal/refusals.yaml").read_text(encoding="utf-8"), "# refusals.yaml\n")

    def test_save_runs_journal_and_failure_does_not_break_save(self):
        run = self.prepare()
        r, _ = self.jrunner()
        code, _ = pf_build.save(self.data, run, self.saved.__setitem__, NOW, root=self.root, runner=r)
        self.assertEqual(code, 200)
        dj = pf_build.read_status(self.data, run)["decision_journal"]
        self.assertEqual(len(dj["written"]), 4)
        self.assertIn("Portfolio/snapshots/portfolio-2026-10-21.json", self.saved)   # снапшот сохранён
        self.saved.clear()
        r, _ = self.jrunner(rc=1)
        code, _ = pf_build.save(self.data, run, self.saved.__setitem__, NOW, root=self.root, runner=r)
        self.assertEqual(code, 200)
        self.assertIn("строка ошибки", pf_build.read_status(self.data, run)["decision_journal"]["error"])
        self.assertTrue(all(not k.startswith("Portfolio/decision-journal/") for k in self.saved))

        def boom(cmd, **kw):
            raise OSError("диск")
        code, _ = pf_build.save(self.data, run, self.saved.__setitem__, NOW, root=self.root, runner=boom)
        self.assertEqual(code, 200)
        self.assertIn("OSError", pf_build.read_status(self.data, run)["decision_journal"]["error"])

    def test_save_returns_before_steps_and_status_goes_running_to_done(self):
        # 29.10: «Сохранить» висело минутами — шаги шли внутри HTTP-запроса; теперь ответ сразу, шаги в потоке
        import threading
        run = self.prepare()
        gate, entered = threading.Event(), threading.Event()
        calls = []

        def slow(cmd, **kw):
            calls.append(Path(cmd[1]).name)
            entered.set()
            gate.wait(10)
            return subprocess.CompletedProcess(cmd, 1, "", "stop")
        code, r = pf_build.save(self.data, run, self.saved.__setitem__, NOW, root=self.root, runner=slow,
                                read_fn=lambda p: (None, None), background=True)
        self.assertEqual((code, r["run"]), (200, run))                       # вернулось, пока runner ждёт
        self.assertTrue(entered.wait(5))
        st = pf_build.read_status(self.data, run)
        self.assertEqual(st["decision_journal"]["state"], "running")
        self.assertIn("Portfolio/snapshots/portfolio-2026-10-21.json", self.saved)   # снапшот записан синхронно
        # повторный save, пока идут шаги, второй поток не запускает
        code, r2 = pf_build.save(self.data, run, self.saved.__setitem__, NOW, root=self.root, runner=slow,
                                 read_fn=lambda p: (None, None), background=True)
        self.assertEqual((code, r2["run"]), (200, run))
        gate.set()
        for _ in range(100):
            st = pf_build.read_status(self.data, run)
            if all(st[k]["state"] != "running" for k in pf_build.POST_STEPS):
                break
            time.sleep(0.05)
        self.assertEqual(st["decision_journal"]["state"], "error")
        self.assertIn("stop", st["decision_journal"]["error"])
        self.assertEqual(calls, ["decision_journal_update.py"])   # по одному разу

    def test_stale_running_shown_as_error(self):
        run = self.prepare()
        st = pf_build.read_status(self.data, run)
        old = time.time() - pf_build.TIMEOUT - 120
        st["decision_journal"] = {"state": "running", "started_ts": old}
        pf_build._write_status(self.data, run, st)
        st = pf_build.read_status(self.data, run)
        self.assertEqual(st["decision_journal"]["state"], "error")
        self.assertIn("прервано", st["decision_journal"]["error"])
        st["decision_journal"] = {"state": "running", "started_ts": time.time()}
        pf_build._write_status(self.data, run, st)
        self.assertEqual(pf_build.read_status(self.data, run)["decision_journal"]["state"], "running")   # свежий — не трогаем

    def test_no_root_no_journal(self):
        run = self.prepare()
        code, _ = pf_build.save(self.data, run, self.saved.__setitem__, NOW)
        self.assertEqual(code, 200)
        self.assertNotIn("decision_journal", pf_build.read_status(self.data, run))

    def test_whitelist_and_deploy(self):
        ok = lambda p: server.is_allowed(p, server.JOB_WHITELIST)   # noqa: E731
        for n in ("inputs.json", "baselines.json", "journal.json", "report-2026-10-28.md"):
            self.assertTrue(ok(f"Portfolio/decision-journal/{n}"), n)
        for n in ("incidents.yaml", "refusals.yaml", "theses.yaml", "stray.json", "report-x.md", "sub/journal.json"):
            self.assertFalse(ok(f"Portfolio/decision-journal/{n}"), n)
        # deploy.zsh кладёт на NAS все *.py загрузчика — скрипты журнала в репозитории есть и попадут
        scripts = Path(pf_build.__file__).resolve().parents[3] / "skills/portfolio-data-loader/scripts"
        for n in ("decision_journal_update.py", "decision_journal.py", "shadow_inputs.py", "shadow_baselines.py",
                  "market_series.py"):
            self.assertTrue((scripts / n).is_file(), n)
        deploy = (Path(pf_build.__file__).resolve().parents[2] / "deploy.zsh").read_text(encoding="utf-8")
        self.assertIn("portfolio-data-loader/scripts/*.py", deploy)
        # шаг 13: журнал импортирует decisions_read (→ last_word, conditions_merge, ds_schemas, codelists, time_msk) —
        # все общие модули должны ехать в pdl/_shared-references
        import re as _re
        shipped = set(_re.findall(r"([a-z_]+\.py)", deploy.split("PDL_STAGE=", 1)[1]))
        for n in ("decisions_read.py", "last_word.py", "conditions_merge.py", "ds_schemas.py", "codelists.py",
                  "time_msk.py", "hub_settings.py"):
            self.assertIn(n, shipped, n)


class SecurityAttrsStep(Journal):
    """«Сохранить» добавляет в Portfolio/security-attrs.json только новые ключи держаний (задача 2.5)."""
    ATTRS = {"schema_version": "security-attrs@1", "by_key": {
        "SBER": {"ticker_class": "bluechip", "listed_at": None, "note": "ручная", "updated_at": "2026-10-31T12:00:00+03:00",
                 "updated_by": "owner"}}}

    def run_save(self, holdings, attrs, save_fn=None):
        run = self.prepare()
        snap = Path(pf_build.read_status(self.data, run)["snapshot_path"])
        d = json.loads(snap.read_text(encoding="utf-8"))
        d["holdings"] = holdings
        snap.write_text(json.dumps(d), encoding="utf-8")
        text = None if attrs is None else json.dumps(attrs)
        reads = []

        def read_fn(p):
            reads.append(p)
            return (text, "h") if p == pf_build.ATTRS_DEST else (None, None)
        code, _ = pf_build.save(self.data, run, save_fn or self.saved.__setitem__, NOW, read_fn=read_fn)
        self.assertEqual(code, 200)
        return pf_build.read_status(self.data, run)

    def test_new_key_added_existing_untouched(self):
        st = self.run_save([{"ticker": "SBER", "qty": 1, "listing_date": "2000-01-01"},
                            {"ticker": "NEWS", "qty": 2, "listing_date": "2025-03-04"}], self.ATTRS)
        self.assertEqual(st["attrs_saved"], {"added": ["NEWS"]})
        doc = json.loads(self.saved[pf_build.ATTRS_DEST])
        self.assertEqual(doc["by_key"]["SBER"], self.ATTRS["by_key"]["SBER"])
        self.assertEqual(doc["by_key"]["NEWS"], {"ticker_class": None, "listed_at": "2025-03-04", "note": None,
                                                 "updated_at": "2026-10-21T22:00:00+03:00", "updated_by": "script"})

    def test_no_new_keys_no_write(self):
        st = self.run_save([{"ticker": "SBER", "qty": 1}], self.ATTRS)
        self.assertEqual(st["attrs_saved"], {"added": []})
        self.assertNotIn(pf_build.ATTRS_DEST, self.saved)

    def test_no_file_is_not_created(self):
        st = self.run_save([{"ticker": "NEWS", "qty": 1}], None)
        self.assertIn("skipped", st["attrs_saved"])
        self.assertNotIn(pf_build.ATTRS_DEST, self.saved)

    def test_write_failure_does_not_break_save(self):
        def fail(path, text):
            if path == pf_build.ATTRS_DEST:
                raise OSError("409 конфликт")
            self.saved[path] = text
        st = self.run_save([{"ticker": "NEWS", "qty": 1}], self.ATTRS, save_fn=fail)
        self.assertIn("OSError", st["attrs_saved"]["error"])
        self.assertIn("Portfolio/snapshots/portfolio-2026-10-21.json", self.saved)


class Cancel(Base):
    """3.121.0: «Остановить сборку» — настоящий долгий подпроцесс (sleep) в своей группе процессов."""
    def setUp(self):
        super().setUp()
        self._cmd, self._script = pf_build.command, pf_build.SCRIPT
        pf_build.command = lambda *a, **k: ["sh", "-c", "sleep 60 & wait"]      # внук тоже должен умереть
        pf_build.SCRIPT = Path(__file__)
        pf_build.KILL_GRACE, self._grace = 1, pf_build.KILL_GRACE

    def tearDown(self):
        pf_build.command, pf_build.SCRIPT, pf_build.KILL_GRACE = self._cmd, self._script, self._grace
        super().tearDown()

    def begin(self):
        code, j = pf_build.start(self.data, self.root, {"files": {"trades": f("t.xlsx")}}, NOW, log=self.log)
        self.assertEqual(code, 202)
        for _ in range(100):
            if pf_build._running["proc"] is not None:
                break
            time.sleep(0.05)
        self.assertIsNotNone(pf_build._running["proc"])
        return j["run"]

    def test_cancel_kills_process_group_and_frees_lock(self):
        run = self.begin()
        p = pf_build._running["proc"]
        code, r = pf_build.cancel(self.data, run)
        self.assertEqual((code, r["state"]), (200, "cancelled"))
        self.assertIsNotNone(p.poll())                                  # процесс завершён
        st = pf_build.read_status(self.data, run)
        self.assertEqual(st["state"], "cancelled")
        self.assertRegex(st["cancelled_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+03:00$")
        self.assertFalse((pf_build.runs_dir(self.data) / run / "inputs").exists())   # рабочие файлы убраны
        self.assertTrue(pf_build._lock.acquire(blocking=False))          # лок свободен
        pf_build._lock.release()
        self.assertEqual(self.logs[-1][1], "cancelled")
        # save отменённой → 409; повторная отмена → 409
        code, r = pf_build.save(self.data, run, self.saved.__setitem__, NOW)
        self.assertEqual(code, 409)
        self.assertIn("отменена", r["error"])
        self.assertEqual(self.saved, {})
        code, r = pf_build.cancel(self.data, run)
        self.assertEqual(code, 409)
        self.assertIn("остановлена", r["error"])
        # новая сборка стартует
        pf_build.command = lambda *a, **k: ["true"]
        code, _ = pf_build.start(self.data, self.root, {"files": {"trades": f("t.xlsx")}}, NOW, background=False)
        self.assertEqual(code, 202)

    def test_cancel_unknown_or_finished_is_409(self):
        code, r = pf_build.cancel(self.data, "20990101-000000-abcdef")
        self.assertEqual(code, 409)
        self.assertIn("нет", r["error"])
        self.assertEqual(pf_build.cancel(self.data, "../x")[0], 409)
        _, j = self.start({"trades": f("t.xlsx")}, fake_runner())
        code, r = pf_build.cancel(self.data, j["run"])
        self.assertEqual(code, 409)
        self.assertIn("закончилась", r["error"])


class StressRecalcStep(Base):
    """Шаг stress_recalc после «Сохранить» рабочего снапшота: статус в status.json, сбой не роняет сохранение."""

    def prep(self, with_stress=True):
        port = self.root / "Portfolio"
        (port / "snapshots").mkdir(parents=True)
        (port / "decision-journal").mkdir()
        (port / "stress").mkdir()
        if with_stress:
            (port / "stress/stress-2026-11-04-x.yaml").write_text("horizon_ends: {h6: '2027-03-31'}\n", encoding="utf-8")
        code, j = self.start({"trades": f("t.xlsx")}, fake_runner())
        self.assertEqual(code, 202)
        return j["run"]

    def runner(self, stress_rc=0):
        calls = []

        def run(cmd, **kw):
            name = Path(cmd[1]).name
            calls.append(name)
            if name == "stress_recalc.py":
                if stress_rc == 0:
                    Path(cmd[cmd.index("--output") + 1]).write_text(
                        "recalc: {snapshot_id: portfolio-2026-10-21.json, reason: snapshot, weights_source: stress, "
                        "needs_judgment: [], dropped: []}\n", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, stress_rc, "", "" if stress_rc == 0 else "ОТКАЗ: плохо")
            return subprocess.CompletedProcess(cmd, 1, "", "stop")      # журнал падает — шаг пересчёта идёт всё равно
        return run, calls

    def test_step_appears_and_finishes_after_journal(self):
        run = self.prep()
        r, calls = self.runner()
        code, _ = pf_build.save(self.data, run, self.saved.__setitem__, NOW, root=self.root, runner=r)
        self.assertEqual(code, 200)
        self.assertEqual(calls, ["decision_journal_update.py", "stress_recalc.py"])
        sr = pf_build.read_status(self.data, run)["stress_recalc"]
        self.assertEqual((sr["state"], sr["source_stress"]), ("done", "stress-2026-11-04-x.yaml"))
        self.assertEqual(sr["path"], "Portfolio/stress/auto/recalc-stress-2026-11-04-x.yaml")
        self.assertIn(sr["path"], self.saved)
        self.assertIn("Portfolio/snapshots/portfolio-2026-10-21.json", self.saved)

    def test_failure_does_not_break_save(self):
        run = self.prep()
        r, _ = self.runner(stress_rc=1)
        code, j = pf_build.save(self.data, run, self.saved.__setitem__, NOW, root=self.root, runner=r)
        self.assertEqual(code, 200)
        self.assertIn("Portfolio/snapshots/portfolio-2026-10-21.json", self.saved)
        sr = pf_build.read_status(self.data, run)["stress_recalc"]
        self.assertEqual(sr["state"], "error")
        self.assertIn("плохо", sr["error"])

    def test_no_stress_file_is_skipped(self):
        run = self.prep(with_stress=False)
        r, calls = self.runner()
        pf_build.save(self.data, run, self.saved.__setitem__, NOW, root=self.root, runner=r)
        self.assertEqual(pf_build.read_status(self.data, run)["stress_recalc"]["state"], "skipped")
        self.assertEqual(calls, ["decision_journal_update.py"])

    def test_not_started_without_root(self):
        run = self.prep()
        r, calls = self.runner()
        pf_build.save(self.data, run, self.saved.__setitem__, NOW, runner=r)       # без root шаги не идут (пробная папка auto/ — то же условие)
        self.assertEqual(calls, [])
        self.assertNotIn("stress_recalc", pf_build.read_status(self.data, run))


class HubApiWhitelist(unittest.TestCase):
    def test_auto_only(self):
        ok = lambda p: server.is_allowed(p, server.JOB_WHITELIST)   # noqa: E731
        self.assertTrue(ok("Portfolio/snapshots/auto/portfolio-2026-10-21.json"))
        self.assertTrue(ok("Portfolio/snapshots/auto/build-summary-2026-10-21.json"))
        self.assertTrue(ok("Portfolio/snapshots/portfolio-2026-10-21.json"))
        self.assertFalse(ok("Portfolio/snapshots/auto/other.json"))
        # несколько сборок на дату: суффикс время-вариант
        self.assertTrue(ok("Portfolio/snapshots/auto/portfolio-2026-10-21-1902-trades.json"))
        self.assertTrue(ok("Portfolio/snapshots/auto/build-summary-2026-10-21-1858-bal.json"))
        self.assertFalse(ok("Portfolio/snapshots/auto/portfolio-2026-10-21-1902-x.json"))
        # справочник типов бумаг — единственный файл Portfolio/ верхнего уровня, который кладёт hub-notify
        self.assertTrue(ok("Portfolio/security-types.json"))
        self.assertFalse(ok("Portfolio/security-types.json.tmp"))
        self.assertFalse(ok("Portfolio/plan.json"))


class BriefPanel(unittest.TestCase):
    """3.122.0: brief несёт кэш по счетам с источником и список изменений позиций против сохранённого снапшота."""

    @staticmethod
    def snap(holdings, **cash):
        return {"as_of_date": "2026-10-30", "generated_at": "2026-10-30T12:28:21", "holdings": holdings,
                "cash": {"total_rub": 223133, "by_account": {"main": 200644, "iis_3": 22489}, **cash},
                "returns": {"total": {"xirr": 0.04}, "restricted": {"xirr": 0.08}}}

    def test_cash_by_account_and_sources(self):
        b = pf_build.brief({}, self.snap([], source="owner_intelinvest", iis_source="carried_from_prev", fact_date="2026-10-30"), None)
        a = b["auto"]
        self.assertEqual(a["cash_by_account"], {"main": 200644, "iis_3": 22489})
        self.assertEqual((a["cash_source"], a["cash_iis_source"]), ("owner_intelinvest", "carried_from_prev"))
        self.assertEqual(a["generated_at"], "2026-10-30T12:28:21")
        self.assertIsNone(b["skill"])
        self.assertIsNone(b["positions_diff"])                    # сохранённого нет — сравнивать не с чем

    def test_positions_diff_sold_bought_qty_same_and_cap(self):
        h = lambda t, q, acc="main": {"ticker": t, "name": t, "qty": q, "account": acc}      # noqa: E731
        prev = self.snap([h("SBER", 1800), h("OLDX", 10), h("SAME", 3), h("TMON", 5, "iis_3")])
        now = self.snap([h("SBER", 1851), h("NEWB", 5, "iis_3"), h("SAME", 3), h("TMON", 5, "main")])
        d = pf_build.brief({}, now, prev)["positions_diff"]
        got = {(r["kind"], r["ticker"], r["account"]): (r["was"], r["now"]) for r in d["rows"]}
        self.assertEqual(got, {("sold", "OLDX", "main"): (10, None), ("sold", "TMON", "iis_3"): (5, None),
                               ("bought", "NEWB", "iis_3"): (None, 5), ("bought", "TMON", "main"): (None, 5),
                               ("qty", "SBER", "main"): (1800, 1851)})
        self.assertEqual([r["kind"] for r in d["rows"]], ["sold", "sold", "bought", "bought", "qty"])      # SAME не попадает
        same = pf_build.brief({}, now, now)["positions_diff"]
        self.assertEqual((same["rows"], same["more"]), ([], 0))                                         # «позиции те же»
        many_now = self.snap([h(f"T{i:02d}", 1) for i in range(25)])
        cap = pf_build.brief({}, many_now, self.snap([h("ZZ", 1)]))["positions_diff"]
        self.assertEqual((len(cap["rows"]), cap["more"], cap["total"]), (20, 6, 26))

    def test_no_holdings_no_diff(self):
        self.assertIsNone(pf_build.brief({}, self.snap(None), self.snap([]))["positions_diff"])


    def test_save_block_known_in_advance(self):
        """3.122.1: brief несёт заранее то, на что save() ответит 409 — сборка только сделок против сохранённого того же дня."""
        only = {"as_of_date": "2026-10-30", "snapshot_type": "trades_holdings", "cash_reconciliation": {"current_drift_rub": None}}
        bal = {"as_of_date": "2026-10-30", "snapshot_type": "full"}
        cash = {"as_of_date": "2026-10-30", "snapshot_type": "trades_holdings", "cash_reconciliation": {"current_drift_rub": 123.0}}
        old = {"as_of_date": "2026-10-29", "snapshot_type": "full"}
        br = lambda snap, prev: pf_build.brief({}, snap, prev)   # noqa: E731
        self.assertEqual((br(only, bal)["trades_only"], br(only, bal)["save_block"]), (True, "balance"))
        self.assertEqual(br(only, cash)["save_block"], "cash_fact")
        self.assertIsNone(br(only, only)["save_block"])            # сохранённый тоже без кэша — ухудшения нет
        self.assertIsNone(br(only, old)["save_block"])             # сохранённый другого дня — другой файл
        self.assertIsNone(br(only, None)["save_block"])
        self.assertIsNone(br(bal, bal)["save_block"])              # сборка с балансом
        self.assertFalse(br(cash, bal)["trades_only"])             # с внесённым кэшем это уже не «только сделки»
        self.assertIsNone(br(cash, bal)["save_block"])
        self.assertIsNone(pf_build.brief({}, None, None)["save_block"])

    def test_save_block_agrees_with_save_409(self):
        """Признак brief и 409 из save() — одно условие (SYNC _is_trades_only)."""
        import json as _j
        for snap, prev in (({"snapshot_type": "trades_holdings", "cash_reconciliation": {"current_drift_rub": None}}, {"snapshot_type": "full"}),
                           ({"snapshot_type": "trades_holdings", "cash_reconciliation": {"current_drift_rub": None}},
                            {"snapshot_type": "trades_holdings", "cash_reconciliation": {"current_drift_rub": 5}})):
            snap["as_of_date"] = prev["as_of_date"] = "2026-10-30"
            self.assertEqual(pf_build.save_block(snap, prev) is not None, pf_build._is_trades_only(_j.dumps(snap)) and not pf_build._is_trades_only(_j.dumps(prev)))


if __name__ == "__main__":
    unittest.main(verbosity=1)
