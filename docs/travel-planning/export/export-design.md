# Travel Planning Export — дизайн-документ

**Статус:** исторический план. Engine + Stage 5 PDF РЕАЛИЗОВАНЫ
(2026-05-28); часть решений плана пересмотрена при реализации.
**Актуальная операционная правда:**
- `skills/travel-planning/references/export/export-modes.md` — flow
  режима Export (polish → sanity → render);
- `skills/travel-planning/references/export/pdf-visual-language.md` —
  визуальный язык (цвета/шрифты/блоки/outline/ссылки/имена файлов),
  единый для всех PDF-стадий;
- `skills/travel-planning/references/stage{N}/stage{N}-polish-prompt.md` —
  **per-stage polish-prompt** (см. §2.5 ниже про обязательность).
- **`skills/travel-planning/references/export/html-rendering.md`** — HTML→PDF
  рендер-слой (v0.57, 1:1 с дизайн-системой): `html_lib` + `stages_html/*` +
  `assets/*.css`, конвертация headless-chromium. Параллелен reportlab (тот
  остаётся fallback). Слой извлечения (`stages/*.extract_content`) общий.
- **`docs/travel-planning/format-firewall.md` §7 «Термины и русификация»** —
  `taxonomy.json` как SSOT видимых ярлыков/категорий во ВСЕХ стадиях и обеих
  ветках рендера; `ru_anglicisms` для англицизмов; правило «новый видимый
  термин → сначала в taxonomy». Хардкодить RU-строку в рендерере нельзя.

Расхождения с этим планом — см. Changelog в конце файла. Не доверять
устаревшим разделам (§2 формат Stage 4, **§2 Stage 2 = SKIP** — теперь
PDF+HTML, см. Changelog 2026-06-01, §5 фон/шрифты, §8 имена файлов,
Q3 core pdf skill) без сверки с реализацией.

**Цель документа:** дать новой сессии достаточно ориентиров для
реализации Export stage без сковывания деталей кода. Контекст
калибровки (v0.21-v0.25) сохранён здесь — новая сессия не должна
повторять старые ошибки.

**Это единственная точка входа.** §0 ниже — навигационная карта по всем
файлам, нужным для работы с экспортом. §0.5 — правила update-discipline
(что обновлять, когда что-то меняется).

---

## 0. Карта документации (single source of truth)

Все файлы, нужные для работы с экспортом, сгруппированы по слоям.
**Все пути относительно корня репозитория `claude_skills/`** (если не
сказано иное).

### 0.1 Архитектурный слой (дизайн, обоснования)

| Файл | Назначение |
|---|---|
| `docs/travel-planning/export/export-design.md` ← **этот файл** | Дизайн-план + историческое обоснование + chek-листы по добавлению stages. **Единственная точка входа.** |
| `docs/travel-planning/export/export-design-by-type.md` | Отличия экспорта по получателям (self / parents / partner / guide / archive): что включается/вырезается, матрица, статус реализации. |
| `docs/travel-planning/architecture.md` | Архитектурные решения скилла в целом (включает экспорт). |
| `docs/travel-planning/changelog.md` | История изменений скилла (включая Export — v0.26 Stage 4 PDF, v0.27 Stage 0 PDF, …). |

### 0.2 Операционный слой (как запускать экспорт)

| Файл | Назначение |
|---|---|
| `skills/travel-planning/references/export/export-modes.md` | Flow Export-режима: trigger → consent → polish → sanity → render → presentation. Жёсткие правила («не пиши свой генератор»). Поток per stage (0/4/5). |
| `skills/travel-planning/references/export/pdf-visual-language.md` | Визуальный язык PDF-стадий: §1-8 базовый (компоненты, палитра, шрифты, outline), §9-10 применение к Stage 4/0, **§11 дизайн-паттерны для cards-стадий** (universal `entity_card`, плотность 2-4, гигиена контента), **§12 чек-лист добавления новой cards-стадии**. |

### 0.3 Per-stage контракты (что polish/builder ожидают друг от друга)

Каждая рендеримая стадия имеет 3 связанных артефакта:

| Артефакт | Stage 0 | Stage 1 | Stage 2 | Stage 3 | Stage 4 | Stage 5 | Stage 6 |
|---|---|---|---|---|---|---|---|
| **Stage spec** | `stage0-scope.md` | `stage1-dr-prompt.md` | `stage2-similarity.md` | `stage3-poi.md` | `stage4-variants.md` | `stage5-final.md` | `stage6-final.md` |
| **Polish-prompt** | `stage0-polish-prompt.md` | `stage1-polish-prompt.md` | `stage2-polish-prompt.md` | `stage3-polish-prompt.md` | `stage4-polish-prompt.md` | `stage5-polish-prompt.md` | `stage6-polish-prompt.md` |
| **Stage-builder** (Python) | `stages/stage0.py` | `stages/stage1.py` | `stages/stage2.py` | `stages/stage3.py` | `stages/stage4.py` | `stages/stage5.py` | `stages/stage6.py` |
| **Формат** | PDF (landscape) | PDF | **PDF + HTML** | **DOCX** (+PDF) | PDF | PDF | PDF |

**Stage 6 — особенность:** единственная стадия с **механическим ассемблером**
(не самостоятельный рендер). `stage6.py` НЕ перерисовывает план: он
переиспускает билдеры `stage5.py` на устаканенном `5_vX` (immutable, читается
по YAML `source_plan`) и вставляет добавки через opt-in `inject`-пакет
(`map_flowables` + `appendix_flowables`) в `stage5.build_pdf`. Так контент 5_vX
ни разу не прогоняется повторно через LLM → ноль дрейфа. Обзорную карту рисует
встроенный универсальный рендерер (matplotlib → PNG, координаты — из
`## Координаты маршрута` блока `6_final.md`, НЕ из газетира на рендере). Тесты —
`tests/test_export_stage6.py` (67 проверок) + `tests/test_geocode.py`
(43 проверки, Tier-1 геокодер контент-стадии).

Формат-контракт Stage 6 (как у 0–5): producing-spec `stage6-final.md` +
**канон `stage6-output-spec.md`** (low-freedom; формат блока координат парсит
рендерер) + polish-prompt `stage6-polish-prompt.md`. Drift-тест
`test_format_contract.py` сверяет канон ↔ парсер (`stage6._edge_kind`,
`_col_index`) ↔ reference. `check_format STAGE_CHECKS["6"]` — generic-проверки
(`--stage 6`: dollar/yaml/brevity/save-as; каунтеров у Stage 6 нет).

(Все spec/polish-prompt — в своей папке на стадию: `references/stageN/`
(например, `references/stage5/stage5-final.md` + `stage5-polish-prompt.md`);
builder — относительно `scripts/export/`.)

**Stage 2 — особенность:** единственная стадия с **двумя форматами**
(осознанная асимметрия под читателя): **PDF** (default, светлая scoring-
витрина по категориям) + **HTML** (тёмный интерактивный lookup с фильтром/
сортировкой/expand). HTML-таб «Практика» обогащается из `1_dr_reports.md`.
HTML-шаблон — `scripts/export/templates/stage2_similarity.html`; визуальный
маппинг — `pdf-visual-language.md §11b`. Тесты —
`tests/test_export_stage2.py` (90 проверок). **Расходится с §2 плана
(там Stage 2 = SKIP)** — см. Changelog 2026-06-01.

**Stage 3 — особенность:** единственная стадия с **DOCX как primary**
(operative-документ для заполнения тегов/комментариев) + PDF secondary.
DOCX-примитивы — в `scripts/export/docx_lib.py`; визуальный язык —
`references/export/docx-visual-language.md`. Тесты —
`tests/test_export_stage3.py` (103 проверки).

### 0.4 Кодовый слой (engine + stage builders + visual primitives)

Все пути относительно `skills/travel-planning/scripts/export/`.

| Файл | Назначение |
|---|---|
| `export.py` | CLI entry point: `--stage N --trip TRIP_ID --recipient ...`. Поиск артефактов, маршрутизация в stage-builder, вывод RenderRequest. `DEFAULT_FORMAT[stage]` карта. |
| `parser.py` | Generic md+YAML splitter (`parse_stage_file`, `parse_md_paste`, `parse_docx_for_import` — заглушка). |
| `adapter.py` | Recipient adaptation (`adapt_for_recipient`): применение `self/parents/…` правил, реестр stage-extensions. |
| `renderer.py` | Реестр renderer'ов: `register_renderer(stage_id, format, fn)`. Stage builders регистрируются на import-time через `stages/__init__.py`. |
| `pdf_lib.py` | **Универсальные визуальные примитивы**: `entity_card`, `card_grid`, `hero_cover_block`, `section_bar`, `day_header_bar`, `region_titler`, `warning_box`, `warning_box_bullets`, `info_box`, `data_table`, `key_params_table`, `bullet_list`, `definition_list`, outline через `BookmarkedDocTemplate`. Полный API — `pdf-visual-language.md §1`. |
| `style.py` | Константы: `COLORS`, `FONTS`, `LAYOUT`, `ROLE_BADGES`, `REGION_PALETTE`, `ICON_MAP`, `TAG_ICONS`, `SIMILARITY_CARD_COLORS`. Единый источник цветов/шрифтов/размеров. |
| `cover_common.py` | Единый «паспорт поездки» для шапок всех стадий: `passport_rows(...)` (порядок Кто едет → Регионы/Маршрут → Сезон → Длительность → Темп → Бюджет) + `profile_name`. Каждая стадия зовёт его и добавляет свой стадийный блок. |
| `file_naming.py` | Конвенции имён: `build_export_filename`, `build_final_plan_filename` (Stage 5), `build_final_filename` (Stage 6, описание `финал`), `build_variants_filename`, `build_scope_filename`, `build_trip_doc_filename` (универсальный с `version=None` для не-versioned стадий). |
| `polish_check.py` | Sanity-check polish-step'а. **Stage-aware** через `STAGE_PROFILES` dict (`0_scope` / `1_dr_reports` / `2_similarity` / `3_poi_aggregation` / `4_variants` / `5_final_plan` / `6_final`). Каждая новая стадия должна добавить свой профиль (см. §2.5). |
| `scripts/geocode.py` | **Tier-1 геокодер контент-стадии Stage 6** (вне `export/`, в `scripts/`): имена точек маршрута → координаты из забандленного `scripts/data/gazetteer.json` (транслит / alias / fuzzy). Авторитет координаты — газетир, не модель. Ненайденное → Tier-2 (модель). stdlib only. |
| `polish_check.py` (CLI) | `python3 polish_check.py --source raw.md --polished polished.md` — exit 0 / 1. |
| `md_to_html.py` | Утилиты markdown→HTML (используется в parser/adapter). |
| `stages/__init__.py` | Подтягивает все stage-модули → их `register_renderer()` отрабатывает. |
| `stages/stage{N}.py` | Stage-specific extractor + builder. **`stages/stage0.py` — эталонный образец cards-стадии.** |

