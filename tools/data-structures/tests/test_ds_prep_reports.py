"""Тесты подготовки цикла машиночитаемости: миграция шапок отчётов, словаря вердиктов облигаций и архиватор.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 -m unittest discover -s tools/data-structures/tests -v
Фикстуры синтетические (tests/fixtures/reports); реальные данные не читаются и не пишутся.
"""
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "migrations"))

import archive_pre_ds as arc  # noqa: E402
import migrate_review_recorded_at as rev  # noqa: E402
import migrate_report_frontmatter as mig  # noqa: E402
import migrate_plan_journal_ts as pj  # noqa: E402
import migrate_bond_verdicts as mbv  # noqa: E402
import backfill_decisions as bf  # noqa: E402
import init_security_attrs as isa  # noqa: E402
import backfill_forecast_links as bfl  # noqa: E402
import ds_schemas as ds  # noqa: E402  (путь к _shared-references добавляет backfill_decisions)

FIX = HERE / "fixtures" / "reports"


def read(name: str) -> str:
    with open(FIX / name, encoding="utf-8", newline="") as f:
        return f.read()


def migrate(name: str, aliases=None) -> "mig.Result":
    return mig.migrate_text(name, read(name), aliases)


def split(text: str):
    m = mig.FRONT_RE.match(text)
    return yaml.safe_load(m.group(1)), text[m.end():]


class ModeMappingTests(unittest.TestCase):
    def test_single_stock_gives_4a_and_adds_fields_at_end(self):
        r = migrate("2026-01-10-single-analysis-abcd.md")
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.codes, ["4a"])  # пробелы вокруг mode нормализуются
        fm, _ = split(r.new_text)
        self.assertEqual(list(fm)[-4:], ["mode_codes", "schema_version", "recorded_at", "recorded_at_estimated"])
        self.assertEqual(fm["schema_version"], "report@1")
        self.assertEqual(fm["mode"], "  4 (single)  ")  # старое поле не трогаем

    def test_only_isin_gives_4b(self):
        r = migrate("2026-01-11-single-analysis-bond.md")
        self.assertEqual(r.codes, ["4b"])

    def test_mixed_modes_order_main_first(self):
        self.assertEqual(mig.MODE_TABLE[mig._norm("3/4 (rebalance + single analysis)")], ["4a", "3"])
        self.assertEqual(mig.MODE_TABLE[mig._norm("3/4 (rebalance_opinion + single_analysis)")], ["3", "4a"])
        self.assertEqual(mig.MODE_TABLE[mig._norm("2 (bonds review) + 3 (rebalance) + 4 (single)")], ["3", "2", "4b"])

    def test_every_table_code_is_known(self):
        known = {"2", "3", "4a", "4b", "5a", "5b", "6", "7", "8", "9", "free"}
        for key, codes in mig.MODE_TABLE.items():
            self.assertTrue(codes and set(codes) <= known, key)

    def test_mode_outside_table_not_touched(self):
        r = migrate("2026-01-13-tactical-rebalance-odd-mode.md")
        self.assertEqual(r.status, "no_mapping")
        self.assertIsNone(r.new_text)
        self.assertTrue(any("нет соответствия" in w for w in r.warnings))

    def test_filename_rules_for_files_without_mode(self):
        for pattern_name, codes, kind in [
            ("2026-06-25-advisory-portfolio-iis3.md", ["7", "3"], "iis_buy"),
            ("2026-06-25-ie-posts-review-x.md", ["free"], "general"),
            ("2026-08-25-macro-report-x-2026-08-25.md", ["free"], "general"),
            ("bond-bridge-planner-2026-05-13.md", ["3", "6"], "bond_bridge_planner"),
            ("portfolio-candidates-outside-ie-2026-05-13.md", ["4b"], "candidates_outside_ie"),
        ]:
            r = mig.migrate_text(pattern_name, "# Заголовок\n\nТекст\n")
            self.assertEqual((r.codes, r.kind_new), (codes, kind), pattern_name)


class KindTests(unittest.TestCase):
    def test_variant_a_main_code_8_becomes_quality_review(self):
        r = migrate("2026-01-12-tactical-rebalance-stock-quality-forward-review.md")
        self.assertEqual((r.kind_old, r.kind_new), ("tactical_rebalance", "quality_review"))
        self.assertEqual(r.codes, ["8", "3"])
        self.assertTrue(r.kind_changed)

    def test_other_kinds_unchanged(self):
        r = migrate("2026-01-10-single-analysis-abcd.md")
        self.assertEqual((r.kind_old, r.kind_new), ("single_analysis", "single_analysis"))
        self.assertFalse(r.kind_changed)

    def test_main_code_not_8_keeps_tactical(self):
        self.assertEqual(mig._kind_variant_a("tactical_rebalance", ["3", "8"]), "tactical_rebalance")

    def test_none_kind_derived_from_table(self):
        r = migrate("portfolio-candidates-outside-ie-2026-01-16.md")
        self.assertEqual(r.kind_new, "candidates_outside_ie")
        fm, _ = split(r.new_text)
        self.assertEqual(fm["kind"], "candidates_outside_ie")
        self.assertEqual(fm["date"], "2026-01-16")  # из review_date
        self.assertIn(fm["kind"], mig.ALLOWED_KINDS)


class TickersTests(unittest.TestCase):
    def test_alias_replaces_company_name(self):
        r = migrate("2026-01-12-tactical-rebalance-stock-quality-forward-review.md", {"Норникель": "GMKN"})
        # Норникель -> GMKN, затем дубликат GMKN схлопывается; «Яндекс» без соответствия остаётся
        self.assertEqual(r.tickers_new, ["GMKN", "SBER", "Яндекс"])
        self.assertEqual(r.unrecognized, ["Яндекс"])

    def test_unrecognized_reported_and_kept(self):
        r = migrate("2026-01-12-tactical-rebalance-stock-quality-forward-review.md")
        self.assertEqual(r.unrecognized, ["Норникель", "Яндекс"])
        self.assertIn("Норникель", r.tickers_new)
        report = mig.build_report([r])
        self.assertIn("## Нераспознанные тикеры", report)
        self.assertIn("`Яндекс`", report)

    def test_one_letter_ticker_and_isin_are_keys(self):
        r = migrate("2026-01-10-single-analysis-abcd.md")
        self.assertEqual(r.unrecognized, [])
        self.assertEqual(r.tickers_new, ["GMKN", "NO", "T"])


