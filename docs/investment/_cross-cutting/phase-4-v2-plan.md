# План реализации: Фаза 4 (V2-A multiple horizons + V2-B full covariance)

> **Тип:** PLAN / handoff · **Создан:** 2026-06-10 · **Статус:** готов к реализации, код не тронут
> **Контекст:** документ самодостаточен — рассчитан на исполнение в свежих сессиях (Sonnet/Opus)
> без предварительно загруженного контекста. Все факты заземлены на реальный код и боевые
> артефакты Claude-Memory (пути и номера строк — на 2026-06-10, могли сместиться —
> ориентируйся также на имена функций/якорей).
>
> **Главный принцип (требование пользователя):** код НЕ содержит подгонки под конкретные
> бумаги, сценарии, прогнозы. Тикеры, ISIN, scenario_id, конкретные горизонты — приходят
> из данных/конфига, не зашиваются в логику. Тестировать на актуальных данных Claude-Memory
> можно и нужно (E2E-приёмка), но юнит-тесты — на синтетических фикстурах.

## Решения зафиксированы (не пересматривать без явной причины)

| # | Решение | Выбор |
|---|---------|-------|
| **D4-1** | Форма weekly-review v2 | Top-level `horizons: [12, 20, 36]` + `horizon_ends` + `primary_horizon: 20`. Структура `per_stock`/`per_bond` НЕ меняется, кроме одного: **`catalyst[].in_horizon` удаляется** — принадлежность горизонту вычисляет consumer детерминированно из `date_window` (убирает LLM-прошитый bool, который ломается при >1 горизонте). |
| **D4-2** | Форма stress v2 | Top-level `horizons` + `horizon_ends`; `scenarios.X.factors` → `scenarios.X.factors_by_horizon: {h12:…, h20:…, h36:…}`; `per_position.X` получает блок `by_horizon: {hNN: {delta_pct_by_scenario, expected_pct_pweighted, tail_var_pct, tail_var_scenario_id}}`. **`factor_betas` остаются плоскими** — это месячные беты (SS-1), от горизонта не зависят. Ключи горизонтов — строки `h12`/`h20`/`h36` (не int-ключи YAML). |
| **D4-3** | Откуда per-horizon факторы | Из **per-year уровней FCA** (механика MFC-4): уровень года, ближайшего к `as_of + h месяцев`, → % против `baseline_spot` (контракт единиц `_shared-references/events-yaml-spec.md` §5.6). Детерминированный хелпер `compute_horizon_factors.py` (новый, в portfolio-scenario-stress). Если уровень нужного года отсутствует — берётся ближайший доступный, CI инфлируется ×√(h_target/h_source), пишется warning. Никакой ручной арифметики у LLM. |
| **D4-4** | Миграция боевых данных | **Backward-compat в коде, БЕЗ массовой миграции.** 23 боевых v1-артефакта (7 stock + 6 bond + 1 mixed review, 9 stress) остаются как есть. Consumers v2 принимают v1-вход и авто-оборачивают его как `{h20: …}` (правило «Backward compatibility 1 major version» из INTEGRATION-DOCS/05). Валидаторы маршрутизируют по `schema_version` (v1-валидаторы не трогать). Новые артефакты пишутся только v2. |
| **D4-5** | Движок Monte Carlo (V2-B) | **stdlib `random`** (включая `random.triangular`), БЕЗ numpy — `aggregate_positions.py` остаётся stdlib-only (зафиксировано в CLAUDE.md). Детерминизм: `--mc-seed` (default фиксированный, напр. 42) + `--mc-paths` (default 10000). Сид и paths пишутся в output. |
| **D4-6** | Модель корреляций в MC | **Общий розыгрыш сценария на path** — в каждом из 10k путей сценарий `s ~ p_norm` разыгрывается ОДИН раз и используется всеми позициями/катализаторами. Это даёт когерентные «миры» (нет mixed-worlds), корреляция между позициями через macro и между катализаторами через `active_scenarios` возникает естественно — **без явной corr_matrix**. Явное поле `corr_matrix` НЕ вводится (исторических данных для его оценки нет; вернуться при V2-C, если калибровка покажет нужду). |
| **D4-7** | Точечные оценки vs MC | **Точечные значения (value) остаются аналитическими** — текущие формулы Σ не трогаются (воспроизводимость, сравнимость с v1). MC считает только CI (перцентили 2.5/97.5), spread CI и портфельные хвосты. Guard: если `|mean(MC) − analytic| > 1.5 п.п.` по портфелю — warning `mc_divergence`. Аналитический CI-режим сохраняется как `--ci-mode analytic` (default `mc`) — для регрессии и отладки. |
| **D4-8** | Verdict и горизонты | `advisor_verdict` остаётся **один на позицию**, семантически привязан к `primary_horizon` (фиксируется в спеке). Per-horizon вердиктов НЕ плодить (recommendations creep + фантомная точность). Equity-vs-bond сравнение в integrated-view — per-horizon. |
| **D4-9** | Никаких хардкодов | Дефолтный список горизонтов — ОДНА константа `DEFAULT_HORIZONS = [12, 20, 36]` в каждом producer/consumer, перекрывается CLI/payload. Scenario_id берутся из данных (как сейчас). Никаких тикеров/ISIN в логике (исключение — уже легализованный опц. fallback `IDIOSYNCRATIC_TICKERS` в stress, его не расширять). |

