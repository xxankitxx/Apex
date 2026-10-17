# Repo review, group B: LLM trading agents and their guardrails

Reviewed 2026-10-17. Each repo was cloned with `git clone --depth 1` into `/tmp/claude-0/repos_b/<repo>` and its source code was read. The READMEs were read too, but no claim in them was taken on trust.

**Access notes.** In this session the GitHub search API and repo-metadata API returned HTTP 403. Repos with unknown owners were found by web search, then cloned. Star counts were not visible: the API was blocked and the HTML page did not expose the counter. Last-commit dates come from `git log`.

**ApexOptions context used for judging.** ApexOptions is written in Python and runs on Breeze tick data. It only buys NIFTY weekly options. Entries are triggered on a 15-second impulse, with synchrony and not-late checks. It sizes all-in and paper-trades. It runs 9 pre-registered variants plus 1 ungated book, uses SPRT, t-test and leave-one-day-out (LODO) to pick the champion, and logs five advisors as would-veto only.

---

## Headline verdict on "LLM in the loop" for ApexOptions

None of the five trading repos has evidence that an LLM adds edge.

- The best-engineered one (ArthurMateus/Claude-trading) ran its own pre-registered out-of-sample test and documented that **no strategy survived**.
- The other four have no evaluation of the LLM's decisions at all.

LLM latency is far too high for ApexOptions' entry path:

| Repo | LLM call path | Timing |
|---|---|---|
| Claude-trading | `claude -p` | 180 s timeout, 5-minute cycle |
| llm-paper-trading-agent | one Opus call per cycle | every 30 minutes |
| OpenProphet | heartbeat | 2 minutes at the open |
| SkopaqTrader | AI sell tier | runs as an async task every N cycles, because it is too slow to block on |

A 15-second impulse trigger with a not-late check would already be "late" by the time any of these returned.

The only LLM roles that are plausibly useful sit **off the hot path**:

- **Post-session journal review.** Summarise the day's would-veto disagreements and propose hypotheses. These become new *pre-registered* variants, never live changes.
- **Pre-market event tagging.** For example, RBI policy, Budget, or a large heavyweight's results day. This is logged as a sixth would-veto advisor and promoted only through the existing evidence gate.
- **Code review of research and risk diffs.** Claude-trading uses `quant-validator` and `risk-reviewer` sub-agents for this.

Everything below is rated with that constraint in mind.

---

## 1. ArthurMateus/Claude-trading ("tradebot")

**What it is.** A Python 3.11 / SQLite multi-agent crypto swing bot on Alpaca, spot and long-only, paper-first.

- **Size:** about 100 files and about 12.4k lines including research output; `src/` is about 5k lines.
- **Last commit:** 2026-10-06, "Document research v2 2026 results: no validated strategy".
- **Licence:** no LICENSE file, so it is all-rights-reserved by default. Borrow ideas, not code verbatim.
- **Agents:** 15 roles: an Opus orchestrator plus Haiku/Sonnet specialists. LLM calls go through `claude -p` on a Pro subscription (`src/tradebot/llm.py`).

**Decision logic actually in code**

- `src/tradebot/pipeline.py` runs one cycle every 5 minutes. The sequence is:
  1. Market data
  2. Manage open positions
  3. Kill switch
  4. For assets where a **backtest-validated setup is firing**: Technical, Quant, News and Flow agents in parallel
  5. Replication agent
  6. Orchestrator
  7. Risk agent plus `guardrails.check_trade`
  8. Portfolio agent, then a guardrail re-check
  9. Execution
- `agents/orchestrator.py: Orchestrator.fused_score()` is a weighted vote: weight × score × confidence over non-abstaining agents.
  - Opus is called only if the fused score is at least `prefilter_min_abs_score` (0.15) **and** a validated setup is active.
  - The LLM picks among validated setups. It cannot invent trades.
  - "Agents agreed / disagreed" is computed in code, not taken from the LLM.
  - The LLM's `confidence` must be read as P(take-profit hit before stop) and is audited later.
- The setups are 8 deterministic rules in `strategies.py`. They are gated by `backtest.py: backtest_setup_pooled()`, which uses:
  - next-bar-open fills plus slippage
  - fees on both sides
  - stop-first when a bar is ambiguous
  - gap-through-stop filled at the open
  - a second-half out-of-sample split

