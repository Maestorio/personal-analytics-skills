# pdf-visual-language.md

Единый визуальный язык PDF-экспортов. Все стадии, которые рендерятся в
PDF (Stage 5 — финальный план; Stage 4 — варианты маршрута; далее
Stage 0/1), используют **одни и те же** строительные блоки из
`scripts/export/pdf_lib.py` и одинаковые цвета/шрифты/структуру. Цель —
чтобы документы разных стадий выглядели как один продукт: пользователь
открывает Stage 4 (3 варианта), сравнивает, выбирает один — и видит тот
же стиль, что и в финальном плане Stage 5.

**Принцип:** визуальный стиль и компоненты **фиксированы** и живут в
`pdf_lib`/`style.py`. Stage-модуль (`stages/stageN.py`) только извлекает
контент из markdown и **компонует** готовые блоки — он не определяет
свои цвета, шрифты или layout.

---

## 1. Переиспользуемые блоки (`pdf_lib` API)

Stage-модуль собирает документ из этих функций. Ничего не рисуем «руками».

| Функция | Что делает |
|---|---|
| `register_fonts()` | Регистрирует body/heading/mono + CJK-фонт. Идемпотентно. |
| `get_styles()` | dict ParagraphStyle'ов: `cover_title`, `cover_subtitle`, `cover_meta`, `h2`, `h3`, `h4`, `body`, `body_compact`, `bullet`, `small`, `day_header`, `day_marker`, … |
| `make_doc(path, *, orientation, title)` | `BookmarkedDocTemplate` (A4, поля 2 см, авто-outline). |
| `build_doc(doc, story)` | Сборка с кремовым/белым фоном, accent-полосой сверху, футером. |
| `set_footer_text(s)` | Левый текст футера (например, «создан 2026-05-28»). |
| `set_section_anchors(map)` / `clear_section_anchors()` | Карта `heading → slug` для inline-ссылок `## Секция`. |
| `para(text, style)` | Параграф с inline-md разметкой (bold/italic/код/ссылки/TODO-подсветка). |
| `heading_paragraph(text, style, *, anchor_slug, outline_level)` | Заголовок с destination (для ссылок) и опц. записью в PDF-outline. |
| `section_bar(text, *, anchor_slug, outline_level)` | Залитая плашка-заголовок H2-секции (белый текст на тёмном). |
| `day_header_bar(label, budget, *, anchor_slug, outline_level, region, region_color)` | Тёмная плашка дня: метка слева, бюджет в правом углу, опц. region-caption + цветная полоса слева. |
| `region_titler(idx, total, name, meta, color, *, bullets, anchor_slug)` | Светлый блок «РЕГИОН N ИЗ M» с bullets — врезка перед группой дней. |
| `key_params_table(rows)` | Двухколоночная таблица «Параметр \| Значение» для обложки. |
| `data_table(rows, *, header, col_widths)` | Таблица в фирменном стиле (тёмный header, зебра, рамка). |
| `warning_box(text, styles)` | Заметный amber-прямоугольник с рамкой — риски/важное (одна фраза). |
| `warning_box_bullets(items, styles)` | Тот же amber-стиль, но содержимое — bullet-список. Для сводки нескольких warning'ов одним блоком (Stage 1 META). |
| `info_box(text, styles)` | Спокойная info-note (светло-голубой фон, левая полоса) — НЕ риск. |
| `bullet_list(items, styles)` | Bullet-список; checkbox-пункты `[ ] …` рендерятся глифом ☐ (отмеченные `[x] …` — ☑), не ASCII `[ ]`. |
| `definition_list(pairs, style)` | Список «**Ключ:** значение» без bullet-маркеров. |
| `lighten_hex(hex, factor)` | Осветлить цвет (для region-caption на тёмном фоне). |
| `spacer(pt)` / `page_break()` | Вертикальный отступ / разрыв страницы. |

---

## 2. Палитра (`style.COLORS`)

Цвета — только отсюда, по семантике, не «на глаз».

| Ключ | Hex | Назначение |
|---|---|---|
| `primary` | `#1a3a5c` | deep blue — заголовки, section-бары, accent |
| `secondary` | `#d4a574` | warm sand — вторичные иконки/highlight, supporting-tier (S0) |
| `warning` | `#d97706` | amber — ТОЛЬКО warning / caution / TODO-подсветка |
| `danger` | `#b91c1c` | deep red — red flag |
| `role_core` / `role_supporting` / `role_niche` / `role_borderline` | `#1a3a5c` / `#d4a574` / `#7c3aed` / `#b45309` | tier-бейджи S0 (у каждого своя форма); `role_borderline` — bronze, отдельный от warning-amber |
| `todo_highlight` | `#fef3c7` | жёлтая заливка-подсветка TODO |
| `text` | `#1f2937` | основной текст (тёмно-серый, не чёрный) |
| `background` | `#ffffff` | фон страниц |
| `accent_stripe` | `#1a3a5c` | тонкая полоса по верху каждой страницы |
| `day_bar_bg` | `#1f3a52` | тёмная плашка дня |
| `section_bar_bg` | `#1a3a5c` | залитая плашка H2-секции |
| `bar_text` / `bar_text_dim` | `#ffffff` / `#cdd6e0` | текст на плашках (основной / приглушённый) |
| `warn_bg` / `warn_border` / `warn_text` | `#f8f0d8` / `#d4a843` / `#7a5c00` | amber warning-box |
| `table_zebra` | `#f4f6f9` | чередование строк таблиц |

**Цветокод групп** — `style.REGION_PALETTE` (неяркие акценты, назначаются
по порядку появления): синий / зелёный / терракот / серо-голубой / охра /
purple / красный. На Stage 4 та же палитра годится для маркировки
вариантов (Вариант А/Б/В — три акцента).

**Семантика тёплых тонов** (каждый смысл — свой тон, не путать): amber
`#d97706` — только warning/caution/TODO; sand `#d4a574` — supporting-tier;
bronze `#b45309` — borderline-tier; yellow `#fef3c7` — заливка TODO;
ochre/терракот (REGION_PALETTE) — региональные акценты. amber для tier'ов
**не переиспользовать.**

---

