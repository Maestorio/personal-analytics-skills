#!/usr/bin/env python3
"""
Регрессионные тесты для sync_planner.py (memory-sync).

Запуск из корня репозитория:
    python3 skills/memory-sync/tests/test_sync_planner.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "skills" / "memory-sync" / "scripts" / "sync_planner.py"

sys.path.insert(0, str(SCRIPT.parent))
from sync_planner import (  # noqa: E402
    aggregate_source,
    auto_inclusion,
    compute,
    compute_diff,
    compute_eviction,
    find_duplicate_variants,
    format_memory_text,
    is_stale,
    lib_source_key,
    normalize_source,
    period_end_year,
    split_memory,
)


checks_run = 0
checks_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks_run, checks_failed
    checks_run += 1
    status = "OK" if condition else "FAIL"
    if not condition:
        checks_failed += 1
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


# --------------------------------------------------------------------------
# Базовые утилиты
# --------------------------------------------------------------------------

def test_normalize_source():
    print("test_normalize_source")
    check("trim+lowercase", normalize_source("  Stratfor  ") == "stratfor")
    check("сравнение case-insensitive",
          normalize_source("BCS") == normalize_source("bcs"))
    check("кириллица != латиница (методология)",
          normalize_source("BCS") != normalize_source("БКС"))


def test_period_end_year():
    print("test_period_end_year")
    check("'2015-2025' → 2025", period_end_year("2015-2025") == 2025)
    check("'2025' → 2025", period_end_year("2025") == 2025)
    check("None → None", period_end_year(None) is None)
    check("'no-year' → None", period_end_year("no-year") is None)


def test_lib_source_key():
    print("test_lib_source_key")
    check("базовый формат", lib_source_key("[lib] Stratfor: HIGH x | ...") == "stratfor")
    check("с пробелами", lib_source_key("  [lib] CFR: ...") == "cfr")
    check("user entry → None", lib_source_key("Личная заметка") is None)


# --------------------------------------------------------------------------
# Агрегация
# --------------------------------------------------------------------------

def test_aggregate_newest_wins():
    """Шаг 4 §Sort order: newest аудит перетирает trust по subdomain."""
    print("test_aggregate_newest_wins")
    files = [
        {
            "subfolder": "geopolitics", "filename": "stratfor-1995-2025.md",
            "frontmatter": {
                "source": "Stratfor", "audit_date": "2024-11-20",
                "last_updated": "2024-11-20", "period": "1995-2025",
                "trust": {"long-term-russia": "HIGH",
                           "eu-future": "IGNORE",
                           "china-collapse": "IGNORE"},
            },
        },
        {
            "subfolder": "geopolitics", "filename": "stratfor-2015-2025.md",
            "frontmatter": {
                "source": "Stratfor", "audit_date": "2025-03-15",
                "last_updated": "2025-03-15", "period": "2015-2025",
                "trust": {"long-term-russia": "MEDIUM",
                           "china-collapse": "LOW",
                           "middle-east": "HIGH"},
            },
        },
        {
            "subfolder": "geopolitics", "filename": "stratfor-2020-2030.md",
            "frontmatter": {
                "source": "Stratfor", "audit_date": "2026-04-22",
                "last_updated": "2026-04-22", "period": "2020-2030",
                "pin": True,
                "trust": {"middle-east": "MEDIUM", "ai-geopolitics": "IGNORE"},
            },
        },
    ]
    agg = aggregate_source(files)
    check("source = Stratfor", agg["source"] == "Stratfor")
    check("audit_count = 3", agg["audit_count"] == 3)
    check("pin = True (от newest)", agg["pin"] is True)
    check("last_audit_date = max", agg["last_audit_date"] == "2026-04-22")
    trust = agg["trust"]
    check("long-term-russia = MEDIUM (от 2015-2025)",
          trust["long-term-russia"] == "MEDIUM", f"got {trust['long-term-russia']}")
    check("eu-future = IGNORE (только в старом)",
          trust["eu-future"] == "IGNORE")
    check("china-collapse = LOW (от 2015-2025)",
          trust["china-collapse"] == "LOW")
    check("middle-east = MEDIUM (от newest 2020-2030 перетёр HIGH)",
          trust["middle-east"] == "MEDIUM", f"got {trust['middle-east']}")
    check("ai-geopolitics = IGNORE (только в newest)",
          trust["ai-geopolitics"] == "IGNORE")


def test_aggregate_pin_or():
    """pin = логическое ИЛИ по всем аудитам source."""
    print("test_aggregate_pin_or")
    files = [
        {"filename": "a.md", "frontmatter": {"source": "X", "audit_date": "2024-01-01",
                                              "trust": {"sd1": "MEDIUM"}, "pin": False}},
        {"filename": "b.md", "frontmatter": {"source": "X", "audit_date": "2025-01-01",
                                              "trust": {"sd1": "LOW"}, "pin": True}},
        {"filename": "c.md", "frontmatter": {"source": "X", "audit_date": "2026-01-01",
                                              "trust": {"sd1": "HIGH"}, "pin": False}},
    ]
    agg = aggregate_source(files)
    check("pin=True если хотя бы один pin=True", agg["pin"] is True)


def test_auto_inclusion():
    print("test_auto_inclusion")
    check("HIGH → включён",
          auto_inclusion({"trust": {"x": "HIGH"}, "pin": False}) is True)
    check("pin=true → включён",
          auto_inclusion({"trust": {"x": "MEDIUM"}, "pin": True}) is True)
    check("ни HIGH ни pin → НЕ включён",
          auto_inclusion({"trust": {"x": "MEDIUM"}, "pin": False}) is False)
    check("LOW/IGNORE без pin → НЕ включён",
          auto_inclusion({"trust": {"x": "LOW", "y": "IGNORE"}, "pin": False}) is False)


def test_is_stale():
    print("test_is_stale")
    today = date(2026, 5, 5)
    check("last_audit 26 мес назад → stale при threshold=24",
          is_stale({"last_audit_date": "2024-03-01"}, today, 24) is True)
    check("last_audit 12 мес назад → НЕ stale при threshold=24",
          is_stale({"last_audit_date": "2025-05-05"}, today, 24) is False)
    check("None → НЕ stale",
          is_stale({"last_audit_date": None}, today, 24) is False)


# --------------------------------------------------------------------------
# Форматирование
# --------------------------------------------------------------------------

def test_format_memory_text_basic():
    print("test_format_memory_text_basic")
    agg = {
        "source": "CFR", "trust": {"iran": "HIGH", "russia": "MEDIUM"},
        "pin": False, "last_audit_date": "2026-04-22", "audit_count": 1,
    }
    text, fmt = format_memory_text(agg, stale=False, max_chars=500)
    check("базовый формат используется", fmt == "basic", f"got {fmt}")
    check("начинается с [lib] CFR:", text.startswith("[lib] CFR:"))
    check("содержит 'HIGH iran'", "HIGH iran" in text)
    check("содержит 'MEDIUM russia'", "MEDIUM russia" in text)
    check("содержит N=1", "N=1" in text)


def test_format_memory_text_pinned():
    """Если pin без HIGH — показать (pinned)."""
    print("test_format_memory_text_pinned")
    agg = {
        "source": "Atom", "trust": {"small-caps-ru": "MEDIUM", "long-term-strategy": "LOW"},
        "pin": True, "last_audit_date": "2026-01-15", "audit_count": 1,
    }
    text, _ = format_memory_text(agg, stale=False, max_chars=500)
    check("содержит (pinned)", "(pinned)" in text, f"got {text!r}")


def test_format_memory_text_stale():
    print("test_format_memory_text_stale")
    agg = {
        "source": "Old", "trust": {"x": "HIGH"}, "pin": False,
        "last_audit_date": "2024-01-01", "audit_count": 2,
    }
    text, _ = format_memory_text(agg, stale=True, max_chars=500)
    check("содержит ⚠️ stale", "⚠️ stale" in text)


def test_format_memory_text_long_falls_back():
    """Длинный профиль должен сократиться по 5 шагам."""
    print("test_format_memory_text_long_falls_back")
    long_trust = {f"subdomain-name-{i:02d}": ("HIGH" if i % 4 == 0 else "MEDIUM")
                  for i in range(20)}
    agg = {
        "source": "Big Source", "trust": long_trust,
        "pin": False, "last_audit_date": "2026-04-22", "audit_count": 5,
    }
    text, fmt = format_memory_text(agg, stale=False, max_chars=200)
    check("длина <= 200", len(text) <= 200, f"got len={len(text)} fmt={fmt}")
    check("использован формат top_avoid* или короче",
          fmt in {"top_avoid", "top_avoid_top3", "high_ignore_only", "truncated_names"},
          f"got {fmt}")


# --------------------------------------------------------------------------
# Diff
# --------------------------------------------------------------------------

def test_compute_diff():
    print("test_compute_diff")
    target = [
        {"source_key": "stratfor", "text": "[lib] Stratfor: HIGH russia | N=2"},
        {"source_key": "cfr", "text": "[lib] CFR: HIGH iran | N=1"},
        {"source_key": "newone", "text": "[lib] NewOne: HIGH x | N=1"},
    ]
    current_lib = [
        {"id": 1, "text": "[lib] Stratfor: HIGH russia | N=2"},      # skip
        {"id": 2, "text": "[lib] CFR: MEDIUM iran | N=1"},           # replace
        {"id": 3, "text": "[lib] OldSource: HIGH x | N=1"},          # remove
    ]
    diff = compute_diff(target, current_lib)
    check("1 add (NewOne)", len(diff["add"]) == 1 and
          diff["add"][0]["source_key"] == "newone")
    check("1 replace (CFR)", len(diff["replace"]) == 1 and
          diff["replace"][0]["id"] == 2)
    check("1 remove (OldSource)", len(diff["remove"]) == 1 and
          diff["remove"][0]["id"] == 3)
    check("1 skip (Stratfor)", diff["skip"] == 1)


def test_compute_diff_renames():
    print("test_compute_diff_renames")
    target = [
        {"source_key": "sbercib investment research", "text": "[lib] SberCIB Investment Research: LOW ru-budget | N=2"},
        {"source_key": "opec-momr", "text": "[lib] opec-momr: HIGH oil | N=3"},
        {"source_key": "world bank cmo+gep", "text": "[lib] World Bank CMO+GEP: MEDIUM oil | N=1"},
        {"source_key": "world bank mpo russia", "text": "[lib] World Bank MPO Russia: LOW ru | N=1"},
    ]
    current_lib = [
        {"id": 1, "text": "[lib] SberCIB: LOW ru-macro | N=1"},
        {"id": 2, "text": "[lib] OPEC MOMR + WOO: HIGH oil | N=3"},
        {"id": 3, "text": "[lib] World Bank: MEDIUM oil | N=1"},
    ]
    diff = compute_diff(target, current_lib)
    renamed = {r["old_source_key"]: r for r in diff["replace"] if r.get("renamed")}
    check("SberCIB -> replace по переименованию", "sbercib" in renamed and renamed["sbercib"]["id"] == 1)
    check("OPEC -> replace по переименованию", "opec momr + woo" in renamed and renamed["opec momr + woo"]["id"] == 2)
    check("неоднозначный World Bank не склеен",
          "world bank" not in renamed and len(diff["remove"]) == 1 and len(diff["add"]) == 2)


def _idx_file(source, trust, **kw):
    fm = {"source": source, "trust": trust, "audit_date": "2026-04-24",
          "last_updated": "2026-04-24"}
    fm.update(kw)
    return {"subfolder": "ru-sellside", "filename": source + ".md", "frontmatter": fm}


def test_index_ignores():
    print("test_index_ignores")
    library = [
        _idx_file("Invest Era", {"oil-gas-ru": "LOW", "bonds-rub": "HIGH", "finance-ru": "MEDIUM"}),
        _idx_file("SberCIB Investment Research", {"bonds-rub": "HIGH", "oil-gas-ru": "LOW"}),
    ]
    res = compute({
        "today": "2026-10-27", "library": library, "current_memory": [],
        "index_ignores": [
            {"source": "Invest Era", "subdomain": "oil-gas-ru"},
            {"source": "SberCIB", "subdomain": "oil-gas-ru"},
            {"source": "Invest Era", "subdomain": "finance-ru"},
            {"source": "Invest Era", "subdomain": "nope"},
            {"source": "Неизвестный", "subdomain": "x"},
        ],
    })
    aggs = {a["source"]: a for a in res["aggregated_sources"]}
    check("Invest Era oil-gas-ru: LOW -> IGNORE", aggs["Invest Era"]["trust"]["oil-gas-ru"] == "IGNORE")
    check("SberCIB по токен-префиксу", aggs["SberCIB Investment Research"]["trust"]["oil-gas-ru"] == "IGNORE")
    check("MEDIUM не перетирается", aggs["Invest Era"]["trust"]["finance-ru"] == "MEDIUM")
    types = sorted(w["type"] for w in res["warnings"])
    check("предупреждения: противоречие, нет поддомена, нет источника",
          types == ["index_override_contradicts_newest", "index_override_source_unresolved",
                    "index_override_subdomain_missing"], str(types))
    check("IGNORE попал в текст записи", "IGNORE" in aggs["Invest Era"]["memory_text"])


def test_pin_dropped_warning():
    print("test_pin_dropped_warning")
    lib = [_idx_file("Банк России", {"ru-rates-late-cycle": "HIGH"})]
    res = compute({"today": "2026-10-27", "library": lib, "current_memory": [
        {"id": "/lib_cbr.md", "text": "[lib] Банк России: HIGH ru-rates-late-cycle | N=1 (pinned)"}]})
    check("pin_dropped при снятии пина",
          any(w["type"] == "pin_dropped" for w in res["warnings"]))
    lib[0]["frontmatter"]["pin"] = True
    res = compute({"today": "2026-10-27", "library": lib, "current_memory": []})
    check("при pin: true предупреждения нет",
          not any(w["type"] == "pin_dropped" for w in res["warnings"]))


def test_split_memory():
    print("test_split_memory")
    memory = [
        {"id": 1, "text": "[lib] X: ..."},
        {"id": 2, "text": "Личная заметка"},
        {"id": 3, "text": "  [lib] Y: ..."},
    ]
    lib, user = split_memory(memory)
    check("lib содержит 2 entries", len(lib) == 2)
    check("user содержит 1 entry", len(user) == 1)


# --------------------------------------------------------------------------
# Eviction
# --------------------------------------------------------------------------

def test_compute_eviction_candidates():
    print("test_compute_eviction_candidates")
    targets = [
        {"source_key": "low_only", "text": "..."},
        {"source_key": "stale_one", "text": "..."},
        {"source_key": "small", "text": "..."},
        {"source_key": "pinned", "text": "..."},
        {"source_key": "good", "text": "..."},
    ]
    aggregates = {
        "low_only": {"source": "LowOnly", "trust": {"x": "LOW", "y": "IGNORE"},
                      "pin": False, "audit_count": 3},
        "stale_one": {"source": "Stale", "trust": {"x": "HIGH"},
                       "pin": False, "audit_count": 2},
        "small": {"source": "Small", "trust": {"x": "HIGH"},
                   "pin": False, "audit_count": 1},
        "pinned": {"source": "Pinned", "trust": {"x": "LOW"},
                    "pin": True, "audit_count": 1},
        "good": {"source": "Good", "trust": {"x": "HIGH"},
                  "pin": False, "audit_count": 5},
    }
    stale_keys = {"stale_one"}
    ev = compute_eviction(targets, user_entries_count=24, memory_limit=30,
                          warn_threshold=28, aggregates_by_key=aggregates,
                          stale_keys=stale_keys)
    keys_in_order = [c["source_key"] for c in ev["candidates"]]
    check("low_only первый", keys_in_order[0] == "low_only")
    check("stale_one второй", "stale_one" in keys_in_order)
    check("small в кандидатах", "small" in keys_in_order)
    check("pinned НЕ в кандидатах", "pinned" not in keys_in_order)
    check("good НЕ в кандидатах", "good" not in keys_in_order)
    check("ev.needed = True (24+5=29 ≥ warn 28)", ev["needed"] is True)


def test_compute_eviction_not_needed():
    print("test_compute_eviction_not_needed")
    ev = compute_eviction([{"source_key": "x", "text": "..."}],
                          user_entries_count=5, memory_limit=30,
                          warn_threshold=28, aggregates_by_key={
                              "x": {"trust": {"x": "HIGH"}, "pin": False, "audit_count": 1}
                          }, stale_keys=set())
    check("не нужно eviction (5+1=6 < 28)", ev["needed"] is False)


# --------------------------------------------------------------------------
# Дубликаты source
# --------------------------------------------------------------------------

def test_duplicate_variants():
    print("test_duplicate_variants")
    library = [
        {"frontmatter": {"source": "BCS"}},
        {"frontmatter": {"source": "БКС"}},  # разные нормализации — НЕ группируются
        {"frontmatter": {"source": "Stratfor"}},
        {"frontmatter": {"source": "stratfor"}},  # case-only — группируются
    ]
    warnings = find_duplicate_variants(library)
    # Stratfor + stratfor → одна группа с 2 вариантами.
    stratfor_warning = next((w for w in warnings if w["normalized"] == "stratfor"), None)
    check("BCS и БКС → разные источники, нет warning",
          all("bcs" not in w.get("normalized", "") for w in warnings))
    check("Stratfor + stratfor → warning",
          stratfor_warning and len(stratfor_warning["variants"]) == 2)


# --------------------------------------------------------------------------
# Полный пайплайн
# --------------------------------------------------------------------------

def test_compute_pipeline():
    print("test_compute_pipeline")
    payload = {
        "today": "2026-05-05",
        "max_chars": 500,
        "memory_limit": 30,
        "memory_warn_threshold": 28,
        "stale_months": 24,
        "library": [
            {
                "subfolder": "geopolitics", "filename": "cfr-2024.md",
                "frontmatter": {
                    "source": "CFR", "audit_date": "2026-04-22",
                    "last_updated": "2026-04-22", "period": "2024",
                    "trust": {"iran": "HIGH"}, "pin": False,
                },
            },
            {
                "subfolder": "ru-sellside", "filename": "atom-2024.md",
                "frontmatter": {
                    "source": "Atom", "audit_date": "2026-01-15",
                    "last_updated": "2026-01-15",
                    # Только LOW — не должен попасть в memory без pin
                    "trust": {"x": "LOW"}, "pin": False,
                },
            },
            {
                "subfolder": "ru-sellside", "filename": "broken.md",
                "frontmatter": {"source": "Broken"},  # нет trust → skip
            },
        ],
        "current_memory": [
            {"id": 1, "text": "Личная заметка"},        # USER
            {"id": 2, "text": "[lib] OldSrc: HIGH x | N=1"},  # remove
        ],
    }
    res = compute(payload)

    check("files_scanned = 3", res["summary"]["files_scanned"] == 3)
    check("files_skipped >= 1 (broken.md)",
          res["summary"]["files_skipped"] >= 1)
    check("Atom не включён (только LOW, без pin)",
          all(a["source"] != "Atom" or not a["include_in_memory"]
              for a in res["aggregated_sources"]))
    check("CFR включён",
          any(a["source"] == "CFR" and a["include_in_memory"]
              for a in res["aggregated_sources"]))
    check("ровно 1 add (CFR)",
          len(res["operations"]["add"]) == 1)
    check("ровно 1 remove (OldSrc)",
          len(res["operations"]["remove"]) == 1)
    check("USER_ENTRIES = 1", res["summary"]["user_entries_count"] == 1)


def test_cli_stdin():
    print("test_cli_stdin")
    payload = {
        "today": "2026-05-05",
        "library": [{
            "subfolder": "x", "filename": "a.md",
            "frontmatter": {"source": "X", "audit_date": "2026-01-01",
                            "last_updated": "2026-01-01",
                            "trust": {"sd": "HIGH"}},
        }],
        "current_memory": [],
    }
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload), capture_output=True, text=True, check=False,
    )
    check("exit code = 0", proc.returncode == 0, f"stderr: {proc.stderr}")
    out = json.loads(proc.stdout)
    check("1 add", len(out["operations"]["add"]) == 1)


def test_aggregate_trust_3d_uses_marginal():
    """trust 3D (D4 backward-compat): aggregate_source flattens marginal layer."""
    print("test_aggregate_trust_3d_uses_marginal")
    files = [
        {"filename": "a.md", "frontmatter": {"source": "X", "audit_date": "2026-01-01",
            "trust": {
                "marginal": {"sd1": "HIGH", "sd2": "MEDIUM"},
                "world_picking": {"primary-D": "MEDIUM"},
                "conditional": {},
            }}},
    ]
    agg = aggregate_source(files)
    check("3D trust → flattened marginal sd1=HIGH", agg["trust"].get("sd1") == "HIGH")
    check("3D trust → flattened marginal sd2=MEDIUM", agg["trust"].get("sd2") == "MEDIUM")
    check("3D trust → world_picking ignored", "primary-D" not in agg["trust"])


def test_aggregate_trust_3d_and_flat_mixed():
    """3D and 1D mixed across audits — newest still wins."""
    print("test_aggregate_trust_3d_and_flat_mixed")
    files = [
        {"filename": "old.md", "frontmatter": {"source": "X", "audit_date": "2024-01-01",
            "trust": {"sd1": "HIGH"}}},
        {"filename": "new.md", "frontmatter": {"source": "X", "audit_date": "2026-01-01",
            "trust": {
                "marginal": {"sd1": "MEDIUM"},
                "world_picking": {},
                "conditional": {},
            }}},
    ]
    agg = aggregate_source(files)
    check("3D newer overrides 1D older", agg["trust"].get("sd1") == "MEDIUM")


def main() -> int:
    print("=" * 60)
    print("memory-sync / sync_planner.py")
    print("=" * 60)

    test_normalize_source()
    test_period_end_year()
    test_lib_source_key()
    test_aggregate_newest_wins()
    test_aggregate_pin_or()
    test_aggregate_trust_3d_uses_marginal()
    test_aggregate_trust_3d_and_flat_mixed()
    test_auto_inclusion()
    test_is_stale()
    test_format_memory_text_basic()
    test_format_memory_text_pinned()
    test_format_memory_text_stale()
    test_format_memory_text_long_falls_back()
    test_compute_diff()
    test_compute_diff_renames()
    test_index_ignores()
    test_pin_dropped_warning()
    test_split_memory()
    test_compute_eviction_candidates()
    test_compute_eviction_not_needed()
    test_duplicate_variants()
    test_compute_pipeline()
    test_cli_stdin()

    print("=" * 60)
    print(f"Итого: {checks_run - checks_failed}/{checks_run} проверок прошло")
    print("=" * 60)
    return 0 if checks_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
