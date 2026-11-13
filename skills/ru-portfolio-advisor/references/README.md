# References index

Навигация по reference-файлам скилла. SKILL.md ссылается на эти файлы — читай их по мере необходимости, не все сразу.

- **sources.md** — иерархия источников (первичка → брокеры → СМИ → агрегаторы мнений → теханализ). Куда идти за данными, какому источнику верить больше при конфликте.
- **data-sources-priority.md** — узко про биржевые данные: MOEX ISS API, fallback-уровни при его недоступности, интерфейс скрипта `scripts/moex_quotes.py`, схема выходного JSON. Читай при любой задаче, где нужна цена, YTM, дюрация, объём или рыночная капитализация.
- **stocks-methodology.md** — методология Weekly Stocks Review и Single Stock Analysis. Шаги сбора событий, классификация сигналов, специфика по секторам.
- **bonds-methodology.md** — методология Weekly Bonds Review и Single Bond Analysis. Работа с YTM, замещайками, рейтингами, ИИС-3.
- **rebalance-framework.md** — как работать с ребалансировкой IE, оценка тайминга продаж/покупок, предложения по изменению целевых долей. Включает Шаг 1а — применение HIGH/MEDIUM/LOW-фильтра к каждому IE-изменению.
- **funds-methodology.md** — анализ конкретного фонда и подбор фонда под сегмент (акции / облигации / all-in-one). Специфика БПИФ/ЗПИФ, TER, tracking error, премия/дисконт к СЧА, сравнение с прямым владением.
- **macro-framework.md** — учёт макро-переменных (ставка, инфляция, курс, нефть, бюджет) и геополитики. Когда макро-сигнал достаточно силён для пересмотра плана.
- **output-templates.md** — общие правила вывода для всех режимов (база весов, база докупки, режимы и гейты словами, плотность, сверка ограничений, решение по бумаге — блок `decisions:`) и карта шаблонов. Шаблоны режимов: **templates-weekly.md** (1–2), **templates-other-modes.md** (3–8). Разрезано 2026-10-26.
- **gate-aware-sizing.md** — обоснование базы докупки акций (вынесено из stocks-methodology 2026-10-26): нужен в режиме 3, при вопросе «откуда число» и при правке правил сайзинга.
- **invest-era-profile.md** — профиль источника Invest Era на основе 3 ретроспективных аудитов (Дек 2024, Мар 2025, Ноя 2025). Содержит категории доверия HIGH/MEDIUM/LOW по типам рекомендаций, системные дельты для контрсигнала по макро-прогнозам IE, триггеры пересмотра профиля. Читай при любом запросе, где используется `IE New` / `IE Old` или колонка `IE`.
- **stress-reading.md** — чтение stress-файла в режимах 3 и 8: прогон `scripts/stress_digest.py`, разные лестницы свежести (Mode 8 отказывается при >60 дней, Mode 3 откладывает только L1-redirect), якорные горизонты и множители, какие поля куда идут, сверка поколения со снапшотом.
- **model-routing.md** — таблица «режим скилла → модель Claude». Дефолт Sonnet для большинства режимов, Opus для режима 8 и многорежимных, Haiku для методологических вопросов без файлов. Сигналы эскалации/деэскалации. Читай в начале сессии для определения, нужно ли рекомендовать пользователю переключение модели.

## Когда какой файл нужен

| Запрос пользователя | Читать |
|---|---|
| Еженедельный обзор акций | stocks-methodology + output-templates + templates-weekly + sources + **data-sources-priority** (по необходимости macro) |
| Еженедельный обзор облигаций | bonds-methodology + macro-framework + output-templates + templates-weekly + sources + **data-sources-priority** |
| Оценить ребалансировку IE / что делать с весами / когда продавать | rebalance-framework + **invest-era-profile** + output-templates + templates-other-modes + gate-aware-sizing + stocks-methodology (для разбора позиций) + **data-sources-priority** + **stress-reading** |
| Разобрать конкретную акцию (особенно из IE-модельки) | stocks-methodology + **invest-era-profile** + output-templates + templates-other-modes + sources + **data-sources-priority** |
| Разобрать конкретную облигацию / эмитента | bonds-methodology + output-templates + templates-other-modes + sources + macro-framework + **data-sources-priority** |
| Есть ли повод менять целевые доли | macro-framework + rebalance-framework + **invest-era-profile** (если IE-обоснование) |
| Stock Quality Forward Review (режим 8) | stocks-methodology + macro-framework + **invest-era-profile** + **model-routing** + output-templates + templates-other-modes + **stress-reading** |
| MOEX ISS недоступен / сомнения в котировке / нужен fallback | **data-sources-priority** (разделы "Уровень 2–6") |
| Нужно понять, какую модель Claude использовать | **model-routing** |
