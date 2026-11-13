#!/usr/bin/env python3
"""Регрессионные тесты для Stage 5 PDF builder (Step 2).

Покрывают:
  - parse_day_block: эмодзи-маркеры, intro, multi-line content
  - split_bullets_and_intro: bullet-list под маркером
  - extract_tables_and_text: чередование md-таблиц и текста
  - extract_content: полный pipeline на Vietnam fixture
  - md_inline_to_rl: эскейп XML, bold/italic/код/links/TODO
  - TODO-regex не ломает уже встроенные `<b>...</b>`
  - build_pdf: фактическая генерация (требует reportlab)
  - CLI integration: export.py --stage 5

Запуск из корня репозитория:
    python3 skills/travel-planning/tests/test_export_stage5.py

Тесты build_pdf и CLI пропускаются, если reportlab не установлен.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPORT_DIR = REPO_ROOT / "skills" / "travel-planning" / "scripts" / "export"
VIETNAM_STAGE5 = REPO_ROOT / "docs" / "travel-planning" / "calibration" / "вьетнам" / "5_final_plan.md"

sys.path.insert(0, str(EXPORT_DIR.parent))
from export import parser, adapter  # noqa: E402
from export.stages import stage5     # noqa: E402

# pdf_lib — soft-import; если reportlab не установлен, пропускаем PDF-тесты.
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


# ─── Fixtures ────────────────────────────────────────────────────────────


SIMPLE_DAY = {
    "level": 3,
    "heading": "День 1 (03.03 Пн). Прилёт в Ушуаю, Ледник Мартиаль",
    "body": """📍 Прилёт в Буэнос-Айрес → трансфер EZE→AEP.
🏨 **Alto Andino Hotel**, центр Ушуаи. — ночи 1, 2, 3.

🎯 **Программа:**
- Заселение, ориентировка по центру.
- **Ледник Мартиаль.** Тропа стартует у базы.

💰 ~5 000–9 000 ₽

⚠️ Мартиаль реалистичен только при прилёте до 14:00.""",
    "subsections": [],
}


# ─── 1. parse_day_block ──────────────────────────────────────────────────


def test_parse_day_block():
    print("\n[1] parse_day_block")

    day = stage5.parse_day_block(SIMPLE_DAY)
    check("day_num=1", day.day_num == 1)
    check("heading сохранён", "Прилёт в Ушуаю" in day.heading)
    check("markers содержит 5 блоков", len(day.markers) == 5)

    icons = [m.icon for m in day.markers]
    check("первый маркер 📍", icons[0] == "📍")
    check("второй маркер 🏨", icons[1] == "🏨")
    check("третий маркер 🎯", icons[2] == "🎯")
    check("четвёртый маркер 💰", icons[3] == "💰")
    check("пятый маркер ⚠️", icons[4] == "⚠️")

    labels = [m.label for m in day.markers]
    check("label локация", labels[0] == "Локация")
    check("label отель", labels[1] == "Отель")

    # Программа = многострочный + bullets.
    program = day.markers[2]
    check("🎯 содержит bullets маркер", program.is_bullets)
    check("🎯 текст начинается с **Программа:**",
          program.content.startswith("**Программа:**"),
          f"content: {program.content[:50]!r}")

    # Бюджет = одна строка.
    budget = day.markers[3]
    check("💰 одна строка", "\n" not in budget.content)


def test_parse_day_block_edge_cases():
    print("\n[1b] parse_day_block — edge cases")

    # День без некоторых маркеров (только 📍 и 🎯).
    minimal = {
        "level": 3,
        "heading": "День 5. Свободный день",
        "body": "📍 Город Бариломье\n🎯 Прогулка по набережной.",
        "subsections": [],
    }
    day = stage5.parse_day_block(minimal)
    check("minimal day → 2 маркера", len(day.markers) == 2)
    check("нет 💰 — пропуск ok",
          all(m.icon != "💰" for m in day.markers))

    # День с intro перед первым маркером.
    with_intro = {
        "level": 3,
        "heading": "День 2",
        "body": "Это intro-текст.\n📍 Локация.",
        "subsections": [],
    }
    day2 = stage5.parse_day_block(with_intro)
    check("intro сохранён", "intro-текст" in day2.intro)
    check("1 маркер", len(day2.markers) == 1)

    # ⚠ без variation selector.
    no_vs = {
        "level": 3,
        "heading": "День 3",
        "body": "⚠ Просто предупреждение без selector.",
        "subsections": [],
    }
    day3 = stage5.parse_day_block(no_vs)
    check("⚠ матчится так же как ⚠️", len(day3.markers) == 1)
    check("label = Риски", day3.markers[0].label == "Риски")


# ─── 2. split_bullets_and_intro ──────────────────────────────────────────


def test_split_bullets_and_intro():
    print("\n[2] split_bullets_and_intro")

    intro, bullets = stage5.split_bullets_and_intro(
        "**Программа:**\n- Пункт 1\n- Пункт 2\n- Пункт 3"
    )
    check("intro = **Программа:**", intro == "**Программа:**")
    check("3 bullets", len(bullets) == 3)
    check("первый bullet — Пункт 1", bullets[0] == "Пункт 1")

    intro2, bullets2 = stage5.split_bullets_and_intro("Просто текст без bullets.")
    check("без bullets → пустой список", bullets2 == [])
    check("intro = весь текст", intro2 == "Просто текст без bullets.")

    # Многострочный bullet (продолжение через отступ).
    intro3, bullets3 = stage5.split_bullets_and_intro(
        "- Первый\n  с продолжением\n- Второй"
    )
    check("multiline bullet склеен", "продолжением" in bullets3[0])
    check("2 bullet'а", len(bullets3) == 2)


# ─── 3. extract_tables_and_text ──────────────────────────────────────────


def test_extract_tables_and_text():
    print("\n[3] extract_tables_and_text")

    body = """Расчёт на 1 человека.

