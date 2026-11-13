#!/usr/bin/env python3
"""
promote_draft.py — приёмка черновика из `Claude-Memory/_drafts/` в библиотеку одной командой.

Черновик — чистовик до приёмки. Приёмка: найти файлы черновика по виду → собрать целевые файлы
(у прогноза и сценариев `.yaml` библиотеки собирается из блока Events YAML и frontmatter `.md` копированием
полей, текст блока переносится как есть) → прогнать существующие валидаторы `assemble_artifact.py` → записать
атомарно → при `--replaces` пометить прежнюю версию `superseded` → зарегистрировать (`update_index.py`: INDEX и
`_sync_log.md`) → удалить черновик. Тело артефакта через вывод модели не проходит.

Решения остаются за моделью и передаются флагами: замена прежней версии (`--replaces`, B5/C5), другое имя
(`--as`, суффикс `-v2`), перезапись занятого имени (`--force`), домен ретро-аудита (`--domain`, если его нет во
frontmatter и он не выводится из trust однозначно), факт на дату замены для промежуточного снимка
(`--actual`, `--actual-source`), резолв заморозки `outcome_log` (`--outcome-resolve` / `--no-outcome-log`),
текст строк INDEX вместо шаблонных (JSON-вход `index_rows`).

Запуск:
  python3 scripts/promote_draft.py --root <Claude-Memory> --draft <имя без расширения> \
      --kind forecast|scenario|stress|integrated-view|monitor-report|retro-audit \
      [--replaces <путь прежней версии>] [--as <имя>] [--force] [--dry-run] [--keep-draft] \
      [--domain <d>] [--actual <число>] [--actual-source <ссылка>] [--interim-note <текст>] \
      [--outcome-resolve YYYY-MM-DD | --no-outcome-log] [--today YYYY-MM-DD]
  или JSON-объект с теми же ключами (дефисы → подчёркивания) в stdin без аргументов.

Вывод — JSON: ok, kind, written[], replaced, index_rows[], index_pending[], sync_log_line, draft_removed,
issues[], notes[], dry_run. Код 0 — принято (или dry-run без блокеров), 1 — блокер или отказ (ничего не записано),
2 — ошибка вызова.
"""
from __future__ import annotations

import argparse
import calendar
import contextlib
import io
import json
import os
import re
import shutil
import sys
from datetime import date, datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import yaml  # noqa: E402  PyYAML — как у assemble_artifact

import assemble_artifact as aa  # noqa: E402
import hub_settings  # noqa: E402
import update_index as ui  # noqa: E402

KINDS = ("forecast", "scenario", "stress", "integrated-view", "monitor-report", "retro-audit")
DRAFTS = "_drafts"
_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_\-]*)\s*:")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PLAIN_RE = re.compile(r"^[a-z][a-z0-9_\-]*$")
_MOJIBAKE = ("Ã¢", "Ã—", "â€", "Ð¿", "Ñ€")
_TIER2_KEYS = ("assumptions", "thresholds", "deadlines", "falsifiers", "agents")


class Refusal(Exception):
    """Блокер: ничего не записывается."""


# ---------------------------------------------------------------------------
# Текстовые помощники
# ---------------------------------------------------------------------------

def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    return text[1:] if text.startswith("﻿") else text


def _split_fm(text: str):
    """(frontmatter-текст без ограничителей | None, тело). Frontmatter — между первыми `---`."""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---", 3)
    if end < 0:
        return None, text
    nl = text.find("\n", end + 4)
    return text[4:end + 1], (text[nl + 1:] if nl >= 0 else "")


def _fm_dict(text: str) -> dict:
    fm, _ = _split_fm(text)
    if fm is None:
        return {}
    data = yaml.safe_load(fm)
    return data if isinstance(data, dict) else {}


def _strip_events_sections(md: str) -> str:
    """Убирает технические секции `## Events YAML…` (блок для save-to-library и patch HST) из `.md`."""
    lines = md.split("\n")
    out, skip = [], False
    for ln in lines:
        if ln.startswith("## "):
            skip = ln.startswith("## Events YAML")
        if not skip:
            out.append(ln)
    text = "\n".join(out).rstrip()
    while text.endswith("\n---") or text == "---":
        text = text[:-3].rstrip()
    return text + "\n"


def _strip_fence(text: str) -> str:
    s = text.strip("\n")
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.rstrip() + "\n"


def _top_blocks(lines: list[str]) -> dict:
    """{ключ: (начало, конец)} для ключей верхнего уровня; конец — строка следующего ключа или len."""
    starts = [(i, m.group(1)) for i, ln in enumerate(lines) if (m := _KEY_RE.match(ln))]
    out = {}
    for n, (i, key) in enumerate(starts):
        out.setdefault(key, (i, starts[n + 1][0] if n + 1 < len(starts) else len(lines)))
    return out


def _block_end(lines: list[str], start: int, end: int) -> int:
    """Позиция вставки в конец блока — после последней непустой строки."""
    pos = end
    while pos - 1 > start and not lines[pos - 1].strip():
        pos -= 1
    return pos


def _child_indent(lines: list[str], start: int, end: int, default: int = 2) -> int:
    for ln in lines[start + 1:end]:
        s = ln.strip()
        if s and not s.startswith("#"):
            return len(ln) - len(ln.lstrip(" "))
    return default


def _dump_kv(key: str, value, indent: int) -> list[str]:
    text = yaml.safe_dump({key: value}, allow_unicode=True, sort_keys=False, default_flow_style=False, width=10 ** 6)
    return [(" " * indent + ln) if ln else ln for ln in text.rstrip("\n").split("\n")]


def _scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, list):
        return "[" + ", ".join(_scalar(x) for x in v) + "]"
    s = str(v)
    if _DATE_RE.match(s) or (_PLAIN_RE.match(s) and yaml.safe_load(f"x: {s}") == {"x": s}):
        return s
    return json.dumps(s, ensure_ascii=False)


