#!/usr/bin/env python3
"""
stress_build.py — одна команда вместо ручной цепочки скилла
(build_stress_stub → compute_horizon_factors → compute_per_position → compute_bond_carry →
compute_portfolio_aggregates → assemble_stress).

Из входов, которые пишет модель (суждения), собирает дерево суждений stress-judgments@1 и считает
полный стресс-файл функцией stress_recalc.recalc — тем же кодом, которым числа пересчитывает сайт.
Новых формул нет.

CLI:
  stress_build.py --snapshot portfolio-DATE.json --scenarios МАТРИЦА.yaml [--macro-scenarios macro-scenarios-DATE.yaml]
      (--priors betas-priors.json | --priors-from ПРОШЛЫЙ_СТРЕСС.yaml | оба)
      [--horizon-factors-input IN.json | --horizon-factors HF.json]
      [--political-from ПРОШЛЫЙ_СТРЕСС.yaml | --political-paths ПУТИ.json]
      [--fill fill.yaml] [--carry-overrides bond-overrides.json] [--<параметр купонного слоя> X ...]
      [--weights-json ВЕСА.json | --library-root КОРЕНЬ_БИБЛИОТЕКИ]
      [--include-ev] [--weight-type equal|probability] [--slug ...] [--horizons 6,12,24 | --anchor-dates ...] [--primary-horizon N]
      [--today YYYY-MM-DD] --output OUT.yaml [--tables ТАБЛИЦЫ.md] [--json]

Входы:
  --priors                JSON {тикер: {factor_betas, factor_betas_method, factor_betas_r2,
                          sanctions_position?, asset_type?, sector_group?}}. Чувствительность обязана быть
                          у каждой бумаги снапшота (денежные фонды скрипт добавляет сам). Вместе с --priors-from
                          даёт только новые бумаги и сознательно пересмотренные: запись заменяет перенесённую целиком.
  --priors-from           прошлый полный стресс-файл: чувствительности бумаг, которые есть в снапшоте, переносятся
                          как есть (метод получает префикс «reused from <файл> | »). Нужен хотя бы один из двух флагов.
  Приоритет источников: references/fixed-priors.yaml (решение владельца) > --priors > перенос из --priors-from.
  sanctions_position бумаг из references/sanctions-positions.yaml берётся оттуда, какое бы значение ни пришло.
  --horizon-factors-input вход compute_horizon_factors (as_of, horizons, horizon_ends, baseline_spot
                          подставляются из стаба, если не заданы); --horizon-factors — его готовый выход.
                          Не больше одного из двух. Ни одного — допустимо только вместе с --macro-scenarios:
                          числовые факторы (brent, usdrub, cnyrub, cbr_rate, xauusd) считаются по сетке дат
                          макро-файла (as_of — дата прогона, сроки — сроки прогона): линейная интерполяция
                          уровня между точками сетки; срок позже сетки — flat hold с CI ×sqrt(дней до срока /
                          дней до последней точки); срок раньше сетки — интерполяция от спота. Весь макро-файл
                          сначала проверяется одним списком (compute_horizon_factors.validate_macro).
  --political-from / --political-paths
                          в режиме «из макро-файла» обязателен ровно один: sanctions и geopol берутся как есть
                          из scenarios.<X>.factors_by_horizon.<hNN> прошлого стресс-файла (сценарии и метки сроков
                          должны совпасть с прогоном) либо из JSON {"A": {"sanctions": {"h6": 0.5, ...},
                          "geopol": {...}}, ...} (все сценарии, оба фактора, все сроки; числа в [-1, 1]).
                          Источники числовых и политических факторов указываются в сводке.
  --fill                  ТОЛЬКО поля суждения (macro_blindspots, caveats, dominant_factor,
                          concentration.{dominant_factor, note}, robustness.{hedge_target, modal_scenario},
                          hedge_candidates, *_note, method, notes, scenario_matrix_ref, forecast_type,
                          scenario_source, weight_type, modal_flag). Посчитанное в fill — отказ.
                          Без --fill — режим «только числа»: файл с numbers_only: true, слоты суждения
                          занимает метка-заглушка, валидатор не запускается, концентрация без фактора
                          не считается.
  Сроки: с --library-root и валидным <корень>/scenarios/horizons.json (horizons@1) сроки прогона — метки, даты,
  основной срок — берутся из него (режим anchored, автосдвига нет; до ближайшего срока меньше 3 мес. —
  предупреждение). Другие --horizons / --anchor-dates / --primary-horizon — отказ. С --horizons-from файл тоже
  главнее; расхождение с прошлым стрессом — предупреждение. Невалидный файл — как будто его нет + предупреждение.
  Веса: --weights-json (stress-weights@1) или <--library-root>/scenarios/stress-weights-<матрица>.json
  (имя матрицы — по имени --scenarios, правило stress_job.matrix_name). Не подошли по срокам или не
  читаются — предупреждение и веса матрицы (так же ведёт себя сайт); файла нет — веса матрицы.

Режим регрессии OLS-бет не поддерживается — только priors (как у recalc).
Коды: 0 — ок; 1 — отказ; 2 — ошибка вызова.
"""
from __future__ import annotations

import argparse
import calendar
import copy
import json
import re
import sys
from datetime import date as date_t
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import assemble_stress as asm  # noqa: E402
import build_stress_stub as bss  # noqa: E402
import compute_bond_carry as cbc  # noqa: E402
import compute_derived_fields as cdf  # noqa: E402
import compute_horizon_factors as chf  # noqa: E402
import stress_judgments as sj  # noqa: E402
import stress_recalc as sr  # noqa: E402
import stress_tables as stt  # noqa: E402
from input_contract import CANONICAL_FACTORS, compute_positions_value_rub  # noqa: E402

REFERENCES = SCRIPTS.parent / "references"
FIXED_PRIORS_FILE = "fixed-priors.yaml"
POSITIONS_FILE = "sanctions-positions.yaml"
FIXED_REQUIRED = ("factor_betas", "factor_betas_method", "asset_type", "sector_group")
FIXED_ALLOWED = FIXED_REQUIRED + ("note",)
_REUSED_RE = re.compile(r"^reused from .*? \| ")

MARK = "ЗАПОЛНИТЬ_В_FILL"  # заглушка слота суждения в режиме «только числа» (не TODO_LLM: расчёт не падает)
# Значения стаба, которые вправе задать модель (идут в meta).
MODEL_META = ("scenario_source", "weight_type", "modal_flag", "scenario_matrix_ref", "forecast_type")
# Посчитанные поля: в fill их задавать нельзя.
DERIVED_KEYS = ("cash_rub_pct", "blocked_pct", "blocked_rub_memo", "weight_base_note", "sector_breakdown_pct",
                "sector_breakdown_basis", "top_risks", "top_resilient", "concentration_ratio", "portfolio_summary")
FORBIDDEN_FILL = (set(sj.FORBIDDEN_KEYS) | set(sj.NOT_JUDGMENT_TOP) | set(DERIVED_KEYS) | set(sj.META_KEYS)
                  | {"_drop", "include_ev", "priors", "carry"}) - set(MODEL_META) - {"robustness"}
FILL_ROBUSTNESS = ("hedge_target", "modal_scenario")
_NAME_RE = re.compile(r"^[a-z0-9-]+$")  # как stress_job._NAME_RE


class BuildError(Exception):
    pass


matrix_name = sr.matrix_name  # как stress_job.matrix_name: без папки и расширения .yaml/.yml/.md


