#!/usr/bin/env python3
"""
Импорт давления и пульса из экспорта Apple Health в labs.json (health-labs).

Вход: export.zip или export.xml («Здоровье» на iPhone → профиль → «Экспортировать
все медданные»). Выход: точки рядов exam_bp_sys, exam_bp_dia, exam_pulse в
labs.json (среднее за день). Поток как у intake.py: plan (ничего не пишет) →
показать → apply (резервная копия labs.json в .intake-backups/, атомарная запись).

  python3 scripts/apple_health_bp.py --root HEALTH_ROOT plan  EXPORT [--since YYYY-MM-DD]
  python3 scripts/apple_health_bp.py --root HEALTH_ROOT apply EXPORT [--since YYYY-MM-DD]

Правила:
  · давление — Correlation HKCorrelationTypeIdentifierBloodPressure (Systolic/Diastolic внутри);
  · пульс — HeartRate с тем же sourceName и startDate в пределах ±2 минут от замера
    давления; пульс часов и прочий HR не берётся;
  · точка = среднее за день (1 знак после запятой; целое пишется целым);
  · день, уже внесённый в ряд с источником Apple Health, и день с ручным замером
    в vitals.json → bp[] пропускаются. vitals.json скрипт только читает.
Парсинг потоковый (iterparse), zip читается потоком без распаковки на диск.
Только stdlib.
"""
from __future__ import annotations

import argparse
import bisect
import datetime as _dt
import json
import re
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import intake  # noqa: E402  (write_atomic, dump_labs, recompute_marker, auto_status)

HEALTH = intake.HEALTH
LAB_BASE = "Самоизмерение (Apple Health)"
WINDOW_SEC = 120
T_CORR = "HKCorrelationTypeIdentifierBloodPressure"
T_SYS = "HKQuantityTypeIdentifierBloodPressureSystolic"
T_DIA = "HKQuantityTypeIdentifierBloodPressureDiastolic"
T_HR = "HKQuantityTypeIdentifierHeartRate"
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SERIES = {  # id → (name, unit)
    "exam_bp_sys": ("АД систолическое", "мм рт. ст."),
    "exam_bp_dia": ("АД диастолическое", "мм рт. ст."),
    "exam_pulse": ("Пульс", "уд/мин"),
}


# ─────────────────────────── разбор экспорта ───────────────────────────
class _Stream:
    """Контекстный менеджер: открывает export.xml из zip (потоком) или с диска."""

    def __init__(self, path: Path):
        self.path, self.zf, self.fh = path, None, None

    def __enter__(self):
        if self.path.suffix.lower() == ".zip":
            self.zf = zipfile.ZipFile(self.path)
            names = [n for n in self.zf.namelist()
                     if n.rsplit("/", 1)[-1].lower() == "export.xml"]
            if not names:
                raise SystemExit("В архиве нет export.xml (ожидался export.zip из Здоровья).")
            self.fh = self.zf.open(names[0])
        else:
            self.fh = open(self.path, "rb")
        return self.fh

    def __exit__(self, *a):
        if self.fh:
            self.fh.close()
        if self.zf:
            self.zf.close()


