#!/usr/bin/env python3
"""parse_dr_cards.py — диагностический контрольщик DR-карточек Stage 1.

**Diagnostic-only режим.** Скрипт проверяет DR-файл `1_dr_reports.md` на
количество карточек, наличие URL, согласованность с YAML `reports_count`,
и выдаёт diagnostic JSON. **payload для similarity_score.py LLM строит
сама**, читая markdown напрямую.

**Контракт формата** (канон, с которым согласованы маркер/разделитель/
reports_count-якоря ниже) — `references/stage1/stage1-output-spec.md`. Правишь
формат `1_dr_reports.md` — правь канон; `tests/test_format_contract.py` сверяет
согласованность всех копий с ним.

Почему diagnostic-only:
- LLM (Opus) надёжно парсит даже deformed markdown — script-парсер по
  фиксированным regex проигрывает, если DR-агент адаптировал поля
  20-field structure под конкретную поездку.
- Граница LLM/script: script отвечает за **диагностику структуры**, LLM
  за **семантическую интерпретацию**. Раньше script делал и то, и другое,
  что давало хрупкость без явной выгоды.
- Маркетная функция: подсказать пользователю «может быть deformed DR
  — стоит запустить LLM-fallback» через `diagnostic.status=error`.

Парсер по-прежнему терпимый к формату (для diagnostic). Поддерживает:
- Карточки по явным маркерам `## КАРТОЧКА N`, `**КАРТОЧКА N**`,
  `### Карточка N`, `### Отчёт N` (bold или heading, регистр любой) —
  приоритетная стратегия, не зависит от ширины разделителя и ловит даже
  карточки, между которыми пропущен разделитель.
- Карточки, разделённые `---` или `-----` (3+ дефиса).
- Карточки под заголовками `### …`, `## …`, `# …`.
- Любая первая `https://` или `http://` строка в карточке = URL.
- Имя автора — из заголовка карточки ИЛИ из «3. Имя или ник…».
- `(user_added)` маркер ищется как подстрока в карточке.

Режим `--normalize` (структурная канонизация, без правки контента):
маркеры карточек любой формы → `## КАРТОЧКА N` со сквозной перенумерацией
(хвостовая аннотация `(multi-region: …)` / `(… tonality: critical)`
сохраняется), строки-разделители `-{3,}` убираются. Stage 1 гоняет его на
собранном DR-файле ПЕРЕД выдачей, чтобы downstream-парсеры (Stage 2/3 и
экспорт) получали единый формат маркеров.

Использование:
    python3 parse_dr_cards.py < 1_dr_reports.md > diagnostic.json
    python3 parse_dr_cards.py --trip-slug vietnam-2026-09 < 1_dr_reports.md
    python3 parse_dr_cards.py --min-cards 20 < 1_dr_reports.md
    python3 parse_dr_cards.py --normalize < 1_dr_reports.md > 1_dr_reports.canon.md
    python3 parse_dr_cards.py --require-count < 1_dr_reports.md   # emit-gate Stage 1

Выходной JSON (diagnostic-only, без authors[] / raw_card_text):
    {
      "trip_slug": "vietnam-2026-09",
      "total_cards": 39,
      "expected_cards": 43,
      "diagnostic": {
        "status": "ok|warning|error",
        "issues": [{severity, code, message, affected_ids}, ...],
        "cards_without_url": [...],
        "cards_without_name": [...]
      },
      "card_summaries": [
        {"id": "vietnam-2026-09-001",
         "url": "https://...",
         "name": "Имя автора",
         "user_added": false}
      ]
    }

LLM workflow:
1. Запустить parse_dr_cards.py — получить diagnostic + card_summaries.
2. Если diagnostic.status=error — opt-in fallback через диалог (§9.12).
3. Прочитать 1_dr_reports.md (markdown) напрямую.
4. Извлечь полный payload для similarity_score.py — components (0–10) и
   outlier_signal для каждой карточки. ID и URL сверять с card_summaries
   (для антигаллюцинационного контроля).
5. Запустить similarity_score.py с собранным payload.

Exit codes:
- 0 — diagnostic OK (status ok/warning) ИЛИ status=error (LLM решает дальше).
- 1 — не найдено ни одной карточки (формат файла нестандартный).
- 2 — невалидные CLI-аргументы.
"""