### 0.5 Тесты (фикстуры + регрессии)

Все пути относительно `skills/travel-planning/`.

| Файл | Покрытие |
|---|---|
| `tests/test_export_stage0.py` | Stage 0: polish-маркеры, role helpers, body extraction (incl. «Что увидишь» bullets), cleanup helpers, страна_г_1 fixture, cover helpers, season chip, card grouping, file_naming, build_pdf smoke, CLI integration (102 проверки). |
| `tests/test_export_stage2.py` | Stage 2: parse_components (обе формы / `→` / `->` / null / перенос), заголовки авторов, extract_content на 5 фикстурах (counts == YAML, contrib-сумма == score), distribution/warnings/SIGNAL, edge HIGH=0, file_naming, build_html (DATA-валидность, HAS_PRACTICAL toggle), enrich_with_practical, build_pdf smoke, CLI pdf+html (90 проверок). |
| `tests/test_export_stage4.py` | Stage 4: md helpers, extract_content, варианты, сравнительная таблица, линкификация, cover helpers, build_pdf, CLI integration (68 проверок). |
| `tests/test_export_stage5.py` | Stage 5: day-block parsing, иконки, TODO, build_pdf, CLI integration (119 проверок). |
| `tests/test_export_stage6.py` | Stage 6: parse_coords_section (таблица/маршрут/рёбра/типы/fallback), build_route_spec, extract_content, extract_route_spec (гео:-fallback), _load_source_plan, render_route_map (matplotlib), build_pdf self/parents/no-coords, backward-compat stage5 без inject, render_stage6 entry-point, CLI (67 проверок). |
| `tests/test_geocode.py` | Stage 6 Tier-1 геокодер: normalize/translit, resolve_countries, калибровочные города ✓, деревни → Tier-2, en-подсказка, country-override, CLI (43 проверки, stdlib). |

**Запуск всех:**
```bash
/usr/bin/python3 skills/travel-planning/tests/test_export_stage0.py
/usr/bin/python3 skills/travel-planning/tests/test_export_stage4.py
/usr/bin/python3 skills/travel-planning/tests/test_export_stage5.py
/usr/bin/python3 skills/travel-planning/tests/test_export_stage6.py
/usr/bin/python3 skills/travel-planning/tests/test_geocode.py
```

### 0.6 Fixtures (тестовые поездки)

Все пути относительно `docs/travel-planning/`.

| Папка | Описание |
|---|---|
| `страна Б/` | Полный pipeline Stage 0-5 (build phase, retrospective). |
| `страна А/` | Полный pipeline Stage 0-5 (validate phase, retro-валидация Страна А). |
| `страна В/` | Stage 0-5 (валидационный кейс). |
| `страна_г_0/` | Калибровочный тест Stage 0 v1 (один артефакт). |
| `страна_г_1/` | Калибровочный тест Stage 0 v2 (Страна Г+Страна Г). **Эталонная фикстура для Stage 0 PDF тестов.** |

### 0.7 Связанные spec'и (storage и наименования)

| Файл | Назначение |
|---|---|
| `skills/travel-planning/references/storage-and-naming.md` | Единственная спецификация хранилища: резолв `{travel_root}`, структура `trips/{trip_id}/`, YAML-frontmatter per stage, операции чтения/записи. **Транспорт менять только здесь.** |

---

## 0.5 Update discipline

**Правило:** любое изменение/добавление в экспорте должно отразиться в
**этом файле и связанных** — иначе «карта документации» рассыхается, и
новая сессия начинает переоткрывать паттерны.

### При **добавлении нового рендеримого stage** (Stage 1 PDF, Stage 3 DOCX, …)

См. полный чек-лист в `pdf-visual-language.md §12`. Минимум:

1. Создать `references/stage{N}/stage{N}-polish-prompt.md`.
2. Добавить `_PROFILE_STAGE{N}` в `polish_check.py:STAGE_PROFILES`.
3. Создать `scripts/export/stages/stage{N}.py` (extractor + builder + `register_renderer`).
4. Импортировать в `scripts/export/stages/__init__.py`.
5. Добавить ветку `args.stage == "{N}"` в `export.py:cmd_export` + `DEFAULT_FORMAT["{N}"]`.
6. Создать `tests/test_export_stage{N}.py`.
7. Добавить «§X. Применение к Stage N» в `pdf-visual-language.md`.
8. Добавить «Поток для Stage N» в `references/export/export-modes.md`.
9. Добавить запись в `docs/travel-planning/changelog.md`.
10. Обновить таблицы в **этом файле**: §0.3 (per-stage контракты), §0.5 (тесты).

### При **изменении визуального стиля** (новый цвет, новый шрифт, новый компонент)

1. Менять только `style.py` (константы) или `pdf_lib.py` (компоненты).
2. Документировать в `pdf-visual-language.md`:
   - новые цвета → §2 (палитра);
   - новые шрифты → §3;
   - новые компоненты → §1 (API) + §6 (компоненты контента).
3. Если новый компонент общего назначения — добавить в §11 (дизайн-паттерны).
4. Запись в `changelog.md` (если значимое).

### При **изменении polish-flow** (новая трансформация, изменение маркера)

1. Менять polish-prompt стадии в `references/stage{N}/stage{N}-polish-prompt.md`.
2. Если меняется протокол маркеров (`[[поездка: …]]`, `[[регион: …]]`) —
   обновить parser в `stages/stage{N}.py`.
3. Если меняется H2/счёт секций — обновить tolerance в
   `_PROFILE_STAGE{N}` в `polish_check.py`.
4. Обновить тесты `tests/test_export_stage{N}.py`.
5. Запись в `changelog.md`.

### При **изменении конвенций имён** (новый pattern имени файла)

1. Менять только `file_naming.py`.
2. Если меняется структура `{trip_id}_*.{ext}` — отразить в
   `pdf-visual-language.md §7`.
3. Обновить `export.py:cmd_export` ветки.
4. Если меняется storage layout — отразить в
   `skills/travel-planning/references/storage-and-naming.md §4`.
5. Обновить тесты.

### При **расхождении плана с реализацией**

Если в этом файле (export-design.md) старый раздел описывает решение,
от которого мы отказались — **не редактировать раздел inline**, а:

1. Добавить запись в **Changelog** в конце файла с пометкой «расхождение
   с §X».
2. В шапке файла (после статуса) обновить список «Не доверять устаревшим
   разделам» — добавить ссылку на устаревший раздел.

Это сохраняет историческую traceability (почему было так, почему стало
иначе) и одновременно не вводит в заблуждение.

### Self-check перед коммитом изменений в экспорте

- [ ] Файл, который я меняю, есть в карте §0?
- [ ] Если нет — добавил его в §0 (в правильный слой)?
- [ ] Если новая стадия / компонент / cleanup-helper — обновил
      `pdf-visual-language.md`?
- [ ] Если меняется polish/sanity — обновил соответствующий
      polish-prompt + `_PROFILE_STAGE{N}`?
- [ ] Запись в `changelog.md` есть?
- [ ] Тесты проходят?

---

**Версия 2** — обновлено 2026-05-27 после уточнений пользователя:
- Round-trip (DOCX → md update) **обязателен в Phase A**, не Phase D
- Stage 0 PDF должен быть **presentation-quality**, не «report-style»
- Test data: **Страна Б** (полный pipeline pre-existing) для имплементации;
  **Страна А** для последующей валидации output'а
- Design agent отсутствует — используем web-research реальных
  travel-itinerary PDF на implementation phase

---

## 1. Цель Export

Export — **finalizer pipeline**: превращает stage-артефакты из
working-format (md + YAML) в **presentation-grade output** для:

1. **Удобного человеческого чтения** — md плохо читаем для длинных
   планов; нужны нормальные форматы (PDF / DOCX).
2. **Получателей** — путешественник часто планирует не один. Партнёр,
   родители, друзья, гид — все могут получить **адаптированную** версию.
3. **Архива** — путешествие закончилось, нужен permanent record.

**Принцип:** export запускается **по запросу пользователя**, не
автоматически после каждой стадии.

---

## 2. Формат за stage

Карта `stage → формат → use case`:

| Stage | Формат | Тип использования | Round-trip (import обратно)? |
|---|---|---|---|
| **Stage 0** (region scope) | **PDF (presentation-grade)** | Презентация regional landscape, coffee-table book style | **НЕТ** — read-only, decisions deferred to Stage 3 tagging |
| **Stage 1** (DR reports) | **PDF** | Простое структурированное представление DR-отчётов | НЕТ |
| **Stage 2** (similarity filter) | **SKIP** | Не экспортируется | — |
| **Stage 3** (POI aggregation) | **DOCX** | Editable, теги регионов + per-POI комментарии | **ДА — critical** Phase A feature |
| **Stage 4** (route variants) | **DOCX** | Editable, выбор варианта + комментарии | **ДА — critical** Phase A feature |
| **Stage 5** (final plan) | **PDF** | Read-only финальный план | НЕТ (revision через чат) |

### Round-trip — обязательный workflow для Stage 3/4

После уточнения от пользователя (2026-05-27) — round-trip **не v2
feature**, а **обязательная часть Phase A**.

**Pipeline:**

```
stage3.md (skill output)
    ↓ EXPORT
stage3_export_self_YYYYMMDD.docx (user или другой человек редактирует)
    ↓ user заполнил теги + комментарии в Word form fields
    ↓ IMPORT (upload DOCX в чат ИЛИ paste md-content из save-as)
stage3.md (updated с пользовательскими тегами + комментариями)
    ↓
Stage 4 pipeline продолжается
```

Без работающего round-trip Stage 3 DOCX **бесполезен** — комментарии
никуда не уходят. То же для Stage 4.

**Два пути import обратно** (поддержать оба):

1. **DOCX upload back** — пользователь загружает заполненный
   `*.docx` файл в чат. Скрипт парсит form fields через
   `python-docx`, апдейтит соответствующий md-файл с user_comments
   и tags. **Primary path.**

2. **MD text paste** — пользователь сохранил DOCX как md (Word
   Save-as) ИЛИ другой человек прислал текстом, и user копирует в
   чат. Скилл парсит md, извлекает изменения. **Fallback path** для
   случаев когда другой человек не имеет Word, прислал текст и т.п.

### 2.5 Polish и sanity-check — per-stage обязательность

