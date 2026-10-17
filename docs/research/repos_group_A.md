# Group A repo review, for ApexOptions

Reviewed 2026-10-17. Each repo was cloned with `git clone --depth 1` into `/tmp/claude-0/repos/`, and the source was read, not just the README. The TradingAgents forks were diffed file by file against the upstream commit they branched from; I reconstructed that commit from the full upstream history.

ApexOptions is the reference point throughout. It is a Python system that buys NIFTY weekly CE/PE options in paper trading. It enters on a Nifty-futures 15-second impulse z-score plus heavyweight synchrony, with a "not-late" gate. It exits on a 12-point futures stop, a trail from +1R, a thesis-void rule and a time limit. It also has depth drain, OI walls, a force detector, Black-76, five would-veto advisors, and a self-learning loop that runs 9 variants plus 1 ungated book.

## Summary

| # | Repo | Found? | Real substance | Value to ApexOptions |
|---|---|---|---|---|
| 1 | jeffstewart/options-trader-bot | Yes | High. A serious, honestly documented paper-trading research operation | **Highest.** Contract-wrapper evidence, data-collection design, gate validation |
| 2 | TauricResearch/TradingAgents | Yes | High engineering quality, but a daily-horizon equity rating tool | Low for signals. Medium for evaluation hygiene (point-in-time, settlement) |
| 2a | newsfriend/TradingAgents | Yes | Trivial. Points the LLM endpoint at a local proxy | None |
| 2b | digoal/TradingAgents | Yes | Chinese prompts plus A-share data vendors, with new look-ahead leaks | None. One negative lesson |
| 3 | youcanbuildthings "claude-trading-bot" | **Not found** | Book companion repo, no public link located | n/a |
| 4 | Tirth8292/Algo-Trade-Strategy | Yes | Small NIFTY/SENSEX script. Buggy, untested, and its backtest scripts are missing | Low to medium. Two small ideas, many anti-patterns |
| 5 | "openclaw-TradingAgents" | **Exact name not found.** Reviewed closest match gaaiyun/TradingAgents-OpenClaw-Skill | Thin wrapper plus a textbook indicator vote. The LLM path is broken against current TradingAgents | None |

---

## 1. jeffstewart/options-trader-bot

**What it is.** This is a news-catalyst options bot for US single stocks on Alpaca, paper trading only. It has three generations:
- `core/` (v1): about 3.9k lines in `bot.py`. Multi-strategy.
- `v2/`: a lean bot that trades lotto calls only.
- `v3/`: a context-aware LLM scorer, a 0.5-delta call picker, a 6.5% spread cap, an OI ≥ 10 floor and a 30-minute timed exit.

Alongside these sits `research/`, about 180 backtest and analysis scripts.

| Field | Value |
|---|---|
| Language | Python |
| Size | About 73k lines including research. 244 files, 99 commits |
| Last commit | 2026-10-02 (v3: SEC EDGAR 8-K ingestion) |
| Licence | **None** (no LICENSE file). Legally all rights reserved, so borrow ideas, not code |
| Stars | 0 |

The most valuable file is `docs/HANDOFF.md`. It is a frank state-of-play log that includes losing P&L.

### Signal logic in code (`v3/bot.py: process_signal`)
1. Drop news older than `MAX_FEED_LAG_SECS = 300`.
2. Deterministic pre-score regex filters (`v3/filters.py`: `prescore_noise`, `soft_catalyst_hit`). They drop listicles, macro wraps, "why is X surging" recaps, analyst price-target notes, chart chatter and acquirer-side M&A.
3. LLM scorer (`v3/scoring.py: SYSTEM_PROMPT`, `build_context_prompt`). The prompt includes the ticker's previous 7 days of news from a point-in-time SQLite archive (`news_db.get_ticker_news_history` with `created_at < signal_ts`) and the 24-hour market sentiment mix. The scorer returns `{sentiment, confidence, magnitude, catalyst, is_stale_echo}`.
4. Trade gates:
   - Sentiment must be bullish. Puts are scored and grid-logged but **never traded**.
   - `is_stale_echo` must be false.
   - `confidence ≥ 0.70` and `magnitude ≥ 0.35`.
   - Per-ticker cooldown of 300 s.
   - SPY regime gate (`v3/market.py: evaluate_regime`): close above the 200d SMA, 3-day momentum, and a "chop brake" of down-day density below 60% over 10 sessions.
   - Daily loss breaker at 2% of equity.
   - Stock price ≥ $10.
5. Size the position at 10% of equity (`POSITION_FRAC_OF_EQUITY`).

