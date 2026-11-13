#!/usr/bin/env python3
"""Вьюер, проход читаемости 4.1.0, пачка 2 «слова» (аудит 31.10: F3, F4, F6, F7, F14, F16; решение R27 от 03.11) — настоящий Chromium.

Фикстура — viewer-live + superseded + conditions-pack (как в test_viewer_conditions_pack) во временной папке.
Контракты:
  F3/F4. В видимом тексте «Действий», «Акций», «Облигаций», карточки акции (YDEX, GMKN) и окна «Решения» нет кодов
      (HOLD/SELL/ADD/BUY/TRIM/WATCH/HOLD_TO_MAT/HIGH/MEDIUM/LOW) и слова «гейт» — только слова кодлистов; код — в подсказке.
      Мутант «чип показывает код» (codeWord возвращает код) обязан ронять эту проверку — тест прогоняет его сам.
  F6. Нет имён файлов (.yaml/.json/.md), путей Portfolio/ и id условий (и на «Долях и целях») вне фразы для Claude и подсказок; «восстановлено из истории» —
      только подсказкой у даты в «Истории» карточки (там же «≈» у времени), в тексте нигде.
  R27. Строка «Докупка: …» по каждому виду причины модуля (б): открыта; закрыта решением («наблюдать, до дд.мм»;
      «нужен разбор»; «новая, без разбора»; «срок решения вышел дд.мм, откроет разбор»), IPO-пауза, пауза после докупки,
      несколько причин — через «;»; у фонда и облигации строки нет.
  F7. Условие без веток с действием «разобрать» (YDEX): «ТОГДА: разбор бумаги», проза свёрнута; «ждём: …», совпадающее
      с шапкой, не дублируется; «создано … · разбор бумаги» — одна ссылка.
  F16. Плашка «План против последнего слова»; кнопка «Отчёты».
  F14. Светлая тема: блокирующие чипы (нужен разбор, наблюдать, срок решения вышел, IPO-пауза, «сократить», «средний») —
      контраст ≥ 4,5:1 и шрифт ≥ 11,5 px; ссылки (mode-lnk, ui-link) — ≥ 4,5:1. Тёмная тема — не ниже 4,35:1.
  Ошибок страницы нет.
Требует playwright + chromium; без них — пропуск. Запуск: python3 tools/tests/test_viewer_words.py
"""
import json
import re
import shutil
import sys
import tempfile
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import quote as _q, unquote as _unq, urlparse as _up

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pages_stand import serve  # noqa: E402  (стенд — _pages_stand, keep-alive)
passed = failed = 0


def check(name, cond_):
    global passed, failed
    if cond_:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("viewer_words: пропуск — нет playwright")
    sys.exit(0)

sys.path.insert(0, str(REPO / "tools/hosting/api"))
import server as hub_api  # noqa: E402

FIX = Path(tempfile.mkdtemp(prefix="vwords-"))
TODAY = "2026-10-30"
CODES = re.compile(r"\b(HOLD_TO_MAT|HOLD|SELL|ADD|BUY|TRIM|WATCH|HIGH|MEDIUM|LOW)\b")
FILES = re.compile(r"[\w-]+\.(?:ya?ml|json|md)\b|Portfolio/")


