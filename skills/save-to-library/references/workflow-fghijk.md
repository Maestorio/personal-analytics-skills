# Workflow F — Еженедельный обзор (Portfolio/weekly-reviews/)

Сохраняет артефакты еженедельного обзора от `ru-portfolio-advisor`: до **трёх** файлов одновременно — stocks YAML, bonds YAML, markdown report. Любая комбинация (один / два / три / только chat).

**Naming convention (Phase 10.4):**
- `weekly-review-stock-{date}.yaml` — акции, `type: weekly-stocks-review`
- `weekly-review-bond-{date}.yaml` — облигации, `type: weekly-bonds-review`
- `weekly-review-stock-{date}.md` / `weekly-review-bond-{date}.md` — MD-отчёты; **имя MD =
  имя парного YAML, только расширение другое** (единый канон с SKILL.md advisor'а; ранее
  здесь значился бессуффиксный `weekly-review-{date}.md` — устарело, вызывает конфликт
  при сохранении stock+bond в разных сессиях)

**Legacy:** старый формат `weekly-review-{date}.yaml` (без stock-суффикса) распознаётся по `type: weekly-stocks-review`. Сохранять можно как есть; новые файлы — только в новом формате.

### F1. Идентификация

**F1a — Stock YAML:**
- Содержит `schema_version: 1`, `type: weekly-stocks-review`, `per_stock`
- Имя файла: `weekly-review-stock-{date}.yaml` или `weekly-review-{date}.yaml` (legacy)
- Пользователь говорит «сохрани обзор акций», «save stocks review»

**F1b — Bond YAML (Phase 10.4):**
- Содержит `schema_version: 1`, `type: weekly-bonds-review`, `per_bond`
- Имя файла: `weekly-review-bond-{date}.yaml`
- Пользователь говорит «сохрани обзор облигаций», «save bonds review»

**F1c — Markdown (.md):**
- Содержит заголовок `# Weekly Review` + строку `portfolio_snapshot_id:` или `snapshot_id:`
- Пользователь говорит «сохрани репорт обзора», «save report»
- ru-portfolio-advisor завершил работу с флагом `--save-report`

**F1d — Все вместе:** если в сообщении присутствуют несколько форм — сохранить все последовательно.

### F2. Валидация (детальная, hard-block на drift и пропущенных required-полях)

> **Вход — путём к файлу (`--file`), не JSON в команде (RPA-38).** Обзор весит 150–260 КБ;
> `echo '<YAML>' | …` выводит его целиком токенами модели — до ~120 тыс. на проверку. stdin оставлен
> для обратной совместимости.
>
> **Новые блокирующие проверки обзоров с `review_date` ≥ 2026-10-27 (RPA-34):** `coverage.method`
> = `sweep_collect` при ≥5 акциях / корп-эмитентах (или `inline_owner_approved` + `method_note`,
> если владелец согласился собирать новости без субагентов). Отказ — вернуть пользователя в
> `/ru-portfolio-advisor` на sweep, а не чинить блок руками.

**Stock YAML — validate-weekly-review-stock** (детальный валидатор с anti-drift проверками после 2026-05-12 incident; маршрутизация по `schema_version`: `2` → v2-ветка, `1` → legacy v1):
```bash
python3 scripts/assemble_artifact.py validate-weekly-review-stock --file {путь к weekly-review-stock-*.yaml}
```
Блокирует запись если:
- `schema_version` не число (v2: `2`; legacy v1: `1` + `horizon_months: 20`)
- `type` ≠ `"weekly-stocks-review"`
- v2: горизонт-блок невалиден (`horizons`/`horizon_ends`/`primary_horizon`) или присутствуют v1-поля (`horizon_months`/`horizon_end`/`in_horizon` в catalyst)
- `per_stock` пуст или содержит drift-имена: `share_actual_pct`, `ie_share_pct`, `delta_pct`, `catalysts:` (с «s»); RPA-19: `planned_share_pct`/`user_planned_pct`/`weight_planned_pct` (канон `weight_user_planned_pct`), `divergence_vs_planned_pp` (канон `weight_divergence_vs_planned_pp`), `divergence_vs_ie_pp` (канон `weight_divergence_vs_ie_pp`)
- Любой ticker без полного канонического набора (sector, weight_real_pct, weight_user_planned_pct [PRIMARY target], weight_ie_target_pct [secondary target], weight_divergence_vs_planned_pp [PRIMARY], weight_divergence_vs_ie_pp [secondary], weight_divergence_pp [DEPRECATED алиас vs_ie, обратная совместимость], on_iis, fundamental_score+basis, div_yield_12m_pct {value, ci_pct}+basis, catalyst[]+full structure, advisor_verdict+confidence+basis; `verification_priority` — поле есть, `null` до штампа stamp-report)
- Любое значение начинается с `TODO_LLM` (нерасфилленный плейсхолдер от build_weekly_stock_stub.py)
- Catalyst entry без `trigger`, `p`, `source`, `source_quality`, или `upside_pct`/`downside_pct` + CI
- форма среза ограничений `user_constraints` (F2.6)

