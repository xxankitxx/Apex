# G3 — Order-book Force & Flow

*Working group G3 of the ApexOptions design team. Session held Saturday 17 October 2026. Chair: G3 lead. Inputs: the Context Pack (§1.3 a–d, §2.1, §3, §5.5), `mythos/feed.py`, `run7/hawk_feed.py`, `mythos/trader.py`, `mythos/app.py` + `config.py` (the old BOOK ignition), the last MYTHOS log, the Breeze SDK README and source on GitHub, and public statements on NSE snapshot dissemination. Tags as in the brief: **[FACT] [OWNER] [ANALYSIS] [HYPOTHESIS]**.*

---

## 1. Members and their lenses

- **Yusuf Al-Rashid** — market-making / HFT engineer. Reads a book as quoter behaviour: what auto-quoters do when the futures tick, when they widen, skew and step back, what a spoof looks like with only five levels visible.
- **Lakshmi Iyer** — professional tape reader. Reads a level as a fight: absorption, exhaustion, icebergs, "sellers running away" versus "sellers being eaten", the difference between a grind-through and a vacuum.
- **Henrik Lund** — statistician. Change-point detection, multi-horizon EWMAs carrying age, calibration from labelled hold/break events, look-ahead discipline, and the early-vs-sure trade-off as a measured curve, not an opinion.
- **Nikhil Bhatt** — NSE data specialist. Exact semantics of the NSE broadcast fields as Breeze relays them, what a consolidated snapshot can and cannot tell you, known artefacts.

---

## 2. What we were asked

**[OWNER]** Three features and a scope:

- *"Uses the number of buyers and the number of sellers (and keep a track of how they are increasing and decreasing) to understand the price movement of that option… the sellers standing are constantly falling slowly or fast in numbers and the price is running for that CE/PE."*
- *"Volumes per unit time (or per bar or whatever) will also be needed. Do not use stale data over a period of time."*
- *"A force detector which detects how the price is not falling below a level or how is it not going above a particular level because of an opposite force. I need the system to detect that this time this supporting force is not enough and will not be able to hold a level or will break (or vice versa…)."*
- Scope: *"all the stocks and indices we are tracking but specifically for NIFTY… at least 2 ITMs and 2 OTMs of both CE and PE of Nifty."*

**[ANALYSIS] Our reading.** The owner is describing a broker terminal's depth window: five rows of *orders / quantity / price* each side plus the two totals. "Sellers standing" are resting asks; "falling in number" is order count and quantity shrinking; "the price is running" is the premium moving while that happens. The force detector is the same picture pointed at a *level*: the resting opposing quantity, whether it refills when hit, whether it leaves before being hit. He wants the *this time it will not hold* call made early — MYTHOS waited for every break to be proven (§3.4). So: three measurement instruments and one judgement engine, all on consolidated snapshot data, each carrying its own freshness, calibrated from recorded outcomes rather than hand-set.

---

## 3. Ideas by member

### Nikhil — what the fields really are

**[FACT, Breeze SDK source `parse_data`]** The raw socket.io payload for an NFO quote is a flat 23-element list: `[symbol, open, last, high, low, change, bPrice, bQty, sPrice, sQty, ltq, avgPrice, OI, CHNGOI, ttq, totalBuyQt, totalSellQ, ttv, trend, lowerCktLm, upperCktLm, ltt, close]`. `ltt` arrives as a *numeric epoch* (`data[21]`) which the SDK converts to a `'%c'` string with `datetime.fromtimestamp(...).strftime` on every tick. Depth is a separate message: `[symbol, time_epoch, [[bRate, bQty, bOrders, bFlag, sRate, sQty, sOrders, sFlag] × 5]]`. Quotes are keyed `4.1!<token>`, depth `4.2!<token>`; they are **two different messages**, never atomic with each other.

**[FACT, README samples, Feb 2025]** NFO depth carries `BuyNoOfOrders-n`/`SellNoOfOrders-n` (sample: 8,475 units in 17 orders at L1). `ttv` is a *string* (`'38.31C'`, crores) on NSE — `float()` on it raises. `CHNGOI` was `None` on the NFO sample. Index spot ticks have `None` for every book/volume field. In two consecutive option ticks `ttq` advanced 2,025 units (27 lots) while `ltq` read 75 (one lot) both times — `ltq` is the last trade only. The tick with the larger `ttq` carried the *earlier* `ltt` (12:12:54 vs 12:12:55): out-of-order delivery or a paste artefact — the probe must check.

**[ANALYSIS]** `totalBuyQt`/`totalSellQ` are whole-book sums (RELIANCE sample: 512,163 total buy vs 92 at L1) — far orders included, trivially inflatable. `avgPrice` = `ttv/ttq` = day VWAP (verified on the sample). `OI` on NSE arrives via the trade ticker, not the depth message, so the value in a quote tick is whatever the broker's handler last saw; whether it moves only with trades is a probe item. NSE's protocol documents were not reachable from this container, so NSE-side field descriptions are tagged ANALYSIS where the README samples don't settle them.

**[FACT, Zerodha support article]** Broker feeds "combine many trades into snapshots called 'ticks' taken one to four times per second", minimum gap 250 ms; "large orders can move prices for microseconds without appearing in exchange snapshots". **[ANALYSIS]** Breeze rides the same NSE broadcast; its exact cadence per instrument is unmeasured. The old code's "Nifty futures peak ~30–50 ticks/s" (`feed.py:53`) was a buffer-sizing guess; HAWK's engine was tuned for the spot index at ~3.6 ticks/s (`hawk_engine.py:626`), also unmeasured for options.

