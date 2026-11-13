#!/usr/bin/env python3
"""Генератор дизайн-системы «Personal Hub» из ui-kit (v2, 2026-10-26).

Источник истины — `tools/assets/ui-kit.css` (токены тем, шрифты, компоненты `.ui-*`) и
`tools/assets/viewer.css` (доменные классы вьюера: вердикт-теги, значки гейта, условия,
полосы веса и разложения). Разметку компонентов, которую ui-kit отдаёт функциями
(`uiModalHTML`, `uiTabsHTML`, `uiTimeChartHTML`, `uiInfoHTML`), скрипт получает запуском
`ui-kit.js` под node — превью совпадают с живыми страницами байт в байт.

Выход — `tools/design-reference/personal-hub-ds/project/` в формате артефакта «Design System»
(README.md, tokens.json, tokens.css, components/bundle.css, components/<Comp>/preview.html +
README.md, components/Cover/preview.html, fonts/, assets/Logos/). Публикация в артефакт
«Personal Hub — Design System» — отдельным шагом (Artifact publish с root=…/personal-hub-ds),
см. `tools/design-reference/viewer-rethink-plan.md` §3.

Запуск: python3 tools/design-reference/gen_personal_hub_ds.py  (stdlib + node в PATH)
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
ASSETS = REPO / "tools" / "assets"
OUT = REPO / "tools" / "design-reference" / "personal-hub-ds" / "project"
TITLE = "Personal Hub"
UIKIT = (ASSETS / "ui-kit.css").read_text(encoding="utf-8")
VIEWER = (ASSETS / "viewer.css").read_text(encoding="utf-8")


# ─── токены ─────────────────────────────────────────────────────────────────────

def _block(css: str, selector: str) -> str:
    m = re.search(r"^" + re.escape(selector) + r"\{(.*?)^\}", css, re.S | re.M)
    if not m:
        raise SystemExit(f"не найден блок {selector}")
    return m.group(1)


def _vars(body: str) -> dict[str, str]:
    return {k: " ".join(v.split()) for k, v in re.findall(r"--([\w-]+)\s*:\s*([^;]+);", body)}


L = {**_vars(_block(UIKIT, ":root")), **_vars(_block(VIEWER, ":root"))}
D = {**_vars(_block(UIKIT, '[data-theme="dark"]')), **_vars(_block(VIEWER, '[data-theme="dark"]'))}
NOT_COLOR = {"font-sans", "font-serif", "shadow", "radius"}

USAGE = {
    "bg": "Фон страницы (`body`, `.ui-page`). На нём читается `text`, `text-muted`, `text-faint`.",
    "bg-elev": "Фон карточек, окон, плиток `.ui-stat`, шапки — приподнятый слой над `bg`.",
    "bg-alt": "Подложка наведения строк `.ui-row.pick`, фон тегов `.tag.hold`, кнопка-плашка «что сказать Claude».",
    "bg-sunk": "Утопленный фон: дорожка `.ui-bar`, `.ui-seg`, `.meter`, пустой сегмент разложения.",
    "text": "Основной текст на `bg` и `bg-elev`. Контраст 11:1 (светлая), 12:1 (тёмная).",
    "text-muted": "Подписи, ключи `.ui-kv`, `.ui-sub`, заголовки колонок таблиц. На `bg-elev` 4,6:1 / 7,3:1.",
    "text-faint": "Самый бледный текст: `.ui-note`, тикер под названием `.ui-name .ui-sub`, интервал `.ui-ci`. На `bg-elev` 4,1:1 / 6,1:1 — только 11–12px пояснения, не для смысла.",
    "border": "Линии строк и карточек (`.ui-kv`, `.ui-card`, `.ui-table td`). Не для текста.",
    "border-strong": "Линии, несущие смысл: шапка таблицы, ось графика, рамка `.ui-seg.sm.acc`, левая черта `.catalyst`.",
    "accent": "Акцент по умолчанию (`--sec-acc`, когда страница не задала свой): ссылки, фокус, метка цели IE на шкале веса.",
    "accent-2": "Акцент при наведении на ссылку и кнопку.",
    "accent-bg": "Подложка под акцентный текст (чип «обновлено»).",
    "warn": "Внимание: вердикт TRIM, фундаментал MEDIUM, условие «созрело», гейт «нужен пересмотр». Текст на `warn-bg`.",
    "warn-bg": "Подложка предупреждений `.ui-alert.warn`, `.tag.trim`, `.cond-badge.ripe`.",
    "err": "Ошибка и опасность: вердикт SELL, red flag, «критично» в стрессе, минус в числах `.bad`. Текст на `err-bg`.",
    "err-bg": "Подложка `.ui-alert` (ошибка), `.tag.sell`, `.cond-badge.worst`.",
    "success": "Хорошо: вердикт BUY, фундаментал HIGH, условие сработало, гейт «держать», плюс в числах `.good`. Текст на `success-bg`.",
    "success-bg": "Подложка `.tag.buy`, `.tag.high`, `.cond-badge.fired`.",
    "info": "Нейтральная справочная метка: ИИС-3 `.tag.iis`, условие истекло `.cond-badge.expired`. Текст на `info-bg`.",
    "info-bg": "Подложка `.ui-alert.info`, `.tag.iis`.",
    "c-1": "Акцент раздела «Инвестиции» (вьюер портфеля): `--sec-acc`, линия акций на графиках (`--c-equity`).",
    "c-2": "Акцент раздела «Еда»; во вьюере — линия облигаций (`--c-bond`).",
    "c-3": "Акцент раздела «Здоровье»; во вьюере — сегмент «Дивиденды» в разложении доходности.",
    "c-4": "Акцент раздела «Путешествия».",
    "c-5": "Акцент раздела «Игры»; во вьюере — сегмент «Катализаторы» в разложении доходности.",
    "c-6": "Акцент раздела «Деньги»; во вьюере — сегмент «Макро» в разложении доходности. Свободных `c-N` нет: новый раздел — обсуждать.",
    "accent-line": "Вьюер: заливка факта на шкале веса `.meter-fill`, линия активной серии. Равен `c-1`.",
    "diff-add": "Вьюер, раздел «Изменения»: фон добавленной строки.",
    "diff-rem": "Вьюер, раздел «Изменения»: фон удалённой строки.",
    "diff-mod": "Вьюер, раздел «Изменения»: фон изменённой строки.",
    "c-equity": "Вьюер: акции на графиках «Динамики» и в сводках. Равен `c-1`.",
    "c-bond": "Вьюер: облигации на графиках «Динамики» и в сводках. Равен `c-2`.",
}

color_tokens = []
for name, lv in L.items():
    if name in NOT_COLOR or name.startswith("diff") and False:
        continue
    if name in NOT_COLOR:
        continue
    color_tokens.append({"name": name, "value": {"light": lv, "dark": D.get(name, lv)},
                         "usage": USAGE.get(name, "ui-kit.css")})

FONT_FILES = sorted(p.name for p in (ASSETS / "fonts").glob("*.woff2"))


def _font_entries() -> list[dict]:
    out = []
    # кириллический сабсет — последним в каждой паре семейство/начертание: в скомпилированном
    # tokens.css @font-face без unicode-range, и последний объявленный побеждает
    order = {"latin-ext": 0, "latin": 1, "cyrillic-ext": 2, "cyrillic": 3}
    rows = []
    for f in FONT_FILES:
        m = re.match(r"(golos-text|spectral)-(cyrillic-ext|cyrillic|latin-ext|latin)-(\d{3})-normal\.woff2$", f)
        if not m:
            continue
        fam = "Golos Text" if m.group(1) == "golos-text" else "Spectral"
        rows.append((fam, int(m.group(3)), order[m.group(2)], f))
    for fam, w, _, f in sorted(rows):
        out.append({"family": fam, "file": f"fonts/{f}", "weight": str(w), "style": "normal"})
    return out


def _style(name, size, lh, weight, usage, sample=None, **kw):
    s = {"name": name, "fontSize": size, "lineHeight": lh, "fontWeight": weight, "usage": usage}
    if sample:
        s["sample"] = sample
    s.update(kw)
    return s


TYPE = {
    "fonts": _font_entries(),
    "families": {"sans": L["font-sans"], "serif": L["font-serif"]},
    "groups": [
        {"name": "Заголовки (Spectral)", "family": "serif", "styles": [
            _style("t-h1", "44px", "1", 600, "Имя раздела `.ui-h1`: clamp(32px, 5vw, 44px), letter-spacing −.02em.", "Облигации", letterSpacing="-0.02em"),
            _style("t-h2", "22px", "1.2", 600, "Заголовок карточки раздела `.ui-h2`; `.lg` — 24px.", "Бумаги", letterSpacing="-0.01em"),
            _style("t-modal-title", "19px", "1.25", 600, "Название окна `.ui-modal-title` (карточка бумаги: «Yandex (3 472 ₽)»).", "Yandex (3 472 ₽)"),
            _style("t-lead", "14.5px", "1.5", 400, "Подзаголовок раздела `.ui-lead` курсивом: «данные на …».", "обзор облигаций от 2026-10-16 · цены — снапшот 2026-10-23", fontStyle="italic"),
            _style("t-table-th", "14px", "1.3", 600, "Заголовки числовых колонок обычной `.ui-table` (в `.dense` — капс без засечек).", "К погашению"),
        ]},
        {"name": "Текст (Golos Text)", "family": "sans", "styles": [
            _style("t-body", "14px", "1.5", 400, "Текст страницы `.ui-page`.", "Держать 9,0 % при плане 10 % — без добора и без среза."),
            _style("t-text", "13px", "1.5", 400, "Текст в карточках, строках `.ui-row`, `.ui-kv`, таблицах `.ui-text`."),
            _style("t-sub", "12.5px", "1.4", 400, "Подпись под заголовком окна `.ui-modal-sub`, `.ui-sub`, строка условия."),
            _style("t-note", "11.5px", "1.4", 400, "Пояснение `.ui-note` цветом `text-faint`: «суммы по снапшоту 23.10»."),
            _style("t-kicker", "11px", "1.3", 700, "Подзаголовок группы `.ui-kicker` капсом с разрядкой .06em: ПОЗИЦИЯ · МОДЕЛЬ IE · ОБЗОР.", "ПОЗИЦИЯ", letterSpacing="0.06em"),
            _style("t-stat-k", "10.5px", "1.25", 600, "Подпись плитки `.ui-stat-k` капсом .05em.", "ВЕС: ФАКТ", letterSpacing="0.05em"),
            _style("t-tag", "11px", "1.3", 600, "Теги `.tag` (вердикт, фундаментал), `.cond-badge` 11.5px.", "HOLD"),
        ]},
        {"name": "Числа (Golos Text, tabular-nums)", "family": "sans", "styles": [
            _style("t-big", "26px", "1.05", 600, "Крупное число плитки раздела `.ui-big`; единица рядом `.ui-unit` 13px.", "15,17", letterSpacing="-0.02em"),
            _style("t-big-xl", "44px", "1", 600, "`.ui-big.xl` — главное число раздела («Сегодня»).", "+7,1%", letterSpacing="-0.025em"),
            _style("t-card-tile", "22px", "1.2", 600, "Число плитки карточки бумаги `.card-tile .ui-stat-v`.", "9,01%", letterSpacing="-0.01em"),
            _style("t-stat-v", "19px", "1.2", 600, "Число плитки `.ui-stat-v` в сводках.", "13,79%"),
            _style("t-ci", "12px", "1.3", 500, "Интервал рядом с числом `.ui-ci` цветом `text-faint`: «[−3,8; +24,0]». Принцип: интервал — у каждого ожидания.", "[−3,8; +24,0]"),
        ]},
    ],
}

TOKENS = {
    "name": TITLE, "version": 2,
    "meta": {"source": "code", "repo": "claude_skills", "paths": {"tokens": ["tools/assets/ui-kit.css", "tools/assets/viewer.css"],
             "fonts": ["tools/assets/fonts/"], "components": ["tools/assets/ui-kit.css", "tools/assets/ui-kit.js", "tools/assets/viewer.css"]},
             "generator": "tools/design-reference/gen_personal_hub_ds.py"},
    "color": {"themes": [{"id": "light", "name": "Светлая"}, {"id": "dark", "name": "Тёмная"}], "tokens": color_tokens},
    "type": TYPE,
    "radius": {"tokens": [{"name": "radius", "value": L["radius"], "usage": "Карточки `.ui-card`, плашки `.ui-alert`. Окна — 14px, плитки `.ui-stat` и кнопки — 8px, теги — 999px (в классах, не токенами)."}]},
    "shadow": {"tokens": [{"name": "shadow", "value": {"light": L["shadow"], "dark": D["shadow"]}, "usage": "Тень карточек `.ui-card` и окон `.ui-modal-box`. Единственная тень системы; границы — `border`, не тени."}]},
}


# ─── bundle.css и tokens.css ───────────────────────────────────────────────────

def _cut(css: str, start_marker: str, end_marker: str) -> tuple[str, str]:
    a = css.index(start_marker)
    b = css.index(end_marker)
    return css[:a] + css[b:], css[a:b]


uikit_body, font_block = _cut(UIKIT, "/* ── Шрифты: Golos Text + Spectral", "/* ── Спиннер")
uikit_body, _tokens_block = _cut(uikit_body, "/* ── Дизайн-токены", "/* ── Базовый слой")
viewer_body = re.sub(r"^:root\{.*?^\}\n", "", VIEWER, count=1, flags=re.S | re.M)
viewer_body = re.sub(r'^\[data-theme="dark"\]\{.*?^\}\n', "", viewer_body, count=1, flags=re.S | re.M)
font_faces = re.sub(r",\s*url\([^)]*\.woff\) format\('woff'\)", "", font_block).replace("url(fonts/", "url(../fonts/")

BUNDLE_CSS = (
    f"/* {TITLE} — components/bundle.css: сборка из tools/assets/ui-kit.css и viewer.css\n"
    "   (без токенов тем — они в tokens.json). Источник истины — репозиторий; файл генерирует\n"
    "   tools/design-reference/gen_personal_hub_ds.py. Шрифты — с unicode-range, поэтому объявлены\n"
    "   здесь ещё раз (объявление позже побеждает; в tokens.css сабсеты без диапазонов). */\n"
    ".ds-p{ min-height:0; padding:18px 20px; }\n.ds-row{ display:flex; flex-wrap:wrap; gap:8px; align-items:center; }\n"
    ".ds-col{ display:flex; flex-direction:column; gap:12px; }\n.ds-lab{ font-size:11px; color:var(--text-faint); margin:0 0 6px; }\n\n"
    "/* ===== ui-kit.css ===== */\n" + uikit_body + "\n\n/* ===== viewer.css (доменные классы вьюера портфеля) ===== */\n" + viewer_body +
    "\n\n/* ===== @font-face с unicode-range ===== */\n" + font_faces
)


def tokens_css() -> str:
    lines = [f"/* {TITLE} — generated from tokens.json */"]
    lines.append(":root, [data-theme=\"light\"] {")
    for t in color_tokens:
        lines.append(f"  --{t['name']}: {t['value']['light']};")
    lines.append(f"  --shadow: {L['shadow']};")
    lines.append("}")
    lines.append("[data-theme=\"dark\"] {")
    for t in color_tokens:
        lines.append(f"  --{t['name']}: {t['value']['dark']};")
    lines.append(f"  --shadow: {D['shadow']};")
    lines.append("}")
    lines.append(":root {")
    lines.append(f"  --radius: {L['radius']};")
    lines.append(f"  --font-sans: {TYPE['families']['sans']};")
    lines.append(f"  --font-serif: {TYPE['families']['serif']};")
    lines.append("}")
    for g in TYPE["groups"]:
        fam = f"var(--font-{g['family']})"
        for s in g["styles"]:
            extra = "".join(f" {k}:{v};" for k, v in (("letter-spacing", s.get("letterSpacing")), ("font-style", s.get("fontStyle"))) if v)
            lines.append(f".{s['name']} {{ font-family:{fam}; font-size:{s['fontSize']}; line-height:{s['lineHeight']}; font-weight:{s['fontWeight']};{extra} }}")
    for f in TYPE["fonts"]:
        lines.append(f"@font-face {{ font-family:'{f['family']}'; font-weight:{f['weight']}; font-style:{f['style']}; font-display:swap; src:url({f['file']}) format('woff2'); }}")
    return "\n".join(lines) + "\n"


# ─── разметка из ui-kit.js (node) ─────────────────────────────────────────────

NODE_HARNESS = r"""
const fs=require("fs");
let src=fs.readFileSync(process.argv[2],"utf8");
src=src.replace(/^uiOfflineInit\(\);\s*$/m,"").replace(/^if \(document\.readyState === "loading"\).*$/m,"");
global.window={addEventListener(){},matchMedia:()=>({matches:false,addEventListener(){}})};
global.document={currentScript:null,readyState:"complete",addEventListener(){},querySelector:()=>null,createElement:()=>({style:{},setAttribute(){},appendChild(){}})};
global.navigator={};global.localStorage={getItem:()=>null,setItem(){}};
new Function(src+"\n;globalThis.__k={uiModalHTML,uiTabsHTML,uiTimeChartHTML,uiInfoHTML};")();
const calls=JSON.parse(fs.readFileSync(process.argv[3],"utf8"));
const out={};
for (const [k,[fn,...args]] of Object.entries(calls)) out[k]=globalThis.__k[fn](...args);
process.stdout.write(JSON.stringify(out));
"""


def node_render(calls: dict) -> dict:
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d)
        (p / "h.js").write_text(NODE_HARNESS, encoding="utf-8")
        (p / "c.json").write_text(json.dumps(calls, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run(["node", str(p / "h.js"), str(ASSETS / "ui-kit.js"), str(p / "c.json")],
                           capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


# ─── превью компонентов ────────────────────────────────────────────────────────

def preview(group: str, height: int, body: str, extra_css: str = "", width: int | None = None) -> str:
    w = f' width={width}' if width else ""
    return (f'<!-- @dsCard group="{group}" height={height}{w} static -->\n'
            f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>preview</title>'
            f'{("<style>" + extra_css + "</style>") if extra_css else ""}</head>'
            f'<body><div class="ui-page ds-p" style="--sec-acc:var(--c-1)">{body}</div></body></html>')


def tag(cls, text):
    return f'<span class="tag {cls}">{text}</span>'


def tile(k, v, sub, cls=""):
    return (f'<div class="ui-stat card-tile"><div class="ui-stat-k">{k}</div>'
            f'<div class="ui-stat-v{(" " + cls) if cls else ""}">{v}</div>' + (f'<div class="ui-note">{sub}</div>' if sub else "") + '</div>')


def kv(k, v, cls=""):
    return f'<div class="ui-kv"><span class="ui-muted">{k}</span><span{(" class=%s" % chr(34) + cls + chr(34)) if cls else ""}>{v}</span></div>'


CARD_TAGS = ('<div class="card-tags">' + tag("hold", "HOLD") + '<span class="vt-mk warn" title="есть условие">!</span>'
             '<span class="gate-badge gate-under" title="гейт: на пересмотре"></span>' + tag("medium", "фундаментал MEDIUM") +
             tag("high", "приоритет HIGH") + '</div>')
CARD_TILES = ('<div class="ui-grid stats card-tiles">' + tile("Вес: факт", "9,01%", "план 10% · IE 10%") +
              tile("Моя доходность", "−7,6%", "XIRR, годовых · 2026-10-23", "bad") +
              tile("Ожидание 12 мес", '+14,3% <span class="ui-ci">[−3,8; +24,0]</span>', "макро + дивиденды + катализаторы") +
              tile("Потенциал IE 12 мес", "+64,8%", "долгосрок +87,9% · цель ≈ 5 700 ₽", "good") + '</div>')
CARD_SUBS = ('<div class="card-subs ui-modal-stick"><div class="ui-seg sm acc" role="tablist">' +
             "".join(f'<button type="button" class="ui-seg-btn" role="tab" aria-pressed="{str(i == 0).lower()}">{l}</button>'
                     for i, l in enumerate(["Главное", "Доходность", "Риски", "История"])) + '</div></div>')
CARD_KV = ('<div class="card-kv"><div class="ui-kicker">Позиция</div>' + kv("Стоимость", "4 030 992 ₽") + kv("Количество", "129 шт.") +
           kv("Моя средняя", "4 126,20 ₽") + kv("Получено дивидендов", "116 010 ₽") + kv("Текущая прибыль", "−253 173 ₽", "bad") +
           kv("Результат", "−137 163 ₽", "bad") + '<div class="ui-kicker card-kv-k">Модель IE · 2026-10-23</div>' +
           kv("Цель по доле", "10%") + kv("Δ к IE", "−0,99 п.п. (намеренно)") + kv("Потенциал 12 мес", "+64,8% (≈ 5 700 ₽)") + '</div>')
CATALYSTS = (
    '<div class="catalyst"><div class="cat-t">Закрепление e-commerce в устойчивой прибыли (менеджмент ждёт на горизонте 12 мес)</div>'
    '<div class="cat-meta"><span class="cat-chip">окно 2026-Q4..2027-Q3</span><span class="cat-chip">вероятность 60%</span>'
    '<span class="cat-chip pos">эффект +14%</span></div><div class="cat-src ui-note">Источник: сегментные результаты Q2 2026</div></div>'
    '<div class="catalyst hl"><div class="cat-t">Прямые удары БПЛА по складам Яндекс Маркета</div>'
    '<div class="cat-meta"><span class="cat-chip">окно 2026-Q3..2027-Q2</span><span class="cat-chip">вероятность 35%</span>'
    '<span class="cat-chip neg">эффект −12%</span><span class="cat-chip">зависит от сценария D</span></div>'
    '<div class="cat-src ui-note">Источник: перенос реализованного сценария Ozon (22–24.08.2026)</div></div>')
CONDITION = (
    '<div class="card-cond"><div class="card-cond-h"><span class="cond-badge wait">ждём</span>'
    '<span class="ui-muted">дата 30.11.2026 · через 35 дн.</span><span class="cond-vd">' + tag("hold", "HOLD") +
    '<span class="ui-faint">→</span>' + tag("hold soft", "HOLD") + '</span></div>'
    '<div class="cond-evt ui-faint">ждём: МСФО Яндекса за 3К2026: гайденс скорр. EBITDA 2026 и раскрытие ущерба ЦОД</div>'
    '<div class="ui-text card-cond-a">Добор до 10% (≈ +158 700 ₽) — если гайденс EBITDA ≥ 332 млрд ₽, капзатраты ≤ 12% выручки и гейт снят; '
    'срез до 7% (≈ −288 000 ₽) — если гайденс снижен более чем на 5% или новая остановка ЦОД дольше 72 ч. Иначе — держать.</div>'
    '<details class="ui-fold act-say cond-say"><summary><span class="ui-muted">Что сказать Claude</span><span class="ui-chev">▾</span></summary>'
    '<div class="cond-say-i"><em>«Разбери YDEX по МСФО 3К2026»</em> <span class="ui-say">скопировать</span></div></details></div>'
    '<div class="card-cond"><div class="card-cond-h"><span class="cond-badge fired">сработало</span>'
    '<span class="ui-muted">дата 19.10.2026</span><span class="cond-vd">' + tag("trim", "TRIM") + '</span></div>'
    '<div class="ui-text card-cond-a">Срез до плана 5,0%: 27 акций ≈ 102 300 ₽ — решение владельца.</div></div>'
    '<div class="card-cond"><div class="card-cond-h"><span class="cond-badge ripe">созрело</span><span class="ui-muted">цена ≥ 1 180 ₽ (сейчас 1 187 — созрело)</span>'
    '<span class="cond-vd">' + tag("hold", "HOLD") + '<span class="ui-faint">→</span>' + tag("trim soft", "TRIM") + '</span></div></div>'
    '<div class="card-cond"><div class="card-cond-h"><span class="cond-badge expired">истёк</span><span class="ui-muted">до 31.10.2026</span></div></div>')


def build_components() -> dict[str, tuple[str, int, str, str, str]]:
    """{Comp: (group, height, body_html, extra_css, readme_md)}"""
    node = node_render({
        "tabs": ["uiTabsHTML", [{"id": "today", "label": "Сегодня"}, {"id": "stocks", "label": "Акции"}, {"id": "bonds", "label": "Облигации"},
                                {"id": "iis", "label": "ИИС-3"}, {"id": "pay", "label": "Выплаты"}, {"id": "dyn", "label": "Динамика"},
                                {"id": "stress", "label": "Стресс"}, {"id": "act", "label": "Действия", "n": "7", "alert": True},
                                {"id": "diff", "label": "Изменения"}, {"id": "goals", "label": "Доли и цели"}, {"id": "macro", "label": "Макро"},
                                {"id": "iv", "label": "Интеграционный анализ", "more": True}, {"id": "fc", "label": "Прогнозы", "more": True},
                                {"id": "src", "label": "Источники", "more": True}], "stocks", {}],
        "modal": ["uiModalHTML", {"title": "Yandex (3 472 ₽)", "sub": "YDEX · Коммуникации и развлечения", "width": 1150, "cls": "tall card-win",
                                  "lead": '<button type="button" class="ui-pager-btn" aria-label="Предыдущая бумага">←</button><button type="button" class="ui-pager-btn" aria-label="Следующая бумага">→</button>',
                                  "aside": '<span class="ui-pager-n">6 из 21</span>',
                                  "top": '<div class="card-head ui-modal-fold">' + CARD_TAGS + CARD_TILES + '</div>' + CARD_SUBS,
                                  "body": '<div class="card-pane"><div class="card-cols"><div class="card-col">'
                                          '<div class="modal-section"><h3>Обоснование вердикта</h3><div class="ui-text">Держать 8,97% при плане 10,0% без добора и без среза: '
                                          'IR 23.10 подтвердил восстановление доступа к данным Cloud, но ущерб и капзатраты эмитент не раскрыл.</div></div>'
                                          '<div class="modal-section"><h3>Отложенные условия</h3>' + CONDITION.split('<div class="card-cond"><div class="card-cond-h"><span class="cond-badge fired">')[0] + '</div>'
                                          '</div><div class="card-col side">' + CARD_KV + '</div></div></div>'}],
        "tchart": ["uiTimeChartHTML", {"key": "ds", "_w": 820, "unit": "₽", "series": [
            {"label": "цена по снапшотам", "pts": [{"date": d, "value": v} for d, v in [
                ("2026-05-12", 4005), ("2026-05-29", 4210), ("2026-06-11", 4120), ("2026-06-29", 3980), ("2026-07-15", 4160), ("2026-08-01", 4090),
                ("2026-08-15", 4230), ("2026-09-01", 4080), ("2026-09-16", 3835), ("2026-09-26", 3600), ("2026-10-01", 3520), ("2026-10-08", 3375),
                ("2026-10-16", 3427), ("2026-10-23", 3391)]]},
            {"label": "моя средняя", "pts": [{"date": "2026-05-12", "value": 4126}, {"date": "2026-10-23", "value": 4126}]}]}],
        "info": ["uiInfoHTML", "Разброс по сценариям стресса (худший … лучший) + дивиденды + катализаторы за горизонт.", {}],
    })
    C: dict[str, tuple[str, int, str, str, str]] = {}

    C["Headings"] = ("Основа", 300,
        '<div class="ui-h1">Облигации</div><p class="ui-lead">обзор облигаций от 2026-10-16 · цены и доли — снапшот 2026-10-23</p>'
        '<div class="ui-head split" style="margin-top:22px"><div class="ui-h2">Бумаги</div><span class="ui-sub">36 из 36 · клик по строке — карточка</span></div>'
        '<div class="ui-sechead"><h3>Сигнал · дюрация против денежного рынка</h3></div>'
        '<div class="ui-kicker">Позиция</div><p class="ui-text" style="margin:6px 0">Текст карточки 13px. <span class="ui-muted">Приглушённый.</span> <span class="ui-faint">Бледный.</span></p>'
        '<div class="ui-note">Пояснение 11,5px: суммы — по снапшоту 23.10, перед сделкой пересчитать.</div>', "",
        "Заголовки и уровни текста страницы раздела.\n\nИмя раздела — `.ui-h1` (Spectral), под ним `.ui-lead` курсивом со строкой «данные на …». Карточка раздела начинается с `.ui-h2`; группы внутри карточки — `.ui-sechead h3` или `.ui-kicker` капсом. Текст — `.ui-text`, подписи — `.ui-sub`, пояснения — `.ui-note`. Эмодзи в заголовках не используются.")

    C["Buttons"] = ("Основа", 200,
        '<div class="ds-row"><button class="ui-btn lg">Загрузки</button><button class="ui-btn">Обновить цены</button>'
        '<button class="ui-btn ghost">Открыть «Выплаты» →</button><button class="ui-btn" disabled>Сохранить</button></div>'
        '<div class="ds-row" style="margin-top:14px"><button class="ui-link">разобрать в «Действиях» →</button>'
        '<button class="ui-pager-btn" aria-label="Предыдущая">←</button><button class="ui-pager-btn" disabled aria-label="Следующая">→</button>'
        '<button class="ui-modal-x" aria-label="Закрыть">✕</button><span class="ui-say">Сделай обзор акций за неделю</span></div>', "",
        "Кнопки и ссылки-действия.\n\n`.ui-btn.lg` — одна главная кнопка формы; `.ui-btn` — обычное действие; `.ui-btn.ghost` — вторичное; `:disabled` с явным фоном. `.ui-link` — переход внутри страницы (к разделу, карточке). Стрелки листания `.ui-pager-btn` и крестик `.ui-modal-x` — только в шапке окна. `.ui-say` — фраза «что сказать Claude»: нажатие копирует текст.")

    gates = [("gate-new", "новая бумага"), ("gate-needed", "нужен пересмотр"), ("gate-keep", "держать"), ("gate-buymore", "докупать"),
             ("gate-under", "на пересмотре"), ("gate-aging", "устаревает"), ("gate-reduce", "сокращать"), ("gate-divested", "выведена")]
    C["Tags"] = ("Основа", 330,
        '<p class="ds-lab">Вердикт обзора</p><div class="ds-row">' + tag("buy", "BUY") + tag("hold", "HOLD") + tag("trim", "TRIM") + tag("sell", "SELL") +
        tag("hold", "HOLD_TO_MAT") + '<span class="ui-faint">·</span>' + tag("hold", "HOLD") + '<span class="ui-faint">→</span>' + tag("trim soft", "TRIM") +
        '<span class="vt-mk warn" title="есть условие">!</span><span class="vt-mk ok">✓</span></div>'
        '<p class="ds-lab" style="margin-top:14px">Фундаментал и качество</p><div class="ds-row">' + tag("high", "HIGH") + tag("medium", "MEDIUM") + tag("low", "LOW") +
        tag("red_flag", "RED FLAG") + tag("iis", "❄ ИИС-3") + '<span class="ui-tag">приватный</span></div>'
        '<p class="ds-lab" style="margin-top:14px">Гейт (значок у вердикта)</p><div class="ds-row" style="gap:14px">' +
        "".join(f'<span class="ui-sub"><span class="gate-badge {c}" style="margin:0 6px 0 0"></span>{l}</span>' for c, l in gates) + '</div>'
        '<p class="ds-lab" style="margin-top:14px">Состояние условия</p><div class="ds-row"><span class="cond-badge wait">ждём</span><span class="cond-badge ripe">созрело</span>'
        '<span class="cond-badge fired">сработало</span><span class="cond-badge expired">истёк</span><span class="cond-badge closed">закрыто</span><span class="cond-badge worst">худший</span></div>', "",
        "Метки вьюера портфеля: вердикт, фундаментал, гейт, условия.\n\nЦвет метки — только из семантических пар (`success`/`warn`/`err`/`info` на своих `-bg`): BUY и HIGH — `success`, TRIM и MEDIUM — `warn`, SELL и RED FLAG — `err`, HOLD и LOW — нейтральные. Пара «сейчас → при срабатывании» — два тега со стрелкой, второй `.soft`. Значок гейта `.gate-badge` ставится справа от вердикта и всегда сопровождается словом в подсказке — цвет сам по себе смысла не несёт.")

    C["Alert"] = ("Основа", 260,
        '<div class="ui-alert tight warn"><strong>Слепое пятно макро.</strong> Чувствительность к макро почти нулевая — цену двигает сама компания, стресс её почти не видит.</div>'
        '<div class="ui-alert tight info">ИИС-3: файл БКС от 12.10 старше снапшота — выгрузи сделки счёта.</div>'
        '<div class="ui-alert tight">Снапшот не собран: нет выгрузки trades_portfolio_*.xlsx.</div>', "",
        "Плашка состояния в потоке страницы.\n\nБез модификатора — ошибка (`err`), `.info` — справка, `.warn` — предупреждение; `.tight` — компактная внутри карточки. Текст начинается с сути жирным. Не использовать для подсказок «как читать» — для них `(i)` (Info).")

    C["Seg"] = ("Основа", 190,
        '<p class="ds-lab">Переключатель раздела</p><div class="ui-seg"><button class="ui-seg-btn" aria-pressed="true">К моему плану</button><button class="ui-seg-btn" aria-pressed="false">к цели IE</button></div>'
        '<p class="ds-lab" style="margin-top:14px">Мелкий</p><div class="ui-seg sm"><button class="ui-seg-btn" aria-pressed="true">6 мес</button><button class="ui-seg-btn" aria-pressed="false">12 мес ★</button><button class="ui-seg-btn" aria-pressed="false">24 мес</button></div>'
        '<p class="ds-lab" style="margin-top:14px">Подвкладки карточки (.sm.acc)</p>' + CARD_SUBS.replace(' ui-modal-stick', ''), "",
        "Сегментный переключатель `.ui-seg`: период, режим, подвкладки.\n\nВыбранная кнопка — `aria-pressed=\"true\"`. `.sm` — компактный; `.sm.acc` — подвкладки карточки бумаги: выбранная подсвечена подложкой `--sec-acc`, иначе на карточке не читалась. Больше 6–7 пунктов — не сегмент, а строка разделов (Tabs).")

    C["Tabs"] = ("Основа", 120, node["tabs"], "",
        "Строка разделов страницы `.ui-tabs` (`uiTabsHTML`).\n\nОдна строка без эмодзи, прокручивается вбок на телефоне; редкие разделы — в «Ещё ▾». Счётчик `.ui-tab-n` справа от имени (`.alert` — красным, если требует действия). Текущий раздел — `aria-current=\"page\"` с чертой цвета `--sec-acc`.")

    C["Info"] = ("Основа", 170,
        '<div class="ui-h2" style="font-size:18px">Ожидание 12 мес <span class="ui-info-glue">+14,3% ' + node["info"].replace('class="ui-info"', 'class="ui-info open"') + '</span></div>'
        '<p class="ui-note" style="margin-top:90px">Наведение — подсказка с задержкой ухода; касание — до касания мимо или Esc.</p>', "",
        "Значок (i) с подсказкой `uiInfoHTML` — пояснение «как читать число» вместо абзаца текста.\n\nСтавится последним словом заголовка через `.ui-info-glue` (не отрывается переносом). Внутри — одно-два предложения; коды и формулы — только здесь, не в тексте страницы.")

    C["Fold"] = ("Основа", 150,
        '<details class="ui-fold" open><summary><span class="ui-muted">Что сказать Claude</span><span class="ui-chev">▾</span></summary>'
        '<div class="cond-say-i" style="margin-top:6px"><em>«Разбери YDEX по МСФО 3К2026»</em> <span class="ui-say">скопировать</span></div>'
        '<div class="cond-say-i"><em>«Закрой условие ydex-q3-ifrs-guidance»</em> <span class="ui-say">скопировать</span></div></details>', "",
        "Сворачиваемый блок `details.ui-fold`: второстепенное содержимое, которое не должно загромождать карточку (фразы для Claude, источники, состояние компании).\n\nСтрелка `.ui-chev` поворачивается при раскрытии. Раскрытие блока в потоке страницы анимируется `uiExpandIn`/`uiCollapseOut`, не CSS.")

    spark = ('<div class="ui-spark sm z"><svg viewBox="0 0 100 40" preserveAspectRatio="none"><line class="zero" x1="0" y1="34" x2="100" y2="34"/>'
             '<polyline points="0,20 12,22 24,18 36,24 48,16 60,19 72,15 84,17 100,12"/></svg><span class="ui-spark-zero">0</span></div>'
             '<div class="ui-spark-x ends"><span>апр ’26</span><span>окт ’26</span></div>')
    C["Tiles"] = ("Данные", 300,
        '<div class="ui-grid kpi"><div class="ui-card tile ui-tile acc"><div class="ui-stat-k">Портфель</div><div class="ui-big">15,17 <span class="ui-unit">млн ₽</span></div>'
        '<div class="ui-sub">акции 33% · облигации 50% · кэш и ликвидность 4,8 млн ₽</div><div class="ui-note">снапшот 2026-10-23</div></div>'
        '<button class="ui-card ui-tile"><div class="ui-stat-k">Доходность активной части</div><div class="ui-big good">+7,1% <span class="ui-unit">годовых</span></div>'
        '<div class="ui-sub">вся история с замороженными: +3,2%</div>' + spark + '</button>'
        '<div class="ui-card ui-tile"><div class="ui-stat-k">Требует внимания</div><div class="ui-big warn">7</div><div class="ui-sub">решений по счёту 3 · 4 важных предупреждения</div></div></div>', "",
        "Плитки главных чисел раздела `.ui-grid.kpi` > `.ui-card.ui-tile` с `.ui-big` («как в Деньгах»).\n\nПодпись капсом `.ui-stat-k`, число `.ui-big` с единицей `.ui-unit`, под ним `.ui-sub` и дата в `.ui-note`. Кликабельная плитка — `button.ui-tile`. Мини-график `.ui-spark.sm` за 6 месяцев по календарю с нулевой линией `line.zero`. Первая плитка раздела — `.acc` (полоска `--sec-acc`). Интервал у ожидания — `.ui-ci` рядом с числом, всегда.")

    C["Stats"] = ("Данные", 150, CARD_TILES, "",
        "Ряд плиток карточки бумаги `.ui-grid.stats.card-tiles` > `.ui-stat.card-tile`.\n\nЧетыре плитки одной высоты (на ~1100px — 2×2): вес факт/план/IE, моя доходность, ожидание на горизонте с интервалом `.ui-ci`, потенциал IE. Знак числа окрашивается `.good`/`.bad`; подпись под числом — `.ui-note`. Облигация: доля в облигациях, доходность к погашению с купоном, погашение/оферта с дюрацией, моя доходность.")

    C["KV"] = ("Данные", 460, '<div style="max-width:380px">' + CARD_KV + '</div>', "",
        "Колонка «ключ — значение» `.card-kv` > `.ui-kv` справа на «Главном» карточки бумаги.\n\nГруппы — `.ui-kicker` (первый без отступа, следующие `.card-kv-k`). Значение выравнивается вправо, числа табличные; минус — `.bad`, плюс — `.good`. Строка без значения не рисуется (не «—»).")

    def th(label, num=False, sort=None):
        a = f' aria-sort="{sort}"' if sort else ' aria-sort="none"'
        return f'<th class="{"num" if num else ""}"{a}>{label}</th>'
    rows = [("Озон", "OZON", "87", "921 984 ₽", "6,2% акций", "−26,8%", "bad", "Потребительский цикличный", "low", "LOW", "hold", "HOLD", "+26,9%"),
            ("X5", "X5", "133", "913 113 ₽", "6,1% акций", "+4,7%", "good", "Потребительский защитный", "medium", "MEDIUM", "hold", "HOLD", "+8,8%"),
            ("MD Medical", "MDMG", "213", "828 783 ₽", "5,6% акций", "+10,0%", "good", "Здравоохранение", "high", "HIGH", "trim", "TRIM", "+13,6%"),
            ("Полюс", "PLZL", "182", "615 888 ₽", "4,1% акций", "−17,8%", "bad", "Добывающий", "low", "LOW", "hold", "HOLD", "+44,7%")]
    C["Table"] = ("Данные", 330,
        '<div class="ui-table-wrap flow"><table class="ui-table dense sticky"><thead><tr>' + th("Бумага", sort="none") + th("Кол-во", True) + th("Стоимость", True, "descending") +
        th("Доходность", True) + th("Сектор") + th("Фундаментал") + th("Вердикт") + th("Ожид. дох. за 12 мес", True) + '</tr></thead><tbody>' +
        "".join(f'<tr><td><div class="ui-name"><b>{n}</b><span class="ui-sub">{t}</span></div></td><td class="num">{q}</td>'
                f'<td class="num"><div class="ui-name mat-cell"><b>{v}</b><span class="ui-sub">{s}</span></div></td><td class="num {rc}">{r}</td><td>{sec}</td>'
                f'<td>{tag(fc, fl)}</td><td>{tag(vc, vl)}<span class="gate-badge gate-keep"></span></td><td class="num">{e}</td></tr>'
                for n, t, q, v, s, r, rc, sec, fc, fl, vc, vl, e in rows) +
        '</tbody><tfoot><tr class="total"><td>Итого</td><td></td><td class="num">43 879 761 ₽</td><td class="num good">+7,1%</td><td colspan="4"></td></tr></tfoot></table></div>', "",
        "Таблица данных `.ui-table.dense` в обёртке `.ui-table-wrap`.\n\nКолонка «Бумага» — `.ui-name`: название, под ним тикер бледнее; стоимость — так же с долей второй строкой. Числа — `.num` вправо, шапка — капс без засечек, сортировка по клику на `th[aria-sort]`, липкая шапка `.sticky`, итог — `tfoot`. Шире экрана — липкая копия шапки `uiTableStickyHead`. Поиск по таблице — `.ui-qbox` в строке заголовка карточки.")

    C["Row"] = ("Данные", 230,
        '<div class="ui-row head" style="--cols:120px 1fr 56px"><span>По типу</span><span></span><span class="num">доля</span></div>' +
        "".join(f'<div class="ui-row" style="--cols:120px 1fr 56px"><span>{l}</span><div class="ui-bar"><i style="width:{w}%"></i></div><span class="num" style="text-align:right">{w}%</span></div>'
                for l, w in [("Замещайка", 48.2), ("ОФЗ", 28.4), ("Корп RUB", 23.4)]) +
        '<div class="ui-row" style="--cols:120px 1fr 56px"><span class="ui-muted">ИИС-3</span><div class="ui-bar thin"><i class="quiet" style="width:4%"></i></div><span class="num" style="text-align:right">4,0%</span></div>', "",
        "Строка с полосой `.ui-row` + `.ui-bar` — распределения (типы облигаций, кредитное качество, доли).\n\nКолонки задаются `--cols`; шапка — `.ui-row.head`. Полоса цвета `--sec-acc`, второстепенная — `i.quiet`. Один график на экран: распределения рядом полосами, без круговых диаграмм.")

    C["TimeChart"] = ("Данные", 330, '<div style="max-width:860px">' + node["tchart"] + '</div>', "",
        "График показателя во времени `uiTimeChartHTML`/`uiTimeChartMount`: ось X — даты замеров (цена по снапшотам, маркер здоровья).\n\n≤20 замеров — вся история; больше и не влезает — «полгода» с прокруткой и переключателем. Паузы — разрыв, частые замеры — медианы. Вторая серия — `.alt` пунктиром (здесь — «моя средняя»). Своих SVG-графиков по датам страницы не заводят.")

    C["Meter"] = ("Данные", 170,
        '<div style="max-width:420px"><div class="ui-kicker" style="margin-bottom:22px">Вес vs целевой</div><div class="meter"><div class="meter-fill" style="width:72%"></div>'
        '<div class="meter-plan" style="left:80%"></div><div class="meter-ie" style="left:80%"></div><div class="meter-lab">9,01%</div></div>'
        '<div class="wlegend"><span><i class="wl-fact"></i>факт</span><span><i class="wl-plan"></i>план 10%</span><span><i class="wl-ie"></i>IE цель 10%</span><span>Δ план −0,99 пп</span></div></div>', "",
        "Шкала веса `.meter`: заливка — факт, две метки — план владельца и цель IE.\n\nДоменный компонент вьюера (три метки на одной шкале); цвета — `accent-line` (факт), `text` (план), `accent` (IE). Подписи меток «план»/«IE» рисует CSS над шкалой — оставлять 22px сверху.")

    C["RetStack"] = ("Данные", 170,
        '<div style="max-width:720px"><div class="modal-section"><h3>Разложение ожидаемой доходности<span class="decomp-total-val">+14,3%</span></h3>'
        '<div class="ret-stack"><span class="ret-seg macro" style="width:4%"></span><span class="ret-seg div" style="width:45%">+6,5%</span><span class="ret-seg idio" style="width:51%">+7,5%</span></div>'
        '<div class="ret-legend"><span><i style="background:var(--c-6)"></i>Макро +0,3%</span><span><i style="background:var(--c-3)"></i>Дивиденды +6,5%</span><span><i style="background:var(--c-5)"></i>Катализаторы +7,5%</span></div></div></div>', "",
        "Полоса разложения ожидаемой доходности `.ret-stack`: макро (`c-6`) + дивиденды (`c-3`) + катализаторы (`c-5`).\n\nСоставляющая меньше 0,05% на полосе не рисуется (в легенде остаётся бледной); отрицательная — `.neg` серым курсивом. Итог — справа в заголовке `.decomp-total-val`. Все проценты — за горизонт, не годовых: подпись обязательна.")

    C["Modal"] = ("Карточка бумаги", 720, node["modal"],
        ".ui-modal{ position:absolute; } .ui-modal-box{ max-height:none; height:680px; }",
        "Окно карточки бумаги `uiModalHTML` 1150px по центру, стопкой (`uiStackCls`/`uiStackPop`).\n\nШапка: стрелки листания слева (`lead`), название с ценой, тикер · сектор, счётчик справа (`aside`), ✕. Закреплённая полоса `top`: метки, четыре плитки (`Stats`), подвкладки (`Seg .sm.acc`); на телефоне плитки сворачиваются при прокрутке (`.fold`). Тело — две колонки `.card-cols`: слева блоки `.modal-section` с заголовком-капсом, справа липкая колонка `KV`. Содержимое меняется по клику — `cls: \"tall\"`. На телефоне — во весь экран.")

    C["Catalyst"] = ("Карточка бумаги", 260, '<div style="max-width:760px">' + CATALYSTS + '</div>', "",
        "Катализатор `.catalyst`: что может двинуть бумагу, окно, вероятность, эффект.\n\nЛевая черта `border-strong`; эффект — `.cat-chip.pos`/`.neg`; «зависит от сценария» — чип. Подсвеченный (`.hl`) — открыт по ссылке из «Изменений». В переделке карточки — на подвкладке «Риски», числа p/эффект уходят в подсказку.")

    C["Condition"] = ("Карточка бумаги", 330, '<div style="max-width:760px">' + CONDITION + '</div>', "",
        "Отложенное условие `.card-cond`: состояние, триггер, вердикт «сейчас → потом», действие, фразы для Claude.\n\nСостояния — `.cond-badge` ждём / созрело / сработало / истёк / закрыто. Ценовой триггер показывает текущую цену и расстояние. Событие, которого ждём, — `.cond-evt` (`.pub` — вышло). Фразы «что сказать Claude» — в `Fold`. В переделке карточки действие становится таблицей «если → то» с суммами.")

    return C


READMES_GROUP = {"Основа": "", "Данные": "", "Карточка бумаги": ""}

README = """Личный кабинет на Synology: портфель, деньги, здоровье, поездки, игры, еда. Один стиль на все страницы — тихий, редакционный: серифные заголовки, спокойные бумажные фоны, тонкие линии, мало цвета. Это инструмент для одного человека, не лендинг: без hero-блоков, градиентов, эмодзи в заголовках, карточек с цветной левой кромкой ради украшения.

