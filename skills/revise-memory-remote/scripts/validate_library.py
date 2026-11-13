#!/usr/bin/env python3
"""
validate_library.py

Детерминированный валидатор для revise-memory-remote:
- Слой 1: проверка обязательных YAML-полей аудитов, парность INDEX ↔ файлы
- Слой 2: парность .md ↔ .yaml в forecasts/, валидация forecast-events,
  триггеры по датам, broken refs
- Слой 3: парность .md ↔ .yaml в scenarios/, валидация scenario-events,
  сумма probability = 1.0 ± 0.05
- Слой 5: носители портфельной схемы — решения, условия и их состояние, справочник бумаг
  (валидаторы ds_schemas)

LLM читает файлы через transport, парсит YAML, передаёт распарсенный JSON.
Скрипт возвращает плоский список issues с категориями для группировки.

CLI:
    cat payload.json | python3 validate_library.py
    python3 validate_library.py --input payload.json --output report.json --pretty

Без внешних зависимостей.
"""
from __future__ import annotations

import argparse
import json
import re
import os
import sys
from datetime import date, datetime

# Валидаторы целевой схемы (`ds_schemas.py` с кодлистами) — канон в _shared-references/; в упакованном
# .skill — в своей scripts/ (pack.sh кладёт модуль по импорту вместе с транзитивными). Сначала каталог скрипта.
_CL_HERE = os.path.dirname(os.path.abspath(__file__))
for _cl_cand in (_CL_HERE, os.path.normpath(os.path.join(_CL_HERE, "..", "..", "..", "_shared-references"))):
    if _cl_cand not in sys.path:
        sys.path.insert(0, _cl_cand)
import ds_schemas  # noqa: E402
from typing import Any


# YAML спецификация запрещает дубли top-level mapping-ключей,
# но PyYAML их молча перетирает, а js-yaml (viewer) ломается на всём файле.
# Stdlib-only сканер ловит проблему на этапе ревизии.
_TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_\-]*)\s*:(\s|$)")
_BLOCK_SCALAR_TAIL_RE = re.compile(r":\s*[|>][+-]?\d*\s*(#.*)?$")


def find_yaml_top_level_duplicates(text: str) -> list:
    """См. assemble_artifact.find_yaml_top_level_duplicates — копия для standalone-скрипта."""
    if not isinstance(text, str):
        return []
    seen: dict[str, int] = {}
    duplicates: list[dict] = []
    in_block_scalar = False
    block_scalar_indent: int | None = None
    for lineno, line in enumerate(text.splitlines(), start=1):
        if in_block_scalar:
            if not line.strip():
                continue
            stripped = line.lstrip(" \t")
            indent = len(line) - len(stripped)
            if block_scalar_indent is None:
                if indent == 0:
                    in_block_scalar = False
                    block_scalar_indent = None
                else:
                    block_scalar_indent = indent
                    continue
            else:
                if indent < block_scalar_indent:
                    in_block_scalar = False
                    block_scalar_indent = None
                else:
                    continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[:1] in (" ", "\t", "-"):
            continue
        m = _TOP_LEVEL_KEY_RE.match(line)
        if not m:
            continue
        key = m.group(1)
        if _BLOCK_SCALAR_TAIL_RE.search(line):
            in_block_scalar = True
            block_scalar_indent = None
        if key in seen:
            duplicates.append({
                "key": key,
                "first_line": seen[key],
                "duplicate_line": lineno,
            })
        else:
            seen[key] = lineno
    return duplicates

REQUIRED_AUDIT_FIELDS = ("source", "audit_date", "trust")
RECOMMENDED_AUDIT_FIELDS = ("period", "last_updated")

REQUIRED_FORECAST_FIELDS = ("date", "horizon", "domain", "topic")
ALLOWED_INTERVAL_MONTHS = {1, 3, 6, 12}

REQUIRED_SCENARIO_MATRIX_FIELDS = ("date", "horizon", "domain", "topic", "axis_x", "axis_y")
SCENARIO_PROBABILITY_TOLERANCE = 0.05

OVERDUE_FINAL_AUDIT_DAYS = 30
SOON_REVIEW_WINDOW_DAYS = 7


def parse_date(s: Any) -> date | None:
    if s is None or s == "":
        return None
    if isinstance(s, date):
        return s
    if isinstance(s, datetime):
        return s.date()
    return datetime.strptime(str(s), "%Y-%m-%d").date()


def issue(
    layer: str,
    file: str,
    level: str,
    category: str,
    human_message: str,
    action_hint: str = "",
    detail: dict | None = None,
) -> dict:
    out = {
        "layer": layer,
        "file": file,
        "level": level,
        "category": category,
        "human_message": human_message,
        "action_hint": action_hint,
    }
    if detail:
        out["detail"] = detail
    return out


# ---------------------------------------------------------------------------
# Слой 1 — Аудиты
# ---------------------------------------------------------------------------

def validate_audit_frontmatter(file_id: str, frontmatter: dict | None) -> list[dict]:
    """Проверка обязательных и рекомендуемых полей в frontmatter аудита."""
    out = []
    if frontmatter is None:
        out.append(issue(
            "audits", file_id, "yellow",
            "audit_no_frontmatter",
            "нет frontmatter",
            "проверить файл, возможно повреждён",
        ))
        return out

    missing_required = [f for f in REQUIRED_AUDIT_FIELDS if frontmatter.get(f) is None]
    if missing_required:
        out.append(issue(
            "audits", file_id, "red",
            "audit_missing_required",
            f"нет обязательных полей: {', '.join(missing_required)}",
            "добавить вручную или через save-to-library",
            {"missing": missing_required},
        ))

    missing_recommended = [f for f in RECOMMENDED_AUDIT_FIELDS if f not in frontmatter]
    if missing_recommended and not missing_required:
        # Рекомендуемые показываем только если все обязательные на месте.
        out.append(issue(
            "audits", file_id, "yellow",
            "audit_missing_recommended",
            f"нет рекомендуемых полей: {', '.join(missing_recommended)}",
            "дополнить frontmatter",
            {"missing": missing_recommended},
        ))
    return out


