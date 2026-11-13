# Perspective Maps — глобальный справочник

Карты лагерей (perspective maps) для тем с поляризованными позициями.
Используется на **Шаге 1.5** скилла `forecast-confidence-applier`:

1. Сначала проверить, есть ли карта для темы запроса в этом файле (по триггерам ниже).
2. Если есть — взять готовую карту, веб-поиск вести по носителям из неё.
3. Если темы нет — Full-auto алгоритм строит карту по знаниям, после успешной отработки
   рекомендуется добавить карту сюда (это growing reference).

---

## Принципы

- **Лагерь = позиция по вопросу, а не организация**. Одна организация может в разных
  вопросах быть в разных лагерях (напр., Carnegie до 2014 vs Carnegie 2024+).
- **Уровни**: `Dominant` / `Significant` / `Minority` / `Fringe`. Fringe не включаем.
- **Структура одной карты**: core claim (1 строка) + типичные носители (3–7 институций) + уровень.
- **Symmetry check**: если запрос содержит асимметричную атрибуцию ответственности
  (формулировки «будет ли X атаковать Y», «приведёт ли политика X к кризису» и т.п.),
  карта обязана содержать как минимум один лагерь с обратной атрибуцией. Если такого
  лагеря нет в institutional discourse — фиксируем явно: *«контр-лагерь институционально
  не представлен»*.
- **Trust weights не задаются в этом файле**. Веса берутся ТОЛЬКО из INDEX.md по
  правилам `trust-application.md`. Здесь — только структура лагерей и их носители.
- **Расширение файла**: при появлении новой темы добавляй раздел по шаблону §6.

---

## Триггер-таблица (ключевые слова в запросе → раздел)

| Триггер | Раздел |
|---|---|
| Иран, Israel-Iran, Hormuz, IRGC, ядерная программа Ирана | §1.1 |
| US-Europe, тарифы Трампа на ЕС, NATO funding, Greenland, IRA vs CBAM | §1.2 |
| Russia-Europe war, NATO-Russia, hybrid escalation, накопление вооружений | §1.3 |
| US-China strategic competition, decoupling, chips, Тайвань-стратегический | §1.4 |
| КНДР, North Korea, Kim Jong Un, поставки в РФ | §1.5 |
| Taiwan kinetic, PLA blockade, semiconductors war (kinetic scenario) | §1.6 |
| Houthis, Красное море, Bab-el-Mandeb, морская логистика | §1.7 |
| ключевая ставка ЦБ РФ, key rate Russia, ДКП | §2.1 |
| инфляция РФ, проинфляционные риски | §2.2 |
| возврат западных компаний в РФ, M&A после санкций | §3.1 |
| US recession 2026/2027, hard/soft landing | §4.1 |
| AGI timeline, когда AGI, ASI прогнозы | §5.1 |

---

## §1. Geopolitics

### §1.1 США/Израиль — Иран

**Триггеры**: ядерная программа Ирана, удары по Натанзу/Фордо, IRGC, Hormuz blockade,
US–Iran direct conflict, JCPOA-2.

| Лагерь | Уровень | Core claim | Типичные носители |
|---|---|---|---|
| Pro-Israel hawkish | Dominant в US/IL | Иран — экзистенциальная угроза, окно для удара закрывается | FDD, Hudson Institute, JINSA, INSS Tel Aviv, WINEP |
| US realist / restraint | Significant | Военные удары контрпродуктивны, нужен containment или новый JCPOA | Quincy Institute (Trita Parsi), International Crisis Group (Ali Vaez), Defense Priorities, Stimson Center |
| Iran-side institutional | Dominant в IR | Программа — легитимная самооборона; ответ будет асимметричным | Tehran Times (gov-aligned), IPIS Tehran, Mehr News, Kayhan |
| EU multilateralist | Significant | JCPOA — единственный non-military выход; E3 как медиаторы | ECFR Middle East (Geranmayeh), IISS London, Chatham House MENA |
| Russia/China view on Iran | Minority | Иран — partner of multipolar order; sanctions = geopolitical weaponization | Valdai (Лукьянов), РСМД, Carnegie China, SIIS Shanghai |

**Symmetry check**: ✓ обе стороны атрибуции + 2 промежуточных лагеря.

---

### §1.2 США — Европа (фрикция союзников)

