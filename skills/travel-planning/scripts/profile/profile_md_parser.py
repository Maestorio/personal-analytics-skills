"""Парсер существующего profile.md → answers dict.

Используется для prefill DOCX в UPDATE flow. Best-effort — секции, которые
не маппятся 1:1 на структурированные вопросы, попадают в text-ответы как есть
или нормализуются с предупреждением.

Парсер НЕ падает на отсутствующих секциях — просто пропускает их (qid не
попадает в answers).
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ParsedProfile:
    frontmatter: dict             # profile_id, created, updated, группа_архетип, …
    answers: dict                 # qid → {"text": "..."} | {"selected": [...], "clarifications": {...}}
    sections_raw: dict            # name (без "## ") → body text — для отладки


# ---------------------------------------------------------------------------
# YAML frontmatter
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_yaml_frontmatter(text: str) -> tuple[dict, str]:
    """Мини-парсер YAML frontmatter (без зависимостей).

    Поддерживает `key: value` строки и вложенный `similarity_weights_override`
    блок (как dict). Достаточно для profile-management §7.1.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw = m.group(1)
    body = text[m.end():]
    fm: dict = {}
    current_block_key: Optional[str] = None
    current_block: dict = {}
    for line in raw.splitlines():
        if not line.strip():
            continue
        # Вложенные строки (`  key: value`)
        if line.startswith(" ") or line.startswith("\t"):
            if current_block_key is None:
                continue
            ms = re.match(r"\s+([\wа-яА-Я_]+)\s*:\s*(.+)\s*$", line)
            if ms:
                k, v = ms.group(1), ms.group(2).strip()
                try:
                    current_block[k] = int(v)
                except ValueError:
                    current_block[k] = v
            continue
        # Закрытие вложенного блока
        if current_block_key is not None:
            fm[current_block_key] = current_block
            current_block_key = None
            current_block = {}

        m2 = re.match(r"([\wа-яА-Я_]+)\s*:\s*(.*)$", line)
        if not m2:
            continue
        k, v = m2.group(1), m2.group(2).strip()
        if not v:
            # Вложенный блок открывается
            current_block_key = k
            current_block = {}
        else:
            fm[k] = v
    if current_block_key is not None:
        fm[current_block_key] = current_block
    return fm, body


# ---------------------------------------------------------------------------
# Извлечение секций body
# ---------------------------------------------------------------------------

_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _split_body_to_sections(body: str) -> dict:
    """Разбить markdown body на dict {section_name → section_body}."""
    sections: dict = {}
    # Удаляем H1 в начале если есть
    body = re.sub(r"^#\s+.*$", "", body, count=1, flags=re.MULTILINE).strip("\n")

    matches = list(_H2_RE.finditer(body))
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[name] = body[start:end].strip()
    return sections


def _strip_bullets(text: str) -> list[str]:
    """Извлечь буллет-пункты (`- foo`) как список строк. Если буллетов нет —
    вернуть [text]."""
    lines = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            continue
        m = re.match(r"^[\-\*]\s+(.+)$", line)
        if m:
            lines.append(m.group(1).strip())
        elif lines:
            # Продолжение предыдущего bullet
            lines[-1] += " " + line.strip()
        else:
            # Параграф без буллетов
            lines.append(line.strip())
    return lines


# ---------------------------------------------------------------------------
# Per-section мапперы (profile_body → answers dict)
# ---------------------------------------------------------------------------


def _map_состав(body: str, answers: dict) -> None:
    bullets = _strip_bullets(body)
    if not bullets:
        return
    # Эвристика: bullet про языки начинается со «Языки» / «языки»
    lang_lines = [b for b in bullets if re.match(r"^[Яя]зыки", b)]
    other_lines = [b for b in bullets if not re.match(r"^[Яя]зыки", b)]
    if other_lines:
        text = "; ".join(other_lines)
        answers["состав.люди_паспорта"] = {"text": text}
        # Фолбэк для возраста: если в Составе есть «N лет / возраст N»,
        # и при этом отсутствует отдельная секция «Возраст группы» —
        # вытащим число и сохраним как ответ возраста.
        # Применим только если возраст ещё не извлечён из своей секции.
        if "возраст.значение" not in answers:
            m_age = re.search(r"(\d{1,2}(?:\s*[\-–]\s*\d{1,2})?)\s*лет", text)
            if m_age:
                answers["возраст.значение"] = {"text": m_age.group(1).strip()}
    if lang_lines:
        # Убираем префикс "Языки:"
        txt = re.sub(r"^[Яя]зыки\s*:\s*", "", lang_lines[0])
        answers["состав.языки"] = {"text": txt}


