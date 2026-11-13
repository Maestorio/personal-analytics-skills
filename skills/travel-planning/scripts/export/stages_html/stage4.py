"""Stage 4 → HTML (дизайн-система Claude Design).

Переиспользует `stages.stage4.extract_content`; presentation на CSS-классах
Design: .opt-grid/.opt-card (компактные карточки вариантов), сравнительная
матрица (.data-table--compact с подсветкой рекомендованной колонки), .cut
(жертвы), полный per-variant detail (интро + подсекции) через md_block.
Решение («## Решение») — за пользователем в самом .md, в витрине не рендерится.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

try:
    from export import html_lib
    from export.stages import stage4 as s4
    from export.stages import stage5 as s5
except ImportError:  # запуск из каталога export/
    import html_lib  # type: ignore
    from stages import stage4 as s4, stage5 as s5  # type: ignore

md = html_lib.md_inline
mdb = html_lib.md_block
esc = html_lib.esc
ru = html_lib.ru_anglicisms  # единый русификатор англицизмов (cost rank, Variant…)

# Контракт полноты: ключи extract_content, учтённые build_html. Новый ключ без
# учёта → красный drift-тест.
CONSUMED_KEYS = frozenset({
    "title", "frontmatter", "warnings", "cover", "trip_params", "context",
    "priority_buckets", "comparison_rows", "variants", "extras", "honest",
    "general_comment",
})

_REGIONS_RE = re.compile(r"\*\*Регионы:\*\*\s*([^\n]+)")
_SPLIT_RE = re.compile(r"\s*(?:->|→)\s*")
_REG_NIGHTS_RE = re.compile(r"(.+?)\s*\((\d+\s*н[^)]*)\)")
_COST_RE = re.compile(r"\*\*Cost rank:\*\*\s*`?(\$+)")


def _norm_letter(s) -> str:
    """`вариант_а` / «Вариант A» / `A` → ведущая буква в верхнем регистре."""
    s = str(s or "").replace("вариант_", "").replace("вариант ", "").replace("_", " ").strip()
    return s[:1].upper() if s else ""


def _field(intro: str, label: str) -> str:
    m = re.search(rf"\*\*{re.escape(label)}:\*\*\s*([^\n]+)", intro)
    return m.group(1).strip().rstrip(".") if m else ""


def _regions(intro: str) -> list[tuple[str, str]]:
    m = _REGIONS_RE.search(intro)
    if not m:
        return []
    out = []
    for part in _SPLIT_RE.split(m.group(1)):
        mm = _REG_NIGHTS_RE.match(part.strip())
        if mm:
            out.append((mm.group(1).strip(), mm.group(2).strip().replace(" ", " ")))
    return out


def _cost_html(intro: str) -> str:
    m = _COST_RE.search(intro)
    if not m:
        return ""
    n = len(m.group(1))
    off = f'<span class="off">{"$" * (3 - n)}</span>' if n < 3 else ""
    return f'<span class="cost">{"$" * n}{off}</span>'


def _passport(rows: list[tuple[str, str]]) -> str:
    return ('<div class="passport">' + "".join(
        f'<div class="passport-row"><div class="passport-k">{esc(k)}</div>'
        f'<div class="passport-v">{md(str(v), todo=False)}</div></div>'
        for k, v in rows if v) + "</div>")


def _cover_rows(extracted: dict) -> list[tuple[str, str]]:
    """Паспорт поездки: кто/старт-финиш/сезон/длительность/темп/бюджет/вариантов."""
    cover = extracted["cover"]
    tp = extracted.get("trip_params") or {}
    rows: list[tuple[str, str]] = []
    if tp.get("группа"):
        rows.append(("Кто едет", tp["группа"]))
    start, finish = tp.get("старт"), tp.get("финиш")
    if start and finish and start.strip().lower() == finish.strip().lower():
        rows.append(("Старт и финиш", start))
    elif start and finish:
        rows.append(("Старт / финиш", f"{start} → {finish}"))
    season = tp.get("сезон") or s4._season_from_trip_id(cover.get("trip_id") or "")
    if season:
        rows.append(("Сезон", season))
    if cover.get("duration_nights"):
        rows.append(("Длительность", f"{cover['duration_nights']} ночей"))
    if tp.get("темп"):
        rows.append(("Темп", tp["темп"]))
    if cover.get("budget_target_rub"):
        rows.append(("Бюджет", f"≈{cover['budget_target_rub']:,} ₽".replace(",", " ")))
    n_variants = cover.get("variants_count") or len(extracted.get("variants") or [])
    if n_variants:
        rows.append(("Вариантов", str(n_variants)))
    return rows


def _card(v, recommended: str) -> str:
    is_rec = bool(recommended) and _norm_letter(v.letter) == recommended
    tempo = _field(v.intro, "Темп")
    note = _field(v.intro, "Open-jaw")
    regs = "".join(
        f'<div class="opt-reg"><span>{esc(name)}</span><span class="n">{esc(nights)}</span></div>'
        for name, nights in _regions(v.intro)
    )
    tag = '<span class="opt-chosen-tag">рекомендован</span>' if is_rec else ""
    return (
        f'<div class="opt-card{" is-chosen" if is_rec else ""}">'
        f'<div class="opt-head"><span class="opt-letter">{esc(v.letter)}</span>{tag}</div>'
        f'<div class="opt-title">{md(ru(v.title), todo=False)}</div>'
        f'<div class="opt-meta"><span>{esc(tempo)}</span>{_cost_html(v.intro)}</div>'
        f'<div class="opt-regions">{regs}</div>'
        f'<div class="opt-note">{md(note, todo=False)}</div></div>'
    )


def _matrix(rows: list[list[str]], recommended: str) -> str:
    if not rows:
        return ""
    header = [ru(c) for c in rows[0]]  # Variant → Вариант через единый ru_anglicisms
    rec_col = None
    if recommended:
        for i, c in enumerate(header):
            if _norm_letter(c.split()[-1] if c.split() else "") == recommended:
                rec_col = i
    def cell(tag, i, c):
        cls = ' class="is-chosen"' if rec_col == i else ""
        return f"<{tag}{cls}>{md(ru(c), todo=(tag=='td'))}</{tag}>"
    head = "".join(cell("th", i, c) for i, c in enumerate(header))
    body = "".join("<tr>" + "".join(cell("td", i, c) for i, c in enumerate(r)) + "</tr>"
                   for r in rows[1:])
    return (f'<table class="data-table data-table--compact"><thead><tr>{head}</tr>'
            f"</thead><tbody>{body}</tbody></table>")


def _cut(body: str) -> str:
    items = [re.sub(r"^\s*[-*]\s+", "", ln) for ln in body.splitlines()
             if re.match(r"^\s*[-*]\s+", ln)]
    if not items:
        return mdb(body)
    lis = "".join(f"<div class=\"cut-item\"><span>{md(it)}</span></div>" for it in items)
    return f'<div class="cut">{lis}</div>'


def _priority_html(buckets) -> str:
    pairs = []
    for b in buckets or []:
        val = ", ".join(b.names) if getattr(b, "names", None) else (
            f"{b.count} поз." if b.count else "—")
        pairs.append(f'<dt>{esc(b.label)}</dt><dd>{esc(val)}</dd>')
    return f'<dl class="kv">{"".join(pairs)}</dl>' if pairs else ""


def _comment_slot(key: str, label: str, text: str) -> str:
    """Слот комментария: якорь edit-слоя (data-var-comment) + статичный текст,
    если заполнен. Пустой слот без живого write-API скрыт CSS'ом."""
    static = (f'<span class="vc-static"><span class="fill-label">{esc(label)}:</span> '
              f'{md(text, todo=False)}</span>') if text else ""
    return (f'<div class="var-comment" data-var-comment="{esc(key)}" '
            f'data-label="{esc(label)}">{static}</div>')


