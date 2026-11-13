# Output Template

Шаблон полного отчёта stress-test — тело черновика `_drafts/stress-{date}-{slug}.md` (в чат идёт выжимка, SKILL.md Шаг 6). Markdown. Всегда на русском.

---

## Структура выхода (обязательные блоки)

```markdown
# Портфельный стресс-тест — {дата}

## ⚙️ Конфигурация

| Параметр | Значение |
|----------|----------|
| Снапшот портфеля | PORTFOLIO-{date}.json |
| Прогнозный вход | {Тип A/B/C: описание источника} |
| Тип весов | **{equal-weighted / probability-weighted}** |
| Позиций в расчёте | {N} ({M} акций, {K} облигаций, {L} фондов) |
| Unmapped позиций | {0 или список тикеров} |

> ⚠️ **Confidence note:** Оценки ориентировочные (±5–15 п.п. на позицию). Sensitivity matrix — исторические средние, не precision tool. Ячейки с ⚠️ = low confidence.
> {Если equal-weighted:} Веса равные (0.25 × 4) — методологическое допущение Shell. **Не интерпретировать как реальные вероятности.** Expected P&L не рассчитывается.

---

## 📋 TL;DR

**Главный риск:** {1–2 предложения — что, сколько, почему}
**Главная возможность:** {1 предложение — best case}
**Скрытая концентрация:** {что не очевидно из распределения по секторам}

> При сравнении с прошлым прогоном — всегда называть базу сравнения явно
> («ценовой слой» или «полная доходность»,  §11.2a yaml-schemas.md) и сверить
> `basis_contract` обоих файлов. Один и тот же прирост/падение числа в разных
> базах означает разное — самая частая причина ложного вывода «доходность
> ушла в минус», когда на деле сменилась только база (см.
> docs/investment/task-stress-basis-contract.md).

---

## 📊 Таблица: позиция × сценарий → ΔP&L

_Сортировка: по убытку в worst scenario_

| Позиция | Сектор | Стоим. (тыс.₽) | {Сцен. 1} Δ% | {Сцен. 1} ΔRUB | {Сцен. 2} Δ% | {Сцен. 2} ΔRUB | ... |
|---------|--------|----------------|-------------|----------------|-------------|----------------|-----|
| LKOH | oil&gas | 380 | −18% | −68k | −6% | −23k | ... |
| SBER | banks | 295 | −22% | −65k | +8% | +24k | ... |
| SU26243 | bond_ofz | 124 | +7% | +9k | −6% | −7k | ... |
| TGLD | fund_gold | 210 | +14%⚠️ | +29k | +3%⚠️ | +6k | ... |
| ... | | | | | | | |
| **ИТОГО** | | **{Σ value}** | **{min Δ%}** | **{min ΔRUB}** | **{Δ%}** | **{ΔRUB}** | ... |
| ~~TICKER~~ ⚠️UNMAPPED | — | {value} | — | — | — | — | ... |

_⚠️ = low confidence оценка_

---

## 🏭 Секторальная сводка

| Сектор | Доля портф. | {Сцен. 1} ΔRUB | {Сцен. 2} ΔRUB | ... |
|--------|------------|----------------|----------------|-----|
| oil&gas | 35% | −145k | −55k | ... |
| banks | 22% | −120k | +45k | ... |
| bonds_ofz | 18% | +42k | −34k | ... |
| ... | | | | |
| **ИТОГО** | 100% | **−380k** | **+120k** | ... |

---

## 📉 Top-5 уязвимых позиций (worst scenario: «{название}»)

| # | Позиция | Сектор | ΔRUB | Δ% | Главный фактор |
|---|---------|--------|------|----|----------------|
| 1 | SBER | banks | −120k | −22% | sanctions + rate |
| 2 | LKOH | oil&gas | −68k | −18% | brent |
| ... | | | | | |

---

## 📈 Top-5 устойчивых / выигрывающих позиций (best scenario: «{название}»)

| # | Позиция | Сектор | ΔRUB | Δ% | Главный фактор |
|---|---------|--------|------|----|----------------|
| 1 | SU26243 | bond_ofz | +42k | +8% | rate (снижение) |
| 2 | TGLD | fund_gold | +29k | +14% | usdrub (ослабление) |
| ... | | | | | |

---

## 🔀 Концентрация рисков

**Concentration ratio:** {X}% стоимости портфеля движется в одном направлении при изменении Brent ({главного фактора}).

**Доминирующий фактор:** {brent / rate / usdrub / sanctions} — влияет на {N}% позиций из {M} в портфеле.

**Скрытый overlap:** {например, «SBMX и LKOH/ROSN создают двойную экспозицию на нефтяников — суммарная доля oil&gas выше, чем кажется»}

---

## 🛡️ Hedge-кандидаты

Позиции с противоположной чувствительностью к {доминирующему фактору}:

| Позиция | Уже в портфеле | Сектор | β к {фактору} | Комментарий |
|---------|---------------|--------|--------------|-------------|
| X5 (FIVE) | Нет | retail | −0.20 | Слабо коррелирует с нефтью |
| SU26207 (ОФЗ короткая) | Нет | bond_ofz | ~0 к brent | Нейтральный к нефти |
| ... | | | | |

_(Это информация, а не рекомендация. Решение о покупке — за пользователем.)_

---

{ТОЛЬКО при Типе C: stress-tested forecast}
## ⚡ Vulnerability Map (хвостовые риски)

Позиции, специфически уязвимые к vulnerability scenarios (не к main case):

| Vulnerability | P | Позиции-мишени | Доп. ΔRUB vs main | Комментарий |
|--------------|---|---------------|-------------------|-------------|
| ОПЕК+ распад → Brent $55 | 10% | LKOH, ROSN, SIBN | −55k | Сверх main case -28k |
| Hike ЦБ 50 б.п. | 15% | SU26243, SMLT | −18k | Выход из ОФЗ ускорится |
| ... | | | | |

Tail-risk вывод: {N}% вероятность убытка >{X}k RUB за счёт tail сценариев.

---

## 📐 Портфельные метрики

Обе базы — §11.2a yaml-schemas.md; числа берутся из `portfolio_aggregates.{price,total_return}`.

**— ценовой слой (Layer 1, price)**

| Метрика | Значение |
|---------|---------|
| P&L range по сценариям | от **−380k** до **+120k** RUB |
| {Если probability-weighted:} Expected P&L | **−85k** RUB |
| {Если equal-weighted:} Avg P&L (equal) | **−65k** RUB (не вероятностно-взвешенный) |
| {Если Тип C:} VaR(85%)-like | ≥−{X}k RUB с вероятностью 85% |
| {Если Тип C:} Tail loss (P5) | −{X}k RUB |

**— полная доходность (Layer 1 + 2, total_return; ноль, если в портфеле нет облигаций)**

| Метрика | Значение |
|---------|---------|
| P&L range по сценариям | от **−350k** до **+126k** RUB |
| {Если probability-weighted:} Expected P&L | **−79k** RUB |
| {Если equal-weighted:} Avg P&L (equal) | **−59k** RUB (не вероятностно-взвешенный) |

**— общее (от базы не зависит)**

| Метрика | Значение |
|---------|---------|
| Доля портфеля с high confidence | {X}% |
| UNMAPPED позиции (не включены) | {0 или list} |

---

_Скилл: portfolio-scenario-stress | {дата} | Данные: PORTFOLIO-{date}.json_
```