**Risk gates.** `src/tradebot/guardrails.py` holds pure functions, unit-tested in `tests/test_guardrails.py` (11 tests).

- `check_trade()` rejects on:
  - halt or pause
  - daily loss limit
  - max positions or duplicate asset
  - min confidence
  - spread above 15 bps
  - wrong-side stop or target
  - reward:risk below 1.5
- **Portfolio heat is capped at min(6%, remaining daily loss budget).** If every stop hit at once, the day still could not breach the daily limit.
- Correlated-cluster cap: assets with 24h correlation of at least 0.7 count as one.
- Notional is capped at the *worst allowed fill* (`max_entry_slippage_bps`).
- `allowed_risk_pct()` gives **"earned" sizing**. Risk above 1% unlocks per confidence bucket only after at least 30 trades in that bucket, a realised win rate within 5 pts of predicted confidence, **and** E[R] > 0.
- `agents/kill_switch.py: KillSwitchAgent.evaluate()` has deterministic levels OK < PAUSE_ENTRIES < HALT_DAY < HALT. Triggers:
  - a persisted halt
  - drawdown of 15% or more, which flattens and requires a human reset
  - 5 straight losses, followed by a cooldown
  - API/LLM error rate
  - **order rate above 30/hour, which halts as a "runaway loop"**
  - rolling slippage above 30 bps
  - no clean data
  - **a mismatch between the broker's positions and the journal, which pauses entries**

  The optional LLM review can only escalate.
- Invariants in `CLAUDE.md`:
  - "code computes, LLMs judge"
  - LLMs can only make things stricter
  - fail closed on LLM error or budget exhaustion
  - a resting broker stop on every fill, or flatten

**Journaling.** `journal.py` uses SQLite with these tables:

- `trades`: entry/exit, size, agents agreed/disagreed, confidence, reason, expected vs actual return, market conditions, slippage, R-multiple, exit reason, attribution, lessons
- `decisions`: every candidate plus the stage and reason it was rejected
- `events`, `equity`, `llm_usage`, `state`

**Promotion and evaluation**

- `agents/paper_trading.py: PaperTradingAgent.evaluate()` gives PROMOTE / CONTINUE / FAIL.
  - Requirements: at least 100 trades, at least 28 days, PF ≥ 1.2, max DD ≤ 10%.
  - **FAIL if realised slippage exceeds the modelled slippage by more than 10 bps.**
  - Promotion is never automatic: going live needs an environment variable plus the verdict.
- `learning.py: update_agent_weights()` gives bounded trust updates:
  - at least 20 observations per agent
  - target = base × (0.5 + hit rate), clamped to [0.25, 2]
  - each update moves at most 20% toward the target
- The **research harness** in `src/tradebot/research/` is the most valuable part:
  - `history.load()` raises `LookaheadError` for any data on or after `TEST_START` (2026-01-01) unless the caller is the frozen final test.
  - `search.select()` uses design years 2022–24 and selects on 2025. The rule is fixed in advance: train PF ≥ 1.1, positive in at least 2 of 3 years, then validation with ≥ 100 trades, PF ≥ 1.1, expectancy > 0, and a **day-clustered t-stat** ≥ 3.
  - `search.freeze()` SHA-256-hashes both the champions **and all the research source files**.
  - `load_frozen()` refuses to run if `frozen.json` or the code changed after freezing.
  - Every view of the 2026 holdout is appended to `research/test_ledger.jsonl`. A re-search after a view is refused unless explicitly marked `contaminated`, and that flag is carried into reports.
  - `engine.trade_stats()` clusters the t-stat by day: daily sums, so BTC, ETH and SOL firing on the same move are not counted as independent evidence.
  - `test2026.null_expectancy()` is a **timing null**. It shifts the champion's own entries by a random whole number of days, wrapping within the test window, and re-prices them with the same exits. This keeps trade count, time of day and cross-asset clustering, and removes only timing skill. A strategy passes if it beats the null's 95th percentile. The report also states how many would beat it by chance (5%).
  - `engine.CostModel` holds separate cost models: spot fees, perp fees plus actual funding, and per-asset slippage.
- Tests: `tests/test_research.py` has about 30 tests, including:
  - no family looks ahead
  - exit P&L is not visible before the exit bar closes
  - tamper detection
  - zero-edge strategies rarely validate
  - ledger blocking

**Evidence quality.** This is the only honest one of the group.