def validate_index_consistency(
    layer: str, folder_id: str, file_basenames: list[str], index_entries: list[str] | None,
) -> list[dict]:
    """
    Проверка INDEX.md против реальных файлов.
    file_basenames — фактические имена в папке, index_entries — упомянутые в INDEX.
    """
    if index_entries is None:
        if not file_basenames:
            return []
        return [issue(
            layer, f"{folder_id}/INDEX.md", "yellow",
            "index_check_skipped",
            "проверка INDEX не выполнялась: index_entries не передан",
            "передать index_entries (basename'ы из INDEX.md) в payload",
        )]
    real = set(file_basenames)
    indexed = set(index_entries)

    out = []
    # Файлы в INDEX, которых нет на диске → мёртвые ссылки.
    for missing in sorted(indexed - real):
        out.append(issue(
            layer, f"{folder_id}/INDEX.md", "yellow",
            "index_dead_link",
            f"мёртвая ссылка на {missing}",
            "удалить строку или восстановить файл",
            {"missing": missing},
        ))
    # Файлы на диске, которых нет в INDEX.
    for not_indexed in sorted(real - indexed):
        out.append(issue(
            layer, f"{folder_id}/{not_indexed}", "yellow",
            "index_missing_entry",
            "не занесён в INDEX",
            "добавить строку в INDEX.md",
            {"file": not_indexed},
        ))
    return out


def validate_audits_layer(payload: dict) -> tuple[list[dict], dict]:
    """Слой 1 целиком: проходит все субпапки и проверяет каждую."""
    audits = payload.get("audits") or {}
    issues: list[dict] = []
    checked = 0
    files_with_issues: set[str] = set()

    for subfolder, data in audits.items():
        files = data.get("files") or []
        index_entries = data.get("index_entries")  # None → пропустить INDEX-проверку

        actual_basenames = [f["basename"] for f in files if "basename" in f]

        for f in files:
            checked += 1
            file_id = f"{subfolder}/{f['basename']}"
            file_issues = validate_audit_frontmatter(file_id, f.get("frontmatter"))
            if file_issues:
                files_with_issues.add(file_id)
            issues.extend(file_issues)

        issues.extend(
            validate_index_consistency("audits", subfolder, actual_basenames, index_entries)
        )

    summary = {
        "audits_checked": checked,
        "audits_with_issues": len(files_with_issues),
    }
    return issues, summary


# ---------------------------------------------------------------------------
# Слои 2-3 — общие проверки парности и триггеров
# ---------------------------------------------------------------------------

def check_pairs(layer: str, files_md: list[str], files_yaml: list[str]) -> list[dict]:
    """Парность .md ↔ .yaml. Имена принимаются с расширениями."""
    md_basenames = {f[:-3] for f in files_md if f.endswith(".md")}
    yaml_basenames = {f[:-5] for f in files_yaml if f.endswith(".yaml")}

    out = []
    # .md без yaml.
    for missing in sorted(md_basenames - yaml_basenames):
        out.append(issue(
            layer, f"{missing}.md", "yellow",
            "md_without_yaml",
            "нет парного yaml — events-monitoring невозможен",
            "создать минимальный Tier 1 yaml из frontmatter .md",
        ))
    # yaml без .md.
    for orphan in sorted(yaml_basenames - md_basenames):
        out.append(issue(
            layer, f"{orphan}.yaml", "red",
            "orphan_yaml",
            "orphan yaml (нет .md)",
            "восстановить .md или удалить yaml",
        ))
    return out


def check_docx_companions(layer: str, files_docx: list[str], files_md: list[str]) -> list[dict]:
    """Слой 2.4 — .docx без .md-компаньона."""
    md_basenames = {f[:-3] for f in files_md if f.endswith(".md")}
    out = []
    for f in files_docx:
        if not f.endswith(".docx"):
            continue
        if f[:-5] not in md_basenames:
            out.append(issue(
                layer, f, "yellow",
                "docx_without_md",
                "нет .md-компаньона",
                "создать .md с frontmatter из .docx (см. Workflow 2.8)",
            ))
    return out


def _outcome_capture_sweep(layer: str, file_id: str, yaml_data: dict, today: date) -> list[dict]:
    """Свип исхода для superseded/expired (F7-sweep). Монитор их скипает ради экономии —
    ловит этот maintenance-свип. Резолв-точки (outcome_log.resolve_date + fca_stats + horizon),
    что прошли и не зафиксированы → флаг «захватить outcome + рассмотреть retro-audit».
    ЗАКРЫВАЕТ/пишет — save-to-library (revise только ловит и предлагает)."""
    log = yaml_data.get("outcome_log") or []

    def _filled(e: dict) -> bool:
        if not isinstance(e, dict):
            return False
        return (e.get("actual") is not None) if e.get("kind") == "level" else (e.get("resolved") is not None)

    def _sd(v):  # safe parse — legacy fca_stats-ключи вроде 'horizon_2026_12_31' не роняют свип
        try:
            return parse_date(v)
        except (ValueError, TypeError):
            return None

    filled = {_sd(e.get("resolve_date")) for e in log if isinstance(e, dict) and _filled(e)}
    filled.discard(None)

    points: set = set()
    for e in log:
        if isinstance(e, dict):
            d = _sd(e.get("resolve_date"))
            if d is not None:
                points.add(d)
    for key in (yaml_data.get("fca_stats") or {}):
        d = _sd(key)
        if d is not None:
            points.add(d)
    hz = _sd((yaml_data.get("forecast") or {}).get("horizon") or yaml_data.get("horizon"))
    if hz is not None:
        points.add(hz)

    unfilled = sorted(p for p in points if p is not None and p <= today and p not in filled)
    if not unfilled:
        return []
    status = yaml_data.get("status")
    return [issue(
        layer, file_id, "yellow", "outcome_uncaptured",
        f"{status}: исход на {unfilled[0].isoformat()} не зафиксирован в outcome_log",
        "захватить outcome (web_search → save-to-library пишет) + рассмотреть retrospective-forecast-audit",
        {"resolve_dates_unfilled": [d.isoformat() for d in unfilled], "status": status},
    )]


