#!/usr/bin/env python3
"""Тесты загрузчика рядов рынка market_series.py (кэш, догрузка хвостов, флаги, пагинация).

Полностью офлайн: фетчер инжектируется, кэш — во временном каталоге, urlopen подменяется.
Запуск: python3 skills/portfolio-data-loader/tests/test_market_series.py
"""
import datetime as dt
import io
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import market_series as ms  # noqa: E402
from market_series import Series, get_series, get_many, lookup  # noqa: E402

PASSED = FAILED = 0


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  ✓ {name}")
    else:
        FAILED += 1
        print(f"  ✗ {name}  {detail}")


D = dt.date


class FakeFetcher:
    """Отдаёт по точке на каждый будний день; считает вызовы и запомненные диапазоны."""

    def __init__(self, value=lambda d: 100.0 + d.toordinal() % 50, meta=None, fail=False):
        self.calls = []
        self.value = value
        self.meta = meta
        self.fail = fail
        self.override = {}

    def __call__(self, kind, secid, a, b):
        self.calls.append((kind, secid, a, b))
        if self.fail:
            raise ConnectionError("нет связи")
        out, d = [], a
        while d <= b:
            if d.weekday() < 5:
                out.append((d.isoformat(), self.override.get(d.isoformat(), self.value(d))))
            d += dt.timedelta(days=1)
        return (out, self.meta) if self.meta is not None else out


def tmp():
    return Path(tempfile.mkdtemp(prefix="ms_test_"))


print("1. кэш: второй вызов с тем же диапазоном не идёт в сеть")
c, f = tmp(), FakeFetcher()
s1 = get_series("share", "SBER", D(2026, 9, 1), D(2026, 9, 30), cache_dir=c, fetcher=f)
s2 = get_series("share", "SBER", D(2026, 9, 1), D(2026, 9, 30), cache_dir=c, fetcher=f)
s3 = get_series("share", "SBER", D(2026, 9, 10), D(2026, 9, 20), cache_dir=c, fetcher=f)
check("первый вызов — один поход в fetcher", len(f.calls) == 1, str(f.calls))
check("второй и вложенный диапазон — без сети", len(f.calls) == 1)
check("ряд непуст, 22 будних дня сентября", len(s1.points) == 22, str(len(s1.points)))
check("повтор даёт тот же ряд", s1.points == s2.points)
check("вложенный диапазон обрезан по датам",
      s3.points[0][0] == "2026-09-10" and s3.points[-1][0] == "2026-09-18", str(s3.points[:1]))
check("точки по возрастанию", [p[0] for p in s1.points] == sorted(p[0] for p in s1.points))

print("2. расширение вправо — хвост + 7 дней; влево — только голова")
c, f = tmp(), FakeFetcher()
get_series("share", "SBER", D(2026, 9, 1), D(2026, 9, 15), cache_dir=c, fetcher=f)
s = get_series("share", "SBER", D(2026, 9, 1), D(2026, 9, 30), cache_dir=c, fetcher=f)
check("вправо: второй вызов докачивает с covered_to−7д",
      f.calls[1][2:] == (D(2026, 9, 8), D(2026, 9, 30)), str(f.calls[1]))
check("вправо: слиянный ряд полный (22 точки)", len(s.points) == 22, str(len(s.points)))
s = get_series("share", "SBER", D(2026, 8, 15), D(2026, 9, 30), cache_dir=c, fetcher=f)
check("влево: докачана только голова до covered_from−1",
      f.calls[2][2:] == (D(2026, 8, 15), D(2026, 8, 31)), str(f.calls[2]))
check("влево: вызовов ровно 3", len(f.calls) == 3)
check("влево: ряд начинается с 17 авг (понедельник)", s.points[0][0] == "2026-08-17", s.points[0][0])
s = get_series("share", "SBER", D(2026, 8, 1), D(2026, 10, 7), cache_dir=c, fetcher=f)
check("в обе стороны сразу — два похода", len(f.calls) == 5, str(len(f.calls)))
check("в обе стороны: нет дубликатов дат",
      len({p[0] for p in s.points}) == len(s.points))

print("3. перезапрос свежих 7 дней перезаписывает исправленное значение")
c, f = tmp(), FakeFetcher()
get_series("index", "MCFTR", D(2026, 9, 1), D(2026, 9, 15), cache_dir=c, fetcher=f)
before = dict(get_series("index", "MCFTR", D(2026, 9, 1), D(2026, 9, 15), cache_dir=c, fetcher=f).points)
f.override["2026-09-14"] = 99999.0   # ISS поправил закрытие внутри последних 7 дней
f.override["2026-09-02"] = 88888.0   # старое значение — перезапрашиваться не должно
s = get_series("index", "MCFTR", D(2026, 9, 1), D(2026, 9, 20), cache_dir=c, fetcher=f)
got = dict(s.points)
check("свежее значение перезаписано", got["2026-09-14"] == 99999.0, str(got.get("2026-09-14")))
check("старое значение не тронуто (вне окна 7 дней)", got["2026-09-02"] == before["2026-09-02"])

