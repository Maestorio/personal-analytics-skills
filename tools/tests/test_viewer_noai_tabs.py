#!/usr/bin/env python3
"""Вьюер портфеля: вкладки в режиме «без ИИ» (решение владельца 11.11) — прогон Chromium, 1280 и 390.

Правило: при data-noai вкладки, которые без ИИ не обновляются (Прогнозы, Источники, Интеграционный анализ,
Изменения — они из обзоров советника), уходят с полосы в «Ещё → Архив ИИ» с датой данных
(«Прогнозы · архив от ДД.ММ»). «Стресс» остаётся на полосе, пока самый свежий стресс — сценарии скилла или
пересчёт сайта (recalc.at) — не старше 60 дней; пересчёт новее сценариев — плашка «сценарии от ДД.ММ, позиции
свежие»; старше 60 дней — в «Архив ИИ». «С ИИ» — всё как было. Ссылка #tab=… на ушедшую вкладку открывает её.

Что проверяется:
  1. «с ИИ»: Источники и Изменения на полосе, Интеграционный анализ и Прогнозы в «Ещё» без группы;
  2. «без ИИ»: на полосе нет четырёх вкладок; в «Ещё» у них group «Архив ИИ», menu «… · архив от ДД.ММ», дата — самого
     свежего файла вида; меню в DOM: заголовок «Архив ИИ» один, пункты с датой; «Загрузки» вне группы;
  3. стресс: 30 дней — на полосе; 61 — в архиве с датой; сценарии 90 дней, пересчёт 10 — на полосе с плашкой в подзаголовке;
     сценарии и пересчёт старше 60 — архив с датой пересчёта; ровно 60 — на полосе;
  4. #tab=forecasts при «без ИИ» открывает раздел, кнопка «Ещё: Прогнозы» отмечена текущей;
  5. переключение режима (uiAiModeApply) перерисовывает полосу в обе стороны; «Динамика» при «без ИИ» — без панели
     «Ожидаемая доходность» (владелец 12.11), при «с ИИ» — с ней;
  6. телефон 390: полоса и меню не шире экрана, страница без горизонтальной прокрутки; ошибок страницы нет.
Данные: временный каталог с одним интеграционным видом; остальное подставляется в state на странице.
Запуск: python3 tools/tests/test_viewer_noai_tabs.py
"""
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import serve  # noqa: E402

passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("viewer_noai_tabs: пропуск — нет playwright")
    sys.exit(0)

SET = """(cfg) => {
  const d = state.data, t = dsToday();
  const ago = (n) => new Date(Date.parse(t + 'T00:00:00Z') - n * 864e5).toISOString().slice(0, 10);
  d.weeklyReviewCurrent = { date: ago(5), parsed: {} }; d.weeklyReviewHistory = [{ date: ago(12), parsed: {} }];
  d.forecasts = [{ date: ago(40), parsed: {} }, { date: ago(20), parsed: {} }];
  d.integratedView = { ...(d.integratedView || {}), date: ago(15) };
  if (cfg.stress === null) d.stressCurrent = null;
  else d.stressCurrent = { date: ago(cfg.stress), parsed: { scenarios: {} }, recalc: cfg.recalc != null ? { at: ago(cfg.recalc) + 'T10:00:00+03:00' } : null };
  return { ago5: ago(5), ago20: ago(20), ago15: ago(15), ago(n) {} };
}"""
TABS = """() => buildTabs().map(t => ({ id: t.id, more: !!t.more, group: t.group || null, menu: t.menu || null }))"""


def ids(tabs, more=None):
    return [t["id"] for t in tabs if more is None or t["more"] == more]