def _entry_lines(entry: dict, indent: int) -> list[str]:
    out = []
    for n, (k, v) in enumerate(entry.items()):
        prefix = " " * indent + "- " if n == 0 else " " * (indent + 2)
        out.append(f"{prefix}{k}: {_scalar(v)}")
    return out


def _append_list_item(text: str, key: str, entry: dict) -> str:
    """Дописывает запись в список верхнего уровня `key` (создаёт ключ в конце файла, если его нет)."""
    lines = text.rstrip("\n").split("\n")
    blocks = _top_blocks(lines)
    if key in blocks:
        s, e = blocks[key]
        pos = _block_end(lines, s, e)
        ind = _child_indent(lines, s, e)
        lines[pos:pos] = _entry_lines(entry, ind)
    else:
        lines += ["", f"{key}:"] + _entry_lines(entry, 2)
    return "\n".join(lines) + "\n"


def _add_months(d: date, months: int) -> date:
    idx = d.year * 12 + d.month - 1 + months
    y, m = idx // 12, idx % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _as_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "")[:10]
    return date.fromisoformat(s) if _DATE_RE.match(s) else None


def _stem(ref) -> str:
    b = os.path.basename(str(ref).strip())
    for ext in (".yaml", ".md"):
        if b.endswith(ext):
            b = b[: -len(ext)]
    return b


def _cell(v) -> str:
    return " ".join(str(v if v is not None else "—").split()).replace("|", "\\|")


def _mojibake(text: str, name: str, issues: list) -> None:
    hit = next((p for p in _MOJIBAKE if p in text), None)
    if hit:
        i = text.index(hit)
        issues.append({"source": "encoding", "file": name, "field": "encoding", "severity": "blocking",
                       "expected": "UTF-8 без mojibake (E2)", "actual": text[max(0, i - 20):i + 30]})


def _collect(issues: list, result: dict, source: str, name: str) -> None:
    for it in result.get("issues") or []:
        issues.append({"source": source, "file": name, **it})


def _blocking(issues: list) -> list:
    return [i for i in issues if i.get("severity") == "blocking"]


# ---------------------------------------------------------------------------
# Сборка прогноза и сценариев (B4 / C4): заголовок + блок Events YAML как есть + недостающие поля
# ---------------------------------------------------------------------------

def _header(type_: str, ref_key: str, ref: str, ev: dict, replaces: list[str]) -> list[str]:
    head = [("schema_version", "schema_version: 1"), ("type", f"type: {type_}"),
            (ref_key, f"{ref_key}: {ref}"), ("status", "status: active")]
    out = [line for k, line in head if k not in ev]
    if replaces and "replaces" not in ev:
        out += ["replaces:"] + [f"  - {r}" for r in replaces]
    return out


def _fill_mapping(lines: list[str], key: str, values: dict) -> list[str]:
    """Дописывает в конец блока `key` недостающие поля `values` (в порядке словаря)."""
    s, e = _top_blocks(lines)[key]
    pos, ind = _block_end(lines, s, e), _child_indent(lines, s, e)
    new = []
    for k, v in values.items():
        new += _dump_kv(k, v, ind)
    lines[pos:pos] = new
    return lines


def _reviews_fill(lines: list[str], ev: dict, interval, base: date, issues: list, name: str) -> list[str]:
    rv = ev.get("reviews")
    if rv is None:
        if not interval:
            issues.append({"source": "promote-draft", "file": name, "field": "reviews.interval_months",
                           "severity": "blocking", "expected": "interval в блоке или review_interval_months во frontmatter",
                           "actual": None})
            return lines
        lines += ["", "reviews:"] + _dump_kv("interval_months", int(interval), 2) \
            + _dump_kv("next_due", _add_months(base, int(interval)), 2) \
            + ["  last_completed: null", "  history: []"]
        return lines
    if not isinstance(rv, dict):
        return lines
    add = {}
    iv = rv.get("interval_months") or interval
    if "interval_months" not in rv and interval:
        add["interval_months"] = int(interval)
    if "next_due" not in rv and iv and base:
        add["next_due"] = _add_months(base, int(iv))
    if "last_completed" not in rv:
        add["last_completed"] = None
    if "history" not in rv:
        add["history"] = []
    return _fill_mapping(lines, "reviews", add) if add else lines


def _final_audit(lines: list[str], ev: dict, horizon) -> list[str]:
    if "final_audit" in ev:
        return lines
    return lines + ["", "final_audit:"] + _dump_kv("due", _as_date(horizon) or horizon, 2) + ["  status: pending"]


def _pick_resolve(ev: dict, forced, issues: list, notes: list, name: str):
    """B4.6: ближайший резолв в окне ~4 мес. от даты прогноза, у которого есть запись fca_stats."""
    fs = ev.get("fca_stats") if isinstance(ev.get("fca_stats"), dict) else {}
    keys = {str(k)[:10]: k for k in fs}
    if forced:
        if str(forced) not in keys:
            issues.append({"source": "promote-draft", "file": name, "field": "outcome_resolve", "severity": "blocking",
                           "expected": f"дата из fca_stats {sorted(keys)}", "actual": str(forced)})
            return None
        return str(forced)
    fdate = _as_date((ev.get("forecast") or {}).get("date"))
    if not fs or not fdate:
        notes.append("outcome_log: fca_stats нет — заморозка пропущена (B4.6, best-effort)")
        return None
    limit = _add_months(fdate, 4)
    cands = {str(_as_date(h)) for h in (ev.get("forecast") or {}).get("horizons") or [] if _as_date(h)}
    for m in ev.get("monitoring") or []:
        if isinstance(m, dict) and m.get("auto_checkable") is True and _as_date(m.get("check_date")):
            cands.add(str(_as_date(m.get("check_date"))))
    window = sorted(c for c in cands if fdate <= date.fromisoformat(c) <= limit)
    chosen = next((c for c in window if c in keys), None)
    skipped = [c for c in window if c not in keys and (chosen is None or c < chosen)]
    if skipped:
        notes.append(f"outcome_log: резолвы без записи fca_stats пропущены: {', '.join(skipped)}")
    if not chosen:
        notes.append(f"outcome_log: в окне до {limit} нет резолва с fca_stats — заморозка не нужна")
    return chosen


