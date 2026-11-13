# Runbook: пошаговое выполнение апгрейда

**Версия:** 2026-05-08
**Связанные документы:** `HANDOFF-claude-code-phased.md`, `HANDOFF-cowork-data-phased.md`
**Цель:** последовательное выполнение апгрейда с проверкой каждого шага

---

## Pre-flight: что должно быть готово до старта

- [x] D1–D7 решения зафиксированы (см. handoff-документы, §1)
- [x] Оба HANDOFF-файла лежат в `/Users/you/Documents/Claude/Projects/Ретроспективный анализ/`
- [x] `~/Documents/Программы/claude_skills` — рабочий репо под git
- [x] Synology Drive синхронизирован (Claude-Memory доступна)
- [ ] Создана feature-branch в репо: `git checkout -b conditional-architecture-upgrade`

---

## Общие правила

**Перед каждым шагом:** прочитай раздел соответствующей фазы в HANDOFF-документе.

**После каждого шага:** проверь критерий готовности. Если не сошлось — **не переходи к следующему**, разбирайся.

**Если что-то сломалось:** rollback по инструкции в шаге.

**Чередование сред:** Cowork и Claude Code — это разные чаты. В каждом новом чате прикладываешь оба HANDOFF-файла + этот runbook.

**Backup-стратегия:**
- Claude-Memory (Synology, без git): `.pre-{step}` суффикс на изменяемых файлах
- Repo (под git): feature-branch + commit на каждый шаг

---

## Выбор модели Claude per шаг

Используй модель в зависимости от характера задачи. В Claude Code — переключай через `/model` команду или настройки. В Cowork — модель задаётся выбором при старте чата.

| Шаг | Модель | Почему |
|-----|--------|--------|
| 1. Coherence audit (CW) | **Sonnet 4.6** | Диагностика, нужны выводы по 22 файлам, не чисто механическая |
| 2. Унификация весов (CW) | **Sonnet 4.6** | 5 файлов, риск ошибки sum != 1.0 → нужна safety; Haiku может промахнуться |
| 3. Спецификации (CC) | **Opus 4.6** | Глубокое архитектурное письмо, схемы, инварианты — окупает дороговизну |
| 4. weighted_consensus.py (CC) | **Sonnet 4.6** | Код с математикой + тесты, стандарт для разработки |
| 5. SKILL.md правки (CC) | **Sonnet 4.6** | Большие doc updates с примерами YAML |
| 6. Tagging lib_*.md (CW) | **Haiku 4.5** | Rule-based tagging по таблице из §4.2 cowork-handoff, дешёвый batch |
| 7. Migration script (CC) | **Sonnet 4.6** | Edge cases (mojibake, mixed formats), нужна точность |
| 8. RECALIBRATE (CC) | **Sonnet 4.6** | Код среднего уровня сложности, валидаторы |
| 9. Split macro-input (CW) | **Sonnet 4.6** | Трансформация данных + coherence diagnostic, нужна аккуратность |
| 10. Stress rerun (CW) | **Sonnet 4.6** | Запуск + интерпретация diff, понимание что mixed-worlds artifact |
| 11. Tests + CI + merge (CC) | **Sonnet 4.6** | Стандартная разработка |
| 12. Forecast migration (CW) | **Haiku 4.5** | Per-file rule-based, дёшево; если файл странный → Sonnet |

**Правила переключения:**

- Если **Haiku не справился** (выдал кривой результат, нарушил backup-правила) → перезапусти Шаг на **Sonnet 4.6**
- Если **Sonnet застрял** на архитектурной проблеме → подними в **Opus 4.6** для разбора, потом обратно на Sonnet для реализации
- **Opus 4.6 не нужен** для рутинной работы (Шаги 4-12) — это deliberately ограниченный список (только Шаг 3 + Phase 7 в будущем)

**Стоимостный recommendation:** Шаги 6 и 12 на Haiku — главная экономия. Остальное Sonnet.

---

## Типы прогнозов в архитектуре

Архитектура поддерживает **три типа прогнозов**, каждый со своей структурой YAML.

### Тип 1: Isolated marginal forecast (без сценарной геометрии)

Прогноз не привязан к scenario matrix. Используется когда:
- Бинарное событие на дату (например, «сделка US-Иран до 2026-08-31»)
- Тема за пределами текущих сценарных матриц (например, AI capex 2026)
- Прогноз другого домена, не входящий в портфельный stress

**Формат YAML:**
```yaml
forecast:
  central_estimate: "Y"
  confidence: 0.40
  domain: ru-macro

# НЕТ блока conditional_on_scenarios

isolated: true
isolated_reason: "Single binary event без сценарной декомпозиции"

# Стандартные поля для аудита:
monitoring: [...]
assumptions: [...]
falsifiers: [...]
```

**Примеры в текущей библиотеке:**
- `iran-us-may-deal-2026-04-30.yaml` (бинарное событие)
- `china-taiwan-forecast-2026-04-28.yaml` (другой домен)
- `russia-europe-war-2030.yaml` (long horizon, отдельный)

