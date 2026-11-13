#!/usr/bin/env python3
"""Регрессионные тесты для движка экспорта (engine-уровень).

Покрывают:
  - parser.split_frontmatter / parse_yaml / parse_sections / parse_stage_text
  - adapter.adapt_for_recipient (self / parents) + register_stage_extension
  - file_naming.build_export_filename / build_final_plan_filename (Stage 5) /
    build_final_filename (Stage 6) / parse_export_filename / next_discriminator
  - renderer.RenderRequest / prepare_*_request / register_renderer
  - CLI smoke: --parse-only, --stage 0 (зарегистрированный renderer → RenderRequest)

Round-trip --import — покрыт в test_export_stage3.py (реальный DOCX), не здесь.

Запуск из корня репозитория:
    python3 skills/travel-planning/tests/test_export_engine.py

Stdlib only (CLI-рендер Stage 0 требует reportlab — гейтится).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPORT_DIR = REPO_ROOT / "skills" / "travel-planning" / "scripts" / "export"

# Импорт пакета export напрямую (без установки).
sys.path.insert(0, str(EXPORT_DIR.parent))
from export import adapter, file_naming, parser, renderer  # noqa: E402


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


# ─── Fixtures ────────────────────────────────────────────────────────────

SAMPLE_STAGE5 = """---
trip_id: вьетнам_2023-09
stage: 5_final_plan
travelers_profile: profiles/алексей.md
mode: reconstructive
duration_nights: 18
total_budget_rub: 245000
budget_target_rub: 257000
budget_status: on_target
chosen_variant: вариант_б
chosen_variant_raw: "B"
home_eq_start: false
web_search_used: true
mcp_extensions_used: []
created: 2023-09-01
warnings:
  - "Цены отелей — TODO"
  - "Точные даты — параметр Stage 0"
input_files:
  - 4_variants.md
  - profiles/алексей.md
---

# Stage 5 — Финальный план: вьетнам_2023-09

## Контекст и ключевые параметры

- Кто: соло, 37 лет
- Длительность: 18 ночей

## Шапка

Паспорт, визы, перелёты.

## Маршрут по дням

### День 1 — Ханой

📍 Локация: Ханой
🏨 Отель: TODO: верифицировать на Booking
🎯 Программа: прогулка по Старому городу
💰 Бюджет: ~3000 ₽
⚠️ Риски: акклиматизация после перелёта

### День 2 — Ханой

Полный день экскурсий.

## TODO для верификации

- Booking отелей
- Визы

## План реагирования на риски

- Если задержка рейса — переночевать в Ханое.

## Warnings