---

## 0. Что такое Фаза 4 и почему V2-A + V2-B вместе

Единственная фаза с **breaking changes**: schema bump weekly-review и stress YAML v1 → v2,
синхронно в трёх скиллах:

- `ru-portfolio-advisor` — генерирует weekly-review (stub-скрипты + LLM);
- `portfolio-scenario-stress` — генерирует stress (stub + `compute_per_position.py`);
- `portfolio-integrated-view` — потребляет оба (`aggregate_positions.py`).

**V2-A (multiple horizons, R3):** сейчас горизонт прошит на 20 мес — это систематически
биасирует сравнение акции/облигации в пользу облигаций (механический цикл ставки).
v2 считает 12/20/36 мес side-by-side.

**V2-B (full covariance, R4):** сейчас CI propagation аналитическая — аддитивная per-position,
spread CI двумя крайностями (corr=1 линейно / corr=0 квадратурно). v2 заменяет это Monte Carlo
по 10k путей с общим розыгрышем сценария (D4-6) — корреляции учитываются честно.

Делаются вместе, потому что оба требуют bump схем и трогают одни и те же файлы — раздельно
пришлось бы делать два bump'а.

---

## 1. Этап 0 — спека схем v2 (SSOT) · Сложность S

**Файл:** `_shared-references/yaml-schemas.md` (там сейчас задокументированы weekly-review v1
≈ строки 201–331 и stress v1). Добавить разделы «weekly-review schema v2» и «stress schema v2».

### 1.1 weekly-review v2 (stock и bond)

```yaml
schema_version: 2                  # было: 1
type: weekly-stocks-review         # | weekly-bonds-review (без изменений)
review_date: '2026-06-15'
horizons: [12, 20, 36]             # НОВОЕ: отсортированный список месяцев
horizon_ends:                      # НОВОЕ: детерминированно от review_date (конец месяца)
  h12: '2027-06-30'
  h20: '2028-02-29'
  h36: '2029-06-30'
primary_horizon: 20                # НОВОЕ: к нему привязан advisor_verdict (D4-8)
# horizon_months / horizon_end / horizon — УДАЛЕНЫ в v2 (drift-check ловит)

per_stock:                         # структура НЕ меняется, кроме:
  <TICKER>:
    catalyst:
    - id: ...
      kind: binary | quantitative
      date_window: '2026-07'       # ОБЯЗАТЕЛЬНОЕ в v2 (в v1 было де-факто); форматы см. 1.3
      # in_horizon — УДАЛЕНО в v2 (consumer вычисляет из date_window; drift-check ловит)
      ...остальные поля catalyst без изменений (METH-1: p/upside_pct/upside_by_scenario/…)
```

`div_yield_12m_pct` / `ytm_pct` остаются годовыми — горизонтное масштабирование всегда было
на стороне consumer (`× h/12`), менять не надо.

### 1.2 stress v2

```yaml
schema_version: 2
type: portfolio-stress-test
date: '2026-06-15'
horizons: [12, 20, 36]
horizon_ends: {h12: ..., h20: ..., h36: ...}
portfolio_snapshot_id: portfolio-....json
baseline_spot: {...}               # единый на все горизонты (без изменений)

scenarios:
  A:
    name: ...
    p: 0.25
    factors_by_horizon:            # БЫЛО: factors (один набор)
      h12: {brent: -10.0, cbr_rate: -2.0, usdrub: 8.0, ...}   # единицы — events-yaml-spec §5.6
      h20: {...}
      h36: {...}
    portfolio_level_by_horizon:    # БЫЛО: portfolio_level
      h12: {delta_rub: ..., expected_pct_pweighted: ...}
      ...

per_position:
  <TICKER>:
    weight_pct: ...
    on_iis: ...
    factor_betas: {...}            # ПЛОСКИЕ (D4-2), как в v1
    factor_betas_method: ...
    factor_betas_r2: ...
    by_horizon:                    # НОВОЕ: всё горизонт-зависимое сюда
      h12:
        delta_pct_by_scenario: {A: {value, ci_pct}, ...}
        expected_pct_pweighted: {value, ci_pct}
        tail_var_pct: ...
        tail_var_scenario_id: ...
      h20: {...}
      h36: {...}
    macro_blindspot: ...           # горизонт-независим (R²-критерий), плоский
```

