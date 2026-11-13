#!/usr/bin/env python3
"""Вьюер, вкладка «Макро»: основной ряд — автосрез сайта, недельная инфляция — отдельная карточка (решение владельца 11.11).

Контракт:
  1. Плитки и мини-графики читают автосрезы macro-snapshots/auto/ru-ДАТА.json (а не ru-*.md скилла): ставка, USD/RUB, CNY/RUB,
     Brent (подпись «фьючерс BR, MOEX, на дату»), RGBI, IMOEX. Инфляция г/г (владелец 12.11, вариант А) — оценка по неделям: срезы скилла ru-*.md + inflation/*.jsonl
     (yoy_pct на yoy_as_of), месячная ЦБ автосреза — в подписи «месячная ЦБ 6,35 за ММ.ГГГГ».
     .md из auto/ срезом скилла не считается. До первого автосреза ряды продолжены срезами скилла ru-*.md (владелец 12.11),
     кроме инфляции г/г (у скилла недельная оценка — другая величина); подпись о склейке и о Brent ICE.
  2. Недельная инфляция: два файла (model.jsonl — скилл, owner.jsonl — форма сайта); карточка берёт САМОЕ СВЕЖЕЕ по date
     (файл не важен), подписывает источник и «внесено вами / скиллом»; строки с битым JSON и без даты пропускаются.
  3. Срок годности — только у недельной инфляции: 9 дн. — граница (без плашки), > 9 — жёлтая, > 16 — красная
     (STALE_THRESHOLDS_DAYS.macro / STALE_FAIL_DAYS.macro); «с ИИ» — строка «Обновить инфляцию» на «Действиях» с командой
     /macro-ru-watcher Обнови инфляцию, «без ИИ» — строки нет (внесение — формой).
  4. Форма «Внести инфляцию» — только при data-noai; при «с ИИ» её нет. Отправка — POST api/pv/macro/inflation с телом
     {record: {date, week_pct (число), week_period, yoy_pct (число), yoy_as_of, source_name, source_url}}; пустое поле —
     «Проверь …» без запроса; 400 — тексты проблем сервера; 403 — «Нет доступа»; успех — запись сразу в карточке «внесено вами».
  5. 1280 и 390 px: страница не шире экрана, форма не вылезает; ошибок JS нет.
Данные синтетические, сервер — http.server во временной папке, POST перехватывает playwright. Требует playwright + chromium.
Запуск: python3 tools/tests/test_viewer_macro_auto.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import serve  # noqa: E402  (стенд — _pages_stand, keep-alive)
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
    print("viewer_macro_auto: пропуск — нет playwright")
    sys.exit(0)


def skill_md(date, usd, infl):
    return (f"---\nas_of_date: {date}\n---\n# Макро {date}\n\n| Индикатор | Текущее | Источник |\n|---|---|---|\n"
            f"| Ключевая ставка ЦБ | 14.0% | ЦБ |\n| Инфляция (г/г) | {infl}% | Росстат |\n"
            f"| USD/RUB | {usd} | MOEX |\n")


def auto(date, usd, flag="", brent=96.5):
    rows = [("cbr_key", "Ключевая ставка ЦБ", 14.0, date, ""), ("infl_yoy", "Инфляция (г/г)", 6.35, "за 09.2026", "⚠️"),
            ("infl_week", "Инфляция (нед)", None, None, ""), ("usd_rub", "USD/RUB", usd, date, flag),
            ("cny_rub", "CNY/RUB", 11.4, date, ""), ("brent", "Brent", brent, date, ""),
            ("rgbi", "RGBI", 118.2, date, ""), ("imoex", "IMOEX", 2650.0, date, "")]
    return {"kind": "macro-ru@1", "date": date, "infl_kind": "cbr_monthly",
            "rows": [{"key": k, "label": lb, "value": v, "as_of": a, "flag": f} for k, lb, v, a, f in rows]}


def jl(date, who, week, rec_at):
    return json.dumps({"date": date, "week_pct": week, "week_period": "27.10–02.11", "yoy_pct": 6.4, "yoy_as_of": date,
                       "source_url": "https://rosstat.gov.ru/x" if who == "model" else None,
                       "source_name": "Росстат" if who == "model" else "МЭР", "recorded_at": rec_at, "author": who},
                      ensure_ascii=False)


def run_viewer(p, base, w, h, off):
    br = p.chromium.launch()
    ctx = br.new_context(viewport={"width": w, "height": h})
    if off:
        ctx.add_init_script("try { localStorage.setItem('hub-noai', 'off'); } catch (e) {}")
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    posts = []
    reply = {"status": 200, "body": None}

    def on_post(route):
        body = json.loads(route.request.post_data or "{}")
        posts.append(body)
        if reply["status"] == 200:
            rec = {**body["record"], "recorded_at": "2026-11-12T10:00:00+03:00", "author": "owner"}
            payload = {"record": rec, "hash": "h", "records": 1}
        else:
            payload = reply["body"] or {}
        route.fulfill(status=reply["status"], content_type="application/json", body=json.dumps(payload, ensure_ascii=False))
    page.route("**/api/pv/macro/inflation", on_post)
    page.goto(base + "/tools/portfolio-integrated-viewer.html")
    page.wait_for_function("typeof state !== 'undefined' && state.data && (state.data.macroAuto || []).length === 2 "
                           "&& (state.data.macroInfl || []).length === 2", timeout=20000)
    return br, page, errs, posts, reply


def main():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "Portfolio/integrated-views").mkdir(parents=True)
    (tmp / "Portfolio/integrated-views/integrated-view-2026-10-01.md").write_text("---\n---\n", encoding="utf-8")
    ms = tmp / "macro-snapshots"
    (ms / "auto").mkdir(parents=True)
    (ms / "inflation").mkdir()
    (ms / "ru-2026-10-08.md").write_text(skill_md("2026-10-08", 86.01, 7.08), encoding="utf-8")
    (ms / "ru-2026-10-16.md").write_text(skill_md("2026-10-16", 84.0, 7.22), encoding="utf-8")
    (ms / "auto/ru-2026-11-10.json").write_text(json.dumps(auto("2026-11-10", 81.9, "⚠️", 96.5)), encoding="utf-8")
    (ms / "auto/ru-2026-11-09.json").write_text(json.dumps(auto("2026-11-09", 82.5, "", 95.0)), encoding="utf-8")
    (ms / "auto/ru-2026-11-10.md").write_text(skill_md("2026-11-10", 1.0, 1.0), encoding="utf-8")   # не срез скилла
    # модель — 04.11, владелец — 11.11 (свежее): карточка показывает владельца; битая строка и строка без даты пропускаются
    (ms / "inflation/model.jsonl").write_text(jl("2026-11-04", "model", 0.11, "2026-11-04T12:00:00+03:00") + "\nне json\n"
                                              + json.dumps({"week_pct": 0.5}) + "\n", encoding="utf-8")
    (ms / "inflation/owner.jsonl").write_text(jl("2026-11-11", "owner", 0.25, "2026-11-11T12:00:00+03:00") + "\n", encoding="utf-8")
    os.symlink(REPO / "tools", tmp / "tools")
    httpd = serve(directory=tmp)[0]   # _pages_stand: очередь 128, keep-alive
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    with sync_playwright() as p:
        try:
            p.chromium.launch().close()
        except Exception:  # noqa: BLE001
            print("viewer_macro_auto: пропуск — нет chromium")
            return 0
        for (w, h) in ((390, 844), (1280, 900)):
            tag = f"{w}px"
            # ───── «с ИИ» ─────
            br, page, errs, posts, reply = run_viewer(p, base, w, h, off=False)
            check(f"{tag}: автосрез и .md из auto/ не попали в срезы скилла", page.evaluate("state.data.macroSnapshots.length") == 2)
            page.evaluate("goToTab('macro')")
            page.wait_for_selector("#macro-tiles", timeout=5000)
            tiles = page.text_content("#macro-tiles")
            kicks = [k.text_content() for k in page.query_selector_all("#macro-tiles .ui-kicker")]
            check(f"{tag}: семь плиток автосреза ({len(kicks)})", len(kicks) == 7)
            check(f"{tag}: Brent — «фьючерс BR, MOEX, на 10.11»", "фьючерс BR, MOEX, на 10.11" in tiles and any("Brent" in k for k in kicks))
            cpi_t = tiles.split("Инфляция г/г, %")[1][:120] if "Инфляция г/г, %" in tiles else ""
            check(f"{tag}: инфляция г/г — оценка по неделям 6,4 на 11.11, месячная ЦБ в подписи ({cpi_t!r})",
                  cpi_t.startswith("6,4") and "оценка по неделям на 11.11" in cpi_t and "месячная ЦБ 6,35 за 09.2026" in cpi_t)
            check(f"{tag}: USD/RUB — последнее значение автосреза 81,9, не скилла", "81,9" in tiles and "84" not in tiles.split("USD/RUB")[1][:30])
            check(f"{tag}: мини-графики у плиток с двумя автосрезами", len(page.query_selector_all("#macro-tiles svg")) >= 7)
            check(f"{tag}: подпись числа срезов — автосрезы, не снапшоты скилла", "2 автосреза: 2026-11-09 … 2026-11-10" in tiles)
            # склейка (владелец 12.11): до первого автосреза — срезы скилла; инфляция г/г — только автосрезы (другая величина)
            usd_t = tiles.split("USD/RUB")[1][:60]
            check(f"{tag}: USD/RUB — изменение с первого среза скилла 08.10 (−4,11) ({usd_t!r})", "−4,11 с 2026-10-08" in usd_t)
            check(f"{tag}: ставка — тоже со среза скилла 08.10", "с 2026-10-08" in tiles.split("Ключевая ставка")[1][:40])
            check(f"{tag}: инфляция г/г — ряд с первого среза скилла 08.10 (7,08 → 6,4: −0,68)", "−0,68 с 2026-10-08" in cpi_t)
            check(f"{tag}: подпись о склейке и о Brent ICE", "продолжены срезами скилла (с 2026-10-08)" in tiles and "фьючерс ICE" in tiles)
            check(f"{tag}: старого сравнения со скиллом нет", "против среза скилла" not in page.inner_text("body") and "пробный месяц" not in page.inner_text("body"))
            infl = page.inner_text("#macro-infl")
            check(f"{tag}: недельная инфляция — свежее из двух файлов (владелец 11.11, 0,25), источник и «внесено вами»",
                  "0,25" in infl and "МЭР" in infl and "внесено вами 11.11" in infl and "0,11" not in infl)
            check(f"{tag}: период недели и «опубликовано»", "за 27.10–02.11" in infl and "опубликовано 11.11" in infl)
            check(f"{tag}: «с ИИ» — формы нет", page.query_selector("#macro-infl-form") is None)
            # свежее — по date, а не по файлу: владелец старше → побеждает модель (источник-ссылка, «скиллом»)
            page.evaluate("""() => { const r = state.data.macroInfl.map(x => /owner/.test(x.name)
                ? { ...x, parsed: { rawText: x.parsed.rawText.replace('2026-11-11', '2026-11-02') } } : x);
                state.data.macroInfl = r; goToTab('macro'); render(); }""")
            page.wait_for_selector("#macro-infl", timeout=5000)
            infl2 = page.inner_text("#macro-infl")
            check(f"{tag}: владелец старше модели → побеждает модель (04.11, 0,11, «скиллом», ссылка)",
                  "0,11" in infl2 and "внесено скиллом" in infl2 and page.query_selector("#macro-infl a[href^='https://rosstat']") is not None)
            # пороги 9 / 16 дней от даты свежей записи (04.11): 13.11 — 9 дн. граница, 14.11 — 10 жёлтая, 20.11 — 16 жёлтая, 21.11 — 17 красная
            def plate(day):
                page.evaluate(f"() => {{ state.todayOverride = '{day}'; goToTab('macro'); render(); }}")
                page.wait_for_selector("#macro-infl", timeout=5000)
                pl = page.query_selector("#macro-infl .infl-stale")
                return None if pl is None else (pl.get_attribute("data-infl-stale"), "warn" in (pl.get_attribute("class") or "").split())
            check(f"{tag}: 9 дней — плашки нет", plate("2026-11-13") is None)
            check(f"{tag}: 10 дней — жёлтая", plate("2026-11-14") == ("warn", True))
            check(f"{tag}: 16 дней — ещё жёлтая", plate("2026-11-20") == ("warn", True))
            check(f"{tag}: 17 дней — красная (без warn)", plate("2026-11-21") == ("fail", False))
            check(f"{tag}: пороги вьюера 9 и 16", page.evaluate("[STALE_THRESHOLDS_DAYS.macro, STALE_FAIL_DAYS.macro]") == [9, 16])
            # «с ИИ»: строка на «Действиях»; срок — только у инфляции (старые срезы скилла ru-*.md и автосрез не краснят)
            keys = page.evaluate("_staleList().map(x => x.key)")
            check(f"{tag}: просрочено только макро (инфляция), остальные отчёты — не из этой фикстуры ({keys})", "macro" in keys)
            check(f"{tag}: «с ИИ» — строка действия есть, команда с именем скилла",
                  page.evaluate("_actStaleList().some(x => x.key === 'macro')") and page.evaluate("STALE_SAY.macro") == "/macro-ru-watcher Обнови инфляцию")
            row = page.evaluate("""() => { const n = _staleRow(_staleList().find(x => x.key === 'macro')); return n.textContent + '|' + n.dataset.stale; }""")
            check(f"{tag}: строка «Обновить инфляцию» · срок вышел · команда ({row[:90]})",
                  "Обновить инфляцию" in row and "срок вышел — старше 16" in row and "/macro-ru-watcher Обнови инфляцию" in row and row.endswith("|macro"))
            alert = page.evaluate("buildStaleAlert().textContent")
            check(f"{tag}: плашка «Устарело» — «срок вышел», не «скиллы не работают»", "срок вышел — старше 16" in alert and "скиллы не работают" not in alert)
            check(f"{tag}: страница не шире экрана (с ИИ)", page.evaluate("document.documentElement.scrollWidth") <= w)
            check(f"{tag}: ошибок JS нет (с ИИ) {errs[:2]}", not errs)
            br.close()

            # ───── «без ИИ» ─────
            br, page, errs, posts, reply = run_viewer(p, base, w, h, off=True)
            page.evaluate("goToTab('macro')")
            page.wait_for_selector("#macro-infl-form", timeout=5000)
            check(f"{tag}: «без ИИ» — форма «Внести инфляцию» есть", page.query_selector("#infl-save") is not None)
            check(f"{tag}: «без ИИ» — строки «Обновить инфляцию» на «Действиях» нет, серой строки нет",
                  page.evaluate("_actStaleList().length") == 0 and page.evaluate("_noaiGreyList().every(x => x.key !== 'macro')"))
            page.evaluate("() => { state.todayOverride = '2026-11-21'; render(); }")
            page.wait_for_selector("#macro-infl-form", timeout=5000)
            check(f"{tag}: «без ИИ» — жёлтая/красная плашка есть, формой предлагается внести",
                  page.query_selector("#macro-infl .infl-stale") is not None and "формой ниже" in page.inner_text("#macro-infl"))
            check(f"{tag}: «без ИИ» — устаревшая инфляция в плашке «Устарело» (не серая)",
                  "инфляция" in page.evaluate("buildStaleAlert().textContent"))
            inputs = page.query_selector_all("#macro-infl-form input")
            check(f"{tag}: семь полей формы", len(inputs) == 7)
            check(f"{tag}: форма не вылезает за экран", all(i.bounding_box()["x"] + i.bounding_box()["width"] <= w + 0.5 for i in inputs)
                  and page.evaluate("document.documentElement.scrollWidth") <= w)
            # пусто → «Проверь», запроса нет
            page.fill("#infl-date", "2026-11-12")
            page.fill("#infl-week", "")
            page.click("#infl-save")
            check(f"{tag}: пустое «за неделю» — «Проверь …», запроса нет", "Проверь" in page.inner_text(".infl-err") and not posts)
            # сервер отверг (400) — тексты проблем
            reply.update(status=400, body={"error": "bad record", "problems": ["week_pct: число от -3 до 5"]})
            page.fill("#infl-week", "0,31")
            page.fill("#infl-period", "03–09.11")
            page.fill("#infl-yoy", "6,3")
            page.fill("#infl-asof", "2026-11-09")
            page.fill("#infl-src", "Росстат")
            page.click("#infl-save")
            page.wait_for_function("document.querySelector('.infl-err') && document.querySelector('.infl-err').textContent.includes('Сервер не принял')", timeout=5000)
            check(f"{tag}: 400 — «Сервер не принял: week_pct …»", "week_pct: число от -3 до 5" in page.inner_text(".infl-err"))
            reply.update(status=403, body={"error": "auth required"})
            page.click("#infl-save")
            page.wait_for_function("document.querySelector('.infl-err').textContent.includes('Нет доступа')", timeout=5000)
            check(f"{tag}: 403 — «Нет доступа»", True)
            # успех: тело запроса и запись сразу в карточке
            reply.update(status=200, body=None)
            posts.clear()
            page.click("#infl-save")
            page.wait_for_function("document.querySelector('#macro-infl').textContent.includes('0,31')", timeout=5000)
            check(f"{tag}: POST — одно тело {{record}} с числами, датой, источником", len(posts) == 1 and posts[0] == {"record": {
                "date": "2026-11-12", "week_pct": 0.31, "week_period": "03–09.11", "yoy_pct": 6.3, "yoy_as_of": "2026-11-09",
                "source_name": "Росстат", "source_url": None}})
            after = page.inner_text("#macro-infl")
            check(f"{tag}: запись видна сразу — 0,31, «внесено вами», плашка срока снята (12.11 — свежее)",
                  "0,31" in after and "внесено вами" in after and page.query_selector("#macro-infl .infl-stale") is None)
            check(f"{tag}: форма осталась для следующей записи", page.query_selector("#macro-infl-form") is not None)
            check(f"{tag}: страница не шире экрана (без ИИ)", page.evaluate("document.documentElement.scrollWidth") <= w)
            check(f"{tag}: ошибок JS нет (без ИИ) {errs[:2]}", not errs)
            br.close()
    httpd.shutdown()
    httpd.server_close()
    print(f"viewer_macro_auto: {passed} OK, {failed} FAIL")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
