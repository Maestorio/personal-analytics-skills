#!/usr/bin/env python3
"""Миграция словаря вердиктов в обзорах облигаций `Portfolio/weekly-reviews/weekly-review-bond-*.yaml`
(schema.md §3.4, шаг 8 цикла машиночитаемости): legacy-коды → целевые по карте `migrate_to` кодлиста `verdict`
(`HOLD_ADD` → `ADD`, `RED_FLAG` → `WATCH`, `MATURE` → `HOLD_TO_MAT`, `HOLD_NO_OFFER` → `HOLD_TO_MAT`).

Что меняется (только значения полей-вердиктов, найденные по валидатору обзора и данным):
  * значения полей VERDICT_FIELDS (`advisor_verdict`, `prior_verdict`, `unconstrained_verdict`, `verdict` у записей
    `per_bond` старого вида-списка, `while_pending_verdict`, `on_trigger_verdict`) — в любом месте документа;
  * ключи счётчика `summary.verdict_counts` — legacy-ключ сливается с целевым (числа складываются);
  * у `HOLD_NO_OFFER` в той же записи к `advisor_verdict_basis` дописывается пометка «(к оферте не предъявлять)» — смысл HOLD_NO_OFFER: держать, оферту не использовать; если поля нет —
    запись попадает в отчёт («пометку некуда дописать»).
Не меняется: `fundamental_score: RED_FLAG` (оценка фундаментала — другой перечень), свободный текст (упоминания кодов
в прозе только считаются и попадают в отчёт), всё остальное — ни на байт: правка построчная, без перезаписи YAML.
Каждый изменённый файл проверяется: разбор нового текста равен разбору старого с теми же заменами (кроме пометки
в `advisor_verdict_basis`, она проверяется отдельно) — иначе файл не пишется и попадает в отчёт ошибкой.
Идемпотентна: повторный прогон по мигрированному файлу ничего не меняет.

Режимы запуска:
  --in <файл|папка>   : обязательно; папка — все weekly-review-bond-*.yaml в ней;
  без --out и --apply : только отчёт в stdout, файлы не пишутся;
  --out <папка>       : изменённые копии и migration-report.md в эту папку;
  --apply             : правка на месте, рядом копия `<имя>.pre-ds.bak` (есть копия — файл пропускается).
ВНИМАНИЕ: --apply — только в момент переключения (decision.md §4.2, шаг 17), после архивации и «да» владельца.

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 tools/data-structures/migrations/migrate_bond_verdicts.py --in <...>
        [--out DIR] [--apply]
Зависимости: stdlib и PyYAML.
"""
from __future__ import annotations

import argparse
import copy
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "_shared-references"))

# Карта прежних кодов — литерал миграции: из кодлиста verdict они сняты после переключения.
LEGACY = {"HOLD_ADD": "ADD", "RED_FLAG": "WATCH", "MATURE": "HOLD_TO_MAT", "HOLD_NO_OFFER": "HOLD_TO_MAT"}
NO_OFFER = "HOLD_NO_OFFER"
NO_OFFER_MARK = "(к оферте не предъявлять)"
VERDICT_FIELDS = ("advisor_verdict", "prior_verdict", "unconstrained_verdict", "verdict",
                  "while_pending_verdict", "on_trigger_verdict")
BASIS = "advisor_verdict_basis"
COUNTS = "verdict_counts"
GLOB = "weekly-review-bond-*.yaml"

_CODES = "|".join(sorted(map(re.escape, LEGACY), key=len, reverse=True))
FIELD_RE = re.compile(r"^(?P<pre>(?P<ind>[ \t]*)(?:- +)?(?P<field>" + "|".join(VERDICT_FIELDS)
                      + r"):[ \t]*)(?P<q>[\"']?)(?P<code>" + _CODES + r")(?P=q)(?P<post>[ \t]*(?:#.*)?)$")
KEY_RE = re.compile(r"^(?P<ind>[ \t]*)(?P<key>[A-Za-z_][A-Za-z0-9_]*):(?P<rest>.*)$")
COUNT_RE = re.compile(r"^(?P<ind>[ \t]+)(?P<q>[\"']?)(?P<code>[A-Z_]+)(?P=q):[ \t]*(?P<n>\d+)[ \t]*$")
PROSE_RE = re.compile(r"\b(" + _CODES + r")\b")


class Result:
    def __init__(self, name: str):
        self.name = name
        self.status = "ok"           # ok | unchanged | error
        self.replaced: dict[str, int] = {}      # «поле: СТАРЫЙ→НОВЫЙ» → число
        self.counts_merged: list[str] = []
        self.basis_marked = 0
        self.basis_missing: list[str] = []      # номера строк HOLD_NO_OFFER без advisor_verdict_basis
        self.prose_mentions = 0
        self.errors: list[str] = []
        self.new_text: str | None = None

    @property
    def n_replaced(self) -> int:
        return sum(self.replaced.values())


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _entry_bounds(lines: list[str], i: int, ind: int, dash: bool) -> tuple[int, int]:
    """Границы записи (mapping), в которой стоит строка i с отступом ключа ind: [start, end)."""
    start = i
    if not dash:
        while start > 0:
            prev = lines[start - 1]
            if prev.strip() and _indent(prev) < ind:
                if prev.lstrip().startswith("- ") and _indent(prev) + 2 == ind:
                    start -= 1          # «- первый_ключ:» той же записи списка
                break
            start -= 1
    end = i + 1
    while end < len(lines):
        ln = lines[end]
        if ln.strip() and (_indent(ln) < ind or (_indent(ln) == ind and ln.lstrip().startswith("- "))):
            break
        end += 1
    return start, end


