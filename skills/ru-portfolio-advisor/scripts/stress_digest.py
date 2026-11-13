#!/usr/bin/env python3
"""
stress_digest.py

Детерминированное чтение stress-файла для режимов 3 (Rebalance Opinion) и 8 (Stock
Quality Forward Review). Снимает с LLM четыре шага, на которых она дрейфует:

  1. поиск свежего `Portfolio/stress/stress-*.yaml` и арифметику возраста + вердикт
     свежести по режиму (лестницы у режимов разные, см. `references/stress-reading.md`);
  2. длину горизонта. Стрессы идут в режиме `horizon_mode: anchored`: ключи h6/h12/h24 —
     конвенция цепочки, а не месяцы. Якорь h12 = 30.06.2027 отстоит от 15.08.2026 на
     ~10,5 мес, поэтому дивиденды и купоны масштабируются множителем 0,87, а не 1,0
     (и h24 — 1,88, а не 2,0);
  3. выемку `expected_pct_pweighted` / `tail_var_pct` по 20+ акциям из YAML на сотни
     килобайт и взвешивание по реальным долям — строка «Stress macro EV» TR-таблицы
     `rebalance-framework.md` §6.2;
  4. bond-сторону той же таблицы: `bond_carry` уже посчитан скриптом стресса по каждому
     held-ISIN (купоны + pull-to-par + fx + reinvest, взвешено по сценариям, с CI).
     Руками пересчитывать held-бумаги незачем — руками считаются только кандидаты,
     которых в портфеле нет.

Плюс сверка поколения: стресс собран на конкретный снапшот (`portfolio_snapshot_id`),
и если Mode 3 идёт на более свежем — веса разъехались, об этом надо сказать в отчёте.

Скрипт строго read-only: ничего не пишет на диск, вся выдача — в stdout.

CLI:
    python3 stress_digest.py [--stress auto|<путь>] [--stress-dir <dir>] \\
        [--snapshot <portfolio-<date>.json>] [--mode 3|8] [--as-of YYYY-MM-DD] \\
        [--horizons h12,h24] [--primary h12] [--top 10] \\
        [--tr-stocks <%>] [--tr-bonds <%>] [--horizons-file <horizons.json>] [--json | --text]

    # режим линта черновика перед эмиссией:
    python3 stress_digest.py --lint-draft <файл с черновиком>

Exit codes: 0 — успех (в том числе с предупреждением о свежести) и чистый линт;
1 — вердикт блокирующий (Mode 8 при стрессе старше 60 дней) либо линт нашёл нарушения;
2 — ошибка входа без traceback.

Требует PyYAML (stress-артефакты — YAML). Снапшот опционален: без него считается
только шапка и таблица горизонтов, взвешивать EV не по чему.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any

# ─────────────────────────── константы ───────────────────────────

DEFAULT_STRESS_DIR = os.path.expanduser(
    "~/Library/CloudStorage/SynologyDrive-home/Claude-Memory/Portfolio/stress"
)

# Лестница свежести (владелец, 20.08.2026). Mode 8 без актуального макро-фильтра
# отказывается работать; Mode 3 деградирует — откладывается только L1-redirect (§6.3),
# остальной режим (диф IE, тайминг продаж, база докупки) стресса не требует.
STALE_WARN_DAYS = 30
STALE_HARD_DAYS = 60

# Money-market фонды лежат в снапшоте как asset_type == "stock", но акционной книгой
# не являются. Близнецы этой константы — gate_aware_sizing.py и build_weekly_stock_stub.py;
# test_stress_digest.py сверяет все три множества.
MONEY_MARKET_TICKERS = {"TMON", "TPAY", "LQDT", "SBMM"}

# Таблица пропорций L1-redirect по спреду TR (rebalance-framework.md §6.2).
# Границы включаются в нижнюю корзину: 10 → «внутри акций», 20 → «50/50», 35 → «70/30».
REDIRECT_TABLE: list[tuple[float | None, str, str]] = [
    (10.0, "buffer внутри акций", "спред узок — дивиденды и idio-катализаторы перекрывают bond carry"),
    (20.0, "50/50 акции/облигации", "смешанный сигнал, hedge"),
    (35.0, "70/30 облигации/акции", "структурный bond bias, idio-carve-outs только HIGH-conviction"),
    (None, "90/10 облигации/акции", "сильный структурный bond bias, тактический выход из акций"),
]

DAYS_PER_MONTH = 365.25 / 12.0

# --lint-draft: признаки того, что черновик опирается на стресс. Ровно две проверки,
# симметрично gate_aware_sizing.py: провенанс и литеральный множитель горизонта.
_STRESS_USE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"stress\s*macro\s*ev", re.IGNORECASE), "строка «Stress macro EV»"),
    (re.compile(r"bond\s*carry", re.IGNORECASE), "bond carry"),
    (re.compile(r"спред\s+tr", re.IGNORECASE), "спред TR"),
    (re.compile(r"пропорц\w*\s+redirect", re.IGNORECASE), "пропорция redirect"),
    (re.compile(r"макро-срез", re.IGNORECASE), "макро-срез"),
    (re.compile(r"tr_stocks|tr_bonds", re.IGNORECASE), "итоги TR-таблицы"),
]

# Провенанс: имя артефакта (stress-YYYY-MM-DD-…) либо строка «стресс … дд.мм.гггг».
_PROVENANCE_PATTERNS: list[re.Pattern] = [
    re.compile(r"stress-\d{4}-\d{2}-\d{2}"),
    re.compile(r"стресс\w*[^\n]{0,80}\d{2}\.\d{2}\.\d{4}", re.IGNORECASE),
]

# Литеральный множитель горизонта — горизонты якорные, hNN не равен числу месяцев.
_LITERAL_FACTOR_RE = re.compile(r"[×xX*]\s*(6|12|24)\s*/\s*12")


# Файл сроков сайта (scenarios/horizons.json, horizons@1): правила валидности те же, что у сайта и stress_build.
HORIZONS_FILE_REL = os.path.join("..", "..", "scenarios", "horizons.json")  # от папки стрессов
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def horizons_file_errors(doc: Any) -> list[str]:
    """Причины невалидности файла сроков (пусто — валиден)."""
    if not isinstance(doc, dict):
        return ["ожидался объект"]
    errs: list[str] = []
    if doc.get("schema") != "horizons@1":
        errs.append(f"schema {doc.get('schema')!r}, нужен 'horizons@1'")
    he = doc.get("horizon_ends")
    if not isinstance(he, dict) or not 1 <= len(he) <= 6:
        return errs + ["horizon_ends: нужен объект из 1-6 сроков"]
    rows = []
    for k, v in he.items():
        m = re.fullmatch(r"h(\d+)", str(k))
        if not m or int(m.group(1)) <= 0:
            errs.append(f"horizon_ends: ключ {k!r} не вида hN")
            continue
        try:
            if not (isinstance(v, str) and _ISO_DATE_RE.match(v)):
                raise ValueError
            date.fromisoformat(v)
        except ValueError:
            errs.append(f"horizon_ends.{k}: {v!r} не дата ГГГГ-ММ-ДД")
            continue
        rows.append((int(m.group(1)), v, k))
    rows.sort()
    for a, b in zip(rows, rows[1:]):
        if not b[1] > a[1]:
            errs.append(f"horizon_ends: дата {b[2]} не позже {a[2]}")
    ph = doc.get("primary_horizon")
    if isinstance(ph, bool) or not isinstance(ph, int) or f"h{ph}" not in he:
        errs.append(f"primary_horizon {ph!r}: нужен номер одного из сроков")
    return errs


def read_site_terms(path: str | None) -> tuple[dict[str, Any] | None, str | None]:
    """(файл сроков | None, причина невалидности | None). Нет файла — (None, None)."""
    if not path or not os.path.isfile(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError) as exc:
        return None, f"не читается: {exc}"
    errs = horizons_file_errors(doc)
    return (None, "; ".join(errs)) if errs else (doc, None)


def _terms_str(ends: dict[str, Any]) -> str:
    return ", ".join(f"{k} {str(v)[:10]}" for k, v in sorted(ends.items(), key=lambda kv: int(str(kv[0])[1:])
                                                             if re.fullmatch(r"h\d+", str(kv[0])) else 0))


def _ru_date_from_iso(value: Any) -> str:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(value or ""))
    return f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else str(value or "?")


def terms_check(stress: dict[str, Any], site: dict[str, Any] | None) -> tuple[dict[str, Any], str | None]:
    """({stress, site, match}, предупреждение | None). Сравниваются метки и даты; основной срок не входит."""
    he = stress.get("horizon_ends")
    st = {str(k): str(v)[:10] for k, v in he.items()} if isinstance(he, dict) else {}
    if site is None:
        return {"stress": st, "site": None, "match": None}, None
    sd_ = {k: v for k, v in site["horizon_ends"].items()}
    info = {"stress": st, "site": {"horizon_ends": sd_, "primary_horizon": site.get("primary_horizon"),
                                    "set_at": site.get("set_at")}, "match": st == sd_}
    if info["match"]:
        return info, None
    return info, (f"stress_terms_mismatch: стресс посчитан на сроки {_terms_str(st)}, действующие сроки "
                  f"{_terms_str(sd_)} (заданы на сайте {_ru_date_from_iso(site.get('set_at'))}) — "
                  "числа стресса относятся к прежним срокам")


class StressDigestError(Exception):
    """Понятная ошибка входа/данных — CLI ловит и завершается exit 2 без traceback."""


# ─────────────────────────── загрузка входов ───────────────────────────

def find_latest_stress(stress_dir: str) -> str:
    """Самый свежий stress-*.yaml: поле `date` внутри файла → время записи файла → имя.

    Первой идёт дата из файла, а не имя или время записи: имена несут сценарий
    (`stress-2026-08-15-geopol-...`), а время записи старого файла меняет любая его
    перезапись. Время записи решает только между файлами одной даты — второй прогон
    за день новее первого при любом имени (то же правило у сайта и вьюера).
    """
    if not os.path.isdir(stress_dir):
        raise StressDigestError(
            f"Каталог стрессов не найден: {stress_dir!r}. Проверь доступ к Synology "
            "(транспорт единственный) или укажи --stress явным путём."
        )
    candidates = sorted(glob.glob(os.path.join(stress_dir, "stress-*.yaml")))
    if not candidates:
        raise StressDigestError(f"В {stress_dir!r} нет ни одного stress-*.yaml")
    dated: list[tuple[str, float, str]] = []
    for path in candidates:
        head = _read_head_date(path)
        if head:
            try:
                written = os.path.getmtime(path)
            except OSError:
                written = 0.0
            dated.append((head, written, path))
    if not dated:
        raise StressDigestError(f"Ни в одном stress-*.yaml из {stress_dir!r} не читается поле date")
    dated.sort()
    return dated[-1][2]


def find_recalc(stress_path: str) -> dict[str, Any] | None:
    """Пересчёт сайта для выбранного стресса скилла: `<папка>/auto/recalc-<имя стресса>`.

    Берётся, только если файл читается, в нём есть блок `recalc`, `recalc.source_stress`
    равен имени выбранного стресса и пересчёт сделан не раньше последней записи файла
    стресса (стресс, заменённый под тем же именем, оставляет пересчёт прежней версии).
    Нет файла -> None (молча). Битый/не тот/устаревший -> словарь с `warning` и без
    `path`: числа остаются из стресса скилла.
    То же правило в skills/portfolio-coherence-audit/scripts/build_coherence_bundle.py.
    """
    name = os.path.basename(stress_path)
    path = os.path.join(os.path.dirname(stress_path), "auto", "recalc-" + name)
    if not os.path.isfile(path):
        return None
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as exc:  # noqa: BLE001 — любой сбой чтения = не берём пересчёт
        return {"warning": f"stress_recalc_skipped:файл {os.path.basename(path)} не читается ({exc})"}
    rc = data.get("recalc") if isinstance(data, dict) else None
    if not isinstance(rc, dict):
        return {"warning": f"stress_recalc_skipped:в {os.path.basename(path)} нет блока recalc"}
    if rc.get("source_stress") != name:
        return {"warning": f"stress_recalc_skipped:recalc.source_stress={rc.get('source_stress')!r} "
                           f"не равен выбранному стрессу {name!r}"}
    if recalc_older_than_stress(rc, stress_path):
        return {"warning": f"stress_recalc_skipped:пересчёт от {rc.get('at')} сделан до последней записи "
                           f"файла стресса {name!r} — он от прежней версии; числа из стресса скилла"}
    return {"path": path}


def recalc_older_than_stress(rc: dict[str, Any], stress_path: str) -> bool:
    """Пересчёт (`recalc.at`) сделан раньше последней записи файла стресса — с точностью до секунды.

    Времени пересчёта нет или оно не читается -> False: не судим, пересчёт берётся как раньше.
    Время без пояса считается московским (так его пишет сайт).
    """
    at = rc.get("at")
    try:
        t = at if isinstance(at, datetime) else datetime.fromisoformat(str(at))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone(timedelta(hours=3)))
        return t.timestamp() < int(os.path.getmtime(stress_path))
    except (TypeError, ValueError, OSError):
        return False


def recalc_info(rc: dict[str, Any], judgments_date: str | None) -> dict[str, Any]:
    """Сведения о пересчёте для вывода (те же ключи в build_coherence_bundle.py)."""
    src = str(rc.get("source_stress"))
    return {
        "source_stress": src,
        "judgments_date": judgments_date,
        "snapshot_id": rc.get("snapshot_id"),
        "source_snapshot_id": rc.get("source_snapshot_id"),
        "at": rc.get("at"),
        "reason": rc.get("reason"),
        "narrative_stale": bool(rc.get("narrative_stale")),
        "message": (f"числа стресса — пересчёт сайта от {rc.get('at')} на снапшоте {rc.get('snapshot_id')}; "
                    f"суждения — {src}" + (f" от {judgments_date}" if judgments_date else "")),
    }


def _read_head_date(path: str) -> str | None:
    """Достаёт `date:` из шапки, не парся весь файл (стрессы — сотни килобайт)."""
    try:
        with open(path, encoding="utf-8") as f:
            for _ in range(40):
                line = f.readline()
                if not line:
                    break
                if line.startswith("date:"):
                    return line.split(":", 1)[1].strip().strip("'\"")
    except OSError:
        return None
    return None


def load_stress(path: str) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        raise StressDigestError(
            "Нужен PyYAML: pip install pyyaml --break-system-packages "
            "(stress-артефакты — YAML, обходного пути нет)"
        )
    if not os.path.exists(path):
        raise StressDigestError(f"Stress-файл не найден: {path!r}")
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        raise StressDigestError(f"Не удалось прочитать/распарсить стресс {path!r}: {exc}")
    if not isinstance(data, dict):
        raise StressDigestError(f"Стресс {path!r} не разобрался в объект")
    schema = data.get("schema_version")
    if schema != 2:
        raise StressDigestError(
            f"Стресс {os.path.basename(path)} имеет schema_version={schema!r}, а не 2. "
            "После V2-CUTOVER (2026-08-03) библиотека целиком schema 2 — перегенерируй "
            "через macro-forecast-chain → portfolio-scenario-stress."
        )
    return data


def load_snapshot(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        raise StressDigestError(f"Снапшот не найден: {path!r}")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise StressDigestError(f"Не удалось прочитать/распарсить снапшот {path!r}: {exc}")


def _parse_date(value: Any, field: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError:
            pass
    raise StressDigestError(f"Не разобрал дату в поле {field}: {value!r} (ожидается YYYY-MM-DD)")


# ─────────────────────────── свежесть ───────────────────────────

def freshness_verdict(age_days: int, mode: int) -> dict[str, Any]:
    """Вердикт по лестнице режима. Mode 3 деградирует, Mode 8 отказывается."""
    if mode == 8:
        if age_days > STALE_HARD_DAYS:
            return {"code": "refuse", "blocking": True,
                    "text": f"Стресс старше {STALE_HARD_DAYS} дней ({age_days} дн) — Mode 8 без "
                            "актуального макро-фильтра даёт ненадёжный verdict. Запусти "
                            "macro-forecast-chain → portfolio-scenario-stress и обратись снова."}
        if age_days > STALE_WARN_DAYS:
            return {"code": "confirm_required", "blocking": False,
                    "text": f"Стресс устарел на {age_days} дн — нужен явный ответ пользователя "
                            "«продолжать ли с устаревшим». Макро-overlay может не отражать "
                            "текущую ставку ЦБ; verdict по macro-фактору — pending refresh."}
        return {"code": "fresh", "blocking": False, "text": f"Стресс свежий ({age_days} дн)."}
    if age_days > STALE_HARD_DAYS:
        return {"code": "defer_redirect", "blocking": False,
                "text": f"Стресс старше {STALE_HARD_DAYS} дней ({age_days} дн) — L1-redirect "
                        "откладывается по §6.3: buffer остаётся внутри акций с минимальными "
                        "движениями по priority queue. Остальной Mode 3 (диф IE, тайминг продаж, "
                        "база докупки) выполняется полностью — стресс им не нужен."}
    if age_days > STALE_WARN_DAYS:
        return {"code": "warn", "blocking": False,
                "text": f"Стресс устарел на {age_days} дн — TR-таблица считается, но пропорция "
                        "redirect помечается «проверить после refresh стресса»."}
    return {"code": "fresh", "blocking": False, "text": f"Стресс свежий ({age_days} дн)."}


def absent_verdict(mode: int) -> dict[str, Any]:
    if mode == 8:
        return {"code": "absent_continue_noted", "blocking": False,
                "text": "Stress-файла нет — Mode 8 продолжается без него, но в ответе явно "
                        "отмечается, что macro ΔP&L недоступен."}
    return {"code": "absent_defer_redirect", "blocking": False,
            "text": "Stress-файла нет — L1-redirect откладывается по §6.3, buffer остаётся "
                    "внутри акций. Остальной Mode 3 выполняется полностью."}


# ─────────────────────────── горизонты ───────────────────────────

def build_horizons(stress: dict[str, Any], as_of: date, keys: list[str]) -> list[dict[str, Any]]:
    """Таблица «ключ → якорь → реальные месяцы → множитель» для дивидендов и купонов.

    Множитель считается от даты стресса: macro EV описывает окно «дата стресса → якорь»,
    и дивиденды в TR-таблице должны идти по тому же окну. Отставание отчёта от стресса
    видно отдельной колонкой и лечится лестницей свежести, а не подгонкой множителя.
    """
    stress_date = _parse_date(stress.get("date"), "date")
    ends = stress.get("horizon_ends") or {}
    if not isinstance(ends, dict) or not ends:
        raise StressDigestError("В стрессе нет horizon_ends — это SSOT длины горизонта, "
                                "подставлять литеральные 12/24 месяца нельзя")
    out = []
    for key in keys:
        if key not in ends:
            raise StressDigestError(
                f"Горизонта {key!r} нет в horizon_ends ({', '.join(sorted(ends))}) — "
                "не подставляю соседний срез"
            )
        end = _parse_date(ends[key], f"horizon_ends.{key}")
        months = (end - stress_date).days / DAYS_PER_MONTH
        out.append({
            "key": key,
            "end": end.isoformat(),
            "months_from_stress": round(months, 2),
            "months_from_as_of": round((end - as_of).days / DAYS_PER_MONTH, 2),
            "scale_factor": round(months / 12.0, 4),
            "literal_factor": round(int(key[1:]) / 12.0, 4),
        })
    return out


# ─────────────────────────── акции ───────────────────────────

def active_stock_holdings(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    holdings = snapshot.get("holdings")
    if not isinstance(holdings, list):
        raise StressDigestError("В снапшоте нет списка holdings — проверь путь/версию снапшота")
    out = []
    for h in holdings:
        if not isinstance(h, dict) or h.get("asset_type") != "stock":
            continue
        if h.get("current_price_source") == "cost_basis":
            continue
        if h.get("is_blocked"):
            continue
        if h.get("ticker") in MONEY_MARKET_TICKERS:
            continue
        out.append(h)
    return out


def _weight_map(snapshot: dict[str, Any], holdings: list[dict[str, Any]]) -> tuple[dict[str, float], str]:
    """Доли L2 внутри акционной книги. Primary — ie_actual.per_ticker[t].real_share_pct."""
    per_ticker = (snapshot.get("ie_actual") or {}).get("per_ticker") or {}
    shares = {}
    for h in holdings:
        rec = per_ticker.get(h.get("ticker"))
        val = rec.get("real_share_pct") if isinstance(rec, dict) else None
        if isinstance(val, (int, float)):
            shares[h["ticker"]] = float(val)
    if len(shares) == len(holdings) and sum(shares.values()) > 0:
        return shares, "ie_actual.real_share_pct"
    total = sum(float(h.get("value_rub") or 0.0) for h in holdings)
    if total <= 0:
        raise StressDigestError("Суммарная стоимость акционной книги нулевая — нечего взвешивать")
    return {h["ticker"]: float(h.get("value_rub") or 0.0) / total * 100 for h in holdings}, "value_rub"


def stocks_side(stress: dict[str, Any], snapshot: dict[str, Any],
                horizons: list[str], top_n: int) -> dict[str, Any]:
    holdings = active_stock_holdings(snapshot)
    weights, weight_source = _weight_map(snapshot, holdings)
    per_position = stress.get("per_position") or {}

    covered, uncovered = [], []
    for h in holdings:
        ticker = h["ticker"]
        rec = per_position.get(ticker)
        if not isinstance(rec, dict) or not isinstance(rec.get("by_horizon"), dict):
            uncovered.append({"ticker": ticker, "weight_pct": weights.get(ticker, 0.0)})
            continue
        row: dict[str, Any] = {"ticker": ticker, "weight_pct": weights.get(ticker, 0.0), "by_horizon": {}}
        for key in horizons:
            slice_ = rec["by_horizon"].get(key)
            if not isinstance(slice_, dict):
                row["by_horizon"][key] = None
                continue
            ev = (slice_.get("expected_pct_pweighted") or {})
            row["by_horizon"][key] = {
                "ev_pct": ev.get("value"),
                "ev_ci_pct": ev.get("ci_pct"),
                "tail_var_pct": slice_.get("tail_var_pct"),
                "tail_var_scenario_id": slice_.get("tail_var_scenario_id"),
            }
        covered.append(row)

    covered.sort(key=lambda r: -r["weight_pct"])
    top = covered[:top_n]

    return {
        "weight_source": weight_source,
        "positions": covered,
        "top_n": top_n,
        "top_tickers": [r["ticker"] for r in top],
        "uncovered": uncovered,
        "uncovered_weight_pct": round(sum(u["weight_pct"] for u in uncovered), 2),
        "weighted_ev_pct": {key: _weighted(covered, key) for key in horizons},
        "weighted_ev_top_pct": {key: _weighted(top, key) for key in horizons},
        "worst_tail": {key: _worst_tail(covered, key) for key in horizons},
    }


def _weighted(rows: list[dict[str, Any]], key: str) -> float | None:
    """Взвешенный EV с ренормировкой на покрытые бумаги — иначе непокрытые молча
    занижают результат, как если бы их EV был нулевым."""
    num = den = 0.0
    for r in rows:
        slice_ = (r.get("by_horizon") or {}).get(key)
        if not slice_ or not isinstance(slice_.get("ev_pct"), (int, float)):
            continue
        num += r["weight_pct"] * float(slice_["ev_pct"])
        den += r["weight_pct"]
    return round(num / den, 2) if den > 0 else None


def _worst_tail(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    worst = None
    for r in rows:
        slice_ = (r.get("by_horizon") or {}).get(key)
        if not slice_ or not isinstance(slice_.get("tail_var_pct"), (int, float)):
            continue
        if worst is None or slice_["tail_var_pct"] < worst["tail_var_pct"]:
            worst = {"ticker": r["ticker"], "tail_var_pct": slice_["tail_var_pct"],
                     "scenario_id": slice_.get("tail_var_scenario_id")}
    return worst


# ─────────────────────────── облигации ───────────────────────────

def bonds_side(stress: dict[str, Any], snapshot: dict[str, Any], horizons: list[str]) -> dict[str, Any]:
    """Bond-сторона §6.2 по held-бумагам — из готового блока bond_carry стресса."""
    carry_block = stress.get("bond_carry") or {}
    carry = carry_block.get("per_position") or {}
    holdings = [h for h in (snapshot.get("holdings") or [])
                if isinstance(h, dict) and h.get("asset_type") == "bond" and not h.get("is_blocked")]
    total = sum(float(h.get("value_rub") or 0.0) for h in holdings)
    if total <= 0:
        return {"available": False, "reason": "в снапшоте нет незаблокированных облигаций",
                "positions": [], "uncovered": [], "weighted_carry_pct": {}}

    covered, uncovered = [], []
    for h in holdings:
        key_isin = h.get("isin") or h.get("ticker")
        weight = float(h.get("value_rub") or 0.0) / total * 100
        rec = carry.get(key_isin)
        if not isinstance(rec, dict) or not isinstance(rec.get("by_horizon"), dict):
            uncovered.append({"isin": key_isin, "name": h.get("name"), "weight_pct": round(weight, 2)})
            continue
        row: dict[str, Any] = {"isin": key_isin, "name": h.get("name"), "weight_pct": weight,
                               "by_horizon": {}, "flags": rec.get("flags") or []}
        for hk in horizons:
            slice_ = rec["by_horizon"].get(hk)
            if not isinstance(slice_, dict):
                row["by_horizon"][hk] = None
                continue
            row["by_horizon"][hk] = {
                "carry_pct": slice_.get("expected_carry_pct"),
                "t_live_months": slice_.get("t_live_months"),
                "matures_within": slice_.get("matures_within"),
            }
        covered.append(row)

    covered.sort(key=lambda r: -r["weight_pct"])
    weighted = {}
    for hk in horizons:
        num = den = 0.0
        for r in covered:
            slice_ = r["by_horizon"].get(hk)
            if not slice_ or not isinstance(slice_.get("carry_pct"), (int, float)):
                continue
            num += r["weight_pct"] * float(slice_["carry_pct"])
            den += r["weight_pct"]
        weighted[hk] = round(num / den, 2) if den > 0 else None

    return {
        "available": True,
        "as_of": carry_block.get("as_of"),
        "baseline_cbr_rate_pct": carry_block.get("baseline_cbr_rate_pct"),
        "positions": covered,
        "uncovered": uncovered,
        "uncovered_weight_pct": round(sum(u["weight_pct"] for u in uncovered), 2),
        "weighted_carry_pct": weighted,
    }


# ─────────────────────────── redirect ───────────────────────────

def redirect_proportion(tr_stocks: float, tr_bonds: float) -> dict[str, Any]:
    """Спред = TR_bonds − TR_stocks → пропорция по таблице §6.2."""
    spread = tr_bonds - tr_stocks
    for upper, proportion, semantics in REDIRECT_TABLE:
        if upper is None or spread <= upper:
            return {"tr_stocks_pct": tr_stocks, "tr_bonds_pct": tr_bonds,
                    "spread_pp": round(spread, 2), "proportion": proportion,
                    "semantics": semantics}
    raise AssertionError("REDIRECT_TABLE обязана заканчиваться открытой корзиной")


# ─────────────────────────── форматирование ───────────────────────────

def _fmt_pct(x: float | None, nd: int = 1, sign: bool = False) -> str:
    """Проценты в русской типографике: десятичная запятая, без хвостовых нулей."""
    if x is None:
        return "н/д"
    s = f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.replace(".", ",")


def _fmt_factor(x: float) -> str:
    """Множитель горизонта — всегда два знака: «1,00» читается как множитель, «1» — нет."""
    return f"{x:.2f}".replace(".", ",")


def _plural(n: int, one: str, few: str, many: str) -> str:
    """Согласование числительного: 1 выпуск / 2 выпуска / 5 выпусков."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def _fmt_ru_date(iso: str) -> str:
    d = _parse_date(iso, "date")
    return d.strftime("%d.%m.%Y")