## Голос

- Русский язык везде; англицизмы и коды системы (`L2`, `review_needed`, `Mode 4`, id условий) в тексте для человека не появляются — только слова; формулы и коды живут в подсказке `(i)`.
- Числа — с единицей и датой: «45,5 млн ₽ · снапшот 2026-10-23». Десятичная запятая, разряды пробелом, минус — `−`, проценты без пробела.
- У каждого ожидания — интервал рядом с числом (`t-ci`): «+14,3% [−3,8; +24,0]». Число без разброса — не ожидание, а факт.
- Кабинет не даёт советов «купить/продать» от себя: вердикты — из обзоров, арифметика лотов подписана как арифметика.
- Фразы, которые человек скажет Claude, — кнопкой-плашкой `.ui-say` (нажатие копирует), не в тексте.

## Цвет

- Фон страницы `bg`, карточки и окна — `bg-elev`, утопленные дорожки — `bg-sunk`. Границы — `border`; смысловые линии — `border-strong`. Тень одна — `shadow`, только у карточек и окон.
- Текст: `text` на `bg`/`bg-elev`; `text-muted` для подписей и ключей; `text-faint` — только пояснения 11–12px (на `bg-elev` 4,1:1 в светлой теме, смысл на нём не держать).
- Акцент раздела один: `--sec-acc` = `c-1` инвестиции · `c-2` еда · `c-3` здоровье · `c-4` путешествия · `c-5` игры · `c-6` деньги. Акцент идёт на полоску первой плитки, черту текущего раздела, ссылки, выбранную подвкладку. Крупные площади акцентом не заливать. Свободных `c-N` нет.
- Семантика только парами «цвет на своём фоне»: `success`/`success-bg` (BUY, HIGH, плюс), `warn`/`warn-bg` (TRIM, MEDIUM, «созрело»), `err`/`err-bg` (SELL, red flag, минус), `info`/`info-bg` (ИИС-3, «истёк»). Зелёный и терракотовый различимы по светлоте в обеих темах, но каждая метка несёт слово — цвет сам по себе смысла не передаёт.
- Обе темы обязательны: каждое правило проверяется на `[data-theme="dark"]`. Фон и цвет у `body` заданы в ui-kit — окна наследуют их.

