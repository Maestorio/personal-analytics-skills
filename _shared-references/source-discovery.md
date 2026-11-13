# Source Discovery

Списки источников по 5 доменам с паттернами web_search.

---

## Домен: geopolitics

| Источник | Субдомены силы | Где искать | Паттерн поиска |
|---|---|---|---|
| Stratfor | Russia long-term, US foreign policy | stratfor.com, worldview.stratfor.com | `stratfor "{topic}" forecast 2026 OR 2027 site:stratfor.com OR site:worldview.stratfor.com` |
| Council on Foreign Relations (CFR) | US policy, multilateral institutions | cfr.org | `cfr.org "{topic}" forecast outlook 2026` |
| Brookings Institution | US domestic, Middle East, China | brookings.edu | `brookings.edu "{topic}" forecast analysis 2026` |
| Carnegie Endowment | Russia, Central Asia, nuclear | carnegieendowment.org | `carnegieendowment.org "{topic}" 2026 forecast` |
| ECFR (European Council on Foreign Relations) | EU foreign policy, Russia-EU | ecfr.eu | `ecfr.eu "{topic}" forecast scorecard 2026` |
| Chatham House | UK/global security, Russia | chathamhouse.org | `chathamhouse.org "{topic}" outlook 2026` |
| RAND Corporation | Defense, geopolitical risk | rand.org | `rand.org "{topic}" analysis forecast 2026` |

**Примечание**: Stratfor часто за paywall. Ищи summary/abstract или цитаты в агрегаторах.
Fallback-запрос: `"{topic}" stratfor forecast 2026 -site:stratfor.com`

**Важно**: дефолтный список выше — Atlantic mainstream, и для тем с поляризованной
атрибуцией ответственности он недостаточен. Для конфликтных и политически-полярных тем
смотри `references/perspective-maps.md` — там карты лагерей с носителями всех
институциональных сторон (US realist / Russia-side / China-side / Iran-side / regional).

---

## Домен: ru-sellside

| Источник | Субдомены силы | Где искать | Паттерн поиска |
|---|---|---|---|
| БКС (BCS Global Markets) | MOEX equities, oil & gas | bcs-express.ru, bcs-gm.ru | `БКС "{тема}" прогноз целевая цена 2026 site:bcs-express.ru` |
| Альфа-Инвестиции | MOEX, banks, retail | alfainvestments.ru, alfabank.ru | `Альфа инвестиции "{тема}" прогноз 2026 аналитика` |
| SberCIB | Macro RU, energy, metals | sberbank.ru, sber.ru | `SberCIB "{тема}" прогноз 2026 OR "Сбер Инвестиции" аналитика` |
| Т-Инвестиции (бывш. Тинькофф) | MOEX broad, retail | tbank.ru, tinkoff.ru | `"Т-Инвестиции" OR "Тинькофф инвестиции" "{тема}" прогноз 2026` |
| Атон (ATON) | MOEX, M&A | aton.ru | `Атон "{тема}" прогноз целевая 2026 site:aton.ru` |
| ВТБ Капитал | Energy, Macro RU | vtb.ru | `"ВТБ Капитал" OR "ВТБ Мои Инвестиции" "{тема}" прогноз 2026` |
| Финам | MOEX broad | finam.ru | `Финам аналитика "{тема}" прогноз 2026 site:finam.ru` |

**Примечание**: Российские брокеры публикуют аналитику преимущественно на своих сайтах
и в Telegram. Если site: поиск не даёт результатов, используй:
`"{название брокера}" "{тема}" прогноз 2026 целевая цена`

---

## Домен: global-banks

