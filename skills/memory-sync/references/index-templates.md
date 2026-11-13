# Index Templates: шаблоны INDEX.md и YAML frontmatter

## Master INDEX.md (root: Claude-Memory/INDEX.md)

```markdown
# Claude Memory — Master Index

*Последний sync: {YYYY-MM-DD HH:MM MSK}*

## Структура библиотеки

| Subdomain | Источников | Последний аудит |
|---|---|---|
| [{domain_name}]({domain_dir}/INDEX.md) | {N} | {YYYY-MM-DD} |
| ... (все найденные папки в domains/) | ... | ... |

## Сводный track record (top-10 по совокупному весу)

| Источник | Subfolder | Trust summary | Аудитов |
|---|---|---|---|
| ... | ... | ... | ... |

## Состояние memory_user_edits

- `[lib]` записей: {N}
- Пользовательских записей: {M}
- Свободно слотов: {30 − N − M}

---

## Принципы

- Файлы в этой библиотеке — **source of truth**.
- `memory_user_edits` — кеш горячих профилей для автоматического срабатывания.
- Не модифицировать содержимое аудитов после публикации без обновления `last_updated` в frontmatter.
- При изменении trust в существующем аудите — поднять `last_updated`, иначе sync пропустит изменения.

## Cross-references

- `forecast-confidence-applier` читает этот INDEX для применения весов
- `retrospective-forecast-audit` пишет новые файлы в правильный subfolder
- `memory-sync` обновляет memory из этого INDEX
- `_sync_log.md` — лог операций memory-sync
- `_meta-analysis/` — cross-source meta-выводы (опционально)
```

## Subfolder INDEX.md (например, geopolitics/INDEX.md)

```markdown
# Geopolitics — Index

*Последний аудит: {YYYY-MM-DD}*

## Источники в этом subfolder

| Источник | Trust по subdomain'ам | Last audit | Аудитов | Pin |
|---|---|---|---|---|
| Stratfor | HIGH long-term-russia, IGNORE eu-future, IGNORE china-collapse | 2025-03-15 | 2 | yes |
| CFR | HIGH iran, MEDIUM russia | 2026-04-22 | 1 | no |
| ... | ... | ... | ... | ... |

## Subdomain coverage

| Subdomain | Кто покрывает | Top источники по trust |
|---|---|---|
| russia-long-term | Stratfor (2), CFR (1) | Stratfor HIGH |
| iran | CFR (1), Carnegie (1) | CFR HIGH, Carnegie MEDIUM |
| china-future | Stratfor (1), Carnegie (1), Brookings (1) | Carnegie MEDIUM, остальные LOW/IGNORE |
| ... | ... | ... |

## Файлы

- `stratfor-1995-2025.md` — Full Audit, Opus, 23 тезиса, hit rate 41%
- `stratfor-2015-2025.md` — Light Audit, Sonnet, 13 тезисов, hit rate 54%
- `cfr-2024.md` — Full Audit, Opus, 8 тезисов, hit rate 75%
- ...
```

## YAML frontmatter аудита

Каждый файл аудита в библиотеке имеет stricter frontmatter, чем стандартный markdown. Пример:

```yaml
---
source: "Stratfor"
period: "1995-2025"
audit_type: "Full"
audit_model: "Opus 4.7"
audit_date: "2026-04-25"
last_updated: "2026-04-25"
theses_count: 23
hit_rate: 0.41
alpha_generation: 0.36
avg_value: 0.18

trust:
  long-term-russia: HIGH
  eu-future: IGNORE
  china-collapse: IGNORE
  middle-east: MEDIUM

pin: false

skill_version: "v0.7"

# Опциональные поля
meta_audit_used: true              # был ли использован §3.M
data_source: "secondary"           # primary | secondary (через Dungaciu)
deep_research_used: false          # workflow B был ли применён
---

# Ретроспективный аудит Stratfor Decade Forecast 1995–2025

[остальное содержимое аудита]
```

### Обязательные поля frontmatter

- `source` — string, ключ агрегации
- `audit_date` — YYYY-MM-DD
- `trust` — object с subdomain → enum {HIGH, MEDIUM, LOW, IGNORE}

### Рекомендуемые поля

- `period` — для определения newest при множественных аудитах
- `last_updated` — для определения newest, обновлять при правках
- `audit_type` — Full / Light, влияет на tie-breaking
- `pin` — boolean, явная пометка для memory inclusion
- `theses_count`, `hit_rate`, `alpha_generation` — для сводной статистики

