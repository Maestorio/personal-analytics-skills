#!/usr/bin/env python3
"""
check_format.py — Pre-emit format validator для Stage 3/4/5/6 артефактов.

**Контракт формата** (секции / `decision_empty` / `todo_count` / `poi_count` —
`STAGE_CHECKS` бэкает их) — каноны `references/stage{3,4,5,6}/stageN-output-spec.md`;
согласованность копий с ними проверяет `tests/test_format_contract.py`.

Заменяет хрупкие bash-grep regex для Pre-emit Class E на детерминированную
Python-проверку через stdin → exit-code. Если модель пытается сама
прогонять `grep '\\$[0-9]'`, chat-tool ломается на encoding с `\\\\$`.
Этот скрипт изолирует проверки в pure Python.

Usage:
    python3 check_format.py --stage 4 < 4_variants.md
    python3 check_format.py --stage 5 < 5_final_plan.md
    python3 check_format.py --check dollar_escape --check yaml < file.md

Exit codes:
    0 — все проверки прошли
    1 — нарушения формата (список в stderr)
    2 — ошибка использования

Доступные проверки:
    dollar_escape   — `$NN` без escape запрещён (нужно `\\$NN`, `USD NN` или backtick)
    yaml_delimiters — три дефиса сверху и снизу YAML frontmatter
    frontmatter_integrity — frontmatter (по нормализованному тексту) без протёкшей
                      markdown-разметки (H2+/таблиц) и с ключами trip_id/stage; ловит
                      стрэй-делиметр, закрывший frontmatter не на месте, и `## trip_id:`
    decision_empty  — блок `## Решение` есть и `**Выбран вариант:**` — placeholder
    no_for_brevity  — нет фраз «опущено for brevity» / «... (сокращено)»
    no_save_as_body — нет `## Сохранить как` в теле файла (только в чате)
    todo_count      — YAML `todo_verification_items` == числу чекбоксов в секции
                      `## TODO для верификации` (Stage 5)
    poi_count       — YAML `total_pois` == числу полей «Комментарий пользователя»
                      в теле (Stage 3)

Stage presets:
    --stage 3: yaml_delimiters, poi_count
    --stage 4: dollar_escape, yaml_delimiters, decision_empty
    --stage 5: dollar_escape, yaml_delimiters, no_for_brevity, no_save_as_body, todo_count
    --stage 6: dollar_escape, yaml_delimiters, no_for_brevity, no_save_as_body
"""
import sys
import datetime as _dt
import re
import argparse


STAGE_CHECKS = {
    # Stage 0–2 (format firewall): делиметр + count-самосогласованность.
    # Полную сверку структуры (longlist names/order, коллапс полей) делают
    # парсеры экспорта-гейтами (validate_longlist / _check_parse_completeness).
    # `frontmatter_integrity` — на всех стадиях (у каждой есть frontmatter):
    # ловит протёкший в frontmatter markdown / стрэй-делиметр / потерю ключей.
    # `frontmatter_parse` + `frontmatter_placeholders` — на всех стадиях (Р5,
    # гейт эмита): непарсимый YAML / незаполненные шаблоны ловятся при сохранении.
    "0": ["yaml_delimiters", "frontmatter_integrity", "frontmatter_parse", "frontmatter_placeholders", "longlist_count"],
    "1": ["yaml_delimiters", "frontmatter_integrity", "frontmatter_parse", "frontmatter_placeholders", "reports_count"],
    "2": ["yaml_delimiters", "frontmatter_integrity", "frontmatter_parse", "frontmatter_placeholders"],
    "3": ["yaml_delimiters", "frontmatter_integrity", "frontmatter_parse", "frontmatter_placeholders", "poi_count"],
    "4": ["dollar_escape", "yaml_delimiters", "frontmatter_integrity", "frontmatter_parse", "frontmatter_placeholders", "decision_empty"],
    "5": ["dollar_escape", "yaml_delimiters", "frontmatter_integrity", "frontmatter_parse", "frontmatter_placeholders", "no_for_brevity", "no_save_as_body", "todo_count"],
    # Stage 6 (финал) — только generic-проверки: счётчиков-каунтеров у него нет
    # (координаты/досье не считаются), структурный дрейф ловит format_contract +
    # polish_check профиль `6_final`.
    "6": ["dollar_escape", "yaml_delimiters", "frontmatter_integrity", "frontmatter_parse", "frontmatter_placeholders", "no_for_brevity", "no_save_as_body"],
}

