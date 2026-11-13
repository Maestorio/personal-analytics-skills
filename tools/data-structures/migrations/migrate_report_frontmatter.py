#!/usr/bin/env python3
"""Миграция шапок отчётов Portfolio/reports/*.md под схему report@1 (schema.md §4.3, decision.md R7).

Что делает с каждым файлом:
  * добавляет `mode_codes: [...]` (главный код первым) по таблице соответствия старого `mode`;
    старое поле `mode` НЕ удаляется;
  * правит `kind` по варианту A (минимально): tactical_rebalance с главным кодом 8 -> quality_review,
    пустой kind выводится из режима/имени файла; остальное без изменений;
  * приводит `tickers[]` к ключам (тикер акции/фонда или ISIN облигации): имя компании заменяется по словарю
    `--aliases aliases.json` вида {"Норникель": "GMKN"}, без соответствия остаётся как есть и попадает
    в отчёт как «не распознано»;
  * добавляет `schema_version: "report@1"`;
  * файлу без шапки дописывает шапку (kind, mode_codes, date из имени файла, title из первого H1,
    остальное null/пусто) с пометкой `frontmatter_added_by: migration`.
Поле `recorded_at` ставится ОЦЕНКОЙ всем мигрируемым отчётам вместе с `recorded_at_estimated: true`: если
`created_at` вида `YYYY-MM-DDTHH:MM` — `created_at + ":00+03:00"`, иначе `date + "T00:00:00+03:00"`. Уже стоящий
`recorded_at` не перезаписывается. Новым отчётам (после перехода) `recorded_at` ставит скрипт сохранения
(save-to-library) по часам без флага `recorded_at_estimated`; этот скрипт к новым отчётам отношения не имеет.
`created_at` остаётся оценкой модели. Тело отчёта (после закрывающего `---`) не меняется ни на байт; порядок полей сохраняется,
новые поля идут в конец.

Режимы запуска:
  без --out и --apply : только отчёт о миграции в stdout, файлы не пишутся;
  --out <папка>       : пишет изменённые копии и migration-report.md;
  --apply             : правит файлы на месте, рядом кладёт копию `<имя>.pre-ds.bak` (существующую копию
                        не перезаписывает — файл пропускается).
ВНИМАНИЕ: --apply — только после архивации (archive_pre_ds.py) и «да» владельца.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 migrate_report_frontmatter.py [--reports DIR] [--out DIR]
        [--aliases aliases.json] [--apply]
Зависимости: stdlib и PyYAML.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

SCHEMA_VERSION = "report@1"
DEFAULT_REPORTS = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory/Portfolio/reports"

# Допустимые kind после миграции (кодлист report_kind).
ALLOWED_KINDS = (
    "single_analysis", "tactical_rebalance", "quality_review", "scenario_analysis", "general",
    "iis_buy", "bond_bridge_planner", "candidates_outside_ie", "fund_selection",
)


def _norm(s: str) -> str:
    """Нормализация строки режима: trim и схлопывание пробелов."""
    return re.sub(r"\s+", " ", str(s)).strip()


# Таблица соответствия старого `mode` -> mode_codes (ключи нормализуются при загрузке).
_MODE_TABLE_RAW = {
    "4 (single)": ["4a"],
    "4 (single) x3": ["4a"],
    "free_form": ["free"],
    "3 (rebalance_opinion)": ["3"],
    "8 (stock_quality_forward_review)": ["8"],
    "5a (fund analysis)": ["5a"],
    "3 (rebalance) + 4 (single)": ["3", "4a"],
    "3 (rebalance opinion) + free_form": ["3", "free"],
    "5a (fund analysis) + 3 (rebalance opinion, сайзинг по классу)": ["5a", "3"],
    "3/4 (rebalance + single analysis)": ["4a", "3"],
    "3/4 (rebalance_opinion + single_analysis)": ["3", "4a"],
    "3 (rebalance) + 4 (single) + 8 overlay": ["3", "4a", "8"],
    "3 (rebalance) + free_form": ["3", "free"],
    "2 (bonds) + 3 (rebalance) + free_form": ["3", "2", "free"],
    "8 (stock_quality_forward_review) + weight opinion (элемент Mode 3, независимо от IE)": ["8", "3"],
    "2 (bonds review) + 3 (rebalance) + 4 (single)": ["3", "2", "4b"],
    "2 (bonds review) + 3 (rebalance opinion) + free_form": ["3", "2", "free"],
    "3 (rebalance) + 5a (fund) + 9 (conditions)": ["3", "5a", "9"],
    "3 (rebalance opinion) + 6 (returns analysis) + free_form": ["3", "6", "free"],
    "3 (rebalance) + single-instrument selection": ["3", "4b"],
    "3 (rebalance opinion) + 9 (conditions management)": ["3", "9"],
    "3 (rebalance opinion)": ["3"],
    "4 (single analysis, мульти-кандидат) + 3 (rebalance opinion)": ["4b", "3"],
    "4 (single) + 9 (conditions)": ["4a", "9"],
    "8 (stock quality forward review) + 3 (rebalance opinion)": ["8", "3"],
    "3 (rebalance)": ["3"],
    "5 (fund)": ["5a", "5b"],   # решение владельца 30.10: денежные фонды 28.10 — разбор с элементами подбора
    "7 (iis3 buy)": ["7"],
}
MODE_TABLE = {_norm(k): v for k, v in _MODE_TABLE_RAW.items()}
# Режимы, где [4a] заменяется на [4b], если в tickers только ISIN (облигации).
SINGLE_MODES = {_norm("4 (single)"), _norm("4 (single) x3")}

# Файлы без `mode`: шаблон имени -> (mode_codes, kind).
FILENAME_RULES = [
    ("*advisory-portfolio-iis3*", ["7", "3"], "iis_buy"),   # внутри «Mode 3 + Mode 7»
    ("*ie-posts-review*", ["free"], "general"),
    ("*macro-report*", ["free"], "general"),
    ("bond-bridge-planner-*", ["3", "6"], "bond_bridge_planner"),   # внутри «Mode 3 + 6»
    ("portfolio-candidates-outside-ie-*", ["4b"], "candidates_outside_ie"),
]

# Резервный вывод kind, если он пуст, а режим известен по таблице.
KIND_BY_MAIN_CODE = {
    "4a": "single_analysis", "4b": "single_analysis", "3": "tactical_rebalance", "8": "quality_review",
    "7": "iis_buy", "5a": "fund_selection", "5b": "fund_selection", "2": "tactical_rebalance",
    "6": "general", "9": "tactical_rebalance", "free": "general",
}

FRONT_RE = re.compile(r"\A---\n(.*?)\n---[ \t]*(?:\n|\Z)", re.S)
ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
KEY_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,11}$")
CREATED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATE_IN_NAME_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
H1_RE = re.compile(r"^#[ \t]+(.+?)[ \t]*$", re.M)


class FlowList(list):
    """Список скаляров, который выводится в одну строку: ["a", "b"]."""


class QStr(str):
    """Строка, которая выводится в двойных кавычках."""


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(
    FlowList, lambda d, v: d.represent_sequence("tag:yaml.org,2002:seq", list(v), flow_style=True))
_Dumper.add_representer(QStr, lambda d, v: d.represent_scalar("tag:yaml.org,2002:str", str(v), style='"'))

_DATEISH_RE = re.compile(r"^\d{4}-\d{2}-\d{2}|^\d+$")


def _repr_str(dumper, value):
    """Многострочные строки — блоком `|`; похожие на дату/число — в кавычках (чтобы читатель не угадал тип)."""
    if "\n" in value:
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|")
    if _DATEISH_RE.match(value):
        return dumper.represent_scalar("tag:yaml.org,2002:str", value, style='"')
    return dumper.represent_scalar("tag:yaml.org,2002:str", value)


_Dumper.add_representer(str, _repr_str)


def dump_frontmatter(data: dict) -> str:
    """Собирает шапку: порядок полей сохраняется, tickers/mode_codes — в одну строку в двойных кавычках."""
    prepared = {}
    for k, v in data.items():
        if k in ("tickers", "mode_codes") and isinstance(v, list) and all(isinstance(x, str) for x in v):
            v = FlowList(QStr(x) for x in v)
        prepared[k] = v
    return yaml.dump(prepared, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=1000,
                     default_flow_style=False)


class Result:
    """Итог по одному файлу."""

    def __init__(self, name: str):
        self.name = name
        self.status = "ok"          # ok | already | no_mapping | error
        self.has_frontmatter = False
        self.header_added = False
        self.mode = None
        self.codes: list[str] = []
        self.kind_old = None
        self.kind_new = None
        self.tickers_old = None
        self.tickers_new = None
        self.unrecognized: list[str] = []
        self.warnings: list[str] = []
        self.recorded_source = None  # 'created_at' | 'date' | None
        self.new_text: str | None = None  # None -> файл не меняется

    @property
    def kind_changed(self) -> bool:
        return self.kind_old != self.kind_new and self.status == "ok"


def map_tickers(tickers, aliases: dict) -> tuple[list, list[str]]:
    """Приводит tickers к ключам. Возвращает (новый список, нераспознанные строки)."""
    out: list = []
    bad: list[str] = []
    folded = {k.casefold(): v for k, v in aliases.items()}
    for item in tickers:
        if not isinstance(item, str):
            out.append(item)
            bad.append(repr(item))
            continue
        s = item.strip()
        if s in aliases:
            new = aliases[s]
        elif s.casefold() in folded:
            new = folded[s.casefold()]
        elif KEY_RE.match(s):
            new = s
        else:
            new = item
            bad.append(item)
        if new not in out:
            out.append(new)
    return out, bad


def estimate_recorded_at(created_at, date) -> tuple[str | None, str | None]:
    """Оценка времени записи: (значение, источник 'created_at'|'date'|None)."""
    if hasattr(created_at, "isoformat") and not isinstance(created_at, str):
        # неквотированное время YAML разобрал как datetime без пояса
        iso = created_at.isoformat(timespec="minutes")
        created_at = iso if len(iso) == 16 else None
    if isinstance(created_at, str) and CREATED_AT_RE.match(created_at.strip()):
        return created_at.strip() + ":00+03:00", "created_at"
    d = date.isoformat() if hasattr(date, "isoformat") else date
    if isinstance(d, str) and DATE_RE.match(d.strip()):
        return d.strip() + "T00:00:00+03:00", "date"
    return None, None


def _kind_variant_a(kind, codes: list[str]):
    """Вариант A: tactical_rebalance с главным кодом 8 -> quality_review; пустой — выводится из режима."""
    if kind is None or kind == "":
        return KIND_BY_MAIN_CODE.get(codes[0]) if codes else None
    if kind == "tactical_rebalance" and codes and codes[0] == "8":
        return "quality_review"
    return kind


def _resolve_codes(mode, name: str, tickers: list | None) -> tuple[list[str] | None, str | None]:
    """Определяет mode_codes и (для файлов без mode) kind по имени файла."""
    if mode is not None:
        if not isinstance(mode, str):
            return None, None
        key = _norm(mode)
        codes = MODE_TABLE.get(key)
        if codes is None:
            return None, None
        codes = list(codes)
        if key in SINGLE_MODES and tickers and all(isinstance(t, str) and ISIN_RE.match(t) for t in tickers):
            codes = ["4b"]
        return codes, None
    for pattern, codes, kind in FILENAME_RULES:
        if fnmatch.fnmatch(name, pattern):
            return list(codes), kind
    return None, None


def migrate_text(name: str, text: str, aliases: dict | None = None) -> Result:
    """Мигрирует содержимое одного отчёта. Тело не меняется."""
    aliases = aliases or {}
    r = Result(name)
    m = FRONT_RE.match(text)
    if not m:
        return _migrate_without_frontmatter(r, name, text)
    r.has_frontmatter = True
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        r.status = "error"
        r.warnings.append(f"ошибка YAML шапки: {str(e).splitlines()[0]}")
        return r
    if not isinstance(fm, dict):
        r.status = "error"
        r.warnings.append("шапка не является mapping")
        return r
    body = text[m.end():]
    r.mode = fm.get("mode")
    r.kind_old = fm.get("kind")
    r.tickers_old = fm.get("tickers")
    if "mode_codes" in fm and fm.get("schema_version") == SCHEMA_VERSION:
        r.status = "already"
        r.codes = list(fm["mode_codes"] or [])
        r.kind_new = r.kind_old
        r.tickers_new = r.tickers_old
        return r

    # tickers
    tickers_new = r.tickers_old
    if isinstance(r.tickers_old, list):
        tickers_new, r.unrecognized = map_tickers(r.tickers_old, aliases)
        for u in r.unrecognized:
            r.warnings.append(f"тикер не распознан: {u}")
    elif r.tickers_old is not None:
        r.warnings.append("tickers не список")
    r.tickers_new = tickers_new

    codes, kind_by_name = _resolve_codes(r.mode, name, tickers_new if isinstance(tickers_new, list) else None)
    if codes is None:
        r.status = "no_mapping"
        r.warnings.append("нет соответствия режима" + (f": {_norm(r.mode)!r}" if isinstance(r.mode, str)
                                                         else " (mode отсутствует и имя файла не из правил)"))
        r.kind_new = r.kind_old
        return r
    r.codes = codes

    kind_new = _kind_variant_a(r.kind_old if r.kind_old else kind_by_name, codes)
    if not r.kind_old and not kind_by_name and kind_new:
        r.warnings.append("kind выведен из режима/имени файла")
    r.kind_new = kind_new
    if kind_new not in ALLOWED_KINDS:
        r.warnings.append(f"kind вне перечня допустимых: {kind_new!r}")

    new = dict(fm)
    new["kind"] = kind_new  # существующий ключ сохраняет позицию, новый встаёт в конец
    if isinstance(tickers_new, list) and "tickers" in new:
        new["tickers"] = tickers_new
    if "date" not in new and "review_date" in new:
        new["date"] = new["review_date"]
        r.warnings.append("date добавлена из review_date")
    elif "date" not in new:
        dm = DATE_IN_NAME_RE.search(name)
        if dm:
            new["date"] = dm.group(1)
            r.warnings.append("date добавлена из имени файла")
    new["mode_codes"] = codes
    new["schema_version"] = SCHEMA_VERSION
    if "recorded_at" not in new:
        rec, src = estimate_recorded_at(new.get("created_at"), new.get("date"))
        if rec:
            new["recorded_at"] = rec
            new["recorded_at_estimated"] = True
            r.recorded_source = src
        else:
            r.warnings.append("recorded_at не оценён: нет created_at и date")
    r.new_text = "---\n" + dump_frontmatter(new) + "---\n" + body
    if r.new_text == text:
        r.new_text = None
    return r


def _migrate_without_frontmatter(r: Result, name: str, text: str) -> Result:
    codes, kind = _resolve_codes(None, name, None)
    if codes is None:
        r.status = "no_mapping"
        r.warnings.append("нет шапки и имя файла не из правил: нет соответствия")
        return r
    r.codes = codes
    r.kind_new = kind
    r.header_added = True
    dm = DATE_IN_NAME_RE.search(name)
    h1 = H1_RE.search(text)
    if not dm:
        r.warnings.append("дата в имени файла не найдена")
    if not h1:
        r.warnings.append("H1 не найден, title = null")
    rec, src = estimate_recorded_at(None, dm.group(1) if dm else None)
    r.recorded_source = src
    fm = {
        "title": h1.group(1) if h1 else None,
        "date": dm.group(1) if dm else None,
        "created_at": None,
        "recorded_at": rec,
        "recorded_at_estimated": True,
        "model": None,
        "author": None,
        "kind": kind,
        "summary": None,
        "tickers": [],
        "mode_codes": codes,
        "schema_version": SCHEMA_VERSION,
        "frontmatter_added_by": "migration",
    }
    r.new_text = "---\n" + dump_frontmatter(fm) + "---\n\n" + text
    return r


def load_aliases(path: str | None) -> dict:
    if not path:
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit("aliases.json должен быть объектом {имя: ключ}")
    return {str(k): str(v) for k, v in data.items()}


def run_reports(reports_dir: Path, aliases: dict) -> list[Result]:
    results = []
    for p in sorted(reports_dir.glob("*.md")):
        if p.name.startswith("."):
            continue
        with open(p, encoding="utf-8", newline="") as f:
            text = f.read()
        results.append(migrate_text(p.name, text, aliases))
    return results


def _cell(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def build_report(results: list[Result]) -> str:
    """Markdown-отчёт: сводка счётчиков и таблица по файлам."""
    n = len(results)
    ok = [r for r in results if r.status in ("ok", "already")]
    nomap = [r for r in results if r.status == "no_mapping"]
    errs = [r for r in results if r.status == "error"]
    unrec_files = [r for r in results if r.unrecognized]
    unrec_set = sorted({u for r in results for u in r.unrecognized})
    kind_ch = [r for r in results if r.kind_changed]
    tick_ch = [r for r in results if r.status == "ok" and r.tickers_old != r.tickers_new]
    lines = ["# Отчёт миграции шапок отчётов (report@1)", "", "## Сводка", "",
             f"- Файлов `.md`: {n}",
             f"- С шапкой: {sum(r.has_frontmatter for r in results)}; без шапки: "
             f"{sum(not r.has_frontmatter for r in results)} (шапка дописывается: "
             f"{sum(r.header_added for r in results)})",
             f"- С соответствием режима: {len(ok)} (из них уже мигрированы: "
             f"{sum(r.status == 'already' for r in results)})",
             f"- Нет соответствия (файл не трогается): {len(nomap)}",
             f"- Ошибки разбора шапки: {len(errs)}",
             f"- `kind` меняется: {len(kind_ch)}",
             f"- `tickers` меняются: {len(tick_ch)}",
             f"- Файлов с нераспознанными тикерами: {len(unrec_files)}; уникальных строк: {len(unrec_set)}",
             f"- `recorded_at` оценён: по created_at {sum(r.recorded_source == 'created_at' for r in results)}, "
             f"по date {sum(r.recorded_source == 'date' for r in results)}",
             f"- Будут изменены: {sum(r.new_text is not None for r in results)}", ""]
    if unrec_set:
        lines += ["## Нераспознанные тикеры", ""] + [f"- `{u}`" for u in unrec_set] + [""]
    if nomap:
        lines += ["## Нет соответствия", ""] + [f"- `{r.name}`: {_cell(r.mode)}" for r in nomap] + [""]
    lines += ["## По файлам", "",
              "| Файл | kind | mode → mode_codes | tickers | Предупреждения |", "|---|---|---|---|---|"]
    for r in results:
        kind = (f"{r.kind_old} → {r.kind_new}" if r.kind_old != r.kind_new else f"{r.kind_new} (без изм.)")
        mode = f"{_cell(r.mode) if r.mode is not None else '—'} → {r.codes if r.codes else '—'}"
        if r.header_added:
            mode = "(нет шапки) → " + str(r.codes)
        if isinstance(r.tickers_old, list) and r.tickers_old == r.tickers_new:
            tk = f"без изм. ({len(r.tickers_old)})"
        elif r.tickers_old is None and not r.tickers_new:
            tk = "—"
        else:
            tk = f"{_cell(r.tickers_old)} → {_cell(r.tickers_new)}"
        lines.append(f"| {r.name} | {_cell(kind)} | {_cell(mode)} | {tk} | {_cell('; '.join(r.warnings)) or '—'} |")
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


def apply_in_place(reports_dir: Path, results: list[Result]) -> tuple[int, list[str]]:
    """Правит файлы на месте; перед правкой кладёт копию `.pre-ds.bak`. Возвращает (число правок, пропуски)."""
    done, skipped = 0, []
    for r in results:
        if r.new_text is None:
            continue
        path = reports_dir / r.name
        bak = path.with_name(path.name + ".pre-ds.bak")
        if bak.exists():
            skipped.append(f"{r.name}: копия {bak.name} уже есть — пропущен")
            continue
        shutil.copy2(path, bak)
        _atomic_write(path, r.new_text)
        done += 1
    return done, skipped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Миграция шапок отчётов под report@1")
    ap.add_argument("--reports", default=str(DEFAULT_REPORTS), help="папка Portfolio/reports")
    ap.add_argument("--out", help="папка для изменённых копий и migration-report.md")
    ap.add_argument("--aliases", help="JSON {\"Имя компании\": \"TICKER\"}")
    ap.add_argument("--apply", action="store_true",
                    help="правка на месте с копией .pre-ds.bak (только после архивации и «да» владельца)")
    args = ap.parse_args(argv)

    reports_dir = Path(args.reports)
    if not reports_dir.is_dir():
        print(f"Папка отчётов не найдена: {reports_dir}", file=sys.stderr)
        return 2
    results = run_reports(reports_dir, load_aliases(args.aliases))
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
        done, skipped = apply_in_place(reports_dir, results)
        print(f"Применено на месте: {done}")
        for s in skipped:
            print("ПРОПУСК:", s, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
