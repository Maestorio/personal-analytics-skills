# Skill: memory-sync

## Summary
Скрипт `sync_planner.py` корректен (60/60 тестов), newest-wins merge, eviction и формат `[lib]`-записи через 5-step shrink работают. Главные дефекты — на стыках: (1) формат `_sync_log.md` в реальной библиотеке расходится с шаблоном в SKILL.md (Шаг 9) — лог пишется ad-hoc; (2) маркер `⚠️ stale` отсутствует в реальных записях, хотя есть очень старые источники (Carnegie 2010–2016 не помечены); (3) контракт с save-to-library не предупреждает пользователя, что LOW-only источник без pin не попадёт в memory.

## Correctness (P1)
- [bug] Tie-breaker в `aggregate_newest_wins()` (`scripts/sync_planner.py:86–93`): если у двух файлов и `last_updated`, и `mtime` равны/`null`, sort недетерминирован.
  - **Статус: ГАЛЛЮЦИНАЦИЯ**. Код содержит 6-tuple ключ сортировки; финальный элемент — `inverse_name = tuple(-ord(c) for c in filename)` — алфавитный tie-breaker. Сортировка детерминирована даже при полностью совпадающих датах.

- [missing-feature] Шаг «truncate subdomains» (`format-templates.md` шаг 4) не покрыт тестами на длинные имена subdomain'ов (>30 chars).
  - **Статус: НЕ БАГИ, тест-coverage.** Функция `_truncate_subdomain_names(trust, max_len=20)` реализована и работает (усечение при 20 символах, не 30). Тест-пробел реален, но не критичен — не является ошибкой в коде.

- [bug] Маркер `⚠️ stale` (старее 24 мес без pin) — определён в `references/format-templates.md:107–113`, но **не проявляется** в реальных `_sync_log.md`-записях. Источники типа Carnegie 2010–2016 не отмечены.
  - **Статус: ГАЛЛЮЦИНАЦИЯ**. Код корректен: `is_stale()` вызывается (строка 497), передаётся в `format_memory_text()` (строка 500), `_suffix()` добавляет `⚠️ stale`. Carnegie не помечен, потому что он LOW trust без pin → **исключён из memory** (auto_inclusion = false). Для источников вне memory stale-маркер не нужен — это правильное поведение.

## Readability (P2)
- Дублирование описания между `references/aggregation-rules.md` (текстом) и `sync_planner.py:96–132` (кодом). Аналогично — `format-templates.md` vs `sync_planner.py:246–283`. Кандидат на консолидацию: оставить одну спецификацию (в коде) + короткий pointer из SKILL.md.
- `file_sort_key()` (sync_planner.py:81–93): кортеж непрозрачный, комментарий помогает, но логика «inverse_name для tie-break» неинтуитивна.
- В SKILL.md (Шаг 4–8) операции делегированы скрипту, но это не явно проговорено — читатель не понимает, что scripted-логика и текстовая спецификация — это одно и то же.
- Тесты не покрывают: невалидные даты в frontmatter, пустой `trust: {}`, очень длинные subdomain'ы, более 1000 файлов в одной агрегации.

## Cost (P3)
- Через Synology — нулевой расход. (MCP-fallback упразднён миграцией 2026-08-13.)
- Скрипт O(N log N) (sort), <100ms для реальных размеров (≤200 файлов).

## Speed (P4)
- Batch-confirmation для replace/remove (≥5 destructive ops) корректен; таймаут не документирован — пользователь может «зависнуть» в подтверждении.

## Cross-skill / contract
- [contract-gap] save-to-library пишет в `domains/<dom>/<source>-*.md` без warning'а: «Без HIGH или pin этот источник не попадёт в memory при следующем sync». Пользователь видит файл в библиотеке, но не понимает, что в memory не доедет.
  - **Статус: TODO → [MS-1]**.

- [contract-gap] Реальный формат `_sync_log.md`:
  ```
  ## Sync 2026-05-02 MSK
  - replaced: stratfor (HIGH, middle-east)
  ...
  ```
  vs шаблон SKILL.md (Шаг 9, ~234–250) — детерминированный YAML-стиль. Логи пишутся свободной формой; невозможен grep/aggregation.
  - **Статус: уже в TODO → [STL-4]**.