- Data is real Binance history, with realistic costs on both sides.
- There is a genuine pre-registered holdout. `docs/BACKTEST_2026_FINDINGS.md` reports **no edge**:
  - 1,152 configurations, then a second search over 1,720 more, from 12 and then 17 families
  - 0 of 51 champions passed the 2025 validation
  - random entries with the same exits lose about −75 bps/trade, which is simply the spot round-trip cost
  - leverage of 5x or more lost 92–99%
- The README makes no profitability claim.
- Small inconsistency: the docs say v1 used t ≥ 2, while `RULES` now says `val_min_tstat: 3.0`.
- The *live* backtest gate in `config/settings.yaml` (`validation:`) is much weaker than the research harness: 60 days, PF ≥ 1.2, and a half split. Setups could pass the live gate while failing the research one.

**Ideas worth taking for ApexOptions**

| # | Idea | ApexOptions module | Value | Why |
|---|---|---|---|---|
| 1 | **Timing null.** Shift each variant's own entry timestamps to random other days at the *same time of day*. Re-price with the same exits (12-pt futures stop, trail from +1R, synchrony-flip void, time stop) on recorded ticks. Report expectancy vs the null's 95th percentile. | Self-learning loop / champion evaluation | **High** | This is exactly the question the domino trigger has to answer: does the impulse-plus-synchrony *timing* have skill, or is profit just intraday seasonality and volatility regime (open drive, expiry-day gamma)? Recorded Breeze ticks make it cheap to run. |
| 2 | **Random-entry, same-exits cost null.** Measures the pure cost drag per round trip. | Paper books / cost model | **High** | Claude-trading found the cost drag exceeded the edge. For NIFTY weekly option *buying*, round-trip cost (half-spread twice, STT on the sell leg, exchange fees, GST, stamp) against a 12-pt futures stop can be a large share of 1R. Do this before trusting any variant's PF. |
| 3 | **Day-clustered t-stat**: sum per day, then compute t. | SPRT / t-test champion gate | **High** | Ten books trade the same days on the same trigger, so their trades are not independent. Testing per day matches LODO. It also guards the multiple-comparison problem across 9 variants. Consider requiring the champion to beat the others by a margin larger than you would expect from picking the best of 10. |
| 4 | **Freeze plus hash plus holdout ledger.** Hash the variant registry *and* the decision code. Log every look at holdout days. Refuse re-tuning on viewed days unless the run is flagged contaminated. | Pre-registered variant registry | **High** | Makes "pre-registered" verifiable, and stops parameters creeping silently after the trader has looked at results. |
| 5 | **Slippage-vs-model promotion check.** FAIL if paper fills drift more than X from the modelled fills. | Paper fill model / promotion | **High** | With all-in sizing on weekly options, the fill model *is* the edge. If paper assumes LTP and live fills at the ask, nothing transfers. Log bid/ask at the signal tick and at the assumed fill. |
| 6 | **`decisions` table with stage and rejection reason** for every candidate, not only trades. | Journaling | Medium | ApexOptions already logs would-veto. Adding "stage reached" (impulse → synchrony → not-late → advisor) lets the funnel be analysed. |
| 7 | **Kill-switch checks**: order-rate runaway, journal-vs-broker position mismatch, data staleness, rolling slippage. | Execution safety (for the future live step) | Medium | Cheap, and catches failure modes that P&L limits miss. Staleness matters a lot with Breeze websocket drops. |
| 8 | **Bounded learning steps** (minimum observations, at most 20% move toward target, clamped). | Advisor promotion / champion switch | Medium | Prevents whipsawing between champions after a lucky day. Could be a hysteresis rule on champion changes. |
| 9 | **Calibration-earned sizing** (bucket win rate vs predicted, E[R] > 0). | Sizing | Low | ApexOptions is all-in, so sizing does not vary. The idea transfers better to *advisor promotion*: an advisor earns gate status only when its veto bucket is calibrated. |
| 10 | **Heat capped at remaining daily loss budget.** | Daily risk | Low–Medium | With all-in, one position *is* the heat. The useful version: after a loss, the next day's all-in should be capped so that a full premium loss cannot breach a weekly loss limit. |

**Red flags**

- No licence.
- The live validation gate is weaker than the research gate.
- 15 LLM agents add cost and complexity with no measured benefit. The repo's own findings say the setups lose before the LLMs even matter.
- The crypto spot cost structure is not comparable to NSE options.

---

