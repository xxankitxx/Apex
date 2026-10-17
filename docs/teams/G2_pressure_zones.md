# G2 — Pressure Zones: working-group report

*ApexOptions design team · Working Group G2 · Saturday 17 October 2026 · chair's record of the session.*
*Tags as in the brief: **[FACT]** verified · **[OWNER]** the owner's words or requirement · **[ANALYSIS]** our reading · **[HYPOTHESIS]** must be tested before it is trusted. Every threshold in this document is a hypothesis with a starting range, not a setting.*

---

## 1. Members and their lenses

- **Priya Natarajan** — options strategist: OI walls, who is short what, dealer hedging flows, max pain, gamma by strike.
- **Tomasz Kowalski** — physicist turned systems thinker: fields, gradients, potential energy; his job is to keep the metaphor honest.
- **Arjun Sethi** — volatility trader: the IV surface, skew and term structure as stored pressure; what IV looks like before and after a move.
- **Elena Rossi** — auction-market / market-profile analyst: value areas, volume voids, single prints, VWAP/AVWAP, unfinished auctions as destinations.
- **Kavita Deshmukh** — data scientist: turning the field into features, zone persistence across sessions, "wind" as a change-point, and the validation design.

## 2. What we were asked

**[OWNER]** *"Market tends to create a high pressure zone and a low pressure zone. Wind always move from high to low pressure zones. If a system keep a good track of all such pressure zones, and then when winds start moving, we can set sail on our ship to that low pressure zone before it is too late."*

Our reading: three nouns and two verbs. **Zones** are the map. **Wind** is the detector. **Set sail** is the trigger. **Before it is too late** is arithmetic, not a feeling. **Keep a good track** is bookkeeping with memory across sessions.

What we inherited **[FACT, MYTHOS_TRADING_RULES.md, config.py 456–490, 1977–1987, 2232–2247]**: MYTHOS had zones — OI walls (strike OI > 2× neighbours), swing pivots, role-flipped levels, prior-day levels — and a display-only cross-session memory (strength EMA α 0.25, decay 8%/day, evicted after 10 days). It used the zones as *places to wait for confirmation*: a touch within 20 pts, a ≥12-pt fall into the zone, a 30-s CVD sign flip, a pivot held ≥2 s, premium within +4 of its post-touch low. The architecture document admits *"the rails guarantee post-inflection entry"*. That is the opposite of "set sail when winds start moving": it waited until the ship had already turned around. Our charter is to make the zones the *where*, the wind the *when*, and "too late" a number.

## 3. Ideas by member

