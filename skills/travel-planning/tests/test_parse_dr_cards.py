#!/usr/bin/env python3
"""Регрессионные тесты для parse_dr_cards.py.

Запуск из корня репозитория:
    python3 skills/travel-planning/tests/test_parse_dr_cards.py

Stdlib only. Без внешних файлов.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "travel-planning" / "scripts" / "parse_dr_cards.py"

sys.path.insert(0, str(SCRIPT.parent))
from parse_dr_cards import (  # noqa: E402
    build_diagnostic,
    extract_name,
    extract_reports_count,
    extract_url,
    normalize_dr_text,
    parse_card,
    slug_from,
    split_into_cards,
)


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


# ─── 1. extract_url ──────────────────────────────────────────────────────

def test_extract_url():
    print("\n[1] extract_url")

    check("https URL", extract_url("text https://example.com/path more") == "https://example.com/path")
    check("http URL", extract_url("http://test.org/x") == "http://test.org/x")
    check("URL с trailing punct", extract_url("see https://x.com/a.") == "https://x.com/a")
    check("URL в markdown ссылке",
          extract_url("[Title](https://forum.awd.ru/viewtopic.php?t=123)") == "https://forum.awd.ru/viewtopic.php?t=123")
    check("нет URL → пустая строка", extract_url("no link here") == "")
    check("первый URL из нескольких",
          extract_url("https://a.com\nhttps://b.com") == "https://a.com")


# ─── 2. extract_name ─────────────────────────────────────────────────────

def test_extract_name():
    print("\n[2] extract_name")

    # Из заголовка ### #5 helvhrav
    card = "### #5 helvhrav\n\n**1. URL:** https://example.com"
    check("из заголовка '### #5 Имя'", extract_name(card) == "helvhrav")

    # Из заголовка ## Имя автора
    card = "## Maria Dol\n\n1. URL: https://example.com"
    check("из заголовка '## Имя'", extract_name(card) == "Maria Dol")

    # Из заголовка с (user_added)
    card = "### #27 helvhrav (user_added)\n\n1. URL: https://example.com"
    check("заголовок чистится от (user_added)",
          extract_name(card) == "helvhrav",
          f"got '{extract_name(card)}'")

    # Из поля 3
    card = "**1. URL:** https://example.com\n\n**3. Имя автора:** Иван Петров"
    name = extract_name(card)
    check("из поля 3 'Имя автора: …'",
          "Иван Петров" in name,
          f"got '{name}'")

    # Заголовок 'Отчёт 5: Title' → Title (без префикса)
    card = "### Отчёт 5: Кругосветка по Патагонии\n\n1. URL: https://x.com"
    check("заголовок чистится от 'Отчёт N:'",
          "Кругосветка" in extract_name(card),
          f"got '{extract_name(card)}'")

    # Нет имени — пустая строка (LLM проставит)
    card = "**1. URL:** https://example.com\n\nраздел без имени"
    check("нет имени → пустая строка",
          len(extract_name(card)) <= 2 or extract_name(card) == "")


# ─── 3. slug_from ────────────────────────────────────────────────────────

def test_slug_from():
    print("\n[3] slug_from")
    check("latin", slug_from("vietnam-2026-09") == "vietnam-2026-09")
    check("cyrillic transliterated",
          slug_from("вьетнам_север_2023") == "vetnam_sever_2023",
          f"got '{slug_from('вьетнам_север_2023')}'")
    check("аргентина_юг → argentina_yug",
          slug_from("аргентина_юг_2025-03") == "argentina_yug_2025-03",
          f"got '{slug_from('аргентина_юг_2025-03')}'")
    check("пустой → пустой", slug_from("") == "")
    check("обрезается до 30",
          len(slug_from("a" * 50)) == 30)
    check("замена пробелов на дефис",
          slug_from("hello world") == "hello-world")


# ─── 4. split_into_cards ─────────────────────────────────────────────────

def test_split_into_cards():
    print("\n[4] split_into_cards")

    # Формат 1: разделители ---
    text = """---
trip_id: test
---

### Отчёт 1: A
1. URL: https://a.com

---

### Отчёт 2: B
1. URL: https://b.com

---

### Отчёт 3: C
1. URL: https://c.com
"""
    cards = split_into_cards(text)
    check("3 карточки через ---", len(cards) == 3, f"got {len(cards)}")
    check("каждая карточка содержит URL",
          all("http" in c for c in cards))

    # Формат 2: заголовки ###
    text2 = """### Карточка 1: Author1
URL: https://a.com
content

### Карточка 2: Author2
URL: https://b.com
content