def check_triggers(layer: str, file_id: str, yaml_data: dict, today: date) -> list[dict]:
    """
    Date-арифметика триггеров актуальности (Слой 2.3 / 3.3).
    active — полная логика; superseded/expired — узкий outcome-свип; resolved — пропуск.
    """
    status = yaml_data.get("status") or "active"
    if status in ("superseded", "expired"):
        return _outcome_capture_sweep(layer, file_id, yaml_data, today)
    if status != "active":            # resolved (уже отаудирован) и прочее — пропускать
        return []

    out = []
    final_audit = yaml_data.get("final_audit") or {}
    final_due = parse_date(final_audit.get("due"))
    final_status = final_audit.get("status")

    if final_due is not None and final_status == "pending":
        delta = (today - final_due).days
        if delta >= OVERDUE_FINAL_AUDIT_DAYS:
            out.append(issue(
                layer, file_id, "red",
                "final_audit_overdue",
                f"final_audit просрочен на {delta} дней",
                "пометить status=expired ИЛИ запустить retrospective-forecast-audit",
                {"days_overdue": delta, "due": final_due.isoformat()},
            ))
        elif delta >= 0:
            out.append(issue(
                layer, file_id, "red",
                "final_audit_due",
                "горизонт прошёл — финальный аудит",
                "запустить retrospective-forecast-audit",
                {"days_overdue": delta, "due": final_due.isoformat()},
            ))

    # §19 — отложенный ретро-аудит: уважаем scheduled_for, НЕ предлагаем expired до даты.
    if final_status == "deferred":
        scheduled = parse_date(final_audit.get("scheduled_for"))
        if scheduled is None:
            out.append(issue(
                layer, file_id, "yellow",
                "deferred_without_schedule",
                "final_audit.status=deferred без scheduled_for — назначь дату или помечай expired",
                "проставить scheduled_for ИЛИ пометить expired",
                {"due": final_due.isoformat() if final_due else None},
            ))
        elif today >= scheduled:
            out.append(issue(
                layer, file_id, "red",
                "deferred_schedule_passed",
                f"отложенный ретро-аудит просрочен на {(today - scheduled).days} дн.",
                "запустить retrospective-forecast-audit ИЛИ пометить expired",
                {"days_overdue": (today - scheduled).days, "scheduled_for": scheduled.isoformat()},
            ))
        # scheduled_for в будущем → уважаем план, ничего не предлагаем

    reviews = yaml_data.get("reviews") or {}
    next_due = parse_date(reviews.get("next_due"))
    if next_due is not None:
        delta = (today - next_due).days
        if delta >= 0:
            out.append(issue(
                layer, file_id, "yellow",
                "review_due",
                f"next_due прошёл ({delta} дн.) — обновить",
                "пересобрать через forecast-confidence-applier",
                {"days_overdue": delta, "next_due": next_due.isoformat()},
            ))
        elif -delta <= SOON_REVIEW_WINDOW_DAYS:
            # next_due в окне 7 дней
            out.append(issue(
                layer, file_id, "green",
                "review_due_soon",
                f"next_due через {-delta} дн. — скоро",
                "информационно, без действия",
                {"days_until": -delta, "next_due": next_due.isoformat()},
            ))
    return out


def check_status_links(
    layer: str, file_id: str, yaml_data: dict, all_files_in_layer: set[str],
) -> list[dict]:
    """Слой 2.5 — superseded_by и final_audit.audit_file должны указывать на существующие файлы."""
    out = []
    status = yaml_data.get("status")
    if status == "superseded":
        sb = yaml_data.get("superseded_by")
        if sb and sb not in all_files_in_layer:
            out.append(issue(
                layer, file_id, "red",
                "broken_superseded_by",
                f"битая ссылка superseded_by → {sb}",
                "восстановить файл или поправить ссылку",
                {"target": sb},
            ))
    if status == "resolved":
        af = (yaml_data.get("final_audit") or {}).get("audit_file")
        if af and af not in all_files_in_layer:
            out.append(issue(
                layer, file_id, "yellow",
                "missing_audit_file",
                f"нет связанного retro-audit файла: {af}",
                "запустить retrospective-forecast-audit или поправить ссылку",
                {"target": af},
            ))
    return out


# ---------------------------------------------------------------------------
# Слой 2 — Forecast-events YAML validation
# ---------------------------------------------------------------------------

def validate_forecast_yaml(file_id: str, yaml_data: dict, scenario_files: set[str] | None = None) -> list[dict]:
    """Слой 2.2 — schema validation для forecast-events."""
    out = []

    if "schema_version" not in yaml_data:
        out.append(issue(
            "forecasts", file_id, "yellow",
            "yaml_no_schema_version",
            "нет schema_version — нужна миграция",
            "добавить schema_version: 1",
        ))

    if yaml_data.get("type") != "forecast-events":
        out.append(issue(
            "forecasts", file_id, "yellow",
            "yaml_wrong_type",
            f"неверный type: {yaml_data.get('type')!r}",
            "поправить type: forecast-events",
        ))

    expected_ref = file_id.split("/")[-1].replace(".yaml", ".md")
    if yaml_data.get("forecast_ref") != expected_ref:
        out.append(issue(
            "forecasts", file_id, "red",
            "yaml_wrong_forecast_ref",
            f"forecast_ref={yaml_data.get('forecast_ref')!r} не соответствует имени файла",
            f"поправить на {expected_ref!r}",
            {"expected": expected_ref, "actual": yaml_data.get("forecast_ref")},
        ))

    forecast = yaml_data.get("forecast") or {}
    missing = [f for f in REQUIRED_FORECAST_FIELDS if forecast.get(f) is None]
    if missing:
        out.append(issue(
            "forecasts", file_id, "red",
            "yaml_missing_forecast_field",
            f"нет обязательных forecast.{{{', '.join(missing)}}}",
            "дополнить forecast",
            {"missing": missing},
        ))

    forecast_date = parse_date(forecast.get("date"))
    horizon = parse_date(forecast.get("horizon"))
    if forecast_date and horizon and horizon < forecast_date:
        out.append(issue(
            "forecasts", file_id, "red",
            "horizon_before_date",
            f"horizon ({horizon}) раньше date ({forecast_date}) — ошибка",
            "поправить даты вручную",
        ))

    interval = (yaml_data.get("reviews") or {}).get("interval_months")
    if interval is not None and interval not in ALLOWED_INTERVAL_MONTHS:
        out.append(issue(
            "forecasts", file_id, "yellow",
            "nonstandard_interval_months",
            f"нестандартный interval_months: {interval} (ожидается {sorted(ALLOWED_INTERVAL_MONTHS)})",
            "поправить или подтвердить намеренное отступление",
            {"actual": interval, "allowed": sorted(ALLOWED_INTERVAL_MONTHS)},
        ))

    final_due = parse_date((yaml_data.get("final_audit") or {}).get("due"))
    if horizon is not None and final_due is not None and final_due != horizon:
        out.append(issue(
            "forecasts", file_id, "yellow",
            "final_audit_due_mismatch",
            f"final_audit.due ({final_due}) ≠ forecast.horizon ({horizon})",
            "синхронизировать final_audit.due с horizon",
        ))

    for collection in ("monitoring", "falsifiers", "thresholds"):
        items = yaml_data.get(collection) or []
        for idx, item in enumerate(items):
            if "auto_checkable" not in item:
                out.append(issue(
                    "forecasts", file_id, "yellow",
                    "missing_auto_checkable",
                    f"{collection}[{idx}] без auto_checkable",
                    "добавить auto_checkable: true|false",
                    {"collection": collection, "index": idx},
                ))
                break  # одного предупреждения на коллекцию хватает

    # Type 1 (isolated) vs Type 2 (conditional_on_scenarios) completeness — events-yaml-spec.md §5.
    has_conditional = (
        "conditional_on_scenarios" in yaml_data
        and yaml_data.get("conditional_on_scenarios") is not None
    )
    is_isolated = bool(yaml_data.get("isolated"))

    if not has_conditional and not is_isolated:
        out.append(issue(
            "forecasts", file_id, "red",
            "missing_scenario_attribution",
            "ни isolated: true, ни conditional_on_scenarios — Type 1/2 не определён",
            "добавить isolated: true (с isolated_reason) или conditional_on_scenarios block",
        ))

    if has_conditional and is_isolated:
        out.append(issue(
            "forecasts", file_id, "red",
            "mixed_isolated_with_conditional",
            "одновременно isolated: true и conditional_on_scenarios — взаимоисключимы",
            "удалить одно из двух",
        ))

    if has_conditional:
        # Type 2 conditional обязан иметь Layer 1 marginal (forecast.central_estimate).
        forecast_block = yaml_data.get("forecast") or {}
        if not forecast_block.get("central_estimate"):
            out.append(issue(
                "forecasts", file_id, "red",
                "type2_missing_layer1_marginal",
                "Type 2 conditional forecast без forecast.central_estimate (Layer 1)",
                "запустить FCA, заполнить forecast.central_estimate — нужно для ru-portfolio-advisor",
            ))

        cond = yaml_data["conditional_on_scenarios"] or {}
        by_scenario = cond.get("by_scenario") or {}
        if isinstance(by_scenario, dict):
            present = set(by_scenario.keys())
            missing_keys = {"A", "B", "C", "D"} - present
            if missing_keys:
                out.append(issue(
                    "forecasts", file_id, "red",
                    "incomplete_by_scenario",
                    f"by_scenario неполный, нет ключей: {sorted(missing_keys)}",
                    "добавить недостающие сценарии (provenance=derived_from_marginal если нет native FCA)",
                    {"missing": sorted(missing_keys)},
                ))

        source_matrix = cond.get("source_matrix")
        if isinstance(source_matrix, str):
            if not source_matrix.startswith("scenarios/"):
                out.append(issue(
                    "forecasts", file_id, "red",
                    "invalid_source_matrix_path",
                    f"source_matrix должен начинаться с 'scenarios/': {source_matrix!r}",
                    "поправить путь",
                ))
            elif scenario_files is not None:
                basename = source_matrix.split("/", 1)[1]
                if basename not in scenario_files:
                    out.append(issue(
                        "forecasts", file_id, "red",
                        "dangling_source_matrix",
                        f"source_matrix указывает на отсутствующий scenario YAML: {source_matrix!r}",
                        "поправить путь или восстановить scenario YAML",
                        {"missing": basename, "available": sorted(scenario_files)[:5]},
                    ))

    return out


