---
name: forecast-monitor
description: >
  Еженедельный мониторинг активных прогнозов и сценариев из Claude-Memory.
  Читает все *.yaml из forecasts/ и Scenarios/, проверяет auto_checkable: true
  события через web_search, собирает структурированный алерт-дайджест.

  Используй ОБЯЗАТЕЛЬНО когда пользователь говорит: «проверь прогнозы», «запусти
  монитор», «что нужно проверить по прогнозам», «forecast monitor», «еженедельный
  дайджест прогнозов», «какие события требуют внимания».

  Также запускается автоматически по расписанию (scheduled task, еженедельно).
  Целевая модель — Haiku (data collection + structured output, без сложного reasoning).

  НЕ активировать на: сохранение прогнозов (→ save-to-library);
  построение новых прогнозов (→ forecast-confidence-applier);
  ретроспективный аудит (→ retrospective-forecast-audit).
shared_refs: [transport-layer, events-yaml-spec, yaml-schemas, claude-memory-layout]
---

# forecast-monitor

Еженедельный дайджест активных прогнозов. Проверяет дедлайны, плановые ревью
и auto_checkable события через web_search. Выдаёт структурированный отчёт
с конкретными действиями для каждого алерта.

## Принципы

1. **Только active-прогнозы** — для алертов. `status: superseded/resolved/expired` скрипт
   пропускает сам. Но в payload передаются **все** файлы: калибровочный сторож (M1–M4)
   считает исходы `outcome_log` в том числе по superseded/expired — они живут в основном там.
2. **Просроченное auto_checkable → web_search обязателен.** Не просто "ПРОСРОЧЕНО" —
   ищем и показываем, пробит ли порог.
3. **Жёсткий пост-фильтр по дате.** Любой результат web_search с датой события
   до `search_from_date` — отбрасывается. Сам факт в отчёт не попадает (он вне
   окна проверки). См. Шаг 4.
4. **Контекст последствий.** Каждый алерт содержит: что за тип события, что значит
   если порог пробит, какое конкретное действие требуется.
5. **Структура по прогнозам.** Один блок = один прогноз. Внутри — подпункты по событиям.
6. **Без технических полей в выводе.** id, severity, would_resolve, impact,
   auto_checkable — внутренние поля YAML, в чат не выводятся. Пользователь работает
   с описаниями событий, а не с их машинными идентификаторами.
7. **Транспорт — только Synology mount.** Читать через `Read`/`Glob`.

---

## Шаг 0 — Транспорт и параметры

Прочитай `references/transport-layer.md`. Транспорт один — Synology mount;
недоступен → остановиться и сообщить пользователю.

```
LOCAL_LIBRARY_ROOT = ~/Library/CloudStorage/SynologyDrive-home/Claude-Memory
```

Зафиксируй:
- `TODAY = сегодняшняя дата (YYYY-MM-DD)`
- `N_RED = 7 дней` — симметричное окно ±N для deadlines / monitoring.check_date

**Окно review-триггера** — отдельная логика, зависит от `reviews.interval_months`:
- `interval_months == 1` → ±**5 дней** (плотный график проверок — узкое окно)
- иначе → ±**7 дней**

**Категория «приближается» (yellow upcoming) убрана.** Вне окна молчим — ждём
следующего запуска монитора. Если событие наступило раньше времени и web_search
покажет ❌ ПРОБИТ — это работает через сам web_search, а не через окно.

---

## Inputs / Outputs

**Inputs:**
- `forecasts/*.yaml` ← Claude-Memory/forecasts/ через transport-layer
- `scenarios/*.yaml` ← Claude-Memory/scenarios/ через transport-layer
- `Portfolio/weekly-reviews/weekly-review-stock-*.yaml` ← каталиazar-события (опционально,
  Шаг 1b). Замыкает петлю R7: катализаторы с `auto_checkable: true` из weekly-review
  попадают в алерт-план наравне с прогнозами (кинд `catalyst` в дайджесте).
- `Portfolio/conditions.yaml` (`conditions@2`) ← определения с триггером `report_published`/`event` (Шаг 1c): в payload `conditions` (+ `prior_condition_findings` прошлого отчёта), ищем, вышло ли событие (кинд `condition_event`), находку — в `condition_findings[]` monitor-report (`{condition_id, version, doc, found_at, note}`; `condition_events` упразднено); состояние условия пишет задача hub-notify, не монитор.

**Outputs (всегда оба, не opt-in):**
1. **Дайджест в чат** — markdown-отчёт с приоритизацией для чтения пользователем (Шаг 6).
2. **monitor-report YAML artefact** — структурированный YAML по схеме `monitor-report` из `references/yaml-schemas.md` (раздел 8), пишется черновиком `Claude-Memory/_drafts/monitor-report-{date}.yaml` (Шаг 7.5); в чат — только строка «черновик: …». Пользователь вызывает `save-to-library` без аргументов → Workflow L берёт черновик и кладёт в `Claude-Memory/monitor-reports/monitor-report-{date}.yaml`.

Оба выхода производятся каждым запуском без флагов и opt-in: дайджест — для чтения, YAML — для дашборда. YAML через чат не проходит — тело отчёта не тратит вывод и не теряется при сжатии контекста.

D3-compliance: в библиотеку monitor не пишет; единственная запись — черновик в служебной зоне `_drafts/`, в `monitor-reports/` его переносит save-to-library.

**Upstream скиллы:** —
**Downstream скиллы:** `save-to-library` (Workflow L при opt-in), `portfolio-integrated-viewer.html` (Watchlist tab читает monitor-report), `macro-forecast-chain` (алерт `factor_breach` делает прогноз STALE для цепочки — `coverage_report.py --monitor-report`)
**Shared refs:** transport-layer, events-yaml-spec, yaml-schemas

