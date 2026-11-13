#!/usr/bin/env python3
"""
fill_catalyst_scenarios.py

Эвристический smart-fill для TODO_LLM маркеров в quant catalysts после миграции.
Применяет типовые паттерны на основе trigger keywords + tagged scenario.

Паттерны:
  RATE_CUT (rate / KS / snizhenie / multiplikator / re-rating tagged "A"):
    A: full × 1.0, B: full × 0.55, C: full × 0.55, D: 0
    CI scales linearly.

  GOV_SPENDING (goszakup / voennoy / gos tagged "C"):
    A: 0, B: 0, C: full, D: full × 0.5

  COMMODITY_GOLD (gold / Pd / PLZL tagged "D"):
    A: full × 0.3, B: full × 0.5, C: full × 0.5, D: full × 1.0

  BRENT_HEADWIND (Brent / cena nefti / tagged "B"):
    A: 0, B: full (downside), C: full × 0.5, D: full × 0.8

  GROWTH (rost / expansion / market_share — null или any tag):
    A: full, B: full × 0.7, C: full × 0.6, D: full × 0.3

  DEFAULT (no pattern match):
    Оставляем tag value, остальные 0 (с inline comment).

Использование:
    python3 fill_catalyst_scenarios.py --input migrated.yaml --output filled.yaml
"""
from __future__ import annotations

import argparse
import re
import sys


PATTERNS = [
    {
        "name": "RATE_CUT",
        "match": re.compile(r"rate[\s_-]?cut|snizhenie\s+KS|rost\s+multiplikator|re[\s-]?reyting|"
                            r"NIM|kreditovani|stavki\s+po\s+ipotek|reklamn|"
                            r"normal[ie]zaci|smy?agcheni", re.IGNORECASE),
        "tag": "A",
        "weights": {"A": 1.0, "B": 0.55, "C": 0.55, "D": 0.0},
    },
    {
        "name": "GOV_SPENDING",
        "match": re.compile(r"goszakup|voennoy|gos\w*kontrakt|import\s+substitution|"
                            r"goss?udar|chizhik|monetka", re.IGNORECASE),
        "tag": "C",
        "weights": {"A": 0.0, "B": 0.0, "C": 1.0, "D": 0.5},
    },
    {
        "name": "COMMODITY_GOLD",
        "match": re.compile(r"gold|XAU|palladium|Pd", re.IGNORECASE),
        "tag": "D",
        "weights": {"A": 0.3, "B": 0.5, "C": 0.5, "D": 1.0},
    },
    {
        "name": "BRENT_HEADWIND",
        "match": re.compile(r"Brent\s+L|brent_headwind|neft\w+\s+dokhod|szhati\w*\s+neft", re.IGNORECASE),
        "tag": "B",
        "weights": {"A": 0.0, "B": 1.0, "C": 0.5, "D": 0.8},
    },
    {
        "name": "MORTGAGE_RISK",
        "match": re.compile(r"lgnot|ipotek\w*\s+end|mortgage", re.IGNORECASE),
        "tag": "B",
        "weights": {"A": 0.0, "B": 1.0, "C": 0.5, "D": 0.3},
    },
    {
        "name": "AI_MONETIZATION",
        "match": re.compile(r"monetiz\w+|AI[\s-]?infra|YandexGPT|fintech_scaling|"
                            r"fintech\s+ozon|take\s+rate|GMV", re.IGNORECASE),
        "tag": None,  # any tag
        "weights": {"A": 1.0, "B": 0.7, "C": 0.6, "D": 0.3},
    },
    {
        "name": "GROWTH_GENERIC",
        "match": re.compile(r"rost\s+vyru|growth|expansion|rasshireni|masshtab|"
                            r"market\s+share|dolya\s+rynka|profitability_turn", re.IGNORECASE),
        "tag": None,
        "weights": {"A": 1.0, "B": 0.7, "C": 0.6, "D": 0.3},
    },
]


def _match_pattern(trigger: str, cat_id: str, tag: str | None) -> dict | None:
    """Find first matching pattern, considering tag if pattern requires it."""
    text = f"{cat_id} {trigger}"
    for pat in PATTERNS:
        if pat["match"].search(text):
            if pat["tag"] is None or pat["tag"] == tag:
                return pat
    return None