**Триггеры**: тарифы Трампа на ЕС, NATO funding 2-5%, Greenland, выход из Парижа,
IRA vs CBAM/Green Deal, AI-регулирование (EU AI Act vs US laissez-faire).

Карта **несимметрична по конструкции** — это не «противостояние», а напряжение
внутри альянса. Лагеря разделены по видению будущего трансатлантизма.

| Лагерь | Уровень | Core claim | Типичные носители |
|---|---|---|---|
| US trade nationalist / America First | Dominant в Trump-orbit | ЕС — free-rider; reciprocal tariffs + ультиматум по обороне | Heritage Foundation (Project 2025), AEI (Hal Brands), Hudson Institute, America First Policy Institute |
| US Atlanticist establishment | Significant, под давлением | Трансатлантизм критичен для US интересов; разрыв = win для КНР/РФ | CSIS, Atlantic Council, Brookings, CFR, German Marshall Fund |
| EU strategic autonomy | Dominant в Brussels/Paris | Уход США → европейский суверенитет в обороне, технологиях, торговле | ECFR (Mark Leonard), Bruegel, Carnegie Europe, IFRI Paris, CER London, Egmont Brussels |
| EU Atlanticist (frontline CEE) | Significant | Без US — Европа не выживет; компромисс с MAGA любой ценой | OSW Warsaw, FOI Stockholm, ICDS Tallinn, RUSI London, Chatham House |
| Realist crossover | Minority | США корректно пересматривают, но методы Трампа разрушительны | Quincy Institute (на US стороне), MERICS Berlin (на EU стороне) |

**Symmetry check**: ✓ внутренние лагеря с обеих сторон Атлантики.

---

### §1.3 Европа — Россия

**Триггеры**: будет ли война НАТО-РФ к 2030, накопление вооружений в Европе,
hybrid escalation, Калининград, Suwałki gap, кибератаки/саботаж.

| Лагерь | Уровень | Core claim | Типичные носители |
|---|---|---|---|
| Atlantic mainstream | Dominant | РФ — эскалирующий агрессор, Европа должна re-arm и сдерживать | Stratfor, Chatham House, ECFR, Atlantic Council, CSIS, RAND |
| Frontline coalition | Dominant в CEE | Война неизбежна в горизонте 5-10 лет, инвестировать в оборону максимально | OSW Warsaw, FOI Sweden, ICDS Tallinn, RUSI, FIIA Helsinki, BSU Vilnius |
| US/EU realist | Significant | Расширение НАТО — провокация; Европа сама эскалирует через прокси | Quincy Institute (Beebe, Mearsheimer non-resident), Defense Priorities, академики Mearsheimer/Walt, Jeffrey Sachs |
| Russia-side post-2024 | Dominant в РФ | Запад первым перешёл в режим войны, Россия отвечает асимметрично | РСМД (Тренин 2024+), Valdai (Лукьянов), СВОП, ВШЭ ФМЭиМП, MGIMO |
| Global South / non-aligned | Minority | Конфликт — внутрирегиональный, Глобальному Югу выгоден multi-polar исход | Carnegie China, ORF Delhi, IPS São Paulo, ISS Pretoria |

**Symmetry check**: ✓ обе стороны атрибуции (атакует РФ / провоцирует Запад) + neutral.

---

### §1.4 США — Китай (стратегическое противостояние)

**Триггеры**: US-China decoupling, chip war, тарифы, Тайвань-стратегический,
TikTok-баны, технологический разрыв, инвестиционные ограничения.

| Лагерь | Уровень | Core claim | Типичные носители |
|---|---|---|---|
| US hawkish / decoupling | Dominant в Washington | КНР — главная угроза порядку; full decoupling в критических секторах | Hudson Institute (China Center), AEI, CSIS China Power Project, FDD, Atlantic Council Scowcroft |
| US engagement / managed competition | Significant | Decoupling нереалистичен; targeted de-risking + сохранение каналов | Brookings (Ryan Hass, Patricia Kim), Carnegie China (Paul Haenle), Quincy Institute, Asia Society Policy Institute |
| China-side institutional | Dominant в CN | США пытаются сдержать законное развитие; КНР готова к long game | CIIS Beijing, SIIS Shanghai, Tsinghua Strategic and Security Studies (Yan Xuetong), Renmin University IIS, Global Times (state mirror) |
| EU pragmatist | Significant | De-risking ≠ decoupling; ЕС нужен независимый трек с КНР | MERICS Berlin (decoupling-sceptic), DGAP, IFRI Asia, Bruegel, Clingendael The Hague |
| Asia regional view | Significant | Hedging вместо выбора стороны; экономика с КНР, безопасность с США | ISEAS Singapore, Lowy Institute Sydney, ORF Delhi, Asan Institute Seoul |

