"""Stage 3 → HTML (POI-агрегация, дизайн-система Claude Design).

`stages.stage3.extract_content` → dict. Presentation на CSS Design:
.region-bar + .region-tag (заполняемый тег) + .poi (счётчики/выдержки .poi-q/
характеристики/флаги). Сводная таблица распределения категорий.
"""
from __future__ import annotations

import json
from pathlib import Path

try:
    from export import html_lib, docx_lib
    from export.stages import stage5 as s5, stage3 as s3
except ImportError:  # запуск из каталога export/
    import html_lib  # type: ignore
    import docx_lib  # type: ignore
    from stages import stage5 as s5, stage3 as s3  # type: ignore

try:  # SSOT ярлыков (flag_badge) — scripts/taxonomy.py
    import taxonomy as tx
except ModuleNotFoundError:  # pragma: no cover
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    import taxonomy as tx  # type: ignore

md = html_lib.md_inline
mdb = html_lib.md_block
esc = html_lib.esc
plate = html_lib.plate
ru = html_lib.ru_anglicisms  # русификация видимых англицизмов прозы (как в Stage 2)

# Контракт полноты: ключи extract_content, учтённые build_html (aggregation_mode
# и служебные скрыты сознательно, Р7; who_goes — резолвер «Кто едет», Р10,
# в HTML-обложке Stage 3 паспорт не выводится вовсе — RL-эталон). Новый ключ
# без учёта → красный drift-тест.
CONSUMED_KEYS = frozenset({
    "trip_id", "stage", "title", "travelers_profile", "total_pois", "who_goes",
    "aggregation_mode", "created", "distribution", "warnings",
    "context_lines", "regions", "non_mainstream", "validation_errors",
})


def _images_link(poi, region_english: str | None, trip_countries: list) -> str:
    """Ссылка на Google Images по POI (паритет с DOCX-экспортом)."""
    q = s3._poi_search_query(
        getattr(poi, "name_local", "") or "", region_english,
        trip_countries or [], name_ru=getattr(poi, "name_ru", None))
    if not (q or "").strip():
        return ""
    url = docx_lib.google_images_url(q)
    return (f'<a class="lnk poi-images" href="{esc(url)}">Картинки Google ↗</a>')

_CAT_SIG = {"STRONG CONFIRMED": "strong", "WEAK CONFIRMED": "weak",
            "HIDDEN GEM": "gem", "CONTESTED": "gem", "RED FLAG": "red",
            "LOW SIGNAL": "low"}


def _sig(cat: str) -> str:
    # CSS-класс по ключу; ярлык — RU badge через taxonomy (HIDDEN GEM → ЖЕМЧУЖИНА).
    cls = _CAT_SIG.get((cat or "").upper(), "low")
    return f'<span class="sig sig--{cls}">{esc(s3._pc_badge(cat) if cat else "")}</span>'


# Тон выдержки (эвристика Excerpt.tone) → цветная левая рамка цитаты.
_TONE_STYLE = {
    "pos": ' style="border-left:2px solid var(--ok,#1a7f37);padding-left:6px"',
    "neg": ' style="border-left:2px solid var(--danger,#b91c1c);padding-left:6px"',
}


def _excerpt(e) -> str:
    """Одна выдержка: автор · год · similarity + название отчёта + ссылка + текст."""
    src_bits = [esc(e.author_name)]
    if getattr(e, "year", None):
        src_bits.append(esc(str(e.year)))
    if getattr(e, "similarity", None):
        src_bits.append(esc(e.similarity.lower()))
    src = " · ".join(src_bits)
    # Название отчёта намеренно НЕ выводим: на карточке POI это нагромождение
    # букв (длинный caps-заголовок), атрибуции хватает «автор · год · similarity»
    # + ссылка на сам отчёт.
    if getattr(e, "url", None):
        src += f' <a class="lnk lnk--mono" href="{esc(e.url)}">↗</a>'
    tone_style = _TONE_STYLE.get(getattr(e, "tone", "neu"), "")
    return (f'<div class="poi-q"{tone_style}><span class="src">{src}</span>'
            f'<span>{md(e.text)}</span></div>')


