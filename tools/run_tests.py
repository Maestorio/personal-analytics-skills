#!/usr/bin/env python3
"""Запуск регрессионных тестов репозитория по реестру `docs/test-registry.md`.

Реестр — единственный список тестов (строки `python3 …` внутри него); здесь он
только читается. Новый тест = блок в реестре: аннотация `# …` + строка команды.

  python3 tools/run_tests.py                     # все тесты (--tier all)
  python3 tools/run_tests.py --tier fast         # без браузера, -j 4 (≈ на каждый коммит)
  python3 tools/run_tests.py --tier browser      # только браузерные (Playwright), -j 2 (перед выкладкой)
  python3 tools/run_tests.py zenmoney-analyst    # только команды, где есть подстрока
  python3 tools/run_tests.py travel health -x    # несколько фильтров; -x — до первого падения
  python3 tools/run_tests.py --list              # показать, что будет запущено, с ярусами
  python3 tools/run_tests.py -j 1                # строго по очереди (оба яруса)
  python3 tools/run_tests.py --group invest      # инвестконтур + вьюер без остальных страниц кабинета (≈ вдвое быстрее)
  python3 tools/run_tests.py --group health      # раздел «Здоровье» + общие тесты со стендом «Здоровья»

Ярусы. Браузерный — файл теста, в тексте которого есть «playwright»; остальные — быстрые. `all` гонит
быстрые при -j 4, затем браузерные при -j 2 (при -j 4 браузерные моргали под нагрузкой), итог один.
`--group` и фильтры работают поверх ярусов; явный -j задаёт параллельность обоим ярусам.

Интерпретатор: --python, иначе $CLAUDE_SKILLS_PYTHON, иначе ~/.pyenv/versions/3.12.9
(системный python3 на этой машине сломан), иначе текущий. Только stdlib.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs" / "test-registry.md"
PYENV = Path.home() / ".pyenv" / "versions" / "3.12.9" / "bin" / "python3"


def registry_commands(path: Path = REGISTRY) -> list[str]:
    """Команды реестра по порядку, без повторов: строки, начинающиеся с `python3 `."""
    seen, out = set(), []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.startswith("python3 "):
            cmd = ln.split("#")[0].strip()
            if cmd not in seen:
                seen.add(cmd)
                out.append(cmd)
    return out


def is_browser(cmd: str) -> bool:
    """Браузерный ли тест: файл скрипта из команды упоминает playwright."""
    for arg in shlex.split(cmd)[1:]:
        if arg.endswith(".py"):
            f = ROOT / arg
            try:
                return "playwright" in f.read_text(encoding="utf-8")
            except OSError:
                return False
    return False


TIER_JOBS = {"fast": 4, "browser": 2}


def interpreter(explicit: str | None) -> str:
    if explicit:
        return explicit
    if os.environ.get("CLAUDE_SKILLS_PYTHON"):
        return os.environ["CLAUDE_SKILLS_PYTHON"]
    return str(PYENV) if PYENV.exists() else sys.executable


# Группы для частых прогонов (владелец 31.10: полный реестр ≈ 5 мин, гонять его на каждый коммит дорого).
# «invest» = весь реестр МИНУС разделы кабинета, не связанные с инвестициями и вьюером (их гоняет полный прогон
# перед закрытием шага и перед выкладкой). Исключения — подстроки команды.
GROUPS = {
    "invest": {
        "exclude": ["skills/travel-planning", "skills/zenmoney-analyst", "skills/game-advisor", "skills/health-",
                    "test_select_", "test_nav_layout", "test_topbar_layout", "test_food_layout", "test_reader_layout",
                    "test_money_layout", "test_health_", "test_games_", "test_travel_status", "test_match_products",
                    "test_nutrition", "test_validate_recipe", "test_zenmoney_"],
    },
    # «health» = раздел «Здоровье»: скиллы health-*, страница health.html и общие тесты, у которых есть стенд
    # «Здоровья» (контракты страниц, write-API /api/hd/*, выпадашки, навигация, шапка, читатель, офлайн, зоны Caddy).
    "health": {
        "include": ["skills/health-", "test_health_", "test_pages_contracts", "test_write_api", "test_select_layout",
                    "test_nav_layout", "test_topbar_layout", "test_reader_layout", "test_offline", "test_stack_e2e",
                    "test_caddy_zones"],
    },
}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("filters", nargs="*", help="подстроки пути/команды (ИЛИ)")
    p.add_argument("--group", choices=sorted(GROUPS), help="именованная группа (invest — инвестконтур и вьюер без "
                                                           "остальных страниц кабинета; health — раздел «Здоровье» "
                                                           "и общие тесты с его стендом); сочетается с фильтрами")
    p.add_argument("--tier", choices=("fast", "browser", "all"), default="all",
                   help="ярус: fast — без браузера (-j 4), browser — Playwright (-j 2), all — оба по очереди")
    p.add_argument("--list", action="store_true", help="только показать команды (с ярусом)")
    p.add_argument("-x", "--fail-fast", action="store_true")
    p.add_argument("--python")
    p.add_argument("-j", "--jobs", type=int, default=None,
                   help="сколько тестов гнать одновременно (по умолчанию: быстрые — min(4, ядра), "
                        "браузерные — 2; 1 — по очереди)")
    p.add_argument("--tail", type=int, default=15, help="строк вывода упавшего теста")
    p.add_argument("--timeout", type=int, default=900)
    a = p.parse_args(argv)

    cmds = [c for c in registry_commands() if not a.filters or any(f in c for f in a.filters)]
    if a.group:
        incl = GROUPS[a.group].get("include")
        excl = GROUPS[a.group].get("exclude", [])
        if incl:
            cmds = [c for c in cmds if any(i in c for i in incl)]
        cmds = [c for c in cmds if not any(e in c for e in excl)]
    tiers = {c: ("browser" if is_browser(c) else "fast") for c in cmds}
    if a.tier != "all":
        cmds = [c for c in cmds if tiers[c] == a.tier]
    if not cmds:
        print(f"нет тестов под фильтр {a.filters} (ярус {a.tier})")
        return 2
    if a.list:
        print("\n".join(f"{tiers[c]:7s} {c}" for c in cmds))
        nb = sum(tiers[c] == "browser" for c in cmds)
        print(f"\n{len(cmds)} тестов: fast {len(cmds) - nb}, browser {nb}")
        return 0

    py = interpreter(a.python)
    failed, t0 = [], time.time()
    def run_one(cmd):
        args = shlex.split(cmd)
        args[0] = py
        start = time.time()
        try:
            r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=a.timeout)
            rc, out = r.returncode, (r.stdout + r.stderr).strip()
        except subprocess.TimeoutExpired:
            rc, out = -1, f"таймаут {a.timeout} с"
        return cmd, rc, out, time.time() - start

    done = 0
    def report(cmd, rc, out, dt):
        nonlocal passed, done
        done += 1
        last = out.splitlines()[-1] if out else ""
        mark = "OK  " if rc == 0 else "FAIL"
        print(f"[{done}/{len(cmds)}] {mark} {cmd[8:]}  ({dt:.0f} с) {last[:120]}", flush=True)
        if rc == 0:
            passed += 1
        else:
            failed.append((cmd, out))

    passed = 0
    stamps = []
    for tier in ("fast", "browser"):
        batch = [c for c in cmds if tiers[c] == tier]
        if not batch or (failed and a.fail_fast):
            continue
        jobs = a.jobs if a.jobs is not None else min(TIER_JOBS[tier], os.cpu_count() or 1)
        ts = time.time()
        if jobs <= 1 or a.fail_fast:
            for cmd in batch:
                report(*run_one(cmd))
                if failed and a.fail_fast:
                    break
        else:
            # тесты независимы (эфемерные порты, свои tmp-каталоги); самые долгие (tools/tests/) — первыми,
            # чтобы хвост не растягивал прогон; отчёт — по мере завершения
            order = sorted(batch, key=lambda c: ("tools/tests/" not in c, ))
            with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
                for fut in cf.as_completed([ex.submit(run_one, c) for c in order]):
                    report(*fut.result())
        stamps.append(f"{tier} {len(batch)} шт. при -j {jobs} — {time.time() - ts:.0f} с")
    # Упавшие при параллельном запуске перегоняются один раз по очереди; прошедшие со второй попытки
    # считаются зелёными, но перечисляются отдельно — стабильное падение так не спрячется (оно упадёт
    # и во второй раз).
    flaky = []
    if failed and (a.jobs is None or a.jobs > 1) and not a.fail_fast:
        retry = [cmd for cmd, _ in failed]
        failed.clear()
        for cmd in retry:
            _, rc, out, dt = run_one(cmd)
            if rc == 0:
                passed += 1
                flaky.append(cmd)
                print(f"[повтор] OK   {cmd[8:]}  ({dt:.0f} с) — прошёл по очереди со второй попытки", flush=True)
            else:
                failed.append((cmd, out))
                print(f"[повтор] FAIL {cmd[8:]}  ({dt:.0f} с)", flush=True)
    if len(stamps) > 1 or a.tier != "all":
        print("\nЯрусы: " + "; ".join(stamps))
    print(f"\nИтого: {passed} из {len(cmds)} прошли за {time.time() - t0:.0f} с (python: {py})")
    if flaky:
        print("Со второй попытки (моргают при параллельном запуске): " + ", ".join(c[8:] for c in flaky))
    for cmd, out in failed:
        print(f"\n── FAIL {cmd}")
        print("\n".join(out.splitlines()[-a.tail:]))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