| Источник | Субдомены силы | Где искать | Паттерн поиска |
|---|---|---|---|
| Goldman Sachs (GS) | US macro, S&P, commodities | goldmansachs.com | `"Goldman Sachs" "{topic}" forecast 2026 outlook` |
| JPMorgan | Global macro, EM, credit | jpmorgan.com | `"JPMorgan" OR "JP Morgan" "{topic}" forecast 2026` |
| Morgan Stanley | Equities, US rates | morganstanley.com | `"Morgan Stanley" "{topic}" forecast 2026 outlook` |
| Bank of America (BofA) | US consumer, commodities | bofasecurities.com | `"Bank of America" OR "BofA" "{topic}" forecast 2026` |
| Citi | EM, FX, commodities | citigroup.com | `"Citi" OR "Citibank" "{topic}" forecast 2026` |
| Barclays | UK macro, credit | barclays.com | `"Barclays" "{topic}" forecast 2026 outlook` |
| UBS | Wealth, global equities | ubs.com | `"UBS" "{topic}" forecast 2026 outlook` |

**Примечание**: Большинство репортов за paywall. Ищи Bloomberg, Reuters, Financial Times
цитирующие прогнозы: `site:bloomberg.com "Goldman Sachs" "{topic}" forecast 2026`
или `"Goldman Sachs" "{topic}" forecast 2026 -site:goldmansachs.com`

---

## Домен: tech-ceo

| Источник | Субдомены силы | Где искать | Паттерн поиска |
|---|---|---|---|
| Илон Маск | AI risk, energy, EV | x.com, tesla.com | `Elon Musk "{topic}" forecast prediction 2026 2027` |
| Сэм Альтман (OpenAI) | AGI timeline, AI capabilities | openai.com | `"Sam Altman" "{topic}" forecast prediction 2026` |
| Дженсен Хуанг (NVIDIA) | GPU, AI compute, data centers | nvidia.com | `"Jensen Huang" "{topic}" forecast outlook 2026` |
| Демис Хассабис (DeepMind/Google) | AI research, protein folding | deepmind.google | `"Demis Hassabis" "{topic}" forecast prediction 2026` |
| Дарио Амодеи (Anthropic) | AI safety, alignment | anthropic.com | `"Dario Amodei" "{topic}" forecast 2026` |
| Сатья Наделла (Microsoft) | Enterprise AI, cloud | microsoft.com | `"Satya Nadella" "{topic}" forecast outlook 2026` |
| Марк Цукерберг (Meta) | Social, AR/VR, AI | meta.com | `"Mark Zuckerberg" "{topic}" forecast 2026` |

**Примечание**: Tech-CEO прогнозы часто в интервью, конференциях, earnings calls.
Ищи на YouTube транскрипты, TechCrunch, The Verge, Ars Technica.

---

## Домен: ru-macro

| Источник | Субдомены силы | Где искать | Паттерн поиска |
|---|---|---|---|
| ЦБ РФ | Ключевая ставка, инфляция, рубль | cbr.ru | `ЦБ РФ "{тема}" прогноз 2026 cbr.ru` |
| Минфин РФ | Бюджет, нефтегазовые доходы, ОФЗ | minfin.ru | `Минфин "{тема}" прогноз 2026 site:minfin.ru` |
| ВЭБ.РФ | Инвестиции, инфраструктура, ВВП | veb.ru | `ВЭБ "{тема}" прогноз 2026 site:veb.ru` |
| ЦМАКП | Макро сценарии, промышленность | forecast.ru | `ЦМАКП "{тема}" прогноз 2026 site:forecast.ru` |
| МВФ (Russia) | External assessment of RU macro | imf.org | `IMF Russia "{topic}" forecast 2026 site:imf.org` |
| Всемирный банк (Russia) | GDP, poverty, development | worldbank.org | `World Bank Russia "{topic}" forecast 2026` |

---

## Общие советы по поиску

1. **Если source за paywall**: добавь `-site:{source-domain}` и ищи через агрегаторы
   (Bloomberg, Reuters, FT, RBC, Ведомости).
2. **Дата**: всегда добавляй `2026` или `2025 2026` в запрос, чтобы получать свежие прогнозы.
3. **Для русскоязычных источников**: используй русские термины в кавычках.
4. **Fallback при нулевых результатах**: `"{источник}" "{тема}" прогноз` без site: ограничений.
5. **Проверяй дату**: если найденная страница старше 6 месяцев от сегодня, отмечай
   «нет свежей позиции» и не включай в основную таблицу.
