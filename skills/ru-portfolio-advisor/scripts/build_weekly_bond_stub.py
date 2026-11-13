#!/usr/bin/env python3
"""
build_weekly_bond_stub.py — детерминированный stub-генератор для weekly-review-bond-{date}.yaml.

Читает portfolio JSON snapshot (schema v2), батч-запрашивает MOEX ISS API
по списку bond-holdings, выдаёт YAML-стаб с пре-заполненными:
- Top-level метаданными (schema_version: 2 как ЧИСЛО, type, review_date в КАВЫЧКАХ,
  horizons/horizon_ends/primary_horizon — Phase 4 multiple horizons, …)
- summary блоком (bonds_total_rub, main_bonds_rub, iis_bonds_rub, bond_share_pct, …)
- per_bond[ISIN] полями из snapshot + MOEX (name, weight, on_iis, value_rub,
  qty, nominal_currency, bond_type heuristic, maturity_date, ytm_pct,
  duration_days, coupon_pct, coupon_type)
- TODO_LLM плейсхолдерами для аналитики (credit_rating, credit_quality,
  catalyst[], advisor_verdict)
- verification_priority: null — приоритет проверки ставит `assemble_artifact.py stamp-report` функцией движка
  после записи обзора (R28); статус гейта в обзор не копируется

LLM должна заменить TODO_LLM значения, НЕ переименовывать поля.
Validator save-to-library блокирует запись при незаполненных TODO_LLM.

CLI:
  python3 build_weekly_bond_stub.py \\
    --snapshot /path/to/portfolio-{date}.json \\
    --output /tmp/weekly-review-bond-{date}.stub.yaml \\
    [--no-moex-fetch]   # для оффлайн-теста (TODO_LLM на всех MOEX-полях)
"""

from __future__ import annotations

import argparse
import calendar
import json
import sys
from datetime import date as date_t
from pathlib import Path
from typing import Any

# ── Phase 4 (schema v2): multiple horizons ──
# Одна константа на producer/consumer, перекрывается CLI (D4-9).
DEFAULT_HORIZONS = [6, 12, 24]
DEFAULT_PRIMARY_HORIZON = 12


def parse_horizons(spec: str | None) -> list[int]:
    """'12,20,36' → [12, 20, 36] (отсортировано, уникально). None → DEFAULT_HORIZONS."""
    if not spec:
        return list(DEFAULT_HORIZONS)
    out = sorted({int(tok) for tok in spec.split(",") if tok.strip()})
    if not out:
        raise ValueError("пустой список горизонтов")
    return out


def add_months_eom(d: date_t, months: int) -> date_t:
    """d + months месяцев, округлённое до КОНЦА месяца (детерминированно, без хардкода)."""
    idx = d.year * 12 + (d.month - 1) + months
    year, month = idx // 12, idx % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date_t(year, month, last_day)


def compute_horizon_ends(review_date: str, horizons: list[int]) -> dict[str, str]:
    """{hNN: 'YYYY-MM-DD'} — конец месяца (review_date + NN мес). 29 февраля корректно."""
    base = date_t.fromisoformat(review_date[:10])
    return {f"h{h}": add_months_eom(base, h).isoformat() for h in horizons}


def parse_anchor_dates(spec: str | None) -> list[str] | None:
    """'2027-06-30,2028-06-30' → ['2027-06-30', '2028-06-30']. None → None."""
    if not spec:
        return None
    return [tok.strip() for tok in spec.split(",") if tok.strip()]


def anchor_dates_to_horizons(review_date: str, dates: list[str]) -> tuple[list[int], dict[str, str]]:
    """
    Якорный режим (§11.6): даты-цели → (horizons N, horizon_ends). N = календарных
    месяцев между review_date и целью. На следующем прогоне с той же датой N меньше →
    consumer пересчитает доходность, точка прогноза стоит.
    """
    base = date_t.fromisoformat(review_date[:10])
    seen: dict[int, str] = {}
    for ds in dates:
        d = date_t.fromisoformat(ds[:10])
        n = (d.year - base.year) * 12 + (d.month - base.month)
        if n <= 0:
            raise ValueError(
                f"якорная дата {ds} не в будущем относительно {review_date} (N={n})"
            )
        if n in seen and seen[n] != d.isoformat():
            raise ValueError(
                f"две якорные даты дают один горизонт h{n}: {seen[n]} и {d.isoformat()}"
            )
        seen[n] = d.isoformat()
    horizons = sorted(seen)
    return horizons, {f"h{n}": seen[n] for n in horizons}


# moex_quotes — канон _shared-references/ (в бандле pack.sh кладёт его в scripts/
# рядом, и Python сам видит каталог скрипта). Раньше брался из папки
# portfolio-data-loader: в репо и в бандле стаб работал с разными версиями.
_SHARED_DIR = Path(__file__).resolve().parents[3] / "_shared-references"
if _SHARED_DIR.is_dir() and str(_SHARED_DIR) not in sys.path:
    sys.path.append(str(_SHARED_DIR))

try:
    from moex_quotes import fetch_quotes  # type: ignore
    MOEX_AVAILABLE = True
except ImportError:
    MOEX_AVAILABLE = False


def find_prior_review(snapshot_path: Path | None, review_date: str) -> Path | None:
    """Последний обзор облигаций строго ДО review_date рядом со снапшотом (Portfolio/snapshots → ../weekly-reviews)."""
    if snapshot_path is None:
        return None
    d = Path(snapshot_path).resolve().parent.parent / "weekly-reviews"
    if not d.is_dir():
        return None
    best = None
    for f in d.glob("weekly-review-bond-*.yaml"):
        stamp = f.stem.rsplit("-", 3)[-3:]
        day = "-".join(stamp)
        if len(day) == 10 and day < review_date[:10] and (best is None or day > best[0]):
            best = (day, f)
    return best[1] if best else None


