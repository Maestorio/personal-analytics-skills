#!/usr/bin/env python3
"""tools/gaming_migrate.py — перевод оверлея игр на три оси; синтетика, HTTP — заглушкой.

Правило: играю / пройдена / брошена → куплена + прохождение; оценка «брошено» снимается (progress «брошена»,
если пуст); «Demo» / «: Demo» / «Trial Version» у купленной → флаг demo при некупленном state (на-карандаш, при оценке
«не понравилось» — не-интересно), оценка брошено|не понравилось → не понравилось без прохождения «брошена»; старое
state «демо» → то же; demo при «куплена» снимается; повторный проход ничего не меняет. Сухой прогон ничего не пишет; --write — POST с base_hash, 409 → код 1.
Запуск: python3 tools/tests/test_gaming_migrate.py
"""
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import gaming_migrate as gm  # noqa: E402

FAIL = []


def check(name, ok, extra=""):
    print(("✓ " if ok else "✗ ") + name + ("" if ok else f" {extra}"))
    if not ok:
        FAIL.append(name)


def rec(title, state="куплена", rating=None, progress=None):
    return {"title": title, "state": state, "rating": rating, "progress": progress, "note": None}


DOC = {"schema": "gaming-user@1", "updated": "2026-11-10", "items": [
    rec("A playing", "играю"), rec("B done", "пройдена", "понравилось"), rec("C dropped state", "брошена"),
    rec("D rating dropped", rating="брошено"), rec("E dropped with progress", rating="брошено", progress="отложена"),
    rec("F Demo", rating=None), rec("G: Demo", rating="брошено"), rec("H Trial Version", rating="не понравилось"),
    rec("I demo lover Demo", rating="понравилось"), rec("J Demonstration"), rec("K normal", rating="нормально"),
    rec("L wish", "хочу"), rec("M wish Demo", "хочу"), rec("N", "куплена", "восторг", "пройдена"),
    rec("O old demo", "демо", "нормально", "отложена"), rec("P old demo bad", "демо", "не понравилось"),
    dict(rec("Q bought flagged", "куплена", "восторг"), demo=True),
]}
d = copy.deepcopy(DOC)
ch = gm.migrate_doc(d)
by = {x["title"]: x for x in d["items"]}
st = lambda t: (by[t]["state"], by[t]["rating"], by[t]["progress"])  # noqa: E731
dm = lambda t: by[t].get("demo") is True  # noqa: E731
check("играю → куплена + progress играю", st("A playing") == ("куплена", None, "играю"))
check("пройдена → куплена + пройдена, оценка цела", st("B done") == ("куплена", "понравилось", "пройдена"))
check("state брошена → куплена + брошена", st("C dropped state") == ("куплена", None, "брошена"))
check("оценка брошено → null и progress брошена", st("D rating dropped") == ("куплена", None, "брошена"))
check("оценка брошено при заполненном progress — progress цел", st("E dropped with progress") == ("куплена", None, "отложена"))
check("«Demo» → флаг demo + на-карандаш, оценки нет, прохождения нет", st("F Demo") == ("на-карандаш", None, None) and dm("F Demo"))
check("«: Demo» + брошено → не-интересно + demo + не понравилось, progress пуст", st("G: Demo") == ("не-интересно", "не понравилось", None) and dm("G: Demo"))
check("«Trial Version» + не понравилось → не-интересно + demo, оценка та же", st("H Trial Version") == ("не-интересно", "не понравилось", None) and dm("H Trial Version"))
check("демо с хорошей оценкой — оценка цела, на-карандаш", st("I demo lover Demo") == ("на-карандаш", "понравилось", None) and dm("I demo lover Demo"))
check("старое state «демо» → на-карандаш + demo, прохождение цело", st("O old demo") == ("на-карандаш", "нормально", "отложена") and dm("O old demo"))
check("старое state «демо» + не понравилось → не-интересно + demo", st("P old demo bad") == ("не-интересно", "не понравилось", None) and dm("P old demo bad"))
check("demo у «куплена» снимается", "demo" not in by["Q bought flagged"] and st("Q bought flagged")[0] == "куплена")
check("значения state «демо» после миграции нет", all(i["state"] != "демо" for i in d["items"]))
check("«Demonstration» — не демо", st("J Demonstration")[0] == "куплена")
check("обычная запись и некупленные не тронуты", st("K normal") == ("куплена", "нормально", None) and st("L wish") == ("хочу", None, None))
check("не купленная «… Demo» остаётся как есть", st("M wish Demo")[0] == "хочу")
check("готовая запись не в списке изменений", "N" not in [c[0] for c in ch])
cnt = gm.summary(ch)
check("сводка по правилам", cnt.get("демо → флаг demo") == 4 and cnt.get("state демо → флаг demo") == 2 and cnt.get("demo снят: игра куплена") == 1 and cnt.get("progress → брошена") == 1 and cnt.get("state → куплена + progress") == 3, cnt)
d2 = copy.deepcopy(d)
check("идемпотентность: второй проход ничего не меняет", gm.migrate_doc(d2) == [] and d2 == d)

