---
name: macro-forecast-chain
description: >
  Оркестратор макропрогнозного пайплайна для портфеля на Мосбирже. Читает снапшот
  портфеля → определяет нужные факторные прогнозы → проверяет Claude-Memory →
  запускает FCA/scenario-builder в DAG-порядке → собирает macro_input матрицу
  для portfolio-scenario-stress.
  Три режима: FULL — полный пайплайн с запуском недостающих прогнозов (~2–3 ч);
  QUICK-REFRESH — staleness-проверка + обновление протухших (~20 мин);
  PARTIAL — matrix строго из имеющегося, без FCA, MISSING/STALE как явные caveats.
  Выход: macro-input-YYYY-MM-DD.yaml + coverage report. Только анализ — никаких рекомендаций купить/продать.
shared_refs: [transport-layer, yaml-schemas, claude-memory-layout, rebuild-plan-template, events-yaml-spec]
---

# macro-forecast-chain

Язык вывода — русский. Всегда.

Оркестрирует прогнозы в правильном порядке причинно-следственных зависимостей.
Сам прогнозов не делает — только координирует FCA, scenario-builder, HST.

---

## Inputs / Outputs

**Inputs:**
- `Portfolio/snapshots/portfolio-<date>.json` ← portfolio-data-loader, Synology mount
- `forecasts/*.yaml`, `scenarios/*.yaml` ← из Claude-Memory через transport-layer

**Outputs (как artefact в чат):**
- `macro-scenarios-<date>.yaml` (Layer 2 bundle для stress-test) → пользователь проверяет → save-to-library кладёт в `Claude-Memory/macro-chain/`
- `macro-marginal-<date>.yaml` (Layer 1 для weekly-review EV) → опц., тот же путь

**Обработка типов прогнозов (events-yaml-spec.md §5):**

| Тип forecast | Поведение | Куда уходит |
|---|---|---|
| **Type 2 conditional** (`conditional_on_scenarios.by_scenario`) | Включается в `macro-scenarios-<date>.yaml` bundle с per-scenario значениями | Stress-test через `portfolio-scenario-stress` |
| **Type 1 isolated** (`isolated: true`) | Включается в `macro-marginal-<date>.yaml` как точечная оценка (одно значение для всех 4 сценариев); в `macro-scenarios-<date>.yaml` НЕ попадает напрямую — в bundle для конкретного фактора используется как baseline (constant across scenarios) | Weekly-review EV через `ru-portfolio-advisor` (опц.) или `portfolio-integrated-view` |
| **Без маркера** (ни `isolated`, ни `conditional_on_scenarios`) | Reject с ошибкой `MISSING_SCENARIO_ATTRIBUTION` — нарушение спецификации, требует ручного фикса (явно поставить `isolated: true` или собрать `conditional_on_scenarios`) | — |

**Сценарная атрибуция Type 2 — динамическая (D8):** при сборке Type 2 forecast через `forecast-confidence-applier` (Шаг 1.5B) LLM классифицирует источники к сценариям по контенту прогноза. Атрибуция записывается inline в forecast YAML (`provenance: inferred_from_content`, `sources_used` как объекты с `camp_weight`/`reasoning`). `macro-forecast-chain` читает уже готовое — он не делает атрибуцию сам.

**Upstream скиллы:** portfolio-data-loader, forecast-confidence-applier, scenario-builder
**Downstream скиллы:** portfolio-scenario-stress, ru-portfolio-advisor (опц., через macro-marginal), portfolio-integrated-view
**Shared refs:** transport-layer, yaml-schemas, claude-memory-layout

---

## Принципы

1. **Минимально необходимый набор.** Не строить прогноз нефти, если нет нефтянки в портфеле.
2. **DAG-порядок строго соблюдается.** Downstream-прогноз всегда строится ПОСЛЕ upstream.
3. **Два явных checkpoint.** Скилл не действует автономно — ждёт подтверждения на шагах 4 и 7.
4. **Staleness ≠ блокировка.** Информирует и предлагает варианты — не блокирует.
5. **Версионирование.** Каждая сборка матрицы получает run_id и diff vs предыдущий run.
6. **Caveats передаются downstream.** Все расхождения, stale-прогнозы и низкие confidence
   автоматически попадают в caveat-блок macro_input.yaml.

---

## Reference-файлы

Читай нужный файл перед соответствующим шагом:

- `references/dependency-map.md` — DAG зависимостей факторов + правила upstream-контекста
- `references/sector-factor-matrix.md` — маппинг сектор→обязательные факторы + тикеры
- `references/staleness-config.md` — пороги устаревания по типу прогноза (для людей; реализовано в скрипте)
- `references/consistency-rules.md` — правила проверки внутренних противоречий (для людей; реализовано в скрипте)
- `references/transport-layer.md` — Synology mount: пути, типовые операции
- `references/coverage-report-template.md` — шаблон Coverage Report (Шаг 3)
- `references/mode-selection-template.md` — шаблон выбора режима (Шаг 3.5)
- `references/rebuild-plan-template.md` — шаблон emit-plan markdown-инструкции (Шаг 4-plan)
- `references/macro-input-schema.md` — полная схема macro_input.yaml (output contract, Шаг 8b)

## Скрипты

- `scripts/check_macro_scenarios.py` — годится ли `macro-scenarios` для расчёта стресса: пять числовых факторов, значения по датам у каждого сценария, спот (Шаг 8b)
- `scripts/check_source_files.py` — warning на факторы bundle без `source_files`; блок `forecast_files` из них (`--forecast-files`) и его проверка (Шаг 8b)
- `scripts/coverage_report.py` — детерминированные расчёты Шагов 2.3, 3, 3.5, 6:
  age × horizon → итоговый статус (worst-of-two), Coverage Score,
  автоматическая рекомендация режима (FULL/QUICK-REFRESH/PARTIAL),
  consistency check сценариев; `--monitor-report` — пробой из отчёта монитора → STALE (PyYAML);
  `--spot` — расхождение центра прогноза со спотом макроснимка → STALE.
  Тесты: `tests/test_coverage_report.py`.

