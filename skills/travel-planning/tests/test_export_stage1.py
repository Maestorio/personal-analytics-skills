#!/usr/bin/env python3
"""Регрессионные тесты для Stage 1 PDF builder (DR-база отчётов).

Покрывают:
  - polish-маркеры: _parse_trip_marker, _find_card_marker_before_h3
  - card field parsing: _parse_card_fields (bold / plain / bare / multi-line)
  - empty-value detection: _is_empty_value (—, не указано, не упомянуто, …)
  - URL/title/author extraction: _extract_url_and_title, _extract_author
  - tonality detection: _detect_tonality (marker / H3 suffix / grep field 18)
  - focus normalization: _normalize_focus
  - META-DIAGNOSTICS parser: _parse_meta на КЛТ_1
  - extract_content на КЛТ_1 (37 cards × 7 regions, 9 critical)
  - card → bullets mapping: drop полей 6/8/10/16/17 и пустых
  - outline title: _card_outline_title (формат «N · Автор — «Название»»)
  - file_naming.build_dr_reports_filename (без версии)
  - resilient к missing YAML (pure DR output без шапки)
  - Mode B sample_curation_note → info_box
  - build_pdf smoke (требует reportlab)
  - CLI integration: export.py --stage 1 → {trip_id}_dr_отчёты.pdf

Запуск из корня репозитория:
    python3 skills/travel-planning/tests/test_export_stage1.py

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
# Фикстура: реальный артефакт Stage 1 из КЛТ_1 (Камбоджа+Лаос, 37 cards × 7 regions).
KLT_STAGE1 = REPO_ROOT / "docs" / "travel-planning" / "calibration" / "КЛТ_1" / "1_dr_reports.md"

sys.path.insert(0, str(EXPORT_DIR.parent))
from export import parser, adapter, file_naming  # noqa: E402
from export.stages import stage1                 # noqa: E402

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


def _mkfields(**kwargs) -> dict[int, dict[str, str]]:
    """Test helper: {1: "value", 3: "Author"} → {1: {label,value,raw}, ...}."""
    out: dict[int, dict[str, str]] = {}
    for k, v in kwargs.items():
        num = int(k.lstrip("f"))
        out[num] = {"label": "", "value": v, "raw": v}
    return out


# ─── 1. Polish-маркеры ─────────────────────────────────────────────────────


def test_polish_markers():
    print("\n[1] polish-маркеры [[поездка: …]] и [[карточка: …]]")

    body = (
        "[[поездка: группа: Алексей | регионы: Камбоджа → Лаос | "
        "сезон: февраль 2026 | темп: размеренный]]\n\n"
        "## РЕГИОН 1: Сием-Рип и Ангкор\n"
        "[[карточка: tonality: critical | focus: photo | flags: residence]]\n"
        "### Карточка 1\n"
        "1. **URL:** https://example.com\n"
    )

    trip = stage1._parse_trip_marker(body)
    check("trip marker: 4 ключа", len(trip) == 4, f"got {trip}")
    check("trip marker: группа", trip.get("группа") == "Алексей")
    check("trip marker: сезон", trip.get("сезон") == "февраль 2026")

    marker = stage1._find_card_marker_before_h3(body, 1)
    check("card marker найден", marker is not None and marker.get("tonality") == "critical")
    check("card marker: focus", marker is not None and marker.get("focus") == "photo")
    check("card marker: flags", marker is not None and marker.get("flags") == "residence")

    check("пустой body → пустой trip", stage1._parse_trip_marker("") == {})
    check("нет маркера → None",
          stage1._find_card_marker_before_h3("### Карточка 5\n", 5) is None)


# ─── 2. Empty-value detection ──────────────────────────────────────────────


def test_empty_values():
    print("\n[2] _is_empty_value (—, не указано, не упомянуто)")

    check("пустая строка", stage1._is_empty_value(""))
    check("None", stage1._is_empty_value(None))
    check("только пробелы", stage1._is_empty_value("   "))
    check("дефис", stage1._is_empty_value("—"))
    check("дефис ASCII", stage1._is_empty_value("-"))
    check("не указано", stage1._is_empty_value("не указано"))
    check("Не указано (caps)", stage1._is_empty_value("Не указано"))
    check("не упомянуто", stage1._is_empty_value("не упомянуто"))
    check("не уточнено", stage1._is_empty_value("не уточнено"))
    check("реальное значение НЕ пусто",
          not stage1._is_empty_value("Алекс (Aleks)"))
    check("'30-40' НЕ пусто", not stage1._is_empty_value("30-40 (оценка)"))


# ─── 3. Card field parsing ─────────────────────────────────────────────────


def test_card_field_parsing():
    print("\n[3] _parse_card_fields — bold / plain / bare / multi-line")

    # Каноническая форма: `N. **Label:** value`
    body = (
        "1. **URL и название:** https://example.com — «Test Report»\n"
        "2. **Платформа / язык:** Example.com / русский\n"
        "3. **Автор:** Алекс\n"
        "14. **POI с тональностью:** Ангкор-Ват — рекомендует; Та-Прохм — рекомендует;\n"
        "    дополнительная строка многострочного POI;\n"
        "    Бенг-Меалеа — нейтрально\n"
        "18. **Жалобы / tonality: critical:** *«It is simply boring»*\n"
        "19. **Главная рекомендация:** «Если у вас мало дней — Малый круг»\n"
    )
    fields = stage1._parse_card_fields(body)
    check("парсит 6 полей", len(fields) == 6, f"got {sorted(fields)}")
    check("поле 1 — URL", "https://example.com" in (stage1._fv(fields, 1) or ""))
    check("поле 3 — автор", stage1._fv(fields, 3) == "Алекс")
    check("поле 14 — multi-line собрано",
          "Бенг-Меалеа" in (stage1._fv(fields, 14) or ""),
          f"got: {stage1._fv(fields, 14)!r}")
    check("поле 18 — критическое сохранено (value)",
          "boring" in (stage1._fv(fields, 18) or ""))
    # Главное: label с двоеточием («Жалобы / tonality: critical») сохраняется
    # и доступен через `raw` для critical-detection.
    check("поле 18 label содержит tonality: critical",
          "tonality: critical" in (fields[18]["label"]),
          f"got label: {fields[18]['label']!r}")
    check("поле 18 raw — для grep critical",
          "tonality: critical" in (stage1._fraw(fields, 18) or ""))

    # Plain form: `N. Label: value` (без bold).
    plain = "1. URL и название: https://x.com — «X»\n3. Автор: User\n"
    f2 = stage1._parse_card_fields(plain)
    check("plain form: парсит 2 поля", len(f2) == 2, f"got {sorted(f2)}")
    check("plain поле 3", stage1._fv(f2, 3) == "User")

    # Bare form: `N. value` без label — берётся как value.
    bare = "1. https://x.com\n"
    f3 = stage1._parse_card_fields(bare)
    check("bare form: парсит value", stage1._fv(f3, 1) == "https://x.com")

    # Прерывание на `---` / `###`.
    with_break = (
        "1. **URL:** https://a.com\n"
        "2. **Platform:** A\n"
        "---\n"
        "### Карточка 2\n"
        "1. **URL:** https://b.com\n"
    )
    f4 = stage1._parse_card_fields(with_break)
    check("прерывание на ---", len(f4) == 2 and "a.com" in (stage1._fv(f4, 1) or ""),
          f"got {sorted(f4)}")

    # D3-дрейф: DR пишет ВСЕ поля как `1.` (Китай `1 dr reports (1).md`).
    # Старый dict[номер]-парсер схлопывал 20 полей в fields[1] → пустая карточка.
    # Collision→positional: `1. 1. 1. …` в каноническом порядке → ключи 1..20.
    collapsed = (
        "1. **URL и название отчёта:** <https://a.com> — «А»\n"
        "1. **Платформа публикации:** блог\n"
        "1. **Имя или ник автора:** Иван\n"
        "1. **Транспорт:** автомобиль\n"
        "1. **Главная рекомендация одной фразой:** «едь весной»\n"
    )
    fc = stage1._parse_card_fields(collapsed)
    check("D3: 5 полей `1.` не схлопнулись (5 ключей)", len(fc) == 5, f"got {sorted(fc)}")
    check("D3: ключи позиционные 1..5", sorted(fc) == [1, 2, 3, 4, 5], f"got {sorted(fc)}")
    check("D3: поле 1 = URL", "a.com" in (stage1._fv(fc, 1) or ""))
    check("D3: поле 3 = автор Иван", "Иван" in (stage1._fv(fc, 3) or ""))
    check("D3: поле 5 = рекомендация", "весной" in (stage1._fv(fc, 5) or ""))

    # Не-регресс: корректная нумерация сохраняется как есть.
    wf = stage1._parse_card_fields("3. **X:** a\n7. **Y:** b\n")
    check("корректные/разрежённые номера сохранены (3,7)",
          sorted(wf) == [3, 7], f"got {sorted(wf)}")


# ─── 4. URL / title / author extraction ────────────────────────────────────


def test_url_title_extraction():
    print("\n[4] _extract_url_and_title, _extract_author")

    # Каноническая форма: «URL — «Название»»
    url, title = stage1._extract_url_and_title(
        "https://aleksblog.com/angkor/ — «Храмы Ангкора: полное руководство»"
    )
    check("url извлечён", url == "https://aleksblog.com/angkor/")
    check("title в кавычках извлечён",
          title == "Храмы Ангкора: полное руководство")

    # Без URL: весь текст = title.
    url2, title2 = stage1._extract_url_and_title("Boring and Overrated")
    check("no URL → title=полный текст", url2 is None and title2 == "Boring and Overrated")

    # URL без кавычек, после `—`.
    url3, title3 = stage1._extract_url_and_title(
        "https://forum.awd.ru/viewtopic.php?t=123 — Вьетнам 2024"
    )
    check("url + post-dash title",
          url3 and url3.startswith("https://forum.awd.ru") and title3 == "Вьетнам 2024",
          f"got url={url3!r}, title={title3!r}")

    # Только URL без кавычек.
    url4, title4 = stage1._extract_url_and_title("https://x.com/post")
    check("только URL → title None", url4 == "https://x.com/post" and title4 is None,
          f"got url={url4!r}, title={title4!r}")

    # Author — режем `(…)` только если уточнение короткое.
    check("автор: имя как есть",
          stage1._extract_author("Алекс (Aleks)") == "Алекс (Aleks)")
    check("автор: helvhrav (Москва) → сохраняем",
          stage1._extract_author("helvhrav (Москва)") == "helvhrav (Москва)")
    check("автор: пустой → None",
          stage1._extract_author("не указано") is None)


# ─── 5. Tonality / focus / flags ───────────────────────────────────────────


def test_tonality_focus():
    print("\n[5] _detect_tonality, _normalize_focus, _detect_flags")

    # Tonality — три ветки приоритета.
    check("tonality: marker > всё",
          stage1._detect_tonality(None, {"tonality": "critical"}, None) is True)
    check("tonality: H3 suffix",
          stage1._detect_tonality("tonality: critical", None, None) is True)
    check("tonality: grep field 18",
          stage1._detect_tonality(None, None,
              "Жалобы / tonality: critical: текст") is True)
    check("tonality: нет — False",
          stage1._detect_tonality(None, {"focus": "photo"}, "обычное поле 18") is False)
    check("tonality: marker non-critical → False",
          stage1._detect_tonality(None, {"tonality": "neutral"}, None) is False)

    # Focus normalization.
    check("focus: mix (архитектура+культура) → mix",
          stage1._normalize_focus("mix (архитектура + культура)") == "mix")
    check("focus: 'фотография + архитектура' → фото",
          stage1._normalize_focus("фотография + архитектура") == "фото")
    check("focus: 'архитектура' → архитектура",
          stage1._normalize_focus("архитектура") == "архитектура")
    check("focus: пусто → mix",
          stage1._normalize_focus(None) == "mix" and
          stage1._normalize_focus("не указано") == "mix")

    # Flags.
    flags1 = stage1._detect_flags({"flags": "residence, photo"}, None)
    check("flags из marker: residence + photo",
          flags1 == {"residence", "photo"}, f"got {flags1}")
    flags2 = stage1._detect_flags(None, "ЯВНЫЕ — оптимизация под свет")
    check("flag photo из поля 20 = ЯВНЫЕ", "photo" in flags2)
    flags3 = stage1._detect_flags(None, "Общий travel-фокус, без явного фото-фокуса")
    check("flag photo: не выставлен если 'без явного'",
          "photo" not in flags3, f"got {flags3}")


# ─── 6. META-DIAGNOSTICS parser ────────────────────────────────────────────


def test_meta_parser():
    print("\n[6] _parse_meta на КЛТ_1")

    if not KLT_STAGE1.exists():
        skip("КЛТ_1 фикстура", f"не нашёл {KLT_STAGE1}")
        return

    text = KLT_STAGE1.read_text(encoding="utf-8")
    parsed = parser.parse_stage_text(text)
    meta = stage1._parse_meta(parsed["body"])

    check("meta непустой", bool(meta))
    cov = meta.get("coverage_per_region") or []
    check("coverage_per_region: 7 регионов", len(cov) == 7,
          f"got {len(cov)}: {[r[0] for r in cov]}")
    # Проверяем что Сием-Рип и Тямпасак на месте.
    cov_dict = {r[0]: r[1] for r in cov}
    check("coverage: Сием-Рип = 6", "6" in cov_dict.get("Сием-Рип и Ангкор", ""),
          f"got: {cov_dict.get('Сием-Рип и Ангкор')!r}")

    dist = meta.get("distributions") or {}
    check("distributions: 4 (стили/сезоны/фокус/языки)", len(dist) >= 4,
          f"got keys: {list(dist.keys())}")
    check("distribution 'стилям путешествия' непуст",
          bool(dist.get("стилям путешествия")) or
          any("стил" in k for k in dist),
          f"keys: {list(dist.keys())}")

    poi = meta.get("poi_critique_per_region") or []
    check("poi_critique_per_region: 7 регионов", len(poi) == 7,
          f"got {len(poi)}")

    season = meta.get("season_caveat") or ""
    check("season_caveat: длинный текст про burning season",
          "burning season" in season.lower() or "дымк" in season.lower(),
          f"got len={len(season)}")

    # sources_outside_seed в КЛТ_1 — 2 длинных bullet'а через запятую,
    # не отдельные пункты на платформу.
    check("sources_outside_seed: ≥ 1 пункт",
          len(meta.get("sources_outside_seed") or []) >= 1,
          f"got {len(meta.get('sources_outside_seed') or [])}")

    check("sources_tried: > 3 пунктов",
          len(meta.get("sources_tried") or []) > 3)


# ─── 7. Region extraction ──────────────────────────────────────────────────


def test_region_extraction():
    print("\n[7] _extract_regions_and_cards на КЛТ_1")

    if not KLT_STAGE1.exists():
        skip("КЛТ_1 фикстура", f"не нашёл {KLT_STAGE1}")
        return

    text = KLT_STAGE1.read_text(encoding="utf-8")
    parsed = parser.parse_stage_text(text)
    regions = stage1._extract_regions_and_cards(parsed)

    check("регионов: 7", len(regions) == 7, f"got {len(regions)}: {[r.name for r in regions]}")
    total_cards = sum(len(r.cards) for r in regions)
    check("карточек всего: 37", total_cards == 37, f"got {total_cards}")

    # Каждый регион ≥ 4 карточек.
    counts = [(r.name, len(r.cards)) for r in regions]
    check("каждый регион ≥ 4 карточек",
          all(c >= 4 for _, c in counts), f"got {counts}")

    # Все card.num уникальны и в диапазоне 1..37.
    all_nums = [c.num for r in regions for c in r.cards]
    check("номера уникальны", len(all_nums) == len(set(all_nums)))
    check("номера в 1..37", min(all_nums) == 1 and max(all_nums) == 37)

    # Slug формат.
    check("region slug формат region-N-<text>",
          all(r.slug.startswith(f"region-{r.idx}-") or r.slug == f"region-{r.idx}"
              for r in regions))


# ─── 8. Critical detection on КЛТ_1 ───────────────────────────────────────


def test_critical_detection():
    print("\n[8] critical detection на КЛТ_1 — H3 suffix + field 18 grep")

    if not KLT_STAGE1.exists():
        skip("КЛТ_1 фикстура", f"не нашёл {KLT_STAGE1}")
        return

    text = KLT_STAGE1.read_text(encoding="utf-8")
    parsed = parser.parse_stage_text(text)
    extracted = stage1.extract_content(parsed)

    check("total_cards: 37", extracted["total_cards"] == 37)
    crit = extracted["critical_count"]
    # КЛТ_1: критические — Карточки 4, 7 (в Жалобы), 12, 15, 16, 17 (Tak-bat), 18, 20, 30, 32, 33, 36
    # Реальное число определяется парсером — проверяем разумный диапазон.
    check("critical_count: разумный диапазон (5-15)", 5 <= crit <= 15,
          f"got {crit}")

    # Карточка 4 точно critical (H3 «Карточка 4 — tonality: critical»).
    card4 = next((c for r in extracted["regions"] for c in r.cards if c.num == 4), None)
    check("Карточка 4 — critical (H3 suffix)",
          card4 is not None and card4.is_critical)

    # Карточка 1 — не critical.
    card1 = next((c for r in extracted["regions"] for c in r.cards if c.num == 1), None)
    check("Карточка 1 — НЕ critical",
          card1 is not None and not card1.is_critical)


# ─── 9. Outline title formatting ───────────────────────────────────────────


def test_outline_title():
    print("\n[9] _card_outline_title — формат «N · Автор — «Название»»")

    card = stage1.Card(
        num=1,
        h3_suffix=None,
        fields=_mkfields(
            f1="https://aleksblog.com/angkor/ — «Храмы Ангкора»",
            f3="Алекс (Aleks)",
        ),
        marker=None,
        region_name="Сием-Рип и Ангкор",
    )
    title = stage1._card_outline_title(card)
    check("формат с автором и названием",
          title == "1 · Алекс (Aleks) — «Храмы Ангкора»",
          f"got {title!r}")

    # Только автор без названия.
    card2 = stage1.Card(
        num=5, h3_suffix=None,
        fields=_mkfields(f3="User", f1="https://x.com"),
        marker=None, region_name="X",
    )
    t2 = stage1._card_outline_title(card2)
    check("только автор", t2 == "5 · User", f"got {t2!r}")

    # Ничего — fallback на «Карточка N».
    card3 = stage1.Card(num=12, h3_suffix=None, fields={}, marker=None, region_name="X")
    t3 = stage1._card_outline_title(card3)
    check("fallback на «Карточка N»", t3 == "Карточка 12", f"got {t3!r}")

    # Обрезка по длине.
    long_title = "x" * 200
    card4 = stage1.Card(
        num=99, h3_suffix=None,
        fields=_mkfields(f1=f"https://x.com — «{long_title}»", f3="U"),
        marker=None, region_name="X",
    )
    t4 = stage1._card_outline_title(card4)
    check("обрезка до 90 символов", len(t4) <= 90 and t4.endswith("…"))


# ─── 10. Card bullets — drop полей 6/8/10/16/17 и пустых ──────────────────


def test_card_bullets_drop_fields():
    print("\n[10] _build_card_bullets — drop полей 6/8/10/16/17 и пустых")

    card = stage1.Card(
        num=1, h3_suffix=None,
        fields=_mkfields(
            f6="Сухой сезон (поле 6 — DROP)",
            f7="Пара",
            f8="30-40 (поле 8 — DROP)",
            f9="mid-range independent",
            f10="3 дня в одной локации (поле 10 — DROP)",
            f11="Тук-тук",
            f12="Koulen Hotel",
            f14="Ангкор-Ват — рекомендует",
            f15="не упомянуто",         # пустое
            f16="Логистика (поле 16 — DROP)",
            f17="не упомянуто",          # поле 17 — DROP в любом случае
            f19="«Малый круг»",
        ),
        marker=None, region_name="X",
    )
    bullets = stage1._build_card_bullets(card)
    text = " ".join(bullets)

    check("поле 6 (сезон) отсутствует", "сухой сезон" not in text.lower(),
          f"got: {text}")
    check("поле 8 (возраст) отсутствует", "30-40" not in text,
          f"got: {text}")
    check("поле 10 (темп) отсутствует", "одной локации" not in text,
          f"got: {text}")
    check("поле 16 (логистика) отсутствует", "логистика" not in text.lower(),
          f"got: {text}")
    check("поле 17 (диета) отсутствует", "не упомянуто" not in text,
          f"got: {text}")
    check("поле 15 (Hidden gems пустое) отсутствует", "Hidden gems" not in text)

    # Group/style комбинируется в одну строку; стиль — русским (Фаза 2a.1).
    check("Группа/стиль — одной строкой",
          any("Группа / стиль" in b and "Пара" in b
              and "миддл-сегмент самостоятельно" in b
              for b in bullets), f"bullets: {bullets}")

    # POI / Транспорт / Размещение / Главное — присутствуют.
    check("транспорт присутствует", any("Транспорт" in b for b in bullets))
    check("размещение присутствует", any("Размещение" in b for b in bullets))
    check("POI присутствует", any("POI" in b for b in bullets))
    check("главное (цитата) присутствует", any("Главное" in b for b in bullets))


# ─── 10b. Rendering cleanups: transport, accommodation, warnings, distribution
# ─────────────────────────────────────────────────────────────────────────


def test_rendering_cleanups():
    print("\n[10b] cleanup-функции: транспорт / размещение / warnings / распределения")

    # _clean_transport: длинные скобки и дедуп.
    tr = stage1._clean_transport(
        "Тук-тук по храмам; авиа в Сием-Рип (рейсы AirAsia, Asiana, "
        "Bangkok Airways, Cambodia Angkor Air, China Eastern, Lao Airlines, "
        "Singapore Airlines, Thai AirAsia, Thai Airways, VietJet, Vietnam Airlines)"
    )
    check("транспорт: длинная скобка-перечисление срезана",
          "AirAsia" not in tr and "VietJet" not in tr, f"got: {tr!r}")
    check("транспорт: тип «авиа» сохранён",
          "авиа" in tr.lower(), f"got: {tr!r}")
    check("транспорт: тип «тук-тук» сохранён",
          "тук-тук" in tr.lower(), f"got: {tr!r}")

    # Короткая скобка — оставляем (это контекст, не перечисление).
    tr2 = stage1._clean_transport("Поезд (ночной); такси")
    check("транспорт: короткая скобка остаётся",
          "(ночной)" in tr2, f"got: {tr2!r}")

    # Дедуп повторов первого слова.
    tr3 = stage1._clean_transport("Тук-тук в храмах; тук-тук в Pub Street; авиа")
    check("транспорт: дедуп повторов",
          tr3.lower().count("тук-тук") == 1 and "авиа" in tr3.lower(),
          f"got: {tr3!r}")

    # _extract_accommodation_type: только тип, без имён отелей.
    check("размещение: «Koulen Hotel (бассейн…)» → отель",
          stage1._extract_accommodation_type(
              "Koulen Hotel (3 ночи, бассейн на крыше, 500 м до Pub Street)"
          ) == "отель")
    check("размещение: хостел с дормом → хостел",
          stage1._extract_accommodation_type("Hostel с dorm-комнатой") == "хостел")
    check("размещение: homestay в Pu Luong",
          stage1._extract_accommodation_type(
              "Homestay у местного гида в долине"
          ) == "homestay")
    check("размещение: микс «отель + хостел»",
          stage1._extract_accommodation_type(
              "Отель в Сием-Рипе и хостел в Пномпене"
          ) in ("отель, хостел", "хостел, отель"))
    check("размещение: «не уточнено» → None",
          stage1._extract_accommodation_type("не уточнено") is None)
    check("размещение: «—» → None",
          stage1._extract_accommodation_type("—") is None)
    check("размещение: «Отель в углу самого центра, 5 минут до Old Market» → отель",
          stage1._extract_accommodation_type(
              "Отель в углу самого центра, 5 минут до Old Market"
          ) == "отель")
    # «не определилось» → None (нет ключевых слов).
    check("размещение: текст без ключевых слов → None",
          stage1._extract_accommodation_type("в центре города") is None)

    # _clean_warning_text: срезает WARN-N / B1-awd.ru / NOTE префиксы.
    check("warning: «WARN-1: текст» → «текст»",
          stage1._clean_warning_text("WARN-1: 0% местноязычных источников") ==
          "0% местноязычных источников")
    check("warning: «**WARN-2:** текст» (с bold) → «текст»",
          stage1._clean_warning_text(
              "**WARN-2:** POI-критика для региона Тямпасак"
          ).startswith("POI-критика"))
    check("warning: «B1-awd.ru: текст» → «текст»",
          stage1._clean_warning_text(
              "B1-awd.ru: BPC-challenge заблокировал доступ"
          ) == "BPC-challenge заблокировал доступ")
    check("warning: «NOTE: текст» → «текст»",
          stage1._clean_warning_text("NOTE: Многие EN-источники…") ==
          "Многие EN-источники…")
    check("warning: без префикса остаётся как был",
          stage1._clean_warning_text("Просто текст") == "Просто текст")

    # _ru_style: english → russian (словарь — taxonomy `report_style`).
    check("dist: backpacker → бэкпэкер",
          "бэкпэкер" in stage1._ru_style(
              "backpacker: ~30% (11 отчётов)"
          ))
    check("dist: mid-range independent (длинный термин раньше mid-range)",
          "миддл-сегмент самостоятельно" in stage1._ru_style(
              "mid-range independent: ~25%"
          ))
    check("dist: photography-focused → фото-фокус",
          "фото-фокус" in stage1._ru_style(
              "photography-focused: ~14% (5 — Карточки 2, 17, 18, 29, 33)"
          ))
    check("dist: оригинальный текст сохраняется кроме термина",
          "30%" in stage1._ru_style("backpacker: ~30%"))
    check("dist: без known терминов — без изменений",
          stage1._ru_style("Январь–февраль: ~24%") ==
          "Январь–февраль: ~24%")

    # Поле 9 «Стиль путешествия» (Фаза 2a.1) — тот же словарь, живой формат DR
    # (свободный текст, составные значения через `/` и с русским хвостом).
    check("поле 9: составное значение по частям",
          stage1._ru_field_value(9, "backpacker / mid-range independent") ==
          "бэкпэкер / миддл-сегмент самостоятельно")
    check("поле 9: русский хвост значения не тронут",
          stage1._ru_field_value(9, "mid-range independent с локальным гидом") ==
          "миддл-сегмент самостоятельно с локальным гидом")
    check("поле 9: незнакомый термин — как есть",
          stage1._ru_field_value(9, "solo budget freelancer / mid-range") ==
          "solo budget freelancer / миддл-сегмент")
    check("поле 9: идемпотентность (второй проход ничего не меняет)",
          stage1._ru_field_value(9, stage1._ru_field_value(9, "organized tour")) ==
          "организованный тур")
    # Поле 7 «Состав группы» — тот же словарь стилей: DR пишет туда «organized
    # tour с русскоязычным гидом», и без него на одной карточке «Стиль» был бы
    # русским, а «Состав группы» — английским.
    check("поле 7: словарь стилей (консистентность внутри карточки)",
          stage1._ru_field_value(7, "organized tour с русскоязычным гидом") ==
          "организованный тур с русскоязычным гидом")
    check("поле 13: своя группа report_focus (mix → микс)",
          stage1._ru_field_value(13, "mix (культура + природа)") ==
          "микс (культура + природа)")
    check("поле 12 «Размещение» НЕ трогаем — там имена отелей",
          stage1._ru_field_value(12, "Family Inn — хостел") == "Family Inn — хостел")
    check("поле вне карты групп — без изменений",
          stage1._ru_field_value(11, "organized tour") == "organized tour")

    # Обе ветки рендера зовут ОДИН хелпер (Р7): kv-поле стиля в HTML.
    ht_stage1 = (EXPORT_DIR / "stages_html" / "stage1.py").read_text(
        encoding="utf-8")
    check("HT/stage1 рендерит kv-значения через _ru_field_value",
          "_ru_field_value(num" in ht_stage1)
    check("HT/stage1 локализует распределения через _ru_style",
          "_ru_style(it)" in ht_stage1)


# ─── 10c. Warnings: YAML primary, body fallback (no merge) ────────────────


def test_warnings_yaml_primary():
    print("\n[10c] warnings: YAML primary, body fallback (без merge — дедуп через polish)")

    if not KLT_STAGE1.exists():
        skip("warnings KLT", f"нет фикстуры {KLT_STAGE1}")
        return

    text = KLT_STAGE1.read_text(encoding="utf-8")
    parsed = parser.parse_stage_text(text)
    extracted = stage1.extract_content(parsed)
    warns = extracted["warnings"]
    # КЛТ_1 YAML содержит 4 warning'а — это и берём (body НЕ мержим, чтобы
    # не было визуальных дублей; полная консолидация — задача polish T9).
    yaml_warns = parsed["frontmatter"].get("meta_diagnostics_warnings") or []
    check("warnings = YAML.meta_diagnostics_warnings (без body merge)",
          len(warns) == len(yaml_warns),
          f"got {len(warns)} (yaml={len(yaml_warns)})")

    # Fallback: если YAML пуст — берём из body.
    no_yaml_text = (
        "---\ntrip_id: x\nstage: 1_dr_reports\n---\n\n"
        "## РЕГИОН 1: X\n### Карточка 1\n1. **URL:** https://a.com\n\n"
        "# META-DIAGNOSTICS\n## WARNINGs\n"
        "- WARN-1: тест-предупреждение из body\n"
    )
    parsed2 = parser.parse_stage_text(no_yaml_text)
    extracted2 = stage1.extract_content(parsed2)
    check("fallback на body при пустом YAML",
          any("тест-предупреждение" in w for w in extracted2["warnings"]),
          f"got: {extracted2['warnings']}")


# ─── 11. extract_content без YAML (pure DR output) ────────────────────────


def test_extract_no_yaml():
    print("\n[11] extract_content — устойчивость к missing YAML (pure DR output)")

    raw = (
        "# Stage 1: Сырая структурированная база отчётов\n\n"
        "Преамбула.\n\n"
        "## РЕГИОН 1: Тестовый регион (Test Region), Страна\n\n"
        "### Карточка 1\n"
        "1. **URL и название:** https://x.com — «Тест»\n"
        "2. **Платформа / язык:** X.com / русский\n"
        "3. **Автор:** Тестер\n"
        "13. **Главный фокус:** mix\n"
        "14. **POI с тональностью:** Точка A — рекомендует\n\n"
        "### Карточка 2\n"
        "1. **URL и название:** https://y.com — «Тест 2»\n"
        "3. **Автор:** Второй\n"
        "13. **Главный фокус:** фотография\n"
        "14. **POI с тональностью:** Точка B — критикует\n"
        "18. **Жалобы / tonality: critical:** *«Скучно»*\n"
    )
    parsed = parser.parse_stage_text(raw)
    check("frontmatter пуст", parsed["frontmatter"] == {})
    extracted = stage1.extract_content(parsed)
    check("регион распознан", len(extracted["regions"]) == 1)
    check("карточки распознаны", extracted["total_cards"] == 2)
    # Карточка 2 — critical через grep поля 18.
    card2 = extracted["regions"][0].cards[1]
    check("Карточка 2 critical", card2.is_critical)
    # Карточка 1 — focus mix, Карточка 2 — focus фото.
    card1 = extracted["regions"][0].cards[0]
    check("focus карточки 1 = mix", card1.focus_tag == "mix")
    check("focus карточки 2 = фото", card2.focus_tag == "фото")
    # Cover не падает на пустой trip_id.
    title = stage1._cover_title(extracted)
    check("cover title не падает", isinstance(title, str) and len(title) > 0,
          f"got {title!r}")


# ─── 11b. Cover: YAML regions: как счётчик, Темп в паспорте, «Предупреждений» ─


def test_cover_yaml_regions_tempo_warnings():
    """Batch 2 §2.2/2.4: счётчик регионов на обложке берётся из YAML `regions:`
    (де-регионизация схлопывает internal `regions` в один псевдо-регион «База
    отчётов» → без этого фикса всегда «Регионы (1)»); строка «Темп» из маркера
    `[[поездка: …]]` не терялась; лейбл «WARN-флагов» русифицирован."""
    print("\n[11b] обложка: YAML regions: счётчик + Темп + «Предупреждений»")

    names = ["Пекин и окрестности", "Сиань", "Чжанцзяцзе", "Гуйлинь",
             "Ланьчжоу", "Дуньхуан", "Сямэнь", "Гонконг"]
    raw = (
        "---\ntrip_id: регион_a_2027\n"
        "regions: [" + ", ".join(names) + "]\n"
        "meta_diagnostics_warnings:\n"
        '  - "WARN-1: тест"\n'
        '  - "WARN-2: тест"\n'
        "---\n\n"
        "[[поездка: группа: Родители | темп: размеренный]]\n\n"
        "## КАРТОЧКА 1\n1. URL: http://a\n"
    )
    parsed = parser.parse_stage_text(raw)
    check("regions: флоу-список из 8 имён распарсен",
          isinstance(parsed["frontmatter"].get("regions"), list)
          and len(parsed["frontmatter"]["regions"]) == 8,
          str(parsed["frontmatter"].get("regions")))
    extracted = stage1.extract_content(parsed)
    rows = dict(stage1._cover_key_params(extracted))
    check("«Регионы (8)» из YAML, не из де-регионизированного internal (1)",
          any(k.startswith("Регионы (8)") for k in rows), str(rows))
    check("Темп из маркера присутствует в паспорте",
          rows.get("Темп") == "размеренный", str(rows))
    check("«Предупреждений» вместо «WARN-флагов»",
          "Предупреждений" in rows and "WARN-флагов" not in rows, str(rows))
    check("subtitle тоже даёт 8 регионов",
          "8 регионов" in stage1._cover_subtitle(extracted))

    # Без YAML regions: — fallback на internal (де-регионизированный) псевдо-регион.
    raw_no_yaml_regions = (
        "---\ntrip_id: регион_a_2027\n---\n\n## КАРТОЧКА 1\n1. URL: http://a\n"
    )
    parsed2 = parser.parse_stage_text(raw_no_yaml_regions)
    extracted2 = stage1.extract_content(parsed2)
    rows2 = dict(stage1._cover_key_params(extracted2))
    check("без YAML regions: — geo_label «Регионы (1)» (fallback на де-регион)",
          any(k.startswith("Регионы (1)") for k in rows2), str(rows2))


# ─── 12. Mode B sample_curation_note ──────────────────────────────────────


def test_mode_b_curation_note():
    print("\n[12] sample_curation_note → отображение для Mode B")

    raw = (
        "---\n"
        "trip_id: x_2026-01\n"
        "stage: 1_dr_reports\n"
        "reports_count: 5\n"
        "sample_curation_note:\n"
        "  - \"карточки 4, 5 добавлены через B1 awd.ru\"\n"
        "---\n\n"
        "## РЕГИОН 1: X\n\n"
        "### Карточка 1\n"
        "1. **URL:** https://a.com\n"
    )
    parsed = parser.parse_stage_text(raw)
    extracted = stage1.extract_content(parsed)
    note = extracted["sample_curation_note"]
    check("sample_curation_note извлечён",
          note is not None and (
              (isinstance(note, list) and "awd.ru" in note[0]) or
              (isinstance(note, str) and "awd.ru" in note)
          ),
          f"got: {note!r}")


def test_mode_b_curation_note_script_name_stripped():
    """Batch 2 §4.5: имя пайплайн-скрипта («через merge_dr_additions.py») —
    внутренняя механика, пользователю не нужна; срезается в рендере (не в
    extract_content — данные там остаются как есть для других потребителей)."""
    print("\n[12b] sample_curation_note: имя скрипта срезано в рендере")

    check("_strip_pipeline_script_ref: срезает «через X.py»",
          stage1._strip_pipeline_script_ref(
              "карточки №29, №30 добавлены вручную через merge_dr_additions.py")
          == "карточки №29, №30 добавлены вручную")
    check("_strip_pipeline_script_ref: без script-ref — не тронут",
          stage1._strip_pipeline_script_ref("карточки №29, №30 добавлены вручную")
          == "карточки №29, №30 добавлены вручную")

    raw = (
        "---\ntrip_id: x_2026-01\nstage: 1_dr_reports\nreports_count: 1\n"
        "sample_curation_note: "
        "\"карточки №29, №30 добавлены вручную через merge_dr_additions.py\"\n"
        "---\n\n## РЕГИОН 1: X\n\n### Карточка 1\n1. **URL:** https://a.com\n"
    )
    parsed = parser.parse_stage_text(raw)
    extracted = stage1.extract_content(parsed)

    if REPORTLAB_OK:
        import tempfile as _tf
        with _tf.TemporaryDirectory() as t:
            out = Path(t) / "s1.pdf"
            stage1.build_pdf(extracted, out)
            check("build_pdf не падает на sample_curation_note со script-ref",
                  out.exists())

    try:
        from export.stages_html import stage1 as h1
    except ImportError:
        skip("HTML-рендер sample_curation_note", "HT-модуль недоступен")
        return
    import tempfile as _tf
    with _tf.TemporaryDirectory() as t:
        doc = h1.build_html(extracted, Path(t) / "s1.html")
    check("HTML: script-name «merge_dr_additions.py» не в выводе",
          "merge_dr_additions.py" not in doc)
    check("HTML: содержательная часть заметки осталась",
          "добавлены вручную" in doc)


# ─── 13. file_naming ──────────────────────────────────────────────────────


def test_file_naming():
    print("\n[13] file_naming.build_dr_reports_filename")

    name = file_naming.build_dr_reports_filename("камбоджа_лаос_2026-02")
    check("дефолт self, PDF",
          name == "1_камбоджа_лаос_2026-02_dr_отчёты.pdf", f"got {name!r}")

    name2 = file_naming.build_dr_reports_filename("вьетнам_2023-09", ext="pdf")
    check("без _v{N} (один артефакт per trip)",
          "_v" not in name2 and name2.endswith(".pdf"),
          f"got {name2!r}")

    name3 = file_naming.build_dr_reports_filename(
        "корея_2024-03", recipient="parents",
    )
    check("recipient parents → суффикс",
          "для_родителей" in name3, f"got {name3!r}")


# ─── 14. build_pdf smoke ───────────────────────────────────────────────────


def test_build_pdf_smoke():
    print("\n[14] build_pdf smoke на КЛТ_1 (требует reportlab)")

    if not REPORTLAB_OK:
        skip("build_pdf", "reportlab не установлен")
        return
    if not KLT_STAGE1.exists():
        skip("build_pdf", f"нет фикстуры {KLT_STAGE1}")
        return

    text = KLT_STAGE1.read_text(encoding="utf-8")
    parsed = parser.parse_stage_text(text)
    extracted = stage1.extract_content(parsed)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        out_path = Path(f.name)
    try:
        stage1.build_pdf(extracted, out_path)
        check("PDF файл создан", out_path.exists())
        size = out_path.stat().st_size
        check("PDF размер > 50 KB (есть контент)", size > 50_000,
              f"got {size} bytes")
        # PDF header.
        with out_path.open("rb") as f:
            header = f.read(8)
        check("PDF magic header", header.startswith(b"%PDF-"),
              f"got {header!r}")
    finally:
        out_path.unlink(missing_ok=True)


# ─── 15. CLI integration ───────────────────────────────────────────────────


def test_cli_integration():
    print("\n[15] CLI: export.py --stage 1 → {trip_id}_dr_отчёты.pdf")

    if not REPORTLAB_OK:
        skip("CLI", "reportlab не установлен")
        return
    if not KLT_STAGE1.exists():
        skip("CLI", f"нет фикстуры {KLT_STAGE1}")
        return

    with tempfile.TemporaryDirectory() as tmp:
        cmd = [
            sys.executable,
            str(EXPORT_DIR / "export.py"),
            "--stage", "1",
            "--input", str(KLT_STAGE1),
            "--output-dir", tmp,
            "--trip", "камбоджа_лаос_2026-02",
            "--format", "pdf",   # дефолт экспорта с 2026-07-04 — html; тест про PDF-путь
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        check("exit code 0", result.returncode == 0,
              f"stderr: {result.stderr[:200]}")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            check("stdout — JSON", False, f"got: {result.stdout[:200]}")
            return
        check("RenderRequest.format = pdf",
              payload.get("format") == "pdf",
              f"got {payload.get('format')}")
        check("RenderRequest.content.stage = 1_dr_reports",
              payload["content"]["stage"] == "1_dr_reports",
              f"got {payload['content']}")
        # PDF с 2026-07 собирается из HTML (Chromium), а не reportlab: счётчиков
        # regions_count/cards_count в content больше нет. «37 карточек» и
        # де-регион «База отчётов» проверяются на extract_content выше.
        check("RenderRequest.content.engine = html→pdf",
              payload["content"].get("engine") == "html→pdf",
              f"got {payload['content']}")
        # Файл существует и имеет правильное имя.
        out_path = Path(payload["output_path"])
        check("файл существует", out_path.exists())
        check("имя файла = {trip_id}_dr_отчёты.pdf",
              out_path.name == "1_камбоджа_лаос_2026-02_dr_отчёты.pdf",
              f"got {out_path.name!r}")


# ─── Side badges / таблица покрытия — ярлыки из taxonomy (i18n 2c) ──────────


def test_side_badges_taxonomy():
    """Подписи side-бейджей и колонки critical — из taxonomy, не хардкод EN."""
    print("\n[2c] side badges + coverage header — русские ярлыки из taxonomy")

    def _card(**kw) -> stage1.Card:
        return stage1.Card(num=1, h3_suffix=None, fields={}, marker=None,
                           region_name="Тест", **kw)

    badges = stage1._build_card_side_badges(
        _card(is_critical=True, flags={"photo", "residence", "iconic"}))
    labels = [b[0] for b in badges]
    check("critical → «критика»", "критика" in labels, str(labels))
    check("photo → «фото-фокус»", "фото-фокус" in labels, str(labels))
    check("residence → «резидент»", "резидент" in labels, str(labels))
    check("iconic → «знаковый»", "знаковый" in labels, str(labels))
    check("сырых EN-бейджей нет",
          not any(l in ("critical", "iconic") for l in labels), str(labels))

    rows = stage1._coverage_table_rows({"cards": [], "meta": {}})
    check("шапка покрытия: последняя колонка «критика»",
          rows[0][-1] == "критика", str(rows[0]))


# ─── Main ───────────────────────────────────────────────────────────────────


def main() -> int:
    print("=" * 70)
    print("Регрессионные тесты: Stage 1 PDF builder (DR-база отчётов)")
    print("=" * 70)

    test_polish_markers()
    test_empty_values()
    test_card_field_parsing()
    test_url_title_extraction()
    test_tonality_focus()
    test_meta_parser()
    test_region_extraction()
    test_critical_detection()
    test_outline_title()
    test_card_bullets_drop_fields()
    test_rendering_cleanups()
    test_warnings_yaml_primary()
    test_extract_no_yaml()
    test_cover_yaml_regions_tempo_warnings()
    test_mode_b_curation_note()
    test_mode_b_curation_note_script_name_stripped()
    test_file_naming()
    test_build_pdf_smoke()
    test_cli_integration()
    test_deregion_card_finder()
    test_side_badges_taxonomy()

    print("\n" + "=" * 70)
    if checks_failed == 0:
        print(f"OK — все {checks_run} проверок прошли")
        return 0
    print(f"FAIL — {checks_failed}/{checks_run} проверок упали")
    return 1


def test_deregion_card_finder():
    print("\n[16] Де-регионизация: толерантный card-finder + покрытие")
    # Три формата заголовка карточки в одном файле, без регион-группировки.
    body = (
        "## Полная база отчётов (3)\n"
        "## КАРТОЧКА 1 (multi-region: Пекин + Сиань)\n1. URL: http://a\n"
        "### РЕГИОН 1 — Сапа (Sa Pa)\n"
        "**КАРТОЧКА 02** (Чжанцзяцзе с критикой)\n1. URL: http://b\n"
        "### Карточка 3\n1. URL: http://c\n"
    )
    cards = stage1._extract_all_cards({"body": body})
    check("найдены все 3 карточки (3 формата заголовка)", len(cards) == 3,
          f"got {[c.num for c in cards]}")
    nums = {c.num for c in cards}
    check("номера 1,2,3 (с ведущим нулём `02`)", nums == {1, 2, 3}, str(nums))
    cov = {c.num: c.covered_regions for c in cards}
    check("покрытие #1: Пекин+Сиань (из multi-region)",
          cov[1] == ["Пекин", "Сиань"], str(cov[1]))
    check("покрытие #2: Чжанцзяцзе (дескриптор «с критикой» отрезан)",
          cov[2] == ["Чжанцзяцзе"], str(cov[2]))
    check("покрытие #3: пусто (нет суффикса)", cov[3] == [], str(cov[3]))

    # `_parse_covered_regions` — шум не попадает.
    pcr = stage1._parse_covered_regions
    check("отброс tonality", pcr("(КРИТИЧЕСКИЙ — tonality: critical)") == [])
    check("отброс language/focus", pcr("(vi-источник)") == [] and pcr("(photography-focused)") == [])
    check("отброс all-caps `B1`", pcr("(B1 awd.ru)") == [])
    check("трим хвоста-POI", pcr("(Шанхай — Юй Юань)") == ["Шанхай"])

    # extract_content → один нейтральный псевдо-регион «База отчётов».
    parsed = parser.parse_stage_text("---\nstage: 1_dr_reports\n---\n" + body)
    ex = stage1.extract_content(parsed)
    check("один псевдо-регион «База отчётов» (де-регион)",
          len(ex["regions"]) == 1 and ex["regions"][0].name == "База отчётов")
    check("нет «Дополнительные карточки»",
          all(r.name != "Дополнительные карточки" for r in ex["regions"]))
    check("ex['cards'] = плоский список всех карточек", len(ex["cards"]) == 3)


if __name__ == "__main__":
    sys.exit(main())
