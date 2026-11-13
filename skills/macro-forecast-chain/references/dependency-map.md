# Dependency Map — macro-forecast-chain

## DAG зависимостей (порядок запуска)

Факторы строятся строго в этом порядке. Downstream-прогноз ВСЕГДА
запускается после upstream. Если upstream MISSING и не запланирован
к запуску в текущем run — фиксировать как caveat.

```
Level 0 (корни — нет зависимостей):
  geopolitics

Level 1 (зависят только от Level 0):
  sanctions          ← geopolitics

Level 2:
  brent              ← geopolitics, sanctions
  budget_deficit     ← sanctions, brent

Level 3:
  urals_discount     ← sanctions, brent
  usdrub             ← brent, sanctions
  xauusd             ← geopolitics, usdrub   (золото — частично safe-haven)

Level 4:
  cnyrub             ← usdrub
  inflation_ru       ← usdrub, budget_deficit

Level 5:
  cbr_rate           ← inflation_ru

Level 6 (секторальные — запускаются последними):
  sector_oil_gas     ← brent, urals_discount, usdrub, sanctions
  sector_banks       ← cbr_rate, inflation_ru
  sector_metals      ← usdrub, sanctions, geopolitics
  sector_realty      ← cbr_rate, inflation_ru
  sector_it          ← usdrub, sanctions
  sector_gold_funds  ← xauusd, usdrub
  sector_bonds_rub   ← cbr_rate, inflation_ru, budget_deficit
  sector_bonds_fx    ← usdrub, cnyrub, sanctions
```

---

## Upstream-контекст для каждого фактора

### geopolitics
```
Скилл: scenario-builder
Upstream: нет
Горизонты: 2026-12-31 и 2027-12-31
Примечание: давать как Shell 2×2 матрицу, не как единственный прогноз
```

### sanctions
```
Скилл: forecast-confidence-applier
Upstream-контекст:
  - geopolitics: {central_estimate} (confidence {X})
Промпт-блок:
  «Контекст: геополитический сценарий — {geopolitics.central_estimate}.
   При каком именно развитии этого сценария ожидается ужесточение санкций?
   При каком — ослабление?»
```

### brent
```
Скилл: forecast-confidence-applier
Upstream-контекст:
  - geopolitics: {central_estimate}
  - sanctions: {central_estimate}
Промпт-блок:
  «Контекст: геополитика — {geopolitics.central_estimate};
   санкционный режим — {sanctions.central_estimate}.
   Как эти факторы влияют на твой прогноз нефти? Укажи явно.»
```

### budget_deficit
```
Скилл: forecast-confidence-applier
Upstream-контекст:
  - brent: {central_estimate}
  - sanctions: {central_estimate}
Промпт-блок:
  «Контекст: Brent — {brent.central_estimate};
   санкционный режим — {sanctions.central_estimate}.
   Как изменятся нефтегазовые доходы бюджета РФ при этих параметрах?»
```

### urals_discount
```
Скилл: forecast-confidence-applier
Upstream-контекст:
  - brent: {central_estimate}
  - sanctions: {central_estimate}
Промпт-блок:
  «Контекст: Brent — {brent.central_estimate};
   санкционный режим — {sanctions.central_estimate}.
   Как это повлияет на дисконт Urals к Brent?»
```

### usdrub
```
Скилл: forecast-confidence-applier
Upstream-контекст:
  - brent: {central_estimate}
  - sanctions: {central_estimate}
  - budget_deficit: {central_estimate} (если есть)
Промпт-блок:
  «Контекст: Brent — {brent.central_estimate};
   санкционный режим — {sanctions.central_estimate};
   бюджетный дефицит — {budget_deficit.central_estimate}.
   Чувствительность: при отклонении Brent на ±15% — как меняется USD/RUB?»
```

### xauusd
```
Скилл: forecast-confidence-applier
Upstream-контекст:
  - geopolitics: {central_estimate}
  - usdrub: {central_estimate}
Промпт-блок:
  «Контекст: геополитика — {geopolitics.central_estimate};
   USD/RUB — {usdrub.central_estimate}.
   Safe-haven спрос на золото при данном геополитическом сценарии?»
```

### cnyrub
```
Скилл: forecast-confidence-applier
Upstream-контекст:
  - usdrub: {central_estimate}
Промпт-блок:
  «Контекст: USD/RUB — {usdrub.central_estimate}.
   Кросс-курс CNY/RUB через USD/CNY. Дополнительно учти торговые
   потоки РФ–Китай при текущем санкционном режиме.»
```

