# Примеры использования portfolio-coherence-audit

Готовые промты и команды для мета-аудита когерентности. Главное разделение:

| Стадия | Что это | Модель | Стоимость |
|---|---|---|---|
| **Stage P** | Python-скрипт, сборка bundle + все детерминированные проверки | **любая** (скрипт без LLM; хоть Haiku-сессия, хоть cron) | копейки |
| **Stage R** | рассуждение по bundle: существенность, red-team, артефакт | **Fable** | дорого → по сигналу или ежемесячно |

> Правило: **Stage R не запускается без Stage P** (нет валидированного bundle — нечего
> рассуждать), а Stage P без Stage R запускается сколько угодно — это и есть дешёвая
> проверка «есть ли повод».

---

## Сценарий 1. Дешёвая проверка «есть ли повод для Fable» (Stage P соло)

Когда: после каждого цикла weekly-review / обновления стресса; перед тем как жечь Fable.
Модель сессии: любая.

### Промт

```
/portfolio-coherence-audit Прогони Stage P и скажи, есть ли повод для полного прогона.
```

### Что произойдёт

Скилл запустит скрипт (Claude-Memory root подставит из транспорта):

```bash
python3 skills/portfolio-coherence-audit/scripts/build_coherence_bundle.py \
  --dir "<Claude-Memory root>" --asof 2026-07-28 \
  --out coherence-input-bundle-2026-07-28.json
```

и прочитает stderr + `watch_verdict` из bundle:

```
[Stage P] consistency=ok  bundle=coherence-input-bundle-2026-07-28.json
[Stage P] fable_recommended=True  counts={'contradictions': 1, 'mc_flagged': 3, 'joint_drawdown_cells': 2}
  * новые противоречия: ['cbr_rate/m12']
```

### Как читать вердикт

- `fable_recommended=True` + список `signals` → есть **новые** сигналы против прошлого
  bundle — полный прогон оправдан.
- `fable_recommended=False` → новых сигналов нет. Это **не запрет**: календарный
  месячный прогон — твоё решение. Висящие (persisting) сигналы не триггерят повторно —
  они уже были в прошлом аудите.
- Первый прогон (нет прошлого bundle) → всегда `True` с пометкой «baseline».

---

## Сценарий 2. Полный месячный прогон (Stage P → Stage R)

Когда: ежемесячно, на смене режима (шаг ЦБ, санкционный сдвиг, слом нефти) или по
`fable_recommended=True`. Модель: **Fable** (на другой модели скилл предупредит).

### Промт

```
/portfolio-coherence-audit Проверь когерентность портфеля: противоречия, скрытые связки, red-team вывода.
```

### Что скилл сделает сам (не повторять в промте)

- Stage P: найдёт свежайшие snapshot / stress / оба weekly / integrated-view,
  сверит **дату снапшота** между ними (HARD STOP при рассинхроне), соберёт bundle.
- Прошлый bundle найдёт сам (рядом с `--out`) → `diachronic` заполнится автоматически.
- R1: отберёт существенные противоречия из `contradiction_candidates` (точка вне конуса /
  sign-conflict), взвесив их `point_confidence`.
