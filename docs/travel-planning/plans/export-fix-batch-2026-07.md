# Export fix batch — июль 2026 (PLAN, исполняемый)

Дата: 2026-07-05. Статус: **РЕАЛИЗОВАН (все 4 этапа, 2026-07-05)**. 20 тест-файлов
travel-planning зелёные. Единственное отклонение: задача 3.7 — `parse_export_filename`/
`build_export_filename` НЕ удалены (премиса «мёртвый код» неверна: покрыты
test_export_engine §9/§10, ветка `else` достижима при `--input` без `--stage`);
docstring исправлен, choices pptx/xlsx убраны. Изменения ещё не закоммичены.

Написан как исполняемая спека: задачи с файлами, сигнатурами и критериями
приёмки — чтобы Sonnet/Opus могли реализовать без повторного анализа.
Происхождение находок — Приложение A (каталог) и B (перепроверка на живых
артефактах); зеркало решений — auto-memory `travel-export-fix-batch`.

---

## 0. Инструкция исполнителю (обязательно)

1. Прочитать `docs/travel-planning/CLAUDE.md` (дев-гайд) и перед этапом 4 —
   `docs/travel-planning/format-firewall.md`.
2. Порядок этапов **строгий** (1 → 2 → 3 → 4): дефолт переключается только
   после паритета (решение Р6). Задачи внутри этапа независимы, если не
   указано иное.
3. Line-номера — ориентиры на 2026-07-05; при расхождении искать по
   приведённым сигнатурам/строкам кода.
4. Python для тестов на этой машине: `~/.pyenv/versions/3.12.9/bin/python3`
   (системный python3 сломан). Команды тестов — в конце каждого этапа.
5. Коммиты — группами по смыслу (код / тесты / доки), см. корневой CLAUDE.md.
6. После каждого этапа — синхронизация документации (SKILL.md → references →
   STAGES.md → changelog.md) и отметка в §5 этого файла.
7. В файлы скилла (`skills/travel-planning/**`) не протаскивать дев-материалы
   (ссылки на этот план, «архитектурное решение», changelog) — правило
   дев-гайда.

Ключевые пути (все относительно корня репозитория):
- `EXP = skills/travel-planning/scripts/export`
- `HT = EXP/stages_html` (HTML-ветка), `RL = EXP/stages` (reportlab/DOCX)
- taxonomy: `skills/travel-planning/scripts/taxonomy.py` +
  `skills/travel-planning/scripts/data/taxonomy.json`
- фикстуры: `docs/travel-planning/calibration/страна_г_1/`, `.../страна Б/`;
  живые артефакты: Synology `trips/регион_a_2027/`, `trips/страна_б_2026-09-новый/`
  (входы прогонов: «0 scope.md», «1 dr reports.md», «2 similarity.md»,
  `3_poi_pool.md`; `5_final_plan_v4.md`, `6_final_v1.md`).

## 1. Решения пользователя (контракт; не пересматривать без него)

| # | Решение |
|---|---|
| Р1 | Дефолт-формат — **HTML для всех стадий 0–6, включая Stage 3**. PDF — по явному запросу; DOCX — Stage 3 по явному запросу |
| Р2 | Термины/англицизмы — **единый SSOT `taxonomy.json`** во всех стадиях и обеих ветках; подход описать в доках. `no_translate`: POI, Deep Research |
| Р3 | `§ S0–§ S6` убрать полностью |
| Р4 | Stage 2 `--format html` → **интерактивный lookup**; статическая витрина — только внутренний этап PDF |
| Р5 | Валидация — на **эмите** `.md` (normalize → check_format), не при импорте; валидный YAML чинится в парсере, а не запретом |
| Р6 | Сначала паритет HTML-веток, потом переключение дефолта |
| Р7 | Политика подавления полей — одна на оба движка, эталон — reportlab-ветка |

---

## 2. Этап 1 — полнота и краши HTML-веток

### 1.1 Краш trap_archetype — [x]
`HT/stage3.py:73-75`. Сейчас: `esc(p.trap_archetype)` (dict → AttributeError,
живой краш на Шаолине, Китай stage 3). Эталон: `RL/stage3.py:1555` —
`poi.trap_archetype['archetype']`.
Сделать: `_t = p.trap_archetype; _txt = _t.get("archetype","") if
isinstance(_t, dict) else (_t or "")`; рендерить только если непусто.
Приёмка: тест в `tests/test_html_export.py` — POI с
`trap_archetype={"archetype":"staged_commercial_monastery"}` рендерится без
исключения, строка `tourist-trap:` в HTML.

