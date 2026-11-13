#!/usr/bin/env python3
"""
parity_check.py — сверка двух снапшотов портфеля поле за полем (API-1b, PR-4).

Назначение — теневой период: снапшот скилла (A) против снапшота build_snapshot.py (B),
собранного повтором пакета прогона на тех же ответах сети
(docs/api-migration/implementation-brief.md, «Теневой период»).

    python3 parity_check.py A.json B.json [--known references/parity-known-diffs.yaml]
                            [--report out.md] [--json]

Правила:
  • канонизация: ключи по алфавиту, списки объектов — по ticker/isin/account/date;
  • служебные поля (generated_at, …) не сравниваются — список VOLATILE;
  • точно: строки, булевы, целые (количества, статусы, флаги, даты, счета, сектора);
  • float: допуск |a−b| ≤ max(ABS_TOL, REL_TOL·max(|a|,|b|)) — порядок операций с
    плавающей точкой; деньги с точностью до копейки;
  • известные расхождения — файл known-diffs (шаблон пути: `*` — фрагмент без точки,
    `**` — что угодно → причина); правило,
    а не исключение по факту.

Итог: совпало / в допуске / известное / расходится. Код выхода 1, если есть «расходится».
Только stdlib (known-diffs читается простым разбором; PyYAML не нужен).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

ABS_TOL = 0.01
REL_TOL = 1e-9
EPS = 1e-6          # запас на двоичную запись копеек: 150000 − 149999.99 > 0.01 в float
VOLATILE = ("$.generated_at", "$.build_suspects")
# Ключи, по которым сортируются списки объектов (первый найденный набор)
SORT_KEYS = (("ticker", "account"), ("ticker",), ("isin",), ("code", "step", "message"),
             ("date", "ticker"), ("date",), ("step",),
             # строки целей и факта по корзинам/классам/матрице (без них порядок зависел от значений)
             ("bucket_key",), ("_bucket_key",), ("currency", "class"), ("Валюта", "Бумага"), ("class",))
HERE = Path(__file__).resolve().parent
DEFAULT_KNOWN = HERE.parent / "references" / "parity-known-diffs.yaml"


def load_known(path: Path | None) -> list[dict]:
    """Простой разбор known-diffs: элементы списка `- path: …` с полями reason/since."""
    if not path or not path.exists():
        return []
    items, cur = [], None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith(("reason", "- reason")) else raw.rstrip()
        s = line.strip()
        if not s:
            continue
        if s.startswith("- "):
            cur = {}
            items.append(cur)
            s = s[2:].strip()
        if cur is None or ":" not in s:
            continue
        k, v = s.split(":", 1)
        cur[k.strip()] = v.strip().strip('"').strip("'")
    return [i for i in items if i.get("path")]


def path_match(path: str, pattern: str) -> bool:
    """Шаблон пути known-diffs: `*` — любой фрагмент без точки (в т.ч. метка `[SBER|main]`),
    `**` — что угодно; остальные символы, включая скобки, — буквально."""
    rx = re.escape(pattern).replace(r"\*\*", "\0").replace(r"\*", r"[^.]*").replace("\0", ".*")
    return re.fullmatch(rx, path) is not None


def _sort_key(obj: dict):
    for keys in SORT_KEYS:
        if all(k in obj for k in keys):
            return tuple(str(obj.get(k)) for k in keys)
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True),)


def canon(x):
    if isinstance(x, dict):
        return {k: canon(x[k]) for k in sorted(x)}
    if isinstance(x, list):
        items = [canon(v) for v in x]
        if items and all(isinstance(v, dict) for v in items):
            return sorted(items, key=_sort_key)
        return items
    return x


def _label(obj, i):
    if isinstance(obj, dict):
        for keys in SORT_KEYS:
            if all(k in obj for k in keys):
                return "[" + "|".join(str(obj[k]) for k in keys) + "]"
    return f"[{i}]"


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def compare(a, b, path="$", out=None):
    """Список (path, kind, a, b); kind ∈ equal-не-выводится, tolerated, differs."""
    out = [] if out is None else out
    if path in VOLATILE:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            p = f"{path}.{k}"
            if k not in a or k not in b:
                if p not in VOLATILE:
                    out.append((p, "differs", a.get(k, "<нет>"), b.get(k, "<нет>")))
                continue
            compare(a[k], b[k], p, out)
        return out
    if isinstance(a, list) and isinstance(b, list):
        if all(isinstance(v, dict) for v in a + b) and a and b:
            la = {_label(v, i): v for i, v in enumerate(a)}
            lb = {_label(v, i): v for i, v in enumerate(b)}
            if len(la) == len(a) and len(lb) == len(b):
                for k in sorted(set(la) | set(lb)):
                    if k not in la or k not in lb:
                        out.append((path + k, "differs", "<есть>" if k in la else "<нет>",
                                    "<есть>" if k in lb else "<нет>"))
                    else:
                        compare(la[k], lb[k], path + k, out)
                return out
        if len(a) != len(b):
            out.append((f"{path}.length", "differs", len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            compare(x, y, f"{path}[{i}]", out)
        return out
    if _num(a) and _num(b) and (isinstance(a, float) or isinstance(b, float)):
        if math.isnan(a) and math.isnan(b) or a == b:
            return out
        tol = max(ABS_TOL, REL_TOL * max(abs(a), abs(b))) + EPS
        out.append((path, "tolerated" if abs(a - b) <= tol else "differs", a, b))
        return out
    if a != b:
        out.append((path, "differs", a, b))
    return out


def classify(diffs, known):
    res = {"tolerated": [], "known": [], "differs": []}
    for p, kind, a, b in diffs:
        if kind == "differs":
            k = next((kd for kd in known if path_match(p, kd["path"])), None)
            if k:
                res["known"].append((p, a, b, k.get("reason", "")))
                continue
        res[kind].append((p, a, b))
    return res


def _short(v, n=80):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= n else s[: n - 1] + "…"


def render(res, a_name, b_name, n_fields) -> str:
    st = "✅ совпадает" if not res["differs"] else f"❌ расходится: {len(res['differs'])}"
    lines = [f"# Сверка снапшотов: {st}", "",
             f"- A: `{a_name}`", f"- B: `{b_name}`",
             f"- полей сравнено: {n_fields}; в допуске: {len(res['tolerated'])}; "
             f"известных: {len(res['known'])}; расходится: {len(res['differs'])}", ""]
    if res["differs"]:
        lines += ["## Расходится", "", "| Поле | A | B |", "|---|---|---|"]
        lines += [f"| `{p}` | {_short(a)} | {_short(b)} |" for p, a, b in res["differs"][:300]]
        if len(res["differs"]) > 300:
            lines.append(f"| … ещё {len(res['differs']) - 300} | | |")
        lines.append("")
    if res["known"]:
        lines += ["## Известные расхождения", "", "| Поле | A | B | Причина |", "|---|---|---|---|"]
        lines += [f"| `{p}` | {_short(a, 40)} | {_short(b, 40)} | {r} |" for p, a, b, r in res["known"][:100]]
        lines.append("")
    if res["tolerated"]:
        lines += [f"## В допуске ({len(res['tolerated'])})", "",
                  "Наибольшие отклонения:", "", "| Поле | A | B |", "|---|---|---|"]
        top = sorted(res["tolerated"], key=lambda t: -abs(t[1] - t[2]))[:10]
        lines += [f"| `{p}` | {a!r} | {b!r} |" for p, a, b in top]
    return "\n".join(lines) + "\n"


def _count_leaves(x) -> int:
    if isinstance(x, dict):
        return sum(_count_leaves(v) for v in x.values())
    if isinstance(x, list):
        return sum(_count_leaves(v) for v in x)
    return 1


def check_files(a_path: Path, b_path: Path, known_path: Path | None = DEFAULT_KNOWN):
    a = canon(json.loads(a_path.read_text(encoding="utf-8")))
    b = canon(json.loads(b_path.read_text(encoding="utf-8")))
    res = classify(compare(a, b), load_known(known_path))
    return res, _count_leaves(a)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Сверка двух снапшотов портфеля.")
    ap.add_argument("a", help="снапшот A (скилл)")
    ap.add_argument("b", help="снапшот B (скрипт)")
    ap.add_argument("--known", default=str(DEFAULT_KNOWN), help="файл известных расхождений")
    ap.add_argument("--report", help="записать отчёт markdown")
    ap.add_argument("--json", action="store_true", help="вывести итог JSON")
    o = ap.parse_args(argv)
    res, n = check_files(Path(o.a), Path(o.b), Path(o.known) if o.known else None)
    if o.json:
        print(json.dumps({k: [list(map(str, x)) for x in v] for k, v in res.items()},
                         ensure_ascii=False, indent=1))
    else:
        text = render(res, o.a, o.b, n)
        if o.report:
            Path(o.report).write_text(text, encoding="utf-8")
        print(text)
    return 1 if res["differs"] else 0


if __name__ == "__main__":
    sys.exit(main())