def _ts(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z")


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def parse_bp(path: Path):
    """Проход 1: замеры давления. → список {source, t, day, sys, dia}."""
    out = []
    with _Stream(path) as fh:
        in_corr = False
        root = None
        for ev, el in ET.iterparse(fh, events=("start", "end")):
            if ev == "start":
                if root is None:
                    root = el
                if el.tag == "Correlation":
                    in_corr = True
                continue
            if el.tag == "Correlation":
                in_corr = False
                if el.get("type") == T_CORR:
                    sys_v = dia_v = None
                    for r in el.findall("Record"):
                        if r.get("type") == T_SYS:
                            sys_v = _num(r.get("value"))
                        elif r.get("type") == T_DIA:
                            dia_v = _num(r.get("value"))
                    st = el.get("startDate")
                    if sys_v is not None and dia_v is not None and st:
                        try:
                            t = _ts(st)
                        except ValueError:
                            t = None
                        if t:
                            out.append({"source": el.get("sourceName") or "", "t": t,
                                        "day": st[:10], "sys": sys_v, "dia": dia_v})
                el.clear()
            elif el.tag == "Record" and not in_corr:
                el.clear()  # вложенные записи читаются через Correlation; одиночные не нужны здесь
            if not in_corr and root is not None and el is not root:
                root.clear()  # очищенные элементы иначе копятся детьми корня: экспорт — миллионы записей
    return out


def parse_hr(path: Path, bp):
    """Проход 2: пульс только в окне ±2 мин от замера давления с тем же источником.
    Память: хранятся только подошедшие значения, не весь HR."""
    by_src = defaultdict(list)
    for m in bp:
        by_src[m["source"]].append(m["t"].timestamp())
    for v in by_src.values():
        v.sort()
    cands = defaultdict(list)  # (source, t_bp) → [(|dt|, hr)]
    with _Stream(path) as fh:
        root = None
        for ev, el in ET.iterparse(fh, events=("start", "end")):
            if ev == "start":
                if root is None:
                    root = el
                continue
            if el.tag == "Record":
                if el.get("type") == T_HR and el.get("sourceName") in by_src:
                    val, st = _num(el.get("value")), el.get("startDate")
                    if val is not None and st:
                        try:
                            ts = _ts(st).timestamp()
                        except ValueError:
                            ts = None
                        if ts is not None:
                            arr = by_src[el.get("sourceName")]
                            i = bisect.bisect_left(arr, ts - WINDOW_SEC)
                            while i < len(arr) and arr[i] <= ts + WINDOW_SEC:
                                cands[(el.get("sourceName"), arr[i])].append((abs(arr[i] - ts), val))
                                i += 1
                el.clear()
            elif el.tag == "Correlation":
                el.clear()
            if el.tag in ("Record", "Correlation") and root is not None:
                root.clear()  # см. parse_bp
    for m in bp:
        c = cands.get((m["source"], m["t"].timestamp()))
        m["pulse"] = min(c)[1] if c else None
    return bp


def aggregate(bp):
    """По дням: средние и число замеров. → {day: {n, sys, dia, pulse|None, n_pulse}}."""
    days = defaultdict(list)
    for m in bp:
        days[m["day"]].append(m)
    out = {}
    for d, ms in days.items():
        pulses = [m["pulse"] for m in ms if m["pulse"] is not None]
        out[d] = {
            "n": len(ms),
            "sys": _avg([m["sys"] for m in ms]),
            "dia": _avg([m["dia"] for m in ms]),
            "pulse": _avg(pulses) if pulses else None,
        }
    return out


def _avg(xs):
    v = round(sum(xs) / len(xs), 1)
    return int(v) if v == int(v) else v


def lab_label(n: int) -> str:
    return LAB_BASE if n == 1 else f"{LAB_BASE}, среднее из {n} замеров за день"


# ─────────────────────────── план ───────────────────────────
def manual_dates(health: Path) -> set:
    p = health / "vitals.json"
    if not p.exists():
        return set()
    try:
        bp = json.loads(p.read_text(encoding="utf-8")).get("bp") or []
    except (ValueError, OSError):
        return set()
    return {b["date"] for b in bp if isinstance(b, dict) and b.get("date")}


def apple_dates(labs, mid: str) -> set:
    for m in labs.get("biomarkers", []):
        if m.get("id") == mid:
            return {s["date"] for s in m.get("series", [])
                    if str(s.get("lab") or "").startswith(LAB_BASE)}
    return set()


def build_plan(days: dict, labs, manual: set, since: str | None):
    plan = {"add": [], "skip_apple": [], "skip_manual": [], "skip_since": 0, "points": defaultdict(list)}
    have = {mid: apple_dates(labs, mid) for mid in SERIES}
    for d in sorted(days):
        if since and d < since:
            plan["skip_since"] += 1
            continue
        if d in manual:
            plan["skip_manual"].append(d)
            continue
        info = days[d]
        vals = {"exam_bp_sys": info["sys"], "exam_bp_dia": info["dia"], "exam_pulse": info["pulse"]}
        new = [mid for mid, v in vals.items() if v is not None and d not in have[mid]]
        if not new:
            plan["skip_apple"].append(d)
            continue
        plan["add"].append(d)
        for mid in new:
            plan["points"][mid].append((d, vals[mid], lab_label(info["n"])))
    return plan


def print_plan(plan, days, since):
    print(f"Экспорт Apple Health: дней с давлением {len(days)}"
          + (f" (с {since})" if since else ""))
    if days:
        print(f"  диапазон: {min(days)} … {max(days)}")
    print(f"  новых дней: {len(plan['add'])}"
          + (f" ({plan['add'][0]} … {plan['add'][-1]})" if plan["add"] else ""))
    print(f"  пропущено: уже внесено {len(plan['skip_apple'])}"
          f" · есть ручной замер {len(plan['skip_manual'])}"
          + (f" · раньше --since {plan['skip_since']}" if since else ""))
    for mid in SERIES:
        print(f"  точек {mid}: +{len(plan['points'].get(mid, []))}")
    for d in plan["add"][:5]:
        i = days[d]
        print(f"    пример {d}: {i['sys']}/{i['dia']}"
              + (f", пульс {i['pulse']}" if i["pulse"] is not None else ", пульса нет")
              + f" — {lab_label(i['n'])}")
    if plan["skip_manual"]:
        print("  есть ручной замер (пропущены): " + ", ".join(plan["skip_manual"][:5])
              + (" …" if len(plan["skip_manual"]) > 5 else ""))


def apply_plan(health: Path, plan, today: str):
    labs = intake.read_json(health / "labs.json")  # перечитали прямо перед записью
    by_id = {m["id"]: m for m in labs.get("biomarkers", [])}
    if "exam" not in {c.get("key") for c in labs.get("categories", [])}:
        raise SystemExit("В labs.json нет категории «exam» — ряды давления/пульса некуда класть.")
    added = 0
    for mid, pts in plan["points"].items():
        name, unit = SERIES[mid]
        m = by_id.get(mid)
        if m is None:
            m = {"id": mid, "name": name, "category": "exam", "kind": "num", "unit": unit,
                 "ref": None, "series": []}
            labs["biomarkers"].append(m)
            by_id[mid] = m
        if mid == "exam_pulse":
            m["name"] = "Пульс"
        have = {s["date"] for s in m["series"] if str(s.get("lab") or "").startswith(LAB_BASE)}
        ref = m.get("ref")
        for d, v, lab in pts:
            if d in have:
                continue
            m["series"].append({"date": d, "value": v, "text": None, "unit": unit, "ref": ref,
                                "status": intake.auto_status(v, ref), "lab": lab})
            added += 1
        intake.recompute_marker(m)
    if "exam_pulse" in by_id:
        by_id["exam_pulse"]["name"] = "Пульс"
    stamp = today + "-" + _dt.datetime.now().strftime("%H%M%S")
    d = health / ".intake-backups"
    d.mkdir(exist_ok=True)
    import shutil
    shutil.copy2(health / "labs.json", d / f"{stamp}-labs.json")
    labs["updated"] = today
    intake.write_atomic(health / "labs.json", intake.dump_labs(labs))
    return added, f"{stamp}-labs.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="Импорт давления и пульса из экспорта Apple Health")
    ap.add_argument("--root", type=Path, default=HEALTH, help="папка Claude-Memory/Health")
    ap.add_argument("--today")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "apply"):
        p = sub.add_parser(name)
        p.add_argument("export", type=Path)
        p.add_argument("--since", help="YYYY-MM-DD: брать дни не раньше")
        if name == "plan":
            p.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.since and not ISO_RE.match(a.since):
        print("✗ --since: нужен формат YYYY-MM-DD")
        return 2
    if not a.export.exists():
        print(f"✗ нет файла: {a.export}")
        return 2
    if not (a.root / "labs.json").exists():
        print(f"✗ нет labs.json в {a.root}")
        return 2
    bp = parse_hr(a.export, parse_bp(a.export))
    days = aggregate(bp)
    labs = intake.read_json(a.root / "labs.json")
    plan = build_plan(days, labs, manual_dates(a.root), a.since)
    print_plan(plan, days, a.since)
    do_apply = a.cmd == "apply" or getattr(a, "apply", False)
    if not do_apply:
        print("\nDRY-RUN: ничего не записано. Для записи — команда apply.")
        return 0
    if not plan["add"]:
        print("\nЗаписывать нечего.")
        return 0
    today = a.today or _dt.date.today().isoformat()
    n, bk = apply_plan(a.root, plan, today)
    print(f"\n✓ записано точек: {n}; labs.json — через зеркало Synology; бэкап: .intake-backups/{bk}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
