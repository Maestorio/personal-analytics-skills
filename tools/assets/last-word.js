/* last-word.js — модуль (б) схемы данных: «последнее слово» по бумаге и статус гейта
 * (docs/investment/_cross-cutting/data-structures/schema.md §1 п.3, §3.5; decision.md R4/R5). JS-близнец
 * _shared-references/last_word.py: LW.card(ctx, key) и LW.cards(ctx, keys) отдают те же карточки — поля, значения,
 * коды и порядок, — что Python card()/cards(). Паритет (JSON-дамп с сортировкой ключей, байт в байт) и равенство
 * текста правил ниже докстрингу Python держит tools/tests/test_last_word_parity.py. Меняешь правило — меняй в обоих местах.
 *
 * Вход ctx — уже разобранные объекты (форма — в докстринге Python): today, decisions, reviews, security_attrs,
 * snapshot_keys, stock_keys, first_buy, plan, last_trade_at, last_sell_at, last_buy_at, buys_at, maturities, ai_mode ('on' по умолчанию). Даты и время — СТРОКИ. Кодлисты — window.CL
 * (assets/codelists.js подключён раньше) или require('./codelists.js') в node. Ни DOM, ни сети. Python-истинность
 * повторена функцией truthy(), отсутствующее поле — null, как None у Python.
 *
 * ПРАВИЛА (спецификация для JS)
 *  1. Время сравнивается как строка: везде YYYY-MM-DDTHH:MM:SS+03:00 (один пояс), даты — YYYY-MM-DD;
 *     лексикографический порядок = хронологический. «Что новее» — только по recorded_at.
 *  2. Источники ключа: решения с key = ключ и строки reviews[ключ] с непустыми recorded_at и advisor_verdict
 *     (строка без них источником не считается). Порядок источников — по (recorded_at, вид, id), вид: обзор раньше
 *     решения — при равном времени решение новее обзора. id решения — id, строки обзора — doc, без него — review_date.
 *  3. Последнее слово — новейший источник: verdict; direction = verdict_direction[verdict] (нет кода — null);
 *     confidence и basis (у решения — confidence и note, у обзора — advisor_verdict_confidence и advisor_verdict_basis);
 *     verdict_source {kind: decision | review, id, recorded_at}. Источников нет — все эти поля null.
 *  4. Только из новейшего решения: decision_verdict, target_pct, review_by (как записан), decision_id,
 *     decision_recorded_at, conditions_created, conditions_resolved (решения нет — null и пустые списки).
 *     review_recorded_at — recorded_at новейшей строки обзора (нет — null). Обзор эти поля не несёт и не стирает.
 *  5. Гейт только для акций: ключа нет в stock_keys -> gate.applicable = false, status null, expired false, даты null,
 *     blocking false, reasons []. Дальше — только для акций.
 *  6. Срок: expires_on = review_by новейшего решения, null -> дата recorded_at + defaults.review_days;
 *     expired = expires_on < today. Решения нет — expires_on null, expired false.
 *     Статус — первое подходящее:
 *       а) ключа нет в snapshot_keys и нет в first_buy -> divested;
 *       б) ключ в first_buy и решения нет -> new_position;
 *       в) есть строка обзора с gate_review_required = true новее новейшего решения (решения нет — любая) -> review_needed;
 *       г) решения нет -> null (держимая бумага без решения не блокируется);
 *       д) expired -> review_aging; иначе verdict_to_gate[вердикт новейшего решения].
 *  7. Пауза докупки — от первой покупки после решения: d — дата recorded_at новейшего решения с вердиктом BUY или ADD;
 *     b — первая покупка по ключу после него: наименьшее из buys_at[ключ] с датой ≥ d (покупка в день решения — по нему:
 *     времена покупок — дни снапшотов, порядок внутри дня неизвестен); списка buys_at[ключ] нет — last_buy_at[ключ] с датой
 *     ≥ d (последняя покупка; при одной покупке после решения — она же первая). b нет -> паузы нет (решение без покупки
 *     докупку не закрывает). Иначе конец = дата b + defaults.add_cooldown_days; add_cooldown_until = конец, если
 *     today < конец, иначе null.
 *  8. IPO-пауза: в справочнике security_attrs.by_key[ключ] ticker_class = ipo и listed_at не null -> конец = listed_at +
 *     3 × defaults.ipo_pause_quarters месяцев (день — не больше длины месяца); ipo_pause_until = конец, если конец > today,
 *     иначе null. Возраст q — полных кварталов: наибольшее q, при котором listed_at + 3q месяцев ≤ today.
 *     Действует при любом вердикте и у первой покупки.
 *  9. reasons по порядку: «gate:<status>», если status есть в карте gate_to_block; «ipo_gate:<q>q» при ipo_pause_until;
 *     «add_cooldown:<add_cooldown_until>» при паузе. У divested пауз и причин нет (бумаги нет).
 *     blocking = reasons непуст. Режим «без ИИ» (ai_mode = off) блокирует теми же статусами, что и «с ИИ» (решение 11.11): снимает
 *     блок не разбор советника, а решение владельца (правило 9а при off не действует). Флаг defaults.noai_gate_blocks = false
 *     оставлен на случай отката: тогда при off «gate:<status>» уходит из reasons в warnings (тот же текст).
 *  9а. При on гейт считается дважды: по всем решениям и без решений с source.kind = owner (решение владельца с сайта
 *     докупку, закрытую гейтом, не открывает — только разбор советника; закрыть может). Итог — строже: reasons —
 *     объединение без дублей (gate: впереди); если gate: даёт только вариант без решений владельца — status, expired,
 *     expires_on и gate:-причина из него (срок разбора), owner_pending_review = true; иначе всё из первого. При off и без
 *     решений владельца — один расчёт, owner_pending_review = false.
 * 10. Конфликт (R5). Хвост — наибольший конечный отрезок источников с тем же direction, что у новейшего; S — первый
 *     источник хвоста, P — источник перед S. Конфликт есть, если P существует, вид P ≠ вид S и direction обоих не null;
 *     иначе conflict = null. conflict = {at: S.recorded_at, source: {kind, id, recorded_at, verdict, direction} S,
 *     against: то же для P, open, closed_by, closed_at}. Закрытие — самое раннее из: confirmed — второй источник хвоста
 *     (следующий источник подтвердил направление; его recorded_at); plan — plan[ключ].changed_at > at (владелец правил
 *     план после конфликта); trade — last_trade_at[ключ] > at (сделка после конфликта, «закрыто сделкой, без
 *     подтверждения»). При равном времени порядок confirmed, plan, trade. Нет закрытия — open = true, closed_by и
 *     closed_at null. Срока давности нет.
 * 11. План против решения. plan_direction: у плана BALANCE («привести к плану») — по знаку отклонения факта от плана:
 *     f = plan[ключ].fact_pct, p = plan[ключ].plan_pct (числа, считает вызывающий), t = defaults.plan_tolerance_pp
 *     (гистерезис плана): f > p + t -> down, f < p − t -> up, иначе flat; f или p нет -> null; у остальных планов —
 *     user_plan_direction[user_plan] (BALANCE в карте — flat «по умолчанию», правилом не читается). plan_direction и
 *     direction последнего слова оба не null и различны -> plan_vs_decision = {user_plan, plan_direction, verdict,
 *     direction, source_kind}; иначе null.
 * 12. Карточка — плоский словарь: key, verdict, direction, confidence, basis, verdict_source, decision_verdict,
 *     target_pct, review_by, decision_id, decision_recorded_at, review_recorded_at, conditions_created,
 *     conditions_resolved, gate {applicable, status, expired, expires_on, add_cooldown_until, ipo_pause_until, blocking,
 *     reasons, warnings, owner_pending_review}, conflict, plan_vs_decision, executed_by_trade_at, executed_source_kind, decision_executed_at, held, left_at, left_kind. cards — карточки по ключам
 *     в порядке ключа; ключи — переданный список, иначе объединение ключей решений, reviews, snapshot_keys и first_buy.
 * 13. Исполнение сделкой — по источнику последнего слова (verdict_source: решение или обзор): direction = down и
 *     last_sell_at[ключ] > его recorded_at -> executed_by_trade_at = last_sell_at[ключ]; direction = up и
 *     last_buy_at[ключ] > его recorded_at -> executed_by_trade_at = last_buy_at[ключ]; иначе null (источника нет,
 *     направление flat или null, сделки в ту сторону после него нет). executed_source_kind = вид этого источника
 *     (decision | review), если executed_by_trade_at не null, иначе null. Отдельно decision_executed_at — то же правило
 *     для новейшего решения (решения нет — null), даже если последнее слово — обзор: строка разбора и «Сделано» по
 *     решению. Уход бумаги из снапшота — тоже уменьшение количества. Гейт, срок, паузы и причины признак не меняет:
 *     решение действует до review_by, что показывать — дело вызывающего.
 * 14. Есть в портфеле (все классы, независимо от gate.applicable): held = ключ в snapshot_keys. Ушла — ключа нет
 *     в snapshot_keys и в first_buy, и есть last_sell_at[ключ] или дата погашения m = maturities[ключ] ≤ today; тогда
 *     left_at = last_sell_at[ключ] (нет — null), left_kind = redeemed, если m есть и (left_at не null и дата left_at ≥ m,
 *     или left_at null), иначе sold (у акций и фондов дат погашения нет — всегда sold). Не ушла (держится, первая
 *     покупка или в известной истории не держалась) — left_at и left_kind null. Гейт признак не меняет: divested акций —
 *     правило 6а.
 */
