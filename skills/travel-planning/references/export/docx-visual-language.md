# DOCX визуальный язык (editable-стадии)

Канонический визуальный язык DOCX-экспортов. Аналог
`pdf-visual-language.md`, но для **editable** документов, где пользователь
заполняет поля (теги, комментарии). Сейчас единственный потребитель —
Stage 3 (POI-агрегация); файл готов к переиспользованию будущими
DOCX-стадиями.

**Все примитивы — в `scripts/export/docx_lib.py`.** Stage-модуль вызывает
готовые `add_*`-функции, не работает с python-docx XML напрямую.

---

## 1. Когда DOCX, а не PDF

DOCX выбирается, когда стадия **operative** — пользователь не читает, а
заполняет:
- Stage 3: теги регионов + комментарии POI.

PDF — для read-only витрин (Stage 0/1/4/5). Если стадия только
презентационная — это PDF, не DOCX.

DOCX-стадия почти всегда имеет и PDF-форму (read-only после заполнения).
Контент идентичен (см. §7 «Паритет с PDF»), различается только
интерактивность.

---

## 2. Палитра и шрифты

Цвета берутся из `style.py` (общие с PDF) — `CATEGORY_COLORS`,
`SIMILARITY_COLORS`, `TONE_COLORS`, `FLAG_COLORS`, плюс локальные
константы `docx_lib`: `PRIMARY` (`1a3a5c`), `TEXT` (`1f2937`),
`TEXT_MUTED`, `TEXT_DIM`, `WARNING_LABEL` (`7a5c00`), `ZEBRA` (`f4f6f9`).

**Цвета — 6-hex БЕЗ `#`** (`RGBColor.from_string` это требует). В отличие
от reportlab (`HexColor("#...")`), в DOCX префикс не ставится.

Шрифты — дефолтные Word/Calibri. CJK и кириллица работают нативно (в
отличие от PDF, где нужна регистрация TTF). Эмодзи допустимы (Word
рендерит), но в Stage 3 не используются.

---

## 3. Low-level примитивы

| Функция | Назначение |
|---|---|
| `set_cell_bg(cell, hex)` | Заливка ячейки фоном |
| `set_cell_border(cell, *, left_size, …)` | Границы ячейки (size в 1/8 pt: 8=1pt, 32=4pt) |
| `add_run(p, text, *, bold, italic, color, size_pt, font)` | Run с форматированием |
| `set_para_spacing(p, before, after)` | Интервалы до/после параграфа (pt) |
| `add_bookmark(p, name, id?)` | Внутренний якорь (для internal-link) |
| `add_internal_link(p, anchor, text, …)` | Ссылка на bookmark (`w:anchor`) |
| `add_external_hyperlink(p, url, text, …)` | Внешняя http-ссылка |
| `set_paragraph_keep(p, *, with_next, lines_together)` | `keepNext`/`keepLines` — anti-page-break |
| `set_table_cant_split(tbl)` | `cantSplit` на всех строках таблицы |
| `add_horizontal_rule_in_cell(cell, color)` | Тонкая разделительная линия |
| `lighten_hex(hex, factor)` | Осветление цвета (0=без изм, 1=белый) |

---

## 4. Anketa-style поля заполнения

**Принцип:** НЕ использовать Word Content Controls (SDT) с серым
placeholder'ом — пользователю приходится стирать текст перед вводом.
Вместо них — подход `anketa_builder.py`:

- **Выбор из вариантов** → `add_choice_question(doc, label, options,
  selected, multi, hint)`. Каждая опция — строка `[ ] значение` (или
  `[x] значение` если pre-selected). Пользователь меняет `[ ]`→`[x]`
  вручную.
- **Свободный текст** → `add_text_field(doc, label, prefill)` или
  `add_text_field_in_cell(cell, …)`. Выводит `label: <prefill или пусто>`,
  курсор сразу после `:`. Ничего стирать не надо.

Stage 3 использует:
- тег региона → `add_choice_question` с 3 опциями (обязательно / можно /
  не интересно);
- комментарий POI → `add_text_field_in_cell(label="Комментарий")`.

**Pre-select из round-trip:** если поле уже заполнено каноническим
значением (DOCX → md → повторный DOCX), соответствующий чекбокс приходит
pre-checked. Скрипт сравнивает тег ТОЧНО с 3 канонами (`_normalize_tag`
не угадывает синонимы) — приведение вольных формулировок к канону делает
polish (T3b), не код.

---

## 5. Высокоуровневые блоки Stage 3

| Функция | Что рисует |
|---|---|
| `add_key_params_table(doc, rows)` | Cover-таблица параметров (zebra) |
| `add_category_distribution(doc, distribution)` | 6 цветных плашек категорий |
| `add_coverage_table(doc, rows, totals)` | Регион × категория; первая колонка — internal-link на region anchor |
| `add_region_header(doc, name, poi_count)` | Синяя плашка региона + bookmark |
| `add_cluster_header(doc, name, member_count, note)` | Заголовок кластера (синие границы) + bookmark |
| `add_poi_card(doc, *, num, name_ru, name_local, category, counts_line, excerpts, characteristics, flags, user_comment, search_query)` | POI-карточка |

