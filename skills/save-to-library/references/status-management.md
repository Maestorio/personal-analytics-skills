# Управление статусом прогнозов и сценариев

> Вынесено из SKILL.md дословно при дроблении 2026-08-12 (этап 3, подготовка Max → Pro).

## Управление статусом (для прогнозов и сценариев)

### `active → resolved`

Триггер: пользователь сохраняет результат `retrospective-forecast-audit` для прогноза.

**Полный flow при сохранении ретроспективы:**

1. Запустить **Workflow D** (атомарный) — за один проход:
   - полный отчёт → `reports/{YYYY-MM-DD}-{source-slug}-{period}.md`
   - сжатый trust-профиль → `domains/{domain}/{source-slug}-{period}.md`
   - обновить `reports/INDEX.md` и `domains/{domain}/INDEX.md`
   - дописать одну строку в `_sync_log.md`
2. Если аудит был направлен на конкретный прогноз из `forecasts/` — предложить обновить его статус:
   - Найти `.yaml` целевого прогноза по `topic` или явному указанию пользователя
   - Обновить `status: active → resolved`
   - Добавить в `final_audit`:
     ```yaml
     final_audit:
       due: {horizon}
       status: done
       completed_date: {audit_date}
       audit_file: reports/{basename-report}.md
     ```

Workflow A (только сжатый профиль, без полного отчёта) запускается отдельно лишь когда полного отчёта нет и пользователь явно хочет обновить только профиль доверия — это редкий edge case. Для типичного ретро-аудита Workflow D сам пишет профиль.

Retrospective-forecast-audit сам не пишет yaml; все изменения статуса делает save-to-library по запросу пользователя.

### `active → superseded`

Триггер: пользователь сохраняет новый прогноз с тем же `topic` и выбирает вариант B5(a).

Действия в save-to-library уже описаны в B6.

**Промежуточный `outcome_log`-снимок (§14.3, калибровка).** Перед пометкой старого файла
`superseded` дописать в его `outcome_log` промежуточную запись `record_type:
interim_supersession` — «как прогноз от даты составления выглядел против факта на дату замены»:

- `resolve_date` = дата замены (`forecast_date` нового файла), `logged_at` = today.
- `forecast_*` — заморожены **на момент составления СТАРОГО прогноза** (freeze из его
  `fca_stats`; не на дату замены — иначе тест ценности весов бессмыслен). Helper:
  `freeze-outcome-log` c `record_type: interim_supersession`.
- `actual` = факт на дату замены (спот/ставка), если пользователь/монитор его дал → прогнать
  `complete-outcome-log` (`actual` — только выводом помощника, правило — `references/events-yaml-spec.md` §14.4); иначе `actual: null` (дозаполнится позже).
- Если у старого файла нет `fca_stats` (legacy) — снимок пропустить (best-effort).

Interim-снимки помечены `record_type` намеренно: они шумнее настоящих horizon-резолвов и не
должны мешаться 1:1 в Brier.

### `active → expired`

Триггер: `revise-memory-remote` обнаруживает прогноз с прошедшим `horizon` и без выполненного retrospective-forecast-audit более 30 дней. revise предлагает пользователю пометить expired или запустить retro-audit. Если пользователь выбирает «пометить expired» — save-to-library обновляет:

```yaml
status: expired
final_audit:
  due: {horizon}
  status: overdue
```

**`outcome_log`-запись на резолв (§14.3).** При переходе в `expired` дописать в `outcome_log`
запись `record_type: horizon_resolve` на `resolve_date = horizon`: freeze `forecast_*` из
`fca_stats`, `actual` = факт на горизонт (если известен → `complete-outcome-log` (`actual` — только выводом помощника, правило — `references/events-yaml-spec.md` §14.4); иначе
`null` + пометка «требует дозаполнения»). Это резолв-точка, пригодная для Brier (в отличие от
interim-снимков). Если `fca_stats` нет — запись пропустить.

`revise-memory-remote` не делает этого сам без подтверждения.

### Разделение ролей при закрытии / захвате исхода (F7)

**save-to-library — единственный, кто закрывает и пишет.** Детектор (forecast-monitor для active,
revise-memory-remote для superseded/expired через свип §2.3.1) находит резолв, **web_search'ит
факт и предлагает** значения; save-to-library:

1. Замораживает предсказанные поля из `fca_stats` прогноза (`freeze-outcome-log`) — не сочиняет.
2. Дозаполняет фактом из предложения (`actual`/`resolved`/`actual_source`) и считает
   `error_pct`/`in_p10_p90` (`complete-outcome-log`; в файл идёт только его вывод — §14.4).
3. Пишет `outcome_log` в forecast, обновляет статус (`expired`/`resolved`), INDEX + `_sync_log`.

**Вход владельца «Закрой прогноз <тема> …»** (фраза монитора для `horizon_passed`) — процедура и формат `final_audit.closed_by: owner_close` в `references/close-forecast.md`.

**Batch-close** (по запросу «закрой все устаревшие»): revise-memory-remote выдаёт список
кандидатов; save-to-library проходит их по одному (каждый — статус + `outcome_log` + INDEX),
пропуская те, где пользователь не подтвердил. Ни детектор (monitor/revise) сам forecasts под
закрытие/исход **не пишет** — только предлагает; запись здесь.