**Правило:** каждая стадия, у которой есть PDF/DOCX-рендер, **обязана**
иметь свой polish-prompt и свой профиль в `polish_check.py`.

Без них экспорт работает только в `--no-polish` режиме — то есть отдаёт
сырой технический артефакт без презентационной обработки.

#### Per-stage polish-prompt

**Где:** `skills/travel-planning/references/stage{N}/stage{N}-polish-prompt.md`.

**Что описывает:**
- Stage-специфичные трансформации T1, T2, … применяемые моделью к
  raw `{N}_*.md` перед рендером.
- Какие YAML-поля сохранять дословно (контракт с downstream-парсером).
- Какие H2-секции переименовывать / удалять.
- Какие polish-маркеры вставлять (например, `[[поездка: …]]`,
  `[[регион: …]]`) — это канонический протокол передачи параметров
  из polish-LLM в детерминированный builder.
- Чек-лист перед сдачей (что НЕ должно остаться в polished-output'е).

**Без polish-prompt'а** stage-builder получает сырой md с pipeline-
жаргоном («Stage N v2 — …», backtick'нутые YAML-ссылки, «Следующий
шаг») в видимых местах PDF. Builder может частично это вычищать
(`_strip_yaml_jargon` в Stage 0 — пример страховки), но это не заменяет
polish.

#### Per-stage профиль в `polish_check.py`

**Где:** `STAGE_PROFILES` dict в `scripts/export/polish_check.py`,
ключ — значение `stage:` из YAML (`0_scope`, `4_variants`, `5_final_plan`).

**Что описывает:**
- `tolerance` — допустимые отклонения по длине, числу H2/H3/checkbox'ов/
  таблиц. У каждой стадии своя структура → свои допуски.
- `h2_synonyms` — карта канон → синонимы для переименований T5.
- `h2_prefix_match` — для стадий, где H2 содержат счётчики/суффиксы
  (Stage 0: «Region universe (18)» ≡ «Region universe»).
- `allowed_added_h2` — секции, которые polish ИМЕЕТ ПРАВО добавить
  (например, Stage 5 T9c добавляет «Регионы маршрута»).
- `allowed_removed_h2` — секции, которые polish ИМЕЕТ ПРАВО удалить
  (например, Stage 0 T4 удаляет «Следующий шаг» — pipeline-жаргон).
- `context_removable` — флаг «Контекст для следующих стадий» может
  быть удалён (Stage 5 T6).

**Без stage-профиля** polish_check фолбэчит на `DEFAULT_PROFILE`
(Stage 5) и выдаёт false-positives — пропавшие H2 / лишняя длина / не
тот счёт H3. Это блокирует автоматический flow и заставляет полишера
обходить sanity-check.

#### Чек-лист при добавлении нового рендеримого stage

1. `references/stage{N}/stage{N}-polish-prompt.md` — написан, описывает
   T1+ трансформации и обязательный чек-лист.
2. `STAGE_PROFILES["{N}_*"]` в `polish_check.py` — добавлен с
   корректными tolerance / synonyms / allowed_*.
3. `references/export/export-modes.md` — добавлена «Поток для Stage N»
   ветка (имя polish-prompt, имя файла, page orientation, особенности).
4. Тест polish_check на тождественной паре `source ≡ polished` для
   stage'а — должен возвращать OK без warnings.
5. (Опц.) Тест polish_check на реальной polished-версии стадии —
   должен возвращать OK с допустимыми warnings.

Стадии без рендера (Stage 2 — skip) полишер не нуждается.

---

### Логика выбора формата

- **PDF** — read-only, presentation-grade, фиксированное оформление.
  Подходит для финальных артефактов и презентационных промежуточных.
- **DOCX** — editable, поддерживает inline-комментарии (Word review
  features). Подходит для стадий с user decisions.
- **md → PDF/DOCX** — конвертация с фиксированным шаблоном (см. §5).

### Почему Stage 5 = PDF, не DOCX

Финальный план **не предназначен для inline-комментариев**. Если он не
устраивает → возвращение на Stage 4 (выбор другого варианта) или Stage 5
(точечные правки) **через чат**, не через файл. Файл — final
presentation product.

---

## 3. Recipient modes

### v1 — `self` (для меня)

**Целевая аудитория:** сам пользователь.

**Что включать:**
- Все TODO маркеры (видны для верификации перед бронированием)
- Warnings stage'а (включая internal calibration warnings — пользователь их понимает)
- Tag_parse_warnings (важно знать, как теги интерпретированы)
- User comments stage 3 (мои собственные заметки)
- Полные red_flags блоки
- Risk-таблицы и swap-стратегии
- `international_flight_context` блок (видеть Day 1 choreography)
- `iconic_status` маркеры (видеть почему категории такие)

**Что НЕ включать (даже для self):**
- Raw YAML frontmatter (избыточен, internal metadata)
- Stage 2 шум (similarity scores авторов — irrelevant в Stage 3+)
- `_log` / `_diagnostic` artefact'ы

### v2 — `родители` (future)

**Целевая аудитория:** родители путешественника, которые волнуются.

**Что включать:**
- Финальный план (Day-by-day только)
- Конкретные адреса отелей с phone
- Транспортные сегменты с часами
- Контакты экстренной связи (если есть в плане)
- Краткий budget summary

**Что НЕ включать:**
- TODO markers (выглядят как «не финально», пугают)
- Warnings (волнуются без причины)
- Risk-таблицы (только tact essential safety info, без alarmist tone)
- User comments stage 3 (личное)
- Контекстные пояснения для следующих стадий
- Diff с предыдущим планом

**Тональность:** информативная, не «черновик в работе». Финальная,
успокаивающая.

### TBD modes

| Mode | Use case | Когда добавить |
|---|---|---|
| `партнёр` | Co-traveler — нужен полный план + комментарии | Когда появится реальный кейс |
| `друзья` | Sharing trip plan for inspiration — sanitize personal | Если будет запрос |
| `гид` | Local guide получает план для координации | Если будет реальный кейс |
| `архив` | Post-trip permanent record — verbose | После первой удачной поездки через скилл |

**Принцип:** не добавлять режимы превентивно. Только когда есть
реальный use case → spec прорабатывается.

---

## 4. Adaptation rules per stage

### Stage 0 PDF (self) — presentation-quality, LANDSCAPE

**Дизайн-цель:** **coffee-table book pages, presentation-style**, не
«report-style». Stage 0 — это **первая презентация поездки** перед тем
как запускать DR. Должен мотивировать, давать чувство **«вот моя
поездка»**.

**Page orientation: landscape (A4 horizontal, 297 × 210 mm).**

Landscape выбран сознательно — Stage 0 PDF естественно ложится в
presentation-style flow (как slides), wider canvas позволяет
размещать region cards рядом друг с другом, лучше читается на экранах
(большинство landscape).

**Структура:**

1. **Cover page** — full-page hero (landscape)
   - Hero-typography с trip title слева, метаданные справа
   - Даты + длительность + сезон в боковой колонке
   - Travelers profile (1 line: «соло, 37, balanced темп»)
   - **Visual:** spacious layout, минимум текста, чувство journal-cover

2. **Trip overview** (1 page landscape)
   - Тематическая сводка: что за поездка (multi-region tour /
     single-base / explicit list)
   - Tempo (с visual marker: slow / balanced / active)
   - Roadmap visualisation: 18 ночей / N регионов
     - Если ≤6 регионов — horizontal timeline во всю ширину страницы
     - Если больше — split в две row'и

3. **Regional universe — карточки регионов** (landscape позволяет
   **2-3 cards на страницу**)
   - Каждый регион = **card** размером ~120×100 mm:
     - **Role badge** (Core / Supporting / Niche / Borderline) с
       цветным маркером
     - **Density indicator** (HIGH/MED/LOW) как bar или иконка
     - **Nights range** (min/optimum) визуально, как range slider
     - **1-paragraph description** (compelling, не technical)
     - **Сезон в окне поездки** (один маркер: ok / risk / blocked)
     - **Ключевые ограничения** одной строкой
   - **Группировка cards** по role: сначала Core (4 card → 2 страницы по
     2 card каждая), потом Supporting (3), потом Niche (3), потом
     Borderline (1)
   - **Reserve-пары** — соединены визуально (стрелка или общая
     полоса между двумя cards, легко делается в landscape)

4. **Excluded regions** (1 page)
   - Компактный список: regions + reason почему отброшены
   - Honest transparency — почему не Тэгу, не Чолла-Намдо, не Уллындо
   - Visual: tasteful strikethrough на названиях, плюс короткое
     обоснование

5. **Tempo + Math summary** (1 page)
   - Tempo (balanced / slow / active)
   - Math: «18 ночей × X регионов = ~Y ночей/регион»
   - Country quota visualisation (если multi-country)

6. **Honest assessment** (1-2 pages)
   - Главные тредофы Stage 4
   - Ключевые развилки (reserve-пары визуализированы)
   - Open questions ahead

7. **Закрывающая страница** (1 page)
   - «Что дальше» — короткая ремарка про Stage 1 DR collection
   - Logo / footer travel-planning v0.X

**Visual style requirements:**

- **Cards:** consistent layout, не tightly-packed. Pусто пространство —
  ценность.
- **Цвета по role:**
  - Core: deep blue (#1a3a5c) — primary
  - Supporting: warm sand (#d4a574) — secondary
  - Niche: muted purple (#7c3aed) — тematic
  - Borderline: amber (#d97706) — caution
- **Иконки role** — distinct shapes:
  - Core: filled circle
  - Supporting: outline circle
  - Niche: filled diamond
  - Borderline: dashed circle
- **Page breaks:** каждая логическая секция начинается с новой
  страницы (Cover / Overview / Cards / Excluded / Tempo / Honest /
  Closing). Internal flow внутри секции — continuous.

**Зачем такая сложность для Stage 0:**

Stage 0 — это **первое впечатление** от плана. Если пользователь решит
поделиться с попутчиком ДО запуска DR — Stage 0 PDF должен производить
впечатление полноценной презентации, не сырого черновика. Это
**marketing-уровневая презентация** маршрута в зачатии.

**Источник данных:** markdown body `0_scope.md` секции `## Region
universe`, `## Excluded regions`, `## Tempo + country quota`,
`## Honest assessment`. YAML — для metadata в header (даты, профиль).

**Open question (resolved):** карты регионов в v1 не делаем (см. Q4).
Iconography + цветовое кодирование compensates за отсутствие карт.

### Stage 1 PDF (self)

**Структура:**

1. **Cover page** — Trip ID + DR run date + reports count
2. **DR prompt** — собранный промт (для воспроизводимости)
3. **Reports summary** — list of authors with 1-line characterization
4. **Per-author cards** — 20 полей каждой DR-карточки в удобном layout
5. **META-DIAGNOSTICS** — coverage stats, language coverage,
   geographic coverage

**Visual:** простой, читабельный. Иконки по languages источников.

**Источник данных:** `1_dr_reports.md` markdown body.

### Stage 3 DOCX (self)

**Структура:**

1. **Cover page** — Trip ID + Stage 3 metadata
2. **Контекст для следующих стадий** — Контекст-секция from md
3. **Распределение по категориям** — таблица
4. **Warnings** — внятный список
5. **Полная агрегация POI** — region-grouped (per §8 spec):
   - Заголовок региона **с editable полем `тег: ___`** (Word inline form field)
   - Описание региона из Stage 0 (passthrough per F-58)
   - Режим категоризации региона
   - Cluster блоки (если есть)
   - Для каждого POI:
     - Counts + категория
     - Выдержки
     - Характеристики
     - Combined with / Iconic exception / Cluster / Trap archetype / Iconic status (если флаги активны)
     - **Editable «Комментарий пользователя» поле** (Word inline form field)
6. **Non-mainstream highlights**

**DOCX specifics:**
- Inline form fields — Word controls для tag и comment. Пользователь
  пишет в них в Word, документ сохраняет.
- Headings styled — H1/H2/H3 для navigability через Word outline
- Stage 3 → Stage 4 touchpoint: после ручного редактирования
  пользователь export DOCX обратно в md (через Word save-as) ИЛИ
  загружает обратно в чат, скилл сам распарсит — TBD механика
  (см. Open Question #5)

**Tags resolution** теперь работает на DOCX form fields, не на md
строках — нужна совместимая логика парсинга при возврате в pipeline.

### Stage 4 DOCX (self)

**Структура:**

1. **Cover page** — Trip ID + iteration N + Stage 4 metadata
2. **Контекст для следующих стадий** — секция from md
3. **Tags resolution** — какие теги распарсены
4. **Сравнение с v{N-1}** — если итерация > 1
5. **Для каждого variant (A/B/C):**
   - Заголовок + title
   - Регионы + ночи + темп + cost rank
   - Транспортная таблица (DOCX table)
   - Sacrifices list
   - Flavor (Day 1 / Day N)
   - RED FLAG / CONTESTED
   - Honest
6. **Сравнительная таблица** — DOCX table с осями
7. **CONTESTED решения**
8. **Что НЕ вошло ни в один variant**
9. **Honest assessment**
10. **Editable «Решение» секция** — Word inline form field для выбора
    варианта + точечных правок

**DOCX specifics:**
- Сравнительные таблицы — нативные DOCX tables, не md
- Form field в `## Решение` для выбора A/B/C/кастомный + комментарий
- При возврате в pipeline — парсинг form field обратно в md

### Stage 5 PDF (self)

**Структура:**

1. **Cover page** — Trip ID + dates + final plan
2. **Контекст и ключевые параметры**
3. **Шапка** — паспорт поездки
4. **Критические подготовительные пункты** — visa, K-ETA, бронирования
   с deadline'ами
5. **Маршрут по дням** — каждый день по шаблону §6.3 spec'а:
   - Header с датой + day name
   - 📍 Локация / переезд
   - 🏨 Отель (если новый блок) — с TODO маркером
   - 🎯 Программа (часы + активности + адреса)
   - 💰 Бюджет
   - ⚠️ Риски
6. **Сводные таблицы** — Транспорт / Бюджет
7. **Гастрономия** — шпаргалка по городам
8. **План реагирования на риски**
9. **TODO для верификации** — full TODO list

**PDF specifics:**
- Иконки 📍 🏨 🎯 💰 ⚠️ как реальные image icons (не emoji в тексте) для
  лучшего рендера
- **Дни — continuous flow** (один за другим, без page break между
  днями). Per Q2 resolution.
- **Page break на каждой большой секции:**
  - Cover page → новая страница
  - Контекст и ключевые параметры → новая страница
  - Шапка (паспорт поездки) → новая страница
  - Критические подготовительные пункты → новая страница
  - Маршрут по дням (header) → новая страница; дни continuous внутри
  - Сводные таблицы → новая страница
  - Гастрономия → новая страница
  - План реагирования на риски → новая страница
  - TODO для верификации → новая страница
- TODO маркеры — выделены цветом (yellow/orange highlight)
- Warnings — выделены красным с иконкой
- Pages limit — нет, plan может быть длинный

### Stage 5 PDF (родители)

**Sanitization rules:**

- Убрать все TODO маркеры (или заменить на финальные значения если они
  верифицированы — но это work для Stage 5 update, не для Export)
- Убрать «План реагирования на риски» (или upbeat-версия с
  «у нас есть запасной план если...»)
- Убрать warnings и tag_parse_warnings
- Убрать internal "Контекст для следующих стадий"
- Убрать «TODO для верификации»
- Оставить адреса отелей, транспорт, день-по-дню, бюджет summary
- Заменить «верифицировать на Booking» на просто диапазон цены

---

## 5. Visual style / template (fixed)

### Фиксируем для всего скилла

**Цветовая палитра:**
- Primary: deep blue (#1a3a5c) — заголовки, accent
- Secondary: warm sand (#d4a574) — для иконок и highlight
- Warning: amber (#d97706)
- Danger / Red flag: deep red (#b91c1c)
- Text: dark grey (#1f2937), не pure black
- Backgrounds: cream (#fefcf7) для PDF — спокойнее чем white

**Шрифты:**
- Headings: serif (например, Source Serif Pro) — solid, не игрушечный
- Body: sans-serif (например, Inter или Source Sans) — читабельный
- Code / inline tech: monospace (например, Source Code Pro) — для
  iconic_status / archetype / адресов URL

**Layout:**
- Margins: 2cm everywhere
- Line height: 1.5 для body
- Cover page: full-page hero с trip title + dates + traveler

**Иконки:**
- Используется core icon library (Lucide / Material Icons / etc.) —
  TBD при реализации
- Mapping spec'а:
  - 📍 → location pin
  - 🏨 → bed / hotel
  - 🎯 → target / activity
  - 💰 → wallet / coin
  - ⚠️ → warning triangle
  - Tag values (обязательно / можно / не интересно) → check / question / x icons

### Шаблон зафиксирован, content гибок

Это **критический принцип:**

- **Visual style + structure of output** = фиксированы для всех стадий
  и всех поездок. Никакой кастомизации per-trip.
- **Content extracted from stage files** = гибок, эволюционирует со
  спекой стадий.

Это значит: когда spec Stage 3 эволюционирует (например, добавляется
новый флаг `trap_archetype` как в F-55) — **Export реализация не
переписывается**. Просто реализация ищет в input новый блок и
рендерит его в фиксированный template-слот «special flags».

---

## 6. Flexibility: schema evolution

### Принципы

Stages эволюционируют — добавляются YAML-поля, новые секции, новые
warnings. Export должен handling это **gracefully**.

**Правила парсинга:**

1. **Markdown body — primary source.** Извлекать секции по
   `## Header` patterns. Stable across schema evolution.

2. **YAML — only structural metadata.** Использовать только хорошо
   известные стабильные поля: `trip_id`, `stage`, `schema_version`,
   `created`, `duration_nights`. Новые поля (`trap_archetype`,
   `iconic_status` etc.) — gracefully ignore если не используются
   в текущей реализации Export'а.

3. **schema_version awareness.** Stages 3-4 имеют `schema_version: 2`.
   Export ВЕРСИОНИРУЕТСЯ — `export_v1` понимает `schema_version: 2`
   stages. Если в будущем появится `schema_version: 3` — Export v1
   эмитит warning «новая схема, реализация может быть incomplete» и
   попытается работать.

4. **Missing fields = warning, не crash.** Если ожидаемая секция
   отсутствует — пропустить с warning, не падать.

5. **Unknown fields = ignore.** Новые YAML-поля или markdown секции,
   которые Export не знает — игнорировать silently.

### Что это означает на практике

Когда мы добавили F-55 `trap_archetype` — Export реализация **не
требует** изменений. Поле либо игнорируется (если нет специального
рендера), либо рендерится через generic «special flags» slot.

Когда добавим F-59 (expectation calibration block) — Export может
изначально его игнорировать, потом добавить отдельный рендер для этого
типа контента в template.

**Тогда зачем дизайн-документ упоминает конкретные флаги (F-55, F-56v2,
F-57, F-61, F-62v4)?** Чтобы реализация v1 их **рендерила правильно**
— это known flags на момент дизайна. Для будущих флагов после v0.25 —
generic handling.

---

## 7. Critical preserve / strip

### Critical preserve (НИКОГДА не терять)

**Across all stages + recipients:**
- `trip_id` — identifier
- `created` date stamp
- Версия итерации (`v1`, `v2`, etc. в filename)

**Specific stages:**
- Stage 3 → 5 для self:
  - User comments в Stage 3 (in DOCX form fields)
  - Сacrifices с reasons в Stage 4
  - TODO маркеры в Stage 5 (для self)
  - Warnings в Stage 5 (для self)
  - International flight context block info (Day 1/N choreography
    зависит от него)
- Stage 5 self:
  - Полные адреса отелей
  - Полные транспортные сегменты с часами
  - Risk-таблица + swap-стратегии

### Critical strip (НИКОГДА не включать)

**Across all stages + recipients:**
- Raw YAML frontmatter (это internal metadata)
- `_log` / `_diagnostic` blocks
- Stage 2 similarity scores авторов (internal pipeline noise)
- Internal warnings про calibration ("modal деградировал на сложных
  кейсах" — пользователю не нужно)

**Specific per recipient:**
- `родители` mode (per Section 3): TODO, warnings, risks-таблица,
  user comments, контексты для следующих стадий

---

## 8. Workflow: trigger and pipeline

### Trigger

Пользователь **explicitly** запрашивает в чате:

- «Export Stage 0 → PDF» (default self)
- «Export Stage 5 для родителей»
- «Export Stage 4 → DOCX»

Auto-export после каждого stage **не делаем** — пользователь должен
решить когда (а часто stages многоразовые до получения acceptable
результата).

### Pipeline

```
Trigger ("Export Stage X [→ format] [for recipient]")
   ↓
Skill определяет stage from context (latest version если несколько)
   ↓
Skill читает stage file (md + YAML)
   ↓
Skill применяет adaptation rules per recipient
   ↓
Skill рендерит в template (PDF / DOCX)
   ↓
Save: {travel_root}/trips/{trip_id}/export_{stage}_{recipient}_{YYYYMMDD}.{ext}
   ↓
Return: file path в чате + краткое summary
```

### File naming

Формат: `export_{stage_short}_{recipient}_{YYYYMMDD}.{ext}`

Примеры:
- `export_stage0_self_20260527.pdf`
- `export_stage3_self_20260527.docx`
- `export_stage5_parents_20260527.pdf`
- `export_stage4_self_v2_20260527.docx` — для версионированных stages

Папка: рядом с stage-артефактом в `{travel_root}/trips/{trip_id}/`.

### Round-trip (DOCX → md) — **обязательно в Phase A**

Stage 3 + Stage 4 экспортируются в DOCX для редактирования. После
редактирования пользователь возвращает в pipeline.

**Primary path — DOCX upload:**

```
Trigger: пользователь загружает заполненный DOCX в чат
   ↓
Skill идентифицирует stage из имени файла / metadata
   ↓
python-docx читает form fields (тег:___, комментарий:___) + body
   ↓
Skill извлекает diff'ы: что изменилось vs оригинал stage*.md
   ↓
Skill обновляет stage*.md inplace с user_comments и tags
   ↓
Save: stage*.md (updated)
   ↓
Return: «Stage 3 обновлён: M тегов выставлено, N комментариев добавлено»
```

**Fallback path — markdown text paste:**

Другой человек редактирует, потом присылает текст (md или просто
структурированный текст). Пользователь paste'ит в чат. Skill парсит:

- Регулярки на `**тег:** значение` строки
- Регулярки на `6. Комментарий пользователя: текст` строки
- Skill извлекает тот же diff и обновляет md

**Что НЕ делаем в v1:**

- Word "Save as md" — структуру ломает, ненадёжно. Не рекомендуем
  пользователю этот путь. Если он его использует — текст всё равно
  попадёт во fallback path и парсер постарается.

**Edge cases для round-trip:**

1. **Пользователь не заполнил все form fields** — оставлять как было
   в исходном md (пустые теги = `_____` placeholder остаётся).
2. **Пользователь изменил структуру** (удалил POI, добавил новый
   header) — warning «нестандартное изменение, проверь diff», но
   попытаться применить.
3. **Пользователь добавил длинный freeform комментарий** —
   полностью сохраняем в `## Комментарий пользователя` POI. Длина
   не ограничена.
4. **Conflict** — пользователь редактировал DOCX **после** того как
   stage*.md был обновлён в pipeline (например, Stage 4 уже запустился
   на старых тегах) — warning «stage*.md обновлён 2026-XX-XX, твои
   правки могут конфликтовать; продолжить?». Stop до решения.

**Реализация важна именно в Phase A**, потому что без неё DOCX-export
бесполезен — комментарии никуда не уходят и не влияют на pipeline.

---

## 9. Implementation hints

### Реализация — на каких tools

**Core anthropic skills:** `pdf` / `docx` (мы знаем что они есть из
CLAUDE.md контекста — `skills/travel-planning/CLAUDE.md` Section про
Export).

**Python libraries:**
- PDF: **reportlab** (programmatic, fine control over styles) ИЛИ
  **weasyprint** (HTML+CSS → PDF, проще для дизайна, но heavier
  dependency). **Рекомендация — reportlab** для лёгкости, weasyprint
  если нужна сложная вёрстка.
- DOCX: **python-docx** (стандарт, поддерживает form fields)

**Templates:** хранить в `skills/travel-planning/export/templates/`:
- `stage0.pdf.template` — reportlab Python skeleton ИЛИ
  `stage0.html.template` (для weasyprint)
- `stage3.docx.template` — python-docx skeleton with form field markers
- ... etc.

**Adaptation logic** — в `skills/travel-planning/scripts/export.py`:
- `parse_stage_file(path) → dict` — извлекает sections
- `adapt_for_recipient(content, recipient) → dict` — применяет правила
  fill/strip
- `render_pdf(content, template) → bytes` — генерация PDF
- `render_docx(content, template) → bytes` — генерация DOCX
- `cli`: `export.py --stage N --trip TRIP_ID --recipient self`

### Тесты

- Unit-тесты на parsing (`parse_stage_file`)
- Unit-тесты на adaptation (`adapt_for_recipient`)
- Snapshot тесты на template rendering (PDF/DOCX bytes стабильны)
- Integration-тесты на full pipeline для каждого stage

---

## 10. Calibration nuances (lessons learned)

Это **критические нюансы** из истории v0.21-v0.25, которые Export
реализация должна знать:

### Из retro-валидаций Страна А и страна_г_1

1. **User comments — критический сигнал.** Stage 5 включил Чагальчхи
   при `Комментарий: не интересно` (Страна А). F-54 это починил. Export
   для **self** в Stage 3 DOCX должен показать комментарии явно как
   editable fields. Для **родителей** — скрыть.

2. **TODO маркеры стабильно на ценах отелей.** Известный bias моделей
   на underpricing. Export для **self** — preserve TODO с подсветкой.
   Для **родителей** — strip (или заменить, но это работа Stage 5
   update).

3. **Day 1 / Day N choreography (F-61).** При `direct_to_entry == false`
   Day 1 = ground day с light evening anchor. Export Stage 5 PDF
   должен это правильно отрисовать — не «лёгкая прогулка», а
   structured day с явным указанием на transit ≈14-18ч.

4. **`iconic_status` (F-56 v2) tiebreaker.** Категории STRONG могут
   быть auto-elevated. Export показывает финальную категорию, но
   может (для self) сигнализировать «category was elevated from
   WEAK due to iconic status».

5. **`trap_archetype` (F-55).** POI помеченные как известные tourist
   traps. Export для self — явный warning блок «⚠ Tourist-trap
   archetype: {archetype} — {reasoning}». Для родителей — скрыть
   (но если POI вошёл в финальный план — он либо safe (hr≥2), либо
   с user comment, который Export уже учёл).

6. **Версионирование stage 4/5.** `4_variants_v1.md`,
   `5_final_plan_v2.md`. Export читает latest версию по умолчанию;
   опционально пользователь говорит конкретную версию.

7. **Tag_parse_warnings.** Stage 3/4 эмитят warnings про невалидные
   значения тегов. Export для **self** — preserve в верху документа
   (важно знать, как теги интерпретированы). Для **родителей** —
   strip.

8. **CONTESTED решения, RED FLAG блоки.** Stage 3/4 эмитят. Для
   **self** — keep. Для **родителей** — strip risks, keep только
   final decisions без alarmist tone.

### Известные структурные правила

- Stage 5 уже эмитит pre-emit Class B / C / D / E / F / G / P
  warnings. Export должен respect эти классы — не дёргать поля,
  которые помечены TODO discipline.
- Stage 4 markdown — SSOT (F-46). Export читает markdown, не YAML.
  YAML только для metadata (trip_id, dates, schema_version).
- Stage 5 ИКОНКИ в markdown (📍 🏨 🎯 💰 ⚠️) — Export может рендерить
  их как реальные image icons или оставлять emoji. Рекомендация:
  для PDF — image icons (consistency on render); для DOCX —
  emoji (Word does emoji ok).

---

## 11. Open questions — RESOLVED

Все open questions из v1 разрешены в обсуждении 2026-05-27. Решения
зафиксированы ниже.

### Q1: Stage 0 «Решение» секция → **Option A**

Принято как есть. Stage 0 PDF полностью read-only. Decisions deferred
to Stage 3 tagging. Stage 0 — презентация landscape, не requires input.

### Q2: Stage 5 PDF — pages per day vs continuous → **Continuous flow + section breaks**

Дни — continuous flow (один за другим). **Page break** на каждой
большой секции (Cover, Контекст, Шапка, Критические подготовительные
пункты, Маршрут по дням header, Сводные таблицы, Гастрономия, План
реагирования, TODO). Внутри секции — continuous.

### Q3: PDF library → **Use Anthropic core pdf skill**

**Reframed.** Не нужно выбирать reportlab vs weasyprint напрямую —
Anthropic уже имеет **core pdf skill** который делает heavy lifting.
Implementation использует core pdf и core docx skills, мы только
передаём structured input + template.

**Если** core skill окажется недостаточно гибким (нет support
landscape, AcroForms, и т.п.) — fall back на **reportlab** как
secondary option. Reportlab pure-Python, no external dependencies,
runs on Anthropic infrastructure. weasyprint требует Cairo/Pango —
heavier, не делаем.

**Cost minimization:** core skills вызываются standardно, минимальный
custom код вокруг них.

### Q4: Карты регионов / маршрутов → **Skip in v1**

Не делаем карты в v1. Stage 0 PDF — текстовая presentation с
iconography. Карты — open feature для v2 при необходимости.

### Q5: DOCX round-trip → **DOCX upload как primary, md-paste как fallback** (см. §8 redesigned)

Promoted из Phase D в **Phase A**. Реализуем оба пути сразу — без
работающего round-trip Stage 3/4 DOCX бесполезен.

Дополнительно от пользователя: иногда другой человек прислал md-text
ответом — Skill должен парсить и его (через fallback md-paste path).

### Q6: PDF/DOCX templates как файлы → **Отдельные файлы**

В `skills/travel-planning/export/templates/`. Версионируются отдельно
от кода.

### Q7: Auto-cleanup старых exports → **Пользователь сам**

Skill не делает auto-cleanup. Накапливаются по trip_id — пользователь
очищает руками.

### Q8: Поддержка партнёра / друзей / архива → **Не делаем превентивно**

Self + parents покрывают v1/v2. Остальные — когда есть реальный кейс.

---

## 11.5 Дополнительные вопросы из обсуждения v2

### Q9: PDF с form fields для комментариев в Claude.ai чате? → **Не recommended, DOCX лучше**

**Технически возможно:** reportlab/core pdf skill поддерживает
AcroForm fields. Workflow: PDF с form fields → user fills в Reader
→ uploads back → Skill извлекает значения через pypdf.

**Но не выбираем primary path** потому что:
- Word `comments` (review panel) — все привыкли, естественный UX
- AcroForm fields в PDF выглядят как «ячейки», не как комментарии —
  worse UX
- DOCX → md round-trip проще

**Зафиксировано:** DOCX для editable stages (3, 4). PDF AcroForms —
fallback option только если получатель не имеет Word и DOCX не
подходит. Не делаем в v1.

### Q10: Test data для implementation → **Vietnam (build), Korea (validate)**

**Build phase:** использовать пайплайн **Страна Б 2023** (полная
калибровочная база):
- `docs/travel-planning/страна Б/` — все stages
- `vietnam_2023_postmortem_template.md` — постмортем
- Stages 0/1/2/3/4/5 — все есть

**Validate phase:** прогон Export на **Страна А 2024** (свежая retro-валидация):
- `docs/travel-planning/страна А/` — все stages
- Сверка output Export с ожиданиями retrospective_validation

Implementation использует Vietnam files как fixtures для тестов и
итераций. Korea — final acceptance test.

### Q11: Design agent → **Нет специализированного, web research как proxy**

**Нет specialized design agent** в Claude Code.

**На implementation phase используем:**
1. `WebSearch` / `WebFetch` для примеров реальных travel itinerary
   PDF (Wanderlog, TripIt, Tripadvisor templates, travel agency
   PDF examples)
2. `general-purpose` agent для research best practices травел-документов
3. Итеративный рефайн на основе real-world references

Не блокер. Просто медленнее чем «дизайнер сделал и показал».

---

## 12. Development steps — engine first, потом stages независимо

**Philosophy:** сначала движок (общая инфраструктура), потом каждый
stage как **независимый module** на этом движке. После Step 1 каждый
следующий step — самостоятельный, может разрабатываться / тестироваться
изолированно.

**Каждый step заканчивается:**
- working code в `skills/travel-planning/scripts/export/` или templates
- unit tests + integration test на Vietnam fixture
- updated changelog
- demo run на Vietnam → verify output looks acceptable

---

### Step 1 — Export engine (общая инфраструктура) ⚙️ **БЛОКЕР для всех остальных**

**Цель:** generic infrastructure, не привязанная к конкретному stage.
После этого шага каждый stage можно добавлять независимо.

**Что входит:**

- `skills/travel-planning/scripts/export/` директория
- `export.py` CLI entry point с командами:
  ```
  export.py --stage N --trip TRIP_ID --recipient self [--format pdf|docx]
  export.py --import FILE --trip TRIP_ID  # round-trip обратно
  ```
- `parser.py`:
  - `parse_stage_file(path) → dict` — generic md + YAML splitter,
    извлечение секций по `## Header` patterns
  - `parse_docx_for_import(path) → dict` — извлечение form field
    values из заполненного DOCX
  - `parse_md_paste(text) → dict` — fallback для md text paste
- `adapter.py`:
  - `adapt_for_recipient(parsed_content, recipient) → dict` —
    применение правил strip/keep
  - Recipient rule registry (self / parents / TBD)
- `renderer.py`:
  - `render_pdf(content, template_path, output_path)` — wrapper
    над Anthropic core pdf skill
  - `render_docx(content, template_path, output_path)` — wrapper
    над Anthropic core docx skill
- `templates/` директория для template files
- `style.py` — fixed visual style constants (colors, fonts, sizes из §5)
- `file_naming.py` — convention enforcement
- Tests: `test_engine.py` со stub stage file → expected parsed dict;
  verify adapter rules, file naming, etc.

**Что НЕ входит:**
- Любой stage-specific код (это Steps 2+)
- Templates (только директория, не файлы)

**Estimate:** 2-3 часа. **Зависимости:** Anthropic core pdf/docx skills.

---

### Step 2 — Stage 5 PDF (self) 📄

**Цель:** финальный план в presentation-grade PDF (portrait, continuous
days + section breaks).

**Что входит:**

- `templates/stage5_self.pdf.template` — структура из §4 «Stage 5 PDF (self)»
- `stages/stage5.py` — stage-specific parser/adapter logic:
  - Извлечение секций (Cover / Контекст / Шапка / Маршрут по дням /
    Сводные таблицы / etc.)
  - Парсинг dayblock'ов с иконками 📍 🏨 🎯 💰 ⚠️
  - Mapping иконок → image icons
  - TODO маркер highlighting (yellow/orange)
  - Warnings highlighting (red)
- Tests: `test_stage5.py` с Vietnam stage5 fixture
- Demo run: `export.py --stage 5 --trip страна_б_2023 --recipient self`

**Estimate:** 2-3 часа. **Зависимости:** Step 1.

---

### Step 3 — Stage 3 DOCX + round-trip (self) 📝 ⇄

**Цель:** editable DOCX для пользовательских комментариев + import
обратно в stage3.md.

**Что входит:**

- `templates/stage3_self.docx.template` — структура из §4 «Stage 3 DOCX (self)»
  с form fields на:
  - Тег региона (для каждого `### {Регион}` заголовка)
  - Комментарий пользователя (для каждого POI)
- `stages/stage3.py` — stage-specific:
  - Export: парсинг stage3.md → структура с регионами → DOCX
  - Import: parse_docx_for_import → diff vs stage3.md → updated
    stage3.md с пользовательскими тегами и комментариями
  - Conflict detection (если stage3.md обновлён после export — warning)
- Tests:
  - `test_stage3_export.py` — Vietnam fixture → DOCX rendered
  - `test_stage3_import.py` — DOCX with filled fields → updated md
  - `test_stage3_roundtrip.py` — full cycle end-to-end
- Demo run: full export + manual edit + import cycle на Vietnam

**Estimate:** 3-4 часа (round-trip нетривиален). **Зависимости:** Step 1.

---

### Step 4 — Stage 4 DOCX + round-trip (self) 📝 ⇄

**Цель:** editable DOCX для выбора варианта + комментариев + import
обратно.

**Что входит:**

- `templates/stage4_self.docx.template` — структура из §4 «Stage 4 DOCX (self)»
  - Native DOCX tables для transport segments + comparison table
  - Form fields в `## Решение` для выбора A/B/C/кастомный + комментария
- `stages/stage4.py` — stage-specific:
  - Export: парсинг stage4.md → variant cards в DOCX
  - Import: parse_docx_for_import → diff → updated stage4.md с
    `## Решение` block заполненным
  - Versioning awareness (читать latest `*_v{N}.md`, output
    `*_v{N}_export.docx`)
- Tests: аналогично Step 3
- Demo run на Vietnam

**Estimate:** 3-4 часа. **Зависимости:** Step 1.

---

**🏁 PHASE A BOUNDARY — minimum viable Export.**

После Steps 1-4 работающий Export:
- Stage 5 PDF финальный (read-only)
- Stage 3/4 DOCX editable с round-trip

Это **минимум**, после которого Export уже полезен. Стoп можно делать
здесь и валидировать на реальном trip.

---

### Step 5 — Stage 0 PDF (self, LANDSCAPE) 🎨

**Цель:** presentation-quality landscape PDF — coffee-table book pages.

**Что входит:**

- `templates/stage0_self.pdf.template` (landscape A4)
- Web research через `WebSearch`/`WebFetch` — примеры travel itinerary
  presentation PDF (Wanderlog, TripIt, агентств — собрать 5-10
  references перед дизайном)
- `stages/stage0.py` — region cards layout, role color coding,
  reserve-пары visualization
- Tests + Vietnam demo

**Estimate:** 3-4 часа (Stage 0 design intensive из-за visual quality
requirements). **Зависимости:** Step 1.

---

### Step 6 — Stage 1 PDF (self) 📄

**Цель:** simple structured PDF с DR-отчётами.

**Что входит:**

- `templates/stage1_self.pdf.template` (portrait)
- `stages/stage1.py` — per-author cards layout, META-DIAGNOSTICS
  summary
- Tests + Vietnam demo

**Estimate:** 1-2 часа (проще чем Stage 0). **Зависимости:** Step 1.

---

**🏁 PHASE B BOUNDARY — все presentation stages для self.**

---

### Step 7 — Stage 5 PDF (parents) 👨‍👩‍👧 🧓

**Цель:** sanitized version Stage 5 для родителей.

**Что входит:**

- `templates/stage5_parents.pdf.template` — упрощённый, без TODO/
  warnings/risks
- Adapter `recipient: parents` — strip rules per §3
- Tests + demo

**Estimate:** 1-2 часа. **Зависимости:** Step 2.

---

**🏁 PHASE C BOUNDARY — recipient parents added.**

---

### Steps 8+ — Refinements (future)

- **Step 8:** Stage 3/4 parents — если будет use case
- **Step 9:** PDF AcroForm fallback (если кто-то не имеет Word)
- **Step 10:** Map integration (карты регионов в Stage 0)
- **Step 11:** Recipient modes: партнёр, гид, архив (если возникнут)
- **Step 12:** Auto-cleanup (cleanup команда для exports папки)

---

### Сводная таблица

| Step | Component | Phase | Estimate | Блокирующий |
|---|---|---|---|---|
| 1 | Engine (parser/adapter/renderer + templates dir) | A | 2-3ч | Anthropic core skills |
| 2 | Stage 5 PDF self | A | 2-3ч | Step 1 |
| 3 | Stage 3 DOCX + round-trip self | A | 3-4ч | Step 1 |
| 4 | Stage 4 DOCX + round-trip self | A | 3-4ч | Step 1 |
| 5 | Stage 0 PDF landscape self | B | 3-4ч | Step 1 |
| 6 | Stage 1 PDF self | B | 1-2ч | Step 1 |
| 7 | Stage 5 PDF parents | C | 1-2ч | Step 2 |
| 8+ | Refinements | D | TBD | — |

**Total Phase A:** 10-14 часов
**Total Phase A + B:** 14-20 часов
**Total Phase A + B + C:** 15-22 часов

### Параллелизация

После Step 1 — **Steps 2, 3, 4, 5, 6 можно делать параллельно** (или в
любом порядке). Каждый — независимый module на общем движке.

Рекомендую последовательность Step 1 → 2 → 3 → 4 → 5 → 6 → 7
(приоритет по value для пользователя).

---

## 13. Что НЕ обсуждаем в этом документе

- Конкретные строки spec'а для `stage_export.md`
- Точная Python-структура `export.py`
- Конкретный шаблон CSS/HTML или reportlab code

Эти детали — для **implementation сессии**, не дизайн.

---

## Источники

Документ основан на:

- Обсуждения с пользователем 2026-05-27 (export design priorities)
- Файл: `docs/travel-planning/страна А/0_scope_opus.md` (как образец Stage 0 output)
- Spec'и stages: `skills/travel-planning/references/stages/stage0-scope.md`,
  `stage1-dr-prompt.md`, `stage3-poi.md`, `stage4-variants.md`,
  `stage5-final.md`
- Calibration history: `docs/travel-planning/changelog.md` (v0.21-v0.25)
- Retro-валидации: Страна А и страна_г_1 retrospective_validation reports

## Версия документа

v1 — 2026-05-27 — initial design
v2 — 2026-05-27 — после уточнений пользователя:
  - Round-trip (DOCX → md) promoted из Phase D в Phase A (critical)
  - Stage 0 PDF — landscape orientation, presentation-quality
  - Stage 5 PDF — continuous days + page breaks per section
  - PDF library — Anthropic core pdf skill (reportlab fallback)
  - Карты в v1 не делаем
  - Test data: Vietnam build / Korea validate
  - Design agent отсутствует — используем web research
  - Q5/round-trip clarified: DOCX upload primary + md paste fallback
  - PDF AcroForm option отложен (DOCX лучше для editing)
v3 — 2026-05-27 — финализация перед commit:
  - §12 reorganized как **Development steps**: engine first (Step 1),
    потом stages независимо (Steps 2-7)
  - Чёткие границы Phase A/B/C
  - Параллелизация после Step 1 явно прописана

При обновлении документа в будущих сессиях — добавлять секцию
«Changelog» в самый конец, не редактировать предыдущие версии inline.

---

## Changelog

### 2026-05-28 — реализация Engine + Stage 5 PDF; расхождения с планом

Реализованы: export engine (`scripts/export/`), Stage 5 PDF (self +
parents), polish-слой. Калибровка на Страна А и страна_г_1. При реализации часть
решений плана пересмотрена — **актуальная правда в**
`references/export/export-modes.md` и `references/export/pdf-visual-language.md`.

Ключевые расхождения с разделами выше:

- **§2 формат Stage 4.** План: DOCX с round-trip. Решение 2026-05-28:
  Stage 4 = **PDF** (read-only витрина сравнения вариантов; пользователь
  выбирает один в чате, максимум комментарий). Round-trip DOCX —
  отложено/не приоритет. Маппинг Stage 4 на PDF-блоки — в
  `pdf-visual-language.md §9`.
- **§5 фон/шрифты.** Фон — **белый** (не cream). Шрифты — DejaVu (body) +
  Adobe CID-фонт для CJK (не Source Serif/Inter; иконки-эмодзи
  вырезаются, т.к. не поддержаны шрифтом).
- **§8 имена файлов.** Не `export_stageN_recipient_date`, а
  `{trip_id}_план_v{N}.pdf` (страна_год-месяц_план_версия).
- **Q3 PDF library.** Не core pdf skill, а **reportlab напрямую**
  (pure-Python, без native-deps; outline через afterFlowable,
  destination'ы по реальной позиции кадра).
- **Новое (не было в плане):** двухслойный flow polish → sanity-check
  (`polish_check.py`) → render; инференция регионов через polish-маркеры
  `[[регион: …]]`; сводная таблица регионов + titler-блоки;
  валюта-агностичный бюджет; жёсткие правила «не писать свой генератор»
  (`export-modes.md` ⛔-блок).

Что из плана осталось в силе: §1 цель, §3 recipient self/parents, §6
schema-evolution graceful, §7 critical preserve/strip, §10 calibration-
нюансы (user comments, TODO на ценах, day-1 choreography и т.д.).

### 2026-05-29 — реализация Stage 4 PDF (витрина вариантов)

Реализован PDF-экспорт Stage 4 — `stages/stage4.py`, polish-промт
`references/stages/stage4-polish-prompt.md`, тесты
`tests/test_export_stage4.py`. Дизайн — `stage4-pdf-export-plan.md`.
Актуальный визуальный маппинг — `pdf-visual-language.md §9`.

Ключевое:
- Stage 4 = **PDF read-only** витрина сравнения; решение фиксируется в
  чате (блок `## Решение` не рендерится).
- Имя файла: `{trip_id}_варианты_v{N}.pdf` через
  `file_naming.build_variants_filename`.
- Дефолт-формат Stage 4 переключён DOCX→PDF в `export.py`.
- Структура: обложка с trip-маркером параметров (`[[поездка: …]]`) +
  outline-якорь «Обзор» → контекст без дублей → сводная сравнительная
  таблица сверху + навигация → свёрнутый Priority pool → варианты A/B/C
  цветными `section_bar` (REGION_PALETTE, в outline level 0) → Спорные
  решения / Что не вошло → Честная оценка.
- Экстрактор устойчив к двум форматам (новый «Вариант A:» +
  «Сравнительная таблица»; старый «Variant A —» + «Сравнение»).
- Русификация в рендере: колонки сравнения (`Variant X` → `Вариант X`),
  заголовки extras (`CONTESTED` → `Спорные`, `variant` → `вариант`),
  английский «Variant X» в прозе — через линкификацию.
- Кликабельные ссылки «Вариант X» в теле секций и ячейках сравнительной
  таблицы (`_linkify_variants`).
- Расширение `pdf_lib.section_bar` параметром `bg_color` (backward-
  compatible) — для цветовой маркировки вариантов.

### 2026-05-30 — третий раунд ревью Stage 4

После прогона на страна А фикстуре:
- Старт/финиш одной строкой, если города совпадают.
- «Кто едет»: только имя/имена/собирательное название (без «соло»,
  «паспорт») — обновлён polish T2b.
- Линкификация теперь и русифицирует английское «Variant»/«variant» в
  тексте ссылки, а не только оборачивает в `<a>`.

### 2026-05-30 — реализация Stage 1 PDF (DR-база отчётов)

Реализован PDF-экспорт Stage 1 — `stages/stage1.py`, polish-промт
`references/stages/stage1-polish-prompt.md`, профиль в `polish_check.py`,
тесты `tests/test_export_stage1.py` (130 проверок).
Актуальный визуальный маппинг — `pdf-visual-language.md §11a`.
Post-review итерация (cleanup'ы, единый warning_box_bullets,
консолидация warnings polish'ом) — описана в `changelog.md` v0.28.

Ключевые расхождения с разделом **§4 «Stage 1 PDF (self)»** плана:

- **План:** Cover → DR prompt → Reports summary → Per-author cards →
  META-DIAGNOSTICS. **Реализация:** Cover → Сводка META (с coverage-
  таблицей) → Region-grouped cards → Tails (caveats/sources). DR-промт
  на cover не выводится (он одноразовый input, не output); reports
  summary заменена на таблицу покрытия с навигационными ссылками.
- **План:** «Иконки по languages источников.» **Реализация:** языки
  агрегируются в одну строку «RU 22% · EN 78%» в key_params_table cover,
  без per-card иконок (они не помещаются в meta_line).
- **План не упоминал** outline-стратегию для Stage 1. **Решение:**
  плоский outline по карточкам формата «N · Автор — «Название»» (формат
  C2 — без региона в названии, согласовано с пользователем). Регионы —
  visual `section_bar` БЕЗ outline-entry; навигация по регионам через
  cover-таблицу «Покрытие по регионам».
- **План не упоминал** Mode B awd.ru extension. **Реализация:** парсер
  устойчив к Mode B (`sample_curation_note` YAML → info-box на cover;
  orphan cards вне регионов → псевдо-регион «Дополнительные карточки»).
- **План:** «Простой, читабельный.» **Реализация:** portrait A4 с
  drop'ом 5 полей низкого приоритета (6 сезон / 8 возраст / 10 темп /
  16 логистика / 17 диета — согласовано с пользователем) и пустых
  значений — карточки компактны, документ читается. Critical-карточки
  выделены danger-accent + `warning_box` с цитатой жалоб (поле 18).

### 2026-06-01 — реализация Stage 2 export (PDF + HTML), снятие SKIP

**Расхождение с §2 плана:** Stage 2 был помечен `SKIP` (не экспортируется).
Решение 2026-06-01 (пользователь): экспортировать в **оба** формата.

Реализованы: `stages/stage2.py` (общий экстрактор `Stage2Content` +
`build_pdf` + `build_html` + `enrich_with_practical`), HTML-шаблон
`templates/stage2_similarity.html`, polish-промт `stage2-polish-prompt.md`,
профиль `2_similarity` в `polish_check.py`, тесты `test_export_stage2.py`
(90 проверок). Визуальный маппинг — `pdf-visual-language.md §11b`, поток —
`export-modes.md` «Поток для Stage 2».

Ключевое — **осознанная асимметрия форматов под читателя** (а не «оба
одинаковые»):
- **PDF** (default, `DEFAULT_FORMAT["2"]="pdf"`) — статичная scoring-витрина
  по категориям (cover → распределение → warnings → reading list
  карточками → UNSCORED → полная таблица → MEDIUM/LOW компактно).
  **Без практики** — она дублировала бы отдельный Stage 1 PDF.
- **HTML** (`--format html`) — тёмный интерактивный lookup (фильтр/
  сортировка/click-to-expand) с табом «Практика», обогащаемым из
  `1_dr_reports.md` (поля 14/15/18/20, матчинг по URL, graceful
  degradation если Stage 1 нет/не парсится).

Инфраструктура: `renderer.Format += "html"`, `file_naming.VALID_EXTENSIONS
+= "html"` + `build_similarity_filename` (`{trip_id}_фильтр_авторов.{pdf,
html}`), `style.SIMILARITY_CARD_COLORS`, ветка `args.stage=="2"` в
`export.py`.

Экстрактор устойчив к формам реальных артефактов: компонент-строка с
именами и компактная, стрелка `→` и ASCII `->`, null `C6 demo —`, перенос
строки компонентов на 2 физических строки, bold и non-bold заголовки
авторов. Валидировано на 5 фикстурах (страна Б/страна А/страна В/страна_г_0/страна_г_1):
counts == YAML, сумма контрибуций == total_score.

### 2026-06-02 — унификация шапок и имён файлов (все стадии)

После фидбэка по Stage 2 — сквозная правка S0–S5.

- **Имена файлов:** единая схема `{stage}_{trip_id}_{описание}[_v{N}].{ext}`
  (см. `storage-and-naming.md §4.2`). Дата генерации убрана из имени.
  `build_trip_doc_filename` получил параметр `stage`; round-trip import
  (`_identify_import`) переписан под префикс стадии + суффикс-описание,
  совместим со старым форматом. S2 `фильтр_авторов`→`похожие_авторы`,
  S5 `план`→`финальный_план`.
- **Шапки:** новый модуль `scripts/export/cover_common.py` —
  `passport_rows(who, geo, geo_label, season, duration, tempo, budget)`
  даёт единый порядок/метки «паспорта поездки»; каждая стадия зовёт его +
  добавляет свой стадийный блок. S3 убрал `Trip ID`/`Создано`, добавил
  `Кто едет`; S5 добавил `Кто едет`. Темп — S0/4/5, бюджет — S4/5.
- **`pdf_lib.entity_card`** расширен параметром `colored_lines`
  (label+text+цвет) — для цветных «Тянет вверх/вниз» в карточках Stage 2;
  backward-compatible.
- Stage 2 polish по фидбэку: человеко-заголовок, «Кто едет» (имя),
  убраны архетип/веса/пороги, расшифрована «Полнота оценки», info →
  «Примечания», русские имена компонентов, локализация англицизмов.

Все 6 export-сьютов зелёные (567 проверок).

### 2026-06-02 — полиграфические правки по дизайн-ревью Страна А

Точечные правки (без переверстки) по `страна А/страна_а_design_review_external.md`.
Детальный план — `export-polish-plan.md`. Решения пользователя: объём
P1+P2+P3; обложки — асимметрия by design (D2); утечки в прозу — только
polish-промт (D3); H2 — унификация точечно (D4).

**P1 — видимые баги (Python, stage5.py):**
- **Дубль «Программа. Программа»** — хелпер `_strip_leading_label`: срезает
  ведущий bold-токен тела, дублирующий метку-лид маркера дня
  (`**Программа** (…)` → `(…)`). `_BOLD_LABEL_RE` ловил только голую
  `**Label:**`, поэтому не срабатывал.
- **Перенос числа валюты** — хелпер `_nbsp_budget`: nbsp в разрядах +
  en-dash без пробелов; применён ко всем местам рендера бюджета (сводная
  таблица регионов, titler, дневная плашка). Бьёт оба источника строки
  (computed `_region_budget_range` и сырое поле маркера региона).
- Тесты: `test_export_stage5.py` +11 (74) + ☐-регресс (77).

**P1-2 / P2-5b — утечки в прозу (polish-промты, D3):**
- `stage5-polish-prompt.md` T11/T12, `stage4-polish-prompt.md` T8/T9 +
  чек-лист: теги (`обязательно/можно/не интересно/пропуск/can_pool`) →
  человеческий язык; имена YAML-полей и токены стадий в прозе → человеческий
  язык. Python-страховку **не** добавляли (D3).

**P2 — унификация:**
- **Футеры** (P2-1): единый «создан {date}» + «стр. N» во всех стадиях;
  убран breadcrumb-фоллбэк S3 (`_footer_text`).
- **Warnings DOCX** (P2-3): S3 DOCX «Warnings» → «Предупреждения» (PDF уже
  был русифицирован).
- **H2 точечно** (P2-4, D4): S3 «Распределение по категориям»
  `heading_paragraph` → `section_bar` (как S2). Прочие H2 не трогали.
- **Слаги обложки S3** (P2-5a): `_cover_title` фоллбэк «Stage 3 · …» →
  «Агрегация POI»; убрана мёртвая строка с хардкодом «Страна Г+Страна Г».
- **Цвета** (P2-7, style.py): `role_borderline` decoupled от `warning`
  (был ровно `#d97706`) → bronze `#b45309`; задокументирована семантика
  тёплой палитры (amber=warning, sand=supporting, bronze=borderline,
  yellow=TODO, ochre/terracotta=region). **Требует визуальной сверки.**
- **Justify → влево** (P2-8): стиль `body` `TA_JUSTIFY` → `TA_LEFT`
  (ragged-right, убирает «реки»). Единственное вхождение justify.

**P3 — мелочи (pdf_lib/style + stageN):**
- Бейдж роли (P3-9): `fontSize` 8→7 — «SUPPORTING»/«BORDERLINE» не
  влезали в 60pt и ломались.
- Чекбоксы (P3-11): ASCII `[ ]` → глиф ☐/☑ (отмеченные `[x]` теперь ☑);
  глиф подтверждён в DejaVu и Arial Unicode.
- Узкие колонки (P3-12): S1 «Карточек» 13%→16%; S3 coverage — явные
  `col_widths` («Регион» ~26%, числовые узкие).
- Eyebrow дня 7 (P3-14): **no-op** — `day_header_bar` уже форсит
  `region.upper()`, строчным быть не может.
- Хвосты таблиц (P3-13): `keepWithNext=1` на h2/h3/h4 (заголовок не
  страндится). **Балансировка осиротевших 1–2 строк / чеклист-хвостов —
  отложена** (нужна визуальная итерация по многостраничным PDF, см. TODO).

**D2 — обложки:** асимметрия S0 (hero) ↔ S1–S5 (плоские) — осознанное
решение, не баг. Зафиксирована в `pdf-visual-language.md` (факт) и здесь.

Все 6 export-сьютов зелёные (581 проверка). End-to-end рендер Страна А S5/S3
без ошибок; P1-1/P1-3 подтверждены на данных страна А фикстуры.

### 2026-08-03 — навигационный слой TNAV в HTML-экспортах (стадии 0–6)

Дизайн — Claude Design, проект `553ebbf1-cf71-453d-9d71-39b0427aee77`
(`nav-layer.snippet.txt`); реализация — `assets/nav-layer.{css,js}`,
инжектится `html_lib.build_html_document` во все документы, собранные общим
сборщиком. Полное описание слоя — `references/export/html-rendering.md`.

**Зачем.** Оглавления в экспортах не было вообще: единственные якорные ссылки
жили в таблице в начале документа, то есть до них надо было домотать вверх.
Сценарии владельца — «что меня ждёт завтра» с телефона в поездке и «что надо
сделать заранее» до неё — упирались в это напрямую.

**Решения, отличные от макета** (мобильный аудит, скилл `mobile-html`):

- панель — плавающая капсула с подписями в строку и авто-прятаньем при
  прокрутке вниз, а не полноширинный таб-бар в три доли: по таблице
  применимости таб-бар для длинной читальной страницы не показан;
- тач-мишень чекбокса подготовки — 40px невидимой накладкой при визуальных
  19px (пункты отмечают пальцем в поездке);
- scroll-lock под открытой шторкой; `dvh` вместо `vh` (iOS);
- глобальные слушатели вешаются один раз: `boot()` пересобирает меню после
  `load`, и в макете второй `init` удваивал `scroll`/`keydown`;
- ключ отметок — `body[data-tnav-key]` = `trip_id`, а не хеш заголовка:
  у `5_план` и `6_финал` заголовки разные, а чеклист один и тот же;
- переход по меню отключает авто-прятанье на 1,2 с — иначе панель исчезала
  ровно в момент, когда ею только что воспользовались.

**Цена и границы.** +~14 КБ на документ (слой инлайном). Печать не
затронута — PDF со слоем и без совпадает байт в байт. Stage 2 в HTML слоя не
получает: это интерактивный lookup со своим шаблоном и своей навигацией.
Тесты — `test_html_export.py` [17], 34 проверки, включая drift-гард на классы,
которые слой читает из документа.

**Доставка слоя в старые экспорты (2026-08-03).** Пересборка существующих
HTML из `.md` невозможна без потери полиша — полированный вход эфемерный, на
диске остались только сырой `.md` и готовый HTML. Поэтому добавлен
`scripts/export/inject_nav.py`: впрыск слоя в готовый файл, идемпотентный
(повторный прогон = апгрейд слоя), с проверкой обратимости в тестах. Второй
реализации слоя нет — блок из `html_lib.nav_layer()`, даты из общего
`stage5.iso_from_daydates`. Применён к 12 экспортам (Китай, Страна Б; стадия 2
пропущена как интерактивная). Тесты — `test_html_export.py` [18].

**Отметки подготовки → в план (2026-08-03, решение владельца).** Состояние
чеклиста хранится в строке `.md` (`- [x] …`), а не отдельным файлом: тогда
вопрос «как привязать отметку после пересборки» исчезает — галочка едет вместе
со строкой, наследуется следующей версией плана и попадает в PDF. Запись — по
кнопке (не на каждый клик) и только под логином; чтение состояния при открытии
страницы публичное, поэтому отметка, сделанная на компьютере, видна с телефона.
Куда писать — решает содержимое (`prep_sync.resolve_plan_md`), а не имя файла:
у Китая объявленный `source_plan` не совпадает с реальным именем на диске.
Whitelist сайдкара расширен на `trips/*/5_*.md` и `6_*.md`. Реализация —
`scripts/export/prep_sync.py` + `assets/nav-layer.js`; тесты — `[19]` и `[18]`
в `test_html_export.py`, whitelist — в `tools/tests/test_write_api.py`.

### 2026-10-05 — слой в окне кабинета: без темы, статус поездки в рельсе

Кабинет (`travel.html`) открывал стадию боковой панелью 880px — слой в ней
всегда уходил в нижнюю панель (рельсу нужно окно ≥ ~1200px: 1100px и ≥202px
слева от листа 794px). Решение владельца: окно документа по центру, как у
отчётов здоровья, шириной 1280px (`ui-kit` `.ui-docwin`, 1.10.0) — рельс
встаёт слева; уже ~1230px — штатно нижняя панель.

- **Кнопка темы снята** (шторка и рельс): тема и так берётся из кабинета
  (`hub-theme`), а переключатель в iframe перекрашивал только документ.
- **Статус поездки в рельсе.** Контекстная кнопка панели («До старта N дн» /
  «Сегодня») в режиме рельса пропадала — теперь строка под заголовком рельса:
  «До старта · N дн» / «Идёт · день X из Y» (X/Y — по календарю первого и
  последнего дня плана, как `uiTripWhen` по `start`/`end`). В панели у
  «Сегодня» — номер дня `X/Y`.
- **Несохранённые отметки в рельсе.** Кнопки «Сохранить» в рельсе нет; у
  «Заранее» — счётчик несохранённого (оранжевая рамка).
- **Escape по слоям**: открытое меню глав гасит Escape (capture-фаза), иначе
  его ловит кабинет на документе iframe и закрывает окно; в полях ввода
  edit-слоя — нет.
- Выложенные экспорты (Страна Б, Страна Д, Китай — 19 файлов, стадия 2
  пропущена) обновлены `inject_nav.py`; сверка на копиях — вне блока слоя
  меняется только `data-tnav-key` на `<body>`. Попутно: ключ из имени файла
  теперь в NFC (macOS отдаёт NFD — ключ впрыснутого файла не совпадал с ключом
  свежего экспорта). Бэкап — `travel-planner/.nav-layer-backup-2026-10-05/`.
- Тесты: `test_html_export.py` [17]/[18], браузером —
  `tools/tests/test_doc_window.py`.
- **Доводка после просмотра владельцем:** «↑ В начало» под списком глав (как
  `.rd-top` читателя кабинета), подвала у рельса нет — `100vh` + отступы
  выталкивали его за край; рельс `border-box`. Закрытая шторка
  `visibility:hidden` (тень полосой по низу окна). Переход по меню держит
  подсветку на цели (`spyHold`), дальний — мгновенный. Панель «Сохранить»
  Stage 3/4 уважает `hidden`; старые экспорты — `inject_nav.fix_edit_bar`.
  Повторный бэкап — `.nav-layer-backup-2026-10-05b/`.