- Цены — оценочные.
"""


# ─── 1. parser.split_frontmatter ─────────────────────────────────────────


def test_split_frontmatter():
    print("\n[1] parser.split_frontmatter")

    yaml_text, body = parser.split_frontmatter(SAMPLE_STAGE5)
    check("YAML извлечён", "trip_id: вьетнам_2023-09" in yaml_text)
    check("body начинается с #", body.lstrip().startswith("# Stage 5"))
    check("разделители не попали в yaml/body", "---" not in yaml_text)

    yaml_text2, body2 = parser.split_frontmatter("без frontmatter\n# заголовок")
    check("нет frontmatter → пустой yaml", yaml_text2 == "")
    check("нет frontmatter → body == исходный", body2.startswith("без frontmatter"))

    # Открытый frontmatter без закрытия — тоже OK, возвращаем весь текст как body.
    broken = "---\ntrip_id: x\n"
    yaml_text3, body3 = parser.split_frontmatter(broken)
    check("frontmatter без закрытия → не парсится", yaml_text3 == "" and body3 == broken)


# ─── 2. parser.parse_yaml ────────────────────────────────────────────────


def test_parse_yaml():
    print("\n[2] parser.parse_yaml")

    yaml_text, _ = parser.split_frontmatter(SAMPLE_STAGE5)
    fm, warnings = parser.parse_yaml(yaml_text)

    check("trip_id извлечён", fm.get("trip_id") == "вьетнам_2023-09")
    check("duration_nights — int", fm.get("duration_nights") == 18 and isinstance(fm["duration_nights"], int))
    check("home_eq_start — False", fm.get("home_eq_start") is False)
    check("web_search_used — True", fm.get("web_search_used") is True)
    check("mcp_extensions_used — пустой список через flow", fm.get("mcp_extensions_used") in ([], "[]"))
    check("warnings — список из 2 элементов",
          isinstance(fm.get("warnings"), list) and len(fm["warnings"]) == 2)
    check("warnings[0] — строка про отели",
          isinstance(fm["warnings"][0], str) and "TODO" in fm["warnings"][0])
    check("input_files — список",
          isinstance(fm.get("input_files"), list) and "4_variants.md" in fm["input_files"])
    check("нет ложных warnings парсера", warnings == [],
          f"warnings: {warnings}")

    # Кавычки.
    fm2, _ = parser.parse_yaml('name: "со словом: двоеточием"\n')
    check("строка с кавычками парсится", fm2["name"] == "со словом: двоеточием")

    # Null + null-альтернативы.
    fm3, _ = parser.parse_yaml("a: null\nb: ~\nc:\n")
    check("null/~/пусто → None", fm3 == {"a": None, "b": None, "c": None})

    # Flow mapping в списке (Stage 0 selected_regions).
    flow_text = """selected_regions:
  - {name: Ханой, nights: 3}
  - {name: Ха-Лонг, nights: 2}
"""
    fm4, _ = parser.parse_yaml(flow_text)
    check("flow-mapping список парсится",
          isinstance(fm4.get("selected_regions"), list) and len(fm4["selected_regions"]) == 2)
    check("flow-mapping значения",
          fm4["selected_regions"][0] == {"name": "Ханой", "nights": 3})

    # Inline comments.
    fm5, _ = parser.parse_yaml("key: value # комментарий\n")
    check("inline comment срезан", fm5["key"] == "value")

    # Flow-список `[a, b, c]` (Р5 firewall — массовый дрейф).
    fm_fl, w_fl = parser.parse_yaml("weights: [style, focus, pace]\nempty: []\n")
    check("flow-список → список", fm_fl["weights"] == ["style", "focus", "pace"])
    check("пустой flow-список → []", fm_fl["empty"] == [])
    check("flow-список без ложных warnings", w_fl == [])

    # Flush-список (`- ` на отступе ключа) — валидный YAML, раньше терялся как None.
    fm_flush, _ = parser.parse_yaml("regions:\n- Пекин\n- Сиань\nother: x\n")
    check("flush-список собран", fm_flush["regions"] == ["Пекин", "Сиань"])
    check("ключ после flush-списка не съеден", fm_flush.get("other") == "x")

    # Block-скаляр `|`/`>` — не молчаливое «|», а строка + warning.
    fm_bs, w_bs = parser.parse_yaml("note: |\n  line1\n  line2\nx: 1\n")
    check("block-скаляр собран строкой", fm_bs["note"] == "line1\nline2")
    check("block-скаляр даёт warning", any("block scalar" in x for x in w_bs))
    check("ключ после block-скаляра парсится", fm_bs.get("x") == 1)

    # Digit-only stage (int) + ключ с дефисом.
    fm_d, _ = parser.parse_yaml("stage: 0\nsome-key: val\n")
    check("digit-only stage — int (валидно)", fm_d["stage"] == 0)
    check("ключ с дефисом парсится", fm_d.get("some-key") == "val")

    # Fenced-код: `## …` внутри ``` не считается секцией.
    _, secs = parser.parse_sections(
        "## Real\ntext\n\n```\n## Fake\n```\n\n## Real2\nx")
    check("заголовок внутри code-fence игнорируется",
          [s.heading for s in secs] == ["Real", "Real2"])

    # Inline-комментарий на BLOCK-ключе не должен превращать список в None
    # (баг китайского Stage 0: longlist: # 8 регионов… → молча пустой экспорт).
    block_comment = """longlist:                  # 8 регионов = 3 фикса + 5 кандидатов
  - region: "Пекин"
    role: core
  - region: "Шанхай"
    role: core