## Шрифт

- `serif` (Spectral) — имя раздела `t-h1`, заголовки карточек `t-h2`, название окна `t-modal-title`, подзаголовок `t-lead` курсивом.
- `sans` (Golos Text) — всё остальное: текст `t-body`/`t-text`, подписи `t-sub`, пояснения `t-note`, подзаголовки групп капсом `t-kicker`, метки `t-tag`.
- Числа — Golos с табличными цифрами: `t-big` в плитках раздела, `t-card-tile` в карточке бумаги, `t-stat-v` в сводках, интервал `t-ci`.
- Шрифты самохостятся (кириллица + латиница, woff2), никаких CDN: страницы живут офлайн и в локальной сети.

## Раскладка

- Страница: шапка `.ui-top` одной строкой (крошка · ромб раздела · кнопки Обновить · Справка · Войти · Тема), строка разделов `Tabs`, `.ui-main` до 1040px (вьюер — 1240px), подвал с версией страницы.
- Раздел начинается с `t-h1` + `t-lead`, затем плитки `Tiles` (3–4 главных числа), затем карточки `.ui-card.lg` с `t-h2`.
- Карточка бумаги — окно `Modal` 1150px, на телефоне во весь экран; карточка из карточки — стопкой с «← назад».
- Телефон: боковой отступ 16px, поля ввода ≥16px (иначе iOS приближает), длинные токены переносятся, на касании `:hover` не держится.
- Один график месяцев на экран; распределения — полосами `Row`, не круговыми диаграммами.