- `scripts/recalibrate.py` — RECALIBRATE-mode (D7): lazy weight update без LLM-вызовов,
  <30 секунд. Читает веса — файл сайта `scenarios/stress-weights-<матрица>.json`, если он есть, иначе матрицу, — пересчитывает Layer 2 marginals
  в forecast YAML с `conditional_on_scenarios`, обновляет modal/hedge ranking в
  macro-scenarios YAML. Режимы: soft (auto-recalculate + warning) и `--strict` (отказ
  при stale). Зависимость: PyYAML; с `ruamel.yaml` файлы правятся точечно (комментарии и формат сохраняются), без него — переписываются целиком с предупреждением в `warnings`. Тесты: `tests/test_recalibrate.py`.

**Правило:** статусы фактора, рекомендация режима и проверка пар факторов —
только через скрипт. LLM делает: чтение прогнозов через transport, парсинг
YAML, формирование текстового отчёта Шага 3 (с эмодзи и форматированием),
диалог с пользователем в Checkpoint 1/2.

---

## Шаг 0 — Транспорт

Читать `references/transport-layer.md`. Транспорт один — Synology mount;
недоступен → остановиться и сообщить пользователю.

**Режим НЕ запрашивается здесь.** Сначала выполняются Шаги 1–3
(Pre-flight статус-обзор портфеля и Claude-Memory), после чего пользователь
выбирает режим на основе реальной картины (Шаг 3.5). Это позволяет принять
осознанное решение: понятно, что именно устарело, что отсутствует и сколько
это займёт.

Исключение: если пользователь явно назвал режим в запросе — зафиксировать
его и пропустить Шаг 3.5.
Названный режим не фиксируется, если `coverage_report.py` вернул `matrix_replaced`: переходи в FULL —
прогнозы на заменённой матрице пересобираются на действующей.

| Признак в запросе | Режим |
|-------------------|-------|
| «full», «полный пайплайн», «запусти всё» | **FULL** — перейти к Шагу 1 |
| «quick-refresh», «что устарело», «обнови» | **QUICK-REFRESH** — перейти к Шагу 1 |
| «partial», «как есть», «без FCA», «быстрая матрица» | **PARTIAL** — перейти к Шагу 1 |
| «assemble-only», «без FCA», «собери из готовых», «только сборка» | **ASSEMBLE-ONLY** — Шаги 1–3 + сразу Шаг 8 (bundle из существующих forecast YAML) |
| Не указан | **UNKNOWN** — выполнить Шаги 1–3, затем Шаг 3.5 |

**Эмит-плановый модификатор (любой режим):** если в запросе/ответе пользователя присутствует одно из ключевых слов — `план`, `plan`, `инструкция`, `выдай план`, `только план`, `не запускай`, `я сам`, `я сам запущу` — устанавливается флаг `emit_plan = true`. Скилл генерирует markdown-план для запуска FCA в отдельных чатах вместо запуска FCA в текущей сессии. См. **Шаг 4-plan** ниже. Для **RECALIBRATE** и **ASSEMBLE-ONLY** флаг игнорируется (FCA не запускаются).

**Поведение в каждом режиме (справка для Шагов 4–8):**

- **FULL** — Шаги 1–8 полностью, Checkpoint 1 и 2 обязательны. С `emit_plan: true` — после Шага 3.5 переход в Шаг 4-plan, FCA не запускаются здесь.
- **QUICK-REFRESH** — Шаги 1–4 (coverage/staleness) + при явном согласии
  пользователя перезапустить только stale-прогнозы. Шаг 8 — только если все
  нужные прогнозы FRESH. С `emit_plan: true` — план только по STALE-прогнозам.
- **PARTIAL** — Шаги 1–3, затем сразу Шаг 8 в режиме «as-is» (FCA не вызывается,
  Checkpoint 1 пропускается, consistency check Шаг 6 ограничен только FRESH
  факторами). MISSING/STALE → явные caveats в matrix с пометкой
  `data_gap: true` и `severity: critical|medium|low`. `emit_plan` не применим.
- **ASSEMBLE-ONLY** — Шаги 1–3 (coverage check для информации) → сразу Шаг 8 (сборка bundle). FCA не запускаются. Используется как **финальный шаг после emit-plan**: пользователь выполнил все FCA в отдельных чатах, теперь собирает `macro-scenarios-{date}.yaml` + `macro-marginal-{date}.yaml` из готовых forecast YAML. Если каких-то факторов не хватает — warning + bundle с пропусками + caveat.

---

## Шаг 1 — Sector-Awareness

Прочитать `references/sector-factor-matrix.md`.

### 1.0 — Override lookup (приоритет выше основной таблицы)

Выполнить до обращения к статической матрице. Три источника переопределений,
применяются в порядке убывания приоритета:

**Приоритет 1 — Снапшот портфеля (`required_factors` в holdings):**
```json
{ "ticker": "IVAT", "sector": "tech", "required_factors": ["cbr_rate", "usdrub"] }
```
Если поле `required_factors` присутствует — использовать его напрямую, матрицу
для этого тикера не читать. Если только `sector` — использовать его для lookup
в таблице сектор→факторы.

**Приоритет 2 — `Claude-Memory/sector-overrides.yaml`:**
```yaml
overrides:
  - ticker: IVAT
    sector: tech
    note: "IVA Technologies, добавлен вручную"
  - ticker: RU000A108G35
    sector: bonds_rub
    asset_type: bond
  - ticker: SMLT
    sector: real_estate
    extra_factors: [inflation_ru]   # добавляются к стандартным факторам сектора
```
Читать файл если существует (не блокировать если нет). Поле `extra_factors` —
дополняет стандартный набор сектора, не заменяет его.

**Приоритет 3 — Статическая матрица** из `sector-factor-matrix.md` (для всех
тикеров без override).

### 1.1 — Сбор снапшота и тикеров

`portfolio-data-loader` пишет снапшоты в `Claude-Memory/Portfolio/snapshots/`
(переменная `PORTFOLIO_SNAPSHOTS` из `references/transport-layer.md`).