**Symmetry check**: ✓ обе стороны + EU + регион.

---

### §1.5 КНДР — Южная Корея/США

**Триггеры**: КНДР, поставки в РФ, северокорейские войска, ядерные тесты,
denuclearization, провокации DMZ.

| Лагерь | Уровень | Core claim | Типичные носители |
|---|---|---|---|
| US/SK hawkish | Dominant в Seoul/DC | КНДР — растущая угроза, нужно sanctions enforcement + extended deterrence | KIDA Seoul, Sejong Institute, Asan Institute, FDD North Korea Program, Heritage |
| US realist / engagement | Significant | Sanctions провалились; нужен arms control дипломатический трек | Stimson Center (Daryl Kimball, Kelsey Davenport), Quincy Institute, 38 North (Jenny Town) |
| КНДР-side institutional | Dominant в Пхеньяне | Ядерное оружие — гарантия выживания; альянс с РФ/КНР институционален | KCNA, Rodong Sinmun (state propaganda — читать как mirror) |
| Russia/China view on DPRK | Significant | КНДР — партнёр в anti-US блоке; sanctions нужно обходить | РСМД (Кистанов), Valdai, Carnegie China, SIIS |
| South Korea progressive | Minority | Sunshine Policy 2.0; диалог + межкорейский экономический трек | Korea Institute for National Unification (KINU dovish faction), Hankyoreh, Kyunghyang |

**Symmetry check**: ✓. Для запросов «КНДР усиливает РФ» — учитывать, что лагерь
«Russia/China view on DPRK» описывает РФ-выгоду открыто, тогда как «US/SK hawkish» —
как угрозу.

---

### §1.6 Тайвань (kinetic scenario)

**Триггеры**: PLA blockade, China invasion Taiwan timeline, semiconductors war,
TSMC fallout, Davidson window 2027.

Отличается от §1.4 тем, что фокус — на конкретный сценарий военного столкновения,
а не общем стратегическом противостоянии.

| Лагерь | Уровень | Core claim | Типичные носители |
|---|---|---|---|
| Imminent threat (Davidson school) | Dominant в US Pentagon | Окно 2027–2030; нужна максимальная deterrence + arming Taiwan | CSIS (Bonny Lin), CNAS, Hudson, Atlantic Council, RAND |
| Slow squeeze / blockade | Significant | КНР предпочтёт quarantine/grey-zone, не invasion; долгая компрессия | Brookings (Ryan Hass), Carnegie China, Asia Society Policy Institute, ORF |
| Deterrence works | Significant | Цена для КНР запредельна; статус-кво устойчив 10+ лет | Quincy Institute, Stimson, German Marshall Fund Indo-Pacific |
| China-side official | Dominant в CN | Воссоединение неизбежно, предпочтительно мирно; провокации DPP блокируют | CIIS, SIIS, Renmin University, Tsinghua, Global Times |
| Taiwan domestic | Dominant в TW | DPP: defend democracy; KMT: cross-strait dialog ≠ surrender | Institute for National Defense and Security Research (INDSR), Prospect Foundation, Cross-Strait Policy Association |

**Symmetry check**: ✓ обе стороны пролива + варианты сценария.

---

### §1.7 Хуситы / Красное море

**Триггеры**: Houthis, Bab-el-Mandeb, Suez disruption, Red Sea attacks,
прокси-фронт Иран-Запад в Йемене.

| Лагерь | Уровень | Core claim | Типичные носители |
|---|---|---|---|
| US/UK military response | Dominant в Washington/London | Operation Prosperity Guardian — необходимая freedom-of-navigation миссия | CSIS, RUSI Maritime, Atlantic Council MENA, FDD |
| Regional realist / Saudi-aligned | Significant | Yemen civil war — корень; нужна Saudi-Houthi сделка, US удары контрпродуктивны | International Crisis Group (Yemen team), Sanaa Center, Chatham House MENA |
| Iran-axis view | Dominant в IR/Houthi | Удары — солидарность с Газой; freedom-of-navigation = legitimization Israel | Tehran Times, Ansar Allah communiques, Al-Manar (Hezbollah-aligned) |
| Shipping industry pragmatist | Significant | Cost of disruption приемлем; rerouting через Cape работает long-term | Lloyd's List, BIMCO, Drewry Shipping Consultants, ACAPS |
| China-pragmatic | Minority | КНР не intervenes; экономия на rerouting + leverage над Ираном | Carnegie China, SIIS, Belt and Road research |