### inflation_ru
```
Скилл: forecast-confidence-applier
Upstream-контекст:
  - usdrub: {central_estimate}
  - budget_deficit: {central_estimate}
Промпт-блок:
  «Контекст: USD/RUB — {usdrub.central_estimate} (инфляционное давление
   через импорт); бюджетный дефицит — {budget_deficit.central_estimate}
   (монетарная эмиссия).
   Чувствительность: при курсе USD/RUB выше 95 — на сколько п.п.
   ускоряется инфляция?»
```

### cbr_rate
```
Скилл: forecast-confidence-applier
Upstream-контекст:
  - inflation_ru: {central_estimate}
Промпт-блок:
  «Контекст: прогноз инфляции РФ — {inflation_ru.central_estimate}.
   Использовать этот прогноз как baseline для траектории ставки ЦБ.
   Горизонты: ближайшие 2 заседания + 2026-12-31 + 2027-12-31.
   Чувствительность: при отклонении инфляции на ±1.5 п.п. —
   на сколько б.п. сдвинется ставка?»
```

### Секторальные прогнозы

Запускаются только если соответствующий сектор есть в портфеле
(определяется по sector-factor-matrix.md).

Каждый — через `forecast-confidence-applier` с полным upstream-контекстом
из соответствующих факторов. Промпты — формировать аналогично выше.

Секторальные прогнозы сохраняются в `Claude-Memory/forecasts/`
с topic-slug: `sector-oil-gas`, `sector-banks`, `sector-metals` и т.д.

---

## Топик-слаги для topic field в YAML

`topic у файлов` — значение поля `topic` в уже сохранённых прогнозах; по нему выбирается прогноз фактора
(Шаг 2.2) и вьюер восстанавливает состав стресс-теста у макро-входа без `source_files`. Новый прогноз
сохраняется с тем же `topic`, что у файлов фактора.

| Фактор | topic slug | topic у файлов |
|--------|-----------|----------------|
| geopolitics | `geopolitics-ru-west` | `geopolitics-ru-west` |
| sanctions | `sanctions-ru` | `sanctions-russia-2026-28` |
| brent | `brent-price` | `brent-price` |
| urals_discount | `urals-discount` | `urals-brent-discount` |
| usdrub | `usdrub-rate` | `usdrub-rate` |
| cnyrub | `cnyrub-rate` | `cnyrub-rate` |
| xauusd | `xauusd-price` | `xauusd-price` |
| inflation_ru | `inflation-ru` | `inflation-ru` |
| cbr_rate | `cbr-rate` | `cbr-rate-2026-2027` |
| budget_deficit | `budget-deficit-ru` | `budget-deficit-ru` |
| sector_oil_gas | `sector-oil-gas` | — |
| sector_banks | `sector-banks` | — |
| sector_metals | `sector-metals` | — |
| sector_bonds_rub | `sector-bonds-rub` | — |
| sector_bonds_fx | `sector-bonds-fx` | — |
| sector_it | `sector-it-ru` | — |
| sector_realty | `sector-realty` | — |
| sector_gold_funds | `sector-gold-funds` | — |

---

## Маппинг factor → portfolio-scenario-stress

При сборке macro_input.yaml факторы конвертируются в формат PSS:

| Фактор | PSS-поле | Трансформация |
|--------|---------|--------------|
| brent.central_estimate | brent_pct_change | Δ% к текущей цене |
| cbr_rate.central_estimate | rate_bps_change | Δ б.п. к текущей ставке |
| usdrub.central_estimate | usdrub_pct_change | Δ% к текущему курсу |
| cnyrub.central_estimate | cnyrub_pct_change | Δ% к текущему курсу |
| sanctions.central_estimate | sanctions_escalation | bool (ужесточение да/нет) |
| geopolitics.central_estimate | geopol_escalation | bool |
| xauusd.central_estimate | xauusd_pct_change | Δ% (нестандартное поле PSS) |
| urals_discount.central_estimate | urals_discount_usd | абсолютное значение $USD |
| cbr_rate.central_estimate | cbr_rate_absolute | абсолютное % значение |
| inflation_ru.central_estimate | inflation_ru_pct | абсолютное % значение |

Нестандартные поля PSS (xauusd, urals_discount, cbr_rate_absolute, inflation_ru_pct)
добавлены в обновлённую версию portfolio-scenario-stress. Если PSS старой версии —
эти поля включить в caveats с пометкой «requires PSS update».