---

## YAML для сохранения (парный файл)

> 🚨 **Пример ниже — ЛЕГАСИ v1, копировать его буквально нельзя.** Живые артефакты
> и валидатор `save-to-library` после V2-CUTOVER принимают **только schema 2**:
> `schema_version: 2`, факторы сценария в `factors_by_horizon.{hNN}`, дельты позиции
> в `by_horizon.{hNN}.delta_pct_by_scenario`. Артефакт со схемой 1 будет отклонён
> как blocking.
>
> **Откуда берётся настоящая структура:** блоки `per_position` и `factors_by_horizon`
> пишет `stress_build.py` (Шаг 3.6). Руками эти блоки не собираются.
>
> Ниже v1-пример оставлен ради перечня ОБЯЗАТЕЛЬНЫХ верхнеуровневых полей и их
> имён — он в этой части актуален. Приведение примера к v2 — задача PSS-8.

Артефакт, генерируемый в Шаге 6. Пользователь проверяет и сохраняет через `save-to-library` в `Portfolio/stress/`.
Нужен для `retrospective-forecast-audit` и `portfolio-integrated-view`.

**Имя файла:** `stress-{YYYY-MM-DD}-{slug}.yaml`

---

### ⚠️ ОБЯЗАТЕЛЬНЫЕ верхнеуровневые поля (контракт schema v1)