## 3. Шрифты (`style.FONTS`, регистрация в `pdf_lib`)

- **Body / heading** — DejaVu Sans (через matplotlib-бандл или системный):
  покрывает кириллицу, ₽, стрелки →↔, ⚠, ✓, ✈, •, ★.
- **CJK** (хангыль/кандзи/ханьцзы) — Adobe **CID-фонт** reportlab
  (`UnicodeCIDFont`, например `HYGothic-Medium`). НЕ файл шрифта:
  CID работает кросс-платформенно, вьюер подставляет глиф. CJK-руны
  автоматически оборачиваются в CID-фонт в `md_inline_to_rl`.
- **Эмодзи** (📍🏨🎯💰⚠️🇰🇷 и пр.) **не рендерятся** ни одним из шрифтов —
  `md_inline_to_rl` их **вырезает** (иначе квадраты). Маркеры дней
  заменяются текстовыми метками/плашками, не эмодзи.

Размеры (`style.LAYOUT`): cover-title 32, H2 20, H3 16, body 11, small 9;
интерлиньяж body 1.5; поля 2 см.

---

## 4. Структура документа

Порядок и приёмы, одинаковые для всех стадий:

1. **Обложка** — `cover_title` (человекочитаемый заголовок, без
   pipeline-жаргона) + `cover_subtitle` (например, «… · Вариант А») +
   `key_params_table` (Длительность, Маршрут стрелками, Темп, Бюджет
   словами, …). trip_id / mode / профиль на обложку НЕ выводим.
   **Исключение — Stage 0:** обложка через `hero_cover_block` (full-bleed
   плашка `primary`); S1–S5 — плоский `cover_title`. Обложки разные по роли
   стадии: S0 — презентационная витрина, S1–S5 — операционные документы.
2. **Page chrome** (`build_doc`): белый фон, тонкая `accent_stripe`
   сверху, футер — слева текст из `set_footer_text`, справа «стр. N».
   Футер единый для всех стадий: левый — «создан {дата}» (или пусто),
   правый — «стр. N». Breadcrumb'ов / слагов стадий в футере нет.
3. **Section-бары** (`section_bar`) — каждый крупный раздел начинается
   залитой плашкой; обычно с `page_break()` перед ним. Заголовки
   (`h2`/`h3`/`h4`) — `keepWithNext`: не остаются одни внизу страницы.
4. **H3-подзаголовки** — `styles["h3"]` (синий текст, без заливки).
5. **Контент** — параграфы (выключка влево, ragged-right) / таблицы /
   боксы (см. §6).

---

## 5. Оглавление (PDF-outline) и гиперссылки

**Outline (закладки в просмотрщике).** Любой flowable с атрибутами
`_dest_slug` + `_outline_level` попадает в PDF-outline. Ставит их
`heading_paragraph` / `section_bar` / `day_header_bar` при передаче
`anchor_slug` + `outline_level`. `build_doc`/`BookmarkedDocTemplate`
регистрирует destination **по реальной позиции кадра** (в `afterFlowable`)
и вызывает `showOutline()` — панель закладок открывается автоматически.

**Внутренние ссылки.** Markdown `[текст](#slug)` → кликабельная ссылка
на destination `slug`. Destination создаёт любой блок с `anchor_slug`
(даже без outline — например, `region_titler` даёт `_dest_slug` без
записи в outline). Inline `## Название Секции` в тексте автоматически
линкуется на якорь секции (через `set_section_anchors` +
`md_inline_to_rl`).

**Видимое оглавление (TOC) — отдельно от outline.** Outline — это панель
закладок в просмотрщике; видимый TOC — страница «Содержание» в теле
документа (нужна при печати/чтении без панели). В Stage 5 (`_build_toc`)
TOC собирается **во время рендера** из реально отрисованных секций
(кликабельные `[Заголовок](#slug)`) и вставляется между обложкой и
контентом — поэтому он автоматически отражает recipient-гейты (например,
полевая версия `field` короче). Условный разрыв: записей больше порога
(`_TOC_BREAK_THRESHOLD`≈10) → разрыв страницы после TOC; меньше — контент
течёт сразу (не плодим пустую страницу под коротким оглавлением).

**Правила навигации (применять на всех стадиях):**
- H2-секции → в outline (level 0).
- Повторяющиеся единицы (дни/варианты) → в outline (level 1), вложенно.
- Сводная таблица в начале → ссылки на каждую единицу; обратная ссылка
  «↑ К сводной таблице» в конце каждой единицы.

---

## 6. Компоненты контента

| Семантика | Компонент |
|---|---|
| Заголовок крупной секции | `section_bar` (залитая плашка) |
| Единица-якорь (день / вариант) | `day_header_bar` (тёмная плашка, акцент в углу) |
| Врезка-описание группы | `region_titler` (светлый блок с цветной полосой + bullets) |
| Риск / важное предупреждение (одна фраза) | `warning_box` (amber, рамка) |
| Сводка нескольких предупреждений | `warning_box_bullets` (тот же amber, bullet-list) |
| Спокойная пояснительная заметка | `info_box` (светло-голубой, левая полоса) |
| Таблица (транспорт/бюджет/сравнение) | `data_table` |
| Параметры на обложке | `key_params_table` |
| Список пунктов | `bullet_list` |
| Пары «ключ-значение» | `definition_list` (не bullets) |
| Чеклист | `bullet_list` с `[ ]`-пунктами |

**Bullets vs параграфы:** список ключ-значений (`**Ключ:** …`) → плоские
строки/definition-list, НЕ bullets. Bullets — только под именованным
sub-header'ом или маркером.

---

## 7. Имена файлов

Финальные/презентационные документы именуются trip-ориентированно, чтобы
скачанные файлы разных поездок не путались:

```
{trip_id}_{что}_v{N}[_получатель].{ext}
```

`{trip_id}` = `{страна(ы)}_{YYYY-MM}`. Примеры:
`корея_2024-03_план_v1.pdf`, `камбоджа_лаос_2026-02_варианты_v1.pdf`.
trip_id берётся из YAML-шапки, версия — из имени исходного `_v{N}.md`.
Реализация — `file_naming.build_final_plan_filename` (для других «что»
аналогичный хелпер).

