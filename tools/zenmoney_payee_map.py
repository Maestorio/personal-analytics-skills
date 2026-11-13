#!/usr/bin/env python3
"""Словарь «текст банка → место» для пересчёта истории из CSV-выгрузки ZenMoney.

Зачем (2026-10-07): колонка «Кому» (payee) в CSV — не всегда место. Если место
поставил плагин банка, там сырой текст банка («PRODUKTY ERMOLINO», «EVO_PRODUKTY»),
а приложение и MCP показывают место («Ермолино», «Продторг»); если место задано
руками — там название места. Пересчёт из CSV переносил текст банка в историю, и
на странице «Деньги» появлялись места, которых в ZenMoney нет (в 2025–2026 так
записано 1429 из 2386 трат с местом).

Верное название есть только в MCP: операция → `merchantId` →
`references.merchants[id].name` (нет места — `merchantId: null`, тогда «без места»,
как в скилле). Скрипт сопоставляет строки CSV операциям из страниц
`list_transactions` по (дата, счёт, сумма) и пишет словарь:

  * `by_text` — текст «Кому» → место, когда у всех найденных операций с этим
    текстом место одно (работает и для операций вне загруженных страниц);
  * `by_op` — «дата|счёт|сумма|текст» → место для строк, где `by_text` ошибся бы
    (один текст банка у разных мест, место снято, совпадение по ключу);
  * `stats` — сколько строк заменено, не найдено в MCP, неоднозначно.

Строки, где «Кому» уже совпадает с местом, в словарь не попадают.

  python3 tools/zenmoney_payee_map.py build --csv <выгрузка.csv> --pages <папка со страницами MCP> \\
      [--pages …] --out docs/zenmoney/csv/payee-map.json

Дозагрузка вместо полной (2026-10-07): правка места в приложении не всегда меняет
«Кому» в CSV (у мест от плагина там текст банка — до и после совмещения тот же), но
всегда меняет `changedDate` операции. Поэтому:

  changed --old <прошлая.csv> --new <новая.csv> [--from 2020-01-01]
      → окна дат (`from`, `to`) для `list_transactions`: дни, где операция изменена,
        появилась или исчезла; соседние дни склеены, пока в окне ≤ 200 строк CSV
        (одна страница MCP на окно);
  grab --session <журнал сессии .jsonl> --after <время ISO> --out <папка страниц> --prefix u<дата>
      → все ответы `list_transactions` этой сессии после `--after` — файлами
        `<prefix>-NNN.json`: большие (сохранённые средой в tool-results) и маленькие
        (пришедшие прямо в контекст, их иначе не достать без перепечатки);
  build — как обычно: страницы читаются по имени файла, у операции побеждает более
        поздний файл (`u…` после `p…`), у места — более позднее название (переименование
        места подхватывается, если в дозагрузке есть хоть одна его операция).

Страницы — ответы `list_transactions` (types expense+income, limit 200) как есть,
по файлу на страницу (`{"data": […], "references": {…}}`). Словарь — личные
данные: лежит в docs/zenmoney/csv/ (в .gitignore). Применяет его
`tools/zenmoney_csv_backfill.py` (функция `load` отсюда).
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

SCHEMA = "zenmoney-payee-map@1"
PAD, SMALL = 180, 25       # окна: дополнять до PAD строк CSV (в них и переводы — у MCP операций меньше); ≤ SMALL — оставлять маленьким


def num(s):
    return float(s.replace(",", ".")) if s else 0.0


def op_key(day, account, amount, text):
    return f"{day}|{account}|{round(float(amount), 2):.2f}|{text}"


def csv_side(r):
    """(счёт, сумма) строки CSV: расход — со стороны списания, доход — зачисления;
    перевод (обе стороны на разных счетах) — None: у переводов места нет."""
    out_v, in_v = num(r["outcome"]), num(r["income"])
    if out_v and in_v and r["outcomeAccountName"] != r["incomeAccountName"]:
        return None
    if out_v:
        return r["outcomeAccountName"], out_v
    if in_v:
        return r["incomeAccountName"], in_v
    return None


def load_pages(dirs):
    """Операции с одной стороной (траты и доходы) → [(дата, счёт, сумма, текст банка, место|"")]."""
    accounts, merchants = {}, {}
    files = sorted(f for d in dirs for f in glob.glob(str(Path(d) / "*.json")))
    by_id = {}
    for f in files:
        page = json.loads(Path(f).read_text(encoding="utf-8"))
        if "data" not in page:
            continue
        refs = page.get("references") or {}
        accounts.update({k: v["name"] for k, v in (refs.get("accounts") or {}).items()})
        merchants.update({k: v["name"] for k, v in (refs.get("merchants") or {}).items()})
        for x in page["data"]:          # более поздний файл (дозагрузка) побеждает
            if ("expense" in x) == ("income" in x):
                by_id.pop(x["id"], None)
                continue
            side = x.get("expense") or x["income"]
            by_id[x["id"]] = (x["date"], side["accountId"], side["amount"], x.get("originalPayee") or "", x.get("merchantId"))
    rows = list(by_id.values())
    out = [(d, accounts.get(a, a), amt, orig, merchants.get(m, "") if m else "") for d, a, amt, orig, m in rows]
    span = (min(r[0] for r in out), max(r[0] for r in out)) if out else None
    return out, span, len(files)


def build(csv_path, page_dirs):
    mcp, span, n_files = load_pages(page_dirs)
    by_key = defaultdict(list)
    for d, acc, amt, orig, name in mcp:
        by_key[op_key(d, acc, amt, "")].append((orig, name))
    st = Counter()
    resolved = []          # (ключ строки, текст CSV, место)
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            side = csv_side(r)
            if not side or not span or not (span[0] <= r["date"] <= span[1]):
                continue
            text = r["payee"]
            cands = by_key.get(op_key(r["date"], side[0], side[1], ""), [])
            if not cands:
                if text:
                    st["нет в MCP (удалена, другой счёт или сумма)"] += 1
                continue
            names = {n for _o, n in cands}
            if len(names) > 1:     # одинаковые суммы в один день на одном счёте — по тексту
                names = {n for o, n in cands if text and text in (o, n)} or names
            if len(names) > 1:
                st["неоднозначно — оставлен текст CSV"] += 1
                continue
            name = names.pop()
            if not text and not name:
                continue
            resolved.append((op_key(r["date"], side[0], side[1], text), text, name))
            st["совпало с местом" if text == name else "заменено"] += 1
    per_text = defaultdict(Counter)
    for _k, text, name in resolved:
        per_text[text][name] += 1
    by_text = {}
    for text, c in per_text.items():
        if text and len(c) == 1:
            name = next(iter(c))
            if name != text:
                by_text[text] = name
    by_op = {k: name for k, text, name in resolved if by_text.get(text, text) != name}
    return {"schema": SCHEMA, "built": date.today().isoformat(), "csv": Path(csv_path).name,
            "pages": {"files": n_files, "operations": len(mcp), "from": span and span[0], "to": span and span[1]},
            "stats": dict(st), "by_text": dict(sorted(by_text.items())), "by_op": dict(sorted(by_op.items()))}


def csv_rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [tuple(sorted(x.items())) for x in csv.DictReader(f, delimiter=";")]


def changed(old_csv, new_csv, frm="2020-01-01", page=200):
    """Окна дат с изменёнными операциями. Строки выгрузок сравниваются целиком (мультимножеством):
    строка новой, которой нет в старой (другой changedDate, место, категория, дата, новая
    операция), и строка старой, которой нет в новой (старая дата правленой, удалённая), дают
    свой день. Ключ «время создания + счёт + сумма» (как в zenmoney_csv_diff) не годится:
    одинаковые покупки в разные дни с временем 00:00:00 склеиваются — 2026-10-07 так выпала
    правка 16.04.2024."""
    o, n = Counter(csv_rows(old_csv)), Counter(csv_rows(new_csv))
    per_day = Counter(dict(r)["date"] for r in n.elements())
    diff = list((n - o).elements()) + list((o - n).elements())
    days = {dict(r)["date"] for r in diff}
    days = {d for d in days if d >= frm}
    ops = sum(1 for r in (n - o).elements() if dict(r)["date"] >= frm)
    days, wins, i = sorted(days), [], 0
    all_days = sorted(per_day)
    while i < len(days):
        start, end, j = days[i], days[i], i + 1
        while j < len(days) and sum(per_day[d] for d in all_days if start <= d <= days[j]) <= page:
            end, j = days[j], j + 1
        wins.append({"from": start, "to": end, "rows": sum(per_day[d] for d in all_days if start <= d <= end)})
        i = j
    # окно средней величины среда возвращает прямо в контекст (~400 знаков на операцию);
    # от ~50 тыс. знаков (~150 операций) — сохраняет в файл. Поэтому среднее окно расширяется соседними днями
    # (без пересечения с другими окнами) до PAD строк; маленькое (≤ SMALL) дешевле оставить
    for k, w in enumerate(wins):
        if not (SMALL < w["rows"] < PAD):
            continue
        lo = wins[k - 1]["to"] if k else ""
        hi = wins[k + 1]["from"] if k + 1 < len(wins) else "9999"
        before = [d for d in all_days if lo < d < w["from"]][::-1]
        after = [d for d in all_days if w["to"] < d < hi]
        while w["rows"] < PAD and (before or after):
            d = after.pop(0) if after else before.pop(0)
            if w["rows"] + per_day[d] > page:
                break
            w["rows"] += per_day[d]
            w["from"], w["to"] = min(w["from"], d), max(w["to"], d)
    return {"operations": ops, "days": len(days), "windows": wins}


def grab(session, after, out_dir, prefix):
    """Ответы list_transactions из журнала сессии (после after) → файлы страниц по порядку."""
    calls, pages = set(), []
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for line in open(session, encoding="utf-8"):
        e = json.loads(line)
        if e.get("timestamp", "") < after:
            continue
        for c in (e.get("message") or {}).get("content") or []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "tool_use" and c.get("name", "").endswith("list_transactions"):
                calls.add(c["id"])
            elif c.get("type") == "tool_result" and c.get("tool_use_id") in calls:
                body = c.get("content")
                text = body if isinstance(body, str) else "".join(b.get("text", "") for b in body or [] if isinstance(b, dict))
                saved = re.search(r"Output has been saved to (\S+?\.txt)", text)
                if saved:
                    pages.append(("file", saved.group(1)))
                elif text.lstrip().startswith('{"data"'):
                    pages.append(("text", text))
    written = []
    for i, (kind, v) in enumerate(pages, 1):
        dst = out_dir / f"{prefix}-{i:03d}.json"
        if kind == "file":
            shutil.copyfile(v, dst)
        else:
            dst.write_text(v, encoding="utf-8")
        page = json.loads(dst.read_text(encoding="utf-8"))
        written.append((dst.name, len(page["data"]), page.get("nextCursor") is None))
    return written


def load(path):
    """Функция (дата, счёт, сумма, текст CSV) → место ("" — без места). Нет файла — None."""
    p = Path(path)
    if not p.exists():
        return None
    m = json.loads(p.read_text(encoding="utf-8"))
    if m.get("schema") != SCHEMA:
        raise SystemExit(f"{p}: schema {m.get('schema')!r}, ожидалась {SCHEMA}")
    by_op, by_text = m["by_op"], m["by_text"]

    def fix(day, account, amount, text):
        k = op_key(day, account, amount, text)
        return by_op[k] if k in by_op else by_text.get(text, text)
    fix.meta = m
    return fix


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--csv", required=True)
    b.add_argument("--pages", required=True, action="append")
    b.add_argument("--out", required=True)
    c = sub.add_parser("changed")
    c.add_argument("--old", required=True)
    c.add_argument("--new", required=True)
    c.add_argument("--from", dest="frm", default="2020-01-01")
    g = sub.add_parser("grab")
    g.add_argument("--session", required=True)
    g.add_argument("--after", required=True, help="время ISO (UTC, как в журнале): ответы раньше — не брать")
    g.add_argument("--out", required=True)
    g.add_argument("--prefix", required=True, help="u<дата>: после p… по имени — дозагрузка побеждает")
    a = p.parse_args(argv)
    if a.cmd == "changed":
        r = changed(a.old, a.new, a.frm)
        print(f"изменено операций с {a.frm}: {r['operations']}, дней {r['days']}, вызовов list_transactions: {len(r['windows'])}")
        for w in r["windows"]:
            print(json.dumps({"from": w["from"], "to": w["to"]}), f"# ~{w['rows']} операций")
        return 0
    if a.cmd == "grab":
        for name, n, last in grab(a.session, a.after, a.out, a.prefix):
            print(f"{name}: {n} операций" + ("" if last else "  (есть следующая страница: дочитать по nextCursor, если это не середина полной загрузки)"))
        return 0
    m = build(a.csv, a.pages)
    Path(a.out).write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    pg = m["pages"]
    print(f"MCP: {pg['files']} страниц, {pg['operations']} операций {pg['from']}…{pg['to']}")
    for k, v in m["stats"].items():
        print(f"  {k}: {v}")
    print(f"словарь: текстов {len(m['by_text'])}, отдельных операций {len(m['by_op'])} → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
