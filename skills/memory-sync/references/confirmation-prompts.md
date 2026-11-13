# Confirmation Prompts: точные формулировки для destructive операций

## Общие принципы

1. Любой `remove` или `replace` показывается ДО выполнения.
2. Несколько destructive операций группируются в один prompt — пользователь решает один раз.
3. `add` для новых источников выполняется автоматически без подтверждения (не destructive).
4. Подтверждение должно быть явным: «да», «подтверждаю», «применить», «yes». Уклончивые ответы («наверно», «может быть») трактуются как отказ — лучше переспросить.

## Формат батч-prompt'а

Когда destructive операций больше 0, после Шага 7 (Diff) показать:

```markdown
## Sync: предложенные изменения

**ADD (выполню автоматически после подтверждения всего блока):**
- [#new] [lib] CFR: HIGH iran, MEDIUM russia | last_audit 2026-04-22 | N=1
- [#new] [lib] Invest Era: HIGH iis-targets, LOW long-term | last_audit 2026-03-10 | N=1

**REPLACE (требуют подтверждения):**
- #5 «[lib] Stratfor: ...» → «[lib] Stratfor: MEDIUM long-term-russia, MEDIUM middle-east, IGNORE eu-future ...»
  Причина: добавлен аудит 2020-2030, newest-wins перетёр HIGH long-term-russia на MEDIUM
- #8 «[lib] CBR: ...» → «[lib] CBR: HIGH ru-rates-forecast, HIGH ru-inflation ...»
  Причина: добавлен subdomain ru-inflation, MEDIUM повышен до HIGH

**REMOVE (требуют подтверждения):**
- #11 «[lib] BCS: LOW long-term, LOW china-stocks ...»
  Причина: trust только LOW во всех subdomain, не pinned, последний аудит 2024-08-10 (>18 мес назад)

**Итого после применения:**
- USER_ENTRIES: 6 (без изменений)
- LIB_ENTRIES: 9 (было 7, +2 add, −1 remove, 2 replace)
- Свободно слотов: 15

Применить все изменения? (да / нет / выборочно)
```

## Обработка ответов пользователя

### «Да» / «применить» / «yes» / «подтверждаю»
Выполнить все операции в порядке: replace → remove → add. Это порядок безопасности: replace и remove на старом списке, add на освободившемся месте.

### «Нет» / «отмена»
Прервать sync. В лог записать: `cancelled by user`. Memory не модифицируется.

### «Выборочно»
Выдать пронумерованный список ВСЕХ destructive операций (replace + remove) с возможностью указать номера к подтверждению:

```
1. [REPLACE] #5 Stratfor
2. [REPLACE] #8 CBR
3. [REMOVE] #11 BCS

Какие применить? (например: «1, 3» или «все кроме 2» или «только remove»)
```

После выбора — применить только выбранные + все add'ы.

### Уклончивый ответ
Если ответ не однозначно «да» / «нет» / «выборочно», переспросить:

```
Не уверен в ответе. Подтверди явно: «да» (применить всё), «нет» (отмена), «выборочно» (по операциям).
```

## Edge case: только add'ы

Если destructive операций ноль (только add'ы) — НЕ показывать prompt, выполнить молча, в чате выдать:

```
✅ Sync: добавлено 2 новых источника в memory
- [lib] CFR: HIGH iran, MEDIUM russia | last_audit 2026-04-22 | N=1
- [lib] Invest Era: HIGH iis-targets, LOW long-term | last_audit 2026-03-10 | N=1
Лог: Claude-Memory/_sync_log.md
```

## Edge case: ничего не изменилось

Если diff пустой:

```
✅ Sync: библиотека и memory консистентны, изменений нет.
Текущее состояние: USER_ENTRIES=6, LIB_ENTRIES=8, свободно 16 слотов.
Лог: Claude-Memory/_sync_log.md
```

## Eviction prompt (Шаг 8)

Если предполагаемое финальное количество ≥ 28, перед основным confirmation prompt'ом показать:

```markdown
## ⚠️ Близко к лимиту memory (30 записей)

Предполагаемое финальное состояние: 28 из 30 записей.

Кандидаты на eviction (отсортированы от первого к последнему по приоритету удаления):

1. [lib] Source A — trust только LOW/IGNORE, не pinned, last_audit 2024-08-10 (>18 мес)
2. [lib] Source B — trust только MEDIUM/LOW, не pinned, last_audit 2024-12-01 (~12 мес)
3. [lib] Source C — pinned, но last_audit 2024-05-10 (>20 мес) — pin может быть устаревшим

Хочешь:
(a) Удалить кандидата #1 — освободить слот для новых
(b) Удалить кандидатов #1 и #2 — больше запаса
(c) Не удалять — sync не добавит N новых источников, замечу в логе
(d) Другой выбор — укажи номера

Что выбираешь?
```

После ответа на eviction prompt — переходить к основному confirmation prompt'у с обновлённым diff.

## Scheduled task (Cowork) — особый режим

В Cowork scheduled task пользователь не отвечает в момент запуска. По стандартной настройке (см. `SKILL.md` § Scheduled task в Cowork):

- Если destructive операций 0 — выполнить sync, отчитаться summary в чат
- Если destructive операций >0 — НЕ выполнять, только выдать pending list и ждать пользователя в следующем chat-режиме

Pending list сохраняется в `Claude-Memory/_pending_sync.md`:

```markdown
# Pending sync — 2026-04-26 21:00 MSK

При следующем интерактивном запуске memory-sync обработать:

[REPLACE]
- #5 Stratfor → ...
- #8 CBR → ...

[REMOVE]
- #11 BCS

[ADD выполнены автоматически]
- [lib] CFR ✓
- [lib] Invest Era ✓
```

При следующем запуске memory-sync проверяет наличие `_pending_sync.md` и предлагает разобрать в первую очередь.

## Подтверждение при первом запуске

Setup-режим (см. `SKILL.md` § Setup) — отдельная история. Создание структуры папок:

```
Создаю структуру:
- Claude-Memory/
  - INDEX.md
  - geopolitics/INDEX.md
  - ru-sellside/INDEX.md
  - global-banks/INDEX.md
  - tech-ceo/INDEX.md
  - ru-macro/INDEX.md
  - _sync_log.md (создастся при первом sync)

Целевой путь: ~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/
Подтвердить? (да / другой путь)
```

После подтверждения — `bash mkdir -p ...` и создание шаблонов из `references/index-templates.md`.

## Error в parsing аудита (не destructive, но важно показать)

Если при сканировании обнаружены файлы с битым frontmatter:

```
⚠️ Sync: 2 файла пропущены из-за ошибок парсинга:
- ru-sellside/atom-2024.md — нет YAML frontmatter
- geopolitics/cfr-2024.md — поле trust пустое

Эти источники НЕ попадут в memory до починки. Файлы остаются в библиотеке.

Продолжить sync без них? (да / нет)
```

После ответа — продолжить со здоровыми файлами, ошибки залогировать в `_sync_log.md`.
