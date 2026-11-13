#!/usr/bin/env python3
"""Тесты канонического статуса позиции (SSOT KNOWN_POSITION_STATUS).

Механика: реестр KNOWN_POSITION_STATUS (ручной, как KNOWN_SPLITS) назначает
holdings[].status ∈ {normal, blocked, distressed}; is_blocked после применения —
строго производное (status == "blocked"); status_summary.by_status даёт
канонические доли стоимости для downstream (stress / integrated-view /
coherence-audit §3).

Запуск: python3 skills/portfolio-data-loader/tests/test_position_status.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from assemble_snapshot import (  # noqa: E402
    KNOWN_POSITION_STATUS, POSITION_STATUSES,
    _apply_position_status, _build_blocked_positions, _build_status_summary,
    assemble,
)

PASSED = FAILED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ✓ {name}")
    else:
        FAILED += 1
        print(f"  ✗ {name}  {detail}")


def mk_holding(**kw) -> dict:
    base = {"ticker": "SBER", "isin": "RU0009029540", "name": "Сбербанк",
            "asset_type": "stock", "account": "main", "qty": 10,
            "value_rub": 10_000.0, "is_blocked": False, "currency": "RUB"}
    base.update(kw)
    return base


print("== 1. Реестр: инварианты ==")
check("Борец RU000A105GN3 СНЯТ с реестра (2026-07-23: событие 2025 урегулировано, "
      "бумага в обращении — ложный RED FLAG от записи «со слов» без верификации)",
      "RU000A105GN3" not in KNOWN_POSITION_STATUS)
check("каждая запись реестра имеет валидный status и note",
      all(e.get("status") in POSITION_STATUSES and e.get("note")
          for e in KNOWN_POSITION_STATUS.values()))
check("таксономия — ровно normal/blocked/distressed",
      set(POSITION_STATUSES) == {"normal", "blocked", "distressed"})

# Синтетическая distressed-запись — fixture для секций 3/4/6/8/9 (реальный Борец
# снят с distressed; механика реестра тестируется на несуществующем ISIN).
TEST_DISTR = "RU000A0TEST7"
KNOWN_POSITION_STATUS[TEST_DISTR] = {
    "status": "distressed",
    "note": "тестовая запись: эмитент под судебными мерами с 27.03.2026 (fixture, "
            "не реальная бумага)",
}
check("fixture-запись distressed валидна",
      KNOWN_POSITION_STATUS[TEST_DISTR]["status"] == "distressed")

print("== 1а. Замороженные иностранные акции (СПб-биржа, 2022) ==")
FROZEN_16 = {"BAC", "PEP", "KMB", "SYY", "RTX", "ABT", "EWBC", "EMR",
             "MS", "KO", "HBAN", "GD", "Z", "BMY", "PFE", "C"}
check("все 16 замороженных тикеров в реестре как blocked",
      all(KNOWN_POSITION_STATUS.get(t, {}).get("status") == "blocked"
          for t in FROZEN_16))
check("FINAMAR НЕ в реестре (владелец ведёт вручную)",
      "FINAMAR" not in KNOWN_POSITION_STATUS)
hs = [mk_holding(ticker="BAC", isin=None, currency="RUB")]
_apply_position_status(hs)
check("BAC → status blocked, is_blocked True",
      hs[0]["status"] == "blocked" and hs[0]["is_blocked"] is True)
check("note о заморозке 21.02.2022", "21.02.2022" in hs[0]["status_note"])

print("== 2. _apply_position_status: дефолт normal ==")
hs = [mk_holding()]
_apply_position_status(hs)
check("status = normal", hs[0]["status"] == "normal")
check("is_blocked производно False", hs[0]["is_blocked"] is False)
check("status_note не добавлен", "status_note" not in hs[0])

print("== 3. Реестр по ticker (fixture: ticker == ISIN) ==")
hs = [mk_holding(ticker=TEST_DISTR, isin=TEST_DISTR,
                 name="ТестБумага (fixture)", asset_type="bond", value_rub=156_441.18)]
_apply_position_status(hs)
check("status = distressed", hs[0]["status"] == "distressed")
check("distressed НЕ is_blocked", hs[0]["is_blocked"] is False)
check("status_note с датой и причиной",
      "27.03.2026" in hs[0].get("status_note", ""))

print("== 4. Реестр по ISIN (ticker не совпал) ==")
hs = [mk_holding(ticker="БОРЕЦ-КЗО26", isin=TEST_DISTR, asset_type="bond")]
_apply_position_status(hs)
check("fallback на ISIN сработал", hs[0]["status"] == "distressed")

print("== 5. Upstream is_blocked=True вне реестра → blocked ==")
hs = [mk_holding(ticker="FXUS", isin=None, is_blocked=True)]
_apply_position_status(hs)
check("status = blocked", hs[0]["status"] == "blocked")
check("is_blocked консистентен", hs[0]["is_blocked"] is True)

print("== 6. Реестр приоритетнее upstream is_blocked ==")
hs = [mk_holding(ticker=TEST_DISTR, isin=TEST_DISTR, is_blocked=True)]
_apply_position_status(hs)
check("реестр перекрывает upstream", hs[0]["status"] == "distressed")
check("is_blocked пересчитан из status", hs[0]["is_blocked"] is False)

print("== 7. Graceful: пустой/битый вход ==")
_apply_position_status(None)
_apply_position_status([])
hs = [mk_holding(), "мусор"]
_apply_position_status(hs)
check("не-dict элементы пропущены, dict обработан",
      hs[0]["status"] == "normal" and hs[1] == "мусор")

print("== 8. _build_status_summary: доли стоимости ==")
hs = [
    mk_holding(ticker="SBER", value_rub=60_000.0),
    mk_holding(ticker="LKOH", value_rub=20_000.0),
    mk_holding(ticker=TEST_DISTR, isin=TEST_DISTR,
               asset_type="bond", value_rub=15_000.0),
    mk_holding(ticker="FXUS", isin=None, is_blocked=True, value_rub=5_000.0),
]
_apply_position_status(hs)
summ = _build_status_summary(hs)
by = summ["by_status"]
check("total = сумма стоимостей", summ["total_value_rub"] == 100_000.0)
check("normal 80%", by["normal"]["value_rub"] == 80_000.0
      and by["normal"]["pct"] == 80.0, str(by["normal"]))
check("distressed 15%", by["distressed"]["value_rub"] == 15_000.0
      and by["distressed"]["pct"] == 15.0)
check("blocked 5%", by["blocked"]["value_rub"] == 5_000.0
      and by["blocked"]["pct"] == 5.0)
check("counts по статусам", by["normal"]["count"] == 2
      and by["distressed"]["count"] == 1 and by["blocked"]["count"] == 1)
check("tickers только у non-normal",
      "tickers" not in by["normal"]
      and by["distressed"]["tickers"] == [TEST_DISTR]
      and by["blocked"]["tickers"] == ["FXUS"])

print("== 9. Сводка: main+iis_3 записи одного тикера не дублируют tickers ==")
hs = [
    mk_holding(ticker=TEST_DISTR, isin=TEST_DISTR,
               asset_type="bond", account="main", value_rub=100_000.0),
    mk_holding(ticker=TEST_DISTR, isin=TEST_DISTR,
               asset_type="bond", account="iis_3", value_rub=50_000.0),
]
_apply_position_status(hs)
summ = _build_status_summary(hs)
check("value_rub суммируется по обеим записям",
      summ["by_status"]["distressed"]["value_rub"] == 150_000.0)
check("тикер в списке один раз",
      summ["by_status"]["distressed"]["tickers"] == [TEST_DISTR])
check("count считает записи (2)", summ["by_status"]["distressed"]["count"] == 2)

print("== 10. Сводка: value_rub=None не роняет и не входит в total ==")
hs = [mk_holding(ticker="AAA", value_rub=None), mk_holding(ticker="BBB")]
_apply_position_status(hs)
summ = _build_status_summary(hs)
check("total без None-стоимостей", summ["total_value_rub"] == 10_000.0)
check("count учитывает обе", summ["by_status"]["normal"]["count"] == 2)

print("== 11. Пустой вход → нулевая сводка ==")
summ = _build_status_summary([])
check("total 0, pct 0", summ["total_value_rub"] == 0.0
      and all(v["pct"] == 0.0 for v in summ["by_status"].values()))

print("== 11а. _build_blocked_positions: замороженные фонды из returns ==")
returns_blocked = {"snapshot_current": {"positions": [
    {"ticker": "FXUS", "name": "FinEx USA", "type": "fund", "qty": 1504.0,
     "value_rub": 89578.0, "cost_basis_rub": 120000.0, "currency": "RUB",
     "price_source": "blocked_last_trade_price", "is_blocked": True},
    {"ticker": "RSHA", "name": "РСХБ Америка", "type": "fund", "qty": 425.0,
     "value_rub": 50562.0, "cost_basis_rub": 40000.0, "currency": "USD",
     "price_source": "blocked_last_trade_price", "is_blocked": True},
    {"ticker": "SBER", "name": "Сбербанк", "type": "stock", "qty": 100.0,
     "value_rub": 30000.0, "is_blocked": False},          # активная — не сюда
    {"ticker": "FXIT", "type": "fund", "qty": 0.0, "is_blocked": True},  # qty=0
]}}
blk, blk_flags = _build_blocked_positions(returns_blocked, {"LKOH"})
check("эмитятся только blocked с qty>0", [h["ticker"] for h in blk] == ["FXUS", "RSHA"])
check("value/price из returns as-is",
      blk[0]["value_rub"] == 89578.0
      and abs(blk[0]["current_price"] - 89578.0 / 1504) < 0.01)
check("avg_cost из cost_basis/qty", abs(blk[0]["avg_cost_rub"] - 120000.0 / 1504) < 0.01)
check("is_blocked=True, currency сохранена",
      blk[0]["is_blocked"] is True and blk[1]["currency"] == "USD")
check("info-флаг blocked_positions_included",
      any(f["code"] == "blocked_positions_included" for f in blk_flags))
_apply_position_status(blk)
check("после apply: status=blocked (upstream-флаг, без реестра)",
      all(h["status"] == "blocked" for h in blk))
check("builder-note сохранена apply'ем", "заморозка 2022" in blk[0]["status_note"])

print("== 11б. Дедуп и режим --blocked-value zero ==")
blk2, _ = _build_blocked_positions(returns_blocked, {"FXUS", "LKOH"})
check("тикер уже в holdings → не дублируется",
      [h["ticker"] for h in blk2] == ["RSHA"])
returns_zero = {"snapshot_current": {"positions": [
    {"ticker": "FXDE", "type": "fund", "qty": 2637.0, "value_rub": 0.0,
     "currency": "RUB", "price_source": "blocked_zero", "is_blocked": True},
]}}
blk3, flags3 = _build_blocked_positions(returns_zero, set())
check("zero-режим: позиция видна, value 0.0, цена None",
      blk3[0]["value_rub"] == 0.0 and blk3[0]["current_price"] is None)
check("warning blocked_positions_zero_valued с честной оговоркой об оценке",
      any(f["code"] == "blocked_positions_zero_valued"
          and "ненадёжна" in f["message"] for f in flags3))
check("graceful на пустом returns", _build_blocked_positions(None, set()) == ([], []))

print("== 11в. apply_corrections: Корректировки по замороженным бумагам игнорируются ==")
import datetime as _dt  # noqa: E402
from portfolio_returns import Trade, apply_corrections, reconstruct_positions  # noqa: E402

SYNC_NOTE = ("Корректировка количества на основе указанного баланса "
             "({} шт.) в загружаемом отчете {}. Чтобы убрать корректировку "
             "и получить более точные расчеты, добавьте фактические сделки.")

def mk_trade(op, qty, price, date, note="", ticker="FXUS", cur="RUB", name="FinEx USA"):
    amt = (qty * price) * (-1 if op == "Продажа" else 1)
    if op == "Корректировка":
        amt = -qty * price
    t = Trade(ticker=ticker, name=name, operation=op, date=date,
              qty=qty, price=price, nominal=None, nkd=None, commission=0.0,
              amount=amt, amount_no_comm=amt, currency=cur, note=note)
    t.rub_amount = amt
    return t

raw = [
    mk_trade("Покупка", 1504, 60.0, _dt.date(2022, 1, 21)),
    # фиктивная синхронизация: FXUS заморожен, счёт ВКС не грузится в IntelInvest
    mk_trade("Корректировка", 1089, 59.56, _dt.date(2026, 4, 10),
             note=SYNC_NOTE.format("415.00", "10.04.2026")),
    # реальная синхронизация по обычной российской бумаге (кейс MDMG) — нужна
    mk_trade("Покупка", 100, 900.0, _dt.date(2025, 1, 15), ticker="MDMG",
             name="Мать и Дитя"),
    mk_trade("Корректировка", 5, 1000.0, _dt.date(2026, 5, 1), ticker="MDMG",
             name="Мать и Дитя", note=SYNC_NOTE.format("105.00", "01.05.2026")),
]
fixed, corr_log = apply_corrections(list(raw))
check("Корректировка по замороженной FXUS удалена, по MDMG осталась",
      not any(t.ticker == "FXUS" and t.operation == "Корректировка" for t in fixed)
      and any(t.ticker == "MDMG" and t.operation == "Корректировка" for t in fixed))
check("лог ignored_blocked_corrections с причиной и подтверждением владельца",
      any(c["type"] == "ignored_blocked_corrections"
          and "подтверждено владельцем" in c["reason"] for c in corr_log))
pos = reconstruct_positions([t for t in fixed if t.ticker == "FXUS"],
                            as_of=_dt.date(2026, 7, 2))
check("qty FXUS = 1504 (ложное списание не применилось)",
      abs(pos[("FXUS", "RUB")].qty - 1504) < 1e-9)
raw_ru_only = [mk_trade("Покупка", 10, 60.0, _dt.date(2022, 1, 21),
                        ticker="SBER", name="Сбербанк")]
_, log2 = apply_corrections(raw_ru_only)
check("без blocked-корректировок лог пуст",
      not any(c["type"] == "ignored_blocked_corrections" for c in log2))

print("== 12. e2e assemble: status/status_summary в снапшоте ==")
portfolio = {
    "stocks": [],
    "bonds": [{
        "Тикер": TEST_DISTR, "Название": "БорецКЗО26",
        "Текущая стоимость": 156_441.18, "Итого без ИИСа": 156_441.18,
        "Итого на ИИС": 0.0, "Всего": 200, "ИИС": 0,
        "Номинал": 1000.0, "Валюта номинала": "USD",
    }],
    "other_positions": [],
    "metrics": {},
}
snap = assemble(portfolio, None, None, {})
h = next(x for x in snap["holdings"] if x["ticker"] == TEST_DISTR)
check("holding.status = distressed", h["status"] == "distressed")
check("holding.is_blocked = False (schema 2.0 сохранён)",
      h["is_blocked"] is False)
check("status_summary присутствует", snap.get("status_summary") is not None)
check("distressed стоимость > 0",
      snap["status_summary"]["by_status"]["distressed"]["value_rub"] > 0)
check("info-флаг distressed_positions",
      any(f.get("code") == "distressed_positions"
          for f in snap["data_quality_flags"]))
check("is_blocked консистентен со status по всем holdings",
      all((x["status"] == "blocked") == x["is_blocked"]
          for x in snap["holdings"]))

print("== 12а. e2e assemble с returns: замороженный фонд в holdings и сводке ==")
snap2 = assemble(portfolio, returns_blocked, None, {})
fx = next((x for x in snap2["holdings"] if x["ticker"] == "FXUS"), None)
check("FXUS в holdings", fx is not None)
check("FXUS: status=blocked, is_blocked=True",
      fx and fx["status"] == "blocked" and fx["is_blocked"] is True)
check("сводка: blocked включает FXUS+RSHA (89578+50562)",
      abs(snap2["status_summary"]["by_status"]["blocked"]["value_rub"]
          - 140140.0) < 0.01)
check("активная SBER из returns НЕ попала через blocked-билдер",
      not any(x["ticker"] == "SBER" and x.get("asset_type") == "other"
              for x in snap2["holdings"]))

print("== 13. e2e assemble без balance-файла: status_summary = null ==")
snap = assemble(None, {"snapshot_current": {}}, None, {})
check("holdings null → status_summary null",
      snap["holdings"] is None and snap["status_summary"] is None)

print(f"\n{'='*50}\nPASSED: {PASSED}  FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
