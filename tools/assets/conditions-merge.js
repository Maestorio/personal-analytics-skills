/* conditions-merge.js — модуль (а) схемы данных: объединение «определение условия + состояние условия»
 * (docs/investment/_cross-cutting/data-structures/schema.md §1 п.3, §3.3). JS-близнец
 * _shared-references/conditions_merge.py: CM.merge(defs, state, today) отдаёт те же плоские строки — поля,
 * значения, коды и порядок, — что Python merge(); CM.select(rows, key) — фильтр по ключу бумаги.
 * Паритет (JSON-дамп с сортировкой ключей, байт в байт) и равенство текста правил ниже докстрингу Python
 * держит tools/tests/test_conditions_merge_parity.py. Меняешь правило — меняй в обоих местах.
 *
 * Вход — уже разобранные объекты: defs — список определений conditions@2 (любые версии), state — документ
 * conditions-state@1, today — 'YYYY-MM-DD'. Даты и время во входе — СТРОКИ (правило 1): YAML разбирает
 * вызывающий так, чтобы даты не становились Date. Кодлисты — window.CL (assets/codelists.js подключён раньше)
 * или require('./codelists.js') в node. Ни DOM, ни сети. Python-истинность (пустой объект/список/строка = ложь)
 * повторена функцией truthy(), отсутствующее поле в выдаче — null, как None у Python.
 *
 * ПРАВИЛА (спецификация для JS)
 *  1. Время сравнивается как строка: везде формат YYYY-MM-DDTHH:MM:SS+03:00 (один пояс), даты —
 *     YYYY-MM-DD; лексикографический порядок = хронологический.
 *  2. Для каждого id берётся определение с наибольшим `version` («последняя версия»). Остальные версии
 *     в результат не попадают. При равной `version` остаётся первое по порядку в файле.
 *  3. События состояния по id берутся любой версии, сортируются по (`at`, порядок в файле) — устойчиво.
 *     Поле `version` события необязательно и модулем не читается (связь только по condition_id).
 *  4. Событие `reopened` (пишет сайт по кнопке владельца) сбрасывает всё: статус и отметки считаются
 *     только по событиям ПОСЛЕ последнего `reopened`; событий после него нет -> pending.
 *     Само `reopened` остаётся последним реальным событием (last_event), если после него ничего нет.
 *  5. Статус из событий (после правила 4) проходом по порядку, начиная с `pending`:
 *       fired        : pending -> fired (fired_at = первое fired). Пересечение ценового порога пишет
 *                      уведомитель как fired; находку монитора (event_found) задача на NAS переносит двумя
 *                      событиями: event_found и fired (с data.doc).
 *       expired      : pending -> expired (после fired/done игнорируется).
 *       done         : pending|fired -> done (после expired остаётся expired). done пишет сайт (кнопка
 *                      «сделал», by=owner; отдельной отметки «сделал» в owner_mark нет), либо задача на NAS:
 *                      новое решение в decisions/ с conditions_resolved[], содержащим id условия в статусе
 *                      fired -> done с data.decision_id; либо сделка (data.trade_date).
 *       owner_mark   : data.mark = dismissed («не актуально») -> как done, closed_as = dismissed;
 *                      deferred («отложить») -> при status fired запоминает until; статус остаётся fired.
 *       event_found  : даёт found_at и found_doc (data.doc), попадает в last_event; статус меняет только
 *                      отметка владельца (by = owner, кнопка «вышел» на сайте): pending -> fired, fired_at = её at;
 *                      от остальных авторов статус НЕ меняет (их находку переносят отдельным fired).
 *     Отсрочка (deferred) учитывается, если это последняя отметка deferred после первого fired
 *     (для вычисленного по сроку fired — любая отметка); deferred_until = её data.until.
 *  6. Вычисление при чтении (`today` — дата YYYY-MM-DD). Только если статус из событий pending:
 *       а) trigger.type == report_published и trigger.window_end < today (окно включает последний день) ->
 *          status = fired, fired_by_deadline = true, fired_at = window_end + "T23:59:59+03:00" (решение владельца);
 *       б) trigger.type == date и trigger.value <= today (дата срабатывает В ДЕНЬ события, как у notifier.py)
 *          -> fired, fired_by_deadline = true, fired_at = value + "T00:00:00+03:00";
 *       в) иначе, если valid_until < today -> status = expired (для price_* дедлайна нет, только это правило).
 *     Вычисленный статус помечается computed = true; last_event остаётся последним РЕАЛЬНЫМ событием.
 *     fired/expired/done из событий дедлайнами не перекрываются.
 *     ОГОВОРКА: событие fired от уведомителя первично; вычисление по сроку при чтении — страховка на случай,
 *     когда проход уведомителя ещё не записал событие. Расхождение fired_at между вычисленным и записанным
 *     допустимо; вычисленное помечено computed = true и исчезает, как только событие записано.
 *  7. state_status = статус по правилам 4–6 (до учёта снятия определения).
 *  8. Снятие: если последняя версия определения имеет withdrawn != null -> status = "withdrawn",
 *     withdrawn_at = withdrawn.at; state_status сохраняет живое состояние («снято, было fired»).
 *  9. active = определение не снято И status in {pending, fired}.
 *     waits_owner = active И status == fired И нет действующей отсрочки (deferred_until is null или today >= deferred_until).
 *     expired и done закрыты (active = false). Пока today < deferred_until, waits_owner = false, статус остаётся fired.
 * 10. Если status == expired, в выдаче поле `on_expiry` (из определения целиком, иначе null): вьюер показывает
 *     «срок вышел: <действие>». Для остальных статусов on_expiry тоже отдаётся как есть.
 * 11. Результат — плоские словари с полями: id, version, key, key_kind (isin | ticker — по ISIN-регулярке на всю
 *     строку ключа, в данных не хранится), kind, trigger, status, state_status, active, waits_owner, computed, fired_by_deadline, closed_as, deferred_until, last_event{event, at, by} | null,
 *     fired_at, found_at, found_doc, verdict_now (while_pending.verdict), verdict_on_trigger, target_pct_on_trigger,
 *     action_code, target (on_trigger.target), amount_source (on_trigger.amount_source), on_expiry, not_before,
 *     valid_until, window_end, withdrawn_at, text (on_trigger.text), note. Модуль их не считает: несёт как есть.
 * 12. Порядок результата детерминирован: по (key, id).
 * 13. События с condition_id, которого нет в определениях, в результат не попадают (см. orphan_event_ids).
 * 14. Новая версия определения начинает состояние заново. Для статуса и отметок учитываются только события с `at` ≥
 *     `created_at` последней версии определения; события раньше остаются в истории прежних версий. Если у последней
 *     версии `created_at` отсутствует — учитываются все события. last_event, found_at и found_doc — тоже только по ним.
 */
