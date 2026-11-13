# Skill: portfolio-integrated-view

> **Статус ревью (2026-05-10):** P1 boundary-leak (§1 action items) закрыт через A5; missing-metadata определён как галлюцинация; minor §3 YAML-имена и P2-косметика — в `docs/investment/TODO.md`. Контракт upstream weekly-review обновлён под Phase 10.4 split.

## Summary
Самый аккуратный из «без скриптов» скиллов: 18+ численных расчётов задокументированы (formulas видимые), CI propagation двойной (консервативный + квадратурный), bond carry с асимметричным CI. Главная неаккуратность — нарушение read-only границы в §1–§2 свежего артефакта v3: action-items с лимитными заявками и quick-verdict с conditional advice проникают в текст несмотря на правило в `SKILL.md:57–58`. Также у `next_check_date` для 20-месячного контура нет metadata-якоря для forecast-monitor.

## Correctness (P1)
- ✅ **ЗАКРЫТО (A5).** [boundary-leak] §1 «HIGH-priority действия» в `Portfolio/integrated-views/integrated-view-2026-05-07.md` содержит формулировки типа «RENI — BUY ⚠ | лимитная заявка +80 шт. ≤1280 ₽». Хотя они помечены «из обзора», структурно это действие, а не количественный синтез. `SKILL.md:57–58` запрещает действия в integrated-view.
  - Эффект: дублирование роли advisor; downstream (пользователь) теряет шанс заметить, что ru-portfolio-advisor рекомендации могли устареть, читая интегрированный view как самостоятельный action-list.
  - Fix sketch: в §1 оставить только количественные сравнения «ожидание vs benchmark», действия — отдельный pointer на advisor-output без копирования вердикта.
  - **Реализовано:** §1 переопределён как «HIGH-priority позиции (verdict-pointers + verification)», семантика колонок 2 (verdict-pointer) и 4 (verification check) уточнена. Rule 6 (`SKILL.md:88–95`) теперь явно запрещает копирование action items, ценовых уровней и размеров лотов. Структура колонок (5) сохранена для совместимости с viewer'ом. `references/output-template.md` обновлён.
- 🌀 **ГАЛЛЮЦИНАЦИЯ.** [missing-metadata] Артефакт не несёт `next_check_date` для retro-audit 20-месячных прогнозов (Шаг R7 в `predictions-for-review-spec.md`). 11 прогнозов в §7 имеют `target_date`, но нет агрегированного поля в frontmatter — forecast-monitor и retrospective-forecast-audit его не подхватят.
  - Эффект: автоматическое напоминание «время аудитировать integrated-view от 2026-05-07» не сработает — нужна ручная пометка.
  - Fix sketch: добавить во frontmatter `forecasts_for_review.due_min_date: <view_date + 20 mo>` и список IDs.
  - **Уточнение после верификации:** `check_date` есть **внутри блока** `predictions_for_review` для каждого прогноза индивидуально (см. `SKILL.md:264–265` в acceptance checklist). retrospective-forecast-audit и forecast-monitor читают check_date по позициям, не по top-level frontmatter. Агрегированное поле во frontmatter не требуется по архитектуре.
- 📋 **В TODO (PIV-1).** [minor-bug] §3 в артефакте использует точные YAML-имена (`per_instrument_xirr.T = null`, `ytm_pct = null`), хотя `SKILL.md:97–99` запрещает выдачу YAML-полей в текст.
  - Эффект: косметика, читателю с YAML-фоном понятно, без — нет.

## Readability (P2)
- 📋 **В TODO (PIV-2).** 3-tier структура (Action / Analysis / Methodology) действительно облегчает чтение — но HTML-комментарии `<!-- collapsible -->` для дальнейшего viewer'а не вставлены, хотя в SKILL.md обещаны.
- 18+ расчётов — все формулы прямо в тексте артефакта (intermediate σ, normalization, p_joint). Это образцово.
- 📋 **В TODO (PIV-3).** Глоссарий (§9) частично выполняет роль перевода YAML→человеческий, но дублируется в нескольких местах.

