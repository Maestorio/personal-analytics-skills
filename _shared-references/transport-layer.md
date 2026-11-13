# Transport Layer — Claude-Memory Access

Единственный транспорт доступа к `Claude-Memory` — **Synology mount** (Mac-зеркало
Synology Drive). Дерево живёт на NAS (`/volume1/homes/hubuser/Claude-Memory`),
вне каких-либо облачных синков; Mac-зеркало — его локальная проекция.

> Миграция 2026-08-13: раньше дерево жило в `Ext_gDrive/Claude-Memory` и
> синкалось в Google Drive; Google Drive как транспорт и как хранилище
> рабочих данных упразднён. Планируемый MCP-сервер на Synology станет вторым
> транспортом к тому же корню (когда появится).

---

## Transport: Synology

**Инструменты:** `Read`, `Write`, `Edit`, `Glob`, `request_cowork_directory`

**Пути:**
```
MEMORY_ROOT            = ~/Library/CloudStorage/SynologyDrive-home/Claude-Memory
DOMAINS_DIR            = {MEMORY_ROOT}/domains
FORECASTS_DIR          = {MEMORY_ROOT}/forecasts
SCENARIOS_DIR          = {MEMORY_ROOT}/scenarios
FORECAST_COLLECTIONS   = {MEMORY_ROOT}/forecast-collections
MACRO_SNAPSHOTS_DIR    = {MEMORY_ROOT}/macro-snapshots
MACRO_CHAIN_DIR        = {MEMORY_ROOT}/macro-chain
REPORTS_DIR            = {MEMORY_ROOT}/reports
PORTFOLIO_DIR          = {MEMORY_ROOT}/Portfolio
PORTFOLIO_SNAPSHOTS    = {PORTFOLIO_DIR}/snapshots
PORTFOLIO_STRESS       = {PORTFOLIO_DIR}/stress
PORTFOLIO_FORECASTS    = {PORTFOLIO_DIR}/forecasts
PORTFOLIO_WEEKLY_REV   = {PORTFOLIO_DIR}/weekly-reviews
PORTFOLIO_INTEGRATED   = {PORTFOLIO_DIR}/integrated-views
PORTFOLIO_DECISIONS    = {PORTFOLIO_DIR}/decisions            # пишет только decision_write.py
SHARED_DIR             = {MEMORY_ROOT}/_shared
ZENMONEY_DIR           = {MEMORY_ROOT}/ZenMoney
```

**Bash-пути не использовать.** Только `Read` / `Write` / `Edit` / `Glob`.

### Запись скриптом скилла — носители решений, условий, справочника бумаг

Три носителя модель не читает и не пишет инструментами — их пишет **скрипт скилла сам** на mount (проверено
31.10 в Cowork): `Portfolio/decisions/*.json` — `decision_write.py`, `Portfolio/conditions.yaml` — `apply_condition.py`,
`Portfolio/security-attrs.json` — `security_attrs.py` (все в `save-to-library`; выборки для модели — их команды
`digest`/`get`/`list` и `security_digest.py`). Правила записи:

- корень — **всегда аргументом** `--root {root}`; в Cowork `{root}` = `$HOME/mnt/Claude-Memory` (путь узнаётся через
  `request_cowork_directory`, в команде не угадывается); на Маке — `MEMORY_ROOT`;
- запись — валидатор схемы (`ds_schemas.py`) → временный файл → `os.replace`; невалидный вход — ошибка до записи;
- скрипт, чей вход — вывод модели, перед записью зовёт `hub_settings.require_ai(путь, имя, действие)`
  (общий модуль `hub_settings.py`; режим читается по сети `HUB_URL`/`HUB_AUTH` → файл зеркала
  `_hub/settings.json` → `on`): при `ai_mode: off` он печатает причину в stderr и выходит кодом 3, ничего не записав;
  скрипты с владельческим входом (команды владельца, импорты из файлов владельца) не гейтятся;
- при доступном сайте (`HUB_URL`/`HUB_AUTH`) `require_ai` ещё и сверяет зеркало с NAS (`hub_settings.mirror_lag`: файлы,
  изменённые на NAS за 6 часов, против копии Mac) — отстаёт → код 4 и отказ, чтобы не писать поверх устаревшей копии;
- **отказ кодом 3 или 4 скилл не обходит**: не повторяет команду сам, не ищет обходных путей, а передаёт владельцу
  текст отказа и одно действие — код 3: включить режим «с ИИ» кнопкой «Режим» на хабе; код 4: дождаться у клиента
  Synology Drive «Up to date»; после слова владельца «повтори» выполняет ту же команду снова;
- скрипты скиллов **не удаляют**: снятие условия = `withdrawn`, правка = новая версия, решение — новый файл;
- `conditions-state.json`, `plan.json`, `plan-journal.jsonl`, снапшоты и журнал решений пишет только сайт (hub-api,
  сборка) — скрипт скилла их только читает.

