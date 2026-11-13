# Приоритет источников биржевых данных и fallback-стратегия

Этот файл читай всегда, когда нужно получить **цену, YTM, дюрацию, объём, рыночную капитализацию, статус листинга** или любую другую рыночную метрику по бумаге. Он описывает, где брать данные в первую очередь, что делать при недоступности основного канала и как не скатиться в галлюцинацию цифр.

## TL;DR — правило одной строки

**MOEX ISS → (fail) → MOEX web → (fail) → рус. брокеры/Cbonds → (fail) → явно сказать пользователю "данные недоступны, работаю по файлу".** Цифры из памяти / training data **не использовать никогда**.

## Уровень 1 — MOEX ISS API (дефолт)

**Канал:** `https://iss.moex.com/iss/` — официальный, бесплатный, без авторизации, XML/JSON, задержка ~15 минут.

**Что покрывает (~95% ежедневных запросов по портфелю):**
- Акции: `LAST`, `BID`, `OFFER`, `PREVPRICE`, `LASTCHANGEPRCNT`, `VALTODAY_RUR`, `ISSUECAPITALIZATION`, `LISTLEVEL`, `ISIN`.
- Облигации: `YIELD` (YTM), `YIELDTOOFFER` (YTP), `DURATION`, `ZSPREAD`, `COUPONVALUE`, `COUPONPERCENT`, `NEXTCOUPON`, `MATDATE`, `OFFERDATE`, `FACEVALUE`, `FACEUNIT`, `ACCRUEDINT`, `BONDTYPE`.
- БПИФ / ETF: те же поля, что у акций, доска `TQTF`.
- Справочник досок: `/iss/securities.xml?q=<SECID или ISIN>` — возвращает `primary_boardid` и `is_traded=1/0`.

**Как пользоваться:**
Вместо ручного формирования URL используй скрипт `scripts/moex_quotes.py` (см. раздел ниже). Он:
- Батчит до 10 тикеров за один HTTP-вызов.
- Автоматически определяет биржевую доску по SECID или ISIN.
- Ретраит на сетевых ошибках.
- Возвращает единый JSON со стабильной схемой.

**Ограничения:**
- Задержка 15 мин — для еженедельных обзоров несущественно.
- Вне торговых часов `LAST` может быть пустым — используй `PREVPRICE` (он же `prev_close` в скрипте).
- Не покрывает: исторические YTM-кривые (есть `/iss/history/...`, но для недельного обзора избыточно), кредитные рейтинги, новости эмитентов.

## Уровень 2 — MOEX web (первый fallback)

Если ISS вернул HTTP 5xx или timeout на трёх попытках подряд (≥10 сек каждая):

- **Страница инструмента на moex.com:** `https://www.moex.com/ru/issue.aspx?board=TQBR&code=SBER` (для акций) или `https://www.moex.com/ru/issue.aspx?board=TQCB&code=RU000A105A95` (для облигаций). Отдаёт тот же срез, что и ISS, но через другой backend. Скрейпинг возможен через `web_fetch`.
- **Аналитический календарь дивидендов/купонов:** `https://www.moex.com/ru/listing/emission-docs.aspx` — для проверки оферт и выплат, если ISS-поле `OFFERDATE` пустое.

**Сценарий срабатывания Уровня 2:** редкий, обычно связан с техобслуживанием ISS (обычно по выходным 02:00–06:00 МСК).

## Уровень 3 — Российские брокеры и справочники (второй fallback)

Если и `iss.moex.com`, и `www.moex.com` не отвечают (такое случается при инфраструктурных инцидентах Мосбиржи), то:

**Для акций** (котировки и базовые метрики):
- **T-Инвестиции:** `https://www.tbank.ru/invest/stocks/SBER/` — котировка, дневное изменение, объём. Задержка аналогичная.
- **БКС Экспресс:** `https://bcs-express.ru/kotirovki-i-grafiki/sber` — текст+график.
- **Финам:** `https://www.finam.ru/quote/moex/sber/` — график, статистика.
- **Investing.com:** `https://ru.investing.com/equities/sberbank_rts` — резервный канал, но может быть geo-blocked.