## Cost (P3)
- Opus 4.7 mandatory — обосновано: multi-source aggregation требует калибровки CI, которые Sonnet занижает. ~12¢/запуск, частота — раз в 2 недели.
- Артефакт ~43 KB — приемлемо для read-only документа.

## Speed (P4)
- Линейный синтез поверх трёх артефактов (snapshot, stress, weekly-review). Никакой параллелизации не требуется; bottleneck — quality of synthesis у LLM, не скорость.

## Cross-skill / contract
- D3 OK: артефакт в чат → save-to-library пишет в `Portfolio/integrated-views/`. Свежий файл присутствует.
- Upstream contract:
  - `portfolio-data-loader/portfolio-{date}.json` — через snapshot ✓
  - `portfolio-scenario-stress/stress-*.yaml` — но в синтезаторе ожидаются поля `expected_pl_rub`, `top_risks`, `macro_blindspots`. Реальный артефакт всё содержит ✓
  - `ru-portfolio-advisor/weekly-review-*.yaml` — но `Portfolio/weekly-reviews/` ПУСТО. Откуда v3 взял per_stock-данные?
- ✅ **ЗАКРЫТО (A7).** [contract-violation] На фоне пустой `Portfolio/weekly-reviews/`, артефакт integrated-view содержит детализированные per_stock секции (RENI, OZON, SBER, MDMG …). Источник неясен — либо weekly-review существовал и был удалён, либо синтезатор в обход опирался на чат-context, что нарушает read-only-from-files принцип.
  - **Уточнение после верификации:** `ru-portfolio-advisor` Phase 10.4 ввёл split на `weekly-review-stock-{date}.yaml` + `weekly-review-bond-{date}.yaml` (с парными MD), и старый формат `weekly-review-{date}.yaml` стал legacy. На момент ревью `portfolio-integrated-view/SKILL.md:33` всё ещё ожидал старое имя — это и есть причина «пустоты» в восприятии. Контракт upstream обновлён в `SKILL.md`, `references/synthesizer-workflow.md`, `references/output-template.md`, `EXAMPLES.md` под новую схему (stock + bond YAML + парные MD).
- forecast-monitor staleness contract — пороги (snapshot ≤14d, stress ≤90d, review ≤14d) явно прописаны и проверяются в §0 артефакта ✓.

## Verified against artifact
- `~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/Portfolio/integrated-views/integrated-view-2026-05-07.md` (v3):
  - §0 Staleness check: snapshot 2d, stress 1d, review 1d — все FRESH ✓
  - §3 Per-position table: 23 позиции, все с формулами, корректные теги (🟢/🔴/👁/⚠/🔒) ✓
  - §4 Equity vs bond spread: точечно −8.4 pp, конс. CI [−29.5; +16.2], реал. CI [−25.1; +8.3], σ_eq ≈ 7.20, σ_bond ≈ 4.24, σ_spread ≈ 8.36 — все промежуточные числа выписаны ✓
  - §4 Bond carry асимметричный CI: 9.83% × 20/12 = 16.4%, CI [+12.4; +18.8] (нижняя граница расширена на 1.5 пп под Sc-D_base) ✓
  - §7 Predictions for review: 11 записей, 4 категории (portfolio_aggregate, position_dividend, catalyst_fired, scenario_realized), `target_date: 2028-01-07` ✓
  - §1 Action items: лимитные заявки, рекомендации — присутствуют ✗ (boundary-leak)
  - §6 ИИС-3: акций нет, R10 не применяется, облигации перечислены — корректно ✓
- `Portfolio/weekly-reviews/`: ПУСТО. Артефакт ссылается на `weekly-review-2026-05-06.yaml`, но файл отсутствует в Synology — расследовать (см. cross-skill).