## 2. OscarJuJi/llm-paper-trading-agent

**How it was found.** Web search for `"llm-paper-trading-agent" github` returned `github.com/OscarJuJi/llm-paper-trading-agent`. It matches the brief: Claude proposes, `risk.py` disposes.

**What it is.** A tiny Python demo.

- 13 files, about 890 lines.
- **A single commit**, 2026-07-16, "Initial commit".
- MIT licence.
- US large caps from yfinance (delayed). Paper broker in a JSON file.
- `agent.py: decide()` makes one `client.messages.parse` call to `claude-opus-4-8` with adaptive thinking, every 30 minutes (`main.py: run_cycle`). The output is a schema-validated `AgentOutput` (buy/sell/hold, quantity, confidence, rationale).

**Decision logic.** Entirely the LLM. The context is SMA, RSI and MACD plus RSS headlines plus the last 8 journal entries, annotated by `journal.with_outcomes()` with `move_since_pct`.

**Risk gates.** `risk.py: vet()` is long-only and watchlist-only. Caps: 10% of equity per order, 20% per position, a 10% cash reserve, and at most 3 trades per cycle. It simulates approvals cumulatively, so a burst of buys cannot overspend. There is a −3% daily-loss kill switch. 7 tests are in `test_guardrails.py`.

**Journaling and promotion.** JSONL cycle log. No promotion gate, no metrics, no backtest.

**Evidence quality.** None:

- no fees or slippage
- fills at the delayed last price
- no stops at all
- no evaluation of decisions

**Ideas for ApexOptions**

| Idea | Module | Value | Why |
|---|---|---|---|
| Cumulative simulated approval within one decision batch | Risk gate | Low | ApexOptions takes one trade at a time. Only relevant if variants ever share capital. |
| Re-feeding decisions annotated with the subsequent move | Journal | Low | Hindsight annotation is fine for review, but ApexOptions already scores outcomes properly. |

**Red flags**

- **The kill switch blocks sells too.** `vet()` rejects every non-hold action once the daily loss is hit, so it prevents de-risking exactly when it matters. ApexOptions must never route exits through entry gates.
- No protective stops.
- One expensive Opus call per cycle.
- The README's "learns from its track record" is just prompt context.

---

## 3. JakeNesler/OpenProphet (successor to Claude_Prophet)

**What it is.** A Go (Gin) trading backend for Alpaca, plus a Node.js agent server, an MCP tool server (45+ tools) and a web dashboard.

- About 88 tracked files and about 29k lines, including a 3.7k-line dashboard HTML.
- Last commit 2026-10-10.
- **Licence CC BY-NC 4.0 (non-commercial).** The author also sells setup guides and templates at openprophet.io.
- The README cites a Bloomberg article whose headline is "AI tools for stock trading put up mixed results".
- The agent runs `opencode run` as a Claude subprocess on a **phased heartbeat**: pre-market 15 minutes, open 2 minutes, midday 10 minutes, close 2 minutes (`agent/harness.js`).

**Decision logic.** Fully discretionary. The LLM reads `TRADING_RULES.md` (prompt-injected), calls tools, and places orders. Strategy "templates" in `agent/config-store.js` are prose prompts. The engine contains no deterministic signal.

**Multi-variant runs.** `agent/orchestrator.js: AgentOrchestrator` runs per-account "sandboxes". Each has its own Go backend port (`portForAgent`), its own SQLite DB under `data/sandboxes/<account>/`, and its own agent, strategy and permissions. These are independent parallel paper accounts. There is no comparison or statistics layer across them.

**Risk gates**

- `permissions.js: checkPermissions()` is pure and unit-tested. It checks:
  - blocked tools
  - `allowLiveTrading`
  - asset-class gates
  - a 0DTE gate that parses OCC symbols
  - `requireConfirmation`
  - `maxOrderValue`

  On `maxOrderValue`: options are valued with the ×100 multiplier, market orders get a live-quote price hint, and an order that cannot be valued **fails closed**. Closing a position is exempt.
- `mcp-server.js: enforcePermissions()` fails closed for order tools if the permissions server is unreachable.
- Daily-loss circuit breaker: `agent/server.js`, on `beat_end`, compares Alpaca equity with `last_equity` and pauses the agent.
- `services/position_manager.go`:
  - managed positions with stop, take-profit, trailing stop and a **partial exit** at +X%
  - polls every 10 s
  - cancels the old stop and re-places it when trailing