def _freeze(fs_entry: dict, resolve, logged_at, record_type, confidence, issues: list, name: str):
    res = aa.freeze_outcome_log({"fca_stats_entry": fs_entry, "resolve_date": resolve, "logged_at": logged_at,
                                 "record_type": record_type, "confidence_at_forecast": confidence})
    _collect(issues, {"issues": [i for i in res["issues"] if i.get("severity") == "blocking"]},
             "freeze-outcome-log", name)
    return res["entry"]


def build_forecast(md_text: str, ev_text: str, target: str, opts: dict, issues: list, notes: list):
    name = f"{target}.yaml"
    fm = _fm_dict(md_text)
    ev = yaml.safe_load(ev_text) or {}
    if not isinstance(ev, dict) or not isinstance(ev.get("forecast"), dict):
        raise Refusal("в .events.yaml нет блока forecast: — это не блок Events YAML прогноза")
    fc = ev["forecast"]
    replaces = [_stem(r) for r in (fm.get("replaces") if isinstance(fm.get("replaces"), list)
                                   else [fm["replaces"]] if fm.get("replaces") else [])]
    if opts.get("replaces") and _stem(opts["replaces"]) not in replaces:
        replaces.append(_stem(opts["replaces"]))
    lines = _header("forecast-events", "forecast_ref", f"{target}.md", ev, replaces) + [""] \
        + ev_text.rstrip("\n").split("\n")
    # B4.1: недостающие поля forecast — из frontmatter .md
    add = {}
    for k, src in (("date", "forecast_date"), ("horizon", "horizon_date"), ("domain", "domain"), ("topic", "topic"),
                   ("method", "method")):
        if k not in fc and fm.get(src) is not None:
            add[k] = fm[src]
    if "horizons" not in fc:
        add["horizons"] = fm.get("horizons") or ([fm["horizon_date"]] if fm.get("horizon_date") else [])
    if "upstream_snapshot" not in fc:
        add["upstream_snapshot"] = fm.get("upstream_snapshot") or []
    if add:
        lines = _fill_mapping(lines, "forecast", add)
    base = _as_date(fc.get("date") or fm.get("forecast_date"))
    lines = _reviews_fill(lines, ev, fm.get("review_interval_months"), base, issues, name)
    lines = _final_audit(lines, ev, fc.get("horizon") or fm.get("horizon_date"))
    text = "\n".join(lines).rstrip("\n") + "\n"
    # B4.6: заморозка outcome_log
    full = yaml.safe_load(text) or {}
    if "outcome_log" not in ev and not opts.get("no_outcome_log"):
        resolve = _pick_resolve(full, opts.get("outcome_resolve"), issues, notes, name)
        if resolve:
            fs = {str(k)[:10]: v for k, v in (full.get("fca_stats") or {}).items()}
            entry = _freeze(fs[resolve], resolve, opts["today"], "horizon_resolve",
                            (full.get("forecast") or {}).get("confidence"), issues, name)
            text = _append_list_item(text, "outcome_log", entry)
            notes.append(f"outcome_log: заморожен резолв {resolve} из fca_stats")
    # .md: без технических секций; replaces во frontmatter
    md = _strip_events_sections(md_text)
    if opts.get("replaces") and not fm.get("replaces"):
        fmt, body = _split_fm(md)
        if fmt is not None:
            md = f"---\n{fmt}replaces: {_stem(opts['replaces'])}.yaml\n---\n{body}"
    return md, text


def build_scenario(md_text: str, ev_text: str, target: str, opts: dict, issues: list, notes: list):
    name = f"{target}.yaml"
    ev = yaml.safe_load(ev_text) or {}
    if not isinstance(ev, dict) or not isinstance(ev.get("matrix"), dict):
        raise Refusal("в .events.yaml нет блока matrix: — это не блок Events YAML сценариев")
    mx = ev["matrix"]
    fm = _fm_dict(md_text)
    replaces = [_stem(fm["replaces"])] if fm.get("replaces") else []
    if opts.get("replaces") and _stem(opts["replaces"]) not in replaces:
        replaces.append(_stem(opts["replaces"]))
    lines = _header("scenario-events", "scenario_ref", f"{target}.md", ev, replaces) + [""] \
        + ev_text.rstrip("\n").split("\n")
    lines = _reviews_fill(lines, ev, 6, _as_date(mx.get("date")), issues, name)
    lines = _final_audit(lines, ev, mx.get("horizon"))
    text = "\n".join(lines).rstrip("\n") + "\n"
    md = _strip_events_sections(md_text)
    fmt, body = _split_fm(md)
    if fmt is None:  # C2: frontmatter из блока matrix
        head = {"schema_version": 1, "type": "scenario-matrix", "date_created": mx.get("date"),
                "horizon": mx.get("horizon"), "domain": mx.get("domain"), "topic": mx.get("topic")}
        if replaces:
            head["replaces"] = replaces[0]
        head.update({"axis_x": mx.get("axis_x"), "axis_y": mx.get("axis_y"),
                     "scenarios": [t.get("label") for t in ev.get("scenario_triggers") or [] if isinstance(t, dict)]})
        md = "---\n" + yaml.safe_dump(head, allow_unicode=True, sort_keys=False, width=10 ** 6) + "---\n\n" + md.lstrip("\n")
        notes.append("frontmatter .md собран из блока matrix (C2)")
    elif opts.get("replaces") and not fm.get("replaces"):
        md = f"---\n{fmt}replaces: {_stem(opts['replaces'])}\n---\n{body}"
    return md, text


# ---------------------------------------------------------------------------
# Пометка прежней версии (B5(a) / C5): status: superseded + superseded_by; у прогноза — interim-снимок
# ---------------------------------------------------------------------------

