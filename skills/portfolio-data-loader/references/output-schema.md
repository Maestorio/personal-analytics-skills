# JSON-схема снапшота портфеля v2

Полный формат выходного `portfolio-{YYYY-MM-DD}.json` (schema_version 2.0). Этот файл потребляется:
- `ru-portfolio-advisor` (рекомендации по ребалансировке, анализ позиций)
- `portfolio-scenario-stress` (сценарный анализ влияния макро-факторов)
- `portfolio-integrated-view` (синтетический integrated view)

---

## Верхний уровень

```json
{
  "schema_version": "2.0",
  "as_of_date": "2026-05-03",
  "generated_at": "2026-05-03T19:57:00",
  "input_files": {
    "trades": "trades_portfolio_707160-7.xlsx",
    "balance": "Общий баланс.numbers"
  },
  "holdings": [...],
  "cash": {...},
  "returns": {...},
  "per_instrument_xirr": {...},
  "per_instrument_xirr_closed": {...},
  "iis_trades_source": "export|carried|none",
  "iis_positions_source": "trades_export|balance|carried|none",
  "iis_account_flows": {...},
  "recent_trades_window": {...},
  "ie_model": {...},
  "ie_actual": {...},
  "ie_summary": {...},
  "balance_summary": {...},
  "corrections_log": [...],
  "data_quality_flags": [...],
  "type_check": {...},
  "known_splits": {...}
}
```

`type_check` (`build_snapshot.py`; скилл-сборка блок не пишет): сверка типа каждого холдинга —
`{"cache": путь|null, "online": bool, "fetched": [тикеры], "failed": [тикеры], "changes": [{ticker, name,
was, now, moex, heur, reason}]}`. `was` — тип бумаги в прошлом снапшоте (тикер, у облигаций ещё ISIN),
`now` — в новом, `moex` — тип из справочника `Portfolio/security-types.json`, `heur` — эвристика
`classify_instrument_type` без переопределений. `reason`: `prev_vs_now` (тип сменился против прошлого
снапшота) или `moex_vs_heuristic` (бумага новая, биржа и эвристика разошлись — сработала биржа).
`online` — ходила ли сборка в ISS (только сайт; повтор пакета и `--no-moex` — нет).

`known_splits` (`build_snapshot.py`; скилл-сборка блок не пишет): откуда взят реестр сплитов —
`{"source": "builtin"|"file", "file": "known-splits.json"|null, "count": N}`. `builtin` — только встроенный
набор; `file` — встроенный плюс файл `Portfolio/known-splits.json`; `count` — число сплитов в действующем реестре.

---

## `holdings` — массив позиций

Каждая позиция (акции, фонды, другие бумаги):

```json
{
  "ticker": "SBER",
  "isin": "RU0009029540",
  "name": "Сбербанк",
  "qty": 150,
  "avg_cost_rub": 285.40,
  "avg_cost_source": "balance",     // акции: "balance" | "value_over_qty" (fallback = ТЕКУЩАЯ цена; + warn avg_cost_fallback_value_over_qty)
  "current_price": 328.50,
  "current_price_source": "moex_iss",
  "current_price_ts": "2026-05-03T19:15:00",
  "value_rub": 147825.00,
  "currency": "RUB",
  "asset_type": "stock",
  "sector": null,
  "sector_ru": null,
  "account": "main",
  "status": "normal",
  "is_blocked": false,
  "nominal_currency": null,
  "ytm_pct": null,
  "ytm_source": null,
  "listing_date": "2011-11-21",
  "listing_age_quarters": 58,
  "lot_size": 10
}
```

`sector` / `sector_ru` (PDL-I, 2026-08-27): `sector` — ВСЕГДА машинный canon-ключ
(словарь macro-forecast-chain/stress: `banks_finance`, `it_telecom`, `oil_gas`, ...),
заполняется из `sector-overrides.yaml` (`_apply_sector_overrides` в `assemble_snapshot.py`),
если задан. `sector_ru` — отдельное поле для отображаемого ярлыка (словарь IntelInvest,
например «Финансовый»), берётся из `sector_ru` записи overrides; `null`, если ярлыка для
тикера не задано (переводов не выдумываем — потребитель отображения фоллбэчит на `sector`).
Оба поля независимы: override с одним `sector` без `sector_ru` заполняет только первое.
Старые снапшоты (до этой правки) несли русский ярлык прямо в `sector` — при чтении такого
артефакта потребители не падают, но `sector` там не машинный ключ (снапшот нужно пересобрать).

`listing_date` / `listing_age_quarters` (только stock, 2026-07): первый торговый
день бумаги на MOEX (`/history/.../{secid}/dates.json` через moex_quotes weekly)
и возраст листинга в полных кварталах. Потребитель — IPO-гейт advisor (правило 23:
`< 8 кварталов → post_ipo_guard, BUY/ADD запрещён без явного override`). Сбой
запроса → оба `null` (advisor проверяет провенанс вручную для кандидатов на покупку).