---

## Cascade staleness — алгоритм для Шага 4

Используется в `SKILL.md → Шаг 4.1` для определения, какие downstream-факторы
нужно пересобрать после rebuild upstream. Применяется единообразно к MISSING и
к STALE — оба случая означают, что upstream меняется в текущем run.

### Алгоритм

```
inputs:
  factors_status[ factor ] ∈ { FRESH, STALE, MISSING, NOT_NEEDED }
  rebuild_planned[ factor ] ∈ { true, false }   # запланировано в Шаге 4

1. Для каждого фактора f в DAG (снизу вверх по уровням):
2.   если f.status ∈ {MISSING, STALE} → rebuild_planned[f] = true (по умолчанию)
3.   иначе если f.status == FRESH:
4.     для каждого upstream u в DAG[f].upstream:
5.       если rebuild_planned[u] == true:
6.         f.flags += "needs_rebuild_after_upstream"
7.         f.cascade_reason += { upstream: u, reason: u.status }

output:
  - план запуска (factors с rebuild_planned == true), упорядоченный по DAG-уровню
  - cascade-флаги для FRESH факторов с изменяющимся upstream
```

### Правила интерпретации в Шаге 4

| Состояние фактора | Где показывать в плане |
|-------------------|------------------------|
| MISSING + нет cascade-флага | Колонка «Действие» = Запустить |
| STALE + нет cascade-флага | Колонка «Действие» = Обновить (age) |
| FRESH + cascade-флаг | Отдельный блок «Cascade-флаги», действие: Обновить (upstream) |
| FRESH + нет cascade-флага | Блок «Использовать как есть» |

### Почему cascade-флаги — отдельный блок

FRESH-фактор с cascade-флагом — это пограничный случай: технически прогноз
не устарел, но логически становится несогласованным после rebuild upstream.
Решение пересобирать остаётся за пользователем (вариант [B] позволяет
проигнорировать cascade), но он должен видеть это как явный trade-off.

### Варианты обработки cascade-флагов

| Вариант пользователя | Поведение скилла |
|----------------------|------------------|
| [A] всё пересобрать | Cascade-флаги тоже идут на rebuild |
| [B] только Missing | Cascade-флаги остаются с устаревшим upstream → caveat `STALE_UPSTREAM_CONTEXT` |
| [C] вручную | Пользователь решает каждый cascade-фактор отдельно |
| [D] PARTIAL / as-is | Cascade-флаги все становятся `STALE_UPSTREAM_CONTEXT` caveats |


---

## Geopolitics → downstream: per-factor translation (Variant 3)

`scenario-builder` выдаёт 4-сценарную Shell-матрицу для `geopolitics`. У каждого
downstream-фактора своя чувствительность к этой матрице — разная по форме.
Прямая подстановка «central_estimate» не работает: brent при двух разных
geopolitics-сценариях может двигаться в противоположные стороны и центральная
оценка теряет смысл.

Variant 3 = per-factor translation. Для каждого downstream-фактора заранее
зафиксирован класс отклика на geopolitics, и `macro-forecast-chain` (Шаг 5)
применяет соответствующее правило.

### Классы отклика

**linear** — отклик монотонный по обеим осям geopolitics-матрицы. Можно брать
взвешенное среднее по сценариям: `f_linear = Σ p_i × f_i`. Ошибка маленькая,
информация сохраняется.

**nonlinear** — отклик немонотонный или знак-зависит от направления конфликта.
Среднее ничего не значит. Translation:

- **Под D1 (modal_scenario: none, default):** собрать FCA на каждом из 4
  сценариев равной глубины и записать все 4 значения в блок
  `conditional_on_scenarios.by_scenario`. Downstream-стресс прогоняет 4
  параллельных расчёта. Caveat не нужен — это штатный путь.
- **Под weighted-режимом (modal_scenario != none, явно заданные веса):**
  основной FCA на модальном сценарии, short-form на 3 остальных →
  `alternatives:` блок. Это устаревший путь, оставлен только для совместимости.
- **Если у legacy-прогноза нет ни by_scenario, ни alternatives:** caveat
  `MISSING_BY_SCENARIO` (severity: medium), стресс деградирует к медианному
  fallback.

**indifferent** — фактор слабо зависит от geopolitics-матрицы. Translation:
не передавать geopolitics в upstream-контекст (или передавать как фоновый
с пометкой `informal: true`). Это явно отделяет факторы с собственной
динамикой от макро-каскада.