**POI-карточка** (`add_poi_card`) — структура:
```
┌─[accent по категории]──────────────────────────┐
│ #N Название (link→Google Images)  [BADGE]      │
│ HIGH 2 (рек 2 · neg 0) · OUTLIER 1 · …          │
│ ✓ Автор («Название отчёта»→link) · 2024 · HIGH: «цитата»│
│ ✗ ...                                           │
│ Характеристики: ...                             │
│ [combined: X→link] [cluster: Y→link]            │
│ ─────────────                                   │
│ Комментарий: ← курсор сразу здесь               │
└─────────────────────────────────────────────────┘
```
- accent-полоса слева 4pt по `CATEGORY_COLORS[category]`, фон —
  `lighten_hex(accent, 0.93)`;
- badge категории — nested 1×2 table (title cell + badge cell);
- выдержки с тоном ✓/✗/• по `TONE_COLORS`; имя автора plain bold,
  «Название отчёта» — кликабельная ссылка на URL отчёта;
- флаги-chip'ы: `combined_with` / `cluster` кликабельны (internal-link на
  целевую карточку/кластер), `iconic`/`trap`/`exception` — статичны;
- комментарий — `add_text_field_in_cell` всегда (даже пустой — это поле
  для ввода).

---

## 6. Навигация (bookmarks + internal links)

DOCX-навигация строится на `w:bookmarkStart` + `w:hyperlink w:anchor`:
- каждый регион → bookmark `region_<slug>`;
- каждая POI → bookmark `poi_<num>`;
- каждый кластер → bookmark `cluster_<slug>`.

Ссылки:
- coverage-таблица: название региона → `region_<slug>`;
- combined_with chip: → `poi_<num>` целевого POI;
- cluster chip: → `cluster_<slug>`.

**Word Navigation Pane** показывает заголовки если они styled как Heading
(в Stage 3 пока не используется — навигация через bookmarks достаточна).

**Ограничение Apple Pages:** Pages **не поддерживает** `w:anchor`
internal-навигацию (документировано). Внутренние ссылки видны, но не
кликабельны. Word / Google Docs / LibreOffice / iOS Word — работают.

---

## 7. Паритет с PDF (критично для dual-render)

DOCX и PDF Stage 3 рендерят **один и тот же extracted dict**. Контент
обязан совпадать; различается только интерактивность:

| Элемент | DOCX | PDF |
|---|---|---|
| Тег региона | чекбоксы (editable) | readonly badge, если заполнен |
| Комментарий POI | поле всегда | текст, если заполнен; скрыт если пуст |
| Распределение | цветные плашки | data-table |
| Coverage navigation | internal-link на регион | outline (Navigation Pane) |
| Google Images query | ASCII-only (Pages-safe) | percent-encoded (кириллица ok) |
| Описание / авторы / выдержки / флаги | идентичны | идентичны |

При правке логики рендера **менять обе ветки** (`build_docx` и
`build_pdf` в `stages/stage3.py`) — расхождение контента = баг.

---

## 8. Anti-page-break

Чтобы карточки не разрывались между страницами:
- `set_table_cant_split(tbl)` на каждой таблице-карточке (и nested
  header-table);
- `set_paragraph_keep(p, with_next=True)` на всех параграфах карточки
  кроме последнего — Word/Pages держат цепочку `keepNext` вместе.

Это надёжнее одного `cantSplit` на больших карточках (Pages иногда
игнорирует cantSplit на nested-таблицах).

---

## 9. Известные ограничения

- **Apple Pages + internal links** — не работают (§6). Рекомендуй Word /
  Google Docs для навигации.
- **Apple Pages + unicode URL** — Pages двойное-encode'ит `%XX`, поэтому
  Google Images query идёт ASCII-only (English-имя POI + регион). См.
  `_poi_search_query`.
- **SDT form fields** — сознательно не используются (§4). Если в будущем
  понадобятся настоящие Word-формы (для строгой валидации ввода) — это
  отдельное решение, не текущая модель.

---

## 10. Чек-лист добавления новой DOCX-стадии

1. `references/stage{N}/stage{N}-polish-prompt.md` — трансформации + маркеры.
2. `_PROFILE_STAGE{N}` в `polish_check.py`.
3. `stages/stage{N}.py` — extractor + `build_docx` (+ опц. `build_pdf` для
   паритета) + `register_renderer`.
4. Переиспользовать примитивы `docx_lib` (не писать свой XML); если нужен
   новый общий блок — добавить в `docx_lib` + сюда в §3/§5.
5. Импорт в `stages/__init__.py`.
6. Ветка в `export.py` + `DEFAULT_FORMAT["{N}"]`.
7. `tests/test_export_stage{N}.py`.
8. Запись в `export-modes.md` (поток) + `changelog.md`.