Warning (не блок), v2:
- **R-COV (2026-07-23)**: у тикера нет ни одного источника с `accessed_date` в окне 7 дней до `review_date` и нет `carried_over: true` — похоже на молчаливый carry-over блока из прошлого обзора (прецедент 23.07: 21/21 тикеров с источниками от 11.07 при заявлении «проверено всё»)

**Bond YAML — validate-weekly-review-bond** (детальный; та же v1/v2-маршрутизация):
```bash
python3 scripts/assemble_artifact.py validate-weekly-review-bond --file {путь к weekly-review-bond-*.yaml}
```
Блокирует запись если:
- `schema_version` не число, `type` ≠ `"weekly-bonds-review"`
- `summary.total_value_rub` отсутствует (drift `bonds_total_rub` без алиаса)
- `summary` без `weighted_ytm_pct` (число ИЛИ `{value, ci_pct}`), `weighted_duration_days` (число, не объект), `by_type_pct`, `by_credit_quality_pct` (ключи ⊆ {HIGH, MEDIUM, LOW}), `maturity_ladder_pct`
- per_bond entry без полного набора (name, weight_real_pct, on_iis, bond_type ∈ {ofz, corp_rub, fx_replacement, floater, perpetual}, maturity_date, ytm_pct, credit_quality, catalyst[], advisor_verdict, advisor_verdict_basis; `verification_priority` — поле есть, `null` до штампа)
- Любое значение `TODO_LLM`

**Backward-compat:** `validate-weekly-review` (без суффикса) теперь маршрутизатор: по полю `type` направляет в `-stock` или `-bond` детальный, для unknown/legacy — базовый чек.

При `blocking_count > 0` — **отказать в записи**, показать первые 5 issues, перенаправить пользователя на перегенерацию через `/ru-portfolio-advisor` (Python-стаб-генератор автоматически предотвратит большую часть нарушений).

**Markdown:** проверить наличие заголовка `# Weekly Review {date}`, строки `snapshot_id:` и хотя бы одной таблицы позиций. Отсутствие — предупредить, не блокировать.

### F2.6. Срез ограничений — проверка формы (stock/bond YAML)

`user_constraints[]` в обзоре — производный срез (schema.md §4.2): его строит `reconcile_constraints.py` советника
из условий и плана на дату обзора; save-to-library источником его не читает и с прошлым обзором не сверяет.
Проверку делает тот же `validate-weekly-review-stock|bond` (F2), отдельной команды нет:

- обзор с `recorded_at` (без него — `review_date`) не раньше 2026-10-31: запись среза обязана иметь
  `derived: true`, `as_of` (дата), ровно одно из `condition_id` / `plan_field` (`user_plan` | `user_status`),
  `summary`; `reason` — код кодлиста `block_reason`, `status` — `pending|fired`, `until` — дата или null;
  нарушение — **блок**. Запись без `derived` (прежняя форма «ограничения обзора») — warning «устаревшая форма»,
  игнорируется;
- TRIPLET RULE (форма, любые обзоры): `unconstrained_verdict` ≠ `advisor_verdict` ⇒ срез непуст (в новых —
  хотя бы одна запись с `derived`), иначе **блок**;
