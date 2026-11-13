#!/usr/bin/env python3
"""Сторож инструкций цикла машиночитаемости (шаг 10, decision.md §2 C5): советник и save-to-library берут базы
выборками скриптов, а не чтением файлов, и не зовут удалённые команды и скрипты.

В `.md` скиллов `ru-portfolio-advisor` и `save-to-library` (рекурсивно) нет:
  1. удалённых команд `apply_condition.py` (evaluate / open / close / remove / fire / touch);
  2. входа `ssot` прежнего API условий;
  3. удалённых скриптов и директив гейта: apply_gate_review, auto_maintain_gate_reviews, gate_review_update,
     gate_review_directive (и proposed_…), gate_review_bulk_update;
  4. чтения носителей целиком: Read / «прочитай» рядом с conditions.yaml, gate-reviews, decisions/, journal.json;
  5. прежних вердиктов облигаций (HOLD_ADD, RED_FLAG, MATURE, HOLD_NO_OFFER) нет совсем — кроме
     `fundamental_score: RED_FLAG` (другое поле, оценка фундаментала);
  5а. (довесок шага 16) записи ограничения в YAML обзора и переноса его из прошлого обзора: «Добавить ограничение
     для», «Захват нового ограничения», constraint_payload, check-constraint-carry-over, типы прежней формы
     (hold_override, price_gate_buy, no_buy_until_date), closed_reason;
  6. в `.py` скриптов советника нет чтения `gate-reviews.yaml` — исключений нет с шага 11 (`gate_aware_sizing.py`
     считает гейт модулем (б) из решений); `ALLOW_GATE_FILE` пуст.
  7. (шаг 15) в репозитории нет писателей индекса бумаги `Portfolio/securities/`: строки `securities_index`,
     `publish_securities`, `Portfolio/securities` не встречаются в `skills/**` (.py, .md), `_shared-references/*.py`,
     `tools/hosting/**/*.py`, `tools/deploy.zsh` (архиватор и миграции — `tools/data-structures/`, документы
     истории — вне проверки).
Плюс замер C5: выдача `security_digest.py` на фикстуре «в натуральную величину» ≤ 6 000 токенов (байты/4).

Различитель: подложенная строка «Read Portfolio/conditions.yaml» или «apply_condition.py evaluate» в любом .md
скилла роняет тест. stdlib + PyYAML (фикстура замера).
"""
import re
import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = [ROOT / "skills" / "ru-portfolio-advisor", ROOT / "skills" / "save-to-library"]
ADVISOR_SCRIPTS = ROOT / "skills" / "ru-portfolio-advisor" / "scripts"
# Исключений для чтения файла гейтов нет: последний читатель (gate_aware_sizing.py) переведён на модуль (б) в шаге 11.
ALLOW_GATE_FILE: set = set()

RULES = [
    ("удалённая команда apply_condition.py",
     re.compile(r"apply_condition\.py`?\s+`?(evaluate|open|close|remove|fire|touch)\b")),
    ("вход ssot прежнего API условий", re.compile(r"(?<![A-Za-z_])ssot(?![A-Za-z_])")),
    ("удалённый скрипт или директива гейта",
     re.compile(r"apply_gate_review|auto_maintain_gate_reviews|gate_review_update|gate_review_directive"
                r"|gate_review_bulk_update")),
    ("чтение носителя целиком",
     re.compile(r"(\bRead\b|[Пп]рочита\w*)[^\n]{0,80}?(conditions\.yaml|gate-reviews|decisions/|journal\.json)")),
    # довесок шага 16 (DS-PA): срез user_constraints производный — ограничение не заводится в YAML обзора и не
    # переносится из прошлого обзора (убраны ветка D «Захват нового ограничения», constraint_payload, F2.6 carry-over)
    ("ограничение записью в YAML обзора / перенос из прошлого обзора",
     re.compile(r"Добавить ограничение для|Захват нового ограничения|constraint_payload|Prior Constraint Reconciliation"
                r"|check-constraint-carry-over|closed_reason|hold_override|price_gate_buy|no_buy_until_date")),
]
LEGACY = re.compile(r"\b(HOLD_ADD|RED_FLAG|MATURE|HOLD_NO_OFFER)\b")
LEGACY_OK = ("fundamental",)

CHECKS = 0
ERRORS = []


def check(cond, msg):
    global CHECKS
    CHECKS += 1
    if not cond:
        ERRORS.append(msg)


def scan_md(path: Path, text: str):
    lines = text.split("\n")
    rel = path.relative_to(ROOT)
    for i, line in enumerate(lines, 1):
        for label, rx in RULES:
            m = rx.search(line)
            check(m is None, f"{rel}:{i}: {label}: «{line.strip()[:120]}»")
        if LEGACY.search(line):
            ctx = " ".join(lines[max(0, i - 4):i + 1]).lower()
            check(any(w in ctx for w in LEGACY_OK),
                  f"{rel}:{i}: прежний вердикт облигаций (кодов нет в словаре): «{line.strip()[:120]}»")