(function (root) {
  "use strict";

  var CL = (root && root.CL) || (typeof require === "function" ? require("./codelists.js") : null);
  if (!CL) throw new Error("conditions-merge: нет кодлистов (assets/codelists.js не подключён раньше)");

  // код из кодлиста; нет такого кода (не-legacy) — ошибка при загрузке, а не тихий пропуск
  function code(list, c) {
    if (CL.codes(list, false).indexOf(c) < 0) throw new Error("conditions-merge: в кодлисте " + list + " нет кода " + c);
    return c;
  }
  var EV_FIRED = code("condition_event", "fired");
  var EV_EXPIRED = code("condition_event", "expired");
  var EV_DONE = code("condition_event", "done");
  var EV_OWNER_MARK = code("condition_event", "owner_mark");
  var EV_EVENT_FOUND = code("condition_event", "event_found");
  var EV_REOPENED = code("condition_event", "reopened");
  var BY_OWNER = code("actor", "owner");
  var MARK_DISMISSED = code("owner_mark", "dismissed");
  var MARK_DEFERRED = code("owner_mark", "deferred");
  var TRIGGER_DATE = code("condition_trigger_type", "date");
  var TRIGGER_REPORT = code("condition_trigger_type", "report_published");
  var HANDLED_EVENTS = [EV_FIRED, EV_EXPIRED, EV_DONE, EV_OWNER_MARK, EV_EVENT_FOUND, EV_REOPENED];
  var HANDLED_MARKS = [MARK_DISMISSED, MARK_DEFERRED];

  // статусы выдачи (словарь модуля, правила 5–8)
  var PENDING = "pending", FIRED = "fired", EXPIRED = "expired", DONE = "done", WITHDRAWN = "withdrawn";
  var ISIN_RE = /^[A-Z]{2}[A-Z0-9]{9}[0-9]$/;

  // истинность по правилам Python: None/False/0/""/[]/{} — ложь
  function truthy(v) {
    if (v === null || v === undefined || v === false || v === 0 || v === "") return false;
    if (Array.isArray(v)) return v.length > 0;
    if (typeof v === "object") return Object.keys(v).length > 0;
    return true;
  }
  function or(v, dflt) { return truthy(v) ? v : dflt; }   // `v or dflt`
  function get(o, k) { var v = o[k]; return v === undefined ? null : v; }   // dict.get(k) -> None
  function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }

  // время с поясом МСК (как time_msk.day_start_iso / day_end_iso)
  function dayStart(d) { return String(d).slice(0, 10) + "T00:00:00+03:00"; }
  function dayEnd(d) { return String(d).slice(0, 10) + "T23:59:59+03:00"; }

  function keyKind(key) { return typeof key === "string" && ISIN_RE.test(key) ? "isin" : "ticker"; }

  // правило 2: id -> определение с максимальной version; при равной version — первое
  function lastDefs(defs) {
    var last = {}, order = [];
    or(defs, []).forEach(function (d) {
      if (!has(last, d.id)) { last[d.id] = d; order.push(d.id); }
      else if (d.version > last[d.id].version) last[d.id] = d;
    });
    return { map: last, order: order };
  }

  // правило 3: id -> события, устойчиво по (at, позиция в файле)
  function eventsById(state) {
    var out = {};
    or(or(state, {}).events, []).forEach(function (e, idx) {
      if (!has(out, e.condition_id)) out[e.condition_id] = [];
      out[e.condition_id].push({ at: e.at, idx: idx, e: e });
    });
    Object.keys(out).forEach(function (cid) {
      out[cid] = out[cid].sort(function (a, b) {
        if (a.at < b.at) return -1;
        if (a.at > b.at) return 1;
        return a.idx - b.idx;
      }).map(function (x) { return x.e; });
    });
    return out;
  }

  // правила 4–5
  // правило 14: события не раньше created_at последней версии; нет created_at — все
  function eventsSince(events, createdAt) {
    if (!truthy(createdAt)) return events;
    return events.filter(function (e) { return e.at >= createdAt; });
  }

  function foldEvents(events) {
    var n = events.length;
    var lastReal = n ? { event: events[n - 1].event, at: events[n - 1].at, by: get(events[n - 1], "by") } : null;
    for (var i = n - 1; i >= 0; i--) {
      if (events[i].event === EV_REOPENED) { events = events.slice(i + 1); break; }
    }
    var status = PENDING, firedAt = null, foundAt = null, foundDoc = null, closedAs = null;
    var deferAfterFire = null, deferAny = null;
    events.forEach(function (e) {
      var ev = e.event, data = or(get(e, "data"), {});
      if (ev === EV_FIRED) {
        if (status === PENDING) { status = FIRED; firedAt = e.at; }
      } else if (ev === EV_EXPIRED) {
        if (status === PENDING) status = EXPIRED;
      } else if (ev === EV_DONE) {
        if (status === PENDING || status === FIRED) { status = DONE; closedAs = EV_DONE; }
      } else if (ev === EV_OWNER_MARK) {
        var mark = get(data, "mark");
        if (mark === MARK_DISMISSED) {
          if (status === PENDING || status === FIRED) { status = DONE; closedAs = mark; }
        } else if (mark === MARK_DEFERRED) {
          deferAny = get(data, "until");
          if (status === FIRED) deferAfterFire = get(data, "until");
        }
      } else if (ev === EV_EVENT_FOUND) {
        if (foundAt === null) { foundAt = e.at; foundDoc = get(data, "doc"); }
        if (get(e, "by") === BY_OWNER && status === PENDING) { status = FIRED; firedAt = e.at; }
      }
    });
    return { status: status, fired_at: firedAt, found_at: foundAt, found_doc: foundDoc,
             defer_after_fire: deferAfterFire, defer_any: deferAny, closed_as: closedAs, last_event: lastReal };
  }

  // правило 6: [status, fired_at, computed, fired_by_deadline]
  function applyDeadlines(folded, trigger, validUntil, today) {
    var status = folded.status, firedAt = folded.fired_at;
    if (status === PENDING) {
      trigger = or(trigger, {});
      var tt = get(trigger, "type");
      if (tt === TRIGGER_REPORT && truthy(get(trigger, "window_end")) && trigger.window_end < today)
        return [FIRED, dayEnd(trigger.window_end), true, true];
      if (tt === TRIGGER_DATE && truthy(get(trigger, "value")) && trigger.value <= today)
        return [FIRED, dayStart(trigger.value), true, true];
      if (truthy(validUntil) && validUntil < today) return [EXPIRED, firedAt, true, false];
    }
    return [status, firedAt, false, false];
  }

  function merge(defs, state, today) {
    var evById = eventsById(state);
    var ld = lastDefs(defs);
    var result = ld.order.map(function (cid) {
      var d = ld.map[cid];
      var folded = foldEvents(eventsSince(has(evById, cid) ? evById[cid] : [], get(d, "created_at")));
      var trigger = or(get(d, "trigger"), {});
      var dl = applyDeadlines(folded, trigger, get(d, "valid_until"), today);
      var live = dl[0], firedAt = dl[1], computed = dl[2], byDeadline = dl[3];
      var deferredUntil = null;
      if (live === FIRED) deferredUntil = computed ? folded.defer_any : folded.defer_after_fire;
      var wd = get(d, "withdrawn");
      var status = truthy(wd) ? WITHDRAWN : live;
      var active = !truthy(wd) && (live === PENDING || live === FIRED);
      var deferredNow = truthy(deferredUntil) && today < deferredUntil;
      var onTrigger = or(get(d, "on_trigger"), {});
      return {
        id: cid,
        version: d.version,
        key: d.key,
        key_kind: keyKind(d.key),
        kind: get(d, "kind"),
        trigger: trigger,
        status: status,
        state_status: live,
        active: active,
        waits_owner: active && live === FIRED && !deferredNow,
        computed: computed,
        fired_by_deadline: byDeadline,
        closed_as: live === DONE ? folded.closed_as : null,
        deferred_until: deferredUntil,
        last_event: folded.last_event,
        fired_at: firedAt,
        found_at: folded.found_at,
        found_doc: folded.found_doc,
        verdict_now: get(or(get(d, "while_pending"), {}), "verdict"),
        verdict_on_trigger: get(onTrigger, "verdict"),
        target_pct_on_trigger: get(onTrigger, "target_pct"),
        action_code: get(onTrigger, "action"),
        target: get(onTrigger, "target"),
        amount_source: get(onTrigger, "amount_source"),
        on_expiry: get(d, "on_expiry"),
        not_before: get(d, "not_before"),
        valid_until: get(d, "valid_until"),
        window_end: get(trigger, "window_end"),
        withdrawn_at: truthy(wd) ? get(wd, "at") : null,
        text: get(onTrigger, "text"),
        note: get(d, "note")
      };
    });
    // правило 12: по (key, id), сравнение строк по кодам символов, как у Python
    result.sort(function (a, b) {
      if (a.key !== b.key) return a.key < b.key ? -1 : 1;
      if (a.id !== b.id) return a.id < b.id ? -1 : 1;
      return 0;
    });
    return result;
  }

  // фильтр выдачи: key — строка или список ключей (пусто — все); onlyActive — только действующие; порядок сохраняется
  function select(rows, key, onlyActive) {
    var ks = key == null || key === "" ? null : (Array.isArray(key) ? (key.length ? key : null) : [key]);
    return (rows || []).filter(function (r) {
      return (ks === null || ks.indexOf(r.key) >= 0) && (!onlyActive || r.active);
    });
  }

  // правило 13: id из событий, которых нет в определениях
  function orphanEventIds(defs, state) {
    var known = {};
    or(defs, []).forEach(function (d) { known[d.id] = true; });
    var seen = {};
    or(or(state, {}).events, []).forEach(function (e) { if (!has(known, e.condition_id)) seen[e.condition_id] = true; });
    return Object.keys(seen).sort(function (a, b) { return a < b ? -1 : (a > b ? 1 : 0); });
  }

  var CM = { merge: merge, select: select, orphanEventIds: orphanEventIds, keyKind: keyKind,
             HANDLED_EVENTS: HANDLED_EVENTS, HANDLED_MARKS: HANDLED_MARKS };
  root.CM = CM;
  if (typeof module !== "undefined" && module.exports) module.exports = CM;
})(typeof window !== "undefined" ? window : (typeof globalThis !== "undefined" ? globalThis : this));
