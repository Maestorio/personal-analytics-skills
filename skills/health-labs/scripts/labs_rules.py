#!/usr/bin/env python3
"""
Общие правила labs.json (раздел «Здоровье»): ОДНА реализация для скилла health-labs (intake.py) и для сервера
сайта (tools/hosting/api/server.py, ручная точка при выключенном ИИ).

Здесь: статус точки (auto_status — только арифметика по референсу, не медицинский вывод), форма референса
(valid_ref), пересчёт производных полей маркера (recompute_marker), проверка плана внесения (plan_check) и
проверка ручной правки labs.json со страницы (check_manual_edit).

Точки с source == "manual" принадлежат владельцу: скилл их не меняет, сайт правит только их.

Только stdlib; при импорте ничего не читает и не пишет.
"""
from __future__ import annotations

import copy
import hashlib
import re
import unicodedata
from pathlib import Path

MANUAL = "manual"          # значение source у точки, введённой владельцем на странице

STUDY_KINDS = ["МРТ", "КТ", "УЗИ", "ЭКГ", "Рентген", "ЭНМГ", "Эндоскопия", "Другое"]  # = STUDY_KINDS в tools/health.html
STUDY_TEXT_FIELDS = ("area", "conclusion", "clinic", "doctor", "notes")
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
STUDY_ID_RE = re.compile(r"^s[0-9a-z][0-9a-z-]*$")

def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def nfc(s: str) -> str:
    """macOS отдаёт имена файлов в NFD («й» = «и» + знак): без приведения к NFC
    имя из лога/плана не совпадает с именем на диске — scan показывал бы
    разобранные файлы снова, а регексы подсказок промахивались."""
    return unicodedata.normalize("NFC", s)

def auto_status(value, ref):
    """Статус числовой точки по её референсу; нет числа/референса → na."""
    if not isinstance(value, (int, float)) or not ref:
        return "na"
    if "low" in ref and "high" in ref:
        return "low" if value < ref["low"] else ("high" if value > ref["high"] else "norm")
    op, v = ref.get("op"), ref.get("value")
    if op in ("<", "≤"):
        return "high" if (value >= v if op == "<" else value > v) else "norm"
    if op in (">", "≥"):
        return "low" if (value <= v if op == ">" else value < v) else "norm"
    return "na"


def valid_ref(ref) -> bool:
    if ref is None:
        return True
    if not isinstance(ref, dict):
        return False
    if set(ref) == {"low", "high"}:
        return all(isinstance(ref[k], (int, float)) for k in ref) and ref["low"] <= ref["high"]
    if set(ref) == {"op", "value"}:
        return ref["op"] in ("<", "≤", ">", "≥") and isinstance(ref["value"], (int, float))
    if set(ref) == {"text"}:
        return isinstance(ref["text"], str) and bool(ref["text"].strip())
    return False


def slug(s: str) -> str:
    tr = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
          "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
          "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
          "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
          "я": "ya"}
    out = "".join(tr.get(c, c if c.isalnum() and c.isascii() else "-") for c in s.lower())
    return re.sub(r"-+", "-", out).strip("-")[:24]


