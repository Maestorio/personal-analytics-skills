# portfolio-data-loader — обновления 2026-10-20…21

Сводка правок загрузчика по итогам разбора обзоров 16.10 и аудита обзоров 01.10–16.10
(`docs/investment/TODO.md#wr-1016`, отчёт аудита — `portfolio/weekly-reviews-audit-2026-10-20.md`).
Методика расчёта (XIRR/TWR, реконструкция позиций, сплиты) **не менялась** — заморозка до
2027-04-07 её не касается, все правки — исправления багов, контроль данных и инструменты.

**Перепаковать и загрузить в claude.ai:** `portfolio-data-loader` (а также `ru-portfolio-advisor`,
`save-to-library` — они затронуты той же волной).

---

## 1. `moex_quotes.py --from-portfolio` читает снапшот v2 — RPA-22 (`4f0447a`)

Файл — канон `_shared-references/moex_quotes.py`, в бандл загрузчика и советника его кладёт
`bundle_scripts`.

- **Было:** `secids_from_portfolio` понимал только промежуточный `portfolio.json`
  (`stocks`/`bonds`/`other_positions`). На снапшоте v2 (`holdings`) список бумаг был пуст,
  скрипт печатал справку и выходил с кодом 2 — в каждом обзоре режимов 1/2, после чего модель
  писала свои скрипты свечей.
- **Стало:** при наличии `holdings` — активные позиции, `blocked` мимо; акции и фонды по тикеру,
  облигации по ISIN. Старый формат сохранён: его читает `per_security_xirr.py`.
- Тест: `skills/portfolio-data-loader/tests/test_quote_overrides.py` (+2, всего 8).
- Ожидаемая ошибка на живых данных — только FINAMAR (внебиржевой ПИФ, цены MOEX нет).

## 2. Версии снапшота дня — PDL-SNAPV (`bb3a672`)

- **Проблема:** 16.10 `portfolio-2026-10-16.json` пересобран в 18:21 под тем же именем после
  выхода обзоров. Обзоры перестали воспроизводиться по `snapshot_id`, стаб акций на новой
  версии дал несогласованные веса (блок валидатора по CNRU), база и кэш обзора облигаций
  «разошлись» со снапшотом (инциденты `inc-2026-10-20-4`, `-10`).
- **Решение:** новый `scripts/archive_snapshot.py`. Шаг 7 SKILL.md — перед Write нового снапшота:
  ```bash
  python3 scripts/archive_snapshot.py --snapshots-dir "{MEMORY_ROOT}/Portfolio/snapshots" --date {YYYY-MM-DD}
  ```
  Прежняя версия копируется в `Portfolio/snapshots/.versions/portfolio-{date}.{generated_at}.json`.
  Имя основного файла не меняется (на шаблон `portfolio-YYYY-MM-DD.json` завязаны вьюер,
  советник, стресс, журнал решений, notifier). Скрипт ничего не удаляет; та же версия
  повторно — пропуск. В подтверждении в чате — строка о перезаписи и времени прежней версии.
- Проверено: вьюер (`tools/assets/viewer.js`) и notifier читают папку без рекурсии —
  `.versions/` в списки снапшотов не попадает.
- Тест: `tests/test_archive_snapshot.py` (5 проверок).
- Поле `snapshot_generated_at` в обзоры не заводили (схема weekly-review): версия находится по
  времени обзора.

## 3. Сверка количества облигаций со сделками — PDL-RECON (`b5fb552`)

- **Проблема:** сверка `reconciliation.balance_vs_trades` покрывает только акции и фонды.
  НорНик1P17 (`RU000A10FC62`) три недели шёл в обзоры с количеством 24 при 34 по сделкам и
  стоимости на 34 шт — без флага.
- **Решение:** `assemble_snapshot._build_bond_qty_vs_trades` → блок
  `reconciliation.bond_qty_vs_trades` и флаг `bond_qty_vs_trades_mismatch` (**warning**).
  Основной счёт, `holdings[].qty` против `per_instrument_xirr[*].qty_now` по ISIN; дубль бумаги
  под SU-ключом и ISIN не суммируется; бумага на двух счетах (ОФЗ 26238: 80 + 130 на ИИС-3)
  сверяется и с суммой; бумаги без сделок основного счёта не сверяются.
