# Исследование «ИИ в инвестициях»: промты и порядок запуска

**Дата:** 2026-10-07 · **Тип:** PLAN/рабочий файл (промты для Perplexity + порядок обработки)

**Цель.** Понять, что ИИ реально умеет в инвестициях на октябрь 2026, чем отличаются системы, которые
зарабатывают, от тех, что нет, и что из этого стоит сделать с нашим контуром. Исследование — оценка
качества, а не поиск подтверждений: нашу систему никто не защищает, бремя доказательства на каждом компоненте.

Объём (выбран пользователем): ИИ-аналитик и прогнозист · портфель и риск · архитектура агентов;
слой «торговые агенты» — модулем проверки тезиса. Рынок: глобально + адаптация к РФ.
Рамки рекомендаций: текущий стек плюс умеренные расширения.

---

## Порядок запуска (по шагам, не параллельно)

| # | Шаг | Кто | Вход | Выход |
|---|---|---|---|---|
| 1 | **Этап 1 — слепой обзор** (промт ниже) | Perplexity, режим Deep Research | только промт; система НЕ упоминается | английский отчёт с ID утверждений, цитатами, грейдами A–D |
| 2 | **Проверка источников** | Claude (эта репа или новая сессия) | отчёт этапа 1 | перечень: подтверждено / не подтверждено / неверно пересказано. Все утверждения грейда A/B + выборка остальных |
| 3 | **Разбор нашей системы** | Claude Opus 5 (`/model opusplan` или Opus) с доками контура через `/investment-docs` | проверенный отчёт + репозиторий | сравнение по компонентам, список изменений, план измерения |
| 4 | **Независимое второе мнение** (необязательно) | Perplexity, Deep Research | проверенный отчёт этапа 1 (без не подтверждённых утверждений) + `SYSTEM CARD` | английский разбор системы; сравниваем расхождения с шагом 3 |

**Почему именно так.**

- Этап 1 запускается **первым и слепым**: если назвать нашу систему, Perplexity начнёт подгонять обзор под
  её архитектуру и искать подтверждения.
- Шаг 2 нельзя пропускать: Perplexity — LLM, он может неточно пересказать источник, придумать цифру или
  сослаться на то, чего не открывал. До проверки выводы использовать нельзя.
- Шаг 3 главный: у Claude есть код и документация, у Perplexity — только `SYSTEM CARD`.
- Шаг 4 нужен из-за общих слепых зон: контур построен на Claude, и разбирает его Claude. Самоаудит
  2026-07-04 уже фиксирует, что ревью делала та же семья моделей. Внешний разбор показывает, где мы не видим.
  Если бюджет лимитов поджимает — шаг 4 можно отложить, шаги 1–3 самодостаточны.
- Fable недоступен на Pro; для шага 3 берём Opus 5 (см. `_shared-references/model-routing.md`).

**Что сказать Claude на шаге 2.** «Вот отчёт этапа 1 (приложен). Проверь по первоисточникам все утверждения
с грейдом A и B и выборку остальных: открой источник, сверь цитату, цифру, период и выборку. Выдай таблицу
ID → подтверждено / не подтверждено / искажено / источник недоступен. Ничего не интерпретируй.»

**Что сказать Claude на шаге 3.** «`/investment-docs portfolio forecasting`. Вот проверенный отчёт. Разбери
нашу систему по компонентам против доказательств: что подтверждено, что нет, что противоречит; что делают
лучшие системы и чего нет у нас; что у нас бесполезно; ранжированный список изменений с учётом стоимости
и риска, включая «удалить» и «ничего не делать»; минимальный план измерения. Строгий бенчмарк, неприятное
вперёд.»

---

## Этап 1. Слепой обзор (без упоминания нашей системы)

Запуск: Perplexity, Deep Research. Вставить блок целиком.