def _parse_ci_list(value: str) -> list[float] | None:
    """Parse '[lo, hi]' string to [lo, hi] floats."""
    m = re.match(r"^\s*\[\s*([\-\d.]+)\s*,\s*([\-\d.]+)\s*\]\s*$", value)
    if not m:
        return None
    try:
        return [float(m.group(1)), float(m.group(2))]
    except ValueError:
        return None


def fill(input_path: str, output_path: str) -> dict:
    """
    Reads migrated YAML, finds quantitative catalysts with TODO_LLM, applies heuristic fill.
    """
    with open(input_path, "r", encoding="utf-8") as f:
        text = f.read()
    lines = text.split("\n")

    # Track per-catalyst context (find catalyst block boundaries)
    # State machine to walk the file.
    new_lines = list(lines)
    catalyst_blocks = []  # list of (start_idx, end_idx, id, trigger, tag)
    current = None
    in_cat = False
    cat_indent = None
    last_top_field = None

    for i, L in enumerate(lines):
        m = re.match(r"^(\s+)- id:\s*(\S+)\s*$", L)
        if m:
            if current:
                current["end"] = i - 1
                catalyst_blocks.append(current)
            cat_indent = m.group(1)
            current = {
                "start": i, "end": None, "indent": cat_indent,
                "id": m.group(2), "trigger": "", "tag": None,
                "upside_a": None, "upside_b": None, "upside_c": None, "upside_d": None,
                "ci_a": None, "ci_b": None, "ci_c": None, "ci_d": None,
                "is_quant": False,
                "in_by_scenario": False,
                "in_ci_by_scenario": False,
            }
            continue
        if current:
            # Detect break of block: less-indent "- id:" or section change handled above
            m2 = re.match(r"^(\s+)kind:\s*(\w+)", L)
            if m2 and m2.group(2) == "quantitative":
                current["is_quant"] = True
                continue
            m2 = re.match(r'^\s+trigger:\s*"(.*)"', L)
            if m2: current["trigger"] = m2.group(1); continue
            m2 = re.match(r"^\s+macro_dependency:\s*(\w+)", L)
            if m2:
                v = m2.group(1)
                current["tag"] = None if v == "null" else v
                continue
            # Detect upside_by_scenario block
            if re.match(r"^\s+upside_by_scenario:\s*$", L):
                current["in_by_scenario"] = True
                current["in_ci_by_scenario"] = False
                continue
            if re.match(r"^\s+upside_ci_by_scenario:\s*$", L):
                current["in_ci_by_scenario"] = True
                current["in_by_scenario"] = False
                continue
            if current["in_by_scenario"]:
                m2 = re.match(r"^\s+([ABCD]):\s*([\-\d.]+|TODO_LLM)", L)
                if m2:
                    key = f"upside_{m2.group(1).lower()}"
                    val = m2.group(2)
                    if val != "TODO_LLM":
                        try: current[key] = float(val)
                        except ValueError: pass
                    current[f"line_{key}"] = i
                    continue
            if current["in_ci_by_scenario"]:
                m2 = re.match(r"^\s+([ABCD]):\s*(\[[^]]+\]|TODO_LLM)", L)
                if m2:
                    key = f"ci_{m2.group(1).lower()}"
                    val = m2.group(2)
                    if val != "TODO_LLM":
                        parsed_ci = _parse_ci_list(val)
                        if parsed_ci is not None:
                            current[key] = parsed_ci
                    current[f"line_{key}"] = i
                    continue
            # Конец блока detection: возврат к меньшему индентy + новый список или конец per_stock
            # Простое условие: следующий "- id:" обработает выше; в остальных случаях продолжаем.

    if current:
        current["end"] = len(lines) - 1
        catalyst_blocks.append(current)

    # Apply fill
    filled_count = 0
    patterns_used = {}
    no_pattern = []
    for cat in catalyst_blocks:
        if not cat["is_quant"]:
            continue
        pat = _match_pattern(cat["trigger"], cat["id"], cat["tag"])
        if not pat:
            no_pattern.append((cat["id"], cat["tag"]))
            continue
        # Find anchor value (the scenario whose upside is filled)
        anchor_scen = None
        anchor_val = None
        anchor_ci = None
        for s in ("a", "b", "c", "d"):
            if cat[f"upside_{s}"] is not None:
                anchor_scen = s.upper()
                anchor_val = cat[f"upside_{s}"]
                anchor_ci = cat[f"ci_{s}"]
                break
        if anchor_val is None:
            continue
        # Anchor scaling factor: assume anchor scenario weight in pattern is its full upside
        # i.e. if pattern says A=1.0, B=0.55 and anchor is A=18, then B should be 18*0.55.
        # If anchor is not in pattern's "tag" — use anchor weight as reference.
        anchor_weight = pat["weights"].get(anchor_scen, 1.0)
        if anchor_weight == 0:
            anchor_weight = 1.0  # avoid div/0; use anchor as full
        scale = anchor_val / anchor_weight

        for s_upper in ("A", "B", "C", "D"):
            s = s_upper.lower()
            if cat[f"upside_{s}"] is not None:
                continue
            w = pat["weights"].get(s_upper, 0)
            target_val = round(scale * w, 2)
            target_ci = None
            if anchor_ci:
                ci_scale = w * (anchor_val and (anchor_val) or 1.0)
                if anchor_val:
                    target_ci_lo = round(anchor_ci[0] * w, 2)
                    target_ci_hi = round(anchor_ci[1] * w, 2)
                    target_ci = [target_ci_lo, target_ci_hi]
            # Replace the line
            li = cat.get(f"line_upside_{s}")
            if li is not None:
                indent_pref = re.match(r"^(\s*)", lines[li]).group(1)
                new_lines[li] = f"{indent_pref}{s_upper}: {target_val}  # auto-fill ({pat['name']})"
            li_ci = cat.get(f"line_ci_{s}")
            if li_ci is not None and target_ci is not None:
                indent_pref = re.match(r"^(\s*)", lines[li_ci]).group(1)
                new_lines[li_ci] = f"{indent_pref}{s_upper}: [{target_ci[0]}, {target_ci[1]}]"
            elif li_ci is not None:
                indent_pref = re.match(r"^(\s*)", lines[li_ci]).group(1)
                new_lines[li_ci] = f"{indent_pref}{s_upper}: [{target_val * 0.5}, {target_val * 1.5}]"
            filled_count += 1
        patterns_used[pat["name"]] = patterns_used.get(pat["name"], 0) + 1

    # Catch remaining TODO_LLM: заменить на 0 с inline comment "manual review"
    for i, L in enumerate(new_lines):
        if "TODO_LLM" in L:
            m = re.match(r"^(\s+[ABCD]):\s*TODO_LLM", L)
            if m:
                indent_pref = re.match(r"^(\s+)", L).group(1)
                key = L.strip().split(":")[0]
                # Decide: upside (numeric 0) or CI (list [0,0])
                # Look at surrounding context — if previous non-blank line is "upside_ci_by_scenario:" → CI
                # Heuristic: if scenario line is followed by another scenario CI list → CI
                # Simpler: look back for nearest block header
                # We'll just check if line contains "ci_by_scenario" context by walking back
                ctx = ""
                for j in range(i, max(0, i - 5), -1):
                    if "upside_ci_by_scenario:" in new_lines[j]:
                        ctx = "ci"; break
                    if "upside_by_scenario:" in new_lines[j]:
                        ctx = "up"; break
                if ctx == "ci":
                    new_lines[i] = f"{indent_pref}{key}: [0, 0]  # manual review needed"
                else:
                    new_lines[i] = f"{indent_pref}{key}: 0  # manual review needed"

    new_text = "\n".join(new_lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(new_text)

    return {
        "filled_count": filled_count,
        "patterns_used": patterns_used,
        "no_pattern_match": no_pattern,
        "remaining_TODO_LLM": new_text.count("TODO_LLM"),
        "manual_review_markers": new_text.count("manual review needed"),
    }


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", "-i", required=True)
    ap.add_argument("--output", "-o", required=True)
    ap.add_argument("--report", "-r")
    args = ap.parse_args()
    import json
    rep = fill(args.input, args.output)
    serial = json.dumps(rep, ensure_ascii=False, indent=2)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(serial + "\n")
    else:
        print(serial)


if __name__ == "__main__":
    _cli()