Эти поля **должны присутствовать ровно под этими именами**. Псевдонимы и
переименования запрещены — `save-to-library` Workflow E3 их не пропустит,
а `portfolio-integrated-view` и `retrospective-forecast-audit` сломаются.

| Поле | Тип | Обязательно? | Почему именно это имя |
|------|-----|--------------|------------------------|
| `schema_version` | int (=1) | ДА | Версионирование контракта |
| `type` | string (=`portfolio-stress-test`) | ДА | save-to-library E1 классифицирует артефакт по этому полю |
| `date` | string (`YYYY-MM-DD`) | ДА | Не `generated_at`. retrospective-forecast-audit фильтрует по `date` |
| `portfolio_snapshot_id` | string (`portfolio-{date}.json`) | ДА | Не `portfolio_snapshot`. portfolio-integrated-view JOIN'ит по этому ключу со снапшотами |
| `scenario_source` | enum | ДА | `scenario-builder \| forecast-confidence-applier \| hypothesis-stress-tester \| macro-forecast-chain \| manual \| hybrid` |
| `weight_type` | enum (`equal`\|`probability`) | ДА | На верхнем уровне (не только внутри `scenarios.*`) |
| `scenario_count` | int | ДА | Обычно 4 |
| `scenarios` | dict | ДА | Ключи — `Sc-X_label`, см. ниже |
| `per_position` | dict | ДА | Ключи — тикеры, см. ниже |
| `sector_breakdown_pct` | dict | ДА | Покрытие 100% ±2%, см. ниже |
| `top_risks` | list | ДА | До 5 позиций |
| `macro_blindspots` | list | ДА (может быть пустым) | Список тикеров с `macro_blindspot: true` или эквивалентным verdict из Шага 3.5. **Таблица и булев флаг — РАЗНЫЕ популяции, это норма:** флаг ставит скрипт механически (R² / \|β\| / список идиосинкратических тикеров), таблицу пишет модель по вердиктам (`MIXED` / `IDIOSYNCRATIC_DOMINATES` / `MACRO_DOMINATES`) — в прогоне 08-15 это 4 позиции против 27. Потребитель (`portfolio-integrated-view`) с 2026-08-16 читает **оба** источника: метка 👁 = флаг ИЛИ вердикт ∈ {MIXED, IDIOSYNCRATIC_DOMINATES}; `MACRO_DOMINATES` слепым пятном не считается. Поэтому вердикт в таблице обязателен и осмыслен — по нему считает потребитель |
| `basis_contract` | int | ДА | Версия контракта баз расчёта (§11.2a yaml-schemas.md); отсутствие = старый формат, `validate_stress_output.py` отклонит |
| `layers_included` | dict | ДА | `{price: true, bond_carry: true, dividends: false}` — `dividends` всегда `false`, дивиденды в стрессе не считаются |
| `per_position_basis` | string (=`price`) | ДА | Инвариант — `per_position` никогда не несёт carry/total-return |
| `base_value_rub` | int | ДА | Знаменатель ВСЕХ pct-полей, единожды |
| `base_value_note` | string | ДА | Из чего состоит `base_value_rub` |
| `p_basis` | enum (`primary_horizon`\|`mean_across_horizons`) | ДА | Что значит скаляр `scenarios.<X>.p` |
| `portfolio_aggregates` | dict (`price`/`total_return`, каждый по всем горизонтам) | ДА | Заменяет `portfolio_pl_range_rub`/`expected_pl_rub` (deprecated, см. ниже) |
| `concentration_ratio` | float | ДА | Доля портфеля, движущаяся однонаправленно |
| `dominant_factor` | string | ДА | Основной драйвер риска |
| `factor_definitions` | dict | ДА | Метаданные факторов: unit (машинный код), display_label (человекочитаемый ярлык единицы), if_positive, if_negative — позволяет viewer'у отображать интерпретации без зашитой логики |
| `unmapped_tickers` | list | ДА (может быть пустым) | Тикеры без секторального маппинга |
| `caveats` | list (≥1 запись с `severity: HIGH`) | ДА | save-to-library E3 проверяет наличие хотя бы одной HIGH |
| `review_date` | string (`YYYY-MM-DD`) | ДА | `date + 6 месяцев`, для retrospective-forecast-audit |