ALL_CHECKS = {
    "dollar_escape",
    "yaml_delimiters",
    "frontmatter_integrity",
    "frontmatter_parse",
    "frontmatter_placeholders",
    "decision_empty",
    "no_for_brevity",
    "no_save_as_body",
    "todo_count",
    "poi_count",
    "longlist_count",
    "reports_count",
}


def _strip_code_blocks(text: str) -> str:
    """Убирает содержимое fenced code blocks и inline backticks для проверок,
    которые не должны срабатывать внутри code-блоков (например, dollar_escape)."""
    # fenced ``` ... ```
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    # inline `...`
    text = re.sub(r"`[^`\n]*`", "", text)
    return text


def check_dollar_escape(text: str) -> list[str]:
    """`$NN` без backslash или USD prefix запрещён."""
    cleaned = _strip_code_blocks(text)
    # Negative lookbehind: not preceded by backslash, not by 'USD '
    # Match: $ followed by digit
    issues = []
    for m in re.finditer(r"(?<!\\)\$(\d)", cleaned):
        # Получить контекст
        start = max(0, m.start() - 30)
        end = min(len(cleaned), m.end() + 20)
        ctx = cleaned[start:end].replace("\n", " ")
        issues.append(f"dollar_escape: неэкранированный $-prefix у числа: «…{ctx}…»")
    return issues


def check_yaml_delimiters(text: str) -> list[str]:
    """YAML frontmatter обрамлён `---` сверху и снизу."""
    if not text.startswith("---\n"):
        return ["yaml_delimiters: файл не начинается с `---`"]
    # Найти закрывающий ---
    rest = text[4:]
    m = re.search(r"^---\s*$", rest, re.MULTILINE)
    if not m:
        return ["yaml_delimiters: не найден закрывающий `---` для YAML"]
    return []


# Делиметр-нормализация для извлечения frontmatter (как делает экспорт перед
# парсингом): `-----` (частый дрейф DR/Stage 1–2) трактуется как `---`. Без неё
# `frontmatter_integrity` смотрел бы на иной текст, чем реальный потребитель.
_DELIM_RE = re.compile(r"(?m)^-{3,}[ \t]*$")


def _normalized_frontmatter_block(text: str) -> str | None:
    """Первый frontmatter-блок (между первыми двумя делиметрами `-{3,}`) — как
    его увидит экспорт после нормализации делиметра. None если frontmatter нет.

    Берётся именно ПЕРВЫЙ закрывающий делиметр, поэтому легитимные `---`/`-----`
    разделители секций в теле (после закрытия) на результат не влияют."""
    norm = _DELIM_RE.sub("---", text)
    if not (norm.startswith("---\n") or norm.startswith("---\r\n")):
        return None
    rest = norm.split("\n", 1)[1] if "\n" in norm else ""
    m = re.search(r"(?m)^---[ \t]*$", rest)
    if not m:
        return None
    return rest[: m.start()]


def check_frontmatter_integrity(text: str) -> list[str]:
    """Целостность YAML frontmatter (по нормализованному тексту — как видит экспорт).

    Ловит два воспроизведённых дрейфа Stage 2:
    - стрэй `-----`/`---` в теле закрывает frontmatter не на месте → секции
      Контекст/Распределение/Warnings проглатываются в frontmatter-блок;
    - ключ записан как markdown-заголовок (`## trip_id:` вместо `trip_id:`).

    Проверяет: внутри первого frontmatter-блока нет markdown-заголовков (H2+) и
    таблиц; присутствуют обязательные верхнеуровневые ключи `trip_id` и `stage`.
    Отсутствие frontmatter не дублируем — это зона `yaml_delimiters`.
    """
    fm = _normalized_frontmatter_block(text)
    if fm is None:
        return []
    issues: list[str] = []

    # 1) Markdown-разметка протекла внутрь frontmatter (H2+ заголовок / таблица).
    #    H1 (одиночный `#`) не матчим, чтобы не путать с YAML-комментарием `# …`.
    leaked = [
        ln.strip() for ln in fm.splitlines()
        if re.match(r"^\s*#{2,6}\s+\S", ln) or re.match(r"^\s*\|.+\|", ln)
    ]
    if leaked:
        issues.append(
            "frontmatter_integrity: внутри YAML frontmatter markdown-разметка "
            f"({len(leaked)} стр., напр. {leaked[0][:60]!r}) — вероятно frontmatter "
            "закрылся не на месте (стрэй `-----`/`---` в теле) или ключ записан "
            "как заголовок (`## trip_id:`). Секции тела будут проглочены."
        )

    # 2) Обязательные верхнеуровневые ключи.
    keys = set()
    for ln in fm.splitlines():
        mk = re.match(r"^([A-Za-z_][\w-]*):", ln)
        if mk:
            keys.add(mk.group(1))
    for req in ("trip_id", "stage"):
        if req not in keys:
            issues.append(
                f"frontmatter_integrity: обязательный ключ `{req}` не найден в "
                f"frontmatter (возможно записан как `## {req}:` или потерян)."
            )
    return issues


