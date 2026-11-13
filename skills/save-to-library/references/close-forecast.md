# Закрой прогноз — вход владельца «Закрой прогноз <тема> …»

Вход: `Закрой прогноз <тема>: на <дата горизонта> <факт>, прогноз <центр/диапазон> — сбылся | не сбылся` (дословная фраза `suggested_action` монитора, `forecast-monitor/references/horizon-passed.md`), либо «закрой с исходом». Ретро-аудита нет: закрытие по факту, роли F7 — `references/status-management.md`.

1. **Найти активные файлы темы.** `forecasts/<тема>-*.yaml` и парные `scenarios/scenario-<тема>-*.yaml` (тема = имя без префикса `scenario-` и без хвоста-даты). Берётся последняя версия со `status: active`; `superseded`/`resolved`/`expired` не трогать. Нет активного файла — остановиться и сказать. Пара `.md` ↔ `.yaml` остаётся парой: `.md` не меняется.
2. **Факт и источник.** Факт — из фразы; источник (URL/документ) обязателен. Нет источника — спросить владельца либо предложить `web_search` и дождаться подтверждения найденного. Факта нет вообще — не закрывать.
3. **Вердикт.** «Сбылся» — факт внутри диапазона/на центре прогноза (`p10_p90`, иначе заявленный диапазон `central_estimate`); иначе «не сбылся». Фраза владельца и расчёт расходятся — показать оба и спросить.
4. **Показать и ждать «да».** Одним блоком: файлы, факт, источник, дата горизонта, вердикт, что запишется (outcome_log, статус, final_audit, INDEX, `_sync_log`). Без «да» ничего не писать.
5. **Прогноз.** `freeze-outcome-log` из `fca_stats` (`record_type: horizon_resolve`, `resolve_date` = горизонт) → дозаполнить `actual` (level) / `resolved` (event) / `actual_source` → `complete-outcome-log` (`blocking_count > 0` — показать, не писать; в файл идёт только вывод помощника — `references/events-yaml-spec.md` §14.4). Нет `fca_stats` — запись из наличных полей, `forecast_l1_weighted` = числовой центр прогноза из фразы (без него level-резолв с фактом blocking). Затем:
   ```yaml
   status: resolved
   final_audit:
     due: {горизонт}
     status: done
     completed: {сегодня}
     closed_by: owner_close
     audit_file: null
     result: "hit | miss — факт, источник, оговорка"
   ```
   Прогнать `validate-forecast-events` + `check-yaml-duplicates` на итоговом файле; blocking — откат. Править Edit'ом точечно.
6. **Сценарная матрица пары.** У сценариев нет `outcome_log`: `status: resolved` и `final_audit` в том же формате плюс `realized_scenario` (ближайший квадрант или `none`) и `prior_probability` его веса. Вес из `scenario_triggers[*].probability` не менять.
7. **INDEX + `_sync_log`.** `forecasts/INDEX.md` и `scenarios/INDEX.md`: статус строк `.md`/`.yaml` → `resolved`, вердикт в описании; строка в таблице «Завершённые прогнозы (resolved)». Одна строка в `_sync_log.md`: файлы, факт, источник, вердикт.

`final_audit.closed_by`: `owner_close` (закрытие по факту, без ретро-аудита) | `retro_audit`. `resolved` + `owner_close` без записи `horizon_resolve` с фактом — blocking в `validate-forecast-events`.
