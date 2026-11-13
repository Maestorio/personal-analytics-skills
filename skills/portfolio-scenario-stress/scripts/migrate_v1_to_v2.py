#!/usr/bin/env python3
"""
migrate_v1_to_v2.py — V2-CUTOVER (Этап 1 плана phase-4-post-v2-cutover-plan.md).

Миграция schema-1 артефактов Portfolio → schema-2 стратегией **wrap-as-single-horizon**
(D7-CUT-1): единственный горизонт v1 оборачивается как `h<N>` без пересчёта чисел —
recompute сознательно НЕ делается (FCA-прогнозы на web_search невоспроизводимы задним
числом), поэтому история сохраняется бит-в-бит.

Два вида (--kind autodetect по полю `type`):

  • weekly-review (stock/bond) — **текстовая хирургия** (комментарии/форматирование
    сохраняются, в файлах до 45 живых комментариев):
      - `schema_version: 1` → `2`;
      - top-level `horizon_months: N` (+ `horizon:`/`horizon_end:` дата) →
        `horizons: [N]` / `primary_horizon: N` / `horizon_ends: {hN: дата}`;
      - строки `in_horizon:` в catalyst-блоках удаляются (v2-консьюмер вычисляет
        принадлежность из date_window, §11.3; v2-валидатор блокирует поле как drift).
  • stress — **YAML round-trip** (структурный wrap; комментариев в файлах нет,
    лидирующие #-строки шапки сохраняются):
      - `horizon: <дата>` → horizons/horizon_ends/primary (N = месяцы от `date`);
      - `scenarios.{X}.factors` → `factors_by_horizon.hN`; `portfolio_level` →
        `portfolio_level_by_horizon.hN`;
      - `per_position.{T}.{delta_pct_by_scenario, expected_pct_pweighted,
        tail_var_pct, tail_var_scenario_id}` → `by_horizon.hN.{...}`.

Вне scope (исключаются с понятным отказом MigrationRefused, не падением) —
фактический список по прогону 2026-08-03:
  - stress-2026-05-02-forecast-consensus (нет schema_version/type — прото-формат);
  - stress-2026-05-04-macro-input (мультидокументный YAML);
  - stress-2026-05-06-zheleznyi-zanaves и stress-2026-05-09-shell-d1 (нет поля
    горизонта — wrap невозможен без recompute).
NB: ранний weekly-review-2026-05-06.yaml («combined» из плана D7-CUT-2) на деле —
обычный stocks-review без даты горизонта и мигрируется штатно с выводом
horizon_end из review_date (derived-пометка в отчёте).

CLI:
    python3 migrate_v1_to_v2.py --input <v1.yaml> --output <v2.yaml> [--report r.json]
    In-place: --input X --output X (бэкап делает вызывающая сторона — Этап 0 плана).

Требует PyYAML только для stress-ветки и самопроверки weekly (parse-гейт).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

DAYS_PER_MONTH = 30.4375  # средний григорианский месяц

# Реальные значения type в живых артефактах (инвентарь 2026-08-03):
# weekly — 'weekly-stocks-review'/'weekly-bonds-review' (v1 и v2 одинаково);
# stress — 'portfolio-stress-test' (+ единичный 'portfolio-scenario-stress' 05-12).
WEEKLY_TYPES = {"weekly-stocks-review", "weekly-bonds-review"}
STRESS_TYPES = {"portfolio-stress-test", "portfolio-scenario-stress"}

# per_position-поля v1, переезжающие под by_horizon.hN (v2)
_PP_HORIZON_FIELDS = (
    "delta_pct_by_scenario", "expected_pct_pweighted",
    "tail_var_pct", "tail_var_scenario_id",
)


class MigrationRefused(Exception):
    """Файл сознательно вне scope миграции (combined / мультидокумент / не v1)."""


def _parse_iso(s: str) -> date | None:
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", str(s).strip().strip("'\""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def months_between(start: str, end: str) -> int | None:
    d0, d1 = _parse_iso(start), _parse_iso(end)
    if d0 is None or d1 is None or d1 <= d0:
        return None
    return max(1, round((d1 - d0).days / DAYS_PER_MONTH))


def add_months_iso(start: str, n: int) -> str | None:
    """start + n календарных месяцев (день клампится к длине месяца)."""
    d0 = _parse_iso(start)
    if d0 is None:
        return None
    total = d0.year * 12 + (d0.month - 1) + n
    y, m = divmod(total, 12)
    m += 1
    for day in (d0.day, 30, 29, 28):
        try:
            return date(y, m, day).isoformat()
        except ValueError:
            continue
    return None


# ── weekly: текстовая хирургия ────────────────────────────────────────────────

_TOP_KEY = lambda key: re.compile(rf"^{key}:\s*(.*?)\s*$")  # noqa: E731


def migrate_weekly_text(text: str) -> tuple[str, dict]:
    """Мигрирует weekly-review YAML как текст. Возвращает (new_text, report)."""
    lines = text.split("\n")

    def find_top(key: str) -> tuple[int, str] | None:
        rx = _TOP_KEY(key)
        for i, ln in enumerate(lines):
            m = rx.match(ln)
            if m:
                return i, m.group(1)
        return None

    t = find_top("type")
    if t and t[1].strip().strip("'\"") not in WEEKLY_TYPES:
        raise MigrationRefused(f"type: {t[1]!r} — не weekly-review")
    sv = find_top("schema_version")
    if sv is None:
        raise MigrationRefused("нет top-level schema_version — вне scope")
    if sv[1].strip().strip("'\"") == "2":
        raise MigrationRefused("уже schema_version 2 — миграция не нужна")

    rd = find_top("review_date")
    review_date = rd[1].strip().strip("'\"") if rd else ""

    hm = find_top("horizon_months")
    he = find_top("horizon_end") or find_top("horizon")
    end_raw = he[1].strip().strip("'\"") if he else None
    if end_raw is not None and _parse_iso(end_raw) is None:
        raise MigrationRefused(f"horizon_end не ISO-дата: {end_raw!r}")

    derived: list[str] = []
    if hm is not None:
        n = int(hm[1].strip().strip("'\""))
    elif end_raw is not None:
        # ранний формат (bond-05-11): только дата горизонта → N из review_date
        n = months_between(review_date, end_raw) or 0
        if n <= 0:
            raise MigrationRefused(
                f"не вычислить месяцы из review_date={review_date!r} horizon={end_raw!r}"
            )
        derived.append("horizon_months")
    else:
        raise MigrationRefused("v1 weekly без horizon_months и без horizon-даты — не мигрируется механически")

    if end_raw is None:
        # ранний формат (05-06/05-07/05-09/05-11-stock): только N → дата из review_date + N
        end_raw = add_months_iso(review_date, n)
        if end_raw is None:
            raise MigrationRefused(f"не вывести horizon_end из review_date={review_date!r} + {n} мес")
        derived.append("horizon_end")

    # 1) schema_version → 2
    lines[sv[0]] = "schema_version: 2"
    # 2) v2-блок горизонтов на месте старого поля (horizon_months либо horizon-даты)
    anchor = hm[0] if hm is not None else he[0]
    v2_block = (
        f"horizons: [{n}]\n"
        f"primary_horizon: {n}\n"
        f"horizon_ends:\n"
        f"  h{n}: '{end_raw}'"
    )
    if derived:
        v2_block += f"  # {'+'.join(derived)} выведены миграцией V2-CUTOVER (wrap-as-h{n})"
    lines[anchor] = v2_block
    # 3) удалить top-level horizon:/horizon_end: (оба, если есть)
    drop_idx = set()
    for key in ("horizon_end", "horizon"):
        f = find_top(key)
        if f:
            drop_idx.add(f[0])
    # 4) удалить строки in_horizon: (catalyst-поле, v2-валидатор блокирует как drift)
    in_horizon_removed = 0
    out_lines = []
    for i, ln in enumerate(lines):
        if i in drop_idx:
            continue
        if re.match(r"^\s+in_horizon:\s", ln):
            in_horizon_removed += 1
            continue
        out_lines.append(ln)
    new_text = "\n".join(out_lines)

    if yaml is not None:  # parse-гейт: хирургия обязана дать валидный YAML
        doc = yaml.safe_load(new_text)
        assert doc.get("schema_version") == 2
        assert doc.get("horizons") == [n]
        assert doc.get("horizon_ends", {}).get(f"h{n}") == end_raw
        assert "horizon_months" not in doc and "horizon_end" not in doc and "horizon" not in doc

    return new_text, {
        "kind": "weekly",
        "wrapped_horizon": n,
        "horizon_end": end_raw,
        "derived_fields": derived,
        "in_horizon_removed": in_horizon_removed,
    }


# ── stress: YAML round-trip ──────────────────────────────────────────────────

def migrate_stress_doc(doc: dict) -> tuple[dict, dict]:
    """Мигрирует распарсенный stress-doc in-place. Возвращает (doc, report)."""
    if not isinstance(doc, dict) or doc.get("schema_version") is None:
        raise MigrationRefused("нет schema_version — ранний эксперимент вне scope")
    if str(doc.get("schema_version")).strip() == "2":
        raise MigrationRefused("уже schema_version 2 — миграция не нужна")

    end_raw = str(doc.get("horizon") or "").strip()
    n = months_between(str(doc.get("date") or doc.get("review_date") or ""), end_raw)
    if n is None:
        raise MigrationRefused(
            f"не вычислить месяцы горизонта из date={doc.get('date')!r} horizon={doc.get('horizon')!r}"
        )
    hk = f"h{n}"

    doc["schema_version"] = 2
    doc["horizons"] = [n]
    doc["primary_horizon"] = n
    doc["horizon_ends"] = {hk: end_raw}
    doc.pop("horizon", None)
    doc.pop("horizon_months", None)
    # Единичный ранний type 'portfolio-scenario-stress' (05-12) → канон v2-валидатора.
    if doc.get("type") == "portfolio-scenario-stress":
        doc["type"] = "portfolio-stress-test"

    scen_wrapped = 0
    for sc in (doc.get("scenarios") or {}).values():
        if not isinstance(sc, dict):
            continue
        if "factors" in sc:
            sc["factors_by_horizon"] = {hk: sc.pop("factors")}
            scen_wrapped += 1
        if "portfolio_level" in sc:
            sc["portfolio_level_by_horizon"] = {hk: sc.pop("portfolio_level")}

    pp_wrapped = 0
    for pp in (doc.get("per_position") or {}).values():
        if not isinstance(pp, dict):
            continue
        moved = {f: pp.pop(f) for f in _PP_HORIZON_FIELDS if f in pp}
        if moved:
            pp["by_horizon"] = {hk: moved}
            pp_wrapped += 1

    return doc, {
        "kind": "stress",
        "wrapped_horizon": n,
        "horizon_end": end_raw,
        "scenarios_wrapped": scen_wrapped,
        "positions_wrapped": pp_wrapped,
    }


def _leading_comments(text: str) -> str:
    """Лидирующие #-строки шапки (yaml.dump их теряет — вернём вручную)."""
    head = []
    for ln in text.split("\n"):
        if ln.startswith("#") or not ln.strip():
            head.append(ln)
        else:
            break
    return "\n".join(head) + ("\n" if head else "")


