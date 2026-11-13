# Export fix batch 2 — июль 2026 (PLAN, исполнен)

Дата: 2026-07-13. Статус: **ИСПОЛНЕНО 2026-07-14** (этапы 1–6, §9). Исполнитель: **Sonnet 4.6**
(вся механика по точным адресам; спековые/промтовые правки сюда не входят —
они в `plans/russification-phase2-plan.md`, исполнитель Opus).

Происхождение: разбор живого экспорта Китай (4 стадии, HTML+PDF, 2026-07-13,
стенограммы `trips/регион_a_2027/{0..3}_stage_log.md`) + локальное
воспроизведение всех дефектов на коде репозитория. Решения пользователя
зафиксированы 2026-07-13 (§1).

---

## 0. Инструкция исполнителю (обязательно)

1. Прочитать `docs/travel-planning/CLAUDE.md` (дев-гайд) и
   `docs/travel-planning/format-firewall.md` (перед этапами 4–5 — правятся
   парсеры).
2. Python для тестов: `~/.pyenv/versions/3.12.9/bin/python3` (системный
   python3 сломан). Команды тестов — в конце каждого этапа.
3. Line-номера — ориентиры на 2026-07-13; при расхождении искать по
   сигнатурам.
4. Политика подавления/отображения полей — одна на оба движка (Р7 батча 1),
   эталон — reportlab-ветка; каждую правку рендера делать в ОБЕИХ ветках,
   если явно не сказано иное.
5. Коммиты — группами по смыслу; синхронизация документации (SKILL.md →
   references → STAGES.md → changelog.md) после каждого этапа.
6. В файлы скилла (`skills/travel-planning/**`) не протаскивать
   дев-материалы.

Ключевые пути:
- `EXP = skills/travel-planning/scripts/export`
- `HT = EXP/stages_html` (HTML-ветка), `RL = EXP/stages` (reportlab/DOCX)
- живые артефакты: Synology `trips/регион_a_2027/` (`0_scope.md`,
  `1_dr_reports.md`, `2_similarity.md`, `3_poi_pool.md`, `trip.yaml`)

## 1. Решения пользователя (контракт; не пересматривать без него)

| # | Решение |
|---|---|
| Р8 | PDF-движок: **wkhtmltopdf убирается из авто-цепочки** (WebKit-2012 без CSS grid — источник «рассыпанных» PDF). Авто-цепочка: chromium → weasyprint → handoff в core `pdf` skill. wkhtmltopdf — только по явному запросу |
| Р9 | Polished-версии `.md` **не сохраняются** обратно в trips/ (эфемерны, только для дебага). Следствие: рендер не имеет права зависеть от polish-маркеров как от единственного источника |
| Р10 | «Кто едет» — SSOT в **профиле** (`display_name` во frontmatter, «Родители»/«Петя»), детерминированная подстановка скриптом; fallback-цепочка ниже (задача 3.2). Решает и расхождения между стадиями |
| Р11 | Stage 3: обложка оставляет только таблицу «Покрытие по регионам»; строка «Итог: …» и таблица «Категория/POI» убираются |
| Р12 | Русификация тела `.md` (Tempo/Country/Math, `explicit_list`, стили карточек DR) — НЕ в этом батче; отдельный план `russification-phase2-plan.md` |

---

## 2. Этап 1 — PDF-движок (корневая причина «страшных» PDF)

Контекст: в контейнере claude.ai нет chromium/weasyprint, цепочка падала в
wkhtmltopdf (Qt WebKit ≈2012, **не поддерживает CSS grid**) → паспорт/kv/comp/
карточки рассыпаются в столбик, рамки и отступы карточек теряются
(скриншоты Китай stage 0/1/2 PDF).

### 1.1 Убрать wkhtmltopdf из авто-цепочки — [ ]
`EXP/html_lib.py`: `_pick_engine` (:421-431) и `html_to_pdf` (:464-498).
- Авто-цепочка: chromium → weasyprint; если обоих нет — `html_to_pdf`
  возвращает «нет движка» → вызывающий код (`_html_to_pdf_request`,
  `export.py`) уходит в handoff core `pdf` skill (`local_conversion=false`) —
  этот путь уже существует, проверить что срабатывает.