**axis_dependent** — отклик зависит от того, какая ось geopolitics-матрицы
сильнее изменилась. Например, ось «интенсивность конфликта» влияет на
санкции и nominally нефть, ось «санкции» — на urals_discount и usdrub.
Translation: использовать ось напрямую (одно число вместо матрицы),
если scenario-builder её предоставил в выходе. Иначе — fallback на nonlinear.

### Per-factor классификация

| Downstream | Класс | Обоснование |
|------------|-------|-------------|
| `sanctions` | `axis_dependent` (sanctions ось) | Санкции — это сама вторая ось geopolitics-матрицы. Translation тривиальная: брать значение оси напрямую. |
| `brent` | `nonlinear` | При эскалации цена может уйти и в +30% (war premium), и в −20% (recession demand drop). Среднее = 0 — теряем сигнал. Использовать modal scenario. |
| `budget_deficit` | `linear` (через brent + sanctions) | Чувствительность приблизительно линейна по нефтегазовым доходам и санкционным компенсациям. Marginalization работает. |
| `urals_discount` | `axis_dependent` (sanctions ось) | Дисконт почти полностью определяется санкционной осью. Использовать её напрямую. |
| `usdrub` | `nonlinear` | При жёсткой эскалации курс может уйти в обе стороны (capital controls + freeze vs нефтяной шок). Modal. |
| `xauusd` | `linear` (но малочувствителен) | Safe-haven спрос приблизительно монотонен по эскалации. Marginalization работает, но веса маленькие — geopolitics здесь второстепенный upstream после USD-cycle. |
| `cnyrub` | `nonlinear` (через usdrub) | Наследует nonlinearity от usdrub. Translation = тот же modal, что и для usdrub. |
| `inflation_ru` | `linear` (через usdrub + budget_deficit) | Чувствительность приблизительно линейна. Marginalization, но наследует caveat от modal-факторов выше. |
| `cbr_rate` | `linear` (через inflation_ru) | Линейная функция инфляции. Marginalization. |
| `sector_oil_gas` | `nonlinear` (через brent) | Наследует от brent. Modal. |
| `sector_banks` | `linear` (через cbr_rate) | Marginalization. |
| `sector_metals` | `axis_dependent` (sanctions) | Доминанта — санкции, не модальный сценарий. |
| `sector_realty` | `linear` | Через cbr_rate. |
| `sector_it` | `axis_dependent` (sanctions) | Tech-санкции. |
| `sector_gold_funds` | `linear` (через xauusd) | Marginalization. |
| `sector_bonds_rub` | `linear` | Marginalization. |
| `sector_bonds_fx` | `nonlinear` (через usdrub) | Modal. |

### Алгоритм применения (для Шага 5 в SKILL.md)

```
def apply_geopolitics_translation(factor, scenario_matrix):
    cls = GEOPOLITICS_TRANSLATION[factor]

    if cls == "linear":
        # Запросить FCA на ВЗВЕШЕННОМ среднем по 4 сценариям.
        # Промпт: «geopolitics — взвешенный профиль из 4 сценариев Shell-матрицы:
        #          p1=0.30 для Sc-A (...), p2=0.28 для Sc-B (...), ...»
        # FCA выдаёт один прогноз с учётом распределения.
        return single_forecast_with_distribution_in_prompt

    elif cls == "nonlinear":
        if modal_scenario_id is None:        # D1 default (Pure Shell)
            # Запросить FCA на КАЖДОМ из 4 сценариев равной глубины.
            # Все 4 значения записываются в conditional_on_scenarios.by_scenario.
            # Downstream-стресс прогоняет 4 параллельных расчёта.
            # Caveat не порождается — это штатный путь.
            return forecasts_by_scenario_all_four
        else:                                # weighted-режим (custom веса)
            # Запросить FCA на модальном сценарии + short-form на 3 остальных.
            # Записать в alternatives: блок macro_input.yaml.
            # Если legacy-прогноз пришёл без обоих блоков → caveat MISSING_BY_SCENARIO.
            return modal_forecast_plus_alternatives

    elif cls == "axis_dependent":
        # Использовать одну ось матрицы напрямую (sanctions ось → bool/intensity).
        # FCA не нужен на geopolitics-вход; запрос строится прямо на оси.
        return axis_value_as_upstream

    elif cls == "indifferent":
        # geopolitics не передаётся в upstream-блок промпта.
        # FCA получает контекст без geopolitics-секции.
        return None
```

