#!/usr/bin/env python3
"""Контракт quotes@1: нормализация ответа ISS по доске → items (без сети).

moex_quotes.board_to_quotes_items — единственное место, где ответ Мосбиржи превращается в
формат цен, общий для hub-api, вьюера (RebalanceEngine.applyQuotes) и советника
(gate_aware_sizing --auto --quotes). Правило цены: LAST → MARKETPRICE → PREVPRICE
(price_kind last / market / prev_close), ts = SYSTIME (для prev_close — PREVDATE), бумага
без цены в items не попадает. Фикстура tools/tests/fixtures/iss/tqbr.json — живой срез ISS
13.10.2026 14:08 (общая с тестами сервера). Доски облигаций (TQOB/TQCB) несут ещё isin, accrued_int, face_value, face_unit — фикстура
tqob.json (живой срез 11.11.2026, урезанные колонки), один разбор у hub-api и загрузчика. План: tools/design-reference/live-prices-plan.md §2.1.
Запуск: python3 tools/tests/test_quotes_contract.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "_shared-references"))

import moex_quotes as mq  # noqa: E402

FIXTURE = REPO / "tools/tests/fixtures/iss/tqbr.json"

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


def iss(rows):
    """rows: (secid, lot, prevprice, prevdate, last, marketprice, systime) → ответ ISS в формате доски."""
    return {
        "securities": {"columns": ["SECID", "LOTSIZE", "PREVPRICE", "PREVDATE"],
                       "data": [[r[0], r[1], r[2], r[3]] for r in rows]},
        "marketdata": {"columns": ["SECID", "LAST", "MARKETPRICE", "LCURRENTPRICE", "UPDATETIME", "SYSTIME", "TRADINGSTATUS"],
                       "data": [[r[0], r[4], r[5], r[4], "10:00:00", r[6], "T"] for r in rows]},
    }


print("== 1. Фикстура ISS (живой срез 13.10) ==")
data = json.loads(FIXTURE.read_text(encoding="utf-8"))
items = mq.board_to_quotes_items("TQBR", data)
n_sec = len(data["securities"]["data"])
check(f"бумаг без цены отброшено, остальные на месте ({len(items)} из {n_sec})", 0 < len(items) <= n_sec)
for t in ("SBER", "TMON", "XXXXXX"):
    check(f"{t} есть в items", t in items)
sber = items["SBER"]
check("SBER: цена из LAST, price_kind last", sber["price"] == 287.21 and sber["price_kind"] == "last", sber)
check("SBER: ts = SYSTIME, лот, prev_close, доска",
      sber["ts"] == "2026-10-13 14:08:33" and sber["lot_size"] == 1 and sber["prev_close"] == 285.29 and sber["board"] == "TQBR", sber)
check("форма item: ровно поля контракта",
      set(sber) == {"price", "price_kind", "lot_size", "board", "ts", "prev_close"}, sorted(sber))
check("у каждого item цена > 0 и допустимый price_kind",
      all(i["price"] > 0 and i["price_kind"] in ("last", "market", "prev_close") for i in items.values()))

print("== 2. Ветки правила цены (синтетика) ==")
S = iss([
    ("AAA", 10, 100.0, "2026-10-12", 105.5, 104.0, "2026-10-13 12:00:00"),   # есть LAST
    ("BBB", 1, 50.0, "2026-10-12", None, 51.2, "2026-10-13 12:01:00"),        # нет LAST → MARKETPRICE
    ("CCC", 100, 20.0, "2026-10-12", None, None, "2026-10-13 12:02:00"),      # нет обеих → PREVPRICE
    ("DDD", 1, None, None, None, None, None),                                  # цены нет вовсе
    ("EEE", 1, 30.0, "2026-10-12", 0, 0, "2026-10-13 12:03:00"),              # нули = нет цены
    ("FFF", None, 40.0, "2026-10-12", 41.0, None, None),                       # нет лота и SYSTIME
])
it = mq.board_to_quotes_items("TQBR", S)
check("LAST → last", it["AAA"]["price"] == 105.5 and it["AAA"]["price_kind"] == "last" and it["AAA"]["ts"] == "2026-10-13 12:00:00", it["AAA"])
check("нет LAST → MARKETPRICE, market", it["BBB"]["price"] == 51.2 and it["BBB"]["price_kind"] == "market", it["BBB"])
check("нет LAST и MARKETPRICE → PREVPRICE, prev_close, ts = PREVDATE",
      it["CCC"]["price"] == 20.0 and it["CCC"]["price_kind"] == "prev_close" and it["CCC"]["ts"] == "2026-10-12", it["CCC"])
check("совсем без цены — не включается", "DDD" not in it)
check("нулевые LAST/MARKETPRICE = нет цены → PREVPRICE", it["EEE"]["price_kind"] == "prev_close" and it["EEE"]["price"] == 30.0, it["EEE"])
check("нет лота → lot_size None; нет SYSTIME → ts = PREVDATE",
      it["FFF"]["lot_size"] is None and it["FFF"]["ts"] == "2026-10-12", it["FFF"])
check("lot_size — целое", it["AAA"]["lot_size"] == 10 and isinstance(it["AAA"]["lot_size"], int))
check("prev_close берётся из PREVPRICE и при last", it["AAA"]["prev_close"] == 100.0)
check("пустой ответ → пустые items", mq.board_to_quotes_items("TQBR", {}) == {})

print("== 3. Запрос на доску и сборка quotes@1 ==")
check("URL доски: колонки и iss.only как в плане",
      "iss.only=securities,marketdata" in mq.QUOTES_BOARD_COLUMNS
      and "securities.columns=SECID,LOTSIZE,PREVPRICE,PREVDATE" in mq.QUOTES_BOARD_COLUMNS
      and "marketdata.columns=SECID,LAST,MARKETPRICE,LCURRENTPRICE,UPDATETIME,SYSTIME,TRADINGSTATUS" in mq.QUOTES_BOARD_COLUMNS)
urls = []
orig = mq._get_json
mq._get_json = lambda url, timeout=15, retries=2: (urls.append(url), data)[1]
try:
    q = mq.fetch_boards(("TQBR",))
finally:
    mq._get_json = orig
check("fetch_boards: один запрос на доску, путь engines/stock/markets/shares/boards/TQBR",
      len(urls) == 1 and "/engines/stock/markets/shares/boards/TQBR/securities.json?" in urls[0], urls)
check("quotes@1: schema, source, задержка, stale, boards",
      q["schema"] == "quotes@1" and q["source"] == "moex_iss" and q["delayed_min"] == 15 and q["stale"] is False
      and list(q["boards"]) == ["TQBR"] and q["boards"]["TQBR"]["stale"] is False and q["fetched_at"], q.get("boards"))
check("quotes@1: items совпали с нормализацией", q["items"] == items)

print("== 4. Доска облигаций (фикстура ISS 11.11, урезанные колонки) ==")
BF = REPO / "tools/tests/fixtures/iss/tqob.json"
bdata = json.loads(BF.read_text(encoding="utf-8"))
bi = mq.board_to_quotes_items("TQOB", bdata)
o = bi["SU26207RMFS9"]
check("ОФЗ: цена LAST (% номинала), isin, НКД, номинал, валюта номинала",
      o["price"] == 98.975 and o["price_kind"] == "last" and o["isin"] == "RU000A0JS3W6"
      and o["accrued_int"] == 22.11 and o["face_value"] == 1000 and o["face_unit"] == "SUR", o)
check("форма item облигации: поля акции + isin/accrued_int/face_value/face_unit/currency_id + yield_pct/yield_offer_pct/duration_days",
      set(o) == {"price", "price_kind", "lot_size", "board", "ts", "prev_close", "isin", "accrued_int", "face_value", "face_unit", "currency_id",
                 "yield_pct", "yield_offer_pct", "duration_days"}, sorted(o))
check("ОФЗ: YIELD биржи 13.74 %, дюрация 83 дн., к оферте null",
      o["yield_pct"] == 13.74 and o["duration_days"] == 83 and o["yield_offer_pct"] is None, o)
check("валютная облигация (цена MARKETPRICE): YIELD 6.36 %, дюрация 787 дн.",
      bi["RU000A10DQB6"]["yield_pct"] == 6.36 and bi["RU000A10DQB6"]["duration_days"] == 787, bi["RU000A10DQB6"])
pc = mq.board_to_quotes_items("TQOB", {"securities": {"columns": ["SECID", "PREVPRICE", "PREVDATE"], "data": [["X1", 97.0, "2026-11-10"]]},
      "marketdata": {"columns": ["SECID", "YIELD", "DURATION"], "data": [["X1", 12.5, 300]]}})
check("цена — вчерашнее закрытие: доходность/дюрация не отдаются (устарели)", "yield_pct" not in pc["X1"] and "duration_days" not in pc["X1"], pc)
zero = mq.board_to_quotes_items("TQOB", {"securities": {"columns": ["SECID", "PREVPRICE"], "data": [["X2", 97.0]]},
      "marketdata": {"columns": ["SECID", "LAST", "YIELD", "DURATION"], "data": [["X2", 97.5, 0, 0]]}})
check("YIELD/DURATION = 0 → null (нет данных), не нулевая доходность", zero["X2"]["yield_pct"] is None and zero["X2"]["duration_days"] is None, zero)
check("бумага без цены (SU26231) в items нет", "SU26231RMFS9" not in bi)
cny = bi["RU000A10DQB6"]
check("валютная облигация: нет LAST → MARKETPRICE, face_unit CNY, номинал 10000",
      cny["price_kind"] == "market" and cny["face_unit"] == "CNY" and cny["face_value"] == 10000, cny)
check("доска акций: полей облигации нет (форма не менялась)", "isin" not in sber and "accrued_int" not in sber)
check("ISS-колонки облигаций: ISIN, ACCRUEDINT, FACEVALUE, FACEUNIT, CURRENCYID, YIELD, DURATION запрошены",
      all(c in mq.QUOTES_BOND_COLUMNS for c in ("ISIN", "ACCRUEDINT", "FACEVALUE", "FACEUNIT", "CURRENCYID", "YIELD", "DURATION")))
cb = mq.board_to_quotes_items("TQOB", {"securities": {"columns": ["SECID", "ISIN", "PREVPRICE", "ACCRUEDINT", "FACEVALUE", "FACEUNIT", "CURRENCYID"],
      "data": [["RU000A10FAK6", "RU000A10FAK6", 96.65, 4204.909285, 10000, "CNY", "SUR"]]}, "marketdata": {"columns": ["SECID"], "data": []}})
check("валютная облигация: currency_id SUR (НКД в рублях), номинал CNY", cb["RU000A10FAK6"]["currency_id"] == "SUR"
      and cb["RU000A10FAK6"]["face_unit"] == "CNY" and cb["RU000A10FAK6"]["accrued_int"] == 4204.909285, cb)
urls = []
mq._get_json = lambda url, timeout=15, retries=2: (urls.append(url), bdata)[1]
try:
    qb = mq.fetch_boards(("TQOB",))
finally:
    mq._get_json = orig
check("fetch_boards(TQOB): путь markets/bonds/boards/TQOB и колонки облигаций",
      len(urls) == 1 and "/markets/bonds/boards/TQOB/" in urls[0] and "ACCRUEDINT" in urls[0], urls)
check("quotes@1 по облигациям: items = нормализация", qb["items"] == bi)

print("== 4б. Блок fx: курс ЦБ (XML_daily, фикстура без сети) ==")
CBR_XML = (REPO / "tools/tests/fixtures/cbr/xml_daily.xml").read_text(encoding="windows-1251")
fxm = mq.cbr_xml_to_fx(CBR_XML)
check("cbr_xml_to_fx: все валюты среза ЦБ 11.11.2026, дата ISO; KZT за 100 → курс за 1 (15,9 / 100)",
      abs(fxm.pop("KZT") - 0.159) < 1e-12 and abs(fxm.pop("JPY") - 0.522096) < 1e-12
      and fxm == {"USD": 82.5486, "EUR": 92.3966, "CNY": 12.3845, "date": "2026-11-11"}, fxm)
fxall = mq.cbr_xml_to_fx(CBR_XML)
check("cbr_xml_to_fx(currencies=[KZT]): только KZT и date, Nominal 100 учтён",
      mq.cbr_xml_to_fx(CBR_XML, ["KZT"]) == {"KZT": fxall["KZT"], "date": "2026-11-11"} and abs(fxall["KZT"] - 0.159) < 1e-12)
check("cbr_xml_to_fx: валюты нет у ЦБ → None; найденные из запрошенных остаются",
      mq.cbr_xml_to_fx(CBR_XML, ["XXX"]) is None and mq.cbr_xml_to_fx(CBR_XML, ["XXX", "USD"]) == {"USD": 82.5486, "date": "2026-11-11"})
check("cbr_xml_to_fx: Value делится на Nominal (CNY за 10 единиц → курс за 1)",
      abs(mq.cbr_xml_to_fx(CBR_XML.replace("<CharCode>CNY</CharCode><Nominal>1</Nominal>", "<CharCode>CNY</CharCode><Nominal>10</Nominal>"))["CNY"] - 1.23845) < 1e-9)
check("cbr_xml_to_fx: нет валюты или даты → None", mq.cbr_xml_to_fx("<ValCurs Date=\"11.11.2026\"></ValCurs>") is None and mq.cbr_xml_to_fx("") is None)
mq._get_json = lambda url, timeout=15, retries=2: bdata
_fxreq = []
mq.fetch_fx = lambda currencies=None, timeout=15: (_fxreq.append(currencies), mq.cbr_xml_to_fx(CBR_XML, currencies))[1]
try:
    qfx = mq.fetch_boards(("TQOB",), fx=["USD", "KZT"])
    qnofx = mq.fetch_boards(("TQOB",))
finally:
    mq._get_json = orig
check("fetch_boards(TQOB, fx=[USD,KZT]): блок fx только с запрошенными валютами",
      qfx.get("fx") == {"USD": 82.5486, "KZT": fxall["KZT"], "date": "2026-11-11"}, qfx.get("fx"))
check("fetch_boards без fx: блока fx нет, к ЦБ не ходим", "fx" not in qnofx and _fxreq == [["USD", "KZT"]], _fxreq)

print("== 5. hub-api (iss_board_to_items) даёт то же, что загрузчик ==")
sys.path.insert(0, str(REPO / "tools/hosting/api"))
try:
    import server as srv  # noqa: E402
    check("облигации: items hub-api = items загрузчика", srv.iss_board_to_items("TQOB", bdata) == bi)
    check("акции: items hub-api = items загрузчика", srv.iss_board_to_items("TQBR", data) == items)
    _bu = srv.MOEX_ISS.format(market="bonds", board="TQOB", seccols=srv.MOEX_SEC_COLS_BOND, mdbond=srv.MOEX_MD_BOND)
    check("URL облигационной доски несёт колонки НКД/номинала и YIELD/DURATION; у акций YIELD нет",
          "ACCRUEDINT" in _bu and "YIELD" in _bu and "DURATION" in _bu
          and "YIELD" not in srv.MOEX_ISS.format(market="shares", board="TQBR", seccols=srv.MOEX_SEC_COLS, mdbond=""))
    check("cbr_xml_to_fx hub-api = загрузчик (все валюты и выборка)",
          srv.cbr_xml_to_fx(CBR_XML) == fxall and srv.cbr_xml_to_fx(CBR_XML, ["KZT"]) == mq.cbr_xml_to_fx(CBR_XML, ["KZT"]))
    fxm = fxall
    calls = []
    srv._FX_CACHE.clear()
    srv.cbr_fetch_xml = lambda: (calls.append(1), CBR_XML)[1]
    srv.moex_fetch_board = lambda board: bdata if board in srv.MOEX_BOND_BOARDS else data
    srv._MOEX_CACHE.clear()
    qs1 = srv.moex_quotes(["TQOB"], fx=["USD", "KZT"])
    qs2 = srv.moex_quotes(["TQOB"], fx=["KZT"])
    check("quotes@1 hub-api: fx=USD,KZT отдаёт только их (KZT за 100 → 0,159); один запрос к ЦБ на два вызова (кэш на сутки), фильтр на выдаче",
          qs1.get("fx") == {"USD": 82.5486, "KZT": fxall["KZT"], "date": "2026-11-11"}
          and qs2.get("fx") == {"KZT": fxall["KZT"], "date": "2026-11-11"} and len(calls) == 1, (qs1.get("fx"), qs2.get("fx"), calls))
    srv._MOEX_CACHE.clear()
    check("без параметра fx блока нет (и на облигациях); к ЦБ не ходим", "fx" not in srv.moex_quotes(["TQOB"]) and len(calls) == 1)
    check("fx с валютой, которой нет у ЦБ: блока нет", "fx" not in srv.moex_quotes(["TQOB"], fx=["XXX"]))
    check("parse_fx_param: коды нормализуются и дедуплицируются",
          srv.parse_fx_param("usd, kzt,USD") == ["USD", "KZT"] and srv.parse_fx_param(None) is None)
    _bad = []
    for raw in ("", "US", "USDD", "U$D", "1AB", ",".join(f"A{c}{d}" for c in "ABCDEF" for d in "AB")):
        try:
            srv.parse_fx_param(raw)
            _bad.append(raw)
        except ValueError:
            pass
    check("parse_fx_param: пусто, не 3 буквы, не буквы, >10 кодов → ValueError", not _bad, _bad)
    srv._MOEX_CACHE.clear()
    srv._FX_CACHE.clear()
    srv.cbr_fetch_xml = lambda: (_ for _ in ()).throw(OSError("cbr.ru недоступен"))
    srv._MOEX_CACHE.clear()
    check("ЦБ недоступен, кэша нет: quotes@1 без fx, не падает", "fx" not in srv.moex_quotes(["TQOB"], fx=["USD"]))
    srv._FX_CACHE["e"] = {"fx": fxm, "fetched": time.time() - 2 * 24 * 3600}
    srv._MOEX_CACHE.clear()
    check("ЦБ недоступен, кэш старше суток моложе 7 дней: отдаётся прошлый курс", srv.moex_quotes(["TQOB"], fx=["USD", "EUR", "CNY"]).get("fx") == {k: fxall[k] for k in ("USD", "EUR", "CNY", "date")})
except ImportError as e:
    check("импорт server.py", False, str(e))

print(f"\nquotes_contract: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
