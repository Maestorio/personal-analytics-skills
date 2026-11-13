#!/usr/bin/env python3
"""
Регрессионные тесты validate_report.py (health-labs, отчёт health-report@1:
Markdown с шапкой, которую рисует вкладка «Отчёты» health.html).

Запуск из корня репозитория:
    python3 skills/health-labs/tests/test_validate_report.py
Без внешних зависимостей.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "health-labs" / "scripts" / "validate_report.py"
sys.path.insert(0, str(SCRIPT.parent))
import validate_report as vr  # noqa: E402

PASSED = FAILED = 0


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {detail}")


LABS = {"biomarkers": [{"id": "ldl"}, {"id": "hgb"}]}
GOOD = """---
schema: health-report@1
title: Общий отчёт
date: 2026-09-29
data_asof: 2026-09-20
summary: Острых отклонений нет.
flags:
  - warn | Липиды | ЛПНП выше цели | уточнение с чертой
  - ok | Щитовидная железа | ТТГ в норме
todo:
  - Сдать липидограмму
markers: ldl, hgb
---

# Общий отчёт — 29.09.2026

Текст.
"""


def with_head(**kw):
    """GOOD с заменой/удалением строк шапки: ключ=None — убрать строку."""
    lines = GOOD.split("\n")
    out = []
    for ln in lines:
        k = ln.split(":", 1)[0]
        if k in kw:
            if kw[k] is not None:
                out.append(f"{k}: {kw[k]}")
            continue
        out.append(ln)
    return "\n".join(out)


def errs(text, labs=LABS, filename=None):
    return vr.check(text, labs, filename)


def test_good():
    print("корректный отчёт")
    e, w, m = errs(GOOD, filename="2026-09-29-общий.md")
    check("ошибок нет", e == [], repr(e))
    check("предупреждений нет", w == [], repr(w))
    check("flags — список из 2", len(m["flags"]) == 2)
    check("черта внутри пояснения не рвёт флаг", vr.split_flag(m["flags"][0])[2] == "ЛПНП выше цели | уточнение с чертой")
    check("todo — список", m["todo"] == ["Сдать липидограмму"])
    meta, body, _ = vr.parse(GOOD)
    check("тело после шапки", body.lstrip().startswith("# Общий отчёт"))


def test_blocking():
    print("blocking")
    cases = [
        ("нет шапки", "# Отчёт\n\nтекст\n", "нет шапки"),
        ("шапка не закрыта", "---\nschema: health-report@1\n", "не закрыта"),
        ("чужая schema", with_head(schema="health-report@2"), "schema"),
        ("нет title", with_head(title=None), "title: обязательно"),
        ("нет summary", with_head(summary=None), "summary: обязательно"),
        ("плохая дата", with_head(date="29.09.2026"), "date:"),
        ("несуществующая дата", with_head(date="2026-02-30"), "date:"),
        ("data_asof позже date", with_head(data_asof="2026-10-01"), "позже"),
        ("длинный title", with_head(title="х" * 91), "title: 91"),
        ("неизвестный ключ (опечатка)", GOOD.replace("flags:", "flag:"), "неизвестный ключ"),
        ("пункт без списка", GOOD.replace("flags:\n", ""), "пункт списка без ключа"),
        ("уровень флага", GOOD.replace("- warn |", "- danger |"), "уровень"),
        ("флаг без частей", GOOD.replace("- ok | Щитовидная железа | ТТГ в норме", "- ok Щитовидная"), "уровень | заголовок"),
        ("маркер не из labs", with_head(markers="ldl, nope"), "'nope' нет в labs.json"),
        ("маркер дважды", with_head(markers="ldl, ldl"), "повторяется"),
        ("пустое тело", GOOD.split("\n---\n")[0] + "\n---\n\n", "тело отчёта пустое"),
        ("значение у списка", GOOD.replace("todo:\n", "todo: x\n"), "список"),
        ("ключ дважды", GOOD.replace("date: 2026-09-29\n", "date: 2026-09-29\ndate: 2026-09-29\n"), "повторяется"),
    ]
    for name, text, needle in cases:
        e, _, _ = errs(text)
        check(name, any(needle in x for x in e), repr(e))
    many = GOOD.replace("todo:", "\n".join(f"  - info | Ф{i} | т" for i in range(8)) + "\ntodo:")
    e, _, _ = errs(many)
    check("флагов больше 8", any("flags: 10 > 8" in x for x in e), repr(e))


def test_warnings():
    print("предупреждения")
    _, w, _ = errs(GOOD, labs=None)
    check("без --labs маркеры не сверены", any("не сверены" in x for x in w))
    _, w, _ = errs(GOOD, filename="health_report.md")
    check("имя не по образцу", any("не по образцу" in x for x in w))
    _, w, _ = errs(GOOD, filename="2026-09-30-общий.md")
    check("дата в имени ≠ date", any("≠ date" in x for x in w))
    _, w, _ = errs(GOOD.replace("Текст.", "<div>x</div>"))
    check("сырой HTML в теле", any("сырой HTML" in x for x in w))
    _, w, _ = errs(with_head(title='"В кавычках"'))
    check("значение в кавычках", any("кавычках" in x for x in w))
    e, _, _ = errs("﻿" + GOOD)
    check("BOM в начале не ломает шапку", e == [], repr(e))


def run(*args):
    r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_cli():
    print("CLI check/save")
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / "Health").mkdir()
        labs = t / "labs.json"
        labs.write_text('{"biomarkers": [{"id": "ldl"}, {"id": "hgb"}]}', encoding="utf-8")
        rep = t / "draft.md"
        rep.write_text(GOOD, encoding="utf-8")
        rc, out = run("check", str(rep), "--labs", str(labs))
        check("check: код 0 у корректного", rc == 0, out)
        bad = t / "bad.md"
        bad.write_text(with_head(summary=None), encoding="utf-8")
        rc, out = run("check", str(bad))
        check("check: код 1 при ошибках", rc == 1, out)
        rc, out = run("save", str(rep), "--health", str(t / "Health"), "--topic", "Общий отчёт", "--labs", str(labs))
        dst = t / "Health" / "reports" / "2026-09-29-общий-отчёт.md"
        check("save: dry-run ничего не пишет", rc == 0 and "dry-run" in out and not dst.exists(), out)
        rc, out = run("save", str(rep), "--health", str(t / "Health"), "--topic", "Общий отчёт", "--apply")
        check("save --apply: имя из date и темы", rc == 0 and dst.exists(), out)
        check("save: содержимое байт в байт", dst.read_bytes() == rep.read_bytes())
        rc, out = run("save", str(rep), "--health", str(t / "Health"), "--topic", "общий отчёт", "--apply")
        check("save: тот же файл повторно — ничего не делает", rc == 0 and "то же" in out, out)
        rep.write_text(GOOD.replace("Текст.", "Другой текст."), encoding="utf-8")
        rc, out = run("save", str(rep), "--health", str(t / "Health"), "--topic", "общий отчёт", "--apply")
        check("save: другой файл с тем же именем — отказ", rc == 1 and "другим содержимым" in out, out)
        check("save: старый файл не тронут", "Другой текст" not in dst.read_text(encoding="utf-8"))
        rc, out = run("save", str(bad), "--health", str(t / "Health"), "--topic", "плохой", "--apply")
        check("save: ошибки формата — не пишет", rc == 1 and not (t / "Health" / "reports" / "2026-09-29-плохой.md").exists(), out)


def test_page_parity():
    # Шапку разбирают два парсера — этот и parseReportHead в health.html.
    # Сверяем, что страница знает те же уровни флагов и списки, иначе флаг
    # с новым уровнем молча перекрасился бы в «Наблюдать».
    print("паритет со страницей")
    html = (REPO_ROOT / "tools" / "health.html").read_text(encoding="utf-8")
    for lvl in vr.LEVELS:
        check(f"страница знает уровень {lvl}", f"  {lvl}:" in html[html.find("var REP_LEVELS"):html.find("function isMdReport")])
    check("страница: списки flags/todo", 'kv[1] === "flags" || kv[1] === "todo"' in html)
    # с ui-kit 1.7.0 тело отчёта рисует общий читатель markdown (uiReaderHTML поверх uiMarkdown)
    check("страница: .md рисуется общим читателем", "uiReaderHTML(md.body" in html)
    check("страница: отчёты новые сверху (по date шапки)", "reportDate(b).localeCompare(reportDate(a))" in html)


if __name__ == "__main__":
    test_good()
    test_blocking()
    test_warnings()
    test_cli()
    test_page_parity()
    print(f"\ntest_validate_report: {PASSED} passed, {FAILED} failed")
    sys.exit(1 if FAILED else 0)
