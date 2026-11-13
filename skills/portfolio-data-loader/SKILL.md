---
name: portfolio-data-loader
description: "Парсит trades_portfolio_*.xlsx (IntelInvest) с планом сайта Portfolio/plan.json (Общий баланс.numbers — по желанию), считает XIRR/TWR/ROI с per-type breakdown (акции/облигации/фонды), доходности по тикеру, применяет сплиты (T 1:10, PLZL 1:10, GMKN 1:100, TRNFP 1:100) и корректировки, получает цены через MOEX ISS, считает YTM облигаций, выдаёт JSON-снапшот v2 (schema_version 2.0). Сохраняет в Portfolio/snapshots/ через Synology mount. Снапшот потребляется ru-portfolio-advisor и portfolio-scenario-stress. ТОЛЬКО данные — никаких рекомендаций. Активируй ОБЯЗАТЕЛЬНО когда: «обнови снапшот портфеля», «пересчитай доходность», «загрузи портфель», «снапшот портфеля», «посчитай XIRR», «portfolio snapshot», прикладывают trades_portfolio_*.xlsx или Общий баланс.numbers для получения структурированных данных. НЕ активировать: «что докупить» (→ advisor), «ребалансировка» (→ advisor), «сценарный анализ» (→ portfolio-scenario-stress), «еженедельный обзор» (→ advisor)."
shared_refs: [transport-layer, yaml-schemas, claude-memory-layout]
bundle_scripts: [moex_quotes.py]
---

# portfolio-data-loader

Чистый data layer: парсит входные файлы, валидирует, считает доходности, отдаёт структурированный JSON-снапшот **schema v2.0**. Аналог `macro-ru-watcher` в портфельном домене.

**Никаких рекомендаций. Никакой аналитики. Только данные.**

**Сборка надёжнее на сайте** (кнопка «📥 Снапшот» во вьюере: тот же `build_snapshot.py` на NAS, где
сеть до MOEX ISS и ЦБ стабильна); в облачной среде Claude MOEX ISS отвечает не на всё, и сборка
скиллом упирается в блок-флаги цен Шага 7. Сайт при «Сохранить» кладёт снапшот прямо в `Portfolio/snapshots/`
(и сам пересобирает журнал решений); при блок-флаге цен у скилла — попроси собрать на сайте.

Тип бумаги (акция / облигация / фонд) с Мосбиржи запрашивает только сборка на сайте
(`security_types.py`); скилл читает справочник `Portfolio/security-types.json` (`--types-cache`, нет файла —
эвристика по сделкам) и в ISS за типами не ходит. Расхождения типа — во флаге `asset_type_changed`
(`snapshot.type_check`): проверить до перевода снапшота в рабочий.

Корзина облигации выводится из справочника (валюта · ОФЗ и срок · рейтинг КОРП из плана или обзора облигаций), в
снапшоте остаётся по плану, пока владелец не примет выведенную: расхождение — флаг `bond_bucket_changed`; ручная
корзина — `plan.bonds[ISIN].manual`. Правило — `bond-subtypes-plan.md` §4.5.

---

## Inputs / Outputs

**Inputs:**
- `trades_portfolio_*.xlsx` ← пользователь прикладывает файл, формат IntelInvest экспорт
- *(опц.)* `Общий баланс.numbers` (или `.xlsx`) — план берётся из `Portfolio/plan.json`; баланс сверяется с планом, а его позиции ИИС-3 сверяются с выгрузкой счёта (расхождение — `iis_returns_mismatch`, баланс не перетирается)
- *(опц.)* `trades_portfolio_838526*.xlsx` — выгрузка IntelInvest **только БКС-ИИС-3**; приходит лишь после покупки/продажи/взноса на этом счёте, иначе берётся последняя из `Claude-Memory/Portfolio/inputs/` (Шаг 4б); **без баланса позиции ИИС-3 строятся по её сделкам** (`iis_positions_source: trades_export`), перенос из прошлого снапшота (`carried`) — только когда выгрузки счёта нет вовсе

**Outputs:**
- `portfolio-<date>.json` — снапшот. Loader **сам** пишет его (**исключение D3** — НЕ через save-to-library), предварительно проактивно спросив разрешение (Шаг 7): по умолчанию в пробную `Portfolio/snapshots/auto/portfolio-<date>-<ЧЧММ>-skill.json`, в рабочую `Portfolio/snapshots/portfolio-<date>.json` — только по явной просьбе. Не останавливайся молча после сборки — всегда предлагай сохранить.

**Upstream скиллы:** —
**Downstream скиллы:** `ru-portfolio-advisor`, `portfolio-scenario-stress`, `portfolio-integrated-view`
**Shared refs:** `transport-layer`, `yaml-schemas`, `claude-memory-layout`

## Скрипты — дерево зависимостей

Пять скриптов + опциональный шестой, порядок жёсткий (промежуточные JSON в /tmp):

```
parse_portfolio.py    (баланс .numbers)  → portfolio.json    ─┐
portfolio_returns.py  (trades .xlsx)     → returns.json      ─┤
moex_quotes.py        (MOEX ISS, сеть)   → quotes.json       ─┼→ assemble_snapshot.py → portfolio-<date>.json
per_security_xirr.py  (trades + quotes)  → per_security.json ─┤      (+ prev-snapshot, sector-overrides)
iis_returns.py        (trades БКС-ИИС-3) → iis_returns.json  ─┘  опц., Шаг 4б
```