**Использование:**
- Marginal point estimate для своих целей
- НЕ участвует в portfolio-scenario-stress
- Аудитируется через `retrospective-forecast-audit` как marginal-only

### Тип 2: Scenario-conditional forecast (привязан к одной scenario matrix)

Прогноз привязан к **ОДНОЙ** scenario matrix через `source_matrix`. Используется когда:
- Фактор входит в макро-цепочку портфеля
- Имеет смысл декомпозиция по 4 сценариям

**Формат YAML:**
```yaml
forecast:
  central_estimate: "X"           # Layer 1 marginal
  confidence: 0.40

conditional_on_scenarios:
  source_matrix: "scenarios/scenario-geopolitics-ru-west-2026-05-04.yaml"
  by_scenario:
    A: { values: ..., provenance: ..., sources_used: ... }
    B: { values: ... }
    C: { values: ... }
    D: { values: ... }
  marginal:
    method: linear
    values: ...                   # Layer 2 marginal
    
coherence_diagnostic: ...
```

**Примеры в текущей библиотеке (после миграции):**
- `ru-rates-2026-2027-2026-05-04.yaml` ←→ `geopolitics-ru-west`
- `cny-rub-dec2026-dec2027-2026-05-04.yaml` ←→ `geopolitics-ru-west`
- `usd-rub-dec2026-dec2027-2026-05-03.yaml` ←→ `geopolitics-ru-west`
- `ru-cpi-2026-2027-2026-05-04.yaml` ←→ `geopolitics-ru-west`
- `urals-brent-discount-2026-05-04.yaml` ←→ `geopolitics-ru-west`

**Использование:**
- В portfolio-scenario-stress — берётся `by_scenario` напрямую
- В weekly-review — берётся `forecast.central_estimate` (Layer 1)

### Тип 3: Independent scenario→forecast chains (несколько матриц)

В системе **могут сосуществовать несколько scenario matrices**, каждая со своей цепочкой прогнозов. Это **разрешено и нормально**.

**Текущие активные scenario matrices:**

```
scenarios/
├── scenario-geopolitics-ru-west-2026-05-04.yaml      ← основная для портфеля
│   └── forecasts: ru-rates, ru-cpi, usd-rub, cny-rub, urals-discount
│
├── scenario-brent-dec-2026-2026-04-30.yaml           ← reference, не для portfolio stress
│   └── forecasts: brent-oil-dec-2026 (потенциально)
│
├── scenario-usd-rub-sept-2026-2026-04-30.yaml        ← reference, superseded
│   └── forecasts: usd-rub-sept-2026 (legacy)
│
└── scenario-ai-capex-scenarios-2026-2026-04-30.yaml  ← reference, другой домен
    └── forecasts: ai-capex-slowdown-2026, us-technical-recession
```

**Правила:**

1. **Каждый forecast ссылается максимум на ОДНУ scenario matrix** через `source_matrix`. 
   Если фактор семантически имеет несколько condition'ов (например, USD/RUB зависит и от 
   geopolitics, и от brent matrices) — выбирается **dominant** matrix; остальное идёт через 
   `upstream_snapshot` или dependency-map.

2. **Каждая scenario matrix получает поле `usage_status`:**
   ```yaml
   matrix:
     usage_status: 
       active_for_portfolio_stress: true | false
       active_for_marginal_decisions: true | false
   ```
   На текущий момент:
   - `geopolitics-ru-west` → portfolio_stress: true
   - `brent-dec`, `ai-capex` → portfolio_stress: false (reference / другой домен)
   - `usd-rub-sept` → superseded (deprecated)

3. **macro-forecast-chain собирает stress только из активных матриц** для портфеля. 
   Текущая конфигурация — только geopolitics-ru-west.

4. **Multi-conditional forecasts (пересечение двух матриц) НЕ поддерживаются в Phase 1-5.** 
   Если в будущем понадобится — это Phase 8+, требует отдельной архитектурной работы.

### Что это значит для миграции (Шаг 12, Phase 5)

При миграции каждого forecast YAML определяешь его тип:

```
1. Если forecast не имеет geopolitics_translation block → Type 1 (isolated)
   → добавить isolated: true, не создавать conditional_on_scenarios
   → migration trivial

2. Если forecast имеет geopolitics_translation с привязкой к geopolitics-ru-west → Type 2 (scenario-conditional)
   → migration через migrate_to_conditional.py
   → SOURCE_MATRIX = scenarios/scenario-geopolitics-ru-west-2026-05-04.yaml

3. Если forecast привязан к другой матрице (например, scenario-brent-dec) → Type 2, 
   но другая матрица
   → migration через migrate_to_conditional.py с указанием другой scenario YAML

4. Если forecast в спорной ситуации (несколько матриц логически релевантны) → 
   обсуди с пользователем перед миграцией.
```

### Текущий inventory с типами