- wkhtmltopdf оставить ТОЛЬКО по явному опту: env `TRAVEL_PDF_ENGINE=wkhtmltopdf`
  (или параметр `engine=`), с патчем ориентации из задачи 1.2.
- Сообщение об отсутствии движка (:496-498) переписать: рекомендовать
  chromium/weasyprint ИЛИ handoff; wkhtmltopdf упомянуть как деградацию
  качества (без grid).
Приёмка: тест — при заглушенных chromium/weasyprint и живом wkhtmltopdf
`html_to_pdf` НЕ рендерит локально (запрос handoff); c
`TRAVEL_PDF_ENGINE=wkhtmltopdf` — рендерит через wkhtmltopdf.
Обновить существующие тесты цепочки в `tests/test_html_export.py`
(`pdf_engine_available`, деградация по цепочке — задача 4.5 батча 1).

### 1.2 Портировать контейнерный патч ориентации — [ ]
`EXP/html_lib.py` `_run_wkhtmltopdf` (:451): wkhtmltopdf не читает CSS
`@page{size:… landscape}` — при landscape-CSS в документе добавлять CLI-флаг
`--orientation Landscape`. (Патч был сделан в контейнере 2026-07-13 и потерян —
в репо его нет.) Актуален только для explicit-opt ветки из 1.1.

### 1.3 Разрывы страниц в печати — [ ]
В print-CSS (`@media print` в `EXP/html_lib.py` / `assets/design-components.css`):
`break-inside: avoid; page-break-inside: avoid;` для `.scard`, `.poi`,
`.opt-card`, `.day`, `.note-item` + `margin-bottom` карточек, переживающий
печать. Закрывает «карточки Stage 1 слипаются в PDF» при любом движке.
Приёмка: smoke — CSS-правило присутствует в собранном HTML.

**Тесты этапа 1:**
```
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_html_export.py
```

---

## 3. Этап 2 — порт потерянных контейнерных патчей Stage 1 + паспорт-CSS

Три фикса были сделаны 2026-07-13 в `/mnt/skills/user/travel-planning/`
(распакованная копия в контейнере) и НЕ попали в репо. Переносим.

### 2.1 Обложка Stage 1 HTML: убрать хардкод — [ ]
`HT/stage1.py:186-200` (`build_html`): сейчас `<h1>Источники для маршрута</h1>`
хардкодом, polish-заголовок и маркер `[[поездка:]]` игнорируются (учитывает
только reportlab-ветка). Сделать: прокинуть из `RL/stage1.py` реальные
`_cover_title`/`_cover_subtitle`/`_cover_key_params` + паспорт-таблицу
(`passport_rows`) — как в reportlab-обложке. Учесть Р9: при отсутствии
polish-маркера обложка собирается из YAML + резолвера 3.2.
Приёмка: тест на фикстуре страна_г_1 — титул из H1 файла (не хардкод), паспорт
с «Кто едет»/«Регионы (N)».

### 2.2 Счётчик регионов и темп в обложке — [ ]
`RL/stage1.py` `_cover_key_params`/`_cover_subtitle`: для де-регионизированного
(флэт) формата Stage 1 структурные Region-объекты схлопываются в один
псевдо-регион «База отчётов» → обложка показывала «Регионы (1)». Сделать:
счётчик и список регионов — из YAML `regions:` (первичный источник); текст
маркера `[[поездка: регионы:]]` — только как fallback для текста (парсинг
маркера по « и » ломается на названиях типа «Пекин и окрестности»).
Добавить строку «Темп» в `passport_rows` (сейчас теряется).
Приёмка: тест на флэт-фикстуре с YAML `regions:` из 8 имён → «Регионы (8)»,
строка темпа присутствует.

### 2.3 Паспорт: лейбл-колонка — [ ]
`assets/design-components.css` (`.passport-row`, `.passport-k`; grep — копий
файла может быть больше одной, синхронизировать все):
`grid-template-columns: var(--passport-k) 1fr` →
`grid-template-columns: minmax(var(--passport-k), max-content) 1fr`, плюс
в `.passport-k` — `overflow-wrap:break-word; hyphens:auto` как страховка.
Даёт «ПРОАНАЛИЗИРОВАНО РЕГИОНОВ» в одну строку вместо переносов
(скриншот stage 0 HTML) и закрывает наезд колонок из лога stage 0.
Приёмка: рендер stage 0 Китай — лейблы паспорта без переносов.