- старые обзоры — без проверки формы.

Блок — вернуть пользователя в `/ru-portfolio-advisor` (Шаг 9.5: перезапустить `reconcile_constraints.py` и положить
выход в YAML), не чинить срез руками. Новое ограничение в обзор не записывается — это условие (Workflow M / Режим 9).

### F2.7. Условия при сохранении обзора (только проверка)

Обзор недели условий не пишет: Mode 1 и Mode 2 их только читают (`apply_condition.py digest`, `crosscheck`), а
определения условий пишет скрипт `apply_condition.py` по Режиму 9, состояние — сайт. save-to-library при
сохранении обзора условий не трогает и проверяет только текст:

1. ✅ сработавшее условие в MD без резолюции (применён / уже исполнено / отклонено / перенесено) — предупредить.
2. Пункт действий «применить условия» / «записать условия» — предупредить: такой пункт ничего не исполняет;
   перенос — фраза владельцу для Режима 9, закрытие — кнопка на сайте.

### F3. Имена файлов и сохранение

**Stock YAML:** `weekly-review-stock-{date}.yaml`
```
Write("{LOCAL_LIBRARY_ROOT}/Portfolio/weekly-reviews/weekly-review-stock-{date}.yaml", content=yaml_content)
```

**Bond YAML:** `weekly-review-bond-{date}.yaml`
```
Write("{LOCAL_LIBRARY_ROOT}/Portfolio/weekly-reviews/weekly-review-bond-{date}.yaml", content=yaml_content)
```

**Порядок (R33): правки условий (Режим 9 / Workflow M) → штамп обзора → validate --root.** Правка условий сама
перештамповывает обзор того же дня (`apply_condition.py` → `restamped`), поэтому условия, поправленные после штампа,
приоритет не ломают; штамп ниже всё равно обязателен после записи YAML.

**Штамп и сверка YAML (R28) — сразу после записи каждого YAML:**
```bash
python3 scripts/assemble_artifact.py stamp-report --root {LOCAL_LIBRARY_ROOT} --doc Portfolio/weekly-reviews/weekly-review-{stock|bond}-{date}.yaml
python3 scripts/assemble_artifact.py validate-weekly-review-{stock|bond} --file {LOCAL_LIBRARY_ROOT}/Portfolio/weekly-reviews/weekly-review-{stock|bond}-{date}.yaml --root {LOCAL_LIBRARY_ROOT}
```
`stamp-report` ставит `recorded_at` (если нет) и пересчитывает `verification_priority` каждой бумаги функцией движка
(вердикт, уверенность, действующие условия модуля (а), гейт модуля (б)); вывод `priority_changed` — «тикер: было →
стало» — показать пользователю одной строкой. Модель приоритет не пишет (в стабе `null`). Валидатор с `--root`
блокирует расхождение приоритета с движком; без `--root` — предупреждение «контекст не передан». Копия
`gate_status_snapshot` у бумаг — предупреждение «устаревшая копия, не читается» (у старых обзоров — норма).
С обзоров от 31.10: упразднённые блоки старого формата (состояние условий, директивы) — предупреждение,
`written_back: true` — блок («обзор не пишет состояние условий»); «срочно» без `verification_checklist` — блок (кроме «нужен разбор» — предупреждение
«Разбери X»), «желательно» без пунктов — предупреждение.

**Markdown:** имя = имя парного YAML (`weekly-review-stock-{date}.md` / `weekly-review-bond-{date}.md`)
```
Write("{LOCAL_LIBRARY_ROOT}/Portfolio/weekly-reviews/weekly-review-{stock|bond}-{date}.md", content=md_content)
```

Время: верхним уровнем YAML обзора опциональное `created_at: "YYYY-MM-DDTHH:MM"` (`date +%Y-%m-%dT%H:%M` перед записью) — по нему вьюер ставит обзор в день среди разборов и гейтов.

Дедуп по имени: если файл с той же датой и тем же типом уже есть — спросить (a) заменить, (b) сохранить как v2, (c) отмена.

### F4. Обновление индексов

