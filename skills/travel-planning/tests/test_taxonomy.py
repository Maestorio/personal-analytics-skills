#!/usr/bin/env python3
"""Тесты scripts/taxonomy.py — словарь таксонов (SSOT переводов).

Покрывают:
  - label/canon round-trip по всем группам × языкам (en/ru);
  - canon толерантен к регистру / ё / пробелам / подчёркиваниям;
  - алиасы («Спорные»/«СПОРНОЕ» → CONTESTED; «ВЫСОКОЕ СХОДСТВО» → HIGH);
  - отсутствие коллизий reverse-map внутри каждой группы;
  - pattern() матчит все ярлыки всех языков и не матчит пустую строку,
    длинные варианты раньше коротких;
  - неизвестный текст → None; неизвестная группа → ValueError;
  - default-язык = ru; канонический ключ резолвится сам в себя.

Запуск из корня репозитория:
    python3 skills/travel-planning/tests/test_taxonomy.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "skills" / "travel-planning" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import taxonomy  # noqa: E402

checks = 0
failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global checks, failed
    checks += 1
    if cond:
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}" + (f" — {detail}" if detail else ""))


GROUPS = taxonomy.groups()

print("[1] round-trip label/canon по всем группам × языкам")
for group in GROUPS:
    for key in taxonomy.keys(group):
        en = taxonomy.label(group, key, "en")
        ru = taxonomy.label(group, key, "ru")
        check(f"{group}.{key}: en/ru непусты",
              bool(en) and bool(ru), f"en={en!r} ru={ru!r}")
        check(f"{group}.{key}: canon(en)→key",
              taxonomy.canon(group, en) == key, f"got {taxonomy.canon(group, en)}")
        check(f"{group}.{key}: canon(ru)→key",
              taxonomy.canon(group, ru) == key, f"got {taxonomy.canon(group, ru)}")
        check(f"{group}.{key}: canon(сам ключ)→key",
              taxonomy.canon(group, key) == key)
        check(f"{group}.{key}: default-язык = ru",
              taxonomy.label(group, key) == ru)

print("\n[2] canon толерантен к регистру / ё / пробелам / подчёркиваниям")
check("регистр", taxonomy.canon("poi_category", "strong confirmed") == "STRONG_CONFIRMED")
check("подчёркивание ≈ пробел",
      taxonomy.canon("poi_category", "STRONG_CONFIRMED") == "STRONG_CONFIRMED")
check("лишние пробелы",
      taxonomy.canon("poi_category", "  STRONG   CONFIRMED ") == "STRONG_CONFIRMED")
check("ё→е (без оцёнки → UNSCORED)",
      taxonomy.canon("author_category", "без оцёнки") == "UNSCORED")
check("_norm('ёлка') == 'елка'", taxonomy._norm("Ёлка") == "елка")

print("\n[3] алиасы")
check("«Спорные» → CONTESTED", taxonomy.canon("poi_category", "Спорные") == "CONTESTED")
check("«СПОРНОЕ» → CONTESTED", taxonomy.canon("poi_category", "СПОРНОЕ") == "CONTESTED")
check("«ВЫСОКОЕ СХОДСТВО» → HIGH",
      taxonomy.canon("author_category", "ВЫСОКОЕ СХОДСТВО") == "HIGH")
check("рендер использует основной ru, не алиас",
      taxonomy.label("poi_category", "CONTESTED") == "СПОРНЫЙ")

print("\n[4] отсутствие коллизий reverse-map внутри группы")
for group in GROUPS:
    try:
        taxonomy._reverse(group)
        check(f"{group}: reverse-map без коллизий", True)
    except ValueError as e:  # pragma: no cover
        check(f"{group}: reverse-map без коллизий", False, str(e))

print("\n[5] pattern() матчит все ярлыки, не матчит пустое")
for group in GROUPS:
    pat = taxonomy.pattern(group)
    ok = True
    for entry in taxonomy._group(group).values():
        for form in taxonomy._forms(entry):
            if not re.fullmatch(pat, form):
                ok = False
    check(f"{group}: pattern матчит все формы", ok, pat)
    check(f"{group}: pattern НЕ матчит пустую строку",
          re.fullmatch(pat, "") is None)

print("\n[6] pattern: длинные варианты раньше коротких")
_forms = set()
for entry in taxonomy._group("poi_category").values():
    _forms.update(taxonomy._forms(entry))
_ordered = sorted(_forms, key=lambda s: (-len(s), s))
_expected = "(?:" + "|".join(re.escape(s) for s in _ordered) + ")"
check("pattern(poi_category) == ожидаемый (длина↓)",
      taxonomy.pattern("poi_category") == _expected)
# поведенческий: длинный ярлык матчится целиком
m = re.search(taxonomy.pattern("poi_category"), "тут СЛАБЫЙ СИГНАЛ есть")
check("длинный ярлык матчится целиком",
      m is not None and m.group() == "СЛАБЫЙ СИГНАЛ", m.group() if m else None)

print("\n[7] неизвестное / ошибки")
check("неизвестный текст → None", taxonomy.canon("poi_category", "блаблабла") is None)
check("пустой текст → None", taxonomy.canon("poi_category", "") is None)
check("None → None", taxonomy.canon("poi_category", None) is None)
check("label неизвестного ключа → как есть",
      taxonomy.label("poi_category", "НЕТТАКОГО") == "НЕТТАКОГО")
try:
    taxonomy.label("несуществующая_группа", "X")
    check("неизвестная группа → ValueError", False)
except ValueError:
    check("неизвестная группа → ValueError", True)

print("\n[8] метаданные словаря")
check("default_display_lang = ru", taxonomy.default_lang() == "ru")
check("POI в no_translate", "POI" in taxonomy.no_translate())
check("Deep Research в no_translate", "Deep Research" in taxonomy.no_translate())
check("17 групп терминов", len(GROUPS) == 17, str(GROUPS))

print("\n[8b] группы Фазы 2c: tempo + flag_badge")
check("tempo slow → размеренный", taxonomy.label("tempo", "slow") == "размеренный")
check("tempo moderate (алиас) → сбалансированный",
      taxonomy.label("tempo", "moderate") == "сбалансированный")
check("tempo fast (алиас) → активный", taxonomy.label("tempo", "fast") == "активный")
check("tempo rapid (алиас) → активный", taxonomy.label("tempo", "rapid") == "активный")
check("canon(активный) → active", taxonomy.canon("tempo", "активный") == "active")
check("flag_badge iconic → знаковый", taxonomy.label("flag_badge", "iconic") == "знаковый")
check("flag_badge iconic_status → знаковость",
      taxonomy.label("flag_badge", "iconic_status") == "знаковость")
check("flag_badge trap → ловушка", taxonomy.label("flag_badge", "trap") == "ловушка")
check("flag_badge combined_with → совмещать с",
      taxonomy.label("flag_badge", "combined_with") == "совмещать с")

print("\n[9] новые группы экспорта (Р2)")
check("content_density HIGH → высокая", taxonomy.label("content_density", "HIGH") == "высокая")
check("content_density MED (алиас) → средняя", taxonomy.label("content_density", "MED") == "средняя")
check("report_focus mix → микс", taxonomy.label("report_focus", "mix") == "микс")
check("report_focus приключения → адвенчура (норм.)",
      taxonomy.label("report_focus", "приключения") == "адвенчура")
check("report_tonality critical → критика", taxonomy.label("report_tonality", "critical") == "критика")
check("region_role_group core → Ядро поездки",
      taxonomy.label("region_role_group", "core") == "Ядро поездки")
check("short_label independence → самост.",
      taxonomy.short_label("similarity_component", "independence") == "самост.")
check("short_label без ru_short → полный label (fallback)",
      taxonomy.short_label("author_category", "HIGH") == taxonomy.label("author_category", "HIGH"))

print("\n[10] author_tag (Р11, батч 2 §5.3)")
check("user_added → добавлен вручную",
      taxonomy.label("author_tag", "user_added") == "добавлен вручную")
check("ext_reading → расш. чтение",
      taxonomy.label("author_tag", "ext_reading") == "расш. чтение")
check("canon: «ext. reading» (EN) → ext_reading",
      taxonomy.canon("author_tag", "ext. reading") == "ext_reading")
check("canon: «добавлен вручную» (RU) → user_added",
      taxonomy.canon("author_tag", "добавлен вручную") == "user_added")

print("\n[11] localize_terms / localize_labels (Фаза 2a — рендер-слой)")
# Свободный текст: DR пишет стиль прозой, а не enum'ом.
check("term: длинный термин раньше короткого",
      taxonomy.localize_terms("report_style", "mid-range independent") ==
      "миддл-сегмент самостоятельно")
check("term: разделители взаимозаменяемы (`_` ≡ `-` ≡ пробел)",
      taxonomy.localize_terms("report_style", "mid_range independent") ==
      "миддл-сегмент самостоятельно")
check("term: составное значение — по каждому термину",
      taxonomy.localize_terms("report_style", "backpacker / organized tour") ==
      "бэкпэкер / организованный тур")
check("term: регистр не важен, окружение сохраняется",
      taxonomy.localize_terms("report_style", "Стиль: Luxury (весь тур)") ==
      "Стиль: люкс (весь тур)")
check("term: незнакомый текст не трогается",
      taxonomy.localize_terms("report_style", "solo freelancer") ==
      "solo freelancer")
check("term: идемпотентность",
      taxonomy.localize_terms("report_style",
                              taxonomy.localize_terms("report_style", "backpacker")) ==
      "бэкпэкер")
check("term: пустой вход",
      taxonomy.localize_terms("report_style", "") == "" and
      taxonomy.localize_terms("report_style", None) == "")
check("term: подстрока внутри слова не матчится",
      taxonomy.localize_terms("report_style", "familyhotel") == "familyhotel")

# Лейблы: подмена ТОЛЬКО перед двоеточием — короткие слова-метки (`Country`,
# `Math`) в свободной фразе значат не то же самое.
check("label: `**Tempo:**` → `**Темп:**`",
      taxonomy.localize_labels("scope_labels", "- **Tempo:** balanced") ==
      "- **Темп:** balanced")
check("label: без bold тоже",
      taxonomy.localize_labels("scope_labels", "- Tempo: balanced") ==
      "- Темп: balanced")
check("label: вне позиции лида — не трогаем",
      taxonomy.localize_labels("scope_labels", "маршрут cross-country") ==
      "маршрут cross-country")
check("label: localize_terms подменил бы и вне лида (разница механизмов)",
      taxonomy.localize_terms("scope_labels", "маршрут cross-country") !=
      "маршрут cross-country")
check("scope_format: ключ enum → русский ярлык",
      taxonomy.localize_terms("scope_format", "scope = explicit_list") ==
      "scope = явный список")
check("scope_format: label() ключа",
      taxonomy.label("scope_format", "single_base") == "одна база")

print(f"\n{'=' * 60}")
print(f"taxonomy: {checks} проверок, {failed} провалено")
print(f"{'=' * 60}")
sys.exit(1 if failed else 0)
