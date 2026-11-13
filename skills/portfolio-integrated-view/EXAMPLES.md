# portfolio-integrated-view — примеры использования

## Триггеры активации

✅ **Активирует:**
- «Сведи стресс и обзор»
- «Полная картина по портфелю»
- «Equity vs bond verdict на 20 мес»
- «Integrated view»
- «Честное сравнение акции облигации с учётом всего»
- «Что докупать с учётом всего макро и обзора»

❌ **Не активирует (использовать другой скилл):**
- «Пересчитай XIRR» → portfolio-data-loader
- «Глубокий разбор SBER» → ru-portfolio-advisor
- «Стресс на новый сценарий» → portfolio-scenario-stress
- «Построй прогноз по нефти» → forecast-confidence-applier
- «Что купить» → ru-portfolio-advisor (mode 6 ИИС-3 buy advice)

---

## Пример 1: типовой запуск (все артефакты свежие)

**Запрос:** «Сведи стресс и обзор, нужна картина 20 мес для решения equity vs bond.»

**Workflow:**
1. Транспорт B (Synology) активен.
2. Найден последний `Portfolio/snapshots/portfolio-2026-05-03.json` (age 1d).
3. Найден последний `Portfolio/stress/stress-2026-05-04-<scenario-slug>.yaml` (age 0d). <!-- illustrative example only; реальный slug читается из имени файла -->

4. Найдены последние `Portfolio/weekly-reviews/weekly-review-stock-2026-05-04.{yaml,md}` и `weekly-review-bond-2026-05-04.{yaml,md}` (age 0d).
5. Schema versions: 2.0 / 1 / 1 — OK.
6. Cross-validate: все macro_dependency резолвятся.
7. Per-position aggregation: 52 позиции.
8. Portfolio-level: equity 38% / bond 62%, spread -7.1pp.
9. Markdown-артефакт `integrated-view-2026-05-04.md` в чат.
10. Suggest: «запусти save-to-library для сохранения в `Portfolio/integrated-views/`».

---

## Пример 2: stress устарел

**Запрос:** «Полная картина по портфелю.»

**Найдено:**
- snapshot age 2d ✅
- stress age 95d ⚠ (limit 90)
- review age 3d ✅

**Output (пометка в начале):**
```
⚠ Stale check warnings:
| Артефакт | Возраст | Лимит | Severity |
|---|---|---|---|
| stress | 95d | 90d | HIGH |

Рекомендую перед integrated-view запустить:
  macro-forecast-chain → portfolio-scenario-stress

Текущий integrated-view сгенерирован, но macro-компонента может
не отражать последние изменения (рост сanctions intensity, FX move).
```

Затем — обычный output с warnings inline в Section 11 (Caveats).

---

## Пример 3: critical staleness — refuse

**Запрос:** «Сведи всё.»

**Найдено:**
- snapshot age 35d ❌ (critical >30)

**Output:**
```
❌ Critical staleness — отказываюсь от синтеза.

snapshot age 35d (critical threshold 30d).

Перед integrated-view нужно:
1. Запустить portfolio-data-loader на свежей выгрузке IntelInvest.
2. После save-to-library — повторить запрос integrated-view.

Без свежего snapshot аггрегаты будут systematically biased
(старые веса × новые stress факторы → meaningless).
```

---

## Пример 4: ИИС-3 позиция в портфеле

**Найдено:** RU000A107RH8 (corp bond) на ИИС-3, weight 0.5%.

**В Section 2 (per-position table):**
```
| ❄ RU000A107RH8 | 0.5% | +8.5% [+5;+12] | +22.3% (YTM) | -1.8% [-5;+1] | +29.0% [+22;+36] | --- | --- | HOLD-IIS |
```

**В Section 8 (ИИС-3 constraints):** отдельная таблица с maturity и YTM.

**Не делает:** не предлагает SELL/TRIM даже если total expected ниже bond average.

---

## Пример 5: HIGH-priority позиция

**Из weekly-review:** CHMF имеет `verification_priority: HIGH` и `advisor_verdict: TRIM`.

**В Section 1:**
```
| CHMF | 0.33% | TRIM | HIGH | • payout ratio FY2025<br>• capex guidance 2026-2027<br>• ROE trajectory |
```

Это первая секция после stale checks — пользователь видит сразу.

---

## Пример 6: disagreement — stress vs review

**Из stress:** OZON `expected_pct_pweighted: -2.1%` (sanctions β neg).
**Из review:** OZON `advisor_verdict: BUY`, catalyst EBITDA growth с upside +14%.

**В Section 5:**
```
| OZON | -2% (sanctions β neg) | BUY (catalyst EBITDA) | Idio dominates macro | Verify EBITDA trajectory in Q2-26 МСФО |
```

Synthesizer **не выбирает сторону** — показывает обе позиции и предлагает
конкретное действие верификации.

---

## Пример 7: catalyst с trust=IGNORE

**Из review:** OZON catalyst `EBITDA growth` источник `Invest Era`.
**Из trust matrix:** `ru-sellside.invest-era: IGNORE`.

**В joint expectation:** catalyst исключён, contribution = 0.
**В output:** виден в drill-down таблице с пометкой:
```
| EBITDA growth | Invest Era | IGNORE | --- | 0 (excluded) |
```

R5: пользователь видит полную картину, но число не подменяется тенденциозным catalyst.

---

## Пример 8: position в snapshot, нет в review

**Найдено:** в snapshot есть YDEX (5.1% веса), но advisor её не покрыл в review.

**В Section 2:** строка с `verdict: NOT REVIEWED`, `verification_priority: HIGH`.
**В Section 1:** YDEX добавляется в HIGH-priority с checklist «Запросить advisor покрытие на следующий weekly».

---

## Пример 9: --diff-with-previous (v1.1, не в v1.0)

**Запрос:** «Integrated view, покажи что изменилось с прошлого раза.»

**v1.0 ответ:** «Флаг `--diff-with-previous` запланирован в v1.1. Текущий v1.0 генерирует полный snapshot без diff.»

---

## Пример 10: пустой HIGH-priority

**Найдено:** все позиции в weekly-review имеют `verdict: HOLD`.

**Section 1:** «Все позиции в HOLD по review — HIGH-priority действий нет.»
Section 2 (per-position dashboard) идёт сразу после.

---

## Антипример: что не должен делать

**Пользователь:** «Какие облигации продать?»

**Скилл:** не активируется. Это buy/sell advice → advisor mode 4 или mode 6.

---

**Пользователь:** «Я думаю SBER переоценён, проверь.»

**Скилл:** не активируется. Это deep-dive по эмитенту → advisor mode 5.
