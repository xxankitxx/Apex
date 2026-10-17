# APEXOPTIONS — MASTER DESIGN

*What the system is, what it actually does, and how it achieves it.*
*Chief architect, integrating the 30-member design team. **Draft 2 — Saturday 17 October 2026, red-team changes integrated (§11, D-031…D-042).***
*Sources: `00_CONTEXT_PACK.md` (the brief), `teams/G1…G7` (the working groups), `02_DECISION_LOG.md` (D-numbers below), `03_OPEN_QUESTIONS.md` (OQ-numbers below).*
*Tags: **[FACT]** verified · **[OWNER]** your requirement · **[ANALYSIS]** our reading · **[HYPOTHESIS]** must be tested before it touches money.*

---

## 0. The design in one page

**What it is.** ApexOptions is a live-order Nifty weekly options *buying* system for one trader. It watches the whole Nifty complex and about 65–70 constituent and sister-index stocks tick by tick, maps where price will meet resistance and where it will not, detects the moment a broad move starts forming *before* Nifty futures has finished pricing it, chooses the one contract that can turn that move into rupees, buys it with an IOC limit, protects it with an exchange-held stop within a second, and manages it out on evidence — not on a clock. [OWNER] Nifty only, buy only, ₹1,00,000 a day, all-in, compounding.

**What it is not.** Not a voting system: no "6 of 14 evidences". Not a confirmation system: it refuses entries once the move is mostly priced. Not a pile of exit rules: there is no +3 floor, no 4-minute kill, no clock-only exit. Not a hypothesis shipped live: every signal earns its way to a real order through a pre-registered bar.

**How it is built, in five layers.**

```
 ┌────────────────────────────────────────────────────────────────────────────────┐
 │ 5  EXECUTOR & RAILS   IOC entry ladder · exchange-held SL-limit within 1 s ·   │  G6
 │                       owner's all-in sizing · day-stop · kill switch · audit   │
 ├────────────────────────────────────────────────────────────────────────────────┤
 │ 4  TRIGGER CARD       one fused decision: WHERE (zone) + WHEN (wind/domino)    │  G4 + all
 │                       + CAN IT HOLD (force) + WHICH CONTRACT CAN PAY (Greeks)  │
 ├──────────────┬──────────────────┬───────────────────┬───────────────────────────┤
 │ 3  DOMINO    │ PRESSURE FIELD   │ ORDER-BOOK FORCE  │ GREEKS & INSTRUMENT       │
 │  who moved   │  R & U over      │  buyers/sellers,  │  forward, IV surface,     │
 │  first, how  │  price; wind     │  volume/sec,      │  feasibility, lateness,   │
 │  broad, how  │  CUSUM; sail     │  hold/break       │  strike & expiry choice,  │
 │  late        │  destination     │  verdicts         │  exit plan                │
 │  G1          │  G2              │  G3               │  G4                       │
 ├──────────────┴──────────────────┴───────────────────┴───────────────────────────┤
 │ 2  SHARED STATE       256-byte row per instrument in shared memory, every     │  G5
 │                       value with its age · ZeroMQ tick stream · REST ledger    │
 ├────────────────────────────────────────────────────────────────────────────────┤
 │ 1  TICK PATH          3 Breeze sockets → 3 FEED processes → GATEWAY → browser  │  G5
 │                       canvas · recorder · p99 feed→paint ≤ 30 ms, on screen    │
 └────────────────────────────────────────────────────────────────────────────────┘
```

**The single most important sentence in this document.** None of layers 3–4 is allowed to influence a real order until it has cleared its own pre-registered bar on recorded data and in live shadow; layers 1, 2 and 5 are built, tested and running first (§9).

**The second most important (from the red team, adopted — D-033).** The four engines together carry ~136 tunable thresholds; a 15-session shadow yields ≤ ~120 trades, enough to validate 5–10. So **v1 wires exactly one four-parameter trigger** (futures impulse + basket synchrony + one lateness test + four exits — §6.1). Domino classification, the pressure field, the force verdicts and the Greeks vetoes all run **advisory**, logging a "would-have" verdict on every trigger, and each is wired in only after an ablation on shadow data shows it adds ≥ +1 pt per trade without vetoing more than 25% of the best trades. That is how this project avoids MYTHOS's real failure: answering uncertainty with more modules.

---

## 1. What the owner asked for, and how each ask is answered

| Owner's ask | Where it lives | One-line answer |
|---|---|---|
| "Superfast… tick-by-tick display is paramount… no delay" | Layer 1 (§3) | Sockets live in processes that do nothing else; the browser mirrors a binary table and paints on canvas; feed→paint p50 ≤ 10 ms / p99 ≤ 30 ms is a number on screen with an alarm. |
| "Constantly vigilant and skeptical" about stocks, futures, options, OI of all three indices | Layers 2–3 (§4, §5) | ~300 live feeds in three tiers; every value carries its age; nothing older than its horizon is shown as live or used in a decision; 18 watchdogs for the silent failures MYTHOS suffered. |
| Number of buyers and sellers, rising/falling; volume per unit time; no stale data | G3 tracker (§5.3) | Four honest series — standing buyers, standing sellers, aggressive buying, aggressive selling — with rate classes (refilling / holding / draining slowly / draining fast / pulled), 1-second volume bins, per-instrument staleness. |
| Force detector: "this time the supporting force is not enough" | G3 force machine (§5.3) | Per-level state machine on the Nifty futures book measuring supply, consumption, refill ρ and pull π across successive attacks; two-stage verdict (WEAKENING early, BREAK-IMMINENT / VACUUM later). |
| …for all stocks and indices, and for Nifty ATM ± 2 strikes, both CE and PE | G3 + G5 subscriptions | Full depth on the ten Nifty hero contracts and Nifty/BankNifty futures; L1 mode on every other instrument; cross-strike coherence across all ten heroes. |
| Greeks at the BUY trigger | G4 (§5.4) | Feasibility (required vs remaining move), speed ratio vs the implied 1σ move, IV-spike lateness, regime at the wall, strike/expiry choice, and the exit plan. |
| Domino effect — enter in the lag | G1 (§5.1) | Classifies every episode by who moved first; triggers only while futures has priced < ~60% of the projected move. Honest correction: the lag is in the *underlying's continuation*, not in market-maker quotes (D-016). |
| Pressure zones — sail to the low-pressure zone before it is too late | G2 (§5.2) | Resistance field R and fuel field U over price; wind = a CUSUM on aggressive flow; sail = destination exists, trip pays, ≤ 60% of leg consumed, IV not yet marked up. |
| Upheaval detector | G1 + G2 + G3 together | Stage 1 positioning (field state), stage 2 trigger (wind/domino + force), stage 3–4 refused (lateness tests). |
| "Fool-proof… actually takes a trade" | G6 + G7 (§6, §8) | Engineering invariants (no position without an exchange-side stop, no duplicate order, no trade on stale data or a dead session, deterministic replay, full audit) — and an honest statement of what fool-proof cannot mean: guaranteed profit. |
| ₹1 lakh, all-in, compounding | G6 (§6.3) | `lots = floor((capital − reserve) / (p_max × 65))`, compounding on realised *net* P&L, made physical by allocating exactly that capital to F&O. The risk arithmetic is shown to you plainly; the decision stays yours. |