"""
    fm6, _ = parser.parse_yaml(block_comment)
    check("block-ключ с inline-комментарием → список (не None)",
          isinstance(fm6.get("longlist"), list) and len(fm6["longlist"]) == 2,
          repr(fm6.get("longlist")))
    check("block-ключ с комментарием: значения целы",
          fm6["longlist"][0] == {"region": "Пекин", "role": "core"})
    # Block-mapping с комментарием тоже.
    fm7, _ = parser.parse_yaml("meta:   # коммент\n  a: 1\n  b: 2\n")
    check("block-mapping с inline-комментарием → dict",
          fm7.get("meta") == {"a": 1, "b": 2}, repr(fm7.get("meta")))


# ─── 3. parser.parse_sections ─────────────────────────────────────────────


def test_parse_sections():
    print("\n[3] parser.parse_sections")

    _, body = parser.split_frontmatter(SAMPLE_STAGE5)
    title, sections = parser.parse_sections(body)

    check("title — H1", title and "Финальный план" in title)
    check("4+ top-level секции", len(sections) >= 4)

    headings = [s.heading for s in sections]
    check("есть «Контекст и ключевые параметры»", "Контекст и ключевые параметры" in headings)
    check("есть «Маршрут по дням»", "Маршрут по дням" in headings)
    check("есть «TODO для верификации»", "TODO для верификации" in headings)
    check("есть «План реагирования на риски»", "План реагирования на риски" in headings)

    # Подсекции дней (H3 под «Маршрут по дням»).
    route = next(s for s in sections if s.heading == "Маршрут по дням")
    sub_headings = [ss.heading for ss in route.subsections]
    check("в маршруте 2 дня", len(route.subsections) == 2)
    check("День 1 в подсекциях", any("День 1" in h for h in sub_headings))
    check("body дня 1 содержит иконки",
          "📍" in route.subsections[0].body and "🎯" in route.subsections[0].body)


# ─── 4. parser.parse_stage_text — full ────────────────────────────────────


def test_parse_stage_text():
    print("\n[4] parser.parse_stage_text")

    parsed = parser.parse_stage_text(SAMPLE_STAGE5)
    check("trip_id извлечён в верхний уровень", parsed["trip_id"] == "вьетнам_2023-09")
    check("stage извлечён", parsed["stage"] == "5_final_plan")
    check("body не пустой", len(parsed["body"]) > 0)
    check("sections — список", isinstance(parsed["sections"], list))
    check("frontmatter_warnings пуст", parsed["frontmatter_warnings"] == [])

    # find_section.
    s = parser.find_section(parsed, "Шапка")
    check("find_section находит секцию", s is not None and s["heading"] == "Шапка")
    s_none = parser.find_section(parsed, "Несуществующая")
    check("find_section вернёт None для отсутствующей", s_none is None)


# ─── 5. adapter.adapt_for_recipient — self ─────────────────────────────────


def test_adapter_self():
    print("\n[5] adapter.adapt_for_recipient — self")

    parsed = parser.parse_stage_text(SAMPLE_STAGE5)
    adapted = adapter.adapt_for_recipient(parsed, "self")

    headings = [s["heading"] for s in adapted["sections"]]
    check("self сохраняет TODO секцию", "TODO для верификации" in headings)
    check("self сохраняет План реагирования", "План реагирования на риски" in headings)
    check("self сохраняет Warnings секцию", "Warnings" in headings)
    check("self сохраняет warnings в frontmatter",
          isinstance(adapted["frontmatter"].get("warnings"), list))
    check("self сохраняет trip_id в frontmatter",
          adapted["frontmatter"].get("trip_id") == "вьетнам_2023-09")

    # adapter не мутирует исходник.
    check("исходный parsed не модифицирован",
          [s["heading"] for s in parsed["sections"]] == headings + [])


# ─── 6. adapter.adapt_for_recipient — parents ──────────────────────────────


def test_adapter_parents():
    print("\n[6] adapter.adapt_for_recipient — parents")

    parsed = parser.parse_stage_text(SAMPLE_STAGE5)
    adapted = adapter.adapt_for_recipient(parsed, "parents")

    headings = [s["heading"] for s in adapted["sections"]]
    check("parents выкидывает TODO для верификации", "TODO для верификации" not in headings)
    check("parents выкидывает План реагирования", "План реагирования на риски" not in headings)
    check("parents выкидывает Warnings секцию", "Warnings" not in headings)
    check("parents сохраняет Шапку", "Шапка" in headings)
    check("parents сохраняет Маршрут по дням", "Маршрут по дням" in headings)

    fm = adapted["frontmatter"]
    check("parents выкидывает warnings из YAML", "warnings" not in fm)
    check("parents сохраняет trip_id", fm.get("trip_id") == "вьетнам_2023-09")
    check("parents сохраняет chosen_variant", fm.get("chosen_variant") == "вариант_б")
    check("parents выкидывает mcp_extensions_used", "mcp_extensions_used" not in fm)
    check("parents выкидывает home_eq_start", "home_eq_start" not in fm)

    # TODO-маркеры внутри body дня — должны быть стрипнуты.
    route = next(s for s in adapted["sections"] if s["heading"] == "Маршрут по дням")
    day1_body = route["subsections"][0]["body"]
    check("TODO в body дня 1 стрипнут (для parents)",
          "TODO: верифицировать" not in day1_body,
          f"day1 body: {day1_body!r}")


# ─── 7. adapter.register_stage_extension ───────────────────────────────────


def test_adapter_stage_extension():
    print("\n[7] adapter.register_stage_extension")

    # Зарегистрируем extension, который ставит маркер на frontmatter.
    def mark(parsed_copy: dict) -> None:
        parsed_copy["frontmatter"]["_stage_ext_marker"] = "ran"

    adapter.register_stage_extension("self", "5_final_plan", mark)

    parsed = parser.parse_stage_text(SAMPLE_STAGE5)
    adapted = adapter.adapt_for_recipient(parsed, "self")
    check("stage extension сработал",
          adapted["frontmatter"].get("_stage_ext_marker") == "ran")

    # Чистим за собой, чтобы не влиять на другие тесты.
    adapter._STAGE_EXTENSIONS.pop(("self", "5_final_plan"), None)


# ─── 8. adapter.adapt_for_recipient — unknown recipient ────────────────────


def test_adapter_unknown():
    print("\n[8] adapter.adapt_for_recipient — unknown recipient")

    parsed = parser.parse_stage_text(SAMPLE_STAGE5)
    try:
        adapter.adapt_for_recipient(parsed, "марсиане")
        check("неизвестный recipient → KeyError", False, "не упало")
    except KeyError as e:
        check("неизвестный recipient → KeyError", True)
        check("в сообщении перечислены доступные", "self" in str(e) and "parents" in str(e))


# ─── 9. file_naming.build_export_filename ──────────────────────────────────


def test_file_naming_final_plan():
    print("\n[9b] file_naming.build_final_plan_filename (Stage 5) + build_final_filename (Stage 6)")
    # Единая trip-ориентированная схема (storage-and-naming §4.2):
    # `{stage}_{trip_id}_{описание}[_v{N}][_получатель].{ext}`.
    check("Stage 5 self pdf",
          file_naming.build_final_plan_filename("корея_2024-03")
          == "5_корея_2024-03_финальный_план_v1.pdf")
    check("Stage 5 multi-country v2",
          file_naming.build_final_plan_filename("камбоджа_лаос_2026-02", version=2)
          == "5_камбоджа_лаос_2026-02_финальный_план_v2.pdf")
    check("Stage 5 parents suffix",
          file_naming.build_final_plan_filename("корея_2024-03", recipient="parents")
          == "5_корея_2024-03_финальный_план_v1_для_родителей.pdf")
    # Stage 6 — описание `финал`, versioned как 4/5.
    check("Stage 6 self pdf",
          file_naming.build_final_filename("вьетнам_север_2026-09")
          == "6_вьетнам_север_2026-09_финал_v1.pdf")
    check("Stage 6 v2",
          file_naming.build_final_filename("вьетнам_север_2026-09", version=2)
          == "6_вьетнам_север_2026-09_финал_v2.pdf")
    check("Stage 6 parents suffix",
          file_naming.build_final_filename("корея_2024-03", recipient="parents")
          == "6_корея_2024-03_финал_v1_для_родителей.pdf")


def test_file_naming_build():
    print("\n[9] file_naming.build_export_filename")

    d = dt.date(2026, 5, 27)
    check("Stage 5 self pdf",
          file_naming.build_export_filename(stage="5", ext="pdf", date=d)
          == "5_финальный_план_2026-05-27.pdf")
    check("Stage 5 parents pdf",
          file_naming.build_export_filename(stage="5", ext="pdf", recipient="parents", date=d)
          == "5_финальный_план_для_родителей_2026-05-27.pdf")
    check("Stage 3 self docx",
          file_naming.build_export_filename(stage="3", ext="docx", date=d)
          == "3_места_2026-05-27.docx")
    check("Stage 4 v2 docx",
          file_naming.build_export_filename(stage="4", ext="docx", version=2, date=d)
          == "4_варианты_v2_2026-05-27.docx")
    check("дискриминатор",
          file_naming.build_export_filename(stage="5", ext="pdf", date=d, discriminator="а")
          == "5_финальный_план_2026-05-27_а.pdf")
    check("кастомное short_name",
          file_naming.build_export_filename(stage="5", ext="pdf", date=d, short_name="печатный")
          == "5_печатный_2026-05-27.pdf")

    # stage передан как полный stage из YAML.
    check("полный stage_id принимается",
          file_naming.build_export_filename(stage="5_final_plan", ext="pdf", date=d)
          == "5_финальный_план_2026-05-27.pdf")

    # Ошибки.
    try:
        file_naming.build_export_filename(stage="5", ext="txt", date=d)
        check("неверный ext → ValueError", False, "не упало")
    except ValueError:
        check("неверный ext → ValueError", True)

    try:
        file_naming.build_export_filename(stage="7", ext="pdf", date=d)
        check("неверный stage → ValueError", False, "не упало")
    except ValueError:
        check("неверный stage → ValueError", True)


# ─── 10. file_naming.parse_export_filename ─────────────────────────────────


def test_file_naming_parse():
    print("\n[10] file_naming.parse_export_filename")

    p = file_naming.parse_export_filename("5_финальный_план_2026-05-27.pdf")
    check("parse: stage_short", p and p["stage_short"] == "5")
    check("parse: recipient self по умолчанию", p["recipient"] == "self")
    check("parse: date — date", isinstance(p["date"], dt.date) and p["date"].isoformat() == "2026-05-27")
    check("parse: ext", p["ext"] == "pdf")

    p2 = file_naming.parse_export_filename("5_финальный_план_для_родителей_2026-05-27.pdf")
    check("parse: recipient parents", p2["recipient"] == "parents")
    check("parse: short_name после удаления суффикса родителей",
          p2["short_name"] == "финальный_план")

    p3 = file_naming.parse_export_filename("4_варианты_v3_2026-05-27.docx")
    check("parse: version = 3", p3 and p3["version"] == 3)

    p4 = file_naming.parse_export_filename("5_финальный_план_2026-05-27_а.pdf")
    check("parse: discriminator", p4 and p4["discriminator"] == "а")

    # Round-trip: build → parse.
    name = file_naming.build_export_filename(
        stage="3", ext="docx", recipient="self", date=dt.date(2026, 1, 15)
    )
    round_trip = file_naming.parse_export_filename(name)
    check("build → parse round-trip",
          round_trip
          and round_trip["stage_short"] == "3"
          and round_trip["recipient"] == "self"
          and round_trip["ext"] == "docx")

    # Невалидные имена.
    check("случайное имя → None",
          file_naming.parse_export_filename("какая-то_фигня.pdf") is None)
    check("неверное расширение → None",
          file_naming.parse_export_filename("5_финальный_план_2026-05-27.txt") is None)


def test_file_naming_discriminator():
    print("\n[10b] file_naming.next_discriminator")

    check("первый свободный — а", file_naming.next_discriminator([]) == "а")
    check("после 'а' → 'б'", file_naming.next_discriminator(["а"]) == "б")
    check("пропуски не имеют значения",
          file_naming.next_discriminator(["а", "в"]) == "б")


# ─── 11. renderer ─────────────────────────────────────────────────────────


def test_renderer():
    print("\n[11] renderer")

    req = renderer.prepare_pdf_request(
        content={"foo": "bar"},
        output_path="/tmp/out.pdf",
        metadata={"trip_id": "x"},
    )
    check("RenderRequest format=pdf", req.format == "pdf")
    check("output_path str", req.output_path == "/tmp/out.pdf")
    check("content проброшен", req.content == {"foo": "bar"})
    check("metadata проброшен", req.metadata == {"trip_id": "x"})

    req2 = renderer.prepare_docx_request(content={}, output_path="/tmp/out.docx")
    check("docx request format", req2.format == "docx")

    d = req.to_dict()
    check("to_dict — словарь со всеми полями",
          set(d.keys()) >= {"format", "output_path", "content", "template_path", "style", "metadata", "notes"})

    # write_request_to_disk.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "req.json"
        renderer.write_request_to_disk(req, path)
        check("write_request_to_disk создал файл", path.exists())
        loaded = json.loads(path.read_text(encoding="utf-8"))
        check("записанный JSON содержит content", loaded["content"] == {"foo": "bar"})

    # register / get_renderer.
    def dummy_renderer(parsed, recipient, output_path, **kw):
        return renderer.prepare_pdf_request(content={"ok": True}, output_path=output_path)
    check("get_renderer до регистрации → None",
          renderer.get_renderer("xx_stage", "pdf") is None)
    renderer.register_renderer("xx_stage", "pdf", dummy_renderer)
    fn = renderer.get_renderer("xx_stage", "pdf")
    check("get_renderer после регистрации → fn", fn is dummy_renderer)
    renderer._RENDERERS.pop(("xx_stage", "pdf"), None)


# ─── 12. CLI smoke: --parse-only ──────────────────────────────────────────


def test_cli_parse_only():
    print("\n[12] CLI smoke: --parse-only")

    with tempfile.TemporaryDirectory() as tmp:
        stage_file = Path(tmp) / "5_final_plan_v1.md"
        stage_file.write_text(SAMPLE_STAGE5, encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(EXPORT_DIR / "export.py"),
             "--parse-only", str(stage_file)],
            capture_output=True, text=True, timeout=10,
        )
        check("--parse-only exit 0",
              result.returncode == 0,
              f"stderr: {result.stderr!r}")
        try:
            out = json.loads(result.stdout)
            check("вывод — валидный JSON", True)
            check("в JSON есть trip_id",
                  out.get("trip_id") == "вьетнам_2023-09")
            check("в JSON есть sections",
                  isinstance(out.get("sections"), list) and len(out["sections"]) >= 4)
        except json.JSONDecodeError as e:
            check("вывод — валидный JSON", False, str(e))


# ─── 13. CLI smoke: --stage без renderer'а ────────────────────────────────


def test_cli_stage_with_renderer():
    print("\n[13] CLI smoke: --stage 0 --engine reportlab → PDF реально создан")
    # Reportlab-движок (fallback) — единственный, кто пишет PDF локально без
    # chromium; дефолтный --engine html ушёл бы в HTML→PDF (конвертация на
    # платформе core `pdf` skill). Здесь закрепляем именно reportlab-путь:
    # renderer зарегистрирован (все 0–6), CLI находит его, рендерит и выдаёт
    # RenderRequest JSON с output_path по единой схеме. PDF-рендер требует
    # reportlab — без него stage-builder бросает RuntimeError, поэтому гейтим.
    try:
        from export import pdf_lib  # noqa: F401
        have_rl = pdf_lib.REPORTLAB_AVAILABLE
    except Exception:
        have_rl = False
    if not have_rl:
        print("  ⊘ --stage 0 render (skip: reportlab не установлен)")
        return

    sample_stage0 = """---