### Contract selection, risk gates, exits (`v3/execution.py`)
- `pick_call_contract`: DTE 14–28, strikes 0.95×–1.10× spot, sorted by (DTE distance, strike distance). The top 10 candidates go through `_passes_contract_guardrails`:
  - tradable, with the root symbol matching
  - mid > 0
  - mid ≥ 0.9 × intrinsic and mid ≤ spot (quote sanity)
  - OI ≥ 10
  - spread_pct ≤ 6.5%
- **Red flag: the code contradicts the README.** The "target delta 0.50 / ATM" is never computed as a delta. The code sets `target_strike = spot * (1 + (1 - 0.50) * 0.15)`, which is **7.5% out of the money**, not ATM. The same heuristic appears in `core/bot.py:1131` and `v2/execution.py:177`.
- Entry is a marketable limit at ask × 1.05. `_await_fill` polls for 10 s, then cancels, which avoids ghost positions.
- Exit: `monitor_open_positions` closes at `EXIT_HORIZON_MINUTES = 30`. The trailing stop exists but is disabled. The close is a limit at bid × 0.95, falling back to a market order after 15 s.
- v2 extras:
  - `_maybe_switch_to_cheaper_contract`, a live "mispricing switch". It backs out each same-expiry neighbour's IV, fits a local **quadratic IV-vs-strike smile**, and switches to the neighbour with the lowest residual only if the residual gap ≥ 0.02 and the neighbour passes the same liquidity checks.
  - Lotto stops: −20% stop, 15% trail, same-day exit.
- Regime and loss breakers **fail open**. `evaluate_regime` returns `passes_regime: True` on any exception or insufficient bars.
- Known bug they document: `oi=None` passes the OI floor in v1.

### Data, backtest and evidence quality
- **Real data, honestly reported.** HANDOFF.md reports −$16,801 over 165 closed v1 trades, a 25% win rate. They diagnose the cause as the *options wrapper* (spread tax plus overnight IV crush), not the signal: "same signals traded as stock ran roughly flat". A "perfect-exit" ceiling analysis put the best case at only about +$5k.
- `research/contract_strategy_tuner.py` is the best piece of methodology in the repo:
  - Chronological signal-level train/test split, plus expanding walk-forward folds (`walk_forward_splits`).
  - Entry at **ask**, exits marked at **bid** (`prep_contract_paths`), so spreads are costed.
  - Feature discovery by three independent methods: Spearman with Benjamini–Hochberg FDR, L1 logistic regression, and random-forest permutation importance with a label-shuffle p-value. A feature must win **at least 2 of 3** votes (`discover_significant_features`). The gate is then fitted on train only (`fit_rule_gate_from_discovery`, with `min_keep_frac=0.4`).
  - The script's own caveat says the sample is thin: about 3.5 days of data, all down-market, n=118. It warns that an empty result is a legitimate finding.
- **README claims that need care:**
  - The "7.5M rows / 652 signals / 5 weeks" dataset is not in the repo (it is gitignored).
  - The spread finding (ρ = −0.532, p ≈ 1.8e-27) is plausible and replicated in their later trade review, but cannot be checked here.
  - The "Gemini saved 74% of losses" table is **n = 11 trades**.
  - Fixed-horizon (30 min) beating trailing stops comes from the same short window.
- Other validation tools that suit ApexOptions:
  - `research/scorer_pnl_matched.py` compares models at a **matched number of realised trades**, separating ranking skill from threshold placement.
  - `research/bootstrap_gate_test.py` bootstraps the P&L of *gated-out* trades and jackknifes for a single lucky multibagger.
  - `research/lotto_mispricing_test.py` documents a methodology error. v1 mistook the ordinary volatility smile for mispricing, and the fix was the quadratic residual.
- They also record that "magnitude is uncalibrated" (rank-IC ≈ 0 across all models, including frontier ones). A different-family model used as a **disagreement veto** helped v1 but hurt v2. Good picker ≠ good gate.

### Ideas worth taking for ApexOptions

1. **The "grid collector": counterfactual contract telemetry per signal** (`v3/grid_collector.py`; `core/grid_collector.py`; HANDOFF "Contract-grid research collector"). **Value: HIGH.**
   - **How it works.** For *every* candidate signal, including ones that do not trade, it snapshots a whole strike × expiry grid: bid/ask/mid/spread/IV/Greeks/OI. It re-polls on a decaying schedule (30 s for 15 min, then 3 min, then 15 min) and joins back to real trades via `grid_signal_id`.
   - **Mapping.** On every ApexOptions trigger, including advisor would-vetoes and all 10 paper books, log the 10 hero contracts plus ±3 strikes, both CE and PE, every 5–15 s until 15:25. Key them by an episode_id shared with the trade logs.
   - **Why it matters.** This turns contract selection (ATM vs ±1/±2 strikes, current vs next weekly) and exit rules (12-point futures stop vs premium stop vs time) into questions that can be answered offline with *real* bid/ask paths. Without it, the self-learning loop can only learn about parameters it actually traded. Breeze gives you the live depth to do this; Alpaca's lack of historical bid/ask is exactly the gap they hit.
