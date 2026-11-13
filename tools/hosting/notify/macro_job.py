"""Макросрез РФ без LLM по расписанию (API-1, пробный месяц с 2026-10-21).

Та же реализация, что у скилла macro-ru-watcher: skills/macro-ru-watcher/scripts/build_macro.py
(на NAS deploy.zsh кладёт её копию в _nas/notify/macro/). Инфляция г/г — месячная из таблицы
cbr.ru/hd_base/infl/ (недельной в API нет), с пометкой о несопоставимости со срезами скилла.

Пишет в macro-snapshots/auto/ru-<дата>.md и .json — ОТДЕЛЬНО от срезов скилла. Плашка и графики
«Макро» вьюера читают автосрез; история z-score каждого индикатора — тоже из auto/*.json (одного
источника, без смешивания со срезами скилла; при нехватке автосрезов — откат на ru-*.md целиком,
build_macro.AUTO_MIN_DELTAS). Недельная инфляция — отдельно, macro-snapshots/inflation/ (скилл / форма).
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# В контейнере файл лежит в /app/ — двух уровней вверх там нет (HERE.parents[2] → IndexError
# при импорте, hub-notify падал по кругу 2026-10-21), поэтому путь репозитория — только если он есть.
_CANDS = [HERE / "macro"]
if len(HERE.parents) > 2:
    _CANDS.append(HERE.parents[2] / "skills/macro-ru-watcher/scripts")
for cand in _CANDS:
    if (cand / "build_macro.py").exists():
        sys.path.insert(0, str(cand))
        break

FOLDER = "macro-snapshots"


def run(root, save, today, make=None):
    """→ итог для журнала. make — build_macro.make (подменяется в тестах)."""
    if make is None:
        import build_macro
        make = build_macro.make
    md, rep = make(today, Path(root) / FOLDER, {}, infl_cbr=True)
    save(f"{FOLDER}/auto/ru-{today}.md", md)
    save(f"{FOLDER}/auto/ru-{today}.json", json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    rows = rep.get("rows") or []
    missing = [r["key"] for r in rows if r.get("value") is None]
    return {"status": "ok" if len(missing) <= 1 else "partial",   # недельной инфляции нет всегда
            "missing": missing, "anomalies": [r["key"] for r in rows if r.get("flag")],
            "values": {r["key"]: r.get("value") for r in rows}}
