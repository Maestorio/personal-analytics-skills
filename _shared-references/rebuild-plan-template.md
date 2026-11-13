# Rebuild Plan Template

Шаблон markdown-документа, который генерируется оркестрационными скиллами (`macro-forecast-chain`, `scenario-builder`) при активации **emit-plan**: вместо запуска FCA внутри одной сессии — пользователь получает инструкцию для запуска каждого FCA в отдельном чате.

**Цель формата:** дешевле (Sonnet в свежей сессии вместо Opus на оркестрации в длинной), можно паузить и распараллеливать, HST идёт отдельным шагом на Opus.

---

## Структура

```markdown
# {Skill} Rebuild Plan — {YYYY-MM-DD}

**Режим:** {FULL | QUICK-REFRESH | PARTIAL — название режима}
**Триггер:** {что вызвало пересборку — например «coverage_score=0.41 → FULL needed» или «matrix shift → 5 факторов нуждаются в новой scenario attribution»}
**Scenario matrix:** {scenarios/scenario-X-{date}.yaml | n/a для Type 1-only}
**Snapshot date:** {YYYY-MM-DD}

---

## Сводка факторов

| # | Фактор | Текущий state | Тип | Зависит от | Причина пересборки |
|---|--------|---------------|-----|-----------|--------------------|
| 1 | brent | MISSING | Type 2 | (none) | Нет forecast YAML |
| 2 | cbr_rate | STALE 95d | Type 2 | inflation_ru, brent | Age > 90d |
| ... |

---

## Порядок выполнения (DAG)

1. **brent** — independent
2. **cbr_rate** — после inflation_ru (зависит)
3. **inflation_ru** — после brent (зависит через pass-through)
4. ...

> Каждый шаг — **новый чат** с указанной моделью и промптом. Между шагами проверь, что forecast YAML сохранён в `Claude-Memory/forecasts/`.

---

## Шаг 1 — {Factor 1} FCA

**Тип:** Type 2 conditional (или Type 1 isolated)
**Модель:** **Sonnet** (default для FCA по model-routing-канону репозитория)
**Открой новый чат.**

**Промпт (скопируй целиком). Минимальный формат — FCA сам прочитает scenario YAML:**

` ` `
/forecast-confidence-applier

Тема: {topic-slug}
Горизонт: {2026-12-31, 2027-12-31}
Домен: {global-banks | ru-macro | geopolitics | ru-sellside | tech-ceo | commodity-agencies}
Тип: {Type 1 isolated | Type 2 conditional}

{ЕСЛИ Type 2:}
Scenario matrix: scenarios/{scenario-slug}-{date}.yaml

{ЕСЛИ axis_dependent — фактор САМ является осью этой матрицы (например, sanctions в geopolitics-матрице):}
Этот фактор — ось сценарной матрицы; значения оси per scenario берутся из scenario YAML by construction. FCA даёт магнитуду в пределах диапазона оси.

