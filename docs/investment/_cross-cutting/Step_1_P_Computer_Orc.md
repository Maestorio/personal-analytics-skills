# AI in Investing: Evidence-Graded Map (as of 2026-10-07)

Labels: **FACT** = stated in an opened source; **AUTHOR'S CLAIM** = the source's own interpretation or self-reported result; **INFERENCE** = this analyst's reasoning. "n.r." = not reported. Preprint = not peer-reviewed.

---

## 0. TL;DR

1. **P1 (results really changed): NOT SUPPORTED.** No Grade A evidence anywhere shows LLM agents beating simple baselines net of costs over a statistically meaningful live window. Confidence: high.
2. The best live evidence (Alpha Arena) is 2 weeks long, has N=6 to 8 models, and 4 of 6 lost 42–59% in Season 1 (C9). That is Grade D, and it points toward "mostly losing", not "now earning". Confidence: high.
3. **P2 (the change is an artifact): partly SUPPORTED.** Look-ahead and memorisation bias is the best-replicated result in this whole field (C3–C7). In-window "alpha" decays 15–22 pp after the training cutoff (C6). Confidence: high.
4. The best-known positive fundamentals paper (Kim/Muhn/Nikolaev) is **"temporarily withdrawn"** after its own authors found data inconsistencies (C2). Confidence: high (author's own page).
5. The original news-sentiment result (Lopez-Lira & Tang, C1) holds after the training cutoff, but only on 2021–22 data, at daily frequency, with returns highly sensitive to costs (550% gross → about 50% at 25 bp). It is not a retail-feasible edge. Confidence: medium.
6. Broad, long, survivorship-controlled backtests show that LLM-strategy advantages "deteriorate significantly" (C11), and that strategies passing leakage-safe evaluation do little against equal-weight buy-and-hold (C12). Confidence: medium-high.
7. **P3 (the cause):** No clean ablation separates base-model capability from scaffolding in trading. Indirect evidence says risk control and position sizing dominate outcome dispersion (author's inference, C9b), and regime/beta explains much of the rest (C10, C11). Confidence: low-medium.
8. **Forecasting is where real, Grade A-like progress exists.** LLMs are approaching superforecasters on contamination-free benchmarks (Brier 0.101 vs 0.081; C13). Metaculus Pros still lead bots, but the gap is no longer significant (C14). This is not the same as making money. Confidence: medium-high.
9. Ensembles of LLMs match a human crowd on a small sample (C15). Multi-agent debate does not reliably beat a single well-prompted model plus majority vote (C16, C17). Confidence: medium.
10. LLMs are unreliable at raw arithmetic on financial data. Accuracy collapses when digits are perturbed, but tool use fixes it (C18). Put numerics in deterministic code. Confidence: high.
11. MOEX: essentially no rigorous LLM investing evidence. The one MOEX paper found has a worse directional accuracy than its baseline (C20). Expect less memorisation, but also worse data and liquidity. Confidence: low.
12. For a retail investor, the defensible uses are research synthesis, calibrated probability forecasts, disciplined checklists and logging, and deterministic risk rules. "LLM picks trades" is unproven and should be tested only as a small, pre-registered forward experiment. Confidence: medium.

---

## 1. Verdicts on P1, P2, P3

### P1. Did outcomes really change?
- **Verdict: Unproven, leaning "no".** Confidence: high.
- **Evidence:**
  - Live arena, crypto (C9): 2 of 6 models were profitable. The spread ran from +22% to −59% over about 2 weeks, with no baseline and no Sharpe ratio reported.
  - Live arena, US equities (C10): the winner made "+12.11% aggregate", and the per-competition rows "do not reconcile" (traderank.ai secondary).
  - StockBench, post-cutoff (C8): returns were 1.9–2.4% vs 0.4% for buy-and-hold over 82 days. The authors themselves say agents underperform in downturns. Costs n.r.
  - The longer, more honest tests (C11, C12) show no durable edge.
- **What would change this verdict:** a ≥12-month live, post-cutoff, costed record with a public ledger and a pre-registered baseline comparison, showing Sharpe or alpha significantly above equal-weight or 60/40.

### P2. Is the change an artifact?
- **Verdict: Largely yes for backtests; undetermined for live results**, which are too short to tell skill from luck. Confidence: high for backtests, medium overall.
- **Mechanisms documented:**
  - Memorisation of prices and returns: ticker+date prompting yields long-short Sharpe up to 5.65 within the training window (C7).
  - Entity re-identification despite masking (C4, C5).
  - Alpha decay after the cutoff (C6).
  - Short windows (C8–C10).
  - Survivorship and selection bias: FINSABER shows that cherry-picked 4-stock tests flip in broad tests (C11).
  - Multiple testing: a planted leaky oracle still scored DSR 1.00, i.e. statistical correction alone does not catch leakage (C12).
  - Marketing / "AI-washing" (C21).
- **What would change this verdict:** results reproduced on point-in-time models (C6-style) or on strictly post-cutoff live data over multiple regimes.

### P3. What is the cause of any gains?
- **Verdict: Unknown.** The best guess is regime/beta plus luck, with risk scaffolding mainly cutting losses. Confidence: low.
- **No controlled ablation of model vs scaffold in live trading was found.** Indirect evidence:
  - Long-only agents beat cash in rising markets and lose in downturns (C8, C11). That is beta.
  - Alpha Arena dispersion is attributed to loss-cutting and position sizing (C9b, author's interpretation, unverified).
  - Within forecasting, model capability does show a steady trend: about 0.016 Brier per year (C13).
- **What would change this verdict:** published ablations holding the market window fixed and varying (a) the model, (b) the tools and data, (c) the risk rules, with costs included.

### Steelman FOR "AI now genuinely earns"
- News-headline sentiment predicts next-day returns after the training cutoff, with a GPT-4 Sharpe of 3.8 before costs (C1).
- LLM sentiment beats dictionary methods on a large 2010–23 sample (C22).
- Point-in-time models show no alpha decay (C6). This implies that a real, if modest, signal exists once leakage is removed.
- LLM-derived features add monthly alpha of 0.17–0.20% in rolling out-of-sample tests (C19).
- Forecasting skill is rising fast and approaching expert parity (C13, C14).
- The honest inference: LLMs are a strong text-processing layer, and text information is priced with some delay.

### Steelman AGAINST
- Every headline "AI earns" number is either:
  - inside the training window (memorisation, C7), or
  - weeks long (C8–C10), or
  - gross of costs (C1, C22), or
  - from a narrow, hand-picked universe (C11).
- The flagship fundamentals paper has been withdrawn (C2).
- Signals that survive are daily, small-cap, and cost-sensitive. They are exactly what retail cannot capture, and published anomalies decay (secondary: McLean & Pontiff, cited in a blog; not opened).
- Live arenas show large losses for frontier models (C9).

---

## 2. Evidence Table

| ID | Source | Type | Period | N | Costs | Leakage controls | Grade | Key number (quote ≤25 words) |
|---|---|---|---|---|---|---|---|---|
| C1 | Lopez-Lira & Tang, arXiv 2304.07619 v4 [link](https://arxiv.org/html/2304.07619v4) | Academic preprint (later revised Oct 2025) | Oct 2021–Dec 2022 | 67,586 headlines, 4,138 firms | 5/10/25 bp tested | Post-cutoff (GPT-3.5 cutoff Sep 2021) | B− (short single window; daily) | GPT-4 Sharpe 3.8; at 25 bp returns fall to "over 50%" from >350–550% gross. Abstract: "approximately 90% portfolio-day hit rates" for initial reaction ([abs](https://arxiv.org/abs/2304.07619)) |
| C2 | Nikolaev faculty page [link](https://faculty.chicagobooth.edu/valeri-nikolaev/ongoing-research-projects) | Author notice | n.r. (accessed 2026-10) | — | — | — | FACT (retraction-type) | KMN paper "temporarily withdrawn"; "Bloated Disclosures" replication "did not yield results supporting the reported findings" |
| C3 | Glasserman & Lin, arXiv 2309.17322 / JFDS 2024 [link](https://arxiv.org/abs/2309.17322) | Peer-reviewed | n.r. in abstract | n.r. | n.r. | Anonymisation of firm identifiers | B (method) | In-sample "the anonymized headlines outperform", "particularly strong for larger companies" (distraction/look-ahead effects) |
| C4 | Sarkar & Vafa, ICML 2025 [link](https://openreview.net/pdf?id=s6WkKKBgw3) | Peer-reviewed | 2018–2020 earnings calls | 1,000 speeches per period | n/a | Cutoff Jul 2023 vs test window | B (bias evidence) | Llama-2 named COVID-type risks in 8.0% of pre-2020 risk predictions; masked firms still identified at 70% accuracy |
| C5 | Lopez-Lira, Tang, Zhu, "Memorization Problem", arXiv 2504.14765 [link](https://ideas.repec.org/p/arx/papers/2504.14765.html) | Preprint (rev. Dec 2025) | n.r. | n.r. | n/a | Pre/post cutoff | B (bias) | "LLMs cannot be trusted for economic forecasts during periods covered by their training data." "Post-cutoff, we observe no recall." |
| C6 | Look-Ahead-Bench, arXiv 2601.13770 [link](https://arxiv.org/html/2601.13770v1) | Preprint, proof of concept | P2 Jul–Dec 2024 | 5 tech stocks | n.r. | Point-in-time models (cutoff Jan 2020) | B− (tiny N) | Standard LLM alpha decay −15 to −22 pp; PiT models +0.3 to +1.3 pp; buy-and-hold 24.75% |
| C7 | "AI's predictable memory", Economics Letters 2025 [link](https://orbilu.uni.lu/bitstream/10993/68692/1/1-s2.0-S0165176525004392-main.pdf) | Peer-reviewed | 2018–2023 (in training window) | US CRSP universe; N n.r. | n.r. | Measures leakage | B (bias) | GPT-4.1 ticker+date-only long-short Sharpe 2.88/4.65/5.65 (daily/monthly/yearly) = pure memorisation proxy |
| C8 | StockBench, arXiv 2510.02209 [link](https://arxiv.org/html/2510.02209) | Preprint | 3 Mar–30 Jun 2025 | 20 DJIA stocks, 82 days | n.r. | Post-cutoff claimed; exact cutoffs n.r. | C | Buy-and-hold 0.4%; Kimi-K2 1.9%, Qwen3-235B 2.4%; abstract: "most models struggle to outperform the simple buy-and-hold baseline" |
| C9 | Alpha Arena S1 via traderank.ai [link](https://www.traderank.ai/alpha-arena-leaderboard) | Live real-money; secondary (nof1 primary not opened) | 18 Oct–3 Nov 2025 | 6 models × $10k | n.r. | Live (post-cutoff by construction) | D (tiny N, 2 weeks) | Qwen3 Max +22.31%, DeepSeek +4.89%, Claude −42.01%, Gemini −45.55%, Grok 4 −57.92%, GPT-5 −58.74% |
| C9b | Goraestory case [link](https://goraestory.com/en/academy/cases/alpha-arena/) | Media | Season 1 | 6 | n.r. | — | D | Author's interpretation: dispersion reflects "how small the losses were when it was wrong"; "reproducibility has [not] been verified" |
| C10 | Alpha Arena S1.5 via traderank.ai (same link as C9) | Live; secondary | 19 Nov–3 Dec 2025 | 8 models × 4 comps | n.r. | Live | D | Winner "+12.11% aggregate"; announced vs per-competition rows "do not reconcile" |
| C11 | FINSABER, arXiv 2505.07078 (KDD 2026 per author post) [link](https://arxiv.org/html/2505.07078v2) | Preprint/conference | 2004–2024 | >7,000 US equities incl. delisted; 63–91 symbols per selection | Commission modelled | Survivorship-free, rolling; model leakage acknowledged | B | FinAgent Sharpe 0.12 in bull markets, −0.38 in bear; FinMem −0.19 to −0.97; advantages "deteriorate significantly" |
| C12 | "What survives honest evaluation?", arXiv 2608.27734 [link](https://arxiv.org/html/2608.27734v1) | Preprint (27 Aug 2026) | 2022–25; 2017–25 | 453 stocks; 39 ETFs | 1 bp commission + 2 bp spread + impact, 0.5×/2× | Registry-validated tools, publication delays, 1-day lag | B | Agent strategy "Eval SR 0.18", +4.7% vs equal-weight +40.8%; planted leaky oracle still DSR 1.00 |
| C13 | ForecastBench / FRI, 8 Oct 2025 [link](https://forecastingresearch.substack.com/p/ai-llm-forecasting-model-forecastbench-benchmark) | Benchmark (ICLR 2025 paper) | Rolling, future-only questions | 500 questions per round | n/a | Future-only resolution | A− for forecasting (not investing) | GPT-4.5 Brier 0.101 vs superforecasters 0.081; parity projected Nov 2026 (95% CI Dec 2025–Jan 2028) |
| C14 | Metaculus FutureEval Spring 2026, 3 Sep 2026 [link](https://x.com/metaculus/status/2095608079991894293) | Live tournament (self-reported by host) | 7 Jan–15 Apr 2026 | 173 bots; 99 Pro-compared questions | n/a | Live | A− for forecasting | Pros ahead by "1.25 head-to-head points per question", "one-sided p = 0.247"; "Nine of ten individual Pros beat every individual bot" |
| C15 | Schoenegger et al., Science Advances 2024 [link](https://www.science.org/doi/10.1126/sciadv.adp1528) | Peer-reviewed | Oct 2023–Jan 2024 | 31 questions, 12 models | ~$1 per forecast | Real-time | B (small N) | LLM ensemble Brier 0.20 vs human crowd 0.19 (p=.850); GPT-4 improved 0.17→0.14 after seeing human median |
| C16 | "Talk Isn't Always Cheap", ICML 2025 [link](https://www.arxiv.org/pdf/2509.05396) | Peer-reviewed | n/a | 100 samples × 3 tasks × 5 seeds | n/a | n/a | B (non-finance) | Debate "can sometimes be harmful rather than helpful"; correct→incorrect switches outnumber the reverse |
| C17 | Wang et al., ACL 2024 [link](https://aclanthology.org/2024.acl-long.331.pdf) | Peer-reviewed | n/a | 100–460 per task | n/a | n/a | B (non-finance) | "A single-agent LLM with strong prompts can achieve almost the same performance" as discussion methods |
| C18 | "Numerical Reasoning and Look-Ahead Bias", J. Accounting Research, 6 May 2026 [link](https://onlinelibrary.wiley.com/doi/abs/10.1111/1475-679x.70058) | Peer-reviewed | 1968–2021 Compustat | 346,731 firm-years; ~1,900 for commercial-LLM tests | n.r. | Yearly-cutoff models; rolling GBDT | B | Best commercial LLM 60% → 51% after randomising the last digit; GBDT +2.7 pp; tool use → 100% on tallying |
| C19 | Wong et al., "LLMs in Equity Research" [link](https://nicwong.com/assets/files/llms_equity_research.pdf) | Working paper | OOS 2013–2022 | Russell 3000 | n.r. | Rolling train; memorisation acknowledged | C+ | Long-portfolio alpha 0.17%/month, IR 1.45; EPS-change accuracy "near 50%" |
| C20 | Multimodal MOEX study, arXiv 2503.08696 [link](https://arxiv.org/html/2503.08696) | Preprint | Test Mar–Aug 2024 | 176 MOEX stocks; 79,555 RU news | n.r. | Prior-day news only | C | LSTM+Qwen accuracy 48.6% vs LSTM-only 52.0% (MAPE lower); test period was a downtrend |
| C21 | SEC 2024-36 [link](https://www.sec.gov/newsroom/press-releases/2024-36) | Regulator | 18 Mar 2024 | 2 advisers | — | — | FACT | Delphia "did not in fact have the AI and machine learning capabilities that it claimed"; $400k total penalties |
| C22 | Kirtac & Germano, Finance Research Letters 2024 [link](https://arxiv.org/abs/2412.19245) | Peer-reviewed | 2010–Jun 2023 | 965,375 articles | n.r. | Not reported (OPT pre-training overlap likely; INFERENCE) | C | OPT long-short Sharpe 3.05 vs Loughran-McDonald 1.23 (gross) |
| C23 | AIEQ ETF, Yahoo Finance (as of 2 Oct 2026) [link](https://finance.yahoo.com/quote/AIEQ/performance/) | Live fund (data aggregator) | Since 2017 | 1 fund | Fees included in NAV | Live | A− for "this fund", N=1 | 5-yr 4.18% vs category 7.67%; 1-yr 15.47% vs 27.18% (page shows inconsistent YTD figures) |
| C24 | TradingAgents, arXiv 2412.20138 [link](https://arxiv.org/abs/2412.20138) | Preprint, framework | n.r. in abstract | n.r. | n.r. | n.r. | C | Claims "notable improvements in cumulative returns, Sharpe ratio, and maximum drawdown" vs unnamed baselines |
| C25 | ESMA AI warning 2025 [link](https://www.esma.europa.eu/sites/default/files/2025-03/ESMA_Warning_on_the_use_of_AI_-_EN.pdf); IOSCO CR/01/2025 [link](https://www.iosco.org/news/pdf/IOSCONEWS761.pdf); Bank of Russia 20 Nov 2025 [link](https://www.cbr.ru/eng/press/event/?id=28109) | Regulators | 2025 | — | — | — | FACT | ESMA: AI advice may be "outdated, incorrect or incomplete"; Bank of Russia: "one in five financial market organisations already uses" AI |

---

## 3. What Separates Winners from Losers

Ranked by evidence strength (strongest first):

1. **Leakage discipline in evaluation, not in the model** (C3–C7, C12). Grade B, replicated across ≥5 independent groups. Most "winners" in backtests are winners because of leakage.
2. **Breadth and length of the test** (C11). Narrow universes and short windows manufacture winners. Grade B.
3. **Beating the right baseline.** In-sample, long-only agents ride beta. Against equal-weight, most edges vanish (C8, C11, C12). Grade B.
4. **Cost sensitivity and signal frequency.** Daily news signals erode with costs (C1). Grade B−.
5. **Deterministic numerics and tools** (C18). Grade B for accuracy; not linked to returns.
6. **Risk control and position sizing** (C9b). Grade D (author's interpretation). Plausible and consistent with classical finance, but untested for LLMs.
7. **Ensembling and aggregation** (C15). Grade B for forecasts; untested for returns.
8. **Multi-agent role-play / debate** (C16, C17, C24). No reliable advantage over a strong single agent; claims rest on Grade C self-reports.

---

## 4. Consensus, Contested, Unknown

- **Consensus**
  - In-training-window backtests of LLMs are invalid (C4–C7).
  - LLMs are good text classifiers, better than dictionaries (C1, C22).
  - LLM arithmetic needs tools (C18).
  - LLM forecasting is improving and near expert level on general questions (C13–C15).
- **Contested**
  - Whether an LLM-news signal survives costs at scale today (C1 vs decay arguments).
  - Whether LLM agents beat buy-and-hold over long horizons. Positive self-reports (C8, C24) vs negative broad tests (C11, C12).
  - Whether debate helps (C16 vs the positive subset in C17).
- **Unknown**
  - Causal ablation of model vs scaffold in live trading.
  - Any Grade A investing result.
  - Behaviour of LLMs on MOEX.
  - Herding effects when many retail users ask the same models.

---

## 5. Practice Catalogue

Ranked by evidence × feasibility for one person, consumer LLM subscriptions, weekly–monthly decisions, and MOEX.

| # | Practice | What it does | Evidence | Transfers to retail+MOEX? | Cost/effort | Risks |
|---|---|---|---|---|---|---|
| 1 | Only trust post-cutoff, forward-logged results | Kills memorisation inflation | B (C4–C7) | Yes, fully | Low | Slow feedback |
| 2 | Always compare against simple baselines (IMOEX/MCFTR total return, equal-weight, a bond index, a fixed mix) | Separates alpha from beta | B (C8, C11, C12) | Yes | Low | Picking a flattering baseline |
| 3 | All numbers via code/spreadsheet, LLM only for text | Removes arithmetic hallucination | B (C18) | Yes | Low–medium | Bugs in your own code |
| 4 | Explicit probability forecasts plus a Brier log | Measures judgement skill with small N | A−/B (C13–C15) | Yes | Low | Few resolved questions |
| 5 | Ensemble 2–3 models plus your own estimate; take the median | Reduces variance | B (C15) | Yes (consumer subscriptions are enough) | Low | Correlated errors across models |
| 6 | Deterministic risk rules (max position size, drawdown stops, liquidity floor) | Caps tail losses | Classical finance; D for LLM-specific evidence (C9b) | Yes; critical on thin MOEX liquidity | Low | Whipsaw |
| 7 | Point-in-time source archive with dates (saved filings, news) | Prevents your own look-ahead | B (method) | Yes; requires manual discipline | Medium | Gaps in archived Russian sources |
| 8 | LLM as a reader/summariser of reports, with forced citations to page or line | Saves time, gives provenance | Inference; no return evidence | Yes; Russian-language capability varies by model (not tested here) | Low | Fabricated citations, so spot-check them |
| 9 | Red-team prompt ("argue the opposite") | Surfaces missed risks | Weak; debate evidence is mixed (C16, C17) | Yes | Low | Generates false balance |
| **Does not work / unproven** | | | | | | |
| — | LLM picking trades autonomously | — | D/C (C8–C10) | No | — | Large drawdowns (C9) |
| — | Multi-agent "trading firm" frameworks | — | C (C24 vs C11) | No | High | Complexity without edge |
| — | Daily news-sentiment trading | — | B− gross only (C1) | No: costs and execution make it infeasible | — | Cost erosion |
| — | Asking an LLM for historical prices or returns | Memorised, unverifiable | B (C7) | No | — | Silent errors |
| — | Buying "AI-powered" funds on the label | — | C23, C21 | — | — | AI-washing |

---

## 6. Anti-Patterns and Red Flags

- A test window inside the model's training period, or a training cutoff that is not stated (C7, C8).
- Few tickers, usually mega-cap tech (C6, C11).
- Returns without costs, or without equal-weight / buy-and-hold baselines.
- Live results of weeks, or N of fewer than 10 agents (C9, C10).
- Only the winner is reported out of many variants. Ask how many were tried (C12).
- Claims of "contamination-free" without stating dates (C8).
- Numbers that do not reconcile (C10, C23).
- Papers whose results are not reproducible by their own authors (C2).
- "Proprietary AI" marketing without methodology (C21).

---

## 7. Evaluation Playbook for a Small-Sample Personal System

- **Pre-register before starting.**
  - State the decision rule, universe, baseline (e.g. a fixed mix of MCFTR plus an RGBI-type bond index), cost assumptions (commission + spread + slippage), and review cadence.
  - Store this in a timestamped Git commit.
- **Expect low statistical power on returns.** About 20 months of monthly decisions gives about 20 portfolio observations.
  - INFERENCE (standard approximation): to detect an annual Sharpe difference of 0.5 at t≈2, you need roughly \( T \approx (2/0.5)^2 = 16 \) years.
  - Returns over 20 months therefore cannot prove skill. Treat them as a sanity check only.
- **Score decisions instead of P&L.**
  - For each decision, log probabilities for verifiable events (e.g. "the next report shows revenue up y/y", "the key rate is cut at the next meeting").
  - Track Brier score against (a) base rates, (b) a single model alone, and (c) the ensemble.
  - About 100–200 resolved binary forecasts give usable resolution. C15 shows 31 questions could not separate an ensemble from a human crowd.
- **Use decision-level attribution.** Log what the LLM recommended, what you did, and what the baseline did. Compute the counterfactual P&L of "you without the LLM" and "LLM-only".
- **Check for leakage.** Every input document carries a publish date that is earlier than the decision time. Never ask a model for historical data it might have memorised; fetch the data instead.
- **Set kill criteria in advance.** For example, stop the LLM layer if its Brier score is worse than base rates after N=50 forecasts, or if the max drawdown exceeds a preset limit.

---

## 8. Open Questions / What Would Change These Conclusions

- A Grade A live track record (≥12 months, public ledger, costs included, post-cutoff) beating equal-weight. This would flip P1.
- Point-in-time LLM studies at scale (beyond the 5 stocks in C6) showing persistent alpha. This would strengthen the steelman FOR.
- Ablation studies (model × tools × risk rules) on a fixed live window. This would resolve P3.
- The outcome of the KMN review (C2): reinstatement or retraction.
- MOEX-specific, post-cutoff, costed LLM studies. None were found.
- ForecastBench reaching superforecaster parity (projected Nov 2026, C13).

---

## 9. Source List

| Source | Date | Grade |
|---|---|---|
| [Lopez-Lira & Tang v4](https://arxiv.org/html/2304.07619v4) | 2023-09 (rev. 2025-10) | B− |
| [Nikolaev withdrawal notice](https://faculty.chicagobooth.edu/valeri-nikolaev/ongoing-research-projects) | accessed 2026-10 | Fact |
| [Glasserman & Lin](https://arxiv.org/abs/2309.17322) | 2023-09 | B |
| [Sarkar & Vafa](https://openreview.net/pdf?id=s6WkKKBgw3) | ICML 2025 | B |
| [Memorization Problem](https://ideas.repec.org/p/arx/papers/2504.14765.html) | 2025 (rev. 2025-12) | B |
| [Look-Ahead-Bench](https://arxiv.org/html/2601.13770v1) | 2026-01-20 | B− |
| [AI's predictable memory](https://orbilu.uni.lu/bitstream/10993/68692/1/1-s2.0-S0165176525004392-main.pdf) | 2025-09-26 | B |
| [StockBench](https://arxiv.org/html/2510.02209) | 2025-10 (rev. 2026-03) | C |
| [Alpha Arena via traderank](https://www.traderank.ai/alpha-arena-leaderboard) | 2026-08 | D, secondary |
| [Goraestory Alpha Arena case](https://goraestory.com/en/academy/cases/alpha-arena/) | 2026-07 | D |
| [FINSABER](https://arxiv.org/html/2505.07078v2) | 2025–26 | B |
| [What survives honest evaluation?](https://arxiv.org/html/2608.27734v1) | 2026-08-27 | B |
| [ForecastBench / FRI](https://forecastingresearch.substack.com/p/ai-llm-forecasting-model-forecastbench-benchmark) | 2025-10-08 | A− |
| [Metaculus FutureEval](https://x.com/metaculus/status/2095608079991894293) | 2026-09-03 | A− |
| [Wisdom of the silicon crowd](https://www.science.org/doi/10.1126/sciadv.adp1528) | 2024 | B |
| [Talk Isn't Always Cheap](https://www.arxiv.org/pdf/2509.05396) | 2025 | B |
| [Rethinking multi-agent discussion](https://aclanthology.org/2024.acl-long.331.pdf) | 2024 | B |
| [Numerical reasoning & look-ahead (JAR)](https://onlinelibrary.wiley.com/doi/abs/10.1111/1475-679x.70058) | 2026-05-06 | B |
| [LLMs in Equity Research](https://nicwong.com/assets/files/llms_equity_research.pdf) | n.r. | C+ |
| [MOEX multimodal study](https://arxiv.org/html/2503.08696) | 2025-03 | C |
| [Kirtac & Germano](https://arxiv.org/abs/2412.19245) | 2024 | C |
| [TradingAgents](https://arxiv.org/abs/2412.20138) | 2024–25 | C |
| [AIEQ performance](https://finance.yahoo.com/quote/AIEQ/performance/) | 2026-10-02 | A−, N=1 |
| [SEC AI-washing](https://www.sec.gov/newsroom/press-releases/2024-36) | 2024-03-18 | Fact |
| [ESMA warning](https://www.esma.europa.eu/sites/default/files/2025-03/ESMA_Warning_on_the_use_of_AI_-_EN.pdf) | 2025 | Fact |
| [IOSCO CR/01/2025](https://www.iosco.org/news/pdf/IOSCONEWS761.pdf) | 2025-03-12 | Fact |
| [Bank of Russia AI](https://www.cbr.ru/eng/press/event/?id=28109) | 2025-11-20 | Fact |

---

## 10. Limits of This Research

- **Contradiction searches were run for about 8 of the 15 key findings, not all 15:**
  - C1: decay and cost argument
  - C2: withdrawal found
  - C9/C10: reconciliation issue found
  - C11
  - C13/C14
  - C16/C17
  - C18
  - The remaining findings were not individually searched for replications.
- **Primary sources not opened:**
  - nof1.ai ledgers (Alpha Arena numbers are secondary)
  - FinMem, FinAgent, FinRobot, FinCon papers
  - McLean & Pontiff
  - IOSCO full report text
  - FCA documents beyond search snippets
  - Bank of Russia consultation PDF
  - Kim/Muhn/Nikolaev full paper (now withdrawn)
- **Many fields are n.r. because only abstracts or HTML extracts were read.** This applies notably to C3 (paywalled JFDS), C5 and C24.
- **Gaps not covered with primary sources:**
  - Module 3: LLM vs Black-Litterman/HRP. One MDPI study surfaced but was not opened.
  - Module 5: alt-data decay.
  - Institutional deployment practices.
- **Russian-language academic literature was barely searched.** The MOEX conclusions are weak.
- Extraction used an automated reader. Quoted numbers should be spot-checked against the PDFs before you rely on them.