### 2.4 «WARN-флагов» → «Предупреждений» — [ ]
`RL/stage1.py:1216`: `rows.append(("WARN-флагов", …))` → «Предупреждений».
Смесь языков в паспорте.

**Тесты этапа 2:**
```
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_export_stage1.py
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_html_export.py
```

---

## 4. Этап 3 — «Кто едет»: SSOT и единый резолвер (Р10)

Сейчас: stage 0/1 — из эфемерного polish-маркера; stage 2 — fallback из
имени файла профиля (`алексей_родители` → «Алексей и родители»,
`RL/stage2.py:565` `_who_goes`); stage 3 — сырое `алексей_родители` в прозе.
Три стадии — три разных ответа.

### 3.1 Поле `display_name` в профиле — [ ]
- `references/profile-management.md`: документировать опциональное
  frontmatter-поле `display_name` («Родители», «Петя», «Алексей и Мария») —
  человекочитаемое имя группы/человека для витрин;
- `scripts/profile/` (парсер профиля, если есть frontmatter-парс) — читать
  поле; отсутствие — не ошибка;
- анкета (EXPORT_FORM/IMPORT_FORM) — НЕ трогать в этом батче (поле руками).
- ✅ `display_name` уже заполнен в живых профилях на Synology (2026-07-13):
  `алексей_родители` → «Родители», `алексей` → «Алексей», `мария` → «Мария»,
  `алексей_мария` → «Алексей и Мария». Исполнителю остаётся только код+доки.

### 3.2 Единый резолвер `who_goes` — [ ]
Новый хелпер в `EXP` (напр. `EXP/travelers.py` или в `html_lib`), сигнатура
`resolve_travelers(yaml: dict, trip_marker: dict, input_path: Path) -> str`.
Цепочка (первый непустой):
1. профиль: `yaml.travelers_profile` → файл `{travel_root}/profiles/{stem}.md`
   (резолв от `input_path`: `../../profiles/`); frontmatter `display_name`;
   читать graceful (нет файла/поля → дальше);
2. `trip.yaml` рядом с артефактом (`input_path.parent / "trip.yaml"`):
   `travelers: [родители]` → join « и », первая буква заглавная;
3. polish-маркер `[[поездка: группа: …]]` (`trip_marker.get("кто"/"группа")`);
4. прежний fallback: stem профиля, `_` → « и », капитализация.
Подключить ВО ВСЕ места «Кто едет» обоих движков: grep `Кто едет` по `EXP/`
(минимум: `RL/stage2.py _who_goes`, обложки stage 0/1/3/4/5/6 обеих веток,
kicker интерактивного stage 2 `RL/stage2.py:1268`).
Приёмка: тесты — (а) профиль с display_name побеждает; (б) без профиля
trip.yaml даёт «Родители»; (в) без всего — прежний fallback; (г) на живом
Китае все стадии дают одно и то же имя.

**Тесты этапа 3:**
```
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_export_stage2.py
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_html_export.py
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_export_engine.py
```

---

## 5. Этап 4 — Stage 3: обложка и жаргон (Р11)

### 4.1 Баг непарных `**` в context_lines — [ ]
`RL/stage3.py:1011`: `line.strip("- *")` срезает ведущие `- **`, но
оставляет закрывающие `**` → «Кто/когда:** пара…», md_inline дальше жирнит
невпопад («Итог:» до RED FLAG). Сделать:
`re.sub(r"^[-*]\s+", "", line.strip())` — срезать только буллет, жирность
отдать `md_inline` (HTML-ветка уже прогоняет через `md()`; проверить, что
reportlab-ветка рендерит bold, а не сырые звёздочки).
Приёмка: тест — строка `- **Кто/когда:** пара 60–61` рендерится
`<b>Кто/когда:</b> пара…` без `**` в выводе.

