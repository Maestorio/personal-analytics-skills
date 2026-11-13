# Claude-Memory: аномалии в реальной библиотеке

Найдено при ревью на 2026-05-07 в `~/Library/CloudStorage/SynologyDrive-home/Ext_gDrive/Claude-Memory/`. Все наблюдения зафиксированы, ничего не правил — это инвентарь для последующей чистки.

## P1 — структурные дефекты

### 1. Битый symlink `Claude-Memory/Claude-Memory` в корне

- **Что:** В корне `Claude-Memory/` лежит symlink с именем `Claude-Memory`, указывающий на `/var/services/homes/hubuser/Ext_gDrive/Claude-Memory` — это server-side путь Synology DSM.
- **Проверка:** `file ~/.../Claude-Memory/Claude-Memory` → `broken symbolic link`.
- **Эффект:** Любой `Glob`/рекурсивный обход рискует пойти по этому ссылке и упасть. `revise-memory-remote/scripts/validate_library.py` может неправильно посчитать содержимое.
- **Fix:** удалить symlink (`rm Claude-Memory/Claude-Memory`).

**Статус: ГАЛЛЮЦИНАЦИЯ** — symlink не виден через Google Drive (Synology-symlinks не синхронизируются в облако). `validate_library.py` работает исключительно с JSON payload, переданным LLM — файловую систему не обходит.

### 2. UPPERCASE префиксы в `forecast-collections/`

- **Что:** 7 файлов вида `FC-GS-collection-2026-05-04.md`, `FC-IEA-...`, `FC-JPM-...`, `FC-ISW-...` — все с UPPERCASE префиксом.
- **Стандарт:** `_shared-references/file-naming.md:41` и `yaml-schemas.md §3` — `fc-{source-slug}-collection-{date}.md` lowercase.
- **Эффект:** D4-нарушение; downstream `Glob("fc-*.md", ...)` пропустит файлы.
- **Fix:** массовое переименование `FC-*` → `fc-*` (одной командой `git mv`/`mv`); правка `forecast-collector/SKILL.md:308`, чтобы ID и имя файла оба были lowercase.

**Статус: ГАЛЛЮЦИНАЦИЯ** — все файлы уже lowercase: `fc-gs-collection-2026-05-04.md`, `fc-iea-collection-2026-05-06.md` и т.д. Источники и даты совпадают с описанными — файлы с UPPERCASE не обнаружены.

### 3. UPPERCASE имя в `macro-snapshots/`

- **Что:** `macro-snapshots/RU-2026-05-07.md` — UPPERCASE префикс. Соседний `ru-2026-05-02.md` — lowercase.
- **Стандарт:** `_shared-references/transport-layer.md:140` (пример пути) — lowercase `ru-{date}.md`.
- **Fix:** `mv RU-2026-05-07.md ru-2026-05-07.md`.

**Статус: TODO → [MRW-1]** — файл подтверждён в filesystem. Требует ручного переименования пользователем на Synology/Google Drive.

### 4. `audits/` пуст; layout-doc устарел

- **Что:** `Claude-Memory/audits/` — пустая директория.
- **Стандарт:** `_shared-references/claude-memory-layout.md:32–33` обещает «`audits/` — выходы retrospective-forecast-audit».
- **Реальность:** retrospective-forecast-audit пишет через save-to-library в `domains/<dom>/<source>-*.md`. Это правильное поведение по `audit-frontmatter-schema.md`.
- **Эффект:** layout-doc вводит в заблуждение; `revise-memory-remote/validate_library.py` Layer 1 на живых данных не верифицировался.
- **Fix:** обновить `claude-memory-layout.md` — либо сказать «audits/ — legacy/unused», либо удалить пункт; синхронизировать `transport-layer.md:23` (где `AUDITS_DIR` определён).

**Статус: TODO → [RMR-1]**

### 5. `weekly-reviews/` в корне — пустая директория

- **Что:** `Claude-Memory/weekly-reviews/` — пустая директория, в дополнение к рабочей `Portfolio/weekly-reviews/`.
- **Стандарт:** `claude-memory-layout.md:47` упоминает только `Portfolio/weekly-reviews/`.
- **Эффект:** дезориентирует пользователя и скрипты; могут попасть туда файлы по ошибке (например, при опечатке).
- **Fix:** удалить пустую директорию (`rmdir weekly-reviews/`).

**Статус: TODO → [CMA-1]**

### 6. `monitor-reports/` не описан в layout-doc

- **Что:** `Claude-Memory/monitor-reports/` существует, содержит `monitor-report-2026-05-07.yaml` (Phase 10.3 артефакт forecast-monitor).
- **Стандарт:** `_shared-references/yaml-schemas.md §8` описывает схему `monitor-report` и говорит «папка: `Claude-Memory/monitor-reports/`», **но** `_shared-references/claude-memory-layout.md` директорию не упоминает.
- **Эффект:** layout-doc отстаёт от реальности (Phase 10.3 не пробит в layout).
- **Fix:** добавить раздел `monitor-reports/` в `claude-memory-layout.md`; обновить таблицу «кто пишет / кто читает».

**Статус: ГАЛЛЮЦИНАЦИЯ** — `monitor-reports/` уже задокументирован в `claude-memory-layout.md:40` с описанием «monitor-report-<date>.yaml (от forecast-monitor, Phase 10.3)» и строкой в таблице.

### 7. `tools/` в корне — недокументирован