def weights_rel(matrix: str) -> str:
    return f"scenarios/stress-weights-{matrix}.json"


def check_fill(fill: Any) -> None:
    """Отказ, если fill несёт посчитанное или плейсхолдер."""
    if not isinstance(fill, dict):
        raise BuildError("--fill: ожидался словарь верхнего уровня")
    bad = sorted(k for k in fill if k in FORBIDDEN_FILL)
    rob = fill.get("robustness")
    if rob is not None:
        if not isinstance(rob, dict):
            bad.append("robustness (не словарь)")
        else:
            bad += [f"robustness.{k}" for k in rob if k not in FILL_ROBUSTNESS]
    conc = fill.get("concentration")
    if conc is not None:
        if not isinstance(conc, dict):
            bad.append("concentration (не словарь)")
        else:
            bad += [f"concentration.{k}" for k in conc if k in sr.CONC_DERIVED_KEYS]
    if bad:
        raise BuildError("fill трогает посчитанное или недопустимое (fill несёт только поля суждения):\n  "
                         + "\n  ".join(bad))
    left = asm.find_ph(fill)
    if left:
        raise BuildError(f"в fill остался {asm.PLACEHOLDER}: {', '.join(left[:15])}")


def _load(path: Path, label: str) -> Any:
    try:
        return asm.load_doc(path, label)
    except asm.AssembleError as e:
        raise BuildError(str(e))


def resolve_weights(j: dict, weights_path: Path | None, library_root: Path | None,
                    scenarios_path: Path, warnings: list[str]) -> tuple[dict | None, str | None]:
    """(файл весов | None, его имя). Не подошёл — предупреждение и None (веса матрицы)."""
    path = weights_path
    if path is None and library_root is not None:
        m = matrix_name(str(scenarios_path))
        if m:
            cand = library_root / weights_rel(m)
            path = cand if cand.is_file() else None
    if path is None:
        if (j.get("meta") or {}).get("weight_type") == "probability":
            warnings.append("веса на сайте не заданы — взяты веса матрицы сценариев по меткам сроков; они задавались "
                            "на даты матрицы, а не на сроки стресса. Задайте веса на странице «Стресс» → «Веса сценариев»")
        return None, None
    try:
        w = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(w, dict):
            raise ValueError("ожидался объект")
        sr.check_weights_file(w, j)
    except (OSError, ValueError) as e:
        warnings.append(f"веса сайта не читаются ({path.name}: {e}) — посчитано на весах матрицы")
        return None, None
    except sr.RecalcError as e:
        if "горизонты стресса изменились" in str(e):
            warnings.append("веса сайта заданы на другие сроки — посчитано на весах матрицы")
        else:
            warnings.append(f"веса сайта не подошли ({e}) — посчитано на весах матрицы")
        return None, None
    return w, path.name


def _plus_months(iso: str, months: int) -> str:
    """Та же дата через N месяцев (день обрезается по длине месяца)."""
    d = date_t.fromisoformat(iso)
    idx = d.year * 12 + d.month - 1 + months
    y, m = idx // 12, idx % 12 + 1
    return date_t(y, m, min(d.day, calendar.monthrange(y, m)[1])).isoformat()


def horizons_from(path: Path) -> tuple[list[int], dict, str | None, int]:
    """Сроки прошлого стресса как есть: метки hNN и даты не пересчитываются. Режим — anchored:
    даты фиксированы, метка — конвенция (сдвиг — shift_horizons)."""
    prev = _load(path, "--horizons-from")
    he = prev.get("horizon_ends") if isinstance(prev, dict) else None
    if not isinstance(he, dict) or not he or not all(re.fullmatch(r"h\d+", str(k)) for k in he):
        raise BuildError(f"--horizons-from: в {path.name} нет horizon_ends с ключами hNN")
    horizons = sorted(int(str(k)[1:]) for k in he)
    ends = {f"h{h}": str(he[f"h{h}"])[:10] for h in horizons}
    primary = prev.get("primary_horizon")
    if primary not in horizons:
        raise BuildError(f"--horizons-from: primary_horizon {primary!r} не из {horizons}")
    return horizons, ends, "anchored", primary


HORIZONS_FILE = "scenarios/horizons.json"
HORIZONS_SCHEMA = "horizons@1"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SITE_HINT = "сдвинуть их можно там: «Стресс» → «Настройки стресса»"


def horizons_file_errors(doc: Any) -> list[str]:
    """Причины, по которым файл сроков horizons@1 невалиден (пусто — валиден). Правила те же, что у сайта."""
    if not isinstance(doc, dict):
        return ["ожидался объект"]
    errs = []
    if doc.get("schema") != HORIZONS_SCHEMA:
        errs.append(f"schema {doc.get('schema')!r}, нужен {HORIZONS_SCHEMA!r}")
    he = doc.get("horizon_ends")
    if not isinstance(he, dict) or not 1 <= len(he) <= 6:
        errs.append("horizon_ends: нужен объект из 1–6 сроков")
        return errs
    nums = []
    for k, v in he.items():
        m = re.fullmatch(r"h(\d+)", str(k))
        if not m or int(m.group(1)) <= 0:
            errs.append(f"horizon_ends: ключ {k!r} не вида hN (N — целое больше 0)")
            continue
        try:
            if not (isinstance(v, str) and _DATE_RE.match(v)):
                raise ValueError
            date_t.fromisoformat(v)
        except ValueError:
            errs.append(f"horizon_ends.{k}: {v!r} не дата ГГГГ-ММ-ДД")
            continue
        nums.append((int(m.group(1)), v, k))
    nums.sort()
    for a, b in zip(nums, nums[1:]):
        if not b[1] > a[1]:
            errs.append(f"horizon_ends: дата {b[2]} ({b[1]}) не позже {a[2]} ({a[1]})")
    ph = doc.get("primary_horizon")
    if isinstance(ph, bool) or not isinstance(ph, int) or f"h{ph}" not in he:
        errs.append(f"primary_horizon {ph!r}: нужен номер одного из сроков")
    return errs


def read_site_terms(library_root: Path | None) -> tuple[dict | None, str | None]:
    """(файл сроков сайта | None, предупреждение). Нет файла — (None, None); невалидный — (None, причина)."""
    if library_root is None:
        return None, None
    path = library_root / HORIZONS_FILE
    if not path.is_file():
        return None, None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"файл сроков сайта не читается ({HORIZONS_FILE}: {e}) — сроки не из него"
    errs = horizons_file_errors(doc)
    if errs:
        return None, f"файл сроков сайта невалиден ({HORIZONS_FILE}: {'; '.join(errs)}) — сроки не из него"
    return doc, None


def _terms_text(ends: dict) -> str:
    return ", ".join(f"{k} {v}" for k, v in ends.items())


def _ddmm(iso: Any) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(iso or ""))
    return f"{m.group(3)}.{m.group(2)}" if m else str(iso or "?")


SHIFT_WHEN_MONTHS_LEFT = 3   # до ближайшего срока осталось меньше — сроки сдвигаются
SHIFT_BY_MONTHS = 6          # на сколько сдвигаются все сроки разом


