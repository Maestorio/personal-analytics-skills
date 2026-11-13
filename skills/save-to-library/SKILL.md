---
name: save-to-library
description: Сохраняет 11 типов артефактов в Claude-Memory/ (аудиты, прогнозы, сценарии, ретро-аудиты, стресс-тесты, еженедельные обзоры, интегрированные виды, снапшоты портфеля, макро-снапшоты, макро-инпуты, коллекции прогнозов). Обновляет INDEX.md и _sync_log.md. Используй когда пользователь говорит «сохрани аудит», «занеси в библиотеку», «сохрани прогноз/сценарии/обзор/снапшот», «закрой прогноз по теме …» / «закрой с исходом» (прогноз с прошедшим горизонтом и известным фактом), «поменяй класс бумаги / дату листинга» или когда другой скилл завершил работу и предлагает сохранить результат.
shared_refs: [transport-layer, events-yaml-spec, yaml-schemas, file-naming, audit-frontmatter-schema, claude-memory-layout, ticker-classes, gate-status-labels]
bundle_scripts: [constraint_engine.py]
---

# save-to-library

Сохраняет завершённый артефакт в библиотеку `Claude-Memory/`, обновляет соответствующий INDEX.md и при необходимости предлагает запустить `memory-sync`.

**Принцип:** скилл активно высказывает сомнения. Лучше лишний раз спросить, чем тихо занести мусор в библиотеку или засорить память некачественным профилем.

---

## Inputs / Outputs

**Inputs:**
- Завершённый артефакт ← любой скилл / пользователь, 11 типов (аудиты, прогнозы, сценарии, ретро-аудиты, стресс-тесты, еженедельные обзоры, integrated-views, снапшоты портфеля, макро-снапшоты, макро-инпуты, коллекции прогнозов)

**Outputs (пишет напрямую в Claude-Memory/, без буфера чата):**
- Файл артефакта → соответствующая папка `Claude-Memory/`
- Запись в соответствующий `INDEX.md`
- Запись в `Claude-Memory/_sync_log.md`

**Upstream скиллы:** retrospective-forecast-audit, forecast-confidence-applier, hypothesis-stress-tester, scenario-builder, portfolio-scenario-stress, ru-portfolio-advisor, portfolio-integrated-view, portfolio-data-loader, macro-ru-watcher, macro-forecast-chain, forecast-collector, forecast-monitor
**Downstream скиллы:** memory-sync (опц.)
**Shared refs:** transport-layer, events-yaml-spec, yaml-schemas, file-naming, audit-frontmatter-schema, claude-memory-layout

---

## Глобальные принципы

1. **Сомнение — норма.** Если что-то неочевидно (тип артефакта, subfolder, trust уровни, нужна ли запись в memory) — озвучить сомнение явно до выполнения. Исключение: если всё ясно — не затягивать лишними вопросами.

2. **Никаких fabricated values.** Если в файле нет поля `trust` или оно пустое — не угадывать. Спросить пользователя или предложить заполнить шаблон.

3. **Файл сохраняется только после подтверждения.** Если есть хотя бы одно сомнение — сначала озвучить, потом ждать ответа, потом сохранять.

4. **INDEX.md обновляется вместе с файлом — безусловно, не вопросом.** Сохранить файл без обновления INDEX.md — неполная операция. Вопрос «Дописать в INDEX?» запрещён — это шаг сохранения, а не опциональный бонус. Исключение: если INDEX недоступен (Synology не подключён) — выполнить все остальные шаги, в финальном сообщении явно указать «INDEX не обновлён — дополнить при следующем подключении», записать warning в `_sync_log.md`.

5. **memory-sync не запускается автоматически.** После сохранения — предложить запустить, не запускать без спроса.

6. **Парность `.md` ↔ `.yaml` для прогнозов и сценариев — обязательна.** Никаких одиночных файлов в `forecasts/` или `Scenarios/`.

---

## Шаг 0 — Транспорт + классификация артефакта

Прочитай `references/transport-layer.md` (пути, проверка доступности). Транспорт
один — Synology mount; недоступен → остановиться и сообщить пользователю, ничего не писать.