class BodyAndRoundTripTests(unittest.TestCase):
    def test_body_is_byte_identical(self):
        for name in ["2026-01-10-single-analysis-abcd.md", "2026-01-11-single-analysis-bond.md",
                     "2026-01-12-tactical-rebalance-stock-quality-forward-review.md",
                     "portfolio-candidates-outside-ie-2026-01-16.md"]:
            old = read(name)
            r = migrate(name, {"Норникель": "GMKN"})
            _, old_body = split(old)
            _, new_body = split(r.new_text)
            self.assertEqual(old_body.encode("utf-8"), new_body.encode("utf-8"), name)

    def test_without_frontmatter_whole_original_is_suffix(self):
        for name in ["2026-01-14-macro-report-sample.md", "bond-bridge-planner-2026-01-15.md"]:
            old = read(name)
            r = migrate(name)
            self.assertTrue(r.new_text.endswith(old), name)
            fm, _ = split(r.new_text)
            self.assertEqual(fm["frontmatter_added_by"], "migration")
            self.assertEqual(fm["schema_version"], "report@1")

    def test_header_added_fields(self):
        r = migrate("2026-01-14-macro-report-sample.md")
        fm, _ = split(r.new_text)
        self.assertEqual(fm["date"], "2026-01-14")
        self.assertEqual(fm["title"], "Макро-отчёт: долг и казначейские облигации")
        self.assertEqual(fm["kind"], "general")
        self.assertEqual(fm["mode_codes"], ["free"])
        for k in ("created_at", "model", "author", "summary"):
            self.assertIsNone(fm[k], k)
        self.assertEqual(fm["recorded_at"], "2026-01-14T00:00:00+03:00")
        self.assertIs(fm["recorded_at_estimated"], True)

    def test_recorded_at_estimate(self):
        fm, _ = split(migrate("2026-01-10-single-analysis-abcd.md").new_text)
        self.assertEqual(fm["recorded_at"], "2026-01-10T10:56:00+03:00")  # из created_at
        self.assertIs(fm["recorded_at_estimated"], True)
        self.assertEqual(list(fm)[-2:], ["recorded_at", "recorded_at_estimated"])
        r = migrate("2026-01-12-tactical-rebalance-stock-quality-forward-review.md")  # created_at нет
        fm, _ = split(r.new_text)
        self.assertEqual(fm["recorded_at"], "2026-01-12T00:00:00+03:00")
        self.assertEqual(r.recorded_source, "date")
        fm, _ = split(migrate("portfolio-candidates-outside-ie-2026-01-16.md").new_text)
        self.assertEqual(fm["recorded_at"], "2026-01-16T00:00:00+03:00")  # date взята из review_date
        # created_at неподходящего вида -> запасной вариант по date
        self.assertEqual(mig.estimate_recorded_at("2026-01-10T10:56:00+03:00", "2026-01-10"),
                         ("2026-01-10T00:00:00+03:00", "date"))
        self.assertEqual(mig.estimate_recorded_at(None, None), (None, None))

    def test_existing_recorded_at_not_overwritten(self):
        text = read("2026-01-10-single-analysis-abcd.md").replace(
            "horizon_months: 12\n", 'horizon_months: 12\nrecorded_at: "2026-02-01T09:00:00+03:00"\n')
        r = mig.migrate_text("2026-01-10-single-analysis-abcd.md", text)
        fm, _ = split(r.new_text)
        self.assertEqual(fm["recorded_at"], "2026-02-01T09:00:00+03:00")
        self.assertNotIn("recorded_at_estimated", fm)

    def test_yaml_roundtrip_special_characters(self):
        old = read("2026-01-10-single-analysis-abcd.md")
        fm_old, _ = split(old)
        r = migrate("2026-01-10-single-analysis-abcd.md")
        fm_new, _ = split(r.new_text)
        for k, v in fm_old.items():
            self.assertEqual(fm_new[k], v, k)  # title/summary с «:», кавычками и # переживают дамп
        self.assertEqual(list(fm_new)[:len(fm_old)], list(fm_old))  # порядок полей
        self.assertIsInstance(fm_new["created_at"], str)  # строка-время не превращается в datetime

    def test_roundtrip_multiline_and_date_objects(self):
        for name in ["portfolio-candidates-outside-ie-2026-01-16.md", "2026-01-11-single-analysis-bond.md"]:
            fm_old, _ = split(read(name))
            fm_new, _ = split(migrate(name).new_text)
            for k, v in fm_old.items():
                if k != "kind":
                    self.assertEqual(fm_new[k], v, f"{name}:{k}")

    def test_idempotent(self):
        r1 = migrate("2026-01-10-single-analysis-abcd.md")
        r2 = mig.migrate_text("2026-01-10-single-analysis-abcd.md", r1.new_text)
        self.assertEqual(r2.status, "already")
        self.assertIsNone(r2.new_text)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.reports = self.tmp / "reports"
        shutil.copytree(FIX, self.reports)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = mig.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_writes_nothing_and_prints_report(self):
        before = {p.name: p.read_bytes() for p in self.reports.iterdir()}
        code, out, _ = self.run_cli("--reports", str(self.reports))
        self.assertEqual(code, 0)
        self.assertIn("Нет соответствия", out)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.reports.iterdir()})

    def test_out_writes_changed_copies_and_report(self):
        out_dir = self.tmp / "out"
        self.run_cli("--reports", str(self.reports), "--out", str(out_dir), "--aliases", str(self._aliases()))
        names = {p.name for p in out_dir.iterdir()}
        self.assertIn("migration-report.md", names)
        self.assertNotIn("2026-01-13-tactical-rebalance-odd-mode.md", names)
        self.assertEqual(len(names), 7)  # 6 изменённых + отчёт
        text = (out_dir / "migration-report.md").read_text(encoding="utf-8")
        self.assertIn("Нет соответствия (файл не трогается): 1", text)

    def _aliases(self):
        p = self.tmp / "aliases.json"
        p.write_text(json.dumps({"Норникель": "GMKN"}, ensure_ascii=False), encoding="utf-8")
        return p

    def test_apply_makes_backup_and_does_not_overwrite_it(self):
        orig = (self.reports / "2026-01-10-single-analysis-abcd.md").read_bytes()
        self.run_cli("--reports", str(self.reports), "--apply")
        bak = self.reports / "2026-01-10-single-analysis-abcd.md.pre-ds.bak"
        self.assertEqual(bak.read_bytes(), orig)
        self.assertIn(b"report@1", (self.reports / "2026-01-10-single-analysis-abcd.md").read_bytes())
        odd = self.reports / "2026-01-13-tactical-rebalance-odd-mode.md"
        self.assertFalse(odd.with_name(odd.name + ".pre-ds.bak").exists())
        # повтор: файлы уже мигрированы, копии не перезаписываются
        self.run_cli("--reports", str(self.reports), "--apply")
        self.assertEqual(bak.read_bytes(), orig)


REVIEW_TEXT = """# Weekly Stocks Review — комментарий в начале
schema_version: 2
type: weekly-stocks-review
review_date: "2026-05-06"
horizons: [20]
horizon_ends:
  h20: '2028-01-06'  # комментарий в конце строки
summary: "ключ: значение, # не комментарий"
"""
REVIEW_REVISED = REVIEW_TEXT.replace('summary:', 'revision:\n  number: 2\n  date: \'2026-05-07\'\nsummary:')


