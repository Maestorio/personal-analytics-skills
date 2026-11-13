# portfolio-coherence-audit

Fable deep-pass (сфера 3) для портфельного пайплайна на Мосбирже. Read-only мета-слой НАД пайплайном:
держит все артефакты разом и находит то, чего fixed-schema скиллы структурно не видят.

## Зачем (ниша)

`portfolio-integrated-view` уже даёт spread, per-position α, tail-flags — по объявленным рёбрам схемы.
Он **не** ищет:

1. **Кросс-артефактные противоречия допущений** — stress, weekly-review и macro-chain могут закладывать
   разные пути одного фактора; никто их между собой не сверяет.
2. **Off-diagonal взаимодействия** — фактор, бьющий и по equity-бетам, и по bond-carry, агрегируется
   как две независимые ноги → скрытая концентрация сверх `concentration_ratio`.
3. **Red-team собственного вывода** — integrated-view по своим правилам не атакует свой equity-vs-bond
   вердикт.

Этот скилл закрывает ровно эти три пробела.

## Архитектура: две стадии

- **Stage P (Python, без LLM)** — `scripts/build_coherence_bundle.py`. Ingest 5 обязательных артефактов
  (+ опц. macro-chain), generation-consistency gate (HARD STOP при рассинхроне **даты снапшота**),
  assumption ledger, предрасчёт contradiction-candidates (точечные взгляды vs scenario-конус) и
  factor-overlap (Σβ·вес по equity- и bond-ноге отдельно) → `coherence-input-bundle-<date>.json`.
- **Stage R (Fable)** — читает ТОЛЬКО bundle + инструкции SKILL.md, делает неустранимое суждение
  (какие противоречия существенны, какие пересечения реальны, устойчив ли вывод), эмитит
  `coherence-audit-<date>.md`.

Смысл разреза: Opus/Python делают всю дешёвую механику → Fable точнее (чистый вход), дешевле (не жжёт
токены на парсинг), воспроизводимо (bundle инспектируется), с локализацией garbage-in в Stage P.

## Входы (обязательные)

| Артефакт | Файл | Схема | Окно |
|---|---|---|---|
| Снапшот | `Portfolio/snapshots/portfolio-<date>.json` | 2.0 | ≤14 дн |
| Стресс | `Portfolio/stress/stress-<date>-<slug>.yaml` | stress@2 | ≤90 дн |
| Обзор акций | `Portfolio/weekly-reviews/weekly-review-stock-<date>.yaml` | 2 | ≤14 дн |
| Обзор облигаций | `Portfolio/weekly-reviews/weekly-review-bond-<date>.yaml` | 2 | ≤14 дн |
| Синтез | `Portfolio/integrated-views/integrated-view-<date>.md` | integrated-view@1.3 | ≤14 дн |

Опциональные overlay: `macro-chain/macro-marginal-<date>.yaml`, `macro-chain/macro-scenarios-<date>.yaml`.

> **Weekly-обзоры нужны в `.yaml`** (не `.md`). Структурные `per_stock/catalyst.macro_dependency` лежат
> в паре `.yaml`; `.md` — только нарратив, скрипт его принимает, но помечает как degraded и не извлекает
> катализаторы.

**Детекция противоречий требует независимых точечных взглядов.** Сценарии стресса — это «конус» (их
разброс сам по себе не противоречие). Чтобы `contradiction_candidates` заполнился, нужен `macro-chain`
(L1/L2) и/или weekly `.yaml`. На одном стрессе получишь только factor-overlap, но не противоречия — это
не баг, а отсутствие второго мнения для сверки.

## Установка зависимостей

```bash
pip install pyyaml --break-system-packages
```

## Запуск Stage P вручную

```bash
python3 skills/portfolio-coherence-audit/scripts/build_coherence_bundle.py \
  --dir "<Claude-Memory root>" --asof <YYYY-MM-DD>
```

Коды выхода: `0` готово · `2` HARD STOP (не запускать Fable) · `3` ошибка IO/usage.

## Дефолты, которые можно менять (см. SPEC §9)

- **Имя:** `portfolio-coherence-audit`.
- **Сохранение:** A2 — прямая запись в `Portfolio/coherence-audits/` (save-to-library не трогаем).
- **Каденс:** ежемесячно + на смене режима.
- **Скоуп red-team:** equity-vs-bond вывод.

## Схемы: проверено против реальных артефактов (2026-07-02/03)

v1.1 — пути полей больше не «по предположению»; сверены с настоящими файлами. Фактически читаются:

- **Факторы** — из `stress.factor_definitions` (не хардкод): `sanctions, geopol, cbr_rate, usdrub,
  cnyrub, brent, xauusd`. Горизонты `h6/h12/h24`.
