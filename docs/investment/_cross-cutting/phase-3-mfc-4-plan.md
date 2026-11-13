# План реализации: Фаза 3 (SS-1) + MFC-4

> **Тип:** PLAN / handoff · **Создан:** 2026-06-09 · **Статус:** готов к реализации, код не тронут
> **Контекст:** документ самодостаточен — рассчитан на исполнение в **свежей сессии (Sonnet)**
> без предварительно загруженного контекста. Все факты заземлены на реальные артефакты
> Claude-Memory и текущий код (пути и номера строк — на 2026-06-09, могли сместиться —
> ориентируйся также на имена функций/якорей).

## Решения зафиксированы (не пересматривать без явной причины)

| # | Решение | Выбор |
|---|---------|-------|
| **D-A** | MFC-4: как эмитить L1-движение фактора | **A′** — macro-marginal хранит числовой **уровень + единицу**, % движения считает **consumer** (`aggregate_positions`) против `baseline_spot` из stress. Единая база с L2 → корректный `coherence_gap`. |
| **D-B** | SS-1: чем считать OLS | **`numpy.linalg.lstsq`**. Зафиксировать numpy как зависимость в корневом `CLAUDE.md` рядом с `numbers-parser`/`openpyxl`. |
| **D-C** | SS-1: sanctions/geopol | **Оставить priors**, регрессией НЕ покрывать (событие-0/1 не сопоставимо с индексом эскалации `[-1..+1]` сценария). |

---

## 0. Зачем вместе и общий стержень — контракт единиц фактора

Фаза 3 (SS-1) и MFC-4 — в разных скиллах и независимы по коду, но завязаны на **один
контракт**: в каких единицах живёт «движение фактора», на которое умножаются `factor_betas`.

- **SS-1** производит `factor_betas` через регрессию — β обязаны быть в этих единицах.
- **MFC-4** должен эмитить числовое движение фактора для Layer 1 — в тех же единицах.
- `aggregate_positions` умножает β × движение и сравнивает L1 с L2 (`coherence_gap`).

Контракт подтверждён из боевого `Claude-Memory/Portfolio/stress/stress-2026-05-29-shell-d1-2026.yaml`,
блок `baseline_spot`:

```yaml
baseline_spot:
  brent_usd: 94.11
  usdrub: 71.38
  cnyrub: 10.475
  cbr_rate_pct: 14.5
  note: факторы сценариев = % отклонение от этого спота; cbr_rate в п.п.
```

### Таблица единиц (SSOT — зафиксировать в Шаге 0.1)

