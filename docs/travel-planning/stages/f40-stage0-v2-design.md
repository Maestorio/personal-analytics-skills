# F-40 — Stage 0 v2 + Stage 4/5 reshape + Iteration loop (дизайн)

**Версия:** 1.0
**Дата:** 2026-05-26
**Статус:** design review

Дизайн-документ для **архитектурного редизайна** Stage 0 + переразделения
ответственностей Stage 4 / Stage 5 + добавления iteration loop (F-41).

Это **спецификация перед имплементацией**, не сама имплементация.
После апрува — превращается в правки `references/stages/*.md`, `SKILL.md`,
`storage-and-naming.md` + новые тесты + регрессионная валидация.

---

## 1. Контекст и постановка задачи

### 1.1 Что было выявлено Страна Г-валидацией

| Симптом | Корневая причина |
|---|---|
| LP=6 ночей перегруз, пустые полудни D9-11 | Stage 0 зашил «LP — обязательный hub» в variant без знания, что POI density LP реально на 3-4 ночи |
| Tonle Sap не в 33 POI Stage 3 | DR воронка работала только по pre-selected регионам Stage 0 → если регион не выбран, его POI теряются окончательно |
| Большой круг Ангкора развалился на отдельные POI | Stage 3 не имеет cluster mechanism — но это deferred к F-36 |
| Stage 4 + Stage 5 дублируют day-by-day работу | Boundary размытая, Stage 4 пишет «черновик per day», Stage 5 «уточняет» — двойная работа |
| После Stage 5 «слишком плотно» — приходится в Stage 0 | Нет re-entry mechanism, итерации = re-run всего пайплайна, включая дорогой DR |

### 1.2 Корневая проблема

**Stage 0 принимает route-decision до evidence.** LLM выбирает 3-5 регионов и строит
3 варианта на основе своего «среднего знания» о направлении, без проверки через
DR. Когда выясняется (после Stage 3), что POI density не соответствует ожиданию —
исправлять уже некуда: variant уже зафиксирован, regions замкнуты.

**Что нужно:** evidence должен предшествовать route-decision. Решение «какие
регионы в финальном плане» делается **после** того как DR-evidence собран,
не до.

### 1.3 Цели редизайна

1. **Evidence-driven region selection.** Variant'ы строятся на базе собранного
   POI pool, не на «среднем знании» LLM.
2. **Visible region decision.** Пользователь явно тегирует регионы (обязательно
   / можно / не интересно) после видения POI evidence.
3. **Stage 4 vs Stage 5 чистый boundary.** Stage 4 = shape (макро), Stage 5 =
   detail (микро). Никакого дублирования.
4. **Iteration loop.** Re-entry в post-Stage 3 без потери дорогого DR.

---

## 2. Принципы и инварианты

Эти принципы не должны быть нарушены имплементацией. Если возникает
противоречие — переспросить пользователя, а не выбирать в дизайне «как
удобнее».

### И-1. Evidence перед route

Никакая стадия не принимает решение о route без DR-evidence. Stage 0 v2
**не** выбирает финальные регионы — он формирует **longlist** для DR.

### И-2. Ключевые решения за человеком

- Stage 0 v2 Akt A: пользователь подтверждает longlist + tempo + country quota.
- Stage 3 → Stage 4 touchpoint: пользователь тегирует регионы.
- Stage 4 v2: пользователь выбирает variant.
- Stage 5 v2: пользователь принимает final.

Скилл **никогда не выбирает за пользователя**. При неопределённости —
эскалирует с явным выбором.

### И-3. Атомарность стадий

Каждая стадия — одна атомарная задача. Stage 0 v2 «двухактная», но обе акта
— часть одной задачи «scope longlist», без артефакта между ними. Внешне
стадия остаётся одним deliverable (`0_scope.md`).

### И-4. Stable / mutable разрез

Артефакты Stage 0, 1, 2, 3 — **stable** (immutable после завершения). Теги,
feedback, Stage 4/5 — **mutable** (мутируемы между итерациями).

### И-5. Совместимость с архитектурными принципами скилла