## Иконография

Значков нет: только текстовые глифы — ✕ (закрыть), ← → (листание), ▾ (раскрыть), (i) — кнопка-кружок `Info`, ромб раздела в шапке — CSS. Эмодзи — только ❓ у кнопки «Справка» и ❄ у метки ИИС-3 (исторически). Логотип — иконка кабинета из шести ромбов цветами разделов и ромб портфеля (`assets/Logos`), в интерфейсе используются только как иконки сайта.

## Компоненты

Новый компонент добавляется в ui-kit (`tools/assets/ui-kit.css/js`), а не в страницу; страница держит только данные (ширины, координаты) в inline-стилях. Доменные классы вьюера (вердикт-теги, значки гейта, условия, шкала веса, разложение доходности) живут в `viewer.css` и перекрашены в токены. Контракт «класс в JS ↔ правило в CSS» проверяет `tools/tests/test_pages_contracts.py`.
"""

LOGOS_README = """Иконки кабинета (не рисовать заново, копировать из `tools/assets/icons/`):

- `hub-512.png` — шесть ромбов цветами разделов `c-1`…`c-6`; иконка сайта и ярлыка всех страниц кабинета.
- `portfolio-512.png` — ромб цвета `c-1`; иконка веб-приложения вьюера портфеля (у него свои уведомления).

