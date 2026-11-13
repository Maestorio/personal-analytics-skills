#!/usr/bin/env python3
"""Сторож шага 12 цикла машиночитаемости (schema.md §1 п.3, §4.2, §4.4; decision.md §1 следствия 1–3, R12):
вьюер читает только новый вид данных и объединяет его только модулями (а)(б)(в).

Контракты (по исходнику tools/assets/viewer.js и странице tools/portfolio-integrated-viewer.html):
  1. Нет файла гейтов: ни `gateReviews`, ни `gate-reviews`, ни `getGateEntry`; гейт — `gateOf` через `lwCard` (модуль (б)).
  2. Нет слоя замещения 3.114: `SUPERSEDE_MODE_RE`, `reviewSupersededBy`, `planChangeAfterReview`, `_supersededRow`.
  3. Копии обзора кодом не читаются: `gate_status_snapshot`, `user_constraints`, `conditions_state` (ни `.поле`, ни `['поле']`).
  4. Условия — только строки модуля (а): нет `condition_events` (монитор пишет `condition_findings`), нет `.touched` и `.history`,
     нет `evalCondition`; `CM.merge` вызывается, `conditionsForTicker` идёт через `CM.select`.
  5. «Последнее слово» — одна точка вызова `LW.card` (функция `lwCard`); движок «Сейчас» получает `engineGateInputs()` и `engineCondInputs()`.
  6. Решение владельца между обзорами — без регулярки по прозе: нет `OWNER_DECISION_RX`/`_OWNER_RX` и литералов-регулярок со «владел».
  7. Режим отчёта — по `mode_codes`: нет чтения `fm.mode`/`fm?.mode` строкой; `_isIisReport` смотрит `mode_codes`/`kind`.
  8. Слова — из кодлистов: словари условий/гейта/действующих лиц — `CL.words(...)`; нет `GATE_SET_BY_RU` и литерала `COND_TRIGGER_RU = {`.
  9. `?v=` у `codelists.js`, `conditions-merge.js`, `last-word.js` на странице = первые 8 знаков md5 файла; модули подключены до движка и вьюера.
 10. YAML условий грузится без автодат (`jsyaml.JSON_SCHEMA`); загрузка видит `Portfolio/decisions/`, `conditions-state.json`, `security-attrs.json`.
 11. Кнопки условий шлют события сайта (`api/pv/cond/event`) с `version`; хвост между синками — `cond/state?since=` и `plan/journal?…since=`.
 12. Офлайн-кэш `sw-offline.js`: нет `gate-reviews`, есть новые носители (decisions, conditions-state, security-attrs, macro-chain).
Запуск: python3 tools/tests/test_viewer_ds_contracts.py
"""
import hashlib
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
VJS = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
HTML = (REPO / "tools/portfolio-integrated-viewer.html").read_text(encoding="utf-8")
SW = (REPO / "tools/sw-offline.js").read_text(encoding="utf-8")
# строка версии (история изменений) — не код: сторож её не читает
CODE = "\n".join(ln for ln in VJS.splitlines() if not ln.startswith("const VIEWER_VERSION"))

passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


def absent(token, why):
    hits = [i + 1 for i, ln in enumerate(CODE.splitlines()) if token in ln]
    check(f"нет «{token}» ({why}){' — строки ' + str(hits[:5]) if hits else ''}", not hits)


# 1–2
for tok in ("gateReviews", "gate-reviews", "getGateEntry", "SUPERSEDE_MODE_RE", "reviewSupersededBy", "planChangeAfterReview", "_supersededRow"):
    absent(tok, "файл гейтов и слой замещения удалены")
check("гейт — gateOf через lwCard", re.search(r"function gateOf\(key\)\s*\{\s*const c = lwCard\(key\)", CODE) is not None)
# 3
for f in ("gate_status_snapshot", "user_constraints", "conditions_state"):
    hits = re.findall(rf"(\.{f}\b|\[['\"]{f}['\"]\])", CODE)
    check(f"копия обзора «{f}» кодом не читается ({len(hits)})", not hits)