def validate_forecasts_layer(payload: dict, today: date) -> tuple[list[dict], dict]:
    forecasts = payload.get("forecasts") or {}
    issues: list[dict] = []

    files_md = forecasts.get("files_md") or []
    files_yaml = forecasts.get("files_yaml") or []
    files_docx = forecasts.get("files_docx") or []
    yaml_data_map = forecasts.get("yaml_data") or {}
    raw_yaml_map = forecasts.get("raw_yaml") or {}
    index_entries = forecasts.get("index_entries")

    scenario_yaml_basenames = set((payload.get("scenarios") or {}).get("files_yaml") or [])

    # Парность.
    issues.extend(check_pairs("forecasts", files_md, files_yaml))
    issues.extend(check_docx_companions("forecasts", files_docx, files_md))

    # Дубликаты top-level ключей в исходном YAML — если payload содержит raw_yaml.
    for fname, raw_text in raw_yaml_map.items():
        for d in find_yaml_top_level_duplicates(raw_text):
            issues.append(issue(
                "forecasts", fname, "red",
                "duplicate_yaml_key",
                (
                    f"top-level ключ '{d['key']}' дублируется "
                    f"(строки {d['first_line']} и {d['duplicate_line']})"
                ),
                "слить items в одну секцию; удалить второе вхождение ключа",
                {"key": d["key"], "first_line": d["first_line"],
                 "duplicate_line": d["duplicate_line"]},
            ))

    # Per-yaml schema/triggers/status.
    all_files = set(files_md) | set(files_yaml) | set(files_docx)
    for fname, ydata in yaml_data_map.items():
        if not isinstance(ydata, dict):
            issues.append(issue(
                "forecasts", fname, "red",
                "yaml_unparseable", "yaml не парсится",
                "проверить синтаксис вручную",
            ))
            continue
        issues.extend(validate_forecast_yaml(fname, ydata, scenario_yaml_basenames))
        issues.extend(check_triggers("forecasts", fname, ydata, today))
        issues.extend(check_status_links("forecasts", fname, ydata, all_files))

    # INDEX-проверка.
    actual_basenames = sorted(set(files_md) | set(files_yaml))
    issues.extend(validate_index_consistency(
        "forecasts", "forecasts", actual_basenames, index_entries,
    ))

    summary = {
        "forecasts_md": len(files_md),
        "forecasts_yaml": len(files_yaml),
        "forecasts_docx": len(files_docx),
        "forecasts_with_issues": len(set(i["file"] for i in issues if i["layer"] == "forecasts")),
    }
    return issues, summary


# ---------------------------------------------------------------------------
# Слой 3 — Scenario-events YAML validation
# ---------------------------------------------------------------------------

def extract_scenario_triggers(yaml_data: dict) -> list[dict]:
    """
    `scenario_triggers` списком, откуда бы он ни лежал: спека
    (`scenario-yaml-spec.md` §1.1) кладёт блок под `matrix`, все шесть живых
    матриц — на верхний уровень. Верхний приоритетнее (там реальность).

    Единая точка нужна, потому что две половины этого файла разошлись: проверка
    полноты матрицы читала верхний уровень и работала, а сборщик scenario_ids
    для кросс-проверки weekly-обзоров смотрел только под `matrix` и обходил блок
    как mapping — то есть на КАЖДОЙ живой матрице получал пусто и молча
    отключал кросс-проверку `macro_dependency`. Тот же класс дефекта, что
    `recalibrate.load_weights` (MFC-5).
    """
    if not isinstance(yaml_data, dict):
        return []
    triggers = yaml_data.get("scenario_triggers")
    if triggers is None:
        matrix = yaml_data.get("matrix")
        triggers = matrix.get("scenario_triggers") if isinstance(matrix, dict) else None
    if isinstance(triggers, list):
        return [t for t in triggers if isinstance(t, dict)]
    return []