def migrate_file(input_path: str, output_path: str) -> dict:
    with open(input_path, encoding="utf-8") as f:
        text = f.read()
    if yaml is None:
        raise RuntimeError("PyYAML требуется для миграции (parse-гейт weekly / stress round-trip)")
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError as e:
        raise MigrationRefused(f"YAML не парсится: {e}") from e
    if len(docs) != 1:
        raise MigrationRefused(f"мультидокументный YAML ({len(docs)} документов) — вне scope")
    doc = docs[0]
    if not isinstance(doc, dict):
        raise MigrationRefused("top-level не mapping — вне scope")

    dtype = str(doc.get("type") or "")
    if dtype in WEEKLY_TYPES:
        new_text, report = migrate_weekly_text(text)
    elif dtype in STRESS_TYPES:
        new_doc, report = migrate_stress_doc(doc)
        body = yaml.safe_dump(new_doc, sort_keys=False, allow_unicode=True, width=100)
        new_text = _leading_comments(text) + body
    else:
        raise MigrationRefused(f"type: {dtype!r} — не weekly-review-stock/bond и не stress-test")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(new_text)
    report["input"] = input_path
    report["output"] = output_path
    return report


def _cli() -> int:
    p = argparse.ArgumentParser(description="V2-CUTOVER: миграция v1→v2 (wrap-as-single-horizon)")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--report", default=None, help="путь для JSON-репорта (default: stdout)")
    args = p.parse_args()
    try:
        report = migrate_file(args.input, args.output)
    except MigrationRefused as e:
        print(json.dumps({"refused": str(e), "input": args.input}, ensure_ascii=False))
        return 2
    out = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(out)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
