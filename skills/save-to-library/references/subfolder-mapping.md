# Subfolder Mapping: расширенный маппинг subdomain → subfolder

Этот файл помогает скиллу `save-to-library` однозначно определять, в какой subfolder класть аудит.

---

## Алгоритм определения subfolder

1. Взять все subdomain'ы из поля `trust` в frontmatter
2. Для каждого subfolder'а посчитать количество совпадений
3. Выбрать subfolder с max совпадений
4. При равенстве — озвучить сомнение, спросить пользователя

---

## Каноническая таблица subdomain'ов

### geopolitics

| Subdomain | Описание | Типичные источники |
|-----------|----------|-------------------|
| `long-term-russia` | Прогнозы на Россию >5 лет | Stratfor, CFR, Carnegie, Brookings |
| `short-term-russia` | Прогнозы на Россию <2 лет | Stratfor, CEPA, ECFR |
| `eu-future` | Будущее ЕС, евроинтеграция | Bruegel, ECFR, Brookings |
| `china-collapse` | Прогнозы дезинтеграции/кризиса Китая | Gordon Chang style, Stratfor |
| `china-rise` | Прогнозы технологического/экономического подъёма | Goldman Sachs, McKinsey |
| `middle-east` | Ближний Восток в широком смысле | Stratfor, CFR, ISS |
| `iran` | Конкретно Иран (ядерная программа, политика) | CFR, IISS, Carnegie |
| `us-domestic` | Внутренняя политика США, выборы | Brookings, Pew |
| `nato-future` | Будущее НАТО, расширение | IISS, Chatham House |
| `nuclear-proliferation` | Распространение ядерного оружия | SIPRI, Carnegie |
| `migration-eu` | Миграционные кризисы в Европе | ECFR, Pew |

### ru-sellside

| Subdomain | Описание | Типичные источники |
|-----------|----------|-------------------|
| `iis-targets` | Таргеты для ИИС-3, 1–3 года | БКС, Альфа, SberCIB |
| `long-term-strategy` | Стратегические рекомендации >3 лет | Invest Era, БКС Premium |
| `oil-gas-ru` | Нефтегазовый сектор РФ | SberCIB, Газпромбанк |
| `metals-mining-ru` | Металлы и горнодобыча РФ | Альфа, ВТБ Капитал |
| `it-tech-ru` | Российский IT (Яндекс, Хэдхантер, OZON) | БКС, Финам |
| `finance-ru` | Финансовый сектор РФ (Сбер, TCS) | Альфа, SberCIB |
| `consumer-ru` | Потребительский сектор | БКС, Атон |
| `bonds-rub` | Рублёвые облигации (ОФЗ, корп.) | Cbonds, Альфа |
| `bonds-fx` | Валютные облигации (замещайки, CNY) | Атон, ВТБ |
| `dividend-stocks` | Дивидендные акции РФ | Invest Era, БКС |
| `small-caps-ru` | Small-caps (Астра, МГКЛ, Европлан) | Атон, Финам |
| `etfs-ru` | Российские ETF / БПИФы (TGLD, SBMX) | Invest Era, БКС |

### global-banks

| Subdomain | Описание | Типичные источники |
|-----------|----------|-------------------|
| `us-equities` | Американские акции (S&P, NASDAQ) | Goldman Sachs, JPM, MS |
| `european-equities` | Европейские акции | UBS, Deutsche Bank |
| `emerging-markets` | Развивающиеся рынки в целом | JPM, GS EM Research |
| `oil-forecast` | Прогнозы нефтяных цен (Brent, WTI) | Goldman Sachs, Citi |
| `commodities-non-oil` | Золото, серебро, агро | Goldman Sachs, Barclays |
| `currency-forecasts` | Валютные прогнозы (EUR/USD, EM FX) | JPM, Citi |
| `ny-rates` | Ставки ФРС, доходности US Treasuries | Goldman Sachs, Pimco |
| `crypto` | Криптовалютные прогнозы | JPM Digital Assets |
| `ai-stocks-bubble` | Прогнозы пузыря AI-акций | Goldman, MS Tech |
| `recession-call` | Прогнозы рецессии в США/ЕС | GS, JPM, Nomura |
| `sector-rotation` | Рекомендации по секторной ротации | JPM, UBS |

### tech-ceo

| Subdomain | Описание | Типичные источники |
|-----------|----------|-------------------|
| `agi-timeline` | Прогнозы достижения AGI | Altman, Hassabis, Lecun |
| `model-capability` | Конкретные capability predictions | Altman, Demis, Ilya |
| `regulation-ai` | Регуляторные прогнозы (EU AI Act, etc) | Altman, Zuckerberg |
| `compute-economics` | Экономика compute, scaling laws | Dario, Ilya |
| `crypto` | Для CEO с крипто-позицией | Musk, Saylor |
| `space-tech` | Космические прогнозы | Musk |
| `biotech-future` | Медицина/биотех | Altman, Hassabis |

### ru-macro