1. **Канонический путь:** `Glob("portfolio-*.json", path=PORTFOLIO_SNAPSHOTS)` →
   взять файл с максимальной датой в имени.
2. **Если нет** → вывести явную ошибку:
   ```
   ✗ Снапшот портфеля не найден в PORTFOLIO_SNAPSHOTS.
     Действие: запусти portfolio-data-loader на свежих trades_portfolio_*.xlsx
              (или Общий баланс.numbers для holdings-only снапшота).
   ```
3. **При наличии снапшота** — извлечь holdings, отфильтровать `is_blocked: false`,
   собрать список тикеров для Шага 1.2.

### 1.2 — Разрешение тикер → сектор → факторы

Для каждого тикера:
1. Проверить `required_factors` в снапшоте → если есть, использовать напрямую
2. Проверить `sector-overrides.yaml` → если есть, использовать (+ `extra_factors`)
3. Иначе — искать в статической матрице
4. Если нигде не найден → **UNMAPPED** (см. 1.3)

Собрать union всех факторов → **минимально необходимый набор**.

### 1.3 — Обработка UNMAPPED тикеров

**🛑 BLOCKING CHECKPOINT: переход к Шагу 2 запрещён, пока есть незакрытые
UNMAPPED.** Скилл обязан получить от пользователя `Y / N / manual` по
**каждому** тикеру до выполнения Шага 2. Inference без подтверждения
**не** записывается в `sector-overrides.yaml` и **не** включается в
`required_factors` — это типовая ошибка, приводящая к скрытым пробелам в
матрице (например, PLZL ошибочно классифицируется как «Металлы» и
теряется фактор `xauusd`).

Для каждого UNMAPPED тикера:

```
⚠ UNMAPPED: {ticker}
  asset_type: {из снапшота, если есть}
  Вывод на основе контекста: {сектор} → {факторы} (confidence: low)
  Добавить в sector-overrides.yaml? [Y / N / вручную укажи сектор]
```

Inference по тикеру: использовать web_search («{ticker} MOEX сектор деятельность»)
если тикер совсем неизвестен. При подтверждении пользователя — записать в
`Claude-Memory/sector-overrides.yaml` через транспорт.

**Алгоритм блокировки:**
1. Собрать список всех UNMAPPED тикеров за один проход.
2. Вывести их единым блоком с inference по каждому.
3. Дождаться явных Y/N/manual ответов по каждому. При `Y` или `manual` —
   записать в `sector-overrides.yaml` (или подготовить запись для записи
   через `save-to-library` в конце цепочки, если так настроено).
4. Только после этого переходить к Шагу 2.

Если пользователь отвечает «N» по тикеру — пометить его в caveats как
`UNMAPPED_ACCEPTED` и исключить из расчёта required_factors (а не
«пропустить с inference»).

Тикеры с `asset_type: bond` без маппинга — двухступенчатая классификация:

1. **Сначала проверить замещающую природу** (FX-synthetic). Бумага считается
   замещающей, если выполнено любое из:
   - в `name` есть маркеры: `ЗО`, `-Д`, `-Е`, `ЗамО`, `Замещ`, `USD-link`, `EUR-link`
   - issuer входит в якорный список замещающих эмитентов
     (`sector-factor-matrix.md` → раздел «Облигации FX-synthetic»)

   Для замещающих → сектор `bonds_fx_synthetic`, факторы из матрицы
   (`usdrub, sanctions`), **не** `cbr_rate` как primary. `currency: RUB` в
   снапшоте у замещающих игнорируется — переоценка идёт через usdrub.

2. **Иначе по `currency`:** `RUB` → `bonds_rub`, прочее → `bonds_fx`.

Если по тикеру неоднозначно — выводить как UNMAPPED (см. 1.3) и спрашивать
пользователя.

### 1.4 — Финальный вывод

```
Секторы в портфеле: Нефтегаз, Банки, Золото, ОФЗ, Корп.облигации RUB
Источник маппинга: матрица (8), overrides (1), снапшот (2), UNMAPPED (1→inference)
Необходимые факторы (9):
  geopolitics, sanctions, brent, urals_discount,
  usdrub, inflation_ru, cbr_rate, xauusd, budget_deficit
```

---

## Шаг 2 — Inventory из Claude-Memory

Прочитать `references/dependency-map.md` для порядка сканирования.
Прочитать `references/staleness-config.md` для порогов и horizon-coverage rules.

### 2.1 — Целевые горизонты текущей цепочки

Перед сканированием зафиксировать `chain_target_horizons` — список дат, которые
должна покрывать матрица. Умолчание для квартального стресс-теста:

```yaml
chain_target_horizons:
  - "2026-12-31"   # near (EOY текущего года)
  - "2027-12-31"   # far  (EOY +1)
```

Есть `scenarios/horizons.json` — `chain_target_horizons` = все даты его `horizon_ends`; файл сроков меняет только сайт.
Пользователь назвал другие даты — сказать о расхождении с файлом сроков и спросить, не меняя файл.
Файла нет — умолчание выше; если пользователь явно указал другие горизонты в запросе («собери матрицу до
2027-Q2») — использовать их. Этот список передаётся всем последующим шагам
и записывается в `macro_input.yaml`.

### 2.2 — Сканирование Claude-Memory

1. Glob `forecasts/*.yaml` и `scenarios/*.yaml`; прогноз фактора искать по колонке «topic у файлов» из `dependency-map.md` — слаг справочника у ставки и дисконта Urals не совпадает с темой файлов
2. Для каждого файла извлечь: `topic`, `forecast.date`, `forecast.horizon`
   (или `forecast.horizons` — список), `forecast.confidence`,
   `forecast.central_estimate`, `forecast.method`, `forecast.upstream_snapshot`
3. Свежесть — по датам самого прогноза (`forecast.date`, горизонт); файла флагов устаревания нет
4. Пробой: прогноз с алертом `factor_breach` в последнем отчёте монитора — STALE независимо от даты
   («пробой по монитору от <дата отчёта>»); считает `coverage_report.py --monitor-report <Claude-Memory/monitor-reports>`,
   у фактора во входе — `forecast_file` (путь прочитанного прогноза)
