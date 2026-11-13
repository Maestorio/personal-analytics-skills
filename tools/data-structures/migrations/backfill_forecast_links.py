#!/usr/bin/env python3
"""Бэкфилл ссылок макросценариев на прогнозы: `forecast_files{фактор: имя файла прогноза}` (schema.md §4.6, шаг 14).

Берутся два последних `macro-chain/macro-scenarios-<дата>.yaml` (по дате в имени). Соответствие фактор -> файл:
  1. у фактора есть `source_files` — одна реализация `check_source_files.forecast_files_from_sources`;
  2. иначе `source_forecast` (слаг фактора, например `brent`) -> «topic у файлов» из таблицы
     `skills/macro-forecast-chain/references/dependency-map.md` -> среди `forecasts/*.yaml` с этим `forecast.topic`
     и датой прогноза не позже даты сборки (`assembled_date`) — самый поздний. Два файла с одной датой, нет темы,
     нет `source_forecast` или нет файла — строка отчёта, ссылка не ставится (не угадываем).
Стресс не меняется: ссылка стресса — существующее поле `macro_input` (R22); последний стресс только проверяется
(есть ли `macro_input`, ведёт ли на один из файлов бэкфилла) — результат в отчёт.

YAML не пересобирается: блок `forecast_files:` вставляется текстом перед верхнеуровневой строкой `factors:`;
после вставки `yaml.safe_load(результат)` сверяется с исходными данными плюс поле, иначе файл не пишется.
Идемпотентно: уже стоящий такой же `forecast_files` — «без изменений»; другой — конфликт в отчёт, файл не трогается.

Режимы: без `--out` — отчёт в stdout; `--out <папка>` — изменённые копии `<out>/macro-chain/<имя>` и
`<out>/backfill-forecast-links-report.md`. `--apply` нет: применение — при переключении (§4.2), копированием из `--out`.
Рабочая папка Claude-Memory только читается; `--out` внутри Claude-Memory запрещён.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 backfill_forecast_links.py [--root <Claude-Memory>] [--out DIR] [--last N]
Зависимости: stdlib и PyYAML.
"""
from __future__ import annotations

import argparse
import copy
import os
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "skills" / "macro-forecast-chain" / "scripts"))
import check_source_files as csf  # noqa: E402

DEFAULT_ROOT = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory"
DEPMAP = REPO / "skills" / "macro-forecast-chain" / "references" / "dependency-map.md"
MS_RE = re.compile(r"^macro-scenarios-(\d{4}-\d{2}-\d{2})\.ya?ml$")
STRESS_RE = re.compile(r"^stress-(\d{4}-\d{2}-\d{2}).*\.ya?ml$")
STEM_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})(?:-v\d+)?$")
FACTORS_LINE_RE = re.compile(r"^factors:[^\n]*(\r?\n)", re.M)
REPORT_NAME = "backfill-forecast-links-report.md"