def build():
    shutil.rmtree(FIX, ignore_errors=True)
    fx = REPO / "tools/tests/fixtures"
    shutil.copytree(fx / "viewer-live", FIX)
    shutil.copytree(fx / "superseded", FIX, dirs_exist_ok=True)
    shutil.copytree(fx / "conditions-pack", FIX, dirs_exist_ok=True)
    (FIX / "monitor-reports").mkdir(exist_ok=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        have = json.loads(self.rfile.read(n) or b"{}").get("have") or {}
        if _up(self.path).path != "/api/pv/sync":
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        body = json.dumps(hub_api.pv_sync(str(FIX), have)).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = _unq(_up(self.path).path)
        f = REPO / "tools" / p[len("/tools/"):] if p.startswith("/tools/") else FIX / p.lstrip("/")
        if f.is_dir() or (p.endswith("/") and not f.exists()):
            body = ("<html><body>" + "".join(f'<a href="{_q(c.name)}{"/" if c.is_dir() else ""}">{c.name}</a>\n'
                                             for c in (sorted(f.iterdir()) if f.is_dir() else [])) + "</body></html>").encode()
            ct = "text/html"
        elif f.is_file():
            body = f.read_bytes()
            ct = {".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css",
                  ".json": "application/json", ".woff2": "font/woff2"}.get(f.suffix, "text/plain; charset=utf-8")
        else:
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)


srv = serve(Handler)[0]   # _pages_stand: очередь 128, keep-alive
URL = f"http://127.0.0.1:{srv.server_address[1]}/tools/portfolio-integrated-viewer.html"

# видимый текст узла без фразы для Claude (её читает модель: пути и id там нужны) — скрыть, прочитать innerText, вернуть
VISIBLE = """(sel) => {
  const root = typeof sel === 'string' ? document.querySelector(sel) : sel;
  if (!root) return '';
  const st = document.createElement('style');
  st.textContent = '.act-say, .gate-say, .cond-say, .act-rerun { display:none !important; }';
  document.head.append(st);
  const t = root.innerText;
  st.remove();
  return t;
}"""
# контраст и размер шрифта по вычисленным стилям (формула WCAG, фон — первый непрозрачный предок; как audit-tools/contrast.py)
CONTRAST = """(sel) => {
  const rgb = (s) => (s.match(/[\\d.]+/g) || [0, 0, 0, 0]).map(Number);
  const lum = (c) => { const a = c.slice(0, 3).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2]; };
  const bg = (e) => { while (e) { const c = rgb(getComputedStyle(e).backgroundColor); if (c.length < 4 || c[3] > 0.5) if (c[3] !== 0) return c; e = e.parentElement; } return [255, 255, 255]; };
  return [...document.querySelectorAll(sel)].filter(e => e.getBoundingClientRect().width > 0).map(e => {
    const cs = getComputedStyle(e), L1 = lum(rgb(cs.color)), L2 = lum(bg(e));
    return { t: e.textContent.trim().slice(0, 30), cr: +((Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05)).toFixed(2), fs: parseFloat(cs.fontSize) };
  });
}"""


def norm(t):
    return re.sub(r"[\s  ]+", " ", t or "").strip()


def open_page(p, dark=False):
    browser = p.chromium.launch()
    ctx = browser.new_context(service_workers="block", viewport={"width": 1400, "height": 1000})
    if dark:
        ctx.add_init_script("try { localStorage.setItem('hub-theme', 'dark'); } catch (e) {}")
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "502" not in m.text and "404" not in m.text else None)
    pg.route("**/api/pv/plan*", lambda r: r.fulfill(status=502, body="{}"))
    pg.route("**/api/moex/quotes*", lambda r: r.fulfill(status=502, body="{}"))
    pg.goto(URL)
    pg.wait_for_selector("#tabs .ui-tab", timeout=20000)
    pg.wait_for_function("() => state.data && state.data.portfolioLatest && state.data.weeklyReviewCurrent && state.data.decisions.length", timeout=20000)
    pg.evaluate("(d) => { state.todayOverride = d; dsInvalidate(); }", TODAY)
    return browser, pg, errs