`merge_cross_currency_positions` снаружи не вызывать; сплиты применяются внутри
`reconstruct_positions` множителем `split_factor`, снаружи повторно не применять. Все quirks промежуточных форматов закодированы в
`assemble_snapshot.py` — таблица в разделе «Технические особенности» ниже; читай её
ПЕРЕД правкой любого скрипта.

---

## Schema versioning

Текущая версия выходного JSON: **`schema_version: "2.0"`**.

Поле присутствует в `portfolio.json` (промежуточный файл из `parse_portfolio.py`) и выставляется в `"2.0"` при финальной сборке снапшота (Шаг 6).

Consumers, которые ожидают v2+, должны проверять:
```python
schema_ver = snapshot.get("schema_version", "1.0")
if schema_ver < "2.0":
    raise ValueError("Нужен snapshot v2.0+. Перегенерируй через portfolio-data-loader.")
```

Backward compatibility: v2 **additive only** — все ключи v1 (`holdings`, `cash`, `returns`, `per_instrument_xirr`) остаются без изменений. Новые ключи: `ie_model`, `ie_actual`, `ie_summary`, `balance_summary.by_account`. Добавления 2026-07 (тоже additive): `holdings[].status` / `status_note` + топ-уровневый `status_summary`; `is_blocked` сохранён как производное от `status`. Добавления 2026-08 (тоже additive, RPA-правило неразворота Rule 3): `per_instrument_xirr[ticker].recent_*` (свёртка недавних buy/sell-сделок — `recent_net_rub`, `recent_direction`, `recent_last_trade_date`, `recent_n_buys`, `recent_n_sells`, `recent_round_trip`) + топ-уровневый `recent_trades_window` (`days`, `net_threshold_rub`, `threshold_basis`). Отсутствуют в снапшотах и `per_security.json` до этой даты — читай отсутствие как `null`/пустое.

---

## Что НЕ парсится

- **Вкладка «Импорт Акции»** — raw IntelInvest snapshot, дублирует `holdings` (которые уже идут с MOEX-ценами и XIRR). Не используется.
- **Вкладка «Импорт облигации»** — аналогично, дублирует `holdings` по облигациям.
- **Колонки «Точка Входа» и «Стоимость покупок» из вкладки «Акции»** — дублируются с `avg_cost_rub` в holdings.
- **Вкладка «Ребаланс»** — внутренняя IntelInvest-разметка, не нужна для snapshot.
- **Реестр сплитов** — файл `Portfolio/known-splits.json` (формат `known-splits@1`) плюс встроенный запасной набор (`known_splits.BUILTIN`); читает его только сборка, advisor список не трогает. Подозрение на новый сплит сборка выдаёт предупреждением `split_suspected`. Подробности — `references/splits-corrections.md`.
- **KNOWN_POSITION_STATUS** — реестр статусов позиций (`normal | blocked | distressed`), живёт **только** в `scripts/assemble_snapshot.py`. Ручной список, как splits: MOEX его не даёт. См. Шаг 6.
- **Per-account XIRR** — только для БКС-ИИС-3 по отдельной выгрузке (Шаг 4б, `returns.by_account.iis_3`); по остальным счетам отдельных выгрузок нет.

---

## Глобальные принципы (применяй ВЕЗДЕ)

1. **Pure data, never advising.** Этот скилл собирает и считает. Никаких «это хорошая доходность», «стоит докупить», «риск высокий». Только snapshot → вычисления → флаги → JSON.

2. **Fail-fast, не заполняй догадками.** Если поле не парсится — помечай в `data_quality_flags`, не подставляй «примерно». Лучше разрыв в данных, чем фантомная цифра.

3. **Каждое число — из источника или явного вычисления.** Не из памяти модели, не из training data. Если MOEX ISS не вернул цену — `price_source: "unavailable"` и флаг в `data_quality_flags`.

4. **Идемпотентность.** Повторный запуск на тех же файлах и той же дате → идентичный JSON. Если сохранённый снапшот за сегодня уже есть — перезаписать.

5. **Язык логов — русский.** `corrections_log` и `data_quality_flags` на русском. Названия полей JSON — английские.

6. **Dual transport.** Читать `references/transport-layer.md` перед первой операцией с файловой системой.

---

## Workflow (7 шагов + шаг 0, опц. 4б)

### Шаг 0. Транспорт

Прочитать `references/transport-layer.md` (пути, проверка доступности Synology mount).

Все операции сессии (чтение предыдущих снапшотов, запись нового) — строго в рамках выбранного транспорта.

---

### Шаг 1. Определи входные файлы

Проверь, что приложено в текущем сообщении:

| Файл | Что даёт | Обязательность |
|------|----------|----------------|
| `trades_portfolio_*.xlsx` | История сделок → XIRR/TWR/per-security | Для расчёта доходностей |
| `Общий баланс.numbers` (или `.xlsx`) | Сверка с `plan.json` и позиций ИИС-3 | Опционально, только для сверки |
| `trades_portfolio_838526*.xlsx` (только БКС-ИИС-3) | Доходность счёта ИИС-3: факт / к погашению / зафиксированная | Опционально, Шаг 4б |

**Сделки + `Portfolio/plan.json`** → полный снапшот (штатный путь). **Сделки + баланс** → полный снапшот со сверкой плана.
**Только `trades_portfolio` без `plan.json`** → returns-only снапшот (без текущей структуры портфеля).
**Только `Общий баланс`** → holdings-only снапшот (без XIRR).