| Статья | Сумма |
|---|---|
| Жильё | 100 000 |
| Еда | 50 000 |

Дополнительный текст.

| A | B |
|---|---|
| 1 | 2 |
"""
    blocks = stage5.extract_tables_and_text(body)
    check("4 блока (text, table, text, table)", len(blocks) == 4,
          f"got {len(blocks)}: types={[b['type'] for b in blocks]}")
    check("первый — text", blocks[0]["type"] == "text")
    check("второй — table", blocks[1]["type"] == "table")
    check("в таблице 1 header + 2 row",
          len(blocks[1]["rows"]) == 3)
    check("header правильный",
          blocks[1]["rows"][0] == ["Статья", "Сумма"])

    # Только текст без таблиц.
    blocks2 = stage5.extract_tables_and_text("Просто параграф\n\nещё параграф")
    check("без таблиц → один text-блок", len(blocks2) == 1 and blocks2[0]["type"] == "text")


# ─── 4. extract_content на Vietnam fixture ────────────────────────────────


def test_extract_content_vietnam():
    print("\n[4] extract_content — Vietnam fixture")

    if not VIETNAM_STAGE5.exists():
        skip("Vietnam fixture", f"нет файла {VIETNAM_STAGE5}")
        return

    parsed = parser.parse_stage_file(VIETNAM_STAGE5)
    extracted = stage5.extract_content(parsed)

    check("cover.trip_id есть", extracted["cover"]["trip_id"])
    check("cover.duration_nights = 13",
          extracted["cover"]["duration_nights"] == 13)
    check("cover.chosen_variant — вариант_а",
          extracted["cover"]["chosen_variant"] == "вариант_а")
    check("title есть", extracted["title"])

    check("context body есть", extracted["context"] and len(extracted["context"]) > 100)
    check("header body есть", extracted["header"] and len(extracted["header"]) > 100)
    check("5 prep-секций (Деньги/SIM/Стыковка/Экипировка/Бронирования)",
          len(extracted["critical_prep"]) == 5,
          f"got {len(extracted['critical_prep'])}")
    check("13 day-блоков", len(extracted["days"]) == 13,
          f"got {len(extracted['days'])}")

    # Дни пронумерованы 1..13.
    nums = [d.day_num for d in extracted["days"]]
    check("day_num 1..13 (упорядочены)", nums == list(range(1, 14)),
          f"got {nums}")

    # У каждого дня минимум 1 маркер.
    no_markers = [d.day_num for d in extracted["days"] if not d.markers]
    check("у всех дней есть маркеры", not no_markers,
          f"дни без маркеров: {no_markers}")

    # 3 summary-подсекции (Транспорт / Бюджет / Гастрономия).
    check("3 summary-подсекции", len(extracted["summary"]) == 3,
          f"got: {[s['title'] for s in extracted['summary']]}")

    # 3 TODO-группы (Перед бронированием / За 2 недели / В процессе).
    check("3 TODO-группы", len(extracted["todo"]) == 3,
          f"got: {[t['title'] for t in extracted['todo']]}")


# ─── 5. md_inline_to_rl — XML escape + markup ─────────────────────────────


def test_md_inline_to_rl():
    print("\n[5] pdf_lib.md_inline_to_rl")

    if pdf_lib is None:
        skip("md_inline_to_rl", "pdf_lib не импортируем")
        return

    # Базовые конверсии.
    check("**bold** → <b>",
          "<b>bold</b>" in pdf_lib.md_inline_to_rl("**bold** text"))
    check("*italic* → <i>",
          "<i>italic</i>" in pdf_lib.md_inline_to_rl("*italic* text"))
    check("`code` → <font name=mono>",
          "<font" in pdf_lib.md_inline_to_rl("`code` here"))
    check("link → <a>",
          "<a href=" in pdf_lib.md_inline_to_rl("[link](https://x.com)"))

    # XML escape.
    out = pdf_lib.md_inline_to_rl("text with < and > and &")
    check("XML escape <", "&lt;" in out)
    check("XML escape >", "&gt;" in out)
    check("XML escape &", "&amp;" in out)

    # TODO highlight.
    out2 = pdf_lib.md_inline_to_rl("Здесь TODO: проверить отель.")
    check("TODO обёрнут в font",
          "<font" in out2 and "TODO:" in out2 and "проверить отель" in out2)

    # Регрессия: TODO внутри **bold** НЕ должен ломать XML (вложенный <b> ок).
    out3 = pdf_lib.md_inline_to_rl("**Входная плата — TODO:** источники конфликтуют.")
    check("TODO внутри <b> — <b> сбалансирован",
          out3.count("<b>") == out3.count("</b>"),
          f"out: {out3!r}")
    check("TODO внутри <b> — <font> сбалансирован (well-formed)",
          out3.count("<font") == out3.count("</font>"),
          f"out: {out3!r}")
    # Маркер TODO всегда жирный — и когда md обернул в **…**, и когда нет
    # (раньше вес «гулял»: то жирный, то обычный).
    plain = pdf_lib.md_inline_to_rl("ориентир, TODO сверить на cbr.ru")
    check("TODO жирный даже без ** в md (консистентный вес)",
          "<b>TODO" in plain, f"plain: {plain!r}")


# ─── 6. Регрессия на реальном fixture: парсить + рендерить без exception ──


def test_render_vietnam_without_exception():
    print("\n[6] build_pdf на Vietnam fixture (no exception)")

    if not REPORTLAB_OK:
        skip("build_pdf Vietnam", "reportlab не установлен")
        return
    if not VIETNAM_STAGE5.exists():
        skip("build_pdf Vietnam", f"нет fixture {VIETNAM_STAGE5}")
        return

    parsed = parser.parse_stage_file(VIETNAM_STAGE5)
    adapted = adapter.adapt_for_recipient(parsed, "self")
    extracted = stage5.extract_content(adapted)

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.pdf"
        try:
            stage5.build_pdf(extracted, out, recipient="self")
        except Exception as e:
            check("build_pdf не падает", False, str(e))
            return
        check("PDF создан", out.exists())
        check("PDF не пустой (>10KB)", out.stat().st_size > 10_000,
              f"size: {out.stat().st_size}")


def test_render_vietnam_parents():
    print("\n[6b] build_pdf parents — ⚠️ блоки в днях убраны")

    if not REPORTLAB_OK:
        skip("parents PDF", "reportlab не установлен")
        return
    if not VIETNAM_STAGE5.exists():
        skip("parents PDF", f"нет fixture {VIETNAM_STAGE5}")
        return

    parsed = parser.parse_stage_file(VIETNAM_STAGE5)
    adapted = adapter.adapt_for_recipient(parsed, "parents")
    extracted = stage5.extract_content(adapted)
    warning_count = sum(
        1 for d in extracted["days"] for m in d.markers if m.icon in ("⚠️", "⚠")
    )
    check("⚠️ маркеры в днях для parents = 0", warning_count == 0,
          f"got {warning_count}")

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out_parents.pdf"
        stage5.build_pdf(extracted, out, recipient="parents")
        check("parents PDF создан и не пустой", out.exists() and out.stat().st_size > 10_000)


# ─── 7. CLI integration ──────────────────────────────────────────────────


def test_cli_integration():
    print("\n[7] CLI integration: export.py --stage 5")

    if not REPORTLAB_OK:
        skip("CLI integration", "reportlab не установлен")
        return
    if not VIETNAM_STAGE5.exists():
        skip("CLI integration", f"нет fixture {VIETNAM_STAGE5}")
        return

    with tempfile.TemporaryDirectory() as tmp:
        trip_dir = Path(tmp) / "trips" / "тест_2025-01"
        trip_dir.mkdir(parents=True)
        # Копируем fixture как v1.
        (trip_dir / "5_final_plan_v1.md").write_text(
            VIETNAM_STAGE5.read_text(encoding="utf-8"), encoding="utf-8"
        )

        result = subprocess.run(
            [sys.executable, str(EXPORT_DIR / "export.py"),
             "--stage", "5",
             "--trip", "тест_2025-01",
             "--recipient", "self",
             "--travel-root", tmp,
             "--format", "pdf"],   # дефолт экспорта с 2026-07-04 — html; тест про PDF-путь
            capture_output=True, text=True, timeout=60,
        )
        check("CLI exit 0", result.returncode == 0,
              f"stderr: {result.stderr[-300:]!r}")

        try:
            out = json.loads(result.stdout)
            check("вывод — RenderRequest JSON", out.get("format") == "pdf")
        except json.JSONDecodeError:
            check("вывод — валидный JSON", False, result.stdout[:200])
            return

        pdf_path = Path(out["output_path"])
        check("PDF создан по пути из RenderRequest", pdf_path.exists())
        check("PDF >10KB", pdf_path.exists() and pdf_path.stat().st_size > 10_000)
        # trip_id берётся из frontmatter фикстуры (аргентина_юг_2025-03),
        # имя — по конвенции {trip_id}_план_v{N}.pdf.
        check("имя по конвенции {trip_id}_план_v{N}.pdf",
              pdf_path.name == "5_аргентина_юг_2025-03_финальный_план_v1.pdf",
              f"got {pdf_path.name}")


def test_strip_leading_label():
    print("\n[1c] _strip_leading_label — дедуп метки-лида (P1-1)")
    f = stage5._strip_leading_label
    # `**Программа** (...)` дублирует метку-лид 🎯 «Программа» → срезаем токен.
    check("**Программа** (...) → без ведущего слова",
          f("**Программа** (день лёгкий):", "Программа") == "(день лёгкий):")
    check("**Программа:** → пусто (голая метка)",
          f("**Программа:**", "Программа") == "")
    check("**Программа** — текст → срезает тире",
          f("**Программа** — вечерняя прогулка", "Программа") == "вечерняя прогулка")
    check("без метки → без изменений",
          f("Просто текст дня", "Программа") == "Просто текст дня")
    check("другая метка → без изменений",
          f("**Локация** Москва", "Программа") == "**Локация** Москва")
    check("совпадение без учёта регистра",
          f("**локация** Москва", "Локация") == "Москва")


def test_nbsp_budget():
    print("\n[1d] _nbsp_budget — неразрывность бюджета (P1-3)")
    f = stage5._nbsp_budget
    NB = " "
    EN = "–"
    # Сырое поле маркера: обычные пробелы в разрядах + en-dash диапазона.
    check("разряды → nbsp, en-dash без пробелов",
          f("~₩75 000–110 000") == f"~₩75{NB}000{EN}110{NB}000",
          f"got {f('~₩75 000–110 000')!r}")
    check("дефис с пробелами в диапазоне → en-dash без пробелов",
          f("35 000 - 50 000") == f"35{NB}000{EN}50{NB}000")
    check("одиночное число → nbsp в разрядах",
          f("~₩200 000") == f"~₩200{NB}000")
    check("идемпотентна",
          f(f("~₩75 000–110 000")) == f("~₩75 000–110 000"))
    check("пустая строка → пустая", f("") == "")


def test_checkbox_glyph():
    print("\n[5b] bullet_list — чекбоксы ☐/☑ (P3-11)")
    if not REPORTLAB_OK:
        skip("чекбоксы ☐/☑", "reportlab не установлен")
        return
    pdf_lib.register_fonts()
    styles = pdf_lib.get_styles()
    out = pdf_lib.bullet_list(["[ ] купить визу", "[x] забронировать отель"], styles)
    texts = [p.text for p in out]
    check("пустой пункт → ☐", any("☐" in t for t in texts))
    check("отмеченный [x] → ☑", any("☑" in t for t in texts))
    check("нет ASCII [ ]", not any("[ ]" in t for t in texts))


def test_day_heading_and_variant():
    """P2-аудит: дата дня в outline + человекочитаемый подзаголовок,
    буква варианта (кириллица→латиница), выброс `---` из контента."""
    print("\n[12] заголовок дня + буква варианта + выброс ---")
    bar, sub = stage5._split_day_heading("День 7 (11.09 Пт). Главный день террас")
    check("day bar = 'День N · DD.MM' (дата в outline)",
          bar == "День 7 · 11.09", bar)
    check("day subtitle = 'DD месяца (Дн): …' без ведущей точки",
          sub == "11 сентября (Пт): Главный день террас", sub)
    bar2, sub2 = stage5._split_day_heading(
        "День 7 · пятница, 11 сентября · Террасы")
    check("day heading: graceful fallback на старый polished-формат",
          bar2 == "День 7" and "террас" in sub2.lower(), f"{bar2!r}/{sub2!r}")

    check("variant: кириллический raw «С» → латинская C",
          stage5._variant_letter(
              {"chosen_variant": "вариант_в", "chosen_variant_raw": "С"}) == "C")
    check("variant: латинская буква passthrough",
          stage5._variant_letter({"chosen_variant_raw": "A"}) == "A")

    sec = {"heading": "День 1 (05.09 Сб). Прилёт",
           "body": "🎯 **Программа:**\n- пункт\n💰 ~2 800 ₽\n"
                   "⚠️ Лёгкий вечер.\n\n---\n"}
    db = stage5.parse_day_block(sec)
    risk = [m for m in db.markers if m.icon in ("⚠️", "⚠")]
    check("⚠️-маркер без хвостового '---' (разделитель выброшен)",
          bool(risk) and "---" not in risk[0].content,
          risk[0].content if risk else "no risk marker")


def test_todo_highlight_consistent():
    """P2-аудит: TODO-подсветка — компактный консистентный спан (только
    сам маркер), без захвата прозы и без ложных совпадений."""
    print("\n[13] TODO-подсветка — консистентный спан")
    from export import pdf_lib
    cases = {
        "TODO: онлайн-регистрация за 24 ч.": ["TODO:"],
        "TODO за 2 недели: проверить.": ["TODO за 2 недели:"],
        "ориентир, TODO сверить на cbr.ru": ["TODO"],
        "отдельного TODO на цену нет": ["TODO"],
        "за 2 дня. TODO.": ["TODO."],
    }
    for text, expected in cases.items():
        got = [m.group(1) for m in pdf_lib._TODO_INLINE_RE.finditer(text)]
        check(f"TODO span: {text[:28]}…", got == expected, f"got {got}")
    check("'Todo Glaciares' (исп.) не подсвечивается — регистрозависимо",
          not pdf_lib._TODO_INLINE_RE.search("Todo Glaciares"))


def test_context_parts_split():
    print("\n[14] _parse_context_parts — разнесение Логики/Чего нет (P1.2)")
    body = (
        "Поездка: X. Вариант: A.\n\n"
        "**Логика ключевых решений:**\n\n"
        "- Решение раз.\n- Решение два.\n\n"
        "**Чего больше нет в маршруте и почему**\n\n"
        "- Место А — слишком далеко.\n- Место Б — не интересно.\n"
    )
    parts = stage5._parse_context_parts(body)
    check("структура найдена (fallback=None)", parts["fallback"] is None)
    check("logic_blocks непустые", len(parts["logic_blocks"]) >= 1)
    check("excluded_rows = 2", len(parts["excluded_rows"]) == 2,
          f"got {parts['excluded_rows']}")
    check("excluded[0] = [место, причина]",
          parts["excluded_rows"][0] == ["Место А", "слишком далеко."],
          f"got {parts['excluded_rows'][0]}")
    # Логика НЕ попала в excluded и наоборот.
    logic_text = " ".join(" ".join(b) for b in parts["logic_blocks"])
    check("Логика содержит решения, не исключения",
          "Решение раз" in logic_text and "Место А" not in logic_text)
    # Нет под-заголовков → fallback (ничего не теряем).
    p2 = stage5._parse_context_parts("Просто контекст без под-заголовков.")
    check("нет структуры → fallback = весь body, logic пуст",
          p2["fallback"] == "Просто контекст без под-заголовков."
          and not p2["logic_blocks"])


def test_is_budget_title():
    print("\n[15] _is_budget_title (P2.3)")
    check("'Бюджет' → True", stage5._is_budget_title("Бюджет"))
    check("'Бюджет (на 1 человека)' → True",
          stage5._is_budget_title("Бюджет (на 1 человека)"))
    check("'Транспорт' → False", not stage5._is_budget_title("Транспорт"))


def test_field_recipient():
    print("\n[16] recipient field — форк полевой версии (P1.4)")
    check("field — валидный recipient", "field" in adapter.list_recipients())
    if not VIETNAM_STAGE5.exists():
        skip("field strip", "нет fixture")
        return
    parsed = parser.parse_stage_file(VIETNAM_STAGE5)
    af = adapter.adapt_for_recipient(parsed, "field")
    heads = [s["heading"] for s in af["sections"]]
    for dropped in ("Шапка", "Критические подготовительные пункты",
                    "TODO для верификации", "Чеклист за 2 недели до поездки"):
        check(f"field срезает {dropped!r}", dropped not in heads)
    for kept in ("Маршрут по дням", "Сводные таблицы",
                 "План реагирования на риски"):
        check(f"field сохраняет {kept!r}", kept in heads)


def test_build_toc():
    print("\n[17] _build_toc — оглавление + условный разрыв (P1.5)")
    if not REPORTLAB_OK:
        skip("_build_toc", "reportlab не установлен")
        return
    from reportlab.platypus import PageBreak, Spacer
    styles = pdf_lib.get_styles()
    check("пустой entries → пустой TOC", stage5._build_toc([], styles) == [])
    short = [(f"Секция {i}", f"s{i}") for i in range(5)]
    flows = stage5._build_toc(short, styles)
    link_paras = [f for f in flows if "href" in getattr(f, "text", "")]
    check("5 ссылок-строк", len(link_paras) == 5, f"got {len(link_paras)}")
    check("каждая ссылка — внутренняя (#slug)",
          all(f'href="#s' in f.text for f in link_paras))
    check("≤ порога → хвост Spacer (без принудительного разрыва)",
          isinstance(flows[-1], Spacer))
    long = [(f"Секция {i}", f"s{i}") for i in range(12)]
    check("> порога → хвост PageBreak",
          isinstance(stage5._build_toc(long, styles)[-1], PageBreak))


def test_render_field_no_exception():
    print("\n[6c] build_pdf field — рендер без исключения (P1.4)")
    if not REPORTLAB_OK or not VIETNAM_STAGE5.exists():
        skip("field PDF", "reportlab/fixture")
        return
    parsed = parser.parse_stage_file(VIETNAM_STAGE5)
    adapted = adapter.adapt_for_recipient(parsed, "field")
    extracted = stage5.extract_content(adapted)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "field.pdf"
        stage5.build_pdf(extracted, out, recipient="field")
        check("field PDF создан и не пустой",
              out.exists() and out.stat().st_size > 10_000)


def test_toc_home_and_order():
    print("\n[18] TOC: «В начало» первым + порядок TODO→Чеклист→Обоснование")
    if not REPORTLAB_OK or not VIETNAM_STAGE5.exists():
        skip("TOC order", "reportlab/fixture")
        return
    parsed = parser.parse_stage_file(VIETNAM_STAGE5)
    extracted = stage5.extract_content(parsed)
    cap = {}
    orig = stage5._build_toc
    stage5._build_toc = lambda e, s: (cap.__setitem__("e", list(e)) or orig(e, s))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            stage5.build_pdf(extracted, Path(tmp) / "o.pdf", recipient="self")
    finally:
        stage5._build_toc = orig
    entries = cap["e"]
    titles = [t for t, _ in entries]
    check("первый пункт TOC — «В начало»→doc-top",
          entries[0] == ("В начало", "doc-top"), f"got {entries[0]}")
    if {"TODO для верификации", "Чеклист за 2 недели до поездки"} <= set(titles):
        check("TODO раньше Чеклиста",
              titles.index("TODO для верификации")
              < titles.index("Чеклист за 2 недели до поездки"))
    if {"Обоснование ключевых решений", "Чеклист за 2 недели до поездки"} <= set(titles):
        check("Обоснование после Чеклиста",
              titles.index("Обоснование ключевых решений")
              > titles.index("Чеклист за 2 недели до поездки"))


def test_budget_subheading_link():
    print("\n[19] инлайн-ссылка «## Сводные таблицы → Бюджет» линкует и Бюджет")
    if pdf_lib is None or not VIETNAM_STAGE5.exists():
        skip("budget sublink", "pdf_lib/fixture")
        return
    parsed = parser.parse_stage_file(VIETNAM_STAGE5)
    extracted = stage5.extract_content(parsed)
    anchors = stage5.build_anchor_map(extracted)
    check("«Бюджет» зарегистрирован → summary-anchor",
          str(anchors.get("Бюджет", "")).startswith("summary-"),
          anchors.get("Бюджет"))
    pdf_lib.set_section_anchors(anchors)
    try:
        out = pdf_lib.preprocess_section_refs(
            "разбивка — в `## Сводные таблицы → Бюджет`.")
    finally:
        pdf_lib.clear_section_anchors()
    check("два SLINK (Сводные таблицы + Бюджет)", out.count("SLINK:") == 2,
          out.replace("\x00", "§"))
    check("Бюджет линкуется на summary-anchor", "SLINK:summary" in out)


# ─── Этап-2 Фаза A: тезис, статус-маркеры, источник ──────────────────────


ETAP2_DAY = {
    "level": 3,
    "heading": "День 6 (06.09 Сб). Сапа",
    "body": """[[регион: Сапа | база: Сапа]]