Веб-скрейпинг этих страниц через `web_fetch` работает, но хрупкий — верстка меняется. Источник даты/времени котировки фиксируй явно.

**Для облигаций** (YTM, дюрация, купонные графики):
- **Rusbonds:** `https://www.rusbonds.ru/isin/<ISIN>` — YTM, дюрация, купонный календарь, рейтинги. Часть данных бесплатна.
- **Cbonds:** `https://cbonds.ru/bonds/<ID>/` — справочник, графики исторической YTM; глубокая аналитика за пейволом, но карточка выпуска видна.
- **T-Инвестиции** — есть страницы по облигациям с YTM: `https://www.tbank.ru/invest/bonds/<ISIN>/`.

## Уровень 4 — Fallback для справочных параметров эмитента

Это **не котировки**, а параметры выпуска и эмитента. Если их не хватает после Уровня 1:

- **E-disclosure:** `https://e-disclosure.ru/portal/company.aspx?id=<ID>` — проспекты, сущфакты, раскрытия. Первоисточник по купонным графикам и офертам.
- **Пресс-релизы рейтинговых агентств** — см. `references/sources.md`, раздел "Уровень 1 — Первичка".
- **Смартлаб:** `https://smart-lab.ru/q/bonds/` — агрегирует MOEX + брокеров; удобно, но **не первичка**.

## Уровень 5 — Ручной расчёт YTM (крайняя мера)

Если **цена** доступна, а **YTM** — нет (например, MOEX не отдал `YIELD`, потому что за сегодня не было сделок), его можно посчитать самому по формуле IRR:

- Вход: текущая цена (чистая, % от номинала), купонный график (`COUPONVALUE` × даты), номинал, дата погашения, НКД (`ACCRUEDINT`).
- Метод: IRR на cash-flow с шагом до `MATDATE` (или до `OFFERDATE`, если есть). Можно через `scipy.optimize.brentq` или вручную методом Ньютона.
- Пометка в отчёте: "YTM рассчитан из цены + купонного графика, не из прямой котировки MOEX".

Обычно это избыточно — проще взять последний рабочий срез `YIELD` из MOEX history API:
```
https://iss.moex.com/iss/history/engines/stock/markets/bonds/securities/<ISIN>.xml?from=2026-04-10&till=2026-04-18
```

## Уровень 6 — Честное "данные недоступны"

Если прошли все уровни и данные по бумаге получить не удалось — **не подставляй цифры по памяти или из прошлой сессии**. Выводи в отчёте:

```
[TICKER / ISIN] — данные MOEX ISS недоступны (причина: <HTTP 5xx / timeout / бумага не найдена>).
Анализ ведётся по данным из файла пользователя (`Текущая стоимость` = X ₽ на момент последнего обновления портфеля).
Рекомендация: перепроверить котировку вручную через терминал брокера перед принятием решения.
```

Это лучше, чем подставлять правдоподобное число.

---

## Скрипт `scripts/moex_quotes.py` — стандартизированный интерфейс

Единая точка входа для всех запросов к MOEX ISS. Используй его **до** любого другого web-поиска цен.

### Что внутри (почему быстро)

Скрипт применяет 6 последовательных оптимизаций:

1. **Column filter** (`marketdata.columns=SECID,LAST,YIELD,...`) — MOEX возвращает только запрошенные поля. Без фильтра ответ весит 15 kB, с фильтром — 0.5 kB (×30 экономии).
2. **gzip** (`Accept-Encoding: gzip`) — дополнительное сжатие ×2.6, ускорение ×1.8.
3. **JSON standard** вместо XML — на 28% быстрее, числа приходят как числа (не строки), парсится через `import json`.
4. **Параллельные HTTP-запросы** по разным доскам через `ThreadPoolExecutor`. На портфеле "акции + ОФЗ + корп + БПИФ" даёт ×3–4 ускорение.
5. **Пакетирование до 10 SECID** на запрос (лимит MOEX).
6. **Опциональный `kind_hint`** пропускает discovery и экономит N HTTP-вызовов, если все SECID одного типа.

