# Output Template

Полный шаблон вывода с примерами для двух типов прогнозов.

---

## Шаблон (общий)

```markdown
---
forecast_date: {YYYY-MM-DD}          # дата составления прогноза
horizon_date: {YYYY-MM-DD}           # когда прогноз сбудется или нет — дата финального аудита
horizons: [{YYYY-MM-DD}, {YYYY-MM-DD}]   # все горизонты, если прогноз многоточечный (опц.); есть scenarios/horizons.json — все даты его horizon_ends
review_interval_months: {N}          # как часто обновлять snapshot (типично: 1, 3, 6)
topic: {краткое название темы}
domain: {geopolitics / ru-sellside / global-banks / tech-ceo / ru-macro}
method: fca                          # тип источника: fca | manual | external_quoted
                                     #   - fca: построен этим скиллом, confidence обязателен
                                     #   - manual: введён вручную, confidence: null допустим
                                     #   - external_quoted: цитата из chat/документа, без агрегации

# upstream_snapshot — фиксирует значения upstream-прогнозов, которые
# использовались при построении ЭТОГО прогноза. Нужен для трассируемости:
# через 3 месяца, когда upstream пересобран, видно, на каком контексте был
# построен текущий прогноз и нужно ли его пересобирать (см. cascade-staleness
# в macro-forecast-chain).
upstream_snapshot:
  - factor: {имя upstream-фактора, e.g. brent}
    central_estimate: "{строка с центральной оценкой, e.g. $88/b к 2026-12-31}"
    confidence: 0.40
    forecast_date: 2026-04-30
    source_file: "forecasts/brent-oil-dec-2026-2026-04-30.yaml"
  - factor: sanctions
    central_estimate: "holding pattern ~50%; relief ~15-20%"
    confidence: 0.43
    forecast_date: 2026-05-02
    source_file: "forecasts/sanctions-russia-2026-27-2026-05-02.yaml"
# Если upstream не использовался (Level-0 фактор) — оставлять upstream_snapshot: []

# geopolitics_translation — обязателен, если в upstream_snapshot есть geopolitics
# или если фактор перечислен в dependency-map.md. См. macro-forecast-chain →
# references/dependency-map.md → «Geopolitics → downstream: per-factor translation».
geopolitics_translation:
  method: linear | nonlinear | axis_dependent | indifferent
  source_scenario_matrix: "scenarios/{file}.yaml"   # из какой Shell-матрицы
  # Только для method=nonlinear:
  modal_scenario_id: "Sc-A"
  modal_probability: 0.30
  alternatives_recorded: true | false               # выполнен ли Шаг 5.2 chain
  # Только для method=axis_dependent:
  axis: "sanctions_intensity"
  axis_value_used: 0.55
  # Только для method=linear:
  distribution_used: true                           # FCA получил все 4 сценария

# alternatives — обязателен ТОЛЬКО для method=nonlinear с alternatives_recorded=true.
# Структура — индикативные оценки на оставшихся 3 сценариях (не основная агрегация).
alternatives:
  - scenario_id: "Sc-B"
    probability: 0.28
    central_estimate: "{строка}"
    indicative: true              # коротко, без полной агрегации
    sources_used: 3               # сколько источников было опрошено
    note: "{1 строка контекста}"
  # Sc-C, Sc-D аналогично
---

# Прогнозы: {тема} · {дата запроса}

**Домен**: {geopolitics / ru-sellside / global-banks / tech-ceo / ru-macro}
**Дата составления**: {YYYY-MM-DD}
**Горизонт прогноза**: {YYYY-MM-DD} — *финальный аудит возможен после этой даты*
**Регулярный ревью**: каждые {N} мес. (следующий: {YYYY-MM-DD})
**Источников проверено**: {N} · **С trust ≥ MEDIUM**: {M} · **Отброшено**: {K}

## TL;DR — modal scenario

**Самый вероятный исход (~{P}%)**: {1–2 строки дистилляции наиболее высоковзвешенного сценария.
Для числовых прогнозов — weighted median. Для качественных — позиция-победитель split-а.}

*Полное распределение и альтернативные сценарии — в секции «Filtered Consensus» ниже.*

## ⚠️ Asymmetry warning (если применимо)

{Выводится только если карта лагерей содержит ≥3 лагерей с одной стороны атрибуции
и 0–1 с другой. Текст:}

«Карта лагерей асимметрична: все/большинство источников атрибутируют ответственность
стороне {X}; контр-нарратив (атрибуция стороне {Y}) {не представлен / представлен слабо}
в доступных источниках. Прогноз отражает institutional discourse, который сам по себе
смещён.»

## Снимок мнений

| Источник | Прогноз | Горизонт | Дата | Trust (домен) | Цитата + URL |
|---|---|---|---|---|---|
| {Имя} | {числовое или качественное} | {конец YYYY / YYYY-QN} | {YYYY-MM} | HIGH / MEDIUM / LOW / IGNORE / ⬜ не аудирован | «{≤15 слов оригинала}» [en: "{перевод}"] · [ссылка]({URL}) |

## Filtered Consensus

{ДЛЯ ЧИСЛОВЫХ ПРОГНОЗОВ:}
- Weighted median (HIGH × 1.0 + MEDIUM × 0.5): **{X}**
- Unweighted median (все источники): **{Y}**
- Расхождение: **{Z} п.п.** — это сила фильтра
  - Интерпретация: {большое расхождение = HIGH/MEDIUM источники систематически
    расходятся с LOW/IGNORE/неаудированными}

{ДЛЯ КАЧЕСТВЕННЫХ ПРОГНОЗОВ:}
- HIGH/MEDIUM источники: {X} за «{позиция A}», {Y} за «{позиция B}»
- Все источники: {X_total} за «{позиция A}», {Y_total} за «{позиция B}»
- Взвешенный split: {доля HIGH+MEDIUM за доминирующую позицию}%

**Взвешенный горизонт**: если источники называют разные сроки — посчитай средневзвешенный
горизонт (HIGH × 1.0, MEDIUM × 0.5). Укажи в шапке. Если горизонты принципиально
разные (напр., один источник говорит «2026», другой «2030+»), не усредняй — раздели
вывод по горизонтам явно.

## Ключевые допущения

Перечисли 3–5 допущений, на которых держится filtered consensus. Для каждого укажи:
- **Насколько обосновано**: HIGH (подтверждено данными) / MEDIUM (вероятно) / LOW (предположение)
- **Чувствительность вывода**: если допущение окажется ложным — вывод рушится / меняется / устойчив

| Допущение | Обоснованность | Чувствительность | Комментарий |
|---|---|---|---|
| {формулировка} | HIGH / MEDIUM / LOW | Критическая / Умеренная / Низкая | {что именно меняется} |

*Допущение с LOW обоснованностью + Критической чувствительностью — главный риск прогноза.*

## Outliers (LOW / IGNORE)

| Источник | Прогноз | Trust | Почему не в consensus |
|---|---|---|---|
| {Имя} | {прогноз} | IGNORE ({субдомен}: 0/N попаданий) | track record 0/N в {субдомене} |

## Не аудированные источники

Следующие источники не найдены в INDEX.md и **не учитываются в filtered consensus**:

| Источник | Прогноз | Рекомендация |
|---|---|---|
| {Имя} | {прогноз} | Прогнать через retrospective-forecast-audit |

*Примечание о вероятностях сценариев: если прогноз сценарный, убедись что суммарные
вероятности сценариев дают ~100%. Остаток (нераспределённая вероятность) выноси явно —
например: «Прочие / непредвиденные сценарии: ~X%». Это не формальность — это честность
о том, что ты не претендуешь на полный охват возможного.*

*Примечание об условиях сценариев: явно размечай, являются ли условия сценария
**необходимыми** (все должны выполниться) или **достаточными** (любое из них запускает
сценарий). «Условия одновременно» = необходимые. «Любой из триггеров» = достаточные.*

## § Что дальше

- **(A)** Передать filtered consensus в **ru-portfolio-advisor** для портфельных выводов
- **(B)** Запустить **retrospective-forecast-audit** для нового источника: {список неаудированных}
- **(C)** Запустить **hypothesis-stress-tester** на modal scenario — атакует допущения
  с LOW обоснованностью и Критической чувствительностью
- **(D)** Сохранить в `Claude-Memory/forecasts/{тема}-{дата запроса}.md` с заполненным YAML frontmatter (forecast_date, horizon_date, review_interval_months)
```