---

## Шаг 1 — Сбор файлов

Имена файлов: `{topic-slug}-{forecast_date}.yaml` (прогнозы),
`scenario-{topic-slug}-{date}.yaml` (сценарии). Суффикс `-events` — это
значение поля `type:` внутри файла, не часть имени.

```
Glob("*.yaml", path="{LOCAL_LIBRARY_ROOT}/forecasts/")
Glob("*.yaml", path="{LOCAL_LIBRARY_ROOT}/scenarios/")
Glob("*.md",   path="{LOCAL_LIBRARY_ROOT}/calibration/")   # маркеры калибровочного сторожа;
                                                           # папки может не быть → пустой список
```

Из третьего Glob'а взять только **имена файлов** (basename) — они уйдут в payload как
`calibration_files`. Содержимое не читать.

Если Synology недоступен — вызвать `request_cowork_directory`, дождаться доступа,
повторить Glob. Только при явном отказе пользователя → сообщить об ошибке и завершить.

Прочитать каждый файл через `Read` и распарсить YAML. Если файл не парсится →
запомнить как warning для секции ⚠️ Предупреждения.

### Type 1 vs Type 2 routing (events-yaml-spec.md §5.5)

Forecast YAML может быть **Type 1 (isolated)** или **Type 2 (scenario-conditional)**:

- Если содержит `isolated: true` — Type 1. Мониторим только `monitoring`/`deadlines`/
  `falsifiers`/`reviews` блоки. Сценарных триггеров нет.
- Если содержит `conditional_on_scenarios.source_matrix` — Type 2. Также можем мониторить
  сценарную матрицу (Phase 2+ — опционально, не блокируется).
- Если ни того, ни другого — legacy forecast, обрабатываем как Tier 1 (только Шаги 2–5).

Type 1 forecasts не входят в макро-цепочку; передавай в JSON-вход поле `isolated: true`.

### Шаг 1b — Сбор катализаторов из weekly-review (R7, опционально)

Замыкает петлю R7 — отслеживает, сработали ли прогнозируемые катализаторы.

```
Glob("weekly-review-stock-*.yaml", path="{LOCAL_LIBRARY_ROOT}/Portfolio/weekly-reviews/")
```

Для **самого свежего** файла (по дате в имени): прочитать и распарсить YAML, извлечь
из `per_stock.{ticker}.catalyst[]` те катализаторы, где `auto_checkable: true` И
`in_horizon: true`. Собрать список объектов:

```json
{
  "ticker": "SBER",
  "review_date": "2026-06-01",
  "catalyst": {
    "auto_checkable": true,
    "in_horizon": true,
    "date_window": "2027-Q1",
    "trigger": "ROE восстановление через снижение ставки",
    "check_what": "Q4 МСФО ROE ≥ 12%",
    "p": 0.6,
    "upside_pct": 20,
    "source_quality": "HIGH"
  }
}
```

Передать этот список в payload как `weekly_review_catalysts: [...]`.

Скрипт (`_process_weekly_review_catalysts`):
- Для каждого катализатора вычисляет `check_date` из `date_window` (парсер понимает
  квартал `"2027-Q1"`, месяц `"2026-06"`, диапазон `"2026-Q4 to 2027-Q2"`, `"any"` →
  `review_date + 6 мес`).
- Severity: tail-risk downside + p≤0.3 → `critical`; HIGH quality + p≥0.5 → `high`;
  иначе `medium`. Просроченный катализатор (check_date < today) → всегда `red` alert.
- Синтетические записи типа `kind: catalyst` встраиваются в общий поток `active_files`,
  `priority_buckets`, `web_search_plan`.

Если `date_window` не распознан (вернул None) — катализатор пропускается (нет check_date).

**Поля схемы катализатора** (`ru-portfolio-advisor` → `weekly-review-schema.md` §Catalyst tree):
- `auto_checkable: true|false` — числовой/датируемый порог → true; требует интерпретации → false.
- `check_what` (рекомендуется) — наблюдаемый исход, е.г. «Q4 МСФО ROE ≥ 12%». Используется
  как `threshold` в web_search-запросе. Если отсутствует — берётся `trigger`.

В дайджесте (Шаг 6) катализаторы отображаются отдельным блоком «📊 Катализаторы из
weekly-review» с тикером, описанием, check_date и ожидаемым исходом.

---

### Шаг 1c — События отложенных условий (conditions.yaml, с 2026-10-14)

Условие вида «после МСФО 9М…» держится контрольной датой; монитор ищет **само событие**, чтобы
владелец узнал о нём раньше даты (и чтобы на дату было ясно, вышло ли оно).

1. `Read {LOCAL_LIBRARY_ROOT}/Portfolio/conditions.yaml` (`conditions@2`; нет файла → шаг пропустить) и передать
   записи в payload как `conditions` — отбор делает скрипт: последняя версия, не снятое, триггер
   `report_published`/`event`, `valid_until` не в прошлом; что ищем — `event_text`, иначе `trigger.value`;
   контрольная дата — `trigger.window_end`, иначе `valid_until`. Условия бывают и на бумаги вне портфеля — не исключай их.
2. Из **предыдущего** `monitor-reports/monitor-report-*.yaml` (самый свежий) взять `condition_findings[]` и передать
   как `prior_condition_findings` — находка той же версии (`found_at` и `doc`) переносится, повторно не ищется.

Скрипт (`_process_condition_events`) даёт записи `kind: condition_event` в общий план поиска
(контрольная дата прошла или ≤7 дн. → red, иначе yellow) и заготовку `condition_findings` для
monitor-report (Шаг 7). **Монитор `conditions.yaml` и состояние условий не пишет** — находку из сохранённого отчёта
задача hub-notify переносит в состояние условия (`event_found` + `fired`); дальше решает владелец.