| Фактор | Единица движения (то, на что умножается β) | Перевод «уровень → движение» |
|---|---|---|
| `brent`, `usdrub`, `cnyrub`, `xauusd` | **% отклонения от `baseline_spot`** | `(level − spot) / spot × 100` |
| `cbr_rate` | **процентные пункты (п.п.)** | `target_pct − baseline_cbr_rate_pct` (14.5) |
| `sanctions`, `geopol` | индекс эскалации `[-1..+1]` | **нет числового уровня** → в L1 не участвуют (остаются качественной строкой, штатно пропускаются guard'ом) |

**Почему движение считаем против `baseline_spot`, а не против спота на дату цепочки:**
L2-факторы в stress — «% отклонение **от `baseline_spot`**». Чтобы `coherence_gap = |L1 − L2|`
имел смысл, L1-движение должно считаться **против той же базы**. Поэтому уровень→движение
переводит `aggregate_positions` (он и так грузит stress с `baseline_spot`), а не producer.
Это и есть суть решения **D-A = A′**.

Пример (brent, горизонт 2026): macro-marginal даёт уровень `$68/bbl`,
stress `baseline_spot.brent_usd = 94.11` → движение `(68 − 94.11)/94.11 × 100 = −27.7%`,
далее `β_brent × (−27.7)` на позицию.

### Шаг 0.1 — задача
- Внести таблицу единиц как SSOT в `_shared-references/events-yaml-spec.md` (§5, рядом с
  `conditional_on_scenarios`).
- Сослаться на неё из `skills/macro-forecast-chain/references/macro-input-schema.md` и
  `skills/portfolio-scenario-stress/references/input-adapters.md` (раздел «Канонические имена факторов»).
- **Сложность:** S. Делается первым — обе задачи на неё ссылаются.

---

## 1. MFC-4 — числовое движение фактора в macro-marginal (Сложность M)

**Цель:** разблокировать живой Layer 1 в `portfolio-integrated-view` на реальных данных
(`acceptance` IV-E). Сейчас механика L1 готова и протестирована, но не включается:
в `macro-marginal-{date}.yaml` все оценки — человекочитаемые **строки-уровни**.

### Реальное состояние данных (заземление)
`Claude-Memory/macro-chain/macro-marginal-2026-05-11.yaml`, фактор brent:
```yaml
  brent:
    type: conditional_estimate
    central_estimate_l1_2026: "$68/bbl (JPMorgan-dominant weighted median)"
    central_estimate_l2_ev_2026: "$80/bbl (D1 EV: ...)"
    central_estimate_l1_2027: "$57/bbl"
    central_estimate_l2_ev_2027: "$71/bbl"
```
То есть: (а) строка, не число; (б) **уровень**, а не движение; (в) суффикс горизонта `_<год>`.

### Реальное состояние consumer (заземление)
`skills/portfolio-integrated-view/scripts/aggregate_positions.py`, `aggregate_macro()`
(строки ~242–306). L1-блок (строки ~266–296) читает **плоский** ключ `central_estimate`
и умножает его как число:
```python
ce = fcast.get("central_estimate") if isinstance(fcast, dict) else fcast
if not _is_number(ce):
    continue            # нечисловой central_estimate → не L1-вход
beta_key = MACRO_FACTOR_ALIASES.get(f, f)   # MACRO_FACTOR_ALIASES (строки 53–58): {"geopolitics": "geopol"}
beta = factor_betas.get(beta_key) ...
l1_terms.append(float(beta) * float(ce))
```
**Проблема даже на стороне consumer:** ключа `central_estimate` в реальном файле нет
(там `central_estimate_l1_2026` и т.п.), горизонт не выбирается, уровень не переводится в движение.

### 1A. Producer — `macro-forecast-chain`
macro-marginal собирается LLM на Шаге 8 (отдельного Python-эмиттера нет; скрипты скилла —
только `coverage_report.py` и `recalibrate.py`). Чтобы не было ручной арифметики у LLM
(принцип репозитория), добавить детерминированный хелпер:

- **Новый** `skills/macro-forecast-chain/scripts/compute_marginal_move.py`:
  - вход: строка FCA нужного горизонта (`"$68/bbl (...)"`, `"88 руб./$"`, `"12% к 2026-12-31"`) + фактор;
  - парсит **число + единицу**, эмитит рядом с человекочитаемым `central_estimate_l1_<год>` машинные поля:
    ```yaml
    brent:
      level_l1_2026: 68
      unit: usd_per_bbl        # usd_per_bbl | rub_per_usd | rate_pct | pct_yoy | ...
      level_l1_2027: 57
    ```
  - sanctions/geopol — числового уровня нет, поля не эмитятся (остаются строкой).
- В `skills/macro-forecast-chain/SKILL.md` (Шаг 8b) и `references/macro-input-schema.md`:
  задокументировать `level_l1_<год>` + `unit`, сослаться на таблицу единиц Шага 0.1.

### 1B. Consumer — `portfolio-integrated-view`
- `aggregate_positions.py` → `aggregate_macro()`:
  - читать **горизонт-суффиксный** `level_l1_<год>` + `unit` (а НЕ плоский `central_estimate`);
  - выбирать `<год>` по горизонту прогона: ближайший `chain_target_horizon` к `as_of + horizon_months`
    (горизонт в `aggregate_div_or_carry` и др. передаётся как `horizon_months`);
  - конвертировать `уровень → движение` против `baseline_spot` из stress по таблице Шага 0.1
    (для cbr_rate — п.п. = `target − 14.5`; для brent/usd/cny/xau — `% от спота`);
  - guard на нечисловое + `MACRO_FACTOR_ALIASES` сохранить; при необходимости расширить алиасы
    (`urals_discount`, проверить `cbr_rate` vs ключ беты).
  - `coherence_gap = |L1 − L2|` (L2 = `expected_pct_pweighted` из stress) — логика уже есть.
- `skills/portfolio-integrated-view/SKILL.md` (строки ~56–61): **снять** блок
  «⚠ Текущее ограничение (Phase 1)» и описать новый контракт (читаем `level_l1_<год>`+`unit`,
  переводим против `baseline_spot`).

### 1C. Тесты
- Расширить `skills/portfolio-integrated-view/tests/test_aggregate_positions.py`:
  - L1 на формате `level_l1_<год>` + `unit` (brent в %, cbr_rate в п.п.);
  - выбор горизонта (2026 vs 2027) по `horizon_months`;
  - перевод уровень→движение против `baseline_spot`;
  - `coherence_gap` присутствует и числовой;
  - fallback на L2 при отсутствии `level_l1_*`/`baseline_spot` (backward-compat).
- Юнит-тест парсера `compute_marginal_move.py` на реальных строках:
  `"$68/bbl (JPMorgan-dominant weighted median)"` → `68`/`usd_per_bbl`;
  `"88 руб./$"` → `88`/`rub_per_usd`; `"12% к 2026-12-31"` → `12`/`rate_pct`.

### 1D. Acceptance (из TODO MFC-4)
- [ ] На реальном `macro-marginal-{date}.yaml` integrated-view выдаёт `layer: L1` +
      `coherence_gap` хотя бы по факторам с betas.
- [ ] E2E IV-E (Шаг 2) на реальных данных даёт L1, а не пустой `macro_marginal`.

---

## 2. Фаза 3 / SS-1 — эмпирические `factor_betas` по регрессии MOEX (Сложность L)

**Цель:** заменить ручные priors на β из 24 мес истории MOEX; `macro_blindspot` определять
автоматически через `R² < 0.3`, а не хардкод-списком.

### Реальное состояние кода (заземление)
`skills/portfolio-scenario-stress/scripts/compute_per_position.py`:
- `CANONICAL_FACTORS` (строка 31): `["sanctions","geopol","cbr_rate","usdrub","cnyrub","brent","xauusd"]`.
- `IDIOSYNCRATIC_TICKERS` (строки 39–45): хардкод MDMG/PRMD/OZON/WUSH/DOMRF. Комментарий уже
  гласит «в Phase 4.2 станет необязательным (automatic detection через r2 < 0.3)».
- moex-режим (строки 170–175): **заглушка** — печатает warning «not implemented» и
  откатывается на priors.
- `is_macro_blindspot()` (строки 133–142): **уже** ставит blindspot при `r2 < 0.3` и при
  всех `|β| < 0.1` — обвязка готова, нужно наполнить `r2`.
- `ci_from_delta()` (строки 119–130): **уже** масштабирует CI по `1/sqrt(r2)` — заработает, как
  только `r2` перестанет быть `null`.
- argparse `--regression-mode {priors,moex}` (строки 342–347): флаг есть.

### 2A. Движок регрессии (`compute_per_position.py`)
- `fetch_moex_history(ticker, months=24)` — по образцу `moex_quotes.py` (батч-запросы к ISS),
  эндпоинт `iss.moex.com/iss/history/engines/stock/markets/shares/securities/{ticker}.json`
  → ряд **месячных доходностей**.
- Факторные ряды-регрессоры в **единицах контракта Шага 0.1**:
  `oil_return` (Brent, % мес), `usd_change` (USD/RUB, % мес), `cnyrub_change` (% мес),
  `cbr_rate_change` (Δ, п.п.).
- OLS через `numpy.linalg.lstsq` (D-B): `monthly_return ~ oil + usd + cnyrub + Δrate`
  → `factor_betas` + `factor_betas_r2`.
- Записывать `factor_betas_r2` (сейчас всегда `null`); `r2 < 0.3` → авто `macro_blindspot`
  (логика уже есть). Хардкод `IDIOSYNCRATIC_TICKERS` оставить как опциональный fallback,
  не как первичный источник.
- Заменить заглушку moex (строки 170–175) реальной реализацией; на сетевой сбой / нехватку
  истории — graceful fallback на priors конкретного тикера + warning (не падать целиком).

### 2B. Sanctions timeline
- **Новый** `skills/portfolio-scenario-stress/references/sanctions-timeline.yaml` — бинарный ряд
  дат эскалации/деэскалации (ручной регрессор).
- **Дизайн-нюанс (D-C):** `sanctions_binary` (0/1) не сопоставим с контрактным `sanctions`-индексом
  `[-1..+1]`. Поэтому `sanctions` и `geopol` **оставляем на priors**, OLS даём только по
  непрерывным рыночным факторам (brent/usdrub/cnyrub/cbr_rate). Это когерентно: авто-R²-blindspot
  срабатывает ровно там, где регрессия слаба (idiosyncratic-позиции).
- (Опц.) Если позже захочется — sanctions-timeline можно использовать как контрольную dummy
  в регрессии для других факторов, но **не** как источник `sanctions`-беты.

### 2C. Зависимости и тесты
- Зафиксировать `numpy` в корневом `CLAUDE.md` (секция «Зависимости»): рядом с
  `numbers-parser`/`openpyxl`; установка `pip install numpy --break-system-packages`.
- Тестов у `portfolio-scenario-stress` для `compute_per_position.py` **нет** (есть только
  `tests/test_build_stress_stub.py`). Завести `tests/test_compute_per_position.py`:
  - OLS на синтетике с известными β/R² (проверка восстановления коэффициентов);
  - units-санити (β в правильных единицах: %stock/%oil, %stock/п.п. для rate);
  - `r2 < 0.3 → macro_blindspot: true` автоматически;
  - graceful при недоступном ISS → fallback на priors без краша;
  - **офлайн-фикстуры** истории (без сети — замокать `fetch_moex_history`).
  - Зарегистрировать тест в корневом `CLAUDE.md` (секция «Запуск тестов»).

### 2D. Acceptance (из TODO SS-1)
- [ ] stress использует эмпирические β из 24 мес MOEX истории вместо ручных priors
      (режим `--regression-mode moex` работает, не заглушка).
- [ ] `factor_betas_r2` заполнен в выходном JSON (не `null`).
- [ ] `macro_blindspot` определяется автоматически через `R² < 0.3` (не хардкод-список).

---

## 3. Порядок и зависимости

```
Шаг 0.1  Контракт единиц (SSOT)  ── общий, делается первым (S)
   │
   ├── MFC-4 (M)  → разблокирует L1 на реальных данных (IV-E acceptance)
   │                 работает на priors-β уже сейчас
   │
   └── SS-1 / Фаза 3 (L) → улучшает те же factor_betas, что потребляет L1
                            ⇒ L1 автоматически точнее, без переделки MFC-4
```

**Рекомендуемый порядок: Шаг 0.1 → MFC-4 → SS-1.**
- MFC-4 меньше (M) и даёт немедленный выигрыш (живой L1 + `coherence_gap`).
- SS-1 крупнее (L) и питает те же `factor_betas`, что L1 потребляет, — поэтому MFC-4 на
  priors-бетах **не придётся переделывать**, когда SS-1 заменит их на эмпирические.
- Задачи можно вести параллельно (разные скиллы), общий — только Шаг 0.1.

---

## 4. Acceptance / команды проверки

```bash
# python3 = ~/.pyenv/versions/3.12.9/bin/python3 (дефолтный python3 сломан, см. memory)

# MFC-4 (расширить существующий тест):
~/.pyenv/versions/3.12.9/bin/python3 skills/portfolio-integrated-view/tests/test_aggregate_positions.py
~/.pyenv/versions/3.12.9/bin/python3 skills/macro-forecast-chain/tests/test_compute_marginal_move.py   # новый

# SS-1 (новый тест):
~/.pyenv/versions/3.12.9/bin/python3 skills/portfolio-scenario-stress/tests/test_compute_per_position.py
```
E2E-приёмка MFC-4 — прогнать integrated-view на боевых
`macro-marginal-2026-05-11.yaml` + `stress-2026-05-29-*.yaml`, убедиться, что в выводе
`layer: L1` и `coherence_gap` по brent/usdrub/cnyrub.

---

## 5. Заземляющие факты (для быстрой верификации в новой сессии)

**Реальные артефакты Claude-Memory** (`~/Library/CloudStorage/SynologyDrive-home/Ext_gDrive/Claude-Memory/`):
- `macro-chain/macro-marginal-2026-05-11.yaml` — L1-строки-уровни (`central_estimate_l1_2026: "$68/bbl …"`),
  `schema_version: 2`, `type: macro-marginal`, факторы: geopolitics, sanctions, brent, urals_discount, usdrub, …
- `macro-chain/macro-input-2026-05-29.yaml` — свежий macro-input.
- `Portfolio/stress/stress-2026-05-29-shell-d1-2026.yaml` — `baseline_spot` (brent_usd 94.11,
  usdrub 71.38, cnyrub 10.475, cbr_rate_pct 14.5), `factors` по сценариям в % отклонения,
  `per_position.<TICKER>.factor_betas` (пример SBER: brent 0.15, cbr_rate −0.2, sanctions −0.35).

**Ключевые файлы кода:**
- `skills/portfolio-integrated-view/scripts/aggregate_positions.py` — `aggregate_macro()`,
  `MACRO_FACTOR_ALIASES`.
- `skills/portfolio-integrated-view/SKILL.md` — macro-marginal как опц. 4-й вход + блок
  «Phase 1 ограничение» (снять).
- `skills/portfolio-scenario-stress/scripts/compute_per_position.py` — moex-заглушка,
  `IDIOSYNCRATIC_TICKERS`, `is_macro_blindspot`, `ci_from_delta`.
- `skills/macro-forecast-chain/SKILL.md` (Шаг 8b) + `references/macro-input-schema.md`.
- SSOT факторов/единиц: `_shared-references/events-yaml-spec.md` §5.

---

## 6. Конвенции репозитория (соблюдать при реализации)

- **Язык — русский** везде (код-комментарии, доки, коммиты, тесты).
- **Никакой ручной арифметики у LLM** — числа считают детерминированные Python-скрипты
  (поэтому `compute_marginal_move.py`, а не «LLM посчитает % движения»).
- **D3:** скиллы (кроме save-to-library/maintenance) в `Claude-Memory/` напрямую не пишут —
  выдают артефакт в чат. Исключение — portfolio-data-loader. MFC-4/SS-1 этого не меняют.
- **Сценарная независимость:** факторные зависимости в скиллах OK, сценарно-специфическая
  логика — нет.
- **Схемы/контракты:** при смене формата либо мигрировать данные, либо backward-compat в коде;
  перед правкой grep'ом проверить реальные артефакты в Claude-Memory. Здесь: новые поля
  `level_l1_<год>`/`unit` — **аддитивные**, старые строки сохраняются → consumer должен иметь
  fallback на L2 при их отсутствии.
- **Коммиты** — группировать по смыслу (код / тесты / доки отдельными коммитами;
  сначала код, потом тесты, потом доки).
- **Тесты** — гонять через `~/.pyenv/versions/3.12.9/bin/python3`, регистрировать новые в
  корневом `CLAUDE.md` (секции «Запуск тестов» и «Зависимости»).

---

## 7. Обновления документации (по завершении)
- `docs/investment/TODO.md`: SS-1 снять `DEFERRED` → `IN PROGRESS/DONE`; MFC-4 — отметить acceptance.
- Корневой `CLAUDE.md`: добавить numpy в зависимости; зарегистрировать 2 новых теста.
- `skills/*/SKILL.md` + `references/*` — по разделам 0.1/1A/1B/2A/2B выше.
