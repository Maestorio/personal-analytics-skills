/* rebalance-engine.js — колонка «Сейчас» в «Долях и целях» вьюера (2026-10-13).
 *
 * ЗЕРКАЛО автоматического режима сайзинга советника:
 *   skills/ru-portfolio-advisor/scripts/gate_aware_sizing.py — run_auto / auto_cycle_flags
 *   (+ classify_stocks, compute_sizing, compute_lots, _direction_for, _blocking_reasons,
 *   _unblock_by), _shared-references/constraint_engine.py — compute_fixed_point_target,
 *   skills/ru-portfolio-advisor/scripts/concentration_limits.py — лимит по эмитенту,
 *   references/concentration-limits.yaml — CONC_LIMITS ниже.
 * Это вторая реализация одной арифметики (вьюер считает при открытии — свежие гейты и
 * условия без перезагрузки портфеля; решение владельца 2026-10-13, вариант А). Совпадение
 * до рубля и лота на фикстурах и реальном снапшоте проверяет
 * tools/tests/test_rebalance_parity.py — меняешь правило там, меняй здесь.
 *
 * Правило автоматического режима (см. докстроку run_auto): Open — доля ниже МОЕГО плана больше
 * гистерезиса (2026-10-26: и докупка, не только срез) и нет автоблокировки, а также pending-условия
 * с продажей (sell_condition) или «держать» (condition_hold) в своём окне; срез — перевес > гистерезиса и user_plan BALANCE; остальное —
 * автоклассификация Dormant/Blocked. Лоты — по цене и лоту снапшота. Цели IE не участвуют.
 * §10.6 (решения владельца 11.11): база непрерывная — F/(1−S) при любом составе F, предел — план класса; каскад одним
 * расчётом (cascade {iterations, converged, added}; converged = false — результат первого прохода, сайт предупреждает);
 * разрыв «план − база» тремя слагаемыми (gap_gated_rub, gap_in_corridor_rub, gap_unallocated_rub; blocked_gap_rub — их
 * сумма); неразворот no_reversal_days по сделкам снапшотов (строка no_reversal); горизонт известных дат для срезов
 * (base_trim_rub, horizon, строки opens_on / opens_if_price_holds). Входы сделок и правок плана — в gateInputs:
 * last_buy_at, last_sell_at, buys_at, plan_changed_at (без них нет паузы докупки и неразворота).
 * Это арифметика от плана и цен, не совет. Цены — из снапшота или (applyQuotes) живые quotes@1: тот же
 * расчёт у gate_aware_sizing --auto --quotes (шаг Б / CR-D, tools/design-reference/live-prices-plan.md).
 *
 * Входы гейта и условий (шаг 11 цикла машиночитаемости, schema.md §3.5): runAuto(snapshot, gateInputs, conditions, opts).
 * gateInputs = {decisions: [decision@1], security_attrs: security-attrs@1, reviews: {ключ: [строка обзора]}} — гейт
 * считает модуль (б) assets/last-word.js (window.LW): статус по вердикту новейшего решения, истечение по review_by,
 * пауза докупки, IPO-пауза по справочнику бумаг, new_position у первой покупки без решения, review_needed от обзора
 * новее решения. conditions = {defs: [определения conditions@2], state: conditions-state@1} — строки модуля (а)
 * assets/conditions-merge.js (window.CM) на opts.today (по умолчанию as_of_date снапшота); действующее условие
 * (pending или fired — «ждёт владельца») закрывает докупку. Файла гейтов и условий 1.2 движок не читает.
 * Причины блокировки (коды): gate:<status> (статусы карты gate_to_block), pending_buy_condition,
 * sell_condition:<id>, condition_hold:<id>, ipo_gate:<q>q, add_cooldown:<дата>, user_plan:<слово>, no_price;
 * opts.aiMode = "off" (режим сайта «без ИИ»): статусы gate:<status> предупреждают (gate.warnings), не блокируют; ipo_gate и add_cooldown блокируют всегда.
 * unblock_by — срок решения, дата паузы, срок условия или «после разбора бумаги».
 */
