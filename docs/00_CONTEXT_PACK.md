# APEXOPTIONS — CONTEXT PACK (the shared brief)

*Project:* ApexOptions — a fresh-build, live-order Nifty options BUYING system for one trader (the owner).
*Location on the owner's machine:* `D:\ApexOptions` (new, empty apart from this `docs/` tree and three NSE factsheets).
*Prepared:* Saturday 17 October 2026, 01:30–02:30 IST, by the chief architect (Claude) after reading the owner's previous systems in `D:\ClaudeCode` and three design conversations with the owner.
*Audience:* every member of the 30-person design team, and the owner.
*Status of claims:* every statement below is tagged. **[FACT]** = verified in code, logs, documents or the broker's own pages. **[OWNER]** = the owner's stated requirement or idea, as close to his words as possible. **[ANALYSIS]** = the architect's reading. **[HYPOTHESIS]** = an idea that must be tested before it is trusted.

---

## 0. How to use this pack — rules for the team

1. Read all of it before writing a word. It is the only shared memory the team has.
2. Nothing in this pack is sacred except Section 1 (the mandate) and Section 2 (hard constraints). Everything else may be challenged — but a challenge must say *why* and *what evidence would settle it*.
3. Label your own claims the same way: FACT / OWNER / ANALYSIS / HYPOTHESIS. The owner has been burned by systems that shipped hypotheses as facts (see §3.4).
4. Never put broker credentials, session keys or account numbers in any document or code. (They were found in plaintext in the old repo's test scripts; that mistake is not repeated here.)
5. Be skeptical by default. The owner's own words: the system must be "constantly vigilant and skeptical and on its toes." That applies to the team too.
6. Write for the owner: he is a Technology Architect and an experienced discretionary Nifty options buyer. He does not want filler, hedging or jargon without definition. He wants to know *what the system is, what it will actually do, and how it will achieve that.*
7. The owner will answer open questions later, not now. Do not block on them; state the assumption you are making and carry on.

---

## 1. THE MANDATE — what the owner asked for

### 1.1 Trading scope **[OWNER]**
- Trades **only NIFTY** index options. BankNifty, FinNifty and all heavyweight stocks are **sensors**, never traded.
- **Only BUYS options** (long CE or long PE). Never sells/writes. The owner: *"I will only buy options. I will not sell them. Which is even more dangerous. So keep this in mind from the very start."*
- Capital: **₹1,00,000 fresh every trading day.** *"Go all in every time it takes a trade. Use the profits and again go all in when it takes another trade and so on."* → intraday compounding: `lots = floor(capital / (premium × lot_size))`, and after every exit `capital += realised P&L`.
- This is a **live-order system** — it "actually takes a trade". The previous systems were paper-only (§3).
- *"This will be totally a new set up."* — the old decision logic is NOT carried over; only what the team deliberately decides to reuse.

### 1.2 Non-negotiable product qualities **[OWNER]**
- **Superfast. Tick-by-tick display is paramount. No delay there.** *"This should be your primary focus point even before you start coding."*
- **Constantly vigilant and skeptical** about positions across the whole universe: *the stocks (actual cash value), their option prices and OI development, their futures — and the indices (Nifty, BankNifty, FinNifty), their option prices and OI development, their futures.*
- Tracks **all heavyweight stocks of Nifty 50, Nifty Bank and Nifty Financial Services** (NSE factsheets provided, §4).
- **Fool-proof** — the owner's word. The team must define what that can and cannot mean (the red team owns this).
- The owner's historical pain, in his words (from the previous system's requirement log — context, not binding): entries are late ("when the trade comes, the move is already done"); he hates voting/multi-evidence gating that "kills all the moves and enters too late"; prices must display on time; he wants "why this trade" on every entry; commentary only for the most significant events; audible alerts.

### 1.3 Features the owner asked for explicitly **[OWNER]**

**(a) Buyers vs sellers tracking.** *"Uses the number of buyers and the number of sellers (and keep a track of how they are increasing and decreasing) to understand the price movement of that option… for example, the sellers standing are constantly falling slowly or fast in numbers and the price is running for that CE/PE."*

**(b) Volume per unit time** (per bar or per interval). *"Do not use stale data over a period of time."*

**(c) A force detector.** *"Detects how the price is not falling below a level or how is it not going above a particular level because of an opposite force… I need the system to detect that this time this supporting force is not enough and will not be able to hold a level or will break (or vice versa that this time this resisting force is not enough and will not be able to stop the price from breaking that level)."*

**(d) Scope of (a)–(c):** all tracked stocks and indices, *"but specifically for NIFTY and not just ATMs in NIFTY (CE and PE), but at least 2 ITMs and 2 OTMs of both CE and PE of Nifty."* → the ten Nifty "hero contracts": strikes ATM−2 … ATM+2, both rights.

