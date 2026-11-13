# Format Templates: шаблоны записей [lib] и правила сокращения

## Базовый формат

```
[lib] {source}: {trust_summary} | last_audit {YYYY-MM-DD} | N={audit_count}
```

**Лимит:** 500 символов. Реальная цель — 200–350 симв. для читаемости. 500 — hard cap.

## Структура `trust_summary`

Subdomain'ы группируются по trust level от высшего к низшему: HIGH → MEDIUM → LOW → IGNORE.

Внутри одного trust level — subdomain'ы перечисляются через запятую, в алфавитном порядке.

### Базовый шаблон

```
HIGH {sd1}, HIGH {sd2}, MEDIUM {sd3}, LOW {sd4}, IGNORE {sd5}
```

### Сокращённый шаблон (когда subdomain'ов много)

```
HIGH: {sd1}, {sd2} | MEDIUM: {sd3} | IGNORE: {sd4}, {sd5}
```

### Очень компактный (когда близко к 500 симв)

```
top: HIGH={sd1, sd2} | avoid: IGNORE={sd4, sd5}
```

(MEDIUM и LOW отбрасываются — они менее actionable; полный профиль остаётся в файле)

## Стратегия сокращения

Если базовый формат превышает 500 симв:

**Шаг 1.** Перейти на сокращённый шаблон (HIGH: {} | MEDIUM: {} | LOW: {} | IGNORE: {}).

**Шаг 2.** Если всё ещё длинно — отбросить LOW и MEDIUM, оставить только HIGH и IGNORE.

**Шаг 3.** Если всё ещё длинно — сократить subdomain имена до 20 символов с многоточием (`long-term-russia` → `long-term-russia`, `middle-east-conflicts` → `middle-east-confli...`).

**Шаг 4.** Если всё ещё длинно — переключиться на компактный шаблон `top: HIGH={} | avoid: IGNORE={}`.

**Шаг 5.** Если ВСЁ ЕЩЁ длинно (>15 subdomain'ов в HIGH+IGNORE) — обрезать до топ-3 в каждом, добавить «+N» в конце:

```
[lib] Source: top: HIGH={sd1, sd2, sd3} +2 | avoid: IGNORE={sd6, sd7} +1 | last_audit 2026-04-22 | N=5
```

В логе при таких сокращениях пометка: «Профиль источника {Source} сокращён до топ-N — полный профиль в `{path/to/file.md}`».

## Примеры

### Пример 1: компактный профиль

```
[lib] CFR: HIGH iran, MEDIUM russia | last_audit 2026-04-22 | N=1
```

(57 симв — отлично)

### Пример 2: средний

```
[lib] Stratfor: HIGH long-term-russia, MEDIUM middle-east, LOW china-collapse, IGNORE eu-future, IGNORE ai-geopolitics | last_audit 2026-04-22 | N=3
```

(151 симв — отлично)

### Пример 3: близко к лимиту

Если subdomain имена длинные и их много, базовый формат может перевалить за 500.

Source: «Goldman Sachs» с 12 subdomain'ами по разным trust levels.

Базовый (превышает 500):
```
[lib] Goldman Sachs: HIGH us-equities, HIGH oil-forecast, HIGH ny-rates, MEDIUM emerging-markets, MEDIUM european-equities, MEDIUM ru-equities, LOW currency-forecasts, LOW commodities-non-oil, IGNORE geopolitics-eu, IGNORE geopolitics-ru, IGNORE crypto, IGNORE ai-stocks-bubble | last_audit 2026-03-10 | N=4
```
(303 симв — на самом деле ОК, но допустим что 600+)

Сокращённый (Шаг 1):
```
[lib] Goldman Sachs: HIGH: us-equities, oil-forecast, ny-rates | MEDIUM: emerging-markets, european-equities, ru-equities | LOW: currency-forecasts, commodities-non-oil | IGNORE: geopolitics-eu, geopolitics-ru, crypto, ai-stocks-bubble | last_audit 2026-03-10 | N=4
```

Top + Avoid (Шаг 4):
```
[lib] Goldman Sachs: top: HIGH={us-equities, oil-forecast, ny-rates} | avoid: IGNORE={geopolitics-eu, geopolitics-ru, crypto, ai-stocks-bubble} | last_audit 2026-03-10 | N=4
```

(184 симв — компактно)

### Пример 4: только pin, никаких HIGH (попадает по pin)

```
[lib] Atom: MEDIUM small-caps-ru, LOW long-term-strategy | last_audit 2026-01-15 | N=1 (pinned)
```

(Пометка `(pinned)` в конце — visual cue, что источник в memory не за HIGH, а за ручной pin.)

### Пример 5: aged source (>18 мес)

```
[lib] Old Source: HIGH economy-2020 | last_audit 2024-08-10 | N=2 ⚠️ stale
```

(Пометка `⚠️ stale` — кандидат на eviction при заполнении лимита.)

## Принципы именования subdomain'ов

Чтобы trust_summary был коротким, рекомендуется в YAML frontmatter аудитов использовать:

- **kebab-case**, не CamelCase: `long-term-russia`, не `LongTermRussia`
- **Латиницу**, не кириллицу (короче): `eu-future`, не `будущее-ес`
- **Универсальные термины**, не специфические события: `oil-forecast`, не `brent-2025-target`
- **15 символов или меньше**: `iran` лучше чем `iran-nuclear-program-future-stance`
- **Переиспользовать** subdomain'ы между источниками: если у одного источника `long-term-russia`, у другого тоже — это правильно (позволяет cross-source comparison)

Полный list рекомендуемых subdomain'ов — в `references/index-templates.md`.

## Что НЕ показывать в записи

❌ Содержание самих прогнозов (это в файле аудита).
❌ Hit rate, альфа-генерация (это в файле аудита).
❌ Ссылки на файлы аудита (memory не место для путей; путь восстанавливается из `source` через INDEX.md).
❌ Эмодзи кроме `⚠️ stale` (засоряет визуально).
❌ Имя автора-эксперта внутри организации (только source-level: «Stratfor», не «Stratfor / Friedman»).

## Длина текста — финальная проверка

Перед записью каждой `[lib]` строки:

1. Подсчитать длину
2. Если >500 — применить сокращение по шагам
3. Если итог 480–500 — попробовать сократить ещё на безопасные 50 симв (буфер на эвентуальные дополнения в будущем)
4. Если получившийся текст идентичен текущему в memory — пропустить (нет операции replace)
