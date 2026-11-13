#!/usr/bin/env python3
"""Обновление журнала решений AIR-1 одной командой (этап 5).

shadow_inputs → shadow_baselines → decision_journal → отчёт. Детерминированно, без LLM:
пишет в `<memory>/Portfolio/decision-journal/` сам — исключение D3 (решение владельца D-1,
то же основание, что снапшоты data-loader). План: docs/investment/portfolio/air-1-decision-journal-plan.md.
Писатель — только сборка сайта (pf_build.publish_journal даёт рабочий корень --memory со ссылками на том /srv):
читает Portfolio/{weekly-reviews, snapshots, decisions/, conditions.yaml, conditions-state.json, plan-journal.jsonl,
security-types.json} и ручные decision-journal/{refusals,theses,incidents}.yaml (валидатор — до сборки).
Mac-путь по умолчанию у --memory оставлен для ручного прогона, сайту он не нужен.

Файлы:
  inputs.json, baselines.json, journal.json — полная пересборка, перезапись;
  report-{as_of}.md — короткий отчёт (что сказать — §9 плана).
В stdout — сводка 3–5 строк + вопросы об отказах + напоминания (§7а), её и показывает модель.

Запуск: python3 decision_journal_update.py [--trades X.xlsx] [--as-of YYYY-MM-DD] [--offline] [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

MEMORY_ROOT = Path.home() / "Library/CloudStorage/SynologyDrive-home/Claude-Memory"
CHECKPOINTS = [
    (dt.date(2027, 1, 6), "первая контрольная точка", "обнови журнал решений и разбери контрольную точку"),
    (dt.date(2027, 5, 6), "проверка правила отключения", "проверь правило отключения по журналу решений"),
]
CHECKPOINT_WARN_DAYS = 7
CONC_RU = {"followed": "исполнено", "contrary": "наоборот", "ignored": "проигнорировано",
           "deferred_by_condition": "отложено условием", "owner_decided": "решил сам"}
BASE_NAMES = {"B0": "B0 ничего не делать", "B1": "B1 индексы (облигации рублёвые)",
              "B2-live": "B2 план механически (текущий)", "B2-frozen": "B2 план на 05.05"}


def next_checkpoints(as_of: dt.date) -> list[tuple[dt.date, str, str]]:
    """Фиксированные даты + раз в полгода с 2027-11-06."""
    out = list(CHECKPOINTS)
    d = dt.date(2027, 11, 6)
    while d <= as_of + dt.timedelta(days=400):
        out.append((d, "полугодовой разбор", "разбери журнал решений за полгода"))
        d = dt.date(d.year + (d.month + 6 > 12), (d.month + 6 - 1) % 12 + 1, 6)
    return [c for c in out if c[0] >= as_of]


def binom_tail(k: int, n: int) -> float | None:
    """P(X ≥ k | n, 0,5) — односторонняя проверка «лучше монетки»."""
    if n <= 0:
        return None
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _pp(x) -> str:
    return "—" if x is None else f"{x:+.1f}".replace(".", ",")


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:+.2f}%".replace(".", ",")


def _rub(x) -> str:
    return "—" if x is None else f"{x:+,.0f} ₽".replace(",", " ")


def owner_vs_system(eps: list[dict]) -> dict:
    """Созревшие направленные эпизоды акций: исполненные против проигнорированных."""
    out = {}
    for conc in ("followed", "ignored"):
        e = [x for x in eps if x["class"] == "stock" and x["concordance"] == conc
             and x.get("kind", "review") == "review" and x["outcome"].get("hit_3m") is not None]
        out[conc] = {"n": len(e), "system_right": sum(1 for x in e if x["outcome"]["hit_3m"])}
    return out


def costly_episodes(eps: list[dict], top: int = 5) -> list[dict]:
    """Исполненные и неверные + проигнорированные и верные — по модулю отклонения на 3 мес."""
    rows = []
    for x in eps:
        if x.get("kind", "review") != "review":          # эпизоды решений — своя сводка (decisions_summary)
            continue
        h, rel = x["outcome"].get("hit_3m"), x["outcome"].get("rel_3m")
        if h is None or rel is None:
            continue
        if x["concordance"] == "followed" and not h:
            rows.append(x | {"why": "исполнено — система ошиблась"})
        elif x["concordance"] == "ignored" and h:
            rows.append(x | {"why": "не исполнено — система была права"})
    return sorted(rows, key=lambda x: -abs(x["outcome"]["rel_3m"]))[:top]


def render_report(base: dict, jr: dict, as_of: dt.date) -> str:
    w = base.get("window") or {}
    L = [f"# Журнал решений — отчёт на {as_of.isoformat()}", "",
         "Сгенерировано `decision_journal_update.py` без LLM. План и правила: "
         "`docs/investment/portfolio/air-1-decision-journal-plan.md`.", ""]
    L += ["## 1. Факт против теневых баз", "",
          f"Окно {w.get('t0')} → {w.get('end')} ({w.get('days')} дн.). Все базы получают те же пополнения в те же дни.", "",
          "| База | За окно | Годовых | Факт − база, п.п. год. | Факт − база, ₽ |", "|---|---|---|---|---|",
          f"| **B3 факт** | {_pct(base['b3']['twr'])} | {_pct(base['b3']['twr_ann'])} | — | — |"]
    for k, b in base["bases"].items():
        L.append(f"| {BASE_NAMES.get(k, k)} | {_pct(b['twr'])} | {_pct(b['twr_ann'])} | "
                 f"{_pp(b['b3_minus_base_pp_ann'])} | {_rub(b['b3_minus_base_rub'])} |")
    L += ["", f"**Окно {w.get('days')} дней — это шум**: для различимого эффекта нужны годы (план §4). "
          "Таблица ловит только грубый вред. B2-live − B2-frozen ≈ вклад смен плана; факт − B2-live ≈ вклад "
          "исполнения (тайминг, отбор бумаг, вето гейтов).", ""]

    L += ["## 2. Направленные вердикты advisor (эпизоды)", "",
          "Эпизод = подряд идущие обзоры с тем же тикером и направлением; исход — доходность бумаги "
          "(с дивидендами) минус MCFTR за 3 мес. от первого обзора; облигации — полная доходность "
          "(цена + НКД + купоны/амортизации) минус индекс корзины (ОФЗ — RGBITR, корп. — RUCBTRNS, "
          "флоатеры — RUSFAR, CNY — RUCNYTR; USD/EUR — индекса нет, без исхода).", "",
          "| Класс | Вердиктов | Доля HOLD | Эпизодов | Созрело 3 мес. | Верных | p (лучше монетки) | Без правок задним числом |",
          "|---|---|---|---|---|---|---|---|"]
    for cls, s in jr["summary"].items():
        p = binom_tail(s["hits_3m"], s["matured_3m"])
        L.append(f"| {'акции' if cls == 'stock' else 'облигации'} | {s['verdicts']} | "
                 f"{'—' if s['hold_share'] is None else f'{s['hold_share']:.0%}'} | {s['episodes']} | "
                 f"{s['matured_3m']} | {s['hits_3m']} | {'—' if p is None else f'{p:.2f}'.replace('.', ',')} | "
                 f"{s['hits_3m_clean']} из {s['matured_3m_clean']} |")
    ovs = owner_vs_system(jr["episodes"])
    f_, i_ = ovs["followed"], ovs["ignored"]
    L += ["", "**Кто был прав (акции, созревшие эпизоды):** "
          f"исполненные — система права в {f_['system_right']} из {f_['n']}; "
          f"проигнорированные — система была права в {i_['system_right']} из {i_['n']} "
          "(там ваш отказ стоил денег).", ""]
    ce = costly_episodes(jr["episodes"])
    if ce:
        L += ["**Самые дорогие эпизоды:**", "", "| Дата | Бумага | Вердикт | Отклонение к индексу, п.п. | Что случилось |",
              "|---|---|---|---|---|"]
        for x in ce:
            L.append(f"| {x['first_date']} | {x['position_name']} | {x['verdict']} | {_pp(x['outcome']['rel_3m'])} | {x['why']} |")
        L.append("")

    L += ["## 3. Вопросы об отказах (один раз на эпизод)", ""]
    if jr["pending_questions"]:
        L += [f"- {q['question']}" for q in jr["pending_questions"]]
    else:
        L.append("Нет.")
    L += ["", "## 4. Открытые ставки владельца", ""]
    th = jr.get("theses") or []
    L += ([f"- `{t['id']}`: {t.get('event')} — p = {t.get('p')}, проверка {t.get('check_date')}" for t in th]
          or ["Нет."])
    L += ["", "## 5. Инциденты по месяцам (автоисточники D-5)", "",
          "| Месяц | Обзоры с проблемой данных | Коммиты fix: advisor/data-loader | Ретро-документы | Записи владельца |",
          "|---|---|---|---|---|"]
    for m, v in jr["incidents_monthly"].items():
        L.append(f"| {m} | {v['data_flags']} | {v['fix_commits']} | {v['retro_docs']} | {v.get('manual', 0)} |")
    ds_ = jr.get("decisions_summary") or {}
    conc = ", ".join(f"{CONC_RU.get(k, k)} {n}" for k, n in sorted((ds_.get("concordance") or {}).items()))
    L += ["", f"Смен плана: {len(jr['plan_changes'])}; решений по бумаге: {ds_.get('decisions', 0)} "
          f"(направленных {ds_.get('directed', 0)}; эпизоды решений: {conc or 'нет'}).", ""]
    flags = (base.get("flags") or []) + (jr.get("flags") or [])
    L += ["## 6. Флаги", ""] + ([f"- {f}" for f in flags] or ["Нет."]) + [""]
    return "\n".join(L)


def open_theses(doc: dict | None) -> list[dict]:
    """Ставки владельца (theses.yaml, append-only): последнее состояние по id; только open."""
    last: dict[str, dict] = {}
    for t in (doc or {}).get("theses") or []:
        if t.get("id"):
            # YAML отдаёт даты объектами date — в journal.json они не сериализуются (сбой 2026-10-08)
            t = {k: (v.isoformat() if isinstance(v, dt.date) else v) for k, v in t.items()}
            last[t["id"]] = {**last.get(t["id"], {}), **t}
    return [t for t in last.values() if t.get("status") == "open"]


def _date(x) -> dt.date | None:
    if isinstance(x, dt.date):
        return x
    try:
        return dt.date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def console_summary(base: dict, jr: dict, as_of: dt.date) -> list[str]:
    s = jr["summary"]["stock"]
    b2 = base["bases"].get("B2-live", {})
    L = [f"Журнал решений обновлён на {as_of}: окно факта {base['window']['days']} дн.; "
         f"факт − план механически {_pp(b2.get('b3_minus_base_pp_ann'))} п.п. годовых ({_rub(b2.get('b3_minus_base_rub'))}) — пока шум.",
         f"Вердикты по акциям: созрело {s['matured_3m']} эпизодов, верных {s['hits_3m']}."]
    if jr["pending_questions"]:
        L.append(f"Вопросы об отказах ({len(jr['pending_questions'])}) — задать владельцу один раз:")
        L += [f"  • {q['question']}" for q in jr["pending_questions"]]
    for d, what, say in next_checkpoints(as_of):
        if (d - as_of).days <= CHECKPOINT_WARN_DAYS:
            L.append(f"Через {(d - as_of).days} дн. ({d}) — {what}. Запустить? Сказать: «{say}».")
    for t in jr.get("theses") or []:
        d = _date(t.get("check_date"))
        if d and (d - as_of).days <= CHECKPOINT_WARN_DAYS:
            when = "сегодня или раньше" if d <= as_of else f"через {(d - as_of).days} дн."
            L.append(f"Ставка «{t.get('event')}» (p={t.get('p')}): дата проверки {d} — {when}; "
                     f"закрыть и записать исход? Сказать: «закрой ставку {t['id']}».")
    for f in (base.get("flags") or []) + (jr.get("flags") or []):
        if "выгрузка сделок" in f or "сверка" in f:
            L.append("⚠ " + f)
    return L


def main(argv: list[str] | None = None) -> int:
    import market_series as ms
    import decision_journal as dj
    import shadow_baselines as sb
    import shadow_inputs as si
    from portfolio_returns import apply_corrections, convert_trades_to_rub, parse_trades

    ap = argparse.ArgumentParser(description="Обновить журнал решений AIR-1.")
    ap.add_argument("--trades", type=Path)
    ap.add_argument("--memory", type=Path, default=MEMORY_ROOT)
    ap.add_argument("--as-of", type=dt.date.fromisoformat, default=dt.date.today())
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="ничего не писать, только сводка")
    a = ap.parse_args(argv)

    port = a.memory / "Portfolio"
    out_dir = port / "decision-journal"
    # ручные входы — до любой работы (сеть, сделки): ошибка записи Workflow P — понятный отказ, журнал не тронут
    refusals, theses_doc, incidents, errs = dj.load_manual(out_dir)
    if errs:
        print("Ручные входы журнала не прошли валидатор — исправь записью save-to-library Workflow P "
              "(новая запись с corrects), журнал не изменён:\n  " + "\n  ".join(errs), file=sys.stderr)
        return 2
    tpath = a.trades or si.newest_trades_export()
    if not tpath:
        print("Нет выгрузки trades_portfolio_*.xlsx — приложи свежую из IntelInvest.", file=sys.stderr)
        return 2
    # журнал строится по ВСЕМ недельным обзорам; нет ни одного — это неполная копия Claude-Memory
    # (2026-10-22, скилл в окружении Claude: скопировал только decision-journal/ и снапшоты →
    # ValueError «min() iterable argument is empty» после минуты сетевых запросов)
    reviews = dj.load_reviews(port / "weekly-reviews")
    if not reviews:
        print(f"Нет недельных обзоров в {port / 'weekly-reviews'}: журнал решений строится по всем "
              "weekly-review-*.yaml. Если Claude-Memory скопирован частично — добавь эту папку целиком "
              "или пропусти шаг. Журнал не изменён.", file=sys.stderr)
        return 2
    trades = convert_trades_to_rub(apply_corrections(parse_trades(str(tpath)))[0], cbr_offline=a.offline)
    snaps_l = si.load_snapshots(port / "snapshots")
    inputs = si.build_inputs(trades, snaps_l, dt.date(2026, 5, 1), a.as_of)
    inputs["trades_file"] = tpath.name

    snaps = {d.isoformat(): s for d, s in snaps_l}
    t0 = dt.date.fromisoformat(inputs["b3"][0]["date"])
    end = dt.date.fromisoformat(inputs["b3"][-1]["date"])
    got = ms.get_many(sb.required_series(inputs, snaps[t0.isoformat()]), t0 - dt.timedelta(days=14), end,
                      offline=a.offline)
    market = sb.Market({k: s.points for k, s in got.items()}, t0, sb.fx_yields_from_snapshot(snaps[t0.isoformat()]))
    base = sb.run(inputs, snaps, market, si.fund_sectors(snaps_l))
    base["flags"] = [f"ряд пуст: {k}" for k, s in got.items() if not s.points] + base.get("flags", [])

    owner, oflags = dj.load_owner(a.memory)
    since = dt.date.fromisoformat(min(r["date"] for r in reviews)) - dt.timedelta(days=10)
    got2 = ms.get_many(dj.series_specs(reviews, owner), since, a.as_of, offline=a.offline)
    jr = dj.build(reviews, trades, inputs, {k: s.points for k, s in got2.items()}, owner, refusals, a.as_of, incidents)
    jr["flags"] = oflags + jr["flags"]
    jr["theses"] = open_theses(theses_doc)

    # сначала сериализовать всё (сбой не должен оставить набор файлов из разных прогонов — 2026-10-08),
    # и даже --dry-run проверяет, что журнал сериализуется
    texts = {
        "inputs.json": json.dumps(inputs, ensure_ascii=False, indent=1),
        "baselines.json": json.dumps(base, ensure_ascii=False, indent=1),
        "journal.json": json.dumps(jr, ensure_ascii=False, indent=1),
        f"report-{a.as_of.isoformat()}.md": render_report(base, jr, a.as_of),
    }
    if not a.dry_run:
        for name, text in texts.items():
            atomic_write(out_dir / name, text)
    print("\n".join(console_summary(base, jr, a.as_of)))
    if not a.dry_run:
        print(f"Файлы: {out_dir}/ (report-{a.as_of.isoformat()}.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