import argparse
import json
import re
import sys
from typing import Any

# Регексы — терпимые, без излишней строгости.
URL_PATTERN = re.compile(r"https?://[^\s<>)\"']+", re.IGNORECASE)
USER_ADDED_PATTERN = re.compile(r"\(user_added\)", re.IGNORECASE)
HEADER_PATTERN = re.compile(r"^#{1,4}\s+(.+?)$", re.MULTILINE)

# Маркер карточки — `## КАРТОЧКА N`, `**КАРТОЧКА N**`, `### Карточка N`,
# `### Отчёт N`, `Card N`, `Report N`. Bold или heading, регистр любой,
# singular-форма + одиночный номер (исключает заголовок `Карточки 1–30`).
# Самый надёжный признак границы карточки — не зависит от ширины разделителя.
CARD_MARKER_PATTERN = re.compile(
    r"^[ \t]*(?:#{1,4}[ \t]+|\*\*[ \t]*)?"
    r"(?:КАРТОЧКА|Карточка|Card|Отчёт|Отчет|Report)"
    r"[ \t]+0*\d+\b(?![ \t]*[–—-][ \t]*\d)",
    re.MULTILINE | re.IGNORECASE,
)

# Та же метка как ПОЛНАЯ строка — с захватом всей хвостовой аннотации для
# --normalize. Аннотация бывает в скобках `(multi-region: …)` /
# `(… tonality: critical)` ИЛИ через тире `— [B1 awd.ru: …]` — захватываем
# всё после номера и закрывающего `**` целиком.
CARD_MARKER_LINE_RE = re.compile(
    r"^[ \t]*(?:#{1,4}[ \t]+|\*\*[ \t]*)?"
    r"(?:КАРТОЧКА|Карточка|Card|Отчёт|Отчет|Report)"
    r"[ \t]+0*\d+[ \t]*(?:\*\*)?[ \t]*(.*?)[ \t]*$",
    re.IGNORECASE,
)

# Строка-разделитель из 3+ дефисов (терпимо к `-----`).
SEP_LINE_RE = re.compile(r"^[ \t]*-{3,}[ \t]*$")

# Heading-строка — для обрезки прилипшей преамбулы следующей карточки
# (region-заголовки между карточками при split по маркерам).
_HEADING_LINE_RE = re.compile(r"^[ \t]*#{1,4}[ \t]+\S")

# Поле 3 (имя автора) — несколько форматов.
NAME_FIELD_PATTERNS = [
    # "**3. Имя автора:** Иван" / "3. Имя или ник: helvhrav" / "3. Автор: …".
    # Greedy match label «Имя [или] ник [автора]» / «Автор» / «Author» / «Name».
    re.compile(
        r"^\s*\*{0,2}\s*3\.\s*\*{0,2}\s*"
        r"(?:Имя(?:\s+(?:или\s+)?ник)?(?:\s+автора)?|Автор|Author|Name)"
        r"\s*\*{0,2}\s*:\s*\*{0,2}\s*"
        r"([^\n*]+?)"
        r"\s*\*{0,2}\s*$",
        re.MULTILINE | re.IGNORECASE,
    ),
    # Простой формат "3. helvhrav" — если поле без явного label
    re.compile(
        r"^\s*\*{0,2}\s*3\.\s*\*{0,2}\s*([А-Яа-яA-Za-z][^\n:*]+?)\s*\*{0,2}\s*$",
        re.MULTILINE,
    ),
]


