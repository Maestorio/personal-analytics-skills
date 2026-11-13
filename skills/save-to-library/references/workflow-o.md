# Workflow O — Калибровочный отчёт (Claude-Memory/calibration/)

> Вынесено из SKILL.md дословно при дроблении 2026-08-12 (этап 3, подготовка Max → Pro).

## Workflow O — Калибровочный отчёт (Claude-Memory/calibration/)

Триггер: сохранение отчёта калибровки прогнозной системы (метрики по `outcome_log`:
Brier / coverage P10–P90 / weighted-vs-unweighted / пере-рейтинг источников). Процедуры
прогонов — `forecast-monitor/references/calibration-playbook.md` (§M1–§M4); этот workflow —
только сохранение результата.

**Файлы этой папки — маркеры калибровочного сторожа forecast-monitor (M1–M4):** по их
basename'ам сторож определяет, какие шаги калибровки сделаны и когда. Поэтому имя файла
жёсткое — отчёт с именем не по паттерну для сторожа невидим.

### O1. Идентификация и frontmatter

Markdown с YAML frontmatter:

| Поле | Статус | Правило |
|------|--------|---------|
| `type` | ОБЯЗАТЕЛЬНО | константа `calibration-report` |
| `kind` | ОБЯЗАТЕЛЬНО | `adhoc` (ручной прогон §M1) / `skill` (отчёт calibration-скилла) / `source_rerating` (§M3) / `catalyst` (v2-C §M4) |
| `date` | ОБЯЗАТЕЛЬНО | YYYY-MM-DD, дата прогона |
| `summary` | ОБЯЗАТЕЛЬНО | 1-2 предложения — идёт в INDEX |
| `n_clean` | Рекомендуется | размер зачётной выборки (warning при отсутствии — честность метрик при малом n) |

### O2. Валидация (детерминированная)

```bash
echo '{"filename": "adhoc-2026-09-14.md",
       "frontmatter": {"type": "calibration-report", "kind": "adhoc",
                       "date": "2026-09-14", "summary": "...", "n_clean": 17}}' \
  | python3 scripts/assemble_artifact.py validate-calibration-report
```

Blocking: `kind` вне enum; имя файла не `{prefix}{date}.md` (prefix по kind: `adhoc-` /
`calibration-` / `source-rerating-` / `catalyst-calibration-`; допустим суффикс `-vN` при
повторном прогоне в тот же день); `TODO_LLM` в frontmatter; пустой `summary`.
При `valid: false` — остановиться, показать issues, не писать.

### O3. Сохранение и индексы

- Путь: `Claude-Memory/calibration/{filename}` — папку создать при первом сохранении.
- В корневой `INDEX.md` — секция `## Calibration` (создать если нет), bullet:
  `- {filename} · {kind} · {date} · n={n_clean} · {summary}`, сортировка по date desc.
- В `_sync_log.md`: `{date} | save-to-library | calibration/{filename} | kind: {kind}`.

### O4. Финальное сообщение

```
✅ Сохранён калибровочный отчёт: Claude-Memory/calibration/{filename}
kind: {kind} | n_clean: {n} — сторож forecast-monitor увидит маркер при следующем запуске.
```

### Anti-patterns (Workflow O)

- ❌ Имя файла не по паттерну `{prefix}{date}.md` — сторож не увидит отчёт, порог будет
  срабатывать повторно.
- ❌ Метрики по фабрикованным полям: записи outcome_log с `null # TODO`
  (l1_unweighted / p10_p90) из соответствующего теста **исключаются**, не додумываются.
- ❌ Смешивать `interim_supersession` / `shock_flag: exogenous_shock` с основным зачётом —
  только отдельными строками (анти-паттерн events-yaml-spec §14.4).