_PARSER_MOD = None


def _parser():
    """Лениво загрузить export/parser.py (тот же минимальный YAML-loader, что и у
    потребителя), чтобы гейт эмита ловил ровно те warnings, что реальный парс."""
    global _PARSER_MOD
    if _PARSER_MOD is None:
        import sys as _sys
        from pathlib import Path
        _sys.path.insert(0, str(Path(__file__).resolve().parent / "export"))
        import parser as _p  # export/parser.py (в py3.12 stdlib `parser` удалён)
        _PARSER_MOD = _p
    return _PARSER_MOD


def check_frontmatter_parse(text: str) -> list[str]:
    """Гейт эмита (Р5): прогнать нормализованный frontmatter через parse_yaml;
    его warnings → FAIL. Ловит непарсимые строки, block-скаляры и прочий YAML,
    который downstream молча потерял бы (flush/flow-списки уже валидны — парсер
    их поддерживает, warning'а не будет)."""
    fm = _normalized_frontmatter_block(text)
    if fm is None:
        return []
    try:
        _, warnings = _parser().parse_yaml(fm)
    except Exception as e:  # noqa: BLE001 — гейт не должен падать
        return [f"frontmatter_parse: parse_yaml упал: {e}"]
    return [f"frontmatter_parse: {w}" for w in warnings]


# Незаполненные шаблоны-заглушки в значениях frontmatter (уехали в артефакт —
# живой кейс КЛТ_1: `dr_run_date: YYYY-MM-DD  # ← поставь дату`).
_PLACEHOLDER_RE = re.compile(r"YYYY-MM-DD|<[^>\n]{0,40}>")


def check_frontmatter_placeholders(text: str) -> list[str]:
    """Placeholder-заглушки (`YYYY-MM-DD`, `<...>`-шаблоны) в значениях
    frontmatter — незаполненные поля не должны попадать в артефакт."""
    fm = _normalized_frontmatter_block(text)
    if fm is None:
        return []
    issues: list[str] = []
    for ln in fm.splitlines():
        m = re.match(r"^\s*([\w-]+)\s*:\s*(.+)$", ln)
        if not m:
            continue
        val = m.group(2).split("#", 1)[0].strip()  # срезать inline-комментарий
        if _PLACEHOLDER_RE.search(val):
            issues.append(
                f"placeholder: поле `{m.group(1)}` содержит незаполненный "
                f"шаблон: «{val[:50]}»")
    return issues


def check_decision_empty(text: str) -> list[str]:
    """Блок `## Решение` существует и `**Выбран вариант:**` пустой/dropdown placeholder."""
    m = re.search(r"^##\s+Решение\s*$", text, re.MULTILINE)
    if not m:
        return ["decision_empty: блок `## Решение` отсутствует"]
    # Найти секцию до следующего ## или EOF
    rest = text[m.end():]
    next_h = re.search(r"^##\s+", rest, re.MULTILINE)
    section = rest[: next_h.start() if next_h else len(rest)]
    vm = re.search(r"\*\*Выбран вариант:\*\*\s*(.+?)(?:\n|$)", section)
    if not vm:
        return ["decision_empty: в блоке `## Решение` нет поля `**Выбран вариант:**`"]
    value = vm.group(1).strip()
    # placeholder values
    placeholders = {
        "<a | b | c | кастомный>",
        "<a / b / c / кастомный>",
        "<a|b|c|кастомный>",
        "",
    }
    # допускается также <вариант_a | вариант_b ...>
    if value.lower() in placeholders or value.startswith("<") and value.endswith(">"):
        return []
    return [
        f"decision_empty: `**Выбран вариант:**` не пустой/не placeholder — "
        f"получено «{value}»; Stage 4 должен оставить это поле для пользователя"
    ]