Скрипты-писатели с входом от модели при `ai_mode: off` (`_hub/settings.json`) отказывают кодом 3 — тогда ничего не писать и сообщить владельцу, что сайт в режиме без ИИ и правки идут с сайта; команды владельца (`decision_write.py owner`, `apply_condition.py --by owner`) работают.

Затем определи тип артефакта по сигналам:

| Тип | Сигнал | Workflow |
|-----|--------|---------|
| **Аудит источника** | YAML frontmatter содержит `source`, `audit_date`, `trust`; контент описывает track record источника по субдоменам | A |
| **Прогноз** (Tier 1 или Tier 2) | YAML frontmatter содержит `forecast_date`, `horizon_date`, `topic`, `domain`; контент — снимок мнений или прогноз+стресс-тест; либо в чате есть технический блок `## Events YAML (для save-to-library)` от forecast-confidence-applier ИЛИ `## Events YAML patch (для save-to-library)` от hypothesis-stress-tester | B |
| **Сценарная матрица** | YAML frontmatter содержит `type: scenario-matrix`, `axis_x`, `axis_y`, `scenarios`; либо в чате есть технический блок `## Events YAML (для save-to-library)` от scenario-builder | C |
| **Ретро-аудит** | Контент является выводом retrospective-forecast-audit: содержит три шкалы оценки (фактическое исполнение / позиция к консенсусу / локализация ошибки), декомпозицию тезисов, дословные цитаты; либо пользователь говорит «сохрани ретро-аудит», «занеси результат ретроспективы» | D |
| **Стресс-тест портфеля** | YAML frontmatter содержит `schema_version: 1`, `type: portfolio-stress-test`; парный `.md`; контент — таблица позиция×сценарий→ΔP&L, top_risks, macro_blindspots, sector_breakdown; либо пользователь говорит «сохрани стресс-тест портфеля», «занеси результат стресс-теста» | E |
| **Еженедельный обзор — акции** | YAML с `schema_version: 1`, `type: weekly-stocks-review`, `per_stock`; имя `weekly-review-stock-{date}.yaml` или legacy `weekly-review-{date}.yaml`; либо пользователь говорит «сохрани обзор акций», «save stocks review» | F |
| **Еженедельный обзор — облигации** | YAML с `schema_version: 1`, `type: weekly-bonds-review`, `per_bond`; имя `weekly-review-bond-{date}.yaml`; либо пользователь говорит «сохрани обзор облигаций», «save bonds review» | F |
| **Интегрированный вид** | Вывод portfolio-integrated-view: содержит ≥5 секций (snapshot, stress, catalyst, verdict, predictions_for_review); либо пользователь говорит «сохрани интегрированный вид» | G |
| **Снапшот портфеля** | JSON с `schema_version: "2.0"` и непустым списком `positions`; вывод portfolio-data-loader; либо пользователь говорит «сохрани снапшот портфеля» | H |
| **Макро-снапшот** | Вывод macro-ru-watcher: `.md` файл с секциями по ставке ЦБ, инфляции, USD/RUB; либо пользователь говорит «сохрани макро-снапшот» | I |
| **Макро-инпут** | YAML с `type: macro-input-chain`; вывод macro-forecast-chain; либо пользователь говорит «сохрани макро-инпут» | J |
| **Коллекция прогнозов** | Файл `fc-{source}-collection-{date}.md` от forecast-collector; либо пользователь говорит «сохрани коллекцию прогнозов» | K |
| **Monitor-report** | YAML с `schema_version: 1`, `type: monitor-report`, `producer: forecast-monitor`; обычно лежит черновиком `_drafts/monitor-report-{date}.yaml` после дайджеста forecast-monitor (без mount — блок в чате `## monitor-report-{date}.yaml`); либо пользователь говорит «сохрани monitor-report», «save monitor», «сохрани отчёт мониторинга» | L |
| **Ad-hoc report** (свободный отчёт от ru-portfolio-advisor) | Markdown файл с YAML frontmatter, содержащий `author: ru-portfolio-advisor` И `kind ∈ {bond_bridge_planner, tactical_rebalance, candidates_outside_ie, scenario_analysis, tax_optimization, retro_calibration, single_analysis, general}`; либо пользователь говорит «сохрани отчёт», «сохрани заметку», «сделай отчёт для памяти», «save this», «put in reports». НЕ активируется при триггерах weekly review | N |
| **Калибровочный отчёт** | Markdown с frontmatter `type: calibration-report` (kind ∈ {adhoc, skill, source_rerating, catalyst}); контент — метрики калибровки по outcome_log (Brier / coverage / weighted-vs-unweighted / trust-дельты); либо пользователь говорит «сохрани калибровку», «сохрани калибровочный отчёт», «сохрани ad-hoc калибровку» | O |
| **Закрытие прогноза по факту** | Фраза «Закрой прогноз <тема>: на <дата> <факт>, прогноз <центр/диапазон> — сбылся \| не сбылся» (из `suggested_action` монитора) либо «закрой с исходом»; артефакта в чате нет — файлы уже в `forecasts/` | `references/close-forecast.md` (роли F7) |
| **Ручная запись журнала решений** (AIR-1) | Ответ владельца на вопрос об отказе («… предлагал X — не сделано. Сознательно?»), «запиши инцидент», итог разбора контрольной точки журнала, открытие/закрытие ставки владельца (`thesis`) | P |
| **Условие или решение по слову владельца** | «добавь / перенеси / сними условие …» (Режим 9 советника), «подтверждаю держать X», «по X решение — …» | M |
| **Справочник бумаг** | «поменяй класс бумаги X», «X — не IPO», «дата листинга X — …», «покажи бумаги класса ipo» | Q |