def _poi(p, images: str = "") -> str:
    name = esc(p.name_ru)
    if p.name_local:
        name += f' <span class="muted">({esc(p.name_local)})</span>'
    head = (f'<div class="poi-head"><span class="poi-num">#{p.num}</span>'
            f'<span class="poi-name">{name}</span>{_sig(p.category)}</div>')
    # Полная строка счётчиков (RU-ярлыки + разбивка HIGH рек./нейтр./крит.).
    counts = f'<div class="poi-counts">{esc(s3._counts_line(p))}</div>'
    quotes = ""
    if getattr(p, "excerpts", None):
        qs = "".join(_excerpt(e) for e in p.excerpts)  # без cap — все выдержки
        quotes = f'<div class="poi-quotes">{qs}</div>'
    char = (f'<div class="poi-char">{md(p.characteristics)}</div>'
            if getattr(p, "characteristics", None) else "")
    flags = []
    if getattr(p, "user_comment", None) and p.user_comment.strip():
        # .poi-comment — хук edit-слоя: при живом write-API статичный текст
        # скрывается, вместо него textarea с актуальным значением из md.
        flags.append(f'<div class="poi-cluster poi-comment">комментарий: {md(p.user_comment)}</div>')
    if getattr(p, "combined_with", None):
        names = ", ".join(esc(c.get("poi_name", "")) for c in p.combined_with
                          if isinstance(c, dict))
        if names:
            flags.append(f'<div class="poi-cluster">'
                         f'{esc(tx.label("flag_badge", "combined_with"))}: {names}</div>')
    if getattr(p, "cluster_name", None):
        flags.append(f'<div class="poi-cluster">'
                     f'{esc(tx.label("flag_badge", "cluster"))}: {esc(p.cluster_name)}</div>')
    if getattr(p, "trap_archetype", None):
        _t = p.trap_archetype
        _txt = _t.get("archetype", "") if isinstance(_t, dict) else (_t or "")
        if _txt:
            flags.append('<div class="poi-cluster" style="color:var(--danger)">'
                         f'{esc(tx.label("flag_badge", "trap"))}: {esc(_txt)}</div>')
    if getattr(p, "iconic_status", None):
        flags.append(f'<div class="poi-cluster">'
                     f'{esc(tx.label("flag_badge", "iconic_status"))}: {esc(p.iconic_status)}</div>')
    img = f'<div class="poi-links">{images}</div>' if images else ""
    # data-poi — якорь edit-слоя (номер POI глобален и стабилен в md).
    return (f'<div class="poi" data-poi="{p.num}">'
            f'{head}{counts}{quotes}{char}{"".join(flags)}{img}</div>')