- R2: разберёт `factor_overlap` — какие reinforcing-пересечения реальны экономически.
- R3: red-team вывода equity-vs-bond (Pre-mortem + Devil's Advocate + Reversibility) →
  вердикт устойчивости + ЕДИНСТВЕННОЕ несущее допущение + фальсификатор.
- R5: изложит детерминированные находки (blindspots, mc_divergence, joint_tail,
  unrealizable, iis3, consensus_dispersion, diachronic) с оценкой существенности.
- Запишет `Portfolio/coherence-audits/coherence-audit-<date>.md` (**дефолт — в файл**),
  в чат — только TL;DR + 3–5 пунктов.
- `predictions_for_review` (≥3) — их дальше отслеживает forecast-monitor.

### Что получишь в чате (пример TL;DR)

```markdown
## TL;DR
- **Вердикт:** акции > облигации на h12 подтверждается · устойчивость: Средняя
- **Несущее допущение:** траектория КС −3 п.п. к m12 · **Фальсификатор:** пауза ЦБ на двух заседаниях подряд
- **Находка 1 (§1):** L1 по cbr_rate (+0.5 п.п.) вне конуса стресса [−3, −0.5] — спред висит на неразрешённом допущении
- **Находка 2 (§2):** sanctions/usdrub двигают ОБЕ ноги — «диверсификация облигациями» частично иллюзорна
- **Находка 3 (§3):** worst joint-ячейка: сценарий D, m12 — equity −14% и bond −5% одновременно (p=0.30)
- **R1-статус:** противоречие (1) · **Файл:** Portfolio/coherence-audits/coherence-audit-2026-07-28.md
```

---

## Сценарий 3. HARD STOP — артефакты из разных поколений

Stage P вернул exit 2:

```
[Stage P] consistency=stop  bundle=coherence-input-bundle-2026-07-28.json
  - snapshot date mismatch across artifacts: {'snapshot': '2026-07-28', 'stress': '2026-07-02', ...}
[Stage P] HARD STOP — do NOT run Fable on this bundle.
```

**Что делать:** перегнать отставший артефакт на свежем снапшоте и повторить Stage P.
В примере выше отстал stress:

```
/macro-forecast-chain Обнови макро-прогноз.
/portfolio-scenario-stress Прогони стресс на свежем снапшоте.
/portfolio-coherence-audit Повтори Stage P.
```

Fable на рассинхронных входах не запускается — кросс-артефактный анализ на смеси
поколений даёт мусор с уверенным лицом. Это дороже, чем подождать перегона.

---

## Сценарий 4. Нестандартные запуски

**Явные пути (минуя auto-discovery):**

```bash
python3 skills/portfolio-coherence-audit/scripts/build_coherence_bundle.py \
  --snapshot .../portfolio-2026-07-28.json \
  --stress .../stress-2026-07-28-fable.yaml \
  --weekly-stock .../weekly-review-stock-2026-07-28.yaml \
  --weekly-bond .../weekly-review-bond-2026-07-28.yaml \
  --integrated-view .../integrated-view-2026-07-28.md \
  --macro-marginal .../macro-marginal-2026-07-25.yaml \
  --asof 2026-07-28 --out bundle.json
```

**Дифф с конкретным прошлым прогоном** (вместо авто-поиска):

```bash
  ... --prev-bundle coherence-input-bundle-2026-06-28.json
```

**Consensus-dispersion по конкретной папке прогнозов** (по умолчанию `<--dir>/forecasts`):

```bash
  ... --forecasts-dir "<Claude-Memory root>/forecasts"
```

---

## Как читать ключевые блоки bundle (шпаргалка)

**Противоречие (R1):**

```json
{"factor": "cbr_rate", "horizon": "m12",
 "scenario_cone": [-3.0, -0.5],
 "point_views": {"macro-L1:cbr_rate": 0.5},
 "point_confidence": {"macro-L1:cbr_rate": 0.72},
 "points_outside_cone": {"macro-L1:cbr_rate": 0.5}}
```

→ стресс закладывает ставку только вниз (−0.5…−3 п.п.), а L1-прогноз — **вверх** на
+0.5 п.п., с приличной уверенностью 0.72. Точка вне конуса = у пайплайна два
несовместимых мира, и вывод integrated-view стоит на одном из них.

**Скрытая концентрация (R2):**

```json
{"factor": "usdrub", "equity_exposure": 0.31, "bond_exposure": 0.08,
 "both_legs": true, "direction": "reinforcing"}
```

→ девальвация двигает и акции, и облигации **в одну сторону** (обе экспозиции
положительные). Спред «акции − облигации» это вычитает и маскирует; реальный риск
на фактор — сумма ног, а не разность.

**Joint tail (§3):**

```json
{"scenario": "D", "horizon": "m12", "equity_delta_pct": -14.0,
 "bond_delta_pct": -5.0, "combined_delta_pct": -10.0,
 "joint_drawdown": true, "probability": 0.3}
```

→ есть ячейка, где обе ноги падают одновременно. Это **ценовой** слой: carry
облигаций смягчит фактический результат — оговорка всегда идёт рядом.

**Diachronic:**

```json
{"contradictions": {"new": ["brent/m12"], "persisting": ["cbr_rate/m12"], "closed": []}}
```

→ `persisting` ≥2 прогона = систематическое расхождение пайплайна (более серьёзный
сигнал, чем свежий «шум месяца»); `closed` = что закрылось после перегона артефактов.

---

## FAQ

**`contradiction_candidates` пуст — всё согласовано?** Смотри `assumption_ledger`:

- есть строки `source_class: point` → числовая сверка прошла, L1 **внутри** конуса —
  да, согласованы (Fable так и напишет);
- точечных строк нет → **пробел покрытия**: не загружен `macro-marginal` (или weekly
  пришли как `.md`). Сценарный конус сам с собой не противоречит — нужен независимый
  точечный взгляд.

**Почему weekly нужны `.yaml`, а не `.md`?** Структурные `catalyst.macro_dependency`
лежат в `.yaml`; `.md` — нарратив, скрипт его примет, но пометит degraded.

**`mc_divergence` флагнул bond на всех горизонтах — что это значит?** У ноги два
центральных значения (headline из `portfolio_by_horizon` vs `total_return.expected`)
или CI не покрывает headline → ширине CI спреда доверять нельзя, пока integrated-view
не перегнан на едином каноне (@1.4).

**Можно ли запустить Stage R на Opus?** Тест из SKILL.md: если разбор помещается в один
заход Opus без потери когерентности — задача вообще не для этого скилла. Fable здесь
не «лучше», а порогово необходим (whole-corpus coherence). На слабой модели скилл
предупредит по правилу model-routing.