def supersede(old_text: str, new_yaml: str, kind: str, opts: dict, issues: list, notes: list, name: str) -> str:
    before = yaml.safe_load(old_text) or {}
    lines = old_text.rstrip("\n").split("\n")
    blocks = _top_blocks(lines)
    if "status" not in blocks:
        raise Refusal(f"{name}: нет поля status верхнего уровня")
    if before.get("status") != "active":
        notes.append(f"{name}: прежний status «{before.get('status')}» — помечается superseded по указанию")
    s, _ = blocks["status"]
    lines[s] = "status: superseded"
    if "superseded_by" in blocks:
        lines[blocks["superseded_by"][0]] = f"superseded_by: {new_yaml}"
    else:
        lines.insert(s + 1, f"superseded_by: {new_yaml}")
    text = "\n".join(lines) + "\n"
    if kind == "forecast" and not opts.get("no_interim"):
        fs = {str(k)[:10]: v for k, v in (before.get("fca_stats") or {}).items()} \
            if isinstance(before.get("fca_stats"), dict) else {}
        when = _as_date(opts.get("new_date"))
        later = sorted(k for k in fs if when and _DATE_RE.match(k) and date.fromisoformat(k) >= when)
        if not fs:
            notes.append(f"{name}: fca_stats нет — промежуточный снимок пропущен")
        elif not later:
            notes.append(f"{name}: все горизонты fca_stats до даты замены — промежуточный снимок пропущен")
        else:
            entry = _freeze(fs[later[0]], when, opts["today"], "interim_supersession",
                            (before.get("forecast") or {}).get("confidence"), issues, name)
            if opts.get("actual") is not None and entry.get("kind") == "level":
                entry["actual"] = float(opts["actual"])
                done = aa.complete_outcome_log({"entry": entry})
                _collect(issues, {"issues": [i for i in done["issues"] if i.get("severity") == "blocking"]},
                         "complete-outcome-log", name)
                entry = done["entry"]
            if opts.get("actual_source"):
                entry["actual_source"] = opts["actual_source"]
            if opts.get("interim_note"):
                entry["note"] = opts["interim_note"]
            text = _append_list_item(text, "outcome_log", entry)
            notes.append(f"{name}: interim_supersession на {when} (заморозка горизонта {later[0]}"
                         + (f", факт {opts['actual']})" if opts.get("actual") is not None else ", факт null)"))
    after = yaml.safe_load(text) or {}
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    if not changed <= {"status", "superseded_by", "outcome_log"}:
        raise Refusal(f"{name}: правка задела лишние поля {sorted(changed)}")
    return text


# ---------------------------------------------------------------------------
# Регистрация: update_index.py (add-rows, sync-log) + пункт списка мониторинга в корневом INDEX
# ---------------------------------------------------------------------------

def _call_ui(fn, payload: dict) -> dict:
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            return fn(payload)
    except SystemExit:
        try:
            return json.loads(buf.getvalue())
        except json.JSONDecodeError:
            return {"ok": False, "error": buf.getvalue().strip()}


def _add_bullet(index_path: str, section: str, line: str, key: str, backup_dir: str, dry: bool) -> dict:
    if not os.path.isfile(index_path):
        return {"ok": False, "error": f"файл не найден: {index_path}"}
    content = _read(index_path)
    lines = content.split("\n")
    sec = ui._find_section(lines, section)
    if sec < 0:
        return {"ok": False, "error": f"секция не найдена: {section}"}
    end = ui._section_bounds(lines, sec)
    if any(key in ln for ln in lines[sec + 1:end]):
        return {"ok": True, "inserted": [], "skipped_existing": [key], "dry_run": dry}
    pos = sec + 1
    while pos < end and not lines[pos].strip():
        pos += 1
    if pos == end:
        pos = sec + 1
        lines[pos:pos] = ["", line]
    else:
        lines[pos:pos] = [line]
    backup = ui._backup(index_path, backup_dir, dry)
    ui._write(index_path, "\n".join(lines), dry)
    return {"ok": True, "inserted": [key], "backup": backup, "dry_run": dry}


# Шапки INDEX по образцу живых файлов (B7, C7, E6, G4, L6, D6): создаются, если файла нет
_FC_ACTIVE = ("## Активные прогнозы",
              "| File | Type | Topic | Forecast date | Horizon | Status | Central estimate / confidence |\n"
              "|------|------|-------|---------------|---------|--------|-------------------------------|")
_FC_SUPER = ("## Сменённые версии (superseded)",
             "| File | Type | Topic | Forecast date | Status | Superseded by |\n"
             "|------|------|-------|---------------|--------|---------------|")
_SC_ACTIVE = ("## Активные матрицы",
              "| File | Type | Topic | Created | Horizon | Status | Axes |\n"
              "|------|------|-------|---------|---------|--------|------|")
_SC_SUPER = ("## Сменённые версии (superseded)",
             "| File | Topic | Created | Status | Superseded by |\n"
             "|------|-------|---------|--------|---------------|")
SUPERSEDED = {"forecasts/INDEX.md": _FC_SUPER, "scenarios/INDEX.md": _SC_SUPER}


def _sect(spec) -> str:
    return f"{spec[0]}\n\n{spec[1]}\n"


INDEX_TEMPLATES = {
    "forecasts/INDEX.md": "# Forecasts — Index\n\nКаталог прогнозов (Tier 1 = FCA, Tier 2 = FCA+HST).\n\n"
                          + _sect(_FC_ACTIVE) + "\n---\n\n" + _sect(_FC_SUPER),
    "scenarios/INDEX.md": "# Scenarios — Index\n\nКаталог сценарных матриц 2×2 (Shell Scenario Planning).\n\n"
                          + _sect(_SC_ACTIVE) + "\n---\n\n" + _sect(_SC_SUPER),
    "Portfolio/INDEX.md": "# Claude-Memory · Portfolio · INDEX\n\n## Активные артефакты\n\n### stress/\n\n"
                          "| Файл | Дата | Macro input | Status |\n|---|---|---|---|\n\n### integrated-views/\n\n"
                          "| Файл | Тип | Дата | Inputs |\n|---|---|---|---|\n",
    "reports/INDEX.md": "# reports/INDEX.md\n\nАрхив полных отчётов ретроспективных аудитов; парный профиль — "
                        "`domains/{domain}/{source-slug}-{period}.md`.\n\n"
                        "| Файл | source | period | audit_date | domain | linked_forecast |\n"
                        "|------|--------|--------|------------|--------|-----------------|\n",
    "INDEX.md": "# Claude Memory — Master Index\n\n## Активные мониторинговые отчёты\n\n## Архив monitor-reports\n",
}