def build_report_block(payload: dict[str, Any]) -> str:
    """Готовый текст для отчёта: провенанс, горизонт, две стороны TR, пропорция."""
    lines: list[str] = []
    src = payload["source"]
    verdict = payload["freshness"]

    if not src.get("path"):
        lines.append(f"**Стресс-тест недоступен.** {verdict['text']}")
        return "\n".join(lines)

    lines.append(
        f"**Макро-срез — `{src['file']}` от {_fmt_ru_date(src['date'])} "
        f"(возраст {src['age_days']} дн).** {verdict['text']}"
    )

    rc = payload.get("stress_recalc")
    if rc:
        lines.append(f"Числа стресса — пересчёт сайта от {rc['at']} на снапшоте {rc['snapshot_id']}; "
                     f"суждения — {rc['source_stress']}" + (f" от {_fmt_ru_date(rc['judgments_date'])}" if rc["judgments_date"] else "")
                     + "; возраст — по дате суждений.")
        if rc["narrative_stale"]:
            lines.append("Тексты стресса (оговорки, слепые зоны) написаны для чисел дня прогона, не для пересчёта.")

    if payload.get("generation"):
        gen = payload["generation"]
        if not gen["match"]:
            lines.append(
                f"**Поколение расходится:** стресс собран на `{gen['stress_snapshot_id']}`, "
                f"анализ идёт на снапшоте {gen['snapshot_as_of']} — веса позиций за это время "
                "сдвинулись, EV по бумагам берётся как приближение."
            )

    prim = payload["primary_horizon"]
    hrow = next(h for h in payload["horizons"] if h["key"] == prim)
    lines.append(
        f"**Горизонт {prim} — до {_fmt_ru_date(hrow['end'])}, это {_fmt_pct(hrow['months_from_stress'])} мес "
        f"от даты стресса.** Дивиденды и купоны масштабируются множителем "
        f"{_fmt_factor(hrow['scale_factor'])} (не {_fmt_factor(hrow['literal_factor'])} — "
        "горизонты якорные, ключ hNN не равен числу месяцев)."
    )

    st = payload.get("stocks")
    if st:
        ev_top = st["weighted_ev_top_pct"].get(prim)
        ev_all = st["weighted_ev_pct"].get(prim)
        line = (f"**Stress macro EV, акции (top-{st['top_n']} по доле): {_fmt_pct(ev_top, 1, sign=True)}%** "
                f"(вся книга {_fmt_pct(ev_all, 1, sign=True)}%)")
        worst = st["worst_tail"].get(prim)
        if worst:
            line += (f"; худший tail — {worst['ticker']} {_fmt_pct(worst['tail_var_pct'], 1, sign=True)}% "
                     f"(сценарий {worst['scenario_id']})")
        lines.append(line + ".")
        if st["uncovered"]:
            names = ", ".join(u["ticker"] for u in st["uncovered"])
            lines.append(
                f"Не покрыты стрессом: {names} — {_fmt_pct(st['uncovered_weight_pct'])}% книги; "
                "EV взвешен по покрытым бумагам."
            )

    bo = payload.get("bonds")
    if bo and bo.get("available"):
        carry = bo["weighted_carry_pct"].get(prim)
        line = f"**Bond carry по держимым бумагам: {_fmt_pct(carry, 1, sign=True)}%** на {prim}"
        if bo["uncovered"]:
            n = len(bo["uncovered"])
            line += (f"; не {_plural(n, 'покрыт', 'покрыты', 'покрыты')} {n} "
                     f"{_plural(n, 'выпуск', 'выпуска', 'выпусков')} "
                     f"({_fmt_pct(bo['uncovered_weight_pct'])}% облигационной части)")
        lines.append(line + ".")
        lines.append(
            "Для облигаций-кандидатов, которых в портфеле нет, carry считается отдельно "
            "(котировки и дюрация — `scripts/moex_quotes.py`), из стресса он не берётся."
        )

    rd = payload.get("redirect")
    if rd:
        lines.append(
            f"**Спред TR = {_fmt_pct(rd['spread_pp'], 1, sign=True)} пп** "
            f"(облигации {_fmt_pct(rd['tr_bonds_pct'], 1, sign=True)}% − акции "
            f"{_fmt_pct(rd['tr_stocks_pct'], 1, sign=True)}%) → пропорция: {rd['proportion']} "
            f"({rd['semantics']})."
        )
        if verdict["code"] == "warn":
            lines.append("Пропорция помечается «проверить после refresh стресса» — стресс за порогом 30 дней.")

    return "\n".join(lines)