| Файл | Тип | Scenario matrix |
|------|-----|-----------------|
| ai-capex-slowdown-2026-2026-04-30.yaml | 2 (или 1) | ai-capex (если используется) или isolated |
| brent-oil-dec-2026-2026-04-30.yaml | 2 (или 1) | brent-dec (если используется) или isolated в portfolio |
| byudzhetnyj-defitsit-rf-2026-05-03.yaml | 2 | geopolitics-ru-west |
| china-taiwan-forecast-2026-04-28.yaml | 1 (isolated) | — |
| cny-rub-dec2026-dec2027-2026-05-04.yaml | 2 | geopolitics-ru-west |
| iran-us-may-deal-2026-04-30.yaml | 1 (isolated) | — |
| iran-us-may-deal-2026-04-30-stress.yaml | 1 (isolated) | — |
| ru-cpi-2026-2027-2026-05-04.yaml | 2 | geopolitics-ru-west |
| ru-rates-2026-2026-04-28.yaml | 2 (legacy) | geopolitics-ru-west (старая версия) |
| ru-rates-2026-2027-2026-05-04.yaml | 2 | geopolitics-ru-west |
| russia-europe-war-2030.yaml | 1 (isolated, long horizon) | — |
| russia-europe-war-2030-2026-04-29.yaml | 1 (isolated) | — |
| sanctions-russia-2026-27-2026-05-02.yaml | 2 (axis_dependent) | geopolitics-ru-west |
| ukraine-postwar-forecast.yaml | 1 (isolated) | — |
| ukraine-russia-forecast-stress-test.yaml | 1 (isolated) | — |
| ukraine-russia-war-end-2026-05-02.yaml | 1 (isolated) | — |
| ukraine-russia-war-forecast-2026-04-28.yaml | 1 (isolated) | — |
| urals-brent-discount-2026-05-04.yaml | 2 (axis_dependent) | geopolitics-ru-west |
| us-technical-recession-2026-2026-04-30.yaml | 1 или 2 | ai-capex (если активна) или isolated |
| usd-rub-dec2026-dec2027-2026-05-03.yaml | 2 (нужно добавить geopolitics_translation) | geopolitics-ru-west |
| usd-rub-sept-2026-2026-04-30.yaml | 2 (superseded) | usd-rub-sept (deprecated) |
| xauusd-price-2026-2027-2026-05-04.yaml | 2 (indifferent method) | geopolitics-ru-west |

**Уточнение во время Phase 0 audit:** Cowork должен определить тип для каждого файла и записать в audit.

---

## Шаг 1 — CW Phase 0: Coherence audit

**Где:** Cowork (новый чат)
**Что:** диагностика текущего состояния, без изменений (read-only)
**Время:** 1.5 часа

### Запуск

1. Открой новый Cowork-чат
2. Прикрепи 3 файла: `HANDOFF-claude-code-phased.md`, `HANDOFF-cowork-data-phased.md`, `HANDOFF-runbook.md`
3. Промпт:
   ```
   Выполни Шаг 1 runbook'а: CW Phase 0 (Coherence audit). 
   Не делай никаких изменений в файлах — только диагностика.
   На выходе ожидаю файл _audits/coherence-audit-{date}.md в Claude-Memory.
   ```

### Что должно произойти

- Cowork смонтирует Claude-Memory
- Прочитает 22 forecast YAML, 4 scenario YAML, 9 lib_*.md
- Создаст `Claude-Memory/_audits/coherence-audit-{date}.md`
- Покажет тебе summary в чате

### Проверка

```bash
# Через Cowork bash или вручную в Finder:
ls -la ~/Library/CloudStorage/SynologyDrive-home/Ext_gDrive/Claude-Memory/_audits/coherence-audit-*.md
```

Файл существует и содержит:
- [ ] Inventory всех 22 forecast YAMLs с checklist
- [ ] Таблица текущих весов (Sc-D inconsistency 0.52 vs 0.525)
- [ ] Implicit-scenario гипотезы для 9 источников
- [ ] UTF-8 mojibake check список
- [ ] Recommendations для Phase 1

### Rollback

Не нужен — read-only шаг. Если файл audit'а сгенерировался кривой — просто перезапусти Шаг 1.

### → Переход к Шагу 2

Audit прочитан, гипотезы выглядят разумно.

---

## Шаг 2 — CW Phase 1: Унификация весов

**Где:** Cowork (можно тот же чат, что и Шаг 1)
**Что:** правка весов в 5 файлах на 0.25 каждому (D1) + удаление «Unaccounted» (D3)
**Время:** 30 минут

### Запуск

Промпт в том же или новом Cowork-чате:
```
Выполни Шаг 2 runbook'а: CW Phase 1 (унификация весов на 0.25). 
Перед каждой правкой — backup в .pre-d1-unification.
После каждой правки — sum check.
Файлы:
  • scenarios/scenario-geopolitics-ru-west-2026-05-04.yaml
  • forecasts/ru-rates-2026-2027-2026-05-04.yaml
  • forecasts/cny-rub-dec2026-dec2027-2026-05-04.yaml
  • macro-chain/macro-input-2026-05-04.yaml (+ удалить «Unaccounted»)
  • Ретроспективный анализ/stress-2026-05-05-iron-curtain-2.yaml (+ удалить expected_pl_*)
По окончании — запись в _sync_log.md.
```

