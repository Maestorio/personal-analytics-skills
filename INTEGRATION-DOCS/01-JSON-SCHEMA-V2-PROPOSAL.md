# PORTFOLIO snapshot — JSON Schema v2 proposal

**Документ версии:** 1.0
**Дата:** 2026-05-05
**Автор:** обсуждение pipeline portfolio-integrated-view
**Статус:** для review перед реализацией в `parse_portfolio.py`

---

## 1. Цель документа

Расширить существующий JSON-снапшот `PORTFOLIO-{date}.json` (генерируется `portfolio-data-loader/scripts/parse_portfolio.py`) до schema v2 для поддержки integrated-view pipeline.

Все добавляемые поля **read-only consumers**: `ru-portfolio-advisor`, `portfolio-scenario-stress`, `portfolio-integrated-view`. Сам loader остаётся source-of-truth для их расчёта.

## 2. Принципы дизайна

| Принцип | Применение |
|---|---|
| **Additive only** | Новые поля, существующие не переименовываются и не удаляются |
| **Backward compatibility** | Loader v2 умеет читать тот же `.numbers` файл; consumers v1 продолжают работать на тех же полях |
| **Schema versioning** | Поле `schema_version` повышается с `"1.0"` до `"2.0"`; consumers проверяют версию |
| **Single source of truth** | Один JSON, не два. IE-данные лежат в нём же, не отдельным файлом |
| **No raw duplication** | Вкладка «Импорт Акции» (raw IntelInvest snapshot) **не парсится** — это duplicate данных, которые уже есть в `holdings` |
| **Explicit nulls** | Для полей, которые могут быть пустыми (нет в IE-модели), используется `null`, не отсутствие ключа |

## 3. Что добавляется в v2

### 3.1. `schema_version: "2.0"` (обновление)

Существующее поле, поднимается до `"2.0"`. Consumers фильтруют:

```python
schema_ver = snapshot.get("schema_version", "1.0")
if schema_ver < "2.0":
    raise SchemaVersionError("PORTFOLIO snapshot v1.x не поддерживается. Перегенерируй через parse_portfolio.py v2+")
```

### 3.2. `holdings[i].account` — расширение

**Было (v1):**
```json
"account": "main"
```

**Стало (v2):**
```json
"account": "main"  // или "iis_3"
```

**Allowed values:** `"main"`, `"iis_3"`.

**Источник:** в `Общий баланс.numbers`, лист «Облигации» — колонка `ИИС/Итого без ИИСа/Итого на ИИС` определяет, какая часть позиции на ИИС-3. Если позиция полностью на ИИС-3 → `account: "iis_3"`. Если split (часть на main, часть на ИИС-3) → две записи в `holdings` с одним `ticker`, разными `account` и `qty`.

**Зачем:** R10 mitigation в integrated-view. Synthesizer должен знать, что нельзя предлагать SELL для ИИС-3 позиций (разрушает налоговую льготу).

### 3.3. Новый блок `ie_model`

```json
"ie_model": {
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
    ...
  ]
}
```

**Поля:**

| Поле | Тип | Источник в .numbers | Обязательное |
|---|---|---|---|
| `ticker` | string | колонка «Тикер» | да |
| `name` | string | колонка «Название» | да |
| `sector` | string | колонка «Сектор» | да |
| `target_share_pct` | number | колонка «Доля» × 100 | да |
| `current_price_rub` | number\|null | колонка «Текущая цена» | нет |
| `entry_price_rub` | number\|null | колонка «Точка входа» | нет |
| `risk_level` | string\|null | колонка «Уровень риска» (Низкий/Средний/Высокий) | нет |
| `growth_potential_12m_pct` | number\|null | колонка «Потенциал роста, %» (parse "5,59" → 5.59) | нет |
| `growth_potential_lt_pct` | number\|null | колонка «Долгосрочный потенциал роста, %» | нет |
| `div_yield_2024_pct` | number\|null | колонка «Дивиденды за 2024, %» (parse "11,52" → 11.52; "-" → null) | нет |
| `active_in_model` | bool | последняя колонка (булева отметка в Numbers) | да |

