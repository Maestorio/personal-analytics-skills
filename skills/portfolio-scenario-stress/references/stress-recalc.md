# stress_recalc.py — пересчёт чисел без модели

Берёт суждения из готового стресс-файла скилла и прогоняет те же расчётные функции на новом снапшоте и/или весах сценариев. Новых формул нет: `compute_per_position` → `compute_bond_carry` → `compute_portfolio_aggregates` → `assemble_stress.assemble`.

```
python3 scripts/stress_recalc.py (--stress STRESS.yaml | --judgments СУЖДЕНИЯ.yaml) --snapshot portfolio-ДАТА.json \
    [--weights scenarios/МАТРИЦА.yaml] --output OUT.yaml [--today YYYY-MM-DD] [--at ISO] [--json]
```

Коды: 0 — посчитано; 1 — отказ (нет входа, невалидный файл суждений, блокер валидатора, `--output` = `--stress`/`--judgments`); 2 — ошибка вызова (в т.ч. `--stress` и `--judgments` вместе или ни одного).

## Откуда входы

- Бумаги: `per_position[t].{factor_betas, factor_betas_method, factor_betas_r2, sanctions_position}` — как priors, режим `priors` (сеть не нужна).
- Сценарии: `name`, `factors_by_horizon`, `p`, `p_by_horizon`; плюс `horizon_ends`, `horizon_coverage` (CI-инфляция), `weight_type`.
- Купонный слой: `bond_carry.params` и `bond_carry.baseline_cbr_rate_pct`. Переопределения по бумагам (например floater) хранятся в `bond_carry.overrides` и применяются при пересчёте; нет ключа — расчёт без них.
- Раскрытие ожидаемого P&L (`--include-ev`) — по тому, заполнено ли оно в исходном файле.
- Поля суждения (`top_risks`, `macro_blindspots`, `caveats`, `sector_breakdown_pct`, `robustness.hedge_target`/`modal_scenario` и остальной fill) переносятся как есть.
- `--weights-json`: файл `stress-weights@1` (`{"schema", "horizon_ends", "weights": {hNN: {сценарий: вес}}}`, прочие ключи — данные сайта, не читаются). `horizon_ends` файла обязаны равняться `horizon_ends` стресса (метки и даты), иначе отказ «веса нужно пересмотреть»; так же отказ при чужом наборе сценариев, весе вне [0, 1], сумме на горизонте ≠ 1 (допуск 1e-6) или пропущенном горизонте. `p_by_horizon` = веса файла, `p` = вес на `primary_horizon`. Веса, равные весам стресса, причиной пересчёта не считаются.

## Файл суждений (`stress-judgments@1`)

Небольшой YAML с тем, что назначает модель и что не выводится из снапшота и весов; числа по нему считает `stress_recalc.py --judgments`. Путь расчёта общий: полный файл (`--stress`) тоже приводится к этой структуре через `stress_judgments.extract`, результат `--stress` и `--judgments` на одном снапшоте совпадает (кроме `recalc.source_stress`, `recalc.source_kind`).

Ключи: `schema`, `date`, `slug`, `source_snapshot_id`, `source_run_id`; `meta` (нерасчётные метаданные стаба: `horizon_ends`, `primary_horizon`, `weight_type`, `baseline_spot`, `factor_definitions`, `basis_contract`, `layers_included`, `scenario_matrix_ref`, `include_ev` и др.); `scenarios` (`name`, `p`, `p_by_horizon`, `factors_by_horizon`); `horizon_coverage`; `priors` (по бумаге `factor_betas` со всеми каноническими факторами, `factor_betas_method`, `factor_betas_r2`, `sanctions_position`); `known_unmapped_tickers`; `carry` (`params`, `baseline_cbr_rate_pct`); `narrative` (весь текст суждения, `robustness.{hedge_target, modal_scenario}` и числа fill, привязанные к снапшоту: `cash_rub_pct`, `blocked_pct`, `blocked_rub_memo`, `sector_breakdown_pct`, `concentration_ratio`).

Не входит: `per_position.*.{by_horizon, weight_pct, on_iis}`, `unmapped_tickers`, `bond_carry`, `portfolio_aggregates`, `scenarios.*.portfolio_level_by_horizon`, `robustness.{price, total_return}`, `base_value_rub`, `portfolio_snapshot_id`, `run_id`.

```
python3 scripts/stress_judgments.py extract  --stress ПОЛНЫЙ.yaml --output СУЖДЕНИЯ.yaml
python3 scripts/stress_judgments.py validate --file СУЖДЕНИЯ.yaml
```

`validate` проверяет обязательные ключи и `schema`, полноту канонических факторов у каждой бумаги, согласованность сценариев и горизонтов (`horizon_ends`, `p_by_horizon`, `factors_by_horizon`, `horizon_coverage`) и отсутствие посчитанных блоков. Коды: 0 — ок, 1 — ошибки/отказ (`--output` = `--stress`), 2 — ошибка вызова. Запись атомарная. В `dropped` вес выбывшей бумаги (`weight_pct`) известен только при входе `--stress`; из суждений он `null`.

## Блок `recalc`

`source_stress` (имя исходного файла: стресса или суждений), `source_kind` (`stress` | `judgments`), `source_snapshot_id`, `snapshot_id`, `weights_set_at`, `weights_source` (`stress` | `stress-weights:<файл>`), `reason` (`snapshot` | `weights` | `both` | `macro` | `none`), `macro_input`, `macro_input_was` (только при `--macro-scenarios`), `at`, `narrative_stale` (true, если изменился снапшот или веса), `stale_numeric_fill_fields` (числовые поля fill, привязанные к снапшоту, при смене снапшота), `needs_judgment`, `dropped`, `notes`, `validator_open`.

- `needs_judgment` — бумаги снапшота без чувствительностей (тикер, название, доля): в расчёт не входят. Блокеры покрытия валидатора (3.13) при этом не гасятся, а записываются в `validator_open`; остальные блокеры дают отказ.
- `dropped` — бумаги стресс-файла, которых нет в снапшоте.
- `--macro-scenarios МАКРО.yaml` — подстановка новой макро-таблицы. Числовые факторы сценариев (brent, usdrub, cnyrub, cbr_rate, xauusd), `baseline_spot`, `horizon_coverage` и уровень КС купонного слоя пересчитываются по сетке дат макро-файла на сроки источника (`as_of` — `--today`) тем же кодом, что в режиме «из макро-файла» у `stress_build.py`; `sanctions` и `geopol` остаются из источника. Числа равны результату `stress_build.py` с тем же макро-файлом, суждениями, сроками и `--today`. Отказ (код 1, одним списком): макро-файл не проходит `validate_macro` или собран на другой матрице, чем стресс. В `recalc` пишутся `macro_input` (новый) и `macro_input_was` (прежний), `narrative_stale: true`, `reason` — `macro`, если нет другой причины (снапшот или веса).
- `date`, `portfolio_snapshot_id`, `base_value_rub` — новые; `run_id` с префиксом `RECALC-`.

## Чего скрипт не делает

Не назначает чувствительности и позицию на санкционной шкале новым бумагам; не обновляет текст и числа внутри fill; не меняет факторы сценариев и веса вне `--weights`; не пишет в путь исходного стресс-файла.