---

## 2. Facts that bound the whole design (verified during the design session)

- **Breeze REST: 100 calls/min AND 5,000/day across all endpoints including orders** [FACT, ICICI FAQ]. Over 375 minutes that is ~13/min sustained. → the WebSocket carries everything it can; REST is a budgeted, persisted, two-lane resource (D-005).
- **Market orders do not exist on Breeze**; the SDK fakes them as LTP ± 10% limits after a hidden quote call [FACT, SDK 1.0.69 source]. → we price every order ourselves (D-007).
- **A static IP is mandatory for API orders** [FACT, ICICI FAQ: "Request Denied: The IP address used does not match…"]. → the most likely reason day one places no order (OQ-1).
- **Nifty lot 65; freeze quantity 3,510 = 54 lots from 5 Oct 2026** [FACT, NSE/FAOP/76693]; STT 0.15% on option sale since 1 Apr 2026 [FACT].
- **No broker auto-square-off protects a long option bought through the API** (the API cannot trade OptionPlus/FuturePlus) [FACT, API docs] → the 15:20 flatten is entirely ours.
- **Order notifications arrive on a separate socket** (`livefeeds.icicidirect.com`) [FACT, SDK].
- **The SDK socket path spawns a thread per tick, can reorder ticks, hides every connect error behind one string, never closes the socket on disconnect, and truncates exchange time to whole seconds** [FACT, source read]. → our own minimal socket.io client, SDK path behind a flag (D-004).
- **NFO depth carries order counts per level; depth and quotes are separate messages, never atomic; `ltq` under-counts (use `ttq` differences); `CHNGOI` is null on NFO; broker feeds are snapshots at ~1–4/s** [FACT / FACT-by-analogy, G3 §3].
- **The 16 Oct WebSocket outage was not fixed by the saved `cert.pem`** (UTF-16, leaf-only, referenced by nothing) [FACT]; the likely mechanism is Windows caching the missing intermediate certificate when it was viewed [HYPOTHESIS, strong]. → explicit, diagnosable trust (D-025).
- **This week's weekly expiry is Monday 19 Oct** (Tuesday 20 Oct is Dussehra) [FACT, NSE holiday list].
- **Theta on a 6-day ATM Nifty weekly is ~0.03 pt per trading minute; one vol point is ~12 premium points** [ANALYSIS, Black-76 at Nifty 23,000]. → a buyer's five-minute enemy is IV and spread, not theta (D-019).

---

## 3. Layer 1 — the tick path (built first, measured always)

*Owner priority. Full specification: `teams/G5_data_platform_latency.md` §5.*

**Processes** (independent Windows processes under one supervisor; nothing inherited; a Job Object kills the whole tree together so no Breeze socket slot is orphaned):

| Process | Does | Must never |
|---|---|---|
| SUPERVISOR | creates and holds the shared table; launches/restarts everything; watchdogs; audio + Windows-toast alarms; 15:32 flight report | touch a socket; decide a trade |
| FEED-0 / FEED-1 / FEED-2 | one Breeze socket each (hero / movers / rest): `recv()` → parse → pack a 256-byte row → seqlock write to shared memory → ZeroMQ publish; per-tick µs histogram | log on the hot path; call REST; compute anything about the market |
| GATEWAY | forwards hero rows to the browser per tick, everything else coalesced every 50 ms, over two binary WebSockets | parse, compute or JSON-encode per tick; block on a slow client |
| ANALYTICS workers (G1–G4) | subscribe to the stream; write metrics back with their own timestamps | write instrument rows; drop silently |
| RECORDER | every raw message, REST response and order event into one sequenced log per socket per day | drop (1,000,000-message buffer; counter on screen) |
| REST | two lanes (orders never wait for data), persisted call ledger | exceed 60/min on the data lane |
| EXECUTOR | the order state machine (§6), order-notification socket | act on anything but a trigger card or a rail |

**The number.** Hero instruments: feed-receive→paint **p50 ≤ 10 ms, p99 ≤ 30 ms**, max ≤ 100 ms over every rolling 10 s; basket ≤ 150 ms. Amber at p99 > 50 ms for 10 s; red (audio + toast) at p99 > 100 ms, any hero row older than 2 s, or one second without a tick frame while the feed reports ticks. Measured FEED hot path in the design session: ≈ 12–18 µs per tick against a 50 µs budget — re-measured on your machine at step 1 of the build.

**Three timestamps on every tick, honestly labelled.** Exchange `ltt` (whole seconds — so sub-second *broker* lag is invisible to it, and the screen says so), FEED receive (ns), paint (browser). A cross-socket canary (Nifty futures subscribed on two sockets) is the only way to see broker-side queueing; it alarms at 500 ms divergence.

