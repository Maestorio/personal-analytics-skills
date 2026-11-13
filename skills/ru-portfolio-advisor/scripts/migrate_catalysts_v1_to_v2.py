#!/usr/bin/env python3
"""
migrate_catalysts_v1_to_v2.py

Миграция weekly-review-stock/-bond YAML с legacy catalyst schema → METH-1 (kind v2).

Логика:
1. Для каждого catalyst в per_stock.{ticker}.catalyst (и per_bond.{isin}.catalyst):
   - Запустить classify_catalyst → получить suggested_kind.
   - Если binary: добавить `kind: binary`; macro_dependency → active_scenarios=[md] если md не null.
     Структура (p, upside_pct, upside_ci_pct) остаётся как есть.
   - Если quantitative: добавить `kind: quantitative`. Конвертация:
       upside_pct=X, macro_dependency="A" → upside_by_scenario: {A: X, B: TODO_LLM, C: TODO_LLM, D: TODO_LLM}
       upside_ci_pct=[lo,hi] → upside_ci_by_scenario: {A: [lo, hi], others: TODO_LLM}
     Поле `p` удаляется (uncertainty в CI).
   - Comment про источник классификации в catalyst (опц.).

2. Output: новый YAML файл + JSON-репорт (counts + TODO_LLM маркеры).

3. Не использует PyYAML — пишет YAML как plain text с сохранением исходной структуры
   (file-level transformation через line-based parsing).

CLI:
    python3 migrate_catalysts_v1_to_v2.py --input weekly-review-stock-X.yaml \\
                                          --output /tmp/migrated.yaml \\
                                          --report /tmp/migration-report.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

# Make classify_catalyst importable
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)
from classify_catalyst import classify_catalyst  # noqa: E402


def _parse_catalysts_from_yaml(text: str) -> list[dict]:
    """
    Извлекает catalysts из YAML файла. Возвращает list of dict:
      {ticker, idx_within_ticker, start_line, end_line, fields: {id, trigger, p, upside_pct, ...}}

    Парсит line-by-line с tracking indent + per_stock/per_bond context.
    """
    lines = text.split("\n")
    result = []
    ticker = None
    in_per = None  # "per_stock" или "per_bond"
    in_catalyst_list = False
    current = None
    cat_idx = 0
    cat_indent = None

    i = 0
    while i < len(lines):
        L = lines[i]
        # Determine context
        if re.match(r"^per_stock:\s*$", L):
            in_per = "per_stock"
            ticker = None
        elif re.match(r"^per_bond:\s*$", L):
            in_per = "per_bond"
            ticker = None
        elif re.match(r"^[A-Za-z_]\w*:\s*", L) and not L.startswith(" "):
            in_per = None
            ticker = None
        elif in_per:
            m = re.match(r"^  ([A-Za-z][A-Za-z0-9_]*):\s*$", L)
            if m:
                if current:
                    current["end_line"] = i - 1
                    result.append(current)
                    current = None
                ticker = m.group(1)
                in_catalyst_list = False
                cat_idx = 0
                cat_indent = None
            elif ticker:
                # catalyst block header
                m = re.match(r"^    catalyst:\s*$", L)
                if m:
                    in_catalyst_list = True
                    cat_indent = None
                    if current:
                        current["end_line"] = i - 1
                        result.append(current)
                        current = None
                elif in_catalyst_list:
                    # Catalyst entry begins with "      - id:"
                    m = re.match(r"^(\s+)- id:\s*(\S+)", L)
                    if m:
                        if current:
                            current["end_line"] = i - 1
                            result.append(current)
                        indent = m.group(1)
                        cat_indent = indent
                        current = {
                            "ticker": ticker,
                            "idx": cat_idx,
                            "start_line": i,
                            "end_line": None,
                            "indent": indent,
                            "fields": {"id": m.group(2)},
                            "field_lines": {"id": i},
                        }
                        cat_idx += 1
                    elif current and cat_indent is not None:
                        # Поля catalyst с большим indent
                        m = re.match(r"^(\s+)(\w+):\s*(.*)$", L)
                        if m:
                            indent2 = m.group(1)
                            field = m.group(2)
                            value = m.group(3).strip()
                            if len(indent2) > len(cat_indent):
                                # field of current catalyst
                                if value.startswith('"') and value.endswith('"'):
                                    value = value[1:-1]
                                current["fields"][field] = value
                                current["field_lines"][field] = i
                            elif len(indent2) <= len(cat_indent):
                                # Возможно конец catalyst — но "  - id:" already matched above
                                pass
                        # Top-level ticker key — handled at outer level
                # Не catalyst-block — закрываем активный catalyst если он был
        i += 1

    if current:
        current["end_line"] = len(lines) - 1
        result.append(current)

    return result


def _make_catalyst_yaml_block(cat: dict, suggestion: dict, indent: str) -> str:
    """
    Собирает YAML для одного catalyst в новом формате.
    cat: оригинал (dict с полями).
    suggestion: {suggested_kind, confidence, reasoning}.
    indent: пробелы перед "- id:" в исходном файле (типично 6 пробелов).
    """
    base_indent = indent  # e.g. "      "
    field_indent = base_indent + "  "  # "        "
    fields = cat["fields"]
    kind = suggestion["suggested_kind"]
    lines = []

    # Order of fields:
    lines.append(f"{base_indent}- id: {fields.get('id', '<no-id>')}")
    lines.append(f"{field_indent}kind: {kind}")
    if "trigger" in fields:
        v = fields["trigger"]
        # quote if not already
        if v and not (v.startswith('"') and v.endswith('"')):
            v = f'"{v}"'
        lines.append(f"{field_indent}trigger: {v}")
    if "date_window" in fields:
        v = fields["date_window"]
        if v and not (v.startswith('"') and v.endswith('"')):
            v = f'"{v}"'
        lines.append(f"{field_indent}date_window: {v}")
    if "in_horizon" in fields:
        lines.append(f"{field_indent}in_horizon: {fields['in_horizon']}")

    if kind == "binary":
        # p, upside_pct, upside_ci_pct
        if "p" in fields:
            lines.append(f"{field_indent}p: {fields['p']}")
        if "upside_pct" in fields:
            lines.append(f"{field_indent}upside_pct: {fields['upside_pct']}")
        if "upside_ci_pct" in fields:
            lines.append(f"{field_indent}upside_ci_pct: {fields['upside_ci_pct']}")
        if "downside_pct" in fields:
            lines.append(f"{field_indent}downside_pct: {fields['downside_pct']}")
        if "downside_ci_pct" in fields:
            lines.append(f"{field_indent}downside_ci_pct: {fields['downside_ci_pct']}")
    else:
        # quantitative — конвертируем (p, upside_pct, macro_dependency=tag) →
        # upside_by_scenario: {tag: upside_pct, others: TODO_LLM}
        tag = (fields.get("macro_dependency") or "").strip().strip('"').strip("'")
        if tag == "null":
            tag = None
        upside_val = fields.get("upside_pct", "TODO_LLM")
        upside_ci = fields.get("upside_ci_pct", "TODO_LLM")
        # 4 scenarios A/B/C/D
        scenarios = ["A", "B", "C", "D"]
        # Heuristic для распределения тагнутого upside по сценариям:
        # tag → full upside; "соседние" сценарии (excluding D-tag → не-D get partial) → TODO_LLM.
        # Без знания basis оставляем TODO_LLM для всех кроме tag.
        lines.append(f"{field_indent}upside_by_scenario:")
        for s in scenarios:
            if s == tag:
                lines.append(f"{field_indent}  {s}: {upside_val}")
            else:
                lines.append(f"{field_indent}  {s}: TODO_LLM  # bypass scenario: оцени upside исходя из macro_dependency_basis")
        # CI
        lines.append(f"{field_indent}upside_ci_by_scenario:")
        for s in scenarios:
            if s == tag:
                lines.append(f"{field_indent}  {s}: {upside_ci}")
            else:
                lines.append(f"{field_indent}  {s}: TODO_LLM")

    # source / source_quality / macro_dependency (как metadata) / basis
    if "source" in fields:
        v = fields["source"]
        if v and not (v.startswith('"') and v.endswith('"')):
            v = f'"{v}"'
        lines.append(f"{field_indent}source: {v}")
    if "source_quality" in fields:
        lines.append(f"{field_indent}source_quality: {fields['source_quality']}")
    if "macro_dependency" in fields:
        lines.append(f"{field_indent}macro_dependency: {fields['macro_dependency']}")
    if "macro_dependency_basis" in fields:
        # Multi-line block scalar — оставляем как было; но мы не парсим многострочные
        # значит, advisor проставит вручную. Здесь — простая пометка.
        lines.append(f"{field_indent}# macro_dependency_basis: см. оригинал (multi-line)")

    # METH-1 миграция metadata
    lines.append(f"{field_indent}# METH-1 classifier: {kind} ({suggestion['confidence']})")
    if suggestion.get("reasoning"):
        lines.append(f"{field_indent}#   reasoning: {'; '.join(suggestion['reasoning'][:2])}")

    return "\n".join(lines)


def migrate(input_path: str, output_path: str | None) -> dict:
    """
    Читает YAML, парсит catalysts, классифицирует, перезаписывает.
    Возвращает report.
    """
    with open(input_path, "r", encoding="utf-8") as f:
        text = f.read()

    lines = text.split("\n")
    catalysts = _parse_catalysts_from_yaml(text)

    if not catalysts:
        return {
            "input": input_path,
            "catalysts_found": 0,
            "warning": "No catalysts found — possibly non-standard schema or empty review",
        }

    # Classify each
    classifications = []
    for cat in catalysts:
        suggestion = classify_catalyst({
            "id": cat["fields"].get("id"),
            "trigger": cat["fields"].get("trigger", ""),
        })
        classifications.append((cat, suggestion))

    # Build new file: replace each catalyst block with regenerated form
    # Sort by start_line descending (so we can splice from bottom to top without offset issues)
    classifications.sort(key=lambda x: -x[0]["start_line"])
    new_lines = list(lines)
    for cat, sug in classifications:
        new_block = _make_catalyst_yaml_block(cat, sug, cat["indent"])
        start = cat["start_line"]
        end = cat["end_line"]
        # Replace lines [start..end] with new_block
        new_lines[start:end + 1] = new_block.split("\n")

    new_text = "\n".join(new_lines)

    # Stats
    binary_count = sum(1 for _, s in classifications if s["suggested_kind"] == "binary")
    quant_count = sum(1 for _, s in classifications if s["suggested_kind"] == "quantitative")
    todo_count = new_text.count("TODO_LLM")
    low_conf = [(c["fields"].get("id"), s["warnings"]) for c, s in classifications
                if s["confidence"] == "LOW"]

    report = {
        "input": input_path,
        "output": output_path,
        "catalysts_migrated": len(classifications),
        "binary_count": binary_count,
        "quantitative_count": quant_count,
        "todo_llm_markers": todo_count,
        "low_confidence_classifications": low_conf,
        "details": [
            {
                "ticker": c["ticker"],
                "id": c["fields"].get("id"),
                "kind": s["suggested_kind"],
                "confidence": s["confidence"],
                "reasoning": s["reasoning"][:3],
            }
            for c, s in sorted(classifications, key=lambda x: x[0]["start_line"])
        ],
    }

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(new_text)

    return report


def _cli():
    ap = argparse.ArgumentParser(description="Migrate catalyst tree to METH-1 schema v2")
    ap.add_argument("--input", "-i", required=True, help="Input YAML path")
    ap.add_argument("--output", "-o", help="Output YAML path (omit for dry-run)")
    ap.add_argument("--report", "-r", help="JSON report path (default: stdout)")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    report = migrate(args.input, args.output)

    serialized = json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(serialized)
            f.write("\n")
    else:
        sys.stdout.write(serialized)
        sys.stdout.write("\n")


if __name__ == "__main__":
    _cli()