**Опциональные расширения** (можно добавлять, не ломают валидацию):

| Поле | Когда добавлять |
|------|-----------------|
| `stress_id` | Когда полезен внешний идентификатор (например, для трекинга в audit) |
| `macro_input` | Когда `scenario_source = macro-forecast-chain` — имя файла `macro-scenarios-<дата>.yaml` (ставит `build_stress_stub.py` из `--macro-scenarios`); единственная ссылка стресса на макросценарии — второго поля нет, версии прогнозов не копируются |
| `forecast_type` | Тип входа (A/B/C/D из Шага 1) |
| `concentration` | Расширенный блок с `top5_by_value_pct`, `usdrub_dominant_pct` и т.п. — не заменяет `concentration_ratio` |
| `method` | Описание метода расчёта — длинное текстовое поле |
| `notes` | Свободный текст |

**Запрещённые переименования** (если встретите соблазн):

| Не делать | Делать |
|-----------|--------|
| `generated_at:` вместо `date:` | `date:` (можно дополнительно `generated_at:`) |
| `portfolio_snapshot:` вместо `portfolio_snapshot_id:` | `portfolio_snapshot_id:` |
| Опускать `caveats` если нечего сказать | Минимум одна запись HIGH про `factor_betas_r2: null` (priors-only Phase 4.1) |

**Deprecated — контракт баз расчёта (§11.2a `yaml-schemas.md`, полная спека —
`docs/investment/task-stress-basis-contract.md`).** Эти имена жили в архиве до
`basis_contract` и означали РАЗНОЕ в разных прогонах (иногда price-only, иногда
price+carry под одним и тем же именем) — источник ложных выводов при сравнении
прогонов. В новых файлах запрещены, `validate_stress_output.py` отклоняет:

| Не делать (deprecated) | Делать |
|-----------|--------|
| `expected_pl_rub:` (скаляр на верхнем уровне) | `portfolio_aggregates.{price,total_return}.expected_pl_rub_by_horizon` |
| `portfolio_pl_range_rub:` (скаляр) | `portfolio_aggregates.{price,total_return}.pl_range_rub_by_horizon` |
| `total_return_by_horizon_rub:` | `scenarios.<X>.portfolio_level_by_horizon.<hNN>.total_return_rub` |
| `scenarios.<X>.portfolio_level_by_horizon.<hNN>.delta_rub` | `.price_delta_rub` и `.total_return_rub` — оба явно, разные числа |
| `l1_price_only_delta_rub` / `l1_price_only_pct` | `price_delta_rub` / `price_delta_pct` в том же блоке |
| `robustness:` плоский (без разбивки по базе) | `robustness.{price,total_return}.by_horizon.<hNN>` |
| `expected_pct_pweighted` в `portfolio_level_by_horizon` (внутри `per_position` — легитимно, не трогать) | `expected_pl_pct_by_horizon` в `portfolio_aggregates.<basis>` |

---

**Scenario IDs** в `scenarios:` и `delta_pct_by_scenario` — короткие абстрактные идентификаторы `A`/`B`/`C`/`D` (по спецификации `references/scenario-yaml-spec.md` §1, D5). Расширенная метка вида `A_<short_label>` опциональна и берётся **из SSOT** (`scenarios/{slug}-{date}.yaml` → `matrix.scenario_triggers[*].label`), а не задаётся в этом скилле.

Скилл не предполагает семантику конкретных сценариев — все 4 ID обрабатываются симметрично. Семантику читай из SSOT scenarios YAML на момент запуска.

