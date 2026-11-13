# Архитектура весов сценариев и conditional forecasts — handoff в новый чат

**Дата составления:** 2026-05-08
**Репозиторий:** `/Users/you/Documents/personal-analytics-skills`
**Язык работы:** русский (везде — скиллы, коммиты, документация)

---

## Кто я и что делаю

Я работаю над коллекцией скиллов Claude Code для личных инвестиционных и прогнозных задач. Профиль читателя отчётов: 7 лет на рынке, мат-стат, не профи индустрии.

Основное хранилище артефактов — `Claude-Memory/` на Synology. Доступ через Read/Write/Edit (Synology mount; с миграции 2026-08-13 — единственный транспорт).

Приоритеты в проекте: **корректность > читаемость > стоимость > скорость**.

---

## Контекст: пайплайн прогнозов и стресс-тестов

### Текущая архитектура

```
scenario-builder ─→ 4 сценария Shell (по умолчанию p=0.25 каждому)
                       ↓
forecast-confidence-applier ─→ FCA на каждом факторе
                       ↓                  ↑
              использует веса        scenario-matrix
              для linear/modal       со ВЗВЕШЕННЫМИ
              трансляции             вероятностями
                       ↓
macro-forecast-chain ─→ macro-input-<date>.yaml
                       ↓             (ОДНО значение на фактор,
                                      веса уже встроены)
                       ↓
portfolio-scenario-stress ─→ точечный ΔP&L
```

### Ключевые скиллы

| Скилл | Роль |
|---|---|
| `scenario-builder` | Строит 4 равновероятных сценария Shell-методом по двум осям. Дефолт p=0.25. |
| `forecast-confidence-applier` (FCA) | Filtered consensus из 3–7 источников через trust-weighted median (`scripts/weighted_consensus.py`). |
| `macro-forecast-chain` | Оркестратор макропрогнозного DAG'а. Translation map (linear/nonlinear/axis_dependent/indifferent) в `references/dependency-map.md`. |
| `portfolio-scenario-stress` | Транслирует прогнозы в ΔP&L по позициям MOEX. |
| `save-to-library` | Единственная точка записи в `Claude-Memory/`. |

---

## Проблема, которую мы обнаружили

### 1. Веса сценариев — недокументированная магия

`scenario-builder` по дизайну выдаёт `0.25/0.25/0.25/0.25` ("нет базового мира" — принципиальная позиция Shell).

Но в реальном артефакте `scenarios/scenario-geopolitics-ru-west-2026-05-04.md` стоят веса `0.08/0.18/0.22/0.525` — **взялись из ниоткуда**, пользователь их не проставлял.

Расследование показало: это сделал **Claude в чате как полезный экспромт** во время цикла `macro-forecast-chain`. Логика:

1. Шаг 5.0 chain'а требует вероятностей для translation map (linear требует распределения, nonlinear — modal_probability, axis_dependent — axis_value)
2. Дефолт 0.25 даёт `WEAK_MODAL_GEOPOLITICS` alert (порог 0.40)
3. Чтобы пройти — Claude провёл FCA по двум осям (conflict, sanctions), извлёк EV (0.73 / 0.65), перемножил с поправкой на корреляцию, вписал результат

**Проверка математики:**
- Independent: P(D) = 0.73 × 0.65 = 0.4745
- В файле: P(D) = 0.525
- Разница +0.05 = положительная корреляция между осями (~0.1)

**Это не задокументировано ни в одном `SKILL.md`**, не воспроизводимо при перезапуске и не валидируется.

### 2. Прогнозы схлопывают условность сразу

Текущий `macro-forecast-chain` Шаг 5 встраивает веса в момент построения прогноза:
- `linear` → FCA на «взвешенном профиле 4 сценариев» → одно число с весами
- `nonlinear` → FCA условно на модальном → значение только для модала
- `axis_dependent` → используется `axis_value_used` = одно число (EV оси)

Поэтому **перекалибровка весов невозможна без перезапуска всех FCA на факторах**. Даже если веса сместились на 5 п.п., нужно гонять 10 прогнозов заново.

Это плохо при горизонте 20 месяцев: структурные предпосылки факторов меняются раз в полгода, а веры в сценарии — каждую неделю.

### 3. Существующие YAML-прогнозы — частично условные, но в разных форматах

Три файла, которые уже привязаны к scenario-matrix:

