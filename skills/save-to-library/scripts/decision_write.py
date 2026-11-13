#!/usr/bin/env python3
"""
decision_write.py — писатель решений по бумаге `Portfolio/decisions/*.json` (`decision@1`, schema.md §3.1).

Один файл на запись: `Portfolio/decisions/{ГГГГ-ММ-ДД}T{ЧЧММ}-{KEY}.json`, имя = поле `id`, время — МСК записи.
Скрипт сам пишет на mount по `--root <корень Claude-Memory>` (schema.md §1 п.1): решение проходит валидатор
`ds_schemas.validate_decision`, запись — временный файл рядом и `os.replace`; файл с таким именем уже есть —
ошибка, не перезапись. Скрипт ничего не удаляет. Модель заполняет только поля блока (verdict, target_pct,
review_by, note и по желанию confidence); остальное ставит скрипт. Модель видит только вывод скрипта.

Вызов:  python3 decision_write.py <команда> --root <корень> [аргументы]
Выход — JSON в stdout. Ошибка — код выхода 1 и JSON {"ok": false, "error": "...", ...}.

Команды:
  from-report  --doc Portfolio/reports/<файл>.md [--stress <stress_id>] [--by model|owner] [--created id1,id2]
               [--today ГГГГ-ММ-ДД]
               Читает шапку сохранённого отчёта (report@1), проверяет её валидатором `ds_schemas.validate_report`
               и для каждой записи блока `decisions:` пишет решение:
                 source = {kind: report, doc: --doc, mode_codes: из шапки, stress_id: --stress или null};
                 conditions_resolved = id условий ключа, ждущих владельца (waits_owner) по модулю (а) на --today, минус keep_open;
                 conditions_created = --created (id должны быть в Portfolio/conditions.yaml);
                 author = --by (по умолчанию model); recorded_at — время записи.
               Все записи проверяются до первой записи на диск: ошибка в любой — ни одного файла.
               Две бумаги одного отчёта — два файла с одной минутой, различаются ключом.
  owner        --key K --verdict V --note "…" [--target-pct N] [--review-by ГГГГ-ММ-ДД] [--confidence 0..1]
               [--keep-open id1,id2] [--created id1,id2] [--today ГГГГ-ММ-ДД]
               Решение по слову владельца: source = {kind: owner, doc: null, mode_codes: [], stress_id: null},
               author = owner; conditions_resolved — как у from-report.
  digest       --key K [--limit N] [--today ГГГГ-ММ-ДД]
               Последние решения по ключу коротко (новые первыми, по recorded_at) — контекст советника (C5),
               и строка latest: последнее решение, гейт по решениям ключа (только акции; модуль (б) last_word через
               decisions_read.gate, без строк обзоров) и статусы его conditions_created/resolved по модулю (а) на --today.
               «Последнее слово» по бумаге целиком (решения + обзоры) — last_word.card, не эта команда.

Блок `decisions:` в шапке отчёта — вход только этой команды (from-report) и валидатора шапки; после записи кодом
не читается (срез, правило 2 схемы): источник истины — файлы `Portfolio/decisions/`.

Условия: `Portfolio/conditions.yaml` (conditions@2) и `Portfolio/conditions-state.json` читаются модулем (а)
`conditions_merge`; нет файла определений — conditions_resolved пуст и `conditions_missing: true` в выводе.

Время записи (recorded_at и время в id) — time_msk.now_iso(); скрытый аргумент `--now <ГГГГ-ММ-ДДTЧЧ:ММ:СС+03:00>`
подменяет его целиком (детерминизм тестов). --today — дата оценки модуля (а), по умолчанию — дата записи.

Зависимости: stdlib + PyYAML (чтение шапки отчёта и YAML условий).
"""

import argparse
import json
import os
import sys

# Общие модули — канон в _shared-references/; в упакованном .skill — в своей scripts/ (pack.sh кладёт их по
# импортам вместе с транзитивными). Как у apply_condition: сначала каталог скрипта.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE, os.path.normpath(os.path.join(_HERE, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import codelists  # noqa: E402
import conditions_merge as cm  # noqa: E402
import decisions_read as dr  # noqa: E402
import hub_settings  # noqa: E402
import ds_schemas as ds  # noqa: E402
import time_msk  # noqa: E402