### 4.2 Убрать строку «Итог:» с обложки — [ ]
Экстрактор `RL/stage3.py` (`context_lines`, :1010-1014): фильтровать строки,
начинающиеся с `Итог:`/`**Итог:**` — их данные полностью дублирует таблица
покрытия. Фильтр в экстракторе = одна точка для обеих веток (Р7).

### 4.3 Убрать таблицу «Категория/POI» — [ ]
`HT/stage3.py:426-439` (блок `if ex.get("distribution")`) — удалить;
аналогичный рендер distribution в `RL/stage3.py` (DOCX и PDF) — удалить.
Таблица «Покрытие по регионам» остаётся единственной сводкой (строка ВСЕГО
несёт те же числа). `_parse_distribution` и ключ `distribution` в extract
НЕ удалять (потребители в тестах/`CONSUMED_KEYS` — поправить контракт:
ключ либо изъять из `CONSUMED_KEYS`, либо пометить сознательно
не-рендерящимся согласно механике drift-теста 1.12 батча 1).

### 4.4 Фильтр внутренних ссылок в warnings — [ ]
Живой кейс: «…в режиме abundant такие места были бы LOW SIGNAL.
См. stage3-poi.md §6.5.» — ссылка на внутренний референс скилла в
user-facing выводе. В рендере warnings/info обеих веток stage 3 (и заодно
stage 2 — та же природа):
`re.sub(r"\s*(?:См\.|see)\s+stage\S*\.md(\s*§?[\d.]+)?\.?", "", w)`.
Приёмка: тест — warning с хвостом «См. stage3-poi.md §6.5.» рендерится без
него; warning без хвоста не тронут.

### 4.5 sample_curation_note без имени скрипта — [ ]
`HT/stage1.py:196-199` и `RL/stage1.py:1462-1466` (info-box Mode B):
перед рендером `re.sub(r"\s*через\s+\S+\.py", "", note)` →
«карточки №29, №30 добавлены вручную». Имя пайплайн-скрипта пользователю
не нужно.

**Тесты этапа 4:**
```
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_export_stage3.py
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_export_stage1.py
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_html_export.py
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_aggregate_pois.py
```

---

## 6. Этап 5 — Stage 2: карточки и витрина

### 5.1 rationale «---» — [ ]
Живой кейс: у карточки `#4 **Arkhip251166** — 6.5/10` нет строки-резюме
(есть только «Тянет вверх/вниз»), и парсер взял разделитель `---` как
rationale → в интерактивном HTML комментарий «---». В парсере карточек
`RL/stage2.py`: строка из одних `-`/`—`/пробелов → НЕ rationale (skip);
при пустом rationale reading-note собирать из первой фразы «Тянет вверх»
(до `;`) или оставлять пустым.
Приёмка: тест на карточке без резюме — rationale пуст/из «Тянет вверх»,
«---» в HTML отсутствует.

### 5.2 Центрирование числовых колонок — [ ]
Статическая витрина `HT/stage2.py`: колонки «Авторов»/«Доля» таблицы
распределения — `text-align:center`. Интерактивный `RL/stage2.py build_html`:
проверить статбенд/таблицы — числа по центру колонок. (Запрос пользователя:
левое выравнивание чисел выглядит криво.)

### 5.3 Русифицировать бейджи user_added / ext. reading — [ ]
`RL/stage2.py:1088-1093` (tags DATA-JSON) и все места рендера этих ярлыков
(грепнуть оба движка, вкл. `HT/stage2.py` бейджи и подпись «добавлен
вручную» уже существующую в HIGH-карточках): через taxonomy —
`user_added` → «добавлен вручную», `ext. reading` → «расш. чтение»
(добавить группу/термины в `scripts/data/taxonomy.json` + потребители,
зеркальная ось в `test_format_contract.py` по образцу Фазы 1).

### 5.4 Полоса warnings под шапкой — [ ]
Интерактивный `RL/stage2.py`: полоса `critical:/info:` сейчас моноширинная
с EN-вкраплениями. Сделать обычную гарнитуру (не mono), прогнать через
`html_lib.ru_anglicisms` + добавить в словарь: `\bscore\b` → «балл»,
`\bsimilarity\b` → «похожесть» (только для этого видимого слоя; JSON/YAML
не трогать). Полный перевод прозы warnings — Фаза 2 русификации (Р12).

