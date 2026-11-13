#!/usr/bin/env python3
"""
codelists.py — загрузчик кодлистов портфельного контура (модуль (в) схемы данных, schema.md §1 п.3, §3.4).

Единственный источник кодов и русских слов — `codelists.json` рядом с этим файлом (в репозитории —
`_shared-references/`, в упакованном скилле — `scripts/`, туда оба файла кладёт pack.sh). Копий словарей в
скриптах, вьюере, сервере и уведомителе нет: они читают JSON (Python — через этот модуль, страница — через
сгенерированный `tools/assets/codelists.js`, hub-api и hub-notify — сам JSON из своего каталога).

Форма JSON:
  {"schema_version": "codelists@1",
   "lists": {"<имя>": {"<КОД>": {"ru": "…", "short"?: "…", "since"?: "ГГГГ-ММ-ДД",
                                  "legacy"?: true, "migrate_to"?: "<КОД того же списка>", …}}},
   "maps": {"<имя>": {"<ключ>": <значение>}},
   "defaults": {"review_days": 60, …}}

Правила, которые держит тест `tools/tests/test_codelists.py`:
  - у каждого кода есть непустое `ru`; legacy-код имеет `migrate_to` из того же списка;
  - карты ссылаются только на существующие коды; `defaults` — целые > 0;
  - **порядок ключей в списке канонический**: по нему вьюер сортирует (вердикты — от «лучше» к «хуже»:
    BUY, ADD, HOLD, HOLD_TO_MAT, WATCH, TRIM, SELL, затем legacy-коды), строит выпадающие списки плана и
    статуса; переставлять ключи — значит менять порядок на экране;
  - `tools/assets/codelists.js` равен генерации из JSON: после правки JSON —
    `python3 _shared-references/codelists.py --emit-js tools/assets/codelists.js`.

Дополнительные поля кодов (сверх формы схемы):
  - `gate_status.*.effect` — что статус значит для сделок одной строкой (gate_status_ru.effect);
    `gate_status.*.hint` — длинное пояснение для вьюера (легенда и карточка);
  - `verdict.*.weekly` — классы (`stock`, `bond`), для которых код допускает валидатор обзора недели
    (weekly-review@2); код без поля обзор не принимает.

  - `since: "2026-10-31"` — код, введённый целевой схемой цикла (decision@1, conditions@2, report@1);
    валидаторы прежних форматов (conditions@1.2, обзор недели) его не принимают до перевода своих писателей.

legacy-коды остаются допустимыми там, где были допустимы, до миграции данных; `migrate_to` — во что их
переводит миграция.

CLI:  python3 codelists.py --emit-js <путь>   — записать JS-копию для страницы
      python3 codelists.py --check-js <путь>  — код выхода 1, если JS-копия устарела

Зависимости: stdlib.
"""

from __future__ import annotations

import json
import os
import sys

JSON_NAME = "codelists.json"
_HERE = os.path.dirname(os.path.abspath(__file__))
_CACHE: dict = {}


def json_path() -> str:
    return os.path.join(_HERE, JSON_NAME)


def load(path: str | None = None) -> dict:
    """Весь документ кодлистов (кешируется по пути)."""
    p = path or json_path()
    if p not in _CACHE:
        with open(p, encoding="utf-8") as f:
            doc = json.load(f)
        if doc.get("schema_version") != "codelists@1":
            raise ValueError(f"{p}: schema_version {doc.get('schema_version')!r}, ожидался codelists@1")
        _CACHE[p] = doc
    return _CACHE[p]


def entries(name: str) -> dict:
    """{код: {ru, …}} списка в каноническом порядке."""
    lists = load()["lists"]
    if name not in lists:
        raise KeyError(f"нет кодлиста {name!r}")
    return lists[name]


def codes(name: str, legacy: bool = True) -> list[str]:
    """Коды списка в каноническом порядке; legacy=False — без legacy-кодов."""
    return [c for c, e in entries(name).items() if legacy or not e.get("legacy")]


def is_legacy(name: str, code) -> bool:
    return bool(entries(name).get(str(code), {}).get("legacy"))