(function (root) {
  "use strict";

  var ENGINE_VERSION = "1.10.0";   // равна ?v= у rebalance-engine.js в portfolio-integrated-viewer.html (контракт-тест)
  var MONEY_MARKET_TICKERS = ["TMON", "TPAY", "LQDT", "SBMM"];
  // Кодлисты (assets/codelists.js, из _shared-references/codelists.json): в браузере — window.CL (подключён ДО движка),
  // в node (тест паритета) — require рядом лежащего файла. Блокирующие статусы гейта — maps.gate_to_block.
  var CL = (root && root.CL) || (typeof require === "function" ? require("./codelists.js") : null);
  if (!CL) throw new Error("rebalance-engine: нет кодлистов (assets/codelists.js не подключён до движка)");
  // модули (а) и (б): в браузере — window.CM / window.LW (подключены ДО движка), в node — соседние файлы
  var CM = (root && root.CM) || (typeof require === "function" ? require("./conditions-merge.js") : null);
  var LW = (root && root.LW) || (typeof require === "function" ? require("./last-word.js") : null);
  if (!CM || !LW) throw new Error("rebalance-engine: нет conditions-merge.js / last-word.js (подключить до движка)");
  var AFTER_REVIEW = "после разбора бумаги";
  var AFTER_OWNER = "после отметки владельца";
  var UNDER_REVIEW = "reviewed_under_review";
  // Слова плана владельца (user_plan) в «Сейчас» — таблица в gate_aware_sizing.py (зеркало):
  // покупку запрещают WAIT/KEEP/SELL; WAIT — блокировка с причиной, KEEP/SELL — «ничего» (dormant);
  // срез до плана — BALANCE; SELL режет позицию до нуля без коридора.
  var EXPLICIT_NO_BUY_PLANS = ["WAIT", "WAIT/TRIM", "KEEP", "SELL"];
  var NO_BUY_DORMANT_PLANS = ["KEEP", "SELL"];
  var AUTO_TRIM_PLANS = ["BALANCE"];
  var AUTO_SELL_PLANS = ["SELL"];
  var HOLD_IN_BASE_PLANS = ["KEEP", "BUY"];   // подпись «держать» (hold): без операции, рубли в F, вес в S не кладётся (§10.5)
  var FIRST_BUY_PLANS = ["BUY", "BALANCE"];   // бумага без позиции с таким словом плана — кандидат на первую покупку
  var DIRECTION_EPS = 0.5;
  var NO_REVERSAL_DAYS = CL.defaults().no_reversal_days;          // неразворот «Сейчас», §10.6 п.6
  var HORIZON_DAYS = CL.defaults().known_dates_horizon_days;      // горизонт известных дат для срезов, §10.6 п.7
  var DEFAULT_HYSTERESIS_PP = 1.0;
  // references/concentration-limits.yaml (тест сверяет с YAML): лимит по эмитенту,
  // отраслевой в автоматическом режиме не считается (как sector_enabled=False у советника)
  var CONC_LIMITS = {
    default_issuer_limit_pct: 15.0,
    issuer_groups: { SBER: ["SBER", "SBERP"] },
    issuer_exceptions: { sber: { issuer: "SBER", limit_pct: 20.0, review_date: "2027-02-21" } }
  };

  function has(arr, x) { return arr.indexOf(x) >= 0; }
  function isNum(x) { return typeof x === "number" && isFinite(x); }
  // js-yaml отдаёт даты объектами Date (UTC-полночь), PyYAML — date; наружу — YYYY-MM-DD
  function dstr(v) {
    if (v instanceof Date) return v.toISOString().slice(0, 10);
    return v == null ? v : String(v);
  }
  function r2(x) { return x == null ? null : Math.round(x * 100) / 100; }

  function activeStockHoldings(snapshot) {
    var out = [];
    (snapshot.holdings || []).forEach(function (h) {
      if (!h || h.asset_type !== "stock") return;
      if (h.current_price_source === "cost_basis") return;
      if (h.is_blocked) return;
      if (has(MONEY_MARKET_TICKERS, h.ticker)) return;
      out.push(h);
    });
    return out;
  }

  function classRow(snapshot) {
    var bs = snapshot.balance_summary;
    if (!bs || typeof bs !== "object") throw new Error("В снапшоте нет balance_summary");
    var nav = bs.total_current_rub_excl_iis;
    if (!isNum(nav)) throw new Error("В balance_summary нет числового total_current_rub_excl_iis");
    var gm = bs.goals_matrix;
    if (!Array.isArray(gm)) throw new Error("В balance_summary нет списка goals_matrix");
    for (var i = 0; i < gm.length; i++) {
      var row = gm[i];
      if (row && row["Валюта"] === "RUB" && row["Бумага"] === "Акция") return { nav: nav, row: row };
    }
    throw new Error("В goals_matrix нет строки RUB/Акция");
  }

  // Контекст гейта и условий одного прогона (ЗЕРКАЛО GateContext в gate_aware_sizing.py): карточки модуля (б) по
  // тикеру (лениво) и строки модуля (а). Первая покупка — строки holdings с first_buy; бумаги снапшота — остальные.
  function qtyPos(h) { return h.qty == null || !isFinite(+h.qty) || +h.qty > 0; }   // как lwCtx: в портфеле — количество > 0 (без поля — держится)
  function gateContext(snapshot, gi, conds, today, aiMode) {
    gi = gi || {};
    var first = {}, snap = {}, stock = {};
    (snapshot.holdings || []).forEach(function (h) {
      if (!h || !h.ticker) return;
      if (h.first_buy) first[h.ticker] = true; else if (qtyPos(h)) snap[h.ticker] = true;
      if (h.asset_type === "stock") stock[h.ticker] = true;
    });
    var srt = function (o) { return Object.keys(o).sort(); };
    var ctx = { today: today, decisions: gi.decisions || [], reviews: gi.reviews || {}, security_attrs: gi.security_attrs || null,
                snapshot_keys: srt(snap), stock_keys: srt(stock), first_buy: srt(first), ai_mode: aiMode === "off" ? "off" : "on" };
    // сделки по истории снапшотов и правки плана (необязательные входы: last_buy_at, last_sell_at, last_trade_at, buys_at,
    // plan_changed_at) — пауза докупки модуля (б) (правило 7) и неразворот (§10.6 п.6); нет входа — нет паузы и неразворота
    ["last_buy_at", "last_sell_at", "last_trade_at", "buys_at"].forEach(function (k) { if (gi[k] != null) ctx[k] = gi[k]; });
    var rows = conds ? CM.merge(conds.defs || [], conds.state || { events: [] }, today) : [];
    var cards = {};
    return { today: today, rows: rows, decisions: ctx.decisions, lastBuy: gi.last_buy_at || {}, lastSell: gi.last_sell_at || {},
             planChanged: gi.plan_changed_at || {},
             card: function (t) { if (!cards.hasOwnProperty(t)) cards[t] = LW.card(ctx, t); return cards[t]; },
             cardOn: function (t, day) { return LW.card(Object.assign({}, ctx, { today: day }), t); } };
  }

  function condRows(t, G) { return G.rows.filter(function (c) { return c.key === t && c.active; }); }

  function pendingBuyCondition(t, G) {
    var list = condRows(t, G);
    for (var i = 0; i < list.length; i++) if (list[i].verdict_on_trigger === "BUY") return list[i];
    return null;
  }

  // Цена условия печатается как String(v). Ограничение зеркала: Python пишет str(100.0) =
  // «100.0», js-yaml отдаёт 100 для обоих написаний — расхождение только у целой цены,
  // записанной в YAML с «.0»; в фикстурах теста — дробная цена.
  function pyNum(v) { return String(v); }

  // строка модуля (а): сработавшее ждёт отметки владельца (или отсрочки); ожидающее — своего триггера
  function conditionUnblockBy(c) {
    if (c.status === "fired") return c.deferred_until ? dstr(c.deferred_until) : AFTER_OWNER;
    var tr = c.trigger || {}, v = tr.value;
    if (tr.type === "date" && v) return dstr(v);
    if (tr.type === "report_published" && tr.window_end) return dstr(tr.window_end);   // окно отчётности (+3 дня)
    if (tr.type === "price_above" && v != null) return "цена ≥ " + pyNum(v) + " ₽";
    if (tr.type === "price_below" && v != null) return "цена ≤ " + pyNum(v) + " ₽";
    return "бессрочно";
  }

  function blockingReasons(h, row, G) {
    var gr = G.card(h.ticker).gate.reasons;
    var reasons = gr.filter(function (r) { return r.indexOf("gate:") === 0; });
    if (pendingBuyCondition(h.ticker, G)) reasons.push("pending_buy_condition");
    gr.forEach(function (r) { if (r.indexOf("gate:") !== 0) reasons.push(r); });   // ipo_gate, add_cooldown
    if (has(EXPLICIT_NO_BUY_PLANS, row.user_plan) && !has(NO_BUY_DORMANT_PLANS, row.user_plan)) reasons.push("user_plan:" + row.user_plan);
    if (h.first_buy && !h.current_price) reasons.push("no_price");
    return reasons;
  }

  // Полный список причин для «Сейчас»: порядок гейт → условия → IPO и пауза → план (код стоп-условия
  // вставляется после gate:/pending_buy_condition).
  function mergeStopReason(reasons, stop) {
    if (!stop) return reasons;
    var code = stop.kind + ":" + stop.c.id, out = [], put = false;
    reasons.forEach(function (r) {
      if (!put && !(r.indexOf("gate:") === 0 || r === "pending_buy_condition")) { out.push(code); put = true; }
      out.push(r);
    });
    if (!put) out.push(code);
    return out;
  }

  function unblockBy(h, row, G, stop) {
    var g = G.card(h.ticker).gate;
    if (g.reasons.some(function (r) { return r.indexOf("gate:") === 0; })) return g.status === UNDER_REVIEW && g.expires_on ? g.expires_on : AFTER_REVIEW;
    var c = pendingBuyCondition(h.ticker, G);
    if (c) return conditionUnblockBy(c);
    if (stop) return conditionUnblockBy(stop.c);
    if (g.ipo_pause_until) return g.ipo_pause_until;
    if (g.add_cooldown_until) return g.add_cooldown_until;
    if (h.first_buy && !h.current_price) return "когда появится цена";
    return "бессрочно";
  }

  // Условие, закрывающее докупку без buy-триггера (зеркало _auto_stop_condition): продажа по порогу
  // (on_trigger TRIM/SELL) старше «держать» (while_pending HOLD/TRIM/SELL); BUY-условия — это
  // pending_buy_condition. Только действующие строки модуля (а) и только внутри окна not_before/valid_until.
  function condActiveOn(c, today) {
    if (c.not_before && today < dstr(c.not_before).slice(0, 10)) return false;
    if (c.valid_until && today > dstr(c.valid_until).slice(0, 10)) return false;
    return true;
  }
  function autoStopCondition(t, G) {
    var list = condRows(t, G), hold = null;
    for (var i = 0; i < list.length; i++) {
      var c = list[i];
      if (!condActiveOn(c, G.today)) continue;
      var ov = c.verdict_on_trigger;
      if (ov === "TRIM" || ov === "SELL") return { kind: "sell_condition", c: c };
      if (ov !== "BUY" && !hold && has(["HOLD", "TRIM", "SELL"], c.verdict_now)) hold = c;
    }
    return hold ? { kind: "condition_hold", c: hold } : null;
  }

  // Первая покупка (ЗЕРКАЛО first_buy_candidates в gate_aware_sizing.py): кандидат — тикер per_ticker с planned_share_pct > 0
  // и user_plan BUY/BALANCE, которого нет среди активных акций снапшота (замороженные/cost_basis и фонды денежного рынка
  // позицией не считаются; запись с qty = 0 идёт обычным путём). Синтетическая строка: доля 0, стоимость 0; дальше те же
  // правила, что у остальных, плюс гейт модуля (б): нет решения = new_position (покупка закрыта до первого разбора);
  // IPO-пауза — по справочнику бумаг, как у позиций. Цена: живая котировка quotes@1
  // (price, lot_size), иначе цена IE (opts.iePrices либо ie_model.positions[].current_price_rub; лот неизвестен → 1),
  // иначе blocked no_price.
  function firstBuyCandidates(snapshot, quotes, iePrices) {
    var pt = ((snapshot.ie_actual || {}).per_ticker) || {};
    var active = {};
    activeStockHoldings(snapshot).forEach(function (h) { active[h.ticker] = true; });
    var items = (quotes && quotes.items) || {}, ie = {};
    ((snapshot.ie_model || {}).positions || []).forEach(function (p) { if (p && p.ticker) ie[p.ticker] = p.current_price_rub; });
    if (iePrices) Object.keys(iePrices).forEach(function (t) { ie[t] = iePrices[t]; });
    var out = [];
    Object.keys(pt).forEach(function (t) {
      var row = pt[t] || {}, plan = row.planned_share_pct;
      if (active[t] || has(MONEY_MARKET_TICKERS, t)) return;
      if (!isNum(plan) || plan <= 0 || !has(FIRST_BUY_PLANS, row.user_plan)) return;
      var it = items[t] || {}, lot = it.lot_size, price = null, source = null;
      if (it.price) { price = +it.price; source = "live"; }
      else if (ie[t]) { price = +ie[t]; source = "ie"; }
      out.push({ ticker: t, asset_type: "stock", qty: 0, value_rub: 0, account: "main", current_price: price, current_price_source: "candidate",
        lot_size: lot ? lot : 1, lot_known: !!lot, price_source: source, first_buy: true });
    });
    return out;
  }

  // Неразворот «Сейчас» (ЗЕРКАЛО _no_reversal, §10.6 п.6, мягкий): докупку бумаги, проданной меньше no_reversal_days дней
  // назад, и срез купленной не предлагаем. Сделка — по истории снапшотов (день снапшота). Снимает событие ПОЗЖЕ дня сделки:
  // новое решение по ключу или правка плана (plan_changed_at); событие в день сделки не снимает; цена не снимает.
  function noReversal(t, action, G) {
    var trade = action === "buy" ? "sell" : "buy";
    var at = (trade === "sell" ? G.lastSell : G.lastBuy)[t];
    if (!at) return null;
    var day = String(at).slice(0, 10), until = LW.addDays(day, NO_REVERSAL_DAYS);
    if (!(G.today < until)) return null;
    if (G.decisions.some(function (d) { return d.key === t && String(d.recorded_at || "").slice(0, 10) > day; })) return null;
    var pc = G.planChanged[t];
    if (pc && String(pc).slice(0, 10) > day) return null;
    return { until: until, trade: trade, trade_at: day };
  }

  // Известная дата снятия условия (ЗЕРКАЛО _cond_lift): ожидающее с триггером «дата» — дата; ценовой с началом окна
  // not_before — эта дата, если текущая цена уже за порогом («если цена удержится»); иначе null
  function condLift(c, price) {
    if (c.status !== "pending") return null;
    var tr = c.trigger || {}, tt = tr.type, v = tr.value;
    if (tt === "date" && v) return [dstr(v).slice(0, 10), false];
    var nb = c.not_before;
    if ((tt === "price_above" || tt === "price_below") && nb && v != null && price) {
      if ((tt === "price_above" && price >= +v) || (tt === "price_below" && price <= +v)) return [dstr(nb).slice(0, 10), true];
    }
    return null;
  }

  // Горизонт известных дат (ЗЕРКАЛО _known_open_date, §10.6 п.7): блокировка снимается в известную дату d ≤ today + N И на
  // дату d вся картина гейта (модуль (б) с today = d) открыта, а каждое условие, действующее на d, снимается не позже d
  function knownOpenDate(h, row, G) {
    var g = G.card(h.ticker).gate, price = h.current_price, dates = [], rs = blockingReasons(h, row, G);
    for (var i = 0; i < rs.length; i++) {
      var r = rs[i];
      if (r.indexOf("ipo_gate:") === 0 && g.ipo_pause_until) dates.push(String(g.ipo_pause_until));
      else if (r.indexOf("add_cooldown:") === 0 && g.add_cooldown_until) dates.push(String(g.add_cooldown_until));
      else if (r !== "pending_buy_condition") return null;
    }
    function blockingConds(day) {
      return condRows(h.ticker, G).filter(function (c) {
        if (c.verdict_on_trigger === "BUY") return true;
        return condActiveOn(c, day) && (has(["TRIM", "SELL"], c.verdict_on_trigger) || has(["HOLD", "TRIM", "SELL"], c.verdict_now));
      });
    }
    var condPrice = false, cs = blockingConds(G.today);
    for (var j = 0; j < cs.length; j++) {
      var lift = condLift(cs[j], price);
      if (!lift) return null;
      dates.push(lift[0]); condPrice = condPrice || lift[1];
    }
    if (!dates.length) return null;
    var d = dates.slice().sort()[dates.length - 1];
    if (!(G.today < d && d <= LW.addDays(G.today, HORIZON_DAYS))) return null;
    if (G.cardOn(h.ticker, d).gate.reasons.length) return null;
    var cd = blockingConds(d);
    for (var k = 0; k < cd.length; k++) {
      var l2 = condLift(cd[k], price);
      if (!l2 || l2[0] > d) return null;
      condPrice = condPrice || l2[1];
    }
    return [d, condPrice];
  }

  // Зеркало auto_cycle_flags: докупка — недобор > гистерезиса и нет блокировки / условия с продажей или
  // «держать» / неразворота; notes — причины для бумаг без операции (в строки результата), opens_on — горизонт известных дат.
  // pt — per_ticker прохода (доли каскада уже подставлены).
  function autoCycleFlags(snapshot, G, hysteresisPp, pt) {
    var open = {}, trim = {}, notes = {}, hold = {};
    activeStockHoldings(snapshot).forEach(function (h) {
      var row = pt[h.ticker] || {};
      var real = row.real_share_pct, plan = row.planned_share_pct;
      if (has(HOLD_IN_BASE_PLANS, row.user_plan) && plan != null && real != null && !blockingReasons(h, row, G).length
          && !autoStopCondition(h.ticker, G)) hold[h.ticker] = plan;
      var isSell = has(AUTO_SELL_PLANS, row.user_plan);
      if (real == null || (plan == null && !isSell)) return;
      var nr;
      // SELL: вся позиция на продажу — независимо от доли, коридора, гейтов и условий (кроме неразворота)
      if (isSell && real > 0) {
        nr = noReversal(h.ticker, "trim", G);
        if (nr) notes[h.ticker] = { category: "dormant", reason: "no_reversal:" + nr.until, unblock_by: nr.until, no_reversal: nr };
        else trim[h.ticker] = 0;
        return;
      }
      var gap = real - plan;
      if (gap < 0) {
        var reasons = blockingReasons(h, row, G);
        var stop = autoStopCondition(h.ticker, G);
        if (reasons.length || stop) {
          notes[h.ticker] = { category: "blocked", reason: mergeStopReason(reasons, stop).join("; "), unblock_by: unblockBy(h, row, G, stop) };
          if (-gap > hysteresisPp && !has(NO_BUY_DORMANT_PLANS, row.user_plan)) {
            var ko = knownOpenDate(h, row, G);
            if (ko) { notes[h.ticker].opens_on = ko[0]; notes[h.ticker].if_price_holds = ko[1]; notes[h.ticker].horizon_weight = plan; }
          }
        } else if (has(NO_BUY_DORMANT_PLANS, row.user_plan)) notes[h.ticker] = { category: "dormant", reason: "user_plan:" + row.user_plan, unblock_by: null };
        else if (-gap > hysteresisPp) {
          nr = noReversal(h.ticker, "buy", G);
          if (nr) notes[h.ticker] = { category: "blocked", reason: "no_reversal:" + nr.until, unblock_by: nr.until, no_reversal: nr };
          else open[h.ticker] = plan;
        }
        else notes[h.ticker] = { category: "dormant", reason: "below_hysteresis:" + (-gap).toFixed(2) + "pp", unblock_by: null };
      } else if (gap > hysteresisPp && has(AUTO_TRIM_PLANS, row.user_plan)) {
        nr = noReversal(h.ticker, "trim", G);
        if (nr) notes[h.ticker] = { category: "dormant", reason: "no_reversal:" + nr.until, unblock_by: nr.until, no_reversal: nr };
        else trim[h.ticker] = plan;
      }
    });
    Object.keys(hold).forEach(function (t) { if (t in open || t in trim) delete hold[t]; });
    return { open: open, trim: trim, notes: notes, hold: hold };
  }

  // лимит по эмитенту (concentration_limits._compute_by_issuer); знаменатель — фактическая книга
  function concentrationBreaches(holdings, limits, today) {
    var groups = limits.issuer_groups || {}, members = {}, values = {}, l2 = 0;
    holdings.forEach(function (h) { l2 += +(h.value_rub || 0); });
    holdings.forEach(function (h) {
      var key = h.ticker;
      Object.keys(groups).forEach(function (g) { if (key === h.ticker && has(groups[g], h.ticker)) key = g; });
      (members[key] = members[key] || []).push(h.ticker);
      values[key] = (values[key] || 0) + +(h.value_rub || 0);
    });
    var exc = {};
    Object.keys(limits.issuer_exceptions || {}).forEach(function (id) { var e = limits.issuer_exceptions[id]; exc[e.issuer] = { id: id, e: e }; });
    var reason = {};
    Object.keys(values).sort().forEach(function (g) {
      var limit = +limits.default_issuer_limit_pct, x = exc[g];
      if (x && dstr(x.e.review_date) >= today) limit = +x.e.limit_pct;
      var limitRub = limit / 100 * l2;
      if (values[g] - limitRub > 1e-6) members[g].forEach(function (t) { reason[t] = "concentration_breach:" + g; });
    });
    return reason;
  }

  function directionFor(cat, delta) {
    if (delta == null) return null;
    if (delta > DIRECTION_EPS) return "buy";
    if (delta < -DIRECTION_EPS && cat === "rebalancing") return "trim";
    return "hold";
  }

  function computeLots(delta, quote) {
    if (!delta || !quote) return { lots: null, price: null };
    var price = quote.last != null ? quote.last : quote.prev_close;
    var lot = quote.lot_size;
    if (!price || !lot) return { lots: null, price: null };
    var lotRub = price * lot;
    var lots = delta > 0 ? Math.floor(delta / lotRub) : Math.ceil(Math.abs(delta) / lotRub);
    return { lots: lots, price: price };
  }

  // Один проход авто-режима (ЗЕРКАЛО _auto_pass + run_sizing/compute_sizing): классификация по долям прохода (снапшота
  // или после исполнения прошлого прохода) ∪ бумаги, уже торгуемые каскадом (sticky), непрерывная база, разрыв, база срезов.
  function autoPass(snapshot, holdings, pt0, G, h, classPlan, conc, shares, stickyOpen, stickyTrim) {
    var pt = pt0;
    if (shares) {
      pt = {};
      Object.keys(pt0).forEach(function (t) {
        var r = pt0[t];
        pt[t] = r && typeof r === "object" && (t in shares) && r.real_share_pct != null ? Object.assign({}, r, { real_share_pct: shares[t] }) : r;
      });
    }
    var flags = autoCycleFlags(snapshot, G, h, pt);
    Object.keys(stickyTrim).forEach(function (t) { flags.trim[t] = stickyTrim[t]; delete flags.open[t]; delete flags.notes[t]; delete flags.hold[t]; });
    Object.keys(stickyOpen).forEach(function (t) { if (!(t in flags.trim)) { flags.open[t] = stickyOpen[t]; delete flags.notes[t]; delete flags.hold[t]; } });

    // докупаемая бумага с целью ниже текущей не торгуется — в F своими рублями (книга после исполнения = база); перевод
    // в F только поднимает базу, проход конечен (ЗЕРКАЛО _auto_pass)
    for (;;) {
      var cls = { open: [], rebalancing: [], blocked: [], dormant: [] };
      holdings.forEach(function (hd) {
        var t = hd.ticker, cur = +(hd.value_rub || 0), row = pt[t] || {};
        if (t in flags.trim) { cls.rebalancing.push({ ticker: t, weight_pct: flags.trim[t], current_rub: cur }); return; }
        if (flags.notes[t] && flags.notes[t].category === "blocked") {
          cls.blocked.push({ ticker: t, current_rub: cur, reason: flags.notes[t].reason, unblock_by: flags.notes[t].unblock_by });
          return;
        }
        if (t in flags.open) {
          if (conc[t]) { cls.blocked.push({ ticker: t, current_rub: cur, reason: conc[t], unblock_by: "после среза до лимита концентрации" }); return; }
          cls.open.push({ ticker: t, weight_pct: flags.open[t], current_rub: cur });
          return;
        }
        var w = row.planned_share_pct != null ? row.planned_share_pct : row.ie_new_pct;
        var notAchieved = row.real_share_pct != null && w != null && row.real_share_pct < w;
        if (flags.notes[t]) {
          // недобор с нарушением лимита эмитента — заблокирован (как classify_stocks), подпись — из заметки
          if (notAchieved && conc[t]) cls.blocked.push({ ticker: t, current_rub: cur, reason: flags.notes[t].reason, unblock_by: flags.notes[t].unblock_by });
          else cls.dormant.push({ ticker: t, current_rub: cur, reason: flags.notes[t].reason, unblock_by: flags.notes[t].unblock_by, hold: flags.hold[t] });
          return;
        }
        // автоклассификация (как classify_stocks): гейт, условия на покупку, стоп-условия, IPO, пауза, план, лимит эмитента
        var stop = autoStopCondition(t, G);
        var reasons = mergeStopReason(blockingReasons(hd, row, G), stop);
        var onlyConc = false;
        if (!reasons.length && conc[t]) { reasons = [conc[t]]; onlyConc = true; }
        if (notAchieved && reasons.length) cls.blocked.push({ ticker: t, current_rub: cur, reason: reasons.join("; "),
          unblock_by: onlyConc ? "после среза до лимита концентрации" : unblockBy(hd, row, G, stop) });
        else cls.dormant.push({ ticker: t, current_rub: cur, hold: flags.hold[t] });
      });

      // непрерывная база (ЗЕРКАЛО compute_sizing + compute_fixed_point_target(full_plan_without_gates=False)): T* = F / (1 − S)
      // при любом составе F, предел — план класса; в F ничего нет — база = план класса
      var dormantSum = 0, blockedSum = 0;
      cls.blocked.forEach(function (x) { blockedSum += x.current_rub; });
      // весь dormant (и «держать» в коридоре) — в F своими рублями: бумага не торгуется, её вес в S не входит
      cls.dormant.forEach(function (x) { dormantSum += x.current_rub; });
      var weights = {}, S = 0;
      cls.open.concat(cls.rebalancing).forEach(function (x) { weights[x.ticker] = (x.weight_pct || 0) / 100; S += weights[x.ticker]; });
      function planW(t) { var w = (pt[t] || {}).planned_share_pct; return w != null ? w : null; }
      // замороженная бумага (и выше своей плановой доли) — в F своими рублями, как любая неторгуемая (§10.7: «на плане» отменено)
      function solve(wts, Sx, bSum) {
        if (Sx >= 1) throw new Error("S >= 1 — вес открытых и срезаемых покрывает весь класс");
        if ((1 - Sx) < 0.01) return { nd: true, S: Sx };
        var F = bSum + dormantSum;
        if (F <= 0) return { base: classPlan, source: "t_full_no_gates", S: Sx };
        var base = F / (1 - Sx);
        if (base > classPlan) return { base: classPlan, source: "fixed_point_capped", S: Sx };   // предохранитель: база не выше плана класса
        return { base: base, source: "fixed_point", S: Sx };
      }
      var R = solve(weights, S, blockedSum);
      var base = R.nd ? null : R.base, baseSource = R.nd ? "manual_check_required" : R.source;

      // горизонт известных дат: база СРЕЗОВ — как будто бумаги, открывающиеся в горизонте, уже открыты (не покупаются сегодня)
      var horizon = {}, baseTrim = null, horizonList = [];
      Object.keys(flags.notes).forEach(function (t) {
        var n = flags.notes[t];
        if (n.opens_on && !conc[t] && cls.blocked.some(function (x) { return x.ticker === t; })) horizon[t] = n.horizon_weight;
      });
      if (Object.keys(horizon).length && base != null && cls.rebalancing.length) {
        var hw = Object.assign({}, weights), hS = S, hb = blockedSum;
        Object.keys(horizon).forEach(function (t) { hw[t] = horizon[t] / 100; hS += horizon[t] / 100; });
        cls.blocked.forEach(function (x) { if (x.ticker in horizon) hb -= x.current_rub; });
        var RH = null;
        try { RH = solve(hw, hS, hb); } catch (e) { RH = null; }
        if (RH && !RH.nd) { baseTrim = RH.base; horizonList = Object.keys(horizon).sort(); }
      }

      var targets = {};
      if (base != null) {
        var reb = {};
        cls.rebalancing.forEach(function (x) { reb[x.ticker] = true; });
        Object.keys(weights).forEach(function (t) { targets[t] = weights[t] * (baseTrim != null && reb[t] ? baseTrim : base); });
      }
      // срез, который требует лимит концентрации, не разворачивается в докупку
      if (base != null) cls.rebalancing.forEach(function (x) {
        if (conc[x.ticker] && targets[x.ticker] != null && targets[x.ticker] > x.current_rub + DIRECTION_EPS) targets[x.ticker] = x.current_rub;
      });

      // разрыв до плана класса: гейты / недобор спящих (со знаком) / нераспределённая доля плана — каждое на (1 − S_eff)
      var gap = { gated: null, corridor: null, unalloc: null };
      if (base != null) {
        var total = classPlan - base;
        if (baseSource === "fixed_point") {
          var k = 1 - R.S;
          var def = function (items) {
            var sum = 0;
            items.forEach(function (x) { sum += (planW(x.ticker) || 0) / 100 * classPlan - x.current_rub; });
            return sum;
          };
          var gGated = def(cls.blocked) / k, gCorr = def(cls.dormant) / k;
          gap = { gated: gGated, corridor: gCorr, unalloc: total - gGated - gCorr };
        } else gap = { gated: 0, corridor: 0, unalloc: total };
      }
      var drop = base == null ? [] : cls.open.filter(function (x) { return targets[x.ticker] != null && targets[x.ticker] - x.current_rub < -DIRECTION_EPS; });
      if (!drop.length) break;
      drop.forEach(function (x) { delete flags.open[x.ticker]; });
    }
    return { cls: cls, notes: flags.notes, base: base, baseSource: baseSource, baseTrim: baseTrim, horizon: horizonList,
             targets: targets, gap: gap, pt: pt };
  }

  function runAuto(snapshot, gateInputs, conditions, opts) {
    opts = opts || {};
    var h = opts.hysteresisPp != null ? opts.hysteresisPp : DEFAULT_HYSTERESIS_PP;
    var limits = opts.limits === undefined ? CONC_LIMITS : opts.limits;
    var cands = firstBuyCandidates(snapshot, opts.quotes, opts.iePrices), candBy = {};
    cands.forEach(function (c) { candBy[c.ticker] = c; });
    if (cands.length) {
      var ptc = Object.assign({}, ((snapshot.ie_actual || {}).per_ticker) || {});
      cands.forEach(function (c) { ptc[c.ticker] = Object.assign({}, ptc[c.ticker], { real_share_pct: 0 }); });
      snapshot = Object.assign({}, snapshot, { holdings: (snapshot.holdings || []).concat(cands), ie_actual: Object.assign({}, snapshot.ie_actual, { per_ticker: ptc }) });
    }
    var cr = classRow(snapshot);
    var classPlan = +(cr.row["Планы"] || 0), classFact = +(cr.row["Сейчас"] || 0);
    var holdings = activeStockHoldings(snapshot);
    var pt = ((snapshot.ie_actual || {}).per_ticker) || {};
    var G = gateContext(snapshot, gateInputs, conditions, opts.today || dstr(snapshot.as_of_date || "").slice(0, 10), opts.aiMode);
    var conc = limits ? concentrationBreaches(holdings, limits, dstr(snapshot.as_of_date)) : {};

    // Каскад за один расчёт (ЗЕРКАЛО run_auto, §10.6 п.1): сделки → идеальное исполнение в модели → доли от книги после
    // исполнения → переклассификация; торгуемая бумага остаётся в наборе; пока набор не перестанет меняться. Предел — число
    // бумаг + 1; колебание (набор уже был) или предел — результат первого прохода и cascade.converged = false
    function movers(P) {
      return JSON.stringify([P.cls.open.map(function (x) { return x.ticker; }).sort(), P.cls.rebalancing.map(function (x) { return x.ticker; }).sort()]);
    }
    function wmap(list) { var o = {}; list.forEach(function (x) { o[x.ticker] = x.weight_pct; }); return o; }
    var limit = holdings.length + 1, stickyO = {}, stickyT = {}, shares = null, first = null, prevKey = null, seen = {};
    var converged = false, iterations = 0, P = null;
    while (iterations < limit) {
      iterations++;
      P = autoPass(snapshot, holdings, pt, G, h, classPlan, conc, shares, stickyO, stickyT);
      if (!first) first = P;
      var key = movers(P);
      if (key === prevKey || (prevKey === null && P.base == null)) { converged = true; break; }
      if (seen[key] || P.base == null) break;
      seen[key] = true; prevKey = key;
      stickyO = wmap(P.cls.open); stickyT = wmap(P.cls.rebalancing);
      var post = {}, book = 0;
      ["open", "rebalancing", "blocked", "dormant"].forEach(function (cat) {
        P.cls[cat].forEach(function (x) {
          var t = (cat === "open" || cat === "rebalancing") ? P.targets[x.ticker] : null;
          if (t === undefined) t = null;
          var d = directionFor(cat, t != null ? t - x.current_rub : null);
          post[x.ticker] = (d === "buy" || d === "trim") ? t : x.current_rub;
          book += post[x.ticker];
        });
      });
      if (book <= 0) break;
      shares = {};
      Object.keys(post).forEach(function (t) { shares[t] = r4(post[t] / book * 100); });
    }
    if (converged && iterations > 2) P = autoPass(snapshot, holdings, pt, G, h, classPlan, conc, null, wmap(P.cls.open), wmap(P.cls.rebalancing));
    else P = first;
    var firstSet = {};
    first.cls.open.concat(first.cls.rebalancing).forEach(function (x) { firstSet[x.ticker] = true; });
    var added = P.cls.open.concat(P.cls.rebalancing).map(function (x) { return x.ticker; }).filter(function (t) { return !firstSet[t]; }).sort();
    var cls = P.cls, base = P.base, targets = P.targets, notes = P.notes;
    var horizonSet = {}; P.horizon.forEach(function (t) { horizonSet[t] = true; });

    var quotes = {};
    (snapshot.holdings || []).forEach(function (x) { if (x && x.asset_type === "stock" && x.ticker) quotes[x.ticker] = { last: x.current_price, lot_size: x.lot_size }; });

    // причина заморозки словами кодов (ЗЕРКАЛО run_auto): блокировка/заметка, иначе причины, которые держат бумагу вне «держать» при перевесе
    var holdBy = {}; holdings.forEach(function (x) { holdBy[x.ticker] = x; });
    function frozenReason(it, cat, row) {
      if (!(cat === "blocked" || (cat === "dormant" && it.hold == null))) return null;
      if (it.reason) return it.reason;
      var hd = holdBy[it.ticker]; if (!hd) return null;
      var rs = mergeStopReason(blockingReasons(hd, row, G), autoStopCondition(it.ticker, G));
      return rs.length ? rs.join("; ") : null;
    }
    var rows = [];
    ["open", "rebalancing", "blocked", "dormant"].forEach(function (cat) {
      cls[cat].forEach(function (it) {
        var row = pt[it.ticker] || {}, q = quotes[it.ticker] || {}, n = notes[it.ticker] || {};
        var target = (cat === "open" || cat === "rebalancing") && base != null ? targets[it.ticker] : null;
        if (target === undefined) target = null;
        var delta = target != null ? target - it.current_rub : null;
        var dir = delta != null ? directionFor(cat, delta) : null;
        var lots = null, price = null;
        if (dir === "buy" || dir === "trim") { var L = computeLots(delta, q); lots = L.lots; price = L.price; }
        if (lots != null && candBy[it.ticker] && !candBy[it.ticker].lot_known) lots = null;   // первая покупка с неизвестным лотом: лоты не считаем, только сумма
        rows.push({
          ticker: it.ticker, category: cat,
          real_pct: row.real_share_pct != null ? row.real_share_pct : null,
          plan_pct: row.planned_share_pct != null ? row.planned_share_pct : null,
          user_plan: row.user_plan != null ? row.user_plan : null,
          current_rub: r2(it.current_rub), target_rub: r2(target), delta_rub: r2(delta),
          direction: dir, lots: lots, lot_size: q.lot_size != null ? q.lot_size : null, price: price,
          trade_rub: lots != null ? r2(lots * price * q.lot_size) : null,
          reason: it.reason || null, unblock_by: it.unblock_by || null,
          frozen: cat === "blocked" || (cat === "dormant" && it.hold == null),   // не торгуется: рубли в F базы «Сейчас»
          frozen_reason: frozenReason(it, cat, pt[it.ticker] || {}),
          first_buy: !!candBy[it.ticker], price_source: candBy[it.ticker] ? candBy[it.ticker].price_source : null,
          lot_known: candBy[it.ticker] ? candBy[it.ticker].lot_known : null,
          // §10.6: неразворот {until, trade, trade_at}; «откроется» (горизонт известных дат); cascade — в сделках после сдвига долей
          no_reversal: n.no_reversal || null,
          opens_on: horizonSet[it.ticker] ? n.opens_on : null,
          opens_if_price_holds: horizonSet[it.ticker] ? !!n.if_price_holds : null,
          cascade: added.indexOf(it.ticker) >= 0
        });
      });
    });
    rows.sort(function (a, b) { return a.ticker < b.ticker ? -1 : a.ticker > b.ticker ? 1 : 0; });
    var buy = 0, sell = 0;
    rows.forEach(function (x) { if (x.trade_rub == null) return; if (x.direction === "buy") buy += x.trade_rub; else if (x.direction === "trim") sell += x.trade_rub; });
    return {
      mode: "auto", as_of: dstr(snapshot.as_of_date), hysteresis_pp: h,
      nav_excl_iis: cr.nav, class_plan_rub: classPlan, class_fact_rub: classFact,
      base_rub: r2(base), base_source: P.baseSource, base_trim_rub: r2(P.baseTrim), horizon: P.horizon,
      blocked_gap_rub: base != null ? r2(classPlan - base) : null,
      gap_gated_rub: r2(P.gap.gated), gap_in_corridor_rub: r2(P.gap.corridor), gap_unallocated_rub: r2(P.gap.unalloc),
      buy_rub: r2(buy), sell_rub: r2(sell),
      cascade: { iterations: iterations, converged: converged, added: added },
      rows: rows
    };
  }

  // Живые цены поверх снапшота (quotes@1, tools/design-reference/live-prices-plan.md §2.2–§2.3).
  // ЗЕРКАЛО gate_aware_sizing.py::apply_quotes — меняешь правило здесь, меняй там. Чистая
  // функция: возвращает копию. opts.noShares — только для самопроверки теста (доли не
  // пересчитываются): тест доказывает, что умеет падать.
  function r4(x) { return Math.round(x * 10000) / 10000; }
  // Облигации (quotes@1 с досок TQOB/TQCB): цена — % номинала, значит value_rub = qty × (цена/100 × номинал × курс + НКД),
  // курс = 1 для рублёвого номинала, иначе курс ЦБ из quotes.fx (валюта номинала = face_unit котировки); НКД — в рублях
  // (валюта торгов SUR). Живую цену получает облигация с оценкой снапшота по MOEX, не заблокированная. Нет в котировках,
  // нет курса ЦБ для валюты номинала или НКД не в рублях (currency_id) → live_quotes.missing_bonds, а не missing: метка
  // «N бумаг по цене снапшота» говорит про акции и фонды. Ключ поиска — SECID, иначе ISIN (тикер облигации в holdings
  // часто ISIN, у ISS ключ — SECID).
  var RUB_FACE = { RUB: 1, SUR: 1 };
  // ячейка «валюта × класс» позиции — правило загрузчика (ЗЕРКАЛО _q_cell): акция — (валюта, «Акция»); облигация — корзина
  // USD/EUR/CNY → своя валюта, ОФЗ/КОРП → RUB, иначе валюта номинала; фонд — plan.funds[T], нет записи — (валюта|RUB, null)
  var CLASS_CANON = { "кеш": "Кеш", "кэш": "Кеш", "акция": "Акция", "акции": "Акция", "облигация": "Облигация",
                      "облигации": "Облигация", "золото": "Золото", "другое": "Другое" };
  function qCur(v) { var c = String(v || "RUB").trim().toUpperCase(); return c === "SUR" || c === "RUR" ? "RUB" : c; }
  function qCell(h, fundClasses) {
    if (h.asset_type === "stock") return [qCur(h.currency), "Акция"];
    if (h.asset_type === "bond") {
      var b = String(h.plan_bucket || "").trim().toUpperCase();
      if (b === "USD" || b === "EUR" || b === "CNY") return [b, "Облигация"];
      if (b === "ОФЗ" || b === "КОРП") return ["RUB", "Облигация"];
      return [qCur(h.nominal_currency || h.currency), "Облигация"];
    }
    var spec = fundClasses && fundClasses[h.ticker];
    if (!spec || typeof spec !== "object") spec = {};
    var cls = CLASS_CANON[String(spec["class"] || "").trim().toLowerCase()] || null;
    var cur = spec.currency ? qCur(spec.currency) : "";
    return cls && cur ? [cur, cls] : [cur || "RUB", null];
  }
  // сдвиг факта классов и ячеек матрицы на Δ стоимости, доли — от живого NAV (ЗЕРКАЛО _shift_class_rows)
  function shiftClassRows(bs, cells, nav) {
    function bump(row, d) {
      row.actual_rub = r2((isNum(row.actual_rub) ? row.actual_rub : 0) + d);
      row.actual_pct = nav ? r4(row.actual_rub / nav * 100) : null;
      if (isNum(row.target_pct)) {
        row.target_rub = r2(row.target_pct / 100 * nav);
        row.delta_pp = row.actual_pct != null ? r4(row.target_pct - row.actual_pct) : null;
        row.delta_rub = r2(row.target_rub - row.actual_rub);
      }
    }
    function blank(extra) {
      var r = { target_pct: null, target_rub: null, actual_rub: 0, actual_pct: null, delta_pp: null, delta_rub: null };
      Object.keys(extra).forEach(function (k) { r[k] = extra[k]; });
      return r;
    }
    var byClass = {}, keys = Object.keys(cells);
    keys.forEach(function (k) {
      var cls = cells[k].cls, name = cls === "Акция" ? "Акции" : cls, nk = name == null ? "\u0000" : name;
      byClass[nk] = (byClass[nk] || 0) + cells[k].d;
    });
    var rows = bs.class_plan_vs_fact;
    if (Array.isArray(rows) && rows.length) {
      var seen = {};
      rows.forEach(function (row) {
        if (!row || typeof row !== "object") return;
        var nk = row["class"] == null ? "\u0000" : row["class"];
        seen[nk] = true;
        bump(row, byClass[nk] || 0);
      });
      Object.keys(byClass).forEach(function (nk) {
        if (seen[nk] || !byClass[nk]) return;
        var row = blank({ "class": nk === "\u0000" ? null : nk });
        bump(row, byClass[nk]); rows.push(row);
      });
    }
    var mrows = bs.matrix_plan_vs_fact;
    if (Array.isArray(mrows) && mrows.length) {
      var seenM = {};
      mrows.forEach(function (row) {
        if (!row || typeof row !== "object") return;
        var k = String(row.currency || "") + "|" + (row["class"] == null ? "\u0000" : row["class"]);
        var d = !seenM[k] && cells[k] ? cells[k].d : 0;   // дубль ячейки — сдвиг один раз
        seenM[k] = true;
        bump(row, d);
      });
      keys.forEach(function (k) {
        if (seenM[k] || !cells[k].d) return;
        var row = blank({ currency: cells[k].cur, "class": cells[k].cls });
        bump(row, cells[k].d); mrows.push(row);
      });
    }
  }
  function bondItem(items, byIsin, h) {
    return (h.ticker && items[h.ticker]) || byIsin[h.isin || h.ticker] || null;
  }
  function applyQuotes(snapshot, quotes, opts) {
    opts = opts || {};
    var snap = JSON.parse(JSON.stringify(snapshot));
    var items = (quotes && quotes.items) || {};
    var byIsin = {};
    Object.keys(items).forEach(function (k) { var i = items[k]; if (i && i.isin) byIsin[i.isin] = i; });
    var fx = quotes && quotes.fx, usedFx = false;
    var applied = [], missing = [], appliedBonds = [], missingBonds = [], deltaMain = 0, deltaIis = 0;
    var cells = {};
    function cellAdd(h, d) {
      if (h.account !== "main" || !d) return;
      var c = qCell(h, opts.fundClasses), k = c[0] + "|" + (c[1] == null ? "\u0000" : c[1]);
      if (!cells[k]) cells[k] = { cur: c[0], cls: c[1], d: 0 };
      cells[k].d += d;
    }
    (snap.holdings || []).forEach(function (h) {
      if (h && h.asset_type === "bond") {
        if (h.current_price_source !== "moex_iss" || h.is_blocked || h.status === "blocked" || !h.qty) return;
        var bi = bondItem(items, byIsin, h);
        if (!bi || bi.price == null) { missingBonds.push(h.ticker); return; }
        if (bi.currency_id && !RUB_FACE[bi.currency_id]) { missingBonds.push(h.ticker); return; }
        var ccy = bi.face_unit || h.nominal_currency || "RUB", rate = 1;
        if (!RUB_FACE[ccy]) {
          rate = fx && fx[ccy] > 0 ? +fx[ccy] : 0;
          if (!(rate > 0)) { missingBonds.push(h.ticker); return; }
        }
        var face = bi.face_value != null ? bi.face_value : h.nominal;
        if (!(face > 0)) { missingBonds.push(h.ticker); return; }
        var acc = bi.accrued_int != null ? bi.accrued_int : (h.accrued_int || 0);
        var bold = +(h.value_rub || 0), bnv = r2(h.qty * (bi.price / 100 * face * rate + acc));
        h.current_price = bi.price;
        h.current_price_source = "moex_live";
        h.current_price_ts = bi.ts != null ? bi.ts : null;
        h.value_rub = bnv;
        h.accrued_int = acc;
        h.nominal = face;
        if (rate !== 1) usedFx = true;
        appliedBonds.push(h.ticker);
        cellAdd(h, bnv - bold);
        if (h.account === "main") deltaMain += bnv - bold; else deltaIis += bnv - bold;
        return;
      }
      if (!h || (h.asset_type !== "stock" && h.asset_type !== "fund")) return;
      if (h.current_price_source !== "moex_iss") return;
      var it = h.ticker ? items[h.ticker] : null;
      var price = it && it.price != null ? it.price : null;
      if (price == null || !h.qty) { missing.push(h.ticker); return; }
      var old = +(h.value_rub || 0), nv = r2(h.qty * price);
      h.current_price = price;
      h.current_price_source = "moex_live";
      h.current_price_ts = it.ts != null ? it.ts : null;
      h.value_rub = nv;
      if (h.lot_size == null && it.lot_size != null) h.lot_size = it.lot_size;
      applied.push(h.ticker);
      cellAdd(h, nv - old);
      if (h.account === "main") deltaMain += nv - old; else deltaIis += nv - old;
    });
    snap.live_quotes = { fetched_at: quotes && quotes.fetched_at != null ? quotes.fetched_at : null, stale: !!(quotes && quotes.stale), applied: applied, missing: missing, applied_bonds: appliedBonds, missing_bonds: missingBonds };
    if (usedFx && fx && fx.date) snap.live_quotes.fx_date = fx.date;

    var book = activeStockHoldings(snap), bookSum = 0;
    book.forEach(function (h) { bookSum += +(h.value_rub || 0); });
    var pt = (snap.ie_actual || {}).per_ticker || {};
    if (bookSum > 0 && !opts.noShares) book.forEach(function (h) {
      var row = pt[h.ticker];
      if (row && typeof row === "object" && "real_share_pct" in row) row.real_share_pct = r4(+(h.value_rub || 0) / bookSum * 100);
    });

    var bs = snap.balance_summary;
    if (bs && typeof bs === "object") {
      var shift = function (key, d) { if (isNum(bs[key])) bs[key] = r2(bs[key] + d); };
      var navOld = bs.total_current_rub_excl_iis;
      shift("total_current_rub_excl_iis", deltaMain);
      shift("total_current_rub", deltaMain);
      shift("total_current_rub_incl_iis", deltaMain + deltaIis);
      shift("iis_balance_rub", deltaIis);
      var nav = bs.total_current_rub_excl_iis;
      (bs.goals_matrix || []).forEach(function (row) {
        if (!row || row["Валюта"] !== "RUB" || row["Бумага"] !== "Акция" || !isNum(navOld)) return;
        var now = r2(bookSum);
        row["Сейчас"] = now;
        if (isNum(row["Доля план"])) row["Планы"] = r2(row["Доля план"] * nav);
        if (nav) row["Доля нынешняя"] = now / nav;
        if (isNum(row["Планы"])) row["Изменение"] = r2(row["Планы"] - now);
      });
      if (isNum(navOld) && isNum(nav) && (Object.keys(cells).length || deltaMain)) shiftClassRows(bs, cells, nav);
    }
    return snap;
  }

  // классы фондов сменились (план сайта загружен или правка funds.*) — факт классов и матрицы копии с живыми ценами
  // пересчитывается от строк исходного снапшота и Δ стоимости позиций основного счёта (по ключу тикер|ISIN|счёт), без
  // повторного applyQuotes: позиции копии не трогаются. Только вьюер; Python-зеркала нет (там класс фонда известен сразу).
  function reclassLive(base, live, fundClasses) {
    var bbs = base && base.balance_summary, lbs = live && live.balance_summary;
    if (!bbs || !lbs || !isNum(lbs.total_current_rub_excl_iis)) return live;
    var key = function (h) { return [h.ticker || "", h.isin || "", h.account || ""].join("|"); };
    var b = {}, l = {};
    (base.holdings || []).forEach(function (h) { if (h && h.account === "main") b[key(h)] = (b[key(h)] || 0) + (+(h.value_rub || 0)); });
    (live.holdings || []).forEach(function (h) {
      if (!h || h.account !== "main" || h.current_price_source !== "moex_live") return;
      var k = key(h);
      if (!l[k]) l[k] = { h: h, v: 0 };
      l[k].v += +(h.value_rub || 0);
    });
    var cells = {};
    Object.keys(l).forEach(function (k) {
      if (!(k in b)) return;
      var d = l[k].v - b[k];
      if (!d) return;
      var c = qCell(l[k].h, fundClasses), ck = c[0] + "|" + (c[1] == null ? "\u0000" : c[1]);
      if (!cells[ck]) cells[ck] = { cur: c[0], cls: c[1], d: 0 };
      cells[ck].d += d;
    });
    if (Array.isArray(bbs.class_plan_vs_fact)) lbs.class_plan_vs_fact = JSON.parse(JSON.stringify(bbs.class_plan_vs_fact));
    if (Array.isArray(bbs.matrix_plan_vs_fact)) lbs.matrix_plan_vs_fact = JSON.parse(JSON.stringify(bbs.matrix_plan_vs_fact));
    shiftClassRows(lbs, cells, lbs.total_current_rub_excl_iis);
    return live;
  }

  var api = { runAuto: runAuto, firstBuyCandidates: firstBuyCandidates, applyQuotes: applyQuotes, reclassLive: reclassLive, CONC_LIMITS: CONC_LIMITS, DEFAULT_HYSTERESIS_PP: DEFAULT_HYSTERESIS_PP };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.RebalanceEngine = api;
})(typeof window !== "undefined" ? window : this);
