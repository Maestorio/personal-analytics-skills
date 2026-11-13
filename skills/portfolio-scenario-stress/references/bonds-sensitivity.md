# Bonds Sensitivity

Облигации имеют принципиально другую модель чувствительности, чем акции. Основной фактор — ставка через дюрацию. Сектор эмитента вторичен (кроме кредитного риска).

---

## Основные компоненты

### 1. Процентный риск (Duration × Rate)

Формула ценовой чувствительности к ставке:

```
Δprice_pct ≈ −duration_years × (rate_bps_change / 100)
```

Примеры:
- ОФЗ 78729 (дюрация ≈ 8.5 лет, ставка ЦБ растёт на 100 б.п.): Δprice ≈ −8.5%
- ОФЗ 78621 (дюрация ≈ 2.5 лет, ставка −200 б.п.): Δprice ≈ +5.0%
- Корпоративная облигация (дюрация ≈ 1.5 лет, ставка +300 б.п.): Δprice ≈ −4.5%

**Дюрация из снапшота:** поле `duration_days` в holdings → `duration_years = duration_days / 365`.

Если `duration_days = null` — использовать эвристику по `maturity_date`:
- maturity < 1 года: duration_years = 0.5
- 1–3 года: duration_years = 1.5
- 3–7 лет: duration_years = 4.0
- >7 лет: duration_years = 7.0
- Флаг в выходе: `⚠️ duration_estimated`

**Convexity-поправка** (для больших изменений ставки):
При |rate_bps_change| > 300:
```
Δprice_pct ≈ −duration_years × Δrate + 0.5 × convexity × Δrate²
```
Для ОФЗ с дюрацией 8–10 лет: convexity ≈ 70–100 (bond math). Упрощённо: при снижении ставки на 300 б.п. эффект выше линейного на 2–4%.

---

### 2. Флоатеры (облигации с плавающей ставкой)

Признак в снапшоте: тикер содержит «Ф» или имя содержит «флоатер», или YTM не фиксированный.

**Чувствительность к ставке:** практически нулевая по цене (купон переменный).
```
Δprice_pct ≈ −0.3 × (rate_bps_change / 100)   # только спред и ликвидность
```

Но **купонный доход** меняется пропорционально ставке:
- Ставка +200 б.п. → купон вырастет через 1–2 купонных периода
- Для P&L в периоде: рост купона = +rate_bps_change / 100 × (купонный период / год)

**В рамках этого скилла:** флоатеры считаем с `Δprice_pct ≈ 0` при изменении ставки. Подписывать `(флоатер — чувствительность цены к ставке близка к нулю)`.

---

### 3. Валютный риск (FX-облигации, замещайки)

Для облигаций с `nominal_currency != "RUB"`:

```
Δprice_rub_pct = Δprice_ccy_pct + Δfx_pct

где:
  Δprice_ccy_pct = −duration_years × rate_usd_bps / 100  (для USD-бондов)
  Δfx_pct = usdrub_pct_change (для USD-номинированных)
           = cnyrub_pct_change (для CNY-номинированных)
```

**Замещайки (nominal_currency = "USD"):**
- При ослаблении рубля на 15%: value_rub растёт на ~15% (прямой FX-эффект)
- При росте ставки USD на 50 б.п.: незначительный price impact по USD-телу
- Итоговый P&L в RUB = FX-переоценка + небольшой USD-ставочный эффект

**Важно:** в сценариях rate_bps_change = изменение ставки ЦБ РФ, **не USD Fed Funds**. Для USD-облигаций применять rate_bps_change только если сценарий явно содержит изменение американских ставок. В большинстве российских сценариев rate = ЦБ РФ → не применять к USD-телу замещаек.

**Практическое правило для замещаек:**
```
Δprice_rub_pct ≈ usdrub_pct_change  (FX доминирует)
```

---

### 4. Кредитный риск (Credit Spread)

Упрощённая модель через rating tier эмитента.

