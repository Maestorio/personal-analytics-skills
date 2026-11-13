# Mode Selection Template (Шаг 3.5)

Шаблон для представления выбора режима пользователю. Используется после показа Coverage Report — когда режим неизвестен и требуется решение пользователя.

## Формат промпта

```
━━━ Выбор режима ━━━
Статус: {N} FRESH | {L} STALE | {M} MISSING | {K} critical

  [FULL]          — полный пайплайн (~2–3 ч): запустить все MISSING/STALE
                    прогнозы через FCA/scenario-builder → consistency → matrix.
  [QUICK-REFRESH] — пересобрать только устаревшие (~20 мин); MISSING → caveats.
  [PARTIAL]       — matrix из имеющегося прямо сейчас (~10–15 мин, без FCA);
                    все MISSING/STALE → явные caveats.

Рекомендация: [{режим}] — {одна строка объяснения на основе Coverage Report выше}
```

## Переменные

- `{N}` — количество FRESH факторов
- `{L}` — количество STALE факторов
- `{M}` — количество MISSING факторов
- `{K}` — количество critical issues
- `{режим}` — автоматическая рекомендация скрипта (FULL | QUICK-REFRESH | PARTIAL)

## Автоматическая рекомендация (режим + причина)

Таблица правил из `scripts/coverage_report.py` output:

| Условие | Рекомендация |
|---------|-------------|
| 0 MISSING + 0 STALE + 0 critical | **PARTIAL** — всё FRESH, просто собрать матрицу |
| 0 MISSING + 1–3 STALE + 0 critical | **QUICK-REFRESH** — пересобрать протухшие, остальное свежее |
| ≥1 MISSING ИЛИ ≥4 STALE ИЛИ ≥1 critical | **FULL** — существенные пробелы, полный пайплайн необходим |
| ≥1 прогноз на заменённой матрице (`matrix_replaced` в выводе скрипта) | **FULL** — пересобрать эти прогнозы на действующей матрице; RECALIBRATE и сборку «как есть» не предлагать |

**Жёсткое правило:** если `{K} ≥ 1` (critical = `BROKEN` у требуемого фактора; файла флагов
устаревания нет) — рекомендация QUICK-REFRESH **запрещена**.
Допустимы FULL или PARTIAL (PARTIAL только когда все остальные факторы
FRESH/AGING, и пересобирается только critical-фактор). Скрипт `coverage_report.py`
сам не выдаст QUICK-REFRESH при `critical_list != []`, но если пользователь
выбрал режим вручную — отказать с пояснением.

Скрипт также возвращает поле `mode_recommendation: {mode, reason, missing_list, stale_list, critical_list}` для формирования последней строки с объяснением.

## Пример

```
━━━ Выбор режима ━━━
Статус: 5 FRESH | 2 STALE | 0 MISSING | 0 critical

  [FULL]          — полный пайплайн (~2–3 ч): запустить все MISSING/STALE
                    прогнозы через FCA/scenario-builder → consistency → matrix.
  [QUICK-REFRESH] — пересобрать только устаревшие (~20 мин); MISSING → caveats.
  [PARTIAL]       — matrix из имеющегося прямо сейчас (~10–15 мин, без FCA);
                    все MISSING/STALE → явные caveats.

Рекомендация: [QUICK-REFRESH] — urals_discount и budget_deficit слегка устарели (>28d),
остальные факторы свежие. Пересобрать их быстро, остальное оставить как есть.
```

## Когда использовать

- После Шага 3 (Coverage Report), если пользователь не назвал режим явно в Шаге 0
- Не показывать, если режим уже зафиксирован (перейти прямо к Шагу 4)
- В режиме PARTIAL Шаг 4 пропускается — сразу к Шагу 8