def check_no_for_brevity(text: str) -> list[str]:
    """Запрет на «опущено for brevity», «... (сокращено)» и аналоги."""
    patterns = [
        r"опущено\s+for\s+brevity",
        r"\(сокращено\)",
        r"\(skipped for brevity\)",
        r"\.{3,}\s*\(остальное аналогично\)",
        r"\(аналогично выше\)",
    ]
    issues = []
    for p in patterns:
        for m in re.finditer(p, text, re.IGNORECASE):
            issues.append(f"no_for_brevity: найден сокращатель «{m.group()}»")
    return issues


def check_no_save_as_body(text: str) -> list[str]:
    """`## Сохранить как` не должен быть в теле файла (только отдельным сообщением)."""
    if re.search(r"^##\s+Сохранить\s+как\b", text, re.MULTILINE):
        return ["no_save_as_body: блок `## Сохранить как` найден в теле файла "
                "(должен быть отдельным сообщением в чате, не в md)"]
    return []


# --- trip.yaml (контракт trip-meta@1, storage-and-naming §2.3) ---------------
# Мета-карточку поездки читают внешние потребители (индексы, дашборды):
# дрейф enum'а status или незакавыченный season ломает их молча.

TRIP_META_STATUSES = ("planning", "ready", "done", "superseded")


def check_trip_meta(text: str) -> list[str]:
    """Валидация содержимого trip.yaml (плоские ключи, без вложенности)."""
    issues: list[str] = []
    fields: dict[str, str] = {}
    for ln in text.splitlines():
        m = re.match(r"^([A-Za-z_][\w]*):\s*(.*?)\s*(?:#.*)?$", ln)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    for key in ("schema", "title", "status", "travelers", "season"):
        if not fields.get(key):
            issues.append(f"trip_meta: отсутствует или пустое обязательное поле `{key}`")
    if fields.get("schema") and fields["schema"] != "trip-meta@1":
        issues.append(f"trip_meta: schema `{fields['schema']}` ≠ `trip-meta@1`")
    if fields.get("status") and fields["status"] not in TRIP_META_STATUSES:
        issues.append(f"trip_meta: status `{fields['status']}` вне enum "
                      f"{'/'.join(TRIP_META_STATUSES)}")
    season = fields.get("season", "")
    if season:
        if not re.fullmatch(r'"\d{4}(-\d{2})?"', season):
            issues.append("trip_meta: season должен быть \"YYYY-MM\" или \"YYYY\" "
                          f"В КАВЫЧКАХ (иначе YAML отдаст число/дату), получено: {season}")
        else:
            mm = re.fullmatch(r'"\d{4}-(\d{2})"', season)
            if mm and not 1 <= int(mm.group(1)) <= 12:
                issues.append(f"trip_meta: месяц в season вне 01–12: {season}")
    trav = fields.get("travelers", "")
    if trav and not re.fullmatch(r"\[[^\[\]]+\]", trav):
        issues.append(f"trip_meta: travelers должен быть flow-списком `[имя, имя]`, получено: {trav}")
    upd = fields.get("updated", "")
    if upd and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", upd):
        issues.append(f"trip_meta: updated должен быть датой YYYY-MM-DD, получено: {upd}")
    issues += _trip_dates_issues(fields)
    return issues


