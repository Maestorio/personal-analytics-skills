/* Офлайн-ядро фоновых скриптов кабинета (2026-10-23). Подключают оба:
     /tools/sw.js           — все страницы (scope /tools/, регистрирует ui-kit uiOfflineInit);
     /tools/portfolio-sw.js — вьюер (держит подписки push; его scope уже, он и управляет вьюером).
   Один набор кешей на сайт, поэтому что бы ни управляло страницей — поведение одно.

   Оболочка (/tools/*.html, *.md справок, /tools/assets/*):
     страницы и справки — «сначала сеть» (выложенная правка видна сразу), без сети или сервер лёг
     (5xx) — из кеша; ассеты с ?v= — из кеша (версия в адресе), без ?v= — из кеша с фоновым
     обновлением. При установке скачиваются все страницы и их ассеты — офлайн открывается и та
     страница, которую давно не открывали.
   Данные (только пути из KEEP — что держим офлайн; отчёты портфеля и исходники исследований «Здоровья» не держим,
   отчёты «Здоровья» и подборки «Игр» — держим, решение владельца 2026-11-05):
     «сначала сеть» с таймаутом DATA_TIMEOUT_MS; ответ 200 — копия обновляется; нет сети, сервер лёг
     или не успел — копия + сообщение странице (ui-kit рисует плашку «показаны данные от …»).
     404 запоминается тоже (без связи — тот же «файла нет», а не «не удалось загрузить»: trip.yaml,
     watchlist.yaml и т. п. необязательны). /api/health (возможности сайдкара) — тоже: без связи страницы
     ведут себя как при связи, а «нет связи» говорит плашка ui-kit. Приватные пути (PRIVATE) хранятся с меткой пароля (хэш Authorization):
     чужая метка не отдаётся; «Выйти» (cab-logout), 401/403 — приватные копии стираются.
   /api/* (кроме чтения файлов «Еды» и «Здоровья» и плана вьюера), POST и чужие домены не трогаются вовсе.

   Знание «связи нет» (1.2.0): на телефоне без связи запрос часто не падает сразу, а висит до таймаута —
   каждая страница ждала сеть 4–8 с, вьюер — минуту (тест 2026-10-26). Первый таймаут или сбой сети
   запоминается (в памяти и в кеше CAB_STATE: телефон останавливает фоновый скрипт между страницами);
   дальше сеть ждём не дольше OFF_TIMEOUT_MS, а при navigator.onLine === false не ждём вовсе. Запрос в сеть
   всё равно уходит: первый же ответ сервера снимает метку (cab-online), копия обновляется.

   Прошлая версия (1.3.0): ассет нужной версии, которого нет в кеше, ждёт сеть ASSET_TIMEOUT_MS (20 с) — на
   медленной сети страница получает новый код. Прежнюю версию отдаём, только если сеть не ответила вовсе
   (нет связи, ошибка, таймаут), и шлём страницам cab-stale — ui-kit показывает тост «Открыта прошлая версия».
   Страница из копии при ответившей позже сети тоже даёт cab-stale, но только если текст отличается. */
var CAB_OFF_VER = '1.6.1';   // 1.6.1: оверлей игр /api/gm/file (карточка игры; запись — только при связи) · 1.6.0: флаг режима сайта «с ИИ / без ИИ» (/api/hub/settings — ui-kit читает при загрузке каждой страницы; без связи — последний известный режим) · 1.5.1 (2026-11-05): журнал плана вьюера (/api/pv/plan/journal) · 1.5.0 (2026-11-05): отчёты «Здоровья» и подборки «Игр» держим (решение владельца; исходники исследований — нет) · 1.4.2: план сайта вьюера (/api/pv/plan) · 1.4.1: «Здоровье» — анамнез и список отчётов (без них страница при висящей сети не открывалась) · 1.4.0 (2026-10-31): носители схемы данных вьюера (решения, условия формата 2 и их состояние, справочник бумаг, макросценарии) вместо файла гейтов · 1.3.1: часть справки 10-new.md
var CAB_SHELL = 'cab-shell-v1';
var CAB_DATA = 'cab-data-v1';
var CAB_STATE = 'cab-state-v1';
var CAB_BASE = new URL('./', self.location).pathname;          // /tools/
var CAB_PAGES = ['hub.html', 'travel.html', 'food.html', 'health.html', 'money.html', 'games.html',
                 'portfolio-integrated-viewer.html', 'login.html',
                 'assets/help/viewer/00-about.md', 'assets/help/viewer/01-run.md', 'assets/help/viewer/02-models.md',
                 'assets/help/viewer/03-fresh.md', 'assets/help/viewer/04-tabs.md', 'assets/help/viewer/05-now.md',
                 'assets/help/viewer/06-gates.md', 'assets/help/viewer/07-conditions.md', 'assets/help/viewer/08-site.md',
                 'assets/help/viewer/09-limits.md', 'assets/help/viewer/10-new.md'];
