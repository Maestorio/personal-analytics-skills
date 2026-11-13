# Domain overlay: Геополитика

**Версия**: 0.5 (от 25.04.2026)
**Базируется на**: общая методология SKILL.md + публичные ретроспективы Eurasia Group / GZero
**Применяется**: ПОВЕРХ методологии `SKILL.md`. Не заменяет её, а конкретизирует для геополитического домена.

⚠️ **Статус v0.5**: первая редакция. После 2–3 реальных аудитов (Eurasia Group Top Risks, CFR/Brookings отчётов, Telegram-каналов с геополитической компонентой) — расширение паттернов и L-R коллекции до v1.0.

---

## 1. Когда активировать

Активируется при аудите прогнозного контента по следующим признакам:

**Обязательно:**
- Annual outlook отчёты think tanks: Eurasia Group Top Risks, CFR Preventive Priorities Survey, Brookings Big Ideas, Carnegie Endowment forecasts, Chatham House Annual Risk Outlook, IISS Strategic Survey, RAND foresight
- Геополитические колонки в Foreign Affairs, Foreign Policy, Atlantic Council, ECFR
- Telegram-каналы с прогнозной геополитической компонентой
- Интервью/выступления отставных дипломатов, разведчиков, военных стратегов с прогнозами
- Архивы постов «инсайдеров» (бывших чиновников, спецпредставителей)

**Обычно:**
- Прогнозы по конфликтам (СВО, Ближний Восток, Тайвань), выборам, sanctions, регионам нестабильности
- Прогнозы по правительственным переходам (преемственность, перевороты)
- Прогнозы по торговым войнам и tariff policy

**НЕ активировать:**
- Чисто финансовые прогнозы по эмитентам, даже если они на санкционной повестке → `domain-finance-ru.md`
- Tech-прогнозы CEO о regulatory fight (это смесь tech + полит) → `domain-tech-ceo.md` с под-tag «regulatory»
- Спортивные/развлекательные прогнозы на Polymarket/Kalshi → не наш домен

---

## 2. Snapshot consensus (обязательный сбор перед шкалой 2)

### 2.1 Структура геополитического консенсуса — он трёхслойный

В отличие от финансов (где консенсус =  снапшот 5–6 sell-side домов), геополитический консенсус **разделён на три слоя**, и они часто расходятся:

| Слой | Источник | Что это | Вес в консенсусе |
|---|---|---|---|
| **Prediction markets** | Polymarket, Kalshi (CFTC-regulated), Metaculus | Real-money + crowd wisdom | средний |
| **Экспертный консенсус** | think tanks, академики, отставные дипломаты, IC analysts | Доменная экспертиза, медленнее реагирует | высокий для long-term |
| **Bond/equity pricing** | Goldman Sachs Top of Mind, JPM, Morgan Stanley геополит. секции | Имплицитные probabilities из спредов и волатильности | низкий — это след, не предикция |

**Ключевое правило:** геополитический консенсус = **где минимум 2 из 3 слоёв сходятся**. Если все три расходятся (≥20 п.п. между ними) — это **Split**, и автор тезиса не может быть «Consensus» автоматически, на каком бы слое ни было совпадение.

### 2.2 Список источников по слоям