def _trim_card_chunk(chunk: str) -> str:
    """Отрезать хвостовую преамбулу следующей карточки (разделители и
    region-заголовки), прилипшую к концу чанка при split по маркерам.

    DR-файл часто кладёт region-заголовок (`### РЕГИОН 2 …`) между двумя
    карточками; при split по card-маркерам он прилипает к концу предыдущей
    карточки и ломает извлечение имени (HEADER_PATTERN взял бы region вместо
    автора). Поля карточек подзаголовков не содержат, поэтому хвостовые
    heading/separator-строки всегда принадлежат следующей карточке.
    """
    out = chunk.rstrip().split("\n")
    while out and (SEP_LINE_RE.match(out[-1]) or _HEADING_LINE_RE.match(out[-1])):
        out.pop()
    return "\n".join(out).strip()


def split_into_cards(text: str) -> list[str]:
    """Разбивает markdown на блоки-карточки.

    Стратегия по приоритету:
    0. Если есть >=3 явных маркеров карточек (`## КАРТОЧКА N`,
       `**КАРТОЧКА N**`, `### Отчёт N`, …) — split по ним. Надёжнее
       разделителей: не зависит от их ширины (`---` vs `-----`) и ловит даже
       карточки, между которыми разделитель пропущен.
    1. Если есть >=3 разделителей `-{3,}` (на отдельной строке) — split по ним.
    2/3. Если есть заголовки `### `, `## `, `# ` (любые) — split по ним.
    4. Иначе — весь текст одна «карточка» (вероятно, неправильный формат).
    """
    # Считаем `---` на отдельной строке, не в YAML.
    lines = text.split("\n")
    # Найти конец YAML frontmatter (первая закрывающая ---).
    yaml_end = -1
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                yaml_end = i
                break

    body = "\n".join(lines[yaml_end + 1:]) if yaml_end > 0 else text

    # Стратегия 0: явные маркеры карточек (приоритетная).
    marker_positions = [m.start() for m in CARD_MARKER_PATTERN.finditer(body)]
    if len(marker_positions) >= 3:
        cards = []
        for i, start in enumerate(marker_positions):
            end = (marker_positions[i + 1]
                   if i + 1 < len(marker_positions) else len(body))
            chunk = _trim_card_chunk(body[start:end])
            if chunk:
                cards.append(chunk)
        if cards:
            return cards

    # Стратегия 1: разделители `-{3,}` (терпимо к `-----`).
    parts = re.split(r"\n[ \t]*-{3,}[ \t]*\n", "\n" + body + "\n")
    parts_with_url = [p for p in parts if URL_PATTERN.search(p)]
    if len(parts_with_url) >= 3:
        return [p.strip() for p in parts_with_url]

    # Стратегия 2/3: split по markdown-заголовкам.
    # Найти позиции всех `#{1,4}\s+...` начал строк.
    header_positions = [
        m.start() for m in re.finditer(r"^#{1,4}\s+", body, re.MULTILINE)
    ]
    if len(header_positions) >= 3:
        cards = []
        for i, start in enumerate(header_positions):
            end = header_positions[i + 1] if i + 1 < len(header_positions) else len(body)
            chunk = body[start:end].strip()
            if URL_PATTERN.search(chunk):
                cards.append(chunk)
        if cards:
            return cards

    # Стратегия 4: fallback — весь body как одна карточка.
    if URL_PATTERN.search(body):
        return [body.strip()]
    return []