def _map_возраст(body: str, answers: dict) -> None:
    text = body.strip()
    bullets = _strip_bullets(body)
    if bullets:
        text = bullets[0]
    if text:
        answers["возраст.значение"] = {"text": text}


def _map_базовый_город(body: str, answers: dict) -> None:
    bullets = _strip_bullets(body)
    if bullets:
        answers["базовый_город.значение"] = {"text": bullets[0]}


def _detect_selected(bullets: list[str], options: list[tuple[str, str]]) -> tuple[list[str], dict]:
    """Найти, какие опции упомянуты в буллетах. Возвращает (selected, clarifications)."""
    selected = []
    clarifications: dict = {}
    joined = " | ".join(bullets).lower()
    for value, _desc in options:
        v = value.lower()
        if v in joined:
            selected.append(value)
            # Попробуем найти clarification как остаток после имени опции в bullet
            for b in bullets:
                bl = b.lower()
                pos = bl.find(v)
                if pos == -1:
                    continue
                tail = b[pos + len(value):].strip(" :;.,—-")
                if tail and len(tail) < 200:
                    clarifications[value] = tail
                break
    return selected, clarifications


def _map_стиль(body: str, answers: dict) -> None:
    bullets = _strip_bullets(body)
    if not bullets:
        return
    joined = " | ".join(bullets).lower()

    # 4.1 Планирование
    if "независимое" in joined or "самостоятельн" in joined:
        answers["стиль.планирование"] = {"selected": ["независимое"], "clarifications": {}}
    elif "организованн" in joined or "тур" in joined:
        answers["стиль.планирование"] = {"selected": ["организованное"], "clarifications": {}}
    elif "гибрид" in joined or "смешан" in joined:
        answers["стиль.планирование"] = {"selected": ["гибрид"], "clarifications": {}}

    # 4.2 Класс
    klass_bullet = next((b for b in bullets if "класс" in b.lower() and "размещ" in b.lower()), "")
    if klass_bullet:
        klass_text = klass_bullet.split(":", 1)[-1].strip() if ":" in klass_bullet else klass_bullet
        klass_low = klass_text.lower()
        # Сначала ищем явное слово выбранного класса в первых ~30 символах
        # (после двоеточия) — оно обычно сразу указывает выбор.
        head = klass_low[:30]
        if "средн" in head:
            chosen = "средний"
        elif "бюджет" in head:
            chosen = "бюджетный"
        elif "премиум" in head or "люкс" in head or "5*" in head:
            chosen = "премиум"
        elif "разн" in head:
            chosen = "разное по поездке"
        elif "хостел" in head and "не хостел" not in head:
            chosen = "бюджетный"
        else:
            chosen = "средний"
        # Уточнение — всё после первого '—' или ',' (для краткости)
        m_clar = re.match(r"^[А-Яа-я\s]+?[\(\—\-,;:]\s*(.+)$", klass_text)
        clar = {}
        if m_clar:
            clar_text = m_clar.group(1).strip(" )(.,;")
            if clar_text and chosen.lower() not in clar_text.lower()[:30]:
                clar = {chosen: clar_text}
        answers["стиль.класс"] = {"selected": [chosen], "clarifications": clar}

    # 4.3 Транспорт
    transport_bullet = next(
        (b for b in bullets if "транспорт" in b.lower()), ""
    )
    if transport_bullet:
        tr_low = transport_bullet.lower()
        sel = []
        clar_txt = ""
        if "обществен" in tr_low:
            sel.append("общественный")
        if "арен" in tr_low and "маш" in tr_low:
            sel.append("аренда машины")
        if "байк" in tr_low or "скутер" in tr_low:
            sel.append("байки/скутеры")
        if "водител" in tr_low:
            sel.append("с водителем")
        if "перелёт" in tr_low or "перелет" in tr_low:
            sel.append("внутренние перелёты")
        if not sel:
            # Нет совпадений — сложим всё в clarification к "общественный"
            clar_txt = transport_bullet.split(":", 1)[-1].strip()
        # Уточнение: всё после первого ';' или ',' если есть
        if "прокат" in tr_low and "общественный" in sel:
            clar_txt = "+ прокат по необходимости"
        if sel:
            answers["стиль.транспорт"] = {
                "selected": sel,
                "clarifications": {sel[0]: clar_txt} if clar_txt else {},
            }

    # 4.4 Ночные переезды
    night_bullet = next((b for b in bullets if "ночные" in b.lower()), "")
    if night_bullet:
        nl = night_bullet.lower()
        if "допустим" in nl or "ок" in nl or "готов" in nl:
            chosen = "ок"
        elif "нежелат" in nl or "ограничен" in nl:
            chosen = "нежелательно"
        elif "исключен" in nl or "не рассматрива" in nl or "нет" in nl:
            chosen = "исключено"
        else:
            chosen = "нежелательно"
        # Clarification после первого тире/двоеточия
        m_clar = re.search(r"[—\-:]\s*(.+)$", night_bullet)
        clar = {}
        if m_clar:
            tail = m_clar.group(1).strip(" )(.,;")
            if tail and len(tail) < 150:
                clar = {chosen: tail}
        answers["стиль.ночные"] = {"selected": [chosen], "clarifications": clar}


