# Sector-Factor Matrix — macro-forecast-chain

## Маппинг тикер → сектор (MOEX)

### Нефтегаз
```
LKOH, ROSN, SNGS, SNGSP, TATN, TATNP, BANE, BANEP, RNFT, NVTK
```

### Банки и финансы
```
SBER, SBERP, VTBR, AFKS, TCSG, BSPB, MOEX, RENI, SFIN
```

### Металлы и горнодобыча
```
GMKN, NLMK, MAGN, CHMF, ALRS, POLY, MTLR, MTLRP, RASP, RUAL, ENPG
```

### IT и телеком
```
YNDX, VKCO, HEAD, OZON, POSI, ASTR, DIAS, MTSS, RTKM, RTKMP
```

### Девелопмент и недвижимость
```
PIKK, SMLT, LSRG, ETLN
```

### Потребительский сектор
```
MGNT, FIVE, X5, FIXP, BELU, MDMG, GCHE
```

### Электроэнергетика
```
HYDR, FEES, IRAO, MSNG, TGKA, TGKB, OGKB, LSNG, LSNGP, MRKP, UPRO
```

### Удобрения / химия
```
PHOR, AKRN, KAZT, KAZTP
```

### Транспорт
```
FLOT, TRMK, NMTP, FESH
```

### Золотодобыча (производители)
```
PLZL, UGLD, SELG
```
Чистые золотодобытчики. Главный P&L driver — мировая цена золота (`xauusd`),
а не общая «металлы». NB: `POLY` (Polymetal) после реструктуризации — не на
MOEX, в матрице не учитывается.

### Золото (фонды)
```
TGLD, GOLD
```

### Облигации RUB (ОФЗ + корпораты)
```
Любой тикер с asset_type: "bond" и currency: "RUB"
SU26* (ОФЗ), RU000A* (корпораты RUB)
```

### Облигации FX
```
Любой тикер с asset_type: "bond" и currency != "RUB"
RU000A* (корпораты USD/EUR/CNY), XS* (еврооблигации)
```

### Облигации FX-synthetic (замещающие)
```
asset_type: "bond" и currency: "RUB", но в name/issuer есть маркеры замещения:
"ЗО" / "-Д" / "-Е" / "ЗамО" / "Замещ" / "USD-link" / "EUR-link"
Эмитенты-якоря: ГазКЗ, РФ ЗО, ЛУКОЙЛ ЗО, ГТЛК ЗО (расширять по мере появления).
```
Номинально RUB-бонды, фактическая выплата привязана к курсу USD/EUR. Реакция на
сценарии — через `usdrub` (USD-замещения) или `cnyrub`/`usdrub` (EUR-замещения,
≈ EUR/USD≈1 при стрессе), **не** через `cbr_rate`. Под Sc-D (слабый рубль) —
выигрывают, не проигрывают.

### Фонды смешанные
```
SBMX, SBGB, TMOS, EQMX, OPNF — по составу underlying
```

### Рентал / ЗПИФ недвижимости
```
RU000A106540 (Рентал ПРО) и аналоги
```

---

## Маппинг сектор → обязательные факторы

| Сектор | Обязательные факторы | Опциональные |
|--------|---------------------|-------------|
| Нефтегаз | brent, urals_discount, usdrub, sanctions | geopolitics |
| Банки/финансы | cbr_rate, inflation_ru | budget_deficit |
| Металлы | usdrub, sanctions | geopolitics, cbr_rate |
| IT/телеком | usdrub, sanctions | cbr_rate |
| Девелопмент | cbr_rate, inflation_ru | — |
| Потребительский | inflation_ru, usdrub | cbr_rate |
| Электроэнергетика | cbr_rate, inflation_ru | budget_deficit |
| Удобрения/химия | usdrub, sanctions | brent |
| Транспорт | usdrub, sanctions, brent | — |
| Золотодобыча | xauusd, usdrub, sanctions | geopolitics, cbr_rate |
| Золото (фонды) | xauusd, usdrub | geopolitics |
| Облигации RUB | cbr_rate, inflation_ru, budget_deficit | — |
| Облигации FX | usdrub, cnyrub, sanctions | cbr_rate |
| Облигации FX-synthetic | usdrub, sanctions | cnyrub, cbr_rate |
| Фонды смешанные | определяется по underlying | — |
| Рентал/ЗПИФ | cbr_rate, inflation_ru | — |