**Механику вставки выполняет `scripts/update_index.py`, не модель.** `Portfolio/INDEX.md` —
138 КБ, `_sync_log.md` — 327 КБ; вычитывать их целиком ради одной строки нельзя. Модель
пишет ТЕКСТ записи (проза про содержание артефакта — она не автоматизируется), скрипт
отвечает за размещение, порядок newest-first, бэкап и идемпотентность по имени файла:

```bash
echo '{"index_path": "{LOCAL_LIBRARY_ROOT}/Portfolio/INDEX.md",
        "section": "### weekly-reviews/",
        "rows": ["| weekly-review-stock-{date}.yaml | weekly-stocks-review | {date} | ... |",
                 "| weekly-review-stock-{date}.md | weekly-review (stocks) | {date} | ... |"],
        "backup_dir": "{LOCAL_LIBRARY_ROOT}/Portfolio/.backups"}' \
  | python3 scripts/update_index.py add-rows

echo '{"index_path": "{LOCAL_LIBRARY_ROOT}/Portfolio/INDEX.md",
        "line": "{date} (weekly-review-stock-{date} — ...)"}' \
  | python3 scripts/update_index.py add-meta

echo '{"log_path": "{LOCAL_LIBRARY_ROOT}/_sync_log.md",
        "entries": ["{date} | save-to-library | {путь} | Workflow F | ..."]}' \
  | python3 scripts/update_index.py sync-log
```

`skipped_existing` в отчёте непуст — файл уже в INDEX: это либо повторное сохранение
(тогда `"replace": true` с обновлённой строкой), либо ошибка адресации. Молча
игнорировать нельзя. `"dry_run": true` — прогон без записи.

Содержание строк (что именно писать):
```
| weekly-review-stock-{date}.yaml | weekly-stocks-review | {date} | snapshot: {snapshot_id} |
| weekly-review-bond-{date}.yaml  | weekly-bonds-review  | {date} | snapshot: {snapshot_id} |
| weekly-review-{date}.md         | weekly-review        | {date} | human-readable report   |
```

Добавить запись(и) в `Claude-Memory/_sync_log.md`:
```
{YYYY-MM-DD} | save-to-library | Portfolio/weekly-reviews/weekly-review-stock-{date}.yaml | Workflow F (stocks) | snapshot: {snapshot_id}
{YYYY-MM-DD} | save-to-library | Portfolio/weekly-reviews/weekly-review-bond-{date}.yaml | Workflow F (bonds) | snapshot: {snapshot_id}
{YYYY-MM-DD} | save-to-library | Portfolio/weekly-reviews/weekly-review-{date}.md | Workflow F | snapshot: {snapshot_id}
```
Формат строки — `{дата} | save-to-library | {путь} | Workflow {X}[ (вариант)] | {ключ: значение | …}`; строка дописывается в конец `_sync_log.md`.
(только для реально сохранённых файлов)

### F4.5. Гейты при сохранении обзора

Гейт акции считается из её последнего решения (`Portfolio/decisions/`) при чтении; файла гейтов нет, при
сохранении обзора ничего не обслуживается. Флаг `flags.gate_review_required: true` в YAML обзора даёт «Нужен
разбор», пока обзор новее решения. Решения пишутся только из отчётов разбора — блок `decisions:` шапки отчёта и
`decision_write.py from-report` (Workflow N) — или по слову владельца (`decision_write.py owner`, Workflow M).

### F5. Финальное сообщение

```
✅ Сохранено:
  Claude-Memory/Portfolio/weekly-reviews/weekly-review-stock-{date}.yaml  ← акции
  Claude-Memory/Portfolio/weekly-reviews/weekly-review-bond-{date}.yaml   ← облигации
  Claude-Memory/Portfolio/weekly-reviews/weekly-review-{date}.md          ← репорт
snapshot: {snapshot_id}

Следующий шаг: portfolio-integrated-view (если есть свежий stress-тест)?
Открой viewer (tools/portfolio-integrated-viewer.html) — увидишь обновлённые вкладки «Позиции» и «📜 Облигации».
```
(показывать только строки реально сохранённых файлов)

---

# Workflow G — Интегрированный вид (Portfolio/integrated-views/)