### Промпт-шаблоны для Шага 5

**linear:**
```
[Upstream-контекст: geopolitics — взвешенное распределение]
- Sc-A («{label}»): p=0.30, описание: {short}
- Sc-B («{label}»): p=0.28, описание: {short}
- Sc-C («{label}»): p=0.22, описание: {short}
- Sc-D («{label}»): p=0.20, описание: {short}

При построении прогноза учти, что эти сценарии равноправны;
выдай взвешенное центральное значение и индикативный разброс
(P10/P90) с учётом распределения сценариев.
```

**nonlinear:**
```
[Upstream-контекст: geopolitics условен на МОДАЛЬНОМ сценарии]
Прогноз ниже — условен ИСКЛЮЧИТЕЛЬНО на сценарии Sc-{modal_id}
(вероятность p_modal=0.30):
{полное описание модального сценария}

Если реализуется альтернативный сценарий — этот прогноз НЕ применим.
Альтернативные значения для альтернативных сценариев — выноси в
отдельный блок «Conditional alternatives» с короткой оценкой по
каждому из остальных трёх сценариев.
```

**axis_dependent (пример sanctions ось):**
```
[Upstream-контекст: ось sanctions из geopolitics-матрицы]
Значение оси: {axis_value} (диапазон [0, 1] от снятия до полного embargo;
текущее распределение сценариев даёт ожидаемое значение axis = 0.55).

Используй это число напрямую — игнорируй другую ось geopolitics.
```

**indifferent:**
```
[Upstream-контекст: без geopolitics]
Этот фактор не имеет значимой чувствительности к geopolitics-сценариям;
строй прогноз только на других upstream-факторах.
```

### Caveats, которые порождает translation

| Translation | Caveat в macro_input.yaml | severity |
|-------------|----------------------------|----------|
| linear | (нет — нормальный режим) | — |
| nonlinear (D1 / by_scenario заполнен) | (нет — штатный путь) | — |
| nonlinear (legacy без by_scenario и без alternatives) | `MISSING_BY_SCENARIO` | medium |
| nonlinear (weighted-режим, alternatives неполные) | `ALTERNATIVES_NOT_RECORDED` | medium |
| axis_dependent | (нет — точная семантика) | — |
| indifferent | (нет) | — |

Под D1 (modal_scenario: none) равные веса 0.25 — норма, и caveat про «слабый
модал» не порождается. Это default-путь: все nonlinear-факторы потребляются
через `by_scenario` параллельно по 4 сценариям.

### Записываем translation в YAML прогноза

Каждый downstream-прогноз сохраняет применённое translation в frontmatter:
```yaml
geopolitics_translation:
  method: linear | nonlinear | axis_dependent | indifferent
  source_scenario_matrix: "scenarios/{file}.yaml"
  modal_scenario_id: "Sc-A"          # только при method=nonlinear
  modal_probability: 0.30            # только при method=nonlinear
  alternatives_recorded: true        # только при method=nonlinear
```

Это и трассируемость, и явная разметка для retrospective-forecast-audit:
если прогноз не сбылся, сначала смотрим — реализовался ли модальный сценарий.

---

## Схема шага 5: фактор → метод → сценарий → обратная связь