```text
ROLE
You are an independent, skeptical research analyst with no commercial stake in AI products, asset managers, or any specific system. Your job is to find out what is TRUE, not what is encouraging. Today is 2026-10-07. Prioritise 2025–2026 evidence, but include earlier foundations.

OBJECTIVE
Produce an evidence-graded map of what AI systems (LLM-based agents, LLM-assisted analysis pipelines, classical ML) can and cannot reliably do in investing as of October 2026; what separates systems that make money from those that don't; and what a single retail investor building a personal AI-assisted research-and-risk pipeline should take from this.

PREMISE TO TEST (do NOT assume it is true)
"Until recently, AI systems given access to trading terminals mostly lost money; now they have started to earn. The cause may be better algorithms, or better configuration."
Split it into three hypotheses and give a verdict + confidence level + "what evidence would change this verdict" for each:
 P1. Outcomes really changed — by how much, net of costs, risk-adjusted, versus simple baselines (index, equal-weight, 60/40, buy-and-hold)?
 P2. The change is real and not an artifact: look-ahead / training-data leakage, survivorship, short windows, favourable market regime (beta, not alpha), selection of winners, multiple testing, marketing.
 P3. What is the cause: base-model capability, scaffolding/configuration (data, tools, memory, prompts, risk limits, position sizing, execution), market regime, or luck? Look for ablation studies and decompositions.
Before concluding, write the strongest honest case FOR "AI now genuinely earns" and the strongest honest case AGAINST (mostly noise, leakage, hype). Default status of any performance claim is "unproven" until it meets the standard below.

EVIDENCE STANDARD (apply to every performance or capability claim)
 Grade A: live/forward results strictly after the model's training cutoff, costs included, independent party or verifiable ledger, long enough to be statistically meaningful.
 Grade B: rigorous backtest — point-in-time data, test window after training cutoff or documented leakage controls, costs, multiple regimes, compared against simple baselines.
 Grade C: backtest without leakage controls, or vendor/self-reported numbers.
 Grade D: marketing, social media, anecdote, tiny-N leaderboards.
For every key claim record: source type, period, sample size, benchmark, transaction costs, model training cutoff vs test window, risk-adjusted metric, independent replication (yes/no), funding/conflict of interest. If a field is not reported, write "not reported" — never guess.

RESEARCH MODULES
 1. Premise audit. Timeline 2023–2026 of public evidence: academic studies, live LLM-trading competitions/arenas, fund and ETF launches, documented failures. Starting points to VERIFY, not to trust: Lopez-Lira & Tang (ChatGPT and stock-return predictability); Kim/Muhn/Nikolaev (LLM financial-statement analysis); research on look-ahead and memorisation bias in LLMs (e.g. Glasserman & Lin; Sarkar & Vafa); agent frameworks (TradingAgents, FinMem, FinAgent, FinRobot, FinCon); live LLM trading arenas (e.g. Alpha Arena / Nof1, StockBench); AI-managed funds. Find more — especially contrary results and failed replications.
 2. Analyst & forecaster layer. LLM forecasting accuracy vs. human crowds and superforecasters (ForecastBench, Metaculus/bot tournaments, etc.); calibration and overconfidence; ensembling/aggregation of multiple sources or models; retrieval-augmented forecasting; scenario and conditional forecasting; LLM fundamental/earnings analysis; known biases (anchoring on stale analyst targets, sycophancy, hallucinated data, recency).
 3. Portfolio & risk layer. LLM-assisted portfolio construction, rebalancing, position sizing, scenario generation and stress testing; what the LLM adds over classical methods (factor models, Black-Litterman, risk parity, HRP) and what it breaks; numeric reliability and the split between LLM reasoning and deterministic code; tail-risk and correlation-breakdown handling.
 4. Agent architecture & reliability. Deterministic compute vs LLM; memory and state; multi-agent debate vs single agent; self-verification / red-team / critic loops (do they measurably help?); provenance and citation discipline; hallucination control; guardrails; human-in-the-loop; failure when agents skip or only partly read instructions; cost/latency trade-offs; what is publicly known about how institutional players deploy this.
 5. Information collection & aggregation. Data sources, point-in-time integrity, news/alt-data/sentiment signals and their decay; what is free vs paid; what edge, if any, survives for a non-professional with no terminal.
 6. Evaluation. How to measure whether an AI investment system works: leakage-free evaluation, pre-registered forward tests, calibration scoring (Brier/log score), decision-level attribution, counterfactual baselines, required sample sizes and statistical power — specifically for a low-frequency (weekly–monthly decisions, ~20-month horizon) single-investor setting where the sample will be small.
 7. Failure modes & regulators. Documented losses, blow-ups, "AI-washing" enforcement, regulator warnings (SEC, FCA, ESMA, IOSCO, Bank of Russia, others), systemic/herding risks.
 8. Adaptation to an emerging, sanctions-constrained market (Russia / MOEX: stocks and bonds, thin liquidity, sanctions, scarce data, Russian-language sources). What transfers from US/EU evidence and what does not; any research specific to Russian or other EM markets.

RETAIL CONSTRAINTS (for module 9 and for relevance filtering)
One person; no Bloomberg/Refinitiv; consumer LLM subscriptions (limited API budget); decisions weekly-to-monthly; ~20-month horizon; manual execution; stocks and bonds on MOEX. Do NOT give buy/sell advice on specific securities.

 9. Practice catalogue. List the practices that the evidence says matter most, ranked by (evidence strength × feasibility for the constraints above). Include practices that do NOT work.

OUTPUT FORMAT (write the report in ENGLISH; it will be post-processed by another analyst, so keep the structure strict)
 0. TL;DR — at most 12 lines, each with a verdict and confidence.
 1. Verdicts on P1, P2, P3 + steelman FOR / AGAINST.
 2. Evidence table: claim ID | source | type | period | N | costs | leakage controls | grade | key number.
 3. What separates winners from losers — mechanisms, ranked by evidence strength.
 4. Consensus / contested / unknown.
 5. Practice catalogue: practice | what it does | evidence grade | transfers to retail+MOEX? | cost/effort | risks.
 6. Anti-patterns and red flags (how to recognise inflated claims).
 7. Evaluation playbook for a small-sample personal system.
 8. Open questions and "what would change these conclusions".
 9. Source list with date and grade.
 10. Limits of this research: what you could not verify, search gaps, paywalled material.

RULES
 - Every non-trivial claim carries a source link and date. Separate FACT / AUTHOR'S CLAIM / YOUR INFERENCE.
 - Give every key claim a unique ID (C1, C2, ...). The evidence table has one row per claim with that ID; in the text refer to claims by ID.
 - For every Grade A/B claim add the exact quote or number from the source (max 25 words) plus the exact URL or DOI.
 - Never cite a source you did not open. If you know a result only from a secondary report, mark the claim "secondary" and name the primary source you could not access.
 - Prefer primary sources (papers on arXiv/SSRN/NBER/journals, regulator documents, arena ledgers, code repositories). Treat media and vendor posts as pointers only. Flag non-peer-reviewed preprints.
 - For each of the 15 most important findings, run an explicit search for contradicting evidence, replications and retractions, and report the result.
 - When sources conflict, show both sides; do not average them into a comfortable middle.
 - Do not pad, do not flatter, do not soften unpleasant conclusions. "Not found" and "unproven" are acceptable answers.
```