📍 Ханой → Сапа: лимузин ~7,5 ч.
🏨 [[бронь: план]] **Topas Ecolodge**, хребет — TODO: цену на Booking. Почему выбран: виды террас ценой удалённости.
🎯 **Программа:**
- Утро — рисовые террасы Мыонгхоа. *Источник: HIGH-автор Алара2009*
💰 ~6 000 ₽
⚠️ Перевал зависит от дождя — план Б в риск-таблице. [[погода: туман, сверить прогноз]]""",
    "subsections": [],
}


def test_etap2_status_markers():
    print("\n[E2-1] статус-маркеры дня (бронь/погода) + Источник")
    d = stage5.parse_day_block(ETAP2_DAY)
    check("booking = план", d.booking == "план", str(d.booking))
    check("weather список из 1", d.weather == ["туман, сверить прогноз"], str(d.weather))
    check("region всё ещё извлечён", d.region == "Сапа")
    htl = next(m for m in d.markers if m.icon == "🏨")
    check("[[бронь]] вырезан из 🏨", "[[" not in htl.content, htl.content[:40])
    check("«Почему выбран» сохранён в 🏨", "Почему выбран" in htl.content)
    prog = next(m for m in d.markers if m.icon == "🎯")
    check("*Источник:* сохранён в 🎯 (не вырезан)", "*Источник:" in prog.content)
    warn = next(m for m in d.markers if m.icon in ("⚠️", "⚠"))
    check("[[погода]] вырезан из ⚠️", "[[" not in warn.content, warn.content[:40])
    # forgiveness: «забронировано» → зелёный чип.
    d2 = stage5.parse_day_block({**ETAP2_DAY,
        "body": "🏨 [[бронь: забронировано]] **Hotel X** ref ABC."})
    check("booking = забронировано", d2.booking == "забронировано")


def test_etap2_status_chips():
    print("\n[E2-2] _day_status_chips цвета")
    d = stage5.parse_day_block(ETAP2_DAY)
    chips = stage5._day_status_chips(d)
    labels = [c[0] for c in chips]
    check("чип брони присутствует", any("бронь: план" in l for l in labels), str(labels))
    check("чип погоды присутствует", any(l.startswith("погода:") for l in labels), str(labels))
    # Дизайн-язык: бронь — teal-тинт (.chip--book), погода — синий тинт (.chip--weather).
    check("бронь → teal-тинт-фон", chips[0][2] == pdf_lib.COLORS["chip_book_bg"], str(chips))
    weather = [c for c in chips if c[0].startswith("погода:")]
    check("погода → синий-тинт-фон (не кричащий)",
          weather and weather[0][2] == pdf_lib.COLORS["chip_weather_bg"], str(weather))
    d2 = stage5.parse_day_block({**ETAP2_DAY, "body": "🏨 [[бронь: забронировано]] X."})
    ch2 = stage5._day_status_chips(d2)
    check("забронировано → teal-тинт-фон", ch2[0][2] == pdf_lib.COLORS["chip_book_bg"], str(ch2))
    # пустой день → нет чипов.
    d3 = stage5.parse_day_block({"level": 3, "heading": "День 1. X",
                                 "body": "📍 Прилёт.", "subsections": []})
    check("без маркеров → чипов нет", stage5._day_status_chips(d3) == [])
    if REPORTLAB_OK:
        check("status_chips → Paragraph", pdf_lib.status_chips(chips) is not None)
        check("status_chips пустой → None", pdf_lib.status_chips([]) is None)


def test_etap2_thesis():
    print("\n[E2-3] тезис «Замысел маршрута»")
    ctx = ("**Замысел маршрута:** север без юга — горы вместо пляжей.\n\n"
           "- Кто: соло\n- Темп: умеренный")
    check("thesis извлечён",
          stage5._extract_thesis(ctx) == "север без юга — горы вместо пляжей.")
    stripped = stage5._strip_thesis_line(ctx)
    check("строка тезиса вырезана", "Замысел маршрута" not in stripped)
    check("остальной контекст цел", "Кто: соло" in stripped)
    check("нет тезиса → None", stage5._extract_thesis("- Кто: соло") is None)
    # Вариант без двоеточия/со звёздочками — тоже ловим.
    check("вариант формата ловится",
          stage5._extract_thesis("Замысел маршрута. Горы и террасы.")
          == "Горы и террасы.")


def test_etap2_render_no_exception():
    print("\n[E2-4] build_pdf с маркерами Этапа-2 (no exception)")
    if not REPORTLAB_OK:
        skip("build_pdf Этап-2", "reportlab не установлен")
        return
    md = """---
