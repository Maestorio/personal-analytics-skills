# Контракт MCP ZenMoney

- **contract_version:** 2.2
- **verified_at:** 2026-10-05 (чтение — по описаниям и реальным ответам 2026-10-01; `upsert_transactions` — по описанию схемы, вызовов не было)
- **Как использовать:** рецепт R9 в `recipes.md`. Preflight — сравнение с этим файлом без вызовов API.

Этот файл описывает то, на что скилл опирается. Если MCP-провайдер что-то изменил, расхождение находится здесь.

---

## 1. Ожидаемые инструменты и параметры

### Чтение (скилл опирается на них)

| Инструмент | Параметры (обязательные отмечены *) |
|---|---|
| `get_monthly_report` | `from`*, `to`* (`YYYY-MM`, не более 24 месяцев включительно) |
| `list_transactions` | первая страница: `from`*, `to`* (`YYYY-MM-DD`), `limit` (1–200, по умолчанию 30), `order` (`desc` по умолчанию / `asc`), фильтры `accountIds`, `categoryIds`, `tagIds`, `merchantIds`, `comments`, `types` (`income`/`expense`/`transfer`), `incomeAmount`, `expenseAmount` (`from` / `toExclusive` / `equalTo`); продолжение: только `cursor` (+ `limit`) |
| `list_scheduled_transactions` | то же, что `list_transactions`, плюс `state` (`planned` по умолчанию / `processed` / `all`) |
| `list_accounts` | без параметров |
| `list_categories` | без параметров |
| `get_account_balances` | `accountIds`* (1–200), `dates`* (1–31 пар `{date, boundary: start|end}`) |
| `get_instrument_rates` | `dates`* (1–31, `YYYY-MM-DD`), `instruments` (1–200 кодов; без поля — все валюты счетов) |
| `get_user` | без параметров (обычно не нужен: те же данные в `references.user`) |
| `search_merchants` | первая страница: `query`*, `countryCode`, `limit`; продолжение: `cursor` (+ `limit`) |
| `search_financial_institutions` | то же, что `search_merchants` (скиллу почти не нужен) |

### Запись (только Режим C)

| Инструмент | Параметры | Примечание |
|---|---|---|
| `upsert_categories` | `categories`* (1–200: `id`, `name`, `parentId`, `isIncome`, `isExpense`, `isArchived`), `requestId` (обязателен при создании) | атомарный пакет |
| `create_merchant` | `name`* | разрешён пользователем; в сессии может отсутствовать или быть отклонён — тогда список для приложения (`write-mode.md`) |
| `upsert_transactions` | `transactions`* (1–200: `id`, `date`, `income`/`expense` `{accountId \| account:{type:"debt",merchantId}, amount, originalAmount, originalInstrument}`, `categoryId`, `tagIds`, `merchantId`, `comment`), `requestId` (обязателен при создании) | атомарный пакет; ловушки — `write-mode.md` §3 |

`delete_transactions` и `upsert_accounts` есть в MCP с 2026-10-05 (совместимое изменение §5), но **запрещены пользователем** — не вызывать (`write-mode.md` §3). В preflight их наличие — не расхождение.

Инструменты могут быть «отложенными»: перед сравнением загрузить их схемы (поиск по «ZenMoney»). Сравнивать по загруженной схеме, а не по памяти. Наличие инструмента в списке не означает, что вызов разрешён: запрет правилом доступа виден только при вызове.

---

## 2. Ключевые смыслы в описаниях инструментов

Сравнивать по смыслу, не по буквальному совпадению строк. Отсутствие смысла — сигнал сменить семантику.

| Инструмент | Что должно быть сказано | Зачем скиллу |
|---|---|---|
| `upsert_transactions` | Передача `income` или `expense` заменяет обе стороны; `categoryId: null` стирает категорию и теги; пропуск поля сохраняет его | `write-mode.md` Т1–Т4 |
| `get_monthly_report` | Область отчёта — все счета `isInBalance` (независимо от `isOtherUser`), категории и настройки планирования по умолчанию; переопределений на вызов нет | Охват отчёта (R8) |
| `get_monthly_report` | Использовать `factWithRefund`, возвраты уже учтены; `fact` — «сырой» | Не вычитать возвраты повторно |
| `get_monthly_report` | «С переводами» = `TagTotal` + строки `TransferGroup` того же `isIncome`, кроме `EXCHANGE_DIFF`; `EXCHANGE_DIFF` не входит никогда | Исключения по умолчанию |
| `get_monthly_report` | Не суммировать родителя и потомков (ни `Tag`, ни `Transfer`) | Принцип 4 |
| `list_transactions` | Читать до `nextCursor = null` перед агрегированием; курсор сохраняет фильтры; страницы — не стабильный снимок | Пагинация |
| `list_transactions` | Суммы в валюте счёта без пересчёта; точки группировать по `merchantId`, не по имени | R4, R10 |
| `list_transactions` | Фильтр категории — только основная категория, без детей; фильтр тега — только теги | R4, R11 |
| `list_transactions` | Факты могут включать холды и операции будущей датой | Оговорки |
| `list_accounts` | Остатки текущие, включают холды и операции будущей датой; долги: «+» должны пользователю, «−» должен он | R3, R6 |
| `get_account_balances` | `balanceInMainCurrency` уже пересчитан по курсу на дату; это реконструкция по текущим записям, не снимок | R12 |
| `get_instrument_rates` | RUB за единицу; на дату, при нехватке истории может взять более поздний курс; `null` — курса нет | R4, R8 |
| `list_scheduled_transactions` | Только созданные вхождения; шаблоны (`references.schedules`) не суммировать; `processed` ≠ оплачено | R5 |
| все чтения | `references` — справочные сущности страницы, не дополнительные операции | Не дублировать суммы |