- Self-contained (никакие зависимости от других skill'ов вне core anthropic).
- Никаких curated DB паттернов «не-canonical regions per country».
- Скилл сценарно-независим — не встраивает специфическую логику для отдельных
  стран в SKILL.md / references.

### И-6. Пользователь не правит YAML руками

Все user-facing файлы — **markdown с понятной человеком структурой**.
YAML существует только как машинный контракт между стадиями и **генерируется
скиллом** из markdown (либо при сборке артефакта, либо парсингом
свободных комментариев пользователя). Пользователь, читающий поток POI,
не пойдёт обратно в YAML-шапку отмечать значения — это против эргономики.

Конкретно:
- **Теги регионов** ставятся прямо в Stage 3 markdown рядом с региональным
  заголовком (или короткой строкой между заголовком и POI), не в
  отдельном `user_region_tags.yaml`.
- **POI-комментарии** — под POI в Stage 3 md (как и было).
- **Iteration feedback** — пользователь при re-run прикладывает старые
  артефакты и пишет комментарии в чате; никаких `iteration_feedback.md`
  для ручного заполнения.
- **YAML внутри артефакта** — генерируется скиллом, не правится. Если
  пользователь хочет изменить — правит markdown и просит скилл
  перегенерировать YAML.

---

## 3. Pipeline после редизайна

```
Stage 0 v2 [Akt A: dialog → Akt B: longlist]
  ↓ 0_scope.md (6-8 regions longlist + reserve pair-bindings + tempo + country_quota)
Stage 1 [DR по longlist] → 1_dr_reports.md
Stage 2 [Similarity] → 2_similarity.md
Stage 3 [POI aggregation + cluster units] → 3_poi_pool.md
  ↓ touchpoint: user правит POI комментарии + создаёт user_region_tags.yaml
Stage 3 freeze point (stable) ════════════════════════
user_region_tags.yaml (mutable: обязательно / можно / не интересно)
iteration_feedback.md (optional, mutable)
Stage 4 v2 [variant shape] → 4_variants_v{N}.md
  ↓ user выбирает variant
Stage 5 v2 [day-by-day] → 5_final_plan_v{N}.md
  ↓ опционально: re-entry → новая итерация Stage 4 v{N+1}
```

### 3.1 Сравнение ответственностей стадий (старое vs новое)

| Stage | Старое | Новое |
|---|---|---|
| 0 | Выбрать 3-5 регионов + построить 3 variant'а | **Akt A:** диалог про universe (12-15) + tempo math + country quota + non-canonical pass + 3 вопроса пользователю. **Akt B:** longlist 6-8 с reserve pairs. **Никаких variant'ов.** |
| 1 | DR по 5 регионам выбранного variant'а | DR по 6-8 регионам longlist'а |
| 2 | Similarity по узкой выборке | Без изменений (просто больше регионов на входе) |
| 3 | POI aggregation, region-first, user комментарии | + cluster units (F-36) + per-region abundant/scarce (F-37) |
| **3 → 4 touchpoint** | — | User тегирует регионы 3 ведра (обязательно / можно / не интересно). Может редактировать POI комментарии. |
| 4 | Распределение ночей + day-by-day POI + бюджет + транспорт + titles + RED FLAG | **Shape only:** выбор регионов из longlist согласно тегам + ночи + region order + open-jaw (F-33) + relative cost rank ($/$$/$$$) + sacrifices list + flavor sample. **БЕЗ** day-by-day, **БЕЗ** точного бюджета. |
| 5 | Финальный day-by-day, уточнение Stage 4 | **Owns** day-by-day POI selection + конкретный транспорт + отели + конкретный бюджет per day. Enforce F-38 (no empty afternoons), F-39 (stop-over ясность). |

---

## 4. Stage 0 v2 — спецификация

### 4.1 Akt A — диалог

#### 4.1.1 Цель

Информировать пользователя о region universe направления + per-trip mood +
country quota → получить input для Akt B.

#### 4.1.2 Поток

**Шаг 1 (LLM):** Web search + analysis → формирует region universe для
направления.

- Перечисляет регионы (обычно 8–15; конкретное число зависит от того,
  что направление физически содержит — см. §4.1.2.bis про размер).
- Для каждого: **2–3 предложения**, **фактических** (не рекламных).
  Что есть в регионе и почему это **может быть интересно конкретно
  этому профилю** (профильно-релевантные факты — архитектурный стиль,
  тип ландшафта, специфика гастрономии, длительность треков, и т.п.).
  - **Запрещено:** «вы почувствуете себя …», «жемчужина страны»,
    «must-see», «открой для себя», «магия места», маркетинговые штампы.
  - **Обязательно:** конкретные факты — что за объекты, какие
    активности, какая сезонность, какие реальные ограничения.
- В конце каждого регионального описания — компактная служебная строка:
  `Density: HIGH | MED | LOW · Сезон в {заданный_месяц}: {ok | risk | bad}`.
- Density tag — оценка LLM «сколько ночей content внутри региона».
- **Non-canonical pass:** явный mental loop «для каждого профильного
  интереса — есть ли регион вне mainstream guidebook, который этому
  интересу соответствует?». Найденные non-canonical регионы помечаются
  отдельной строкой `Non-canonical: причина соответствия профилю`.

**Шаг 2 (LLM):** Информационный блок + расчёт.

- **Universe summary:** «нашёл ~M регионов в `{назначение}`».
- **Density warning** (если применимо):
  - Country density: «`{страна}` имеет всего ~K значимых регионов — N=K
    значит видишь всю страну как gazetteer».
  - Если формула даёт N > 8 (ceiling) — предупредить про DR-bandwidth
    и предложить split-trip.
- **Tempo math:** «для `{N}` дней при longlist=`{L}` → ~`{N/L}` ночей/регион
  (slow / balanced / active)».
- **Формула N (longlist size):** см. §4.1.2.bis ниже — не одна простая
  формула, а контекстуально-зависимая.
- **AI-bandwidth ceiling note:** «N>8 — DR теряет качество; рекомендую разбить
  на 2 trip-segments».

**Шаг 3 (LLM → user):** 3 вопроса в одном batch'е (НЕ по одному):

1. **Mood per-trip:** «эта поездка — slow (3-4 ночи/регион, глубокое погружение)
   / balanced (2-3) / active (1-2, насыщенный темп)?»
2. **Country quota** (только если multi-country): «баланс по странам или
   акцент на одну? (например: K1=`{country1}` — пропорционально, K2=`{country2}`
   — больше, K3=`{country3}` — транзит)»
3. **Must-haves и skip'ы из universe** (опционально): «есть ли в списке выше
   что-то, что точно должно войти в longlist (must-have) или точно нет
   (skip-now)?»

**Шаг 4 (пользователь):** Отвечает в одном сообщении на 3 вопроса.

**Шаг 5 (LLM):** Переходит к Akt B (тот же chat-turn, без промежуточного
артефакта).

#### 4.1.2.bis Размер longlist'а зависит от формата запроса

Формула N не одна — она зависит от **формата поездки** (что пользователь
изначально хочет). Три типовых сценария:

**Сценарий А — multi-region tour** («посмотреть основные достопримечательности
Норвегии за 3 недели», «3 страны ЮВА за 2.5 недели», «север Страна В за 12 дней»):
- `target_count = ceil(days / 3)` — средние 3 ночи на регион.
- `longlist_count = ceil(target_count * 1.3)` — 30% reserve.
- **Ceiling:** 8 (DR-bandwidth).
- **Floor:** `ceil(available × 0.7)` если доступно мало регионов.

**Сценарий Б — single-base trip** («2 недели в Анталии», «10 дней в Киото и
вокруг», «жить в Дахабе и ездить»):
- Longlist size = 1 регион (базовый) + 2-4 day-trip направления.
- DR-промт работает иначе: основная база + radial day-trips.
- Stage 4 v2 не строит variants по «выбору регионов» — все варианты
  внутри одной базы, различаются POI-плотностью и темпом активностей.
- Сценарий маркируется в Stage 0 v2 YAML: `trip_format: single_base`.

**Сценарий В — explicit user list** («Сеул + Пусан + Кёнджу, остальное на
твой выбор» / «обязательно Vientiane, Pakse, Bolaven; что ещё?»):
- Пользователь даёт явный список из ≥3 регионов как `pre_committed_places`.
- Akt A показывает universe, помечает обязательные, предлагает 2-3
  дополнительных кандидата (если есть пространство).
- `longlist_count = |pre_committed| + 1..3 дополнительных`.

**Как Akt A детектит сценарий:**
- Запрос содержит «жить в», «база», «оттуда ездить», «day-trip из» → Б.
- Запрос содержит явный список ≥3 регионов с «обязательно» → В.
- Иначе → А.

При неясности — **спросить в шаге 3 одной строкой**: «формат поездки:
multi-region tour / single-base trip / explicit list?». Не угадывать.

#### 4.1.3 Стиль диалога

- **Краткость:** Akt A целиком умещается в 1 LLM-message ≤ 60 строк.
- **Без формы.** Это **информирование + 3 вопроса**, не form-wizard.
- **Не задавать вопросы по одному.** Один batch.
- **Если пользователь говорит «выбери сам»:** Akt A graceful fallback —
  скилл предлагает defaults и идёт в Akt B без задержки.

#### 4.1.4 Что НЕ делает Akt A

- НЕ выбирает финальные регионы (это Akt B + Stage 4).
- НЕ строит variants (нет в Stage 0 v2 вообще).
- НЕ оценивает POI (это Stage 3).
- НЕ называет цены.

### 4.2 Akt B — longlist

#### 4.2.1 Цель

Формализовать longlist 6-8 регионов с reserve pairs + tempo + country quota
в YAML + markdown артефакт `0_scope.md`.

#### 4.2.2 Содержание

**Region universe (12-15)** — полный список с density tags, остаётся в
артефакте для прозрачности (пользователь видит, что было отброшено и
почему).

**Longlist (6-8)** — выбранные регионы. Каждый:
1. Название + состав ключевых мест
2. Принципиальное содержание (1-2 предложения, без клише)
3. Минимум и оптимум ночей
4. Релевантность профилю + явные конфликты
5. Сезонные особенности
6. Логистическая стоимость включения
7. Уровень туристической нагрузки 0-10
8. Особые ограничения
9. **Density tag:** HIGH / MED / LOW
10. **Reserve pair binding:** если регион — reserve substitute для другого,
    указать `reserve_for: {другой_регион}` + `substitute_reason: …`

**Excluded regions (5-9)** — region universe minus longlist. Каждый — 1-2
строки + явная причина исключения (логистика / сезон / mood / уже покрыто).

**Tempo + country quota** — в YAML и явно в honest assessment.

**Non-canonical found** — явная подсекция (поглощает F-14.E):
- Перечислить 2-3 hidden-gem региона из non-canonical pass'а.
- Для каждого: профильное попадание + статус (в longlist или исключён).

**Honest assessment** — 1 абзац: какие регионы «уверенные кандидаты», какие
«пограничные», какие открытые вопросы. Без выбора за пользователя.

**Не строит variants.** Раздела `## Предложенные пакеты` больше нет.
`## Решение` тоже нет — теперь выбор regions делается через теги после
Stage 3, не в Stage 0.

#### 4.2.3 YAML schema (Stage 0 v2)

```yaml
---
trip_id: {trip_id}
stage: 0_scope
schema_version: 2                      # бэкворд-совместимость
travelers_profile: profiles/{profile_id}.md
created: YYYY-MM-DD
duration_nights: N
season: {season_descriptor}
home_city: {home_city}
trip_start_city: {trip_start_city}
home_eq_start: {true|false}
pre_committed_places: [...] | null
trip_wishes:
  - "пингвинов"
  - ...

# Stage 0 v2 specifics
tempo: slow | balanced | active        # per-trip mood (Akt A Q1)
country_quota:                         # Akt A Q2; null для single-country
  - country: "Страна Г"
    weight: proportional               # | major | minor | transit
  - country: "Страна Г"
    weight: proportional
  - country: "Таиланд"
    weight: transit

longlist:                              # 6-8 регионов (Akt B output)
  - region: "Ангкор и Страна Г"
    country: "Страна Г"
    density_tag: HIGH
    nights_min: 2
    nights_optimum: 4
    reserve_for: null                  # либо null, либо substitute для region X
  - region: "Северный Страна Г — Нонг Кхьяу"
    country: "Страна Г"
    density_tag: MED
    nights_min: 2
    nights_optimum: 3
    reserve_for: "Страна Г"        # substitute pair — если LP отпал, NK берёт
    substitute_reason: "тот же archetype 'тихий горный север Страна Г'"
  - ...

excluded_regions:                      # 5-9 — что отброшено и почему
  - region: "Кратиэ"
    reason: "логистическая изоляция, добавляет 2 ночи перевозок"
  - ...

content_density_overrides:             # как было
  - region: "Ангкор и Страна Г"
    profile_max_nights: 3
    observed_optimum_nights: 4
    reason: "..."

non_canonical_regions:                 # F-14.E поглощено
  - region: "Нонг Кхьяу"
    interest_match: "карст + треккинг"
    status: in_longlist                # | excluded
  - region: "Plain of Jars"
    interest_match: "археология как древняя архитектура"
    status: excluded
    reason: "сезонная недоступность"

# computed metrics
total_regions_analyzed: 14             # universe size
longlist_count: 7
formula_target_nights_per_region: 2.4  # duration_nights / longlist_count
---
```

#### 4.2.4 Output schema markdown тело

```markdown
# Stage 0 v2 — Региональное сужение: {назначение}, {сезон_год}

## Контекст для следующих стадий
{5-8 строк}

## Region universe ({total_regions_analyzed})
### {Регион 1} — {1-фраза суть} (HIGH/MED/LOW)
### {Регион 2} — ...
(полный список с 1-строчным описанием)

## Longlist ({longlist_count}) — для DR Stage 1

### {Регион 1}
{6-10 строк по 8+2 параметрам, включая density_tag, reserve_for, override}

### {Регион 2} — RESERVE for {Регион 1}
{6-10 строк + явный substitute_reason}

(6-8 регионов всего)

## Excluded regions

### {Регион X}
{1-2 строки + причина}

## Non-canonical found
- {регион} — {interest_match} — {status, reason}
- ...

## Tempo + country quota
- Tempo: {slow|balanced|active}
- Country: {Страна Г: proportional, Страна Г: proportional, Таиланд: transit}
- Math: {N} дней / {longlist_count} регионов = ~{X} ночей/регион среднее

## Honest assessment
{1 абзац: уверенные / пограничные / открытые вопросы}

## Следующий шаг
Stage 1 (DR) запускается по longlist (всем 6-8 регионам). DR соберёт
evidence по каждому, не только по «канонически популярным» — выбор
финальных регионов делается **после** Stage 3 через тегирование.
```

#### 4.2.5 Что миграции из старого Stage 0

| Старое | Куда |
|---|---|
| `selected_regions` YAML | Удаляется (выбор больше в `user_region_tags.yaml`) |
| `## Предложенные пакеты` | Удаляется (variants больше в Stage 4) |
| `## Решение` | Удаляется (выбор через теги) |
| `total_regions_analyzed` | Сохраняется |
| `content_density_overrides` | Сохраняется |
| `trip_wishes`, `home_city`, `trip_start_city` etc. | Сохраняются |

### 4.3 Storage и naming

- `0_scope.md` — один файл per trip (immutable после Stage 0 v2 завершения).
- Storage: `{travel_root}/trips/{trip_id}/0_scope.md` (тот же путь как
  раньше).
- Backward compat: `schema_version: 2` явно указывается; старые
  `0_scope.md` без поля интерпретируются как v1 и требуют миграции
  (если пользователь хочет re-run на v2 архитектуре).

---

## 5. Stage 3 → Stage 4 touchpoint

### 5.1 Цель

Пользователь, видя POI evidence (Stage 3), выражает свои предпочтения по
регионам через 3 тега. Этот сигнал — input для Stage 4 v2.

### 5.2 3-tag system

| Тег | Семантика | Влияние на Stage 4 |
|---|---|---|
| `обязательно` (must) | Без региона поездка бессмысленна | Stage 4 обязан включить во **все** variants. Если 2+ must конфликтуют логистически — escalate к пользователю с явными опциями |
| `можно` (can) | Нейтральное отношение, на усмотрение скилла | Stage 4 распределяет по variants для **дифференциации** — пространство манёвра |
| `не интересно` (skip) | Не хочу видеть в плане | Stage 4 не включает ни в один variant |

**Default behavior:** если пользователь не пометил никакие регионы — Stage
4 трактует всё как `можно` → строит variants чисто на основе логистики +
density. Это валидно (пользователь делегирует выбор).

### 5.3 Где пользователь ставит теги (И-6 совместимость)

**Не в отдельном YAML.** Stage 3 markdown получает в **региональном
заголовке** компактное поле для тега:

```markdown
### Регион {Название} — {N} POI · **тег:** _____

— режим: abundant/scarce (HIGH-авторов: X)

— описание региона из Stage 0 (2-3 предложения, скопированные через тонкий
  passthrough — чтобы пользователю не приходилось скроллить в Stage 0)

{POI 1, POI 2, ...}
```

Пользователь, читая поток POI:
1. **Над каждой региональной секцией** видит строку `**тег:** _____`.
2. **Дописывает руками** одно из трёх слов: `обязательно`, `можно`,
   `не интересно`. Поддерживаются короткие синонимы: `must`, `ok`/`да`,
   `skip`/`нет`.
3. Если оставил пустым (`_____`) — Stage 4 трактует как `можно`.

**Никакого отдельного YAML-файла `user_region_tags.yaml` не существует.**
Stage 4 при чтении парсит Stage 3 markdown и извлекает теги из строк
`**тег:**` после каждого регионального заголовка.

### 5.4 Парсинг тегов скиллом

Stage 4 при загрузке Stage 3 md:
1. Для каждого `### Регион {имя} — {N} POI` ищет следующую строку
   с `**тег:** {слово}`.
2. Нормализует слово в одно из трёх: `обязательно` / `можно` /
   `не интересно`. Синонимы и регистр игнорирует. Пустое или невалидное
   → `можно`.
3. Дополнительно: если пользователь написал произвольный комментарий
   рядом (например, `**тег:** обязательно — ради этого вся поездка`),
   Stage 4 сохраняет это как note (см. §6.7 в must_have_resolved).

Это и есть «простой скилл по дешифровке комментариев пользователя»,
который пользователь упомянул как опцию — но реализован в Stage 4 шаге
загрузки, а не как отдельный декодер.

### 5.5 UX в чате (end-of-Stage-3 touchpoint)

После Stage 3 артефакта скилл выводит **одно сообщение**:

> Stage 3 готов. POI pool сохранён в `3_poi_pool.md`. В файле под каждым
> региональным заголовком — пустое поле `**тег:**`. Заполни прямо в
> markdown:
> - `обязательно` — регион обязателен в плане
> - `можно` — на усмотрение скилла (можно опустить, это и есть default)
> - `не интересно` — не включать
>
> Пустые поля трактую как `можно`. Когда готов — скажи «строй варианты»,
> Stage 4 прочитает теги из файла и предложит 3 варианта маршрута.

Пользователь редактирует Stage 3 md руками, потом просит запустить Stage 4.

---

## 6. Stage 4 v2 — спецификация

### 6.1 Цель

На входе POI pool + user_region_tags → построить 3 variant'а **shape**:
которые регионы, сколько ночей, в каком порядке, какие POI **выпали**.

### 6.2 Что Stage 4 v2 НЕ делает

- НЕ распределяет POI по дням (это Stage 5).
- НЕ оценивает точный бюджет (только relative rank).
- НЕ выбирает конкретный транспорт (только тип: рейс / поезд / автобус).
- НЕ предлагает отели.

### 6.3 Что Stage 4 v2 делает

1. **Region selection.** Выбирает подмножество регионов из longlist
   согласно тегам. **Размер подмножества зависит от формата поездки**
   (см. §4.1.2.bis):
   - **Multi-region tour:** обычно 4-6 регионов из longlist 6-8
     (точное число — функция `duration_nights / 3` ± с учётом tempo
     и density override'ов).
   - **Single-base trip:** 1 регион + 2-4 day-trip направления —
     все variants внутри одной базы, различаются POI/темпом, не выбором
     регионов.
   - **Explicit list:** все `pre_committed_places` + опционально 1-2
     дополнительных.

   Логика тегов одинакова для всех форматов:
   - Все `обязательно` включаются (или escalate если конфликт).
   - `не интересно` исключаются.
   - `можно` распределяются по variants для дифференциации.
2. **Nights distribution.** Распределяет ночи по выбранным регионам с
   учётом density tags + tempo (из Stage 0 v2 YAML).
3. **Region order.** Определяет порядок прохождения с учётом open-jaw
   возможностей и Stage 1 META flight facts (F-33).
4. **Inter-region transport type.** Рейс / поезд / автобус — тип, не
   конкретный перевозчик.
5. **Relative cost rank.** `$` / `$$` / `$$$` — без точных сумм.
6. **Sacrifices list.** Какие POI из Stage 3 pool НЕ входят в этот variant
   (потому что регион выпал) — явный список.
7. **Flavor sample.** Первый и последний день каждого variant'а — 2
   строки на день (POI + темп).
8. **Honest assessment.** В терминах user tags + tradeoffs.

### 6.4 Migrated TODOs из старого Stage 0

| # | Что | Куда в Stage 4 v2 |
|---|---|---|
| F-13 | Logistics tradeoff явный в pakets | §6 «Region order + transport» — для каждого variant'а явно показать выбор при наличии 2+ маршрутов |
| F-15 | nights/base в honest assessment | §6 — обязательное «темп: N.NN ночи/база» для каждого variant'а |
| F-17 | Формат логистики pakages | §6 — 1 строка на сегмент, явный выбор типа транспорта |
| F-19 | Title пакета без метафор | §6 — title как прямое перечисление осей |
| F-20 | content_density override two-way | §6 — override применяется при распределении ночей (overshoot и undershoot) |

### 6.5 F-33 — open-jaw routing optimization

Pre-emit Class D (правило):
- Если поездка multi-country и предполагает открытую дугу (вход в один
  город, выход из другого) — **обязательно проверить оба направления**.
- Использовать факты из Stage 1 META-DIAGNOSTICS (наличие прямых рейсов
  между крайними точками).
- Финальный выбор направления — основан на total cost (international +
  внутренних рейсов).

### 6.6 F-35 — CONTESTED не эскалирует до ночёвки при HIGH-контр-сигнале

- Если POI / cluster имеет CONTESTED status и **HIGH контр-сигнал** (≥2
  негативных отзывов высокой trust) — Stage 4 НЕ делает ночёвку в этом
  регионе. Только day-trip или skip.
- Для cluster: status наследуется от **dominant member** (POI с
  максимальным signal weight).

### 6.7 YAML schema (Stage 4 v2)

```yaml
---
trip_id: {trip_id}
stage: 4_variants
schema_version: 2
iteration: 1
created: YYYY-MM-DD
based_on:
  stage0_scope: 0_scope.md
  stage3_pool: 3_poi_pool.md
  user_region_tags: user_region_tags.yaml
  iteration_feedback: null              # | iteration_feedback.md (если есть)

# Tags resolution
must_have_resolved: ["Ангкор", "Страна Г"]
must_have_conflict: false              # true если конфликт → escalate сообщение
skip_resolved: ["Vientiane"]
can_pool: ["Konglor", "Plain of Jars", "Pakse", "Bangkok"]

variants:
  - name: A
    title: "Страна Г + север Страна Г"     # F-19: прямое перечисление, без метафор
    chosen_regions:
      - region: "Ангкор и Страна Г"
        nights: 4
      - region: "Страна Г"
        nights: 4
      - region: "Северный Страна Г — Нонг Кхьяу"
        nights: 3
    nights_total: 11
    nights_per_base: 3.67                # F-15
    region_order: ["SR", "LP", "NK"]
    open_jaw: true
    open_jaw_direction: "вход SR → выход NK"
    transport_segments:                  # F-13/F-17
      - from: "Москва"
        to: "SR"
        type: рейс
        rationale: "прямой через стыковку"
      - from: "SR"
        to: "LP"
        type: рейс
        rationale: "QV513 прямой"
      - from: "LP"
        to: "NK"
        type: автобус
        rationale: "4 часа, дешевле"
      - from: "NK"
        to: "Москва"
        type: рейс
        rationale: "через VTE"
    cost_rank: $$
    sacrifices:                          # POI выпавшие из-за исключённых регионов
      - poi: "Конглор пещера"
        reason: "регион 'Тхакхэк' не вошёл"
      - ...
    flavor_first_day: "Прилёт SR, ужин в Pub Street; medium tempo"
    flavor_last_day: "Утренний поход в Nong Khiaw viewpoint, дневной рейс в Москву"
    red_flags:                          # cluster/region level
      - "Ангкор-Ват — большой круг рекомендуется как cluster (см. Stage 3)"
    honest_summary: "..."

  - name: B
    ...
  - name: C
    ...

# Honest assessment
comparison_table:                       # три варианта по 4-5 осям
  - axis: "темп"
    A: "балансный"
    B: "slow"
    C: "active"
  - axis: "охват"
    A: "Страна Г+север Страна Г"
    B: "Страна Г+юг+север Страна Г"
    C: "максимум регионов"
  - ...

contested_decisions:                    # F-35
  - poi_or_cluster: "Muang Ngoi"
    contested_reason: "HIGH-сигнал критики: 'потерял аутентичность'"
    decision: "только day-trip из LP, не ночёвка"
---
```

### 6.8 Markdown тело Stage 4 v2

```markdown
# Stage 4 v2 — Варианты маршрута: {trip_id}, итерация {N}

## Контекст
{Tags resolution: must-have, skip, can pool}

## Variant A — {title}
{6-10 строк описания}

**Регионы:** SR (4) → LP (4) → NK (3)
**Темп:** 3.67 ночи/база (балансный)
**Cost rank:** $$
**Open-jaw:** вход SR → выход NK
**Transport:** {таблица сегментов}

**Sacrifices** ({K} POI выпало):
- Конглор пещера — регион 'Тхакхэк' не вошёл
- ...

**Flavor:**
- День 1 (SR): {2 строки}
- День 11 (NK): {2 строки}

**Honest:** {1-2 предложения о tradeoffs этого variant'а}

---

## Variant B — ...
## Variant C — ...

## Сравнение

{Comparison table}

## CONTESTED решения
{Список с rationale}

## Что НЕ вошло ни в один variant
{POI, которые исключены во всех 3 вариантах из-за `не интересно` тегов}

## Следующий шаг
Выбери variant в чате — скилл запустит Stage 5 для детального плана.

Можешь также:
- изменить теги (user_region_tags.yaml) и запросить новую итерацию — Stage 4 v{N+1}
- запросить корректировку конкретного variant'а (добавить/убрать регион)
```

---

## 7. Stage 5 v2 — спецификация

### 7.1 Что Stage 5 v2 owns (новые ответственности)

- Day-by-day POI selection из Stage 3 pool.
- Конкретный транспорт (время, перевозчик, цена-ориентир).
- Отели (общая зона + ориентир по цене, helpfully TODO для проверки).
- Конкретный бюджет per day.
- F-38 enforcement: каждый день ≥1 POI на morning AND ≥1 POI на afternoon.
- F-39 enforcement: явное обозначение stop-over рейсов.

### 7.2 F-38 — Pre-emit Class G

Новый класс Pre-emit checklist'а специально для Stage 5:

```
Class G (day-fill discipline):
для каждого дня в плане проверить:
- [ ] есть ≥1 POI на morning slot (до обеда)
- [ ] есть ≥1 POI на afternoon slot (после обеда)
- [ ] если slot пустой («свободное время» / «полудня свободно») —
      должна быть **явная причина** в описании дня (например, «день отдыха
      между активным треккингом», «компенсация джет-лага», «обязательный
      буфер при переезде»)
- [ ] никаких «полудня свободно» без явной причины
```

Если хоть один пункт fail → Stage 5 переделывает день.

### 7.3 F-39 — stop-over ясность

В описании рейсов:
- **Прямой рейс:** `Рейс QV514 LPQ → MOW, 12:50 → 18:30 прямой`
- **Stop-over без ночёвки:** `Рейс QV514 LPQ → MOW через VTE (стыковка 50 мин,
  без выхода из аэропорта)`
- **Stop-over с ночёвкой:** `Рейс QV514 LPQ → VTE (1 ночь VTE) → QV515 VTE → MOW`

Никаких «через X» без явного указания, что это означает.

### 7.4 Migration: Stage 4 → Stage 5 boundary

| Было в Stage 4 | Стало в Stage 5 |
|---|---|
| День-за-днём POI selection | Stage 5 v2 |
| Точный бюджет | Stage 5 v2 |
| Отели | Stage 5 v2 |
| Конкретный транспорт | Stage 5 v2 |

| Было в Stage 5 | Осталось в Stage 5 |
|---|---|
| Финальная сборка | Да |
| Hotel TODO marking | Да |
| Day-by-day uточнение | Да (теперь основная работа) |

### 7.5 YAML schema (Stage 5 v2)

Существующая schema (`stage: 5_final_plan`) расширяется:
- `iteration: N` (для версионирования)
- `based_on.stage4_variant: A | B | C` (какой variant был выбран)
- Day-by-day остаётся как сейчас.

---

## 8. Iteration loop (F-41 MVP) — спецификация

### 8.1 Stable / mutable boundary

| Тип | Файлы |
|---|---|
| **Stable** (не правится между итерациями) | `0_scope.md`, `1_dr_reports.md`, `2_similarity.md`, `3_poi_pool.md` |
| **Mutable** (правится пользователем между итерациями) | `user_region_tags.yaml`, `iteration_feedback.md` (optional) |
| **Versioned** (новый файл за итерацию) | `4_variants_v{N}.md`, `5_final_plan_v{N}.md` |

### 8.2 Versioning

- Первая итерация: `4_variants_v1.md`, `5_final_plan_v1.md`.
- Каждая новая итерация инкрементирует `{N}`.
- В YAML каждого артефакта: `iteration: N`.
- Latest актуальные — `v{max(N)}`.
- При `N >= 4` — старые архивируются в `{trip_id}/_archive/` (F-41.I, Polish).
- Не лимитируем число итераций.

### 8.3 Re-entry detection

При запуске скилла для `trip_id`:

1. Glob: `{travel_root}/trips/{trip_id}/`
2. Анализ:
   - Если `5_final_plan_v{N}.md` существует и пользователь не указал явно
     «новая итерация» — спросить:
     > Нашёл существующие артефакты:
     > - Stage 0–3 завершены ✓
     > - Stage 4 итерации: v1, v2
     > - Stage 5: v2 финален
     >
     > Что делать?
     > 1. Новая итерация Stage 4 (вернуться к POI pool, перетегировать регионы) ← рекомендую при «план не подошёл»
     > 2. Продолжить с v2 (Stage 5 другая корректировка)
     > 3. Пересобрать Stage 3 (потерять POI комментарии)
     > 4. Вернуться раньше Stage 3 (требует переделки DR, дорого)
     > 5. Сбросить все теги и начать tagging заново (новая итерация с чистыми тегами)

3. Default = 1 (новая итерация Stage 4).

### 8.4 Default behavior — empty tags

Если пользователь не правил `user_region_tags.yaml` (все теги остались
`можно`) — Stage 4 v2 трактует это как «делай по логистике + density».
Это **valid path**, не undefined behavior.

В honest assessment Stage 4 v2 явно: «теги не заданы — варианты построены
из всех `можно` регионов, дифференциация по логистическому groupings».

### 8.5 Clear tags option (F-41 re-entry UX)

При re-entry — option 5 «сбросить все теги»:
- `user_region_tags.yaml` перезаписывается со всеми `можно`.
- Пользователь тегирует заново.
- Это эквивалентно «забыл что было раньше, начну с чистого листа».

### 8.6 Iteration feedback — без отдельного файла (И-6)

Никакого `iteration_feedback.md` не существует — это против И-6
(пользователь не должен заполнять отдельные шаблоны).

Вместо этого re-run работает так:
1. Пользователь правит `**тег:** ...` в Stage 3 md (если хочет иначе
   распределить регионы).
2. В чате говорит: «новая итерация Stage 4. Что не подошло в v{N}:
   {фритекст про проблемы — слишком плотно / мало природы / убери X /
   добавь Y}».
3. Stage 4 v{N+1} получает на вход:
   - Stage 3 md (с обновлёнными тегами) — stable артефакт.
   - Старый `4_variants_v{N}.md` — чтобы видеть, что менялось.
   - Фритекст из чата — как constraint для нового набора variants.
4. Stage 4 строит v{N+1} с учётом feedback'а; в honest assessment
   явная строка «по сравнению с v{N}: …».

Пользователь работает только с тем, что он уже привык читать (Stage 3 md
+ старый Stage 4 артефакт + чат). Никаких новых шаблонов.

---

## 9. Migration plan

### 9.1 Существующие trip-кейсы (Vietnam, Argentina, Страна Г)

Vietnam, Argentina и Страна Г имеют v1 артефакты Stage 0. Для re-run на v2:

**Option A (recommended):** Игнорировать существующие `0_scope.md`,
запустить Stage 0 v2 с нуля → новый `0_scope.md` с `schema_version: 2`.
Старый перемещается в `_archive/0_scope_v1.md`.

**Option B:** Скрипт миграции `migrate_v1_to_v2.py`:
- Парсит старый `0_scope.md`.
- Извлекает регионы из `## Решение`.
- Превращает в longlist (но без reserve pairs и non-canonical, поскольку
  v1 их не содержал).
- Помечает `migration: from_v1` в YAML.

**Решение:** Option A для калибровки (нужен чистый blind test). Option B
— только если пользователь хочет re-run с экономией времени.

### 9.2 In-flight trips (нет таких сейчас)

N/A для текущего состояния. Если в будущем — миграция аналогично 9.1.

### 9.3 Schema versioning

Каждый артефакт имеет `schema_version: N` в YAML. Скилл проверяет при
чтении. Несовпадение → graceful error с предложением миграции.

---

## 10. Open questions (deferred к имплементации / калибровке)

### Q1: Akt A — должен ли скилл сразу подгружать profile?

Профиль нужен для tempo math и non-canonical pass. Сейчас в Stage 0 v1
профиль читается перед промтом. В v2 — аналогично, без изменений.

**Решение:** да, профиль читается перед Akt A.

### Q2: Что если Akt A user отвечает не на все 3 вопроса?

Например, ответ только на mood, без country quota.

**Решение:** Akt A повторяет один **дополнительный** вопрос (graceful).
Если пользователь явно говорит «выбери сам» — defaults применяются.

### Q3: Цикл «теги → Stage 4 → не понравилось → теги» — где предел?

**Что это за цикл (пояснение):**

1. **Теги:** пользователь, видя POI evidence в Stage 3 md, отмечает
   региональные теги (`обязательно` / `можно` / `не интересно`)
   прямо в md под каждым региональным заголовком.
2. **Stage 4:** скилл строит 3 variant'а маршрута (shape only — выбор
   регионов, ночи, порядок, sacrifices list, flavor sample).
3. **Не понравилось:** пользователь читает 3 variant'а и понимает —
   нет, плотно/мало природы/мало гор/etc. Хочет другой набор вариантов
   без перезапуска DR.
4. **Обновляет теги:** идёт в Stage 3 md, меняет теги (например,
   `Vientiane: можно` → `не интересно`; `Konglor: можно` → `обязательно`).
5. **Запускает Stage 4 v{N+1}:** скилл читает обновлённые теги,
   опционально комментарий пользователя «что не подошло в v1», строит
   новый набор variants.

Цикл может повторяться — это **дёшево** (Stage 4 не запускает DR, не
пересобирает POI pool), поэтому ограничивать его не имеет смысла.

**Решение:** не лимитируем. Auto-archive `v1, v2, ...` в `_archive/`
при `N ≥ 4` (только чтобы не загромождать trip dir), но сами итерации
unlimited.

### Q4: Stage 4 v2 без day-by-day — пользователь может почувствовать «недостаточно конкретно».

Risk: user захочет видеть day-by-day до выбора variant'а.

**Mitigation:** Flavor sample (первый + последний день) даёт ощущение.
Если калибровка покажет, что недостаточно — добавить «day 1 + day midpoint
+ day last» (3 sample days).

**Решение:** начать с 2 days flavor. Если на Phase 3 калибровке user
скажет «мало» — расширить.

### Q5: F-36 (cluster units) — что считается cluster?

Это deferred к Phase 2 (Stage 3 prep). Возможный критерий:
- Geographic proximity (POIs в радиусе < X km).
- Logistic grouping (доступны из одной базы).
- Thematic unity (один archeological cycle, например).

**Решение:** F-36 spec'нуть в Phase 2, до Stage 4 v2 имплементации.

### Q6: iteration feedback — отдельный файл vs чат?

**Решение:** **никаких отдельных файлов** (И-6). Re-run Stage 4 принимает:
- старый артефакт (`4_variants_v{N-1}.md`) — прикладывается к чату либо
  читается из travel_root;
- свободные комментарии в чате — «что не подошло в прошлой итерации».

Это проще и не требует от пользователя заполнения дополнительных
шаблонов. Stage 4 строит новый набор variants и в honest assessment
явно пишет, что изменилось по сравнению с предыдущей итерацией.

---

## 11. Implementation phasing (overlapping Phase 3 из общего плана)

### Phase 3 — MVP implementation order

Внутри Phase 3 (после Phase 1 + Phase 2):

1. **storage-and-naming.md** — обновить §2-3 (новые файлы, schema_version).
2. **methodology.md** — добавить секции «evidence перед route», «3-tag система»,
   «iteration loop». Не переписывать всё; добавить новые секции.
3. **stage0-scope.md v2** — переписать целиком под Stage 0 v2 spec.
4. **SKILL.md** — обновить pipeline section + re-entry detection logic.
5. **stage1-dr-prompt.md** — обновить input (longlist 6-8 вместо 5 финальных).
6. **stage3-poi.md** — добавить end-of-Stage-3 touchpoint + tagging output.
7. **stage4-variants.md** — переписать под Stage 4 v2 (shape only, sacrifices, flavor).
8. **stage5-final.md** — обновить под Stage 5 v2 (owns day-by-day, F-38 Pre-emit G, F-39 stop-over).
9. **Schemas:** user_region_tags.yaml, обновлённый 0_scope.md, обновлённый 4_variants.md.
10. **Tests** — обновить там где есть unit tests; добавить новые для cluster + tagging.
11. **Regression: re-run Страна Г через v2** + новый blind на Страна А.

### Phase 4 — Polish

После Phase 3 калибровки — реализуются:
- F-40.B/C/D/E (если калибровка показала нужду)
- F-41.D/F/G (iteration feedback channel)
- methodology.md крупная переписка
- changelog.md v0.23

---

## 12. Acceptance criteria для Phase 3 calibration

Пошаговый план прогона. Запускается **после** того как Phase 3
имплементация завершена (все правки §11 сделаны, юнит-тесты зелёные).

### 12.1 Шаги Страна Г re-run

**Шаг 0 (подготовка).** Существующие Страна Г-артефакты сохранить в
`_archive/v0.22/`. Stage 0–5 запускаются заново.

**Шаг 1 — Stage 0 v2 на Страна Г-направлении** (Страна Г + Страна Г + транзит
BKK, февраль).
- Verify: Akt A показывает 2-3 предложения per region, fact-based.
- Verify: detected `trip_format: multi-region tour`.
- Verify: longlist 6-8 регионов с reserve pairs.
- Verify: non-canonical pass нашёл регионы вне mainstream guidebook.

**Шаг 2 — Stage 1 DR по longlist** (6-8 регионов вместо 5).
- **Метрика A:** DR wall-clock измерить.
- Verify: 20 полей канонические (никаких trip-specific переименований).
- Verify: META-DIAGNOSTICS — POI-критика per region отдельно от
  сезонной (есть число critical-отчётов на каждый регион).

**Шаг 3 — Stage 2 similarity + Stage 3 POI aggregation.**
- Verify: parse_dr_cards.py diagnostic-only (нет authors[] в output).
- Verify: Stage 3 md имеет `**тег:**` поле под каждым региональным
  заголовком.
- Verify: cluster units сработали — храмовый комплекс (Ангкор) собран
  как cluster unit, не разрозненные POI.
- Verify: per-region режим — регион с 1 HIGH-автором в scarce режиме.
- **Метрика B:** Tonle Sap есть в POI pool (в v0.22 был исключён).

**Шаг 4 — Tagging.** Пользователь дописывает теги в Stage 3 md.

**Шаг 5 — Stage 4 v2 — первая итерация (v1).**
- Verify: shape only (нет day-by-day POI selection).
- Verify: sacrifices list присутствует.
- Verify: relative cost rank `$/$$/$$$` (не точные суммы).
- Verify: flavor sample — первый и последний день каждого variant'а.

**Шаг 6 — Stage 5 v2.**
- **Метрика C:** в variant'е с LP ≤ 5 ночей (не 6 как в v0.22).
- Verify: Pre-emit Class G — нет полудней без POI без явной причины.
- Verify: stop-over рейсы описаны явно (3 формата).

**Шаг 7 — Iteration test.** Пользователь меняет 1-2 тега и запускает
Stage 4 v2 заново.
- Verify: DR не пересобирается (stable артефакт).
- Verify: v2 variants отличаются от v1 в нужную сторону.
- Verify: honest assessment явно сравнивает v2 vs v1.

**Шаг 8 — Composite score.** Сопоставление с postmortem Страна Г:
- **Метрика D:** composite ≥ 5.5 (baseline v0.22: 5.0).
- Reproduction / failure_detection / added_value / blind_spots —
  отдельные subscores.

### 12.2 Шаги Страна А blind run

Пользователь заполняет `south_korea_2024_postmortem_template.md`
**до** прогона.

**Шаг 0 (подготовка).** Postmortem template заполнен на 80%+
ключевых тезисов (не открывая выходы скилла).

**Шаг 1 — Stage 0 v2.** Запрос: «Южная Страна А, 18 ночей, конец марта —
начало апреля {год}».
- Verify: detected `trip_format: multi-region tour`.
- Verify: формула N даёт longlist 5-6 (Korea имеет ~5-6 значимых
  регионов → floor сработал).
- Verify: Akt A упоминает **сакура window** как сезонный фактор.
- Verify: non-canonical regions (если такие есть) — например, Андон,
  Чонджу, Тхэбэк.

**Шаг 2 — Stage 1 DR.**
- **Метрика E:** DR wall-clock на 5-6 регионах vs baseline Страна Г
  (6-8). Должен быть пропорциональным.

**Шаг 3 — Stage 2/3.** Verify cluster units на культовых сакура-spots
в Кёнджу (если применимо).

**Шаг 4 — Tagging.** Пользователь маркирует Сеул как must-have (или
не маркирует — оба валидно).

**Шаг 5 — Stage 4 v2 + Stage 5 v2.**

**Шаг 6 — Iteration test (consistency check).** Re-run Stage 4 на тех же
тегах.
- Verify: v2 структурно похож на v1 (не радикально другой при тех же
  inputs).

**Шаг 7 — Сравнение с postmortem.** Открывается заполненный postmortem,
сравнивается с выходами скилла по 14 ключевым тезисам.
- **Метрика F:** ≥ 8 из 14 тезисов подтверждены/опровергнуты в нужную
  сторону.

### 12.3 Default behavior (отдельные мини-прогоны после 12.1/12.2)

- **Empty tags:** запустить Stage 4 v2 без заполнения тегов в Stage 3 md
  (все поля пустые). Verify: Stage 4 трактует как all-`можно`, строит
  varianты по логистике.
- **Tag synonyms:** проверить парсинг `must` / `да` / `ok` / `skip`
  как валидных синонимов. Verify: нормализуются в три канонических
  значения.
- **Single-base trip:** мини-прогон на запросе типа «2 недели в одном
  городе с day-trips». Verify: detected `trip_format: single_base`,
  один регион в longlist + 2-4 day-trip направления.

### 12.4 Сводные метрики Phase 3

После всех шагов — таблица:

| Метрика | Страна Г baseline (v0.22) | Целевое значение | Фактически |
|---|---|---|---|
| A. DR wall-clock на longlist | ~X мин (5 регионов) | ≤ 2× при 6-8 | _ |
| B. Tonle Sap в POI pool | нет | да | _ |
| C. LP nights в выбранном variant'е | 6 | ≤ 5 | _ |
| D. Composite Страна Г | 5.0 | ≥ 5.5 | _ |
| E. DR wall-clock Страна А | n/a | пропорциональный | _ |
| F. Тезисы Страна А подтверждены | n/a | ≥ 8/14 | _ |

Если хотя бы 4 из 6 метрик в зелёной зоне → Phase 3 принят, переходим к
Phase 4 (Polish). Если ниже → возврат на iteration внутри Phase 3.

---

## 13. Glossary

| Термин | Определение |
|---|---|
| Akt A | Первая часть Stage 0 v2 — диалог + 3 вопроса |
| Akt B | Вторая часть Stage 0 v2 — формализация longlist |
| Longlist | 6-8 регионов из Stage 0 v2 для DR |
| Region universe | 12-15 регионов на верхнем уровне, до фильтрации |
| Reserve pair | Регион-substitute для другого (если основной отпал) |
| 3-tag system | Tagging регионов: обязательно / можно / не интересно |
| Sacrifices list | POI выпавшие из variant'а из-за исключённых регионов |
| Flavor sample | Первый + последний день variant'а как «вкус» |
| Cluster unit | Группа POI как 1 selectable (F-36) |
| Iteration | Цикл Stage 4 + Stage 5 c одним набором тегов |
| Re-entry | Возврат в post-Stage 3 для новой итерации без пересборки DR |

---

**Конец F-40 дизайн-документа.**

Готов к review. Acceptance — после approval начинается Phase 3 implementation.