SCHEMA_VERSION = "decision@1"
PORTFOLIO = "Portfolio"
DECISIONS_DIR = "decisions"
REPORTS_PREFIX = "Portfolio/reports/"
DEFS_REL = (PORTFOLIO, "conditions.yaml")
STATE_REL = (PORTFOLIO, "conditions-state.json")
CONDITIONS_SCHEMA = "conditions@2"
AUTHORS = ds.CODELISTS["author"]
DIGEST_LIMIT = 5


class CmdError(Exception):
    """Ошибка команды: код выхода 1, JSON {"ok": false, "error": ..., **extra}."""

    def __init__(self, message, **extra):
        super().__init__(message)
        self.extra = extra


# ----------------------------------------------------------------------------- файлы

def _root(root):
    root = os.path.abspath(os.path.expanduser(root))
    if not os.path.isdir(os.path.join(root, PORTFOLIO)):
        raise CmdError(f"в корне {root} нет папки {PORTFOLIO}/ — неверный --root или mount не подключён")
    return root


def _decisions_dir(root):
    return os.path.join(root, PORTFOLIO, DECISIONS_DIR)


def _read_report(root, doc):
    """Шапка сохранённого отчёта (даты остаются строками)."""
    if not isinstance(doc, str) or not doc.startswith(REPORTS_PREFIX) or not doc.endswith(".md") \
            or ".." in doc.split("/"):
        raise CmdError(f"--doc: ожидается путь от корня вида {REPORTS_PREFIX}<файл>.md, получено {doc!r}")
    path = os.path.join(root, *doc.split("/"))
    if not os.path.isfile(path):
        raise CmdError(f"нет отчёта {path} — сначала сохранить отчёт (Workflow N), потом решения")
    with open(path, encoding="utf-8") as f:
        fm = ds.report_frontmatter(f.read())
    if fm is None:
        raise CmdError(f"{doc}: нет YAML-шапки")
    return fm


def _conditions(root, today):
    """Плоские строки модуля (а) на today; (строки, известные id, нет файла определений)."""
    defs_path, state_path = os.path.join(root, *DEFS_REL), os.path.join(root, *STATE_REL)
    if not os.path.isfile(defs_path):
        return [], set(), True
    doc = cm.load_yaml(defs_path)
    if not isinstance(doc, dict) or doc.get("schema_version") != CONDITIONS_SCHEMA:
        sv = doc.get("schema_version") if isinstance(doc, dict) else None
        raise CmdError(f"{defs_path}: формат {sv!r}, нужен {CONDITIONS_SCHEMA} "
                       f"(перевод — tools/data-structures/migrations/migrate_conditions_v2.py)")
    defs = doc.get("conditions") or []
    state = {"events": []}
    if os.path.isfile(state_path):
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    ids = {d.get("id") for d in defs if isinstance(d, dict)}
    return cm.merge(defs, state, today), ids, False


def _write_new(path, obj):
    """Новый файл: существует — ошибка; иначе временный файл рядом → os.replace."""
    if os.path.exists(path):
        raise CmdError(f"файл решения уже есть: {path} — решения не перезаписываются")
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(path):  # кто-то успел записать за время записи временного файла
        raise CmdError(f"файл решения появился во время записи: {path} — временный файл {tmp} оставлен")
    os.replace(tmp, path)


# ----------------------------------------------------------------------------- сборка решения

def _ids_arg(value):
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def _resolved(rows, key, keep_open):
    """Условия ключа, ждущие владельца (waits_owner: сработали и не отложены им), минус keep_open;
    отложенное владельцем («отложить до») решение не закрывает; keep_open вне этого набора — ошибка."""
    fired = [r["id"] for r in cm.select(rows, keys=[key]) if r["waits_owner"]]
    stray = [c for c in keep_open if c not in fired]
    if stray:
        raise CmdError(f"keep_open по {key}: условия {', '.join(stray)} не в сработавших по ключу "
                       f"({', '.join(fired) or 'сработавших нет'})", key=key, fired=fired)
    return [c for c in fired if c not in keep_open]


def _check_created(created, known_ids, missing):
    if not created:
        return
    if missing:
        raise CmdError("--created: нет файла условий Portfolio/conditions.yaml — нечего связывать")
    unknown = [c for c in created if c not in known_ids]
    if unknown:
        raise CmdError(f"--created: нет условий с id {', '.join(unknown)} в Portfolio/conditions.yaml")