---

## 3. Ожидаемые поля ответов

**Обязательные** — пропажа = ломающее изменение. **Необязательные** — не приходят, когда пусты; их отсутствие в конкретном ответе не расхождение.

| Ответ | Обязательные | Необязательные |
|---|---|---|
| Любое чтение со ссылками | `references.user`: `currency`, `monthStartDay` | `references.accounts`, `categories`, `merchants`, `instrumentRates`, `schedules` |
| `list_accounts` | `data[]`: `id`, `name`, `type`, `instrument`, `balance`, `isInBalance`, `isArchived`, `isSavings`, `isOtherUser`; `nextCursor` (всегда `null`) | `institution {id, name, countryCode}`, `externalIds`, `startBalance`, `creditLimit`, `balanceCorrectionType`, `merchantId` (у долгов); у вкладов `interestRate`, `openingDate`, `openingAmount`, `term`, `capitalization`, `payoffPeriod` |
| `list_categories` | `data[]`: `id`, `name`, `parentId`, `isIncome`, `isExpense`, `isArchived` | — |
| `list_transactions` | `data[]`: `id`, `date`, хотя бы одно из `expense`/`income` (`accountId`, `amount`); `nextCursor` (ключ есть, значение может быть `null`) | `categoryId` (нет у переводов), `tagIds`, `merchantId` (может быть `null`), `originalPayee`, `payee`, `comment`, `source`, `hold` |
| `get_monthly_report` | `currency`; `months` → `YYYY-MM` → строки: `rowId.type.type`, `rowId.isIncome`, `fact`, `factWithRefund`; у категорий `rowId.type.categoryId`, у переводов `rowId.type.accountId`, у групп `rowId.type.transferGroupType` | `parentRowId` (нет у `TagTotal`, `Transfer`, `TransferGroup`), `factCount`, `budget`, `isHidden`, `isForecast`, `residue`, `delta`, `planned`, `processed`, `expired`, `plannedCount`, `isLocked`; верхнеуровневый `monthStartDay`; `references.categories`, `references.accounts` |
| `get_account_balances` | `data[]`: `date`, `boundary`, `accountId`, `balance`, `instrument`, `balanceInMainCurrency` | `references.instrumentRates` (текущие) |
| `get_instrument_rates` | `data[]`: `instrument`, `date`, `rate` (может быть `null`) | — |
| `list_scheduled_transactions` | `data[]`: `id`, `date`, `expense`/`income`, `scheduleId`, `state`; `nextCursor` | `categoryId`, `merchantId`, `isForecast`; `references.schedules` → `interval`, `step`, `points`, `startDate` |

---

## 4. Семантические допущения

| № | Допущение | Статус |
|---|---|---|
| A1 | Сумма строк верхнего уровня = `TagTotal` (±1 ₽) | Проверено на 2026-09 (расходы и доходы) и ранее на шести месяцах |
| A2 | Отчёт покрывает только счета `isInBalance = true` | Подтверждено на данных 2026-09-24; формулировка есть в описании v2 |
| A3 | Тег лежит в `tagIds` операции и не виден в отчёте | Проверено; тег поездки встречается на «Корректировке» кошелька (2026-09) |
| A4 | Суммы операций — в валюте счёта | Проверено |
| A5 | `nextCursor = null` на последней странице | Проверено |
| A6 | `source: split` — часть разбитой операции | По наблюдению, в описании не сказано |
| A7 | Возврат покупки — `income` с расходной `categoryId`; в отчёте это доходная строка расходной категории, `fact = factWithRefund` | Проверено на 2026-08 и 2026-09 |
| A8 | Пустые поля операций не передаются (`tagIds`, `comment`, `hold` у ручных и т. п.) | Проверено 2026-10-01 |
| A9 | Большие ответы (`list_accounts`, месяц операций) сохраняются средой в файл | `list_accounts` ≈ 54 тыс. символов → файл, 2026-10-01 |
| A10 | Доходная строка родителя в отчёте может иметь `factCount = 0` и `fact` = сумма детей (возврат в подкатегории) | Наблюдалось 2026-09 («Транспорт» ← «Такси») |
| A11 | Фильтры `categoryIds`/`types` применяются на сервере до пагинации | Проверено 2026-10-01 |
| A12 | `get_account_balances` возвращает `balanceInMainCurrency` по курсу на дату | Проверено 2026-10-01 (курс отличается от текущего) |
| A13 | Поле `payee` в операциях банковского плагина не приходит; имя точки — `references.merchants[merchantId].name`, сырое — `originalPayee` | Наблюдение 2026-10-01 |
| A14 | `originalPayee` без `merchantId` при создании: подставляется сохранённая точка с тем же нормализованным именем, иначе текст может стать новой точкой (по инструкции MCP — не становится; наблюдалось обратное 2026-10-10/11) | Не проверено после смены инструкции — перечитывать `merchantId` после каждого создания (Т12) |