### Что должно произойти

- Cowork сделает `.pre-d1-unification` копию каждого файла
- Заменит 4 веса на 0.25 везде
- Удалит «Unaccounted» из macro-input
- Удалит `expected_pl_pct` и `expected_pl_rub` из stress
- Запишет в `_sync_log.md`

### Проверка

В Cowork-чате попроси:
```
Покажи sum check всех 5 изменённых файлов через bash. 
Все суммы должны быть строго 1.0 (с точностью до 0.001).
```

Должно вывести:
```
✓ scenario-geopolitics-...yaml: sum = 1.000
✓ ru-rates-...yaml: sum = 1.000
✓ cny-rub-...yaml: sum = 1.000
✓ macro-input-...yaml: sum = 1.000  (без Unaccounted)
✓ stress-...yaml: sum = 1.000
```

Также проверь, что `.pre-d1-unification` файлы существуют:
```bash
ls -la ~/Library/CloudStorage/SynologyDrive-home/Ext_gDrive/Claude-Memory/**/*.pre-d1-unification
```

### Rollback (если что-то поломалось)

```bash
# Через Cowork bash:
cd /sessions/.../mnt/Claude-Memory
for f in $(find . -name "*.pre-d1-unification"); do
  original="${f%.pre-d1-unification}"
  cp "$f" "$original"
done
```

### → Переход к Шагу 3

Все 5 файлов с весами 0.25 каждому, sum=1.0, backup'ы на месте.

---

## Шаг 3 — CC Phase 1: Спецификации схем

**Где:** Claude Code (новый чат, в репозитории `~/Documents/Программы/claude_skills`)
**Что:** написать 4 файла спецификаций
**Время:** 2–3 часа

### Запуск

1. Открой Claude Code в `~/Documents/Программы/claude_skills`
2. Создай feature-branch (если ещё не создал):
   ```bash
   git checkout -b conditional-architecture-upgrade
   ```
3. Прикрепи 3 файла: `HANDOFF-claude-code-phased.md`, `HANDOFF-cowork-data-phased.md`, `HANDOFF-runbook.md` (все 3 — из Project folder Cowork)
4. Промпт:
   ```
   Выполни Шаг 3 runbook'а: CC Phase 1 (спецификации схем).
   Создай 4 файла спецификации согласно §2 HANDOFF-claude-code-phased.md.
   Без TODO в финальных версиях. После — git commit.
   ```

### Что должно произойти

- Создаются файлы:
  - `_shared-references/events-yaml-spec.md` (с разделами `conditional_on_scenarios` и `implicit_geopolitical_scenarios`)
  - `_shared-references/audit-frontmatter-schema.md` (3D trust)
  - `_shared-references/scenario-yaml-spec.md` (SSOT правила)
  - `scripts/migrate_to_conditional.spec.md` (psuedocode миграции)
- Коммит: `git add _shared-references/ scripts/migrate_to_conditional.spec.md && git commit -m "spec: conditional_on_scenarios + implicit_scenario схемы (Phase 1)"`

### Проверка

```bash
cd ~/Documents/Программы/claude_skills
ls -la _shared-references/events-yaml-spec.md \
       _shared-references/audit-frontmatter-schema.md \
       _shared-references/scenario-yaml-spec.md \
       scripts/migrate_to_conditional.spec.md

# Проверка отсутствия TODO:
grep -rn "TODO\|FIXME\|XXX" _shared-references/ scripts/migrate_to_conditional.spec.md
# должно быть пусто

git log --oneline -1
# должен быть коммит про spec
```

### Rollback

```bash
git reset --hard HEAD~1
# или если уже несколько коммитов:
git checkout -- _shared-references/ scripts/migrate_to_conditional.spec.md
```

### → Переход к Шагу 4

4 файла спецификаций существуют, без TODO, закоммичены.

---

## Шаг 4 — CC Phase 2.1: Код weighted_consensus.py

**Где:** Claude Code (тот же чат, что Шаг 3)
**Что:** реализовать 3 функции + написать unit tests
**Время:** 2 часа

### Запуск

Промпт в Claude Code:
```
Выполни Шаг 4 runbook'а: CC Phase 2.1 (weighted_consensus.py).
Реализуй функции согласно §3.1 HANDOFF-claude-code-phased.md:
  • joint_from_axes(ev_x, ev_y, rho)
  • aggregate_marginal(by_scenario, weights, horizon, method)
  • coherence_check(forecast_yaml)
  + helpers parse_central, load_weights_from_scenario
Напиши тесты в tests/test_weighted_consensus.py.
Запусти pytest, должно быть зелёным.
После — git commit.
```

### Что должно произойти

- Файл `skills/forecast-confidence-applier/scripts/weighted_consensus.py` обновлён
- Файл `tests/test_weighted_consensus.py` создан
- pytest зелёный
- Коммит: `git commit -m "feat: joint_from_axes + aggregate_marginal + coherence_check (Phase 2.1)"`

### Проверка