print("4. offline")
c, f = tmp(), FakeFetcher()
s = get_series("share", "SBER", D(2026, 9, 1), D(2026, 9, 30), cache_dir=c, offline=True, fetcher=f)
check("без кэша: пусто", s.points == [])
check("без кэша: флаг offline", any(x.startswith("offline") for x in s.flags), str(s.flags))
check("без кэша: fetcher не вызывался", f.calls == [])
get_series("share", "SBER", D(2026, 9, 1), D(2026, 9, 15), cache_dir=c, fetcher=f)
n = len(f.calls)
s = get_series("share", "SBER", D(2026, 9, 1), D(2026, 9, 30), cache_dir=c, offline=True, fetcher=f)
check("частичное покрытие: флаг с диапазоном покрытия",
      s.flags == ["offline: покрытие 2026-09-01..2026-09-15 меньше запроса"], str(s.flags))
check("частичное покрытие: отдаёт что есть", len(s.points) == 11, str(len(s.points)))
check("offline не ходит в fetcher", len(f.calls) == n)
s = get_series("share", "SBER", D(2026, 9, 2), D(2026, 9, 10), cache_dir=c, offline=True, fetcher=f)
check("offline в покрытом диапазоне — без флагов", s.flags == [] and len(s.points) == 7, str(s.flags))

print("5. сбой fetcher при наличии кэша — кэш + флаг, без исключения")
c, f = tmp(), FakeFetcher()
get_series("share", "SBER", D(2026, 9, 1), D(2026, 9, 15), cache_dir=c, fetcher=f)
f.fail = True
try:
    s = get_series("share", "SBER", D(2026, 9, 1), D(2026, 9, 30), cache_dir=c, fetcher=f)
    raised = False
except Exception:
    raised = True
check("исключение наружу не вышло", not raised)
check("флаг «сеть: …»", len(s.flags) == 1 and s.flags[0].startswith("сеть:"), str(s.flags))
check("отдан кэш (11 точек)", len(s.points) == 11, str(len(s.points)))
s = get_series("share", "SBER", D(2026, 9, 1), D(2026, 9, 15), cache_dir=c, fetcher=f)
check("в покрытом диапазоне сбой неважен — без флагов", s.flags == [])
s = get_series("share", "GAZP", D(2026, 9, 1), D(2026, 9, 15), cache_dir=tmp(), fetcher=f)
check("сбой без кэша: пустые points + флаг", s.points == [] and s.flags and s.flags[0].startswith("сеть:"))
check("покрытие после сбоя не расширено",
      json.loads(next(c.glob("share__SBER.json")).read_text())["covered_to"] == "2026-09-15")

print("6. валюта и единицы из meta")
c = tmp()
f = FakeFetcher(meta={"currency": "CNY"})
s = get_series("index", "RUCNYTR", D(2026, 9, 1), D(2026, 9, 10), cache_dir=c, fetcher=f)
check("Series.currency = CNY", s.currency == "CNY", str(s.currency))
raw = json.loads((c / "index__RUCNYTR.json").read_text())
check("валюта в файле кэша", raw["currency"] == "CNY")
check("поля файла кэша", {"kind", "secid", "unit", "currency", "source", "points",
                          "covered_from", "covered_to", "fetched_at"} <= set(raw), str(set(raw)))
f2 = FakeFetcher()
s = get_series("index", "RUCNYTR", D(2026, 9, 1), D(2026, 9, 30), cache_dir=c, fetcher=f2)
check("валюта переживает догрузку без meta", s.currency == "CNY")
s = get_series("rate_index", "RUSFAR", D(2026, 9, 1), D(2026, 9, 10), cache_dir=c, fetcher=FakeFetcher())
check("rate_index → unit pct_annual", s.unit == "pct_annual", s.unit)
s = get_series("index", "MCFTR", D(2026, 9, 1), D(2026, 9, 10), cache_dir=c, fetcher=FakeFetcher())
check("index → unit points", s.unit == "points")
s = get_series("key_rate", "KEYRATE", D(2026, 9, 1), D(2026, 9, 10), cache_dir=c, fetcher=FakeFetcher())
check("key_rate: source cbr, pct_annual", s.source == "cbr" and s.unit == "pct_annual")
s = get_series("fx_cbr", "USD", D(2026, 9, 1), D(2026, 9, 10), cache_dir=c, fetcher=FakeFetcher())
check("fx_cbr: source cbr, rub_per_unit", s.source == "cbr" and s.unit == "rub_per_unit")

