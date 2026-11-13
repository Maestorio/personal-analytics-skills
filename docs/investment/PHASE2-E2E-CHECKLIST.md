# Фаза 2 — E2E проверки на реальных данных

> Этот файл — инструкция для ручной локальной проверки изменений Фазы 2 (**I-1**: перенос
> bond-обогащения MOEX ISS из браузера в `portfolio-data-loader`) на реальных артефактах.
> Юнит-тесты (`python3 skills/portfolio-data-loader/tests/test_*.py`) покрывают
> детерминированную логику (`_build_bonds`, `_coupon_freq`, payload-unwrap).
> E2E-проверки ниже — чтобы убедиться, что весь пайплайн работает с **реальной выгрузкой
> IntelInvest + MOEX ISS** и что viewer показывает облигации **офлайн**, без браузерного fetch.

**Что именно проверяем (I-1):**
- `moex_quotes.py --fields weekly` отдаёт полный bond-набор (купон, частота, номинал, НКД,
  дата след. купона, YTM, дюрация, оферта, погашение).
- `assemble_snapshot.py` кладёт эти поля в каждый `holding` с `asset_type: "bond"`.
- `portfolio-integrated-viewer.html` рендерит облигацию из полей `holding`, **без** сетевого
  запроса к `iss.moex.com` (мёртвый блок `moexBondCache`/`fetchMoexBond`/`showBondModalFromMoex`
  удалён).

> **D-1 (per-account XIRR)** в Фазу 2 **не входит** — заблокирована отсутствием trades-выгрузки
> IntelInvest с разметкой по счёту. Проверять нечего.

---

## Предусловия

```bash
# Зависимости
pip install numbers-parser openpyxl --break-system-packages -q
# (scipy опционально — для XIRR; certifi опционально — для SSL на macOS)

# Все команды запускать из корня репозитория
cd ~/claude_skills   # или куда склонирован repo

# Нужна сеть к iss.moex.com (для шагов 1–3). Шаги 4–5 — офлайн.
```

**Тестовые данные (когда будут доступны):**
- `trades_portfolio_*.xlsx` — выгрузка сделок IntelInvest (хотя бы с одной облигацией).
- `Общий баланс.numbers` (или `.xlsx`) — текущие позиции, включая ≥1 облигацию.

Положи их в `/tmp/`:
```bash
TRADES=/tmp/trades.xlsx
BALANCE="/tmp/Общий баланс.numbers"
```

---

## I-1.A — moex_quotes weekly-профиль отдаёт bond-поля

**Цель:** убедиться, что `--fields weekly` действительно возвращает полный bond-набор
(а не только цену), и что `COUPONPERIOD` присутствует → частота купона вычислима.

### Шаг 1. Health-check + котировка реальной облигации

```bash
# MOEX доступен?
python3 _shared-references/moex_quotes.py --health

# Запросить 1–2 реальные облигации из ПОРТФЕЛЯ (SECID = тикер из parse_portfolio.py;
# не бери примеры «из головы» — погашенные/делистнутые вернут not_in_response).
# Пример живых на 2026-06: RU000A105JH9 RU000A108G70 RU000A105GN3.
python3 _shared-references/moex_quotes.py \
    --type bond --fields weekly RU000A105JH9 RU000A108G70 \
    --json | python3 -c "
import json, sys
data = json.load(sys.stdin)
quotes = data.get('quotes', data)   # CLI отдаёт обёртку {source,profile,quotes,errors}
for secid, q in quotes.items():
    if q.get('kind') != 'bond':
        print(f'  {secid}: не bond (kind={q.get(\"kind\")}) — взять другой тикер'); continue
    fields = ['coupon_pct','coupon_period_days','next_coupon_date','accrued_interest',
              'face_value','ytm_pct','duration_days','maturity_date','offer_date']
    present = [f for f in fields if q.get(f) is not None]
    missing = [f for f in fields if q.get(f) is None]
    print(f'  {secid}: есть {len(present)}/{len(fields)} → {present}')
    if missing: print(f'    ⚠️  null: {missing}')
    assert q.get('coupon_period_days') is not None, 'COUPONPERIOD не пришёл — частота не вычислится!'
    print('  ✅ coupon_period_days присутствует → coupon_freq_per_year будет вычислен')
"
```

**Ожидаемый результат:**
- `kind: "bond"`, заполнены `coupon_pct`, `coupon_period_days`, `ytm_pct`, `duration_days`,
  `maturity_date`, `face_value`.
- `coupon_period_days` **не null** (иначе частота купона не вычислится — это и есть суть I-1).
- `offer_date`/`accrued_interest` могут быть null для бумаг без оферты/в день купона — это норма.