def _map_вождение(body: str, answers: dict) -> None:
    bullets = _strip_bullets(body)
    if not bullets:
        return
    joined = " | ".join(bullets).lower()
    sel = []
    clar: dict = {}
    if "нет возможности" in joined or "нет прав" in joined or joined.strip() == "нет":
        sel = ["нет"]
        if "нет прав" in joined:
            clar = {"нет": "нет прав"}
    else:
        if "машин" in joined:
            sel.append("машина")
        if "байк" in joined or "скутер" in joined:
            sel.append("байк/скутер")
        if not sel:
            sel = ["нет"]
    answers["вождение.готовность"] = {"selected": sel, "clarifications": clar}
    # Гео-ограничения — отдельный буллет «географические» / «не в Х»
    geo = [b for b in bullets if "географ" in b.lower() or "не в " in b.lower() or " ок" in b.lower()]
    if geo and sel != ["нет"]:
        answers["вождение.гео_ограничения"] = {"text": "; ".join(geo)}


def _map_темп(body: str, answers: dict) -> None:
    bullets = _strip_bullets(body)
    if not bullets:
        return
    txt = bullets[0].lower()
    if "активн" in txt and "умеренн" not in txt:
        chosen = "активный"
    elif "медленн" in txt:
        chosen = "медленный"
    elif "умеренн" in txt:
        chosen = "умеренный"
    elif "активн" in txt and "умеренн" in txt:
        chosen = "умеренный"
    else:
        chosen = "умеренный"
    clar = {}
    if "при необходимости" in bullets[0].lower() or len(bullets) > 1:
        clar = {chosen: bullets[0]}
    answers["темп.значение"] = {"selected": [chosen], "clarifications": clar}


def _map_частота(body: str, answers: dict) -> None:
    bullets = _strip_bullets(body)
    if not bullets:
        return
    txt = bullets[0].lower()
    # Числа из строки
    nums = [int(x) for x in re.findall(r"\d+", txt)]
    if nums:
        lo = min(nums)
        hi = max(nums)
        if hi <= 2:
            chosen = "1–2 ночи"
        elif lo >= 5:
            chosen = "5+ ночей"
        else:
            chosen = "3–5 ночей"
    else:
        chosen = "нет жёсткого мнения"
    clar = {chosen: bullets[0]}
    answers["частота.значение"] = {"selected": [chosen], "clarifications": clar}


def _map_интересы(body: str, answers: dict) -> None:
    bullets = _strip_bullets(body)
    if not bullets:
        return
    # Если буллет состоит из «название — пояснение», склеиваем через `; `
    answers["интересы.значение"] = {"text": "; ".join(bullets)}