Если ни одного файла не приложено — остановись и попроси:
> «Для снапшота портфеля нужна выгрузка сделок `trades_portfolio_*.xlsx`; выгрузка ИИС-3 — если по счёту были операции; «Общий баланс» — только для сверки.»

Запиши пути к файлам:
```python
trades_path = "/tmp/trades.xlsx"          # если приложен
balance_path = "/tmp/Общий баланс.numbers"  # если приложен
```

---

### Шаг 2. Парсинг Общий баланс (если приложен)

«Общий баланс» — по желанию, нужен для сверки: штатный путь — сделки + `Portfolio/plan.json` (план, цели, корзины облигаций, IE и ручные позиции из базы сайта, без `--plan-primary`); с балансом сборка идёт как прежде, а план главным делает только `--plan-primary`. Что и откуда в сборке без баланса — `references/output-schema.md`, раздел «Снапшот без баланса».

```bash
pip install numbers-parser --break-system-packages -q
python3 scripts/parse_portfolio.py "$balance_path" > /tmp/portfolio.json
```

Проверь `raw_sheets` в выходном JSON — если структура неожиданная, пометь в `data_quality_flags` и не прерывай работу. Детали формата — в `references/parsing-numbers.md`.

Ключевые поля из `/tmp/portfolio.json`:
- `metrics.active_stock_tickers` → список тикеров для per-security XIRR
- `metrics.total_current_rub_excl_iis` → база для долей
- `holdings` → будущий список позиций в снапшоте
- `errors_check` → проверь сразу, если `"Есть в IntelInvest, нет в Акция" = true` → флаг рассинхрона

---

### Шаг 3. Расчёт доходностей (если приложен trades)

```bash
pip install openpyxl --break-system-packages -q

# Базовый отчёт
python3 scripts/portfolio_returns.py --trades "$trades_path" --format json > /tmp/returns.json

# Если MOEX недоступен
python3 scripts/portfolio_returns.py --trades "$trades_path" --format json --no-moex > /tmp/returns.json

# Если ЦБ РФ возвращает 503
python3 scripts/portfolio_returns.py --trades "$trades_path" --format json --cbr-offline > /tmp/returns.json
```

Детали формата `returns.json` — в `references/xirr-twr-calculation.md`.

**Бенчмарк-гейт (PME)** считается в этом же прогоне best-effort: блок
`benchmarks_restricted` — те же потоки суб-портфелей, вложенные в бенчмарк
(акции → MCFTR полной доходности через MOEX ISS, облигации → вклад КС−1 пп
через ЦБ SOAP). При сбое сети блок частично/полностью `null` + флаги внутри
блока — отчёт не падает. Отключение: `--no-benchmarks`. В снапшоте блок
живёт в `returns.benchmarks`; отрицательный `gap_pp` = бенчмарк был лучше
фактических решений на окне с 2022-03 — покажи это пользователю в сводке.

Флаги в `data_quality_flags` при частичном успехе:
- `moex_unavailable` / `moex_quotes_failed` — MOEX ISS не ответил при сборке; молчаливая оценка по цене
  последней сделки при живой котировке MOEX — блок-флаги Шага 7, не предупреждение
- `"ЦБ РФ недоступен, курсы из bundled cache"` — если использован `--cbr-offline`
- `"blocked_positions: N позиций оценены в 0"` — если есть заблокированные

⚠️ `--blocked-value last_trade` **не использовать**: для FinEx-фондов
`last_known_trade_price` попадает на sell-ногу сплит-пары (до-сплитовая цена ×
post-split qty → завышение до 100×, кейс FXRL: 4.36 млн вместо ~38 тыс.).
Default `zero` — консервативная и честная оценка; см. Шаг 6 «Статус позиции».

---

### Шаг 4. Per-security XIRR

Запускай, если `trades_portfolio_*.xlsx` приложен. Список тикеров — из `metrics.active_stock_tickers` (шаг 2) или из `returns.json → snapshot_current.positions`.

```bash
# Получить список активных тикеров
TICKERS=$(python3 -c "
import json
positions = json.load(open('/tmp/returns.json'))['snapshot_current']['positions']
tickers = [p['ticker'] for p in positions if not p.get('is_blocked') and p.get('qty',0)>0]
print(','.join(tickers))
")

python3 scripts/per_security_xirr.py \
    --trades "$trades_path" \
    --tickers "$TICKERS" \
    --format json > /tmp/per_security.json
```

Если `Общий баланс.numbers` тоже приложен, добавь `--common /tmp/portfolio.json`: стоимость баланса служит **запасной** оценкой (MOEX first, с 2026-10-13: при наличии котировки MOEX стоимость = qty × MOEX, облигации — грязная + НКД; «Цена» баланса бывает устаревшей), а значение баланса всегда пишется в `per_security.json[ticker].balance_value_rub` для сверки. Флаг `--common` принимает **либо** `portfolio.json` (выход `parse_portfolio.py` из Шага 2 — берёт `stocks[].Стоимость` + `bonds[].Текущая стоимость`), **либо** `common_portfolio_*.xlsx` (экспорт IntelInvest). `.numbers` напрямую сюда не передавать — только распарсенный `portfolio.json`.

Детали и валидация (≤0.25 п.п. vs IntelInvest) — в `references/xirr-twr-calculation.md`.

Ставки в `per_security.json` — долями под ключами `*_frac` (`xirr_frac`: 0.2337 = 23.37%); сборщик читает их как есть.