> ⚠️ **Колонки ниже — это НЕ беты.** Это расширение кредитного спреда в базисных
> пунктах при ужесточении на 1.0 интенсивности, **знак «+» = спред расширяется**.
> Прежняя редакция файла держала здесь «credit β» с отрицательными значениями и
> перепутанным знаком в формуле. Подставлять числа из таблицы прямо в
> `factor_betas` **нельзя** — сначала перевести формулой ниже, и получится
> отрицательная и малая по модулю бета.

| Rating Tier | Признаки | Spread premium (б.п.) | Δspread при ужесточении на 1.0, б.п. (>0 = расширение) | То же по geopol, б.п. |
|-------------|----------|----------------------|---------------------|-------------------|
| **Tier 1: ОФЗ** | Госбумаги; SU-тикеры | 0 (базовый) | +5 (суверенный) | +3 |
| **Tier 2: Системообразующие** | SBER, LKOH, GAZP, ROSN, RTKM | +100–150 б.п. | +10 | +5 |
| **Tier 3: Качественные корп.** | ВТБ, Атомфлот, Дом.рф, Регионы | +200–300 б.п. | +15 | +10 |
| **Tier 4: Mid-grade** | SMLT, MAGN, HYDR, МТС-Банк | +350–550 б.п. | +20 | +15 |
| **Tier 5: High-yield / проблемные** | Малые эмитенты, B-рейтинг | +700–1500 б.п. | +35 | +25 |

**Как получить политическую β облигации** (контракт единиц — п.п. цены на 1.0
интенсивности, см. `sector-sensitivities.md` → «Контракт единиц»):

```
β_sanctions = −duration_years × Δspread_sanctions_bps / 100
β_geopol    = −duration_years × Δspread_geopol_bps / 100
```

Пример: Tier 2, дюрация 3 года → `β_sanctions = −3 × 10/100 = −0.3` п.п. на
единицу интенсивности. Знак минусовой: ужесточение (`intensity > 0`) расширяет
спред и роняет цену; смягчение даёт симметричный плюс.

**У облигаций политические беты законно малы** (доли п.п.) — их цену определяют
ставка и валюта, а не санкционный дил. Это НЕ та долевая шкала, которую чинил
контракт единиц: акции считаются десятками п.п., облигации — долями, и обе записи
в одних и тех же единицах. Умножать бету облигации на 100 не нужно.

> ⚠️ **Магнитуда Δspread в таблице — унаследованная и, вероятно, заниженная.**
> Она переписана из прежней формулы `credit_beta × 100` бит-в-бит, но против
> факта 2022 (спреды RU-корпората разъезжались на сотни б.п.) выглядит слабо.
> Пере-калибровка на event-study — задача **PSS-5** в бэклоге репозитория
> (отдельная от PSS-4: та калибровала долевые инструменты и закрыта).
> Пока считать эти числа LOW-confidence и не строить на них выводов.

---

## Полная формула для облигации

```python
def bond_price_change(holding, scenario, current_cbr_rate):
    duration_years = holding.get("duration_days", None)
    if duration_years:
        duration_years = duration_years / 365
    else:
        duration_years = estimate_duration(holding["maturity_date"])
        flag_estimated = True

    is_floater = is_floater_bond(holding)
    nominal_currency = holding.get("nominal_currency", "RUB")

    # 1. Процентный риск
    if is_floater:
        price_change_rate = -0.3 * scenario["rate_bps_change"] / 100
    elif nominal_currency == "RUB":
        price_change_rate = -duration_years * scenario["rate_bps_change"] / 100
    else:
        price_change_rate = 0  # USD/CNY-тело: ЦБ РФ не применяем

    # 2. Валютный риск
    if nominal_currency == "USD":
        price_change_fx = scenario.get("usdrub_pct_change", 0)
    elif nominal_currency == "CNY":
        price_change_fx = scenario.get("cnyrub_pct_change", 0)
    else:
        price_change_fx = 0

    # 3. Кредитный риск: интенсивность −1..+1, а не binary-флаг
    tier = get_credit_tier(holding["ticker"])
    price_change_credit = (
        -duration_years * DSPREAD_SANCTIONS_BPS[tier] / 100 * scenario.get("sanctions", 0)
        - duration_years * DSPREAD_GEOPOL_BPS[tier] / 100 * scenario.get("geopol", 0)
    )

    total_pct = price_change_rate + price_change_fx + price_change_credit
    return total_pct
```