**`forecasts/ru-rates-2026-2027-2026-05-04.yaml`** (лучший):
```yaml
geopolitics_translation:
  method: linear
  distribution: { Sc-A: 0.08, Sc-B: 0.18, Sc-C: 0.22, Sc-D: 0.525 }
  scenario_rates_2026: { Sc-A: "10.5%", Sc-B: "12.5%", Sc-C: "11.5%", Sc-D: "13.5%" }
  scenario_rates_2027: { Sc-A: "8.0%", Sc-B: "10.5%", Sc-C: "9.5%", Sc-D: "11.5%" }
```
Все 4 сценария + 2 горизонта. Но значения — **строки с `%`**.

**`forecasts/cny-rub-dec2026-dec2027-2026-05-04.yaml`** (частично):
```yaml
geopolitics_translation:
  method: nonlinear
  modal_scenario_id: D
  modal_probability: 0.525
  alternatives:
    - { scenario_id: A, probability: 0.08, cny_rub_2026: "10.8–12.6", ... }
    - { scenario_id: B, ... }
    - { scenario_id: C, ... }
```
Только A/B/C в alternatives. **Sc-D отсутствует в структуре** — его «12.8–13.5» в `central_estimate` строкой. Значения — диапазоны-строки.

**`forecasts/ru-cpi-2026-2027-2026-05-04.yaml`** (хуже всех):
```yaml
geopolitics_translation:
  method: linear
  distribution_used: true   # просто флаг!
```
Условные значения CPI (4.4/7.0/6.0/7.75%) — **только в markdown-таблице**, в YAML их нет.

### 4. Несовместимости между файлами

- Разные имена полей: `scenario_rates_2026` vs `cny_rub_2026` vs ничего
- Разные scenario_id: `Sc-A` vs `A`
- Значения как строки: `"13.5%"`, `"10.8–12.6"`, `"~12.71%"` — каждое требует свой regex
- `Sc-D` для nonlinear в одном месте (top-level), для linear в другом (distribution)

Стресс-тест на 4 сценариях с такой схемой работать не может уверенно — для CPI пришлось бы вернуться к marginal значению (один точечный ответ), для CNY/RUB парсить диапазоны, для rates парсить проценты.

---

## Решение: унифицированная схема `conditional_on_scenarios`

### Принцип

**Прогнозы должны быть условными на сценарии, а не маргинальными.** Веса — отдельный, легко-перекалибрируемый слой. Агрегация (linear/nonlinear/...) делается в самом конце детерминированной функцией.

### Схема

```yaml
conditional_on_scenarios:
  source_matrix: "scenarios/scenario-geopolitics-ru-west-2026-05-04.yaml"
  scenario_id_format: short              # "A" вместо "Sc-A"
  by_scenario:
    A:
      probability: 0.08
      values:
        "2026-12-31": { central: 10.5, range: [10.0, 11.0] }
        "2027-12-31": { central: 8.0,  range: [7.5, 8.5] }
    B:
      probability: 0.18
      values:
        "2026-12-31": { central: 12.5, range: [12.0, 13.0] }
        "2027-12-31": { central: 10.5, range: [10.0, 11.0] }
    C:
      probability: 0.22
      values:
        "2026-12-31": { central: 11.5, range: [11.0, 12.0] }
        "2027-12-31": { central: 9.5,  range: [9.0, 10.0] }
    D:
      probability: 0.525
      values:
        "2026-12-31": { central: 13.5, range: [12.5, 14.0] }
        "2027-12-31": { central: 11.5, range: [10.5, 12.0] }
  marginal:
    method: linear                        # linear / nonlinear / axis_dependent / indifferent
    modal_scenario_id: D                  # для всех методов (нужен для tail-risk)
    values:
      "2026-12-31": { central: 12.71, range: [12.5, 13.0] }
      "2027-12-31": { central: 10.66, range: [10.0, 11.0] }
    unit: "%"                             # один раз для всего блока
```

### Ключевые свойства

- `by_scenario` **всегда содержит все 4 сценария** (включая D даже при nonlinear)
- Числа, не строки
- `unit` отдельным полем, не таскается в значениях
- `marginal` пересчитывается из `by_scenario` детерминированно функцией `weighted_consensus.py`
- `modal_scenario_id` есть всегда — нужен для tail-risk анализа в стресс-тесте

---

## Стресс-тест на 4 сценариях

### С унифицированной схемой — работает элегантно