### 1.3 Контракт `date_window` (для детерминированного in-horizon)

Принимаемые форматы (толерантный парсер, регистронезависимо):
`YYYY-MM` · `YYYY-MM-DD` · `YYYY` · `YYYY-Qn` · диапазон `A..B` / `A—B` / `A - B`
(каждая сторона — любой из форматов выше). Правило: катализатор «в горизонте h», если
**начало окна ≤ horizon_ends[h]**. Непарсибельный `date_window` → катализатор считается
в горизонте на ВСЕХ горизонтах + warning `date_window_unparseable` (консервативно,
сохраняет v1-поведение, где `in_horizon: true` ставил LLM).

### 1.4 Задачи этапа
- [ ] Разделы v2 в `_shared-references/yaml-schemas.md` (схемы 1.1–1.2, контракт 1.3, правило CI-инфляции из D4-3).
- [ ] В тех же разделах — таблица «что удалено в v2» (`horizon_months`, `horizon_end`, `horizon`, `in_horizon`) — это вход для drift-чеков валидаторов.
- [ ] Спека MC-блока output integrated-view (D4-5/6/7): `ci_method`, `mc: {paths, seed}`.

Делается ПЕРВЫМ — все остальные этапы ссылаются на эти разделы.

---

## 2. Этап 1a — producer weekly-review (`ru-portfolio-advisor`) · Сложность M

**Файлы:** `skills/ru-portfolio-advisor/scripts/build_weekly_stock_stub.py`,
`build_weekly_bond_stub.py`, `SKILL.md` (Mode 1/2: упоминания «20 мес» ≈ строки 281, 315, 390, 418, 481, 529).

Заземление (текущее v1-поведение):
- `build_weekly_stock_stub.py:256` и `build_weekly_bond_stub.py:332` пишут `schema_version: 1`;
- `build_weekly_bond_stub.py:335` — `horizon_months: 20`; `:257` — хардкод `horizon_end = "2027-12-31"`; `:235` — TODO-хинт `in_horizon: TODO_LLM_bool_true_if_within_20mo`;
- оба стаба fail-fast'ят снапшот `schema_version 2.x` (строки 52–55 / 51–54) — это про СНАПШОТ, НЕ трогать.

Задачи:
- [ ] CLI `--horizons 12,20,36` (default `DEFAULT_HORIZONS`) + `--primary-horizon 20`.
- [ ] Эмитить `schema_version: 2`, `horizons`, `horizon_ends` (детерминированная дата-арифметика: `review_date + h месяцев`, конец месяца; никакого хардкода дат), `primary_horizon`.
- [ ] Убрать эмит `horizon_months`/`horizon`/`horizon_end` и TODO-хинт `in_horizon` (LLM его больше не заполняет; `date_window` — обязателен, хинт-формат из 1.3).
- [ ] `SKILL.md`: описать v2-контракт, заменить «20 мес» на «`primary_horizon` (default 20)»; явно: вердикты — к primary_horizon (D4-8).
- [ ] Тесты: `tests/` у ru-portfolio-advisor для стабов (если файла нет — завести `test_weekly_stubs.py`): горизонт-арифметика (включая 29 февраля / конец месяца), v2-поля присутствуют, v1-поля отсутствуют, кастомные `--horizons 6,18`.

---

## 3. Этап 1b — producer stress (`portfolio-scenario-stress`) · Сложность L

**Файлы:** `scripts/build_stress_stub.py`, `scripts/compute_per_position.py`,
**новый** `scripts/compute_horizon_factors.py`, `SKILL.md`, `references/input-adapters.md`.

Заземление:
- `build_stress_stub.py:163` пишет `schema_version: 1`; `:149` — хардкод `horizon_end = "2027-12-31"`; `:171` — `horizon_months`; CLI `--horizon-months` (:302).
- `compute_per_position.py`: `compute_delta_pct(betas, factors)` читает `sc["factors"]` (≈ строки 850–858); сборка entry ≈ 886–901; беты SS-1 — месячные, горизонт-независимые.

