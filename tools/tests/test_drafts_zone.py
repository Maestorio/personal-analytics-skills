#!/usr/bin/env python3
"""Сторож служебной зоны `Claude-Memory/_drafts/` (STL-41, 04.11.2026).

Семь генераторов пишут черновик в `_drafts/` до вывода в чат: FCA — прогноз (отчёт + блок Events YAML),
scenario-builder — матрицу сценариев (вывод + блок Events YAML), hypothesis-stress-tester — патч Tier 2 и полный
текст; forecast-monitor, portfolio-scenario-stress, portfolio-integrated-view, retrospective-forecast-audit — полный
артефакт, а в чат печатают только выжимку (решение владельца 04.11). save-to-library берёт их оттуда (Workflow B1.0,
B1.2/B1.3, C1.0, D1.0, E1.0, G1.0, L1.0), а не из чата, который мог сжаться между сбором и сохранением. Зона служебная: не индексируется, в `_sync_log.md` не попадает. Сторожа раскладки в коде нет —
контракт держится документами, этот тест сверяет их:

1. Раскладка (`claude-memory-layout.md`): `_drafts/` в дереве и в таблице «кто пишет / кто читает» —
   пишут семь скиллов (с именами файлов), читает save-to-library, «не индексируется»; среди исключений D3.
2. FCA (SKILL.md Шаг 6), scenario-builder (Шаг 5), HST (Шаг 6): имена файлов черновика, запись до вывода в чат,
   строка «черновик:» в чат, при недоступном mount — «черновик не записан»; у HST в shared_refs — transport-layer.
3. save-to-library (`workflow-bcde.md`): строка B1.0 — первая в таблице B1, `.hst.md` из неё исключён; приёмка —
   `promote_draft.py --kind forecast` (`--dry-run`, затем по «да»), черновик удаляет приёмка (STL-42); черновики старше
   14 дней — строка владельцу; B1.2 и B1.3 берут патч из `.patch.yaml`; строка C1.0 — первая в таблице C1.
4. Монитор (Шаг 7.5), стресс (Шаг 6), интегрированный вид (Шаг 6), ретро-аудит («Выбор канала вывода»): имена
   черновика, запись до вывода в чат, выжимка, «черновик:», «черновик не записан», «выведи полностью»;
   transport-layer в shared_refs. save-to-library: L1.0/E1.0/D1.0 — в начале своего шага идентификации, G1.0 — тоже;
   особый случай монитора в SKILL.md ищет черновик.
7. Приёмка скриптом (STL-42): `promote_draft.py` знает шесть видов; в B1.0/C1.0/D1.0/E1.0/G1.0/L1.0 — команда
   `promote_draft.py … --kind <вид>` с `--dry-run` и «да», ни `Write(`, ни «черновик можно удалить»; финальные
   сообщения B8/C8/D9/E8/G6/L8 — «принят и удалён»; SKILL.md — скрипт в списке и anti-pattern «Переписывать
   черновик» в группе «Транспорт»; раскладка — читатель `promote-draft`, «удаляется при приёмке».
5. Корневой CLAUDE.md: `_drafts/` среди исключений D3, «генераторы артефактов».
6. Писатель INDEX (`update_index.py`) и сторож библиотеки (`validate_library.py`) зону не упоминают — содержимое
   черновиков не проверяется и не индексируется.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAILS = []
RUN = [0]


def check(name, cond, hint=""):
    RUN[0] += 1
    print(("✓ " if cond else "✗ ") + name + ("" if cond or not hint else f"\n    → {hint}"))
    if not cond:
        FAILS.append(name)


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


layout = read("_shared-references/claude-memory-layout.md")
tree = layout.split("## Кто пишет / кто читает")[0]
check("раскладка: `_drafts/` в дереве", re.search(r"^├── _drafts/", tree, re.M) is not None)
row = next((ln for ln in layout.splitlines() if ln.startswith("| `_drafts/` |")), "")
check("раскладка: строка `_drafts/` в таблице кто пишет / кто читает", bool(row))
WRITERS = {"forecast-confidence-applier": ("<topic>-<forecast_date>.md", ".events.yaml"),
           "scenario-builder": ("scenario-<topic>-<date>.md", ".events.yaml"),
           "hypothesis-stress-tester": ("<topic>-<date>.patch.yaml", ".hst.md"),
           "forecast-monitor": ("monitor-report-<date>.yaml",),
           "portfolio-scenario-stress": ("stress-<date>-<slug>.md", ".yaml"),
           "portfolio-integrated-view": ("integrated-view-<date>.md",),
           "retrospective-forecast-audit": ("<date>-<source-slug>-<period>.md", "<source-slug>-<period>-profile.md")}
writers_col = row.split(" | ")[1] if row.count(" | ") >= 2 else ""
for skill, names in WRITERS.items():
    check(f"раскладка: пишет {skill} ({', '.join(names)})",
          skill in writers_col and all(n in writers_col for n in names))
check("раскладка: читает save-to-library (B1.0, B1.2/B1.3, C1.0, L1.0, E1.0, G1.0, D1.0)",
      "save-to-library" in row and row.index("save-to-library") > len(writers_col)
      and all(w in row for w in ("B1.0", "B1.2/B1.3", "C1.0", "L1.0", "E1.0", "G1.0", "D1.0")))
check("раскладка: зона не индексируется и не в _sync_log", "не индексируется" in row and "_sync_log.md" in row)
d3 = layout.split("**Задокументированные исключения D3")[1].split("**Известный gap")[0] if "**Задокументированные исключения D3" in layout else ""
check("раскладка: черновики — среди исключений D3", "`_drafts/`" in d3)

fca = read("skills/forecast-confidence-applier/SKILL.md")
step6 = fca.split("### Шаг 6")[1].split("## Output Format")[0] if "### Шаг 6" in fca else ""
check("FCA Шаг 6: два файла черновика",
      "_drafts/<topic>-<forecast_date>.md" in step6 and "_drafts/<topic>-<forecast_date>.events.yaml" in step6)
check("FCA Шаг 6: строка «черновик:» в чат и «черновик не записан» без mount",
      "черновик: `_drafts/" in step6 and "черновик не записан" in step6)
check("FCA: черновик пишется до вывода в чат", "до вывода в чат" in step6)


def section(text, start, end):
    return text.split(start)[1].split(end)[0] if start in text and end in text.split(start)[1] else ""


sb = read("skills/scenario-builder/SKILL.md")
sb5 = section(sb, "## Шаг 5 — Сборка блока Events YAML", "## Шаг 5.5")
check("scenario-builder Шаг 5: два файла черновика",
      "_drafts/scenario-<topic>-<date>.md" in sb5 and "_drafts/scenario-<topic>-<date>.events.yaml" in sb5)
check("scenario-builder Шаг 5: до вывода в чат, «черновик:», «черновик не записан», C1.0",
      all(w in sb5 for w in ("до вывода в чат", "черновик: `_drafts/", "черновик не записан", "C1.0")))
check("scenario-builder: transport-layer в shared_refs", "transport-layer" in sb.split("shared_refs:")[1].split("\n")[0])

hst = read("skills/hypothesis-stress-tester/SKILL.md")
hst6 = section(hst, "## Шаг 6 — Сборка блока Events YAML stress-pair", "## Output rules")
check("HST Шаг 6: два файла черновика (патч и полный текст)",
      "_drafts/<topic>-<date>.patch.yaml" in hst6 and "_drafts/<topic>-<date>.hst.md" in hst6)
check("HST Шаг 6: до вывода в чат, «черновик:», «черновик не записан», B1.2/B1.3",
      all(w in hst6 for w in ("до вывода в чат", "черновик: `_drafts/", "черновик не записан", "B1.2/B1.3")))
check("HST: transport-layer в shared_refs", "transport-layer" in hst.split("shared_refs:")[1].split("\n")[0])

bcde = read("skills/save-to-library/references/workflow-bcde.md")
b1 = bcde.split("### B1.")[1].split("### B2.")[0]
rows = [ln for ln in b1.splitlines() if ln.startswith("| **B1.")]
check("save-to-library B1: строка B1.0 — первая", bool(rows) and rows[0].startswith("| **B1.0"), rows[:1])
check("save-to-library B1.0: приёмка promote_draft.py --kind forecast, черновики старше 14 дней",
      bool(rows) and "promote_draft.py" in rows[0] and "--kind forecast" in rows[0] and "старше 14 дней" in rows[0])
check("save-to-library B1.0: `.hst.md` не принимается за черновик прогноза", bool(rows) and "*.hst.md" in rows[0])
for code in ("B1.2", "B1.3"):
    r = next((ln for ln in rows if ln.startswith(f"| **{code}")), "")
    check(f"save-to-library {code}: патч из черновика `.patch.yaml`", ".patch.yaml" in r and ".hst.md" in r)
c1 = bcde.split("### C1.")[1].split("### C2.")[0] if "### C1." in bcde else ""
crows = [ln for ln in c1.splitlines() if ln.startswith("| **C1.")]
check("save-to-library C1: строка C1.0 — первая, черновик сценариев",
      bool(crows) and crows[0].startswith("| **C1.0") and "_drafts/scenario-<topic>-" in crows[0]
      and "--kind scenario" in crows[0])

check("раскладка D3: генераторы артефактов — все семь, четыре печатают выжимку",
      "Генераторы артефактов" in d3 and all(f"`{w}`" in d3 for w in WRITERS) and "выжимк" in d3)


def has_all(text, words):
    return all(w in text for w in words)


COMMON = ("до вывода в чат", "черновик не записан", "выведи полностью")


def shared_refs(text):
    return text.split("shared_refs:")[1].split("\n")[0] if "shared_refs:" in text else ""


fm = read("skills/forecast-monitor/SKILL.md")
fm75 = section(fm, "### 7.5 ", "**Частичный прогон:**")
check("forecast-monitor 7.5: черновик monitor-report, YAML в чат не печатается",
      "_drafts/monitor-report-{YYYY-MM-DD}.yaml" in fm75 and "YAML в чат не печатается" in fm75
      and "черновик: `_drafts/monitor-report-" in fm75)
check("forecast-monitor 7.5: до вывода, «черновик не записан», «выведи полностью»", has_all(fm75, COMMON))
check("forecast-monitor: в чат — дайджест Шага 6 как выжимка",
      "единственное, что монитор печатает в чат" in section(fm, "## Шаг 6 — Сборка дайджеста", "### Принципы"))
check("forecast-monitor: transport-layer в shared_refs", "transport-layer" in shared_refs(fm))

pss = read("skills/portfolio-scenario-stress/SKILL.md")
pss6 = section(pss, "#### Черновик и выжимка в чат", "## Anti-patterns")
check("stress Шаг 6: пара черновика stress-…md + .yaml",
      "_drafts/stress-{YYYY-MM-DD}-{slug}.md" in pss6 and "_drafts/stress-{YYYY-MM-DD}-{slug}.yaml" in pss6)
check("stress Шаг 6: выжимка — ΔP&L по горизонтам, топ-5, tail-флаги, «черновик:»",
      has_all(pss6, ("ΔP&L", "по горизонтам", "топ-5", "tail-флаги", "черновик: `_drafts/stress-")))
check("stress Шаг 6: до вывода, «черновик не записан», «выведи полностью»", has_all(pss6, COMMON))
check("stress: transport-layer в shared_refs", "transport-layer" in shared_refs(pss))

piv = read("skills/portfolio-integrated-view/SKILL.md")
piv6 = section(piv, "### Шаг 6. Черновик", "## Edge cases")
check("integrated-view Шаг 6: черновик integrated-view-{date}.md", "_drafts/integrated-view-{date}.md" in piv6)
check("integrated-view Шаг 6: выжимка — акции vs облигации, joint expectation, что сменилось, «черновик:»",
      has_all(piv6, ("акции vs облигации", "joint expectation", "что сменилось", "черновик: `_drafts/integrated-view-")))
check("integrated-view Шаг 6: до вывода, «черновик не записан», «выведи полностью»", has_all(piv6, COMMON))
check("integrated-view: transport-layer в shared_refs", "transport-layer" in shared_refs(piv))

rfa = read("skills/retrospective-forecast-audit/SKILL.md")
rfa_ch = section(rfa, "### Черновик в файл и выжимка в чат", "### Что делать, если контекст")
check("ретро-аудит: пара черновика — полный отчёт и профиль",
      "_drafts/<YYYY-MM-DD>-<source-slug>-<period>.md" in rfa_ch and "_drafts/<source-slug>-<period>-profile.md" in rfa_ch)
check("ретро-аудит: выжимка — шапка, сводка трёх шкал, trust-вердикт, §8, «черновик:»",
      has_all(rfa_ch, ("шапка", "трёх шкал", "trust-вердикт", "§8", "черновик: `_drafts/")))
check("ретро-аудит: до вывода, «черновик не записан», «выведи полностью»", has_all(rfa_ch, COMMON))
check("ретро-аудит: transport-layer в shared_refs", "transport-layer" in shared_refs(rfa))


def first_para(text, start, end, code):
    body = section(text, start, end)
    paras = [p for p in body.split("\n\n")[1:] if p.strip()]
    return paras[0] if paras and paras[0].startswith(f"**{code}") else ""


wl = read("skills/save-to-library/references/workflow-l.md")
l10 = next((p for p in wl.split("\n\n") if p.startswith("**L1.0")), "")
check("save-to-library L1.0: черновик monitor-report до L1, приёмка --kind monitor-report",
      bool(l10) and wl.index("**L1.0") < wl.index("**L1. ") and "_drafts/monitor-report-" in l10
      and "--kind monitor-report" in l10)
fgh = read("skills/save-to-library/references/workflow-fghijk.md")
ACCEPT = {"B1.0": rows[0] if rows else "", "C1.0": crows[0] if crows else "", "L1.0": l10}
for code, text, start, end, name, kind in (("D1.0", bcde, "### D1.", "### D2.", "-profile.md", "retro-audit"),
                                           ("E1.0", bcde, "### E1.", "### E2.", "_drafts/stress-", "stress"),
                                           ("G1.0", fgh, "### G1.", "### G2.", "_drafts/integrated-view-",
                                            "integrated-view")):
    para = first_para(text, start, end, code)
    ACCEPT[code] = para
    check(f"save-to-library {code}: первый абзац шага, черновик, приёмка --kind {kind}",
          bool(para) and name in para and f"--kind {kind}" in para)
stl = read("skills/save-to-library/SKILL.md")
check("save-to-library: особый случай монитора ищет черновик _drafts/",
      "_drafts/monitor-report-" in section(stl, "**Особый случай — после forecast-monitor.**", "\n\n"))

# 7. Приёмка скриптом (STL-42)
promote = read("skills/save-to-library/scripts/promote_draft.py")
kinds = re.search(r"^KINDS = \((.*)\)$", promote, re.M)
check("promote_draft.py: шесть видов приёмки",
      bool(kinds) and all(f'"{k}"' in kinds.group(1) for k in
                          ("forecast", "scenario", "stress", "integrated-view", "monitor-report", "retro-audit")))
for code, para in ACCEPT.items():
    check(f"save-to-library {code}: приёмка командой с --dry-run и «да», без Write черновика",
          "promote_draft.py --root" in para and "--dry-run" in para and "«да»" in para
          and "Write(" not in para and "черновик можно удалить" not in para and "модель не переписывает" in para)
finals = {"B8": section(bcde, "### B8.", "# Workflow C"), "C8": section(bcde, "### C8.", "# Workflow D"),
          "D9": section(bcde, "### D9.", "# Workflow E"), "E8": section(bcde, "### E8.", "**Если какое-то поле"),
          "G6": section(fgh, "### G6.", "# Workflow H"), "L8": section(wl, "**L8.", "**Anti-patterns")}
for code, text in finals.items():
    check(f"save-to-library {code}: финальное сообщение — черновик принят и удалён",
          "ринят и удалён" in text and not re.search(r"\{При (B1\.0|C1\.0)[^\n]*можно удалить", text)
          and ("можно удалить: _drafts/{basename}" not in text))
stl_tr = section(stl, "### Транспорт", "## Concurrency Guard")
check("save-to-library SKILL.md: anti-pattern «Переписывать черновик» в группе «Транспорт»",
      "Переписывать черновик" in stl_tr and "promote_draft.py" in stl_tr)
check("save-to-library SKILL.md: promote_draft.py в списке скриптов", "- `scripts/promote_draft.py`" in stl)
check("раскладка: читатель _drafts — promote-draft, черновик удаляется при приёмке",
      "`promote-draft`" in row and "удаляется при приёмке" in row)

claude = read("CLAUDE.md")
d3_root = claude.split("- **D3:**")[1].split("- **Транспорт")[0] if "- **D3:**" in claude else ""
check("CLAUDE.md: `_drafts/` среди исключений D3", "`_drafts/`" in d3_root)
check("CLAUDE.md: черновики пишут генераторы артефактов", "Генераторы артефактов" in d3_root)

for rel in ("skills/save-to-library/scripts/update_index.py", "skills/revise-memory-remote/scripts/validate_library.py"):
    check(f"{rel.split('/')[-1]}: зона `_drafts` не индексируется и не проверяется", "_drafts" not in read(rel))

print(f"\nИтого: {RUN[0] - len(FAILS)} из {RUN[0]} проверок")
sys.exit(1 if FAILS else 0)