**Тесты этапа 5:**
```
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_export_stage2.py
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_format_contract.py
~/.pyenv/versions/3.12.9/bin/python3 skills/travel-planning/tests/test_taxonomy.py
```

---

## 7. Этап 6 — travel.html (Personal Hub)

### 6.1 Логи стадий не должны попадать в стадии — [ ]
`tools/travel.html` `buildStages` (:823-837): `N_stage_log.md` матчится
`stageOf` (`/^([0-6])[_ ]/`) и попадает в md-бакет стадии; для stage 0
`best()` (localeCompare desc) выбирает `0_stage_log.md` **вместо**
`0_scope.md` → «смотреть (md)» открывает лог. Фильтр:
`if (/_stage_log\.md$/i.test(f.name)) return;` в `rootFiles.forEach`.
Обновить контракт-тест `tools/tests/test_pages_contracts.py` (ось file_naming:
`N_stage_log.md` → не файл стадии).

### 6.2 Свежесть листинга — [x] поведение штатное, кода не требует
Причина «не вижу HTML в travel.html»: листинг директорий кешируется в
localStorage на 60 минут (`CACHE_TTL_MIN = 60`, travel.html:591); экспорт
лёг 22:20–22:22, окно смотрело кеш. Кнопка «Обновить» сбрасывает кеш
(`travel-cache:*`) — этого достаточно. Если будет раздражать — отдельным
решением снизить TTL для листингов (не для контента), в этот батч не входит.

**Тесты этапа 6:**
```
~/.pyenv/versions/3.12.9/bin/python3 tools/tests/test_pages_contracts.py
```

---

## 8. Синхронизация документации (после этапов)

- `docs/travel-planning/changelog.md` — новая версия (батч 2: движок PDF,
  порт контейнерных патчей, who_goes SSOT, stage 3 обложка, stage 2 фиксы,
  travel.html фильтр логов);
- `references/export/export-modes.md` — цепочка PDF-движков (Р8: wkhtmltopdf
  только по явному запросу; хендофф в core `pdf` — штатный путь без
  chromium/weasyprint);
- `references/profile-management.md` — `display_name` (задача 3.1);
- `format-firewall.md` — дрейфы: карточка Stage 2 без строки-резюме
  (разделитель как rationale), лог-файлы `N_stage_log.md` в корне trips/;
- `STAGES.md` — если упоминает форматы/движки PDF, синхронизировать;
- `docs/travel-planning/TODO.md` §1 — без изменений здесь (правится планом
  русификации).

## 9. Прогресс

| Этап | Статус |
|---|---|
| 1 — PDF-движок | ✅ выполнено 2026-07-14 |
| 2 — порт патчей Stage 1 + паспорт | ✅ выполнено 2026-07-14 |
| 3 — who_goes SSOT | ✅ выполнено 2026-07-14 |
| 4 — Stage 3 обложка/жаргон | ✅ выполнено 2026-07-14 |
| 5 — Stage 2 | ✅ выполнено 2026-07-14 |
| 6 — travel.html | ✅ выполнено 2026-07-14 |

Документация синхронизирована (§8): `changelog.md` (v0.69),
`references/export/export-modes.md`, `references/profile-management.md`
(`display_name`), `format-firewall.md` (D14/D15). Полный прогон
travel-planning + tools: 0 провалов.

## Приложение. Происхождение (для контекста исполнителю)

Экспорт Китай 2026-07-13 шёл в контейнере claude.ai: (а) PDF рендерился
wkhtmltopdf (единственный движок в контейнере) — все «страшные» PDF-скриншоты
это grid-коллапс WebKit-2012; (б) три бага чинились патчами прямо в
`/mnt/skills/user/travel-planning/` и не попали в репо (этап 2 их портирует);
(в) polished .md остались в контейнере (Р9 — это штатно). HTML-экспорты
корректно легли на Synology; «не видны» они были из-за 60-минутного кеша
листинга travel.html (задача 6.2).