Задачи:
- [ ] **Новый `compute_horizon_factors.py`** (D4-3): вход — JSON `{scenario_id: {factor: {level_<год>: число | level: число}}}` + `baseline_spot` + `horizons` + `as_of`; выход — `factors_by_horizon` (% против спота / п.п. по контракту §5.6). Выбор года — ближайший к `as_of + h`; при отсутствии — ближайший доступный + CI ×√(h_target/h_source) + warning. Логика выбора года и level→move — переиспользовать паттерн `aggregate_positions._pick_nearest_level`/`_level_to_move` (скопировать в скилл, не импортировать через границу скиллов).
- [ ] `build_stress_stub.py`: `--horizons 12,20,36`; эмитить v2-скелет (1.2) с TODO-блоками `factors_by_horizon` per horizon; `horizon_ends` — дата-арифметика от `--as-of`, хардкод `2027-12-31` убрать.
- [ ] `compute_per_position.py`: цикл по горизонтам — для каждого `hNN` считать `delta_pct_by_scenario`/`expected_pct_pweighted`/`tail_var_*` от `factors_by_horizon[hNN]` (беты одни). Выход — `by_horizon`-блок. Принимать и v1-вход (один `factors`) → эмитить `by_horizon: {h20: …}` с warning (для отладочных прогонов на старых данных).
- [ ] `SKILL.md` + `references/input-adapters.md`: v2-контракт, ссылка на yaml-schemas v2 и §5.6.
- [ ] Тесты: расширить `tests/test_compute_per_position.py` (мульти-горизонт: 3 блока by_horizon, беты одинаковые, дельты разные; v1-вход → h20-обёртка) + новый `tests/test_compute_horizon_factors.py` (выбор года, CI-инфляция, qualitative-факторы без level пропускаются, десятичные запятые НЕ поддерживаем — вход уже числовой).

---

## 4. Этап 2 — валидаторы и schema-роутинг · Сложность M

Заземление (полный реестр мест, завязанных на v1):

| Файл | Что проверяет | Якоря |
|---|---|---|
| `skills/save-to-library/scripts/assemble_artifact.py` | `validate_stress()` ≈ 211–410; `validate_weekly_review_stock_detailed()` ≈ 1063–1233 (BLOCKING: `schema_version != 1` :1078, `horizon_months != 20` :1100); `…_bond_detailed()` ≈ 1235–1450 (:1251, :1258); router `validate_weekly_review()` ≈ 1477–1485; drift-словари ≈ 646–656; catalyst-валидаторы METH-1 ≈ 748–928 | v1-only |
| `scripts/validate_schema.py` (корень репо) | stress generic, check `schema_version != 1` ≈ :223 | v1-only |
| `skills/revise-memory-remote/scripts/validate_library.py` | catalyst schema ≈ 731–861; weekly-reviews layer ≈ 867–942; bond ytm-санити :915 | версия не прошита жёстко — проверить |

Задачи:
- [ ] `assemble_artifact.py`: **роутинг по `schema_version`** — v1 → существующие валидаторы (НЕ трогать, легаси остаётся валидным), v2 → новые `validate_weekly_review_stock_v2` / `…_bond_v2` / `validate_stress_v2`. Проверки v2: `horizons` — непустой sorted-список уникальных int; `horizon_ends` — ключи `h<NN>` ровно по horizons, даты ISO и согласованы с review_date (+h мес, допуск ±5 дней); `primary_horizon ∈ horizons`; `factors_by_horizon`/`by_horizon` — ключи ⊆ `h<NN>`; catalyst через СУЩЕСТВУЮЩИЕ METH-1-валидаторы (они версии не касаются) + новое: `date_window` обязателен и парсится контрактом 1.3 (warning, не blocking, при непарсибельном).
- [ ] Drift-чеки v2 (анти-möbius): присутствие `horizon_months`/`horizon_end`/`horizon`/`in_horizon` в v2-файле → BLOCKING `v1_field_in_v2` (по образцу `_check_drift_renames` :731–746).
- [ ] `scripts/validate_schema.py`: тот же роутинг для stress.
- [ ] `validate_library.py`: weekly-layer и ytm-санити должны принимать оба формата (горизонт-поля не читает → вероятно, ноль правок; подтвердить тестом на v2-фикстуре).
- [ ] Тесты: расширить `skills/save-to-library/tests/test_assemble_artifact.py` (валидный v2 проходит; v1 как раньше; v2 с `in_horizon` — BLOCKING; v2 без `horizons` — BLOCKING) и `skills/revise-memory-remote/tests/test_validate_library.py` (v2-фикстура через weekly-layer).