2. **Spread as the dominant loss predictor, plus a hard spread cap at selection time** (`_passes_contract_guardrails`, `MAX_SPREAD_PCT`). **Value: HIGH.**
   - **Mapping.** Add `spread_pct = (ask − bid)/mid` and top-of-book quantity to the contract picker. Promote it straight to a hard gate, with a cap fitted on your own data. NIFTY ATM weeklies are tight, so the cap mainly bites on expiry afternoons and fast moves. Log spread at entry and exit as an advisor feature.
   - **Why it matters.** Their −$16.8k post-mortem says the options wrapper ate the edge. For an all-in, compounding buyer the same mechanism (spread plus IV crush after the impulse) is the most likely silent killer. It also complements your IV-late advisor.
3. **Wrapper-vs-signal decomposition** (HANDOFF "P&L reality check"). **Value: HIGH.**
   - **Mapping.** For every ApexOptions trade, compute three P&Ls side by side: (a) futures P&L over the same holding window, (b) option P&L at mid, (c) option P&L at actual bid/ask fills. Write them to the trade log.
   - **Why it matters.** When the champion loses, this tells you whether the trigger or the instrument choice failed. Treat it as a standard column for the SPRT/t-test comparisons.
4. **"≥2 of 3 methods" feature discovery for promoting advisors to gates** (`discover_significant_features`). **Value: MEDIUM-HIGH.**
   - **Mapping.** Your advisors are promoted to gates only with evidence. Their recipe is a concrete evidence bar to add next to SPRT and leave-one-day-out: BH-FDR Spearman, L1 logistic and permutation-RF with shuffled labels, requiring agreement from at least two. It also gives a principled way to discover new advisor features from the logged would-veto data.
