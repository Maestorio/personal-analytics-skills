#!/usr/bin/env python3
"""
migrate_to_conditional.py — Phase 3 migration script.

Мигрирует forecast YAML с legacy geopolitics_translation блоком в новый
conditional_on_scenarios формат согласно migrate_to_conditional.spec.md.

Usage:
    python3 scripts/migrate_to_conditional.py --input forecasts/ru-rates-*.yaml
    python3 scripts/migrate_to_conditional.py --input forecast.yaml \\
        --scenario scenarios/scenario-X.yaml [--dry-run]

Output per run:
    <input>.yaml            — updated in-place (or --output)
    <input>.yaml.pre-migration — backup
    <input>.migration-diff.md  — change log
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

# Import helpers from weighted_consensus
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "skills" / "forecast-confidence-applier" / "scripts"))
from weighted_consensus import parse_central, load_weights_from_scenario

SCENARIO_IDS = ["A", "B", "C", "D"]
DEFAULT_SOURCE_MATRIX = "scenarios/scenario-geopolitics-ru-west-2026-05-04.yaml"


def _normalize_source_matrix_path(scenario_yaml_path: str) -> str:
    """Return relative Claude-Memory path (strips absolute prefix before 'scenarios/')."""
    idx = scenario_yaml_path.find("scenarios/")
    if idx >= 0:
        return scenario_yaml_path[idx:]
    return f"scenarios/{Path(scenario_yaml_path).name}"


# ── Encoding helpers ──────────────────────────────────────────────────────────

def _repair_encoding(raw: bytes) -> tuple[bytes, bool]:
    """Detect and repair mojibake (UTF-8 content stored as latin-1→utf-8 double-encoding)."""
    # Try chardet if available
    try:
        import chardet
        detected = chardet.detect(raw)
        enc = (detected.get("encoding") or "utf-8").lower()
        conf = detected.get("confidence") or 0.0
        if enc not in ("utf-8", "ascii", "utf-8-sig") and conf > 0.7:
            try:
                return raw.decode(enc).encode("utf-8"), True
            except (UnicodeDecodeError, LookupError):
                pass
    except ImportError:
        pass

    # Cyrillic mojibake heuristic: UTF-8 Cyrillic bytes decoded as latin-1, then
    # re-encoded as UTF-8. Characteristic pattern in decoded text: Ð + continuation
    mojibake_pattern = re.compile(r'Ð[¡-¿\x80-\x9f]|Ñ[\x80-\x9f]')
    try:
        decoded = raw.decode("utf-8")
        if mojibake_pattern.search(decoded):
            try:
                repaired = decoded.encode("latin-1").decode("utf-8")
                return repaired.encode("utf-8"), True
            except (UnicodeDecodeError, UnicodeEncodeError):
                pass
    except UnicodeDecodeError:
        pass

    # Non-UTF-8 bytes: try latin-1 decode and re-encode as utf-8
    try:
        raw.decode("utf-8")
        return raw, False
    except UnicodeDecodeError:
        pass
    try:
        text = raw.decode("latin-1")
        return text.encode("utf-8"), True
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass

    return raw, False


def _load_yaml_with_encoding(path: Path) -> tuple[dict, bool]:
    """Load YAML with auto encoding repair. Returns (data, was_repaired)."""
    raw = path.read_bytes()
    cleaned, repaired = _repair_encoding(raw)
    text = cleaned.decode("utf-8", errors="replace")
    return yaml.safe_load(text), repaired


# ── Value parsing ─────────────────────────────────────────────────────────────

def _normalize_scenario_id(s: str) -> str:
    """'Sc-A' → 'A', 'scenario_id: A' → 'A', 'A' → 'A'."""
    s = str(s).strip()
    m = re.match(r'^Sc-([ABCD])$', s, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    if s.upper() in SCENARIO_IDS:
        return s.upper()
    return s


def _parse_scenario_value(s: str) -> tuple[float | None, list[float] | None, str | None]:
    """
    Parse scenario value string. Returns (central, range_or_none, unit_or_none).
    Handles: "10.5%", "10.8–12.6", "10.8–12.6%", "13.5", "~7.5%", "**4.4%**"
    EC2: Unicode range dashes (–, —) and ASCII hyphen.
    EC3: Percent-strings → central + unit.
    """
    s = str(s).strip().replace("**", "").replace("~", "").strip()
    unit: str | None = None

    if "%" in s:
        unit = "%"
        s = s.replace("%", "").strip()
    elif "$" in s:
        unit = "USD"
        s = s.replace("$", "").strip()

    # Bug 6: strip thousands-separator commas ("5,400" → "5400", "5,400–6,000" → "5400–6000")
    s = s.replace(",", "")

    # EC2: range "10.8–12.6" (Unicode en/em dash or ASCII hyphen, not negative number)
    range_m = re.match(r'^([\d.]+)\s*[–—\-]\s*([\d.]+)$', s)
    if range_m:
        lo, hi = float(range_m.group(1)), float(range_m.group(2))
        return (lo + hi) / 2, [lo, hi], unit

    # Single number
    num_m = re.match(r'^([\d.]+)$', s)
    if num_m:
        return float(num_m.group(1)), None, unit

    return None, None, unit


def _make_entry(central: float, range_: list[float] | None) -> dict:
    entry: dict = {"central": central}
    if range_:
        entry["range"] = range_
    return entry


# ── Extraction methods ────────────────────────────────────────────────────────

def _has_scenario_rates(geo_trans: dict) -> bool:
    """True if geopolitics_translation has scenario_rates_YYYY dict keys."""
    for key, val in geo_trans.items():
        if isinstance(val, dict) and re.search(r'\d{4}$', key):
            return True
    return False


def _extract_from_scenario_rates(
    geo_trans: dict, horizons: list[str]
) -> tuple[dict[str, dict], str | None]:
    """
    Linear case: parse scenario_rates_YYYY keys (e.g. ru-rates).
    Keys like scenario_rates_2026 → horizon 2026-12-31.
    """
    # derived_from_marginal: scenario values computed via upstream chain (e.g. CPI+500bp floor)
    # coverage_quality LOW for Sc-A: 0 native sources for the peaceful scenario in current library
    by_scenario: dict[str, dict] = {
        sid: {"values": {}, "provenance": "derived_from_marginal",
              "sources_used": [], "coverage_quality": "LOW" if sid == "A" else "HIGH"}
        for sid in SCENARIO_IDS
    }
    unit: str | None = None

    for key, values_dict in geo_trans.items():
        if not isinstance(values_dict, dict):
            continue
        year_m = re.search(r'(\d{4})$', key)
        if not year_m:
            continue
        hz = f"{year_m.group(1)}-12-31"
        if hz not in horizons:
            continue

        for sc_raw, val_raw in values_dict.items():
            sc_id = _normalize_scenario_id(str(sc_raw))
            if sc_id not in SCENARIO_IDS:
                continue
            central, range_, u = _parse_scenario_value(str(val_raw))
            if central is None:
                continue
            if u:
                unit = u
            by_scenario[sc_id]["values"][hz] = _make_entry(central, range_)

    return by_scenario, unit


def _extract_from_alternatives(
    geo_trans: dict, forecast_data: dict, horizons: list[str]
) -> tuple[dict[str, dict], str | None]:
    """
    Nonlinear case: parse alternatives list (e.g. cny-rub).
    EC1: Sc-D may be absent from alternatives → extract from forecast.central_estimate.
    """
    by_scenario: dict[str, dict] = {
        sid: {"values": {}, "provenance": "derived_from_marginal",
              "sources_used": [], "coverage_quality": "LOW" if sid == "A" else "MEDIUM"}
        for sid in SCENARIO_IDS
    }
    unit: str | None = None
    seen: set[str] = set()

    for alt in geo_trans.get("alternatives", []):
        sc_id = _normalize_scenario_id(str(alt.get("scenario_id", "")))
        if sc_id not in SCENARIO_IDS:
            continue
        seen.add(sc_id)
        for k, v in alt.items():
            year_m = re.search(r'(\d{4})$', k)
            if not year_m:
                continue
            hz = f"{year_m.group(1)}-12-31"
            if hz not in horizons:
                continue
            central, range_, u = _parse_scenario_value(str(v))
            if central is None:
                continue
            if u:
                unit = u
            by_scenario[sc_id]["values"][hz] = _make_entry(central, range_)

    # EC1: if D missing from alternatives, extract from forecast.central_estimate
    if "D" not in seen:
        central_str = str(forecast_data.get("forecast", {}).get("central_estimate", ""))
        for hz in horizons:
            year = hz[:4]
            m = re.search(rf'([\d.]+[–—\-][\d.]+|[\d.]+)\s*к\s*{year}', central_str)
            if m:
                central, range_, u = _parse_scenario_value(m.group(1))
                if central is not None:
                    if u:
                        unit = u
                    by_scenario["D"]["values"][hz] = _make_entry(central, range_)
                    by_scenario["D"]["provenance"] = "derived_from_marginal"
                    by_scenario["D"]["coverage_quality"] = "MEDIUM"

    return by_scenario, unit


def _extract_from_markdown(
    md_path: Path, horizons: list[str]
) -> tuple[dict[str, dict], str | None]:
    """
    Markdown-only case: parse geopolitics table from sibling .md (e.g. ru-cpi).
    Looks for rows with **A/B/C/D** label + bold numeric value in 5th column.
    """
    # Bug 3: MEDIUM for B/C/D, LOW for A (Sc-A has 0 native sources in peaceful scenario)
    by_scenario: dict[str, dict] = {
        sid: {"values": {}, "provenance": "derived_from_marginal",
              "sources_used": [], "coverage_quality": "LOW" if sid == "A" else "MEDIUM"}
        for sid in SCENARIO_IDS
    }
    unit: str | None = None

    if not md_path or not md_path.exists():
        return by_scenario, unit

    md_text = md_path.read_text(encoding="utf-8", errors="replace")
    first_hz = horizons[0] if horizons else "2026-12-31"

    for line in md_text.splitlines():
        # Match table data rows: | **A ... | ... | **value%** |
        m_id = re.search(r'\|\s*\*\*([ABCD])\s', line)
        if not m_id:
            continue
        sc_id = m_id.group(1)

        # Find bold numeric values in the row (skip the label which is non-numeric)
        bold_numbers = re.findall(r'\*\*([\d.]+%?)\*\*', line)
        if not bold_numbers:
            continue

        # First bold numeric value in data columns is the forecast value
        central, range_, u = _parse_scenario_value(bold_numbers[0])
        if central is None:
            continue
        if u:
            unit = u
        # Bug 2: keep provenance=derived_from_marginal; do NOT override to native_fca
        by_scenario[sc_id]["values"][first_hz] = _make_entry(central, range_)

    return by_scenario, unit


def _build_indifferent_scenario(
    forecast: dict, horizons: list[str]
) -> tuple[dict[str, dict], str | None]:
    """EC5: No geopolitics_translation — all 4 scenarios equal to Layer 1 value."""
    layer1 = _extract_layer1_value(forecast, horizons)
    by_scenario: dict[str, dict] = {}
    for sid in SCENARIO_IDS:
        values = {hz: {"central": layer1 if layer1 is not None else 0.0} for hz in horizons}
        by_scenario[sid] = {
            "values": values,
            "provenance": "derived_from_marginal",
            "sources_used": [],
            "coverage_quality": "DERIVED",
        }
    return by_scenario, "%"


# ── Layer 1 extraction ────────────────────────────────────────────────────────

def _extract_layer1_value_for_horizon(forecast: dict, horizon: str) -> float | None:
    """Extract Layer 1 value for a specific horizon year from central_estimate."""
    ce_str = re.sub(r'(?<=\d),(?=\d)', '', str(forecast.get("central_estimate", "")))
    year = horizon[:4]
    m = re.search(rf'([\d.]+[–—\-][\d.]+|[\d.]+)%?\s*(?:к\s*)?{year}', ce_str)
    if m:
        c, _, _ = _parse_scenario_value(m.group(1))
        return c
    return None


def _extract_layer1_value(forecast: dict, horizons: list[str]) -> float | None:
    """Extract numeric Layer 1 value from forecast.central_estimate (first horizon)."""
    ce = forecast.get("central_estimate", "")

    # Direct numeric or simple parse
    result = parse_central(ce)
    if result is not None:
        return result

    ce_str = re.sub(r'(?<=\d),(?=\d)', '', str(ce))  # strip thousands-separator commas

    # First horizon year: find value near "к YYYY"
    if horizons:
        year = horizons[0][:4]
        m = re.search(rf'([\d.]+[–—\-][\d.]+|[\d.]+)%?\s*(?:к\s*)?{year}', ce_str)
        if m:
            c, _, _ = _parse_scenario_value(m.group(1))
            if c is not None:
                return c

    # "weighted median X%"
    m = re.search(r'weighted\s+median\s+([\d.]+)%?', ce_str, re.IGNORECASE)
    if m:
        return float(m.group(1))

    # First range X–Y
    m = re.search(r'([\d.]+)\s*[–—\-]\s*([\d.]+)', ce_str)
    if m:
        return (float(m.group(1)) + float(m.group(2))) / 2

    # First percentage X%
    m = re.search(r'([\d.]+)%', ce_str)
    if m:
        return float(m.group(1))

    return None


# ── Parse horizons ────────────────────────────────────────────────────────────

def _parse_horizons(forecast_data: dict) -> list[str]:
    f = forecast_data.get("forecast", {})
    horizons = f.get("horizons", [])
    if horizons:
        return [str(h) for h in horizons]
    h = f.get("horizon")
    return [str(h)] if h else []


# ── Core migration ────────────────────────────────────────────────────────────

class MigrationResult:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.warnings: list[str] = []
        self.output_data: dict | None = None

    def info(self, msg: str) -> None:
        self.log.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        self.log.append(f"WARNING: {msg}")


def migrate_forecast(
    forecast_data: dict,
    scenario_yaml_path: str,
    md_path: Path | None = None,
    isolated: bool = False,
    isolated_reason: str | None = None,
) -> tuple[dict, MigrationResult]:
    """
    Core migration logic (no file I/O). Returns (updated_data, result).
    Replaces geopolitics_translation → conditional_on_scenarios + coherence_diagnostic.

    Args:
        isolated: if True — Type 1 (isolated) per events-yaml-spec.md §5.5;
            не создаёт conditional_on_scenarios, добавляет isolated: true.
        isolated_reason: free text reason; default — auto-generated.
    """
    result = MigrationResult()
    data = {k: v for k, v in forecast_data.items()}  # shallow copy

    forecast = data.get("forecast", {})
    # Bug 5: geopolitics_translation may be nested under forecast OR at top level
    geo_trans = forecast.get("geopolitics_translation") or data.get("geopolitics_translation")

    # EC5a — Type 1 (isolated). Триггер — флаг isolated=True.
    if isolated:
        # Удалить legacy geopolitics_translation если есть.
        if "geopolitics_translation" in data.get("forecast", {}):
            del data["forecast"]["geopolitics_translation"]
            result.info("REMOVED: forecast.geopolitics_translation (Type 1 isolated)")
        elif "geopolitics_translation" in data:
            del data["geopolitics_translation"]
            result.info("REMOVED: geopolitics_translation top-level (Type 1 isolated)")
        data["isolated"] = True
        data["isolated_reason"] = isolated_reason or (
            "auto: no scenario translation block found (Type 1 per events-yaml-spec.md §5.5)"
        )
        # Не создаём conditional_on_scenarios / coherence_diagnostic.
        result.info("EC5a: Type 1 isolated — no conditional_on_scenarios block")
        result.output_data = data
        return data, result

    method = (geo_trans.get("method", "linear") if geo_trans else "indifferent")
    horizons = _parse_horizons(data)
    if not horizons:
        horizons = ["2026-12-31"]

    # --- Choose extraction path ---
    if geo_trans is None:
        by_scenario, unit = _build_indifferent_scenario(forecast, horizons)
        result.info("EC5: no geopolitics_translation → indifferent method")
    elif method == "nonlinear" and geo_trans.get("alternatives"):
        by_scenario, unit = _extract_from_alternatives(geo_trans, data, horizons)
        result.info("METHOD: nonlinear with alternatives list")
        # Check for EC1
        if "D" not in {k for k in by_scenario if by_scenario[k]["values"]}:
            result.info("EC1: Sc-D absent from alternatives, extracted from central_estimate")
    elif (method in ("linear", "indifferent")
          and geo_trans.get("distribution_used")
          and not _has_scenario_rates(geo_trans)):
        # Markdown-only case (ru-cpi pattern)
        if md_path and md_path.exists():
            by_scenario, unit = _extract_from_markdown(md_path, horizons)
            result.info("METHOD: markdown table parsing (distribution_used=true, no YAML values)")
        else:
            by_scenario, unit = _build_indifferent_scenario(forecast, horizons)
            result.warn("distribution_used=true but no scenario YAML values and no .md file; derived")
    else:
        by_scenario, unit = _extract_from_scenario_rates(geo_trans, horizons)
        result.info(f"METHOD: scenario_rates extraction (method={method})")

    if not unit:
        unit = "%"

    # Bug 4: fill missing horizons with Layer 1 derived value
    for hz in horizons:
        missing = [sid for sid in SCENARIO_IDS
                   if hz not in by_scenario.get(sid, {}).get("values", {})]
        if missing:
            layer1_hz = _extract_layer1_value_for_horizon(forecast, hz)
            if layer1_hz is not None:
                for sid in missing:
                    by_scenario[sid]["values"][hz] = {
                        "central": layer1_hz,
                        "provenance_note": "per-scenario breakdown unavailable for this horizon",
                    }

    # --- Load scenario weights ---
    weights: dict[str, float]
    try:
        weights = load_weights_from_scenario(scenario_yaml_path)
        if len(weights) < 4:
            raise ValueError(f"only {len(weights)} scenarios loaded")
    except Exception as exc:
        weights = {"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25}
        result.warn(f"Scenario weights not loaded ({exc}); using equal 0.25")

    # --- Modal scenario ID ---
    max_w = max(weights.values())
    modal_id = max(weights, key=weights.get) if max_w > 0.30 else "none"

    # --- Compute Layer 2 marginals (inline to avoid reference aliasing) ---
    marginal_values: dict[str, dict] = {}
    total_w = sum(weights.values()) or 1.0
    for hz in horizons:
        complete = all(hz in by_scenario.get(sid, {}).get("values", {}) for sid in SCENARIO_IDS)
        if not complete:
            continue
        try:
            wmean = sum(
                weights.get(sid, 0.0) * by_scenario[sid]["values"][hz]["central"]
                for sid in SCENARIO_IDS
            ) / total_w
            entry: dict = {"central": round(wmean, 6)}
            all_lows = [
                by_scenario[sid]["values"][hz]["range"][0]
                for sid in SCENARIO_IDS
                if "range" in by_scenario[sid]["values"][hz]
            ]
            all_highs = [
                by_scenario[sid]["values"][hz]["range"][1]
                for sid in SCENARIO_IDS
                if "range" in by_scenario[sid]["values"][hz]
            ]
            if all_lows and all_highs:
                entry["range"] = [float(min(all_lows)), float(max(all_highs))]
            marginal_values[hz] = entry
        except Exception as exc:
            result.warn(f"marginal computation failed for {hz}: {exc}")

    # --- Build conditional_on_scenarios block ---
    # Migration всегда применяет weighted_mean (linear aggregation) для marginal.
    # axis_dependent: семантически монотонно зависит от одной оси, индифферентен к другой.
    # Сценарии с одинаковым состоянием доминантной оси имеют равное значение фактора, поэтому
    # probability-weighted mean математически эквивалентен коллапсу вдоль доминантной оси.
    # Метод хранится как диагностический тег; aggregation_formula = weighted_mean.
    is_axis_dep = method == "axis_dependent"
    marginal_block: dict = {
        "method": "axis_dependent" if is_axis_dep else "linear",
        "modal_scenario_id": modal_id,
        "values": marginal_values,
        "aggregation_formula": "weighted_mean",
    }
    if is_axis_dep:
        result.info("EC5c: axis_dependent resolved via weighted_mean along dominant axis")

    conditional = {
        "source_matrix": _normalize_source_matrix_path(scenario_yaml_path),
        "scenario_id_format": "short",
        "by_scenario": by_scenario,
        "marginal": marginal_block,
        "unit": unit,
    }

    # --- Coherence diagnostic ---
    layer1 = _extract_layer1_value(forecast, horizons)
    layer2_central = marginal_values.get(horizons[0], {}).get("central")

    if layer1 is not None and layer2_central is not None and layer1 != 0:
        div_pct = round(abs(layer1 - layer2_central) / abs(layer1) * 100, 2)
        if div_pct < 5:
            severity = "LOW"
        elif div_pct < 15:
            severity = "MEDIUM"
        else:
            severity = "HIGH"
        warn_text = None
        if severity != "LOW":
            warn_text = (
                f"Layer 1 ({layer1:.2f}) vs Layer 2 ({layer2_central:.2f}) "
                f"divergence {div_pct:.1f}%"
            )
            if severity == "HIGH":
                result.warn(f"MANUAL REVIEW REQUIRED: {warn_text}")
        coherence = {
            "layer1_marginal": layer1,
            "layer2_marginal": round(layer2_central, 6),
            "divergence_pct": div_pct,
            "severity": severity,
            "warning": warn_text,
        }
    else:
        coherence = {
            "layer1_marginal": layer1,
            "layer2_marginal": layer2_central,
            "divergence_pct": None,
            "severity": "UNKNOWN",
            "warning": "Could not compute divergence (layer1 or layer2 is None)",
        }

    # --- Remove legacy block, add new blocks ---
    if "geopolitics_translation" in data.get("forecast", {}):
        del data["forecast"]["geopolitics_translation"]
        result.info("REMOVED: forecast.geopolitics_translation")
    elif "geopolitics_translation" in data:
        del data["geopolitics_translation"]
        result.info("REMOVED: geopolitics_translation (top-level)")

    data["conditional_on_scenarios"] = conditional
    data["coherence_diagnostic"] = coherence

    result.output_data = data
    return data, result


# ── File-level migration ──────────────────────────────────────────────────────

def migrate_file(
    input_path: Path,
    scenario_yaml_path: str = DEFAULT_SOURCE_MATRIX,
    output_path: Path | None = None,
    dry_run: bool = False,
    no_backup: bool = False,
    isolated: bool = False,
    isolated_reason: str | None = None,
) -> MigrationResult:
    """
    Migrate a forecast YAML file, creating backup and diff log.
    Returns MigrationResult with log entries.
    """
    result = MigrationResult()

    # 1. Load (with encoding repair)
    data, encoding_repaired = _load_yaml_with_encoding(input_path)
    if encoding_repaired:
        result.info("ENCODING REPAIR: non-UTF-8 content repaired")

    # 2. Discover sibling .md
    md_path = input_path.with_suffix(".md")
    if not md_path.exists():
        md_path = None  # type: ignore[assignment]

    # 3. Run migration
    updated_data, migration_result = migrate_forecast(
        data,
        scenario_yaml_path=scenario_yaml_path,
        md_path=md_path,
        isolated=isolated,
        isolated_reason=isolated_reason,
    )
    result.log.extend(migration_result.log)
    result.warnings.extend(migration_result.warnings)
    result.output_data = updated_data

    if dry_run:
        result.info("DRY RUN: no files written")
        return result

    # 4. Backup
    if not no_backup:
        import shutil
        backup_path = Path(str(input_path) + ".pre-migration")
        shutil.copy2(input_path, backup_path)
        result.info(f"BACKUP: {backup_path.name}")

    # 5. Atomic write
    out_path = output_path or input_path
    yaml_str = yaml.dump(
        updated_data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=120,
    )
    fd, tmp_name = tempfile.mkstemp(dir=out_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(yaml_str)
        os.replace(tmp_name, out_path)
    except Exception:
        os.unlink(tmp_name)
        raise
    result.info(f"WRITTEN: {out_path.name}")

    # 6. Diff log
    diff_path = input_path.parent / (input_path.stem + ".migration-diff.md")
    lines = [f"# Migration: {input_path.name}\n\n"]
    for entry in result.log:
        lines.append(f"- {entry}\n")
    if result.warnings:
        lines.append("\n## Warnings\n\n")
        for w in result.warnings:
            lines.append(f"- {w}\n")
    diff_path.write_text("".join(lines), encoding="utf-8")

    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate forecast YAML to conditional_on_scenarios format (Phase 3)"
    )
    parser.add_argument("--input", required=True, help="Input forecast YAML")
    parser.add_argument("--scenario", default=DEFAULT_SOURCE_MATRIX,
                        help="Scenario YAML path (source_matrix SSOT)")
    parser.add_argument("--output", help="Output path (default: in-place)")
    parser.add_argument("--dry-run", action="store_true", help="No file writes")
    parser.add_argument("--no-backup", action="store_true", help="Skip .pre-migration backup")
    parser.add_argument(
        "--isolated", action="store_true",
        help="Type 1 (isolated) per events-yaml-spec.md §5.5: write isolated: true, "
             "не создавать conditional_on_scenarios."
    )
    parser.add_argument(
        "--isolated-reason", default=None,
        help="Reason для isolated: true (опционально; default — auto-generated)."
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {input_path} not found", file=sys.stderr)
        sys.exit(1)

    result = migrate_file(
        input_path=input_path,
        scenario_yaml_path=args.scenario,
        output_path=Path(args.output) if args.output else None,
        dry_run=args.dry_run,
        no_backup=args.no_backup,
        isolated=args.isolated,
        isolated_reason=args.isolated_reason,
    )

    for entry in result.log:
        print(entry)
    if result.warnings:
        print("\nWarnings:", file=sys.stderr)
        for w in result.warnings:
            print(f"  {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