5. Расхождение со спотом: центр ближайшего горизонта дальше от спота последнего макроснимка, чем порог фактора
   (`references/staleness-config.md`), — STALE (`STALE_VS_SPOT`); спот берёт `coverage_report.py --spot
   <Claude-Memory/macro-snapshots> --root <Claude-Memory>` (свежайший из срезов скилла и автосрезов сайта)
6. Заменённая матрица: прогноз, чей `conditional_on_scenarios.source_matrix` указывает на матрицу с `superseded_by`, —
   STALE независимо от даты (`MATRIX_REPLACED`): его значения по сценариям даны для прежних осей. Считает
   `coverage_report.py --root <Claude-Memory>` по `forecast_file` фактора; такой прогноз пересобирается на
   действующей матрице — RECALIBRATE и сборка «как есть» его не обновляют

### 2.2a — Интерпретация confidence по method

Поле `forecast.method` определяет, как трактовать `confidence`:

| `method` | `confidence: null` | `confidence: число` | Действие в chain |
|----------|--------------------|--------------------|------------------|
| `fca` | ❌ невозможно — это битая запись (save-to-library должен был заблокировать) | ✓ нормальная FCA-агрегация | Если всё-таки встретили `null` — пометить как `BROKEN_RECORD`, требует rebuild через FCA. Блокирует FULL/QUICK-REFRESH (предлагать перезапустить FCA или временно перевести в method: manual). В PARTIAL — caveat `severity: critical`. |
| `manual` | ✓ ожидаемое значение — прогноз введён вручную | ✓ субъективная оценка (`confidence_method: subjective`) | Caveat `NO_CONFIDENCE` (не блокирующий). В matrix фиксируется с пометкой «непрошедшая агрегацию оценка». |
| `external_quoted` | ✓ обычное значение — цитата без агрегации | ✓ цитированная вероятность | Caveat `NO_CONFIDENCE` (не блокирующий). В matrix трактуется как single-source view. |
| отсутствует / null | — | — | Backward compatibility: трактовать как `manual` + caveat `LEGACY_FORMAT_NO_METHOD`. Предложить пользователю при первой возможности обновить запись. |

Это позволяет пайплайну работать с прогнозами разной природы (агрегированные FCA,
ручные оценки, цитаты CEO/аналитиков) без блокировки, но с прозрачной разметкой
качества каждой оценки в финальной матрице.

### 2.2b — caveat-типы для качества оценки

Типы caveats (`BROKEN_RECORD`, `NO_CONFIDENCE`, `LEGACY_FORMAT_NO_METHOD`, `INSUFFICIENT_HORIZON`,
`MISSING_BY_SCENARIO`, `ALTERNATIVES_NOT_RECORDED` и остальные) и их severity — реестр в
`references/macro-input-schema.md` («Поле caveats»); здесь не дублируются.

### 2.3 — Расчёт статуса по двум осям: age × horizon-coverage

**Делегировано `scripts/coverage_report.py`** — пороги, классификация и
worst-of-two считает скрипт. LLM передаёт распарсенные YAML-прогнозы как
JSON (`{factors: [{name, forecast_file, forecast_date, horizon_dates, method, confidence,
schema_version, needed}]}`) и папку `monitor-reports/` аргументом `--monitor-report`, скрипт возвращает row для
каждого фактора с `overall_status`, `is_blocking`, `caveats` (при пробое — `stale_reason`, `monitor_breach`;
с `--spot` — `spot_check`).

Описание правил (для справки и аргументации в отчёте):

**Age-status** (по `staleness-config.md`):
- `FRESH` — age ≤ порог × 0.75
- `AGING` — порог × 0.75 < age ≤ порог
- `STALE` — age > порог
- `VERY_STALE` — age > порог × 2

**Horizon-status:**
- `COVERS` — самый дальний `horizon` прогноза ≥ всех `chain_target_horizons`
- `INSUFFICIENT_HORIZON` — самый дальний horizon < хотя бы одного целевого

**Итоговый статус (worst-of-two):**
| age | horizon | итог |
|-----|---------|------|
| FRESH | COVERS | `✓ FRESH` |
| FRESH | INSUFFICIENT_HORIZON | `⚠ FRESH-but-short` (нужен extend) |
| STALE | COVERS | `⚠ STALE` |
| STALE | INSUFFICIENT_HORIZON | `⚠ STALE+SHORT` (rebuild целиком) |
| любой | (прогноз отсутствует) | `✗ MISSING` |

Также:
- `⚠ NO_CONFIDENCE` — прогноз есть и age в порядке, но `forecast.confidence: null`
  (например, manually-quoted без FCA-агрегации). Не блокирует, но идёт в caveats.
- `— NOT NEEDED` — фактор не нужен для данного портфеля

В реальной сессии 2026-05-03 `usdrub` имел horizon до 2026-09-01 при
`chain_target_horizons = [2026-12-31, 2027-12-31]` — это `⚠ FRESH-but-short`,
а не `✓ FRESH`. Старая версия скилла такие случаи не отлавливала автоматически.

---

## Шаг 3 — Coverage Score + Staleness Report

Вызови `scripts/coverage_report.py` с JSON, собранным в Шаге 2.3. Скрипт
возвращает `summary` с числами FRESH/STALE/MISSING/BROKEN, `coverage_score`,
`ready_for_stress_test` и `blocking_issues`. LLM использует эти данные для
форматирования вывода ниже (саму таблицу собирай вручную, чтобы не терять
кириллические эмодзи и форматирование колонок).

В таблицу добавлены колонки `Method` и `Horizon`:
показывать `BROKEN_RECORD`/`NO_CONFIDENCE`/`INSUFFICIENT_HORIZON`/`LEGACY_FORMAT`
непосредственно в строке фактора, а не только в caveats — так проблемы видны
до построения плана.

→ Шаблон отчёта: читай `references/coverage-report-template.md`

Там же описаны:
- структура колонок
- пример заполнения
- правила сортировки по DAG
- резюме критичных проблем

---

## Шаг 3.5 — Выбор режима (на основе статус-обзора)