**Staleness is a property of every value.** Per-instrument trade-stale / book-stale / feed-stale thresholds scaled to that instrument's own inter-arrival time (an ITM-2 that trades every 20 s is not stale at 10 s; an ATM silent for 5 s is). Stale values are grey on screen and are never used for a decision — a stale input makes a verdict UNKNOWN, and UNKNOWN never approves an order.

**Subscriptions (≈ 300–360 feeds; capacity to be measured):** Socket 0 — Nifty spot, Nifty futures (+depth), weekly ATM±8 CE+PE (+depth on the ten heroes), BankNifty spot+futures (+depth), next-week ATM±2 from Monday of expiry week. Socket 1 — the ten top-weight names: cash, futures (+depth on the five common banks and RIL), monthly options ATM±2; a Nifty-futures canary. Socket 2 — the remaining ~58 constituents of the three indices, cash + futures; up to five promoted names get options and depth.

**REST plan:** ≈ 2,570 calls/day planned (≈ 59% of 5,000) + 300 reserved for orders; an exhaustion ladder that sheds stock chains, then sister chains, then slows the Nifty chain, and finally closes the data lane entirely so orders always have budget.

---

## 4. Layer 2 — shared state and the rules every subsystem obeys

- One 256-byte row per instrument (price, bid/ask/qty, totals, `ttq`, OI, five depth levels with order counts, three timestamps, flags); a metrics table (64 slots per instrument) with a timestamp per value; a control block (heartbeats, socket states, REST budget, alarm bits).
- Volume always from `ttq` differences, never `ltq`. Book changes timed by receive time, trades by exchange time. Expiry strings from an explicit English month list. A value older than its horizon is invalid.
- Every analytics output is published with its age and recorded, so a replay reproduces what was *shown*, not only what was *true*.

---

## 5. Layer 3 — the four intelligence engines

### 5.1 Domino Detector (G1) — "who moved first, how broad, how late"
*Full spec: `teams/G1_domino_lag.md`.*

- **Inputs:** every Nifty constituent's cash tick, Tier-1 stock futures, BankNifty and Nifty futures; each stock's move converted into **Nifty points** by its free-float weight (NSE factsheet 30 Sep 2026).
- **Every 100 ms it computes:** basket-implied move M_b and futures move M_f over 5/15/60 s; the **gap G = M_b − M_f** (futures behind the basket?); weighted **synchrony** (fraction of index weight moving the same way with volume above its own baseline); breadth; synchrony *excluding the leader* (single-name veto); concentration; crossing clocks (who crossed a volatility-normalised threshold first).
- **Episode types:** bank-led · broad basket-led · futures-led · index-program · single-name. Only the first two may claim "lag".
- **Phase machine:** QUIET → STIRRING → **FALLING** → RECRUITED → EXHAUSTING. Triggers **only in FALLING, once per episode**: broad, synchronous, futures already responding but < ~60% of the projected extent, IV not yet marked up (+2%/60 s), premium velocity not past its peak.
- **Honest correction (D-016):** market makers reprice option quotes in ~10–100 ms; no retail buyer hits a stale delta quote. What is capturable is the *continuation* of a broad move plus the filtering of narrow, fake ones. Estimated capture on a true 20–40 pt impulse: **+5 to +8 ATM points net (+12 to +15 on a Δ≈0.9 ITM)** vs **+1 to +3 for a confirmation entry** — and +1 to +3 is exactly MYTHOS's recorded median peak of +3.1. [HYPOTHESIS until Study F3]
- **Kill rule pre-registered:** if basket-led episodes are < 15% of impulses (Study F1), the detector is re-scoped to a veto/annotation service.

### 5.2 Pressure Field (G2) — "where it will stop, where it will run, when the wind blows"
*Full spec: `teams/G2_pressure_zones.md`.*

- **Two fields over price, one unit** (Nifty-futures-equivalent contracts), 5-point grid ± 600 pts: **R** = resistance to movement (resting depth, OI walls × hedging, volume nodes, battle-tested memory, prior-day and opening-range levels) and **U** = fuel released if the level breaks (writers covering, short-gamma hedging, trapped positioning). Your "high pressure" is high R *and* high U at the same place — a dam; "low pressure" is low R — the valley.
- **Nifty field** = chain + a beta-mapped, breadth-weighted basket overlay + BankNifty (FinNifty synthesised from its constituents). When they disagree, the nearer wall sets the destination and the disagreement is shown, never vetoed.
- **Wind** = a CUSUM on one signed flux (futures CVD z-score, basket impulse, basis velocity), its gain *amplified* — never gated — by structure changing at the wall ahead (OI unwinding, depth pulled, synchrony, IV lift at the wall strike, price efficiency rising). Confirms in 2–8 s; a gust decays before crossing.
- **Set sail** when: wind; R ahead < R behind (or the wall ahead is BREAK-IMMINENT per G3); a destination exists; **the remaining distance pays** (D_rem ≥ 1.3 × required move); **≤ 60% of the leg consumed**; **ATM IV up ≤ 1.5 vol points since wind onset**. Worked example at Nifty 23,000: a ~100-point entry window on a 155-point trip; after that the ship stays in port.
- **Memory:** zones created, tested (by G3), strengthened, flipped on break, persisted nightly with 8%/day decay; a new weekly wall at a remembered level inherits its test history.
- **Dependency flagged (D-018):** whether OI on a WebSocket tick changes per trade or on an exchange interval is unmeasured. Until the probe answers, OI is context/amplifier only, never a trigger input.
- **Correction (D-031):** G2's worked example uses the brief's old theta prior (0.3 pt/min; 1–1.5 on expiry). At the correct 0.03–0.25 pt/min, θ·H over 13 minutes is ~2–3 pts, not 15–20 — so G2's "most sails fail the pays rule after lunch on expiry day" is an artefact. Expiry-afternoon caution comes from G4's delta bands and the 0DTE time rails, not from the pays rule.
- **Red-team cuts from v1 (D-034):** rejection sails, GEX, max pain, the basket-overlay field, U in any formula, and the wall-unwind / depth-pull amplifiers until the probe measures OI cadence. The zone ledger (levels with tests held/broken) and the leg-consumed / IV-rise caps stay — the caps are the lateness test.