- Order idempotency: a client order ID is persisted *before* submit. `OrderController.ReconcileOpenOrders` reconciles at startup. Tests: `TestBuyPersistsIntentBeforeSubmit`, `TestReconcileOpenOrdersOnlyUpdatesConfirmedOrders`, `TestManagedProtectiveLegsPersistIntentBeforeSubmit`.

**Journaling.** `services/activity_logger.go` writes daily activity JSON plus decision logs. `vectorDB.js` does semantic search over past trade setups using local 384-dimension embeddings in sqlite-vec.

**Evidence quality.** None in the repo. No backtest, no metrics, no published paper results.

**Ideas for ApexOptions**

| Idea | Module | Value | Why |
|---|---|---|---|
| **Persist order intent with a client order ID before submit, and reconcile at startup** | Future live execution (Breeze) | **High when going live**; Low while on paper | A lost HTTP response must not duplicate an all-in position. Breeze order placement plus a websocket drop is exactly this scenario. |
| Permission checker as a **pure, unit-tested function** that **fails closed** when it cannot value an order | Risk layer design | Medium | A good pattern. Their changelog shows two real bypasses: options valued 100× too low, and market orders valued at $0. Write explicit tests for "cannot price, so reject". |
| 0DTE / expiry-date gate, plus their **timezone bug** lesson (UTC midnight parsing let same-day expiries through) | Expiry selection | Medium | Parse Breeze expiry strings as IST calendar dates, and test around midnight IST and on Tuesday expiry. |
| Partial exit at a target, with the rest trailing | Exit variants | Medium | A natural *pre-registered variant* to test against the current "trail from +1R": take half at +1R, trail the rest. Judge it by the existing SPRT/LODO. |
| Phased cadence by session phase | Monitoring / advisors | Low | ApexOptions is tick-driven already. Possibly useful only for the cadence of slow advisors. |
| Separate DB and port per variant sandbox | Parallel paper books | Low | ApexOptions already runs parallel books, so nothing new. |

**Red flags**

- **Most limits are prompt-only.** `maxPositionPct`, `maxDeployedPct` and `maxOpenPositions` appear only as prompt lines in `agent/harness.js` (lines ~601–604). No code enforces them.
- **The agent can rewrite its own guardrails.** The MCP tool `update_permissions` (`mcp-server.js` ~line 2129) PUTs new permissions "effective immediately". It is in the agent's tool catalog (`agent/tool-catalog.js`), along with `update_strategy_rules` and `update_agent_prompt`.
- `DEFAULT_PERMISSIONS.allowLiveTrading = true` and `maxOrderValue = 0` (no limit).
- The daily-loss breaker runs only at the end of a beat and silently skips if the account read fails.
- Non-commercial licence plus a paid tier.

---

## 4. JakeNesler/Claude_Prophet

**What it is.** The deprecated predecessor; the README says to use OpenProphet.

- Go backend plus `mcp-server.js` (1.7k lines) for Claude Code.
- About 209 files, about 12.9k lines excluding logs.
- Last commit 2026-03-12. MIT licence.
- Includes real `activity_logs/` (Nov–Dec 2025) and about 160 `decisive_actions/*.json` files.

**Decision logic.** Discretionary LLM, steered by `TRADING_RULES.md`, which says explicitly: "Discretionary execution – Rules are guidelines, not hard constraints".

- Multi-timeframe: swing positions at 50–120 DTE, delta 0.40–0.70; scalps at 2–5 DTE.
- Exits: −15% "mental" stops, take profit at +25–50% with an optional half exit at +25%.
- Liquidity: bid-ask spread < 10% of mid, limit orders only.
- Limits: at most 10 trades/day, at most 5 scalps.
- Hedging means buying puts. All of this is prose.
- `.claude/agents/` define CEO, Strategy, Consultant and Engineer personas, used for "veto" reviews.

**Code-enforced parts.** Only `services/position_manager.go`: managed stop, take-profit, partial exit and trailing percent, polled every 10 s (`MonitorPositions`).

**Journaling.** `decisive_actions/` JSON per decision: PASS, VETO, BUY, SELL, HEDGE, OVERRIDE.

**Evidence quality.** Anecdotal logs only; no P&L analysis. One log, `2025-11-20T14-58-00-381Z_OVERRIDE.json`, records "Overriding governance framework for rapid scalping… user-directed".