def _map_форма(body: str, answers: dict) -> None:
    bullets = _strip_bullets(body)
    if not bullets:
        return
    # 9.1 уровень: первая строка
    first = bullets[0].lower()
    if "хорош" in first:
        level = "хорошая"
    elif "ограничен" in first or "слаб" in first:
        level = "ограниченная"
    else:
        level = "средняя"
    answers["форма.уровень"] = {"selected": [level], "clarifications": {}}
    # 9.2 треки/высокогорье — буллеты со словами «трек», «лестниц», «высокогор», «шаг»
    track_bullets = [
        b for b in bullets[1:]
        if any(kw in b.lower() for kw in ("трек", "лестниц", "высокогор", "шаг", "подъём"))
    ]
    if track_bullets:
        answers["форма.треки"] = {"text": "; ".join(track_bullets)}
    # 9.3 ограничения — буллеты с явными indicator'ами
    limit_bullets = [
        b for b in bullets[1:]
        if any(kw in b.lower() for kw in ("аллерг", "артрит", "болезн", "ограничен", "противопоказ"))
    ]
    if limit_bullets:
        answers["форма.ограничения"] = {"text": "; ".join(limit_bullets)}


# Маркер второго тира исключений («не как основа, но иногда можно»).
_SOFT_TIER_RE = re.compile(
    r"^\s*\**\s*не как основа", re.IGNORECASE | re.MULTILINE)
# Строки-ярлыки тиров и блок-цитаты — не данные, в буллеты не попадают.
_TIER_LABEL_RE = re.compile(
    r"^\s*(\**\s*(никогда|не как основа)|>)", re.IGNORECASE)


def _split_exclusion_tiers(body: str) -> tuple[str, str]:
    """Разделить секцию исключений на жёсткий и мягкий тир.

    Профили без второго тира (все, написанные до 09.2026) возвращают
    пустой мягкий тир — поведение не меняется.
    """
    m = _SOFT_TIER_RE.search(body)
    if not m:
        return body, ""
    return body[:m.start()], body[m.start():]


def _clean_tier(text: str) -> list[str]:
    lines = [ln for ln in text.splitlines()
             if not _TIER_LABEL_RE.match(ln)]
    # Ярлык тира может занимать две строки («…допустимо** (по запросу /
    # или как замена сорвавшегося дня):»). Хвост ярлыка — это всё до
    # первого буллета: отбрасываем, иначе он станет первым «исключением».
    first_bullet = next((i for i, ln in enumerate(lines)
                         if re.match(r"^[\-\*]\s+", ln)), None)
    if first_bullet is not None:
        lines = lines[first_bullet:]
    return _strip_bullets("\n".join(lines))


def _map_исключения(body: str, answers: dict) -> None:
    hard_body, soft_body = _split_exclusion_tiers(body)
    hard = _clean_tier(hard_body)
    if hard:
        answers["исключения.значение"] = {"text": "; ".join(hard)}
    soft = _clean_tier(soft_body)
    if soft:
        answers["исключения.мягкие"] = {"text": "; ".join(soft)}


# Ключевые слова для разнесения буллетов «Переносимости» по трём вопросам.
_ПЕРЕНОСИМОСТЬ_KEYS = (
    ("переносимость.климат",
     ("климат", "°c", "жар", "влажн", "холод", "температур", "духот")),
    ("переносимость.экспозиция",
     ("экспозиц", "скольж", "тропа", "троп", "брод", "обрыв", "крут", "падени")),
    ("переносимость.транспорт",
     ("укачив", "серпантин", "автобус", "мото", "байк", "паром", "морск",
      "спальник")),
)


def _map_переносимость(body: str, answers: dict) -> None:
    bullets = [b for b in _strip_bullets(body) if not b.startswith(">")]
    if not bullets:
        return
    buckets: dict[str, list[str]] = {}
    for b in bullets:
        low = b.lower()
        for qid, keys in _ПЕРЕНОСИМОСТЬ_KEYS:
            if any(k in low for k in keys):
                buckets.setdefault(qid, []).append(b)
                break
    for qid, items in buckets.items():
        answers[qid] = {"text": "; ".join(items)}