### Рабочий корень (`SCOPE_ROOT`) — не `MEMORY_ROOT`

Проверять доступность и запрашивать доступ надо **к своей подпапке дерева**, а не
к корню библиотеки. `request_cowork_directory(MEMORY_ROOT)` отдаёт скиллу всё
дерево, а `Glob("*", path=MEMORY_ROOT)` вываливает листинг всех папок — лишний
доступ и лишний контекст. Кейс 2026-08-14: `health-meds`, которому нужны два файла
в `Health/`, запросил корень целиком и вывалил листинг всего дерева.

| Скилл | `SCOPE_ROOT` |
|---|---|
| `health-meds` · `health-labs` | `{MEMORY_ROOT}/Health` |
| `game-advisor` | `{MEMORY_ROOT}/Gaming` |
| `zenmoney-analyst` | `{ZENMONEY_DIR}` (только чтение карты) |
| `portfolio-data-loader` | `{PORTFOLIO_SNAPSHOTS}` |
| `macro-ru-watcher` | `{MACRO_SNAPSHOTS_DIR}` |
| `forecast-collector` | `{FORECAST_COLLECTIONS}` |
| `save-to-library` · `revise-memory-remote` · `revise-memory-local` · `memory-sync` | `MEMORY_ROOT` — этим всё дерево нужно по роли |
| остальные | подпапки, перечисленные в собственном `SKILL.md` |

Скиллу нужно несколько подпапок (например, `{PORTFOLIO_DIR}` + `{DOMAINS_DIR}` +
`{SCENARIOS_DIR}`) — запросить **каждую перечисленную в его `SKILL.md`**, а не
общий корень. `MEMORY_ROOT` целиком запрашивают только те, кто по роли ходит по
всему дереву (последняя строка таблицы), и скиллы, которым нужны почти все
верхнеуровневые папки, — но это решение, а не умолчание.

**Проверка доступности (первый шаг в сессии):**
1. `Glob("*", path=SCOPE_ROOT)` — если пусто или ошибка →
   `request_cowork_directory(path=SCOPE_ROOT)` (в Cowork-сессиях доступ
   выдаётся заново каждую сессию) и повторить.
2. Если Synology недоступен и после повтора — **остановиться и сообщить
   пользователю**. Никуда не писать: альтернативного транспорта нет.
3. Проба на незагруженное содержимое — см. следующий раздел.

### Файл виден, но не читается — режим «по требованию»

Synology Drive держит файл в одном из трёх состояний: **загружен** (данные на
диске), **загружен временно** (скачан по обращению, позже вытесняется) и
**заглушка** (в дереве виден, содержимого на диске нет). `Glob` показывает все
три одинаково — по листингу заглушка неотличима от загруженного файла.

Что будет при чтении заглушки, зависит от среды исполнения:

| Среда | Поведение | Цена |
|---|---|---|
| Полный доступ к File Provider | читается, файл докачивается прозрачно | 0,6–2 с на файл |
| Доступа к провайдеру нет (наблюдалось в Cowork) | **чтение падает**, файл остаётся нечитаемым | работа невозможна |

**Условие, которое нельзя путать с «файла нет»:** `Glob` файл показал, а `Read`
по нему вернул ошибку. Это не отсутствие файла и не потеря доступа к дереву —
это незагруженное содержимое, и сообщать о нём надо именно так.

**Проба.** После успешного `Glob` прочитать **один самый мелкий файл из нужных
по задаче**. Пробовать все не надо — полная проба стоит столько же, сколько сама
работа.

- проба прошла → работать; остальные заглушки обойдутся задержкой, не отказом;
- проба упала → **остановиться до начала работы**, ничего не записав, и спросить
  пользователя.

**Форма вопроса** — список нужных файлов, дословный текст ошибки и варианты:

> Нужны файлы: `<список>`. Первый же (`<файл>`) не читается: `<текст ошибки>`.
> Похоже, содержимое не загружено на устройство (режим «по требованию» Synology
> Drive) — скачать его отсюда я не могу, это делается на самом устройстве.
> · Я загрузил — проверь ещё раз · Работаем без них · Стоп

Ошибку приводить дословно: она называет причину (`EPERM` — нет прав,
`EIO`/таймаут — провайдер недоступен, `ENOENT` — файла действительно нет).

**Вариант «работаем без них» предлагать не всем.** Там, где неполный вход даёт
правдоподобный, но ложный результат, оставить только «загрузил» и «стоп»:
`portfolio-data-loader`, `save-to-library`, `memory-sync`, `revise-memory-remote`,
`portfolio-integrated-view`. Валидатор библиотеки на половине файлов отрапортует
«всё чисто», а сводный вид не заметит, что половины артефактов не было.

**Если файлов много, а среда читать умеет** — слать несколько `Read` **одним
сообщением**, а не по очереди: параллельная докачка измерена в 2,6 раза дешевле
на файл (0,22 с против 0,57 с).

