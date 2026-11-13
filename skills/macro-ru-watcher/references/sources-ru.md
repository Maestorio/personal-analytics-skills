# Sources: первоисточники и парсинг для индикаторов

## Скрипт fetch_macro.py — детерминированный сбор 5 из 7 Tier-1 индикаторов

Файл: `scripts/fetch_macro.py` (внутри скилла, без внешних зависимостей).

Покрывает: **ключевая ставка ЦБ, USD/RUB, CNY/RUB, RGBI, IMOEX** —
через публичные API:
- MOEX ISS (`iss.moex.com/iss/...`) для индексов и валют
- CBR DailyInfoWebServ (SOAP POST) для ключевой ставки

**Запуск (один раз на снапшот, перед web_search):**
```bash
python3 skills/macro-ru-watcher/scripts/fetch_macro.py --pretty
```

**Output schema** (JSON в stdout):
```json
{
  "fetched_at_utc": "2026-05-09T10:45:02Z",
  "indicators": {
    "imoex":   {"status": "ok", "value": 2597.80, "prev_close": 2615.33,
                "change_pct": -0.67, "as_of": "2026-05-08 19:00:13",
                "source": "moex_iss/index"},
    "rgbi":    {"status": "ok", "value": 119.33,  ...},
    "usd_rub": {"status": "ok", "value": 74.0050, ...},
    "cny_rub": {"status": "ok", "value": 10.9245, ...},
    "cbr_key": {"status": "ok", "value": 14.50,   "as_of": "2026-05-08", ...}
  },
  "errors": {}
}
```

**Exit codes:** 0 = все 5 ok; 1 = частичный сбор (см. `errors`); 2 = всё упало.

**Что делать при `status: "error"` отдельного индикатора:** помечать `❓ не получено`
в отчёте, как и при провале web_search. Скрипт уже сделал 3 ретрая с back-off — повторять
вручную не нужно.

**Время:** ~1–2 секунды для всех 5 параллельно. На несколько порядков дешевле
и точнее, чем 5 web_search.

**Зачем не web_search:** котировки MOEX (RGBI/IMOEX/валюты) не индексируются
в реальном времени поисковиками — `web_search` стабильно возвращал landing-pages
без чисел в трёх предыдущих запусках. ISS API — родной endpoint биржи, JSON,
без auth.

**RGBI vs RGBITR:** скрипт возвращает **RGBI** (price index, ~120) — совместим
с историческими snapshot'ами и стандартен для RU финансовой прессы. RGBITR
(total return, ~780) — параллельный ряд, в скрипт не включён, чтобы не было
ложной аномалии +552% при сравнении с историей.

---

## Fallback для USD/RUB при ошибке скрипта

Если `fetch_macro.py` вернул `status: "error"` для `usd_rub` — пробовать по порядку:

1. **MOEX ISS напрямую** — `iss.moex.com/iss/engines/currency/markets/selt/securities/USD000UTSTOM.json?iss.only=marketdata` (тот же эндпоинт, что скрипт, но вручную через web_fetch)
2. **ЦБ РФ XML** — `cbr.ru/scripts/XML_daily.asp` → поле `ValCurs/Valute[CharCode=USD]/Value`
3. **Bloomberg/Investing manual** — web_search паттерн: `USD RUB курс MOEX сегодня`

Если все три упали — `❓ не получено`, продолжай. Не подставляй значение из памяти модели.

---

## Tier 1: оставшиеся 3 индикатора через web_search

Только для тех, кого нет в `fetch_macro.py` (Росстат не имеет чистого API,
Brent — вне периметра RU-источников).

### 1. Инфляция г/г (годовая)

**Источник:** rosstat.gov.ru или cbr.ru
**Primary URL (Росстат):** https://rosstat.gov.ru/storage/mediabank/ipc_god.htm
**Альтернатива (ЦБ):** https://www.cbr.ru/statistics/macro_itm/inflation/
**Web search паттерн:** `инфляция Россия г/г текущая Росстат`
**Что извлечь:** последнее месячное значение CPI YoY (%)
**Формат:** `X.X%`
**Update frequency:** ежемесячно, обычно 5–10 число следующего месяца
**Pitfall:** Росстат публикует разные cuts — нужен именно «годовой темп прироста ИПЦ» (CPI YoY)

### 2. Инфляция недельная

**Источник:** Росстат еженедельные данные
**URL:** https://rosstat.gov.ru/folder/313/document/142853
**Альтернатива:** https://www.cbr.ru/statistics/macro_itm/inflation/ (раздел «недельная»)
**Web search паттерн:** `недельная инфляция Россия Росстат текущая`
**Что извлечь:** прирост ИПЦ за последнюю опубликованную неделю (%)
**Формат:** `X.XX%` (часто очень маленькие числа)
**Update frequency:** еженедельно, обычно среда
**Pitfall:** часто публикуют накопленный с начала месяца + недельный — нужен ТОЛЬКО недельный

