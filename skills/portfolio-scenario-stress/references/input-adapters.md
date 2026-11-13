# Input Adapters — Нормализация прогнозных входов

Скилл принимает три типа прогнозных входов (A, B, C) и гибрид. Этот файл описывает, как конвертировать каждый тип в **единый internal format** — список сценариев с нормализованными факторами и вероятностями.

После нормализации вся расчётная логика работает с одним форматом.

---

## Канонические имена факторов (что ждёт скрипт)

Скрипт `scripts/compute_per_position.py` (строка 31) ожидает в каждом сценарии
ровно эти ключи в `factors:`:

```
CANONICAL_FACTORS = ["sanctions", "geopol", "cbr_rate", "usdrub", "cnyrub", "brent", "xauusd"]
```

Любые другие имена в `scenarios[*].factors` скрипт **молча игнорирует** —
`factors.get(f, 0)` вернёт 0, и `delta_pct` для всех позиций будет 0 без
warning. Это самый частый баг.

**Schema v2 (Phase 4 — multiple horizons):** в v2 факторы живут не в плоском
`factors:`, а в `scenarios[*].factors_by_horizon.{hNN}:` — те же канонические ключи,
но отдельный набор % delta на каждый горизонт `hNN`. Полная спека —
`references/yaml-schemas.md` §11.2. `factors_by_horizon` рекомендуется
строить детерминированно из per-year уровней FCA через `compute_horizon_factors.py`
(он же отдаёт `horizon_coverage` — coverage-чек + CI-инфляция при экстраполяции
года). v1-вход с плоским `factors:` `compute_per_position.py` принимает →
оборачивает в один горизонт (`by_horizon.{h20}`) + warning.

**Единицы факторов (SSOT — `references/events-yaml-spec.md` §5.6):**
`brent`/`usdrub`/`cnyrub`/`xauusd` — **% отклонение от `baseline_spot`**;
`cbr_rate` — **п.п.** (= `target − baseline_cbr_rate_pct`, напр. `-3.5` при ставке
11.0 от базы 14.5); `sanctions`/`geopol` — индекс эскалации `[-1..+1]` (`+1` =
ужесточение, `−1` = смягчение), задаётся **путём по горизонтам**, а не скаляром
(P0-2). Эти же единицы
обязательны для эмпирических `factor_betas` из OLS (`--regression-mode moex`): регрессоры
строятся ровно в них (см. ниже «Эмпирические беты»).

**Mapping** internal-format (исторические имена в формулах
`bonds-sensitivity.md` / `sector-sensitivities.md` / `fund-decomposition.md`)
→ canonical (что подаётся в скрипт):

| Internal-format (в формулах ниже) | Canonical (в `scenarios-fragment.yaml`) | Единицы |
|---|---|---|
| `brent_pct_change` | `brent` | % изменение |
| `rate_bps_change` / `rate_pp_change` | `cbr_rate` | **п.п.** (>0 = рост ставки ЦБ); канон §5.6 — п.п., НЕ bps |
| `usdrub_pct_change` | `usdrub` | % изменение USD/RUB |
| `cnyrub_pct_change` | `cnyrub` | % изменение CNY/RUB |
| `sanctions_escalation` (bool) | `sanctions` | интенсивность `[-1..+1]`; bool `true` → оценить величину пакета по шкале, не подставлять `1` механически |
| `geopol_escalation` (bool) | `geopol` | интенсивность `[-1..+1]`, там же |
| `xauusd_pct_change` | `xauusd` | % изменение XAU/USD |

**Не поддержаны скриптом** (упоминаются в формулах, но игнорируются при
расчёте): `urals_discount_chg`, `urals_discount_usd`, `cbr_rate_absolute`,
`inflation_ru_pct`, `budget_deficit_gdp_pct`. Если эти факторы важны для
сценария — отразить через β и `cbr_rate` / `brent` (ставка определяет реакцию
на инфляцию; brent ± urals_discount определяет реальную выручку нефтяников).

**Поток данных:**

