#!/usr/bin/env python3
"""Тесты общего модуля _shared-references/scenario_weights.py (файл весов сайта, интерполяция по дням).

Запуск: ~/.pyenv/versions/3.12.9/bin/python3 skills/macro-forecast-chain/tests/test_scenario_weights.py
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "_shared-references"))
import scenario_weights as sw  # noqa: E402

fails = 0
total = 0


def check(name, cond, detail=""):
    global fails, total
    total += 1
    print(f"  [{'OK' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        fails += 1


GOOD = {
    "schema": "stress-weights@1", "matrix": "m",
    "horizon_ends": {"h6": "2027-01-01", "h12": "2027-07-01", "h24": "2028-07-01"},
    "weights": {"h6": {"A": 0.2, "B": 0.8}, "h12": {"A": 0.6, "B": 0.4}, "h24": {"A": 0.0, "B": 1.0}},
    "set_at": "2026-11-06T11:00:00+03:00",
}


def write(tmp, data, name="stress-weights-m.json"):
    p = Path(tmp) / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def refused(tmp, data):
    try:
        sw.load_site(write(tmp, data))
    except sw.SiteWeightsError as e:
        return str(e)
    return None


def main():
    with tempfile.TemporaryDirectory() as tmp:
        site = sw.load_site(write(tmp, GOOD))
        check("файл годный: _file", site["_file"] == "stress-weights-m.json")
        check("нет файла → None", sw.load_site(Path(tmp) / "нет.json") is None)
        check("site_file_for", sw.site_file_for("/x/y/scenario-a.yaml") == Path("/x/y/stress-weights-scenario-a.json"))

        w, meta = sw.weights_on_dates(site, ["2027-07-01"])
        check("точная дата — как есть", w["2027-07-01"] == {"A": 0.6, "B": 0.4} and meta["exact"] == ["2027-07-01"])
        # 2027-01-01 .. 2027-07-01 = 181 день; середина-ближе: 2027-04-02 = 91 день
        w, meta = sw.weights_on_dates(site, ["2027-04-02"])
        f = 91 / 181
        check("интерполяция по дням (ручной расчёт)",
              abs(w["2027-04-02"]["A"] - round(0.2 + 0.4 * f, 6)) < 1e-9, str(w))
        check("интерполяция в мете", meta["interpolated"] == ["2027-04-02"] and not meta["exact"])
        w, meta = sw.weights_on_dates(site, ["2026-06-01", "2030-01-01"])
        check("до первого — веса первого срока", w["2026-06-01"] == {"A": 0.2, "B": 0.8})
        check("после последнего — веса последнего", w["2030-01-01"] == {"A": 0.0, "B": 1.0})
        check("held в мете", meta["held"] == ["2026-06-01", "2030-01-01"])
        dates = ["2026-12-31", "2027-02-14", "2027-07-02", "2028-03-03", "2028-07-01", "2029-01-01"]
        w, meta = sw.weights_on_dates(site, dates)
        check("сумма = 1 на любой дате", all(abs(sum(v.values()) - 1) < 1e-5 for v in w.values()))
        check("мета: set_at и site_dates", meta["set_at"] == GOOD["set_at"] and meta["site_dates"]["h12"] == "2027-07-01"
              and meta["file"] == "stress-weights-m.json" and meta["source"] == "site")

        def mut(f):
            d = copy.deepcopy(GOOD)
            f(d)
            return d

        cases = {
            "нет схемы": mut(lambda d: d.pop("schema")),
            "сумма ≠ 1": mut(lambda d: d["weights"]["h12"].update(A=0.7)),
            "разный набор сценариев": mut(lambda d: d["weights"]["h6"].update(C=0.0)),
            "битая дата": mut(lambda d: d["horizon_ends"].update(h6="2027-13-40")),
            "совпадающие даты": mut(lambda d: d["horizon_ends"].update(h6="2027-07-01")),
            "ключи weights ≠ horizon_ends": mut(lambda d: d["weights"].pop("h24")),
            "вес вне [0,1]": mut(lambda d: d["weights"]["h6"].update(A=-0.2, B=1.2)),
            "пустые сроки": mut(lambda d: d.update(horizon_ends={})),
        }
        for name, d in cases.items():
            msg = refused(tmp, d)
            check(f"отказ: {name}", msg is not None and "stress-weights-m.json" in msg, str(msg))
    print(f"Итого: {total - fails} из {total}")
    sys.exit(1 if fails else 0)


main()
