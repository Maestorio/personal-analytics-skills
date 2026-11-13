# portfolio-integrated-view — TODO

**Этот файл живёт внутри скилла** (`/skills/portfolio-integrated-view/TODO.md`).
**Назначение:** roadmap для улучшений за пределами v1. Не читается ни consumers, ни producers — только ориентир для разработки.

---

## v1 — что уже сделано

См. `SKILL.md` v1.0. Покрыто:
- R1 (confidence intervals)
- R2 (catalyst sources required)
- R4 partial (macro_dependency, simplified joint expectation)
- R5 (cognitive substitution mitigation)
- R6 (schema versioning + fail-fast)
- R7 (predictions_for_review block)
- R10 (ИИС-3 constraints)

Намеренно НЕ покрыто в v1:
- R3 (multiple horizons) — частично через 20mo lock
- R4 full covariance
- R8 concurrency safety
- R9 calibrated catalyst quality scoring

---

## v1.1 — small improvements (1-2 недели)

### v1.1-A: Diff с предыдущим integrated-view

**Цель:** показать, что изменилось с прошлой генерации. Помогает не перечитывать всё каждый раз.

**Acceptance:**
- [ ] Флаг `--diff-with-previous` находит `INTEGRATED-VIEW-{previous_date}.md` в библиотеке
- [ ] Сравнивает per-position table; помечает строки `+/=/-`
- [ ] Section «Что изменилось» добавляется в начало (после stale checks)
- [ ] Diff включает: новые HIGH-priority позиции, изменения в verdict, изменения в total_pct >5pp

### v1.1-B: Auto-checking catalyst dates через forecast-monitor

**Цель:** интеграция с `forecast-monitor` для tracking сработал ли catalyst.

**Acceptance:**
- [ ] Catalyst events с `auto_checkable: true` field автоматически submission в forecast-monitor
- [ ] Через 6 мес — automated check какие catalysts fired
- [ ] Это feeds R7 retrospective audit

### v1.1-C: Concurrency safety (R8)

**Цель:** предотвратить race conditions при параллельных runs.

**Acceptance:**
- [ ] Lockfile в `Portfolio-Stress/.lock` и `Weekly-Reviews/.lock`
- [ ] Atomic INDEX.md update (write to .tmp, then rename)
- [ ] Clear error message если lock conflict

### v1.1-D: Sanity checks для extreme values

**Цель:** alert когда synthesizer выдаёт implausible numbers (бug или corrupt data).

**Acceptance:**
- [ ] Если total_expected_pct > 100% или < -100% → warning HIGH
- [ ] Если CI width > 100pp → warning HIGH
- [ ] Если weight_pct sum != 100% → warning HIGH
- [ ] Этот checklist runs до output generation

---

## v2 — methodology upgrades (1-2 месяца)

### v2-A: Multiple horizons (R3)

**Цель:** показывать предсказания на 12mo / 20mo / 36mo одновременно.

**Spec:**
- weekly-review schema v2 поддерживает `horizons: [12, 20, 36]` array
- stress schema v2 supports multiple horizon factor effects
- integrated-view shows three columns side-by-side
- Honest comparison: short bond vs short equity, long bond vs long equity

**Why important:**
- IE-портфель — long horizon (3-5 yr)
- Сравнение на 20mo systematically biased в сторону bonds (mechanical rate cycle)
- 36mo horizon показывает другую картину

**Acceptance:**
- [ ] User может задать `--horizon=12` / `--horizon=36` / `--all-horizons`
- [ ] Per-position table имеет 3 колонки expected_pct (одна на каждый horizon)
- [ ] Equity vs bond comparison делается per-horizon
- [ ] Каждый horizon имеет свой `predictions_for_review` block

### v2-B: Full covariance modeling (R4)

**Цель:** точная joint expectation учитывая корреляции между catalysts.

**Spec:**
- catalyst может иметь множественные dependencies: `macro_dependencies: [Sc-D_base, Sc-A_bull]`
- corr_matrix между catalysts оценивается из historical data
- Monte Carlo simulation для CI propagation (10,000 paths)

**Acceptance:**
- [ ] joint expected учитывает correlations между catalysts within position
- [ ] CI propagation через Monte Carlo, не аналитически
- [ ] Per-position correlations с macro factors сохраняются в weekly-review

### v2-C: Backtested catalyst.p calibration (R7 maturation)

**Цель:** через 6+ мес работы — калибровать P(catalyst fires) на realized data.

**Spec:**
- retrospective-forecast-audit запускается на накопленных predictions_for_review
- Результат — calibration curve P(realized | predicted)
- Calibration applied как multiplicative factor в synthesizer

**Acceptance:**
- [ ] Минимум 30 catalyst predictions resolved (выпало realised / not realised)
- [ ] Brier score / log loss computed
- [ ] Если systematic over/underconfidence — apply correction factor
- [ ] Calibration report в Claude-Memory/calibration/