### Карточка 3: Author3
URL: https://c.com
content
"""
    cards = split_into_cards(text2)
    check("3 карточки через ###", len(cards) == 3, f"got {len(cards)}")

    # Формат 3: смешанные уровни заголовков
    text3 = """## Section header

### #1 Foo
https://a.com

### #2 Bar
https://b.com

### #3 Baz
https://c.com
"""
    cards = split_into_cards(text3)
    check("split по разноуровневым заголовкам — без падения",
          len(cards) >= 3)

    # Формат 4: пустой или без URL
    text4 = "Just some text without links."
    cards = split_into_cards(text4)
    check("нет URL → пустой список", cards == [])


# ─── 5. parse_card ──────────────────────────────────────────────────────

def test_parse_card():
    print("\n[5] parse_card")

    card = """### #5 helvhrav

**1. URL:** https://forum.awd.ru/viewtopic.php?t=422593
**2. Платформа:** forum.awd.ru
**3. Имя или ник автора:** helvhrav

(user_added)

Lots of report content here...
"""
    result = parse_card(card, idx=5, trip_slug="arg-2025-03")

    check("id = '{slug}-005'", result["id"] == "arg-2025-03-005")
    check("url извлечён",
          result["url"] == "https://forum.awd.ru/viewtopic.php?t=422593")
    check("name = helvhrav", result["name"] == "helvhrav")
    check("user_added = True", result["user_added"] is True)
    # F-27.D: diagnostic-only — нет raw_card_text/components/outlier_signal.
    check("нет raw_card_text (F-27.D)", "raw_card_text" not in result)
    check("нет components (F-27.D)", "components" not in result)
    check("нет outlier_signal (F-27.D)", "outlier_signal" not in result)
    check("результат содержит только id/url/name/user_added",
          set(result.keys()) == {"id", "url", "name", "user_added"})

    # Без user_added маркера
    card2 = """### Maria Dol
URL: https://mapandcamera.com/ushuaia-end-of-the-world/
Some content.
"""
    result = parse_card(card2, idx=1, trip_slug="arg")
    check("user_added = False (нет маркера)", result["user_added"] is False)
    check("name = Maria Dol", result["name"] == "Maria Dol",
          f"got '{result['name']}'")


# ─── 6. subprocess end-to-end ───────────────────────────────────────────

def test_subprocess_end_to_end():
    print("\n[6] subprocess end-to-end")

    dr_file = """---
trip_id: vietnam-2026-09
stage: 1_dr_reports
reports_count: 3
---

### #1 Tom Divers (Vietnam Coracle)

**1. URL:** https://www.vietnamcoracle.com/bac-ha-sunday-market/
**2. Платформа:** Vietnam Coracle (блог)
**3. Имя или ник автора:** Tom Divers
**4. Дата публикации:** 2018

[content]

---

### #2 Emily Lush (user_added)

**1. URL:** https://wander-lush.org/duong-lam-ancient-village-hanoi-day-trip/
**2. Платформа:** Wander-Lush
**3. Имя или ник автора:** Emily Lush

[content]

---

### #3 helvhrav

**1. URL:** https://forum.awd.ru/viewtopic.php?t=422593
**3. Имя или ник автора:** helvhrav