### 1.2 Обрыв TODO-подсветки на точке — [x]
`EXP/html_lib.py:106`: `_TODO_RE = re.compile(r"(TODO[:：]?[^.<;\n]*)")`.
Живой баг (Страна Б stage 6): `TODO: верифицировать цену на 5–8.09.2026`
подсвечено до «5–8» (капс — CSS `text-transform:uppercase`, не текст).
Сделать: `r"(TODO[:：]?(?:[^.<;\n]|\.(?=\d))*)"` — точка разрешена только
перед цифрой (даты/цены), конец предложения по-прежнему обрывает.
Приёмка: тесты — (а) дата внутри подсветки целиком; (б) регресс: подсветка
не заходит в `<`-теги и обрывается на `.` перед пробелом/буквой.

### 1.3 Stage 1: позиционные поля вместо label-матчинга — [x]
`HT/stage1.py:27-56`. Сейчас `_card_map` строит dict по label и ищет
`m.get("Автор"/"Платформа"/"URL")` — канонические лейблы на самом деле
«URL и название», «Платформа / язык» (`RL/stage1.py:127-129`), а DR пишет
развёрнутые («Имя или ник автора») → в живом прогоне все 30 карточек без
автора/ссылки/платформы.
Сделать: импортировать из `RL/stage1.py` `_fv`, `_extract_author`,
`_extract_url_and_title`; титул карточки — как outline reportlab
(`_card_outline_title`, `RL/stage1.py:1013`): «N · Автор — «Название»»
(без обрезки 90 симв.); платформа — поле 2; URL — из поля 1.
kv-строки: label поля — канон из `_FIELD_NAMES` (`RL/stage1.py:126`),
скрывать поля из `_FIELDS_DROP` (`RL/stage1.py:1229`) и поля 1/2/3/4
(ушли в шапку) — Р7. Дубли/пустые label больше не схлопываются
(позиционный доступ).
Приёмка: тест на карточке с развёрнутыми лейблами и полями-`1.`
(D3-коллизия): титул содержит автора и название, платформа отображена,
поля 6/8/10/16/17 отсутствуют в HTML.

### 1.4 Stage 1: meta-блок и repr-утечка — [x]
`HT/stage1.py:58-75`. Сделать:
- distributions: значения-списки → `", ".join(v)` (сейчас Python-repr);
- добавить рендер `coverage_per_region` (таблица «Покрытие по регионам»,
  эталон `RL/stage1.py:1487-1499`), `covered_regions` карточки (строка
  «Покрывает: …»), `season_caveat`, `sources_outside_seed`,
  `poi_critique_per_region` (эталоны `RL/stage1.py:1383-1565`);
- side-флаги photo/residence/iconic → бейджи (эталон `RL/stage1.py:1311`).
Приёмка: smoke-тест по фикстуре страна_г_1: строки покрытия и season_caveat
присутствуют; `[` из repr списков в kv отсутствует.

### 1.5 Stage 0: потерянные поля — [x]
`HT/stage0.py`. Сделать:
- non_canonical (:131-137): рендерить `nc.interest_match` и статус
  (`status == "in_longlist"` → «уже в лонг-листе»), эталон
  `RL/stage0.py:1287-1292`; `ru()` применять;
- excluded (:120-127): при непустом reason НЕ терять description/bullets
  (reason + description + bullets, эталон `RL/stage0.py:972-979`); пустой
  note не рендерить (guard как у non_canonical);
- description_bullets карточки (:51): рендерить ВСЕ bullets списком, не
  только первый (эталон `RL/stage0.py:955`);
- добавить `tempo` («Темп и распределение», эталон `RL/stage0.py:1147`)
  и `warnings` (`RL/stage0.py:1229`);
- cover-паспорт: добавить группу/темп/страны/цель ночей
  (эталон `RL/stage0.py:842-869`);
- context/honest прогонять через `_strip_yaml_jargon` из RL (:1144, :1224);
- поправить стейл-докстринг про landscape (:1,7 — рендер портретный).
Приёмка: тест на фикстуре с interest_match: детали в HTML; excluded с
reason+description показывает оба.

