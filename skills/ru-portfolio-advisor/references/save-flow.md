# Save-режим weekly review: поток сохранения (шаги 1–6)

> Вынесено из SKILL.md дословно при дроблении 2026-08-12 (этап 3, подготовка Max → Pro).

## Содержание

1. [Поток сохранения — шаги 1–6](#поток-сохранения--шаги-16)
2. [Именование файлов (Phase 10.4)](#именование-файлов-phase-104)
3. [Правила для артефактов](#правила-для-артефактов)

## Поток сохранения — шаги 1–6

Контекст: активирован режим сохранения (`--save-report` / `--save-to-library`).
НЕ выводи аналитический отчёт отдельным текстом в чат перед артефактами. Вместо этого:

1. Выполни анализ внутренне: загрузи snapshot, котировки, рейтинговые события по каждой позиции.

1a. **Определи горизонт(ы) обзора (schema v2 — multiple horizons).** Weekly-review v2
   считается на несколько горизонтов side-by-side. Два режима (полная спека —
   `references/yaml-schemas.md` §11.6):
   - **Скользящий** (`--horizons 6,12,24`, default): «N месяцев вперёд от даты обзора».
     Горизонты едут вперёд каждую неделю; удобно для стоячего forward-взгляда и diff.
   - **Якорный** (`--anchor-dates 2027-06-30,2028-06-30`): «к фиксированной дате-цели».
     На следующем прогоне с той же датой остаток срока сжимается (10→9 мес),
     доходность пересчитывается — согласовано с прогнозами на конкретную дату.

   **Если пользователь не задал горизонт явно — уточни перед запуском стаба:**
   найди предыдущий `Portfolio/weekly-reviews/weekly-review-{stock|bond}-*.yaml`,
   прочитай его `horizons` / `horizon_ends` / `primary_horizon` и спроси:
   «Использовать прошлый горизонт ({перечисли horizon_ends даты}) или задать новый?».
   - «прошлый» + он был **якорным** → передай те же `--anchor-dates`
     (= прежние `horizon_ends`), N пересчитается под новую дату обзора;
   - «прошлый» + он был **скользящим** → передай те же `--horizons`;
   - «новый» → уточни режим и значения.
   Только если предыдущего обзора нет — молча применяй default `--horizons 6,12,24`.

   `primary_horizon` (default 12 — «1 год») — горизонт, к которому привязан единственный
   `advisor_verdict` (D4-8). Per-horizon вердиктов НЕ плодить.

2. **ОБЯЗАТЕЛЬНО — запусти Python-стаб-генератор перед генерацией YAML:**
   - Для Mode 1 (stocks):
     ```bash
     python3 skills/ru-portfolio-advisor/scripts/build_weekly_stock_stub.py \
       --snapshot {path-to-portfolio-{date}.json} \
       --output /tmp/stock-stub-{date}.yaml \
       --sector-overrides {path-to-Claude-Memory}/sector-overrides.yaml \
       [--horizons 6,12,24 | --anchor-dates 2027-06-30,2028-06-30] [--primary-horizon 12]
     ```
     `--sector-overrides` — страховка от `sector: unknown` для бумаг без сектора
     в IntelInvest-выгрузке (цепочка: ie_model → snapshot.holdings → overrides;
     overrides не перекрашивают уже размеченные тикеры). Если снапшот собран
     loader'ом с тем же файлом — флаг избыточен, но безвреден.
   - Для Mode 2 (bonds):
     ```bash
     python3 skills/ru-portfolio-advisor/scripts/build_weekly_bond_stub.py \
       --snapshot {path-to-portfolio-{date}.json} \
       --output /tmp/bond-stub-{date}.yaml \
       [--horizons 6,12,24 | --anchor-dates 2027-06-30,2028-06-30] [--primary-horizon 12]
     ```
   - Скрипт детерминированно заполнит ~70% полей: `schema_version: 2` (число), `review_date: "{date}"` (строка в кавычках), `type`, `horizons`/`horizon_ends`/`primary_horizon` (Phase 4 multiple horizons), `snapshot_id`, `weight_real_pct`/`weight_ie_target_pct`/`weight_divergence_pp`/`on_iis`/`sector`/`price_rub`/`xirr`/`pnl_rub` для каждого тикера, `portfolio_summary` блок. Аналитические поля помечены строками `TODO_LLM_<hint>`.

2а. **Есть прошлый обзор того же класса — перенос делает скрипт, а не ты (RPA-23).** Не читай
   прошлый YAML/MD целиком и не пиши одноразовых merge-скриптов: 16.10.2026 это стоило 3–4 компакций
   и всего лимита сессии. Порядок:
   ```bash
   python3 skills/ru-portfolio-advisor/scripts/carry_over_weekly.py --kind stock|bond \
     --stub /tmp/{stock|bond}-stub-{date}.yaml --prior {прошлый weekly-review-*.yaml} \
     --output /tmp/{stock|bond}-carry-{date}.yaml --report /tmp/carry-report.json
   ```
   Скрипт заполняет TODO_LLM стаба значениями прошлого обзора (числа стаба главнее), переносит
   источники с ИХ датами `accessed_date` — **с отбором (RPA-37)**: свежие все, из старых — те, на
   которые ссылается катализатор или `*_basis`, плюс 3 самых новых (`--keep-old-sources N`,
   `--no-prune` — без отбора); отданные старые остаются в прошлых файлах. Отдаёт отчёт: новые бумаги («требует анализа»),
   выбывшие (→ `trades_since_prior`/`closed_positions`), катализаторы с прошедшей датой, текст
   `*_basis` с числами прошлой недели, бумаги, чей срез ограничений не перенесён (строит `reconcile_constraints.py`).
   Дальше ты пишешь **только изменения недели** в `delta.json`. Формат не выясняй по коду — образец
   с ключами твоего стаба и перечнем допустимых полей даёт `carry_over_weekly.py --kind stock|bond
   --example --stub {стаб}` (RPA-40; формат также в шапке скрипта:
   `per_item.set/append/unset`, `catalyst_add/remove/update`, `top.set/append`, `all_items`,
   `drop_items`) и перезапускаешь с `--delta delta.json --strict`. Правила:
   - перенесённые вердикты — не решение этой недели: каждый пересматривается по факту недели,
     условиям и плану (`reconcile_constraints.py` + `apply_condition.py crosscheck`, analysis-process Шаг 9.5); подтверждённый без
     изменений — так и написать в MD;
   - общий для многих бумаг источник (макро, аукцион, решение ЦБ) — один раз через `all_items.append`;
   - `accessed_date` новых источников — дата, когда ты реально открыл страницу в этом прогоне;
     перенесённым источникам дату не переставлять;
   - числа из стаба править нельзя (скрипт откажет) — только через `override_stub` с причиной в basis;
     поле, которое стаб посчитать не смог (`null`, напр. YTM флоатера), отчёт переноса называет
     (`stub_null_field`, с прошлым значением) — задай его через `per_item.set` с источником в basis;
   - блок `coverage` из прошлого обзора **не переносится**: каждый прогон кладёт свежий из
     `sweep_collect.py` через `top.set` (без него валидатор блокирует);
   - `review_date` стаба — день прогона, `snapshot_date` — дата снапшота; не править руками;
   - срез ограничений (`user_constraints`, `unconstrained_verdict*`, `advisor_verdict_constraints`) скрипт из
     прошлого обзора не переносит — положи выход `reconcile_constraints.py` через `per_item.set`;
   Чтобы пересмотреть каждый перенесённый вердикт, НЕ читай прошлый MD целиком — возьми выжимку
   (RPA-24, ≈5–10 КБ вместо 67–86 КБ MD): вердикт, уверенность, обоснование одной фразой, рейтинг,
   действующие условия, катализаторы с окном в ближайшие 14 дней или уже прошедшие:
   ```bash
   python3 scripts/prior_digest.py --prior {прошлый weekly-review-*.yaml} --today {review_date} \
     --conditions {root}/Portfolio/conditions.yaml --decisions {root}/Portfolio/decisions \
     --reports-dir {root}/Portfolio/reports --macro-dir {root}/macro-snapshots
   ```
   Разборы бумаг после прошлого обзора с записанными из них решениями и гейты из последних решений — в
   выжимке; отчёт разбора целиком не читать.
   Полный прошлый MD читай точечно — по бумаге с событием, а не целиком.

3. **Прочти stub (или результат переноса). Заполни оставшиеся TODO_LLM плейсхолдеры аналитическим контентом.**
   - **НЕ переименовывай ключи** (`share_actual_pct`/`ie_share_pct`/`delta_pct`/`catalysts` — drift, заблокирует save-to-library валидатор).
   - **НЕ удаляй TODO_LLM ключи** — заполни их (если данных нет — `null` с обоснованием в basis).
   - **НЕ меняй типы Python-заполненных полей** (схема: weight_real_pct — число, on_iis — bool, review_date — строка в кавычках).
   - Catalyst entry: каждая запись должна иметь полную структуру (`id, trigger, date_window, p, upside_pct/downside_pct, *_ci_pct, source, source_quality, macro_dependency`). **`date_window` обязателен** — consumer вычисляет принадлежность горизонту из него (в v2 поле `in_horizon` удалено, §11.3). Минимум 1 catalyst на тикер; добавляй по содержанию. **Сценарные ID для `macro_dependency` — из активной SSOT-матрицы `scenarios/` (catalyst-tree-rules.md, Hard rule 4)**: матрица существует независимо от стресса, «стресс не собран» — не причина оставить все катализаторы без привязки.

4. **MD собирает скрипт, ты пишешь только `changes.md` (RPA-33).** Не пиши отчёт целиком и не делай
   одноразовых `build_report.py` (26.10.2026: 66 КБ отчёта руками и ~26 шагов правки под линт):
   ```bash
   python3 {save-to-library}/scripts/apply_condition.py digest --root {root} --key {бумаги обзора через запятую} \
     --today {review_date} > {workdir}/conditions-digest.json
   python3 skills/ru-portfolio-advisor/scripts/render_weekly_md.py --yaml {workdir}/weekly-review-{stock|bond}-{date}.yaml \
     --changes {workdir}/changes.md --output {workdir}/weekly-review-{stock|bond}-{date}.md --embed-notes \
     --conditions {workdir}/conditions-digest.json
   ```
   Очередь условий в MD строится из выборки `--conditions` (резолюция сработавшего — фрагмент
   `<!-- cond: <id> -->` в changes.md, одна строка); без выборки раздела условий нет. Блоков состояния условий и
   директив старого формата в YAML обзора нет: состояние условий пишет только сайт, перенос их не берёт, валидатор
   ругается.
   `--embed-notes` обязателен (контракт A, 2026-10-26): фрагмент каждой бумаги («Что произошло / Рекомендация /
   Макро») скрипт разбирает в `per_*[id].week_note` и перезаписывает YAML — карточка во вьюере показывает
   «Что произошло за неделю» из него. Пиши фрагмент с подписями `**Что произошло:**` (пункты списком),
   `**Рекомендация:**`, при макро-связи — `**Макро:**`; текст без подписи уйдёт в «что произошло».
   `changes.md` — фрагменты с маркерами: `<!-- section: summary -->` и `<!-- section: actions -->`
   (обязательны); `urgent`, `macro`, `ie`, `risks`, `extra` (и `events` у облигаций) — по необходимости;
   `<!-- item: YDEX | Яндекс -->` (у облигаций — ISIN) — раздел бумаги с новостями недели («Что произошло /
   Рекомендация»): заголовок с вердиктом, вес/цену/план, гейт словами, катализаторы и источники добавит
   скрипт. Бумага без `item` уйдёт строкой в «Позиции без существенных новостей» из YAML. Таблицы,
   условия, покрытие, IE-дисциплина, топ-катализаторы, caveats, источники — из YAML. Неизвестный маркер,
   бумага не из YAML, нет обязательного раздела — код 2. Текст фрагментов скрипт не правит, но проверяет:
   голый «Mode N» и коды гейтов вне обратных кавычек — предупреждения в stderr (`--strict-text` — код 3);
   исправь их во фрагменте и пересобери. `--prior {прошлый weekly-review-*.yaml}` добавляет «было → стало»
   по цене (и YTM у облигаций). Требования к содержанию отчёта ниже остаются: **MD = полный аналитический отчёт** (та же глубина и структура, что была бы в чате): все прозовые секции по каждой позиции, макро-привязка, каталитические деревья, таблицы, источники. НЕ сокращать до одной сводной таблицы. Структура — `references/report-template.md`.

5. **YAML и MD — файлами, не блоками кода в чате** (RPA-38): YAML обзора 150–260 КБ ≈ 45–75 тыс.
   токенов — в блок кода не помещается, а попытка съедает контекст. Покажи оба файла пользователю
   (средство показа файлов среды) и дай краткое резюме (3–5 строк): ключевые метрики, число
   BUY/TRIM/HOLD, главный риск. Вопрос, требующий решения (гейты, условия, журнал), — **первым блоком**
   ответа с ответом «да / нет» (`references/gate-status-labels.md`), а не в конце списка.

6. «Файлы обзора выше — проверь вердикты и данные. Запусти `/save-to-library` (лучше в новой сессии:
   контекст этой уже занят сбором и сборкой).»

**Не записывай в библиотеку самостоятельно** (правило D3). Артефакты — файлы в рабочей папке → пользователь запускает save-to-library, который вызывает Python-валидатор. Тот же валидатор гоняй сам до выдачи — **по пути к файлу**, не вставляя YAML в команду:
```bash
python3 skills/save-to-library/scripts/assemble_artifact.py validate-weekly-review-stock --file {workdir}/weekly-review-stock-{date}.yaml
python3 skills/save-to-library/scripts/assemble_artifact.py validate-weekly-review-bond  --file {workdir}/weekly-review-bond-{date}.yaml
```
Если `valid: false` или `blocking_count > 0` — save-to-library **отказывает в записи** с указанием отсутствующих полей. Перегенерируй с учётом feedback'а.

### Делегирование заполнения (батч-агенты, опционально при ≥15 строках)

YAML weekly-review — 150–260 КБ, и это самый медленный участок всего прогона:
токены вывода генерируются последовательно. Описательную часть можно раздать
батч-агентам, **но только по конструкции ниже** — иначе экономия обнуляется.

- **Что делегируется:** `*_basis`-проза, `issuer`, источники с `accessed_date`,
  enum'ы (`credit_quality`, `source_quality`) — то, что
  переписывается из уже готового MD-отчёта.
- **Что НЕ делегируется (правило 18):** `advisor_verdict` и `confidence`,
  `p`/CI/`macro_dependency` катализаторов, `fundamental_score`, reconcile
  ограничений. Это идёт вниз в стресс и integrated-view — решения остаются
  у центральной модели.
- **Обмен только через файлы.** Агент пишет фрагмент в `/tmp/<part>-<batch>.yaml`
  и возвращает **путь + число заполненных полей**, ничего больше. Вернёт YAML
  текстом — 140 КБ приедут в родительский контекст дословно, и делегировать
  было незачем.
- **Сборка — Python**, не склейка моделью; затем обязательный прогон валидатора
  `assemble_artifact.py validate-weekly-review-{stock|bond}`: он и есть страховка
  от дрейфа (TODO_LLM, переименованные ключи, enum'ы, рассинхрон вердиктов).
- Модель — sonnet; батч 5–7 строк. Haiku на этой задаче не использовать:
  два инцидента 15.08 (BTBR, Аэрофьюэлз) показали, что схема + инструкция
  «только извлекай» не удерживают маленькую модель от подстановки своих данных.

**Дешевле делегирования — не генерировать лишнее:** прежде чем раздавать работу,
проверь, не считается ли поле детерминированно. С 2026-08-15 облигационный стаб
сам закрывает взвешенные агрегаты и подтягивает недостающие поля из снапшота
(см. ниже) — 888 плейсхолдеров прошлого прогона превратились в 815.

**Что Python-стабы делают за тебя (не повторяй):**
- Top-level метаданные (schema_version, type, review_date в кавычках, snapshot_id, …)
- Per-stock: weight_real_pct, weight_user_planned_pct (PRIMARY), weight_ie_target_pct (secondary), weight_divergence_vs_planned_pp (PRIMARY), weight_divergence_vs_ie_pp (secondary), weight_divergence_pp (DEPRECATED алиас vs_ie), on_iis, sector, price_rub, xirr, pnl_rub, ie_divergence_*
- Per-bond: name, on_iis, weight_real_pct, qty, value_rub, nominal_currency, bond_type (по эвристике), maturity_date / ytm_pct / duration_days / coupon_pct (через MOEX ISS API)
- Bond split merge (один ISIN на main + iis_3 → одна запись с qty_main/qty_iis/iis_share_pct)
- Portfolio summary: bonds_total_rub, target/actual share, deficit, by_account splits
- **Bond summary-агрегаты (с 2026-08-15):** `weighted_ytm_pct.value`,
  `weighted_duration_days`, `by_type_pct`, `maturity_ladder_pct` и по-валютные
  срезы — считаются скриптом в ДВУХ вариантах: по всей корзине и `_main_only`
  (без ИИС-3). **Сравнивать между собой можно только числа одного среза, и
  срез обязан быть назван в любой прозе про них.** Прецедент 15.08: MD-таблица
  §3.3 честно объявляла срез main (рублёвая 17.34% / 1136 дн, валютная 7.82% —
  внутри среза сравнимы), YAML нёс срез по всей корзине
  (`weighted_ytm_rub_pct: 16.47`), а `weighted_ytm_pct.basis` в том же YAML
  ссылался на «рублёвые выпуски (17,20%)» — третье число, не равное ни одному
  соседнему полю. Потребитель машинного артефакта различить срезы не мог.
- **Bond fallback MOEX → снапшот (с 2026-08-15):** `ytm_pct`, `maturity_date`,
  `duration_days`, `coupon_pct`, `next_coupon_date`, `offer_date`. ISS не
  резолвит ОФЗ по ISIN на TQCB (они торгуются на TQOB) — раньше это давало
  TODO_LLM по 11 суверенным выпускам и покрытие агрегатов 78,7%; теперь 100%.
  `SUR`/`RUR` нормализуются в `RUB`.
- **ОФЗ:** `issuer` («Минфин России»), `credit_quality: HIGH`, `credit_rating: null` — заданы правилом.
- **`verification_priority: null` у всех бумаг** — приоритет проверки ставит `stamp-report` save-to-library
  функцией движка после записи обзора (R28); модель поле не заполняет.

**Что ТЫ заполняешь (TODO_LLM плейсхолдеры):**
- Stock per-entry: fundamental_score + basis + sources, div_yield_12m_pct {value, ci_pct} + div_basis, catalyst[] (полная структура), advisor_verdict + confidence + basis
- Bond per-entry: issuer, credit_rating (+ agency), credit_quality, fundamental_score, catalyst[], advisor_verdict + basis
- Bond summary: weighted_ytm_pct {value, ci_pct}, weighted_duration_days, by_type_pct, by_credit_quality_pct, maturity_ladder_pct (агрегаты после анализа per-bond)
- Risks и caveats (top-level)

После заполнения — обязательный Pre-emit checklist в SKILL.md (§ Output modes).

### Именование файлов (Phase 10.4)

**Правило: имя MD = имя YAML, только расширение разное.** Никакого `weekly-review-{date}.md` без суффикса — вызывает конфликт при одновременном сохранении stocks + bonds в разных сессиях.

| Активные режимы | YAML | MD |
|---|---|---|
| Только Mode 1 (stocks) | `weekly-review-stock-{date}.yaml` | `weekly-review-stock-{date}.md` |
| Только Mode 2 (bonds) | `weekly-review-bond-{date}.yaml` | `weekly-review-bond-{date}.md` |
| Mode 1+2 (оба) | оба YAML последовательно | оба MD последовательно |
| Mode 3–8 без 1/2 | YAML не генерируется | MD не генерируется |

**Синхронизация дат при Mode 1+2.** `<date>` в обоих файлах = `snapshot.as_of_date`. При разных сессиях в разные дни — `portfolio-integrated-view` проверяет, что обе даты ≥ `snapshot_date − 14 дней`; превышение → warning HIGH о смешанном обзоре.

**Bonds-специфика YAML:**
- Ключ в `per_bond` — ISIN (для ОФЗ/корп) или MOEX-тикер.
- `bond_type ∈ {ofz, corp_rub, fx_replacement, floater, perpetual}`.
- `credit_quality ∈ {HIGH, MEDIUM, LOW}` — ОФЗ → всегда HIGH.
- `verification_priority` — не заполнять (ставит штамп save-to-library по вердикту, уверенности, условиям и гейту).
- Catalyst tree: **НЕ добавлять `id: redemption`** для стандартного погашения. `redemption` — только при реальном риске не-погашения (credit_quality LOW + active credit concern). Опционально `rate_cut_capital_gain` (duration > 2 лет), `credit_event` (credit_quality LOW).
- `summary` блок ОБЯЗАТЕЛЕН: `weighted_ytm_pct: {value, ci_pct}` (плоский формат), `weighted_duration_days: N` (число), `by_type_pct`, `by_credit_quality_pct`, `maturity_ladder_pct`. Опционально `weighted_ytm_pct_main_only` и `weighted_duration_days_main_only`.
- `last_corp_event` — только прошедшее событие (дата ≤ today). `next_corp_event` — ближайшее будущее; `null` если нет.

### Правила для артефактов

**Правила генерации catalyst tree** — в `references/catalyst-tree-rules.md`.
Методология формул и kind split — в `docs/investment/portfolio/methodology.md` §1 (METH-1, 2026-05-13).

**Обязательные поля каждого catalyst (для YAML):**
- `kind` (`binary` или `quantitative`) — METH-1, без него aggregator падает в legacy backward-compat с занижением.
- `source` (не null — иначе catalyst отбрасывается)
- `date_window` (обязательно) — consumer вычисляет принадлежность горизонту из него (v2; поле `in_horizon` удалено, §11.3).
- Для **binary**: `p ∈ (0, 0.95]`, `upside_pct`, `upside_ci_pct`.
- Для **quantitative**: `upside_by_scenario` (все 4 сценария), `upside_ci_by_scenario` (все 4). Без `p`.

**Классификация kind:** при сомнениях запустить
```bash
python3 scripts/classify_catalyst.py --catalyst-json '{"id": "...", "trigger": "..."}'
```
HIGH-confidence suggestion — следовать; MEDIUM/LOW — читать reasoning, override с явным `macro_dependency_basis`.

**ИИС-3 constraints:** позиции с `on_iis: true` не могут иметь `advisor_verdict: SELL` или `TRIM` без `advisor_verdict_constraints`.

**`fundamental_score: RED_FLAG`** — отдельное значение (не заменяет LOW). Использовать при: иске Генпрокуратуры, угрозе национализации, реальном риске дефолта/обнуления. `fundamental_score_basis` начинается с "RED FLAG: ...". Нельзя писать `fundamental_score: LOW` + "RED FLAG:" в basis — viewer не подхватит 🚩.

**Trust matrix для catalyst confidence** берётся из `Claude-Memory/INDEX.md` (subdomain weights, обновляются через memory-sync). Дисконт по `source_quality` — согласно `references/catalyst-tree-rules.md`.