**Prediction markets:**
- **Polymarket** ([polymarket.com/geopolitics](https://polymarket.com/geopolitics)) — крупнейший, $3.2B+ cumulative volume к 2026. Subcategory: Macro Geopolitics, Iran, Ukraine, Middle East, Russia. Точность 73% overall, 81% на binary political outcomes ([Fensory analysis 2026](https://fensory.com/intelligence/predict/polymarket-accuracy-analysis-track-record-2026))
- **Kalshi** ([kalshi.com](https://kalshi.com)) — единственная CFTC-regulated в США, 900+ active contracts
- **Metaculus** ([metaculus.com](https://metaculus.com)) — non-monetary, исследовательский. 80,000+ forecasts. Superforecasters достигают 79% accuracy. С 17.02.2026 — FutureEval benchmark для AI vs human

**Экспертный консенсус (think tanks, открытые публикации):**
- **Eurasia Group** Top Risks ([eurasiagroup.net/top-risks](https://www.eurasiagroup.net/issues/top-risks-2026)) — публикуется в начале января
- **CFR** Preventive Priorities Survey ([cfr.org/preventive-priorities-survey](https://www.cfr.org/preventive-priorities-survey)) — annual, ranks conflicts by US interest + likelihood
- **Brookings Big Ideas** ([brookings.edu/big-ideas](https://www.brookings.edu/big-ideas)) — annual policy forecasts
- **Carnegie Endowment** ([carnegieendowment.org](https://carnegieendowment.org)) — региональная экспертиза, особенно сильны по постсоветскому пространству, Ближнему Востоку
- **Chatham House** ([chathamhouse.org](https://www.chathamhouse.org)) — UK perspective, регулярные expert surveys
- **IISS Strategic Survey + Military Balance** ([iiss.org](https://www.iiss.org)) — оборонная аналитика
- **ECFR** ([ecfr.eu](https://ecfr.eu)) — European Council on Foreign Relations, EU-perspective
- **Atlantic Council** ([atlanticcouncil.org](https://www.atlanticcouncil.org))
- **RAND foresight** ([rand.org/research](https://www.rand.org/research.html))
- **Bruegel** ([bruegel.org](https://www.bruegel.org)) — для economic + geopolit. crossover

**Bond/equity pricing (как proxy):**
- **Goldman Sachs Top of Mind** ([goldmansachs.com/insights/top-of-mind](https://www.goldmansachs.com/insights/top-of-mind)) — содержит и эксперта, и trader-side секции; цитировать обе
- **JPM Eye on the Market** Michael Cembalest
- **Morgan Stanley** Cross-Asset
- **BlackRock Investment Institute Outlook** ([blackrock.com/corporate/insights](https://www.blackrock.com/corporate/insights))

### 2.3 Где брать архивный snapshot

- **Polymarket API + Wayback Machine** — для исторических цен на конкретную дату
- **GZero «Top Risks Reviewed»** ([gzeromedia.com](https://www.gzeromedia.com)) — Eurasia Group в декабре каждого года публикует ретроспективу собственного январского прогноза, с явными вердиктами «hit/miss/partial»
- **Foreign Policy** «Forecast 2024/2025» — annual collection
- **Metaculus track record на конкретного forecaster или questions tag** — публичные данные

### 2.4 ⚠️ Системные искажения геополитического консенсуса

**Bias 1: "Status quo plus drift"**
- Экспертный консенсус систематически недооценивает резкие переходы (revolutions, sudden coups, war initiations). Pattern detected: Eurasia Group в Top Risks 2024 включала «Partitioned Ukraine» (#3) и «Middle East on the brink» (#2), но **не предсказала** распад «оси сопротивления» Ирана к концу 2024 (Hezbollah обескровлен, Асад пал 8.12.2024). [GZero retrospective](https://www.gzeromedia.com/news/analysis/top-risks-of-2025-reviewed)
- Пример: Большинство think tanks оценивали вероятность падения Асада в 2024 как < 15%; реальное событие 8.12.2024 было «черным лебедем» для большинства, кроме узких специалистов

**Bias 2: "Western mirror imaging"**
- Применение моделей рационального выбора западного типа к авторитарным режимам с другими incentive structures. Особенно ярко проявилось в прогнозах Russia-Ukraine 2022 (большинство US/EU экспертов до января 2022 оценивали полномасштабное вторжение как < 30%)

**Bias 3: "Bond pricing as truth"**
- Goldman Sachs трейдинговая секция систематически переоценивает probability «soft» events (быстрые переговоры, сделки), потому что trader incentives — низкая волатильность; экспертная секция того же отчёта часто противоречит. Пример: GS Top of Mind 13.03.2025 — bond pricing 70% probability cease-fire, экспертная секция (Thomas Graham) — «No, quick end is not probable». **Цитировать обе секции, помечать как Split**

**Bias 4: "Recency overweight в prediction markets"**
- Polymarket markets с горизонтом < 30 дней реагируют на новостной фон сильнее, чем оправдано. На горизонтах > 90 дней Polymarket ближе к экспертным прогнозам

### 2.5 Практические правила для разметки шкалы 2

| Ситуация | Правильная метка |
|---|---|
| Экспертный консенсус и markets сходятся (≤15 п.п.), автор согласен | **Consensus** |
| Все три слоя сходятся, автор against | **Contrarian** (истинная) |
| Markets говорят X, эксперты — Y, расхождение ≥20 п.п. | **Split** (даже если автор совпал с одним из слоёв) |
| Регион/тема вообще не обсуждается ни в markets, ни в expert publications | **Off-market** |
| Snapshot не получен | **❓** |

**Минимальная доказательность для Contrarian:** для любого политического тезиса с горизонтом > 30 дней — надо найти snapshot минимум 2 think tanks + 1 prediction market. Иначе ❓.

---

## 3. Паттерны типичных ошибок в геополитических прогнозах

### 3.1 Паттерн «Линейная экстраполяция переговорного трека»

**Модель автора:**
«Раунд переговоров X состоялся → значит, идём к сделке Y → значит, к концу периода будет cease-fire / соглашение / урегулирование»

**Почему ломается:**
- Переговоры — циклический процесс с откатами, а не линейная прогрессия. Каждый «раунд переговоров» имеет ~20–30% probability коллапса, а не сходимости
- Игнорирование veto players: один внутренний игрок (radical wing, military, parliament) может откатить любой публичный прогресс
- Пример (СВО 2025): Аляска-саммит Путин–Трамп 15.08.2025 произошёл, но соглашения не было. Pasha-перемирие 11–12.04.2026 сорвано через 32 часа. На 24.04.2026 — переговоры в Абу-Даби/Женеве заблокированы территориальным вопросом Донбасса
- Polymarket «Russia x Ukraine ceasefire by 31.03.2026» — 96% No с февраля 2026 ([Polymarket](https://polymarket.com/predictions/macro-geopolitics))

**Чек-лист для тезиса о «прогрессе переговоров»:**
- [ ] Идентифицированы veto players на обеих сторонах?
- [ ] Учтены прошлые откаты этого трека?
- [ ] Есть ли явное условие активации (что должно сорваться)?
- [ ] Совпадает ли тезис с Polymarket/Metaculus или нет?

**Кейсы:** Israel-Hamas 2024–2025, Russia-Ukraine 2022–2026, Iran nuclear deal 2015→2018→2023→ослабление к 2025

---

### 3.2 Паттерн «Ось рассыпается / страна падает»

**Модель автора:**
«Режим X на грани / экономика Y коллапсирует / правительство Z падёт в течение N месяцев»

**Почему ломается:**
- **Authoritarian resilience underestimation**: централизованные режимы со state capacity и силовыми резервами держатся существенно дольше прогнозов либеральных аналитиков (paradigm shift в политологии после 2010-х)
- **Confounding sample**: Сирия 2024 (пал) ≠ Иран 2024 (не пал) ≠ Венесуэла 2024 (не пал). Нельзя обобщать
- **Sanctions coping**: режимы под санкциями развивают alternative trade networks (Россия–Китай–Иран–КНДР), это занимает 2–3 года, далее реальный экономический ущерб резко падает
- Пример: к 2026 «оси rogue» (Eurasia Group термин) усиливается, а не распадается, несмотря на 4 года прогнозов «вот-вот сломается»

**Базовые ставки (priors) для калибровки:**
- Authoritarian regime falls within next 12 months in normal circumstances: ~3% (исторический base rate)
- В период кризиса: до 15%
- При наличии активного military conflict внутри: 25–40%
- При иностранной интервенции с air superiority: 50–70%

**Если автор закладывает > 20% probability падения режима без второго или третьего из условий выше — это overclaim**

**Кейсы:** Maduro forecasts 2017–2026 (так и не упал), Putin-after-2022 forecasts, Khamenei health-based forecasts

---

### 3.3 Паттерн «Bond pricing как первоисточник консенсуса»

**Модель автора:**
«Polymarket даёт 70% probability X → значит, надёжный консенсус → ставлю по нему»

**Почему ломается:**
- Polymarket/Kalshi reflect retail trader sentiment + media narrative, а не экспертную оценку
- **Liquidity + manipulation risk**: markets под $1M open interest подвержены price distortion ([Fensory analysis 2026](https://fensory.com/intelligence/predict/polymarket-accuracy-analysis-track-record-2026))
- **Markets reflect base-rate fallacy на closed political systems**: для РФ/СВО expert consensus исторически ближе к фактическому исходу, чем bond pricing
- Goldman Sachs параллельно публикует expert + market pricing → автор может цитировать только market и пропустить экспертный взгляд

**Правило**: для геополитических тезисов всегда проверять **расхождение между слоями**. Если markets vs experts расходятся ≥20 п.п. — это Split, не Consensus.

**Кейс:** аналог из РФ-finance: GS Top of Mind 13.03.2025, тезис T1 у Invest Era (см. `domain-finance-ru.md` §3.3) — прямой геополитический парафраз этого паттерна

---

### 3.4 Паттерн «Hard counterfactual: что сделают США/Россия/Китай»

**Модель автора:**
«США point Y будут делать Z → следствие W»

**Почему ломается:**
- **Bureaucratic inertia underestimation**: даже при политической воле принятие нового policy в США занимает 3–9 месяцев (interagency process, Hill consultations). Лавров 11.04.2025 публично предложил снять санкции с Аэрофлота — США не ответили в течение года, на 24.04.2026 санкции в силе
- **Domestic political constraints**: новая Администрация имеет ограниченный political capital; major foreign policy moves конкурируют с domestic priorities
- **Personnel turnover ignored**: ключевой driver policy — кто на конкретной позиции; смена ответственного лица перенастраивает весь трек

**Чек-лист для тезиса «государство X сделает Y»:**
- [ ] Идентифицирован конкретный actor (агентство, должность)?
- [ ] Прописан bureaucratic timeline (в месяцах)?
- [ ] Учтена domestic альтернатива (что может перебить приоритет)?
- [ ] Учтён personnel risk (кто ответственный, могут ли его сменить)?

---

### 3.5 Паттерн «Один регион — одна модель»

**Модель автора:**
«Все события на Ближнем Востоке развиваются по логике X»

**Почему ломается:**
- Internal heterogeneity: Иран ≠ Саудовская Аравия ≠ Израиль ≠ Турция. Применение одной модели приводит к over-generalization
- **Conflict spillover overestimation**: эксперты часто прогнозируют, что конфликт A приведёт к региональной escalation. Историческая base rate для regional spillover в Ближний Восток после 2000 года: ~20–30%, а не 50%+

**Кейсы:** «Iran will retaliate massively after X» — после убийства Сулеймани (2020), после Hamas attack (2023), после strikes 2024 → реакция была сдержаннее прогнозов; «12-day war» Israel–Iran 2025 ([Eurasia Group hits & misses](https://www.gzeromedia.com/news/analysis/top-risks-of-2025-reviewed)) — это исключение, не правило

---

## 4. Калибровка временных горизонтов

### 4.1 Конфликтологическая база

| Тип события | Median duration / Base rate |
|---|---|
| Cease-fire negotiations to actual ceasefire | 8–18 месяцев |
| Cease-fire holding > 6 месяцев | ~40% (зависит от региона) |
| Authoritarian regime collapse w/o military intervention | 3–8 лет от первых признаков |
| Major sanctions package → measurable economic impact | 12–24 месяцев |
| Sanctions removal → market normalization | 6–18 месяцев (Turkey 2018, Иран 2015 partial) |
| New administration → first major foreign policy action | 4–9 месяцев |
| Coup → constitutional return | 3–12 лет (Sahel показывает > 5 лет) |
| Election → policy implementation | 6–18 месяцев |

**Применение**: если автор закладывает срок существенно короче медианы — отметить как L-C (overconfidence в timing); если существенно длиннее — overcautious.

### 4.2 «Календарные» иллюзии

Автор геополитических прогнозов часто привязывает события к **формальным датам** (сменам администраций, саммитам, годовщинам), хотя политические события **редко синхронизируются с календарём**. Правило: если тезис содержит конкретную дату как ожидаемый момент события (не дедлайн) — снижать его probability на 30–50% от заявленной.

---

## 5. Доменный L-R sweep — реализованные хвостовые риски 2024–2026

Для аудита прогнозов с горизонтом 2024–2026 проверить, обсуждал ли автор следующие **реализовавшиеся** хвосты:

### 5.1 Ближний Восток
- **08.10.2023→2024**: разгром «оси сопротивления» Ирана. Hezbollah обескровлен (сентябрь–октябрь 2024). Iran nuclear program оголён до threshold state status
- **08.12.2024**: падение режима Асада в Сирии (HTS-led offensive). Большинство think tanks предсказывало < 15% probability на конец 2023
- **Июнь 2025**: 12-day war Israel–Iran (предсказан Eurasia Group Top Risks 2025 как один из top hits — [GZero review](https://www.gzeromedia.com/news/analysis/top-risks-of-2025-reviewed))
- **2026**: продолжающееся напряжение US–Iran (cease-fire не extended, Polymarket даёт low probability на permanent peace deal)

### 5.2 Россия–Украина
- **13.03.2025**: Путин в Москве отклонил полное 30-дневное прекращение огня; узкий мораторий на удары по энергоинфраструктуре получен 18.03.2025
- **15.08.2025**: саммит Трамп–Путин на Аляске без прорыва
- **22.10.2025**: новые санкции США против Роснефти и Лукойла (Трамп). Основная масса прогнозов 2024 ставила на снятие санкций, не на новые
- **11–12.04.2026**: пасхальное 32-часовое перемирие сорвано
- **24.04.2026**: переговоры в Абу-Даби/Женеве заблокированы Донбассом

### 5.3 США
- **20.01.2025**: инаугурация Трампа. Реализация tariff policy быстрее ожиданий: Китай +10% уже в феврале, ответные меры
- **2025**: erosion of independent checks (DOJ purges, IG firings) — предсказано Eurasia Group Top Risks 2025 #2 «Rule of Don»
- **2026**: midterm elections cycle активирует political volatility

### 5.4 Латинская Америка
- **2025–2026**: Венесуэла — Мадуро удержался; Polymarket даёт 66% probability Delcy Rodriguez как лидер на конец 2026 ([Polymarket geopolitics](https://polymarket.com/geopolitics))
- **Мексика**: Sheinbaum tested by Trump tariffs (Top Risks 2025 #10 «Mexican standoff» — частичный hit)

### 5.5 Азия–Тихий океан
- **Тайвань**: пролив сохраняет risk premium, но full invasion не материализовалась
- **КНДР–Россия**: углубление военного сотрудничества (войска на Украине с октября 2024)

### 5.6 Технология как геополитика
- **27.01.2025**: DeepSeek v3 шок — China продемонстрировала AI capability при export controls. Большинство think tanks 2024 не закладывали такой scenario до 2026
- **AI export controls**: Trump 2025 расширил, но и обходные каналы (через Малайзию, Сингапур) масштабировались

### 5.7 Правило применения
Для каждой темы пройти 5.1–5.6 и отметить:
- **Обсуждал ли автор?** (да / нет / частично)
- Если **нет** и хвост реализовался → ⚠️ L-R, **−1** к ценности
- Если **да**, но автор оценивал probability существенно ниже факта (например, < 10% при post-hoc базовой ставке 30%+) → L-C, не L-R

---

## 6. Связь с другими доменами

- **Финансы**: тезис типа «снятие санкций → рост акций санкционных компаний» одновременно геополитический (вероятность снятия) и финансовый (corporate impact). Применять **оба overlay** последовательно. Геополитический слой — для probability события; финансовый — для magnitude последствий
- **Tech-CEO**: AI predictions с regulatory компонентой (export controls, AI Act, China decoupling) — частично ложатся в этот overlay (geopolitical), частично в `domain-tech-ceo.md`. Правило: если основной тезис о rate of technological change → tech-ceo; если о government action → geopolitics

---

## 7. История версий

- **v0.5 (25.04.2026)**: первая редакция. Источники для snapshot, 5 паттернов ошибок, временные базовые ставки, L-R sweep 2024–2026
- **Планируется v1.0** (после 2–3 реальных аудитов):
  - Развёрнутые профили типовых источников: Eurasia Group, CFR, Carnegie с накопленной статистикой
  - Расширение коллекции паттернов до 8–10
  - Шаблоны memory/export специфически для геополитических think tanks
  - Доменный мини-словарь терминов (G-Zero, decoupling, axis of upheaval и т.д.)

---

## 8. Связь с другими файлами скилла

- **SKILL.md** — общая методология, не переопределяется
- **EXAMPLES.md** — общие примеры; геополитические кейсы добавятся в v1.0
- **references/consensus-sources.md** — общая карта источников; этот файл добавляет геополитическую трёхслойность
- **references/output-templates.md** — общие шаблоны; в Light-таблице для геополитики колонка «Консенсус» заполняется как «Polymarket/Эксперты/Bond» с явным split-маркером, если расхождение