# ── CLI: сухой прогон по файлу ──
tmp = Path(tempfile.mkdtemp())
f = tmp / "user-state.json"
f.write_text(json.dumps(DOC, ensure_ascii=False), encoding="utf-8")
before = f.read_bytes()
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = gm.run(["--file", str(f)])
check("--file: сухой прогон, код 0, файл не изменён", rc == 0 and f.read_bytes() == before and "Сухой прогон" in buf.getvalue())
with contextlib.redirect_stderr(io.StringIO()):
    check("--file --write отказывает", gm.run(["--file", str(f), "--write"]) == 2)

# ── HTTP-заглушка ──
os.environ["HUB_URL"], os.environ["HUB_AUTH"] = "https://hub.test", "Basic x"
calls = []


def opener_ok(url, auth, body=None):
    calls.append((url, auth, body))
    if body is None:
        return 200, {"hash": "h0", "content": json.dumps(DOC, ensure_ascii=False)}
    return 200, {"hash": "h1"}


def opener_409(url, auth, body=None):
    if body is None:
        return 200, {"hash": "h0", "content": json.dumps(DOC, ensure_ascii=False)}
    return 409, {}


with contextlib.redirect_stdout(io.StringIO()):
    rc = gm.run([], opener=opener_ok)
check("сухой прогон по HTTP: только чтение", rc == 0 and len(calls) == 1 and calls[0][2] is None
      and calls[0][0].endswith("/api/gm/file?path=Gaming/user-state.json") and calls[0][1] == "Basic x")
calls.clear()
with contextlib.redirect_stdout(io.StringIO()):
    rc = gm.run(["--write"], opener=opener_ok)
body = calls[-1][2] if calls else None
saved = json.loads(body["content"]) if body else {}
check("--write: POST /api/gm/save с base_hash и новым содержимым",
      rc == 0 and body and body["path"] == "Gaming/user-state.json" and body["base_hash"] == "h0"
      and calls[-1][0].endswith("/api/gm/save") and saved["items"][0]["state"] == "куплена" and saved["items"][5]["state"] == "на-карандаш" and saved["items"][5]["demo"] is True)
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    rc = gm.run(["--write"], opener=opener_409)
check("409 → код 1", rc == 1)
del os.environ["HUB_URL"]
with contextlib.redirect_stderr(io.StringIO()):
    check("без HUB_URL → код 2", gm.run([]) == 2)

# одна карточка вместо двух: демо при записи основной игры (решение владельца 2026-11-10)
_d = {"items": [rec("Base One", "не-интересно"), rec("Base One Demo", "куплена", "не понравилось"),
                rec("Bought Two!", "куплена", "восторг"), rec("Bought Two! Demo", "куплена"),
                rec("Lonely Demo", "куплена")]}
gm.migrate_doc(_d, today="2026-11-10", demo=["Only In Library Trial Version"], hide=["Other: Demo"])
_g = {i["title"]: i for i in _d["items"]}
check("демо + некупленная основная → основная с флагом demo и оценкой демо, демо скрыта",
      (_g["Base One"]["state"], _g["Base One"]["rating"], _g["Base One"]["demo"]) == ("не-интересно", "не понравилось", True) and _g["Base One Demo"]["deleted"] is True)
check("демо при купленной основной → основная не тронута, демо скрыта",
      (_g["Bought Two!"]["state"], _g["Bought Two!"]["rating"]) == ("куплена", "восторг") and _g["Bought Two! Demo"]["deleted"] is True)
check("демо без основной → своя демо-карточка (demo true, некупленная)",
      (_g["Lonely Demo"]["state"], _g["Lonely Demo"]["demo"]) == ("на-карандаш", True) and not _g["Lonely Demo"].get("deleted"))
check("--demo: игры нет в оверлее → запись с флагом demo",
      (_g["Only In Library Trial Version"]["state"], _g["Only In Library Trial Version"]["demo"]) == ("на-карандаш", True))
_d2 = copy.deepcopy(_d)
check("идемпотентность на свёртке демо: второй проход без изменений", gm.migrate_doc(_d2, today="2026-11-11") == [] and _d2 == _d)
check("--hide: игры нет в оверлее → скрытая запись", _g["Other: Demo"]["deleted"] is True)

print(f"\nИтого: {'все зелёные' if not FAIL else str(len(FAIL)) + ' провалено'}")
sys.exit(1 if FAIL else 0)