## Шаги 2–5 — Делегируется `scripts/monitor_alerts.py`

Вся date-арифметика (фильтрация active, расчёт `search_from_date`, классификация
🔴/🟡 по `reviews.next_due`, `deadlines`, `monitoring.check_date`, `thresholds`,
`falsifiers`), приоритезация и формирование плана web_search **выполняются
скриптом**. Никогда не считай дни и не классифицируй severity вручную: собери
JSON, вызови скрипт, используй результат.

### 2.1 Подготовь JSON-вход

Для каждого распарсенного YAML добавь объект в `forecasts: []`:

```json
{
  "today": "YYYY-MM-DD",
  "n_red_days": 7,
  "n_yellow_days": 14,
  "max_web_searches": 10,
  "forecasts": [
    {
      "basename": "brent-oil-dec-2026-2026-04-30.yaml",
      "type": "forecast-events",         // или scenario-events
      "status": "active",                 // active|superseded|resolved|expired
      "topic": "brent-price",
      "domain": "global-banks",
      "horizon": "2026-12-31",
      "central_estimate": "...",
      "confidence": 0.7,
      "forecast_date": "2026-04-30",
      "reviews": {"next_due": "2026-07-30", "last_completed": null},
      "deadlines":   [ {...} ],
      "monitoring":  [ {...} ],
      "thresholds":  [ {...} ],
      "falsifiers":  [ {...} ],
      "outcome_log": [ {"resolve_date": "...", "record_type": "horizon_resolve|interim_supersession",
                        "kind": "level|event", "actual": null, "resolved": null, "shock_flag": "none"} ],
      "fca_stats":   { "<date>": {"kind": "level|event"} }
    }
  ],
  "calibration_files": ["adhoc-2026-09-14.md"],   // basename'ы из Glob calibration/*.md; нет папки → []
  "catalyst_resolved_count": null                  // int, когда появится учёт catalyst-исходов; пока null
}
```

**Важно для сторожа:** объекты в `forecasts[]` добавляются для **всех** файлов, включая
`superseded`/`expired`, и обязательно с их `outcome_log` (полными записями — `record_type`,
`shock_flag`, `actual`/`resolved`). Active-фильтр для алертов скрипт делает сам.

Свежесть прогноза скрипт считает по датам самого файла: `forecast_date`, горизонт (`horizon_date`,
`horizon_passed` в строке файла и алерт `horizon_passed`). Файла флагов устаревания нет.

### 2.2 Вызови скрипт (compute-режим)

```bash
cat input.json | python3 scripts/monitor_alerts.py
# или: python3 scripts/monitor_alerts.py --input input.json --output plan.json
```

Скрипт возвращает:

- `active_files: []` — для каждого active-прогноза: `search_from_date`,
  список `alerts` с `kind` (`review|deadline|monitoring|threshold|falsifier`),
  `severity` (`red|yellow|none`), `label` («ПРОСРОЧЕНО на 5 дней», «через 12
  дней» и т.п.), `days_delta`, `auto_checkable`, `needs_web_search`,
  `action_hint`. Также проброшены: `description`, `threshold`, `check_date`,
  `impact`, `would_resolve` — всё, что нужно для вывода блока в чат; у `kind: monitoring` —
  `monitoring_id` (id пункта из файла).
- `monitoring_checked: []` — заготовка одноимённого поля отчёта: каждый пункт `monitoring[]` активного
  файла с `check_date` не позже сегодня, включая ручные (`auto_checkable: false`); пункты прогноза с прошедшим
  горизонтом (`horizon_passed`) не входят — их покрывает алерт `horizon_passed`.
- `priority_buckets: {red, yellow, white}` — basename'ы по приоритетам (Шаг 5).
- `web_search_plan: {scheduled, deferred, total_candidates}` — приоритезированный
  план запросов с лимитом `max_web_searches`. Поле `query` уже сформировано
  с `after:{search_from_date}` (Шаг 4). `deferred` — отложенные при превышении
  лимита (получают пометку «лимит запусков — не проверен»).
- `files_skipped: []` — пропущенные (`status != active` или `type` чужой).
- `calibration: {counts, progress_line, milestones, alerts}` — калибровочный сторож M1–M4
  (пороги из handoff §4, детерминированно). `progress_line` — готовая строка прогресса для
  дайджеста; `alerts[]` — сработавшие пороги, каждый с готовыми `label`, `instruction`
  (выводить дословно) и `playbook` (путь к секции `references/calibration-playbook.md`).

LLM использует этот результат как **готовый план**: пробегает `web_search_plan.scheduled`,
делает запросы, потом форматирует дайджест из `active_files` и `priority_buckets`.

---

## Шаг 4 — web_search

Запросы и приоритеты уже сформированы скриптом в `web_search_plan.scheduled`.
Для каждого item в `scheduled` (в порядке списка):

1. Выполнить `web_search` с `query` из плана.
2. Извлечь из лучшего релевантного результата **дату самого события** (не дату
   публикации) и краткий факт ≤20 слов.
3. Прогнать через пост-фильтр (Шаг 4.1).
4. Сформулировать вердикт (Шаг 4.2).

Items из `web_search_plan.deferred` — пометка `(лимит запусков — не проверен)`,
без вызова web_search.

### 4.0 Fan-out субагентам на Haiku (рекомендуется при ≥5 запросов)

Сырые выдачи web_search — главный пожиратель контекстного окна монитора. При
`scheduled` ≥5 items — **не выполняй поиски сам**: разбей план на батчи по 5–8
запросов и запусти по субагенту на батч (**model: haiku**, все батчи одним
сообщением — параллельно). Выдачи живут в окнах субагентов и умирают вместе с
ними; тебе возвращается компактный JSON.

