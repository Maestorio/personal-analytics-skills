#!/usr/bin/env python3
"""Сторож диеты CLAUDE.md (этап 1 подготовки Max → Pro, 2026-08-12; этап 2 — 2026-10-05).

CLAUDE.md грузится в контекст каждой сессии и каждого субагента; 2026-08-12 он
был ужат со 188 КБ (~60К токенов) до ~36 КБ (~12К токенов): аннотации тестов
уехали в docs/test-registry.md. 2026-10-05 из корня ушёл и сам список команд
(~18 КБ): единственный список тестов — реестр, запускает его tools/run_tests.py.
Без сторожа файл отрастёт обратно тем же путём, каким вырос: «допишу подробность
прямо здесь, один раз не страшно».

Держит:
1. Бюджет корня — MAX_BYTES. Превысил → выноси в docs/ и оставляй сводку.
2. Список тестов не возвращается в CLAUDE.md: ни одной строки `python3 …/tests/…`.
3. CLAUDE.md ссылается на реестр и запускатель; запускатель видит ровно команды
   реестра (тот же парсер), их не меньше 70, и каждый файл существует.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLAUDE_MD = ROOT / "CLAUDE.md"
REGISTRY = ROOT / "docs" / "test-registry.md"
sys.path.insert(0, str(ROOT / "tools"))
import run_tests  # noqa: E402

MAX_BYTES = 32_000          # после выноса списка тестов ~28 КБ; запас ~15%, дальше — в docs/

CHECKS = 0


def check(cond, msg):
    global CHECKS
    CHECKS += 1
    assert cond, msg


def main():
    claude = CLAUDE_MD.read_text(encoding="utf-8")

    # 1. Бюджет корня
    size = len(claude.encode("utf-8"))
    check(size <= MAX_BYTES,
          f"CLAUDE.md разросся: {size} Б > бюджета {MAX_BYTES} Б. "
          f"Длинное — в docs/ (тесты → docs/test-registry.md, "
          f"спеки → docs/investment/), в корне оставляй сводку.")

    # 2. Список тестов не вернулся в корень
    back = [ln[:80] for ln in claude.splitlines()
            if ln.startswith("python3 ") and "/tests/" in ln]
    check(not back, f"в CLAUDE.md снова перечислены тесты — им место в docs/test-registry.md: {back}")

    # 3. Ссылки и реестр
    check(REGISTRY.exists(), f"нет {REGISTRY} — реестр тестов удалён?")
    check("docs/test-registry.md" in claude, "CLAUDE.md потерял ссылку на docs/test-registry.md")
    check("tools/run_tests.py" in claude, "CLAUDE.md потерял команду запуска tools/run_tests.py")
    cmds = run_tests.registry_commands(REGISTRY)
    raw = {ln.split("#")[0].strip() for ln in REGISTRY.read_text(encoding="utf-8").splitlines()
           if ln.startswith("python3 ")}
    check(set(cmds) == raw, "запускатель видит не те команды, что лежат в реестре")
    check(len(cmds) >= 70, f"в реестре подозрительно мало команд ({len(cmds)}) — реестр повреждён?")
    missing = [c.split()[1] for c in cmds if not (ROOT / c.split()[1]).exists()]
    check(not missing, f"реестр ссылается на несуществующие файлы: {missing}")

    print(f"OK: {CHECKS} проверок — CLAUDE.md {size} Б (бюджет {MAX_BYTES}), "
          f"в реестре {len(cmds)} тестов, все файлы на месте")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"FAIL: {e}")
        sys.exit(1)