Nikhil's conclusions: consume the **raw list** and keep `ltt` numeric — never `strftime` on the hot path; `ttq` differences are the only honest volume; depth and trades are joined by *receive* time. He rejected his own idea of interval VWAP from Δ(`avgPrice`×`ttq`): at 2 dp and `ttq` ≈ 70 M the rounding error (±350 k rupees) swamps a 1 s bin.

### Yusuf — what the book is actually showing you

**[ANALYSIS]** Five levels at a 0.05 tick is a quarter of a point. On a ₹100 ATM option the visible asks are 100.05–100.25; on Nifty futures at 23,065 the dense book spans ~0.25 points. The depth is a **microscope on the touch, not a map of walls**: "supply resting at 23,100" is invisible until the touch is within a quarter-point of it. So the force detector measures what happens *during* a test at the touch; the wall prior comes from OI, totals and volume-at-price history.

**Auto-quoter re-pricing.** When futures tick up, every CE quoter re-prices within ~50–300 ms: the ask at 100.05 vanishes and reappears at 100.30. Per-level differencing calls this "pulled at 100.05, added at 100.30" — a false pull. Re-pricing conserves total visible quantity and order count across the window (± consumption); withdrawal shrinks both. **π must be computed on window totals, not per price.**

**MMs don't predict; they react and skew.** He disagrees with the brief's §5.5 line and with G1's "MMs pull before the futures level gives way". What can lead is *non-MM* flow: sweeps (`Δttq` large, `last` jumping ≥ 2 levels in one snapshot) across several strikes in the same second, after which quoters widen, cut size and skew. Widening plus two-sided shrink is a **volatility** signature; a directional read needs *asymmetry* (ask side shrinks more than bid side) plus aggressor imbalance.

**Spoofing with five visible levels.** A deep spoof shows only as an unexplained jump in `totalSellQ`; one inside the window sits within 0.25 pt of the touch, at risk of being hit. Signature: one order (`ΔN = +1`) with a large `ΔS` at L2–L5, gone without trades as the touch comes within 1–2 levels. NSE's per-order freeze quantity caps a single order, so `ΔS/ΔN` above the freeze is an artefact.

**Queue position is unobservable** and irrelevant for a taker; what G6 needs is the visible ask ladder at the instant of a VACUUM verdict and how far the fill walks it.

### Lakshmi — what a failing level looks like

**[ANALYSIS]** Three different things make "sellers fall": they are **eaten** (volume prints at the ask, level shrinks, price grinds), they **leave** (level shrinks on little volume, price gaps — the vacuum), or they are **re-priced** (quoter shift, nothing changed). Only the first two are information, and they trade differently: a grind-through is slow, costly and tends to continue; a vacuum is fast, thin, prone to snap back — the place to be *before* it, not after.

**Absorption** = large volume consumed at the level with no price progress; while replenishment keeps pace, the level is strong. **Exhaustion** = the attack's volume drying up as price stalls. **Iceberg** = a level that keeps refilling after many hits, order count flat or one, cumulative executed far above the largest displayed size.

**Attack-attempt profiling** is the owner's "this time". A level is rarely broken on the first attack. Profile each attack *k*: consumed `C_k`, net refill `R_k`, `ρ_k = R_k/C_k`, peak intensity `A_k`. The weakening pattern is `ρ_1 > ρ_2 > ρ_3` with `A_k` rising — defenders refill less each time while attackers come harder — visible one attack *before* the break.

**Mirror reads.** A CE "runs" only if the PE is dying: CE asks thin/pulled **and** PE bids thin/pulled. If CE asks lift and PE asks also lift, that is IV, not direction. The cross-right mirror is the cheapest fake filter we have.

### Henrik — making it measurable and early

**[ANALYSIS]** Every stat is a multi-horizon EWMA with irregular-Δt update `α = 1 − exp(−Δt·ln2/h)`, half-lives 2 / 10 / 60 s, each carrying `age = now − last_update`; older than its own half-life is invalid and shown grey. Ratios `ρ`, `π` are unstable at small denominators: floors on `C` and `S₀` (in lots) before a ratio is quoted, else "n/a".

**Rate classes** should be relative to the instrument's own baseline; raw thresholds serve as *starting hypotheses* until the probe gives distributions, then become z-scores.

**Drain detection as change-point**: a one-sided CUSUM on the standing-opposing series' log-returns, threshold set so the false-alarm rate per quiet hour is bounded — a principled "sellers started falling" time instead of eyeballing a 10 s change.

**Calibration discipline**: labels fixed at a horizon *after* the verdict; features use data only up to the verdict time; out-of-sample means **by session** (walk-forward), never shuffled ticks; thresholds scanned on a grid with precision/recall plotted against verdict latency — the *latency–accuracy curve* is the deliverable and the owner picks the operating point. Minimums: ≥ 150 labelled tests per class per regime (binomial 95% CI about ±8 pts at p ≈ 0.5), ≥ 30 per grid bin.

**Two-stage output** is the only honest way to be early: a WEAKENING alert with a high false-positive rate that G4/G6 may act on with reduced commitment, then a BREAKING verdict with a lower one.

---

## 4. The debate