```bash
cd ~/Documents/Программы/claude_skills
pytest tests/test_weighted_consensus.py -v

# Все тесты должны пройти. Минимум должны быть:
# • test_joint_from_axes_independent
# • test_joint_from_axes_with_correlation
# • test_aggregate_marginal_linear_equal_weights
# • test_coherence_check_divergent
```

### Rollback

```bash
git reset --hard HEAD~1
```

### → Переход к Шагу 5

Тесты зелёные, функции работают.

---

## Шаг 5 — CC Phase 2.2-2.7: SKILL.md правки + correlation-rubric

**Где:** Claude Code (тот же чат)
**Что:** обновить 5 SKILL.md + создать `correlation-rubric.md`
**Время:** 2 часа

### Запуск

Промпт:
```
Выполни Шаг 5 runbook'а: CC Phase 2.2-2.7 (SKILL.md правки).
Обнови:
  • skills/forecast-confidence-applier/SKILL.md (implicit_scenario filter, two-marginal)
  • skills/scenario-builder/SKILL.md (default 0.25, opt-in joint_from_axes)
    + создай references/correlation-rubric.md
  • skills/macro-forecast-chain/SKILL.md (split output, RECALIBRATE, out-of-frame caveats)
    + обнови references/dependency-map.md
  • skills/portfolio-scenario-stress/SKILL.md (no expected_pl, robustness verdict)
  • skills/retrospective-forecast-audit/SKILL.md (Phase 6 stub)
По §3.3-3.8 HANDOFF-claude-code-phased.md.
После — git commit.
```

### Что должно произойти

- 5 SKILL.md обновлены с новыми разделами
- `correlation-rubric.md` создан
- `dependency-map.md` обновлён
- Коммит: `git commit -m "docs: SKILL.md обновления под conditional architecture (Phase 2.2-2.7)"`

### Проверка

```bash
cd ~/Documents/Программы/claude_skills

# Проверка наличия ключевых разделов:
grep -l "conditional_on_scenarios" skills/*/SKILL.md
grep -l "two-marginal" skills/forecast-confidence-applier/SKILL.md
grep -l "RECALIBRATE" skills/macro-forecast-chain/SKILL.md
grep -l "robustness" skills/portfolio-scenario-stress/SKILL.md

# Проверка YAML-примеров (валидный YAML):
python -c "
import yaml, re
for f in ['skills/macro-forecast-chain/SKILL.md', 
         'skills/portfolio-scenario-stress/SKILL.md']:
    text = open(f).read()
    for match in re.finditer(r'\`\`\`yaml\n(.*?)\n\`\`\`', text, re.DOTALL):
        try: yaml.safe_load(match.group(1))
        except yaml.YAMLError as e: print(f'INVALID YAML in {f}: {e}')
"
```

### Rollback

```bash
git reset --hard HEAD~1
```

### → Переход к Шагу 6

Все SKILL.md обновлены, YAML-примеры валидны.

---

## Шаг 6 — CW Phase 2: Тегирование lib_*.md

**Где:** Cowork (новый чат)
**Что:** добавить `implicit_geopolitical_scenarios` в 9 lib_*.md + обновить MEMORY.md + создать scenario-coverage audit
**Время:** 1 час

**Зависит от:** Шаг 3 завершён (нужна спека `events-yaml-spec.md`).

### Запуск

1. Новый Cowork-чат
2. Прикрепи 3 HANDOFF-файла
3. Промпт:
   ```
   Выполни Шаг 6 runbook'а: CW Phase 2 (тегирование 9 lib_*.md).
   Перед правкой каждого — backup в .pre-tagging.
   По §4 HANDOFF-cowork-data-phased.md, конкретные значения тегов в §4.2.
   После — обнови MEMORY.md и создай _audits/scenario-coverage-{date}.md.
   ```

### Что должно произойти

- 9 файлов в `.auto-memory/lib_*.md` получают `implicit_geopolitical_scenarios` блок
- 3 источника тегированы как `agnostic_total: true` (ВТБ-МИ, ЦБ, MS)
- MEMORY.md обновлён с пометками implicit
- Создан `Claude-Memory/_audits/scenario-coverage-{date}.md` с asymmetry warning

### Проверка

```bash
# Все 9 файлов имеют новый блок:
grep -l "implicit_geopolitical_scenarios" \
  ~/Library/Application\ Support/Claude/local-agent-mode-sessions/*/spaces/*/memory/lib_*.md

# Должен показать 9 файлов

# scenario-coverage audit существует:
cat ~/Library/CloudStorage/SynologyDrive-home/Ext_gDrive/Claude-Memory/_audits/scenario-coverage-*.md | head -30
# должно показать распределение implicit + asymmetry warning Sc-A=0
```

В Cowork-чате попроси:
```
Покажи trust-matrix всех 9 источников после тегирования: 
trust.marginal × implicit_scenario × agnostic_subdomains.
```

### Rollback

```bash
# Restore от backup'ов
for f in ~/Library/Application\ Support/Claude/.../lib_*.md.pre-tagging; do
  original="${f%.pre-tagging}"
  cp "$f" "$original"
done
```

### → Переход к Шагу 7