---

## 8. Правила рендера, которые нельзя ломать

Накоплено при доводке Stage 5 — переносить на все стадии:

1. **CJK — только CID-фонт**, не файл (`.ttc` с CFF-outlines reportlab не
   грузит). Не пытаться bundl'ить Noto.
2. **Эмодзи вырезаются** — не закладывать их в заголовки/контент как
   значимые; использовать текстовые метки или Unicode-геометрию (■ ▶ ★).
3. **Destination — через `afterFlowable`/anchored-механизм**, НЕ через
   `<a name>` внутри ячейки `Table` (даёт неверную Y) и НЕ отдельным
   0-height flowable (отрывается на page-break). У `Table` высота в
   `_height`/`_rowHeights`, не в `.height`.
4. **Числа/валюту парсить валюта-агностично** (₩/₽/$/€/₫/₭/៛/£) и с
   учётом разделителей тысяч (запятая/пробел/nbsp).
5. **Никакого pipeline-жаргона** в человеко-facing PDF (trip_id, mode,
   «Stage N», «aggregation_mode» и т.п.) — это убирает polish-шаг.

---

## 9. Применение к Stage 4 (варианты маршрута)

Use case: пользователь открывает PDF с 2–3 вариантами, **сравнивает,
выбирает один**, максимум оставляет комментарий (в чате, не в файле).
PDF — read-only витрина сравнения. Реализовано в `stages/stage4.py`,
polish-промт — `references/stage4/stage4-polish-prompt.md`.

Маппинг компонентов:

- **Обложка** — `cover_title` («{регионы} · сравнение вариантов»; БЕЗ
  «N ночей» — длительность идёт в таблицу, не дублируем). У заголовка
  установлен outline-якорь «Обзор» (быстрый прыжок в начало). Под ним —
  `key_params_table` со строками: Кто едет / Старт и финиш (одной
  строкой, если города совпадают; через стрелку, если разные) /
  Длительность / Сезон / Темп / Вариантов / Бюджет-ориентир. Параметры
  приходят из polish-маркера `[[поездка: …]]` (см. polish-промт T2b) с
  fallback-инференцией регионов/сезона из `trip_id`.
- **Сводка сравнения сверху** — `data_table` (строки = оси, колонки =
  варианты A/B/C). Заголовки колонок русифицируются автоматически
  (`Variant X` → `Вариант X`); упоминания «Вариант X» внутри ячеек —
  кликабельные ссылки на секции вариантов. Над таблицей —
  навигационная строка «Подробнее по вариантам: A · B · C» со ссылками.
- **Каждый вариант** — `section_bar` («Вариант A — …») с цветом из
  `REGION_PALETTE[i]`, в outline **level 0** (родительская «Варианты
  маршрута» в outline не выводится — варианты сами секции верхнего
  уровня). Внутри:
  - бюджетный лид `⚠️ **Бюджет:**` — `warning_box`;
  - таблицы (Маршрут по дням и т.п.) — `data_table`;
  - «осознанно жертвует», «логистика», «риски», «кому подходит» —
    `bullet_list` (с inline-bold);
  - flavor / контекст — параграфы;
  - «↑ К сравнению» — обратная ссылка на сводную таблицу.
- **Контекст / предупреждения** — под обложкой, без page break.
  Из контекста вырезаны вводные **Key:**-пункты, дублирующие таблицу
  параметров (Поездка / Темп / Маршрут / Длительность / Сезон / Бюджет /
  Группа) — `_strip_dup_context`.
- **Прочие содержательные H2** (`Спорные решения`, `Что НЕ вошло ни в
  один вариант`) — отдельные `section_bar` в outline level 0; заголовки
  с английским «CONTESTED»/«variant» русифицируются автоматически
  (`_normalize_heading`). Pipeline-шум (`Tags resolution`,
  `Trip parameters`, «Следующий шаг») подавляется.
- **Линкификация в теле** — упоминания «Вариант X» / «вариант X» /
  «Variant X» (с падежами) в прозе секций становятся кликабельными
  ссылками на соответствующий вариант (`_linkify_variants`), английский
  «Variant» в тексте ссылки русифицируется.
- **Решение** — блок `## Решение` из markdown НЕ рендерится: PDF
  read-only, выбор фиксируется в чате.

Имя файла: `{trip_id}_варианты_v{N}.pdf` через
`file_naming.build_variants_filename`. Дефолт-формат Stage 4 в `export.py`
— PDF (DEFAULT_FORMAT["4"]="pdf").

Поддерживаемые форматы исходника: новый (`## Вариант A: …` +
`## Сравнительная таблица`) и старый (`## Variant A — …` + `## Сравнение`)
— renderer матчит оба.

---

## 10. Применение к Stage 0 (региональная витрина для DR)

Use case: пользователь открывает PDF, видит **landscape-витрину
регионов** longlist'а — карточки сгруппированы по role (Core /
Supporting / Niche / Borderline), на каждой кликабельный заголовок
открывает Google Images по этому региону. Read-only — финальный выбор
делается через теги в Stage 3. Реализовано в `stages/stage0.py`,
polish-промт — `references/stage0/stage0-polish-prompt.md`.

**Page orientation: landscape** (`style.LAYOUT["stage0_orientation"]`).
В landscape карточки нормально ложатся в 2-колоночную сетку, hero-блок
читается как presentation-slide.

Маппинг компонентов:

- **Обложка** — `hero_cover_block` (full-bleed плашка в `primary` ~35%
  высоты страницы) с заголовком («{Регионы} · регионы для DR») и
  подзаголовком («{сезон} · {N} ночей · {формат}»). Под hero —
  `key_params_table` со строками: Кто едет / Страны / Темп / Регионов
  в выборке / Проанализировано регионов / Цель по ночам/регион.
  Параметры приходят из polish-маркера `[[поездка: …]]` + YAML.
- **Контекст** — отдельная страница: `section_bar` «Контекст поездки» +
  параграф «Контекст для следующих стадий» из артефакта (через
  `_render_md_paragraphs`).
