# fill.yaml и сборка итогового stress-YAML (Шаг 6.0)

Итоговый файл собирает `scripts/stress_build.py`. Расчётные блоки не проходят через ответ модели;
модель пишет только `fill.yaml` — поля суждения.

## Порядок

1. Чувствительности `betas-priors.json` и вход факторов `horizon-factors-input.json` (Шаг 3.6).
2. `stress_build.py` без `--fill` → рабочий файл с числами (`numbers_only: true`) и сводка в выводе.
3. По числам — текст отчёта и `fill.yaml`.
4. `stress_build.py` с `--fill` и `--output` в `_drafts/` → итоговый файл (команды — в SKILL.md, Шаги 3.6.4 и 6.0).

## Источники ключей

| Ключ итогового файла | Источник |
|---|---|
| метаданные (`schema_version` … `review_date`), `date` и `run_id` (дата прогона), контракт баз (`basis_contract`, `layers_included`, `per_position_basis`, `base_value_rub`, `base_value_note`, `p_basis`), `macro_input`, `baseline_spot`, `factor_definitions` | скрипт |
| `horizons`, `horizon_ends`, `primary_horizon`, `horizon_mode` | файл сроков сайта `scenarios/horizons.json` (при `--library-root`; автосдвига нет), иначе `--horizons-from` (прошлый стресс; до ближайшего срока меньше 3 месяцев — все сроки сдвигаются на 6 месяцев) либо `--horizons` / `--anchor-dates` |
| `scenarios.<X>.name` | матрица `--scenarios` |
| `scenarios.<X>.p`, `.p_by_horizon` | веса сайта (`--library-root` / `--weights-json`), если заданы на те же сроки; иначе матрица |
| `scenarios.<X>.factors_by_horizon`: числовые факторы и `horizon_coverage` | сетка дат `--macro-scenarios` (вход не из макро-цепочки — `--horizon-factors-input` или готовый `--horizon-factors`) |
| `scenarios.<X>.factors_by_horizon.<hNN>.{sanctions, geopol}` | `--political-from` (прошлый стресс как есть) либо `--political-paths` |
| `per_position`, `unmapped_tickers` | скрипт |
| `per_position.<тикер>.{factor_betas, factor_betas_method, factor_betas_r2, asset_type}` | по старшинству: `references/fixed-priors.yaml` → `--priors` (новые и пересмотренные) → `--priors-from` (прошлый стресс) |
| `per_position.<тикер>.sanctions_position` | `references/sanctions-positions.yaml`; бумаги вне справочника — из входа |
| `bond_carry` (с `overrides` из `--carry-overrides`), `scenarios.<X>.portfolio_level_by_horizon`, `portfolio_aggregates`, `robustness.price`, `robustness.total_return` | скрипт |
| `cash_rub_pct`, `blocked_pct`, `blocked_rub_memo`, `weight_base_note`, `sector_breakdown_pct`, `sector_breakdown_basis`, `top_risks`, `top_resilient`, `concentration_ratio`, `concentration.{same_direction_pct, opposite_pct, neutral_pct, same_direction_incl_cnyrub_pct}` | скрипт |
| `scenario_matrix_ref` | имя файла `--scenarios`, если fill не задал своё |
| `robustness.hedge_target`; `robustness.modal_scenario` (при вероятностных весах: `none` под `modal_flag: no_modal`, иначе id модального сценария; при равных весах `none` ставит скрипт) | fill |
| `macro_blindspots`, `caveats`, `dominant_factor`, `concentration.{dominant_factor, note}`, `hedge_candidates`, `forecast_type`, `scenario_source`, `modal_flag`, `horizon_label_note`, `*_note`, `method`, `notes` | fill |

## Правила fill

- fill несёт только поля суждения. Ключ из строк «скрипт» таблицы выше, а также `priors`, `carry`, `_drop` — отказ с перечнем ключей.
- В `robustness` допустимы только `hedge_target` и `modal_scenario`; в `concentration` — только `dominant_factor` и `note`.
- `concentration.dominant_factor` — фактор, по которому скрипт считает концентрацию; без него концентрация не считается.
- Плейсхолдер `TODO_LLM` в fill — отказ.
- `weight_type` в fill сильнее флага `--weight-type`.