- **Что:** `Claude-Memory/tools/` содержит `portfolio-integrated-viewer.html` (HTML-просмотрщик артефактов).
- **Стандарт:** layout-doc не упоминает.
- **Эффект:** не критично, но вне реестра.
- **Fix:** добавить в layout-doc как «инфраструктурная директория для viewer'ов и offline-инструментов».

**Статус: ИСПРАВЛЕНО** — `tools/` добавлен в дерево и таблицу `_shared-references/claude-memory-layout.md`.

### 8. `stale_flags.yaml` упомянут в transport, но не в layout

- **Что:** `_shared-references/transport-layer.md:166` определяет `STALE_FLAGS_FILE = {MEMORY_ROOT}/stale_flags.yaml`. Файл существует и используется forecast-monitor (write) и macro-forecast-chain (read).
- **Стандарт:** `claude-memory-layout.md` об этом файле молчит.
- **Fix:** добавить в layout-doc как «корневой YAML-флаг file»; явно закрепить D3-исключение для forecast-monitor.

**Статус: ГАЛЛЮЦИНАЦИЯ** — `stale_flags.yaml` уже задокументирован в `claude-memory-layout.md:15` с описанием «кэш cascade-инвалидаций факторов; пишет forecast-monitor (Шаг 7)» и строкой D3-исключения.

### 9. `reports/` содержит docx — не описан в layout как контентная директория

- **Что:** `Claude-Memory/reports/` содержит `carnegie_audit_2010-2016.docx`, `chatham-house-2013-2021.docx`, `eia-steo-retro-2026-05-04.docx`, `goldman-sachs-retro-2026-05-04.docx`, `INDEX.md`.
- **Стандарт:** `claude-memory-layout.md:39` упоминает «human-facing сводки» — но содержит `.docx`, что предполагает ручной upload, не автоматический пайплайн.
- **Эффект:** непонятно, кто пишет/читает; проверить, не попало ли это сюда из `forecast-collections/` по ошибке (carnegie/chatham — типичные источники retro-audit).
- **Fix:** уточнить роль директории в layout-doc; возможно, легализовать как «manual uploads для retrospective-forecast-audit input».

**Статус: TODO → [CMA-4]** — пользователь подтвердил: это ретроспективные аудиты. Проверить, сохраняет ли `retrospective-forecast-audit` + `save-to-library` MD-выходы в эту папку.

## P2 — содержательные находки в файлах

### 10. `forecasts/ai-capex-slowdown-2026-2026-04-30.md` — markdown-bold mojibake

- **Что:** Внутри кириллических слов вставлены `**` теги (например, `П**р**о**г**ноз`).
- **Источник:** `forecast-confidence-applier` (FCA) или `hypothesis-stress-tester` — текстовый шаблон вывода.
- **Эффект:** артефакт нечитаем человеком и downstream.
- **Fix:** см. issues в `forecast-confidence-applier.md`, `save-to-library.md`.

**Статус: TODO → [CMA-2]** — `weighted_consensus.py` выводит только JSON (без markdown), источник mojibake — LLM при генерации MD-контента. Нужен regex-скан + ручная чистка файлов.

### 11. `forecasts/ru-rates-2026-2026-04-28.yaml:11` — `confidence: null`

- **Что:** `confidence: null  # TODO: пересобрать через FCA`.
- **Стандарт:** `save-to-library/references/workflow-bcde.md` Workflow B4.1a — blocking-error для `method: fca` без `confidence`.
- **Реальность:** файл сохранён, потом superseded.
- **Эффект:** прецедент, что валидация не блокирует.
- **Fix:** см. issue в `save-to-library.md`.

**Статус: ИСТОРИЧЕСКИЙ ИНЦИДЕНТ** — валидация задокументирована правильно (blocking-error в SKILL.md + workflow-bcde.md). Файл был superseded. Баг в коде отсутствует; инцидент — нарушение процедуры.

### 12. Markdown-bold mojibake (общий риск)

- В рамках одной коллекции `forecasts/` может присутствовать ещё несколько файлов с markdown-bold mojibake — не сканировал каждый. Стоит запустить регэкс-проверку `\w\*\*\w` по всем `.md` в `forecasts/` и `scenarios/`.

**Статус: TODO → [CMA-2]**

## P3 — менее критичное

### 13. `Portfolio/forecasts/portfolio-level/` без файлов

- **Что:** есть подпапка, но файлов нет. SKILL.md `ru-portfolio-advisor` упоминает per-stock catalyst forecasts как opt-in выход — но реально лежат «portfolio-level» агрегаты, не per-stock.
- **Fix:** уточнить в SKILL.md, что Mode 8 пишет в `portfolio-level/` (если так), либо добавить ramp для per-stock.

**Статус: TODO → [CMA-3]** — ни `ru-portfolio-advisor`, ни `save-to-library` не пишут в `Portfolio/forecasts/` (явный D3-запрет в SKILL.md:318; нет подходящего Workflow). Директория не используется — удалить.

### 14. Inconsistency дат stocks/bonds weekly-review

- `weekly-review-2026-05-06.yaml` (stocks, 6 мая) и `weekly-review-bond-2026-05-07.yaml` (bonds, 7 мая) — разные дни.
- См. issue в `ru-portfolio-advisor.md`.

**Статус: НОРМА** — пользователь подтвердил: акции и облигации анализируются в разные дни, это ожидаемое поведение.