**Промт субагенту (самодостаточный — агент НЕ читает этот SKILL.md и не может
ничего спросить):**

```
Для каждого запроса выполни web_search и верни СТРОГО JSON-массив, по объекту на запрос:
{"query_id": "...", "event_date": "YYYY-MM-DD", "fact": "<=20 слов", "url": "..."}
Правила (нарушение = мусор):
- event_date — дата САМОГО СОБЫТИЯ, не дата публикации страницы.
- fact — только из результатов поиска ЭТОЙ сессии; ничего из своих знаний.
- Нет релевантного результата / дата не извлекается → {"query_id": "...", "status": "none"}.
  Честное "none" лучше догадки.
- Никаких вердиктов и интерпретаций — только извлечение.
Запросы: [{query_id, query}, ...]
```

**Разделение труда жёсткое:** агент только собирает (`event_date`/`fact`/`url`);
пост-фильтр 4.1 (детерминированный скрипт) и вердикты 4.2 делаешь **ты** по его
JSON. Так галлюцинация формата ловится скриптом, а суждение не делегируется.
Ответ агента с нарушенным форматом / вердиктами вместо фактов — отбрасывается,
батч выполняется самостоятельно как раньше (fallback). `status: "none"` маппится
в `⚠️ НЕОПРЕДЕЛЁННО` как обычно.

### 4.1 Пост-фильтр по дате (ОБЯЗАТЕЛЕН)

Оператор `after:` фильтрует ненадёжно. Каждый результат пропускай через скрипт.
Дату события извлекаешь ты из сниппета `web_search` и передаёшь готовым аргументом: дата самого события
(не публикации) → одна ISO-дата `YYYY-MM-DD` → `--event-date`. Дата не извлекается или неоднозначна
(несколько дат, «на прошлой неделе») → `--event-date` опусти или передай пустым: скрипт вернёт `undefined`.
Скрипт сам даты из текста не разбирает. Пример: сниппет «OPEC+ agreed on 15 April to extend cuts…» →
`post-filter --search-from 2026-04-30 --event-date 2026-04-15` → `drop`.

```bash
python3 scripts/monitor_alerts.py post-filter \
    --search-from {search_from_date} --event-date {YYYY-MM-DD}
# stdout: keep | drop | undefined
# exit:    0    | 1    | 1
```

Маппинг вердиктов:
- `keep` → формулировать `✅ НЕ ПРОБИТ` или `❌ ПРОБИТ` (Шаг 4.2)
- `drop` → `⚠️ НЕОПРЕДЕЛЁННО — нет новых событий после {search_from_date}`,
  сам факт в отчёт **не выводить**.
- `undefined` (дата события не извлекается) →
  `⚠️ НЕОПРЕДЕЛЁННО — дата события не определена`.

### 4.2 Вердикт

```
✅ НЕ ПРОБИТ — {краткий факт ≤20 слов от {date}} | Источник: {URL}
❌ ПРОБИТ — {краткий факт ≤20 слов от {date}} | Источник: {URL}
⚠️ НЕОПРЕДЕЛЁННО — {причина} (требует ручной проверки)
```

В факте всегда указывать **дату события**, не дату публикации источника.
Если web_search вернул нерелевантный результат → `⚠️ НЕОПРЕДЕЛЁННО`.

---

## Шаг 5 — Классификация приоритетов

Готова в `priority_buckets` от скрипта. Особый случай — **апгрейд** буцкета по
результатам web_search:

- если `falsifier` показал `❌ ПРОБИТ` И `would_resolve: true` → перенести
  basename из `yellow` в `red` (это единственный апгрейд, который скрипт сделать
  не может — он не знает результат web_search).

Остальные правила (`deadline ≤ 7д`, `next_due` просрочен, `monitoring critical`
просрочен) уже учтены скриптом.

---

## Шаг 6 — Сборка дайджеста

Дайджест — выжимка прогона и единственное, что монитор печатает в чат; выводится после записи черновика YAML (Шаг 7.5).

### Принципы оформления для чата

- Между блоками алертов — **пустая строка + горизонтальный разделитель `---`**.
  Чат склеивает абзацы без явных разделителей.
- Внутри блока алерта — пустая строка между подпунктами.
- Технические поля YAML (`id`, `severity`, `would_resolve`, `impact`,
  `auto_checkable`, `monitoring.id`) **не выводятся**. Пользователь работает с
  описаниями событий, а не с их машинными идентификаторами.
- Глоссарий типов событий — внутри `<details><summary>...</summary>...</details>`,
  чтобы не занимать место по умолчанию.

### Структура отчёта

