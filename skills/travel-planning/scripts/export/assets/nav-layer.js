/* ═══════════════════════════════════════════════════════════════════════════
   TNAV — навигационный слой путеводителя (стадии 0–6).

   Источник: Claude Design, проект 553ebbf1-cf71-453d-9d71-39b0427aee77,
   файл `nav-layer.snippet.txt`. Меню строится ИЗ САМОГО ДОКУМЕНТА (плашки
   разделов, дни, POI, карточки) — генератор экспорта разметку под меню не
   готовит, поэтому рассинхрон невозможен по построению.

   Правки поверх макета (мобильный аудит 2026-08):
   · слушатели window/document вешаются ОДИН раз: `boot()` пересобирает меню
     после `load` (стадия 2 дорисовывает карточки своим скриптом), и в макете
     второй init удваивал scroll/keydown, а старая копия держала удалённый DOM;
   · scroll-lock страницы на время открытой шторки;
   · ключ сохранения отметок берётся из `body[data-tnav-key]` (trip_id) —
     у 5_план и 6_финал разные <title>, а чеклист один и тот же, и на хеше
     заголовка галочки не переносились между ними;
   · панель прячется при прокрутке вниз, возвращается при прокрутке вверх;
   · высота панели отдаётся в `--tnav-bottom` (под неё сдвигается плавающая
     кнопка «Сохранить» edit-слоя Stage 3).

   Правки 2026-10 (кабинет открывает стадию окном по центру, рельс влезает):
   · кнопки темы нет — тема берётся из кабинета (`hub-theme`, html_lib), а
     переключатель внутри iframe менял только сам документ, не страницу вокруг;
   · в рельсе — строка статуса поездки («До старта · N дн» / «Идёт · день X
     из Y»), раньше она жила только в нижней панели;
   · у «Заранее» в рельсе — счётчик несохранённых отметок; отметка пишется в
     план сама через 2 с (автосохранение), ручная кнопка «Сохранить в план» —
     в шторке «Заранее»;
   · переход по меню: подсветка сразу на цели, без пробега по промежуточным
     главам; дальний переход — мгновенный;
   · «↑ В начало» — сразу под списком глав (как в читателе кабинета), подвала
     у рельса больше нет.
   ══════════════════════════════════════════════════════════════════════════ */