# ---------------------------------------------------------------------------
# Edit-слой: комментарии к вариантам прямо из HTML
# ---------------------------------------------------------------------------
# Тот же протокол, что у edit-слоя Stage 3 (GET /api/health · GET /api/file ·
# POST /api/save {path, content, base_hash}); нет API → статичная витрина.
# Пишет в md секцию `## Комментарии к вариантам` (строки `**Вариант X:** …` /
# `**Общий комментарий:** …`): существующая строка правится, отсутствующая
# дописывается в конец секции; нет секции — создаётся перед `## Решение`
# (или в конце файла). Регэксп строки — из Python-парсера (ноль дрейфа).

_EDIT_CSS = (
    ".var-comment:empty{display:none;}"
    ".var-comment{margin:8px 0 12px;}"
    ".var-edit{display:flex;gap:10px;align-items:flex-start;}"
    ".var-edit .fill-label{padding-top:7px;}"
    ".var-edit textarea{flex:1;font:inherit;font-size:var(--fs-small,12px);"
    "background:var(--paper);color:inherit;border:1px solid var(--line);"
    "border-radius:6px;padding:6px 8px;min-height:2.4em;resize:vertical;}"
    ".edit-bar{position:fixed;right:18px;bottom:calc(18px + var(--tnav-bottom,0px));"
    "z-index:50;display:flex;gap:12px;align-items:center;background:var(--paper);"
    "color:var(--ink);font-family:var(--font-body);border:1px solid var(--line);"
    "border-radius:9px;box-shadow:0 4px 14px rgba(0,0,0,.18);padding:8px 12px;}"
    ".edit-bar button{font:inherit;font-size:var(--fs-small,12px);padding:6px 14px;"
    "border-radius:7px;border:1px solid var(--line);background:var(--accent);"
    "color:#fff;cursor:pointer;}"
    ".edit-bar button[disabled]{opacity:.5;cursor:default;}"
    ".edit-status{font-size:var(--fs-small,12px);opacity:.75;}"
    # display:flex выше перебивал атрибут hidden — панель висела всегда, с
    # пустым статусом и его отступом слева (кнопка не по центру рамки)
    ".edit-bar[hidden]{display:none;}.edit-status:empty{display:none;}"
    "@media print{.edit-ui,.edit-bar{display:none !important;}}"
)