def _iso_date(v: str):
    """'YYYY-MM-DD' → date или None (в т.ч. для 2026-02-30)."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v or ""):
        return None
    try:
        return _dt.date.fromisoformat(v)
    except ValueError:
        return None


def _trip_dates_issues(fields: dict) -> list[str]:
    """Точные даты поездки: необязательны, только парой, ISO, end ≥ start.
    Нет обоих ключей — нормальное состояние (поездка без точных дат)."""
    start, end = fields.get("start", ""), fields.get("end", "")
    if not start and not end:
        return []
    if not start or not end:
        return ["trip_meta: start и end ставятся только парой "
                f"(есть {'start' if start else 'end'}, нет {'end' if start else 'start'})"]
    out = []
    ds, de = _iso_date(start), _iso_date(end)
    for k, v, d in (("start", start, ds), ("end", end, de)):
        if d is None:
            out.append(f"trip_meta: {k} должен быть датой YYYY-MM-DD без кавычек, получено: {v}")
    if ds and de and de < ds:
        out.append(f"trip_meta: end {end} раньше start {start}")
    return out


def trip_meta_warnings(text: str) -> list[str]:
    """Мягкие сигналы trip.yaml — НЕ блокируют сохранение:
    - status: ready, а в season нет месяца (готовая поездка без срока —
      почти наверняка забытый месяц или даты);
    - месяц start не совпадает с season (поездку могли сдвинуть — сверить)."""
    fields: dict[str, str] = {}
    for ln in text.splitlines():
        m = re.match(r"^([A-Za-z_][\w]*):\s*(.*?)\s*(?:#.*)?$", ln)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    warns = []
    season = fields.get("season", "").strip('"')
    month = season if re.fullmatch(r"\d{4}-\d{2}", season) else ""
    ds = _iso_date(fields.get("start", ""))
    if fields.get("status") == "ready" and not month and not ds:
        warns.append("trip_meta: status ready, но ни месяца в season, ни start/end — "
                     "указать месяц или точные даты")
    if ds and month and ds.strftime("%Y-%m") != month:
        warns.append(f"trip_meta: start {ds.isoformat()} не в месяце season {month} — "
                     "сверить (поездку сдвинули?)")
    return warns


# --- Семантические count-проверки (YAML-счётчик == факт в теле) -------------
# Закрывают воспроизводимый дефект: счётчик в frontmatter ведётся вручную и
# расходится с телом (Stage 5 todo_verification_items 24 vs факт 22 на двух
# прогонах подряд). Источник истины — тело; YAML обязан совпадать.

def _yaml_frontmatter(text: str) -> str:
    """Содержимое YAML frontmatter по НОРМАЛИЗОВАННОМУ тексту (как видит экспорт):
    `-----`-делимитер трактуется как `---`, иначе count-проверки молча
    «неприменимы» на дрейфнутом делиметре. '' если frontmatter нет."""
    fm = _normalized_frontmatter_block(text)
    return fm if fm is not None else ""


def _yaml_int(text: str, field: str) -> int | None:
    """Извлекает целочисленное YAML-поле верхнего уровня из frontmatter."""
    fm = _yaml_frontmatter(text)
    m = re.search(rf"^{re.escape(field)}:\s*(\d+)\s*$", fm, re.MULTILINE)
    return int(m.group(1)) if m else None


def _section_body(text: str, header_re: str) -> str | None:
    """Тело секции от заголовка `## …` до следующего `## ` или EOF; None если нет."""
    m = re.search(header_re, text, re.MULTILINE)
    if not m:
        return None
    rest = text[m.end():]
    nxt = re.search(r"^##\s+", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def check_todo_count(text: str) -> list[str]:
    """Stage 5: YAML `todo_verification_items` == числу чекбоксов в `## TODO для верификации`."""
    section = _section_body(text, r"^##\s+TODO\s+для\s+верификации\s*$")
    if section is None:
        return []  # секции нет — проверка неприменима (не Stage 5 / другой формат)
    found = len(re.findall(r"^\s*-\s*\[[ xX]\]", section, re.MULTILINE))
    declared = _yaml_int(text, "todo_verification_items")
    if declared is None:
        return ["todo_count: секция `## TODO для верификации` есть, но в YAML нет "
                "`todo_verification_items` — нечем сверить число пунктов "
                f"(в секции найдено {found})"]
    if declared != found:
        return [f"todo_count: YAML `todo_verification_items: {declared}`, а в секции "
                f"`## TODO для верификации` фактически {found} чекбоксов. "
                f"Приведи поле к факту ({found})."]
    return []


def check_poi_count(text: str) -> list[str]:
    """Stage 3: YAML `total_pois` == числу полей «Комментарий пользователя» в теле."""
    declared = _yaml_int(text, "total_pois")
    if declared is None:
        return []  # нет total_pois — не Stage 3 артефакт
    found = sum(1 for ln in text.splitlines() if "Комментарий пользователя" in ln)
    if declared != found:
        return [f"poi_count: YAML `total_pois: {declared}`, а полей "
                f"«Комментарий пользователя» в теле {found}. Расхождение — вероятно "
                f"потеряны/слиты POI или счётчик отстал; приведи к факту ({found})."]
    return []


# Толерантный маркер карточки Stage 1 (`## КАРТОЧКА N` / `**КАРТОЧКА 01**` /
# `### Карточка N` / `Card/Отчёт/Report N`; не диапазон `Карточки 1–30`).
_CARD_MARKER_RE = re.compile(
    r"^[ \t]*(?:#{1,4}[ \t]+|\*\*[ \t]*)?"
    r"(?:КАРТОЧКА|Карточка|Card|Отч[её]т|Report)"
    r"[ \t]+0*\d+\b(?![ \t]*[–—-][ \t]*\d)",
    re.MULTILINE | re.IGNORECASE,
)


def check_longlist_count(text: str) -> list[str]:
    """Stage 0: YAML `longlist_count` == числу `### `-регионов в секции `## Longlist`."""
    declared = _yaml_int(text, "longlist_count")
    if declared is None:
        return []  # нет longlist_count — не Stage 0 артефакт
    section = _section_body(text, r"^##\s+Longlist")
    if section is None:
        return []  # секции нет — нечем сверить
    found = len(re.findall(r"^###\s+\S", section, re.MULTILINE))
    if declared != found:
        return [f"longlist_count: YAML `longlist_count: {declared}`, а `### `-регионов "
                f"в `## Longlist` фактически {found}. Расхождение — потеряны/добавлены "
                f"регионы или счётчик отстал; приведи к факту ({found})."]
    return []


def check_reports_count(text: str) -> list[str]:
    """Stage 1: YAML `reports_count` == числу маркеров карточек в теле."""
    declared = _yaml_int(text, "reports_count")
    if declared is None:
        return []  # нет reports_count — не Stage 1 артефакт
    found = len(_CARD_MARKER_RE.findall(text))
    if declared != found:
        return [f"reports_count: YAML `reports_count: {declared}`, а маркеров карточек "
                f"в теле {found}. Расхождение — потеряны/добавлены карточки или счётчик "
                f"отстал; приведи к факту ({found})."]
    return []


CHECK_FUNCS = {
    "dollar_escape": check_dollar_escape,
    "yaml_delimiters": check_yaml_delimiters,
    "frontmatter_integrity": check_frontmatter_integrity,
    "frontmatter_parse": check_frontmatter_parse,
    "frontmatter_placeholders": check_frontmatter_placeholders,
    "decision_empty": check_decision_empty,
    "no_for_brevity": check_no_for_brevity,
    "no_save_as_body": check_no_save_as_body,
    "todo_count": check_todo_count,
    "poi_count": check_poi_count,
    "longlist_count": check_longlist_count,
    "reports_count": check_reports_count,
}


def main() -> int:
    p = argparse.ArgumentParser(description="Stage 0–6 format pre-emit validator")
    p.add_argument("--stage", choices=sorted(STAGE_CHECKS),
                   help="preset checks for a stage (0–6)")
    p.add_argument("--check", action="append", choices=sorted(ALL_CHECKS),
                   help="explicit check (repeatable); overrides --stage")
    args = p.parse_args()

    if args.check:
        checks = args.check
    elif args.stage:
        checks = STAGE_CHECKS[args.stage]
    else:
        print("usage: --stage 4|5 OR --check NAME [--check NAME ...]", file=sys.stderr)
        return 2

    text = sys.stdin.read()
    all_issues: list[str] = []
    for name in checks:
        issues = CHECK_FUNCS[name](text)
        all_issues.extend(issues)

    if all_issues:
        print(f"FAIL: {len(all_issues)} нарушений формата", file=sys.stderr)
        for issue in all_issues:
            print(f"  - {issue}", file=sys.stderr)
        return 1

    print(f"OK: все проверки прошли ({len(checks)})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