**Пропустить, если режим был зафиксирован в Шаге 0** (пользователь явно назвал его).

Если режим UNKNOWN — предложить выбор, опираясь на только что показанный
Coverage Report. Пользователь видит реальное состояние системы ДО принятия
решения, а не наоборот.

→ Шаблон промпта: читай `references/mode-selection-template.md`

Там же описаны:
- таблица автоматической рекомендации (правила выбора режима)
- переменные для подстановки
- пример с расшифровкой
Таблица для справки:

| Условие | Рекомендация |
|---------|-------------|
| 0 MISSING + 0 STALE | PARTIAL — всё FRESH, просто собрать матрицу |
| 0 MISSING + 1–3 STALE + 0 critical | QUICK-REFRESH — пересобрать протухшие |
| ≥1 MISSING ИЛИ ≥4 STALE ИЛИ ≥1 critical | FULL — существенные пробелы |
| ≥1 прогноз на заменённой матрице (`matrix_replaced`) | FULL — пересобрать эти прогнозы на действующей матрице |

**Жёсткое правило:** critical — это `BROKEN` у требуемого фактора; при нём режим QUICK-REFRESH
**запрещён**, допустимы FULL или PARTIAL (пересобирается только сломанный фактор).

После ответа пользователя — зафиксировать режим и перейти к Шагу 4.

---

## Шаг 4 — Checkpoint 1: план действий (ждать ответа пользователя)

**В режиме PARTIAL Шаг 4 пропускается** — сразу перейти к Шагу 8 (as-is сборка
матрицы). FCA не запускается, Checkpoint 1 не показывается. Если пользователь
явно скажет «всё-таки запусти эти прогнозы» — переключиться в FULL и вернуться
к Шагу 4.

Сформировать единый план запуска: каждой строке плана сопоставить
upstream-зависимости из `references/dependency-map.md` со статусом каждой
зависимости. Это позволяет пользователю видеть, что именно надо пересобрать
и в каком порядке — независимо от того, MISSING это фактор или STALE.

### 4.1 — Cascade-проверка staleness

До формирования плана: пройти DAG снизу вверх. Если хотя бы один upstream-фактор
имеет статус MISSING или STALE — downstream-фактор помечается флагом
`needs_rebuild_after_upstream`, даже если его собственный age в пределах порога.
STALE по пробою монитора (`stale_reason` строки `coverage_report`) каскадирует так же, причина — «пробой по монитору от <дата>».

Пример: если `inflation_ru` MISSING, то `cbr_rate` помечается
`needs_rebuild_after_upstream` с указанием конкретной upstream-причины.
Это применяется одинаково и к MISSING-, и к STALE-факторам — пользователь должен
видеть всю цепочку, а не только первый разрыв.

### 4.2 — Формат плана (единый для Missing и Stale)

```
План запуска (в порядке DAG):

# Упорядочено по DAG-уровню. В колонке «Зависит от» каждый upstream
# показан со своим статусом: ✓ FRESH, ⚠ STALE, ✗ MISSING, ⟳ запланирован.

#  Фактор          Действие   Зависит от                                 Источник промпта
─────────────────────────────────────────────────────────────────────────────────────────────
[1] sanctions       Запустить  geopolitics ✓ FRESH                       FCA
[2] budget_deficit  Запустить  sanctions ⟳ (шаг 1), brent ✓              FCA
[3] urals_discount  Обновить   sanctions ⟳ (шаг 1), brent ✓              FCA  ← STALE,
                                                                              нужен rebuild
                                                                              т.к. upstream
                                                                              sanctions меняется
[4] usdrub          Запустить  brent ✓, sanctions ⟳ (шаг 1),
                               budget_deficit ⟳ (шаг 2)                  FCA
[5] xauusd          Запустить  geopolitics ✓, usdrub ⟳ (шаг 4)           FCA
[6] cnyrub          Запустить  usdrub ⟳ (шаг 4)                          FCA
[7] inflation_ru    Запустить  usdrub ⟳ (шаг 4),
                               budget_deficit ⟳ (шаг 2)                  FCA
[8] cbr_rate        Обновить   inflation_ru ⟳ (шаг 7)                    FCA  ← STALE,
                                                                              auto-rebuild:
                                                                              upstream меняется

Использовать как есть: [2] geopolitics ✓, brent ✓

Cascade-флаги (нужно пересобрать после upstream):
  cbr_rate          ← inflation_ru обновляется на шаге 7
  urals_discount    ← sanctions обновляется на шаге 1

Варианты:
  [A] Выполнить всё (8 прогонов FCA/scenario-builder)        ← рекомендуется
  [B] Только Missing-факторы (6 прогонов); STALE принять как есть
       — но имей в виду: cbr_rate и urals_discount будут с устаревшим
       upstream-контекстом. Это попадёт в caveats матрицы.
  [C] Указать конкретный список вручную
  [D] Принять всё как есть, записать caveats в матрицу
       (равно режиму PARTIAL — переключиться?)

Ожидаю выбор.
```

**Ключевая идея формата.** Один и тот же фактор может потребовать пересборки
по трём разным причинам:
1. Сам устарел (age > порога) или отсутствует.
2. Upstream-фактор пересобирается → текущий прогноз построен на устаревшем контексте.
3. Самый дальний horizon прогноза не покрывает `chain_target_horizons` →
   нужен extend (Действие = «Extend» в плане), без полной пересборки.

Колонка «Действие» отражает, что именно нужно сделать:
- `Запустить` — прогноза нет (MISSING)
- `Обновить (age)` — прогноз STALE по дате
- `Обновить (upstream)` — cascade-флаг, upstream меняется
- `Extend` — FRESH по дате, но `INSUFFICIENT_HORIZON` (расширить, не пересобирать с нуля)
- `Rebuild` — STALE+SHORT (и устарел, и горизонт мал — полная пересборка)

Колонка «Зависит от» показывает upstream-причины явно. Выбор [B] (только Missing)
оставит cascade- и horizon-факторы с устаревшим/коротким контекстом — это явный
trade-off, не скрытый.

**Дополнительный вариант — emit-plan modifier:**