- **Регионы для маршрутного списка** — отдельная страница: `section_bar`
  + `info_box` с пояснением (клик по названию → Google Images). Далее
  по каждой role-группе (Core → Supporting → Niche → Borderline):
  - подзаголовок «{Role} · {count}» в `styles["h3"]`;
  - `card_grid(cards, cols=2)` с `entity_card` для каждого региона;
  - **дисциплина плотности**: каждая role-группа начинается с новой
    страницы; если в группе > 4 карточек — режется на pageful-куски
    по 4 (2 ряда × 2 колонки) с `page_break` между ними и
    «{Role} · продолжение» подзаголовком на continuation-странице.
  - reserve-карточка ставится сразу после своей пары через
    `_order_with_reserves`.
- **Карточка региона** — `entity_card` со слотами:
  - `title` = имя региона, **`title_link`** = `https://www.google.com/
    search?tbm=isch&q={URL-encoded имя}` (кликабельная ссылка на Google
    Images — нулевая инфраструктура, работает в любом PDF-viewer'е).
  - `accent_color` = `style.ROLE_BADGES[Role]["color"]` (полоса слева
    + тинт фона).
  - `badge` = (role, role-color) в правом верхнем углу.
  - `meta_line` = «density: HIGH · 3–5 ночей · камбоджа».
  - `body` приоритет:
    1. **«Что увидишь»** — блок от polish T8 с 3-5 конкретными
       впечатлениями (Ангкор-Ват на рассвете; Та-Прохм с корнями…).
       Это наиболее ценное содержание для presentation.
    2. **«Принципиально»** из исходного longlist'а — fallback, если
       polish T8 не запущен.
    3. fallback — первые 1-2 не-технические предложения longlist'а.
  - `side_badges`: `RESERVE → {парный регион}` (warning amber);
    `non-canonical` (purple); `сезон: risk` / `сезон: blocked` (warning
    / danger) — короткий tag извлекается из длинного season-note через
    `_season_chip`.
- **Excluded regions** — отдельная страница: `section_bar` «Регионы
  вне выборки» + `card_grid(cols=2)` минимальных `entity_card` (только
  title + body=reason, нейтральный `accent_color="#94a3b8"`, без badge).
- **Non-canonical found** — отдельная страница: `section_bar` + per item
  `info_box` («**Кампонгтхом** (вне выборки). Древние кирпичные башни
  Ченла VII в. — LOW-MED density при slow-темпе»).
- **Честная оценка** — отдельная страница: `section_bar` + параграф.
- **Предупреждения** (`warnings` из YAML) — внизу как `bullet_list`,
  если есть.

Имя файла: `{trip_id}_регионы.pdf` через
`file_naming.build_scope_filename`. **Без версии** (`version=None` в
`build_trip_doc_filename`): Stage 0 артефакт один per trip, пересмотр
перезаписывает (storage-and-naming.md §2.1, §9.7). Дефолт-формат Stage 0
в `export.py` — PDF (`DEFAULT_FORMAT["0"]="pdf"`).

**Устойчивость к legacy-формату.** КЛТ_1 артефакт (опусный output)
группирует Region universe по странам (`### Камбоджа` / `### Лаос`), а
не по role; `role` в longlist YAML отсутствует. Builder работает с этим
форматом через `_resolve_role` (polish-маркер → YAML → инференция по
density+reserve_for) и `_find_subsection` (матчит описание региона
независимо от группировки H2). Для новых артефактов polish T3 даёт
`[[регион: …]]` маркер с явным role — это primary источник, не fallback.

---

## 11a. Применение к Stage 1 (DR-база отчётов)

Use case: пользователь открывает PDF, видит **structured DR-архив** — 37+
карточек авторов сгруппированы по регионам. Прыжок по outline к
конкретному автору, чтение POI с тональностью / жалоб. Read-only
reference-документ. Реализовано в `stages/stage1.py`, polish-промт —
`references/stage1/stage1-polish-prompt.md`.

**Page orientation: portrait** A4. В отличие от Stage 0 (landscape для
cards-витрины), Stage 1 — это длинный последовательный документ с
plenty текста (20 полей × 37 карточек), portrait читается лучше.
Hero-блок НЕ используется (§11.4: для portrait не применяется).

Маппинг компонентов:

- **Обложка** — `cover_title` («{Регионы} · DR-база отчётов») +
  `cover_subtitle` («{сезон} · {N} отчётов · {M} регионов»). Под ним —
  `key_params_table` со строками: Кто едет / Регионы (count + список) /
  Сезон / Дата DR-прогона / Отчётов всего (+ critical:) / WARN-флагов /
  Языки источников (формат «RU 22% · EN 78%»). Параметры приходят из
  polish-маркера `[[поездка: …]]` + YAML.
- **Mode B sample_curation_note** — если YAML содержит поле
  `sample_curation_note` (карточки добавлены через `merge_dr_additions.py`
  / awd.ru) — `info_box` на cover с пометкой «Расширение выборки: …».
- **Сводка отчётов** — `section_bar` «Сводка отчётов» (outline level 0):
  - `data_table` «Покрытие по регионам» (Регион | Карточек | POI-критика
    META | critical) — ячейка «Регион» = кликабельная ссылка на anchor
    региона.
  - `bullet_list` распределений (по стилям / сезонам / фокусу / языкам)
    под H3-подзаголовками. **EN-термины локализуются на лету**
    (`_localize_distribution_term`): «backpacker» → «бэкпэкер»,
    «mid-range independent» → «миддл-сегмент самостоятельно»,
    «photography-focused» → «фото-фокус» и т.д. (12 термов на КЛТ_1).
  - WARN-флаги — **один** `warning_box_bullets` с bullet-list'ом всех
    warning'ов (не N отдельных box'ов). Source приоритет: YAML
    `meta_diagnostics_warnings` → fallback body `## WARNINGs`. Merge НЕ
    делаем — это даёт визуальные дубли при разных формулировках одной
    мысли; семантическая дедупликация — задача polish T9.
    Префиксы `WARN-N:` / `B1-awd.ru:` / `NOTE:` срезаются
    (`_clean_warning_text`) — карточка сама даёт сигнал «предупреждение».
- **Региональные секции** — `section_bar` («{Регион} · {N} карточек»)
  с `bg_color = REGION_PALETTE[i]`, **БЕЗ outline_level** (регионы в
  outline не выводятся — навигация по картам).