### 5.3 Order-Book Force & Flow (G3) — "buyers, sellers, and whether the level holds this time"
*Full spec: `teams/G3_orderbook_force.md`.*

- **Four honest series per instrument:** resting buy (qty + orders), resting sell (qty + orders), aggressive buy volume, aggressive sell volume — plus an explicit *unclassified* bucket when a consolidated tick cannot be attributed.
- **Consumed vs pulled vs added**, on *window totals* (D-013): sellers being **eaten** (volume at the ask, grinding price), sellers **leaving** (shrinking without trades — the vacuum), or quoters simply **re-pricing** (nothing changed; filtered by a conservation check).
- **Rate classes** (your "falling slowly or fast"): REFILLING · HOLDING · DRAINING-SLOW · DRAINING-FAST · PULLED, timestamped by a CUSUM change-point.
- **Run score** per hero contract and **cross-strike coherence K** across all ten: "sellers falling while the CE runs" must show in most CE strikes *and* be mirrored by bids draining in the PEs — otherwise it is an IV event or one trader, not direction.
- **Force machine on the Nifty futures book** (D-012): idle → approaching → testing → holding | breaking | broke | rejected. During a test it measures supply S, consumed C, refill R, pull P, intensity A, absorption, **ρ = R/C** and **π = P/S₀**, and profiles each attack — *"defenders refill less each time while attackers come harder"* is visible one attack before the break.
- **Two-stage verdict (D-014):** **WEAKENING** (early; allowed to be wrong about half the time; the executor pre-positions) → **BREAK-IMMINENT / VACUUM / HOLD-STRONG / FAKE**. VACUUM tells the executor to lift the ask immediately.
- Starting thresholds are hypotheses; they are calibrated from ≥ 150 labelled level tests, walk-forward by session; the deliverable is a latency-vs-accuracy curve from which you pick the operating point.
- **Red-team amendments (D-035):** BREAK-IMMINENT as specified is a seven-clause AND-gate (incl. a 60-s OI window and the G1 sign) — i.e. late by construction; the OI clause waits for the probe and the G1 sign moves out of the verdict into the trigger card. **WEAKENING never places an order in v1** — it only pre-computes contract and size. Spoof/iceberg detectors are display-only.

### 5.4 Greeks & Instrument (G4) — "which contract can pay, and are we late"
*Full spec: `teams/G4_greeks_instrument.md`.*

- **Engine:** synthetic forward from ATM put–call parity; Black-76; IV from the mid with an uncertainty band; surface at 4 Hz, hero Greeks per tick, regime at 1 Hz; sticky-IV P&L attribution (how much of the premium change was delta, gamma, vega, theta) for the open position.
- **At a trigger, five checks:**
  1. **Feasibility** — required spot move to make the target after spread and rent, vs the move still projected. +12 needs ~25 spot points at a 6-day ATM, ~18 at ITM4, ~31 at OTM2.
  2. **Speed ratio** — remaining projected move ÷ the implied 1σ move for the hold (9.2 pts for 5 minutes at 13% IV). < 1 → the option market itself says the move won't pay the rent.
  3. **IV lateness** — IV up ≥ 8–12% in 5 min, IV ≫ realised vol, straddle widening, skew already tilted our way → LATE/PRICED. *("It pulls back right after I enter" is mostly buying the IV spike the move itself created — one vol point ≈ 12 premium points on a 6-day ATM.)*
  4. **Regime at the nearest wall** — PIN / NEUTRAL / ACCELERATE, inferred from behaviour (OI dynamics, price response, straddle), because the dealer-gamma sign cannot be known from Indian OI. In a PIN, approve only with G3 BREAK-IMMINENT/VACUUM.
  5. **Instrument** — DTE-dependent delta bands (≥3 DTE: Δ 0.52–0.70; 1–2 DTE: 0.60–0.80; expiry day before 13:00: 0.65–0.85; after 13:00 prefer next week; none after 14:45), spread-filtered, tie-break to "the strike that is already moving". **Under all-in sizing, strike choice IS position size** — a cheaper option loses more of your capital per adverse point.
- **Verdicts are advisory first (D-023).** LATE/PRICED may veto only after its bar.
- **Red-team corrections (D-032, D-036):** the speed ratio mixes clocks — the 5-minute 1σ move at 13% IV is **9.2 pts on a calendar clock but 21.7 pts on a trading-minute clock**; the true value lies between and must be calibrated on the frames' realised moves before ρ is shown, let alone used. The weighted instrument *score* is not live on day one (its weights are unspecified — a hypothesis shipped live); v1 uses a plain rule: **DTE delta band → nearest-the-money strike that passes the spread filter.** LATE as "any two of four IV tests" is a vote and is redesigned as one composite before it may veto.

---

## 6. Layers 4–5 — the trade, from trigger to flat

### 6.1 The trigger — v1 (wired) and the full card (advisory)

**v1 — the only thing allowed to fire an order in shadow and live (D-033), four tunables:**
1. **Impulse:** Nifty-futures 15-second move in direction d with z ≥ m* against its own 20-minute scale.
2. **Structure:** weighted basket synchrony S(15 s) ≥ s* (fraction of index weight moving with d on above-baseline volume) — this is your domino, reduced to the one number that separates a broad move from a narrow fake.
3. **Not late (one composite, not a vote):** futures move since episode onset ≤ L* × its 20-minute median impulse, **and** ATM IV up ≤ 1.5 vol points since onset (frozen, not tuned).
4. **Exits:** exchange stop at a fixed spot distance d* converted by delta; trail on the futures path from +1R; thesis-void = synchrony sign flip; the time rails. Nothing else.
Instrument: DTE delta band → nearest-the-money strike passing the spread filter. **It must beat a MYTHOS-ignition-style null on the same days, not merely zero** — a futures-momentum trigger is exactly what lost −138.5 pts out of sample before; synchrony is the claimed difference and has to prove it.