print("7. lookup на выходных и за пределами")
ser = Series("share", "X", "rub", "RUB",
             points=[("2026-09-04", 10.0), ("2026-09-07", 11.0), ("2026-09-08", 12.0)])
sat, sun = D(2026, 9, 5), D(2026, 9, 6)
check("prev: суббота → пятница", lookup(ser, sat, "prev") == 10.0)
check("next: суббота → понедельник", lookup(ser, sat, "next") == 11.0)
check("prev: воскресенье → пятница", lookup(ser, sun) == 10.0)
check("точное совпадение — prev и next", lookup(ser, D(2026, 9, 7), "prev") == 11.0
      and lookup(ser, D(2026, 9, 7), "next") == 11.0)
check("prev до начала ряда → None", lookup(ser, D(2026, 9, 1), "prev") is None)
check("next после конца ряда → None", lookup(ser, D(2026, 9, 9), "next") is None)
check("prev после конца → последняя точка", lookup(ser, D(2026, 9, 20), "prev") == 12.0)
check("next до начала → первая точка", lookup(ser, D(2026, 9, 1), "next") == 10.0)
check("пустой ряд → None", lookup(Series("share", "X", "rub", None), sat) is None)
try:
    lookup(ser, sat, "sideways")
    check("неверное direction → ValueError", False)
except ValueError:
    check("неверное direction → ValueError", True)

print("8. неизвестный kind")
try:
    get_series("bondz", "X", D(2026, 9, 1), D(2026, 9, 2), cache_dir=tmp(), fetcher=FakeFetcher())
    check("get_series: ValueError", False)
except ValueError as e:
    check("get_series: ValueError", "bondz" in str(e))
try:
    get_many([("share", "SBER"), ("nope", "X")], D(2026, 9, 1), D(2026, 9, 2),
             cache_dir=tmp(), fetcher=FakeFetcher())
    check("get_many: ValueError", False)
except ValueError:
    check("get_many: ValueError", True)
r = get_many([("share", "SBER"), ("index", "MCFTR")], D(2026, 9, 1), D(2026, 9, 4),
             cache_dir=tmp(), fetcher=FakeFetcher())
check("get_many: ключи kind:secid", set(r) == {"share:SBER", "index:MCFTR"}, str(set(r)))

print("9. атомарность записи")
c, f = tmp(), FakeFetcher()
get_series("share", "SBER", D(2026, 9, 1), D(2026, 9, 15), cache_dir=c, fetcher=f)
get_series("share", "SBER", D(2026, 9, 1), D(2026, 9, 30), cache_dir=c, fetcher=f)
names = sorted(p.name for p in c.iterdir())
check("нет *.tmp после записи", not any(n.endswith(".tmp") for n in names), str(names))
check("в каталоге один файл ряда", names == ["share__SBER.json"], str(names))
check("файл — валидный JSON", isinstance(json.loads((c / names[0]).read_text()), dict))
(c / "share__SBER.json").write_text("{битый json")
s = get_series("share", "SBER", D(2026, 9, 1), D(2026, 9, 15), cache_dir=c, fetcher=f)
check("битый кэш → перекачка + флаг, без падения",
      len(s.points) == 11 and any("повреждён" in x for x in s.flags), str(s.flags))

print("10. пагинация сетевого фетчера (подмена urlopen)")


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def page(n, start_day):
    rows = []
    d = dt.date(2026, 1, 1) + dt.timedelta(days=start_day)
    for i in range(n):
        rows.append([(d + dt.timedelta(days=i)).isoformat(), 200.0 + i])
    return FakeResp(json.dumps({"history": {"data": rows}}).encode())


urls = []
pages = [page(100, 0), page(93, 100)]


def fake_urlopen(url, *a, **kw):
    urls.append(url)
    return pages[len(urls) - 1]


with mock.patch.object(ms.urllib.request, "urlopen", fake_urlopen):
    rows, meta = ms.fetch_iss_history("share", "SBER", D(2026, 1, 1), D(2026, 10, 6))
check("193 точки из двух страниц", len(rows) == 193, str(len(rows)))
check("ровно два запроса", len(urls) == 2, str(len(urls)))
check("второй запрос со start=100", "start=100" in urls[1], urls[1])
check("путь TQBR и колонки без CURRENCYID",
      "boards/TQBR/securities/SBER.json" in urls[0] and "CURRENCYID" not in urls[0], urls[0])