Если сигналов нет ни в одной категории — спросить:
> Это аудит источника, прогноз, сценарная матрица, ретро-аудит, стресс-тест, еженедельный обзор, интегрированный вид, снапшот портфеля, макро-снапшот, макро-инпут, коллекция прогнозов, monitor-report, свободный отчёт (ad-hoc), калибровочный отчёт или запись журнала решений?

**Особый случай — после forecast-monitor.** Если пользователь только что запускал `forecast-monitor` и теперь говорит «сохрани», искать черновик `_drafts/monitor-report-*.yaml` (Workflow L1.0; блок в чате — только при «черновик не записан») и применять Workflow L. Не спрашивать классификацию.

**Дальше workflow расходится по типам:**

- **Аудит источника** → `Workflow A`
- **Прогноз** → `Workflow B` (сначала черновик `_drafts/<topic>-<дата>` — B1.0; патч HST — `.patch.yaml`, B1.2/B1.3)
- **Сценарная матрица** → `Workflow C` (сначала черновик `_drafts/scenario-<topic>-<дата>` — C1.0)
- **Ретро-аудит** → `Workflow D` (сначала черновик-пара `_drafts/` — D1.0)
- **Стресс-тест портфеля** → `Workflow E` (сначала черновик `_drafts/stress-<дата>-<slug>` — E1.0)
- **Еженедельный обзор** → `Workflow F`
- **Интегрированный вид** → `Workflow G` (сначала черновик `_drafts/integrated-view-<дата>.md` — G1.0)
- **Снапшот портфеля** → `Workflow H`
- **Макро-снапшот** → `Workflow I`
- **Макро-инпут** → `Workflow J`
- **Коллекция прогнозов** → `Workflow K`
- **Monitor-report** → `Workflow L` (сначала черновик `_drafts/monitor-report-<дата>.yaml` — L1.0)
- **Условия и решения по слову владельца** → `Workflow M`
- **Ad-hoc report** → `Workflow N`
- **Калибровочный отчёт** → `Workflow O`
- **Ручная запись журнала решений** → `Workflow P`
- **Справочник бумаг** → `Workflow Q`

Workflow A/B/C используют общую спецификацию `references/events-yaml-spec.md` для генерации `*.yaml`. Workflow E использует свою схему v1 (см. `portfolio-scenario-stress/references/output-template.md`).

**Детальные инструкции по workflow — в reference-файлах. Загружать ровно тот файл, чей workflow выполняется:**