9 источников тегированы, scenario-coverage audit создан.

---

## Шаг 7 — CC Phase 3: Migration script

**Где:** Claude Code (тот же чат, что Шаги 3-5)
**Что:** реализовать `migrate_to_conditional.py` + тесты
**Время:** 2–3 часа

**Зависит от:** Шаг 5 (SKILL.md содержит примеры формата) + Шаг 6 (есть тегированные lib_*.md для тестов).

### Запуск

Промпт:
```
Выполни Шаг 7 runbook'а: CC Phase 3 (migration script).
Реализуй scripts/migrate_to_conditional.py согласно §4 HANDOFF-claude-code-phased.md.
Напиши тесты в tests/test_migration.py.
Тестовые данные — 3 reference YAML:
  • ru-rates-2026-2027-2026-05-04.yaml (linear, лучший)
  • cny-rub-dec2026-dec2027-2026-05-04.yaml (nonlinear, partial)  
  • ru-cpi-2026-2027-2026-05-04.yaml (markdown only, худший)
Скопируй reference YAMLs из Claude-Memory как fixtures (через scp или вручную).
pytest должен пройти. После — git commit.
```

### Что должно произойти

- `scripts/migrate_to_conditional.py` написан
- `tests/test_migration.py` написан
- Fixtures из Claude-Memory скопированы в `tests/fixtures/`
- pytest зелёный (миграция работает на 3 файлах)
- Коммит: `git commit -m "feat: migrate_to_conditional.py + tests (Phase 3)"`

### Проверка

```bash
cd ~/Documents/Программы/claude_skills
pytest tests/test_migration.py -v

# Должно пройти. Минимум:
# • test_migrate_ru_rates_linear (best case)
# • test_migrate_cny_rub_nonlinear_partial
# • test_migrate_ru_cpi_markdown_only
# • test_migration_chardet_mojibake
# • test_migration_creates_backup
```

### Rollback

```bash
git reset --hard HEAD~1
```

### → Переход к Шагу 8

Migration script работает на 3 reference fixtures.

---

## Шаг 8 — CC Phase 4: RECALIBRATE-mode

**Где:** Claude Code (тот же чат)
**Что:** реализовать `recalibrate.py` + интеграционный тест
**Время:** 2 часа

### Запуск

Промпт:
```
Выполни Шаг 8 runbook'а: CC Phase 4 (RECALIBRATE).
Реализуй skills/macro-forecast-chain/scripts/recalibrate.py 
согласно §5 HANDOFF-claude-code-phased.md.
Интегрируй в SKILL.md как режим --mode RECALIBRATE.
Напиши тесты в tests/test_recalibrate.py:
  • valid weight sum
  • modal scenario change detection
  • stale marginal auto-recalculate (soft)
  • --strict refuses stale
  • время выполнения < 30 секунд
После — git commit.
```

### Что должно произойти

- `scripts/recalibrate.py` написан
- `tests/test_recalibrate.py` написан
- pytest зелёный
- Коммит: `git commit -m "feat: RECALIBRATE-mode для cheap weight updates (Phase 4)"`

### Проверка

```bash
pytest tests/test_recalibrate.py -v

# Должны пройти все тесты, включая time-guard < 30s.
```

### Rollback

```bash
git reset --hard HEAD~1
```

### → Переход к Шагу 9

RECALIBRATE работает, тесты зелёные.

---

## Шаг 9 — CW Phase 3: Сплит macro-input

**Где:** Cowork (новый чат)
**Что:** разделить `macro-input-2026-05-04.yaml` на marginal + scenarios
**Время:** 1.5 часа

**Зависит от:** Шаг 5 (SKILL macro-forecast-chain обновлён).

### Запуск

1. Новый Cowork-чат
2. Прикрепи 3 HANDOFF-файла
3. Промпт:
   ```
   Выполни Шаг 9 runbook'а: CW Phase 3 (сплит macro-input).
   1. Backup исходника: macro-input-2026-05-04.yaml → .pre-split
   2. Создать macro-marginal-2026-05-04.yaml (Layer 1) + coherence_diagnostic
   3. Создать macro-scenarios-2026-05-04.yaml (Layer 2, 4 bundles)
   4. Verification: сумма весов через scenario reference = 1.0; 
      Layer 1 vs Layer 2 marginal divergence — допустимая severity
   5. Запись в _sync_log.md
   По §5 HANDOFF-cowork-data-phased.md.
   ```

### Что должно произойти

- `macro-input-2026-05-04.yaml` → `.pre-split`
- Созданы 2 новых файла
- coherence_diagnostic в `macro-marginal` показывает divergence < 15%
- `_sync_log.md` обновлён

### Проверка

```bash
ls -la ~/Library/CloudStorage/SynologyDrive-home/Ext_gDrive/Claude-Memory/macro-chain/
# Должно показать:
#   macro-input-2026-05-04.yaml.pre-split
#   macro-marginal-2026-05-04.yaml
#   macro-scenarios-2026-05-04.yaml
```