## Пример fill.yaml (значения условные)

```yaml
dominant_factor: sanctions
concentration:
  dominant_factor: sanctions
  note: "без кэша; фонды денежного рынка — нейтральные"
macro_blindspots: []
caveats:
  - {severity: HIGH, type: methodology, message: "factor_betas — секторальные priors, не регрессия; CI — placeholder"}
robustness:
  hedge_target: "A — единственный сценарий с отрицательным ценовым ΔP&L"
  modal_scenario: C
forecast_type: D
method: "priors-only, Phase 4.1"
```

## Отказы (код 1, файл не пишется, текст — на stderr)

| Причина | Текст |
|---|---|
| у бумаги снапшота нет чувствительности | `у бумаг снапшота нет чувствительностей в --priors (тикер — название — доля):` + перечень |
| ошибка контракта priors (форма, нечисловые беты, шкала политических бет, `sanctions_position`) | текст гарда `compute_per_position` одним списком |
| fill несёт посчитанное или недопустимое | `fill трогает посчитанное или недопустимое (fill несёт только поля суждения):` + ключи |
| в fill остался плейсхолдер | `в fill остался TODO_LLM:` + пути |
| нет слота суждения | `в fill нет robustness.hedge_target` (или `.modal_scenario`) |
| в матрице нет вероятностей / нет `baseline_spot` | `в --scenarios нет scenario_triggers с вероятностями` / `нужен --macro-scenarios с baseline_spot` |
| файл макро-сценариев не годится для расчёта | перечень строк «фактор — сценарий — что не так» (нет фактора, сценария, числового `value`, спота) |
| политические факторы: нет источника, заданы оба, сценарии или сроки не совпали, значение вне [-1, 1] | текст с `--political-from` / `--political-paths` и перечнем расхождений |
| сценарии факторов и матрицы расходятся | `сценарии факторов … не совпадают со сценариями матрицы …` |
| сроки факторов и прогона расходятся | `суждения невалидны:` + строки `горизонты … не совпадают с horizon_ends …` |
| `--horizons-from` вместе с `--horizons` / `--anchor-dates`, или в прошлом файле нет `horizon_ends` | `--horizons-from нельзя сочетать …` / `--horizons-from: в <файл> нет horizon_ends …` |
| матрица сценариев сменилась: файл макро-цепочки или прошлый стресс (`--political-from`) ссылаются на другую матрицу | `матрица сценариев сменилась:` + что пересобрать (макро-прогноз на новой матрице; пути sanctions/geopol — заново файлом `--political-paths`) |
| блокер валидатора контракта баз | `валидатор: блокеров N, файл не записан:` + коды |

Предупреждения (код 0, в сводке): файл весов сайта задан на другие сроки или не читается — посчитано на весах матрицы; priors на бумаги вне снапшота — в файл не попали; ключи priors вне контракта проигнорированы.
Код 2 — ошибка вызова или вход не читается. С `--json` сводка печатается машинно.

Оговорка о покрытии сроков: для каждого срока со статусом не `covered` скрипт (`stress_recalc.script_caveats`) сам добавляет в конец `caveats` запись `HORIZON_EXTRAPOLATED` (`source: script`, `horizon`, числа и даты из `horizon_coverage`). Записи `H<N>_EXTRAPOLATED` / `HORIZON_EXTRAPOLATED` из fill и прежние записи скрипта при сборке и пересчёте отбрасываются (в выжимке — предупреждение); в режиме «только числа» запись не добавляется. Модель такую оговорку не пишет.

Вклад факторов: в выжимке и в `--tables` (блок «Вклад факторов») команда печатает вклад каждого фактора на основном сроке (ценовой слой, п.п. по сценариям и в ожидание, взвешенный |вклад|) и пробы «рубль = 0» (usdrub+cnyrub), «золото = 0» (xauusd) — повторные `recalc` с обнулёнными факторами; в YAML стресса эти числа не пишутся. Работает и в режиме «только числа» — по ним модель пишет суждения.