_EDIT_JS = r"""
(function(){
"use strict";
if (!window.fetch || !window.URL || location.protocol === "file:") return;
var CFG = JSON.parse(document.getElementById("s4-edit-config").textContent);
var RE_LINE = new RegExp(CFG.reLine, "i"), RE_H2 = /^##\s+(.+?)\s*$/;
var mdPath = decodeURIComponent(new URL(".", location.href).pathname)
             .replace(/^\/+/, "") + CFG.mdFile;
var state = null; /* {hash, lines, comments:{ключ→строка}} */
var edits = {};
function key(m){ return m[2] ? m[2].trim().charAt(0).toUpperCase() : CFG.general; }
function lineFor(k, txt){
  var lbl = (k === CFG.general) ? CFG.generalLabel : "Вариант " + k;
  return "**" + lbl + ":**" + (txt ? " " + txt : "");
}

function apiFetch(url, init){
  init = init || {};
  init.credentials = "omit";
  var tok = null;
  try { tok = localStorage.getItem("hub-auth"); } catch(e){}
  if (tok){
    var h = new Headers(init.headers || {});
    h.set("Authorization", "Basic " + tok);
    init.headers = h;
  }
  return fetch(url, init);
}

/* секция комментариев: [начало заголовка, конец) или null */
function section(lines){
  var start = -1;
  for (var i = 0; i < lines.length; i++){
    var m = lines[i].match(RE_H2);
    if (!m) continue;
    if (start >= 0) return [start, i];
    if (m[1] === CFG.h2) start = i;
  }
  return start >= 0 ? [start, lines.length] : null;
}

function parseMd(text){
  var lines = text.split("\n"), comments = {}, sec = section(lines), m;
  if (sec) for (var i = sec[0] + 1; i < sec[1]; i++){
    if ((m = lines[i].match(RE_LINE))){ var k = key(m); if (!(k in comments)) comments[k] = m[3].trim(); }
  }
  return { lines: lines, comments: comments };
}

function applyEdits(){
  var lines = state.lines.slice(), sec = section(lines), done = {}, m, k;
  if (sec){
    for (var i = sec[0] + 1; i < sec[1]; i++){
      if (!(m = lines[i].match(RE_LINE))) continue;
      k = key(m);
      if ((k in edits) && !(k in done)){ lines[i] = m[1].replace(/[ \t]*$/, "") + (edits[k] ? " " + edits[k] : ""); done[k] = 1; }
    }
  }
  var add = [];
  Object.keys(edits).forEach(function(k){ if (!(k in done) && edits[k]) add.push(lineFor(k, edits[k])); });
  if (!add.length) return lines.join("\n");
  if (sec){
    /* дописать в конец секции, перед хвостовыми пустыми строками */
    var at = sec[1];
    while (at > sec[0] + 1 && !lines[at - 1].trim()) at--;
    var ins = add.slice();
    if (at === sec[0] + 1) ins.unshift("");
    Array.prototype.splice.apply(lines, [at, 0].concat(ins));
  } else {
    var block = ["## " + CFG.h2, ""].concat(add).concat([""]);
    var pos = -1;
    for (var j = 0; j < lines.length; j++){
      var hm = lines[j].match(RE_H2);
      if (hm && hm[1] === CFG.decisionH2){ pos = j; break; }
    }
    if (pos < 0){
      while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
      lines = lines.concat([""]).concat(block);
    } else {
      /* перед `## Решение` и его возможным разделителем `---` */
      var p = pos;
      while (p > 0 && (!lines[p - 1].trim() || /^-{3,}\s*$/.test(lines[p - 1]))) p--;
      Array.prototype.splice.apply(lines, [p, 0].concat([""]).concat(block.slice(0, -1)));
    }
  }
  return lines.join("\n");
}

var bar, barStatus, barBtn;
function updateBar(msg){
  var n = Object.keys(edits).length;
  try { window.__travelUnsavedEdits = (n > 0); } catch(e){}
  bar.hidden = (n === 0 && !msg);
  barBtn.disabled = (n === 0);
  barStatus.textContent = msg || (n ? n + " несохранённых правок" : "");
}

function enhance(){
  Array.prototype.forEach.call(document.querySelectorAll(".var-comment[data-var-comment]"), function(el){
    var k = el.getAttribute("data-var-comment");
    var st = el.querySelector(".vc-static");
    if (st) st.style.display = "none";
    var wrap = document.createElement("div");
    wrap.className = "var-edit edit-ui";
    var lbl = document.createElement("span");
    lbl.className = "fill-label";
    lbl.textContent = el.getAttribute("data-label") + ":";
    var ta = document.createElement("textarea");
    ta.rows = 2; ta.value = state.comments[k] || "";
    ta.addEventListener("input", function(){
      var cur = ta.value.replace(/\s*\n\s*/g, " ").trim();
      if (cur === (state.comments[k] || "")) delete edits[k]; else edits[k] = cur;
      updateBar();
    });
    wrap.appendChild(lbl); wrap.appendChild(ta); el.appendChild(wrap);
  });

  bar = document.createElement("div");
  bar.className = "edit-bar edit-ui"; bar.hidden = true;
  barStatus = document.createElement("span"); barStatus.className = "edit-status";
  barBtn = document.createElement("button");
  barBtn.textContent = "Сохранить";
  barBtn.addEventListener("click", save);
  bar.appendChild(barStatus); bar.appendChild(barBtn);
  document.body.appendChild(bar);
  window.addEventListener("beforeunload", function(e){
    if (window.__travelUnsavedEdits){ e.preventDefault(); e.returnValue = ""; }
  });
}

function save(){
  barBtn.disabled = true;
  var newMd = applyEdits();
  apiFetch("/api/save", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: mdPath, content: newMd, base_hash: state.hash })
  }).then(function(r){
    if (r.status === 409){
      updateBar("файл изменился на диске — обнови страницу");
      barBtn.disabled = true;
      return null;
    }
    if (!r.ok) throw new Error("save " + r.status);
    return r.json();
  }).then(function(res){
    if (!res) return;
    var parsed = parseMd(newMd);
    state = { hash: res.hash, lines: parsed.lines, comments: parsed.comments };
    edits = {};
    var t = new Date();
    updateBar("сохранено " +
      ("0" + t.getHours()).slice(-2) + ":" + ("0" + t.getMinutes()).slice(-2));
  }).catch(function(e){
    updateBar("ошибка сохранения");
    barBtn.disabled = false;
    if (window.console) console.log("stage4 edit:", e);
  });
}

function notice(msg){
  var b = document.createElement("div");
  b.className = "edit-bar edit-ui";
  b.title = mdPath;
  var s = document.createElement("span");
  s.className = "edit-status";
  s.textContent = msg;
  b.appendChild(s);
  b.addEventListener("click", function(){ b.remove(); });
  document.body.appendChild(b);
}

apiFetch("/api/health").then(function(r){ return r.ok ? r.json() : null; })
.then(function(h){
  if (!h || !h.ok || !h.writable) return null;
  return apiFetch("/api/file?path=" + encodeURIComponent(mdPath)).then(function(r){
    if (!r.ok){
      notice(r.status === 404
        ? "правка недоступна: рядом со страницей нет «" + CFG.mdFile + "»"
        : r.status === 403
          ? "правка недоступна: «" + CFG.mdFile + "» вне whitelist write-API"
          : "правка недоступна: «" + CFG.mdFile + "» → " + r.status);
      return null;
    }
    return r.json();
  });
}).then(function(f){
  if (!f) return;
  var parsed = parseMd(f.content);
  state = { hash: f.hash, lines: parsed.lines, comments: parsed.comments };
  enhance();
}).catch(function(){ /* нет API → обычная витрина */ });
})();
"""