Сохраняет `.md` вывод `portfolio-integrated-view`.

### G1. Идентификация

**G1.0 — черновик в `_drafts/`** (первый по приоритету): `Glob("_drafts/integrated-view-*.md")`; самый поздний черновик, дата которого позже даты последнего вида в `Portfolio/integrated-views/` (или там пусто), — источник `.md`, чат — только для уточнений владельца (дата та же — спросить владельца). Черновика нет (mount был недоступен, «черновик не записан») — вывод из чата. G2 проверяет черновик так же, как текст из чата. Приёмка — командой `python3 scripts/promote_draft.py --root {LOCAL_LIBRARY_ROOT} --draft <имя> --kind integrated-view --dry-run` → показать владельцу, что будет записано и заменено → по «да» та же команда без `--dry-run`: скрипт проверяет frontmatter (G2.1) и секции (G2.2), пишет вид, строку `### integrated-views/` в `Portfolio/INDEX.md`, дописывает INDEX и `_sync_log.md` и удаляет черновик (код 1 — блокер, ничего не записано, `issues` — владельцу). Текст черновика модель не переписывает; за ней — напоминание в календаре и строка «Self-validation roadmap» (G5), решение по занятому имени, ответы на вопросы валидатора и правка текста по замечаниям (Edit черновика, приёмка заново).

Сигналы:
- Вывод portfolio-integrated-view: содержит ≥5 секций из набора (Snapshot, Stress, Catalyst, Verdict, Predictions for Review)
- Пользователь говорит «сохрани интегрированный вид»

### G2. Валидация

**G2.1 (БЛОКИРУЮЩАЯ, Python) — frontmatter-контракт графиков (@1.3).** Распарсить
YAML frontmatter артефакта и прогнать валидатор:

```bash
echo '<frontmatter-as-json>' | python3 skills/save-to-library/scripts/assemble_artifact.py validate-integrated-view
```

`valid: false` / `blocking_count > 0` → **отказ в записи** с перечнем полей.
Валидатор ловит именно LLM-drift машинных блоков: `portfolio_by_horizon` /
`total_return` должны быть скопированы **as-is** из результата
`aggregate_positions.py` (`frontmatter_portfolio_by_horizon` /
`frontmatter_total_return`) — числа числами (не строки «+13.6%»), даты строками
в кавычках (иначе js-yaml вьюера отдаёт Date и графики ломаются), ключи-месяцы
совпадают с top-level `horizons`, `primary_horizon ∈ horizons`, `ci_method`
enum, v1-поля горизонта (`horizon_months`/`horizon_end`) отсутствуют.
Frontmatter не парсится как YAML → это само по себе блокер (перегенерировать).
Артефакты @≤1.2 — только warning «старый формат» (legacy не блокируем).

**G2.2 (мягкая) — секции.** Проверить наличие хотя бы 5 ожидаемых секций. Если ≥1
обязательной секции нет — предупредить, но не блокировать (portfolio-integrated-view
мог сгенерировать частичный вид).

### G3. Имя файла и сохранение

**Имя:** `integrated-view-{date}.md`

Пример: `integrated-view-2026-05-06.md`

Запись (Synology mount):
```
Write("{LOCAL_LIBRARY_ROOT}/Portfolio/integrated-views/integrated-view-{date}.md", content=md_content)
```

### G4. Обновление индексов

Добавить строку в `Portfolio/INDEX.md`:
```
| integrated-view-{date}.md | integrated-view | {date} | — |
```

Добавить запись в `Claude-Memory/_sync_log.md`:
```
{YYYY-MM-DD} | save-to-library | Portfolio/integrated-views/integrated-view-{date}.md | Workflow G
```

### G5. Calendar reminder

Вычислить `reminder_date = {integrated-view date} + 6 мес` (пример: 2026-05-06 → 2026-11-06).

Предложить пользователю создать Google Calendar событие:

```
Создать напоминание в Google Calendar? [да / нет]
Дата: {reminder_date}
Название: «Аудит predictions_for_review — integrated-view-{date}.md»
Описание: «Запустить retrospective-forecast-audit на Section 10 из
  Claude-Memory/Portfolio/integrated-views/integrated-view-{date}.md.
  После аудита обновить calibration factors в catalyst-tree-rules.md.
  Ориентир: Claude-Memory/Portfolio/INDEX.md → Self-validation roadmap.»
```