```python
for scenario_id in ["A", "B", "C", "D"]:
    shocked_factors = {
        f.name: f.conditional_on_scenarios.by_scenario[scenario_id].values[horizon].central
        for f in macro_input.factors
    }
    pl_scenario = portfolio_pl(snapshot, shocked_factors)

E_pl = sum(p_i * pl_i for i in scenarios)
sigma_pl = sqrt(sum(p_i * (pl_i - E_pl)**2 for i in scenarios))
```

### Выход стресс-теста

| Сценарий | p | ΔP&L портфель | Главные драйверы |
|---|---|---|---|
| A «Дипломатический оазис» | 0.08 | +12% | Банки, IT (re-rating ↓ ставка) |
| B «Заморозка с рисками» | 0.18 | −4% | Нефтегаз страдает (Urals discount) |
| C «Военная экономика» | 0.22 | +6% | Нефтегаз бенефициар |
| D «Железный занавес-2» | 0.525 | −9% | FX-замайки выигрывают, ОФЗ распродажа |
| **E[ΔP&L]** | | **−3.2%** | |
| **σ** | | **8.1%** | |

Сразу даёт три вещи, которых нет в текущем точечном результате:
1. **Tail risk** — Sc-D даёт −9%, не средневзвешенные −3.2%
2. **Сценарная диверсификация** — какие позиции компенсируют друг друга
3. **Слабое звено** — высокая σ означает портфель сильно зависит от того, какой мир реализуется

### Что не должен делать стресс-тест

- **Не шокировать USD/RUB второй раз**, если pass-through уже встроен в conditional CPI (двойной счёт)
- **Не идти от scenario к `cbr_rate` напрямую** — он `indifferent` к осям, трансляция через CPI
- **Использовать `range` для P10/P90 портфеля**, не для дополнительных шоков

---

## План работы (минимальный)

### Шаг 1 (1–2 часа) — спецификация и миграция

**Цель:** появилась схема + один пример полной миграции.

- Дописать `_shared-references/events-yaml-spec.md` с разделом `conditional_on_scenarios`
- Написать миграционный скрипт `scripts/migrate_to_conditional.py`:
  - Читает существующий `forecasts/*.yaml` + соответствующий `*.md`
  - Парсит markdown-таблицы геополитической трансляции regex'ом
  - Извлекает per-scenario значения, нормализует scenario_id (`Sc-A` → `A`)
  - Парсит проценты и диапазоны в числа
  - Выдаёт унифицированный `conditional_on_scenarios` блок
- Прогон на трёх существующих файлах как валидация
- Ручная проверка `ru-cpi-2026-2027.yaml` (худший случай) — референсный пример

### Шаг 2 (1 день) — стресс-тест

**Цель:** стресс работает на 4 сценариях.

- Расширить `portfolio-scenario-stress` для потребления `conditional_on_scenarios.by_scenario`
- Выход: 4 ΔP&L + E[ΔP&L] + σ + декомпозиция драйверов
- Старый режим (`marginal.values.central`) остаётся fallback'ом для прогнозов без conditional-блока
- Тесты: на трёх существующих файлах после Шага 1

### Шаг 3 (½ дня) — joint weights без магии

**Цель:** уход от «магии в чате» при выводе весов сценариев.

- Функция `joint_from_axes(ev_x, ev_y, rho) -> [pA, pB, pC, pD]` в `weighted_consensus.py`
- Опциональное поле `correlation_xy` в `events-yaml-spec.md` для матриц сценариев
- Явный Шаг 5.5 в `scenario-builder/SKILL.md`: «Если на входе есть `for_chain: true` или `portfolio_context` — провести FCA по каждой оси и записать joint-вероятности»

### Шаг 4 (½ дня) — режим RECALIBRATE

**Цель:** месячная перекалибровка весов без LLM-вызовов.

- Режим `RECALIBRATE` в `macro-forecast-chain`:
  - Читает все `forecasts/*.yaml` с `conditional_on_scenarios`
  - Берёт новые веса из обновлённой scenario-matrix
  - Пересчитывает `marginal.values` детерминированно
  - Обновляет `macro-input-<date>.yaml`
  - Не делает LLM-вызовов
- Триггеры в `forecast-monitor`: пересборка только при структурной смене предпосылок (а не при движении весов)

---

## Желаемый месячный режим работы после миграции