def _supersede_index(path: str, active: str, keys: list[str], index_rel: str, kind: str, new_stem: str,
                     bdir: str, dry: bool) -> dict:
    """B5(a)/C5: строки прежней версии уходят из активной секции в «Сменённые версии» (раздела нет — создаётся в
    конце файла); статус — superseded, последняя колонка — новая версия."""
    lines = _read(path).split("\n")
    sec = ui._find_section(lines, active)
    if sec < 0:
        return {"ok": False, "error": f"секция не найдена: {active}"}
    end = ui._section_bounds(lines, sec)
    found = [i for i in range(sec + 1, end) if lines[i].strip().startswith("|") and ui._first_cell(lines[i]) in keys]
    if not found:
        return {"ok": True, "moved": [], "missing": True}
    moved, topic, created = [], None, None
    for i in found:
        c = [x.strip() for x in lines[i].strip().strip("|").split("|")]
        is_md = ui._first_cell(lines[i]).rstrip(")").endswith(".md")
        if kind == "forecast":
            moved.append(f"| {c[0]} | {c[1]} | {c[2]} | {c[3]} | superseded | "
                         f"{new_stem if is_md else new_stem + '.yaml'} |")
        else:
            if is_md:
                topic, created = c[2], c[3]
            moved.append(f"| {c[0]} | {topic or c[2]} | {created if not is_md and topic else c[3]} | superseded | "
                         f"→ {new_stem} |")
    for i in reversed(found):
        del lines[i]
    head, table = SUPERSEDED[index_rel]
    sup = ui._find_section(lines, head)
    if sup < 0:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "---", "", head, ""] + table.split("\n") + [""]
        sup = ui._find_section(lines, head)
    send = ui._section_bounds(lines, sup)
    sep = next((i for i in range(sup + 1, send) if ui._TABLE_SEP.match(lines[i])), -1)
    if sep < 0:
        return {"ok": False, "error": f"в секции {head} нет таблицы"}
    pos = ui.table_insert_pos(lines, sep, send, "auto")
    lines[pos:pos] = moved
    backup = ui._backup(path, bdir, dry)
    ui._write(path, "\n".join(lines), dry)
    return {"ok": True, "moved": moved, "section": head, "backup": backup}


def _link(name: str) -> str:
    return f"[{name}]({name})"


# ---------------------------------------------------------------------------
# Виды
# ---------------------------------------------------------------------------

def _draft_paths(root: str, kind: str, draft: str) -> dict:
    d = os.path.join(root, DRAFTS)
    if kind in ("forecast", "scenario"):
        return {"md": os.path.join(d, f"{draft}.md"), "events": os.path.join(d, f"{draft}.events.yaml")}
    if kind == "stress":
        return {"md": os.path.join(d, f"{draft}.md"), "yaml": os.path.join(d, f"{draft}.yaml")}
    if kind == "integrated-view":
        return {"md": os.path.join(d, f"{draft}.md")}
    if kind == "monitor-report":
        return {"yaml": os.path.join(d, f"{draft}.yaml")}
    m = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+?)-(\d{4}(?:-\d{4})?)$", draft)
    if not m:
        raise Refusal(f"ретро-аудит: имя черновика `<YYYY-MM-DD>-<source-slug>-<period>` не распознано: {draft}")
    return {"report": os.path.join(d, f"{draft}.md"),
            "profile": os.path.join(d, f"{m.group(2)}-{m.group(3)}-profile.md")}


