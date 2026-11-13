#!/usr/bin/env python3
"""validate_fca_output — pre-save гейт FCA (Шаг 6): форма вывода против §5.

Тонкий CLI над каноном `fca_output_checks` (канон — _shared-references/
fca_output_checks.py; в упакованном .skill pack.sh кладёт его рядом,
в scripts/, через `bundle_scripts:` — образец constraint_engine.py).

Использование (Шаг 6, ПЕРЕД save-to-library):
    echo '<forecast-yaml-as-json>' | python3 scripts/validate_fca_output.py
Exit 0 — форма чистая; exit 1 — есть blocking-нарушения (не сохранять,
исправить вывод и перегнать).
"""
from __future__ import annotations

import sys
from pathlib import Path


def _load_checks():
    """Импорт канона: соседний файл (packed) → _shared-references/ (repo)."""
    here = Path(__file__).resolve().parent
    for candidate in (here, here.parent.parent.parent / "_shared-references"):
        if (candidate / "fca_output_checks.py").exists():
            sys.path.insert(0, str(candidate))
            break
    import fca_output_checks
    return fca_output_checks


if __name__ == "__main__":
    sys.exit(_load_checks().main())