# индекс: колонка CURRENCYID, None-значения отбрасываются, валюта уходит в meta
urls.clear()
rows_idx = json.dumps({"history": {"data": [
    ["2026-09-01", 118.0, "CNY"], ["2026-09-02", None, "CNY"], ["2026-09-03", 119.5, "CNY"]]}}).encode()
with mock.patch.object(ms.urllib.request, "urlopen",
                       lambda url, *a, **kw: (urls.append(url), FakeResp(rows_idx))[1]):
    rows, meta = ms.fetch_iss_history("index", "RUCNYTR", D(2026, 9, 1), D(2026, 9, 3))
check("индекс: None в CLOSE отброшен", [r[0] for r in rows] == ["2026-09-01", "2026-09-03"], str(rows))
check("индекс: валюта в meta", meta == {"currency": "CNY"}, str(meta))
check("индекс: запрошен CURRENCYID и путь index",
      "CURRENCYID" in urls[0] and "markets/index/securities/RUCNYTR.json" in urls[0], urls[0])

# сквозной вызов get_series с дефолтным фетчером и подменённым urlopen
urls.clear()
c = tmp()
with mock.patch.object(ms.urllib.request, "urlopen",
                       lambda url, *a, **kw: (urls.append(url), FakeResp(rows_idx))[1]):
    s = get_series("index", "RUCNYTR", D(2026, 9, 1), D(2026, 9, 3), cache_dir=c)
check("дефолтный фетчер: валюта CNY попала в Series", s.currency == "CNY" and len(s.points) == 2)

print("11. облигации: bond / bond_cf (AIR-1b)")
ms._BOARD_CACHE.clear()


def fake_iss(url, timeout=20):
    if "iss.only=boards" in url:
        return {"boards": {"data": [["LIQB", "mamc", 0], ["TQCB", "bonds", 1]]}}
    if "/history/" in url:
        assert "boards/TQCB/" in url, url
        return {"history": {"data": [
            ["2026-09-01", 98.4, 98.24, 18.86, 1000, "SUR"],
            ["2026-09-02", None, 98.28, 19.56, 1000, "SUR"],      # нет CLOSE → LEGALCLOSEPRICE
            ["2026-09-03", None, None, 20.26, 1000, "SUR"]]}}     # нет цены → пропуск
    if "bondization" in url:
        return {"coupons": {"data": [["2026-08-05", 20.96, "RUB"], ["2026-09-04", 20.96, "RUB"],
                                     ["2026-10-04", None, "RUB"]]},
                "amortizations": {"data": [["2026-09-04", 1000.0, "RUB", "maturity"]]}}
    raise AssertionError(url)


with mock.patch.object(ms, "_http_json", fake_iss):
    pts, meta = ms.fetch_bond_history("RU000A10B2F7", D(2026, 9, 1), D(2026, 9, 3))
    check("bond: грязная цена = CLOSE%·номинал + НКД", pts[0] == ("2026-09-01", 98.4 * 10 + 18.86), str(pts))
    check("bond: без CLOSE — LEGALCLOSEPRICE; без цены — пропуск", len(pts) == 2 and abs(pts[1][1] - (982.8 + 19.56)) < 1e-9, str(pts))
    check("bond: доска основная (TQCB), валюта SUR → RUB", meta == {"board": "TQCB", "currency": "RUB"}, str(meta))
    cf, cmeta = ms.fetch_bond_cashflows("RU000A10B2F7", D(2026, 9, 1), D(2026, 12, 31))
    check("bond_cf: купон + погашение в один день суммируются; вне окна и без значения — нет",
          cf == [("2026-09-04", 1020.96)], str(cf))
    check("bond_cf: валюта", cmeta == {"currency": "RUB"})
    s = get_series("bond", "RU000A10B2F7", D(2026, 9, 1), D(2026, 9, 3), cache_dir=tmp())
    check("bond через get_series: unit dirty_per_bond, валюта из meta", s.unit == "dirty_per_bond" and s.currency == "RUB" and len(s.points) == 2, str(s))
ms._BOARD_CACHE.clear()
with mock.patch.object(ms, "_http_json", lambda url, timeout=20: {"boards": {"data": [["EQRP", "ccp", 0]]}}):
    s = get_series("bond", "RU000ANOPE00", D(2026, 9, 1), D(2026, 9, 3), cache_dir=tmp())
    check("bond без доски bonds → пусто + флаг сети, без исключения", s.points == [] and any("нет доски" in f for f in s.flags), str(s.flags))

print(f"\n{PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