### 1.6 Stage 2 (static, PDF-путь): потерянные блоки — [x]
`HT/stage2.py`. Сделать: рендер `context` (инфо-бокс), `warnings`
(по severity), когорты `unscored_with_signal`, compact-карточек MEDIUM/LOW
(компоненты+URL, эталон `RL/stage2.py:894-938`), колонки «Ссылка» в полной
таблице; бейджи `user_added`/`low_confidence`; guard пустой категории в
`_sig` (:30, `.split()[0]` → IndexError; эталон guard — `HT/stage0.py:43`).
Приёмка: smoke на страна_г_1: warnings и unscored в HTML; `_sig("")` не падает.

### 1.7 Stage 3: потерянные блоки и Р7 — [x]
`HT/stage3.py`. Сделать: рендер `warnings` + `context_lines`; «Покрытие по
регионам» (`_coverage_rows` RL3:1931); «Кто писал про регион»
(`polished_authors_summary`, RL3:1968); pre-select заполненного `region.tag`
(RL3:1959 — round-trip тег); снять cap `p.excerpts[:5]` (:58) — рендерить
все; поля выдержек year/url/report_title/tone (эталон RL3:2004-2015);
разбивка HIGH «нейтр./крит.» — переиспользовать `_counts_line` (RL3:1522);
скрыть `aggregation_mode`/`region.mode` (:86,123) — DOCX скрывает сознательно
(RL3:2087).
Приёмка: smoke на страна_г_1 (57 POI): счётчик выдержек в HTML == md; строки
«режим:» отсутствуют.

### 1.8 Stage 4: подсекции вариантов и мёртвый verdict — [x]
`HT/stage4.py:104-160`. Сделать:
- рендерить `Variant.subsections` (маршрут по дням / что включает /
  логистика / риски / кому подходит) — сейчас только `v.intro`, тело
  вариантов исчезает (эталон `RL/stage4.py:763-765`);
- добавить `context` (RL4:661), `warnings` (RL4:668), `priority_buckets`
  (RL4:703), cover-паспорт trip_params (RL4:549-584);
- удалить ветку `cover.get("chosen_variant_raw")` (:57-73, 80-92, 108,
  149-151): экстрактор ключ не производит (RL4:494-504), решение
  «`## Решение` не рендерится» — verdict-блок убрать целиком.
Приёмка: тест на фикстуре Stage-4 (пример `docs/travel-planning/stages/
Stage-4-example.md`): текст подсекций в HTML; строк verdict нет.

### 1.9 Stage 5: дорендерить документ до паритета — [x]
`HT/stage5.py:245-260` (`build_html`). Эмпирика (Страна Б 5_v4, живой
экспорт): отсутствуют «Контекст и ключевые параметры», «Шапка»,
«Критические подготовительные пункты», «План реагирования на риски»,
«Чеклист за 2 недели», «TODO для верификации»; дни/бюджет/Diff есть.
Сделать (эталоны в `RL/stage5.py`): рендер `header` (:714), `critical_prep`
(:720), `route_intro` (:731), контекст («Замысел» уже есть на обложке —
добавить таблицу «Чего нет в маршруте», :698), «Регионы маршрута» с полями
маркеров (:704-711, 735-757), `risk_plan_blocks` (:786), `todo` (:800),
`checklist_2w` (:809), `extra` (:835 — незнакомые H2, защита от эволюции
схемы). Плюс:
- `_render_marker_block`/program (:126): intro 🎯-маркера рендерить
  параграфом перед bullets (сейчас `_, bullets = split_bullets_and_intro`
  выбрасывает; маркер без bullets теряет всё);
- чип брони: fallback при `day.booking` без 🏨-блока (:149-151, 172;
  эталон `RL/stage5.py:957-959`).
Приёмка: тест-матрица «H2-секции md ↔ HTML» на фикстуре страна Б:
каждая H2-секция 5_vX представлена характерной строкой в HTML
(пробники: «Карты РФ Visa», «Вероятность», «Прогноз погоды по регионам»,
строка TODO-секции).

### 1.10 Stage 6: свои потери — [x]
`HT/stage6.py`. Сделать: интро-текст секции броней рендерить И при наличии
H3-подсекций (:136-137, сейчас `subs or [{body: bookings}]` теряет body;
эталон RL6:769-772); легенда карты (эталон RL6:723-727). Полнота дней
приходит из 1.9 автоматически (stage 6 реюзает h5-хелперы).
Приёмка: фикстура с bookings-body+H3: оба в HTML.