# ─────────────────────────── план: проверка и применение ───────────────────────────
def plan_check(plan, labs, studies, log, src_dir: Path, studies_dir: Path, allow_repeat=False):
    """Проверяет план целиком. -> (errors, warnings, ops). Ничего не пишет.

    ops — нормализованные операции для apply_ops (с разрешёнными id)."""
    errors, warnings = [], []
    E = errors.append
    W = warnings.append

    by_id = {m["id"]: m for m in labs.get("biomarkers", [])}
    by_name = {m["name"]: m for m in labs.get("biomarkers", [])}
    cats = {c["key"] for c in labs.get("categories", [])}
    study_ids = {s["id"] for s in studies.get("studies", [])}
    logged = log.get("files", {})

    new_cats = []
    for c in plan.get("new_categories", []):
        k, n = c.get("key"), c.get("name")
        if not (isinstance(k, str) and ID_RE.match(k) and isinstance(n, str) and n.strip()):
            E(f"new_categories: нужна пара key (латиница) + name: {c!r}")
        elif k in cats:
            E(f"new_categories: категория {k!r} уже есть")
        else:
            cats.add(k)
            new_cats.append({"key": k, "name": n.strip()})

    new_markers = []
    for m in plan.get("new_markers", []):
        mid, name, cat = m.get("id"), (m.get("name") or "").strip(), m.get("category")
        if not (isinstance(mid, str) and ID_RE.match(mid)):
            E(f"new_markers: id латиницей [a-z0-9_]: {m!r}")
            continue
        if mid in by_id:
            E(f"new_markers: id {mid!r} уже занят маркером «{by_id[mid]['name']}»")
            continue
        if not name:
            E(f"new_markers[{mid}]: пустое name")
            continue
        if name in by_name:
            E(f"new_markers[{mid}]: маркер с именем «{name}» уже есть (id {by_name[name]['id']}) — "
              f"используйте его, а не заводите дубль")
            continue
        if cat not in cats:
            E(f"new_markers[{mid}]: неизвестная категория {cat!r} (заведите в new_categories)")
            continue
        nm = {"id": mid, "name": name, "category": cat, "kind": "num",
              "unit": (m.get("unit") or "").strip(), "ref": None, "series": []}
        by_id[mid] = nm
        by_name[name] = nm
        new_markers.append(nm)

    ops = {"new_categories": new_cats, "new_markers": new_markers, "items": []}
    seen_src = set()
    seen_points = set()
    for n, it in enumerate(plan.get("items", [])):
        where = f"items[{n}]"
        src = it.get("src")
        if isinstance(src, str):
            src = [src]
        if isinstance(src, list):
            src = [nfc(s) if isinstance(s, str) else s for s in src]
        if not src or not all(isinstance(s, str) and s for s in src):
            E(f"{where}: src — непустой список имён файлов первоисточника")
            continue
        for s in src:
            if not (src_dir / s).is_file():
                E(f"{where}: файла нет в первоисточнике: {s}")
            if s in logged and not allow_repeat:
                E(f"{where}: {s} уже разобран ({logged[s].get('status')}, {logged[s].get('date')}) — "
                  f"повторно только с --allow-repeat")
            if s in seen_src:
                E(f"{where}: {s} встречается в плане дважды")
            seen_src.add(s)
        op = {"src": src, "study": None, "study_ref": None, "add_files": [], "copies": [], "points": []}

        st = it.get("study")
        sid = None
        if st is not None:
            if "ref" in st:
                sid = st["ref"]
                if sid not in study_ids:
                    E(f"{where}: study.ref {sid!r} — такого исследования нет")
                op["study_ref"] = sid
                # add_files — дописать файлы к существующему исследованию
                # (второе прочтение снимка, внесённое раньше без него).
                cur = next((x for x in studies.get("studies", []) if x["id"] == sid), {})
                have = {cur.get("file")} | set(cur.get("more_files") or [])
                op["add_files"] = []
                for f in st.get("add_files") or []:
                    a, fr = (f or {}).get("as"), (f or {}).get("from")
                    a = nfc(a) if isinstance(a, str) else a
                    fr = nfc(fr) if isinstance(fr, str) else fr
                    if not (isinstance(a, str) and a and "/" not in a and isinstance(fr, str) and fr in src):
                        E(f"{where}: study.add_files: нужны as и from (from — из src): {f!r}")
                        continue
                    tgt = studies_dir / a
                    if tgt.exists() and (src_dir / fr).is_file() and sha256_file(tgt) != sha256_file(src_dir / fr):
                        E(f"{where}: в Health/studies/ уже есть ДРУГОЙ файл {a} — не перезаписываю")
                    op["copies"].append((fr, a))
                    if a not in have:
                        op["add_files"].append(a)
            else:
                d, kind = st.get("date"), st.get("kind")
                if not (isinstance(d, str) and ISO_RE.match(d)):
                    E(f"{where}: study.date — YYYY-MM-DD")
                    d = "0000-00-00"
                if kind not in STUDY_KINDS:
                    E(f"{where}: study.kind {kind!r} — одно из {STUDY_KINDS}")
                if not (st.get("conclusion") or "").strip():
                    E(f"{where}: study.conclusion пусто — заключение обязательно")
                for f in STUDY_TEXT_FIELDS:
                    if f in st and st[f] is not None and not isinstance(st[f], str):
                        E(f"{where}: study.{f} — строка")
                sid = st.get("id") or "s" + d.replace("-", "") + "-" + slug((kind or "") + "-" + (st.get("area") or ""))
                if not STUDY_ID_RE.match(sid):
                    E(f"{where}: study.id {sid!r} — формат s<дата>-<слаг>")
                if sid in study_ids:
                    E(f"{where}: исследование {sid!r} уже есть — для привязки к нему используйте study.ref")
                study_ids.add(sid)
                rec = {"id": sid, "date": d, "kind": kind}
                for f in STUDY_TEXT_FIELDS:
                    rec[f] = (st.get(f) or "").strip()
                # Файлы: target-имя в Health/studies/ ← источник из первоисточника.
                files = st.get("files") or []
                if not isinstance(files, list):
                    E(f"{where}: study.files — список {{\"as\": имя-в-studies, \"from\": имя-в-первоисточнике}}")
                    files = []
                targets = []
                for f in files:
                    a, fr = (f or {}).get("as"), (f or {}).get("from")
                    a = nfc(a) if isinstance(a, str) else a
                    fr = nfc(fr) if isinstance(fr, str) else fr
                    if not (isinstance(a, str) and a and "/" not in a and isinstance(fr, str)):
                        E(f"{where}: study.files: нужны as и from: {f!r}")
                        continue
                    if fr not in src:
                        E(f"{where}: study.files: {fr} не перечислен в src этого пункта")
                    tgt = studies_dir / a
                    if tgt.exists() and (src_dir / fr).is_file() and sha256_file(tgt) != sha256_file(src_dir / fr):
                        E(f"{where}: в Health/studies/ уже есть ДРУГОЙ файл {a} — не перезаписываю")
                    op["copies"].append((fr, a))
                    targets.append(a)
                rec["file"] = targets[0] if targets else ""
                if len(targets) > 1:
                    rec["more_files"] = targets[1:]
                rec["src"] = list(src)
                if not targets:
                    W(f"{where}: у исследования {sid} нет файла (study.files пуст)")
                op["study"] = rec

        for k, p in enumerate(it.get("points", [])):
            pw = f"{where}.points[{k}]"
            key = p.get("marker")
            m = by_id.get(key) or by_name.get(key)
            if not m:
                E(f"{pw}: маркер {key!r} не найден ни по id, ни по имени (новый — в new_markers)")
                continue
            d = p.get("date")
            if not (isinstance(d, str) and ISO_RE.match(d)):
                E(f"{pw}: date — YYYY-MM-DD")
                continue
            if (m["id"], d) in seen_points:
                E(f"{pw}: {m['id']} на {d} дважды в плане")
            seen_points.add((m["id"], d))
            existing = [s for s in m["series"] if s["date"] == d]
            link_only = bool(p.get("link_only"))
            if any(is_manual(s) for s in existing):
                E(f"{pw}: КОНФЛИКТ — у {m['id']} на {d} уже есть ручная точка владельца (source: manual): "
                  f"скилл её не меняет, не дублирует и не привязывает; решение за человеком "
                  f"(убрать точку на сайте или исключить её из плана)")
                continue
            if link_only:
                if not existing:
                    E(f"{pw}: link_only, но у {m['id']} нет точки на {d}")
                    continue
                if existing[0].get("study") and existing[0]["study"] != sid:
                    E(f"{pw}: точка {m['id']} {d} уже привязана к {existing[0]['study']}")
                if sid is None:
                    E(f"{pw}: link_only без исследования в этом пункте — привязывать не к чему")
                op["points"].append({"mode": "link", "marker": m["id"], "date": d})
                continue
            if existing:
                E(f"{pw}: у {m['id']} уже есть точка на {d} (значение {existing[0].get('value')!r}) — "
                  f"дубль; если это то же измерение — link_only: true")
                continue
            value, text = p.get("value"), p.get("text")
            if value is not None and not isinstance(value, (int, float)) or isinstance(value, bool):
                E(f"{pw}: value — число (текстовый результат — в text)")
                continue
            if value is None and not (isinstance(text, str) and text.strip()):
                E(f"{pw}: нужно value (число) или text")
                continue
            ref = p.get("ref")
            if not valid_ref(ref):
                E(f"{pw}: ref — {{low,high}} | {{op,value}} | {{text}} | null: {ref!r}")
                continue
            unit = (p.get("unit") if p.get("unit") is not None else m.get("unit")) or ""
            if m.get("unit") and unit != m["unit"]:
                W(f"{pw}: единица «{unit}» ≠ единице маркера «{m['unit']}» ({m['name']}) — проверьте пересчёт")
            status = p.get("status") or auto_status(value, ref)
            if status not in ("norm", "high", "low", "na"):
                E(f"{pw}: status — norm|high|low|na")
                continue
            lab = p.get("lab") or it.get("lab")
            lab = lab.strip() if isinstance(lab, str) else None
            if not sid and not lab:
                E(f"{pw}: у анализа не указана лаборатория (lab пункта или точки) — "
                  f"не нашёл в документе → спросить владельца, не угадывать")
                continue
            if sid and op["study"] and d != op["study"]["date"]:
                W(f"{pw}: дата точки {d} ≠ дате исследования {op['study']['date']}")
            op["points"].append({"mode": "add", "marker": m["id"], "point": {
                "date": d, "value": value, "text": None if value is not None else text.strip(),
                "unit": unit, "ref": ref, "status": status, "lab": lab or None,
                **({"study": sid} if sid else {}), "src": src[0]}})
        op["sid"] = sid
        ops["items"].append(op)
    return errors, warnings, ops


