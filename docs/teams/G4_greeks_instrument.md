# G4 — Options, Greeks & Instrument Selection

*Working-group report for the ApexOptions master design. Chair: G4. Date: Saturday 17 Oct 2026. Sources read in full: `00_CONTEXT_PACK.md`; `mythos/greeks.py`; `mythos/trader.py` 1–420; `mythos/config.py` 290–420 (plus the expiry functions at 184–230 and the exit constants at 905–930); `MYTHOS_HOW_TRADES_ARE_TAKEN.md`; `KILL_CRITERION.md`. All numbers below were computed with a Black-76 pricer on a forward at Nifty 23,000, lot 65, ₹1,00,000, and are reproducible; the script is referenced in §6.*

Tags as in the brief: **[FACT]** verified in code/docs · **[OWNER]** the owner's words · **[ANALYSIS]** our reading · **[HYPOTHESIS]** must be tested before trusted.

---

## 1. Members and their lenses

- **Dr. Sunita Rao** — derivatives quant: pricing model and forward choice, IV solver numerics, Greek identities, dealer-gamma construction and its hidden assumptions, what breaks as T→0.
- **Marco Vitale** — discretionary Nifty weekly buyer: what actually pays in a 3–10-minute hold, why ATM buyers bleed (it is not theta), strike liquidity as it really trades, expiry-week habits.
- **Farah Khan** — risk manager: buyer-only loss paths, the rupee arithmetic of all-in sizing, streak and ruin probabilities. Informs the owner's decision; does not override it.
- **Vikram Choudhary** — 0DTE specialist: gamma/charm/vanna on Tuesday, pin and unpin, dealer hedge unwind into 15:30, when Black-Scholes Greeks stop meaning anything.

---

## 2. What we were asked

**[OWNER]** *"I will only buy options. I will not sell them. Which is even more dangerous. So keep this in mind from the very start."* · *"How can we also leverage option greeks to take a better decision making during a BUY trigger. Be it a CALL or a PUT trade."* · ₹1,00,000 fresh daily, *"go all in every time it takes a trade… use the profits and again go all in."* Historical, to re-confirm: *"I need ATM or ITM which will MOVE"* (never OTM), a +10–15-point objective in a 3–10-minute hold, *"Nifty hunts stops right after entry"*.

Our reading **[ANALYSIS]**: the Greeks are not a seventh voter in an evidence gate (the owner hates gates that "kill all the moves"). They answer four things when G1/G2/G3 say *a move is forming*: **(i) which contract turns it into rupees with the least that can go wrong**, **(ii) can that contract pay the target inside the hold, after rent and spread**, **(iii) is the premium already carrying the move — are we late**, **(iv) what exit plan the instrument implies**. The engine ranks and sizes; it vetoes only on "late" and "already priced", and only after earning that right (§6). We keep the brief's §5.4 questions, change two of them (§4), and reject one of its numbers.

---

## 3. Ideas by member