| Workflow | Файл |
|---|---|
| A (Аудит источника) | `references/workflow-a.md` |
| B (Прогноз), C (Сценарии), D (Ретро-аудит), E (Стресс-тест) | `references/workflow-bcde.md` |
| F (Еженедельный обзор), G (Интегрированный вид), H (Снапшот), I (Макро-снапшот), J (Макро-инпут), K (Коллекция) | `references/workflow-fghijk.md` |
| L (Monitor-report) | `references/workflow-l.md` |
| M (Условия и решения по слову владельца) | `references/workflow-m.md` |
| N (Ad-hoc report) | `references/workflow-n.md` |
| O (Калибровочный отчёт) | `references/workflow-o.md` |
| P (Ручные записи журнала решений: отказы, инциденты, контрольные точки, ставки) | `references/workflow-p.md` |
| Q (Справочник бумаг: класс, дата листинга) | `references/workflow-q.md` |
| Смена статуса прогнозов/сценариев (`resolved` / `superseded` / `expired`, роли F7) | `references/status-management.md` |
| Вход «Закрой прогноз <тема> …» / «закрой с исходом» (закрытие по факту, без ретро-аудита) | `references/close-forecast.md` |

Жёсткие инварианты (всегда в силе; детали и процедуры — в соответствующем файле):

- **M, N, Q:** условия (`conditions.yaml`), решения (`decisions/`) и справочник бумаг (`security-attrs.json`) пишут
  только скрипты `apply_condition.py`, `decision_write.py`, `security_attrs.py` — на mount сами (корень `--root`);
  Read/Write/Edit по этим файлам — регрессия. Файла гейтов нет: гейт — проекция последнего решения.
- **Время записи:** ставят скрипты (`time_msk`, МСК с поясом): условиям и решениям — `apply_condition.py` и
  `decision_write.py`, отчёту (N) — `assemble_artifact.py stamp-report`; вручную не писать. Обзору недели (F) —
  тот же `stamp-report` после записи файла: `recorded_at` и `verification_priority` каждой бумаги (функцией движка;
  модель приоритет не заполняет), затем проверка `validate-weekly-review-* --file … --root …` (расхождение — блок).
- **L:** `outcome_log_updates` из monitor-report применяет к `forecasts/` только
  save-to-library — детекторы (monitor/revise) не пишут.
- **P:** `Portfolio/decision-journal/{refusals,incidents,theses}.yaml` — только дописывание; итог контрольной точки —
  решением (`decision_write.py owner`); остальные файлы папки пишет сборка сайта, save-to-library их не трогает.
- **O:** имя файла строго `{prefix}{date}.md` — по basename калибровочный сторож
  forecast-monitor видит маркер; иное имя для сторожа невидимо.
- **Статусы (F7):** save-to-library — единственный, кто закрывает прогнозы и пишет
  `outcome_log`; monitor/revise только находят резолв и предлагают факт.
- `apply_condition.py` вызывает и Режим 9 `ru-portfolio-advisor` напрямую, и сохранение отчёта (N); команды —
  `references/workflow-m.md`.


---

## Сомнения: когда озвучивать, когда молчать

### Озвучивать сомнение (блокирующее — ждать ответа)

- Тип артефакта неоднозначен
- Нет обязательного поля (`source`, `audit_date`, `trust` для аудитов; `forecast_date`, `horizon_date`, `topic`, `domain` для прогнозов; `axis_x`, `axis_y` для сценариев; `period` для ретро-отчётов)
- Subfolder неоднозначен (равный счёт совпадений) — для аудитов
- `include_in_memory = False` — для аудитов
- Найден дубль по `topic` (для прогнозов и сценариев — обязательный выбор a/b/c/d)
- Найден дубль по `source` + `period` (для ретро-отчётов — обязательный выбор a/b/c)
- В прогнозе/сценарии нет технического блока Events YAML и нельзя извлечь обязательные поля
- Mojibake в stress-test артефакте (Workflow E2)
- Stress-test schema v1 не валидна (Workflow E3) — отсутствуют обязательные поля или нарушены семантические инварианты

### Предупреждать (не блокировать)

- Нет рекомендуемого поля (`period`, `last_updated` для аудитов; `confidence` для прогнозов после HST на чужом тексте; `linked_forecast` для ретро-отчётов) — установить дефолт или null+TODO, сообщить
- Subdomain'ы нестандартные, но subfolder однозначен
- Источник уже есть в другом subfolder'е (для аудитов)

