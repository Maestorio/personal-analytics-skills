"""HTML-рендереры стадий (дизайн-система Claude Design, движок html_lib).

Параллельны reportlab-билдерам в `stages/`: переиспользуют тот же слой
извлечения (`stages/stageN.extract_content`), отвечают только за HTML.

Точка входа движка — `render_html(stage_id, adapted, output_path, …)`:
извлекает контент и собирает HTML для любой стадии 0–6. CLI (`export.py
--engine html`) вызывает её для `--format html` и для HTML→PDF.
"""
from __future__ import annotations

import re
from pathlib import Path

# Импорт подмодулей — для прямого доступа и единообразия с `stages/`.
from . import (  # noqa: F401,E402
    stage0, stage1, stage2, stage3, stage4, stage5, stage6)

try:  # пакетный запуск (`python3 export.py`, тесты)
    from export import html_lib  # type: ignore[no-redef]  # noqa: E402,F401
    from export.stages import (  # type: ignore[no-redef]  # noqa: E402
        stage0 as _e0, stage1 as _e1, stage2 as _e2,
        stage3 as _e3, stage4 as _e4, stage5 as _e5)
except ImportError:  # запуск из каталога export/
    import html_lib  # type: ignore  # noqa: E402,F401
    from stages import (  # type: ignore  # noqa: E402
        stage0 as _e0, stage1 as _e1, stage2 as _e2,
        stage3 as _e3, stage4 as _e4, stage5 as _e5)


# Канонический stage_id → (extractor: adapted→content, html-builder).
# Stage 6 — особый случай (на вход parsed 6_final + source_file, резолвит 5_vX).
_HTML = {
    "0_scope":           (_e0.extract_content, stage0.build_html),
    "1_dr_reports":      (_e1.extract_content, stage1.build_html),
    "2_similarity":      (_e2.extract_content, stage2.build_html),
    "3_poi_aggregation": (_e3.extract_content, stage3.build_html),
    "4_variants":        (_e4.extract_content, stage4.build_html),
    "5_final_plan":      (_e5.extract_content, stage5.build_html),
}

# Лидирующая цифра stage_id → канонический id (толерантный резолв).
_BY_DIGIT = {
    "0": "0_scope", "1": "1_dr_reports", "2": "2_similarity",
    "3": "3_poi_aggregation", "4": "4_variants", "5": "5_final_plan",
    "6": "6_final",
}

# Стадии, у которых ориентация зависит от формата: HTML — портрет, PDF — landscape
# (крупные карточки источников Stage 1). Их build_html принимает `landscape=`.
_PDF_LANDSCAPE = {"1_dr_reports"}

# Каноничное имя md-источника Stage 3 в директории поездки. Ровно этот класс имён
# пропускает whitelist write-API (`^travel-planner/trips/[^/]+/3_[^/]+\.md$`).
_CANON_S3_MD_RE = re.compile(r"^3_.+\.md$")
# То же для Stage 4 (edit-слой комментариев к вариантам; whitelist `4_*.md`).
_CANON_S4_MD_RE = re.compile(r"^4_.+\.md$")
_VER_RE = re.compile(r"_v(\d+)")


def normalize_stage_id(stage_id: str | None) -> str | None:
    """«5_final_plan» / «5_stage» / «5» → «5_final_plan» (толерантно к alias'ам)."""
    if not stage_id:
        return None
    s = str(stage_id)
    if s in _HTML or s == "6_final":
        return s
    if s[:1] in _BY_DIGIT:
        return _BY_DIGIT[s[0]]
    return s


def has_builder(stage_id: str | None) -> bool:
    """Есть ли HTML-рендерер для стадии (включая Stage 6)."""
    sid = normalize_stage_id(stage_id)
    return sid in _HTML or sid == "6_final"


def _gate(sid: str, extracted: dict) -> None:
    """Гейты целостности — те же, что в reportlab-ветке (Р6): при критичном
    расхождении парсинга документ НЕ собираем, а падаем с понятным сообщением
    (иначе HTML тихо выдаёт кривой артефакт с пропавшими регионами/POI)."""
    if sid == "3_poi_aggregation":
        _e3._gate_validation(extracted)  # raises на errors + печатает warnings
        return
    # Stage 2 отдаёт dataclass (не dict) — гейт по validation_errors только для
    # Stage 0, где extract_content возвращает dict с этим ключом.
    if sid == "0_scope":
        errs = extracted.get("validation_errors") or []
        if errs:
            raise RuntimeError(
                "Stage 0 export — несоответствие longlist (HTML не собран):\n  - "
                + "\n  - ".join(errs)
                + "\nИсправь 0_scope.md / polished.md и повтори.")


def _stage3_md_name(output_path: str | Path,
                    source_file: str | Path | None) -> str | None:
    """Имя md-источника для edit-слоя Stage 3 (или None — слой не включаем).

    Страница просит этот файл у write-API хостинга по пути «рядом с собой»,
    поэтому имя обязано быть КАНОНИЧНЫМ `3_*.md` из директории поездки: whitelist
    сайдкара (`tools/hosting/api/server.py`) пускает только `trips/{id}/3_*.md`.
    Вход экспорта каноничным НЕ является — двухслойный flow (polish → render)
    предписывает `--input polished_stage_3.md`, и имя черновика в странице даёт
    тихий 403: edit-слой не поднимается, правки недоступны без единого сообщения
    (реальный случай — регион_a_2027, 2026-07-27).

    Порядок: имя входа, если оно само каноничное → иначе `3_*.md` рядом с выводом
    (при нескольких — `3_poi_pool.md`, затем максимальный `_vN`).
    """
    return _canon_md_name(output_path, source_file, _CANON_S3_MD_RE,
                          "3_*.md", preferred="3_poi_pool.md")