**Свёртка недавних сделок (RPA Rule 3, 2026-08):** для каждого тикера скрипт также кладёт `recent_net_rub`/`recent_n_buys`/`recent_n_sells`/`recent_last_trade_date`/`recent_round_trip` — свёртку buy/sell-сделок за скользящее окно `[as_of − N дней; as_of]` (обе границы включительно). Ширина окна — `--recent-window-days` (default 60), параметр, не константа. Дивиденды/купоны/амортизации и Корректировки (Korrektirovka) в эту свёртку **не входят** (см. комментарий в `_compute_recent_window`). Направление (`recent_direction`: buy/trim/null) здесь ещё не классифицируется — для этого нужен порог, который знает только Шаг 6 (см. ниже).

---

### Шаг 4б. Доходность БКС-ИИС-3 (если есть его выгрузка)

Файл счёта — приложенный `trades_portfolio_838526*.xlsx`, иначе последний такой файл в
`Claude-Memory/Portfolio/inputs/<дата>/` (туда его кладёт импорт на сайте; Glob по Synology mount).
Папки на Mac (`docs/investment/source/`, «Загрузки») не искать — решение 2026-10-21: 16.10 там лежал
файл от 12.10, а свежий был в «Загрузках». Нет файла → расчёт пропускается, а Шаг 6 с `--snapshots-dir` **переносит блок `returns.by_account.iis_3` из последнего снапшота, где он есть** (в т.ч. из файла того же дня до перезаписи): `carried_from`/`carried_reason`, флаг `iis_returns_carried`; состав ИИС-3 разошёлся → warn `iis_composition_changed` — попроси свежую выгрузку. Детали — `references/output-schema.md`.
Отсутствие НОВОГО файла — норма: владелец выгружает его только после покупки/продажи/взноса на
счёте, купоны между выгрузками скрипт достраивает по графику MOEX сам.

```bash
python3 scripts/iis_returns.py --trades "$iis_trades_path" \
    --forecasts-dir "<Claude-Memory>/forecasts" --output /tmp/iis_returns.json
```

`--forecasts-dir` — путь инфляции для линкеров (Layer 1 `inflation-ru-*.yaml`; нет → 4%).
Сверка с балансом и смысл трёх чисел — `references/output-schema.md` → `returns.by_account.iis_3`.
При флаге `iis_returns_mismatch` попроси свежую выгрузку счёта: числа ИИС-3 в снапшот не попадут.

---

### Шаг 5. Текущие котировки (MOEX ISS)

Если список тикеров известен (из шагов 2 или 3):

```bash
# Health-check
python3 scripts/moex_quotes.py --health

# Если ok — получить котировки
python3 scripts/moex_quotes.py \
    --fields weekly \
    --from-portfolio /tmp/portfolio.json \
    --json > /tmp/quotes.json
```

Используй профиль `weekly` (I-1): для акций он отдаёт цену + `price_source`, для облигаций — полный bond-набор (купон, частота купона, номинал, НКД, дата след. купона, YTM, дюрация, оферта, погашение). Column-filter держит ответ компактным. Эти поля попадают в `holding`, и viewer читает их офлайн, без браузерного MOEX-fetch. Если MOEX недоступен — пометь в `data_quality_flags`, продолжай с `price_source: "last_trade"` (bond-поля останутся `null`).

---

### Шаг 6. Собери JSON-снапшот v2

**Перед сборкой найди предыдущий снапшот** в `Claude-Memory/Portfolio/snapshots/` (самый свежий `portfolio-*.json`, Glob по Synology mount) и скопируй его в `/tmp/prev_snapshot.json`. Он нужен для carry-over `first_appearance_date` (METH-2) и baseline кэш-расхождения (`cash_reconciliation`). Если предыдущего снапшота нет (первый прогон) — просто опусти `--prev-snapshot`.

**Также скопируй `Claude-Memory/sector-overrides.yaml` в `/tmp/sector-overrides.yaml`** (Read с Synology mount → Write в /tmp). Он закрывает дыры секторов: у части бумаг (SBERP, MOEX, NVTK, BTBR, новые IPO) в выгрузке IntelInvest сектора нет → без overrides в снапшоте будет `sector: null`, а на вкладке «Акции» вьюера — «unknown». Overrides только заполняют пустое (`sector` из «Общий баланс.numbers» имеет приоритет). PDL-I (2026-08-27): `sector` в снапшоте — ВСЕГДА машинный canon-ключ (словарь macro-forecast-chain/stress), даже для тикеров из overrides; отображаемый ярлык (словарь IntelInvest) пишется в ОТДЕЛЬНОЕ поле `sector_ru`, если задан в записи — два словаря больше не смешиваются в одном поле. Файла нет — просто опусти флаг.

```bash
TODAY=$(date +%Y-%m-%d)
python3 scripts/assemble_snapshot.py \
    --portfolio    /tmp/portfolio.json \
    --returns      /tmp/returns.json \
    --per-security /tmp/per_security.json \
    --quotes       /tmp/quotes.json \
    --output       /tmp/portfolio-${TODAY}.json \
    --trades       "$trades_path" \
    --balance      "$balance_path" \
    --prev-snapshot /tmp/prev_snapshot.json \
    --sector-overrides /tmp/sector-overrides.yaml \
    --snapshots-dir "<Claude-Memory>/Portfolio/snapshots" \
    --iis-returns  /tmp/iis_returns.json   # если был Шаг 4б; без него блок ИИС-3 переносится из прошлого снапшота
```

Скрипт обрабатывает все quirks автоматически:
- MOEX `last` vs `price`, xirr% → decimal, IIS-3 split, qty из returns, флаги
- Выводит краткое подтверждение: holdings count, XIRR restricted, кол-во флагов