class ReviewRecordedAtTests(unittest.TestCase):
    def test_inserts_two_lines_after_review_date_keeping_rest(self):
        r = rev.migrate_text("weekly-review-2026-05-06.yaml", REVIEW_TEXT)
        self.assertEqual(r.status, "ok")
        lines = r.new_text.splitlines()
        i = lines.index('review_date: "2026-05-06"')
        self.assertEqual(lines[i + 1:i + 3], ['recorded_at: "2026-05-06T00:00:00+03:00"', "recorded_at_estimated: true"])
        # остальной текст (в том числе комментарии) не изменился
        self.assertEqual(r.new_text.replace("".join(l + "\n" for l in lines[i + 1:i + 3]), ""), REVIEW_TEXT)
        want = yaml.safe_load(REVIEW_TEXT)
        want.update(recorded_at="2026-05-06T00:00:00+03:00", recorded_at_estimated=True)
        self.assertEqual(yaml.safe_load(r.new_text), want)

    def test_crlf_and_unquoted_date(self):
        text = "review_date: 2026-05-06\r\nx: 1\r\n"
        r = rev.migrate_text("weekly-review-x.yaml", text)
        self.assertEqual(r.status, "ok")
        self.assertIn("recorded_at_estimated: true\r\nx: 1\r\n", r.new_text)

    def test_already_and_error(self):
        self.assertEqual(rev.migrate_text("a.yaml", 'review_date: "2026-05-06"\nrecorded_at: "x"\n').status, "already")
        self.assertEqual(rev.migrate_text("a.yaml", "x: 1\n").status, "error")
        self.assertEqual(rev.migrate_text("a.yaml", "a: [\n").status, "error")

    def test_revision_table_in_report(self):
        results = [rev.migrate_text("weekly-review-a.yaml", REVIEW_REVISED),
                   rev.migrate_text("weekly-review-b.yaml", REVIEW_TEXT)]
        report = rev.build_report(results)
        self.assertIn("| weekly-review-a.yaml | 2026-05-06 | №2 от 2026-05-07 |", report)
        self.assertNotIn("| weekly-review-b.yaml |", report)
        self.assertIn("с `revision`", report.replace("С `revision`", "с `revision`"))

    def test_cli_dry_run_out_and_apply(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        d = tmp / "wr"
        d.mkdir()
        (d / "weekly-review-2026-05-06.yaml").write_text(REVIEW_TEXT, encoding="utf-8")
        (d / "weekly-review-2026-05-06.yaml.bak").write_text("не трогать", encoding="utf-8")
        (d / "weekly-review-2026-05-05.md").write_text("md", encoding="utf-8")

        def cli(*a):
            o, e = io.StringIO(), io.StringIO()
            with redirect_stdout(o), redirect_stderr(e):
                code = rev.main(["--reviews", str(d), *a])
            return code, o.getvalue()
        code, out = cli()
        self.assertEqual(code, 0)
        self.assertEqual((d / "weekly-review-2026-05-06.yaml").read_text(encoding="utf-8"), REVIEW_TEXT)
        self.assertIn("Файлов `weekly-review-*.yaml`: 1", out)
        cli("--out", str(tmp / "out"))
        self.assertTrue((tmp / "out/migration-report.md").exists())
        self.assertIn("recorded_at_estimated", (tmp / "out/weekly-review-2026-05-06.yaml").read_text(encoding="utf-8"))
        cli("--apply")
        self.assertEqual((d / "weekly-review-2026-05-06.yaml.pre-ds.bak").read_text(encoding="utf-8"), REVIEW_TEXT)
        self.assertEqual((d / "weekly-review-2026-05-06.yaml.bak").read_text(encoding="utf-8"), "не трогать")
        code, out = cli("--apply")  # повтор: recorded_at уже стоит
        self.assertIn("Уже стоит `recorded_at`: 1", out)


class ArchiverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.mem = self.tmp / "mem"
        self.dest = self.tmp / "arch"
        files = {
            "Portfolio/conditions.yaml": "a: 1\n",
            "Portfolio/gate-reviews.yaml": "b: 2\n",
            "Portfolio/reports/r1.md": "# r1\n",
            "Portfolio/reports/r1.yaml": "не берём\n",
            "Portfolio/weekly-reviews/weekly-review-2026-05-06.yaml": "review_date: x\n",
            "Portfolio/weekly-reviews/weekly-review-2026-05-06.yaml.bak": "не берём\n",
            "Portfolio/plan-journal.jsonl": '{"ts": 1}\n',
            "stale_flags.yaml": "c: 3\n",
            "Portfolio/securities/AAA.json": "{}",
            "Portfolio/.backups/old.md": "backup",
            "Portfolio/_bak-cutover-2026-08-03/x.txt": "extra",
        }
        for rel, body in files.items():
            p = self.mem / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = arc.main(["--memory", str(self.mem), "--dest", str(self.dest), *args])
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_writes_nothing(self):
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertFalse(self.dest.exists())
        self.assertIn("Файлов: 9", out)  # с reports/r1.yaml (YAML-копия отчёта архивируется), без extra
        self.assertIn("r1.yaml", out)   # YAML-копия отчёта входит в архив
        self.assertIn("weekly-reviews/weekly-review-2026-05-06.yaml |", out)
        self.assertNotIn(".yaml.bak", out)
        self.assertNotIn("_bak-cutover", out)

    def test_macro_chain_and_decision_journal_archived(self):
        """macro-chain/ и Portfolio/decision-journal/ входят целиком (с копиями .bak внутри); verify их видит."""
        extra = {
            "macro-chain/macro-scenarios-2026-07-05.yaml": "a: 1\n",
            "macro-chain/macro-marginal-2026-07-05.yaml": "b: 2\n",
            "macro-chain/macro-scenarios-2026-07-05.yaml.bak": "копия\n",
            "Portfolio/decision-journal/journal.json": "{}",
            "Portfolio/decision-journal/report-2026-10-30.md": "# r\n",
            "Portfolio/snapshots/portfolio-2026-10-30.json": "{}",   # не носитель — в архив не идёт
        }
        for rel, body in extra.items():
            p = self.mem / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
        code, out, _ = self.run_cli("--run", "--step", "2")
        self.assertEqual(code, 0)
        man = json.loads((self.dest / "manifest.json").read_text(encoding="utf-8"))["entries"]
        for rel in extra:
            if rel.startswith("Portfolio/snapshots"):
                self.assertNotIn(rel, man)
                self.assertFalse((self.dest / rel).exists())
            else:
                self.assertIn(rel, man)
                self.assertTrue((self.dest / rel).is_file())
        self.assertIn("macro-chain/macro-scenarios-2026-07-05.yaml |", (self.dest / "MANIFEST.md").read_text(encoding="utf-8"))
        self.assertEqual(arc.verify_archive(self.dest), [])
        (self.dest / "macro-chain/macro-marginal-2026-07-05.yaml").write_text("подмена\n", encoding="utf-8")
        self.assertTrue(any("macro-marginal" in x for x in arc.verify_archive(self.dest)))

    def test_extra_adds_cutover_backup(self):
        _, out, _ = self.run_cli("--extra")
        self.assertIn("_bak-cutover-2026-08-03/x.txt", out)

    def test_run_copies_and_manifest_matches(self):
        code, _, _ = self.run_cli("--run", "--step", "3")
        self.assertEqual(code, 0)
        self.assertEqual((self.dest / "Portfolio/reports/r1.md").read_text(encoding="utf-8"), "# r1\n")
        self.assertTrue((self.dest / "Portfolio/.backups/old.md").exists())
        manifest = json.loads((self.dest / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["entries"]), 9)
        e = manifest["entries"]["stale_flags.yaml"]
        self.assertEqual((e["md5"], e["size"], e["step"]), (arc.md5_of(self.mem / "stale_flags.yaml"), 5, "3"))
        self.assertEqual(arc.verify_archive(self.dest), [])
        md = (self.dest / "MANIFEST.md").read_text(encoding="utf-8")
        self.assertIn("Portfolio/securities/AAA.json", md)

    def test_verify_catches_tampering(self):
        self.run_cli("--run")
        (self.dest / "stale_flags.yaml").write_text("подмена", encoding="utf-8")
        code, out, _ = self.run_cli_verify()
        self.assertEqual(code, 1)
        self.assertIn("stale_flags.yaml", out)

    def run_cli_verify(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = arc.main(["verify", "--dest", str(self.dest)])
        return code, out.getvalue(), err.getvalue()

    def test_repeat_run_does_not_duplicate_manifest_rows(self):
        self.run_cli("--run")
        self.run_cli("--run")
        md_rows = [ln for ln in (self.dest / "MANIFEST.md").read_text(encoding="utf-8").splitlines()
                   if ln.startswith("| 20")]
        self.assertEqual(len(md_rows), 9)
        self.assertEqual(len(json.loads((self.dest / "manifest.json").read_text(encoding="utf-8"))["entries"]), 9)

    def test_differing_file_not_overwritten_without_force(self):
        self.run_cli("--run")
        (self.mem / "stale_flags.yaml").write_text("c: 4\n", encoding="utf-8")
        code, out, err = self.run_cli("--run")
        self.assertEqual(code, 1)
        self.assertIn("отличается", out)
        self.assertEqual((self.dest / "stale_flags.yaml").read_text(encoding="utf-8"), "c: 3\n")
        code, _, _ = self.run_cli("--run", "--force")
        self.assertEqual(code, 0)
        self.assertEqual((self.dest / "stale_flags.yaml").read_text(encoding="utf-8"), "c: 4\n")
        self.assertEqual(arc.verify_archive(self.dest), [])

    def test_journal_override_from_nas(self):
        nas = self.tmp / "nas-plan-journal.jsonl"
        nas.write_text('{"ts": 1}\n{"ts": 2}\n', encoding="utf-8")
        code, out, err = self.run_cli("--run", "--journal", str(nas))
        self.assertEqual(code, 0)
        self.assertEqual((self.dest / "Portfolio/plan-journal.jsonl").read_text(encoding="utf-8"),
                         '{"ts": 1}\n{"ts": 2}\n')   # байты с «NAS», не из зеркала
        man = json.loads((self.dest / "manifest.json").read_text(encoding="utf-8"))
        e = man["entries"]["Portfolio/plan-journal.jsonl"]
        self.assertEqual((e["source"], e["md5"]), ("nas", arc.md5_of(nas)))
        self.assertNotIn("source", man["entries"]["stale_flags.yaml"])
        self.assertEqual(arc.verify_archive(self.dest), [])
        code, _, err = self.run_cli("--run", "--journal", str(self.tmp / "нет.jsonl"))
        self.assertEqual(code, 2)

    def test_default_dest_is_timestamped_per_run(self):
        d = arc.default_dest(self.mem, "1", "2026-10-31T11:30:58+03:00")
        self.assertEqual(d, self.mem / "_archive/data-structures/2026-10-31T1130-step1")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = arc.main(["--memory", str(self.mem), "--run", "--step", "2"])
        self.assertEqual(code, 0)
        parent = self.mem / "_archive/data-structures"
        dirs = sorted(p.name for p in parent.iterdir())
        self.assertEqual(len(dirs), 1)
        self.assertRegex(dirs[0], r"^\d{4}-\d{2}-\d{2}T\d{4}-step2$")
        self.assertIn("Папка архива:", out.getvalue())
        # папка архива внутри памяти не попадает в собственные источники
        self.assertNotIn("_archive/", (parent / dirs[0] / "MANIFEST.md").read_text(encoding="utf-8"))
        # verify без --dest берёт последнюю папку
        out2 = io.StringIO()
        with redirect_stdout(out2), redirect_stderr(io.StringIO()):
            code = arc.main(["verify", "--memory", str(self.mem)])
        self.assertEqual(code, 0)
        self.assertIn(dirs[0], out2.getvalue())
        # второй прогон — новая папка, а не перезапись (если минута та же — имя совпадёт; проверяем через явное время)
        d2 = arc.default_dest(self.mem, "2", "2026-10-31T11:31:00+03:00")
        self.assertNotEqual(d, d2)

    def test_plan_journal_warning_only_on_mirror(self):
        _, _, err = self.run_cli()
        self.assertNotIn("зеркала", err)  # временная папка — не зеркало
        self.assertTrue(arc.is_mirror(Path("/Users/x/Library/CloudStorage/SynologyDrive-home/Claude-Memory")))


class PlanJournalTsTests(unittest.TestCase):
    SRC = (
        '{"ts": "2026-10-30T21:40:00Z", "who": "site", "path": "stocks.AAAA.plan_pct", "was": 1, "now": 2, "reason": null}\n'
        '{"ts": "2026-10-31T10:00:05", "who": "site", "kind": "import", "reason": "x"}\n'
        '{"ts": "2026-10-31T12:00:00+03:00", "who": "site", "path": "p", "decision_id": null}\n'
        'не json\n'
        '\n'
    )

    def test_ts_converted_by_recount_and_decision_id_added(self):
        new, cnt = pj.migrate_text(self.SRC)
        rows = [json.loads(x) for x in new.splitlines() if x.startswith("{")]
        self.assertEqual(rows[0]["ts"], "2026-10-31T00:40:00+03:00")   # 21:40Z — уже следующие сутки по Москве
        self.assertEqual(rows[1]["ts"], "2026-10-31T13:00:05+03:00")   # без пояса = UTC
        self.assertEqual(rows[2]["ts"], "2026-10-31T12:00:00+03:00")
        self.assertTrue(all("decision_id" in r and r["who"] == "site" for r in rows))
        self.assertEqual((cnt["rows"], cnt["ts_converted"], cnt["decision_id_added"], cnt["skipped"]), (3, 2, 2, 1))
        self.assertIn("не json\n", new)                                  # нечитаемая строка не тронута

    def test_idempotent_and_self_check(self):
        once, _ = pj.migrate_text(self.SRC)
        twice, cnt = pj.migrate_text(once)
        self.assertEqual(once, twice)
        self.assertEqual((cnt["ts_converted"], cnt["decision_id_added"]), (0, 0))
        self.assertEqual(pj.check_text(once), [])
        self.assertTrue(pj.check_text(self.SRC))

    def test_cli_in_out_and_in_place_backup(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = Path(d) / "j.jsonl", Path(d) / "j.new.jsonl"
            src.write_text(self.SRC, encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(pj.main(["--in", str(src), "--out", str(dst)]), 0)
                self.assertEqual(src.read_text(encoding="utf-8"), self.SRC)   # исходник не тронут
                self.assertEqual(pj.check_text(dst.read_text(encoding="utf-8")), [])
                self.assertEqual(pj.main(["--in", str(src), "--out", str(src)]), 0)
            self.assertTrue((Path(d) / "j.jsonl.pre-ds.bak").exists())
            self.assertEqual(src.read_text(encoding="utf-8"), dst.read_text(encoding="utf-8"))



# Синтетический обзор облигаций: словарь (per_bond), старый вид-список, счётчик, проза, fundamental_score.
BOND_REVIEW = """schema_version: 2
type: weekly-bonds-review
review_date: "2026-01-20"
summary:
  verdict_counts:
    HOLD_TO_MAT: 3
    ADD: 1
    HOLD_ADD: 2
    RED_FLAG: 1
  vocabulary_note: словарь (HOLD_TO_MAT / HOLD_ADD / ADD / TRIM)   # проза не меняется
per_bond:
  RU000A000AA1:
    name: "Бумага 1"
    fundamental_score: RED_FLAG          # оценка фундаментала — другой перечень
    advisor_verdict: RED_FLAG   # был красный флаг
    prior_verdict: "HOLD_ADD"
    advisor_verdict_basis: "Рейтинг на пересмотре; RED_FLAG по иску."
  RU000A000AA2:
    name: Бумага 2
    advisor_verdict: HOLD_NO_OFFER
    advisor_verdict_confidence: 0.85
    advisor_verdict_basis: "Оферта 15.06 — не предъявлять."
    verification_priority: HIGH
  RU000A000AA3:
    advisor_verdict: HOLD_NO_OFFER
    advisor_verdict_basis: |
      Оферта через месяц,
      купон выше ставки.
    user_constraints:
      - kind: hold_override
    unconstrained_verdict: MATURE
  RU000A000AA4:
    advisor_verdict: HOLD_NO_OFFER
    advisor_verdict_basis: держать до оферты
  RU000A000AA5:
    advisor_verdict: HOLD_TO_MAT
    advisor_verdict_basis: без изменений
bonds_old_list:
  - isin: RU000A000BB1
    verdict: HOLD_NO_OFFER
    notes: "ОФЕРТА 15.06"
  - isin: RU000A000BB2
    verdict: MATURE
"""


class BondVerdictMigrationTests(unittest.TestCase):
    def setUp(self):
        self.r = mbv.migrate_text("weekly-review-bond-2026-01-20.yaml", BOND_REVIEW)
        self.new = yaml.safe_load(self.r.new_text)

    def test_map_from_codelists(self):
        self.assertEqual(mbv.LEGACY, {"HOLD_ADD": "ADD", "RED_FLAG": "WATCH", "MATURE": "HOLD_TO_MAT",
                                      "HOLD_NO_OFFER": "HOLD_TO_MAT"})

    def test_values_replaced(self):
        pb = self.new["per_bond"]
        self.assertEqual(pb["RU000A000AA1"]["advisor_verdict"], "WATCH")
        self.assertEqual(pb["RU000A000AA1"]["prior_verdict"], "ADD")
        self.assertEqual(pb["RU000A000AA2"]["advisor_verdict"], "HOLD_TO_MAT")
        self.assertEqual(pb["RU000A000AA3"]["unconstrained_verdict"], "HOLD_TO_MAT")
        self.assertEqual([b["verdict"] for b in self.new["bonds_old_list"]], ["HOLD_TO_MAT", "HOLD_TO_MAT"])
        self.assertEqual(self.r.n_replaced, 8)
        self.assertEqual(self.r.replaced["advisor_verdict: HOLD_NO_OFFER→HOLD_TO_MAT"], 3)

    def test_untouched(self):
        pb = self.new["per_bond"]
        self.assertEqual(pb["RU000A000AA1"]["fundamental_score"], "RED_FLAG")
        self.assertIn("RED_FLAG по иску", pb["RU000A000AA1"]["advisor_verdict_basis"])        # проза
        self.assertIn("HOLD_ADD", self.new["summary"]["vocabulary_note"])
        self.assertIn('    fundamental_score: RED_FLAG          # оценка фундаментала', self.r.new_text)
        self.assertIn("    advisor_verdict: WATCH   # был красный флаг", self.r.new_text)    # комментарий цел
        self.assertIn('    prior_verdict: "ADD"', self.r.new_text)                         # кавычки целы
        self.assertGreaterEqual(self.r.prose_mentions, 2)

    def test_counts_merged(self):
        self.assertEqual(self.new["summary"]["verdict_counts"], {"HOLD_TO_MAT": 3, "ADD": 3, "WATCH": 1})
        self.assertEqual(sorted(self.r.counts_merged), ["HOLD_ADD→ADD: 2", "RED_FLAG→WATCH: 1"])

    def test_no_offer_mark(self):
        pb = self.new["per_bond"]
        self.assertEqual(pb["RU000A000AA2"]["advisor_verdict_basis"], "Оферта 15.06 — не предъявлять. (к оферте не предъявлять)")
        self.assertEqual(pb["RU000A000AA3"]["advisor_verdict_basis"],
                         "Оферта через месяц,\nкупон выше ставки.\n(к оферте не предъявлять)\n")
        self.assertEqual(pb["RU000A000AA4"]["advisor_verdict_basis"], "держать до оферты (к оферте не предъявлять)")
        self.assertEqual(pb["RU000A000AA5"]["advisor_verdict_basis"], "без изменений")      # не HOLD_NO_OFFER
        self.assertEqual(self.r.basis_marked, 3)
        self.assertEqual(len(self.r.basis_missing), 1)                  # запись списка без advisor_verdict_basis
        self.assertEqual(self.r.status, "ok")

    def test_idempotent(self):
        again = mbv.migrate_text("x.yaml", self.r.new_text)
        self.assertEqual(again.status, "unchanged")
        self.assertIsNone(again.new_text)
        self.assertEqual(again.n_replaced, 0)

    def test_untouched_lines_byte_identical(self):
        old, new = BOND_REVIEW.split("\n"), self.r.new_text.split("\n")
        same = [ln for ln in old if ln in new]
        changed = [ln for ln in old if ln not in new]
        expected_extra = {"    ADD: 1",                                                 # счётчик принял слияние
                          '    advisor_verdict_basis: "Оферта 15.06 — не предъявлять."',  # пометка «без оферты»
                          "    advisor_verdict_basis: держать до оферты"}
        self.assertEqual({ln for ln in changed if not any(c in ln for c in mbv.LEGACY)}, expected_extra)
        self.assertGreater(len(same), 30)

    def test_failed_check_is_error_not_written(self):
        # код внутри блочного скаляра — построчная правка изменила бы прозу: проверка ловит, файл не пишется
        text = "per_bond:\n  X:\n    advisor_verdict_basis: |\n      advisor_verdict: HOLD_ADD\n"
        r = mbv.migrate_text("bad.yaml", text)
        self.assertEqual(r.status, "error")
        self.assertIsNone(r.new_text)

    def test_cli_report_out_apply(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "wr"
            src.mkdir()
            (src / "weekly-review-bond-2026-01-20.yaml").write_text(BOND_REVIEW, encoding="utf-8")
            (src / "weekly-review-stock-2026-01-20.yaml").write_text("advisor_verdict: HOLD_ADD\n", encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(mbv.main(["--in", str(src)]), 0)                  # только отчёт
            self.assertIn("Замен значений: 8", buf.getvalue())
            self.assertEqual((src / "weekly-review-bond-2026-01-20.yaml").read_text(encoding="utf-8"), BOND_REVIEW)
            out = Path(d) / "out"
            with redirect_stdout(io.StringIO()):
                mbv.main(["--in", str(src), "--out", str(out)])
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                             ["migration-report.md", "weekly-review-bond-2026-01-20.yaml"])   # акции не трогаются
            with redirect_stdout(io.StringIO()):
                mbv.main(["--in", str(src), "--apply"])
            self.assertTrue((src / "weekly-review-bond-2026-01-20.yaml.pre-ds.bak").exists())
            self.assertEqual((src / "weekly-review-bond-2026-01-20.yaml").read_text(encoding="utf-8"),
                             self.r.new_text)
            self.assertEqual((src / "weekly-review-stock-2026-01-20.yaml").read_text(encoding="utf-8"),
                             "advisor_verdict: HOLD_ADD\n")

# ----------------------------------------------------------------------------- шаг 9: бэкфилл решений

GATES_YAML = """schema_version: gate-reviews@1.0
tickers:
  AAA:
    status: reviewed_keep
    set_date: '2026-09-19'
    set_by: mode_8
    trigger_reason: Текущая запись AAA.
    valid_until: '2026-11-18'
    ticker_class: bluechip
    history:
    - {date: '2026-05-15', status: reviewed_buy_more, set_by: mode_8, reason: Первый разбор}
    - {date: '2026-05-15', status: reviewed_keep, set_by: mode_4, reason: Второй разбор того же дня}
    - {date: '2026-07-01', status: review_aging, set_by: auto, reason: 'auto-aging: valid_until 2026-06-20 expired'}
    - {date: '2026-07-02', status: review_needed, set_by: mode_1, reason: Флаг обзора}
    - {date: '2026-08-01', status: reviewed_under_review, set_by: user, reason: Слово владельца}
    - {date: '2026-09-19', status: reviewed_keep, set_by: mode_8, reason: Текущая запись AAA.}
  BBB:
    status: divested
    set_date: '2026-08-06'
    set_by: auto
    trigger_reason: 'auto-divest: missing 1 snapshot(s)'
    valid_until: null
    ticker_class: ipo
    history:
    - {date: '2026-06-28', status: reviewed_reduce, set_by: mode_4, reason: Срез}
    - {date: '2026-08-06', status: divested, set_by: auto, reason: 'auto-divest: missing 1 snapshot(s)'}
  CCC:
    status: reviewed_reduce
    set_date: '2026-10-23'
    set_by: mode_4
    trigger_reason: Срез CCC.
    valid_until: '2026-11-06'
    ticker_class: mid_cap
    history:
    - {date: '2026-10-23', status: reviewed_reduce, set_by: mode_4, reason: Срез CCC.}
  DDD:
    status: new_position
    set_date: '2026-10-01'
    set_by: auto
    trigger_reason: first appearance
    valid_until: null
    ticker_class: ''
    history:
    - {date: '2026-10-01', status: new_position, set_by: auto, reason: first appearance}
"""

REPORT_MD = """---
title: Разбор
date: '2026-10-23'
kind: single_analysis
mode: 4 (single)
tickers: [CCC, AAA]
---
# Разбор

```yaml
gate_review_update:
  - ticker: CCC
    new_status: reviewed_reduce
    set_date: 2026-10-23
    set_by: mode_4
    reason: Срез CCC.
  - ticker: AAA
    new_status: reviewed_keep
    set_date: 2026-10-23
    set_by: mode_4
    reason: Директива, не применённая в гейт.
    valid_days: 45
  - ticker: CCC
    new_status: review_needed
    set_date: 2026-10-24
    set_by: mode_4
    reason: флаг
```
"""

REPORT_CONFLICT_MD = """---
title: Разбор 2
date: '2026-09-19'
kind: single_analysis
mode: 4 (single)
tickers: [AAA, EEE]
---
```yaml
gate_review_update:
  ticker: AAA
  new_status: reviewed_reduce
  set_date: 2026-09-19
  reason: расходится с историей
```
"""

WEEKLY_YAML = """review_date: '2026-10-16'
proposed_gate_review_directives:
- ticker: AAA
  proposed_action: override_cooldown_and_set_review_needed
  set_date: '2026-10-16'
  set_by: mode_1
  reason: событие
per_stock:
  AAA:
    advisor_verdict: SELL
"""


def _bf_fixture(root: Path):
    arch = root / "arch" / "Portfolio"
    (arch / "reports").mkdir(parents=True)
    (arch / "weekly-reviews").mkdir()
    (arch / "gate-reviews.yaml").write_text(GATES_YAML, encoding="utf-8")
    (arch / "gate-reviews-archive-2026.yaml").write_text(
        "entries:\n- {ticker: CCC, date: '2026-05-15', status: reviewed_keep, set_by: mode_8, reason: Вынесено}\n",
        encoding="utf-8")
    (arch / "reports" / "2026-10-23-single-analysis-ccc-aaa.md").write_text(REPORT_MD, encoding="utf-8")
    (arch / "reports" / "2026-09-19-single-analysis-aaa.md").write_text(REPORT_CONFLICT_MD, encoding="utf-8")
    (arch / "weekly-reviews" / "weekly-review-stock-2026-10-16.yaml").write_text(WEEKLY_YAML, encoding="utf-8")
    return root / "arch"


def _bf_run(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = bf.main(argv)
    return code, buf.getvalue()


class BackfillDecisionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.arch = _bf_fixture(self.tmp)
        self.out = self.tmp / "out"
        code, out = _bf_run(["build", "--archive", str(self.arch), "--out", str(self.out)])
        self.assertEqual(code, 0, out)
        self.res = json.loads(out)
        self.dec = {}
        for f in sorted((self.out / "Portfolio" / "decisions").glob("*.json")):
            self.dec[f.stem] = json.loads(f.read_text(encoding="utf-8"))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_all_files_valid_backfill_estimated(self):
        self.assertTrue(self.dec)
        for d in self.dec.values():
            self.assertEqual(ds.validate_decision(d), [], d["id"])
            self.assertIs(d["recorded_at_estimated"], True)
            self.assertEqual(d["source"]["kind"], "backfill")
            self.assertIsNone(d["target_pct"])
            self.assertEqual((d["conditions_created"], d["conditions_resolved"]), ([], []))

    def test_inverse_map_and_which_rows(self):
        got = sorted((k, d["verdict"], d["author"]) for k, d in self.dec.items())
        self.assertEqual(got, [
            ("2026-05-15T0000-AAA", "ADD", "model"), ("2026-05-15T0000-CCC", "HOLD", "model"),
            ("2026-05-15T0001-AAA", "HOLD", "model"), ("2026-06-28T0000-BBB", "TRIM", "model"),
            ("2026-08-01T0000-AAA", "WATCH", "owner"), ("2026-09-19T0000-AAA", "HOLD", "model"),
            ("2026-10-23T0000-AAA", "HOLD", "model"), ("2026-10-23T0000-CCC", "TRIM", "model")])
        # auto, review_needed, new_position — без решений; текущая запись = последняя строка истории — без дубля
        self.assertNotIn("DDD", {d["key"] for d in self.dec.values()})
        self.assertEqual(self.res["without_decision"][0]["key"], "DDD")

    def test_review_by_rules(self):
        d = self.dec
        self.assertEqual(d["2026-09-19T0000-AAA"]["review_by"], "2026-11-18")   # valid_until текущей записи
        self.assertEqual(d["2026-05-15T0000-AAA"]["review_by"], "2026-05-22")   # следующая строка в тот же день → clamp 7
        self.assertEqual(d["2026-05-15T0001-AAA"]["review_by"], "2026-06-20")   # следующая — авто-истечение: его срок
        self.assertEqual(d["2026-08-01T0000-AAA"]["review_by"], "2026-09-19")   # дата следующей строки
        self.assertEqual(d["2026-06-28T0000-BBB"]["review_by"], "2026-08-06")
        self.assertEqual(d["2026-10-23T0000-AAA"]["review_by"], "2026-12-07")   # директива: + valid_days
        self.assertEqual(d["2026-05-15T0001-AAA"]["recorded_at"], "2026-05-15T00:01:00+03:00")
        self.assertEqual(d["2026-05-15T0000-CCC"]["review_by"], "2026-10-23")   # строка архива гейтов в истории

    def test_directives_enrich_new_conflict_flag(self):
        doc = "Portfolio/reports/2026-10-23-single-analysis-ccc-aaa.md"
        self.assertEqual(self.dec["2026-10-23T0000-CCC"]["source"]["doc"], doc)
        self.assertEqual(self.dec["2026-10-23T0000-CCC"]["source"]["mode_codes"], ["4a"])
        self.assertEqual(self.dec["2026-10-23T0000-AAA"]["source"]["doc"], doc)   # нет в истории → отдельное
        self.assertIsNone(self.dec["2026-09-19T0000-AAA"]["source"]["doc"])        # конфликт статусов — не обогащено
        rep = (self.out / "backfill-report.md").read_text(encoding="utf-8")
        self.assertIn("конфликт: в истории на эту дату reviewed_keep", rep)
        self.assertIn("флаг обзора (review_needed)", rep)
        self.assertIn("weekly-review-stock-2026-10-16.yaml | proposed_gate_review_directives", rep)
        self.assertNotIn("SELL", json.dumps(self.dec))   # смены вердикта в обзоре не копируются
        self.assertIn("Portfolio/reports/2026-09-19-single-analysis-aaa.md | single_analysis", rep)   # кандидат LLM: EEE
        self.assertIn("| EEE |", rep)

    def test_build_refuses_nonempty_and_live_root(self):
        code, out = _bf_run(["build", "--archive", str(self.arch), "--out", str(self.out)])
        self.assertEqual(code, 1)
        self.assertIn("не пуст", out)
        code, out = _bf_run(["build", "--archive", str(self.arch), "--out", str(bf.LIVE_ROOT / "Portfolio")])
        self.assertEqual(code, 1)
        self.assertIn("внутри рабочей Claude-Memory", out)

    def _snap(self, keys, extra=()):
        p = self.tmp / "snap.json"
        h = [{"ticker": k, "qty": 1, "asset_type": "stock"} for k in keys]
        h += [{"ticker": k, "qty": 1, "asset_type": "fund"} for k in extra]
        p.write_text(json.dumps({"as_of_date": "2026-10-30", "holdings": h}), encoding="utf-8")
        return p

    def _verify(self, snap, today="2026-10-31", gates=None, extra=()):
        types = self.tmp / "types.json"
        types.write_text(json.dumps({"by_ticker": {k: {"type": "stock"} for k in ("AAA", "BBB", "CCC", "DDD", "ZZZ")}
                                     | {"FFF": {"type": "fund"}}}), encoding="utf-8")
        return _bf_run(["verify", "--out", str(self.out), "--gates",
                        str(gates or self.arch / "Portfolio/gate-reviews.yaml"),
                        "--snapshot", str(snap), "--today", today, "--types", str(types), *extra])

    def _gates(self, **status):
        g = yaml.safe_load(GATES_YAML)
        for k, st in status.items():
            g["tickers"].setdefault(k, {"set_date": "2026-10-01", "set_by": "mode_4", "history": []})["status"] = st
        p = self.tmp / "g2.yaml"
        p.write_text(yaml.safe_dump(g, allow_unicode=True), encoding="utf-8")
        return p

    def test_verify_reproduces_stock_only(self):
        # BBB продан, DDD — новая без решения; фонд FFF в архиве и в снапшоте — гейт не ведётся, из сравнения вон
        code, out = self._verify(self._snap(["AAA", "CCC", "DDD"], extra=["FFF"]), gates=self._gates(FFF="divested"))
        self.assertEqual(code, 0, out)
        self.assertIn("совпало 4 / устаревших записей архива 0 / расхождений 0", out)
        self.assertIn("гейт не ведётся: 1", out)
        self.assertIn("| FFF | divested | — | — | — | — | гейт не ведётся |", out)
        code, out = self._verify(self._snap(["AAA", "CCC", "DDD"]), today="2026-11-10")   # срок CCC 06.11 истёк
        self.assertEqual(code, 0, out)                                                   # базовый совпал — не падение
        self.assertIn("в проекции review_aging", out)

    def test_verify_stale_archive_does_not_fail(self):
        code, out = self._verify(self._snap(["AAA", "DDD"]))   # CCC продан, архив гейтов не обслуживался
        self.assertEqual(code, 0, out)
        self.assertIn("| CCC | reviewed_reduce | divested |", out)
        self.assertIn("устаревшая запись архива", out)
        self.assertIn("совпало 3 / устаревших записей архива 1 / расхождений 0", out)

    def test_verify_mismatch_fails(self):
        code, out = self._verify(self._snap(["AAA", "CCC", "DDD"]), gates=self._gates(CCC="reviewed_keep"))
        self.assertEqual(code, 1)
        self.assertIn("базовый статус reviewed_reduce, ожидался reviewed_keep", out)
        code, out = self._verify(self._snap(["AAA", "CCC", "DDD", "ZZZ"]), gates=self._gates(ZZZ="reviewed_keep"))
        self.assertEqual(code, 1)                                # reviewed_* в архиве, решения нет
        self.assertIn("нет решения (ожидался базовый reviewed_keep)", out)

    def test_verify_aging_and_review_needed_in_archive(self):
        g = self._gates(CCC="review_aging", AAA="review_needed")
        code, out = self._verify(self._snap(["AAA", "CCC", "DDD"]), today="2026-11-10", gates=g)
        self.assertIn("| CCC | review_aging | review_aging |", out)
        self.assertIn("| AAA | review_needed | reviewed_keep |", out)   # базовый совпал с последним reviewed_* истории
        self.assertEqual(code, 0, out)

    def test_projection_by_last_word(self):
        """verify считает статус модулем (б) last_word — локальной проекции нет (шаг 11)."""
        mk = lambda k, t, v, rb=None: {"id": f"{t[:10]}T{t[11:13]}{t[14:16]}-{k}", "key": k, "verdict": v,
                                       "review_by": rb, "recorded_at": t}
        decs = [mk("A", "2026-10-01T00:00:00+03:00", "ADD", "2026-12-01"),
                mk("A", "2026-10-01T00:01:00+03:00", "SELL", "2026-12-01"),
                mk("B", "2026-08-01T00:00:00+03:00", "HOLD")]          # null → +60 = 30.09 < сегодня
        p = bf.projection(decs, {"A", "B", "N"}, "2026-10-31")
        self.assertEqual((p["A"]["status"], p["A"]["base"]), ("reviewed_reduce", "reviewed_reduce"))   # новейшее
        self.assertEqual((p["B"]["status"], p["B"]["review_by"]), ("review_aging", "2026-09-30"))
        self.assertEqual((p["N"]["status"], p["N"]["decision_id"]), (None, None))   # держимая без решения — без статуса
        self.assertEqual(bf.projection(decs, {"B"}, "2026-10-31")["A"]["status"], "divested")
        self.assertEqual(bf.projection(decs, set(), "2026-10-31", keys=["Z"])["Z"]["status"], "divested")
        only_b = bf.projection(decs, {"A", "B"}, "2026-10-31", is_stock=lambda k: k != "A")
        self.assertEqual(sorted(only_b), ["B"])                           # не акция — вне проекции
        self.assertIn("модулем (б)", bf.projection.__doc__)
        self.assertFalse(hasattr(bf, "gate_projection"))


# ----------------------------------------------------------------------------- шаг 9: справочник бумаг

class SecurityAttrsTests(unittest.TestCase):
    TYPES = {"by_ticker": {"AAA": {"type": "stock"}, "BBB": {"type": "stock"}, "FFF": {"type": "fund"},
                           "OLD": {"type": "stock"}, "RU000A000001": {"type": "bond"}}}
    SNAP = {"holdings": [{"ticker": "AAA", "qty": 5, "listing_date": "1997-03-24"},
                         {"ticker": "FFF", "qty": 1}, {"ticker": "ZZZ.DE", "qty": 1}, {"ticker": "OLD", "qty": 0}]}
    GATES = {"AAA": {"ticker_class": "bluechip"}, "BBB": {"ticker_class": "ipo"}, "FFF": {"ticker_class": "fund_zpif"},
             "CCC": {"ticker_class": ""}}
    NOW = "2026-10-31T12:00:00+03:00"

    def fetch(self, url):
        self.calls.append(url)
        self.assertNotIn("/boards/", url)                 # любая доска, не TQBR
        self.assertIn("from=1990-01-01&limit=1", url)
        if "/securities/AAA" in url:
            return {"history": {"columns": ["SECID", "TRADEDATE", "BOARDID"], "data": [["AAA", "2025-01-09", "TQBR"]]}}
        if "/securities/BBB" in url:
            return {"history": {"columns": ["SECID", "TRADEDATE", "BOARDID"], "data": [["BBB", "2025-06-01", "SMAL"]]}}
        return None

    def setUp(self):
        self.calls = []

    def test_build_keys_classes_dates(self):
        doc, info = isa.build(self.TYPES, self.SNAP, self.GATES, "2026-10-31", self.NOW, fetch=self.fetch)
        self.assertEqual(ds.validate_security_attrs(doc), [])
        bk = doc["by_key"]
        self.assertEqual(sorted(bk), ["AAA", "BBB", "CCC", "FFF", "OLD", "RU000A000001", "ZZZ.DE"])
        self.assertEqual(bk["AAA"], {"ticker_class": "bluechip", "listed_at": "2025-01-09", "note": None,
                                     "updated_at": self.NOW, "updated_by": "script"})
        self.assertEqual(bk["BBB"]["listed_at"], "2025-06-01")      # первая строка истории, доска любая
        self.assertIsNone(bk["CCC"]["ticker_class"])                # пустой класс → null
        self.assertIsNone(bk["FFF"]["listed_at"])                   # не акция — дата не запрашивается
        self.assertIsNone(bk["OLD"]["listed_at"])                   # акция без класса и не в снапшоте
        self.assertEqual(sorted(info["fetched"]), ["AAA", "BBB"])
        rep = isa.render_report(doc, info, "w.yaml", {"BBB": {"listing_age_quarters": 5, "post_ipo_guard": True}}, False)
        self.assertIn("| BBB | 2025-06-01 | SMAL | 5 | — | 5 | True |", rep)   # дата снапшота — для сравнения
        self.assertIn("| AAA | 2025-01-09 | bluechip | 1997-03-24 |", rep)   # «проверить владельцу»
        self.assertIn("| AAA | 2025-01-09 | 1997-03-24 |", rep)              # расхождение со снапшотом

    def test_offline_and_unknown_class(self):
        doc, info = isa.build(self.TYPES, self.SNAP, self.GATES, "2026-10-31", self.NOW, offline=True, fetch=self.fetch)
        self.assertEqual(self.calls, [])
        self.assertTrue(all(r["listed_at"] is None for r in doc["by_key"].values()))
        self.assertIn("offline", info["fetch_notes"]["AAA"])
        with self.assertRaises(bf.Fail):
            isa.build(self.TYPES, self.SNAP, {"AAA": {"ticker_class": "megacap"}}, "2026-10-31", self.NOW, offline=True)

    def test_validator_rules(self):
        ok = {"ticker_class": None, "listed_at": None, "note": None, "updated_at": self.NOW, "updated_by": "script"}
        self.assertEqual(ds.validate_security_attrs({"schema_version": "security-attrs@1", "by_key": {"A": ok}}), [])
        bad = {"schema_version": "security-attrs@2", "by_key": {
            "A": dict(ok, ticker_class="megacap"), "B": dict(ok, listed_at="2025-13-01"),
            "C": dict(ok, note="x" * 201), "D": dict(ok, updated_at="2026-10-31T12:00:00"),
            "E": dict(ok, updated_by="robot"), "F": {k: v for k, v in ok.items() if k != "note"},
            "G H": ok, "I": dict(ok, extra=1)}}
        errs = "\n".join(ds.validate_security_attrs(bad))
        for frag in ("schema_version", "by_key.A.ticker_class", "by_key.B.listed_at", "by_key.C.note",
                     "by_key.D.updated_at", "by_key.E.updated_by", "by_key.F.note: обязательное",
                     "by_key.G H: ключ", "by_key.I.extra: неизвестное"):
            self.assertIn(frag, errs)

    def test_decision_estimated_flag_type(self):
        d = {"schema_version": "decision@1", "id": "2026-10-01T0000-AAA", "key": "AAA", "verdict": "HOLD",
             "target_pct": None, "review_by": None, "note": "x", "conditions_created": [], "conditions_resolved": [],
             "source": {"kind": "backfill", "doc": None, "mode_codes": [], "stress_id": None}, "author": "model",
             "recorded_at": "2026-10-01T00:00:00+03:00"}
        self.assertEqual(ds.validate_decision(d), [])                      # поле необязательное
        self.assertEqual(ds.validate_decision(dict(d, recorded_at_estimated=True)), [])
        self.assertIn("recorded_at_estimated", ds.validate_decision(dict(d, recorded_at_estimated="да"))[0])

    def test_cli_writes_only_out(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "types.json").write_text(json.dumps(self.TYPES), encoding="utf-8")
            (t / "snap.json").write_text(json.dumps(self.SNAP), encoding="utf-8")
            (t / "g.yaml").write_text(yaml.safe_dump({"tickers": self.GATES}), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                code = isa.main(["--types", str(t / "types.json"), "--snapshot", str(t / "snap.json"), "--gates",
                                 str(t / "g.yaml"), "--out", str(t / "out"), "--offline", "--now", self.NOW])
            self.assertEqual(code, 0)
            doc = json.loads((t / "out/Portfolio/security-attrs.json").read_text(encoding="utf-8"))
            self.assertEqual(ds.validate_security_attrs(doc), [])
            self.assertIn("Режим --offline", (t / "out/security-attrs-report.md").read_text(encoding="utf-8"))
            self.assertEqual(sorted(p.name for p in (t / "out/Portfolio").iterdir()), ["security-attrs.json"])



class BackfillForecastLinksTests(unittest.TestCase):
    """Шаг 14 (schema.md §4.6): forecast_files{} двум последним макросценариям, стресс не меняется (R22)."""

    MS = (
        "schema_version: 1\n"
        "type: macro-scenarios\n"
        "assembled_date: '{d}'\n"
        "# комментарий сохраняется\n"
        "scenario_matrix:\n  source_file: scenarios/geo-2026-07-01.yaml\n"
        "factors:\n"
        "  brent_price:\n    source_forecast: brent\n    unit: usd\n"
        "  cbr_rate:\n    source_forecast: cbr_rate\n"
        "  usdrub_rate:\n    source_forecast: usdrub\n"
        "  xauusd_price:\n    unit: usd\n"
        "  inflation_ru:\n    source_forecast: nosuch\n"
        "  cnyrub_rate:\n    source_files: ['forecasts/cnyrub-rate-2026-09-01.yaml']\n"
        "caveats: []\n"
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "mem"
        (self.root / "macro-chain").mkdir(parents=True)
        (self.root / "forecasts").mkdir()
        (self.root / "Portfolio" / "stress").mkdir(parents=True)
        for d in ("2026-08-30", "2026-09-17", "2026-10-04"):
            (self.root / "macro-chain" / f"macro-scenarios-{d}.yaml").write_text(self.MS.format(d=d), encoding="utf-8")
        (self.root / "macro-chain" / "macro-marginal-2026-10-04.yaml").write_text("x: 1\n", encoding="utf-8")

        def fc(stem, topic, date, **extra):
            body = {"type": "forecast-events", "status": "active", "forecast": {"topic": topic, "date": date}}
            body.update(extra)
            (self.root / "forecasts" / f"{stem}.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")
        fc("brent-price-2026-09-17", "brent-price", "2026-09-17", superseded_by="brent-price-2026-10-08")
        fc("brent-price-2026-10-08", "brent-price", "2026-10-08")            # позже сборки 04.10 — не берётся
        fc("brent-price-2026-07-28", "brent-price", "2026-07-28")
        fc("cbr-rate-2026-2027-2026-09-17", "cbr-rate-2026-2027", "2026-09-17")   # тема файлов ≠ слаг
        fc("usdrub-rate-2026-09-17", "usdrub-rate", "2026-09-17")
        fc("usdrub-rate-2026-09-17-v2", "usdrub-rate", "2026-09-17")        # два файла одной даты
        (self.root / "Portfolio/stress/stress-2026-10-04-x.yaml").write_text(
            "schema_version: 2\nmacro_input: macro-scenarios-2026-10-04.yaml\n", encoding="utf-8")
        (self.root / "Portfolio/stress/stress-2026-09-18-x.yaml").write_text("schema_version: 2\n", encoding="utf-8")
        self.out = Path(self.tmp.name) / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def test_topic_map_from_dependency_map(self):
        tm = bfl.load_topic_map()
        self.assertEqual(tm["brent"], "brent-price")
        self.assertEqual(tm["cbr_rate"], "cbr-rate-2026-2027")
        self.assertEqual(tm["urals_discount"], "urals-brent-discount")
        self.assertNotIn("sector_banks", tm)                                 # «—» — темы файлов нет

    def test_backfill_two_latest(self):
        before = {p.name: p.read_bytes() for p in (self.root / "macro-chain").iterdir()}
        with redirect_stdout(io.StringIO()):
            code = bfl.main(["--root", str(self.root), "--out", str(self.out)])
        self.assertEqual(code, 0)
        self.assertEqual({p.name: p.read_bytes() for p in (self.root / "macro-chain").iterdir()}, before)  # рабочая папка цела
        self.assertEqual(sorted(p.name for p in (self.out / "macro-chain").iterdir()),
                         ["macro-scenarios-2026-09-17.yaml", "macro-scenarios-2026-10-04.yaml"])
        text = (self.out / "macro-chain/macro-scenarios-2026-10-04.yaml").read_text(encoding="utf-8")
        self.assertIn("# комментарий сохраняется", text)
        d = yaml.safe_load(text)
        self.assertEqual(d["forecast_files"], {"brent_price": "brent-price-2026-09-17",
                                               "cbr_rate": "cbr-rate-2026-2027-2026-09-17",
                                               "cnyrub_rate": "cnyrub-rate-2026-09-01"})
        self.assertLess(text.index("forecast_files:"), text.index("\nfactors:"))
        src = yaml.safe_load(before["macro-scenarios-2026-10-04.yaml"])
        d.pop("forecast_files")
        self.assertEqual(d, src)                                             # остальное байт-в-данные то же
        rep = (self.out / bfl.REPORT_NAME).read_text(encoding="utf-8")
        self.assertIn("неоднозначно: 2 файла с датой 2026-09-17", rep)     # usdrub — не угадываем
        self.assertIn("у фактора нет source_forecast", rep)                 # xauusd
        self.assertIn("нет «topic у файлов»", rep)                          # nosuch
        self.assertIn("есть новее: brent-price-2026-10-08", rep)
        self.assertIn("macro_input = macro-scenarios-2026-10-04.yaml — входит в бэкфилл", rep)
        self.assertNotIn("stress", " ".join(p.name for p in self.out.rglob("*.yaml")))   # стресс не пишется

    def test_idempotent(self):
        with redirect_stdout(io.StringIO()):
            bfl.main(["--root", str(self.root), "--out", str(self.out)])
        for p in (self.out / "macro-chain").iterdir():
            shutil.copy(p, self.root / "macro-chain" / p.name)
        out2 = Path(self.tmp.name) / "out2"
        with redirect_stdout(io.StringIO()):
            results, _, _ = bfl.run(self.root, out2)
        self.assertEqual([r.status for r in results], ["unchanged", "unchanged"])
        for p in (self.out / "macro-chain").iterdir():
            self.assertEqual((out2 / "macro-chain" / p.name).read_bytes(), p.read_bytes())

    def test_conflict_not_overwritten(self):
        p = self.root / "macro-chain/macro-scenarios-2026-10-04.yaml"
        p.write_text(p.read_text(encoding="utf-8").replace("factors:\n", "forecast_files:\n  brent_price: other-2026-01-01\nfactors:\n", 1),
                     encoding="utf-8")
        results, _, rep = bfl.run(self.root, self.out)
        self.assertEqual(results[0].status, "conflict")
        self.assertFalse((self.out / "macro-chain" / p.name).exists())

    def test_stress_without_macro_input_reported(self):
        (self.root / "Portfolio/stress/stress-2026-10-05-y.yaml").write_text("schema_version: 2\n", encoding="utf-8")
        _, lines, _ = bfl.run(self.root, None)
        self.assertEqual(len(lines), 1)
        self.assertIn("macro_input нет", lines[0])

    def test_out_inside_memory_refused(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(bfl.main(["--root", str(self.root), "--out", "/x/Claude-Memory/y"]), 2)

if __name__ == "__main__":
    unittest.main()
