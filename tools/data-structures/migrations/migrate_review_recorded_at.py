#!/usr/bin/env python3
"""Миграция обзоров недели: верхнеуровневые `recorded_at` и `recorded_at_estimated` (schema.md §4.2).

Для каждого `Portfolio/weekly-reviews/weekly-review-*.yaml` (файлы `.yaml.bak`, `.md` не берутся) ставится
оценка: `recorded_at = review_date + "T00:00:00+03:00"`, `recorded_at_estimated: true`. Новым обзорам
(после перехода) `recorded_at` ставит скрипт сборки по часам, без флага оценки.

YAML НЕ пересобирается: в файлах есть комментарии и якорные пояснения (часть строк с `# …`), поэтому две
строки вставляются текстом сразу после верхнеуровневой строки `review_date:` (с тем же переводом строки, что в
файле). После вставки проверяется, что `yaml.safe_load(результат)` равен исходным данным плюс два поля; иначе
файл помечается ошибкой и не пишется. Уже стоящий `recorded_at` не трогается.

Обзоры с `revision` / `amendments` / `amended_at` выводятся отдельной таблицей отчёта «файл · review_date ·
revision · даты в amendments»: время перезаписанного обзора решает владелец, скрипт пока ставит `review_date`.

Режимы: без флагов — только отчёт в stdout; `--out <папка>` — изменённые копии и migration-report.md;
`--apply` — правка на месте с копией `<имя>.pre-ds.bak` (существующую копию не перезаписывает).
ВНИМАНИЕ: --apply — только после архивации (archive_pre_ds.py) и «да» владельца.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 migrate_review_recorded_at.py [--reviews DIR] [--out DIR] [--apply]
Зависимости: stdlib и PyYAML.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

DEFAULT_REVIEWS = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory/Portfolio/weekly-reviews"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REVIEW_DATE_LINE_RE = re.compile(r"^review_date:[^\n]*?(\r?\n)", re.M)


class Result:
    def __init__(self, name: str):
        self.name = name
        self.status = "ok"  # ok | already | error
        self.review_date = None
        self.revision = None
        self.amend_dates: list[str] = []
        self.has_amend_keys = False
        self.warnings: list[str] = []
        self.new_text: str | None = None


def _d(v) -> str | None:
    v = v.isoformat() if hasattr(v, "isoformat") else v
    return v.strip() if isinstance(v, str) else None


def _revision_str(rev) -> str:
    if isinstance(rev, dict):
        return f"№{rev.get('number', '?')} от {_d(rev.get('date')) or '?'}"
    return str(rev)


def _amend_dates(data: dict) -> list[str]:
    out: list[str] = []
    am = data.get("amendments")
    if isinstance(am, list):
        for a in am:
            if isinstance(a, dict) and a.get("date") is not None:
                out.append(_d(a["date"]) or str(a["date"]))
    if data.get("amended_at") is not None:
        out.append("amended_at " + (str(data["amended_at"])))
    return out


def migrate_text(name: str, text: str) -> Result:
    """Ставит recorded_at текстовой вставкой после строки review_date; проверяет данные до/после."""
    r = Result(name)
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        r.status = "error"
        r.warnings.append(f"ошибка YAML: {str(e).splitlines()[0]}")
        return r
    if not isinstance(data, dict):
        r.status = "error"
        r.warnings.append("корень не mapping")
        return r
    r.review_date = _d(data.get("review_date"))
    r.revision = data.get("revision")
    r.amend_dates = _amend_dates(data)
    r.has_amend_keys = any(k in data for k in ("revision", "amendments", "amended_at"))
    if "recorded_at" in data:
        r.status = "already"
        return r
    if not r.review_date or not DATE_RE.match(r.review_date):
        r.status = "error"
        r.warnings.append(f"review_date не вида YYYY-MM-DD: {data.get('review_date')!r}")
        return r
    m = REVIEW_DATE_LINE_RE.search(text)
    if not m:
        r.status = "error"
        r.warnings.append("верхнеуровневая строка review_date: не найдена")
        return r
    nl = m.group(1)
    ins = f'recorded_at: "{r.review_date}T00:00:00+03:00"{nl}recorded_at_estimated: true{nl}'
    new_text = text[:m.end()] + ins + text[m.end():]
    expected = dict(data)
    expected["recorded_at"] = f"{r.review_date}T00:00:00+03:00"
    expected["recorded_at_estimated"] = True
    try:
        got = yaml.safe_load(new_text)
    except yaml.YAMLError as e:
        r.status = "error"
        r.warnings.append(f"после вставки YAML не читается: {str(e).splitlines()[0]}")
        return r
    if got != expected:
        r.status = "error"
        r.warnings.append("проверка не сошлась: данные после вставки != исходные + 2 поля")
        return r
    r.new_text = new_text
    return r


def run_reviews(reviews_dir: Path) -> list[Result]:
    results = []
    for p in sorted(reviews_dir.glob("weekly-review-*.yaml")):
        with open(p, encoding="utf-8", newline="") as f:
            text = f.read()
        results.append(migrate_text(p.name, text))
    return results


def _cell(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def build_report(results: list[Result]) -> str:
    n = len(results)
    amended = [r for r in results if r.has_amend_keys]
    lines = ["# Отчёт миграции обзоров недели (recorded_at)", "", "## Сводка", "",
             f"- Файлов `weekly-review-*.yaml`: {n}",
             f"- Будет проставлено `recorded_at` (оценка по review_date): {sum(r.new_text is not None for r in results)}",
             f"- Уже стоит `recorded_at`: {sum(r.status == 'already' for r in results)}",
             f"- Ошибки (файл не трогается): {sum(r.status == 'error' for r in results)}",
             f"- С `revision` / `amendments` / `amended_at` (время решает владелец): {len(amended)}", ""]
    errs = [r for r in results if r.status == "error"]
    if errs:
        lines += ["## Ошибки", ""] + [f"- `{r.name}`: {_cell('; '.join(r.warnings))}" for r in errs] + [""]
    lines += ["## Перезаписанные обзоры (recorded_at пока = review_date)", "",
              "| Файл | review_date | revision | Даты в amendments |", "|---|---|---|---|"]
    for r in amended:
        rev = _revision_str(r.revision) if r.revision is not None else "—"
        am = ", ".join(r.amend_dates) if r.amend_dates else "— (пусто)"
        lines.append(f"| {r.name} | {r.review_date} | {_cell(rev)} | {_cell(am)} |")
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        if path.exists():
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def apply_in_place(reviews_dir: Path, results: list[Result]) -> tuple[int, list[str]]:
    done, skipped = 0, []
    for r in results:
        if r.new_text is None:
            continue
        path = reviews_dir / r.name
        bak = path.with_name(path.name + ".pre-ds.bak")
        if bak.exists():
            skipped.append(f"{r.name}: копия {bak.name} уже есть — пропущен")
            continue
        shutil.copy2(path, bak)
        _atomic_write(path, r.new_text)
        done += 1
    return done, skipped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="recorded_at для обзоров недели")
    ap.add_argument("--reviews", default=str(DEFAULT_REVIEWS), help="папка Portfolio/weekly-reviews")
    ap.add_argument("--out", help="папка для изменённых копий и migration-report.md")
    ap.add_argument("--apply", action="store_true",
                    help="правка на месте с копией .pre-ds.bak (только после архивации и «да» владельца)")
    args = ap.parse_args(argv)
    reviews_dir = Path(args.reviews)
    if not reviews_dir.is_dir():
        print(f"Папка обзоров не найдена: {reviews_dir}", file=sys.stderr)
        return 2
    results = run_reviews(reviews_dir)
    report = build_report(results)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        for r in results:
            if r.new_text is not None:
                _atomic_write(out / r.name, r.new_text)
        (out / "migration-report.md").write_text(report, encoding="utf-8")
        print(f"Записано в {out}: {sum(r.new_text is not None for r in results)} файлов + migration-report.md")
    else:
        print(report)
    if args.apply:
        done, skipped = apply_in_place(reviews_dir, results)
        print(f"Применено на месте: {done}")
        for s in skipped:
            print("ПРОПУСК:", s, file=sys.stderr)
    return 1 if any(r.status == "error" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