**(a) Does the option book lead the futures?** Lakshmi has seen CE bids build and asks thin before the futures move. Yusuf: survivorship; the same picture precedes trapped buyers. G1 has written the lead into its design. *Evidence that settles it:* on the probe recordings, the probability of futures moving ≥ 5 pts within 30 s after a hero-ladder "asks thin + bids build" event against the base rate, and the measured lag between the first CE ask-pull and the first futures tick. **Decided:** build the measurement, publish `asks_pulled` with its measured lead, and nobody assumes the lead until the probe shows it. G1's statement is flagged as a cross-group hypothesis.

**(b) Per-level versus window quantities.** The brief's §5.5 defines S, C, R, P per level; Yusuf showed per-level differencing produces false pulls on every re-price; Henrik and Nikhil agreed. **Decided:** S, R, P on the *visible window totals* (quantity and order count) of the opposing side; C attributed per price by the sweep model but reported as a window sum; per-level deltas kept only for the iceberg and spoof detectors.

**(c) Can the data support attack profiling?** Nikhil: at 1–4 snapshots/s an attack of 1–2 s is one or two snapshots; `C_k`/`R_k` at that resolution is noise. Lakshmi: profile only attacks spanning ≥ 2 snapshots; the `ρ` sequence still means something there. Henrik: each `ρ_k` carries a confidence from its snapshot count and consumed quantity. **Decided:** attacks profiled at ≥ 2 snapshots; single-snapshot attacks feed C and A only.

**(d) Futures book or option book?** Yusuf: the futures book, because option quotes are derived and the option window is a quarter-point. Lakshmi: the option book still shows aggressor behaviour, and the owner asked for it on the options. **Decided:** the level state machine runs on the **Nifty futures book** (mapped to spot levels via the basis EWMA) and on each hero contract's own premium levels; the option ladder's main roles are **coherence** and the **run score**. Verdicts that feed a trigger come from the futures level plus coherence; an option-only verdict is advisory.

**(e) How early?** Henrik wanted a measured curve before any promise; Lakshmi wanted WEAKENING to fire on the first attack with a falling `ρ`. **Decided:** two-stage output, WEAKENING allowed to be wrong about half the time, BREAKING calibrated to a pre-registered precision, operating point fixed from the latency–accuracy curve on probe recordings.

**(f) Totals.** Spoofable and price-blind, but the only view beyond the quarter-point. **Decided:** totals feed rate classes for L1-only instruments and a "deep order placed/pulled" event; they never trigger on their own.

---

## 5. Consensus proposal

### 5.1 What it is

A per-instrument **flow and force engine** that turns the consolidated Breeze stream into four honest series (standing buyers, standing sellers, aggressive buying, aggressive selling), a stale-free volume clock, and a per-level **force state machine** with a two-stage verdict. Full-resolution on the twelve depth instruments (ten Nifty hero contracts, Nifty futures, BankNifty futures); degraded L1-only mode on everything else. Every output carries its age; nothing older than its horizon is shown as live or used in a verdict.

### 5.2 A day in its life (ANALYSIS, illustrative)

09:14 — raw handler registered; level registry loaded from G2 and from memory. 09:15–09:16 — opening burst across 300 feeds; depth instruments warm their baselines; no rate class is quoted until 30 samples exist. 09:45 — spot 23,085, futures 23,112; G2's zone at 23,100 spot ≈ 23,127 futures is **approaching**. 09:46:10 — touch enters the band: **testing**; `S₀` = 1,420 lots across the ask window, 61 orders. Attack 1: 380 lots consumed in 2 s, refill 410 → `ρ₁ = 1.08`, price rejected 1.5 pts: **holding**. 09:47:30 — attack 2: 560 consumed, 290 refilled, `ρ₂ = 0.52`, orders 61 → 38 with trades explaining 60% of the drop; the standing-ask CUSUM crosses; 4 of 5 CE strikes show asks draining-fast, 4 of 5 PE strikes bids draining — coherence 0.8; G1 reports basket push, synchrony 0.6. **WEAKENING** fires at 09:47:33 (two short tones). 09:47:41 — window asks 31% of `S₀`, `π = 0.41`, 23,100 CE spread 0.10 → 0.35, `A` rising: **BREAK-IMMINENT**; one snapshot later the touch is 2 ticks beyond on 80% buy-classified volume: **VACUUM**; G6 receives the live ask ladder and an urgency flag. 09:48:10 — 6 pts beyond for 30 s: **broke**; the level flips to support with a fresh `S₀`. 10:20 — re-tested from above, holds twice (`ρ` 1.3, 1.1), marked battle-tested for G2.

### 5.3 Inputs by Breeze field

| Field | What we use it for | Trust |
|---|---|---|
| `last`, `ltq`, `ttq`, `ltt` (raw epoch) | trade clock, volume bins, classification, trade-stale | `ttq` monotone = truth; `ltq` = one trade only; `ltt` second-resolution (sub-second only if the raw epoch is float — probe) |
| `bPrice/bQty/sPrice/sQty` | L1 touch, spread, L1-only standing series | fresh per tick; compare quantities only at the same price |
| `totalBuyQt/totalSellQ` | regime, deep-order events, L1-only rate classes | whole book, spoofable, never a trigger alone |
| depth `[rate, qty, orders, flag] × 5` per side | window totals S, N; sweep model; iceberg/spoof | quarter-point window; `flag` meaning unknown (probe) |
| `OI`, `CHNGOI` | writer behaviour at the strike under test | `CHNGOI` likely null on NFO; compute ΔOI ourselves |
| `avgPrice`, `ttv` | sanity only (`ttv` is a string) | not for interval VWAP |
| receive time (monotonic, FEED process) | book clock, bins, ages | the only clock that is consistent across instruments |

