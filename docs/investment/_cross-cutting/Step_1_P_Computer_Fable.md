# AI in Investing, October 2026: An Evidence-Graded Map

Independent audit of what LLM agents, LLM-assisted pipelines and classical ML can and cannot reliably do in investing, with a specific test of the premise "AI trading systems used to lose money and have now started to earn", and a translation to a single retail investor on MOEX with weekly-to-monthly decisions and a ~20-month horizon.

Conventions used throughout:

- Grades: **A** live/forward after training cutoff, costs included, independent or verifiable ledger, statistically meaningful length; **B** rigorous backtest or prospective study with leakage controls, costs, baselines; **C** backtest without leakage controls or vendor/self-reported numbers; **D** marketing, social media, anecdote, tiny-N leaderboards.
- Labels: **FACT** (verifiable statement from a primary document), **AUTHOR'S CLAIM** (what a paper or vendor asserts), **INFERENCE** (this report's reasoning).
- Every performance claim starts at "unproven" and is only upgraded if it meets the standard. Claims are referenced by ID (C1, C2, ...); the evidence table in Section 2 has one row per ID.
- "Secondary" marks a result known only through another document; the primary is named.
- Non-peer-reviewed preprints are flagged "preprint". NBER working papers are not peer-reviewed and are flagged as such.

---

## 0. TL;DR

