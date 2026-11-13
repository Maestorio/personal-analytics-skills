#!/usr/bin/env python3
"""Проверка сетки дат файла макро-цепочки macro-scenarios-<дата>.yaml перед выдачей (Шаг 8).

Та же проверка, что у стресса и у сохранения в библиотеку (общий модуль macro_grid_check): пять числовых
факторов, у каждого уровни по датам для каждого сценария, спот в baseline_spot. Сценарии — из
`scenario_matrix.scenarios` файла, иначе по ключам by_scenario.

Плюс сверка матрицы: прогнозы факторов (`forecast_files`, иначе `factors.*.source_files` с `forecasts/`)
должны быть построены на той же матрице, что указана в `scenario_matrix.source_file` файла
(`conditional_on_scenarios.source_matrix` прогноза); иначе отказ. Без корня библиотеки сверка
пропускается с предупреждением.

Запуск: python3 scripts/check_macro_scenarios.py macro-scenarios-<дата>.yaml [--root <Claude-Memory>]
Корень без --root выводится из положения файла (<root>/macro-chain/ или <root>/_drafts/, где рядом forecasts/).
Код: 0 — годен (предупреждения возможны); 1 — есть отказы; 2 — файл не читается/не YAML.
"""
from __future__ import annotations

import os
import sys

# Общий модуль: сначала каталог скрипта (пакет .skill), затем _shared-references/ репозитория.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import macro_grid_check as _mgc  # noqa: E402


def _stem(x) -> str | None:
    if not x:
        return None
    b = os.path.basename(str(x).strip())
    for ext in (".yaml", ".yml", ".md"):
        if b.endswith(ext):
            b = b[: -len(ext)]
    return b or None


def check_forecast_matrix(doc: dict, root: str | None) -> tuple[list[str], list[str]]:
    """Матрица каждого прогноза фактора против матрицы файла: (ошибки, предупреждения)."""
    errs: list[str] = []
    warns: list[str] = []
    if not isinstance(doc, dict):
        return errs, warns
    sm = doc.get("scenario_matrix")
    mat = _stem(sm.get("source_file")) if isinstance(sm, dict) else None
    if not mat:
        warns.append("в файле нет scenario_matrix.source_file — матрица прогнозов не сверена")
        return errs, warns
    ffs: dict[str, str] = {}
    fl = doc.get("forecast_files")
    if isinstance(fl, dict) and fl:
        ffs = {str(k): str(v) for k, v in fl.items() if v}
    else:
        facs = doc.get("factors")
        for name, fv in (facs.items() if isinstance(facs, dict) else []):
            sf = fv.get("source_files") if isinstance(fv, dict) else None
            for p in (sf if isinstance(sf, list) else []):
                if isinstance(p, str) and p.startswith("forecasts/"):
                    ffs[str(name)] = p
                    break
    if root is None:
        warns.append("матрица прогнозов не сверена: укажи --root <Claude-Memory>")
        return errs, warns
    try:
        import yaml
    except Exception as e:  # noqa: BLE001
        warns.append(f"матрица прогнозов не сверена: {e}")
        return errs, warns
    for fac, ref in ffs.items():
        st = _stem(ref)
        path = os.path.join(root, "forecasts", f"{st}.yaml")
        if not os.path.isfile(path):
            warns.append(f"фактор {fac}: файл прогноза {path} не найден — матрица не сверена")
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                fd = yaml.safe_load(f)
        except Exception as e:  # noqa: BLE001
            warns.append(f"фактор {fac}: прогноз {st} не читается ({e}) — матрица не сверена")
            continue
        cos = fd.get("conditional_on_scenarios") if isinstance(fd, dict) else None
        fm = _stem(cos.get("source_matrix")) if isinstance(cos, dict) else None
        if not fm:
            continue
        if fm != mat:
            errs.append(f"фактор {fac}: прогноз {st} построен на матрице {fm}, файл собран на матрице {mat} "
                        f"— значения по сценариям относятся к другой матрице; пересобери прогноз на {mat}")
    return errs, warns


def _derive_root(path: str) -> str | None:
    parent = os.path.dirname(os.path.dirname(os.path.abspath(path)))
    return parent if os.path.isdir(os.path.join(parent, "forecasts")) else None


def main(argv: list[str]) -> int:
    root = None
    if "--root" in argv:
        i = argv.index("--root")
        if i + 1 >= len(argv):
            sys.stderr.write(__doc__ or "")
            return 2
        root = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if len(argv) != 1:
        sys.stderr.write(__doc__ or "")
        return 2
    try:
        import yaml
        with open(argv[0], "r", encoding="utf-8") as f:
            doc = yaml.safe_load(f)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"файл не читается: {e}\n")
        return 2
    errs, warns = _mgc.check_macro_file(doc)
    if root is None:
        root = _derive_root(argv[0])
    e2, w2 = check_forecast_matrix(doc, root)
    errs, warns = errs + e2, warns + w2
    for w in warns:
        sys.stdout.write(f"ПРЕДУПРЕЖДЕНИЕ: {w}\n")
    if errs:
        sys.stdout.write("ОТКАЗ:\n  " + "\n  ".join(errs) + "\n")
        return 1
    sys.stdout.write("ок\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
