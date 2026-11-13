#!/usr/bin/env python3
"""Кодлисты портфельного контура (шаг 2 цикла машиночитаемости, schema.md §1 п.5, §3.4).

Один источник — `_shared-references/codelists.json`; читатели берут коды и слова через загрузчик
(`_shared-references/codelists.py`, страница — сгенерированный `tools/assets/codelists.js`, hub-api и
hub-notify — сам JSON). Тест держит:
  (а) у каждого кода каждого списка непустое `ru`;
  (б) `tools/assets/codelists.js` = генерация из JSON, а `?v=` в странице = md5 файла (иначе браузер держит старый);
  (в) сторож копий: в читателях нет литеральных словарей и перечней из JSON (регулярки ниже, с пояснением);
  (г) карты ссылаются только на существующие коды;
  (д) legacy-код имеет `migrate_to` из того же списка либо явный null «значение снимается» (и сам этот код не legacy);
  (е) `defaults` — целые > 0;
  (ж) наборы допустимых кодов у читателей те же, что были до перевода на JSON (поведение не менялось);
  (з) канонический порядок: вердикты BUY → … → SELL, затем legacy; план и статус — порядок выпадающих списков.

Запуск: python3 tools/tests/test_codelists.py
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SHARED = REPO / "_shared-references"
sys.path.insert(0, str(SHARED))
import codelists  # noqa: E402

FAILS = []


def check(name, cond, hint=""):
    print(("✓ " if cond else "✗ ") + name + ("" if cond or not hint else f"\n    → {hint}"))
    if not cond:
        FAILS.append(name)


DOC = json.loads((SHARED / "codelists.json").read_text(encoding="utf-8"))
LISTS, MAPS = DOC["lists"], DOC["maps"]

# ── схема документа ──
SPEC_LISTS = {"verdict", "user_plan", "user_status", "gate_status", "actor", "ticker_class", "asset_class",
              "condition_kind", "condition_trigger_type", "condition_action", "condition_event", "owner_mark",
              "decision_source", "condition_source", "report_kind", "mode_codes", "block_reason",
              "verification_priority", "alert_kind",
              "fundamental_level", "credit_quality", "alert_severity",   # 03.11 (R27): слова вместо кодов на экране
              "reinvest_source", "bond_bucket",   # 03.11 (R30): исход условия «реинвестировать» — откуда и куда
              "monitoring_result",   # 04.11 (FM-20): итог проверки пункта monitoring[] в monitor-report
              "game_state", "game_platform", "game_rating", "game_progress"}   # игры: оверлей Gaming/user-state.json (gaming-user@1), страница и скилл — один enum
SPEC_MAPS = {"verdict_to_gate", "verdict_direction", "user_plan_direction", "gate_to_block", "ticker_aliases"}
check("schema_version = codelists@1", DOC.get("schema_version") == "codelists@1")
check(f"списки — ровно из §3.4 (лишние {sorted(set(LISTS) - SPEC_LISTS)}, нет {sorted(SPEC_LISTS - set(LISTS))})",
      set(LISTS) == SPEC_LISTS)
check(f"карты — ровно из §3.4 (лишние {sorted(set(MAPS) - SPEC_MAPS)}, нет {sorted(SPEC_MAPS - set(MAPS))})",
      set(MAPS) == SPEC_MAPS)

# ── (а) слова ──
no_ru = [f"{n}.{c}" for n, l in LISTS.items() for c, e in l.items()
         if not isinstance(e, dict) or not isinstance(e.get("ru"), str) or not e["ru"].strip()]
check(f"(а) у каждого кода есть непустое ru (нет: {no_ru})", not no_ru,
      "добавь слово коду в codelists.json — код без слова на экране показался бы как есть")
KNOWN_FIELDS = {"ru", "short", "since", "legacy", "migrate_to", "effect", "hint", "weekly"}
odd = [f"{n}.{c}.{k}" for n, l in LISTS.items() for c, e in l.items() for k in e if k not in KNOWN_FIELDS]
check(f"поля кодов — из известных (лишние: {odd})", not odd)

# ── (г) карты ──
def _codes(n):
    return set(LISTS[n])


bad = []
for k, v in MAPS["verdict_to_gate"].items():
    if k not in _codes("verdict") or v not in _codes("gate_status"):
        bad.append(f"verdict_to_gate {k}→{v}")
for k, v in MAPS["verdict_direction"].items():
    if k not in _codes("verdict") or v not in ("up", "flat", "down"):
        bad.append(f"verdict_direction {k}→{v}")
for k, v in MAPS["user_plan_direction"].items():
    if k not in _codes("user_plan") or v not in ("up", "flat", "down"):
        bad.append(f"user_plan_direction {k}→{v}")
for k, v in MAPS["gate_to_block"].items():
    if k not in _codes("gate_status") or v not in _codes("block_reason"):
        bad.append(f"gate_to_block {k}→{v}")
for k, v in MAPS["ticker_aliases"].items():
    if not (isinstance(k, str) and isinstance(v, str) and k.isupper() and v.isupper()):
        bad.append(f"ticker_aliases {k}→{v}")
check(f"(г) карты ссылаются только на существующие коды (плохо: {bad})", not bad)
check("(г) направление есть у каждого вердикта",
      set(MAPS["verdict_direction"]) == _codes("verdict"))
check("(г) verdict_to_gate покрывает все не-legacy вердикты",
      set(MAPS["verdict_to_gate"]) == {c for c, e in LISTS["verdict"].items() if not e.get("legacy")})
check("(г) user_plan_direction покрывает все коды плана", set(MAPS["user_plan_direction"]) == _codes("user_plan"))

# ── (д) legacy ──
bad = []
for n, l in LISTS.items():
    for c, e in l.items():
        if e.get("legacy"):
            t = e.get("migrate_to")
            if t is None and "migrate_to" in e:   # явное «значение снимается» (game_rating.брошено)
                continue
            if t not in l or l[t].get("legacy"):
                bad.append(f"{n}.{c}→{t}")
        elif "migrate_to" in e:
            bad.append(f"{n}.{c}: migrate_to без legacy")
check(f"(д) legacy-код имеет migrate_to из того же списка, не legacy (плохо: {bad})", not bad)
legacy_verdicts = [c for c, e in LISTS["verdict"].items() if e.get("legacy")]
check("(д) в кодлисте verdict legacy-кодов нет (прежние коды облигаций сняты после переключения)",
      not legacy_verdicts and not ({"HOLD_ADD", "RED_FLAG", "MATURE", "HOLD_NO_OFFER"} & set(LISTS["verdict"])
                                   | {"HOLD_ADD", "RED_FLAG", "MATURE", "HOLD_NO_OFFER"} & set(MAPS["verdict_direction"])))

# ── (е) defaults ──
d = DOC.get("defaults") or {}
check("(е) defaults — целые > 0 (флаг noai_gate_blocks — bool)",
      d and all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for k, v in d.items() if k != "noai_gate_blocks")
      and isinstance(d.get("noai_gate_blocks"), bool))
check("(е) defaults — ключи схемы §3.4",
      d == {"review_days": 60, "add_cooldown_days": 21, "ipo_pause_quarters": 8, "report_window_days": 3, "plan_tolerance_pp": 1,
          "noai_gate_blocks": True, "no_reversal_days": 14, "known_dates_horizon_days": 7})

# ── (з) порядок ──
check("(з) порядок вердиктов канонический (по нему сортирует вьюер)",
      list(LISTS["verdict"]) == ["BUY", "ADD", "HOLD", "HOLD_TO_MAT", "WATCH", "TRIM", "SELL"])
check("(з) порядок плана — как в выпадающем списке вьюера", list(LISTS["user_plan"]) == ["KEEP", "BALANCE", "WAIT", "SELL", "BUY"])
check("(з) порядок статуса — как в выпадающем списке вьюера", list(LISTS["user_status"]) == ["DONE", "DEFERRED", "ORDER", "NOTED"])
check("(з) порядок статусов гейта — как в легенде вьюера",
      list(LISTS["gate_status"]) == ["new_position", "review_needed", "reviewed_keep", "reviewed_buy_more",
                                     "reviewed_under_review", "reviewed_reduce", "review_aging", "divested"])
check("(з) mode_codes — коды схемы §3.4 (+ legacy «4»)",
      codelists.codes("mode_codes", legacy=False) == ["1", "2", "3", "4a", "4b", "5a", "5b", "6", "7", "8", "9", "free"])

# ── загрузчик ──
check("загрузчик: ru/word/is_legacy/map_/defaults",
      codelists.ru("verdict", "HOLD") == "Держать" and codelists.ru("verdict", "XYZ") == "XYZ"
      and codelists.word("condition_trigger_type", "price_below", short=True) == "порог цены"
      and codelists.is_legacy("actor", "user") and not codelists.is_legacy("actor", "owner")
      and codelists.map_("ticker_aliases") == {"RENT": "XXXXXX"} and codelists.defaults()["review_days"] == 60)

# ── (б) JS-копия ──
JS = REPO / "tools/assets/codelists.js"
GEN = "python3 _shared-references/codelists.py --emit-js tools/assets/codelists.js"
check("(б) tools/assets/codelists.js = генерация из codelists.json",
      JS.is_file() and JS.read_text(encoding="utf-8") == codelists.render_js(), f"перегенерируй: {GEN}")
_html = (REPO / "tools/portfolio-integrated-viewer.html").read_text(encoding="utf-8")
_md5 = hashlib.md5(JS.read_bytes()).hexdigest()[:8] if JS.is_file() else "?"
_iv = [_html.find(f"assets/codelists.js?v={_md5}"), _html.find("assets/rebalance-engine.js?v="), _html.find("assets/viewer.js?v=")]
check("(б) вьюер подключает codelists.js?v=<md5[:8] файла> ДО движка и viewer.js",
      0 <= _iv[0] < _iv[1] < _iv[2],
      f"в portfolio-integrated-viewer.html: <script src=\"assets/codelists.js?v={_md5}\"></script> перед rebalance-engine.js")

NODE = shutil.which("node")
if NODE:
    r = subprocess.run([NODE, "-e", """