**Парсинг decimal:** Numbers сохраняет числа в строках с запятой («5,59»). Loader должен парсить через `float(s.replace(',', '.'))`. Для прочерков «-» → `null`.

**Зачем:** advisor и synthesizer получают модельные доли для расчёта divergence от текущего портфеля. Без этого synthesizer не сможет показать «реальная 12.5% vs IE-цель 6%».

### 3.4. Новый блок `ie_actual` (per-ticker IE state из вкладки «Акции»)

```json
"ie_actual": {
  "source_sheet": "Акции",
  "extraction_date": "2026-05-03",
  "per_ticker": {
    "SBER": {
      "ie_new_pct": 6.0,
      "ie_old_pct": 6.0,
      "ie_delta_pct": 0.0,
      "real_share_pct": 12.46,
      "planned_share_pct": null,
      "user_action": null,
      "user_note_ie": null,
      "user_note_t": null,
      "user_note_ai": null
    },
    "T": {
      "ie_new_pct": 6.0,
      "ie_old_pct": 6.0,
      "ie_delta_pct": 0.0,
      "real_share_pct": 6.66,
      ...
    },
    ...
  }
}
```

**Поля:**

| Поле | Тип | Источник | Назначение |
|---|---|---|---|
| `ie_new_pct` | number\|null | колонка «IE New» | Текущая рекомендация IE |
| `ie_old_pct` | number\|null | колонка «IE Old» | Предыдущая рекомендация IE |
| `ie_delta_pct` | number\|null | вычислено: `ie_new_pct - ie_old_pct` | Изменение IE за период |
| `real_share_pct` | number\|null | колонка «Доля Реальная» × 100 | Текущая фактическая доля |
| `planned_share_pct` | number\|null | колонка «Доля Планируемая» × 100 | Целевая доля пользователя |
| `user_action` | string\|null | колонка «Действие» | Пометка пользователя (например, «Продать») |
| `user_note_ie` | string\|null | колонка «IE» | Комментарий пользователя по IE |
| `user_note_t` | string\|null | колонка «T» | Комментарий по T-Инвестициям |
| `user_note_ai` | string\|null | колонка «AI» | Комментарий AI/Claude (если есть) |

**Critical parsing rules:**

1. **Decimal parsing:** значения в Numbers могут быть как float (0.06), так и string ("0,06") — обрабатывать оба случая.
2. **Empty cells:** пустая строка / `None` → `null`. **Не** заполнять `0.0` — это потеряет различие между «нет в модели» и «исключено из модели».
3. **Игнорировать строку Итог:** последняя строка таблицы — итог, тикер `"Итог"`, не парсится в `per_ticker`.
4. **Только активные позиции:** строки с `Стоимость = 0` И пустыми `IE_New`/`IE_Old` пропускаются (это удалённые/неактуальные тикеры).

### 3.5. Новый блок `ie_summary`

```json
"ie_summary": {
  "tickers_in_ie_model": 21,
  "tickers_in_portfolio_active": 25,
  "tickers_in_both": 18,
  "tickers_in_portfolio_not_in_ie": 7,
  "tickers_in_ie_not_in_portfolio": 3,
  "ie_model_total_pct": 100.0,
  "real_share_total_in_ie_pct": 84.5,
  "ie_changes_count": 0,
  "list_in_portfolio_not_in_ie": ["MOEX", "SBERP", "NVTK", ...],
  "list_in_ie_not_in_portfolio": ["LSNGP", ...]
}
```

**Зачем:** quick stats для consumers. Synthesizer использует `list_in_ie_not_in_portfolio` для секции «IE candidates not held». Advisor использует `list_in_portfolio_not_in_ie` для секции «User-only positions».

### 3.6. Расширение `balance_summary`

**Было (v1):**
```json
"balance_summary": {
  "total_current_rub": 26278000.0,
  "total_current_rub_excl_iis": 26278000.0,
  "iis_balance_rub": 786664.4,
  "summary": {...},
  "goals_overall": [...]
}
```