def _map_гастро(body: str, answers: dict) -> None:
    bullets = _strip_bullets(body)
    if not bullets:
        return
    joined = " | ".join(bullets).lower()
    # 11.1 стиль
    sel = []
    clar: dict = {}
    if "улич" in joined:
        sel.append("уличная еда")
    # «гастро-рестораны» — только при явных маркерах высокой кухни
    high_cuisine_markers = ("гастро-рестораны", "гастро-кухн", "fine dining",
                            "мишлен", "michelin", "авторск")
    high_cuisine = any(m in joined for m in high_cuisine_markers)
    # «обычные рестораны» — упоминание ресторанов или «простая/обычная еда»
    has_ordinary = (
        ("ресторан" in joined and not high_cuisine)
        or "прост" in joined
        or "обычн" in joined
    )
    if has_ordinary:
        sel.append("обычные рестораны")
        # clarification — первый bullet про еду
        food_b = next(
            (b for b in bullets if any(kw in b.lower() for kw in
                                        ("прост", "обычн", "ресторан"))),
            "",
        )
        if food_b:
            # Снимем слова «обычные рестораны» если они есть
            clar = {"обычные рестораны": food_b}
    if high_cuisine:
        sel.append("гастро-рестораны")
    if "в отеле" in joined or "только в отеле" in joined:
        sel.append("в основном в отеле")
    if sel:
        answers["гастро.стиль"] = {"selected": sel, "clarifications": clar}

    # 11.2 кофе/алкоголь
    drink_bullets = [
        b for b in bullets
        if any(kw in b.lower() for kw in ("кофе", "алкогол", "вино", "пиво"))
    ]
    fish_bullets = [b for b in bullets if "рыб" in b.lower()]
    if drink_bullets or fish_bullets:
        all_drink = drink_bullets + fish_bullets
        answers["гастро.напитки"] = {"text": "; ".join(all_drink)}

    # 11.3 ограничения
    limit_bullets = [
        b for b in bullets
        if any(kw in b.lower() for kw in ("не ест", "аллерг", "не пьёт", "вегетариан",
                                           "лактоз", "глютен"))
    ]
    if limit_bullets:
        # Сохраним без префикса «НЕ ест:»
        txt = "; ".join(
            re.sub(r"^НЕ\s+ест\s*:\s*", "не ест: ", b, flags=re.IGNORECASE) for b in limit_bullets
        )
        answers["гастро.ограничения"] = {"text": txt}


def _map_фото(body: str, answers: dict) -> None:
    bullets = _strip_bullets(body)
    if not bullets:
        return
    joined = " | ".join(bullets).lower()
    if "профес" in joined and "не для" not in joined:
        level = "профессионально"
    elif "телефон" in joined and "не делает" not in joined and "не для себя" not in joined:
        level = "на телефон"
    elif "не делает" in joined or "не интересно" in joined:
        level = "не делает"
    else:
        level = "для себя"
    clar = {}
    self_bullet = next((b for b in bullets if "для себя" in b.lower()), "")
    if self_bullet and level == "для себя":
        tail = self_bullet.split("для себя", 1)[-1]
        tail = tail.strip().strip(" )(,;:.")
        # Снимем висящие скобки и слова-связки
        tail = re.sub(r"^[\(\),;:\s—\-]+", "", tail)
        tail = re.sub(r"[\(\)]+$", "", tail).strip()
        if tail:
            clar = {"для себя": tail[:120]}
    answers["фото.уровень"] = {"selected": [level], "clarifications": clar}
    # Жанры/оборудование — все остальные буллеты
    other = [
        b for b in bullets
        if any(kw in b.lower() for kw in ("жанр", "оборудован", "обработ", "fujifilm",
                                           "sony", "canon", "nikon", "camera", "пейзаж"))
    ]
    if other:
        answers["фото.жанры"] = {"text": "; ".join(other)}


def _map_опыт(body: str, answers: dict) -> None:
    if body.strip():
        # Нормализуем `**Европа:** …` → `Европа: …`
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", body).strip()
        # Снимем bullet-маркеры `- ` в началах строк
        text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
        # Свернём пробелы и переносы
        text = re.sub(r"\s+", " ", text).strip()
        answers["опыт.значение"] = {"text": text}