Если в ответе пользователя присутствуют ключевые слова `план`, `plan`, `инструкция`,
`выдай план`, `только план`, `не запускай`, `я сам`, `я сам запущу` (в любом
сочетании с выбором A/B/C/D или конкретным режимом) — установить флаг
`emit_plan: true`. Вместо Шага 5 (запуск FCA в этой сессии) перейти в **Шаг 4-plan**
(генерация markdown-инструкции). Примеры приёма:

- `A план` / `план A` / `выдай план для всех 8 прогонов`
- `план — я сам запущу FCA в отдельных чатах`
- `только инструкция, не запускай`
- `B, но дай план` (план только по missing, остальные as-is)

После ответа — перейти к Шагу 5 (или к Шагу 4-plan при `emit_plan: true`, или к Шагу 8 при варианте [D]).

---

## Шаг 4-plan — Генерация markdown-плана (вместо Шага 5)

**Активируется** при `emit_plan: true` в Шаге 4 или при явном `--emit-plan`:
вместо запуска FCA в этой сессии выдаётся markdown-инструкция «какие FCA в каком
порядке запустить в отдельных чатах» по шаблону `references/rebuild-plan-template.md`.
Процедура (Glob существующих active-forecast → `replaces:`, структура документа,
финальный `--mode ASSEMBLE-ONLY`) и anti-patterns промптов (orchestrator НЕ делает
работу FCA: никаких интерпретаций неосевых факторов, anchor-значений и копий
сценариев в промпте) — **загрузи `references/emit-plan-mode.md` при активации**.

---

## Шаг 5 — Запуск прогнозов в порядке DAG

Схема шага (фактор → метод → сценарий → обратная связь) — в `references/dependency-map.md`, раздел «Схема шага 5: фактор → метод → сценарий → обратная связь».

Прочитать `references/dependency-map.md` — там порядок запуска, upstream-контекст
для каждого фактора, **и per-factor translation для geopolitics-матрицы**
(секция «Geopolitics → downstream: per-factor translation»).

### 5.0 — Geopolitics translation pre-pass

**Запускается один раз перед любыми downstream-прогнозами.** Цель — определить,
как именно каждый downstream-фактор будет потреблять Shell-матрицу geopolitics.

1. Прочитать актуальный `forecasts/geopolitics-*.yaml` (или scenario-matrix
   из `scenarios/`). Извлечь все 4 сценария с вероятностями + axis-значения
   (если scenario-builder их предоставил).
2. Прочитать `modal_flag` из scenario YAML.
   - `modal_flag: no_modal` (Pure Shell D1, default) → `modal_scenario = none`,
     ни один сценарий не выбирается как «основной».
   - `modal_flag: weighted` (пользователь явно задал custom веса) → найти
     сценарий с максимальной вероятностью; если `max(p_i) ≥ 0.40` — это
     `modal_scenario`, иначе всё ещё `none`.
3. Для каждого фактора в плане Шага 4 — взять `geopolitics_translation` класс
   из таблицы в `dependency-map.md` (linear / nonlinear / axis_dependent /
   indifferent).
4. Зафиксировать в журнале запуска: какой translation применяется к какому
   фактору. Это попадёт в caveats `macro_input.yaml` и в YAML каждого
   downstream-прогноза.

**Под `modal_scenario: none` (штатное состояние D1):** для nonlinear-факторов
обязательно собирать блок `conditional_on_scenarios.by_scenario` со значениями
по всем 4 сценариям равной глубины — никакой «primary vs short-form» асимметрии,
все 4 запроса равноправны (см. Шаг 5.1). Никаких caveats об этом не
поднимается — это default-путь.

**Вывод пользователю после 5.0:**
```
━━━ Geopolitics translation map ━━━
Modal scenario: none (Pure Shell D1, equal weights 0.25 × 4)
                 [или Sc-{id} «{label}» (p={modal_p}) при weighted]

Фактор             Translation        Что передаётся в FCA
─────────────────────────────────────────────────────────────────
sanctions          axis_dependent     ось «sanctions», значение из матрицы
brent              nonlinear          by_scenario: 4 равноправных запроса (Sc-A/B/C/D)
budget_deficit     linear             взвешенное среднее 4 сценариев
urals_discount     axis_dependent     ось «sanctions»
usdrub             nonlinear          by_scenario: 4 значения
xauusd             linear             взвешенное среднее (низкий вес geopolitics)
cnyrub             nonlinear (через usdrub)
inflation_ru       linear
cbr_rate           linear
```

### 5.1 — Запуск каждого фактора

Для каждого фактора из утверждённого плана:

1. **Применить translation** из 5.0 — выбрать соответствующий промпт-шаблон
   из `dependency-map.md` (секция «Промпт-шаблоны для Шага 5»). Для nonlinear
   при `modal_scenario: none` (D1) — запросить FCA на каждом из 4 сценариев
   равной глубины и записать все 4 значения в блок
   `conditional_on_scenarios.by_scenario`. При `modal_scenario != none`
   (weighted-режим) — основной FCA на модальном + short-form на остальных
   3 сценариях в `alternatives:`. Для linear — один FCA-запрос на условиях
   взвешенного среднего сценариев. Для axis_dependent — без FCA, значение
   читается из оси scenario-матрицы.

2. **Сформировать остальной промпт** со ссылкой на другие upstream-прогнозы:
   - Тема, горизонт (`chain_target_horizons`), домен
   - В секции «Контекстные допущения» — central_estimate из upstream
     (kроме geopolitics — он подаётся через 5.0 translation)
   - Sensitivity-вопрос: «при отклонении X на Y% — как меняется?»

3. **Вызвать нужный скилл:**
   - `scenario-builder` → только для geopolitics (если её самой ещё нет)
   - `forecast-confidence-applier` → для всех остальных факторов

4. **После получения результата** — вызвать `save-to-library`. В YAML прогноза
   будет записан блок `geopolitics_translation` (см. dependency-map.md).

5. **Обновить внутренний статус** фактора: MISSING/STALE → FRESH

