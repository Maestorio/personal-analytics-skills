#!/usr/bin/env python3
"""
build_coherence_bundle.py  —  Stage P of portfolio-coherence-audit (Fable deep-pass, sphere 3).

DETERMINISTIC PRE-STAGE. No LLM. Run by Opus/Sonnet orchestration or plain cron BEFORE Fable.

v1.1 — field paths verified against REAL artifacts (2026-07-02/03): snapshot 2.0, stress@2, integrated-view@1.3.
v1.2 — macro-L1 (factors.*.level_l1_<DATE>) levels->deltas vs baseline_spot; weekly=scenario-tag; cone tolerance.
v1.3 — +scenario_blindspots +mc_divergence +unrealizable_exposure +iis3 +consensus_dispersion (--forecasts-dir).
v1.4 — +joint_tail (worst joint cell из delta_pct_by_scenario) +diachronic (дифф с прошлым bundle)
       +watch_verdict (детерминированный «нужен ли Fable-прогон») +confidence у L1 point-views.

Purpose
-------
Turn the 5 required pipeline artifacts (+ optional macro-chain overlays) into ONE validated,
normalized, self-contained bundle: `coherence-input-bundle-<date>.json`.

Fable's Stage R then reads ONLY this bundle + the fixed brief in SKILL.md — it never parses
the heterogeneous files itself. Precise, cheap, testable; garbage-in is caught here (before Fable).

Hard rule: reason OVER validated numbers, never recompute them. This script only *repackages*
numbers already produced by scenario-stress. The only arithmetic is trivially auditable aggregation
(Σ betaᵢ·weightᵢ per factor; min/max of a scenario cone), explicitly labelled.

Exit codes: 0 = bundle ready; 2 = HARD STOP (consistency / missing input); 3 = usage/IO error.
"""

from __future__ import annotations
import argparse
import datetime as dt
import glob
import json
import os
import re
import sys

try:
    import yaml
except Exception:  # pragma: no cover
    sys.stderr.write("PyYAML required: pip install pyyaml --break-system-packages\n")
    sys.exit(3)

# Кодлисты (`codelists.json`, загрузчик `codelists.py`) — канон в _shared-references/; в упакованном .skill — в своей
# scripts/ (pack.sh кладёт оба файла по импорту). Сначала каталог скрипта.
_CL_HERE = os.path.dirname(os.path.abspath(__file__))
for _cl_cand in (_CL_HERE, os.path.normpath(os.path.join(_CL_HERE, "..", "..", "..", "_shared-references"))):
    if _cl_cand not in sys.path:
        sys.path.insert(0, _cl_cand)
import codelists  # noqa: E402

# Вердикт облигации «бумага под вопросом» в едином словаре (schema.md §3.4).
_WATCH = "WATCH"

SCHEMA = "coherence-input-bundle@1.4"  # v1.4: +joint_tail +diachronic +watch_verdict +L1 confidence

STALENESS = {  # days, from SPEC §4
    "snapshot": 14, "stress": 90, "weekly_stock": 14, "weekly_bond": 14,
    "integrated_view": 14, "macro_marginal": 30, "macro_scenarios": 30,
}
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


# --------------------------------------------------------------------------- IO
def _read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def load_json(p):
    return json.loads(_read(p))


def load_yaml(p):
    return yaml.safe_load(_read(p))


def load_md_frontmatter(p):
    txt = _read(p)
    m = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n", txt, re.DOTALL)
    if not m:
        return {}, txt
    return (yaml.safe_load(m.group(1)) or {}), txt[m.end():]


def date_from_name(p):
    m = DATE_RE.search(os.path.basename(p or ""))
    return m.group(1) if m else None


def date_in(s):
    """Extract a YYYY-MM-DD from any id/filename form (e.g. 'portfolio-2026-07-02.json')."""
    if not s:
        return None
    m = DATE_RE.search(str(s))
    return m.group(1) if m else str(s)


def age_days(d, asof):
    try:
        return (asof - dt.date.fromisoformat(d)).days
    except Exception:
        return None


def as_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def norm_h(h):
    if h is None:
        return None
    s = str(h).strip().lower()
    m = re.fullmatch(r"h?(\d{1,3})", s)
    if m:
        return f"m{int(m.group(1)):02d}"
    m = re.fullmatch(r"(20\d{2})", s)
    return f"y{m.group(1)}" if m else s


def find_recalc(stress_path):
    """Пересчёт сайта для выбранного стресса скилла: `<папка>/auto/recalc-<имя стресса>`.

    Берётся, только если файл читается, в нём есть блок `recalc`, `recalc.source_stress`
    равен имени выбранного стресса и пересчёт сделан не раньше последней записи файла стресса
    (стресс, заменённый под тем же именем, оставляет пересчёт прежней версии).
    Нет файла -> None. Битый/не тот/устаревший -> {"warning": ...}.
    То же правило в skills/ru-portfolio-advisor/scripts/stress_digest.py.
    """
    name = os.path.basename(stress_path)
    path = os.path.join(os.path.dirname(stress_path), "auto", "recalc-" + name)
    if not os.path.isfile(path):
        return None
    try:
        data = load_yaml(path)
    except Exception as exc:  # noqa: BLE001
        return {"warning": f"stress_recalc_skipped: {os.path.basename(path)} не читается ({exc})"}
    rc = data.get("recalc") if isinstance(data, dict) else None
    if not isinstance(rc, dict):
        return {"warning": f"stress_recalc_skipped: в {os.path.basename(path)} нет блока recalc"}
    if rc.get("source_stress") != name:
        return {"warning": f"stress_recalc_skipped: recalc.source_stress={rc.get('source_stress')!r} "
                           f"не равен выбранному стрессу {name!r}"}
    if recalc_older_than_stress(rc, stress_path):
        return {"warning": f"stress_recalc_skipped: пересчёт от {rc.get('at')} сделан до последней записи "
                           f"файла стресса {name!r} — он от прежней версии; числа из стресса скилла"}
    return {"path": path, "doc": data}