### 1.11 render_html: гейты и обогащение — [x]
`HT/__init__.py:87-93` + `EXP/export.py` (`_export_html_engine`, :204).
Сделать: перед build вызывать те же гейты, что reportlab-ветка
(stage 0 — `validation_errors` → исключение с текстом, RL0:1097;
stage 3 — `_gate_validation`, RL3:1879); для stage 3 прокидывать
`stage1_path`/`stage0_path` (как `render_stage3_docx/pdf`,
RL3:2393-2428) — иначе теряются реестр авторов и описания регионов.
Приёмка: битая фикстура stage 0 роняет HTML-рендер той же ошибкой, что
PDF; stage 3 HTML с лежащим рядом `1_dr_reports.md` содержит url автора.

### 1.12 Drift-тест полноты (защита от рецидива) — [x]
В каждом `HT/stageN.py` объявить контракт `CONSUMED_KEYS: frozenset[str]` —
ключи extract-словаря, которые build_html обязан потреблять. В
`tests/test_html_export.py` тест: для каждой стадии прогнать фикстурный
extract → множество непустых ключей extract ⊆ CONSUMED_KEYS, и smoke:
характерная строка каждой секции присутствует в HTML. Новый ключ в
extract без потребителя → красный тест.

**Тесты этапа 1:**
```
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_html_export.py
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_export_stage5.py
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_export_stage6.py
```

---

## 3. Этап 2 — единый словарь (Р2, Р3, Р7)

### 2.1 Дополнить taxonomy.json — [x]
В `terms` добавить группы (en/ru; формат как существующие):
- `content_density`: HIGH→«высокая», MED→«средняя», MEDIUM→«средняя»,
  LOW→«низкая»;
- `report_focus`: photo→«фото», culture→«культура», nature→«природа»,
  architecture→«архитектура», food→«гастрономия», adventure→«адвенчура»,
  mix→«микс»;
- `report_tonality`: critical→«критика» (тональность КАРТОЧКИ stage 1;
  существующая группа `tonality` — про упоминания POI, не трогать);
- в `similarity_component` добавить поле `ru_short`: style→«стиль»,
  focus→«фокус», pace→«темп», independence→«самост.», depth→«глубина»,
  demo→«демо»;
- `region_role_group` (заголовки групп stage 0): core→«Ядро поездки»,
  supporting→«Поддержка», niche→«Нишевые», borderline→«Пограничные»
  (выравнивание с singular `region_role`; текущий хардкод
  «Дополнительные» заменяется на «Поддержка»).
`no_translate` оставить `["POI"]` + добавить `"Deep Research"`.

### 2.2 Подключить taxonomy к HTML-слою — [x]
`skills/travel-planning/scripts/taxonomy.py`: убедиться, что есть/добавить
хелпер `label(group, term, lang="ru") -> str` (canon-толерантный) и
`short_label(group, term)`. Заменить хардкоды:
- `HT/stage0.py:27` `_ROLE_RU` → taxonomy `region_role_group`;
  `_DENSITY_SIG` (:29) — подпись бейджа через `content_density` (RU);
- `HT/stage1.py:43-48` — `critical` → `report_tonality`, focus-тег →
  `report_focus` (нормализует и EN `mix`, и готовые RU);
- `HT/stage2.py:22-32` `_CAT_SIG`/`_sig` → `author_category` RU
  («ВЫСОКАЯ»…), `_COMP_ABBR` (:26) удалить → `ru_short`;
  категории в полной таблице (:139) и distribution (:101-104) — RU
  (эталон reportlab `_localize_dist_category`, RL2:683);
- `HT/stage3.py:34-41` `_CAT_SIG`/`_sig` → `poi_category_badge` RU
  («ЖЕМЧУЖИНА»…); counts-строка (:50-52) — переиспользовать
  `RL/stage3.py:1522 _counts_line`;
- легенда RU=EN: один хелпер в `html_lib` (эталоны RL2:909, RL3:1864),
  вывод в подвале stage 2 и stage 3.
Приёмка: в HTML стадий 0–3 нет EN-бейджей `high|med|low|critical|mix|
hidden gem|outlier|style|indep.` (кроме легенды «РУС = EN»).

