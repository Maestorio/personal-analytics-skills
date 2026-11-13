# Фаза 1 — E2E проверки на реальных данных

> Этот файл — инструкция для ручной локальной проверки изменений Фазы 1 на реальных артефактах из `Claude-Memory/`.  
> Юнит-тесты (`python3 tests/test_*.py`) покрывают детерминированную математику.  
> E2E-проверки ниже — для того, чтобы убедиться, что скрипты работают с **реальными YAML/JSON** из Synology.

---

## Предусловия

```bash
# Установить зависимости (если нужно)
pip install pyyaml --break-system-packages

# Все команды запускать из корня репозитория
cd ~/claude_skills   # или куда склонирован repo
```

---

## IV-B — Catalyst R7 pipeline (forecast-monitor читает weekly-review)

**Цель:** убедиться, что `monitor_alerts.py compute` генерирует `kind: catalyst` алерты
для `auto_checkable: true` катализаторов из реального weekly-review.

### Шаг 1. Подготовить payload

```python
import yaml, json
from datetime import date

# Читать реальный weekly-review
with open("PATH/Claude-Memory/Portfolio/weekly-reviews/weekly-review-stock-2026-LATEST.yaml") as f:
    wr = yaml.safe_load(f)

# Извлечь auto_checkable катализаторы
catalysts_payload = []
for ticker, pos in (wr.get("per_stock") or {}).items():
    for cat in (pos.get("catalyst") or []):
        if cat.get("auto_checkable") is True:
            catalysts_payload.append({
                "ticker": ticker,
                "review_date": wr.get("review_date", str(date.today())),
                "catalyst": cat,
            })

print(f"Найдено auto_checkable катализаторов: {len(catalysts_payload)}")
for c in catalysts_payload:
    print(f"  {c['ticker']}: {c['catalyst'].get('id')} | window={c['catalyst'].get('date_window')} | check_what={c['catalyst'].get('check_what')}")
```

### Шаг 2. Собрать минимальный payload для compute

```python
# Минимальный payload: только weekly_review_catalysts (без прогнозов и сценариев)
payload = {
    "today": str(date.today()),
    "n_red": 7,
    "max_searches": 5,
    "forecasts": [],
    "scenarios": [],
    "weekly_review_catalysts": catalysts_payload,
}

with open("/tmp/monitor_payload_test.json", "w") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
```

### Шаг 3. Запустить compute

```bash
python3 skills/forecast-monitor/scripts/monitor_alerts.py compute \
    --input /tmp/monitor_payload_test.json \
    --pretty
```

**Ожидаемый результат:**
- Для катализатора с `date_window` в прошлом (например `2026-Q1`) → алерт `severity: red`, `kind: catalyst`
- Для катализатора с `date_window` в будущем (вне окна ±7) → алерт отсутствует
- Поле `source_file` содержит ticker, `check_what` содержит наблюдаемый исход

**Если `auto_checkable: true` катализаторов нет в реальном weekly-review:**  
→ Нужно добавить поля `auto_checkable: true` и `check_what: "..."` в следующий обзор акций.  
→ Схема полей: `skills/ru-portfolio-advisor/references/weekly-review-schema-v1.md` (секция catalyst).

---

## IV-C — Sanity checks для extreme values

**Цель:** убедиться, что при запуске `aggregate_positions.py` с реальным стресс-тестом
`validation.sanity_warnings` корректно пуст (нет ложных срабатываний).

### Шаг 1. Подготовить payload из реальных файлов

```python
import yaml, json

# Читать артефакты (через Synology или локально)
with open("PATH/Claude-Memory/Portfolio/snapshots/portfolio-LATEST.json") as f:
    snapshot = json.load(f)

with open("PATH/Claude-Memory/Portfolio/stress/stress-LATEST.yaml") as f:
    stress = yaml.safe_load(f)

with open("PATH/Claude-Memory/Portfolio/weekly-reviews/weekly-review-stock-LATEST.yaml") as f:
    review_stocks = yaml.safe_load(f)

payload = {
    "snapshot": snapshot,
    "stress": stress,
    "review_stocks": review_stocks,
}

with open("/tmp/iv_c_payload.json", "w") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
```

### Шаг 2. Запустить скрипт