```
# 📋 Forecast Monitor — {DD.MM.YYYY}

**Активных прогнозов:** {N}  
**Проверено событий:** {M}  
**web_search выполнено:** {K}/10

---

<details>
<summary>Глоссарий типов событий</summary>

| Тип | Что это | Если порог пробит |
|---|---|---|
| **МОНИТОРИНГ** | Индикатор-триггер с числовым порогом | прогноз провалился / подтверждён / неоднозначно |
| **ДЕДЛАЙН** | Дата ключевого события; после неё требуется действие | Выполнить действие из карточки прогноза |
| **ПОРОГ** | Значение переменной, при котором прогноз «переключается» на альтернативный сценарий | Прогноз меняет направление → запустить FCA |
| **ФАЛЬСИФИКАТОР** | Событие, которое опровергает прогноз | Прогноз закрывается (→ save-to-library) или существенно ослаблен |
| **РЕВЬЮ** | Плановая переоценка прогноза | Запустить forecast-confidence-applier |
| **ГОРИЗОНТ** | Горизонт прогноза прошёл (приоритет над РЕВЬЮ) | Закрыть прогноз с исходом; обновлять нечего |
| **ИСХОД** | Резолв-точка наступила, факт ещё не зафиксирован в outcome_log | web_search факт → outcome_log_updates → save-to-library пишет (калибровка §14) |

</details>

---

## 🔴 ТРЕБУЮТ ВНИМАНИЯ СЕЙЧАС

### ▸ {basename}

**[{domain} | горизонт: {horizon} | confidence: {confidence}]**  
Проверка с: {search_from_date}  
Центральная оценка: «{central_estimate}»

**[РЕВЬЮ]** — ПРОСРОЧЕНО на {N} дней

→ **Действие:** скажи Claude `/forecast-confidence-applier Обнови прогноз {basename}`.

**[ГОРИЗОНТ]** — прошёл {N} дней назад ({horizon})

→ **Действие:** `/save-to-library Закрой прогноз {тема}: на {дата горизонта} {факт}, прогноз {центр/диапазон} — сбылся | не сбылся`. Детали — `references/horizon-passed.md`.

---

**[ДЕДЛАЙН]** {deadline.description} — через **{N} дней** ({date})

→ **Действие:** {deadline.action}

---

**[МОНИТОРИНГ]** {monitoring.description}

Порог: {threshold} | срок проверки: {check_date}  
Если пробит: прогноз {invalidated/supported/mixed-формулировка человеческими словами}  
web_search: ✅ НЕ ПРОБИТ — Brent $67/bbl от 28.04.2026 | Источник: {URL}

→ **Действие:** ничего, продолжить мониторинг.

---

## 🟡 ПРОВЕРИТЬ НА ЭТОЙ НЕДЕЛЕ

### ▸ {basename}

**[{domain} | горизонт: {horizon}]**  
Проверка с: {search_from_date}

**[ФАЛЬСИФИКАТОР]** «{falsifier.description}»

Если произошло: прогноз ЗАКРЫВАЕТСЯ.  
web_search: ✅ НЕ ПРОБИТ — событие не зафиксировано после {search_from_date} | Источник: {URL}

→ **Действие:** ничего.

---

**[ПОРОГ]** {threshold.variable} — {threshold.condition}

Если выполнено: прогноз переходит в «{flips_to-человеческими словами}».  
web_search: ⚠️ НЕОПРЕДЕЛЁННО — данных недостаточно (требует ручной проверки)

→ **Действие:** проверить вручную, при необходимости запустить FCA.

---

## ⚪ БЕЗ ИЗМЕНЕНИЙ

| Файл | Центральная оценка | Следующее ревью |
|---|---|---|
| {basename} | {central_estimate} | {next_due} |

---

## 🎯 Калибровочный сторож

{calibration.progress_line}

*(если calibration.alerts непусты — для каждого алерта, дословно из скрипта:)*

**[{id}] {label}**

→ **Действие:** {instruction}

→ **Инструкция целиком:** `{playbook}` (репозиторий claude_skills)

---

## 🧭 Портфельный сторож

*(секция выводится ТОЛЬКО если `portfolio_watch` в выводе скрипта не null)*

**[{portfolio_watch.id}] {portfolio_watch.label}**

Сработало по: {для каждого источника — `{basename}` ({kinds})}

→ **Действие:** {portfolio_watch.instruction}

→ **Рубрика:** `{portfolio_watch.rubric}` (репозиторий claude_skills)

> Почему это отдельный сторож: `sanctions_position` в стресс-тесте — слепок
> санкционного статуса эмитентов на дату. Новый пакет или снятие мер делают его
> устаревшим, но числа остаются правдоподобными, и устаревание незаметно.
> Пересобирать **по рубрике**, а не по памяти: полосы, поправки и якоря там
> заданы именно затем, чтобы значения не переопределялись каждый раз заново.

---

## ⚠️ Предупреждения парсинга

- {filename} — {причина} *(если есть)*

---

## 📌 Итог и следующие шаги

### 🔴 Требуют действий немедленно

**1. {Краткое описание действия 1}**
- {basename} — {что нужно сделать}
- → скажи Claude: `/{скилл} {что сделать} {basename}` · {модель из model-routing}

**2. {Краткое описание действия 2}**
- ...

### 🟡 Требуют внимания на этой неделе

- **{basename}** — {краткое резюме} → `/{скилл} {что сделать} {basename}`

### 📅 Следующий запуск монитора: {TODAY + 7 дней}
```

### Правила форматирования

- **Каждое действие в «Итоге» — готовая команда** в `коде`, которую пользователь вставит в чат
  как есть: `/<скилл> <глагол> <id прогноза/сценария>` (не «запустить FCA»). Та же фраза идёт в
  `suggested_action` YAML — по ней вьюер («Действия», «скопировать») и утреннее уведомление.
  Действий нет — «ничего делать не нужно». **Ручная проверка — тоже через скилл**, который потом
  обновит артефакт: «проверить проект бюджета» → `/forecast-confidence-applier Обнови прогноз
  budget-deficit-ru-….yaml`, «проверить подписание закона» → `/sanctions-positions`. Фраза без
  `/скилл` блокирует сохранение (save-to-library L3, `validate-monitor-report`): без имени скилла
  чат начинает без контекста проекта (кейс 26.10, «Лайм-Займ»).
- Если секция 🔴 пуста → `🔴 Срочных алертов нет` (без подзаголовков-прогнозов).
- Если секция 🟡 пуста → `🟡 Алертов на этой неделе нет`.
- Сортировка внутри секций: `critical` → `high` → `medium` → нет severity.
- Метки типов всегда в квадратных скобках: `[МОНИТОРИНГ]`, `[ДЕДЛАЙН]`,
  `[ФАЛЬСИФИКАТОР]`, `[ПОРОГ]`, `[РЕВЬЮ]`, `[ГОРИЗОНТ]`.