---

## Пример 1: Числовой прогноз (ключевая ставка ЦБ РФ)

```markdown
---
forecast_date: 2026-04-27
horizon_date: 2026-12-31
review_interval_months: 3
topic: ru-rates-2026
domain: ru-macro
---

# Прогнозы: ключевая ставка ЦБ РФ к концу 2026 · 2026-04-27

**Домен**: ru-macro + ru-sellside
**Дата составления**: 2026-04-27
**Горизонт прогноза**: 2026-12-31 — *финальный аудит возможен после этой даты*
**Регулярный ревью**: каждые 3 мес. (следующий: 2026-07-27)
**Источников проверено**: 6 · **С trust ≥ MEDIUM**: 4 · **Отброшено**: 2

## TL;DR — modal scenario

**Самый вероятный исход**: ставка **14.5%** к концу 2026 (weighted median HIGH+MEDIUM).
Дезинфляционный тренд сохраняется, ЦБ снижает поэтапно. Расхождение с unweighted median
минимально (0.25 п.п.) — фильтр слабый.

## Снимок мнений

| Источник | Прогноз | Горизонт | Дата | Trust (домен) | Цитата + URL |
|---|---|---|---|---|---|
| ЦБ РФ | 16% | конец 2026 | 2026-03 | ⬜ не аудирован | «снижение ставки до 16% к концу 2026» · [ссылка](https://cbr.ru/...) |
| SberCIB | 14% | конец 2026 | 2026-04 | HIGH ru-rates | «ожидаем снижение до 14% в базовом сценарии» · [ссылка](https://sber.ru/...) |
| БКС | 15% | конец 2026 | 2026-03 | MEDIUM finance-ru | «ставка 15% к декабрю 2026» · [ссылка](https://bcs-express.ru/...) |
| Альфа-Инв | 13% | конец 2026 | 2026-04 | MEDIUM ru-rates | «агрессивный сценарий — 13% при снижении инфляции» · [ссылка](https://alfabank.ru/...) |
| JPMorgan | 17% | конец 2026 | 2026-02 | LOW russia-macro | «Russia rates to stay elevated at 17%» [en: «ставки в РФ останутся высокими на уровне 17%»] · [ссылка](https://jpmorgan.com/...) |
| ВТБ Мои Инв. | 14% | конец 2026 | 2026-04 | MEDIUM finance-ru | «14-15% к концу года» · [ссылка](https://vtb.ru/...) |

## Filtered Consensus

- Weighted median (HIGH × 1.0 + MEDIUM × 0.5): **14.5%**
  - Расчёт: SberCIB(14%, вес 1.0), БКС(15%, вес 0.5), Альфа(13%, вес 0.5), ВТБ(14%, вес 0.5)
- Unweighted median (все 6 источников): **14.75%**
- Расхождение: **0.25 п.п.** — фильтр слабый, мнения близки

## Ключевые допущения

| Допущение | Обоснованность | Чувствительность | Комментарий |
|---|---|---|---|
| Инфляция снижается к 5–6% к концу 2026 | MEDIUM | Критическая | При инфляции >7% ЦБ остановит цикл — ставка останется 16–17% |
| Бюджетные расходы не разгоняются выше плана | MEDIUM | Критическая | Проинфляционный сигнал → ЦБ замедлит снижение |
| Внешние условия (нефть, санкции) без резких шоков | LOW | Умеренная | Новый пакет санкций или нефть <$50 → вероятна пауза в снижении |

## Outliers (LOW / IGNORE)

| Источник | Прогноз | Trust | Почему не в consensus |
|---|---|---|---|
| JPMorgan | 17% | LOW (russia-macro) | Низкий track record по Russian rates в аудите |

## Не аудированные источники

| Источник | Прогноз | Рекомендация |
|---|---|---|
| ЦБ РФ | 16% | Прогнать через retrospective-forecast-audit — важный якорный источник |

## § Что дальше

- **(A)** Передать filtered consensus (14.5%) в **ru-portfolio-advisor** для оценки облигаций
- **(B)** Запустить **retrospective-forecast-audit** для: ЦБ РФ (высокий приоритет)
- **(C)** Сохранить: `Claude-Memory/forecasts/ru-rates-2026-04-27.md`
```