**Суммарный выигрыш** против наивного подхода (XML, без фильтра, без gzip, последовательно):
- Размер ответа: ×30 меньше.
- Latency на портфель из 22 бумаг: 1.3 с вместо ~15 с (×10 быстрее).

### Профили полей (`--fields`)

Профиль определяет, какие колонки MOEX вернёт. Выбирай по задаче:

**`minimal`** — только цена и статус торговли. Для:
- Быстрой проверки "сколько стоит сейчас".
- Скрининга большого списка (50+ бумаг) на движение за день.
- Health-check после pipeline-сбоя.

Поля: `last`, `prev_close`, `trading_status`, `timestamp`, плюс `short_name` / `maturity_date` / `face_unit` для идентификации. Для облигаций дополнительно — `ytm_pct`.

**`weekly`** (дефолт) — оптимизирован под Weekly Stocks/Bonds Review. Для:
- Еженедельных обзоров.
- Оценки ребалансировки.
- Сравнения позиций с IE.

Поля акций: `last`, `change_pct`, `volume_rub_today`, `list_level`, `isin`, `prev_close`, `prev_date`, `board` + все из minimal.
Поля облигаций: добавляются `ytm_to_offer_pct`, `duration_days`, `coupon_value`, `coupon_pct`, `next_coupon_date`, `offer_date`, `accrued_interest`, `bond_type`, `change_pct`, `volume_rub_today`.

**`full`** — максимум. Для:
- Single Stock / Single Bond Analysis.
- Разбора спорной позиции.
- Debug, когда `fields_missing` в weekly сигнализирует проблему.

Поля акций: + `bid`, `offer`, `open/high/low`, `waprice`, `market_cap_rub`, `num_trades`, `vol_today`.
Поля облигаций: + `yield_at_waprice`, `z_spread_bps`, `bid`, `offer`, `waprice`, `num_trades`.

### Бенчмарк

Измерено на типичном портфеле 22 бумаги (19 акций TQBR + ОФЗ + замещайка USD + БПИФ) на Claude-сэндбоксе:

| Сценарий | Вызовов HTTP | Время |
|---|---|---|
| 22 SECID, weekly, параллельно (auto-discovery) | ~25 | **1.3 с** |
| 22 SECID, weekly, без параллельности | ~25 | 5.5 с |
| 19 акций, `--type share` (skip discovery), weekly | 2 | **0.33 с** |
| 19 акций, minimal vs weekly vs full | одинаково | 0.33 с (разница в байтах, не latency) |

**Правило:** когда режим известен заранее (Weekly Stocks Review работает только с акциями), всегда передавай `kind_hint` / `--type`. Это экономит N discovery-запросов.

### Базовое использование (CLI)

```bash
# Дефолт — weekly-профиль, параллельно, auto-discovery
python3 scripts/moex_quotes.py SBER GAZP LKOH SU26238RMFS4 RU000A105A95

# Минимальный набор полей — для скрининга или скорости
python3 scripts/moex_quotes.py --fields minimal SBER GAZP LKOH

# Полный разбор облигации для Single Bond Analysis
python3 scripts/moex_quotes.py --fields full SU26238RMFS4

# Weekly Stocks Review — все акции, пропуск discovery
python3 scripts/moex_quotes.py --type share --fields weekly \
    SBER SBERP GAZP LKOH ROSN TATN SIBN SNGS NVTK CHMF

# JSON для передачи в Research / последующий анализ
python3 scripts/moex_quotes.py --json --fields weekly --from-portfolio /tmp/portfolio.json > /tmp/quotes.json

# Тайминг в stderr
python3 scripts/moex_quotes.py --bench --fields weekly SBER GAZP

# Health-check перед большим пакетом
python3 scripts/moex_quotes.py --health
```

### Python API