Многоцветные PNG — краска в самом файле, токенов не наследуют.
"""


def cover() -> str:
    return """<!-- @dsCard height=288 -->
<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>cover</title><style>
.cv{position:relative;width:960px;height:288px;background:var(--bg);overflow:hidden;font-family:var(--font-serif)}
.cv svg{position:absolute;inset:0;width:960px;height:288px}
.c1{fill:var(--c-1)}.c2{fill:var(--c-2)}.c3{fill:var(--c-3)}.c4{fill:var(--c-4)}.c5{fill:var(--c-5)}.c6{fill:var(--c-6)}
.rule{stroke:var(--border-strong);stroke-width:1}
.tile{rx:var(--radius)}
.name{position:absolute;left:40px;bottom:50px;max-width:440px;color:var(--text);font-weight:600;font-size:96px;line-height:.95;letter-spacing:-.02em;margin:0}
.tagline{position:absolute;left:42px;bottom:26px;max-width:440px;color:var(--text-muted);font-family:var(--font-sans);font-size:13.5px;margin:0}
</style></head><body><div class="cv">
<!-- derivation:
     blocks: c-1 (инвестиции) 300×132 · c-6 (деньги) 150×132 · c-3 (здоровье) 160×72 · c-4 (путешествия) 120×72 · c-2 (еда) 90×48 · c-5 (игры) 60×48 — шесть красок разделов, вес по площади раздела в кабинете
     arrangement: ступенчатая стопка полос у правого края, крупная слева-сверху, сбегает вниз-вправо; всё правее x=480
     pattern: editorial, serif, «границы, не тени» → три горизонтальные hairline-правила border-strong, пересекающие блоки; одна строка — не поле
     scales: шаг 20px между блоками, скругление radius (9px) у каждого блока -->
