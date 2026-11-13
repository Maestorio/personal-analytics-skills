# Domain overlay: Выступления tech-CEO и AI-прогнозы

**Версия**: 0.5 (от 25.04.2026)
**Базируется на**: общая методология SKILL.md + публичные track records (Musk, Altman, Amodei, Pichai, Nadella, Huang)
**Применяется**: ПОВЕРХ методологии `SKILL.md`. Не заменяет её, а конкретизирует для прогнозного контента tech-CEO и AI-аналитики.

⚠️ **Статус v0.5**: первая редакция. После 2–3 реальных аудитов (выступление Альтмана на Davos, презентация Маска по Tesla AI Day, GTC Хуанга) — расширение паттернов до v1.0.

---

## 1. Когда активировать

Активируется при аудите прогнозного контента по следующим признакам:

**Обязательно:**
- Интервью CEO в подкастах (All-In, Lex Fridman, Joe Rogan, BG2 Pod, Acquired, Dwarkesh Podcast, 20VC)
- Выступления на конференциях: Davos, GTC, OpenAI DevDay, Microsoft Build, Google I/O, Apple WWDC, Tesla AI Day, Dreamforce, Web Summit, Sequoia AI Ascent
- Personal blog posts: blog.samaltman.com, dario amodei posts, andrej karpathy писания, gwern.net, sundar pichai blog
- Earnings calls и quarterly letters c прогнозной компонентой (особенно Nvidia, Microsoft, Meta, Tesla)
- Twitter/X-треды CEO с конкретными прогнозами

**Обычно:**
- Прогнозы AGI/ASI timelines, capability emergence, scaling laws
- Прогнозы по adoption rate новых технологий (autonomous driving, robotics, quantum, BCI)
- Прогнозы по market structure: «Y компаний победят», «индустрия X исчезнет», «Z станет крупнейшим рынком»
- Прогнозы по compute/energy capex, semiconductor cycles
- Прогнозы по labor market impact AI

**НЕ активировать:**
- Чисто технические заявления без прогнозной компоненты (анонсы фич)
- Финансовые guidance без причинно-следственной модели → `domain-finance-ru.md` (если РФ) или общий
- Регуляторные battles, антитрест → частично `domain-geopolitics.md`

---

## 2. Snapshot consensus (обязательный сбор перед шкалой 2)

### 2.1 Структура tech-CEO консенсуса — четыре слоя

| Слой | Источник | Что это | Вес |
|---|---|---|---|
| **Прогнозы AI labs** | OpenAI/Anthropic/DeepMind/xAI/Meta AI roadmaps, blog posts | Insider view, но с PR-bias | средний |
| **Industry analysts** | Gartner, IDC, McKinsey AI Index, Stanford HAI | Институциональная оценка | высокий |
| **Prediction markets** | Metaculus AI Bench, Manifold, Polymarket tech | Crowd wisdom + skin-in-the-game | средний |
| **Academic forecasts** | AI Impacts surveys, Cotra biological anchors, expert surveys | Долгий горизонт, fundamental | высокий для AGI-timing |

**Ключевое правило:** для AI-прогнозов консенсус = минимум **2 из 4 слоёв сходятся**. Industry analysts (Gartner, IDC) систематически отстают на 12–18 месяцев от frontier; академики систематически опережают.

### 2.2 Источники по слоям