**Symmetry check**: ✓.

---

### TBD geopolitics (заготовки для будущего наполнения)

Темы с известным влиянием на РФ, для которых карты ещё не построены — добавлять
по запросу. Кратко: вектор раскола.

- **Армения — Азербайджан**: pro-Yerevan vs pro-Baku vs Russian retreat thesis vs Turkey-Azerbaijan strategic axis.
- **Молдова — Приднестровье**: pro-EU integration vs pro-Russia federalization vs frozen-conflict pragmatism.
- **Сербия — Косово / Балканы**: pro-Belgrade balancing vs Atlantic full integration vs Russia residual presence.
- **Грузия (внутренний транзит)**: «Грузинская мечта» pro-RU narrative vs European Future protests vs US-driven leverage.
- **Беларусь (после Лукашенко)**: succession-stable vs внутренний разлом vs Russian formal absorption.
- **Сахель + Africa Corps**: French retreat narrative vs Russia anti-colonial pitch vs Western alarm vs местная агентность.
- **Венесуэла / US-Venezuela**: regime-change school vs sanctions-relief pragmatism vs Maduro-survives consensus.
- **Япония — Курилы / Хоккайдо**: ремилитаризация Японии + союз с США vs Russian frozen status vs Korea/China implications.
- **Турция — Греция / E.Med**: NATO-internal balancing vs Cyprus dispute vs energy resources vs Erdogan post-strategic.

---

## §2. Ru-macro

### §2.1 Ключевая ставка ЦБ РФ

**Триггеры**: ключевая ставка, key rate Russia, ДКП ЦБ, заседание совета директоров ЦБ,
прогноз ставки.

| Лагерь | Уровень | Core claim | Типичные носители |
|---|---|---|---|
| Монетаристы / ЦБ-апологеты | Dominant в институциональном дискурсе | Ставка = главный анти-инфляционный инструмент, держим долго | SberCIB Macro (Хаспеков), РЭШ (Гурвич), ВЭБ.РФ (Клепач отчасти), Альфа-Капитал (Вьюгин-orbit) |
| Структуралисты | Significant | Высокая ставка убивает инвестиции; инфляция в РФ — издержная и санкционная | Институт народнохозяйственного прогнозирования РАН (Широв), ЦМАКП (Белоусов А., Сальников), Деловая Россия |
| ВПК-реалисты / бюджетные приматисты | Significant | Ставка нерелевантна в военной экономике с гос-кредитованием по льготным каналам | Часть РСМД, ВЭБ Институт исследований (Андрей Клепач некоторые тексты), Промсвязьбанк |
| Радикальные критики | Minority | ЦБ работает против национальных интересов; нужна валютная переориентация и контроль капитала | Глазьев (ЕАЭС), Делягин, Хазин (с оговоркой fringe-edge) |

**Symmetry check**: ✓ — есть лагерь, защищающий ЦБ, и три критических с разной аргументацией.

---

### §2.2 Инфляция РФ — природа и драйверы

**Триггеры**: проинфляционные риски, инфляция РФ, базовая инфляция, инфляц. ожидания.

| Лагерь | Уровень | Core claim | Типичные носители |
|---|---|---|---|
| Монетарный взгляд | Dominant | Избыток денежного предложения + перегрев спроса от ВПК | SberCIB, Альфа-Капитал, ЦБ РФ official communications, РЭШ |
| Издержечный (cost-push) | Significant | Санкции, логистика, импорт оборудования, рубль — главные драйверы | ЦМАКП, ИНП РАН, ВТБ Капитал |
| Бюджетно-фискальный | Significant | Импульс военных расходов + льготная ипотека/кредитование = основной разгон | Ренессанс Капитал, Bloomberg Economics RU coverage, IMF Article IV consultations |
| Институционально-ожиданческий | Minority | Слабый рубль + проинфляционные ожидания самоисполняются | ВТБ Мои Инвестиции, отдельные публикации БКС, ЦСР (Отчёты Кудрина) |