`lot_size` (только stock, 2026-10-13): лот MOEX (`LOTSIZE` через moex_quotes). Потребитель —
колонка «Сейчас» в «Долях и целях» вьюера и `gate_aware_sizing.py --auto` (лоты покупки
округляются вниз, среза — вверх). Нет котировки/битое значение → `null` (лоты не считаются,
вьюер показывает сумму с пометкой «лот неизвестен"). Старые снапшоты поля не несут.

Значения `asset_type`: `"stock"`, `"bond"`, `"fund"`, `"other"`.
Значения `account`: **`"main"`, `"iis_3"`** (underscore, не `iis3`).
Значения `current_price_source`: `"moex_iss"`, `"last_trade"`, `"cost_basis"`, `"unavailable"`.
`current_price_basis` (с 2026-10-21; только при котировке MOEX): `"last"` — цена последней сделки дня, `"prev_close"` — сделок сегодня ещё не было (прогон до открытия торгов, неликвид), взята цена закрытия прошлой сессии; источник при этом остаётся `"moex_iss"`. `null` — цены MOEX нет. Старые снапшоты поля не несут.

### Статус позиции (SSOT, 2026-07)

`status` ∈ `"normal" | "blocked" | "distressed"` — канонический статус позиции.
Назначается из **ручного** реестра `KNOWN_POSITION_STATUS` (`scripts/assemble_snapshot.py`,
ключ ticker/ISIN, аналог `KNOWN_SPLITS`) — MOEX ISS такие статусы автоматически не отдаёт:

- `normal` — дефолт;
- `blocked` — торги/распоряжение заблокированы (НРД, санкционная заморозка).
  В реестре: 16 замороженных иностранных акций СПб-биржи (BAC…C, RTX, Z;
  заморозка 2022, оценка по котировке 21.02.2022);
- `distressed` — торгуется, но эмитент/потоки под угрозой (национализация,
  судебная блокировка выплат, преддефолт). Пример: `RU000A105GN3` БорецКЗО26 —
  эмитент национализирован 27.03.2026, купоны физлицам заблокированы судом.

Non-normal позиции несут `status_note` (дата + причина + ссылка из реестра;
непроверенная атрибуция помечается «источник не верифицирован»).
`is_blocked` сохранён для обратной совместимости, но **производный**:
`is_blocked == (status == "blocked")` — читать статус нужно из `status`.
`FINAMAR` не в реестре (нормальный российский фонд с `cost_basis`-ценой —
владелец ведёт вручную); автоэвристики «cost_basis → blocked» нет сознательно.

Замороженные иностранные **фонды** (FinEx/RSH*/TBIO) и мелкие акции вне
баланса приходят в holdings из `returns.snapshot_current` (билдер
`_build_blocked_positions`) со `status=blocked`, реальными qty (ложные
Корректировки-синхронизации по blocked-бумагам фильтруются в `apply_corrections`) и
**консервативной оценкой 0** (`--blocked-value zero`; last_trade для FinEx
ненадёжен — сплит-пары, см. SKILL Шаг 6). Они видимы по qty, но в доли
стоимости `by_status.blocked` входят нулём, пока оценка не сверена вручную.

Топ-уровневый блок `status_summary` — канонические доли для downstream
(stress / integrated-view / coherence-audit §3 берут blocked/distressed отсюда;
snapshot и stress теперь сходятся: blocked 1.76% на 2026-07-02):

```json
"status_summary": {
  "total_value_rub": 40802331.24,
  "by_status": {
    "normal":     {"value_rub": 39615372.96, "pct": 97.09, "count": 70},
    "blocked":    {"value_rub": 717634.74,   "pct": 1.76,  "count": 16,
                   "tickers": ["BAC", "PEP", "KMB", "SYY", "RTX", "ABT", "EWBC", "EMR",
                               "MS", "KO", "HBAN", "GD", "Z", "BMY", "PFE", "C"]},
    "distressed": {"value_rub": 469323.54,   "pct": 1.15,  "count": 1, "tickers": ["RU000A105GN3"]}
  }
}
```

`pct` — доля от суммарной стоимости holdings; `count` — число записей
(main+iis_3 считаются отдельно), `tickers` — уникальные тикеры (только non-normal).

### ИИС-3 split (v2)

Если облигация разделена между обычным счётом и ИИС-3 — **две отдельные записи** с одним ticker:

```json
{
  "ticker": "RU000A1038V6",
  "name": "ОФЗ 78714",
  "qty": 80,
  "value_rub": 147350.40,
  "asset_type": "bond",
  "account": "main",
  ...
},
{
  "ticker": "RU000A1038V6",
  "name": "ОФЗ 78714",
  "qty": 130,
  "value_rub": 239444.40,
  "asset_type": "bond",
  "account": "iis_3",
  ...
}
```

Источник данных для split: из `portfolio.json` (промежуточный файл `parse_portfolio.py`):
- `Итого без ИИСа` → `value_rub` main-записи; qty = `Всего` − `ИИС`
- `Итого на ИИС` → `value_rub` iis_3-записи; qty = `ИИС`

### Дополнительные поля для облигаций

Все bond-поля обогащаются из MOEX ISS (`moex_quotes.py`, профиль `weekly`) во время
сборки снапшота — viewer читает их офлайн из `holding`, без браузерного fetch (I-1).

```json
{
  "ticker": "SU26243RMFS4",
  "asset_type": "bond",
  "account": "iis_3",
  "nominal_currency": "RUB",
  "nominal": 1000.0,
  "ytm_pct": 14.82,
  "ytm_source": "moex_iss",
  "coupon_pct": 9.8,
  "coupon_freq_per_year": 2,
  "next_coupon_date": "2026-07-15",
  "accrued_int": 12.34,
  "maturity_date": "2043-07-19",
  "offer_date": null,
  "duration_days": 3200
}
```

| Поле | Источник MOEX ISS | Примечание |
|---|---|---|
| `nominal` | `FACEVALUE` | номинал; fallback на `Номинал` из balance |
| `coupon_pct` | `COUPONPERCENT` | купонная ставка, % годовых |
| `coupon_freq_per_year` | `COUPONPERIOD` | `round(365 / период_дней)`; null если период не отдан |
| `next_coupon_date` | `NEXTCOUPON` | дата следующего купона |
| `accrued_int` | `ACCRUEDINT` | НКД на дату снапшота. **Единица — ВСЕГДА рубли за бумагу**, в т.ч. у замещаек (валюта расчётов MOEX). Верифицировано на portfolio-2026-07-02: `value_rub/qty = price/100 × nominal × fx + accrued_int(RUB)` сходится ±0.1 п.п. на RUB-бумагах и даёт спред implied-курса 0.8% на USD |
| `ytm_pct` | `YIELD` | доходность к погашению |
| `duration_days` | `DURATION` | дюрация в днях |
| `maturity_date` | `MATDATE` | погашение; fallback на `Дата погашения` |
| `offer_date` | `OFFERDATE`/`BUYBACKDATE` | оферта; fallback на `Дата оферты` |

Если MOEX ISS не вернул данные по облигации — bond-поля `null` (не угадываются),
событие в `data_quality_flags`. **Цена при этом не остаётся null**: с 2026-07
`assemble_snapshot.py` детерминированно выводит implied-цену из стоимости позиции —
`current_price = (value_rub/qty − accrued_int) / (nominal × fx_ЦБ) × 100`,
`current_price_source: "implied_from_value"`; если НКД неизвестен — цена «грязная»,
флаг `current_price_implied_dirty: true` (завышение ≤ купон/частота). Нет курса
валюты → цена null + warn-флаг `no_fx_for_implied_price`.

### `fx_rates_used` — курсы ЦБ на дату снапшота (2026-07)

Top-level блок; источник — `portfolio_returns.py` (`fx_rates_asof`, кэш+bundled+live ЦБ). Ключи — только валюты
держимых бумаг (номинал облигаций + валюта позиций, кроме RUB/SUR; любые, что публикует ЦБ — KZT и т. д.), не фиксированный
список; курс за единицу (Nominal учтён). Валюта без курса ЦБ в ±30 дней — `null` и блок `fx_rates_missing`, не курс 1.0:

```json
"fx_rates_used": {
  "USD": {"rate": 78.27, "rate_date": "2026-07-02", "source": "cbr"},
  "EUR": null,     // сбой по валюте — потребители обязаны флагом отметить
  "CNY": {"rate": 10.9, "rate_date": "2026-07-02", "source": "cbr"}
}
```

Потребители: implied-цена замещаек, `bond_cashflow_calendar`, downstream-аналитика FX.

### `bond_cashflow_calendar` — контрактный денежный поток облигаций (2026-07)

Top-level блок: купоны (факт. расписание от `next_coupon_date`, шаг `12/freq` мес)
и погашения по номиналу на 12 мес вперёд; **оферта — отдельным `kind: offer`**
(пут держателя, потенциальный приток — НЕ смешивать с гарантированными).
FX-потоки в рублях по текущему курсу ЦБ (`fx_rate_used` в каждой строке detail).

```json
"bond_cashflow_calendar": {
  "horizon_months": 12,
  "as_of": "2026-07-02",
  "by_month": {"2026-07": {"coupons_rub": 144631.5, "redemptions_rub": 0.0, "offers_rub": 783000.0}},
  "totals": {"coupons_rub": ..., "redemptions_rub": ..., "offers_rub": ...},
  "detail": [{"ticker": "...", "name": "...", "date": "2026-12-29", "kind": "coupon|redemption|offer",
              "amount_rub": 35221.5, "currency": "USD", "fx_rate_used": 78.27, "flags": []}],
  "flags": ["<ticker>: нет курса EUR — потоки не посчитаны"],   // честно, не тихий ноль
  "notes": ["..."]
}
```

Честность: флоатеры — по текущей ставке купона (флаг), амортизация v1 не покрыта,
отсутствие частоты/qty/курса — строка во `flags`. Потребитель — вкладка «Облигации»
HTML-viewer (≥2.6.0, офлайн из снапшота); кросс-чек — купонная компонента
`bond_carry` stress за 12 мес должна сходиться с календарём по RUB-бумагам.

### Подтипы облигаций (плановые корзины, 2026-08)

Для облигаций дополнительно прокидываются поля плановой корзины из вкладки
«Облигации» Numbers-файла (колонки `Тип`/`Подтип`/`Рейтинг`, **не** таблица
«План по Облигациям» — это две разные таблицы, см. `parsing-numbers.md`):

```json
{
  "ticker": "SU29014RMFS0",
  "asset_type": "bond",
  "plan_bucket": "ОФЗ",
  "plan_subtype": "Флоат",
  "plan_bucket_key": "ОФЗ/Флоат",
  "credit_rating_file": null
}
```

| Поле | Источник | Примечание |
|---|---|---|
| `plan_bucket` | «Облигации».`Тип` | `USD` \| `EUR` \| `CNY` \| `ОФЗ` \| `КОРП` |
| `plan_subtype` | «Облигации».`Подтип` | `null` для валютных; `>10`\|`<10`\|`Флоат` для ОФЗ; `AA+`\|`A`\|`B+`(\|`Флоат`) для КОРП |
| `plan_bucket_key` | производное | `"{Тип}/{Подтип}"` (`"ОФЗ/>10"`) для ОФЗ/КОРП, просто `"{Тип}"` (`"USD"`) для валютных без подтипа |
| `credit_rating_file` | «Облигации».`Рейтинг` | детальный рейтинг из файла (`AAA`…`B-`), пользователь ведёт вручную. `credit_rating` (обогащённое поле weekly-review) остаётся `TODO_LLM` — это два разных поля, см. `bond-subtypes-plan.md` §4.1/Q5 |

Корзина выводится из данных Мосбиржи и рейтинга; `plan_bucket_key` остаётся итоговым, остальное — как получен:

| Поле | Значение |
|---|---|
| `bucket_source` | `iss` (валюта · ОФЗ) · `rating` (КОРП по лестнице; рейтинг — последний обзор облигаций, затем `plan.bonds[ISIN].rating`) · `manual` (`plan.bonds[ISIN].manual`) · `plan` (по плану: выведенная расходится, вывести нельзя или нет справочника) |
| `bucket_derived` | выведенный ключ (`"ОФЗ/>10"`) или `null` |
| `bucket_reason` | причина словами: «ОФЗ, до погашения 12,3 г.», «КОРП, рейтинг AA- (АКРА, 12.09.2026)», «валюта номинала USD», «вручную: …» |
| `avg_price_pct` · `avg_cost_rub` · `avg_cost_source` · `avg_includes_accint` | средняя цена покупки по сделкам счёта (WACC): % номинала без НКД · ₽ за бумагу без НКД · `trades`/`carried` · true, если в сделке нет цены |
| `locked_pct` · `locked_real_pct` | «При покупке»: IRR(потоки счёта по бумаге: покупки −, продажи/купоны/амортизации/погашения + ; плюс будущие купоны и погашения по графику MOEX на количество счёта), % годовых; `locked_real_pct` — только линкеры (будущие потоки без индексации); `null` — нет графика/сети/потоков счёта. Основной счёт: суммарные потоки бумаги минус потоки ИИС-3 (как `per_instrument_xirr.by_account`); ИИС-3: `returns.by_account.iis_3.per_bond[].locked_pct` |

`bond_bucket_check` (снапшот): `{"changes": [{isin, name, was, now, reason}], "missing": [{isin, name, code, reason}],
"derived": N, "attrs_missing": bool}` — `changes` — выведенная корзина расходится с плановой (флаг `bond_bucket_changed`,
решает владелец); `missing` — корзину вывести нельзя. Правило вывода и приоритет источников — SSOT `bond-subtypes-plan.md` §4.5.

⚠️ Имена плановых корзин — **ярлыки владельца, не пороги диапазона**: корзина
`AA+` содержит рейтинг `AAA`, корзина `B+` содержит `BBB+` (лестница §4.2
`bond-subtypes-plan.md`). Полный контракт (пары Тип/Подтип, лестница
рейтингов, обратная совместимость со снапшотами до 2026-08-18) — SSOT там,
здесь не дублируется.

### Замещайки (FX-облигации)

```json
{
  "ticker": "RU000A105JH9",
  "name": "ГазКЗ-27Д2",
  "nominal_currency": "USD",
  "current_price": 85.40,
  "value_rub": 226260.00,
  "ytm_pct": 6.15,
  "ytm_source": "moex_iss"
}
```

---

## `ie_model` — модельный портфель Invest Era (v2 new)

```json
{
  "source_sheet": "Invest Era",
  "extraction_date": "2026-05-03",
  "model_total_pct": 100.0,
  "positions": [
    {
      "ticker": "SBER",
      "name": "Сбербанк",
      "sector": "Финансовый",
      "target_share_pct": 6.0,
      "current_price_rub": 326.74,
      "entry_price_rub": 285.0,
      "risk_level": "Низкий",
      "growth_potential_12m_pct": 5.59,
      "growth_potential_lt_pct": 31.6,
      "div_yield_2024_pct": 11.52,
      "active_in_model": true
    },
    {
      "ticker": "GMKN",
      "name": "Норникель",
      "sector": "Материалы",
      "target_share_pct": 4.0,
      "current_price_rub": 109.52,
      "entry_price_rub": 100.0,
      "risk_level": "Средний",
      "growth_potential_12m_pct": 29.18,
      "growth_potential_lt_pct": 55.0,
      "div_yield_2024_pct": null,
      "active_in_model": true
    }
  ]
}
```

**Парсинг decimal:** строки с запятой (`"5,59"` → `5.59`), прочерк `"-"` → `null`.
**Graceful degradation:** если вкладка «Invest Era» отсутствует → `positions: []` + warning flag.

---

## `ie_actual` — per-ticker IE state из вкладки «Акции» (v2 new)

```json
{
  "source_sheet": "Акции",
  "extraction_date": "2026-05-03",
  "per_ticker": {
    "SBER": {
      "ie_new_pct": 6.0,
      "ie_old_pct": 6.0,
      "ie_delta_pct": 0.0,
      "real_share_pct": 12.46,
      "planned_share_pct": 10.0,
      "user_plan": "KEEP",
      "user_status": null,
      "user_note_ie": null,
      "user_note_ai": "Держать"
    },
    "DATA": {
      "ie_new_pct": 3.0,
      "ie_old_pct": 3.0,
      "ie_delta_pct": 0.0,
      "real_share_pct": 1.07,
      "planned_share_pct": 2.0,
      "user_plan": null,
      "user_status": null,
      "user_note_ie": null,
      "user_note_ai": null
    }
  }
}
```

Последние 4 колонки вкладки «Акции» (с 2026-06):
- `user_plan` ← **План** (что пользователь собирается сделать)
- `user_status` ← **Статус** (что пользователь уже сделал)
- `user_note_ie` ← **IE** (комментарий от Invest Era)
- `user_note_ai` ← **AI** (вывод ru-portfolio-advisor)

**Конвертация долей:** значения из Numbers — дроби (`0.06`), умножаем на 100 → проценты (`6.0`).
**Фильтрация:** пропускаем строки, где Стоимость=0 И IE New пусто И IE Old пусто (удалённые тикеры).
**Пустые ячейки:** `None`, `''`, `'--'` → `null` (не `0.0` — различие между «нет в модели» и «0%»).

---

## `ie_summary` — derived cross-reference stats (v2 new)

```json
{
  "tickers_in_ie_model": 19,
  "tickers_in_portfolio_active": 23,
  "tickers_in_both": 18,
  "tickers_in_portfolio_not_in_ie": 5,
  "tickers_in_ie_not_in_portfolio": 1,
  "ie_model_total_pct": 100.0,
  "real_share_total_in_ie_pct": 75.36,
  "ie_changes_count": 0,
  "list_in_portfolio_not_in_ie": ["CHMF", "MOEX", "NVTK", "SBERP", "VTBR"],
  "list_in_ie_not_in_portfolio": ["LSNGP"]
}
```

Используется consumers для:
- `list_in_portfolio_not_in_ie` → секция «User-only positions» в advisor и synthesizer
- `list_in_ie_not_in_portfolio` → секция «IE candidates not held»

---

## `balance_summary` — баланс по счетам (v2 расширение)

```json
{
  "total_current_rub": 39417000.0,
  "total_current_rub_excl_iis": 39417000.0,
  "total_current_rub_incl_iis": 40596996.6,
  "iis_balance_rub": 1179996.6,
  "by_account": {
    "main": {
      "total_rub": 39417000.0,
      "stocks_rub": 13883789.85,
      "bonds_rub": 17701742.70,
      "funds_rub": 1869846.00,
      "cash_rub": 5961621.45
    },
    "iis_3": {
      "total_rub": 1179996.6,
      "stocks_rub": 0.0,
      "bonds_rub": 1013751.60,
      "funds_rub": 0.0,
      "cash_rub": 166245.00
    }
  },
  "bonds_value_by_type_excl_iis": {"USD": 8441911.53, "ОФЗ": 3177730.5, "КОРП": 4648734.6},
  "bonds_value_by_type_iis_only": {"ОФЗ": 1600998.96},
  "bonds_value_by_subtype": {"USD": 8441911.53, "ОФЗ/>10": 2633612.07, "ОФЗ/<10": 2145117.39, "КОРП/AA+": 2372467.29, "КОРП/A": 1426646.28, "КОРП/B+": 849621.03},
  "bonds_value_by_subtype_excl_iis": {"...": "..."},
  "bonds_value_by_subtype_iis_only": {"...": "..."},
  "bonds_plan_vs_fact": [
    {
      "bucket_key": "ОФЗ/>10", "type": "ОФЗ", "subtype": ">10",
      "target_pct": 30.0, "target_rub": 6356442.6,
      "actual_rub": 1943690.67, "actual_rub_incl_iis": 2633612.07,
      "actual_rub_file": 1943690.67,
      "actual_pct": 9.7, "delta_rub": 4412751.93, "delta_pp": 20.3
    }
  ],
  "bonds_plan_vs_fact_iis": [
    {"bucket_key": "ОФЗ/>10", "type": "ОФЗ", "subtype": ">10", "actual_rub": 689921.4}
  ],
  "class_plan_vs_fact": [
    {"class": "Акции", "target_pct": 40.0, "target_rub": 17362693.2, "actual_rub": 14626586.37,
     "actual_pct": 33.7, "delta_pp": 6.3, "delta_rub": 2736106.83}
  ],
  "matrix_plan_vs_fact": [
    {"currency": "USD", "class": "Золото", "target_pct": 3.0, "target_rub": 1302201.99, "actual_rub": 1146960.0,
     "actual_pct": 2.64, "delta_pp": 0.36, "delta_rub": 155241.99}
  ],
  "summary": {...},
  "goals_overall": [...],
  "goals_matrix": [
    {"Валюта": "RUB", "Бумага": "Акция", "Доля план": 0.4, "Доля нынешняя": 0.3249,
     "Сейчас": 14065338.96, "Планы": 17314827.6, "Изменение": 3249488.64, "Действие": null}
  ],
  "goals_matrix_iis": [
    {"Валюта": "RUB", "Бумага": "ИИС", "Доля план": "NA", "Доля нынешняя": "NA",
     "Сейчас": 1783446.0, "Планы": 1783446.0, "Изменение": 0.0, "Действие": null}
  ],
  "errors_check": [
    {"Тип ошибки": "Есть в IntelInvest, нет в Акция", "Наличие": false},
    {"Тип ошибки": "Есть в IE, нет в Акция", "Наличие": true}
  ],
  "goals_bonds_breakdown": [
    {"Тип": "USD", "Подтип": null, "Доля План": 0.12, "План сумма": 2542577.04, "Нынешняя Сумма": 8942311.53, "Изменение": -6399734.49},
    {"Тип": "ОФЗ", "Подтип": ">10", "Доля План": 0.3, "План сумма": 6356442.6, "Нынешняя Сумма": 1943690.67, "Изменение": 4412751.93}
  ]
}
```

**Числа в примерах выше иллюстративны** (сняты со снапшота 2026-08-19) — плановые
доли всегда читаются из файла владельца, нигде не хардкодятся.

`goals_bonds_breakdown` — **сырые строки** таблицы «План по Облигациям» листа
«Общий баланс», **как есть**, с русскими ключами (не `{"subcategory", "target_pct"}` —
такой формы не было никогда). С 2026-08-18 — 9 строк (+ строка `Итог`) по контракту
§4.3 `bond-subtypes-plan.md`: `Тип` (`USD`/`EUR`/`CNY`/`ОФЗ`/`КОРП`), `Подтип`
(`null` для валютных; `>10`/`<10`/`Флоат` для ОФЗ; `AA+`/`A`/`B+` для КОРП),
`Доля План` (дробь 0–1), `План сумма`, `Нынешняя Сумма`, `Изменение`. Снапшоты до
2026-08-18 несут вместо `Подтип` **legacy**-колонку `Рейтинг` и 6 строк
(`КОРП/AAA`, `КОРП/BBB` — старые, более грубые корзины); парсер принимает оба
имени колонки, старые снапшоты не мигрируются (read-only исторические, §4.4
плана). Может быть `[]`/`null`, если лист «Общий баланс» отсутствует или пуст.
Ключующий по `Тип` потребитель схлопнет 3 строки ОФЗ / 3 строки КОРП в одну —
различать нужно по паре `Тип`+`Подтип` (или готовому `bonds_plan_vs_fact`, где
это уже сделано).

`goals_matrix` / `goals_matrix_iis` / `errors_check` (**PDL-13, 2026-08-19**) —
сырые строки листа «Общий баланс», с русскими ключами, как есть. До PDL-13
`parse_portfolio.py` их парсил, но `assemble_snapshot.py` в снапшот не переносил:
Mode 3 advisor'а оставался слеп к плановой валютной аллокации, а
`rebalance-framework.md` ссылался на пути промежуточного `portfolio.json`
(`goals.matrix`, `errors_check`), которых у режима на руках не было (RPA-17).

- `goals_matrix` — матрица «Планы»: разрез **Валюта × Бумага** (колонка
  называется `Бумага`, не `Тип`: `Кеш`/`Акция`/`Облигация`/`Золото`/`Другое`),
  плюс `Доля план`, `Доля нынешняя` (дроби 0–1), `Сейчас`, `Планы`, `Изменение`,
  `Действие`. Строка ИИС-3 вынесена в отдельный `goals_matrix_iis` и в долях не
  участвует (решение владельца Q1) — там `Доля план`/`Доля нынешняя` приходят
  строкой `"NA"`, а не числом: потребитель обязан это выдержать.
- `errors_check` — таблица «Проверка»: `Тип ошибки` + булево `Наличие`. Хоть
  одно `true` → IntelInvest рассинхронизирован с файлом. **Дополняет, но не
  заменяет** `data_quality_flags[]` и `cash_reconciliation` — это проверки
  владельца внутри его файла, а не проверки загрузчика.

`bonds_value_by_type*` группирует облигации только по `Тип` (5 корзин, старое
поведение, оставлено для обратной совместимости). `bonds_value_by_subtype*` —
тот же расчёт по плановой корзине `plan_bucket_key` (до 9 корзин) в трёх срезах:
весь портфель / без ИИС-3 (`_excl_iis`) / только ИИС-3 (`_iis_only`). Ключ —
строка `plan_bucket_key` (`"USD"`, `"ОФЗ/>10"`…), значение — сумма `value_rub`.

`bonds_plan_vs_fact` — план↔факт по каждой строке «План по Облигациям» (кроме
`Итог`). **База — БЕЗ ИИС-3** (решение владельца Q1, `bond-subtypes-plan.md` §3.1):
`actual_rub` считается заново по `holdings[]` (свежие цены MOEX, `account == "main"`),
а не берётся из файла напрямую. Для валютных корзин `actual_rub` дополнительно
включает фонды из «Tаблица 1» с `Тип` вида `"<корзина> - Облигации"` (кейс
TLCB — фонда нет на вкладке «Облигации»; без него корзина USD расходится с
файлом на 500 400 ₽). Поля: `bucket_key`/`type`/`subtype` (совпадают с строкой
плана), `target_pct`/`target_rub` (из файла), `actual_rub` (пересчёт),
`actual_rub_incl_iis` (то же + ИИС-3, справочно), `actual_rub_file` (`Нынешняя
Сумма` из Numbers как есть — для сверки со свежестью файла), `actual_pct`
(доля от Σ `actual_rub` по всем строкам), `delta_rub` (`target_rub − actual_rub`),
`delta_pp` (`target_pct − actual_pct`). `null`, если таблицы плана нет в
`portfolio.json`.

`bonds_plan_vs_fact_iis` — параллельный факт **только** по ИИС-3 (`account ==
"iis_3"`), сгруппированный по `plan_bucket_key`, **без** плана (ИИС-3 не
участвует в «План по Облигациям», Q1) — только `bucket_key`/`type`/`subtype`/`actual_rub`.

`class_plan_vs_fact` / `matrix_plan_vs_fact` — факт и план по классам и по ячейкам
валюта × класс (`build_class_breakdown`, этап 4b ухода от Numbers). Есть только при
`--plan plan.json` (без плана — `null`). **База — БЕЗ ИИС-3** (`account == "main"`),
проценты — от суммы факта, суммы — ₽ (2 знака); сумма фактов = `total_current_rub_excl_iis`.
Поля строки: `class` (в `class_plan_vs_fact` имена как в `plan.classes[]` — «Акции»·«Облигация»·
«Золото»·«Другое»·«Кеш»; в `matrix_plan_vs_fact` — как в `plan.matrix[]` — «Акция»…) и
`currency` (только в матрице), `target_pct`/`target_rub` (из `plan.classes`/`plan.matrix`,
`null` — плана нет), `actual_rub`, `actual_pct`, `delta_pp` (`target_pct − actual_pct`),
`delta_rub` (`target_rub − actual_rub`). Состав факта: акции — `asset_type == stock` с
`current_price_source != cost_basis` (замороженные вне), валюта позиции; облигации — по корзине
плана (USD/EUR/CNY → своя валюта, ОФЗ/КОРП → RUB; без корзины — `nominal_currency`);
фонды — по карте `plan.funds[T]` (`class`, `currency`; фонд класса «Облигация» входит и в факт
облигаций своей валюты), запасной путь — тип строки «Таблицы 1» (`other_positions`/
`plan.manual_positions`); деньги — `cash.by_account.main` в «Кеш RUB»; строки «Таблицы 1» —
только если такой бумаги нет в `holdings` с ценой. Фонд со стоимостью > 0 без класса попадает в
строку `class: null` («не отнесён», `target_*` = `null`). Строки матрицы: все из `plan.matrix`
плюс ячейки с фактом, которых в плане нет.

Флаги (`data_quality_flags`, шаг `class_breakdown`): `fund_unmapped` (warn; `checks.py` →
предупреждение `fund_unmapped`), `manual_position_duplicate` (info — строка «Таблицы 1» пропущена,
бумага есть в holdings с биржевой ценой), `manual_position_override` (info — ручная оценка перекрыла
стоимость holdings у позиции с небиржевой ценой `last_trade`/`cost_basis`: FINAMAR, решение §5.5), `class_fact_mismatch` (info — ячейка расходится с Numbers
`goals_matrix[].Сейчас` на ≥ 1 % и > 1000 ₽; «Золото» сравнивается внутри «Другое» своей валюты).
В `bonds_plan_vs_fact` фонды-члены валютных корзин берутся из карты (`plan.funds[T].bucket`,
стоимость из holdings) и из «Таблицы 1» (запасной путь) без двойного счёта.

**Источники:**
- `total_current_rub_incl_iis` ← «Имеется (RUB)» из Общего баланса как есть
  (весь портфель ВКЛЮЧАЯ ИИС-3, без заблокированных — семантика владельца,
  2026-07-08)
- `total_current_rub_excl_iis` ← Имеется − ИИС (основные счета, база для долей)
- `iis_balance_rub` ← «ИИС» из Общего баланса
- `by_account.iis_3.bonds_rub` ← сумма `Итого на ИИС` по всем облигациям
- `by_account.main.cash_rub` ← total_main − stocks − bonds_main − funds —
  «грязный» балансовый остаток: содержит позиции вне вкладок баланса
  (TPAY/TMON/FINAMAR из трейдов). Для настоящего кэша использовать блок
  `cash` снапшота, НЕ это поле

---

## `cash` — настоящий свободный кэш + ликвидность

```json
{
  "total_rub": 598000.20,
  "by_currency": {
    "RUB": 840000.00,
    "USD": 1200.50,
    "CNY": 15000.00,
    "EUR": 0.0
  },
  "by_account": {
    "main": 486648.57,
    "iis_3": 111351.63
  },
  "cash_equiv_rub": 2355413.28,
  "liquid_rub": 2953413.48,
  "cash_equiv_tickers": {"TPAY": 1517100.0, "TMON": 838313.28}
}
```

Семантика (фикс 2026-07-08):
- `total_rub` — **настоящий** свободный кэш = «Имеется» (весь портфель вкл.
  ИИС, без заблокированных) − стоимость всех незаблокированных holdings.
  Балансовый остаток `by_account.main.cash_rub` из `balance_summary` НЕ
  используется — он содержит денежные фонды и FINAMAR.
- `by_account.iis_3` = «ИИС» − облигации ИИС − прочие ИИС-позиции (SBGB);
  `main` = total − iis_3.
- `cash_equiv_rub` — фонды денежного рынка из `CASH_EQUIV_TICKERS`
  (LQDT/TMON/TPAY). FINAMAR сюда не входит.
- `liquid_rub = total_rub + cash_equiv_rub` — «кэш + ликвидность» в рабочем
  определении владельца; двойного счёта нет, т.к. total_rub фонды не содержит.
- Если расчётный кэш отрицательный (устаревшее «Имеется» против свежих
  котировок) — warning-флаг `cash_negative`.

---

## `returns` — доходности

```json
{
  "parameters": {
    "as_of": "2026-05-03",
    "start_date": "2022-03-01",
    "trades_count": 9265,
    "use_moex": true,
    "cbr_offline": false,
    "bond_value_basis": "dirty"
  },
  "total": {
    "xirr": -0.042,
    "roi": -0.089,
    "twr_dietz_annualized": -0.031,
    "pnl_rub": -142000.00,
    "comment": "Включает заблокированные позиции (оценены в 0)"
  },
  "restricted": {
    "xirr": 0.148,
    "roi": 0.312,
    "twr_dietz_annualized": 0.121,
    "pnl_rub": 2670000.00,
    "comment": "Только активная часть с 01.03.2022, без заблокированных"
  },
  "by_type": {
    "stock": {"xirr": 0.182, "roi": 0.418, "pnl_rub": 2340000.00},
    "bond": {"xirr": 0.127, "roi": 0.201, "pnl_rub": 510000.00},
    "fund": {"xirr": 0.093, "roi": 0.141, "pnl_rub": 42000.00},
    "other": {"xirr": null, "roi": null, "comment": "Недостаточно данных"}
  },
  "benchmarks": {
    "note": "PME: те же потоки и конвенции, что by_type (start 2022-03-01 по cost basis)...",
    "window": {"start": "2022-03-01", "end": "2026-07-02"},
    "stock_vs_mcftr": {
      "benchmark": "MCFTR",
      "actual_xirr": 0.0057, "bench_xirr": 0.0036, "gap_pp": 0.21,
      "actual_terminal_rub": 16411694.85, "bench_terminal_rub": 16343567.49
    },
    "bond_vs_deposit": {
      "benchmark": "вклад КС−1пп",
      "actual_xirr": 0.0993, "bench_xirr": 0.1552, "gap_pp": -5.59,
      "actual_terminal_rub": 20385566.19, "bench_terminal_rub": 23358557.16
    },
    "flags": [],
    "sources": {"key_rate_points": 1101, "index_points": 1084}
  }
}
```

**`benchmarks` — бенчмарк-гейт (PME, Long-Nickels).** Те же потоки суб-портфеля
(стартовая cost-basis база + внутренние покупки/продажи/купоны/дивиденды),
вложенные в бенчмарк: акции → MCFTR (индекс Мосбиржи полной доходности,
история через MOEX ISS), облигации → вклад по КС − 1 пп (ежедневная
капитализация, история КС через ЦБ SOAP). `actual_xirr` бит-в-бит совпадает с
`by_type.*.xirr` (одна математика). `gap_pp` = actual − bench в пп годовых;
**минус = бенчмарк был лучше фактических решений**. Сеть best-effort: при
сбое подблоки `null` + флаги; отключение расчёта — `--no-benchmarks`.
Viewer («Динамика») рисует бенчмарк-линии и строку гейта из этого блока.

**`parameters.bond_value_basis` (2026-10-12).** `"dirty"` — облигации с ценой
MOEX оценены с НКД (как и покупки в trades, где «Сумма» включает уплаченный НКД).
Нет поля → `"clean"`: снапшоты до 12.10.2026, XIRR облигаций в них занижен
(на 12.10: 11,7% против 12,3% с 2022), прямо не сравнивать. НКД MOEX (`ACCRUEDINT`)
номинирован в валюте торгов, у замещаек — рубли.

### `returns.live_basis` — вход живой доходности вьюера (2026-10-23)

Потоки XIRR без конечной стоимости и позиции, из которых она сложена (основной счёт). Вьюер подставляет
живые цены MOEX акций, фондов и рублёвых облигаций и решает то же уравнение — доходность на странице на
текущих ценах, а не на дату снапшота. На ценах снапшота уравнение обязано дать ровно `total.xirr` /
`restricted.xirr` и то же по строкам: `per_instrument_xirr[*].xirr`, `by_type.*.xirr`, `by_account.iis_3.fact.xirr`
(сторожа — `tests/test_live_basis.py`, `tools/tests/test_viewer_live_xirr.py`). Потоки берутся из того же
места, где посчитан XIRR строки, — равенство по построению. Нет блока или новых полей (снапшоты до
11.11.2026) — вьюер показывает XIRR снапшота; итог по новым полям не зависит от строк.

```json
"live_basis": {
  "terminal_date": "2026-10-22",          // дата конечной стоимости отчёта
  "cash_rub": 953296.77,                  // кэш portfolio_returns (реконструкция по сделкам)
  "flows_total": [["2019-11-11", -100000.0], …],      // знак XIRR: вложение < 0; по дням
  "flows_restricted": [["2022-03-01", -29629629.0], …], // первый — стартовая стоимость 01.03.2022
  "positions": [{"ticker": "TGLD", "type": "fund", "qty": 88500, "value_rub": 1146960.0,
                 "price_source": "moex", "blocked": false},
                {"ticker": "SU26243RMFS3", "type": "bond", "qty": 1017, "value_rub": 2196658.98, "price_source": "moex",
                 "blocked": false, "face": 1000.0, "face_ccy": "RUB", "accrued_rub": 42.69}, …],
                                          // облигации с ценой MOEX: номинал, валюта номинала, НКД одной бумаги в ₽ —
                                          // value_rub = qty × (цена/100 × face + accrued_rub); вьюер оценивает живьём
                                          // только при face_ccy RUB (замещайки — по снапшоту)
  "flows_by_type": {"stock": [["2022-03-01", -…], …], "bond": […], "fund": […]},
                                          // потоки подпортфеля типа (первый — стоимость начала окна), те же, что у
                                          // returns_by_type_restricted; терминал типа = Σ value незаблокированных позиций типа
  "flows_by_ticker": {"SU26243RMFS3": [["2026-07-02", -704198.4], …]},
                                          // ключи — как в per_instrument_xirr (ISIN-алиасы без потоков, находятся по alias_of);
                                          // = cashflows записи per_security без терминала (assemble_snapshot._live_flows_by_ticker)
  "flows_by_ticker_account": {"SU26247RMFS5": {"main": […], "iis_3": […]}}
                                          // только у бумаг с by_account; те же счётчики, что у xirr счетов
}
```

`returns.by_account.iis_3.live_basis` — `{terminal_date, cash_rub, flows_total, positions}` расчёта счёта
(`iis_returns._iis_live_basis`): XIRR на ценах расчёта = `fact.xirr`. Перенесённый (`carried_from`) блок
вьюер живьём не считает.

Размер на реальной выгрузке — ≈30 КБ базовых (≈360 дней потоков, 120 позиций) плюс ≈60 КБ новых полей
(≈1000 потоков по бумагам, три списка по типам, ИИС-3, номинал/НКД 41 облигации).

### `returns.by_account.iis_3` — доходность БКС-ИИС-3 (2026-10-12)

Есть, только если на Шаге 4б посчитан `iis_returns.py` по отдельной выгрузке
счёта. Финамовский ИИС-3 владелец ведёт как брокерский — он в общем файле и сюда
не входит; `account: "iis_3"` в holdings = БКС-ИИС-3.

```json
"by_account": {"iis_3": {
  "broker": "БКС", "source_file": "trades_portfolio_838526.xlsx",
  "file_last_operation": "2026-09-23", "as_of": "2026-10-12",
  "status": "ok",                     // ok | mismatch | unverified
  "reconciliation": [],               // при mismatch: [{ticker, file_qty, balance_qty}]
  "fact": {"xirr": 0.0077, "roi": 0.0032, "twr_dietz_annualized": 0.0077,
           "net_external_deposits_rub": 1799892.75, "received_coupons_rub": 74802.6,
           "synthetic_coupons_rub": 0, "current_value_rub": 1805223.0,
           "pnl_rub": 1777.0, "period_start": "2026-04-17", "years": 0.49,
           "bond_value_basis": "dirty"},
  "forward": {"bonds_irr_pct": 14.56, "account_pct": 14.3,
              "fund_proxy": {"index": "RGBI", "ytm_pct": 16.1, "coverage": 1.0}},
  "locked":  {"bonds_irr_pct": 13.64},
  "per_bond": [{"secid": "SU52004RMFS7", "isin": "RU000A103MX5", "linker": true,
                "qty": 180, "value_rub": 677819.16, "forward_pct": 10.84,
                "forward_real_pct": 6.45, "locked_pct": 12.19, "locked_real_pct": 7.98,
                "moex_ytm_pct": 6.45}],
  "other_positions": [{"secid": "SBGB", "kind": "fund", "qty": 3520, "value_rub": 161061.12}],
  "inflation_assumption": {"source": "inflation-ru-2026-09-17.yaml",
                           "path": [["2026-12-31", 6.5], ["2027-12-31", 4.0]],
                           "flat_pct": null},
  "synthetic_coupons": [],            // [{secid, date, qty, value_per_bond, amount_rub}]
  "carried_from": "2026-10-13",       // ТОЛЬКО у перенесённого блока (см. ниже)
  "carried_reason": "нет новой выгрузки ИИС-3"
}}
```

**Перенос без новой выгрузки (2026-10-13).** Выгрузка ИИС-3 приходит только после
операций (последняя переданная лежит в `Portfolio/inputs/`; до 2026-10-21 — в `docs/investment/source/` на Mac, которой нет в упакованном скилле), и повторная
загрузка в тот же день перезаписывает `portfolio-<date>.json` (инцидент 13.10:
прогон 15:10 с ИИС, прогон 16:56 без — блок пропал). Поэтому без `--iis-returns`
`assemble_snapshot.py` берёт блок из последнего снапшота, где он есть и с числами
(`status != mismatch`): `--output` (читается ДО записи, т.е. файл того же дня),
`--prev-snapshot`, затем `--snapshots-dir` по убыванию даты. Блок копируется как
есть + `carried_from` (дата расчёта; при цепочке переносов сохраняется исходная) и
`carried_reason`; флаг `iis_returns_carried` (info). Состав ИИС-3 сверяется по qty
(ключ ISIN, допуск 0,5 шт.) с holdings снапшота-источника: разошёлся → warn
`iis_composition_changed` («нужна свежая выгрузка»), блок всё равно переносится.
Источника с блоком нет — блока нет, как раньше.

Три числа — разные вопросы, не путать:
- **`fact.xirr`** (А) — что счёт заработал: взносы → купоны → текущая грязная стоимость.
  Доля, как `total.xirr`.
- **`forward.*_pct`** (Б) — доходность к погашению по СЕГОДНЯШНЕЙ цене: IRR
  (−грязная стоимость сейчас + будущие купоны и погашения). У фиксированных ОФЗ
  совпадает с YTM MOEX (±0,01 п.п.). `account_pct` — по стоимости: облигации IRR
  книги, фонды — прокси RGBI (средневзвешенная YTM состава, до комиссии фонда;
  покрытие < 90% → null), кэш — 0%. Проценты, не доли.
- **`locked.bonds_irr_pct`** (В) — «зафиксированная при покупке»: покупки по факту
  + полученные купоны + будущие потоки текущего остатка. Фонды и кэш не входят.

**Линкер (ОФЗ-ИН):** номинал и купоны будущего индексируются по
`inflation_assumption` — Layer 1 `forecasts/inflation-ru-*.yaml`
(`fca_stats[*].l1_weighted`, после последнего горизонта держится последнее
значение); нет прогноза → `flat_pct: 4.0`. Индексационный лаг ~3 мес. не
моделируется. `*_real_pct` — та же IRR при нулевой инфляции (реальная
доходность; совпадает с YTM MOEX линкера). Погашение не ниже первоначального номинала.

**Купоны между выгрузками.** Контракт владельца: покупка/продажа/взнос сразу
влекут новую выгрузку; нет файла — операций не было. Купоны после последней даты
файла достраиваются по графику MOEX (bondization; количество — по сделкам строго
до даты отсечки, T+1) и попадают в `synthetic_coupons` + флаг
`iis_synthetic_coupons`. Состояния нет: каждый прогон строит заново, и купон,
пришедший в новом файле (±10 дней от даты графика), синтетику вытесняет —
разница XIRR от сдвига ±1 день < 0,01 п.п. Купон по графику, которого нет
ВНУТРИ периода файла, не достраивается (файл авторитетен) — `warn`
`iis_coupon_missing_in_file`. Погашение/амортизация после даты файла не
достраиваются — `warn` `iis_redemption_not_in_file`.

**Сверка (`status`).** Позиции файла против holdings `account == "iis_3"`
(допуск 0,5 шт.), кэш файла против `balance_summary.by_account.iis_3.cash_rub`
(допуск max(1 000 ₽; 0,5% счёта) — взнос без покупки виден здесь). Расхождение →
`status: "mismatch"`, блок БЕЗ `fact/forward/locked` + `warn`
`iis_returns_mismatch`: была операция без выгрузки или баланс устарел. Баланс не
приложен → `unverified` (числа есть, не сверены).

**Когда какую метрику использовать:**
- `restricted.xirr` — основная для стратегических обсуждений (без заблок.)
- `total.xirr` — полная картина с замороженным капиталом
- `twr_dietz_annualized` — для сравнения с фондами и бенчмарками
- `by_type` — для диагностики «что тянет портфель вниз»

---

## `per_instrument_xirr` — XIRR по тикерам

```json
{
  "SBER": {
    "xirr": 0.213,
    "qty_now": 150,
    "pnl_rub": 192600.00,
    "buy_total_rub": 1284300.00,
    "dividends_rub": 37800.00,
    "sell_total_rub": 0.00,
    "coupons_rub": 0.00,
    "amortization_rub": 0.00,
    "corr_buy_rub": 0.00,
    "corr_sell_rub": 0.00,
    "n_sells": 0,
    "market_value_rub": 147825.00,
    "balance_value_rub": 148500.00,
    "price_source": "moex",
    "first_trade_date": "2022-05-15",
    "last_trade_date": "2025-11-20",
    "recent_net_rub": 60000.00,
    "recent_n_buys": 2,
    "recent_n_sells": 0,
    "recent_round_trip": false,
    "recent_last_trade_date": "2026-08-04",
    "recent_direction": "buy"
  }
}
```

**`market_value_rub` / `price_source`.** Цена — из того же `quotes.json`, что у holdings (`per_security_xirr
--quotes`; в MOEX ISS — только за бумагами вне файла), поэтому у торгуемых бумаг `market_value_rub / qty_now`
= `holdings.current_price` (облигации — грязная стоимость одной бумаги). `price_source` (нормализован): `moex_iss`,
`last_trade` (цена последней покупки/продажи), `cost_basis`, `override` (баланс, если котировки нет), `closed`.
Акция/фонд с котировкой MOEX в holdings, но не `moex*` здесь → error `per_instrument_price_not_moex` (блок
записи); расхождение цены > 0,5 % при `moex*` → warning `per_instrument_value_mismatch`. `last_trade_date` —
последняя операция любого вида, включая дивиденд, а не только сделка.

**`by_account` — доходность бумаги по счетам (аддитивно).** Есть только у бумаги, которая была на обоих счетах
(основной и ИИС-3) и для которой известны сделки ИИС-3; иначе поля нет. Верхний уровень записи — объединение
счетов (портфельная доходность и доходность по типам считаются по нему). Структура:
`by_account: {main: {...}, iis_3: {...}}`, у каждого счёта `xirr` (доля; нет при несходимости), `pnl_rub`,
`buy_total_rub`, `sell_total_rub`, `coupons_rub`, `dividends_rub`, `amortization_rub`, `corr_buy_rub`,
`corr_sell_rub`, `market_value_rub`, `qty_now`, `first_trade_date`. Основная выгрузка сводная (колонки счёта
нет), поэтому потоки основного = суммарные (`per_security.cashflows`) минус потоки ИИС-3 из его выгрузки;
купоны и дивиденды берутся по фактическим зачислениям счёта, а не делятся по позиции на дату записи.
Терминальная стоимость делится по количеству на счёте. Σ `pnl_rub` по счетам = `pnl_rub` объединения.
Поток ИИС-3, которого нет в суммарных, или отрицательный остаток основного → поля нет. Верхнеуровневые
`iis_trades_source` (`export` — свежая выгрузка ИИС-3, `carried` — из прошлого снапшота, `none`) и
`iis_account_flows {file_last_operation, flows}` (потоки ИИС-3 по бумагам; переносятся вперёд, пока новой
выгрузки нет). При `carried` остаток ИИС-3 по балансу сверяется с перенесёнными потоками; расхождение
(ИИС-3 торговал после выгрузки) → у бумаги нет `by_account`, warn `iis_trades_stale` со списком бумаг.

**`iis_positions_source` (позиции ИИС-3 в `holdings[account=iis_3]`).** `trades_export` — по сделкам выгрузки ИИС-3
(количество точное; основной счёт у облигации на двух счетах = выгрузка основного − ИИС-3; проданная и погашённая
бумага уходит в ноль); `balance` — из «Общего баланса» (с выгрузкой счёта сверяются: `iis_returns_mismatch`,
баланс не перетирается); `carried` — выгрузки нет, позиции прошлого снапшота (`balance_summary.carried` содержит
`iis_positions`); `none` — позиций ИИС-3 нет ни в одном источнике. Акция на ИИС-3 и фонд на двух счетах не делятся
по счетам: warn `iis_positions_not_split`; qty ИИС-3 больше всей выгрузки основного → основной 0 и warn
`iis_qty_exceeds_total`.

**`per_instrument_xirr_closed` (проданные и погашённые бумаги, акции · облигации · фонды обоих счетов).** Отдельный
блок: `per_instrument_xirr` читают как «то, что держу» (доли, сортировка по XIRR, `recent_*`), закрытые его бы
исказили. Ключ — тикер выгрузки сделок. Запись: `closed: true`, `close_date` (последняя продажа или погашение;
в выгрузке погашение — «Продажа»), `holding_days` (первая сделка → `close_date`), `name`, `asset_type`,
`qty_now: 0`, `market_value_rub: 0`, `price_source: "closed"`, `xirr` (доля), `pnl_rub`, `buy_total_rub`,
`sell_total_rub`, `dividends_rub`, `coupons_rub`, `amortization_rub`, `corr_buy_rub`, `corr_sell_rub`, `n_sells`,
`first_trade_date`, `last_trade_date`, при проданной на ИИС-3 — `by_account`. Результат целиком из потоков
(`pnl_rub = продажи + купоны + дивиденды + амортизации − покупки`), терминала нет. Проданная и купленная снова
бумага держится и живёт одной записью в `per_instrument_xirr`; фьючерсы и заблокированные не входят. Поля нет
(`null`) — прогон без файла сделок.

**`isin` и ISIN-алиасы (2026-10-13, аддитивно).** Ключ записи — тикер выгрузки сделок (SECID). У ОФЗ он
не равен ISIN (`SU26243RMFS4` vs `holdings[].ticker = RU000A106E90`), поэтому каждая запись несёт `isin`
(если известен; мост SECID↔ISIN — название бумаги «ОФЗ 78729»: `returns.snapshot_current.positions[].name` ↔
`holdings[].name`; неоднозначное название не сопоставляется), а для бумаг с SECID ≠ ISIN та же запись
дублируется под ключом ISIN с флагом `alias_of: "<SECID>"`. Итог: `per_instrument_xirr[holding.ticker]`
находится напрямую. Агрегаты по словарю считать с пропуском записей с `alias_of` (иначе двойной счёт).
Остаток без `isin`/алиаса — бумаги без holdings (проданные) и без совпадения названия.

**Оценка позиции — MOEX first (2026-10-13).** `market_value_rub` = qty × MOEX
(облигации — грязная + НКД), если котировка есть; стоимость «Общего баланса»
(`--common`) — только запасной вариант (`price_source: "override"`). Значение баланса
всегда пишется в `balance_value_rub` (нет в балансе — поле отсутствует) для сверки.
До фикса баланс имел приоритет, а его «Цена» бывает устаревшей (CNRU: 671,4 против
MOEX 661,8) — `pnl_rub`/`xirr` считались по устаревшей цене.

**Разбивка результата (2026-10-13, аддитивно):** `sell_total_rub` (сумма продаж), `coupons_rub`,
`amortization_rub`, `corr_buy_rub`/`corr_sell_rub` (корректировки), `n_sells` (число продаж за всё время,
не путать с `recent_n_sells`) — as-is из `per_security_xirr.py`. Для вьюера: «прибыль по сделкам»
показывается только при `n_sells > 0`; «получено» = `dividends_rub` (+ `coupons_rub`, `amortization_rub`).
Старый `per_security.json` без этих полей → поля отсутствуют (читать как `null`).

**Добавлено 2026-08 (аддитивно, RPA-правило неразворота — Rule 3 `ru-portfolio-advisor`):**
свёртка недавних buy/sell-сделок по бумаге за скользящее окно (см. `recent_trades_window`
ниже за параметрами). Дивиденды/купоны/амортизации и Корректировки (Korrektirovka) в
`recent_net_rub`/`recent_n_buys`/`recent_n_sells` **не входят** — только настоящие
Покупка/Продажа (обоснование — `per_security_xirr._compute_recent_window`).

- `recent_net_rub` — нетто за окно, ₽, со знаком: покупки минус продажи (положительное = набирали).
- `recent_direction` — `"buy"` \| `"trim"` \| **поле отсутствует**, если сделок в окне не
  было или `|recent_net_rub|` ниже `recent_trades_window.net_threshold_rub` (читай
  отсутствие как `null` — та же конвенция, что у `xirr`/`price_source` при их
  недоступности в этой функции).
- `recent_last_trade_date` — дата последней Покупки/Продажи в окне (ISO) либо
  поле отсутствует, если таких сделок не было.
- `recent_n_buys` / `recent_n_sells` — счётчики сделок в окне (всегда присутствуют,
  включая `0`).
- `recent_round_trip` — `true`, если в окне были и покупки, и продажи (ровно тот
  случай, ради которого вводится правило неразворота, — виден отдельно).

**Обратная совместимость:** снапшоты до 2026-08 (и любой `per_security.json`,
собранный без `recent_window_days`) этих полей не несут — вся группа `recent_*`
в записи тикера отсутствует целиком (аддитивная деградация, `schema_version`
не менялся — прецедент: `cash_equiv_rub`, `status`/`status_summary`,
`bonds_plan_vs_fact` добавлялись так же).

---

## `recent_trades_window` — параметры окна/порога для `per_instrument_xirr[*].recent_*`

```json
{
  "days": 60,
  "net_threshold_rub": 142323.42,
  "threshold_basis": "1пп акционной книги (goals_matrix RUB/Акция «Сейчас»=14,232,340.50 ₽)"
}
```

Один блок на весь снапшот — параметры одинаковы для всех тикеров в `per_instrument_xirr`.

- `days` — фактическая ширина окна (дней), взятая из `per_security.json`
  (`--recent-window-days` шага 4, default 60), а не пере-объявленная отдельно —
  так `days` гарантированно совпадает с тем, что реально использовано при свёртке.
- `net_threshold_rub` — порог (₽), применённый к `recent_net_rub` для
  классификации `recent_direction`. `null`, если посчитать не удалось (см.
  `threshold_basis`) — тогда `recent_direction` отсутствует у всех тикеров.
- `threshold_basis` — самоописывающий текст базы: явный `--recent-net-threshold-rub`
  override, `N пп акционной книги` (`balance_summary.goals_matrix` RUB/Акция
  «Сейчас» — приоритетная база владельца), fallback `N пп NAV excl. ИИС`
  (когда `goals_matrix` недоступен), либо сообщение о невозможности расчёта.

`null` целиком, если `per_security.json` не несёт `recent_window_days` (старый
прогон per_security_xirr.py без этой фичи) — тогда и в каждой записи
`per_instrument_xirr[ticker]` группа `recent_*` тоже отсутствует.

---

## `corrections_log` — применённые корректировки

```json
[
  {
    "type": "split",
    "ticker": "T",
    "ratio": "1:10",
    "date": "2026-04-17",
    "description": "Сплит Т-Технологии 1:10, дата возобновления торгов 17.04.2026."
  },
  {
    "type": "tmf_forced_close",
    "ticker": "TMF",
    "date": "2024-08-05",
    "description": "Виртуальная продажа остатка TMF 05.08.2024."
  }
]
```

---

## `data_quality_flags` — флаги качества данных

**`asset_type_changed` (severity `warn`)** — тип бумаги (акция/облигация/фонд) сменился против прошлого
снапшота или у новой бумаги биржа и эвристика по сделкам разошлись («TMON: был акция, стал фонд (по бирже)»);
подробности — `type_check.changes`. Проверить до перевода снапшота в рабочий. **`types_step_failed`** (warning) — шаг справочника не отработал (не записался или упал; текст — `type_check.errors`), типы по справочнику и эвристике. **`moex_types_unavailable`
(severity `info`)** — сборка была онлайн, но ISS не ответил ни по одному тикеру справочника типов:
использованы справочник и эвристика.

**`fx_rates_missing` (severity `error`, 2026-10-21)** — `portfolio_returns` не нашёл курс ЦБ: сделки в
валюте пересчитаны в 0 ₽ и/или бумага оценена по стоимости покупки (курс 1.0 не применяется; `returns.fx_gaps` с
`tickers` → `assemble_snapshot`: «нет курса ЦБ для KZT — бумага X»). Числа снапшота неверны; Шаг 7 SKILL.md и `checks.py` — не сохранять.

**`returns_price_not_moex` (severity `error`, 2026-10-23)** — акция или фонд в расчёте доходности оценены
НЕ по MOEX (цена последней сделки / стоимость покупки), хотя в `holdings` у той же бумаги котировка MOEX
есть: MOEX ISS не ответил `portfolio_returns`. Случай 22.10 (скилл в окружении Claude): TGLD по 14,58 ₽
вместо 12,96 ₽ — XIRR +0,3 п.п., кэш −144 тыс. ₽. Внебиржевой FINAMAR, заблокированные и облигации —
вне проверки. Шаг 7 и `checks.py` — не сохранять.

```json
[
  {
    "step": "ie_model_parse",
    "severity": "warn",
    "code": "ie_model_total_mismatch",
    "message": "Сумма target_share_pct = 99.0%, ожидается 100.0%."
  },
  {
    "step": "ie_actual_parse",
    "severity": "info",
    "code": "ie_changes_detected",
    "message": "Изменения IE по 3 тикерам: SBER (5→6), T (4→6), MBNK (3→4)"
  },
  {
    "step": "iis_account_assignment",
    "severity": "warn",
    "code": "iis_split_position",
    "message": "Тикер RU000A1038V6 (ОФЗ 78714) разделён между main и iis_3: 80 + 130 шт."
  },
  {
    "step": "moex_quotes",
    "severity": "info",
    "code": "moex_unavailable_tickers",
    "message": "MOEX ISS не вернул данные для 2 тикеров. Использован last_trade_price."
  }
]
```

Значения `severity`: `"error"` (снапшот неполный), `"warn"` (требует внимания), `"info"` (известное ограничение).

### Гейты подтипов облигаций (2026-08-18, `bond-subtypes-plan.md` §5.1)

14 кодов, `step` — `bond_subtype_check` / `bond_plan_check` (в `parse_portfolio.py`,
не нужны свежие MOEX-данные) или `assemble_bonds` / `bonds_plan_vs_fact` /
`balance_vs_trades` (в `assemble_snapshot.py`, нужны holdings/даты погашения).

| Код | Severity | Условие |
|---|---|---|
| `bond_subtype_missing` | warn | `Тип ∈ {ОФЗ, КОРП}` в «Облигации», `Подтип` пуст |
| `bond_subtype_unknown` | warn | пара (Тип, Подтип) в «Облигации» вне §4.3 |
| `bond_bucket_not_in_plan` | warn | у позиции есть корзина, которой нет в «План по Облигациям» |
| `bond_plan_shares_not_100` | warn | Σ `Доля План` ≠ 1.0 ± 0.005 |
| `bond_plan_fact_stale` | warn | пересчитанный `actual_rub` разошёлся с `actual_rub_file` >1% — файл устарел против котировок MOEX |
| `bond_plan_base_mismatch` | warn | `План по Облигациям`.`Итог`.`Нынешняя Сумма` совпал с Σ `Текущая стоимость` (вкл. ИИС-3), а не с Σ `Итого без ИИСа` — файл смешивает базы |
| `matrix_bond_iis_leak` | warn | `Планы`.RUB/Облигация.`Сейчас` ≠ Σ(ОФЗ+КОРП) из «План по Облигациям» — ИИС-3 протекла в матрицу |
| `balance_total_vs_trades_drift` | info | \|«Имеется (RUB)» − (позиции реконструкции + Σ НКД + `cash.total_rub`)\| / «Имеется» > **1%** (PDL-14). Базы сведены до сравнения: фактический кэш вместо реконструированного (кассовый дрейф мониторит `cash_drift_changed`), НКД добавлен к чистым ценам MOEX. Монитор реконструкции `portfolio_returns.py`, НЕ валидатор Numbers-файла; при срабатывании сначала проверять дату сохранения файла |
| `bucket_fund_member_missing` | info | фонд «Tаблица 1» с `Тип` вида `"<корзина> - Облигации"` не попал ни в одну плановую корзину |
| `balance_identity_broken` | warn | Σ `Сейчас` по строкам матрицы «Планы» + строка ИИС ≠ «Имеется (RUB)» |
| `bond_ofz_subtype_maturity_mismatch` | warn | `Подтип=">10"` при текущем сроке до погашения <10 лет или `"<10"` при ≥10 лет (Q2: срок текущий, не при выпуске) |
| `bond_floater_subtype_mismatch` | info | `Подтип=Флоат` не подтверждается именем бумаги (best-effort эвристика) — и наоборот |
| `bond_rating_bucket_mismatch` | warn | `Рейтинг` (`credit_rating_file`) не попадает в диапазон своего `Подтип` по лестнице §4.2 |
| `bond_rating_below_ladder` | info | `Рейтинг` ниже `B-` / не распознан лестницей §4.2 |
| `bond_bucket_changed` | warn | выведенная корзина облигации расходится с плановой (было → стало); в снапшоте корзина по плану, решает владелец |
| `bond_rating_missing` | info | КОРП без рейтинга в плане и в обзоре облигаций — подтип не вывести |
| `bond_attrs_unavailable` | info | справочник типов без блока `bond` — корзины взяты из плана, вывод не выполнен |

Полные условия и регресс-защитные случаи («на файле 19.08 молчит») — SSOT
`docs/investment/portfolio/bond-subtypes-plan.md` §5.1, не дублировать здесь.

---

## `reconciliation.balance_vs_trades` — «Общий баланс vs расчёт по сделкам» (2026-10-13)

Полгода (с 2026-10-13 до 2027-04-13) держим оба источника и сравниваем; критерий
перехода — `docs/investment/TODO.md`, «Переход с „Общего баланса“ на расчёт по
транзакциям». Всегда присутствует ключ `reconciliation`; `balance_vs_trades` = `null`,
если баланс не приложен (holdings нет).

```json
"reconciliation": {"balance_vs_trades": {
  "started": "2026-10-13", "threshold_pct": 1.0,
  "positions": [{
    "ticker": "CNRU", "asset_type": "stock", "qty": 10,
    "avg_cost_balance": 580.9,        // колонка «Ср, Цена»; null, если avg_cost_source != "balance" и у фондов
    "avg_cost_trades": 580.9,         // reconstruct_positions: pos.avg_cost_rub (WACC, сплиты учтены)
    "avg_cost_diff_pct": 0.0,         // (баланс − сделки) / сделки, %
    "value_balance_rub": 6714.0,      // «Стоимость» баланса
    "value_moex_rub": 6618.0,         // qty × MOEX
    "value_diff_pct": 1.45,           // (баланс − MOEX) / MOEX, %
    "mismatch": true, "mismatch_fields": ["value"],
    "known_reasons": []               // ["known_split"] — тикер из KNOWN_SPLITS
  }],
  "summary": {"n_checked": 60, "n_mismatch": 3, "n_mismatch_unexplained": 2,
              "mismatch_tickers": [], "unexplained_tickers": []}
}}
```

Охват: активные акции и фонды с котировкой MOEX (`current_price_source == "moex_iss"`),
не заблокированные. Облигации здесь не сверяются (их количество — `bond_qty_vs_trades`). `mismatch` при |Δ| > 1 % по любому из
полей. Из законных причин код знает только `known_split` (KNOWN_SPLITS); смену тикера
и переезд бумаг между брокерами не знает — такие расхождения идут в
`unexplained_tickers` и разбираются руками. Расхождение — не ошибка загрузки: только
флаг `balance_vs_trades_mismatch` (info). Средняя цена из fallback `value/qty` не
сравнивается (это не данные баланса). Количество облигаций сверяет соседний блок ниже.

## `reconciliation.bond_qty_vs_trades` — количество облигаций: баланс vs сделки (2026-10-20)

Основной счёт: `holdings[].qty` облигаций против `per_instrument_xirr[*].qty_now` по ISIN.
Ключа нет, если нет holdings или `per_instrument_xirr`.

```json
"reconciliation": {"bond_qty_vs_trades": {
  "positions": [{"isin": "RU000A10FC62", "name": "НорНик1P17",
                 "qty_balance": 24, "qty_trades": 34, "qty_iis": 0, "mismatch": true}],
  "summary": {"n_checked": 36, "n_mismatch": 1, "mismatch_isins": ["RU000A10FC62"]}
}}
```

Правила: одна бумага под двумя ключами `per_instrument_xirr` (SU-тикер и ISIN) — дубль, не
сумма; бумага на двух счетах (ОФЗ 26238: 80 main + 130 ИИС-3) не расходится, если `qty_now`
равен main или main+ИИС; бумага без сделок основного счёта не сверяется. Расхождение ≥ 1 шт →
флаг `bond_qty_vs_trades_mismatch` (**warning**): стоимость позиции берётся из баланса, и
неверное количество искажает цену за бумагу. Кейс: НорНик1P17 — 24 шт на TQCB + 10 шт на TQOY,
в «Общем балансе» строка с 24 при стоимости на 34; три недели без флага (PDL-RECON).

---

## `trades_digest` — отпечаток выгрузки сделок (2026-10-21)

Additive. Строит `assemble_snapshot.py` из `--trades` (модуль `scripts/trades_digest.py`); нет
`--trades` или сбой разбора → `null` (сбой — warning `trades_digest_failed`). Сырые строки выгрузки
IntelInvest до `apply_corrections`, датой ≤ `upto` (= `as_of_date`), сгруппированные без расчётов:

```json
"trades_digest": {
  "schema": "trades-digest@1", "upto": "2026-10-16", "rows": 30858,
  "by_ticker": {"RU000A105GN3": {"Покупка": [1, 504000.0, 2.0], "Продажа": [2, -337297.4, 3.992046]},
                "Деньги (RUB)": {"Внесение": [2118, 29629629.63, 0.0]}}
}
```

`[строк, сумма в валюте строки (2 знака), количество (6 знаков)]`. Читатель — `checks.py`
(`check_backdated`): отпечаток прошлого снапшота против текущей выгрузки на ту же дату `upto` →
удаления, сделки и корректировки задним числом (warning `trades_changed_before_prev`), поздно
внесённые выплаты (info `payouts_recorded_late`), денежные строки — часть кэш-дрейфа
(`money_rows_changed_before_prev`). Строки, датированные самим днём `upto` и появившиеся после сборки
снапшота, правкой задним числом не считаются — одна info `trades_on_prev_snapshot_day`, а их бумаги
идут как сделки после снапшота в проверках позиций. Времени сделки в выгрузке нет, поэтому условий
два: снапшот собран в свой день (`generated_at`), и по ячейке (тикер, операция) его отпечаток равен
строкам текущей выгрузки строго до этого дня; иначе ячейка остаётся в предупреждениях. Итоги `per_instrument_xirr` для этого не годятся: их смысл
менялся между версиями загрузчика. Размер ≈30 КБ.


## `build_suspects` — что сборка сочла подозрительным (2026-11-11)

Additive. `build_snapshot.py` пишет после проверок: список `[тикер, операция]` бумаг с `payout_exceeds_holding` и
`payouts_recorded_late`. Следующая сборка читает его у прошлого снапшота: если все изменения задним числом —
удаление строк этих бумаг и операций, `trades_changed_before_prev` — info («чистка дублей»), иначе warning. Нет поля
(старый снапшот) — warning, как раньше. В parity не сравнивается (`parity_check.VOLATILE`).
## `cash_reconciliation` — baseline-дрейф кэша

Реконструированный из трейдов кэш исторически расходится с фактическим
(~1020 тыс. ₽ на 2026-07: часть пополнений прошлых лет отсутствует в экспорте
IntelInvest — владелец подтвердил: происхождение старой дыры неизвестно,
чинить её не нужно). До фикса семантики кэша 2026-07-08 baseline был ~2,2 млн —
бо́льшая часть оказалась артефактом двойного счёта ИИС и денежных фондов в
«кэше»; при первом прогоне после апгрейда старый baseline даст разовый
`cash_drift_changed` — перегнать с `--rebaseline-cash`. `actual_cash_rub`
берётся из `cash.total_rub` (настоящий кэш). Блок фиксирует расхождение как
baseline и сигналит **только на новые изменения**:

```json
{
  "actual_cash_rub": 598000.20,
  "reconstructed_cash_rub": -144650.25,
  "current_drift_rub": 1031950.95,
  "baseline_drift_rub": 1031950.95,
  "baseline_date": "2026-07-08",
  "delta_vs_baseline_rub": 0.0,
  "threshold_rub": 10000.0
}
```

Механика:
- **Первый снапшот** (или прогон с `--rebaseline-cash`): baseline = текущий дрейф,
  info-флаг `cash_baseline_set`.
- **Дальше** baseline наследуется из `--prev-snapshot` и НЕ самозакрепляется:
  `|delta_vs_baseline_rub| > threshold_rub` → warning-флаг `cash_drift_changed`
  в `data_quality_flags` (проверить полноту выгрузки trades — пополнения/выводы
  с прошлого снапшота; осознанное изменение принять перегоном с `--rebaseline-cash`).
- Нет returns/balance-данных → блок `null`, без флагов.

---

## Снапшот без баланса — позиции из сделок (`--holdings-from-trades`, с 2026-10-21; сделки + plan.json — штатно с 2026-10-28)

`build_snapshot.py` без `--balance` (сборка с сайта: «Общий баланс» необязателен). `snapshot_type:
"trades_holdings"`. При наличии `Portfolio/plan.json` план главный без `--plan-primary`; из прошлого снапшота
(`find_prev_snapshot` — последний с опорой кэша: с балансом или с кэшем владельца) берётся только то, чего нет в плане,
сделках и котировках. `balance_carried_from` и `balance_summary.carried_from` — день этого переноса, `null`, если
переносить было нечего; `balance_summary.carried` — перечень: `iis_positions`, `cash_drift`, `iis_cash`, `names`,
`nominal`, `bond_types`, `otc_price:<T>` (при отсутствии плана — ещё `ie_model`, `goals`, `plan_vs_fact`).

| Блок | Откуда |
|---|---|
| `holdings[]` основного счёта: qty, `value_rub`, `avg_cost_rub` (`avg_cost_source: "trades"`) | `returns.snapshot_current.positions` (цены MOEX) |
| `name` | прошлый снапшот → `short_name` котировки → название сделок → тикер (`carried: names`, если названия нет в котировках) |
| облигации: `plan_bucket` / `plan_subtype` / рейтинг / действие | `plan.bonds[ISIN]`; нет в плане — прошлый снапшот (`carried: bond_types`); `nominal` — котировка (`face_value`), прошлый — запасной |
| `holdings[]` с `account: "iis_3"` | прошлый снапшот (сделок счёта нет); облигация на двух счетах — цена за бумагу как у основного; qty сделок = основной + ИИС → основной = qty − ИИС |
| внебиржевые (FINAMAR: цены MOEX нет) | `plan.manual_positions[name].value_rub`; плана нет — стоимость за бумагу прошлого снапшота (`otc_price:<T>`). Биржевые бумаги из `manual_positions` не затрагиваются |
| `ie_model`, `ie_actual.per_ticker` (поля плана), `ie_actual.source_sheet: "plan.json"` | `plan.ie_model`, `plan.stocks`; `extraction_date` — дата импорта плана |
| `ie_actual.per_ticker[*].real_share_pct`, `ie_delta_pct`, `ie_summary` | считает загрузчик: акции основного счёта из holdings (доля от стоимости акционной книги), позиции общего портфеля IE (`active_in_model: false`) в сводку не входят |
| `balance_summary.goals_overall`, `goals_bonds_breakdown`, `goals_matrix` | `plan.classes`, `plan.bond_buckets`, `plan.matrix`; колонки формул листа («Сейчас», «Доля нынешняя», «Планы», «План сумма», «Нынешняя Сумма», «Изменение») считает загрузчик по holdings, золото — в «Другое» своей валюты; `goals_matrix_iis` — `null` (ИИС-3 вне целей) |
| `balance_summary.bonds_plan_vs_fact(_iis)`, `class_plan_vs_fact`, `matrix_plan_vs_fact` | holdings + `plan.funds`; `target_rub` корзины = доля × цель класса «Облигация»; `actual_rub_file` — `null` |
| `cash.total_rub` (`cash.source: "trades_plus_prev_drift"`) | `cash_balance_rub` сделок + `cash_reconciliation.current_drift_rub` прошлого снапшота; кэш ИИС-3 — прошлый |
| `cash.total_rub` (`cash.source: "owner_intelinvest"`, `--cash-fact`) | свободные деньги основного портфеля из IntelInvest (владелец) + кэш ИИС-3 прошлого |
| `cash.by_account.iis_3` (`cash.iis_source: "owner_intelinvest"`, `--cash-fact-iis`) | кэш ИИС-3, внесённый владельцем (только рубли), вместо переноса из прошлого снапшота (`iis_source: "carried_from_prev"`); оценка основного счёта при этом прежняя, total = бумаги + основной + ИИС-3 |
| `cash.fact_date` | дата последнего факта кэша: у снапшота с балансом и при `--cash-fact` / `--cash-fact-iis` — `as_of`, у оценки — из прошлого; возраст оценки основного счёта (`cash_fact_stale`) факт ИИС-3 не освежает |
| `cash_reconciliation` | только при `--cash-fact` (как у снапшота с балансом, с `cash_drift_changed`); у оценки — `null` |
| `balance_summary.summary`, `errors_check`, стоимости по типам | `null` (итоги листа не переносятся) |
| `balance_summary.by_account` | из holdings и итогов `total_current_rub_excl_iis` / `iis_balance_rub`, смысл полей как у сборки с балансом (`_by_account_from_holdings`): `main.funds_rub` — фонды без денежных TMON/TPAY/LQDT и без внебиржевого FINAMAR, `main.cash_rub` — «грязный» остаток `total − stocks − bonds − funds` (кэш + денежные фонды + FINAMAR; настоящий кэш — `cash`); `iis_3.funds_rub` — реальные фонды счёта (у сборки с балансом 0, фонд лишь вычтен из `cash_rub`; законное различие в `parity-known-diffs`); итога нет (кэш неизвестен) → `total_rub`/`cash_rub` `null` |
| `plan_check` | `{source: "plan_only", applied: true, plan_updated_at, n_diff: 0}` — сравнивать не с чем |
| `parity` | см. ниже |

Флаги: `balance_absent_holdings_from_trades` (warning): «Общий баланс не приложен: названия — из котировок/прошлого
снапшота; корзины облигаций, доли и цели (IE), план — из базы сайта (plan.json от <updated_at>); стоимость
внебиржевых — из плана; ИИС-3 — позиции прошлого снапшота, сделок счёта нет; кеш — факт владельца или оценка»;
`no_plan_for_trades_mode` (warning) — plan.json нет или не читается: цели, IE и план↔факт взяты из прошлого снапшота;
`no_prev_snapshot_for_trades_mode` (warning) — прошлого снапшота нет, переносить нечего, кэш `null`.
`manual_value_stale` (warning, в `ATTENTION_FLAGS`) — у ручной позиции (`plan.manual_positions`, FINAMAR) количество по сделкам изменилось против прошлого снапшота, а `value_rub` в плане прежний: «FINAMAR: количество по сделкам изменилось (0,876 → 0,95 шт.), а оценка в базе сайта осталась 450 000 ₽ — обнови «Оценку вручную» в карточке фонда». Вторая ветка (один флаг на бумагу, первая ветка приоритетнее): у записи плана есть `value_as_of` (дата оценки, `YYYY-MM-DD`) и последняя сделка по бумаге (`per_security[T].last_trade_date`) позже неё — «FINAMAR: оценка в базе сайта от 20.10.2026, последняя сделка 25.10.2026 — обнови «Оценку вручную» в карточке фонда.»; сделка в день оценки или раньше, нет `value_as_of` или даты сделки — флага нет.
`cash_fact_stale` (warning + решение владельца) — факт кэша старше 14 дней (`CASH_FACT_MAX_AGE_DAYS`):
спросить свободные деньги основного портфеля в IntelInvest и пересобрать с `--cash-fact`;
`cash_fact_ignored` (info) — `--cash-fact` при наличии баланса.

### `parity` — сверка «без баланса ↔ с балансом» одного дня

`{against, against_date, same_day, auto, matched, within_tol, known, diverged, diverged_paths[≤50]}` (в сводке
build-summary — ещё `report_path`) или `null`: `--parity-against PATH` либо автоматически
`{memory}/Portfolio/snapshots/portfolio-{as_of}.json`, если в нём `input_files.balance` не `null`; у сборки с балансом
и без снапшота с балансом на дату — `null`; нечитаемый снапшот — `{against, auto, error}`. Сверяет `parity_check.py` с
`references/parity-known-diffs-nobalance.yaml` (законные различия: происхождение, кэш, колонки формул листа, модель IE
общего портфеля; стоимость позиций, FINAMAR, классы и матрица факта, доли — НЕ известные). Допуск денег — копейка.
Расхождения не блокируют сборку.

## Минимальный снапшот (только returns, без balance)

```json
{
  "schema_version": "2.0",
  "as_of_date": "2026-05-03",
  "snapshot_type": "returns_only",
  "input_files": {"trades": "trades_portfolio_707160-7.xlsx", "balance": null},
  "holdings": null,
  "ie_model": null,
  "ie_actual": null,
  "ie_summary": null,
  "cash": {"total_rub": 1067835.00, "source": "trades_derived"},
  "returns": {...},
  "per_instrument_xirr": {...},
  "corrections_log": [...],
  "data_quality_flags": [
    {"step": "parse_balance", "severity": "info", "code": "no_balance_file",
     "message": "Общий баланс.numbers не приложен. holdings = null. IE-данные недоступны."}
  ]
}
```