Если «да» (или без ответа — создать по умолчанию): создать событие через Google Calendar MCP:
```
mcp__claude_ai_Google_Calendar__create_event(
  summary="Аудит predictions_for_review — integrated-view-{date}.md",
  start={"dateTime": "{reminder_date}T10:00:00", "timeZone": "Europe/Moscow"},
  end={"dateTime": "{reminder_date}T11:00:00", "timeZone": "Europe/Moscow"},
  description="Запустить retrospective-forecast-audit на Section 10 из Claude-Memory/Portfolio/integrated-views/integrated-view-{date}.md. После аудита обновить calibration factors в ru-portfolio-advisor/references/catalyst-tree-rules.md. Ориентир: Claude-Memory/Portfolio/INDEX.md → Self-validation roadmap.",
  calendarId="primary"
)
```

Если «нет» или MCP недоступен: показать блок для ручного создания:
```
📅 Создай напоминание вручную:
  Дата: {reminder_date}
  Название: Аудит predictions_for_review — integrated-view-{date}.md
  Описание: Запустить retrospective-forecast-audit на Section 10 из
  integrated-view-{date}.md. Обновить catalyst-tree-rules.md.
```

После создания события (или отказа): обновить раздел «Self-validation roadmap» в
`Claude-Memory/Portfolio/INDEX.md` — добавить строку:
```
| integrated-view-{date}.md | {date} | **{reminder_date}** | ⏳ ожидает |
```

### G6. Финальное сообщение

```
✅ Сохранено: Claude-Memory/Portfolio/integrated-views/integrated-view-{date}.md
{если взят черновик: «черновик принят и удалён»}
```

---

# Workflow H — Снапшот портфеля (Portfolio/snapshots/)

Сохраняет JSON-снапшот от `portfolio-data-loader`.

### H1. Идентификация

Сигналы:
- JSON с `schema_version: "2.0"` и непустым списком `positions`
- Вывод portfolio-data-loader
- Пользователь говорит «сохрани снапшот портфеля»

### H2. Валидация

Для запуска: `python3 scripts/assemble_artifact.py validate-snapshot < snapshot.json`

Обязательные: `schema_version: "2.0"`, непустой список `positions`, `total_value > 0`.

При `blocking_count > 0` — остановиться, не сохранять.

### H3. Имя файла и сохранение

**Имя:** `portfolio-{date}.json`

Дата — из поля `date` или `generated_at` в JSON. Уточнить у пользователя при неясности.

Дедуп по дате: если уже есть — спросить (a) заменить, (b) сохранить как v2, (c) отмена.

Запись (Synology mount):
```
Write("{LOCAL_LIBRARY_ROOT}/Portfolio/snapshots/portfolio-{date}.json", content=json_content)
```

### H4. Обновление индексов

Добавить строку в `Portfolio/INDEX.md`:
```
| portfolio-{date}.json | snapshot | {date} | positions: {N}, total: {total_value} RUB |
```

Добавить запись в `Claude-Memory/_sync_log.md`:
```
{YYYY-MM-DD} | save-to-library | Portfolio/snapshots/portfolio-{date}.json | Workflow H | positions: {N} | total_value: {total_value}
```

### H5. Финальное сообщение

```
✅ Сохранено: Claude-Memory/Portfolio/snapshots/portfolio-{date}.json
positions: {N} | total_value: {total_value} RUB
```

---

# Workflow I — Макро-снапшот (macro-snapshots/)

Сохраняет `.md` снапшот российских макроиндикаторов от `macro-ru-watcher`.

### I1. Идентификация

Сигналы:
- `.md` файл с секциями по ставке ЦБ, инфляции, USD/RUB (или CNY/RUB, RGBI, IMOEX)
- Вывод macro-ru-watcher
- Пользователь говорит «сохрани макро-снапшот»

### I2. Валидация