def recalc_older_than_stress(rc, stress_path):
    """Пересчёт (`recalc.at`) сделан раньше последней записи файла стресса — с точностью до секунды.
    Времени пересчёта нет или оно не читается -> False (не судим). Время без пояса — московское."""
    at = rc.get("at")
    try:
        t = at if isinstance(at, dt.datetime) else dt.datetime.fromisoformat(str(at))
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone(dt.timedelta(hours=3)))
        return t.timestamp() < int(os.path.getmtime(stress_path))
    except (TypeError, ValueError, OSError):
        return False


def recalc_info(rc, judgments_date):
    """Сведения о пересчёте (те же ключи в stress_digest.py)."""
    src = str(rc.get("source_stress"))
    return {
        "source_stress": src, "judgments_date": judgments_date,
        "snapshot_id": rc.get("snapshot_id"), "source_snapshot_id": rc.get("source_snapshot_id"),
        "at": rc.get("at"), "reason": rc.get("reason"),
        "narrative_stale": bool(rc.get("narrative_stale")),
        "message": (f"числа стресса — пересчёт сайта от {rc.get('at')} на снапшоте {rc.get('snapshot_id')}; "
                    f"суждения — {src}" + (f" от {judgments_date}" if judgments_date else "")),
    }


def latest(pat):
    hits = sorted(glob.glob(pat))
    return hits[-1] if hits else None


def latest_stress(pat):
    """Самый свежий стресс: дата в имени → время записи файла → имя (то же правило у сайта, вьюера и советника).
    Между двумя прогонами одной даты решает время записи, а не слаг в имени."""
    def key(path):
        try:
            written = os.path.getmtime(path)
        except OSError:
            written = 0.0
        return (date_from_name(path) or "", written, os.path.basename(path))
    hits = glob.glob(pat)
    return max(hits, key=key) if hits else None


def discover(root):
    p = os.path.join
    return {
        "snapshot": latest(p(root, "Portfolio", "snapshots", "portfolio-*.json")),
        "stress": latest_stress(p(root, "Portfolio", "stress", "stress-*.yaml")),
        "weekly_stock": latest(p(root, "Portfolio", "weekly-reviews", "weekly-review-stock-*.yaml")),
        "weekly_bond": latest(p(root, "Portfolio", "weekly-reviews", "weekly-review-bond-*.yaml")),
        "integrated_view": latest(p(root, "Portfolio", "integrated-views", "integrated-view-*.md")),
        "macro_marginal": latest(p(root, "macro-chain", "macro-marginal-*.yaml")),
        "macro_scenarios": latest(p(root, "macro-chain", "macro-scenarios-*.yaml")),
    }