def _mark_basis(lines: list[str], start: int, end: int, ind: int) -> bool:
    """Дописать NO_OFFER_MARK к advisor_verdict_basis записи. False — поля нет или вид значения не поддержан."""
    for j in range(start, end):
        m = KEY_RE.match(lines[j].replace("- ", "  ", 1) if lines[j].lstrip().startswith("- ") else lines[j])
        if not m or m.group("key") != BASIS or len(m.group("ind")) != ind:
            continue
        rest = m.group("rest").strip()
        if rest[:1] in ("|", ">"):                          # блочный скаляр: строка в конец блока
            k = j + 1
            last = j
            while k < len(lines) and (not lines[k].strip() or _indent(lines[k]) > ind):
                if lines[k].strip():
                    last = k
                k += 1
            if last == j:
                return False
            lines.insert(last + 1, " " * _indent(lines[last]) + NO_OFFER_MARK)
            return True
        nxt = lines[j + 1] if j + 1 < len(lines) else ""
        if nxt.strip() and _indent(nxt) > ind:              # многострочный плоский скаляр — не трогаем
            return False
        body = lines[j]
        if rest[:1] in ('"', "'") and rest.endswith(rest[0]) and len(rest) >= 2:
            q = rest[0]
            cut = body.rstrip().rfind(q)
            lines[j] = body[:cut] + " " + NO_OFFER_MARK + body[cut:]
            return True
        if rest and not rest.startswith(("#", "&", "*", "!", "[", "{")) and " #" not in rest:
            lines[j] = body.rstrip() + " " + NO_OFFER_MARK
            return True
        return False
    return False


def _merge_counts(lines: list[str], res: Result) -> None:
    """summary.verdict_counts: legacy-ключ сливается с целевым."""
    i = 0
    while i < len(lines):
        m = KEY_RE.match(lines[i])
        if not (m and m.group("key") == COUNTS and not m.group("rest").strip()):
            i += 1
            continue
        ind = len(m.group("ind"))
        j, rows = i + 1, {}
        while j < len(lines) and (not lines[j].strip() or _indent(lines[j]) > ind):
            cm = COUNT_RE.match(lines[j])
            if cm:
                rows[cm.group("code")] = j
            j += 1
        drop = []
        for code, ln in list(rows.items()):
            if code not in LEGACY:
                continue
            target = LEGACY[code]
            n = int(COUNT_RE.match(lines[ln]).group("n"))
            if target in rows:
                tm = COUNT_RE.match(lines[rows[target]])
                lines[rows[target]] = f"{tm.group('ind')}{target}: {int(tm.group('n')) + n}"
                drop.append(ln)
            else:
                cm = COUNT_RE.match(lines[ln])
                lines[ln] = f"{cm.group('ind')}{target}: {n}"
                rows[target] = ln
            res.counts_merged.append(f"{code}→{target}: {n}")
        for ln in sorted(drop, reverse=True):
            del lines[ln]
        i = j - len(drop)