1. **P1 (outcomes changed, net of costs, risk-adjusted, vs simple baselines): NOT SUPPORTED. Confidence: high.** Every Grade A/B source that compares LLM trading systems against buy-and-hold or equal-weight finds no certified net alpha (C9, C10, C11, C13, C21, C25, C44); the 2025–2026 "they started earning" signal comes from Grade C/D arenas with 2–16 week windows, N of 6–10 models, and no benchmark (C14, C16, C17, C18).
2. **P2 (the change is real, not an artifact): REJECTED for trading; PARTIALLY SUPPORTED for forecasting. Confidence: high / medium.** Look-ahead and memorisation are measured, not hypothetical (C2, C4, C5, C7, C8, C51); arena results do not reconcile across sources (C17, C18, C84) and most winners sit inside beta-driven rallies (C82, C83). On judgmental forecasting, LLMs genuinely approached superforecaster parity in 2026 (C30, C32), but with a stale human baseline and no demonstrated conversion to returns.
3. **P3 (cause): scaffolding and evaluation design explain most of the measured variation; base-model capability explains little; market regime and luck explain the rest. Confidence: medium.** Frontier models are statistically indistinguishable in paired replay (C19); interface design drives leverage and behaviour (C19); reasoning effort does not improve net returns (C11, C12, C40); architecture dominates backbone in the one live benchmark that varies both (C15, Grade C).
4. **Where LLMs genuinely add value (Grade B): text-to-signal extraction on post-cutoff news (C1, C53), information processing around earnings (C54), judgmental probability forecasting (C30, C32, C34), and research throughput (C29). None of these has been shown to convert into retail-tradable net alpha. Confidence: medium-high.**
5. **Where LLMs measurably hurt (Grade B): multi-number arithmetic without code (C7), position sizing and risk (C19, C44), concentration and home bias in advice (C22, C53), self-correction without external feedback (C39), and retrieval poisoning by fabricated news (C38). Confidence: high.**
6. **Classical, deterministic methods remain the benchmark to beat: 1/N and buy-and-hold are still not consistently beaten by optimisers (C47) or by LLM allocators (C44, C45); gradient-boosted trees beat the best commercial LLM on earnings direction (C7). Confidence: high.**
7. **Public AI funds: Grade A/B live record is negative.** 0 of 10 fully-AI funds beat the S&P 500 through 2023 (C25); AIEQ returned ~100% vs ~200% for the S&P since 2017 (C26); AI hedge funds' alpha disappeared after 2017 (C24). Confidence: high.
8. **Institutional claims (Bridgewater AIA, Man AlphaGPT) are Grade D: self-reported, no benchmark, no risk metrics, no independent verification (C28, C29).** Confidence that they are unverified: high.
9. **Regulators (SEC, FCA, ESMA, IOSCO, BoE, IMF, FSB, Bank of Russia) converge: AI-washing is being prosecuted (C58), retail trust in AI exceeds its accountability (C59, C66), production use of autonomous AI trading is rare (C60, C61, C62, C65), herding risk is plausible but unmeasured (C61, C64, C66). Confidence: high.**
10. **For a 20-month, monthly-decision single investor, the sample is too small to prove skill: a true Sharpe of 0.5 needs ~18 years for t≈2 (INFERENCE from Lo's SE formula); 20 monthly directional calls need ≥15 correct to reject coin-flipping at 5%.** The evaluable targets are process quality, calibration (Brier), and avoided errors, not alpha. Confidence: high.
11. **What transfers to MOEX: all the negative findings and all the process disciplines; what does not transfer: any US signal estimate, because disclosure gaps (C71), data licensing (C72) and thin liquidity change the information set. Russian-specific evidence is Grade C/D only (C67–C70). Confidence: medium.**
12. **Strongest actionable conclusion: use LLMs as a leakage-aware research and risk-checklist layer with deterministic code for every number, pre-registered rules, and human sign-off; do not use them as a signal generator or position sizer. Confidence: high.**

---

## 1. Verdicts on P1, P2, P3

### Premise as stated

"Until recently, AI systems given access to trading terminals mostly lost money; now they have started to earn. The cause may be better algorithms, or better configuration."

### P1 — Did outcomes really change, net of costs, risk-adjusted, versus simple baselines?

**Verdict: Not supported. Confidence: high.**

What changed between 2023 and 2026 is the *volume and visibility* of live LLM-agent experiments, not the measured net outcome against baselines.

- The strongest 2026 evidence with costs, held-out windows and passive baselines (Gençay, C10, Grade B): passive SPY and equal-weight buy-and-hold were certified by held-out Sharpe confidence intervals excluding zero, while **"no LLM-discovered strategy was certified"** across 453 US large caps (design 2017–2021, evaluation 2022–2025), 39 ETFs (2007–2016 / 2017–2025), two frontier models and five repeated runs; costs 1 bp commission + 2 bp spread + square-root impact + 50 bp borrow ([arXiv 2608.27734](https://arxiv.org/pdf/2608.27734v1)). The best gpt-4.1 strategy had evaluation Sharpe 0.18 with 95% CI [−0.80, +1.14] while SPY returned +51.5% over the same window.
- The KDD 2026 re-evaluation of the two most-cited agent frameworks (FinMem, FinAgent) over two decades and 100+ symbols, with Moomoo commissions (Li, Kim, Cucuringu, Ma, C9, Grade B): **"previously reported LLM advantages deteriorate significantly under broader cross-section and over a longer-term evaluation"**; buy-and-hold beat both agents with paired-test p-values of 3.0e-6 to 0.0117 across setups; agent alphas had p > 0.34 ([arXiv 2505.07078](https://arxiv.org/html/2505.07078v5)). Extending FinMem's MSFT window by two months flipped cumulative return from +23.3% to −22.0%.
- The 2026 full-pipeline portfolio benchmark (PortBench, C44, Grade B): 90% of model-profile cases failed to beat equal-weight on Sharpe in the 2024 window; across four regimes LLMs beat equal-weight in 39/120 cases (32.5%), with 15 bps round-trip costs ([arXiv 2605.27887](https://arxiv.org/html/2605.27887v3)).
- Prospective household portfolios recommended by LLMs (Carlin, Israelsen, Wazzan, NBER 2026, C21, Grade B for design): **"do not appear to earn statistically-significant abnormal returns"** and are driven primarily by media attention ([NBER w35153](https://www.nber.org/papers/w35153)).
- The one Grade A-type record for public AI funds is negative: 0 of 10 fully-AI funds beat the S&P 500 over their lives through 2023, averaging −10.05 pp/yr; portfolio Sharpe 0.19–0.27 vs 0.60 for the S&P (Smith & Wyatt, C25); AIEQ +100.2% since 2017 vs ~+199.7% for the S&P 500 as of August 2026 (C26, secondary via 24/7 Wall St; ETFRC shows 9.9% annualised since inception).

The "now they earn" evidence is exclusively Grade C/D and lacks baselines: Alpha Arena Season 1 (16 days, N=6, 2 profitable, GPT-5 −58.74%), Season 1.5 (two weeks, 8 models × 4 contests, 6 of 32 entries profitable, portfolio lost about one third), HKU AIEL (six weeks, 10 agents, +9.9% to −15.1%, no benchmark), AI-Trader (MiniMax +9.56% on Nasdaq-100 while GPT-5 at +1.56% trailed QQQ at +1.87%; no agent beat SSE-50). Where a benchmark exists, the median model loses to it (C82, C83).

**Numbers on "by how much":** no Grade A/B source reports a positive net, risk-adjusted excess return for an LLM trading system over buy-and-hold or 1/N that survives its own confidence interval. The sign of the best available point estimates is mixed; the certified sign is zero or negative.

**What evidence would change this verdict:** a pre-registered, audited, live ledger of ≥3 years (or ≥5 years at Sharpe ≤0.6) with disclosed costs, a stated universe, point-in-time data, a fixed decision rule, and an independent custodian or exchange record, compared against volatility-matched passive baselines with a deflated Sharpe ratio reported against the number of trials.

### P2 — Is the change real and not an artifact?

**Verdict for trading: rejected (the apparent change is explained by artifacts). Confidence: high. Verdict for judgmental forecasting: partially supported (a real improvement exists but its baseline is stale and its conversion to returns is unproven). Confidence: medium.**

Each artifact listed in the premise test is documented, not hypothetical:

- **Look-ahead / memorisation.** GPT-4o's pre-cutoff S&P 500 MAPE was 0.61% vs 16.87% post-cutoff; a fake cutoff in the system prompt was ignored with 98% accuracy on "future" GDP; masked Apple earnings calls were identified with 100% firm accuracy (Lopez-Lira, Tang, Zhu, C5). Llama-2 "forecasts" of 2020 risks from 2019 calls mentioned COVID-19 in 6.8% of generations when the no-leak benchmark is 0% (Sarkar & Vafa, C4). A 1-SD increase in Lookahead Propensity raises the LLM news-return effect by 0.077 pp, about 37% of the standalone effect (Gao, Jiang, Yan, C2). Standard LLM "alpha" on 5 tech stocks decayed by −21.77 pp out of sample while point-in-time models were stable (Look-Ahead-Bench, C51, N=5). Randomising only the least-significant digit of financial-statement items dropped GPT-4 earnings-direction accuracy from 60% to 51%, i.e. to chance (Levy, C7, Journal of Accounting Research).
- **Survivorship / universe.** Of 19 closed-loop LLM-agent studies audited, 1 documents universe or survivorship handling, 1 has an explicit transaction-cost model, 2 have time-consistent splits, 0 reach replayable reproducibility (Xia et al., C42). Even the most careful 2026 negative study admits a fixed-current-list survivorship bias that *flatters* active strategies (C10).
- **Short windows.** Arena windows are 2–16 weeks (C16, C17, C18); live academic benchmarks were 2 months at submission (C15) or 12 trading days (C44 real-time arm). Flat Circle, which tracks 11 arenas: **"The median model always loses money, except for long only arenas during periods of increasing equity values"** (C82, Grade D).
- **Regime (beta, not alpha).** TradeRank's nine-season compounding shows 1 of 13 model families ahead of SPY, mostly via crypto exposure, with the explicit caveat that this does not establish stock-picking skill (C83). LLM-Black-Litterman success is **"contingent on its alignment with the prevailing market regime"** (C46).
- **Selection of winners / multiple testing.** Alpha Arena's announced Season 1.5 aggregate and its per-competition rows **"do not reconcile"** (C18 via TradeRank); five independent gpt-4.1 runs all found the same strategy family and 0/5 survived certification (C10); DSR with N=102 trials turned a design Sharpe of 1.69 into an uncertifiable 0.18 (C10).
- **Marketing.** The arena operator's own site says current LLMs are "shockingly bad" at markets while raising $15m to train trading models (C85); the SEC has brought at least four AI-washing actions since March 2024 (C58).

On forecasting the picture differs. ForecastBench's July 2026 update finds several systems **statistically indistinguishable from superforecasters** (Cassi one-sided p = 0.41) and 17 submissions above the superforecaster median on the preliminary board (C30), and Metaculus's Spring 2026 FutureEval shows pros ahead of the top-10 bot team by only 1.25 head-to-head points (p = 0.247, 99 questions) versus −11 to −20 points in 2024–2025 (C32). Two caveats keep this at "partially supported": the ForecastBench superforecaster predictions were last elicited in 2024 and the comparison "grows less reliable over time" (C30); and no study links forecasting Brier gains to realised trading returns, while prediction-market agents lost on every Kalshi run (C20).

**What evidence would change this verdict:** replication of an LLM trading result on strictly post-cutoff data by a party without a stake, with the universe, cost model, number of trials and prompts disclosed; or a forecasting-to-returns bridge study showing that improved Brier scores in a live tournament translate into positive net returns after fees and spreads over several regimes.

### P3 — What is the cause: model capability, scaffolding/configuration, regime, or luck?

**Verdict: scaffolding and evaluation design dominate what is measurable; base-model capability contributes little to trading outcomes (but does to forecasting accuracy); regime and luck account for the remaining dispersion. Confidence: medium.**

Ablations and decompositions that actually exist:

- **Model vs scaffold, paired replay (C19, Grade C, vendor-affiliated):** across 416 captured production scenarios, **frontier models' decision quality was statistically indistinguishable**; a risk slider shifted leverage by +0.425× per level; agent fixed effects absorbed 60% of variance; a leaderboard display boundary routed selection with a 1.75× effect; median leverage was 5.0× in every volatility sextile ("sizing is volatility-blind"). Behaviour was **"driven by interface design more than strategy"** ([Hugging Face / arXiv 2609.05663](https://huggingface.co/papers/2609.05663)).
- **Reasoning effort (C11, Grade B):** nine annual low-vs-baseline reasoning comparisons across DeepSeek, GPT-5.6 and Gemini 3.1 on 2024 US equities with 10 bps costs — all inconclusive; DeepSeek masked-news audit showed replicated harm (−9.0 bps/day, CI [−16.2, −1.8]); **"More reasoning is not necessarily better judgment"** ([arXiv 2609.30705](https://arxiv.org/html/2609.30705v1)). Consistent with Sodha on NIFTY (C12). Contrast: in judgmental forecasting, higher-reasoning variants beat standard versions in 8/8 pairs (C32).
- **Architecture vs backbone (C15, Grade C):** the only live benchmark varying both (4 architectures × 5 backbones, 2 months) claims **"agent architecture dominates trading performance over LLM backbone selection"** — qualitative, costs not reported.
- **Coordination vs reasoning quality (C40, Grade C):** across 210 multi-agent-debate runs, reasoning quality was uncorrelated with Sharpe (r = 0.07, p = 0.29); enriched prompts raised reasoning scores +17.7% without improving returns; a divergence-preserving intervention improved Sharpe by +0.14 (p = 0.028) — **"the dominant driver of performance is the preservation of independent informational signals across agents"**. Debate beat 1/N only 33% of the time with no costs.
- **Tool validation vs free-form (C10):** registry-validated tools yielded 99/100 valid gpt-4.1 proposals vs 0/60 for a JSON-emitting critic without validation; scaffolding changed *validity*, not *alpha*.
- **Prompt structure and human oversight (C23, Grade C):** naive prompts 0.35%/month (IR 0.06, n.s.) → structured prompts 2.24% → CoT with human review 3.04% (IR 0.68) on IBEX-35, live April 2025–January 2026, costs not reported. Direction plausible; magnitude unverified.
- **Code execution for arithmetic (C7, Grade B):** financial-statement tallying 4% → 100% with code execution; DuPont analysis 100%.
- **Retrieval (mixed):** retrieval + fine-tuning gave Brier 0.179 vs 0.206 without retrieval (C35); but news retrieval "did not improve performance" on ForecastBench 2024 (C31); and one fabricated article flips 56% of RAG forecasts (C38).
- **Scenario generation (C48):** portfolio composition and prompt design explained most VaR/CVaR variance (partial η² 0.59/0.79 and 0.26); RAG ≈ 0.
- **Interface and incentive design in retail products (C19, C73):** Robinhood's Cortex team deliberately moved to "one model, one prompt, tools" and says **"when models improve, Cortex improves with them. That's the bet"** — a bet, not a result.

**INFERENCE:** if base-model capability were the driver, the ordering of models would be stable across arenas and tasks. It is not: Qwen won Alpha Arena S1 and HKU, Grok 4.20 won S1.5, MiniMax won AI-Trader US, Gemini won TradeRank's compounding table, and DeepSeek ranged from +4.9% (S1) to −15.1% (HKU). Instability of rank under changed harness, assets and window is the signature of scaffold + regime + noise, not of capability.

**What evidence would change this verdict:** a factorial study holding universe, window, costs and prompts fixed while varying (a) backbone generation, (b) tool set, (c) memory, (d) risk limits, (e) sizing rule, with enough repeated seeds to report confidence intervals per factor; or a demonstration that newer backbones monotonically improve net Sharpe under an unchanged harness across ≥3 regimes.

### Steelman FOR: "AI now genuinely earns"

1. Text-to-signal is real and peer-reviewed: GPT-4 scores on post-cutoff headlines predict drift, especially small caps and negative news, with ~90% hit rate on the (non-tradable) initial reaction (C1, Journal of Financial Economics 2026). A large good-news ratio predicts the market risk premium with 3.55% CER gain after 50 bp costs (C52).
2. Judgmental forecasting parity with superforecasters was reached in 2026 (C30, C32); forecasting is upstream of asset allocation.
3. Properly point-in-time language models retain most of the useful signal (C49, C50), so leakage is not the whole story.
4. Information processing around earnings doubled from R² 8% to ~20% with optimised agentic systems (C54).
5. Live small-sample results are not uniformly negative: some models were profitable in every arena (C16, C17, C18, C82), Mystery Model/Grok 4.20 made money in all four S1.5 contests (C18), and VTB's AI strategy fell 7% while MOEX fell 19.5% in 2026 (C69, Grade D).
6. Human-AI collaboration measurably raised consumer welfare in a bank field experiment (C76) and structured prompting plus human review raised IR from 0.06 to 0.68 live (C23).
7. Institutions with the most data say the tools now generate signals that pass their thresholds (C28, C29), and AI hedge funds did earn ~6%/yr benchmark-adjusted before 2017 (C24).

### Steelman AGAINST: "mostly noise, leakage, hype"

1. Every Grade A/B comparison against buy-and-hold or 1/N fails to certify LLM alpha (C9, C10, C11, C21, C25, C26, C44, C47).
2. Leakage is measured and large: 37% of the headline-return effect co-moves with lookahead propensity (C2); earnings-direction "skill" collapses to chance under digit randomisation (C7); models ignore stated cutoffs (C5); a celebrated ML analyst-forecast alpha of 1.54%/month "erases" once look-ahead is removed (C8).
3. The field's own audits: 1/19 closed-loop agent studies has a cost model, 0/19 are reproducible (C42); 30 studies under-report execution assumptions (C43); a reviewed FinMem +23% became −22% on re-evaluation (C9, C41).
4. Arena results are two-week, N=6–10 contests run by a company raising money to sell trading agents (C17, C18, C85); the aggregate and per-contest numbers do not reconcile (C18).
5. The pre-2017 AI hedge fund edge faded even for early adopters (C24); Eurekahedge's AI index trailed the S&P by 11 pp annualised and was discontinued (C27, secondary).
6. LLM advice concentrates and herds (C22, C53), leverage is volatility-blind (C19), and regulators find retail trust (56%) far ahead of accountability (C59, C66).
7. The forecasting parity result uses human forecasts collected in 2024 (C30) and has not been converted into returns; prediction-market bots lost on every Kalshi run (C20).

**INFERENCE on balance:** the AGAINST case is supported by higher-grade evidence on every point where the two cases meet; the FOR case's best items (C1, C30, C54) are about information processing and forecasting, not about net returns from a trading terminal.

---

## 2. Evidence table

Columns: claim ID | source (link) | type | period | N | costs | leakage controls | grade | key number (verbatim ≤25 words where Grade A/B).

| ID | Source | Type | Period | N | Costs | Leakage controls | Grade | Key number / quote |
|---|---|---|---|---|---|---|---|---|
| C1 | [Lopez-Lira & Tang, JFE 2026](https://ideas.repec.org/a/eee/jfinec/v184y2026ics0304405x26001066.html) | peer-reviewed journal | post-cutoff headlines; dates not in abstract | not reported | not reported (paywalled) | post-knowledge-cutoff design | B/C | "approximately 90% portfolio-day hit rates for the non-tradable initial reaction"; returns decline as LLM adoption rises |
| C2 | [Gao, Jiang, Yan 2025/26](https://arxiv.org/html/2512.23847v1) | preprint, diagnostic | news Jan 2012–Dec 2023; CapEx 2006–2020 | 91,361 headlines; 74,338 firm-quarters | n/a | Lookahead Propensity interaction; Llama-2 post-release placebo | B | 1 SD LAP raises news effect by 0.077 pp, "about 37% of the standalone effect (0.197%)" |
| C3 | [Glasserman & Lin 2023](https://arxiv.org/abs/2309.17322) | preprint | not reported | not reported | not reported | headline anonymisation | C | "the distraction effect has a greater impact than look-ahead bias"; look-ahead not a concern OOS |
| C4 | [Sarkar & Vafa, ICML WS 2025](https://openreview.net/pdf?id=fn9cJkB86T) | workshop paper, diagnostic | calls 2018–2019; elections 2014–2022 | 1,000 + 1,000 calls; 732 races | n/a | compares pre/post-event phrase rates | B | "6.8% of generations included COVID-19" vs 0% no-leak benchmark; "prompting alone is not enough" |
| C5 | [Lopez-Lira, Tang, Zhu 2025](https://arxiv.org/pdf/2504.14765) | preprint, diagnostic | 1990–Feb 2025 | 8,488 pre / 292 post days; 90,123 headlines | n/a | pre/post cutoff, fake cutoffs, masking, embeddings | B | S&P MAPE "0.61% (N=8,488), versus 16.87% post-cutoff (N=292)"; fake-cutoff GDP accuracy 98% |
| C6 | [Kim, Muhn, Nikolaev 2024](https://arxiv.org/html/2407.17866v2) | preprint (Chicago Booth) | 1968–2021; OOS FY2022→2023 | 150,678 firm-years | 10 bps | anonymised statements; identity-guess test (firm 0.07%) | C | GPT CoT 60.35% vs analysts 52.71%; EW Sharpe 3.36 → 2.84 after 10 bps; VW 0.95 |
| C7 | [Levy, J. Accounting Research 2026](https://onlinelibrary.wiley.com/doi/10.1111/1475-679x.70058) | peer-reviewed journal | 1968–2021; cutoffs 1999–2023 | 346,731 firm-years; 1,871 LLM tests | not reported | digit randomisation; yearly-cutoff 410M models | B | accuracy "60% to 51%" after randomising least-significant digit; "GBDTs dominate LLMs" (+2.7 pp) |
| C8 | [Zhang, Zhu, Linnainmaa, RFS 2025](https://academic.oup.com/rfs/article-abstract/38/12/3768/8246070) + [Reply, SSRN 2025](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5154044) | peer-reviewed + reply | not reported | not reported | not reported | identifies look-ahead in BHL horizons | B (contested) | "Removing the bias erases the alpha" (1.54%/mo, t=5.84); reply: double-sort still 1.7%/mo after correction |
| C9 | [Li, Kim, Cucuringu, Ma, KDD 2026 (FINSABER)](https://arxiv.org/html/2505.07078v5) | conference paper | 2004–2024 rolling; 100+ symbols | 7,000+ equities incl. delisted | Moomoo $0.0049/share, $0.99 min | historical constituents incl. delisted; LLM pretraining leakage not eliminated | B | "previously reported LLM advantages deteriorate significantly"; B&H vs FinMem p=3.0e-6; alphas p>0.34 |
| C10 | [Gençay 2026](https://arxiv.org/pdf/2608.27734v1) | preprint, independent | design 2017–21 / eval 2022–25; ETFs 2007–16 / 2017–25 | 453 stocks; 39 ETFs; N trials 9–102 | 1 bp + 2 bp + sqrt impact + 50 bp borrow | registry-validated features; 1-day lag; PIT liquidity universe; DSR/PBO | B | passive certified; "no LLM-discovered strategy was certified"; best Sharpe 0.18, CI [−0.80, +1.14] |
| C11 | [Chen & Wang 2026, "Price of Thought"](https://arxiv.org/html/2609.30705v1) | preprint | 2024 US equities, 241 days | 808,800 asset predictions; 3 backbones | 10 bps one-way (5/20/50 sensitivity) | masked news; opaque IDs; cutoffs not reported | B | "additional reasoning does not produce a reliable improvement in net portfolio returns"; 13/18 portfolios negative |
| C12 | [Sodha 2025](https://arxiv.org/abs/2511.08608) | preprint | rolling 48m/1m, dates NR | universes 5–36 | yes, rates NR | not reported | C | "Portfolio results under transaction costs do not support a net advantage for the TLLM" |
| C13 | [StockBench 2025/26](https://arxiv.org/abs/2510.02209) | preprint | multi-month, dates NR | not reported | not reported | "contamination-free" asserted | C | "most models struggle to outperform the simple buy-and-hold baseline" |
| C14 | [AI-Trader 2025](https://www.alphaxiv.org/abs/2512.10971) | preprint, live | dates NR | 6 LLMs; 100 + 50 + 10 assets | not reported | temporal filtering of tools | C | MiniMax +9.56%; GPT-5 +1.56% vs QQQ +1.87%; "No agent beat SSE-50" |
| C15 | [When Agents Trade 2025](https://www.alphaxiv.org/abs/2510.11695) | preprint, live | Aug–Sep 2025 (2 months) | 4 assets; 4 archs × 5 backbones | not reported | live; expert-checked news | C | InvestorAgent/GPT-4.1 +40.83% TSLA, Sharpe 6.47; "agent architecture dominates… over LLM backbone" |
| C16 | [HKU AIEL press release, Jul 2026](https://www.hkubs.hku.hk/media/press-release/testing-ai-in-the-real-world-hku-business-school-released-ai-agents-trading-performance/) | university press release, live | 6 weeks from Apr 2026 | 10 agents | not reported | live | C/D | "+9.9% for Qwen to −15.1% for DeepSeek"; no benchmark; internal inconsistency on winner |
| C17 | [Alpha Arena S1 via Protos](https://protos.com/llm-crypto-trading-contest-finds-llms-cant-trade-crypto/) + [TradeRank snapshot](https://www.traderank.ai/alpha-arena-leaderboard) | news + vendor snapshot (secondary; primary nof1.ai) | 18 Oct–3 Nov 2025 | 6 models, $10k each | fees reported ($1,654 Qwen) | none | D | Qwen +22.31%, DeepSeek +4.89%, GPT-5 −58.74%; win rates 25–30% |
| C18 | [nof1 founder X post](https://x.com/jay_azhang/status/1996984618751611006) + TradeRank + [Business Standard](https://www.business-standard.com/amp/markets/news/ai-bots-auditioning-for-wall-street-trading-are-mostly-losing-money-126050701793_1.html) | vendor claim + news | 19 Nov–3 Dec 2025 | 8 models × 4 contests = 32 entries | not reported | none | D | Grok 4.20 "up 12% on avg"; 6 of 32 entries profitable; portfolio lost ~1/3; figures "do not reconcile" |
| C19 | [Barton et al. (DXRG) 2026](https://huggingface.co/papers/2609.05663) | preprint, vendor-affiliated, pseudonymous author | Feb–Mar 2026 (21 days) + Jun–Aug 2026 | 3,505 vaults; 500–599 agents; 14,596 fills; 416 replay scenarios | "common-fee restatement", amounts NR | none | C | "neither fleet shows a directional edge"; 41% win rate vs 50% retail; frontier models indistinguishable |
| C20 | [Prediction Arena 2026](https://arxiv.org/html/2604.07355) | preprint, live | 12 Jan–9 Mar 2026 (57 days) | 6 live models; 2,916 trades | fees in EV checks | prospective | C | Kalshi returns "−16.0% to −30.8%"; all lost; drawdowns 16–31% |
| C21 | [Carlin, Israelsen, Wazzan, NBER 2026](https://www.nber.org/papers/w35153) | NBER WP (not peer-reviewed), prospective | daily, dates NR | not reported | not reported | prospective recommendations | B (design) / numbers NR | "do not appear to earn statistically-significant abnormal returns"; driven by media attention |
| C22 | [Winder, Hildebrand, Hartmann, PLOS ONE 2025](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0325459) | peer-reviewed | Jul 2023–Jan 2025 | 270 prompts; N=180 per study | not reported | not reported | B | "over 93%" US equities vs 59% benchmark; 51% in active funds/single stocks; Copilot Sharpe lower (β=−1.14) |
| C23 | [Mykhalyuk 2026](https://www.alphaxiv.org/abs/2603.19944) | preprint, live | Apr 2025–Jan 2026 | IBEX-35; N NR | not reported | monthly information cutoff | C | naive 0.35%/mo IR 0.06 (n.s.) → structured 2.24% → CoT+human 3.04% IR 0.68 |
| C24 | [Chen, Sialm, Xu, NBER 2026](https://www.nber.org/system/files/working_papers/w35273/w35273.pdf) | NBER WP (not peer-reviewed) | 2006–2024 | 324,952 fund-months; 89 AI funds of 7,896 | n/a (net fund returns) | prior-year-end classification; FH/AQR factors | B | "49.6 basis points per month" FH-alpha before 2017, none after; AI pair alpha correlation 0.021 vs 0.124 |
| C25 | [Smith & Wyatt, J. Investing 2025](http://economics-files.pomona.edu/GarySmith/papers/DisappointingAIFunds.pdf) | journal | Oct 2017–Dec 2023 | 10 fully-AI + 44 partly-AI funds | fund NAV net of fees; trading costs/taxes ignored | live fund record | B | "None of the AI funds did as well as the S&P 500"; fully-AI 3.63% vs 12.45%; Sharpe 0.19–0.27 vs 0.60 |
| C26 | [24/7 Wall St, Aug 2026](https://247wallst.com/investing/2026/08/26/can-ai-help-you-beat-the-stock-market-the-answer-may-surprise-you/) + [ETFRC AIEQ](https://www.etfrc.com/AIEQ) | news (secondary) + data vendor | Oct 2017–Aug 2026 | 1 fund | expense 75 bp | live | B (verifiable NAV) | AIEQ "100.2% since inception, versus roughly 199.7%" S&P; 9.9% annualised since inception |
| C27 | [MarketWatch/Morningstar, Sep 2025](https://www.morningstar.com/news/marketwatch/2025090265/stock-traders-six-favorite-ai-tools-are-faring-much-worse-than-the-sp-500) | news (secondary; primary Eurekahedge index) | 5y/10y to Jan 2025 | index | n/a | live | C | Eurekahedge AI HF index trailed S&P by 11 pp (5y) and 8 pp (10y) annualised; discontinued Jan 2025 |
| C28 | [AI Street, Aug 2026](https://www.ai-street.co/p/how-bridgewater-is-building-an-artificial) | paid newsletter (secondary) | since late 2023, dates NR | ~$4.5bn | not reported | none | D | AIA Macro "11.3% annualized since inception"; no benchmark, no risk metrics, no verification |
| C29 | [Man Group Insights](https://www.man.com/insights/what-ai-can-do-for-alpha) | vendor | not reported | not reported | not reported | none | D | "dozens of viable concepts within minutes"; "not… ready to run unsupervised"; no quantified alpha |
| C30 | [FRI ForecastBench, Jul 2026](https://forecastingresearch.substack.com/p/ai-models-have-likely-reached-parity) | benchmark operator post | leaderboard to 16 Jul 2026; superforecasters elicited 2024 | ≥225 resolved Qs per submission | n/a | live forward questions | B | Cassi one-sided p = 0.41 vs superforecasters; "17 submissions now rank above superforecasters on our preliminary leaderboard" |
| C31 | [Karger et al., ForecastBench paper 2024](https://arxiv.org/pdf/2409.19839v2) | preprint | 2024 | 1,000 Qs; 200 human-comparison | n/a | forward questions | B | superforecasters Brier "0.093, versus 0.107 for the public and 0.111 for… Claude 3.5 Sonnet" (p=0.01); news retrieval did not help |
| C32 | [Metaculus FutureEval Spring 2026](https://www.lesswrong.com/posts/wZBbDqzfBjYG58CxK/futureeval-spring-results-pros-beat-bots-but-the-gap-is) | platform analysis | 7 Jan–15 Apr 2026 | 173 bots; 297 scored Qs; 99 shared; 10 pros | n/a | pros' forecasts hidden | B | bot team "−1.25 head-to-head points" (95% CI −4.87 to 2.37, p=0.247); higher reasoning beat standard 8/8 |
| C33 | [explainx on Metaculus Cup Summer 2026](https://www.explainx.ai/blog/ai-beats-forecasters-metaculus-cup-coverage-2026) | blog (secondary; primary Metaculus) | resolved 5 Sep 2026 | not reported | n/a | n/a | C | bots 1st, 2nd, 5th; scoring "mixes judgement with throughput" |
| C34 | [Schoenegger et al., Science Advances 2024](https://www.science.org/doi/10.1126/sciadv.adp1528) | peer-reviewed | Oct 2023–Jan 2024 | 31 Qs; 12 LLMs; 925 humans | n/a | real-time forecasts | B | ensemble Brier "0.20 versus 0.25" baseline; vs crowd 0.19 "statistically indistinguishable" (p=0.85) |
| C35 | [Halawi et al. 2024](https://arxiv.org/html/2402.18563v1) | preprint | test Qs after Jun 2023 | 914 test Qs | n/a | post-cutoff Qs; dated retrieval | B | system Brier "0.179, crowd 0.149"; no-retrieval 0.206; combined 0.146 |
| C36 | [Lu 2025](https://arxiv.org/html/2507.04562) | preprint | Jul–Dec 2024 | 334 + 130 Qs | n/a | cutoffs before Jul 2024 | C | o3 Brier 0.1352 beats crowd 0.149, not experts; narrative prompting worse; internal inconsistencies |
| C37 | [Aitchison et al., ICML WS 2026](https://arxiv.org/pdf/2606.29661v1) | workshop preprint | May–Jul 2025 | 113 Qs | n/a | cutoffs before tournament | C | "samples from… frontier LLMs are highly correlated"; diversity, not volume, drives ensemble gain |
| C38 | [Lu & Zhang 2026, Corroboration Illusion](https://arxiv.org/html/2609.22246v1) | preprint, diagnostic | Jul 2024–Aug 2025 Qs | 500 Qs; 17.4M articles | n/a | 0/10,000 retrieved articles violated cutoff | B | one fabricated article flipped "56%" of forecasts; Brier 0.18 → 0.37; "The forecaster ignores provenance" |
| C39 | [Huang et al., ICLR 2024](https://proceedings.iclr.cc/paper_files/paper/2024/hash/8b4add8b0aa8749d80a34ca5d941c355-Abstract-Conference.html) | peer-reviewed conference | n/a | n/a | n/a | n/a | B | "LLMs struggle to self-correct their responses without external feedback"; "performance even degrades" |
| C40 | [Huang et al. 2026, MAD trading](https://arxiv.org/html/2609.29701v1) | preprint | 2021Q4–2025Q3 | 210 runs; 35 scenarios | not included | not reported | C | reasoning quality vs Sharpe r=0.07 (p=0.29); debate beat 1/N in 33% of 455 obs |
| C41 | [Nguyen & Pham 2026](https://www.alphaxiv.org/abs/2603.27539) | survey preprint | n/a | 12 MAS + 2 single-agent | n/a | n/a | C/D | Coordination Primacy is "a falsifiable research hypothesis"; FinMem 23% → −22% (secondary, cites C9) |
| C42 | [Xia et al. 2026, Agentic Trading audit](https://arxiv.org/html/2605.19337v1) | audit survey preprint | studies 2022–Mar 2026 | 77 studies; 19 closed-loop | n/a | n/a | B (audit) | "1/19 explicit transaction-cost model… 1/19 universe/survivorship… 0/19 R3"; "no study reaches R3 reproducibility" |
| C43 | [Yao & Zheng 2026](https://arxiv.org/abs/2606.08285) | audit preprint | n/a | 30 studies | n/a | n/a | C | "architecture reporting is generally clearer than the evaluation assumptions" |
| C44 | [PortBench 2026](https://arxiv.org/html/2605.27887v3) | preprint | 2015–2025; windows 2015–16, 2020, 2022, 2024; live 16–31 Jul 2026 | 183 instruments; 10 LLMs | 10 bps slippage + 5 bps commission | PIT data; forward returns withheld | B | "90% of model–profile cases in the 2024 test window failed to beat equal-weight"; 39/120 across periods |
| C45 | [Mantshimuli & Mwamba, JRFM 2026](https://www.mdpi.com/1911-8074/19/5/320) | journal (MDPI) | tune 2016–21; OOS Jan 2022–Mar 2025 | 50 stocks; 7 LLMs | 10 bps | non-overlapping tuning; base cutoffs NR | C | best LLM Sharpe 0.708 post-cost vs DL-MVO 1.319, FinBERT-BL 0.921; LLMs "generally beat naive diversification" |
| C46 | [Lee et al., CIKM 2025, LLM-BL](https://arxiv.org/html/2504.14345v2) | conference | test Sep 2024–Jun 2025 | 50 stocks; 100 queries/stock | 0.1% of weight change | cutoffs asserted pre-Jun 2024, not verified | C | Llama Sharpe 1.2286 vs EW 0.8937, MVO 0.2793; "contingent on its alignment with the prevailing market regime" |
| C47 | [DeMiguel, Garlappi, Uppal, RFS 2009](https://academic.oup.com/rfs/article/22/5/1915/1592901) | peer-reviewed | 1963–2004 datasets | 14 models; 7 datasets | 50 bps | rolling OOS | B | "none is consistently better than the 1/N rule"; >3,000 months needed for 25 assets |
| C48 | [Soleimani 2025](https://arxiv.org/html/2512.07867v1) | preprint | scenario Q4 2026; data 2000–2025 | 627 + 617 + 307 scenarios | not reported | frozen artifacts | C | "portfolio composition and prompt design dominate risk variance"; RAG "only marginal effects" |
| C49 | [Kelly, Malamud, Schwab, Xu, NBER 2026](https://www.nber.org/papers/w35247) | NBER WP (not peer-reviewed); AQR affiliations | checkpoints 2013–2024 | 4B params, 1T tokens | not reported | chronological pretraining "by construction" | C | PIT embeddings "robust positive Sharpe ratios… close to full-sample counterparts"; values NR |
| C50 | [He, Lv, Manela, Wu 2025, ChronoGPT](https://arxiv.org/pdf/2502.21206v3) | preprint | 2008–Jul 2023 | not reported | not reported | yearly vintages; president/event recall tests 0–4/78 post-cutoff | C | Sharpe "4.80 and 4.92, versus 4.90 for Llama 3.1"; lookahead "relatively modest" here; daily-rebalanced deciles |
| C51 | [Benhenda 2026, Look-Ahead-Bench](https://arxiv.org/html/2601.13770v1) | preprint, proof-of-concept | Apr–Sep 2021; Jul–Dec 2024 | 5 stocks | not reported | PIT vs standard LLM | C/D | DeepSeek 3.2 alpha decay "−21.77 pp"; PIT-Large +1.30 pp; momentum beats both |
| C52 | [Chen, Tang, Zhou, Zhu 2025](http://arxiv.org/pdf/2502.10008) | preprint | 1996–2022; OOS 2006–2022 | 84,535 WSJ articles | 50 bps | GPT-3.5 cutoff Sep 2021 inside test window; weekly post-cutoff check | C | CER gain "3.55% after 50-basis-point transaction costs"; Sharpe 0.51 vs 0.30; DeepSeek no forecast power |
| C53 | [HBS Working Knowledge on Cao, Wang, Xiang](https://www.library.hbs.edu/working-knowledge/chatgpt-vs-deepseek-what-chinese-stocks-reveal-about-ais-limits) | news on HBS WP 26-013 (secondary) | prompts Jun–Jul 2024 → Dec 2024 | 4,978 Chinese firms | not reported | prospective 6-month | B (design) | ChatGPT prices "about 12.5% higher"; errors "13% larger"; local news removes bias |
| C54 | [Koijen & Levy, NBER 2026](https://www.nber.org/papers/w35431) | NBER WP (not peer-reviewed) | not reported | not reported | not reported | "real-time, out-of-sample" asserted | C | "R2 increasing from 8% to close to 20%" — contemporaneous explanation, not tradable |
| C55 | [McLean & Pontiff, JF 2016](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365) | peer-reviewed | to ~2013 | 97 predictors | not reported | OOS vs post-publication | B | "returns are 26% lower out-of-sample and 58% lower post-publication" |
| C56 | [Harvey, Liu, Zhu, NBER/RFS 2016](https://www.nber.org/papers/w20592) | peer-reviewed | 1967–2014 | hundreds of factors | n/a | multiple-testing framework | B | "t-ratio greater than 3.0" required; "most claimed research findings in financial economics are likely false" |
| C57 | [Bailey & López de Prado 2014, DSR](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) | journal (JPM) | method | worked example T=1250 | n/a | n/a | B (method) | "Without this information [number of trials], it is impossible to assess the relevance of a backtest" |
| C58 | [SEC 2024-36](https://www.sec.gov/newsroom/press-releases/2024-36); [SEC LR-26282 (Nate)](https://www.sec.gov/enforcement-litigation/litigation-releases/lr-26282); [DLA Piper on Presto](https://www.dlapiper.com/en-us/insights/publications/ai-outlook/2025/sec-settlement-highlights-continued-focus-on-ai-washing) | regulator documents + law-firm note | 2019–2025 | 4 actions | n/a | n/a | A (fact) | Delphia $225k + Global Predictions $175k; Nate "over $42 million" raised on false AI claims; Presto cease-and-desist |
| C59 | [FCA press release, 27 Aug 2026](https://www.fca.org.uk/news/press-releases/young-investors-trust-ai-more-tv-or-celebrities) | regulator survey | 24 Jul 2026 | 666 UK 18–40 | n/a | n/a | B (survey) | 56% trust AI tools; "Almost half (44%) mistakenly believe AI-generated financial information is regulated" |
| C60 | [ESMA warning 2025](https://www.esma.europa.eu/sites/default/files/2025-03/ESMA_Warning_on_the_use_of_AI_-_EN.pdf); [ESMA TRV Feb 2026](https://www.esma.europa.eu/sites/default/files/2026-02/ESMA50-481369926-30599_TRV_Risk_Analysis_AI_adoption_and_trends_in_securities_markets.pdf) | regulator | survey Jun–Sep 2025 | 728 firms, 19 countries | n/a | n/a | B (survey) | 45% no AI use cases; "77% involved low or no autonomy"; 10 algo-trading and 3 HFT use cases; "no one and nothing… can accurately predict financial markets" |
| C61 | [IOSCO CR Mar 2025](https://www.iosco.org/library/pubdocs/pdf/IOSCOPD788.pdf) | regulator consultation | surveys 2024 | 30 members/SROs; 184 AMCC | n/a | n/a | B | "evidence of potential collusive or scheming behavior risk appears theoretical at present"; no evidence of complex AI at scale in trading |
| C62 | [Bank of England FSiF, Apr 2025](https://www.bankofengland.co.uk/financial-stability-in-focus/2025/april-2025) | regulator | 2024 survey | not reported | n/a | n/a | B | "55% of… AI use cases involve some autonomous decision-making, but only 2% are fully autonomous"; "no single technique that outperforms another" |
| C63 | [IMF GFSR Oct 2024, Ch. 3](https://www.imf.org/-/media/files/publications/gfsr/2024/october/english/ch3.pdf) | IMF report | 2007–2024 panel | 235 stocks; 3 AI ETFs | n/a | n/a | B | AI-powered ETFs "less than $1 billion" AUM; AI ETF turnover rose in March 2020; "Most current use of AI appears to be an extension of existing trends" |
| C64 | [FSB, Nov 2024](https://www.fsb.org/uploads/P14112024.pdf) | regulator | n/a | n/a | n/a | n/a | B | "limited information about the actual strategies of hedge funds"; herding and flash-crash risk flagged, not measured |
| C65 | [Bank of Russia consultation, Nov 2025](https://cbr.ru/Content/Document/File/185193/Consultation_Paper_20112025.pdf) | regulator survey | Jul 2025 | 252 organisations | n/a | n/a | B (survey) | investment recommendations in brokerage 35%; portfolio formation 28%; trade execution 0%; "общий уровень применения ИИ в специальных функциях пока остается низким" |
| C66 | [Bank of Russia ORFR, Aug 2026](https://cbr.ru/Collection/Collection/File/62360/ORFR_2026-8.pdf) | regulator | Aug 2026 | n/a | n/a | n/a | B | "модели ИИ до сих пор периодически выдают недостоверные данные"; herd-behaviour risk from common AI signals; cites FCA 56% |
| C67 | [HSE news on Lysenok 2026](https://www.hse.ru/en/news/research/1165996693.html) | university news on journal paper (secondary) | 2014–2025, 10-min bars | 10 MOEX stocks | not reported | not reported | C/D | LightGBM: simulated profitability "from 6.48% to 13.68%"; forecast errors −15% |
| C68 | [Khubiyev & Semenov 2025](https://arxiv.org/html/2503.08696) | preprint | train Jul 2022–Mar 2024; test Mar–Aug 2024 | 18 of 176 stocks; 79,555 articles | not reported | news before market open; chronological split | C | MAPE 0.397% → 0.256% (abstract says 55%, implied 35.5%); accuracy 48.6% < LSTM 52.0% |
| C69 | [Market Power on VTB AI strategy, 2026](https://marketpower.pro/post/finalnye-itogi-testirovaniia-strategii-intellekt); [Банковское обозрение Apr 2026](https://bosfera.ru/sites/default/files/read_to_pdf/bo_04_april_2026-38-42.pdf) | blog + magazine (vendor figures) | since Mar 2026; since 2025 | 1 strategy | fee excluded | none | D | −7% vs MOEX −19.5% since Mar 2026; VTB claims +51.8% since launch, +7.1% vs MOEX TR since 2025 |
| C70 | [Smart-Lab test, Jul 2026](http://smart-lab.ru/mobile/topic/1332040/) | blog, product-affiliated | Jun–Jul 2026 | 10 AIs; 1 portfolio | n/a | web search on | D | "восемь советовали держать акцию без дивидендов" (8/10 missed cancelled PhosAgro dividend); Russian models caught it |
| C71 | [РБК Инвестиции, 5 Oct 2026](https://www.rbc.ru/quote/05/10/2026/6ac375d99a7947356c7d9b9d) | news | 2026 | 8+ issuers | n/a | n/a | fact | MOEX marked Sovcomflot, Surgutneftegaz, Bashneft, NMTP and others for incomplete disclosure; deferral ended 1 Oct 2026 |
| C72 | [MOEX ISS API page](https://www.moex.com/a2193) | exchange documentation | n/a | n/a | n/a | n/a | fact | data "только для ознакомления"; delayed without subscription; other use requires contract with MOEX |
| C73 | [Robinhood Cortex blog, Aug 2026](https://robinhood.com/us/en/careers/blog/loop-stays-dumb-so-the-model-can-be-smart/) | vendor engineering blog | n/a | n/a | n/a | n/a | D | "The loop stays dumb so the model can be smart"; no evaluation results; informational-only disclaimer |
| C74 | [Zhu & Cai 2026, review](https://arxiv.org/html/2609.04917v1) | critical review preprint (secondary for cited studies) | literature to 31 Aug 2026 | n/a | n/a | n/a | review | "no general AI architecture is shown to deliver persistent, cross-regime, capacity-aware net alpha" |
| C75 | [Sinha et al. 2025](https://arxiv.org/html/2509.09677v1) | preprint, synthetic | n/a | 50,000-step rollouts | n/a | programmatic generation | C | "models become more likely to make mistakes when the context contains their errors from prior turns"; Qwen3-32B <50% within 15 turns |
| C76 | [Yang, Bauer, Li, Hinz 2025](https://ideas.repec.org/p/arx/papers/2506.03707.html) | preprint, field experiment | not reported | not reported | n/a | n/a | B (design) / numbers NR | human-AI advice followed more, "higher material welfare"; human final say "does not compromise its quality" |
| C77 | [Stanford GSB on deHaan et al. 2025](https://www.gsb.stanford.edu/insights/ai-analyst-made-30-years-stock-picks-blew-human-investors-away) | news on working paper (secondary) | model 1980–90; sim 1990–2020 | ~3,300 funds; 170 variables | not reported | model built on prior decade | C | AI adjustments "$17.1 million per quarter" vs $2.8m human alpha; retrospective; costs NR |
| C78 | [Tait & Pisaneschi, CFA Institute Sep 2026](https://rpc.cfainstitute.org/sites/default/files/docs/research-reports/rpc_tait_managing-llm-bias-in-investing_online.pdf) | industry research report | hypothetical scenarios | 900 prompts/model; 9 models | n/a | n/a | C | framing score 0.2444 → 0.0750 with both-perspectives prompt (p<0.001); defining bias: no effect (p=1.00) |
| C79 | [CNBC on Chatterjee, Cude, Nicolini, JFP 2026](https://www.cnbc.com/2026/07/07/ai-personal-finance-advice.html) | news on journal article (secondary) | Aug 2025 | 7 platforms; 3 scenarios | n/a | n/a | C | "substantial variation in guidance" on allocation; "helpful starting point" only |
| C80 | [WashU Olin on Martin, Chang, Dong, Zhou 2025](https://olin.washu.edu/about/news-and-media/news/2025/04/chatgpt-level-playing-field-retail-investors.php) | news on working paper (secondary) | 2010–; post-Nov 2022 | 19 years of calls | not reported | outage natural experiment | C | retail trading aligned with short sellers' AI-sentiment after ChatGPT; "during outages, it almost went away" |
| C81 | [Rahimikia & Drinkall page](https://www.felixdrinkall.com/publication/fintext_2024/) + C50 | preprint page | 2007–2023 vintages | not reported | not reported | year-specific models | D (flag) | claims year-specific models beat Llama ~50× larger; He et al. state the earlier models "were retracted" |
| C82 | [Flat Circle, Jim Moran](https://blog.flatcircle.ai/p/ai-trading-arenas) | blog | 2025–May 2026 | 11 arenas | not reported | none | D | "The median model always loses money, except for long only arenas during periods of increasing equity values" |
| C83 | [TradeRank blog, Mar/Oct 2026](https://www.traderank.ai/blog/can-ai-beat-the-market) | vendor paper-trading arena | 22 Dec 2025–12 Sep 2026 | 13 families; 56 models; 2,826 trades | 0.1%/trade (benchmark no fee) | none | D | Gemini "only one of 13 model families ahead of the S&P 500"; "does not establish stock-picking skill" |
| C84 | [Business Standard (Bloomberg syndication), May 2026](https://www.business-standard.com/amp/markets/news/ai-bots-auditioning-for-wall-street-trading-are-mostly-losing-money-126050701793_1.html) | news | Q4 2025–2026 | see text | not reported | none | D | "LLMs can't really make money by themselves" (Izydorczyk); Intelligent Alpha: ChatGPT 68% earnings-direction accuracy Q4 2025 |
| C85 | [nof1.ai](https://nof1.ai/) | vendor site | n/a | n/a | n/a | n/a | D | current LLMs "shockingly bad" at markets; backed by Village Global, Jane Street angels; $15m raised (C18 source) |
| C86 | [TradingAgents 2024/25](https://arxiv.org/abs/2412.20138) | preprint | not reported | not reported | not reported | not reported | D | "notable improvements in cumulative returns, Sharpe ratio, and maximum drawdown" — no values in abstract; window NR |
| C87 | [ETFRC GPT (Intelligent Alpha Atlas)](https://www.etfrc.com/GPT) | data vendor | 17 Sep 2024–31 Aug 2026 | 1 fund | 69 bp + 46 bp spread | live | C | since inception total return 17.4%, vol 20.4%; benchmark-relative return not reported on page |
| C88 | [ESMA/ILB/Turing LLMs in Finance 2025](https://www.turing.ac.uk/sites/default/files/2025-07/llms_in_finance_-_ilb_esma_turing_report.pdf) | regulator-affiliated workshop report | Jun 2024 | 38 experts; 32 survey | n/a | n/a | C | LLMs "augmenting the capabilities of experts rather than replacing them"; "not the right tool" in some cases |

---

## 3. What separates winners from losers — mechanisms ranked by evidence strength

Ranking criterion: grade of the best supporting source × consistency across independent sources. "Winner" here means a system whose measured outcome is better *relative to its own baseline*, since no system is certified to beat passive baselines.

| Rank | Mechanism | Direction | Best evidence | Grade | Consistency |
|---|---|---|---|---|---|
| 1 | **Leakage-free evaluation vs leaky evaluation** | Leaky setups manufacture "winners"; honest setups remove them | C7, C8, C9, C10, C2, C5, C51 | B | 7/7 sources agree |
| 2 | **Deterministic code for every number** | Arithmetic errors drive wrong fundamentals | C7 (4% → 100% with code); C19 (volatility-blind sizing) | B | consistent |
| 3 | **Passive/1/N baseline discipline** | Systems that are not benchmarked against 1/N and buy-and-hold look better than they are | C44, C47, C9, C10, C82 | B | consistent |
| 4 | **Risk limits, sizing and turnover control imposed outside the LLM** | Fee drag and leverage drive losses; low-turnover LLM strategies survive costs | C17 ("PnL… dominated by trading costs"), C19, C45 ("low-turnover LLM strategies retain their competitiveness post-costs"), C44 (under-trading universal), C16 ("acting more frequently does not necessarily lead to better outcomes") | B/C | consistent |
| 5 | **Fresh, post-cutoff, local-language information** | Signal exists in text the model has not seen; missing local news biases output | C1, C53, C70 | B | consistent |
| 6 | **Preserving independent signals (ensemble diversity) rather than more reasoning** | Diversity of sources/models helps; reasoning effort and self-critique do not | C34, C37, C40, C11, C12, C39 | B/C | consistent across forecasting and trading |
| 7 | **Human sign-off on a structured process** | Human review raises IR and welfare in the two studies that test it | C23, C76 | C/B(design) | 2 sources, small |
| 8 | **Retrieval with provenance controls** | Retrieval helps Brier (C35) only if poisoning is controlled (C38); otherwise neutral (C31) | C35, C38, C31 | B | mixed |
| 9 | **Interface/incentive design of the harness** | Leaderboards, risk sliders and defaults determine behaviour | C19, C73 | C/D | 1 quantitative source |
| 10 | **Base-model generation** | Weak effect on trading; moderate on forecasting | C19 (indistinguishable), C15 (architecture > backbone), C32 (reasoning helps forecasting 8/8) | C | mixed by task |
| 11 | **Multi-agent coordination per se** | Hypothesis only; one preprint claims 15–30% Sharpe drop on removal (secondary), others find debate ≈ noise | C41, C40, C15 | C/D | contested |
| 12 | **Regime alignment** | Long-only in rising markets and crypto beta are the dominant "winner" explanation in arenas | C82, C83, C46 | D | consistent but low grade |

**INFERENCE:** mechanisms 1–4 are about *evaluation and plumbing*, not intelligence. The systems that look like winners in Grade B studies are those that (a) cannot see the future, (b) compute with code, (c) trade little, (d) are compared honestly and still show nothing certifiable. That is the honest state of the art.

---

## 4. Consensus / contested / unknown

### Consensus (≥3 independent sources, ≥1 Grade B, no Grade B contradiction found)

- LLMs memorise financial history and ignore prompted cutoffs; masking is insufficient (C2, C4, C5, C7, C51).
- No LLM trading agent has certified net alpha over buy-and-hold or 1/N across regimes (C9, C10, C11, C13, C44, C74).
- Public AI-managed funds have underperformed the S&P 500 over their lives (C25, C26, C27) and AI hedge funds' pre-2017 edge faded (C24).
- Reporting standards in LLM-trading papers are inadequate: costs, universe, splits and artifacts are mostly missing (C42, C43).
- LLM arithmetic on multi-number financial tables is unreliable without code execution (C7).
- LLM advice to retail concentrates portfolios (US, tech, active, recently-traded names) (C22) and shows home/information bias (C53).
- Regulators find autonomous AI trading rare in production and herding a theoretical, unmeasured risk (C60, C61, C62, C63, C64, C65).
- Retail trust in AI exceeds its regulatory status (C59, C66).
- Intrinsic self-correction does not improve reasoning (C39); more test-time reasoning does not improve net trading returns (C11, C12).
- 1/N and buy-and-hold remain hard to beat for any optimiser (C47) and for LLM allocators (C44).

### Contested (Grade B sources on both sides, or a Grade B result with a credible Grade B challenge)

- **Does GPT fundamental analysis beat analysts?** Kim/Muhn/Nikolaev (C6: 60.35% vs 52.71%) vs Levy (C7: collapses to chance under digit noise; GBDT better). Status: the C6 effect is at best partly arithmetic/look-ahead; the headline is not robust.
- **Does ML beat analysts after look-ahead correction?** Zhang/Zhu/Linnainmaa (C8: "erases the alpha") vs van Binsbergen/Han/Lopez-Lira reply (C8: 1.7%/mo persists in double sorts). Status: unresolved; both sides acknowledge look-ahead in the original.
- **How much of the headline-return effect is lookahead?** Glasserman & Lin (C3: distraction > look-ahead) vs Gao et al. (C2: ~37% co-moves with lookahead propensity) vs Lopez-Lira & Tang (C1: post-cutoff, effect real). Status: a real post-cutoff effect probably exists but is smaller than in-sample estimates and decays with adoption.
- **Point-in-time models: how much signal survives?** Kelly et al. (C49: "close to full-sample") and ChronoGPT (C50: Sharpe 4.92 ≈ 4.90) vs Look-Ahead-Bench (C51: standard LLM alpha decays −21.8 pp). Status: both can be true — PIT models retain signal *and* standard models carry large leakage; C49 has AQR conflicts and no numbers.
- **Does retrieval help forecasting?** Halawi (C35: yes) vs ForecastBench 2024 (C31: no) vs Corroboration Illusion (C38: it creates an attack surface).
- **Does reasoning help?** Yes for judgmental forecasting (C32: 8/8) and arithmetic with tools (C7); no for net trading returns (C11, C12, C40).
- **Do multi-agent architectures matter?** C15 (yes, qualitative) vs C40 (reasoning quality irrelevant; divergence matters) vs C41 (hypothesis only).
- **LLM portfolio construction vs classical.** C46 (LLM-BL beats EW over 9 months) vs C44 (90% fail vs EW in 2024) vs C45 (LLM < DL-MVO and FinBERT-BL but > EW). Status: regime- and window-dependent; no cross-regime win.
- **Forecasting parity.** C30 (parity) vs C32 (pros still ahead, n.s.) vs C33 (bots win Cup under throughput-weighted scoring). Status: parity on accuracy is plausible as of mid-2026; superiority is not shown.

### Unknown (no Grade A/B evidence either way)

- Whether any private institutional LLM-driven strategy earns net alpha (C28, C29, C64: "limited information").
- Whether the forecasting gains convert into tradable returns in any market.
- Whether LLM herding is measurable in prices (regulators say theoretical; C24 finds *lower* comovement among AI hedge funds).
- Any Grade A/B result on the Russian market for LLM-based systems (C67–C70 are C/D).
- Long-run (≥3-year) live performance of any 2025–2026 agent framework.
- The exact test window and cost treatment of C1 (paywalled full text).

---

## 5. Practice catalogue

Ranked by evidence strength × feasibility under the retail constraints (one person, no terminal, consumer LLM subscriptions, weekly–monthly decisions, ~20-month horizon, manual execution, MOEX stocks and bonds). Includes practices that do **not** work.

| # | Practice | What it does | Evidence grade (IDs) | Transfers to retail + MOEX? | Cost/effort | Risks |
|---|---|---|---|---|---|---|
| 1 | **Every number computed by deterministic code; LLM only reads, extracts, explains** | Removes the dominant LLM failure (arithmetic, volatility-blind sizing) | B (C7, C19) | Yes, fully | Low: spreadsheet/Python | False confidence if code is wrong; keep unit tests |
| 2 | **Leakage audit before trusting any backtest or "AI said X would happen"** | Checks that inputs predate the decision; treats any pre-cutoff "forecast" as recall | B (C2, C4, C5, C7, C8) | Yes | Low: timestamp discipline | None; but requires rejecting most vendor backtests |
| 3 | **Passive baselines first: 1/N, buy-and-hold, MOEX index / OFZ ladder** | Any AI-assisted decision is judged only against these | B (C44, C47, C10) | Yes; MOEX Total Return and RGBITR/RUCBTRNS indices exist (C66) | Low | Baseline returns in RUB may dominate for years; emotional cost |
| 4 | **Hard risk limits outside the LLM: max position, max sector, turnover cap, no leverage** | Prevents the fee-drag and concentration failures | B/C (C17, C19, C22, C44, C45) | Yes | Low | Limits may bind in illiquid MOEX names; set liquidity floors |
| 5 | **Low turnover (monthly) with pre-committed rebalancing rule** | Low-turnover LLM-assisted strategies survive costs; high frequency loses | C (C45, C16, C44) | Yes, matches constraints | Low | Slow reaction in shocks — accepted trade-off |
| 6 | **Pre-registration of rules and a decision log before outcomes are known** | Enables honest evaluation; kills post-hoc selection | B (C57, C10, C56) | Yes | Low: a dated text file | None |
| 7 | **Use LLMs for post-cutoff text processing: disclosures, news, call transcripts, Russian-language sources** | This is where Grade B signal exists | B (C1, C53, C54) | Partially: Russian disclosure gaps (C71) and limited English coverage; Russian models catch local facts better (C70) | Medium: consumer subscriptions | Hallucinated data; missing cancelled dividends (C70); must verify against e-disclosure/MOEX |
| 8 | **Provenance-first retrieval: allow-listed sources, dated citations, cross-check two sources** | Reduces poisoning and stale data | B (C38, C35) | Yes | Medium | Allow-lists have bypasses (C38); still manual |
| 9 | **Diversity over volume: ask 2–3 different model families / sources once, average; don't re-sample one model** | Ensemble gains come from decorrelated inputs | B/C (C34, C37, C40) | Yes with 2–3 consumer subscriptions | Low–medium | Correlated errors across frontier models (C37) |
| 10 | **Calibration scoring: log every probabilistic statement, score Brier against base rates** | The only metric with enough sample in 20 months | B (C30, C31, C34) | Yes | Low | Self-scoring bias; use fixed resolution criteria |
| 11 | **Both-perspectives prompting for every thesis (bull and bear written separately)** | Reduces framing bias; defining bias to the model does nothing | C (C78) | Yes | Low | None |
| 12 | **Human final sign-off with a checklist (dividend status, disclosure flags, liquidity, position limit)** | Live and field evidence favours structured human review | C/B-design (C23, C76) | Yes | Low | Sycophancy to your own prior — use the checklist, not conversation |
| 13 | **Scenario/stress generation with LLM, numbers via historical bootstrap/EWMA** | LLM for plausible narratives; code for VaR/CVaR | C (C48) | Yes | Medium | Scenarios are not macro-validated (C48) |
| 14 | **Track adoption decay: assume any public text signal halves after publication** | Published predictors decay 26–58% (C55); LLM headline returns decline with adoption (C1) | B (C55, C1) | Yes | None | Over-discounting real signals |
| 15 | **DOES NOT WORK: asking the LLM to pick stocks or time the market** | Prospective recommendations earn no abnormal return and chase media attention | B (C21, C22) | — | — | Concentration, herding (C66) |
| 16 | **DOES NOT WORK: "think harder"/extended reasoning for trading decisions** | No net return improvement; sometimes harm | B (C11, C12) | — | Higher token cost | Illusion of rigour |
| 17 | **DOES NOT WORK: asking the model to check its own answer** | Intrinsic self-correction degrades | B (C39) | — | — | False reassurance |
| 18 | **DOES NOT WORK: multi-agent debate as alpha source** | Debate beats 1/N 33% of the time, no costs | C (C40, C41) | — | High token cost | Byte-identical outputs across "agents" (C40) |
| 19 | **DOES NOT WORK: backtesting an LLM on pre-cutoff history** | Non-identified: recall vs prediction (C5) | B | — | — | Everything looks good |
| 20 | **DOES NOT WORK: trusting arena leaderboards or vendor "since inception" numbers** | 2-week N=6 contests; unreconciled figures; no benchmark | D (C17, C18, C28, C69) | — | — | Marketing capture |
| 21 | **DOES NOT WORK (for retail): autonomous agent connected to a brokerage account** | No directional edge, volatility-blind leverage, interface-driven behaviour | C (C19); brokers now offer it on MOEX (T-Bank MCP, human confirm required — Smart-Lab post, D) | — | — | Irreversible losses; the user bears responsibility |

---

## 6. Anti-patterns and red flags

How to recognise an inflated AI-investing claim (each item is tied to a documented case):

1. **No number of trials disclosed.** Without it "it is impossible to assess the relevance of a backtest" (C57). Five seeds that find the same strategy and 0/5 survive deflation (C10).
2. **Backtest window overlaps the model's training data**, or the cutoff is "asserted" rather than verified (C46, C52, C5). Red flag phrase: "we instructed the model to use only information available at the time" (C4, C5).
3. **Headline accuracy without noise test.** If accuracy survives randomising the least significant digit, it is reasoning; if not, it is recall (C7).
4. **Returns without a passive baseline**, or with a baseline that has no fees while the strategy does (C83), or with "S&P 500 price return excluding dividends" (C83).
5. **Window shorter than one regime**: 2–16 weeks (C16, C17, C18), 2 months (C15), 3 days (C20 Cohort 2), 12 trading days (C44 live arm).
6. **Winner selected after the fact**: "Gemini was the only one of 13 families…" (C83); "Mystery Model" revealed after winning (C18); aggregate and per-contest numbers that do not reconcile (C18).
7. **Vendor conflict**: the arena operator sells agents and raises capital (C85, C84); the fund sponsor publishes the benchmark (C84, Intelligent Alpha); research by consultants to a quant manager (C49); pseudonymous authorship ("Annie Mous", C19).
8. **"Since inception" without benchmark or risk** (C28, C69, C87).
9. **"Our AI reads thousands of companies daily"** while charging 75 bp vs 3 bp passive and trailing the index by half over eight years (C26).
10. **Reasoning scores or debate transcripts presented as evidence** — reasoning quality is uncorrelated with Sharpe (C40).
11. **Excessive trading as a feature**: 1,418 trades in two weeks (C18); 238 trades in 16 days with 25–30% win rate (C17).
12. **Regulatory tells**: claims of "first regulated AI financial advisor" (C58 Global Predictions), "AI-driven forecasts" from a firm without the capability (C58 Delphia), orders processed by humans abroad (C58 Presto, Nate).
13. **Survey-based "adoption" numbers used as performance evidence** (C60, C61, C65 explicitly say they are not).
14. **Internal inconsistencies in the source itself**: HKU naming two different "strongest" models (C16); a 55% improvement in the abstract that computes to 35.5% (C68); expert Brier mean 0.157 vs median 0.0225 (C36).
15. **"The model improves, so the product improves"** as a stated bet rather than a measured result (C73).

---

## 7. Evaluation playbook for a small-sample personal system

Setting: ~20 months, decisions weekly to monthly, N ≈ 20 monthly or ≈ 80 weekly decisions, MOEX stocks and bonds, manual execution.

### 7.1 Accept what cannot be measured

**INFERENCE using Lo's (2002) approximation SE(SR) ≈ sqrt((1 + SR²/2)/T) with T in years:**

| True annual Sharpe | SE at T = 1.67 y | t-stat at 1.67 y | Years for t ≈ 2 |
|---|---|---|---|
| 0.3 | 0.79 | 0.38 | ~46 |
| 0.5 | 0.82 | 0.61 | ~18 |
| 0.6 | — | — | ~13 (Gençay states "roughly 11 years" before deflation, C10) |
| 1.0 | 0.95 | 1.05 | ~6 |

Conclusion: a 20-month track record cannot distinguish a good process from luck on returns. Harvey-Liu-Zhu's t > 3 bar for new "factors" (C56) is unreachable. Design the evaluation around things that *can* be measured.

### 7.2 Pre-register (before the first decision)

- Universe (with liquidity floor), rebalancing calendar, position/sector limits, cost assumptions (commission, spread by liquidity bucket, tax), and the exact passive baselines: MOEX Total Return index, 1/N over the universe, an OFZ ladder or RGBITR, and a 60/40 of the two.
- The decision rule and what the LLM is allowed to do (extract, summarise, propose scenarios) and not allowed to do (set weights, compute).
- Resolution criteria for every probabilistic statement you will score.
- The number of alternative rules considered (your "trials", C57).

### 7.3 Score what has enough sample

- **Directional calls (binomial, one-sided 5%):** INFERENCE: with N = 20 monthly calls you need ≥ 15 correct (75%; p = 0.021); with N = 40, ≥ 26 (65%); with N = 80 weekly, ≥ 48 (60%). Anything below is indistinguishable from a coin.
- **Calibration:** Brier score per statement vs (a) 50% baseline, (b) base-rate baseline, (c) if available, market-implied probabilities. Use log score as a second check. Forecasting benchmarks show this is where LLMs genuinely improved (C30–C34), so it is also where you can detect whether your pipeline adds information.
- **Decision-level attribution:** for each decision log the counterfactual (what the pre-registered passive rule would have done) and compute the paired difference; after 20 months report mean difference and a block-bootstrap CI, expecting it to include zero (C10 methodology).
- **Process-error rate:** count avoided and committed errors with definite truth values — missed cancelled dividends (C70), stale prices, wrong share counts, breached limits, trades without two-source confirmation. This is where a research layer earns its keep and it is measurable from month one.
- **Turnover and realised cost drag** vs the pre-registered cap.

### 7.4 Leakage-free habits

- Never ask a model about a period before its training cutoff and treat the answer as a forecast (C5).
- Date-stamp every input; store the retrieved text, not just the summary; re-verify any figure that moves a decision against MOEX/e-disclosure/Bank of Russia primary data.
- Keep the LLM blind to outcomes when it scores past decisions (outcome-blind review, C11 methodology).

### 7.5 Deflate

- At the end, report Sharpe, deflated Sharpe given the number of rules tried (C57), paired difference vs baselines, Brier, process-error rate. State openly that the return metrics are uninformative at this sample size and that the pipeline is justified, if at all, by calibration and error avoidance.

---

## 8. Open questions and what would change these conclusions

1. **A 3+ year audited live ledger** of any LLM-agent strategy with disclosed costs, trials and universe, beating volatility-matched passive baselines with a deflated Sharpe → would overturn P1.
2. **Independent replication of C1 on post-cutoff MOEX news** with costs and liquidity constraints → would establish a Grade B text signal for the Russian market (none exists).
3. **A factorial ablation** (backbone × tools × memory × risk rules × sizing) with repeated seeds → would settle P3.
4. **A forecasting-to-returns bridge**: do systems at superforecaster parity (C30) produce positive net returns in any market? Prediction Arena (C20) says no on Kalshi; a longer test is needed.
5. **Release of full text and replication package for C1 and C49**; both are central to the FOR case and partly paywalled or unquantified.
6. **Measured herding**: any price-based evidence that common LLM signals synchronise retail flows (regulators flag it; C24 finds lower comovement among AI funds).
7. **Does the Chen–Sialm–Xu fade (C24) reverse post-2023 with LLMs?** Their data end 2024; an update would be informative.
8. **Nof1 Season 2** and HKU's extended run: if either publishes verifiable, benchmarked, multi-regime results, the arena evidence could rise from D to C/B.
9. **Russian-language LLM reliability on disclosures**: a systematic test (not a blog) of GigaChat/YandexGPT/ChatGPT on e-disclosure facts (dividend decisions, buybacks, sanctions status) would convert C70 into usable evidence.
10. **Retraction/expression-of-concern status**: the RFS expression of concern on the BHL paper (reported by C74) and the retraction of Rahimikia–Drinkall models (reported by C50) were not verified from the journal or SSRN pages themselves.

---

## 9. Source list (date, type, grade)

Primary sources opened for this report, grouped by module. Date is the document date; grade is the evidence grade assigned above (fact-type regulator documents graded A for provenance, not performance).

**Premise audit / trading systems**
- Lopez-Lira & Tang, JFE 2026 — 2026 — journal — B/C — [link](https://ideas.repec.org/a/eee/jfinec/v184y2026ics0304405x26001066.html); arXiv v5 2024 — [link](https://arxiv.org/abs/2304.07619v5)
- Li, Kim, Cucuringu, Ma, KDD 2026 — Feb 2026 — conference — B — [link](https://arxiv.org/html/2505.07078v5)
- Gençay — Aug 2026 — preprint — B — [link](https://arxiv.org/pdf/2608.27734v1)
- Chen & Wang, Price of Thought — Sep 2026 — preprint — B — [link](https://arxiv.org/html/2609.30705v1)
- Sodha — Nov 2025 — preprint — C — [link](https://arxiv.org/abs/2511.08608)
- StockBench — Oct 2025 / Mar 2026 — preprint — C — [link](https://arxiv.org/abs/2510.02209)
- AI-Trader — Dec 2025 — preprint — C — [link](https://www.alphaxiv.org/abs/2512.10971)
- When Agents Trade — Oct 2025 — preprint — C — [link](https://www.alphaxiv.org/abs/2510.11695)
- TradingAgents — Dec 2024 / Jun 2025 — preprint — D — [link](https://arxiv.org/abs/2412.20138)
- HKU AIEL press release — 14 Jul 2026 — press release — C/D — [link](https://www.hkubs.hku.hk/media/press-release/testing-ai-in-the-real-world-hku-business-school-released-ai-agents-trading-performance/)
- Protos on Alpha Arena S1 — 4 Nov 2025 — news — D — [link](https://protos.com/llm-crypto-trading-contest-finds-llms-cant-trade-crypto/)
- TradeRank Alpha Arena snapshot — Aug 2026 — vendor — D — [link](https://www.traderank.ai/alpha-arena-leaderboard); TradeRank "Can AI beat the market" — Mar/Oct 2026 — vendor — D — [link](https://www.traderank.ai/blog/can-ai-beat-the-market)
- nof1 founder post on S1.5 — 5 Dec 2025 — vendor X post — D — [link](https://x.com/jay_azhang/status/1996984618751611006); nof1.ai — 2026 — vendor — D — [link](https://nof1.ai/)
- Business Standard (Bloomberg) — 7 May 2026 — news — D — [link](https://www.business-standard.com/amp/markets/news/ai-bots-auditioning-for-wall-street-trading-are-mostly-losing-money-126050701793_1.html)
- Flat Circle — 2026 — blog — D — [link](https://blog.flatcircle.ai/p/ai-trading-arenas)
- Barton et al. (DXRG) — Sep 2026 — preprint, vendor-affiliated — C — [link](https://huggingface.co/papers/2609.05663)
- Prediction Arena — Mar 2026 — preprint — C — [link](https://arxiv.org/html/2604.07355)
- Carlin, Israelsen, Wazzan, NBER w35153 — Apr 2026 — NBER WP — B(design) — [link](https://www.nber.org/papers/w35153)
- Chen, Sialm, Xu, NBER w35273 — May 2026 — NBER WP — B — [link](https://www.nber.org/system/files/working_papers/w35273/w35273.pdf)
- Smith & Wyatt, J. Investing — Apr 2025 — journal — B — [link](http://economics-files.pomona.edu/GarySmith/papers/DisappointingAIFunds.pdf)
- ETFRC AIEQ — Aug 2026 — data vendor — B — [link](https://www.etfrc.com/AIEQ); ETFRC GPT — Aug 2026 — C — [link](https://www.etfrc.com/GPT)
- 24/7 Wall St — 26 Aug 2026 — news — B(secondary) — [link](https://247wallst.com/investing/2026/08/26/can-ai-help-you-beat-the-stock-market-the-answer-may-surprise-you/)
- MarketWatch/Morningstar (Hulbert) — 2 Sep 2025 — news — C — [link](https://www.morningstar.com/news/marketwatch/2025090265/stock-traders-six-favorite-ai-tools-are-faring-much-worse-than-the-sp-500)
- AI Street on Bridgewater AIA — 4 Aug 2026 — paid newsletter — D — [link](https://www.ai-street.co/p/how-bridgewater-is-building-an-artificial)
- Man Group Insights — n.d. — vendor — D — [link](https://www.man.com/insights/what-ai-can-do-for-alpha)
- Robinhood Cortex blog — 25 Aug 2026 — vendor — D — [link](https://robinhood.com/us/en/careers/blog/loop-stays-dumb-so-the-model-can-be-smart/)
- Zhu & Cai review — Sep 2026 — preprint review — secondary — [link](https://arxiv.org/html/2609.04917v1)
- Xia et al., Agentic Trading audit — May 2026 — preprint — B(audit) — [link](https://arxiv.org/html/2605.19337v1)
- Yao & Zheng — Jun 2026 — preprint — C — [link](https://arxiv.org/abs/2606.08285)
- Nguyen & Pham — Mar 2026 — survey preprint — C/D — [link](https://www.alphaxiv.org/abs/2603.27539)
- Stanford GSB on deHaan et al. — 9 Jun 2025 — news — C — [link](https://www.gsb.stanford.edu/insights/ai-analyst-made-30-years-stock-picks-blew-human-investors-away)

**Leakage / memorisation**
- Gao, Jiang, Yan — Dec 2025 / Aug 2026 — preprint — B — [link](https://arxiv.org/html/2512.23847v1)
- Glasserman & Lin — Sep 2023 — preprint — C — [link](https://arxiv.org/abs/2309.17322)
- Sarkar & Vafa, ICML WS — 2025 — workshop — B — [link](https://openreview.net/pdf?id=fn9cJkB86T)
- Lopez-Lira, Tang, Zhu — Apr/Dec 2025 — preprint — B — [link](https://arxiv.org/pdf/2504.14765)
- Levy, JAR — May 2026 — journal — B — [link](https://onlinelibrary.wiley.com/doi/10.1111/1475-679x.70058)
- Kim, Muhn, Nikolaev — Nov 2024 — preprint — C — [link](https://arxiv.org/html/2407.17866v2)
- Zhang, Zhu, Linnainmaa, RFS — Sep 2025 — journal — B — [link](https://academic.oup.com/rfs/article-abstract/38/12/3768/8246070); Reply — Feb 2025 — SSRN — B — [link](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5154044)
- Kelly, Malamud, Schwab, Xu, NBER w35247 — May 2026 — NBER WP — C — [link](https://www.nber.org/papers/w35247)
- He, Lv, Manela, Wu, ChronoGPT — Jul 2025 — preprint — C — [link](https://arxiv.org/pdf/2502.21206v3)
- Benhenda, Look-Ahead-Bench — Jan 2026 — preprint — C/D — [link](https://arxiv.org/html/2601.13770v1)
- Rahimikia & Drinkall page — Jan 2025 — preprint page — D(flag) — [link](https://www.felixdrinkall.com/publication/fintext_2024/)
- Chen, Tang, Zhou, Zhu — Feb 2025 — preprint — C — [link](http://arxiv.org/pdf/2502.10008)
- HBS Working Knowledge on Cao, Wang, Xiang — 6 Mar 2026 — news — B(design, secondary) — [link](https://www.library.hbs.edu/working-knowledge/chatgpt-vs-deepseek-what-chinese-stocks-reveal-about-ais-limits)
- Koijen & Levy, NBER w35431 — Jul 2026 — NBER WP — C — [link](https://www.nber.org/papers/w35431)

**Forecasting**
- FRI ForecastBench parity post — 16 Jul 2026 — operator — B — [link](https://forecastingresearch.substack.com/p/ai-models-have-likely-reached-parity)
- Karger et al., ForecastBench — Nov 2024 — preprint — B — [link](https://arxiv.org/pdf/2409.19839v2)
- Metaculus FutureEval Spring 2026 — 9 Sep 2026 — platform — B — [link](https://www.lesswrong.com/posts/wZBbDqzfBjYG58CxK/futureeval-spring-results-pros-beat-bots-but-the-gap-is)
- explainx on Metaculus Cup — 17 Sep 2026 — blog — C — [link](https://www.explainx.ai/blog/ai-beats-forecasters-metaculus-cup-coverage-2026)
- Schoenegger et al., Science Advances — 2024 — journal — B — [link](https://www.science.org/doi/10.1126/sciadv.adp1528)
- Halawi et al. — Feb 2024 — preprint — B — [link](https://arxiv.org/html/2402.18563v1)
- Lu — 2025 — preprint — C — [link](https://arxiv.org/html/2507.04562)
- Aitchison et al. — Jun 2026 — workshop preprint — C — [link](https://arxiv.org/pdf/2606.29661v1)
- Lu & Zhang, Corroboration Illusion — Sep 2026 — preprint — B — [link](https://arxiv.org/html/2609.22246v1)

**Portfolio / risk / architecture**
- PortBench — Aug 2026 — preprint — B — [link](https://arxiv.org/html/2605.27887v3)
- Mantshimuli & Mwamba, JRFM — Apr 2026 — journal — C — [link](https://www.mdpi.com/1911-8074/19/5/320)
- Lee et al., CIKM 2025 LLM-BL — Oct 2025 — conference — C — [link](https://arxiv.org/html/2504.14345v2)
- DeMiguel, Garlappi, Uppal, RFS — 2009 — journal — B — [link](https://academic.oup.com/rfs/article/22/5/1915/1592901)
- Soleimani — Nov 2025 — preprint — C — [link](https://arxiv.org/html/2512.07867v1)
- Huang et al., ICLR 2024 — 2024 — conference — B — [link](https://proceedings.iclr.cc/paper_files/paper/2024/hash/8b4add8b0aa8749d80a34ca5d941c355-Abstract-Conference.html)
- Huang et al., MAD trading — Aug 2026 — preprint — C — [link](https://arxiv.org/html/2609.29701v1)
- Sinha et al., long-horizon execution — Sep 2025 — preprint — C — [link](https://arxiv.org/html/2509.09677v1)
- Yang, Bauer, Li, Hinz — 2025 — preprint field experiment — B(design) — [link](https://ideas.repec.org/p/arx/papers/2506.03707.html)
- Mykhalyuk — Apr 2026 — preprint — C — [link](https://www.alphaxiv.org/abs/2603.19944)
- Tait & Pisaneschi, CFA Institute — Sep 2026 — industry report — C — [link](https://rpc.cfainstitute.org/sites/default/files/docs/research-reports/rpc_tait_managing-llm-bias-in-investing_online.pdf)
- Winder, Hildebrand, Hartmann, PLOS ONE — 27 Jun 2025 — journal — B — [link](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0325459)
- CNBC on Chatterjee et al. — 7 Jul 2026 — news — C — [link](https://www.cnbc.com/2026/07/07/ai-personal-finance-advice.html)
- WashU Olin on Martin et al. — 10 Apr 2025 — news — C — [link](https://olin.washu.edu/about/news-and-media/news/2025/04/chatgpt-level-playing-field-retail-investors.php)

**Evaluation methodology**
- Bailey & López de Prado, DSR — 2014 — journal — B — [link](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)
- Harvey, Liu, Zhu — 2014/2016 — NBER/RFS — B — [link](https://www.nber.org/papers/w20592)
- McLean & Pontiff, JF — 2016 — journal — B — [link](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365)

**Regulators**
- SEC press release 2024-36 — 18 Mar 2024 — A — [link](https://www.sec.gov/newsroom/press-releases/2024-36)
- SEC LR-26282 (Nate) — 11 Apr 2025 — A — [link](https://www.sec.gov/enforcement-litigation/litigation-releases/lr-26282)
- DLA Piper on Presto order — 28 Jan 2025 — law-firm note — B — [link](https://www.dlapiper.com/en-us/insights/publications/ai-outlook/2025/sec-settlement-highlights-continued-focus-on-ai-washing)
- FCA press release — 27 Aug 2026 — B — [link](https://www.fca.org.uk/news/press-releases/young-investors-trust-ai-more-tv-or-celebrities)
- ESMA investor warning — 2025 — B — [link](https://www.esma.europa.eu/sites/default/files/2025-03/ESMA_Warning_on_the_use_of_AI_-_EN.pdf)
- ESMA TRV AI adoption — 20 Feb 2026 — B — [link](https://www.esma.europa.eu/sites/default/files/2026-02/ESMA50-481369926-30599_TRV_Risk_Analysis_AI_adoption_and_trends_in_securities_markets.pdf)
- ESMA/ILB/Turing report — 2025 — C — [link](https://www.turing.ac.uk/sites/default/files/2025-07/llms_in_finance_-_ilb_esma_turing_report.pdf)
- IOSCO CR — Mar 2025 — B — [link](https://www.iosco.org/library/pubdocs/pdf/IOSCOPD788.pdf)
- Bank of England FSiF — 9 Apr 2025 — B — [link](https://www.bankofengland.co.uk/financial-stability-in-focus/2025/april-2025)
- IMF GFSR Oct 2024 Ch. 3 — Oct 2024 — B — [link](https://www.imf.org/-/media/files/publications/gfsr/2024/october/english/ch3.pdf)
- FSB — 14 Nov 2024 — B — [link](https://www.fsb.org/uploads/P14112024.pdf)
- Bank of Russia consultation paper — Nov 2025 — B — [link](https://cbr.ru/Content/Document/File/185193/Consultation_Paper_20112025.pdf)
- Bank of Russia ORFR — Aug 2026 — B — [link](https://cbr.ru/Collection/Collection/File/62360/ORFR_2026-8.pdf)

**Russia / MOEX**
- HSE news on Lysenok — 4 Jun 2026 — C/D — [link](https://www.hse.ru/en/news/research/1165996693.html)
- Khubiyev & Semenov — Mar 2025 — preprint — C — [link](https://arxiv.org/html/2503.08696)
- Market Power on VTB strategy — Sep 2026 — blog — D — [link](https://marketpower.pro/post/finalnye-itogi-testirovaniia-strategii-intellekt)
- Банковское обозрение "Инвестируй с ИИ" — Apr 2026 — magazine — D — [link](https://bosfera.ru/sites/default/files/read_to_pdf/bo_04_april_2026-38-42.pdf)
- Smart-Lab 10-AI test — 23 Jul 2026 — blog — D — [link](http://smart-lab.ru/mobile/topic/1332040/)
- Smart-Lab on T-Bank MCP agents — 10 Sep 2026 — blog — D — [link](https://smart-lab.ru/blog/1350210.php)
- РБК Инвестиции on MOEX disclosure marks — 5 Oct 2026 — news — fact — [link](https://www.rbc.ru/quote/05/10/2026/6ac375d99a7947356c7d9b9d)
- MOEX ISS API terms — n.d. — exchange documentation — fact — [link](https://www.moex.com/a2193)

---

## 10. Limits of this research

**Could not verify from the primary document**
- Full text of Lopez-Lira & Tang (JFE 2026) is paywalled; test window, cost treatment and sample size are taken from the abstract only (C1).
- Kelly et al. (C49) economic results: only qualitative statements were accessible; no Sharpe values.
- Carlin et al. (C21) and Yang et al. (C76): the accessible pages give design and conclusions but no numeric results.
- The RFS "expression of concern" on van Binsbergen–Han–Lopez-Lira and the retraction of Rahimikia–Drinkall models are reported only by other papers (C74, C50) and were not confirmed on the journal/SSRN pages.
- Nof1's Season 1.5 ledger ("100% verifiable" per the founder) was not inspected; results come from a founder post, a competitor's archived snapshot and a Bloomberg-syndicated article (C18). No Season 2 results were found.
- Bridgewater AIA and Man AlphaGPT performance: no primary disclosure accessible (C28, C29).
- Intelligent Alpha's earnings-direction benchmark (68%) is known only via Bloomberg/Business Standard (C84).
- Eurekahedge AI Hedge Fund Index values: via MarketWatch only (C27).
- Metaculus Summer 2026 Cup standings: via a blog (C33); FutureEval Spring 2026 was read on a Metaculus-staff linkpost.
- The Cao–Wang–Xiang HBS working paper and the deHaan et al. working paper were read through institutional news pages, not the papers (C53, C77).
- Bank of Russia's "56% of young investors" figure is the FCA's UK figure re-cited by the Bank of Russia (C66), not a Russian survey; Russian media present it as if domestic (C70 vicinity). The Frank RG/VTB 15% and Выбери.ру 33% Russian usage figures (C69 source) have no reported sample sizes.

**Search gaps**
- No Grade A/B study of LLM-based systems on MOEX was found in Russian or English; Russian academic work found is classical ML on volatility/prices (C67, C68) and crisis early-warning systems (not fetched).
- No study on LLM reliability for Russian corporate disclosures beyond a product-affiliated blog test (C70).
- No study on sanctions-driven data gaps and their effect on model-based investing was found; the disclosure situation was documented only via news (C71).
- Institutional deployment evidence (Two Sigma, JPMorgan, Citadel, etc.) was not pursued beyond Man Group and Bridgewater; survey results (C60, C61, C62) stand in for it.
- Bond-specific LLM evidence (credit, OFZ curve) was not found; all portfolio evidence is equity/ETF/crypto.
- FinRobot, FinCon and FinMem original papers were not fetched directly; their claims are assessed through C9, C41, C42.

**Paywalled or inaccessible**
- Financial Times "AI can pick stocks better than you can" (June 2024) returned no content.
- ScienceDirect full text of C1; Wiley full text of C55 (abstract used).
- AI Street (C28) is a paid newsletter; only the accessible text was used.

**Method limits of this report**
- Evidence grading is a judgement applied consistently but not independently replicated; borderline cases are marked (B/C, C/D).
- Fetched pages were processed with an extraction prompt; verbatim quotes were taken from those extractions, which could introduce transcription error on long documents. Where a number looked inconsistent within a source, the inconsistency is reported rather than resolved (C16, C36, C68).
- The Sharpe sample-size and binomial thresholds in Section 7 are the report's own calculations (INFERENCE), not sourced.
- Literature cutoff: searches run on 7 October 2026; anything posted after early October 2026 is not covered.
