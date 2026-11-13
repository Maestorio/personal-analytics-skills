# Audit Frontmatter Schema

Схема YAML frontmatter для профилей аудитов источников в `Claude-Memory/domains/{domain}/`.

> **Архитектурное примечание (D8, 2026-05-10):** trust остаётся плоским 1D dict `{subdomain: LEVEL}`. Решение D4 о расширении trust до 3D (`marginal/world_picking/conditional`) и блок `implicit_geopolitical_scenarios` **отозваны**. Сценарная атрибуция источников делается динамически в момент FCA по контенту прогноза (`forecast-confidence-applier/SKILL.md` Шаг 1.5B), не хранится в profile.

---

## Обязательные поля

```yaml
source: "{source-slug}"           # kebab-case slug источника
audit_date: YYYY-MM-DD            # дата написания аудита
trust:                            # плоский dict; хотя бы одно ненулевое HIGH/MEDIUM/LOW
  geopolitics: HIGH
  ru-macro: MEDIUM
```

## Рекомендуемые поля

```yaml
period: "{YYYY-YYYY}"             # охватываемый период (напр., "2020-2026")
last_updated: YYYY-MM-DD          # = audit_date при создании; обновляется при ревизии
pin: false                        # true → принудительно включить в memory-sync
methodology_notes: |              # свободное описание методологии источника
  RU sell-side, регулярные базовые сценарии, склонны к консерватизму.
  Не специализируются на геополитике — взгляд на санкции вторичен.
```

## Опциональные поля

```yaml
audit_type: source_profile        # source_profile | analyst | channel | think_tank
theses_count: <N>                 # число проверенных тезисов
hit_rate: 0.00                    # доля верных (0.0–1.0)
alpha_generation: 0.00            # доля contrarian-правильных (0.0–1.0)
avg_value: <N>                    # средняя ценность тезиса (шкала −2 ... +3)
skill_version: "<semver>"         # версия скилла при создании
```

---

## Trust (1D, плоский)

```yaml
trust:
  {subdomain}: HIGH | MEDIUM | LOW | IGNORE
```

Одно измерение точности — насколько источник попадает в реальность по точечному прогнозу (`central_estimate` vs realized). Используется и в FCA Layer 1 (точечная оценка), и в FCA Layer 2 (per-scenario): один источник, одна оценка trust per subdomain.

### Допустимые значения

- `HIGH` — статистически значимая точность (≥70% попаданий, ≥6 наблюдений) или субъективно высокая для редко резолвед-прогнозов
- `MEDIUM` — средне (50–70%)
- `LOW` — низкая, но не повод исключать
- `IGNORE` — систематически ошибается / пропагандистский / нерелевантен субдомену

### Сценарная атрибуция (D8)

При построении Type 2 conditional FCA скилл `forecast-confidence-applier` (Шаг 1.5B) **динамически классифицирует** источники по scenario camps на основе контента конкретного прогноза. Эта атрибуция:
- **Не хранится** в profile источника — была бы stale при смене сценарной оси.
- **Записывается inline в forecast YAML**: `by_scenario.{X}.sources_used = [{source_id, camp_weight, reasoning}]`, `provenance: inferred_from_content`.

Поле `methodology_notes:` (опциональное) помогает LLM в Шаге 1.5B быстрее ориентироваться, но **не диктует** атрибуцию — это методологическая характеристика, не привязанная к сценариям.

### Backward compat (legacy 3D)

Если в старом профиле встречается `trust: {marginal: {...}, world_picking: {...}, conditional: {...}}` (формат отозванного D4) — загрузчики (`flatten_trust` в `assemble_artifact.py`, `_flatten_trust` в `sync_planner.py`) трактуют его как `trust.marginal` (берут `marginal` подсловарь как плоский trust). Этот код помечен как deprecated noop. Новые профили должны использовать плоский 1D.

---

## Логика включения в memory-sync

```
include_in_memory = pin == true  OR  (любой subdomain в trust == HIGH)
```

Если оба условия ложны — файл не попадёт в `memory_user_edits`.
Предупреждение от `save-to-library`: «Без HIGH trust или pin:true файл не попадёт в память.»

---

## Имя файла

`{source-slug}-{period}.md`

Примеры:
- `isw-2022-2025.md`
- `stratfor-2015-2025.md`
- `goldman-sachs-2020-2026.md`

Префикс `lib_` **не используется** — устаревшая конвенция.

---

## Субдомены (допустимые ключи trust)

`geopolitics` · `ru-macro` · `ru-sellside` · `global-banks` · `tech-ceo` · `commodity-agencies`

Если у источника нет покрытия субдомена — поле просто отсутствует (не пишется как `null`).