**Ideas for ApexOptions**

| Idea | Module | Value | Why |
|---|---|---|---|
| Option liquidity gate: spread / mid < 10% | Strike selection / not-late check | Medium | ATM NIFTY weeklies are usually tight, but a spread gate at signal time protects against news spikes and far-OTM fallbacks. Log it as an advisor first. |
| Half off at +X%, trail the rest | Exit variant | Medium | Same as in OpenProphet. |
| Persona "veto" reviews logged as PASS/VETO | Advisors | Low | ApexOptions already does would-veto logging, and deterministically. |

**Red flags**

- **Guardrails are explicitly non-binding.** The logs show them being overridden.
- In `manageRiskOrders()`, when the stop or the take-profit fills, the **sibling order is not cancelled**. Only the status changes, so the stop and take-profit are not linked as OCO. An orphaned order can later open an unintended position.
- Percentage stops on option premium.
- 10-second polling.
- Deprecated.

---

## 5. Skopaq-AI/skopaqtrader (SkopaqTrader)

**How it was found.** Web search returned `github.com/Skopaq-AI/skopaqtrader`; there is also a mirror at `samuelvinay91/skopaqtrader`.

**What it is.** A large Python 3.11 platform for Indian equities.

- **About 71k lines of Python**, about 25.7k of them in 127 test files.
- Built on a vendored copy of TauricResearch/TradingAgents (LangGraph).
- Apache-2.0. Last commit 2026-10-02.
- **Brokers:** INDstocks (INDmoney) REST and websocket (`skopaq/broker/client.py`, `websocket.py`, `token_manager.py`, `scrip_resolver.py` with `NSE_<security_id>` scrip codes), plus Zerodha Kite (`broker/kite_client.py`, with a daily OAuth `request_token` flow) and Binance.
- Parts: FastAPI, Next.js dashboard, Telegram bot, MCP server (1.9k lines), autonomous daemon (`execution/daemon.py`, `scheduler.py`).

**Decision logic actually in code**

- The core decision is the TradingAgents LLM graph (`graph/skopaq_graph.py`):
  1. market, news, social and fundamental analysts
  2. bull/bear debate
  3. trader
  4. portfolio manager, which outputs a confidence of 50–100%
- `scanner/engine.py` and `screen.py` run 3 LLM screeners (Gemini, Grok, Perplexity) every 30 s over the NIFTY 50.
- Multi-model tiering by role is in `llm/model_tier.py`. Redis semantic cache is in `llm/cache.py`.
- Position exits (`execution/position_monitor.py`) are three-tier:
  1. Hard safety stops (`_check_safety`).
  2. An AI sell analyst every N cycles, run as a bounded async task. A slow answer is applied "in the cycle it arrives".
  3. An EOD safety net. No new orders are placed after 15:29:55 IST (`deadlines.can_place()`).
- **Min-profit gate.** An AI SELL is overridden to HOLD if net profit after an estimated ₹120 round-trip brokerage falls below a threshold (`_ai_reason`). Hard stops are not affected.

**Risk gates**

- `constants.py: SafetyRules` is a **frozen dataclass**, so the learning code cannot mutate it. Limits:
  - 15% per position
  - daily / weekly / monthly loss limits of 3% / 7% / 12%
  - 5 positions, 5 lots
  - ₹5L per order, 20 orders/min
  - stop required, at least 2% away
  - 15-minute cooldown after a loss
  - no naked option selling
  - plus evolution guardrails
- Variants: `PAPER_SAFETY_RULES` (drops the stop requirement), `DAEMON_SAFETY_RULES` (tighter), and crypto variants.
- `execution/safety_checker.py: SafetyChecker.validate()`:
  - **Risk-adding checks apply only to BUYs.** Its docstring: "Otherwise a stop-loss or EOD exit would be refused exactly when it is needed."
  - A no-short-sale check reads the live order book, subtracts open SELLs and unshown fills, and refuses the order if the book is unreadable.
  - Option SELLs are rejected outright.
  - Sector concentration is capped at 40%.