---

## Пример 2: Качественный прогноз (рецессия в США)

```markdown
---
forecast_date: 2026-04-27
horizon_date: 2026-12-31
review_interval_months: 3
topic: us-recession-2026
domain: global-banks
---

# Прогнозы: рецессия в США в 2026 · 2026-04-27

**Домен**: global-banks + geopolitics
**Дата составления**: 2026-04-27
**Горизонт прогноза**: 2026-12-31 — *финальный аудит возможен после этой даты*
**Регулярный ревью**: каждые 3 мес. (следующий: 2026-07-27)
**Источников проверено**: 7 · **С trust ≥ MEDIUM**: 4 · **Отброшено**: 3

## TL;DR — modal scenario

**Самый вероятный исход**: **рецессии не будет** (67% взвешенного split-а HIGH+MEDIUM
источников). Soft landing — базовый сценарий. Главные риски — sticky inflation и эскалация
тарифов.

## Снимок мнений

| Источник | Прогноз | Горизонт | Дата | Trust (домен) | Цитата + URL |
|---|---|---|---|---|---|
| Goldman Sachs | Нет рецессии | 2026 | 2026-04 | ⬜ не аудирован | «soft landing remains base case» [en: «мягкая посадка — базовый сценарий»] · [ссылка] |
| JPMorgan | Да (45% вероятность) | 2026 | 2026-03 | ⬜ не аудирован | «recession probability at 45% for 2026» [en: «вероятность рецессии 45% в 2026»] · [ссылка] |
| Brookings | Да (структурные риски) | 2026 | 2026-02 | MEDIUM us-domestic | «structural headwinds raise recession risk» [en: «структурные факторы повышают риск рецессии»] · [ссылка] |
| CFR | Нет рецессии | 2026 | 2026-03 | MEDIUM us-policy | «fiscal policy buffers recession» [en: «бюджетная политика смягчает риски рецессии»] · [ссылка] |
| Stratfor | Нет рецессии | 2026 | 2026-01 | MEDIUM us-domestic | «US economy resilient through 2026» [en: «экономика США устойчива в 2026»] · [ссылка] |
| Citi | Да (35% вероятность) | 2026 | 2026-03 | ⬜ не аудирован | «35% chance of US recession» · [ссылка] |
| Barclays | Нет рецессии | 2026 | 2026-04 | ⬜ не аудирован | «growth slows but no recession» · [ссылка] |

## Filtered Consensus

- HIGH/MEDIUM источники (Brookings, CFR, Stratfor): 1 за рецессию, 2 против
- **Взвешенный split: 67% против рецессии** (2 из 3 аудированных источников)
- Все 7 источников: 3 за рецессию, 4 против (57% против)
- Расхождение фильтра: фильтр незначительно смещает против рецессии (+10 п.п.)

## Ключевые допущения

| Допущение | Обоснованность | Чувствительность | Комментарий |
|---|---|---|---|
| ФРС продолжает постепенное снижение ставок в 2026 | MEDIUM | Критическая | Возобновление роста инфляции заморозит смягчение → рост вероятности рецессии |
| Бюджетный дефицит не вызывает рыночного кризиса доверия | MEDIUM | Умеренная | Spike доходности US10Y выше 5.5% изменит вывод |
| Тарифная война не эскалирует в полный торговый разрыв | LOW | Умеренная | Если тарифы достигнут >25% на основные группы товаров — рецессия становится базовым сценарием |

## Outliers (LOW / IGNORE)

Нет источников с LOW/IGNORE в этом домене в INDEX.

## Не аудированные источники

| Источник | Прогноз | Рекомендация |
|---|---|---|
| Goldman Sachs | Нет рецессии | Прогнать через retrospective-forecast-audit |
| JPMorgan | 45% рецессии | Прогнать через retrospective-forecast-audit |
| Citi | 35% рецессии | Прогнать через retrospective-forecast-audit |

*Примечание: ключевые global-banks не аудированы — filtered consensus основан
только на 3 geopolitics-источниках. Рекомендуется сначала пополнить INDEX.*

## § Что дальше

- **(A)** Использовать в **ru-portfolio-advisor** для оценки EM-рисков
- **(B)** **Приоритет**: запустить retrospective-forecast-audit для GS, JPM, Citi —
  это повысит качество filtered consensus по global-banks
- **(C)** Сохранить: `Claude-Memory/forecasts/us-recession-2026-04-27.md`
```