def screens(pg):
    """видимый текст основных экранов: вкладки, карточки YDEX и GMKN («Главное»), окно «Решения» (все строки раскрыты)."""
    out = {}
    for tab in ("actions", "positions", "bonds"):
        pg.evaluate("(t) => { cardStack.length = 0; renderCards(); goToTab(t); }", tab)
        pg.wait_for_timeout(500)
        out[tab] = pg.evaluate(VISIBLE, "#content")
    for t in ("YDEX", "GMKN"):
        pg.evaluate("(t) => { cardStack.length = 0; renderCards(); const pbt = buildPositionByTicker(); openCard(pbt[t], [pbt[t]]); }", t)
        pg.wait_for_selector("#card-layer .card-dec", timeout=8000)
        pg.wait_for_timeout(300)
        out["card " + t] = pg.evaluate(VISIBLE, "#card-layer")
    pg.evaluate("() => { cardStack.length = 0; renderCards(); state.decFilter = ''; showGateLegendModal(''); document.querySelectorAll('#modal-body details').forEach(d => d.open = true); }")
    pg.wait_for_timeout(300)
    out["Решения"] = pg.evaluate(VISIBLE, "#modal-body")
    pg.evaluate("() => closeModal()")
    pg.wait_for_timeout(400)
    return out