def promote(opts: dict) -> dict:
    root = os.path.abspath(os.path.expanduser(opts["root"]))
    kind, draft, dry = opts["kind"], opts["draft"], bool(opts.get("dry_run"))
    today = opts["today"]
    if not dry:
        hub_settings.require_ai(root, "promote_draft.py", "приёмка черновика", zones=("Portfolio", "scenarios"))   # вход — вывод модели: при «без ИИ» отказ
    issues, notes, pending = [], [], []
    out = {"ok": False, "kind": kind, "draft": draft, "written": [], "replaced": None, "index_rows": [],
           "index_pending": pending, "sync_log_line": None, "draft_removed": False, "issues": issues,
           "notes": notes, "dry_run": dry}
    if not os.path.isdir(root):
        raise Refusal(f"корень не найден: {root}")
    src = _draft_paths(root, kind, draft)
    missing = [os.path.relpath(p, root) for p in src.values() if not os.path.isfile(p)]
    if missing:
        raise Refusal(f"нет файлов черновика: {', '.join(missing)}")
    texts = {k: _read(p) for k, p in src.items()}
    for k, t in texts.items():
        _mojibake(t, os.path.relpath(src[k], root), issues)
    target = opts.get("as_name") or draft
    files: dict[str, str] = {}      # относительный путь → содержимое
    index_plan: list[dict] = []     # {index, section, rows, replace?} | {bullet…}
    old_rel = None
    if opts.get("replaces"):
        if kind not in ("forecast", "scenario"):
            raise Refusal("--replaces — только для прогноза и сценариев (B5/C5)")
        rel = opts["replaces"].strip()
        folder = "forecasts" if kind == "forecast" else "scenarios"
        old_rel = rel if "/" in rel else f"{folder}/{rel}"
        old_rel = f"{os.path.dirname(old_rel)}/{_stem(old_rel)}.yaml"
        if not os.path.isfile(os.path.join(root, old_rel)):
            raise Refusal(f"прежняя версия не найдена: {old_rel}")

    if kind in ("forecast", "scenario"):
        folder = "forecasts" if kind == "forecast" else "scenarios"
        ev_text = _strip_fence(texts["events"])
        build = build_forecast if kind == "forecast" else build_scenario
        md, y = build(texts["md"], ev_text, target, opts, issues, notes)
        files[f"{folder}/{target}.md"], files[f"{folder}/{target}.yaml"] = md, y
        _collect(issues, aa.check_yaml_duplicates({"yaml_text": y, "file": f"{target}.yaml"}),
                 "check-yaml-duplicates", f"{target}.yaml")
        doc = yaml.safe_load(y) or {}
        fm = _fm_dict(md)
        if kind == "forecast":
            _collect(issues, aa.validate_forecast_frontmatter(fm), "validate-forecast", f"{target}.md")
            _collect(issues, aa.validate_forecast_events({**doc, "_strict": True}), "validate-forecast-events",
                     f"{target}.yaml")
            fc = doc.get("forecast") or {}
            tier = "events Tier 2" if any(k in doc for k in _TIER2_KEYS) else "events Tier 1"
            tier += " (isolated)" if doc.get("isolated") else ""
            rows = [f"| {_link(target + '.md')} | forecast | {_cell(fc.get('topic'))} | {_cell(fc.get('date'))} | "
                    f"{_cell(fc.get('horizon'))} | active | {_cell(fc.get('central_estimate'))} |",
                    f"| {_link(target + '.yaml')} | {tier} | (см. ↑) | — | — | — | confidence: {_cell(fc.get('confidence'))} |"]
            index_plan.append({"index": "forecasts/INDEX.md", "section": "## Активные прогнозы", "rows": rows,
                               "position": "auto"})
            log = (f"{today} | save-to-library | forecasts/{target}.{{md,yaml}} | Workflow B (promote-draft) | "
                   f"topic: {fc.get('topic')} | method: {fc.get('method')} | confidence: {fc.get('confidence')} | "
                   f"horizon: {fc.get('horizon')} | next_due: {(doc.get('reviews') or {}).get('next_due')}")
            opts["new_date"] = fc.get("date")
        else:
            _collect(issues, aa.validate_scenario_events(doc), "validate-scenario-events", f"{target}.yaml")
            mx = doc.get("matrix") or {}
            labels = " / ".join(str(t.get("label")) for t in doc.get("scenario_triggers") or [] if isinstance(t, dict))
            rows = [f"| {_link(target + '.md')} | scenario-matrix | {_cell(mx.get('topic'))} | {_cell(mx.get('date'))} | "
                    f"{_cell(mx.get('horizon'))} | active | {_cell(mx.get('axis_x'))} × {_cell(mx.get('axis_y'))} |",
                    f"| {_link(target + '.yaml')} | [events scenarios] | (см. ↑) | — | — | — | "
                    f"{len(doc.get('scenario_triggers') or [])} сценария: {_cell(labels)} |"]
            index_plan.append({"index": "scenarios/INDEX.md", "section": "## Активные матрицы", "rows": rows,
                               "position": "auto"})
            log = (f"{today} | save-to-library | scenarios/{target}.{{md,yaml}} | Workflow C (promote-draft) | "
                   f"topic: {mx.get('topic')} | horizon: {mx.get('horizon')}")
            opts["new_date"] = mx.get("date")
        if old_rel:
            old_text = _read(os.path.join(root, old_rel))
            files[old_rel] = supersede(old_text, f"{target}.yaml", kind, opts, issues, notes, old_rel)
            old_doc = yaml.safe_load(old_text) or {}
            new_old = yaml.safe_load(files[old_rel]) or {}
            if kind == "forecast":
                bb = len(_blocking(aa.validate_forecast_events(old_doc)["issues"]))
                ba = aa.validate_forecast_events(new_old)
                if len(_blocking(ba["issues"])) > bb:
                    _collect(issues, ba, "validate-forecast-events", old_rel)
            stem = _stem(old_rel)
            idx = f"{folder}/INDEX.md"
            sec = index_plan[-1]["section"]
            keys = [_link(stem + ".md"), _link(stem + ".yaml"), stem + ".md", stem + ".yaml"]
            index_plan.append({"index": idx, "section": sec, "supersede": keys, "kind": kind, "new_stem": target,
                               "old_stem": stem})
            out["replaced"] = old_rel
            log += f" | {stem} → superseded"
    elif kind == "stress":
        files[f"Portfolio/stress/{target}.md"] = texts["md"]
        files[f"Portfolio/stress/{target}.yaml"] = texts["yaml"]
        _collect(issues, aa.check_yaml_duplicates({"yaml_text": texts["yaml"], "file": f"{target}.yaml"}),
                 "check-yaml-duplicates", f"{target}.yaml")
        doc = yaml.safe_load(texts["yaml"]) or {}
        _collect(issues, aa.validate_stress(doc), "validate-stress", f"{target}.yaml")
        rows = [f"| {target}.md/.yaml | {_cell(doc.get('date'))} | {_cell(doc.get('scenario_source'))}; "
                f"snapshot: {_cell(doc.get('portfolio_snapshot_id'))} | active |"]
        index_plan.append({"index": "Portfolio/INDEX.md", "section": "### stress/", "rows": rows, "position": "end"})
        log = (f"{today} | save-to-library | Portfolio/stress/{target}.{{md,yaml}} | Workflow E (promote-draft) | "
               f"scenario_source: {doc.get('scenario_source')} | snapshot: {doc.get('portfolio_snapshot_id')}")
    elif kind == "integrated-view":
        files[f"Portfolio/integrated-views/{target}.md"] = texts["md"]
        try:
            fm = _fm_dict(texts["md"])
        except yaml.YAMLError as exc:
            raise Refusal(f"frontmatter вида не разобран как YAML: {exc}")
        _collect(issues, aa.validate_integrated_view(fm), "validate-integrated-view", f"{target}.md")
        n_sec = sum(1 for ln in texts["md"].split("\n") if ln.startswith("## "))
        if n_sec < 5:
            issues.append({"source": "promote-draft", "file": f"{target}.md", "field": "sections", "severity": "warning",
                           "expected": "≥5 секций (G2.2)", "actual": n_sec})
        inp = fm.get("inputs") if isinstance(fm.get("inputs"), dict) else {}
        used = " + ".join(str(inp[k]) for k in ("snapshot", "stress", "review_stock", "review_bond") if inp.get(k)) or "—"
        rows = [f"| {target}.md | integrated-view | {_cell(fm.get('view_date'))} | {_cell(used)} |"]
        index_plan.append({"index": "Portfolio/INDEX.md", "section": "### integrated-views/", "rows": rows,
                           "position": "end"})
        log = (f"{today} | save-to-library | Portfolio/integrated-views/{target}.md | Workflow G (promote-draft) | "
               f"schema {fm.get('schema_version')}")
        notes.append("G5: напоминание в календаре и строка «Self-validation roadmap» — моделью")
    elif kind == "monitor-report":
        files[f"monitor-reports/{target}.yaml"] = texts["yaml"]
        _collect(issues, aa.check_yaml_duplicates({"yaml_text": texts["yaml"], "file": f"{target}.yaml"}),
                 "check-yaml-duplicates", f"{target}.yaml")
        doc = yaml.safe_load(texts["yaml"]) or {}
        aa._monitoring_context_from_root(doc, root)
        _collect(issues, aa.validate_monitor_report(doc), "validate-monitor-report", f"{target}.yaml")
        al = [a for a in doc.get("alerts") or [] if isinstance(a, dict)]
        cnt = {s: sum(1 for a in al if a.get("severity") == s) for s in ("HIGH", "MEDIUM", "LOW")}
        bullet = (f"- `{target}` · {cnt['HIGH']} HIGH · {cnt['MEDIUM']} MEDIUM · {cnt['LOW']} LOW → "
                  f"[monitor-reports/{target}.yaml](monitor-reports/{target}.yaml)")
        index_plan.append({"index": "INDEX.md", "section": "## Активные мониторинговые отчёты", "bullet": bullet,
                           "key": f"`{target}`"})
        log = (f"{today} | save-to-library | monitor-reports/{target}.yaml | Workflow L (promote-draft) | "
               f"alerts: {len(al)} ({cnt['HIGH']} HIGH, {cnt['MEDIUM']} MEDIUM)")
        if doc.get("outcome_log_updates"):
            notes.append(f"L5.5: outcome_log_updates ×{len(doc['outcome_log_updates'])} — применить к forecasts/ моделью")
        notes.append("L6: перенос отчётов старше 30 дней в «## Архив monitor-reports» — моделью")
    else:  # retro-audit
        prof_fm = _fm_dict(texts["profile"])
        rep_fm = _fm_dict(texts["report"])
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-(.+?)-(\d{4}(?:-\d{4})?)$", draft)
        audit_date, slug, period = m.group(1), m.group(2), m.group(3)
        domain = opts.get("domain") or prof_fm.get("domain") or rep_fm.get("domain")
        if not domain:
            sub = aa.determine_subfolder(aa.flatten_trust(prof_fm.get("trust") or {}))
            domain = sub.get("recommended")
            if domain:
                notes.append(f"домен {domain} — по trust-субдоменам (A3): {sub.get('counts')}")
            else:
                raise Refusal(f"домен не определён ({sub.get('reason')}) — передай --domain")
        report_rel, profile_rel = f"reports/{draft}.md", f"domains/{domain}/{slug}-{period}.md"
        files[report_rel], files[profile_rel] = texts["report"], texts["profile"]
        _collect(issues, aa.validate_audit_frontmatter(prof_fm), "validate-audit", profile_rel)
        _collect(issues, aa.validate_retro_audit_paths({"report_path": report_rel, "profile_path": profile_rel,
                                                        "source_slug": slug, "period": period,
                                                        "audit_date": audit_date, "only": None}),
                 "validate-retro-audit-paths", report_rel)
        if not os.path.isdir(os.path.join(root, "domains", domain)):
            notes.append(f"папки domains/{domain}/ нет — будет создана")
        inc = aa.compute_inclusion(bool(prof_fm.get("pin")), aa.flatten_trust(prof_fm.get("trust") or {}))
        notes.append(f"auto-inclusion (A4): {inc.get('include_in_memory')} — {inc.get('reason')}")
        rows = [f"| {draft}.md | {_cell(prof_fm.get('source') or rep_fm.get('source'))} | {period} | {audit_date} | "
                f"{domain} | {_cell(prof_fm.get('linked_forecast') or rep_fm.get('linked_forecast') or '—')} |"]
        index_plan.append({"index": "reports/INDEX.md", "section": "reports/INDEX.md", "rows": rows,
                           "position": "auto"})
        pending.append(f"domains/{domain}/INDEX.md: строку профиля — по образцу соседних (формат у доменов разный); "
                       f"или передать её в index_rows")
        log = (f"{today} | save-to-library | {report_rel} + {profile_rel} | Workflow D (promote-draft) | "
               f"source: {prof_fm.get('source')} | period: {period}")

    # Строки INDEX от модели заменяют шаблонные для своего файла
    custom = opts.get("index_rows") or {}
    if custom:
        index_plan = [p for p in index_plan if p["index"] not in custom or p.get("supersede")]
        for idx, spec in custom.items():
            index_plan.append({"index": idx, "section": spec["section"], "rows": spec["rows"],
                               "position": spec.get("position", "auto")})
            pending[:] = [p for p in pending if not p.startswith(idx)]

    # Занятые имена
    new_paths = [r for r in files if r != old_rel]
    taken = [r for r in new_paths if os.path.exists(os.path.join(root, r))]
    if taken and not opts.get("force"):
        issues.append({"source": "promote-draft", "file": ", ".join(taken), "field": "target", "severity": "blocking",
                       "expected": "свободное имя (или --force / --as <имя>)", "actual": "файл уже есть"})
    if not os.path.isfile(os.path.join(root, "_sync_log.md")):
        issues.append({"source": "promote-draft", "file": "_sync_log.md", "field": "sync_log", "severity": "blocking",
                       "expected": "файл существует", "actual": None})

    # Регистрация: предварительный прогон (dry_run) — секции и таблицы должны найтись до записи
    out["index_created"] = []

    def register(really: bool) -> None:
        out["index_rows"] = []
        for p in index_plan:
            path = os.path.join(root, p["index"])
            bdir = os.path.join(root, ".backups", os.path.dirname(p["index"]) or "root")
            if not os.path.isfile(path):
                if p["index"] not in INDEX_TEMPLATES:
                    if not really:
                        pending.append(f"{p['index']}: файла нет, формат строки скрипту не известен — добавить вручную")
                    continue
                if p["index"] not in out["index_created"]:
                    out["index_created"].append(p["index"])
                if not really:
                    continue                     # шаблон заведомо содержит секцию; в dry-run файл не создаётся
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(INDEX_TEMPLATES[p["index"]])
            if "supersede" in p:
                res = _supersede_index(path, p["section"], p["supersede"], p["index"], p["kind"], p["new_stem"],
                                       bdir, not really)
                if res.get("missing") and not really:
                    pending.append(f"{p['index']}: строки прежней версии {p['old_stem']} в «{p['section']}» нет — "
                                   f"в «Сменённые версии» не перенесены")
                if res.get("ok"):
                    out["index_rows"].append({"index": p["index"], "section": res.get("section"),
                                              "rows": res.get("moved"), "moved_from": p["section"]})
                    continue
                rows = []
            elif "bullet" in p:
                res = _add_bullet(path, p["section"], p["bullet"], p["key"], bdir, not really)
                rows = [p["bullet"]]
            else:
                res = _call_ui(ui.cmd_add_rows, {"index_path": path, "section": p["section"], "rows": p["rows"],
                                                 "position": p.get("position", "top"), "backup_dir": bdir,
                                                 "dry_run": not really})
                rows = p["rows"]
            if not res.get("ok"):
                issues.append({"source": "update_index", "file": p["index"], "field": p["section"],
                               "severity": "warning" if really else "blocking", "expected": "секция с таблицей",
                               "actual": res.get("error")})
                continue
            out["index_rows"].append({"index": p["index"], "section": p["section"], "rows": rows,
                                      "inserted": res.get("inserted"), "replaced": res.get("replaced"),
                                      "skipped_existing": res.get("skipped_existing")})

    register(False)
    out["sync_log_line"] = log
    if _blocking(issues):
        out["written"] = []
        return out
    out["written"] = sorted(new_paths)
    if dry:
        out["ok"] = True
        out["would_remove"] = [] if opts.get("keep_draft") else sorted(os.path.relpath(p, root) for p in src.values())
        return out

    # Запись: все временные файлы, затем rename; прежняя версия — с копией в .backups/
    if old_rel:
        bdir = os.path.join(root, ".backups", os.path.dirname(old_rel))
        os.makedirs(bdir, exist_ok=True)
        shutil.copy2(os.path.join(root, old_rel), os.path.join(
            bdir, f"{os.path.basename(old_rel)}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"))
    tmps = []
    for rel, content in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp-promote"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(content)
        tmps.append((tmp, path))
    for tmp, path in tmps:
        os.replace(tmp, path)
    register(True)
    res = _call_ui(ui.cmd_sync_log, {"log_path": os.path.join(root, "_sync_log.md"), "entries": [log]})
    if not res.get("ok"):
        issues.append({"source": "update_index", "file": "_sync_log.md", "field": "sync-log", "severity": "warning",
                       "expected": "строка дописана", "actual": res.get("error")})
    if not opts.get("keep_draft"):
        for p in src.values():
            os.remove(p)
        out["draft_removed"] = sorted(os.path.relpath(p, root) for p in src.values())
    out["ok"] = True
    return out


