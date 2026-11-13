# Workflow L — Monitor-report (Phase 10.3)

> Вынесено из SKILL.md дословно при дроблении 2026-08-12 (этап 3, подготовка Max → Pro).

## Workflow L — Monitor-report (Phase 10.3)

Триггер: пользователь сохраняет artefact `monitor-report-{date}.yaml` от `forecast-monitor` Шаг 7 (черновик `_drafts/` — L1.0).

**L1.0. Черновик в `_drafts/` (первый по приоритету):** `Glob("_drafts/monitor-report-*.yaml")`; самый поздний черновик, дата которого позже даты последнего отчёта в `monitor-reports/` (или папка пуста), — источник YAML, чат — только для уточнений владельца. Дата та же, что у сохранённого `monitor-report-{date}.yaml`, — спросить владельца (L4). Черновика нет (mount был недоступен, «черновик не записан») — блок `monitor-report-*.yaml` из чата. Приёмка — командой `python3 scripts/promote_draft.py --root {LOCAL_LIBRARY_ROOT} --draft <имя> --kind monitor-report --dry-run` → показать владельцу, что будет записано и заменено → по «да» та же команда без `--dry-run`: скрипт проверяет кодировку (L2) и схему с покрытием monitoring (L3, `--root`), пишет отчёт, пункт в «## Активные мониторинговые отчёты» корневого `INDEX.md`, дописывает INDEX и `_sync_log.md` и удаляет черновик (код 1 — блокер, ничего не записано, `issues` — владельцу). Текст черновика модель не переписывает; за ней — решение по дате-дублю (L4: `--as …-v2`, `--force`), применение `outcome_log_updates` (L5.5) и перенос старых отчётов в архив (L6), ответы на вопросы валидатора и правка текста по замечаниям (Edit черновика, приёмка заново).

**L1. Идентификация:** YAML с `schema_version: 1`, `type: monitor-report`, `producer: forecast-monitor`. Имя `monitor-report-{YYYY-MM-DD}.yaml` (lowercase D4).

**L2. Encoding-check:** проверить отсутствие mojibake (как в E2).

**L3. Schema validation:**
- Обязательные top-level: `schema_version`, `type`, `generated_at`, `producer`, `alerts`, `freshness_audit`.
- `alerts[*]` — массив с обязательными полями: `severity`, `category`, `target`, `message`, `detected_at`.
- `severity ∈ {HIGH, MEDIUM, LOW, INFO}`, `category ∈ {stale, horizon_passed, event_window, factor_breach, source_dead, prediction_due, catalyst_missed}`.
- `freshness_audit` — объект с любым подмножеством ключей `{integrated_view, stress, weekly_review, macro_snapshot, trust_matrix}`.
- `condition_findings` (опционально, forecast-monitor Шаг 1c) — список находок по условиям `{condition_id, version, doc, found_at, note}`: `version` — целое ≥ 1; `found_at` — ISO-дата или null; при `found_at` обязателен `doc` (ссылка) и наоборот; чужие поля — blocking. Прежнее поле `condition_events` — blocking. В состояние условий находку переносит задача hub-notify (`event_found` + `fired`), не save-to-library.
- `outcome_log_updates` (опционально, §14.3) — список резолв-обновлений исходов; если присутствует, каждый элемент имеет `target_file`, `resolve_date`, `kind`, и факт (`actual` или `resolved`) + `actual_source`. Применяется в L5.5 к `forecasts/`.

- `monitoring_checked` (опционально) — пункты `monitoring[]` с прошедшей датой без алерта
  `{target, target_file, monitoring_id, check_date, result, note?}`, `result` — кодлист `monitoring_result`.