### 2.3 Единый ru_anglicisms — [x]
`EXP/html_lib.py:118-131`: добавить `\bcost[ _-]rank\b` → «ранг стоимости».
`open-jaw` НЕ переводить (авиатермин; при желании — задокументировать).
Применение: stage 4 — все видимые текстовые блоки (интро/подсекции
вариантов, оси, честная оценка; убрать точечный `re.sub(r"\bVariant\b",…)`
`HT/stage4.py:79`); stage 6 — сводные секции и досье. «Бюджет all-in» →
«Бюджет всё включено» в ОБОИХ движках: `HT/stage5.py:80` и
`RL/stage5.py:669`.
Приёмка: тест `ru_anglicisms` на «Cost rank», грепы «all-in» по обоим
модулям пусты.

### 2.4 Убрать § SN — [x]
Вызовы `plate(..., no="§ SN")`: `HT/stage0.py:116`, `stage1.py:96`,
`stage2.py:122`, `stage3.py:136`, `stage4.py:128`, `stage5.py:250`,
`stage6.py:124` — убрать аргумент `no`. В `html_lib.plate` (:134-153)
удалить параметр `no` и `sp-no`-разметку; вычистить CSS `.sp-no`.
Обновить тесты, которые проверяют `sp-no`/`§` (grep по tests/).
Приёмка: `§ S` не встречается ни в одном рендере фикстур.

### 2.5 Документировать подход — [x]
- `docs/travel-planning/format-firewall.md` — раздел «Термины и
  русификация: taxonomy.json как SSOT» (группы, no_translate, ru_short,
  правило «новый видимый термин → сначала в taxonomy»);
- `docs/travel-planning/export/export-design.md` — ссылка на раздел;
- `README.md` §2 строка i18n — дополнить;
- пользовательская шпаргалка `skills/travel-planning/STAGES.md` — если
  упоминает EN-категории, обновить.

**Тесты этапа 2:**
```
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_taxonomy.py
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_format_contract.py
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_html_export.py
```
(в test_format_contract добавить ось: новые группы taxonomy ↔ их
потребители в stages_html — 1:1, чтобы дрейф ловился в обе стороны).

---

## 4. Этап 3 — дефолты, роутинг, документация (Р1, Р4)

### 3.1 DEFAULT_FORMAT → html — [x]
`EXP/export.py:60-68`: все стадии `"html"` (включая `"3"`). Комментарий:
PDF/DOCX — по явному `--format`.

### 3.2 Stage 2 html → интерактивный lookup — [x]
`EXP/export.py:334-341` (`args.engine == "html"`): для `stage_id == "2"
and fmt == "html"` НЕ уходить в `stages_html`, а падать в
reportlab-registry (`renderer.get_renderer("2", "html")` → интерактивный
`RL/stage2.py build_html`, тёмная тема, фильтры/сортировка/expand,
таб «Практика» из соседнего `1_dr_reports.md`). Статический
`HT/stage2.py` остаётся для `fmt == "pdf"`.
Приёмка: `--stage 2 --format html` даёт файл с `<script>` и
кнопками-фильтрами; `--format pdf` — прежний путь.

### 3.3 Сверка --stage ↔ YAML — [x]
`EXP/export.py` (`cmd_export`, ~:250): если frontmatter-`stage` есть и его
лидирующая цифра ≠ `args.stage` → ошибка, exit 2 (сейчас имя файла берётся
из `--stage`, контент из YAML → молча «не тот артефакт»).

### 3.4 Переписать export-modes.md — [x]
`skills/travel-planning/references/export/export-modes.md`. Сейчас
утверждает «дефолт E — PDF», «HTML только Stage 2» — в трёх живых
прогонах модели из-за этого отказывали в HTML/делали PDF-first.
Новая структура: (1) дефолт — HTML везде, PDF/DOCX по запросу, матрица
стадия×формат; (2) flow polish → sanity → render (без изменений);
(3) предупреждения исполнителю: HTML-сайдкар PDF-рендера ≠ HTML-экспорт
(for_pdf-ориентация: stage 1 landscape/2 колонки); пакет `scripts/export`
НЕ копировать/переименовывать (ломаются относительные импорты и
`taxonomy` уровнем выше — потерянный цикл отладки, Страна Б stage 5);
запуск из read-only места работает.