---

## Определение типа облигации из снапшота

| Поле | Значение | Тип |
|------|----------|-----|
| `ticker` starts with `SU` | — | ОФЗ (Tier 1) |
| `nominal_currency = "USD"` | — | Замещайка USD |
| `nominal_currency = "CNY"` | — | CNY-облигация |
| `nominal_currency = "EUR"` | — | EUR-замещайка |
| `name` содержит «флоатер» или «Ф» в ISIN | — | Флоатер |
| `ytm_pct = null` и `maturity_date = null` | — | Вечный/бессрочный; дюрация ≈ 10–15 лет |

---

## YTM vs Price Impact

Скилл оценивает **цены** (mark-to-market), не YTM. YTM из снапшота используется только для валидации: если YTM значительно выше ключевой ставки, облигация торгуется с дисконтом (возможен высокий кредитный риск).

**Правило:** если `ytm_pct > cbr_rate + 5 п.п.` → повысить credit tier на 1 шаг (более консервативная оценка).

---

## Канонические `factor_betas_method` строки

Для блока `per_position.<ticker>.factor_betas_method` использовать одну из шаблонных строк (важно для consistency между запусками и для downstream-парсинга в `portfolio-integrated-view`):

| Тип облигации | Канонический шаблон | Пример |
|---------------|---------------------|--------|
| ОФЗ (известная duration) | `"OFZ duration {N}yr"` | `"OFZ duration 8yr"` |
| ОФЗ (estimated duration) | `"OFZ duration {N}yr, ⚠️ duration_estimated"` | `"OFZ duration 4yr, ⚠️ duration_estimated"` |
| USD-замещайка | `"USD-замещайка Tier {tier}, FX-pass-through"` | `"USD-замещайка Tier 2, FX-pass-through"` |
| EUR-замещайка | `"EUR-замещайка Tier {tier}, FX-pass-through (EUR/RUB)"` | `"EUR-замещайка Tier 2, FX-pass-through (EUR/RUB)"` |
| CNY-облигация | `"CNY-облигация Tier {tier}, FX-pass-through (CNY/RUB)"` | `"CNY-облигация Tier 3, FX-pass-through (CNY/RUB)"` |
| Корп RUB | `"corp-RUB rating-tier {AAA\|AA\|A\|BBB\|BB\|B\|HY}, duration {N}yr"` | `"corp-RUB rating-tier A, duration 2yr"` |
| Флоатер RUB | `"floater RUB, rate-pass-through (price ≈ const)"` | `"floater RUB, rate-pass-through (price ≈ const)"` |
| Вечный/бессрочный | `"perpetual bond, duration ≈ {N}yr (estimated)"` | `"perpetual bond, duration ≈ 12yr (estimated)"` |

**Tier** берётся из таблицы кредитного риска выше (Tier 1 = ОФЗ, Tier 2 = системообразующие и т.д.).

**Когда `duration_estimated`:** если `duration_days` в snapshot отсутствует/null — обязательно добавлять флаг `⚠️ duration_estimated` в method-строке.

---

## Confidence для облигаций

- ОФЗ с известной дюрацией: `confidence = HIGH`
- ОФЗ с estimated дюрацией: `confidence = MEDIUM`, флаг `⚠️ duration_estimated`
- Корпоративные (Tier 2–3): `confidence = MEDIUM`
- Высокодоходные (Tier 4–5) или замещайки с неясной ликвидностью: `confidence = LOW`
- Флоатеры при изменении ставки: `confidence = LOW` (модель упрощена)