В Cowork-чате попроси:
```
Покажи coherence_diagnostic из macro-marginal-2026-05-04.yaml. 
Layer 1 vs Layer 2 divergence — какая severity?
```

Если severity HIGH — разбирайся (в большинстве случаев — asymmetric coverage Sc-A; это известная проблема, не блокирует).

### Rollback

```bash
cd /sessions/.../mnt/Claude-Memory/macro-chain
mv macro-input-2026-05-04.yaml.pre-split macro-input-2026-05-04.yaml
rm macro-marginal-2026-05-04.yaml macro-scenarios-2026-05-04.yaml
```

### → Переход к Шагу 10

Split выполнен, divergence приемлемая, backup на месте.

---

## Шаг 10 — CW Phase 4: Stress test rerun

**Где:** Cowork (тот же чат, что Шаг 9)
**Что:** перезапустить stress на coherent bundles + написать comparison doc
**Время:** 30 минут

**Зависит от:** Шаг 5 (SKILL portfolio-scenario-stress обновлён) + Шаг 9 (macro-scenarios существует).

### Запуск

Промпт:
```
Выполни Шаг 10 runbook'а: CW Phase 4 (stress rerun).
Запусти portfolio-scenario-stress на macro-scenarios-2026-05-04.yaml
(новый, coherent bundles). Сохрани в Ретроспективный анализ/
stress-2026-05-XX-coherent-v2.yaml.
Создай stress-comparison-2026-05-XX.md с diff vs старый stress.
По §6 HANDOFF-cowork-data-phased.md.
```

### Что должно произойти

- Создан `Ретроспективный анализ/stress-2026-05-XX-coherent-v2.yaml`
- Создан `Ретроспективный анализ/stress-comparison-2026-05-XX.md`
- expected_pl_pct отсутствует (D2)
- modal_scenario_id = none (D1, equal weights)
- robustness verdict присутствует

### Проверка

```bash
ls -la ~/Documents/Claude/Projects/Ретроспективный\ анализ/stress-*-coherent-v2.yaml
ls -la ~/Documents/Claude/Projects/Ретроспективный\ анализ/stress-comparison-*.md
```

В Cowork-чате попроси:
```
Покажи 4 ΔP&L точки из нового стресса и diff vs старый stress.
Если |new - old| > 2% — это сигнал, что mixed-worlds artifact в старом был большим.
```

### Rollback

Старый stress YAML не трогается. Если новый кривой:
```bash
rm ~/Documents/Claude/Projects/Ретроспективный\ анализ/stress-*-coherent-v2.yaml
rm ~/Documents/Claude/Projects/Ретроспективный\ анализ/stress-comparison-*.md
```

### → Переход к Шагу 11

Новый stress существует, robustness verdict читаем, diff vs старый описан.

---

## Шаг 11 — CC Phase 5: Tests + CI

**Где:** Claude Code (тот же чат)
**Что:** прогнать полный pytest, настроить CI
**Время:** 2 часа

### Запуск

Промпт:
```
Выполни Шаг 11 runbook'а: CC Phase 5 (tests + CI).
1. Прогон полного pytest (всех тестов)
2. Integration test end-to-end:
   scenario YAML edit → RECALIBRATE → новый stress YAML
3. Schema validator scripts/validate_schema.py
4. Pre-commit hook (опционально, если настраивается без git push)
По §6 HANDOFF-claude-code-phased.md.
После — git commit и merge feature branch в main.
```

### Что должно произойти

- pytest зелёный (все тесты от Шагов 4, 7, 8 + новые integration)
- `scripts/validate_schema.py` создан
- Pre-commit hook (если в репо есть .pre-commit-config) обновлён
- Коммит: `git commit -m "test: full coverage for conditional architecture (Phase 5)"`
- Merge: `git checkout main && git merge conditional-architecture-upgrade`

### Проверка

```bash
cd ~/Documents/Программы/claude_skills
pytest -v
# Все зелёные

git log --oneline | head -10
# 5-6 коммитов на feature-branch

# После merge:
git log --oneline main | head -10
# Все коммиты в main
```

### Rollback (если что-то развалилось перед merge)

```bash
git checkout main
git branch -D conditional-architecture-upgrade
```

### → Стабильная система

Архитектура работает, тесты зелёные, всё в main. **Можно использовать в production**.

---

## Шаг 12 (lazy, по запросу) — CW Phase 5: Forecast migration

**Где:** Cowork
**Что:** мигрировать forecast YAMLs в `conditional_on_scenarios` схему
**Когда:** **по мере следующего refresh каждого фактора**, не batch.
**Время:** 30 минут на файл

### Запуск (для одного файла, например ru-cpi)

Промпт:
```
Выполни Шаг 12 runbook'а для ru-cpi-2026-2027-2026-05-04.yaml.
1. Backup в .pre-migration
2. Запуск migrate_to_conditional.py (из репо ~/Documents/Программы/claude_skills/)
3. Diff review
4. Schema validate
5. Promote (replace original)
По §7 HANDOFF-cowork-data-phased.md.
```

### Очередность приоритета

