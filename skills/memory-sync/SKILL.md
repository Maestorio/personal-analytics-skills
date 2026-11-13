---
name: memory-sync
description: >-
  Синхронизирует библиотеку аудитов из Claude-Memory в память профиля Claude (mcp__memory: корень — уровень профиля, /lib_{source}.md + индекс /memory-notes.md; копии в projects/* выравниваются). Читает из локального пути Synology Drive (~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/). Парсит YAML frontmatter аудитов, формирует компактные профили (≤500 симв.), применяет add/replace/remove с подтверждением для destructive. Legacy-цель memory_user_edits — только если доступна. Работает только с записями [lib]. Eviction policy при лимите 30. Пишет лог в _sync_log.md. Используй когда пользователь говорит «синхронизируй память», «обнови memory из библиотеки», «memory sync». Целевая модель — Sonnet.
shared_refs: [transport-layer, audit-frontmatter-schema, claude-memory-layout]
---

# memory-sync

Синхронизирует библиотеку аудитов из Claude-Memory (Synology) в **память профиля** Claude.

**Архитектурная роль:** файлы библиотеки — source of truth; память профиля — кеш, чтобы `[lib]`-профили
работали в любом чате и проекте **без доступа к Claude-Memory**. Поэтому цель — уровень профиля, а не проекта.

---

## Хранилище памяти (где живут `[lib]`-записи)

С 2026-10 основное хранилище — файловая память `mcp__memory` (кейс 2026-10-02: `memory_user_edits`
в сессиях отсутствовал, `[lib]` нашлись только в проектах, на уровне профиля их не было).

| Уровень | Путь в `mcp__memory` | Роль |
|---|---|---|
| **Профиль (цель записи)** | `/lib_<slug>.md` — по файлу на источник; `/memory-notes.md` — индекс, одна строка на источник | читается в любом чате/проекте |
| Проекты (копии) | `/projects/<id>/lib_<slug>.md`, `/projects/<id>/memory-notes.md` | исторические копии; если есть — выравниваются **по корню** |

- `<slug>` — kebab/snake от `source` (`Invest Era` → `lib_invest_era.md`), как в существующих файлах.
- Файл `lib_<slug>.md`: frontmatter (сохранить существующие поля; обновить `description`, `trust.marginal`,
  `last_audit`, `N`; `sources` дополнить значением, которое требует формат памяти, напр. `cowork`) +
  тело — ровно одна строка `memory_text` из планировщика.
- Строка индекса: `- [[lib] {source}](lib_<slug>.md) — {trust через «/»} | last_audit {date} | N={n}`
  (+ хвост `| implicit: …`, если он уже был — не терять).
- Снимки вида `*.pre-tagging`, `*.bak-*` не трогать и в состояние не включать.

**Порядок выбора цели:** `mcp__memory` доступен → пишем туда (основной путь). Нет, но есть
`memory_user_edits` → legacy-путь (старые add/replace/remove). Нет ни того, ни другого → **не выдумывать
причину/окружение**: вывести готовые строки (`memory_text` + строку индекса), пометить в `_sync_log.md`
«план подготовлен, не применён: нет инструмента памяти» и остановиться.

---

## Inputs / Outputs

**Inputs:**
- `Claude-Memory/domains/*/` YAML frontmatter ← Synology mount (Glob `domains/*/`)
- Текущий state памяти профиля ← `mcp__memory` (корень `/lib_*.md`, `/memory-notes.md`; копии в `/projects/*/`); legacy — `memory_user_edits view`
- `Claude-Memory/_sync_log.md` ← Synology mount

**Outputs (пишет напрямую, без буфера чата):**
- `mcp__memory`: `/lib_<slug>.md` + строки `/memory-notes.md` (add/replace/remove `[lib]`) и выравнивание копий в `/projects/*/`; legacy — `memory_user_edits`
- `Claude-Memory/_sync_log.md` — обновлён записью о синхронизации

**Upstream скиллы:** save-to-library (пишет источники в domains/)
**Downstream скиллы:** —
**Shared refs:** transport-layer, audit-frontmatter-schema, claude-memory-layout

---

## Транспортный слой

Читай `references/transport-layer.md` перед Шагом 0 — там пути и типовые операции.
Транспорт один — Synology mount. Недоступен → остановиться и сообщить пользователю.

---

## Глобальные принципы

0. **Язык вывода — русский.**

1. **Файлы — source of truth.** Никогда не модифицируем файлы из memory. Поток данных строго односторонний: file → memory.

2. **`[lib]` префикс — граница ответственности.** Скилл управляет ТОЛЬКО `[lib]`-записями (файлы `lib_*.md` и их строки в `memory-notes.md`; в legacy — записи memory_user_edits с префиксом `[lib]`). `profile.md`, `preferences.md`, `areas/`, `people/`, `topics/` не трогаются никогда. Пользовательские записи без префикса не трогаются никогда.

3. **Подтверждение для destructive.** Любая операция `remove` или `replace` показывается пользователю ДО выполнения. Операция `add` для новых источников выполняется автоматически. Если destructive операций больше 5 — батчится в один confirmation prompt.

4. **Никогда не fabricate trust.** Если файл не парсится корректно — источник пропускается, в логе фиксируется ошибка.

5. **Auto-inclusion правило:** в memory попадают источники с `trust: HIGH` хотя бы в одном subdomain ИЛИ с явным `pin: true`. Всё остальное — только в файлах.

---

## Workflow

### Шаг 0. Проверка транспорта

Выполни проверку доступности из `references/transport-layer.md`.

**Гард корня памяти.** Запись `/lib_*.md` и `/memory-notes.md` в корень `mcp__memory` проверить до планирования
(пробная запись/чтение корня). Корень не пишется (сессия привязана к проекту) → остановиться и сказать:
«запусти `/memory-sync` в чате вне проекта». Запись в копии `/projects/*/` вместо корня как вариант не предлагать.

---

### Шаг 1. Локализация библиотеки

```
LOCAL_LIBRARY_ROOT  = "~/Library/CloudStorage/SynologyDrive-home/Claude-Memory"
LOCAL_DOMAINS_ROOT  = "{LOCAL_LIBRARY_ROOT}/domains/"
```
Проверить доступность: `Glob("*", path=LOCAL_LIBRARY_ROOT)`.
Если недоступна → вызвать `request_cowork_directory(LOCAL_LIBRARY_ROOT)`;
не помогло → остановиться и сообщить пользователю.

### Шаг 2. Чтение текущего состояния memory

Основной путь (`mcp__memory`):
1. Прочитать корень: `/lib_*.md` (кроме снимков `*.pre-tagging`, `*.bak-*`) и `/memory-notes.md`.
2. Собрать `current_memory` для планировщика: `{id: "<путь к lib_*.md>", text: "<строка тела [lib] ...>"}`.
   `id` — путь к файлу, не число.
3. Отдельно составить список копий в `/projects/*/lib_*.md` и строк `[lib]` в `/projects/*/memory-notes.md`
   (в планировщик не передаются — нужны для шага выравнивания).

Legacy (`memory_user_edits`): `view` → плоский список `{id, text}`; split на
`LIB_ENTRIES` / `USER_ENTRIES` сделает скрипт по префиксу `[lib]`.

### Шаг 3. Сканирование библиотеки

Список доменов **не фиксирован** — он определяется динамически через Glob. Это
позволяет добавлять новые домены в `Claude-Memory/domains/` без правки скилла.

1. Обнаружить домены:
   ```
   Glob("*/", path="{LOCAL_DOMAINS_ROOT}")  →  список domain_dirs
   ```
   Если список пуст → вывести предупреждение («domains/ пуста или недоступна»), не прерывать.
2. Для каждого `domain_dir` из списка:
   ```
   Glob("*.md", path="{LOCAL_DOMAINS_ROOT}/{domain_dir}/")
   ```
   Исключить: `INDEX.md`, `_sync_log.md`, файлы начинающиеся на `_`.
3. Прочитать каждый файл:
   ```
   Read("{LOCAL_DOMAINS_ROOT}/{domain_dir}/{filename}.md")
   ```
   Извлечь YAML frontmatter (между `---` разделителями).
   Если frontmatter отсутствует или не парсится → передать скрипту с `frontmatter: null` (не пропускать).

**Никакой логики «пропустить если нет trust».** Передавай скрипту все файлы
с распарсенным frontmatter — он сам распределит на skipped / aggregated.

---

### Шаги 4–8 — Делегируется `scripts/sync_planner.py`

Агрегация по источникам, auto-inclusion, форматирование `[lib]`-записей с
сокращением до 500 симв, diff, eviction-candidates — **в скрипте**. LLM
никогда не считает newest-wins-merge, не форматирует записи и не сравнивает
строки вручную.

#### 4.1 Подготовь JSON-вход

```json
{
  "today": "YYYY-MM-DD",
  "max_chars": 500,
  "memory_limit": 30,
  "memory_warn_threshold": 28,
  "stale_months": 24,
  "index_ignores": [{"source": "Invest Era", "subdomain": "oil-gas-ru"}],   // опционально, из INDEX
  "library": [
    {
      "subfolder": "geopolitics",
      "filename": "stratfor-2015-2025.md",
      "mtime": "2025-03-15",                       // опционально (fallback для newest)
      "frontmatter": {
        "source": "Stratfor",
        "audit_date": "2025-03-15",
        "last_updated": "2025-03-15",
        "period": "2015-2025",
        "trust": {"long-term-russia": "MEDIUM", "middle-east": "HIGH"},
        "pin": false,
        "audit_type": "Full",                      // optional, tie-breaker
        "theses_count": 12                         // optional, tie-breaker
      }
    }
  ],
  "current_memory": [
    {"id": 1, "text": "[lib] Stratfor: ..."},      // LIB
    {"id": 2, "text": "Личная заметка"}            // USER (по префиксу)
  ]
}
```

#### 4.2 Вызови скрипт

```bash
cat input.json | python3 scripts/sync_planner.py --pretty
# или: python3 scripts/sync_planner.py --input input.json --output plan.json
```

Скрипт возвращает:

- `aggregated_sources: []` — для каждого source: `trust` (newest-wins merge),
  `pin`, `last_audit_date`, `audit_count`, `subdomains_covered`,
  `include_in_memory`, `is_stale`, `memory_text` (готовая `[lib]`-строка),
  `format_used` (basic / grouped / high_ignore_only / truncated_names /
  top_avoid / top_avoid_top3 — отладочное поле).
- `operations: {add, replace, remove, skip}` — diff с текущим memory:
  - `add`: новые `[lib]`-записи (выполнять автоматически согласно §3 Принципов).
  - `replace`: `{id, old_text, new_text}` (требуют batch-confirmation).
  - `remove`: `{id, old_text}` (требуют batch-confirmation).
  - `skip`: число записей без изменений.
- `eviction: {needed, predicted_total, candidates: []}` — план Шага 8.
  Если `needed: true` — показать кандидатов пользователю. Кандидаты в
  порядке предпочтения: LOW/IGNORE-only без pin → stale без pin → малый
  audit_count без pin. `pin: true` НИКОГДА не предлагается.
- `skipped_files: []` — файлы без `source` или `trust` (с причиной).
- `warnings: []` — возможные дубликаты source (case variants),
  отсутствующие dating-поля (last_updated/period).

**Ручные агрегаты INDEX.** Если в `domains/{subfolder}/INDEX.md` есть таблица «Подтверждённые IGNORE»,
передать её строки в `index_ignores: [{"source": "<source как в frontmatter>", "subdomain": "<поддомен>"}]`.
Планировщик ставит IGNORE поверх newest-wins там, где тот даёт LOW/IGNORE (по умолчанию побеждает INDEX), и строит
запись обычным форматом. Предупреждения `index_override_contradicts_newest` (свежий аудит поднял поддомен до
MEDIUM/HIGH), `index_override_subdomain_missing` и `index_override_source_unresolved` показать пользователю:
INDEX надо править или имя источника уточнить. Frontmatter передавать дословно, включая `pin`; предупреждение
`pin_dropped` — пин исчез из записи, сверить `pin` в файлах источника до подтверждения replace.

LLM использует результат (основной путь, `mcp__memory`):
- **add**: создать `/lib_<slug>.md` (frontmatter + строка `memory_text`) и добавить строку в `/memory-notes.md`
  (создать индекс по образцу, если его нет). Выполнять автоматически.
- **replace**: показать было/стало (тело + ключевые поля frontmatter), после «да» — перезаписать файл и строку индекса.
  Операция с `renamed: true` — тот же источник под другим именем (`old_source_key` → `source_key`): файл и
  строка индекса переименовываются с сохранением смысловых деталей старой записи (bias, коэффициенты); как remove+add не выполнять.
- **remove**: показать, после «да» — убрать строку из `/memory-notes.md`; файл удалить, а если удаление запрещено —
  заменить тело на `[lib] {source}: (снято с синхронизации {date})` и сообщить.
- **Выравнивание копий:** для каждого источника из корня, у которого есть копии в `/projects/*/`, —
  показать список расхождений одним блоком, после «да» привести копии и строки их индексов к корню.
  Новых копий в проекты не создавать.
- Legacy (`memory_user_edits`): add / replace / remove через API, как раньше.
- **replace** / **remove** — batch-confirmation (формулировки в `references/confirmation-prompts.md`).
- **eviction**: если `needed`, показать кандидатов перед выполнением
  destructive-операций.
- **log**: использовать `summary`, `operations`, `skipped_files`,
  `warnings` для блока `_sync_log.md` (Шаг 9).

1. Прочитать лог (если есть): `Read("{LOCAL_LIBRARY_ROOT}/_sync_log.md")`
2. Добавить новый sync-блок в начало содержимого.
3. Перезаписать файл: `Write("{LOCAL_LIBRARY_ROOT}/_sync_log.md", content=...)`

**Формат блока лога:**
```markdown
## Sync {YYYY-MM-DD HH:MM} MSK

- Сканировано файлов: N
- Источников после агрегации: N
- Прошло auto-inclusion: N

Операции:
- add: «[lib] CFR: ...»
- replace #5: «[lib] Stratfor: ...»
- error при парсинге: ru-sellside/atom-2024.md (нет frontmatter)

Финальное состояние memory:
- USER_ENTRIES: N
- LIB_ENTRIES: N
- Свободно слотов: N
```

В чате — компактное summary: «Sync завершён: +N add, N replace, N remove. Лог обновлён.»

---

## Setup (первый запуск)

Если `Claude-Memory` не найдена через Synology:

1. Остановиться и сообщить пользователю — вероятно, недоступен Synology mount
   (создание библиотеки с нуля — осознанное решение пользователя, не скилла).
2. Если пользователь подтверждает создание структуры — создать папки через `Write`
   по layout из `references/claude-memory-layout.md` (shared ref). Конкретный
   список доменов в `domains/` определяется на момент создания — не
   фиксируется в коде скилла; смотри актуальный список в `claude-memory-layout.md`.
3. В каждый subfolder создать INDEX.md по шаблону из `references/index-templates.md`
4. После создания — sync ничего не добавит в memory (библиотека пуста)

---

## Anti-patterns

❌ **Писать `[lib]` только в проект.** Цель — корень `mcp__memory` (уровень профиля); копии в проектах лишь выравниваются.

❌ **Объяснять неудачу догадкой об окружении** («это облачный Claude Code» и т.п.). Нет инструмента памяти — так и сказать и выдать готовые строки.

❌ **Использовать bash для файловых операций.** При транспорте B — только Read/Write/Glob, не bash.

❌ **Трогать USER_ENTRIES.** Никогда.

❌ **Fabricate trust.** Если файл не парсится — пропустить.

❌ **Тихо удалять.** Каждый `remove` — с подтверждением.

❌ **Дублировать записи.** Один источник = одна запись в memory.

❌ **Запускать sync молча.** Даже scheduled task должен выдавать summary в чат.

---

## Scheduled task в Cowork

```
/schedule
Запускай memory-sync каждое воскресенье в 21:00 MSK.
В чате выдавай только short-form summary.
Если destructive операций больше 0 — НЕ выполняй автоматически, оставь pending для ручного подтверждения.
```

---

## Структура файлов скилла

- `SKILL.md` (этот файл) — оркестрация: чтение, парсинг, confirmation, лог.
- `scripts/sync_planner.py` — агрегация newest-wins, форматирование `[lib]`,
  diff, eviction. Без зависимостей. Тесты: `tests/test_sync_planner.py`.
- `references/aggregation-rules.md` — спецификация newest-wins merge (для
  людей; алгоритм реализован в скрипте).
- `references/format-templates.md` — спецификация 5-шагового сокращения (для
  людей; реализовано в скрипте).
- `references/confirmation-prompts.md` — формулировки prompts для destructive операций.
- `references/index-templates.md` — шаблоны INDEX.md для master + 5 subdomains.

**Правило:** LLM никогда не считает агрегацию вручную, не форматирует
`[lib]`-строки и не сравнивает их с текущим memory — всё через
`sync_planner.py`. LLM делает только I/O (Read через transport; чтение/запись `mcp__memory`,
legacy — view/add/replace/remove через memory API), confirmation flow и финальный лог.
