#!/usr/bin/env python3
"""Регрессионные тесты для Stage 0 PDF builder (витрина регионов).

Покрывают:
  - polish-маркеры: _parse_trip_marker, _parse_region_markers
  - role helpers: _normalize_role, _infer_role_from_longlist_item, _resolve_role
  - body extraction: _extract_description_and_season, _find_subsection
  - extract_content на legacy фикстуре КЛТ_1 (Region universe по странам,
    role в YAML отсутствует)
  - cover helpers: _humanize_regions, _season_from_trip_id, _cover_title,
    _cover_subtitle, _cover_key_params
  - season chip: _season_chip (короткий tag из длинного note)
  - card grouping: _group_by_role, _order_with_reserves
  - file_naming.build_scope_filename (без версии)
  - build_pdf: фактическая генерация PDF (требует reportlab)
  - CLI integration: export.py --stage 0 → {trip_id}_регионы.pdf

Запуск из корня репозитория:
    python3 skills/travel-planning/tests/test_export_stage0.py

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
# Фикстура: реальный артефакт Stage 0 v2 из КЛТ-валидации (Камбоджа+Лаос).
KLT_STAGE0 = REPO_ROOT / "docs" / "travel-planning" / "calibration" / "КЛТ_1" / "0_scope_opus.md"

sys.path.insert(0, str(EXPORT_DIR.parent))
from export import parser, adapter, file_naming  # noqa: E402
from export.stages import stage0                 # noqa: E402

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


# ─── 1. polish-маркеры ─────────────────────────────────────────────────────


def test_polish_markers():
    print("\n[1] polish-маркеры [[поездка: …]] и [[регион: …]]")

    body = (
        "[[поездка: группа: Алексей | регионы: Камбоджа → Лаос | "
        "сезон: февраль 2026 | темп: размеренный]]\n\n"
        "## Контекст\n\n"
        "[[регион: имя: Сием-Рип и Ангкор | role: core | density: HIGH | "
        "сезон: ok | ночи: 3-5]]\n"
        "### Сием-Рип и Ангкор\nКрупнейший ансамбль.\n\n"
        "[[регион: имя: Луангпрабанг | role: core | density: HIGH | "
        "сезон: risk | ночи: 3-4]]\n"
        "### Луангпрабанг\nUNESCO.\n"
    )

    trip = stage0._parse_trip_marker(body)
    check("trip marker: 4 ключа", len(trip) == 4, f"got {trip}")
    check("trip marker: группа", trip.get("группа") == "Алексей")
    check("trip marker: темп", trip.get("темп") == "размеренный")

    regs = stage0._parse_region_markers(body)
    check("region markers: 2 региона", len(regs) == 2, f"got {list(regs.keys())}")
    check("region marker: lookup lowercase",
          "сием-рип и ангкор" in regs and "луангпрабанг" in regs)
    check("region marker: role от polish",
          regs["сием-рип и ангкор"].get("role") == "core")
    check("region marker: сезон risk сохранён",
          regs["луангпрабанг"].get("сезон") == "risk")

    check("пустой body → пустой dict",
          stage0._parse_trip_marker("") == {} and stage0._parse_region_markers("") == {})


# ─── 2. role helpers ──────────────────────────────────────────────────────


def test_role_helpers():
    print("\n[2] role helpers — normalize / infer / resolve")

    check("_normalize_role 'core'", stage0._normalize_role("core") == "core")
    check("_normalize_role 'CORE'", stage0._normalize_role("CORE") == "core")
    check("_normalize_role 'ядро'", stage0._normalize_role("ядро") == "core")
    check("_normalize_role None → None", stage0._normalize_role(None) is None)
    check("_normalize_role 'bogus' → None", stage0._normalize_role("bogus") is None)
    # Фаза 1 русификации: канонические RU-термины taxonomy через canon-fallback.
    check("_normalize_role 'Поддержка' → supporting (taxonomy)",
          stage0._normalize_role("Поддержка") == "supporting")
    check("_normalize_role 'Нишевый' → niche (taxonomy)",
          stage0._normalize_role("Нишевый") == "niche")
    check("_normalize_role 'Пограничный' → borderline (taxonomy)",
          stage0._normalize_role("Пограничный") == "borderline")

    # Инференция для legacy (КЛТ_1 — нет role в YAML).
    must_high = {"density_tag": "HIGH", "reserve_for": None}
    check("infer HIGH+no_reserve → core",
          stage0._infer_role_from_longlist_item(must_high) == "core")

    must_med = {"density_tag": "MED", "reserve_for": None}
    check("infer MED+no_reserve → core",
          stage0._infer_role_from_longlist_item(must_med) == "core")

    reserve = {"density_tag": "MED", "reserve_for": "Пномпень"}
    check("infer reserve → supporting",
          stage0._infer_role_from_longlist_item(reserve) == "supporting")

    low = {"density_tag": "LOW", "reserve_for": None}
    check("infer LOW → niche",
          stage0._infer_role_from_longlist_item(low) == "niche")

    # _resolve_role: приоритет polish-маркера над YAML и инференцией.
    item = {"density_tag": "HIGH", "reserve_for": None, "role": "borderline"}
    check("resolve: polish > YAML",
          stage0._resolve_role(item, {"role": "niche"}) == "niche")
    check("resolve: YAML > infer",
          stage0._resolve_role(item, None) == "borderline")
    check("resolve: pure infer",
          stage0._resolve_role(
              {"density_tag": "HIGH", "reserve_for": None}, None) == "core")

    # Фаза 2b: тело эмитится с русскими заголовками role-групп. Без этого
    # `## Region universe` тихо терял бы role-классификацию excluded-регионов.
    check("_normalize_role 'Ядро поездки' → core (заголовок группы)",
          stage0._normalize_role("Ядро поездки") == "core")
    check("_normalize_role 'Нишевые' → niche (заголовок группы)",
          stage0._normalize_role("Нишевые") == "niche")
    check("_normalize_role 'Пограничные' → borderline (заголовок группы)",
          stage0._normalize_role("Пограничные") == "borderline")


def test_universe_roles_russian_body():
    print("\n[2b] `## Region universe` с русскими заголовками групп")

    def _universe(core_h: str, supp_h: str) -> dict:
        md = (
            "---\ntrip_id: t\nstage: 0_scope\nlonglist_count: 0\n---\n\n"
            "# Stage 0\n\n## Region universe (2) — группировано по role\n\n"
            f"### {core_h}\n\n#### Пекин\nСтолица.\n\n"
            f"### {supp_h}\n\n#### Сиань\nТерракотовая армия.\n"
        )
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "0_scope.md"
            p.write_text(md, encoding="utf-8")
            parsed = parser.parse_stage_file(str(p))
        return stage0._parse_universe_roles(parsed["sections"])

    ru = _universe("Ядро поездки (1)", "Поддержка (1)")
    en = _universe("Core (1) — ядро поездки", "Supporting (1)")
    check("русские заголовки групп → role-карта не пуста", bool(ru), str(ru))
    check("русская карта ролей == английской", ru == en, f"ru={ru} en={en}")
    check("«Ядро поездки» → core у Пекина", ru.get("пекин") == "core", str(ru))
    check("«Поддержка» → supporting у Сианя", ru.get("сиань") == "supporting", str(ru))


# ─── 3. body extraction: differentiator / season / non-canonical ──────────


def test_body_extraction():
    print("\n[3] body extraction — «Принципиально:», сезон, non-canonical")

    body_full = (
        "Состав: археопарк Ангкор, outlying-храмы.\n"
        "Принципиально: крупнейший ансамбль кхмерской храмовой архитектуры.\n"
        "Ночи: минимум 3, оптимум 5.\n"
        "Сезон в феврале 2026: сухо, для парка комфортно. Provincia в advisory.\n"
        "Логистика: международный аэропорт.\n"
        "Density: HIGH. Reserve binding: нет (core, must).\n"
    )
    desc, bullets, season, non_canon = stage0._extract_description_and_season(body_full)
    check("«Принципиально» → description (с capitalize)",
          desc == "Крупнейший ансамбль кхмерской храмовой архитектуры.",
          f"got: {desc!r}")
    check("«Принципиально» → bullets None (одна точка)", bullets is None)
    check("сезон: текст после «Сезон в … :»",
          season and season.startswith("сухо, для парка"), f"got: {season!r}")
    check("non_canon=False (нет строки Non-canonical)", non_canon is False)

    body_nc = (
        "Состав: что-то.\n"
        "Принципиально: differentiator.\n"
        "Non-canonical: колониальная урбанистика.\n"
        "Density: MED.\n"
    )
    _, _, _, nc = stage0._extract_description_and_season(body_nc)
    check("Non-canonical: строка → флаг True", nc is True)

    # Без «Принципиально:» — берётся первая содержательная строка.
    body_no_princ = (
        "Описание региона первая строка.\n"
        "Density: HIGH.\n"
    )
    desc2, _, _, _ = stage0._extract_description_and_season(body_no_princ)
    check("fallback: первая содержательная строка",
          desc2 == "Описание региона первая строка.",
          f"got: {desc2!r}")

    check("пустое body → пусто",
          stage0._extract_description_and_season("") == ("", None, None, False))

    # T8: «Что увидишь» (polish) приоритет над «Принципиально».
    body_t8 = (
        "**Что увидишь:** Ангкор-Ват на рассвете; Та-Прохм с корнями.\n"
        "Состав: археопарк.\n"
        "Принципиально: differentiator должен быть подавлен.\n"
        "Density: HIGH.\n"
    )
    desc_t8, bullets_t8, _, _ = stage0._extract_description_and_season(body_t8)
    check("T8 «Что увидишь» приоритет над «Принципиально»",
          "Ангкор-Ват" in desc_t8 and "differentiator" not in desc_t8,
          f"got: {desc_t8!r}")
    check("T8 — 2 точки → bullets с 2 элементами",
          bullets_t8 and len(bullets_t8) == 2, f"got: {bullets_t8!r}")

    # T8 multi-line с продолжением.
    body_t8_ml = (
        "**Что увидишь:** ансамбль Ангкор-Ват на рассвете;\n"
        "руины Та-Прохм; outlying-храмы Бенг-Меалеа.\n"
        "Density: HIGH.\n"
    )
    desc_ml, bullets_ml, _, _ = stage0._extract_description_and_season(body_t8_ml)
    check("T8 multi-line собирается в одну строку (fallback)",
          "Ангкор-Ват" in desc_ml and "Бенг-Меалеа" in desc_ml,
          f"got: {desc_ml!r}")
    check("T8 multi-line → bullets с 3 элементами",
          bullets_ml and len(bullets_ml) == 3,
          f"got: {bullets_ml!r}")

    # T8 markdown-bullets формат («Что увидишь:» + list).
    body_t8_bullets = (
        "**Что увидишь:**\n"
        "- ансамбль Ангкор-Ват на рассвете\n"
        "- руины Та-Прохм\n"
        "- outlying-храмы Бенг-Меалеа\n"
        "Density: HIGH.\n"
    )
    _, bullets_md, _, _ = stage0._extract_description_and_season(body_t8_bullets)
    check("T8 md-bullets формат → 3 точки",
          bullets_md and len(bullets_md) == 3
          and "Ангкор-Ват" in bullets_md[0],
          f"got: {bullets_md!r}")

    # _split_what_to_see — отдельный helper.
    parts = stage0._split_what_to_see("a; b; c")
    check("_split_what_to_see: ; → 3", len(parts) == 3 and parts == ["a", "b", "c"])
    parts2 = stage0._split_what_to_see("- one\n- two\n- three")
    check("_split_what_to_see: md-bullets → 3",
          len(parts2) == 3 and parts2 == ["one", "two", "three"])
    parts3 = stage0._split_what_to_see("одна точка без разделителей")
    check("_split_what_to_see: одна точка → list из 1",
          len(parts3) == 1)


# ─── 3b. cleanup helpers: yaml-жаргон, capitalize ─────────────────────────


def test_cleanup_helpers():
    print("\n[3b] cleanup helpers — _strip_yaml_jargon / _capitalize_first")

    # YAML-ссылки в скобках с backtick'ом.
    text1 = "Маршрут — Москва (`home_eq_start: true`); далее транзит."
    out1 = stage0._strip_yaml_jargon(text1)
    check("strip (`home_eq_start: true`)",
          "home_eq_start" not in out1 and "Москва" in out1,
          f"got: {out1!r}")

    # Bullet «Флаг `field: value` — ...».
    text2 = (
        "- Поездка: 18 ночей.\n"
        "- Флаг `retrospective: true` — пайплайн запущен на дате уже\n"
        "  состоявшейся поездки.\n"
        "- Старт и финиш в Москве.\n"
    )
    out2 = stage0._strip_yaml_jargon(text2)
    check("strip целого Флаг-bullet'а",
          "retrospective" not in out2 and "Поездка" in out2 and "Старт" in out2,
          f"got: {out2!r}")

    # Backtick'нутый trip_id.
    text3 = "Поездка `камбоджа_лаос_2026-02`, 18 ночей."
    out3 = stage0._strip_yaml_jargon(text3)
    check("strip backtick'нутый trip_id",
          "камбоджа_лаос" not in out3 and "18 ночей" in out3,
          f"got: {out3!r}")

    # Пустые / без жаргона — passthrough.
    check("пустой → пустой", stage0._strip_yaml_jargon("") == "")
    text4 = "Без жаргона, обычный текст."
    check("без жаргона → passthrough", stage0._strip_yaml_jargon(text4) == text4)

    # _capitalize_first
    check("строчная → заглавная",
          stage0._capitalize_first("крупнейший ансамбль") == "Крупнейший ансамбль")
    check("уже заглавная → passthrough",
          stage0._capitalize_first("Сием-Рип") == "Сием-Рип")
    check("ведущие пробелы — пропускаются",
          stage0._capitalize_first("  крупнейший") == "  Крупнейший")
    check("пустой → пустой", stage0._capitalize_first("") == "")
    check("цифра в начале → passthrough",
          stage0._capitalize_first("18 ночей") == "18 ночей")


# ─── 4. extract_content на КЛТ_1 (legacy) ────────────────────────────────


def test_extract_content_klt():
    print("\n[4] extract_content — КЛТ_1 legacy fixture")
    if not KLT_STAGE0.exists():
        skip("fixture", f"нет {KLT_STAGE0}")
        return

    parsed = parser.parse_stage_file(KLT_STAGE0)
    adapted = adapter.adapt_for_recipient(parsed, "self")
    ex = stage0.extract_content(adapted)

    check("trip_id извлечён",
          ex["frontmatter"].get("trip_id") == "камбоджа_лаос_2026-02")
    check("longlist: 7 регионов",
          len(ex["longlist"]) == 7, f"got {len(ex['longlist'])}")
    check("excluded: 11 регионов",
          len(ex["excluded"]) == 11, f"got {len(ex['excluded'])}")
    check("non_canonical: 4 элемента",
          len(ex["non_canonical"]) == 4, f"got {len(ex['non_canonical'])}")
    check("context не пустой", ex["context"] is not None and len(ex["context"]) > 50)
    check("honest не пустой", ex["honest"] is not None and len(ex["honest"]) > 50)

    # Role-инференция для legacy: проверяем 3 ключевых случая.
    by_name = {r.name: r for r in ex["longlist"]}
    check("Сием-Рип (HIGH, no reserve) → core",
          by_name["Сием-Рип и Ангкор"].role == "core")
    check("Пномпень (MED, no reserve) → core (compromise для legacy)",
          by_name["Пномпень"].role == "core")
    check("Баттамбанг (reserve_for=Пномпень) → supporting",
          by_name["Баттамбанг"].role == "supporting")
    check("Луангпрабанг (HIGH) → core", by_name["Луангпрабанг"].role == "core")
    check("Нонгкхиав (reserve) → supporting",
          by_name["Нонгкхиав и долина Нам-Оу"].role == "supporting")

    # Description — должен быть differentiator (из «Принципиально:»).
    s = by_name["Сием-Рип и Ангкор"]
    check("Сием-Рип description: differentiator из Принципиально",
          "крупнейший ансамбль" in s.description.lower(),
          f"got: {s.description[:80]!r}")
    check("Сием-Рип reserve_for=None", s.reserve_for is None)

    b = by_name["Баттамбанг"]
    check("Баттамбанг reserve_for=Пномпень", b.reserve_for == "Пномпень")
    check("Баттамбанг substitute_reason не пуст",
          b.substitute_reason and "колониаль" in b.substitute_reason.lower())

    # Excluded — names, reasons, описания из ## Region universe.
    excluded_names = [e.name for e in ex["excluded"]]
    check("excluded содержит Кампонгтхом", "Кампонгтхом и Самбор-Прей-Кук" in excluded_names)
    check("excluded содержит Вьентьян", "Вьентьян" in excluded_names)
    check("каждый excluded имеет reason",
          all(e.reason for e in ex["excluded"]))
    # Description обогащается из universe (где он есть).
    by_excl_name = {e.name: e for e in ex["excluded"]}
    camp = by_excl_name.get("Кампонгтхом и Самбор-Прей-Кук")
    check("Кампонгтхом description из universe (не reason)",
          camp and camp.description
          and "ангкорск" in camp.description.lower(),
          f"got: {camp.description if camp else None!r}")

    # Non-canonical: проверим статусы.
    statuses = {nc.name: nc.status for nc in ex["non_canonical"]}
    check("Кампонгтхом non-canonical excluded",
          statuses.get("Кампонгтхом и Самбор-Прей-Кук") == "excluded")
    check("Тхакхэк non-canonical in_longlist",
          statuses.get("Центральный Меконг — Тхакхэк и карст Кхаммуан") == "in_longlist")


# ─── 5. cover helpers ────────────────────────────────────────────────────


def test_cover_helpers():
    print("\n[5] cover helpers — humanize / season / title / subtitle")

    check("_humanize_regions: 2 страны",
          stage0._humanize_regions("камбоджа_лаос_2026-02") == "Камбоджа и Лаос")
    check("_humanize_regions: 1 страна",
          stage0._humanize_regions("корея_2024-03") == "Корея")
    check("_humanize_regions: пустой",
          stage0._humanize_regions("") == "")

    check("_season_from_trip_id: 2026-02 → февраль 2026",
          stage0._season_from_trip_id("камбоджа_лаос_2026-02") == "февраль 2026")
    check("_season_from_trip_id: 2024-10 → октябрь 2024",
          stage0._season_from_trip_id("корея_2024-10") == "октябрь 2024")
    check("_season_from_trip_id: без даты → None",
          stage0._season_from_trip_id("корея") is None)

    check("_tempo_display: slow → размеренный",
          stage0._tempo_display("slow") == "размеренный")
    check("_tempo_display: balanced",
          stage0._tempo_display("balanced") == "сбалансированный")
    check("_tempo_display: passthrough",
          stage0._tempo_display("custom") == "custom")

    # Ярлык scope-формата — из taxonomy (Фаза 2a.3): раньше свой словарь
    # печатал EN в подзаголовок обложки («explicit list»).
    check("_trip_format_display: multi_region_tour → мульти-регион-тур",
          stage0._trip_format_display("multi_region_tour") == "мульти-регион-тур")
    check("_trip_format_display: explicit_list → явный список",
          stage0._trip_format_display("explicit_list") == "явный список")
    check("_trip_format_display: single_base → одна база",
          stage0._trip_format_display("single_base") == "одна база")
    check("_trip_format_display: неизвестный формат — passthrough",
          stage0._trip_format_display("cruise") == "cruise")
    check("_trip_format_display: пусто → None",
          stage0._trip_format_display("") is None)

    # _prose (Фаза 2a.2/2a.3) — лиды секции «Темп и распределение» + scope-енум
    # в прозе. Живой формат Китая: bold-лид; Вьетнама: без bold.
    check("_prose: **Tempo:** → **Темп:**",
          "**Темп:** balanced" in
          stage0._prose("- **Tempo:** balanced с лёгким slow-уклоном."))
    check("_prose: лид без bold тоже (формат Вьетнама)",
          "Темп: balanced" in stage0._prose("- Tempo: balanced (1–2 ночи)"))
    check("_prose: Country/Math → Страны/Расчёт",
          "**Страны:**" in stage0._prose("- **Country:** одна страна") and
          "**Расчёт:**" in stage0._prose("- **Math:** 13 / 8 = ~1.6"))
    check("_prose: scope-енум в backtick'ах",
          "`явный список`" in stage0._prose("- **Формат:** `explicit_list` — 3 региона"))
    check("_prose: scope-енум голым текстом",
          "scope = явный список" in stage0._prose("**Что решено:** scope = explicit_list, 3 фикса"))
    check("_prose: слово-лейбл в свободной прозе НЕ подменяется",
          stage0._prose("маршрут cross-country без остановок") ==
          "маршрут cross-country без остановок")
    check("_prose: чистка YAML-жаргона сохранена",
          "home_eq_start" not in stage0._prose("Старт — Москва (`home_eq_start: true`)."))
    check("_prose: пустой вход",
          stage0._prose("") == "" and stage0._prose(None) is None)

    # Обе ветки рендера зовут ОДИН хелпер (Р7).
    ht_stage0 = (EXPORT_DIR / "stages_html" / "stage0.py").read_text(encoding="utf-8")
    check("HT/stage0 рендерит прозу через общий _prose",
          ht_stage0.count("s0._prose(") == 3 and
          "_strip_yaml_jargon" not in ht_stage0)

    # _cover_title: pipeline H1 → синтезируется человекочитаемый.
    extracted = {
        "title": "Stage 0 v2 — Региональное сужение: Камбоджа и Лаос",
        "frontmatter": {"trip_id": "камбоджа_лаос_2026-02"},
        "trip_params": {},
    }
    title = stage0._cover_title(extracted)
    check("_cover_title: pipeline H1 заменён",
          "Stage 0" not in title and "Камбоджа" in title,
          f"got: {title!r}")

    # _cover_title: чистый H1 от polish → используется как есть.
    extracted2 = {
        "title": "Камбоджа и Лаос · регионы для DR",
        "frontmatter": {"trip_id": "камбоджа_лаос_2026-02"},
        "trip_params": {},
    }
    check("_cover_title: чистый polish H1 сохранён",
          stage0._cover_title(extracted2) == "Камбоджа и Лаос · регионы для DR")

    # _cover_subtitle: сезон + ночи + формат.
    ex_full = {
        "title": "x", "frontmatter": {
            "trip_id": "камбоджа_лаос_2026-02",
            "duration_nights": 18,
            "trip_format": "multi_region_tour",
        }, "trip_params": {"сезон": "февраль 2026", "темп": "размеренный"},
    }
    sub = stage0._cover_subtitle(ex_full)
    check("_cover_subtitle: сезон / ночи / формат (формат — русским, 2a.3)",
          "февраль 2026" in sub and "18 ночей" in sub and "мульти-регион-тур" in sub,
          f"got: {sub!r}")

    # _cover_key_params для КЛТ_1.
    if KLT_STAGE0.exists():
        parsed = parser.parse_stage_file(KLT_STAGE0)
        ex = stage0.extract_content(parsed)
        rows = stage0._cover_key_params(ex)
        labels = [k for k, _ in rows]
        check("key_params: Страны", "Страны" in labels)
        check("key_params: Темп", "Темп" in labels)
        check("key_params: Регионов в выборке",
              any(l.startswith("Регионов в выборке") for l in labels))


# ─── 6. season chip ──────────────────────────────────────────────────────


def test_season_chip():
    print("\n[6] _season_chip — короткий tag из длинного note")

    # ok / комфортно → chip не нужен.
    check("ok → None", stage0._season_chip("сухо, для парка комфортно") is None)
    check("пустой → None", stage0._season_chip(None) is None)
    check("пустая строка → None", stage0._season_chip("") is None)

    # risk → жёлтый.
    chip = stage0._season_chip("risk по мгле — крайний север, экспозиция сезону")
    check("risk → жёлтый chip", chip is not None and chip[0] == "сезон: risk")

    chip2 = stage0._season_chip("мгла к концу месяца")
    check("мгла → risk", chip2 is not None and chip2[0] == "сезон: risk")

    # bad / blocked → красный.
    chip3 = stage0._season_chip("bad (активная конфликтная зона)")
    check("bad → blocked красный",
          chip3 is not None and chip3[0] == "сезон: blocked"
          and chip3[1] == stage0.COLORS["danger"])

    chip4 = stage0._season_chip("закрыт для иностранцев")
    check("закрыт → blocked красный",
          chip4 is not None and chip4[0] == "сезон: blocked")


# ─── 7. card grouping + reserve ordering ─────────────────────────────────


def test_grouping():
    print("\n[7] _group_by_role + _order_with_reserves")

    R = stage0.Region
    regs = [
        R("A", None, "HIGH", "core", 3, 5, None, None, "x", None, None, False),
        R("B", None, "MED", "supporting", 2, 3, "A",
          "reserve for A", "x", None, None, False),
        R("C", None, "HIGH", "core", 3, 5, None, None, "x", None, None, False),
        R("D", None, "MED", "niche", 2, 3, None, None, "x", None, None, False),
    ]
    groups = stage0._group_by_role(regs)
    keys = [g[0] for g in groups]
    check("порядок групп: core → supporting → niche",
          keys == ["core", "supporting", "niche"], f"got {keys}")

    core_group = dict(groups)["core"]
    check("core: A и C", [r.name for r in core_group] == ["A", "C"])

    # Reserve внутри той же group (если есть).
    regs2 = [
        R("X", None, "HIGH", "core", 3, 5, None, None, "x", None, None, False),
        R("Y", None, "MED", "core", 2, 3, "X",
          "reserve for X", "x", None, None, False),
        R("Z", None, "HIGH", "core", 3, 5, None, None, "x", None, None, False),
    ]
    ordered = stage0._order_with_reserves(regs2)
    names = [r.name for r in ordered]
    check("reserve Y стоит сразу после X",
          names == ["X", "Y", "Z"], f"got {names}")


# ─── 8. file_naming ──────────────────────────────────────────────────────


def test_file_naming():
    print("\n[8] file_naming.build_scope_filename")

    name = file_naming.build_scope_filename("камбоджа_лаос_2026-02", ext="pdf")
    check("без версии: {trip_id}_регионы.pdf",
          name == "0_камбоджа_лаос_2026-02_регионы.pdf", f"got {name}")

    name2 = file_naming.build_scope_filename(
        "корея_2024-03", ext="pdf", recipient="parents",
    )
    check("recipient parents → суффикс для_родителей",
          name2 == "0_корея_2024-03_регионы_для_родителей.pdf", f"got {name2}")

    # build_trip_doc_filename: version=None опускает _v{N}.
    check("build_trip_doc_filename(version=None) → без _v",
          file_naming.build_trip_doc_filename("x_2025-01", "что", version=None)
          == "x_2025-01_что.pdf")
    check("build_trip_doc_filename(version=2) → _v2",
          file_naming.build_trip_doc_filename("x_2025-01", "что", version=2)
          == "x_2025-01_что_v2.pdf")


# ─── 9. build_pdf smoke (требует reportlab) ──────────────────────────────


def test_build_pdf():
    print("\n[9] build_pdf — smoke на КЛТ_1")
    if not REPORTLAB_OK:
        skip("build_pdf", "reportlab не установлен")
        return
    if not KLT_STAGE0.exists():
        skip("build_pdf", f"нет fixture {KLT_STAGE0}")
        return

    parsed = parser.parse_stage_file(KLT_STAGE0)
    adapted = adapter.adapt_for_recipient(parsed, "self")
    ex = stage0.extract_content(adapted)

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "scope.pdf"
        try:
            stage0.build_pdf(ex, out, recipient="self")
        except Exception as e:
            check("build_pdf не падает", False, repr(e))
            return
        check("PDF создан", out.exists())
        check("PDF не пустой (>20KB)", out.stat().st_size > 20_000,
              f"size: {out.stat().st_size}")


# ─── 10. CLI integration ─────────────────────────────────────────────────


def test_cli_integration():
    print("\n[10] CLI integration: export.py --stage 0")
    if not REPORTLAB_OK:
        skip("CLI integration", "reportlab не установлен")
        return
    if not KLT_STAGE0.exists():
        skip("CLI integration", f"нет fixture {KLT_STAGE0}")
        return

    with tempfile.TemporaryDirectory() as tmp:
        trip_dir = Path(tmp) / "trips" / "камбоджа_лаос_2026-02"
        trip_dir.mkdir(parents=True)
        (trip_dir / "0_scope.md").write_text(
            KLT_STAGE0.read_text(encoding="utf-8"), encoding="utf-8"
        )
        result = subprocess.run(
            [sys.executable, str(EXPORT_DIR / "export.py"),
             "--stage", "0", "--trip", "камбоджа_лаос_2026-02",
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
        check("имя {trip_id}_регионы.pdf (без версии)",
              pdf_path.name == "0_камбоджа_лаос_2026-02_регионы.pdf",
              f"got {pdf_path.name}")


def test_validate_longlist():
    print("\n[11] validate_longlist — гейт целостности (порядок/сдвиг/все регионы)")

    def _sec_ll(preamble, names, bodies=None):
        bodies = bodies or {}
        return {"heading": "Longlist (N)", "body": preamble,
                "subsections": [{"heading": n, "body": bodies.get(n, "тело"),
                                 "subsections": []} for n in names]}

    # Good: YAML == тело, порядок совпадает, по 1 «Что увидишь» на регион.
    good = {"frontmatter": {"longlist": [{"region": "Пекин"}, {"region": "Шанхай"}],
                            "longlist_count": 2},
            "sections": [_sec_ll("", ["Пекин", "Шанхай"],
                                 {"Пекин": "**Что увидишь:** A",
                                  "Шанхай": "**Что увидишь:** B"})]}
    v = stage0.validate_longlist(good)
    check("чистый scope — без ошибок", v["errors"] == [], str(v["errors"]))
    check("чистый scope — без предупреждений", v["warnings"] == [], str(v["warnings"]))

    # E: YAML longlist пуст, но регионы в теле (Bug 1 — молчаливый пустой PDF).
    empty = {"frontmatter": {"longlist": [], "longlist_count": 8},
             "sections": [_sec_ll("", [f"R{i}" for i in range(8)])]}
    v = stage0.validate_longlist(empty)
    check("пустой YAML при регионах в теле → ERROR", len(v["errors"]) == 1, str(v["errors"]))

    # E: longlist_count ≠ числу регионов.
    cnt = {"frontmatter": {"longlist": [{"region": "A"}, {"region": "B"}],
                           "longlist_count": 5},
           "sections": [_sec_ll("", ["A", "B"])]}
    check("счётчик ≠ списку → ERROR",
          any("longlist_count" in e for e in stage0.validate_longlist(cnt)["errors"]))

    # W: регион в теле, но не в YAML → не попадёт в PDF.
    extra = {"frontmatter": {"longlist": [{"region": "Пекин"}], "longlist_count": 1},
             "sections": [_sec_ll("", ["Пекин", "Лоян"])]}
    check("лишний регион в теле → WARN",
          any("Лоян" in w for w in stage0.validate_longlist(extra)["warnings"]))

    # W: порядок YAML ≠ порядку тела.
    order = {"frontmatter": {"longlist": [{"region": "Пекин"}, {"region": "Шанхай"}],
                             "longlist_count": 2},
             "sections": [_sec_ll("", ["Шанхай", "Пекин"])]}
    check("разный порядок → WARN",
          any("порядок" in w for w in stage0.validate_longlist(order)["warnings"]))

    # W: «Что увидишь» в преамбуле (Bug 2 — сдвиг в чужую карточку).
    shift = {"frontmatter": {"longlist": [{"region": "Пекин"}, {"region": "Шанхай"}],
                             "longlist_count": 2},
             "sections": [_sec_ll("**Что увидишь:** Запретный город…",
                                  ["Пекин", "Шанхай"])]}
    check("«Что увидишь» в преамбуле → WARN (сдвиг)",
          any("преамбул" in w for w in stage0.validate_longlist(shift)["warnings"]))

    # build_pdf падает при validation_errors (не выдаёт кривой PDF).
    if REPORTLAB_OK:
        bad = {"longlist": [], "excluded": [], "non_canonical": [], "validation_errors":
               ["longlist пуст"], "warnings": [], "title": "t", "frontmatter": {},
               "trip_params": {}, "context": None, "tempo": None, "honest": None}
        raised = False
        try:
            stage0.build_pdf(bad, "/tmp/_should_not_build.pdf")
        except RuntimeError as e:
            raised = "не собран" in str(e)
        check("build_pdf падает при validation_errors", raised)

    # Реальный fixture КЛТ_1 — гейт не даёт ложных срабатываний на хорошем scope.
    if KLT_STAGE0.exists():
        v = stage0.validate_longlist(parser.parse_stage_file(KLT_STAGE0))
        check("реальный КЛТ scope — без ERROR", v["errors"] == [], str(v["errors"]))


def test_universe_grid():
    print("\n[12] _universe_groups — единая вселенная (✓ в DR / ◌ кандидат на замену)")
    R, E = stage0.Region, stage0.ExcludedRegion
    longlist = [
        R(name="A", country=None, density="", role="core", nights_min=1,
          nights_optimum=2, reserve_for=None, substitute_reason=None,
          description="", description_bullets=None, season_note=None,
          is_non_canonical=False),
        R(name="B", country=None, density="", role="supporting", nights_min=None,
          nights_optimum=None, reserve_for=None, substitute_reason=None,
          description="", description_bullets=None, season_note=None,
          is_non_canonical=False),
    ]
    excluded = [
        E(name="C", reason="дубль", description="карст", role="supporting"),
        E(name="D", reason="крюк", description="панды", role="niche"),
        E(name="Z", reason="виза", description="", role=None),  # без role → хвост
    ]
    g = stage0._universe_groups(longlist, excluded)
    total = sum(len(items) for _, _, _, items in g)
    check("все регионы попадают в сетку (5)", total == 5, str(total))
    sup = [i for d, _, _, i in g if d == "Дополнительные"][0]
    names = {o.name: sel for o, sel in sup}
    check("Дополнительные: выбранный B ✓ + кандидат C ◌ в одной группе",
          names.get("B") is True and names.get("C") is False, str(names))
    tail = [i for d, _, _, i in g if d == "Кандидаты на замену"]
    check("безролевой кандидат Z → хвостовая группа",
          bool(tail) and tail[0][0][0].name == "Z")
    order = [d for d, _, _, _ in g]
    check("порядок Ядро→Дополнительные→Нишевые (русские названия)",
          order.index("Ядро поездки") < order.index("Дополнительные") < order.index("Нишевые"))

    # _parse_universe_roles: role-grouped universe → роли; country-grouped → пусто.
    role_sec = [{"heading": "Region universe (2)", "body": "", "subsections": [
        {"heading": "Core (1)", "body": "", "subsections":
            [{"heading": "X", "body": "", "subsections": []}]},
        {"heading": "Niche (1)", "body": "", "subsections":
            [{"heading": "Y — RESERVE", "body": "", "subsections": []}]}]}]
    rm = stage0._parse_universe_roles(role_sec)
    check("universe роли: X→core, Y→niche (+ базовое имя без суффикса)",
          rm.get("x") == "core" and rm.get("y") == "niche", str(rm))
    country_sec = [{"heading": "Region universe (1)", "body": "", "subsections": [
        {"heading": "Камбоджа", "body": "", "subsections":
            [{"heading": "P", "body": "", "subsections": []}]}]}]
    check("country-grouped universe → ролей нет",
          stage0._parse_universe_roles(country_sec) == {})

    # Реальный китайский scope: 15 регионов в сетке (8✓ + 7◌), роли кандидатов.
    china = Path("/Users/you/Library/CloudStorage/SynologyDrive-home"
                 "/Claude-Memory/travel-planner/trips/регион_a_2027/0_scope.md")
    if china.exists():
        ex = stage0.extract_content(parser.parse_stage_file(china))
        gg = stage0._universe_groups(ex["longlist"], ex["excluded"])
        check("китай: 15 регионов в сетке",
              sum(len(i) for _, _, _, i in gg) == 15)
        check("китай: 8 ✓ в DR",
              sum(1 for _, _, _, i in gg for _, s in i if s) == 8)


# ─── runner ──────────────────────────────────────────────────────────────


def main() -> int:
    test_polish_markers()
    test_role_helpers()
    test_universe_roles_russian_body()
    test_body_extraction()
    test_cleanup_helpers()
    test_extract_content_klt()
    test_cover_helpers()
    test_season_chip()
    test_grouping()
    test_file_naming()
    test_build_pdf()
    test_cli_integration()
    test_validate_longlist()
    test_universe_grid()

    print(f"\n{'=' * 60}")
    print(f"Всего проверок: {checks_run}, провалов: {checks_failed}")
    return 0 if checks_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