def _decision(now, entry, source, author, resolved, created):
    d = {
        "schema_version": SCHEMA_VERSION,
        "id": f"{now[:10]}T{now[11:13]}{now[14:16]}-{entry['key']}",
        "key": entry["key"],
        "verdict": entry["verdict"],
        "target_pct": entry.get("target_pct"),
        "review_by": entry.get("review_by"),
        "note": entry.get("note"),
    }
    if entry.get("confidence") is not None:
        d["confidence"] = entry["confidence"]
    d.update({"conditions_created": list(created), "conditions_resolved": list(resolved), "source": source,
              "author": author, "recorded_at": now})
    return d


def _write_all(root, decisions):
    """Проверка всех решений и имён до записи; затем запись по одному файлу."""
    ddir = _decisions_dir(root)
    errors = {}
    for d in decisions:
        errs = ds.validate_decision(d)
        if errs:
            errors[d.get("key")] = errs
    if errors:
        raise CmdError("валидация не пройдена — ни одного файла не записано", errors=errors)
    paths = [os.path.join(ddir, f"{d['id']}.json") for d in decisions]
    if len(set(paths)) != len(paths):
        raise CmdError("два решения с одним id (повтор ключа) — ни одного файла не записано")
    exist = [p for p in paths if os.path.exists(p)]
    if exist:
        raise CmdError("файл решения уже есть — решения не перезаписываются; ни одного файла не записано",
                       existing=exist)
    os.makedirs(ddir, exist_ok=True)
    for p, d in zip(paths, decisions):
        _write_new(p, d)
    return [os.path.relpath(p, root).replace(os.sep, "/") for p in paths]


# ----------------------------------------------------------------------------- команды

def cmd_from_report(args):
    root = _root(args.root)
    hub_settings.require_ai(root, "decision_write.py from-report", "запись решений из отчёта", zones=("Portfolio", "scenarios"))   # вход — шапка отчёта модели
    fm = _read_report(root, args.doc)
    errs = ds.validate_report(fm)
    if errs:
        raise CmdError(f"{args.doc}: шапка не проходит validate-report", errors=errs)
    block = fm.get("decisions")
    if not block:
        raise CmdError(f"{args.doc}: в шапке нет блока decisions: — записывать нечего")
    if args.stress is not None and not args.stress.strip():
        raise CmdError("--stress: пустая строка")
    created = _ids_arg(args.created)
    now = args.now or time_msk.now_iso()
    today = args.today or now[:10]
    rows, known, missing = _conditions(root, today)
    _check_created(created, known, missing)
    source = {"kind": "report", "doc": args.doc, "mode_codes": list(fm["mode_codes"]), "stress_id": args.stress}
    decisions = []
    for entry in block:
        resolved = _resolved(rows, entry["key"], entry.get("keep_open") or [])
        decisions.append(_decision(now, entry, dict(source), args.by or "model", resolved, created))
    written = _write_all(root, decisions)
    out = {"ok": True, "command": "from-report", "today": today, "written": written, "decisions": decisions}
    if missing:
        out["conditions_missing"] = True
    return out


def build_owner(root, entry, now, today=None, created=()):
    """Решение владельца — чистая сборка без записи: проверка полей блока (`validate_report_decisions`), условия
    ключа, ждущие владельца (`_resolved`), запись `_decision` и её проверка `validate_decision`.
    Единственная сборка для CLI `owner` и для сайта (hub-notify `decision_job`).
    entry — {key, verdict, target_pct, review_by, note, confidence[, keep_open]}; now — МСК-время записи.
    → (решение, conditions_missing); CmdError — поля, условия или схема не прошли."""
    keep_open = list(entry.get("keep_open") or [])
    errs = ds.validate_report_decisions([entry])
    if errs:
        raise CmdError("решение владельца не проходит проверку полей", errors=errs)
    created = list(created or [])
    today = today or now[:10]
    rows, known, missing = _conditions(root, today)
    _check_created(created, known, missing)
    resolved = _resolved(rows, entry["key"], keep_open)
    source = {"kind": "owner", "doc": None, "mode_codes": [], "stress_id": None}
    d = _decision(now, entry, source, "owner", resolved, created)
    errs = ds.validate_decision(d)
    if errs:
        raise CmdError("валидация не пройдена — ни одного файла не записано", errors={d["key"]: errs})
    return d, missing


