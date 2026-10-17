# G1 — Domino & Lag (market microstructure)

*Working Group G1 report for the ApexOptions master design. Saturday 17 October 2026.*
*Tags as in the brief: **[FACT]** verified in code/logs/documents · **[OWNER]** the owner's requirement or words · **[ANALYSIS]** our reading · **[HYPOTHESIS]** must be tested before it is trusted.*
*Sources read in full: `00_CONTEXT_PACK.md`; `mythos/feed.py`; `MYTHOS_HOW_TRADES_ARE_TAKEN.md`; `FORWARD_TEST_LEDGER.md`; plus `mythos/app.py` (`_build_frame`, lines 1385–1496) and `mythos/config.py` (heavyweights, poll cadences) to establish exactly what the recorded frames contain.*

---

## 1. Members and their lenses

- **Meera Raghavan** — index arbitrage: the cash–futures basis, program trades, how fast the gap between a basket and Nifty futures gets closed, and by whom.
- **Daniel Okafor** — lead–lag econometrics: what "A leads B by k seconds" means statistically, what is and is not measurable at 1 s on a retail vendor feed, and how to avoid finding leads that are artefacts.
- **Siddharth Jain** — the bank group: what moves HDFCBANK/ICICIBANK/SBIN/AXISBANK/KOTAKBANK together, when the banks lead the index and when they are dragged by it.
- **Anja Berg** — options market making: how quotes are repriced on a futures move, where the IV re-mark lags, when quotes are pulled, what a buyer paying the ask can and cannot capture.
- **Rohit Menon** — quant development: turning all of the above into a detector that runs per tick without stalling, with honest latency arithmetic.

---

## 2. What we were asked

**[OWNER]** *"Market sometimes work like a domino effect. One falls making the other fall and gradually it comes up to Nifty (after a very short lag). We need to take the opportunity during this lag to enter a winning directional trade."* Also: entries must not be late — *"when the trade comes, the move is already done"* — and he hates voting/multi-evidence gating that *"kills all the moves and enters too late."*

**[ANALYSIS] Our reading.** The owner asserts three things: (1) a Nifty move is often *preceded* by moves in its parts; (2) the gap between the parts moving and Nifty (and its premiums) fully reflecting it is a "very short lag"; (3) an entry inside that gap has the odds on its side. We treat (1) and (3) as hypotheses to test on the recorded frames, and (2) as the thing to be most honest about: parts of the chain have *no* exploitable lag for a retail buyer, and the owner must be told which parts.

**Constraints that shape the answer [FACT]:** Breeze exchange-quote ticks carry `last, ltq, ttq, bPrice, bQty, sPrice, sQty, totalBuyQt, totalSellQ, ltt` (+ `OI, strike_price, right, product_type` on NFO); the only exchange timestamp is `ltt` (a last-trade time; its resolution on Breeze is believed to be one second — **[ANALYSIS]**, to be confirmed in the probe). Nifty futures peaked at ~30–50 ticks/s on the old feed (comment in `feed.py` line 52). The recorded frames are ~1–2 s snapshots with intra-frame order lost; the sister indices in those frames are REST polls every 20 s (`SENTIMENT_POLL_SEC = 20.0`), so they carry no second-level timing at all.

---

## 3. Ideas by member

### Meera Raghavan — "one number says whether anything is left to propagate"
- **[ANALYSIS]** Market makers price Nifty options off Nifty **futures** (or the synthetic forward), never off the cash print. So the only domino hop that can still be "unpriced" in a premium is *basket → futures*. The print is a computed average of constituent last prices, lagging only by stale constituents and dissemination. **A detector that triggers on the spot print triggers on a lagging indicator by construction** — MYTHOS's zone path did exactly that.
- **The gap G** = basket-implied Nifty move M_b (weights × returns × index level) minus the futures move M_f over the same window. When stocks have moved and futures have not, arbitrage desks and program traders close G — **[ANALYSIS, desk experience]** in liquid hours a few points are gone in 1–3 s; slower in thin periods (12:30–13:30), on expiry-day afternoons (arb unwinds dominate) and in disorderly tape (desks widen risk limits). The *level* of G is never exploitable; its *persistence* is — a basket that keeps pushing drags futures along for as long as the flow lasts.
- **Basis velocity** (d(fut − spot)/dt) signs the episode: a *futures-led* move spikes basis, which then decays as the print follows; a *basket-led* move compresses basis before futures catch up. Measurable on the frames. Track fair basis (cost of carry) so shocks are read against fair value; the expiry-day basis collapse is a known non-signal.
- **Index-level programs** (a fund buying or selling the index as a basket) move everything at once: synchrony is instantly high, futures lead or coincide, nothing is left to capture. The detector must not call this a domino.
- **BankNifty futures vs Nifty futures** is the cleanest bank-led tell: both liquid, both NFO on the same vendor path (minimal timestamp skew); the five common banks are ~63% of BankNifty but ~29.5% of Nifty, so ΔNifty% ≈ 0.47 × ΔBankNifty% when only the five banks move **[ANALYSIS from the factsheet weights]**.