def _region(r, trip_countries: list | None = None) -> str:
    region_english = (getattr(r, "english_name", None)
                      or s3._REGION_RU_TO_EN_FALLBACK.get(r.name))
    # Режим агрегации (region.mode) сознательно скрыт — служебная мета (Р7).
    out = [f'<div class="region-bar"><span class="rname">{esc(r.name)} — {r.poi_count} POI</span></div>']
    # Тег региона — anketa-чекбоксы с pre-select заполненного (round-trip).
    # data-region/data-tag — якоря edit-слоя: при живом write-API опции
    # становятся кликабельными, выбор пишется в `**тег:**` заголовка md.
    tag_sel = s3._normalize_tag(getattr(r, "tag", None))
    boxes = " ".join(
        f'<span class="tagopt" data-tag="{esc(o)}">{"☑" if o == tag_sel else "☐"} {esc(o)}</span>'
        for o in s3._CANONICAL_TAGS)
    out.append(f'<div class="region-tag" data-region="{esc(r.name)}">'
               '<span class="fill-label">Тег региона:</span> '
               f'<span class="muted">{boxes}</span></div>')
    # Описание: polished (или fallback, но не placeholder «недоступно»).
    desc = getattr(r, "polished_description", None) or getattr(r, "description", None)
    if desc and "недоступно" not in desc.lower():
        out.append(f'<p class="muted">{md(desc, todo=False)}</p>')
    # Сводка «Кто писал про регион» (polished-маркер).
    if getattr(r, "polished_authors_summary", None):
        out.append(f'<p><b>Кто писал про регион:</b> '
                   f'{md(r.polished_authors_summary, todo=False)}</p>')
    # Комментарий к региону (что ещё хочется посмотреть). Якорь data-region-comment
    # выводится всегда — edit-слой ставит сюда поле ввода, даже если строки в md
    # ещё нет (создаст её под заголовком региона); статичный текст — только
    # когда комментарий заполнен.
    rc = (getattr(r, "user_comment", None) or "").strip()
    rc_static = (f'<span class="rc-static"><span class="fill-label">Комментарий к региону:</span> '
                 f'{md(rc, todo=False)}</span>') if rc else ""
    out.append(f'<div class="region-comment" data-region-comment="{esc(r.name)}">'
               f'{rc_static}</div>')
    for cl in getattr(r, "clusters", None) or []:
        def _g(key, *alts):
            if isinstance(cl, dict):
                return cl.get(key)
            for k in (key, *alts):
                v = getattr(cl, k, None)
                if v is not None:
                    return v
            return None
        name = _g("name", "title") or "Кластер"
        cnt = _g("member_count")
        cat = _g("aggregate_category", "category")
        note = _g("note", "description", "body") or ""
        label = f"{esc(str(name))}" + (f" ({cnt} POI)" if cnt else "")
        sig = f" {_sig(str(cat))}" if cat else ""
        out.append('<div class="box box--warn"><span class="box-mark"></span>'
                   f'<div><span class="box-label">Кластер · {label}{sig}</span>'
                   f'{md(str(note))}</div></div>')
    for p in r.pois:
        out.append(_poi(p, _images_link(p, region_english, trip_countries or [])))
    return "".join(out)


# ---------------------------------------------------------------------------
# Edit-слой (операционные правки прямо из HTML: тег региона + комментарий POI)
# ---------------------------------------------------------------------------
# Активируется ТОЛЬКО если хостинг артефакта предоставляет generic write-API
# (GET /api/health · GET /api/file?path= · POST /api/save {path, content,
# base_hash}); иначе страница остаётся обычной статичной витриной (file://,
# чужой хостинг, PDF-прогон). Пути резолвятся от URL самой страницы: md-источник
# лежит рядом с экспортом (канон trips/{trip_id}/). Правки применяются к md
# КЛИЕНТСКИ — построчная хирургия зеркалит `stages.stage3.import_docx`
# (DOCX round-trip), причём регэкспы не дублируются, а передаются в JS из тех
# же Python-паттернов (_REGION_HEADER_RE и др.) — дрейф исключён конструктивно.
# Семантика: тег региона — только выставить/сменить (снять нельзя, паритет
# с DOCX); комментарий POI — правится/чистится, только существующая строка
# `6. Комментарий пользователя:` (однострочный v1, как в import_docx);
# комментарий к региону — `**Комментарий к региону:**` в шапке региона:
# существующая строка правится, отсутствующая создаётся сразу под заголовком.