- `search_from_date` выводить в каждом блоке прогноза — пользователь видит,
  за какой период проверялось.
- Вердикты web_search: `✅ НЕ ПРОБИТ` / `❌ ПРОБИТ` / `⚠️ НЕОПРЕДЕЛЁННО` —
  всегда с источником и датой события.
- Между каждым блоком алерта (внутри одного прогноза тоже) — горизонтальный
  разделитель `---` на отдельной строке, окружённый пустыми строками.

---

## Anti-patterns

❌ **Алерт без вердикта для auto_checkable.** Если поле `auto_checkable: true` и
событие попало в окно проверки — web_search обязателен, даже если check_date просрочена.
"ПРОСРОЧЕНА" без результата поиска бесполезно.

❌ **Цитировать события до search_from_date.** Если web_search вернул событие до
`search_from_date` — оно отбрасывается, в отчёт идёт `⚠️ НЕОПРЕДЕЛЁННО — нет новых
событий после {date}`. Пользователь видел это событие в предыдущем запуске.

❌ **web_search без временного фильтра.** Всегда `after:{search_from_date}` в
запросе **И** пост-фильтр по дате события (Шаг 4.1).

❌ **Выводить технические поля YAML.** `id`, `severity`, `would_resolve: true`,
`(invalidates)`, `(impact: mixed)`, `auto_checkable` — не выводить в чат.
Пользователь не помнит и не должен помнить машинные имена. Тип события
(`[МОНИТОРИНГ]`, `[ФАЛЬСИФИКАТОР]` и т.д.) — выводить, остальное — нет.

❌ **Термины без объяснения.** ФАЛЬСИФИКАТОР, ПОРОГ, МОНИТОРИНГ — всегда с
однострочным пояснением последствий в блоке алерта (формулировкой для человека,
не машинным `impact: invalidates`).

❌ **Глоссарий по умолчанию раскрытый.** Глоссарий типов событий — всегда внутри
`<details>`. Пользователь раскроет если нужно.

❌ **Слипшиеся блоки.** Между алертами — пустая строка и `---`. Чат рендерит
markdown иначе, чем .md-файл; без явных разделителей абзацы склеиваются.

❌ **Изменять yaml-файлы прогнозов.** Монитор — read-only для `forecasts/` и `Scenarios/`.
Захваченные исходы (`outcome_log`, §14.3) монитор **не пишет** в forecasts напрямую — только
кладёт в `outcome_log_updates[]` своего monitor-report; физическую запись делает
`save-to-library` Workflow L (D3 сохраняется).

❌ **Делать выводы о прогнозах.** Только факты: пробит / не пробит / неопределённо.
Интерпретацию делает пользователь.

❌ **Инферить статусные переходы в прозе дайджеста.** Монитор НЕ утверждает «прогноз заменён
матрицей X», «superseded», «resolved» и т.п. — статус он читает из поля `status` YAML, а не
выводит из контекста (реальный инцидент: дайджест 2026-07-05 ошибочно назвал scenario-usd-rub-sept
«заменён матрицей ru-west»). Если статус в файле не тот, что ожидался — это факт для показа
(«status в файле: active»), а не повод для собственного вывода. Смену статуса делает
save-to-library по решению пользователя.

❌ **Писать куда-либо при недоступном Synology.** При ошибке — сначала
`request_cowork_directory`, не помогло → остановиться и сообщить пользователю.

❌ **Терять пункт мониторинга с прошедшей датой.** Каждая строка заготовки `monitoring_checked` попадает в
отчёт алертом с `monitoring_id` или строкой `monitoring_checked`, иначе save-to-library отчёт не сохранит.

❌ **Более 10 web_search за запуск.** Приоритет по severity, остальные → пометка
`(лимит запусков — не проверен)`.

---

## Шаг 7 — monitor-report YAML artefact (всегда, Phase 10.3)

Производится автоматически после Шага 6, без opt-in. YAML пишется черновиком в `_drafts/` (7.5), чтобы:
- save-to-library взял его из файла при следующем вызове пользователя (Workflow L1.0);
- portfolio-integrated-viewer.html (Watchlist tab) питался им после сохранения.

Пользователь не указывает никаких флагов — просто запускает `forecast-monitor`, читает дайджест, вызывает `save-to-library` если хочет архивировать.

### 7.1 Сборка YAML

Из тех же данных, что использовались для Шага 6 дайджеста, собрать YAML по схеме `references/yaml-schemas.md` раздел 8 (`type: monitor-report`):