trip_id: вьетнам_север_2026-09
stage: 5_final_plan
duration_nights: 6
todo_verification_items: 1
created: 2026-09-01
---

# Stage 5 — Финальный план: вьетнам_север_2026-09

## Контекст и ключевые параметры

**Замысел маршрута:** север без юга — горы и террасы вместо пляжей; база-радиалы.

- Кто: соло, 37 лет
- Темп: умеренный

## Маршрут по дням

### День 6 (06.09 Сб). Сапа

📍 Ханой → Сапа: лимузин ~7,5 ч.
🏨 [[бронь: план]] **Topas Ecolodge**, хребет — TODO: цену на Booking.
🎯 **Программа:**
- Утро — террасы Мыонгхоа. _Источник: HIGH-автор Алара2009_
💰 ~6 000 ₽
⚠️ Перевал зависит от дождя. [[погода: туман]]

## TODO для верификации

- [ ] Booking Topas Ecolodge
"""
    extracted = stage5.extract_content(parser.parse_stage_text(md))
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "e2.pdf"
        try:
            stage5.build_pdf(extracted, out, recipient="self")
        except Exception as e:
            check("build_pdf с маркерами не падает", False, str(e))
            return
        check("PDF создан", out.exists() and out.stat().st_size > 8_000)
    # thesis вырезан из контекста (не дублируется у фронта).
    check("thesis извлекается из контекста",
          stage5._extract_thesis(extracted["context"]) == "север без юга — горы и террасы вместо пляжей; база-радиалы.")


# ─── Волна 1 (пост-прогон Корея): бюджет-охват, collapse, cover-outline ───


def test_implied_budget_status():
    print("\n[W1-G3] _implied_budget_status + метка охвата")
    f = stage5._implied_budget_status
    check("162500/257000 → under_target (≠ on_target → охваты разные)",
          f(162500, 257000) == "under_target")
    check("250000/257000 → on_target", f(250000, 257000) == "on_target")
    check("295000/257000 → over_10_20", f(295000, 257000) == "over_10_20")
    check("320000/257000 → over_20+", f(320000, 257000) == "over_20+")
    check("target=0 → on_target (без деления на ноль)", f(100, 0) == "on_target")
    if REPORTLAB_OK:
        # Обложка с расхождением охвата (status=on_target, но 162.5k/257k=0.63
        # → under) → метка «поездка … · план all-in …» вместо «факт … · план …».
        # Бюджет лежит в ячейке Table → извлекаем plain-text из её Paragraph'ов.
        ex = stage5.extract_content(parser.parse_stage_text("""---