---

## 5. Этап 3 — consumer V2-A: multi-horizon в `aggregate_positions.py` · Сложность L

Заземление (текущее v1-поведение, `skills/portfolio-integrated-view/scripts/aggregate_positions.py`):
- `DEFAULT_HORIZON_MONTHS = 20` (:42); `run()` читает `payload["horizon_months"]` (:1134), отдаёт `horizon_months` в output (:1211).
- `aggregate_div_or_carry()` (:388–440): `× horizon/12`, bond-кэп `eff_months = min(horizon, months_to_event)` — уже параметризовано.
- `aggregate_macro()` (:290–377): L2 = `expected_pct_pweighted` из stress (плоский в v1), L1 = MFC-4 level→move (уже выбирает год по горизонту).
- `aggregate_idio()` (:615–660) фильтрует по `catalyst.in_horizon` (:633).
- `compute_portfolio_aggregates()` (:747–791): аннуализация `12/h`, dual spread CI.
- Fail-fast schema_version у aggregate_positions НЕТ (мягкий `_get`) — в v2 добавить явный.

Задачи:
- [ ] Payload v2: `horizons: [12, 20, 36]` (список) вместо `horizon_months`; `primary_horizon`. Backward-compat: payload с `horizon_months` → `horizons = [horizon_months]` (D4-4).
- [ ] Явная проверка версий входов: review/stress `schema_version ∈ {1, 2}`; v1-stress → авто-обёртка `by_horizon = {h20: <плоские поля>}` + `factors_by_horizon = {h20: factors}`; v1-review → `horizons=[20]`, легаси `in_horizon` уважается. Несовпадение запрошенных горизонтов с доступными в stress → fail-fast с понятным сообщением (какие hNN есть).
- [ ] **Детерминированный in-horizon:** парсер `date_window` по контракту 1.3 (новая функция `_catalyst_in_horizon(catalyst, review_date, horizon_end) -> bool`, unparseable → True + warning). v1-вход: если есть легаси `in_horizon` — использовать его для h20, для остальных горизонтов — парсер.
- [ ] Главный цикл: `for h in horizons:` → per-position `{macro, div_or_carry, idio, total}` per horizon. Macro: L2 из `by_horizon[hNN].expected_pct_pweighted`; L1 (macro_marginal) уже выбирает год — передавать h текущей итерации.
- [ ] Output: `per_position[t].by_horizon.{hNN}` + дублирование primary_horizon в плоские поля (совместимость прозы §-шаблонов и viewer v1-рендера); портфельные агрегаты, equity-vs-bond и spread — per horizon; `predictions_for_review`: единый dedup-список катализаторов, у каждого поле `horizons: [12, 20]` (в каких горизонтах активен) — это удовлетворяет acceptance «свой блок на горизонт» без дублирования сущностей.
- [ ] Sanity checks (IV-C) и tail_flags (@1.2) — гонять per horizon; в отчёте tail-флаги primary_horizon, расхождения по другим горизонтам — отдельной строкой.
- [ ] Diff IV-A (`--diff-with-previous`): сравнивать по primary_horizon (v1-предыдущий отчёт сравним только по h20 — учесть).
- [ ] CLI/режимы: `--horizon 12` / `--horizon 36` (подмножество), `--all-horizons` (default).
- [ ] `SKILL.md` portfolio-integrated-view: новый контракт входов/выходов, шаблон отчёта — per-position таблица с 3 колонками `expected_pct`, секция equity-vs-bond per horizon.
- [ ] Тесты (`tests/test_aggregate_positions.py`, сейчас 108): мульти-горизонт e2e на синтетике (3 горизонта, числа h20 == прежним v1-ожиданиям!); v1-входы → h20-обёртка (регрессия: все старые тесты проходят без правок ожиданий); парсер date_window (все форматы + unparseable); subset `--horizon`; bond-кэп оферты на h36 (event раньше горизонта).

**Регрессионный инвариант этапа:** на v1-входах и `horizons=[20]` все числа выхода
бит-в-бит совпадают с текущим v1-поведением. Это главный гейт.

---

## 6. Этап 4 — consumer V2-B: Monte Carlo CI · Сложность L

