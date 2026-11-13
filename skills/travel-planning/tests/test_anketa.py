#!/usr/bin/env python3
"""Тесты anketa: profile.md → answers → DOCX → answers → profile.md.

Запуск:
    /usr/bin/python3 skills/travel-planning/tests/test_anketa.py
"""
from __future__ import annotations
import sys
import tempfile
from pathlib import Path

# Подключаем scripts/
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from profile.anketa_spec import (
    ANKETA_SECTIONS, ARCHETYPE_VALUES, ARCHETYPE_LEGACY_ALIASES,
    QUESTIONS_BY_ID, Question, Subheader,
)
from profile.anketa_builder import build_docx
from profile.anketa_docx_parser import (
    parse_docx, _parse_option_line, _match_option_value,
)
from profile.profile_md_parser import parse_profile_md, _parse_yaml_frontmatter
from profile.profile_assembler import assemble_profile_md
from profile.profile_merger import merge_answers, merged_profile_id


PASSED = 0
FAILED = 0
FAILURES: list = []


def check(cond, message: str) -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
    else:
        FAILED += 1
        FAILURES.append(message)


# ---------------------------------------------------------------------------
# 1. Спека: целостность
# ---------------------------------------------------------------------------

def test_spec_integrity():
    check(len(ANKETA_SECTIONS) == 18,
          f"expected 18 sections, got {len(ANKETA_SECTIONS)}")
    # Переносимость — отдельная секция, не подпункт «Физической формы»
    tol = next((s for s in ANKETA_SECTIONS if s.id == "переносимость"), None)
    check(tol is not None and tol.profile_h2 == "## Переносимость",
          "секция «Переносимость» отсутствует или с чужим profile_h2")
    if tol:
        check({q.id for q in tol.questions()} == {
                  "переносимость.климат",
                  "переносимость.экспозиция",
                  "переносимость.транспорт"},
              "состав вопросов «Переносимости» разошёлся со спекой")
    # Все секции имеют уникальные id
    ids = [s.id for s in ANKETA_SECTIONS]
    check(len(set(ids)) == len(ids), "section ids must be unique")
    # Все qid уникальны
    qids = []
    for s in ANKETA_SECTIONS:
        for q in s.questions():
            qids.append(q.id)
    check(len(set(qids)) == len(qids), "qids must be unique")
    # Архетип в spec присутствует с валидными значениями
    arch_q = QUESTIONS_BY_ID.get("архетип.значение")
    check(arch_q is not None, "архетип.значение question missing")
    if arch_q:
        opts = [v for v, _ in arch_q.options]
        check(set(opts) == set(ARCHETYPE_VALUES),
              f"archetype options mismatch: {opts} vs {ARCHETYPE_VALUES}")
    # Маркеры — только из допустимого набора
    valid_markers = {"[ОБЯЗАТЕЛЬНО]", "[ВАЖНО]", "[ОПЦИОНАЛЬНО]", ""}
    for s in ANKETA_SECTIONS:
        check(s.marker in valid_markers,
              f"section {s.id} has invalid marker «{s.marker}»")
    # Архетип помечен ОБЯЗАТЕЛЬНО
    arch_sec = next((s for s in ANKETA_SECTIONS if s.id == "архетип"), None)
    check(arch_sec and arch_sec.marker == "[ОБЯЗАТЕЛЬНО]",
          "архетип section must be [ОБЯЗАТЕЛЬНО]")


# ---------------------------------------------------------------------------
# 2. YAML frontmatter mini-parser
# ---------------------------------------------------------------------------