def build_text_output(payload: dict[str, Any]) -> str:
    out: list[str] = []
    src = payload["source"]
    out.append("СТРЕСС-ДАЙДЖЕСТ")
    out.append(f"  режим:      Mode {payload['mode']}")
    if src.get("path"):
        out.append(f"  файл:       {src['file']}")
        out.append(f"  дата:       {src['date']}  (возраст {src['age_days']} дн на {payload['as_of']})")
        out.append(f"  сценарии:   {src.get('scenario_matrix_ref')}  run_id={src.get('run_id')}")
    else:
        out.append("  файл:       не найден")
    if payload.get("stress_recalc"):
        out.append(f"  числа:      {payload['stress_recalc']['message']}")
        if payload["stress_recalc"]["narrative_stale"]:
            out.append("  ВНИМАНИЕ:   тексты стресса (оговорки, слепые зоны) написаны для чисел дня прогона")
    out.append(f"  вердикт:    {payload['freshness']['code']} — {payload['freshness']['text']}")

    gen = payload.get("generation")
    if gen:
        mark = "совпадает" if gen["match"] else "РАСХОЖДЕНИЕ"
        out.append(f"  поколение:  {mark} (стресс: {gen['stress_snapshot_id']}, снапшот: {gen['snapshot_as_of']})")

    if payload.get("horizons"):
        out.append("")
        out.append("ГОРИЗОНТЫ (anchored — ключ hNN не равен числу месяцев)")
        out.append("  ключ   якорь        мес от стресса  мес от as_of  множитель  литеральный")
        for h in payload["horizons"]:
            star = " *" if h["key"] == payload["primary_horizon"] else "  "
            out.append(f"  {h['key']:<4}{star} {h['end']}   {h['months_from_stress']:>10.2f}  "
                       f"{h['months_from_as_of']:>11.2f}  {h['scale_factor']:>9.3f}  {h['literal_factor']:>11.3f}")

    st = payload.get("stocks")
    if st:
        out.append("")
        out.append(f"АКЦИИ — веса из {st['weight_source']}")
        hkeys = list(st["weighted_ev_pct"])
        head = "  тикер    доля  " + "  ".join(f"EV {k:<5} tail {k:<5}" for k in hkeys)
        out.append(head)
        for r in st["positions"][: st["top_n"]]:
            cells = []
            for k in hkeys:
                s = r["by_horizon"].get(k) or {}
                ev = s.get("ev_pct")
                tv = s.get("tail_var_pct")
                cells.append(f"{ev:>8.2f} {tv:>10.2f}" if ev is not None and tv is not None else f"{'н/д':>8} {'н/д':>10}")
            out.append(f"  {r['ticker']:<7} {r['weight_pct']:>5.1f}%  " + "  ".join(cells))
        for k in hkeys:
            out.append(f"  взвешенный EV {k}: top-{st['top_n']} = {st['weighted_ev_top_pct'][k]}%  "
                       f"вся книга = {st['weighted_ev_pct'][k]}%")
        if st["uncovered"]:
            out.append(f"  не покрыты: {', '.join(u['ticker'] for u in st['uncovered'])} "
                       f"({st['uncovered_weight_pct']}% книги)")

    bo = payload.get("bonds")
    if bo and bo.get("available"):
        out.append("")
        out.append("ОБЛИГАЦИИ — bond_carry стресса, только держимые выпуски")
        for k, v in bo["weighted_carry_pct"].items():
            out.append(f"  взвешенный carry {k}: {v}%")
        for r in bo["positions"][:8]:
            cells = "  ".join(
                f"{k}={(r['by_horizon'].get(k) or {}).get('carry_pct')}" for k in bo["weighted_carry_pct"]
            )
            out.append(f"  {r['isin']:<14} {r['name'] or '':<18} {r['weight_pct']:>5.1f}%  {cells}")
        if bo["uncovered"]:
            out.append(f"  не покрыты: {', '.join(u['isin'] for u in bo['uncovered'])} "
                       f"({bo['uncovered_weight_pct']}% облигаций)")

    rd = payload.get("redirect")
    if rd:
        out.append("")
        out.append("L1-REDIRECT (§6.2)")
        out.append(f"  спред {rd['spread_pp']} пп → {rd['proportion']} ({rd['semantics']})")

    if payload.get("warnings"):
        out.append("")
        out.append("ПРЕДУПРЕЖДЕНИЯ")
        for w in payload["warnings"]:
            out.append(f"  · {w}")

    out.append("")
    out.append("── БЛОК ДЛЯ ОТЧЁТА ──")
    out.append(payload["report_block"])
    return "\n".join(out)