Проверить наличие хотя бы двух из: ставка ЦБ / инфляция / USD/RUB / IMOEX. Если меньше двух — предупредить (возможно неполный снапшот).

### I3. Имя файла и сохранение

**Имя:** `ru-{date}.md`

Дата — из поля `date` или шапки снапшота.

Дедуп по дате: если `ru-{date}.md` уже есть — спросить (a) заменить, (b) добавить суффикс `-v2`, (c) отмена.

Запись (Synology mount):
```
Write("{LOCAL_LIBRARY_ROOT}/macro-snapshots/ru-{date}.md", content=md_content)
```

### I4. _sync_log.md

Добавить запись в `Claude-Memory/_sync_log.md`:
```
{YYYY-MM-DD} | save-to-library | macro-snapshots/ru-{date}.md | Workflow I
```

### I5. Финальное сообщение

```
✅ Сохранено: Claude-Memory/macro-snapshots/ru-{date}.md
```

---

# Workflow J — Макро-инпут (macro-chain/)

Сохраняет YAML-артефакт от `macro-forecast-chain`.

### J1. Идентификация

Сигналы:
- YAML с `type: macro-input-chain` либо `type: macro-scenarios` (файл сценарных значений факторов для стресса)
- Вывод macro-forecast-chain (Шаг 8d)
- Пользователь говорит «сохрани макро-инпут»

### J2. Валидация

Обязательные поля: `type: macro-input-chain`, `date`, `factors` (непустой). При отсутствии — спросить.

Файл `type: macro-scenarios` перед записью проверь скриптом:

```bash
python3 scripts/assemble_artifact.py validate-macro-scenarios --file {путь к macro-scenarios-{date}.yaml}
```

`valid: false` — не сохранять: вернуть перечень отказов (фактор — сценарий — что не так) на пересборку `macro-forecast-chain`; по такому файлу стресс не считается. Записи `warning` показать пользователю и сохранять.

### J3. Имя файла и сохранение

**Имя:** `macro-input-{date}.yaml`; для `type: macro-scenarios` — `macro-scenarios-{date}.yaml` (путь и дедуп те же).

Дедуп по дате: если уже есть — спросить (a) заменить, (b) v2, (c) отмена.

Запись (Synology mount):
```
Write("{LOCAL_LIBRARY_ROOT}/macro-chain/macro-input-{date}.yaml", content=yaml_content)
```

### J4. _sync_log.md

Добавить запись в `Claude-Memory/_sync_log.md`:
```
{YYYY-MM-DD} | save-to-library | macro-chain/macro-input-{date}.yaml | Workflow J | factors: {N}
```

### J5. Финальное сообщение

```
✅ Сохранено: Claude-Memory/macro-chain/macro-input-{date}.yaml
factors: {N}

Следующий шаг: portfolio-scenario-stress?
```

---

# Workflow K — Коллекция прогнозов (forecast-collections/)

Сохраняет `.md` файл с набором resolved-прогнозов от `forecast-collector`.

### K1. Идентификация

Сигналы:
- Файл `fc-{source}-collection-{date}.md`
- Вывод forecast-collector
- Пользователь говорит «сохрани коллекцию прогнозов»

### K2. Валидация

Проверить frontmatter на наличие: `source`, `collection_date`, хотя бы один прогноз в теле. При отсутствии `source` или `collection_date` — спросить.

### K3. Имя файла и сохранение

**Имя:** `fc-{source-slug}-collection-{collection_date}.md`

Пример: `fc-invest-era-collection-2026-04.md`

Запись (Synology mount):
```
Write("{LOCAL_LIBRARY_ROOT}/forecast-collections/fc-{source-slug}-collection-{date}.md", content=md_content)
```

### K4. _sync_log.md

Добавить запись в `Claude-Memory/_sync_log.md`:
```
{YYYY-MM-DD} | save-to-library | forecast-collections/fc-{source-slug}-collection-{date}.md | Workflow K | source: {source}
```

### K5. Финальное сообщение

```
✅ Сохранено: Claude-Memory/forecast-collections/fc-{source-slug}-collection-{date}.md
source: {source} | collection_date: {date}

Следующий шаг: retrospective-forecast-audit?
```
