#!/usr/bin/env python3
"""
sync_planner.py

Детерминированный планировщик для memory-sync:
- агрегация множественных аудитов одного source через newest-wins (Шаг 4)
- auto-inclusion: pin OR (any subdomain trust = HIGH) (Шаг 5)
- форматирование [lib]-записей с 5-шаговым сокращением до 500 симв (Шаг 6)
- diff текущего vs целевого state → add/replace/remove (Шаг 7)
- кандидаты на eviction при предельной заполненности (Шаг 8)
- предупреждения о возможных дубликатах source (BCS vs БКС)

LLM читает файлы через transport, парсит frontmatter, читает memory (view),
передаёт скрипту JSON. Скрипт возвращает план — LLM выполняет confirmation,
вызывает memory API, пишет лог.

CLI:
    cat payload.json | python3 sync_planner.py
    python3 sync_planner.py --input payload.json --output plan.json --pretty

Без внешних зависимостей.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from typing import Any

DEFAULT_MAX_CHARS = 500
DEFAULT_MEMORY_LIMIT = 30
DEFAULT_MEMORY_WARN_THRESHOLD = 28
DEFAULT_STALE_MONTHS = 24

TRUST_ORDER = ["HIGH", "MEDIUM", "LOW", "IGNORE"]
AUDIT_TYPE_ORDER = {"Full": 2, "Light": 1, None: 0}


def parse_date(s: Any) -> date | None:
    if s is None or s == "":
        return None
    if isinstance(s, date):
        return s
    if isinstance(s, datetime):
        return s.date()
    return datetime.strptime(str(s), "%Y-%m-%d").date()


def normalize_source(s: str) -> str:
    """Нормализация для группировки: trim + case-insensitive."""
    if s is None:
        return ""
    return " ".join(s.strip().split()).lower()


def period_end_year(period: str | None) -> int | None:
    """Извлекает последний год из строки 'YYYY-YYYY' или 'YYYY'."""
    if not period:
        return None
    matches = re.findall(r"\d{4}", str(period))
    if not matches:
        return None
    return int(matches[-1])


def file_sort_key(file_entry: dict) -> tuple:
    """
    Newest-first сортировка (Шаг 4 §Sort order):
    1) last_updated 2) period end-year 3) mtime 4) tie-breakers (audit_type, theses_count, filename).
    Возвращает кортеж "чем больше, тем новее".
    """
    fm = file_entry.get("frontmatter") or {}
    last_updated = parse_date(fm.get("last_updated"))
    audit_date = parse_date(fm.get("audit_date"))
    period_year = period_end_year(fm.get("period"))
    mtime = parse_date(file_entry.get("mtime"))
    audit_type_rank = AUDIT_TYPE_ORDER.get(fm.get("audit_type"), 0)
    theses = fm.get("theses_count") or 0
    # Лексически меньшее имя файла → детерминизм при полной идентичности.
    # Используем negative-ord для совпадения "лексически меньшее = старше" → инвертируем
    # сортировку: чем больше ord, тем "новее" в смысле tie-break последний.
    filename = file_entry.get("filename") or ""
    inverse_name = tuple(-ord(c) for c in filename)
    return (
        last_updated or date.min,
        period_year or 0,
        mtime or date.min,
        audit_type_rank,
        theses,
        inverse_name,
    )


TRUST_3D_DIMENSIONS = ("marginal", "world_picking", "conditional")


def _flatten_trust(trust: object) -> dict:
    """Normalize trust 1D ↔ 3D.

    DEPRECATED noop after D8 (CLAUDE.md, 2026-05-10): новые profile все 1D.
    Сохранено для backward-compat с legacy 3D dict из отозванного D4:
    `{marginal: {...}, world_picking: {...}, conditional: {...}}` → trust['marginal'].
    Plain 1D → возвращается как есть.
    """
    if not isinstance(trust, dict):
        return {}
    if (
        trust
        and set(trust.keys()).issubset(set(TRUST_3D_DIMENSIONS))
        and all(isinstance(v, (dict, type(None))) for v in trust.values())
    ):
        return dict(trust.get("marginal") or {})
    return trust


def aggregate_source(files: list[dict]) -> dict:
    """
    Агрегирует несколько аудитов одного source.
    Newest-wins для trust per subdomain; pin = OR; last_audit = max; audit_count = len.
    """
    sorted_files = sorted(files, key=file_sort_key)  # ascending: oldest → newest
    trust_merged: dict[str, str] = {}
    pin_any = False
    last_audit_dates: list[date] = []

    # Идём от старых к новым — каждый следующий перетирает subdomain'ы своего профиля.
    for f in sorted_files:
        fm = f.get("frontmatter") or {}
        flat_trust = _flatten_trust(fm.get("trust"))
        for sd, level in flat_trust.items():
            if level not in TRUST_ORDER:
                continue
            trust_merged[sd] = level
        if fm.get("pin"):
            pin_any = True
        ad = parse_date(fm.get("audit_date") or fm.get("last_updated"))
        if ad is not None:
            last_audit_dates.append(ad)

    last_audit = max(last_audit_dates) if last_audit_dates else None

    # Канонический source — берём из самого свежего файла.
    newest_fm = (sorted_files[-1].get("frontmatter") or {}) if sorted_files else {}
    canonical_source = (newest_fm.get("source") or "").strip()

    return {
        "source": canonical_source,
        "trust": trust_merged,
        "pin": pin_any,
        "last_audit_date": last_audit.isoformat() if last_audit else None,
        "audit_count": len(files),
        "subdomains_covered": sorted(trust_merged.keys()),
    }


def auto_inclusion(aggregate: dict) -> bool:
    """include_in_memory = pin OR (any subdomain trust = HIGH)."""
    if aggregate.get("pin"):
        return True
    return any(level == "HIGH" for level in (aggregate.get("trust") or {}).values())


def is_stale(aggregate: dict, today: date, stale_months: int) -> bool:
    last_audit = parse_date(aggregate.get("last_audit_date"))
    if last_audit is None:
        return False
    months_diff = (today.year - last_audit.year) * 12 + (today.month - last_audit.month)
    return months_diff >= stale_months


# ---------------------------------------------------------------------------
# Форматирование [lib]-записей с 5-шаговым сокращением
# ---------------------------------------------------------------------------

def _group_by_level(trust: dict[str, str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {lvl: [] for lvl in TRUST_ORDER}
    for sd, level in trust.items():
        if level in out:
            out[level].append(sd)
    for lvl in out:
        out[lvl].sort()
    return out


def _suffix(aggregate: dict, stale: bool) -> str:
    parts = [
        f"last_audit {aggregate.get('last_audit_date') or 'unknown'}",
        f"N={aggregate.get('audit_count', 0)}",
    ]
    if aggregate.get("pin") and not _has_high(aggregate.get("trust") or {}):
        parts.append("(pinned)")
    if stale:
        parts.append("⚠️ stale")
    return " | ".join(parts)


def _has_high(trust: dict[str, str]) -> bool:
    return any(level == "HIGH" for level in trust.values())


def _format_basic(source: str, trust: dict[str, str], suffix: str) -> str:
    by_level = _group_by_level(trust)
    parts = []
    for lvl in TRUST_ORDER:
        for sd in by_level[lvl]:
            parts.append(f"{lvl} {sd}")
    body = ", ".join(parts) if parts else "—"
    return f"[lib] {source}: {body} | {suffix}"


def _format_grouped(source: str, trust: dict[str, str], suffix: str) -> str:
    by_level = _group_by_level(trust)
    chunks = []
    for lvl in TRUST_ORDER:
        if by_level[lvl]:
            chunks.append(f"{lvl}: " + ", ".join(by_level[lvl]))
    body = " | ".join(chunks) if chunks else "—"
    return f"[lib] {source}: {body} | {suffix}"


def _format_high_ignore_only(source: str, trust: dict[str, str], suffix: str) -> str:
    by_level = _group_by_level(trust)
    chunks = []
    if by_level["HIGH"]:
        chunks.append("HIGH: " + ", ".join(by_level["HIGH"]))
    if by_level["IGNORE"]:
        chunks.append("IGNORE: " + ", ".join(by_level["IGNORE"]))
    body = " | ".join(chunks) if chunks else "—"
    return f"[lib] {source}: {body} | {suffix}"


def _truncate_subdomain_names(trust: dict[str, str], max_len: int = 20) -> dict[str, str]:
    return {
        (sd if len(sd) <= max_len else sd[: max_len - 3] + "...") : level
        for sd, level in trust.items()
    }


def _format_top_avoid(source: str, trust: dict[str, str], suffix: str,
                      top_n: int | None = None) -> str:
    by_level = _group_by_level(trust)
    high = by_level["HIGH"]
    ignore = by_level["IGNORE"]
    if top_n is not None:
        high_extra = max(0, len(high) - top_n)
        ignore_extra = max(0, len(ignore) - top_n)
        high = high[:top_n]
        ignore = ignore[:top_n]
    else:
        high_extra = ignore_extra = 0

    chunks = []
    if high:
        s = "top: HIGH={" + ", ".join(high) + "}"
        if high_extra:
            s += f" +{high_extra}"
        chunks.append(s)
    if ignore:
        s = "avoid: IGNORE={" + ", ".join(ignore) + "}"
        if ignore_extra:
            s += f" +{ignore_extra}"
        chunks.append(s)
    body = " | ".join(chunks) if chunks else "—"
    return f"[lib] {source}: {body} | {suffix}"


def format_memory_text(aggregate: dict, stale: bool, max_chars: int) -> tuple[str, str]:
    """
    Возвращает (text, format_used).
    Применяет 5-шаговое сокращение пока строка не уложится в max_chars.
    """
    source = aggregate.get("source") or ""
    trust = aggregate.get("trust") or {}
    suffix = _suffix(aggregate, stale)

    # Шаг 0: базовый
    text = _format_basic(source, trust, suffix)
    if len(text) <= max_chars:
        return text, "basic"

    # Шаг 1: грутт-формат (HIGH: {} | MEDIUM: {} | ...)
    text = _format_grouped(source, trust, suffix)
    if len(text) <= max_chars:
        return text, "grouped"

    # Шаг 2: только HIGH и IGNORE
    text = _format_high_ignore_only(source, trust, suffix)
    if len(text) <= max_chars:
        return text, "high_ignore_only"

    # Шаг 3: усечение имён subdomain'ов
    truncated = _truncate_subdomain_names(trust)
    text = _format_high_ignore_only(source, truncated, suffix)
    if len(text) <= max_chars:
        return text, "truncated_names"

    # Шаг 4: top + avoid
    text = _format_top_avoid(source, truncated, suffix)
    if len(text) <= max_chars:
        return text, "top_avoid"

    # Шаг 5: top-3 + +N
    text = _format_top_avoid(source, truncated, suffix, top_n=3)
    return text, "top_avoid_top3"


# ---------------------------------------------------------------------------
# Diff и eviction
# ---------------------------------------------------------------------------

def split_memory(current_memory: list[dict]) -> tuple[list[dict], list[dict]]:
    """Разделение memory на LIB_ENTRIES и USER_ENTRIES."""
    lib, user = [], []
    for entry in current_memory:
        text = entry.get("text") or ""
        if text.lstrip().startswith("[lib]"):
            lib.append(entry)
        else:
            user.append(entry)
    return lib, user


def lib_source_key(text: str) -> str | None:
    """
    Извлекает source из строки '[lib] Source: ...'. Возвращает нормализованный ключ.
    """
    m = re.match(r"^\s*\[lib\]\s+([^:]+):", text)
    if not m:
        return None
    return normalize_source(m.group(1))


def _key_tokens(key: str) -> list[str]:
    return re.findall(r"[0-9a-zа-яё]+", key.lower())


def _is_token_prefix(a: list[str], b: list[str]) -> bool:
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return bool(short) and long_[:len(short)] == short


def _pair_renames(add_ops: list[dict], remove_ops: list[dict], replace_ops: list[dict]) -> None:
    """
    Пара remove+add с ключами, один из которых — токен-префикс другого
    («sbercib» ↔ «sbercib investment research», «opec momr woo» ↔ «opec-momr»),
    — переименование ключа, а не снятие источника: сводится в replace с
    renamed=true. Пара берётся только однозначная с обеих сторон.
    """
    pairs = []
    for rem in remove_ops:
        cands = [a for a in add_ops
                 if _is_token_prefix(_key_tokens(rem["source_key"]), _key_tokens(a["source_key"]))]
        if len(cands) != 1:
            continue
        back = [r for r in remove_ops
                if _is_token_prefix(_key_tokens(r["source_key"]), _key_tokens(cands[0]["source_key"]))]
        if len(back) == 1:
            pairs.append((rem, cands[0]))
    for rem, add in pairs:
        remove_ops.remove(rem)
        add_ops.remove(add)
        replace_ops.append({
            "id": rem.get("id"),
            "source_key": add["source_key"],
            "old_source_key": rem["source_key"],
            "renamed": True,
            "old_text": rem.get("old_text"),
            "new_text": add["new_text"],
        })


def compute_diff(target_entries: list[dict], current_lib: list[dict]) -> dict:
    """
    target_entries: [{source_key, text}]
    current_lib: [{id, text}]
    Возвращает план операций add/replace/remove + skip count.
    """
    # Index current lib by source key.
    current_by_source: dict[str, dict] = {}
    for entry in current_lib:
        key = lib_source_key(entry.get("text") or "")
        if key:
            current_by_source[key] = entry

    target_by_source: dict[str, dict] = {t["source_key"]: t for t in target_entries}

    add_ops: list[dict] = []
    replace_ops: list[dict] = []
    remove_ops: list[dict] = []
    skip_count = 0

    # Add / replace / skip.
    for key, target in target_by_source.items():
        cur = current_by_source.get(key)
        if cur is None:
            add_ops.append({"source_key": key, "new_text": target["text"]})
        elif cur.get("text", "").strip() == target["text"].strip():
            skip_count += 1
        else:
            replace_ops.append({
                "id": cur.get("id"),
                "source_key": key,
                "old_text": cur.get("text"),
                "new_text": target["text"],
            })

    # Remove: всё, что в текущем lib есть, но в target нет.
    for key, cur in current_by_source.items():
        if key not in target_by_source:
            remove_ops.append({
                "id": cur.get("id"),
                "source_key": key,
                "old_text": cur.get("text"),
            })

    _pair_renames(add_ops, remove_ops, replace_ops)

    return {
        "add": add_ops,
        "replace": replace_ops,
        "remove": remove_ops,
        "skip": skip_count,
    }


def compute_eviction(
    target_entries: list[dict],
    user_entries_count: int,
    memory_limit: int,
    warn_threshold: int,
    aggregates_by_key: dict[str, dict],
    stale_keys: set[str],
) -> dict:
    """
    Возвращает кандидатов на eviction в порядке предпочтения:
      1) LOW/IGNORE-only без pin
      2) stale (без pin)
      3) малый audit_count (без pin)
    pin=True никогда не предлагается на eviction.
    """
    predicted_total = user_entries_count + len(target_entries)
    needed = predicted_total > memory_limit or predicted_total >= warn_threshold

    candidates_low = []
    candidates_stale = []
    candidates_small = []

    for t in target_entries:
        key = t["source_key"]
        agg = aggregates_by_key.get(key) or {}
        if agg.get("pin"):
            continue
        levels = set((agg.get("trust") or {}).values())
        if levels and levels.issubset({"LOW", "IGNORE"}):
            candidates_low.append({
                "source_key": key, "source": agg.get("source"),
                "reason": "LOW/IGNORE-only без pin",
            })
            continue
        if key in stale_keys:
            candidates_stale.append({
                "source_key": key, "source": agg.get("source"),
                "reason": f"stale (>{DEFAULT_STALE_MONTHS} мес.)",
            })
            continue
        if (agg.get("audit_count") or 0) <= 1:
            candidates_small.append({
                "source_key": key, "source": agg.get("source"),
                "reason": f"малый audit_count={agg.get('audit_count')}",
            })

    return {
        "needed": needed,
        "predicted_total": predicted_total,
        "user_entries_count": user_entries_count,
        "target_lib_count": len(target_entries),
        "memory_limit": memory_limit,
        "warn_threshold": warn_threshold,
        "candidates": candidates_low + candidates_stale + candidates_small,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def find_duplicate_variants(library: list[dict]) -> list[dict]:
    """
    Ищет вероятные дубликаты source разных написаний (BCS vs БКС и т.п.).
    Группирует по case-insensitive нормализации; если в одной группе ≥2
    разных оригинальных написания — flag.
    """
    by_norm: dict[str, set[str]] = {}
    for f in library:
        fm = f.get("frontmatter") or {}
        src = fm.get("source")
        if not src:
            continue
        key = normalize_source(src)
        by_norm.setdefault(key, set()).add(src.strip())
    warnings = []
    for key, variants in by_norm.items():
        if len(variants) > 1:
            warnings.append({
                "type": "case_variants",
                "normalized": key,
                "variants": sorted(variants),
            })
    return warnings


def apply_index_ignores(
    aggregates_by_key: dict[str, dict], index_ignores: list[dict],
) -> list[dict]:
    """
    Ручные агрегаты INDEX («Подтверждённые IGNORE»): пары {source, subdomain}
    принудительно ставят IGNORE поверх newest-wins. Применяется, только если
    newest-wins даёт LOW/IGNORE; MEDIUM/HIGH (свежий аудит перекрыл INDEX) и
    неразрешённые пары не применяются, а возвращаются предупреждениями.
    Источник сопоставляется по нормализованному ключу или однозначному токен-префиксу.
    """
    warnings: list[dict] = []
    for item in index_ignores or []:
        src_key = normalize_source(item.get("source") or "")
        subdomain = (item.get("subdomain") or "").strip()
        if src_key in aggregates_by_key:
            matches = [src_key]
        else:
            matches = [k for k in aggregates_by_key
                       if _is_token_prefix(_key_tokens(src_key), _key_tokens(k))]
        if len(matches) != 1:
            warnings.append({"type": "index_override_source_unresolved",
                             "source": item.get("source"), "subdomain": subdomain,
                             "candidates": sorted(matches)})
            continue
        agg = aggregates_by_key[matches[0]]
        level = (agg.get("trust") or {}).get(subdomain)
        if level is None:
            warnings.append({"type": "index_override_subdomain_missing",
                             "source": agg["source"], "subdomain": subdomain})
        elif level in ("MEDIUM", "HIGH"):
            warnings.append({"type": "index_override_contradicts_newest",
                             "source": agg["source"], "subdomain": subdomain,
                             "newest_wins": level})
        elif level != "IGNORE":
            agg["trust"][subdomain] = "IGNORE"
            agg.setdefault("index_overrides", []).append(
                {"subdomain": subdomain, "from": level, "to": "IGNORE"})
    return warnings


def compute(payload: dict) -> dict:
    today = parse_date(payload.get("today")) or date.today()
    max_chars = int(payload.get("max_chars", DEFAULT_MAX_CHARS))
    memory_limit = int(payload.get("memory_limit", DEFAULT_MEMORY_LIMIT))
    warn_threshold = int(payload.get("memory_warn_threshold", DEFAULT_MEMORY_WARN_THRESHOLD))
    stale_months = int(payload.get("stale_months", DEFAULT_STALE_MONTHS))

    library = payload.get("library") or []
    current_memory = payload.get("current_memory") or []

    # Skipped files (no source / no trust) + group by source.
    skipped: list[dict] = []
    by_source: dict[str, list[dict]] = {}
    for f in library:
        fm = f.get("frontmatter") or {}
        file_id = f"{f.get('subfolder', '?')}/{f.get('filename', '?')}"
        if fm is None or fm.get("source") is None or fm.get("source") == "":
            skipped.append({"file": file_id, "reason": "no_source_field"})
            continue
        if not fm.get("trust"):
            skipped.append({"file": file_id, "reason": "no_trust_field"})
            continue
        if (
            not fm.get("last_updated") and not fm.get("period")
            and not fm.get("audit_date") and not f.get("mtime")
        ):
            # Не блокирующее — просто warning. Файл всё равно пойдёт в агрегацию.
            pass
        by_source.setdefault(normalize_source(fm["source"]), []).append(f)

    warnings = find_duplicate_variants(library)
    for f in library:
        fm = f.get("frontmatter") or {}
        if (
            fm.get("source") and fm.get("trust")
            and not fm.get("last_updated") and not fm.get("period")
        ):
            warnings.append({
                "type": "missing_dating_fields",
                "file": f"{f.get('subfolder', '?')}/{f.get('filename', '?')}",
            })

    # Aggregate.
    aggregates_by_key: dict[str, dict] = {}
    for source_key, files in by_source.items():
        aggregates_by_key[source_key] = aggregate_source(files)
    warnings += apply_index_ignores(aggregates_by_key, payload.get("index_ignores") or [])
    for source_key, agg in aggregates_by_key.items():
        agg["include_in_memory"] = auto_inclusion(agg)
        agg["is_stale"] = is_stale(agg, today, stale_months)
        agg["source_key"] = source_key
        if agg["include_in_memory"]:
            text, fmt = format_memory_text(agg, agg["is_stale"], max_chars)
            agg["memory_text"] = text
            agg["format_used"] = fmt

    target_entries = [
        {"source_key": agg["source_key"], "text": agg["memory_text"]}
        for agg in aggregates_by_key.values()
        if agg["include_in_memory"]
    ]
    target_entries.sort(key=lambda e: e["source_key"])

    lib_current, user_current = split_memory(current_memory)
    diff = compute_diff(target_entries, lib_current)

    for op in diff["replace"]:
        if "(pinned)" in (op.get("old_text") or "") and "(pinned)" not in op["new_text"]:
            warnings.append({"type": "pin_dropped", "source_key": op["source_key"]})

    stale_keys = {k for k, agg in aggregates_by_key.items() if agg.get("is_stale")}
    eviction = compute_eviction(
        target_entries, len(user_current), memory_limit, warn_threshold,
        aggregates_by_key, stale_keys,
    )

    return {
        "today": today.isoformat(),
        "summary": {
            "files_scanned": len(library),
            "files_skipped": len(skipped),
            "sources_aggregated": len(aggregates_by_key),
            "included_in_memory": len(target_entries),
            "user_entries_count": len(user_current),
            "lib_entries_current": len(lib_current),
            "lib_entries_target": len(target_entries),
            "operations_total": len(diff["add"]) + len(diff["replace"]) + len(diff["remove"]),
        },
        "skipped_files": skipped,
        "warnings": warnings,
        "aggregated_sources": list(aggregates_by_key.values()),
        "operations": diff,
        "eviction": eviction,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sync planner for memory-sync (aggregation + diff + eviction).",
    )
    parser.add_argument("--input", "-i")
    parser.add_argument("--output", "-o")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            payload = json.load(f)
    else:
        payload = json.load(sys.stdin)

    result = compute(payload)
    indent = 2 if args.pretty else None
    serialized = json.dumps(result, ensure_ascii=False, indent=indent)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(serialized)
            f.write("\n")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    sys.exit(main())