### 5.4 The buyers-vs-sellers tracker

**Four series per instrument**, each a (qty, orders) pair where orders exist:
- `RB` resting buy: hero = Σ over the five visible bid levels; L1-only = `bQty` (same-price rule) with `totalBuyQt` as the slow series.
- `RS` resting sell: mirror.
- `AB` aggressive buy volume, `AS` aggressive sell volume, plus `U` unclassified — per 1 s bin and as EWMAs.

**Trade classification on consolidated ticks.** Let `Δq = ttq₁ − ttq₀`, previous quotes `(b₀, a₀)`, current `(b₁, a₁)`, `p = last`.
1. `Δq ≤ 0`: no trade (if `ttq` fell: out-of-order or replay — drop the tick, count the anomaly).
2. `p ≥ a₀` → all `Δq` to `AB` (buyer lifted the ask, possibly several levels). `p ≤ b₀` → all to `AS`.
3. `b₀ < p < a₀` (quotes moved during the interval): tick rule against the previous `last` (up → `AB`, down → `AS`); if unchanged, position rule against the new quotes (`p == a₁` → `AB`, `p == b₁` → `AS`, else midpoint of `(b₁, a₁)`); confidence low.
4. First tick after a gap > 2 s for the instrument, or `b₀ ≥ a₀` (crossed/locked artefact), or `ltq > Δq`: `Δq → U`.
*Failure cases, stated:* an interval in which price went up and back down prints one `last`; the sweep is split wrongly and `U` is under-stated — the 2 s and 10 s CVD slopes are robust to this, the 1 s bin is not and is displayed as such. `ltq` is kept as one real trade-size sample per tick (median `ltq` over 60 s = typical trade size).

**Consumed / pulled / added on depth (hero instruments).** Between depth snapshots `D₀`, `D₁` with trades `Δq` classified in between, for the opposing side (asks for an up-move):
- Compare **by price**, not by rank; a level outside the new window's price range is *unobserved*, not pulled.
- **Sweep model:** allocate `AB` to ask levels from `a₀` upward, filling each level's `S₀(p)` before the next → consumed `C(p)`; leftover beyond displayed sizes = hidden liquidity hit (iceberg or refill evidence).
- Window residual `ΔS_w + C_w = A_w − P_w`: positive → net refill `R`, negative → net pull `P`. Gross add and pull inside one interval are not separable at snapshot cadence; we report the net and say so.
- Order counts: `ΔN` with no trades → orders pulled or added; `ΔS/ΔN` is the footprint size of what came or went.
- Re-price filter: `ΣS` and `ΣN` conserved across the window (±C, ±10%) while levels shifted together → re-price, `P = 0`.

**Multi-horizon EWMAs with ages**: every series at h = 2 / 10 / 60 s, `age` attached, grey past its half-life.

**Rate classes for the standing opposing series `S(t)`** (window total for hero; `sQty`-at-same-price plus `totalSellQ` for L1-only). With `r10 = ln(S_now/S_10s_ago)` and `r60 = ln(S_now/S_60s_ago)`: **[HYPOTHESIS, starting values]**
- REFILLING: `r10 > +0.15`
- HOLDING: `|r10| ≤ 0.15` and `|r60| ≤ 0.30`
- DRAINING-SLOW: `r60 ≤ −0.30` and `r10 > −0.40` (steady loss over the minute)
- DRAINING-FAST: `r10 ≤ −0.40` (a third gone within 10 s)
- PULLED: `r10 ≤ −0.50` and consumption explains < 25% of the drop
Henrik's CUSUM timestamps the start of a drain; the class names are the owner's "slowly / fast".