```
macro-forecast-chain → macro-input-{date}.yaml (internal-format с _pct_change)
       ↓ LLM делает rename по таблице выше
scenarios-fragment.yaml (canonical имена)
       ↓
compute_per_position.py (читает canonical)
       ↓
Portfolio/stress/stress-{date}-{src}.yaml (canonical в factor_betas и factors)
```

---

## Эмпирические беты — `--regression-mode moex` (SS-1)

По умолчанию `compute_per_position.py` берёт `factor_betas` из `betas-priors.json`
(`--regression-mode priors`). Флаг `--regression-mode moex` считает беты **эмпирически**
через OLS (`numpy.linalg.lstsq`) на 24 мес истории:

| Регрессор | Источник | Единица (контракт §5.6) |
|---|---|---|
| `brent` | MOEX FORTS, фьючерсы `BR` (near-expiry month-end) | % мес. |
| `usdrub` | **офиц. курс ЦБ** (`XML_dynamic`, R01235) | % мес. |
| `cnyrub` | **офиц. курс ЦБ** (R01375) | % мес. |
| `cbr_rate` | ЦБ KeyRate (SOAP) | Δ п.п. мес. |

`monthly_return_акции ~ const + Σ β_f · factor_f` → `factor_betas` + `factor_betas_r2`.

**Почему FX из ЦБ, а не MOEX:** биржевые торги USD/RUB (`USD000UTSTOM`) приостановлены
с июня 2024 (санкции на Мосбиржу) — MOEX отдаёт нулевой `CLOSE`. Официальный курс ЦБ —
надёжный непрерывный источник для обоих FX.

**Единицы `factor_betas` (контракт P0-1):** β — п.п. цены на ОДНУ единицу фактора
в его собственной единице. Для `sanctions`/`geopol` единица — интенсивность 1.0,
поэтому политическая бета банка ≈ −35, а не −0.35. Долевая запись отличается ×100
и зануляет политический канал; `compute_per_position.py` отказывается считать
(`--political-scale-check`). SSOT — `sector-sensitivities.md` → «Контракт единиц».

**`sanctions`/`geopol` — НЕ регрессируются (D-C):** событие-0/1 не сопоставимо с
контрактным индексом эскалации `[-1..+1]`. Их беты остаются из priors. Аналогично любой
фактор, чей ряд не удалось построить (сеть/ISS), сохраняет prior-бету.

**Автоматический `macro_blindspot`:** при `R² < 0.3` позиция помечается idiosyncratic
автоматически (хардкод-список `IDIOSYNCRATIC_TICKERS` становится необязательным fallback).
CI масштабируется ~`1/√R²` — низкий R² → шире доверительный интервал.

**Статистические оговорки (важно):** беты из 24 мес монтли-данных **шумные**.
- `usdrub` и `cnyrub` сильно коррелированы (обе = ослабление рубля) → мультиколлинеарность,
  индивидуальные беты могут иметь противоположные знаки (совместный эффект устойчивее, чем
  каждая по отдельности).
- `cbr_rate` — почти ступенчатая константа (≈8 изменений за 24 мес) → бета слабо
  идентифицирована.
- **Доверять следует `R²` и совместному эффекту, а не отдельным β.** Низкий R² → blindspot →
  модель сама сигналит о ненадёжности. Это by-design: SS-1 заменяет ручную калибровку на
  data-driven оценку с явным флагом неуверенности, а не на «точные» беты.

**Гард качества данных:** месяцы с экстремальной доходностью (|return| > 100% —
неадаптированный сплит/реорганизация, напр. реверс-сплит VTB 2024 → +462624% за месяц)
исключаются из регрессии; если бета всё равно вырождена (|β| > 15 — почти сингулярная
матрица, короткая история) → откат на priors тикера. Без гарда такой выброс отравил бы
`expected_pct` на тысячи % и портфельные агрегаты.

**Робастность:** все сетевые вызовы best-effort. Сбой по тикеру/фактору → graceful fallback
на priors + warning, run целиком не падает. priors-режим (default) этим блоком не затронут.
Требует `numpy` + сеть; без `numpy` moex деградирует в priors с предупреждением.