```python
from moex_quotes import fetch_quotes, health_check, secids_from_portfolio

# Проверка перед запросом
if not health_check(timeout=5).get("ok"):
    # → Уровень 2 (MOEX web / web_fetch)
    ...

# Weekly Bonds Review — только облигации, пропуск discovery
quotes, errors = fetch_quotes(
    ["SU26238RMFS4", "RU000A105A95", "RU000A108F82"],
    fields="weekly",
    kind_hint="bond",   # или 'ofz' для чистых ОФЗ-пакетов
    parallel=True,
)

for secid, q in quotes.items():
    print(secid, q.ytm_pct, q.duration_days, q.maturity_date)
    if q.fields_missing:
        # Критическое поле не пришло — fallback нужен
        print(f"  fallback for: {q.fields_missing}")
```

### Когда какой профиль запрашивать (матрица)

| Режим скилла | Профиль | kind_hint | Обоснование |
|---|---|---|---|
| Weekly Stocks Review | `weekly` | `share` | Нужны цена, изменение за день, объём, для всех акций |
| Weekly Bonds Review | `weekly` | не указывать (смесь ОФЗ+корп) | YTM, duration, оферта — все в weekly |
| Rebalance Opinion | `weekly` | не указывать | Все типы, одинаковый набор полей достаточен |
| Single Stock Analysis | `full` | `share` | Нужны market_cap, bid/offer, OHLC |
| Single Bond Analysis | `full` | `bond` или `ofz` | z-spread, yield_at_waprice, все метрики |
| Fund Analysis | `weekly` | `etf` | Цена + объём, TER и СЧА берутся из другого endpoint'а / с сайта УК |
| "Что с X сейчас" быстрый вопрос | `minimal` | — | Только цена + статус торговли |
| Скрининг 50+ бумаг на движения | `minimal` | — | Экономия байт, латентность та же |

### Критически отсутствующие поля — `fields_missing`

Если в ответе скрипта поле `fields_missing` непусто — MOEX не отдал одно или несколько критических полей. Это бывает в трёх случаях:

1. **Вне торговых часов** (после 23:50 МСК, выходные, праздники) — `last`, `change_pct`, иногда `ytm_pct` пусты. Используй `prev_close` и помечай "срез на конец предыдущей сессии".
2. **Бумага временно не торгуется** (`trading_status=S` или `N`) — например, приостановка торгов на дискретный аукцион.
3. **Редкая бумага без сделок за день** — `YIELD` отсутствует, нужно либо взять `YIELDATWAPRICE` (средневзвешенный), либо перейти на Уровень 2–5 этого документа.

LLM должна в отчёте явно пометить такие бумаги: "данные MOEX неполные: не пришло `[fields]`, источник fallback — [...]".

### Выходная схема (ключевые поля)

Для акций и БПИФ:
```
{
  "secid": "SBER", "kind": "share" | "etf",
  "board": "TQBR" | "TQTF", "short_name": "Сбербанк", "isin": "RU0009029540",
  "currency": "SUR",
  "last": 324.25, "prev_close": 323.87, "change_pct": 0.12,
  "bid": 324.25, "offer": 324.30,          # только в full
  "volume_rub_today": 770_336_051,
  "market_cap_rub": 7_000_863_105_880,     # только в full
  "list_level": 1,
  "trading_status": "T",
  "timestamp": "2026-04-18 17:59:26",
  "source": "moex_iss", "profile": "weekly"
}
```

Для облигаций:
```
{
  "secid": "SU26238RMFS4", "kind": "bond",
  "board": "TQOB" | "TQCB", "short_name": "ОФЗ 78714",
  "isin": "RU000A1038V6",
  "currency": "SUR" | "USD" | "EUR" | "CNY",   # из FACEUNIT
  "last": 59.72,                 # % от номинала
  "prev_close": 59.665, "change_pct": 0.09,
  "ytm_pct": 13.82,              # YIELD из MOEX
  "ytm_to_offer_pct": null,
  "duration_days": 2712,
  "z_spread_bps": 58.0,          # только в full
  "accrued_interest": 27.04,
  "coupon_value": 35.4, "coupon_pct": 7.1,
  "next_coupon_date": "2026-06-03",
  "maturity_date": "2041-05-15",
  "offer_date": null,
  "face_value": 1000.0,
  "bond_type": "Фикс с известным купоном",
  "timestamp": "2026-04-18 17:59:26",
  "source": "moex_iss", "profile": "weekly"
}
```