**The run score** for contract `c` in direction `d` (UP: CE's opposing side is asks, PE's is bids; DOWN mirrored):
`RS_c = w₁·clip(v_c / v_ref) + w₂·drain_c/3 + w₃·agg_c + w₄·pull_c`, with `v_c` = mid-price velocity (EWMA 5 s, pts/s; mid = (b+a)/2, less noisy than `last`), `drain_c ∈ {−1,0,1,2,3}` for the classes above, `agg_c = (AB−AS)/(AB+AS)` over 10 s signed toward `d`, `pull_c ∈ {0,1}`. Starting weights 0.3/0.3/0.3/0.1, `v_ref = 0.5 pt/s` (MYTHOS's knife guard used 0.6 pt/s falling as "free-fall", `config.KNIFE_PREM_VEL`). **"Sellers falling while the CE runs"** = `RS_c ≥ 0.5` with `drain_c ≥ 1` and `v_c > 0`. The PE mirror in the same up-move is bids draining with `v_c < 0` and `agg_c` negative — the same formula with the opposing side swapped.

**Cross-strike coherence** `K_d` = liquidity-weighted fraction of the ten hero contracts with `RS_c ≥ 0.3` in direction `d`. **[HYPOTHESIS]** `K_d ≥ 0.7` for trigger-eligible; `K_d ≤ 0.3` = local/fake. The cross-right mirror is built in: a CE-only pattern with no PE mirror scores `K ≈ 0.5` at best and is an IV event, not direction.

### 5.5 Volume per unit time without stale data

- **1 s bins on the receive clock** per instrument: `vol = Σ Δq` of ticks received in the bin, split `AB/AS/U`, rolled into 5 s / 15 s / 1 m. `ltt` is *not* the bin clock (second resolution, trades only, possibly out of order); it flags `trade_age` and out-of-order ticks.
- **First tick after a gap** (> 2 s for that instrument): its `Δq` is real but unplaceable; it enters the EWMA as rate `Δq/Δt_gap` (honest average over the gap), is marked `gap_volume`, drawn as one grey bar spanning the gap, and goes to `U`.
- **Staleness is per instrument and per kind.** `trade_stale` when `now − t_last_trade_tick > max(3 s, 5 × median inter-trade interval over 5 min)`; `book_stale` when no quote/depth message for `> max(2 s, 5 × median inter-message interval)`; `feed_stale` when the socket has carried nothing for 3 s in market hours (the brief's dead-session case). An ITM-2 contract that trades every 20 s is not stale at 10 s; an ATM contract silent for 5 s is.
- **Display and gating:** every number carries its age; white → amber at half the threshold → grey past it → red on `feed_stale`. A verdict whose inputs are grey is not issued; the panel shows "no verdict (stale)", never the last verdict. MYTHOS exited held positions after 15 s of silence (`STALE_QUOTE_EXIT_SEC`); that rule belongs to G6, fed by our `book_stale` flag.
- The Breeze OHLCV 1-second stream (separate socket, CSV with `volume` and `oi`) is a probe-time cross-check for the bins, not a hot-path input.

### 5.6 The Force Detector

**Level registry.** Per instrument, the nearest 2–3 levels above and below from: G2's `pressure.zones` (OI walls, voids, session and prior-day H/L/C, VWAP/anchored VWAP, with strength and test counts); strikes and round numbers for the underlying; round premiums (every 10 pts, 50/100/150/200 weighted) and session high/low per hero contract; battle-tested levels from memory. Spot levels map to the futures book through `basis_EWMA60` and are shown in both units.

**Attack band** (within which a level is "under test"). **[HYPOTHESIS, starting values]** Nifty futures ±5 pts; BankNifty futures ±12 pts; stock cash/futures ±0.15% of price; hero options ±2 premium pts below 150, ±3 above. These are 10–20× the visible window, which is why S, C, R, P are measured at the touch *during* the test and `S₀` is defined at band entry.

**State machine per (instrument, level):** `idle → approaching → testing → {holding | breaking | broke | rejected}`.
- `approaching`: touch within 2× band, moving toward the level.
- `testing`: touch within band; `S₀`, `N₀` = visible opposing window totals at entry, `C=R=P=0`, attack counter starts.
- `holding`: price ≥ band away on the near side for ≥ 10 s without crossing (test continues; attacks counted).
- `rejected`: holding ≥ 30 s with `A` below half its peak → test closed as HOLD.
- `breaking`: BREAK-IMMINENT or VACUUM live.
- `broke`: touch ≥ band beyond for ≥ 30 s → test closed as BREAK; the level flips role with a new `S₀`.
- Resets: `idle` when the touch leaves 2× band for 30 s; `unknown` (not idle) on `book_stale`, reconnect, or the 09:15 open. Intraday S/C/R/P never cross a session; the registry and test counts do.

**Quantities during a test (window totals of the opposing side):**
- `S` current visible opposing quantity (and `N` orders); `S₀`, `N₀` at band entry.
- `C` cumulative consumed (sweep model), `R` cumulative net refill, `P` cumulative net pull.
- `A = dC/dt` (EWMA 5 s, lots/s) — attack intensity; `A_peak` for this test.
- `absorption = C / max(progress, 1 tick)` with progress = furthest advance into the level during the test (lots per tick of progress); high absorption with zero progress = a wall doing its job.
- `ρ = R / C` (quoted only when `C ≥ 100 lots` on futures, `≥ 50 lots` on options — hypothesis floors); `π = P / S₀` (only when `S₀ ≥ 200 lots` futures / `≥ 50 lots` options).
- Attack profile: list of `(C_k, R_k, ρ_k, A_k, snapshots_k)` for attacks spanning ≥ 2 snapshots.
- Strike OI trend for option levels and for the futures level nearest a strike: ΔOI over 60 s from the WS field (writers adding = defending; unwinding = fuel).

**Verdicts [HYPOTHESIS — thresholds with starting ranges, to be calibrated per §5.8]:**
- **HOLD-STRONG**: `ρ_10s ≥ 1.0` (0.9–1.2), `A < 0.5·A_peak`, progress ≤ 0 with a rejection of ≥ 2 ticks, aggressor share toward the level < 50%. Consumers: G2 (zone strength), G4 (fade candidate — the opposite option).
- **WEAKENING** (stage 1, early): `ρ_10s < 0.7` (0.5–0.8) **and** standing class ≥ DRAINING-SLOW **and** `A` steady or rising **and** (for Nifty) `K_d ≥ 0.5` — or the attack profile shows `ρ_k` falling over two attacks with `A_k` rising. Expected to be wrong often; that is its job.
- **BREAK-IMMINENT** (stage 2): `ρ_10s < 0.5` (0.3–0.6) sustained ≥ 2 snapshots and ≥ 2 s, `S < 0.4·S₀` (0.3–0.5), `A_5s ≥ A_baseline`, `π ≥ 0.3` (0.2–0.5), strike OI not rising over 60 s, `K_d ≥ 0.7`, G1 basket push sign agrees.
- **VACUUM**: `π ≥ 0.5` (0.4–0.7) reached within ≤ 3 s with consumption explaining < 25% of the drop, spread ≥ 2× its 5-minute median, touch already ≥ 2 ticks beyond the level. Fill will be thin and fast; G6 lifts at ask plus buffer, never rests.
- **FAKE**: any of — `ρ ≥ 1` with `A < A_baseline` despite a 1-tick poke through (a probe, not an attack); `K_d ≤ 0.3`; G1 synchrony below its floor; no cross-right mirror; a spoof signature on the *attacking* side in the last 30 s (large single order added then pulled); the break occurred on `U`-dominated volume (gap).

**Iceberg logic (per price, hero only):** cumulative executed at price `p` ≥ 3× the largest displayed `S(p)` during the test while the level persists and `N(p)` ≤ 2 → `iceberg`; raises `R` credibility and suppresses WEAKENING at that level until two consecutive hits go unrefilled.

**Spoof / large-order logic (hero only):** `ΔN = +1` with `ΔS ≥ 10× median order size` at L2–L5 → `large_order`; gone with no trades as the touch comes within 2 levels → `spoof_pulled`, and that side's `R` over the last 30 s is discounted by its size; partly consumed when touched → `large_order_real`, strengthening the side. `ΔS/ΔN` above the NSE freeze quantity → artefact, ignored.

**Hero (full depth) versus L1-only instruments.** L1-only (all other stocks/indices, Tier-1 futures until promoted): standing = `bQty/sQty` at the touch *only while the touch price is unchanged*, totals as the slow series; consumed-vs-pulled at L1 only (`ΔsQty` explained by `AB` → consumed; else pulled/added); no order counts, no window `π`, no VACUUM; verdicts limited to HOLD-STRONG / WEAKENING from touch dynamics plus aggressor CVD; each stock's L1 imbalance and CVD weighted into Nifty points for G1. A promoted Tier-1 future gets the full set.

**What the screen shows.**
- *Force ladder* (canvas, per tick): ten hero rows, CE left / PE right: LTP and mid-velocity, standing bid (lots · orders · rate-class arrow), standing ask (same), 10 s aggressor bar, CVD and volume/s sparklines (60 s), ΔOI 5 min, spread vs median, `RS_c` UP and DOWN, age dot. Footer: `K_UP`, `K_DOWN`, basket push (G1).
- *Level panel* for Nifty futures (and the held contract): level in spot and futures units, kind and strength (G2), state, time in test, `S/S₀`, `N/N₀`, `C`, `R`, `P`, `ρ`, `π`, `A`, absorption, attack profile as `ρ_k` chips, OI trend, verdict with confidence and age.
- *Event tape*: state changes only, one line each, audio only on these. The old top-of-book imbalance commentary "fired 6 ways/sec" (`config.py`) and is not repeated.

### 5.7 Data flow

FEED raw handler → shared-memory latest-state row per instrument (L1, totals, ttq, OI, depth 5×2×4) + ZeroMQ PUB of the raw list with receive stamp → G3 worker (SUB, conflate off for depth instruments, on for the basket) computes bins, series, states, verdicts → writes outputs with their own timestamp and age to the state table and PUBs events (`flow.series`, `force.verdict`, `force.event`) → GATEWAY paints; RECORDER stores raw and outputs separately. Target: a verdict update ≤ 5 ms after the triggering message on the owner's machine.

### 5.8 Calibration

- **A test** begins when the futures touch enters a registered level's band and ends as HOLD (touch ≥ band away on the near side for 30 s), BREAK (≥ band beyond for 30 s) or STALL (neither within 3 min; kept for false-positive accounting, excluded from hold/break rates).
- **Trade relevance label:** the relevant hero contract's mid-price change over 1 / 3 / 5 min from each verdict time, honest (buy at ask, mark at bid); "right" for the owner = +8 pts before −10 (hypothesis; exit geometry is an open question).
- **Features frozen at verdict time**, labels resolved at the horizon, no feature reads past the verdict (the stop-clock rule).
- **Threshold learning:** grid-scan `ρ`, `S/S₀`, `π`, `K` jointly; report precision, recall and median lead time (seconds before the 5-pt confirmation) at each point; pick the operating point from the latency–accuracy curve, not the best single number.
- **Minimums:** ≥ 150 labelled tests per class on Nifty futures before any threshold is trusted; ≥ 30 per grid bin; separate regimes for expiry day and VIX bands once events allow.
- **Out-of-sample:** walk-forward by session; the last 30% of sessions never touched during tuning; accept a threshold only if OOS precision is within 10 pts of in-sample.
- **The trade-off, stated plainly:** waiting for `ρ < 0.5` sustained 10 s plus `S < 0.3·S₀` plus coherence plus OI confirmation is MYTHOS again — by then the touch is 5–10 pts beyond the level and the premium has moved 3–5 pts. The early edge is the attack profile (`ρ_k` falling across attacks) and the standing-series CUSUM, both available *before* the break. WEAKENING is designed to fire 5–15 s before BREAK-IMMINENT and to be wrong perhaps half the time; its value is that G4/G6 pre-position (contract chosen, size computed, a resting limit at the current ask) so BREAK-IMMINENT/VACUUM is one click, not a search.

---

## 6. Validation plan

**On the recorded frames** (1–2 s, L1 only; `app.py:1403` writes `opt_bqty/opt_aqty` into frames, so L1 sizes exist on sessions after that code landed; no depth, no per-trade data):
1. Level-test labelling and **base rates**: hold vs break by level kind across 30 sessions — roughly 20–40 tests a day, 600–1,200 tests; the prior the detector must beat.
2. **Value of a verdict**: premium response of the relevant ATM/ITM contract 1/3/5 min after each break and hold — which breaks are worth an option buyer's money, and what lead time is worth having.
3. **Trade classification** at 1–2 s on futures and ATM options: no ground truth, but the CVD's relationship to the next 30 s move is measurable, and the share of frames with `last` outside the previous spread says how often rule 2 applies at that cadence.
4. **The L1-only run score** on the frames' bid/ask sizes with the same-price rule — the baseline the depth version must beat.
5. **Negative control:** MYTHOS's BOOK ignition (`IGN_BOOK_*`: ask-qty below 70% of its value 300 s ago with ltp up 2%, floor 20,000 units) compared L1 quantities across *different* prices and fired 1,104 times in one replay log; the ignition engine it belonged to scored −48.2 pts OOS in its own ledger and was shadow-parked (`IGN_BOOK_ON = False`). Our tracker must not reproduce it.

**The live tick-recorder probe** (a normal day first, then an expiry day — Monday 19 Oct is a weekly expiry because 20 Oct is a holiday): raw handler on the socket; ten hero contracts + Nifty and BankNifty futures with quotes *and* depth; everything else quotes only. Measure and write down: messages/s per instrument (quotes vs depth) through the day and in 09:15–09:17; inter-arrival distribution; raw `ltt` type and resolution; whether depth `time` advances without trades; `ttq` monotonicity and `ltq` vs `Δttq`; OI update cadence and whether OI changes only with `ttq`; `CHNGOI` content; `totalSellQ` vs Σ visible ask levels; `Flag` contents; depth-vs-quote alignment at receive time; share of `Δq > 0` ticks with `last` outside the previous spread; conservation of window totals on re-prices; SDK handler cost vs raw handler. Only then do the hypotheses above get numbers.

**Pre-registered bar before this subsystem may influence a real order:** ≥ 10 live sessions of raw depth; ≥ 150 labelled Nifty-futures tests; walk-forward OOS BREAK-IMMINENT precision ≥ 60% with median lead ≥ 5 s before the 5-pt confirmation; WEAKENING recall ≥ 70% of eventual breaks; a shadow ledger (buy at ask on BREAK-IMMINENT/VACUUM, honest exit at bid at +5 min or −10) net positive after costs OOS and green on ≥ 60% of days; verdict latency ≤ 5 ms on the owner's machine; stale gating demonstrated on a replay with injected gaps. Until then: display and shadow only.

---

## 7. Risks and failure modes

- **Late again.** Any single-stage verdict that waits for `ρ` to be sure is post-inflection. Mitigation is the two-stage output and the attack profile; the test is the median lead time in the OOS ledger. If WEAKENING's lead is < 3 s or BREAK-IMMINENT's is ≤ 0, we have rebuilt MYTHOS with better vocabulary and must say so.
- **Wrong with confidence — re-price mistaken for pull.** Mitigated by window totals and the conservation check; still fails when a re-price and a genuine pull coincide.
- **Consolidated ticks hide the sequence.** A level hit, refilled and hit again inside one 250–1,000 ms snapshot reads as "unchanged"; `ρ` is biased toward 1 in quiet tape and toward 0 in violent tape. Confidence weights by snapshots per attack; the probe measures the cadence that sets this bias.
- **Spoofing.** Inside the window the detector sees it; beyond it only totals move. A spoofer who lays size in the window and pulls as the touch approaches creates a false `π` once — a side is discounted for 30 s after `spoof_pulled`. Not fool-proof; nothing here is.
- **Expiry-day quoter behaviour.** After ~14:30 on expiry, hero sizes shrink, spreads widen and quoters step back en masse; every strike looks like a vacuum. Regime flag `expiry_pm`: VACUUM suppressed, BREAK-IMMINENT on futures-level evidence alone, option ladder advisory; calibrated separately once there are enough expiry tests.
- **IV events read as direction.** The cross-right mirror inside `K_d` catches the symmetric case; a skewed IV move (puts bid only) still looks partly directional — G4's IV check is the second line.
- **Gap volume and reconnects.** A 5 s socket stall followed by a burst creates a false sweep: `U` bucket, grey bins, state → `unknown` on reconnect.
- **Window edge artefacts.** Levels leaving the quarter-point window are not pulls; a bug here manufactures `π`. Covered by the by-price comparison and a unit test on synthetic books.
- **Ratios at small denominators.** `ρ` with `C` of three lots is noise; floors are enforced and "n/a" is a valid display.
- **SDK overhead and field misreads.** The SDK handler parses, builds a dict, does a token lookup and a `strftime` per message — tens of milliseconds per second of GIL time at depth rates; the raw handler avoids it. `ttv` as a string, `CHNGOI` null, `ltt` ordering and unknown flags are each a silent zero or an exception in a careless parser; the hot path treats every field as optional.

---

## 8. Interfaces

**From G2 (pressure zones):** `pressure.zones` — nearest 2–3 zones above/below per instrument with kind, strength, void/wall role, test count, and the spot↔futures mapping convention. **To G2:** `force.verdict` per zone `{instrument, level, state, S, S₀, N, C, R, P, ρ, π, A, absorption, attack_profile, oi_trend, verdict, confidence, age}` at tick cadence, plus closed-test outcomes (HOLD/BREAK/STALL with duration and attacks) for the zone ledger and the battle-tested memory. Note for G2's worked example: `π` and `ρ` on a *CE's* book describe a quarter-point window at the premium touch; the wall-at-23,100 numbers come from the futures level, and the CE/PE ladder supplies `K_d`.

**From G1 (domino):** basket push `{sign, magnitude in Nifty pts, synchrony, leaders, age}` — used in BREAK-IMMINENT and FAKE. **To G1:** tick-rule CVD (`AB−AS`, 2/10/60 s slopes, `U` share) on Nifty futures and each Tier-1 stock future; per-stock L1 imbalance and CVD in Nifty points for basket book pressure; `asks_pulled`/`bids_pulled` on the hero ladder with class and **measured lead** (G1 should treat the lead as a hypothesis until the probe reports it); stock-futures OI quadrant from the WS OI field.

**To G4 (Greeks and instrument selection):** per hero contract `{RS_UP, RS_DOWN, drain class both sides, agg_10s, CVD slope, vol/s, spread vs median, ΔOI_60s, iceberg/spoof flags, age}`; `K_UP`, `K_DOWN`; the nearest futures-level verdict in each direction with confidence; a *fill-feasibility* line per contract (visible ask ladder, L1 size vs intended quantity, pull state) so G4 picks a contract that can actually be bought.

**To G5 (recorder) — exact columns.** Quote stream, one row per message: `recv_mono_ns, recv_wall_ns, instrument_id, token, feed_seq, ltt_raw, last, ltq, ttq, avgPrice, bPrice, bQty, sPrice, sQty, totalBuyQt, totalSellQ, OI, CHNGOI_raw, open, high, low, close, lowerCktLm, upperCktLm, ttv_raw(str), trend(str)`. Depth stream: `recv_mono_ns, recv_wall_ns, instrument_id, depth_time_raw, b_rate1..5, b_qty1..5, b_ord1..5, b_flag1..5, s_rate1..5, s_qty1..5, s_ord1..5, s_flag1..5`. Session stream: connects, reconnects, subscribe results, `feed_stale` transitions. Output stream (separate, timestamped): every state change, verdict, alert and the input ages at that instant — so a replay can reproduce what was *shown*, not only what was *true*. Raw values stored as received (no float conversion of strings); append-only per instrument per day.

**To G6 (execution) at VACUUM / BREAK-IMMINENT:** `{instrument, direction, urgency ∈ {rest, take, take_now}, ask_now, ask_ladder[(price, lots)×5], expected_walk for the intended quantity, spread_now, recommended_limit = ask + buffer (hypothesis: 0.5 pt for premiums < 150, 1.0 above), do_not_chase_beyond (hypothesis: ask + 2 pts), book_stale flag, age}`. On WEAKENING: `urgency = rest` with the suggested resting price. On FAKE or HOLD-STRONG against a working order: `cancel_advice`. G6 owns the decision; we own the picture of the book at that instant.

---

## 9. Open questions for the owner

1. Is the picture you mean by "number of buyers and sellers" the broker terminal's five-level depth with order counts and the two totals? (Assumed yes.)
2. Will you run one normal session and one expiry session as pure recording (no design freeze, no trading) before we set a single threshold? (Assumed yes; the first week is measurement.)
3. Levels in spot points or futures points on screen? (Assumed both, spot primary, mapped by basis.)
4. On expiry day after 14:30, may the option-ladder verdicts be advisory only? (Assumed yes.)
5. Which of the five state changes deserve sound: WEAKENING, BREAK-IMMINENT, VACUUM, HOLD-STRONG, FAKE? (Assumed the first three.)
6. What exit geometry should the calibration label use (+8 before −10 assumed)?

---

## 10. Summary for the master design

G3 delivers a per-instrument flow-and-force engine on the consolidated Breeze stream: four honest series (resting buy/sell quantity and orders, aggressive buy/sell volume with an explicit unclassified bucket), 1 s volume bins on the receive clock with per-instrument trade- and book-staleness, and a per-level force state machine (`idle → approaching → testing → holding | breaking | broke | rejected`) that measures, during a test, opposing supply `S`, consumed `C`, net refill `R`, net pull `P`, intensity `A`, absorption, `ρ = R/C` and `π = P/S₀` on *window totals* (per-level differencing produces a false pull on every quoter re-price), profiles successive attacks, and issues a two-stage verdict — an early WEAKENING alert allowed to be wrong often, then BREAK-IMMINENT / VACUUM / HOLD-STRONG / FAKE — gated by ten-contract coherence across the Nifty hero ladder with the cross-right mirror as the fake filter. Full resolution on the twelve depth instruments, degraded L1 mode elsewhere. The five-level book is a quarter-point microscope on the touch, not a wall map, so the level machine runs on the futures book and the option ladder supplies coherence and the run score. What is unknown — Breeze cadence, OI coupling, flag meanings, the option-leads-futures lag — goes to the first live probe; every threshold is a hypothesis with a range; nothing from G3 touches a real order until the pre-registered bar in §6 is cleared out of sample.

---

*Sources:* Breeze Python SDK README and `breeze_connect.py` (github.com/Idirect-Tech/Breeze-Python-SDK) — field lists, sample ticks, `parse_data`/`parse_market_depth`; Zerodha support article on SL execution without a visible breach — snapshots 1–4/s, 250 ms minimum; kite.trade forum (Zerodha API support, Aug 2024) — "snapshot means you won't get all trades"; NSE F&O Trimmed NNF Protocol 9.51 — table of contents only, broadcast chapter unreachable from this container. Old-system evidence: `mythos/feed.py`, `run7/hawk_feed.py`, `mythos/trader.py` (honest fills, knife guard 0.6 pt/s, 15 s stale exit, 2.0 max spread), `mythos/app.py` + `config.py` (BOOK ignition, radar floors), `mythos/logs/mythos.log` (1,104 BOOK events).