```bash
python3 skills/portfolio-integrated-view/scripts/aggregate_positions.py \
    --input /tmp/iv_c_payload.json \
    --pretty | python3 -c "
import json, sys
r = json.load(sys.stdin)
sw = r['validation']['sanity_warnings']
if sw:
    print(f'⚠️  {len(sw)} sanity warnings:')
    for w in sw: print(f'  [{w[\"severity\"]}] {w[\"type\"]}: {w.get(\"message\",\"\")}')
else:
    print('✅ Sanity warnings: пусто (норма для чистых данных)')
"
```

**Ожидаемый результат:**
- На корректных реальных данных → `sanity_warnings: []`
- Если WARNING: проверить конкретную позицию. Например, `total.value > 100` может означать ошибку в stress YAML (единицы измерения не в процентах) или баг в upstream.
- **Кейс put/offer-облигаций (исправлено):** раньше бумага с офертой (MOEX отдаёт `ytm_pct` = yield-to-offer, напр. 414%) давала carry ≈ ytm × горизонт = сотни % и срабатывал `extreme_total_pct`. Теперь `aggregate_div_or_carry` при оферте/погашении внутри горизонта (а) берёт базис `coupon_pct` если `ytm_pct` неправдоподобен (>60%), (б) capping горизонта до даты события, (в) backstop-клампит `|carry| ≤ 50`. Экономику оферты несёт catalyst `offer_exit`. Если в реальном bond-review всё ещё лежит `ytm_pct > 100` — это флагует `revise-memory-remote` (`bond_ytm_implausible`).

---

## IV-A — Diff с предыдущим integrated-view

**Цель:** убедиться, что новый ключ `diff` появляется при передаче `previous_view`.

### Шаг 1. Подготовить previous_view из прошлого артефакта

```python
import re, json

# Прочитать прошлый integrated-view markdown и извлечь per-position строки
# (формат таблицы §3: | TICKER | доля | verdict | expected | ... |)
# Пример парсера (адаптировать к реальному формату шаблона):

def extract_previous_view(iv_md_path):
    with open(iv_md_path) as f:
        text = f.read()
    rows = []
    for line in text.split("\n"):
        # Ищем строки таблицы с тикером (2+ символа uppercase)
        m = re.match(r"\|\s*([A-Z]{2,}[0-9]*)\s*\|.*?(\d+\.\d+)%.*?\|\s*(\w+)\s*\|.*?([+-]?\d+\.\d+)%", line)
        if m:
            rows.append({
                "ticker": m.group(1),
                "weight_pct": float(m.group(2)),
                "verdict": m.group(3),
                "total_value": float(m.group(4)),
                "verification_priority": "MEDIUM",
            })
    return rows

previous_view = extract_previous_view("PATH/Claude-Memory/Portfolio/integrated-views/integrated-view-PREV.md")
print(f"Извлечено {len(previous_view)} позиций из previous_view")
```

### Шаг 2. Добавить previous_view в payload и запустить

```python
payload["previous_view"] = previous_view

with open("/tmp/iv_a_payload.json", "w") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
```

```bash
python3 skills/portfolio-integrated-view/scripts/aggregate_positions.py \
    --input /tmp/iv_a_payload.json \
    --pretty | python3 -c "
import json, sys
r = json.load(sys.stdin)
diff = r.get('diff')
if diff is None:
    print('❌ diff is None — previous_view не был передан или пуст')
else:
    print(f'✅ diff присутствует: +{diff[\"total_added\"]} новых, -{diff[\"total_removed\"]} удалено, {diff[\"total_changed\"]} изменений')
    for vc in diff.get('verdict_changes', []):
        print(f'  Смена verdict: {vc[\"ticker\"]} {vc[\"from\"]} → {vc[\"to\"]}')
    for lm in diff.get('large_moves', []):
        print(f'  Крупное движение: {lm[\"ticker\"]} Δ={lm[\"delta\"]:+.1f}пп')
"
```

---

## IV-E — Layer 1 macro (coherence_gap)

**Цель:** убедиться, что при наличии числового `macro_marginal` скрипт переключается на Layer 1
и выдаёт `coherence_gap`; а на текущем (прозаичном) формате — gracefully остаётся на L2 без краша.

> ⚠ **Известное ограничение Phase 1.** В реальных `macro-marginal-{date}.yaml` ВСЕ `central_estimate`
> (включая версионные `central_estimate_l1_<год>`) — человекочитаемые **строки** с уровнем и единицами
> (`'$68/bbl (JPMorgan…)'`, `'88 руб./$'`), а не числа, и это **уровень**, а не движение. Поэтому Шаг 1
> на реальном файле даёт **пустой** `macro_marginal` → integrated-view остаётся на **L2** (это корректное
> поведение после фикса guard, раньше тут был краш `ValueError`). Полноценный L1 на реальных данных
> заработает после апстрим-апгрейда `macro-forecast-chain` (числовое поле ожидаемого движения по фактору)
> — см. TODO. Проверку L1-механики ниже делаем на синтетическом beta-keyed payload (Шаг 2-альт).