**(e) Greeks at the BUY trigger.** *"How can we also leverage option greeks to take a better decision making during a BUY trigger. Be it a CALL or a PUT trade."*

**(f) The domino effect.** *"Market sometimes work like a domino effect. One falls making the other fall and gradually it comes up to Nifty (after a very short lag). We need to take the opportunity during this lag to enter a winning directional trade."*

**(g) Pressure zones.** *"Market tends to create a high pressure zone and a low pressure zone. Wind always move from high to low pressure zones. If a system keep a good track of all such pressure zones, and then when winds start moving, we can set sail on our ship to that low pressure zone before it is too late."*

**(h) The upheaval detector.** The owner asked how the constituent universe can be leveraged *"to see a change that is going to create an upheaval in Nifty"* and to enter before/while it forms.

### 1.4 The owner's historical preferences (MYTHOS era — context only, to be re-confirmed, NOT binding) **[OWNER, historical]**
- Strikes: "I trade the ATM generally, or just OTM if my conviction is very strong"; later: "I need ATM or ITM which will MOVE" (never OTM after two OTM losers).
- Exit geometry he lived with: hard stop at entry −10 premium points; wanted +12 minimum but let winners run; "Nifty hunts stops right after entry → ruthless early, relax the trail once convincingly in profit".
- "Cannot hold more than 5–7 minutes by hand; come out with some profit if it doesn't run, re-enter on the next setup."
- "Try to buy cheap but don't miss the move" — a brief resting limit below LTP, then take it.
- Expiry-day caution (theta kills a flat trade). No invented time-of-day cutoffs. Persistent memory of battle-tested levels across sessions.

---

## 2. HARD CONSTRAINTS (broker, exchange, machine) — all **[FACT]** unless marked