{ЕСЛИ Type 1:}
Изолированный прогноз — обоснование: {почему isolated, например «binary event без сценарной декомпозиции» или «out of scenario matrix horizon»}.
` ` `

**Anti-patterns при составлении промпта (orchestrator должен их избегать):**

- ❌ **Не интерпретировать неосевые факторы через сценарии в промпте.** Например, для Brent нельзя писать «Sc-A → Ормуз нормализуется». Эта работа — Шаг 1.5B FCA: LLM прочитает scenario YAML, оценит как сценарий влияет на фактор, проатрибутирует источники. Если orchestrator пропишет интерпретацию заранее — FCA получит anchor и потеряет независимость суждения.
- ❌ **Не передавать «базовые параметры из текущего прогноза».** Никаких «L1 weighted median = $68», «working modal Sc-D $107/$93». Каждый FCA-запуск должен стартовать чисто — иначе старая оценка якорит новую.
- ❌ **Не копировать описания сценариев из scenario YAML в промпт.** FCA откроет scenario YAML по пути `source_matrix:` и прочитает triggers/assumptions сам.
- ✅ **Допустимо для axis-факторов:** указать что фактор — ось матрицы (`axis_dependent: true`). Значения оси per scenario in scenario YAML — FCA их прочитает; orchestrator не должен их дублировать в промпте.

**Expected output:**
- Forecast YAML по схеме `events-yaml-spec.md` §5
- {Если Type 2: `forecast.central_estimate` (Layer 1) + `by_scenario` для всех 4 ID + `provenance: inferred_from_content` + `sources_used` с `camp_weight` + `reasoning`}
- {Если Type 1: `isolated: true` + `isolated_reason`; `forecast.central_estimate` всегда обязателен}
- **Если по этой теме уже есть active forecast** в `forecasts/` (orchestrator должен проверить через Glob `forecasts/{topic}*.yaml`): новый FCA должен добавить в свой output поле `replaces: <старый_basename>.yaml` (на верхнем уровне forecast YAML). Это сигнал для save-to-library workflow B5: применить вариант (a) — новая версия + старый файл получает `status: superseded` + `superseded_by:` указатель. Без `replaces:` save-to-library заколеблется между опциями.
- Сохранение через save-to-library: `forecasts/{topic-slug}-{date}.yaml`

**После сохранения** → переходи к Шагу 2.

---

## Шаг 2 — {Factor 2} FCA

{... аналогично}

---

## (Опц.) HST для критичных прогнозов

> HST — логический stress-test (Pre-mortem / KAC / Devil's Advocate / Reversibility). Запускается **по решению пользователя** на forecast'ах с высокой неопределённостью или критичных для портфельных решений.

**Кандидаты:** {список из 1–3 самых критичных факторов; если их нет — пропустить блок}

**Открой новый чат.** Модель: **Opus** (HST требует deep reasoning).

**Промпт:**

` ` `
/hypothesis-stress-tester forecasts/{slug}-{date}.yaml
` ` `

**Expected output:**
- Parallel pair: `forecasts/{slug}-{date}-stress.{md,yaml}` (не патч — отдельный файл)
- Tier 1 + Tier 2 структура с указанием weak points и downward-revision confidence

---

## Финал — собрать macro-chain bundle

> Запускается **после выполнения всех FCA** из плана.

**Открой новый чат.** Модель: **Sonnet**.

**Промпт:**

` ` `
/macro-forecast-chain --mode ASSEMBLE-ONLY
` ` `

или в свободной форме: «assemble-only — собери bundle из готовых forecast YAML, без новых FCA».

**Expected output:**
- `macro-scenarios-{date}.yaml` (Layer 2 bundle для `portfolio-scenario-stress`)
- `macro-marginal-{date}.yaml` (Layer 1 marginal для `portfolio-integrated-view` и weekly-review EV)
- Если каких-то факторов из плана не хватает — warning + bundle с пропусками + caveat

**После сборки bundle:**
- `/portfolio-scenario-stress` — пересобрать stress на новом bundle
- `/portfolio-integrated-view` — синтезировать обновлённый дашборд

---

## Trace

- **Сгенерировано:** {skill} {date}, mode `{mode}`, `emit_plan: true`
- **Coverage report (на момент генерации):** {inline summary или ссылка на сохранённый отчёт}
- **План сохранён:** `_audits/rebuild-plan-{date}.md` (если пользователь подтвердил save-to-library)
```

---

## Правила использования шаблона

### Какие скиллы могут эмитить план

- **`macro-forecast-chain`** — основной случай. Активирует план в Шаге 4 (Checkpoint 1) при keyword-триггере в ответе пользователя или флаге `--emit-plan`.
- **`scenario-builder`** — при изменении scenario matrix; эмитит план для пересборки соответствующих Type 2 FCA. Опционально, не обязательно.

### Когда НЕ эмитить план

- **Режим RECALIBRATE** — это lazy weight update <30 сек, не нужно дробить.
- **Режим ASSEMBLE-ONLY** — bundle assembly без FCA, дробить нечего.
- **Режим PARTIAL** — FCA не запускаются по определению (as-is с caveat'ами).

### Keyword-триггеры в ответе пользователя

| Что пишет пользователь | Эффект |
|---|---|
| `план`, `plan`, `инструкция` | Активирует emit-plan |
| `выдай план`, `только план`, `только инструкция` | Активирует emit-plan |
| `не запускай`, `я сам`, `я сам запущу` | Активирует emit-plan |
| Просто `FULL` / `A` / `B` / etc. без триггер-слов | Запуск как обычно |

Триггеры комбинируются с выбором режима: `FULL план`, `A — выдай план`, `B + только инструкция` — все валидны.

### Saving плана

После генерации скилл предлагает: «Сохранить план в `_audits/rebuild-plan-{date}.md`?». Пользователь может ответить «да/save/нет». Это опционально — план полезен и без сохранения, но сохранение позволяет вернуться к нему через 1–2 дня (план может выполняться частями).

### Модели в плане

| Скилл | Рекомендованная модель | Примечание |
|---|---|---|
| `forecast-confidence-applier` | Sonnet | Default. Если в FCA активен Шаг 1.5B (Type 2) — всё равно Sonnet, классификация источников по сценариям не требует Opus |
| `hypothesis-stress-tester` | **Opus** | Deep reasoning для Pre-mortem / KAC; Sonnet даёт worse calibration |
| `macro-forecast-chain --mode ASSEMBLE-ONLY` | Sonnet | Простая сборка bundle, без FCA |
| `scenario-builder` (если в плане) | Sonnet | Default. Opus — только при сложной матрице с >2 осями |

В каждом шаге плана модель указывается явно, чтобы пользователь не задумывался.