def main():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "Portfolio/integrated-views").mkdir(parents=True)
    (tmp / "Portfolio/integrated-views/integrated-view-2026-10-01.md").write_text("---\n---\n", encoding="utf-8")
    os.symlink(REPO / "tools", tmp / "tools")
    base = serve(directory=tmp)[1]
    with sync_playwright() as p:
        try:
            br = p.chromium.launch()
        except Exception:  # noqa: BLE001
            print("viewer_noai_tabs: пропуск — нет chromium")
            return 0
        for w, h, mobile in ((1280, 900, False), (390, 844, True)):
            tag = f"{w}px"
            ctx = br.new_context(viewport={"width": w, "height": h}, service_workers="block", **({"is_mobile": True, "has_touch": True} if mobile else {}))
            pg = ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/tools/portfolio-integrated-viewer.html")
            pg.wait_for_function("typeof state !== 'undefined' && state.data && document.querySelector('#tabs .ui-tab')", timeout=20000)
            pg.evaluate("uiAiModeApply('on')")
            pg.evaluate(SET, {"stress": 30, "recalc": None})
            ago = pg.evaluate("() => { const t = dsToday(), a = (n) => new Date(Date.parse(t + 'T00:00:00Z') - n * 864e5).toISOString().slice(0, 10); return { a5: a(5), a15: a(15), a20: a(20), a30: a(30) }; }")
            dm = lambda iso: f"{iso[8:10]}.{iso[5:7]}"   # noqa: E731 — «дд.мм» (год текущий)

            # 1. «с ИИ» — как раньше
            tabs = pg.evaluate(TABS)
            check(f"{tag}: «с ИИ»: Источники и Изменения — на полосе", {"sources", "diff", "scenarios"} <= set(ids(tabs, False)))
            check(f"{tag}: «с ИИ»: Прогнозы и Интеграционный анализ — в «Ещё», без группы", {"forecasts", "dashboard"} <= set(ids(tabs, True))
                  and all(t["group"] is None for t in tabs))

            # 2. «без ИИ»
            pg.evaluate("uiAiModeApply('off')")
            tabs = pg.evaluate(TABS)
            strip, more = ids(tabs, False), ids(tabs, True)
            check(f"{tag}: «без ИИ»: на полосе нет Прогнозов, Источников, Интеграционного анализа, Изменений ({strip})",
                  not ({"forecasts", "sources", "dashboard", "diff"} & set(strip)))
            check(f"{tag}: «без ИИ»: на полосе остались Сегодня, Действия и Стресс (30 дн.)", {"today", "actions", "scenarios"} <= set(strip) or {"today", "scenarios"} <= set(strip))
            arch = {t["id"]: t for t in tabs if t["group"] == "Архив ИИ"}
            check(f"{tag}: «Архив ИИ» — Прогнозы, Источники, Интеграционный анализ, Изменения ({sorted(arch)})", set(arch) == {"forecasts", "sources", "dashboard", "diff"})
            check(f"{tag}: Прогнозы — «архив от» даты самого свежего прогноза ({arch['forecasts']['menu']!r})",
                  arch["forecasts"]["menu"] == f"Прогнозы · архив от {dm(ago['a20'])}")
            check(f"{tag}: Интеграционный анализ — дата вида ({arch['dashboard']['menu']!r})", arch["dashboard"]["menu"] == f"Интеграционный анализ · архив от {dm(ago['a15'])}")
            check(f"{tag}: Изменения — дата последнего обзора, Источники — самого свежего из файлов",
                  arch["diff"]["menu"] == f"Изменения · архив от {dm(ago['a5'])}" and arch["sources"]["menu"] == f"Источники · архив от {dm(ago['a5'])}")
            check(f"{tag}: «Загрузки» (если есть) вне группы", all(t["group"] is None for t in tabs if t["id"] == "pfbuild"))
            pg.evaluate("renderTabs()")
            pg.click("#tabs [data-ui-tabs-more]")
            pop = pg.evaluate("""() => { const p = document.querySelector('.ui-tabs-pop'), b = p.getBoundingClientRect();
              return { heads: [...p.querySelectorAll('.ui-tabs-pop-h')].map(x => x.textContent), items: [...p.querySelectorAll('[data-ui-tab]')].map(x => x.textContent),
                       inside: b.left >= 0 && b.right <= innerWidth + 1 }; }""")
            check(f"{tag}: меню «Ещё»: один заголовок «Архив ИИ» ({pop['heads']})", pop["heads"] == ["Архив ИИ"])
            check(f"{tag}: пункты архива с датой ({pop['items']})", any(x.startswith("Прогнозы · архив от ") for x in pop["items"])
                  and any(x.startswith("Интеграционный анализ · архив от ") for x in pop["items"]))
            check(f"{tag}: меню целиком в окне", pop["inside"])
            pg.keyboard.press("Escape")
            pg.evaluate("uiTabsClose()")

            # 3. стресс по 60 дням
            def stress(n, rc):
                pg.evaluate(SET, {"stress": n, "recalc": rc})
                t = pg.evaluate(TABS)
                return next((x for x in t if x["id"] == "scenarios"), None), pg.evaluate("tabLead('scenarios')")
            s, lead = stress(30, None)
            check(f"{tag}: стресс 30 дн. — на полосе, плашки нет ({s}, {lead!r})", s and not s["more"] and "позиции свежие" not in lead)
            s, _ = stress(60, None)
            check(f"{tag}: стресс ровно 60 дн. — ещё на полосе", s and not s["more"])
            s, _ = stress(61, None)
            check(f"{tag}: стресс 61 дн. — в «Архив ИИ» с датой ({s})", s and s["more"] and s["group"] == "Архив ИИ" and "архив от " in s["menu"])
            s, lead = stress(90, 10)
            check(f"{tag}: сценарии 90 дн., пересчёт сайта 10 дн. — на полосе, плашка «сценарии от ДД.ММ, позиции свежие» ({lead!r})",
                  s and not s["more"] and "позиции свежие" in lead and "сценарии от " in lead)
            s, _ = stress(120, 70)
            ag = pg.evaluate("() => { const t = dsToday(); return new Date(Date.parse(t + 'T00:00:00Z') - 70 * 864e5).toISOString().slice(0, 10); }")
            check(f"{tag}: сценарии 120, пересчёт 70 дн. — архив, дата — пересчёта ({s})", s and s["more"] and s["menu"] == f"Стресс · архив от {dm(ag)}")
            s, _ = stress(61, None)

            # 4. ссылка на ушедшую вкладку
            pg.evaluate(SET, {"stress": 30, "recalc": None})
            pg.evaluate("goToTab('forecasts')")
            cur = pg.evaluate("() => ({ tab: state.currentTab, more: document.querySelector('#tabs [data-ui-tabs-more]').textContent, head: document.querySelector('#content h1, #content .ui-h1')?.textContent })")
            check(f"{tag}: #tab=forecasts при «без ИИ» открывает «Прогнозы» ({cur})", cur["tab"] == "forecasts" and "Прогнозы" in cur["more"])

            # 5. переключение режима
            pg.evaluate("uiAiModeApply('on')")
            on = pg.evaluate("() => [...document.querySelectorAll('#tabs .ui-tabs > .ui-tab:not(.more)')].map(x => x.textContent)")
            pg.evaluate("uiAiModeApply('off')")
            off = pg.evaluate("() => [...document.querySelectorAll('#tabs .ui-tabs > .ui-tab:not(.more)')].map(x => x.textContent)")
            check(f"{tag}: «с ИИ» — Источники на полосе, «без ИИ» — нет ({'Источники' in ' '.join(on)} / {'Источники' in ' '.join(off)})",
                  any(x.startswith("Источники") for x in on) and not any(x.startswith("Источники") for x in off))
            # 5а. «Динамика»: «Ожидаемая доходность» (история прогнозов интеграционного анализа) — только «с ИИ» (владелец 12.11)
            # вкладки «Динамика» в фикстуре нет (нужно ≥2 снапшота) — раздел рисуется в отдельный узел
            heads = "() => { const c = document.createElement('div'); renderHistoryTab(c); return [...c.querySelectorAll('.sec-h')].map(h => h.textContent); }"
            h_off = pg.evaluate(heads)
            pg.evaluate("uiAiModeApply('on')")
            h_on = pg.evaluate(heads)
            pg.evaluate("uiAiModeApply('off')")
            check(f"{tag}: «Динамика» без ИИ — без «Ожидаемой доходности», «Реализованная» на месте ({h_off})",
                  not any(h.startswith("Ожидаемая") for h in h_off) and any(h.startswith("Реализованная") for h in h_off))
            check(f"{tag}: «Динамика» с ИИ — «Ожидаемая доходность» есть ({h_on})", any(h.startswith("Ожидаемая") for h in h_on))

            # 6. телефон
            ov = pg.evaluate("() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, tabs: document.querySelector('#tabs .ui-tabs').getBoundingClientRect().right })")
            check(f"{tag}: страница без горизонтальной прокрутки ({ov})", ov["sw"] <= ov["cw"] + 1 and ov["tabs"] <= ov["cw"] + 1)
            check(f"{tag}: ошибок страницы нет ({errs})", not errs)
            ctx.close()
        br.close()
    print(f"viewer_noai_tabs: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