1. `ru-cpi-2026-2027-2026-05-04.yaml` (худший YAML — как референс)
2. `ru-rates-2026-2027-2026-05-04.yaml` (лучший — должен пройти clean)
3. `cny-rub-dec2026-dec2027-2026-05-04.yaml` (nonlinear partial)
4. Далее — по мере refresh каждого фактора в обычном workflow

### Проверка per file

```bash
# До:
diff <(yaml file_before.yaml) <(yaml file_after.yaml)

# Schema validate:
python ~/Documents/Программы/claude_skills/scripts/validate_schema.py file.yaml
```

### Rollback per file

```bash
mv file.yaml.pre-migration file.yaml
```

---

## Шаги 13+ (deferred): Phase 6, 7

**Phase 6** (3D retrospective audit) — **через 6+ месяцев**, при первом резолвед-прогнозе.
**Phase 7** (scenario-level meta-audit) — **через 12+ месяцев**, при ≥6 резолюций.

Когда подойдёт время — снова через handoff-документы и runbook-добавление.

---

## Cheat sheet: что где запускать

| Шаг | Среда | Модель | Время | Зависит от |
|-----|-------|--------|-------|------------|
| 1. Coherence audit | Cowork | Sonnet 4.6 | 1.5ч | — |
| 2. Унификация весов | Cowork | Sonnet 4.6 | 30мин | Шаг 1 |
| 3. Спецификации | Claude Code | **Opus 4.6** | 2-3ч | — (parallel с CW) |
| 4. weighted_consensus.py | Claude Code | Sonnet 4.6 | 2ч | Шаг 3 |
| 5. SKILL.md правки | Claude Code | Sonnet 4.6 | 2ч | Шаг 3 |
| 6. Tagging lib_*.md | Cowork | **Haiku 4.5** | 1ч | Шаг 3 |
| 7. Migration script | Claude Code | Sonnet 4.6 | 2-3ч | Шаги 5, 6 |
| 8. RECALIBRATE | Claude Code | Sonnet 4.6 | 2ч | Шаг 4 |
| 9. Сплит macro-input | Cowork | Sonnet 4.6 | 1.5ч | Шаг 5 |
| 10. Stress rerun | Cowork | Sonnet 4.6 | 30мин | Шаги 5, 9 |
| 11. Tests + CI + merge | Claude Code | Sonnet 4.6 | 2ч | Шаги 4, 7, 8 |
| 12. Forecast migration | Cowork | Haiku 4.5 (Sonnet если файл странный) | 30мин/файл | Шаг 7 |

**Минимально возможный путь (sequential):** Шаги 1→2→3→4→5→6→7→8→9→10→11.
**Параллелизация:** Шаги 1+2 (Cowork) и Шаг 3 (Claude Code) можно запускать одновременно.
Шаг 6 (Cowork) и Шаги 7-8 (Claude Code) тоже параллелятся.

---

## Главные правила безопасности

1. **Не пропускай проверки.** Каждый шаг имеет verification — выполняй его.
2. **Backup перед каждой правкой данных.** Cowork делает `.pre-X`, Claude Code — git commit.
3. **Если проверка не сошлась — не двигайся дальше.** Разбирайся.
4. **Cowork не правит код, Claude Code не правит данные.** Не путай среды.
5. **Documentation source of truth — handoff-файлы.** Если runbook конфликтует с handoff — handoff важнее.
6. **Один шаг = один логически завершённый блок.** Не разбивай шаги между сессиями (кроме Шага 12 — он lazy).

---

## Если что-то пошло не так

| Симптом | Действие |
|---------|----------|
| Cowork не видит Claude-Memory | `mcp__cowork__request_cowork_directory(path="...")` повторно |
| pytest красный после Шага 4-8 | git revert последнего коммита, читай stack trace, чини |
| Sum of weights ≠ 1.0 после Шага 2 | Rollback из `.pre-d1-unification`, повтор |
| Layer 1 vs Layer 2 divergence > 30% | Не баг — это сигнал асимметричного coverage; читай `coherence_diagnostic.warning` |
| Migration script падает на одном файле | Это нормально (edge cases). Заведи issue, мигрируй вручную, остальные продолжают |
| Stress rerun дал странные ΔP&L | Сравни с старым через comparison doc; если delta ≥ 5% — это и был mixed-worlds artifact |
| RECALIBRATE превышает 30 секунд | Time-guard в тестах должен был это поймать. Профилируй, оптимизируй |

---

## Финальный sanity check после всех шагов

После Шага 11 в production должно быть:

- [ ] `~/Documents/Программы/claude_skills` — main с merged feature branch
- [ ] pytest зелёный
- [ ] Все 5 SKILL.md обновлены
- [ ] Claude-Memory: 5 файлов с весами 0.25 each, sum=1.0
- [ ] 9 lib_*.md тегированы
- [ ] macro-marginal + macro-scenarios существуют (вместо macro-input)
- [ ] Новый stress YAML с robustness verdict (без expected_pl_pct)
- [ ] Все backup'ы (`.pre-X` и `.pre-split`) на месте — на случай regression

Если всё это есть — апгрейд завершён.