def _stage4_md_name(output_path: str | Path,
                    source_file: str | Path | None) -> str | None:
    """Имя md-источника для edit-слоя Stage 4 (комментарии к вариантам).

    Логика `_stage3_md_name`, но без «предпочтительного» имени: итерации Stage 4
    рождают `4_variants_v{N+1}.md`, и актуальна максимальная версия."""
    return _canon_md_name(output_path, source_file, _CANON_S4_MD_RE, "4_*.md")


def _canon_md_name(output_path, source_file, canon_re, glob: str,
                   preferred: str | None = None) -> str | None:
    src = Path(source_file).name if source_file else ""
    if canon_re.match(src):
        return src
    out_dir = Path(output_path).parent
    try:
        cands = [p.name for p in out_dir.glob(glob)
                 if canon_re.match(p.name)
                 and not p.name.endswith("_stage_log.md")]
    except OSError:
        cands = []
    if not cands:
        return None
    if preferred and preferred in cands:
        return preferred

    def _ver(name: str) -> int:
        m = _VER_RE.search(name)
        return int(m.group(1)) if m else 0

    return sorted(cands, key=lambda n: (_ver(n), n))[-1]


def render_html(stage_id: str, adapted: dict, output_path: str | Path, *,
                recipient: str = "self", embed_fonts: bool = True,
                source_file: str | Path | None = None,
                for_pdf: bool = False) -> str:
    """Отрендерить стадию в HTML (Claude Design) и записать в `output_path`.

    Возвращает HTML-строку. Stage 6 особый: на вход parsed 6_final + `source_file`,
    резолвит устаканенный 5_vX. Остальные: `extract_content(adapted)` → `build_html`.

    Stage 3 обогащается из соседних `1_dr_reports.md` (url/год авторов) и
    `0_scope*.md` (описания регионов), как reportlab-ветка. Перед сборкой —
    те же гейты валидации, что и PDF/DOCX (см. `_gate`).

    `for_pdf=True` — рендер как промежуток для HTML→PDF: стадии из `_PDF_LANDSCAPE`
    (Stage 1) отдаются в landscape; HTML-экспорт (`for_pdf=False`) — портрет.
    """
    sid = normalize_stage_id(stage_id)

    def _finish(doc: str) -> str:
        """Промежуточный рендер для PDF интерактив не несёт: навигационный слой
        в печати всё равно скрыт, а внутри документа-полуфабриката это мёртвый
        вес и лишний JS во время печатного прогона chromium."""
        if not for_pdf:
            return doc
        doc = html_lib.strip_nav_layer(doc)
        Path(output_path).write_text(doc, encoding="utf-8")
        return doc

    if sid == "6_final":
        return _finish(stage6.build_html(adapted, output_path, source_file=source_file,
                                         recipient=recipient, embed_fonts=embed_fonts))
    if sid not in _HTML:
        raise KeyError(f"нет HTML-рендерера для стадии {stage_id!r}")
    extractor, builder = _HTML[sid]
    # Кандидаты путей для резолвера «Кто едет»: исходный md может быть
    # эфемерным polished-файлом вне trips/ — вывод же идёт в каноническую
    # директорию поездки (там trip.yaml и walk-up до profiles/).
    who_paths = [source_file, output_path]
    if sid == "3_poi_aggregation":
        # Обогащение из соседних артефактов (реестр авторов / описания регионов).
        extracted = extractor(
            adapted,
            stage1_path=_e3._guess_stage1_path(output_path, source_file),
            stage0_path=_e3._guess_stage0_path(output_path, source_file),
            input_path=who_paths,
        )
    else:
        extracted = extractor(adapted, input_path=who_paths)
    _gate(sid, extracted)
    if sid == "3_poi_aggregation":
        # Edit-слой (правка тегов/комментариев через write-API хостинга):
        # только для HTML-экспорта, не для HTML→PDF-прогона. Имени md-источника
        # достаточно — на хостинге он лежит рядом со страницей (канон trips/),
        # но имя берём КАНОНИЧНОЕ, а не имя входного polished-черновика
        # (см. `_stage3_md_name`: чужое имя = тихий 403 и мёртвый edit-слой).
        src_name = None if for_pdf else _stage3_md_name(output_path, source_file)
        return _finish(builder(extracted, output_path, recipient=recipient,
                               embed_fonts=embed_fonts, source_md_name=src_name))
    if sid == "4_variants":
        # Edit-слой комментариев к вариантам — та же логика имени, что у Stage 3.
        src_name = None if for_pdf else _stage4_md_name(output_path, source_file)
        return _finish(builder(extracted, output_path, recipient=recipient,
                               embed_fonts=embed_fonts, source_md_name=src_name))
    if sid == "5_final_plan":
        # source_file — второй кандидат каталога для поиска файла плана, в
        # который слой пишет отметки подготовки (вывод мог уехать в --output-dir).
        return _finish(builder(extracted, output_path, recipient=recipient,
                               embed_fonts=embed_fonts, source_file=source_file))
    if sid in _PDF_LANDSCAPE:
        return _finish(builder(extracted, output_path, recipient=recipient,
                               embed_fonts=embed_fonts, landscape=for_pdf))
    return _finish(builder(extracted, output_path, recipient=recipient,
                           embed_fonts=embed_fonts))