# ─────────────────────────── lint-draft ───────────────────────────

def lint_draft(text: str) -> list[tuple[int, str]]:
    """Две проверки черновика ответа. Возвращает [(номер строки, сообщение), …].

    1. Числа стресса без провенанса: в тексте есть признак использования стресса, но
       нигде не названы файл и дата. Без них читатель не знает, на каком макро-срезе
       построен вывод, а устаревший стресс неотличим от свежего.
    2. Литеральный множитель горизонта (`× 24/12`, `× 12/12`): горизонты якорные,
       ключ hNN не равен числу месяцев — множитель берётся из таблицы скрипта.
    """
    violations: list[tuple[int, str]] = []
    has_provenance = any(p.search(text) for p in _PROVENANCE_PATTERNS)

    if not has_provenance:
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern, label in _STRESS_USE_PATTERNS:
                if pattern.search(line):
                    violations.append((
                        lineno,
                        f"{label} — но в черновике нигде не названы файл и дата стресса. "
                        "Провенанс обязателен: «Макро-срез — <файл> от <дата> (возраст N дн)».",
                    ))
                    break

    for lineno, line in enumerate(text.splitlines(), 1):
        m = _LITERAL_FACTOR_RE.search(line)
        if m:
            violations.append((
                lineno,
                f"литеральный множитель горизонта «{m.group(0)}» — горизонты якорные, "
                "ключ hNN не равен числу месяцев; множитель бери из колонки скрипта.",
            ))

    violations.sort(key=lambda v: v[0])
    return violations