### Молчать (всё очевидно)

- Все обязательные поля есть, дублей нет, всё валидно

---

## Anti-patterns

### Schema / валидация

❌ **Сохранять `.md` без парного `.yaml`** в `forecasts/` или `Scenarios/`. Никогда. Если yaml не собирается — спросить пользователя, не сохранять одиночный `.md`.

❌ **Сохранять без валидации.** Минимальная проверка обязательных полей всегда обязательна.

❌ **Угадывать `central_estimate` или `confidence` без FCA.** Только null+TODO, пользователь правит вручную. Для прогнозов с `method: fca` confidence обязателен — не сохранять без него (см. B4.1a). Для `method: manual / external_quoted` null допустим — это явная разметка «прогноз не прошёл агрегацию», и downstream-скиллы (macro-forecast-chain) должны видеть эту разметку и трактовать её корректно.

❌ **Использовать кириллицу в `topic` или `id`.** Slug — всегда транслит ISO 9.

❌ **Включать технические блоки `## Events YAML` в `.md` файл.** Они идут только в `.yaml`.

❌ **Сохранять stress-test YAML без полного покрытия per_position.** E3 проверяет `Σ weight_pct ≥ 98%`. При меньшем покрытии — вернуть в `portfolio-scenario-stress` для перезапуска `compute_per_position.py` с дополненными priors.

❌ **Самостоятельно дописывать обязательные поля schema v1 в Workflow E.**
E3 — блокирующая проверка. При отсутствии `type`, `date`, `portfolio_snapshot_id`,
`caveats`, `weight_type` скилл останавливается и ждёт пользователя. Никакого
«дополняю по контексту», даже если значение восстанавливается тривиально
(`type: portfolio-stress-test` из имени, `date` из `generated_at` и т.п.).
Такое «исправление» — галлюцинация структуры: артефакт перестаёт быть выходом
upstream-скилла. Аудиторский след ломается.

❌ **Создавать portfolio-snapshot вручную** (без вывода portfolio-data-loader). Workflow H принимает только валидный JSON с `schema_version: "2.0"` и проверяет его через `validate-snapshot`. Не сохранять JSON, сгенерированный LLM «на глаз».

❌ **Сохранять weekly-review без `portfolio_snapshot_id`.** Поле обязательно — без него weekly-review нельзя связать со snapshot, и portfolio-integrated-view не сможет загрузить пару.

### Кодировка / ввод-вывод

❌ **Сохранять stress-test с mojibake кодировкой.** Encoding-check (E2) — блокирующая проверка для Workflow E. Артефакт с `Ã—`, `â€™`, `Ðº` и подобными паттернами не сохраняется до регенерации или ручного исправления. Downstream consumers (`portfolio-integrated-view`, `retrospective-forecast-audit`) не толерантны к битой кодировке.

❌ **Сочинять числа в финальном сообщении E8.** E[P&L], range, количество
позиций, scenario IDs, число caveats — всё читается заново из записанного
файла перед составлением сообщения. Любое значение, которое нельзя извлечь
из файла на диске, заменяется на `—` или `(не задано)`. То же правило применяется
к финальным сообщениям других workflow (A8, B8, C8, D8) — если их числа брались
из inputs, а не из записанных файлов, нужно то же исправление.

### D3 / дедуп / раскладка

❌ **Удалять старые файлы при `superseded`.** Помечаем статус, не удаляем. Старые файлы — история.