(function (root) {
  "use strict";

  var CL = (root && root.CL) || (typeof require === "function" ? require("./codelists.js") : null);
  if (!CL) throw new Error("last-word: нет кодлистов (assets/codelists.js не подключён раньше)");

  function gateCode(c) {
    if (CL.codes("gate_status", false).indexOf(c) < 0) throw new Error("last-word: в кодлисте gate_status нет кода " + c);
    return c;
  }
  var VERDICT_TO_GATE = CL.map("verdict_to_gate");
  var VERDICT_DIRECTION = CL.map("verdict_direction");
  var PLAN_DIRECTION = CL.map("user_plan_direction");
  var GATE_TO_BLOCK = CL.map("gate_to_block");
  var D = CL.defaults();
  var REVIEW_DAYS = D.review_days, ADD_COOLDOWN_DAYS = D.add_cooldown_days, IPO_PAUSE_QUARTERS = D.ipo_pause_quarters;
  var NOAI_GATE_BLOCKS = D.noai_gate_blocks === true;
  var PLAN_TOLERANCE_PP = D.plan_tolerance_pp, BALANCE = "BALANCE";
  var ADD_VERDICTS = ["BUY", "ADD"];
  var IPO_CLASS = "ipo";
  var DIVESTED = gateCode("divested"), NEW_POSITION = gateCode("new_position");
  var REVIEW_NEEDED = gateCode("review_needed"), REVIEW_AGING = gateCode("review_aging");
  var KIND_DECISION = "decision", KIND_REVIEW = "review";
  var KIND_ORDER = { review: 0, decision: 1 };   // правило 2: при равном времени решение новее

  // истинность по правилам Python: None/False/0/""/[]/{} — ложь
  function truthy(v) {
    if (v === null || v === undefined || v === false || v === 0 || v === "") return false;
    if (Array.isArray(v)) return v.length > 0;
    if (typeof v === "object") return Object.keys(v).length > 0;
    return true;
  }
  function or(v, dflt) { return truthy(v) ? v : dflt; }
  function get(o, k) { if (o === null || o === undefined) return null; var v = o[k]; return v === undefined ? null : v; }
  function has(o, k) { return o !== null && o !== undefined && Object.prototype.hasOwnProperty.call(o, k); }
  function cmp(a, b) { return a < b ? -1 : (a > b ? 1 : 0); }
  function setOf(list) { var s = {}; or(list, []).forEach(function (k) { s[k] = true; }); return s; }
  function mapGet(m, k) { return has(m, k) ? m[k] : null; }   // dict.get(k) по карте кодлиста

  function day(iso) { return String(iso).slice(0, 10); }
  function pad(n, w) { var s = String(n); while (s.length < w) s = "0" + s; return s; }
  function ymd(y, m, d) { return pad(y, 4) + "-" + pad(m, 2) + "-" + pad(d, 2); }
  function parts(iso) { var s = day(iso); return [+s.slice(0, 4), +s.slice(5, 7), +s.slice(8, 10)]; }
  function addDays(iso, n) {
    var p = parts(iso), t = new Date(Date.UTC(p[0], p[1] - 1, p[2] + n));
    return ymd(t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate());
  }
  // дата + n месяцев; день не больше длины месяца (правило 8)
  function addMonths(iso, n) {
    var p = parts(iso), total = p[1] - 1 + n;
    var y = p[0] + Math.floor(total / 12), m = ((total % 12) + 12) % 12 + 1;
    var last = new Date(Date.UTC(y, m, 0)).getUTCDate();
    return ymd(y, m, Math.min(p[2], last));
  }

  function direction(v) { return truthy(v) ? mapGet(VERDICT_DIRECTION, v) : null; }

  // правило 2: источники ключа по (recorded_at, вид, id)
  function sources(ctx, key) {
    var out = [];
    or(get(ctx, "decisions"), []).forEach(function (d) {
      if (get(d, "key") !== key) return;
      out.push({ kind: KIND_DECISION, id: or(get(d, "id"), ""), recorded_at: d.recorded_at, verdict: get(d, "verdict"),
                 confidence: get(d, "confidence"), basis: get(d, "note"), flag: false, doc: d });
    });
    var revs = or(get(ctx, "reviews"), {});
    or(get(revs, key), []).forEach(function (r) {
      if (!truthy(get(r, "recorded_at")) || !truthy(get(r, "advisor_verdict"))) return;
      out.push({ kind: KIND_REVIEW, id: or(get(r, "doc"), or(get(r, "review_date"), "")), recorded_at: r.recorded_at,
                 verdict: get(r, "advisor_verdict"), confidence: get(r, "advisor_verdict_confidence"),
                 basis: get(r, "advisor_verdict_basis"), flag: get(r, "gate_review_required") === true, doc: null });
    });
    out.sort(function (a, b) {
      return cmp(a.recorded_at, b.recorded_at) || (KIND_ORDER[a.kind] - KIND_ORDER[b.kind]) || cmp(a.id, b.id);
    });
    return out;
  }

  function brief(s) {
    return { kind: s.kind, id: s.id, recorded_at: s.recorded_at, verdict: s.verdict, direction: direction(s.verdict) };
  }

  // правило 8: [ipo_pause_until, q] или [null, null]
  function ipo(ctx, key, today) {
    var attrs = or(get(or(get(or(get(ctx, "security_attrs"), {}), "by_key"), {}), key), {});
    var listed = get(attrs, "listed_at");
    if (get(attrs, "ticker_class") !== IPO_CLASS || !truthy(listed)) return [null, null];
    var end = addMonths(listed, 3 * IPO_PAUSE_QUARTERS);
    if (!(end > today)) return [null, null];
    var q = 0;
    while (q < IPO_PAUSE_QUARTERS && addMonths(listed, 3 * (q + 1)) <= today) q++;
    return [end, q];
  }

  function isOwner(doc) { return get(or(get(doc, "source"), {}), "kind") === "owner"; }
  function gateCodes(reasons) { return reasons.filter(function (r) { return r.indexOf("gate:") === 0; }); }
  function uniq(list) { var seen = {}; return list.filter(function (x) { if (seen[x]) return false; seen[x] = true; return true; }); }

  // правило 9а: при on гейт — строже из двух (все решения / без решений владельца)
  function gate(ctx, key, today, decision, srcs) {
    var a = gateCore(ctx, key, today, decision, srcs);
    if (get(ctx, "ai_mode") === "off" || !a.applicable) return a;
    if (!srcs.some(function (s) { return s.kind === KIND_DECISION && isOwner(s.doc); })) return a;
    var srcsB = srcs.filter(function (s) { return !(s.kind === KIND_DECISION && isOwner(s.doc)); });
    var decsB = srcsB.filter(function (s) { return s.kind === KIND_DECISION; }).map(function (s) { return s.doc; });
    var b = gateCore(ctx, key, today, decsB.length ? decsB[decsB.length - 1] : null, srcsB);
    var gb = gateCodes(b.reasons);
    if (!gb.length) return a;
    var ga = gateCodes(a.reasons);
    var rest = a.reasons.filter(function (r) { return r.indexOf("gate:") !== 0; });
    if (ga.length) { a.reasons = uniq(ga.concat(gb)).concat(rest); return a; }
    a.status = b.status; a.expired = b.expired; a.expires_on = b.expires_on;
    a.reasons = gb.concat(rest);
    a.blocking = true;
    a.owner_pending_review = true;
    return a;
  }

  // правило 7: первая покупка по ключу с датой ≥ d (buys_at; списка нет — last_buy_at) или null
  function firstBuyAfter(ctx, key, d) {
    var buys = get(get(ctx, "buys_at"), key);
    if (buys === null) { var lb = get(get(ctx, "last_buy_at"), key); buys = truthy(lb) ? [lb] : []; }
    var after = buys.filter(function (b) { return truthy(b) && day(b) >= d; }).map(day).sort();
    return after.length ? after[0] : null;
  }

  // правила 5–9
  function gateCore(ctx, key, today, decision, srcs) {
    var g = { applicable: false, status: null, expired: false, expires_on: null, add_cooldown_until: null,
              ipo_pause_until: null, blocking: false, reasons: [], warnings: [], owner_pending_review: false };
    if (!setOf(get(ctx, "stock_keys"))[key]) return g;
    g.applicable = true;
    if (decision !== null) {
      g.expires_on = or(get(decision, "review_by"), addDays(decision.recorded_at, REVIEW_DAYS));
      g.expired = g.expires_on < today;
    }
    var inSnap = !!setOf(get(ctx, "snapshot_keys"))[key];
    var first = !!setOf(get(ctx, "first_buy"))[key];
    var dAt = decision !== null ? decision.recorded_at : null;
    var flagged = srcs.some(function (s) { return s.kind === KIND_REVIEW && s.flag && (dAt === null || s.recorded_at > dAt); });
    if (!inSnap && !first) { g.status = DIVESTED; return g; }
    if (first && decision === null) g.status = NEW_POSITION;
    else if (flagged) g.status = REVIEW_NEEDED;
    else if (decision === null) g.status = null;
    else if (g.expired) g.status = REVIEW_AGING;
    else g.status = mapGet(VERDICT_TO_GATE, decision.verdict);
    var adds = srcs.filter(function (s) { return s.kind === KIND_DECISION && ADD_VERDICTS.indexOf(s.verdict) >= 0; });
    var buy = adds.length ? firstBuyAfter(ctx, key, day(adds[adds.length - 1].doc.recorded_at)) : null;
    if (buy !== null) {
      var end = addDays(buy, ADD_COOLDOWN_DAYS);
      g.add_cooldown_until = today < end ? end : null;
    }
    var ip = ipo(ctx, key, today);
    g.ipo_pause_until = ip[0];
    var reasons = [];
    var soft = get(ctx, "ai_mode") === "off" && !NOAI_GATE_BLOCKS;
    if (g.status !== null && has(GATE_TO_BLOCK, g.status)) (soft ? g.warnings : reasons).push("gate:" + g.status);
    if (truthy(ip[0])) reasons.push("ipo_gate:" + ip[1] + "q");
    if (truthy(g.add_cooldown_until)) reasons.push("add_cooldown:" + g.add_cooldown_until);
    g.reasons = reasons;
    g.blocking = reasons.length > 0;
    return g;
  }

  // правило 10
  function conflict(ctx, key, srcs) {
    if (!srcs.length) return null;
    var lastDir = direction(srcs[srcs.length - 1].verdict);
    var i = srcs.length - 1;
    while (i > 0 && direction(srcs[i - 1].verdict) === lastDir) i--;
    if (i === 0) return null;
    var s = srcs[i], p = srcs[i - 1];
    if (p.kind === s.kind || direction(s.verdict) === null || direction(p.verdict) === null) return null;
    var at = s.recorded_at, closes = [];
    if (i + 1 < srcs.length) closes.push([srcs[i + 1].recorded_at, 0, "confirmed"]);
    var changed = get(or(get(or(get(ctx, "plan"), {}), key), {}), "changed_at");
    if (truthy(changed) && changed > at) closes.push([changed, 1, "plan"]);
    var trade = get(or(get(ctx, "last_trade_at"), {}), key);
    if (truthy(trade) && trade > at) closes.push([trade, 2, "trade"]);
    closes.sort(function (a, b) { return cmp(a[0], b[0]) || (a[1] - b[1]); });
    var first = closes.length ? closes[0] : null;
    return { at: at, source: brief(s), against: brief(p), open: first === null,
             closed_by: first ? first[2] : null, closed_at: first ? first[0] : null };
  }

  // правило 13: [время сделки в сторону последнего слова после его записи, вид источника] или [null, null]
  function executed(ctx, key, last) {
    if (last === null) return [null, null];
    var d = direction(last.verdict);
    var field = d === "down" ? "last_sell_at" : d === "up" ? "last_buy_at" : null;
    var at = field ? get(or(get(ctx, field), {}), key) : null;
    if (truthy(at) && at > last.recorded_at) return [at, last.kind];
    return [null, null];
  }

  // правило 14: [held, left_at, left_kind]
  function heldOf(ctx, key, today) {
    if (setOf(get(ctx, "snapshot_keys"))[key]) return [true, null, null];
    if (setOf(get(ctx, "first_buy"))[key]) return [false, null, null];
    var left = get(or(get(ctx, "last_sell_at"), {}), key);
    if (!truthy(left)) left = null;
    var m = get(or(get(ctx, "maturities"), {}), key);
    if (!truthy(m)) m = null;
    if (left === null && !(m !== null && day(m) <= today)) return [false, null, null];
    var redeemed = m !== null && (left === null || day(left) >= day(m));
    return [false, left, redeemed ? "redeemed" : "sold"];
  }

  // карточка «последнего слова» по ключу (правила 1–14)
  function num(v) { return typeof v === "number" && isFinite(v) ? v : null; }
  // правило 11: направление плана; у BALANCE — по знаку отклонения факта от плана с допуском
  function planDirection(plan) {
    var up = get(plan, "user_plan");
    if (!truthy(up)) return null;
    if (up !== BALANCE) return mapGet(PLAN_DIRECTION, up);
    var f = num(get(plan, "fact_pct")), p = num(get(plan, "plan_pct"));
    if (f === null || p === null) return null;
    if (f > p + PLAN_TOLERANCE_PP) return "down";
    if (f < p - PLAN_TOLERANCE_PP) return "up";
    return "flat";
  }
  function card(ctx, key) {
    var today = ctx.today;
    var srcs = sources(ctx, key);
    var decs = srcs.filter(function (s) { return s.kind === KIND_DECISION; });
    var revs = srcs.filter(function (s) { return s.kind === KIND_REVIEW; });
    var d = decs.length ? decs[decs.length - 1].doc : null;
    var last = srcs.length ? srcs[srcs.length - 1] : null;
    var verdict = last ? last.verdict : null;
    var dir = direction(verdict);
    var plan = or(get(or(get(ctx, "plan"), {}), key), {});
    var pdir = planDirection(plan);
    var hl = heldOf(ctx, key, today);
    var ex = executed(ctx, key, last);
    var decEx = executed(ctx, key, decs.length ? decs[decs.length - 1] : null)[0];
    var pvd = null;
    if (pdir !== null && dir !== null && pdir !== dir)
      pvd = { user_plan: get(plan, "user_plan"), plan_direction: pdir, verdict: verdict, direction: dir, source_kind: last.kind };
    return {
      key: key,
      verdict: verdict,
      direction: dir,
      confidence: last ? last.confidence : null,
      basis: last ? last.basis : null,
      verdict_source: last ? { kind: last.kind, id: last.id, recorded_at: last.recorded_at } : null,
      decision_verdict: d ? get(d, "verdict") : null,
      target_pct: d ? get(d, "target_pct") : null,
      review_by: d ? get(d, "review_by") : null,
      decision_id: d ? get(d, "id") : null,
      decision_recorded_at: d ? d.recorded_at : null,
      review_recorded_at: revs.length ? revs[revs.length - 1].recorded_at : null,
      conditions_created: d ? or(get(d, "conditions_created"), []).slice() : [],
      conditions_resolved: d ? or(get(d, "conditions_resolved"), []).slice() : [],
      gate: gate(ctx, key, today, d, srcs),
      conflict: conflict(ctx, key, srcs),
      plan_vs_decision: pvd,
      executed_by_trade_at: ex[0],
      executed_source_kind: ex[1],
      decision_executed_at: decEx,
      held: hl[0],
      left_at: hl[1],
      left_kind: hl[2]
    };
  }

  function allKeys(ctx) {
    var ks = {};
    or(get(ctx, "decisions"), []).forEach(function (d) { if (truthy(get(d, "key"))) ks[d.key] = true; });
    Object.keys(or(get(ctx, "reviews"), {})).forEach(function (k) { ks[k] = true; });
    or(get(ctx, "snapshot_keys"), []).concat(or(get(ctx, "first_buy"), [])).forEach(function (k) { ks[k] = true; });
    return Object.keys(ks).sort(cmp);
  }

  // карточки по ключам в порядке ключа (правило 12)
  function cards(ctx, keys) {
    var ks;
    if (keys === undefined || keys === null) ks = allKeys(ctx);
    else { var s = setOf(keys); ks = Object.keys(s).sort(cmp); }
    return ks.map(function (k) { return card(ctx, k); });
  }

  var LW = { card: card, cards: cards, allKeys: allKeys, addDays: addDays, addMonths: addMonths };
  root.LW = LW;
  if (typeof module !== "undefined" && module.exports) module.exports = LW;
})(typeof window !== "undefined" ? window : (typeof globalThis !== "undefined" ? globalThis : this));
