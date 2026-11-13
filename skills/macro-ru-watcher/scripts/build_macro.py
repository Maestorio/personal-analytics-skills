#!/usr/bin/env python3
"""
build_macro.py — макросрез РФ без LLM (API-1c): данные, Δ, z-score и отчёт ru-<дата>.md.

Что делает модель в SKILL.md и что берёт на себя скрипт:
  • 5 индикаторов (ставка ЦБ, USD/RUB, CNY/RUB, IMOEX, RGBI) — fetch_macro.py, как и раньше;
  • Brent — расчётная цена ближайшего фьючерса BR на MOEX (ISS FORTS), а не цена «с первого
    найденного сайта» (в срезах 09–10.2026: finance.mail.ru, minfin.com.ua, tradingeconomics).
    Δ к прошлому срезу — на ТОМ ЖЕ контракте (история ISS на дату прошлого среза): смена
    контракта раз в месяц иначе давала бы ложный скачок. Решение владельца 2026-10-21;
  • Δ, «месяц назад», окно z-score и флаги — строго по references/anomaly-detection.md,
    история — по значениям ОДНОГО источника: основной автосрезы macro-snapshots/auto/ru-*.json
    (если из них выходит ≥ AUTO_MIN_DELTAS Δ), иначе срезы скилла ru-*.md; источники в окне не
    смешиваются (одна и та же процедура каждый раз:
    в срезах 10.2026 скилл сам отмечал, что μ/σ «не воспроизводят» прошлые отчёты);
  • инфляция — ВХОД (--infl-yoy, --infl-week, --infl-source): недельной инфляции нет в API
    (только пресс-релизы Росстата), месячная таблица ЦБ — другой показатель. Нет входа —
    строка «нет данных», без подстановок.

Пишет только в --out (ru-<дата>.md + ru-<дата>.json); в Claude-Memory не пишет — теневой
период: срез скилла и скрипта сверяются, потом решается запись.

    python3 build_macro.py --history "$CM/macro-snapshots" --out /tmp/macro \\
        [--infl-yoy 7.22 --infl-yoy-asof 2026-10-12 --infl-week 0.11 --infl-week-period "06–12.10" \\
         --infl-source https://…] [--date 2026-10-21]
Только stdlib.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import statistics
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fetch_macro  # noqa: E402

ISS = "https://iss.moex.com/iss"
WINDOW = 12
AUTO_MIN_DELTAS = 8     # автосрезов на окно хватает, если из них выходит ≥ 8 Δ (порог, с которого ≥3σ уже не ❓)
AUTO_KEYS = ("cbr_key", "usd_rub", "cny_rub", "brent", "rgbi", "imoex")
SNAP_RE = re.compile(r"^ru-(\d{4}-\d{2}-\d{2})\.md$", re.I)
AUTO_RE = re.compile(r"^ru-(\d{4}-\d{2}-\d{2})\.json$", re.I)
NUM_RE = re.compile(r"[-−+]?\d+(?:[.,]\d+)?")

# Строки таблицы среза: ключ, подпись, вид Δ ('pct' — %, 'pp' — п.п., 'binary' — ставка ЦБ)
ROWS = [
    ("cbr_key",   "Ключевая ставка ЦБ", "binary"),
    ("infl_yoy",  "Инфляция (г/г)",     "pp"),
    ("infl_week", "Инфляция (нед)",     "pp"),
    ("usd_rub",   "USD/RUB",            "pct"),
    ("cny_rub",   "CNY/RUB",            "pct"),
    ("brent",     "Brent",              "pct"),
    ("rgbi",      "RGBI",               "pct"),
    ("imoex",     "IMOEX",              "pct"),
]
LABEL_TO_KEY = {label: key for key, label, _ in ROWS}
HIST_LABEL = {"usd_rub": "USD/RUB", "cny_rub": "CNY/RUB", "brent": "Brent", "rgbi": "RGBI",
              "imoex": "IMOEX", "infl_yoy": "Инфл. (г/г)", "infl_week": "Инфл. (нед)"}
SOURCES = {
    "cbr_key": "[cbr.ru](https://www.cbr.ru/hd_base/keyrate/)",
    "usd_rub": "[MOEX ISS](https://iss.moex.com/iss/engines/currency/)",
    "cny_rub": "[MOEX ISS](https://iss.moex.com/iss/engines/currency/)",
    "rgbi": "[MOEX ISS](https://www.moex.com/ru/index/RGBI)",
    "imoex": "[MOEX ISS](https://www.moex.com/ru/index/IMOEX)",
}


# ───────────────────────────── история ─────────────────────────────

def parse_number(cell: str) -> float | None:
    """Первое число ячейки: «14.00% (на 16.10)» → 14.0, «$105.92 (закрытие 15.10)» → 105.92,
    «83.995 (внутри дня 16.10)» → 83.995, «❓» / «—» → None."""
    if cell is None or "❓" in cell:
        return None
    m = NUM_RE.search(cell.replace(" ", "").replace("\xa0", ""))
    if not m:
        return None
    return float(m.group(0).replace("−", "-").replace(",", "."))


def parse_snapshot_md(text: str) -> dict[str, float | None]:
    """Таблица среза → {ключ: значение «Текущее»} (второй столбец, как anomaly-detection.md)."""
    out: dict[str, float | None] = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0] in LABEL_TO_KEY:
            out[LABEL_TO_KEY[cells[0]]] = parse_number(cells[1])
    return out


def load_history(folder: Path | None, before: str) -> list[tuple[str, dict]]:
    """[(дата, значения)] срезов строго раньше `before`, по возрастанию даты."""
    if not folder or not folder.is_dir():
        return []
    res = []
    for p in folder.iterdir():
        m = SNAP_RE.match(p.name)
        if m and m.group(1) < before:
            res.append((m.group(1), parse_snapshot_md(p.read_text(encoding="utf-8"))))
    return sorted(res)


def deltas(series: list[float | None], kind: str, groups: list | None = None) -> list[float]:
    """Δ между соседними срезами; срез без значения (❓) выпадает из ряда. groups — метка на точку
    (контракт Brent): Δ через смену метки не считается (скачок экспирации — не движение рынка)."""
    pairs = [(v, groups[i] if groups else None) for i, v in enumerate(series) if v is not None]
    out = []
    for (a, ga), (b, gb) in zip(pairs, pairs[1:]):
        if ga != gb:
            continue
        if kind == "pct":
            if a:
                out.append((b - a) / a * 100.0)
        else:
            out.append(b - a)
    return out


def zscore(cur: float | None, hist: list[float]) -> tuple[float | None, float | None, float | None, int]:
    if cur is None or len(hist) < 2:
        return None, None, None, len(hist)
    mu, sd = statistics.mean(hist), statistics.stdev(hist)
    if sd == 0:
        return None, mu, sd, len(hist)
    return (cur - mu) / sd, mu, sd, len(hist)


def flag(z: float | None, n_hist: int) -> str:
    """Флаги anomaly-detection.md: 1/2/3σ; ≥3σ при истории <8 — ❓; история <2 — без флагов."""
    if z is None or n_hist < 2:
        return ""
    a = abs(z)
    if a >= 3.0:
        return "❓" if n_hist < 8 else "⚠️⚠️⚠️"
    if a >= 2.0:
        return "⚠️⚠️"
    if a >= 1.0:
        return "⚠️"
    return ""


# ───────────────────────────── Brent: фьючерс BR ─────────────────────────────

def _iss_json(url: str, timeout: int = 20, retries: int = 3) -> dict:
    """GET ISS с повтором (сбой DNS/VPN 2026-10-21 — разовый, со второй попытки проходит)."""
    import time
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    raise last


def brent_contracts(today: str) -> list[tuple[str, str]]:
    """Активные контракты BR (secid, последний день торгов), ближайший первым. Контракт, у
    которого до экспирации ≤ 3 дней, пропускается — его цена в последние дни шумная."""
    d = _iss_json(f"{ISS}/engines/futures/markets/forts/securities.json?iss.meta=off&iss.only=securities"
                  "&securities.columns=SECID,ASSETCODE,LASTTRADEDATE")
    rows = [(r[0], r[2]) for r in d["securities"]["data"] if r[1] == "BR" and r[2]]
    lim = (dt.date.fromisoformat(today) + dt.timedelta(days=3)).isoformat()
    return sorted([r for r in rows if r[1] > lim], key=lambda r: r[1])


def brent_settle_on(secid: str, date: str) -> tuple[str, float] | None:
    """Последняя расчётная цена контракта на дату ≤ date (история ISS, окно 10 дней)."""
    frm = (dt.date.fromisoformat(date) - dt.timedelta(days=10)).isoformat()
    d = _iss_json(f"{ISS}/history/engines/futures/markets/forts/securities/{secid}.json?iss.meta=off"
                  f"&from={frm}&till={date}&history.columns=TRADEDATE,SETTLEPRICE")
    rows = [(r[0], r[1]) for r in d["history"]["data"] if r[1] is not None and r[0] <= date]
    return rows[-1] if rows else None


def fetch_brent(today: str, prev_date: str | None) -> dict:
    try:
        contracts = brent_contracts(today)
        if not contracts:
            return {"status": "error", "error": "нет активных контрактов BR"}
        secid, last_day = contracts[0]
        cur = brent_settle_on(secid, today)
        if not cur:
            return {"status": "error", "error": f"нет расчётной цены {secid}"}
        res = {"status": "ok", "value": cur[1], "as_of": cur[0], "contract": secid,
               "contract_last_day": last_day, "source": "moex_iss/forts/BR"}
        if prev_date:
            prev = brent_settle_on(secid, prev_date)
            if prev:
                res["prev_same_contract"] = {"value": prev[1], "as_of": prev[0]}
        return res
    except Exception as e:  # noqa: BLE001 — сеть: срез не падает, строка «нет данных»
        return {"status": "error", "error": str(e)[:300]}


# ───────────────────────────── инфляция: таблица ЦБ ─────────────────────────────

CBR_INFL_URL = "https://www.cbr.ru/hd_base/infl/"
_INFL_ROW = re.compile(r"<tr>\s*<td>(\d{2})\.(\d{4})</td>\s*<td>[^<]*</td>\s*<td>([^<]*)</td>", re.S)


def parse_cbr_infl(html: str) -> dict | None:
    """Таблица cbr.ru/hd_base/infl/ (месяц · ключевая · инфляция г/г · цель) → последний месяц.
    Это МЕСЯЧНАЯ инфляция г/г Росстата в публикации ЦБ, не недельная оценка: в срезах скилла
    строка «Инфляция (г/г)» — оценка по недельным данным, у сайта (без LLM) — эта таблица."""
    m = _INFL_ROW.search(html or "")
    if not m:
        return None
    v = parse_number(m.group(3))
    if v is None:
        return None
    return {"yoy": v, "yoy_asof": f"за {m.group(1)}.{m.group(2)}",
            "source": f"[ЦБ РФ, инфляция г/г за месяц]({CBR_INFL_URL})"}


def fetch_cbr_infl(timeout: int = 20) -> dict | None:
    try:
        return parse_cbr_infl(fetch_macro._http_get(CBR_INFL_URL, timeout=timeout).decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 — нет данных → строка «нет данных», срез не падает
        return None


# ───────────────────────────── сборка ─────────────────────────────

def nearest(history: list[tuple[str, dict]], target: str, key: str) -> tuple[str, float] | None:
    best = None
    for d, vals in history:
        v = vals.get(key)
        if v is None:
            continue
        gap = abs((dt.date.fromisoformat(d) - dt.date.fromisoformat(target)).days)
        if best is None or gap < best[0]:
            best = (gap, d, v)
    return (best[1], best[2]) if best else None


def load_auto_infl(folder: Path | None, before: str) -> list[tuple[str, float]]:
    """[(дата, инфляция г/г)] автосрезов (auto/ru-*.json) строго раньше `before`, по возрастанию даты — ТОЛЬКО
    месячные значения ЦБ (infl_kind cbr_monthly). История z-score инфляции ЦБ не смешивается с недельными
    оценками из ru-*.md скилла: другой показатель, смесь давала ложный флаг."""
    if not folder or not (folder / "auto").is_dir():
        return []
    res = []
    for p in (folder / "auto").iterdir():
        m = AUTO_RE.match(p.name)
        if not (m and m.group(1) < before):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("infl_kind") != "cbr_monthly":
            continue
        v = next((r.get("value") for r in d.get("rows") or [] if r.get("key") == "infl_yoy"), None)
        if isinstance(v, (int, float)):
            res.append((m.group(1), float(v)))
    return sorted(res)


def load_auto_series(folder: Path | None, before: str) -> dict[str, list[tuple]]:
    """{ключ: [(дата, значение, контракт)]} автосрезов (auto/ru-*.json) строго раньше `before`, по возрастанию.
    Только показатели AUTO_KEYS (инфляцию ведёт load_auto_infl). Автосрез — единый источник сайта
    (одно расписание съёма, Brent — BR MOEX); срезы скилла ru-*.md снимались в другое время суток,
    а до 21.10.2026 Brent в них — ICE, поэтому окно одного показателя строится по ОДНОМУ источнику."""
    res: dict[str, list[tuple]] = {k: [] for k in AUTO_KEYS}
    if not folder or not (folder / "auto").is_dir():
        return res
    for p in sorted((folder / "auto").iterdir()):
        m = AUTO_RE.match(p.name)
        if not (m and m.group(1) < before):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in d.get("rows") or []:
            v = r.get("value")
            if r.get("key") in res and isinstance(v, (int, float)) and not isinstance(v, bool):
                res[r["key"]].append((m.group(1), float(v), r.get("contract")))
    return res


def pick_auto(auto: dict[str, list[tuple]]) -> dict[str, list[tuple]]:
    """Показатели, чья история берётся из автосрезов: хватает AUTO_MIN_DELTAS Δ (с учётом смен контракта).
    Остальные — по ru-*.md целиком, без подмешивания."""
    out = {}
    for key, rows in auto.items():
        ds = deltas([v for _, v, _ in rows], "pct", [c for _, _, c in rows])
        if len(ds) >= AUTO_MIN_DELTAS:
            out[key] = rows
    return out


def build(today: str, history: list[tuple[str, dict]], fetched: dict, brent: dict, infl: dict,
          override: dict[str, list[tuple[str, float]]] | None = None) -> dict:
    """override — {ключ: [(дата, значение)]}: история этого показателя берётся из него, а не из ru-*.md
    (прошлое значение, «месяц назад», окно z-score — по одному источнику)."""
    prev_date, prev_vals = history[-1] if history else (None, {})
    month = (dt.date.fromisoformat(today) - dt.timedelta(days=30)).isoformat()
    cur: dict[str, dict] = {}
    for key in ("cbr_key", "usd_rub", "cny_rub", "rgbi", "imoex"):
        r = (fetched.get("indicators") or {}).get(key) or {}
        cur[key] = {"value": r.get("value") if r.get("status") == "ok" else None,
                    "as_of": r.get("as_of"), "error": r.get("error")}
    cur["brent"] = {"value": brent.get("value"), "as_of": brent.get("as_of"), "error": brent.get("error"),
                    "contract": brent.get("contract")}
    cur["infl_yoy"] = {"value": infl.get("yoy"), "as_of": infl.get("yoy_asof")}
    cur["infl_week"] = {"value": infl.get("week"), "as_of": infl.get("week_period")}

    rows = []
    for key, label, kind in ROWS:
        v = cur[key]["value"]
        hist_rows = history
        pv = prev_vals.get(key)
        if override and key in override:
            hist_rows = [(e[0], {key: e[1], "_c": e[2] if len(e) > 2 else None}) for e in override[key]]
            pv = hist_rows[-1][1][key] if hist_rows else None
        delta, note = None, None
        if key == "brent" and brent.get("prev_same_contract"):
            p = brent["prev_same_contract"]["value"]
            delta = (v - p) / p * 100.0 if v is not None and p else None
            note = f"Δ на одном контракте {brent['contract']} к {brent['prev_same_contract']['as_of']}"
        elif v is not None and pv is not None:
            delta = (v - pv) / pv * 100.0 if kind == "pct" and pv else (v - pv)
        series = [vals.get(key) for _, vals in hist_rows]
        groups = [vals.get("_c") for _, vals in hist_rows] if key == "brent" and override and key in override else None
        hist = deltas(series, "pct" if kind == "pct" else "pp", groups)[-WINDOW:]
        if kind == "binary":
            z = mu = sd = None
            n = len(hist)
        else:
            z, mu, sd, n = zscore(delta, hist)
        rows.append({"key": key, "label": label, "kind": kind, "value": v, "as_of": cur[key].get("as_of"),
                     "prev": pv, "month_ago": nearest(hist_rows, month, key), "delta": delta,
                     "z": z, "mu": mu, "sigma": sd, "n_hist": n, "flag": flag(z, n) if kind != "binary" else "",
                     "note": note, "error": cur[key].get("error"), "contract": cur[key].get("contract")})
    return {"kind": "macro-ru@1", "date": today, "prev_date": prev_date, "n_snapshots": len(history),
            "rows": rows, "infl_source": infl.get("source")}


def _fmt_val(r: dict) -> str:
    v = r["value"]
    if v is None:
        return "нет данных"
    if r["key"] in ("cbr_key", "infl_yoy", "infl_week"):
        s = f"{v:.2f}%"
    elif r["key"] == "brent":
        s = f"${v:.2f}"
    else:
        s = f"{v:g}"
    extra = r.get("as_of") or ""
    if r["key"] == "brent" and r.get("contract"):
        extra = f"{r['contract']}, расчётная {r['as_of']}"
    return f"{s} ({extra})" if extra else s


def _fmt_delta(r: dict) -> str:
    d = r["delta"]
    if d is None:
        return "—"
    if r["kind"] == "binary":
        return "—" if abs(d) < 1e-9 else f"⚠️ {d:+.2f} п.п."
    return f"{d:+.2f}%" if r["kind"] == "pct" else f"{d:+.2f} п.п."


def render_md(rep: dict, collected_at: str) -> str:
    d = dt.date.fromisoformat(rep["date"]).strftime("%d.%m.%Y")
    prev = rep["prev_date"]
    prev_s = (f"{dt.date.fromisoformat(prev):%d.%m.%Y} "
              f"({(dt.date.fromisoformat(rep['date']) - dt.date.fromisoformat(prev)).days} дн. назад)") if prev else "нет"
    pd_short = f"{dt.date.fromisoformat(prev):%d.%m}" if prev else "—"
    lines = [f"# Макропанель РФ · {d}", "",
             f"*Сбор: {collected_at} · Предыдущий snapshot: {prev_s} · Tier: 1 · окно z-score: "
             f"до {WINDOW} Δ между срезами, предшествующих текущему · build_macro.py*", "",
             "## Snapshot", "",
             f"| Индикатор | Текущее | Прошлый snapshot ({pd_short}) | Месяц назад | Δ (к {pd_short}) | z-score | Источник |",
             "|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        ma = r["month_ago"]
        z = "— (бинарный маркер)" if r["kind"] == "binary" else (
            f"{r['z']:+.2f}σ {r['flag']}".strip() if r["z"] is not None else "—")
        src = SOURCES.get(r["key"]) or ("[MOEX ISS, фьючерс BR](https://iss.moex.com/iss/engines/futures/markets/forts/)"
                                        if r["key"] == "brent" else (rep.get("infl_source") or "вход не передан"))
        prev_cell = "" if r["prev"] is None else f"{r['prev']:g}"
        month_cell = "" if not ma else f"{ma[1]:g} ({dt.date.fromisoformat(ma[0]):%d.%m})"
        lines.append(f"| {r['label']} | {_fmt_val(r)} | {prev_cell} | {month_cell} | {_fmt_delta(r)} | {z} | {src} |")
    anomalies = [r for r in rep["rows"] if r["flag"]]
    lines += ["", "## Аномалии (|z| ≥ 1.0)", ""]
    lines += ([f"- {r['flag']} **{r['label']} {_fmt_val(r).split(' (')[0]}** (Δ {_fmt_delta(r)}, z={r['z']:+.2f}σ)"
               for r in anomalies] or ["Нет. Все индикаторы в пределах |z| < 1.0σ."])
    lines += ["", f"## История z-score (окно до {WINDOW} Δ)", "", "```"]
    for r in rep["rows"]:
        if r["kind"] == "binary" or r["mu"] is None:
            continue
        unit = "%" if r["kind"] == "pct" else " п.п."
        lines.append(f"{HIST_LABEL[r['key']]:<11}: μ={r['mu']:+.2f}{unit}  σ={r['sigma']:.2f}{unit}  N={r['n_hist']}")
    lines += ["```", "", "## Данные качества и пропуски", ""]
    for r in rep["rows"]:
        if r["error"]:
            lines.append(f"- **{r['label']}:** нет данных — {r['error']}")
        if r["note"]:
            lines.append(f"- **{r['label']}:** {r['note']}.")
    if rep.get("infl_kind") == "cbr_monthly":
        lines.append("- **Инфляция (г/г):** месячная из таблицы ЦБ; Δ и z-score — только по прежним месячным "
                     "значениям ЦБ из автосрезов, недельные оценки срезов скилла в историю не входят.")
    if any(r["key"].startswith("infl") and r["value"] is None for r in rep["rows"]):
        lines.append("- **Инфляция:** вход не передан (скрипт её не собирает — недельные данные только в "
                     "пресс-релизах Росстата).")
    brent = next(r for r in rep["rows"] if r["key"] == "brent")
    if brent["value"] is not None:
        lines.append("- **Brent:** фьючерс BR MOEX, расчётная цена (с 2026-10-21; раньше — ICE с разных сайтов). "
                     "История z-score: " + ("автосрезы сайта (BR MOEX)." if "brent" in (rep.get("history_auto") or [])
                                  else "до 21.10.2026 в срезах скилла — ICE, смешанная."))
    if rep["n_snapshots"] < 2:
        lines.append("- Аномалии не флагуются: история < 2 срезов.")
    lines += ["", "## Без интерпретаций", "", "Этот отчёт — pure signaling panel. Без прогнозов, без рекомендаций.",
              "", "---", "*Сгенерировано: macro-ru-watcher · build_macro.py (без LLM)*", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Макросрез РФ без LLM.")
    ap.add_argument("--history", help="папка macro-snapshots с прошлыми ru-*.md")
    ap.add_argument("--out", required=True, help="куда писать ru-<дата>.md и .json")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--infl-yoy", type=float)
    ap.add_argument("--infl-yoy-asof")
    ap.add_argument("--infl-week", type=float)
    ap.add_argument("--infl-week-period")
    ap.add_argument("--infl-source", help="ссылка markdown на источник инфляции")
    ap.add_argument("--infl-cbr", action="store_true",
                    help="инфляции г/г нет на входе — взять месячную из таблицы ЦБ")
    a = ap.parse_args(argv)
    infl = {"yoy": a.infl_yoy, "yoy_asof": a.infl_yoy_asof, "week": a.infl_week,
            "week_period": a.infl_week_period, "source": a.infl_source}
    md, rep = make(a.date, Path(a.history) if a.history else None, infl, infl_cbr=a.infl_cbr)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"ru-{a.date}.md").write_text(md, encoding="utf-8")
    (out / f"ru-{a.date}.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2, default=str),
                                           encoding="utf-8")
    print(out / f"ru-{a.date}.md")
    return 0


def make(date: str, history_dir: Path | None, infl: dict, infl_cbr: bool = False) -> tuple[str, dict]:
    """Сбор + отчёт без записи: (markdown, json-отчёт). Его же зовёт ежедневная задача сайта
    (tools/hosting/notify/macro_job.py) — одна реализация для скилла и сайта."""
    history = load_history(history_dir, date)
    auto = pick_auto(load_auto_series(history_dir, date))
    fetched = fetch_macro.fetch_all()
    brent_prev = auto["brent"][-1][0] if "brent" in auto else (history[-1][0] if history else None)
    brent = fetch_brent(date, brent_prev)
    infl = dict(infl)
    infl_kind = "input" if infl.get("yoy") is not None else None
    if infl_kind is None and infl_cbr:
        cbr = fetch_cbr_infl()
        if cbr:
            infl.update(cbr)
            infl_kind = "cbr_monthly"
    override: dict = dict(auto)
    if infl_kind == "cbr_monthly":
        override["infl_yoy"] = load_auto_infl(history_dir, date)
    rep_auto = sorted(auto)
    rep = build(date, history, fetched, brent, infl, override=override)
    rep["infl_kind"] = infl_kind
    rep["history_auto"] = rep_auto
    rep["fetched"] = {"fetch_macro": fetched, "brent": brent}
    collected = dt.datetime.now().strftime("%d.%m.%Y %H:%M MSK")
    return render_md(rep, collected), rep


if __name__ == "__main__":
    sys.exit(main())