# --------------------------------------------------------------------------- Stage P
class Prep:
    def __init__(self, paths, asof, forecasts_dir=None, auto_recalc=False):
        self.paths, self.asof = paths, asof
        self.auto_recalc = auto_recalc  # True при автопоиске (--dir); явный --stress пересчёт не подставляет
        self.forecasts_dir = forecasts_dir
        self.notes, self.provenance, self.docs = [], [], {}

    def note(self, m):
        if m not in self.notes:
            self.notes.append(m)

    def load_all(self):
        for key, path in self.paths.items():
            e = {"artifact": key, "path": path, "present": bool(path)}
            if not path:
                self.provenance.append(e); continue
            if not os.path.exists(path):
                e.update(present=False, error="file not found"); self.provenance.append(e); continue
            try:
                if key == "integrated_view":
                    fm, body = load_md_frontmatter(path)
                    self.docs[key] = {"frontmatter": fm, "body": body}
                elif key in ("weekly_stock", "weekly_bond") and path.endswith(".md"):
                    # narrative md fallback: structured catalyst data lives in the paired .yaml
                    self.docs[key] = {"_md_narrative": _read(path)[:6000], "_is_md": True}
                    self.note(f"{key}: got .md (narrative) — structured per_stock/catalyst needs the paired .yaml")
                elif key == "snapshot":
                    self.docs[key] = load_json(path)
                else:
                    self.docs[key] = load_yaml(path)
            except Exception as ex:  # noqa: BLE001
                e.update(present=False, error=f"parse error: {ex}"); self.provenance.append(e); continue
            if key == "stress" and self.auto_recalc:
                found = find_recalc(path)
                if found and found.get("warning"):
                    e["stress_recalc_warning"] = found["warning"]; self.note(found["warning"])
                elif found:
                    # числа — из пересчёта; возраст/дата ниже считаются по файлу стресса скилла (path)
                    self.docs[key] = found["doc"]
                    e["numbers_path"] = found["path"]
                    e["stress_recalc"] = recalc_info(found["doc"]["recalc"], date_from_name(path))
                    self.note(e["stress_recalc"]["message"] + "; возраст стресса — по дате суждений")
                    if e["stress_recalc"]["narrative_stale"]:
                        self.note("тексты стресса (оговорки, слепые зоны) написаны для чисел дня прогона, "
                                  "не для пересчёта")
            d = date_from_name(path); a = age_days(d, self.asof)
            e.update(date=d, age_days=a, stale_limit_days=STALENESS.get(key),
                     stale=(a is not None and a > STALENESS.get(key, 10**9)))
            self.provenance.append(e)

    def _prov(self, k):
        return next((e for e in self.provenance if e["artifact"] == k), {})

    # ---- P1 consistency gate -------------------------------------------------
    def consistency_gate(self):
        required = ["snapshot", "stress", "weekly_stock", "weekly_bond", "integrated_view"]
        missing = [k for k in required if not self.docs.get(k)]
        stale = [k for k in required if self._prov(k).get("stale")]

        snap = self.docs.get("snapshot") or {}
        st = self.docs.get("stress") or {}
        ws = self.docs.get("weekly_stock") or {}
        wb = self.docs.get("weekly_bond") or {}
        iv = (self.docs.get("integrated_view") or {}).get("frontmatter", {})
        iv_inputs = iv.get("inputs", {}) if isinstance(iv, dict) else {}

        sids = {
            "snapshot": date_in(snap.get("as_of_date") or snap.get("id") or date_from_name(self.paths.get("snapshot"))),
            "stress": date_in(st.get("portfolio_snapshot_id")),          # 'portfolio-2026-07-02.json'
            "weekly_stock": date_in(ws.get("snapshot_id")) if not ws.get("_is_md") else None,
            "weekly_bond": date_in(wb.get("snapshot_id")) if not wb.get("_is_md") else None,
            "integrated_view": date_in(iv_inputs.get("snapshot_date") or iv_inputs.get("snapshot") or iv.get("view_date")),
        }
        self.note("snapshot ids normalized to YYYY-MM-DD from: snapshot.as_of_date | stress.portfolio_snapshot_id | "
                  "weekly.snapshot_id | integrated_view.inputs.snapshot_date")

        present = {k: v for k, v in sids.items() if v}
        distinct = set(present.values())
        conflict = len(distinct) > 1
        status, reasons = "ok", []
        if missing:
            status = "stop"; reasons.append(f"missing required inputs: {missing}")
        if stale:
            status = "stop"; reasons.append(f"stale required inputs beyond window: {stale}")
        if conflict:
            status = "stop"; reasons.append(f"snapshot date mismatch across artifacts: {present}")
        if not conflict and len(present) < len(sids):
            reasons.append(f"snapshot date absent in: {[k for k in sids if not sids[k]]} (degraded)")
            if status == "ok":
                status = "degraded"
        return {"status": status, "snapshot_ids": sids, "id_conflict": conflict,
                "missing_required": missing, "stale_required": stale, "reasons": reasons}

    # ---- helpers -------------------------------------------------------------
    def factor_defs(self):
        fd = (self.docs.get("stress") or {}).get("factor_definitions") or {}
        if not fd:
            self.note("stress.factor_definitions absent -> factor set inferred from beta keys")
        return fd

    def asset_types(self):
        """ticker -> 'stock'|'bond' from snapshot.holdings[].asset_type; bond if in bond_carry.per_position."""
        typ = {}
        for h in (self.docs.get("snapshot") or {}).get("holdings", []):
            t = h.get("ticker")
            if t:
                typ[t] = (h.get("asset_type") or "").lower()
        bc = ((self.docs.get("stress") or {}).get("bond_carry") or {}).get("per_position") or {}
        for isin in bc:
            typ.setdefault(isin, "bond")
        self.note("asset class from snapshot.holdings[].asset_type; bond_carry.per_position keys treated as bond")
        return typ

    # ---- P4 factor-overlap (the key finding) ---------------------------------
    def factor_overlap(self):
        st = self.docs.get("stress") or {}
        per = st.get("per_position") or {}
        typ = self.asset_types()
        eq, bd = {}, {}
        n_eq = n_bd = 0
        for tkr, pos in per.items():
            if not isinstance(pos, dict):
                continue
            betas = pos.get("factor_betas") or {}
            w = as_float(pos.get("weight_pct"))
            if w is None or not betas:
                continue
            is_bond = typ.get(tkr, "").startswith("bond")
            tgt = bd if is_bond else eq
            n_bd += is_bond; n_eq += (not is_bond)
            for f, b in betas.items():
                bf = as_float(b)
                if bf is None:
                    continue
                tgt[f] = tgt.get(f, 0.0) + bf * w / 100.0
        self.note("exposure per factor = Σ factor_betas·weight_pct/100, split equity/bond by asset class "
                  "(betas share a factor's unit, so equity vs bond is comparable within a factor)")
        factors = sorted(set(eq) | set(bd))
        rows = []
        for f in factors:
            e, b = eq.get(f), bd.get(f)
            # a leg counts only if present AND material (exactly-zero exposure = no leg, made explicit)
            both = e is not None and b is not None and abs(e) > 1e-9 and abs(b) > 1e-9
            direction = None
            if both:
                direction = "reinforcing" if (e > 0) == (b > 0) else "offsetting"
            rows.append({
                "factor": f,
                "equity_exposure": round(e, 4) if e is not None else None,
                "bond_exposure": round(b, 4) if b is not None else None,
                "net_exposure": round((e or 0) + (b or 0), 4),
                "both_legs": both,
                "direction": direction,   # reinforcing = hidden concentration; offsetting = natural hedge
            })
        rows.sort(key=lambda r: (r["both_legs"] and r["direction"] == "reinforcing", abs(r["net_exposure"])), reverse=True)
        return {"rows": rows, "n_equity_positions": n_eq, "n_bond_positions": n_bd,
                "stress_dominant_factor": st.get("dominant_factor"),
                "stress_concentration_ratio": st.get("concentration_ratio")}

    # ---- P2 assumption ledger ------------------------------------------------
    def assumption_ledger(self):
        L = []
        st = self.docs.get("stress") or {}
        for sc, blk in (st.get("scenarios") or {}).items():
            for h, fac in ((blk or {}).get("factors_by_horizon") or {}).items():
                if isinstance(fac, dict):
                    for f, v in fac.items():
                        L.append({"source": f"stress:{sc}", "source_class": "scenario",
                                  "factor": f, "horizon": norm_h(h), "value": as_float(v)})
        ms = self.docs.get("macro_scenarios") or {}
        for sc, blk in (ms.get("by_scenario") or {}).items():
            fbh = (blk or {}).get("factors_by_horizon") or (blk or {}).get("factors") or {}
            for h, fac in (fbh or {}).items():
                if isinstance(fac, dict):
                    for f, v in fac.items():
                        L.append({"source": f"macro-L2:{sc}", "source_class": "scenario",
                                  "factor": f, "horizon": norm_h(h), "value": as_float(v)})
        # macro-marginal (L1): factors.<name>.level_l1_<DATE> are LEVELS -> deltas vs stress.baseline_spot,
        # so they land on the same basis as the scenario cone (which is in deltas). This basis conversion
        # is trivially auditable ((level-base)/base, or level-base for the rate) — labelled, not a new forecast.
        MM2STRESS = {"brent_price": "brent", "usdrub_rate": "usdrub", "cnyrub_rate": "cnyrub",
                     "xauusd_price": "xauusd", "cbr_rate": "cbr_rate", "sanctions_russia": "sanctions"}
        BASE_KEY = {"brent": "brent_usd", "usdrub": "usdrub", "cnyrub": "cnyrub",
                    "xauusd": "xauusd_usd", "cbr_rate": "cbr_rate_pct"}
        base = st.get("baseline_spot") or {}
        mm = self.docs.get("macro_marginal") or {}
        mm_factors = mm.get("factors") if isinstance(mm, dict) else None
        if isinstance(mm_factors, dict):
            for mmname, blk in mm_factors.items():
                sf = MM2STRESS.get(mmname)
                if not sf or not isinstance(blk, dict):
                    continue
                lv = []
                for k, v in blk.items():
                    m = re.match(r"level_l1_(\d{4}-\d{2}-\d{2})$", str(k))
                    if m and as_float(v) is not None:
                        lv.append((m.group(1), as_float(v)))
                lv.sort()
                b = as_float(base.get(BASE_KEY.get(sf)))
                conf = as_float(blk.get("confidence"))
                for i, (_d, level) in enumerate(lv[:3]):
                    if b in (None, 0):
                        delta = None
                    elif sf == "cbr_rate":
                        delta = round(level - b, 4)                    # pp
                    else:
                        delta = round((level - b) / b * 100.0, 4)      # % vs baseline
                    L.append({"source": f"macro-L1:{mmname}", "source_class": "point",
                              "factor": sf, "horizon": ["m06", "m12", "m24"][i], "value": delta,
                              "confidence": conf})
            self.note("macro-L1 from factors.<name>.level_l1_<DATE>: names mapped to stress factors; "
                      "LEVELS->deltas vs stress.baseline_spot (pct for FX/oil/gold, pp for cbr_rate); "
                      "dates ordered -> m06/m12/m24; confidence = FCA-уверенность фактора (trust-контекст "
                      "точки для Stage R, None если в macro-marginal её нет)")

        # weekly catalyst.macro_dependency is a SCENARIO tag (A-D / null), NOT {factor, level}.
        # It's a thesis-anchor, not an independent numeric point-view -> excluded from the factor ledger.
        if any(not (self.docs.get(w) or {}).get("_is_md") for w in ("weekly_stock", "weekly_bond")):
            self.note("weekly catalyst.macro_dependency is a scenario tag (A-D/null), not {factor,level} -> "
                      "excluded from numeric ledger; scenario-lean in passthrough.weekly_scenario_dependency")
        return L

    # ---- P3 contradiction candidates -----------------------------------------
    def contradiction_candidates(self, ledger):
        """A scenario set is a CONE (differences are expected). A contradiction requires an independent
        POINT view (macro-L1 / weekly) that conflicts with another point view or falls OUTSIDE the cone."""
        groups = {}
        for e in ledger:
            groups.setdefault((e["factor"], e["horizon"]), []).append(e)
        out = []
        for (factor, horizon), items in groups.items():
            cone = [i["value"] for i in items if i["source_class"] == "scenario" and i["value"] is not None]
            points = {i["source"]: i["value"] for i in items
                      if i["source_class"] == "point" and i["value"] is not None}
            point_conf = {i["source"]: i.get("confidence") for i in items
                          if i["source_class"] == "point" and i["value"] is not None}
            if not points:
                continue  # scenario cone alone is not a contradiction
            lo, hi = (min(cone), max(cone)) if cone else (None, None)
            # tolerance kills rounding noise and degenerate cones (e.g. a factor whose scenario paths were
            # themselves derived from the same L1 marginal): 5% of cone width + small absolute floor.
            tol = (max(0.05, 0.05 * (hi - lo)) if cone else 0.0)
            pv = list(points.values())
            sign_conflict = len(pv) >= 2 and (min(pv) < 0 < max(pv))
            outside = {s: v for s, v in points.items() if cone and (v < lo - tol or v > hi + tol)}
            if not sign_conflict and not outside:
                continue
            out.append({"factor": factor, "horizon": horizon,
                        "scenario_cone": [lo, hi] if cone else None,
                        "point_views": points, "point_confidence": point_conf,
                        "point_sign_conflict": sign_conflict,
                        "points_outside_cone": outside})
        out.sort(key=lambda r: (r["point_sign_conflict"], len(r["points_outside_cone"])), reverse=True)
        return out

    # ---- NEW v1.3 checks -----------------------------------------------------
    @staticmethod
    def _sign(v):
        return 0 if v is None or abs(v) < 1e-9 else (1 if v > 0 else -1)

    def _scenario_grid(self):
        """List of per-cell factor dicts across scenario x horizon."""
        grid = []
        for _sc, blk in ((self.docs.get("stress") or {}).get("scenarios") or {}).items():
            for _h, fac in ((blk or {}).get("factors_by_horizon") or {}).items():
                if isinstance(fac, dict):
                    grid.append({k: as_float(v) for k, v in fac.items() if as_float(v) is not None})
        return grid

    def scenario_blindspots(self):
        """(#1) Factors whose sign never flips = one-sided axis (no opposite world);
        pairs of varying factors with constant relative sign = locked (super-factor / structural hedge)."""
        grid = self._scenario_grid()
        cells = {}
        for cell in grid:
            for f, v in cell.items():
                cells.setdefault(f, []).append(v)
        one_sided, varying = [], set()
        for f, vs in cells.items():
            signs = {self._sign(v) for v in vs if self._sign(v) != 0}
            if len(signs) <= 1 and vs:
                s = signs.pop() if signs else 0
                one_sided.append({"factor": f, "sign": "+" if s > 0 else "-" if s < 0 else "0",
                                  "range": [round(min(vs), 3), round(max(vs), 3)],
                                  "note": f"{f}: знак не меняется ни в одном сценарии×горизонте → нет мира с обратным движением"})
            else:
                varying.add(f)
        locked, vf = [], sorted(varying)
        for i in range(len(vf)):
            for j in range(i + 1, len(vf)):
                a, b = vf[i], vf[j]
                rels = {self._sign(c[a]) * self._sign(c[b]) for c in grid
                        if a in c and b in c and self._sign(c[a]) and self._sign(c[b])}
                if len(rels) == 1:
                    rel = rels.pop()
                    locked.append({"pair": [a, b], "relation": "super-factor" if rel > 0 else "structural-hedge",
                                   "note": (f"{a} и {b} всегда в одну сторону → стресс трактует их как один фактор"
                                            if rel > 0 else f"{a} и {b} всегда противоположны → хедж внутри сценариев")})
        return {"one_sided_factors": one_sided, "locked_pairs": locked,
                "note": "one-sided = ось без обратного мира (напр. ставка всегда вниз); "
                        "locked super-factor = скрытая концентрация оси; locked hedge = встроенный хедж"}

    def mc_divergence(self):
        """(#2) integrated-view headline (portfolio_by_horizon) vs total_return.expected; flag when they
        disagree or the CI does not cover the headline value the spread was built from."""
        iv = (self.docs.get("integrated_view") or {}).get("frontmatter", {})
        pbh = (iv.get("portfolio_by_horizon") or {}).get("horizons") or {}
        tr = (iv.get("total_return") or {}).get("horizons") or {}
        rows = []
        for h in sorted(set(pbh) | set(tr), key=lambda x: int(x) if str(x).isdigit() else 999):
            for leg in ("equity", "bond"):
                p = (pbh.get(h) or {}).get(leg) or {}
                pv = as_float(p.get("value"))
                tv = as_float(((tr.get(h) or {}).get("expected") or {}).get(leg))
                if pv is None or tv is None:
                    continue
                ci = p.get("ci")
                lo, hi = (as_float(ci[0]), as_float(ci[1])) if isinstance(ci, list) and len(ci) == 2 else (None, None)
                cov = (lambda x: lo is not None and hi is not None and min(lo, hi) <= x <= max(lo, hi))
                rows.append({"horizon": f"m{int(h):02d}", "leg": leg,
                             "headline_value": pv, "total_return_expected": round(tv, 3), "gap": round(pv - tv, 3),
                             "ci": [lo, hi], "ci_covers_headline": cov(pv), "ci_covers_expected": cov(tv),
                             "diverges": abs(pv - tv) > 2.0 or (lo is not None and not cov(pv))})
        return {"rows": rows, "flagged": [r for r in rows if r["diverges"]],
                "note": "headline=portfolio_by_horizon.value (база spread) vs total_return.expected; "
                        "gap>2пп или CI не покрывает headline → два центральных значения / mc_divergence"}

    def unrealizable_exposure(self):
        """(#3) blocked positions whose contribution to the verdict may be unrealizable."""
        snap = self.docs.get("snapshot") or {}
        st = self.docs.get("stress") or {}
        hold = snap.get("holdings") or []
        total = sum(as_float(h.get("value_rub")) or 0 for h in hold) or 1.0
        blocked = [h for h in hold if h.get("is_blocked")]
        blk_val = sum(as_float(h.get("value_rub")) or 0 for h in blocked)
        iv = (self.docs.get("integrated_view") or {}).get("frontmatter", {})
        tail_tk = {f.get("ticker") for f in ((iv.get("tail_flags") or {}).get("flags") or [])}
        blk_tk = {h.get("ticker") for h in blocked if h.get("ticker")}
        return {"blocked_pct_snapshot": round(blk_val / total * 100, 2),
                "blocked_pct_stress": st.get("blocked_pct"),
                "blocked_tickers": sorted(blk_tk),
                "blocked_and_tail_flagged": sorted(blk_tk & tail_tk),
                "note": "is_blocked позиции — вклад в вывод может быть нереализуем. Distressed (национализация и т.п.) "
                        f"в снапшоте НЕ помечен → сверять с вердиктом обзора облигаций {_WATCH} "
                        f"(напр. Борец RU000A105GN3)."}

    def iis3_summary(self):
        """(#4) ИИС-3 composition: long duration on a tax-locked account carries rate risk."""
        pos = [h for h in ((self.docs.get("snapshot") or {}).get("holdings") or []) if h.get("account") == "iis_3"]
        if not pos:
            return {"n_positions": 0, "note": "на ИИС-3 позиций нет"}
        durs = [as_float(h.get("duration_days")) for h in pos if as_float(h.get("duration_days")) is not None]
        return {"n_positions": len(pos), "value_rub": round(sum(as_float(h.get("value_rub")) or 0 for h in pos), 2),
                "avg_duration_days": round(sum(durs) / len(durs)) if durs else None,
                "max_duration_days": max(durs) if durs else None,
                "positions": [{"ticker": h.get("ticker"), "name": h.get("name"),
                               "duration_days": h.get("duration_days"), "maturity": h.get("maturity_date")}
                              for h in pos],
                "note": "ИИС-3: длинная дюрация = ставка-риск на льготном счёте; продажа рушит льготу (❄). "
                        "Все бумаги — главные бенефициары снижения ставки, но и её разворота."}

    _TOPIC2F = {"cbr-rate": "cbr_rate", "usdrub": "usdrub", "cnyrub": "cnyrub",
                "brent-price": "brent", "brent-oil": "brent", "xauusd": "xauusd", "gold-price": "xauusd"}

    def consensus(self):
        """(#7) Optional: parse forecasts/*.yaml conditional_on_scenarios.marginal.values (central+range,
        LEVELS) -> deltas vs baseline. Consensus central == macro-L1 (same source), so we do NOT re-add it
        as a point-view; the value is purely the DISPERSION check: scenario-cone width vs analyst range."""
        if not self.forecasts_dir or not os.path.isdir(self.forecasts_dir):
            return []
        st = self.docs.get("stress") or {}
        base = st.get("baseline_spot") or {}
        BASE_KEY = {"brent": "brent_usd", "usdrub": "usdrub", "cnyrub": "cnyrub",
                    "xauusd": "xauusd_usd", "cbr_rate": "cbr_rate_pct"}
        cone = {}
        for _sc, blk in (st.get("scenarios") or {}).items():
            for _h, fac in ((blk or {}).get("factors_by_horizon") or {}).items():
                if isinstance(fac, dict):
                    for f, v in fac.items():
                        vv = as_float(v)
                        if vv is None:
                            continue
                        k = (f, norm_h(_h))
                        c = cone.setdefault(k, [vv, vv])
                        c[0], c[1] = min(c[0], vv), max(c[1], vv)
        # prefer the exact forecast files this generation used (macro-marginal.factors.*.source_file);
        # fall back to forecasts matching the snapshot date. Avoids mixing stale dated versions.
        root = os.path.dirname(self.forecasts_dir.rstrip("/"))
        files, mmf = [], (self.docs.get("macro_marginal") or {}).get("factors")
        if isinstance(mmf, dict):
            for _blk in mmf.values():
                sfp = (_blk or {}).get("source_file")
                if sfp and os.path.exists(os.path.join(root, sfp)):
                    files.append(os.path.join(root, sfp))
        if not files:
            snapd = date_in((self.docs.get("snapshot") or {}).get("as_of_date")) or "@@@no-date@@@"
            files = [f for f in glob.glob(os.path.join(self.forecasts_dir, "*.yaml")) if snapd in f]
        disp = []
        for fp in sorted(set(files)):
            try:
                doc = load_yaml(fp)
            except Exception:
                continue
            if not isinstance(doc, dict):
                continue
            topic = str((doc.get("forecast") or {}).get("topic") or "")
            if "discount" in topic:                       # urals-brent-discount is not a stress factor
                continue
            sf = next((f for key, f in self._TOPIC2F.items() if topic.startswith(key)), None)
            if not sf:
                continue
            vals = ((doc.get("conditional_on_scenarios") or {}).get("marginal") or {}).get("values") or {}
            b = as_float(base.get(BASE_KEY.get(sf)))

            def to_delta(level, _sf=sf, _b=b):
                if level is None or _b in (None, 0):
                    return None
                return level - _b if _sf == "cbr_rate" else (level - _b) / _b * 100.0

            items = sorted((d, blk) for d, blk in vals.items() if isinstance(blk, dict))
            for i, (_d, blk) in enumerate(items[:3]):
                hz = ["m06", "m12", "m24"][i]
                rng = blk.get("range")
                if isinstance(rng, list) and len(rng) == 2:
                    r0, r1 = to_delta(as_float(rng[0])), to_delta(as_float(rng[1]))
                    cw = cone.get((sf, hz))
                    cwid = (cw[1] - cw[0]) if cw else None
                    if r0 is not None and r1 is not None:
                        rwid = abs(r1 - r0)
                        flag = "ok"
                        if cwid is not None and rwid > 1e-9:
                            if cwid < 0.6 * rwid:
                                flag = "stress understates dispersion"
                            elif cwid > 1.6 * rwid:
                                flag = "stress overstates dispersion"
                        disp.append({"factor": sf, "horizon": hz,
                                     "consensus_range_delta": [round(min(r0, r1), 3), round(max(r0, r1), 3)],
                                     "consensus_width": round(rwid, 3),
                                     "scenario_cone_width": round(cwid, 3) if cwid is not None else None,
                                     "cone_over_consensus": round(cwid / rwid, 2) if (cwid is not None and rwid > 1e-9) else None,
                                     "flag": flag})
        if disp:
            self.note("consensus dispersion from forecasts/*.yaml conditional_on_scenarios.marginal.values.range "
                      "(levels->deltas): scenario-cone width vs analyst range. Central==macro-L1, not re-added.")
        return disp

    # ---- v1.4: joint tail (worst joint cell, deterministic) ------------------
    def joint_tail(self):
        """(#v1.4) Совместный хвост ЧИСЛОМ: из stress.per_position.<t>.by_horizon.<h>
        .delta_pct_by_scenario.<sid>.value — взвешенная ценовая дельта каждой ноги в каждой ячейке
        сценарий×горизонт. Ячейка, где ОБЕ ноги минусовые одновременно, = joint drawdown.
        Только переупаковка готовых чисел стресса (Σ delta·weight / Σ weight per leg) — carry НЕ включён
        (bond carry смягчает; это консервативный ценовой хвост)."""
        st = self.docs.get("stress") or {}
        per = st.get("per_position") or {}
        typ = self.asset_types()
        acc = {}  # (sid, horizon, leg) -> [Σ delta·w, Σ w]
        for tkr, pos in per.items():
            if not isinstance(pos, dict):
                continue
            w = as_float(pos.get("weight_pct"))
            bh = pos.get("by_horizon")
            if w is None or not isinstance(bh, dict):
                continue
            leg = "bond" if typ.get(tkr, "").startswith("bond") else "equity"
            for h, cell in bh.items():
                dps = (cell or {}).get("delta_pct_by_scenario") or {}
                for sid, d in dps.items():
                    v = as_float((d or {}).get("value")) if isinstance(d, dict) else as_float(d)
                    if v is None:
                        continue
                    a = acc.setdefault((sid, norm_h(h), leg), [0.0, 0.0])
                    a[0] += v * w
                    a[1] += w
        if not acc:
            self.note("joint_tail: в stress.per_position нет by_horizon.delta_pct_by_scenario "
                      "(старый stress без Phase 4 V2-A) -> блок пуст")
            return {"cells": [], "worst": None,
                    "note": "нет per-scenario дельт по горизонтам в стрессе — joint tail не считается"}
        scen = st.get("scenarios") or {}
        probs = {sid: as_float((blk or {}).get("probability", (blk or {}).get("p")))
                 for sid, blk in scen.items()}
        # PSS-9: убеждение может зависеть от срока (`p_by_horizon`). Ключ ячейки здесь —
        # ПАРА (сценарий, горизонт), поэтому скалярная вероятность рядом с ней стала бы
        # ложной подписью: читатель отнесёт её именно к этому горизонту. Арифметики в
        # блоке нет — число только сопровождает ячейку, но подпись обязана быть верной.
        raw_by_h = {}   # norm_h -> {sid: вес}
        for sid, blk in scen.items():
            pbh = (blk or {}).get("p_by_horizon")
            if not isinstance(pbh, dict):
                continue
            for hk, v in pbh.items():
                val = as_float(v)
                if val is not None:
                    raw_by_h.setdefault(norm_h(hk), {})[sid] = val
        probs_by_h = {}  # (sid, norm_h) -> нормированная доля
        for hn, per_sid in raw_by_h.items():
            # Блок, заданный не всем сценариям, к подписи не годится: смешивать
            # горизонтные веса со скаляром нельзя (движок стресса такой артефакт и не
            # выпускает — input_contract.check_scenario_weights). Тихо остаёмся на скаляре.
            if len(per_sid) != len(scen) or sum(per_sid.values()) <= 0:
                continue
            tot = sum(per_sid.values())
            for sid, v in per_sid.items():
                probs_by_h[(sid, hn)] = round(v / tot, 4)
        combo = {}  # (sid, h) -> {leg: {"delta_pct", "weight_pct"}}
        for (sid, h, leg), (sw, tw) in acc.items():
            combo.setdefault((sid, h), {})[leg] = {
                "delta_pct": round(sw / tw, 3) if tw else None, "weight_pct": round(tw, 2)}
        cells = []
        for (sid, h), legs in sorted(combo.items()):
            eqd = (legs.get("equity") or {}).get("delta_pct")
            bdd = (legs.get("bond") or {}).get("delta_pct")
            wsum = sum((legs.get(lg) or {}).get("weight_pct") or 0 for lg in ("equity", "bond"))
            combined = (sum(((legs.get(lg) or {}).get("delta_pct") or 0) *
                            ((legs.get(lg) or {}).get("weight_pct") or 0)
                            for lg in ("equity", "bond")) / wsum) if wsum else None
            cells.append({"scenario": sid, "horizon": h,
                          "equity_delta_pct": eqd, "bond_delta_pct": bdd,
                          "combined_delta_pct": round(combined, 3) if combined is not None else None,
                          "joint_drawdown": eqd is not None and bdd is not None and eqd < 0 and bdd < 0,
                          "probability": probs_by_h.get((sid, h), probs.get(sid)),
                          "probability_source": "p_by_horizon"
                                                if (sid, h) in probs_by_h else "scalar"})
        cells.sort(key=lambda c: c["combined_delta_pct"] if c["combined_delta_pct"] is not None else 0)
        joint = [c for c in cells if c["joint_drawdown"]]
        self.note("joint_tail: взвешенные ценовые дельты ног по ячейкам сценарий×горизонт "
                  "(Σ delta·weight/Σ weight из stress delta_pct_by_scenario); carry не включён")
        if probs_by_h:
            self.note("joint_tail: probability взята из scenarios.p_by_horizon для своего "
                      "горизонта (probability_source), а не из скаляра")
        return {"cells": cells, "worst": joint[0] if joint else None,
                "n_joint_drawdown_cells": len(joint),
                "note": "joint_drawdown = обе ноги минусовые в одной ячейке; спред «акции−облигации» "
                        "такую ячейку маскирует. Ценовой слой: bond carry смягчает и здесь не учтён."}

    # ---- v1.4: diachronic diff vs previous bundle ----------------------------
    @staticmethod
    def _diff_sets(cur, prev):
        cur, prev = set(cur), set(prev)
        return {"new": sorted(cur - prev), "persisting": sorted(cur & prev),
                "closed": sorted(prev - cur)}

    def diachronic(self, current, prev_bundle_path):
        """(#v1.4) Дифф сигналов с прошлым bundle: закрывшиеся/висящие/новые. Персистентное
        противоречие (≥2 прогона) — качественно другой сигнал, чем свежее."""
        if not prev_bundle_path or not os.path.exists(prev_bundle_path):
            self.note("diachronic: прошлый bundle не найден — первый прогон, базы для диффа нет")
            return None
        try:
            prev = load_json(prev_bundle_path)
        except Exception as ex:  # noqa: BLE001
            self.note(f"diachronic: прошлый bundle не читается ({ex}) — дифф пропущен")
            return None

        def contr_keys(b):
            return [f"{c['factor']}/{c['horizon']}" for c in b.get("contradiction_candidates") or []]

        def onesided_keys(b):
            return [r["factor"] for r in (b.get("scenario_blindspots") or {}).get("one_sided_factors") or []]

        def mc_keys(b):
            return [f"{r['horizon']}/{r['leg']}" for r in (b.get("mc_divergence") or {}).get("flagged") or []]

        def reinf_keys(b):
            return [r["factor"] for r in (b.get("factor_overlap") or {}).get("rows") or []
                    if r.get("both_legs") and r.get("direction") == "reinforcing"]

        def cons_keys(b):
            return [f"{r['factor']}/{r['horizon']}:{r['flag']}" for r in b.get("consensus_dispersion") or []
                    if isinstance(r, dict) and r.get("flag") not in (None, "ok")]

        return {
            "prev_bundle": os.path.basename(prev_bundle_path),
            "prev_as_of": prev.get("as_of"),
            "contradictions": self._diff_sets(contr_keys(current), contr_keys(prev)),
            "one_sided_factors": self._diff_sets(onesided_keys(current), onesided_keys(prev)),
            "mc_flags": self._diff_sets(mc_keys(current), mc_keys(prev)),
            "reinforcing_factors": self._diff_sets(reinf_keys(current), reinf_keys(prev)),
            "consensus_flags": self._diff_sets(cons_keys(current), cons_keys(prev)),
            "note": "persisting ≥2 прогона = систематическое расхождение пайплайна, не месячный шум",
        }

    # ---- v1.4: watch verdict (deterministic gate for the expensive Stage R) --
    @staticmethod
    def watch_verdict(current, dia):
        """Детерминированный вердикт «оправдан ли Fable-прогон». Без LLM: любая дешёвая сессия
        запускает Stage P и читает это поле. Календарный месячный прогон остаётся решением
        пользователя — вердикт говорит только о НАЛИЧИИ сигналов."""
        signals = []
        n_contr = len(current.get("contradiction_candidates") or [])
        n_mc = len((current.get("mc_divergence") or {}).get("flagged") or [])
        n_joint = (current.get("joint_tail") or {}).get("n_joint_drawdown_cells") or 0
        if dia is None:
            if n_contr:
                signals.append(f"противоречия point-vs-конус: {n_contr}")
            if n_mc:
                signals.append(f"mc_divergence флагов: {n_mc}")
            signals.append("первый прогон — нет базы диффа, baseline-прогон Fable оправдан")
        else:
            for key, label in (("contradictions", "противоречия"), ("mc_flags", "mc_divergence"),
                               ("one_sided_factors", "one-sided оси"),
                               ("reinforcing_factors", "reinforcing-пересечения"),
                               ("consensus_flags", "consensus-флаги")):
                new = (dia.get(key) or {}).get("new") or []
                if new:
                    signals.append(f"новые {label}: {new}")
        return {"fable_recommended": bool(signals), "signals": signals,
                "counts": {"contradictions": n_contr, "mc_flagged": n_mc,
                           "joint_drawdown_cells": n_joint},
                "note": "fable_recommended=false ≠ запрет: это «новых сигналов нет», календарный "
                        "прогон — на усмотрение пользователя"}

    # ---- weekly scenario-lean (thesis concentration signal) ------------------
    def weekly_scenario_dependency(self):
        out = {}
        for wk in ("weekly_stock", "weekly_bond"):
            wd = self.docs.get(wk) or {}
            if not isinstance(wd, dict) or wd.get("_is_md"):
                out[wk] = None
                continue
            per = wd.get("per_stock") or wd.get("per_bond") or wd.get("positions") or {}
            it = per.items() if isinstance(per, dict) else enumerate(per)
            counts = {}
            for _tkr, pos in it:
                for cat in (pos or {}).get("catalyst", []) or []:
                    dep = cat.get("macro_dependency")
                    key = "none" if dep in (None, "", "null", []) else str(dep)
                    counts[key] = counts.get(key, 0) + 1
            out[wk] = counts
        return out

    # ---- passthrough ---------------------------------------------------------
    def passthrough(self):
        st = self.docs.get("stress") or {}
        iv = (self.docs.get("integrated_view") or {}).get("frontmatter", {})
        return {
            "stress": {k: st.get(k) for k in
                       ("concentration_ratio", "dominant_factor", "sector_breakdown_pct",
                        "macro_blindspots", "top_risks", "primary_horizon", "horizons")},
            "integrated_view": {k: iv.get(k) for k in
                                ("portfolio_by_horizon", "total_return", "tail_flags", "tiers",
                                 "primary_horizon", "horizons", "ci_method")},
            "weekly_scenario_dependency": self.weekly_scenario_dependency(),
        }

    def build(self, prev_bundle_path=None):
        self.load_all()
        gate = self.consistency_gate()
        ledger = self.assumption_ledger()
        cdisp = self.consensus()
        bundle = {
            "schema_version": SCHEMA,
            "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "as_of": self.asof.isoformat(),
            "consistency": gate,
            "provenance": self.provenance,
            "stress_recalc": next((e.get("stress_recalc") for e in self.provenance
                                   if e["artifact"] == "stress"), None),
            "factor_definitions": self.factor_defs(),
            "assumption_ledger": ledger,
            "contradiction_candidates": self.contradiction_candidates(ledger),
            "factor_overlap": self.factor_overlap(),
            "scenario_blindspots": self.scenario_blindspots(),
            "mc_divergence": self.mc_divergence(),
            "unrealizable_exposure": self.unrealizable_exposure(),
            "iis3": self.iis3_summary(),
            "consensus_dispersion": cdisp,
            "joint_tail": self.joint_tail(),
            "passthrough_numbers": self.passthrough(),
        }
        dia = self.diachronic(bundle, prev_bundle_path)
        bundle["diachronic"] = dia
        bundle["watch_verdict"] = self.watch_verdict(bundle, dia)
        bundle["schema_notes"] = self.notes
        bundle["fable_task_pointer"] = (
            "Stage R (Fable): consume THIS bundle only; do NOT recompute numbers. "
            "R1 contradiction_candidates (point views incl. consensus vs scenario cone; "
            "point_confidence = trust-контекст точки). "
            "R2 factor_overlap.rows both_legs=true & reinforcing (hidden concentration). "
            "R3 red-team the integrated-view conclusion. "
            "Also surface as deterministic findings: scenario_blindspots (one_sided_factors / locked_pairs = "
            "missing worlds & super-factors), mc_divergence (two central values / CI mismatch), "
            "joint_tail (worst joint cell: обе ноги минусовые одновременно, ценовой слой без carry), "
            "unrealizable_exposure (blocked positions in the verdict), iis3, consensus_dispersion "
            "(scenario cone narrower/wider than analyst range), diachronic (persisting ≥2 прогона = "
            "систематика, closed = закрыто пайплайном). Emit coherence-audit-<date>.md."
        )
        return bundle, gate["status"]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Stage P: build the Fable coherence-audit input bundle.")
    ap.add_argument("--dir")
    for k in ("snapshot", "stress", "weekly_stock", "weekly_bond", "integrated_view",
              "macro_marginal", "macro_scenarios"):
        ap.add_argument("--" + k.replace("_", "-"), dest=k)
    ap.add_argument("--asof"); ap.add_argument("--out")
    ap.add_argument("--forecasts-dir", dest="forecasts_dir",
                    help="optional dir of forecasts/*.yaml (FCA) for consensus point-views + dispersion; "
                         "auto-derived as <dir>/forecasts when --dir is given")
    ap.add_argument("--prev-bundle", dest="prev_bundle",
                    help="previous coherence-input-bundle-*.json for the diachronic diff; "
                         "auto-discovered next to --out (latest bundle dated before --asof)")
    a = ap.parse_args(argv)
    asof = dt.date.fromisoformat(a.asof) if a.asof else dt.date.today()
    keys = ("snapshot", "stress", "weekly_stock", "weekly_bond", "integrated_view",
            "macro_marginal", "macro_scenarios")
    paths = discover(a.dir) if a.dir else {k: getattr(a, k) for k in keys}
    fdir = a.forecasts_dir or (os.path.join(a.dir, "forecasts") if a.dir else None)
    out = a.out or f"coherence-input-bundle-{asof.isoformat()}.json"

    prev = a.prev_bundle
    if not prev:  # auto-discover: свежайший bundle рядом с --out, датированный СТРОГО раньше asof
        cand = [p for p in glob.glob(os.path.join(os.path.dirname(os.path.abspath(out)),
                                                  "coherence-input-bundle-*.json"))
                if (date_from_name(p) or "9999") < asof.isoformat()
                and os.path.abspath(p) != os.path.abspath(out)]
        prev = max(cand, default=None)

    bundle, status = Prep(paths, asof, forecasts_dir=fdir, auto_recalc=bool(a.dir)).build(prev_bundle_path=prev)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=2)
    sys.stderr.write(f"[Stage P] consistency={status}  bundle={out}\n")
    for r in bundle["consistency"]["reasons"]:
        sys.stderr.write(f"  - {r}\n")
    wv = bundle.get("watch_verdict") or {}
    sys.stderr.write(f"[Stage P] fable_recommended={wv.get('fable_recommended')}"
                     f"  counts={wv.get('counts')}\n")
    for s in wv.get("signals") or []:
        sys.stderr.write(f"  * {s}\n")
    if status == "stop":
        sys.stderr.write("[Stage P] HARD STOP — do NOT run Fable on this bundle.\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