- `execution/kill_switch.py`: a single halt that every path obeys. Sources: an env var, a halt file (`~/.skopaq/HALT`), or a Supabase `system_flags` row shared across processes. BUYs are blocked and SELLs stay allowed.
- `risk/drawdown.py` persists drawdown state across restarts.
- `risk/regime.py: RegimeDetector` uses India VIX bands (<13, 13–20, 20–30, ≥30) × NIFTY vs its 200-SMA (±2% band) to produce a size scale of 0–1.2. Data comes from yfinance `^INDIAVIX` / `^NSEI`.
- `risk/calendar.py: NSEEventCalendar`:
  - AVOID (scale 0): RBI policy days, Budget on 1 Feb, election results
  - CAUTION (0.7): F&O expiry
  - the NSE holiday list fails closed: a year with no list is treated as a non-trading day
- `risk/position_sizer.py`: 1% risk / (2 × ATR), multiplied by regime × calendar × confidence scales.

**Journaling and learning**

- `execution/order_journal.py`; late-fill reconciliation in `position_monitor.record_late_fill`.
- `learning/tracker.py` tracks signal accuracy by symbol, sector, regime, time of day and confidence calibration.
- `memory/reflection.py` writes BM25 reflection memory into prompts.
- `backtest/`: `walk_forward.py` (walk-forward efficiency), `monte_carlo.py`, `evolve.py` (the "self-evolving loop").

**Evidence quality.** Weak.

- `backtest/evolve.py: run_evolution_cycle()` grid-searches **an RSI threshold strategy**, not the LLM pipeline. The LLM decisions are never backtested.
- `monte_carlo.run_monte_carlo()` permutes trade returns. That changes the path and drawdown, never the total return, so it says nothing about edge.
- `backtest/engine.py` enters at the **signal bar's close** × (1 + slippage), which is optimistic. Costs are a flat 0.1% plus 0.1% slippage.
- The README advertises a "Track record" command (`skopaq report`), but no results are published in the repo.
- "~45x speedup" refers to cache hits, not trading.

**Indian market / NSE handling: notes for ApexOptions**

