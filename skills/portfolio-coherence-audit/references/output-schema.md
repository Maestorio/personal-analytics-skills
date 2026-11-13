# Выходной артефакт: `coherence-audit@1.1`

Файл: `coherence-audit-<date>.md`. Markdown с YAML-frontmatter.
По умолчанию записывается в файл `Claude-Memory/Portfolio/coherence-audits/`; в чат уходит только TL;DR +
основное (см. SKILL.md §«Вывод и сохранение»).

## Frontmatter

```yaml
---
schema_version: "coherence-audit@1.1"
date: <YYYY-MM-DD>
model: claude-fable-5
snapshot_id: <из bundle.consistency.snapshot_ids.snapshot>
inputs:                       # из bundle.provenance — файл + возраст
  - {artifact: snapshot,        date: ..., age_days: ...}
  - {artifact: stress,          date: ..., age_days: ...}
  - {artifact: weekly_stock,    date: ..., age_days: ...}
  - {artifact: weekly_bond,     date: ..., age_days: ...}
  - {artifact: integrated_view, date: ..., age_days: ...}
consistency_status: ok | degraded         # stop сюда не доходит (Stage P остановил)
robustness_verdict: Высокая | Средняя | Низкая
load_bearing_assumption: "<одно допущение, чей flip ломает вывод>"
review_date: <YYYY-MM-DD>
---
```

## TL;DR (первый блок тела, обязателен, ~6 строк)

Идёт сразу после frontmatter, до §0. Ровно то, что дублируется в чат. Формат:

```markdown
## TL;DR
- **Вердикт:** <equity-vs-bond вывод + устойчивость Высокая/Средняя/Низкая>
- **Несущее допущение:** <одно; чей flip ломает вывод> · **Фальсификатор:** <что увидим>
- **Находка 1 (§1):** <одна строка> · **Находка 2 (§2):** <…> · **Находка 3 (§3):** <…>
- **R1-статус:** L1 внутри конуса (согласованы) / противоречие / пробел покрытия
- **Файл:** Portfolio/coherence-audits/coherence-audit-<date>.md
```

## Секции тела

### §0 — Provenance & generation-consistency
Какие артефакты, их даты и возраст, общий `snapshot_id`, вердикт согласованности поколения.
Если `degraded` — явно перечислить, у каких артефактов отсутствует `snapshot_id`.

### §1 — Cross-artifact contradiction ledger
Таблица существенных противоречий (из R1). Колонки:
`фактор | горизонт | scenario-конус [min,max] | точечные взгляды (source→value) | вне конуса / sign-conflict | ломает вывод? | severity`.
Источник — `contradiction_candidates` (`scenario_cone`, `point_views`, `points_outside_cone`,
`point_sign_conflict`). Если список пуст — писать «пробел покрытия: нет macro-chain L1/L2 или weekly
`.yaml`», а не «противоречий нет».

### §2 — Off-diagonal factor interactions
Строки `factor_overlap.rows` с `both_legs: true` (из R2). Колонки:
`фактор | equity-экспозиция | bond-экспозиция | net | direction | совместный эффект`.
`direction: reinforcing` = скрытая концентрация (обе ноги в одну сторону); `offsetting` = естественный хедж.
Беты факторов в разных единицах — межфакторное ранжирование только после домножения на масштаб сценариев
(см. SKILL.md R2), внутри фактора equity vs bond сравнимо напрямую.

### §3 — Hidden concentration / joint tail
Скрытая концентрация сверх `concentration_ratio` и совместный хвост, возникающий только при
одновременном сваливании equity- и bond-ног через общий фактор.

### §4 — Red-team вывода
Вердикт устойчивости equity-vs-bond (Высокая/Средняя/Низкая) + несущее допущение + фальсификатор.
Методы: Pre-mortem, Devil's Advocate, Reversibility.

### §5 — Что уже покрыто downstream (non-duplication)
Явные указатели: spread, per-position α, tail-flags остаются в `integrated-view@1.3` — здесь НЕ повторяются.

### §6 — Caveats
Разбить на ВЫСОКАЯ / СРЕДНЯЯ / НИЗКАЯ, с provenance-тегом источника каждого caveat.
Находки, зависящие от предупреждений в `bundle.schema_notes` (напр. weekly пришёл как `.md`, а не
`.yaml` → нет структурных катализаторов) — с пониженной уверенностью. + `review_date`.

### `predictions_for_review` (≥3)
Проверяемые следствия найденных противоречий, каждое с `check_date` (= горизонт), `auto_checkable`,
`check_what`. Формат — как в `integrated-view` §7 (тот же набор полей): `forecast-monitor`
сканирует `Portfolio/coherence-audits/coherence-audit-*.md` наравне с integrated-view (§7.4
монитора) — предсказания попадают в overdue/due-учёт и калибровочную петлю.

### «Что НЕ показано»
Указатели на первоисточники (snapshot/stress/weekly/integrated-view) для самостоятельной проверки.

## Детерминированные блоки bundle (v1.3) → куда класть

Stage P теперь предсчитывает пять доп. проверок; Fable их **интерпретирует**, не пересчитывает:

| bundle-блок | Артефакт | Что это ловит |
|---|---|---|
| `scenario_blindspots` | §1 / §3 | оси без обратного мира (ставка всегда вниз) + супер-факторы / хеджи (`locked_pairs`) |
| `mc_divergence.flagged` | §1 | два центральных значения ноги / CI не покрывает headline spread (класс §1.2) |
| `unrealizable_exposure` | §3 / §6 | blocked-позиции в выводе (distressed — сверять с вердиктом обзора облигаций `WATCH`) |
| `iis3` | §3 / §6 | дюрация-риск на льготном счёте |
| `consensus_dispersion` | §1 / §6 | сценарный конус уже/шире аналитического разброса (`stress understates/overstates dispersion`) |
| `joint_tail` (v1.4) | §3 | совместный хвост числом: ячейки сценарий×горизонт с обеими минусовыми ногами, `worst`-ячейка; ценовой слой без carry — оговаривать |
| `diachronic` (v1.4) | §0 / §1 | дифф с прошлым bundle: closed/persisting/new; persisting ≥2 прогона = систематика, не месячный шум |
| `watch_verdict` (v1.4) | TL;DR | детерминированный вердикт Stage P «оправдан ли Fable-прогон» + сигналы; в аудите цитировать, не пересчитывать |
| `contradiction_candidates[].point_confidence` (v1.4) | §1 | FCA-уверенность L1-точки — вес противоречия в severity-колонке |

## Инвариант непересчёта
Все числовые значения в артефакте — копии из bundle (который скопировал их из валидированных
артефактов). Никакое число в этом файле не должно быть выведено LLM-арифметикой.