trip_id: t
stage: 5_final_plan
total_budget_rub: 162500
budget_target_rub: 257000
budget_status: on_target
home_eq_start: true
---

# План
"""))
        story = []
        stage5._build_cover_page(story, ex["cover"], ex.get("title"), pdf_lib.get_styles())
        texts = []
        for fl in story:
            # Бюджетная сноска — теперь отдельный Paragraph под статбендом
            # (раньше лежала в ячейке паспорт-таблицы).
            if hasattr(fl, "getPlainText"):
                texts.append(fl.getPlainText())
            for row in getattr(fl, "_cellvalues", []) or []:
                for cell in row:
                    for p in (cell if isinstance(cell, list) else [cell]):
                        if hasattr(p, "getPlainText"):
                            texts.append(p.getPlainText())
        joined = " ".join(texts)
        check("метка охвата «поездка … · план all-in …»",
              "all-in" in joined and "поездка" in joined, joined[:200])


def test_cover_back_to_top_outline():
    print("\n[W1-C] обложка несёт outline-запись «В начало»")
    if not REPORTLAB_OK:
        skip("cover outline", "reportlab не установлен")
        return
    story = []
    styles = pdf_lib.get_styles()
    stage5._build_cover_page(story, {"trip_id": "t"}, "Финальный план", styles)
    title_para = story[0]
    check("cover title несёт _dest_slug=doc-top",
          getattr(title_para, "_dest_slug", None) == "doc-top")
    check("cover title несёт outline «В начало» уровня 0",
          getattr(title_para, "_outline_title", None) == "В начало"
          and getattr(title_para, "_outline_level", None) == 0)


def test_collapse_double_breaks():
    print("\n[W1-fix] _collapse_double_breaks — нет пустых страниц")
    if not REPORTLAB_OK:
        skip("collapse breaks", "reportlab не установлен")
        return
    pb = pdf_lib.page_break
    sp = pdf_lib.spacer
    story = [sp(2), pb(), pb(), sp(2), pb(), pb(), pb(), sp(2)]
    out = stage5._collapse_double_breaks(story)
    n_break = sum(1 for f in out if isinstance(f, pdf_lib.PageBreak))
    check("подряд идущие разрывы схлопнуты (4 → 2)", n_break == 2, str(n_break))
    check("контент (спейсеры) сохранён", sum(1 for f in out if not isinstance(f, pdf_lib.PageBreak)) == 3)
    # break + spacer + break — НЕ схлопывается (между ними контент).
    story2 = [pb(), sp(2), pb()]
    check("разрыв-спейсер-разрыв сохранён",
          sum(1 for f in stage5._collapse_double_breaks(story2) if isinstance(f, pdf_lib.PageBreak)) == 2)


def test_render_markdown_body_air():
    print("\n[W2-D] _render_markdown_body air=True — воздух в досье")
    if not REPORTLAB_OK:
        skip("markdown air", "reportlab не установлен")
        return
    from reportlab.platypus import Spacer
    styles = pdf_lib.get_styles()
    body = "Первый абзац досье.\n\nВторой абзац.\n\nТретий абзац."
    plain: list = []
    stage5._render_markdown_body(plain, body, styles, air=False)
    aired: list = []
    stage5._render_markdown_body(aired, body, styles, air=True)
    n_plain = sum(1 for f in plain if isinstance(f, Spacer))
    n_air = sum(1 for f in aired if isinstance(f, Spacer))
    check("air=False — без доп. спейсеров между прозой", n_plain == 0, str(n_plain))
    check("air=True — спейсер после каждого абзаца", n_air == 3, str(n_air))
    # H4-подзаголовок + bullets: air добавляет отбой и там.
    body2 = "#### Прививки\n\nГепатит A — рекомендуется.\n\n- денге\n- малярия"
    aired2: list = []
    stage5._render_markdown_body(aired2, body2, styles, air=True)
    check("air распространяется на H4-блок и bullets",
          sum(1 for f in aired2 if isinstance(f, Spacer)) >= 3)


def test_region_titler_intro():
    print("\n[W2-G4] region_titler intro — establishing-фраза региона")
    if not REPORTLAB_OK:
        skip("titler intro", "reportlab не установлен")
        return
    def _texts(tbl) -> str:
        out = []
        def walk(f):
            if hasattr(f, "getPlainText"):
                out.append(f.getPlainText())
            for cell_row in getattr(f, "_cellvalues", []) or []:
                for cell in cell_row:
                    if isinstance(cell, list):
                        for x in cell:
                            walk(x)
                    else:
                        walk(cell)
        walk(tbl)
        return " | ".join(out)
    intro_txt = "гранитные пики и буддийские тропы — два дня на главные виды"
    with_intro = pdf_lib.region_titler(
        2, 4, "Сораксан", "дни 4–5 · ноч. 2", pdf_lib.COLORS["primary"],
        bullets=[("Главное", "Ульсанбави")], intro=intro_txt)
    no_intro = pdf_lib.region_titler(
        2, 4, "Сораксан", "дни 4–5 · ноч. 2", pdf_lib.COLORS["primary"],
        bullets=[("Главное", "Ульсанбави")])
    check("intro-текст присутствует в плашке", "гранитные пики" in _texts(with_intro))
    check("без intro плашка рендерится (backward-compat)",
          "Сораксан" in _texts(no_intro) and "гранитные пики" not in _texts(no_intro))
    # описание из маркера → titler.intro (сквозной путь parse → render).
    name, fields = stage5._parse_region_marker(
        "Сораксан | описание: " + intro_txt + " | база: Сокчо | главное: Ульсанбави")
    check("маркер парсит поле «описание»", fields.get("описание") == intro_txt, str(fields))


# ─── runner ──────────────────────────────────────────────────────────────


def main() -> int:
    test_parse_day_block()
    test_parse_day_block_edge_cases()
    test_strip_leading_label()
    test_nbsp_budget()
    test_split_bullets_and_intro()
    test_extract_tables_and_text()
    test_extract_content_vietnam()
    test_md_inline_to_rl()
    test_checkbox_glyph()
    test_day_heading_and_variant()
    test_todo_highlight_consistent()
    test_context_parts_split()
    test_is_budget_title()
    test_field_recipient()
    test_build_toc()
    test_toc_home_and_order()
    test_budget_subheading_link()
    test_render_vietnam_without_exception()
    test_render_vietnam_parents()
    test_render_field_no_exception()
    test_etap2_status_markers()
    test_etap2_status_chips()
    test_etap2_thesis()
    test_etap2_render_no_exception()
    test_implied_budget_status()
    test_cover_back_to_top_outline()
    test_collapse_double_breaks()
    test_render_markdown_body_air()
    test_region_titler_intro()
    test_cli_integration()

    print(f"\n{'=' * 60}")
    print(f"Всего проверок: {checks_run}, провалов: {checks_failed}")
    return 0 if checks_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