<svg viewBox="0 2 880 864" aria-hidden="true">
  <rect class="c1 tile" x="500" y="24" width="300" height="132"/>
  <rect class="c6 tile" x="820" y="24" width="150" height="132"/>
  <rect class="c3 tile" x="560" y="176" width="160" height="72"/>
  <rect class="c4 tile" x="740" y="176" width="120" height="72"/>
  <rect class="c2 tile" x="880" y="176" width="90" height="48"/>
  <rect class="c5 tile" x="500" y="200" width="40" height="48"/>
  <line class="rule" x1="480" y1="92" x2="960" y2="92"/>
  <line class="rule" x1="480" y1="164" x2="960" y2="164"/>
  <line class="rule" x1="480" y1="236" x2="960" y2="236"/>
</svg>
<p class="name">Personal<br>Hub</p>
<p class="tagline">портфель · деньги · здоровье · поездки · игры · еда</p>
</div></body></html>
"""


def main() -> None:
    if OUT.parent.exists():
        shutil.rmtree(OUT.parent)
    (OUT / "components").mkdir(parents=True)
    (OUT / "fonts").mkdir()
    (OUT / "assets" / "Logos").mkdir(parents=True)
    for f in FONT_FILES:
        shutil.copy(ASSETS / "fonts" / f, OUT / "fonts" / f)
    for f in ("hub-512.png", "portfolio-512.png"):
        shutil.copy(ASSETS / "icons" / f, OUT / "assets" / "Logos" / f)
    (OUT / "assets" / "Logos" / "README.md").write_text(LOGOS_README, encoding="utf-8")
    (OUT / "README.md").write_text(README, encoding="utf-8")
    (OUT / "tokens.json").write_text(json.dumps(TOKENS, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "tokens.css").write_text(tokens_css(), encoding="utf-8")
    (OUT / "components" / "bundle.css").write_text(BUNDLE_CSS, encoding="utf-8")
    for name, (group, h, body, extra, readme) in build_components().items():
        d = OUT / "components" / name
        d.mkdir()
        (d / "preview.html").write_text(preview(group, h, body, extra), encoding="utf-8")
        (d / "README.md").write_text(f"# {name}\n\n{readme}\n", encoding="utf-8")
    (OUT / "components" / "Cover").mkdir()
    (OUT / "components" / "Cover" / "preview.html").write_text(cover(), encoding="utf-8")
    files = sorted(p.relative_to(OUT).as_posix() for p in OUT.rglob("*") if p.is_file())
    total = sum((OUT / f).stat().st_size for f in files)
    print(f"{len(files)} файлов, {total / 1024:.0f} КБ → {OUT}")
    print(f"цветов: {len(color_tokens)} · шрифтов: {len(TYPE['fonts'])} · стилей: {sum(len(g['styles']) for g in TYPE['groups'])} · компонентов: {len([f for f in files if f.endswith('preview.html')])}")


if __name__ == "__main__":
    main()
