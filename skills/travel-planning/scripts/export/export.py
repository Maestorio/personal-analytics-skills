#!/usr/bin/env python3
"""export.py — CLI entry point движка экспорта.

Usage:
    # Export stage в формат под получателя (выбор формата — дефолт стадии).
    python3 export.py --stage 5 --trip аргентина_юг_2025-03 --recipient self
    python3 export.py --stage 3 --trip вьетнам_2023-09 --recipient self --format docx
    python3 export.py --stage 5 --trip вьетнам_2023-09 --recipient parents

    # Презентационный движок (--engine html, дизайн-система):
    #   --format html → self-contained .html;
    #   --format pdf  → HTML→PDF (сайдкар .html + конвертация core pdf skill).
    # --engine reportlab — нативный рендер (локальный PDF без браузера,
    # DOCX Stage 3). Дефолт движка — html везде, КРОМЕ PDF Stage 6: дорожный
    # документ печатают, ему нужны номера страниц и воспроизводимость (см.
    # DEFAULT_ENGINE). Явный --engine перекрывает дефолт в обе стороны.
    python3 export.py --stage 5 --trip корея_2025 --format html
    python3 export.py --stage 6 --trip корея_2025 --format pdf              # reportlab
    python3 export.py --stage 6 --trip корея_2025 --format pdf --engine html  # HTML→PDF

    # Import обратно (DOCX → md) — round-trip для Stage 3/4.
    python3 export.py --import path/to/filled.docx --trip вьетнам_2023-09

    # Только парсинг — для debugging.
    python3 export.py --parse-only path/to/5_final_plan.md

Step 1 (engine) НЕ реализует stage-специфичный рендеринг. Если для
запрошенной (stage, format) пары не зарегистрирован renderer — CLI
выводит подготовленный `RenderRequest` как JSON в stdout и заканчивает
exit-кодом 0; это полезно для testing и для последующего pipeline'а,
который сам отдаст payload core-скиллу.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Поддерживаем запуск как `python3 export.py` и как `python3 -m ...export`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from export import adapter, file_naming, parser, renderer  # type: ignore[no-redef]
else:
    from . import adapter, file_naming, parser, renderer

# Импорт пакета stages регистрирует renderer'ы во всех известных stage-модулях
# (stage5, и в будущем stage0/1/3/4). Делается отложенно и обёрнуто в try/except,
# чтобы CLI с командами `--parse-only` / `--import` оставался рабочим даже
# при отсутствии reportlab — экспорт стадии-конкретного PDF в этом случае
# просто не зарегистрирует stage-renderer, и CLI выдаст RenderRequest JSON.
try:
    if __package__ in (None, ""):
        from export import stages  # type: ignore[no-redef]  # noqa: F401
    else:
        from . import stages  # noqa: F401
except Exception as _stage_import_err:
    print(f"warning: stage-renderer'ы не зарегистрированы ({_stage_import_err}); "
          f"export.py продолжит без stage-PDF — выдаст только RenderRequest JSON",
          file=sys.stderr)


# Карта дефолтных форматов по стадии (Р1: дефолт — HTML везде, PDF/DOCX по
# явному `--format`). Stage 2 `--format html` → интерактивный lookup (Р4);
# Stage 3 DOCX (round-trip импорт) — по явному `--format docx`.
DEFAULT_FORMAT = {
    "0": "html",
    "1": "html",
    "2": "html",   # интерактивный lookup (Р4); `--format pdf` — статичная витрина
    "3": "html",   # `--format docx` — operative-документ + round-trip импорт
    "4": "html",
    "5": "html",
    "6": "html",   # финал: механический рендер 5_vX + карта + досье
}

# Карта дефолтного движка по (стадия, формат). Везде презентационный HTML-движок
# (дизайн-система, PDF через HTML→PDF), кроме PDF Stage 6.
#
# Почему Stage 6 --format pdf идёт нативным reportlab (решение 2026-09-03):
#   * Stage 6 — единственная стадия, чей PDF существует ради бумаги: его печатают
#     и берут в поездку. Там нужны номера страниц и колонтитул с провенансом
#     («финал · из 5_final_plan_v6.md · создан …») — HTML→PDF не даёт ни того,
#     ни другого.
#   * HTML→PDF воспроизводим только в пределах одной машины: конвертер выбирается
#     из того, что установлено (chromium → weasyprint → wkhtmltopdf), и разбивка
#     на страницы у них разная. Три экспорта одного вьетнамского финала дали три
#     разных конвертера и 13/25/26 страниц. Для дорожного документа это дефект.
#   * Содержимое при этом не расходится: оба движка рендерят один и тот же
#     polish-md через один парсер (замер на 6_final_v3.md — покрытие текста
#     87,5% против 87,6%, расхождение в три слова).
# Экранный HTML Stage 6 остаётся на HTML-движке — там дизайн-система и есть
# основной артефакт «проверить с телефона».
DEFAULT_ENGINE = {("6", "pdf"): "reportlab"}


def _resolve_travel_root(arg_root: str | None) -> Path:
    """Резолв `{travel_root}` для CLI-режима.

    Приоритет:
      1. явный `--travel-root` аргумент,
      2. переменная окружения `TRAVEL_ROOT`,
      3. Synology mount по умолчанию (см. storage-and-naming §1.1).

    Не падает, если путь не существует — некоторые сценарии (parse-only,
    рендер из приложенного файла) этого не требуют.
    """
    import os
    if arg_root:
        return Path(arg_root).expanduser()
    env = os.environ.get("TRAVEL_ROOT")
    if env:
        return Path(env).expanduser()
    return Path(
        "~/Library/CloudStorage/SynologyDrive-home/"
        "Claude-Memory/travel-planner/"
    ).expanduser()


def _find_stage_file(travel_root: Path, trip_id: str, stage: str) -> Path:
    """Найти артефакт стадии для поездки.

    Stage 0–3: один файл per trip (`{N}_*.md`).
    Stage 4/5/6: versioned (`{N}_*_v*.md`) → берём максимальную версию.
    """
    trip_dir = travel_root / "trips" / trip_id
    if not trip_dir.exists():
        raise FileNotFoundError(f"папка поездки не найдена: {trip_dir}")
    if stage in ("4", "5", "6"):
        candidates = sorted(trip_dir.glob(f"{stage}_*_v*.md"))
        if not candidates:
            # Legacy compat: без _v суффикса.
            candidates = sorted(trip_dir.glob(f"{stage}_*.md"))
        if not candidates:
            raise FileNotFoundError(
                f"артефакт Stage {stage} не найден в {trip_dir} (искал {stage}_*_v*.md)"
            )
        # Versioned: сортировка по версии, не лексикографически.
        return max(candidates, key=_version_sort_key)
    # Stage 0–3: один файл.
    candidates = sorted(trip_dir.glob(f"{stage}_*.md"))
    # Отсеиваем экспорты (.md тут только md-стадии; экспорты — pdf/docx).
    candidates = [c for c in candidates if not c.stem.endswith("_export")]
    if not candidates:
        raise FileNotFoundError(
            f"артефакт Stage {stage} не найден в {trip_dir} (искал {stage}_*.md)"
        )
    if len(candidates) > 1:
        # Берём первый, но предупреждаем — это edge case (повторный прогон Stage 2 → alt).
        print(
            f"предупреждение: найдено {len(candidates)} файла Stage {stage}; "
            f"использую {candidates[0].name}",
            file=sys.stderr,
        )
    return candidates[0]


def _version_sort_key(path: Path) -> int:
    """Извлечь число версии из имени `5_final_plan_v2.md`."""
    import re
    m = re.search(r"_v(\d+)\.md$", path.name)
    return int(m.group(1)) if m else 0


def _version_from_path(path: Path) -> int:
    """Версия из имени файла стадии (`..._v2.md` → 2; иначе 1)."""
    import re
    m = re.search(r"_v(\d+)(?:\.md)?$", path.stem + ".md")
    return int(m.group(1)) if m else 1


def _resolve_version(stage_path: Path, adapted: dict) -> int:
    """Строгое соответствие версии входа и выхода.

    Авторитет версии — `iteration` из frontmatter md (версия ПЛАНА), а не только
    имя входного файла. Если имя входа врёт (напр. `..._v1.md`, а `iteration: 5`)
    — громкое предупреждение, но выход именуется по СОДЕРЖИМОМУ (`_v5`), чтобы
    HTML/PDF строго соответствовал версии плана. Нет `iteration` → версия из имени.
    Это ловит кейс, когда экспорт-сессия подала не тот/переименованный md.
    """
    fname_v = _version_from_path(stage_path)
    fm = adapted.get("frontmatter") or {}
    content_v = fm.get("iteration")
    try:
        content_v = int(content_v)
    except (TypeError, ValueError):
        content_v = None
    if content_v is None:
        return fname_v
    if content_v != fname_v:
        print(
            f"⚠ ВЕРСИЯ: имя входного файла = v{fname_v}, но frontmatter "
            f"iteration = {content_v}. Выход именую v{content_v} (по содержимому — "
            f"строгое соответствие плану). Проверь имя входа: {stage_path.name}",
            file=sys.stderr,
        )
    return content_v


# ---------------------------------------------------------------------------
# HTML-движок (Claude Design) — новый презентационный слой
# ---------------------------------------------------------------------------


def _import_html_engine():
    """Импортировать пакет HTML-рендереров + html_lib (или None при сбое)."""
    try:
        if __package__ in (None, ""):
            from export import stages_html, html_lib  # type: ignore[no-redef]
        else:
            from . import stages_html, html_lib
        return stages_html, html_lib
    except Exception as e:  # noqa: BLE001 — отсутствие движка не фатально
        print(f"warning: HTML-движок недоступен ({e}); fallback на reportlab",
              file=sys.stderr)
        return None, None


def _html_to_pdf_request(html_lib, doc: str, html_path: Path, pdf_path: Path, *,
                         stage_id: str, recipient: str,
                         source_file: Path) -> "renderer.RenderRequest":
    """HTML→PDF: best-effort локальный chromium + handoff к core `pdf` skill.

    На платформе chromium может отсутствовать — тогда PDF собирает core `pdf`
    skill (server-side) из HTML-сайдкара; RenderRequest всегда несёт инструкцию.
    """
    engine = html_lib.pdf_engine_available()  # chromium/weasyprint/wkhtmltopdf или None
    local_ok, err = False, None
    try:
        html_lib.html_to_pdf(doc, pdf_path)
        local_ok = True
    except Exception as e:  # noqa: BLE001 — движок может отсутствовать
        err = str(e)
    if local_ok:
        # Сайдкар — чисто промежуточный файл конвертации; после успешного
        # локального PDF удаляем, чтобы не засорять trips/ (нужен он только
        # для handoff-ветки ниже, где конвертирует core `pdf` skill).
        try:
            html_path.unlink(missing_ok=True)
        except OSError:
            pass
        notes = [f"PDF собран движком «{engine}»: {pdf_path}."]
        print(f"PDF готов ({engine}): {pdf_path}", file=sys.stderr)
    else:
        notes = [
            "Движок HTML→PDF недоступен локально — конвертацию выполнит core "
            "`pdf` skill на платформе Claude.ai (server-side).",
            f"Отдать core pdf skill: {html_path} → {pdf_path}.",
            "После конвертации сайдкар *_print.html можно удалить.",
            f"(детали: {err})",
        ]
        print(f"HTML готов: {html_path} — PDF соберёт core pdf skill (server-side)",
              file=sys.stderr)
    return renderer.RenderRequest(
        format="pdf",
        output_path=str(pdf_path),
        content={"stage": stage_id, "engine": "html→pdf",
                 "pdf_engine": engine, "html_source": str(html_path),
                 "local_conversion": local_ok},
        metadata={"recipient": recipient, "source_file": str(source_file)},
        notes=notes,
    )


def _reportlab_available() -> bool:
    """Установлен ли reportlab — нативный движок PDF/DOCX.

    Импорт ленивый и защищённый: сам export.py обязан оставаться работоспособным
    без reportlab (режимы `--parse-only`, `--import`, HTML-экспорт)."""
    try:
        if __package__ in (None, ""):
            from export import pdf_lib  # type: ignore[no-redef]
        else:
            from . import pdf_lib
        return bool(pdf_lib.REPORTLAB_AVAILABLE)
    except Exception:  # noqa: BLE001 — отсутствие движка не должно ронять CLI
        return False


def _export_html_engine(stages_html, html_lib, adapted: dict, stage_id: str,
                        fmt: str, *, output_path: Path, recipient: str,
                        source_file: Path, write_request: str | None) -> int:
    """Рендер через HTML-движок: fmt=html → пишет .html; fmt=pdf → .html-сайдкар
    + HTML→PDF (локальный chromium best-effort, иначе handoff к core pdf skill).

    Сайдкар PDF-пути именуется `{stem}_print.html` — НЕ `{stem}.html`:
    иначе прогон `--format pdf` молча затирал настоящий HTML-экспорт
    (сайдкар — другой документ: alt-ориентация Stage 1, без edit-слоя
    Stage 3). При успешной локальной конвертации сайдкар удаляется; при
    handoff остаётся для core `pdf` skill. Панель travel.html фильтрует
    `_print.html` из файлов стадии.
    """
    html_path = (output_path if fmt == "html"
                 else output_path.with_name(output_path.stem + "_print.html"))
    # for_pdf → стадии с format-зависимой ориентацией (Stage 1) идут в landscape
    # для PDF и в портрет для HTML-экспорта.
    doc = stages_html.render_html(
        stage_id, adapted, html_path,
        recipient=recipient, source_file=source_file, for_pdf=(fmt == "pdf"),
    )
    if fmt == "html":
        request = renderer.RenderRequest(
            format="html",
            output_path=str(html_path),
            content={"stage": stage_id, "engine": "html"},
            metadata={"recipient": recipient, "source_file": str(source_file)},
            notes=["HTML self-contained (инлайн CSS + шрифты); открывается в браузере."],
        )
        print(f"HTML готов: {html_path}", file=sys.stderr)
    else:
        request = _html_to_pdf_request(
            html_lib, doc, html_path, output_path,
            stage_id=stage_id, recipient=recipient, source_file=source_file,
        )
    if write_request:
        renderer.write_request_to_disk(request, write_request)
    json.dump(request.to_dict(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


# ---------------------------------------------------------------------------
# Команды CLI
# ---------------------------------------------------------------------------


def cmd_export(args: argparse.Namespace) -> int:
    """Главная команда: распарсить → адаптировать → отдать на рендер."""
    travel_root = _resolve_travel_root(args.travel_root)

    # 1. Найти и распарсить файл стадии.
    if args.input:
        stage_path = Path(args.input).expanduser()
    else:
        stage_path = _find_stage_file(travel_root, args.trip, args.stage)
    parsed = parser.parse_stage_file(stage_path)
    if parsed["frontmatter_warnings"]:
        for w in parsed["frontmatter_warnings"]:
            print(f"frontmatter warning: {w}", file=sys.stderr)

    # 2. Адаптировать под получателя.
    adapted = adapter.adapt_for_recipient(parsed, args.recipient)

    # 2.5. Сверка --stage ↔ YAML: имя файла берётся из --stage, а контент из
    # артефакта. Если frontmatter объявляет stage и его лидирующая цифра ≠
    # --stage — это чужой артефакт под нужным именем (молчаливый баг). Падаем.
    declared_stage = (parsed.get("frontmatter") or {}).get("stage")
    if declared_stage is None:
        declared_stage = adapted.get("stage")
    if args.stage is not None and declared_stage is not None:
        declared_digit = str(declared_stage).lstrip()[:1]
        if declared_digit.isdigit() and declared_digit != str(args.stage):
            print(
                f"stage mismatch: --stage {args.stage}, но артефакт объявляет "
                f"stage={declared_stage!r} (лидирующая цифра {declared_digit}). "
                f"Проверь --stage и входной файл.",
                file=sys.stderr,
            )
            return 2

    # 3. Определить формат.
    fmt = args.format or DEFAULT_FORMAT.get(args.stage)
    if fmt is None:
        print(
            f"для Stage {args.stage} нет дефолтного формата экспорта; "
            f"укажи --format явно или выбери другую стадию",
            file=sys.stderr,
        )
        return 2

    # 4. Собрать имя файла-вывода.
    if args.stage == "6":
        # Финал Stage 6: `6_{trip_id}_финал_v{N}.pdf` (план + карта + досье).
        trip_id = adapted.get("trip_id") or (args.trip or "поездка")
        version = _resolve_version(stage_path, adapted)
        output_name = file_naming.build_final_filename(
            trip_id, version=version, ext=fmt, recipient=args.recipient,
        )
    elif args.stage == "5":
        # Финальный план: `{trip_id}_план_v{N}.pdf` (страна_год-месяц_план_версия).
        trip_id = adapted.get("trip_id") or (args.trip or "поездка")
        version = _resolve_version(stage_path, adapted)
        output_name = file_naming.build_final_plan_filename(
            trip_id, version=version, ext=fmt, recipient=args.recipient,
        )
    elif args.stage == "4":
        # Витрина вариантов: `{trip_id}_варианты_v{N}.pdf`.
        trip_id = adapted.get("trip_id") or (args.trip or "поездка")
        version = _resolve_version(stage_path, adapted)
        output_name = file_naming.build_variants_filename(
            trip_id, version=version, ext=fmt, recipient=args.recipient,
        )
    elif args.stage == "0":
        # Витрина регионов: `{trip_id}_регионы.pdf` (без версии — Stage 0
        # артефакт один per trip, см. storage-and-naming.md §2.1).
        trip_id = adapted.get("trip_id") or (args.trip or "поездка")
        output_name = file_naming.build_scope_filename(
            trip_id, ext=fmt, recipient=args.recipient,
        )
    elif args.stage == "1":
        # DR-база отчётов: `{trip_id}_dr_отчёты.pdf` (без версии — Stage 1
        # артефакт один per trip, перепрогон DR переписывает).
        trip_id = adapted.get("trip_id") or (args.trip or "поездка")
        output_name = file_naming.build_dr_reports_filename(
            trip_id, ext=fmt, recipient=args.recipient,
        )
    elif args.stage == "2":
        # Витрина similarity: `{trip_id}_фильтр_авторов.pdf` (default) или
        # `.html` (интерактивный lookup). Без версии — артефакт один per trip.
        trip_id = adapted.get("trip_id") or (args.trip or "поездка")
        output_name = file_naming.build_similarity_filename(
            trip_id, ext=fmt, recipient=args.recipient,
        )
    elif args.stage == "3":
        # Витрина POI: `{trip_id}_места.docx` (default) или `.pdf`
        # (без версии — Stage 3 артефакт один per trip).
        trip_id = adapted.get("trip_id") or (args.trip or "поездка")
        output_name = file_naming.build_poi_filename(
            trip_id, ext=fmt, recipient=args.recipient,
        )
    else:
        output_name = file_naming.build_export_filename(
            stage=args.stage, ext=fmt, recipient=args.recipient,
        )
    output_path = (
        Path(args.output_dir).expanduser() if args.output_dir
        else stage_path.parent
    ) / output_name

    stage_id = adapted.get("stage") or f"{args.stage}_stage"

    # 5. HTML-движок (Claude Design) — новый презентационный слой.
    #    Перехватывает html и pdf (через HTML→PDF), кроме пар из DEFAULT_ENGINE
    #    (PDF Stage 6 — нативный reportlab). reportlab обслуживает ещё и форматы
    #    без HTML-аналога (docx). Явный `--engine` перекрывает дефолт в обе
    #    стороны: `--engine html` вернёт Stage 6 на HTML→PDF.
    #    Исключение (Р4): Stage 2 `--format html` → интерактивный lookup из
    #    reportlab-registry (тёмная тема, фильтры/сортировка/expand), а НЕ
    #    статичная Claude-Design-витрина (та — только внутренний этап PDF-пути).
    stage2_interactive = (str(args.stage) == "2" and fmt == "html")
    engine = args.engine or DEFAULT_ENGINE.get((str(args.stage), fmt), "html")
    # Дефолт reportlab не должен оставлять пользователя вообще без PDF там, где
    # раньше он собирался: reportlab — внешняя зависимость. Проверяем именно её
    # наличие, а НЕ регистрацию renderer'а: renderer регистрируется в любом
    # случае и падает уже внутри, RuntimeError'ом на середине экспорта.
    # Откат молчаливым не делаем — типографика хуже, пользователь должен знать.
    # Явный `--engine reportlab` не трогаем: его просили осознанно, и честный
    # отказ полезнее тихой подмены движка.
    if engine == "reportlab" and args.engine is None and not _reportlab_available():
        print(f"warning: reportlab не установлен — ({stage_id}, {fmt}) собираю "
              f"через HTML→PDF. Нативный печатный рендер: "
              f"pip install reportlab --break-system-packages", file=sys.stderr)
        engine = "html"
    if engine == "html" and fmt in ("html", "pdf") and not stage2_interactive:
        stages_html, html_lib = _import_html_engine()
        if stages_html is not None and stages_html.has_builder(stage_id):
            return _export_html_engine(
                stages_html, html_lib, adapted, stage_id, fmt,
                output_path=output_path, recipient=args.recipient,
                source_file=stage_path, write_request=args.write_request,
            )
        if fmt == "html":
            print(f"warning: нет HTML-рендерера для стадии {stage_id}; "
                  f"пробую reportlab-registry", file=sys.stderr)
        # Иначе (pdf без html-билдера) — проваливаемся в reportlab ниже.

    # 6. Найти зарегистрированный stage-renderer (reportlab / core skill).
    render_fn = renderer.get_renderer(stage_id, fmt)
    if render_fn is None:
        # Step 1: renderer'ов ещё нет. Готовим payload и выводим в stdout.
        request = renderer.RenderRequest(
            format=fmt,
            output_path=str(output_path),
            content={"parsed": adapted},
            metadata={
                "trip_id":   adapted.get("trip_id"),
                "stage":     adapted.get("stage"),
                "recipient": args.recipient,
                "source_file": str(stage_path),
            },
            notes=[
                f"Renderer для ({stage_id}, {fmt}) пока не зарегистрирован — "
                f"это нормально для Step 1 (engine). Stage-модуль (Step 2+) "
                f"подключит свой renderer и сгенерирует {fmt.upper()}.",
            ],
        )
        if args.write_request:
            renderer.write_request_to_disk(request, args.write_request)
            print(f"render-request записан: {args.write_request}", file=sys.stderr)
        json.dump(request.to_dict(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    # Renderer найден — вызываем.
    request = render_fn(
        adapted, recipient=args.recipient, output_path=output_path,
        source_file=stage_path,
    )
    if args.write_request:
        renderer.write_request_to_disk(request, args.write_request)
    print(f"render-request готов: {output_path}", file=sys.stderr)
    json.dump(request.to_dict(), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


# Обратный маппинг описания → stage (для round-trip import):
# `3_{trip_id}_места.docx` → «места» → "3".
_WHAT_TO_STAGE = {v: k for k, v in file_naming.DEFAULT_NAMES.items()}


def _identify_import(src: Path, trip_arg: str | None) -> tuple[str, str] | None:
    """По имени заполненного файла определить (stage_short, trip_id).

    Единый формат: `{stage}_{trip_id}_{описание}.{ext}` (например
    `3_камбоджа_лаос_2026-02_места.docx`). Описание может быть многословным
    (`dr_отчёты`, `похожие_авторы`, `финальный_план`), поэтому матчим его
    как суффикс из известного набора, а не отрезаем последний сегмент.
    Лидирующий `{stage}_` снимаем; остаток без описания — это trip_id.
    Совместимо со старым форматом без stage-префикса.
    """
    import re as _re
    stem = src.stem
    body = stem
    m = _re.match(r"^(\d)_(.+)$", stem)
    if m:
        body = m.group(2)
    for what, stage in _WHAT_TO_STAGE.items():
        suffix = "_" + what
        if body.endswith(suffix):
            trip_id = body[: -len(suffix)]
            if trip_id:
                return stage, (trip_arg or trip_id)
    return None


def _find_stage_md(src: Path, stage: str, travel_root: Path,
                   trip_id: str) -> Path | None:
    """Найти исходный md стадии: сначала рядом с заполненным файлом,
    потом в trips/{trip_id}/."""
    patterns = {
        # `3_poi_pool` — текущее имя; `3_poi_aggregation` — legacy v0.22.
        "3": ["3_poi_pool*.md", "3_poi_aggregation*.md"],
    }
    pats = patterns.get(stage, [f"{stage}_*.md"])
    for base in (src.parent, travel_root / "trips" / trip_id):
        for pat in pats:
            hits = sorted(p for p in base.glob(pat)
                          if not p.stem.endswith("_места"))
            if hits:
                return hits[0]
    return None


def cmd_import(args: argparse.Namespace) -> int:
    """Round-trip import: заполненный DOCX → обновить исходный stage-md.

    Реализован для Stage 3 (`{trip_id}_места.docx` → `3_poi_aggregation.md`):
    извлекает проставленные теги регионов и комментарии POI, обновляет md
    inplace. Прочие стадии — пока не поддержаны (round-trip не нужен).
    """
    src = Path(args.import_path).expanduser()
    if not src.exists():
        print(f"файл не найден: {src}", file=sys.stderr)
        return 2

    ident = _identify_import(src, args.trip)
    if ident is None:
        print(f"не удалось определить стадию по имени {src.name!r}; "
              f"ожидается `{{trip_id}}_места.docx` для Stage 3", file=sys.stderr)
        return 1
    stage, trip_id = ident

    if stage != "3":
        print(f"import для Stage {stage} пока не реализован "
              f"(round-trip есть только у Stage 3)", file=sys.stderr)
        return 1

    if src.suffix.lower() != ".docx":
        print(f"import Stage 3 принимает только DOCX, получен {src.suffix}",
              file=sys.stderr)
        return 1

    travel_root = _resolve_travel_root(args.travel_root)
    md_path = _find_stage_md(src, stage, travel_root, trip_id)
    if md_path is None:
        print(f"исходный 3_poi_pool*.md (или legacy 3_poi_aggregation*.md) "
              f"не найден рядом с {src.name} и в trips/{trip_id}/; "
              f"укажи --output-dir или положи рядом",
              file=sys.stderr)
        return 2

    if __package__ in (None, ""):
        from export.stages import stage3  # type: ignore[no-redef]
    else:
        from .stages import stage3
    result = stage3.import_docx(src, md_path)

    for w in result["warnings"]:
        print(f"warning: {w}", file=sys.stderr)
    print(
        f"Stage 3 импортирован в {md_path.name}: "
        f"{result['tags_applied']} тег(ов), "
        f"{result['comments_applied']} комментари(ев)",
        file=sys.stderr,
    )
    json.dump(
        {
            "stage":            stage,
            "trip_id":          trip_id,
            "md_updated":       str(md_path),
            "tags_applied":     result["tags_applied"],
            "comments_applied": result["comments_applied"],
            "warnings":         result["warnings"],
        },
        sys.stdout, ensure_ascii=False, indent=2,
    )
    sys.stdout.write("\n")
    return 0


def cmd_parse_only(args: argparse.Namespace) -> int:
    """Debug: распарсить файл стадии и вывести результат как JSON."""
    src = Path(args.parse_only).expanduser()
    parsed = parser.parse_stage_file(src)
    # Сокращаем body в выводе, чтобы JSON не разрастался.
    def _trim(d: dict) -> dict:
        out = dict(d)
        if isinstance(out.get("body"), str) and len(out["body"]) > 200:
            out["body"] = out["body"][:200] + f"... [+{len(out['body']) - 200} chars]"
        return out
    summary = _trim(parsed)
    summary["sections"] = [
        {
            **_trim(s),
            "subsections": [_trim(ss) for ss in s["subsections"]],
        }
        for s in summary["sections"]
    ]
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="export.py",
        description="Движок экспорта travel-planning (HTML/PDF/DOCX; "
                    "движок по умолчанию — html, у PDF Stage 6 — reportlab).",
    )
    p.add_argument("--stage", choices=["0", "1", "2", "3", "4", "5", "6"],
                   help="номер стадии для экспорта")
    p.add_argument("--trip", help="trip_id (русскими, как в storage)")
    p.add_argument("--recipient", default="self",
                   choices=adapter.list_recipients(),
                   help="получатель (по умолчанию self)")
    # pptx/xlsx рендереров нет — их принятие давало «успешный» JSON без файла.
    p.add_argument("--format", choices=["html", "pdf", "docx"],
                   help="формат вывода (по умолчанию HTML; PDF/DOCX по запросу)")
    p.add_argument("--engine", choices=["html", "reportlab"], default=None,
                   help="движок презентации: html (Claude Design; для pdf — "
                        "HTML→PDF) | reportlab (нативный PDF/DOCX). По "
                        "умолчанию html везде, кроме PDF Stage 6 — там "
                        "reportlab (дорожный документ: номера страниц, "
                        "колонтитул, независимость от конвертера)")
    p.add_argument("--input", help="явный путь к файлу стадии (вместо поиска по trip)")
    p.add_argument("--output-dir", help="куда положить экспорт (по умолчанию — папка стадии)")
    p.add_argument("--travel-root", help="переопределить корень хранилища")
    p.add_argument("--write-request", help="сохранить render-request как JSON по этому пути")
    p.add_argument("--import", dest="import_path",
                   help="round-trip: загрузить заполненный DOCX и обновить stage-md")
    p.add_argument("--parse-only", help="debug: распарсить файл и вывести JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.parse_only:
        return cmd_parse_only(args)
    if args.import_path:
        # --trip опционален: trip_id выводится из имени файла
        # (`{trip_id}_места.docx`); --trip переопределяет при необходимости.
        return cmd_import(args)
    if args.stage:
        if not args.trip and not args.input:
            print("--stage требует либо --trip, либо --input", file=sys.stderr)
            return 2
        return cmd_export(args)

    _build_parser().print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