def shift_horizons(ends: dict, today: str) -> tuple[dict, int]:
    """Сроки прошлого стресса держатся, пока до ближайшего не меньше SHIFT_WHEN_MONTHS_LEFT месяцев;
    иначе все сроки разом уходят на SHIFT_BY_MONTHS месяцев вперёд (конец месяца), метки hNN прежние.
    -> (сроки, сколько раз сдвинуто)."""
    out, n = dict(ends), 0
    while today > _plus_months(min(out.values()), -SHIFT_WHEN_MONTHS_LEFT):
        out = {hk: bss.add_months_eom(date_t.fromisoformat(d), SHIFT_BY_MONTHS).isoformat() for hk, d in out.items()}
        n += 1
        if n > 40:
            raise BuildError("--horizons-from: сроки прошлого файла слишком далеко в прошлом — задай новые (--horizons / --anchor-dates)")
    return out, n


def check_same_matrix(scenarios_path: Path, *, macro_yaml: Any = None, macro_name: str | None = None,
                      political_prev: Any = None, political_prev_name: str | None = None) -> None:
    """Суждения, привязанные к матрице, не переносятся на другую матрицу: при смене осей те же id сценариев
    значат другое, а числа остаются правдоподобными. Ссылки нет в файле — проверка молчит."""
    cur = matrix_name(str(scenarios_path))
    if not cur:
        return
    errs = []
    msg = sr.macro_matrix_mismatch(cur, macro_yaml, macro_name)
    if msg:
        errs.append(msg)
    ref = political_prev.get("scenario_matrix_ref") if isinstance(political_prev, dict) else None
    if isinstance(ref, str) and matrix_name(ref) not in (None, cur):
        errs.append(f"--political-from {political_prev_name or '?'}: пути sanctions/geopol заданы для матрицы {matrix_name(ref)}, "
                    f"а прогон — на {cur}: задай их заново по новой матрице файлом --political-paths")
    if errs:
        raise BuildError("матрица сценариев сменилась:\n  " + "\n  ".join(errs))


def political_from_stress(prev: Any, sids: list[str], hks: list[str], name: str) -> dict:
    """sanctions/geopol прошлого стресс-файла как есть; сценарии и метки сроков обязаны совпасть."""
    sc = prev.get("scenarios") if isinstance(prev, dict) else None
    if not isinstance(sc, dict):
        raise BuildError(f"--political-from: в {name} нет scenarios")
    errs: list[str] = []
    if sorted(sc) != sids:
        errs.append(f"сценарии {sorted(sc)} не совпадают со сценариями прогона {sids}")
    out: dict = {}
    for sid in sids:
        fbh = (sc.get(sid) or {}).get("factors_by_horizon") if isinstance(sc.get(sid), dict) else None
        if not isinstance(fbh, dict):
            if sid in sc:
                errs.append(f"{sid}: нет factors_by_horizon")
            continue
        if sorted(fbh) != sorted(hks):
            errs.append(f"{sid}: сроки {sorted(fbh)} не совпадают со сроками прогона {sorted(hks)}")
            continue
        out[sid] = {}
        for hk in hks:
            cell = fbh[hk] if isinstance(fbh[hk], dict) else {}
            out[sid][hk] = {}
            for f in chf.POLITICAL_FACTORS:
                v = cell.get(f)
                if not chf._is_number(v):
                    errs.append(f"{sid}.{hk}.{f}: нет числа в {name}")
                else:
                    out[sid][hk][f] = v
    if errs:
        raise BuildError(f"--political-from ({name}):\n  " + "\n  ".join(errs))
    return out


def political_from_paths(doc: Any, sids: list[str], hks: list[str], name: str) -> dict:
    """sanctions/geopol из JSON: все сценарии, оба фактора, все сроки; числа в [-1, 1]."""
    if not isinstance(doc, dict):
        raise BuildError(f"--political-paths ({name}): ожидался словарь {{сценарий: {{фактор: {{hNN: число}}}}}}")
    errs = [f"лишний сценарий {k}" for k in sorted(set(doc) - set(sids))]
    out: dict = {}
    for sid in sids:
        node = doc.get(sid)
        if not isinstance(node, dict):
            errs.append(f"{sid}: нет сценария в файле")
            continue
        out[sid] = {hk: {} for hk in hks}
        for f in chf.POLITICAL_FACTORS:
            path = node.get(f)
            if not isinstance(path, dict):
                errs.append(f"{sid}.{f}: нет пути по срокам")
                continue
            errs += [f"{sid}.{f}: лишний срок {k}" for k in sorted(set(path) - set(hks))]
            for hk in hks:
                v = path.get(hk)
                if not chf._is_number(v):
                    errs.append(f"{sid}.{f}.{hk}: нет числа")
                elif not -1 <= v <= 1:
                    errs.append(f"{sid}.{f}.{hk}: {v} вне [-1, 1]")
                else:
                    out[sid][hk][f] = v
    if errs:
        raise BuildError(f"--political-paths ({name}):\n  " + "\n  ".join(errs))
    return out


def load_fixed_priors(path: Path) -> dict:
    """references/fixed-priors.yaml -> {тикер: запись priors}. Битый или отсутствующий файл — отказ."""
    import yaml
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise BuildError(f"справочник фиксированных чувствительностей не читается ({path}): {e}")
    except yaml.YAMLError as e:
        raise BuildError(f"{path.name}: невалидный YAML: {e}")
    if not isinstance(doc, dict) or doc.get("schema_version") != 1 or not isinstance(doc.get("fixed"), dict):
        raise BuildError(f"{path.name}: ожидались schema_version: 1 и словарь fixed")
    errs: list[str] = []
    out: dict = {}
    for t, rec in doc["fixed"].items():
        if not isinstance(rec, dict):
            errs.append(f"{t}: запись не словарь")
            continue
        errs += [f"{t}: нет ключа {k}" for k in FIXED_REQUIRED if k not in rec]
        errs += [f"{t}: лишний ключ {k}" for k in sorted(set(rec) - set(FIXED_ALLOWED))]
        betas = rec.get("factor_betas")
        if isinstance(betas, dict):
            miss = [f for f in CANONICAL_FACTORS if f not in betas]
            extra = sorted(set(betas) - set(CANONICAL_FACTORS))
            if miss:
                errs.append(f"{t}.factor_betas: нет факторов {', '.join(miss)}")
            if extra:
                errs.append(f"{t}.factor_betas: лишние факторы {', '.join(extra)}")
            for f in CANONICAL_FACTORS:
                v = betas.get(f)
                if f in betas and (isinstance(v, bool) or not isinstance(v, (int, float)) or v != v
                                   or v in (float("inf"), float("-inf"))):
                    errs.append(f"{t}.factor_betas.{f} = {v!r} — не конечное число")
        elif "factor_betas" in rec:
            errs.append(f"{t}.factor_betas: ожидался словарь")
        for k in ("factor_betas_method", "asset_type", "sector_group"):
            if k in rec and (not isinstance(rec[k], str) or not rec[k].strip()):
                errs.append(f"{t}.{k}: ожидалась непустая строка")
        if not errs:
            out[str(t).upper()] = {"factor_betas": {f: float(betas[f]) for f in CANONICAL_FACTORS},
                                   "factor_betas_method": rec["factor_betas_method"],
                                   "factor_betas_r2": None,
                                   "asset_type": rec["asset_type"].strip(), "sector_group": rec["sector_group"].strip()}
    if errs:
        raise BuildError(f"{path.name}: файл не прошёл проверку:\n  " + "\n  ".join(errs))
    return out