**AI labs / insider:**
- **OpenAI blog** ([openai.com/blog](https://openai.com/blog)) — Altman posts, model release blogs
- **Anthropic blog** ([anthropic.com/news](https://www.anthropic.com/news)) — Amodei essays («Machines of Loving Grace»)
- **DeepMind blog** ([deepmind.google/discover](https://deepmind.google/discover/blog/)) — research posts, Hassabis essays
- **Karpathy posts** ([karpathy.ai](https://karpathy.ai)) — practical capability assessments
- **Personal blogs**: blog.samaltman.com, gwern.net (deep AI analysis)

**Industry analysts:**
- **Gartner Hype Cycle + Top Strategic Predictions** ([gartner.com/en/newsroom](https://www.gartner.com/en/newsroom)) — annual в октябре
- **IDC FutureScape** ([idc.com](https://www.idc.com))
- **McKinsey State of AI** ([mckinsey.com/featured-insights](https://www.mckinsey.com/featured-insights))
- **BCG Tech Sonar**, **Bain Tech Report**
- **Stanford HAI AI Index Report** ([hai.stanford.edu/ai-index](https://hai.stanford.edu/ai-index)) — annual baseline на capabilities
- **State of AI Report** by Nathan Benaich ([stateof.ai](https://www.stateof.ai)) — annual в октябре

**Prediction markets:**
- **Metaculus AI Bench / FutureEval** ([metaculus.com/tournament](https://www.metaculus.com/tournament/futureeval/)) — c 17.02.2026 continuous AI benchmark
- **Polymarket AI category** — markets на «AGI declared by Y», «GPT-X capabilities», competitions
- **Manifold Markets** ([manifold.markets](https://manifold.markets)) — non-monetary, large AI section

**Academic / expert surveys:**
- **AI Impacts** survey ([aiimpacts.org](https://aiimpacts.org)) — 2700+ AI researchers polled (последний 2024); median P(AI outperforms humans on most tasks by 2027) = 10%
- **Open Philanthropy biological anchors** (Ajeya Cotra)
- **Epoch AI** ([epoch.ai](https://epoch.ai)) — empirical scaling law research, compute/data forecasts

### 2.3 ⚠️ Системные искажения tech-CEO консенсуса

**Bias 1: "Roadmap leakage as prophecy"**
- CEO предсказывает то, что уже **строится в его компании** в течение 12–18 месяцев. Это не прогноз о мире — это про-rata раскрытие internal roadmap. Часто маскируется под «общий прогноз индустрии»
- **Контрмера:** для каждого тезиса CEO X — проверить, что у компании X уже строится подобное. Если да → markings: «Roadmap reveal», не «forecast». Не Contrarian, не Off-market — это **Special: insider disclosure**

**Bias 2: "Self-aligned timeline overconfidence"**
- AGI timelines у CEO компаний, делающих frontier AI, систематически на 5–10 лет короче, чем у академиков и broad expert surveys. Musk 2024: AGI by 2025; Musk Dec 2025: AGI by 2026 ([Gizmodo](https://gizmodo.com/elon-musk-predicts-agi-by-2026-he-predicted-agi-by-2025-last-year-2000701007)). Altman Dec 2024: «AGI during Trump's term»; Amodei: «AGI by 2026»
- **Median expert survey 2024 vs CEO claim**: 10% probability «AI outperforms humans on most tasks by 2027» vs CEO claim 50%+
- **Контрмера:** для AGI/superintelligence timelines — всегда сравнивать с **academic surveys** + **Metaculus AI Bench**. Если разрыв > 5 лет — Split, не Consensus

**Bias 3: "Cycle-blind boom forecasting"**
- Tech-CEO во время bull cycles предсказывают continued exponential growth, не учитывая capex constraints, energy/data limits, regulatory pushback
- Hardware delays игнорируются (Nvidia Blackwell, ASML EUV, TSMC fab buildouts)
- **Контрмера:** проверять Epoch AI compute forecasts, energy projections (IEA), capex announcements реальные vs обещанные

**Bias 4: "Adoption curve compression"**
- CEO систематически занижают time-to-mass-adoption. Прогнозы вида «через 2 года 80% компаний будут использовать X» обычно реализуются за 5–7 лет
- Gartner Hype Cycle сама по себе подвержена этому bias на peak phase, но в trough phase даёт более реалистичные оценки

**Bias 5: "Survivor narrative on competitors"**
- CEO часто предсказывают конкретный исход конкурентной борьбы («индустрия консолидируется в 3 игрока, мы будем одним»). Реализованная structure часто включает 5–10 значимых players с региональными differences (China, EU)

### 2.4 Практические правила для разметки шкалы 2

| Ситуация | Правильная метка |
|---|---|
| CEO предсказывает то, что строит сам, и реальность подтвердит через 12–18 мес | **Special: Insider disclosure**, не Contrarian |
| AGI timing CEO < median expert survey на 3+ года | **Contrarian** (против академического экспертного консенсуса) |
| Adoption curve у CEO более агрессивный, чем Gartner | **Contrarian** (против industry analysts) |
| CEO согласен с Gartner + Stanford HAI + Metaculus | **Consensus** |
| Тезис о специфическом продукте/компании, нет coverage у Gartner/IDC | **Off-market** |

**Минимальная доказательность для Contrarian:** для AI capability/timing — минимум 2 academic/industry sources + 1 prediction market

---

## 3. Паттерны типичных ошибок в tech-CEO прогнозах

### 3.1 Паттерн «AGI by [near year]»

**Модель автора:**
«AGI/ASI/superintelligence будет к [2025/2026/2027/2029]»

**Почему ломается:**
- AGI — нечётко определяемое понятие; CEO часто не специфицируют, что считают «достижением». Altman: «AGI has become a very sloppy term» — прямо признал в Bloomberg interview
- Predictions с горизонтом 1–2 года практически никогда не сбываются буквально, но автор может **ретроспективно переопределить** AGI под достигнутые capabilities
- Capability emergence не линейный: scaling laws могут давать diminishing returns; data wall, energy wall, capex wall

**Известные prediction tracks:**
- **Musk**: 2014 «AI summons the demon» → 2018 ASI by 2025 → 2024 AGI by 2025 → Dec 2025 AGI by 2026 → последовательный slip
- **Altman**: 2023 «AGI within reasonable timeframe» → Dec 2024 «AGI during Trump's term» (т.е. до Jan 2029) → Jan 2025 «we know how to build AGI as we have traditionally understood it»
- **Amodei**: 2024 «Machines of Loving Grace» — предсказывал «powerful AI» к 2026
- **Hinton**: эволюция от 2018 «20–50 лет» к 2024 «5–20 лет» — meta-pattern: эксперты сжимают timelines после ChatGPT
- **Kurzweil**: 2029 (предсказание с 2005), один из самых стабильных trackers

**Чек-лист для тезиса об AGI timing:**
- [ ] Дано ли operational definition AGI?
- [ ] Совпадает ли с Metaculus median?
- [ ] Учтены ли scaling law concerns (Epoch AI)?
- [ ] Учтены ли capex constraints (energy, fabs)?
- [ ] Совпадает ли с track record самого CEO (давал ли raньше короткие timelines, которые не сбылись)?

**Кейсы для аудита:** Lex Fridman interviews 2024–2025 с Musk/Altman/Amodei/Karpathy, где AGI timing обсуждается напрямую

---

### 3.2 Паттерн «Roadmap reveal disguised as prophecy»

**Модель автора:**
«Через 6–12 месяцев [конкретная capability] будет доступна»

**Почему ломается (как методологическая ошибка аудитора, не самого CEO):**
- Аудитор может ошибочно засчитать это как Contrarian / альфу, тогда как это **insider disclosure**
- CEO компании X говорит, что capability Y будет, потому что Y строится в его команде
- Это **не прогноз о реальности**, а **PR-выжимка roadmap**

**Чек-лист:**
- [ ] Совпадает ли тезис CEO с публично известным product roadmap его компании?
- [ ] Цитирует ли CEO собственные training runs / internal benchmarks?
- [ ] Использует ли формулировки «we are training», «we expect», «we have early signs»?

Если хотя бы один пункт — да → пометить как **Special: Insider disclosure** в маркерах. Это не альфа, не персональная ошибка — это disclosure под видом прогноза. Оценивать **отдельной шкалой**: «было ли заявленное доставлено в срок?» (yes/late/no), без претензий на «провидение».

**Кейсы:** Sundar Pichai о Gemini capabilities; Zuckerberg о Llama roadmap; Huang о next-gen GPUs на GTC

---

### 3.3 Паттерн «Adoption curve в 2 года вместо 5»

**Модель автора:**
«К [2025/2026] [процент] [сегмент] будут использовать [технология]»

**Почему ломается:**
- Enterprise adoption тормозят: integration cost, change management, regulatory compliance, security review, vendor lock-in concerns
- Consumer adoption тормозят: trust, learning curve, network effects, switching costs
- Историческая база: cloud computing заняла ~10 лет до 70% enterprise penetration; smartphones — 8 лет до 80%; SaaS — 7 лет до majority

**Доменно-специфические базовые ставки:**

| Тип технологии | Time to 50% adoption (target segment) |
|---|---|
| New SaaS feature within incumbent | 1–3 года |
| New SaaS category (e.g., AI Copilot) | 3–7 лет |
| Major hardware shift (e.g., new chip arch) | 5–10 лет |
| Consumer device with new form factor | 5–12 лет |
| Regulatory-bound vertical (healthcare, finance) | +50–100% к baseline |

**Кейсы:** Gartner предсказывал в 2023 что 30% S&P companies будут использовать «xxGPT» branding к 2028 — с reality check 2026 (некоторые компании отступили от GenAI rebranding)

---

### 3.4 Паттерн «China cannot catch up under export controls»

**Модель автора:**
«Export controls на полупроводники и AI compute → Китай отстаёт на N лет»

**Почему ломается:**
- **DeepSeek v3 шок (27.01.2025)**: китайская команда продемонстрировала frontier-level capability с компьютом на порядок дешевле, чем у US labs
- Underground supply chains через Малайзию, Сингапур, ОАЭ
- Local fabrication breakthrough (SMIC 7nm, дальнейшие итерации)
- **Экспертный консенсус 2023 vs reality 2025–2026**: gap сократился с предсказанных 4–5 лет до фактических 1–2 лет

**Контр-чек:** для тезиса о China gap — обязательно проверить:
- Latest model benchmarks (DeepSeek, Qwen, Doubao, Yi)
- Hardware production capacity SMIC, Huawei
- Recent export control loopholes

---

### 3.5 Паттерн «Этот раз другой» (Cycle blindness)

**Модель автора:**
«Текущий AI/crypto/VR cycle отличается от предыдущих хайпов, потому что [reasons]»

**Почему ломается:**
- Историческая база: каждый tech cycle сопровождается «this time is different» нарративом, и каждый последующий drawdown пересматривает оценки на 50–80%
- Bubbles рассыпаются на конкретных triggers: capex glut, regulatory action, single high-profile failure (FTX 2022, Theranos 2018)
- AI-специфический риск: $500B+ data center buildouts (Stargate, Microsoft, Amazon, Meta) при не доказанной unit economics на frontier inference

**Контр-чек:**
- Сравнить заявленный capex с потенциальным revenue (rate × penetration × pricing)
- Учесть energy constraints: к 2027 многие data center проекты bottlenecked не chip availability, а grid capacity
- Проверить, есть ли в материале сценарии downside

---

## 4. Калибровка временных горизонтов в tech

### 4.1 Capability scaling

| Прогноз | Историческая база | Калибровка |
|---|---|---|
| «Capability X через 1 год» | ~30% sub bait outcomes | Снижать на 30% |
| «Capability X через 2 года» | ~50% delivered с задержкой | Принимать |
| «Capability X через 5+ лет» | ~30% delivered, 70% revised | Широкие диапазоны |

### 4.2 Compute and infrastructure

- **GPU generations**: ~18–24 месяцев (Hopper → Blackwell → Rubin); задержки на 6–12 месяцев — норма
- **Data center build**: 18–36 месяцев от announcement до operation
- **Energy supply**: 3–7 лет на новый significant grid expansion в US/EU; в Китае — 1–3 года
- **Fab buildouts (TSMC, Samsung, Intel)**: 4–6 лет

Если CEO обещает infrastructure delivery в 12 месяцев — это либо minor expansion, либо overclaim.

---

## 5. Доменный L-R sweep — реализованные хвостовые риски 2024–2026

Для аудита tech-прогнозов 2024–2026 проверить:

### 5.1 AI capability shocks
- **27.01.2025**: **DeepSeek v3 / R1 шок**. China demonstrated frontier-level reasoning at fraction of cost. US AI lab valuations пересматривались в течение нескольких недель
- **2025**: **GPT-5 release** и эра «long thinking» / o-series — переход от pure scaling к inference-time compute
- **2026**: Anthropic Opus 4.7 release, Claude 4-series как production frontier
- **17.02.2026**: Metaculus FutureEval launch — первый continuous AI benchmark

### 5.2 Hardware / infrastructure
- **2025**: Nvidia Blackwell delays и thermal issues (несколько месяцев slip)
- **2025**: Stargate $500B announcement (OpenAI + Oracle + SoftBank)
- **2026**: Energy capacity constraints начинают bite — некоторые US data center проекты задерживаются из-за grid

### 5.3 Regulatory / geopolitical
- **2025**: Trump rollback federal AI executive order (Biden); state-level AI regulations (California, NY) активизируются
- **2025**: EU AI Act compliance phases начинают bite
- **2025–2026**: расширение US export controls; одновременно — расширение caveats и обходных путей

### 5.4 Market / commercial
- **2025**: rapid commoditization mid-tier LLMs (open-weight модели догоняют GPT-3.5 уровень)
- **2025–2026**: GenAI revenue meaningfully shows up в earnings (Microsoft Azure AI, Google Cloud, Meta ads)
- **2025–2026**: первая волна disillusionment — ChatGPT psychosis cases, agent reliability issues, attempts to roll back GenAI features in some products

### 5.5 Social / labor
- **2025–2026**: первые видимые white-collar layoffs attributed to AI (legal junior associates, customer support, copywriting); evidence пока mixed
- **2025**: рост AI-skepticism в публичном дискурсе после notable failures

### 5.6 Применение L-R
Для каждого тезиса в материале пройти 5.1–5.5 и отметить:
- **Обсуждал ли автор?** (да / нет / частично)
- Если **нет** и хвост реализовался → ⚠️ L-R, **−1** к ценности
- Особенно важно для AI-CEO прогнозов: **не упомянуть DeepSeek-class шок** в материалах после янв 2025 — серьёзный L-R

---

## 6. Связь с другими доменами

- **Геополитика**: prognoses про export controls, China decoupling, AI regulation — кросс-доменные. Tech-overlay для capability/timing; geopolitics для probability of regulatory action
- **Финансы**: тезис «купить Nvidia / OpenAI valuation justified at $X» — финансовый. Этот overlay для underlying capability assumption; finance overlay для valuation modeling
- **Healthcare AI / biotech AI**: специфический поддомен. В этом overlay — общие capability вопросы; specific clinical trial timelines, FDA pathways — отдельный (TBD в v1.0)

---

## 7. История версий

- **v0.5 (25.04.2026)**: первая редакция. 4-слойная структура консенсуса, 5 паттернов, calibration tables, L-R sweep 2024–2026
- **Планируется v1.0** (после 2–3 реальных аудитов):
  - Развёрнутые профили: Altman, Amodei, Musk, Pichai, Huang с накопленной prediction history
  - Paper trail для верификации старых заявлений (archive.org, archived tweets)
  - Расширение паттернов до 8–10
  - Healthcare AI / robotics / quantum sub-overlays
  - Шаблоны memory/export для tech CEOs

---

## 8. Связь с другими файлами скилла

- **SKILL.md** — общая методология
- **EXAMPLES.md** — общие примеры; tech-CEO кейсы добавятся в v1.0
- **references/consensus-sources.md** — общая карта; этот файл добавляет 4-слойность
- **references/output-templates.md** — общие шаблоны; в Light-таблице для tech-CEO добавлять колонку «Special: Insider?» для маркера roadmap leakage