| Subdomain | Описание | Типичные источники |
|-----------|----------|-------------------|
| `ru-rates-forecast` | Ставка ЦБ РФ | ЦБ, SberCIB, Альфа |
| `ru-inflation` | Инфляция в РФ | ЦБ, Bloomberg Economics |
| `usd-rub-forecast` | Прогнозы USD/RUB | БКС, Альфа, SberCIB |
| `cny-rub-forecast` | Прогнозы CNY/RUB | РСХБ, Газпромбанк |
| `ru-budget` | Бюджет РФ, нефтегазовые доходы | Минфин, ЦБ, SberCIB |
| `ru-economy-growth` | ВВП, промпроизводство, рынок труда | ЦБ, МВФ, ВБ |
| `ru-banking-system` | Банковский сектор РФ, кредитование | ЦБ, АКРА |

### commodity-agencies

| Subdomain | Описание | Типичные источники |
|-----------|----------|-------------------|
| `oil-market` | Общий обзор рынка нефти | IEA OMR, OPEC OMR, EIA |
| `oil-demand` | Прогнозы спроса на нефть | IEA, OPEC, EIA |
| `oil-supply` | Прогнозы добычи и предложения | IEA, OPEC, EIA |
| `gas-market` | Рынок газа (СПГ, трубопроводный) | IEA, Газпром отчёты |
| `lng` | СПГ — торговля, мощности, цены | IEA, Shell LNG Outlook |
| `metals` | Металлы: железная руда, медь, алюминий | World Bank, USGS |
| `coal` | Рынок угля | IEA Coal, IEEFA |
| `agricultural` | Агропродукция: зерно, масло, сахар | FAO, USDA |
| `iea-omr` | IEA Oil Market Report специфически | IEA |
| `opec-omr` | OPEC Monthly Oil Market Report | OPEC |
| `energy-transition` | Энергопереход, возобновляемая энергия | IEA WEO, IRENA |

---

## Примеры маппинга для реальных источников

| Источник | Subdomain'ы (примеры) | Subfolder |
|----------|----------------------|-----------|
| Stratfor | long-term-russia, eu-future, middle-east | geopolitics |
| CFR | iran, us-domestic, long-term-russia | geopolitics |
| Goldman Sachs (macro) | us-equities, oil-forecast, ny-rates | global-banks |
| Goldman Sachs (geo) | eu-future, russia-risk | geopolitics → ⚠️ уточнить |
| БКС | iis-targets, oil-gas-ru, dividend-stocks | ru-sellside |
| Invest Era | iis-targets, etfs-ru, long-term-strategy | ru-sellside |
| SberCIB | ru-rates-forecast, ru-inflation, usd-rub-forecast | ru-macro или ru-sellside → ⚠️ уточнить |
| Sam Altman | agi-timeline, model-capability, regulation-ai | tech-ceo |
| ЦБ РФ | ru-rates-forecast, ru-inflation, ru-banking-system | ru-macro |
| Альфа-Банк research | iis-targets, metals-mining-ru, ru-rates-forecast | ru-sellside или ru-macro → ⚠️ уточнить |
| IEA OMR | iea-omr, oil-market, oil-demand, oil-supply | commodity-agencies |
| OPEC OMR | opec-omr, oil-market, oil-supply | commodity-agencies |
| EIA Short-Term Outlook | oil-market, oil-demand, oil-supply | commodity-agencies |
| Shell LNG Outlook | lng, gas-market | commodity-agencies |

---

## Нестандартные subdomain'ы: что делать

Если в файле встречается subdomain, которого нет в таблицах выше:

1. Попытаться семантически сопоставить с ближайшим каноническим
   - `brent-2025-price` → `oil-forecast` (в global-banks)
   - `ru-key-rate` → `ru-rates-forecast` (в ru-macro)
   - `llm-scaling` → `model-capability` (в tech-ceo)

2. Если сопоставление неочевидно — озвучить: «Нестандартный subdomain `{name}`. Это ближе к {вариант A} или {вариант B}?»

3. Если пользователь настаивает на нестандартном имени — использовать как есть, отметить в INDEX.md: «нестандартный subdomain»

---

## Источники с пограничным доменом

Некоторые источники покрывают несколько субдоменов из разных папок. Правило:

- **Посчитать совпадения** → выбрать папку с max совпадений
- **Если равенство** → предпочесть тот subfolder, который является «основным бизнесом» источника (Goldman Sachs → global-banks, даже если есть 1 геополитический subdomain)
- **Если явно кросс-доменный источник** (например, Сбербанк CIB публикует и макро, и акции) → спросить пользователя или создать отдельные аудиты для каждого домена

---

## Исключения и специальные случаи

**Академические think tanks** (CFR, Brookings, Carnegie, Chatham House) → всегда `geopolitics`, даже если есть экономические прогнозы

**Центральные банки** (ЦБ РФ, ФРС, ЕЦБ) → `ru-macro` для ЦБ РФ, `global-banks` для ФРС/ЕЦБ

**Commodity-агентства** (IEA, OPEC, EIA, IRENA) → всегда `commodity-agencies`. Исключение: если IEA публикует геополитический прогноз (редко) — по содержанию.

**Telegram-каналы** — по содержанию subdomain'ов, не по названию канала

**Персональные аналитики** — по организации, не по имени: «Goldman Sachs / Jan Hatzius» → source = «Goldman Sachs»
