# Model Routing

Таблица выбора модели по скиллу и режиму.

## Текущие версии семейств

Единственное место с номерами версий; в остальных файлах пишется только семейство.

| Семейство | Текущая версия | Проверено |
|---|---|---|
| Haiku | 5.5 | 2026-11-05 |
| Sonnet | 5.5 | 2026-11-05 |
| Opus | 5.5 | 2026-11-05 |
| Fable | 5.1 | 2026-11-05 |

Источник — список моделей Claude Code на дату проверки; в claude.ai сверять по переключателю моделей.

**Модели (обновлено 2026-08-12, подписка Pro):**

| Модель | Input $/MTok | Output $/MTok | Context | Примечание |
|---|---|---|---|---|
| **Opus** | $5 | $25 | 1M | отдельный недельный счётчик на Pro — беречь для сложного |
| **Sonnet** | $3 | $15 | 1M | дефолт; с Sonnet 5 новый токенизатор (~30% больше токенов на тот же текст, чем Sonnet 4.6 — цена/токен та же, пере-базируй бюджеты) |
| **Haiku** | $1 | $5 | 200K | рутина и мониторинг |
| **Fable** | $10 | $50 | 1M | НЕТ в подписке Pro — только API/Max; см. строку coherence-audit |

Экономия от маршрутизации на подписке — в первую очередь **квотная**: у Opus на Pro
отдельный недельный лимит, исполнение на Sonnet его не расходует. Дефолт сессии —
Sonnet; для планирования сложных правок — `/model opusplan` (Opus планирует,
Sonnet исполняет) или точечный `/model opus`.

---

## Таблица по скиллу

| Скилл | Режим / условие | Модель |
|---|---|---|
| `forecast-monitor` | всегда | Haiku (только проверка событий; `claude -p` на Pro тратит тот же лимит подписки) |
| `macro-ru-watcher` | всегда | Sonnet |
| `memory-sync` | всегда | Sonnet |
| `forecast-collector` | всегда | Sonnet |
| `forecast-confidence-applier` | всегда | Sonnet |
| `hypothesis-stress-tester` | всегда | Sonnet |
| `scenario-builder` | всегда | Sonnet |
| `portfolio-data-loader` | всегда | Sonnet |
| `portfolio-scenario-stress` | всегда | Sonnet |
| `macro-forecast-chain` | всегда | Sonnet |
| `save-to-library` | всегда | Sonnet |
| `revise-memory-local` | всегда | Sonnet |
| `revise-memory-remote` | всегда | Sonnet |
| `retrospective-forecast-audit` | ≤8 тезисов, ≤45 мин | Sonnet (Light) |
| `retrospective-forecast-audit` | ≥9 тезисов или ≥45 мин | Opus (Full) |
| `ru-portfolio-advisor` | Режимы 1–7 | Sonnet |
| `ru-portfolio-advisor` | Режим 8 (Stock Quality Forward Review) | Opus |
| `portfolio-integrated-view` | всегда | Opus |
| `portfolio-coherence-audit` | Stage P (bundle-скрипт) | любая (Python без LLM — хоть Haiku-сессия/cron) |
| `portfolio-coherence-audit` | Stage R (рассуждение) | **Fable** (whole-corpus coherence). На Pro недоступен: либо реже и через API-кредиты, либо деградация на Opus с явной оговоркой в шапке отчёта «прогон на Opus, глубина ниже канона»; тест оправданности прежний: помещается в один заход Opus без потери когерентности → задача НЕ для Fable |

---

## Правило предупреждения

Если активная модель слабее рекомендуемой — в шапке ответа добавить предупреждение:

> ⚠️ Этот режим рекомендует [модель]. На [текущей модели] результат будет ограничен.
> Переключи модель и повтори запрос.

Если активная модель мощнее (Opus на Sonnet-задаче) — работать молча, не предупреждать.

---

## Запрет Haiku

`retrospective-forecast-audit` и `ru-portfolio-advisor` (Режим 8) **не запускаются на Haiku.**
Причина: 200K контекста легко превышается; глубина рассуждений недостаточна.
При активной Haiku → отказ + инструкция переключить модель.