const CL = require(process.argv[1]);
const E = require(process.argv[2]);
process.stdout.write(JSON.stringify({ codes: CL.codes('verdict', false), all: CL.codes('verdict'),
  ru: CL.ru('gate_status', 'review_aging'), unk: CL.ru('verdict', 'XYZ'), short: CL.short('condition_trigger_type', 'price_above'),
  words: CL.words('user_plan'), hint: CL.words('gate_status', 'hint').divested, leg: CL.isLegacy('actor', 'user'),
  map: CL.map('ticker_aliases'), ok: typeof E.runAuto === 'function' }));
""", str(JS), str(REPO / "tools/assets/rebalance-engine.js")], capture_output=True, text=True, timeout=30)
    try:
        o = json.loads(r.stdout)
    except ValueError:
        o = {}
    check("(б) JS-API CL: codes/ru/short/words/isLegacy/map (и движок грузится в node)",
          o.get("codes") == codelists.codes("verdict", legacy=False) and o.get("all") == codelists.codes("verdict")
          and o.get("ru") == LISTS["gate_status"]["review_aging"]["ru"] and o.get("unk") == "XYZ" and o.get("short") == "порог цены"
          and o.get("words") == codelists.words("user_plan") and o.get("leg") is True
          and o.get("hint") == LISTS["gate_status"]["divested"]["hint"]
          and o.get("map") == {"RENT": "XXXXXX"} and o.get("ok") is True, r.stderr.strip()[:300])
else:
    print("· (б) JS-API: пропуск — нет node")

# ── (в) сторож копий ──
# Файлы-читатели (шаг 2): в них не должно быть литералов словарей/перечней, которые живут в codelists.json.
GUARDED = [
    "_shared-references/terms_ru.py", "_shared-references/gate_status_ru.py", "_shared-references/constraint_engine.py",
    "tools/assets/viewer.js", "tools/assets/rebalance-engine.js",
    "tools/hosting/api/server.py", "tools/hosting/notify/notifier.py",
    "skills/save-to-library/scripts/assemble_artifact.py", "skills/save-to-library/scripts/decision_write.py",
    "skills/save-to-library/scripts/apply_condition.py",
    "skills/ru-portfolio-advisor/scripts/gate_aware_sizing.py", "skills/ru-portfolio-advisor/scripts/prior_digest.py",
    "skills/portfolio-data-loader/scripts/decision_journal.py", "skills/revise-memory-remote/scripts/validate_library.py",
    "_shared-references/ds_schemas.py",
    "_shared-references/conditions_merge.py", "tools/assets/conditions-merge.js",
]
# Регулярка → что она ловит. Слова — характерные значения словарей (любая копия словаря их содержит);
# коды — литералы в кавычках, которые встречаются только в копиях перечней (legacy-коды облигаций,
# пары «код: слово», наборы статусов блокировки). Код в комментарии сторож не трогает — только в кавычках.
GUARD = [
    (r"Держать до погашения", "слово вердикта HOLD_TO_MAT (словарь вердиктов)"),
    (r"Держать, можно добирать", "слово вердикта HOLD_ADD"),
    (r"[Кк]расный флаг['\"]", "слово вердикта RED_FLAG"),
    (r"['\"]HOLD_ADD['\"]", "legacy-код HOLD_ADD в перечне (направление/допустимые вердикты — из кодлиста)"),
    (r"['\"](?:SELL|TRIM)['\"]\s*,\s*['\"](?:SELL|TRIM)['\"]\s*,\s*['\"]RED_FLAG['\"]",
     "legacy-код RED_FLAG в перечне вердиктов «вниз» (RED_FLAG оценки фундаментала — другой перечень)"),
    (r"['\"]HOLD_TO_MAT['\"]\s*[:,]", "HOLD_TO_MAT в словаре или перечне вердиктов"),
    (r"reviewed_buy_more['\"]?\s*:\s*(\{\s*label|['\"]Наращивать)", "словарь подписей статусов гейта"),
    (r"['\"]Наращивать['\"]", "подпись статуса гейта reviewed_buy_more"),
    (r"['\"]Оценка устарела['\"]", "прежняя подпись статуса гейта review_aging"),
    (r"['\"]срок решения вышел['\"]", "подпись статуса review_aging (кодлист gate_status)"),
    (r"['\"]новая, без разбора['\"]", "подпись статуса new_position (кодлист gate_status)"),
    (r"\{\s*['\"]?HIGH['\"]?\s*:\s*['\"](?:высок|важно|требует)", "словарь уровней HIGH/MEDIUM/LOW (fundamental_level, credit_quality, alert_severity)"),
    (r"['\"]привести к плану['\"]", "слово плана BALANCE (словарь плана)"),
    (r"['\"]поставил заявку['\"]", "слово статуса ORDER (словарь статуса плана)"),
    (r"['\"]Тактическая ребалансировка['\"]", "словарь видов отчёта (REPORT_KIND_RU)"),
    (r"['\"]обзор облигаций за неделю['\"]", "словарь режимов (MODE_RU)"),
    (r"['\"]?RENT['\"]?\s*:\s*['\"]XXXXXX['\"]", "псевдонимы тикеров (TICKER_ALIASES)"),
    (r"['\"]new_position['\"]\s*,\s*['\"]review_needed['\"]\s*,\s*['\"]reviewed_under_review['\"]",
     "набор блокирующих статусов гейта (maps.gate_to_block)"),
    (r"['\"]KEEP['\"]\s*,\s*['\"]BALANCE['\"]\s*,\s*['\"]WAIT['\"]", "перечень кодов плана (server PLAN_USER_PLANS)"),
    (r"['\"]DONE['\"]\s*,\s*['\"]DEFERRED['\"]", "перечень кодов статуса плана"),
    (r"['\"]не срочно['\"]", "слова приоритета проверки (verification_priority)"),
    (r"['\"]катализатор не случился['\"]", "слова видов предупреждений монитора (alert_kind)"),
    (r"\{\s*['\"]?BUY['\"]?\s*:\s*['\"]Докупать['\"]", "словарь вердиктов «код: слово»"),
    (r"['\"]BUY['\"]\s*,\s*['\"]SELL['\"]\s*,\s*['\"]TRIM['\"]\s*,\s*['\"]ADD['\"]", "inline-перечень вердиктов-сделок"),
    (r"['\"]BUY['\"]\s*,\s*['\"]ADD['\"]\s*,\s*['\"]HOLD['\"]", "inline-порядок вердиктов"),
    (r"\{\s*['\"]BUY['\"]\s*,\s*['\"]TRIM['\"]\s*,\s*['\"]SELL['\"]\s*,\s*['\"]ADD['\"]\s*\}", "набор вердиктов-сделок"),
    (r"['\"]reviewed_keep['\"]\s*,\s*['\"]reviewed_buy_more['\"]", "перечень статусов гейта (кодлист gate_status)"),
]
hits = []
for rel in GUARDED:
    txt = (REPO / rel).read_text(encoding="utf-8")
    for rx, why in GUARD:
        for m in re.finditer(rx, txt):
            line = txt.count("\n", 0, m.start()) + 1
            hits.append(f"{rel}:{line} «{m.group(0)}» — {why}")
check(f"(в) в читателях нет копий словарей и перечней кодлистов ({len(hits)})", not hits,
      "\n    → ".join(hits[:20]) + "\n    → возьми значение из codelists (Python: codelists.py, страница: CL из assets/codelists.js)")

# ── (ж) поведение: наборы кодов у читателей те же, что до перевода на JSON ──
sys.path.insert(0, str(REPO / "skills/save-to-library/scripts"))
sys.path.insert(0, str(REPO / "skills/ru-portfolio-advisor/scripts"))
sys.path.insert(0, str(REPO / "skills/portfolio-data-loader/scripts"))
sys.path.insert(0, str(REPO / "skills/revise-memory-remote/scripts"))
import assemble_artifact as AA  # noqa: E402
import apply_condition as AC  # noqa: E402
import constraint_engine as CE  # noqa: E402
import decision_journal as DJ  # noqa: E402
import ds_schemas as DSS  # noqa: E402
import gate_aware_sizing as GAS  # noqa: E402
import last_word as LWP  # noqa: E402
import gate_status_ru as GS  # noqa: E402
import prior_digest as PD  # noqa: E402
import terms_ru as TR  # noqa: E402
import validate_library as VL  # noqa: E402

GATE8 = {"new_position", "review_needed", "reviewed_keep", "reviewed_buy_more", "reviewed_under_review",
         "reviewed_reduce", "review_aging", "divested"}
BLOCK4 = {"new_position", "review_needed", "reviewed_under_review", "review_aging"}
check("(ж) assemble_artifact: вердикты обзора акций/облигаций и направленные — прежние",
      AA.VALID_ADVISOR_VERDICT_STOCK == {"BUY", "HOLD", "TRIM", "SELL", "ADD", "WATCH"}   # шаг 8: единый словарь — WATCH и у акций
      and AA.VALID_ADVISOR_VERDICT_BOND == {"BUY", "HOLD", "TRIM", "SELL", "ADD", "HOLD_TO_MAT", "WATCH",
}
      and AA.DIRECTIONAL_VERDICTS == {"BUY", "ADD", "TRIM", "SELL"}
      and AA._MR_CATEGORIES == {"stale", "horizon_passed", "event_window", "factor_breach", "source_dead",
                                "prediction_due", "catalyst_missed"})
# apply_condition с шага 6 пишет conditions@2: допустимые коды — у валидатора ds_schemas (ниже), у скрипта —
# только конфликты crosscheck по карте verdict_direction 
check("(ж) apply_condition (conditions@2): конфликты crosscheck — по verdict_direction, actor — из ds_schemas",
      AC._CONFLICT_IF_SELL == {"BUY", "ADD", "HOLD", "HOLD_TO_MAT", "WATCH"}
      and AC._CONFLICT_IF_BUY == {"SELL", "TRIM"}
      and AC.ACTORS == DSS.CODELISTS["actor"] and AC.WINDOW_DAYS == DOC["defaults"]["report_window_days"])
# apply_gate_review.py удалён в шаге 8 (файл гейтов упразднён, schema.md §4.4); validate_library с DS-RMR файл
# гейтов не проверяет — коды носителей схемы берёт у ds_schemas
check("(ж) validate_library: перечней гейта нет, валидатор — ds_schemas; apply_gate_review удалён",
      not hasattr(VL, "VALID_GATE_STATUSES") and not hasattr(VL, "codelists") and VL.ds_schemas is DSS
      and not (REPO / "skills/save-to-library/scripts/apply_gate_review.py").exists())
check("(ж) constraint_engine / gate_aware_sizing: сделки и блокирующие статусы — прежние",
      CE.ACTIONABLE_VERDICTS == {"BUY", "TRIM", "SELL", "ADD"} and GAS.BLOCKING_GATE_STATUSES == BLOCK4)
check("(з) defaults.noai_gate_blocks = true (решение 11.11: «без ИИ» блокирует как «с ИИ»; false — откат) читают оба зеркала модуля (б)",
      DOC["defaults"].get("noai_gate_blocks") is True and LWP.NOAI_GATE_BLOCKS is True
      and "D.noai_gate_blocks === true" in (REPO / "tools/assets/last-word.js").read_text(encoding="utf-8"))
check("(ж) decision_journal: направление эпизода по карте verdict_direction",
      DJ.PLUS == {"BUY", "ADD"} and DJ.MINUS == {"TRIM", "SELL"}
      and DJ.direction("hold_to_mat") is None and DJ.direction("WATCH") is None)
check("(ж) prior_digest: виды отчётов разбора — прежние + целевой код оценки качества quality_review (шаг 10)",
      PD._REVIEW_KINDS == {"single_analysis", "tactical_rebalance", "stock_quality", "quality_review"})
check("(ж) ds_schemas: перечни целевой схемы — не-legacy коды кодлистов, defaults из JSON",
      DSS.CODELISTS["verdict"] == ("BUY", "ADD", "HOLD", "HOLD_TO_MAT", "WATCH", "TRIM", "SELL")
      and DSS.CODELISTS["condition_event"] == ("fired", "expired", "event_found", "owner_mark", "done", "reopened")
      and "user" not in DSS.CODELISTS["actor"] and "owner" in DSS.CODELISTS["actor"]
      and DSS.DEFAULTS == DOC["defaults"] and "ticker_class" not in DSS.CODELISTS)
check("(ж) terms_ru / gate_status_ru: прежние публичные имена, значения из JSON",
      TR.VERDICT_RU == codelists.words("verdict") and TR.USER_PLAN_RU == codelists.words("user_plan")
      and TR.USER_STATUS_RU == codelists.words("user_status") and TR.MODE_RU == codelists.words("mode_codes")
      and TR.verdict_word("HOLD") == "Держать" and TR.mode_word("4") == "разбор бумаги"
      and set(GS.GATE_STATUS_RU) == GATE8 and GS.label("reviewed_keep") == LISTS["gate_status"]["reviewed_keep"]["ru"]
      and all(GS.effect(c) for c in GATE8))

sys.path.insert(0, str(REPO / "tools/hosting/api"))
sys.path.insert(0, str(REPO / "tools/hosting/notify"))
import notifier as N  # noqa: E402
import server as S  # noqa: E402
check("(ж) server: допустимые user_plan / user_status и слова — из кодлистов, прежние",
      S.PLAN_USER_PLANS == ("KEEP", "BALANCE", "WAIT", "SELL", "BUY")
      and S.PLAN_STATUS_CODES == ("DONE", "DEFERRED", "ORDER", "NOTED")
      and S.PLAN_USER_PLAN_WORD == codelists.words("user_plan") and S.PLAN_USER_STATUS_WORD == codelists.words("user_status"))
check("(ж) notifier: VERDICT_WORD = слова verdict строчными, plain() заменяет коды (длинные раньше коротких)",
      N.VERDICT_WORD == {k: v.lower() for k, v in codelists.words("verdict").items()}
      and N.plain("HOLD_TO_MAT, HOLD") == "держать до погашения, держать")

# ── сторож корзин облигаций (4.2.4): кодлист bond_bucket = ключам корзин плана ──
# Ключи bond_buckets[].key в Portfolio/plan.json пишет только сайт (hub-api, PLAN_BUCKET_KEYS — перечень допустимых путей
# bond_buckets.<ключ>.share); вьюер рисует корзины по PLAN_BUCKET_KEYS; исход условия reinvest.target сверяется с кодлистом
# bond_bucket (ds_schemas). Новая корзина в плане без кода в кодлисте (или наоборот) — падение здесь.
_srv_txt = (REPO / "tools/hosting/api/server.py").read_text(encoding="utf-8")
_vw_txt = (REPO / "tools/assets/viewer.js").read_text(encoding="utf-8")
_m_srv = re.search(r"^PLAN_BUCKET_KEYS = \(([^)]*)\)", _srv_txt, re.M)
_m_vw = re.search(r"^const PLAN_BUCKET_KEYS = \[([^\]]*)\]", _vw_txt, re.M)
_keys = lambda m: re.findall(r"'([^']+)'|\"([^\"]+)\"", m.group(1)) if m else []
_srv_keys = [a or b for a, b in _keys(_m_srv)]
_vw_keys = [a or b for a, b in _keys(_m_vw)]
_cl_keys = list(LISTS["bond_bucket"])
check(f"корзины: кодлист bond_bucket = ключам корзин плана в hub-api (PLAN_BUCKET_KEYS) "
      f"(лишние в кодлисте {sorted(set(_cl_keys) - set(_srv_keys))}, нет в кодлисте {sorted(set(_srv_keys) - set(_cl_keys))})",
      len(_srv_keys) == 9 and set(_cl_keys) == set(_srv_keys) and len(_cl_keys) == len(set(_cl_keys)))
check(f"корзины: вьюер PLAN_BUCKET_KEYS = кодлист bond_bucket ({_vw_keys})", set(_vw_keys) == set(_cl_keys) and len(_vw_keys) == len(_cl_keys))
sys.path.insert(0, str(REPO / "skills/portfolio-data-loader/scripts"))
try:
    from parse_portfolio import _bond_bucket_key  # noqa: E402
    _ld = {k for k in (_bond_bucket_key(t, None) for t in ("USD", "EUR", "CNY")) if k} | {
        _bond_bucket_key(t, sb) for t in ("ОФЗ",) for sb in (">10", "<10", "Флоат")} | {
        _bond_bucket_key("КОРП", sb) for sb in ("AA+", "A", "B+")}
    check(f"корзины: ключи загрузчика (_bond_bucket_key, план из «Общего баланса») ⊆ кодлиста ({sorted(_ld)})", _ld <= set(_cl_keys) and len(_ld) == 9)
except ImportError as e:
    check(f"корзины: загрузчик импортируется ({e})", False)
_ds = (SHARED / "ds_schemas.py").read_text(encoding="utf-8")
check("корзины: валидатор reinvest.target сверяет с кодлистом bond_bucket (не с литеральным перечнем)",
      'CODELISTS["bond_bucket"]' in _ds and "ОФЗ/>10" not in _ds)

# ── деплой и упаковка ──
_dep = (REPO / "tools/deploy.zsh").read_text(encoding="utf-8")
_cmp = (REPO / "tools/hosting/docker-compose.yml").read_text(encoding="utf-8")
check("деплой: codelists.json едет в _nas/api/, загрузчик с JSON — в pdl/_shared-references/ (оттуда же берёт hub-notify, шаг 7)",
      'for d in api; do' in _dep and '"$NAS_STAGE/$d/codelists.json"' in _dep
      and "for f in codelists.py codelists.json; do" in _dep and "for f in conditions_merge.py ds_schemas.py; do" in _dep)
check("compose: hub-api видит /app/codelists.json, hub-notify — папку notify/ целиком",
      "./api/codelists.json:/app/codelists.json:ro" in _cmp and "./notify:/app:ro" in _cmp)
_pack = (REPO / "pack.sh").read_text(encoding="utf-8")
check("pack.sh: общий модуль по импорту (`import X` / `from X import`) едет в scripts/ с данными X.json, рекурсивно "
      "(скрипт с `import codelists` получает codelists.py и codelists.json)",
      "shared_import_files()" in _pack and "(import|from)[[:space:]]+" in _pack
      and '"$SHARED_DIR/$name.json"' in _pack and 'queue+=($(module_imports "$SHARED_DIR/$name.py"))' in _pack
      and 'shared_import_files "$SCRIPTS_DIR"' in _pack and 'shared_import_files "$dir/scripts" -r' in _pack)

print()
if FAILS:
    print(f"✗ test_codelists: провалено {len(FAILS)}")
    sys.exit(1)
print("✓ test_codelists: всё зелёное")