6. **Вывод прогресса после каждого фактора:**
   ```
   ✓ [3/7] cbr_rate — готов (central: 15% к 2026-12-31, confidence 0.71,
                              translation: linear)
   ⟳ [4/7] xauusd — запускаю (translation: linear)...
   ```

### 5.2 — Особенность для nonlinear-факторов: alternatives запись

После основного FCA-запроса на модальный сценарий, для каждого nonlinear-фактора
запустить **3 short-form FCA** на остальных сценариях. Цель — не полная
агрегация, а индикативная оценка central_estimate ± P10/P90 при условном
сценарии. Это нужно для:

1. **Tail-risk анализа** в `portfolio-scenario-stress` — стресс-тест прогоняет
   сценарии-альтернативы, чтобы пользователь видел, что будет с портфелем,
   если реализуется НЕ модальный сценарий.
2. **Retrospective audit** — если факт реализовался по альтернативному
   сценарию, можно сверить, насколько хорошо были оценены альтернативы.

short-form FCA = 3–5 источников, без full-aggregation, явно с пометкой
«conditional on Sc-{X}, indicative only». Записывается в YAML фактора:

```yaml
forecast:
  central_estimate: "..."
  alternatives:
    - scenario_id: "Sc-B"
      probability: 0.28
      central_estimate: "..."
      indicative: true
      sources_used: 3
    - scenario_id: "Sc-C"
      probability: 0.22
      central_estimate: "..."
      indicative: true
      sources_used: 3
    # Sc-D аналогично
```

Если у пользователя ограничено время — Шаг 5.2 можно пропустить (сообщить и
зафиксировать в caveat `ALTERNATIVES_NOT_RECORDED`).

---

## Шаг 6 — Consistency Check

**Делегировано `scripts/coverage_report.py`** — все правила пар факторов и
тройных комбинаций из `references/consistency-rules.md` реализованы в
функции `check_consistency_pair`. LLM передаёт сценарии в `scenarios_to_check:
{label: {brent_pct_change, usdrub_pct_change, rate_bps_change, ...}}` и
получает в output поле `consistency: {violations_by_scenario, counts,
compatible, total}`. Никогда не сравнивай сам — пропустишь редкие комбинации.

Для каждого нарушения правила — вывести объяснение и степень серьёзности:

```
━━━ Consistency Check ━━━

⚠ ПРЕДУПРЕЖДЕНИЕ (Medium):
  Brent +8% YoY & USD/RUB +6% — нетипично
  Нефть↑ обычно укрепляет рубль. Возможная причина: санкционный
  разрыв в нефтяной премии. Требует: обоснования или подтверждения.

✓ ОК:
  Ставка ЦБ −200 б.п. & Инфляция 7.5% — совместимо при снижении инфляции
  Brent +8% & Urals discount $13 — реалистично при текущих санкциях

Критичных противоречий: 0
Предупреждений: 1
```

---

## Шаг 7 — Checkpoint 2: подтверждение (ждать ответа пользователя)

```
Consistency check завершён. Одно предупреждение требует подтверждения:

⚠ Brent↑ + рубль↓ — нетипичная комбинация.
  Принять как допущение? Если да — объясни причину (она попадёт в caveats матрицы).

Варианты:
  [A] Принять, причина: [введи объяснение]
  [B] Пересмотреть прогноз USD/RUB
  [C] Пересмотреть прогноз Brent
```

После подтверждения — перейти к Шагу 8.

---

## Шаг 8 — Сборка macro_input.yaml

### 8a — Diff vs предыдущий run

Найти предыдущий `macro-input-*.yaml` в `Claude-Memory/macro-chain/`.
Если есть — показать diff:

```
vs предыдущая матрица (2026-03-20):
  cbr_rate:    18% → 15% (−300 б.п.)
  brent:       $68 → $75 (+10%)
  usdrub:      без изменений
  inflation:   8.2% → 7.5% (−0.7 п.п.)
```

### 8b — Формирование файла

→ Полная схема файла: читай `references/macro-input-schema.md`

У каждого фактора записывай `source_files` — точные файлы прогнозов, из которых взяты числа (Layer 1 и Layer 2). Файл пиши с `schema_version: 2` и блоком `forecast_files: {<фактор>: "<имя файла прогноза без расширения>"}` рядом с `factors` — его печатает `scripts/check_source_files.py --forecast-files <macro-scenarios>.yaml` из `source_files` (руками не собирать). После сборки прогоняй `scripts/check_source_files.py <macro-scenarios>.yaml`: без `forecast_files` новый файл не проходит (код 1) — вьюер не дойдёт от стресса до прогнозов и не покажет «есть новее». Затем прогоняй `scripts/check_macro_scenarios.py <macro-scenarios>.yaml --root <Claude-Memory>`: код 1 — стресс по такому файлу не посчитается (нет фактора, сценария, числового `value` по датам или спота) либо прогноз фактора построен на другой матрице, чем файл; файл не выдавай, пока не исправлены все отказы из перечня. Предупреждения о расхождении `pct_vs_spot` с `value` сообщи пользователю.

Там содержится:
- полный аннотированный YAML template с примерами
- описание всех полей и их типов
- таблица типов caveats
- правила для каждого режима (FULL / QUICK-REFRESH / PARTIAL)

**Coherence diagnostic в macro-marginal:**

```yaml
coherence_diagnostic:
  implicit_world_distribution: { A: <n>, B: <n>, C: <n>, D: <n>, agnostic: <n> }
  dominant_implicit_world: <id>
  inconsistency_score: 0..1
  warnings:
    - factor: brent
      implicit: A
      contradicts_majority: D
      severity: HIGH
      action: "Для marginal — допустимо. Для stress — использовать macro-scenarios, не macro-marginal."
```

**Числовые поля L1 для downstream (MFC-4):**

Человекочитаемые `central_estimate_l1_<год>` (`"$68/bbl …"`, `"88 руб./$"`) — строки-уровни,
непригодные для арифметики `portfolio-integrated-view`. Чтобы L1 включился, прогони
**детерминированный** `scripts/compute_marginal_move.py` на блоке `factors` —
он добавит рядом машинные поля (никакой ручной арифметики у LLM):