def validate_scenario_yaml(file_id: str, yaml_data: dict) -> list[dict]:
    """Слой 3.2 — scenario-events validation, включая сумму probability."""
    out = []

    if "schema_version" not in yaml_data:
        out.append(issue(
            "scenarios", file_id, "yellow",
            "yaml_no_schema_version",
            "нет schema_version — нужна миграция",
            "добавить schema_version: 1",
        ))

    if yaml_data.get("type") != "scenario-events":
        out.append(issue(
            "scenarios", file_id, "yellow",
            "yaml_wrong_type",
            f"неверный type: {yaml_data.get('type')!r}",
            "поправить type: scenario-events",
        ))

    expected_ref = file_id.split("/")[-1].replace(".yaml", ".md")
    if yaml_data.get("scenario_ref") != expected_ref:
        out.append(issue(
            "scenarios", file_id, "red",
            "yaml_wrong_scenario_ref",
            f"scenario_ref={yaml_data.get('scenario_ref')!r} не соответствует имени файла",
            f"поправить на {expected_ref!r}",
        ))

    matrix = yaml_data.get("matrix") or {}
    missing = [f for f in REQUIRED_SCENARIO_MATRIX_FIELDS if matrix.get(f) is None]
    if missing:
        out.append(issue(
            "scenarios", file_id, "red",
            "yaml_missing_matrix_field",
            f"нет обязательных matrix.{{{', '.join(missing)}}}",
            "дополнить matrix",
            {"missing": missing},
        ))

    matrix_date = parse_date(matrix.get("date"))
    horizon = parse_date(matrix.get("horizon"))
    if matrix_date and horizon and horizon < matrix_date:
        out.append(issue(
            "scenarios", file_id, "red",
            "horizon_before_date",
            f"horizon ({horizon}) раньше date ({matrix_date}) — ошибка",
            "поправить даты вручную",
        ))

    triggers = extract_scenario_triggers(yaml_data)
    if len(triggers) != 4:
        out.append(issue(
            "scenarios", file_id, "yellow",
            "scenario_triggers_count",
            f"ожидается 4 сценария (Shell 2x2), получено {len(triggers)}",
            "проверить полноту матрицы",
            {"actual": len(triggers)},
        ))

    if triggers:
        probs = [t.get("probability") for t in triggers if isinstance(t.get("probability"), (int, float))]
        if probs:
            total = round(sum(probs), 4)
            if abs(total - 1.0) > SCENARIO_PROBABILITY_TOLERANCE:
                out.append(issue(
                    "scenarios", file_id, "yellow",
                    "probability_sum_off",
                    f"суммарная вероятность {total} ≠ 1.0",
                    "перебалансировать probability",
                    {"sum": total, "tolerance": SCENARIO_PROBABILITY_TOLERANCE},
                ))

    final_due = parse_date((yaml_data.get("final_audit") or {}).get("due"))
    if horizon is not None and final_due is not None and final_due != horizon:
        out.append(issue(
            "scenarios", file_id, "yellow",
            "final_audit_due_mismatch",
            f"final_audit.due ({final_due}) ≠ matrix.horizon ({horizon})",
            "синхронизировать final_audit.due с horizon",
        ))
    return out


def validate_scenarios_layer(payload: dict, today: date) -> tuple[list[dict], dict]:
    scenarios = payload.get("scenarios") or {}
    issues: list[dict] = []

    files_md = scenarios.get("files_md") or []
    files_yaml = scenarios.get("files_yaml") or []
    yaml_data_map = scenarios.get("yaml_data") or {}
    raw_yaml_map = scenarios.get("raw_yaml") or {}
    index_entries = scenarios.get("index_entries")

    issues.extend(check_pairs("scenarios", files_md, files_yaml))

    for fname, raw_text in raw_yaml_map.items():
        for d in find_yaml_top_level_duplicates(raw_text):
            issues.append(issue(
                "scenarios", fname, "red",
                "duplicate_yaml_key",
                (
                    f"top-level ключ '{d['key']}' дублируется "
                    f"(строки {d['first_line']} и {d['duplicate_line']})"
                ),
                "слить items в одну секцию; удалить второе вхождение ключа",
                {"key": d["key"], "first_line": d["first_line"],
                 "duplicate_line": d["duplicate_line"]},
            ))

    all_files = set(files_md) | set(files_yaml)
    for fname, ydata in yaml_data_map.items():
        if not isinstance(ydata, dict):
            issues.append(issue(
                "scenarios", fname, "red",
                "yaml_unparseable", "yaml не парсится",
                "проверить синтаксис вручную",
            ))
            continue
        issues.extend(validate_scenario_yaml(fname, ydata))
        issues.extend(check_triggers("scenarios", fname, ydata, today))
        issues.extend(check_status_links("scenarios", fname, ydata, all_files))

    actual_basenames = sorted(set(files_md) | set(files_yaml))
    issues.extend(validate_index_consistency(
        "scenarios", "scenarios", actual_basenames, index_entries,
    ))

    summary = {
        "scenarios_md": len(files_md),
        "scenarios_yaml": len(files_yaml),
        "scenarios_with_issues": len(set(i["file"] for i in issues if i["layer"] == "scenarios")),
    }
    return issues, summary


# ---------------------------------------------------------------------------
# Слой 4 — Weekly-reviews catalyst kind validation (METH-1, 2026-05-13)
# ---------------------------------------------------------------------------