**Порог направления недавних сделок (RPA Rule 3, 2026-08):** здесь, а не на Шаге 4, классифицируется `per_instrument_xirr[ticker].recent_direction` (buy/trim/null) — только здесь известна «акционная книга». По умолчанию порог = `--recent-net-threshold-pct` (default `1.0`, то есть 1 процентный пункт) от `balance_summary.goals_matrix[Валюта=RUB,Бумага=Акция]['Сейчас']`; если этой строки нет — fallback на тот же процент от `total_current_rub_excl_iis` (NAV); если и NAV нет — порог не считается, `recent_direction` остаётся `null` у всех тикеров (явно видно в `recent_trades_window.threshold_basis`, ничего не подставляется молча). `--recent-net-threshold-rub` — явный override в ₽ вместо расчёта. Ширина окна (`recent_trades_window.days`) берётся из уже посчитанного `per_security.json`, а не декларируется здесь заново (иначе могла бы разъехаться с шагом 4).

Если какой-то файл отсутствует (returns-only или holdings-only режим) — скрипт gracefully пропускает недостающий блок и ставит флаг `no_balance_file`. (`build_snapshot.py` без баланса вместо этого передаёт `--holdings-from-trades`: позиции из сделок, остальное из прошлого снапшота — `references/output-schema.md`, «Снапшот без баланса».)

**Настоящий кэш (`cash`, семантика 2026-07-08):** строка «Имеется (RUB)» баланса = весь портфель **включая ИИС-3, без заблокированных** (инвариант файла: «Итого» = Имеется + Пополнение). `cash.total_rub` = Имеется − стоимость всех незаблокированных holdings; `liquid_rub` = кэш + денежные фонды TMON/TPAY/LQDT (рабочее определение владельца «кэш + ликвидность»). Балансовый остаток `balance_summary.by_account.*.cash_rub` — «грязный» (содержит TPAY/TMON/FINAMAR, которых нет во вкладках баланса) — для кэша не использовать. FINAMAR — не кэш ни в каком смысле, обычная fund-позиция.

**Кэш-сверка (`cash_reconciliation`):** фактический кэш (`cash.total_rub`) сверяется с реконструкцией из трейдов. Историческое расхождение (~340 тыс. ₽ — пополнения прошлых лет вне экспорта, владелец в курсе; до фикса 2026-07-08 baseline был ~2,2 млн — артефакт двойного счёта ИИС и фондов) зафиксировано как baseline и НЕ является ошибкой — не поднимай его пользователю. Реагируй только на warning-флаг `cash_drift_changed` (новое расхождение > 10 тыс. ₽ против baseline): покажи его в сводке Шага 7 и подскажи проверить полноту выгрузки trades; если пользователь подтверждает осознанность изменения — перегони Шаг 6 с `--rebaseline-cash`. Первый прогон после фикса 2026-07-08 со старым prev-snapshot даст разовый `cash_drift_changed` — это ожидаемо, перегнать с `--rebaseline-cash`.

**Кэш без баланса (`cash_fact_stale`):** без «Общего баланса» кэш — оценка от последнего факта
(`cash.fact_date`: баланс или сумма владельца). Флаг `cash_fact_stale` (факт старше 14 дней) — спроси
владельца: «Сколько свободных денег в основном портфеле в IntelInvest (все валюты в рублях, без ИИС-3)?»
и пересобери с `--cash-fact <сумма>`: сумма станет фактом и опорой следующих сборок
(`cash.source = owner_intelinvest`). Кэш ИИС-3 вносится своим флагом `--cash-fact-iis <сумма>` (только рублёвый; подменяет перенос из прошлого снапшота). Не знает или отказался — сохраняй с оценкой, флаг останется в сводке.

**Статус позиции (SSOT, 2026-07):** каждый `holdings[]` получает каноническое поле `status` ∈ `normal | blocked | distressed` из реестра `KNOWN_POSITION_STATUS` в `scripts/assemble_snapshot.py`. Реестр поддерживается **ВРУЧНУЮ** — по аналогии с `KNOWN_SPLITS`: MOEX ISS статусы blocked/distressed автоматически не отдаёт. Ключ — ticker или ISIN; каждая non-normal запись обязана иметь `note` (дата + причина + ссылка на источник; если ссылка не проверена — писать в note «источник не верифицирован» явно) — она попадает в `holdings[].status_note`. `is_blocked` сохранён для обратной совместимости, но теперь **строго производный** (`status == "blocked"`). Доли стоимости по статусам — в `status_summary.by_status`; downstream (stress, integrated-view, coherence-audit) числа по blocked/distressed берёт **только оттуда**, не пересчитывает сам. При появлении новой distressed/blocked бумаги (дефолт, национализация, судебная блокировка выплат) — добавь запись в реестр и перегони снапшот.

В реестре уже лежат: **16 замороженных иностранных акций** (BAC…C, RTX, Z — СПб-биржа, санкционная заморозка 2022, оценка по котировке 21.02.2022) → `blocked`; **БорецКЗО26** (`RU000A105GN3`, национализация эмитента) → `distressed`. `FINAMAR` в реестр **не вносить** — российский фонд, владелец отслеживает его вручную (`cost_basis`-цена ≠ заморозка). Автоэвристики «`cost_basis` → blocked» нет сознательно: она ловила бы FINAMAR и пропускала RTX/Z (`last_trade`).

