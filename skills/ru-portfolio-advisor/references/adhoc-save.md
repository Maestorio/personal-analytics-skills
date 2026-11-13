# Ad-hoc save: свободный отчёт в Portfolio/reports/

> Вынесено из SKILL.md дословно при дроблении 2026-08-12 (этап 3, подготовка Max → Pro).

### Ad-hoc save: сохранение свободного отчёта в `Portfolio/reports/`

Для режимов **3 / 4 / 5 / 6 / 7 / 8** (Rebalance, Single Analysis, Fund, Returns, ИИС-3 Buy, Quality Review)
и любых *свободных запросов* (custom analysis, scenario thinking, retrospective, plan,
education content) — НЕ генерируй weekly-review YAML. Вместо этого сохраняй
**один markdown-файл** в `Claude-Memory/Portfolio/reports/`.

**Триггеры активации:**
- Явные: «сохрани отчёт», «сохрани как заметку», «сделай отчёт для памяти», «save this», «put in reports».
- НЕ активируй при триггерах weekly review (см. предыдущий раздел) — там свой save-flow.

**Имя файла:** `Portfolio/reports/{YYYY-MM-DD}-{kind-slug}-{short-topic-slug}.md`,
например `2026-05-13-bond-bridge-planner-domrf-ofz.md`.

**Шапка `report@1`** (проверка — блокирующая `validate-report` при сохранении):

```yaml
---
title: "Разбор GMKN после отчёта 3К"
date: "2026-10-29"
kind: "single_analysis"       # кодлист report_kind, см. таблицу ниже
mode_codes: ["4a", "3"]       # коды режимов, главный первым (4a — акция, 4b — облигация, 5a/5b — фонды, 7 — ИИС-3, 8 — оценка качества)
mode: "4 (single)"            # для глаз; ИИС-3 Buy Advice — "7 (iis3 buy)"
tickers: ["GMKN"]             # ключи бумаг (тикер или ISIN); [] — у макро/education
summary: "Тезис жив, докупка после дивидендной политики"
author: "ru-portfolio-advisor"
model: "claude-opus-5"
related_artifacts: ["Portfolio/snapshots/portfolio-2026-10-28.json"]
horizon_months: 12            # null — без горизонта
decisions:                    # режимы 3 / 4 / 5a / 8: по записи на бумагу с выводом (output-templates.md §«Решение по бумаге»)
  - key: GMKN
    verdict: HOLD
    target_pct: null
    review_by: "2026-12-15"
    note: "отчёт 3К подтвердил тезис"
---
```

`schema_version: report@1` и `recorded_at` (время записи, МСК) модель не пишет — их ставит скрипт при сохранении
(`assemble_artifact.py stamp-report`). Новые условия по бумаге (Режим 9) отчёт перечисляет в тексте с полями входа
`apply_condition.py add`; создаёт их save-to-library при сохранении.

**Допустимые значения `kind`** (кодлист `report_kind`):

| kind | Когда |
|---|---|
| `single_analysis` | Разбор одной бумаги (режим 4, 5a) |
| `tactical_rebalance` | Ребалансировка, тактический ход по событию (режим 3) |
| `quality_review` | Оценка качества акций на 1–2 года (режим 8) |
| `iis_buy` | Докупка на ИИС-3 (режим 7) |
| `fund_selection` | Подбор фонда (режим 5b) |
| `bond_bridge_planner` | Стратегия bond → equity перекладывание |
| `candidates_outside_ie` | Кандидаты вне IE-модели |
| `scenario_analysis` | Глубокий разбор одного сценария |
| `tax_optimization` | ИИС-3, tax-loss harvesting и т.п. |
| `retro_calibration` | Самоаудит советов advisor'а |
| `general` | Свободный (default) |

**Структура тела (markdown):**

```markdown
# {Title — повтор для viewer fallback}

**TL;DR:** {summary expanded — 2-3 строки}

## Контекст
{что обсуждали, какой prompt, на каких данных}

## Анализ
{основной контент — таблицы, прозой, расчёты}

## Выводы / Action items
{что выносим из этого репорта; checklist OK}

## Источники
{URL, related artifacts, даты доступа}
```

**Сохранение:**

Файл отчёта — в рабочей папке сессии, показанный пользователю; в библиотеку сам не записывай (правило D3).
Запись — «сохрани отчёт» → save-to-library Workflow N: файл отчёта → `stamp-report` (время записи и версия схемы) →
`validate-report` → новые условия (`apply_condition.py add`) → файлы решений (`decision_write.py from-report
--created …`). Гейт по бумаге после этого считается из нового решения.

**Viewer-интеграция:**

`tools/portfolio-integrated-viewer.html` (v1.3+) автоматически подхватывает все
`*.md` из `Portfolio/reports/` и показывает кнопкой `📄 Reports (N)` в header.
Клик → modal со списком (по `title`/`date`/`kind`/`author`/`summary`) →
клик на пункт → modal с rendered markdown.