### Dr. Sunita Rao — the engine
1. **Price on the forward, not spot.** Index options trade off the forward to *their* expiry. Use the **synthetic forward from ATM put–call parity**, F = K_atm + C_mid − P_mid (averaged over ATM±1 when both quote), sanity-checked against the futures mid (|F_syn − F_fut| < 15 pts), with futures mid as fallback and spot×carry as last resort. Black-76 then needs r only for discounting (negligible intraday). This removes the basis bias that spot-based pricing injects into IV and skew, and the forward ticks with the options themselves rather than lagging with the cash index.
2. **greeks.py has a validity bug for ITM puts.** **[FACT]** `implied_vol` marks a quote invalid when `price ≤ max(K−S,0)+0.05` using *spot* intrinsic, while its own BS put can legitimately trade down to `K·e^{−rT} − S`. With 6 days left, `K·rT ≈ 23,100×0.065×6/365 ≈ 24.7` pts — so any ITM put with less than ~25 pts of spot-measured extrinsic is NaN'ed and falls to the deep-ITM fallback (Δ = −0.99, Γ = Θ = V = 0). It bites only on deep ITM puts far from expiry (second-order), but on a down day the "PE ITM that MOVES" is exactly our instrument; fix by testing against forward intrinsic.
3. **Solve IV from the mid, carry an uncertainty band.** LTP is stale between trades; mid is live. Band: ±(spread/2)/vega vol points. A crossed or locked book → IV invalid. Bisection stays (Newton diverges on deep OTM near expiry); 20 iterations on [0.01, 3.0] give 3/2²⁰ ≈ 3e-6 vol — more than enough; expiry day widens the bracket to [0.01, 5.0] because 0DTE ATM IV annualises to 50–100%+ in the last hour.
4. **Sticky-IV between solves = free P&L attribution.** Hold each contract's IV from the last solve, re-price with the new forward on every forward tick; the gap between the observed premium and the sticky-IV price *is* the vega/IV component. This gives the live decomposition ΔP = Δ·ΔF + ½Γ·ΔF² + V·Δσ + Θ·Δt + residual that §5 exits key on.
5. **The gamma/theta score is degenerate.** With r = 0, Θ/Γ = −F²σ²/2 for **every strike and every expiry** at the same IV (we verified numerically: −12,269 pts·pt² per day for all of 22,800…23,200 at 13%). A per-strike Γ/Θ ranking only re-ranks by IV smile. The real question is whether the *move* will beat the *rent*: break-even move over hold H is M_be = F·σ·√(H/525,600), the one-sigma implied move. Replace the score with the **speed ratio** ρ = M_proj / M_be. (Numbers in §5.)
6. **GEX needs an explicit sign assumption, and the standard one is probably wrong here.** Compute it, label it, and infer the *effective* sign from behaviour (§5.4e).
7. **Near expiry**: floor T at 600 s on expiry day (MYTHOS's fix was right), express Γ as "points per 25-pt move" and Θ as "points per 5 min" so the displayed numbers stay bounded, and raise an UNRELIABLE flag after 15:00 on expiry day when the ATM is effectively a binary.
8. **Verdict on reuse**: the *approach* in greeks.py (vectorised bisection, deep-ITM fallback, holiday-aware 15:30 expiry clock) is sound; the *module* must be rewritten: forward-based, `scipy.special.ndtr`/`erf` instead of `scipy.stats.norm` (10–50× less per-call overhead), theta in per-trading-minute units, charm/vanna/GEX added, no `config` globals (it runs in an analytics worker reading shared memory). 160 lines; rewrite is cheaper than retrofit.

### Marco Vitale — what pays a buyer
1. **In a 5-minute hold the ATM buyer does not bleed theta; he bleeds vega and spread.** A 6-day ATM at 13% IV (premium ~166) has vega ≈ 11.9 pts per vol point; IV ticking from 13% to 12% costs 11.9 pts with spot unchanged — an entire target. Theta over the same 5 minutes is 0.17 pts. The "pulls back after I enter" pattern is mostly "I bought the IV spike that the trigger itself created".
2. **IV-spike veto.** Never buy a contract whose IV has risen more than ~8–10% of its level (13 → 14.1–14.3) in the last 3–5 minutes unless the *remaining* projected move is ≥ 1.5× the required move. The spike is the market makers' response to the move already made.
3. **Take the gift.** If the premium is up on IV with spot not following, book it; IV spikes mean-revert in minutes.
4. **Default to just-ITM (Δ 0.60–0.70), tie-break on "which strike is already moving".** ITM has lower vega-per-rupee and no charm bleed; and the strike whose asks are being pulled (G3's option-leads-futures tell) is the one market makers expect to run. Caveat he insists on: ITM books are thinner — ITM2 spreads of 1.5–3 pts are common intraday vs 0.5–1 at ATM, paid twice. Measure before adopting.
5. **Stops belong under structure in spot terms, converted to premium**, never a fixed −10 points: −10 is 12.5% of an ₹80 option and 5% of a ₹200 one; it means nothing by itself.
6. **Expiry week:** Monday is "cheap gamma" — ATM is a 75-pt lottery with 20 lots all-in; after Tuesday 13:00 the next-week contract is the better buyer's instrument unless the 0DTE trade is deep enough ITM.

### Farah Khan — the rupee arithmetic
1. **With all-in sizing, strike choice IS position sizing.** Lots ≈ capital/(P×65), so rupees per spot point = Δ×lots×65 ≈ capital × (Δ/P) × utilisation. **Risk per adverse spot point as % of capital ≈ Δ/P × utilisation.** OTM has the highest Δ/P (cheap), deep ITM the lowest. The owner's "ITM, never OTM" rule is, mechanically, a de-leveraging rule — a good one.
2. **Set the stop as a % of capital first, then check it fits the structure.** If the structural stop (spot distance d) costs more than the cap, the instrument is wrong: pick lower Δ/P (ITM or next week) or pass.
3. **The streak table (§5.6)** is the number the owner must look at before the first live order: at MYTHOS's 41% win rate, **48% of 12-trade days contain a run of four losses**.
4. **0DTE ATM all-in is 1.3–1.9% of capital per adverse spot point.** One 20-pt wiggle = 26–38% of the day's capital. This single instrument can end the day in one trade.
5. Book net of STT/charges; a −10 stop that fills at −13 is the normal case, not the exception (MYTHOS's worst recorded stop fill was −29 **[FACT, config comment]**).
6. "Dying to time alone" is minimised by the instrument with the lowest (|Θ| + |V·σ-drift|)/P per minute: next-week ATM/ITM1 or current-week ITM Δ ≥ 0.7.

### Vikram Choudhary — Tuesday
1. **On 0DTE only buy Δ ≥ 0.65 (ITM1–2); no new 0DTE entries after ~14:45; flatten 0DTE by ~15:00 unless Δ ≥ 0.9.** The last 30–45 minutes are hedge-unwind time: either a hard pin or a violent unpin, and BS Greeks are meaningless (Γ, Θ ∝ 1/√T).
2. **Charm and vanna are the buyer's silent enemies on Tuesday.** Charm: a just-OTM call's Δ decays from 0.30 at 11:00 to 0.23 by 14:00 with spot flat (our table) — you were right on direction and still lost delta. Vanna: 0DTE IV drifts *down* through the day as the priced vol fails to realise; falling IV pulls OTM deltas down and ITM deltas up. Rule: never own OTM into a falling IV; ITM gets vanna working for it.
3. **The expiry-day IV drift is the buyer's hidden theta** — measurable from the recorded frames: ATM IV vs time of day on expiry Tuesdays. It will be larger than BS theta.
4. **Pin detection**: spot within ~20 pts of the max-|gamma×OI| strike for > ~60–90 min, OI there *rising*, straddle *compressing* → PIN state; a long option in a pin stalls. Approve a BUY in a pin only with G3's BREAK-IMMINENT verdict and OI at the wall *falling*.

---

## 4. The debate

**D1 — Theta per minute. The brief's prior (§5.4: 0.3–0.5 pt/min morning, 1–1.5 pt/min afternoon in expiry week) is 3–10× too high for ATM at Nifty 23,000.** Computed [ANALYSIS]: 6-day ATM (prem 166) 0.033 pt per trading minute; Monday of expiry week (prem 75) 0.08; expiry Tuesday 11:00 (prem 38, IV 18%) 0.07; 14:00 (prem 27, IV 22%) 0.15; 15:00 ≈ 0.25. Over a 5-minute hold: 0.2–1.3 pts. Marco and Vikram: the owner's *felt* bleed is real but it is IV drift + spread, not theta. **Decided:** theta stays in the cost formula (it is the floor of the bleed), but the stall rule is not built on it; the vega term is. **Evidence that settles it:** on the recorded frames, the realised decay of the ATM straddle in windows where |Δspot| < 5 pts over 10 minutes, bucketed by DTE and time of day — this gives empirical theta+IV-drift per minute, which the engine will then use as a multiplier on BS theta.

**D2 — Default strike.** Marco: just-ITM. Rao/Farah: on a 6-day contract ATM vs ITM1 is a wash in rupees (7.8% vs 6.6% of capital for a 25-pt move) and the ITM spread may cost the difference; on 1 DTE and 0DTE the ITM case is overwhelming (risk per point halves). Vikram: 0DTE ITM only. **Decided:** a DTE-dependent delta band (§5.3), spread-aware, with "which strike is already moving" as tie-break. **Evidence:** the recorder's measured spreads at ITM1/ITM2 at the moment of triggers, and the backtest's net ₹ per trigger by strike.

**D3 — Gamma/theta score.** Rao: degenerate across strikes (identity in §3). Chair checked the arithmetic; agreed. **Decided:** replaced by the speed ratio ρ = M_proj/M_be (§5.4b). The charter's item is answered by saying it is the wrong question.

**D4 — Dealer gamma sign.** Rao: the US convention (call OI = dealers long gamma, put OI = dealers short) rests on US customer behaviour (overwriting, put buying). Vikram: Indian retail is net long both CE and PE and the writers are net short both sides, so a signed sum is always negative and says nothing; yet expiry-day pins are routine — because writers *defend* strikes by adding shorts (a mean-reverting flow) and *unwind* when the wall breaks, which is why walls hold until they don't and then accelerate. **Decided:** publish the unsigned profile |Γ_K × OI_K| (where the battleground is), the signed GEX as a labelled **[HYPOTHESIS]** panel, and infer the *effective* local sign from behaviour (OI dynamics at the wall, price response near it, straddle response). GEX is **advisory, not a gate**, until the behavioural sign is validated on the frames (§6).

**D5 — Points vs rupees.** Farah: the +12 target and −10 stop are meaningless across instruments; the engine must think in % of capital and spot points. Marco: the owner thinks in premium points; the card must speak points. **Decided:** internal maths in spot points and % capital; the card shows premium points, spot points and ₹ side by side.

**D6 — Time-based stall exits.** Marco: none — MYTHOS's 163 time kills (45% of exits) are the proof; let the stop and the thesis do the work. Farah: a bleed budget is needed, or a dead trade sits through an IV deflation. Vikram: on 0DTE a stall is lethal. **Decided:** no clock-only kill ever. A stall exit requires both "bleed exceeded" *and* the driver (G1 synchrony / G3 force) gone neutral or reversed; stricter budgets on 0DTE.

**D7 — Does the Greeks engine veto?** Marco: every veto is a way to be late again. Rao/Farah: feasibility and IV-spike vetoes stop the two worst buyer mistakes. **Decided:** **advisory first** (shows a would-be verdict on every trigger), veto rights only for LATE and IV-SPIKE after the pre-registered bar (§6), never a "wait for more evidence" veto. The instrument selector (which strike/expiry) is live from day one because it does not delay anything.

---

## 5. Consensus proposal

### 5.1 What the subsystem is
A **Greeks & Instrument service** — one analytics worker on the tick stream — that maintains, continuously and with age stamps: the forward, the IV surface for all subscribed Nifty strikes (this week; next week from Monday of expiry week), per-contract Greeks for the ten hero contracts at tick cadence, realised-vol and implied-move estimates, the gamma/OI profile and regime label, and for an open position the live P&L attribution. At a BUY trigger it produces a **trigger card** (instrument, size, feasibility, lateness, IV state, regime, exit plan) in under a few milliseconds from state it already holds — it never fetches anything at trigger time.

### 5.2 A day in its life
**08:55 preflight.** Loads this week's (and from Monday of expiry week, next week's) contract codes, confirms expiry = Tuesday 20 Oct is a holiday → **Mon 19 Oct is expiry this week [FACT, brief §2.2]**, sets the 15:30 expiry clock, loads the empirical theta multiplier table (§6). **09:15–09:20.** Forward from ATM parity as soon as both ATM contracts quote; IV surface at 4 Hz; the first "implied 5-minute move" shows on screen (e.g. 9.2 pts at 13%). **10:42:10** G1 reports stage-2: synchronous weighted impulse up, projected +32 pts at ~6 pts/min, confidence 0.7, move done since t0 = 6 pts. G3 reports BREAK-IMMINENT on 23,050 CE asks, VACUUM forming. The engine evaluates (§5.5), picks 23,000 CE this week (Δ 0.52, 9 lots) over 22,950 CE (Δ 0.57, 7 lots, spread 1.6), prints the card: required move 25.1 pts vs remaining projected 26 (ρ = 1.04 → **marginal**), IV +2% in 5 min (fresh), skew unchanged, regime NEUTRAL, stop at spot 23,015 → premium −9 (≈ 8.4% of capital), take-zone +11–14 pts, budget W = 5 min, verdict **APPROVE-MARGINAL**. G6 places the limit at ask. **10:44–10:47** attribution shows Δ-term +9, vega −3 (IV deflating as the move pauses), spot stalling 8 pts below projection, G1 synchrony fading → the "move happened, IV deflated" rule fires at +6 net; exit at bid. **13:05** 0DTE-style logic is not active (not expiry day); **on Monday 19 Oct** the whole afternoon runs under the expiry-day profile: ITM-only, next-week preferred after 13:00, no 0DTE entries after 14:45.

### 5.3 The engine — specification
**Inputs (from shared memory, G5):** per subscribed option: bid, ask, bid/ask qty, LTP, ltq, ttq, OI, exchange time, receive time; Nifty futures bid/ask/LTP; spot; VIX (1/min); REST chain OI snapshot (90 s); contract metadata (strike, right, expiry); the clock.

**Forward:** F_syn as in §3-Rao-1, EWMA half-life 1 s. **Time:** T = seconds to 15:30 IST on expiry / (365×86,400); floor 600 s on expiry day, 60 s otherwise. **Rate:** r = 6.5% for discounting only; dividend 0.

**IV solver:** vectorised bisection over all strikes of one expiry and right in one numpy pass (34 strikes × 20 iterations ≈ 680 vectorised price evaluations ≈ < 1 ms); mid price; validity = mid > forward-intrinsic + 0.05 and book not crossed; bracket [0.01, 3.0] (expiry day [0.01, 5.0]); deep-ITM fallback: |Δ| set by intrinsic (0.98–0.99), extrinsic Greeks zero, flagged NO-INFO when extrinsic < 0.5 pt; IV uncertainty band ±(spread/2)/vega.

**Outputs per contract:** IV ± band; Δ; Γ (and "pts per 25-pt move" = 25Δ + 312.5Γ); Θ per trading minute = Θ_day/375 off-expiry, Θ_day/1440 on expiry day (all remaining decay is inside the session), × empirical multiplier; Vega per vol point; charm per hour; vanna per vol point; elasticity Δ/P; risk-per-point = Δ/P × utilisation. **Surface outputs:** ATM IV, straddle, implied 1σ move for H = 3/5/10/15 min, skew = IV(ATM−100 PE) − IV(ATM+100 CE), term spread (this week − next week ATM IV), ΔIV over 1/3/5/15 min for ATM and each hero. **Realised:** RV from 1-s futures mid returns over 5/15/30 min, annualised; move speed v = pts/min over 1 and 3 min. **GEX:** per strike g_K = Γ_K × OI_K × 65 × F² × 0.01 (₹ gamma per 1% move — OI units must be confirmed with G5: Breeze may report quantity rather than contracts), unsigned profile, US-convention signed sum (labelled hypothesis), max-|g| strike, flip strike, regime label.

**Cadence:** surface pass 4 Hz (every 250 ms) for both expiries; hero pass event-driven on each hero or forward tick, conflated to ≤ 20 Hz per contract (Newton from the last IV, bisection fallback); GEX/regime 1 Hz (tick OI on ATM±8 from the WS, chain OI beyond that from REST); attribution per tick for the open position. CPU: ~1 ms per surface pass + microseconds per hero update — well under 2% of one core. Every output carries its timestamp; the trigger card treats anything older than 2 s as UNKNOWN (an unknown never approves, and never vetoes either — it says UNKNOWN).

**Other pitfalls handled:** crossed books after a burst (IV invalid, not wrong); the VIX 100× bug **[FACT, brief]** — VIX is display-only, never a solver input; locale-safe expiry strings **[FACT, brief]**.

### 5.4 The BUY-trigger decision set
Inputs at trigger from G1: direction, projected total move M_proj (spot pts), projected speed v_proj (pts/min), confidence c, trigger time t0, move done since t0 M_done. From G3: force verdict at the relevant level (HOLD-STRONG / BREAK-IMMINENT / VACUUM / FAKE), option-leads-futures tell per hero. From G2: nearest walls/zones above and below.

**(a) Feasibility.** For each candidate contract, required spot move M_req solves Δ·M + ½Γ·M² = target_pts + |Θ_min|·H + spread + slip, with H = clamp(M_proj / v_proj, 2, 10) min, slip = 1 tick each side. Remaining projection M_rem = M_proj − M_done. Pass if M_rem ≥ κ·M_req, **κ ∈ [1.2, 1.5] [HYPOTHESIS]**; marginal if 1.0 ≤ ratio < κ. Card: "needs 25 · projected 26 remaining · ratio 1.04 — MARGINAL". Worked numbers (6-day, 13%): +12 needs 25.1 pts at ATM, 22.9 at ITM1, 18.3 at ITM4, 31.2 at OTM2; on Monday (1 DTE) 26.3 / 21.7 / 15.2 / 44.2; on expiry Tuesday 11:00 26.5 / 18.8 / 13.2 / 90.5.

**(b) Speed vs rent — the speed ratio (replaces Γ/Θ).** ρ = M_rem / M_be, M_be = F·σ_K·√(H/525,600) — the implied one-sigma move for the hold at the *candidate's own* IV. At 13%: M_be = 9.2 (5 min), 13.0 (10 min); at 22%: 15.6 / 22.1. A +12 ATM target in 5 minutes is a 2.7σ event at implied vol — which is exactly what G1 claims to see; if ρ < 1 the market's own vol says the move will not pay the rent. **Thresholds [HYPOTHESIS]:** ρ ≥ 1.5 strong, 1.0–1.5 marginal, < 1.0 refuse. Card: "projected 26 vs 1σ 9.2 (ρ 2.8)".

**(c) Theta time budget → stall rule (bleed exceeded).** Bleed(t) = |Θ_min|·t·m_emp + max(0, spread_now − spread_entry)/2, with m_emp the measured multiplier (expected ~1 off-expiry, 2–4 on expiry afternoons [HYPOTHESIS]). At t = W (the projected completion window, = H above): if P&L_net < Bleed(W) **and** the G1/G3 driver state is NEUTRAL or REVERSED → exit "STALL — bleed exceeded, driver dead". If the driver is still LIVE → extend once by W/2. On 0DTE after 13:00, W is capped at 4 min and no extension. There is **no exit for time alone while the driver is alive**.

**(d) IV-richness veto (LATE / PRICED).** Four tests, each shown, any two → LATE [HYPOTHESIS, ranges in brackets]:
- ΔIV_5min of the candidate ≥ [8–12]% of its level (13 → 14.0–14.6);
- IV_K / RV_15m ≥ [1.4–1.8] **and** RV_15m rising (the market already repriced the realised burst);
- straddle-implied move to expiry has grown by ≥ [15–25]% in the last 10 min;
- skew tilt toward our side (for a PE buy: put IV − call IV up by ≥ [1.0–1.5] vol pts in 15 min) = "already positioned".
Pass-with-ITM: if only the ΔIV test trips, the engine prefers the ITM1–2 strike (lower vega/P) rather than vetoing. Card: "IV 13.4% (+1.9% in 5m) · IV/RV 1.2 · skew flat · straddle +6% — FRESH".

**(e) GEX regime gate.** Sign assumption, stated: *US convention* = dealers long calls / short puts; *Indian hypothesis* = hedgers short both sides, walls defended by fresh writing, broken walls unwound. Weakness of any OI-based sign: OI is a net count with no initiator, and 90-s REST OI is coarse (tick OI on ATM±8 from the WS fixes this near the money). The engine therefore labels the regime from **behaviour at the nearest wall on our side**: OI_wall rising over 5–15 min + price absorbed on approach (negative 30-s autocorrelation) + straddle compressing → **PIN**; OI_wall falling + price response positive + straddle expanding → **ACCELERATE**; else NEUTRAL. In PIN: approve only with G3 BREAK-IMMINENT or VACUUM; in ACCELERATE: a synchronous trigger is enough; the signed GEX panel is displayed for the owner's eye and logged for validation. **[HYPOTHESIS]** thresholds: wall = OI ≥ 2× median of ATM±8; pin distance ≤ 20 pts; dwell ≥ 60 min.

### 5.5 Instrument selection
Candidates: this week's strikes with |Δ| in the DTE band below; from Monday of expiry week also next week's ATM/ITM1; filter: spread ≤ max(1.0 pt, 1.2% of mid) [HYPOTHESIS], mid ∈ [40, 400], book not crossed, both expiries' codes pre-resolved. **Score** = Δ/P efficiency within the risk cap − spread cost − vega/P penalty × ΔIV-flag − charm/vanna penalty (0DTE OTM-ward) + "already moving" bonus (G3 tell). Tie-break toward the money.

**Delta bands [HYPOTHESIS, DTE-dependent]:** ≥ 3 DTE: 0.52–0.70 (ATM to ITM2); 1–2 DTE: 0.60–0.80; 0DTE before 13:00: 0.65–0.85 (ITM1–3); 0DTE after 13:00: next-week 0.52–0.65 preferred, 0DTE only if Δ ≥ 0.8 and the structural stop fits the cap; 0DTE after 14:45: none.

**The lot-count effect — a 25-pt favourable Nifty move, ₹1,00,000 all-in, 5-min hold, our pricer [ANALYSIS]:**

| Scenario | Strike | Prem | Δ | Lots | Pts | ₹ | % cap | % cap per adverse pt |
|---|---|---|---|---|---|---|---|---|
| 6 DTE, IV 13% | 22,800 CE (ITM4) | 289 | 0.72 | 5 | +18.1 | 5,871 | 5.9 | 0.23 |
| | 22,900 CE (ITM2) | 223 | 0.62 | 6 | +15.8 | 6,145 | 6.1 | 0.24 |
| | 23,000 CE (ATM) | 166 | 0.52 | 9 | +13.3 | 7,752 | 7.8 | 0.31 |
| | 23,100 CE (OTM2) | 119 | 0.42 | 12 | +10.7 | 8,352 | 8.4 | 0.33 |
| | 23,200 CE (OTM4) | 82 | 0.33 | 18 | +8.3 | 9,698 | 9.7 | 0.38 |
| 1 DTE (Mon), IV 14% | 22,900 CE | 137 | 0.72 | 11 | +18.1 | 12,956 | 13.0 | 0.51 |
| | 23,000 CE | 75 | 0.51 | 20 | +13.0 | 16,926 | 16.9 | 0.66 |
| | 23,100 CE | 35 | 0.30 | 43 | +7.8 | 21,788 | 21.8 | 0.85 |
| 0DTE 11:00, IV 18% | 22,900 CE | 107 | 0.86 | 14 | +22.0 | 20,047 | 20.0 | 0.78 |
| | 23,000 CE | 38 | 0.50 | 40 | +13.6 | 35,278 | 35.3 | 1.31 |
| | 23,050 CE | 18 | 0.30 | 86 | +8.4 | 46,750 | 46.7 | 1.68 |
| 0DTE 14:00, IV 22% | 23,000 CE | 27 | 0.50 | 58 | +13.7 | 51,629 | 51.6 | 1.89 |
| same morning, NEXT week | 23,000 CE (7 DTE) | 180 | 0.53 | 8 | +13.3 | 6,909 | 6.9 | 0.27 |

Reading it: **(1)** the cheaper the option, the more rupees the same move makes *and* the more it loses per adverse point — all-in sizing makes OTM the most leveraged bet, not ITM; "more delta per lot" is true, "more delta in rupees" is false. **(2)** "+12 premium points" is not one objective: it is 7.8% of capital at a 6-day ATM and 35% at a 0DTE ATM. The engine's targets and stops are in **% of capital and spot points**; the card translates to premium points. **(3)** On expiry day the ATM all-in buyer is risking 1.3–1.9% of capital per spot point against him — the owner's own warning, in numbers. **(4)** Next week's contract on expiry day gives one-fifth of the rupees of the 0DTE ATM for the same move, and one-fifth of the risk; it is the instrument when the structural stop cannot fit the risk cap.

**Monday/Tuesday of expiry week (this week: Friday 16 → Monday 19 is expiry):** Monday profile = 1 DTE: ATM is 20 lots of a 75-pt contract with 0.66%/pt risk; use ITM1–2 (Δ 0.6–0.8); from 13:00 on expiry day the 0DTE rules in §3-Vikram apply.

**The owner's history and the resume-brain finding.** *Agree* with "ATM or ITM that MOVES, never OTM" — for a buyer with all-in sizing it is simultaneously the lower-risk, lower-vega, no-charm choice, and "MOVES" becomes a measured input (G3's tell) rather than a feeling. *Refute* Δ≈1 (ATM∓200) as the default for this system: that result **[FACT, resume brain, in-sample, 14 days, "marginal/screening-level"]** came from multi-hour holds where theta over hours and a 10-pt-spot stop under a real swing low did the work; in a 5-minute hold Δ≈1 gives the fewest rupees for the move (5.9% vs 7.8% at 6 DTE; 11% vs 35% on 0DTE), 5–7 lots waste 6–9% of capital to lot granularity (utilisation 91–94%), and 200–300-pt contracts carry the widest spreads. The transferable part of the finding is "don't let theta/vega eat a correct view" — which our bands do with Δ 0.6–0.85 on expiry week, not 0.99.

### 5.6 All-in compounding — the arithmetic, for the owner's decision
Stops as % of capital (lot 65, all-in; utilisation in brackets): **P = 80 (19 lots, 98.8%)**: −8 → ₹9,880 = 9.9%; −10 → ₹12,350 = 12.3%; −15 → ₹18,525 = 18.5%. **P = 120 (12 lots, 93.6%)**: 6.2% / 7.8% / 11.7%. **P = 200 (7 lots, 91%)**: 3.6% / 4.5% / 6.8%. **P = 35, 0DTE ATM (43 lots)**: −10 → ₹27,950 = **28%**.
Capital left after consecutive stops at −10: P = 80: 3 → 67%, 4 → 59%, 5 → 52%. P = 120: 78% / 72% / 67%. P = 200: 87% / 83% / 79%. P = 35: 37% / 27% / 19%.
Probability that a 12-trade day contains ≥ 4 consecutive losses (i.i.d.): **41% win rate: 48%** (≥ 3: 76%; ≥ 5: 27%); **55%: 21.5%** (≥ 3: 48%; ≥ 5: 9%); 60%: 14.5%. An 8-trade day: 32% / 13%.
Upside: three +12 wins re-sized all-in: P = 80 → ₹1,51,480 (+51.5%); P = 120 → ₹1,31,980 (+32%); P = 200 → ₹1,17,940 (+18%). A 12-trade day at MYTHOS's measured +4.3/−4.7/41% at P = 120 → ₹90,906 (−9.1%) — the compounding cuts both ways, and with those statistics it only amplifies the bleed.
Instruments that reduce dying to time alone: lowest (|Θ| + vega-drift)/P per minute → next-week ATM/ITM1 (0.03 pt/min on 166–180, vega 12 but IV moves of 1-DTE/0DTE size do not occur there), then current-week ITM Δ ≥ 0.7. Worst: 0DTE ATM/OTM after 13:00.
**Farah's note, not a rule:** a risk cap of 6–8% of capital per trade [HYPOTHESIS] keeps a 4-loss run at −22 to −28% and is compatible with all-in sizing *because strike choice sets the cap*: at ATM 6 DTE it allows a 20–26-pt spot stop; at 0DTE ATM it allows 3–6 pts — which is the engine's way of saying "not that contract". The daily stop and whether a cap exists at all are the owner's call (brief §6 Q4).

### 5.7 Exit geometry proposal (the old −10/+12 is not assumed)
- **Stop** = structural first: the trigger level or broken wall re-crossed by a buffer b = max(8 pts, 0.5×ATR_1m) [HYPOTHESIS 6–12] in spot terms; converted to a premium stop via Δ (and re-converted as Δ changes); executed on the bid as a limit (G6). Cap: premium stop ≤ 6–8% of capital [HYPOTHESIS]; if the structural stop exceeds the cap → lower Δ/P instrument; if none → no trade.
- **Take-zone**, not a fixed target: 0.6–0.7 × M_proj in spot terms [HYPOTHESIS], converted with Δ and Γ; minimum reward:risk at the gate 1.5 [HYPOTHESIS 1.3–2.0], else no trade.
- **Trail** arms only at **+1R** (P&L ≥ initial risk) [HYPOTHESIS 0.8–1.2R]; it trails the *futures path*, not the premium: width = max(0.6×ATR_1m_spot, 8 pts) [HYPOTHESIS], converted to a premium stop each tick — IV flicker and spread bounce cannot stop us out; only the underlying can.
- **Thesis-void exit** (replaces every MYTHOS time kill): the driver that fired reverses — synchrony flips sign, the wall refills (G3 ρ ≥ 1), futures CVD flips — exit at the next bid regardless of P&L. This is "ruthless early" keyed on evidence, in seconds, not on a clock.
- **Bleed-exceeded stall** (§5.4c): bleed > P&L at t = W *and* driver dead.
- **Vega rules** from attribution: *move happened, IV deflated* — Δ-term ≥ 0.7× its expected value for the spot move made, vega-term ≤ −0.3× Δ-term, G1 continuation weak → exit at the next bid (do not wait for spot to give it back). *Vega windfall* — vega-term ≥ 60% of P&L and ≥ 0.5R with spot not following → book it.
- **Expiry-day overlay**: W capped at 4 min after 13:00, 0DTE flat by 15:00 unless Δ ≥ 0.9, no 0DTE entries after 14:45.
- **What there is not**: no floor at +3, no breakeven ratchet, no 4-minute kill, no "book ≥ +1 at 3 minutes". **[FACT, config.py 344–351 and 905–930; trader.py `_check_one` 704–731 and 814–817]** MYTHOS armed a ratchet-only floor the moment peak profit reached +3 (floor = entry + 0, i.e. breakeven), interpolating to entry+1.5 at peak +6, entry+3.5 at peak +8 and the lock at peak +14 (`TRAIL_ACTIVATE = 14`; `TRAIL_INITIAL_LOCK` left at a 7.5-point *test* value, not the +12 the doctrine header claims); separately it killed any trade at 240 s whose peak was below +5 (`BROWNIE_KILL_3MIN_S = 240`, `_PEAK = 5`), put a trade into "book ≥ +1 / scratch if negative" mode at 180 s below a +6 peak (`BROWNIE_STALL_BOOK_S = 180`), and had a "POINTS FADED" exit on top. With a median peak of +3.1 **[FACT]**, that machinery converted most correct entries into +0 to +4 exits (132 ramp-floor exits averaging +3.8; 163 time-based exits, 45% of all). The only pre-1R exits in our proposal are evidence exits. Between the stop and 1R the trade is left alone.

### 5.8 Trigger card (what the owner sees)
Instrument chosen + runner-up + next-week alternative, each with mid/spread/Δ/lots/₹-per-point · required vs remaining-projected move (bar) and ratio · ρ speed ratio · lateness M_done/M_proj · IV, ΔIV 5m, IV/RV, skew tilt, straddle change → FRESH/RICH/LATE · regime PIN/NEUTRAL/ACCELERATE with nearest wall (strike, OI, ΔOI 5m, distance) · the exit plan (stop in spot and premium and % capital, take-zone, W, bleed budget) · verdict APPROVE / APPROVE-ITM / MARGINAL / LATE / PRICED / UNKNOWN, with the one line that decided it · age of every input.

Pseudo-code of the evaluation:
```
on_trigger(dir, M_proj, v_proj, c, t0, M_done, force, tell):
  H = clamp(M_proj / v_proj, 2, 10); M_rem = M_proj - M_done
  if M_done / M_proj > L_max: return LATE("move 40% done")           # L_max in [0.3,0.5]
  cands = strikes(dir, dte_band(now), spread_ok, both_expiries_if_expiry_week)
  for k in cands:
      g = greeks[k]; M_req = solve(g.delta*M + .5*g.gamma*M^2 = target(k) + g.theta_min*H*m_emp + spread + slip)
      ratio = M_rem / M_req; rho = M_rem / (F*g.iv*sqrt(H/525600))
      stop_pts = structural_stop(dir) ; stop_prem = g.delta*stop_pts + slip
      if stop_prem*lots(k)*65 > cap*capital: continue                 # instrument too hot
      score(k) = f(ratio, rho, Δ/P, spread, vega_pen(ΔIV_5m), charm_pen, tell_bonus)
  best = argmax(score); if none: return NO_INSTRUMENT
  iv_state = richness_tests(best); regime = regime_at_wall(dir)
  if iv_state == LATE and ratio(best) < 1.5: return PRICED
  if regime == PIN and force not in (BREAK_IMMINENT, VACUUM): return WAIT_PIN   # advisory until validated
  return APPROVE(best, plan(stop, take_zone, W, bleed))
```

### 5.9 Data flow and interfaces (summary; detail in §8)
Shared-memory rows (G5) → Greeks worker (4 Hz surface, per-tick heroes, 1 Hz regime) → shared-memory "greeks" rows + ZMQ events (IV-SPIKE, REGIME-CHANGE, UNRELIABLE) → trigger card builder (consumes G1/G2/G3 state) → G6 executor (instrument, lots, limit, stop plan) → fills back → attribution per tick → exit events to G6 → recorder logs every card and every attribution frame.

---

## 6. Validation plan

**On the recorded frames (`mythos.db`, 1–2 s, near-ATM ltp/bid/ask/OI, futures, VIX, chain OI/90 s) [FACT available].**
1. *Engine correctness*: recompute IV/Greeks on every frame; check put–call parity residuals (|F_syn − F_fut| distribution), IV continuity, deep-ITM fallback frequency, expiry-day blow-ups.
2. *Empirical theta/IV-drift table*: ATM straddle decay in 10-min windows with |Δspot| < 5 pts, by DTE × hour → m_emp. Settles D1.
3. *Vega mechanism*: for every ≥ 20-pt spot burst, how much of the premium change over the next 5 minutes is IV (attribution on frames); the frequency and size of "IV spike then deflate within 5 min" — the owner's pullback hypothesis, quantified.
4. *Gate backtest*: G1/G3 produce a trigger log on the frames; for each trigger and each candidate instrument compute honest-fill MFE/MAE at 3/5/10 min; evaluate each rule (feasibility, ρ, IV-richness, regime, lateness) as a filter: net points per trigger with and without; **recall check** — fraction of top-quartile-MFE triggers each rule vetoes (strangling test); leave-one-day-out; concentration.
5. *Instrument selector*: net ₹ per trigger by strike band and by this-week vs next-week on expiry week, with recorded spreads.
6. *Regime sign*: does PIN/ACCELERATE (behavioural) predict absorption vs continuation at walls better than the signed-GEX convention? Settles D4.
Limits: no depth and intra-frame order lost → spread *at the moment of the move* is unknown; 90-s chain OI beyond ATM±8.

**Tick recorder must capture (G5):** all ten hero contracts and ATM±8 both rights with bid/ask/qty, LTP/ltq/ttq, OI, exchange `ltt` and receive time, 5-level depth with order counts on the heroes and Nifty futures; next-week's ATM±2 from Monday of expiry week; spot; VIX; REST chain snapshots; **and the engine's own outputs** (forward, IV surface, hero Greeks, regime, every trigger card, every attribution frame) with their timestamps — so a replay reproduces exactly what the live system saw, and a "would-have" verdict is logged on every trigger from day one.

**Pre-registered bar before the Greeks gate may veto or approve a real order [HYPOTHESIS, to be fixed with G7 before any live session]:** over ≥ 20 recorded sessions plus ≥ 10 forward shadow sessions at live cadence: each veto rule improves net honest points per trigger by ≥ 1.5 pts (or is dropped); vetoes ≤ 25% of top-quartile winners; leave-one-day-out positive; no single day carries > 40% of the improvement; the selector beats "always ATM" on net ₹ per trigger. Until then: instrument selection and the exit plan are live (they delay nothing), LATE/PRICED verdicts are **shown** but orders go through, GEX is advisory. The owner's past pattern **[FACT, KILL_CRITERION]** — "six full rebuilds, each shipped live unproven" — is the reason this bar is written now.

---

## 7. Risks and failure modes

1. **Being late with confidence.** A feasibility gate fed a *trailing* projection (extrapolating the last 60 s) passes only after the move; mitigated by requiring G1's projection to come from stage-1/2 state, by the lateness test M_done/M_proj, and by the recall check in §6. If G1 cannot produce a forward projection with a stated confidence, the feasibility gate must be advisory only.
2. **Vetoes that strangle.** Any IV-richness veto will reject some of the best moves (IV rises *because* the move is real). The 25%-recall bar and "pass-with-ITM instead of veto" exist for this.
3. **Wrong sign on GEX** presented as knowledge. Kept unsigned/behavioural and advisory.
4. **Spread at the moment of the move.** Market makers widen on bursts; our ITM preference may pay 2–3 pts twice; unknown until the recorder measures it. Hard fallback: spread filter at trigger time, and the limit-pricing policy is G6's.
5. **Model risk near expiry**: BS Greeks are fiction in the last 30–45 min of expiry day; the UNRELIABLE flag and the 14:45/15:00 rules are the guard — if the owner trades those minutes by hand, the engine must say "no opinion", not a number.
6. **Stale inputs looking alive** **[FACT, brief]** (frozen REST chain, dead session): every output carries age; UNKNOWN never approves.
7. **Buyer-only losses with spot not against us, and what the system does:** *theta* — costed in M_req and the bleed budget; *IV deflation after a spike* — ΔIV veto at trigger, attribution exit during hold; *spread widening at the move* — spread filter at trigger, trail on the futures path so a wide bid does not read as a loss, limits not markets (G6); *pin at a wall* — regime PIN demands G3 BREAK-IMMINENT, take-zone set below the next wall; *charm into expiry* — ITM-only bands on 0DTE, charm penalty in the score; *vol crush after an event* (RBI 10:00 on policy days, monthly expiry, index rebalances) — event calendar from G5 marks the window, IV percentile shown, PRICED verdict weight doubled in the window [HYPOTHESIS]; *gap-through of the stop* — sized by the cap, not by the stop (a −10 stop that fills at −29 is in the arithmetic); *lot granularity* — utilisation shown on the card.
8. **False precision.** The thresholds here are starting ranges. Shipping them as facts is the MYTHOS failure; every number in §5 is tagged HYPOTHESIS for that reason.

---

## 8. Interfaces

- **From G1 (domino/lag):** at trigger — direction, M_proj, v_proj, confidence, t0, M_done, continuation state during the hold (LIVE/NEUTRAL/REVERSED), event flags. **To G1:** implied 1σ move surface (what the market has priced for 3/5/10 min), IV-SPIKE and PRICED events, the premium-lag measurement (option mid vs Δ×futures move, per hero, per tick — the "last domino" latency G1 wants).
- **From G2 (pressure zones):** nearest walls/zones above and below with strength and OI dynamics. **To G2:** per-strike gamma×OI profile, flip strike, skew and term spread as pressure inputs, regime label.
- **From G3 (force & flow):** force verdict at the level, option-leads-futures tell per hero, replenishment ρ at the wall. **To G3:** Δ per hero so premium velocity can be normalised to implied futures velocity (a contract moving faster than Δ×futures = IV/positioning driven, not price driven).
- **From G5 (data):** the shared-memory rows and fields listed in §5.3 and §6, tick OI on ATM±8 (confirm per tick), depth on heroes, next-week subscriptions from Monday of expiry week, contract codes for both expiries pre-resolved, OI units (contracts vs quantity), an event calendar, one analytics-worker slot (~2% core), recorder fields. **To G5:** the engine's output schema with timestamps.
- **From G6 (execution/risk):** fills (price, qty, time), working-order state, the owner's decisions on risk cap and daily stop, freeze-quantity slicing. **To G6:** instrument, lots, reference ask and a suggested limit, stop plan (spot level, premium level, % capital), take-zone, W, exit events (THESIS-VOID, STALL, VEGA-DEFLATED, WINDFALL, EXPIRY-FLAT) each with the reason string for the "why".
- **To G7 (red team):** the pre-registered bar, the recall metric, the GEX sign study design, the m_emp table.

---

## 9. Open questions for the owner

1. Risk cap per trade as % of capital (we assume 6–8% for the exit geometry) and whether any daily stop exists — the streak table in §5.6 is the input.
2. On expiry day after 13:00, do you want the system to prefer next week's contract (fewer rupees, far less risk) or 0DTE ITM (Δ ≥ 0.8) — or both offered on the card with you choosing?
3. Do you accept targets/stops expressed in % of capital and spot points internally, with premium points shown on the card, instead of a fixed +12/−10?
4. Should the IV-richness verdict ever veto an order, or only colour the card? (We propose advisory until the bar in §6 is met.)
5. May the recorded MYTHOS frames be used for the theta/IV-drift and GEX-sign studies (assumed yes)?

---

## 10. One-paragraph summary for the master design

G4 specifies a Greeks & Instrument service that prices every subscribed Nifty strike on the synthetic forward (Black-76, mid-price IV by vectorised bisection, 4 Hz surface, per-tick hero Greeks, 1 Hz gamma/OI regime), rewriting MYTHOS's greeks.py rather than reusing it (spot-based intrinsic bug, calendar theta, no attribution). At a BUY trigger it selects the contract (DTE-dependent delta bands: ATM–ITM2 far from expiry, ITM1–3 on expiry week, next week after 13:00 on expiry day; spread-filtered; "already moving" tie-break), tests feasibility as required-vs-remaining projected move, replaces the degenerate gamma/theta score with a speed ratio against the implied one-sigma move, flags IV-spike/skew/straddle richness as LATE/PRICED, and labels the dealer-gamma regime behaviourally because the OI sign is unknowable here. It supplies a Greeks-aware exit plan: structural stop capped in % of capital (which, under all-in sizing, is what strike choice really sets), take-zone from the projection, trail on the futures path from +1R, evidence-only early exits (thesis void, bleed exceeded with a dead driver, IV deflated after the move), and no floors or clock kills below 1R. The arithmetic the owner must see: a −10 stop is 12% of capital at ₹80 and 28% at a 0DTE ₹35; at a 41% win rate half of all 12-trade days contain a four-loss run. Everything numeric is a hypothesis with a pre-registered bar before any veto touches a real order.