### Опциональные поля

- `audit_model` — Opus 4.7 / Sonnet 4.6 (для версионирования)
- `skill_version` — версия скилла, который сделал аудит
- `meta_audit_used` — flag для §3.M
- `data_source` — primary / secondary
- `deep_research_used` — workflow B?

## Стандартные subdomain'ы по доменам

> **Важно:** это справочник рекомендуемых имён subdomain'ов для консистентности
> между источниками. Скилл не фильтрует по этому списку — он принимает любые
> subdomain'ы из frontmatter `trust`. Новые домены в `domains/` не требуют
> обновления этого файла для работы скилла.

Чтобы trust_summary был коротким и cross-source comparable.

### geopolitics
- `long-term-russia` — прогнозы на Россию >5 лет
- `short-term-russia` — прогнозы на Россию <2 лет
- `eu-future` — будущее ЕС, евроинтеграция
- `china-collapse` — прогнозы дезинтеграции Китая
- `china-rise` — прогнозы технологического/экономического подъёма
- `middle-east` — Ближний Восток в широком смысле
- `iran` — конкретно Иран
- `us-domestic` — внутренняя политика США
- `nato-future` — будущее НАТО
- `nuclear-proliferation` — ядерное распространение
- `migration-eu` — миграционные кризисы в Европе

### ru-sellside
- `iis-targets` — таргеты для ИИС-3 (1–3 года)
- `long-term-strategy` — стратегические рекомендации >3 лет
- `oil-gas-ru` — нефтегаз
- `metals-mining-ru` — металлы и горнодобыча
- `it-tech-ru` — российский IT
- `finance-ru` — финансовый сектор
- `consumer-ru` — потребительский сектор
- `bonds-rub` — рублёвые облигации
- `bonds-fx` — валютные облигации
- `dividend-stocks` — дивидендные акции
- `small-caps-ru` — small-caps
- `etfs-ru` — российские ETF / БПИФы

### global-banks
- `us-equities` — американские акции
- `european-equities` — европейские акции
- `emerging-markets` — EM в целом
- `oil-forecast` — нефтяные прогнозы
- `commodities-non-oil` — золото, серебро, агро
- `currency-forecasts` — валюты
- `ny-rates` — ставки FED, доходности US Treasuries
- `crypto` — криптовалюты
- `ai-stocks-bubble` — AI-stock прогнозы
- `recession-call` — прогнозы рецессии
- `sector-rotation` — секторная ротация рекомендации

### tech-ceo
- `agi-timeline` — прогнозы достижения AGI
- `model-capability` — конкретные capability prediction
- `regulation-ai` — регуляторные прогнозы
- `compute-economics` — экономика compute
- `crypto` — для CEO с крипто-уклоном
- `space-tech` — для Маска и т.п.
- `biotech-future` — Альтман, Хассабис

### ru-macro
- `ru-rates-forecast` — ставка ЦБ
- `ru-inflation` — инфляция
- `usd-rub-forecast` — USD/RUB
- `cny-rub-forecast` — CNY/RUB
- `ru-budget` — бюджет, нефтегазовые доходы
- `ru-economy-growth` — ВВП, промпроизводство
- `ru-banking-system` — банковский сектор

### commodity-agencies
- `oil-price-forecast` — нефтяные прогнозы цены (IEA, OPEC, EIA)
- `gas-forecast` — газовые прогнозы
- `metals-forecast` — металлы (золото, медь, алюминий)
- `agro-forecast` — агропрогнозы
- `ru-oil-production` — добыча/экспорт нефти Россия
- `demand-outlook` — прогнозы спроса на сырьё

## Шаблон создания структуры в Setup

При первом запуске `memory-sync` без существующей библиотеки:

Создать папку `domains/` и внутри неё — по одной папке на каждый домен согласно
актуальному списку из `references/claude-memory-layout.md`. Пример:
```
domains/geopolitics/
domains/ru-sellside/
domains/global-banks/
domains/tech-ceo/
domains/ru-macro/
domains/commodity-agencies/
... (добавляй по мере появления новых доменов)
```
Список не фиксирован в этом файле — он определяется `claude-memory-layout.md`.

Затем создать INDEX.md в root и в каждом subfolder с template'ами выше (поля `{N}` и `{YYYY-MM-DD}` заполнить как 0 и сегодняшней датой соответственно).

`_sync_log.md` создаётся при первом успешном sync.

`_pending_sync.md` создаётся только при scheduled task с destructive operations (см. confirmation-prompts.md § Scheduled task).