[content]
"""

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--trip-slug", "vietnam-2026-09"],
        input=dr_file,
        capture_output=True,
        text=True,
    )
    check("subprocess exit 0", result.returncode == 0,
          f"stderr: {result.stderr}")

    output = json.loads(result.stdout)
    check("trip_slug в output",
          output["trip_slug"] == "vietnam-2026-09")
    check("total_cards = 3", output["total_cards"] == 3,
          f"got {output['total_cards']}")
    # F-27.D: output key — card_summaries (не authors).
    check("ключ 'card_summaries' в output (F-27.D)",
          "card_summaries" in output)
    check("нет ключа 'authors' (F-27.D)", "authors" not in output)
    check("card_summaries[0].id = vietnam-2026-09-001",
          output["card_summaries"][0]["id"] == "vietnam-2026-09-001")
    check("card_summaries[0].url правильный",
          "vietnamcoracle.com" in output["card_summaries"][0]["url"])
    check("card_summaries[1].user_added = True (по маркеру)",
          output["card_summaries"][1]["user_added"] is True)
    check("card_summaries[2].user_added = False",
          output["card_summaries"][2]["user_added"] is False)
    # F-27.D: card_summaries содержит только id/url/name/user_added (без components).
    check("card_summaries не содержит components (F-27.D)",
          all("components" not in a for a in output["card_summaries"]))
    check("card_summaries не содержит raw_card_text (F-27.D)",
          all("raw_card_text" not in a for a in output["card_summaries"]))

    # v0.9: пустой stdin → exit 2 (невалидный input)
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input="",
        capture_output=True,
        text=True,
    )
    check("empty stdin → exit 2", result.returncode == 2)

    # v0.9: совсем нет карточек → exit 1
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input="just text no url no cards",
        capture_output=True,
        text=True,
    )
    check("zero cards → exit 1", result.returncode == 1)

    # v0.9: мало карточек (1, min=3) → exit 0 + diagnostic.status=error
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--min-cards", "3"],
        input="### Single\nhttps://only-one.com",
        capture_output=True,
        text=True,
    )
    check("1 карточка < min=3 → exit 0 (diagnostic)", result.returncode == 0)
    output = json.loads(result.stdout)
    check("1 < min=3: diagnostic.status = error",
          output["diagnostic"]["status"] == "error")
    too_few = [i for i in output["diagnostic"]["issues"]
               if i["code"] == "too_few_cards"]
    check("too_few_cards issue присутствует", len(too_few) == 1)

    # min=1, та же одна карточка → проходит
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--min-cards", "1", "--trip-slug", "test"],
        input="### Single Author\nhttps://only-one.com",
        capture_output=True,
        text=True,
    )
    check("--min-cards 1 проходит", result.returncode == 0)


# ─── 7. extract_reports_count (v0.9) ─────────────────────────────────────

def test_extract_reports_count():
    print("\n[7] extract_reports_count")

    yaml_with = """---
trip_id: vietnam-2026-09
stage: 1_dr_reports
reports_count: 39
created: 2026-05-22
---

### content
"""
    check("reports_count=39 извлечён",
          extract_reports_count(yaml_with) == 39)

    yaml_without = """---
trip_id: x
stage: 1_dr_reports
---

content
"""
    check("нет reports_count → None",
          extract_reports_count(yaml_without) is None)

    no_yaml = "Just markdown without frontmatter\nreports_count: 5"
    check("нет YAML frontmatter → None",
          extract_reports_count(no_yaml) is None)


# ─── 8. build_diagnostic (v0.9) ──────────────────────────────────────────

def test_build_diagnostic():
    print("\n[8] build_diagnostic")

    def make_minimal_author(id, url="https://x.com", name="A"):
        return {"id": id, "url": url, "name": name}

    # All perfect → ok
    authors = [make_minimal_author(f"a{i}") for i in range(10)]
    d = build_diagnostic(authors, expected_count=10)
    check("perfect parse → status=ok", d["status"] == "ok", f"got {d['status']}")
    check("found_cards=10", d["found_cards"] == 10)
    check("expected_cards=10", d["expected_cards"] == 10)
    check("no URL/name pop", d["cards_without_url"] == [] and d["cards_without_name"] == [])

    # 30% без URL → error
    authors = [make_minimal_author(f"a{i}", url="") for i in range(3)]
    authors += [make_minimal_author(f"a{i}") for i in range(7)]
    d = build_diagnostic(authors, expected_count=10)
    check("30% без URL → status=error", d["status"] == "error", f"got {d['status']}")
    url_issues = [i for i in d["issues"] if i["code"] == "url_missing_high"]
    check("url_missing_high issue", len(url_issues) == 1)

    # 10% без URL → warning, не error
    authors = [make_minimal_author("a0", url="")]
    authors += [make_minimal_author(f"a{i}") for i in range(1, 10)]
    d = build_diagnostic(authors, expected_count=10)
    check("10% без URL → status=warning",
          d["status"] == "warning",
          f"got {d['status']}")

    # 30% без name → warning, не error
    authors = [make_minimal_author(f"a{i}", name="") for i in range(3)]
    authors += [make_minimal_author(f"a{i}") for i in range(7)]
    d = build_diagnostic(authors, expected_count=10)
    check("30% без name → status=warning (не error)",
          d["status"] == "warning",
          f"got {d['status']}")

    # expected=28, found=10 → error (mismatch > 20%)
    authors = [make_minimal_author(f"a{i}") for i in range(10)]
    d = build_diagnostic(authors, expected_count=28)
    check("expected=28, found=10 → error",
          d["status"] == "error",
          f"got {d['status']}")
    mismatch = [i for i in d["issues"] if i["code"] == "count_mismatch_high"]
    check("count_mismatch_high issue", len(mismatch) == 1)

    # expected=28, found=26 → warning (расхождение 7%)
    authors = [make_minimal_author(f"a{i}") for i in range(26)]
    d = build_diagnostic(authors, expected_count=28)
    check("expected=28, found=26 → warning (расхождение 7%)",
          d["status"] == "warning",
          f"got {d['status']}")

    # expected=None → не сверяется, но info count_not_verifiable surfaced
    authors = [make_minimal_author(f"a{i}") for i in range(10)]
    d = build_diagnostic(authors, expected_count=None)
    check("expected=None → status=ok (без сверки)",
          d["status"] == "ok")
    check("expected_cards=None в output",
          d["expected_cards"] is None)
    check("expected=None → info count_not_verifiable (не молчит)",
          any(i["code"] == "count_not_verifiable" for i in d["issues"]))

    # require_count=True (emit-gate Stage 1): отсутствие reports_count → error
    d = build_diagnostic(authors, expected_count=None, require_count=True)
    check("require_count + expected=None → status=error",
          d["status"] == "error")
    check("require_count → code count_required_missing (не info)",
          any(i["code"] == "count_required_missing" for i in d["issues"]))
    check("require_count → нет мягкого count_not_verifiable",
          not any(i["code"] == "count_not_verifiable" for i in d["issues"]))
    # require_count при наличии expected → обычная сверка, не блокирует
    d = build_diagnostic(authors, expected_count=10, require_count=True)
    check("require_count + count совпал → status=ok",
          d["status"] == "ok")


# ─── 9. subprocess: diagnostic в output (v0.9) ──────────────────────────

def test_subprocess_diagnostic():
    print("\n[9] subprocess: diagnostic в output")

    # Файл с reports_count=3, и 3 валидные карточки → ok
    dr = """---