_EDIT_CSS = (
    ".edit-ui .tagopt{cursor:pointer;user-select:none;}"
    ".edit-ui .tagopt:hover{color:var(--accent);}"
    ".edit-ui .tagopt.sel{color:var(--accent);font-weight:600;}"
    ".poi-edit{display:flex;gap:10px;align-items:flex-start;margin-top:6px;}"
    ".poi-edit .fill-label{padding-top:7px;}"
    ".region-comment:empty{display:none;}"
    ".region-comment{margin:6px 0 10px;}"
    ".poi-edit textarea{flex:1;font:inherit;font-size:var(--fs-small,12px);"
    "background:var(--paper);color:inherit;border:1px solid var(--line);"
    "border-radius:6px;padding:6px 8px;min-height:2.4em;resize:vertical;}"
    # bottom считает высоту навигационной панели (--tnav-bottom ставит
    # nav-layer.js на телефоне): иначе «Сохранить» оказывается под ней.
    ".edit-bar{position:fixed;right:18px;bottom:calc(18px + var(--tnav-bottom,0px));"
    "z-index:50;display:flex;"
    # color: панель живёт вне .guide и наследует цвет body (чёрный) —
    # в тёмной теме статус «сохранено» был чёрным по тёмному фону.
    "gap:12px;align-items:center;background:var(--paper);color:var(--ink);"
    "font-family:var(--font-body);"
    "border:1px solid var(--line);"
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
var CFG = JSON.parse(document.getElementById("s3-edit-config").textContent);
var RE_REGION = new RegExp(CFG.reRegion), RE_POI = new RegExp(CFG.rePoi),
    RE_COMMENT = new RegExp(CFG.reComment), RE_TAG = new RegExp(CFG.reTag),
    RE_RCOMMENT = new RegExp(CFG.reRegionComment), RE_CLUSTER = new RegExp(CFG.reCluster);
function nfc(s){ return (s && s.normalize) ? s.normalize("NFC") : (s || ""); }
/* md-источник — сосед страницы; путь для API — от корня хостинга, байты как в URL */
var mdPath = decodeURIComponent(new URL(".", location.href).pathname)
             .replace(/^\/+/, "") + CFG.mdFile;
var state = null; /* {hash, lines, regions:{имя→тег|null}, comments:{num→строка},
                     rcomments:{имя→строка} — только регионы, где строка уже есть} */
var tagEdits = {}, commentEdits = {}, rcommentEdits = {};

/* Если хостинг кладёт basic-auth токен в localStorage["hub-auth"] (единый ключ
   origin'а), прикладываем его — тогда запись работает и с адреса, который сам по
   себе к write-API не допущен. Нет токена и адрес не доверенный → фоновый fetch
   к /api получает тихий 403, слой остаётся статичной витриной.
   credentials:"omit" обязателен: гасит нативный диалог пароля на 401-челлендж. */
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

function parseMd(text){
  var lines = text.split("\n"), cur = null, reg = null, regions = {}, comments = {},
      rcomments = {}, m;
  for (var i = 0; i < lines.length; i++){
    var ln = lines[i];
    if ((m = ln.match(RE_REGION))){ reg = nfc(m[1].trim()); regions[reg] = (m[3] || "").trim() || null; cur = null; continue; }
    if ((m = ln.match(RE_POI))){ cur = parseInt(m[1], 10); reg = null; continue; }
    if (RE_CLUSTER.test(ln)){ reg = null; continue; }
    /* шапка региона (до первого POI/кластера) — там живёт комментарий к региону */
    if (reg !== null && (m = ln.match(RE_RCOMMENT)) && !(reg in rcomments)){ rcomments[reg] = m[2].trim(); continue; }
    if (cur !== null && (m = ln.match(RE_COMMENT)) && !(cur in comments)) comments[cur] = m[2].trim();
  }
  return { lines: lines, regions: regions, comments: comments, rcomments: rcomments };
}
function rcommentLine(prefix, txt){ return prefix.replace(/[ \t]*$/, "") + (txt ? " " + txt : ""); }

/* зеркало import_docx: построчно, регион сбрасывает текущий POI */
function applyEdits(){
  var out = [], cur = null, reg = null, m;
  for (var i = 0; i < state.lines.length; i++){
    var ln = state.lines[i];
    if ((m = ln.match(RE_REGION))){
      var name = nfc(m[1].trim());
      if (name in tagEdits){
        var t = tagEdits[name];
        if (ln.indexOf("**тег:**") >= 0) ln = ln.replace(RE_TAG, function(_, p1){ return p1 + t; });
        else ln = ln.replace(/\s*$/, "") + " · **тег:** " + t;
      }
      out.push(ln); cur = null; reg = name;
      /* строки комментария к региону ещё нет → создаём сразу под заголовком */
      if ((name in rcommentEdits) && !(name in state.rcomments) && rcommentEdits[name]){
        out.push(""); out.push("**Комментарий к региону:** " + rcommentEdits[name]);
      }
      continue;
    }
    if ((m = ln.match(RE_POI))){ cur = parseInt(m[1], 10); reg = null; out.push(ln); continue; }
    if (RE_CLUSTER.test(ln)){ reg = null; out.push(ln); continue; }
    if (reg !== null && (m = ln.match(RE_RCOMMENT))){
      if (reg in rcommentEdits) ln = rcommentLine(m[1], rcommentEdits[reg]);
      out.push(ln); reg = null; continue;
    }
    if (cur !== null && ln.match(RE_COMMENT) && (cur in commentEdits)){
      var indent = (ln.match(/^\s*/) || [""])[0], txt = commentEdits[cur];
      out.push(indent + "6. Комментарий пользователя:" + (txt ? " " + txt : ""));
      continue;
    }
    out.push(ln);
  }
  return out.join("\n");
}

var bar, barStatus, barBtn;
function updateBar(msg){
  var n = Object.keys(tagEdits).length + Object.keys(commentEdits).length
        + Object.keys(rcommentEdits).length;
  /* флаг для внешнего вьюера (травел-панель) — есть ли несохранённые правки:
     он спрашивает подтверждение при закрытии стадии крестиком */
  try { window.__travelUnsavedEdits = (n > 0); } catch(e){}
  bar.hidden = (n === 0 && !msg);
  barBtn.disabled = (n === 0);
  barStatus.textContent = msg || (n ? n + " несохранённых правок" : "");
}

function enhance(){
  Array.prototype.forEach.call(document.querySelectorAll(".region-tag[data-region]"), function(el){
    var name = nfc(el.getAttribute("data-region"));
    if (!(name in state.regions)) return; /* экспорт разошёлся с md — оставляем статику */
    el.classList.add("edit-ui");
    var opts = el.querySelectorAll(".tagopt");
    function paint(sel){
      Array.prototype.forEach.call(opts, function(o){
        var on = (o.getAttribute("data-tag") === sel);
        o.classList.toggle("sel", on);
        o.textContent = (on ? "☑" : "☐") + " " + o.getAttribute("data-tag");
      });
    }
    paint(state.regions[name]);
    Array.prototype.forEach.call(opts, function(o){
      o.addEventListener("click", function(){
        var t = o.getAttribute("data-tag");
        if (t === state.regions[name]) delete tagEdits[name]; else tagEdits[name] = t;
        paint(t); updateBar();
      });
    });
  });
  Array.prototype.forEach.call(document.querySelectorAll(".region-comment[data-region-comment]"), function(el){
    var name = nfc(el.getAttribute("data-region-comment"));
    if (!(name in state.regions)) return; /* экспорт разошёлся с md — статика */
    var st = el.querySelector(".rc-static");
    if (st) st.style.display = "none";
    var wrap = document.createElement("div");
    wrap.className = "poi-edit edit-ui";
    var lbl = document.createElement("span");
    lbl.className = "fill-label";
    lbl.textContent = "Комментарий к региону:";
    var ta = document.createElement("textarea");
    ta.rows = 1; ta.value = state.rcomments[name] || "";
    ta.placeholder = "что ещё хочется посмотреть в регионе";
    ta.addEventListener("input", function(){
      var cur = ta.value.replace(/\s*\n\s*/g, " ").trim();
      /* база читается живьём: после сохранения state перечитан из нового md */
      if (cur === (state.rcomments[name] || "")) delete rcommentEdits[name]; else rcommentEdits[name] = cur;
      updateBar();
    });
    wrap.appendChild(lbl); wrap.appendChild(ta); el.appendChild(wrap);
  });
  Array.prototype.forEach.call(document.querySelectorAll(".poi[data-poi]"), function(el){
    var num = parseInt(el.getAttribute("data-poi"), 10);
    if (!(num in state.comments)) return; /* нет строки поля 6 в md — не редактируем */
    var st = el.querySelector(".poi-comment");
    if (st) st.style.display = "none";
    var wrap = document.createElement("div");
    wrap.className = "poi-edit edit-ui";
    var lbl = document.createElement("span");
    lbl.className = "fill-label";
    lbl.textContent = "Комментарий:";
    var ta = document.createElement("textarea");
    ta.rows = 1; ta.value = state.comments[num];
    ta.addEventListener("input", function(){
      var cur = ta.value.replace(/\s*\n\s*/g, " ").trim();
      if (cur === state.comments[num]) delete commentEdits[num]; else commentEdits[num] = cur;
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

  /* прямое открытие страницы (не во вьюере): закрытие вкладки/навигация с
     несохранёнными правками → штатное предупреждение браузера. Во вьюере
     закрытие крестиком перехватывает сам вьюер по флагу __travelUnsavedEdits. */
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
    state = { hash: res.hash, lines: parsed.lines, regions: parsed.regions,
              comments: parsed.comments, rcomments: parsed.rcomments };
    tagEdits = {}; commentEdits = {}; rcommentEdits = {};
    var t = new Date();
    updateBar("сохранено " +
      ("0" + t.getHours()).slice(-2) + ":" + ("0" + t.getMinutes()).slice(-2));
  }).catch(function(e){
    updateBar("ошибка сохранения");
    barBtn.disabled = false;
    if (window.console) console.log("stage3 edit:", e);
  });
}

/* Диагностика вместо молчания. Гостю (write-API не ответил или не пишет) слой
   молчит по дизайну — статичная витрина. Но если API доступен, а файл не отдался,
   причина операционная (страница просит НЕ ТОТ md: имя черновика polished_*,
   переименованный/перенесённый источник) — и молчание неотличимо от read-only,
   диагноз занимает часы. Показываем причину строкой в углу. */
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
  state = { hash: f.hash, lines: parsed.lines, regions: parsed.regions,
            comments: parsed.comments, rcomments: parsed.rcomments };
  enhance();
}).catch(function(){ /* нет API → обычная витрина */ });
})();
"""


def _edit_layer(source_md_name: str) -> str:
    """Конфиг+стили+скрипт edit-слоя. Регэкспы — из Python-паттернов парсера
    (single source of truth), в JS уезжают строками через JSON."""
    cfg = {
        "mdFile": source_md_name,
        "reRegion": s3._REGION_HEADER_RE.pattern,
        "rePoi": s3._POI_HEADER_RE.pattern,
        "reComment": s3._MD_COMMENT_LINE_RE.pattern,
        "reTag": s3._MD_TAG_IN_HEADER_RE.pattern,
        "reRegionComment": s3._REGION_COMMENT_RE.pattern,
        "reCluster": s3._CLUSTER_HEADER_RE.pattern,
        "tags": list(s3._CANONICAL_TAGS),
    }
    cfg_json = json.dumps(cfg, ensure_ascii=False).replace("<", "\\u003c")
    return (f'<script type="application/json" id="s3-edit-config">{cfg_json}</script>'
            f"<style>{_EDIT_CSS}</style><script>{_EDIT_JS}</script>")


def build_html(extracted: dict, output_path: str | Path, *,
               recipient: str = "self", embed_fonts: bool = True,
               source_md_name: str | None = None) -> str:
    ex = extracted
    country = s5._human_cover_title({"trip_id": ex.get("trip_id", "")})

    parts = ['<div class="page"><div class="guide">']
    parts.append('<div class="cover-kicker">Агрегация POI · Deep Research</div>')
    parts.append(f'<h1 class="cover-title">{esc(country)}</h1>')
    # Режим агрегации (aggregation_mode) скрыт — служебная мета (Р7).
    parts.append(f'<p class="cover-sub">Агрегировано {esc(str(ex.get("total_pois", "?")))} POI</p>')

    # Контекст агрегации (context_lines).
    ctx = ex.get("context_lines") or []
    if ctx:
        items = "".join(f'<div class="note-item"><div>{md(ru(str(c)))}</div></div>' for c in ctx)
        parts.append(f'<div class="lead"><div class="notelist">{items}</div></div>')

    # Предупреждения агрегации (проза модели → русификатор, как в Stage 2).
    warns = ex.get("warnings") or []
    if warns:
        items = "".join(f'<div class="note-item"><div>{md(ru(str(w)))}</div></div>' for w in warns)
        parts.append('<div class="box box--warn"><span class="box-mark"></span>'
                     f'<div><div class="notelist">{items}</div></div></div>')

    # Таблица «Категория/POI» убрана (Р11) — таблица «Покрытие по регионам»
    # ниже несёт те же числа (строка ВСЕГО), дублировать не нужно.

    # Покрытие по регионам (категории POI × регионы + строка ВСЕГО).
    cov_rows, tots = s3._coverage_rows(ex)
    if cov_rows:
        parts.append(plate("Покрытие по регионам", sub=True))
        headers = (["Регион", "POI"]
                   + [s3.taxonomy.label("poi_category_badge", k) for k in s3._POI_CAT_ORDER])
        head = "".join(f"<th>{esc(h)}</th>" for h in headers)
        crows = []
        for region, t, s, w, h, c, r, low in cov_rows:
            cells = [region, str(t)] + [str(x) if x else "·" for x in (s, w, h, c, r, low)]
            crows.append("<tr>" + "".join(f"<td>{esc(str(x))}</td>" for x in cells) + "</tr>")
        total_cells = ["ВСЕГО"] + [str(x) for x in tots]
        crows.append("<tr><td><b>ВСЕГО</b></td>"
                     + "".join(f"<td>{esc(str(x))}</td>" for x in total_cells[1:]) + "</tr>")
        parts.append('<table class="data-table data-table--compact data-table--zebra">'
                     f'<thead><tr>{head}</tr></thead><tbody>{"".join(crows)}</tbody></table>')

    # P0-1: единственная filled-плашка стадии. P0-2: заголовки регионов —
    # только .region-bar (внутри _region), дублирующую .section-plate убрали.
    parts.append(html_lib.plate("Агрегация POI"))
    trip_countries = s3._trip_countries_en(ex.get("trip_id"))
    for r in ex.get("regions") or []:
        parts.append(_region(r, trip_countries))

    if ex.get("non_mainstream"):
        parts.append(html_lib.plate("Находки вне турпотока", sub=True))
        parts.append(mdb(str(ex["non_mainstream"])))

    # Легенда RU=EN (Р2): категории POI + сходства авторов.
    parts.append(html_lib.legend_line(
        s3.taxonomy.legend("poi_category", "author_category"),
        prefix="Категории (RU = EN)"))

    parts.append("</div></div>")
    if source_md_name:
        parts.append(_edit_layer(source_md_name))
    doc = html_lib.build_html_document(
        "".join(parts), title=f"{country} — POI", embed_fonts=embed_fonts)
    Path(output_path).write_text(doc, encoding="utf-8")
    return doc