def validate_catalyst_schema(
    catalyst: dict,
    scenario_ids: set[str] | None,
    path: str,
) -> list[dict]:
    """
    Валидация одного catalyst по METH-1 schema.
    `path` — для сообщений (e.g., "per_stock.SBER.catalyst[0]").
    `scenario_ids` — множество допустимых scenario_id (None = пропустить cross-check).
    Возвращает список issues (без поля layer/file — caller добавит).
    """
    out = []
    cid = catalyst.get("id", "<no-id>")
    raw_kind = catalyst.get("kind")

    if raw_kind is None:
        # Legacy detection
        if "upside_by_scenario" in catalyst:
            out.append({
                "level": "yellow",
                "category": "catalyst_missing_kind",
                "human_message": f"{path} ({cid}): нет поля kind, по эвристике quantitative",
                "action_hint": "добавить kind: quantitative",
            })
        elif "p" in catalyst and ("upside_pct" in catalyst or "downside_pct" in catalyst):
            out.append({
                "level": "yellow",
                "category": "catalyst_missing_kind",
                "human_message": f"{path} ({cid}): нет поля kind, по эвристике binary (legacy)",
                "action_hint": "добавить kind: binary (или quantitative если катализатор непрерывный)",
            })
        else:
            out.append({
                "level": "red",
                "category": "catalyst_invalid_structure",
                "human_message": f"{path} ({cid}): нет ни kind, ни legacy полей (p+upside_pct)",
                "action_hint": "добавить kind + соответствующие поля",
            })
        return out

    kind = str(raw_kind).strip().lower()
    if kind not in ("binary", "quantitative"):
        out.append({
            "level": "red",
            "category": "catalyst_invalid_kind",
            "human_message": f"{path} ({cid}): kind={raw_kind!r}, допустимо binary | quantitative",
            "action_hint": "поправить kind",
        })
        return out

    if kind == "binary":
        if "p" not in catalyst:
            out.append({
                "level": "red", "category": "catalyst_binary_missing_p",
                "human_message": f"{path} ({cid}): binary catalyst без p",
                "action_hint": "добавить p ∈ (0, 0.95]",
            })
        else:
            try:
                p_val = float(catalyst["p"])
                if not (0 < p_val <= 0.95):
                    out.append({
                        "level": "red", "category": "catalyst_binary_p_out_of_range",
                        "human_message": f"{path} ({cid}): p={p_val} вне (0, 0.95]",
                        "action_hint": "p ∈ (0, 0.95]; для уверенных событий p ≤ 0.95",
                    })
            except (TypeError, ValueError):
                out.append({
                    "level": "red", "category": "catalyst_binary_p_invalid",
                    "human_message": f"{path} ({cid}): p={catalyst['p']!r} не numeric",
                    "action_hint": "p должно быть числом",
                })
        if "upside_pct" not in catalyst and "downside_pct" not in catalyst and "upside_by_scenario" not in catalyst:
            out.append({
                "level": "red", "category": "catalyst_binary_missing_upside",
                "human_message": f"{path} ({cid}): binary без upside_pct/downside_pct/upside_by_scenario",
                "action_hint": "добавить одно из трёх",
            })
        # Cross-check active_scenarios IDs если заданы
        active = catalyst.get("active_scenarios")
        if active and scenario_ids is not None:
            unknown = [s for s in active if s not in scenario_ids]
            if unknown:
                out.append({
                    "level": "red", "category": "catalyst_scenario_id_unknown",
                    "human_message": f"{path} ({cid}): active_scenarios содержит неизвестные ID: {unknown}",
                    "action_hint": f"допустимые ID: {sorted(scenario_ids)}",
                    "detail": {"unknown": unknown, "valid": sorted(scenario_ids)},
                })
        # И macro_dependency как legacy single-id
        macro_dep = catalyst.get("macro_dependency")
        if macro_dep and scenario_ids is not None and macro_dep not in scenario_ids:
            out.append({
                "level": "yellow", "category": "catalyst_macro_dependency_unknown",
                "human_message": f"{path} ({cid}): macro_dependency={macro_dep!r} не найден в сценариях",
                "action_hint": f"допустимые ID: {sorted(scenario_ids)} или null",
            })

    elif kind == "quantitative":
        if "p" in catalyst and catalyst.get("p") is not None:
            out.append({
                "level": "yellow", "category": "catalyst_quantitative_has_p",
                "human_message": f"{path} ({cid}): quantitative catalyst имеет p — игнорируется агрегатором",
                "action_hint": "удалить p (uncertainty в CI)",
            })
        ubs = catalyst.get("upside_by_scenario")
        if not ubs:
            out.append({
                "level": "red", "category": "catalyst_quantitative_missing_scenarios",
                "human_message": f"{path} ({cid}): quantitative без upside_by_scenario",
                "action_hint": "добавить upside_by_scenario с 4 сценариями",
            })
        else:
            if scenario_ids is not None:
                unknown = [k for k in ubs.keys() if k not in scenario_ids]
                if unknown:
                    out.append({
                        "level": "red", "category": "catalyst_scenario_id_unknown",
                        "human_message": f"{path} ({cid}): upside_by_scenario содержит неизвестные ID: {unknown}",
                        "action_hint": f"допустимые ID: {sorted(scenario_ids)}",
                        "detail": {"unknown": unknown, "valid": sorted(scenario_ids)},
                    })
                missing = [s for s in scenario_ids if s not in ubs]
                if missing:
                    out.append({
                        "level": "yellow", "category": "catalyst_quantitative_incomplete_scenarios",
                        "human_message": f"{path} ({cid}): upside_by_scenario не заполнен для {missing} (будет 0)",
                        "action_hint": "заполнить значения для всех 4 сценариев",
                    })

    return out


# per_bond.ytm_pct выше этого порога — почти наверняка yield-to-offer, ошибочно
# записанный как YTM-к-погашению (carry-базис). На горизонте integrated-view такой
# ytm раздувает carry в сотни %. См. portfolio-integrated-view CARRY_YTM_SANITY_PCT.
BOND_YTM_SANITY_PCT = 100.0