---

## Anti-patterns (❌ так не делать)

**AP1: Filtered consensus без указания отброшенных источников**

```markdown
❌ ПЛОХО:
## Filtered Consensus
Weighted median: 14.5%

✅ ХОРОШО:
## Filtered Consensus
Источников проверено: 6 · С trust ≥ MEDIUM: 4 · Отброшено: 2 (JPMorgan LOW, ЦБ РФ не аудирован)
Weighted median: 14.5%
```

Почему важно: пользователь должен понимать, какой процент информации был отфильтрован
и почему. Если отброшены 5 из 6 источников — это критически меняет интерпретацию.

---

**AP2: Применение trust weight «по ощущениям»**

```markdown
❌ ПЛОХО:
Goldman Sachs получает вес HIGH, потому что это авторитетный банк с многолетней
репутацией в финансовом прогнозировании.

✅ ХОРОШО:
Goldman Sachs не найден в INDEX.md → помечен как «не аудирован», вес 0 в consensus.
Рекомендуется прогнать через retrospective-forecast-audit.
```

Почему важно: репутация ≠ точность прогнозов. Track record calibrated через аудиты
— единственный надёжный сигнал. Goldman Sachs мог ошибаться систематически именно
в тех субдоменах, которые релевантны текущему запросу.

---