### 3.5 Синк SKILL.md / STAGES.md / changelog — [x]
Все места, где заявлены форматы стадий (grep «PDF» по SKILL.md,
STAGES.md, references/stage*-polish-prompt.md) — привести к Р1.
Запись в `docs/travel-planning/changelog.md`.

### 3.6 stage5-polish-prompt: keep/drop YAML — [x]
`skills/travel-planning/references/stage5/…polish-prompt…`: добавить
явный список «какие YAML-поля оставить/удалить» (keep: trip_id, stage,
duration_nights, travelers_profile, chosen_variant, budget*, warnings;
drop: mode, chosen_variant_raw, aggregation_mode_inherited, schema_version,
iteration, previous_plan, trip_id_warning, web_search/mcp-флаги) — в живом
прогоне модель выясняла это чтением parser/adapter/рендерера (десяток
лишних чтений, вклад в исчерпание контекста).

### 3.7 Чистка мёртвого кода — [x] (частично: choices pptx/xlsx убраны; parse/build_export_filename СОХРАНЕНЫ — покрыты test_export_engine §9/§10 и ветка else достижима при --input без --stage; docstring parse_export_filename исправлен)
- `EXP/file_naming.py:239-291` `parse_export_filename` — переписать под
  действующую trip-схему или удалить (сейчас требует `_YYYY-MM-DD`,
  которого в именах нет; не вызывается, docstring врёт);
- `EXP/export.py:320-323` — недостижимая ветка `build_export_filename`
  (choices 0–6 покрыты явными ветками) — удалить;
- `EXP/export.py:542` — убрать `pptx`,`xlsx` из choices (рендереров нет,
  «успешный» JSON вводит в заблуждение).

**Тесты этапа 3:**
```
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_export_engine.py
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_export_stage2.py
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_html_export.py
```
(+ в test_export_engine: DEFAULT_FORMAT-матрица, сверка --stage↔YAML,
stage-2 маршрутизация.)

---

## 5. Этап 4 — format-firewall (Р5)

### 4.1 parser.py: валидный YAML не должен теряться — [x]
`EXP/parser.py`:
- **flow-списки** (`_parse_scalar`): `[a, b, c]` → список (сплит по
  запятым вне кавычек; пустой `[]` → `[]`). Сейчас — строка БЕЗ warning;
  массово в свежих артефактах (`weights_used`, `trip_wishes`,
  `must_have_resolved`, `mcp_extensions_used`…), ломает JS интерактивного
  stage 2 (`_json.dumps(строки)` → список символов);
- **flush-списки** (:214-224): элементы `- ` на отступе ключа (валидный
  YAML; живой кейс — «Регионов в выборке: 0», Китай stage 0) — принимать:
  если peek-строка `- ` на indent == indent ключа, собирать блок;
- **block-скаляры** `|`/`>`: минимум — warning «block scalar не
  поддержан» вместо молчаливого значения-`"|"`;
- **digit-only `stage:`**: не менять кастинг (int валиден), но все
  потребители обязаны нормализовать: `EXP/adapter.py:171` (`if stage_id:`
  → `is not None` + str), `EXP/export.py:329` (то же);
- `_HEADER_RE` (:381): вырезать fenced-код перед поиском заголовков;
- ключи с дефисами: regex топ-уровня (:200) выровнять с
  check_format.py:174 (`[\w-]`).

### 4.2 normalize.py: кавычки — [x]
`skills/travel-planning/scripts/normalize.py`: новый проход — в границах
frontmatter выпрямлять `“ ”` → `"` только когда кавычки обрамляют
значение YAML (`: “…”` / `: “…”  # comment`). Подтверждено в свежих
артефактах (Китай stage 0/1/2/3 — ломало матчинг имён регионов с
`### {регион}`). Идемпотентность обязательна. Зарегистрировать дрейф в
`docs/travel-planning/format-firewall.md` (каталог дрейфов).

### 4.3 check_format.py: гейт эмита — [x]
- новый чек `frontmatter_parse` (во всех пресетах 0–6): прогнать
  нормализованный frontmatter через `parser.parse_yaml`; warnings → FAIL
  с их текстом (ловит flush/flow/скаляры на эмите — Р5);
- ловля placeholder-заглушек: `YYYY-MM-DD`, `<...>`-шаблоны в значениях
  frontmatter (живой кейс страна_г_1: `dr_run_date: YYYY-MM-DD  # ← поставь
  дату` уехал в артефакт);