### 3. Brent

**Источник:** EIA (US Energy Information Administration) или ICE
**Primary URL:** https://www.eia.gov/dnav/pet/hist/RBRTEd.htm
**Альтернатива:** https://www.theice.com/products/219/Brent-Crude-Futures
**Альтернатива 3:** Bloomberg, Reuters (через web_search, без direct URL)
**Web search паттерн:** `Brent crude oil price closing $ today EIA`
**Что извлечь:** closing price ($/barrel) на ближайший прошедший торговый день
**Формат:** `$XX.XX`
**Update frequency:** ежедневно по торговым дням
**Pitfall:** есть spot price (Europe Brent Spot) и frontmonth futures (ICE Brent Front) — берём frontmonth futures как стандарт; spot publis EIA с задержкой 1 день

---

## Tier 2 (по запросу `--extended` / «расширенный отчёт»)

### 9. Ликвидность банковской системы (структурный профицит/дефицит)

**Источник:** ЦБ РФ
**URL:** https://www.cbr.ru/hd_base/bliquidity/
**Web search паттерн:** `структурный профицит ликвидности банков ЦБ`
**Что извлечь:** последнее значение структурного профицита/дефицита ликвидности (трлн руб; знак: + профицит, − дефицит)
**Формат:** `+X.XX трлн ₽` или `−X.XX трлн ₽`
**Update frequency:** ежедневно
**Pitfall:** ЦБ публикует несколько метрик (ликвидность с учётом ОБР и без; структурный баланс vs остатки) — берём именно «структурный баланс» (structural liquidity surplus/deficit)

### 10. US 10Y Treasury yield

**Источник:** Treasury.gov
**URL:** https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve&field_tdr_date_value=2026
**Альтернатива:** Bloomberg, CNBC
**Web search паттерн:** `US 10 year treasury yield closing today`
**Что извлечь:** closing yield (%) на ближайший прошедший US trading day
**Формат:** `X.XX%`
**Update frequency:** ежедневно по US trading days
**Pitfall:** Treasury публикует несколько curves (Constant Maturity, Real, Nominal) — берём Constant Maturity Nominal (CMT)

### 11. VIX

**Источник:** CBOE
**URL:** https://www.cboe.com/tradable_products/vix/vix_index/
**Web search паттерн:** `VIX index closing today CBOE`
**Что извлечь:** closing value на ближайший прошедший US trading day
**Формат:** `XX.XX`
**Update frequency:** ежедневно по US trading days

### 12. Резервы ЦБ РФ

**Источник:** ЦБ РФ
**URL:** https://www.cbr.ru/hd_base/mrrf/mrrf_m/
**Web search паттерн:** `международные резервы ЦБ РФ текущие`
**Что извлечь:** последнее месячное значение (млрд $)
**Формат:** `$XXX.X млрд`
**Update frequency:** ежемесячно (на 1 число месяца)
**Pitfall:** есть golden reserves отдельно — берём ОБЩИЕ международные резервы ($ + золото + SDR + IMF position)

---

## Общие правила сбора

1. **Сначала запусти `fetch_macro.py`** — он покрывает 5 из 7 Tier-1 индикаторов
   за ~2 секунды детерминированно. Парси JSON.
2. **Затем web_search для оставшихся 3** (инфляция г/г, инфляция нед, Brent
   на Tier 1; для Tier 2 — отдельно по списку ниже). Один запрос на индикатор.
3. **Если запрос не дал чистого результата** — попробуй альтернативный URL.
   Если и он не дал — пометь индикатор `❓ не получено`, продолжай.
4. **Не копи fallbacks.** Если оба URL упали, не ищи через Google/Yandex —
   это снижает качество источника. Лучше показать ❓, чем подсунуть данные
   неизвестного качества. Скрипт `fetch_macro.py` уже сделал 3 ретрая —
   повторно не запускай.
5. **Дата получения значения** фиксируется в отчёте (для ежедневных
   индикаторов — ближайший прошедший trading day; для еженедельных —
   последняя опубликованная неделя). Для скрипта — поле `as_of` в JSON.

## Часовой пояс

Все timestamps в отчёте — MSK (Europe/Moscow). При запуске после 18:00 MSK в пятницу должны быть доступны Russian closing prices текущей недели. Если запуск раньше — берём предыдущую пятницу.

## Прогнозируемые проблемы доступа

- **MOEX ISS / CBR DailyInfo** (через `fetch_macro.py`) — стабильны при наличии
  сети. SSL: на macOS Python 3.13+ может потребоваться `certifi` или
  `/etc/ssl/cert.pem` — скрипт ищет CA bundle автоматически.
- **rosstat.gov.ru** — обычно доступен через web_search.
- **EIA** — стабильно через web_search.
- **Treasury.gov, CBOE** (Tier 2) — стабильно.