def test_frontmatter_parser():
    txt = "---\nprofile_id: x\ncreated: 2026-01-01\ngруппа_архетип: люкс\n---\n\n# Body\n"
    # Используем правильное русское "г"
    txt = "---\nprofile_id: x\ncreated: 2026-01-01\nгруппа_архетип: люкс\n---\n\n# Body\n"
    fm, body = _parse_yaml_frontmatter(txt)
    check(fm.get("profile_id") == "x", f"profile_id parse: {fm}")
    check(fm.get("группа_архетип") == "люкс", f"архетип parse: {fm}")
    check(body.strip().startswith("# Body"), "body extracted")

    # Вложенный блок similarity_weights_override
    txt2 = (
        "---\n"
        "profile_id: x\n"
        "группа_архетип: самостоятельные\n"
        "similarity_weights_override:\n"
        "  стиль: 30\n"
        "  фокус: 25\n"
        "  темп: 15\n"
        "  независимость: 5\n"
        "  non_touristy: 15\n"
        "  возраст_состав: 10\n"
        "---\n\n"
    )
    fm2, _ = _parse_yaml_frontmatter(txt2)
    swo = fm2.get("similarity_weights_override", {})
    check(isinstance(swo, dict) and swo.get("стиль") == 30,
          f"nested block parse: {swo}")


# ---------------------------------------------------------------------------
# 3. Парсер profile.md → answers (на профиле алексей)
# ---------------------------------------------------------------------------

PROFILE_OWNER = (
    "/Users/you/Library/CloudStorage/SynologyDrive-home/"
    "Claude-Memory/travel-planner/profiles/алексей.md"
)


def test_parse_profile_md():
    if not Path(PROFILE_OWNER).exists():
        print(f"  - skip: личный профиль недоступен ({PROFILE_OWNER}) — проверка только на машине владельца")
        return
    p = parse_profile_md(PROFILE_OWNER)
    fm = p.frontmatter
    check(fm.get("profile_id") == "алексей", f"profile_id: {fm.get('profile_id')}")
    check(fm.get("группа_архетип") in ("самостоятельные", "независимые_соло_пара"),
          f"архетип: {fm.get('группа_архетип')}")
    # Ключевые ответы извлечены
    a = p.answers
    check("базовый_город.значение" in a, "базовый город не извлечён")
    check(a.get("базовый_город.значение", {}).get("text") == "Москва",
          f"базовый город: {a.get('базовый_город.значение')}")
    check("архетип.значение" in a, "архетип не извлечён")
    check("возраст.значение" in a, "возраст не извлечён (fallback из состава)")
    check(a.get("возраст.значение", {}).get("text", "").strip() == "37",
          f"возраст: {a.get('возраст.значение')}")
    # Стиль.класс = средний (а не бюджетный — известный косяк, исправленный)
    check(a.get("стиль.класс", {}).get("selected") == ["средний"],
          f"стиль.класс: {a.get('стиль.класс')}")
    # Гастро.стиль = обычные рестораны (а не гастро-рестораны — исправлено)
    check(a.get("гастро.стиль", {}).get("selected") == ["обычные рестораны"],
          f"гастро.стиль: {a.get('гастро.стиль')}")
    # Вождение — нет
    check(a.get("вождение.готовность", {}).get("selected") == ["нет"],
          f"вождение: {a.get('вождение.готовность')}")
    # Темп — умеренный
    check(a.get("темп.значение", {}).get("selected") == ["умеренный"],
          f"темп: {a.get('темп.значение')}")
    # Платежи карты — Visa+MC
    cards = a.get("платежи.карты", {})
    check(set(cards.get("selected", [])) == {"Visa", "Mastercard"},
          f"карты: {cards}")


# ---------------------------------------------------------------------------
# 4. Backward-compat: legacy архетип родители_60_плюс
# ---------------------------------------------------------------------------

