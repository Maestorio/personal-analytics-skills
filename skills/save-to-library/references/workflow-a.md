# Workflow A — Аудит источника

> Вынесено из SKILL.md дословно при дроблении 2026-08-12 (этап 3, подготовка Max → Pro).

# Workflow A — Аудит источника

Сохраняется в субпапки доменов: `geopolitics/`, `ru-sellside/`, `global-banks/`, `tech-ceo/`, `ru-macro/`, `commodity-agencies/`.

### A1. Получение файла

Определить источник:
- **Файл передан напрямую** → читать через Read
- **Контент в чате** → использовать напрямую
- **Ссылка на существующий файл** → пометить UPDATE

Если источник неясен — спросить.

### A2. Валидация YAML frontmatter

Извлечь YAML frontmatter. Проверить:

| Поле | Статус | Действие при отсутствии |
|------|--------|------------------------|
| `source` | ОБЯЗАТЕЛЬНО | Остановиться, спросить |
| `audit_date` | ОБЯЗАТЕЛЬНО | Остановиться, спросить |
| `trust` | ОБЯЗАТЕЛЬНО | Остановиться, предложить шаблон |
| `period` | Рекомендуется | Предупредить, не блокировать |
| `last_updated` | Рекомендуется | Установить = `audit_date`, предупредить |
| `pin` | Опционально | Установить `false` по умолчанию |

**Если `trust` отсутствует**, предложить шаблон:

```yaml
trust:
  {subdomain1}: HIGH    # HIGH / MEDIUM / LOW / IGNORE
  {subdomain2}: MEDIUM
```

Пояснение: «Без поля `trust` файл не попадёт в память (memory-sync пропустит его).»

После валидации — вывести резюме для подтверждения.

### A2.4. Conditional architecture validation

**Если тип `scenario-events`** (артефакт от `scenario-builder`) — запустить:

```bash
echo '<payload_json>' | python3 scripts/assemble_artifact.py validate-scenario-events
```

Payload — это содержимое YAML-артефакта, переданное как JSON. Проверяет:
- обязательные поля: `type`, `schema_version`, `matrix`, `scenario_triggers`, `reviews`
- Σ `scenario_triggers[*].probability` ∈ [0.98, 1.02] (warning при нарушении)

**Если тип `forecast-events`** (артефакт от FCA / macro-forecast-chain) — запустить
(STL-5 закрыт 2026-08-03: автоматическая валидация живёт в `validate-forecast-events`,
отдельный `validate_schema.py` не нужен):

```bash
echo '<payload_json>' | python3 scripts/assemble_artifact.py validate-forecast-events
```

Payload — содержимое YAML-артефакта как JSON. Проверяет Type 1/Type 2 (взаимоисключение
`isolated` ↔ `conditional_on_scenarios`), все 4 сценария в `by_scenario`, `source_matrix`,
`unit` один на блок, канон provenance §5.2.1 (6 значений; legacy-имена → blocking с
подсказкой миграции), форму `upstream_used`, калибровочные блоки §14–§19 (fca_stats /
outcome_log / конус F1 / confidence F3 / l2_informative F5 / deferred).

**Для НОВОГО артефакта от FCA** — добавить в payload `"_strict": true`: кросс-правила
provenance ↔ `sources_used`/`upstream_used` и известные non-spec формы FCA-вывода
(`horizon_YYYY`-ключи, `central_estimate`/`p10`/`p90` внутри values, `sources_used`
числом, `coherence_diagnostic` внутри блока) становятся blocking. Без `_strict`
(ре-валидация уже сохранённых файлов) те же кросс-правила — warning. Канон формы —
общий модуль `fca_output_checks.py` (репо-канон, бандлится pack.sh в scripts/ FCA
через его `bundle_scripts:`); FCA гоняет его же на своём Шаге 6
(`validate_fca_output.py`), drift запинен контракт-тестом.