```yaml
schema_version: 1
type: monitor-report
generated_at: "{ISO8601 текущего момента}"
producer: "forecast-monitor"
horizon_window_days: 7
scope: full | partial            # partial — пользователь назвал файлы или тему; full — без указаний (можно опустить)
checked: ["{target_file}"]       # только при partial, обязательно: проверенные файлы прогнозов и сценариев

alerts:
  - severity: HIGH | MEDIUM | LOW | INFO
    category: stale | horizon_passed | event_window | factor_breach | source_dead | prediction_due | catalyst_missed
    target: "{forecast-id или scenario-id}"
    target_file: "{относительный путь от Claude-Memory/}"
    target_kind: forecast | scenario | catalyst | source | view
    message: "{короткое описание для viewer}"
    detected_at: "{YYYY-MM-DD}"
    web_search_summary: "{опц. краткая сводка результата web_search}"
    suggested_action: "{готовая фраза для чата Claude, та же, что в «Итоге» дайджеста: `/<скилл> <что сделать> <id>`}"
    monitoring_id: "{опц.: алерт по пункту monitoring[] — monitoring_id из вывода скрипта, не придумывать}"

monitoring_checked:             # пункты с прошедшей датой без алерта — заготовка скрипта `monitoring_checked`
  - target: "{topic}"
    target_file: "{forecasts|scenarios}/{basename}.yaml"
    monitoring_id: "{id пункта}"
    check_date: "{YYYY-MM-DD}"
    result: met | not_met | unverified   # порог достигнут / не достигнут / не проверено (ручной пункт, нет данных)
    note: "{≤20 слов; при unverified — почему}"

freshness_audit:
  integrated_view: { age_days, next_due, due_for_refresh }
  stress: { age_days, threshold_days, due_for_refresh, message }
  weekly_review: { age_days, threshold_days, due_for_refresh }
  macro_snapshot: { age_days, threshold_days, due_for_refresh }
  trust_matrix: { age_days, threshold_days, due_for_refresh }

predictions:
  total_active: <int>
  overdue_count: <int>
  due_30d_count: <int>
  overdue_list:
    - { id, file, days_overdue }

condition_findings:             # Шаг 1c — заготовка из вывода скрипта `condition_findings`, дозаполнить
  - condition_id: "{id условия}"   # по итогам web_search; найденное раньше — перенести как есть
    version: <int>                 # версия определения из заготовки
    doc: "{URL|null}"              # ссылка на вышедший документ — ТОЛЬКО при keep пост-фильтра и явном факте выхода
    found_at: "{YYYY-MM-DD|null}"  # дата публикации события, не страницы; не найдено — null
    note: "{≤20 слов|null}"

outcome_log_updates:            # §14.3 — захваченные исходы (опционально; см. 7.6)
  - target_file: "forecasts/{basename}.yaml"
    resolve_date: "{YYYY-MM-DD}"   # горизонт/дата события — по какой записи outcome_log
    kind: level | event
    actual: <num|null>            # level: факт (Brent $/bbl, ставка %)
    resolved: <0|1|null>          # event: наступило/нет
    actual_source: "{URL}"
    shock_flag: none | exogenous_shock
    detected_at: "{YYYY-MM-DD}"

caveats:
  - { severity: INFO, message: "..." }
```

### 7.2 Mapping дайджеста → YAML

| Из дайджеста (Шаг 6) | В monitor-report YAML |
|---|---|
| `🔴 ТРЕБУЮТ ВНИМАНИЯ` | `alerts[*]` с `severity: HIGH` |
| `🟡 ПРОВЕРИТЬ НА ЭТОЙ НЕДЕЛЕ` | `alerts[*]` с `severity: MEDIUM` |
| `🟢 МОНИТОРИНГ` | `alerts[*]` с `severity: LOW` |
| `[РЕВЬЮ] просрочено` | `category: stale` |
| `[ГОРИЗОНТ] прошёл` | `category: horizon_passed` (вместо `stale`, если горизонт < даты прогона) |
| `[ДЕДЛАЙН]` | `category: event_window` |
| `[МОНИТОРИНГ]` факторного индикатора | `category: factor_breach` (если пробит) |
| `[ФАЛЬСИФИКАТОР]` | `category: catalyst_missed` |
| Пункт `[МОНИТОРИНГ]` с прошедшей датой | алерт с `monitoring_id` (есть что поднять) или строка `monitoring_checked` — один к одному с заготовкой скрипта: строка заготовки, по которой нет алерта, остаётся в отчёте; «нечего сказать» = `result: unverified` с `note`. Пункты прогноза с алертом `horizon_passed` покрыты им (прогноз закрывают с исходом) — скрипт их в заготовку не выдаёт, строк не нужно |
| `[СОБЫТИЕ УСЛОВИЯ]` (`kind: condition_event`) | **не** `alerts[]` — строка `condition_findings[]` (заготовка от скрипта + итог поиска); в дайджесте — блок «📌 События условий»: «{ticker}: {event} — вышло {дата} / пока не найдено (контрольная дата {deadline})» |
| Глоссарий, статистики | не входят в YAML — это для людей |
| 🎯 Калибровочный сторож | `caveats[]`: progress_line → `severity: INFO`; каждый сработавший M-алерт → `severity: MEDIUM`, `message: "{id}: {label} → {instruction}"`. Категории `alerts[]` не расширяем — схема §8 не меняется |

### 7.3 Freshness audit

Дополнительно к Шагам 1–5 проверить возраст артефактов в Portfolio/ и заполнить `freshness_audit`:

| Артефакт | Где | Threshold |
|---|---|---|
| integrated-view | `Portfolio/integrated-views/integrated-view-*.md` | 180 дней (next_due из frontmatter если есть) |
| stress | `Portfolio/stress/stress-*.yaml` | 90 дней |
| weekly-review | `Portfolio/weekly-reviews/weekly-review-*.yaml` | 14 дней |
| macro-snapshot | `macro-snapshots/ru-*.md` | 14 дней |
| trust_matrix | `INDEX.md` (`trust_matrix_extracted_at` из integrated-view fm) | 90 дней |

Latest по типу выбирается по дате в имени файла. `due_for_refresh: true` если `age_days > threshold_days`.

### 7.4 Predictions

Сканировать активные прогнозы из `forecasts/*.yaml`, `Portfolio/integrated-views/integrated-view-*.md` секция §7 и `Portfolio/coherence-audits/coherence-audit-*.md` блок `predictions_for_review` (тот же формат, что §7 integrated-view; папки может не быть — тогда молча пропустить). Для каждого с `next_due` вычислить:
- `overdue_count` — сколько с `next_due < today`
- `due_30d_count` — сколько с `next_due in [today, today+30d]`
- `overdue_list` — детализация по просроченным.

### 7.6 Захват исходов — `outcome_log_updates` (§14.3, калибровка)