def test_legacy_archetype_alias():
    check("родители_60_плюс" in ARCHETYPE_LEGACY_ALIASES,
          "legacy alias for родители_60_плюс отсутствует")
    check(ARCHETYPE_LEGACY_ALIASES["родители_60_плюс"] == "взрослые_50_плюс",
          "родители_60_плюс должен мапиться на взрослые_50_плюс")

    # Эмулируем legacy profile
    legacy_md = (
        "---\nprofile_id: тест\ncreated: 2024-01-01\nупdated: 2024-01-01\n"
        "группа_архетип: родители_60_плюс\n---\n\n# Профиль: Тест\n\n"
        "## Состав группы\n- 2 человека, 65 и 68 лет\n"
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(legacy_md)
        legacy_path = f.name
    p = parse_profile_md(legacy_path)
    arch = p.answers.get("архетип.значение", {})
    check(arch.get("selected") == ["взрослые_50_плюс"],
          f"legacy архетип не сконвертирован: {arch}")
    Path(legacy_path).unlink()


# ---------------------------------------------------------------------------
# 4a. Переименование архетипа: независимые_соло_пара → самостоятельные
#     (legacy-алиас продолжает работать на импорте и предзаполнении)
# ---------------------------------------------------------------------------

LEGACY_SOLO = "независимые_соло_пара"
CANON_SOLO = "самостоятельные"


def _write_tmp_profile(archetype: str) -> str:
    md = (
        "---\nprofile_id: тест\ncreated: 2024-01-01\nupdated: 2024-01-01\n"
        f"группа_архетип: {archetype}\n---\n\n# Профиль: Тест\n\n"
        "## Состав группы\n- 2 человека, 37 и 35 лет\n"
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(md)
        return f.name


def test_archetype_rename_spec():
    check(ARCHETYPE_VALUES[0] == CANON_SOLO,
          f"каноническое имя первым в ARCHETYPE_VALUES: {ARCHETYPE_VALUES}")
    check(LEGACY_SOLO not in ARCHETYPE_VALUES,
          "legacy-имя не должно быть в списке канонических значений")
    check(ARCHETYPE_LEGACY_ALIASES.get(LEGACY_SOLO) == CANON_SOLO,
          "алиас независимые_соло_пара → самостоятельные отсутствует")
    q = QUESTIONS_BY_ID["архетип.значение"]
    opts = dict(q.options)
    check(CANON_SOLO in opts and LEGACY_SOLO not in opts,
          f"опции анкеты: {list(opts)}")
    check("соло или пара, планируют сами, без гида" in opts.get(CANON_SOLO, ""),
          f"подпись опции: {opts.get(CANON_SOLO)}")


def test_archetype_rename_prefill_from_legacy_profile():
    """Профиль со старым значением → в предзаполненной анкете чекбокс канонический."""
    path = _write_tmp_profile(LEGACY_SOLO)
    try:
        p = parse_profile_md(path)
        check(p.answers.get("архетип.значение", {}).get("selected") == [CANON_SOLO],
              f"legacy не нормализован при импорте: {p.answers.get('архетип.значение')}")
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            docx_path = f.name
        try:
            build_docx(out_path=docx_path, answers=p.answers, profile_id="тест")
            from docx import Document
            texts = [para.text for para in Document(docx_path).paragraphs]
            check(any(t.startswith("[x]") and t.endswith(CANON_SOLO) for t in texts),
                  "в предзаполненной анкете не отмечен чекбокс «самостоятельные»")
            check(not any(LEGACY_SOLO in t for t in texts),
                  "legacy-имя не должно попадать в анкету")
            p2 = parse_docx(docx_path)
            check(p2.answers.get("архетип.значение", {}).get("selected") == [CANON_SOLO],
                  "roundtrip DOCX потерял архетип")
        finally:
            Path(docx_path).unlink(missing_ok=True)
    finally:
        Path(path).unlink(missing_ok=True)


def test_archetype_rename_canonical_profile_roundtrip():
    path = _write_tmp_profile(CANON_SOLO)
    try:
        p = parse_profile_md(path)
        check(p.answers.get("архетип.значение", {}).get("selected") == [CANON_SOLO],
              "каноническое имя должно читаться напрямую")
    finally:
        Path(path).unlink(missing_ok=True)


def test_archetype_rename_docx_legacy_label_and_assembler():
    """Старая анкета с отмеченным legacy-чекбоксом → канон; ассемблер пишет канон."""
    q = QUESTIONS_BY_ID["архетип.значение"]
    check(_match_option_value(q, LEGACY_SOLO) == (CANON_SOLO, ""),
          f"legacy-метка в DOCX: {_match_option_value(q, LEGACY_SOLO)}")
    check(_match_option_value(q, CANON_SOLO) == (CANON_SOLO, ""),
          "каноническая метка в DOCX")
    md, warnings = assemble_profile_md(
        answers={"архетип.значение": {"selected": [LEGACY_SOLO], "clarifications": {}}},
        profile_id="тест",
    )
    check(f"группа_архетип: {CANON_SOLO}" in md and LEGACY_SOLO not in md,
          "ассемблер должен писать каноническое имя при legacy на входе")
    check(not any("не из допустимого набора" in w for w in warnings),
          f"legacy не должен давать warning: {warnings}")


# ---------------------------------------------------------------------------
# 5. Builder DOCX: пустой шаблон не падает
# ---------------------------------------------------------------------------

def test_build_empty_docx():
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        out = f.name
    try:
        saved = build_docx(out_path=out)
        check(saved.exists() and saved.stat().st_size > 5000,
              f"empty DOCX слишком мал: {saved.stat().st_size if saved.exists() else 'no file'}")
    finally:
        Path(out).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 6. Round-trip: profile.md → answers → DOCX → answers → answers (semantic eq)
# ---------------------------------------------------------------------------

def test_roundtrip_arsenij():
    if not Path(PROFILE_OWNER).exists():
        return
    p = parse_profile_md(PROFILE_OWNER)
    original = p.answers

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        out = f.name
    try:
        build_docx(out_path=out, answers=original, profile_id="алексей")
        parsed = parse_docx(out)
        roundtrip = parsed.answers

        # Сравним ключевые поля семантически
        keys_to_check = [
            "архетип.значение",
            "базовый_город.значение",
            "темп.значение",
            "стиль.планирование",
            "стиль.класс",
            "стиль.ночные",
            "вождение.готовность",
            "форма.уровень",
            "фото.уровень",
            "частота.значение",
            "платежи.локальные",
        ]
        for k in keys_to_check:
            orig = original.get(k, {}).get("selected", [])
            rt = roundtrip.get(k, {}).get("selected", [])
            check(orig == rt,
                  f"round-trip {k}: original={orig}, roundtrip={rt}")
        # Multi-choice
        multi_keys = ["стиль.транспорт", "гастро.стиль", "платежи.карты"]
        for k in multi_keys:
            orig = set(original.get(k, {}).get("selected", []))
            rt = set(roundtrip.get(k, {}).get("selected", []))
            check(orig == rt,
                  f"round-trip multi {k}: original={orig}, roundtrip={rt}")
        # Text fields — текст сохраняется
        text_keys = ["базовый_город.значение", "возраст.значение",
                     "состав.языки", "гастро.напитки"]
        for k in text_keys:
            orig = original.get(k, {}).get("text", "").strip()
            rt = roundtrip.get(k, {}).get("text", "").strip()
            check(orig == rt or (orig in rt) or (rt in orig),
                  f"round-trip text {k}: «{orig}» vs «{rt}»")
    finally:
        Path(out).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 7. Assembler: profile.md собирается и содержит все [ОБЯЗАТЕЛЬНО]-секции
# ---------------------------------------------------------------------------

def test_assembler_required_sections():
    if not Path(PROFILE_OWNER).exists():
        return
    p = parse_profile_md(PROFILE_OWNER)
    md, warnings = assemble_profile_md(
        answers=p.answers,
        profile_id="алексей",
        created="2026-05-21",
        updated="2026-05-30",
    )
    # Frontmatter
    check("profile_id: алексей" in md, "frontmatter profile_id отсутствует")
    # Профиль может хранить legacy-имя; ассемблер пишет каноническое.
    check("группа_архетип: самостоятельные" in md,
          "frontmatter архетип отсутствует")
    # Каждая [ОБЯЗАТЕЛЬНО]-секция должна присутствовать
    for sec in ANKETA_SECTIONS:
        if sec.marker == "[ОБЯЗАТЕЛЬНО]" and sec.profile_h2:
            check(sec.profile_h2 in md,
                  f"обязательная секция «{sec.profile_h2}» отсутствует в выходе")
    # Архетип НЕ дублируется в body
    check(md.count("## Архетип") == 0,
          "архетип не должен попадать в body — только в frontmatter")
    # Базовый город
    check("- Москва" in md, "Базовый город не записан")


def test_assembler_missing_archetype_warning():
    md, warnings = assemble_profile_md(
        answers={},  # пусто
        profile_id="пусто",
    )
    check(any("архетип" in w.lower() for w in warnings),
          f"должна быть warning про архетип, получили: {warnings}")
    # Fallback архетип присутствует
    check("группа_архетип: самостоятельные" in md,
          "fallback архетип не подставлен")


# ---------------------------------------------------------------------------
# 8. DOCX-parser: обработка edge cases
# ---------------------------------------------------------------------------

def test_docx_parser_edge_cases():
    # Сгенерим DOCX с известными answers, в т.ч. с clarifications
    answers = {
        "базовый_город.значение": {"text": "Тбилиси"},
        "темп.значение": {"selected": ["активный"], "clarifications": {"активный": "со скидкой на жару"}},
        "стиль.транспорт": {
            "selected": ["общественный", "аренда машины"],
            "clarifications": {"общественный": "только метро"},
        },
        "архетип.значение": {"selected": ["взрослые_50_плюс"], "clarifications": {}},
    }
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        out = f.name
    try:
        build_docx(out_path=out, answers=answers, profile_id="тест")
        parsed = parse_docx(out)
        a = parsed.answers
        check(a.get("базовый_город.значение", {}).get("text") == "Тбилиси",
              f"город: {a.get('базовый_город.значение')}")
        tempo = a.get("темп.значение", {})
        check(tempo.get("selected") == ["активный"], f"темп: {tempo}")
        check(tempo.get("clarifications", {}).get("активный") == "со скидкой на жару",
              f"темп clar: {tempo}")
        tr = a.get("стиль.транспорт", {})
        check(set(tr.get("selected", [])) == {"общественный", "аренда машины"},
              f"транспорт: {tr}")
        check(tr.get("clarifications", {}).get("общественный") == "только метро",
              f"транспорт clar: {tr}")
        arch = a.get("архетип.значение", {})
        check(arch.get("selected") == ["взрослые_50_плюс"],
              f"архетип: {arch}")
    finally:
        Path(out).unlink(missing_ok=True)


def test_checkbox_v_marks_and_trailing_clar():
    """Реальный кейс анкеты «родители»: галочки `[v ]` вместо `[x]` и дописка
    после варианта без скобок («нет жёсткого мнения 2-3 ночи»)."""
    # --- Fix A: маркер «отмечено» терпим к x/X, кир. х/Х, ✓, V/v, кир. В/в
    #     и к лишним пробелам внутри скобок ([v ], [x ], [ v ]) ---
    for line in ("[x]  активный", "[X]  активный", "[х]  активный",
                 "[✓]  активный", "[v]  активный", "[V]  активный",
                 "[в]  активный", "[v ]  активный", "[x ]  активный",
                 "[ v ]  активный"):
        res = _parse_option_line(line)
        check(res is not None and res[0] is True and res[1] == "активный",
              f"checkbox отмечено: {line!r} → {res}")
    for line in ("[ ]  активный", "[]  активный", "[   ]  активный"):
        res = _parse_option_line(line)
        check(res is not None and res[0] is False and res[1] == "активный",
              f"checkbox пусто: {line!r} → {res}")
    check(_parse_option_line("Ответ: что-то") is None, "не-чекбокс → None")
    # уточнение в круглых скобках по-прежнему ловится
    res = _parse_option_line("[v]  средний (в Европе бюджет)")
    check(res == (True, "средний", "в Европе бюджет"), f"clar в скобках: {res}")

    # --- Fix B: хвост после канон-варианта без скобок → clarification ---
    q = Question(id="частота.значение", type="single", text="Частота",
                 options=[("1-2 ночи", ""), ("3-5 ночей", ""),
                          ("нет жёсткого мнения", "")])
    check(_match_option_value(q, "нет жёсткого мнения 2-3 ночи")
          == ("нет жёсткого мнения", "2-3 ночи"), "хвост §7 как clar")
    check(_match_option_value(q, "нет жёсткого мнения")
          == ("нет жёсткого мнения", ""), "точное совпадение → ('canon','')")
    check(_match_option_value(q, "что попало") is None, "не из набора → None")


# ---------------------------------------------------------------------------
# 9. Полный pipeline CLI-style: profile.md → DOCX → profile.md семантическая
#    идентичность по ключевым полям
# ---------------------------------------------------------------------------

def test_merge_arsenij_alena():
    """MERGE двух реальных профилей: per-§4.1 правила, ASK для архетипа/состава/
    бюджета, MIN для темп/класс, UNION для языков, INTERSECT для транспорта."""
    if not Path(PROFILE_OWNER).exists():
        return
    alena_path = Path(PROFILE_OWNER).parent / "мария.md"
    if not alena_path.exists():
        return
    p_a = parse_profile_md(PROFILE_OWNER)
    p_b = parse_profile_md(alena_path)
    merged, ask_items = merge_answers(
        [p_a.answers, p_b.answers],
        ["алексей", "мария"],
    )
    # Архетип: у обоих `самостоятельные` (в профилях может стоять legacy-имя
    # `независимые_соло_пара` — парсер нормализует его через алиас)
    # → согласие, без ASK; значение переносится в merged.
    ask_qids = {item.qid for item in ask_items}
    check("архетип.значение" not in ask_qids,
          f"согласный архетип не должен быть в ASK: {sorted(ask_qids)}")
    check(merged.get("архетип.значение", {}).get("selected")
          == ["самостоятельные"],
          f"архетип должен перенестись: {merged.get('архетип.значение')}")
    # Бюджет ориентир — ASK (расходятся)
    check("бюджет.ориентир" in ask_qids, "бюджет.ориентир должен быть в ASK")
    # Состав — ASK (всегда подтверждаем)
    check("состав.люди_паспорта" in ask_qids, "состав должен быть в ASK")
    # Частота — ASK (1-2 vs 3-5 — противоположные)
    check("частота.значение" in ask_qids, "частота должна быть в ASK")
    # Возраст — ASK
    check("возраст.значение" in ask_qids, "возраст должен быть в ASK")

    # Темп — MIN: умеренный (алексей) более ограничителен, чем активный (мария)
    check(merged.get("темп.значение", {}).get("selected") == ["умеренный"],
          f"темп MIN: {merged.get('темп.значение')}")
    # Класс размещения — оба «средний» → один результат
    check(merged.get("стиль.класс", {}).get("selected") == ["средний"],
          f"стиль.класс MIN: {merged.get('стиль.класс')}")
    # Языки — UNION_TEXT, должны содержать обоих
    langs = merged.get("состав.языки", {}).get("text", "")
    check("алексей" in langs and "мария" in langs,
          f"состав.языки должен union'ить оба профиля: {langs}")
    # Опыт — UNION_TEXT, должны быть оба
    exp = merged.get("опыт.значение", {}).get("text", "")
    check("алексей" in exp and "мария" in exp,
          f"опыт должен union'ить: {exp[:100]}")
    # Платежи.карты — UNION (Visa, Mastercard, Mir)
    cards = set(merged.get("платежи.карты", {}).get("selected", []))
    check("Visa" in cards and "Mastercard" in cards and "Mir" in cards,
          f"карты union: {cards}")


def test_merge_full_agreement_no_ask():
    """Если все профили идентичны — никаких ASK не должно быть."""
    a = {
        "темп.значение": {"selected": ["умеренный"], "clarifications": {}},
        "архетип.значение": {"selected": ["самостоятельные"], "clarifications": {}},
        "опыт.значение": {"text": "Греция, Италия"},
    }
    merged, ask = merge_answers([a, dict(a)], ["one", "two"])
    # Архетип одинаков — без ASK
    ask_qids = {x.qid for x in ask}
    check("архетип.значение" not in ask_qids,
          f"одинаковый архетип не должен быть в ASK: {ask_qids}")
    check(merged["темп.значение"]["selected"] == ["умеренный"],
          "темп должен сохраниться")


def test_merge_intersect_transport_empty_to_ask():
    """Если transport sets не пересекаются — должно быть ASK."""
    a = {"стиль.транспорт": {"selected": ["общественный"], "clarifications": {}}}
    b = {"стиль.транспорт": {"selected": ["аренда машины", "байки/скутеры"],
                              "clarifications": {}}}
    merged, ask = merge_answers([a, b], ["one", "two"])
    ask_qids = {x.qid for x in ask}
    check("стиль.транспорт" in ask_qids,
          f"пустое пересечение transport должно быть ASK: {ask_qids}")


def test_merged_profile_id_owner_first():
    check(merged_profile_id(["алексей", "мария"]) == "алексей_мария",
          "владелец алексей должен быть первым")
    check(merged_profile_id(["мария", "дмитрий"]) == "дмитрий_мария",
          "без владельца — по алфавиту")
    check(merged_profile_id(["саша", "алексей", "иван"]) == "алексей_иван_саша",
          "владелец первый, остальные по алфавиту")


def test_alena_legacy_aliases():
    """Марии profile использует legacy section names. Проверяем что aliases
    в _SECTION_ALIASES сработали."""
    alena_path = Path(PROFILE_OWNER).parent / "мария.md"
    if not alena_path.exists():
        return
    p = parse_profile_md(alena_path)
    check("вождение.готовность" in p.answers,
          "Legacy alias «Вождение» → вождение.готовность")
    check("состав.языки" in p.answers,
          "Legacy alias «Языки и коммуникация» → состав.языки")
    check("стиль.класс" in p.answers,
          "Legacy alias «Размещение» → стиль.класс")


def test_full_pipeline_semantic_eq():
    if not Path(PROFILE_OWNER).exists():
        return
    # 1. parse_profile_md
    p1 = parse_profile_md(PROFILE_OWNER)
    # 2. build DOCX
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        docx_path = f.name
    try:
        build_docx(out_path=docx_path, answers=p1.answers, profile_id="алексей")
        # 3. parse DOCX
        p2 = parse_docx(docx_path)
        # 4. assemble new profile
        md2, _ = assemble_profile_md(
            answers=p2.answers,
            profile_id="алексей",
            created=p1.frontmatter.get("created"),
            updated="2026-05-30",
        )
        # Проверки на md2
        check("Москва" in md2, "Москва потерян в финальном md")
        check("самостоятельные" in md2, "архетип потерян в финальном md")
        check("умеренный" in md2, "темп потерян")
        check("Fujifilm" in md2 or "фотограф" in md2.lower(),
              "фото-секция потеряна")
    finally:
        Path(docx_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

def run():
    tests = [
        test_spec_integrity,
        test_frontmatter_parser,
        test_parse_profile_md,
        test_legacy_archetype_alias,
        test_archetype_rename_spec,
        test_archetype_rename_prefill_from_legacy_profile,
        test_archetype_rename_canonical_profile_roundtrip,
        test_archetype_rename_docx_legacy_label_and_assembler,
        test_alena_legacy_aliases,
        test_build_empty_docx,
        test_roundtrip_arsenij,
        test_assembler_required_sections,
        test_assembler_missing_archetype_warning,
        test_docx_parser_edge_cases,
        test_checkbox_v_marks_and_trailing_clar,
        test_merge_arsenij_alena,
        test_merge_full_agreement_no_ask,
        test_merge_intersect_transport_empty_to_ask,
        test_merged_profile_id_owner_first,
        test_full_pipeline_semantic_eq,
    ]
    for t in tests:
        try:
            t()
        except Exception as e:  # pragma: no cover
            global FAILED
            FAILED += 1
            FAILURES.append(f"{t.__name__} crashed: {e}")
    print(f"\nанкета: {PASSED} passed, {FAILED} failed")
    if FAILURES:
        print("\nFailures:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