def load_positions(path: Path) -> dict:
    """references/sanctions-positions.yaml -> {тикер: позиция на санкционной шкале}."""
    import yaml
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise BuildError(f"справочник позиций на санкционной шкале не читается ({path}): {e}")
    except yaml.YAMLError as e:
        raise BuildError(f"{path.name}: невалидный YAML: {e}")
    pos = doc.get("positions") if isinstance(doc, dict) else None
    if not isinstance(pos, dict) or not pos:
        raise BuildError(f"{path.name}: нет словаря positions")
    out: dict = {}
    for t, rec in pos.items():
        v = rec.get("position") if isinstance(rec, dict) else None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise BuildError(f"{path.name}: positions.{t}.position = {v!r} — не число")
        out[str(t).upper()] = v
    return out


def reuse_method(method: Any, name: str) -> str:
    """Метод перенесённой записи: «reused from <файл> | <исходный>», прежний префикс снимается."""
    if not isinstance(method, str) or not method.strip():
        return f"reused from {name}"
    m = method
    while _REUSED_RE.match(m):
        m = _REUSED_RE.sub("", m, count=1)
    return f"reused from {name} | {m}"


def merge_priors(*, snapshot: dict, carried_src: dict | None, carried_name: str | None, priors_in: dict,
                 fixed: dict, positions: dict, warnings: list[str]) -> tuple[dict, dict]:
    """Итоговые priors и сводка по источникам. Приоритет: fixed > priors_in > перенос; позиции — из справочника."""
    snap_t = {str(h.get("ticker") or "").upper() for h in snapshot.get("holdings") or []}
    carried: dict = {}
    gone = 0
    if carried_src is not None:
        for t, pr in carried_src.items():
            if str(t).upper() not in snap_t:
                gone += 1
                continue
            rec = copy.deepcopy(pr)
            rec["factor_betas_method"] = reuse_method(rec.get("factor_betas_method"), carried_name or "?")
            carried[str(t).upper()] = rec
    final = dict(carried)
    new: list[str] = []
    changed: list[str] = []
    fixed_used = sorted(t for t in fixed if t in snap_t)
    ignored = []
    for t, pr in priors_in.items():
        tu = str(t).upper()
        if tu in fixed_used:
            ignored.append(tu)
            continue
        if carried_src is not None and tu in snap_t:
            (changed if tu in carried else new).append(tu)
        final[t] = pr
    if ignored:
        warnings.append("проигнорировано: чувствительность задана в fixed-priors.yaml — " + ", ".join(sorted(ignored)))
    for t in fixed_used:
        final[t] = copy.deepcopy(fixed[t])
    diffs = []
    for t in sorted(final):
        if t.upper() in fixed or t.upper() not in positions or not isinstance(final[t], dict):
            continue
        ref, old = positions[t.upper()], final[t].get("sanctions_position")
        if old is not None and old != ref:
            diffs.append(f"{t}: было {old}, по справочнику {ref}")
        final[t] = {**final[t], "sanctions_position": ref}
    if diffs:
        warnings.append("sanctions_position заменён значением справочника sanctions-positions.yaml — "
                        + "; ".join(diffs))
    kept = sorted(t for t in carried if t not in changed and t not in fixed_used)
    info = {"from": carried_name, "carried": len(kept) if carried_src is not None else 0,
            "carried_gone": gone, "new": sorted(new), "changed": sorted(changed), "fixed": fixed_used,
            "ignored_in_priors": sorted(ignored)}
    return final, info