**The full card — shown on every trigger, every field advisory until ablation earns it a vote:**
A trigger is born from **one** of two sources — the Domino Detector in FALLING, or the Pressure Field's SAIL — and is then *qualified*, not voted on:

```
SOURCE        domino FALLING  or  wind → SAIL                     (when)
WHERE         destination / wall ahead from the pressure field    (where to)
CAN IT HOLD   G3 verdict at the level in the way:                 (will the wall give)
              BREAK-IMMINENT / VACUUM → go;  HOLD-STRONG → no;  WEAKENING → pre-position
WHICH         G4 instrument + feasibility + speed ratio + lateness (can this contract pay)
SIZE          owner's all-in rule (G6)
EXIT PLAN     structural stop · take-zone · trail on futures path from +1R
WHY           one sentence, e.g. "bank-led domino: HDFCBANK first, 4 of 5 banks +
              RIL/LT joined; futures −7 of projected −19 (37%); IV +0.8%; support
              22,990 BREAK-IMMINENT; 23,000 PE Δ0.55, 9 lots, needs 22 pts, 1σ 9.2"
```
Every input on the card shows its age. A stale input → UNKNOWN → no order.

### 6.2 Executing the trade (G6)
*Full spec: `teams/G6_execution_risk_capital.md` §5.*