```
По событию (Polymarket дёрнулся, пакет санкций принят):
  → FCA на двух осях scenario-matrix (3–7 источников × 2 оси) — минуты
  → joint_from_axes(ev_x, ev_y, rho) — секунды
  → новая scenario-matrix
  → macro-forecast-chain в режиме RECALIBRATE — секунды, без LLM
  → новый macro-input.yaml + новый стресс-тест

Раз в 3 месяца / при смене предпосылки конкретного мира:
  → перестроить тот фактор, у которого предпосылка структурно сместилась
  → один FCA-вызов с conditional-промптом
  → обновлённый conditional_on_scenarios для этого фактора
  → автоматический пересчёт marginal
```

10 прогнозов гонять с нуля **только при смене самих осей сценариев** (война кончилась, sanctions ось становится неактуальной).

---

## Открытые вопросы

1. **Разделение conditional vs structural updates.** Когда leading_indicator сценария трогается (`Polymarket > 50%`), это сигнал на пересчёт весов или на пересборку конкретного conditional-прогноза? Где провести границу?

2. **Корреляция между осями.** Закладывать в схему `correlation_xy` параметром (тогда нужно объяснять как его выводить) или оставлять joint считать вручную с явным комментарием?

3. **Mojibake в существующих YAML.** Все три файла прогнозов в `Claude-Memory/forecasts/` приходят с Latin-1 декодингом UTF-8 (русский текст не читается). На логику не влияет, но `revise-memory-remote` это пропустил — нужен тест на UTF-8 валидность.

4. **Кто пересчитывает `marginal`.** Скрипт-валидатор при загрузке forecast'а (eager), или явная команда `RECALIBRATE` (lazy)? Для согласованности данных eager надёжнее, для производительности — lazy.

5. **Range vs central в стресс-тесте.** Использовать `central` как точку или прогонять Monte Carlo внутри scenario через `range`? Второе даёт честный CI портфеля, но дороже.

---

## Ссылки на ключевые артефакты

### Существующие файлы (для миграции)

- `Claude-Memory/scenarios/scenario-geopolitics-ru-west-2026-05-04.{md,yaml}` — матрица сценариев с весами 0.08/0.18/0.22/0.525
- `Claude-Memory/forecasts/ru-rates-2026-2027-2026-05-04.{md,yaml}` — лучший YAML, все 4 сценария
- `Claude-Memory/forecasts/cny-rub-dec2026-dec2027-2026-05-04.{md,yaml}` — частичный YAML, nonlinear
- `Claude-Memory/forecasts/ru-cpi-2026-2027-2026-05-04.{md,yaml}` — худший YAML, только marginal

### Файлы для правки

- `_shared-references/events-yaml-spec.md` — добавить раздел `conditional_on_scenarios`
- `_shared-references/audit-frontmatter-schema.md` — обновить YAML frontmatter правила
- `skills/forecast-confidence-applier/scripts/weighted_consensus.py` — добавить `joint_from_axes()` и `aggregate_marginal()`
- `skills/macro-forecast-chain/SKILL.md` — добавить режим `RECALIBRATE` (Шаг 5)
- `skills/macro-forecast-chain/references/dependency-map.md` — обновить «Промпт-шаблоны для Шага 5» под conditional-формат
- `skills/portfolio-scenario-stress/SKILL.md` — переход с marginal на by_scenario
- `skills/scenario-builder/SKILL.md` — опциональный Шаг 5.5 (FCA по осям)

### Контекст репозитория

- `CLAUDE.md` (корень) — обзор архитектуры скиллов, тестов, конвенции
- `docs/investment/_cross-cutting/plan.md` — архитектурные решения
- `INTEGRATION-DOCS/00-MASTER-PLAN.md` — будущий Portfolio Integrated View

---

## Конкретное следующее действие

Начать с **Шага 1**: набросать спецификацию `conditional_on_scenarios` в `_shared-references/events-yaml-spec.md` + полную миграцию `ru-cpi-2026-2027.yaml` (худшего из трёх) вручную как референсный пример.

Это валидирует:
- Схема покрывает linear-случай (CPI)
- Можно извлечь данные из markdown-таблицы regex'ом
- Числовые значения консистентны (взвешенный marginal = `Σ p_i × by_scenario[i].central`)

После — параллельно прогон на `ru-rates` (linear, лучший YAML — должен пройти без markdown) и `cny-rub` (nonlinear, частичный YAML) для проверки покрытия всех методов.

---

## Критерий завершения миграции

Стресс-тест на портфеле выдаёт таблицу из 4 ΔP&L + E[ΔP&L] + σ, использует только `conditional_on_scenarios.by_scenario` (без парсинга строк, без fallback'ов на markdown), и **полная перекалибровка весов** через изменение scenario-matrix занимает меньше 5 минут без LLM-вызовов.