**Замороженные иностранные фонды и мелкие акции вне баланса** (FinEx FX*, РСХБ RSH*, TBIO, AXSM/JPM/DAL и т.п.): в реестр не вносятся — `portfolio_returns.classify_blocked` сам помечает их `is_blocked`, и `_build_blocked_positions` эмитит их в holdings со `status=blocked` из `returns.snapshot_current`. Владелец сознательно не вносит их в balance-файл — снапшот их всё равно видит (qty из трейдов). **Корректировки-синхронизации по замороженным бумагам фиктивны** («Корректировка количества на основе указанного баланса в загружаемом отчёте» — IntelInvest сверяет с отчётом брокера, а замороженные бумаги лежат на счетах, чьи отчёты не грузятся: 10.04.2026 синхронизация массово списала их qty; позиции живы — подтверждено владельцем 2026-07-04: FXUS 1504 на ВКС, TBIO на А-Инвестициях). Такие Корректировки **фильтруются в `apply_corrections`** только по blocked-бумагам (`ignored_blocked_corrections` в corrections_log); по обычным бумагам (MDMG, WUSH) и деньгам — применяются как раньше. **Оценка — консервативный 0** (default `--blocked-value zero`, warning-флаг в снапшоте): режим `last_trade` для FinEx ломается на сплит-парах (до-сплитовая цена × post-split qty, завышение до 100×). Бумажную стоимость сверять с IntelInvest вручную; честный 0 лучше выдуманной цифры. Коллизия тикеров: `T` (AT&T, USD) отбрасывается дедупом в пользу Т-Технологии.

Полная схема выходного JSON — в `references/output-schema.md`.

---

### Шаг 6а. Теневая сверка со скриптом (ВРЕМЕННО — API-1b, удалить при переключении)

Пока идёт теневой период (`docs/api-migration/implementation-brief.md`, «Теневой период»), каждый
прогон в **Claude Code на Mac** (в Cowork и упакованном скилле — пропустить) пишет пакет прогона,
и скрипт `build_snapshot.py` собирает снапшот на тех же ответах сети. Шаги 2–7 не меняются,
меняется только запуск команд:

1. **До Шага 2:** `eval $(python3 scripts/shadow_bundle.py init --as-of $TODAY)` → в `$B` путь пакета
   (локально, `~/.cache/claude-skills/pdl-parity/<дата>/`, не на Synology).
2. **Шаги 2–6:** каждую команду `python3 scripts/<скрипт>.py …` (и `moex_quotes.py`) запускай через
   обёртку `python3 scripts/netcache.py run --record "$B/net" -- scripts/<скрипт>.py …`.
3. **После Шага 6:** `python3 scripts/shadow_bundle.py finish --as-of $TODAY --trades "$trades_path"
   --balance "$balance_path" [--iis-trades …] --prev-snapshot /tmp/prev_snapshot.json
   --sector-overrides /tmp/sector-overrides.yaml --snapshots-dir "<Claude-Memory>/Portfolio/snapshots"
   --forecasts-dir "<Claude-Memory>/forecasts" --skill-snapshot /tmp/portfolio-${TODAY}.json`
   + `--skill-no-moex` / `--skill-cbr-offline` / `--rebaseline-cash`, если шёл с ними.
4. Покажи пользователю первую строку итога («✅ совпадает» / «❌ расходится: N») и путь
   `parity-report.md`. Расхождение — не повод не сохранять снапшот скилла: это материал для
   разбора в журнале теневого периода.

---

### Шаг 7. Предложи сохранить и сохрани

**Любой флаг severity `error` — НЕ сохранять и не передавать дальше:**
- `fx_rates_missing` — без курсов ЦБ валютные сделки посчитаны в 0 ₽, бумаги без курса — по стоимости покупки (не по курсу 1.0), текст называет валюту и бумагу
  (2026-10-21, Mac через VPN: XIRR −2,82% вместо 8,27%). Нужен доступ к cbr.ru (исключение в VPN или NAS).
- `returns_price_not_moex` — MOEX не отдал котировку при расчёте доходности, и бумага оценена по цене
  последней сделки (2026-10-22: TGLD 14,58 вместо 12,96 ₽ — XIRR +0,3 п.п., кэш −48 тыс.). Перезапусти
  `portfolio_returns.py`, когда MOEX отвечает, или собери снапшот на сайте («Снапшот» во вьюере).
- `per_instrument_price_not_moex` — то же для XIRR и результата по бумагам (`per_instrument_xirr`): акция
  или фонд оценены не по MOEX при котировке MOEX в holdings (2026-10-27: все бумаги по цене последней
  сделки, NVTK XIRR 26,1% вместо 22,7%). Собери снапшот на сайте.
Отсутствие error-флагов — не повод опустить сводку: перечисли warning-флаги о ценах
(`per_instrument_value_mismatch`, `moex_quotes_failed`), если они есть.

**Сразу после сборки снапшота (Шаг 6) проактивно спроси разрешение на сохранение — НЕ жди, пока пользователь сам напишет «сохрани», и не останавливайся молча с готовым JSON.** Покажи краткую сводку и вопрос:

> Снапшот собран: `portfolio-{date}.json` — N позиций, XIRR (restricted) XX%, флагов: K.
> Сохранить в Claude-Memory → `Portfolio/snapshots/auto/` (пробная папка)? (да / нет)