Заземление (что заменяется):
- Per-position total CI — аддитивный (`aggregate_position()` :700–705).
- Портфель — `_weighted_total()` (:733–744), spread dual CI (linear corr=1 / quadratic corr=0, σ≈width/4) в `compute_portfolio_aggregates()` (:774–787).
- Катализаторы: `compute_catalyst_contribution()` (:499–612) — binary `factor = p × scenario_mass × src_disc`, quant `Σ_s p_s × upside_s × src_disc`; `NULL_DEPENDENCY_DISCOUNT = 0.7` (:43), `LOW_QUALITY_DISCOUNT = 0.5`.

Дизайн (D4-5/6/7), один path из 10k:
1. Разыграть сценарий `s ~ p_norm` — ОДИН на path, общий для всех позиций и горизонтов.
2. Macro позиции: сэмпл `triangular(ci_lo, value, ci_hi)` из `delta_pct_by_scenario[s]` (не pweighted! — сценарий уже разыгран). Если L1-режим — точечный L1 + сэмпл CI-ширины L2 вокруг него (зафиксировать в коде комментарием).
3. Div/carry: сэмпл `triangular` из его CI.
4. Катализаторы binary: если `active_scenarios` resolved — событие стреляет при `s ∈ active` и `Bernoulli(p)`; null/unresolved dependency — `Bernoulli(p × 0.7)` безусловно (паритет с NULL_DEPENDENCY_DISCOUNT). Импакт — `triangular` из upside/downside CI, `× src_disc` (LOW → 0.5 как множитель импакта, паритет с аналитикой).
5. Катализаторы quantitative: значение `triangular` из `upside_ci_by_scenario[s]` (отсутствует CI → дельта в точке `upside_by_scenario[s]`), `× src_disc`.
6. Path-сумма по позиции = macro + div/carry + Σ катализаторов; портфель/корзины — взвешенно по `weight_pct`; spread = eq − bd на том же path (корреляция автоматически).

Выход MC: перцентили P2.5/P97.5 → `ci`; spread — единый `ci` (поля `ci_linear`/`ci_quadratic` в v2-выводе заменяются на `ci` + `ci_method: mc`; в режиме `--ci-mode analytic` остаётся прежняя пара). Дополнительно `p5_pct`/`p95_pct` портфеля — вход для tail-флагов.

Задачи:
- [ ] Функции `mc_simulate(positions_ctx, scenarios, paths, seed)` и обвязка в `run()`; вырожденные случаи (CI нулевой ширины → дельта-распределение; p∈{0,1}; пустые катализаторы).
- [ ] Точечные значения НЕ трогать (D4-7); guard `mc_divergence` (|MC mean − analytic| > 1.5 п.п. портфеля → warning).
- [ ] `--ci-mode {mc,analytic}` default `mc`; `--mc-paths 10000`, `--mc-seed 42`; в output — `ci_method`, `mc: {paths, seed}`.
- [ ] tail_flags: считать от MC-CI (логика порогов не меняется — она читает готовый CI); проверить на синтетике, что floor/cap не разъезжаются.
- [ ] Производительность: 10k paths × ~40 позиций × 3 горизонта на чистом Python — потолок секунд; если >10 с, разыгрывать пути горизонтами независимо с под-сидами `seed+h` (зафиксировать в коде).
- [ ] Тесты: фикс-сид воспроизводимость (два прогона — идентичный output); сходимость к аналитике на симметричной синтетике (|MC − analytic| < 0.5 п.п. при 10k); корреляция через общий сценарий (две позиции с противоположными бетами → spread CI уже, чем corr=0-квадратура); Bernoulli-паритет (catalyst p=1, active=все сценарии → MC CI == аналитическому импакт-CI); analytic-режим == текущему поведению.

---

## 7. Этап 5 — viewer + E2E на реальных данных · Сложность M

**Файл:** `Claude-Memory/tools/portfolio-integrated-viewer.html` (вне репо, транспорт B).

Заземление: `SUPPORTED = {weeklyReview: 1, stress: 1, portfolio: /^2\./, …}` (≈ :903–927,
`checkSchema()` кидает при несовпадении); `normalizeWeeklyReview()` (:991), `normalizeStress()`
(:1008) — drift-нормализация v1; чтение `fm.horizon_months || 20` (:2714).

