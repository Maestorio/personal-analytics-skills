#!/usr/bin/env python3
"""Регрессионные тесты для Stage 4 PDF builder (варианты маршрута).

Покрывают:
  - markdown-хелперы: split_md_blocks, table-detect, bullets
  - extract_content: варианты, сравнительная таблица, свёрнутый Priority pool
  - render_md_body: warning-блок (⚠️ бюджет), таблица, bullets
  - build_pdf: фактическая генерация PDF (требует reportlab)
  - решение НЕ рендерится; back-link и навигация присутствуют
  - CLI integration: export.py --stage 4 → имя {trip_id}_варианты_v{N}.pdf
  - file_naming.build_variants_filename

Запуск из корня репозитория:
    python3 skills/travel-planning/tests/test_export_stage4.py

PDF/CLI тесты пропускаются, если reportlab не установлен.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPORT_DIR = REPO_ROOT / "skills" / "travel-planning" / "scripts" / "export"
# Фикстура: в папке «вьетнам» лежит реальный Stage 4 поездки аргентина_юг.
ARG_STAGE4 = REPO_ROOT / "docs" / "travel-planning" / "calibration" / "вьетнам" / "4_variants.md"
# Старый формат Stage 4 (Variant A — …, «Сравнение», CONTESTED-секции).
KLT_STAGE4 = REPO_ROOT / "docs" / "travel-planning" / "calibration" / "КЛТ_1" / "4_variants_v1.md"

sys.path.insert(0, str(EXPORT_DIR.parent))
from export import parser, adapter, file_naming  # noqa: E402
from export.stages import stage4                 # noqa: E402

try:
    from export import pdf_lib       # noqa: E402
    REPORTLAB_OK = pdf_lib.REPORTLAB_AVAILABLE
except Exception:
    pdf_lib = None  # type: ignore
    REPORTLAB_OK = False


checks_run = 0
checks_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    if condition:
        print(f"  ✓ {name}")
    else:
        checks_failed += 1
        suffix = f" — {detail}" if detail else ""
        print(f"  ✗ {name}{suffix}")


def skip(name: str, reason: str) -> None:
    print(f"  ⊘ {name} (skip: {reason})")


# ─── 1. markdown helpers ──────────────────────────────────────────────────


def test_md_helpers():
    print("\n[1] markdown helpers")

    blocks = stage4._split_md_blocks("a\nb\n\nc\n\n\nd")
    check("3 блока по пустым строкам", len(blocks) == 3, f"got {len(blocks)}")

    tbl_block = ["| A | B |", "|---|---|", "| 1 | 2 |", "| 3 | 4 |"]
    check("распознаёт GFM-таблицу", stage4._is_table_block(tbl_block))
    rows = stage4._table_rows(tbl_block)
    check("таблица: header + 2 ряда", len(rows) == 3, f"got {len(rows)}")
    check("разделитель выкинут", rows[0] == ["A", "B"])

    bul = ["- один", "- два", "  продолжение", "- три"]
    check("bullet-блок распознан", stage4._is_bullet_block(bul))
    items = stage4._parse_bullets(bul)
    check("3 bullet'а, continuation склеен", len(items) == 3 and "продолжение" in items[1],
          f"got {items}")

    check("первая таблица из body",
          stage4._extract_first_table("текст\n\n| X | Y |\n|---|---|\n| a | b |")
          == [["X", "Y"], ["a", "b"]])


# ─── 2. extract_content на фикстуре Аргентины ─────────────────────────────


def test_extract_content():
    print("\n[2] extract_content — Argentina fixture")

    if not ARG_STAGE4.exists():
        skip("fixture", f"нет {ARG_STAGE4}")
        return

    parsed = parser.parse_stage_file(ARG_STAGE4)
    ex = stage4.extract_content(parsed)

    check("cover.trip_id", ex["cover"]["trip_id"] == "аргентина_юг_2025-03",
          f"got {ex['cover']['trip_id']!r}")
    check("cover.duration_nights = 13", ex["cover"]["duration_nights"] == 13)
    check("cover.variants_count = 3", ex["cover"]["variants_count"] == 3)
    check("recommended_balanced = вариант_а",
          ex["cover"]["recommended_balanced"] == "вариант_а")

    check("context есть", ex["context"] and len(ex["context"]) > 100)
    check("warnings собраны (>=5)", len(ex["warnings"]) >= 5, f"got {len(ex['warnings'])}")

    # 3 варианта, метки A/B/C.
    check("3 варианта", len(ex["variants"]) == 3, f"got {len(ex['variants'])}")
    letters = [v.letter for v in ex["variants"]]
    check("метки A/B/C", letters == ["A", "B", "C"], f"got {letters}")
    check("у варианта A есть заголовок",
          ex["variants"][0].title.startswith("Сбалансированное"),
          f"got {ex['variants'][0].title!r}")
    # Интро варианта содержит бюджетный ⚠️-блок.
    check("интро варианта A — бюджетный ⚠ блок", "Бюджет" in ex["variants"][0].intro)
    # Подсекции варианта: Маршрут по дням + ещё.
    sub_heads = [s["heading"] for s in ex["variants"][0].subsections]
    check("вариант A: подсекция «Маршрут по дням ...»",
          any(h.startswith("Маршрут по дням") for h in sub_heads), f"got {sub_heads}")
    check("вариант A: подсекция «Кому подходит ...»",
          any("Кому подходит" in h for h in sub_heads), f"got {sub_heads}")

    # Сравнительная таблица: 1 ось-колонка + 3 варианта.
    check("comparison_rows извлечена", ex["comparison_rows"] is not None)
    if ex["comparison_rows"]:
        check("comparison: 4 колонки (Ось+A+B+C)",
              len(ex["comparison_rows"][0]) == 4, f"got {len(ex['comparison_rows'][0])}")

    # Priority pool свёрнут в корзины.
    labels = [b.label for b in ex["priority_buckets"]]
    check("priority: есть «Обязательно ...»",
          any(l.startswith("Обязательно") for l in labels), f"got {labels}")
    check("priority: есть «Исключено»",
          any(l == "Исключено" for l in labels), f"got {labels}")
    must = next((b for b in ex["priority_buckets"] if b.label.startswith("Обязательно")), None)
    check("MUST содержит имена POI", bool(must and must.names),
          f"names: {must.names if must else None}")

    check("honest assessment есть", ex["honest"] and "сбалансиров" in ex["honest"].lower())


def test_decision_not_rendered():
    print("\n[2b] блок «Решение» не извлекается")
    if not ARG_STAGE4.exists():
        skip("fixture", "нет файла")
        return
    parsed = parser.parse_stage_file(ARG_STAGE4)
    ex = stage4.extract_content(parsed)
    # «Решение» не должно попасть ни в варианты, ни в honest.
    var_titles = [v.title for v in ex["variants"]]
    check("Решение не стало вариантом",
          all("ЗАПОЛНЯЕТСЯ" not in (ex["honest"] or "") for _ in [0])
          and not any("Решение" in t for t in var_titles))


# ─── 3. variant display + filename ────────────────────────────────────────


def test_legacy_format_klt():
    print("\n[2c] extract_content — legacy format (КЛТ_1)")
    if not KLT_STAGE4.exists():
        skip("КЛТ_1 fixture", f"нет {KLT_STAGE4}")
        return
    parsed = parser.parse_stage_file(KLT_STAGE4)
    ex = stage4.extract_content(parsed)
    # «Variant A — …» (латиница, тире) должны распознаться.
    check("3 варианта (legacy Variant A — …)", len(ex["variants"]) == 3,
          f"got {len(ex['variants'])}: {[v.letter for v in ex['variants']]}")
    check("заголовок варианта A извлечён",
          bool(ex["variants"] and ex["variants"][0].title), )
    # «Сравнение» (а не «Сравнительная таблица») как comparison.
    check("comparison из «Сравнение»", ex["comparison_rows"] is not None)
    # CONTESTED / «Что не вошло» — в extras (graceful passthrough).
    extra_heads = [e["heading"] for e in ex["extras"]]
    check("extras содержит CONTESTED/«Что не вошло»",
          any("CONTESTED" in h or "не вошло" in h.lower() for h in extra_heads),
          f"got {extra_heads}")
    # Pipeline-шум подавлен.
    check("Tags resolution / Trip parameters НЕ в extras",
          not any(h in ("Tags resolution", "Trip parameters", "Следующий шаг")
                  for h in extra_heads), f"got {extra_heads}")


def test_cover_helpers():
    print("\n[2d] cover-хелперы (русификация/параметры/сезон)")
    check("Variant A → Вариант A", stage4._ru_variant_label("Variant A") == "Вариант A")
    check("Вариант Б без изменений", stage4._ru_variant_label("Вариант Б") == "Вариант Б")
    check("ось-колонка не трогается", stage4._ru_variant_label("Ось") == "Ось")

    check("CONTESTED → Спорные",
          stage4._normalize_heading("CONTESTED решения") == "Спорные решения")
    # Фаза 1: идемпотентность — уже русский заголовок не корёжится.
    check("идемпотентность: «Спорные решения» не меняется",
          stage4._normalize_heading("Спорные решения") == "Спорные решения")
    check("variant → вариант",
          "вариант" in stage4._normalize_heading("Что НЕ вошло ни в один variant").lower()
          and "variant" not in stage4._normalize_heading("Что НЕ вошло ни в один variant"))

    season = stage4._season_from_trip_id("камбоджа_лаос_2026-02")
    check("сезон из trip_id", season == "февраль 2026", f"got {season!r}")
    regions = stage4._humanize_regions("камбоджа_лаос_2026-02")
    check("регионы из trip_id", regions == "Камбоджа, Лаос", f"got {regions!r}")

    tp = stage4._parse_trip_marker(
        "x\n[[поездка: группа: Соло | регионы: Камбоджа → Лаос | темп: размеренный]]\ny"
    )
    check("trip-маркер: группа", tp.get("группа") == "Соло")
    check("trip-маркер: регионы", tp.get("регионы") == "Камбоджа → Лаос")
    check("trip-маркер: темп", tp.get("темп") == "размеренный")

    # _cover_title: pipeline-H1 → собран; чистый H1 → как есть.
    ex_dirty = {"title": "Stage 4 — Варианты маршрута: камбоджа_лаос_2026-02",
                "cover": {"trip_id": "камбоджа_лаос_2026-02", "duration_nights": 18},
                "trip_params": {}}
    t = stage4._cover_title(ex_dirty)
    check("pipeline-H1 заменён на собранный (регионы + «сравнение вариантов», БЕЗ ночей)",
          "Stage" not in t and "сравнение вариантов" in t and "ночей" not in t
          and "Камбоджа" in t, f"got {t!r}")
    ex_clean = {"title": "Камбоджа и Лаос · 18 ночей · сравнение вариантов",
                "cover": {}, "trip_params": {}}
    check("чистый H1 оставлен как есть",
          stage4._cover_title(ex_clean) == ex_clean["title"])


def test_linkify_variants():
    print("\n[2f] линкификация «Вариант X»")
    stage4._set_variant_link_map({"A": "variant-1", "B": "variant-2", "C": "variant-3"})
    try:
        t = stage4._linkify_variants("В варианте B нет Мартильо; см. также Variant C.")
        check("«варианте B» → [варианте B](#variant-2)",
              "[варианте B](#variant-2)" in t, f"got {t!r}")
        check("«Variant C» русифицировано в тексте ссылки",
              "[Вариант C](#variant-3)" in t and "[Variant C]" not in t, f"got {t!r}")
        # «variant» (нижний регистр) → «вариант».
        t_low = stage4._linkify_variants("Когда выбирать variant A.")
        check("«variant A» → [вариант A](#variant-1)",
              "[вариант A](#variant-1)" in t_low, f"got {t_low!r}")
        # Существующая markdown-ссылка не трогается.
        t2 = stage4._linkify_variants("См. [Вариант A](#variant-1) и вариант B.")
        check("уже существующая ссылка не двойная",
              t2.count("[Вариант A](#variant-1)") == 1
              and "[вариант B](#variant-2)" in t2, f"got {t2!r}")
        # Code-спан не трогаем.
        t3 = stage4._linkify_variants("`Вариант A` — это код, а в варианте B — нет.")
        check("code-спан не линкуется",
              "`Вариант A`" in t3 and "[варианте B](#variant-2)" in t3, f"got {t3!r}")
        # Несуществующая буква — не трогаем.
        t4 = stage4._linkify_variants("Вариант Z вообще не существует.")
        check("Z не в карте — не ссылка", "Вариант Z вообще" in t4 and "](#" not in t4)
    finally:
        stage4._clear_variant_link_map()


def test_start_finish_collapse():
    print("\n[2g] старт == финиш → одна строка")
    # Прямая проверка через build_pdf на in-memory extracted минимально.
    if not REPORTLAB_OK:
        skip("start/finish PDF", "reportlab не установлен")
        return
    ex = {
        "title": None, "cover": {"trip_id": "test_2025-03", "duration_nights": 7},
        "frontmatter": {}, "warnings": [],
        "trip_params": {"группа": "Алексей", "старт": "Сеул", "финиш": "Сеул"},
        "context": None, "priority_buckets": [],
        "comparison_rows": None, "variants": [], "extras": [], "honest": None,
    }
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "x.pdf"
        stage4.build_pdf(ex, out, recipient="self")
        # Текст PDF: найти строку «Старт и финиш» с одним городом.
        from pypdf import PdfReader
        txt = "\n".join((p.extract_text() or "") for p in PdfReader(str(out)).pages)
        # Метки паспорта рендерятся uppercase (дизайн-язык .passport) —
        # сверяем регистронезависимо.
        check("'Старт и финиш' (один город) в выводе",
              "старт и финиш" in txt.lower(), txt[:300])
        check("'Сеул → Сеул' (дубль) НЕ выводится",
              "Сеул → Сеул" not in txt)

    # Разные города — ожидаем «X → Y».
    ex2 = dict(ex, trip_params={"старт": "Пномпень", "финиш": "Луангпрабанг"})
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "y.pdf"
        stage4.build_pdf(ex2, out, recipient="self")
        from pypdf import PdfReader
        txt = "\n".join((p.extract_text() or "") for p in PdfReader(str(out)).pages)
        check("разные → «Старт / финиш: X → Y»",
              "Пномпень" in txt and "Луангпрабанг" in txt and "→" in txt)


def test_context_dedup():
    print("\n[2e] контекст без дублей таблицы параметров")
    ctx = (
        "- **Поездка:** Камбоджа + Лаос, 18 ночей, февраль 2026, один человек.\n"
        "- **Темп:** профильный slow (3–4 ночи/регион).\n"
        "- **Жёсткое ограничение:** прав на вождение нет → общественный транспорт.\n"
        "  мотопетли — только авто с водителем.\n"
        "- **Теги пользователя:** обязательно — Луангпрабанг."
    )
    res = stage4._strip_dup_context(ctx)
    check("«Поездка» (маршрут/18 ночей) вырезана", "Камбоджа + Лаос" not in res, res[:80])
    check("«Темп» вырезан", "профильный slow" not in res)
    check("«Жёсткое ограничение» сохранено", "вождение нет" in res)
    check("continuation сохранённого пункта на месте", "авто с водителем" in res)
    check("«Теги пользователя» сохранены", "Луангпрабанг" in res)
    # Прозовый контекст (без bullets) не трогаем.
    prose = "Поездка соло, 13 ночей, март 2025. Ландшафтная фотография."
    check("прозовый контекст без изменений", stage4._strip_dup_context(prose) == prose)


def test_variant_display_and_naming():
    print("\n[3] _variant_display + build_variants_filename")
    check("вариант_а → Вариант А", stage4._variant_display("вариант_а") == "Вариант А")
    check("A → Вариант A", stage4._variant_display("A") == "Вариант A")

    fn = file_naming.build_variants_filename("аргентина_юг_2025-03", version=2)
    check("имя витрины вариантов",
          fn == "4_аргентина_юг_2025-03_варианты_v2.pdf", f"got {fn}")
    fn_self = file_naming.build_trip_doc_filename("корея_2024-03", "план", version=1)
    check("generic helper для плана",
          fn_self == "корея_2024-03_план_v1.pdf", f"got {fn_self}")


# ─── 4. build_pdf ─────────────────────────────────────────────────────────


def test_build_pdf():
    print("\n[4] build_pdf на фикстуре (no exception)")
    if not REPORTLAB_OK:
        skip("build_pdf", "reportlab не установлен")
        return
    if not ARG_STAGE4.exists():
        skip("build_pdf", f"нет fixture {ARG_STAGE4}")
        return

    parsed = parser.parse_stage_file(ARG_STAGE4)
    adapted = adapter.adapt_for_recipient(parsed, "self")
    ex = stage4.extract_content(adapted)

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "variants.pdf"
        try:
            stage4.build_pdf(ex, out, recipient="self")
        except Exception as e:
            check("build_pdf не падает", False, repr(e))
            return
        check("PDF создан", out.exists())
        check("PDF не пустой (>10KB)", out.stat().st_size > 10_000,
              f"size: {out.stat().st_size}")


# ─── 5. CLI integration ───────────────────────────────────────────────────


def test_cli_integration():
    print("\n[5] CLI integration: export.py --stage 4")
    if not REPORTLAB_OK:
        skip("CLI integration", "reportlab не установлен")
        return
    if not ARG_STAGE4.exists():
        skip("CLI integration", f"нет fixture {ARG_STAGE4}")
        return

    with tempfile.TemporaryDirectory() as tmp:
        trip_dir = Path(tmp) / "trips" / "тест_2025-01"
        trip_dir.mkdir(parents=True)
        (trip_dir / "4_variants_v1.md").write_text(
            ARG_STAGE4.read_text(encoding="utf-8"), encoding="utf-8"
        )
        result = subprocess.run(
            [sys.executable, str(EXPORT_DIR / "export.py"),
             "--stage", "4", "--trip", "тест_2025-01",
             "--recipient", "self", "--travel-root", tmp,
             "--format", "pdf"],   # дефолт экспорта с 2026-07-04 — html; тест про PDF-путь
            capture_output=True, text=True, timeout=60,
        )
        check("CLI exit 0", result.returncode == 0, f"stderr: {result.stderr[-300:]!r}")
        try:
            out = json.loads(result.stdout)
        except json.JSONDecodeError:
            check("вывод — валидный JSON", False, result.stdout[:200])
            return
        check("RenderRequest format=pdf", out.get("format") == "pdf")
        pdf_path = Path(out["output_path"])
        check("PDF создан", pdf_path.exists())
        check("имя {trip_id}_варианты_v{N}.pdf",
              pdf_path.name == "4_аргентина_юг_2025-03_варианты_v1.pdf",
              f"got {pdf_path.name}")


def test_field_line_params():
    """P2-аудит: блок параметров варианта `**Label:** value` — каждая строка
    отдельным абзацем, не склеивается в один (markdown soft-wrap иначе сливает)."""
    print("\n[P2] параметры варианта — построчно")
    check("FIELD_LINE_RE матчит '**Регионы:** …'",
          bool(stage4._FIELD_LINE_RE.match("**Регионы:** Ханой → Сапа")))
    check("FIELD_LINE_RE матчит пустой caption '**Transport:**'",
          bool(stage4._FIELD_LINE_RE.match("**Transport:**")))
    check("FIELD_LINE_RE не матчит обычный абзац",
          not stage4._FIELD_LINE_RE.match("Обычный абзац текста без лейбла"))
    if not REPORTLAB_OK:
        skip("render field-строк", "reportlab не установлен")
        return
    pdf_lib.register_fonts()
    styles = pdf_lib.get_styles()
    story: list = []
    block = ("**Регионы:** Ханой → Сапа\n**Темп:** медленный\n"
             "**Ценовой уровень:** $\n**Транспорт:**")
    stage4.render_md_body(story, block, styles)
    check("4 field-строки → ≥4 отдельных flowable (не склеены)",
          len(story) >= 4, f"got {len(story)}")


def test_cover_cosmetic():
    """Косметика обложки: гео-квалификатор стороны света → прилагательное,
    имя участника с заглавной + ё."""
    print("\n[P2c] косметика обложки (гео + имя)")
    CC = stage4.cover_common
    check("вьетнам_север → «Северный Вьетнам» (не «Вьетнам + Север»)",
          CC.humanize_trip_geo("вьетнам_север_2026-09", join=" + ")
          == "Северный Вьетнам")
    check("аргентина_юг → «Южная Аргентина» (согласование рода)",
          CC.humanize_trip_geo("аргентина_юг_2025-03") == "Южная Аргентина")
    check("камбоджа_лаос → «Камбоджа + Лаос» (две страны, без квалификатора)",
          CC.humanize_trip_geo("камбоджа_лаос_2026-02", join=" + ")
          == "Камбоджа + Лаос")
    check("профиль алексей_мария → «Алексей и Мария» (каждое имя + ё)",
          CC.profile_name("profiles/алексей_мария.md") == "Алексей и Мария")
    check("профиль алексей → «Алексей»",
          CC.profile_name("profiles/алексей.md") == "Алексей")


# ─── runner ────────────────────────────────────────────────────────────────


def main() -> int:
    test_md_helpers()
    test_extract_content()
    test_decision_not_rendered()
    test_legacy_format_klt()
    test_cover_helpers()
    test_linkify_variants()
    test_start_finish_collapse()
    test_context_dedup()
    test_variant_display_and_naming()
    test_field_line_params()
    test_cover_cosmetic()
    test_build_pdf()
    test_cli_integration()

    print(f"\n{'=' * 60}")
    print(f"Всего проверок: {checks_run}, провалов: {checks_failed}")
    return 0 if checks_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