Рабочим снапшотом `Portfolio/snapshots/portfolio-<date>.json` штатно владеет сайт («Сохранить»); советник и прочие читатели берут рабочую папку и пробный снимок не видят. Скилл по умолчанию сохраняет в пробную папку: `build_snapshot.py --commit` пишет `auto/portfolio-<date>-<ЧЧММ>-skill.json` + `build-summary` рядом, рабочий снапшот и журнал решений не трогает. В рабочую папку — только по явной просьбе владельца («сохрани как рабочий», «в рабочую папку»): `--commit --working` (защита от ухудшения, `.versions/` — Шаги ниже; журнал решений пересоберёт сайт при следующем «Сохранить»). После пробного сохранения скажи, где файл лежит и что сделать, чтобы он стал рабочим.

При согласии — пиши **напрямую** (loader — исключение D3, save-to-library для снапшотов не нужен). Перед первой записью в сессии проверь доступ к своему рабочему корню (`SCOPE_ROOT` = `PORTFOLIO_SNAPSHOTS`, корень `Claude-Memory/` целиком не запрашивать): `Glob("portfolio-*.json", path=PORTFOLIO_SNAPSHOTS)`; если пусто/ошибка → `request_cowork_directory(path=PORTFOLIO_SNAPSHOTS)` (детали — `references/transport-layer.md`); не помогло → остановиться и сообщить пользователю.

Имя файла (lowercase, конвенция D4): `portfolio-{YYYY-MM-DD}.json`
Путь рабочего (только по явной просьбе): `Portfolio/snapshots/portfolio-{YYYY-MM-DD}.json`

**Снапшот за эту дату уже есть → сначала отложи старую версию (PDL-SNAPV), потом пиши:**
```bash
python3 scripts/archive_snapshot.py --snapshots-dir "{MEMORY_ROOT}/Portfolio/snapshots" --date {YYYY-MM-DD}
```
Старая версия уходит в `snapshots/.versions/portfolio-{date}.{generated_at}.json` (имя основного
файла не меняется — на него завязаны вьюер, советник, стресс и журнал). В подтверждении в чате
добавь строку: «Снапшот за {date} перезаписан; прежняя версия (собрана {generated_at}) — в
`.versions/`; обзоры, вышедшие до перезаписи, строились на ней». Кейс 16.10.2026: пересборка в
18:21 под тем же именем сделала обзоры акций и облигаций невоспроизводимыми по `snapshot_id`
(inc-2026-10-20-4).

Запись вручную (без `build_snapshot.py`) — тем же правилом: по умолчанию `Portfolio/snapshots/auto/portfolio-{today}-{ЧЧММ}-skill.json`, рабочее имя — только по явной просьбе.

```python
Write(f"{MEMORY_ROOT}/Portfolio/snapshots/portfolio-{today}.json",   # рабочий: только по явной просьбе
      content=json.dumps(snapshot, ensure_ascii=False, indent=2))
```

В чате — короткое подтверждение:
```
Снапшот сохранён: portfolio-{date}.json
schema_version: 2.0 | Позиций: N | XIRR (restricted): XX% | Флаги: [список или «нет»]
IE Model: N позиций | IE Summary: N in both, N not in IE
ИИС-3 (если был Шаг 4б): факт XIRR X% | к погашению сейчас Y% | зафиксировано Z% | статус сверки
```

Если пользователь отказался (ответил «нет») ИЛИ снапшот нужен только для передачи в другой скилл (advisor, scenario-stress) в этой же сессии — пропусти запись и верни JSON напрямую.

Журнал решений собирает сайт; на Маке скилл его не запускает. `--commit --working` отказывает (код 1, ничего не пишется), если сборка «только сделки» ложится поверх сохранённого снапшота того же дня с балансом или внесённым кэшем; осознанная перезапись — `--allow-downgrade` (прежняя версия уходит в `.versions/`).

`python3 scripts/numbers_to_plan.py --portfolio /tmp/portfolio.json --diff "$CM/Portfolio/plan.json"` — сверка плана с `plan.json`
(этап 1 ухода от Numbers); `build_snapshot.py` делает это сам при наличии `Portfolio/plan.json` (снапшот получает `plan_check`).

### Шаг 7г. Паритет «без баланса ↔ с балансом»

`build_snapshot.py` без баланса сам сверяет сборку поле за полем со снапшотом того же дня с балансом (`--parity-against PATH` или `{memory}/Portfolio/snapshots/portfolio-{as_of}.json`): блок `parity` в снапшоте и сводке (`diverged`, `diverged_paths`), отчёт `work/parity-report.md`, законные различия — `references/parity-known-diffs-nobalance.yaml`; расхождения не блокируют. «Сборки без расхождений» для решения §5.6 — файлы `Portfolio/snapshots/auto/build-summary-*.json` с `parity.diverged == 0`; переключение Numbers → план в балансном режиме (`--plan-primary` по умолчанию) — решение владельца: через месяц и не раньше трёх таких сборок.

### Шаг 7в. Старая проба сайта из `auto/` — рабочей

Сайт сохраняет в рабочую папку сам; шаг нужен только для старых проб из `auto/`.

Пользователь собирает на сайте → файл `Portfolio/snapshots/auto/portfolio-{date}-ЧЧММ-{bal|trades}.json`.
Проверь в нём: нет error-флагов, у акций и фондов `per_instrument_xirr[*].price_source` — `moex_iss`. Спроси
разрешение и замени рабочий снапшот: прежний рабочий того же дня (если есть) — копией
`auto/portfolio-{date}-skill-replaced.json`, затем сайтовая сборка → `Portfolio/snapshots/portfolio-{date}.json`,
Замену запиши в `Portfolio/decision-journal/incidents.yaml`
новой записью (старые не правятся).

---