def scan_py(path: Path, text: str):
    if path.name in ALLOW_GATE_FILE:
        return
    for i, line in enumerate(text.split("\n"), 1):
        check("gate-reviews.yaml" not in line and "--gate-reviews" not in line,
              f"{path.relative_to(ROOT)}:{i}: скрипт советника читает файл гейтов «{line.strip()[:100]}»")


def self_test():
    """Различитель: подложенные нарушения ловятся, допустимые формы — нет."""
    global CHECKS, ERRORS
    saved = (CHECKS, ERRORS)
    CHECKS, ERRORS = 0, []
    fake = ROOT / "skills" / "ru-portfolio-advisor" / "x.md"
    scan_md(fake, "1. Read Portfolio/conditions.yaml целиком\n`apply_condition.py evaluate` {ssot}\n"
                  "gate_review_update:\nвердикт HOLD_ADD для облигаций\nПрочитай `Portfolio/decision-journal/journal.json`\n"
                  "«Добавить ограничение для TICKER в YAML?»")
    bad = len(ERRORS)
    CHECKS, ERRORS = 0, []
    scan_md(fake, "`apply_condition.py digest --key X`\nfundamental_score: RED_FLAG\n"
                  "SSOT весов сценариев\nвыборка `decision_write.py digest`")
    good = len(ERRORS)
    CHECKS, ERRORS = saved
    check(bad >= 7, f"самопроверка: подложенные нарушения не пойманы ({bad} из ≥7)")
    check(good == 0, f"самопроверка: допустимые формы помечены нарушением ({good})")


def measure_c5():
    sys.path.insert(0, str(ROOT / "skills" / "ru-portfolio-advisor" / "tests"))
    import test_security_digest as T  # noqa: E402 — фикстура и замер живут рядом с тестами выборки
    root = tempfile.mkdtemp(prefix="c5-measure-")
    try:
        T.build_fixture(root)
        tokens = T.measure(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    check(tokens <= T.TOKEN_TARGET, f"C5: security_digest по бумаге {tokens} токенов > {T.TOKEN_TARGET}")
    return tokens


SEC_WRITER = re.compile(r"securities_index|publish_securities|Portfolio/securities")


def scan_securities_writers():
    """Шаг 15: индекс бумаги упразднён — писателей и вызовов нет. Возвращает число просмотренных файлов."""
    files = [p for p in (ROOT / "skills").rglob("*") if p.suffix in (".py", ".md")]
    files += list((ROOT / "_shared-references").glob("*.py"))
    files += list((ROOT / "tools" / "hosting").rglob("*.py"))
    files.append(ROOT / "tools" / "deploy.zsh")
    me = Path(__file__).resolve()
    n = 0
    for p in files:
        if not p.is_file() or p.resolve() == me or "__pycache__" in p.parts or "tests" in p.parts:
            continue
        n += 1
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if SEC_WRITER.search(line) and "упразднён" not in line and "удалён" not in line:
                check(False, f"{p.relative_to(ROOT)}:{i}: писатель/читатель индекса бумаги (упразднён, шаг 15)")
    check(not (ROOT / "skills/portfolio-data-loader/scripts/securities_index.py").exists(),
          "securities_index.py должен быть удалён")
    check(n >= 100, f"подозрительно мало файлов в сторожe шага 15: {n}")
    return n


GATE_DOCS = ["game-advisor", "macro-ru-watcher", "portfolio-coherence-audit", "travel-planning", "save-to-library"]


def scan_ai_mode_docs():
    """Режим «без ИИ»: SKILL.md скиллов-писателей Claude-Memory упоминают флаг `_hub/settings.json` / `ai_mode`."""
    for name in GATE_DOCS:
        t = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        check("_hub/settings.json" in t and "ai_mode" in t, f"skills/{name}/SKILL.md: нет правила режима без ИИ (_hub/settings.json, ai_mode)")


def main():
    self_test()
    scan_ai_mode_docs()
    scan_securities_writers()
    n_md = 0
    for sk in SKILLS:
        for p in sorted(sk.rglob("*.md")):
            n_md += 1
            scan_md(p, p.read_text(encoding="utf-8"))
    check(n_md >= 30, f"подозрительно мало .md в скиллах: {n_md}")
    n_py = 0
    for p in sorted(ADVISOR_SCRIPTS.glob("*.py")):
        n_py += 1
        scan_py(p, p.read_text(encoding="utf-8"))
    tokens = measure_c5()
    if ERRORS:
        print(f"FAIL: {len(ERRORS)} нарушений из {CHECKS} проверок")
        for e in ERRORS:
            print(f"  - {e}")
        sys.exit(1)
    print(f"OK: {CHECKS} проверок — {n_md} .md и {n_py} .py без чтения носителей и удалённых команд; "
          f"C5 security_digest ≈ {tokens} токенов на бумагу")


if __name__ == "__main__":
    main()