- **Карточка** — `entity_card` со слотами:
  - `title` = «Карточка N · «Название отчёта»» из поля 1.
  - `title_link` = URL из поля 1 (кликабельный заголовок).
  - `accent_color` = `COLORS["danger"]` для critical / region color иначе.
  - `badge` = (focus_короткий, focus-color) — тэг из поля 13 («mix» /
    «фото» / «архитектура» / …).
  - `meta_line` = «{платформа·язык} · {автор} · {дата_публикации} ·
    {когда поездка}» (поля 2/3/4/5; пустые пропускаются).
  - `body_bullets` (компактно, **drop полей 6/8/10/16/17**):
    `**Группа / стиль:** {7} · {9}`, `**Транспорт:** {11}`,
    `**Размещение:** {12}`, `**POI:** {14}`, `**Hidden gems:** {15}`,
    `**Главное:** {19}` (цитата). Пустые/«не указано» — скрываются.
    Дополнительные cleanup'ы:
    - **Поле 11 (Транспорт)** — `_clean_transport` режет скобки-
      перечисления длиной > 40 символов (списки авиалиний, тарифов) и
      дедуплицирует повторы типа транспорта по первому слову
      («тук-тук по храмам; тук-тук в Pub Street» → «тук-тук …»).
    - **Поле 12 (Размещение)** — `_extract_accommodation_type` извлекает
      только тип (отель / хостел / homestay / гестхаус / квартира /
      кемпинг / luxury / бунгало / riverside) по keyword-словарю.
      Имена конкретных отелей и описания удобств не выводятся. Если
      тип не извлёкся — bullet вообще не показывается.
  - `side_badges`: `critical` (danger), `фото-фокус` (primary, если
    поле 20 = «ЯВНЫЕ»), `резидент` (secondary, если в маркере
    flags=residence), `iconic` (если flags=iconic).
  - `anchor_slug` = `card-{N}`, `_outline_level = 0`,
    `_outline_title = "N · Автор — «Название»"` — каждая карточка
    попадает в PDF-outline (формат C2 — без региона в названии).
- **Critical-карточка** — сразу под `entity_card` добавляется
  `warning_box` с цитатой жалоб (поле 18, label-префикс «Жалобы / …»
  срезается).
- **Tails** (каждый на новой странице):
  - «Сезонные caveat'ы» — `info_box` с длинной цитатой из META.
  - «Источники вне seed-списка» — `bullet_list`.
  - «Источники, что пробовали» — `bullet_list`.

**Outline-стратегия (Stage 1 specifics):**
- Сводка / Сезонные caveat'ы / Источники tails — `outline_level=0`.
- Региональные `section_bar` — **outline_level=None** (только anchor для
  внутренних ссылок из coverage-таблицы).
- Карточки — `outline_level=0` (плоский outline, каждая на своём уровне)
  с title формата «N · Автор — «Название»» (обрезается до 90 симв).

**Tonality-detection** — три ветки с приоритетом:
1. `[[карточка: tonality: critical | …]]` маркер от polish T3.
2. Inline-суффикс H3 — `### Карточка 4 — tonality: critical`.
3. Grep `tonality: critical` в **raw** (label+value) поля 18 — критично:
   часто маркер живёт в label `**Жалобы / tonality: critical:**`, а не
   в value (цитате).

**Источники полей в `Card`-структуре:** `_parse_card_fields` возвращает
`dict[int, dict[str, str]]` с ключами `label` / `value` / `raw` —
shortcut'ы `_fv(fields, N)` (value) и `_fraw(fields, N)` (label+value).

**Устойчивость к входным форматам:**
- Pure DR-output без YAML → regions парсятся из H2, trip_id fallback на
  `--trip` CLI arg, cover deg радирует gracefully.
- Mode A.wrap (Claude AI добавил шапку поверх DR content) → YAML
  валидный, всё работает.
- Mode B (`merge_dr_additions.py` добавил awd.ru карточки + обновил
  YAML с `sample_curation_note`) → новые карточки парсятся как обычные
  H3 «### Карточка N» с продолжением нумерации; `sample_curation_note`
  рендерится info-box'ом на cover. Если карточки оказались вне
  региональных H2 — собираются в псевдо-регион «Дополнительные карточки».

Имя файла: `{trip_id}_dr_отчёты.pdf` через
`file_naming.build_dr_reports_filename`. Без `_v{N}` — Stage 1 артефакт
один per trip, перепрогон DR переписывает.

---

## 11b. Применение к Stage 2 (similarity — авторы по похожести)

Stage 2 — **единственная стадия с двумя форматами вывода**. Реализовано
в `stages/stage2.py`, polish-промт —
`references/stage2/stage2-polish-prompt.md`.

| Формат | Роль | Практика (POI/gems/warnings) |
|---|---|---|
| **PDF** (default, портретный, светлый) | Печать / архив, scoring-витрина по категориям | НЕТ — дублировала бы Stage 1 PDF |
| **HTML** (тёмный) | Рабочий lookup: фильтр / сортировка / click-to-expand | ДА — таб «Практика» из `1_dr_reports.md` (поля 14/15/18/20, матчинг по URL) |

Общий экстрактор `extract_content` → `Stage2Content` (scoring), один на
оба формата. Парсер устойчив к двум формам строки компонентов
(`C1 style 8→2.0` и компактной `C1 8→2.0`), к ASCII-стрелке `->`
(старый формат), к null `C6 demo —` и к переносу строки компонентов на
2 физических строки. Категории — фиксированы spec'ой: HIGH / OUTLIER /
MEDIUM / LOW / UNSCORED. Цвета карточек — `style.SIMILARITY_CARD_COLORS`.

**PDF (scoring-витрина), маппинг компонентов:**
- **Обложка** — `cover_title` («{Регионы} · Похожие авторы») +
  `key_params_table` (профиль / архетип+источник весов / веса C1–C6 /
  пороги / авторов / распределение / confidence). Контекст — `info_box`.
- **Распределение** — `section_bar` (outline 0) + `data_table`
  (Категория | Кол-во | Доля) + строка `**Confidence:** …`.