**Symmetry check**: ✓ — четыре несовместимых каузальных модели.

---

### TBD ru-macro

- **Курс рубля**: фундаменталисты (платёжный баланс) vs монетаристы (реальная ставка) vs управляемый-курс школа.
- **ВВП в военной экономике**: SuperFinance/Bloomberg-RU vs OECD/Минфин vs независимые (Bloomberg Economics, Russia Matters).
- **ФНБ и устойчивость бюджета**: бюджетный реалист vs ВПК-приматист vs IMF-aligned external view.

---

## §3. Ru-sellside

### §3.1 Возврат западных компаний / M&A после санкций

**Триггеры**: возврат западных активов, McDonald's-back, IKEA, Renault, M&A разморозка,
разворот РФ-Запад.

| Лагерь | Уровень | Core claim | Типичные носители |
|---|---|---|---|
| Оптимисты быстрого возврата | Minority | При смягчении санкций — массовый возврат уже в горизонте 1-2 лет | Отдельные авторы РБК, Forbes Russia, Telegram-каналы инвест-инфлюенсеров |
| Реалисты с дисконтом | Dominant в sellside | Возврат medium-term (3-5 лет), но с дисконтом 50-70% и ограничениями | БКС-аналитика, Альфа-Капитал, Sber Investments, Атон |
| Скептики долгого выхода | Significant | 5-10 лет минимум, юридический ландшафт сложнее, чем кажется | ВТБ Капитал, иностранные юрфирмы (Baker McKenzie post-2022 commentary), OFAC-комментаторы |
| Sovereign / RU-government view | Significant | Национализированные активы — невозвратны; «недружественные» уходили на условиях РФ | Минфин РФ official, ФАС России, ФНБ-aligned аналитика |
| Western institutional view | Significant | Возврат = legitimization war crimes, регуляторные риски репутационные | EU Commission DG TRADE, US Treasury OFAC commentary, Atlantic Council Russia program |

**Symmetry check**: ✓ — RU-side и Western-side представлены, плюс sell-side спектр.

---

### TBD ru-sellside

- **Газпром bull/bear**: дивидендный кейс vs structural decline vs LNG-расширение Сила Сибири 2.
- **Сбер**: лидер цифровизации vs sanction-overhang vs дивидендная история.
- **Дивидендный сезон 2026/27**: пайщики оптимисты vs ставка-bear vs payout-shrinkage реалисты.
- **ИИС-3 структурный**: налоговый оптимист vs ликвидный pessimist vs регуляторный риск.

---

## §4. Global-banks

### §4.1 US recession 2026/2027

**Триггеры**: US recession, hard landing, soft landing, no landing, Fed cuts.

| Лагерь | Уровень | Core claim | Типичные носители |
|---|---|---|---|
| Soft landing (мягкая посадка) | Dominant | Дезинфляция без рецессии, Fed аккуратно снижает ставку | Goldman Sachs (Hatzius), Brookings (Yellen-aligned), Citi sometimes |
| No landing | Significant | Экономика не остывает, инфляция sticky → ставки выше дольше | Larry Summers (Harvard), Mohamed El-Erian, отдельные strategists JPMorgan |
| Hard landing / structural recession | Significant | Накопление dislocations (CRE, региональные банки, потребкредит) → острый спад | David Rosenberg (Rosenberg Research), Lacy Hunt (Hoisington), BCA Research, Quincy economic policy |
| Stagflation 2.0 | Minority | Низкий рост + повышенная инфляция как новый режим | Roubini Macro Associates, Stephen Roach (Yale), Russell Napier |
| Cycles-deny structural growth | Minority | Productivity boost от AI отменяет циклическую логику | Goldman Sachs AI team (Kostin), некоторые публикации McKinsey, RBC Capital |

**Symmetry check**: ✓ — все 4 классических исхода + AI wildcard.

---

### TBD global-banks

- **Fed rate path 2026**: dovish (быстрые cuts) vs hawkish (ставка stuck) vs sideways.
- **Inflation regime**: transitory (вернёмся к 2%) vs structurally higher (3-4% new normal) vs fragmentation-driven.
- **EM debt crisis**: contained vs cascading (Frontier first) vs China-spillover.
- **Oil 2026/27**: $50 (recession) vs $80 (status quo) vs $100+ (Iran/supply shock).

---

## §5. Tech-CEO