---

## Алгоритм определения необходимых факторов

```python
required_factors = set()

for ticker in portfolio_holdings:
    sector = get_sector(ticker)
    if sector is not None:
        required_factors.update(MANDATORY_FACTORS[sector])
    else:
        log_warning(f"UNMAPPED: {ticker} — добавить в таблицу вручную")

# geopolitics и sanctions — всегда добавлять как базовые
# если есть хотя бы один нефтегазовый, металлургический, IT или FX-актив
base_sectors = {'oil_gas', 'metals', 'it', 'bonds_fx', 'transport', 'chemicals'}
if any(get_sector(t) in base_sectors for t in portfolio_holdings):
    required_factors.add('geopolitics')
    required_factors.add('sanctions')
```

---

## Секторальные прогнозы — когда нужны

Секторальные прогнозы (sector_*) добавляются в пайплайн при выполнении условий:

1. Доля сектора в портфеле > 10% по рыночной стоимости
2. ИЛИ пользователь явно запросил секторальный анализ
3. ИЛИ в секторе произошли структурные изменения (новые санкции по отрасли,
   изменение дивидендной политики ключевого эмитента)

Для каждого секторального прогноза — указать конкретные эмитенты из портфеля,
чтобы FCA мог сфокусироваться на релевантных источниках.

---

## Обработка UNMAPPED тикеров

Если тикер не найден в таблице выше:
1. Флаг `⚠ UNMAPPED: {ticker}` в coverage report
2. Попытка определить сектор по полю `sector` в снапшоте портфеля (если есть)
3. Если сектор не определён — исключить из factor-требований, но сохранить флаг
4. В caveats матрицы: «{ticker} не включён в factor-требования — сектор не определён»

Пользователь может указать сектор вручную в Checkpoint 1.

---

## Механизм расширения — sector-overrides.yaml

Статическая матрица покрывает ~90% стандартных позиций на MOEX. Для остальных —
пользовательский override файл в `Claude-Memory/sector-overrides.yaml`.

### Формат файла

```yaml
# Claude-Memory/sector-overrides.yaml
# Создаётся/обновляется macro-forecast-chain при обработке UNMAPPED тикеров.
# Редактируется вручную без ограничений.

version: 1
last_updated: "2026-05-02"

overrides:
  - ticker: IVAT
    sector: tech
    note: "IVA Technologies — ВКС, IPO 2024. Добавлен 2026-05-02."

  - ticker: DATA
    sector: tech
    note: "Аренадата — СУБД. Добавлен 2026-05-02."

  - ticker: SOFL
    sector: tech
    extra_factors: [inflation_ru]
    note: "Софтлайн — дистрибуция ПО. Чувствителен к инфляции через импорт."

  - ticker: RU000A108G35
    sector: bonds_rub
    asset_type: bond
    note: "Замещайка Газпром ЗО26-1-Д2. Валюта расчётов RUB."

  - ticker: RU000A105SG1
    sector: bonds_fx
    asset_type: bond
    currency: USD
    note: "Замещайка Лукойл. FX-переоценка через usdrub."

  - ticker: RU000A106540
    sector: bonds_rub
    asset_type: bond
    extra_factors: [inflation_ru]
    note: "Рентал ПРО ЗПИФ — рентная недвижимость, доход привязан к инфляции."
```

### Поля

| Поле | Обязательно | Описание |
|------|-------------|----------|
| `ticker` | да | Тикер MOEX или ISIN |
| `sector` | да | Сектор из таблицы выше |
| `asset_type` | нет | `stock`, `bond`, `fund`; если не указан — из снапшота |
| `extra_factors` | нет | Дополнительные факторы поверх стандартных для сектора |
| `required_factors` | нет | Полная замена стандартного набора факторов сектора |
| `currency` | нет | Для bonds_fx: `USD`, `EUR`, `CNY` |
| `note` | нет | Свободный комментарий (дата, причина) |

### Приоритет при конфликтах

Если один тикер есть и в матрице, и в overrides — override имеет приоритет.
`extra_factors` добавляется к стандартным факторам сектора.
`required_factors` полностью заменяет стандартный набор.

### Когда создаётся автоматически

macro-forecast-chain создаёт/обновляет файл при обработке UNMAPPED тикера,
если пользователь подтвердил inference-результат. Существующие записи не затираются.
