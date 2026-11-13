#!/usr/bin/env python3
"""
shadow_bundle.py — пакет прогона СКИЛЛА для теневого периода (API-1b, временно).

Теневой период: скилл собирает снапшот как обычно (Шаги 2–6 SKILL.md), но его команды
с сетью обёрнуты в netcache.py --record — записываются именно ЕГО ответы MOEX и ЦБ.
Затем build_snapshot.py --replay собирает снапшот на тех же ответах, parity_check.py
сверяет. Критерий переключения — implementation-brief.md, «Теневой период».

Пакет — ЛОКАЛЬНО (по умолчанию ~/.cache/claude-skills/pdl-parity/<дата>/), не в
Claude-Memory: правило транспорта запрещает Bash-операции с файлами на Synology.

    # до Шага 2 — стартовое состояние кэшей курсов и рядов
    python3 scripts/shadow_bundle.py init --as-of 2026-10-20
    # Шаги 2–6 — каждую python3-команду через обёртку:
    python3 scripts/netcache.py run --record "$B/net" -- scripts/portfolio_returns.py …
    # после Шага 6 — входы, снапшот скилла, повтор скриптом и сверка
    python3 scripts/shadow_bundle.py finish --as-of 2026-10-20 \\
        --trades /tmp/trades.xlsx --balance "/tmp/Общий баланс.numbers" \\
        [--iis-trades …] [--prev-snapshot /tmp/prev_snapshot.json] \\
        [--sector-overrides /tmp/sector-overrides.yaml] [--snapshots-dir …] [--forecasts-dir …] \\
        --skill-snapshot /tmp/portfolio-2026-10-20.json \\
        [--skill-no-moex] [--skill-cbr-offline] [--rebaseline-cash]

`finish` печатает итог сверки и путь отчёта `parity-report.md`; код выхода 1 — расходится.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
# Время МСК (`time_msk.py`) — канон в _shared-references/; в упакованном .skill — рядом (pack.sh).
_HERE_TM = os.path.dirname(os.path.abspath(__file__))
for _cand in (_HERE_TM, os.path.normpath(os.path.join(_HERE_TM, "..", "..", "..", "_shared-references"))):
    if _cand not in sys.path:
        sys.path.insert(0, _cand)
import time_msk  # noqa: E402


HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = Path.home() / ".cache" / "claude-skills" / "pdl-parity"


def bundle_dir(root: Path, as_of: str) -> Path:
    return root / as_of


def cmd_init(a) -> int:
    b = bundle_dir(Path(a.root), a.as_of)
    if b.exists() and not a.force:
        print(f"пакет уже есть: {b} (повтор прогона того же дня — --force)", file=sys.stderr)
        return 1
    if b.exists():
        shutil.rmtree(b)
    start = b / "caches-start"
    start.mkdir(parents=True)
    (b / "net").mkdir()
    (b / "net" / "index.json").write_text("{}", encoding="utf-8")
    cbr = Path(os.environ.get("PDL_CBR_CACHE") or "/tmp/cbr_rates_cache.json")
    if cbr.is_file():
        shutil.copy2(cbr, start / "cbr_rates_cache.json")
    ms = Path(os.environ.get("PDL_MARKET_SERIES_CACHE")
              or Path.home() / ".cache" / "claude-skills" / "market-series")
    if ms.is_dir():
        shutil.copytree(ms, start / "market-series")
    print(f"B={b}")
    return 0


def cmd_finish(a) -> int:
    b = bundle_dir(Path(a.root), a.as_of)
    if not (b / "net" / "index.json").exists():
        print(f"нет пакета {b}: сначала shadow_bundle.py init", file=sys.stderr)
        return 1
    inp = b / "inputs"
    inp.mkdir(exist_ok=True)
    m_in = {}
    for key, src in (("trades", a.trades), ("balance", a.balance), ("iis_trades", a.iis_trades),
                     ("prev_snapshot", a.prev_snapshot), ("sector_overrides", a.sector_overrides)):
        if src:
            p = Path(src)
            name = {"prev_snapshot": "prev_snapshot.json"}.get(key, p.name)
            shutil.copy2(p, inp / name)
            m_in[key] = name
    if a.snapshots_dir and Path(a.snapshots_dir).is_dir():
        (inp / "snapshots").mkdir(exist_ok=True)
        for p in sorted(Path(a.snapshots_dir).glob("portfolio-*.json"), reverse=True)[:3]:
            shutil.copy2(p, inp / "snapshots" / p.name)
    if a.forecasts_dir and Path(a.forecasts_dir).is_dir():
        shutil.copytree(a.forecasts_dir, inp / "forecasts", dirs_exist_ok=True)
    shutil.copy2(a.skill_snapshot, b / "skill-snapshot.json")
    (b / "manifest.json").write_text(json.dumps({
        "kind": "pdl-run-bundle@1", "as_of": a.as_of, "source": "skill",
        "created_at": time_msk.now_iso(),
        "inputs": m_in,
        # Решения о фолбэках скрипт принимает САМ по записанным ответам сети —
        # это и проверяется; решения скилла — для сравнения в отчёте.
        "decisions": {},
        "skill_decisions": {"moex_down": bool(a.skill_no_moex), "cbr_offline": bool(a.skill_cbr_offline)},
        "rebaseline_cash": bool(a.rebaseline_cash),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    out = b / "script-run"
    if out.exists():
        shutil.rmtree(out)
    r = subprocess.run([sys.executable, str(HERE / "build_snapshot.py"), "--replay", str(b), "--out", str(out),
                        "--json"], capture_output=True, text=True)
    if r.returncode not in (0, 2):
        print(r.stderr, file=sys.stderr)
        print("скрипт не собрал снапшот — это расхождение (записать в журнал теневого периода)")
        return 1
    summary = json.loads(r.stdout)
    report = b / "parity-report.md"
    p = subprocess.run([sys.executable, str(HERE / "parity_check.py"), str(b / "skill-snapshot.json"),
                        summary["snapshot_path"], "--report", str(report)], capture_output=True, text=True)
    sd = json.loads((b / "manifest.json").read_text(encoding="utf-8"))["skill_decisions"]
    if summary["fallbacks"].get("moex_down") != sd["moex_down"] or \
            summary["fallbacks"].get("cbr_offline") != sd["cbr_offline"]:
        with report.open("a", encoding="utf-8") as f:
            f.write(f"\n## Фолбэки разошлись\n\nскилл: {sd}; скрипт: {summary['fallbacks']}\n")
    print(p.stdout.splitlines()[0] if p.stdout else "сверка не выполнена")
    print(f"отчёт: {report}")
    return p.returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Пакет прогона скилла для теневой сверки (API-1b).")
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="где хранить пакеты (локально)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("--as-of", default=dt.date.today().isoformat())
    i.add_argument("--force", action="store_true")
    f = sub.add_parser("finish")
    f.add_argument("--as-of", default=dt.date.today().isoformat())
    f.add_argument("--skill-snapshot", required=True)
    for k in ("--trades", "--balance", "--iis-trades", "--prev-snapshot", "--sector-overrides",
              "--snapshots-dir", "--forecasts-dir"):
        f.add_argument(k)
    f.add_argument("--skill-no-moex", action="store_true", help="скилл шёл с --no-moex")
    f.add_argument("--skill-cbr-offline", action="store_true", help="скилл шёл с --cbr-offline")
    f.add_argument("--rebaseline-cash", action="store_true", help="скилл пересобирал с --rebaseline-cash")
    a = ap.parse_args(argv)
    for opt in ("root",):
        setattr(a, opt, os.path.expanduser(getattr(a, opt)))
    return cmd_init(a) if a.cmd == "init" else cmd_finish(a)


if __name__ == "__main__":
    sys.exit(main())
