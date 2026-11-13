# Workflow N — Ad-hoc report (Portfolio/reports/)

> Вынесено из SKILL.md дословно при дроблении 2026-08-12 (этап 3, подготовка Max → Pro).

## Workflow N — Ad-hoc report (свободный markdown в Portfolio/reports/)

Триггер: пользователь сохраняет свободный отчёт от `ru-portfolio-advisor` (Mode 3/4/5/6/7/8 или free-form). Полная спецификация полей и тела отчёта — `ru-portfolio-advisor` `references/adhoc-save.md` (до дробления 2026-08-12 — SKILL.md §«Ad-hoc save»). Viewer-рендер — `tools/portfolio-integrated-viewer.html` кнопкой `📄 Reports` через `state.data.advisorReports`.

### N1. Идентификация

Markdown файл с YAML frontmatter, который содержит **минимум**:
- `author: "ru-portfolio-advisor"` (константа)
- `kind` — код кодлиста `report_kind` (`single_analysis`, `tactical_rebalance`, `quality_review`, `iis_buy`, `fund_selection`, `bond_bridge_planner`, `candidates_outside_ie`, `scenario_analysis`, `tax_optimization`, `retro_calibration`, `general`)

Если frontmatter содержит распознаваемый `type:` другого workflow (`weekly-stocks-review`, `monitor-report`, `scenario-matrix`, и т.п.) — это НЕ ad-hoc report, маршрутизировать в соответствующий workflow.

### N2. Порядок сохранения (одним списком, без развилок)

Шапка `report@1` (схема — `docs/investment/_cross-cutting/data-structures/schema.md` §4.3): `title`, `date`, `kind`
(кодлист `report_kind`), `mode_codes` (главный первым; `4a`/`4b`, не `4`), `tickers`, блок `decisions:` у режимов
3 / 4 / 5a / 8 (`key, verdict, target_pct, review_by, note`, + `confidence`, `keep_open`; `key` из `tickers`).
`schema_version` и `recorded_at` ставит скрипт. Корень `{root}` — в Cowork `$HOME/mnt/Claude-Memory`.

1. **Файл отчёта** — `Write` в `{root}/Portfolio/reports/{filename}.md` (имя — N3); `{doc}` =
   `Portfolio/reports/{filename}.md`.
2. **Время записи и версия схемы:** `python3 scripts/assemble_artifact.py stamp-report --root {root} --doc {doc}` —
   ставит `recorded_at` (МСК) и `schema_version: report@1`, если их нет; повтор ничего не меняет.
3. **Проверка шапки (блокирующая):** `python3 scripts/assemble_artifact.py validate-report --file {root}/{doc}`.
   `blocking_count > 0` — исправить шапку в сохранённом файле и повторить шаг 3; шаги 4–5 до зелёной проверки
   не выполняются.
4. **Новые условия из отчёта** (если отчёт их предлагает): по каждому —
   `echo '{…, "source": {"kind": "report", "doc": "{doc}"}}' | python3 scripts/apply_condition.py add --root {root}
   --by mode_<главный режим> [--plan … --snapshot …]`; `id` из вывода — в список `{created}`. Поля входа —
   `ru-portfolio-advisor` `references/mode-9-conditions.md`.
5. **Решения** (если в шапке есть `decisions:`): `python3 scripts/decision_write.py from-report --root {root}
   --doc {doc} [--stress <id действующего стресса>] [--created {created через запятую}]` — файлы решений; сработавшие
   условия бумаги скрипт закрывает решением (`conditions_resolved`, кроме `keep_open`). Условия создаются до
   решений, потому что `--created` проверяет, что такие `id` уже есть в файле условий.
6. Индексы — N6; сообщение — N7.

Жёсткие проверки (hard-block): mojibake в шапке или теле, `TODO_LLM` в теле — отказ до регенерации.

### N3. Имя файла

Паттерн: `Portfolio/reports/{YYYY-MM-DD}-{kind-slug}-{topic-slug}.md`

- `{YYYY-MM-DD}` = frontmatter `date`
- `{kind-slug}` = `kind` с `_` → `-` (например, `bond_bridge_planner` → `bond-bridge-planner`)
- `{topic-slug}` — короткий slug (2-3 значимых слова, lowercase kebab-case, кириллица → ISO 9 транслит, max 30 симв; правила в `references/file-naming.md`)

Дедупликация: если файл с этим именем уже есть → спросить «перезаписать или сохранить с суффиксом `-v2`?».

### N4. Структура body (рекомендуемая, не блок)

Yellow warning (не hard-block) если отсутствует `# H1` в первой строке после frontmatter (viewer использует fallback на `title` из frontmatter, но это менее идиоматично).

Рекомендуемая структура (из ru-portfolio-advisor `references/adhoc-save.md`):
```
# {Title}
**TL;DR:** ...
## Контекст
## Анализ
## Выводы / Action items
## Источники
```

### N5. Сохранение

Путь `Claude-Memory/Portfolio/reports/{filename}.md` (папки нет — создать); запись и порядок — N2.

### N6. Обновление индексов

В `Portfolio/INDEX.md` секцию `## Ad-hoc reports` (создать если нет) — bullet:
```
- {filename} · {kind} · {date} · {title} · {N_tickers}t · h={horizon_months}мес
```
Сортировка — по `date` desc.

Старые reports (>180 дней) — перенести в подсекцию `## Архив reports/`.

В `_sync_log.md`:
```
{YYYY-MM-DD} | save-to-library | Portfolio/reports/{filename}.md | kind: {kind} | title: "{title}"
```

### N7. Финальное сообщение

```
✅ Сохранён ad-hoc report: Claude-Memory/Portfolio/reports/{filename}.md
kind: {kind} | author: {author} | mode: {mode} | tickers: {N}
Решения: {KEY — вердикт словами, гейт словами} · условия: {id новых}   (строки — только если записаны)

Открой viewer (tools/portfolio-integrated-viewer.html) → кнопка 📄 Reports — увидишь репорт в списке.
```

### Anti-patterns

- ❌ Сохранять отчёт без обязательных полей frontmatter (`title`, `date`, `author`, `kind`, `summary`) — viewer не сможет рендерить корректно.
- ❌ Использовать `kind` вне enum — viewer фильтрация сломается.
- ❌ Маршрутизировать сюда weekly-review, integrated-view, stress-test — у них свои workflow (F, G, E) с детальной валидацией.
- ❌ Писать в `Portfolio/reports/` файлы от других producer'ов (forecast-monitor, macro-watcher, и т.п.) — папка зарезервирована под output ru-portfolio-advisor.
- ❌ Дописывать TODO_LLM или mojibake — отказ.
- ❌ Писать `recorded_at` в шапку самому (командой `date`) — время ставит `stamp-report`.
- ❌ Решения или условия без зелёной `validate-report`; решения раньше условий того же отчёта.