def normalize_dr_text(text: str) -> tuple[str, int]:
    """Канонизировать структурные маркеры DR-файла, НЕ трогая контент.

    Преобразует:
      - маркер карточки любой формы (`**КАРТОЧКА 01**`, `### Карточка 5`,
        `КАРТОЧКА 5`) → `## КАРТОЧКА {n}` со сквозной перенумерацией; хвостовая
        аннотация в скобках (`(multi-region: …)`, `(… tonality: critical)`)
        сохраняется — Stage 3 читает из неё tonality;
      - строки-разделители `-{3,}` (включая `-----`) убираются — границей
        карточки становится heading `## КАРТОЧКА N`.

    YAML frontmatter, region-заголовки, поля карточек, META-DIAGNOSTICS — без
    изменений. Возвращает (normalized_text, n_cards).
    """
    lines = text.split("\n")
    yaml_end = -1
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                yaml_end = i
                break
    head = lines[:yaml_end + 1] if yaml_end > 0 else []
    body_lines = lines[yaml_end + 1:] if yaml_end > 0 else lines

    out: list[str] = []
    n = 0
    for line in body_lines:
        if SEP_LINE_RE.match(line):
            continue  # разделитель убираем — граница теперь heading
        m = CARD_MARKER_LINE_RE.match(line)
        if m:
            n += 1
            annot = (m.group(1) or "").strip()
            out.append(f"## КАРТОЧКА {n}" + (f" {annot}" if annot else ""))
        else:
            out.append(line)

    # Схлопнуть прогоны из 3+ пустых строк (после удаления разделителей) до 1.
    collapsed: list[str] = []
    blanks = 0
    for line in out:
        if line.strip() == "":
            blanks += 1
            if blanks >= 2:
                continue
        else:
            blanks = 0
        collapsed.append(line)

    return "\n".join(head + collapsed), n


def extract_url(card_text: str) -> str:
    """Первый URL в карточке."""
    m = URL_PATTERN.search(card_text)
    return m.group(0).rstrip(".,;:!?)") if m else ""


def extract_name(card_text: str) -> str:
    """Имя автора. Несколько эвристик.

    1. Заголовок карточки (`### #5 Имя`, `## Имя автора`).
    2. Поле 3 («3. Имя автора: …»).
    3. Если ничего — пустая строка, LLM проставит.
    """
    # Попытка из заголовка.
    header_match = HEADER_PATTERN.search(card_text)
    if header_match:
        title = header_match.group(1).strip()
        # Убрать префикс типа "#5 ", "Отчёт 5: ", "Карточка 5 — "
        title = re.sub(r"^#?\d+\.?\s*[—–-]?\s*", "", title)
        title = re.sub(r"^(?:Отчёт|Карточка|Report|Card)\s+\d+\.?\s*[:—–-]?\s*",
                       "", title, flags=re.IGNORECASE)
        # Убрать (user_added)
        title = USER_ADDED_PATTERN.sub("", title).strip()
        # Убрать URL если он зашит в заголовок
        title = URL_PATTERN.sub("", title).strip()
        # Убрать остаточные скобки / запятые
        title = re.sub(r"[(),]+$", "", title).strip()
        if title and len(title) > 1:
            return title[:120]  # ограничение длины

    # Попытка из поля 3.
    for pattern in NAME_FIELD_PATTERNS:
        m = pattern.search(card_text)
        if m:
            name = m.group(1).strip().strip("*").strip()
            # Стрипнуть «Имя автора:» если попало
            name = re.sub(r"^(?:[ИиAa]м[яe][^:]*|[Аa]втор|[Nn]ame)\s*:\s*",
                          "", name)
            if name and len(name) > 1:
                return name[:120]

    return ""


def slug_from(text: str, max_len: int = 30) -> str:
    """Транслит-slug для ID: оставляет латиницу, цифры, _-, остальное →."""
    if not text:
        return ""
    # Замена кириллицы на латиницу (упрощённо).
    cyrillic_map = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
        "ё": "yo", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k",
        "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
        "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
        "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
        "э": "e", "ю": "yu", "я": "ya",
    }
    result = []
    for ch in text.lower():
        if ch in cyrillic_map:
            result.append(cyrillic_map[ch])
        elif ch.isalnum() or ch in "-_":
            result.append(ch)
        elif ch in " /":
            result.append("-")
    s = "".join(result).strip("-_")
    s = re.sub(r"-+", "-", s)
    return s[:max_len]


