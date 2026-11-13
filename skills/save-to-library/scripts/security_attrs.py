#!/usr/bin/env python3
"""
security_attrs.py — писатель справочника бумаг `Portfolio/security-attrs.json` (`security-attrs@1`, schema.md §4.8).

Медленные атрибуты бумаги: класс (`ticker_class`, кодлист), дата первых торгов на Мосбирже (`listed_at`, для
IPO-паузы) и одна фраза (`note`). Скрипт сам читает и пишет файл на mount по `--root <корень Claude-Memory>`
(schema.md §1 п.1): весь документ проходит `ds_schemas.validate_security_attrs`, запись — временный файл рядом и
`os.replace`, файл изменился после чтения — ошибка без записи. Скрипт ничего не удаляет. Модель видит только вывод.

Вызов:  python3 security_attrs.py <команда> --root <корень> [аргументы]
Выход — JSON в stdout. Ошибка — код выхода 1 и JSON {"ok": false, "error": "...", ...}.

Команды:
  set   --key K [--class C|none] [--listed-at ГГГГ-ММ-ДД|none] [--note "…"|none] --by <actor>
        Правка полей бумаги; `--by` — код кодлиста actor: `owner` (слово владельца), `mode_N` (из разбора),
        `script` (разработчик); `none` — очистить
        поле (null). Не названное поле не меняется. Ключа нет в справочнике — новая запись, остальные поля null.
        updated_at (time_msk.now_iso) и updated_by (--by) ставит скрипт. Значения те же — файл не пишется,
        `unchanged: true`.
  add-missing --root … --snapshot <portfolio-*.json> [--by script]
        Добавляет в справочник ТОЛЬКО отсутствующие ключи держаний снапшота (qty > 0; ключ — ticker, иначе isin):
        ticker_class null, listed_at — `holdings[].listing_date` снапшота у акций (иначе null; сеть не трогается),
        note null. Существующие записи не меняются никогда. Новых ключей нет — файл не пишется.
        Ту же функцию `add_missing` вызывает hub-notify при «Сохранить» снапшота на сайте (pf_build.save).
  get   --key K          запись бумаги (`found: false`, если ключа нет).
  list  [--class C]      все записи или только класса C (например, ipo), по ключу.

Файла нет — ошибка «справочник не заполнен»: разовое заполнение делает миграция шага 9
(`init_security_attrs.py`) при переключении, этот скрипт файл не создаёт.

Время записи — time_msk.now_iso(); скрытый аргумент `--now <ГГГГ-ММ-ДДTЧЧ:ММ:СС+03:00>` подменяет его (тесты).

Зависимости: stdlib.
"""

import argparse
import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import codelists  # noqa: E402
import ds_schemas as ds  # noqa: E402
import time_msk  # noqa: E402

REL = ("Portfolio", "security-attrs.json")
FIELDS = ds.SECURITY_ATTR_FIELDS
CLASSES = ds.TICKER_CLASSES
ACTORS = ds.CODELISTS["actor"]
NONE = "none"


class CmdError(Exception):
    def __init__(self, message, **extra):
        super().__init__(message)
        self.extra = extra


def _path(root):
    root = os.path.abspath(os.path.expanduser(root))
    if not os.path.isdir(os.path.join(root, REL[0])):
        raise CmdError(f"в корне {root} нет папки {REL[0]}/ — неверный --root или mount не подключён")
    path = os.path.join(root, *REL)
    if not os.path.isfile(path):
        raise CmdError(f"справочник не заполнен: нет {'/'.join(REL)} — разовое заполнение делает миграция "
                       f"init_security_attrs.py при переключении, этот скрипт файл не создаёт")
    return path


def _read(path):
    with open(path, "rb") as f:
        raw = f.read()
    doc = json.loads(raw.decode("utf-8"))
    errs = ds.validate_security_attrs(doc)
    if errs:
        raise CmdError(f"{'/'.join(REL)}: справочник не проходит валидатор — правка не делается", errors=errs)
    return doc, hashlib.sha256(raw).hexdigest()


def _write(path, doc, digest):
    errs = ds.validate_security_attrs(doc)
    if errs:
        raise CmdError("валидация не пройдена — файл не изменён", errors=errs)
    with open(path, "rb") as f:
        if hashlib.sha256(f.read()).hexdigest() != digest:
            raise CmdError("справочник изменился после чтения — файл не изменён, повтори команду")
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _row(key, rec):
    out = {"key": key, **{k: rec.get(k) for k in FIELDS}}
    out["ticker_class_ru"] = codelists.ru("ticker_class", rec.get("ticker_class")) if rec.get("ticker_class") else None
    return out


def _value(raw):
    return None if raw == NONE else raw