1. **Pre-trade checks (< 1 ms, local):** flat; inside 09:15:05–15:15; not halted; book fresh (L1 age < 500 ms); session heartbeat fresh; order socket alive; no live order of ours exists.
2. **Entry:** IOC limits laddered **ask + 0.3 → ask + 1 → ask + 2** (start rung from G3's urgency; VACUUM starts higher); stop chasing at G3's cap or 4 seconds. Partial fills are kept. No resting bid below the market on a momentum entry (it fills when the move fails).
3. **Protect within one second:** an **exchange-held stop-loss-limit SELL** for the filled quantity (trigger = the structural stop in premium terms; limit 5 pts / 4% below; wider on expiry afternoons). It survives a dead session. GTT is the fallback; never both (a double exit is a naked short).
4. **Manage in software on every tick:** in v1 exactly four exits — the exchange stop, the trail on the futures path from +1R, thesis-void (synchrony sign flip), and the time rails (D-038). The other proposed exits (bleed exceeded with a dead driver, IV deflated after the move, vega windfall, destination reached) are shadow-logged and earn their way in by ablation; twelve exit rules would rebuild MYTHOS's ladder under better names.
5. **Exit:** modify the resting SL into an aggressive limit at bid − 0.3 → −1 → band edge; alarm and manual checklist if still unfilled after 5 s.
6. **Flat:** realised **net** P&L (STT, exchange, SEBI, stamp, GST, brokerage) compounds into capital.

### 6.3 Capital and the arithmetic you must see (information, not a recommendation)
- Sizing is your rule: `lots = floor((capital − reserve) / (p_max × 65))`; above the freeze quantity (3,510 units = 54 lots) the order is **sliced, never capped** (D-037) — 54 lots cost only ₹1,00,000 at a ₹28.5 premium (₹1,30,000 at ₹37), so expiry-week sizes reach it and the slicer is tested live in the one-lot trial; the F&O allocation is set to exactly the day's capital so ICICI itself rejects a duplicate or oversized buy.
- **A −10 premium stop costs 12.6% of capital at ₹80, 8.1% at ₹120, 4.8% at ₹200, 28% at a 0DTE ₹35.** A 20-point gap-through at ₹80 costs 37%.
- **At MYTHOS's 41% win rate, 48% of 12-trade days contain four consecutive losses** (−28% at ₹120, −40% at ₹80). At 55% it is 21.5%.
- **Three +12 wins compound to +30%** at ₹120. The rule rewards a real edge as hard as it punishes a streak.
- **At MYTHOS's measured statistics, Kelly is negative** — no stake is right until an edge exists. The sizing rule is survivable only with an edge that has not yet been measured.
- **Three classes of rail (D-039, one page you sign):**
  - *Invariants — not switchable:* no naked short; one position; a protective order on every fill; time rails; order-rate and REST limits; kill switch; and the **phase size cap** (0 lots in shadow, 1 lot in trial, then the ramp) — it protects the measurement, not the trader.
  - *Owner-switchable defaults (on unless you say off, logged):* day-stop at −20%; 30-minute pause after 3 consecutive stops; a 6–8% per-trade cap applied as a **strike-eligibility filter** (it never reduces lots; it removes contracts whose structural stop would cost more than that — so it is compatible with all-in).
  - *Information only:* the streak table, the gap-through table, the Kelly sign.
  The risk officer's dissent stays on record: at MYTHOS's statistics she would not let the day-stop be switched off.

### 6.4 Exit geometry (pending your answer, OQ-5)
Structural stop in spot terms, converted to premium via delta, capped in % of capital · take-zone 0.6–0.7 × projected move · trail on the *futures path* (IV flicker and spread bounce cannot stop you out — only the underlying can) from +1R · evidence-only early exits. **No +3 floor, no breakeven ratchet, no 4-minute kill, no clock-only exit** — those turned MYTHOS's correct entries into +0 to +4 exits (132 ramp-floor exits at +3.8; 163 time-kills).

---

## 7. A day in the life (non-expiry Wednesday)

- **08:45** You paste the day's session token into the credential store; `apex preflight`: TLS probe on all three hosts, session, clock skew, spot, VIX, the computed expiry and its chain row count, constituent tokens, funds = capital, positions flat, public IP = registered static IP, one real socket test. **GO / NO-GO in under a minute.**
- **08:50** `apex start`. Supervisor → table → recorder → gateway → analytics → REST → three FEEDs. Browser opens on a snapshot.
- **09:15** Opening burst; latency meter live; the domino strip, pressure map and force ladder fill in; suppression 09:15–09:25 (overnight news moves everything together — synchrony is meaningless).
- **09:16** Notification probe: a 1-lot ₹0.05 buy that cannot fill, cancelled — proves auth, IP and the order socket before any real trigger.
- **10:05–10:48** *(illustrative)* The 23,100 CE wall is approaching; G3 tests it — attack 1 refilled (ρ 1.08), attack 2 refilled only half (ρ 0.52), orders 61 → 38, asks draining across 4 of 5 CE strikes and bids across 4 of 5 PE strikes → **WEAKENING** (two short tones); the executor pre-computes the contract and size. Banks and RIL join; futures has done 37% of the projected move; IV +0.3 → **BREAK-IMMINENT** → card → **IOC at ask + 0.3, filled** → SL-limit resting at NSE within a second. The trade runs the void; at the destination G3 reports HOLD-STRONG and synchrony fades → evidence exit at the bid. Capital compounds.
- **12:30–13:30** Lags lengthen, impulses shrink; most episodes classify as futures-led → "ALREADY IN FUTURES", no trigger, reason on screen.
- **15:15** No new entries. **15:20** flatten window. **15:30** reconcile against the broker's trade list; positions must be empty. **15:32** flight report (latency percentiles, drops, reconnects, budget, alarms, silent instruments) and the nightly who-led report.

On **Monday 19 Oct (expiry)** the whole afternoon runs the expiry profile: ITM-only, next week preferred after 13:00, no 0DTE entries after 14:45, option-ladder verdicts advisory after 14:30.

---

## 8. "Fool-proof" — what the build will be held to

**It can mean: the system fails stopped and loud, never running and quiet.** Fifteen invariants, each with an automated test and a live check; a violation blocks new entries and alarms (full table: G7 §3).

| # | Invariant |
|---|---|
| I-1 | At most one open position and one live order of ours per side, ever. |
| I-2 | Live sell quantity ≤ held long quantity at every instant (no naked short). |
| I-3 | Every filled unit is covered by exactly one resting protective sell within 2 s of the fill — else flatten immediately and HALT. |
| I-4 | No entry unless: session heartbeat < 90 s, order socket alive, today's static-IP check passed, L1 age < 500 ms, contract = computed expiry with a non-empty chain, lot and freeze read from today's contract file. |
| I-5 | An order in UNKNOWN state is resolved by query before anything new on that contract; nothing is re-sent blind. |
| I-6 | ≤ 3 order requests/s; ≤ 400 order calls/day; data lane ≤ 60 REST/min; orders always hold 40/min and 300/day; no new entry with < 50 order calls left. |
| I-7 | No entries after 15:15; flat by 15:25 (15:00 for 0DTE contracts unless Δ ≥ 0.9); alarm and checklist if not flat 2 minutes later. |
| I-8 | Quantity ≤ owner's formula ≤ broker-reported funds; above freeze it is sliced, never capped. |
| I-9 | No decision uses an input older than its horizon; stale means "no decision", never the last value. |
| I-10 | Every order traces to a decision row with reason, inputs hash, config version and code hash. |
| I-11 | Live and shadow run the same code; thresholds change only between sessions via a versioned, pre-registered config. |
| I-12 | The kill switch reaches HALTED and starts the exit ladder within 2 s from any state; re-arming needs your explicit action. |
| I-13 | The lot cap per validation phase is enforced in code; raising it needs your signed log entry citing the bar that was met. |
| I-14 | Alarms reach you without the browser (supervisor audio + Windows toast). |
| I-15 | No credential-shaped string anywhere in the tree; preflight refuses GO otherwise. |

Plus one *positive* invariant for "actually takes a trade": **a decided trigger becomes an order within 100 ms unless an invariant blocks it, and the block reason is on screen within 1 s** — audited daily, decisions vs orders, every gap explained.

**It cannot mean** profit; a fill at the expected price in a gap or an empty expiry book; protection when NSE, ICICI's risk system or your internet line is down; no losing days; or safety from a signal with negative expectancy — only the pre-committed kill rule in §9 protects against that.

---

## 9. How we get from here to a live all-in trade

### 9.1 Build order (each step passes its gate before the next depends on it)

| Step | When | Builds | Gate |
|---|---|---|---|
| 0 | Sat 17 – Sun 18 Oct | **Probe recorder only:** SDK socket path with a raw-packet hook (bytes + receive-ns captured *before* the SDK's per-tick threads), sequenced log, holiday-aware expiry function, token builder, TLS probe, credential store | expiry function unit-tested for 19/20/21/27 Oct, 9/10 Nov, 23/24 Nov; dry run on a converted MYTHOS day |
| 1 | **Mon 19 Oct** (weekly expiry) | **First live probe — record only, no orders** (checklist §9.3) | `probe_report_1.md`: every item measured or marked "not observed" |
| 2 | Wed 21 Oct | Probe 2: second socket on the session, slot-hold time after an unclean kill, join/leave timing | two-socket answer; slot-hold seconds |
| 3 | from 19 Oct | Platform: shared table, FEED, GATEWAY + latency meter, replay (lockstep + timed), REST ledger, supervisor + watchdogs, preflight **with the static-IP check** | G5 acceptance tests; fault-injection matrix |
| 4 | parallel | Frames studies (kill tests only — §9.2 Phase 1) | results recorded against the pre-registration, pass or fail |
| 5 | parallel | Executor + FillSimulator + the 15 invariant tests | 20 paper sessions, zero invariant violations, zero reconciliation mismatches |
| 6 | as soon as a static IP exists | **Owner-clicked one-lot execution trial** (signal-free) | go/no-go: IOC accepted on NFO options; **SL-limit sell accepted without short margin** (else GTT accepted and reconciled); modify works; sale proceeds reusable (or you are told); session-kill drill — alarm ≤ 2 min and the SL survives at NSE; freeze slicer exercised (2 slices of 1 lot) |
| 7 | after ≥ 5 observe sessions | v1 trigger + all advisory engines in **shadow** | Phase 3 sequential test |
| 8 | after Phase 3 GO | Signal-driven, **one lot** | Phase 4 |
| 9 | after Phase 4 | Ramp to all-in | Phase 5 |

The custom socket.io client (D-004, reopened as D-040) is built during step 3 but goes to production only after a **full-session parity test** against the SDK path (≥ 99.9% of (token, ttq, price, bid, ask, OI) tuples matched, no silent tokens, no ttq regressions), with **automatic** fallback to the SDK path after two handshake failures and the SDK path exercised in preflight every morning.

### 9.2 Validation protocol (pre-registered; full detail G7 §4)

**Common rules.** Unit of evidence = net premium points per trade at honest fills — buy at the ask seen at trigger time + measured ack latency, **walking the visible depth for the all-in quantity** (shadow simulates all-in size even while live is one lot), sell at the bid likewise, minus charges. Every phase must also pass day-level conditions: every leave-one-day-out mean > 0, total > 0 with the best day dropped, no single day > 40% of the total, ≥ 50% of days net-green (MYTHOS: 8 of 31). Splits are by session in time order; thresholds frozen and hashed before any held-out run; one primary hypothesis per subsystem.

| Phase | What | Pass | What passing does *not* prove |
|---|---|---|---|
| 1 | 30+ MYTHOS frame days (1–2 s, no depth, 14 heavyweights) | G1: basket-led ≥ 15% of impulses; F3 net > 0 and ≥ +1 pt above an ignition-style null; median lateness at trigger ≤ 0.5 · G2: hold rate vs *random-level* control; wind lead ≥ 20 s, AUC ≥ 0.65 OOS · G3: L1 run score beats the BOOK-ignition control · G4: theta/IV-drift table, IV-path sign, the clock; each veto ≥ +1.5 pt with ≤ 25% of top winners vetoed | anything live; it does not shorten Phase 3 |
| 2 | Tick-recorder observe period, **≥ 10 sessions** incl. Mon 19 Oct (weekly expiry), Tue 27 Oct (monthly expiry), ≥ 1 trend day, ≥ 1 range day | zero recorder drops; zero silent instruments; feed→paint p50 ≤ 10 / p99 ≤ 30 ms; every probe fact written down; ≥ 150 labelled futures level tests (else G3 stays display-only); no threshold tuned before session 5 | — |
| 3 | Shadow trading, real order path disabled | **Sequential test (SPRT)** on per-trade net points, H0 μ ≤ 0 vs H1 μ ≥ +1.5, α 0.05, β 0.20 (σ frozen from the frames): **GO when cumulative net ≥ 66.5 + 0.75·n; KILL when ≤ −37.4 + 0.75·n**; ~43–61 trades expected to decide; undecided at 200 trades = fail; plus day-level conditions, ≥ 15 sessions, ≥ 2 expiry days, ≥ 1 trend day | the size of the edge (±1.5 pts at 60 trades), execution quality, regime robustness |
| 4 | Signal-driven, one lot | ≥ 30 trades, ≥ 10 sessions; median |simulated − real fill| ≤ 0.3 pt, p95 ≤ 1.0; live net within 1 pt of shadow on the same days; SPRT continues and its KILL line still applies; zero invariant violations | all-in fills (one lot doesn't walk the book) |
| 5 | All-in ramp | Phase 3 GO + Phase 4 pass + zero execution incidents in the last 10 sessions + the rails page signed → 25% → 50% → 100%, ≥ 3 sessions each; an incident or two day-stop hits → back one step | — |

**The kill rule you are asked to pre-commit to (OQ-0):** if the sequential test crosses KILL, the trigger is retired — not retuned on the same days. Any retune is a *new* hypothesis tested only on sessions recorded after it. This is the single protection against "six full rebuilds, each shipped live unproven".

### 9.3 First live probe — Monday 19 October 2026 (weekly expiry; Tuesday 20 Oct is Dussehra)
- **Before 09:00:** session; TLS probe on `livestream` and `livefeeds`; clock vs the API's `Date`; expiry = 19-Oct-2026 with a non-empty chain on both rights; tokens resolved; disk space. Decide whether MYTHOS runs that day on the same API key (then the probe is implicitly a second socket).
- **Subscribe, one socket (~85 feeds):** Nifty spot; Nifty futures quotes + depth; BankNifty spot (CNXBAN) and an attempt at BankNifty futures; 19-Oct weekly ATM±8 both rights, depth on the ten heroes; 27-Oct ATM±2 both rights; the ten Tier-1 cash names and their futures; INDVIX on the socket (attempt). At 10:00 add the remaining Nifty-50 cash names and record the rate change.
- **Log:** every raw packet with receive-ns and per-socket sequence; every REST call (VIX 1/min, Nifty chain every 90 s) with request and response times.
- **Measure:** messages/s per instrument and type (09:15–09:17 and 15:00–15:30 peaks); `ltt` type and resolution; out-of-order `ttq`; **OI behaviour** (fraction of messages where OI changed, fraction coincident with trades, interval distribution, WS vs REST lag — this decides whether OI can ever be a trigger input); `CHNGOI`; non-zero order counts in NFO depth; depth `time` advancing without trades; option-quote response to futures moves (closes the market-maker-lag question); ask-thinning lift vs base rate; expiry-afternoon spreads and depth at ITM1/ITM2 from 13:00; silence episodes; reconnects with reasons.
- **Not on Monday:** extra sockets, unclean kills, the custom client, any order call.

### 9.4 What must not be built before its measurement exists
OI in any trigger or amplifier → probe OI cadence · G3 verdict thresholds → ≥ 150 labelled futures tests on recorded depth · first-mover/lead claims → cash-vs-NFO vendor skew ≤ 300 ms · ask-thinning urgency → lift ≥ 1.5× over ≥ 100 events · three-socket split → probe 2 · custom client in production → parity test · speed ratio as a gate → clock calibration · bleed rule → measured theta/IV-drift table · vega exits → frames IV-path study · GTT path → trial shows SL-limit unusable · **any all-in order → Phase 5.** Built early, contrary to the first draft: the freeze slicer.

## 10. Where each group's work lives

| Document | What it contains |
|---|---|
| `00_CONTEXT_PACK.md` | Everything discussed before the team started; verified facts; MYTHOS post-mortem |
| `teams/G1_domino_lag.md` | Domino Detector — episode classification, gap/synchrony/lateness, Studies F1–F4 |
| `teams/G2_pressure_zones.md` | R/U fields, wind CUSUM, sail arithmetic, zone memory, Studies A–E |
| `teams/G3_orderbook_force.md` | Buyers/sellers tracker, volume clock, force state machine, calibration |
| `teams/G4_greeks_instrument.md` | Greeks engine, trigger checks, strike selection, lot-count table, exit geometry |
| `teams/G5_data_platform_latency.md` | Processes, row format, subscriptions, REST plan, display contract, watchdogs, probe |
| `teams/G6_execution_risk_capital.md` | Order state machine, IOC/SL-limit, sizing, charges, risk arithmetic, runbook |
| `teams/G7_red_team_validation.md` | Critique of all of the above, invariants, validation protocol, failure modes |
| `02_DECISION_LOG.md` | Every decision with its evidence and what would reopen it |
| `03_OPEN_QUESTIONS.md` | 21 questions for you, ranked, each with the assumption we build on meanwhile |

---

## 11. Red-team integration (what changed between draft 1 and draft 2)

The red team (G7) found the platform and execution layers close to fool-proof in the only sense the word can carry, and the decision layer honest but — taken together — repeating MYTHOS's meta-pattern of answering uncertainty with more modules. Adopted:

1. **One wired trigger, four tunables; everything else advisory until ablation earns it in** (§0, §6.1; D-033). ~136 tunables vs ≤ ~120 shadow trades made the full fusion unvalidatable in 2026.
2. **Hidden votes removed:** G1's "too late" (2-of-4), G4's LATE (2-of-4) and G3's seven-clause BREAK-IMMINENT are rewritten as single composites before any may gate an order (D-035, D-036; corrects D-015).
3. **Number corrections:** the old theta prior still in G1 §5.10 and G2 §5.6 (D-031); G4's two time clocks — 9.2 vs 21.7 pts for the same 5-minute 1σ move (D-032); the freeze quantity *is* reachable below a ₹28.5 premium → slice, never cap (D-037; corrects D-009).
4. **The custom socket.io client follows a parity test** with automatic SDK fallback; the first probe runs on the SDK path with a raw-packet hook (D-040; reopens D-004).
5. **WEAKENING never places an order in v1**; v1 has four exits; 0DTE flat by 15:00 is an invariant on expiry day (D-035, D-038, D-041; amends D-014, D-022, D-010).
6. **Session counts replaced by a sequential test** with a pre-committed kill rule (§9.2; D-042; amends D-027).
7. **Rails in three classes** — invariants (incl. the phase size cap), owner-switchable defaults, information (§6.3; D-039).
8. **SL-limit margin treatment is a go/no-go gate** for live trading: if ICICI margins a pending stop-loss sell against a long as a fresh short, the dead-session protection fails at 94% utilisation (§9.1 step 6).
9. **The first live probe moves to Monday 19 Oct** — record only; the expiry session is exactly the data the 0DTE rules need (§9.3).

Recorded disagreements kept for you to see: the risk officer would not let the day-stop be switched off at MYTHOS's statistics; the forensic auditor insists the minimal trigger must beat MYTHOS's failed ignition engine, not merely zero (adopted); the quant and risk officer disagreed on signal-driven one-lot trading before the shadow bar (resolved: the owner-clicked execution trial is early and signal-free; signal-driven one lot waits for the shadow GO).


## 12. Paper-trading build v1 (17 Oct 2026) — what was actually built

The owner switched v1 to **paper trading** (D-046…D-053): no orders, no static IP, fills at LTP gross, ₹1,00,000 a day compounding intraday. That removes the executor, the margin gate and the order-socket probe from the critical path; everything that reads the market was built.

| Process | Module | Job |
|---|---|---|
| Supervisor | `run_apex.py` | creates shared memory, starts the three processes, restarts the live feed, Ctrl+C = clean stop |
| FEED | `apex/feed_breeze.py` (live) · `feed_sim.py` · `feed_replay.py` | raw Breeze packets → shared table (seqlock rows) + recorder; VIX 60 s, chain 90 s on a REST ledger |
| ENGINE | `apex/engine_main.py` + `apex/engine/*` | 10 Hz: buyers/sellers flow classes, Greeks (Black-76 on the synthetic forward, 4 Hz), pressure walls, domino basket + episodes, force detector, five advisors, ten paper books |
| GATEWAY | `apex/gateway.py` + `apex/static/*` | tick-by-tick rows to the browser every 4 ms (only changed rows), engine state at ~4 Hz |

Universe tracked: Nifty spot/futures (depth), VIX, BankNifty and FinNifty spot/futures, 23 heavyweights (cash + futures, depth on the five big banks and Reliance), Nifty weekly ATM ± 12 (depth ATM ± 3) and next week ATM ± 4 — about 120 instruments, re-centred as Nifty drifts.

Trade rule = D-033 v1 trigger with the D-036 instrument rule and the D-038 four exits. Every trade stores the five advisors' would-have verdicts, which is what the learning loop (D-051) scores.

What is verified here: unit tests (calendar, packet parsing incl. the NSE/NFO shared token prefix, IV round-trip, sizing and stop, learning promotion) and full simulated sessions end-to-end through the same parser. **What is not:** a live Breeze connection from this build (first run Monday 19 Oct); the simulator's P&L says nothing about edge.