Задачи:
- [ ] `SUPPORTED.weeklyReview/stress` → принимать `{1, 2}`; внутренняя нормализация к v2-форме: v1 → `horizons=[20]`, `by_horizon={h20:…}` (существующие normalize* остаются для v1-дрифтов).
- [ ] Переключатель горизонта (вкладки/селектор 12/20/36, default `primary_horizon`); строка :2714 — на `primary_horizon`-логику.
- [ ] Показ `ci_method`/`mc` в шапке отчёта; spread — один CI (v2) или пара (v1).
- [ ] **E2E-приёмка на актуальных данных Claude-Memory** (разработческий прогон, НЕ запись в библиотеку):
  1. `compute_horizon_factors.py` на per-year уровнях из боевого `macro-chain/macro-marginal-*.yaml` (последний: `macro-marginal-2026-05-11.yaml`) + `baseline_spot` из `Portfolio/stress/stress-2026-05-29-shell-d1-2027.yaml`.
  2. Stress v2 через `compute_per_position.py` на боевом снапшоте.
  3. `aggregate_positions.py` v2-payload (боевые review v1 → авто-обёртка h20 + синтетические h12/h36 факторы) — проверить: h20-числа == последнему боевому integrated-view (допуск точечных — 0.1 п.п.), sanity чист, MC CI ⊇/≈ разумно против старой квадратуры.
  4. Viewer открывает и v1-, и v2-файлы.
  Первый ПОЛНЫЙ боевой v2-цикл — следующий weekly-обзор (LLM-часть production), это уже эксплуатация, не Фаза 4.

---

## 8. Порядок, зависимости, мульти-агентный режим

```
Этап 0  Спека схем v2 (S) ─── первым, всё ссылается на неё
   │
   ├── Этап 1a  producer weekly-review (M)  ┐
   ├── Этап 1b  producer stress (L)         ├─ ПАРАЛЛЕЛЬНЫ (разные скиллы, общая только спека)
   ├── Этап 2   валидаторы (M)              ┘
   │
   └── Этап 3  consumer V2-A (L)  ── зависит только от спеки; параллелен 1a/1b/2
          │
          └── Этап 4  consumer V2-B MC (L)  ── строго после Этапа 3 (тот же файл)
                 │
                 └── Этап 5  viewer + E2E (M) ── последним, нужны все артефакты
```

Рекомендации для мульти-агентного исполнения (opt-in, по запросу пользователя):
- Этапы 1a / 1b / 2 / 3 — четыре независимых агента в **worktree-изоляции** (правят разные
  скиллы; Этап 2 и Этап 3 не пересекаются по файлам: валидаторы — save-to-library/корень,
  consumer — portfolio-integrated-view).
- Этапы 4 и 5 — последовательно, одной сессией каждый.
- Интеграционная сессия после merge: прогнать ВСЕ тесты репозитория + E2E §7.
- Каждому агенту в промт: ссылка на этот план (раздел этапа) + раздел «Конвенции» ниже +
  релевантная строка каталога `docs/investment/README.md` §3.

Бюджет: ~5 рабочих сессий (S+M+L+M+L+L+M), календарно «несколько недель» из TODO — c
параллелизацией этапов 1–3 сжимается до ~3 сессий стенки.

---

## 9. Acceptance (сводный, из TODO V2-A/V2-B)

**V2-A:**
- [ ] `--horizon=12` / `--horizon=36` / `--all-horizons` работают в integrated-view.
- [ ] Per-position таблица — 3 колонки `expected_pct` (по горизонту).
- [ ] Equity vs bond — per horizon.
- [ ] `predictions_for_review` — катализатор несёт `horizons: […]` (per-horizon view).
- [ ] weekly-review v2 и stress v2 генерируются стабами/скриптами, проходят валидаторы.
- [ ] **Регрессия:** v1-входы + `horizons=[20]` → числа идентичны текущим (старые тесты зелёные без правки ожиданий).

**V2-B:**
- [ ] Joint expected учитывает корреляции катализаторов внутри позиции (общий розыгрыш сценария).
- [ ] CI propagation через MC (10k paths, фикс-сид, воспроизводимо), не аналитически; `--ci-mode analytic` сохранён.
- [ ] Spread CI — единый из joint-сэмплов (вместо пары linear/quadratic).
- [ ] Точечные оценки аналитические; guard `mc_divergence`.

**Команды проверки** (`python3` = `~/.pyenv/versions/3.12.9/bin/python3` — дефолтный сломан):
```bash
P=~/.pyenv/versions/3.12.9/bin/python3
$P skills/portfolio-integrated-view/tests/test_aggregate_positions.py
$P skills/portfolio-scenario-stress/tests/test_compute_per_position.py
$P skills/portfolio-scenario-stress/tests/test_compute_horizon_factors.py   # новый
$P skills/ru-portfolio-advisor/tests/test_weekly_stubs.py                   # новый
$P skills/save-to-library/tests/test_assemble_artifact.py
$P skills/revise-memory-remote/tests/test_validate_library.py
```

---

## 10. Заземляющие факты (для быстрой верификации в новой сессии)