def parse_card(card_text: str, idx: int, trip_slug: str) -> dict[str, Any]:
    """Разбирает одну карточку в минимальную structure для diagnostic+summary.

    Diagnostic-only: только id/url/name/user_added. Никакого raw_card_text,
    components, outlier_signal — LLM строит payload отдельно, читая markdown
    напрямую.
    """
    url = extract_url(card_text)
    name = extract_name(card_text)
    user_added = bool(USER_ADDED_PATTERN.search(card_text))

    # ID: {trip_slug}-{idx:03d}. Имя в ID не включаем — может быть кириллицей,
    # неуникальным или отсутствующим. Порядковый номер достаточен и стабилен.
    author_id = f"{trip_slug}-{idx:03d}"

    return {
        "id": author_id,
        "url": url,
        "name": name,
        "user_added": user_added,
    }


# Пороги для diagnostic.status.
URL_MISSING_ERROR_RATIO = 0.20    # > 20% без URL → error
NAME_MISSING_WARNING_RATIO = 0.20  # > 20% без name → warning
COUNT_MISMATCH_ERROR_RATIO = 0.20  # expected vs found расхождение > 20% → error


# Извлечение reports_count из YAML frontmatter — для сверки expected vs found.
REPORTS_COUNT_PATTERN = re.compile(
    r"^reports_count:\s*(\d+)\s*$", re.MULTILINE,
)


