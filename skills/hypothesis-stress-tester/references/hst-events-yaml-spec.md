# Events YAML stress-pair для hypothesis-stress-tester

## Шаблон

```markdown
## Events YAML stress-pair (для save-to-library)

\`\`\`yaml
# Stress-pair расширяет Tier 1 yaml до Tier 2. Если Tier 1 ещё не существует
# (HST на чужом тексте без FCA) — save-to-library создаст Tier 1 с
# null+TODO маркерами для central_estimate и confidence.

monitoring:        # из «Что проверить в первую очередь» + leading indicators KAC
  - id: {slug}
    description: "{что проверяем}"
    threshold: "{конкретный порог}"
    check_date: {YYYY-MM-DD}
    impact: invalidates|supports|mixed
    severity: critical|high|medium
    auto_checkable: true|false
    # source — отсутствует (HST не имеет источников; пользователь добавит при необходимости)

assumptions:       # из KAC, только ⚠️ критические (LOW обоснованность + Критическая чувствительность)
  - id: {slug}
    text: "{допущение}"
    robustness: HIGH|MEDIUM|LOW
    sensitivity: critical|moderate|low
    auto_checkable: false   # ВСЕГДА false

thresholds:        # из Sensitivity sweep, только пункты «флипает: Да»
  - id: {slug}
    variable: "{переменная}"
    condition: "{при каком значении флипает}"
    flips_to: "{альтернативный исход или scenario_id если есть}"
    auto_checkable: true|false

deadlines:         # из Reversibility check, только если есть точка невозврата
  - id: {slug}
    date: {YYYY-MM-DD}
    description: "{что происходит}"
    action: "{что делать при наступлении}"
    auto_checkable: true   # ВСЕГДА true (дата проверяется автоматически)

falsifiers:        # из Pre-mortem, топ-3 причины провала
  - id: {slug}
    description: "{событие фальсификации}"
    would_resolve: true|false   # true → прогноз закрывается status=resolved
    auto_checkable: true|false

agents:            # из Red team
  - id: {slug}
    agent: "{кто}"
    action: "{что делает}"
    window: "{YYYY-MM-DD/YYYY-MM-DD}"
    impact: invalidates|mixed|supports
    severity: critical|high|medium
    auto_checkable: false   # ВСЕГДА false (agent intent требует суждения)
\`\`\`
```

## Правила секций

- **Включается только секция, где есть item-ы.** Пустые секции не выводятся.
- **`monitoring`** обязательно содержит как минимум 1 item (из «Что проверить в первую очередь»).
- **`assumptions`** — ТОЛЬКО ⚠️ из KAC (LOW + Критическая). Если нет ⚠️ — секция отсутствует.
- **`thresholds`** — ТОЛЬКО переменные с флипом «Да» из sensitivity sweep.
- **`deadlines`** — ТОЛЬКО если в Reversibility check есть конкретная точка невозврата с датой.
- **`falsifiers`** — топ-3 причины из Pre-mortem; описание из формулировки причины.
- **`agents`** — только из Red team (если был запущен).

## Patch-merge правило (КРИТИЧНО)

HST patch почти всегда ложится на YAML, где **Tier 1 уже содержит** хотя бы один из тех же top-level ключей (`monitoring:` от FCA; иногда `falsifiers:` или `deadlines:`).

**Правило:** items из HST-блока **дописываются в существующий список** соответствующего ключа. Категорически нельзя выводить второй top-level ключ с тем же именем — YAML такое запрещает, js-yaml во viewer падает на всём файле, PyYAML молча перетирает предыдущий список.

Конкретно:
- В выводе HST блока `## Events YAML patch` — выводить ключи, как если бы это был самостоятельный YAML (`monitoring:` со своими items).
- **`save-to-library` при merge'е** (workflow B4.2 / B5) обязан слить списки items, а не дублировать ключи.
- Перед записью save-to-library запускает `python3 assemble_artifact.py check-yaml-duplicates` на итоговом тексте; если есть top-level дубль — операция блокируется.

Если HST-merge архитектурно невозможен (например, item конфликтует по `id` с Tier 1) — выпускать отдельный stress-pair файл `<slug>-<date>-stress.{md,yaml}` (см. CLAUDE.md «forecasts/», правило о параллельной паре).

## Quick-режим

В quick-режиме блок содержит ТОЛЬКО:
- `monitoring` (из «Что проверить в первую очередь»)
- `falsifiers` (топ-3 из Pre-mortem)

Остальные секции опускаются.

## Slug-правило

Канонический источник: `file-naming.md` §«Slug-правила» и §«Stress-pair slug rules» (инжектится из shared_refs при упаковке). Кратко:
- lowercase, ISO 9 транслит для кириллицы
- стоп-слова отсеять
- первые 3 значимых слова, дефисы
- ≤30 символов
- уникальность в файле — обязательна (коллизия → суффикс `-2`, `-3`)
- stress-пара: `<base-slug>-stress.{md,yaml}`, `<base-slug>` совпадает с Tier 1 парой

## auto_checkable правила

| Поле | Значение |
|------|---------|
| `monitoring` | true если есть числовой `threshold` или конкретная дата события; иначе false |
| `assumptions` | **всегда false** (требует интерпретации) |
| `thresholds` | true если численная переменная; false если качественная |
| `deadlines` | **всегда true** |
| `falsifiers` | true если есть числовой порог; false если требует суждения |
| `agents` | **всегда false** (agent intent — суждение) |
