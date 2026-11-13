# План реализации V2-CUTOVER — миграция v1→v2 + удаление co-existence (handoff)

> **⚡ ИСПОЛНЕНО (данные + валидаторы) 2026-08-03** — итоговая сводка в
> [`TODO.md#v2-cutover`](../TODO.md#v2-cutover). Ключевые отклонения от этого плана,
> выясненные на живых данных: (1) инвентарь — 17 мигрируемых + 4 исключённых
> (`stress/_archive-pre-v2/`), а не 19; (2) DRIFT-2-гейт переопределён на структурный
> (detailed-валидаторы — save-гейты новых эмитов, архив не проходит даже живым v2 06-10);
> (3) DRIFT-1 отменён — normalize* вьюера оказались живой совместимостью
> (v2-slice synthesis + альт-имена текущих эмиссий), не мёртвым v1-шимом;
> (4) C-3 (aggregate_positions) отложен: обёртка мертва на живых данных, но на ней
> стоит базовый фикстур 152-тестового сьюта — снятие отдельным заходом.

**Дата:** 2026-06-11 · **Тип:** PLAN/handoff · **Задача:** [V2-CUTOVER](../TODO.md#v2-cutover) (тег `4-post`, Этап 6 плана Фазы 4)
**Скиллы:** `save-to-library`, `portfolio-integrated-view`, `ru-portfolio-advisor` + `tools/portfolio-integrated-viewer.html`
**Бандлит:** [DRIFT-1](../TODO.md#drift-1), [DRIFT-2](../TODO.md#drift-2), [DRIFT-3](../TODO.md#drift-3)
**Образцы стиля:** [`phase-4-v2-plan.md`](phase-4-v2-plan.md), [`phase-6-v3-ux-plan.md`](phase-6-v3-ux-plan.md)

---

## 0. Готовность: гейт снят (проверено на боевых данных 2026-06-11)

Условие старта в TODO — «ПОСЛЕ E2E-приёмки v2 на боевых данных (≥1 полный боевой v2-цикл)».
**Полный v2-цикл уже прошёл.** `Portfolio/integrated-views/integrated-view-2026-06-11.md`
собран сквозь весь пайплайн из schema-2 артефактов:

```
snapshot:      portfolio-2026-06-08.json                    schema 2.0
stress:        stress-2026-06-08-mfc-shell-d1-6-12-24.yaml  schema 2, горизонты 6/12/24
review_stock:  weekly-review-stock-2026-06-11.yaml          schema 2
review_bond:   weekly-review-bond-2026-06-10.yaml           schema 2
→ integrated-view@1.2, horizons:[6,12,24], primary 12
```

Вывод: **V2-CUTOVER полностью разблокирован.** Это чистый tech-debt — co-existence работает
(viewer и валидаторы понимают оба формата), срочности нет; задача = «убрать двойные ветки», а не
«починить сломанное».

> ⚠️ **Поправка к тексту TODO.** Формулировка V2-CUTOVER ссылается на удаление v1-веток «в
> `assemble_artifact.py`/**`validate_schema.py`**/`aggregate_positions.py`». **`validate_schema.py`
> не существует** (см. [STL-5](../TODO.md#stl-5) — он referenced, но не реализован). Реальные точки
> co-existence — §2 ниже.

---

## 1. Scope миграции (реальный инвентарь, не stale «23»)

TODO называет «23 v1-файла (14 weekly + 9 stress)» — это срез мая. **Фактически на Synology
сейчас 19 живых v1-артефактов** (остальные из grep-счёта — `.bak`):

| Тип | Живых v1 | Особые случаи | `.bak` на удаление (DRIFT-3) |
|---|---|---|---|
| weekly-review | **12** (11 split stock/bond + 1 combined) | `weekly-review-2026-05-06.yaml` — **старый combined-формат** (до split stock/bond) | `…stock-2026-05-11.yaml.bak`, `…stock-2026-05-11.yaml.pre-restore.bak`, `…bond-2026-05-12.yaml.bak` |
| stress | **7** | `stress-2026-05-06-zheleznyi-zanaves.yaml` (ранний нейминг); 20mo-locked файлы | `stress-2026-05-12-mfc-shell-d1-20mo.yaml.bak` |

**Не входит в scope:** уже-v2 артефакты (3 weekly + 1 stress + integrated-view-2026-06-11),
`forecasts/*.yaml` и `scenarios/*.yaml` (своя schema, не horizons-bump), snapshot JSON (отдельная
schema 2.0, не трогается).

---

## 2. Что держит co-existence сейчас (точные точки — что удалять)

| # | Где | Что | Действие |
|---|---|---|---|
| **C-1** | `tools/portfolio-integrated-viewer.html:1079` `normalizeWeeklyReview()`, `:1096` `normalizeStress()`, вызовы `:1183-1184` | DRIFT-1: client-side нормализация v1→v2-подобной формы при загрузке | Удалить функции + вызовы после миграции файлов |
| **C-2** | `skills/save-to-library/scripts/assemble_artifact.py` — `validate_stress` (214), `validate_weekly_stocks_review` (1306), `validate_weekly_bonds_review` (1493) | Роутинг `v2 = schema_version==2`, else **v1-ветка не трогается** | Убрать v1-ветки, оставить только v2-путь |
| **C-3** | `skills/portfolio-integrated-view/scripts/aggregate_positions.py:1631-1632` + h20-обёртки v1-входа (§V2-A backward-compat) | Принимает review без `schema_version==2` и оборачивает в h20 | Убрать v1-приём + авто-обёртку |
| **C-4** | `assemble_artifact.py:1807` `schema_version != "2.0"` | **НЕ ЭТО** — отдельная string-schema (scenario/iv-events), не weekly/stress int 1↔2 | Не трогать |

> Все три (C-1/2/3) держат именно horizons-bump (Фаза 4). METH-1 catalyst-bump (`migrate_catalysts_v1_to_v2.py`)
> — отдельный, уже отработан, в scope не входит, но служит **шаблоном CLI** (§3).

---

## 3. Решения V2-CUTOVER (D7-CUT-*) — зафиксировать при реализации

| # | Решение | Рекомендация по умолчанию |
|---|---------|---------------------------|
| **D7-CUT-1** | **Wrap-as-single-horizon vs recompute.** Чистая файловая миграция v1→v2 может только обернуть существующий единственный горизонт v1 (обычно 20mo) как `by_horizon.h20`/`factors_by_horizon.h20` — **она не способна выдумать 6/12/24** без повторного прогона моделей. Recompute (перегенерация stress/weekly на старых снапшотах) недетерминирован: FCA-прогнозы строятся на web_search, не воспроизводимы задним числом. | **Wrap-as-h20** (faithful, детерминированно, числа сохраняются). Recompute — НЕ делать. Именно поэтому «цена» из TODO (сдвиг дат горизонтов) **не возникает**, если выбрать wrap. |
| **D7-CUT-2** | **Combined-формат `weekly-review-2026-05-06.yaml`** (до split stock/bond). Мигратор split-схемы его не поймёт. | Либо отдельная ветка парсинга, либо **исключить из миграции** и пометить «legacy archive, не открывается в v2-viewer». Рекомендую исключить (1 файл, ранний, ценность архивная). |
| **D7-CUT-3** | **Migrate vs freeze-archive.** Альтернатива миграции 19 файлов — объявить старые v1 «замороженным архивом» и принять, что v2-viewer/валидаторы их не открывают. Но это ломает drill-down старых обзоров. | **Migrate** (как в TODO): всё становится v2, co-existence-код снимается без потери читаемости истории. |
| **D7-CUT-4** | **Порядок: код до данных или данные до кода.** Если снять v1-ветки до миграции файлов — старые файлы временно перестанут валидироваться/открываться. | **Данные → код:** сначала мигрировать все 19 + revalidate (DRIFT-2), убедиться что 0 v1 осталось, **потом** снимать C-1/2/3. |
| **D7-CUT-5** | **`schema_version` для мигрированных** — int `2` (как у боевых v2 weekly/stress), не string «2.0». | int `2`. |

---

## 4. Этапы реализации

### Этап 0 — бэкап и базлайн
- Synology: скопировать `Portfolio/weekly-reviews/` + `Portfolio/stress/` → `*.bak-cutover-<date>/` (или git-tar). Repo viewer — revertable через git; Synology viewer → `.bak-cutover-<date>`.
- Зафиксировать список 19 целевых файлов (snapshot инвентаря из §1).

### Этап 1 — `migrate_v1_to_v2.py` (weekly-review + stress)
- Новый скрипт (рекомендую `skills/portfolio-scenario-stress/scripts/migrate_v1_to_v2.py` для stress и расширить/parallel для weekly, либо общий с `--kind`). **Шаблон CLI/бэкап/in-place** — `skills/ru-portfolio-advisor/scripts/migrate_catalysts_v1_to_v2.py` (METH-1): `migrate(input, output)` + `_cli()` argparse.
- Трансформация (D7-CUT-1, wrap-as-h20):
  - **weekly-review:** добавить `schema_version: 2`, `horizons: [<v1-horizon>]`, `horizon_ends`, `primary_horizon`; перенести плоские `expected_pct`/CI в `by_horizon.h<N>`; убрать `catalyst[].in_horizon` (consumer вычисляет из `date_window`).
  - **stress:** добавить `schema_version: 2`, `horizons`/`horizon_ends`/`primary_horizon`, `scenarios[].factors_by_horizon.h<N>` из плоских `factors`, `per_position[].by_horizon.h<N>` из плоских полей, `portfolio_level_by_horizon`.
  - `weekly-review-2026-05-06.yaml` (combined) — исключить (D7-CUT-2).
- Прогнать на 19 файлах; **бэкап до прогона** (Этап 0).

### Этап 2 — DRIFT-2: bulk re-validate
- Прогнать все мигрированные YAML через v2-валидаторы (`assemble_artifact.py` `validate_weekly_*`/`validate_stress`, v2-ветка). 0 ошибок — гейт перехода к Этапу 3.
- Проверить инвариант coverage (макро-горизонт ≥ горизонта анализа) на мигрированных.

### Этап 3 — снять co-existence код (C-1/2/3), только после Этапа 2
- **DRIFT-1 (C-1):** удалить `normalizeWeeklyReview`/`normalizeStress` + вызовы из viewer (оба зеркала).
- **C-2:** в `assemble_artifact.py` убрать v1-ветки из трёх `validate_*`; оставить v2-путь; обновить docstring-маршрутизацию.
- **C-3:** в `aggregate_positions.py` убрать приём v1-входа и h20-авто-обёртку; обновить 108 v1-регресс-тестов → их инварианты должны переехать на «вход уже v2» (или быть удалены как покрывавшие снятую ветку).
- Прогнать все тест-сьюты трёх скиллов; `node --check` viewer.

### Этап 4 — DRIFT-3 + cutover-date + зеркала
- Удалить 4 `.bak` (§1) после подтверждения стабильности мигрированных.
- Записать **cutover-date** в корневой `CLAUDE.md` (раздел про двухслойную/schema-архитектуру).
- Зеркала viewer идентичны; справки (`viewer-help.md` + `portfolio-workflow-guide.md`) — если co-existence упоминался, снять.
- Закрыть в TODO: V2-CUTOVER + DRIFT-1/2/3.

---

## 5. Acceptance

- [ ] `migrate_v1_to_v2.py` существует, покрыт тестами (wrap-as-h20, in_horizon удалён, combined исключён); прогнан на 19 боевых v1 с бэкапом.
- [ ] Bulk re-validate (DRIFT-2): 0 v1-файлов осталось в `weekly-reviews/` + `stress/`; все проходят v2-валидатор.
- [ ] Co-existence снят: 0 вхождений `normalizeWeeklyReview`/`normalizeStress` в viewer; v1-ветки в `assemble_artifact.py`/`aggregate_positions.py` удалены; тесты зелёные.
- [ ] **Регрессия:** мигрированный v1-файл, прогнанный через v2-консьюмер, даёт те же числа на своём горизонте, что v1-файл через (теперь удалённую) v1-ветку **до** миграции (snapshot ожиданий до Этапа 3).
- [ ] 4 `.bak` удалены (DRIFT-3); cutover-date в `CLAUDE.md`; зеркала идентичны.
- [ ] Боевой `integrated-view-2026-06-11` (уже чистый v2) открывается без изменений.

---

## 6. Риски и заметки

- **Combined-формат 2026-05-06** — единственный файл, который мигратор split-схемы не съест (D7-CUT-2). Не уронить прогон на нём; исключить явным фильтром.
- **108 v1-регресс-тестов** `aggregate_positions` написаны как «v1-вход → h20-обёртка == v1-числа». При снятии C-3 они теряют смысл (ветки нет) — либо переписать на «v2-вход напрямую», либо удалить с пометкой. **Не оставлять висящими.**
- **Бит-в-бит история** — при wrap-as-h20 (рекомендация) **сохраняется**; «цена» из TODO (сдвиг дат) возникает только при recompute, который мы не делаем (D7-CUT-1).
- **Порядок данные→код** (D7-CUT-4) критичен: снять валидаторные ветки раньше миграции = временно нечитаемые файлы.
- **Два зеркала viewer** — правки C-1 в обоих (CLAUDE.md «Синхронизация справки вьюера»).
- **Срочности нет:** co-existence стабилен; делать, когда захочется убрать долг, а не под давлением.

---

## 7. Что этот план НЕ делает

- Не запускает recompute исторических прогнозов (недетерминирован; D7-CUT-1).
- Не трогает METH-1 catalyst-bump (отдельный, отработан), snapshot schema 2.0, forecasts/scenarios.
- Не реализует [STL-5](../TODO.md#stl-5) `validate_schema.py` (отдельная задача; здесь только зафиксирована поправка, что текущий роутинг — в `assemble_artifact.py`).
- Не закрывает V2-VIEW doc-drift (устаревший «Что осталось» под `#v2-view`) — отдельная косметика.