(function () {
"use strict";
if (window.__tnav) return;
window.__tnav = 1;

var D = document, W = window, CURRENT = null, API = null;

function $(s, c) { return (c || D).querySelector(s); }
function $$(s, c) { return Array.prototype.slice.call((c || D).querySelectorAll(s)); }
function el(t, cls, txt) { var e = D.createElement(t); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; }
function tx(n) { return ((n && n.textContent) || "").replace(/\s+/g, " ").trim(); }
var LS = {
  g: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  s: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
};
function hash(s) { var h = 5381, i = s.length; while (i) h = (h * 33 ^ s.charCodeAt(--i)) >>> 0; return h.toString(36); }

var I = {
  list: '<path d="M3 5h14M3 10h14M3 15h10"/>',
  up: '<path d="M10 16V5M5 10l5-5 5 5"/>',
  today: '<rect x="3" y="4.5" width="14" height="13" rx="1.5"/><path d="M3 8.5h14M7 3v3M13 3v3"/><circle cx="10" cy="13" r="1.6" fill="currentColor" stroke="none"/>',
  clock: '<circle cx="10" cy="10" r="7"/><path d="M10 6v4.4l2.8 1.8"/>',
  close: '<path d="M5 5l10 10M15 5L5 15"/>',
  back: '<path d="M12 4l-6 6 6 6"/>',
  jump: '<path d="M6 12l8-8M8 4h6v6"/>',
  check: '<path d="M2 6.2l3 3.2L11 2.6"/>',
  chev: '<path d="M6 3l5 5-5 5"/>',
  pin: '<path d="M10 17s5.5-5.2 5.5-9A5.5 5.5 0 004.5 8c0 3.8 5.5 9 5.5 9z"/><circle cx="10" cy="8" r="2"/>'
};
function svg(p, cls) { return '<svg viewBox="0 0 20 20" aria-hidden="true"' + (cls ? ' class="' + cls + '"' : "") + ">" + p + "</svg>"; }

function init() {

  /* ── модель документа ────────────────────────────────────────────────── */
  var page = $(".page") || D.body;
  var guide = $(".guide", page) || page;
  /* Ключ хранения отметок: trip_id из data-атрибута (общий у 5_план и
     6_финал), иначе — хеш заголовка (для страниц, собранных без ключа). */
  var DOCKEY = "tnav:" + ((D.body.getAttribute("data-tnav-key") || "").trim() ||
    hash((D.title || "") + "|" + tx($(".cover-kicker", guide))));

  var SECSEL = ".section-plate, .section-plate--sub, .anno";
  var secNodes = $$(SECSEL, guide);
  var secFallback = false;
  if (!secNodes.length) { secNodes = $$("h2, h3", guide); secFallback = true; }
  var sections = secNodes.map(function (n, i) {
    if (!n.id) n.id = "tnav-s" + i;
    var lvl = secFallback ? (n.tagName === "H2" ? 1 : 2)
      : (n.classList.contains("anno") ? 3
        : (n.classList.contains("section-plate--sub") ? 2 : 1));
    return { id: n.id, el: n, lvl: lvl, label: tx(n) };
  }).filter(function (s) { return s.label; });

  function idify(nodes, pre) {
    nodes.forEach(function (n, i) { if (!n.id) n.id = pre + (i + 1); });
    return nodes;
  }
  var days = idify($$(".day", guide), "tnav-d");
  var pois = idify($$(".poi[data-poi]", guide), "tnav-p");
  var opts = idify($$(".opt-card", guide), "tnav-o");
  var cards = idify($$(".scard", guide), "tnav-c");

  var items = [];
  function collect(itemSel, headSel, labelFn, keyFn) {
    var seq = $$(itemSel + "," + headSel, guide), head = null;
    seq.forEach(function (n) {
      if (n.matches(headSel)) { head = tx(n).slice(0, 60); return; }
      items.push({ id: n.id, el: n, group: head, label: labelFn(n), key: keyFn ? keyFn(n) : "" });
    });
  }
  var KIND = "none";
  if (days.length) {
    KIND = "days";
    days.forEach(function (n) {
      items.push({
        id: n.id, el: n, group: null,
        label: tx($(".day-title", n) || n).slice(0, 80),
        key: tx($(".day-date", n)).replace(/^День\s*/i, "")
      });
    });
  } else if (pois.length) {
    KIND = "poi";
    collect(".poi[data-poi]", ".region-bar",
      function (n) { return tx($(".poi-name", n) || n).slice(0, 80); },
      function (n) { return "#" + n.getAttribute("data-poi"); });
  } else if (opts.length) {
    KIND = "opt";
    opts.forEach(function (n, i) {
      items.push({ id: n.id, el: n, group: null, label: tx($("h2,h3,.opt-title", n) || n).slice(0, 70), key: String.fromCharCode(65 + i) });
    });
  } else if (cards.length) {
    KIND = "card";
    collect(".scard", ".section-plate--sub",
      function (n) { return tx($(".scard-title", n) || n).slice(0, 80); },
      function (n) { return tx($(".sig", n)).slice(0, 4); });
  } else {
    var auth = $$('[id^="author-"]', guide);
    if (auth.length) {
      KIND = "authors";
      auth.forEach(function (n, i) {
        items.push({
          id: n.id, el: n, group: null,
          label: tx($(".scard-title, h2, h3, .name, .author, b, strong", n) || n).slice(0, 80),
          key: String(i + 1)
        });
      });
    }
  }

  var WORDS = [[/регион/i, "Регионы"], [/автор/i, "Авторы"], [/отч[её]т|deep research|\bdr\b/i, "Отчёты"],
               [/poi|мест/i, "Места"], [/вариант/i, "Варианты"], [/день|дням|маршрут по дн/i, "Дни"]];
  function kindWord() {
    if (KIND === "days") return "Дни";
    if (KIND === "poi") return "Места";
    if (KIND === "opt") return "Варианты";
    if (KIND === "authors") return "Авторы";
    var probes = [tx($(".section-plate:not(.section-plate--sub)", guide)),
                  tx($(".cover-kicker", guide)), D.title || ""];
    for (var p = 0; p < probes.length; p++)
      for (var i = 0; i < WORDS.length; i++) if (WORDS[i][0].test(probes[p])) return WORDS[i][1];
    return "Карточки";
  }

  /* ── даты поездки ────────────────────────────────────────────────────── */
  function iso(d) { return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2); }
  var dated = days.filter(function (n) { return /^\d{4}-\d{2}-\d{2}$/.test(n.getAttribute("data-date") || ""); });
  var TODAY = iso(new Date()), tripState = "none", todayEl = null, daysLeft = 0, dayNo = 0, dayTot = 0;
  if (dated.length) {
    var first = dated[0].getAttribute("data-date"), last = dated[dated.length - 1].getAttribute("data-date");
    if (TODAY < first) {
      tripState = "before";
      daysLeft = Math.round((Date.parse(first) - Date.parse(TODAY)) / 864e5);
    } else if (TODAY > last) { tripState = "after"; }
    else {
      tripState = "during";
      /* «день X из Y» — по календарю первого/последнего дня плана, как
         uiTripWhen кабинета считает по start/end trip.yaml */
      dayNo = Math.round((Date.parse(TODAY) - Date.parse(first)) / 864e5) + 1;
      dayTot = Math.round((Date.parse(last) - Date.parse(first)) / 864e5) + 1;
      todayEl = dated.filter(function (n) { return n.getAttribute("data-date") <= TODAY; }).pop() || dated[0];
    }
  }

  /* ── отметки: план (.md) — хранилище, браузер — буфер несохранённого ─────
     Состояние пункта живёт в строке плана (`- [x] …`), поэтому переживает
     пересборку экспорта и попадает в PDF. Клик копится локально и через 2 с
     уходит в файл сам (автосохранение); кнопка «Сохранить в план» в «Заранее»
     остаётся ручным путём (запись — под логином). */
  var PCFG = (function () {
    var el = D.getElementById("tnav-prep-config");
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  })();
  var canSave = !!(PCFG && W.fetch && W.URL && location.protocol !== "file:");

  function normKey(s) {
    var out = String(s == null ? "" : s);
    if (out.normalize) out = out.normalize("NFC");
    if (PCFG) PCFG.normRules.forEach(function (r) {
      out = out.replace(new RegExp(r[0], "g"), r[1]);
    });
    return out.replace(/ё/g, "е").replace(/Ё/g, "Е").trim().toLowerCase();
  }

  var PENDKEY = DOCKEY + ":pending", pend = {}, diag = null;
  try { pend = JSON.parse(LS.g(PENDKEY) || "{}") || {}; } catch (e) { pend = {}; }
  function savePend() { LS.s(PENDKEY, JSON.stringify(pend)); }
  function pendCount() { return Object.keys(pend).length; }
  /* Желаемое состояние: буфер важнее плана; в плане — то, что пришло в HTML. */
  function isDone(r) { return (r.key in pend) ? !!pend[r.key] : !!r.md; }
  function setDone(r, on) {
    if (on === !!r.md) delete pend[r.key]; else pend[r.key] = on;
    savePend();
  }

  /* ── «Заранее» ───────────────────────────────────────────────────────── */
  var PREP = /критическ|подготовит|за\s*2\s*недел|чеклист|брониров|todo|заранее|перед поездкой|перед вылетом/i;
  var HEADSEL = ".section-plate, .section-plate--sub, .anno";
  function nearestHead(node) {
    var n = node;
    while (n && n !== guide) {
      var p = n.previousElementSibling;
      while (p) { if (p.matches && p.matches(HEADSEL)) return p; p = p.previousElementSibling; }
      n = n.parentElement;
    }
    return null;
  }
  function keyOf(text) { return DOCKEY + ":p:" + hash(text); }
  var prepGroups = [];
  (function buildPrep() {
    if (!days.length) return;
    var map = {}, order = [];
    $$(".note-item", guide).forEach(function (n) {
      var raw = tx(n);
      var box = raw.match(/^\[([ xXхХ]?)\]/);        // `[ ]`, `[]` или `[x]` из плана
      if (!box) return;
      var t = raw.replace(/^\[.?\]\s*/, "");
      var h = nearestHead(n);
      if (!h) return;
      if (!h.id) h.id = "tnav-h" + order.length;
      if (!map[h.id]) { map[h.id] = { id: h.id, label: tx(h), rows: [] }; order.push(map[h.id]); }
      var mdDone = /[xXхХ]/.test(box[1]);
      var row = { key: (PCFG ? normKey(t) : keyOf(t)), el: n, md: mdDone, text: t };
      /* перенос отметок старой схемы (до записи в план они жили поштучно) */
      var legacy = keyOf(t);
      if (LS.g(legacy) === "1") {
        if (!mdDone && !(row.key in pend)) { pend[row.key] = true; savePend(); }
        try { localStorage.removeItem(legacy); } catch (e) {}
      }
      map[h.id].rows.push(row);
    });
    sections.forEach(function (s) {
      if (!PREP.test(s.label)) return;
      if (!map[s.id]) { map[s.id] = { id: s.id, label: s.label, rows: [] }; order.push(map[s.id]); }
    });
    prepGroups = order.filter(function (g) { return g.rows.length || PREP.test(g.label); });
  })();
  var hasPrep = prepGroups.length > 0;


  /* Пункты «[ ]» становятся живыми чекбоксами НА САМОЙ СТРАНИЦЕ: отметка
     сохраняется сразу, кнопки «сохранить» нет. Исходный «[ ]» прячется в
     .tnav-pb и возвращается при печати. */
  function firstBracket(node) {
    var w = D.createTreeWalker(node, NodeFilter.SHOW_TEXT, null), n;
    while ((n = w.nextNode())) if (/^\s*\[[ xXхХ]?\]/.test(n.nodeValue)) return n;
    return null;
  }
  function enhanceChecks() {
    prepGroups.forEach(function (g) {
      g.rows.forEach(function (r) {
        if (r.el.getAttribute("data-tnav-chk")) return;
        var node = firstBracket(r.el);
        if (!node) return;
        node.nodeValue = node.nodeValue.replace(/^(\s*)\[[ xXхХ]?\]\s*/, "$1");
        var pb = el("span", "tnav-pb", "[ ] ");
        var btn = el("button", "tnav-box");
        btn.type = "button";
        btn.innerHTML = svg(I.check);
        btn.setAttribute("aria-label", "Отметить пункт");
        function paint(on) {
          btn.setAttribute("aria-pressed", on ? "true" : "false");
          r.el.classList.toggle("tnav-done", on);
          /* пункт, отличающийся от плана, помечен как несохранённый */
          r.el.classList.toggle("tnav-unsaved", on !== !!r.md);
          pb.textContent = on ? "[×] " : "[ ] ";
        }
        r.paint = paint;
        paint(isDone(r));
        btn.addEventListener("click", function (e) {
          e.preventDefault(); e.stopPropagation();
          setDone(r, btn.getAttribute("aria-pressed") !== "true");
          paint(isDone(r));
          syncSaveUI();
          scheduleAuto();
          if (isOpen && state === "prep") renderPrep();
        });
        node.parentNode.insertBefore(btn, node);
        node.parentNode.insertBefore(pb, node);
        r.el.setAttribute("data-tnav-chk", r.key);
      });
    });
  }
  enhanceChecks();

  /* Свежее состояние плана при открытии страницы. Экспорт статичен: он помнит
     `[ ]` на момент сборки, поэтому без этого отметка, записанная в план (тем
     более с другого устройства), в уже собранном HTML не видна. Читаем сам
     `.md` рядом со страницей — он лежит в публичной зоне, логин не нужен;
     не получилось (file://, нет сети, гость без доступа) — остаётся состояние
     из HTML, то есть ровно нынешнее поведение. */
  function refreshFromPlan() {
    if (!canSave) return;
    fetch(new URL(encodeURIComponent(PCFG.mdFile), location.href).href, { credentials: "omit" })
      .then(function (r) { return r.ok ? r.text() : null; })
      .then(function (text) {
        if (!text) return;
        var re = new RegExp(PCFG.itemRe), plan = {}, seen = {};
        text.split("\n").forEach(function (ln) {
          var m = ln.match(re);
          if (!m) return;
          var k = normKey(m[3]);
          seen[k] = (seen[k] || 0) + 1;
          plan[k] = /[xXхХ]/.test(m[2]);
        });
        var changed = false;
        diag = { checked: 0, matched: 0, stale: [], missing: [], ambiguous: [],
                 planItems: Object.keys(plan).length, planDone: 0 };
        Object.keys(plan).forEach(function (k) { if (plan[k]) diag.planDone++; });
        prepGroups.forEach(function (g) {
          g.rows.forEach(function (r) {
            diag.checked++;
            if (!(r.key in plan)) { diag.missing.push(r.text); return; }
            if (seen[r.key] > 1) { diag.ambiguous.push(r.text); return; }
            diag.matched++;
            if (r.md === plan[r.key]) return;
            /* HTML собран раньше, чем правился план: страница помнит своё
               состояние скобок, план — актуальное. Правда за планом. */
            diag.stale.push(r.text);
            r.md = plan[r.key];
            changed = true;
            if (r.key in pend && pend[r.key] === r.md) delete pend[r.key];
            if (r.paint) r.paint(isDone(r));
          });
        });
        savePend(); syncSaveUI();
        if (isOpen && state === "prep") renderPrep();
        if (changed) { /* состояние страницы подтянуто к плану */ }
      })
      .catch(function () {});
  }

  /* ── запись отметок в план (.md) ─────────────────────────────────────── */
  /* Зеркало `prep_sync.apply_marks`: правится ТОЛЬКО символ в скобках, вся
     остальная строка сохраняется как есть. Неоднозначные ключи (одинаковый
     текст в двух строках) пропускаются — молча угадывать нельзя. */
  function applyMarks(text, marks) {
    var lines = text.split("\n"), re = new RegExp(PCFG.itemRe), seen = {}, i, m, k;
    for (i = 0; i < lines.length; i++) {
      m = lines[i].match(re);
      if (!m) continue;
      k = normKey(m[3]);
      (seen[k] = seen[k] || []).push(i);
    }
    var missed = [], applied = [];
    Object.keys(marks).forEach(function (key) {
      var idx = seen[key];
      if (!idx || idx.length > 1) { missed.push(key); return; }
      var mm = lines[idx[0]].match(re);
      lines[idx[0]] = mm[1] + "[" + (marks[key] ? "x" : " ") + "] " + mm[3];
      applied.push(key);
    });
    return { text: lines.join("\n"), missed: missed, applied: applied };
  }

  function token() { try { return localStorage.getItem("hub-auth"); } catch (e) { return null; } }
  function apiFetch(url, init) {
    init = init || {};
    init.credentials = "omit";
    var t = token();
    if (t) {
      var h = new Headers(init.headers || {});
      h.set("Authorization", "Basic " + t);
      init.headers = h;
    }
    return fetch(url, init);
  }
  function mdPath() {
    return decodeURIComponent(new URL(".", location.href).pathname)
      .replace(/^\/+/, "") + PCFG.mdFile;
  }
  function loginUrl() {
    return "/tools/login.html?why=travel&next=" + encodeURIComponent(location.href);
  }

  var saving = false, saveMsg = "", msgT = null;
  function httpErr(status) { var e = new Error("http " + status); e.status = status; return e; }
  /* 401 и 403 — РАЗНЫЕ беды, и лечатся по-разному. 401 — пароль не принят.
     403 — либо адрес недоверенный и токена нет, либо сайдкар на NAS старее
     репозитория и просто не знает этот путь (для него это «не разрешено»).
     Различаем пробой /api/health: он отвечает и пишет writable → дело в
     whitelist, то есть в необновлённом server.py, и слать человека на форму
     входа бессмысленно. */
  function explain403() {
    return apiFetch("/api/health")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (h) {
        return (h && h.writable)
          ? "Отказ 403: сайдкар не принимает этот файл. Похоже, на NAS не обновлён server.py."
          : "Отказ 403: нет прав с этого адреса — нужен вход.";
      })
      .catch(function () { return "Отказ 403: сайдкар недоступен."; });
  }
  /* Автосохранение: клик по пункту → через 2 с тишины запись в план. Без токена
     молчим (редирект на форму входа посреди отметок мешает) — остаётся кнопка
     «Сохранить в план» в «Заранее», она ведёт на вход. Не вышло — отметка
     остаётся в буфере браузера и видна как несохранённая. */
  var autoT = null;
  function scheduleAuto() {
    if (!canSave || !token()) return;
    clearTimeout(autoT);
    autoT = setTimeout(function () {
      if (saving) { scheduleAuto(); return; }
      saveToPlan(true);
    }, 2000);
  }
  function saveToPlan(auto) {
    if (saving || !canSave || !pendCount()) return;
    if (!token()) { if (auto !== true) location.href = loginUrl(); return; }
    saving = true; saveMsg = "Сохраняю…"; syncSaveUI();
    var path = mdPath(), marks = {};
    Object.keys(pend).forEach(function (k) { marks[k] = pend[k]; });

    function attempt(retry) {
      return apiFetch("/api/file?path=" + encodeURIComponent(path))
        .then(function (r) {
          if (r.status === 401 || r.status === 403) throw httpErr(r.status);
          if (!r.ok) throw new Error("Файл плана не читается (" + r.status + ")");
          return r.json();
        })
        .then(function (f) {
          var res = applyMarks(f.content, marks);
          if (!res.applied.length) return { ok: true, res: res, skipped: true };
          return apiFetch("/api/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: path, content: res.text, base_hash: f.hash })
          }).then(function (r) {
            if (r.status === 409 && !retry) return attempt(true);   // гонка — перечитать
            if (r.status === 401 || r.status === 403) throw httpErr(r.status);
            if (!r.ok) throw new Error("Не удалось записать план (" + r.status + ")");
            return { ok: true, res: res };
          });
        });
    }

    attempt(false).then(function (out) {
      if (!out || !out.ok) return;
      var res = out.res, done = {};
      res.applied.forEach(function (k) { done[k] = true; });
      // применённое переходит в «план», остальное остаётся в буфере
      prepGroups.forEach(function (g) {
        g.rows.forEach(function (r) {
          if (done[r.key]) { r.md = !!marks[r.key]; delete pend[r.key]; if (r.paint) r.paint(isDone(r)); }
        });
      });
      savePend();
      saveMsg = res.missed.length
        ? ("Сохранено: " + res.applied.length + " · не нашли строку в плане: " + res.missed.length)
        : ("Сохранено в план: " + res.applied.length);
    }).catch(function (e) {
      if (e && e.status === 401) {
        try { localStorage.removeItem("hub-auth"); } catch (x) {}
        saveMsg = "Пароль не принят — войдите заново";
        return;
      }
      if (e && e.status === 403) {
        return explain403().then(function (m) { saveMsg = m; });
      }
      saveMsg = "Не сохранилось: " + (e && e.message ? e.message : "ошибка");
    }).then(function () {
      saving = false; syncSaveUI();
      if (isOpen && state === "prep") renderPrep();
      clearTimeout(msgT);
      msgT = setTimeout(function () { saveMsg = ""; syncSaveUI(); }, 4000);
    });
  }

  /* Несохранённое видно ТАМ, ГДЕ человек отмечает, — в панели, а не только
     на два тапа вглубь в шторке: иначе «отметил и ушёл» выглядит как
     сохранение, а отметка остаётся в браузере. */
  function syncSaveUI() {
    try {
      var n = pendCount();
      if (typeof bTOC !== "undefined" && bTOC) bTOC.classList.toggle("has-unsaved", n > 0);
      if (typeof railPrep !== "undefined" && railPrep) paintRailPrep();
      if (typeof bSave === "undefined" || !bSave) return;
      bSave.classList.toggle("tnav-off", n === 0 && !saveMsg);
      var label = saving ? "Сохраняю…"
        : (!n && saveMsg) ? "Сохранено"
        : (canSave && !token()) ? "Войти" : "Сохранить";
      setBtn(bSave, saving ? I.clock : I.check, label, n || null);
      bSave.disabled = saving;
      fitBar();
    } catch (e) {}
  }

  /* ── каркас ──────────────────────────────────────────────────────────── */
  var root = el("div"); root.id = "tnav-root";
  var spacer = el("div"); spacer.id = "tnav-spacer";
  var scrim = el("div", "tnav-scrim");
  var sheet = el("div", "tnav-sheet");
  sheet.setAttribute("role", "dialog"); sheet.setAttribute("aria-modal", "true");
  var rail = el("nav", "tnav-rail"); rail.setAttribute("aria-label", "Оглавление документа");
  var bar = el("nav", "tnav-bar"); bar.setAttribute("aria-label", "Навигация по документу");

  var kicker = tx($(".cover-kicker", guide)) || (D.title || "Документ");
  var titleT = tx($(".cover-title", guide)) || (D.title || "");

  var head = el("div", "tnav-head");
  var backB = el("button", "tnav-ico tnav-off"); backB.innerHTML = svg(I.back); backB.title = "Назад";
  var headT = el("div", "tnav-head-t");
  var headK = el("div", "tnav-kick", kicker);
  var headN = el("div", "tnav-ttl", titleT);
  headT.appendChild(headK); headT.appendChild(headN);
  var closeB = el("button", "tnav-ico"); closeB.innerHTML = svg(I.close); closeB.title = "Закрыть";
  head.appendChild(backB); head.appendChild(headT); head.appendChild(closeB);
  var body = el("div", "tnav-body");
  sheet.appendChild(el("div", "tnav-grab")); sheet.appendChild(head); sheet.appendChild(body);

  function mkBtn(cls, icon, label) {
    var b = el("button", "tnav-b" + (cls ? " " + cls : ""));
    b.type = "button";
    b.innerHTML = svg(icon) + '<span class="tnav-lb"><span class="tnav-w">' + label + "</span></span>";
    return b;
  }
  function setBtn(b, icon, label, num) {
    b.innerHTML = svg(icon) + '<span class="tnav-lb"><span class="tnav-w">' + label + "</span>" +
      (num != null ? '<i class="tnav-n">' + num + "</i>" : "") + "</span>";
    b.setAttribute("aria-label", label + (num != null ? " " + num : ""));
    b.title = label + (num != null ? " " + num : "");
    fitBar();
  }

  /* Панель не режет подписи по букве («Сохра…»): если в ширину не влезает,
     подписи снимаются целиком по приоритету — сначала у контекстной кнопки,
     потом у «Разделов», в последнюю очередь у «Сохранить» (пока есть что
     сохранять, это главное действие). Счётчик остаётся всегда. */
  /* Меряем «влезает ли» ЧЕСТНО: на время замера запрещаем кнопкам сжиматься
     и снимаем обрезку — тогда переполнение панели видно. Сравнивать
     scrollWidth подписи с clientWidth бесполезно: у текста с многоточием они
     почти равны (само многоточие помещается), и «Сохра…» проходит как
     «влезло» — на этом первая версия и прокололась. */
  function overflows() {
    bar.classList.add("is-measuring");
    var over = bar.scrollWidth > bar.clientWidth + 1;
    bar.classList.remove("is-measuring");
    return over;
  }
  function fitBar() {
    if (!bar || bar.classList.contains("tnav-off")) return;
    /* пока есть несохранённое, подпись «Сохранить» — последняя, что снимаем */
    var order = pendCount() ? [bCtx, bTOC, bSave] : [bSave, bCtx, bTOC];
    order.forEach(function (b) { if (b) b.classList.remove("is-compact"); });
    for (var i = 0; i < order.length; i++) {
      if (!overflows()) return;
      if (order[i]) order[i].classList.add("is-compact");
    }
  }
  var bTOC = mkBtn("tnav-b--main", I.list, "Разделы");
  var bCtx = mkBtn("tnav-b--ctx", I.pin, "");
  var bSave = mkBtn("tnav-b--save tnav-off", I.check, "");
  bSave.title = "Сохранить отметки в план";
  var bTop = mkBtn("tnav-b--ico", I.up, "");
  bTop.setAttribute("aria-label", "Наверх"); bTop.title = "Наверх";
  bTOC.setAttribute("aria-expanded", "false");

  var ctxMode = null;
  if (tripState === "during") { ctxMode = "today"; setBtn(bCtx, I.today, "Сегодня", dayNo + "/" + dayTot); }
  else if (tripState === "before") { ctxMode = "before"; setBtn(bCtx, I.clock, "До старта", daysLeft + " дн"); }
  else if (items.length) { ctxMode = "count"; setBtn(bCtx, KIND === "days" ? I.today : I.pin, kindWord(), items.length); }

  bar.appendChild(bTOC);
  if (ctxMode) bar.appendChild(bCtx);
  bar.appendChild(bSave);
  bar.appendChild(bTop);
  bSave.onclick = function () {
    if (!canSave) { open("prep"); return; }
    saveToPlan();
  };

  var railH = el("div", "tnav-rail-h");
  railH.appendChild(el("div", "tnav-kick", kicker));
  /* статус поездки — то же, что контекстная кнопка нижней панели */
  if (tripState === "before") railH.appendChild(el("div", "tnav-rail-st", "До старта · " + daysLeft + " дн"));
  else if (tripState === "during") railH.appendChild(el("div", "tnav-rail-st", "Идёт · день " + dayNo + " из " + dayTot));
  var railBody = el("div", "tnav-rail-body");
  /* «↑ В начало» — сразу под списком глав, как в читателе кабинета (ui-kit
     .rd-top, вьюер портфеля); раньше жила в подвале рельса и уходила за край */
  var rTop = el("button", "tnav-top", "↑ В начало"); rTop.type = "button";
  rail.appendChild(railH); rail.appendChild(railBody);

  root.appendChild(rail); root.appendChild(bar); root.appendChild(scrim); root.appendChild(sheet); root.appendChild(spacer);
  if (CURRENT && CURRENT.parentNode) CURRENT.parentNode.removeChild(CURRENT);
  CURRENT = root;
  D.body.appendChild(root);

  /* ── переходы ────────────────────────────────────────────────────────── */
  /* Переход по меню — это прокрутка ВНИЗ, и авто-прятанье панели убирало бы её
     ровно в момент, когда человек только что ею воспользовался. На время
     программной прокрутки прятанье выключено. */
  /* Подсветка в рельсе на время перехода стоит на ЦЕЛИ и не пересчитывается:
     иначе при плавной прокрутке она пробегала все промежуточные главы и
     каждый раз дёргала прокрутку рельса. Дальний переход (> 2 экранов) —
     мгновенный: плавная прокрутка через весь документ с картами и таблицами
     выглядела как перерисовка страницы («мигает»). */
  var navUntil = 0, spyHold = 0;
  function goto(id) {
    var t = D.getElementById(id);
    if (!t) return;
    close();
    var y0 = W.pageYOffset || D.documentElement.scrollTop || 0;
    var y = t.getBoundingClientRect().top + y0 - 16;
    var far = Math.abs(y - y0) > W.innerHeight * 2;
    navUntil = spyHold = Date.now() + (far ? 250 : 1200);
    bar.classList.remove("is-hidden");
    setActive(id);
    if (far) { W.scrollTo(0, y); return; }
    try { W.scrollTo({ top: y, behavior: "smooth" }); } catch (e) { W.scrollTo(0, y); }
  }
  function toTop() {
    close();
    navUntil = Date.now() + 1200;
    bar.classList.remove("is-hidden");
    try { W.scrollTo({ top: 0, behavior: "smooth" }); } catch (e) { W.scrollTo(0, 0); }
  }

  bTop.onclick = toTop; rTop.onclick = toTop;

  /* ── содержимое шторки ───────────────────────────────────────────────── */
  var itemsAnchor = null;   /* заголовок группы элементов внутри шторки */
  function rowFor(o) {
    var b = el("button", "tnav-row" + (o.cls ? " " + o.cls : ""));
    b.type = "button";
    b.dataset.tnavId = o.id || "";
    if (o.key != null && o.key !== "") b.appendChild(el("span", "tnav-k", o.key));
    b.appendChild(el("span", "tnav-txt", o.label));
    if (o.sig) b.appendChild(el("span", "tnav-sig", o.sig));
    return b;
  }
  function renderTOC() {
    state = "toc";
    itemsAnchor = null;
    backB.classList.add("tnav-off");
    headK.textContent = kicker; headN.textContent = titleT;
    body.innerHTML = "";
    if (hasPrep) {
      var cta = el("button", "tnav-cta");
      cta.type = "button";
      cta.innerHTML = svg(I.check) + "<span>Заранее — что сделать до поездки</span>";
      cta.onclick = renderPrep;
      var wrap = el("div");
      wrap.style.padding = "12px 14px 4px";
      wrap.appendChild(cta);
      body.appendChild(wrap);
    }
    body.appendChild(el("div", "tnav-gh", "Разделы"));
    sections.forEach(function (s) {
      var b = rowFor({ id: s.id, label: s.label, cls: "tnav-l" + s.lvl });
      b.onclick = function () { goto(s.id); };
      body.appendChild(b);
    });
    if (items.length) {
      itemsAnchor = el("div", "tnav-gh", kindWord() + " · " + items.length);
      body.appendChild(itemsAnchor);
      var g = null;
      items.forEach(function (it) {
        if (it.group && it.group !== g) { g = it.group; body.appendChild(el("div", "tnav-sub", g)); }
        var b = rowFor({ id: it.id, key: it.key, label: it.label });
        b.onclick = function () { goto(it.id); };
        body.appendChild(b);
      });
    }
    if (!sections.length && !items.length) body.appendChild(el("div", "tnav-empty", "В документе нет размеченных разделов."));
    paintActive();
    centerActive();
  }
  function renderPrep() {
    state = "prep";
    itemsAnchor = null;
    backB.classList.remove("tnav-off");
    headK.textContent = "Подготовка";
    headN.textContent = "Заранее";
    body.innerHTML = "";
    var total = 0, done = 0;
    prepGroups.forEach(function (g) {
      g.n = g.rows.length;
      g.d = g.rows.filter(isDone).length;
      total += g.n; done += g.d;
    });
    var pr = el("div", "tnav-prog");
    pr.appendChild(el("span", "tnav-prog-t", done + " / " + total));
    var pbar = el("div", "tnav-prog-b"), fill = el("div", "tnav-prog-f");
    fill.style.width = total ? (done / total * 100) + "%" : "0";
    pbar.appendChild(fill); pr.appendChild(pbar); body.appendChild(pr);

    /* Состояние сохранности: что уже в плане, что пока только в браузере.
       Пишем в файл одной кнопкой, а не на каждый клик. */
    var unsaved = pendCount();
    if (PCFG || unsaved) {
      var sv = el("div", "tnav-save");
      var inPlan = 0;
      prepGroups.forEach(function (g) {
        g.rows.forEach(function (r) { if (r.md) inPlan++; });
      });
      sv.appendChild(el("div", "tnav-save-t",
        "В плане: " + inPlan + " · не сохранено: " + unsaved));
      if (saveMsg) sv.appendChild(el("div", "tnav-save-m", saveMsg));
      if (!canSave) {
        sv.appendChild(el("div", "tnav-save-m",
          PCFG ? "Сохранение доступно, когда страница открыта с сервера."
               : "Файл плана не определён — отметки живут только в этом браузере."));
      } else {
        var b = el("button", "tnav-cta");
        b.type = "button";
        b.disabled = !unsaved || saving;
        b.style.margin = "8px 0 0";
        b.innerHTML = svg(I.check) + "<span>" +
          (saving ? "Сохраняю…" : (token() ? "Сохранить в план" : "Войти, чтобы сохранить")) +
          "</span>";
        b.onclick = saveToPlan;
        sv.appendChild(b);
        sv.appendChild(el("div", "tnav-save-m", "Пишется в " + PCFG.mdFile));
      }
      body.appendChild(sv);
    }

    /* Сверка HTML ↔ план: для отладки технологии и чтобы «пункт не
       сохраняется» не выяснялось молча. Показывается всегда, когда план
       прочитан: числа сразу говорят, сходится ли разметка страницы с файлом. */
    if (diag) {
      var dg = el("div", "tnav-diag");
      dg.appendChild(el("div", "tnav-diag-t",
        "Сверка с планом: " + diag.matched + " из " + diag.checked
        + " · в плане отмечено " + diag.planDone + " из " + diag.planItems));
      var probs = [];
      if (diag.stale.length) probs.push(["HTML старше плана", diag.stale]);
      if (diag.missing.length) probs.push(["нет строки в плане", diag.missing]);
      if (diag.ambiguous.length) probs.push(["текст встречается дважды", diag.ambiguous]);
      probs.forEach(function (pr) {
        var d = el("details", "tnav-diag-d");
        var sm = el("summary", null, pr[0] + ": " + pr[1].length);
        d.appendChild(sm);
        pr[1].slice(0, 12).forEach(function (t) {
          d.appendChild(el("div", "tnav-diag-i", "· " + t.slice(0, 90)));
        });
        if (pr[1].length > 12) d.appendChild(el("div", "tnav-diag-i", "…"));
        dg.appendChild(d);
      });
      if (!probs.length) dg.appendChild(el("div", "tnav-diag-ok", "расхождений нет"));
      body.appendChild(dg);
    }

    body.appendChild(el("div", "tnav-gh", "Где что лежит"));
    prepGroups.forEach(function (g) {
      var b = el("button", "tnav-row");
      b.type = "button";
      b.dataset.tnavId = g.id;
      b.appendChild(el("span", "tnav-txt", g.label));
      if (g.n) {
        var all = g.d === g.n;
        b.appendChild(el("span", "tnav-sig" + (all ? " is-done" : ""), g.d + " / " + g.n));
        if (all) b.classList.add("is-closed");
      }
      var j = el("span", "tnav-jump");
      j.innerHTML = svg(I.jump);
      b.appendChild(j);
      b.onclick = function () { goto(g.id); };
      body.appendChild(b);
    });
    body.appendChild(el("div", "tnav-empty",
      "Пункты отмечаются галочкой прямо в документе — по ссылке. Отметка сохраняется "
      + "в файл плана по кнопке выше, поэтому переживает пересборку экспорта и попадает в PDF."));
  }
  backB.onclick = renderTOC;

  /* ── открытие / закрытие ─────────────────────────────────────────────── */
  var state = "toc", isOpen = false;
  function open(view) {
    isOpen = true;
    (view === "prep" && hasPrep) ? renderPrep() : renderTOC();
    if (view === "items" && itemsAnchor) body.scrollTop = itemsAnchor.offsetTop;
    scrim.classList.add("is-open");
    sheet.classList.add("is-open");
    D.documentElement.classList.add("tnav-lock");
    bTOC.setAttribute("aria-expanded", "true");
    bTOC.classList.add("is-on");
  }
  function close() {
    if (!isOpen) return;
    isOpen = false;
    scrim.classList.remove("is-open");
    sheet.classList.remove("is-open");
    D.documentElement.classList.remove("tnav-lock");
    bTOC.setAttribute("aria-expanded", "false");
    bTOC.classList.remove("is-on");
  }
  bTOC.onclick = function () { isOpen ? close() : open("toc"); };
  closeB.onclick = close;
  scrim.onclick = close;

  bCtx.onclick = function () {
    if (ctxMode === "today" && todayEl) goto(todayEl.id);
    else if (ctxMode === "before") hasPrep ? open("prep") : goto(days[0] ? days[0].id : (items[0] || {}).id);
    else open("items");
  };

  function centerActive() {
    var a = $(".tnav-row.is-active", body);
    if (!a) return;
    body.scrollTop = Math.max(0, a.offsetTop - body.clientHeight / 2 + a.offsetHeight / 2);
  }

  /* ── рельс: разделы + раскрытие ──────────────────────────────────────── */
  var railExpanded = items.length > 0 && (items.length <= 20 || sections.length < 6);
  var railPrep = null;
  function paintRailPrep() {
    var n = pendCount();
    railPrep.classList.toggle("has-unsaved", n > 0);
    railPrep.innerHTML = svg(I.check) + "<span>Заранее</span>" +
      (n ? '<i class="tnav-n" title="не сохранено в план">' + n + "</i>" : "");
  }
  function renderRail() {
    railBody.innerHTML = "";
    railPrep = null;
    if (hasPrep) {
      var cta = el("button", "tnav-cta");
      cta.type = "button";
      cta.style.margin = "0 10px 10px";
      cta.style.width = "calc(100% - 20px)";
      cta.onclick = function () { open("prep"); };
      railPrep = cta;
      paintRailPrep();
      railBody.appendChild(cta);
    }
    if (tripState === "during" && todayEl) {
      var t = el("button", "tnav-cta");
      t.type = "button";
      t.innerHTML = svg(I.today) + "<span>Сегодня · " + tx($(".day-date", todayEl)) + "</span>";
      t.style.margin = "0 10px 10px";
      t.style.width = "calc(100% - 20px)";
      t.onclick = function () { goto(todayEl.id); };
      railBody.insertBefore(t, railBody.firstChild);
    }
    sections.forEach(function (s) {
      var b = el("button", "tnav-rl lv" + s.lvl);
      b.type = "button";
      b.dataset.tnavId = s.id;
      b.appendChild(el("span", "tnav-rt", s.label));
      b.onclick = function () { goto(s.id); };
      railBody.appendChild(b);
    });
    if (items.length) {
      var exp = el("button", "tnav-exp" + (railExpanded ? " is-open" : ""));
      exp.type = "button";
      exp.innerHTML = svg(I.chev) + kindWord() + " · " + items.length;
      exp.onclick = function () { railExpanded = !railExpanded; renderRail(); paintActive(); };
      railBody.appendChild(exp);
      if (railExpanded) {
        var g = null;
        items.forEach(function (it) {
          if (it.group && it.group !== g) {
            g = it.group;
            var gb = el("button", "tnav-rl lv3");
            gb.type = "button";
            gb.appendChild(el("span", "tnav-rt", g));
            gb.onclick = function () { goto(it.id); };
            railBody.appendChild(gb);
          }
          var b = el("button", "tnav-rl it");
          b.type = "button";
          b.dataset.tnavId = it.id;
          if (it.key) b.appendChild(el("span", "tnav-rk", it.key));
          b.appendChild(el("span", "tnav-rt", it.label));
          b.onclick = function () { goto(it.id); };
          railBody.appendChild(b);
        });
      }
    }
    railBody.appendChild(rTop);
  }
  renderRail();

  /* ── подсветка активного + прятанье панели ───────────────────────────── */
  var spyList = sections.map(function (s) { return s.id; }).concat(items.map(function (i) { return i.id; }));
  var activeId = null, lastY = W.pageYOffset || 0, idleT = null;
  function computeActive() {
    var best = null, bestTop = -1e9, lim = 140;
    for (var i = 0; i < spyList.length; i++) {
      var n = D.getElementById(spyList[i]);
      if (!n) continue;
      var t = n.getBoundingClientRect().top;
      if (t <= lim && t > bestTop) { bestTop = t; best = spyList[i]; }
    }
    return best;
  }
  function paintActive() {
    $$("[data-tnav-id]", root).forEach(function (b) {
      b.classList.toggle("is-active", b.dataset.tnavId === activeId);
    });
  }
  function onScrollFrame() {
    var y = W.pageYOffset || D.documentElement.scrollTop || 0;
    /* панель уходит при прокрутке вниз и возвращается при прокрутке вверх —
       на читальной странице постоянная полоса внизу мешает. Через 900 мс
       покоя возвращается в любом случае: «куда делась панель» быть не должно */
    if (!isOpen && Date.now() > navUntil) {
      var down = y - lastY;
      if (y > 220 && down > 6) bar.classList.add("is-hidden");
      else if (down < -6 || y <= 220) bar.classList.remove("is-hidden");
      clearTimeout(idleT);
      idleT = setTimeout(function () { bar.classList.remove("is-hidden"); }, 900);
    }
    if (Math.abs(y - lastY) > 2) lastY = y;
    if (Date.now() < spyHold) return;
    setActive(computeActive());
  }
  function setActive(a) {
    if (a === activeId) return;
    activeId = a;
    paintActive();
    var cur = $(".tnav-rl.is-active", railBody);
    if (cur) {
      var top = cur.offsetTop, h = railBody.clientHeight;
      if (top < railBody.scrollTop + 20 || top > railBody.scrollTop + h - 40)
        railBody.scrollTop = Math.max(0, top - h / 2);
    }
  }

  /* ── раскладка: рельс только если слева реально есть место ───────────── */
  var mode = null;
  function layout() {
    var r = page.getBoundingClientRect();
    var gap = r.left, w = Math.min(236, gap - 30);
    var desk = W.innerWidth >= 1100 && w >= 172;
    root.classList.toggle("tnav-desk", desk);
    root.classList.toggle("tnav-mobile", !desk);
    bar.classList.toggle("tnav-off", desk);
    if (desk) { rail.style.width = w + "px"; rail.style.left = Math.max(10, (gap - w) / 2) + "px"; }
    /* высоту панели отдаём наружу: под неё сдвигается плавающая кнопка
       «Сохранить» edit-слоя Stage 3 */
    D.documentElement.style.setProperty("--tnav-bottom", desk ? "0px" : (bar.offsetHeight + 18) + "px");
    fitBar();
    /* шторку закрываем ТОЛЬКО при реальной смене режима на рельс: на телефоне
       resize прилетает от сворачивания адресной строки и от клавиатуры */
    if (desk && mode === false) close();
    mode = desk;
  }
  layout();
  onScrollFrame();
  refreshFromPlan();

  return {
    sig: sections.length + ":" + items.length,
    scroll: onScrollFrame,
    layout: layout,
    close: close,
    esc: function (e) { if (isOpen && e.key === "Escape") { e.stopPropagation(); close(); } },
    page: page
  };
}

