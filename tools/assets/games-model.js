/* games-model.js — модель слияния библиотеки игр: ОДНА реализация для games.html и плитки «Игры» на hub.html.
 * Слои: taste-profile.yaml: library + library_full.yaml (пишет скилл) под оверлеем Gaming/user-state.json (пишет сайт).
 * Правила — skills/game-advisor/references/data-layout.md. Нужен assets/codelists.js (CL) до этого файла.
 * Обычный скрипт без модулей: глобальные функции games*. */
(function (root) {
  "use strict";
  var PLAT_ALIAS = { switch2: "switch2", nintendoswitch2: "switch2", ns2: "switch2", "switch": "switch", nintendoswitch: "switch", ns: "switch",
    steamdeck: "steam_deck", deck: "steam_deck", steam: "steam", pc: "pc", windows: "pc",
    xbox: "xbox", xboxseries: "xbox", xboxone: "xbox", xsx: "xbox", xboxseriesx: "xbox", xboxseriess: "xbox", xboxseriesxs: "xbox" };

  /* ключ игры во всех файлах — название без регистра и пунктуации */
  function gamesNormTitle(s) {
    return String(s).toLowerCase().replace(/[^a-zа-яё0-9]+/g, " ").trim();
  }
  /* платформа из файлов советника → код кодлиста game_platform; неизвестное → null */
  function gamesNormPlat(v) {
    if (v == null) return null;
    var k = String(v).toLowerCase().replace(/[^a-zа-яё0-9]+/g, "");
    return Object.prototype.hasOwnProperty.call(PLAT_ALIAS, k) ? PLAT_ALIAS[k] : null;
  }
  function progCodes() { return CL.codes("game_progress"); }
  /* статусы «не куплена» (хочу / на-карандаш / не-интересно): игра живёт на экране «Присматриваюсь» */
  function gamesIsWatchState(v) {
    v = String(v || "").trim();
    return v !== "куплена" && CL.codes("game_state", false).indexOf(v) >= 0;
  }
  /* Единое правило старых значений (то же в tools/gaming_migrate.py): state демо → demo + статус по оценке;
     играю / пройдена / брошена → куплена + прохождение с тем же словом; оценка «брошено» снимается. */
  function gamesNormUserRec(u) {
    if (!u) return u;
    if (u.state === "демо") {
      u.demo = true;
      u.state = u.rating === "не понравилось" ? "не-интересно" : "на-карандаш";
    }
    if (u.state === "куплена" && u.demo) delete u.demo;
    var gs = (root.CODELISTS && root.CODELISTS.lists.game_state) || {}, e = gs[u.state];
    if (e && e.legacy && e.migrate_to) {
      if (!u.progress && progCodes().indexOf(u.state) >= 0) u.progress = u.state;
      u.state = e.migrate_to;
    }
    if (u.rating === "брошено") {
      u.rating = null;
      if (!u.progress) u.progress = "брошена";
    }
    if (u.progress === "не-начата") u.progress = null;
    return u;
  }
  function gamesNormUserDoc(doc) {
    ((doc && doc.items) || []).forEach(gamesNormUserRec);
    return doc;
  }
  function gamesUserMap(items) {
    var m = {};
    (items || []).forEach(function (u) { if (u && u.title) m[gamesNormTitle(u.title)] = u; });
    return m;
  }
  /* profileLibrary — taste-profile.yaml: library; libFull — library_full.yaml: library_full; overlayItems — user-state.json: items
     (уже нормализованные gamesNormUserDoc). → { rows, total } */
  function gamesMergeLibrary(profileLibrary, libFull, overlayItems) {
    var um = gamesUserMap(overlayItems), rows = {}, order = [], verdicted = {}, progs = progCodes();
    function put(k, r) { if (!rows[k]) { order.push(k); } rows[k] = r; }
    function drop(k) { if (rows[k]) { delete rows[k]; order.splice(order.indexOf(k), 1); } }
    (profileLibrary || []).forEach(function (g) {
      if (g && g.title && g.verdict) verdicted[gamesNormTitle(g.title)] = 1;
    });
    (profileLibrary || []).forEach(function (g) {
      /* вердикт «брошено» файлов советника — прохождение «брошена», оценки нет */
      if (g && g.title && g.verdict) put(gamesNormTitle(g.title), { title: g.title, platform: gamesNormPlat(g.platform), hours: g.hours != null ? g.hours : null, baseHours: g.hours != null ? g.hours : null,
        verdict: g.verdict === "брошено" ? null : g.verdict, progress: g.verdict === "брошено" ? "брошена" : (progs.indexOf(g.progress) >= 0 ? g.progress : null) });
    });
    (libFull || []).forEach(function (g) {
      if (!g || !g.title) return;
      var k = gamesNormTitle(g.title);
      if (!verdicted[k]) put(k, { title: g.title, platform: gamesNormPlat(g.platform), hours: g.hours != null ? g.hours : null, baseHours: g.hours != null ? g.hours : null, verdict: null, progress: null });
    });
    Object.keys(um).forEach(function (k) {
      var u = um[k], r = rows[k];
      if (u.deleted) { drop(k); return; }
      if (!r) {
        if (gamesIsWatchState(u.state)) return;            /* хочу / на карандаше — экран «Присматриваюсь» */
        r = { title: u.title, platform: null, hours: null, baseHours: null, verdict: null, progress: null };
        put(k, r);
      }
      if (gamesIsWatchState(u.state)) { drop(k); return; } /* не куплена (в т. ч. с флагом демо) — только «Присматриваюсь» */
      r.u = u;
      if (u.progress) r.progress = u.progress;
      if (u.rating) r.verdict = u.rating;                  /* оценка с сайта вместо verdict */
      if (u.platform) r.platform = u.platform;
      r.note = u.note; r.cover = u.cover_url; r.steam_appid = u.steam_appid;
      if (u.hours != null) r.hours = u.hours;              /* часы владельца главнее библиотеки */
    });
    return { rows: order.map(function (k) { return rows[k]; }), total: order.length };
  }
  /* сводка плитки: всего · не начато (чип «не начата» библиотеки без других фильтров) · часы (округлённая сумма) */
  /* Сводка для плитки хаба: играю · бэклог (не начата + отложена) · пройдено; брошенные ни в одну группу не входят.
     plats — платформы, на которых в библиотеке есть игры, по убыванию числа (Switch и Switch 2 — один ключ switch). */
  function gamesLibSummary(merged) {
    var notStarted = 0, paused = 0, playing = 0, done = 0, hours = 0, pc = {};
    merged.rows.forEach(function (g) {
      var p = g.progress || "не-начата";
      if (p === "не-начата") notStarted++;
      else if (p === "отложена") paused++;
      else if (p === "играю") playing++;
      else if (p === "пройдена") done++;
      hours += +g.hours || 0;
      var pl = g.platform === "switch2" ? "switch" : g.platform;
      if (pl) pc[pl] = (pc[pl] || 0) + 1;
    });
    var plats = Object.keys(pc).sort(function (x, y) { return pc[y] - pc[x] || (x < y ? -1 : 1); });
    return { total: merged.total, notStarted: notStarted, playing: playing, backlog: notStarted + paused, done: done,
             hours: Math.round(hours), plats: plats };
  }
  root.gamesNormTitle = gamesNormTitle; root.gamesNormPlat = gamesNormPlat; root.gamesIsWatchState = gamesIsWatchState;
  root.gamesNormUserRec = gamesNormUserRec; root.gamesNormUserDoc = gamesNormUserDoc; root.gamesUserMap = gamesUserMap;
  root.gamesMergeLibrary = gamesMergeLibrary; root.gamesLibSummary = gamesLibSummary;
})(typeof window !== "undefined" ? window : globalThis);