> Если `coupon_period_days` приходит null **для всех** бумаг — проверь, что `COUPONPERIOD`
> остался в `BOND_STATIC_WEEKLY` (а не уехал обратно в `full`):
> ```bash
> python3 -c "import sys; sys.path.insert(0,'skills/portfolio-data-loader/scripts'); \
>   import moex_quotes as m; assert 'COUPONPERIOD' in m.BOND_STATIC_WEEKLY; \
>   assert m.BOND_STATIC_FULL.count('COUPONPERIOD')==1; print('✅ профиль OK')"
> ```

---

## I-1.B — assemble_snapshot переносит bond-поля в holdings

**Цель:** прогнать полный пайплайн на реальной выгрузке и убедиться, что в финальном
снапшоте каждый `holding` с `asset_type: "bond"` несёт обогащённые поля.

### Шаг 1. Полный пайплайн (порядок строгий)

```bash
TODAY=$(date +%Y-%m-%d)

# 1) Общий баланс → portfolio.json
python3 skills/portfolio-data-loader/scripts/parse_portfolio.py "$BALANCE" > /tmp/portfolio.json

# 2) Сделки → returns.json
python3 skills/portfolio-data-loader/scripts/portfolio_returns.py \
    --trades "$TRADES" --format json > /tmp/returns.json

# 3) Per-security XIRR
TICKERS=$(python3 -c "
import json
pos = json.load(open('/tmp/returns.json'))['snapshot_current']['positions']
print(','.join(p['ticker'] for p in pos if not p.get('is_blocked') and p.get('qty',0)>0))")
# Примечание: --common ОПЦИОНАЛЕН и принимает ТОЛЬКО .xlsx-баланс (override рыночных
# цен для XIRR), НЕ parsed portfolio.json. Без него скрипт берёт цены сам — для E2E
# bond-обогащения это не важно, поэтому --common опускаем.
python3 skills/portfolio-data-loader/scripts/per_security_xirr.py \
    --trades "$TRADES" --tickers "$TICKERS" \
    --format json --no-cashflows > /tmp/per_security.json

# 4) Котировки — ВАЖНО: --fields weekly (не minimal!)
python3 _shared-references/moex_quotes.py \
    --fields weekly --from-portfolio /tmp/portfolio.json \
    --json > /tmp/quotes.json

# 5) Сборка снапшота
python3 skills/portfolio-data-loader/scripts/assemble_snapshot.py \
    --portfolio /tmp/portfolio.json \
    --returns /tmp/returns.json \
    --per-security /tmp/per_security.json \
    --quotes /tmp/quotes.json \
    --output /tmp/portfolio-${TODAY}.json
```

### Шаг 2. Проверить bond-обогащение в снапшоте

```bash
python3 -c "
import json
snap = json.load(open('/tmp/portfolio-$(date +%Y-%m-%d).json'))
holdings = snap.get('holdings') or snap.get('positions') or []
bonds = [h for h in holdings if h.get('asset_type')=='bond']
print(f'Облигаций в снапшоте: {len(bonds)}')
if not bonds:
    print('⚠️  Нет облигаций — взять портфель с бондом'); raise SystemExit
enriched_fields = ['coupon_pct','coupon_freq_per_year','next_coupon_date','accrued_int',
                   'nominal','nominal_currency','ytm_pct','duration_days','maturity_date']
for b in bonds:
    present = [f for f in enriched_fields if b.get(f) is not None]
    print(f'  {b.get(\"ticker\")}: {len(present)}/{len(enriched_fields)} полей · '
          f'купон={b.get(\"coupon_pct\")}% · freq={b.get(\"coupon_freq_per_year\")}/год · '
          f'YTM={b.get(\"ytm_pct\")} · ytm_source={b.get(\"ytm_source\")}')
# Хотя бы одна облигация должна нести полный набор (если MOEX отдал данные)
assert any(b.get('coupon_freq_per_year') is not None for b in bonds), \
    'Ни одна облигация не получила coupon_freq_per_year — проверь --fields weekly на шаге 4'
print('✅ I-1.B: bond-поля в снапшоте присутствуют')
"
```

**Ожидаемый результат:**
- Каждая облигация с MOEX-данными несёт `coupon_pct`, `coupon_freq_per_year`,
  `next_coupon_date`, `accrued_int`, `nominal`, `ytm_pct`, `duration_days`, `maturity_date`.
- `ytm_source: "moex_iss"` для бумаг с YTM.
- Облигация на двух счетах (ИИС-3 split) → **обе** записи несут bond-поля.

**Если поля null при наличии облигации:**
- Чаще всего — на шаге 4 запущен `--fields minimal` вместо `weekly`. Перезапусти шаг 4.
- Если `coupon_freq_per_year: null`, но `coupon_pct` есть → MOEX не вернул `COUPONPERIOD`
  по этой бумаге (частоту не угадываем — это by design, см. `_coupon_freq`).

### Шаг 3. (опц.) Грейсфул-режим без MOEX