```bash
# вход: JSON {factor: {central_estimate_l1_<год>: "<строка>", ...}}
python3 skills/macro-forecast-chain/scripts/compute_marginal_move.py < factors.json
```

```yaml
brent:
  central_estimate_l1_2026: "$68/bbl (JPMorgan-dominant weighted median)"  # человекочитаемо
  level_l1_2026: 68.0        # ← добавлено скриптом
  level_l1_2027: 57.0
  unit: usd_per_bbl          # usd_per_bbl | rub_per_usd | rub_per_cny | usd_per_troy_oz | rate_pct
```

`unit` фиксирует единицу **уровня**; перевод уровень→движение (% от `baseline_spot` для
цен, Δ п.п. для ставки) делает consumer (`portfolio-integrated-view`) против `baseline_spot`
из stress — единая база с Layer 2 → корректный `coherence_gap`. Контракт единиц (SSOT):
`references/events-yaml-spec.md` §5.6. Качественные факторы (geopolitics/sanctions) числового
уровня не получают — остаются строкой.

### 8c — Поведение по режимам

| Режим | ready_for_stress_test | Когда true / partial / false |
|-------|----------------------|------------------------------|
| FULL | `true` или `false` | true: 0 critical issues; false: есть critical caveats |
| QUICK-REFRESH | `true` или `false` | true: всё FRESH; иначе false с инструкцией перейти в FULL |
| PARTIAL | `partial` (новое значение) | всегда `partial` — сигнал PSS, что matrix неполная и нужно интерпретировать осторожно |

В PARTIAL режиме `ready_for_stress_test: partial` — `portfolio-scenario-stress`
должен это видеть и явно выводить пользователю предупреждение типа:
«Матрица собрана в PARTIAL-режиме. N факторов отсутствуют, M устаревшие.
Результаты по позициям, зависимым от data-gap факторов, помечены звёздочкой.»

### 8d — Сохранение

Сгенерировать **два артефакта** в чат:

- `macro-marginal-{date}.yaml` — Layer 1 (EV, weekly-review). Содержит
  `central_estimate_l1_<год>` (строка) + машинные `level_l1_<год>` + `unit`
  (через `compute_marginal_move.py`, см. 8b) по каждому фактору + `coherence_diagnostic`.
- `macro-scenarios-{date}.yaml` — Layer 2 (для portfolio-scenario-stress).
  Содержит `by_scenario` блоки.

Пользователь проверяет — затем явно вызывает `save-to-library`.
save-to-library кладёт файлы в `Claude-Memory/macro-chain/`.

(Нижний регистр в именах файлов — D4. Путь `macro-chain/`, а не `Macro-Chain/` — D4.)

### 8e — Финальный вывод

```
━━━ MACRO-FORECAST-CHAIN: Готово ━━━

Coverage: 9/9 факторов ✓
Caveats: 2 (некритичных)
Версия: MFC-20260502-1423
Артефакт: macro-input-2026-05-02.yaml

Для сохранения вызови: save-to-library
После сохранения будет записан в Claude-Memory/macro-chain/.

Готов к передаче в portfolio-scenario-stress.
Запустить стресс-тест сейчас? [Y / N]
```

Если Y → вызвать `portfolio-scenario-stress` с указанием на свежий `macro-scenarios-{date}.yaml`.

---

## RECALIBRATE-mode (D7)

Запускается командой `--mode RECALIBRATE [--strict]`. **Никаких LLM-вызовов, цель
<30 секунд**: `scripts/recalibrate.py` берёт веса из файла сайта `scenarios/stress-weights-{ref}.json`
(владелец задаёт их на странице «Стресс»; на даты прогнозов — линейная интерполяция между сроками сайта),
а если файла нет — из матрицы `scenarios/{ref}.yaml`, и пересчитывает Layer 2 marginal в прогнозах, чей `source_matrix` указывает на эту
матрицу. НЕ запускает FCA, НЕ трогает Layer 1 и conditional values, `expected_pl_pct`
не считает (D2). Молча не делает ничего: не угадывает modal при равных весах, не
переписывает файлы без изменения чисел, все пропуски — `SKIP:`/`skipped_files`.
CLI, поведение `--strict`, веса по горизонтам (MFC-5) — **загрузи
`references/recalibrate-mode.md` при этом режиме**.
Расхождение весов в матрице и в файле сайта — норма (в матрице исходные веса на её дату):
владельца о нём не спрашивай, действуют веса сайта.
После замены матрицы RECALIBRATE не предлагай: он меняет веса, а значения по сценариям остаются от прежней
матрицы — прогнозы с `MATRIX_REPLACED` сначала пересобираются.

---

## Out-of-frame caveats (D3)

Вместо «Unaccounted» сценария добавлять в `macro-marginal-{date}.yaml`:

```yaml
out_of_frame_caveats:
  - severity: low
    description: |
      Shell-матрица конструктивно полна для выбранных осей. События вне осей
      (кибератака, природная катастрофа, политический кризис в США) обрабатываются
      отдельным механизмом вне scenario-matrix probability frame.
    examples_of_out_of_frame:
      - "Кибератака на банковский сектор РФ"
      - "Катастрофа Saudi Aramco"
      - "Политический кризис в США 2026-2027"
```

---

## Upstream-контекст: как передавать в FCA

При вызове `forecast-confidence-applier` для downstream-фактора всегда включать блок:

```
[Upstream-контекст из Claude-Memory]
- {upstream_factor}: {central_estimate} (confidence {X}, дата {Y})
- Чувствительность: при отклонении {upstream_factor} на ±{threshold} —
  как изменится твой прогноз по {current_factor}? Укажи явно.
```

Порядок и список upstream-контекстов для каждого фактора — в `references/dependency-map.md`.

---

## Интеграция с forecast-monitor

Файла флагов устаревания нет: свежесть фактора — по датам самого прогноза (`forecast.date`, горизонт),
«горизонт прошёл» ставит скрипт монитора в его отчёте; пробой порога — алерт `factor_breach` того же отчёта:
`coverage_report.py --monitor-report` делает такой прогноз STALE (Шаг 2.2 п. 4).