---

## Этап 2 (необязательно). Независимое второе мнение о системе

Запуск: Perplexity, Deep Research, **после** шагов 1–2. К запросу приложить проверенный отчёт этапа 1
(без не подтверждённых утверждений). Основной разбор системы делает Claude на шаге 3; этот этап — внешняя
проверка слепых зон.

Блок `SYSTEM CARD` составлен по внутренним самоаудитам (июль–август 2026; часть дефектов могла быть
исправлена). Суммы и тикеры в него не входят. Перед запуском сверить актуальность «KNOWN WEAKNESSES»
с `docs/investment/TODO.md` и обновить, если что-то закрыто.

```text
ROLE
You are an independent, skeptical reviewer. You have no stake in the system described below and no obligation to find it good. Today is 2026-10-07. Attached: (1) a verified Stage-1 evidence report on AI in investing; (2) below, a SYSTEM CARD of a personal AI-assisted investment pipeline.

OBJECTIVE
Assess the system's QUALITY against the evidence, not defend it. Establish (a) which design choices have supporting evidence, which have none, and which are contradicted; (b) what the best-performing approaches in the evidence do that this system does not; (c) what this system does that evidence suggests is useless or harmful; (d) what to change, in what order, and what NOT to touch. "Do nothing" and "remove component X" are legitimate recommendations.

SYSTEM CARD (written neutrally; known weaknesses included)
Purpose: decision-support for one retail investor (MOEX stocks and bonds, ~20-month horizon). The system does NOT trade; the human executes manually. Cadence: weekly review, monthly meta-audit, ad-hoc on regime change.
Stack: LLM agents ("skills") in Claude Code + deterministic Python scripts; file-based memory library; no terminal data, public sources via web search and MOEX/Bank-of-Russia APIs.
Pipeline: (1) data loader — parses broker exports, computes returns/XIRR deterministically, takes a JSON snapshot; (2) macro watcher — snapshot of 7 Russian macro indicators, no interpretation; (3) forecast layer — collects forecasts from 3–7 sources and aggregates them with trust weights learned from retrospective audits of each source's past accuracy ("Layer 1": marginal consensus per factor); (4) scenario builder — 2×2 scenario matrix of 4 coherent worlds with manually set probabilities ("Layer 2": scenario bundles of factor values); (5) stress test — translates scenarios into per-position P&L via per-position factor betas (priors or OLS on MOEX history) over several horizons, with confidence-interval propagation; (6) weekly advisor — per-position review through a "fundamental gate" (alive / under review / broken) combined with macro-scenario context to produce verdicts and sizing; (7) integrated view — read-only synthesis of equity-vs-bond outlook; (8) coherence audit — monthly meta-pass looking for cross-artifact contradictions, hidden common-factor exposure, and red-teaming of the equity-vs-bond conclusion; (9) hypothesis stress-tester (pre-mortem, devil's advocate); (10) memory-maintenance skills.
Design principles: deterministic code for numbers, LLM for reading/reasoning; scenario-independent skills; schema validation before saving; no recommendations in the synthesis layer.
KNOWN WEAKNESSES (from internal audits, July–August 2026; some may since be fixed):
 - No resolved-outcome log exists, so forecast calibration (Brier/reliability) has NEVER been computed; the trust weights come from retrospective audits of sources, not from tracked outcomes of this system.
 - "Confidence" in forecasts measured source coverage, not uncertainty (21 of 43 files had exactly the same value).
 - The consensus layer often collapsed to a single high-trust source; one-sided scenario cones for policy-rate and FX (no "rate hike" or "strong ruble" world); a shared "shock normalises" assumption across all four scenarios; anchoring to stale analyst targets when a newer fact existed.
 - About 62% of forecast replacements were caused by the system's own process churn (matrix rebuilds, method upgrades), not by new information.
 - Scenario probabilities are set manually; correlation between scenario axes defaults to zero.
 - An internal self-audit found the advisor skipped mandatory reference files and produced a sizing error of ~14x; the instruction text contained the correct rule.
 - An early internal review found ~51 correctness-level defects across 16 skills (schema mismatches, silent zero betas, null values passing validation).
 - Evaluation of the system as a whole (does it beat a passive baseline? does it change decisions for the better?) has not been done.

TASKS
 1. Component audit. For each pipeline component (1–10): what the evidence says about this kind of component → verdict {supported / partially supported / no evidence / contradicted} → evidence grade (A–D) → your confidence → what you would check next.
 2. Benchmark gap. Which practices from the top of the Stage-1 practice catalogue are missing here? Which present practices are not in that catalogue at all?
 3. Weakness diagnosis. For each KNOWN WEAKNESS: how serious is it according to evidence, is it a known, studied failure mode, and what is the cheapest credible mitigation? Then add the weaknesses the owner has NOT listed (blind spots of self-audit; the system was reviewed largely by the same family of models that runs it).
 4. Biggest risk. State the three most likely ways this system produces confident but wrong decisions, and the evidence for each.
 5. Recommendations. Table: change | expected effect | evidence strength (A–D) | cost/effort in the constraint set below | risk of making things worse | prerequisites | dependencies. Rank by (expected effect × evidence strength) / (cost + risk). Include "remove", "simplify", "do nothing", and "stop using the system for X" as options.
 6. Measurement plan. A minimal experiment design to find out whether this system adds value: baselines, metrics, forward-only protocol, sample-size reality check given weekly-to-monthly decisions, pre-registration, how to build the outcome log, and what result would justify shutting components down.
 7. Pre-mortem. Assume that in 12 months the system turned out to be net harmful. Write the three most plausible causes.

CONSTRAINTS FOR RECOMMENDATIONS
Current stack plus moderate extensions: Claude Code/skills, Python, consumer subscription without large API spend; modest paid data/tools are allowed only with a cost estimate; full architecture rewrite is out of scope unless the evidence says the current architecture is fundamentally unsound (then say so explicitly). No buy/sell advice on specific securities.

RULES
 - Same evidence standard and sourcing rules as Stage 1 (grade A–D; link + date for every non-trivial claim; unique claim IDs; exact quotes for Grade A/B; never cite a source you did not open; separate FACT / AUTHOR'S CLAIM / YOUR INFERENCE).
 - Mark every place where you reason by analogy from a different setting (e.g. autonomous trading agents → a human-in-the-loop advisory pipeline, US/EU → MOEX). Analogical conclusions get at most "medium" confidence.
 - Do not be diplomatic. If a component is useless, say so. If the evidence is insufficient to judge, say "insufficient evidence", not a hedged guess.
 - Do not assume the system is good, and do not assume it is bad. Burden of proof is on each component.
 - Write the report in ENGLISH. Structure: TL;DR (≤12 lines) → sections 1–7 → list of sources with grades → limits of this review.
```

---

## Примечания

- Источники идей по слабостям системы: `docs/investment/temp/forecasting-self-audit-2026-07-04.md`,
  `docs/investment/2026-08-19-retro_calibration-missed-fixed-point-rule.md`,
  `docs/investment/_cross-cutting/reviews-INDEX.md`.
- Главная неприятная правда, которую шаг 3 должен вынести вперёд: **качество системы не измерено** —
  resolved-исходов нет, калибровка не считалась. Любые «улучшения» без плана измерения нечем оценить.
- Результаты исследования (проверенный отчёт, разбор, решения) складывать рядом с этим файлом и заносить
  в `TODO.md` с префиксом; в этом файле хранятся только промты и порядок.
