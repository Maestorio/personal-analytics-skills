# Skill: portfolio-data-loader

## Summary
Самый «инженерный» скилл: 3 регрессионных теста (`test_per_security_xirr.py`, `test_splits_and_corrections.py`, `test_fx_bond_valuation.py`) зелёные, JSON snapshot `portfolio-2026-05-05.json` соответствует `_shared-references/yaml-schemas.md §6` (`schema_version: "2.0"`). XIRR/TWR/ROI считают только скрипты, не LLM. Главные риски: (1) `KNOWN_SPLITS` — ручной список, пропуск нового сплита приведёт к ошибочной `avg_cost_rub`; (2) скилл сам пишет в `Portfolio/snapshots/` — формальное противоречие с `claude-memory-layout.md:68`, где написано «пишет save-to-library»; (3) хрупкая конвенция «XIRR хранится как процент, downstream должен делить на 100».

## Correctness (P1)
- [d3-tension] ✅ РЕШЕНО (2026-06). По факту `claude-memory-layout.md` (стр. 76 + 93–110) и `CLAUDE.md` (стр. 171) корректно фиксируют исключение D3 (loader пишет `Portfolio/snapshots/` напрямую). Реальное противоречие было только в `SKILL.md` Outputs («save-to-library пишет»), из-за чего скилл после сборки молча останавливался и ждал команды «сохрани». Исправлено: Outputs + Шаг 7 теперь однозначно — loader **сам** пишет снапшот (исключение D3), но **проактивно спрашивает разрешение** сразу после сборки (Шаг 6), а не ждёт отдельной команды.
- [convention-debt] `KNOWN_SPLITS` (`portfolio_returns.py:131–167`) — 4 сплита (T 1:10, PLZL 1:10, GMKN 1:100, TRNFP 1:100). Пропуск нового сплита => `avg_cost_rub` посчитается неверно.
  - Эффект: ROI/XIRR ошибочны, downstream Stock Quality Forward Review даст плохие рекомендации.
  - Fix sketch: добавить MOEX ISS запрос за corp-events с автоматическим обнаружением; либо как минимум alert «обнаружено резкое изменение цены при отсутствии записи в KNOWN_SPLITS — проверить».
- [silent-conversion] `xirr_pct/100` — корректно сделано в `assemble_snapshot.py:386`, но scripts хранят XIRR как процент (23.37, не 0.2337). Любой downstream обязан помнить эту конвенцию (`SKILL.md:172` предупреждает). Хрупко при появлении нового консумера.
  - Fix sketch: либо унифицировать на доли (0.2337) во всех скриптах, либо ввести явное имя поля `xirr_pct` (на всех уровнях) и валидацию диапазона в downstream.

## Readability (P2)
- Quirks-таблица (`SKILL.md:253–262`) — самое ценное место в скилле, лежит в самом конце. Поднять выше или вынести в `references/quirks.md`.
- Шаг 0 (Transport) ссылается на `references/transport-layer.md` — это корректное поведение через `pack.sh`, не пропавший файл.
- 5 скриптов с разной зоной ответственности (parse / returns / per-security / quotes / iis-shortlist) — связи между ними расписаны в `SKILL.md` Шагах 1–6, но без диаграммы. Стоит добавить «scripts dependency tree» в начало.

## Cost (P3)
- numbers-parser + openpyxl + scipy — приемлемые dependencies.
- ЦБ РФ курсы кэшируются (`cbr_rates_bundled.json` в `references/`) — экономно.
- MOEX ISS — батчи по 10 SECID, без лишних запросов.

## Speed (P4)
- Numbers-parser ~5–10 сек; полный snapshot ~30 сек на портфеле ~100 позиций. Приемлемо.

## Cross-skill / contract
- Downstream: `ru-portfolio-advisor`, `portfolio-scenario-stress`, `macro-forecast-chain`, `portfolio-integrated-view` — все читают `Portfolio/snapshots/portfolio-{date}.json`.
- Schema v2.0 additive (новые поля `ie_model`, `ie_actual`, `ie_summary`, `balance_summary.by_account`) — backward-compatible.
- Тесты согласно `CLAUDE.md` зелёные; валидация ≤0.25 п.п. vs IntelInvest на 9 бумагах.
- `SKILL.md:157` запрещает вызывать `merge_cross_currency_positions` и `apply_known_splits` снаружи — корректное выделение приватного API.

## Verified against artifact
- `~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/Portfolio/snapshots/portfolio-2026-05-05.json`:
  - `schema_version: "2.0"`, `as_of_date: "2026-05-05"`, `generated_at`, `input_files` ✓
  - `holdings[*]`: ticker, isin, qty, avg_cost_rub, current_price, current_price_source, value_rub, currency, asset_type, account, is_blocked, ytm_pct (где применимо) ✓
  - Все required-поля §6 присутствуют.
  - `KNOWN_SPLITS` применённые: GMKN, T, PLZL, TRNFP — даты сверены с moex-исторической ценой.