def _map_бюджет(body: str, answers: dict) -> None:
    bullets = _strip_bullets(body)
    if not bullets:
        return
    # 14.1 ориентир — первая строка с цифрами/валютой
    orient = next(
        (b for b in bullets if re.search(r"[\d₽$€]|тыс\.?\s*₽", b)), bullets[0]
    )
    answers["бюджет.ориентир"] = {"text": orient}
    # 14.2 что включает — буллет с «включает», «включ.», «всё»
    incl = next(
        (b for b in bullets[1:]
         if any(kw in b.lower() for kw in ("включ", "всё", "все ", "вкл "))),
        "",
    )
    if incl:
        answers["бюджет.включает"] = {"text": incl}
    # 14.3 готовность переплачивать — буллет про «премиум», «комфорт», «переплат»
    extra = next(
        (b for b in bullets
         if any(kw in b.lower() for kw in ("переплат", "выше лимит", "готов плат"))),
        "",
    )
    if extra:
        answers["бюджет.переплата"] = {"text": extra}


# Отрицание карты в том же буллете: «не оформлена», «не работает»,
# «не принимается», «не брали», «нет карты».
_NEGATED_CARD_RE = re.compile(
    r"\bне\s+(оформл|работа|принима|бра[лн]|получ|дела)|\bнет\s+карт")
# Границы клауз внутри буллета: `;`, тире-дефис, em/en-dash, точка, `|`.
_CLAUSE_SPLIT_RE = re.compile(r"[;.|]|\s[—–-]\s")


def _map_платежи(body: str, answers: dict) -> None:
    bullets = _strip_bullets(body)
    if not bullets:
        return
    joined = " | ".join(bullets).lower()

    # 15.1 карты. Упоминание карты ≠ наличие карты: «UnionPay не оформлена»,
    # «Visa за рубежом не работает» — это отсутствие канала, а не канал.
    # Поэтому ищем по буллетам и отбрасываем те, где карта отрицается.
    def _has_card(*keys: str) -> bool:
        # Отрицание проверяем в пределах клаузы, а не всего буллета: строка
        # «Мир: работает в РФ и Азии — в Европе не принимается» описывает
        # имеющуюся карту, а не отсутствующую.
        for b in bullets:
            for clause in _CLAUSE_SPLIT_RE.split(b.lower()):
                if not any(k in clause for k in keys):
                    continue
                if _NEGATED_CARD_RE.search(clause):
                    continue
                return True
        return False

    sel = []
    clar = {}
    if _has_card("visa"):
        sel.append("Visa")
    if _has_card("mastercard", "master card", "мастер"):
        sel.append("Mastercard")
    if _has_card("unionpay", "union pay"):
        sel.append("UnionPay")
    if _has_card("mir", "мир ", "карта мир"):
        sel.append("Mir")
    if "нет работающих" in joined or "только наличн" in joined:
        sel = ["нет рабочих карт"]
    if not sel and ("международные карты" in joined or "работающие" in joined):
        # Профиль алексея — упомянуто абстрактно. По дефолту проставим Visa+MC.
        sel = ["Visa", "Mastercard"]
        clar = {"Visa": "уточни конкретный банк, если важно",
                "Mastercard": "уточни конкретный банк, если важно"}
    if sel:
        answers["платежи.карты"] = {"selected": sel, "clarifications": clar}

    # 15.2 локальные платежи
    if "при необходимост" in joined:
        local = "при необходимости"
    elif "готов" in joined or "да, готов" in joined or " да" in joined:
        local = "да"
    elif "нет" in joined and "наличн" in joined:
        local = "нет"
    else:
        local = "при необходимости"
    answers["платежи.локальные"] = {"selected": [local], "clarifications": {}}


def _map_дополнительно(body: str, answers: dict) -> None:
    if body.strip():
        answers["дополнительно.значение"] = {"text": body.strip()}


# --- Legacy-section aliases (для профилей с нестандартными именами H2) ---


