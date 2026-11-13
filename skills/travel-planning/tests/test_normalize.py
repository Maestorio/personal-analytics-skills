"""Тесты scripts/normalize.py — детерминированный нормализатор (все стадии)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "skills" / "travel-planning" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import normalize  # noqa: E402

checks = 0
failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global checks, failed
    checks += 1
    if cond:
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}" + (f" — {detail}" if detail else ""))


print("[1] normalize_delimiters")
check("`-----` → `---`", normalize.normalize_delimiters("a\n-----\nb") == "a\n---\nb")
check("`---` не трогается", normalize.normalize_delimiters("a\n---\nb") == "a\n---\nb")
check("`-{3}` (ровно 3) не трогается", normalize.normalize_delimiters("---") == "---")
check("делиметр с пробелами", normalize.normalize_delimiters("  ------  ") == "---")
check("дефис в прозе не трогается", normalize.normalize_delimiters("про-цена") == "про-цена")

print("[1b] normalize_frontmatter_quotes")
_q_src = ('---\ntitle: “Пекин и Сиань”\nregions:\n- “Пекин”\n- “Сиань”\n'
          'submodes: [“b1”, “b2”]\nname: «Настоящие» кавычки\n---\n\nтело: “не трогать”\n')
_q_out = normalize.normalize_frontmatter_quotes(_q_src)
check("YAML key-value: “…” → \"…\"", 'title: "Пекин и Сиань"' in _q_out)
check("list-элементы: - “…” → - \"…\"", '- "Пекин"' in _q_out and '- "Сиань"' in _q_out)
check("flow-список: [“…”] → [\"…\"]", 'submodes: ["b1", "b2"]' in _q_out)
check("guillemets «…» не тронуты", "«Настоящие»" in _q_out)
check("тело документа не тронуто", "“не трогать”" in _q_out)
check("идемпотентность кавычек",
      normalize.normalize_frontmatter_quotes(_q_out) == _q_out)
check("нет frontmatter → no-op",
      normalize.normalize_frontmatter_quotes("просто “текст”") == "просто “текст”")
check("diff: frontmatter-кавычки",
      any("frontmatter-кавычки" in i for i in normalize.diff_report(_q_src)))

print("\n[2] normalize_dollar (вне кода)")
check("`$80` → `\\$80`", normalize.normalize_dollar("цена $80") == "цена \\$80")
check("уже экранированный не трогается", normalize.normalize_dollar("цена \\$80") == "цена \\$80")
check("в inline-коде не трогается", normalize.normalize_dollar("`$80`") == "`$80`")
check("в fenced-коде не трогается",
      normalize.normalize_dollar("```\n$80\n```") == "```\n$80\n```")
check("`$` без цифры не трогается", normalize.normalize_dollar("$ymbol") == "$ymbol")

print("\n[3] normalize_tidy + полный normalize")
check("хвостовые пробелы убраны", normalize.normalize_tidy("a   \nb\t\n") == "a\nb\n")
_full = normalize.normalize("---\nstage: 1\n-----\n# H\nцена $5   ")
check("полный: делиметр + $ + tidy",
      "-----" not in _full and "\\$5" in _full and not _full.endswith(" "))

print("\n[4] идемпотентность")
sample = "---\nx: 1\n-----\ncost $80 and `$5`\ntrail   "
once = normalize.normalize(sample)
twice = normalize.normalize(once)
check("normalize идемпотентен", once == twice)

print("\n[5] diff_report")
issues = normalize.diff_report("a\n----\n$80  ")
check("diff: делиметр", any("делиметр" in i for i in issues))
check("diff: $-escape", any("$-escape" in i for i in issues))
check("diff: tidy", any("tidy" in i for i in issues))
check("diff чистого текста — пусто", normalize.diff_report("---\nx: 1\n---\nok\n") == [])

print("\n[6] CLI")
r = subprocess.run([sys.executable, str(SCRIPTS / "normalize.py")],
                   input="a\n-----\ncost $9", capture_output=True, text=True)
check("CLI stdout нормализован", r.returncode == 0 and "-----" not in r.stdout and "\\$9" in r.stdout)
r2 = subprocess.run([sys.executable, str(SCRIPTS / "normalize.py"), "--check"],
                    input="a\n-----\n", capture_output=True, text=True)
check("CLI --check exit 1 при наличии правок", r2.returncode == 1)
r3 = subprocess.run([sys.executable, str(SCRIPTS / "normalize.py"), "--check"],
                    input="---\nx: 1\n---\nok\n", capture_output=True, text=True)
check("CLI --check exit 0 на чистом", r3.returncode == 0)

print("\n[7] defensive: parser нормализует `-----`-YAML на входе")
from export import parser as _p  # noqa: E402  (SCRIPTS уже на path)
parsed = _p.parse_stage_text("-----\nstage: 1_dr_reports\ntrip_id: t\n-----\n# Body\n")
check("YAML распарсен несмотря на `-----`-делиметр",
      parsed["frontmatter"].get("stage") == "1_dr_reports", str(parsed["frontmatter"]))

print(f"\n{'=' * 60}")
print(f"normalize: {checks} проверок, {failed} провалено")
print(f"{'=' * 60}")
sys.exit(1 if failed else 0)