---

## 5. Классификация расхождений

| Тип | Пример | Действие |
|---|---|---|
| **Ломающее** | Инструмент чтения из §1 отсутствует или переименован; обязательный параметр изменён; пропало **обязательное** поле из §3 | Остановить рецепт. «Скилл устарел: <что именно>». Числа не выдавать, если сверка не проходит. Предложить правки в `mcp-contract.md` и рецептах |
| **Смена семантики** | Нет смысла из §2 (особенно про область отчёта); изменился текст о возвратах или о курсах | Запустить канарейку и R8; до результата помечать цифры оговоркой |
| **Совместимое (новые возможности)** | Новый инструмент (в том числе записи); необязательный параметр; новые поля; нет необязательного поля | Продолжить по старым рецептам. Одной строкой: «MCP получил: …. Скилл можно упростить (см. §6)». Новый инструмент записи — только Режим C |
| **Запрет доступа** | Вызов отклонён правилом разрешений | Не обходить; сказать пользователю |
| **Не удалось сравнить** | Схема не загружена | Загрузить схему и повторить; иначе сказать «контракт не проверен» |

---

## 6. Признаки улучшений на стороне провайдера

| Возможность | Признак | Что обновить |
|---|---|---|
| Агрегирующий инструмент | Новый инструмент или параметр `group_by` / `aggregate` | R4, R10, R11: считать на стороне сервера |
| Экспорт в файл | Ссылка, `url`, `download`, файловый ресурс | R4, пересчёт истории: скачать и считать в песочнице |
| Охват отчёта | Параметр вроде `accountIds` или `includeAllAccounts` в отчёте | Убрать R8, поправить A2 |
| Компактный список счетов | `fields`, фильтр по `isArchived` | Режим B и R3 дешевле |
| Теги в отчёте | Строки с `tagId` | Убрать оговорки про теги |
| Фильтр категории с потомками | Параметр вроде `includeChildren` | R4, R11 проще |
| Удаление/восстановление операций | `delete_transactions` (есть с 2026-10-05), `restore_*` | Удаление запрещено пользователем; восстановление — только Режим C, отдельное согласие на каждую запись |

---

## 7. Журнал версий контракта

Результаты проверок в конкретной среде (дата, что нашлось) хранятся в приватной карте, раздел «Проверки». Сюда записываются только изменения самого контракта.

| contract_version | verified_at | Что изменилось |
|---|---|---|
| 1 | 2026-09-24 | Первая версия |
| 1 (правка) | 2026-09-24 | A2 подтверждено на реальных данных; контракт (инструменты, параметры) не менялся |
| 1.1 | 2026-09-24 | §3 разделён на обязательные и необязательные поля (иначе канарейка ложно срабатывала на отсутствие `tagIds`); добавлены A7–A9; A1 перепроверено на 2026-08 |
| 2.0 | 2026-10-01 | **Ломающее обновление MCP.** Удалены `get_reference_data`, `get_transactions`, `get_scheduled_transactions`. Новые чтения: `list_accounts`, `list_categories`, `list_transactions` (фильтры по счёту, категории, тегу, точке, комментарию, типу, сумме), `list_scheduled_transactions` (те же фильтры), `get_account_balances` (остатки на даты), `get_instrument_rates` (курсы на даты), `get_user`, `search_merchants`, `search_financial_institutions`. Запись: `upsert_categories`, `create_merchant`. Во всех чтениях — `references` с названиями. У счетов `title` → `name`, `company` → `institution {name, countryCode}`, ID долгов — непрозрачные `a1_…`, `term` — ISO 8601. У плановых шаблоны переехали в `references.schedules`. Добавлены A10–A13 |
| 2.2 | 2026-10-05 | Появились `delete_transactions` и `upsert_accounts`; решение пользователя — оба запрещены в скилле |
| 2.3 | 2026-11-01 | Инструкция MCP: `originalPayee` слать вместе с `merchantId`, не создавать точки из строк банка; добавлено A14. `create_merchant` разрешён пользователем |
| 2.1 | 2026-10-02 | Появился `upsert_transactions` (создание и правка операций; ловушки замены обеих сторон и стирания тегов). Протокол записи вынесен в `write-mode.md`: согласие на каждый пункт, снимок до и проверка после |