/* ── глобальные слушатели вешаются ОДИН раз на весь документ ───────────── */
var ticking = false;
function onScroll() {
  if (ticking || !API) return;
  ticking = true;
  W.requestAnimationFrame(function () { ticking = false; if (API) API.scroll(); });
}
function bindGlobals() {
  W.addEventListener("scroll", onScroll, { passive: true });
  W.addEventListener("resize", function () { if (API) API.layout(); }, { passive: true });
  W.addEventListener("beforeprint", function () { if (API) API.close(); });
  D.addEventListener("keydown", function (e) { if (API) API.esc(e); }, true);
  if (W.ResizeObserver) {
    var ro = new ResizeObserver(function () { if (API) API.layout(); });
    var target = $(".page") || D.body;
    if (target) ro.observe(target);
  }
}

/* Документы, которые дорисовывают содержимое своим скриптом (стадия 2 строит
   карточки авторов после загрузки), пересобирают меню один раз после `load`. */
function boot() {
  API = init();
  bindGlobals();
  W.addEventListener("load", function () {
    setTimeout(function () {
      var probe = D.querySelectorAll(".section-plate,.section-plate--sub,.anno").length + ":" +
        (D.querySelectorAll(".day").length || D.querySelectorAll(".poi[data-poi]").length ||
         D.querySelectorAll(".opt-card").length || D.querySelectorAll(".scard").length ||
         D.querySelectorAll('[id^="author-"]').length);
      if (API && probe !== API.sig) API = init();
    }, 300);
  }, { once: true });
}
if (D.readyState === "loading") D.addEventListener("DOMContentLoaded", boot);
else boot();
})();