def extract_reports_count(text: str) -> int | None:
    """Извлекает reports_count из YAML frontmatter, если есть.

    YAML frontmatter — блок между первыми двумя `---`.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    yaml_end = -1
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            yaml_end = i
            break
    if yaml_end < 0:
        return None
    yaml_text = "\n".join(lines[1:yaml_end])
    m = REPORTS_COUNT_PATTERN.search(yaml_text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def build_diagnostic(
    authors: list[dict[str, Any]],
    expected_count: int | None,
    require_count: bool = False,
) -> dict[str, Any]:
    """Собирает diagnostic block: status, issues, проблемные id.

    Статусы:
    - ok — всё чисто.
    - warning — некритичные пропуски (имена, мелкое расхождение count).
    - error — критичные проблемы (URL пропуски, большое расхождение count).
      Требует решения пользователя (LLM-fallback / пропустить / стоп).
    """
    found = len(authors)
    issues: list[dict[str, Any]] = []

    cards_without_url = [a["id"] for a in authors if not a["url"]]
    cards_without_name = [a["id"] for a in authors if not a["name"]]

    status = "ok"

    # 1. URL — критично.
    if found > 0 and len(cards_without_url) / found > URL_MISSING_ERROR_RATIO:
        status = "error"
        issues.append({
            "severity": "error",
            "code": "url_missing_high",
            "message": (
                f"{len(cards_without_url)}/{found} карточек без URL "
                f"(> {URL_MISSING_ERROR_RATIO:.0%}). Формат поля 1 не распознан. "
                "Требуется решение пользователя: LLM-fallback парсинг, пропуск "
                "или исправление DR-файла."
            ),
            "affected_ids": cards_without_url,
        })
    elif cards_without_url:
        issues.append({
            "severity": "warning",
            "code": "url_missing_low",
            "message": (
                f"{len(cards_without_url)}/{found} карточек без URL. "
                "Эти авторы попадут в payload с пустым URL — на Stage 3 ссылки "
                "будут недоступны."
            ),
            "affected_ids": cards_without_url,
        })
        if status == "ok":
            status = "warning"

    # 2. Имена — некритично.
    if found > 0 and len(cards_without_name) / found > NAME_MISSING_WARNING_RATIO:
        issues.append({
            "severity": "warning",
            "code": "name_missing_high",
            "message": (
                f"{len(cards_without_name)}/{found} карточек без имени автора. "
                "Имя не критично для scoring, но усложнит чтение Stage 2 файла. "
                "LLM может вытащить имена из raw_card_text при заполнении."
            ),
            "affected_ids": cards_without_name,
        })
        if status == "ok":
            status = "warning"
    elif cards_without_name:
        issues.append({
            "severity": "info",
            "code": "name_missing_few",
            "message": f"{len(cards_without_name)}/{found} карточек без имени — мелкие пропуски.",
            "affected_ids": cards_without_name,
        })

    # 3. Сверка expected vs found.
    if expected_count is not None:
        diff = abs(expected_count - found)
        ratio = diff / expected_count if expected_count else 0
        if ratio > COUNT_MISMATCH_ERROR_RATIO:
            status = "error"
            issues.append({
                "severity": "error",
                "code": "count_mismatch_high",
                "message": (
                    f"Найдено {found} карточек, в YAML reports_count={expected_count} "
                    f"(расхождение {ratio:.0%} > {COUNT_MISMATCH_ERROR_RATIO:.0%}). "
                    "Парсер мог пропустить часть карточек из-за нестандартного формата. "
                    "Требуется решение пользователя."
                ),
                "affected_ids": [],
            })
        elif diff > 0:
            issues.append({
                "severity": "warning",
                "code": "count_mismatch_low",
                "message": (
                    f"Найдено {found} карточек, ожидалось {expected_count} "
                    f"(расхождение {diff}). В пределах допуска, продолжаем."
                ),
                "affected_ids": [],
            })
            if status == "ok":
                status = "warning"
    elif require_count:
        # Emit-gate (Stage 1 валидирует свой ВЫХОД): top-level целочисленного
        # reports_count нет (отсутствует, плейсхолдер `N`, или съехал отступ
        # после списка regions и поле стало вложенным — реальный кейс прогона).
        # Это блокирующая ошибка: без поля count-assert никогда не сработает и
        # расхождение уйдёт молча в Stage 2.
        status = "error"
        issues.append({
            "severity": "error",
            "code": "count_required_missing",
            "message": (
                f"Найдено {found} карточек, но top-level `reports_count` в YAML "
                "отсутствует или не целое. Проверь, что поле не съехало под "
                "список `regions:` и стоит ровно `reports_count: N` на верхнем "
                "уровне frontmatter. При эмите Stage 1 это обязательное поле — "
                "без него Stage 2 не сможет сверить число карточек. Проставь и "
                "перепрогони."
            ),
            "affected_ids": [],
        })
    else:
        # Ingest (Stage 2 читает чужой/старый файл): reports_count нет —
        # кросс-проверку сделать нельзя, но не блокировать. Пометить info,
        # чтобы LLM глазами сверила, что found похоже на правду.
        issues.append({
            "severity": "info",
            "code": "count_not_verifiable",
            "message": (
                f"Найдено {found} карточек, но в YAML нет reports_count — "
                "число не с чем сверить. Проверь, что найдено столько, "
                "сколько ожидаешь (иначе парсер мог срезать часть по формату)."
            ),
            "affected_ids": [],
        })

    return {
        "status": status,
        "issues": issues,
        "cards_without_url": cards_without_url,
        "cards_without_name": cards_without_name,
        "found_cards": found,
        "expected_cards": expected_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Парсер DR-карточек Stage 1 → JSON-template для similarity_score.py",
    )
    parser.add_argument(
        "--trip-slug",
        type=str,
        default="dr",
        help="Префикс для ID авторов (например, 'vietnam-2026-09'). "
             "Дефолт: 'dr'.",
    )
    parser.add_argument(
        "--min-cards",
        type=int,
        default=3,
        help="Минимум карточек для успешного парсинга. Если найдено меньше — "
             "exit 1 с warning. Дефолт: 3.",
    )
    parser.add_argument(
        "--normalize",
        action="store_true",
        help="Вместо diagnostic JSON — вывести в stdout канонизированный "
             "DR-файл: маркеры карточек → `## КАРТОЧКА N` (сквозная "
             "перенумерация, аннотации сохранены), разделители `-{3,}` убраны. "
             "Контент карточек не меняется. Число карточек — в stderr.",
    )
    parser.add_argument(
        "--require-count",
        action="store_true",
        help="Emit-gate (Stage 1 валидирует свой выход): требовать top-level "
             "целочисленный `reports_count` в YAML. Без него — status=error "
             "(жёсткая ветка) вместо мягкого info. Для ingest (Stage 2) НЕ ставить.",
    )
    args = parser.parse_args()

    text = sys.stdin.read()
    if not text.strip():
        print("Ошибка: stdin пустой.", file=sys.stderr)
        return 2

    # Режим --normalize: структурная канонизация, не diagnostic.
    if args.normalize:
        normalized, n_cards = normalize_dr_text(text)
        sys.stdout.write(normalized)
        if not normalized.endswith("\n"):
            sys.stdout.write("\n")
        # Пост-проверка строгого формата: канонизация ДОЛЖНА покрыть все
        # маркеры. Если ноль — формат не распознан; если остались
        # неканонизированные строки-маркеры — частичное покрытие. В обоих
        # случаях не эмитить молча: пусть LLM разберётся с причиной.
        residual = [
            ln for ln in normalized.splitlines()
            if CARD_MARKER_PATTERN.match(ln)
            and not re.match(r"^[ \t]*## КАРТОЧКА \d+\b", ln)
        ]
        if n_cards == 0:
            print(
                "[normalize] ВНИМАНИЕ: не распознан ни один маркер карточки "
                "(`КАРТОЧКА N` / `Отчёт N`). Похоже, это не DR-файл или формат "
                "нестандартный. Разберись с причиной ПЕРЕД использованием — "
                "не эмить файл как есть.",
                file=sys.stderr,
            )
            return 1
        if residual:
            print(
                f"[normalize] ВНИМАНИЕ: {len(residual)} маркер(ов) не "
                "канонизировано (нестандартная строка маркера). Это значит, "
                "что часть карточек downstream-парсер может пропустить — "
                "проверь причину:",
                file=sys.stderr,
            )
            for ln in residual[:5]:
                print(f"    {ln.strip()[:80]}", file=sys.stderr)
            return 1
        print(f"[normalize] карточек канонизировано: {n_cards}", file=sys.stderr)
        return 0

    cards = split_into_cards(text)
    if not cards:
        # Совсем ничего не нашли — фатально, output не имеет смысла.
        print(
            "Ошибка: не нашёл ни одной карточки. Формат DR-файла не распознан. "
            "Ожидается markdown с карточками 20-field, разделёнными `---` или "
            "заголовками `### …` / `## …`. В каждой карточке должен быть URL.",
            file=sys.stderr,
        )
        return 1

    card_summaries = [
        parse_card(card, idx, args.trip_slug)
        for idx, card in enumerate(cards, start=1)
    ]

    # Сверка с reports_count из YAML и diagnostic block.
    expected_count = extract_reports_count(text)
    diagnostic = build_diagnostic(card_summaries, expected_count,
                                  require_count=args.require_count)

    # Жёсткий gate по --min-cards только если совсем мало.
    if len(card_summaries) < args.min_cards:
        diagnostic["status"] = "error"
        diagnostic["issues"].insert(0, {
            "severity": "error",
            "code": "too_few_cards",
            "message": (
                f"Найдено {len(card_summaries)} карточек, минимум {args.min_cards}. "
                "Парсер мог пропустить большинство — формат файла нестандартный."
            ),
            "affected_ids": [],
        })

    result = {
        "trip_slug": args.trip_slug,
        "total_cards": len(card_summaries),
        "expected_cards": expected_count,
        "diagnostic": diagnostic,
        "card_summaries": card_summaries,
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")

    # exit 0 всегда если есть хоть одна карточка — LLM решает по diagnostic.status
    # как поступать (продолжить / спросить пользователя / стоп).
    return 0


if __name__ == "__main__":
    sys.exit(main())