5. **Matched-N comparison for variants** (`scorer_pnl_matched.py`). **Value: MEDIUM-HIGH.**
   - **Mapping.** When the 9 variant books trade different counts, compare them on their top-N ranked trades (ranked by each variant's own score, such as z-score × synchrony), truncated on *realised* trades.
   - **Why it matters.** Otherwise "variant B wins" may only mean that B's threshold admits more of a favourable day.
6. **Bootstrap the gated-out set** (`bootstrap_gate_test.py`). **Value: MEDIUM-HIGH.**
   - **Mapping.** For each advisor, the question "does vetoing help?" is the same as "are the vetoed trades net-negative?". Your ungated book already gives you these trades. Bootstrap their summed P&L and jackknife the largest winner before promoting the advisor to a gate.
7. **IV-smile residual contract switch** (`v2/execution.py: _maybe_switch_to_cheaper_contract`). **Value: MEDIUM.**
   - **Mapping.** Black-76 IV for ATM ±3 strikes on the chosen expiry. Fit a quadratic smile and prefer the in-band strike with the most negative residual, subject to the same spread and OI gates.
   - **Fit for ApexOptions.** It overlaps naturally with the IV-late advisor: buy the strike whose IV hasn't caught up yet. NIFTY weeklies are efficient, so expect small gains. Run it first as a would-switch shadow.
8. **Time-of-day and lateness cutoff checked twice, at scoring and at order placement** (v2 `LOTTO_ENTRY_CUTOFF_MIN_BEFORE_CLOSE`). **Value: LOW-MEDIUM.** It is a cheap guard against a trigger that fires before a cutoff but fills after it.
9. **Engineering details.** **Value: MEDIUM** (operational).
   - Fill confirmation with timeout-cancel (`_await_fill`).
   - State persistence and restart recovery (`save_state` / `load_state`).
   - A single-instance guard (they had two live bots 4 minutes apart).
   - A note that in-process stops are the only protection. For ApexOptions paper trading this means the paper engine must mark stops on every tick, not on a polling loop.

### Things to avoid / red flags
- A README claim that the code doesn't implement: "0.50 delta" is really about 7.5% OTM. Always compute the actual delta with Black-76.
- Fail-open risk gates (`evaluate_regime` returns pass on error). In ApexOptions, gates should fail closed.
- Headline statistics on tiny samples (n = 11; 3.5 days of down-market). The 30-minute exit "proven empirically" rests on very little data.
- LLM magnitude scores are uncalibrated. Don't size on any uncalibrated score, including your own synchrony or coherence scores, without checking rank-IC first.
- Fixed take-profit rules that looked good in a synthetic Black-Scholes backtest were contradicted by real intraday option paths. Don't trust synthetic option repricing for exit tuning.
- No licence: reuse ideas, don't copy code.

---

## 2. TauricResearch/TradingAgents (original)

**What it is.** A LangGraph multi-agent LLM framework that issues a **daily** 5-tier rating (Buy / Overweight / Hold / Underweight / Sell) for a stock or crypto ticker on a given date.

| Field | Value |
|---|---|
| Language | Python |
| Size | About 28k lines (13.4k in package and CLI), plus a large `tests/` suite (about 80 test files) |
| Last commit | 2026-10-16 (v0.7.0) |
| Licence | Apache-2.0 |
| Stars | About 98k, about 18.9k forks |

It does **not** size, place orders or simulate a portfolio. `tradingagents/backtest.py` says this explicitly: "It is not a portfolio simulator, and must not grow one."

### Pipeline in code (`graph/setup.py: GraphSetup.setup_graph`)
1. Four analysts run in parallel, each in its own sub-graph with a private message history and a tool-round cap (`_analyst_graph`, `max_tool_rounds` then a forced `WRAP_UP`): market (indicators), sentiment (StockTwits/Reddit), news, fundamentals (SEC EDGAR "as filed").
2. A "Memory Log" node runs at the same time.
3. Bull and Bear researchers alternate. `ConditionalLogic.should_continue_debate` stops after `2 * max_debate_rounds`, default 1 round each.
4. The Research Manager (deep model, structured `ResearchPlan`) passes to the Trader (Buy/Hold/Sell proposal).
5. Aggressive, Conservative and Neutral risk analysts rotate.
6. The Portfolio Manager (deep model, structured `PortfolioDecision`) makes the final call.

### Exact "rules"
There are none in a quantitative sense. The decision is LLM prose that structured output turns into a rating. The prompt (`agents/managers/portfolio_manager.py`) says conflict alone is not a reason to Hold. `agents/rating.py: extract_rating` returns a non-tradeable `REVIEW` sentinel when no unambiguous rating is found, instead of defaulting to Hold. That is a good integrity rule.

### Evaluation and memory (`memory/settlement.py`, `memory/log.py`, `backtest.py`)
- **Settlement.** `fetch_returns` enters at the **first close after the decision date**, because a run dated d reads news published after d's close (#1518). It computes raw and alpha return versus a benchmark resolved by exchange suffix, over `holding_period_days = 5`. It refuses to settle until the full window has traded (#1169) and records a `resolution_date`.
- **Point-in-time lessons.** `get_past_context(as_of=...)` injects only reflections whose outcome was known (`resolved <= as_of`) on the run date (#1251). This prevents a backtest from "learning" from the future.
- **Backtest.** `run_backtest` runs a (ticker × date) grid into its own memory log, so the live log is not polluted. `summarize` reports hit rate and mean alpha per rating. The disclaimer says one sample per cell and that text feeds are not archived, so results are "indicative rather than repeatable".
- **Evidence.** The repo contains **no performance results**. Paper claims (arXiv 2412.20138) cannot be checked from the code. There is no cost model and no execution model. LLM non-determinism makes runs non-reproducible.

### Ideas worth taking for ApexOptions
1. **Settlement discipline: record `resolution_date` and use only lessons resolved by `as_of`** (`settlement.fetch_returns`, `memory/log.get_past_context`). **Value: MEDIUM.**
   - **Mapping.** In the self-learning loop, every statistic that feeds a champion or gate decision should be computed only from episodes fully closed before the decision timestamp. For leave-one-day-out, exclude the held-out day's own episodes from every input to the fitted variant, including advisor thresholds. It's cheap to add to the champion-switch code as an assertion.
2. **A `REVIEW` sentinel instead of a silent default** (`rating.py`). **Value: LOW-MEDIUM.**
   - **Mapping.** When the episode-type advisor or the coherence calculation can't classify (missing ticks, stale depth), log `UNKNOWN` and exclude the episode from evidence counts rather than defaulting to "pass". This matters for the honesty of the would-veto statistics.
3. **Separate the run log for sweeps from the live log** (`run_backtest`'s per-run memory log). **Value: LOW-MEDIUM.**
   - **Mapping.** Replay and backtest runs of ApexOptions variants should write to a separate store, so they never contaminate the live paper-book evidence used for SPRT.
4. **Bull/Bear adversarial review as an advisor.** **Value: LOW.**
   - **Fit for ApexOptions.** A 15-second impulse trigger can't wait for multi-minute LLM debates. At most this is a post-hoc end-of-day review of losing episodes, which is not on the critical path.

### Red flags / avoid
- Daily-horizon, LLM-only decisions with no quantitative edge test. This is not a signal source for intraday NIFTY options.
- A run is expensive (about 10+ LLM calls) and non-deterministic.
- The many look-ahead fixes in the CHANGELOG (v0.3.1 to v0.7.0: Alpha Vantage, FRED, social, fundamentals, news, memory) show how easy it is to leak future data into LLM context. Any earlier version, and any fork, should be treated as leaky.

### Fork 2a: newsfriend/TradingAgents
**Not marked as a GitHub fork. 12 stars, last commit 2026-06-01.** Its base is upstream v0.2.2 (commit `589b351`, March 2026); a diff against it shows only **5 files changed**:

| File | Change |
|---|---|
| `tradingagents/default_config.py` | Defaults set to `claude-sonnet-4-20250514` for both tiers, with `backend_url: http://localhost:8080/v1` |
| `cli/utils.py` | Claude models listed under the "openai" provider. OpenAI and Ollama URLs changed to `localhost:8080` |
| `llm_clients/openai_client.py`, `anthropic_client.py` | Placeholder `api_key="sk-no-key-required"` when `base_url` is set. Responses API skipped for custom endpoints. Model validation skipped |
| `README.md` | Clone and Contributing sections removed |

In short, it routes Claude through a local OpenAI-compatible gateway. It makes **no strategy, data or evaluation changes**. It is also about 7 months behind upstream, missing every look-ahead fix since v0.2.3 (for example `e111388` "prevent look-ahead bias in backtesting data fetchers"). **Value: none.**

### Fork 2b: digoal/TradingAgents
**Not marked as a fork. 9 stars, last commit 2026-03-31.** Also based on v0.2.2 (`589b351`); 27 files differ. Concrete differences:

- **A-share data vendors.** New `dataflows/akshare/` (stock, indicators, fundamentals, news) and `dataflows/efinance/` (stock, fundamentals). `cn_ticker_utils.is_china_ticker` detects formats such as `600000`, `sh600000` and `600000.SS`.
- **Router change** (`dataflows/interface.py: route_to_vendor`):
  - For CN tickers it reorders vendors so akshare and efinance come first.
  - Fallback now triggers on *any* exception or "No data found" string, not just Alpha Vantage rate limits.
  - When all vendors fail it returns an error string instead of raising. The LLM then reads "Error: Data unavailable…" as tool output and keeps reasoning.
- `stockstats_utils` accepts a pre-fetched DataFrame.
- **All agent prompts translated to Chinese** (trader, managers, researchers, risk debators, analysts), keeping the English `FINAL TRANSACTION PROPOSAL` marker for parsing.
- New `llm_clients/minimax_client.py` for MiniMax through the Anthropic SDK (`ANTHROPIC_AUTH_TOKEN`).

**New look-ahead leaks:**
- `akshare/news.py: get_akshare_global_news` ignores `curr_date` and returns today's headlines (`ak.stock_news_main_cx()` with `.head(limit)`) for any historical date.
- `efinance/fundamentals.py` documents `curr_date` as "not used". Historical runs therefore see current fundamentals.
- Stock-level news (`get_akshare_news`) does filter by `end_date`.

**Value to ApexOptions: none.** The one lesson is negative: a vendor-fallback chain that silently swaps data sources mid-run, and turns failures into prose, hides data-quality problems. The ApexOptions Breeze feed should fail loudly and mark the episode as unusable.

---

## 3. "claude-trading-bot" by youcanbuildthings: NOT FOUND

**What I tried:**
- `gh search repos claude-trading-bot`. Blocked: this session's GitHub API is restricted to repository-scoped endpoints, and search returns 403.
- `git ls-remote` on guessed owner/name pairs. Owners: `youcanbuildthings`, `YouCanBuildThings`, `youcanbuildthings-com`, `ycbt`, `jcook`, `johncook`, `cooklabs`, `Cook-Labs`. Names: `claude-trading-bot`, `claude-trading-bots`, `use-claude-trading-bot`, `ai-trading-bot`. None exist publicly.
- Web search (several queries) and fetches of `youcanbuildthings.com/about`, `/start/trading-bots/` and `/books/ai-trading-bot`. No GitHub links on any of them.
- Two similarly named repos that turned up: `mircone66/claude-trading-bot` (an HTML page plus a JSON file) and `benclawbot/Claude-trading-bot` (BTC/USDT Binance). I cloned both and grepped them for "youcanbuild", "unusual whales" and "monte carlo". **No match.** Neither is the book repo.

**What is known.** The Apple Books listing for "Use Claude to Build an AI Trading Bot" by John Cook (Cook Labs, 2026 2nd ed.) says every bot comes with a "free companion GitHub repo" that runs offline without API keys. It mentions Unusual Whales MCP options flow, Alpaca paper trading, Monte Carlo backtesting, a 4-agent setup and Polymarket. "Runs offline without API keys" strongly implies **synthetic or bundled sample data**. The URL appears to be distributed only inside the book.

**To review it**, the user needs to supply the URL from the book. I would then check whether Monte Carlo resamples real trades or synthetic paths, and whether "options flow" is real Unusual Whales data or mocked.

---

## 4. Tirth8292/Algo-Trade-Strategy

**What it is.** An intraday NIFTY/SENSEX weekly-options buying script. It learns a "strong candle" benchmark from the 10:00–10:45 one-minute candles, then buys CE or PE when a later candle beats that benchmark on both volume and body width. Every position is squared off at 14:55.

| Field | Value |
|---|---|
| Language | Python |
| Size | 1,238 lines across 4 scripts, plus a `.docx` and a committed `.pyc`. 9 commits |
| Last commit | 2026-09-26 |
| Licence | None |
| Stars | 0 |

The README is long and polished. The code is not consistent with it.

### Signal logic actually in code
Both implementations share these rules:
- **Reference window, 10:00–10:45 IST** (`algo_trade.py: reference_window`; `Algo_Trade_Groww_Implement.py: build_reference`). Take the green candle with the maximum `body × volume`; its body and volume become `width_ref_G` and `volume_ref_G`. Do the same for red. Swing high and low are computed but **never used** in any rule.
- **Signal, 10:45–14:55** (`Strategy._detect_and_enter`; `SignalEngine.check`):
  - Green candle with `volume > volume_ref_G` **and** `body > width_ref_G + 0.12` → buy CE.
  - Mirror rule for red → buy PE.
  - At most 2 entries per side per day. A stop-out locks that side for the rest of the day (`State.LOCKED`, `buy_blocked`).
  - `big_volume` = signal volume ≥ 1.5× the reference volume.
- **The 0.12 body buffer is in index points.** On NIFTY one-minute bodies (often 5–30 points) it does nothing.
- **Index candles have no real traded volume.** The NIFTY 50 and SENSEX spot indices aren't traded instruments. The Groww version pulls candles for `underlying_id = params["name"]` (the index). Unless Groww synthesises a volume field, the volume test is meaningless or always zero. Using futures volume would be the fix, but the code doesn't do that.

### Contract selection, exits
- **`algo_trade.py: choose_strike`.** CE = floor(spot/step)·step and PE = ceil(spot/step)·step, i.e. ATM or one step ITM.
- **Groww version: `select_strike`.** Walks outward from ATM to the first strike whose LTP is in the premium band: NIFTY 125–150, SENSEX 350–450. Otherwise it falls back to the strike closest to the band.
- **Exits** (`Trade.update`, Groww):
  - SL and T1 in premium points: NIFTY 16/16, SENSEX 70/115.
  - At T1, the stop moves to breakeven, then trails by a fixed step (NIFTY 20, SENSEX 75).
  - SENSEX "HOLD_90PCT": if the signal candle was big-volume, exit when P&L < 90% of peak P&L.
  - Force square-off at 14:55.
- **The two files disagree with each other and with the README:**
  - NIFTY settings: `algo_trade.py` uses SL 15 / T1 15 / final 70 / trail 15; the README says 16 / 16 / none / 20.
  - Fridays: `algo_trade.py` doesn't trade (`trade_instrument` returns None); the README and the Groww file trade NIFTY.
  - SENSEX: the code's own comment admits a "documentation conflict".

### Critical bugs found
1. **Long puts are managed as shorts.** In `Algo_Trade_Groww_Implement.py`, a PE is bought (`place_order(..., "BUY", ...)`) but wrapped as `Trade("SELL", entry_px=PE premium)`. `pnl = entry − price` and `sl = entry + sl_pts` are then applied to the *put premium*. A winning put (rising premium) hits the "stop", and a losing put is treated as profit. `algo_trade.py` has the same sign convention for PUT positions (`Position.profit`, stop = close + SL), applied to whatever single price series the CSV holds.
2. **Paper mode can't trade.**
   - `GrowwAPI.get_candles_1min` returns `[]` in paper mode, so no reference window forms and the run exits.
   - `get_ltp` returns 0.0, and the loop overwrites the live price with `ltp = trade.entry`, so exits can never fire.
   - The README's claim that the worked-example tables are "reproduced exactly by `groww_strategy.py` in paper-trade mode" is false. That file doesn't exist; the shipped file is `Algo_Trade_Groww_Implement.py`.
3. **The backtest can't run.** `backtest_runner.py` imports `nifty_sensex_algo_v3`, and `run_monthly.py` calls `sample_data_generator.py`, `enhanced_reporter.py` and `paper_trading.py`. **None of these files is in the repo.**
4. **Signal and trade prices are mixed in `algo_trade.py`.** It reads one CSV ("1-minute option OHLCV") for both the volume/body signal and the stop/target prices, but chooses the strike from a separately passed `--spot`. Signal on option candles, strike from spot, and point stops on the option are never reconciled.

### Data, backtest, evidence
There is no data, no results, no tests and no cost model; brokerage, STT, slippage and spread are all ignored. `run_monthly.py` defaults to `--generate-sample` synthetic data. The README disclaimer is accurate: "has not been backtested against historical market data in this repository". **No evidence of edge.**

### Ideas worth taking for ApexOptions
1. **Day-relative benchmarks: calibrate "strong" against today's own early session** (`reference_window`). **Value: MEDIUM.**
   - **Mapping.** ApexOptions' impulse z-score already normalises. The idea here is to make the *baseline* explicitly intraday-anchored: compute the impulse and aggressive-volume distribution of the first N minutes and express later impulses as a percentile against today, alongside your rolling z-score.
   - **Better input.** Use Nifty futures traded volume and aggressive-volume classes, not index volume.
   - **How to test.** As a variant parameter (rolling z vs session-anchored percentile) in one of the 9 books.
2. **Episode-conviction-dependent exit: a looser give-back rule for high-conviction triggers** (`HOLD_90PCT` for big-volume signals). **Value: LOW-MEDIUM.**
   - **Mapping.** Make trail tightness a function of entry conviction (for example synchrony percentile or force class) rather than a constant. It is cleanly testable in the parallel books.
   - **Caution.** A retention of 90% of peak P&L is extremely tight. On option premium it will exit on noise, so test it on futures R.
3. **Expiry-day exclusion per instrument** (`is_expiry_day`). **Value: LOW.** ApexOptions trades NIFTY weeklies, so the decision to trade or avoid Tuesday expiry (with its gamma and theta profile) belongs in the "episode type" advisor. Log `is_expiry_day` and `minutes_to_expiry` as features rather than hard-excluding.
4. **Premium band for strike choice** (`select_strike`). **Value: LOW.** It's a crude stand-in for a delta target, so prefer Black-76 delta and the spread gate from repo 1. It is mildly useful as an affordability guard under all-in sizing, since lot cost should map to a premium band given your ₹1 lakh capital.
5. **Manual override layer** (README §11 `WorkflowOverride`: kill switch, forced instrument, forced signal that still obeys caps). **Value: LOW-MEDIUM** (operational). A `skip_signals` kill switch for event days that still runs the would-trade logging is worth having. This exists only in the README, not in the code.

### Red flags / avoid
- Index "volume", unused swing levels and an absolute 0.12-point buffer: features that look meaningful and aren't.
- Inverted P&L for long puts. ApexOptions must test CE and PE paths symmetrically with unit tests on sign conventions.
- A README that describes files and behaviour that don't exist.
- Point stops on premium that ignore the premium level (16 points on a ₹138 option is about 12%, independent of IV or time to expiry).

---

## 5. "openclaw-TradingAgents": exact repo NOT FOUND; reviewed nearest match

**What I tried:**
- `gh search repos openclaw-TradingAgents`: 403, API restricted.
- Web search for `"openclaw-TradingAgents"` and variants. The top hit was the GitHub profile `hjadm`, which now shows "no public repositories", so the repo may have been deleted or made private.
- `git ls-remote` for `openclaw-TradingAgents`, `OpenClaw-TradingAgents` and `openclaw-tradingagents` under the owners `gaaiyun`, `win4r`, `shenhao-stu`, `netzpirat`, `hjadm`, `openclaw-trade`, `BlockRunAI`, `LLMQuant`, `TauricResearch` and `openclaw`. None exist.
- Grepped `LLMQuant/awesome-trading-agents`. No match.

**Closest match reviewed: gaaiyun/TradingAgents-OpenClaw-Skill.**

| Field | Value |
|---|---|
| Language | Python |
| Size | 1,237 lines; 6 commits |
| Last commit | 2026-06-01 |
| Licence | MIT |
| Stars | 2 |

It is an OpenClaw "skill" (`SKILL.md`, `_meta.json`) that wraps TradingAgents behind one interface with engines `auto | llm | signals | mock`.

### What's in code
- **`signals.py: aggregate_signals`.** A weighted vote over daily-bar indicators from yfinance (`load_ohlcv`, period 1y). Each indicator scores bullish = +1, bearish = −1, or neutral at a low weight:

  | Indicator | Rule | Weight |
  |---|---|---|
  | RSI(14) | < 30 bullish, > 70 bearish | 1.0 |
  | MACD | MACD > signal with hist > 0 bullish (mirror bearish) | 1.0 |
  | MA stack | price > MA20 > MA50 > MA200 bullish (mirror bearish) | 1.2 |
  | Bollinger | touching the band is contrarian | 0.8 |
  | OBV | 5-day slope | 0.6 |

- The score is normalised to [−1, 1]: BUY ≥ 0.35, SELL ≤ −0.35, confidence = |score|.
- `analyze_with_signals` sets target = close × (1 ± 6%) and stop = close ∓ 2×ATR(14). It truncates data to the requested date, which is point-in-time correct for prices.
- **The LLM engine is broken against current TradingAgents.**
  - `_llm_decide` calls `decision.get(...)` on the second value of `propagate()`. In TradingAgents that value is a **rating string** (`trading_graph.py:404`, `return final_state, run_rating(final_state)`), so it raises AttributeError, outside the try block.
  - It reads state keys (`fundamental_analysis`, `bull_arguments`) that don't exist; the real keys are `fundamentals_report` and so on.
  - It calls `reflect_and_remember`, which no longer exists upstream.
  - Tests cover only the `signals` and `mock` paths (`tests/test_signals.py`, `tests/test_skill_engines.py`).
- **No backtest, no evidence.** Mixing mean-reversion votes (RSI, Bollinger) with trend votes (MACD, MA stack) means they often cancel each other out, which yields HOLD by construction.

### Ideas worth taking for ApexOptions
1. **A unified decision schema across engines, with a mock engine for CI** (`__init__.py: TradingAgentsSkill`, `_mock_decision`). **Value: LOW.**
   - **Mapping.** ApexOptions' 10 paper books and the advisors could share one `Decision` record (action, confidence, reasons[], would_veto_by[], engine/variant_id), and a deterministic mock feed could drive tests. You probably already have the equivalent.
2. **Per-indicator contribution records ("rationale" per vote)** (`SignalContribution`). **Value: LOW.** It mirrors your advisor logging; nothing new.

### Red flags
- The name advertises TradingAgents integration, but that path crashes.
- Daily textbook indicators have no relevance to a 15-second NIFTY impulse system.

---

## Cross-repo shortlist for ApexOptions, ranked by value

1. **Counterfactual contract-grid telemetry on every trigger, including vetoed and untraded ones** (repo 1, `grid_collector`). Log the 10 hero contracts plus neighbours (CE and PE), with bid/ask/IV/Greeks and depth, on a decaying poll after each episode, keyed by episode_id. This is what lets the self-learning loop tune strike choice and exits on real fills instead of on what happened to trade.
2. **Spread at entry as a hard contract gate, plus a wrapper-vs-signal P&L decomposition** (repo 1). Put futures P&L, option-at-mid and option-at-fill side by side for every trade. Their real-money-style post-mortem found the option wrapper, not the signal, was the loss source.
3. **A stricter evidence bar for promoting advisors to gates** (repo 1):
   - (a) bootstrap and jackknife the P&L of would-vetoed trades from the ungated book;
   - (b) require at least 2 of 3 agreeing tests (FDR Spearman, L1 logistic, permutation RF);
   - (c) compare variants at matched N realised trades.
4. **Point-in-time settlement hygiene** (repo 2). Stamp every outcome with its resolution time. Champion and gate decisions may only use outcomes resolved before the decision time, and replay runs write to separate stores.
5. **Smaller ideas** (repos 1 and 4): the IV-smile residual strike switch, the session-anchored impulse benchmark, and a conviction-dependent trailing give-back. Run them only as shadow variants.

**Patterns to avoid**, seen across these repos:
- Labels that don't match the code (a "0.5 delta" that is really 7.5% OTM; "index volume").
- Risk gates that fail open.
- Sign errors on long puts.
- Headline statistics on n ≈ 11.
- READMEs describing files that don't exist.
- Vendor fallbacks that silently swap data sources or leak current data into historical runs.