### §5.1 AGI timeline

**Триггеры**: когда AGI, AGI прогноз, ASI timeline, transformative AI.

| Лагерь | Уровень | Core claim | Типичные носители |
|---|---|---|---|
| Short timeline (≤5 лет) | Dominant в frontier labs | AGI к 2027–2030; scaling + reasoning достаточны | Sam Altman (OpenAI), Demis Hassabis (DeepMind), Dario Amodei (Anthropic), Leopold Aschenbrenner |
| Medium timeline (5–15 лет) | Significant | AGI к 2035–2040; потребуются архитектурные прорывы | Jensen Huang (NVIDIA), Sundar Pichai (Google), Satya Nadella (MS), Mustafa Suleyman, Reid Hoffman |
| Long timeline (15+ лет) / scaling-skeptic | Significant | LLMs упираются в потолок; AGI требует фундаментально нового подхода | Yann LeCun (Meta FAIR), Andrew Ng, Rodney Brooks, Subbarao Kambhampati |
| AGI-критики (понятие проблемно) | Minority | «AGI» — недоопределённое понятие; критика hype-цикла и benchmarking | Gary Marcus (NYU), Emily Bender, Timnit Gebru, Melanie Mitchell |
| Safety-first cautious | Minority | Timeline возможно short, но риски недооценены, нужна пауза | Stuart Russell (Berkeley), Yoshua Bengio (Mila), MIRI, FLI |

**Symmetry check**: ✓ — обе крайности (short/long) + критики самого понятия + safety angle.

---

### TBD tech-ceo

- **AI labor disruption timeline**: 2030-collapse (Hinton, частично Altman) vs gradual (Acemoglu) vs no-disruption (Robert Gordon, Daron skeptics некоторые).
- **AI alignment solvable**: solvable (Anthropic, OpenAI Superalignment ex) vs hard but tractable (DeepMind safety) vs unsolvable in time (MIRI, Bengio).
- **Big Tech антимонопольные риски**: structural breakup vs status quo vs functional regulation.

---

## §6. Шаблон для добавления новой темы

```markdown
### §X.Y {Название темы}

**Триггеры**: {ключевые слова в запросе пользователя, по которым выбирать эту карту}

| Лагерь | Уровень | Core claim | Типичные носители |
|---|---|---|---|
| {Название лагеря 1} | Dominant / Significant / Minority | {1 строка ключевого тезиса} | {3–7 институций} |
| {Название лагеря 2} | ... | ... | ... |
| ... |

**Symmetry check**: {✓ / ✗ + почему}. Если ✗ — пометить «контр-лагерь институционально не представлен».
```

**Чек-лист перед коммитом новой карты:**

1. ☐ Минимум 3 лагеря.
2. ☐ Хотя бы один Dominant.
3. ☐ Если запрос содержит асимметричную атрибуцию — есть лагерь с обратной стороны.
4. ☐ Все носители — institutional (не частные блогеры/Telegram-каналы без института).
5. ☐ Core claim каждого лагеря в одну строку, без воды.
6. ☐ Триггеры однозначно отличают эту тему от соседних.
7. ☐ Тема упомянута в триггер-таблице в начале файла.

---

## §7. Cross-domain — заметки по связкам

Темы, требующие карт из >1 домена одновременно. При запросе таких тем — собрать
лагеря из всех релевантных разделов.

- **«Ставка ЦБ vs геополитика»** → §2.1 + §1.3 (если контекст санкций/войны).
- **«Возврат западных компаний vs санкции»** → §3.1 + §1.3 + §1.2 (US-Europe политика санкций).
- **«AI export controls США → КНР»** → §5.1 + §1.4.
- **«Иран и нефть»** → §1.1 + §4.1 (oil scenarios) + §1.7 (Hormuz).
- **«КНДР усиливает РФ»** → §1.5 + §1.3.

---

## §8. Версионирование и пересборка

- При добавлении/изменении карты — указать дату изменения комментарием перед таблицей: `<!-- updated YYYY-MM-DD -->`.
- При очередном аудите источника в INDEX.md — носители в карте автоматически перевзвешиваются скиллом (вес тут не зашит).
- Если носитель удалён из INDEX как unreliable + появилась альтернатива — обновить таблицу карты.
- Раз в 6 месяцев — review всего файла на устаревшие лагеря (новые расколы, исчезнувшие лагеря).