**Стало (v2):**
```json
"balance_summary": {
  "total_current_rub": 26278000.0,
  "total_current_rub_excl_iis": 25491335.6,  // фикс: реальный excl IIS
  "iis_balance_rub": 786664.4,
  "summary": {...},
  "goals_overall": [...],
  "by_account": {                              // новый блок
    "main": {
      "total_rub": 25491335.6,
      "stocks_rub": 9000000.0,
      "bonds_rub": 13000000.0,
      "funds_rub": 3000000.0,
      "cash_rub": 491335.6
    },
    "iis_3": {
      "total_rub": 786664.4,
      "stocks_rub": 0.0,
      "bonds_rub": 786664.4,
      "funds_rub": 0.0,
      "cash_rub": 0.0
    }
  }
}
```

**Замечание о текущем багге v1:** в текущем JSON `total_current_rub_excl_iis == total_current_rub`, потому что ИИС-3 не отделяется в `holdings` (все `account: "main"`). После v2 это исправляется естественным образом.

### 3.7. Расширение `data_quality_flags`

Добавляются новые типы флагов (existing flags остаются):

```json
{
  "step": "ie_model_parse",
  "severity": "warn",
  "code": "ie_model_total_mismatch",
  "message": "Сумма target_share_pct в IE-модели = 99.0%, ожидается 100.0%. Возможна ошибка в файле."
},
{
  "step": "ie_actual_parse",
  "severity": "info",
  "code": "ie_changes_detected",
  "message": "За период обнаружены изменения IE по 3 тикерам: SBER (5→6), T (4→6), MBNK (3→4)"
},
{
  "step": "iis_account_assignment",
  "severity": "warn",
  "code": "iis_split_position",
  "message": "Тикер RU000A107RH8 (Русал 1Р6) разделён между main и iis_3: 25 + 5 шт. соответственно"
}
```

## 4. Полный пример нового JSON v2 (фрагмент)

```json
{
  "schema_version": "2.0",
  "as_of_date": "2026-05-03",
  "generated_at": "2026-05-03T19:57:00",
  "input_files": {
    "trades": "trades_portfolio_1414320-7.xlsx",
    "balance": "Общий баланс.numbers"
  },

  "holdings": [
    {
      "ticker": "SBER",
      "isin": null,
      "name": "Сбербанк",
      "qty": 1800.0,
      "avg_cost_rub": null,
      "current_price": 320.96,
      "current_price_source": "moex_iss",
      "current_price_ts": "2026-05-03 19:15:14",
      "value_rub": 1155456.0,
      "currency": "RUB",
      "asset_type": "stock",
      "account": "main",
      "is_blocked": false,
      "nominal_currency": "RUB",
      "ytm_pct": null,
      "ytm_source": null
    },
    {
      "ticker": "RU000A107RH8",
      "name": "Русал 1Р6",
      "qty": 25.0,
      "value_rub": 547252.1,
      "asset_type": "bond",
      "account": "main",
      ...
    },
    {
      "ticker": "RU000A107RH8",
      "name": "Русал 1Р6",
      "qty": 5.0,
      "value_rub": 164175.63,
      "asset_type": "bond",
      "account": "iis_3",
      ...
    }
  ],

  "cash": {...},
  "returns": {...},
  "per_instrument_xirr": {...},

  "ie_model": {
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
        "ticker": "T",
        "name": "Т-Технологии",
        "sector": "Финансовый",
        "target_share_pct": 6.0,
        "current_price_rub": 326.28,
        "entry_price_rub": 300.0,
        "risk_level": "Средний",
        "growth_potential_12m_pct": 22.59,
        "growth_potential_lt_pct": 47.11,
        "div_yield_2024_pct": 45.67,
        "active_in_model": true
      },
      ...21 позиция всего...
    ]
  },

  "ie_actual": {
    "source_sheet": "Акции",
    "extraction_date": "2026-05-03",
    "per_ticker": {
      "SBER": {
        "ie_new_pct": 6.0,
        "ie_old_pct": 6.0,
        "ie_delta_pct": 0.0,
        "real_share_pct": 12.46,
        "planned_share_pct": null,
        "user_action": null,
        "user_note_ie": null,
        "user_note_t": null,
        "user_note_ai": null
      },
      "T": {
        "ie_new_pct": 6.0,
        "ie_old_pct": 6.0,
        "ie_delta_pct": 0.0,
        "real_share_pct": 6.66,
        ...
      },
      ...все активные тикеры с IE-метками...
    }
  },

  "ie_summary": {
    "tickers_in_ie_model": 21,
    "tickers_in_portfolio_active": 25,
    "tickers_in_both": 18,
    "tickers_in_portfolio_not_in_ie": 7,
    "tickers_in_ie_not_in_portfolio": 3,
    "ie_model_total_pct": 100.0,
    "real_share_total_in_ie_pct": 84.5,
    "ie_changes_count": 0,
    "list_in_portfolio_not_in_ie": ["MOEX", "SBERP", "NVTK", "CHMF", "VTBR", "TGLD", "TPAY"],
    "list_in_ie_not_in_portfolio": ["LSNGP"]
  },

  "balance_summary": {
    "total_current_rub": 26278000.0,
    "total_current_rub_excl_iis": 25491335.6,
    "iis_balance_rub": 786664.4,
    "by_account": {
      "main": {
        "total_rub": 25491335.6,
        "stocks_rub": 9000000.0,
        "bonds_rub": 13000000.0,
        "funds_rub": 3000000.0,
        "cash_rub": 491335.6
      },
      "iis_3": {
        "total_rub": 786664.4,
        "stocks_rub": 0.0,
        "bonds_rub": 786664.4,
        "funds_rub": 0.0,
        "cash_rub": 0.0
      }
    },
    "summary": {...},
    "goals_overall": [...]
  },

  "corrections_log": [...],
  "data_quality_flags": [...]
}
```