---

## Типовые операции

| Операция | Как |
|---|---|
| Читать INDEX.md | `Read("{MEMORY_ROOT}/INDEX.md")` |
| Список файлов в папке | `Glob("*.md", path="{MEMORY_ROOT}/{subfolder}/")` |
| Читать файл | `Read("{MEMORY_ROOT}/{subfolder}/{file}.md")` |
| Записать файл | `Write("{MEMORY_ROOT}/{subfolder}/{file}.md", content=...)` |
| Обновить файл | `Edit(...)` или `Write(...)` |
| Записать парный YAML | `Write("{MEMORY_ROOT}/{subfolder}/{base}.yaml", content=...)` |

---

## Конкретные примеры путей (для скиллов)

### portfolio-data-loader

Файл именуется `portfolio-{YYYY-MM-DD}.json` — дата запуска скилла.

```python
# Сохранить снапшот портфеля
snapshot_path = f"{PORTFOLIO_SNAPSHOTS}/portfolio-{today}.json"
Write(snapshot_path, content=json_data)

# Читать два последних для diff
files = sorted(Glob("portfolio-*.json", path=PORTFOLIO_SNAPSHOTS))
prev = Read(f"{PORTFOLIO_SNAPSHOTS}/{files[-2]}")
curr = Read(f"{PORTFOLIO_SNAPSHOTS}/{files[-1]}")
```

### macro-ru-watcher

Файл именуется `ru-{YYYY-MM-DD}.md` — дата запуска скилла.

```python
# Сохранить снапшот
snapshot_path = f"{MACRO_SNAPSHOTS_DIR}/ru-{today}.md"
Write(snapshot_path, content=markdown_data)

# Читать последний
files = sorted(Glob("ru-*.md", path=MACRO_SNAPSHOTS_DIR))
latest = Read(f"{MACRO_SNAPSHOTS_DIR}/{files[-1]}")
```

### ru-portfolio-advisor
```python
# Читать последний снапшот
files = sorted(Glob("portfolio-*.json", path=PORTFOLIO_SNAPSHOTS))
data = Read(f"{PORTFOLIO_SNAPSHOTS}/{files[-1]}")

# Опционально читать stress-файлы для mode 8
stress_files = Glob("*.yaml", path=PORTFOLIO_STRESS)
```

### macro-forecast-chain

```python
# Сохранить выход (macro-input YAML)
output_path = f"{MACRO_CHAIN_DIR}/macro-input-{today}.yaml"
Write(output_path, content=yaml_data)
```

**sector-overrides.yaml:**

| Операция | Как |
|---|---|
| Читать | `Read("{MEMORY_ROOT}/sector-overrides.yaml")` — не блокировать если нет |
| Обновить | `Read` → merge → `Write("{MEMORY_ROOT}/sector-overrides.yaml", ...)` |

При обновлении: читать существующий файл → merge → записать. Никогда не перезаписывать без merge.

### portfolio-scenario-stress

Файлы именуются `stress-{YYYY-MM-DD}-{slug}.{md,yaml}`. Каждый stress-тест — пара `.md` + `.yaml` с одинаковым базовым именем.

**Slug:** kebab-case, ISO 9 транслит, ≤20 символов. Примеры: `oilcrash`, `rate-cut-200bp`, `sanctions-wave`, `stagflation`.

```python
# Читать снапшот портфеля
files = sorted(Glob("portfolio-*.json", path=PORTFOLIO_SNAPSHOTS))
data = Read(f"{PORTFOLIO_SNAPSHOTS}/{files[-1]}")

# Сохранить stress-тест (пара файлов)
base = f"stress-{today}-{slug}"
Write(f"{PORTFOLIO_STRESS}/{base}.md", content=markdown_data)
Write(f"{PORTFOLIO_STRESS}/{base}.yaml", content=yaml_data)

# Найти все stress-тесты
stress_files = Glob("stress-*.yaml", path=PORTFOLIO_STRESS)
```

### forecast-collector

Файл именуется `fc-{source}-collection-{YYYY-MM-DD}.md`.

```python
collection_path = f"{FORECAST_COLLECTIONS}/fc-{source}-collection-{today}.md"
Write(collection_path, content=markdown_data)
```

### save-to-library
```python
# Маршрутизация по типу артефакта:
# Аудит             → REPORTS_DIR (полный отчёт) + DOMAINS_DIR (trust-профиль)
# Прогноз           → FORECASTS_DIR (+ парный .yaml)
# Сценарий          → SCENARIOS_DIR (+ парный .yaml)
# Недельный обзор   → PORTFOLIO_WEEKLY_REV
# Stress-анализ     → PORTFOLIO_STRESS (+ парный .yaml)
# Macro-input       → MACRO_CHAIN_DIR
# Macro-снапшот     → MACRO_SNAPSHOTS_DIR
```