def ru(name: str, code, default=None):
    """Русское слово кода; неизвестный код → default (по умолчанию сам код: ошибку не прячем)."""
    e = entries(name).get(str(code)) if code is not None else None
    if e is None:
        return code if default is None else default
    return e["ru"]


def word(name: str, code, short: bool = False, default=None):
    """Слово кода; short=True — короткое (`short`), если есть, иначе обычное."""
    e = entries(name).get(str(code)) if code is not None else None
    if e is None:
        return code if default is None else default
    return e.get("short", e["ru"]) if short else e["ru"]


def words(name: str, field: str = "ru", legacy: bool = True) -> dict:
    """{код: поле} в каноническом порядке (по умолчанию слово `ru`)."""
    return {c: e.get(field) for c, e in entries(name).items() if legacy or not e.get("legacy")}


TARGET_SCHEMA_SINCE = "2026-10-31"   # см. докстринг: since этого дня = код целевой схемы цикла


def where(name: str, field: str, value) -> list[str]:
    """Коды, у которых поле `field` равно value или (если поле — список) содержит value."""
    out = []
    for c, e in entries(name).items():
        v = e.get(field)
        if v == value or (isinstance(v, list) and value in v):
            out.append(c)
    return out


def map_(name: str) -> dict:
    maps = load()["maps"]
    if name not in maps:
        raise KeyError(f"нет карты {name!r}")
    return maps[name]


def defaults() -> dict:
    return dict(load()["defaults"])


# ─────────────────────────── JS-копия для страницы ───────────────────────────

_JS_API = """(function (root) {
  "use strict";
  var D = root.CODELISTS;
  var L = D.lists, M = D.maps;
  function ent(list) { if (!L[list]) throw new Error("нет кодлиста " + list); return L[list]; }
  var CL = {
    // коды в каноническом порядке; legacy=false — без legacy-кодов
    codes: function (list, legacy) { var e = ent(list); return Object.keys(e).filter(function (c) { return legacy !== false || !e[c].legacy; }); },
    // слово кода; неизвестный код — сам код (или fallback)
    ru: function (list, code, fallback) { var e = ent(list)[code]; return e ? e.ru : (fallback === undefined ? code : fallback); },
    short: function (list, code) { var e = ent(list)[code]; return e ? (e.short || e.ru) : code; },
    // {код: поле} в каноническом порядке (поле по умолчанию ru)
    words: function (list, field, legacy) { var e = ent(list), o = {}; Object.keys(e).forEach(function (c) { if (legacy !== false || !e[c].legacy) o[c] = e[c][field || "ru"]; }); return o; },
    isLegacy: function (list, code) { var e = ent(list)[code]; return !!(e && e.legacy); },
    map: function (name) { if (!M[name]) throw new Error("нет карты " + name); return M[name]; },
    defaults: function () { return D.defaults; }
  };
  root.CL = CL;
  if (typeof module !== "undefined" && module.exports) module.exports = CL;
})(typeof window !== "undefined" ? window : (typeof globalThis !== "undefined" ? globalThis : this));
"""


def render_js(path: str | None = None) -> str:
    doc = load(path)
    data = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    return ("/* codelists.js — СГЕНЕРИРОВАН из _shared-references/codelists.json, руками не править.\n"
            " * Перегенерировать: python3 _shared-references/codelists.py --emit-js tools/assets/codelists.js\n"
            " * Равенство JSON ↔ JS держит tools/tests/test_codelists.py. */\n"
            "(typeof window !== \"undefined\" ? window : (typeof globalThis !== \"undefined\" ? globalThis : this))"
            f".CODELISTS = {data};\n" + _JS_API)


def _main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] in ("--emit-js", "--check-js"):
        js = render_js()
        if argv[0] == "--emit-js":
            with open(argv[1], "w", encoding="utf-8") as f:
                f.write(js)
            print(f"✓ {argv[1]}")
            return 0
        try:
            cur = open(argv[1], encoding="utf-8").read()
        except FileNotFoundError:
            cur = None
        if cur != js:
            print(f"✗ {argv[1]} устарел: python3 _shared-references/codelists.py --emit-js {argv[1]}")
            return 1
        print(f"✓ {argv[1]} совпадает с {JSON_NAME}")
        return 0
    print(__doc__.split("CLI:")[1].split("Зависимости")[0].strip())
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
