"""file_naming.py — конвенции имён файлов экспорта (storage-and-naming §4.2).

Шаблон:
    {stage_short}_{краткое_русское_имя}_{YYYY-MM-DD}[_{discriminator}].{ext}

Примеры:
    0_регионы_2026-05-27.pdf
    3_места_2026-05-27.docx
    5_финальный_план_для_родителей_2026-05-27.pdf
    4_варианты_v2_2026-05-27.docx
    5_финальный_план_2026-05-27_а.pdf   # коллизия → дискриминатор

Имена экспортов лежат в той же папке `trips/{trip_id}/`, что и исходный
md-артефакт. Отдельной подпапки `exports/` нет.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Iterable


# Короткие русские имена по умолчанию (storage-and-naming.md §4.2).
DEFAULT_NAMES = {
    "0": "регионы",
    "1": "dr_отчёты",
    "2": "похожие_авторы",
    "3": "места",
    "4": "варианты",
    "5": "финальный_план",
    "6": "финал",
}

# Опциональные суффиксы для уточнения получателя (часть описательного
# имени, НЕ отдельный структурный слот).
RECIPIENT_SUFFIX = {
    "self":     "",            # дефолт — суффикс не нужен
    "parents":  "для_родителей",
    "field":    "полевой",     # полевая версия (без подготовительных/review-секций)
}

# Разрешённые расширения экспорта.
VALID_EXTENSIONS = {"pdf", "docx", "pptx", "xlsx", "html"}


def build_trip_doc_filename(
    trip_id: str, what: str, *, stage: str | int | None = None,
    version: int | None = 1, ext: str = "pdf", recipient: str = "self",
) -> str:
    """Имя trip-документа: `{stage}_{trip_id}_{что}[_v{N}][_получатель].{ext}`.

    Единая конвенция (2026-06-01): первым сегментом — номер стадии
    (`0`..`5`), затем `trip_id` формы `{страна(ы)}_{YYYY-MM}`, затем
    описание. Примеры:
      - `5_камбоджа_лаос_2026-02_финальный_план_v1.pdf`
      - `2_корея_2024-03_похожие_авторы.html`
      - `0_аргентина_юг_2025-03_регионы.pdf`

    `stage=None` — префикс опускается (legacy / generic). `version=None` —
    суффикс `_v{N}` опускается (стадии без итерационных версий: 0/1/2/3).
    Для не-self получателя добавляется суффикс.
    """
    if ext not in VALID_EXTENSIONS:
        raise ValueError(f"расширение {ext!r} не поддерживается")
    parts: list[str] = []
    if stage is not None:
        parts.append(str(stage))
    parts += [trip_id, what]
    if version is not None:
        parts.append(f"v{version}")
    suffix = RECIPIENT_SUFFIX.get(recipient, "")
    if suffix:
        parts.append(suffix)
    return "_".join(parts) + f".{ext}"


def build_final_plan_filename(
    trip_id: str, *, version: int = 1, ext: str = "pdf",
    recipient: str = "self",
) -> str:
    """Имя финального плана: `{trip_id}_план_v{N}[_получатель].{ext}`."""
    return build_trip_doc_filename(
        trip_id, "финальный_план", stage="5", version=version, ext=ext,
        recipient=recipient,
    )


def build_variants_filename(
    trip_id: str, *, version: int = 1, ext: str = "pdf",
    recipient: str = "self",
) -> str:
    """Имя витрины вариантов: `4_{trip_id}_варианты_v{N}[_получатель].{ext}`."""
    return build_trip_doc_filename(
        trip_id, "варианты", stage="4", version=version, ext=ext,
        recipient=recipient,
    )


def build_final_filename(
    trip_id: str, *, version: int = 1, ext: str = "pdf",
    recipient: str = "self",
) -> str:
    """Имя финала Stage 6: `6_{trip_id}_финал_v{N}[_получатель].{ext}`.

    Versioned (как 4/5) — перегон после новой брони / enrichment даёт v2, v3.
    Отличается от Stage 5 (`финальный_план`): Stage 6 — «идеал»-сборка (план +
    карта + досье), описание `финал`.
    """
    return build_trip_doc_filename(
        trip_id, "финал", stage="6", version=version, ext=ext,
        recipient=recipient,
    )


def build_scope_filename(
    trip_id: str, *, ext: str = "pdf", recipient: str = "self",
) -> str:
    """Имя витрины регионов Stage 0: `{trip_id}_регионы[_получатель].{ext}`.

    Без суффикса `_v{N}` — Stage 0 артефакт `0_scope.md` один per trip,
    пересмотр перезаписывает (storage-and-naming.md §2.1, §9.7).
    """
    return build_trip_doc_filename(
        trip_id, "регионы", stage="0", version=None, ext=ext, recipient=recipient,
    )


def build_dr_reports_filename(
    trip_id: str, *, ext: str = "pdf", recipient: str = "self",
) -> str:
    """Имя DR-базы Stage 1: `{trip_id}_dr_отчёты[_получатель].{ext}`.

    Без суффикса `_v{N}` — Stage 1 артефакт `1_dr_reports.md` один per
    trip; перепрогон DR переписывает (storage-and-naming.md §2.1).
    """
    return build_trip_doc_filename(
        trip_id, "dr_отчёты", stage="1", version=None, ext=ext, recipient=recipient,
    )


def build_similarity_filename(
    trip_id: str, *, ext: str = "pdf", recipient: str = "self",
) -> str:
    """Имя витрины Stage 2: `2_{trip_id}_похожие_авторы[_получатель].{ext}`.

    Без суффикса `_v{N}` — Stage 2 артефакт `2_similarity.md` один per trip;
    пересмотр перезаписывает (storage-and-naming.md §2.1). `ext`:
      - `pdf`  — статичная scoring-витрина (default);
      - `html` — интерактивный lookup (фильтр / сортировка / expand).
    """
    return build_trip_doc_filename(
        trip_id, "похожие_авторы", stage="2", version=None, ext=ext,
        recipient=recipient,
    )


def build_poi_filename(
    trip_id: str, *, ext: str = "docx", recipient: str = "self",
) -> str:
    """Имя витрины POI Stage 3: `{trip_id}_места[_получатель].{ext}`.

    Без суффикса `_v{N}` — Stage 3 артефакт `3_poi_aggregation.md` один
    per trip; пересмотр перезаписывает (storage-and-naming.md §2.1).

    Default ext = "docx": Stage 3 — operative-документ, в котором
    пользователь заполняет теги регионов и комментарии POI.
    `ext="pdf"` — read-only витрина (для sharing / архива после
    заполнения).
    """
    return build_trip_doc_filename(
        trip_id, "места", stage="3", version=None, ext=ext, recipient=recipient,
    )


def build_export_filename(
    stage: str,
    ext: str,
    *,
    recipient: str = "self",
    short_name: str | None = None,
    date: dt.date | None = None,
    version: int | None = None,
    discriminator: str | None = None,
) -> str:
    """Собрать имя файла экспорта по конвенции §4.2.

    Параметры:
      - `stage`            — `"0"` / `"1"` / ... / `"5"` или полный
                             `stage` из YAML (`"5_final_plan"`).
      - `ext`              — `"pdf"` / `"docx"` / `"pptx"` / `"xlsx"`.
      - `recipient`        — для добавления суффикса (см. RECIPIENT_SUFFIX).
      - `short_name`       — переопределить дефолт из DEFAULT_NAMES.
      - `date`             — дата генерации (по умолчанию сегодня).
      - `version`          — версия Stage 4/5 (например, `2` → суффикс `_v2`).
      - `discriminator`    — `"а"` / `"б"` / ... для разруливания коллизий
                             когда дата + имя совпадают.
    """
    stage_short = _stage_short(stage)
    name = short_name or DEFAULT_NAMES.get(stage_short)
    if name is None:
        raise ValueError(
            f"нет дефолтного короткого имени для stage {stage!r}; "
            f"передай `short_name=...` явно"
        )
    if ext not in VALID_EXTENSIONS:
        raise ValueError(
            f"расширение {ext!r} не поддерживается; ожидается одно из "
            f"{sorted(VALID_EXTENSIONS)}"
        )

    parts = [stage_short, name]
    if version is not None:
        parts.append(f"v{version}")
    rec_suffix = RECIPIENT_SUFFIX.get(recipient, "")
    if rec_suffix:
        parts.append(rec_suffix)

    date = date or dt.date.today()
    parts.append(date.strftime("%Y-%m-%d"))
    if discriminator:
        parts.append(discriminator)

    return "_".join(parts) + f".{ext}"


def _stage_short(stage: str) -> str:
    """Достать короткий префикс стадии (`0`/`1`/.../`5`)."""
    if not stage:
        raise ValueError("stage не может быть пустым")
    m = re.match(r"^(\d)(?:_|$)", stage)
    if m:
        return m.group(1)
    if stage in DEFAULT_NAMES:
        return stage
    raise ValueError(f"не понял stage {stage!r}; ожидается '0'..'5' или '5_final_plan' и т.п.")


def parse_export_filename(filename: str) -> dict | None:
    """Распарсить имя экспорта (обёртка `build_export_filename`) обратно в
    компоненты. Возвращает dict или None, если имя не соответствует конвенции.

    Требует дату `_YYYY-MM-DD` в имени — т.е. парсит имена от
    `build_export_filename` (round-trip), а НЕ безымянно-датовые trip-имена
    stage-специфичных билдеров (`{trip_id}_регионы.pdf` и т.п.). Реальный
    import-flow Stage 3 DOCX опознаёт стадию не по имени, а через
    `stage3.parse_docx_for_import`; эта функция — утилита build↔parse
    round-trip (см. test_export_engine §10)."""
    stem = Path(filename).stem
    ext = Path(filename).suffix.lstrip(".").lower()
    if ext not in VALID_EXTENSIONS:
        return None
    # Дата в имени должна быть.
    m = re.search(r"_(\d{4}-\d{2}-\d{2})(?:_([а-яa-z]))?$", stem)
    if not m:
        return None
    date_str = m.group(1)
    discriminator = m.group(2)
    try:
        date = dt.date.fromisoformat(date_str)
    except ValueError:
        return None
    head = stem[: m.start()]
    parts = head.split("_")
    if len(parts) < 2 or not parts[0].isdigit():
        return None
    stage_short = parts[0]
    rest = parts[1:]
    # Поднять опциональный `v{N}` суффикс.
    version: int | None = None
    if rest and re.fullmatch(r"v(\d+)", rest[-1]):
        version = int(re.fullmatch(r"v(\d+)", rest[-1]).group(1))
        rest = rest[:-1]
    # Угадать recipient по совпадению с RECIPIENT_SUFFIX (если суффикс
    # стоит в конце rest).
    recipient = "self"
    for r_name, r_suffix in RECIPIENT_SUFFIX.items():
        if not r_suffix:
            continue
        suffix_parts = r_suffix.split("_")
        if len(suffix_parts) <= len(rest) and rest[-len(suffix_parts):] == suffix_parts:
            recipient = r_name
            rest = rest[: -len(suffix_parts)]
            break
    short_name = "_".join(rest) if rest else None
    return {
        "stage_short":   stage_short,
        "short_name":    short_name,
        "recipient":     recipient,
        "version":       version,
        "date":          date,
        "discriminator": discriminator,
        "ext":           ext,
    }


def next_discriminator(existing: Iterable[str]) -> str:
    """Подобрать следующий свободный дискриминатор (а / б / в / г / ...).

    `existing` — список уже использованных однобуквенных дискриминаторов.
    """
    used = set(existing)
    # Русский алфавит без ё/ъ — простая прогрессия.
    for ch in "абвгдежзиклмнопрстуфхцчшщэюя":
        if ch not in used:
            return ch
    raise RuntimeError("исчерпан алфавит дискриминаторов — это явный bug")
