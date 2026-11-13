"""Фикстуры формата 2 для браузерных тестов вьюера (шаг 12 цикла машиночитаемости, schema.md §3).

Не тест: импортируется тестами tools/tests/test_viewer_*.py. Даёт записи решений decision@1, определения conditions@2,
события conditions-state@1, справочник бумаг security-attrs@1 и JS-функцию DS_SET, которая кладёт их в state.data
вьюера (как после загрузки файлов) и сбрасывает кэш модулей (dsInvalidate).
"""
import json
from datetime import date, timedelta

DS_SET = """(o) => {
  if ('decisions' in o) state.data.decisions = (o.decisions || []).slice().sort((a, b) => a.recorded_at.localeCompare(b.recorded_at));
  if ('defs' in o) state.data.conditions = o.defs ? { name: 'conditions.yaml', parsed: { schema_version: 'conditions@2', conditions: o.defs } } : null;
  if ('events' in o) state.data.conditionsState = { name: 'conditions-state.json', parsed: { schema_version: 'conditions-state@1', events: o.events || [] } };
  if ('attrs' in o) state.data.securityAttrs = o.attrs ? { name: 'security-attrs.json', parsed: { schema_version: 'security-attrs@1', by_key: o.attrs } } : null;
  dsInvalidate();
}"""


def day(offset=0):
    """Дата относительно сегодняшней (вьюер считает гейт и условия на сегодня, dsToday)."""
    return (date.today() + timedelta(days=offset)).isoformat()


def at(d, hm="10:00"):
    return f"{d}T{hm}:00+03:00"


def dec(key, verdict, recorded, *, target_pct=None, review_by=None, note="фикстура", doc=None, mode_codes=None,
        kind="report", cc=None, cr=None, confidence=None, author="model"):
    """Решение decision@1; recorded — время «ГГГГ-ММ-ДДTЧЧ:ММ:СС+03:00» или дата (тогда 10:00)."""
    rec = recorded if "T" in recorded else at(recorded)
    hhmm = rec[11:13] + rec[14:16]
    return {"schema_version": "decision@1", "id": f"{rec[:10]}T{hhmm}-{key}", "key": key, "verdict": verdict,
            "target_pct": target_pct, "review_by": review_by, "note": note, "confidence": confidence,
            "conditions_created": cc or [], "conditions_resolved": cr or [],
            "source": {"kind": kind, "doc": doc if doc or kind != "report" else f"Portfolio/reports/{rec[:10]}-fixture-{key.lower()}.md", "mode_codes": mode_codes if mode_codes is not None else (["4a"] if kind == "report" else []),
                       "stress_id": None},
            "author": author, "recorded_at": rec}


def cond(cid, key, ttype, value, *, version=1, kind="review", verdict_now="HOLD", on_verdict=None, action="run_analysis",
         text="разобрать", target_pct=None, valid_until=None, window_end=None, not_before=None, created="2026-10-01T10:00:00+03:00",
         created_by="mode_4", doc=None, branches=None, otherwise=None, on_expiry=None, note=None, withdrawn=None,
         event_text=None, plan_pct=None):
    """Определение conditions@2 (одна версия)."""
    trig = {"type": ttype, "value": value}
    if window_end:
        trig["window_end"] = window_end
    ot = {"action": action, "verdict": on_verdict, "text": text}
    if target_pct is not None:
        ot["target_pct"] = target_pct
    if branches:
        ot["branches"] = branches
    if otherwise:
        ot["otherwise"] = otherwise
    d = {"id": cid, "version": version, "key": key, "kind": kind, "trigger": trig,
         "while_pending": {"verdict": verdict_now, "text": "ждём"}, "on_trigger": ot, "on_expiry": on_expiry,
         "not_before": not_before, "valid_until": valid_until,
         "source": {"kind": "report", "doc": doc}, "created_at": created, "created_by": created_by,
         "withdrawn": withdrawn, "superseded_by": None}
    if event_text:
        d["event_text"] = event_text
    if note:
        d["note"] = note
    if plan_pct is not None:
        d["context"] = {"plan_pct": plan_pct, "snapshot_id": None, "as_of": created[:10]}
    return d


def ev(cid, event, when, by="notifier", data=None, version=None):
    e = {"condition_id": cid, "event": event, "at": when if "T" in when else at(when), "by": by, "data": data or {}}
    if version is not None:
        e["version"] = version
    return e


def attr(ticker_class=None, listed_at=None, note=None):
    return {"ticker_class": ticker_class, "listed_at": listed_at, "note": note,
            "updated_at": "2026-10-31T00:00:00+03:00", "updated_by": "script"}


def write_decisions(root, decisions):
    """Файлы Portfolio/decisions/<id>.json во временном корне фикстуры."""
    ddir = root / "Portfolio" / "decisions"
    ddir.mkdir(parents=True, exist_ok=True)
    for d in decisions:
        (ddir / f"{d['id']}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def write_conditions(root, defs, events=None):
    import yaml
    pf = root / "Portfolio"
    pf.mkdir(parents=True, exist_ok=True)
    (pf / "conditions.yaml").write_text(yaml.safe_dump({"schema_version": "conditions@2", "conditions": defs},
                                                       allow_unicode=True, sort_keys=False), encoding="utf-8")
    (pf / "conditions-state.json").write_text(json.dumps({"schema_version": "conditions-state@1", "events": events or []},
                                                         ensure_ascii=False, indent=1), encoding="utf-8")


def write_attrs(root, by_key):
    pf = root / "Portfolio"
    pf.mkdir(parents=True, exist_ok=True)
    (pf / "security-attrs.json").write_text(json.dumps({"schema_version": "security-attrs@1", "by_key": by_key},
                                                       ensure_ascii=False, indent=1), encoding="utf-8")