---

## Internal Format (целевой)

```json
[
  {
    "label": "string — название сценария или кейса",
    "probability": 0.25,
    "factors": {
      "brent_pct_change":    -20.0,   // % изменение цены Brent
      "urals_discount_chg":  5.0,     // изменение дисконта Urals-Brent, п.п. (>0 = рост дисконта = хуже для РФ)
      "rate_bps_change":     200,     // изменение ставки ЦБ РФ, базисные пункты (>0 = рост)
      "usdrub_pct_change":   15.0,    // % изменение USD/RUB (>0 = ослабление рубля)
      "cnyrub_pct_change":   12.0,    // % изменение CNY/RUB (>0 = ослабление рубля к юаню)
      "sanctions_escalation": false,  // bool: новый пакет санкций (SDN + sectoral)
      "geopol_escalation":   false,   // bool: эскалация конфликта / геополитическая напряжённость
      "xauusd_pct_change":   null,    // % изменение XAU/USD — для TGLD, PLZL; null если не задан
      "urals_discount_usd":  null,    // абсолютный дисконт Urals к Brent, USD (альтернатива chg; из macro-forecast-chain)
      "cbr_rate_absolute":   null,    // абсолютное значение ставки ЦБ, % — для контекстного β банков
      "inflation_ru_pct":    null     // абсолютный уровень инфляции РФ, % — для реальной доходности облигаций
    },
    "confidence": "high" | "medium" | "low",
    "source": "scenario-builder" | "forecast-confidence-applier" | "hypothesis-stress-tester" | "manual",
    "weight_type": "equal" | "probability",
    "notes": "опциональные комментарии о допущениях"
  }
]
```

**Незаполненные факторы** = `null` (фактор не присутствует в сценарии, β не применяется).
**Нулевые значения** = явный "нет изменения" (β применяется и даёт 0).

---

## Тип A: scenario-builder (4 Shell-сценария)

**Характеристика:** 4 равновероятных сценария по двум осям неопределённости. Явных вероятностей нет — это методологическое допущение метода Shell.

**Откуда берётся вход:**
- Текстовый нарратив из session (пользователь передаёт результат scenario-builder)
- Или YAML-блок `scenario_triggers` из Events YAML в конце вывода scenario-builder

**Алгоритм конвертации:**

1. Определить 4 сценария (A, B, C, D) из матрицы 2×2
2. Из нарратива каждого сценария извлечь ключевые факторы:
   - «нефть $55–60» → `brent_pct_change = (avg/base - 1) × 100`
   - «ставка снизится до 14%» → `rate_bps_change = (14 - current_rate) × 100` (отрицательное значение)
   - «рубль ослабнет до 120» → `usdrub_pct_change = (120/current - 1) × 100`
   - «санкционный пакет» → `sanctions_escalation = true`
3. Установить `probability = 0.25` для каждого сценария
4. Установить `weight_type = "equal"`
5. `confidence` — оценить по насыщенности нарратива конкретными цифрами: high (есть числа) / medium (направление без чисел) / low (только качественно)

**Пример:**
```json
[
  {"label": "Шторм на горизонте", "probability": 0.25, "factors": {"brent_pct_change": -30, "rate_bps_change": 300, "usdrub_pct_change": 20, "sanctions_escalation": true}, "source": "scenario-builder", "weight_type": "equal", "confidence": "medium"},
  {"label": "Управляемая турбулентность", "probability": 0.25, "factors": {"brent_pct_change": -10, "rate_bps_change": 0, "usdrub_pct_change": 5, "sanctions_escalation": false}, "source": "scenario-builder", "weight_type": "equal", "confidence": "medium"},
  {"label": "Тихая гавань", "probability": 0.25, "factors": {"brent_pct_change": 10, "rate_bps_change": -200, "usdrub_pct_change": -8, "sanctions_escalation": false}, "source": "scenario-builder", "weight_type": "equal", "confidence": "medium"},
  {"label": "Новый нормальный", "probability": 0.25, "factors": {"brent_pct_change": 20, "rate_bps_change": -300, "usdrub_pct_change": -15, "sanctions_escalation": false}, "source": "scenario-builder", "weight_type": "equal", "confidence": "high"}
]
```

