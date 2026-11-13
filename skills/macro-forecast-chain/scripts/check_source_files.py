#!/usr/bin/env python3
"""Проверка bundle macro-scenarios/macro-input: файлы прогнозов у факторов и ссылки `forecast_files`.

`source_files: [forecasts/<файл>.yaml]` у фактора — точные файлы прогнозов, из которых взяты числа фактора.
`forecast_files: {<фактор>: "<имя файла прогноза без расширения>"}` на верхнем уровне рядом с `factors` —
ссылка макросценариев на прогнозы (schema.md §4.6): по ней вьюер идёт стресс → макросценарии → прогноз и
показывает «есть новее» по `superseded_by` прогноза. Блок строится из `source_files` этим скриптом
(`--forecast-files`), руками не собирается — одна реализация соответствия «фактор → файл прогноза».

Признак «новый файл»: `schema_version >= 2` (шаблон Шага 8 пишет `schema_version: 2`). У нового файла
`forecast_files` обязателен (ошибка, код 1); у старых (`schema_version: 1`) — необязателен, но если есть —
проверяется так же. Фактор без файла-источника (status MISSING / ACCEPTED_MISSING) не проверяется.

Запуск:
  python3 skills/macro-forecast-chain/scripts/check_source_files.py macro-scenarios-<дата>.yaml
  python3 skills/macro-forecast-chain/scripts/check_source_files.py --forecast-files macro-scenarios-<дата>.yaml
    (печатает готовый блок `forecast_files:` из `source_files`; неоднозначные факторы — в stderr)
Код: 0 — без ошибок (предупреждения возможны); 1 — ошибки `forecast_files`; 2 — файл не читается/не YAML.
"""
from __future__ import annotations

import json
import os
import sys

SKIP_STATUS = {"MISSING", "ACCEPTED_MISSING"}
FORECAST_FILES_SINCE_SCHEMA = 2


def _skipped(body) -> bool:
    return not isinstance(body, dict) or str(body.get("status", "")).upper() in SKIP_STATUS


def forecast_stem(path: str) -> str:
    """`forecasts/brent-price-2026-09-17.yaml` -> `brent-price-2026-09-17`."""
    base = os.path.basename(str(path).strip())
    for ext in (".yaml", ".yml", ".md"):
        if base.endswith(ext):
            return base[: -len(ext)]
    return base


def forecast_files_from_sources(doc: dict) -> tuple[dict[str, str], list[str]]:
    """{фактор: имя файла прогноза} из `source_files` факторов + список проблем (не угадываем).

    Берутся только пути `forecasts/…`; у фактора ровно один такой файл — ссылка ставится, ни одного или
    несколько — проблема в список (файлы `scenarios/…` — матрица сценариев, у неё своё поле source_file)."""
    out: dict[str, str] = {}
    problems: list[str] = []
    factors = doc.get("factors") if isinstance(doc, dict) else None
    if not isinstance(factors, dict):
        return out, ["нет блока factors"]
    for name, body in factors.items():
        if _skipped(body):
            continue
        files = body.get("source_files")
        if not isinstance(files, list):
            continue
        stems = sorted({forecast_stem(f) for f in files
                        if isinstance(f, str) and f.strip().replace("\\", "/").startswith("forecasts/")})
        if len(stems) == 1:
            out[name] = stems[0]
        elif len(stems) > 1:
            problems.append(f"factors.{name}: несколько файлов прогнозов в source_files ({', '.join(stems)}) — "
                            "forecast_files не ставится, выбрать один")
    return out, problems


def check(doc: dict) -> list[str]:
    """Список предупреждений: по одному на фактор без непустого `source_files`."""
    out: list[str] = []
    factors = doc.get("factors") if isinstance(doc, dict) else None
    if not isinstance(factors, dict):
        return ["нет блока factors"]
    for name, body in factors.items():
        if _skipped(body):
            continue
        files = body.get("source_files")
        if not (isinstance(files, list) and files and all(isinstance(f, str) and f.strip() for f in files)):
            out.append(f"factors.{name}: нет source_files — стресс-тест не знает точный файл прогноза")
    return out


def is_new(doc: dict) -> bool:
    sv = doc.get("schema_version") if isinstance(doc, dict) else None
    return isinstance(sv, int) and not isinstance(sv, bool) and sv >= FORECAST_FILES_SINCE_SCHEMA


def check_forecast_files(doc: dict) -> tuple[list[str], list[str]]:
    """(ошибки, предупреждения) по полю `forecast_files`."""
    errors: list[str] = []
    warns: list[str] = []
    if not isinstance(doc, dict):
        return ["файл — не объект"], warns
    factors = doc.get("factors") if isinstance(doc.get("factors"), dict) else {}
    ff = doc.get("forecast_files")
    if ff is None:
        if is_new(doc):
            errors.append(f"forecast_files: обязателен при schema_version >= {FORECAST_FILES_SINCE_SCHEMA} "
                          "(собрать: check_source_files.py --forecast-files)")
        return errors, warns
    if not isinstance(ff, dict):
        return [f"forecast_files: ожидается объект {{фактор: имя файла прогноза}}, получено {type(ff).__name__}"], warns
    derived, _ = forecast_files_from_sources(doc)
    for name, fn in ff.items():
        p = f"forecast_files.{name}"
        if not isinstance(fn, str) or not fn.strip():
            errors.append(f"{p}: ожидается непустая строка — имя файла прогноза")
            continue
        if "/" in fn or fn.endswith((".yaml", ".yml", ".md")):
            errors.append(f"{p}: имя файла без папки и расширения (`{forecast_stem(fn)}`), получено {fn!r}")
        if factors and name not in factors:
            warns.append(f"{p}: фактора {name!r} нет в factors")
        if name in derived and derived[name] != forecast_stem(fn):
            warns.append(f"{p}: {fn!r} не совпадает с source_files фактора ({derived[name]!r})")
    for name in derived:
        if name not in ff:
            warns.append(f"forecast_files: нет фактора {name!r}, хотя у него есть source_files ({derived[name]})")
    return errors, warns


def render_block(mapping: dict[str, str]) -> str:
    """Блок YAML `forecast_files:` (значения в кавычках — имена с датами не превращаются в даты)."""
    if not mapping:
        return "forecast_files: {}\n"
    lines = ["forecast_files:"]
    for k, v in mapping.items():
        lines.append(f"  {k}: {json.dumps(v, ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def _load(path: str):
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main(argv: list[str]) -> int:
    args = argv[1:]
    emit = "--forecast-files" in args
    args = [a for a in args if a != "--forecast-files"]
    if len(args) != 1:
        print(__doc__)
        return 2
    try:
        doc = _load(args[0])
    except Exception as e:  # noqa: BLE001
        print(f"ОШИБКА: {e}")
        return 2
    if emit:
        mapping, problems = forecast_files_from_sources(doc)
        for p in problems:
            print("WARNING:", p, file=sys.stderr)
        sys.stdout.write(render_block(mapping))
        return 0
    warns = check(doc)
    errors, fwarns = check_forecast_files(doc)
    for w in warns + fwarns:
        print("WARNING:", w)
    for e in errors:
        print("ОШИБКА:", e)
    print(f"source_files: предупреждений {len(warns)}; forecast_files: ошибок {len(errors)}, "
          f"предупреждений {len(fwarns)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