- **Скриптом (blocking):** `python3 scripts/assemble_artifact.py validate-monitor-report --file report.yaml --root <корень Claude-Memory>`
  (или JSON в stdin с тем же `--root`). Проверяет поля выше и сверх них: каждый пункт `monitoring[]` активных
  прогнозов и сценариев с `check_date` не позже `generated_at` отражён алертом с `monitoring_id` или строкой
  `monitoring_checked` (без `--root` проверка не выполняется — warning); у HIGH/MEDIUM `suggested_action` — готовая команда
  `/скилл …`; в `alerts[]` нет записей про условия (`target: condition …` — им место в
  `condition_findings`). `blocking_count > 0` → не сохранять, показать список и попросить
  forecast-monitor поправить фразы (кейс 2026-10-26: три действия без скилла, одно — про условие).

**L4. Дедупликация:**
- Если `monitor-report-{date}.yaml` за эту дату уже есть → спросить: перезаписать (опция, если новый отчёт более свежий) или сохранить с суффиксом `-v2`?

**L5. Сохранение:**
- Путь: `Claude-Memory/monitor-reports/monitor-report-{YYYY-MM-DD}.yaml` (создать папку если её нет).
- Сохранить через transport-layer.

**L5.5. Применение `outcome_log_updates` к `forecasts/` (§14.3 — резолв исходов).**

Если monitor-report содержит `outcome_log_updates: [...]` — форекаст-монитор захватил факт на
резолве (он сам в `forecasts/` не пишет — D3 + read-only-контракт; физическую запись делает
**здесь**, save-to-library — единственный писатель библиотеки). Для каждого update:

1. Прочитать целевой файл `update.target_file` (`forecasts/{basename}.yaml`).
2. Найти в его `outcome_log` запись по (`resolve_date`, `kind`). **Если записи нет** (резолв
   не был засеян) — собрать её из `fca_stats` этого горизонта через `freeze-outcome-log`, затем
   продолжить; если и `fca_stats` нет — создать минимальную запись только с наличными полями.
3. Дозаполнить факт: `actual` (level) / `resolved` (event) / `actual_source` / `shock_flag` из
   update, затем прогнать арифметику helper'ом:
   ```bash
   echo '{"entry": <дозаполненная запись>}' \
     | python3 scripts/assemble_artifact.py complete-outcome-log
   ```
   `blocking_count > 0` (напр. event-резолв без `predicted_p`) → показать пользователю, **не
   писать** этот update, продолжить остальные (`actual`/`resolved` — только выводом помощника,
   `references/events-yaml-spec.md` §14.4).
4. Заменить запись в `outcome_log` результатом helper'а. Прогнать `validate-forecast-events` +
   `check-yaml-duplicates` на итоговом файле; при blocking — откат, сообщить.
5. Записать файл через transport (Edit точечно по `outcome_log`, чтобы не переформатировать).

Это единственная запись Workflow L в `forecasts/`; сам monitor-report остаётся в
`monitor-reports/`. Если `outcome_log_updates` пуст/отсутствует — шаг пропустить.

**L6. INDEX.md:**
- В корневой `Claude-Memory/INDEX.md` секции `## Активные мониторинговые отчёты` (создать если её нет) добавить bullet:
  - `- monitor-report-2026-05-07 · {N_high} HIGH alerts · stress {age_days}д{ ⚠️ если due_for_refresh}`
- Старые monitor-reports (>30 дней) — перенести в подсекцию `## Архив monitor-reports`.

**L7. `_sync_log.md`:** строка `{YYYY-MM-DD} | save-to-library | monitor-reports/monitor-report-{date}.yaml | Workflow L | alerts: {N} ({N_high} HIGH, {N_medium} MEDIUM)`.

**L8. Сообщение пользователю:**
```
✅ Сохранён monitor-report-2026-05-07.yaml в Claude-Memory/monitor-reports/.
Открой viewer (tools/portfolio-integrated-viewer.html) → вкладка 🚨 Watchlist для просмотра.
Черновик принят и удалён.
```

**Anti-patterns:**
- ❌ Сохранять monitor-report без `freshness_audit` (он обязателен).
- ❌ Молча принимать неизвестные `category` значения — сначала проверить совместимость с viewer.
- ❌ Перезаписывать старые reports без предупреждения — они представляют исторический контекст.