def build(*, snapshot: dict, scenarios_yaml: dict, macro_yaml: dict | None, macro_name: str | None,
          priors_in: dict, hf_in: dict | None, hf_payload: dict | None, fill: dict | None,
          carry_params: dict, overrides: dict | None, include_ev: bool, weight_type: str | None, slug: str, horizons: list[int],
          horizon_ends: dict | None, primary_horizon: int, today: str, horizon_mode: str | None = None,
          weights_path: Path | None, library_root: Path | None, scenarios_path: Path,
          political_prev: dict | None = None, political_prev_name: str | None = None,
          political_paths: dict | None = None, political_paths_name: str | None = None,
          hf_source: str | None = None, priors_from: dict | None = None, priors_from_name: str | None = None,
          references_dir: Path | None = None, pre_warnings: list[str] | None = None,
          terms_source: str | None = None) -> tuple[dict, dict]:
    import yaml
    warnings: list[str] = list(pre_warnings or [])
    refs = references_dir or REFERENCES
    fixed = load_fixed_priors(refs / FIXED_PRIORS_FILE)
    positions = load_positions(refs / POSITIONS_FILE)
    numbers_only = fill is None
    if fill is not None:
        check_fill(fill)
    check_same_matrix(scenarios_path, macro_yaml=macro_yaml, macro_name=macro_name,
                      political_prev=political_prev, political_prev_name=political_prev_name)

    stub_text = bss.build_stub(snapshot=snapshot, scenarios_yaml=scenarios_yaml, macro_yaml=macro_yaml,
                               slug=slug, horizons=horizons, primary_horizon=primary_horizon, today_iso=today,
                               horizon_ends=horizon_ends, macro_input=macro_name)
    stub = yaml.safe_load(stub_text)
    # Дата файла — дата прогона (по ней считается возраст суждений), а не дата снапшота.
    stub["date"] = today
    stub["run_id"] = f"PSS-{today.replace('-', '')}-{slug.upper().replace('-', '_')}"
    stub["review_date"] = _plus_months(today, 6)
    if horizon_mode:
        stub["horizon_mode"] = horizon_mode
    sids = sorted(stub["scenarios"])
    if not sids or any(not isinstance(stub["scenarios"][s].get("p"), (int, float)) for s in sids):
        raise BuildError("в --scenarios нет scenario_triggers с вероятностями")
    if asm.has_ph(stub.get("baseline_spot")):
        raise BuildError("в стабе baseline_spot без значений: нужен --macro-scenarios с baseline_spot")

    # горизонтные факторы
    if hf_in is not None and hf_payload is not None:
        raise BuildError("нужен не больше одного из --horizon-factors-input / --horizon-factors")
    sources = {"numeric": hf_source or "—", "political": None}
    from_macro = hf_in is None and hf_payload is None
    if not from_macro and (political_prev is not None or political_paths is not None):
        raise BuildError("--political-from / --political-paths нужны только в режиме «из макро-файла» "
                         "(без --horizon-factors-input / --horizon-factors)")
    if from_macro:
        if macro_yaml is None:
            raise BuildError("нужен --horizon-factors-input / --horizon-factors либо --macro-scenarios")
        if (political_prev is None) == (political_paths is None):
            raise BuildError("в режиме «из макро-файла» нужен ровно один источник политических факторов: "
                             "--political-from или --political-paths (sanctions, geopol)")
        hks = list(stub["horizon_ends"])
        try:
            fbh_n, cov_n, mw = sr.numeric_factors_from_macro(macro_yaml, sids, today, stub["horizon_ends"])
        except sr.RecalcError as e:
            raise BuildError(str(e))
        if political_prev is not None:
            pol = political_from_stress(political_prev, sids, hks, political_prev_name or "?")
            sources["political"] = f"--political-from {political_prev_name}"
        else:
            pol = political_from_paths(political_paths, sids, hks, political_paths_name or "?")
            sources["political"] = f"--political-paths {political_paths_name}"
        sources["numeric"] = f"сетка дат {macro_name}"
        for sid in sids:
            for hk in hks:
                fbh_n[sid][hk].update(pol[sid][hk])
        warnings += [f"макро-файл: {w}" for w in mw]
        warnings += [f"{hk}: {w}" for hk in hks for w in cov_n[hk]["warnings"]]
        hf = {"factors_by_horizon": fbh_n, "horizon_coverage": cov_n}
    elif hf_payload is not None:
        payload = copy.deepcopy(hf_payload)
        payload.setdefault("as_of", stub["date"])
        payload.setdefault("horizons", list(stub["horizons"]))
        payload.setdefault("horizon_ends", dict(stub["horizon_ends"]))
        payload.setdefault("baseline_spot", dict(stub["baseline_spot"]))
        try:
            hf = chf.run(payload)
        except SystemExit as e:
            raise BuildError(f"compute_horizon_factors: {str(e.code).strip()}")
        warnings += [f"horizon_factors: {w}" for w in hf.get("warnings") or []]
    else:
        hf = hf_in
    fbh, cov = hf.get("factors_by_horizon"), hf.get("horizon_coverage")
    if not isinstance(fbh, dict) or not isinstance(cov, dict):
        raise BuildError("горизонтные факторы: нет factors_by_horizon / horizon_coverage")
    if sorted(fbh) != sids:
        raise BuildError(f"сценарии факторов {sorted(fbh)} не совпадают со сценариями матрицы {sids}")

    meta = {k: copy.deepcopy(stub[k]) for k in sj.META_KEYS if k in stub}
    meta["include_ev"] = bool(include_ev)
    if weight_type:
        meta["weight_type"] = weight_type
    narrative: dict = {}
    if fill:
        for k, v in fill.items():
            (meta if k in MODEL_META else narrative)[k] = copy.deepcopy(v)
        if isinstance(narrative.get("caveats"), list):
            keep = []
            for c in narrative["caveats"]:
                if isinstance(c, dict) and sr.is_extrap_caveat(c):
                    warnings.append(f"оговорку о покрытии сроков пишет скрипт — запись {c.get('type')} из fill отброшена")
                else:
                    keep.append(c)
            narrative["caveats"] = keep
    if "scenario_matrix_ref" not in meta:
        meta["scenario_matrix_ref"] = f"scenarios/{scenarios_path.name}"
    rob_fill = narrative.pop("robustness", None) or {}
    narrative["robustness"] = {"hedge_target": rob_fill.get("hedge_target", MARK),
                               "modal_scenario": rob_fill.get("modal_scenario", MARK)}

    scenarios: dict = {}
    for sid in sids:
        st = stub["scenarios"][sid]
        p_by_h = st.get("p_by_horizon") or {hk: st["p"] for hk in meta["horizon_ends"]}
        scenarios[sid] = {"name": st["name"], "p": st["p"], "p_by_horizon": p_by_h,
                          "factors_by_horizon": copy.deepcopy(fbh[sid])}

    carried_src = None
    if priors_from is not None:
        carried_src = sj.extract(priors_from)["priors"]
    merged, priors_info = merge_priors(snapshot=snapshot, carried_src=carried_src, carried_name=priors_from_name,
                                       priors_in=priors_in, fixed=fixed, positions=positions, warnings=warnings)
    priors: dict = {}
    ignored: set[str] = set()
    for t, pr in merged.items():
        if not isinstance(pr, dict):
            raise BuildError(f"priors.{t}: ожидался словарь")
        priors[t] = {k: copy.deepcopy(pr[k]) for k in sj.PRIOR_KEYS if k in pr}
        ignored |= set(pr) - set(sj.PRIOR_KEYS)
    if ignored:
        warnings.append(f"ключи priors вне контракта проигнорированы: {', '.join(sorted(ignored))}")

    carry: dict = {"params": dict(carry_params),
                   "baseline_cbr_rate_pct": meta["baseline_spot"].get("cbr_rate_pct", meta["baseline_spot"].get("cbr_rate"))}
    if overrides:
        carry["overrides"] = copy.deepcopy(overrides)

    j = {"schema": sj.SCHEMA, "date": stub["date"], "slug": slug,
         "source_snapshot_id": stub["portfolio_snapshot_id"], "source_run_id": stub["run_id"],
         "meta": meta, "scenarios": scenarios, "horizon_coverage": copy.deepcopy(cov), "priors": priors,
         "known_unmapped_tickers": [], "carry": carry, "narrative": narrative}
    errs = sj.validate(j)
    if errs:
        raise BuildError("суждения невалидны:\n  " + "\n  ".join(errs))

    wfile, wname = resolve_weights(j, weights_path, library_root, scenarios_path, warnings)
    try:
        tree, summary = sr.recalc(j, snapshot, source_name="stress_build", source_kind="judgments", ctx=None,
                                  weights=wfile, weights_name=wname, today=stub["date"], at=stub["date"])
    except (sr.RecalcError, asm.AssembleError) as e:
        raise BuildError(str(e))
    rec = tree.pop("recalc")

    if rec["needs_judgment"]:
        rows = "\n  ".join(f"{x['ticker']} — {x.get('name')} — {x.get('weight_pct')}%" for x in rec["needs_judgment"])
        raise BuildError("у бумаг снапшота нет чувствительностей в --priors (тикер — название — доля):\n  " + rows)
    if rec["dropped"]:
        warnings.append("priors на бумаги вне снапшота (в файл не попали): "
                        + ", ".join(f"{d['ticker']}" for d in rec["dropped"]))
    if rec["stale_numeric_fill_fields"] and not numbers_only:
        raise BuildError("не посчитано и осталось значением fill: " + ", ".join(rec["stale_numeric_fill_fields"])
                         + "\n  " + "\n  ".join(rec.get("notes") or []))
    for n in rec.get("notes") or []:
        m = re.match(r"не посчитано (.*?): ", n)
        if m and set(x.strip() for x in m.group(1).split(",")) <= {"blocked_rub_memo"}:
            continue
        warnings.append(n)

    tree["run_id"] = stub["run_id"]
    tree["date"] = stub["date"]
    rob = tree.get("robustness") or {}
    if numbers_only:
        tree = {"numbers_only": True, **tree}
    else:
        for k in FILL_ROBUSTNESS:
            if rob.get(k) == MARK:
                raise BuildError(f"в fill нет robustness.{k}")
        issues = asm.validate_tree(tree, snapshot)
        if issues:
            raise BuildError(f"валидатор: блокеров {len(issues)}, файл не записан:\n" + "\n".join(
                f"  [{i['code']}] {i['field']}: ожидалось {i['expected']!r}, факт {i['actual']!r}" for i in issues))
    info = _summary(tree, snapshot, warnings, wname, wfile, numbers_only, summary)
    info["factor_probes"] = factor_probes(tree, j, snapshot, wfile, wname, today=stub["date"])
    info["factor_sources"] = sources
    if terms_source:
        info["terms_source"] = terms_source
    info["priors"] = {**priors_info, "from_file": priors_from is not None}
    return tree, info


RUB_FACTORS = ("usdrub", "cnyrub")
GOLD_FACTORS = ("xauusd",)


def _price_pct(tree: dict, sid: str, hk: str) -> float:
    pl = tree["scenarios"][sid]["portfolio_level_by_horizon"][hk]
    return pl["price_delta_rub"] / tree["base_value_rub"] * 100


def _expected(tree: dict, basis: str, hk: str) -> float | None:
    pa = (tree.get("portfolio_aggregates") or {}).get(basis) or {}
    return (pa.get("expected_pl_pct_by_horizon") or {}).get(hk)


def _zeroed(j: dict, factors: set[str]) -> dict:
    """Копия суждений, где перечисленные факторы равны 0.0 во всех сценариях на всех сроках."""
    j2 = copy.deepcopy(j)
    for sc in j2["scenarios"].values():
        for cell in (sc.get("factors_by_horizon") or {}).values():
            for f in factors:
                if f in cell:
                    cell[f] = 0.0
    return j2