trip_id: test
reports_count: 3
---

### #1 Alice
https://a.com

### #2 Bob
https://b.com

### #3 Charlie
https://c.com
"""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=dr,
        capture_output=True,
        text=True,
    )
    output = json.loads(result.stdout)
    check("diagnostic присутствует в output",
          "diagnostic" in output)
    check("diagnostic.status=ok при чистом парсе",
          output["diagnostic"]["status"] == "ok")
    check("expected_cards=3", output["expected_cards"] == 3)

    # Файл с reports_count=20, найдено 3 → error
    dr_mismatch = """---
trip_id: test
reports_count: 20
---

### #1 A
https://a.com

### #2 B
https://b.com

### #3 C
https://c.com
"""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=dr_mismatch,
        capture_output=True,
        text=True,
    )
    output = json.loads(result.stdout)
    check("count mismatch → diagnostic.status=error",
          output["diagnostic"]["status"] == "error")
    check("expected_cards=20", output["expected_cards"] == 20)


# ─── 10. F-27.D: parse_method поле удалено (diagnostic-only) ────────────

def test_no_parse_method_field():
    print("\n[10] F-27.D: parse_method поле удалено")
    card = "### #1 X\nhttps://x.com"
    result = parse_card(card, idx=1, trip_slug="t")
    check("нет parse_method (diagnostic-only режим)",
          "parse_method" not in result)


# ─── 11. split_into_cards — маркеры карточек + ----- (реальный DR-формат) ─

def test_split_robust_markers():
    print("\n[11] split_into_cards — маркеры + -----")

    # Bold-маркеры `**КАРТОЧКА N**` + 5-дефисные разделители + region-заголовки.
    text = """---
trip_id: t
---

### РЕГИОН 1 — ХАНОЙ
-----
**КАРТОЧКА 01**
**1. URL:** https://a.com
**3. Имя автора:** Alice
-----
**КАРТОЧКА 02**
**1. URL:** https://b.com
**3. Имя автора:** Bob
-----
### РЕГИОН 2 — НИНЬБИНЬ
-----
**КАРТОЧКА 03**
**1. URL:** https://c.com
**3. Имя автора:** Carol
"""
    cards = split_into_cards(text)
    check("3 карточки через bold-маркеры + -----",
          len(cards) == 3, f"got {len(cards)}")
    check("region-заголовки не попали внутрь карточек",
          all("РЕГИОН" not in c for c in cards))
    names = [extract_name(c) for c in cards]
    check("имя карточки 1 = Alice (region-заголовок не перебил)",
          names[0] == "Alice", f"got {names!r}")

    # Пропущенный разделитель между карточками — маркеры всё равно ловят все.
    text2 = """**КАРТОЧКА 1**
**1. URL:** https://a.com
**КАРТОЧКА 2**
**1. URL:** https://b.com
**КАРТОЧКА 3**
**1. URL:** https://c.com
"""
    cards = split_into_cards(text2)
    check("3 карточки по маркерам без разделителей",
          len(cards) == 3, f"got {len(cards)}")

    # Section-заголовок «Карточки 1–30» (plural + диапазон) НЕ карточка.
    text3 = """### Карточки 1–30 — Deep Research