def recompute_marker(m):
    m["series"].sort(key=lambda s: s["date"])
    last = m["series"][-1]
    m["ref"] = last.get("ref")
    units = [s["unit"] for s in m["series"] if s.get("unit")]
    m["unit"] = units[-1] if units else m.get("unit", "")
    # num — если все точки числовые. Прежнее правило конвертера («и у последней
    # есть интервал») делало авторефрактометрию «качественной»: диоптрии без
    # нормы теряли график (2026-09-29).
    m["kind"] = "num" if all(isinstance(s.get("value"), (int, float)) for s in m["series"]) else "qual"


# ─────────────────────────── ручные точки (source: manual) ───────────────────────────
MANUAL_NOTE_MAX = 200


def is_manual(point) -> bool:
    return isinstance(point, dict) and point.get("source") == MANUAL


def manual_points(labs) -> dict:
    """{(id маркера, дата): точка} по всем ручным точкам — для сверки «скилл их не трогает»."""
    out = {}
    for m in (labs or {}).get("biomarkers", []):
        for s in m.get("series", []):
            if is_manual(s):
                out[(m["id"], s["date"])] = copy.deepcopy(s)
    return out


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def check_manual_edit(old, new):
    """Проверяет, что `new` отличается от `old` (labs.json) ТОЛЬКО тем, что разрешено странице:
    добавить/править/удалить точки source=manual и завести новый показатель. -> (errors, normalized).

    normalized — `new` с серверным пересчётом производных полей маркера (recompute_marker) и статусом точек
    (auto_status). Страница статус и производные поля не определяет: что она прислала, перезаписывается."""
    errors = []
    E = errors.append
    if not isinstance(new, dict) or not isinstance(old, dict):
        return ["labs.json: корень — объект"], None
    new = copy.deepcopy(new)
    for k in set(old) | set(new):
        if k in ("biomarkers", "updated"):
            continue
        if old.get(k) != new.get(k):
            E(f"поле верхнего уровня «{k}» ведёт скилл — страница его не меняет")
    if old.get("categories") != new.get("categories"):
        E("категории ведёт скилл — страница их не меняет")
    obm, nbm = old.get("biomarkers"), new.get("biomarkers")
    if not isinstance(nbm, list) or not isinstance(obm, list):
        return errors + ["biomarkers — список"], None
    cats = {c["key"] for c in old.get("categories", [])}
    old_by = {m["id"]: m for m in obm}
    seen = set()
    changed = set()
    names = {m["name"]: m["id"] for m in obm}
    for m in nbm:
        if not isinstance(m, dict) or not isinstance(m.get("id"), str):
            E("маркер без id")
            continue
        mid = m["id"]
        if mid in seen:
            E(f"маркер {mid}: дважды")
            continue
        seen.add(mid)
        series = m.get("series")
        if not isinstance(series, list):
            E(f"маркер {mid}: series — список")
            continue
        o = old_by.get(mid)
        if o is None:
            # новый показатель
            if not ID_RE.match(mid):
                E(f"новый маркер: id латиницей [a-z0-9_]: {mid!r}")
            name = (m.get("name") or "").strip() if isinstance(m.get("name"), str) else ""
            if not name:
                E(f"новый маркер {mid}: пустое имя")
            elif name in names:
                E(f"новый маркер {mid}: имя «{name}» уже занято (id {names[name]})")
            else:
                names[name] = mid
            if m.get("category") not in cats:
                E(f"новый маркер {mid}: категория {m.get('category')!r} не из существующих")
            m["name"] = name
            if not isinstance(m.get("unit", ""), str):
                E(f"новый маркер {mid}: unit — строка")
            if not all(is_manual(s) for s in series):
                E(f"новый маркер {mid}: все точки обязаны быть source=manual")
            oseries = []
            changed.add(mid)
        else:
            for k in ("id", "name", "category"):
                if o.get(k) != m.get(k):
                    E(f"маркер {mid}: поле «{k}» ведёт скилл — страница его не меняет")
            oseries = o.get("series", [])
            known = {"id", "name", "category", "kind", "unit", "ref", "series"}
            if {k: v for k, v in o.items() if k not in known} != {k: v for k, v in m.items() if k not in known}:
                E(f"маркер {mid}: служебные поля ведёт скилл — страница их не меняет")
            if oseries != series:
                changed.add(mid)
            elif any(o.get(k) != m.get(k) for k in ("kind", "unit", "ref")):
                E(f"маркер {mid}: производные поля (kind/unit/ref) считает сервер — страница их не меняет")
        # точки скилла (не manual) — побайтно как были, в том же наборе
        o_skill = [s for s in oseries if not is_manual(s)]
        n_skill = [s for s in series if not is_manual(s)]
        key = lambda s: (s.get("date", ""), repr(sorted(s.items(), key=lambda kv: kv[0])))
        if sorted(o_skill, key=key) != sorted(n_skill, key=key):
            E(f"маркер {mid}: точки скилла (без source=manual) нельзя менять, добавлять или удалять со страницы")
        # ручные точки: форма
        dates = {}
        for s in series:
            if not isinstance(s, dict):
                E(f"маркер {mid}: точка — объект")
                continue
            d = s.get("date")
            if not (isinstance(d, str) and ISO_RE.match(d)):
                E(f"маркер {mid}: date — YYYY-MM-DD: {d!r}")
                continue
            dates[d] = dates.get(d, 0) + 1
            if not is_manual(s):
                continue
            where = f"маркер {mid} {d}"
            v, t = s.get("value"), s.get("text")
            if v is not None and not _num(v):
                E(f"{where}: value — число или null")
            if v is None and not (isinstance(t, str) and t.strip()):
                E(f"{where}: нужно число или текст")
            if v is not None and t not in (None, ""):
                E(f"{where}: либо число, либо текст")
            if not valid_ref(s.get("ref")):
                E(f"{where}: ref — {{low,high}} | {{op,value}} | {{text}} | null")
            unit = s.get("unit")
            if not isinstance(unit, str):
                E(f"{where}: unit — строка")
            elif o is not None and o.get("unit") and unit != o["unit"]:
                E(f"{where}: единица «{unit}» ≠ единице показателя «{o['unit']}» — у существующего показателя она не меняется")
            for f in ("lab", "note"):
                x = s.get(f)
                if x is not None and not (isinstance(x, str) and len(x) <= MANUAL_NOTE_MAX):
                    E(f"{where}: {f} — строка до {MANUAL_NOTE_MAX} символов или null")
            if s.get("study"):
                E(f"{where}: ручная точка не привязывается к исследованию со страницы")
            extra = set(s) - {"date", "value", "text", "unit", "ref", "status", "lab", "note", "source"}
            if extra:
                E(f"{where}: лишние поля {sorted(extra)}")
            # статус — только арифметика по референсу, считает сервер
            s["status"] = auto_status(v if _num(v) else None, s.get("ref"))
            s["text"] = None if v is not None else (t or "").strip()
            s["lab"] = (s.get("lab") or None)
            if s.get("note") in ("", None):
                s.pop("note", None)
        for d, n in dates.items():
            if n > 1:
                E(f"маркер {mid}: на {d} больше одной точки")
        # ручная правка не должна «съесть» точку скилла: дата ручной точки не занята точкой скилла
        skill_dates = {s.get("date") for s in n_skill}
        for s in series:
            if is_manual(s) and s.get("date") in skill_dates:
                E(f"маркер {mid} {s.get('date')}: на эту дату уже есть точка из документа — ручную рядом не ставлю")
    # удаление маркера: допустимо, только если в нём не было точек скилла (т.е. остались одни ручные и их убрали)
    for mid, o in old_by.items():
        if mid not in seen and any(not is_manual(s) for s in o.get("series", [])):
            E(f"маркер {mid}: есть точки из документов — страница не удаляет показатель")
    if errors:
        return errors, None
    kept = []
    for m in nbm:
        if m["series"]:
            if m["id"] in changed:
                recompute_marker(m)
            kept.append(m)
    new["biomarkers"] = kept if all(m["id"] in old_by for m in kept) else sorted(
        kept, key=lambda b: (b["category"], b["name"]))
    return [], new