**Предусловие:** наличие `macro-chain/macro-marginal-LATEST.yaml`.

### Шаг 1. Парсить macro-marginal

```python
with open("PATH/Claude-Memory/macro-chain/macro-marginal-LATEST.yaml") as f:
    macro_marginal_raw = yaml.safe_load(f)

# Контракт payload (см. portfolio-integrated-view/SKILL.md):
#   {beta_key: {central_estimate: <ЧИСЛО>}}, ключ = имя из factor_betas (geopol, brent, …).
# В реальном файле числовые оценки лежат в central_estimate_l1_<год>, а верхнеуровневый
# central_estimate для shell-факторов (geopolitics/sanctions) — СТРОКА → её опускаем.
ALIAS = {"geopolitics": "geopol"}     # macro-marginal → factor_betas
YEAR = "2026"                          # горизонт integrated-view
macro_marginal = {}
for factor, data in (macro_marginal_raw.get("factors") or macro_marginal_raw).items():
    if not isinstance(data, dict):
        continue
    ce = None
    for key in (f"central_estimate_l1_{YEAR}", f"central_estimate_{YEAR}", "central_estimate"):
        v = data.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            ce = float(v); break
    if ce is None:                     # качественный/строковый central_estimate (shell) → пропуск
        continue
    macro_marginal[ALIAS.get(factor, factor)] = {"central_estimate": ce}

print(f"Числовых факторов в macro_marginal: {len(macro_marginal)}")
print("Факторы (beta-ключи):", list(macro_marginal.keys()))

# Проверить наличие factor_betas в stress per_position
stress_pp = stress.get("per_position") or {}
tickers_with_betas = [t for t, p in stress_pp.items() if p.get("factor_betas")]
print(f"Тикеров с factor_betas в stress: {len(tickers_with_betas)}: {tickers_with_betas[:5]}")
```

### Шаг 2. Запустить с macro_marginal

```python
payload["macro_marginal"] = macro_marginal

with open("/tmp/iv_e_payload.json", "w") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)
```

```bash
python3 skills/portfolio-integrated-view/scripts/aggregate_positions.py \
    --input /tmp/iv_e_payload.json \
    --pretty | python3 -c "
import json, sys
r = json.load(sys.stdin)
for pos in r.get('per_position', []):
    macro = pos.get('macro', {})
    layer = macro.get('layer')
    gap = macro.get('coherence_gap')
    ticker = pos.get('ticker')
    if layer == 'L1':
        marker = '⚡ L1' if (gap is not None and gap > 3) else 'L1'
        print(f'{marker} {ticker}: L1={macro[\"value\"]:.1f}пп, coherence_gap={gap}пп')
    else:
        print(f'  L2 {ticker}: {macro.get(\"value\")}пп (нет factor_betas или macro_marginal)')
"
```

**Ожидаемый результат:**
- Тикеры с `factor_betas` + хотя бы один числовой сопоставимый фактор в `macro_marginal` → `layer: L1`, `coherence_gap` в пп
- Тикеры без `factor_betas` → `layer: L2`, `coherence_gap: null`
- Если `macro_marginal` собран без числовых факторов (например, передали только строковые shell-оценки) → скрипт НЕ падает (guard на нечисловой `central_estimate`) и остаётся `layer: L2`. Чтобы получить L1 — извлекать `central_estimate_l1_<год>` (см. Шаг 1), а не строковый верхнеуровневый `central_estimate`.
- Имена факторов в `macro-marginal.yaml` (`geopolitics`) не равны ключам `factor_betas` (`geopol`) — скрипт делает alias `geopolitics→geopol` (`MACRO_FACTOR_ALIASES`); прочие — передавать уже под beta-именами.
- Если `coherence_gap > 3` → стоит перепроверить соответствие L1 и L2 (может указывать на устаревший macro_marginal или неверные β)

### Шаг 2-альт. L1-смоук на синтетическом beta-keyed payload