```
 ВХОД
 ┌────────────────────────────────────────────────────────────────────┐
 │ geopolitics Shell-матрица: 4 сценария (p, оси) + modal_flag        │
 │ Layer 1: upstream central_estimate других факторов                 │
 └───────────────────────────────┬────────────────────────────────────┘
                                 ▼
 ШАГ 5.0  geopolitics_translation (один раз, до любых прогнозов)
 ┌────────────────────────────────────────────────────────────────────┐
 │ modal_flag: no_modal            -> modal_scenario = none (D1)      │
 │ modal_flag: weighted, max p>=.40 -> modal_scenario = Sc-{id}       │
 │                                  иначе none                        │
 │ класс отклика на фактор:                                           │
 │  axis_dependent: sanctions, urals_discount, sector_metals,         │
 │                  sector_it (ось sanctions)                         │
 │  nonlinear:      brent, usdrub, cnyrub (через usdrub),             │
 │                  sector_oil_gas, sector_bonds_fx                   │
 │  linear:         budget_deficit, xauusd, inflation_ru, cbr_rate,   │
 │                  sector_banks, sector_realty, sector_gold_funds,   │
 │                  sector_bonds_rub                                  │
 │  indifferent:    факторы без значимой связи, geopolitics не        │
 │                  передаётся в upstream-контекст                    │
 └───────────────────────────────┬────────────────────────────────────┘
                                 ▼
 ШАГ 5.1  запуск каждого фактора из плана
 ┌────────────────────────────────────────────────────────────────────┐
 │ linear         -> 1 FCA-запрос, взвешенное среднее 4 сценариев     │
 │ nonlinear D1   -> 4 равноправных FCA-запроса (Sc-A..D)             │
 │                   -> conditional_on_scenarios.by_scenario          │
 │ nonlinear      -> FCA на модальном + short-form на 3 остальных     │
 │  weighted         -> alternatives:                                 │
 │ axis_dependent -> без FCA, значение из оси матрицы                 │
 │ indifferent    -> FCA без geopolitics в контексте                  │
 │ geopolitics, если её нет -> scenario-builder; остальные -> FCA     │
 │ затем save-to-library, в YAML блок geopolitics_translation         │
 └───────────────┬────────────────────────────────────┬───────────────┘
                 ▼                                    ▼
 ШАГ 5.2  alternatives (nonlinear)         ВЫХОД
 ┌──────────────────────────────┐   ┌─────────────────────────────────┐
 │ 3 short-form FCA (3-5 ист.), │   │ macro-scenarios / macro-marginal│
 │ indicative: true, пишутся    │   │ caveats в macro_input.yaml;     │
 │ в forecast.alternatives      │   │ статус фактора -> FRESH         │
 │ пропуск (мало времени) ->    │   └────────────────┬────────────────┘
 │ caveat ALTERNATIVES_NOT_     │                    │
 │ RECORDED                     │                    ▼
 └───────────────┬──────────────┘      portfolio-scenario-stress
                 └─────────────────────────►(tail-risk, by_scenario)
 ОБРАТНАЯ СВЯЗЬ: нет by_scenario и alternatives у legacy-прогноза
   -> caveat MISSING_BY_SCENARIO, стресс -> медианный fallback;
   retrospective audit: сначала смотрят, реализовался ли модальный сценарий
```

Легенда:
- Sc-A..D — четыре сценария Shell-матрицы geopolitics; D1 = равные веса 0.25, модального нет.
- by_scenario — штатный путь nonlinear под D1; caveat не порождается.
- alternatives — путь weighted-режима (оставлен для совместимости), его заполняет шаг 5.2.
- Классы факторов взяты из таблицы «Per-factor классификация»; прочие факторы шага 4 — по ней же.
- inflation_ru (linear) наследует caveat от modal-факторов выше (usdrub, budget_deficit).

---

## Conditional FCA per scenario — шаблоны промптов

### Когда применяется

Если macro-forecast-chain запрашивает per-scenario оценку фактора (не маргинальную):
использовать только источники с matching `implicit_geopolitical_scenarios`.

### Промпт-шаблон по method

**method: linear** (большинство факторов):
```
Контекст: сценарий {scenario_id} («{label}»).
В этом мире: {scenario_description}.
Как ведёт себя {factor} в данном сценарии? Дай центральную оценку + диапазон.
```

**method: nonlinear** (usdrub, brent при высокой эскалации):
```
Контекст: сценарий {scenario_id}. В этом мире ожидаем нелинейный отклик.
Опиши основной отклик {factor} + tail distribution (P10/P90).
```

**method: axis_dependent** (факторы, жёстко привязанные к одной оси):
```
Контекст: ось {axis_name} = {axis_value}.
Твой прогноз {factor} зависит только от этой оси. Ось Y — нейтральна для этого фактора.
```

**method: indifferent** (xauusd, gold_funds — слабая привязка к сценариям):
```
{factor} слабо зависит от сценариев — используй маргинальный прогноз.
Per-scenario вариация: добавь ±{threshold}% к маргинальному значению.
```

### Trust-weight per scenario

При per-scenario FCA: `effective_weight = trust.conditional × implicit_weight_in_scenario`.
Если `trust.conditional` отсутствует → fallback на `trust.marginal` (D4 backward compat).

Пример для Sc-D (эскалация + санкции):
```
Источник A: trust.marginal=HIGH,   implicit={D: 0.7} → effective = 1.0 × 0.7 = 0.70
Источник B: trust.marginal=MEDIUM, implicit={A: 0.8, D: 0.2} → effective = 0.5 × 0.2 = 0.10
```