def load_prior_ratings(path: Path | None) -> dict[str, dict]:
    """ISIN → rating {value, agency, date, source} прошлого обзора облигаций; нет файла/блока — пусто.
    Рейтинг переносится в заготовку как есть: Mode 2 меняет его только при новом релизе агентства."""
    if path is None or not Path(path).is_file():
        return {}
    try:
        import yaml
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except Exception:                                   # noqa: BLE001 — битый прошлый обзор не роняет заготовку
        return {}
    out: dict[str, dict] = {}
    for isin, b in (doc.get("per_bond") or {}).items():
        r = b.get("rating") if isinstance(b, dict) else None
        if isinstance(r, dict) and r.get("value") not in (None, ""):
            out[str(isin)] = r
    return out


def load_snapshot(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        sys.stderr.write(f"ERROR: snapshot not found: {path}\n")
        sys.exit(1)
    data = json.loads(text)
    sv = str(data.get("schema_version", ""))
    if not sv.startswith("2."):
        sys.stderr.write(f"ERROR: snapshot schema_version={sv!r}; expected 2.x\n")
        sys.exit(1)
    return data


def y_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def y_num(value: Any, decimals: int | None = None) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if decimals is not None:
        return f"{value:.{decimals}f}"
    if isinstance(value, float):
        formatted = f"{value:.6f}".rstrip("0").rstrip(".")
        return formatted if formatted else "0"
    return str(value)


def y_bool(value: Any) -> str:
    return "true" if bool(value) else "false"


def derive_bond_type(name: str | None, nominal_currency: str | None,
                     moex_bond_type: str | None) -> str | None:
    """Эвристика: возвращает один из {ofz, corp_rub, fx_replacement, floater, perpetual} или None.

    None означает «не уверены, оставить TODO_LLM».
    """
    n = (name or "").lower()
    nc = (nominal_currency or "").upper()
    mbt = (moex_bond_type or "").lower()

    # ОФЗ — самый явный сигнал
    if "офз" in n or "ofz" in n.lower():
        return "ofz"
    # MOEX ISS отдаёт рубль legacy-кодом SUR, а не RUB — синонимы;
    # без этого каждый рублёвый корпорат уходил в fx_replacement (кейс 2026-07-31)
    is_rub = nc in ("RUB", "SUR")
    # Замещайки: валютный номинал или MOEX bond_type содержит «валютн»
    if nc and not is_rub:
        return "fx_replacement"
    if "валютн" in mbt or "замещ" in n:
        return "fx_replacement"
    # Floaters / перпы — по name
    if "плав" in n or "floater" in n:
        return "floater"
    if "перпет" in n or "perpetual" in n or "бессрочн" in n:
        return "perpetual"
    # Default — corp_rub если nominal рублёвый
    if is_rub:
        return "corp_rub"
    return None


def is_floater_by_name(name: str | None) -> bool:
    """Эвристика по имени — тот же паттерн, что floater-ветка derive_bond_type
    («плав»/«floater»), но отдельной функцией (RPA-14).

    derive_bond_type для ОФЗ возвращает "ofz" раньше, чем доходит до
    floater-ветки (ОФЗ — самый явный сигнал, проверяется первым), поэтому
    is_floater для ОФЗ-ПК не может опираться на derive_bond_type — только на
    plan_subtype ("Флоат") ИЛИ на эту самостоятельную проверку имени.
    """
    n = (name or "").lower()
    return "плав" in n or "floater" in n


def fetch_moex_data(isin_list: list[str]) -> dict[str, dict]:
    """Батч-запрос к MOEX ISS. Возвращает {ISIN: {ytm_pct, maturity_date, …}} или {} при ошибке."""
    if not MOEX_AVAILABLE:
        return {}
    if not isin_list:
        return {}
    try:
        quotes, _errors = fetch_quotes(isin_list, fields="full", kind_hint="bond")
    except Exception as e:
        sys.stderr.write(f"WARN: MOEX fetch failed: {e}\n")
        return {}
    out: dict[str, dict] = {}
    # fetch_quotes returns dict {secid: Quote}
    if isinstance(quotes, dict):
        items = quotes.items()
    else:
        # Defensive: assume list
        items = [(q.secid, q) for q in quotes if hasattr(q, "secid")]
    for secid, q in items:
        if not q:
            continue
        out[secid] = {
            "ytm_pct": getattr(q, "ytm_pct", None),
            "ytm_currency": getattr(q, "currency", None),
            "maturity_date": getattr(q, "maturity_date", None),
            "next_coupon_date": getattr(q, "next_coupon_date", None),
            "offer_date": getattr(q, "offer_date", None),
            "duration_days": getattr(q, "duration_days", None),
            "coupon_pct": getattr(q, "coupon_pct", None),
            "coupon_value": getattr(q, "coupon_value", None),
            "face_value": getattr(q, "face_value", None),
            "current_price": getattr(q, "last", None) or getattr(q, "prev_close", None),
            "short_name": getattr(q, "short_name", None),
            "moex_bond_type": getattr(q, "bond_type", None),
            "nominal_currency": getattr(q, "currency", None),
            "trading_status": getattr(q, "trading_status", None),
        }
    return out


MATURITY_BUCKET_UNKNOWN = "unknown"

# MOEX и IntelInvest отдают рублёвый номинал кодом SUR; в схеме валюта RUB.
# Без нормализации срез корзины расползается на две валюты (RUB и SUR),
# а bond_type ОФЗ рискует уехать в fx_replacement (SUR-баг, фикс 2026-08-01).
_CURRENCY_ALIASES = {"SUR": "RUB", "RUR": "RUB"}

# Поля, которые при молчании MOEX ISS берутся из снапшота. Прецедент 2026-08-15:
# ISS не резолвит суверенные выпуски по ISIN на TQCB (ОФЗ торгуются на TQOB),
# и стаб оставил TODO_LLM по 11 ОФЗ — модель восстанавливала их вручную, хотя
# portfolio-data-loader уже положил всё это в снапшот.
_SNAPSHOT_FALLBACK_FIELDS = (
    "ytm_pct", "maturity_date", "next_coupon_date", "offer_date",
    "duration_days", "coupon_pct", "nominal_currency",
)


def norm_currency(value: str | None) -> str | None:
    if not value:
        return value
    v = str(value).strip().upper()
    return _CURRENCY_ALIASES.get(v, v)


def bond_field(moex_data: dict | None, holding: dict[str, Any], field: str):
    """Значение поля: MOEX ISS → снапшот. Источник фиксируется в *_source."""
    md = moex_data or {}
    val = md.get(field)
    if val not in (None, ""):
        return val
    if field in _SNAPSHOT_FALLBACK_FIELDS:
        return holding.get(field)
    return None


def compute_summary_aggregates(bonds: list[dict[str, Any]],
                               moex_map: dict[str, dict],
                               bonds_total_rub: float,
                               *, value_key: str = "value_rub") -> dict[str, Any]:
    """Взвешенные агрегаты корзины — арифметика, не аналитика.

    До 2026-08-15 весь блок summary (weighted_ytm/duration, by_type_pct,
    maturity_ladder_pct, по-валютные срезы) стоял как TODO_LLM «см. формулу»,
    и модель считала его руками по 39–40 позициям. Верификация облигационного
    прогона 15.08 нашла 8 расхождений, часть из них — округления и потерянные
    строки именно в этих агрегатах. Всё перечисленное выводится из полей,
    которые скрипт уже собрал (value_rub, ytm_pct, duration_days, bond_type,
    maturity_date, nominal_currency), поэтому считается здесь.

    За моделью остаются: ci_pct к средней доходности (оценка неопределённости),
    by_credit_quality_pct (нужны кредитные рейтинги) и вся прозовая часть.

    Веса — доля value_rub в bonds_total_rub. Позиции без нужного поля в
    среднее не входят; их суммарный вес возвращается в coverage_*, чтобы
    «средняя по 60% корзины» не выглядела как средняя по корзине.

    `value_key="value_rub_main"` даёт срез без ИИС-3. Оба среза эмитятся
    намеренно: в артефактах 15.08 они сосуществовали неявно. MD-таблица §3.3
    честно объявляла срез main (рублёвая 17.34% / 1136 дн, валютная 7.82% —
    внутри одного среза сравнимы), YAML нёс срез по всей корзине (rub 16.47%,
    fx 7.82%), а `weighted_ytm_pct.basis` в том же YAML ссылался на «рублёвые
    выпуски (17,20%)» — третье число, не равное ни одному из соседних полей.
    Читатель машинного артефакта различить срезы не мог. Теперь оба среза
    лежат рядом явными ключами, и прозе не нужно их пересказывать.
    """
    scoped = [h for h in bonds if (h.get(value_key) or 0) > 0]
    scope_total = sum((h.get(value_key) or 0) for h in scoped)

    def _w(h):
        v = h.get(value_key) or 0
        return (v / scope_total) if scope_total else 0.0

    def _weighted(field: str, rows) -> tuple[float | None, float]:
        num = 0.0
        wsum = 0.0
        for h, md in rows:
            val = bond_field(md, h, field)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                w = _w(h)
                num += val * w
                wsum += w
        return ((num / wsum) if wsum else None), wsum

    rows = [(h, moex_map.get(h.get("ticker") or h.get("isin") or "") or {}) for h in scoped]

    ytm, ytm_cov = _weighted("ytm_pct", rows)
    dur, dur_cov = _weighted("duration_days", rows)

    by_type: dict[str, float] = {}
    by_plan_bucket: dict[str, float] = {}
    by_currency: dict[str, list] = {}
    ladder: dict[str, float] = {}
    for h, md in rows:
        w_pct = _w(h) * 100
        btype = derive_bond_type(
            (md.get("short_name") or h.get("name") or ""),
            bond_field(md, h, "nominal_currency"),
            md.get("moex_bond_type"),
        )
        by_type[btype or MATURITY_BUCKET_UNKNOWN] = round(
            by_type.get(btype or MATURITY_BUCKET_UNKNOWN, 0.0) + w_pct, 4)

        # by_plan_bucket_pct (RPA-13): plan_bucket_key приходит из снапшота
        # (PDL), не выводится здесь — модель классификации не дублируется.
        bucket_key = h.get("plan_bucket_key") or MATURITY_BUCKET_UNKNOWN
        by_plan_bucket[bucket_key] = round(
            by_plan_bucket.get(bucket_key, 0.0) + w_pct, 4)

        cur = norm_currency(bond_field(md, h, "nominal_currency")) or "RUB"
        by_currency.setdefault(cur, []).append((h, md))

        mdate = bond_field(md, h, "maturity_date")
        bucket = str(mdate)[:4] if mdate else MATURITY_BUCKET_UNKNOWN
        ladder[bucket] = round(ladder.get(bucket, 0.0) + w_pct, 4)

    per_currency: dict[str, dict] = {}
    for cur, crows in by_currency.items():
        c_total = sum((h.get(value_key) or 0) for h, _ in crows)

        def _cw(field):
            num = wsum = 0.0
            for h, md in crows:
                val = bond_field(md, h, field)
                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    w = (h.get(value_key) or 0) / c_total if c_total else 0
                    num += val * w
                    wsum += w
            return (num / wsum) if wsum else None

        per_currency[cur] = {
            "ytm_pct": _cw("ytm_pct"),
            "duration_days": _cw("duration_days"),
            "share_pct": round(c_total / scope_total * 100, 4) if scope_total else None,
        }

    return {
        "scope": "all" if value_key == "value_rub" else "main_only",
        "scope_total_rub": round(scope_total, 2),
        "weighted_ytm_pct": ytm,
        "weighted_ytm_coverage_pct": round(ytm_cov * 100, 2),
        "weighted_duration_days": dur,
        "weighted_duration_coverage_pct": round(dur_cov * 100, 2),
        "by_type_pct": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
        "by_plan_bucket_pct": dict(sorted(by_plan_bucket.items(), key=lambda kv: -kv[1])),
        "maturity_ladder_pct": dict(sorted(ladder.items())),
        "per_currency": per_currency,
    }


def build_per_bond_entry(
    isin: str,
    holding: dict[str, Any],
    moex_data: dict | None,
    total_excl_iis: float,
    bonds_total_rub: float,
    today_iso: str,
    prior_rating: dict | None = None,
) -> list[str]:
    """Сгенерировать YAML-блок для одной облигации."""
    lines: list[str] = []
    lines.append(f"  {isin}:")

    name = (moex_data or {}).get("short_name") or holding.get("name") or isin
    lines.append(f"    name: {y_str(name)}")

    # Account / IIS aggregate (поддерживает split main + iis_3 для одного ISIN)
    qty_main = holding.get("qty_main") or 0
    qty_iis = holding.get("qty_iis") or 0
    value_main = holding.get("value_rub_main") or 0
    value_iis = holding.get("value_rub_iis") or 0
    value_rub = holding.get("value_rub") or 0
    # on_iis: True если позиция полностью на IIS-3
    on_iis = (qty_main == 0 and qty_iis > 0)
    lines.append(f"    on_iis: {y_bool(on_iis)}")
    iis_share = (value_iis / value_rub * 100) if value_rub else None
    lines.append(f"    iis_share_pct: {y_num(iis_share, 2)}  # split-кейс: % этой позиции на IIS-3")

    # Weight (доля от total_excl_iis)
    weight_real_pct = (value_rub / total_excl_iis * 100) if total_excl_iis else None
    weight_in_bonds_pct = (value_rub / bonds_total_rub * 100) if bonds_total_rub else None
    lines.append(f"    weight_real_pct: {y_num(weight_real_pct, 4)}")
    lines.append(f"    weight_in_bonds_pct: {y_num(weight_in_bonds_pct, 4)}")

    # Numeric snapshot fields (агрегаты)
    lines.append(f"    qty: {y_num(holding.get('qty'), 2)}")
    lines.append(f"    qty_main: {y_num(qty_main, 2)}")
    lines.append(f"    qty_iis: {y_num(qty_iis, 2)}")
    lines.append(f"    value_rub: {y_num(value_rub, 2)}")
    lines.append(f"    value_rub_main: {y_num(value_main, 2)}")
    lines.append(f"    value_rub_iis: {y_num(value_iis, 2)}")

    # MOEX-populated fields (если есть)
    md = moex_data or {}
    nominal_currency = norm_currency(bond_field(md, holding, "nominal_currency")) or "RUB"
    lines.append(f"    nominal_currency: {y_str(nominal_currency)}")
    # bond_type heuristic (валюта — сырая, derive_bond_type сам знает про SUR)
    btype = derive_bond_type(name, bond_field(md, holding, "nominal_currency"),
                             md.get("moex_bond_type"))
    if btype:
        lines.append(f"    bond_type: {btype}")
    else:
        lines.append(f"    bond_type: TODO_LLM_ofz_corp_rub_fx_replacement_floater_perpetual")
    lines.append(f"    moex_bond_type_raw: {y_str(md.get('moex_bond_type') or 'unknown')}  # MOEX classifier для traceability")

    # === Плановые поля из снапшота (PDL-4, RPA-13/14) ===
    # plan_bucket/plan_subtype/credit_rating_file — из «План по Облигациям»/
    # «Облигации» Numbers-файла, отдельная таксономия от bond_type (§4.1 плана
    # bond-subtypes-plan.md). credit_rating (аналитическое, ниже) остаётся
    # TODO_LLM — файл даёт справку (Q5), модель проверяет по агентствам.
    plan_bucket = holding.get("plan_bucket")
    plan_subtype = holding.get("plan_subtype")
    credit_rating_file = holding.get("credit_rating_file")
    lines.append(f"    plan_bucket: {y_str(plan_bucket) if plan_bucket else 'null'}")
    lines.append(f"    plan_subtype: {y_str(plan_subtype) if plan_subtype else 'null'}")
    lines.append(f"    credit_rating_file: {y_str(credit_rating_file) if credit_rating_file else 'null'}  # справка из файла, НЕ сверенный credit_rating")
    # rating {value, agency, date, source} — рейтинг агентства, по нему загрузчик выводит корзину КОРП.
    # Переносится из прошлого обзора; меняется только при новом релизе агентства. У ОФЗ блока нет.
    if derive_bond_type(name, bond_field(md, holding, "nominal_currency"), md.get("moex_bond_type")) != "ofz":
        if prior_rating:
            lines.append("    rating:  # перенос из прошлого обзора — менять только при новом релизе агентства")
            for k in ("value", "agency", "date", "source"):
                v = prior_rating.get(k)
                lines.append(f"      {k}: {y_str(str(v)) if v not in (None, '') else 'null'}")
        else:
            lines.append("    rating: null  # {value, agency, date, source}: заполнить, если найден рейтинг агентства")
    # is_floater — ортогонально bond_type (эмитент), НЕ подменяет значение
    # floater в нём: ОФЗ-ПК остаётся bond_type: ofz, но is_floater: true (RPA-14).
    is_floater = (plan_subtype == "Флоат") or is_floater_by_name(name)
    lines.append(f"    is_floater: {y_bool(is_floater)}")

    # === Numeric MOEX fields ===
    # MOEX ISS → снапшот (ISS не резолвит ОФЗ по ISIN на TQCB — они на TQOB)
    mat = bond_field(md, holding, "maturity_date")
    lines.append(f"    maturity_date: {y_str(mat) if mat else 'TODO_LLM_YYYY-MM-DD'}")
    nxt = bond_field(md, holding, "next_coupon_date")
    lines.append(f"    next_coupon_date: {y_str(nxt) if nxt else 'null'}")
    offer = bond_field(md, holding, "offer_date")
    lines.append(f"    offer_date: {y_str(offer) if offer else 'null'}")
    lines.append(f"    duration_days: {y_num(bond_field(md, holding, 'duration_days'), 0)}")
    lines.append(f"    ytm_pct: {y_num(bond_field(md, holding, 'ytm_pct'), 4)}")
    lines.append(f"    ytm_currency: {y_str(norm_currency(md.get('ytm_currency')) or 'RUB')}")
    ytm_src = "moex_iss" if md.get("ytm_pct") not in (None, "") else \
        (holding.get("ytm_source") or "snapshot")
    lines.append(f"    ytm_source: {y_str(ytm_src)}")
    lines.append(f"    coupon_pct: {y_num(bond_field(md, holding, 'coupon_pct'), 4)}")
    lines.append(f"    coupon_value: {y_num(md.get('coupon_value'), 4)}")
    lines.append(f"    face_value: {y_num(md.get('face_value'), 2)}")
    cprice = md.get("current_price") or holding.get("current_price")
    lines.append(f"    current_price: {y_num(cprice, 4)}")

    # === Аналитические поля — LLM ===
    lines.append(f"    # === Аналитические поля ниже — заполнить LLM (НЕ переименовывать ключи) ===")
    # ОФЗ: эмитент, кредитное качество и приоритет проверки заданы правилом
    # (save-flow.md: «ОФЗ → credit_quality всегда HIGH»; суверен не рейтингуется
    # российскими агентствами отдельно от РФ). Остальным — TODO_LLM.
    if btype == "ofz":
        lines.append(f"    issuer: \"Минфин России\"")
        lines.append(f"    credit_rating: null  # суверен: отдельного рейтинга выпуска нет")
        lines.append(f"    credit_rating_agency: null")
        lines.append(f"    credit_rating_checked_at: null")
        lines.append(f"    credit_quality: HIGH")
    else:
        lines.append(f"    issuer: TODO_LLM_legal_entity_name  # ТОЛЬКО из раскрытия/MOEX, не из расшифровки тикера")
        lines.append(f"    credit_rating: TODO_LLM_rating_or_null")
        lines.append(f"    credit_rating_agency: TODO_LLM_agency_or_null")
        lines.append(f"    credit_rating_checked_at: null  # дата сверки рейтинга с первоисточником агентства; не сверял — не трогать")
        lines.append(f"    credit_quality: TODO_LLM_HIGH_MEDIUM_LOW")
    lines.append(f"    fundamental_score: TODO_LLM_HIGH_MEDIUM_LOW_RED_FLAG")
    lines.append(f"    fundamental_sources:")
    lines.append(f"      - url: TODO_LLM_url")
    lines.append(f"        label: TODO_LLM_short_label")
    lines.append(f"        accessed_date: {y_str(today_iso)}")
    lines.append(f"    catalyst:")
    lines.append(f"      # Для bond: минимум 1 catalyst (обычно redemption-related или rate_cut_capital_gain).")
    lines.append(f"      # Для HOLD_TO_MAT с погашением в горизонте 20 мес — id: redemption допустим.")
    lines.append(f"      - id: TODO_LLM_slug")
    lines.append(f"        trigger: TODO_LLM_free_text_event_or_milestone")
    lines.append(f"        date_window: TODO_LLM_YYYY-MM_or_YYYY-Qx_or_YYYY_or_range  # ОБЯЗАТЕЛЬНО (v2): consumer вычисляет горизонт из него")
    lines.append(f"        p: TODO_LLM_float_0_to_1_probability")
    lines.append(f"        upside_pct: TODO_LLM_float_or_null")
    lines.append(f"        upside_ci_pct: TODO_LLM_list_lo_hi_or_null")
    lines.append(f"        downside_pct: TODO_LLM_float_or_null")
    lines.append(f"        downside_ci_pct: TODO_LLM_list_lo_hi_or_null")
    lines.append(f"        source: TODO_LLM_url_or_advisor_estimate")
    lines.append(f"        source_quality: TODO_LLM_HIGH_MEDIUM_LOW")
    lines.append(f"        macro_dependency: TODO_LLM_A_B_C_D_or_null")
    lines.append(f"    advisor_verdict: TODO_LLM_BUY_ADD_HOLD_HOLD_TO_MAT_WATCH_TRIM_SELL")  # единый словарь (codelists verdict)
    lines.append(f"    advisor_verdict_confidence: TODO_LLM_float_0_to_1")
    lines.append(f"    confidence_basis: TODO_LLM_what_lowers_confidence_one_phrase_or_null")
    lines.append(f"    advisor_verdict_basis: TODO_LLM_2_to_5_lines_with_thesis")
    lines.append(f"    verification_priority: null  # ставит stamp-report save-to-library (R28), модель не заполняет")
    lines.append(f"    last_corp_event: null  # заполнить LLM если есть прошедшее событие")
    lines.append(f"    next_corp_event: null  # заполнить LLM если есть ближайшее")

    return lines


def build_stub(snapshot: dict[str, Any], today_iso: str, *, no_moex_fetch: bool = False,
               horizons: list[int] | None = None,
               primary_horizon: int = DEFAULT_PRIMARY_HORIZON,
               anchor_dates: list[str] | None = None,
               prior_ratings: dict[str, dict] | None = None) -> str:
    as_of = snapshot.get("as_of_date") or today_iso
    snapshot_id = f"portfolio-{as_of}.json"
    # Дата обзора — день прогона, а не снапшота (снапшот бывает на несколько дней старше: 26.10.2026
    # обзор шёл по снапшоту 23.10, модель правила review_date руками). Раньше снапшота — не бывает.
    review = max(today_iso[:10], str(as_of)[:10])
    if anchor_dates:
        # Якорный режим: горизонты выводятся из дат-целей (§11.6).
        horizons, h_ends = anchor_dates_to_horizons(review, anchor_dates)
        if primary_horizon not in horizons:
            primary_horizon = horizons[0]  # ближайшая цель
    else:
        horizons = horizons or list(DEFAULT_HORIZONS)
        if primary_horizon not in horizons:
            raise ValueError(
                f"primary_horizon={primary_horizon} не входит в horizons={horizons}"
            )
        h_ends = compute_horizon_ends(review, horizons)

    holdings = snapshot.get("holdings", [])

    # Filter: bond positions. ISIN может встречаться 2 раза (main + iis_3 split) —
    # мерджим по ticker (ISIN). on_iis: True если ВСЁ на IIS, False если всё на main,
    # отдельное поле iis_share_pct для split-кейса.
    bonds_by_isin: dict[str, dict[str, Any]] = {}
    for h in holdings:
        if h.get("asset_type") != "bond":
            continue
        if h.get("is_blocked"):
            continue
        isin = h.get("ticker")
        if not isin:
            continue
        if isin not in bonds_by_isin:
            # First occurrence — copy + initialize aggregates
            merged = dict(h)
            merged["qty_main"] = h["qty"] if h.get("account") == "main" else 0
            merged["qty_iis"] = h["qty"] if h.get("account") == "iis_3" else 0
            merged["value_rub_main"] = h["value_rub"] if h.get("account") == "main" else 0
            merged["value_rub_iis"] = h["value_rub"] if h.get("account") == "iis_3" else 0
            bonds_by_isin[isin] = merged
        else:
            # Merge: aggregate qty + value_rub
            existing = bonds_by_isin[isin]
            existing["qty"] = (existing.get("qty") or 0) + (h.get("qty") or 0)
            existing["value_rub"] = (existing.get("value_rub") or 0) + (h.get("value_rub") or 0)
            if h.get("account") == "main":
                existing["qty_main"] = (existing.get("qty_main") or 0) + (h.get("qty") or 0)
                existing["value_rub_main"] = (existing.get("value_rub_main") or 0) + (h.get("value_rub") or 0)
            elif h.get("account") == "iis_3":
                existing["qty_iis"] = (existing.get("qty_iis") or 0) + (h.get("qty") or 0)
                existing["value_rub_iis"] = (existing.get("value_rub_iis") or 0) + (h.get("value_rub") or 0)
    bonds = list(bonds_by_isin.values())
    bonds.sort(key=lambda h: h.get("value_rub") or 0, reverse=True)

    # MOEX batch fetch
    moex_map: dict[str, dict] = {}
    if not no_moex_fetch and bonds:
        isin_list = list({h["ticker"] for h in bonds})
        moex_map = fetch_moex_data(isin_list)

    # Aggregate values
    bs = snapshot.get("balance_summary", {}) or {}
    by_acc = bs.get("by_account", {}) or {}
    main = by_acc.get("main", {}) or {}
    iis = by_acc.get("iis_3", {}) or {}
    total_excl_iis = bs.get("total_current_rub_excl_iis") or main.get("total_rub") or 0
    main_bonds_rub = main.get("bonds_rub") or 0
    iis_bonds_rub = iis.get("bonds_rub") or 0
    bonds_total_rub = main_bonds_rub + iis_bonds_rub
    cash_main_rub = main.get("cash_rub") or 0
    target_bond_share_pct = None
    for g in (bs.get("goals_overall") or []):
        if g.get("Тип") in ("Облигация", "Облигации", "Bonds"):
            target_bond_share_pct = round((g.get("Доля") or 0) * 100, 2)
            break
    bond_share_pct = (main_bonds_rub / total_excl_iis * 100) if total_excl_iis else None
    # positions_on_iis: count позиций, у которых есть iis-доля (qty_iis > 0)
    positions_on_iis = sum(1 for h in bonds if (h.get("qty_iis") or 0) > 0)
    positions_reviewed = len(bonds)  # уникальные ISIN (после deduplicate)
    # position_lines: исходное число holdings entries (включая split)
    position_lines = sum(
        1 for h in holdings
        if h.get("asset_type") == "bond" and not h.get("is_blocked") and h.get("ticker")
    )

    out: list[str] = []
    out.append(f"# weekly-review-bond-{review}.yaml")
    out.append(f"# Generated by build_weekly_bond_stub.py from {snapshot_id}.")
    out.append(f"# LLM должна заменить TODO_LLM плейсхолдеры. Имена полей фиксированы.")
    out.append(f"# Validator save-to-library (validate-weekly-review-bond) блокирует TODO_LLM.")
    out.append("")
    out.append("schema_version: 2")
    out.append("type: weekly-bonds-review")
    out.append(f"review_date: {y_str(review)}")
    # v2 (Phase 4): multiple horizons — horizon_ends детерминированы от review_date.
    # horizon_months / horizon (v1) удалены.
    out.append(f"horizons: [{', '.join(str(h) for h in horizons)}]")
    out.append("horizon_ends:")
    for h in horizons:
        out.append(f"  h{h}: {y_str(h_ends[f'h{h}'])}")
    out.append(f"primary_horizon: {primary_horizon}  # advisor_verdict привязан к нему")
    out.append(f"horizon_mode: {'anchored' if anchor_dates else 'rolling'}  # rolling=скользящий (default), anchored=якорный (--anchor-dates)")
    out.append(f"snapshot_id: {y_str(snapshot_id)}")
    out.append(f"snapshot_date: {y_str(as_of)}")
    out.append('advisor_version: "ru-portfolio-advisor@2.x"')
    out.append("producer: TODO_LLM_model_name")
    out.append("macro_source: TODO_LLM_macro_marginal_filename_or_null")
    out.append("")
    out.append("# === Summary (числа из snapshot, детерминировано) ===")
    out.append("summary:")
    out.append(f"  positions_reviewed: {y_num(positions_reviewed, 0)}")
    out.append(f"  position_lines: {y_num(position_lines, 0)}")
    out.append(f"  positions_on_iis: {y_num(positions_on_iis, 0)}")
    out.append(f"  bonds_total_rub: {y_num(bonds_total_rub, 2)}")
    out.append(f"  total_value_rub: {y_num(bonds_total_rub, 2)}  # canonical alias для bonds_total_rub")
    out.append(f"  main_bonds_rub: {y_num(main_bonds_rub, 2)}")
    out.append(f"  iis_bonds_rub: {y_num(iis_bonds_rub, 2)}")
    out.append(f"  total_portfolio_rub_excl_iis: {y_num(total_excl_iis, 2)}")
    out.append(f"  bond_share_pct: {y_num(bond_share_pct, 2)}")
    out.append(f"  target_share_pct: {y_num(target_bond_share_pct, 2)}")
    if bond_share_pct is not None and target_bond_share_pct is not None:
        out.append(f"  share_delta_pct: {y_num(bond_share_pct - target_bond_share_pct, 2)}")
        deficit = round((target_bond_share_pct - bond_share_pct) / 100 * total_excl_iis, 2) \
            if total_excl_iis else None
        out.append(f"  bond_deficit_rub: {y_num(deficit, 2)}")
    else:
        out.append(f"  share_delta_pct: null")
        out.append(f"  bond_deficit_rub: null")
    out.append(f"  cash_main_rub: {y_num(cash_main_rub, 2)}")
    out.append(f"  cash_share_pct: {y_num(cash_main_rub / total_excl_iis * 100 if total_excl_iis else None, 2)}")

    # Взвешенные агрегаты — арифметика по уже собранным полям (см.
    # compute_summary_aggregates). Модели остаются только ci_pct и
    # by_credit_quality_pct (нужны кредитные рейтинги).
    agg = compute_summary_aggregates(bonds, moex_map, bonds_total_rub or 0.0)
    out.append(f"  weighted_ytm_pct:")
    out.append(f"    value: {y_num(agg['weighted_ytm_pct'], 4)}  # покрытие "
               f"{agg['weighted_ytm_coverage_pct']}% корзины по весу")
    out.append(f"    ci_pct: TODO_LLM_list_lo_hi  # оценка неопределённости — за LLM")
    out.append(f"  weighted_duration_days: {y_num(agg['weighted_duration_days'], 0)}"
               f"  # покрытие {agg['weighted_duration_coverage_pct']}%")
    agg_main = compute_summary_aggregates(bonds, moex_map, bonds_total_rub or 0.0,
                                          value_key="value_rub_main")
    out.append(f"  weighted_ytm_pct_main_only: {y_num(agg_main['weighted_ytm_pct'], 4)}")
    out.append(f"  weighted_duration_days_main_only: {y_num(agg_main['weighted_duration_days'], 0)}")
    out.append(f"  # ВАЖНО: сравнивать между собой только числа ОДНОГО среза, и называть")
    out.append(f"  # срез в любой прозе про них. Прецедент 15.08: MD считал по main,")
    out.append(f"  # YAML — по всей корзине, а basis внутри YAML ссылался на третье число.")
    out.append(f"  # Ключи без суффикса ниже — по всей корзине, с _main_only — без ИИС-3.")
    out.append(f"  # по-валютные срезы (считаются по nominal_currency позиций):")
    for cur, vals in sorted(agg["per_currency"].items()):
        suffix = cur.lower()
        main_vals = agg_main["per_currency"].get(cur, {})
        out.append(f"  weighted_ytm_{suffix}_pct: {y_num(vals['ytm_pct'], 4)}")
        out.append(f"  weighted_duration_{suffix}_days: {y_num(vals['duration_days'], 0)}")
        out.append(f"  share_{suffix}_pct: {y_num(vals['share_pct'], 4)}")
        out.append(f"  weighted_ytm_{suffix}_pct_main_only: {y_num(main_vals.get('ytm_pct'), 4)}")
        out.append(f"  weighted_duration_{suffix}_days_main_only: {y_num(main_vals.get('duration_days'), 0)}")
    out.append(f"  by_type_pct:")
    for k, v in agg["by_type_pct"].items():
        out.append(f"    {k}: {y_num(v, 4)}")
    out.append(f"  by_plan_bucket_pct:  # доля по plan_bucket_key (9 корзин «План по Облигациям», RPA-13)")
    for k, v in agg["by_plan_bucket_pct"].items():
        out.append(f"    {y_str(k)}: {y_num(v, 4)}")
    out.append(f"  by_credit_quality_pct: TODO_LLM_dict_HIGH_MEDIUM_LOW  # нужны рейтинги — за LLM")
    out.append(f"  maturity_ladder_pct:")
    for k, v in agg["maturity_ladder_pct"].items():
        out.append(f"    '{k}': {y_num(v, 4)}")

    # Returns (snapshot)
    returns_obj = snapshot.get("returns") or {}
    by_type = returns_obj.get("by_type") or {}
    bond_ret = by_type.get("bond") or {}
    out.append("  returns:")
    out.append(f"    bond_xirr: {y_num(bond_ret.get('xirr'), 4)}")
    out.append(f"    bond_roi: {y_num(bond_ret.get('roi'), 4)}")
    out.append(f"    bond_pnl_rub: {y_num(bond_ret.get('pnl_rub'), 2)}")
    out.append("")
    out.append(f"# === per_bond: {len(bonds)} active bond position(s). ===")
    out.append("# Сортировка по value_rub desc для удобства чтения. Имена ключей —")
    out.append("# каноническая схема (yaml-schemas.md §7b). НЕ переименовывать.")
    out.append("per_bond:")
    out.append("")
    for h in bonds:
        isin = h["ticker"]
        out.extend(build_per_bond_entry(
            isin=isin,
            holding=h,
            moex_data=moex_map.get(isin),
            total_excl_iis=total_excl_iis,
            bonds_total_rub=bonds_total_rub,
            today_iso=today_iso,
            prior_rating=(prior_ratings or {}).get(isin),
        ))
        out.append("")

    out.append("# === Risks / caveats / sources — LLM ===")
    out.append("key_risks:")
    out.append("  - id: TODO_LLM_slug")
    out.append("    severity: TODO_LLM_HIGH_MEDIUM_LOW")
    out.append("    note: TODO_LLM_short_description")
    out.append("")
    out.append("caveats:")
    out.append("  - severity: TODO_LLM_HIGH_MEDIUM_LOW")
    out.append("    message: TODO_LLM_text")
    out.append("")
    out.append("sources:")
    out.append(f"  snapshot: {y_str(f'Portfolio/snapshots/{snapshot_id}')}")
    out.append(f"  moex_iss: {y_str(f'MOEX ISS API, {as_of}')}")
    out.append("  macro_input: TODO_LLM_filename_or_null")

    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--today", default=None)
    parser.add_argument("--no-moex-fetch", action="store_true",
                        help="Skip MOEX ISS API calls (for offline tests)")
    parser.add_argument("--horizons", default=None,
                        help="Скользящий режим: список горизонтов в месяцах через запятую (default: 6,12,24)")
    parser.add_argument("--anchor-dates", default=None,
                        help="Якорный режим (§11.6): даты-цели через запятую (YYYY-MM-DD). "
                             "Переопределяет --horizons: N вычисляется как месяцы до цели.")
    parser.add_argument("--prior-review", default=None, type=Path,
                        help="Прошлый обзор облигаций (yaml): из него переносится per_bond[ISIN].rating. "
                             "Нет флага — последний weekly-review-bond-*.yaml рядом со снапшотом (../weekly-reviews), "
                             "строго раньше даты обзора.")
    parser.add_argument("--primary-horizon", type=int, default=DEFAULT_PRIMARY_HORIZON,
                        help="Горизонт, к которому привязан advisor_verdict (default: 12)")
    args = parser.parse_args()

    snapshot = load_snapshot(args.snapshot)
    today_iso = args.today or date_t.today().isoformat()
    anchor = parse_anchor_dates(args.anchor_dates)
    horizons = None if anchor else parse_horizons(args.horizons)
    prior_path = args.prior_review or find_prior_review(args.snapshot, today_iso)
    stub = build_stub(snapshot, today_iso=today_iso, no_moex_fetch=args.no_moex_fetch,
                      horizons=horizons, primary_horizon=args.primary_horizon,
                      anchor_dates=anchor, prior_ratings=load_prior_ratings(prior_path))

    args.output.write_text(stub, encoding="utf-8")
    bond_isins = set()
    bond_lines = 0
    for h in snapshot.get("holdings", []):
        if h.get("asset_type") == "bond" and not h.get("is_blocked") and h.get("ticker"):
            bond_isins.add(h["ticker"])
            bond_lines += 1
    summary = {
        "output": str(args.output),
        "snapshot": str(args.snapshot),
        "snapshot_date": snapshot.get("as_of_date"),
        "bonds_unique_isin": len(bond_isins),
        "bonds_position_lines": bond_lines,
        "moex_fetched": not args.no_moex_fetch and MOEX_AVAILABLE,
    }
    sys.stdout.write(json.dumps(summary, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