Поскольку реальный `macro-marginal` сейчас прозаичный (см. ограничение выше) и Шаг 2 даёт L2,
проверяем саму L1-механику синтетическим payload с числовыми движениями под beta-ключами:

```python
payload["macro_marginal"] = {           # ключи = имена factor_betas в stress
    "brent": {"central_estimate": 4.0}, "usdrub": {"central_estimate": 3.0},
    "cnyrub": {"central_estimate": 2.0}, "cbr_rate": {"central_estimate": -1.5},
    "xauusd": {"central_estimate": 2.5},
}
import json; json.dump(payload, open("/tmp/iv_e_synth.json","w"), ensure_ascii=False)
```

```bash
python3 skills/portfolio-integrated-view/scripts/aggregate_positions.py \
    --input /tmp/iv_e_synth.json | python3 -c "
import json,sys; from collections import Counter
r=json.load(sys.stdin)
print('layer dist:', dict(Counter(p['macro'].get('layer') for p in r['per_position'])))
"
```
Ожидаемо: тикеры с `factor_betas` → `L1` + ненулевой `coherence_gap`. Так подтверждаем, что L1-путь рабочий.

**Ожидаемый результат (реальный Шаг 2):** на текущем формате `macro_marginal` пуст → все `layer: L2`, краша нет.

**Viewer-проверка:** открыть `tools/portfolio-integrated-viewer.html`, загрузить stress YAML с `factor_betas`. В карточке позиции (Декомпозиция ожиданий) строка «Макро» будет помечена `⚡L1` — это сигнал, что Layer 1 available.

---

## SB-1 — axis_dependent migration (smoke test)

**Цель:** убедиться, что при миграции реального forecast YAML с `method: axis_dependent` нет `_todo` в выходном YAML.

```bash
# Найти forecast с axis_dependent (если есть)
grep -rl "axis_dependent" Claude-Memory/forecasts/ 2>/dev/null | head -3

# ВАЖНО: в --dry-run migrator печатает ЛОГ операций (не итоговый YAML), поэтому
# для проверки результата мигрируем КОПИЮ в /tmp с --output (Claude-Memory не трогаем).
cp "PATH/Claude-Memory/forecasts/SOME-FORECAST.yaml" /tmp/sb1_src.yaml
python3 scripts/migrate_to_conditional.py \
    --input /tmp/sb1_src.yaml \
    --scenario "PATH/Claude-Memory/scenarios/scenario-geopolitics-ru-west-2026-05-04.yaml" \
    --output /tmp/sb1_out.yaml --no-backup

python3 -c "
import yaml
data = yaml.safe_load(open('/tmp/sb1_out.yaml'))
marg = (data.get('conditional_on_scenarios') or {}).get('marginal', {})
if marg.get('method') == 'axis_dependent':
    assert '_todo' not in marg, f'_todo должен отсутствовать: {marg}'
    assert marg.get('aggregation_formula') == 'weighted_mean', f'Expected weighted_mean: {marg}'
    print('✅ SB-1: axis_dependent resolved без _todo')
else:
    print(f'(method={marg.get(\"method\")} — не axis_dependent, пропущено)')
"
```

---

## Полная прогонка юнит-тестов (финальная верификация)

```bash
# Запускать из корня репозитория
python3 skills/forecast-monitor/tests/test_monitor_alerts.py       # 114 проверок
python3 skills/portfolio-integrated-view/tests/test_aggregate_positions.py  # 99 проверок
python3 tests/test_migration.py                                      # 22 проверки
python3 skills/revise-memory-remote/tests/test_validate_library.py  # 122 проверки
python3 skills/save-to-library/tests/test_assemble_artifact.py      # 232 проверки
python3 skills/portfolio-data-loader/tests/test_bond_enrichment.py  # 17 проверок
```

Все должны пройти 100%.

---

## Ожидаемые артефакты в Claude-Memory после первого боевого прогона

| Артефакт | Путь | Когда создаётся |
|---|---|---|
| `integrated-view-{date}.md` | `Portfolio/integrated-views/` | После первого запуска portfolio-integrated-view с новым payload |
| `monitor-report-{date}.yaml` | `monitor-reports/` | После forecast-monitor Шага 7 с реальными weekly-review_catalysts |
| `weekly-review-stock-{date}.yaml` + `.md` | `Portfolio/weekly-reviews/` | После следующего ru-portfolio-advisor с `auto_checkable` полями |

---

*Создан 2026-06-09 как часть Фазы 1 v1.1. Обновить при смене схемы payload или формата артефактов.*