def validate_weekly_reviews_layer(payload: dict) -> tuple[list[dict], dict]:
    """
    Валидация catalyst kind schema в weekly-review-stock/-bond YAML.
    Payload format:
      "weekly_reviews": {
        "files_yaml": ["weekly-review-stock-2026-05-11.yaml", ...],
        "yaml_data": {fname: {schema_version, type, per_stock: {ticker: {catalyst: [...]}}, ...}, ...}
      }
    Scenarios IDs берутся из payload["scenarios"]["yaml_data"][...] (объединение всех scenario IDs).
    """
    weekly = payload.get("weekly_reviews") or {}
    issues: list[dict] = []
    files_yaml = weekly.get("files_yaml") or []
    yaml_data_map = weekly.get("yaml_data") or {}

    # Собираем все известные scenario IDs из scenarios layer
    scenario_ids: set[str] = set()
    sc_data = (payload.get("scenarios") or {}).get("yaml_data") or {}
    for sc_fname, sc_yaml in sc_data.items():
        for t in extract_scenario_triggers(sc_yaml):
            sid = t.get("scenario_id")
            if isinstance(sid, str) and sid.strip():
                scenario_ids.add(sid.strip())
    # Если в payload не передали scenarios — disable cross-check (pass None)
    sids = scenario_ids if scenario_ids else None
    # Отключённая кросс-проверка обязана быть слышна. Раньше она молчала:
    # scenario_ids не собирались НИ НА ОДНОЙ живой матрице (читался не тот
    # уровень), и отчёт выглядел так, будто macro_dependency проверены.
    if sc_data and not scenario_ids:
        issues.append(issue(
            "weekly_reviews", "<scenarios>", "yellow",
            "scenario_ids_not_extracted",
            f"scenario-файлы переданы ({len(sc_data)} шт.), но ни одного "
            f"scenario_id извлечь не удалось — кросс-проверка macro_dependency "
            f"и active_scenarios ОТКЛЮЧЕНА",
            "проверить, что в матрицах есть scenario_triggers списком "
            "(scenario-yaml-spec.md §1.1)",
        ))

    for fname, ydata in yaml_data_map.items():
        if not isinstance(ydata, dict):
            issues.append(issue(
                "weekly_reviews", fname, "red",
                "yaml_unparseable", "yaml не парсится",
                "проверить синтаксис вручную",
            ))
            continue
        # Поддерживаем оба ключа: per_stock и per_bond
        for collection_key in ("per_stock", "per_bond"):
            per = ydata.get(collection_key) or {}
            if not isinstance(per, dict):
                continue
            for ticker, pos in per.items():
                if not isinstance(pos, dict):
                    continue
                # per_bond: ytm_pct-санити — отлов yield-to-offer, записанного как YTM
                if collection_key == "per_bond":
                    ytm = pos.get("ytm_pct")
                    if isinstance(ytm, (int, float)) and not isinstance(ytm, bool) \
                            and ytm > BOND_YTM_SANITY_PCT:
                        issues.append(issue(
                            "weekly_reviews", fname, "yellow",
                            "bond_ytm_implausible",
                            f"{ticker}: ytm_pct={ytm}% > {BOND_YTM_SANITY_PCT:.0f}% — "
                            f"вероятно yield-to-offer, а не YTM-к-погашению",
                            "если у бумаги близкая оферта — перенести значение в "
                            "ytm_to_offer_pct, ytm_pct оставить YTM-к-погашению или null; "
                            "экономику оферты держать в catalyst",
                        ))
                catalysts = pos.get("catalyst") or []
                for idx, cat in enumerate(catalysts):
                    if not isinstance(cat, dict):
                        continue
                    path = f"{collection_key}.{ticker}.catalyst[{idx}]"
                    for item in validate_catalyst_schema(cat, sids, path):
                        issues.append(issue(
                            "weekly_reviews", fname,
                            item["level"], item["category"],
                            item["human_message"], item.get("action_hint", ""),
                            item.get("detail"),
                        ))

    summary = {
        "weekly_reviews_yaml": len(files_yaml),
        "weekly_reviews_with_issues": len(set(i["file"] for i in issues if i["layer"] == "weekly_reviews")),
    }
    return issues, summary


# ---------------------------------------------------------------------------
# Слой 5 — Носители портфельной схемы (schema.md §3.1–§3.3, §4.8)
# ---------------------------------------------------------------------------
#
# Решения `Portfolio/decisions/*.json` (decision@1), определения условий `Portfolio/conditions.yaml`
# (conditions@2) и их состояние `Portfolio/conditions-state.json` (conditions-state@1), справочник бумаг
# `Portfolio/security-attrs.json` (security-attrs@1). Правила схемы — у общих валидаторов `ds_schemas`; здесь
# только раскладка их ошибок в issues и проверки по библиотеке целиком.
#
# Payload (всё опционально; нет ключа или null — проверка пропускается):
#   "portfolio_carriers": {
#     "decisions": {"2026-10-30T1015-GMKN.json": {...}, ...},  # распарсенные файлы decisions/
#     "conditions": {...},                 # conditions.yaml
#     "conditions_archive": [{...}, ...],  # conditions-archive-{ГГГГ}.yaml — для ссылок событий на прошлые условия
#     "conditions_state": {...},           # conditions-state.json
#     "security_attrs": {...},             # security-attrs.json
#     "snapshot_keys": ["SBER", "RU000A10…", ...],  # ключи бумаг последнего снапшота
#     "blocked_keys": ["JPM", ...],        # замороженные бумаги снапшота — вычитаются из snapshot_keys
#   }

LAYER_CARRIERS = "portfolio_carriers"
_ERR_PREVIEW = 5


def _schema_issue(file_id: str, category: str, what: str, errs: list[str], hint: str) -> dict:
    head = "; ".join(errs[:_ERR_PREVIEW]) + (f"; … ещё {len(errs) - _ERR_PREVIEW}" if len(errs) > _ERR_PREVIEW else "")
    return issue(LAYER_CARRIERS, file_id, "red", category, f"{what}: {head}", hint, {"errors": errs})


def validate_portfolio_carriers_layer(payload: dict, today: date) -> tuple[list[dict], dict]:
    pc = payload.get(LAYER_CARRIERS) or {}
    issues: list[dict] = []
    files_with_issues: set[str] = set()

    # 1. Решения: схема, имя файла = id, просроченный review_by у текущего решения бумаги.
    decisions = pc.get("decisions") or {}
    valid: list[dict] = []
    for name in sorted(decisions):
        obj = decisions[name]
        file_id = f"decisions/{name}"
        errs = ds_schemas.validate_decision(obj)
        if errs:
            issues.append(_schema_issue(file_id, "ds_decision_invalid", "решение не проходит decision@1", errs,
                                        "исправить скриптом decision_write.py (save-to-library), не вручную"))
            files_with_issues.add(file_id)
            continue
        if name != f"{obj['id']}.json":
            issues.append(issue(LAYER_CARRIERS, file_id, "red", "ds_decision_name_mismatch",
                                f"имя файла не совпадает с id решения ({obj['id']})",
                                "имя файла решения = {id}.json; переименовать"))
            files_with_issues.add(file_id)
        valid.append(obj)
    current: dict[str, dict] = {}
    for d in valid:
        cur = current.get(d["key"])
        if cur is None or (d["recorded_at"], d["id"]) > (cur["recorded_at"], cur["id"]):
            current[d["key"]] = d
    today_iso = today.isoformat()
    for key in sorted(current):
        d = current[key]
        rb = d.get("review_by")
        if rb is not None and rb < today_iso:
            file_id = f"decisions/{d['id']}.json"
            issues.append(issue(LAYER_CARRIERS, file_id, "yellow", "ds_decision_review_overdue",
                                f"срок пересмотра текущего решения по {key} прошёл ({rb})",
                                f"пересмотреть {key}: разбор советника или слово владельца → новое решение",
                                {"key": key, "review_by": rb}))
            files_with_issues.add(file_id)

    # 2. Условия: файл определений conditions@2, состояние conditions-state@1, события без определения.
    conds = pc.get("conditions")
    if conds is not None:
        errs = ds_schemas.validate_conditions_file(conds)
        if errs:
            issues.append(_schema_issue("conditions.yaml", "ds_conditions_invalid",
                                        "определения условий не проходят conditions@2", errs,
                                        "править скриптом apply_condition.py (save-to-library), не вручную"))
            files_with_issues.add("conditions.yaml")
    state = pc.get("conditions_state")
    n_events = 0
    if state is not None:
        errs = ds_schemas.validate_conditions_state(state)
        if errs:
            issues.append(_schema_issue("conditions-state.json", "ds_state_invalid",
                                        "состояние условий не проходит conditions-state@1", errs,
                                        "файл пишет только hub-api; разобраться, кто записал мимо"))
            files_with_issues.add("conditions-state.json")
        if isinstance(state, dict) and isinstance(state.get("events"), list):
            n_events = len(state["events"])
            defs: list = []
            for src in [conds, *(pc.get("conditions_archive") or [])]:
                if isinstance(src, dict) and isinstance(src.get("conditions"), list):
                    defs.extend(src["conditions"])
            for e in ds_schemas.validate_state_refs(state, {"conditions": defs}):
                issues.append(issue(LAYER_CARRIERS, "conditions-state.json", "red", "ds_state_orphan_event",
                                    f"событие без определения: {e}",
                                    "найти условие в архиве определений или в архиве шага; без него событие не читается"))
                files_with_issues.add("conditions-state.json")

    # 3. Справочник бумаг: схема; бумаги снапшота без записи.
    attrs = pc.get("security_attrs")
    n_attrs = 0
    if attrs is not None:
        errs = ds_schemas.validate_security_attrs(attrs)
        if errs:
            issues.append(_schema_issue("security-attrs.json", "ds_security_attrs_invalid",
                                        "справочник бумаг не проходит security-attrs@1", errs,
                                        "править скриптом security_attrs.py (save-to-library), не вручную"))
            files_with_issues.add("security-attrs.json")
        by_key = attrs.get("by_key") if isinstance(attrs, dict) else None
        if isinstance(by_key, dict):
            n_attrs = len(by_key)
            blocked = set(pc.get("blocked_keys") or [])
            for k in sorted(set(pc.get("snapshot_keys") or []) - blocked - set(by_key)):
                issues.append(issue(LAYER_CARRIERS, "security-attrs.json", "yellow", "ds_security_attrs_missing",
                                    f"бумага {k} есть в снапшоте, но нет в справочнике бумаг",
                                    f"save-to-library Workflow Q: security_attrs.py set --key {k} (класс можно null)",
                                    {"key": k}))
                files_with_issues.add("security-attrs.json")

    summary = {
        "carriers_decisions": len(decisions),
        "carriers_decision_keys": len(current),
        "carriers_conditions": len(conds.get("conditions") or []) if isinstance(conds, dict) else 0,
        "carriers_state_events": n_events,
        "carriers_security_attrs": n_attrs,
        "carriers_with_issues": len(files_with_issues),
    }
    return issues, summary