**Канонический список факторов** в `factor_betas` каждой позиции:
`sanctions`, `geopol`, `cbr_rate`, `usdrub`, `cnyrub`, `brent`, `xauusd`.

**Единицы β (контракт P0-1):** п.п. цены на ОДНУ единицу фактора в его собственной
единице. Для `sanctions`/`geopol` единица — интенсивность 1.0 по шкале −1…+1, то
есть бета банков ≈ −35, а не −0.35. Долевая запись отличается ×100 и зануляет
политический канал — `compute_per_position.py` откажется считать.
Отсутствующий в `sector-sensitivities.md` фактор означает β=0 для позиции, но запись ОПУСКАТЬ нельзя — пиши `0` явно. Это нужно для downstream-консистентности (`portfolio-integrated-view` ожидает фиксированный набор ключей).

---

### Полнота `sector_breakdown_pct`

`sector_breakdown_pct` должен **полностью покрывать позиции портфеля**:

```
Σ sector_breakdown_pct[*].weight_pct ≈ 100% (±2%)
```

База весов бумаг и секторов — позиции без кэша. `cash_rub_pct` и `blocked_pct` —
отдельные верхнеуровневые поля, доля портфеля с кэшем; в сумму секторов они не входят
и отдельной строкой сектора не дублируются.

1. Ключи секторов и подписи — закрытый список `references/sector-groups.yaml`; своих ключей не придумывать.
2. Фонды раскладываются по таблице `funds` того же файла (денежные — `money_market`, не сливаются с банками).
3. Фонд, которого в таблице нет, — сначала добавить его туда, затем считать.

**Контроль перед записью YAML:**

```python
covered = sum(s["weight_pct"] for s in sector_breakdown_pct.values())
assert 98.0 <= covered <= 102.0, f"Coverage {covered}% выходит за ±2%"
```

Если расхождение — найти потерянный сектор, прежде чем выдавать артефакт.
Типовые пропуски (по опыту прогона 2026-05-06):
- Healthcare/Фарма (MDMG, PRMD)
- Real Estate (DOMRF, GLRX, Rental PRO)
- Электроэнергетика (UPRO)
- Stock-funds (FINAMAR, SBGB, TLCB как фонды)