**Боевые артефакты** (`~/Library/CloudStorage/SynologyDrive-home/Ext_gDrive/Claude-Memory/`):
- `Portfolio/weekly-reviews/weekly-review-stock-2026-06-08.yaml` — свежайший stock v1: `schema_version: 1` (int), `horizon_months: 20`, `horizon_end: '2027-12-31'`, `per_stock.<T>.catalyst[].in_horizon`.
- `Portfolio/weekly-reviews/weekly-review-bond-2026-06-08.yaml` — bond v1: top-level `horizon` (не `horizon_end`!), `summary.total_value_rub`, `per_bond.<ISIN>`.
- `Portfolio/stress/stress-2026-05-29-shell-d1-2027.yaml` — stress v1: `horizon: '2027-12-31'` (без `_months`), `baseline_spot`, `scenarios.A.factors`, `per_position.<T>.factor_betas` плоские.
- Объём legacy: 14 weekly-review + 9 stress = 23 файла v1 (НЕ мигрируются, D4-4).

**Ключевой код:**
- `skills/portfolio-integrated-view/scripts/aggregate_positions.py` — `DEFAULT_HORIZON_MONTHS` :42, `aggregate_macro` :290, `aggregate_div_or_carry` :388, `compute_catalyst_contribution` :499, `aggregate_idio` :615, `aggregate_position` :663, `_weighted_total` :733, `compute_portfolio_aggregates` :747 (dual spread CI :774–787), `run` :1134. Stdlib-only — сохранить.
- `skills/portfolio-scenario-stress/scripts/` — `build_stress_stub.py` (v1-эмит :163, хардкод horizon_end :149), `compute_per_position.py` (`compute_delta_pct` ≈ :850).
- `skills/ru-portfolio-advisor/scripts/build_weekly_{stock,bond}_stub.py` — v1-эмит :256/:332.
- `skills/save-to-library/scripts/assemble_artifact.py` — валидаторы (раздел 4 выше); `scripts/validate_schema.py` (корень репо) :223.
- `Claude-Memory/tools/portfolio-integrated-viewer.html` — `SUPPORTED` :903, normalize* :991/:1008, horizon-fallback :2714.
- Прецедент миграционного тулинга: `skills/ru-portfolio-advisor/scripts/migrate_catalysts_v1_to_v2.py` (METH-1) — образец стиля, если всё же понадобится точечная миграция.

---

## 11. Конвенции репозитория (соблюдать при реализации)

- **Язык — русский** везде (код-комментарии, доки, коммиты, тесты).
- **Никакой подгонки под конкретные данные:** тикеры/ISIN/scenario_id/верcии прогнозов — только из входных данных; горизонты — `DEFAULT_HORIZONS` + CLI/payload. Юнит-тесты — синтетика; боевые данные — только E2E-приёмка (§7), read-only.
- **Никакой ручной арифметики у LLM** — все числа через детерминированные скрипты (поэтому `compute_horizon_factors.py` и парсер `date_window`, а не «LLM посчитает»).
- **D3:** скиллы (кроме save-to-library/maintenance/data-loader) в `Claude-Memory/` напрямую не пишут. Фаза 4 этого не меняет; E2E-прогоны пишут только во временные файлы.
- **Сценарная независимость:** `factors_by_horizon` и MC-розыгрыш работают с любым набором scenario_id из данных; «при сценарии A делать X» в коде/SKILL.md — запрещено.
- **Схемы/контракты:** v1-валидаторы и v1-чтение НЕ удалять (backward-compat 1 major); перед правкой grep'ом сверяться с реальными артефактами Claude-Memory.
- **Коммиты** — группировать по смыслу: основной код / тесты / документация, отдельно по этапам.
- **Тесты** — гонять через `~/.pyenv/versions/3.12.9/bin/python3`; новые тесты зарегистрировать в корневом `CLAUDE.md` (секция «Запуск тестов»).

---

## 12. Обновления документации (по завершении)

- `docs/investment/TODO.md`: V2-A/V2-B — снять `DEFERRED`, отметить acceptance; секция «Фаза 4» — итоги.
- Корневой `CLAUDE.md`: зарегистрировать новые тесты (зависимостей новых НЕТ — stdlib-only по D4-5).
- `_shared-references/yaml-schemas.md` — финализировать v2-разделы (Этап 0 + фактические правки).
- `skills/*/SKILL.md` трёх скиллов + `references/` — по разделам 2/3/5/6.
- `docs/investment/README.md` §2: строка про этот план уже добавлена при его создании.