- count-проверки (:244-250) читать по нормализованному frontmatter
  (сейчас `-----`-файл → счётчики молча «неприменимы»).

### 4.4 polish_check.py: тот же разбор, что у парсера — [x]
- `_split_yaml_body` (:303) → `parser.split_frontmatter` + делимитер-
  нормализация `-{4,}` (живой кейс: Китай stage 0 получил профиль
  Stage 5) + CRLF-толерантность;
- `_profile_for` (:271): матчить по лидирующей цифре `stage`
  (`0`≡`0_scope`), при fallback на DEFAULT_PROFILE — явный warning;
- `_parse_yaml_flat` (:322): срезать inline-комментарии
  (`parser._strip_inline_comment`);
- H2-сравнение (:364-389): `collections.Counter` вместо set —
  удаление одного из двух одноимённых H2 должно ловиться.

### 4.5 html_to_pdf: деградация по цепочке — [x]
`EXP/html_lib.py:349-375`: каждый движок (chromium → weasyprint →
wkhtmltopdf) в try/except — сбой (не только отсутствие) ведёт к
следующему; stderr упавшего движка включать в notes/сообщение.

**Тесты этапа 4:**
```
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_normalize.py
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_check_format.py
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_export_engine.py
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_polish_check.py
```
(+ новые кейсы: flow/flush-списки, кавычки, digit-stage, placeholder,
`-----`+CRLF в polish_check, «упавший chromium → weasyprint».)

---

## 6. Прогресс

| Этап | Статус | Коммиты |
|---|---|---|
| 1 — паритет/краши | **готов** (148 html-проверок ✓) | pending |
| 2 — словарь | **готов** (taxonomy 316, format-contract 246 ✓) | pending |
| 3 — дефолты/доки | **готов** (engine 128 ✓; 3.7 частично — см. заметку) | pending |
| 4 — firewall | **готов** (parser/normalize/check_format/polish_check/html_to_pdf ✓) | pending |

---

## Приложение A. Происхождение находок

1. Живые прогоны (стенограммы: `trips/*/new_export/*_stage_log.txt`):
   - Китай stage 0 (Sonnet): исходник с `-----`-делимитером,
     flush-списками, фигурными кавычками — полсессии диагностики
     («Регионов в выборке: 0»), PDF-first из-за устаревшего
     export-modes.md;
   - Китай stage 1 (Sonnet): отказ «HTML не реализован» по устаревшему
     export-modes.md; выдан HTML-сайдкар PDF (landscape, 2 колонки)
     вместо HTML-экспорта; все 30 карточек без автора;
   - Китай stage 2 (Opus): выдана статическая витрина, ложно описана как
     интерактивная (0 `<script>`);
   - Китай stage 3 (Opus): краш trap_archetype, патч скилла на лету
     с откатом;
   - Страна Б stage 5 (Sonnet): «продолжай» — исчерпание контекста
     (см. §4 задача 3.6 и export-modes 3.4); секции документа потеряны
     в HTML (см. 1.9);
   - Страна Б stage 6 (Sonnet): TODO-подсветка оборвана на дате; рапорт
     «риски/чеклист/TODO внутри» ложен — секций нет.
2. Три аудит-агента (2026-07-04): консистентность stages_html /
   правильность обвязки / паритет веток — находки инкорпорированы в
   задачи выше.
3. Вывод о ложных рапортах моделей: содержимому экспорта без
   программной проверки не верить — закрывается drift/smoke-тестами
   (1.12) и гейтами (1.11).

## Приложение B. Перепроверка дрейфов на свежих артефактах (2026-07-05)

| Дрейф | Китай_2027 | Страна Б-новый | Вердикт |
|---|---|---|---|
| `-----`-делимитер | st. 0/1/2 | st. 1 | подтверждён |
| Фигурные кавычки в YAML | st. 0/1/2/3 | st. 1/2 | подтверждён |
| Flush-списки | st. 0, 2 | — | подтверждён |
| Flow-списки `[...]` | st. 0/2 | st. 0/2/3/4/5/6 | подтверждён, массовый |
| digit-only `stage:` | — | 1 файл | частично (+Страна Г) |
| Placeholder `YYYY-MM-DD` | — | — | только Страна Г; гейт всё равно нужен |
| Block-скаляры / CRLF | — | — | не встречены; толерантность дёшево |