def main():
    with sync_playwright() as p:
        try:
            p.chromium.launch().close()
        except Exception as e:
            print(f"viewer_words: пропуск — {str(e).splitlines()[0][:80]}")
            return
        build()
        browser, pg, errs = open_page(p)
        txt = screens(pg)
        cids = pg.evaluate("() => dsCondRows().map(c => c.id).filter(Boolean)")
        pg.evaluate("() => { goToTab('ie-model'); }")
        pg.wait_for_timeout(500)
        txt["ie-model"] = pg.evaluate(VISIBLE, "#content")
        for k, t in txt.items():
            ids = [c for c in cids if c in t]
            check(f"F6 {k}: id условий нет в тексте — только текст условия ({ids[:3]})", not ids)
            check(f"{k}: экран отрисован ({len(t)} знаков)", len(t) > 200)
            codes = sorted({m.group(1) for m in CODES.finditer(t)})
            check(f"F3 {k}: кодов в видимом тексте нет ({codes}; …{t[max(0, CODES.search(t).start() - 60):CODES.search(t).end() + 30] if codes else ''}…)", not codes)
            g = re.search(r".{0,60}[Гг]ейт.{0,40}", t)
            check(f"R27 {k}: слова «гейт» нет ({g.group(0) if g else ''!r})", g is None)
            f = FILES.search(t)
            check(f"F6 {k}: имён файлов и путей нет вне фразы для Claude ({t[max(0, f.start() - 50):f.end() + 10] if f else ''!r})", f is None)
            check(f"F6 {k}: «восстановлено из истории» нет", "восстановлено из истории" not in t)
            iso = re.search(r".{0,50}\b20\d\d-\d\d-\d\d\b.{0,20}", t) if k in ("actions", "positions", "bonds", "card YDEX", "card GMKN") else None
            check(f"4.2.4 {k}: ISO-дат «2026-10-28» на экране нет — «дд.мм» / «дд.мм.гггг» ({iso.group(0) if iso else ''!r})", iso is None)
        check("F3: в чипах вердикта код — в подсказке (title), на экране слово",
              pg.evaluate("() => { goToTab('positions'); const t = document.querySelector('#content .tag[data-code=HOLD]'); return !!t && t.textContent === 'Держать' && /HOLD/.test(t.title); }"))

        # 4.2.4: чипы источника строки — один класс act-src с data-src по типу, одинаковый размер шрифта; на «Действиях», «Сегодня», «Изменениях», в карточке
        chips = []
        for tab in ("actions", "today", "diff"):
            pg.evaluate("(t) => { cardStack.length = 0; renderCards(); goToTab(t); document.querySelectorAll('#content details').forEach(d => d.open = true); }", tab)
            pg.wait_for_timeout(400)
            chips += pg.evaluate("""() => [...document.querySelectorAll('#content [class*="act-src"], #content [data-src]')].map(x => [x.className, x.dataset.src || '', getComputedStyle(x).fontSize, x.textContent])""")
        pg.evaluate("() => { cardStack.length = 0; renderCards(); const pbt = buildPositionByTicker(); openCard(pbt.YDEX, [pbt.YDEX]); document.querySelectorAll('#card-layer details').forEach(d => d.open = true); }")
        pg.wait_for_selector("#card-layer .card-dec", timeout=8000)
        chips += pg.evaluate("""() => [...document.querySelectorAll('#card-layer [class*="act-src"], #card-layer [data-src]')].map(x => [x.className, x.dataset.src || '', getComputedStyle(x).fontSize, x.textContent])""")
        bad = [c for c in chips if c[0].split()[0] != "act-src" or not c[1]]
        check(f"4.2.4 чипы источника: все — act-src с data-src ({len(chips)} шт., без метки: {bad[:2]})", len(chips) >= 3 and not bad)
        check(f"4.2.4 чипы источника: один размер шрифта, типов не больше 7 ({sorted({c[2] for c in chips})}, {sorted({c[1] for c in chips})})",
              len({c[2] for c in chips}) == 1 and len({c[1] for c in chips}) <= 7)
        pg.evaluate("() => { cardStack.length = 0; renderCards(); }")

        # мутант: чип снова показывает код — проверка «кодов нет» обязана это поймать
        pg.evaluate("() => { window.__cw = codeWord; window.codeWord = (l, c) => String(c ?? ''); }")
        pg.evaluate("() => { goToTab('positions'); }")
        pg.wait_for_timeout(400)
        mt = pg.evaluate(VISIBLE, "#content")
        check(f"мутант «код в чипе» ловится проверкой кодов ({sorted({m.group(1) for m in CODES.finditer(mt)})})", CODES.search(mt) is not None)
        pg.evaluate("() => { window.codeWord = window.__cw; goToTab('positions'); }")
        pg.wait_for_timeout(300)
        check("после отката мутанта кодов снова нет", CODES.search(pg.evaluate(VISIBLE, "#content")) is None)

        # «История» карточки: пометка бэкфилла — только подсказкой у даты
        pg.evaluate("() => { cardStack.length = 0; renderCards(); const pbt = buildPositionByTicker(); openCard(pbt.GMKN, [pbt.GMKN]); }")
        pg.wait_for_selector("#card-layer .card-dec", timeout=8000)
        pg.evaluate("() => document.querySelector('#card-layer .ui-seg-btn[data-v=hist]').click()")
        pg.wait_for_selector("#card-layer .card-tl", timeout=8000)
        h = pg.evaluate("""() => ({ text: document.querySelector('#card-layer .card-tl').innerText,
          est: [...document.querySelectorAll('#card-layer .card-tl .tl-d[title]')].map(x => [x.title, x.innerText]) })""")
        check(f"F6 «История»: в тексте «восстановлено из истории» нет, есть подсказка у даты с «≈» у времени ({h['est'][:2]})",
              "восстановлено из истории" not in h["text"] and any("восстановлено из истории" in t and "≈" in v for t, v in h["est"]))
        check(f"R27 «История»: слова «гейт» нет", "гейт" not in h["text"].lower())

        # R27: «Докупка: …» по видам причин (модуль (б): gate.reasons) — слова, даты, «;» между причинами
        words = pg.evaluate("""() => ({
          open: buyReasonsText({ reasons: [] }),
          under: buyReasonsText({ reasons: ['gate:reviewed_under_review'], expires_on: '2026-12-13' }),
          need: buyReasonsText({ reasons: ['gate:review_needed'], expires_on: '2026-12-13' }),
          fresh: buyReasonsText({ reasons: ['gate:new_position'] }),
          aging: buyReasonsText({ reasons: ['gate:review_aging'], expires_on: '2026-10-20' }),
          ipo: buyReasonsText({ reasons: ['ipo_gate:3q'], ipo_pause_until: '2027-04-30' }),
          cool: buyReasonsText({ reasons: ['add_cooldown:2026-11-12'], add_cooldown_until: '2026-11-12' }),
          two: buyReasonsText({ reasons: ['gate:reviewed_under_review', 'ipo_gate:3q'], expires_on: '2026-12-13', ipo_pause_until: '2027-04-30' }) })""")
        check(f"«Докупка»: решение «наблюдать» — «наблюдать, до 13.12» ({words['under']!r})", words["under"] == "наблюдать, до 13.12")
        check(f"«Докупка»: «нужен разбор» и «новая, без разбора» ({words['need']!r}, {words['fresh']!r})", words["need"] == "нужен разбор" and words["fresh"] == "новая, без разбора")
        check(f"«Докупка»: срок вышел — «срок решения вышел 20.10, откроет разбор» ({words['aging']!r})", words["aging"] == "срок решения вышел 20.10, откроет разбор")
        check(f"«Докупка»: IPO-пауза и пауза после докупки ({words['ipo']!r}, {words['cool']!r})", words["ipo"] == "IPO-пауза до 30.04.2027" and words["cool"] == "пауза после докупки до 12.11")
        check(f"«Докупка»: несколько причин — через «;» ({words['two']!r})", words["two"] == "наблюдать, до 13.12; IPO-пауза до 30.04.2027")
        lines = pg.evaluate("""() => { const out = {}; for (const k of lwCtx().stock_keys) { const t = buyLineText(k); if (t) out[k] = [t, lwCard(k).gate.blocking]; } return out; }""")
        check(f"«Докупка»: у держимых акций строка есть, «открыта» ⇔ не блокирует ({len(lines)})",
              len(lines) >= 5 and all(t == "Докупка: открыта" if not b else t.startswith("Докупка: закрыта: ") for t, b in lines.values())
              and any(b for _, b in lines.values()) and any(not b for _, b in lines.values()))
        check("«Докупка»: у фонда строки нет", pg.evaluate("() => buyLineText('TMON') === null"))
        card_gmkn = norm(txt["card GMKN"])
        check(f"карточка GMKN: «Докупка: закрыта: наблюдать, до 13.12» ({card_gmkn[:240]!r})", "Докупка: закрыта: наблюдать, до 13.12" in card_gmkn)

        # F7: YDEX — условие без веток с действием «разобрать»
        pg.evaluate("() => { cardStack.length = 0; renderCards(); const pbt = buildPositionByTicker(); openCard(pbt.YDEX, [pbt.YDEX]); }")
        pg.wait_for_selector("#card-layer .card-wait", timeout=8000)
        w = pg.evaluate("""() => { const c = document.querySelector('#card-layer .card-wait .card-cond[data-cond="ydex-q3-ifrs-guidance"]');
          return c ? { text: c.innerText, more: !!c.querySelector('details.card-then-more:not([open])'), made: c.querySelectorAll('.cond-made').length,
                       links: c.querySelectorAll('.cond-src-made').length } : null; }""")
        wt = norm(w["text"] if w else "")
        check(f"F7 YDEX: «ТОГДА: разбор бумаги», проза свёрнута ({wt[:200]!r})", bool(w) and re.search(r"ТОГДА\s*:?\s*разбор бумаги", w["text"], re.I) is not None and w["more"])
        check(f"F7 YDEX: «ждём: …» не повторяет шапку ({wt[:200]!r})", "ждём: МСФО" not in wt)
        check(f"F7 YDEX: «создано … · разбор бумаги» — одна строка-ссылка ({w and (w['made'], w['links'])})", bool(w) and w["made"] == 1 and w["links"] == 1)

        # F16: плашка и кнопка
        check("F16: плашка «План против последнего слова»",
              pg.evaluate("() => lwPlaquesNode({ plan_vs_decision: { user_plan: 'WAIT', verdict: 'BUY', source_kind: 'review' } }).textContent.startsWith('План против последнего слова: план «ждать», обзор «докупать»')"))
        check("F16: кнопка в шапке — «Отчёты»", pg.evaluate("() => document.querySelector('#btn-reports .h-btn-lbl').textContent") == "Отчёты")

        # F14: контраст блокирующих чипов и ссылок в светлой теме
        pg.evaluate("() => { cardStack.length = 0; renderCards(); goToTab('ie-model'); }")
        pg.wait_for_timeout(500)
        pg.evaluate("""() => { const box = document.createElement('div'); box.id = 'cr-probe'; box.className = 'ui-card';
          box.append(...['gate-needed', 'gate-under', 'gate-aging', 'trim', 'medium'].map(c => el('span', { class: 'tag ' + c }, 'проба ' + c)),
            el('button', { class: 'mode-lnk' }, 'разбор бумаги'), el('button', { class: 'ui-link' }, 'скопировать'), el('div', { class: 'act-cond' }, 'Ждёт условия:'));
          document.querySelector('#content').append(box); }""")
        chips = pg.evaluate(CONTRAST, "#cr-probe .tag")
        links = pg.evaluate(CONTRAST, "#cr-probe .mode-lnk, #cr-probe .ui-link, #cr-probe .act-cond")
        real = pg.evaluate(CONTRAST, "#content .rb-gate .tag.gate-needed, #content .rb-gate .tag.gate-under, #content .rb-gate .tag.gate-aging, #content .rb-gate .tag.trim")
        check(f"F14 светлая: блокирующие чипы ≥ 4,5:1 и ≥ 11,5 px ({chips})", len(chips) == 5 and all(c["cr"] >= 4.5 and c["fs"] >= 11.5 for c in chips))
        check(f"F14 светлая: чипы под тикером на «Долях и целях» ≥ 4,5:1 ({real[:4]})", all(c["cr"] >= 4.5 and c["fs"] >= 11.5 for c in real))
        check(f"F14 светлая: ссылки и «Ждёт условия:» ≥ 4,5:1 ({links})", len(links) == 3 and all(c["cr"] >= 4.5 for c in links))
        check(f"ошибок страницы нет ({errs[:2]})", not errs)
        browser.close()

        browser, pg, errs = open_page(p, dark=True)
        pg.evaluate("() => { goToTab('ie-model'); }")
        pg.wait_for_timeout(400)
        check("тёмная тема включена", pg.evaluate("() => document.documentElement.getAttribute('data-theme')") == "dark")
        pg.evaluate("""() => { const box = document.createElement('div'); box.id = 'cr-probe'; box.className = 'ui-card';
          box.append(...['gate-needed', 'gate-under', 'gate-aging', 'trim', 'medium'].map(c => el('span', { class: 'tag ' + c }, 'проба ' + c)),
            el('button', { class: 'mode-lnk' }, 'разбор бумаги'), el('button', { class: 'ui-link' }, 'скопировать'), el('div', { class: 'act-cond' }, 'Ждёт условия:'));
          document.querySelector('#content').append(box); }""")
        dk = pg.evaluate(CONTRAST, "#cr-probe .tag, #cr-probe .mode-lnk, #cr-probe .ui-link, #cr-probe .act-cond")
        check(f"F14 тёмная: не хуже 4,35:1 ({dk})", len(dk) == 8 and all(c["cr"] >= 4.35 for c in dk))
        check("F14 тёмная: ссылки — акцентом раздела, не цветом текста (токен светлой темы в тёмной не действует)",
              pg.evaluate("() => { const a = getComputedStyle(document.querySelector('#cr-probe .ui-link')).color, t = getComputedStyle(document.body).color; return a !== t; }"))
        check(f"ошибок страницы нет (тёмная) ({errs[:2]})", not errs)
        browser.close()


main()
shutil.rmtree(FIX, ignore_errors=True)
print(f"Итого: {passed} из {passed + failed} прошли" if failed == 0 else f"Итого: {passed} из {passed + failed} прошли (падений: {failed})")
sys.exit(1 if failed else 0)
