# Класс бумаги — справка

Класс бумаги (`ticker_class`) живёт **в справочнике бумаг** `Claude-Memory/Portfolio/security-attrs.json`
(`security-attrs@1`, `docs/investment/_cross-cutting/data-structures/schema.md` §4.8): одна запись на ключ (тикер или
ISIN) с полями `ticker_class`, `listed_at` (дата первых торгов на Мосбирже), `note`. Значения класса — кодлист
`ticker_class` в `codelists.json` (`bluechip`, `mid_cap`, `ipo`, `fund_zpif`, `fund`, `bond`).

- В решении по бумаге класс **не хранится** и модель его не пишет (schema.md §3.1).
- Срок пересмотра от класса не зависит: его ставит модель полем `review_by` решения (по умолчанию 60 дней).
- Несущая роль класса — IPO-пауза: `ticker_class: ipo` и `listed_at` + 8 кварталов позже сегодняшнего дня →
  докупка закрыта при любом вердикте.
- Класс модель не определяет эвристически; правка — по слову владельца через save-to-library.
