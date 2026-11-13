# Implementation Spec — Conditions SSOT + Constraint Reconciliation Enforcement

**Для:** Claude Code (запускать в репозитории скиллов: `ru-portfolio-advisor`, `save-to-library`, `portfolio-integrated-view`).
**Автор контекста:** сессия ru-portfolio-advisor, 2026-06-29.
**Состоит из двух частей:** Part A — фикс рассинхрона (срочное), Part B — sibling `conditions.yaml` + независимый CRUD (новая архитектура). Части композируются: валидатор из Part A проверяет, что derived-вердикт согласован с условиями из Part B.

---

## Глоссарий

- **Условие (condition)** — отложенный триггер «жди X → сделай Y», с трёхшаговым жизненным циклом (pending → fired → удаляется).
- **gate-reviews.yaml** — durable SSOT фундаментального статуса (медленно, Mode 8). НЕ трогаем его роль.
- **conditions.yaml** — НОВЫЙ transient SSOT отложенных условий (быстро, Mode 1). Sibling-файл.
- **user_constraints** — текущий per-weekly механизм (Шаг 10.5). После миграции — *derived* отражение conditions.yaml, не источник.
- **reconcile_constraints.py** — детерминированный движок: condition/constraint + цена/дата → эффективный вердикт.

---

# PART A — Принудительный reconcile (фикс рассинхрона)

## A.0 Контекст бага

`weekly-review-stock-{date}.yaml` хранит `per_stock.user_constraints`. Они копируются между снапшотами через `carried_over_from`. В файле 2026-06-28 тикеры DOMRF, BTBR, NVTK перенесли условия из 2026-06-11 без прогона через `reconcile_constraints.py`:
- `advisor_verdict` разошёлся с ценой/датой (DOMRF: stored BUY, активный `price_gate_buy ≤2200` при цене 2218.6 ⇒ должно быть HOLD);
- `advisor_verdict_constraints: null` при активных ограничениях;
- `user_constraints[].active` — устаревший флаг.

Viewer рисует противоречивую карточку. Цель Part A — сделать класс рассинхрона невозможным.

## A.1 ru-portfolio-advisor — документация (без новых Write; правило D3)

В `references/analysis-process.md` (Шаг 10.5) и в pre-emit чеклисте `SKILL.md` (weekly-review-stock) добавить ОБЯЗАТЕЛЬНЫЙ шаг:

> Перед эмитом weekly-review-stock YAML прогнать `reconcile_constraints.py` по КАЖДОМУ per_stock с активными ограничениями (новыми и `carried_over_from`). Для каждого:
> - `unconstrained_verdict` = аналитический вердикт;
> - `advisor_verdict` = reconcile `final_verdict`;
> - `advisor_verdict_constraints` = список АКТИВНЫХ ограничений (пустой только если активных нет);
> - `user_constraints[].active` = из reconcile-оценки, НИКОГДА не копировать старый флаг.
>
> Эмитить `advisor_verdict`, отличный от reconcile-результата, — блокирующая ошибка.
> Цена — `per_stock.price_rub`, дата — `review_date`.

## A.2 save-to-library — блокирующая проверка в валидаторе

В `scripts/assemble_artifact.py`, ветка `validate-weekly-review-stock`, добавить детерминированную проверку (valid:false) для каждого per_stock с непустым `user_constraints`:

```
ref_date = review_date
price    = per_stock.price_rub          # если нет → price-gate проверки = yellow warning, не block
active, final = reconcile(per_stock)    # ВЫЗВАТЬ функции из reconcile_constraints.py, не дублировать
БЛОКИРОВАТЬ если:
  (a) advisor_verdict != final
  (b) есть активное условие, но advisor_verdict_constraints null/пусто
  (c) любой user_constraints[].active != пересчитанному is_active   (устаревший флаг)
  (d) есть user_constraints, но нет unconstrained_verdict           (правило инцидента 2026-05-13 — сохранить/усилить)
human_message: тикер, stored vs expected verdict, конкретное условие.
```

## A.3 Рефактор для переиспользования