def cmd_owner(args):
    root = _root(args.root)
    if not args.key or not args.verdict or args.note is None:
        raise CmdError("owner: нужны --key, --verdict и --note (одна фраза «почему», ≤ 200 знаков)")
    entry = {"key": args.key, "verdict": args.verdict, "target_pct": args.target_pct,
             "review_by": args.review_by, "note": args.note, "confidence": args.confidence}
    keep_open = _ids_arg(args.keep_open)
    if keep_open:
        entry["keep_open"] = keep_open
    now = args.now or time_msk.now_iso()
    today = args.today or now[:10]
    d, missing = build_owner(root, entry, now, today, _ids_arg(args.created))
    written = _write_all(root, [d])
    out = {"ok": True, "command": "owner", "today": today, "written": written, "decisions": [d]}
    if missing:
        out["conditions_missing"] = True
    return out


def cmd_digest(args):
    root = _root(args.root)
    if not args.key:
        raise CmdError("digest: нужен --key")
    if args.limit < 1:
        raise CmdError("--limit: ожидается целое ≥ 1")
    today = args.today or (args.now or time_msk.now_iso())[:10]
    return {"ok": True, "command": "digest", **dr.digest(root, args.key, today, args.limit)}


COMMANDS = {"from-report": cmd_from_report, "owner": cmd_owner, "digest": cmd_digest}


# ----------------------------------------------------------------------------- CLI

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CmdError(f"аргументы: {message}")


def _parser():
    ap = _Parser(description="Решения по бумаге decision@1: from-report / owner / digest")
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("--root", required=True, help="корень Claude-Memory (в Cowork — $HOME/mnt/Claude-Memory)")
    ap.add_argument("--doc", default=None, help="from-report: путь отчёта от корня, Portfolio/reports/<файл>.md")
    ap.add_argument("--stress", default=None, help="from-report: id действующего стресса (source.stress_id)")
    ap.add_argument("--by", default=None, choices=AUTHORS, help="from-report: автор решения (model | owner)")
    ap.add_argument("--created", default=None, help="id условий, созданных в том же сохранении, через запятую")
    ap.add_argument("--today", default=None, help="дата оценки условий ГГГГ-ММ-ДД (по умолчанию — дата записи)")
    ap.add_argument("--key", default=None, help="owner/digest: ключ бумаги (тикер или ISIN)")
    ap.add_argument("--verdict", default=None, help="owner: вердикт (кодлист verdict)")
    ap.add_argument("--target-pct", dest="target_pct", type=float, default=None, help="owner: целевая доля, %%")
    ap.add_argument("--review-by", dest="review_by", default=None, help="owner: срок пересмотра ГГГГ-ММ-ДД")
    ap.add_argument("--note", default=None, help="owner: одна фраза «почему» (≤ 200 знаков)")
    ap.add_argument("--confidence", type=float, default=None, help="owner: уверенность 0..1")
    ap.add_argument("--keep-open", dest="keep_open", default=None,
                    help="owner: сработавшие условия ключа, которые решение не закрывает, через запятую")
    ap.add_argument("--limit", type=int, default=DIGEST_LIMIT, help="digest: сколько последних решений")
    ap.add_argument("--now", default=None, help=argparse.SUPPRESS)  # подмена time_msk.now_iso() для тестов
    return ap


def run(argv):
    """(код выхода, объект вывода). Побочный эффект — только запись файлов решений командами from-report/owner."""
    try:
        args = _parser().parse_args(argv)
        if args.today is not None and not ds.is_date(args.today):
            raise CmdError(f"--today: ожидается ГГГГ-ММ-ДД, получено {args.today!r}")
        if args.now is not None and not ds.is_time(args.now):
            raise CmdError(f"--now: ожидается ГГГГ-ММ-ДДTЧЧ:ММ:СС+03:00, получено {args.now!r}")
        if args.command == "from-report" and not args.doc:
            raise CmdError("from-report: нужен --doc Portfolio/reports/<файл>.md")
        out = COMMANDS[args.command](args)
    except CmdError as exc:
        return 1, {"ok": False, "error": str(exc), **exc.extra}
    except Exception as exc:  # noqa: BLE001 — нечитаемый YAML/JSON, ввод-вывод: модель получает JSON, не трассу
        return 1, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return 0, out


def main():
    code, out = run(sys.argv[1:])
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