### Daniel Okafor — "measure what the feed can actually resolve"
- **[ANALYSIS]** Sub-second lead–lag is not measurable on this feed: the exchange stamp is 1 s, and the vendor pipeline (NSE → ICICI livestream → socket.io → us) adds jitter that is probably *instrument-class dependent* (NSE cash and NFO may travel different internal paths). If cash ticks arrive 300 ms before NFO ticks for the same exchange second, every naive estimator "discovers" that stocks lead futures. **The first measurement is the skew between instrument classes, from ticks sharing the same `ltt` second.** Nothing shorter than ~2× that skew may be claimed as a lead.
- At 1 s, stock-vs-futures correlations are depressed by asynchronous trading (the Epps effect) and bid–ask bounce; lag-k cross-correlations are small and noisy. Hasbrouck information shares need a VECM on a common grid and give wide bounds in noisy data; transfer entropy is data-hungry and biased at these sample sizes. **These are nightly diagnostics on the tick recorder (who led *today*, as a regime read), not per-tick triggers.**
- **Live, use event ordering, not correlation.** Each instrument keeps a *crossing clock*: the first time its volatility-normalised move exceeds a threshold in the episode's direction. "Who moved first" is the order of crossing clocks — robust, interpretable, cheap. Resolution ±2 s on frames, ±(vendor skew) live.
- The **continuation test** needs a *matched* null — same futures move over the same window, low synchrony — so any effect is attributable to basket structure, not to Nifty-futures momentum in general. MYTHOS's per-frame direction study (28 features, nothing beat the day base rate — **[FACT]** `MYTHOS_HOW_TRADES_ARE_TAKEN.md` §3) did not test a *conditional* continuation during an impulse, but it is a warning to show ours against that null.
- Power is in *events*, not days: ~10–30 qualifying impulses per day over 30+ sessions gives several hundred events — enough to kill thresholds, not enough to fine-tune many.

### Siddharth Jain — "banks lead on bank days and are dragged on index days"
- **[ANALYSIS]** The five banks move together on RBI/liquidity/bond-yield news, FII flow days (banks are the FII proxy for India), one large bank's result repricing the group, and visible block prints in one name. Then the group follows the leader within ~10–60 s and *keeps going* because the flow is fundamental — the owner's domino. On global risk-on/off days the order reverses: Nifty futures move first and the banks catch up last — futures → stocks, with nothing in it for an option buyer.
- **Group abstraction.** The five banks as one unit, RIL as one, the IT trio (INFY/TCS/HCL) as one. IT often runs the *anti-domino* (IT up on USD/INR or US cues while banks fall): a bank-led down move with IT rising is narrower than it looks and the index impulse will be smaller than the bank impulse implies.
- **Single-name veto:** a 1% move in HDFCBANK alone is ~24 Nifty points and shows as a large weighted impulse, but arbitrage prices a single stock into the index exactly — no continuation beyond that stock's own move. Require breadth *excluding the leader*.
- The **10:00 opening-drive read** (**[FACT]** `MYTHOS_HOW_TRADES_ARE_TAKEN.md`: direction at 10:00 vs the open predicted the close ~71% on 14 tapes, flagged screening-level) is a *prior*, not a gate: with-drive dominoes get more room; against-drive ones are more often fakes. Test on the frames; display; never veto on it.