def _expected(obj):
    """Семантика миграции на разобранном YAML (для проверки построчной правки)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == COUNTS and isinstance(v, dict):
                cnt = {}
                for ck, cv in v.items():
                    nk = LEGACY.get(ck, ck)
                    cnt[nk] = cnt.get(nk, 0) + cv if isinstance(cv, int) and isinstance(cnt.get(nk, 0), int) else cv
                out[k] = cnt
            elif k in VERDICT_FIELDS and isinstance(v, str) and v in LEGACY:
                out[k] = LEGACY[v]
            else:
                out[k] = _expected(v)
        return out
    if isinstance(obj, list):
        return [_expected(x) for x in obj]
    return obj


def _strip_marks(obj):
    """Убрать пометку NO_OFFER_MARK из advisor_verdict_basis — сравнение остального."""
    if isinstance(obj, dict):
        return {k: (v.replace(" " + NO_OFFER_MARK, "").replace("\n" + NO_OFFER_MARK, "")
                    if k == BASIS and isinstance(v, str) else _strip_marks(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_marks(x) for x in obj]
    return obj


def migrate_text(name: str, text: str) -> Result:
    res = Result(name)
    try:
        old_obj = yaml.safe_load(text)
    except yaml.YAMLError as e:
        res.status, res.errors = "error", [f"YAML не разбирается: {str(e).splitlines()[0]}"]
        return res
    nl_end = text.endswith("\n")
    lines = text.split("\n")
    if nl_end:
        lines.pop()
    no_offer_rows = []
    for i, ln in enumerate(lines):
        m = FIELD_RE.match(ln)
        if not m:
            continue
        code, target = m.group("code"), LEGACY[m.group("code")]
        lines[i] = f"{m.group('pre')}{m.group('q')}{target}{m.group('q')}{m.group('post')}"
        key = f"{m.group('field')}: {code}→{target}"
        res.replaced[key] = res.replaced.get(key, 0) + 1
        if code == NO_OFFER:
            dash = ln.lstrip().startswith("- ")
            ind = _indent(ln) + (2 if dash else 0)
            no_offer_rows.append((i, ind, dash))
    for i, ind, dash in sorted(no_offer_rows, reverse=True):     # с конца: вставки строк не сдвигают предыдущие
        start, end = _entry_bounds(lines, i, ind, dash)
        if _mark_basis(lines, start, end, ind):
            res.basis_marked += 1
        else:
            res.basis_missing.append(f"строка {i + 1}")
    _merge_counts(lines, res)
    new_text = "\n".join(lines) + ("\n" if nl_end else "")
    res.prose_mentions = sum(1 for ln in new_text.split("\n") if PROSE_RE.search(ln)
                             and not re.match(r"^\s*fundamental_score:", ln))
    if new_text == text:
        res.status = "unchanged"
        return res
    try:
        new_obj = yaml.safe_load(new_text)
    except yaml.YAMLError as e:
        res.status, res.errors = "error", [f"после правки YAML не разбирается: {str(e).splitlines()[0]}"]
        return res
    if _strip_marks(new_obj) != _strip_marks(_expected(copy.deepcopy(old_obj))):
        res.status, res.errors = "error", ["проверка не сошлась: разбор после правки ≠ ожидаемой замене — файл не пишется"]
        return res
    res.new_text = new_text
    return res


def run_paths(src: Path) -> list[Result]:
    files = [src] if src.is_file() else sorted(p for p in src.glob(GLOB) if p.is_file())
    out = []
    for p in files:
        with open(p, encoding="utf-8", newline="") as f:
            out.append(migrate_text(p.name, f.read()))
    return out


def build_report(results: list[Result]) -> str:
    changed = [r for r in results if r.new_text is not None]
    lines = ["# Отчёт миграции словаря вердиктов облигаций", "", "## Сводка", "",
             f"- Файлов: {len(results)}; меняются: {len(changed)}; без изменений: "
             f"{sum(r.status == 'unchanged' for r in results)}; ошибок: {sum(r.status == 'error' for r in results)}",
             f"- Замен значений: {sum(r.n_replaced for r in results)}; слияний в verdict_counts: "
             f"{sum(len(r.counts_merged) for r in results)}",
             f"- Пометка «{NO_OFFER_MARK}» дописана: {sum(r.basis_marked for r in results)}; некуда дописать: "
             f"{sum(len(r.basis_missing) for r in results)}",
             f"- Строк прозы с legacy-кодами (не меняются): {sum(r.prose_mentions for r in results)}",
             f"- Карта: " + ", ".join(f"{k} → {v}" for k, v in LEGACY.items()), "",
             "## По файлам", "", "| Файл | Статус | Замены | verdict_counts | Пометка | Некуда дописать | Проза |",
             "|---|---|---|---|---|---|---|"]
    for r in results:
        rep = "; ".join(f"{k} ×{v}" for k, v in sorted(r.replaced.items())) or "—"
        lines.append(f"| {r.name} | {r.status}{(': ' + '; '.join(r.errors)) if r.errors else ''} | {rep} | "
                     f"{'; '.join(r.counts_merged) or '—'} | {r.basis_marked or '—'} | "
                     f"{', '.join(r.basis_missing) or '—'} | {r.prose_mentions or '—'} |")
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    if path.exists():
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def apply_in_place(src: Path, results: list[Result]) -> tuple[int, list[str]]:
    base = src if src.is_dir() else src.parent
    done, skipped = 0, []
    for r in results:
        if r.new_text is None:
            continue
        path = base / r.name
        bak = path.with_name(path.name + ".pre-ds.bak")
        if bak.exists():
            skipped.append(f"{r.name}: копия {bak.name} уже есть — пропущен")
            continue
        shutil.copy2(path, bak)
        _atomic_write(path, r.new_text)
        done += 1
    return done, skipped


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Миграция словаря вердиктов в обзорах облигаций (legacy → migrate_to)")
    ap.add_argument("--in", dest="src", required=True, help="файл обзора или папка weekly-reviews")
    ap.add_argument("--out", help="папка для изменённых копий и migration-report.md")
    ap.add_argument("--apply", action="store_true",
                    help="правка на месте с копией .pre-ds.bak (только при переключении, после архива и «да»)")
    args = ap.parse_args(argv)
    src = Path(args.src)
    if not src.exists():
        print(f"Нет такого пути: {src}", file=sys.stderr)
        return 2
    results = run_paths(src)
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
        done, skipped = apply_in_place(src, results)
        print(f"Применено на месте: {done}")
        for s in skipped:
            print("ПРОПУСК:", s, file=sys.stderr)
    return 1 if any(r.status == "error" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