# 4
absent("condition_events", "монитор пишет condition_findings[]")
check("нет .touched / .history (условия 1.2)", not re.search(r"[\w)\]?]\.(touched|history)\b", CODE))
absent("evalCondition", "статус условия — модуль (а)")
check("строки условий — CM.merge(condDefsAll(), …)", "CM.merge(condDefsAll()" in CODE)
check("conditionsForTicker — через CM.select", re.search(r"function conditionsForTicker\(key\)[\s\S]{0,200}CM\.select\(dsCondRows\(\)", CODE) is not None)
check("находки монитора — condition_findings", "condition_findings" in CODE)
# 5
check("LW.card вызывается ровно в одном месте (lwCard)", len(re.findall(r"\bLW\.card\(", CODE)) == 1 and "function lwCard(key)" in CODE)
n_eng = len(re.findall(r"RebalanceEngine\.runAuto\(", CODE))
n_new = len(re.findall(r"RebalanceEngine\.runAuto\(port, engineGateInputs\(\), engineCondInputs\(\)", CODE))
check(f"движок «Сейчас» — engineGateInputs()/engineCondInputs() во всех вызовах ({n_new} из {n_eng})", n_eng >= 2 and n_new == n_eng)
check("второй аргумент движка нигде не берётся из state.data", not re.search(r"runAuto\([^,]+,\s*state\.data", CODE))
# 6
for tok in ("OWNER_DECISION_RX", "_OWNER_RX"):
    absent(tok, "решение владельца — по событиям и журналу плана")
check("нет регулярок-проверок по прозе со «владел» (.test/.exec/.search/.match)",
      not re.search(r"/[^/\n]*владел[^/\n]*/[gimsuy]*\.(test|exec)\(|\.(search|match)\(/[^/\n]*владел", CODE))
check("ownerDecided — по событиям состояния и журналу плана", re.search(r"function ownerDecided\(isin, curRec, prevRec\)[\s\S]{0,1500}condStateDoc\(\)[\s\S]{0,800}planJournal", CODE) is not None)
# 7
check("режим отчёта не читается строкой (fm.mode)", not re.search(r"\bfm\??\.mode\b|fm\?\.modes\b|\.fm\??\.mode\b", CODE))
check("_isIisReport — по mode_codes/kind", re.search(r"function _isIisReport\(r\)[\s\S]{0,300}mode_codes[\s\S]{0,120}iis_buy", CODE) is not None)
# 8
absent("GATE_SET_BY_RU", "кто записал — кодлист actor / decision_source")
check("нет литерала COND_TRIGGER_RU = {", "COND_TRIGGER_RU = {" not in CODE)
for name, lst in (("COND_TRIGGER_RU", "condition_trigger_type"), ("COND_KIND_RU", "condition_kind"), ("ACTOR_RU", "actor"),
                  ("COND_ACTION_RU", "condition_action"), ("OWNER_MARK_RU", "owner_mark"), ("COND_EVENT_RU", "condition_event")):
    check(f"{name} = CL.words('{lst}')", f"const {name} = CL.words('{lst}');" in CODE)
check("слова статусов гейта — кодлист gate_status", "CL.codes('gate_status').map(k => [k, { label: CL.ru('gate_status', k)" in CODE)
# 9
srcs = re.findall(r'<script src="assets/([\w.-]+)\?v=([\w.]+)"', HTML)
order = [n for n, _ in srcs]
for mod in ("codelists.js", "conditions-merge.js", "last-word.js"):
    md5 = hashlib.md5((REPO / "tools/assets" / mod).read_bytes()).hexdigest()[:8]
    ver = dict(srcs).get(mod)
    check(f"?v= у {mod} = md5 файла ({ver} / {md5})", ver == md5)
check(f"порядок: codelists → conditions-merge → last-word → rebalance-engine → viewer ({order})",
      all(m in order for m in ("codelists.js", "conditions-merge.js", "last-word.js", "rebalance-engine.js", "viewer.js"))
      and order.index("codelists.js") < order.index("conditions-merge.js") < order.index("last-word.js")
      < order.index("rebalance-engine.js") < order.index("viewer.js"))
# 10
check("условия грузятся без автодат (JSON_SCHEMA)", "loadYamlFirstDoc(text, jsyaml.JSON_SCHEMA)" in CODE)
for path in ("'Portfolio/decisions/'", "conditions-state", "security-attrs", "conditions-archive"):
    check(f"загрузка видит {path}", path in CODE)
# 11
check("кнопки условий — POST api/pv/cond/event с version", re.search(r"pvApi\('api/pv/cond/event', body\)", CODE) is not None
      and "version: row.version" in CODE)
check("хвост состояния — cond/state?since=", "api/pv/cond/state' + (since ? '?since='" in CODE)
check("хвост журнала плана — plan/journal …&since=", "'&since=' + encodeURIComponent(since)" in CODE)
check("«открыть заново» не у триггеров date/report_published", re.search(r"byDate = tt === 'date' \|\| tt === 'report_published'", CODE) is not None
      and "перенести срок — через разбор" in CODE)
# 12
check("офлайн-кэш: нет gate-reviews", "gate-reviews" not in SW)
for tok in ("decisions", "conditions-state", "security-attrs", "macro-chain"):
    check(f"офлайн-кэш держит {tok}", tok in SW)

print(f"Итого: {passed} из {passed + failed}" + ("" if not failed else f" (падений: {failed})"))
sys.exit(1 if failed else 0)
