# Отчёт: оптимизация скиллов через перенос задач в Python-скрипты

**Дата:** 2026-05-05
**Метод:** статический обзор `SKILL.md` всех 15 скиллов + сверка с `docs/investment/_cross-cutting/plan.md` и `docs/investment/_cross-cutting/report.md`
**Цель:** найти детерминированные блоки, которые сейчас выполняет LLM, но которые можно отдать Python-скриптам — это удешевит вызовы и повысит математическую точность.

---

## 1. Сводка по приоритетам

| # | Скилл | Что вынести | Выгода |
|---|---|---|---|
| **1** | `portfolio-scenario-stress` | Шаг 3 (β × ΔF), Шаг 4 (агрегация P&L, Expected, Vulnerability) | 🟢 Высокая — уже в roadmap (`plan.md` Phase 4) |
| **2** | `forecast-confidence-applier` | Шаг 5 (weighted median/range), формула confidence в Шаге 6 | 🟢 Высокая |
| **3** | `forecast-monitor` | Шаг 3a–3e (date-арифметика, классификация 🔴/🟡), пост-фильтр web_search по `search_from_date` | 🟢 Высокая |
| **4** | `save-to-library` | Расчёт `next_due = forecast.date + interval_months`, валидация YAML frontmatter, сборка `*.yaml` из блока FCA/HST | 🟡 Средняя |
| **5** | `revise-memory-remote` | Слой 1–3: YAML-валидация, парность `.md ↔ .yaml`, триггеры по датам (`final_audit.due ≤ today`) | 🟡 Средняя |
| 6 | `memory-sync` | Парсинг frontmatter аудитов и diff желаемого vs текущего `memory_user_edits` | 🟡 Средняя |
| 7 | `retrospective-forecast-audit` | Шаг 7 (агрегаты `hit_rate`, `alpha_generation`, `avg_value` по матрице ценностей) | 🟡 Средняя |
| 8 | `macro-forecast-chain` | Coverage report (Шаги 1–3): возраст файлов, FRESH/AGING/STALE по таблице | 🟡 Средняя |

**Низкая выгода (не трогать):** `macro-ru-watcher` (объём данных мал, узкое горло — web_search), `scenario-builder` (форматирование <20 токенов), `hypothesis-stress-tester` (LLM-аналитика), `forecast-collector` (узкое горло — web-поиск), `revise-memory-local`.

---

## 2. Детали по топ-3

### 2.1 `portfolio-scenario-stress` — уже в работе

Подтверждаю направление, описанное в `docs/investment/_cross-cutting/plan.md` Phase 4. Конкретные кандидаты в `scripts/`:

- `apply_sensitivity.py` — `(positions × scenarios × β-matrix) → ΔP&L per position`. Формулы для акций (`Σβ_i × ΔF_i`) и облигаций (`−duration × Δrate_bps / 100`) детерминированы.
- `aggregate_stress.py` — Sector × scenario, Expected P&L (взвешенный по probability), Vulnerability ratio, top-N risks.

В LLM остаётся: Шаг 3.5 (idiosyncratic reasoning), выбор источника входа A/B/C/D, нарратив.

### 2.2 `forecast-confidence-applier` — самый недооценённый

Сейчас весь Шаг 5 (взвешивание 3–7 источников по trust из `INDEX.md`) и формула `confidence = 0.4 + 0.4×share_HIGH − 0.2×asymmetry` считаются LLM-ом. Это типичное место для арифметических ошибок (см. `docs/investment/_cross-cutting/report.md` §2.3 — фрагментация YAML-схем).

Скрипт `weighted_consensus.py`:
- input: JSON со списком `{source, value, horizon, trust_weight, position}`,
- output: `{weighted_median, range_p10_p90, modal_horizon, confidence, asymmetry_warning}`.

LLM продолжает делать сбор источников, карту лагерей и TL;DR.

### 2.3 `forecast-monitor` — еженедельный запуск (высокая частота)

Дата-арифметика — частый источник багов LLM. Скрипт `monitor_alerts.py`:
- читает `forecasts/*.yaml` + `scenarios/*.yaml`,
- классифицирует каждый монитор/deadline по таблице (🔴 ≤7д, 🟡 ≤14д, ✅ дальше),
- фильтрует web_search-кандидатов по `search_from_date`.

LLM остаётся: интерпретация web_search результатов и формирование дайджеста. Скилл крутится на Haiku 4.5 — но именно из-за дата-чувствительности скрипт тут особенно полезен.

---

## 3. Архитектурное замечание

Сейчас `ru-portfolio-advisor/scripts/` дословно дублирует 4 файла из `portfolio-data-loader/scripts/` (`parse_portfolio.py`, `portfolio_returns.py`, `per_security_xirr.py`, `moex_quotes.py`). Это уже зафиксировано в `plan.md` §3.2 как тех-долг. Перед добавлением новых скриптов в FCA/monitor/save-to-library стоит решить общую схему:

- **Вариант A:** общий пакет `_shared-scripts/` (по аналогии с `_shared-references/`), который `pack.sh` инжектит в каждый `.skill`.
- **Вариант B:** скрипты лежат в одном «owner»-скилле (например, `forecast-confidence-applier/scripts/`), а другие скиллы их импортируют через `pack.sh` по аналогии с `shared_refs:` (новое поле `shared_scripts:` в frontmatter).

Вариант B логичнее, потому что согласуется с D1 (каждый `.skill` самодостаточен), и не требует синхронизации копий в репо.

---

## 4. Что НЕ рекомендую делать

- Выносить **аналитические** шаги (Pre-mortem, Devil's Advocate, decomposition A/B/C, ACH lite) — это семантическая работа LLM.
- Скриптовать `macro-ru-watcher` z-score (объём 7 индикаторов, выгода <50 токенов, основное время — web_search).
- Трогать `scenario-builder` и `hypothesis-stress-tester` — там нет детерминированной математики кроме форматирования таблиц.

---

## 5. Сводка по 12 скиллам (детальная)

### forecast-confidence-applier (552 строк)

**Кандидаты на скрипт:**
- Шаг 5: взвешивание прогнозов по trust-весам (weighted median, range P10/P90).
- Шаг 5: расчёт взвешенного горизонта (HIGH×1.0 + MEDIUM×0.5).
- Шаг 6: формула confidence `0.4 + 0.4 × share_HIGH − 0.2 × asymmetry`.

**Что остаётся в LLM:** сбор источников через web_search, карта лагерей, проверка симметрии (Шаг 1.5), TL;DR.

**Выгода:** Высокая (200–300 токенов на сессию, устраняет ошибки).

### retrospective-forecast-audit (636 строк)

**Кандидаты на скрипт:**
- Шаг 7: агрегаты `hit_rate`, `alpha_generation`, `avg_value`, доля ошибок толпы.
- Шаг 5 (частично): применение трёх шкал → ячейка матрицы ценностей (−3..+3).

**Что остаётся в LLM:** извлечение цитат, сбор консенсуса на дату прогноза (web_search, hindsight check), декомпозиция A/B/C, shape-of-error.

**Выгода:** Средняя (расчёты ценности часто ошибочны; скрипт стабилизирует).

### macro-forecast-chain (850 строк)

**Кандидаты на скрипт:**
- Шаги 1–3: coverage report (FRESH/STALE/MISSING по таблице из `staleness-config.md`).
- Шаг 6 (rules-based): проверка внутренних противоречий в матрице.
- Шаг 2: `age-status` и `horizon-coverage` по жёсткой таблице.

**Что остаётся в LLM:** выбор режима, интерпретация UNMAPPED тикеров, составление DAG-порядка.

**Выгода:** Средняя (основной вклад скилла — оркестрация).

### forecast-monitor (492 строки)

**Кандидаты на скрипт:**
- Шаги 1–3: парсинг YAML-файлов и фильтрация active-прогнозов.
- Шаги 3a–3e: классификация алертов (🔴/🟡 по дате).
- Шаг 4: пост-фильтр web_search по `search_from_date`.

**Что остаётся в LLM:** интерпретация web_search результатов, дайджест.

**Выгода:** Высокая (date-арифметика, частый запуск, Haiku-цена).

### forecast-collector (498 строк)

**Кандидаты на скрипт:**
- Шаги 3–4: дедупликация и diversity-check.
- Шаг 5: подсчёт тематических и направленческих перекосов.

**Что остаётся в LLM:** определение falsifiable, хронологический поиск по архивам, интерпретация.

**Выгода:** Средняя (узкое горло — web-поиск, скрипт экономит ~80 токенов).

### portfolio-scenario-stress (422 строк)

См. §2.1.

### macro-ru-watcher (224 строки)

**Кандидаты:** z-score, Δ нед/мес.

**Выгода:** Низкая.

### save-to-library (740 строк)

> **Статус:** скилл правится в другой ветке. Этот раздел — **только рекомендации**
> для будущей оптимизации, в текущей ветке не реализуется.

**Решение по `next_due`:** убрать расчёт из save-to-library полностью. Сейчас
`weighted_consensus.py` (FCA) уже считает `reviews.next_due` и пробрасывает
в Events YAML. Save-to-library должен брать значение «как есть», без
пересчёта. Это устраняет двойную точку правды.

**Кандидаты на скрипт `assemble_artifact.py`:**

1. **Парсинг и валидация YAML frontmatter** (Workflow A/B/C/D, обязательные/
   рекомендуемые поля). Возвращает плоский список issues с `severity` и
   `human_message` — по образцу `validate_library.py`. Этим закроется ~120
   строк процедурных проверок в SKILL.md.

2. **B4.1a — семантическая валидация по `method`** (FCA-прогноз без confidence
   = блокирующая ошибка, manual/external_quoted допускают null). Это
   детерминированное правило, сейчас занимает ~50 строк ветвлений.

3. **A3 — определение subfolder** по trust-subdomain'ам: подсчёт совпадений
   с `subfolder-mapping.md`, выбор max или флаг неоднозначности при равном
   счёте. Чисто арифметика.

4. **A4 / B4 — auto-inclusion check:** `include_in_memory = pin OR (any
   subdomain trust = HIGH)`. Однострочное правило, но с этим же предикатом
   работает `memory-sync` — стоит вынести в общий модуль.

5. **B5 / C5 — дедупликация по `topic`:** скрипт получает список
   существующих файлов с frontmatter, выдаёт matches и предлагаемые варианты
   (a/b/c/d/e). LLM выбирает с пользователем.

6. **Сборка `.yaml` из `.md`-frontmatter + блок Events YAML** (B4 / C4 целиком).
   Сейчас это ~150 строк процедурного кода в SKILL.md. Скрипт принимает
   payload `{frontmatter, events_yaml_block, tier, slug_rules}` и возвращает
   готовый YAML-текст с применёнными правилами `auto_checkable` (§3.2
   спецификации) и slug-нормализацией. Полностью детерминировано.

7. **Имя файла:** `{topic}-{forecast_date}.md/.yaml` или
   `{source-kebab}-{period}.md`, с автосуффиксом `-v2/-v3` при коллизиях.
   Тривиально, но удобнее централизованно.

**Что остаётся в LLM:** диалог с пользователем, подтверждение деструктивных
операций (a/b/c/d/e), Read/Write через transport, обновление INDEX.md
(форматирование Markdown-таблицы).

**Выгода:** Высокая (если делать целиком). SKILL.md можно сжать с 740 до
~300 строк. Главное — устраняется проблема рассинхрона `next_due` между
FCA и save-to-library: скрипт берёт значение из FCA-блока и больше не
пересчитывает.

**Связь с FCA:** `weighted_consensus.py` уже отдаёт `reviews.{interval_months,
next_due}` в Events YAML формате. Save-to-library должен передавать этот блок
скрипту `assemble_artifact.py` как готовый, без пересчёта. Это финализирует
контракт FCA → save-to-library.

### scenario-builder (381 строки)

**Кандидаты:** форматирование Markdown-таблицы 2×2.

**Выгода:** Низкая.

### hypothesis-stress-tester (345 строк)

**Кандидаты:** классификация устойчивости по числу уязвимостей.

**Выгода:** Низкая.

### memory-sync (251 строка)

**Кандидаты на скрипт:**
- Шаги 3–4: парсинг frontmatter аудитов, агрегация по `source` (max `last_updated`).
- Шаги 5–6: применение auto-inclusion (`pin OR any subdomain = HIGH`), форматирование записей.
- Шаг 7: diff желаемого vs текущего state → батч операций.

**Что остаётся в LLM:** диалог подтверждения, eviction policy при лимите.

**Выгода:** Средняя.

### revise-memory-remote (336 строк)

**Кандидаты на скрипт:**
- Слои 1–3: YAML-валидация (обязательные поля, парность `.md ↔ .yaml`).
- Слой 2: триггеры актуальности (`final_audit.due ≤ today`, `reviews.next_due ≤ today`).
- Слой 2: orphan-files.

**Что остаётся в LLM:** диалог о действиях, формирование читаемого отчёта.

**Выгода:** Средняя.

---

## 6. Дальнейшие шаги (обновлено 2026-05-05)

Выполнено в ветке `claude/optimize-skills-with-scripts-B1FVc`:

| Скилл | Скрипт | Тестов | Коммит |
|---|---|---:|---|
| ✅ forecast-confidence-applier | `weighted_consensus.py` | 47 | `12a0a00` |
| ✅ forecast-monitor | `monitor_alerts.py` (compute + post-filter) | 74 | `c134b0e`, `e9d1c4b` |
| ✅ revise-memory-remote | `validate_library.py` | 45 | `8d96b61` |
| ✅ memory-sync | `sync_planner.py` | 60 | `8119ac5` |
| ✅ retrospective-forecast-audit | `retro_metrics.py` | 50 | (текущий) |
| ✅ macro-forecast-chain | `coverage_report.py` | 54 | (текущий) |
| 🔄 portfolio-scenario-stress | (параллельно тобой) | — | — |
| ✅ save-to-library | `assemble_artifact.py` (validate-stress, validate-forecast, validate-audit, determine-subfolder, compute-inclusion) + Fix 1 E3 + Fix 2 E8 + Fix 3 transport | 55 | (текущий) |

**Параллельно:** решить вопрос общей схемы (`shared_scripts:` в frontmatter
`pack.sh` или копии в каждом скилле). Подробнее — в финальном сообщении
коммита `12a0a00`. Не блокирует текущие спринты.

Текущий эффект (после 3 скиллов): 166 регрессионных проверок, устранены ручные
date-расчёты, формула confidence и валидация YAML-полей; SKILL.md этих скиллов
ужаты на 50–150 строк процедурного кода.