### Когда НЕ запускать скрипт

- **Анализ, не требующий текущих котировок** (разбор МСФО за прошлый квартал, оценка дивидендной политики из устава). Котировки в таких задачах — справочно, достаточно `PREVPRICE` из файла пользователя.
- **Анализ единичного события** (рейтинговое действие АКРА сегодня) — здесь важен первоисточник (пресс-релиз), а не цена.
- **Исторический анализ** (YTM два года назад) — используй `/iss/history/...` напрямую, это отдельный endpoint; скрипт заточен на срез "сейчас".

### Чек-лист оптимального запроса

Перед запуском `moex_quotes.py` проверь:

1. **Какой профиль нужен?** Не запрашивай `full`, если достаточно `weekly`. Не запрашивай `weekly`, если нужно только "сколько стоит сейчас" — бери `minimal`.
2. **Знаю ли я тип всех бумаг?** Если да — всегда передавай `--type` / `kind_hint`. Экономит N discovery-запросов.
3. **Один ли раз за сессию?** Результат `/tmp/quotes.json` актуален минимум 15 минут (задержка MOEX). В рамках одного обзора переиспользуй, не запрашивай повторно.
4. **Нужны ли все бумаги портфеля?** Для Single Stock Analysis — один SECID, не весь файл. `--from-portfolio` оправдан только для Weekly-обзоров и ребалансировки.
5. **Проверить ли доступность ISS?** Для пакетов >30 SECID — да, сначала `--health`. Для 1–5 SECID — не окупается, retries внутри скрипта справятся.

## Сводная таблица: какой источник для какой задачи

| Задача | Первый выбор | Fallback |
|---|---|---|
| Текущая цена акции | `moex_quotes.py` | moex.com/ru/issue.aspx → T-Инвестиции |
| Дневное изменение % | `moex_quotes.py` (`change_pct`) | moex.com → T-Инвестиции |
| Текущий YTM облигации | `moex_quotes.py` (`ytm_pct`) | Rusbonds → Cbonds → ручной IRR |
| Дюрация | `moex_quotes.py` (`duration_days`) | Rusbonds |
| НКД | `moex_quotes.py` (`accrued_interest`) | Rusbonds |
| Дата оферты | `moex_quotes.py` (`offer_date`) | e-disclosure (первичка) |
| Купонный график (будущий) | `/iss/statistics/engines/stock/markets/bonds/bondization/<ISIN>.xml` | e-disclosure |
| Рыночная капитализация | `moex_quotes.py` (`market_cap_rub`) | moex.com → Smartlab |
| Исторический YTM | `/iss/history/...` напрямую | Cbonds |
| Кредитный рейтинг эмитента | **НЕ MOEX** — первичка AKRA/RA Expert/NKR/NRA | — |
| Отчётность МСФО/РСБУ | **НЕ MOEX** — сайт IR эмитента, e-disclosure | — |
| Новости и сущфакты | **НЕ MOEX** — e-disclosure, пресс-релизы, СМИ | — |

---

## Интеграция с обязательным процессом анализа

В `SKILL.md`, раздел "Обязательный процесс анализа" шаг 1 — "Запусти парсер". Шаг 1.5 (новый):

> **1.5. Подгрузи свежие котировки и YTM через `moex_quotes.py --from-portfolio /tmp/portfolio.json --json > /tmp/quotes.json`.** Это даст единый снапшот на момент начала анализа, который потом переиспользуется во всех разделах отчёта. Если `health_check` вернул `ok=false` — переходи на Уровень 2 и сообщи пользователю в шапке отчёта, что данные получены с задержкой/через резервный канал.