Ручной остаток (не покрыт скриптом): **implicit_geopolitical_scenarios** (audit
frontmatter): `primary.weight + secondary.weight == 1.0` (или `agnostic_total: true`);
**3D trust** — backward-compat 1D/2D через fallback на `trust.marginal`;
**modal_scenario_id**: `argmax(weights)` если `max > 0.30`, иначе `none`.

Если валидация упала с критической ошибкой — остановить запись, показать пользователю
diagnostic. Warnings (не критические) — записать в результат, но не блокировать.

### A2.5. Полнота trust-треков (для аудитов от retrospective-forecast-audit)

Если файл является выводом `retrospective-forecast-audit` (тип Full / Light Audit — видно по шапке):

Явно спроси себя: **все ли тематические треки аудита представлены в trust?**

Пример-триггер: аудит содержит тезисы по ВВП России, ВВП США, рецессии, нефти — но в trust только `oil-forecast` и `recession-call`. Это сигнал, что `ru-economy-growth` и `us-macro-gdp` были молча свёрнуты. В таком случае:

1. Вывести список тематических кластеров из аудита (в 1–2 строки)
2. Сверить с trust
3. Если несовпадение — сообщить пользователю:
   > «В аудите есть тезисы по [темам X, Y], но в trust нет соответствующих субдоменов. Добавить их перед сохранением?»

Если пользователь говорит «нет, так и надо» — сохранять как есть. Если «да» — уточнить уровень (HIGH/MEDIUM/LOW/IGNORE) и добавить в frontmatter.

### A3. Определение subfolder

Канонический маппинг — `references/subfolder-mapping.md`. Алгоритм:

1. Посчитать совпадения trust-subdomain'ов с каждым subfolder'ом
2. Выбрать subfolder с наибольшим количеством совпадений
3. Равный счёт → высказать сомнение, спросить
4. Никаких совпадений → спросить, не изобретать

### A4. Проверка auto-inclusion

```
include_in_memory = pin == true  ИЛИ  хотя бы один subdomain с trust == HIGH
```

Если `False` — сообщить и предложить (a) сохранить как есть, (b) `pin=true`, (c) пересмотреть trust.

### A5. Проверка дублей

Поиск файлов с тем же `source` в subfolder. Если найден — спросить: (a) новый аудит, (b) заменить, (c) отмена.

### A6. Сохранение, INDEX.md и _sync_log.md

**Имя файла:** `{source-kebab}-{period}.md`

Примеры: `iea-omr-2025-h2.md`, `stratfor-2026-q1.md`, `invest-era-2026-04.md`

Запись в `Claude-Memory/domains/{subfolder}/{filename}.md` (детали транспортов — в `transport-layer.md`).

Обновить:
- `domains/{subfolder}/INDEX.md` — таблица track record
- `Claude-Memory/INDEX.md` (master) — сводный track record

Добавить запись в `Claude-Memory/_sync_log.md`:
```
{YYYY-MM-DD} | save-to-library | domains/{subfolder}/{filename}.md | Workflow A | source: {source} | auto-inclusion: {true/false}
```
Формат строки — `{дата} | save-to-library | {путь} | Workflow {X}[ (вариант)] | {ключ: значение | …}`; строка дописывается в конец `_sync_log.md` (`update_index.py sync-log`).

**Финальное сообщение:**
```
✅ Сохранено: Claude-Memory/domains/{subfolder}/{filename}.md
source: "{source}" | period: {period} | trust: {summary}
Auto-inclusion в memory: {да/нет/да pinned}

Следующий шаг: запустить memory-sync? (да / нет, позже)
```

При `auto-inclusion: false` (все subdomain `LOW`/`IGNORE` и `pin` не `true`) добавить в финальное сообщение строку:
«Trust = LOW/IGNORE, pin = false → при следующем `memory-sync` этот источник **не попадёт** в память. Чтобы включить принудительно — добавь `pin: true` в frontmatter.»

