"""Тесты scripts/export/polish_check.py — source↔polished diff-гейт.

Фокус: симметрия H2-сравнения при prefix-match (Stage 1 T4 переименовывает
суффиксы заголовков карточек — `КАРТОЧКА 2 (multi-region: …)` → `КАРТОЧКА 2
(…)`, снятие `user_added, B1 awd.ru`). Раньше «added»-сторона диффа
сравнивала RAW polished-заголовки с НОРМАЛИЗОВАННЫМ src_set → ложный
«H2 добавлен polish'ом». Фикс: обе стороны через `_h2_set_normalized`.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "skills" / "travel-planning" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from export import polish_check as pc  # noqa: E402

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


# Наполнитель, чтобы length-ratio не шумел (реальные файлы крупные).
_PAD = "\n".join("1. **Поле:** значение достаточно длинное для веса строки " * 2
                 for _ in range(8))


def _card(h: str) -> str:
    return f"## {h}\n{_PAD}\n"


_SRC = (
    "---\nstage: 1_dr_reports\ntrip_id: t\n---\n"
    + _card("КАРТОЧКА 1")
    + _card("КАРТОЧКА 2 (multi-region: Пекин + Сиань)")
    + _card("КАРТОЧКА 29 (user_added, B1 awd.ru)")
    + "## WARNINGs\n- предупреждение одно\n- предупреждение два\n"
)


print("[1] _h2_prefix — срез счётчика/суффикса")
check("`(...)`-суффикс срезан",
      pc._h2_prefix("КАРТОЧКА 2 (multi-region: Пекин)") == "КАРТОЧКА 2")
check("`user_added`-суффикс срезан",
      pc._h2_prefix("КАРТОЧКА 29 (user_added, B1 awd.ru)") == "КАРТОЧКА 29")
check("без суффикса не меняется", pc._h2_prefix("КАРТОЧКА 1") == "КАРТОЧКА 1")
check("хвост после ` — ` срезан",
      pc._h2_prefix("Reading list — для Stage 3") == "Reading list")

print("\n[2] _h2_set_normalized — prefix-only при prefix_match")
prof_pm = {"h2_prefix_match": True, "h2_synonyms": {}}
s = pc._h2_set_normalized(["КАРТОЧКА 2 (multi-region: X)"], prof_pm)
check("prefix-match: множество содержит ТОЛЬКО префикс",
      s == {"КАРТОЧКА 2"}, str(s))
prof_no = {"h2_prefix_match": False, "h2_synonyms": {}}
s2 = pc._h2_set_normalized(["КАРТОЧКА 2 (X)"], prof_no)
check("без prefix-match: полная форма", s2 == {"КАРТОЧКА 2 (X)"}, str(s2))

print("\n[3] Stage 1 T4-переименование — НЕ нарушение (ядро фикса)")
pol_ok = (
    "---\nstage: 1_dr_reports\ntrip_id: t\n---\n[[поездка: Китай]]\n"
    + _card("КАРТОЧКА 1")
    + _card("КАРТОЧКА 2 (Пекин + Сиань)")          # снят `multi-region:`
    + _card("КАРТОЧКА 29")                          # снят `(user_added, …)`
)
r1 = pc.check_polish(_SRC, pol_ok)
check("ok=True (нет ложных H2-нарушений)", r1.ok, f"violations={r1.violations}")
check("ноль violations", len(r1.violations) == 0, str(r1.violations))
check("WARNINGs-удаление → warning, не violation",
      any("WARNINGs" in w for w in r1.warnings))

print("\n[4] negative — реальное удаление карточки ловится")
pol_del = (
    "---\nstage: 1_dr_reports\ntrip_id: t\n---\n"
    + _card("КАРТОЧКА 1") + _card("КАРТОЧКА 29")
    + "## WARNINGs\n- x\n- y\n"
)
r2 = pc.check_polish(_SRC, pol_del)
check("ok=False при удалении карточки", not r2.ok)
check("«КАРТОЧКА 2 отсутствует» в violations",
      any("КАРТОЧКА 2" in v and "отсутств" in v for v in r2.violations),
      str(r2.violations))

print("\n[5] negative — выдуманная секция ловится")
pol_invent = (
    "---\nstage: 1_dr_reports\ntrip_id: t\n---\n"
    + _card("КАРТОЧКА 1")
    + _card("КАРТОЧКА 2 (Пекин)")
    + _card("КАРТОЧКА 29")
    + _card("ВЫДУМАННАЯ СЕКЦИЯ")
)
r3 = pc.check_polish(_SRC, pol_invent)
check("выдуманный H2 → violation",
      any("ВЫДУМАННАЯ" in v and "добавлен" in v for v in r3.violations),
      str(r3.violations))

print("\n[6] firewall: делимитер/CRLF/цифра-stage + Counter дублей")
# `-----`-делимитер + CRLF → тот же профиль, что `---`.
y, b = pc._split_yaml_body("-----\r\nstage: 0_scope\r\n-----\r\n\r\nбоди\r\n")
check("split `-----`+CRLF → yaml+body", y.strip() == "stage: 0_scope" and b.strip() == "боди")
# Профиль по лидирующей цифре (`stage: 0`).
check("профиль по цифре stage 0", pc._profile_for({"stage": "0"}) is pc.STAGE_PROFILES["0_scope"])
check("_profile_matched: 0 распознан, xyz — нет",
      pc._profile_matched({"stage": "0"}) and not pc._profile_matched({"stage": "xyz"}))
# inline-comment на скаляре срезается.
check("flat: inline-comment срезан", pc._parse_yaml_flat("stage: 5  # финал")["stage"] == "5")
# Counter: удаление одного из двух одноимённых H2 ловится.
_dup_src = "---\nstage: 5_final_plan\ntrip_id: t\n---\n\n## X\na\n## Углубления\nb\n## Углубления\nc\n"
_dup_pol = "---\nstage: 5_final_plan\ntrip_id: t\n---\n\n## X\na\n## Углубления\nb\n"
check("Counter: потеря дубль-H2 → violation",
      any("дублирующая" in v for v in pc.check_polish(_dup_src, _dup_pol).violations))


print("\n[7] бюджет «Углублений» Stage 6 (≤5 предложений + источник)")
# Гейт стоит в скрипте, а не только в каноне, намеренно: инструкция «сохранить
# polished.md» в том же каноне есть и систематически пропускается.
_enr = lambda body: pc.check_enrichment_budget("## Углубления\n\n" + body)
check("5 предложений + источник — норма",
      _enr("### Ханой\nОдин. Два. Три. Четыре. Пять.\nИсточник: https://e.org/h\n") == [])
check("6 предложений — нарушение",
      any("6 предложений" in m for _, m in
          _enr("### Сапа\nРаз. Два. Три. Четыре. Пять. Шесть.\nИсточник: https://e.org/s\n")))
check("без источника — нарушение",
      any("нет строки источника" in m for _, m in _enr("### МСС\nТеррасы хмонгов.\n")))
check("оба нарушения ловятся вместе",
      len(_enr("### X\nА. Б. В. Г. Д. Е. Ж.\n")) == 2)
check("секции «Углубления» нет → нарушений нет",
      pc.check_enrichment_budget("## Дорожное досье\n\nВизы.\n") == [])
# Сокращения с точкой («ок. 968 г.», «в т.ч.») не должны считаться концом
# предложения — иначе гейт заваливал бы нормальные исторические справки.
check("сокращения с точкой не раздувают счёт",
      _enr("### Ниньбинь\nСтолица X в. (ок. 968 г.) в карстовой долине. "
           "Позже двор ушёл в Тханглонг.\nИсточник: https://e.org/nb\n") == [])
check("«Источники —» тоже считается провенансом",
      _enr("### Y\nОдин. Два.\nИсточники — https://e.org/y\n") == [])
# Строка источника не должна съедать бюджет содержания.
check("строка источника не входит в лимит",
      _enr("### Z\nОдин. Два. Три. Четыре. Пять.\nИсточник: https://e.org/z\n") == [])

print(f"\n{'=' * 60}")
print(f"polish_check: {checks} проверок, {failed} провалено")
print(f"{'=' * 60}")
sys.exit(1 if failed else 0)