**⚠️ Всегда добавлять в выход:** «Веса равные (0.25 × 4) — методологическое допущение Shell, не реальные вероятности. Expected P&L не рассчитывается.»

---

## Тип B: forecast-confidence-applier (Filtered Consensus)

**Характеристика:** Modal оценка с bias-discount + confidence band (80% CI). Единственный точечный прогноз с диапазоном.

**Откуда берётся вход:**
- Блок `## TL;DR` из вывода forecast-confidence-applier (Modal scenario + confidence band)
- Или явные значения из filtered consensus в тексте

**Алгоритм конвертации:**

Из modal estimate + confidence band создать **3 сценария:**

| Сценарий | Значение | Вес | Логика |
|----------|----------|-----|--------|
| Modal | точечная оценка | 0.60 | Центр распределения |
| Lower bound | нижняя граница 80% CI | 0.20 | Левый хвост |
| Upper bound | верхняя граница 80% CI | 0.20 | Правый хвост |

Сумма весов = 1.0. Устанавливать `weight_type = "probability"`.

**Пример** (filtered consensus: «Brent $70–75 modal, CI $62–82 80% при текущем $85»):
```json
[
  {"label": "Consensus modal", "probability": 0.60, "factors": {"brent_pct_change": -13.0}, "source": "forecast-confidence-applier", "weight_type": "probability", "confidence": "medium"},
  {"label": "Consensus downside", "probability": 0.20, "factors": {"brent_pct_change": -27.0}, "source": "forecast-confidence-applier", "weight_type": "probability", "confidence": "low"},
  {"label": "Consensus upside", "probability": 0.20, "factors": {"brent_pct_change": -3.5}, "source": "forecast-confidence-applier", "weight_type": "probability", "confidence": "low"}
]
```

**Если factor в consensus не указан явно** (например, нет прогноза по USD/RUB) → оставить `null`, β не применяется.

---

## Тип C: hypothesis-stress-tester (Stress-Tested Forecast)

**Характеристика:** Main case с вероятностью + уязвимости (vulnerabilities) с условными вероятностями. Наиболее ценный вход — реальные probability weights.

**Откуда берётся вход:**
- Блок `## Заключение` + `## Точки отказа` из вывода hypothesis-stress-tester
- Main case P + list of vulnerabilities с P_conditional

**Алгоритм конвертации:**

1. Зафиксировать `P_main_case` из вывода стресс-тестера
2. Для каждой vulnerability взять `P_conditional` (вероятность реализации vulnerability)
3. Рассчитать `P_scenario = P_conditional × (1 - P_main_case)` для уязвимостей
   *(уязвимость реализуется при отклонении от main case)*
4. Проверить: `P_main_case + sum(P_scenarios) ≈ 1.0`. Если ∑ < 1.0 — main case добирает остаток
5. Каждая уязвимость — отдельный сценарий с собственными факторами

**Пример** (stress-tested прогноз ставки: main case cut 100bp P=0.60, vulnerabilities: hold P=0.25, hike 50bp P=0.15):
```json
[
  {"label": "Main: cut 100bp", "probability": 0.60, "factors": {"rate_bps_change": -100}, "source": "hypothesis-stress-tester", "weight_type": "probability", "confidence": "high"},
  {"label": "Vuln: hold", "probability": 0.25, "factors": {"rate_bps_change": 0}, "source": "hypothesis-stress-tester", "weight_type": "probability", "confidence": "medium"},
  {"label": "Vuln: hike 50bp", "probability": 0.15, "factors": {"rate_bps_change": 50}, "source": "hypothesis-stress-tester", "weight_type": "probability", "confidence": "low"}
]
```
Sum probabilities: 0.60 + 0.25 + 0.15 = 1.00 ✓

**Vulnerability mapping:** vulnerability сценарии отдельно помечаются в Шаге 4 для специального анализа — позиции, уязвимые именно к ним, а не к main case.