```bash
# Симулировать недоступность MOEX: пустые quotes
echo '{"source":"moex_iss","profile":"weekly","quotes":{},"errors":[]}' > /tmp/quotes_empty.json
python3 skills/portfolio-data-loader/scripts/assemble_snapshot.py \
    --portfolio /tmp/portfolio.json --returns /tmp/returns.json \
    --quotes /tmp/quotes_empty.json --output /tmp/portfolio-nomoex.json
python3 -c "
import json
bonds = [h for h in json.load(open('/tmp/portfolio-nomoex.json')).get('holdings',[])
         if h.get('asset_type')=='bond']
assert all(b.get('coupon_pct') is None for b in bonds), 'без MOEX купон должен быть null'
assert all(b.get('current_price_source')=='last_trade' for b in bonds if b.get('current_price_source'))
print('✅ I-1.B (graceful): без MOEX bond-поля null, скрипт не падает, цена last_trade')
"
```

**Ожидаемый результат:** скрипт не падает, bond-поля `null`, цена из `last_trade`.

---

## I-1.C — Viewer работает офлайн (нет браузерного MOEX-fetch)

**Цель:** убедиться, что облигация без `weekly-review-bond-*.yaml` рендерится в модалке
из полей снапшота, **без** сетевого запроса к `iss.moex.com`.

### Шаг 1. Статическая проверка — мёртвый блок удалён

```bash
# Должно быть 0 совпадений: lazy-fetch вырезан
grep -c "showBondModalFromMoex\|moexBondCache\|fetchMoexBond" tools/portfolio-integrated-viewer.html
# → 0

# Никаких прямых fetch к MOEX из viewer не осталось
grep -c "iss.moex.com" tools/portfolio-integrated-viewer.html
# → 0
```

**Ожидаемый результат:** обе команды печатают `0`. Если не 0 — мёртвый блок не удалён
или появился новый сетевой вызов.

### Шаг 2. Ручная проверка в браузере

1. Открыть `tools/portfolio-integrated-viewer.html` в браузере.
2. Открыть **DevTools → вкладка Network**, поставить фильтр `moex`.
3. Загрузить `/tmp/portfolio-${TODAY}.json` (снапшот из I-1.B) **без** bond-weekly-review.
4. Перейти на вкладку облигаций, кликнуть по строке облигации, у которой нет weekly-review.
5. **Проверить модалку** — должны быть заполнены: Номинал, Купон (`% · N раз/год`),
   Следующий купон, **НКД**, YTM, Duration, Погашение.
6. **Проверить Network** — после клика **не должно** быть запроса к `iss.moex.com`.

**Ожидаемый результат:**
- Модалка показывает купон/частоту/номинал/НКД/след.купон **из полей `holding`** снапшота.
- Network-таб пуст по фильтру `moex` — данные офлайн, один источник истины.

**Если модалка пустая (прочерки вместо данных):**
- Проверь, что снапшот действительно содержит bond-поля (вернись к I-1.B Шаг 2).
- Проверь, что `buildBondRow` получает `holding` третьим аргументом и читает
  `holding?.coupon_pct` / `holding?.coupon_freq_per_year` / `holding?.nominal` /
  `holding?.next_coupon_date` / `holding?.accrued_int`.

---

## Юнит-тесты (детерминированная верификация)

```bash
# Запускать из корня репозитория
python3 skills/portfolio-data-loader/tests/test_bond_enrichment.py   # 17 проверок (вкл. yield-to-offer separation)
python3 skills/portfolio-data-loader/tests/test_first_appearance.py  # 7 проверок (регрессия assemble)
python3 skills/portfolio-data-loader/tests/test_per_security_xirr.py # 11 проверок (требует examples/)
```

Все должны пройти 100%. `test_bond_enrichment.py` покрывает: полный quote → все поля,
отсутствие quote → graceful nulls, частичный quote без `coupon_period_days` →
`coupon_freq_per_year: null`, fallback номинала на balance, fx-замещайка (USD-номинал),
ИИС-3 split (оба holding несут поля), `_coupon_freq` (182→2, 91→4, 365→1, 30→12, None/0→None).

---

## Ожидаемые артефакты после первого боевого прогона

| Артефакт | Путь | Что нового (I-1) |
|---|---|---|
| `portfolio-{date}.json` | `Portfolio/snapshots/` | `holdings[asset_type=bond]` несут `coupon_pct`, `coupon_freq_per_year`, `next_coupon_date`, `accrued_int`, `nominal`, `ytm_pct`, `duration_days`, `maturity_date`, `offer_date` |

Viewer отдельным артефактом не сохраняется — это статический HTML в репозитории,
изменения уже в `tools/portfolio-integrated-viewer.html`.

---

*Создан 2026-06-09 как часть Фазы 2 (I-1). Обновить при смене bond-схемы снапшота, профиля
`weekly` в `moex_quotes.py` или формата модалки облигации в viewer.*