**AP3: Modal scenario без указания вероятности**

```markdown
❌ ПЛОХО:
## TL;DR
Korean-style armistice к 2027–2028, Украина в ЕС.

✅ ХОРОШО:
## TL;DR — modal scenario
**Самый вероятный исход (~50%)**: Korean-style armistice к 2027–2028, Украина в ЕС
через PACT-membership к 2030. Альтернативы — в секции Filtered Consensus.
```

Почему важно: пользователь должен сразу видеть степень уверенности в modal-исходе.
50% modal означает что 50% вероятности — у альтернатив; 80% modal — почти консенсус.
Без числа TL;DR превращается в скрытое утверждение.

---

**AP4: Карта лагерей с одной стороны атрибуции (asymmetry)**

```markdown
❌ ПЛОХО (карта по «будет ли война РФ-НАТО»):
| Atlantic mainstream | Dominant | РФ — агрессор |
| Frontline coalition | Significant | РФ скоро атакует Балтию |
| Nordic defense | Significant | РФ нужно сдерживать |

✅ ХОРОШО:
| Atlantic mainstream | Dominant | РФ — агрессор |
| US realist | Significant | Расширение НАТО — провокация |
| Russia-side | Dominant в РФ | Запад первым перешёл в режим войны |
| Global South | Minority | Конфликт внутрирегиональный |
```

Почему важно: асимметричная атрибуция выдаёт за консенсус то, что является institutional
bias одной стороны. Скилл — агрегатор, его задача — дать пользователю настоящую карту
позиций, а не воспроизвести самый громкий нарратив. Если контр-лагерь институционально
не существует — фиксировать это явно.


---

## upstream_snapshot — правила заполнения

**Когда заполнять.** Если в промпте FCA-запроса есть блок «Upstream-контекст»
(типично — при запуске из `macro-forecast-chain`), КАЖДОЕ значение из этого
блока должно быть зафиксировано в `upstream_snapshot` с полным набором полей:
factor, central_estimate (строка), confidence, forecast_date, source_file.

**Зачем.** Прогноз — это снимок мира на момент построения. Через N месяцев
upstream-прогнозы будут пересобраны, и без `upstream_snapshot` невозможно
понять, на каком именно контексте текущий прогноз стоял. Это нужно для:

1. **Cascade-staleness** в `macro-forecast-chain` — определить, насколько
   текущий прогноз устарел в плане upstream-контекста.