# ─────────────────────────── оркестрация / CLI ───────────────────────────

def run_digest(stress_path: str | None, snapshot_path: str | None, mode: int, as_of: date,
               horizons: list[str], primary: str, top_n: int,
               tr_stocks: float | None, tr_bonds: float | None,
               auto_recalc: bool = False, horizons_file: str | None = None) -> dict[str, Any]:
    """auto_recalc=True (CLI при --stress auto): числа берутся из пересчёта сайта, если он
    есть для выбранного стресса; возраст и вердикт свежести — по стрессу скилла.
    horizons_file — файл сроков сайта: не совпадает со сроками стресса — предупреждение stress_terms_mismatch."""
    warnings: list[str] = []

    if not stress_path:
        return {
            "mode": mode, "as_of": as_of.isoformat(),
            "source": {"path": None}, "freshness": absent_verdict(mode),
            "horizons": [], "primary_horizon": primary, "warnings": ["stress_absent"],
            "report_block": build_report_block({
                "source": {"path": None}, "freshness": absent_verdict(mode),
            }),
        }

    stress = load_stress(stress_path)
    stress_date = _parse_date(stress.get("date"), "date")
    skill_file, skill_run_id = os.path.basename(stress_path), stress.get("run_id")
    numbers_path, recalc = stress_path, None
    if auto_recalc:
        found = find_recalc(stress_path)
        if found and found.get("warning"):
            warnings.append(found["warning"])
        elif found:
            try:
                stress = load_stress(found["path"])
                numbers_path = found["path"]
                recalc = recalc_info(stress["recalc"], stress_date.isoformat())
            except StressDigestError as exc:
                stress = load_stress(stress_path)
                warnings.append(f"stress_recalc_skipped:{exc}")
    elif os.path.basename(stress_path).startswith("recalc-") and isinstance(stress.get("recalc"), dict):
        # Задан сам файл пересчёта: возраст — по дате суждений (стресс скилла рядом, в папке выше).
        src_name = str(stress["recalc"].get("source_stress") or "")
        jd = _read_head_date(os.path.join(os.path.dirname(os.path.dirname(stress_path)), src_name)) if src_name else None
        if not jd:
            m = re.search(r"stress-(\d{4}-\d{2}-\d{2})", src_name)
            jd = m.group(1) if m else None
        if jd:
            recalc = recalc_info(stress["recalc"], jd)
            stress_date = _parse_date(jd, "recalc.source_stress")
            skill_file, skill_run_id = src_name, None
        else:
            warnings.append("stress_recalc_skipped:дата суждений recalc.source_stress не определена")
    age_days = (as_of - stress_date).days
    if age_days < 0:
        warnings.append(f"stress_in_future:{stress_date.isoformat()}")
        age_days = 0

    if primary not in horizons:
        horizons = [primary] + horizons

    payload: dict[str, Any] = {
        "mode": mode,
        "as_of": as_of.isoformat(),
        "source": {
            "path": stress_path,
            "file": skill_file,
            "numbers_file": os.path.basename(numbers_path),
            "date": stress_date.isoformat(),
            "age_days": age_days,
            "run_id": skill_run_id if recalc is not None else stress.get("run_id"),
            "numbers_run_id": stress.get("run_id"),
            "scenario_matrix_ref": stress.get("scenario_matrix_ref"),
            "portfolio_snapshot_id": stress.get("portfolio_snapshot_id"),
            "horizon_mode": stress.get("horizon_mode"),
            "primary_horizon_in_file": stress.get("primary_horizon"),
        },
        "stress_recalc": recalc,
        "freshness": freshness_verdict(age_days, mode),
        "horizons": build_horizons(stress, as_of, horizons),
        "primary_horizon": primary,
    }

    if snapshot_path:
        snapshot = load_snapshot(snapshot_path)
        stress_sid = stress.get("portfolio_snapshot_id")
        snap_as_of = snapshot.get("as_of_date")
        expected_sid = f"portfolio-{snap_as_of}.json"
        payload["generation"] = {
            "stress_snapshot_id": stress_sid,
            "snapshot_as_of": snap_as_of,
            "match": stress_sid == expected_sid,
        }
        if not payload["generation"]["match"]:
            warnings.append(f"generation_mismatch:{stress_sid}!={expected_sid}")
        payload["stocks"] = stocks_side(stress, snapshot, horizons, top_n)
        if payload["stocks"]["uncovered"]:
            warnings.append(f"stocks_uncovered:{len(payload['stocks']['uncovered'])}")
        payload["bonds"] = bonds_side(stress, snapshot, horizons)
        if payload["bonds"].get("uncovered"):
            warnings.append(f"bonds_uncovered:{len(payload['bonds']['uncovered'])}")
    else:
        warnings.append("snapshot_absent:взвешивание EV и carry недоступно")

    if tr_stocks is not None and tr_bonds is not None:
        payload["redirect"] = redirect_proportion(tr_stocks, tr_bonds)
    elif (tr_stocks is None) != (tr_bonds is None):
        warnings.append("tr_incomplete:нужны обе стороны — --tr-stocks и --tr-bonds")

    site, site_err = read_site_terms(horizons_file)
    if site_err:
        warnings.append(f"horizons_file_invalid:{site_err}")
    payload["terms"], terms_warn = terms_check(stress, site)
    if terms_warn:
        warnings.append(terms_warn)

    payload["warnings"] = warnings
    payload["report_block"] = build_report_block(payload)
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Дайджест stress-файла для Mode 3 и Mode 8.")
    ap.add_argument("--stress", default="auto", help="Путь к stress-*.yaml или 'auto' (самый свежий по полю date)")
    ap.add_argument("--stress-dir", default=DEFAULT_STRESS_DIR, help="Каталог стрессов для --stress auto")
    ap.add_argument("--horizons-file", default=None,
                    help="Файл сроков сайта horizons.json (по умолчанию <папка стрессов>/../../scenarios/horizons.json)")
    ap.add_argument("--snapshot", help="Путь к portfolio-<date>.json (нужен для взвешивания EV и carry)")
    ap.add_argument("--mode", type=int, choices=(3, 8), default=3, help="Режим advisor'а (лестница свежести разная)")
    ap.add_argument("--as-of", help="Дата анализа YYYY-MM-DD (по умолчанию сегодня)")
    ap.add_argument("--horizons", default="h12,h24", help="Срезы через запятую (по умолчанию h12,h24)")
    ap.add_argument("--primary", default="h12", help="Основной срез отчёта (по умолчанию h12)")
    ap.add_argument("--top", type=int, default=10, help="Сколько бумаг в top-N взвешивании (§6.2 — 10)")
    ap.add_argument("--tr-stocks", type=float, help="Итог TR акций, %% — для расчёта спреда и пропорции")
    ap.add_argument("--tr-bonds", type=float, help="Итог TR облигаций, %% — для расчёта спреда и пропорции")
    ap.add_argument("--lint-draft", metavar="ФАЙЛ",
                    help="Проверить черновик ответа: провенанс стресса и литеральные множители")
    ap.add_argument("--json", action="store_true", help="Выдать JSON вместо текста")
    ap.add_argument("--text", action="store_true", help="Текстовый вывод (по умолчанию)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.lint_draft:
        try:
            with open(args.lint_draft, encoding="utf-8") as f:
                draft = f.read()
        except OSError as exc:
            print(f"Ошибка: не прочитать черновик {args.lint_draft!r}: {exc}", file=sys.stderr)
            return 2
        violations = lint_draft(draft)
        if not violations:
            print("Линт чист: провенанс стресса на месте, литеральных множителей горизонта нет.")
            return 0
        print(f"Нарушений: {len(violations)}")
        for lineno, message in violations:
            print(f"  строка {lineno}: {message}")
        return 1

    try:
        as_of = _parse_date(args.as_of, "--as-of") if args.as_of else date.today()
        if args.stress == "auto":
            try:
                stress_path = find_latest_stress(args.stress_dir)
            except StressDigestError as exc:
                if "нет ни одного" in str(exc):
                    stress_path = None
                else:
                    raise
        else:
            stress_path = args.stress

        horizons = [h.strip() for h in args.horizons.split(",") if h.strip()]
        payload = run_digest(stress_path, args.snapshot, args.mode, as_of, horizons,
                             args.primary, args.top, args.tr_stocks, args.tr_bonds,
                             auto_recalc=(args.stress == "auto"),
                             horizons_file=args.horizons_file or os.path.normpath(
                                 os.path.join(args.stress_dir, HORIZONS_FILE_REL)))
    except StressDigestError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(build_text_output(payload))
    return 1 if payload["freshness"].get("blocking") else 0


if __name__ == "__main__":
    sys.exit(main())
