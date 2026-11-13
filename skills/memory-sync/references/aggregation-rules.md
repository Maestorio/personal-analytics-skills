# Aggregation Rules: правила агрегации множественных аудитов одного источника

Один источник может иметь несколько аудитов разных периодов. В memory попадает ОДИН агрегат на источник. Здесь описано, как агрегировать.

## Идентификация источника

**Ключ агрегации** — поле `source` в YAML frontmatter. Регистр и пробелы нормализуются:
- `"Stratfor"` == `"stratfor"` == `" Stratfor "`
- `"BCS"` != `"БКС"` (считаются разными источниками — это методологически правильно: транслит и кириллица могут быть разными ресурсами)

Если в библиотеке есть оба варианта написания — в логе предупреждение: «Возможный дубликат: 'BCS' и 'БКС' — слить вручную, если это один источник».

## Правила агрегации полей

### `trust` (по subdomain)

**Newest аудит wins** для subdomain'ов, упомянутых в обоих.

Пример:
- Stratfor 1995–2025: `{long-term-russia: HIGH, eu-future: IGNORE, china-collapse: IGNORE}`
- Stratfor 2015–2025: `{long-term-russia: MEDIUM, china-collapse: LOW, middle-east: HIGH}`

Newest = 2015–2025 (по `period` end-year или `last_updated`).

Финальный агрегат:
- `long-term-russia: MEDIUM` (newest перетёр)
- `eu-future: IGNORE` (есть только в старом — сохраняется)
- `china-collapse: LOW` (newest перетёр)
- `middle-east: HIGH` (есть только в новом — добавляется)

### `pin`

Логическое ИЛИ: если хотя бы один аудит источника имеет `pin: true`, источник считается pinned.

### `last_audit_date`

Максимум по всем аудитам источника (формат YYYY-MM-DD).

### `audit_count`

Количество файлов аудитов с этим `source` в библиотеке.

### `subdomains_covered`

Объединение subdomain'ов из всех аудитов (для INDEX.md и трекинга покрытия).

## Sort order для newest

При определении «newest» проверять поля в таком порядке:

1. **`last_updated`** в frontmatter (если есть) — приоритет 1
2. **`period`** end-year (если есть) — приоритет 2
3. **mtime файла** на диске — приоритет 3 (последний fallback)

Если оба поля `last_updated` и `period` отсутствуют — это отклонение от стандарта. В логе предупреждение, но источник всё равно агрегируется по mtime.

## Edge cases

### Случай 1: Аудит без поля `trust`

Файл пропускается. В логе:
```
- skip: ru-sellside/atom-2024.md — нет поля trust в frontmatter
```

Этот файл НЕ участвует в агрегации источника `Atom`, даже если другие аудиты Atom есть в библиотеке.

### Случай 2: Конфликт между аудитами одной даты

Если два аудита имеют одинаковый `last_updated` (например, оба сделаны в один день) — выбирается тот, у которого выше `audit_type`:
- Full > Light
- Если оба Full / оба Light — выбирается с большим `theses_count` (поле в frontmatter, опциональное)
- Если и оно совпадает — файл с лексически меньшим именем (детерминизм)

### Случай 3: Конфликтующие trust в одном subdomain

Не возникает после применения «newest wins». Каждый subdomain имеет ровно одно значение из newest аудита, упомянувшего этот subdomain.

### Случай 4: Источник упомянут в нескольких subfolders

Маловероятно (источник обычно «принадлежит» одному домену), но возможно: например, Goldman Sachs может быть в `global-banks/` и `geopolitics/` (если делает геополитические прогнозы).

Правило: разные файлы агрегируются независимо от их subfolder'а — ключ агрегации это `source` в frontmatter, не путь к файлу. Goldman Sachs остаётся одним источником.

В trust агрегате могут быть subdomain'ы из разных доменов:
```
[lib] Goldman Sachs: HIGH us-equities, MEDIUM oil-forecast, LOW geopolitics-eu
```

### Случай 5: Источник с одним subdomain

Одна запись trust = один subdomain. Это нормально для узкоспециализированных источников.

```yaml
source: "Кремль про"
trust:
  ru-domestic-policy: MEDIUM
```

→ `[lib] Кремль про: MEDIUM ru-domestic-policy | last_audit 2025-12-15 | N=1`

### Случай 6: Все аудиты источника старше 24 месяцев

Не блокирует включение в memory, если auto-inclusion критерий пройден (HIGH или pin). Но в финальной статистике помечается:

```
- [lib] Old Source: ... | last_audit 2023-08-10 | N=2 ⚠️ stale (>24 мес)
```

И в Шаге 8 (Eviction) — это первый кандидат на удаление при приближении к лимиту 30.

## Пример полной агрегации

**Файлы в библиотеке:**

```
geopolitics/stratfor-1995-2025.md  (last_updated: 2024-11-20, period_end: 2025)
geopolitics/stratfor-2015-2025.md  (last_updated: 2025-03-15, period_end: 2025)
geopolitics/stratfor-2020-2030.md  (last_updated: 2026-04-22, period_end: 2030, pin: true)
```

**Агрегация:**

| Поле | Значение |
|---|---|
| `source` | Stratfor |
| Newest аудит | 2020–2030 (last_updated: 2026-04-22) |
| `trust` (с newest перекрытием) | См. ниже |
| `pin` | true (от 2020–2030) |
| `last_audit_date` | 2026-04-22 |
| `audit_count` | 3 |

**Trust merge** (старший → младший по дате):

```
1995-2025: {long-term-russia: HIGH, eu-future: IGNORE, china-collapse: IGNORE}
+ 2015-2025: {long-term-russia: MEDIUM, china-collapse: LOW, middle-east: HIGH}
+ 2020-2030 (newest): {middle-east: MEDIUM, ai-geopolitics: IGNORE}

Финал:
  long-term-russia: MEDIUM     (от 2015-2025, не упомянут в 2020-2030)
  eu-future: IGNORE             (только в 1995-2025)
  china-collapse: LOW           (от 2015-2025)
  middle-east: MEDIUM           (от 2020-2030, перетёр HIGH из 2015-2025)
  ai-geopolitics: IGNORE        (только в 2020-2030)
```

**Auto-inclusion check:**

Нет HIGH ни в одном subdomain в финале. НО `pin: true` (от 2020-2030).
→ Включается в memory.

**Запись в memory:**

```
[lib] Stratfor: MEDIUM long-term-russia, MEDIUM middle-east, IGNORE eu-future/china-collapse/ai-geopolitics, LOW china-collapse | last_audit 2026-04-22 | N=3
```

(близко к 500 симв — будет применено сокращение по format-templates.md, см. формат «top: HIGH={список}, avoid: IGNORE={список}»)

## Что НЕ делать при агрегации

❌ **Не средить trust значения.** Если 2 аудита дают HIGH и LOW — это не «MEDIUM в среднем», это «MEDIUM от newest или LOW от newest» в зависимости от того, какой newest. Усреднение скрывает методологический сигнал «track record менялся со временем».

❌ **Не считать pin'нутый аудит «более авторитетным».** Pin влияет только на auto-inclusion. На trust merge не влияет — там работает только newest-wins.

❌ **Не агрегировать аудиты разных сторон одного материала.** Если есть retrospective-forecast-audit на «Stratfor 2015-2025» и meta-аудит «Dungaciu et al. о Stratfor» — это разные источники (`source: Stratfor` и `source: Dungaciu et al.`). Не путать.
