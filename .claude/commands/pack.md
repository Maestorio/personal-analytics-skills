Упаковщик скиллов из `skills/` в `outputs/*.skill`. Работает **только** в репозитории `claude_skills` (проверь `pwd`: должен заканчиваться на `/claude_skills`).

## Что нужно сделать перед упаковкой

1. **Определить целевые скиллы** (в порядке приоритета):
   - Если пользователь передал имена скиллов в `$ARGUMENTS` — использовать их.
   - Если просил «изменённые / поправленные / новые» или ничего не указал — `./pack.sh --check` (список скиллов, чьи файлы или подключённый канон из `_shared-references/` новее пакета в `outputs/`, с первым изменившимся файлом), показать список и упаковать `./pack.sh` без имён — он пакует ровно этот список.
   - Упаковывать, когда правки серии завершены: пакет, собранный посреди правок, придётся пересобирать.

2. **Sanity-check перед запуском:**
   - Каждое имя должно соответствовать существующей папке `skills/<имя>/`. Если нет — предупредить и не запускать.
   - Если в SKILL.md скилла есть `shared_refs:` во frontmatter, но `_shared-references/` в корне отсутствует — предупредить (без канона нечего инжектить, скилл получит пустой references/).
   - Если в `skills/<имя>/references/<ref_name>.md` лежит локальная копия — упомянуть, что она override'ит канон при упаковке (это нормально, если действительно нужны правки).

3. **Запуск:**
   ```bash
   ./pack.sh <скилл1> <скилл2> ...
   ```
   Скрипт делает временную копию скилла, для каждого имени из `shared_refs:` проверяет: если в скилле уже есть `references/<name>.md` — оставляет (local override); если нет — копирует канон из `_shared-references/<name>.md`. Зипает temp в `outputs/<имя>.skill`, чистит. **Репо после запуска не меняется.** Внутри `.skill` всегда лежит самодостаточная `references/` со всеми shared-файлами.

4. **После выполнения:**
   - Вывести список созданных `.skill`-файлов с размерами (`ls -lh outputs/*.skill`).
   - Если были warnings про missing shared-refs — упомянуть пользователю, в каком скилле и какие отсутствуют.

## Список скиллов в репо

forecast-collector, forecast-confidence-applier, forecast-monitor, hypothesis-stress-tester, macro-forecast-chain, macro-ru-watcher, memory-sync, portfolio-data-loader, portfolio-scenario-stress, retrospective-forecast-audit, revise-memory-local, revise-memory-remote, ru-portfolio-advisor, save-to-library, scenario-builder

(плюс будущий `portfolio-integrated-view` — см. `INTEGRATION-DOCS/`)

## Аргументы пользователя

`$ARGUMENTS`