### 2.1 ICICI Direct Breeze API — limits and behaviours
- **REST: 100 calls/minute AND 5,000 calls/day, across ALL endpoints — quotes, option chains and order placement alike.** (ICICI Direct FAQ "What is the rate limit for Breeze API?"; ICICI community notice.) Over a 375-minute session that is **~13 calls/minute sustained**; orders eat from the same pool.
- **Orders: a combined limit of 10 orders/second** (placement, cancellation, modification, square-off).
- **Market orders are NOT permitted.** The SDK converts "market" into an aggressive limit inside a price band — **options: 10% band, minimum 5-point difference**; futures 1.5%; equity 3% (Breeze Python SDK README). Consequence: every entry and every stop-exit must be an explicit LIMIT priced by us off the live bid/ask and re-priced if unfilled.
- **Order notifications stream over the WebSocket** (`subscribe_feeds(get_order_notification=True)`) — fills can be reconciled with zero REST calls.
- **A "limit price & quantity calculator" endpoint** (`fnolmtpriceandqtycal`) returns `limit_rate`, `order_margin`, `available_quantity` — an affordability/sizing check for all-in sizing.
- **WebSocket subscriptions:** by instrument parameters or by token (`stock_token="4.1!2885"`, lists accepted). Exchange-quote ticks carry: `symbol, open, last, high, low, change, bPrice, bQty, sPrice, sQty, ltq, avgPrice, quotes, ttq, totalBuyQt, totalSellQ, ttv, trend, lowerCktLm, upperCktLm, ltt, close, exchange, stock_name` (+ `OI`, `strike_price`, `right`, `product_type`, `expiry_date` on F&O — confirmed in the old system's hot path). Market depth (`get_market_depth=True`): five levels each side with `BestBuyRate-N, BestBuyQty-N, BuyNoOfOrders-N, BestSellRate-N, BestSellQty-N, SellNoOfOrders-N`. An OHLCV stream exists with `interval` ∈ {1second, 1minute, 5minute, 30minute} carrying `oi`.
- **No documented cap on feeds per socket.** The old system carried ~50 feeds on one socket. Capacity at ~300 feeds, and depth message weight at the open, are **unknown → must be measured** (the first live probe).
- **The SDK README mentions a registered static IP** ("primary or secondary static IP provided by the client can be updated only once per week"). Whether this applies to the owner's account for order placement is an **open question** (§6).
- **Session:** `BreezeConnect(api_key)` → `generate_session(api_secret, session_token)`. The session token is the `apisession=` value from the daily login redirect, refreshed manually every morning. A mid-day session death does not raise exceptions — `subscribe_feeds` starts returning error *strings* while cached prices look alive. For a live-order system this means: **a dead session = you cannot exit via API.**
- **WebSocket endpoint** `livestream.icicidirect.com` (socket.io). Its TLS certificate was re-issued on **12 Oct 2026** (GlobalSign GCC R46 EV TLS CA 2025). On **16 Oct 2026, 10:24–10:46 IST**, the old system's WS refused to connect three times ("Failed to connect to live stream"); the owner saved the new certificate at 11:09 and the socket connected at 11:10. What exactly fixed it is an open question (§6). The new system must handle TLS trust explicitly.
- **Known Breeze quirks (from 4 months of logs):** `get_names()` (ScripMaster lookup) breaks upstream periodically → cache resolved codes on disk; India VIX code `INDVIX` sometimes returns a value 100× too small; `subscribe_feeds` returns an error STRING instead of raising; REST option-chain responses can silently freeze (identical/empty) for hours mid-session; transient `ConnectionReset 10054 / Read timed out / RemoteDisconnected` on REST are normal; always `ws_disconnect()` on shutdown (an orphaned socket holds a slot and trips errors on quick restart); `import breeze_connect` is slow (downloads the scrip master); `datetime.strftime('%b')` is locale-dependent on Windows — expiry strings must be built from an explicit English month list.
- **Breeze codes that work:** Nifty spot `NIFTY` (NSE, cash); futures/options `NIFTY` on `NFO`; VIX `INDVIX`; BankNifty spot `CNXBAN`; **FinNifty: no working code found among `NIFFIN / FINNIFTY / NIFSER` as of 16 Oct 2026 23:16**; heavyweights via ISEC codes resolved by `get_names` (e.g. RELIND, HDFBAN, ICIBAN, BHAAIR, LARTOU, INFTEC, STABAN, AXIBAN, KOTMAH, ITC, TCS, MAHMAH, BAJFI, HINLEV) with equity tokens (e.g. HDFCBANK 1333, RELIANCE 2885).
- **Expiry string formats:** WebSocket `16-Jun-2026`; REST `2026-06-16T06:00:00.000Z`.

### 2.2 NSE / contract facts
- **Nifty weekly options expire on TUESDAY** (since Sep 2025); monthly index derivatives on the **last Tuesday**. If that Tuesday is an NSE holiday, expiry moves to the **previous trading day**. Contracts are dead after 15:30 on expiry day. NSE 2026 weekday holidays loaded in the old config include: Oct 20 (Dussehra → weekly expiry Mon Oct 19), Nov 10 (→ Mon Nov 9), Nov 24 (monthly → Mon Nov 23), Dec 25.
- **Nifty lot size 65** (owner-confirmed June 2026 — re-verify; NSE revises lots). **Strike step 50.** Market 09:15–15:30 IST.
- **Stock options are monthly-expiry only** (no weekly stock options); stock option liquidity is thinner and strike steps/lot sizes vary per stock. **Stock futures** (near month) are liquid and carry OI — the better real-time positioning sensor for stocks.
- Nifty level in mid-October 2026: ~22,500–23,100 (spot 22,715 on 15 Oct; 23,065 on 16 Oct — from the old system's logs). ATM weekly premiums seen: ₹85–₹210.
- Index options are European, cash-settled; dividend ≈ 0 for pricing.
- NSE freeze quantity per order for Nifty options exists and must be re-verified; as capital compounds the all-in quantity may require order slicing.
- STT on option sale, exchange transaction charges, SEBI fee, stamp duty, GST and brokerage apply (the old system booked gross P&L; the new one must book net).

### 2.3 Owner's machine and stack
- Windows desktop (`desktop-2jkhr8a`), drive `D:`. Python **3.13** (per compiled caches). `breeze-connect ≥ 1.0.65`, numpy, scipy, FastAPI/uvicorn, pygame were used previously. No `uvloop` on Windows. `multiprocessing` uses spawn on Windows.
- The owner runs the system himself each morning (session key paste, launch, open dashboard in a browser).

---

## 3. WHAT EXISTS — the previous systems (`D:\ClaudeCode`)

### 3.1 Two generations, both PAPER-ONLY **[FACT]**
- **HAWK** (`run7/`, Apr–Jun 2026): Rich-console dashboard, "brain" subprocess, lock-free feed. "All-in, no partials, capital compounds on every trade" (on paper).
- **MYTHOS** (`mythos/`, Jun–Oct 2026, still running daily as of 16 Oct): FastAPI/WebSocket dashboard, 1 Hz analytics thread + 4 Hz exit thread, SQLite flight recorder, virtual clock + tape replay, ~12 decision modules (most shadowed), a paper trader with full-capital sizing and intraday compounding.
- **No order-placement code exists in either**: no `place_order`, `get_order_detail`, `get_portfolio_positions`, `square_off`, `cancel_order`, `get_margin`. The execution layer for ApexOptions is greenfield.

### 3.2 The Breeze data layer that already works (reusable knowledge) **[FACT]**
- Lock-free `PriceStore`: the WS callback is the single writer of plain dicts; everything else reads lock-free (CPython GIL atomicity). Proven zero tick-drops for months.
- `on_ticks` hot path: dict writes only, never raises, no logging, no allocation beyond one deque append.
- Tick routing: equities by **token** in `symbol` (`"4.1!<token>"`), spot by token with `stock_name` fragment fallback; F&O by `product_type` ∈ {futures, options} and `strike_price`/`right`.
- Subscriptions: spot ATM±8 both rights (34 feeds) re-centred every ~10 s; on reconnect replay every previously held strike.
- Reconnect: exponential backoff 3/6/12/24/48 s; off-hours silence gated so it doesn't burn the budget; "3 consecutive all-rejected subscribe passes ⇒ session dead ⇒ force reconnect"; REST spot fallback when WS spot is stale >10 s.
- REST pollers on fixed budgets (~9 calls/min total): Nifty chain both rights every 90 s, 14 heavyweight chains round-robin one stock / 20 s (⇒ each stock's chain refreshed every ~4.7 min), VIX every 60 s, sister indices every 20 s.
- Watchdogs that key on response *signature* (row count + total OI) because the REST chain froze silently for ~3 hours on 06 Jul 2026 with zero exceptions.
- Honest accounting: buy at ASK, sell at BID ("honest fills" — measured ~2 pt/trade drag vs LTP).
- Preflight script (GO/NO-GO before 09:15): session → spot → VIX → chain → heavyweights → WS + one option subscribe.

### 3.3 MYTHOS performance — its own archive, 31 sessions **[FACT]**
361 paper trades, honest ASK/BID fills, ₹1 lakh daily reset:
- Net **−355.5 premium points / −₹3,29,492**. **Positive on 8 of 31 days.**
- Win rate **41%**; average win **+4.3**; average loss **−4.7**. (A "−10 / +12" doctrine trading as a ±4.5 coin flip.)
- Median hold **2.9 min**; median peak **+3.1 pts**. Peak ≥ +5 on 33% of trades; ≥ +12 on **11%**; ≥ +14 on 9%; ≥ +20 on 3%.
- Exit reasons: TRAIL SL at a ramp floor 132 (avg +3.8); "4MIN SUB-5 — KILLED" 75 (−2.1); "NO FOLLOW-THROUGH" 55 (−1.4); hard SL HIT **50** (−10.2); "3MIN SUB-6 — SCRATCHED" 19 (−4.1); STALL KILL 14; EOD 5; STALE QUOTE 5; "OPPOSITE ARMED — FLIPPED" 5 (−6.3). **163 of 361 exits (45%) were time-based kills/scratches.**
- 58 of 205 losers were green by ≥ +3 before reversing (the owner's "price pulls back" pattern); 24 were green by ≥ +5.
- Forward-test ledger (real fills): the "leg" path −107.8 pts over 12 days (profit entirely in 2 trend days; drop the best day → −204.8); the "ignition" engine −138.5 pts out-of-sample at live cadence; the "resume brain" (10:00 opening-drive read → pullback → resumption → delta≈1 ITM option) +87 pts in-sample on 14 days, 12/14 green, flagged as marginal/screening-level by its own stats review and never allowed into the book.
- 16 Oct 2026 (the last session): 12 trades, ₹1,00,000 → ₹74,390; max peak of any trade +5.0.

### 3.4 Why MYTHOS was late and why trades pulled back **[ANALYSIS, supported by the code and its own docs]**
- Every live entry path was a **confirmation design**: the zone path needed a confirmed pivot held ≥2 s + a CVD sign-flip + a ≥12-pt drop into the zone + premium within +4 of the zone-low + ≥6 of 14 evidences; the "Brownie points" path waited for option-*writing events* (OI prints that occur after the move); the resume brain waited for pullback-and-resumption. All three fire after the inflection. The architecture document admits it: *"the rails guarantee post-inflection entry."*
- The response was to add more brains (~12 decision modules, most shadow/flag-off) rather than change the premise. The project's own kill-criterion council named the pattern: *"six full rebuilds, each shipped live unproven the next morning."*
- The exit ladder accreted ~15 stacked rules (hard SL, EOD, opposite-side flip, grace, 12/15/18-minute budgets, 4-min sub-5 kill, 3-min sub-6 book mode, points-faded, stale mode, a floor ramp arming at peak +3, an exponentially decaying chandelier, per-kind leg profiles, blind hold, scratches, stall kills). A floor armed at +3 and a kill at 4 minutes means a correct entry has no room to breathe.
- Cross-instrument "co-equality" was never built: 14 Nifty names only; their option chains refreshed every ~4.7 min; BankNifty/FinNifty were spot-LTP-only; their influence was a 40% weight in a sentiment gauge.
- Operationally the system was sound; the decision layer was the failure.

### 3.5 Reusable assets **[FACT]**
- **Recorded flight-recorder frames**: `D:\ClaudeCode\mythos\data\mythos.db` (8.2 GB), table `frames(day, ts, frame JSON)` at ~1–2 s cadence for 30+ sessions since 12 Jun 2026 (per-frame: spot, futures, near-ATM option ltp/bid/ask/OI/volume, heavyweight cash LTPs, sister-index LTPs, VIX, and since ~1 Jul the heavyweight option chains with per-strike OI). Intra-frame tick order is lost; no depth. Usable to test the domino/synchrony/positioning hypotheses before any live money, and as a sanity backtest for triggers.
- The Breeze hardening list above (§3.2), the Black-Scholes/IV solver approach (vectorised bisection; deep-ITM fallback), the holiday-aware expiry calendar, the virtual clock + tape replay pattern, the SQLite WAL writer-thread pattern, the preflight script.
- Trade archives (CSV/JSON per day) and 4.5 MB of recent logs.

### 3.6 Source map (staged copies readable by the team in this container)
`/mnt/user-data/uploads/ClaudeCode/mythos/feed.py` (Breeze layer, 948 lines) · `trader.py` (paper trader & exit ladder) · `app.py` (orchestrator, thread model, pollers) · `config.py` (every tunable; §"INSTRUMENT", expiry functions at lines 1–230) · `greeks.py` · `store.py` · `server.py` · `tape_feed.py` · `sim_feed.py` · `clk.py` · `contracts.py` · `archive.py` · `/mnt/user-data/uploads/ClaudeCode/preflight.py` · `run_mythos.py` · `check_feed_health.py` · `run7/hawk_feed.py` · `run7/hawk_trader.py` · docs: `README_MYTHOS.md`, `MYTHOS_ARCHITECTURE.md`, `MYTHOS_TRADING_RULES.md`, `KILL_CRITERION.md`, `FORWARD_TEST_LEDGER.md`, `REQUIREMENTS.md`, `Requirement.txt`, `MYTHOS_HOW_TRADES_ARE_TAKEN.md` · trade archives under `mythos/archive/trades_*.csv` · last log `mythos/logs/mythos.log`.

---

## 4. INDEX STRUCTURE — NSE factsheets dated 30 September 2026 **[FACT]**
(files: `D:\ApexOptions\ind_nifty50.pdf`, `ind_nifty_bank.pdf`, `ind_Nifty_Financial_Services.pdf`; staged at `/mnt/user-data/uploads/ApexOptions/`)

**Nifty 50** — 50 constituents; Financial Services 37.45% of the index; Oil, Gas & Consumable Fuels 9.39%; IT 7.52%; Autos 6.65%; FMCG 5.50%; Telecom 5.10%; Metals 4.86%; Healthcare 4.74%; Construction 4.20%. Top 10 by weight (52.3% of the index): HDFC Bank 10.38 · ICICI Bank 9.05 · Reliance 7.58 · Bharti Airtel 5.10 · L&T 4.20 · SBI 3.79 · Axis Bank 3.37 · Infosys 3.35 · Kotak Bank 2.93 · M&M 2.52. (MYTHOS's May-2026 weights are stale: e.g. HDFC 10.56, ICICI 8.32, RIL 8.27, Infy 3.77; ITC has left the top 10.)

**Nifty Bank** — **14** constituents (not 12); beta 1.15 to Nifty, correlation 0.91. Top 10 (87.5%): HDFC Bank 18.61 · ICICI 14.18 · Kotak 10.20 · Axis 10.06 · SBI 9.93 · Federal 6.56 · IndusInd 4.97 · AU SFB 4.85 · IDFC First 4.54 · Bank of Baroda 3.59.

**Nifty Financial Services** — 20 constituents; beta 1.20, correlation 0.93; top-3 weights capped at 19/14/10%; non-F&O stocks capped at 4.5% each. Top 10 (86.2%): HDFC Bank 18.63 · ICICI 14.20 · Axis 10.18 · Kotak 10.11 · SBI 9.94 · Bajaj Finance 8.62 · Shriram Finance 4.53 · BSE Ltd 4.16 · Bajaj Finserv 3.31 · SBI Life 2.51.

**Structural fact:** HDFCBANK, ICICIBANK, AXISBANK, KOTAKBANK, SBIN are in all three indices — ~29.5% of Nifty, ~63% of Bank Nifty, ~63% of FinNifty. Five stocks move all three indices. FinNifty ≈ Bank Nifty + the Bajaj twins + Shriram + BSE + SBI Life.

**Gap:** the factsheets list only the top 10 per index. The full lists (~65–70 unique names across the three) must come from NSE's constituent CSVs (`ind_nifty50list.csv`, `ind_niftybanklist.csv`, `ind_niftyfinancelist.csv`) or be resolved via the API.

---

## 5. IDEAS DISCUSSED SO FAR (architect ↔ owner, 16–17 Oct 2026)

### 5.1 The tick path — designed first, everything subordinate **[ANALYSIS, agreed direction]**
- **Process layout, no shared GIL on the tick path:** FEED (owns the Breeze socket(s); parse tick → write a shared-memory "latest state" table (numpy over `multiprocessing.shared_memory`, one row per instrument) → publish the raw tick on ZeroMQ PUB; target < 50 µs per tick; no logging/datetime/allocation) · GATEWAY (binary WebSocket to the browser; hero instruments per tick, basket coalesced every 50–100 ms; computes nothing) · ANALYTICS workers (separate SUB sockets with drop/conflate; outputs written back with their own timestamp and shown with their *age*) · RECORDER (every tick to disk, append-only per instrument per day — tick-level replay, unlike MYTHOS's 1–2 s frames) · EXECUTOR (pre-warmed session, pre-resolved contract codes; a trigger = one HTTP call; listens to order-notification stream).
- **Browser:** typed-array state, `requestAnimationFrame` at 60 fps, canvas for dense panels; never one DOM update per tick.
- **Latency contract:** three stamps per tick (exchange `ltt`, FEED receive, paint). Feed-to-screen on the same machine under ~20–30 ms, measured continuously, shown on screen, alarmed on drift.
- If one Breeze socket queues at ~300 feeds, run 2–3 sockets on the same session with the universe split (to be tested).

### 5.2 The universe and the budget **[ANALYSIS, proposed]**
- **Tier 0 — Nifty complex (~40 feeds):** spot; near futures with 5-level depth; weekly options ATM±8 both rights, depth on ATM±2 (the hero contracts); BankNifty and FinNifty spot + futures; VIX by REST 1/min.
- **Tier 1 — the movers (~120 feeds):** the ten top-weight Nifty names (five common banks, RIL, Bharti, L&T, Infosys, M&M): cash tick + futures tick (price, OI, CVD) + monthly options ATM±2 both rights.
- **Tier 2 — the rest (~110 feeds):** cash + futures only; a name is *promoted* (chain fetched, options subscribed, depth on) when its activity spikes, demoted when quiet.
- REST ≈ 9/min ≈ 3,400/day (Nifty chain 2/90 s, VIX 1/60 s, Tier-1 chains 20 calls/5 min, sister chains 4/5 min) leaving ~1,500/day for orders/positions/funds.
- Every stock tick converted on arrival into **Nifty points implied** (weight × %change × index level) so the basket reads in Nifty's units.

### 5.3 The upheaval detector — what leads, what to watch, what to refuse **[HYPOTHESIS, to be tested on the recorded frames first]**
Causal order of a big Nifty move: (1) **positioning builds** (futures OI one-sided in heavyweights/index futures; writers crowd one side into walls; IV compresses (coil) or skew tilts; basis stretches) → (2) **the trigger** (Nifty-futures CVD and weighted stock-futures CVD turn *together*; basis jumps; book imbalance flips; ATM straddle starts expanding; OI at the nearest wall starts *unwinding* = writers covering = fuel) → (3) **propagation** (cash index catches up; premiums reprice — delta first, then vega; laggards join; sisters confirm) → (4) **exhaustion** (breadth narrows; CVD diverges from price; IV spikes then stalls; the opposite wall firms; pullback).
MYTHOS entered at stage 3–4. ApexOptions measures stage 1 as a continuous *state*, detects stage 2 within seconds **across the basket**, and refuses stage 3–4 entries.
Signals (each a worker on the tick stream): weighted impulse + **synchrony** (fraction of weighted names moving together with volume above their own baseline); flow (tick-rule CVD on Nifty futures and each Tier-1 stock future; agreement between index-futures flow and basket flow); positioning (per-stock futures OI quadrant at tick cadence, weight-aggregated); basis velocity; pressure-vs-breakout-force on the chain (wall OI vs OI unwinding rate + premium velocity); lead–lag table (who moved first); the skeptic's vetoes (Nifty moving without weighted participation = unsupported; IV already spiked = late; breadth narrowing = exhausting).
Honest framing: constituent flow leads the Nifty *print* by seconds, not minutes; the edge is (a) seeing the *structure* of the move (broad, synchronous, positioned) which filters fakes that pull back, and (b) option premiums reprice with their own lag (market makers follow futures; IV adjusts over minutes).

### 5.4 Greeks at the BUY trigger **[ANALYSIS, proposed]**
Breeze gives no Greeks; solve IV and Greeks from live premiums (vectorised Black-Scholes, bisection IV; T to 15:30 on expiry day). Five questions at the trigger:
- **Which contract — Delta & feasibility:** required spot move ≈ (target + θ·H + spread) / Δ for hold H minutes; compare to the move the basket impulse projects. ATM (Δ≈0.5) needs ~24+ pts for +12; just-ITM (Δ≈0.7) ~17; OTM (Δ≈0.3) 40+.
- **Convexity vs rent — Gamma/Theta:** θ ≈ −½σ²S²Γ; gamma/theta score per strike for the expected *speed* of the move (fast → ATM this week; slow → ITM or next week).
- **Time budget — Theta:** theta/minute computed live (rough prior: 0.3–0.5 pt/min morning, 1–1.5 pt/min afternoon in expiry week); if θ×H exceeds ~¼ of the target, demand a bigger projected move or a lower-theta instrument; makes stall-kills principled ("bleed exceeded").
- **Chase or wait — Vega/IV:** buying after a sharp move often buys an IV spike that deflates when the move pauses (premium falls without spot retracing — one mechanism of "pulls back after I enter"). Check IV change over last 5 min, IV vs short-window realised vol, straddle vs projected move; compressed IV + synchronous trigger is the sweet spot. Skew (put IV − call IV) as the "already positioned → late" check.
- **Regime gate — dealer gamma (GEX):** from chain OI × gamma per strike. Net positive dealer gamma → hedging against the move → pins, long options stall; net negative → hedging with it → moves accelerate. In a positive-gamma pin a BUY needs wall-unwinding force evidence; in negative gamma a synchronous impulse is enough.
Expiry-day refinements (charm, vanna, hedge unwind into 15:30) are second-order.

### 5.5 Order-book force & flow (the owner's features (a)–(d)) **[ANALYSIS, proposed]**
- **Standing vs hitting:** "sellers" in the book are passive (resting asks); aggressors are inferred per trade (printed at the ask → buyer hit; at the bid → seller hit). Track four series: resting buy qty/orders, resting sell qty/orders, aggressive buy volume, aggressive sell volume. "Sellers thinning while the CE runs" = resting asks disappearing AND trades at the ask.
- **Consumed vs pulled:** Δdepth explained by Δttq is consumption; the unexplained remainder is pull (withdrawn) or add (replenished). Consumed-and-not-replenished = wall being eaten; pulled-without-trades = sellers running (vacuum, gaps).
- NSE total-book quantities include far orders and are spoofable; near-touch depth and order counts carry more truth; totals are trend inputs, not triggers.
- **Freshness by construction:** every stat is a multi-horizon EWMA (half-lives ~2/10/60 s) carrying its *age*; older than its horizon = invalid, shown grey. `ltt` only advances on trades → book changes timed by receive time, trades by exchange time; volume always from ttq differences (several trades can land between ticks; `ltq` under-counts).
- Per-contract metrics: volume per 1 s bin → 5 s/15 s/1 m; trade intensity; average trade size; aggressor CVD with slope/acceleration; standing orders (qty and count at L1, L1–5, total) with 5 s/30 s derivatives and a rate class (refilling / holding / draining slowly / draining fast / pulled); book imbalance by qty and by order count; OI Δ per interval; price response (absorption vs vacuum).
- **The force detector** (per level per instrument, state machine `idle → approaching → testing → holding | breaking | broke | rejected`): supply S (resting asks at/just above L), consumed C, replenished R, pulled P, attack intensity A = dC/dt, absorption = C/progress; **ρ = R/C** (refilling as they're hit?), **π = P/S₀** (leaving?); verdicts **HOLD-STRONG** (ρ ≥ 1, A decaying), **BREAK-IMMINENT** (ρ < ~0.5 sustained, S draining, A steady/rising, π climbing, OI at strike unwinding — "the force is not enough"), **VACUUM** (high π, low C — fast move, thin fill, limit at the ask immediately), **FAKE** (ρ high & A weak, or one contract only, or underlying/basket not pushing). Thresholds calibrated from recorded hold/break outcomes, not hand-set. Mirror for support with bids.
- **Levels to watch:** OI walls; strikes/round numbers (underlying); round premiums 100/150/200 (contracts); session high/low; prior-day high/low/close; VWAP, anchored VWAP; battle-tested levels (tests counted). Nearest 2–3 above and below per instrument.
- **Underlying vs option:** direction decided by force at the Nifty level (futures book + basket); the CE's own book is the earliest tell — market makers pull asks in the contracts they expect to run before the futures level gives way.
- **Additions proposed:** cross-strike coherence (all five strikes of a side must agree — required for a trigger); CE-vs-PE book asymmetry across the ladder; iceberg detection (consumed > visible while level persists); large-order footprints vs spoofs (persist vs pulled within seconds); option-leads-futures lag table; attack-attempt profiling; basket book pressure (every stock's L1 force weighted into Nifty points); a force ladder on screen (ATM±2, CE left/PE right, signed force bars, sparklines of standing orders, volume/sec, CVD, OI-Δ); an event tape with audio on state changes only; trigger fusion (force verdict + coherence + basket participation + Greeks' "can pay").
- Subscriptions: exchange quotes for everything (L1, totals, ttq, OI); 5-level depth for the ten hero contracts + Nifty and BankNifty futures; depth on a Tier-1 stock future only when promoted.
- **First live probe before any threshold is designed:** subscribe the ten hero contracts + futures with depth during a session and record raw messages — confirm NFO depth carries order counts, OI arrives per tick, the actual update cadence, and depth message weight at the open.

### 5.6 The domino effect (owner's thought 1) **[OWNER + first reading]**
"One falls making the other fall and gradually it comes up to Nifty (after a very short lag). Take the opportunity during this lag."
Architect's first reading: a propagation chain exists (a heavyweight or a sector moves → correlated names and the sector index move → index futures (arbitrage/program trades) → the cash index print → option premiums (delta repricing, then IV)). Each hop has a lag of seconds; the option-premium hop (market-maker quote updates and IV adjustment) is the longest and the one an option buyer can exploit. The team must determine where the lag actually is, how big it is, how to measure it live, and how to enter inside it without being the last domino.

### 5.7 Pressure zones (owner's thought 2) **[OWNER + first reading]**
"Market tends to create a high pressure zone and a low pressure zone. Wind always moves from high to low. Track all such zones; when winds start moving, set sail to the low-pressure zone before it is too late."
Architect's first reading: "pressure" is where resistance to movement is concentrated — resting liquidity (depth), option-writer OI walls and dealer hedging, crowded positioning (futures OI), high IV; "low pressure" is where there is nothing to stop price — thin depth, no OI, unhedged gaps between walls, volume-profile voids. "Wind" is flow leaving the high-pressure side (OI unwinding, depth pulling, aggressive volume turning, IV shifting). The team must turn the metaphor into a pressure field over price per instrument (and for Nifty via the basket), define wind detection, the "set sail" trigger and the "too late" rule, and how zones persist across sessions.

---

## 6. OPEN QUESTIONS FOR THE OWNER (he will answer later; state assumptions and proceed)
1. What fixed the 16 Oct WebSocket outage (certificate installed where? env var? SDK upgrade?)
2. Exact `breeze-connect` version installed; ICICI account has API order placement for F&O enabled; brokerage plan; whether a static IP must be registered for API orders.
3. Lot size and NSE freeze quantity for Nifty options as of now.
4. One position at a time? (assumed yes.) Hard account-level daily stop? (The owner's council in June noted that full-capital sizing turns one −10 stop into a ~₹11–19k event; sizing is the owner's call — the team presents the math, does not override.)
5. Exit geometry for the new system (the old −10/+12 is NOT assumed).
6. Dashboard and audio expectations; whether the MYTHOS recorded frames may be used for validation (assumed yes).
7. Full constituent lists (CSV) for the three indices.

---

## 7. GLOSSARY
ATM/ITM/OTM — at/in/out of the money. CE/PE — call/put. OI — open interest. CVD — cumulative volume delta (aggressive buy volume minus aggressive sell volume). Basis — futures minus spot. GEX — dealer gamma exposure (Σ OI × gamma per strike, signed by who is long/short gamma). Wall — a strike with OI far above its neighbours. Hero contracts — Nifty weekly ATM−2…ATM+2 CE and PE (10). L1 — best bid/ask. Depth — 5 levels each side. ttq — total traded quantity (cumulative for the day). ltq/ltt — last traded quantity/time. Tick path — the FEED→GATEWAY→browser route that must never wait. Honest fills — buy at ask, sell at bid. Synchrony — fraction of weighted names moving the same way at once. Replenishment ρ — resting quantity added back per quantity consumed at a level. Pull π — resting quantity withdrawn without trades, as a fraction of initial supply.

---

## 8. TEAM STRUCTURE (30 members)
- **G1 Domino & Lag (market microstructure)** — 5 members
- **G2 Pressure Zones** — 5 members
- **G3 Order-book Force & Flow** — 4 members
- **G4 Options, Greeks & Instrument Selection** — 4 members
- **G5 Data Platform & Latency** — 4 members
- **G6 Execution, Risk & Capital** — 4 members
- **G7 Red Team, Validation & Research** — 4 members (second wave: critiques G1–G6)
- Chief architect (integration, master design, decision log) — the 30th.

Each group writes `docs/teams/G<n>_<name>.md`. The architect writes `01_MASTER_DESIGN.md`, `02_DECISION_LOG.md`, `03_OPEN_QUESTIONS.md`.