# ---------------------------------------------------------------------------
# Слой 6 — Library layout (структурные проблемы layout'а Claude-Memory)
# ---------------------------------------------------------------------------
#
# Проверки: deprecated-папки `_audits/` / `audits/`, MCP-следы дублей
# (`X (N).ext`, `_sync_log_append-*`), нарушение конвенции имён в `domains/`.

_DUP_MARKER_RE = re.compile(r" \(\d+\)(\.|$)")


def validate_library_layout(payload: dict) -> tuple[list[dict], dict]:
    """Layout-level structural issues, независимые от контента файлов."""
    layout = payload.get("library_layout") or {}
    issues: list[dict] = []

    # 1. Deprecated directories — любой файл здесь = ошибка.
    deprecated = layout.get("deprecated_dirs") or {}
    deprecated_count = 0
    for dir_name in ("_audits", "audits"):
        files = deprecated.get(dir_name) or []
        for basename in files:
            deprecated_count += 1
            issues.append(issue(
                "library_layout", f"{dir_name}/{basename}", "red",
                "deprecated_directory_file",
                f"файл лежит в устаревшей папке `{dir_name}/` (полные ретро-аудиты → `reports/`, сжатые профили → `domains/{{domain}}/`)",
                "перенести в reports/ или domains/, удалить из деприкейтнутой папки",
                {"deprecated_dir": dir_name},
            ))

    # 2. MCP-следы: `X (N).ext`, `_sync_log_append-*`.
    dup_files = layout.get("dup_marker_files") or []
    dup_count = 0
    for entry in dup_files:
        path = entry if isinstance(entry, str) else entry.get("path", "")
        if not path:
            continue
        basename = path.rsplit("/", 1)[-1]
        bad = False
        reason = ""
        if _DUP_MARKER_RE.search(basename):
            bad = True
            reason = "имя содержит `(N)` — след MCP create без edit"
        elif basename.startswith("_sync_log_append"):
            bad = True
            reason = "patch-файл `_sync_log_append-*` — содержимое надо смержить в `_sync_log.md`"
        if bad:
            dup_count += 1
            issues.append(issue(
                "library_layout", path, "red",
                "dup_marker_file",
                reason,
                "смержить с основным файлом и удалить дубликат",
            ))

    # 3. Suffix `-audit.md` в `domains/{domain}/` — устаревшая конвенция.
    domains_files = layout.get("domains") or {}
    suffix_count = 0
    for domain, basenames in domains_files.items():
        for basename in basenames:
            if basename.endswith("-audit.md"):
                suffix_count += 1
                issues.append(issue(
                    "library_layout", f"domains/{domain}/{basename}", "yellow",
                    "profile_audit_suffix",
                    "имя профиля содержит устаревший суффикс `-audit` (правильно: `{source-slug}-{period}.md`)",
                    "переименовать без суффикса `-audit`, проверить ссылки в INDEX.md",
                ))

    summary = {
        "library_layout_deprecated_files": deprecated_count,
        "library_layout_dup_markers": dup_count,
        "library_layout_profile_suffix": suffix_count,
    }
    return issues, summary


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def compute(payload: dict) -> dict:
    today = parse_date(payload.get("today")) or date.today()

    audit_issues, audit_summary = validate_audits_layer(payload)
    fc_issues, fc_summary = validate_forecasts_layer(payload, today)
    sc_issues, sc_summary = validate_scenarios_layer(payload, today)
    wr_issues, wr_summary = validate_weekly_reviews_layer(payload)
    pc_issues, pc_summary = validate_portfolio_carriers_layer(payload, today)
    ll_issues, ll_summary = validate_library_layout(payload)

    issues = audit_issues + fc_issues + sc_issues + wr_issues + pc_issues + ll_issues

    by_level = {"red": [], "yellow": [], "green": []}
    for it in issues:
        by_level.setdefault(it["level"], []).append(it)

    return {
        "today": today.isoformat(),
        "summary": {**audit_summary, **fc_summary, **sc_summary, **wr_summary, **pc_summary, **ll_summary,
                    "total_issues": len(issues),
                    "red": len(by_level["red"]),
                    "yellow": len(by_level["yellow"]),
                    "green": len(by_level["green"])},
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validator for revise-memory-remote (audits, forecasts, scenarios)."
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