def _parse(argv: list[str]) -> dict:
    if not argv:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("stdin должен быть JSON-объектом")
        opts = {k.replace("-", "_"): v for k, v in payload.items()}
        if "as" in opts:
            opts["as_name"] = opts.pop("as")
    else:
        ap = argparse.ArgumentParser(description="Приёмка черновика _drafts/ в библиотеку")
        ap.add_argument("--root", required=True)
        ap.add_argument("--draft", required=True)
        ap.add_argument("--kind", required=True, choices=KINDS)
        ap.add_argument("--replaces")
        ap.add_argument("--as", dest="as_name")
        ap.add_argument("--force", action="store_true")
        ap.add_argument("--dry-run", action="store_true")
        ap.add_argument("--keep-draft", action="store_true")
        ap.add_argument("--domain")
        ap.add_argument("--actual", type=float)
        ap.add_argument("--actual-source")
        ap.add_argument("--interim-note")
        ap.add_argument("--no-interim", action="store_true")
        ap.add_argument("--outcome-resolve")
        ap.add_argument("--no-outcome-log", action="store_true")
        ap.add_argument("--today")
        opts = vars(ap.parse_args(argv))
    for req in ("root", "draft", "kind"):
        if not opts.get(req):
            raise ValueError(f"нужен {req}")
    if opts["kind"] not in KINDS:
        raise ValueError(f"kind — один из {KINDS}")
    opts["draft"] = os.path.basename(str(opts["draft"]))
    for ext in (".events.yaml", ".yaml", ".md"):
        if opts["draft"].endswith(ext):
            opts["draft"] = opts["draft"][: -len(ext)]
    opts["today"] = str(opts.get("today") or date.today().isoformat())
    return opts


def main() -> None:
    try:
        opts = _parse(sys.argv[1:])
    except (ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)
    try:
        out = promote(opts)
    except Refusal as exc:
        out = {"ok": False, "kind": opts["kind"], "draft": opts["draft"], "written": [], "replaced": None,
               "index_rows": [], "index_pending": [], "sync_log_line": None, "draft_removed": False,
               "issues": [{"source": "promote-draft", "severity": "blocking", "field": "draft", "expected": "",
                           "actual": str(exc)}], "notes": [], "dry_run": bool(opts.get("dry_run"))}
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    sys.exit(0 if out["ok"] else 1)


if __name__ == "__main__":
    main()