```yaml
---
# stress-{YYYY-MM-DD}-{slug}.yaml
schema_version: 2
type: portfolio-stress-test
date: {YYYY-MM-DD}
scenario_source: scenario-builder | forecast-confidence-applier | hypothesis-stress-tester | manual | hybrid
weight_type: equal | probability
portfolio_snapshot_id: portfolio-{date}.json
scenario_count: 4

scenarios:
  # ID-ы (A/B/C/D) — абстрактные, согласуются с SSOT scenarios YAML.
  # Семантика и `name` берутся из source_matrix; в скилле не предполагаются.
  D:
    name: "{из SSOT scenarios YAML}"
    p: 0.525                                     # вероятность; для equal-weighted: 0.25
    probability: 0.525                           # backward compat alias
    # ⚠️ v2: факторы задаются per horizon и ТОЛЬКО каноническими именами
    # (sanctions, geopol, cbr_rate, usdrub, cnyrub, brent, xauusd). Имена вида
    # sanctions_intensity / cbr_rate_delta_bp / usdrub_delta_pct движок молча
    # игнорирует → фактор считается нулём.
    factors_by_horizon:
      h6:  {sanctions: -0.05, geopol: -0.10, cbr_rate: -1.75, usdrub: 12.5, brent: -8.0}
      h12: {sanctions: -0.15, geopol: -0.20, cbr_rate: -2.50, usdrub: 18.0, brent: -12.0}
      h24: {sanctions: -0.30, geopol: -0.35, cbr_rate: -3.50, usdrub: 24.0, brent: -15.0}
    portfolio_level:
      expected_pct_pweighted: -2.5
      expected_pct_ci:                           # R1: CI на портфельном уровне
        lo: -8.0
        hi: 4.0
      delta_rub: -350000
    sector_breakdown:
      banks: -3.2
      oil_gas: -1.8
      # ... остальные секторы ...
  A:
    name: "{из SSOT scenarios YAML}"
    p: 0.08
    probability: 0.08
    factors:
      cbr_rate_delta_bp: -300
      usdrub_delta_pct: -8.0
      brent_usd: 80
    portfolio_level:
      expected_pct_pweighted: 15.0
      expected_pct_ci: {lo: 8.0, hi: 24.0}
      delta_rub: 1200000
    sector_breakdown:
      banks: 12.5
      # ...
  B:
    name: "{из SSOT scenarios YAML}"
    p: 0.15
    probability: 0.15
    factors:
      cbr_rate_delta_bp: 200
      usdrub_delta_pct: 35.0
      brent_usd: 55
    portfolio_level:
      expected_pct_pweighted: -28.0
      expected_pct_ci: {lo: -45.0, hi: -15.0}
      delta_rub: -2800000
    sector_breakdown:
      banks: -35.0
      # ...
  C:
    name: "{из SSOT scenarios YAML}"
    p: 0.225
    probability: 0.225
    factors:
      cbr_rate_delta_bp: 100
      usdrub_delta_pct: 22.0
      brent_usd: 70
    portfolio_level:
      expected_pct_pweighted: -8.0
      expected_pct_ci: {lo: -18.0, hi: -2.0}
      delta_rub: -800000
    sector_breakdown:
      banks: -10.5
      # ...

per_position:
  SBER:
    weight_pct: 12.46
    on_iis: false
    factor_betas:
      sanctions: -35         # п.п. на 1.0 интенсивности — НЕ доля (контракт единиц)
      geopol: -20            # там же; sector-sensitivities.md → «Контракт единиц»
      cbr_rate: 0.30
      usdrub: -0.10
      cnyrub: 0.0            # явно 0, не пропускать
      brent: 0.05
      xauusd: 0.0            # явно 0
    sanctions_position: 0.9   # P1-3: позиция на санкционной шкале; эхо из priors,
                              # присутствует только если поле задано
    factor_betas_method: "sector prior from sector-sensitivities.md (banks, elevated-rate context)"
    factor_betas_r2: null    # null в priors-only режиме (Phase 4.1)
    by_horizon:                  # v2: на каждый горизонт — свой блок
      h24:
        delta_pct_by_scenario:
          A: {value: -44.9, ci_pct: [-62.9, -26.9]}
          B: {value: -12.0, ci_pct: [-22.0, -2.0]}
          C: {value: 6.0, ci_pct: [-1.0, 13.0]}
          D: {value: 45.5, ci_pct: [27.2, 63.7]}
        expected_pct_pweighted:
          value: -1.4
          ci_pct: [-14.7, 12.0]
        tail_var_pct: -44.9
        tail_var_scenario_id: "A"
      # h6, h12 — той же формы
  # ...остальные позиции (все unblocked, value_rub > 0, не cash)...
  RU000A107RH8:                                  # пример облигации
    weight_pct: 0.42
    on_iis: true                                 # on_iis: true если хотя бы часть на ИИС-3
    # Бумага на двух счетах — ОДНА запись: weight_pct от полной стоимости
    # (main + iis_3), ноги схлопывает скрипт. Публиковать вес одного счёта
    # нельзя: 2026-08-04 так потерялось 0.33% позиционной части.
    factor_betas:
      sanctions: -0.10                           # у облигаций политическая β законно мала:
                                                 # −duration × Δspread_бп / 100
      cbr_rate: -0.50                            # основной драйвер для облигаций
      usdrub: 0
      brent: 0
    factor_betas_method: "duration-based, sector prior"
    factor_betas_r2: null                        # нет регрессионной истории
    delta_pct_by_scenario:
      D: {value: 8.5, ci_pct: [5, 12]}
      A: {value: 14.0, ci_pct: [10, 18]}
      B: {value: -12.0, ci_pct: [-18, -8]}
      C: {value: -5.0, ci_pct: [-9, -2]}
    expected_pct_pweighted:
      value: 5.2
      ci_pct: [-2, 11]
    tail_var_pct: -12.0
    tail_var_scenario_id: "B"

sector_breakdown_pct:
  Банки:
    weight_pct: 32.1
    expected_pct_pweighted: {value: -1.5, ci_pct: [-10, 8]}
  Облигации_RUB:
    weight_pct: 28.5
    expected_pct_pweighted: {value: 6.8, ci_pct: [3, 11]}
  # ...

top_risks:
  - {position: "SBER", scenario: "B", delta_pct: -38, weight_pct: 12.46}
  - {position: "LKOH", scenario: "B", delta_pct: -32, weight_pct: 9.12}
  # до 5 позиций

macro_blindspots:
  - {ticker: "OZON", reason: "Catalyst — выход в EBITDA-positive, operational milestone"}
  - {ticker: "MDMG", reason: "Catalyst — открытие новых клиник, не зависит от macro напрямую"}
  # ...позиции с factor_betas_r2 < 0.3 или все |beta| < 0.1

portfolio_pl_range_rub:
  min: -380000
  max: 120000
expected_pl_rub: null        # null если equal-weighted
avg_pl_rub_equal: -65000     # только для equal-weighted (не вероятностный)

concentration_ratio: 0.58    # доля портфеля, движущаяся однонаправленно
dominant_factor: brent
unmapped_tickers: []         # [] если все смаплены

# Метаданные факторов — viewer читает отсюда, не зашивает логику
# Перечислить ТОЛЬКО те факторы, которые реально используются в scenarios.*. factors
# Для нового фактора — добавить сюда; viewer автоматически подхватит
# unit — машинный код единицы (для скриптов); display_label — человекочитаемый
# ярлык единицы, viewer показывает его вместо unit (U3, Фаза 4.1 Блок D).
factor_definitions:
  cbr_rate:
    unit: "pct_delta"
    display_label: "п.п."
    if_positive: "рост ставки"
    if_negative: "снижение ставки"
  brent:
    unit: "pct_delta"
    display_label: "%"
    if_positive: "нефть дорожает"
    if_negative: "нефть дешевеет"
  usdrub:
    unit: "pct_delta"
    display_label: "%"
    if_positive: "рубль слабеет"
    if_negative: "рубль укрепляется"
  cnyrub:
    unit: "pct_delta"
    display_label: "%"
    if_positive: "рубль к юаню слабеет"
    if_negative: "рубль к юаню укрепляется"
  xauusd:
    unit: "pct_delta"
    display_label: "%"
    if_positive: "золото дорожает"
    if_negative: "золото дешевеет"
  sanctions:
    unit: "intensity_-1_to_1"
    display_label: "усл. шкала −1…+1"
    if_positive: "санкционное давление растёт"
    if_negative: "санкционное давление ослабевает"
  geopol:
    unit: "intensity_-1_to_1"
    display_label: "усл. шкала −1…+1"
    if_positive: "геополитический риск растёт"
    if_negative: "геополитический риск снижается"

caveats:
  - severity: HIGH
    message: |
      Macro factors confidence: ~0.40. Joint covariance estimated by analogy.
  - severity: MEDIUM
    message: |
      factor_betas estimated on 24mo window. Re-estimate каждые 6 мес.

# Метаданные для retrospective-forecast-audit
review_date: {YYYY-MM-DD + 6 months}
notes: ""
```

---

## Правила форматирования таблиц

1. **Знаки ΔP&L:** убыток = жирным если > 5% портфеля; прибыль = обычным
2. **Сортировка:** по абсолютному убытку в worst scenario (самый уязвимый — первый)
3. **Единицы:** RUB в тысячах (тыс. ₽ или k) для читаемости. Если позиция > 1 млн — в млн
4. **Облигации:** суффикс `_bond` в секторе; `_ofz` для госбумаг; `_corp` для корп.
5. **Фонды:** суффикс `_fund`
6. **Unmapped:** всегда в отдельных строках ВНИЗУ таблицы, зачёркнуты и с пометкой

## Confidence-индикаторы в таблице

| Символ | Значение |
|--------|---------|
| (без символа) | HIGH или MEDIUM confidence |
| ⚠️ | LOW confidence |
| ❓ | Расчёт невозможен (unmapped или недостаточно данных) |
| `(оцен.)` | Estimated duration (bonds) |