- **Off-diagonal** — из `stress.per_position.<ticker>.factor_betas` × `weight_pct`, раздельно по
  equity/bond. Облигации в `per_position` **тоже имеют `factor_betas`** — поэтому bond-нога считается
  честно (не только carry). Класс актива — `snapshot.holdings[].asset_type` (bond если тикер есть в
  `stress.bond_carry.per_position`).
- **Consistency** — дата снапшота из `snapshot.as_of_date` / `stress.portfolio_snapshot_id` /
  `weekly.snapshot_id` / `integrated_view.inputs.snapshot_date` (у integrated-view нет top-level
  `snapshot_id` — ссылка в `inputs`).
- **Единицы бет различаются** между факторами (`cbr_rate` — п.п., `usdrub` — %, `sanctions/geopol` —
  шкала −1…+1). Внутри фактора equity vs bond сравнимо; межфакторное ранжирование — только после
  домножения на масштаб сценария (это делает Stage R/Fable, не скрипт).

Любые правки полей — в одном месте (методы `Prep.*`); предположения и ограничения прогона всегда
дублируются в `bundle.schema_notes`.

## Что показал прогон на реальном портфеле

На выровненном поколении (30 акций + 40 облигаций) `dominant_factor: usdrub`, а factor-overlap выявил
**усиливающую** концентрацию по обеим ногам сразу: `sanctions`, `geopol`, `cbr_rate`, `usdrub`, `cnyrub`
двигают и акции, и облигации в одну сторону. Спред «акции−облигации» это маскирует — то есть
«облигации диверсифицируют акции» частично иллюзорно против доминирующих факторов. Ровно та находка,
которой нет в `integrated-view@1.3`.

## Проверки v1.3 (детерминированные, в Stage P)

Чем больше ловится числами — тем меньше зависит от «додумает ли модель». Добавлены:

1. **scenario_blindspots** — оси без обратного мира (`one_sided_factors`, напр. ставка всегда вниз →
   нет мира «пауза ЦБ») + `locked_pairs` (супер-факторы / встроенные хеджи).
2. **mc_divergence** — два центральных значения ноги в integrated-view и CI, не покрывающий headline,
   от которого считался spread (на реальных данных bond флагнут на всех горизонтах).
3. **unrealizable_exposure** — blocked-позиции, чей вклад в вывод может быть нереализуем.
4. **iis3** — состав ИИС-3 и дюрация-риск на льготном счёте.
5. **consensus_dispersion** (`--forecasts-dir`) — ширина сценарного конуса vs аналитический разброс из
   `forecasts/*.yaml`; флаг `stress understates/overstates dispersion`. Берёт только те forecast-файлы,
   что это поколение использовало (`macro-marginal.factors.*.source_file`).

`--forecasts-dir` авто-выводится как `<--dir>/forecasts`. Всё это — предсчёт; Fable интерпретирует
существенность, не пересчитывает.

## Проверки v1.4 (расширение 2026-07)

6. **joint_tail** — совместный хвост числом: взвешенные ценовые дельты ног по ячейкам
   сценарий×горизонт из `stress.per_position.*.by_horizon.*.delta_pct_by_scenario`; ячейки, где
   обе ноги минусовые одновременно (`worst` — худшая по combined). Carry не включён — это
   консервативный ценовой хвост; на старом stress без Phase 4 блок пуст с note.
7. **diachronic** — дифф с прошлым bundle (авто-поиск рядом с `--out`, либо `--prev-bundle`):
   closed/persisting/new по противоречиям, one-sided осям, mc-флагам, reinforcing-пересечениям,
   consensus-флагам. Persisting ≥2 прогона = систематика.
8. **watch_verdict** — детерминированный гейт дорогого прогона: `fable_recommended` + `signals`
   (первый прогон = baseline; дальше — только НОВОЕ против прошлого bundle). Stage P запускает
   любая дешёвая сессия; Fable — только по сигналу или календарному решению пользователя.
9. **point_confidence** — FCA-уверенность L1-точек в `contradiction_candidates` (trust-контекст:
   противоречие от точки с confidence 0.8 весит больше, чем от 0.4).

Петля предсказаний замкнута: `forecast-monitor` §7.4 сканирует
`Portfolio/coherence-audits/coherence-audit-*.md` (блок `predictions_for_review`, формат §7
integrated-view) — overdue/due-учёт и калибровка работают и для этого скилла.

Тесты: `tests/test_build_coherence_bundle.py` (120 проверок, требует PyYAML).

## Границы

Только анализ. Никаких buy/sell, никакого пересчёта чисел, read-only. Не дублирует integrated-view.