def _map_размещение(body: str, answers: dict) -> None:
    """Legacy-формат — отдельная секция «Размещение» вместо подсекции
    в «Стиль путешествий». Извлекаем класс."""
    bl = body.lower()
    if "хостел" in bl and ("нежелат" in bl or "рассмотрит" in bl):
        chosen = "средний"  # «не хостел» = средний минимум
        clar = "не хостелы; своя ванная — приоритет"
    elif "премиум" in bl or "5*" in bl:
        chosen = "премиум"
        clar = ""
    elif "бюджет" in bl or "хостел" in bl:
        chosen = "бюджетный"
        clar = ""
    else:
        chosen = "средний"
        clar = ""
    # Не перетираем уже извлечённое значение
    if "стиль.класс" not in answers:
        answers["стиль.класс"] = {
            "selected": [chosen],
            "clarifications": {chosen: clar} if clar else {},
        }


def _map_языки_коммуникация(body: str, answers: dict) -> None:
    """Legacy-формат — «Языки и коммуникация» отдельной секцией."""
    bullets = _strip_bullets(body)
    # Берём только language-related bullets
    langs = []
    for b in bullets:
        bl = b.lower()
        if any(kw in bl for kw in ("английск", "русск", "испанск", "французск",
                                     "немецк", "китайск", "японск", "корейск",
                                     "итальянск", "португальск", "translate")):
            langs.append(b)
    if langs:
        # Снимем "Английский: базовый" → нормальный список
        text = "; ".join(langs)
        if "состав.языки" not in answers:
            answers["состав.языки"] = {"text": text}
        else:
            # Добавим к существующему
            old = answers["состав.языки"].get("text", "")
            answers["состав.языки"] = {"text": f"{old}; {text}" if old else text}


# Алиасы секций для legacy-профилей
_SECTION_ALIASES = {
    "Возможность вождения": _map_вождение,     # canonical name
    "Вождение":             _map_вождение,     # legacy (мария)
    "Размещение":           _map_размещение,   # legacy (мария) — extra section
    "Языки и коммуникация": _map_языки_коммуникация,  # legacy (мария)
}


# ---------------------------------------------------------------------------
# Реестр: profile H2 → mapper function
# ---------------------------------------------------------------------------

_MAPPERS = {
    "Состав группы": _map_состав,
    "Возраст группы": _map_возраст,
    "Базовый город": _map_базовый_город,
    "Стиль путешествий": _map_стиль,
    "Темп": _map_темп,
    "Частота смены локаций": _map_частота,
    "Ядро интересов": _map_интересы,
    "Физическая форма": _map_форма,
    "Переносимость": _map_переносимость,
    "Явные исключения": _map_исключения,
    "Гастрономия": _map_гастро,
    "Фотография": _map_фото,
    "Опыт поездок": _map_опыт,
    "Бюджет": _map_бюджет,
    "Платёжная инфраструктура": _map_платежи,
    "Дополнительно": _map_дополнительно,
    # canonical + legacy aliases ниже
    **_SECTION_ALIASES,
}


def parse_profile_md(path: str | Path) -> ParsedProfile:
    """Распарсить profile.md → ParsedProfile."""
    path = Path(path).expanduser()
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _parse_yaml_frontmatter(text)
    sections_raw = _split_body_to_sections(body)

    answers: dict = {}
    # Архетип идёт из YAML
    archetype = frontmatter.get("группа_архетип")
    if archetype:
        # Backward-compat: deprecated alias
        from .anketa_spec import ARCHETYPE_LEGACY_ALIASES, ARCHETYPE_VALUES
        if archetype in ARCHETYPE_LEGACY_ALIASES:
            archetype = ARCHETYPE_LEGACY_ALIASES[archetype]
        if archetype in ARCHETYPE_VALUES:
            answers["архетип.значение"] = {"selected": [archetype], "clarifications": {}}

    for sec_name, sec_body in sections_raw.items():
        mapper = _MAPPERS.get(sec_name)
        if mapper is None:
            continue
        try:
            mapper(sec_body, answers)
        except Exception as e:  # pragma: no cover
            # Не падать на одной плохой секции — продолжать остальные.
            import sys
            print(f"warning: парсер споткнулся на секции «{sec_name}»: {e}",
                  file=sys.stderr)

    return ParsedProfile(
        frontmatter=frontmatter,
        answers=answers,
        sections_raw=sections_raw,
    )