- Проверено на снапшотах 01, 08, 13, 16.10: ловит только FC62.
- Схема — `references/output-schema.md`, раздел `reconciliation.bond_qty_vs_trades`.
- Тест: `tests/test_balance_reconciliation.py` (+2).
- Причина у FC62 — данные: 24 шт на доске TQCB (расчёты в рублях) и 10 шт на TQOY (в юанях),
  один ISIN; в «Облигациях» Numbers держать **одной строкой, 34 шт** (две строки с одним ISIN
  столкнутся в `per_bond` обзора — ключ ISIN).

## 4. Расследование расхождений данных — PDL-RECON (без правок кода)

| Расхождение | Причина | Что сделано |
|---|---|---|
| USD-корзина `bonds_plan_vs_fact` больше USD-облигаций на 151–170 тыс ₽, девять недель | Фонд TLCB («USD - Облигации») законно входит в `actual_rub` корзины (`_build_bonds_plan_vs_fact`); 16.10: 6 097 203 − 5 596 803 = 500 400 ≈ TLCB 499 950 | Подпись в `ru-portfolio-advisor/references/bonds-methodology.md` (`dea2974`) — не разрыв |
| База и кэш обзора облигаций 16.10 ≠ снапшоту | Перезапись снапшота после обзора | §2 |
| Кэш-дрейф +169 тыс ₽ (13→16.10) | Двойное погашение Борца 18.09 в IntelInvest (фантомные 1,992 шт / 505 038 ₽), затем автокорректировка IntelInvest −550 530 ₽ от 01.10 при импорте отчёта за 01–13.10; продажа ЭталонФин5 от 28.09, внесённая задним числом; дубли TPAY 08.10 и ПГК3Р02 09.10 | 21.10 владелец удалил фантом и дубли; корректировка сжалась до −25 713 ₽ (остаток неотражённых операций, кандидат — НДФЛ, не проверено). **Следующий снапшот — с `--rebaseline-cash`** |
| «Грязный» `cash_rub` main выше ликвидного на ≈150 тыс ₽ | FINAMAR 449 999,97 (внебиржевой ПИФ) | Норма данных |
| `weight_real_pct` акций | Это доля акционной книги (`ie_actual.real_share_pct`, «Доля Реальная»), не портфеля | Комментарий в `build_weekly_stock_stub.py` |

Продажа ЭталонФин5 внесена задним числом — инцидент `inc-2026-10-21-1`; урок для пользователя —
в `tools/viewer-help.md` («вноси сделку в день исполнения»).

## 5. Документация, обновлённая вместе с кодом

- `skills/portfolio-data-loader/SKILL.md` — Шаг 7: `archive_snapshot.py` перед записью.
- `skills/portfolio-data-loader/references/output-schema.md` — `reconciliation.bond_qty_vs_trades`.
- `_shared-references/claude-memory-layout.md` — `Portfolio/snapshots/.versions/`.
- `docs/investment/portfolio-workflow-guide.md` и `tools/viewer-help.md` (зеркала, SYNC).
- `docs/investment/_cross-cutting/scripts-map.md` — `archive_snapshot.py`.
- `docs/test-registry.md` — блоки тестов §1–§3.

## 6. Открыто по загрузчику

- **PDL-SNAP**, варианты 1–2 (история закрытых позиций в снапшоте, скрипты-ответчики) — не
  делались: правило в `ru-portfolio-advisor` (startup-checklist Шаг 3.7) закрыло кейс 16.10.
- Остаток корректировки IntelInvest −25 713 ₽ за 01–13.10 — найти операцию в отчёте брокера.
- `cash_drift_changed` мог бы сразу перечислять новые строки сделок за период и Δ по классам
  потоков — тогда такие разборы не требовали бы ручной выгрузки (предложение из PDL-RECON,
  в TODO не заведено).