- D3 OK: memory-sync — единственный скилл, который пишет в `memory_user_edits` `[lib]`-записи. Файлы `domains/*` остаются неизменными (source of truth) ✓.
- Pin override: если пользователь edit'ит memory вручную, при следующем sync newest-wins файл перепишет — это спецификация, но в SKILL.md не проговорено явно.

## Verified against artifact
- `~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/_sync_log.md` (хвост ~430 строк):
  - Newest-wins merge: запись 2026-04-28 «Stratfor middle-east HIGH→MEDIUM» — соответствует логике ✓
  - Auto-inclusion: запись 2026-04-28 «Carnegie excluded (no HIGH, pin=false)» ✓
  - Pin notation `(pinned)` присутствует у ВТБ-записи ✓
  - **Stale-маркер `⚠️ stale` отсутствует** — корректно: Carnegie excluded from memory, поэтому stale-маркер не нужен
  - Формат лога — ad-hoc, не строгий YAML/list ✗ (трекается в STL-4)
- `domains/`: 5 субдоменов (geopolitics, ru-sellside, ru-macro, global-banks, commodity-agencies), tech-ceo пуст. Все читаются скриптом ✓.

## 2026-10-02 — смена цели записи: `memory_user_edits` → `mcp__memory` (уровень профиля)

- **Инцидент.** При пересмотре профиля Invest Era в сессиях Desktop (Chat и Cowork) не оказалось `memory_user_edits`, был только `mcp__memory` (файловая память). `[lib]`-записи нашлись лишь в проектах (`projects/<id>/lib_*.md` + `memory-notes.md`), на уровне профиля (корень) их не было. Две копии Invest Era расходились: N=6 и N=3. Скилл дважды остановился и объяснял неудачу «облачным Claude Code».
- **Ручная развязка 2026-10-02.** Созданы `/lib_invest_era.md` и `/memory-notes.md` в корне, копии в проектах выровнены по корню (одинаковый хеш), в `_sync_log.md` есть отметка.
- **Правка SKILL.md.** Основная цель — корень `mcp__memory` (уровень профиля); копии в `projects/*` выравниваются по корню и новыми не плодятся. `memory_user_edits` — legacy-фолбэк. Если нет ни того, ни другого, скилл выдаёт готовые строки и останавливается, не гадая про окружение. При расхождении newest-wins с ручным агрегатом INDEX показывает оба варианта, по умолчанию берёт INDEX.
- **Открыто.** Перенести остальные `[lib]` (БКС, Stratfor, ЦБ и др.) из проектов в корень (первым запуском обновлённого скилла). `sync_planner.py` не знает ручных правил INDEX («IGNORE+anything», «LOW×N → IGNORE») — кандидат на формализацию в скрипте с тестами.

## 2026-10-27 — запуск из сессии, привязанной к проекту; ложные remove+add

- **Инцидент.** Запуск `/memory-sync` в чате внутри проекта: корень `mcp__memory` не пишется, в корне только `lib_invest_era.md`. Агент предложил писать в копии проекта (запрещено Anti-patterns). Планировщик выдал remove+add для переименованных ключей: «SberCIB» ↔ «SberCIB Investment Research», «OPEC MOMR + WOO» ↔ `opec-momr`; замена грозила потерей bias и коэффициентов OPEC.
- **Правки.** SKILL.md, шаг 0: гард корня памяти — не пишется → остановиться и попросить запуск вне проекта. `sync_planner.py`: `_pair_renames` сводит однозначную пару remove+add с токен-префиксным совпадением ключей в replace с `renamed: true`; неоднозначные (несколько World Bank) не склеивает. Тест `test_compute_diff_renames` (67 проверок).
- **Закрыто позже.** Пин ЦБ: в библиотеке один файл `cbr-rf-2024-2025.md` с `pin: true`, «pin: no» был ошибкой при ручной сборке входного JSON (дословную передачу frontmatter теперь требует SKILL.md); планировщик предупреждает `pin_dropped`. Таблица «Подтверждённые IGNORE» передаётся как `index_ignores` и применяется скриптом (только ru-sellside/INDEX.md содержит такую таблицу); правила «LOW×N → IGNORE» в скрипт не вшиты — INDEX остаётся единственным местом решения, скрипт только исполняет.
- **Открыто.** Сам синк не применён; перенос остальных `[lib]` в корень — первым запуском вне проекта.