## 5. Migration plan

### 5.1. Изменения в `parse_portfolio.py`

1. **Поднять `SCHEMA_VERSION = "2.0"`** (или какая константа используется).
2. **Расширить парсинг `.numbers`:**
   - Добавить `parse_ie_model()` — читает вкладку «Invest Era» → блок `ie_model`.
   - Добавить `parse_ie_actual()` — читает колонки `IE New`, `IE Old`, `Доля Реальная`, `Доля Планируемая`, `Действие`, `IE`, `T`, `AI` из вкладки «Акции» → блок `ie_actual`.
   - Добавить `compute_ie_summary()` — derived stats.
   - Добавить `parse_iis_assignment()` — определяет account=iis_3 для каждой позиции на базе вкладки «Облигации» (колонка `ИИС/Итого без ИИСа/Итого на ИИС`).
3. **Скорректировать `balance_summary`:**
   - Пересчитать `total_current_rub_excl_iis` на основе `holdings` с фильтром `account != "iis_3"`.
   - Добавить блок `by_account`.
4. **Добавить новые data quality flags** (см. 3.7).

### 5.2. Изменения в SKILL.md `portfolio-data-loader`

- Раздел «Output schema» — добавить документацию по v2 полям.
- Раздел «Что НЕ парсится» — явно перечислить:
  - Вкладка «Импорт Акции» (raw IntelInvest snapshot) — не используется, так как `holdings` содержит ту же информацию плюс XIRR.
  - Колонки `Точка Входа` и `Стоимость` из вкладки «Акции» — дублируются с MOEX-данными в `holdings`.
- Раздел «Schema versioning» — добавить.

### 5.3. Backward compatibility

- **Новые поля игнорируются** consumers v1.x, которые читают только старые ключи. Это работает безопасно.
- **Старые поля не меняются** — все существующие keys в `holdings`, `cash`, `returns`, `per_instrument_xirr` остаются с тем же smysl.
- **`schema_version` field** уже существует в v1 (как `"1.0"`). v2 consumers проверяют version, v1 consumers могут игнорировать.

### 5.4. Регенерация существующего снапшота

После обновления `parse_portfolio.py`:
```bash
python3 scripts/parse_portfolio.py \
  --balance "Общий баланс.numbers" \
  --trades "trades_portfolio_1414320-7.xlsx" \
  --output "PORTFOLIO-2026-05-03-v2.json"
```

Старый `PORTFOLIO-2026-05-03.json` (v1) сохраняется как backup в Google Drive.

## 6. Acceptance criteria

JSON v2 считается готовым к использованию consumers, когда выполнены все:

- [ ] `schema_version == "2.0"`
- [ ] `ie_model.positions` содержит все 21 позицию из вкладки «Invest Era»
- [ ] `ie_model.model_total_pct` равен 100.0 (или есть warning flag, если нет)
- [ ] `ie_actual.per_ticker` содержит записи для всех тикеров с непустыми `IE New`/`IE Old` из вкладки «Акции»
- [ ] `ie_summary` содержит непустые списки `list_in_portfolio_not_in_ie` и `list_in_ie_not_in_portfolio`
- [ ] Все `holdings` имеют `account` ∈ {`"main"`, `"iis_3"`}
- [ ] Сумма `value_rub` для `account="iis_3"` равна `balance_summary.iis_balance_rub` (с погрешностью ≤1 руб.)
- [ ] `balance_summary.total_current_rub_excl_iis` ≠ `total_current_rub` (баг v1 исправлен)
- [ ] `balance_summary.by_account` присутствует с обоими ключами `main` и `iis_3`
- [ ] Старые поля `holdings`, `cash`, `returns`, `per_instrument_xirr` не изменены (проверка через diff с v1)
- [ ] Decimal parsing работает корректно: «5,59» → 5.59, «-» → null
- [ ] Loader не падает на `.numbers` файле, в котором вкладки «Invest Era» нет (graceful degradation: `ie_model.positions = []`, warning flag)

## 7. Открытые вопросы

| Вопрос | Предлагаемое решение |
|---|---|
| **Что делать, если IE-модель в файле обновлена недавно, а вкладка «Акции» ещё нет?** | Парсить обе независимо. Если рассинхрон — warning flag `ie_model_actual_mismatch` |
| **Хранить ли user_note_ie / user_note_t / user_note_ai как plain text?** | Да. Это пользовательские свободные пометки, никакая семантика не парсится |
| **Что с раздельным ИИС-3 в trades?** | По текущей информации, в `trades_portfolio_*.xlsx` ИИС-3 не отделён → `per_instrument_xirr` для ИИС-3 не считается отдельно. Это TODO для v3. В v2 — единый XIRR на всю позицию |
| **Парсить ли названия секторов IE в нормализованный enum?** | Нет в v2. Хранить raw string из файла. Нормализацию (`«Финансовый» → "financial"`) делать на стороне consumers, если нужно |

## 8. Что НЕ делается в v2 (TODO для будущих версий)

- **Per-account XIRR** (отдельный XIRR для ИИС-3) — нужна отдельная trades-выгрузка.
- **Sector classification normalization** — секторные коды по ОКВЭД-2 / GICS.
- **Вкладка «Облигации» — детализация погашений и оферт** — сейчас только cash flow в `per_instrument_xirr`.
- **План пополнений** (вкладка «Планы») — explicit-blocked правилом №4 в `ru-portfolio-advisor`.
- **Watchlist tickers** (если появится) — пока не используется.

## 9. Что ломается / что НЕ ломается

**Не ломается:**
- Любой код, читающий `holdings[i].ticker`, `holdings[i].value_rub`, `holdings[i].asset_type`, `holdings[i].is_blocked`, `holdings[i].currency` — остаются без изменений.
- `returns.total.xirr_pct`, `returns.by_type.*`, `per_instrument_xirr.*` — не меняются.
- `cash.cash_balance_rub` — не меняется.

**Ломается / требует обновления:**
- Любой код, который сравнивает `holdings[i].account == "main"` без учёта `"iis_3"` (теперь это два разных аккаунта).
- Любой код, который ожидает `total_current_rub_excl_iis == total_current_rub` (бывший баг исправлен).
- Любой код, который читал `metrics.active_stock_tickers` и подобное — поля переименовываются (если такие были; сверять с advisor).

## 10. Размер контракта

**Оценочный размер JSON v2 для текущего портфеля (60+ holdings, 21 IE-позиция):**

- v1: ~93 KB (текущий)
- v2: ~115-120 KB (+25%, в основном из-за `ie_model.positions` и `ie_actual.per_ticker`)

Это в пределах 5MB лимита Google Drive value storage и не создаёт проблем для consumers.