Когда событие/уровень **резолвится**, монитор уже достал факт web_search'ем на Шаге 4 —
этот факт нельзя терять (раньше фиксировался только статус, отсюда 0 записей «прогноз vs факт»
в библиотеке, self-audit §7). Монитор **захватывает** исход в `outcome_log_updates[]`, но
**сам в `forecasts/` не пишет** (D3 + read-only-контракт): физическую запись в forecast YAML
делает `save-to-library` Workflow L при сохранении отчёта.

**Триггер теперь детерминированный (F7).** `monitor_alerts.py` сам сканирует резолв-точки
каждого прогноза (`outcome_log.resolve_date` + `fca_stats`-ключи + `horizon`) и на каждую
наступившую без зафиксированного исхода выдаёт alert **`kind: outcome_capture`** + запрос в
`web_search_plan`. Раньше захват жил только в этой прозе → монитор детектил резолв, но факт в
`outcome_log` не клал (реальный промах: iran-us-may-deal, monitor-report-2026-07-05 без
`outcome_log_updates`). Теперь: **пройди `web_search_plan.scheduled` items с `kind:
outcome_capture`**, для каждого достань факт на `resolve_date` и заполни `outcome_log_updates[]`.
Чтобы это работало — передавай `outcome_log`/`fca_stats`/`horizon` в JSON-вход (Шаг 2.1).

Заполнять `outcome_log_updates` при любом из триггеров резолва (все они теперь дают
`kind: outcome_capture` от скрипта):
- `[ФАЛЬСИФИКАТОР]` / `[МОНИТОРИНГ]` показал **`❌ ПРОБИТ`** для события с датой (заседание ЦБ,
  OPEC-решение) → `kind: event`, `resolved: 1` (или `0`, если явно НЕ произошло к дате), плюс
  `actual` уровня, если он числовой (напр. ставка после заседания).
- Достигнут **горизонт** level-прогноза, и web_search дал факт → `kind: level`,
  `actual: <число>`.
- `actual_source` = URL из вердикта Шага 4.2; `detected_at` = today; `shock_flag:
  exogenous_shock`, если движение вызвано явным внешним шоком (иначе `none`).

**Приоритет — микропрогнозы** (заседания ЦБ ~раз в 6 недель, OPEC, недельная инфляция): они
резолвятся за недели и дают калибровочную выборку уже к осени. При лимите web_search
приоритизировать их резолвы над дальними горизонтами.

Правила заполнения `actual`/`resolved` — **без фабрикации**: если факт из web_search не
извлекается однозначно (`⚠️ НЕОПРЕДЕЛЁННО`) — update **не создавать** (пусть резолвится в
следующий запуск). Никакой арифметики (`error_pct`/`in_p10_p90`) монитор не считает — это
делает `save-to-library` helper'ом. Если резолвов нет — `outcome_log_updates: []`.

### 7.5 Черновик в файл, в чат — строка

После сборки YAML и pre-emit-проверки (ниже) запиши его через `Write` на mount (`references/transport-layer.md`)
в `{LOCAL_LIBRARY_ROOT}/_drafts/monitor-report-{YYYY-MM-DD}.yaml` — то же имя получит файл в `monitor-reports/`.
Запись — до вывода в чат (дайджест печатается после); YAML в чат не печатается, под дайджестом одна строка:

```
черновик: `_drafts/monitor-report-{YYYY-MM-DD}.yaml` — сохранить: «save-to-library», файл уйдёт в `Claude-Memory/monitor-reports/`.
```

Mount недоступен — YAML блоком в чат после дайджеста (заголовок `## monitor-report-{YYYY-MM-DD}.yaml`) и фраза
«черновик не записан». Владелец просит «выведи полностью» — YAML дополнительно печатается в чат.

**Частичный прогон:** если пользователь назвал файлы или тему — `scope: partial` и `checked` с каждым проверенным файлом, иначе вьюер примет отчёт за полный и скроет предупреждения по всем остальным файлам; в `alerts` — только проверенные файлы, тишина по файлу в `checked` означает «сейчас без предупреждения».

**Pre-emit (до записи черновика):** у каждого HIGH/MEDIUM `suggested_action` начинается с `/скилл`;
в `alerts[]` нет записей про условия (`target: condition …`) — находки только в `condition_findings[]`;
каждая строка заготовки `monitoring_checked` — в отчёте алертом с её `monitoring_id` или строкой.
Те же правила проверяет save-to-library (`validate-monitor-report --root`) и не сохранит отчёт с нарушением.

D3-compliance: monitor сам не пишет в библиотеку, только черновик в `_drafts/`. Сохранение — отдельный явный вызов save-to-library Workflow L.

---

## Структура файлов скилла

- `SKILL.md` — основная логика монитора
- `scripts/monitor_alerts.py` — детерминированный планировщик алертов
  (фильтрация active, классификация по дате, горизонт, web_search plan, post-filter).
  Без внешних зависимостей. Тесты:
  `tests/test_monitor_alerts.py`.
- `references/transport-layer.md` — Synology mount: пути, типовые операции
- `references/events-yaml-spec.md` — полная спецификация YAML-схемы
- `references/calibration-playbook.md` — инструкции по сработавшим порогам калибровочного
  сторожа M1–M4 (что и как гонять; самодостаточен — рассчитан на чтение без контекста)

## Скрипты

`scripts/monitor_alerts.py` принимает один JSON со списком распарсенных YAML
и возвращает готовый план: алерты с severity/label, web_search queries с
лимитом и приоритетами, горизонт каждого файла. Поддерживает две команды:

- `compute` (default) — основной планировщик (Шаги 2–5, 7).
- `post-filter` — однострочный фильтр web_search-результата по дате
  (Шаг 4.1). Возвращает `keep|drop|undefined`, exit-code = 0 для keep.

**Правило:** ни одна date-классификация (включая «горизонт прошёл»)
не выполняется LLM вручную. Web_search и markdown-дайджест — за LLM, всё
остальное — скрипт.