**КАРТОЧКА 1**
https://a.com
**КАРТОЧКА 2**
https://b.com
**КАРТОЧКА 3**
https://c.com
"""
    cards = split_into_cards(text3)
    check("section-заголовок 'Карточки 1–30' не считается карточкой",
          len(cards) == 3, f"got {len(cards)}")

    # `## КАРТОЧКА N` (канонический heading-формат) тоже ловится.
    text4 = """## КАРТОЧКА 1
https://a.com
## КАРТОЧКА 2
https://b.com
## КАРТОЧКА 3
https://c.com
"""
    check("канонический '## КАРТОЧКА N' → 3 карточки",
          len(split_into_cards(text4)) == 3)


# ─── 12. normalize_dr_text ───────────────────────────────────────────────

def test_normalize_dr_text():
    print("\n[12] normalize_dr_text")

    text = """---
trip_id: t
reports_count: 3
---

### РЕГИОН 1 — ХАНОЙ
-----
**КАРТОЧКА 05** (multi-region: X + Y)
**1. URL:** https://a.com
-----
**КАРТОЧКА 52** — [B1 awd.ru: Z]
**1. URL:** https://b.com
-----
### РЕГИОН 2
-----
## КАРТОЧКА 31
**1. URL:** https://c.com
"""
    out, n = normalize_dr_text(text)
    check("3 карточки канонизировано", n == 3, f"got {n}")
    check("сквозная перенумерация 1..3 по порядку документа",
          "## КАРТОЧКА 1 " in out and "## КАРТОЧКА 2 " in out
          and "## КАРТОЧКА 3" in out, out)
    check("аннотация в скобках сохранена",
          "(multi-region: X + Y)" in out)
    check("аннотация через тире/скобки сохранена",
          "— [B1 awd.ru: Z]" in out)
    check("разделители ----- убраны", "-----" not in out)
    check("region-заголовки сохранены",
          "### РЕГИОН 1 — ХАНОЙ" in out and "### РЕГИОН 2" in out)
    check("YAML frontmatter сохранён", out.startswith("---\ntrip_id: t"))
    check("старых bold-маркеров не осталось", "**КАРТОЧКА" not in out)

    # Идемпотентность по числу карточек.
    out2, n2 = normalize_dr_text(out)
    check("повторный normalize идемпотентен (3 карточки)",
          n2 == 3, f"got {n2}")

    # Нормализованный файл ре-парсится без потерь.
    cards = split_into_cards(out)
    check("normalize → split: 3 карточки, все с URL",
          len(cards) == 3 and all("http" in c for c in cards),
          f"got {len(cards)}")


# ─── 13. subprocess --normalize ──────────────────────────────────────────

def test_subprocess_normalize():
    print("\n[13] subprocess --normalize")
    dr = """---
trip_id: t
---
-----
**КАРТОЧКА 01**
**1. URL:** https://a.com
-----
**КАРТОЧКА 02**
**1. URL:** https://b.com
-----
**КАРТОЧКА 03**
**1. URL:** https://c.com
"""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--normalize"],
        input=dr, capture_output=True, text=True,
    )
    check("--normalize exit 0", result.returncode == 0, result.stderr)
    check("stdout содержит '## КАРТОЧКА 1'",
          "## КАРТОЧКА 1" in result.stdout)
    check("stdout без bold-маркеров",
          "**КАРТОЧКА" not in result.stdout)
    check("stderr сообщает число карточек",
          "канонизировано: 3" in result.stderr, result.stderr)

    # Пост-проверка: не-DR текст без маркеров → exit 1 + причина в stderr,
    # а не молчаливый «странный» вывод.
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--normalize"],
        input="просто текст без карточек https://x.com\n",
        capture_output=True, text=True,
    )
    check("--normalize без маркеров → exit 1",
          result.returncode == 1, f"rc={result.returncode}")
    check("--normalize без маркеров → причина в stderr",
          "не распознан" in result.stderr)


# ─── main ────────────────────────────────────────────────────────────────

def main():
    test_extract_url()
    test_extract_name()
    test_slug_from()
    test_split_into_cards()
    test_parse_card()
    test_subprocess_end_to_end()
    test_extract_reports_count()
    test_build_diagnostic()
    test_subprocess_diagnostic()
    test_no_parse_method_field()
    test_split_robust_markers()
    test_normalize_dr_text()
    test_subprocess_normalize()

    print(f"\n{'=' * 50}")
    print(f"Всего проверок: {checks_run}, провалов: {checks_failed}")
    if checks_failed:
        print("FAIL")
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