- **Warnings** — один `warning_box_bullets`.
- **Reading list** — `section_bar` «Reading list для Stage 3» (outline 0),
  внутри три цветные `section_bar` без outline (HIGH green / OUTLIER
  purple / extended blue), под каждой — `entity_card` на автора:
  `title` = имя, `badge` = категория, `meta_line` = «score/10 ·
  [user_added] · [low_confidence: M/6]», `body` = SIGNAL (OUTLIER) +
  строка компонентов `C1 style v→c · …` + Тянет вверх/вниз + URL
  (markdown-ссылкой, не bare — иначе `_wrap_bare_urls` double-wrap'ит
  дефисные домены).
- **UNSCORED с сигналом** — `entity_card` grey, с SIGNAL.
- **Полная таблица** — `data_table` (# | Автор | Score | Категория | URL),
  все авторы, score ↓.
- **MEDIUM/LOW компактно** — per-author параграфы (`_compact_block`):
  заголовок + строка компонентов + tag-marker + URL.

Outline — плоский по большим секциям (`section_bar` outline 0); категории
внутри reading list — визуальные, без outline-entry.

**HTML (интерактивный lookup):** шаблон
`templates/stage2_similarity.html` (тёмная тема, IBM Plex + Playfair,
Google Fonts) с токенами `%%…%%`. JS-функции (filter/sort/switchTab/
renderCards) статичны; `build_html` подставляет данные:
- `const reports = [...]` — массив объектов `{num, author, url, cat,
  score, tags, comps[6], contribs[6], rationale, up, down, outlierSignal,
  readingList, practical?}`, собранный `_merge_authors` (полная таблица =
  authoritative score/cat/url + детали по матчингу URL/имени).
- `HAS_PRACTICAL` — `true`/`false`. Управляет наличием таба «Практика».
- summary-плашки, warning-banner, reading-section, веса/имена
  компонентов — генерируются из YAML/контента.

**Практика (только HTML, graceful degradation):**
`enrich_with_practical(content, dr_path)` переиспользует
`stage1.extract_content` + `stage1._extract_url_and_title` / `_fv`,
строит `{url → {poi, gems, warnings, photo}}` из DR-карточек, матчит по
нормализованному URL. Если `1_dr_reports.md` не найден ИЛИ его layout
не парсится stage1 (0 карточек) → `False`, таб «Практика» не рендерится.
DR-путь резолвится автоматически рядом с `source_file`.

Имя файла: `{trip_id}_фильтр_авторов.{pdf,html}` через
`file_naming.build_similarity_filename` (без `_v{N}` — артефакт один per
trip). Дефолт-формат — **pdf** (`DEFAULT_FORMAT["2"]`); HTML по явному
`--format html`.

---

## 11. Дизайн-паттерны для cards-стадий

Накопленные при реализации Stage 0 решения, переиспользуемые в будущих
cards-стадиях (Stage 1 DR-отчёты, Stage 2 авторы, Stage 3 POI — DOCX-
версия будет аналогична). Этот раздел — справочник «как принято
делать», чтобы при добавлении новой стадии не переоткрывать паттерны.

### 11.1 Универсальный примитив `entity_card`

Любая сущность пайплайна (регион / POI / автор / DR-отчёт) рендерится
одним и тем же примитивом `pdf_lib.entity_card(...)` со слотами:

| Слот | Назначение | Пример Stage 0 (регион) |
|---|---|---|
| `title` | Имя сущности (крупный кликабельный заголовок) | имя региона |
| `accent_color` | Цвет полосы слева + tinted фон (lighten 90%) | role-color из `ROLE_BADGES` |
| `badge` (text, color) | Маркер категории в правом верхнем углу | role («CORE» / «SUPPORTING» / …) |
| `meta_line` | Компактная строка под header | `density: HIGH · 3–5 ночей · камбоджа` |
| `body` | Текст-описание (markdown inline) | «Принципиально:» differentiator (fallback) |
| `body_bullets` | Список точек (приоритет над `body`) | «Что увидишь»: 3-5 конкретных впечатлений |
| `side_badges` | Доп. чипы внизу (text, color) | RESERVE / non-canonical / сезон: risk |
| `title_link` | URL — превращает title в кликабельную ссылку | Google Images по имени региона |
| `anchor_slug` | Destination для внутренних ссылок | `region-{slug}` |
| `width` | Ширина (`"50%"` для 2-col grid в landscape) | `"100%"` (внутренний по grid) |

**Принцип маппинга.** Stage-builder делает тонкий wrapper
(`_region_to_card`, `_author_to_card`, `_poi_to_card`, …), который
переводит свои поля в эти слоты. Никакой стилизации в stage-модуле —
вся визуальная логика в `entity_card`.

**Эскизы маппинга для будущих стадий:**

| Stage | Сущность | accent_color источник | badge | body_bullets | title_link |
|---|---|---|---|---|---|
| 1 | DR-отчёт | нейтральный (slate) или по author trust | reports_count | bias-warnings или ключевые findings | — |
| 2 | автор | trust-color (`HIGH`=primary / `MED`=warning / `LOW`=danger) | trust-label | reading-list URLs | URL автора |
| 3 | POI | category-color (`STRONG`=primary / `WEAK`=secondary / …) | category | выдержки из DR | — |

### 11.2 Раскладка карточек: `card_grid` + дисциплина плотности

**Сетка.** `pdf_lib.card_grid(cards, cols=2, gutter_pt=8)` — outer Table
с равными колонками. Для landscape A4 — 2 колонки. Для portrait может
работать в 1 колонку (или 2 с узкими карточками).

**Дисциплина плотности (2-4 карточки на страницу).** Без жёсткой
дисциплины reportlab разваливает grid посреди карточки и портит визуал.
Правила:

1. Каждая логическая группа (role / category / trust-level) начинается
   с новой страницы — `page_break()` перед заголовком группы.
2. Если группа > 4 карточек — делим на `_chunk(items, 4)` куски по 4
   (2 ряда × 2 колонки на странице), вставляем `page_break()` между
   кусками.
3. На continuation-странице — тот же section_bar с суффиксом
   «· продолжение», **без** `anchor_slug` / `outline_level` (не
   попадает в оглавление).

Реализация — `stages/stage0.py:build_pdf` блок 3 (longlist). Это
эталонный паттерн для Stage 1/2/3 cards.

### 11.3 Заголовки групп: цветные `section_bar`

Когда сущности разбиты на категории с цветовым кодированием
(Stage 0: role; будущий Stage 2: trust; Stage 3: category) —
**заголовок группы** = `section_bar(text, bg_color=category_color,
anchor_slug=..., outline_level=0)`:

- Залитая плашка во всю ширину, цвет группы.
- `outline_level=0` → плоская структура оглавления (группы на верхнем
  уровне рядом с «Контекст», «Честная оценка»).
- Continuation: тот же `bg_color`, без `anchor_slug`/`outline_level`.

**Не** заворачивать группы под общий родительский section_bar в
outline («Регионы для маршрутного списка» как родитель Core/Supporting/
…) — это лишняя обёртка, оглавление становится глубоким без пользы.

### 11.4 Обложка landscape: `hero_cover_block`

Для landscape-презентационных стадий (Stage 0; вероятно Stage 1 если
делаем в landscape):

```python
story.append(pdf_lib.hero_cover_block(
    title="…",                          # большой заголовок
    subtitle="…",                       # подзаголовок мелче, dim
    accent_color=COLORS["primary"],     # дефолт
    height_ratio=0.35,                  # ~35% высоты Frame
))
story.append(pdf_lib.spacer(14))
story.append(pdf_lib.key_params_table(rows))  # ниже hero — таблица параметров
```

Hero даёт presentation-ощущение (full-bleed deep blue с белым
заголовком), отличает PDF от report-style документа. Для portrait
стадий (Stage 4/5) hero не применяется — там cover делается через
`cover_title` + `cover_subtitle` styles.

### 11.5 Google Images как `title_link` — паттерн для presentation-стадий

Кликабельный `title_link` карточки на Google Images — нулевая
инфраструктура, мгновенный «карточка → визуальная ассоциация»:

```python
google_q = quote_plus(name)              # urllib.parse.quote_plus
title_link = f"https://www.google.com/search?tbm=isch&q={google_q}"
```

Применяется для cards, где имя сущности — географическое (регион, POI).
Для DR-отчётов / авторов не нужно (там `title_link` ведёт на URL
источника или вовсе отсутствует).

### 11.6 Семантика `side_badges`

Чипы в подвале карточки — это **рисковые/контекстные сигналы**, не
основная информация:

| Тип | Цвет (`style.COLORS`) | Когда |
|---|---|---|
| Reserve / substitute | `warning` (amber) | подменяющая карточка |
| Non-canonical / off-pattern | `role_niche` (purple) | нестандартная категория |
| Сезон/доступность risk | `warning` (amber) | пограничный риск |
| Сезон/доступность blocked | `danger` (deep red) | критичный/закрыт |
| Iconic / star | `primary` или `secondary` | положительный сигнал |

**Правило:** не более 2-3 chip'ов на карточку. Если нужно показать
много меток — это не chip'ы, а полноценный body content.

### 11.7 Гигиена контента: универсальные cleanup-helpers

Перед рендером prose-секций (контекст, honest assessment, описания)
прогонять через универсальные cleanup'ы — это страховка на случай
рендера без polish, и одновременно вторая линия обороны если polish
что-то пропустил.

**`_strip_yaml_jargon(text)`** (`stages/stage0.py`) — убирает:
- `(\`field: value\`)` — скобочные YAML-ссылки;
- `\`field: value\`` — голые backtick'нутые YAML-refs;
- Bullet «Флаг `field: value` — …» — целый bullet про YAML-флаг;
- Backtick'нутые `trip_id` (`\`корея_2024-03\``).

Применять ко всему prose-контенту перед рендером.

**`_capitalize_first(text)`** (`stages/stage0.py`) — заглавная первая
буква описания (пропускает ведущие пробелы / `**`). Источники часто
дают описания со строчной после двоеточия — для presentation
капитализируем.

Эти helpers сейчас живут в `stages/stage0.py`. При добавлении Stage 1/3
**перенести в общий модуль** (например, `scripts/export/cleanup.py`)
если будут переиспользоваться. Не дублировать — один источник.

### 11.8 Шрифт для landscape: локальное переопределение

Landscape-стадии (Stage 0) визуально требуют чуть более крупного
body-шрифта, чем portrait (Stage 4/5). Глобальный `LAYOUT["size_body"]`
оптимизирован под portrait — **не менять**. Вместо этого в stage-builder
локально:

```python
styles = pdf_lib.get_styles()
styles["body"] = _bump_font(styles["body"], size=12.5, leading=18)
styles["bullet"] = _bump_font(styles["bullet"], size=12.5, leading=18)
```

`_bump_font` — простая обёртка `ParagraphStyle(parent=..., fontSize=...,
leading=...)`. Размер 12.5pt + leading 18 проверены на КЛТ_1 как
комфортные для чтения «Честной оценки» в landscape A4.

### 11.9 Извлечение описания: приоритеты body content

Для cards-стадий тело карточки строится с приоритетом:

1. **Polish-маркер «Что увидишь:» / аналог** — bullets с 3-5 конкретных
   точек. Самое ценное для presentation. Если есть — рендерим как
   `body_bullets`.
2. **Исходный differentiator** («Принципиально:» в Stage 0 longlist) —
   плоская фраза, fallback если polish не запущен.
3. **Первые 1-2 не-технические предложения** — финальный fallback.

Технические key-value строки (Состав / Density / Сезон в … / Логистика
/ Reserve binding) всегда отсекаются. Это `_TECH_KEY_LINE_RE` + явные
исключения в `_extract_description_and_season`.

**Polish T-блок «Что увидишь»** должен быть в каждом polish-prompt
cards-стадии. Шаблон: 3-5 точек через `;` или `\n- `, конкретные
имена/феномены (Ангкор-Ват на рассвете; Та-Прохм с корнями …), не
generic enumeration.

### 11.10 Outline-стратегия

Плоский outline удобнее иерархического:

- Все основные секции — `outline_level=0`.
- Группы внутри секции (Core / Supporting / …) — тоже `outline_level=0`,
  без обёртки-родителя.
- Continuation-страницы и titler'ы (region_titler в Stage 5) — `anchor_slug`
  есть (для внутренних ссылок), но `outline_level=None` (в оглавление
  не попадают).

Excluded sections (excluded_regions, non-canonical) — тоже `level=0`.
Конечная глубина outline = 1 уровень, плоско, всё видно сразу.

---

## 12. Чек-лист добавления новой cards-стадии

Для разработчика, который начинает Stage N PDF (например, Stage 1
DR-отчёты или Stage 3 POI после внедрения DOCX-варианта):

1. **Дизайн** — секция «Применение к Stage N» в этом файле (§9 для
   Stage 4, §10 для Stage 0 — шаблоны), описывающая:
   - какие сущности → cards, какие → table/info_box/параграф;
   - маппинг полей сущности на слоты `entity_card` (см. §11.1);
   - источник `accent_color` (категория сущности);
   - logic для `body` / `body_bullets` (приоритет «Что увидишь» из polish);
   - какие `side_badges` рисуем (см. §11.6);
   - наличие/отсутствие `title_link`;
   - hero или обычный cover (§11.4);
   - page orientation (landscape для presentation, portrait для
     read-only документов).

2. **Polish-prompt** — `references/stageN/stageN-polish-prompt.md`
   (export-design.md §2.5).

3. **Stage-профиль** — `_PROFILE_STAGEN` в `polish_check.py`
   (export-design.md §2.5).

4. **Stage-builder** — `scripts/export/stages/stageN.py` по образцу
   `stage0.py`:
   - `extract_content(parsed)` — структура из markdown/YAML;
   - тонкие wrapper'ы `_entity_to_card(...)`;
   - `build_pdf(extracted, output_path)` с дисциплиной плотности (§11.2);
   - `render_stageN(parsed, recipient, output_path)` entry-point;
   - регистрация: `_renderer.register_renderer("N_*", "pdf", render_stageN)`.

5. **File naming** — `file_naming.build_X_filename` если имя файла
   не подходит под `build_export_filename` (как Stage 0/4/5).

6. **`export.py` ветка** — `DEFAULT_FORMAT["N"]` + ветка под
   `args.stage == "N"` для выбора filename builder'а.

7. **Тесты** — `tests/test_export_stageN.py` по образцу
   `test_export_stage0.py`: extract_content на fixture, helpers,
   file_naming, build_pdf smoke, CLI integration.

8. **Documentation update**:
   - Эта file: добавить «§X. Применение к Stage N».
   - `references/export/export-modes.md`: «Поток для Stage N».
   - `docs/travel-planning/changelog.md`: запись.

9. **Smoke на реальной fixture** (Vietnam / Korea / КЛТ_1) — визуальная
   инспекция PDF, итерации.

При следовании этому чек-листу новая стадия добавляется без переоткрытия
паттернов — всё консолидировано в §1-11 этого файла + образцовом коде
`stage0.py`.

---

## 13. Применение к Stage 6 (финал: карта + досье)

Stage 6 — **не cards-стадия** и **не самостоятельный рендер**: это
**механический ассемблер** поверх Stage 5. Образец §12 (cards) к нему не
применяется; вместо него — паттерн «inject в чужой builder».

### Принцип сборки

`stage6.build_pdf(s5, s6, …)` НЕ перерисовывает план. Он:
1. читает устаканенный `5_vX` (immutable) и зовёт `stage5.build_pdf` с opt-in
   параметром `inject` — пакетом готовых flowables;
2. генерит обзорную карту (matplotlib → PNG) из координат `6_final.md`;
3. собирает приложения досье / бронь / углубления из `6_final.md`.

`stage5.build_pdf(..., inject=None)` — поведение Stage 5 неизменно (golden
сохранён). При `inject={…}` сплайсит добавки в фиксированные точки:

| Ключ `inject` | Куда вставляется | TOC |
|---|---|---|
| `map_flowables` / `map_toc` | сразу после обложки → ложится **после TOC**, своя страница | строка «Обзорная карта маршрута» (первой) |
| `appendix_flowables` / `appendix_toc` | после чеклиста, **перед** приложением «Обоснование» | строки Дорожное досье / Бронирования / Углубления |
| `footer` / `title` | футер «финал · создан …» / заголовок PDF-документа | — |

### Карта (Уровень 1 — обзорная)

- Движок — `render_route_map(spec, countries, out_base)` в `stage6.py`
  (универсальный: авто bbox, point-in-polygon заливка страны маршрута,
  поправка широты, кривые рёбра, типы рёбер). Контур стран —
  `scripts/export/data/ne_countries.geojson`.
- Координаты — из блока `## Координаты маршрута` `6_final.md` (НЕ из газетира
  на рендере: резолв сделан на контент-стадии). Парсит `parse_coords_section`
  → `build_route_spec`.
- Типы рёбер: `обычное` → сплошная primary-линия; `узкое звено` → толстая
  `danger`-линия; `перелёт` → пунктир. Пины нумерованы цветами
  `REGION_PALETTE` по порядку остановок.
- Встраивание: matplotlib PNG → `pdf_lib.map_image(png)` (вписывает в
  контент-бокс с сохранением пропорций, центрирует). Требует `Image` из
  reportlab (импортирован в `pdf_lib`).
- Scope v1 — **только обзорная** карта. Региональные инсеты (Уровень 2) нужны
  деревенские координаты (Tier-2, риск точности) — отдельная итерация.

### Вёрстка досье (приложения)

Под-секции досье рендерятся через `stage5._render_markdown_body` — он уже даёт
нужные компоненты:
- `> ...` (blockquote) → `info_box` — ключевые предупреждения (виза, безвиз);
- `⚠️ ...` → `warning_box` — критические предупреждения;
- markdown-таблица → `data_table` — экстренные контакты / упаковка;
- `- ...` → `bullet_list` — перечни (прививки, что взять);
- заголовки H3 под-секций (Визы / Медицина / …) → `para(styles["h3"])`.

Секции-плашки приложений — `section_bar(title, anchor_slug=…, outline_level=0)`
(те же якоря / PDF-outline / TOC, что у H2 Stage 5).