# Ключ общего комментария в JS (буквы вариантов — одна заглавная буква).
_GENERAL_KEY = "*"


def _edit_layer(source_md_name: str) -> str:
    """Конфиг+стили+скрипт edit-слоя комментариев. Регэксп строки — из
    Python-парсера (`stages.stage4._COMMENT_LINE_RE`), в JS уезжает строкой."""
    cfg = {
        "mdFile": source_md_name,
        "reLine": s4._COMMENT_LINE_RE.pattern,
        "h2": s4._COMMENTS_H2,
        "decisionH2": s4._DECISION_H2,
        "general": _GENERAL_KEY,
        "generalLabel": s4._GENERAL_COMMENT_LABEL,
    }
    cfg_json = json.dumps(cfg, ensure_ascii=False).replace("<", "\\u003c")
    return (f'<script type="application/json" id="s4-edit-config">{cfg_json}</script>'
            f"<style>{_EDIT_CSS}</style><script>{_EDIT_JS}</script>")


def build_html(extracted: dict, output_path: str | Path, *,
               recipient: str = "self", embed_fonts: bool = True,
               source_md_name: str | None = None) -> str:
    cover = extracted["cover"]
    variants = extracted.get("variants") or []
    recommended = _norm_letter(cover.get("recommended_balanced"))
    country = s5._human_cover_title(cover)

    parts = ['<div class="page"><div class="guide">']
    parts.append('<div class="cover-kicker">Сравнение вариантов маршрута</div>')
    parts.append(f'<h1 class="cover-title">{esc(country)}</h1>')
    parts.append('<p class="cover-sub">Три варианта маршрута — сравнение по осям, '
                 'жертвы и развилки. Финальный выбор фиксируется пользователем.</p>')

    # Паспорт поездки.
    rows = _cover_rows(extracted)
    if rows:
        parts.append(_passport(rows))

    # Контекст (без дублирующих cover-таблицу **Key:**-пунктов).
    if extracted.get("context"):
        parts.append('<div class="box box--info"><span class="box-mark"></span>'
                     f'<div>{mdb(ru(s4._strip_dup_context(extracted["context"])))}</div></div>')

    # Предупреждения.
    if extracted.get("warnings"):
        items = "".join(f'<div class="note-item"><div>{md(str(w))}</div></div>'
                        for w in extracted["warnings"])
        parts.append('<div class="box box--warn"><span class="box-mark"></span>'
                     f'<div><div class="notelist">{items}</div></div></div>')

    # opt-grid карточек вариантов.
    if variants:
        parts.append('<div class="opt-grid">'
                     + "".join(_card(v, recommended) for v in variants) + "</div>")

    # сравнительная матрица.
    if extracted.get("comparison_rows"):
        parts.append(html_lib.plate("Сравнение по осям", sub=True))
        parts.append(_matrix(extracted["comparison_rows"], recommended))

    # приоритеты POI (свёрнуто).
    if extracted.get("priority_buckets"):
        parts.append(html_lib.plate("Приоритеты POI", sub=True))
        parts.append(_priority_html(extracted["priority_buckets"]))

    # полный per-variant detail — P0-1: одна filled-плашка стадии, варианты внутри — sub.
    if variants:
        parts.append(html_lib.plate("Детальный разбор вариантов"))
    for v in variants:
        parts.append(html_lib.plate(f"Вариант {v.letter} — {ru(v.title)}", sub=True))
        if v.intro:
            parts.append(mdb(ru(v.intro)))
        # Подсекции варианта (Маршрут по дням / Что включает / логистика / риски /
        # кому подходит) — иначе тело варианта теряется.
        for ss in getattr(v, "subsections", None) or []:
            parts.append(html_lib.anno(ru(ss["heading"])))
            parts.append(mdb(ru(ss["body"])))
        # Комментарий к варианту (заполняет пользователь; edit-слой — поле ввода).
        parts.append(_comment_slot(s4._comment_key(v.letter), "Комментарий к варианту",
                                   getattr(v, "user_comment", "") or ""))

    # extras: CONTESTED / что не вошло.
    for e in extracted.get("extras") or []:
        h = e.get("heading", "")
        parts.append(html_lib.plate(ru(h), sub=True))
        if "не вошл" in h.lower() or "sacrific" in h.lower():
            parts.append(_cut(ru(e.get("body", ""))))
        else:
            parts.append(mdb(ru(e.get("body", ""))))

    # honest.
    if extracted.get("honest"):
        parts.append(html_lib.plate("Честная оценка", sub=True))
        parts.append('<div class="box box--info"><span class="box-mark"></span>'
                     f'<div>{mdb(ru(extracted["honest"]))}</div></div>')

    # Общий комментарий ко всем вариантам.
    parts.append(_comment_slot(_GENERAL_KEY, s4._GENERAL_COMMENT_LABEL,
                               extracted.get("general_comment") or ""))

    parts.append("</div></div>")
    if source_md_name:
        parts.append(_edit_layer(source_md_name))
    doc = html_lib.build_html_document("".join(parts), title=f"{country} — варианты маршрута",
                                       embed_fonts=embed_fonts)
    Path(output_path).write_text(doc, encoding="utf-8")
    return doc