2. **Ретроспективный аудит** через `retrospective-forecast-audit` — отделить
   ошибку самого прогноза от ошибки upstream-предпосылок.
3. **Reproducibility** — воспроизвести логику прогноза спустя время.

**Если upstream не передавался в промпте** (Level-0 факторы — geopolitics,
прямой sell-side прогноз без зависимостей) — оставлять пустым: `upstream_snapshot: []`.

**Если upstream упоминается в промпте лексически, но без числа** — например,
«при текущем санкционном режиме» — записывать с пометкой `informal: true`:
```yaml
upstream_snapshot:
  - factor: sanctions
    central_estimate: "текущий санкционный режим (без числовой фиксации)"
    informal: true
```

**Связка с macro-forecast-chain.** Если прогноз запущен оркестратором,
оркестратор передаёт upstream-блок через промпт; FCA читает его и копирует
в `upstream_snapshot`. Никакой отдельной логики ходить за upstream-данными
у FCA нет — это ответственность оркестратора.

---

## method — три типа источника

| `method` | Когда использовать | confidence |
|----------|-------------------|-----------|
| `fca` | Прогноз построен через filtered consensus в этом скилле | обязателен, число в [0, 1] |
| `manual` | Прогноз введён пользователем вручную, без агрегации | `null` допустим, попадёт в caveat `LOW_CONFIDENCE` или `NO_CONFIDENCE` |
| `external_quoted` | Цитата прогноза из конкретного источника (один аналитик, один CEO) | `null` допустим — это не агрегированная оценка |

`save-to-library` валидирует это поле: если `method: fca` и `confidence: null` —
блокирует сохранение и просит явно перезапустить FCA.


---

## geopolitics_translation — правила заполнения (V3)

`macro-forecast-chain` (Шаг 5.0) определяет, какой translation применить к
каждому downstream-фактору, и передаёт это в промпт FCA. FCA **обязан**
зафиксировать использованный translation в frontmatter — это нужно для:

1. **Трассируемости.** Через 6 мес. понятно, на чём именно стоял прогноз —
   на модальном сценарии, на взвешенном среднем или на одной оси матрицы.
2. **Ретроспективного аудита.** Если прогноз не сбылся — сначала смотрим,
   реализовался ли модальный geopolitics-сценарий.
3. **Cascade staleness.** Если geopolitics-матрица пересчитана и модальный
   сценарий сменился — все downstream nonlinear-факторы автоматически
   помечаются как stale-by-cascade.

### Алгоритм заполнения

```
1. Прочитать класс translation для топика прогноза из dependency-map.md
   (поле GEOPOLITICS_TRANSLATION[topic]).

2. Если class == "linear":
     method: linear
     distribution_used: true (всегда true — иначе это не linear)
     alternatives: []  # не нужны для linear

3. Если class == "nonlinear":
     method: nonlinear
     modal_scenario_id: {из промпта macro-forecast-chain}
     modal_probability: {из промпта}
     # alternatives_recorded — true если Шаг 5.2 был выполнен
     # (3 short-form FCA для остальных сценариев)
     alternatives:
       - {scenario_id, probability, central_estimate, indicative: true, sources_used}
       - ... (3 объекта)

4. Если class == "axis_dependent":
     method: axis_dependent
     axis: {название оси из geopolitics scenario-matrix}
     axis_value_used: {число}
     alternatives: []  # ось — точная семантика, нет alternatives

5. Если class == "indifferent":
     method: indifferent
     # geopolitics не входил в upstream — никаких полей дополнительно
```

### Что делать, если translation в промпте не указан

Если `macro-forecast-chain` забыл передать translation (старая версия chain
или manual-запуск FCA) — заполнить:
```yaml
geopolitics_translation:
  method: legacy_unspecified
  note: "translation не передан в промпте; trace неполный"
```
И добавить в выходе caveat «Translation метод не зафиксирован — рекомендуется
перезапуск через macro-forecast-chain v2+».

### Связь с upstream_snapshot

Если `geopolitics` в `upstream_snapshot` — `geopolitics_translation` обязателен.
Если geopolitics НЕ в upstream_snapshot — `geopolitics_translation: null`
или `method: indifferent` — два эквивалентных способа сказать «этот прогноз
не зависит от geopolitics».