trip_id: вьетнам_2023-09
stage: 0_scope
travelers_profile: profiles/тест.md
duration_nights: 18
created: 2023-09-01
---

# Stage 0 — scope: вьетнам_2023-09

## Контекст для следующих стадий

соло, 18 ночей.
"""
    with tempfile.TemporaryDirectory() as tmp:
        trip_dir = Path(tmp) / "trips" / "вьетнам_2023-09"
        trip_dir.mkdir(parents=True)
        stage_file = trip_dir / "0_scope.md"
        stage_file.write_text(sample_stage0, encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(EXPORT_DIR / "export.py"),
             "--stage", "0",
             "--trip", "вьетнам_2023-09",
             "--recipient", "self",
             "--engine", "reportlab",
             # Дефолт формата теперь HTML (Р1); этот тест про reportlab→PDF —
             # запрашиваем PDF явно.
             "--format", "pdf",
             "--travel-root", tmp,
             "--output-dir", tmp],
            capture_output=True, text=True, timeout=30,
        )
        check("exit 0 при зарегистрированном renderer'е",
              result.returncode == 0,
              f"stderr: {result.stderr!r}")
        out = json.loads(result.stdout)
        check("вывод — RenderRequest dict", out.get("format") == "pdf")
        check("output_path по единой схеме (stage_trip_описание)",
              out.get("output_path", "").endswith("0_вьетнам_2023-09_регионы.pdf"),
              out.get("output_path"))
        check("PDF реально создан", Path(out["output_path"]).exists())


def test_cli_r1_defaults_and_routing():
    print("\n[13b] Р1/Р4: дефолт HTML, сверка --stage↔YAML, маршрутизация Stage 2")
    from export import export as cli  # noqa: PLC0415

    # (а) DEFAULT_FORMAT-матрица: дефолт — HTML во всех стадиях 0–6 (Р1).
    check("DEFAULT_FORMAT все стадии = html",
          all(cli.DEFAULT_FORMAT.get(s) == "html" for s in "0123456"),
          str(cli.DEFAULT_FORMAT))

    # (б) Сверка --stage ↔ YAML: чужой артефакт под нужным именем → exit 2.
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "3_poi_aggregation.md"
        f.write_text("---\ntrip_id: t\nstage: 3_poi_aggregation\n---\n\n# Stage 3\n",
                     encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(EXPORT_DIR / "export.py"),
             "--stage", "0", "--input", str(f), "--output-dir", tmp],
            capture_output=True, text=True, timeout=30)
        check("--stage 0 на stage-3 артефакте → exit 2", r.returncode == 2,
              f"rc={r.returncode} stderr={r.stderr[:120]!r}")
        check("сообщение о stage mismatch", "stage mismatch" in r.stderr)

    # (в) Stage 2 --format html → интерактивный lookup (reportlab-registry):
    #     файл с <script> и фильтрами, НЕ статичная Claude-Design-витрина.
    ko2 = (REPO_ROOT / "docs" / "travel-planning" / "calibration" / "корея"
           / "2_similarity.md")
    try:
        from export import pdf_lib
        have_rl = pdf_lib.REPORTLAB_AVAILABLE
    except Exception:
        have_rl = False
    if ko2.exists() and have_rl:
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run(
                [sys.executable, str(EXPORT_DIR / "export.py"),
                 "--stage", "2", "--input", str(ko2), "--format", "html",
                 "--output-dir", tmp],
                capture_output=True, text=True, timeout=60)
            out = json.loads(r.stdout) if r.stdout.strip() else {}
            op = out.get("output_path", "")
            html = Path(op).read_text(encoding="utf-8") if op and Path(op).exists() else ""
            check("Stage 2 html → интерактивный (<script>)", "<script" in html,
                  f"rc={r.returncode} op={op}")
    else:
        print("  ⊘ Stage 2 routing (skip: нет фикстуры/reportlab)")


# ─── 14. (удалено) CLI --import ────────────────────────────────────────────
# Бывший `test_cli_import_stub` тестировал import как заглушку Step 1 (выход
# `stage_short`/`ext`). Round-trip import давно реализован по-настоящему
# (новая trip-схема имени `3_{trip_id}_места.docx`, реальный парсинг DOCX +
# обновление `3_poi_pool.md` inplace) и полноценно покрыт в
# `tests/test_export_stage3.py` (включая `--import` CLI на реальном DOCX).
# Дублировать его здесь нечем — engine-уровень знает об import только маршрутизацию.


# ─── 15. Парсинг реальных fixtures ────────────────────────────────────────


def test_real_fixtures():
    print("\n[15] парсинг реальных fixtures из docs/travel-planning/calibration/")

    fixtures_dir = REPO_ROOT / "docs" / "travel-planning" / "calibration"
    if not fixtures_dir.exists():
        check("fixtures доступны", True, "пропускаем — docs/travel-planning/calibration отсутствует")
        return

    targets = [
        ("вьетнам", ["0_scope.md", "1_dr_reports.md", "3_poi_aggregation.md",
                     "4_variants.md", "5_final_plan.md"]),
        ("КЛТ_1",   ["0_scope_opus.md", "3_poi_aggregation.md",
                     "4_variants_v1.md", "5_final_plan_v1.md"]),
    ]
    for subdir, files in targets:
        for name in files:
            path = fixtures_dir / subdir / name
            if not path.exists():
                continue
            try:
                parsed = parser.parse_stage_file(path)
                ok_trip = bool(parsed.get("trip_id"))
                ok_sections = isinstance(parsed.get("sections"), list) and len(parsed["sections"]) >= 1
                # frontmatter_warnings допустимы, но не должны быть критичными
                # (т.е. ни на одной строке шапки не должно быть unparseable).
                fatal = [w for w in parsed["frontmatter_warnings"] if "unparseable" in w]
                check(f"{subdir}/{name}: trip_id и секции есть",
                      ok_trip and ok_sections,
                      f"trip_id={parsed.get('trip_id')!r}, sections={len(parsed.get('sections', []))}")
                check(f"{subdir}/{name}: нет fatal YAML-warnings",
                      not fatal, f"warnings: {fatal[:3]}")
            except Exception as e:
                check(f"{subdir}/{name}: парсинг не упал", False, str(e))


# ─── runner ───────────────────────────────────────────────────────────────


def main() -> int:
    test_split_frontmatter()
    test_parse_yaml()
    test_parse_sections()
    test_parse_stage_text()
    test_adapter_self()
    test_adapter_parents()
    test_adapter_stage_extension()
    test_adapter_unknown()
    test_file_naming_final_plan()
    test_file_naming_build()
    test_file_naming_parse()
    test_file_naming_discriminator()
    test_renderer()
    test_cli_parse_only()
    test_cli_stage_with_renderer()
    test_cli_r1_defaults_and_routing()
    test_real_fixtures()

    print(f"\n{'=' * 60}")
    print(f"Всего проверок: {checks_run}, провалов: {checks_failed}")
    return 0 if checks_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
