#!/usr/bin/env python3
"""
merge_dr_additions.py — склеить DR-файл Stage 1 с одним/несколькими additions.md
и перегенерировать детерминируемые блоки META-DIAGNOSTICS.

Detrministic recompute:
  - reports_count, warning о sample skew
  - распределение по языкам источника (поле 2)
  - распределение по стилям путешествия (поле 9)
  - распределение по фокусу автора (поле 13)
  - распределение по сезону (regex по полям 5-6)
  - warnings (50% стиля, 50% фокуса, 10% ES, 4 на регион)
  - YAML frontmatter: reports_count, updated; добавляет sample_curation_note

НЕ recompute (требует NER):
  - распределение по регионам — оставляет оригинальный текст + TODO

Usage:
    python3 merge_dr_additions.py main.md additions.md > merged.md
    python3 merge_dr_additions.py main.md add1.md add2.md -o merged.md
    python3 merge_dr_additions.py main.md additions.md --inplace
"""
import sys, re, argparse, datetime, html, os
from collections import Counter
from pathlib import Path

# Общие модули — канон в _shared-references/; в упакованном .skill — в своей scripts/ (pack.sh кладёт по импорту).
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import hub_settings  # noqa: E402

# ---------- Парсинг ----------

YAML_RE = re.compile(r'\A---\n(.*?)\n---\n', re.DOTALL)
CARD_HEADER_RE = re.compile(r'^#{1,2}\s+КАРТОЧКА\s+(\d+)\s*(?:\(([^)]+)\))?\s*$', re.MULTILINE)
META_RE = re.compile(r'^#\s+META-DIAGNOSTICS\b', re.MULTILINE)
FIELD_RE = re.compile(r'^\s*(\d+)\.\s+\*\*([^:*]+):\*\*\s*(.*?)(?=\n\s*\d+\.\s+\*\*|\n---|\n#{1,2}\s|\Z)',
                       re.DOTALL | re.MULTILINE)

def parse_yaml_frontmatter(text):
    m = YAML_RE.match(text)
    if not m:
        return None, text
    return m.group(1), text[m.end():]

def parse_cards(text):
    """Возвращает список (number, marker, raw_block_text, fields_dict)."""
    cards = []
    matches = list(CARD_HEADER_RE.finditer(text))
    for i, m in enumerate(matches):
        start = m.end()
        # конец карточки — следующий КАРТОЧКА, # META-DIAGNOSTICS, или конец текста
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        # обрезать на META-DIAGNOSTICS, если попало
        meta = META_RE.search(text, start, end)
        if meta:
            end = meta.start()
        block = text[start:end]
        # обрезать trailing разделитель ---
        block_clean = re.sub(r'\n+---\s*\n+\s*$', '\n', block).rstrip()
        fields = {}
        for fm in FIELD_RE.finditer(block_clean):
            num = int(fm.group(1))
            name = fm.group(2).strip()
            value = fm.group(3).strip()
            fields[num] = {"name": name, "value": value}
        cards.append({
            "number": int(m.group(1)),
            "marker": m.group(2),
            "raw": block_clean,
            "fields": fields,
        })
    return cards

# ---------- Классификация ----------

LANG_PATTERNS = [
    ("ru", r'\b(ru|русск|Russian|Россия|forum\.awd\.ru|tourister)\b'),
    ("en", r'\b(en|English|англ)\b'),
    ("es", r'\b(es|Spanish|испан|viajeros\.com|taringa)\b'),
    ("vi", r'\b(vi|Vietnamese|вьетнам)\b'),
    ("ja", r'\b(ja|Japanese|япон|jalan\.net)\b'),
    ("zh", r'\b(zh|Chinese|кит|mafengwo|qyer)\b'),
    ("ko", r'\b(ko|Korean|коре|naver)\b'),
]