❌ **Перезаписывать `.md` при добавлении HST patch (flow #1).** Создаём новые файлы; пользователь сам удалит дубли при желании.

❌ **Запускать memory-sync автоматически.** Это отдельный скилл с отдельным confirmation flow.

❌ **Сохранять в корень LIBRARY_ROOT** (минуя subfolders). Если целевой subfolder недоступен (нет прав, не найден) — остановиться и запросить у пользователя: [A] повторить, [B] указать папку вручную, [C] отмена. Никакого молчаливого fallback в корень.

❌ **Молча создавать новый subfolder.**

❌ **Сохранять ретро-аудит в `audits/` или `_audits/`.** Эти папки deprecated. Полный отчёт → `reports/{YYYY-MM-DD}-{source-slug}-{period}.{md|docx}`, сжатый профиль → `domains/{domain}/{source-slug}-{period}.md` — атомарно за один Workflow D.

❌ **Разбивать ретро-аудит на два вызова save-to-library** (сначала отчёт, потом профиль отдельным сообщением). Workflow D атомарный по дефолту: оба файла + два INDEX + одна запись в `_sync_log.md` за один проход. Разделять только по явному флагу `--only=report|profile`.

❌ **Использовать суффикс `-audit` в имени файла в `domains/`.** Старая ошибочная конвенция (`fursov-2020-2024-audit.md` ← так нельзя). Правильно: `fursov-2020-2024.md`.

❌ **Пропускать запись в `_sync_log.md`.** Каждый workflow (A–K) обязан добавить строку в `_sync_log.md`. Без неё теряется audit trail — memory-sync и revise-memory-remote слепые к этой операции.

### Транспорт

❌ **Продолжать Workflow D при недоступном Synology.** INDEX.md и _sync_log.md
правятся только через `Edit`/`Write` на Synology mount; недоступен — остановиться
и запросить у пользователя действие.

❌ **Переписывать черновик `_drafts/` командой Write в библиотеку.** Приёмка — только `promote_draft.py` (`--dry-run`, затем по «да» без него): иначе тело артефакта снова проходит через вывод модели, а черновик остаётся.

❌ **Писать куда-либо, кроме Synology mount.** Если Synology недоступен —
остановиться и сообщить пользователю; альтернативных транспортов нет.
Пользователь должен знать, в какую физическую локацию ушёл файл.

---

## Concurrency Guard (IV-D, R8)

Правило: если одновременно запущены несколько сессий Claude Code (или агент сохраняет, пока пользователь редактирует INDEX.md вручную), конкурентная запись в `Claude-Memory/` может испортить INDEX.md или перезаписать файл. Минимальный lockfile-протокол для Synology mount.

### Протокол pre-write guard

**Шаг 0. Проверить `.lock`** перед любой записью артефакта или INDEX.md:

```
READ Claude-Memory/.lock
```

- Файл **не существует** или содержимое начинается с `RELEASED` → продолжить.
- Файл **существует** с активным содержимым — проверить возраст:
  - **Stale (> 60 мин с момента записи в содержимом)** → выдать предупреждение и перезахватить лок (записать в финальный отчёт: «stale lock overridden»).
  - **Свежий** → сообщить пользователю:
    > ⚠️ `Claude-Memory/.lock` существует: "{содержимое}".  
    > Другая операция сохранения, вероятно, ещё идёт.  
    > [A] Подождать и повторить через 30 сек  
    > [B] Принудительно снять блокировку (если уверены, что операция зависла)  
    > [C] Отмена

  **Не записывать ничего** до явного выбора пользователя (кроме stale-случая).

**Шаг 1. Установить `.lock`** сразу после проверки:

```
WRITE Claude-Memory/.lock:
  "save-to-library | {YYYY-MM-DD HH:MM} | workflow={X} | artifact={filename}"
```

**Шаг 2. Записать артефакт и обновить INDEX.md** (стандартные шаги workflow).

**Шаг 3. Снять `.lock`** — обязательный финальный шаг (чеклист):

- [ ] Перезаписать содержимое лока (transport удалять файлы не умеет — снятие
      лока = перезапись, НЕ создание соседних файлов-маркеров):
      ```
      WRITE Claude-Memory/.lock:
        "RELEASED | save-to-library | workflow={X} | {artifact} | released_at={YYYY-MM-DD HH:MM} MSK"
      ```
- [ ] Убедиться перечитыванием (`READ`), что содержимое начинается с `RELEASED`.
- [ ] ❌ Никогда не создавать `.lock.released-*` / `.lock.deleted*` — эти маркеры
      копились мусором до чистки 2026-08-13. **Не завершать сессию с активным локом.**

Если шаг 2 упал с ошибкой — всё равно выполнить шаг 3 перед показом ошибки пользователю.

### Atomic INDEX.md update (аппроксимация на Synology)

Synology mount не поддерживает atomic rename. Аппроксимация:

1. Прочитать текущий `INDEX.md` → применить изменения в памяти → записать целиком через `WRITE` (или `EDIT` при точечных правках). Lock из шага 1 защищает от конкурентной записи.
2. Новые записи добавлять в конец секции, не в середину — это минимизирует риск конфликтов при параллельном просмотре.

### Примечание об ответственности (план IV-D)

`portfolio-integrated-view` не пишет файлы — скрипт `aggregate_positions.py` работает только с stdin/stdout. Поэтому lockfile-протокол живёт здесь (в `save-to-library`), а не в `portfolio-integrated-view`. Это задокументированное архитектурное решение IV-D Фазы 1.

---

## Структура файлов скилла

- `SKILL.md` (этот файл) — dispatch (Шаг 0 + таблица workflow→файл), глобальные принципы, сомнения, anti-patterns, Concurrency Guard
- `references/workflow-a.md` — Workflow A (Аудит источника)
- `references/workflow-bcde.md` — Workflow B (Прогноз), C (Сценарии), D (Ретро-аудит), E (Стресс-тест)
- `references/workflow-fghijk.md` — Workflow F (Еженедельный обзор), G (Интегрированный вид), H (Снапшот), I (Макро-снапшот), J (Макро-инпут), K (Коллекция)
- `references/workflow-l.md` / `workflow-m.md` / `workflow-n.md` / `workflow-o.md` / `workflow-p.md` / `workflow-q.md` — Workflow L (Monitor-report), M (условия и решения по слову владельца), N (Ad-hoc report), O (Калибровочный отчёт), P (журнал решений), Q (справочник бумаг)
- `references/status-management.md` — смена статуса прогнозов/сценариев (resolved / superseded / expired, роли F7)
- `references/close-forecast.md` — вход «Закрой прогноз <тема> …»: закрытие по факту (outcome_log + resolved + INDEX)
- `references/events-yaml-spec.md` — полная спецификация YAML-схемы Tier 1/Tier 2/scenarios (ОБЯЗАТЕЛЬНО прочитать перед сборкой `.yaml`)
- `references/subfolder-mapping.md` — маппинг trust-subdomain → subfolder для аудитов источников (Workflow A), включая `commodity-agencies`
- `references/transport-layer.md` — Synology mount: пути, типовые операции
- `scripts/assemble_artifact.py` — детерминированная валидация: validate-stress (E3, с anti-drift `label`/`probability`/flat-pnl), validate-forecast (B3+B4.1a), validate-forecast-events (B4), validate-scenario-events (B4), validate-audit (A2), **validate-weekly-review-stock / validate-weekly-review-bond** (F2 детальные, hard-block на TODO_LLM и drift-имена `share_actual_pct`/`ie_share_pct`/`catalysts:`; **catalyst kind v2 schema (METH-1) — обязателен `kind: binary|quantitative`; для quant — `upside_by_scenario` все 4 сценария; для binary — `p ∈ (0, 0.95]` + `upside_pct`; legacy без kind = yellow warning, не блок** — детали в `references/events-yaml-spec.md` §12), validate-weekly-review (router по `type`), validate-snapshot (H2), check-yaml-duplicates (top-level guard), determine-subfolder (A3), compute-inclusion (A4); validate-report / validate-decision и stamp-report (время записи отчёта, N2)
- `scripts/apply_condition.py` — определения условий `conditions@2`: add / edit / withdraw / digest / crosscheck / validate
- `scripts/decision_write.py` — решения `decision@1`: from-report / owner / digest (последнее решение с гейтом и статусами условий)
- `scripts/security_attrs.py` — справочник бумаг `security-attrs@1`: set / get / list
- `scripts/update_index.py` — вставка строк в INDEX.md и `_sync_log.md`
- `scripts/promote_draft.py` — приёмка черновика `_drafts/` (`--kind forecast|scenario|stress|integrated-view|monitor-report|retro-audit`, `--dry-run`, `--replaces`): сборка, валидация, атомарная запись, INDEX, `_sync_log.md`, удаление черновика (B1.0, C1.0, D1.0, E1.0, G1.0, L1.0)
- `tests/` — тесты скриптов (реестр — `docs/test-registry.md` в репозитории)