**Priya (OI, dealers, gamma).**
1. An OI wall is two things at once: a *barrier* while it holds (writers defend, hedgers dampen) and a *reservoir* when it breaks (writers buy back; that covering is the fuel of the run beyond). The owner's "high pressure" is both, and the system must carry both numbers per wall.
2. OI is two-sided by construction; the feed never tells us whether the OI at 23,100 CE is a pro writer who will defend or a retail buyer who will fuel. So wall-as-barrier is a **[HYPOTHESIS]** per strike that must be *earned* by evidence: did price stall there before (the frames), and is the wall refilling when hit (G3's ρ).
3. Dealer gamma (GEX) with the conventional sign assumption (customers sell calls, buy puts → dealers long gamma above spot, short gamma below) predicts pinning above and acceleration below. She wants it in the field but only after the frames show that realised volatility near high-OI strikes is lower in the "positive gamma" state. Until then: display, not decision.
4. The earliest *structural* tell of a break is OI at the wall strike *falling* while volume at that strike rises and its premium rises faster than delta explains: short covering. "Unwinding at the wall = fuel being released."
5. Max pain is a weak attractor into Tuesday expiry; she proposes it as an expiry-day destination candidate only. **[HYPOTHESIS]**

**Tomasz (keeping the metaphor honest).**
1. In meteorology the pressure gradient *is* the force. In a market, price is one point, not a fluid, and what people call "pressure" is mostly *resistance*: how much aggressive volume it costs to move price through a level. Resistance does not push; it stops. What pushes is **net aggressive flow** — a flux, in contracts per second. So the honest decomposition is three quantities: a **resistance field R(x)** (barrier height), a **stored-energy field U(x)** (what is forced to trade if x is crossed: hedges, covering, stops), and a **flux F(t)** (the wind itself). "High pressure" in the owner's sense is high R *and* high U at the same place — a dam: it holds water and, when it cracks, the water goes to the valley. "Low pressure" is low R: the valley.
2. Everything in R and U must be in **one unit** or the composite is a story. He proposes *Nifty-futures-equivalent contracts*: for R, "contracts of aggressive flow needed to traverse this bin"; for U, "contracts of forced flow released on crossing it". Depth is already in that unit; an OI wall converts via the hedge ratio (Γ × OI × hedger-fraction); a volume node via how much volume it took to cross it last time; a battle-tested level via the volume it absorbed. With one unit, R/F is a time — an **ETA to the destination** — which is a real number the screen can show.
3. Direction is the gradient: wind only "blows" in a direction where R immediately ahead is lower than R behind. If both sides of the current price are low, the metaphor gives no direction and the system should say so.
4. The hedger fraction h and the covering fraction c are unknown constants; he insists they are fitted from recorded breaks, published with their uncertainty, and never hand-set.

**Arjun (volatility as stored pressure).**
1. IV is not a level quantity; it is a *regime multiplier* on the whole field. Compressed IV (ATM IV low versus 15-min realised, straddle narrowing, skew flat) with positioning building = the coil: pressure stored, wind not yet blowing. Elevated IV after a move = pressure already released; the option buyer who enters then pays for a wind that has blown.
2. Per-strike IV versus its neighbours is a tick-cadence tell (premiums tick; OI prints do not): a wall strike whose IV lifts above the smile before its OI moves is being *bid* — market-makers reprice before the exchange's OI print catches up. His claim, testable on the frames: at the wall strike, IV rises before OI falls.
3. The "too late by vol" rule: if ATM IV has risen more than ~1.5 vol points since wind onset, the premium carries a vega load that deflates at the first pause — one mechanism of the owner's "it pulls back right after I enter" **[OWNER, historical]**.
4. Skew tilt tells where the crowd has already bought insurance: puts bid = the down move is positioned (late if you buy puts); a surprise up move against heavy put writing has covering fuel. Use skew as the "already positioned → late" check, not as direction.
5. On expiry day the field is dominated by theta and charm after ~13:00; "pays" arithmetic must be recomputed with live theta per minute, not a morning prior.

**Elena (auction market).**
1. The market profile already has the owner's vocabulary: the **point of control** and **value area** (70% of volume) are acceptance — high resistance; **single prints, low-volume nodes and gaps** are rejection — price crossed them fast and will cross fast again. An **unfinished auction** (a session high or low made without excess, i.e., no rejection tail) is a magnet: the auction will come back to finish. These are destinations the chain cannot see.
2. Build the profile from Nifty futures `ttq` differences binned by price at tick cadence, keep a decayed multi-session composite, and classify every bin; prior-day high/low/close, the opening range and VWAP/anchored VWAP are the anchors.
3. Her wind is *initiative versus responsive* activity at the edge of value: responsive flow fades back into value (a gust); initiative flow leaves value with expanding volume and *rising price efficiency* — more points per contract traded — which is literally "entering the low-pressure zone". Efficiency is observable on the futures at tick cadence and, degraded, in the 1–2-s frames.
4. She disagrees that OI walls are the primary structure: on many sessions price ignores option strikes and respects yesterday's value-area edges. Which stalls price more often is an empirical question for the frames; neither should be assumed.
5. Voids are fast *both* ways. A destination void is not a place price rests; the trade must exit at the far wall or when the wind turns, never on a clock.

**Kavita (features, change-points, persistence).**
1. The field is a fixed grid, not a list: spot ± 600 pts in 5-pt bins (241 bins) for Nifty; per-contributor arrays with an *age* each; the composite recomputed only for bins whose inputs changed. Stocks use relative bins (0.05% of price) so that the basket overlay maps into percent-move space.
2. Wind is a **change-point** problem, not a vote. One signed composite flux series per direction, a CUSUM on it, and *amplifiers* (structure change at the wall, basket participation, IV lift) that scale the flux so that the CUSUM crosses *sooner* when structure agrees — never a k-of-n gate that waits for everything to line up. The owner's objection to voting **[OWNER]** is also a statistical objection: MYTHOS's 14 evidences were collinear (all downstream of the same price move) and anti-predictive (config.py 492–499).
3. Zone persistence is survival analysis: the hazard of a zone breaking given its strength, tests, age and OI trend. MYTHOS's constants (α 0.25, 8%/day, 10 days) are usable priors because they are sensible, not because they were validated — they never gated a trade.
4. The validation trap is leakage: an OI sample stamped 10:31:30 may describe the chain *after* the 10:31:00 break. Every feature must be computed only from data whose timestamp precedes the event it predicts, with the REST latency added.
5. Thirty sessions cannot support a ten-input composite. Freeze to three families (flow, basket, wall-structure), hand-set priors, test, then add. And synthesise FinNifty from its constituents since no Breeze code works for it **[FACT, brief §2.1]** — we track the names anyway.

## 4. The debate

**4.1 Is "pressure" a barrier or stored energy? (Tomasz vs Priya.)** Priya: the owner means the crowded side that must unwind. Tomasz: that is potential energy; what stops price is resistance. Both are right about different numbers. **Decided:** two fields, R (resistance) and U (fuel), kept separate, in the same unit, shown side by side. A wall is R while it holds and U when it cracks. Evidence that would settle it: none needed — it is a definition.

**4.2 OI walls or the volume profile as the primary structure? (Priya vs Elena.)** Decided: neither is assumed. Both contribute to R; the weights come from the stall statistics on the recorded frames (§6.1 study A): for each candidate level type, how often did price reverse within 25 pts of it versus pass through? If option walls stall more often than value-area edges, they get the higher prior weight, and the reverse. Until measured, equal weights.

**4.3 What is the earliest tell? (Priya: OI unwinding; Arjun: IV at the strike; Elena: efficiency; Kavita: flow + basket synchrony.)** The brief is explicit that constituent flow leads the Nifty print by seconds, not minutes **[ANALYSIS, brief §5.3]**. The OI print's own cadence is unknown — the WS tick carries an `OI` field **[FACT]** but whether that field changes per trade or on an exchange dissemination interval is unmeasured. **Decided:** the trigger uses only inputs that are observable at tick cadence (flow, basket, basis, premiums/IV, depth via G3); OI is an *amplifier* when it is fresh and *context* when it is not. The frames study C (§6.1) measures the lead ordering of all four and settles who is right.

**4.4 One statistic or a vote?** Everyone agreed with the owner, for the statistical reason in §3 (Kavita 2). The pays-arithmetic and the gradient check are *not* votes: they are accounting (can this trade pay if it is right?) and geometry (is there a valley ahead?). They refuse only trades that cannot pay even when correct.

**4.5 Is the basket overlay legitimate? (Tomasz as skeptic.)** A single stock's wall mapped through its index weight is almost nothing: HDFC Bank at 10.38% moving 1% is ~24 Nifty points **[FACT, weights brief §4]**, and that assumes nobody else moves. Tomasz: overlaying stock walls on the Nifty price axis by weight is a category error. Kavita's reformulation carried the room: map in **percent-move space with beta** — "if Nifty rises 0.8%, where will each heavyweight be, and what resistance does *it* meet there?" — and weight-sum those resistances. That is a *conditional* field, valid for broad moves and wrong for rotations (banks up, IT down). **Decided:** the overlay is built that way, carries a "breadth validity" number (fraction of weight moving with the index over the last 5 minutes), and when the chain field and the overlay disagree, the *nearer* wall sets the destination (conservative target) and the disagreement is shown, not vetoed. Study B (§6.1) measures which field predicts stalls better.

**4.6 Hold duration.** Elena: a wall-to-wall leg on Nifty takes 10–40 minutes; the owner's hand habit is 5–7 minutes **[OWNER, historical]**. The sail metaphor implies holding to the destination. Not ours to decide — open question §9.1; G6 owns exits.

**4.7 What survives expiry?** Priya: OI walls die at 15:30 Tuesday and are rebuilt, often at the same round strikes, by Wednesday noon. Elena: the *price* memory outlives the options that made it. **Decided:** the level persists in memory with its OI contributor zeroed and its test history intact; a new wall at the same strike inherits the test history. The first 60–90 minutes of a new weekly are flagged "field forming".

**4.8 Max pain and GEX.** Tomasz: stories until measured. Priya: stories with testable predictions. **Decided:** both on screen, neither in the trigger, both in the frames study (pinning versus positive-gamma state; distance of expiry close to max pain). With ~15 expiry sessions in the archive this will not settle quickly; carried as hypotheses.

## 5. Consensus proposal

### 5.1 What this subsystem is

A per-instrument **pressure map** — two fields over price, R (resistance) and U (fuel), built from the order book, the option chain, the volume profile, positioning and cross-session memory — plus a **wind detector** that watches for flux leaving a high-R zone toward a low-R zone, plus a **sail calculator** that names the destination, the remaining distance, and whether an option bought now can pay for the trip. It publishes zones for G3 to test, consumes G3's hold/break verdicts to update them, and publishes a `SailCandidate` for the trigger fusion. It never places an order and never gates one except by the pays arithmetic.

### 5.2 A day in its life (Nifty, a non-expiry day)

- **08:50** Load the memory ledger (levels, tests, strengths, the decayed multi-session volume profile). Decay untouched levels. Fetch the first chain. Mark the field *forming*.
- **09:15–09:30** Build today's grid: prior-day H/L/C, overnight gap bounds, chain walls, memory levels. Confidence is low: OI is noisy at the open and the profile is empty. The screen says "forming"; no sail until the opening range closes (09:30, **[HYPOTHESIS]** 15 min; the old system used 10:00).
- **10:05** Spot 23,085 approaching the 23,100 CE wall (R high). Beyond it the map shows a void to 23,240 (yesterday's unfinished high, held twice in memory) and the next CE wall at 23,300. G3 is told: *watch 23,100, kind = OI_CE + ORH, strength 0.62.*
- **10:07:15** Wind stirs. Flow: Nifty futures CVD z = +2.1. Basket: 0.68 of index weight rising with volume above baseline (banks + RIL), from G1. Amplifiers: G3 reports asks at 23,100 CE being pulled (π = 0.35, ρ = 0.4); 23,100 CE OI −2.4%/min on the WS field; 23,100 CE IV +0.6 vol pts over 60 s. Gain 2.8×. The up-CUSUM crosses h in 6 s.
- **10:07:21** Gradient check: R ahead (23,100 bin, now eroding) < R behind (today's value 22,950–23,020). Destination = nearest high-R beyond the wall = 23,240. D_rem = 155. Pays? ATM 23,100 CE: M_req ≈ 31 (§5.6); κ·M_req = 40 ≤ 155. Leg consumed 0%. IV rise since onset 0.3. **SAIL ↑ → 23,240** published with the why-text. G4 picks the contract; G6 works the limit.
- **10:09–10:18** Price runs the void. Efficiency (pts per contract) rises then falls near 23,230. G3: 23,240 testing, ρ = 1.3 (refilling), verdict HOLD-STRONG. G2 publishes *destination reached, wind fading* to G6.
- **15:30** Fold: 23,100 broke → role flips to support at strength ×0.35; 23,240 held → strength up; today's profile merged into the composite; the ledger is written.

### 5.3 The field — contributors, units, cadence

Grid: Nifty, spot ± 600 pts, 5-pt bins. Stocks and sisters: relative bins of 0.05% of price. Each contributor is an array over the grid with its own timestamp; the composite R and U are recomputed for changed bins only. Unit for R and U: Nifty-futures-equivalent contracts (Tomasz, §3). Hedger fraction h ∈ [0.2, 0.6] and covering fraction c ∈ [0.2, 0.5] are **[HYPOTHESIS]** to be fitted.

| Contributor | Field | Formula (per bin x) | Source | Cadence | Decay / invalidation |
|---|---|---|---|---|---|
| Resting depth (near field) | R | resting qty in bin / lot | Nifty futures 5-level depth: `BestBuyQty-N`, `BestSellQty-N`, order counts | tick | state, not memory: invalid after 2 s; only the ~5 ticks around spot are visible |
| OI wall, barrier | R | h × Γ_K × OI_K × 1 pt / lot, if OI_K ≥ max(2.0× [1.8–3.0] mean of K±1..3, top-quartile OI within ATM±10) | WS `OI` on subscribed strikes ATM±8; REST chain every 90 s beyond | tick (cadence unmeasured) / 90 s | re-scored on every OI update; zero at expiry; the level survives in memory |
| OI wall, reservoir | U (beyond K) | c × OI_K / lot | same | same | same |
| Dealer gamma (GEX) | R above / U below | Σ Γ × OI × sign(convention) | REST chain + solved IV (G4) | 90 s | display-only until study D passes |
| Volume node, today | R | volume traded in bin / bin width (contracts per point) | Nifty futures `ttq` differences binned by LTP | tick | none intraday; merged at EOD |
| Composite profile | R | Σ_sessions w^age × volume per point, w = 0.7/day [0.5–0.85], 5 sessions | ledger | at open | decays by age |
| Void / single print | R (low) | ≥ 3 consecutive bins with density < 0.3× [0.2–0.4] session mean and no wall and no memory level | derived | per profile update | filled when volume accrues |
| Prior-day H/L/C, OR H/L, gap bounds, unfinished extremes | R | fixed small R plus memory strength | computed at open / 09:30 | static | gap bound removed once filled |
| Battle-tested memory | R | volume absorbed in held tests × strength s | ledger (§5.7) | on test outcomes | 8%/day [5–12] untouched; evicted at s < 0.05 or 10 days |
| Positioning cost basis | U | OI added over window × fraction underwater if x crossed, f ∈ [0.1–0.3] | Nifty futures `OI` + LTP; Tier-1 stock futures OI | tick | rolling 30-min window |
| IV regime | multiplier on U | ATM IV / 15-min realised; skew (25Δ put − call); 1-min EWMA | solved IV on hero contracts (G4); VIX REST 1/min | tick / 60 s | regime, not level |
| Basket overlay | R_b, U_b | Σ_i w_i × R_i(p_i(1 + β_i (x/N − 1))) over Tier-1 names, same for U | per-stock fields (cash profile at tick, futures OI at tick, monthly chain by REST every few minutes) | ~1 s coalesced | carries breadth validity b ∈ [0,1] |
| Sister fields | R_s, U_s | BankNifty field mapped by β 1.15 **[FACT]**; FinNifty synthesised from its top-10 constituents (86% of weight) | BankNifty spot/futures ticks + monthly chain | tick / minutes | same |

**Tick cadence:** depth, flow, premiums → IV, futures OI (if the field moves per tick — to be measured), basket cash ticks, basis, book totals. **Only every ~90 s or slower:** chain OI beyond ATM±8, GEX, VIX, heavyweight and sister chains.

### 5.4 Combining the Nifty complex and the basket

```
R_total(x) = R_chain(x) + λ_b · b · R_b(x) + λ_s · R_s(x)        λ_b, λ_s ∈ [0.3, 1.0]  [HYPOTHESIS]
U_total(x) = U_chain(x) + λ_b · b · U_b(x) + λ_s · U_s(x)
disagree(x) = |rank(R_chain, x) − rank(R_b, x)|  → shown as a hatched band, never a veto
destination(d) = nearest bin beyond the current wall where R_total ≥ wall threshold, from EITHER field (the nearer wins)
```
b is the breadth validity: fraction of index weight whose 5-min return has the index's sign. When b < 0.5 the overlay fades on screen and λ_b·b makes it nearly inert — a rotation day has no basket field, and that is correct.

### 5.5 Wind — the detector

Two instances, d ∈ {up, down}. Per second (coalesced from ticks):

```
z_flow  = z(CVD slope 5 s, Nifty futures)        vs 20-min robust baseline (median/MAD), signed toward d
z_bask  = z(weighted basket impulse 15 s)        from G1, signed toward d
z_basis = z(basis velocity 15 s)                 signed toward d
phi     = 0.5·z_flow + 0.35·z_bask + 0.15·z_basis           [weights HYPOTHESIS; equal weights is the fallback]
gain    = Π amplifiers, each 1.0 when absent:
          wall_unwind : OI at the wall ahead falling ≥ 2%/min [1–4]            → 1.5
          depth_pull  : G3 π ≥ 0.3 at the wall ahead                            → 1.5
          synchrony   : G1 synchrony ≥ 0.6 of weight [0.5–0.75]                 → 1.5
          iv_lift     : wall-strike IV +0.5 vol pt / 60 s [0.3–0.8]             → 1.25
          efficiency  : pts per contract (15 s) ≥ 1.5× its 20-min median        → 1.25
S_d     = max(0, S_d + gain·phi − k),  k = 0.5     [drift; range 0.3–0.8]
WIND(d) when S_d ≥ h,  h ∈ [4, 8]
reset   : phi changes sign for 3 s, or S_d has been > 0 for 30 s without crossing (stale wind = chop)
```
Confirmation time is a consequence, not a parameter: at a steady phi = +1.5 with no amplifiers it is ~5–8 s; with structure agreeing, 2–4 s; a gust of +3 for 2 s then nothing reaches ~5 and decays — it never crosses h = 6. That is the gust/wind distinction in one line: **persistence, participation, structure response, and price efficiency.** A gust hits a wall and the wall refills (G3 ρ ≥ 1); a wind erodes it (ρ < 0.5). A gust shows flow with little price progress (absorption); a wind shows rising efficiency (the valley). The detector is direction-agnostic about *why*: at a holding wall (G3 HOLD-STRONG) with flow turning away, the same CUSUM fires *away* from the wall — the rejection sail, MYTHOS's bounce without the four late rails.

### 5.6 Set sail — the trigger and the "too late" arithmetic

```
SAIL(d) fires when ALL of:
  WIND(d)                                              the detector, §5.5
  gradient: R_total just ahead (next 30 pts) < R_total behind, OR the wall ahead is BREAK-IMMINENT/BROKE per G3
  destination exists: next R-high beyond, distance D_rem
  pays: D_rem ≥ κ · M_req,  κ = 1.3 [1.2–1.6]
  not late by progress: leg_consumed = (spot − leg_start)/(destination − leg_start) ≤ 0.6 [0.5–0.7]
  not late by vol: ATM IV rise since wind onset ≤ 1.5 vol pts [1.0–2.5]
M_req = (T + θ_min · H + s) / Δ_eff            brief §5.4 **[ANALYSIS]**
  T      target in premium points (owner's historical +12 is a placeholder — §9.3)
  θ_min  live theta per minute from G4 (not a morning prior; recomputed on expiry day)
  H      projected hold = D_rem / v_proj, v_proj = recent impulse speed, floor 5 pts/min
  s      spread + 1 pt honest-fill drag (measured ~2 pt/trade  **[FACT, brief §3.2]**)
  Δ_eff  Δ + ½ Γ · D_rem (delta grows as the option goes ITM)
```
The gradient check and the pays rule are not evidence votes; they refuse only a trade that cannot pay even if the wind is real. The leg-consumed cap exists because void runs often stall before the far wall **[HYPOTHESIS; study A measures the run-length distribution]**.

**Worked example, Nifty 23,000, 50-pt strikes, Wednesday 10:40.** Walls: 22,900 PE (R high), 23,100 CE (R high, reservoir U large), 23,300 CE. Memory: 23,240 = yesterday's unfinished high, held twice, s = 0.70. Profile: today's value 22,950–23,020; a void 23,120–23,230 (yesterday's single prints). Spot 23,085; wind up confirmed with wall_unwind and synchrony amplifiers.
- Destination = the nearer of 23,240 (memory) and 23,300 (chain) = **23,240**. D_rem = 155. Leg start = 23,100 (the wall), leg = 140.
- Contract (G4's call, but for the arithmetic): 23,100 CE, premium ~115, Δ 0.48, Γ such that Δ_eff ≈ 0.55 over 150 pts; θ_min 0.3 (brief prior, G4 replaces with the live value); H = 155 / 12 pts-per-min ≈ 13 min → θH ≈ 4; s = 2; T = 12 → M_req = (12 + 4 + 2)/0.55 ≈ **33**. κ·M_req = 43 ≤ 155: **pays**, with 3.6× headroom. At ₹115 × 65 = ₹7,475/lot, ₹1,00,000 buys 13 lots (sizing is G6's).
- Latest entry by arithmetic: 23,240 − 43 ≈ 23,197. Latest entry by progress: 23,100 + 0.6 × 140 = **23,184**. So the sail window is spot 23,085 → 23,184; in premium terms the same CE costs ~115 at the bottom of the window and ~175 near the top, and the buyer at the top needs 23,215+ with the far wall only 55 pts away. The window is the first ~100 pts of a 155-pt trip; after that the ship stays in port.
- **Variant — late because the tell came by REST:** the wall-unwind amplifier arrives from the 90-s chain at 10:52 with spot already 23,200. D_rem = 40; Δ of the 23,100 CE is now 0.75 → M_req = (12 + 2 + 2)/0.75 ≈ 21, κ·M_req = 28 ≤ 40: the arithmetic *passes*. Leg consumed = 100/140 = 71% > 60%: **no sail**. ATM IV is also +1.8 since onset: **no sail** twice over. This is exactly the trade MYTHOS took.
- **Expiry-day note (Tuesday 14:30):** θ_min can be 1–1.5 **[ANALYSIS, brief §5.4 prior]**; H = 13 min → θH ≈ 15–20; M_req balloons to ~60 and most sails fail the pays rule after lunch — which is the owner's expiry caution **[OWNER, historical]** made numeric.

### 5.7 Zone bookkeeping and the data model

```
Zone      id, instrument, price, half_width (10 pts Nifty / 0.1% stocks), kinds {OI_CE, OI_PE, HVN, LVN, POC, VA_HI, VA_LO, PDH, PDL, PDC, ORH, ORL, GAP, UNFINISHED, MEM, BASKET, SISTER}
          R_contracts, U_contracts, strength s∈[0,1], tests_held, tests_broken, absorbed_qty, first_seen, last_test, role {support, resistance, both}, age_s, provenance, g3_state
Field     instrument, t, grid_lo, step, n, R[n], U_up[n], U_dn[n], contrib[k][n], age[k], b (breadth validity), status {forming, live, stale}
Wind      d, S_up, S_dn, phi, gain, components {flow, basket, basis, wall_unwind, depth_pull, synchrony, iv_lift, efficiency} each with age, state {calm, stirring, wind, reset}, onset_t
Sail      d, entry_spot, destination zone id, D_rem, leg_start, leg_consumed, M_req, pays, iv_rise, flags, why_text, t
Ledger    per instrument per day: zones (as above) + session profile + test events (t, zone, attack volume, outcome)
```
Life cycle: **created** when a contributor crosses its threshold (wall, node, void edge, anchor) or at open from memory; **tested** when price is within the half-width with aggressive flow toward it ≥ 1.5× baseline (G3 owns the test itself); **strengthened** on a held test: s ← (1−α)s + α·min(1, absorbed/absorbed_ref), α = 0.25 [0.15–0.4]; **weakened** immediately when its OI or depth contributor falls (that *is* the wind); **invalidated** on a break: price beyond by ≥ 25 pts [20–35] for ≥ 60 s [30–120] → role flips, s ← 0.35·s, the reservoir U is released; **persisted** nightly; **decayed** 8%/day untouched; **evicted** at s < 0.05 or after 10 days [7–20]; **inherited**: a new weekly wall at a remembered level takes the old test history. Nothing in the ledger is written from the hot path (the old copy-and-enqueue daemon pattern **[FACT, memory.py]** is reused).

### 5.8 What the screen shows

- **Pressure map per instrument** (canvas, vertical price axis, current price as a line): R as bars to the left, U as bars to the right, zones as labelled ticks with strength and test count, voids as empty bands, memory levels in a muted colour with their age, chain OI as a thin histogram behind. Ages grey a contributor out past its horizon.
- **Nifty map with the basket overlay**: three translucent layers — chain, basket (fading with b), sisters — and hatched bands where they disagree; the destination marked with D_rem, the ETA (Σ R ahead / F, a display aid **[HYPOTHESIS]**) and the pays badge.
- **Wind gauge**: direction arrow, S/h as a filling bar per direction, the components as mini-bars with ages, the amplifiers lit when active, the reset reason when it resets.
- **Sail panel**: "SAIL ↑ → 23,240 · 155 pts · pays 3.6× · leg 0% · IV +0.3 · why: flow +2.1z, banks+RIL 68%, 23,100 CE OI −2.4%/min, asks pulled" — the owner's "why this trade" **[OWNER]**.
- **Event tape with audio only on state changes**: wall forming, wall unwinding, wind confirmed, sail, destination reached, wind reversed.
- Thumbnails for BankNifty, synthetic FinNifty and the Tier-1 names.

### 5.9 Data flow (G5's layout, brief §5.1)

FEED → shared-memory latest-state table and ZeroMQ PUB → **G2 worker** (SUB with conflation) maintains the grids in numpy, publishes `pressure.field` (coalesced 250 ms or on change), `pressure.zones` (on change), `pressure.wind` (per second while stirring, per tick while wind), `pressure.sail` (on fire) → GATEWAY → browser; `pressure.zones` → G3; `pressure.sail` → trigger fusion (G4/G6). G3's `force.verdict` and G1's `basket.impulse` / `basket.synchrony` come back on the same bus. Nothing in G2 touches the tick path.

## 6. Validation plan

**Data **[FACT, brief §3.5]**:** frames at 1–2 s for 30+ sessions since 12 Jun 2026 with spot, futures, near-ATM option ltp/bid/ask/OI/volume, heavyweight cash LTPs, sister LTPs, VIX; Nifty chain per strike every ~90 s; heavyweight chains since ~1 Jul every ~4.7 min; no depth; intra-frame tick order lost. Honest ceiling: at this resolution we can test whether wall-unwinding precedes breaks on a *minutes* scale and whether flow/basket synchrony precede on a *tens-of-seconds* scale. We cannot test depth-pull tells or anything inside 2 s.

**6.1 The recorded-frames study (pre-registered, thresholds frozen before the run).**
- **A — Do zones stall price?** Every 90 s, build the zone set (walls, prior-day levels, OR, profile nodes from the futures LTP/volume, memory from prior sessions in the archive). A *test* = spot within 15 pts with the 60-s move toward it. Label *hold* (reverses ≥ 25 pts without exceeding by > 10 within 10 min) or *break* (≥ 25 beyond, held 60 s). Report per zone kind: hold rate, and the void-run length after breaks (distance to the first 25-pt reversal). Outputs the prior weights for §4.2 and the leg-consumed cap for §5.6.
- **B — Chain field versus basket overlay.** Rebuild both fields from the frames (heavyweight chains and cash LTPs, since July). For each stall in A, which field had the nearer R-high? Score each by distance-to-actual-stall.
- **C — Can wind be seen before the break?** For every test in A, compute at each second in the 5 minutes before resolution, using only data stamped earlier: CVD proxy (1–2-s tick rule on futures LTP and volume), basket impulse and synchrony, basis velocity, ATM IV change (solved from LTP), wall-strike IV versus neighbours, wall-strike OI change (last two REST samples, with their latency), efficiency. Report AUC per feature for break-versus-hold, the composite's AUC, and the **lead time** distribution: seconds from the composite crossing h to the 25-pt break. The ordering of lead times settles §4.3.
- **D — GEX and max pain.** Realised 5-min volatility within 30 pts of high-OI strikes in "positive gamma" versus "negative gamma" states; expiry-day close distance to max pain. Carried as hypotheses; ~15 expiry sessions will not settle D.
- **E — Does the sail pay?** Walk-forward: calibrate h, k, κ, the leg cap and the IV cap on the first 15 sessions, freeze, apply to the rest. Simulate each SAIL with honest fills from the frame's ask/bid on the ATM contract, exit at destination-reached or wind-reset, costs included. Report expectancy per sail, the 95% bootstrap interval, and the result with the best day removed (the brief's own test **[FACT, §3.3]**).

**6.2 Live tick-recorder probe (no orders).** Subscribe the ten hero contracts + Nifty and BankNifty futures with depth and record raw messages with receive time and `ltt`. Measure: how often the `OI` field on a tick *changes* (per trade, or on an interval — the single fact this group most needs); whether NFO depth carries order counts; the true update cadence of premiums versus futures; depth message weight at the open. Add to the recorder: every tick (not frames), per-tick OI with a change flag, `totalBuyQt`/`totalSellQ`, `ttq`/`ltq`, Tier-1 cash and futures ticks with OI, every REST chain with its request and response times, VIX per minute, and a derived zone-event log (creation, test, outcome) so A can be rerun on tick data.

**6.3 The bar before this subsystem may influence a real order.** All of: (i) study A shows at least one zone kind with a hold rate distinguishable from 50% at p < 0.05 over ≥ 150 tests; (ii) study C shows the composite's median lead time ≥ 20 s before the 25-pt break with AUC ≥ 0.65 out of sample; (iii) study E's out-of-sample expectancy per sail is positive after costs with the bootstrap interval excluding zero *and* stays positive with the best day removed; (iv) ten live shadow sessions on the tick recorder, calls logged with no orders, reproducing (ii) and (iii) at live cadence; (v) G7 has reviewed the pre-registration and the leakage controls. First live use is then at the smallest size G6 allows, not all-in, for a further ten sessions.

## 7. Risks and failure modes

- **Late again, by construction.** If the wind detector leans on the 90-s chain, it is minutes late (§5.6 variant). If "confirmation" becomes k-of-n, it is the vote the owner retired. Defences: tick-cadence inputs only in phi; OI as amplifier/context; the CUSUM is the only confirmation; a 30-s staleness reset.
- **Wrong with confidence: the two-sided-OI trap.** A "wall" of long-call speculators does not resist; it fuels. If the frames show walls stall price no better than chance, the OI contributor to R is demoted to U only. OI walls are also the most-watched structure in Indian index options — the edge, if any, is in *when* a wall cracks, not in knowing it exists. The screen will still *look* authoritative; the age/confidence rendering and study A are the only antidotes.
- **A pretty field is not a measurement** (Tomasz). The hedger fraction h, covering fraction c and stop fraction f are fitted constants with wide uncertainty; show the uncertainty, never a single ETA without it.
- **Basket overlay on rotation days** — wrong by construction; b must gate its weight and the screen must fade it.
- **Spoofed and far depth** — book totals include far orders **[ANALYSIS, brief §5.5]**; near-touch and order counts carry the truth.
- **Expiry structure**: walls pin then evaporate after ~13:00 Tuesday; the new weekly's field is thin Wednesday morning. Status *forming* and the live-theta pays rule handle it; a sail in the last 90 minutes of expiry needs the owner's answer (§9.2).
- **Stale chain shown as live** — the REST freeze **[FACT, brief §3.2]**: signature watchdog and ages; a stale contributor greys out and drops from R.
- **The OI tick cadence is unknown.** If OI only moves on an exchange interval, "unwinding at tick cadence" is fiction and the amplifier is REST-slow; the probe in 6.2 decides before any design depends on it.
- **Overfitting thirty sessions** with ten inputs; three families, frozen priors, walk-forward, and the best-day-removed test.
- **Voids are fast both ways** — a destination is where to *exit*, not where price rests; exits on wind-reset, not on clocks (G6).

## 8. Interfaces

- **G1 (domino & lag)** → G2: `basket.impulse` (Nifty-point-equivalent, 15 s), `basket.synchrony` (fraction of weight), lead–lag table, the β_i used in percent-space mapping (one shared table). G2 → G1: the destination and D_rem so a lag entry has a target; the percent-space zones of each heavyweight (a stock's own wall is where its domino may stop).
- **G3 (force)** ← G2: `pressure.zones` — the nearest 2–3 zones above and below per instrument with kinds, R, U, s, tests, role; G3 runs `idle → approaching → testing → holding | breaking | broke | rejected` on them. G3 → G2: per zone `force.verdict` {state, ρ, π, A, absorbed, verdict, confidence} at tick cadence; G2 uses ρ/π as wind amplifiers, verdicts as test outcomes for the ledger, and BREAK-IMMINENT/BROKE to satisfy the gradient check at a wall.
- **G4 (Greeks)** → G2: per hero strike Δ, Γ, θ per minute, IV; ATM IV, skew, straddle; GEX per strike. G2 → G4: the `SailCandidate` (d, D_rem, H) for contract choice. Contract selection is G4's; M_req is computed with G4's numbers.
- **G5 (platform)** → G2: the SUB feed with conflation, shared-memory latest state, the recorder capturing §6.2's list, the REST budget slice (the chain poller stays at 2 calls/90 s; nothing new from G2). G2 → G5: topic schemas above, the canvas panel spec, the ledger file format and its daemon writer.
- **G6 (execution)** ← G2: `pressure.sail` with the why-text, `destination.reached`, `wind.reset` and `wall.refilling` as exit *hints* (G6 owns the exit); the pays arithmetic's inputs for its own sizing check. G6 → G2: fills and exits so the ledger records what the sail actually earned per zone.
- **G7 (red team)**: the pre-registration in §6 is theirs to shred before it runs.

## 9. Open questions for the owner

1. Will you hold to the destination when the leg takes 10–40 minutes, or should the sail target the first ~100 pts of a void only? (Assumed: hold to destination or wind-reset, G6's trail.)
2. Expiry afternoons: no sails after 13:00, or sails with the live-theta pays rule only? (Assumed: pays rule only.)
3. The target T for the pays arithmetic: is +12 premium points still your number, or should the destination set T? (Assumed: destination sets T, +12 as the floor.)
4. Rejection sails (price bounces off a holding wall) — do you want them, given MYTHOS's bounces were its losers? (Assumed: yes, but only with G3 HOLD-STRONG and the same wind detector.)
5. Memory horizon: 10 trading days with 8%/day decay, 20 days for levels held twice or more? (Assumed as stated.)

## 10. One-paragraph summary for the master design

G2 turns the owner's metaphor into two measured fields over price per instrument — **R**, the resistance to movement (depth, OI walls scaled by hedging, volume nodes, battle-tested memory) and **U**, the fuel released when a level breaks (writer covering, short-gamma hedging, trapped positioning) — both in Nifty-futures-equivalent contracts, on a 5-pt grid with per-contributor ages; the Nifty field combines the chain with a beta-mapped, breadth-weighted basket overlay and the BankNifty sister, disagreement shown not vetoed. **Wind** is a CUSUM on one signed flux composite (futures CVD, basket impulse, basis) whose gain is amplified — never gated — by structure changes (wall OI unwinding, depth pulled, synchrony, wall-strike IV lift, price efficiency); it confirms in 2–8 s and a gust decays before crossing. **Set sail** fires toward the lower-R side when a destination (the next R-high) exists and the remaining distance pays — D_rem ≥ 1.3 × (target + live theta × hold + spread)/Δ_eff — and refuses when more than ~60% of the leg is consumed or ATM IV has risen > 1.5 points since onset: at Nifty 23,000 that is a ~100-pt window on a 155-pt trip. Zones are created, tested (G3), strengthened, flipped on break and persisted nightly with decay. Nothing here may touch a live order until the pre-registered frames study shows zones stall price, wind leads breaks by ≥ 20 s out of sample, and simulated sails pay after costs with the best day removed, followed by ten shadow sessions on the tick recorder.