def detect_lang(field2_value):
    """Поле 2: 'Tourister.ru, ru' → 'ru'. forum.awd.ru, ru → 'ru'. etc."""
    v = field2_value or ""
    # сначала ищем явный suffix ", xx"
    m = re.search(r',\s*(ru|en|es|vi|ja|zh|ko|de|fr|pt|it)\b', v, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    for code, pat in LANG_PATTERNS:
        if re.search(pat, v, re.IGNORECASE):
            return code
    return "?"

STYLE_KEYWORDS = [
    ("mid-range independent", r'mid[-\s]?range|midrange|средн|backpacker|бюджетн|independent'),
    ("photography-focused",   r'photo|фотограф|съёмк|съемк'),
    ("hardcore adventure",    r'hardcore|adventure|приключен|хайк|hiking|trek'),
    ("organized tour",        r'organized|tour|групп|организован'),
    ("cultural deep-dive",    r'cultural|культур|критич'),
    ("food-focused",          r'food|кулинар|гастроном'),
    ("литературный",          r'литератур|atmospheric|atmosph'),
]

def detect_style(field9_value):
    v = (field9_value or "").lower()
    matched = []
    for label, pat in STYLE_KEYWORDS:
        if re.search(pat, v, re.IGNORECASE):
            matched.append(label)
    # вернуть первый матч (приоритетный список)
    return matched[0] if matched else "?"

FOCUS_KEYWORDS = [
    ("фотография",      r'фотограф|photo'),
    ("приключения",     r'приключен|adventure|хайк|hik'),
    ("природа",         r'природ|nature'),
    ("культура",        r'культур|cultural|атмосфер'),
    ("food-focused",    r'food|кулинар'),
    ("mix",             r'mix|микс'),
]

def detect_focus(field13_value):
    v = (field13_value or "").lower()
    for label, pat in FOCUS_KEYWORDS:
        if re.search(pat, v):
            return label
    return "?"

SEASON_PATTERNS = [
    ("март-апрель",      r'март|апрел'),
    ("январь-февраль",   r'январ|феврал|январ.{0,5}феврал'),
    ("декабрь",          r'декабр'),
    ("ноябрь",           r'ноябр'),
    ("октябрь",          r'октябр'),
    ("сентябрь",         r'сентябр'),
    ("зима",             r'зим'),
    ("осень",            r'осен'),
]

def detect_season(field5, field6):
    v = ((field5 or "") + " " + (field6 or "")).lower()
    for label, pat in SEASON_PATTERNS:
        if re.search(pat, v):
            return label
    return "не уточнено"

# ---------- Recompute META-DIAGNOSTICS ----------

def pct(part, total):
    return f"{round(100*part/total)}%" if total else "0%"

def recompute_meta(cards, original_meta_text=None, regions_warning_hint=None):
    n = len(cards)
    lang_c, style_c, focus_c, season_c = Counter(), Counter(), Counter(), Counter()

    for c in cards:
        f = c["fields"]
        lang_c[detect_lang(f.get(2, {}).get("value", ""))] += 1
        style_c[detect_style(f.get(9, {}).get("value", ""))] += 1
        focus_c[detect_focus(f.get(13, {}).get("value", ""))] += 1
        season_c[detect_season(
            f.get(5, {}).get("value", ""),
            f.get(6, {}).get("value", ""))] += 1

    # Какие карточки добавлены руками (marker)
    added_marker = [c["number"] for c in cards if (c["marker"] or "").strip()]
    added_marker_str = ", ".join(f"№{n}" for n in added_marker) if added_marker else ""

    lines = []
    lines.append("# META-DIAGNOSTICS")
    lines.append("")
    lines.append("## Количество отчётов")
    lines.append(f"- **Уникальных отчётов:** {n}")
    if added_marker:
        lines.append(f"- Из них добавлены вручную: {added_marker_str}")
    lines.append("")

    # Регионы — оставляем placeholder
    lines.append("## Распределение по регионам")
    lines.append("⚠ **TODO:** автоматический пересчёт регионального распределения недоступен "
                 "(требует ручной NER по полям POI / Темп / Месяц-длительность). "
                 "Сверьте список карточек, относящихся к каждому региону, вручную.")
    if regions_warning_hint:
        lines.append("")
        lines.append(regions_warning_hint)
    lines.append("")

    # Стили
    lines.append(f"## Распределение по стилям путешествия (поле 9), % от {n}")
    for label, cnt in sorted(style_c.items(), key=lambda x: -x[1]):
        lines.append(f"- {label}: {pct(cnt, n)} ({cnt})")
    lines.append("")

    # Сезон
    lines.append(f"## Распределение по сезону поездки (поля 5–6), % от {n}")
    for label, cnt in sorted(season_c.items(), key=lambda x: -x[1]):
        lines.append(f"- {label}: {pct(cnt, n)} ({cnt})")
    lines.append("")

    # Фокус
    lines.append(f"## Распределение по фокусу автора (поле 13), % от {n}")
    for label, cnt in sorted(focus_c.items(), key=lambda x: -x[1]):
        lines.append(f"- {label}: {pct(cnt, n)} ({cnt})")
    lines.append("")

    # Языки
    lines.append("## Распределение по языку источника")
    for label, cnt in sorted(lang_c.items(), key=lambda x: -x[1]):
        lines.append(f"- **{label.upper()}:** {cnt} отчётов — {pct(cnt, n)}")
    lines.append("")

    # Warnings — детерминируемые
    lines.append("## Warnings о смещении выборки (детерминируемые)")
    max_style_label, max_style_cnt = max(style_c.items(), key=lambda x: x[1]) if style_c else ("?", 0)
    max_focus_label, max_focus_cnt = max(focus_c.items(), key=lambda x: x[1]) if focus_c else ("?", 0)
    es_share = lang_c.get("es", 0) / n if n else 0
    lines.append(f"- {'✓' if max_style_cnt/n < 0.5 else '⚠'} Доля одного стиля = {pct(max_style_cnt, n)} ({max_style_label}); порог 50%")
    lines.append(f"- {'✓' if max_focus_cnt/n < 0.5 else '⚠'} Доля одного фокуса = {pct(max_focus_cnt, n)} ({max_focus_label}); порог 50%")
    lines.append(f"- {'✓' if es_share >= 0.10 else '⚠'} Испаноязычная доля = {pct(lang_c.get('es', 0), n)}; порог ≥10%")
    lines.append("")
    lines.append("⚠ **TODO:** региональный порог «≥4 на регион» — пересчитайте вручную после ревизии регионов.")
    lines.append("")

    # Если есть оригинальный META — приклеить статичные блоки (источники / технические / отсутствует)
    if original_meta_text:
        static_keep = []
        for sect_name in ("Источники, которые пробовали использовать, но не смогли",
                          "Дополнительные технические уточнения",
                          "Что фотографически отсутствует в выборке"):
            m = re.search(rf'^##\s+{re.escape(sect_name)}.*?(?=^##\s|\Z)',
                          original_meta_text, re.MULTILINE | re.DOTALL)
            if m:
                static_keep.append(m.group(0).rstrip())
        if static_keep:
            lines.append("---")
            lines.append("")
            lines.append("# Унаследованные блоки из исходного META-DIAGNOSTICS")
            lines.append("(сохранены без изменений — обновите вручную, если добавленные карточки их меняют)")
            lines.append("")
            for blk in static_keep:
                lines.append(blk)
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"

# ---------- YAML frontmatter ----------

def build_yaml(orig_yaml_str, total_count, added_marker_numbers, warnings_extra=None):
    """Простая обновлялка YAML — без зависимости от PyYAML."""
    today = datetime.date.today().isoformat()
    lines = []
    seen = set()
    src_lines = (orig_yaml_str or "").splitlines()
    for ln in src_lines:
        m = re.match(r'^(\w[\w_]*)\s*:', ln)
        if not m:
            lines.append(ln)
            continue
        key = m.group(1)
        seen.add(key)
        if key == "reports_count":
            lines.append(f"reports_count: {total_count}")
        elif key == "updated":
            lines.append(f"updated: {today}")
        else:
            lines.append(ln)
    if "reports_count" not in seen:
        lines.append(f"reports_count: {total_count}")
    if "updated" not in seen:
        lines.append(f"updated: {today}")
    if added_marker_numbers and "meta_diagnostics_warnings" not in seen:
        lines.append("meta_diagnostics_warnings:")
        note = ", ".join(f"№{n}" for n in added_marker_numbers)
        lines.append(f'  - "sample_curation_note: карточки {note} добавлены вручную через merge_dr_additions.py"')
    return "---\n" + "\n".join(lines) + "\n---\n"

# ---------- Сборка ----------

def build_merged(main_path, additions_paths):
    main_text = Path(main_path).read_text(encoding="utf-8")
    yaml_str, body = parse_yaml_frontmatter(main_text)

    # Отрезаем оригинальный META-DIAGNOSTICS из body
    meta_m = META_RE.search(body)
    if meta_m:
        body_cards_text = body[:meta_m.start()]
        orig_meta_text = body[meta_m.start():]
    else:
        body_cards_text = body
        orig_meta_text = None

    main_cards = parse_cards(body_cards_text)
    if not main_cards:
        raise SystemExit("ERROR: в основном файле не найдено карточек (## КАРТОЧКА N)")

    # Шапка до первой карточки
    first_card_pos = CARD_HEADER_RE.search(body_cards_text).start()
    preamble = body_cards_text[:first_card_pos].rstrip() + "\n\n"

    next_num = max(c["number"] for c in main_cards) + 1

    all_cards = list(main_cards)
    added_marker_numbers = []
    for ap in additions_paths:
        atext = Path(ap).read_text(encoding="utf-8")
        # игнорируем YAML и META-DIAGNOSTICS в additions
        _, abody = parse_yaml_frontmatter(atext)
        am = META_RE.search(abody)
        if am:
            abody = abody[:am.start()]
        acards = parse_cards(abody)
        for c in acards:
            c["number"] = next_num
            existing = (c["marker"] or "").strip()
            # Всегда явно метить additions как user_added, даже если в исходном
            # файле уже был свой marker (например, имя автора в скобках). Без
            # этого downstream-стадии не отличают B1/B2-карточки от DR.
            if not existing:
                c["marker"] = "user_added"
            elif "user_added" not in existing.lower():
                c["marker"] = f"user_added, {existing}"
            # иначе оставить как есть (user_added уже там)
            added_marker_numbers.append(next_num)
            all_cards.append(c)
            next_num += 1

    # Собираем body
    out = []
    if yaml_str is not None or added_marker_numbers:
        out.append(build_yaml(yaml_str, len(all_cards), added_marker_numbers))
    out.append(preamble.rstrip() + "\n\n")
    for c in all_cards:
        marker = f" ({c['marker']})" if c["marker"] else ""
        out.append(f"## КАРТОЧКА {c['number']}{marker}\n\n{c['raw'].strip()}\n\n---\n\n")
    # META
    out.append(recompute_meta(all_cards, orig_meta_text))
    return "".join(out)

# ---------- CLI ----------

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("main")
    p.add_argument("additions", nargs="+")
    p.add_argument("-o", "--output", help="файл вывода (по умолчанию stdout)")
    p.add_argument("--inplace", action="store_true",
                   help="переписать main файл (создаст .bak)")
    args = p.parse_args()

    merged = build_merged(args.main, args.additions)

    if args.inplace:
        hub_settings.require_ai(args.main, "merge_dr_additions.py --inplace", "слияние карточек DR", zones=("travel-planner",))   # вход — вывод модели
        bak = Path(args.main + ".bak")
        bak.write_text(Path(args.main).read_text(encoding="utf-8"), encoding="utf-8")
        Path(args.main).write_text(merged, encoding="utf-8")
        print(f"OK: переписан {args.main}, бэкап в {bak}", file=sys.stderr)
    elif args.output:
        Path(args.output).write_text(merged, encoding="utf-8")
        print(f"OK: записано в {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(merged)