def cmd_set(args):
    if not args.key:
        raise CmdError("set: нужен --key")
    if not args.by:
        raise CmdError(f"set: нужен --by (кодлист actor: {', '.join(ACTORS)})")
    changes = {}
    if args.cls is not None:
        v = _value(args.cls)
        if v is not None and v not in CLASSES:
            raise CmdError(f"--class: нет в кодлисте ticker_class ({', '.join(CLASSES)}): {v!r}; "
                           f"новый класс добавляет разработчик в кодлисты")
        changes["ticker_class"] = v
    if args.listed_at is not None:
        v = _value(args.listed_at)
        if v is not None and not ds.is_date(v):
            raise CmdError(f"--listed-at: ожидается ГГГГ-ММ-ДД или none, получено {v!r}")
        changes["listed_at"] = v
    if args.note is not None:
        changes["note"] = _value(args.note)
    if not changes:
        raise CmdError("set: нечего менять — нужен хотя бы один из --class, --listed-at, --note")
    path = _path(args.root)
    doc, digest = _read(path)
    by_key = doc["by_key"]
    rec = by_key.get(args.key)
    created = rec is None
    old = dict(rec) if rec else {k: None for k in FIELDS}
    if not created and all(old.get(k) == v for k, v in changes.items()):
        return {"ok": True, "command": "set", "key": args.key, "unchanged": True, "record": _row(args.key, old)}
    new = {k: old.get(k) for k in FIELDS}
    new.update(changes)
    new["updated_at"] = args.now or time_msk.now_iso()
    new["updated_by"] = args.by
    by_key[args.key] = new
    doc["by_key"] = dict(sorted(by_key.items()))
    _write(path, doc, digest)
    return {"ok": True, "command": "set", "key": args.key, "created": created,
            "changed": sorted(k for k, v in changes.items() if old.get(k) != v),
            "before": None if created else _row(args.key, old), "record": _row(args.key, new)}


def add_missing(doc, holdings, now, by="script"):
    """(doc, [добавленные ключи]): записи для держаний снапшота, которых нет в справочнике. Чистая функция:
    существующие записи не трогаются, doc меняется на месте только добавлением. listed_at — из
    holdings[].listing_date (есть только у акций; валидная дата), иначе null."""
    by_key = doc["by_key"]
    added = []
    for h in holdings or []:
        if not isinstance(h, dict) or not (h.get("qty") or 0) > 0:
            continue
        key = h.get("ticker") or h.get("isin")
        if not key or key in by_key:
            continue
        ld = h.get("listing_date")
        by_key[key] = {"ticker_class": None, "listed_at": ld if ds.is_date(ld) else None,
                       "note": None, "updated_at": now, "updated_by": by}
        added.append(key)
    if added:
        doc["by_key"] = dict(sorted(by_key.items()))
    return doc, added


def cmd_add_missing(args):
    if not args.snapshot:
        raise CmdError("add-missing: нужен --snapshot")
    with open(args.snapshot, encoding="utf-8") as f:
        snap = json.load(f)
    path = _path(args.root)
    doc, digest = _read(path)
    doc, added = add_missing(doc, snap.get("holdings"), args.now or time_msk.now_iso(), args.by or "script")
    if added:
        _write(path, doc, digest)
    return {"ok": True, "command": "add-missing", "added": added, "unchanged": not added}


def cmd_get(args):
    if not args.key:
        raise CmdError("get: нужен --key")
    doc, _ = _read(_path(args.root))
    rec = doc["by_key"].get(args.key)
    return {"ok": True, "command": "get", "key": args.key, "found": rec is not None,
            "record": _row(args.key, rec) if rec is not None else None}


def cmd_list(args):
    if args.cls is not None and args.cls not in CLASSES:
        raise CmdError(f"--class: нет в кодлисте ticker_class ({', '.join(CLASSES)}): {args.cls!r}")
    doc, _ = _read(_path(args.root))
    items = [_row(k, r) for k, r in sorted(doc["by_key"].items())
             if args.cls is None or r.get("ticker_class") == args.cls]
    return {"ok": True, "command": "list", "class": args.cls, "count": len(items), "items": items}


COMMANDS = {"set": cmd_set, "add-missing": cmd_add_missing, "get": cmd_get, "list": cmd_list}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CmdError(f"аргументы: {message}")


def _parser():
    ap = _Parser(description="Справочник бумаг security-attrs@1: set / get / list")
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("--root", required=True, help="корень Claude-Memory (в Cowork — $HOME/mnt/Claude-Memory)")
    ap.add_argument("--key", default=None, help="ключ бумаги (тикер или ISIN)")
    ap.add_argument("--class", dest="cls", default=None, help="класс (кодлист ticker_class) или none")
    ap.add_argument("--listed-at", dest="listed_at", default=None, help="дата первых торгов ГГГГ-ММ-ДД или none")
    ap.add_argument("--note", default=None, help="одна фраза (≤ 200 знаков) или none")
    ap.add_argument("--snapshot", default=None, help="add-missing: снапшот портфеля portfolio-*.json")
    ap.add_argument("--by", default=None, help="set: кто меняет — код кодлиста actor (owner, mode_4 …, script)")
    ap.add_argument("--now", default=None, help=argparse.SUPPRESS)
    return ap


def run(argv):
    try:
        args = _parser().parse_args(argv)
        if args.by is not None and args.by not in ACTORS:
            raise CmdError(f"--by: нет в кодлисте actor ({', '.join(ACTORS)}): {args.by!r}")
        if args.now is not None and not ds.is_time(args.now):
            raise CmdError(f"--now: ожидается ГГГГ-ММ-ДДTЧЧ:ММ:СС+03:00, получено {args.now!r}")
        out = COMMANDS[args.command](args)
    except CmdError as exc:
        return 1, {"ok": False, "error": str(exc), **exc.extra}
    except Exception as exc:  # noqa: BLE001 — нечитаемый JSON, ввод-вывод: модель получает JSON, не трассу
        return 1, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return 0, out


def main():
    code, out = run(sys.argv[1:])
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