def load_topic_map(path: Path = DEPMAP) -> dict[str, str]:
    """Таблица «Фактор | topic slug | topic у файлов» -> {фактор (слаг source_forecast): topic у файлов}."""
    out: dict[str, str] = {}
    text = path.read_text(encoding="utf-8")
    in_table = False
    for line in text.splitlines():
        if line.startswith("| Фактор | topic slug | topic у файлов"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                break
            cells = [c.strip().strip("`") for c in line.strip("|").split("|")]
            if len(cells) < 3 or set(cells[0]) <= {"-"}:
                continue
            if cells[2] and cells[2] != "—":
                out[cells[0]] = cells[2]
    return out


def _date_str(v) -> str | None:
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", str(v))
    return m.group(1) if m else None


def index_forecasts(forecasts_dir: Path) -> list[dict]:
    """[{stem, topic, date, status, superseded_by}] по forecasts/*.yaml (нечитаемые пропускаются)."""
    out = []
    for p in sorted(forecasts_dir.glob("*.yaml")):
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(d, dict):
            continue
        fc = d.get("forecast") if isinstance(d.get("forecast"), dict) else {}
        topic = fc.get("topic") or d.get("topic")
        m = STEM_DATE_RE.search(p.stem)
        out.append({"stem": p.stem, "topic": topic, "date": _date_str(fc.get("date")) or (m.group(1) if m else None),
                    "status": d.get("status"), "superseded_by": d.get("superseded_by")})
    return out


def resolve_factor(name: str, body: dict, assembled: str | None, topic_map: dict, forecasts: list[dict]):
    """(имя файла | None, причина | None, кандидаты) по source_forecast и датам прогнозов."""
    slug = body.get("source_forecast") if isinstance(body, dict) else None
    if not slug:
        return None, "у фактора нет source_forecast", []
    topic = topic_map.get(slug)
    if not topic:
        return None, f"для слага {slug!r} нет «topic у файлов» в dependency-map.md", []
    if not assembled:
        return None, "у файла нет assembled_date", []
    cands = [f for f in forecasts if f["topic"] == topic and f["date"] and f["date"] <= assembled]
    if not cands:
        return None, f"нет прогноза с topic {topic!r} не позже {assembled}", []
    best = max(f["date"] for f in cands)
    top = sorted(f["stem"] for f in cands if f["date"] == best)
    if len(top) > 1:
        return None, f"неоднозначно: {len(top)} файла с датой {best}", top
    return top[0], None, top


def build_links(doc: dict, topic_map: dict, forecasts: list[dict]):
    """({фактор: файл}, строки отчёта [(фактор, файл|None, способ, причина|None, заметка)])."""
    factors = doc.get("factors") if isinstance(doc.get("factors"), dict) else {}
    from_src, src_problems = csf.forecast_files_from_sources(doc)
    assembled = _date_str(doc.get("assembled_date"))
    by_stem = {f["stem"]: f for f in forecasts}
    mapping: dict[str, str] = {}
    rows = []
    for name, body in factors.items():
        if name in from_src:
            stem, how, why = from_src[name], "source_files", None
        elif isinstance(body, dict) and isinstance(body.get("source_files"), list):
            stem, how = None, "source_files"
            why = next((p for p in src_problems if p.startswith(f"factors.{name}:")), "нет файла forecasts/ в source_files")
        else:
            stem, why, _ = resolve_factor(name, body, assembled, topic_map, forecasts)
            how = "source_forecast + дата"
        note = ""
        if stem:
            mapping[name] = stem
            rec = by_stem.get(stem)
            if rec is None:
                note = "файла прогноза нет в forecasts/"
            elif rec.get("superseded_by"):
                note = f"есть новее: {rec['superseded_by']}"
        rows.append((name, stem, how, why, note))
    return mapping, rows


def insert_block(text: str, mapping: dict) -> str | None:
    """Текст с блоком forecast_files перед строкой `factors:`; None — строки нет."""
    m = FACTORS_LINE_RE.search(text)
    if not m:
        return None
    nl = m.group(1)
    block = csf.render_block(mapping).replace("\n", nl)
    return text[:m.start()] + block + text[m.start():]


class FileResult:
    def __init__(self, name):
        self.name = name
        self.status = None      # added | unchanged | conflict | error
        self.detail = ""
        self.rows = []
        self.mapping = {}
        self.new_text = None


def process_file(path: Path, topic_map: dict, forecasts: list[dict]) -> FileResult:
    r = FileResult(path.name)
    text = path.read_text(encoding="utf-8")
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as e:
        r.status, r.detail = "error", f"YAML не читается: {e.__class__.__name__}"
        return r
    if not isinstance(doc, dict):
        r.status, r.detail = "error", "не объект"
        return r
    r.mapping, r.rows = build_links(doc, topic_map, forecasts)
    have = doc.get("forecast_files")
    if have is not None:
        if have == r.mapping:
            r.status, r.new_text, r.detail = "unchanged", text, "forecast_files уже стоит такой же"
        else:
            r.status, r.detail = "conflict", "forecast_files уже стоит и отличается — не трогаем"
        return r
    new = insert_block(text, r.mapping)
    if new is None:
        r.status, r.detail = "error", "нет верхнеуровневой строки factors:"
        return r
    expect = copy.deepcopy(doc)
    expect["forecast_files"] = dict(r.mapping)
    if yaml.safe_load(new) != expect:
        r.status, r.detail = "error", "после вставки данные не совпали с ожидаемыми — файл не пишется"
        return r
    errs, _ = csf.check_forecast_files(yaml.safe_load(new))
    if errs:
        r.status, r.detail = "error", "; ".join(errs)
        return r
    r.status, r.new_text = "added", new
    return r


def latest_files(folder: Path, rx: re.Pattern, n: int) -> list[Path]:
    items = [(rx.match(p.name).group(1), p.name, p) for p in folder.iterdir() if rx.match(p.name)] if folder.is_dir() else []
    return [p for _, _, p in sorted(items)[-n:]][::-1]


def check_stress(root: Path, ms_names: list[str]) -> list[str]:
    st = latest_files(root / "Portfolio" / "stress", STRESS_RE, 1)
    if not st:
        return ["стресса нет — проверять нечего"]
    p = st[0]
    try:
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return [f"{p.name}: YAML не читается"]
    mi = d.get("macro_input") if isinstance(d, dict) else None
    if not mi:
        return [f"{p.name}: macro_input нет — ссылка не записана (стресс не меняется, решает владелец)"]
    base = os.path.basename(str(mi))
    tail = "входит в бэкфилл" if base in ms_names else "НЕ входит в бэкфилл (цепочка до прогнозов не замкнётся)"
    extra = "; поле macro_scenarios_file есть — дубль (R22)" if "macro_scenarios_file" in d else ""
    return [f"{p.name}: macro_input = {base} — {tail}{extra}"]


def render_report(results: list[FileResult], stress_lines: list[str]) -> str:
    L = ["# Бэкфилл ссылок макросценариев на прогнозы (forecast_files, шаг 14)\n"]
    tot = sum(len(r.rows) for r in results)
    linked = sum(1 for r in results for x in r.rows if x[1])
    L.append(f"Файлов: **{len(results)}**. Факторов: **{tot}**, со ссылкой: **{linked}**, без ссылки: **{tot - linked}**.\n")
    for r in results:
        L.append(f"## {r.name} — {r.status}\n")
        if r.detail:
            L.append(f"{r.detail}\n")
        if r.rows:
            L.append("| фактор | файл прогноза | способ | причина, если нет | заметка |")
            L.append("|---|---|---|---|---|")
            for name, stem, how, why, note in r.rows:
                L.append(f"| {name} | {stem or '-'} | {how} | {why or '-'} | {note or '-'} |")
            L.append("")
    L.append("## Стресс (не меняется, R22)\n")
    L.extend(f"- {s}" for s in stress_lines)
    return "\n".join(L) + "\n"


def run(root: Path, out: Path | None, last: int = 2, depmap: Path = DEPMAP):
    topic_map = load_topic_map(depmap)
    forecasts = index_forecasts(root / "forecasts")
    files = latest_files(root / "macro-chain", MS_RE, last)
    results = [process_file(p, topic_map, forecasts) for p in files]
    stress_lines = check_stress(root, [p.name for p in files])
    report = render_report(results, stress_lines)
    if out is not None:
        (out / "macro-chain").mkdir(parents=True, exist_ok=True)
        for r in results:
            if r.new_text is not None:
                (out / "macro-chain" / r.name).write_text(r.new_text, encoding="utf-8")
        (out / REPORT_NAME).write_text(report, encoding="utf-8")
    return results, stress_lines, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Бэкфилл forecast_files в макросценариях (шаг 14)")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="корень Claude-Memory (только чтение)")
    ap.add_argument("--out", help="папка для изменённых копий и отчёта; без неё — отчёт в stdout")
    ap.add_argument("--last", type=int, default=2, help="сколько последних макросценариев (по умолчанию 2)")
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else None
    if out is not None and "Claude-Memory" in str(out.resolve()):
        print("--out внутри Claude-Memory запрещён: применение — при переключении (§4.2)", file=sys.stderr)
        return 2
    results, _, report = run(Path(a.root), out, a.last)
    if out is None:
        print(report)
    tot = sum(len(r.rows) for r in results)
    linked = sum(1 for r in results for x in r.rows if x[1])
    st = ", ".join(f"{r.name}: {r.status}" for r in results) or "нет файлов"
    print(f"ИТОГ: файлов {len(results)} ({st}); факторов {tot}, со ссылкой {linked}, без ссылки {tot - linked}")
    return 1 if any(r.status == "error" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