---

## Гибридный вход

**Когда использовать:** пользователь передаёт сценарии Shell (Тип A) как базу, но для одного конкретного фактора (например, ставка ЦБ) есть более специфический источник (Тип C от hypothesis-stress-tester).

**Правило приоритета:** более специфический источник перекрывает менее специфический для конкретного фактора.

**Алгоритм:**
1. Начать с нормализации более широкого источника (обычно Тип A — 4 сценария)
2. Для каждого сценария: если фактор указан в более специфическом источнике — перезаписать его значением из специфического источника
3. `probability` остаётся от более широкого источника (Shell 0.25)
4. `weight_type` → `"equal"` (Shell-основа), но добавить ноту о hybrid

**Пример:** Shell-сценарий «Шторм» имеет rate_bps_change +300, но stress-tester говорит hold/hike 50 с вероятностями. При гибриде используем +50 (vulnerability hike) для worst-case Shell-сценария.

---

## Ручной ввод (Manual)

Если пользователь описывает сценарий текстом без использования скиллов:

> «Предположим нефть $55, ставка остаётся 21%, рубль 100 к доллару»

Конвертировать в internal format с `source: "manual"`, `confidence: "medium"` (пользователь знает свои допущения), `weight_type` = "equal" (одиночный сценарий без вероятностей).

**Уточнить у пользователя при ручном вводе:**
- Базовые значения факторов (что сейчас?)
- Это абсолютные значения или изменения?
- Один сценарий или несколько с вероятностями?

---

## Частые ошибки конвертации

| Ошибка | Правильно |
|--------|-----------|
| Суммировать P из разных источников | Каждый тип — отдельный список сценариев |
| Приравнивать Тип A к Типу C | Явно указывать weight_type в каждом сценарии |
| Пропускать null для незаданных факторов | null ≠ 0; при null β не применяется |
| Использовать номинальные значения вместо %-изменений | Всегда конвертировать в % от текущего значения |
| Забывать ноту для equal-weighted | Ноту добавлять в выход автоматически при weight_type: "equal" |

---

## Тип D: macro-forecast-chain (macro_input.yaml)

**Характеристика:** самый полный вход — агрегированная матрица всех факторов,
подготовленная macro-forecast-chain. Содержит probability-weighted сценарии
и поле `caveats` с зафиксированными расхождениями.

**Откуда берётся вход:**
- Файл `Claude-Memory/Macro-Chain/MACRO-INPUT-{date}.yaml`
- Или пользователь: «используй последний MACRO-INPUT»

**Алгоритм конвертации:**

1. Прочитать блок `scenarios[]` из yaml.
2. Маппинг полей — прямой (имена совпадают с internal format).
3. Установить `weight_type = "probability"` для всех сценариев.
4. `source = "macro-forecast-chain"`.
5. `confidence` — из `coverage_score` в yaml:
   - `N/N` (полное) → `"high"` / `N-1/N` → `"medium"` / `≤ N-2/N` → `"low"`.
6. **Caveats → notes:** из блока `caveats[]` собрать строку в `notes`:
   `"Caveats: urals_discount stale; brent↑+usdrub↓ принято пользователем"`
7. Если сумма вероятностей < 1.0 — добавить сценарий `Остальное` с probability = 1 - sum.

**Новые поля** (появились вместе с Типом D, поддерживаются во всех типах):

| Поле | Использование |
|------|--------------|
| `xauusd_pct_change` | % изменение XAU/USD → для TGLD, PLZL |
| `urals_discount_usd` | Абсолютный дисконт Urals к Brent, $USD |
| `cbr_rate_absolute` | Абсолютная ставка ЦБ % → контекст для β банков |
| `inflation_ru_pct` | Абсолютная инфляция % → реальная доходность облигаций |

**Приоритет:** Тип D имеет наивысший приоритет при auto-discovery из Claude-Memory.
Если найден `MACRO-INPUT-*.yaml` — предпочесть его, если пользователь не указал иное.