def _r4(x: float | None) -> float | None:
    return None if x is None else round(x, 4)


def factor_probes(tree: dict, j: dict, snapshot: dict, wfile: dict | None, wname: str | None, *, today: str) -> dict:
    """Вклад каждого фактора и пробы «рубль = 0» / «золото = 0» на основном сроке, ценовой слой.
    Повторный sr.recalc на копиях суждений; ничего не пишет, исходные суждения не меняет."""
    hk = f"h{tree['primary_horizon']}"
    sids = list(tree["scenarios"])
    present: list[str] = []
    for sc in j["scenarios"].values():
        for cell in (sc.get("factors_by_horizon") or {}).values():
            for f, v in cell.items():
                if f not in present and isinstance(v, (int, float)) and not isinstance(v, bool):
                    present.append(f)

    def variant(factors: set[str]) -> dict:
        t, _ = sr.recalc(_zeroed(j, factors), snapshot, source_name="factor_probes", source_kind="judgments",
                         ctx=None, weights=wfile, weights_name=wname, today=today, at=today)
        return t

    base_pct = {s: _price_pct(tree, s, hk) for s in sids}
    base_ep, base_et = _expected(tree, "price", hk), _expected(tree, "total_return", hk)
    raw_p = {s: tree["scenarios"][s].get("p_by_horizon", {}).get(hk) for s in sids}
    if any(not isinstance(v, (int, float)) for v in raw_p.values()) or sum(raw_p.values()) <= 0:
        raw_p = {s: 1.0 for s in sids}
    tot = sum(raw_p.values())
    p = {s: raw_p[s] / tot for s in sids}

    trees: dict[tuple, dict] = {}

    def tree_without(factors: tuple[str, ...]) -> dict:
        if factors not in trees:
            trees[factors] = variant(set(factors))
        return trees[factors]

    by_factor: dict = {}
    for f in present:
        t = tree_without((f,))
        pp = {s: base_pct[s] - _price_pct(t, s, hk) for s in sids}
        ep = _expected(t, "price", hk)
        by_factor[f] = {"by_scenario_pp": {s: _r4(v) for s, v in pp.items()},
                        "expected_pp": _r4(None if base_ep is None or ep is None else base_ep - ep),
                        "abs_weighted_pp": _r4(sum(p[s] * abs(pp[s]) for s in sids))}
    ranking = sorted(by_factor, key=lambda f: (-by_factor[f]["abs_weighted_pp"], f))

    def probe(names: tuple[str, ...]) -> dict | None:
        fs = tuple(f for f in names if f in present)
        if not fs:
            return None
        t = tree_without(fs)
        return {"factors": list(fs),
                "expected_price_pct": {"base": _r4(base_ep), "without": _r4(_expected(t, "price", hk))},
                "expected_total_pct": {"base": _r4(base_et), "without": _r4(_expected(t, "total_return", hk))},
                "by_scenario_pct_without": {s: _r4(_price_pct(t, s, hk)) for s in sids}}

    probes = {k: v for k, v in (("rub", probe(RUB_FACTORS)), ("gold", probe(GOLD_FACTORS))) if v is not None}
    worst = min(sids, key=lambda s: tree["scenarios"][s]["portfolio_level_by_horizon"][hk]["price_delta_rub"])
    return {"horizon": hk, "basis": "price", "by_factor": by_factor, "ranking": ranking,
            "worst_scenario": worst, "probes": probes}


def _summary(tree: dict, snapshot: dict, warnings: list[str], wname: str | None, wfile: dict | None,
             numbers_only: bool, rsum: dict) -> dict:
    ph = f"h{tree['primary_horizon']}"
    sids = list(tree["scenarios"])
    hks = list(tree["horizon_ends"])
    table = {}
    for basis, key in (("price", "price_delta"), ("total_return", "total_return")):
        table[basis] = {sid: {hk: {"rub": tree["scenarios"][sid]["portfolio_level_by_horizon"][hk][f"{key}_rub"],
                                   "pct": tree["scenarios"][sid]["portfolio_level_by_horizon"][hk][f"{key}_pct"]}
                              for hk in hks} for sid in sids}
    ev = {}
    for basis in ("price", "total_return"):
        pa = tree["portfolio_aggregates"][basis]
        if any(v is not None for v in pa["expected_pl_rub_by_horizon"].values()):
            ev[basis] = {hk: {"rub": pa["expected_pl_rub_by_horizon"][hk], "pct": pa["expected_pl_pct_by_horizon"][hk]}
                         for hk in hks}
    worst = min(sids, key=lambda s: tree["scenarios"][s]["portfolio_level_by_horizon"][ph]["price_delta_rub"])
    # Топ-5 убытка — строки top_risks дерева (тот же список, что в YAML и таблицах); нет в дереве —
    # считаем функцией compute_derived_fields, а не своей формулой.
    risks = tree.get("top_risks")
    if risks is None:
        smap, _, _ = cdf.sector_map(snapshot, tree["per_position"], {}, cdf.load_sector_groups())
        risks = cdf.top_lists(snapshot, tree["per_position"], smap, tree["portfolio_aggregates"], [ph])[0]
    contrib = [{"ticker": x["ticker"], "rub": x["price_delta_rub"], "delta_pct": x["delta_pct"],
                "weight_pct": x["weight_pct"]} for x in risks if x.get("horizon") == ph]
    return {
        "snapshot": tree["portfolio_snapshot_id"], "horizon_ends": tree["horizon_ends"],
        "primary_horizon": ph, "weight_type": tree["weight_type"],
        "weights": ({"source": f"stress-weights:{wname}", "set_at": wfile.get("set_at")} if wfile
                    else {"source": "матрица сценариев", "set_at": None}),
        "p_primary": {s: tree["scenarios"][s]["p"] for s in sids},
        "table": table, "expected": ev, "worst_scenario": worst,
        "worst_scenario_name": tree["scenarios"][worst]["name"],
        "top_losers": contrib[:5], "positions": rsum["positions_computed"],
        "numbers_only": numbers_only,
        "concentration_computed": "concentration_ratio" in tree,
        "warnings": warnings,
    }


