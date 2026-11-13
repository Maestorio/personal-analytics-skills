# Skill: macro-ru-watcher

## Summary
Снапшот российских макроиндикаторов без интерпретации — именно так и должно быть. Реальные `macro-snapshots/ru-2026-05-02.md` и `RU-2026-05-07.md` (UPPERCASE — нарушение D4) фиксируют 7 индикаторов. Главные дефекты: (1) USD/RUB в обоих свежих снапшотах помечен `❓` (нет данных) — fallback на ЦБ-курс или альтернативный источник не описан; (2) имя `RU-2026-05-07.md` в UPPERCASE; (3) Tier 1 в `SKILL.md` обозначен как «7 индикаторов», но в `references/sources-ru.md` заголовок секции web_search говорил «2», а тело перечисляло 3. Нерабочие дни обработаны (берётся последняя торговая сессия).

## Correctness (P1)
- [naming-violation] `macro-snapshots/RU-2026-05-07.md` использует UPPERCASE префикс. По `_shared-references/file-naming.md` — должно быть `ru-{date}.md` lowercase.
  - Эффект: D4-нарушение, Glob-фильтры пропустят.
  - **Статус: TODO → [MRW-1]**. Код/SKILL.md корректны. Требует ручного переименования файла на Synology Drive.

- [missing-fallback] USD/RUB помечен `❓` в обоих свежих снапшотах. SKILL.md не описывал fallback перед тем, как ставить `❓`.
  - Эффект: Tier 1 индикатор системно отсутствует при любой проблеме с MOEX ISS.
  - **Статус: ЗАКРЫТ**. В `references/sources-ru.md` добавлена секция «Fallback для USD/RUB при ошибке скрипта» с цепочкой: 1) MOEX ISS напрямую, 2) CBR XML `XML_daily.asp`, 3) web_search. ❓ только если все три упали.

- [spec-inconsistency] `references/sources-ru.md` заголовок секции web_search писал «2 индикатора», но тело перечисляло 3 (инфляция г/г, инфляция нед, Brent). Reviewer ошибочно назвал причиной «IMOEX как 8-й индикатор» — IMOEX корректно входит в 7, проблема была в тексте заголовка.
  - **Статус: ЗАКРЫТ**. Заголовок исправлен: «оставшиеся 3 индикатора через web_search».

## Readability (P2)
- 244 строки SKILL.md — компактно, шаги ясные.
- Anti-patterns явные: «не интерпретировать», «не прогнозировать», «не рекомендовать», «не скрывать data quality».
- Fallback при недоступности web_search — текстом «попробуй позже», не автоматизированно.

## Cost (P3)
- 8–11 web_search/web_fetch на запуск — приемлемо (раз в неделю).
- ЦБ-курсы кэшируются (`cbr_rates_bundled.json` в data-loader, не здесь).

## Speed (P4)
- Параллельная загрузка 7–11 источников. ~5–10 секунд.

## Cross-skill / contract
- D3-исключение: `macro-snapshots/` пишет macro-ru-watcher напрямую (как `Portfolio/snapshots/` для loader). Это есть в `_shared-references/transport-layer.md:140` (пример пути), но не явно в layout-doc.
- Downstream: `macro-forecast-chain` (читает свежий `ru-{date}.md` для baseline), `ru-portfolio-advisor` (Mode 8).
- Memory integration: `[macro]`-запись с next_due — но реализация не в этом скилле, а через memory-sync.

## Verified against artifact
- `~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/macro-snapshots/ru-2026-05-02.md` (lowercase) и `RU-2026-05-07.md` (UPPERCASE):
  - 7 индикаторов в обоих, IMOEX присутствует
  - USD/RUB: «торговля приостановлена с 13.06.2024» (старая ссылка) или `❓` нет данных
  - z-score не превышает 1.0 нигде в свежем — индикаторы спокойные
  - Каждое значение со ссылкой на первоисточник ✓
- D4-нарушение в файле 7-мая (UPPERCASE).