Вынести `evaluate_constraint` и `apply_constraints_to_verdict` из `reconcile_constraints.py` в импортируемый модуль (например `constraint_engine.py` рядом). CLI/stdin-контракт `reconcile_constraints.py` НЕ менять. Валидатор save-to-library импортирует этот модуль.

## A.4 Регресс-тесты (Part A)

- **DOMRF**: stored BUY, unconstrained BUY, price_rub 2218.6, `user_constraints=[price_gate_buy expires price_below 2200, active]`, `advisor_verdict_constraints=null` ⇒ валидатор БЛОКИРУЕТ по (a)+(b).
- DOMRF после фикса (advisor_verdict HOLD + заполненный список) ⇒ проходит.
- **NVTK**: `price_gate_sell ≥1200`, price 947, verdict HOLD ⇒ по вердикту OK, но `advisor_verdict_constraints=null` ⇒ блок по (b).
- Тикер без `user_constraints` ⇒ поведение не меняется.
- Артефакты schema v1 ⇒ не затрагиваются (роутинг по `schema_version`).

---

# PART B — Sibling `conditions.yaml` + независимый CRUD

## B.0 Идея

Условия — это **очередь отложенных действий**, а не постоянный атрибут. Выносим определения условий в отдельный быстрый SSOT, которым владеет еженедельный флоу (Mode 1). Durable-исход срабатывания уходит мостиком в `gate-reviews.yaml`. `user_constraints` в weekly становятся *derived*-отражением, не источником.

Разделение:
- `conditions.yaml` = быстрая очередь триггеров (Mode 1, частые правки, CRUD).
- `gate-reviews.yaml` = медленный durable-статус (Mode 8).
- Срабатывание условия = мост transient → durable (`on_trigger.set_status` пишет в gate-reviews).

## B.1 Схема `Portfolio/conditions.yaml` (singleton)

```yaml
schema_version: "conditions@1.0"
last_updated: '2026-06-29'
conditions:
  - id: moex-divcapture-0708           # уникальный slug; авто-генерация {ticker}-{kind}-{ddmm}
    ticker: MOEX
    created: '2026-06-29'
    created_by: mode_1 | mode_4 | user
    trigger:
      type: date | price_above | price_below
      value: '2026-07-08'              # дата ISO ИЛИ число (цена)
    while_pending:
      verdict: HOLD                    # эффективный вердикт пока условие не выполнено
      note: 'держать до дивотсечки 08.07 (19.57₽)'
    on_trigger:
      action: 'TRIM до 8% L2, redeploy PLZL/RENI'
      set_status: reviewed_reduce | null   # опц.: толкнуть статус в gate-reviews при срабатывании
    state: pending | fired
    fired_date: null
    history:                           # append-only, опц.
      - {date: '2026-06-29', event: created, note: 'div-capture gate'}
```

**Валидатор схемы** (`conditions@1.0`): id уникальны; `trigger.type ∈ {date, price_above, price_below}`; `value` — ISO-дата для `date`, число для price; `state ∈ {pending, fired}`; `while_pending.verdict ∈ {HOLD, TRIM, BUY, SELL}`; `set_status ∈ gate-status enum | null`; ticker должен быть в snapshot ИЛИ в gate-reviews (orphan-warning иначе).

## B.2 Жизненный цикл — машина состояний (3 шага)

Выполняется на КАЖДОМ Mode 1 прогоне (и по запросу). Вход: текущие цены (snapshot/quotes) + today.

| Состояние | Условие | Действие в отчёте | Мутация conditions.yaml |
|---|---|---|---|
| 1. pending, trigger НЕ выполнен | `is_active == True` | «⏳ Условие `<id>` не выполнено (`<trigger>`). Вердикт: `<while_pending.verdict>`» | без изменений |
| 2. pending, trigger выполнен ВПЕРВЫЕ | `is_active == False` & `state==pending` | «✅ Условие `<id>` ВЫПОЛНЕНО (`<trigger>`) → `<on_trigger.action>`; статус → `<set_status>`» | `state: fired`, `fired_date: today`; если `set_status` — записать в gate-reviews (мост) |
| 3. fired в прошлый раз | `state == fired` | не рендерить | удалить запись (prune) |