### v2-D: Per-sector catalyst quality calibration (R9)

**Цель:** разные секторы имеют разную quality of catalyst predictions.

**Spec:**
- catalyst.source_quality scoring per sector (banks vs pharma vs tech)
- Backtest catalyst hit rate per sector
- Apply sector-specific discount factors

**Acceptance:**
- [ ] R7 audit segmented по секторам
- [ ] Different discount factors persisted в `references/sector-calibration.yaml`
- [ ] Synthesizer applies discount based on sector

---

## v3 — UX & visualization (2-3 месяца)

### v3-A: Interactive HTML dashboard with full features

**Цель:** беспощадно good UX в браузере.

**Spec:**
- См. `06-portfolio-integrated-viewer-HTML-spec.md` для базовой версии
- v3 расширяет: drill-down per position, history view, export to PDF

**Acceptance:**
- [ ] Per-position click → modal с всем контекстом (catalysts, sources, sector, IE-data)
- [ ] History toggle — line chart как expected_pct менялся во времени
- [ ] Export current view as PDF report
- [ ] Mobile-responsive

### v3-B: Notifications & alerts

**Цель:** проактивно уведомлять о важных изменениях.

**Spec:**
- Подписка на конкретные positions (e.g. SBER, T)
- Алерт когда verdict меняется
- Алерт когда CI расходится сильно (uncertainty grew)
- Email / Telegram delivery

**Acceptance:**
- [ ] Subscription configurable
- [ ] Alerts отправляются после каждого integrated-view run
- [ ] Не больше 1 алерта/неделя на позицию

### v3-C: Comparison mode

**Цель:** сравнить разные portfolio compositions.

**Spec:**
- Hypothetical: «что если переложить 5% из SBER в RENI»
- Synthesizer пересчитывает aggregates на гипотетическом портфеле
- Side-by-side comparison

**Acceptance:**
- [ ] User может задать hypothetical re-allocations
- [ ] Output: «Δ expected return», «Δ volatility», «Δ sector concentration»
- [ ] Honest CI comparison (не выглядит лучше чем есть)

---

## v4 — Beyond v3 (long term)

### v4-A: Multi-portfolio support

Если у пользователя появляется больше портфелей (брокер 2, ИИС у супруги, etc.) — synthesizer работает с каждым.

### v4-B: Real-time data integration

Integration с MOEX ISS для live prices в integrated-view (а не на момент snapshot).

### v4-C: ML-augmented catalyst generation

Train на historical sell-side reports для automated catalyst tree generation. Это в идеале не replaces advisor, а augments его.

### v4-D: Portfolio optimization layer

Honestly: **not v1-v3.** Optimization — это совсем другой класс tools (`scipy.optimize`, mean-variance, robust optimization). Это decoupled от integrated-view, но может consume его outputs.

---

## TODO not assigned to specific version

### Documentation

- [ ] FAQ.md в скилле для пользователей
- [ ] EXAMPLES.md с реальными use cases
- [ ] CHANGELOG.md между версиями

### Testing

- [ ] Unit tests для synthesize.py
- [ ] Integration tests на synthetic snapshot + stress + review
- [ ] Regression tests на исторических данных

### Performance

- [ ] Profile synthesizer на больших портфелях (1000+ positions)
- [ ] Cache trust matrix between runs
- [ ] Parallel computation для per_position aggregates

### Robustness

- [ ] Graceful handling stale data scenarios (refuse vs degrade)
- [ ] Network failure handling (Synology vs gdrive failover)
- [ ] Schema v2 migration tools (auto-convert if possible)

---

## Декомпозиция risks которые ещё не закрыты

| Risk | Status | Plan |
|---|---|---|
| R3 (horizon mismatch) | Partial (v1: 20mo lock) | Full в v2-A |
| R4 (correlations) | Partial (v1: macro_dependency) | Full в v2-B |
| R7 (validation loop) | Initiated (v1: predictions_for_review) | Maturation в v2-C через retrospective audit |
| R8 (concurrency) | Not addressed (v1) | v1.1-C |
| R9 (catalyst quality) | Partial (v1: source_quality flag) | Full в v2-D |

---

## Принципы разработки

1. **Никогда не add features которые повышают phantom precision.** Если новая feature даёт «уверенный single number» там, где есть real uncertainty — не делать.
2. **Всегда сохранять CI propagation.** Любой новый pathway вычислений должен propagate uncertainty.
3. **Schema breaking changes — только при bump major version.** v1.x → v2.0, не silent.
4. **Backward compatibility 1 major version.** v2.x consumers должен auto-convert v1.x inputs если возможно.
5. **Каждое поле в YAML schema должно иметь reason for existence.** Не storage of «just in case» данных.
6. **No recommendations creep.** Если кто-то предлагает добавить «buy/sell suggestion» — refuse. Это другой product.
7. **User in the loop.** Никогда не automate действия без user confirmation.