- **Stale expiry logic.** `risk/calendar.py` hard-codes F&O weekly expiry as "every Thursday" and monthly expiry as the last Thursday (`_all_thursdays`, `_last_thursday`). NSE moved NIFTY weekly and monthly expiries to **Tuesday** from September 2025. Never copy weekday-hard-coded expiry logic; take expiries from the Breeze instrument master.
- `options/chain.py` declares an `iv` field that is **never computed** (it stays 0.0). ApexOptions' Black-76 IV is far ahead.
- `options/strategy.py` is a short-premium selector (short put/call/strangle/condor). It contradicts `no_naked_option_selling`, and `SafetyChecker` rejects option SELLs anyway, so it is effectively dead code on the safe path.
- The useful Indian specifics:
  - market-hours constants: pre-open 09:00–09:08, open 09:15–15:30
  - an order cut-off at 15:29:55
  - an NSE holiday list that fails closed
  - RBI and Budget dates for 2025–26
  - India VIX regime bands
  - the INDstocks/Kite token lifecycle (daily expiry, much like Breeze's session token)

**Ideas for ApexOptions**

| Idea | Module | Value | Why |
|---|---|---|---|
| **Exits never blocked by entry gates.** Loss limits, cooldown and halt apply to BUY only. | Risk layer / exit engine | **High** (cheap) | All-in, a blocked exit is catastrophic. Add an explicit test: after the daily-loss limit or a halt, the stop, thesis-void and time exits still go through. |
| **Frozen safety constants** (frozen dataclass), separate from learnable parameters | Risk layer vs self-learning loop | **High** (cheap) | Guarantees the variant/champion machinery can never touch the futures stop cap, daily loss limit or halt rules. |
| **Halt file / env-var kill switch obeyed by every process** | Ops | Medium | One `touch HALT` stops all 10 paper books (and, later, live) at once. |
| **Restore persistent loss state on restart** | Daily/weekly loss tracking | Medium | With ₹1L/day compounding, a crash and restart must not reset the day's P&L. |
| **Event calendar** (RBI, Budget, holidays; fail closed on a missing holiday list) | New would-veto advisor | Medium | For an option *buyer*, event days may be the best days, so log it as advisor #6 and do not gate. Use correct Tuesday expiries from the instrument master. |
| **India VIX regime bucket** as a journal dimension | Journaling / evaluation slices | Medium | Slice each variant's expectancy by VIX band and by time-of-day bucket, as `learning/tracker.py` does. Useful for diagnosing *when* the domino trigger works. ATM IV is already in the system, so VIX is a cheap second axis. |
| **Order cut-off deadline** (no new orders after 15:29:55; ApexOptions should use its own earlier entry cut-off) | Time exits | Low–Medium | Probably already covered by the time stop, but an explicit "no new entries after T" guard is cheap. |
| **Min-profit-after-costs gate** on *discretionary* exits | Thesis-void exit | Low | Worth testing as a variant: do not thesis-void-exit a position that is green but below costs. A hard stop must never be gated this way. |
| Walk-forward efficiency metric | Evaluation | Low | ApexOptions' LODO plus SPRT is already stronger. |

**Red flags**

- The LLM pipeline is unvalidated, and the "self-evolution" loop optimises an unrelated RSI strategy.
- The Monte Carlo is a no-op on total return.
- The expiry calendar is stale.
- `PositionSizer.compute_size()` returns `max(min_qty, floor(raw))`, so a regime or calendar scale of 0 still yields **1 share**. The daemon must rely on `should_trade` elsewhere.
- Paper rules disable the stop-loss requirement, so paper behaviour differs from live.
- Running three LLM screeners every 30 s is expensive and slow.
- Very large surface area: Binance, gas oracles and whale alerts in an "Indian equities" platform.

---

## 6. "Fables": czlonkowski/fables

**How it was found.** Web search for "Fables Astra advisor Sol worker Fable orchestration" returned `github.com/czlonkowski/fables`. Its README is titled "Advisor and orchestrator protocols for Claude Fable and GPT-6 Astra", and its latest commit is "Publish Astra Orchestrator with updated worker models". It matches the brief exactly.

**What it is.** Four Claude Code / Codex **plugins** made of skill and agent markdown, plus eval JSON. There is no executable trading code.

- 29 files. MIT licence. Last commit 2026-10-01.
- `fable-advisor` (consult up): a compact verdict from a premium model, capped at 1–3 consults with a short brief.
- `fable-orchestrator` (delegate down): a premium parent plans, and cheap parallel workers read and extract.
- `astra-advisor` and `astra-orchestrator`: the GPT-6 Astra parent uses Sol 6.1 / Luna 6 workers.
- `evals/` holds scenario specifications. The README is candid: its trigger benchmarks are about 20-query tests, the cost figures (~2.5× cheaper, 3× faster) are historical pilots, and the Astra routing is "not runtime-tested".

**Trading-related content.** None. A grep for "trad / stock / market" finds only words like "tradeoffs" and "contradiction".

**Relevance to ApexOptions.** Low, and only for *developer workflow*: it suggests how to use a premium model as a one-shot reviewer for risk-layer or research diffs, which is the same pattern as Claude-trading's `risk-reviewer` and `quant-validator` sub-agents. It has no runtime value for the trading system.

---

## Consolidated top picks for ApexOptions (ranked)

1. **Timing null** (Claude-trading `test2026.null_expectancy`). Shift entries to random other days at the same time of day and re-price with the same exits on recorded ticks. Directly tests whether the domino timing has skill.
2. **Random-entry, same-exits cost null.** Quantifies how much of 1R the option round-trip costs eat before any edge.
3. **Day-clustered statistics** for SPRT, t-test and LODO across 10 correlated books, plus a correction for picking the best of 9 variants.
4. **Freeze plus hash plus holdout ledger** for the pre-registered variant registry, with a `contaminated` flag.
5. **Exits never blocked by entry or loss gates**, plus **frozen safety constants** that the learning loop cannot touch (SkopaqTrader `SafetyChecker`, `SafetyRules`). Add tests for both.
6. **Promotion requires realised-vs-modelled slippage within tolerance**, with bid/ask logged at the signal tick.
7. **Order intent persisted before submit, plus reconciliation at startup** (OpenProphet). Needed before any live Breeze order.
8. **Kill-switch extras**: order-rate runaway, position-mismatch, data-staleness, a shared halt file, and P&L state that survives restarts.
9. Pre-registered **exit variants**: half off at +1R with the rest trailed; a spread/mid liquidity check as an advisor; an event-calendar advisor and an India VIX regime slice, logged only.

Avoid copying:

- prompt-only limits (OpenProphet, Claude_Prophet)
- self-editable permissions (OpenProphet `update_permissions`)
- non-OCO stop and take-profit pairs (Claude_Prophet)
- kill switches that block exits (llm-paper-trading-agent)
- weekday-hard-coded expiries (SkopaqTrader)
- permutation "Monte Carlo" presented as robustness evidence (SkopaqTrader)
