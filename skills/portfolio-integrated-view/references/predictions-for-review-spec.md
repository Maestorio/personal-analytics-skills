# predictions_for_review — формат R7 блока

Каждый запуск integrated-view создаёт блок с предсказаниями для проверки
через 6 месяцев. Это база для retrospective-forecast-audit и для
калибровки catalyst.p в v2.

---

## Цель

Зафиксировать **проверяемые** числовые предсказания на конкретную дату
с источником, где можно увидеть realised value. Без этого блока integrated-view
накапливает phantom precision: красивые числа без обратной связи.

---

## Формат

Минимум **5 предсказаний** на запуск. Каждое — строка таблицы:

| Поле | Тип | Описание |
|---|---|---|
| `id` | string | unique slug — `{ticker}_{metric}` или `{theme}_{metric}` |
| `predicted` | number + CI | то, что предсказано на target_date |
| `target_date` | ISO date | когда проверять (по умолчанию: today + 6mo) |
| `what_to_check` | string | конкретная метрика и где её взять |
| `source` | string | первичный источник (e-disclosure, IR releases, CBR, MOEX) |
| `category` | enum | `portfolio_aggregate / position_dividend / catalyst_fired / scenario_realized / spread` |

---

## Обязательные категории

Из 5+ предсказаний должны быть представлены **все** категории:

### 1. portfolio_aggregate (≥1)
Агрегированный показатель всего портфеля.

```
id: eq_vs_bond_spread_20mo
predicted: -7.1pp [-10; +25]
target_date: 2026-11-04
what_to_check: реализованный spread (equity XIRR vs bond YTM aggregate)
source: portfolio-data-loader выгрузка на target_date
category: portfolio_aggregate
```

### 2. position_dividend (≥1)
Дивиденд по конкретной позиции — самый легко-проверяемый.

```
id: sber_dividend_2025
predicted: 11.5% [9; 13]
target_date: 2026-07-15  # после ГОСА
what_to_check: объявленный дивиденд за 2025 как % от цены на 2025-12-31
source: e-disclosure SBER ГОСА решение
category: position_dividend
```

### 3. catalyst_fired (≥2)
Сработал ли конкретный catalyst из weekly-review.

```
id: ozon_ebitda_positive_p
predicted: 0.5  # joint P из catalyst в review
target_date: 2026-11-15  # после Q3-26 МСФО
what_to_check: Q3-26 МСФО показал ли EBITDA-positive
source: OZON IR releases
category: catalyst_fired
```

### 4. scenario_realized (≥1)
Какой scenario из stress оказался ближе всего к реальности.

```
id: stress_realized_scenario
predicted: D (p=0.525)    # abstract scenario_id; конкретная семантика — из SSOT scenarios YAML
target_date: 2026-11-04
what_to_check: какой scenario наиболее похож по факторам (sanctions, rate, FX, oil)
source: macro-ru-watcher snapshots на target_date
category: scenario_realized
```

---

## Где сохраняется

В самом integrated-view markdown как Section 10. Когда `save-to-library`
сохранит файл в `Portfolio/integrated-views/`, retrospective-forecast-audit
через 6 мес найдёт этот файл по `target_date` и проверит каждую строку.

**Файл также не пишется отдельно** — predictions inline в markdown,
парсятся при retro audit'е через regex/yaml-block внутри markdown.

---

## Anti-patterns

1. **«Будет хорошо»** — нет числа, не проверяемо.
2. **«SBER вырастет»** — нет timeframe и величины.
3. **target_date в открытом будущем (10 лет)** — слишком далеко, не проверится.
4. **5 предсказаний из одной категории** — bias в калибровке.
5. **Источник «по моим расчётам»** — должен быть external verifiable source.

---

## Пример минимального блока

```markdown
## 🔮 Section 10: predictions_for_review (R7)

Через 6 мес (target date: 2026-11-04) проверить:

| ID | Predicted | Target | What to check | Source | Category |
|---|---|---|---|---|---|
| eq_vs_bond_spread_20mo | -7.1pp [-10; +25] | 2026-11-04 | spread между equity XIRR и bond YTM aggregate | portfolio-data-loader | portfolio_aggregate |
| sber_div_2025 | 11.5% [9; 13] | 2026-07-15 | объявленный дивиденд за 2025 | e-disclosure ГОСА | position_dividend |
| sber_rate_cut_re_rating | P_joint=0.315 | 2026-11-04 | rate cut произошёл и SBER цена выросла | CBR + MOEX | catalyst_fired |
| ozon_ebitda_positive | P_joint=0.35 | 2026-11-15 | Q3-26 МСФО EBITDA > 0 | OZON IR | catalyst_fired |
| stress_scenario_realized | D | 2026-11-04 | какой stress scenario ближе всего | macro-ru-watcher | scenario_realized |
```

---

## Связь с retrospective-forecast-audit

Через 6 мес скилл `retrospective-forecast-audit` читает все
`integrated-view-*.md` где `target_date ≤ today` и:
1. Извлекает predictions_for_review таблицу
2. Для каждого ID проверяет realised value
3. Считает hit-rate / Brier score per category
4. Выдаёт calibration report для v2-C upgrade синтезатора