def render(info: dict) -> str:
    L = [f"Снапшот {info['snapshot']}; сроки {info['horizon_ends']}; основной {info['primary_horizon']}",
         f"Веса: {info['weights']['source']}" + (f" (set_at {info['weights']['set_at']})" if info['weights']['set_at'] else "")
         + f"; тип {info['weight_type']}; p основного: "
         + ", ".join(f"{s}={p}" for s, p in info["p_primary"].items())]
    hks = list(info["horizon_ends"])
    for basis in ("price", "total_return"):
        L.append(f"[{basis}] сценарий × горизонт, ₽ (%):")
        for sid, row in info["table"][basis].items():
            L.append(f"  {sid}: " + "; ".join(f"{hk} {row[hk]['rub']:,} ({row[hk]['pct']:+.2f}%)" for hk in hks))
        if basis in info["expected"]:
            e = info["expected"][basis]
            L.append("  ожидание: " + "; ".join(f"{hk} {e[hk]['rub']:,} ({e[hk]['pct']:+.2f}%)" for hk in hks))
    L.append(f"Худший сценарий основного горизонта (цена): {info['worst_scenario']} — {info['worst_scenario_name']}")
    L.append("Топ-5 бумаг по вкладу в убыток: " + "; ".join(
        f"{c['ticker']} {c['rub']:,} ₽ ({c['delta_pct']:+.1f}%, доля {c['weight_pct']}%)" for c in info["top_losers"]))
    L.append(f"Бумаг посчитано: {info['positions']}")
    fp = info.get("factor_probes")
    if fp and fp.get("ranking"):
        L.append(f"Вклад факторов ({fp['horizon']}, цена, взвешенный по весам |вклад|, п.п.): " + " · ".join(
            f"{f} {fp['by_factor'][f]['abs_weighted_pp']:.2f}".replace(".", ",") for f in fp["ranking"]))
        parts = []
        names = {"rub": "рубля", "gold": "золота"}
        for k, v in (fp.get("probes") or {}).items():
            e = v["expected_price_pct"]
            if e["base"] is not None and e["without"] is not None:
                parts.append(f"без {names[k]} ({'+'.join(v['factors'])}) ожидание по цене "
                             f"{e['base']:.2f}% → {e['without']:.2f}%".replace(".", ","))
        if parts:
            L.append("пробы: " + "; ".join(parts))
    pi = info.get("priors") or {}
    if pi.get("from_file"):
        L.append(f"чувствительности: перенесено {pi['carried']} из {pi['from']}, новых {len(pi['new'])}, "
                 f"изменено {len(pi['changed'])}")
        if pi["new"]:
            L.append("  новые: " + ", ".join(pi["new"]))
        if pi["changed"]:
            L.append("  изменены: " + ", ".join(pi["changed"]))
        if pi["carried_gone"]:
            L.append(f"  перенесённых бумаг, которых нет в снапшоте: {pi['carried_gone']}")
    if pi.get("fixed"):
        L.append("чувствительности из fixed-priors.yaml (решение владельца): " + ", ".join(pi["fixed"]))
    if info.get("terms_source"):
        L.append(f"Сроки: {info['terms_source']}")
    fs = info.get("factor_sources") or {}
    L.append(f"Числовые факторы: {fs.get('numeric')}" + (f"; политические: {fs['political']}" if fs.get("political") else ""))
    if info["numbers_only"]:
        L.append("Режим «только числа»: numbers_only: true, слоты суждения — заглушка " + MARK
                 + "; валидатор не запускался"
                 + ("" if info["concentration_computed"] else "; концентрация не посчитана (нет фактора концентрации в fill) — это нормально"))
    for w in info["warnings"]:
        L.append(f"ПРЕДУПРЕЖДЕНИЕ: {w}")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Стресс-файл одной командой: суждения → recalc → файл")
    ap.add_argument("--snapshot", required=True, type=Path)
    ap.add_argument("--scenarios", required=True, type=Path)
    ap.add_argument("--macro-scenarios", type=Path, default=None)
    ap.add_argument("--priors", type=Path, default=None)
    ap.add_argument("--priors-from", type=Path, default=None,
                    help="прошлый полный стресс-файл: чувствительности бумаг снапшота переносятся как есть")
    ap.add_argument("--horizon-factors-input", type=Path, default=None)
    ap.add_argument("--horizon-factors", type=Path, default=None)
    ap.add_argument("--political-from", type=Path, default=None,
                    help="прошлый стресс-файл: sanctions/geopol как есть (режим «из макро-файла»)")
    ap.add_argument("--political-paths", type=Path, default=None,
                    help="JSON {сценарий: {sanctions: {hNN: x}, geopol: {...}}} (режим «из макро-файла»)")
    ap.add_argument("--fill", type=Path, default=None)
    ap.add_argument("--carry-overrides", type=Path, default=None)
    for key, default in cbc.DEFAULT_PARAMS.items():
        ap.add_argument(f"--{key.replace('_', '-')}", type=float, default=None, help=f"параметр (default {default})")
    ap.add_argument("--weights-json", dest="weights", type=Path, default=None)
    ap.add_argument("--library-root", type=Path, default=None)
    ap.add_argument("--include-ev", action="store_true")
    ap.add_argument("--weight-type", choices=["equal", "probability"], default=None,
                    help="тип весов сценариев (по умолчанию как в стабе — equal; fill.weight_type приоритетнее)")
    ap.add_argument("--slug", default="shell-d1")
    ap.add_argument("--horizons", default=None)
    ap.add_argument("--anchor-dates", default=None)
    ap.add_argument("--horizons-from", type=Path, default=None,
                    help="прошлый стресс-файл: взять из него horizons, horizon_ends, primary_horizon, "
                         "(те же метки и даты; режим anchored; до ближайшего срока меньше 3 мес — сдвиг на 6)")
    ap.add_argument("--primary-horizon", type=int, default=None)
    ap.add_argument("--today", default=None)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--tables", type=Path, default=None,
                    help="файл .md: готовые таблицы отчёта из того же дерева результата (без новых расчётов)")
    try:
        args = ap.parse_args()
    except SystemExit as e:
        return 2 if e.code else 0
    if not args.priors and not args.priors_from:
        sys.stderr.write("ОШИБКА: нужен --priors и/или --priors-from\n")
        return 2
    if args.weights and args.library_root:
        sys.stderr.write("ОШИБКА: --weights-json и --library-root взаимоисключающи\n")
        return 2
    if args.horizon_factors_input and args.horizon_factors:
        sys.stderr.write("ОШИБКА: нужен не больше одного из --horizon-factors-input / --horizon-factors\n")
        return 2
    if not args.horizon_factors_input and not args.horizon_factors and not args.macro_scenarios:
        sys.stderr.write("ОШИБКА: нужен --horizon-factors-input / --horizon-factors либо --macro-scenarios\n")
        return 2
    today = args.today or date_t.today().isoformat()
    try:
        date_t.fromisoformat(today)
    except ValueError:
        sys.stderr.write(f"ОШИБКА: --today {today!r} не YYYY-MM-DD\n")
        return 2
    inputs = {"--snapshot": args.snapshot, "--scenarios": args.scenarios, "--macro-scenarios": args.macro_scenarios,
              "--priors": args.priors, "--priors-from": args.priors_from, "--horizon-factors-input": args.horizon_factors_input,
              "--horizon-factors": args.horizon_factors, "--fill": args.fill,
              "--carry-overrides": args.carry_overrides, "--weights-json": args.weights,
              "--political-from": args.political_from, "--political-paths": args.political_paths}
    if args.tables and args.tables.resolve() == args.output.resolve():
        sys.stderr.write("ОТКАЗ: --tables совпадает с --output\n")
        return 1
    for name, p in inputs.items():
        if p is not None and p.resolve() == args.output.resolve():
            sys.stderr.write(f"ОТКАЗ: --output совпадает с {name}\n")
            return 1
    try:
        for name, p in inputs.items():
            if p is not None and name != "--weights-json" and not p.exists():
                raise BuildError(f"{name} не найден: {p}")
        try:
            snapshot = bss.load_snapshot(args.snapshot)
        except SystemExit as e:
            raise BuildError(f"--snapshot: {e.code}")
        scen_yaml = _load(args.scenarios, "--scenarios")
        macro_yaml = _load(args.macro_scenarios, "--macro-scenarios") if args.macro_scenarios else None
        priors = {}
        if args.priors:
            priors = _load(args.priors, "--priors")
            if not isinstance(priors, dict) or not priors:
                raise BuildError("--priors: нужен непустой словарь {тикер: {...}}")
        prior_stress = _load(args.priors_from, "--priors-from") if args.priors_from else None
        if args.priors_from and not isinstance(prior_stress, dict):
            raise BuildError("--priors-from: ожидался полный стресс-файл (словарь)")
        hf_in = _load(args.horizon_factors, "--horizon-factors") if args.horizon_factors else None
        hf_payload = _load(args.horizon_factors_input, "--horizon-factors-input") if args.horizon_factors_input else None
        fill = None
        if args.fill:
            fill = _load(args.fill, "--fill")
            fill = {} if fill is None else fill
        pol_prev = _load(args.political_from, "--political-from") if args.political_from else None
        pol_paths = None
        if args.political_paths:
            try:
                pol_paths = json.loads(args.political_paths.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise BuildError(f"--political-paths не читается: {e}")
        hf_source = (args.horizon_factors_input or args.horizon_factors)
        hf_source = (f"{'--horizon-factors-input' if args.horizon_factors_input else '--horizon-factors'} "
                     f"{hf_source.name}") if hf_source else None
        overrides = _load(args.carry_overrides, "--carry-overrides") if args.carry_overrides else None
        if overrides is not None and not isinstance(overrides, dict):
            raise BuildError("--carry-overrides: ожидался словарь {тикер: {...}}")
        if args.weights is not None and not args.weights.exists():
            sys.stderr.write(f"ПРЕДУПРЕЖДЕНИЕ: --weights-json не найден: {args.weights}\n")
        as_of = snapshot.get("as_of_date") or today
        try:
            anchor = bss.parse_anchor_dates(args.anchor_dates)
            horizon_mode = None
            pre_warnings: list[str] = []
            terms_source = None
            site, site_warn = read_site_terms(args.library_root)
            if site_warn:
                pre_warnings.append(site_warn)
            if site is not None:
                if args.horizons_from and (anchor or args.horizons):
                    raise BuildError("--horizons-from нельзя сочетать с --horizons / --anchor-dates")
                horizons = sorted(int(k[1:]) for k in site["horizon_ends"])
                horizon_ends = {f"h{h}": site["horizon_ends"][f"h{h}"] for h in horizons}
                horizon_mode = "anchored"
                site_primary = site["primary_horizon"]
                terms_source = f"файл сроков сайта от {_ddmm(site.get('set_at'))}"
                same = True  # метки якорных дат — месяцы от снимка, поэтому сравниваются сами даты
                if anchor:
                    same = list(bss.anchor_dates_to_horizons(as_of, anchor)[1].values()) == list(horizon_ends.values())
                elif args.horizons:
                    same = bss.compute_horizon_ends(as_of, bss.parse_horizons(args.horizons)) == horizon_ends
                if not same or \
                        (args.primary_horizon is not None and args.primary_horizon != site_primary):
                    raise BuildError(f"сроки заданы на сайте ({HORIZONS_FILE}: {_terms_text(horizon_ends)}"
                                     f", основной h{site_primary}) — {SITE_HINT}")
                args.primary_horizon = site_primary
                if horizon_ends and today > _plus_months(min(horizon_ends.values()), -SHIFT_WHEN_MONTHS_LEFT):
                    pre_warnings.append(f"до ближайшего срока ({min(horizon_ends.values())}) осталось меньше "
                                        f"{SHIFT_WHEN_MONTHS_LEFT} мес.: сроки пора сдвинуть на сайте: «Стресс» → «Настройки стресса»")
                if args.horizons_from:
                    _, prev_ends, _, _ = horizons_from(args.horizons_from)
                    if prev_ends != horizon_ends:
                        pre_warnings.append(f"сроки изменены на сайте {_ddmm(site.get('set_at'))}: было "
                                            f"{_terms_text(prev_ends)}, стало {_terms_text(horizon_ends)}")
                if pol_prev is not None:
                    pol_ends = pol_prev.get("horizon_ends") if isinstance(pol_prev, dict) else None
                    if isinstance(pol_ends, dict) and {k: str(v)[:10] for k, v in pol_ends.items()} != horizon_ends:
                        pre_warnings.append(
                            f"санкционный и геополитический пути перенесены со сроков "
                            f"{_terms_text({k: str(v)[:10] for k, v in pol_ends.items()})} — пересмотри их под новые "
                            f"({_terms_text(horizon_ends)})")
            else:
                if args.horizons_from is None and args.primary_horizon is None:
                    args.primary_horizon = bss.DEFAULT_PRIMARY_HORIZON
                if args.horizons_from:
                    if anchor or args.horizons:
                        raise BuildError("--horizons-from нельзя сочетать с --horizons / --anchor-dates")
                    horizons, horizon_ends, horizon_mode, prev_primary = horizons_from(args.horizons_from)
                    was = dict(horizon_ends)
                    horizon_ends, shifted = shift_horizons(horizon_ends, today)
                    if shifted:
                        pre_warnings.append(
                            f"сроки сдвинуты на {SHIFT_BY_MONTHS * shifted} мес.: до ближайшего срока прошлого прогона "
                            f"({min(was.values())}) осталось меньше {SHIFT_WHEN_MONTHS_LEFT} мес. Было "
                            + ", ".join(f"{k} {v}" for k, v in was.items()) + "; стало "
                            + ", ".join(f"{k} {v}" for k, v in horizon_ends.items())
                            + ". Веса на сайте и политические пути заданы на прежние сроки — пересмотреть")
                    if args.primary_horizon is None:
                        args.primary_horizon = prev_primary
                    terms_source = f"из прошлого стресса {args.horizons_from.name}"
                elif anchor:
                    horizons, horizon_ends = bss.anchor_dates_to_horizons(as_of, anchor)
                else:
                    horizons, horizon_ends = bss.parse_horizons(args.horizons), None
        except ValueError as e:
            sys.stderr.write(f"ОШИБКА: {e}\n")
            return 2
        carry_params = {k: v for k in cbc.DEFAULT_PARAMS if (v := getattr(args, k)) is not None}
        tree, info = build(
            snapshot=snapshot, scenarios_yaml=scen_yaml, macro_yaml=macro_yaml,
            macro_name=args.macro_scenarios.name if args.macro_scenarios else None,
            priors_in=priors, hf_in=hf_in, hf_payload=hf_payload, fill=fill, carry_params=carry_params,
            overrides=overrides, include_ev=args.include_ev, weight_type=args.weight_type, slug=args.slug, horizons=horizons,
            horizon_ends=horizon_ends, primary_horizon=args.primary_horizon, today=today,
            horizon_mode=horizon_mode, weights_path=args.weights, library_root=args.library_root, scenarios_path=args.scenarios,
            political_prev=pol_prev, political_prev_name=args.political_from.name if args.political_from else None,
            political_paths=pol_paths, political_paths_name=args.political_paths.name if args.political_paths else None,
            hf_source=hf_source, pre_warnings=pre_warnings, priors_from=prior_stress,
            priors_from_name=args.priors_from.stem if args.priors_from else None,
            terms_source=terms_source)
    except BuildError as e:
        sys.stderr.write(f"ОТКАЗ: {e}\n")
        return 1
    asm.atomic_write(args.output, sr._dump_yaml(tree))
    if args.tables:
        asm.atomic_write(args.tables, stt.build_tables(tree, snapshot, info))
        info["tables"] = str(args.tables)
    info["output"] = str(args.output)
    sys.stdout.write(json.dumps(info, ensure_ascii=False, indent=2) + "\n" if args.json
                     else f"OK: {args.output}\n" + render(info))
    return 0


if __name__ == "__main__":
    sys.exit(main())