`is_active` считать ТЕМ ЖЕ движком, что reconcile (date/price). Никаких хранимых флагов «на веру».

## B.3 `apply_condition.py` — детерминированный CRUD-исполнитель

Расположение: `save-to-library/scripts/apply_condition.py` (брат `apply_gate_review.py`). Stdlib + yaml. Атомарная запись с авто-бэкапом в `Portfolio/.backups/conditions-{ts}.yaml`. Каждая мутация обновляет `last_updated` + добавляет `history`.

Команды:

| Команда | Назначение | Обязательные аргументы |
|---|---|---|
| `add` | новое условие (state=pending, авто-id, created) | `--ticker --trigger-type --trigger-value --action` (опц. `--while-verdict` [def: текущий advisor_verdict или HOLD], `--set-status`, `--note`) |
| `close` | вручную закрыть (state=fired+prune на след. прогоне ИЛИ сразу remove) | `--id` или `--ticker` |
| `open` / `reopen` | вернуть fired→pending ИЛИ создать новое | `--id` (reopen) или add-набор |
| `edit` | изменить поля существующего | `--id` + изменяемые поля |
| `remove` | удалить по id | `--id` |
| `fire` | принудительно применить `on_trigger` сейчас | `--id` |
| `list` | показать все (фильтр `--ticker`, `--state`) | — |
| `evaluate` | прогнать цикл B.2: оценить все, prune fired, вернуть derived-состояние + render-блоки | `--prices <json|snapshot> --today` |

`evaluate` — это то, что зовёт Mode 1. Возвращает JSON: `{ticker: {effective_verdict, active_conditions[], render_block, status_pushes[]}}`.

## B.4 Путь записи и D3

`conditions.yaml` — **операционная очередь, не аналитический артефакт**, поэтому подпадает под scoped-исключение из D3 (которое покрывает аналитические артефакты: weekly-review/integrated-view/forecasts). Решение для реализации:

- Мутации `conditions.yaml` идут через `apply_condition.py` с авто-бэкапом.
- `ru-portfolio-advisor` Conditions Mode (B.5) МОЖЕТ звать `apply_condition.py` напрямую (это вызов детерминированного скрипта, не свободный `Write`/`Edit`). Это нужно для frictionless-UX «закрой условие» без прохода через save-to-library.
- Альтернатива (если хотим строгий D3): обернуть в `save-to-library` Workflow N. **Рекомендация: прямой вызов** — UX важнее, файл транзакционно-безопасен через бэкап. Зафиксировать выбор в `SKILL.md` явным исключением «conditions.yaml — операционный, не артефакт D3».

## B.5 ru-portfolio-advisor — Conditions Mode (независимый CRUD)

Новый режим (например **Mode 9 — Conditions Management**). Триггеры активации:
- «поменяй/измени условие», «закрой условие», «открой/добавь условие», «удали условие», «покажи условия», «условия по `<ticker>`».

Требования к UX (КЛЮЧЕВОЕ — без долгих вопросов):
- Детерминированный маппинг естественного языка → аргументы `apply_condition.py`. Поля: `ticker`, `trigger.{type,value}`, `on_trigger.action`, опц. `while_pending.verdict` (default = текущий advisor_verdict из последнего weekly, иначе HOLD), опц. `set_status`.
- Спрашивать ТОЛЬКО реально отсутствующее обязательное поле (ticker / trigger / action). Всё, что выводимо по умолчанию — не спрашивать.
- Примеры, которые должны работать одним проходом без уточнений:
  - «добавь условие на MOEX: если цена ≤2200, докупать и статус → reviewed_buy_more»
    → `add --ticker MOEX --trigger-type price_below --trigger-value 2200 --action "докупать" --set-status reviewed_buy_more`
  - «закрой условие по WUSH» → `close --ticker WUSH` (если несколько — показать список и попросить id, единственный вопрос).
  - «покажи условия» → `list`.