## Технические особенности

Все quirks промежуточных форматов обрабатываются в `scripts/assemble_snapshot.py`. Для справки — что именно там закодировано:

| Quirk | Где обрабатывается |
|---|---|
| MOEX ISS field `LAST` (uppercase) → `last` в JSON | `assemble_snapshot._build_stocks` |
| `per_security.xirr` — **процент** (23.37), не decimal | `assemble_snapshot._build_per_instrument_xirr` |
| qty акций **из returns.json**, не из balance | `assemble_snapshot._build_stocks` |
| IIS-3 split: две holdings-записи для одного тикера | `assemble_snapshot._build_bonds` |
| Bond-обогащение (купон/частота/номинал/НКД/YTM/дюрация/оферта) из MOEX `weekly` (I-1) | `assemble_snapshot._build_bonds` |
| `coupon_freq_per_year` = `round(365 / COUPONPERIOD)` | `assemble_snapshot._coupon_freq` |
| Облигации в доходностях — **грязная** стоимость (цена + НКД), как покупки в trades; `ACCRUEDINT` в валюте **торгов** (`CURRENCYID`), у замещаек это рубли — к курсу номинала не домножать. `returns.parameters.bond_value_basis: "dirty"` (нет поля → старый `clean`, XIRR облигаций занижен) | `portfolio_returns.estimate_position_value_rub`, `_accrued_rub_of`; гейт `_check_balance_vs_trades_drift` второй раз НКД не добавляет |
| `quotes.json` приходит обёрткой `{quotes:{…}}` от `moex_quotes.py` CLI | `assemble_snapshot.main` (авто-разворот) |
| Русские имена колонок в `portfolio.json.stocks[]` | docstring `extract_portfolio` в `parse_portfolio.py` |
| `recent_direction` классифицируется НЕ в `per_security_xirr.py` — там только сырой `recent_net_rub` (порог знает только сборка снапшота, у неё есть `goals_matrix`) | `assemble_snapshot._derive_recent_net_threshold`, `_build_per_instrument_xirr` |
| `recent_trades_window.days` — эхо реально применённого окна из `per_security.json`, не отдельный CLI-параметр (иначе мог бы разъехаться со Шагом 4) | `assemble_snapshot._recent_window_days_from_per_security` |

---

## Anti-patterns

❌ **Добавлять интерпретации.**
Плохо: `"XIRR 15% — хороший результат, выше ключевой ставки"`.
Хорошо: `"xirr": 0.15`. Интерпретация — в advisor.

❌ **Заполнять пустые поля "по памяти".**
Плохо: `"ytm": 14.5` без источника.
Хорошо: `"ytm": null, "ytm_source": "unavailable"` + флаг в `data_quality_flags`.

❌ **Давать рекомендации.**
Плохо: `"Рекомендуется ребалансировать в пользу облигаций"`.
Этот скилл не даёт рекомендаций — это задача advisor.

❌ **Молча пропускать ошибки парсинга.**
Плохо: вернуть неполный снапшот без предупреждения.
Хорошо: каждая проблема → в `data_quality_flags` с описанием и шагом, где возникла.

❌ **Запускать Extended Search / Deep Research.**
Скилл не исследует рынок. Все данные из файлов пользователя и MOEX ISS.

---

## Когда читать references

- `transport-layer.md` — Шаг 0, один раз в начале сессии
- `parsing-numbers.md` — Шаг 2, если структура Numbers-файла неожиданная
- `parsing-intelinvest.md` — Шаг 3, если trades.xlsx ведёт себя нестандартно
- `splits-corrections.md` — Шаги 3–4, если видишь аномальные qty или новый сплит
- `xirr-twr-calculation.md` — Шаги 3–4, для понимания методологии и валидации
- `output-schema.md` — Шаг 6, при сборке снапшота
- `decision-journal.md` — просьбы про журнал решений / теневые базы

---

## Структура файлов скилла

```
portfolio-data-loader/
  SKILL.md                          ← этот файл
  references/
    transport-layer.md              ← Synology mount, Portfolio/snapshots/ пути
    parsing-intelinvest.md          ← формат trades_portfolio_*.xlsx
    parsing-numbers.md              ← формат Общий баланс.numbers
    splits-corrections.md           ← таблица сплитов и логика Корректировки
    xirr-twr-calculation.md         ← формулы, валидация, ограничения
    output-schema.md                ← JSON-схема снапшота v2 с примером
    cbr_rates_bundled.json          ← исторические курсы ЦБ РФ 2019→релиз
  scripts/
    parse_portfolio.py              ← парсер Numbers/xlsx → JSON (v2: ie_model, ie_actual, ie_summary)
    portfolio_returns.py            ← XIRR/TWR/ROI + per-type breakdown
    per_security_xirr.py            ← XIRR по отдельным тикерам
    moex_quotes.py                  ← котировки MOEX ISS
    assemble_snapshot.py            ← сборка финального JSON v2 из 4 промежуточных файлов
    build_snapshot.py               ← API-1b: Шаги 1–7 одной командой без LLM (теневой период)
    numbers_to_plan.py              ← portfolio.json ↔ plan.json, сверка плана (этап 1 ухода от Numbers)
    checks.py                       ← API-1b: проверки целостности (block / warning / info)
    netcache.py                     ← API-1b: запись/повтор ответов сети (пакет прогона)
    parity_check.py                 ← API-1b: сверка двух снапшотов поле за полем
    shadow_bundle.py                ← API-1b: пакет прогона скилла (Шаг 6а, временно)
```