### Anja Berg — "the delta hop is gone before you see it; the vega hop is real but has a sign"
- **[ANALYSIS, market-making practice]** An auto-quoter prices every strike as f(futures or synthetic, vol surface, inventory). When futures tick, all quotes are re-sent within tens of milliseconds; the owner's feed and order path are hundreds of milliseconds at best. **A retail buyer never hits a stale delta quote in Nifty ATM weeklies.** "MM quote-update latency" as the edge is a false premise; we refuse to write it into the design.
- What *is* slow is the **IV re-mark** (realised vol updates, option demand, surfaces moved by hand or slower models): seconds to minutes. It is **direction-dependent** — Nifty's spot–vol correlation is negative, so a down impulse tends to lift IV (PE tailwind) and an up impulse to deflate it (CE headwind). One mechanism behind "the premium pulled back after I entered though Nifty held"; the frames can measure it.
- **Quote pulling.** In a fast move the asks on the running side thin out and the spread widens 3–10× for a few seconds; the buyer pays up 1–3 pts or misses. The thinning itself is an early tell — MMs pull before the futures level gives way (G3's "asks pulled" signal; we consume it).
- The **premium residual** v_prem − Δ·v_fut over 10–30 s says whether IV is being marked up, flat, or down, and feeds the "IV already up → late" veto. What a buyer can capture: the *continuation* after the trigger plus IV drift on the downside, minus spread, slippage, theta and (for CE) IV deflation. What he cannot: the first delta tick.

### Rohit Menon — "the plumbing is fast; the decision window is the delay"
- **[ANALYSIS] Latency budget** (every term a hypothesis until the probe): exchange event → FEED receive 100–400 ms (vendor); FEED → shared-memory row < 50 µs (G5 target); detector evaluation every 100 ms (numpy over ~70 names: microseconds); trigger → REST placement → ack 200–500 ms; fill → WS order notification. **Trigger-to-fill ≈ 0.5–1 s; event-to-trigger is dominated by the detection window (2–15 s), not code.** A shorter window means more fakes — that trade-off is the design decision.
- Per tick: O(1) write of price/ttq into a 100 ms ring-buffer slot. Every 100–250 ms: all per-instrument and group statistics recomputed vectorised; the lag table once per second. Nothing on the tick path waits for the detector; its outputs carry their own timestamp and are shown with their age.
- The same code must run on recorded frames (1 s, no intra-frame order) and on live ticks (100 ms), degrading honestly: on frames anything inside ±2 s is "co-first".
- Suppress 09:15–09:25 (overnight information reprices everything together — synchrony is trivially 1) and require per-name baselines to have ≥ 10 min of data or a prior-day seed.

---

## 4. The debate

**D1 — Do constituents ever lead Nifty futures, or is that Daniel's artefact?**
Meera: on most liquid days futures are the price-discovery venue; stocks follow via arbitrage within a second or two, so "stocks lead" is mostly the arb's reaction time and invisible at our resolution. Siddharth: on bank-catalyst days the group leads by tens of seconds and the move persists; those are the days the owner remembers. Daniel: both can be true; the question is the *proportion* of ≥20-pt impulses that are basket-led by more than the measurement skew. **Evidence that settles it:** Study F1 (§6) — the fraction of events whose weighted basket crossing clock precedes the futures clock by ≥ 2 s on the frames, then by ≥ 2× skew on the tick recorder. **Decision:** the detector *classifies every episode live* as basket-led / futures-led / index-program / single-name, and only basket-led episodes may carry the "lag" claim. If F1 shows basket-led episodes are rare (< 15% of impulses), the subsystem's value is fake-filtering, not lag capture, and the master design should say so.

**D2 — Is there a market-maker lag an option buyer can exploit?**
The owner's premise and the architect's first reading (§5.6) say the option-premium hop is "the longest and the one an option buyer can exploit." Anja: the *delta* part is milliseconds and unreachable; only the IV re-mark and spread normalisation are slow, and the IV part has a sign that hurts CE buyers. Meera and Rohit agree. **Decision (unanimous):** the design does not claim MM-latency capture. The exploitable "lag" is the *propagation and continuation of the underlying move* (seconds to minutes) plus structure-based fake-filtering; the IV path is a lateness veto and an input to instrument choice (G4). This contradicts §5.6's first reading; flagged for the architect.

**D3 — Window length.**
Rohit: 2–3 s, or we are late by design. Daniel: individual-stock moves over 3 s are bid–ask bounce; membership needs 10–15 s. Meera: the gap closes in 1–3 s, so anything longer is already propagated. **Decision:** multi-horizon — 5 s for direction and speed, 15 s for membership/synchrony, 60 s for extent and lateness — evaluated every 100 ms on the 5 s/15 s pair. The horizons are a sweep in F4, not a choice made in this room.

**D4 — Cash or stock futures as the sensor?**
Meera: stock futures carry directional flow and OI; cash carries the arb legs. Siddharth: institutional block flow prints in cash. **Decision:** both. Index weights apply to *cash* returns (what the index and the arb use); Tier-1 stock futures supply flow (CVD, OI — from G3). The crossing clock uses whichever crosses first and says which.

**D5 — Trigger or filter?**
Siddharth and Rohit: a trigger in its own right. Daniel and Anja: a *service* that upgrades or vetoes G3's force trigger, because the lag edge is unproven and the structure edge is a filter by nature. **Decision:** build it as both and let validation decide which is wired to a real order. To honour the owner's dislike of voting, the trigger is **one composite condition with one on-screen reason string**, not a tally of evidences.

**Not disputed:** the print is never a trigger input; the 09:15–09:25 window is excluded; the subsystem ships shadow-only behind a pre-registered bar (the ledger discipline in `FORWARD_TEST_LEDGER.md`).

---

## 5. Consensus proposal

### 5.1 What it is
The **Domino Detector** is an ANALYTICS worker that, ten times a second, answers four questions about the Nifty complex: *Is a broad move forming? Who started it? Has Nifty futures (and therefore the premium) finished pricing it? Is it too late?* It publishes a `DominoState` every 100 ms, emits `DOMINO_TRIGGER`, `DOMINO_EXHAUSTING` and `DOMINO_INVALID` events, and maintains a lead–lag table for the screen and the nightly report. It never places orders; G6 does.

### 5.2 The chain, hop by hop (charter Q1)

| Hop | Usual direction | Typical lag | Shortens / lengthens | Tag |
|---|---|---|---|---|
| Originating name(s) → correlated names / bank group | leader → group on catalyst days; coincident on index days | 5–60 s | sector flow and bank-group stat-arb shorten it; thin tape lengthens | HYPOTHESIS (F1 measures) |
| Bank group → BankNifty futures | banks → BN futures (BN is ~63% those five) | 1–5 s | arb capacity; expiry afternoons | HYPOTHESIS |
| Constituents ↔ Nifty futures | **futures → constituents on most days** (index flow, arb); constituents → futures on catalyst days | 1–3 s liquid hours; 3–10 s thin periods | arb thresholds, risk limits, volatility, lunch lull, expiry | ANALYSIS (standard index-futures finding) + HYPOTHESIS for the split |
| Futures → cash index print | futures → print | ≤ 1–2 s, mostly stale constituents + dissemination | number of untraded constituents; vendor cadence | ANALYSIS |
| Futures → option quotes (delta) | futures → quotes | **~10–100 ms** | never slow enough for us | ANALYSIS (Anja) |
| Option IV re-mark (vega) | after the move | 10 s – several min; sign negative to spot | size and speed of move, time to expiry, demand | ANALYSIS + HYPOTHESIS (F3 measures the path) |

Caveat the owner should hold onto: "cash heavyweights lead index futures" is **not** the default state of the market; it is a regime that the detector must identify in real time.

### 5.3 Inputs, by Breeze field [FACT for field names; subscriptions per §5.2 of the brief]

| Instrument set | Feed | Fields used |
|---|---|---|
| Nifty 50 constituents (cash, ~50) | NSE exchange quotes by token (`symbol = "4.1!<token>"`) | `last, ltt, ttq, ltq, bPrice, sPrice, bQty, sQty` + FEED receive stamp |
| Tier-1 stock futures (10) | NFO `product_type=futures` | `last, ltq, ttq, bPrice, sPrice, OI` (CVD and OI quadrant come from G3) |
| Nifty futures (near month) | NFO futures + 5-level depth | `last, ltq, ttq, bPrice, sPrice, bQty, sQty, OI`, `BestBuyRate/Qty-1..5`, `BestSellRate/Qty-1..5` |
| BankNifty futures (near month) | NFO futures (code to verify — `CNXBAN` works for spot) | `last, ltq, ttq, bPrice, sPrice` |
| Nifty spot, BankNifty spot | NSE cash index (`NIFTY`, `CNXBAN`) | `last` (lateness only; **never a trigger input**) |
| Hero options ATM±2 CE/PE (10) | NFO options + depth | `last, bPrice, sPrice, bQty, sQty, ttq, OI`; IV/Greeks from G4 |
| Weights | NSE constituent CSVs (owner, OQ 7) | free-float weight w_i, group membership |
| Clock | FEED monotonic receive stamp (ns), `ltt` | skew calibration |

FinNifty is excluded until a working code exists (**[FACT]** none found as of 16 Oct).

### 5.4 Per-instrument state (every 100 ms, vectorised)
For instrument i with price p_i, cumulative volume ttq_i, weight w_i (%), Nifty level N:
- Move in Nifty points over horizon τ: **m_i(τ) = (w_i/100) · (p_i(t) − p_i(t−τ))/p_i(t−τ) · N**. (Stocks read in Nifty's units, as §5.2 of the brief proposed.)
- Own scale: **σ_i(τ)** = EWMA of |m_i(τ)| sampled every τ, half-life ~20 min, seeded from the prior session's closing value; valid after ≥ 10 min.
- Normalised move **z_i(τ) = m_i(τ)/σ_i(τ)**.
- Activity **a_i(τ) = Δttq_i(τ) / EWMA(Δttq_i(τ))** (volume per unit time vs the name's own baseline — the owner's feature (b), with no stale data by construction).
- **Crossing clock t_i^x**: first time in the current episode that |z_i(15 s)| ≥ z* with sign s_i; cleared when |z_i(15 s)| < 0.5 for 10 s. Starting z* = 2.0 (range 1.5–2.5).
- Freshness: every statistic carries the age of its newest input; older than its horizon → invalid (grey on screen).

### 5.5 Group statistics
- Direction **d = sign(Σ_i w_i · m_i(5 s))**.
- **Basket-implied Nifty move M_b(τ) = Σ_i m_i(τ) · (100 / Σ_tracked w_i)** (rescaled for untracked or stale names; coverage shown).
- Futures move M_f(τ), print move M_c(τ), BankNifty-implied move M_bn(τ) = 0.47 · ΔBN%(τ) · N (bank-only mapping; the 1.15 beta is used when the move is broad).
- **Gap G(τ) = M_b(τ) − M_f(τ)** (Meera's number). G > 0 in direction d: futures behind the basket. G < 0: futures ahead — the move is already in the premiums.
- **Synchrony S(τ) = Σ{w_i : sign(m_i) = d, |z_i(τ)| ≥ 1, a_i ≥ 1.2} / Σ w_i** — the weighted fraction moving together *with volume above their own baseline* (brief §5.3).
- **Breadth B(τ)** = unweighted fraction of names with sign(m_i) = d and |z_i(τ)| ≥ 1.
- **Ex-leader synchrony S′** = S recomputed without the first-mover (Siddharth's veto).
- **Concentration c** = share of M_b contributed by the single largest contributor.
- **First-mover** = earliest crossing clock among {names, BN futures, Nifty futures}; co-first if within the resolution band (±2 s on frames; ±2× measured skew live). Episode type: *bank-led* (a bank or BN futures first, group follows), *broad basket-led* (several names before futures), *futures-led* (Nifty futures first), *index-program* (everything within the band), *single-name* (one name first, S′ low).
- **Lead table** (every 1 s, slow path): EWMA cross-covariance between 1 s basket-impulse returns and 1 s futures returns at lags k ∈ {−5…+5}; the argmax lag is shown as "basket leads futures by k s" only when the peak exceeds its neighbours by a margin (starting 0.05); otherwise "unresolved". Nightly, Daniel's HRY lead–lag estimator and Hasbrouck information shares run on the tick recorder per episode type as a check on the live table.

### 5.6 Projected extent and lateness (charter Q4)
- **Projected extent E** = k_proj · M_b(15 s) at the moment of evaluation, with k_proj the median ratio (eventual 3-min extent ÷ 15 s basket impulse) learned on the frames per episode type; starting guess k_proj = 2.0 (range 1.5–3.0) **[HYPOTHESIS; wide error bars — F4 reports the interquartile range]**.
- **Price lateness L_p = M_f(since episode start) / E.**
- **Recruitment lateness L_r**: breadth has not risen for ≥ 20 s (range 15–40 s) — the domino has finished recruiting.
- **IV lateness L_iv**: ATM IV (from G4) up ≥ 2% relative over 60 s (range 1.5–4%; e.g. 12.0 → 12.24).
- **Premium lateness L_v**: the hero contract's 5 s premium velocity has fallen below 50% of its 30 s maximum after having exceeded 0.5 pt/s (range 0.4–0.6).
- **Print caught up**: |M_c(10 s)| ≥ 0.8 · |M_f(10 s)| with M_f already ≥ 0.5 E.
**"Too late"** = L_p ≥ 0.6 (range 0.5–0.75) **or** any two of {L_r, L_iv, L_v, print caught up}. The reason is shown on screen in words.

### 5.7 Phase state machine (per episode, direction d)
`QUIET → STIRRING → FALLING → RECRUITED → EXHAUSTING → QUIET`, with `INVALID` reachable from any phase.
- QUIET → STIRRING: |z_b(15 s)| ≥ 1.5 where z_b is the basket impulse normalised by its own σ; episode start price = futures price now; crossing clocks armed.
- STIRRING → FALLING: S(15 s) ≥ 0.5 (range 0.4–0.6) and B(15 s) ≥ 0.5 and |z_b| ≥ 2 and sign(M_f(5 s)) = d with |M_f(5 s)| ≥ 3 pts (futures has begun to respond — we never buy against futures) and S′ ≥ 0.35 and c < 0.6.
- FALLING → RECRUITED: B plateau ≥ 20 s or L_p ≥ 0.6.
- RECRUITED → EXHAUSTING: S(15 s) falls below 0.3, or futures CVD (G3) diverges from price for ≥ 15 s, or IV spikes then stalls (G4), or the opposite-side force firms (G3).
- → INVALID: single-name (c ≥ 0.6 and S′ < 0.35); index-program (all crossing clocks inside the band and G ≤ 0); futures reverses ≥ 40% of its episode move; G turns negative by > 5 pts (stocks retreating while futures hangs); premium already repriced (L_iv or L_v) before any trigger.
- Any → QUIET: |z_b(15 s)| < 0.5 for 30 s.
Only the FALLING phase can emit a trigger.

### 5.8 Trigger (charter Q3) — pseudo-code
```
every 100 ms, after state update:
  if phase != FALLING: emit no trigger; publish state with reason
  elif too_late(): reason = "LATE: " + which tests; no trigger
  elif G(15s)*d <= 0 and episode_type == "futures-led": reason = "ALREADY IN FUTURES"; no trigger
  elif g3.force_at_nearest_level(d) == HOLD_STRONG: reason = "WALL HOLDING"; no trigger
  elif clock in suppression windows (09:15-09:25, last 15 min, expiry-day rules): no trigger
  else:
     urgency = VACUUM if g3.asks_pulled(hero, d) else NORMAL
     emit DOMINO_TRIGGER(d, E, L_p, S, B, first_mover, episode_type, urgency, reason_string)
```
One trigger per episode; a second requires a new episode. The reason string is the owner's "why this trade", e.g. *"bank-led domino: HDFCBANK first (−0.22%/6 s, 3.1× vol), 4 of 5 banks + RIL/LT joined; synchrony 0.58, breadth 0.55; futures −7 of projected −19 (37%); IV +0.8%/60 s; support 22,990 BREAK-IMMINENT."*

### 5.9 A day in its life
09:15 — baselines seeded from yesterday; QUIET; suppression on; the domino strip colours in as names tick. 09:25 — armed; live baselines take over by 09:35. 10:00 — the drive side is latched and shown as a prior badge. Most of the day: QUIET/STIRRING episodes that never reach FALLING (narrow, or futures-led), each with its reason on screen. An episode like §5.11 fires once; after the hand-off the detector keeps publishing S, B, G and lateness so G6's exit logic can read EXHAUSTING. 12:30–13:30: lags lengthen, impulses shrink, baselines adapt. 14:30 onward: closing-basket episodes are typically futures-led or co-first → "ALREADY IN FUTURES". 15:15 — suppression. After close: the nightly who-led report and the lead-table check.

### 5.10 The option-premium hop and what entering inside it is worth (charter Q2)
**[ANALYSIS]** Worked numbers for a true impulse of 30 Nifty points in ~90 s, Nifty ≈ 23,000, weekly ATM IV ≈ 12%, 3 days to expiry:
- ATM gamma ≈ φ(d1)/(S·σ·√T) ≈ 0.4/(23,000 × 0.12 × 0.091) ≈ 0.0016 per point; the gamma term over 30 pts is ≈ ½ × 0.0016 × 900 ≈ 0.7 pt. **Delta dominates:** ATM premium ≈ +15 pts over the full impulse; a delta≈0.9 ITM ≈ +27 pts.
- Domino trigger at L_p ≈ 0.35 (futures has moved ~10 of 30): remaining ≈ 20 pts → ATM +10 gross; ITM +18 gross.
- Costs: spread at a widened book 1–3 pts round trip (MYTHOS measured ~2 pts/trade honest-fill drag **[FACT]**); trigger-to-fill slippage ~0.5–1 s × 0.2–0.5 pt/s ≈ 0.1–0.5 Nifty pts; theta over 3 min ≈ 1–1.5 pts (afternoon expiry week, less in the morning); IV: **PE on a down impulse +1 to +3 pts, CE on an up impulse −1 to −2 pts** (Anja's sign).
- **Net on a true impulse: ATM ≈ +5 to +8 (CE lower, PE higher); ITM ≈ +12 to +15.** On a fake that stalls at ~40% of E: ATM ≈ −2 to −5; ITM ≈ −4 to −7 (wider ITM spreads).
- **Confirmation-style entry** (MYTHOS: print −12 + pivot held 2 s + CVD flip ≈ L_p 0.6–0.8): remaining 6–12 pts → ATM +3–6 gross, ≈ +1 to +3 net, with full exposure to the exhaustion pullback. This reproduces MYTHOS's own median peak of +3.1 **[FACT, brief §3.3]** — the strongest evidence we have that its losses were a *timing* problem, not a direction problem.
- Error bars are wide: impulse size is heavy-tailed, k_proj is a guess until F4, and the spread during VACUUM moments can be 5+ pts. Break-even at +6/−4 (ATM) is a 40% true-impulse rate; the synchrony filter must lift that rate to ≥ 55% to be worth running — that number is the pre-registered bar in §6.7.

### 5.11 Worked example (charter Q4), 1 s resolution, hypothetical values
- 10:42:03 HDFCBANK −0.22% in 6 s on 3.1× baseline volume (z15 = 2.4) → crossing clock set; ICICIBANK z 1.8 at :05; BankNifty futures −0.18% at :07; AXIS/SBIN/KOTAK cross by :10. Phase STIRRING at :06 (z_b 1.6); episode start futures 23,012.
- :12 M_b(15 s) = −9.5 (banks −8.2); M_f(15 s) = −4; **G = −5.5 in direction d** (futures behind). S = 0.31 (banks only) → not FALLING.
- :15 RIL, LT, M&M, Bharti join (z ≥ 1, a ≥ 1.2): S = 0.58, B = 0.55 (28 of 50), S′ = 0.47, c = 0.41. M_f(5 s) = −3.2, futures −7 since start, velocity −0.4 pt/s. E = 2.0 × (−9.5) = −19; **L_p = 0.37**. ATM 23,000 PE: bid/ask 118.0/118.4 at 10:41:55 → 121.2/122.0 now (spread 0.4 → 0.8; delta 0.5 × 7 = +3.5 plus a little IV). IV60 = +0.8% (12.1 → 12.2). Premium velocity +0.9 pt/s and rising. G3: support 22,990 BREAK-IMMINENT.
- **10:42:16 DOMINO_TRIGGER PE, urgency NORMAL** → G6 limit at ask + 0.5 = 122.5 → filled 122.3 at :17.2.
- 10:43:40 futures −24 since start (E under-projected); PE bid 135.5 at :45 (**+13.2**: delta ≈ +9.5, IV +0.4 vol pt ≈ +2.5, gamma ≈ +0.7, a little spread give-back).
- 10:44:12 breadth flat 22 s, S = 0.29, IV stalled → **EXHAUSTING** published; G6 owns the exit.
- The same episode evaluated at 10:43:30 would read L_p = 1.16, IV60 +3.5%, premium velocity at 40% of its max → **"LATE"**, no trigger. A confirmation-style entry would have come ≈ 10:42:50 at ask ≈ 127.5 with 6–8 pts to the peak — MYTHOS's trade.

### 5.12 On screen
A **domino strip**: the 50 names as tiles ordered by weight, coloured by z(15 s), volume-activity as a bar, the first-mover ringed with its time-since-cross; group boxes (banks, RIL, IT, autos, rest). A **gauge row**: S, B, S′, c. A **gap bar**: M_b vs M_f vs M_c in Nifty points with G labelled. A **lateness bar**: "37% of projected −19" with the four lateness flags. The **lead table** (basket/BN futures/first-mover vs Nifty futures, lag in seconds, confidence). The current phase and the one-line reason (fires audibly only on FALLING, TRIGGER, EXHAUSTING, INVALID — the owner's "most significant events only"). All values show their age.

### 5.13 Thresholds — all [HYPOTHESIS] with starting value (sweep range)
z* 2.0 (1.5–2.5) · recruit |z| ≥ 1 (0.8–1.5) · activity a ≥ 1.2 (1.0–1.5) · S_FALLING 0.5 (0.4–0.6) · B_FALLING 0.5 (0.4–0.6) · S′ 0.35 (0.25–0.45) · c_max 0.6 (0.5–0.7) · futures minimum 3 pts/5 s (2–5) · k_proj 2.0 (1.5–3.0) · L_p late 0.6 (0.5–0.75) · IV60 2% (1.5–4%) · breadth plateau 20 s (15–40) · velocity ratio 0.5 (0.4–0.6) · horizons 5/15/60 s (3–8 / 10–20 / 45–90). Calibrated on recorded outcomes per §6, never hand-set in production.

---

## 6. Validation plan

### 6.1 What the frames can and cannot test [FACT from `_build_frame`]
Each ~1–2 s frame holds: `spot`, `fut`, `fut_oi`, `fut_bq/fut_aq`, `fut_vol` (interval volume), `vix`, `opts` for ATM±8 both rights as `[ltp, oi, ttq, bid, ask, bqty, aqty]`, wide `chain` OI, `hw` (14 heavyweight cash LTPs), `hwf` = `[bqty, aqty, age-of-last-tick to 0.1 s]`, `hw_chains`, and since 28 Jun an `instruments` block with each stock's `vol` (= ttq). Sister indices are 20 s REST values.

| Question | Frames (1–2 s) | Needs the tick recorder |
|---|---|---|
| Synchrony, breadth, concentration during impulses | yes (14 names, ~62% of weight — a coverage caveat) | full 50-name basket |
| Basket-implied vs futures gap G, basis velocity | yes | finer timing |
| Who crossed first, ±2 s | yes, using `hwf` age to sharpen last-tick time | sub-second ordering, vendor skew |
| Premium capture net of ask/bid at trigger vs confirmation | yes (`opts` bid/ask at 1 s) | spread dynamics inside the second |
| IV path after up vs down impulses | yes (G4 solver on mid) | — |
| BankNifty futures lead | **no** (20 s REST, no BN futures) | yes |
| Stock-futures flow/OI lead | **no** (cash only) | yes |
| Option-quote response time to a futures tick | **no** | yes |
| Cash L1 prices of stocks | **no** (only L1 quantities recorded) | yes |
Sessions before ~23 Jun have HDFCBANK dead (**[FACT]** `feed.py` note) and are excluded from basket statistics.

### 6.2 Study F1 — event catalogue and who led
Events: every Nifty-futures excursion ≥ 20 pts within 3 min and ≥ 30 pts within 5 min, found by a pivot-to-extreme scan, de-overlapped. For each: onset t0 (first second futures is ≥ 5 pts from the pivot), crossing clocks for the 14 names, M_b, futures, print; episode type; the lead = t^x(futures) − median t^x(names crossed). Output: the distribution of leads and the share of basket-led events by time of day, VIX regime and expiry proximity. Pre-registered reading: if basket-led-by-≥-2 s events are < 15% of all events, D1 is settled against the lag claim.

### 6.3 Study F2 — does structure predict continuation? (the fake filter)
At each event's would-be trigger moment (first time S ≥ 0.5 and futures ≥ 3 pts with d), record S, B, S′, c, G, L_p; then the outcome: eventual extent over 3 min, time to peak, maximum adverse excursion, pullback depth. Compare against Daniel's **matched null**: moments with the same futures move over the same window but S < 0.3. The claim to test: top-quartile synchrony events continue further (median extent ratio ≥ 1.5× the null) and pull back less. Also condition on with-drive vs against-drive (the 10:00 prior).

### 6.4 Study F3 — premium capture, honest fills
For each event, three entries on the ATM and ATM∓100 (delta ≈ 0.7) contracts of side d: (a) at the domino trigger, (b) at a MYTHOS-style confirmation (print moved 12 pts + held 2 s), (c) oracle at the pivot. Buy at `ask`, sell at `bid` at fixed horizons 60/180/300 s and at a 50%-of-peak trail; subtract 0.7 pt charges. Report median, IQR, 10th/90th, by episode type, CE vs PE, time of day, expiry proximity; and the IV path (G4 solver on mid) after up vs down impulses to test Anja's sign.

### 6.5 Study F4 — sweep and split
Sweep every threshold in §5.13 over its range on the first two-thirds of sessions in time order; evaluate the chosen set once on the last third; report the drop-best-day result and the trigger rate per day. Days, not events, define the split. Nothing is re-tuned after the held-out run.

### 6.6 Live probe P1 (first sessions of the new FEED, shadow only)
Record raw messages with nanosecond receive stamps for Nifty spot/futures (+depth), BankNifty spot/futures, the ten hero options (+depth), Tier-1 cash and futures. Measure: (1) per-instrument tick cadence; (2) **vendor skew between NSE cash and NFO** using ticks sharing an `ltt` second — the resolution floor for every lead claim; (3) option-quote response time after a ≥ 2 pt futures mid change (expectation: within one or two vendor ticks; if ≥ 1 s it is the pipeline, not the MM); (4) spread and ask-quantity dynamics in the hero ladder 10 s either side of impulses; (5) IV path per tick; (6) the Breeze NIFTY spot print vs our own basket-implied index — if ours leads the vendor's print by a measurable fraction of a second, that is a free, mechanical lag removed from our own pipeline **[HYPOTHESIS]**.

### 6.7 Pre-registered bar before this subsystem may influence a real order
Registered now, before any study runs; a fail retires the trigger role (the veto/annotation role may continue):
1. F1: basket-led events ≥ 15% of impulses, or the subsystem is re-scoped as a filter.
2. F3 on the held-out third: domino-trigger net at the 180 s horizon positive on ≥ 55% of events, mean ≥ +2 pts above the confirmation entry, survives drop-best-day, with ≤ 8 triggers/day.
3. P1: measured cash/NFO skew ≤ 300 ms; otherwise first-mover claims are disabled and only synchrony/breadth/gap may feed a trigger.
4. ≥ 15 live shadow sessions with honest-fill shadow P&L positive and surviving drop-best-day. As the ledger's stats review said of its own 15-session bar **[FACT]**, this is a kill test (~25–40% power), not a confirmation; confirmation needs ~45–60 sessions, and the owner is told so.

---

## 7. Risks and failure modes

- **Late by design.** Synchrony needs 5–15 s to form, and every G3/G4 veto removes early entries. The detector's own lateness is visible as L_p at trigger: if its median on the frames exceeds ~0.5, we have rebuilt MYTHOS with better vocabulary. F4 sweeps the horizons; the trigger uses the 5 s/15 s pair, never 60 s.
- **Wrong with confidence — the index program.** A basket program saturates S and B instantly, futures lead or coincide, premiums are already repriced. The G ≤ 0 and co-first checks catch most; some slip through at the open and close — hence the suppression windows and the "ALREADY IN FUTURES" reason.
- **Fake leads from vendor skew.** If cash ticks arrive before NFO ticks, stocks "always lead". P1 measures it; the bar disables first-mover claims above 300 ms skew.
- **Single-name news split across two correlated names** passes the concentration check (HDFCBANK + ICICIBANK on a sector downgrade is legitimate; RELIANCE + a subsidiary is not). S′ helps; group abstraction is the proper fix and needs the full constituent list.
- **Overfitting on 30 sessions of one low-VIX regime** (**[FACT]** ledger caveat). The time-ordered split and the shadow sessions are the only protection; budget for re-calibration.
- **IV sign for CE buyers.** If F3 confirms it, ATM CEs on up-dominoes under-deliver; G4 should steer them to higher delta.
- **Expiry day.** Extreme gamma, meaningless IV, wide spreads, basis collapse — every lateness test misbehaves. Separate thresholds or refuse; the owner's expiry caution stands.
- **Feed stalls** drop a stale name out of S and B (age-gated), making the detector quieter, not louder — the safe direction, shown as coverage %.
- **Shadow-to-live drift.** The shadow ledger runs the same code at the same cadence as live (the ignition engine's 4 s-vs-1 Hz lesson, **[FACT]** ledger).

---

## 8. Interfaces

**From G5 (platform):** per-instrument shared-memory row with `last, bid, ask, bqty, aqty, ttq, ltq, OI, ltt, recv_ns`; a 100 ms sampler or ZMQ SUB with conflation; the constituent weight/group table from the NSE CSVs; the raw-message recorder with `recv_ns`; a replay harness that runs this worker unchanged on frames and on ticks; the measured feed-to-worker latency.
**From G3 (force & flow):** tick-rule CVD on Nifty futures and Tier-1 stock futures; the force verdict at the nearest Nifty level in direction d; `asks_pulled` on the hero ladder (our urgency class); stock-futures OI quadrant for the "positioned" prior.
**From G4 (Greeks):** IV per hero contract at ≥ 1 Hz with timestamp; delta/gamma/theta; a "can pay" check given E and a hold horizon; instrument recommendation per episode type (PE/CE, ATM vs delta-0.7–0.9) — including the IV-sign asymmetry if F3 confirms it.
**From G2 (pressure zones):** the nearest wall/zone in direction d and its distance; whether E crosses it (a wall inside the projected path shortens the expected capture and should be displayed, not vetoed).
**From G6 (execution):** measured trigger→ack→fill latency fed back into our budget; the limit-pricing policy by urgency (NORMAL = ask + small buffer; VACUUM = wider); confirmation that one trigger per episode is enforced at their layer too.
**We give everyone:** `DominoState` at 10 Hz (phase, d, S, B, S′, c, M_b, M_f, M_c, G, E, L_p, lateness flags, first-mover, episode type, coverage, age); `DOMINO_TRIGGER`, `DOMINO_EXHAUSTING`, `DOMINO_INVALID` events with the reason string; the lead table at 1 Hz; the nightly who-led report (per episode type, with HRY/IS checks) for G7.

---

## 9. Open questions for the owner
1. Which domino have you actually watched? Name the usual first-mover(s) and the timescale you have in mind (seconds or minutes) — it decides whether F1 is looking for the right thing.
2. For domino trades, do you want the convex ATM (bigger % move, exposed to IV sign and theta) or the delta-0.7–0.9 ITM that tracks the move (bigger capture in points, wider spread, more capital per lot)? The resume brain found ITM beat ATM on its own entries **[FACT]**; we would optimise F3 for your preference.
3. May the subsystem run shadow-only for ≥ 15 live sessions behind the bar in §6.7 before it can touch a real order, and may the recorded MYTHOS frames be used for F1–F4 (assumed yes)?
4. Is a trigger budget of ≤ 8/day acceptable, and is suppression at 09:15–09:25 and the last 15 minutes acceptable to you (you asked for no invented time-of-day cutoffs; these two are measurement limits, not opinions, and we will show the evidence)?
5. The full constituent CSVs (brief OQ 7) and whether BankNifty futures subscribe under `CNXBAN` on NFO on your account.

---

## 10. One-paragraph summary for the master design
The Domino Detector is a 10 Hz analytics worker that watches all Nifty constituents (cash, weights applied), the Tier-1 stock futures, BankNifty futures and Nifty futures, converts every move into Nifty points, and classifies each episode as bank-led, broad basket-led, futures-led, index-program or single-name using crossing-clock ordering, weighted synchrony with volume above each name's own baseline, breadth, ex-leader breadth and the gap between the basket-implied index and Nifty futures. It triggers once per episode, only in the FALLING phase — broad, synchronous, futures responding but less than ~60% of the projected extent, IV not yet marked up, premium velocity not yet peaked — and publishes a lateness read and an EXHAUSTING flag for execution. The group's honest finding against the brief's first reading: there is no market-maker delta lag a retail buyer can capture; the exploitable lag is the propagation and continuation of the underlying move plus structure-based fake-filtering, with the IV re-mark acting as a tailwind for puts and a headwind for calls. On a true 20–40 pt impulse the detector should capture roughly +5 to +8 ATM points net (+12 to +15 on a delta-0.9 ITM), versus the +1 to +3 a confirmation entry gets — which is exactly MYTHOS's recorded median peak. Everything is a hypothesis until the four frame studies, the live skew probe and 15 shadow sessions clear the pre-registered bar in §6.7; if basket-led episodes prove rare, the subsystem is re-scoped as a veto and annotation service for G3's trigger rather than a trigger of its own.