- Pure-CRUD (add/close/open/edit/list) НЕ требует snapshot. `fire`/`evaluate` требуют цены → snapshot.
- Conditions Mode НЕ дублирует анализ — он только CRUD над очередью.

## B.6 Mode 1 (weekly) — интеграция

В генерацию weekly-review-stock (Mode 1) добавить шаг ПЕРЕД эмитом:
1. `apply_condition.py evaluate --prices <snapshot> --today <review_date>`.
2. Применить B.2: для каждого тикера взять `effective_verdict` → это `advisor_verdict` в weekly; `unconstrained_verdict` = аналитический; `advisor_verdict_constraints` = активные условия (текст).
3. Вставить render-блоки (шаги 1/2 цикла) в MD-отчёт.
4. Prune (шаг 3) выполняется внутри `evaluate`.
5. Сработавшие `set_status` → записать в gate-reviews (через существующий путь Workflow M / `apply_gate_review.py`).

После этого Part A валидатор автоматически зелёный (advisor_verdict ≡ reconcile).

## B.7 Viewer — отображение на вкладке «Акции»

`portfolio-integrated-viewer.html`: источник условий для карточки — `conditions.yaml` (а не `per_weekly.user_constraints`). Рендерить:
- пилюля = `effective_verdict`;
- блок «⏳/✅ Условие: `<trigger>` → `<action>`» (статусы 1/2 из B.2).

`weekly.user_constraints` остаётся как derived-снимок для обратной совместимости, помечен `derived: true`.

## B.8 Миграция существующих user_constraints

Однократный скрипт/шаг: сконвертировать активные `user_constraints` из последнего weekly (DOMRF, BTBR, NVTK, MOEX, SBER, SBERP) в записи `conditions.yaml`:
- `price_gate_buy` → trigger `price_below`; `price_gate_sell` → `price_above`; `no_buy_until_date`/`manual+date` → `date`.
- `while_pending.verdict` = текущий (reconciled) advisor_verdict.
- `on_trigger.action` = из `re_entry`; `set_status` если очевиден (напр. MOEX → reviewed_reduce).
После миграции weekly перестаёт быть источником; его `user_constraints` помечаются `derived: true`.

## B.9 Тесты (Part B)

- `add` → запись появилась, id уникален, бэкап создан, `last_updated` обновлён.
- `evaluate` на MOEX (date 2026-07-08): today=2026-07-07 → pending, render «⏳»; today=2026-07-08 → fired, render «✅», `set_status` ушёл в gate-reviews; следующий `evaluate` (today=2026-07-09) → запись удалена.
- `close --ticker WUSH` → состояние fired/удалено, в отчёте больше не рендерится.
- `add` с price-триггером DOMRF (price_below 2200): price 2218.6 → pending; price 2199 → fired.
- orphan-тикер (нет в snapshot и gate-reviews) → warning при валидации.
- Conditions Mode: NL «добавь условие на MOEX если ≤2200 докупать статус reviewed_buy_more» → корректный `add` без доп. вопросов.

---

## Порядок реализации (рекомендуемый)

1. Part A (срочно, маленький blast radius): рефактор `constraint_engine.py` → валидатор save-to-library → тесты A.4. Чинит текущий баг навсегда.
2. Part B каркас: схема + валидатор `conditions@1.0`, `apply_condition.py` (add/close/open/edit/remove/list/fire/evaluate), бэкапы.
3. Part B интеграция: Mode 1 evaluate→render→prune→bridge; Conditions Mode (Mode 9); миграция B.8; viewer B.7.

## Инварианты (не нарушать)

- Обратная совместимость: v1-артефакты и записи без условий валидируются как раньше.
- Никаких сетевых вызовов в валидаторах; цены — из snapshot/price_rub.
- `reconcile_constraints.py` CLI-контракт неизменен; логика не дублируется.
- `gate-reviews.yaml` durable-роль не меняется; conditions только толкают `set_status` при срабатывании.
- Состояние условия — всегда derived (пересчёт по цене/дате), никогда не «на веру» из хранимого флага.
