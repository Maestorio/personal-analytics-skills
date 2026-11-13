# Workflow B — Прогноз (forecasts/)

Сохраняется в `forecasts/` парой: `{topic-slug}-{forecast_date}.md` + `{topic-slug}-{forecast_date}.yaml`.

### B1. Идентификация источника контента

| Сценарий | Что есть на входе |
|----------|-------------------|
| **B1.0 — черновик в `_drafts/`** (первый по приоритету) | `Glob("_drafts/<topic>-*.md")` без `*.hst.md` (это текст HST — B1.2/B1.3): пара `<topic>-<forecast_date>.md` + `.events.yaml`, дата черновика позже даты последнего прогноза темы в `forecasts/` (или темы там нет) → `.md` и Tier 1 берутся из файлов, чат — только для уточнений владельца (дата та же — спросить владельца). Сжатие контекста между FCA и сохранением текст не теряет. Приёмка — командой `python3 scripts/promote_draft.py --root {LOCAL_LIBRARY_ROOT} --draft <имя> --kind forecast [--replaces <прежний .yaml>] --dry-run` → показать владельцу, что будет записано и заменено → по «да» та же команда без `--dry-run`: скрипт собирает `.yaml` из блока Events YAML и frontmatter (B4, B4.6 — заморозка `outcome_log`), валидирует (B3, B6.0), пишет пару, при `--replaces` помечает прежнюю версию `superseded` с промежуточным снимком (B5(a)), дописывает INDEX и `_sync_log.md` и удаляет черновик (код 1 — блокер, ничего не записано, `issues` — владельцу). Текст черновика модель не переписывает; за ней — решение о замене (B5: `--replaces`, `--as <имя>-v2`, `--force`), факт на дату замены (`--actual`, `--actual-source`), ответы на вопросы валидатора и правка текста по замечаниям (Edit черновика, приёмка заново). Черновики старше 14 дней по другим темам — одна строка владельцу в B8 |
| **B1.1 — После FCA только** | вывод FCA + блок `## Events YAML (для save-to-library)` (Tier 1) |
| **B1.2 — После FCA → HST в одной сессии (flow #2)** | вывод FCA + вывод HST с блоком `## Events YAML patch` (Tier 2). Пользователь говорит «сохрани всё» один раз. Черновик HST `_drafts/<topic>-<дата>.patch.yaml` + `.hst.md` есть и его дата не раньше даты FCA-черновика или сохранённого прогноза темы → патч и `## Стресс-тест` берутся из файлов, не из чата (та же логика дат, что B1.0; в B8 — «черновик можно удалить»). Если FCA-черновик ещё не принят — патч вливается в его `.events.yaml` (B4.2, Edit), `## Стресс-тест` — в его `.md`, затем приёмка B1.0 |
| **B1.3 — Сначала FCA сохранён, потом HST добавляется (flow #1)** | в библиотеке уже есть `*.md` + `*.yaml` после первого save; в чате — новый вывод HST. При вопросе дедупликации (B5) рекомендуем **вариант (e) Merge** — дописать `## Стресс-тест` в существующий `.md` и добавить Tier 2 секции в существующий `.yaml`. Итог: один консолидированный файл вместо двух разрозненных. Патч и текст HST — из черновика `_drafts/<topic>-<дата>.patch.yaml` + `.hst.md`, если он есть и его дата позже даты сохранённого прогноза темы (иначе — из чата) |
| **B1.4 — HST на чужом тексте без FCA** | пользователь дал прогноз внешнего источника + HST атаковал его. Сохраняем как новый прогноз. |
| **B1.5 — `.md` готовый, передан напрямую** | пользователь передал готовый `.md` файл прогноза. Используем как есть. |

### B2. Валидация и сборка контента `.md`

`.md` файл должен содержать:

```markdown
---
schema_version: 1
forecast_date: YYYY-MM-DD
horizon_date: YYYY-MM-DD
review_interval_months: N
topic: <slug>
domain: <geopolitics|ru-macro|ru-sellside|global-banks|tech-ceo>
---

# {Заголовок прогноза}

## Прогноз
{Полный вывод FCA: TL;DR, снимок мнений, filtered consensus, ключевые допущения,
outliers, не аудированные источники, что дальше — БЕЗ технического блока Events YAML}

## Стресс-тест
{Полный вывод HST: pre-mortem, KAC, devil's advocate, reversibility, applicable Tier 2,
вердикт — БЕЗ технического блока Events YAML patch}
```

**Правила содержимого `.md`:**

- Если в инпуте есть только FCA — секция `## Стресс-тест` отсутствует.
- Если в инпуте есть только HST на чужом тексте — секция `## Прогноз` содержит цитату исходного прогноза + источник, секция `## Стресс-тест` — вывод HST.
- Технические блоки `## Events YAML (для save-to-library)` и `## Events YAML patch` ИСКЛЮЧАЮТСЯ из `.md` — они уходят в `.yaml` файл.
- Frontmatter `.md` — минимальный (только идентификационные поля). Вся структурная информация — в `.yaml`.

### B3. Проверка обязательных полей frontmatter

| Поле | Статус | Действие при отсутствии |
|------|--------|------------------------|
| `forecast_date` | ОБЯЗАТЕЛЬНО | Спросить |
| `horizon_date` | ОБЯЗАТЕЛЬНО | Спросить (НЕ принимать TODO) |
| `review_interval_months` | ОБЯЗАТЕЛЬНО | Предложить дефолт по домену: ru-macro/geopolitics-active = 3, geopolitics-slow/structural = 6, long-term = 12 |
| `topic` | ОБЯЗАТЕЛЬНО | Сгенерировать из заголовка по правилу slug; подтвердить с пользователем |
| `domain` | ОБЯЗАТЕЛЬНО | Спросить |
| `method` | ОБЯЗАТЕЛЬНО для прогнозов | Определить по контексту: `fca` если есть Events YAML блок от forecast-confidence-applier; `manual` если пользователь явно ввёл прогноз; `external_quoted` если это цитата конкретного источника. При сомнении — спросить. |
| `schema_version` | ОБЯЗАТЕЛЬНО | Установить `1` автоматически |

**Slug-правило** для `topic` и для всех `id` в `.yaml` — см. `references/events-yaml-spec.md` §1.2.

### B4. Сборка `.yaml`

Прочитай `references/events-yaml-spec.md` для полной схемы. Алгоритм:

**B4.1.** Создать Tier 1 секцию:

```yaml
schema_version: 1
type: forecast-events
forecast_ref: <basename>.md
status: active

forecast:
  date: {forecast_date}
  horizon: {horizon_date}
  horizons: {если в .md frontmatter есть список — копировать; иначе [{horizon_date}]}
  domain: {domain}
  topic: {topic}
  method: {fca | manual | external_quoted — см. B4.1a}
  central_estimate: {извлечь по правилам B4.1a}
  confidence: {извлечь по правилам B4.1a; null допустим только при method != fca}
  upstream_snapshot: {копировать как есть из .md frontmatter, если есть; иначе []}

reviews:
  interval_months: {review_interval_months}
  next_due: {forecast_date + review_interval_months месяцев}
  last_completed: null
  history: []

final_audit:
  due: {horizon_date}
  status: pending
```

**B4.1a — Семантическая валидация по `method`.** Это критическая проверка —
не пропускать FCA-прогнозы без confidence, иначе теряется смысл агрегации.

Алгоритм:

```
1. Определить method:
   - В инпуте есть блок «## Events YAML (для save-to-library)» от FCA?
     → method = fca
   - Пользователь явно написал «вручную» или «без агрегации»?
     → method = manual
   - Это цитата прогноза конкретного аналитика/CEO без агрегации
     (типичный сигнал: один источник в «Снимок мнений»)?
     → method = external_quoted
   - Иначе — спросить.

2. Извлечь confidence:
   - method = fca: confidence ОБЯЗАТЕЛЕН, число в [0, 1].
     Если в инпуте FCA-блок есть, но confidence отсутствует или null —
     ❌ БЛОКИРУЮЩАЯ ОШИБКА. Не сохранять. Сообщить пользователю:

     ```
     ✗ FCA-прогноз без confidence — это ошибка в FCA-выводе.
       Confidence не пересчитан с применением trust weights из INDEX.md.
       Действия:
       [A] Перезапустить FCA на этом же топике с явной агрегацией
       [B] Сохранить как method: manual + confidence: null
           (потеряется FCA-семантика, но прогноз будет в библиотеке)
       [C] Отменить сохранение
     ```
     Не угадывать confidence. Не ставить значение «по ощущениям».

   - method = manual: confidence обычно null.
     Если пользователь хочет проставить — ОК, число в [0, 1] с пометкой
     `confidence_method: subjective`.

   - method = external_quoted: confidence почти всегда null.
     Если в цитате есть прямое указание уверенности («с вероятностью 60%»)
     — записать как число + `confidence_method: quoted_in_source`.

3. Извлечь central_estimate:
   - Из FCA-блока (поле «modal scenario» или «weighted median»).
   - Из текста пользователя (для manual/external_quoted).
   - Если совсем нет числовой/вербальной оценки — null + TODO.
```

**B4.2.** Если в инпуте есть Tier 2 блок (`## Events YAML patch` от HST или Tier 2 поля в FCA-блоке) — добавить в `.yaml` секции `monitoring`, `assumptions`, `thresholds`, `deadlines`, `falsifiers`, `agents` по схеме из `events-yaml-spec.md` §3.

> **Patch-merge правило (КРИТИЧНО).** Если соответствующий ключ (`monitoring:` и т.д.) уже присутствует в Tier 1 части файла — items из патча **дописываются в существующий список**, а не выводятся под повторным top-level ключом. Дубликат top-level ключа = невалидный YAML (js-yaml в viewer падает на всём файле, PyYAML молча перетирает).

**B4.3.** Применить правила `auto_checkable` (§3.2 спецификации):
- `monitoring`, `thresholds`, `falsifiers` — true только при наличии числового `threshold` или конкретной даты события
- `assumptions`, `agents` — всегда `false`
- `deadlines` — всегда `true`

**B4.4.** Применить `id`-slug-правила. Уникальность в файле — обязательна.

**B4.5.** TODO-маркер для не извлечённых полей: `field: null  # TODO: <причина>`.

**B4.6. Seeding `outcome_log` (калибровка, §14.3 — аддитивно, опционально).**

Если в `.yaml` есть блок `fca_stats` (или прогноз событийный с `monitoring[].check_date`),
засеять stub `outcome_log` для **ближайшего неразрешённого резолва, входящего в ~4-месячное
окно** от `forecast.date`. Дальние горизонты (2027/2028) НЕ seed'ить преждевременно — они
получат запись позже, при следующем supersession/rescan, когда приблизятся. Приоритет —
**микропрогнозы** (заседания ЦБ, OPEC, недельная инфляция): резолвятся быстро.

Алгоритм:
1. Собрать кандидат-резолвы: `forecast.horizons` + event-даты из `monitoring[].check_date`
   (`auto_checkable: true`). Отбросить те, что дальше `forecast.date + ~4 мес`.
2. Для ближайшего — вызвать helper (заморозка из `fca_stats`, никакой ручной сборки):
   ```bash
   echo '{"fca_stats_entry": <fca_stats["{resolve}"]>, "resolve_date": "{resolve}",
          "logged_at": "{today}", "record_type": "horizon_resolve",
          "confidence_at_forecast": {forecast.confidence}}' \
     | python3 scripts/assemble_artifact.py freeze-outcome-log
   ```
3. Взять `entry` из output, дописать в список `outcome_log:` файла (создать ключ, если нет).
   `blocking_count > 0` → показать пользователю, не сохранять с битой записью.
4. `warning` про `null`-поля (`l1_unweighted`, `predicted_p` event-стаба) — это норма
   (честная отметка «не персистилось»), не блокирует.

Seeding — **best-effort**: если `fca_stats` нет (не-FCA прогноз, legacy) — шаг тихо
пропускается, `outcome_log` не создаётся. Прогнать `check-yaml-duplicates` после дописи.

### B5. Дедупликация по `topic`

Перед сохранением — `Glob("*.md", path="{LOCAL_LIBRARY_ROOT}/forecasts/")`, прочитать frontmatter каждого, найти файлы с **тем же `topic`** и `status: active` (status читается из `.yaml` пары).

Если найдено:

```
В forecasts/ уже есть прогноз с topic="{topic}":
  • {filename}.md (forecast_date: {date}, status: active, method: {method}, central_estimate: "{...}")

Что сделать?
(a) Создать новую версию: пометить старый status=superseded, superseded_by={новый}; новый ru-rates-2026-2026-04-30.md создаётся отдельно
(b) Заменить существующий (без истории; старый и .md, и .yaml перезаписываются)
(c) Создать как независимый прогноз (имя файла с суффиксом, статус старого не меняется)
(d) Отмена
(e) Merge: дописать секцию ## Стресс-тест в существующий .md + добавить Tier 2 секции в существующий .yaml; имя файла не меняется, новых файлов не создаётся
```

**По умолчанию выбираем (a)** — самый чистый, история сохраняется. Но всегда спрашиваем.

**Исключение для flow #1 (B1.3 — после уже сохранённого FCA добавляется HST):** рекомендуем **(e) Merge** — дописать стресс-тест в существующий файл, не создавая новых. Показываем меню всех 5 вариантов на случай, если пользователь хочет другую логику.

**Исключение для Type 1 → Type 2 upgrade (events-yaml-spec.md §5):** если существующий active forecast — Type 1 (`isolated: true`), а новый артефакт — Type 2 conditional (с `by_scenario` блоком) на ту же тему, **рекомендуем (a) Новая версия** автоматически (не предлагать (b)/(c)/(e)):
- Старый файл получает `status: superseded` + `superseded_by: {new}.yaml`.
- Новый файл получает `replaces: {old}.yaml` в frontmatter.
- В новом файле обязательно есть **оба слоя**: `forecast.central_estimate` (Layer 1) + `conditional_on_scenarios.by_scenario` (Layer 2). Если Layer 1 отсутствует — validate_forecast_events заблокирует с `forecast.central_estimate: blocking`.
- (e) Merge **не подходит**: Type 1 → Type 2 — это не «добавить стресс-тест к marginal'у», а **переход на новую методологию атрибуции** (D8, dynamic scenario classification). Файл переписывается полностью.
- (b)/(c) не предлагать: (b) теряет историю, (c) создаёт два параллельных active forecast на одну тему.

При этом если в библиотеке цепочка `replaces:` (например, A → B, B → C через `replaces:`), но `status:` старых файлов не обновлён — это **дополнительная задача cleanup**. После сохранения нового файла пройти по цепочке `replaces:` и обновить `status: superseded` у всех файлов в ней. INDEX.md обновить соответственно (убрать superseded-файлы из active-таблицы или явно пометить).

### B5e. Механика Merge (вариант e)

Применяется только когда пользователь выбрал (e) или скилл рекомендовал (e) при flow #1 (B1.3) и пользователь согласился.

1. Прочитать существующий `{basename}.md` из библиотеки.
2. Дописать в конец файла секцию `## Стресс-тест` с полным выводом HST (без технического блока `## Events YAML patch`). Использовать Edit (точечное добавление), не Write (перезапись).
3. Прочитать существующий `{basename}.yaml` из библиотеки.
4. **Слить Tier 2 секции с существующими (key-merge, не append-as-new-top-level)**:
   - Для каждого ключа из патча (`monitoring`, `assumptions`, `thresholds`, `deadlines`, `falsifiers`, `agents`):
     - Если ключ **уже есть** в Tier 1 части файла → дописать items нового списка в конец существующего (через Edit на месте закрытия списка ключа в файле, либо Write всего файла после in-memory merge). НЕ выводить второй `monitoring:` после существующего.
     - Если ключа **нет** — добавить как новую секцию в конец файла.
   - Items сравниваются по `id`: при коллизии — items из патча **пропускаются** (Tier 1 имеет приоритет) и записывается warning в финальный отчёт.
   - Перед записью прогнать `python3 scripts/assemble_artifact.py check-yaml-duplicates` на итоговом тексте. Если duplicates найдены — операция блокируется, сообщение пользователю с указанием строк.
5. INDEX.md не менять — файлы уже зарегистрированы под теми же именами.
6. Финальное сообщение:

```
✅ Стресс-тест добавлен в существующий файл:
  • {basename}.md — дописана секция ## Стресс-тест
  • {basename}.yaml — добавлены Tier 2 секции (monitoring / assumptions / ...)
Новых файлов не создано.
```

### B6. Имя файла и сохранение

**Имя:** `{topic}-{forecast_date}.md` и `.yaml`. Пример: `ru-rates-2026-2026-04-30.md`.

Если такое имя уже существует (тот же `topic` + та же `forecast_date`) — это коллизия не по логике, а по таймингу (несколько прогнозов в один день). Добавить суффикс `-v2`, `-v3`.

**B6.0. Pre-write validation (blocking):**

Перед записью запустить детерминированную валидацию YAML-контента:
```
echo '{"yaml_text": "<сериализованный YAML-текст>"}' | python3 scripts/assemble_artifact.py check-yaml-duplicates
python3 scripts/assemble_artifact.py validate-forecast <yaml_content>
python3 scripts/assemble_artifact.py validate-forecast-events <yaml_content>
```

Порядок имеет значение: `check-yaml-duplicates` идёт **первым** — он работает с сырым текстом и ловит top-level дубликаты ключей (`monitoring:` после `monitoring:`), которые `yaml.safe_load`/LLM-парсинг сглатывает и приводит к молчаливой потере данных и падению viewer'а.

Если скрипт вернул хотя бы одну issue с `severity: blocking` — **не писать файл**, вернуться в B4.1a и показать меню исправления. Пример blocking issue: `confidence: null` при `method: fca`; дубликат top-level ключа `monitoring`; неполный `by_scenario` (≠4 ключа).

**Гейт одностороннего конуса (§15, F1).** `validate-forecast-events` пересчитывает cone из `fact_anchor` + `by_scenario`. Если `one_sided_cone: true` (все миры по одну сторону от текущего факта) И `counter_world_reason` пуст → **blocking** (`conditional_on_scenarios.counter_world_reason`); сообщение называет сработавшие горизонты. Разрешение — **осознанное**: добавить встречный мир в `by_scenario` (предпочтительно — он дойдёт до portfolio-scenario-stress) либо заполнить `counter_world_reason`. **Не** сочинять reason за пользователя. `missing_side_falsifier` и «сторона не размечена» — warning (не блок).

**Запись (Synology mount):**
```
Write("{LOCAL_LIBRARY_ROOT}/forecasts/{basename}.md", content=md_content)
Write("{LOCAL_LIBRARY_ROOT}/forecasts/{basename}.yaml", content=yaml_content)
```

**Если выбран вариант B5(a)** — дополнительно обновить старый `.yaml`:
```
status: superseded
superseded_by: {новый_basename}
```
(Edit, не Write — точечная правка, чтобы не переформатировать файл.)

### B7. Обновление `forecasts/INDEX.md`

Если `forecasts/INDEX.md` не существует — создать с минимальной шапкой:

```markdown
# forecasts/ — INDEX

Каталог прогнозов (Tier 1 = FCA, Tier 2 = FCA+HST). Схема описана в шапке этого файла.

| Файл | Тип | topic | forecast_date | horizon_date | status | central_estimate |
|------|-----|-------|---------------|--------------|--------|-----------------|
```

Добавить две строки в таблицу прогнозов:

```markdown
| {basename}.md | forecast | {topic} | {forecast_date} | {horizon_date} | active | {central_estimate} |
| {basename}.yaml | [events Tier {1\|2}] | (см. ↑) | — | — | — | confidence: {value} |
```

Если применён B5(a) — также обновить старую строку в INDEX.md: `status: active → superseded`.

### B8. Финальное сообщение

Добавить запись в `Claude-Memory/_sync_log.md`:
```
{YYYY-MM-DD} | save-to-library | forecasts/{basename}.{md,yaml} | Workflow B | topic: {topic} | method: {method} | horizon: {horizon_date}
```

```
✅ Сохранено в forecasts/:
  • {basename}.md — прогноз{ + стресс-тест}
  • {basename}.yaml — events Tier {1|2}

topic: "{topic}" | horizon: {horizon_date} | next review: {next_due}
{Если применён (a):}
  ⚠️ Предыдущая версия помечена status=superseded: {old_basename}.md/.yaml

Следующий шаг:
  • Запустить hypothesis-stress-tester (если ещё не запускался)
  • Или: ничего, прогноз войдёт в weekly haiku-checker
{При B1.0:} Черновик принят и удалён (`promote-draft`)
{При патче из черновика (B1.2/B1.3):} Черновик можно удалить: _drafts/{topic}-{дата}.patch.yaml, _drafts/{topic}-{дата}.hst.md
{Черновики старше 14 дней:} В _drafts/ лежат старые черновики: {имена} — сохранить или удалить
```

---

# Workflow C — Сценарная матрица (Scenarios/)

Сохраняется в `Scenarios/` парой: `scenario-{topic-slug}-{date}.md` + `scenario-{topic-slug}-{date}.yaml`.

### C1. Идентификация контента

| Сценарий | Что есть на входе |
|----------|-------------------|
| **C1.0 — черновик в `_drafts/`** (первый по приоритету) | `Glob("_drafts/scenario-<topic>-*.md")`: пара `scenario-<topic>-<date>.md` + `.events.yaml`, дата черновика позже даты последней матрицы темы в `scenarios/` (или темы там нет) → `.md` и блок Events YAML берутся из файлов, чат — только для уточнений владельца (дата та же — спросить владельца). Приёмка — командой `python3 scripts/promote_draft.py --root {LOCAL_LIBRARY_ROOT} --draft <имя> --kind scenario [--replaces <прежний .yaml>] --dry-run` → показать владельцу, что будет записано и заменено → по «да» та же команда без `--dry-run`: скрипт собирает `.yaml` (C4) и при необходимости frontmatter `.md` из блока matrix (C2), валидирует (C6), пишет пару, при `--replaces` помечает прежнюю `superseded`, дописывает INDEX и `_sync_log.md` и удаляет черновик (код 1 — блокер, ничего не записано, `issues` — владельцу). Текст черновика модель не переписывает; за ней — решение о замене (C5), ответы на вопросы валидатора и правка текста по замечаниям (Edit черновика, приёмка заново). |
| **C1.1 — вывод scenario-builder в чате** | нарративы + блок `## Events YAML (для save-to-library)` |

Источник — вывод scenario-builder. Должен содержать технический блок `## Events YAML (для save-to-library)` с секцией `scenario_triggers`. Если блока нет — попросить пользователя его сгенерировать или предоставить вручную.

### C2. Валидация и сборка `.md`

```markdown
---
schema_version: 1
type: scenario-matrix
date_created: YYYY-MM-DD
horizon: YYYY-MM-DD
domain: <domain>
topic: <slug>
axis_x: "<переменная X: A vs B>"
axis_y: "<переменная Y: C vs D>"
scenarios: ["{Имя A}", "{Имя B}", "{Имя C}", "{Имя D}"]
---

# Сценарии: {тема} · {date_created}

## Карта лагерей
{из шага 1 scenario-builder}

## Матрица 2×2
{Markdown-таблица из шага 2}

## Сценарии
### Сценарий A: «{Имя}»
{нарратив из шага 3}

### Сценарий B: «{Имя}»
...

### Сценарий C: «{Имя}»
...

### Сценарий D: «{Имя}»
...

## Triage по хрупкости (если был выполнен Шаг 4 scenario-builder)
{таблица + рекомендация}
```

### C3. Проверка обязательных полей

| Поле | Статус | Действие при отсутствии |
|------|--------|------------------------|
| `date_created` | ОБЯЗАТЕЛЬНО | = сегодня |
| `horizon` | ОБЯЗАТЕЛЬНО | Спросить |
| `domain` | ОБЯЗАТЕЛЬНО | Спросить |
| `topic` | ОБЯЗАТЕЛЬНО | Сгенерировать из заголовка |
| `axis_x`, `axis_y` | ОБЯЗАТЕЛЬНО | Из подтверждённых на Шаге 1.2 scenario-builder |
| `scenarios` | ОБЯЗАТЕЛЬНО | Из подтверждённых на Шаге 2 scenario-builder |

### C4. Сборка `.yaml`

```yaml
schema_version: 1
type: scenario-events
scenario_ref: <basename>.md
status: active

matrix:
  date: {date_created}
  horizon: {horizon}
  domain: {domain}
  topic: {topic}
  axis_x: "{axis_x}"
  axis_y: "{axis_y}"

scenario_triggers:
  - scenario_id: A
    label: "{Имя A}"
    probability: 0.25     # default Shell-равновероятность
    enabling_conditions: [...]
    leading_indicators:
      - id: <slug>
        description: "..."
        threshold: "..."
        check_date: YYYY-MM-DD  # опционально
        auto_checkable: true|false
  - scenario_id: B
    ...
  - scenario_id: C
    ...
  - scenario_id: D
    ...

reviews:
  interval_months: 6        # дефолт для сценариев — 6 мес.
  next_due: {date_created + 6 мес.}
  last_completed: null
  history: []

final_audit:
  due: {horizon}
  status: pending
```

Все `id` — по slug-правилу. `auto_checkable` — по правилам `events-yaml-spec.md §3.2`.

### C5. Дедупликация по `topic`

Аналогично B5. По дефолту — вариант (a) с superseded chain.

### C6. Имя файла и сохранение

**Имя:** `scenario-{topic}-{date_created}.md` и `.yaml`. Пример: `scenario-ru-economy-2030-2026-04-30.md`.

**Pre-write validation (blocking):**
```
echo '{"yaml_text": "<сериализованный YAML-текст>"}' | python3 scripts/assemble_artifact.py check-yaml-duplicates
python3 scripts/assemble_artifact.py validate-scenario-events <yaml_content>
```
Любая blocking issue → не писать, вернуться в C4 для правки.

Запись (Synology mount):
```
Write("{LOCAL_LIBRARY_ROOT}/Scenarios/{basename}.md", content=md_content)
Write("{LOCAL_LIBRARY_ROOT}/Scenarios/{basename}.yaml", content=yaml_content)
```

Если папка `Scenarios/` не существует — создать (Write автоматически создаст путь при первой записи).

### C7. Обновление `Scenarios/INDEX.md`

Если не существует — создать с минимальной шапкой:

```markdown
# scenarios/ — INDEX

Каталог сценарных матриц 2×2 (Shell Scenario Planning). Схема описана в шапке этого файла.

| Файл | Тип | topic | date_created | horizon | status | оси |
|------|-----|-------|--------------|---------|--------|-----|
```

Добавить две строки:

```markdown
| {basename}.md | scenario-matrix | {topic} | {date_created} | {horizon} | active | {axis_x} × {axis_y} |
| {basename}.yaml | [events scenarios] | (см. ↑) | — | — | — | 4 сценария |
```

### C8. Финальное сообщение

Добавить запись в `Claude-Memory/_sync_log.md`:
```
{YYYY-MM-DD} | save-to-library | scenarios/{basename}.{md,yaml} | Workflow C | topic: {topic} | horizon: {horizon}
```

```
✅ Сохранено в scenarios/:
  • {basename}.md — матрица сценариев
  • {basename}.yaml — scenario-events

topic: "{topic}" | horizon: {horizon} | next review: {next_due}

Сценарии: A «{Имя}», B «{Имя}», C «{Имя}», D «{Имя}»
{При C1.0:} Черновик принят и удалён (`promote-draft`)
```

---

# Workflow D — Ретро-аудит (reports/ + domains/, атомарно)

Сохраняет вывод `retrospective-forecast-audit` **двумя файлами за один вызов**:
- полный отчёт со всеми цитатами, шкалами, декомпозицией тезисов → `Claude-Memory/reports/{YYYY-MM-DD}-{source-slug}-{period}.md` (или `.docx` — формат сохраняется как есть)
- сжатый trust-профиль источника → `Claude-Memory/domains/{domain}/{source-slug}-{period}.md`

Обновляются **оба** `INDEX.md` (`reports/` и `domains/{domain}/`) и **одной строкой** дописывается `_sync_log.md`.

**Зачем атомарно:** ретро-аудит — это всегда пара «полный отчёт + сжатый профиль для memory-sync». Раньше эти два шага делались отдельными вызовами save-to-library, что приводило к рассинхрону, забытому профилю и мусору в `_audits/`. Атомарность — дефолт.

**Опциональные флаги** (для редких случаев, когда явно нужен только один файл):
- `--only=report` — только полный отчёт в `reports/`, профиль не пишется
- `--only=profile` — только сжатый профиль в `domains/`, отчёт не пишется

Без флагов — пишутся оба.

### D1. Идентификация контента

**D1.0 — черновик в `_drafts/`** (первый по приоритету): `Glob("_drafts/*-profile.md")` — профиль `<source-slug>-<period>-profile.md` с парным отчётом `_drafts/<YYYY-MM-DD>-<source-slug>-<period>.md`; дата отчёта позже даты последнего отчёта той же пары `source-slug`+`period` в `reports/` (или его там нет) → оба текста берутся из файлов, чат — только для уточнений владельца (дата та же — спросить владельца, D3). При записи профиль теряет суффикс `-profile` (он лишь отличает профиль в общей папке черновиков): `domains/{domain}/<source-slug>-<period>.md`, `domain` — по D2. Черновика нет (mount был недоступен, «черновик не записан») — вывод в чате, как ниже. Приёмка — командой `python3 scripts/promote_draft.py --root {LOCAL_LIBRARY_ROOT} --draft <имя> --kind retro-audit --dry-run` → показать владельцу, что будет записано и заменено → по «да» та же команда без `--dry-run`: скрипт валидирует (A2, D4.5), пишет отчёт и профиль без суффикса `-profile`, строку `reports/INDEX.md`, дописывает INDEX и `_sync_log.md` и удаляет черновик (код 1 — блокер, ничего не записано, `issues` — владельцу). Текст черновика модель не переписывает; за ней — домен при неоднозначном trust (`--domain`), строка `domains/{domain}/INDEX.md` (формат у доменов разный: Edit или JSON-вход `index_rows`), ответы на вопросы валидатора и правка текста по замечаниям (Edit черновика, приёмка заново).

Источник — вывод retrospective-forecast-audit. Ожидаемая структура:
- Декомпозиция тезисов на слои (предпосылка → каузация → калибровка)
- Оценка по трём шкалам (фактическое исполнение / позиция к консенсусу / локализация ошибки)
- Дословные цитаты с атрибуцией (в формате оригинал + перевод)

Если контент передан как файл — прочитать через Read. Если контент в чате — использовать напрямую.

Параллельно retrospective-forecast-audit обычно выдаёт (или его можно попросить выдать) сжатый trust-профиль источника для `domains/`. Если профиля в выводе нет — собрать минимальный из шапки полного отчёта (frontmatter с `source`, `period`, `trust`, итоговый verdict §8) перед сохранением.

### D2. Сбор метаданных

Обязательные поля:

| Поле | Статус | Действие при отсутствии |
|------|--------|------------------------|
| `source` | ОБЯЗАТЕЛЬНО | Спросить (обычно очевидно из контента) |
| `source-slug` | ОБЯЗАТЕЛЬНО | Транслит ISO 9 от `source`, kebab-case; пример: `Изборский клуб` → `izborsk` |
| `audit_date` | ОБЯЗАТЕЛЬНО | = сегодня, подтвердить с пользователем |
| `period` | ОБЯЗАТЕЛЬНО | Покрытый период аудита, формат `{YYYY}-{YYYY}` или `{YYYY}`; пример: `2022-2023`, `2020-2024` |
| `topic` | Рекомендуется | Slug темы/прогноза; используется только если аудит привязан к конкретному прогнозу |
| `domain` | ОБЯЗАТЕЛЬНО | Спросить; должен совпадать с подпапкой в `domains/` |
| `linked_forecast` | Рекомендуется | Имя `.md` файла прогноза в `forecasts/`, если аудит проводился по конкретному прогнозу |

### D3. Имена файлов

**Полный отчёт:** `reports/{YYYY-MM-DD}-{source-slug}-{period}.md`
**Сжатый профиль:** `domains/{domain}/{source-slug}-{period}.md` (**без** суффикса `-audit`)

Примеры:
- `reports/2026-05-15-zhirinovsky-1991-2022.md` + `domains/geopolitics/zhirinovsky-1991-2022.md`
- `reports/2026-05-15-izborsk-2022-2023.md` + `domains/geopolitics/izborsk-2022-2023.md`

**Запрещённые паттерны имени** (валидируется в assemble_artifact.py):
- destination `_audits/`, `audits/` — deprecated, должно быть `reports/`
- пробелы или `(N)` в имени файла — это след от MCP без edit
- суффикс `-audit` в имени файла в `domains/` — старая ошибочная конвенция

Если файл с таким именем уже существует — спросить: (a) новый аудит с суффиксом `-v2`, (b) заменить, (c) отмена. Решение применяется к обоим файлам синхронно.

### D4. Проверка дублей

Поиск в `reports/` файлов с тем же `source-slug` и `period`; параллельно — в `domains/{domain}/` файла с тем же `source-slug` и `period`. Если найден хотя бы один — предложить варианты (a/b/c из D3).

### D4.5. Pre-emit чек-лист (валидация путей)

**Перед записью** прогнать обе пути через детерминированный валидатор:

```bash
python3 skills/save-to-library/scripts/assemble_artifact.py validate-retro-audit-paths << 'EOF'
{
  "report_path":  "reports/{YYYY-MM-DD}-{source-slug}-{period}.md",
  "profile_path": "domains/{domain}/{source-slug}-{period}.md",
  "source_slug":  "{source-slug}",
  "period":       "{period}",
  "audit_date":   "{YYYY-MM-DD}",
  "only":         null
}
EOF
```

Что проверяется:
- destination не `_audits/` и не `audits/` (deprecated)
- `report_path` начинается с `reports/`, имя = `{audit_date}-{source-slug}-{period}.{md|docx}`
- `profile_path` имеет вид `domains/{domain}/{source-slug}-{period}.md` (3 сегмента)
- нет суффикса `-audit` в имени профиля
- нет пробелов и `(N)` в именах (след MCP-дублей)
- `source_slug` соответствует `[a-z0-9](-[a-z0-9]+)*` (lowercase kebab-case, транслит ISO 9)
- `period` соответствует `YYYY` или `YYYY-YYYY`
- `audit_date` соответствует `YYYY-MM-DD`
- при `only=null` обе пути обязательны; при `only=report|profile` — соответствующая одна

**При `blocking_count > 0`** — остановиться, **не писать** в Claude-Memory, показать пользователю список `issues` и попросить исправить slug/date/destination. Никакого «всё равно сохраню».

### D5. Сохранение пары файлов

Через Transport B (Synology — Write):
1. `{LOCAL_LIBRARY_ROOT}/reports/{YYYY-MM-DD}-{source-slug}-{period}.md` (или сохранить исходный формат, если `.docx`)
2. `{LOCAL_LIBRARY_ROOT}/domains/{domain}/{source-slug}-{period}.md`

Папки `reports/` и `domains/{domain}/` должны существовать; если нет — создать без дополнительных вопросов.

**Transport policy:** MCP (Google Drive) для Workflow D **запрещён** — он не умеет edit, что ломает обновление `INDEX.md` и `_sync_log.md` (плодит дубли вида `INDEX (1).md`, `_sync_log (2).md`). Если Synology недоступен — остановиться и сообщить пользователю, не пытаться fallback на MCP.

### D6. Обновление двух INDEX.md

**`reports/INDEX.md`** — дописать строку:
```markdown
| {YYYY-MM-DD}-{source-slug}-{period}.md | {source} | {period} | {audit_date} | {domain} | retro-audit | {linked_forecast или —} |
```
Если файла нет — создать с шапкой по существующему образцу `reports/INDEX.md`.

**`domains/{domain}/INDEX.md`** — добавить/обновить строку профиля по образцу соседних записей (carnegie, chatham-house и т.п.).

Мастер-INDEX (`Claude-Memory/INDEX.md`) обновляется только если он реально содержит секцию по этому домену; иначе не трогаем.

### D7. Запись в `_sync_log.md`

Одной строкой в конец файла (`update_index.py sync-log`, как и остальные workflow; путь — третья колонка, имя workflow — четвёртая):
```
{YYYY-MM-DD} | save-to-library | reports/{basename-report}.md + domains/{domain}/{basename-profile}.md | Workflow D | source: {source} | period: {period}
```

### D8. Связь с другими workflow

После D5–D7 предложить (не выполнять автоматически):

- **Пометить прогноз как resolved**: «Обновить статус прогноза {linked_forecast} → resolved?» (если `linked_forecast` указан — см. раздел "Управление статусом")
- **Запустить memory-sync**: «Синхронизировать профиль {source} в memory_user_edits?»

### D9. Финальное сообщение

```
✅ Ретро-аудит сохранён (атомарно, Synology mount):
  • Claude-Memory/reports/{YYYY-MM-DD}-{source-slug}-{period}.md   (полный отчёт)
  • Claude-Memory/domains/{domain}/{source-slug}-{period}.md       (сжатый профиль)
  source: "{source}" | period: {period} | audit_date: {audit_date}
  INDEX обновлены: reports/, domains/{domain}/  | _sync_log.md — 1 запись
  {если профиль не прошёл auto-inclusion: «Trust = LOW/IGNORE, pin = false → при следующем memory-sync источник не попадёт в память; включить — `pin: true` в frontmatter профиля»}

Следующие шаги (по желанию):
  • Пометить прогноз {linked_forecast} как resolved (если применимо)
  • Запустить memory-sync
  {если пара взята из черновика: «черновик принят и удалён»}
```

---

# Workflow E — Стресс-тест портфеля (Portfolio/stress/)

Сохраняется в `Portfolio/stress/` парой: `stress-{YYYY-MM-DD}-{slug}.md` + `stress-{YYYY-MM-DD}-{slug}.yaml`.

### E1. Идентификация контента

**E1.0 — черновик в `_drafts/`** (первый по приоритету): `Glob("_drafts/stress-*.md")` — пара `stress-<YYYY-MM-DD>-<slug>.md` + `.yaml`; дата черновика позже даты последнего стресса в `Portfolio/stress/` (или там пусто) → оба файла берутся из черновика, чат — только для уточнений владельца (то же имя уже сохранено — E4). Черновика нет (mount был недоступен, «черновик не записан») — артефакты из чата. Приёмка — командой `python3 scripts/promote_draft.py --root {LOCAL_LIBRARY_ROOT} --draft <имя> --kind stress --dry-run` → показать владельцу, что будет записано и заменено → по «да» та же команда без `--dry-run`: скрипт проверяет кодировку (E2) и схему (E3), пишет пару, дописывает INDEX и `_sync_log.md` и удаляет черновик (код 1 — блокер, ничего не записано, `issues` — владельцу). Текст черновика модель не переписывает; за ней — решение по занятому имени (E4: `--as`, `--force`), ответы на вопросы валидатора и правка текста по замечаниям (Edit черновика, приёмка заново). E2–E3 проверяют черновик так же, как текст из чата.

Источник — вывод `portfolio-scenario-stress`. Скилл пишет пару черновиком в `_drafts/`, в библиотеку — нет (D3). Если артефакт пришёл как файл — Read; если в чате — использовать напрямую.

### E2. Encoding-check (КРИТИЧНО, блокирующая проверка)

**Перед любой валидацией проверить кодировку обоих артефактов** — Synology Drive и буфер обмена иногда ломают UTF-8.

1. Проверить первые 200 символов каждого артефакта на mojibake-паттерны:
   - `Ã—`, `Ã¢ÂÂ`, `Ã¢ÂÂ¢` (UTF-8→cp1252 round-trip)
   - `â€™`, `â€"` (UTF-8 интерпретирован как Latin-1)
   - `Ð¿`, `Ñ€` (кириллица в cp1252)

2. Если хотя бы один паттерн найден — **БЛОКИРУЮЩАЯ ОШИБКА**:

   ```
   ✗ Артефакт содержит повреждённую кодировку (mojibake).
     Файл: {filename}
     Detected pattern: "{первые 50 символов с проблемой}"
     
     Действия:
     [A] Получить артефакт повторно от portfolio-scenario-stress (регенерация)
     [B] Показать diff и попросить пользователя исправить вручную
     [C] Сохранить как есть (НЕ рекомендуется — downstream consumers
         (portfolio-integrated-view, retrospective-forecast-audit) сломаются)
     
     Какой вариант?
   ```

3. Дополнительно проверить BOM (`﻿`) — если есть, удалить перед записью (но не блокировать).

### E3. Валидация YAML schema v1

Прочитать YAML frontmatter и тело `.yaml` файла. Обязательные поля:

| Поле | Статус | Действие при отсутствии |
|------|--------|------------------------|
| `schema_version` (=1) | ОБЯЗАТЕЛЬНО | Блокирующая |
| `type: portfolio-stress-test` | ОБЯЗАТЕЛЬНО | Блокирующая |
| `date` | ОБЯЗАТЕЛЬНО | = сегодня, подтвердить |
| `portfolio_snapshot_id` | ОБЯЗАТЕЛЬНО | Спросить (имя snapshot JSON) |
| `scenarios` (dict с ключами `Sc-X_label`) | ОБЯЗАТЕЛЬНО | Блокирующая |
| `per_position` (dict с unblocked tickers) | ОБЯЗАТЕЛЬНО | Блокирующая |
| `caveats` (≥1 запись с `severity: HIGH`) | ОБЯЗАТЕЛЬНО | Блокирующая |
| `weight_type` (equal\|probability) | ОБЯЗАТЕЛЬНО | Спросить |

**Для запуска валидации:** `python3 scripts/assemble_artifact.py validate-stress < stress.json`
Скрипт принимает JSON с содержимым `.yaml` файла и возвращает список `issues` с полем `severity`.
Если `blocking_count > 0` — следовать процедуре ниже.

**Семантика «Блокирующая»:** при обнаружении отсутствия любого из обязательных
полей скилл **обязан остановиться** и вывести меню действий пользователю
(вариант [A]/[B]/[C] ниже). Скилл **НЕ** имеет права:

- Самостоятельно проставить значение «по контексту» (даже если оно «очевидно»
  — например, `type: portfolio-stress-test` из имени файла, `date` из
  `generated_at`, `portfolio_snapshot_id` из `portfolio_snapshot`).
- Объявить «исправляю» и продолжить запись.
- Молча конвертировать псевдонимы (`generated_at` → `date`, `portfolio_snapshot`
  → `portfolio_snapshot_id`).

Все эти действия — **галлюцинация структуры**: скилл выдаёт собственный output
за вход от portfolio-scenario-stress, разрушая аудиторский след «что именно
сгенерировал upstream-скилл».

**Семантические проверки:**

1. **Sum of probabilities:** `Σ scenarios[*].p ∈ [0.99, 1.01]` (±1% rounding tolerance). Если выходит за диапазон — предупредить, не блокировать (LLM-стохастика допустима в небольших пределах).

2. **Coverage:** `Σ per_position[*].weight_pct + cash_pct + blocked_pct ∈ [98, 102]` (±2%). Если <98% — блокирующая (per_position неполный, downstream сломается). Если >102% — блокирующая (двойной учёт).

3. **Scenario IDs cross-reference:** все ключи `delta_pct_by_scenario` в `per_position.*` должны существовать в верхнеуровневом `scenarios`. Если есть orphan ID — блокирующая.

4. **macro_blindspots:** если в YAML присутствует поле `macro_blindspots` — проверить, что все указанные тикеры присутствуют в `per_position`.

**Меню при провале E3:**

```
✗ Стресс-тест YAML не прошёл валидацию schema v1.
  Отсутствующие/некорректные поля:
  • {field_name}: {expected} (найдено: {actual or "—"})
  • ...

  Семантические нарушения:
  • {описание}
  • ...

Действия:
[A] Вернуть на доработку в portfolio-scenario-stress
    (артефакт регенерируется с правильными полями; рекомендуется)
[B] Я вручную дополню YAML и пришлю исправленный артефакт
    (скилл ждёт нового артефакта и перезапускает E1–E3)
[C] Сохранить как есть, с warning в _sync_log.md
    (НЕ рекомендуется: portfolio-integrated-view и retrospective-forecast-audit
    не толерантны к отсутствию `type/date/portfolio_snapshot_id/caveats`)

Какой вариант?
```

При [C] — добавить в `_sync_log.md` строку с пометкой `schema_v1_violation:
{список полей}`, чтобы при последующем revise-memory-remote можно было найти
такие записи и предложить ремонт.

При [A]/[B] — **не записывать ничего ни в библиотеку, ни в INDEX.md, ни в
_sync_log.md**. Сохранение откладывается до получения исправленного артефакта.

### E4. Дедупликация по date+slug

Поиск файлов `stress-{date}-*.{md,yaml}` в `Portfolio/stress/` через Glob. Если найден файл с тем же `date` и slug:

```
В Portfolio/stress/ уже есть стресс-тест на {date}:
  • {existing_basename}.md / .yaml

Что сделать?
(a) Заменить существующий
(b) Создать новый с суффиксом -v2
(c) Отмена
```

По умолчанию — спросить. Старые stress-тесты не помечаются `superseded` (нет такого статуса в schema v1) — они просто остаются как история.

### E5. Имя файла и сохранение

**Имя:** `stress-{YYYY-MM-DD}-{slug}.md` и `.yaml`.

**Slug** — из `scenario_source` в YAML (если задан) или из smart-default по содержимому `scenarios`. Slug — kebab-case, ASCII, ≤30 символов.

**Перед записью:**

1. Зафиксировать выбранный транспорт (`B` по умолчанию, `A` если B недоступен —
   см. `transport-layer.md` раздел «Fallback B → A: правило прозрачности»).
2. Если транспорт ≠ B — вывести предупреждение и дождаться подтверждения
   пользователя (меню из transport-layer.md). Без явного `[A]` — не записывать.
3. Только после подтверждения — `Write(...)`.

После записи — `Read(path)` обоих файлов для верификации в E8.

**Запись (Synology mount):**

```python
PORTFOLIO_STRESS_ROOT = "{LOCAL_LIBRARY_ROOT}/Portfolio/stress"
Write(f"{PORTFOLIO_STRESS_ROOT}/stress-{date}-{slug}.md", content=md_content)
Write(f"{PORTFOLIO_STRESS_ROOT}/stress-{date}-{slug}.yaml", content=yaml_content)
```

Если папки `Portfolio/stress/` не существует — создать (Write автоматически создаст путь).

### E6. Обновление `Portfolio/INDEX.md`

Если в `Portfolio/INDEX.md` нет секции стресс-тестов — создать её. Добавить две строки в таблицу:

```markdown
| {basename}.md | stress | {scenario_source} | {date} | active | {portfolio_snapshot_id} |
| {basename}.yaml | stress-events | (см. ↑) | — | — | E[P&L]: {expected_pl_rub or "—"} |
```

Если ранее существовал stress-тест с тем же `portfolio_snapshot_id` и был выбран вариант E4(a) — обновить старую строку: `status: active → superseded`.

### E7. Обновление `_sync_log.md`

Добавить запись в `Claude-Memory/_sync_log.md`:

```
{date} | save-to-library | Portfolio/stress/{basename}.{md,yaml} | Workflow E | scenario_source: {value} | snapshot: {portfolio_snapshot_id}
```

### E8. Финальное сообщение

**Перед составлением сообщения** — обязательное перечитывание записанного
артефакта: `Read` всего `.yaml`-файла, `Read` первых 30 строк `.md`-файла.
Все числа и поля в сообщении берутся **только из перечитанного содержимого**,
не из внутренней памяти процесса.

Если при перечитывании обнаружено расхождение с тем, что должно было быть
записано (файл короче, ключ отсутствует) — это сигнал, что `Write` прошёл
частично или произошла другая ошибка. **Не** сообщать «успешно сохранено» —
вернуть пользователю описание расхождения и предложить повторить запись.

Шаблон сообщения (все поля в `{}` — **только** из перечитанного файла):

```
✅ Стресс-тест сохранён в Portfolio/stress/:
  • {basename}.md — отчёт ({N_lines_in_md} строк)
  • {basename}.yaml — schema v1
    per_position: {len(yaml.per_position)} позиций (coverage {sum(weight_pct)}%)
    scenarios: {sorted(yaml.scenarios.keys())}
    weight_type: {yaml.weight_type}

E[P&L]: {yaml.portfolio_summary.expected_pnl.rub} RUB ({yaml.portfolio_summary.expected_pnl.pct}%)
range: [{min pnl_by_scenario.rub}, {max pnl_by_scenario.rub}] RUB
caveats: {len(yaml.caveats)}× ({count by severity})
review: {yaml.review_date if present else "не задано"}

Следующий шаг (по желанию):
  • portfolio-integrated-view (если есть свежий weekly-review)
  • retrospective-forecast-audit через 6 мес ({yaml.review_date})
{если пара взята из черновика: «черновик принят и удалён»}
```

**Если какое-то поле отсутствует** в перечитанном файле — писать `—` или
`(не задано)`, не подставлять «правдоподобное» значение из памяти.