var NAV_TIMEOUT_MS = 4000;
var ASSET_TIMEOUT_MS = 20000;                                   // ассет нужной версии: медленная сеть — ждём, а не отдаём прежнюю версию (1.3.0)
var DATA_TIMEOUT_MS = 8000;
var OFF_TIMEOUT_MS = 1200;                                      // связи не было — ждём сеть не дольше
var SAVE_TIMEOUT_MS = 10000;                                    // запись без ответа — в очередь
var DATA_MAX = 1500;                                            // записей копии; больше — старые вон

// Что держим офлайн — пути от корня сайта. Чего здесь нет — без сети недоступно (как раньше).
var CAB_KEEP = [
  /^\/Food\/[^/]+\.json$/, /^\/Food\/recipes\/([^/]+\.json)?$/, /^\/api\/fd\/file$/,
  /^\/api\/health$/,
  /^\/api\/file$/,                                              // слой правок стадий: md + хэш (1.1.0)
  /^\/travel-planner\/trips\/$/, /^\/travel-planner\/trips\/[^/_.][^/]*\/$/,
  /^\/travel-planner\/trips\/[^/_.][^/]*\/[^/]+\.(md|ya?ml|html)$/, /^\/travel-planner\/profiles\/([^/]+\.md)?$/,
  /^\/health-data\/(labs|biomarkers-info|meds|vaccinations|vitals|studies|anamnesis)\.json$/, /^\/health-data\/reports\/([^/]+\.(md|html))?$/, /^\/api\/hd\/file$/,
  /^\/ZenMoney\/audit\/([^/]+\.json)?$/,
  /^\/Gaming\/[^/]+\.(ya?ml|json)$/, /^\/Gaming\/recommendations\/([^/]+\.md)?$/,
  /^\/api\/pv\/plan$/,                                          // план сайта вьюера (доли, статусы); запись — только при связи
  /^\/api\/pv\/plan\/journal$/,                                  // журнал изменений плана (только чтение)
  /^\/api\/hub\/settings$/,                                      // режим сайта «с ИИ / без ИИ» (ui-kit 1.67.0); запись — только при связи
  /^\/api\/gm\/file$/,                                            // оверлей игр Gaming/user-state.json (games 2.1); запись — только при связи
  /^\/Portfolio\/$/, /^\/Portfolio\/(conditions|conditions-archive-\d{4})\.yaml$/, /^\/Portfolio\/(conditions-state|security-attrs)\.json$/,
  /^\/Portfolio\/(integrated-views|weekly-reviews|stress|snapshots|decisions)\/([^/]+)?$/,
  /^\/(macro-snapshots|macro-snapshots\/auto|macro-snapshots\/inflation|monitor-reports|forecasts|scenarios|macro-chain)\/([^/]+)?$/
];
// Внутри держимых папок — всё равно нет: печатные копии, архив, тяжёлые экспорты
var CAB_NEVER = [/_print\.html$/i, /\/_archive\//, /\.(pdf|docx)$/i, /\/\.[^/]*$/, /\/@eaDir\//];
var CAB_PRIVATE = /^\/(Portfolio|health-data|ZenMoney|macro-snapshots|monitor-reports|forecasts|scenarios|macro-chain|api\/hd|api\/pv|api\/hub|api\/gm)\//;

function cabKeep(path) {
  if (CAB_NEVER.some(function (re) { return re.test(path); })) return false;
  return CAB_KEEP.some(function (re) { return re.test(path); });
}
function cabMark(auth) {                                        // хэш, сам пароль не хранится
  if (!auth) return '';
  var h = 5381;
  for (var i = 0; i < auth.length; i++) h = ((h << 5) + h + auth.charCodeAt(i)) | 0;
  return 'm' + (h >>> 0);
}
function cabNoop() {}

// Ключ копии данных: без меток «Обновить» (cb, _), листинг JSON отдельно от HTML-листинга
function cabDataKey(req) {
  var u = new URL(req.url);
  u.searchParams.delete('cb');
  u.searchParams.delete('_');
  if ((req.headers.get('Accept') || '').indexOf('json') >= 0 && /\/$/.test(u.pathname)) u.searchParams.set('__a', 'json');
  u.hash = '';
  return u.href;
}

// Сеть с таймаутом: → { res } | { late: promise } | { err }
function cabRace(promise, ms) {
  return new Promise(function (resolve) {
    var done = false;
    var t = setTimeout(function () { if (!done) { done = true; resolve({ late: promise }); } }, ms);
    promise.then(function (r) { if (!done) { done = true; clearTimeout(t); resolve({ res: r }); } },
                 function (e) { if (!done) { done = true; clearTimeout(t); resolve({ err: e }); } });
  });
}

// Метка «связи нет»: 0 — связь есть, число — с какого момента нет. Читается из кеша при каждом запросе:
// фоновых скриптов два (sw.js и portfolio-sw.js вьюера), память у каждого своя — метку, поставленную на
// хабе, вьюер иначе не видел и ждал сеть заново
var cabOff = 0;
var CAB_STATE_KEY = 'https://cab.state/offline';
function cabOffGet() {
  return caches.open(CAB_STATE).then(function (c) { return c.match(CAB_STATE_KEY); })
    .then(function (r) { return r ? r.text() : '0'; })
    .then(function (t) { cabOff = +t || 0; return cabOff; })
    .catch(function () { return cabOff; });
}
function cabOffSet(v) {
  cabOff = v;
  return caches.open(CAB_STATE).then(function (c) { return c.put(CAB_STATE_KEY, new Response(String(v))); }).catch(cabNoop);
}
// Сколько ждать сеть: связи точно нет — 0; недавно не было — OFF_TIMEOUT_MS; иначе — обычный таймаут
function cabWait(ms) {
  if (self.navigator && self.navigator.onLine === false) return Promise.resolve(0);
  return cabOffGet().then(function (off) { return off ? Math.min(ms, OFF_TIMEOUT_MS) : ms; });
}
function cabNetSeen(o) {                                         // итог гонки → метка
  if (o.late || o.err) cabOffSet(Date.now());
  if (o.late) o.late.then(function (r) { if (r && r.status < 500) cabOnlineAgain(); }, cabNoop);
}

function cabNotify(event, path, saved) {
  var id = event.clientId || event.resultingClientId;
  if (!id) return;
  self.clients.get(id).then(function (c) {
    if (c) c.postMessage({ type: 'cab-offline', path: path, saved: saved });
  }).catch(cabNoop);
}

// ─── оболочка ───────────────────────────────────────────────────────────────
function cabShellKey(req) {
  var u = new URL(req.url);
  u.hash = '';
  // версия в адресе — только у ассетов (?v=); у страниц (?trip=) и справок (?cb=) адрес без запроса
  if (u.pathname.indexOf(CAB_BASE + 'assets/') !== 0 || /\.md$/.test(u.pathname)) u.search = '';
  return u.href;
}
function cabPut(cacheName, key, res) {
  return caches.open(cacheName).then(function (c) { return c.put(key, res); }).catch(cabNoop);
}
// После новой версии ассета (?v=) — прежние версии того же файла вон
function cabDropOldVersions(key) {
  var u = new URL(key);
  return caches.open(CAB_SHELL).then(function (c) {
    return c.keys().then(function (ks) {
      return Promise.all(ks.filter(function (k) {
        var x = new URL(k.url);
        return x.pathname === u.pathname && x.search !== u.search;
      }).map(function (k) { return c.delete(k); }));
    });
  }).catch(cabNoop);
}
function cabShellNetFirst(event) {
  var req = event.request, key = cabShellKey(req);
  var net = fetch(req).then(function (r) {
    if (r.ok) cabPut(CAB_SHELL, key, r.clone());
    return r;
  });
  return cabWait(NAV_TIMEOUT_MS).then(function (ms) { return cabRace(net, ms); }).then(function (o) {
    cabNetSeen(o);
    if (o.res && o.res.status < 500) { cabOnlineAgain(); return o.res; }
    return caches.match(key, { cacheName: CAB_SHELL }).then(function (hit) {
      if (hit) {
        // страница из копии, а сеть всё же ответила (поздно) и страница другая — прошлая версия: сказать (1.3.0)
        if (o.late) o.late.then(function (r) {
          if (!r || !r.ok) return null;
          return Promise.all([r.clone().text(), hit.clone().text()]).then(function (t) {
            if (t[0] !== t[1]) cabStale(event, req.url, hit.url || key, key);
          });
        }).catch(cabNoop);
        return hit;
      }
      if (o.res) return o.res;
      if (o.late) return o.late;
      return new Response('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        + '<p style="font-family:sans-serif;padding:40px;text-align:center">Нет связи с сервером, а эта страница '
        + 'ещё не сохранена на устройстве. Открой её один раз при связи.</p>',
        { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
    });
  });
}
// Нужной версии нет (установка не успела докачать: ей отведено 20 с) — ждём сеть ASSET_TIMEOUT_MS: на
// медленной сети страница получает НОВЫЙ код, а не прежнюю версию того же файла. Прежняя версия — только
// когда сеть не ответила вовсе (связи нет, ошибка, 20 с вышли); тогда страницам уходит cab-stale, и ui-kit
// говорит «открыта прошлая версия». Без таймаута страница без связи не открывалась вовсе (1.2.0)
function cabAssetCacheFirst(event) {
  var key = cabShellKey(event.request);
  return caches.match(key, { cacheName: CAB_SHELL }).then(function (hit) {
    if (hit) return hit;
    var net = fetch(event.request).then(function (r) {
      if (r.ok) cabPut(CAB_SHELL, key, r.clone()).then(function () { return cabDropOldVersions(key); });
      return r;
    });
    return cabWait(ASSET_TIMEOUT_MS).then(function (ms) { return cabRace(net, ms); }).then(function (o) {
      cabNetSeen(o);
      if (o.res && o.res.status < 500) { cabOnlineAgain(); return o.res; }
      return cabOldAsset(key).then(function (old) {
        if (old) { cabStale(event, event.request.url, old.url, key); return old.res; }
        if (o.res) return o.res;
        if (o.late) return o.late;
        return Promise.reject(o.err);
      });
    });
  });
}
// Другая версия того же файла из кеша: { res, url } | null
function cabOldAsset(key) {
  return caches.open(CAB_SHELL).then(function (c) {
    return c.keys(key, { ignoreSearch: true }).then(function (ks) {
      if (!ks.length) return null;
      return c.match(ks[0]).then(function (r) { return r ? { res: r, url: ks[0].url } : null; });
    });
  }).catch(function () { return null; });
}
// Страницам: отдана прошлая версия. Сообщение шлём сразу и ещё раз через 3 с — слушатель ui-kit встаёт
// позже скриптов из <head>; тост у ui-kit один, повтор его не множит
function cabStale(event, url, served, wanted) {
  var msg = { type: 'cab-stale', url: url, served: served, wanted: wanted };
  var again = new Promise(function (res) { setTimeout(function () { cabBroadcast(msg).then(res, res); }, 3000); });
  cabBroadcast(msg);
  if (event && event.waitUntil) event.waitUntil(again);
}
function cabAssetRevalidate(event) {
  var key = cabShellKey(event.request);
  return caches.match(key, { cacheName: CAB_SHELL }).then(function (hit) {
    var net = fetch(event.request).then(function (r) {
      if (r.ok) cabPut(CAB_SHELL, key, r.clone());
      return r;
    });
    if (hit) { event.waitUntil(net.catch(cabNoop)); return hit; }
    return net;
  });
}

// Установка: все страницы, их ассеты и шрифты из стилей — офлайн открывается любая страница
function cabCacheUrl(c, url) {
  return fetch(url, { cache: 'no-cache' }).then(function (r) {
    if (!r.ok) return null;
    var copy = r.clone();
    return c.put(url, r).then(function () { return copy; });
  }).catch(function () { return null; });
}
// Предзагрузка без повторов и не больше CAB_PRE_LIMIT запросов разом: страницы → их ассеты → шрифты и
// картинки из стилей. Было — всё разом и с повторами (ui-kit.css на каждой странице → каждый шрифт ×7):
// ~80+ одновременных запросов в момент установки отнимали канал у самой страницы (2026-10-26).
var CAB_PRE_LIMIT = 4;
function cabPool(urls, fn) {
  var i = 0;
  var worker = function () {
    if (i >= urls.length) return Promise.resolve();
    var u = urls[i++];
    return fn(u).then(worker, worker);
  };
  var ws = [];
  for (var k = 0; k < Math.min(CAB_PRE_LIMIT, urls.length); k++) ws.push(worker());
  return Promise.all(ws);
}
function cabPrecache() {
  return caches.open(CAB_SHELL).then(function (c) {
    var seen = {}, assets = [], subs = [];
    var uniq = function (list, u) { if (!seen[u]) { seen[u] = 1; list.push(u); } };
    var pages = CAB_PAGES.map(function (pg) { return new URL(CAB_BASE + pg, self.location).href; });
    pages.forEach(function (u) { seen[u] = 1; });
    return cabPool(pages, function (url) {
      return cabCacheUrl(c, url).then(function (r) {
        if (!r || !/\.html(\?|$)/.test(url)) return null;
        return r.text().then(function (html) {
          (html.match(/(?:src|href)="(assets\/[^"#]+)"/g) || []).forEach(function (m) {
            uniq(assets, new URL(m.replace(/^(?:src|href)="/, '').replace(/"$/, ''), url).href);
          });
        });
      });
    }).then(function () {
      return cabPool(assets, function (a) {
        return cabCacheUrl(c, a).then(function (ar) {
          if (!ar || !/\.css(\?|$)/.test(a)) return null;
          return ar.text().then(function (css) {                       // шрифты и картинки из стилей
            (css.match(/url\(["']?([^"')]+)["']?\)/g) || []).forEach(function (m) {
              var x = new URL(m.replace(/^url\(["']?/, '').replace(/["']?\)$/, ''), a).href;
              if (x.indexOf('data:') !== 0) uniq(subs, x);
            });
          });
        });
      });
    }).then(function () { return cabPool(subs, function (x) { return cabCacheUrl(c, x); }); });
  }).catch(cabNoop);
}

// ─── данные ─────────────────────────────────────────────────────────────────
var cabSaves = 0;
function cabSave(key, res, mark) {
  var status = res.status === 404 ? 404 : 200;
  return (status === 404 ? Promise.resolve(null) : res.blob()).then(function (b) {
    var h = new Headers({ 'Content-Type': res.headers.get('Content-Type') || 'application/octet-stream',
                          'X-Cab-Saved': new Date().toISOString(), 'X-Cab-Mark': mark });
    return cabPut(CAB_DATA, key, new Response(b, { status: status, headers: h }));
  }).then(function () { if (++cabSaves % 50 === 0) return cabTrim(); }).catch(cabNoop);
}
function cabTrim() {
  return caches.open(CAB_DATA).then(function (c) {
    return c.keys().then(function (ks) {
      if (ks.length <= DATA_MAX) return null;
      return Promise.all(ks.map(function (k) {
        return c.match(k).then(function (r) { return { k: k, t: (r && r.headers.get('X-Cab-Saved')) || '' }; });
      })).then(function (all) {
        all.sort(function (a, b) { return a.t < b.t ? -1 : 1; });
        return Promise.all(all.slice(0, all.length - DATA_MAX).map(function (x) { return c.delete(x.k); }));
      });
    });
  }).catch(cabNoop);
}
function cabPurgePrivate() {
  return caches.open(CAB_DATA).then(function (c) {
    return c.keys().then(function (ks) {
      return Promise.all(ks.map(function (k) {
        return c.match(k).then(function (r) { if (r && r.headers.get('X-Cab-Mark')) return c.delete(k); });
      }));
    });
  }).catch(cabNoop);
}
function cabCopy(key, mark) {
  return caches.match(key, { cacheName: CAB_DATA }).then(function (hit) {
    return hit && (hit.headers.get('X-Cab-Mark') || '') === mark ? hit : null;
  }).catch(function () { return null; });
}
function cabOnlineAgain() {
  cabOffGet().then(function (off) {
    if (!off) return;
    cabOffSet(0);
    cabBroadcast({ type: 'cab-online' });
    cabFlush(null);
  });
}
function cabDataNetFirst(event, path) {
  var req = event.request, key = cabDataKey(req);
  var mark = CAB_PRIVATE.test(path) ? cabMark(req.headers.get('Authorization')) : '';
  var net = fetch(req).then(function (r) {
    if (r.ok || r.status === 404) event.waitUntil(cabSave(key, r.clone(), mark));   // 404 — «файла нет», помним
    if (r.ok) cabOnlineAgain();
    else if ((r.status === 401 || r.status === 403) && CAB_PRIVATE.test(path)) event.waitUntil(cabPurgePrivate());
    return r;
  });
  return cabWait(DATA_TIMEOUT_MS).then(function (ms) { return cabRace(net, ms); }).then(function (o) {
    cabNetSeen(o);
    if (o.res && o.res.status < 500) return o.res;            // ответ сервера (в т.ч. 403/404) — как есть
    return cabCopy(key, mark).then(function (hit) {
      if (hit) { cabOffSet(Date.now()); cabNotify(event, path, hit.headers.get('X-Cab-Saved')); return hit; }
      if (o.res) return o.res;                                // 5xx и копии нет
      if (o.late) return o.late;                              // не успел, копии нет — ждём сеть
      return Promise.reject(o.err);                           // нет сети и копии — ошибка, как без нас
    });
  });
}

// ─── очередь записи без связи (1.1.0) ───────────────────────────────────────
// POST /api/save (правки поездок и игр: слой правок в HTML стадий 3–5, чекбоксы подготовки) без связи →
// очередь на устройстве, странице — 200 с временной меткой версии (cabq:…), и она считает правку
// сохранённой. Пока очередь не ушла, GET того же файла (/api/file и сам md) отдаёт СВОЮ версию — после
// перезагрузки без связи правка на месте. Связь появилась (cab-flush от ui-kit: открытие страницы, online,
// возврат в приложение; или первый ответ сервера) — отправка с исходной версией; файл изменился (409) —
// объединение по строкам с копией исходника (cabMerge3): правки на разных строках сливаются, на одной —
// не затираются: запись остаётся в очереди, страницы получают cab-conflict. «Еда» (/api/fd/save) — своя
// очередь в food.html, «Здоровье» (/api/hd/save) — только при связи: их запросы сюда не попадают.
var CAB_OUTBOX = 'cab-outbox-v1';
var CAB_Q = 'cabq:';
function cabOutKey(path) { return 'https://cab.outbox/' + encodeURIComponent(path); }
function cabOutAll() {
  return caches.open(CAB_OUTBOX).then(function (c) {
    return c.keys().then(function (ks) {
      return Promise.all(ks.map(function (k) { return c.match(k).then(function (r) { return r ? r.json() : null; }); }));
    });
  }).then(function (xs) { return xs.filter(Boolean); }).catch(function () { return []; });
}
function cabOutGet(path) {
  return caches.open(CAB_OUTBOX).then(function (c) { return c.match(cabOutKey(path)); })
    .then(function (r) { return r ? r.json() : null; }).catch(function () { return null; });
}
function cabOutPut(e) {
  return caches.open(CAB_OUTBOX).then(function (c) {
    return c.put(cabOutKey(e.path), new Response(JSON.stringify(e), { headers: { 'Content-Type': 'application/json' } }));
  }).catch(cabNoop);
}
function cabOutDel(path) {
  return caches.open(CAB_OUTBOX).then(function (c) { return c.delete(cabOutKey(path)); }).catch(cabNoop);
}
function cabBroadcast(msg) {
  return self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (cs) {
    cs.forEach(function (c) { try { c.postMessage(msg); } catch (x) {} });
  }).catch(cabNoop);
}
function cabJson(obj, status) {
  return new Response(JSON.stringify(obj), { status: status || 200,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Cab-Queued': '1' } });
}
// Исходник правки: копия ответа /api/file с тем же хэшем (её сохранил cabDataNetFirst, когда страница читала файл)
function cabBaseContent(path, hash) {
  if (!hash) return Promise.resolve(null);
  return caches.open(CAB_DATA).then(function (c) {
    return c.keys().then(function (ks) {
      var k = ks.find(function (r) {
        var u = new URL(r.url);
        return u.pathname === '/api/file' && u.searchParams.get('path') === path;
      });
      return k ? c.match(k) : null;
    });
  }).then(function (r) { return r ? r.json() : null; })
    .then(function (j) { return j && j.hash === hash ? j.content : null; }).catch(function () { return null; });
}
function cabQueueSave(event) {
  var req = event.request;
  return req.clone().text().then(function (raw) {
    var b = null;
    try { b = JSON.parse(raw); } catch (x) {}
    if (!b || typeof b.path !== 'string' || typeof b.content !== 'string') return fetch(req);
    return cabOutGet(b.path).then(function (prev) {
      var queue = function () {
        var keepBase = prev && prev.status !== 'conflict';
        var baseHash = keepBase ? prev.base_hash : b.base_hash;
        return (keepBase ? Promise.resolve(prev.base_content) : cabBaseContent(b.path, b.base_hash)).then(function (bc) {
          var e = { path: b.path, content: b.content, base_hash: baseHash, base_content: bc,
                    token: CAB_Q + Date.now().toString(36), auth: req.headers.get('Authorization') || null,
                    t: Date.now(), status: 'queued' };
          return cabOutPut(e).then(function () {
            cabBroadcast({ type: 'cab-queued', path: b.path });
            return cabJson({ path: b.path, hash: e.token, queued: true });
          });
        });
      };
      // правка поверх своей же неотправленной (метка cabq:) — сразу в очередь, к серверу с ней нельзя
      if (prev && typeof b.base_hash === 'string' && b.base_hash.indexOf(CAB_Q) === 0) return queue();
      // без ответа дольше SAVE_TIMEOUT_MS (связи недавно не было — OFF_TIMEOUT_MS) — в очередь; если запрос
      // всё же дойдёт, отправка очереди получит 409, а объединение увидит ту же правку с обеих сторон
      return cabWait(SAVE_TIMEOUT_MS).then(function (ms) { return cabRace(fetch(req), ms); }).then(function (o) {
        cabNetSeen(o);
        if (!o.res) return queue();
        var r = o.res;
        if (r.status >= 502 && r.status <= 504) return queue();
        if (r.ok) cabOnlineAgain();
        if (r.ok && prev) cabOutDel(b.path);                     // сервер принял свежую версию — очередь не нужна
        return r;
      });
    });
  });
}
// Своя версия файла из очереди: /api/file?path=… (JSON) и сам файл по адресу (текст)
function cabQueuedFile(path, asJson) {
  return cabOutGet(path).then(function (e) {
    if (!e || e.status === 'conflict') return null;
    if (asJson) return cabJson({ path: e.path, content: e.content, hash: e.token });
    return new Response(e.content, { headers: { 'Content-Type': 'text/markdown; charset=utf-8', 'X-Cab-Queued': '1' } });
  });
}

// Без связи и без копии /api/file — собрать её из копии самого md (страница стадии читает md при каждом
// открытии): хэш — тот же sha256 hex, что считает сервер (file_hash), поэтому запись с ним пройдёт.
function cabHex(buf) {
  return Array.prototype.map.call(new Uint8Array(buf), function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
}
function cabApiFileFromMd(path) {
  var url = new URL('/' + path.split('/').map(encodeURIComponent).join('/'), self.location).href;
  return caches.match(url, { cacheName: CAB_DATA }).then(function (hit) {
    if (!hit || hit.status !== 200) return null;
    return hit.arrayBuffer().then(function (buf) {
      return crypto.subtle.digest('SHA-256', buf).then(function (d) {
        return cabJson({ path: path, content: new TextDecoder().decode(buf), hash: cabHex(d) });
      });
    });
  }).catch(function () { return null; });
}

// Слияние по строкам: base → mine и base → theirs, куски не пересекаются — применяются оба; пересеклись — null
function cabDiff(a, b) {                                          // → [{s, e, lines}] заменить a[s:e] на lines
  var n = a.length, m = b.length, pre = 0, suf = 0;
  while (pre < n && pre < m && a[pre] === b[pre]) pre++;
  while (suf < n - pre && suf < m - pre && a[n - 1 - suf] === b[m - 1 - suf]) suf++;
  var A = a.slice(pre, n - suf), B = b.slice(pre, m - suf), N = A.length, M = B.length;
  if (!N && !M) return [];
  if (N * M > 4e6) return [{ s: pre, e: n - suf, lines: B }];  // огромная разница — одним куском
  var L = new Uint16Array((N + 1) * (M + 1));                   // LCS с конца
  for (var i = N - 1; i >= 0; i--) for (var j = M - 1; j >= 0; j--)
    L[i * (M + 1) + j] = A[i] === B[j] ? L[(i + 1) * (M + 1) + j + 1] + 1
      : Math.max(L[(i + 1) * (M + 1) + j], L[i * (M + 1) + j + 1]);
  var out = [], x = 0, y = 0, hs = -1, hl = [];
  var flush = function () { if (hs >= 0) { out.push({ s: pre + hs, e: pre + x, lines: hl }); hs = -1; hl = []; } };
  while (x < N || y < M) {
    if (x < N && y < M && A[x] === B[y]) { flush(); x++; y++; }
    else if (y < M && (x === N || L[x * (M + 1) + y + 1] >= L[(x + 1) * (M + 1) + y])) { if (hs < 0) hs = x; hl.push(B[y]); y++; }
    else { if (hs < 0) hs = x; x++; }
  }
  flush();
  return out;
}
function cabMerge3(base, mine, theirs) {
  if (base == null) return null;
  var B = base.split('\n'), h1 = cabDiff(B, mine.split('\n')), h2 = cabDiff(B, theirs.split('\n'));
  var all = h1.map(function (h) { return { s: h.s, e: h.e, lines: h.lines, w: 1 }; })
    .concat(h2.map(function (h) { return { s: h.s, e: h.e, lines: h.lines, w: 2 }; }))
    .sort(function (p, q) { return p.s - q.s || p.e - q.e; });
  for (var i = 1; i < all.length; i++) {
    var p = all[i - 1], q = all[i];
    if (p.w === q.w) continue;
    var same = p.s === q.s && p.e === q.e && p.lines.join('\n') === q.lines.join('\n');
    if (same) { q.dup = true; continue; }
    if (q.s < p.e || (q.s === p.s)) return null;                 // пересеклись или вставки в одно место
  }
  var res = [], at = 0;
  all.forEach(function (h) {
    if (h.dup) return;
    for (; at < h.s; at++) res.push(B[at]);
    Array.prototype.push.apply(res, h.lines);
    at = h.e;
  });
  for (; at < B.length; at++) res.push(B[at]);
  return res.join('\n');
}
var cabFlushing = null;
function cabFlush(auth) {
  if (cabFlushing) return cabFlushing;
  cabFlushing = cabOutAll().then(function (es) {
    var sent = 0, merged = false;
    var post = function (e, content, base, a) {
      var h = { 'Content-Type': 'application/json' };
      if (a) h.Authorization = a;
      return fetch('/api/save', { method: 'POST', headers: h, credentials: 'omit',
                                  body: JSON.stringify({ path: e.path, content: content, base_hash: base }) });
    };
    return es.filter(function (e) { return e.status !== 'conflict'; }).reduce(function (chain, e) {
      return chain.then(function (go) {
        if (!go) return false;
        var a = auth ? 'Basic ' + auth : e.auth;
        return post(e, e.content, e.base_hash, a).then(function (r) {
          if (r.ok) return cabOutDel(e.path).then(function () { sent++; return true; });
          if (r.status === 401 || r.status === 403) { cabBroadcast({ type: 'cab-auth' }); return false; }
          if (r.status !== 409) return r.status >= 500 ? false : true;
          var h = a ? { Authorization: a } : {};
          return fetch('/api/file?path=' + encodeURIComponent(e.path), { headers: h, credentials: 'omit', cache: 'no-store' })
            .then(function (fr) { return fr.ok ? fr.json() : null; })
            .then(function (cur) {
              var m = cur ? cabMerge3(e.base_content, e.content, cur.content) : null;
              if (m == null) {
                e.status = 'conflict';
                return cabOutPut(e).then(function () {
                  cabBroadcast({ type: 'cab-conflict', path: e.path, name: e.path.split('/').pop() });
                  return true;
                });
              }
              return post(e, m, cur.hash, a).then(function (r2) {
                if (!r2.ok) return r2.status >= 500 ? false : true;
                merged = true;
                return cabOutDel(e.path).then(function () { sent++; return true; });
              });
            });
        }, function () { return false; });                      // связи нет — ждём следующего раза
      });
    }, Promise.resolve(true)).then(function () {
      if (sent) cabBroadcast({ type: 'cab-sent', count: sent, merged: merged });
    });
  }).catch(cabNoop).then(function () { cabFlushing = null; });
  return cabFlushing;
}

// ─── обработчики ────────────────────────────────────────────────────────────
self.addEventListener('install', function (e) {
  e.waitUntil(Promise.race([cabPrecache(), new Promise(function (r) { setTimeout(r, 20000); })]));
});
self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (ks) {
    return Promise.all(ks.filter(function (k) { return /^cab-/.test(k) && [CAB_SHELL, CAB_DATA, CAB_OUTBOX, CAB_STATE].indexOf(k) < 0; })
      .map(function (k) { return caches.delete(k); }));
  }).catch(cabNoop));
});
self.addEventListener('message', function (e) {
  var m = e.data || {};
  if (m.type === 'cab-logout') e.waitUntil(cabPurgePrivate().then(function () {
    return cabOutAll().then(function (es) {                       // пароль из очереди — вон, правки остаются
      return Promise.all(es.map(function (x) { x.auth = null; return cabOutPut(x); }));
    });
  }));
  if (m.type === 'cab-flush') e.waitUntil(cabFlush(m.auth || null));
  if (m.type === 'cab-precache') e.waitUntil(cabPrecache());
});
self.addEventListener('fetch', function (e) {
  var req = e.request;
  var u = new URL(req.url);
  if (u.origin !== self.location.origin) return;
  var p = u.pathname;
  if (req.method === 'POST' && p === '/api/save') { e.respondWith(cabQueueSave(e)); return; }
  // сверка вьюера: связи недавно не было — не дольше OFF_TIMEOUT_MS, иначе сетевая ошибка, и вьюер
  // берёт копию с устройства (без этого запрос висел до таймаута вьюера: 2 × 30 с)
  if (req.method === 'POST' && p === '/api/pv/sync') {
    e.respondWith(cabWait(Infinity).then(function (ms) {
      if (ms === Infinity) return fetch(req);
      return cabRace(fetch(req), ms).then(function (o) {
        cabNetSeen(o);
        if (o.res) { if (o.res.ok) cabOnlineAgain(); return o.res; }
        return Response.error();
      });
    }));
    return;
  }
  if (req.method !== 'GET') return;
  // файл с неотправленной правкой — своя версия (страница стадии читает md и через /api/file, и напрямую)
  if (p === '/api/file' || /^\/travel-planner\/.+\.md$/.test(p)) {
    var qpath = p === '/api/file' ? u.searchParams.get('path') : decodeURIComponent(p).replace(/^\/+/, '');
    e.respondWith(cabQueuedFile(qpath, p === '/api/file').then(function (q) {
      if (q) return q;
      var net = cabKeep(p) ? cabDataNetFirst(e, p) : fetch(req);
      if (p !== '/api/file') return net;
      return net.catch(function (err) {
        return cabApiFileFromMd(qpath).then(function (r) { if (r) return r; throw err; });
      });
    }));
    return;
  }
  if (p.indexOf(CAB_BASE) === 0) {
    if (/\/(sw|sw-offline|portfolio-sw)\.js$/.test(p)) return;
    if (p.indexOf(CAB_BASE + 'assets/') === 0) {
      if (/\.md$/.test(p)) e.respondWith(cabShellNetFirst(e));                 // справки страниц
      else e.respondWith(u.searchParams.has('v') ? cabAssetCacheFirst(e) : cabAssetRevalidate(e));
      return;
    }
    if (req.mode === 'navigate' || /\.(html|md)$/.test(p)) e.respondWith(cabShellNetFirst(e));
    return;
  }
  if (cabKeep(p)) e.respondWith(cabDataNetFirst(e, p));
});
